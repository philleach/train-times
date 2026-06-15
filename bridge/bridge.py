"""
Darwin → MQTT bridge.

Consumes the Darwin JSON/AVRO Kafka topic, filters for WAT→FNH services,
maintains a live state of upcoming departures, and publishes to MQTT
whenever the state changes.

Two Darwin message types are used:
  schedule — identifies which rids call at WAT and FNH (with scheduled times)
  TS       — provides live timing updates for those rids
"""

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

import paho.mqtt.client as mqtt
from confluent_kafka import Consumer, KafkaError, TopicPartition

import config
import ldbsv
from darwin import (
    _SF_KEYS,
    FARNHAM,
    WATRLMN,
    extract_dest_eta,
    extract_formation,
    extract_origin_departure,
    extract_schedules,
    extract_ts_update,
    parse_kafka_value,
)

DEBUG_RAW = os.environ.get("DEBUG_RAW", "").lower() in ("1", "true")

# Formations stream for the whole network; cap the per-direction cache of
# not-yet-confirmed formations so memory can't grow unbounded over a long run.
_FORMATION_CACHE_MAX = 2000

logging.basicConfig(
    level=logging.DEBUG if DEBUG_RAW else logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

def _now_mins() -> int:
    t = time.localtime()
    return t[3] * 60 + t[4]


def _hhmm_to_mins(hhmm: str) -> int:
    try:
        return int(hhmm[:2]) * 60 + int(hhmm[3:5])
    except Exception:
        return 0


class Direction:
    """A single travel direction (e.g. WAT→FNH) with its own state and topic."""

    def __init__(self, name: str, origin: str, dest: str, topic: str,
                 origin_crs: str, dest_crs: str):
        self.name = name          # human label, e.g. "WAT→FNH"
        self.origin = origin      # origin tiploc
        self.dest = dest          # destination tiploc
        self.topic = topic        # MQTT topic
        self.origin_crs = origin_crs  # CRS codes for LDBSV board lookups
        self.dest_crs = dest_crs
        self.known_rids: set[str] = set()    # rids confirmed for this direction
        self.pending: dict[str, dict] = {}   # origin departures awaiting dest confirmation
        self.state: dict[str, dict] = {}     # rid -> train dict
        # rid -> {length, first}. SF messages can arrive before we know the rid
        # (or its schedule), so we cache every formation and apply it when the
        # service is confirmed. Bounded by _FORMATION_CACHE_MAX (see _cache_formation).
        self.formation: dict[str, dict] = {}
        self.last_published: str = ""

    def _prune(self):
        now = _now_mins()
        stale = [
            rid for rid, t in self.state.items()
            if t.get("std") and _hhmm_to_mins(t["std"]) < now - 2
        ]
        for rid in stale:
            del self.state[rid]
            self.known_rids.discard(rid)
            self.formation.pop(rid, None)
            log.debug("[%s] Pruned departed service %s", self.name, rid)
        for rid in [
            rid for rid, t in self.pending.items()
            if t.get("std") and _hhmm_to_mins(t["std"]) < now - 2
        ]:
            del self.pending[rid]

    def _upcoming(self) -> list:
        self._prune()
        return sorted(self.state.values(), key=lambda t: t.get("std", "99:99"))[:6]

    def _cache_formation(self, rid: str, fields: dict):
        """Remember a formation, evicting oldest entries to stay bounded.

        Re-inserting moves the rid to the freshest position; entries for
        services we're actively tracking are kept (their data also lives in
        self.state, so evicting them would be harmless, but skipping them
        keeps the cache useful)."""
        self.formation.pop(rid, None)
        self.formation[rid] = fields
        if len(self.formation) <= _FORMATION_CACHE_MAX:
            return
        for old in list(self.formation):
            if old in self.state:
                continue
            del self.formation[old]
            if len(self.formation) <= _FORMATION_CACHE_MAX:
                break

    def publish(self, mqtt_client: mqtt.Client):
        trains = self._upcoming()
        payload = json.dumps(trains)
        if payload == self.last_published:
            return
        mqtt_client.publish(self.topic, payload, retain=True)
        self.last_published = payload
        n_len = sum(1 for t in trains if t.get("length"))
        log.info("[%s] Published %d trains (%d with coach count)", self.name, len(trains), n_len)

    def handle_schedules(self, pport: dict, mqtt_client: mqtt.Client):
        now = _now_mins()
        for sched in extract_schedules(pport, self.origin, self.dest):
            rid = sched["rid"]
            if rid in self.known_rids:
                continue
            if _hhmm_to_mins(sched["std"]) < now - 2:
                continue  # already departed
            self.known_rids.add(rid)
            self.state[rid] = {
                "rid": rid,
                "std": sched["std"],
                "etd": "On time",
                "platform": None,
                "cancelled": False,
                "eta_dest": sched["pta_dest"],
                **self.formation.get(rid, {}),
            }
            log.info("[%s] %s dep %s arr %s", self.name, rid, sched["std"], sched["pta_dest"])
            self.publish(mqtt_client)

    def handle_ts(self, pport: dict, mqtt_client: mqtt.Client):
        now = _now_mins()

        # Update services we already know about
        update = extract_ts_update(pport, self.known_rids, self.origin, self.dest)
        if update:
            rid = update.pop("rid")
            if rid in self.state:
                prev = dict(self.state[rid])
                self.state[rid].update(update)
                if self.state[rid] != prev:
                    t = self.state[rid]
                    log.info(
                        "[%s] %s  dep %s (%s)  arr %s  plt %s%s",
                        self.name, rid, t["std"], t["etd"], t.get("eta_dest", "?"),
                        t.get("platform", "?"), "  CANC" if t["cancelled"] else "",
                    )
                    self.publish(mqtt_client)

        # Track origin departures for services we don't have a schedule for
        dep = extract_origin_departure(pport, self.origin)
        if dep:
            rid = dep["rid"]
            if rid not in self.known_rids and rid not in self.pending:
                if _hhmm_to_mins(dep["std"]) >= now - 2:
                    self.pending[rid] = dep
                    log.debug("[%s] Pending departure: %s dep %s", self.name, rid, dep["std"])

        # Confirm pending services when the destination appears
        eta = extract_dest_eta(pport, self.dest)
        if eta:
            rid = eta["rid"]
            if rid in self.pending:
                self.known_rids.add(rid)
                self.state[rid] = {**self.pending.pop(rid), "eta_dest": eta["eta_dest"], **self.formation.get(rid, {})}
                log.info("[%s] Confirmed via TS: %s dep %s arr %s", self.name, rid, self.state[rid]["std"], eta["eta_dest"])
                self.publish(mqtt_client)
            elif rid in self.state:
                prev = dict(self.state[rid])
                self.state[rid]["eta_dest"] = eta["eta_dest"]
                if self.state[rid] != prev:
                    self.publish(mqtt_client)

    def handle_formation(self, pport: dict, mqtt_client: mqtt.Client):
        fo = extract_formation(pport)
        if not fo:
            if DEBUG_RAW and any(k in pport.get("uR", {}) for k in _SF_KEYS):
                log.debug("[%s] SF message present but not parsed: %s",
                          self.name, json.dumps(pport.get("uR", {}))[:300])
            return
        rid = fo["rid"]
        fields = {"length": fo["length"], "first": fo["first"]}
        # Cache every formation — it may arrive before we know the rid; the
        # schedule/TS that confirms the service later picks it up from here.
        self._cache_formation(rid, fields)
        if rid in self.state and {k: self.state[rid].get(k) for k in fields} != fields:
            self.state[rid].update(fields)
            log.info("[%s] %s formation: %d cars%s", self.name, rid,
                     fo["length"], f" ({fo['first']} first)" if fo["first"] else "")
            self.publish(mqtt_client)
        elif DEBUG_RAW:
            where = ("in-state" if rid in self.state else
                     "known" if rid in self.known_rids else
                     "pending" if rid in self.pending else "untracked")
            log.debug("[%s] cached formation rid=%s (%s) %d cars",
                      self.name, rid, where, fo["length"])

    def enrich_from_ldbsv(self, mqtt_client: mqtt.Client):
        """Fill coach counts from LDBSV for tracked services Darwin hasn't given
        a formation. LDBSV only confirms a length close to departure, so this is
        polled periodically. No-op without a key; never raises."""
        if not config.LDBSV_KEY:
            return
        forms = ldbsv.formations(self.origin_crs, self.dest_crs,
                                 config.LDBSV_KEY, config.LDBSV_BASE_URL)
        changed = False
        for rid, fo in forms.items():
            t = self.state.get(rid)
            if not t or t.get("length"):
                continue  # not tracked, or Darwin already supplied a length
            fields = {"length": fo["length"]}
            if fo.get("first"):  # board usually lacks per-coach class
                fields["first"] = fo["first"]
            t.update(fields)
            self._cache_formation(rid, {**self.formation.get(rid, {}), **fields})
            log.info("[%s] %s LDBSV formation: %d cars", self.name, rid, fo["length"])
            changed = True
        if changed:
            self.publish(mqtt_client)


_TFL_URL = "https://api.tfl.gov.uk/Line/waterloo-city/Status"
_HEARTBEAT_INTERVAL = 30   # publish a heartbeat this often so the Pico knows the feed is live
_WC_EVERY_N_TICKS = 2      # poll TfL once every N heartbeats (~60s)
_LDBSV_INTERVAL = 60       # how often to top up coach counts from LDBSV


def _fetch_wc_status() -> tuple[str, str] | None:
    """Return (status, reason) for the Waterloo & City line, or None on failure."""
    try:
        req = urllib.request.Request(_TFL_URL, headers={"User-Agent": "train-times-bridge/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        ls = data[0]["lineStatuses"][0]
        status = ls["statusSeverityDescription"]
        reason = ls.get("reason", "") or ""
        # TfL reasons are prefixed with the line name; strip it for brevity
        if reason.startswith("Waterloo & City Line: "):
            reason = reason[len("Waterloo & City Line: "):]
        return status, reason
    except Exception as e:
        log.warning("TfL W&C status fetch failed: %s", e)
        return None


def _publish_wc(mqtt_client: mqtt.Client, status: str, reason: str):
    payload = json.dumps({"status": status, "reason": reason})
    mqtt_client.publish(config.MQTT_WC_TOPIC, payload, retain=True)


def _background_poller(mqtt_client: mqtt.Client, stop: threading.Event):
    """Emit a periodic heartbeat (so the Pico can tell the feed is live) and
    poll the W&C line status on a slower cadence."""
    last_published = ""
    ticks = 0
    while not stop.wait(_HEARTBEAT_INTERVAL):
        mqtt_client.publish(config.MQTT_HEARTBEAT_TOPIC, b"1")
        ticks += 1
        if ticks % _WC_EVERY_N_TICKS != 0:
            continue
        result = _fetch_wc_status()
        if result is None:
            continue
        status, reason = result
        key = status + "|" + reason
        if key != last_published:
            _publish_wc(mqtt_client, status, reason)
            last_published = key
            log.info("W&C line status: %s%s", status, f" — {reason}" if reason else "")


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": config.KAFKA_BOOTSTRAP,
        "security.protocol": "SASL_SSL",
        "sasl.mechanism": "PLAIN",
        "sasl.username": config.KAFKA_API_KEY,
        "sasl.password": config.KAFKA_API_SECRET,
        "group.id": config.KAFKA_GROUP_ID,
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })


def _seek_to_start_of_day(consumer: Consumer, topic: str):
    """Seek all partitions to midnight UTC so we catch today's schedules."""
    midnight_ms = int(time.mktime(time.strptime(
        time.strftime("%Y-%m-%d"), "%Y-%m-%d"
    )) * 1000)
    metadata = consumer.list_topics(topic, timeout=10)
    partitions = [
        TopicPartition(topic, p, midnight_ms)
        for p in metadata.topics[topic].partitions
    ]
    offsets = consumer.offsets_for_times(partitions, timeout=10)
    for tp in offsets:
        if tp.offset >= 0:
            consumer.seek(tp)
    log.info("Seeked to start of day across %d partition(s)", len(offsets))


def _make_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config.MQTT_TLS:
        client.tls_set()
    client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
    client.reconnect_delay_set(min_delay=5, max_delay=60)
    client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    client.loop_start()
    return client


def run():
    consumer = _make_consumer()
    consumer.subscribe([config.KAFKA_TOPIC])
    log.info("Subscribed to Kafka topic: %s", config.KAFKA_TOPIC)

    # Wait for partition assignment, then rewind to midnight to catch today's schedules
    while not consumer.assignment():
        consumer.poll(timeout=1.0)
    _seek_to_start_of_day(consumer, config.KAFKA_TOPIC)
    log.info("Replaying from start of day to build schedule state...")

    mqtt_client = _make_mqtt()
    log.info("Connected to MQTT at %s:%s", config.MQTT_HOST, config.MQTT_PORT)

    directions = [
        Direction("WAT→FNH", WATRLMN, FARNHAM, config.MQTT_TOPIC, "WAT", "FNH"),
        Direction("FNH→WAT", FARNHAM, WATRLMN, config.MQTT_TOPIC_RETURN, "FNH", "WAT"),
    ]

    # Publish W&C status immediately, then poll every 60s
    result = _fetch_wc_status()
    if result:
        status, reason = result
        _publish_wc(mqtt_client, status, reason)
        log.info("W&C line status (initial): %s%s", status, f" — {reason}" if reason else "")
    stop_event = threading.Event()
    poller_thread = threading.Thread(target=_background_poller, args=(mqtt_client, stop_event), daemon=True)
    poller_thread.start()

    last_ldbsv = 0.0
    try:
        while True:
            msg = consumer.poll(timeout=1.0)

            # Periodically top up coach counts from LDBSV for services Darwin
            # didn't give a formation. Done on this thread so all state stays
            # single-threaded; the HTTP call has a short timeout.
            now_t = time.monotonic()
            if now_t - last_ldbsv >= _LDBSV_INTERVAL:
                last_ldbsv = now_t
                for direction in directions:
                    direction.enrich_from_ldbsv(mqtt_client)

            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.error("Kafka error: %s", msg.error())
                continue

            pport = parse_kafka_value(msg.value())
            if pport is None:
                continue

            if DEBUG_RAW:
                log.debug("RAW: %s", json.dumps(pport, indent=2))

            for direction in directions:
                direction.handle_schedules(pport, mqtt_client)
                direction.handle_ts(pport, mqtt_client)
                direction.handle_formation(pport, mqtt_client)

    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        stop_event.set()
        consumer.close()
        mqtt_client.loop_stop()


if __name__ == "__main__":
    run()
