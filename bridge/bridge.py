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
import time

import paho.mqtt.client as mqtt
from confluent_kafka import Consumer, KafkaError, TopicPartition

import config
from darwin import (
    extract_farnham_eta,
    extract_ts_update,
    extract_wat_fnh_schedules,
    extract_watrlmn_departure,
    parse_kafka_value,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

DEBUG_RAW = os.environ.get("DEBUG_RAW", "").lower() in ("1", "true")

_known_rids: set[str] = set()    # rids confirmed to serve WAT→FNH
_pending_wat: dict[str, dict] = {}  # WATRLMN departures seen; awaiting FARNHAM confirmation
_state: dict[str, dict] = {}    # rid -> train dict
_last_published: str = ""


def _now_mins() -> int:
    t = time.localtime()
    return t[3] * 60 + t[4]


def _hhmm_to_mins(hhmm: str) -> int:
    try:
        return int(hhmm[:2]) * 60 + int(hhmm[3:5])
    except Exception:
        return 0


def _prune():
    now = _now_mins()
    stale = [
        rid for rid, t in _state.items()
        if t.get("std") and _hhmm_to_mins(t["std"]) < now - 2
    ]
    for rid in stale:
        del _state[rid]
        _known_rids.discard(rid)
        log.debug("Pruned departed service %s", rid)
    stale_pending = [
        rid for rid, t in _pending_wat.items()
        if t.get("std") and _hhmm_to_mins(t["std"]) < now - 2
    ]
    for rid in stale_pending:
        del _pending_wat[rid]


def _upcoming() -> list:
    _prune()
    return sorted(_state.values(), key=lambda t: t.get("std", "99:99"))[:6]


def _publish(mqtt_client: mqtt.Client):
    global _last_published
    trains = _upcoming()
    payload = json.dumps(trains)
    if payload == _last_published:
        return
    mqtt_client.publish(config.MQTT_TOPIC, payload, retain=True)
    _last_published = payload
    log.info("Published %d trains", len(trains))


def _handle_schedules(pport: dict, mqtt_client: mqtt.Client):
    now = _now_mins()
    for sched in extract_wat_fnh_schedules(pport):
        rid = sched["rid"]
        if rid in _known_rids:
            continue
        if _hhmm_to_mins(sched["std"]) < now - 2:
            continue  # already departed
        _known_rids.add(rid)
        _state[rid] = {
            "rid": rid,
            "std": sched["std"],
            "etd": "On time",
            "platform": None,
            "cancelled": False,
            "eta_fnh": sched["pta_fnh"],
        }
        log.info("WAT→FNH: %s dep %s arr FNH %s", rid, sched["std"], sched["pta_fnh"])
        _publish(mqtt_client)


def _handle_ts(pport: dict, mqtt_client: mqtt.Client):
    now = _now_mins()

    # Update known WAT→FNH services
    update = extract_ts_update(pport, _known_rids)
    if update:
        rid = update.pop("rid")
        if rid in _state:
            prev = dict(_state[rid])
            _state[rid].update(update)
            if _state[rid] != prev:
                t = _state[rid]
                log.info(
                    "%s  dep %s (%s)  arr FNH %s  plt %s%s",
                    rid, t["std"], t["etd"], t.get("eta_fnh", "?"),
                    t.get("platform", "?"), "  CANC" if t["cancelled"] else "",
                )
                _publish(mqtt_client)

    # Track WATRLMN departures for services we don't have a schedule for
    dep = extract_watrlmn_departure(pport)
    if dep:
        rid = dep["rid"]
        if rid not in _known_rids and rid not in _pending_wat:
            if _hhmm_to_mins(dep["std"]) >= now - 2:
                _pending_wat[rid] = dep
                log.debug("Pending WAT departure: %s dep %s", rid, dep["std"])

    # Confirm pending services when FARNHAM appears
    fnh = extract_farnham_eta(pport)
    if fnh:
        rid = fnh["rid"]
        if rid in _pending_wat:
            _known_rids.add(rid)
            _state[rid] = {**_pending_wat.pop(rid), "eta_fnh": fnh["eta_fnh"]}
            log.info("Confirmed WAT→FNH via TS: %s dep %s arr FNH %s", rid, _state[rid]["std"], fnh["eta_fnh"])
            _publish(mqtt_client)
        elif rid in _state:
            prev = dict(_state[rid])
            _state[rid]["eta_fnh"] = fnh["eta_fnh"]
            if _state[rid] != prev:
                _publish(mqtt_client)


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

    try:
        while True:
            msg = consumer.poll(timeout=1.0)
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

            _handle_schedules(pport, mqtt_client)
            _handle_ts(pport, mqtt_client)

    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        consumer.close()
        mqtt_client.loop_stop()


if __name__ == "__main__":
    run()
