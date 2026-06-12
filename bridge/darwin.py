"""
Parse Darwin Push Port messages from the JSON/AVRO Kafka topic.

Each Kafka message value is a JSON object whose `bytes` field contains another
JSON string — the serialised Pport document. Two message types are relevant:

  schedule — full service timetable; used to identify WAT→FNH services
  TS       — per-location timing updates; used for real-time ETDs/ETAs

Darwin sends TS updates for individual stops, not the full journey in one
message, so the two types must be combined: schedules tell us which rids call
at FARNHAM, TS messages tell us the live times for those rids.
"""

import json
import logging

log = logging.getLogger(__name__)

WATRLMN = "WATRLMN"  # London Waterloo mainline platforms
FARNHAM = "FARNHAM"

_LOCATION_KEYS = ("Location", "ns2:Location", "fc:Location")
_PLATFORM_TEXT_KEYS = ("_text", "value", "#text", "")


def _locations(ts: dict) -> list:
    for key in _LOCATION_KEYS:
        val = ts.get(key)
        if val is not None:
            return val if isinstance(val, list) else [val]
    return []


def _platform(plat) -> str | None:
    if plat is None:
        return None
    if isinstance(plat, str):
        return plat
    for key in _PLATFORM_TEXT_KEYS:
        val = plat.get(key)
        if val:
            return str(val)
    return None


def _time(timing: dict | None) -> str | None:
    """Return best available time from a dep/arr object (et preferred over at)."""
    if not timing:
        return None
    return timing.get("et") or timing.get("at")


def parse_kafka_value(raw: bytes) -> dict | None:
    """Decode a raw Kafka message value and return the inner Darwin Pport dict."""
    try:
        outer = json.loads(raw)
        inner_str = outer.get("bytes")
        if not inner_str:
            return None
        return json.loads(inner_str)
    except Exception as exc:
        log.debug("Could not parse Kafka value: %s", exc)
        return None


def extract_wat_fnh_schedules(pport: dict) -> list[dict]:
    """
    Return a list of {rid, std, pta_fnh} for any WAT→FNH services in a
    schedule message. Returns an empty list if this isn't a schedule message
    or contains no WAT→FNH services.
    """
    ur = pport.get("uR", {})
    schedules = ur.get("schedule", [])
    if isinstance(schedules, dict):
        schedules = [schedules]

    result = []
    for sc in schedules:
        or_ = sc.get("OR", {})
        if not isinstance(or_, dict) or or_.get("tpl") != WATRLMN:
            continue

        pta_fnh = None

        ips = sc.get("IP", [])
        if isinstance(ips, dict):
            ips = [ips]
        for ip in ips:
            if ip.get("tpl") == FARNHAM:
                pta_fnh = ip.get("pta")
                break

        if pta_fnh is None:
            dt = sc.get("DT", {})
            if isinstance(dt, dict) and dt.get("tpl") == FARNHAM:
                pta_fnh = dt.get("pta")

        if pta_fnh is None:
            continue

        rid = sc.get("rid")
        std = or_.get("ptd")
        if rid and std:
            result.append({"rid": rid, "std": std, "pta_fnh": pta_fnh})

    return result


def extract_ts_update(pport: dict, known_rids: set) -> dict | None:
    """
    If this pport is a TS update for a known WAT→FNH rid, return a partial
    update dict containing any of: rid, etd, platform, cancelled, eta_fnh.
    Returns None if not relevant.
    """
    ur = pport.get("uR", {})
    ts = ur.get("TS")
    if not ts:
        return None

    rid = ts.get("rid")
    if rid not in known_rids:
        return None

    update: dict = {"rid": rid}
    for loc in _locations(ts):
        tpl = loc.get("tpl", "")
        if tpl == WATRLMN:
            dep = loc.get("dep") or {}
            cancelled = str(loc.get("cancelled", "false")).lower() == "true"
            etd = _time(dep)
            std = loc.get("ptd")
            update["etd"] = "On time" if (etd is None or etd == std) else etd
            update["platform"] = _platform(loc.get("plat"))
            update["cancelled"] = cancelled
        elif tpl == FARNHAM:
            arr = loc.get("arr") or {}
            eta = _time(arr)
            if eta:
                update["eta_fnh"] = eta

    return update if len(update) > 1 else None


def extract_watrlmn_departure(pport: dict) -> dict | None:
    """
    If this pport is a TS with a WATRLMN departure (ptd present), return
    {rid, std, etd, platform, cancelled}. Used to track candidate services
    whose schedule we don't have. Returns None otherwise.
    """
    ur = pport.get("uR", {})
    ts = ur.get("TS")
    if not ts:
        return None
    for loc in _locations(ts):
        if loc.get("tpl") != WATRLMN:
            continue
        std = loc.get("ptd")
        if not std:
            continue  # no public departure time → arrival, not departure
        dep = loc.get("dep") or {}
        cancelled = str(loc.get("cancelled", "false")).lower() == "true"
        etd = _time(dep)
        return {
            "rid": ts.get("rid"),
            "std": std,
            "etd": "On time" if (etd is None or etd == std) else etd,
            "platform": _platform(loc.get("plat")),
            "cancelled": cancelled,
        }
    return None


def extract_farnham_eta(pport: dict) -> dict | None:
    """
    If this pport is a TS with a FARNHAM arrival estimate, return
    {rid, eta_fnh}. Returns None otherwise.
    """
    ur = pport.get("uR", {})
    ts = ur.get("TS")
    if not ts:
        return None
    for loc in _locations(ts):
        if loc.get("tpl") != FARNHAM:
            continue
        arr = loc.get("arr") or {}
        eta = _time(arr) or loc.get("pta")
        if eta:
            return {"rid": ts.get("rid"), "eta_fnh": eta}
    return None
