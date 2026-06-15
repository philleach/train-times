"""
OpenLDBSVWS (Live Arrival & Departure Boards, Staff Version) REST client.

Darwin's Push Port doesn't always carry scheduleFormations for the services we
track. LDBSV's GetServiceDetailsByRID returns coach formation for a service
looked up by its RID — which we already have from Darwin — so we use it as a
fallback to fill in coach counts.

Rail Data Marketplace REST API (Swagger): JSON over HTTPS with an x-apikey
header. GET /api/20220120/GetServiceDetailsByRID/{rid} -> ServiceDetails.

Run directly to inspect a real response (key comes from bridge/.env):

    uv run python bridge/ldbsv.py 202606157678623
"""

import json
import logging
import sys

import httpx

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://realtime.nationalrail.co.uk/LDBSVWS"
_API_VERSION = "20220120"


def _coach_counts(coaches: list) -> tuple[int, int]:
    length = len(coaches)
    first = sum(1 for c in coaches
                if str(c.get("coachClass", "")).strip().lower() in ("first", "f"))
    return length, first


def parse_formation(details: dict) -> dict | None:
    """Derive {length, first} from a ServiceDetails document, or None."""
    # formation is an array of per-tiploc LocFormationData; the first non-empty
    # set of coaches is the train as formed at origin.
    coaches: list = []
    for f in details.get("formation") or []:
        if f.get("coaches"):
            coaches = f["coaches"]
            break

    length, first = (_coach_counts(coaches) if coaches else (0, 0))
    if not length:
        # No per-coach detail — fall back to the coach count on a calling point.
        for loc in details.get("locations") or []:
            if loc.get("length"):
                length = loc["length"]
                break
    if not length:
        return None
    return {"length": length, "first": first}


def fetch_service_details(rid: str, key: str, base_url: str = DEFAULT_BASE_URL,
                          timeout: float = 10.0) -> dict:
    url = "%s/api/%s/GetServiceDetailsByRID/%s" % (base_url, _API_VERSION, rid)
    resp = httpx.get(url, headers={"x-apikey": key, "Accept": "application/json"},
                     timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def formation_for_rid(rid: str, key: str, base_url: str = DEFAULT_BASE_URL) -> dict | None:
    """Return {length, first} for a RID via LDBSV, or None on any failure."""
    if not key:
        return None
    try:
        return parse_formation(fetch_service_details(rid, key, base_url))
    except Exception as exc:  # network, HTTP, auth — never break the caller
        log.warning("LDBSV lookup failed for %s: %s", rid, exc)
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    import config  # noqa: E402  (bridge/ is on sys.path[0]; loads .env)

    if len(sys.argv) < 2:
        print("usage: python bridge/ldbsv.py <rid>")
        raise SystemExit(2)
    rid = sys.argv[1]
    key = getattr(config, "LDBSV_KEY", "")
    base_url = getattr(config, "LDBSV_BASE_URL", DEFAULT_BASE_URL)
    if not key:
        print("No LDBSV_KEY set in bridge/.env")
        raise SystemExit(2)

    details = fetch_service_details(rid, key, base_url)
    print("=== formation ===")
    print(json.dumps(details.get("formation"), indent=2))
    print("=== locations[].length ===")
    print([loc.get("length") for loc in details.get("locations") or []])
    print("=== PARSED ===")
    print(parse_formation(details))
