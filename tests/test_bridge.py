import importlib.util
import json
import os
import sys

import pytest

# bridge/config.py reads these at import time; set dummy values so we can
# import the bridge without a real .env.
for _k in ("KAFKA_API_KEY", "KAFKA_API_SECRET", "MQTT_HOST", "MQTT_USER", "MQTT_PASSWORD"):
    os.environ.setdefault(_k, "test")

# bridge.py uses bare `import config` / `from darwin import ...`, so bridge/ must
# be on the path (as it is in production). We load bridge.py under a distinct
# name so it doesn't shadow the `bridge` namespace package other tests import.
_BRIDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "bridge")
sys.path.append(_BRIDGE_DIR)
from darwin import FARNHAM, WATRLMN  # noqa: E402

_spec = importlib.util.spec_from_file_location("bridge_app", os.path.join(_BRIDGE_DIR, "bridge.py"))
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)


class FakeMQTT:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, retain=False):
        self.published.append((topic, payload, retain))


@pytest.fixture
def now_fixed(monkeypatch):
    # Pin "now" to 14:00 so a 14:32 departure is always upcoming.
    monkeypatch.setattr(br, "_now_mins", lambda: 14 * 60)


def _direction():
    return br.Direction("WAT→FNH", WATRLMN, FARNHAM, "trains/WAT/FNH")


def _sf_pport(rid, coaches):
    return {"uR": {"scheduleFormations": {
        "rid": rid, "formation": {"fid": rid + "-1", "coaches": {"coach": coaches}}}}}


def _schedule_pport(rid, std="14:32", pta="15:22"):
    return {"uR": {"schedule": [{
        "rid": rid, "OR": {"tpl": WATRLMN, "ptd": std}, "IP": [{"tpl": FARNHAM, "pta": pta}]}]}}


def _coaches(n, first=0):
    return [{"coachNumber": str(i),
             "coachClass": "First" if i <= first else "Standard"} for i in range(1, n + 1)]


def test_formation_before_schedule_is_applied(now_fixed):
    """An SF arriving before the schedule must still reach the published train."""
    d = _direction()
    mq = FakeMQTT()

    # Formation arrives first — rid is unknown, nothing to publish yet.
    d.handle_formation(_sf_pport("r1", _coaches(8, first=2)), mq)
    assert "r1" not in d.state
    assert d.formation["r1"] == {"length": 8, "first": 2}

    # Schedule arrives later — the cached formation is merged in.
    d.handle_schedules(_schedule_pport("r1"), mq)
    assert d.state["r1"]["length"] == 8
    assert d.state["r1"]["first"] == 2

    # ...and it's in the published payload.
    topic, payload, retain = mq.published[-1]
    trains = json.loads(payload)
    assert trains[0]["length"] == 8


def test_formation_after_schedule_still_applied(now_fixed):
    d = _direction()
    mq = FakeMQTT()
    d.handle_schedules(_schedule_pport("r1"), mq)
    assert "length" not in d.state["r1"]

    d.handle_formation(_sf_pport("r1", _coaches(4)), mq)
    assert d.state["r1"]["length"] == 4
    assert json.loads(mq.published[-1][1])[0]["length"] == 4


def test_cache_is_bounded(now_fixed):
    d = _direction()
    mq = FakeMQTT()
    # Track one real service whose formation must survive eviction.
    d.handle_schedules(_schedule_pport("keep"), mq)
    d.handle_formation(_sf_pport("keep", _coaches(5)), mq)

    for i in range(br._FORMATION_CACHE_MAX + 50):
        d.handle_formation(_sf_pport(f"x{i}", _coaches(4)), mq)

    assert len(d.formation) <= br._FORMATION_CACHE_MAX
    # The tracked service's formation is protected from eviction.
    assert d.formation["keep"]["length"] == 5
    assert d.state["keep"]["length"] == 5
