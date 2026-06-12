import json

import pytest

from bridge.darwin import extract_ts_update, extract_wat_fnh_schedules, parse_kafka_value


def _wrap(pport: dict) -> bytes:
    return json.dumps({"bytes": json.dumps(pport)}).encode()


def _pport_ts(locations: list, rid: str = "rid123") -> dict:
    return {
        "ts": "2024-06-10T14:00:00",
        "uR": {
            "updateOrigin": "TD",
            "TS": {"rid": rid, "uid": "C12345", "ssd": "2024-06-10", "Location": locations},
        },
    }


def _pport_schedule(schedules: list | dict) -> dict:
    return {
        "ts": "2024-06-10T08:00:00",
        "uR": {"updateOrigin": "CIS", "schedule": schedules},
    }


def _schedule(or_tpl="WATRLMN", ip_tpl="FARNHAM", dt_tpl=None, std="14:32", pta="15:22", rid="rid123"):
    sc = {
        "rid": rid,
        "uid": "C12345",
        "ssd": "2024-06-10",
        "OR": {"tpl": or_tpl, "ptd": std},
    }
    if ip_tpl:
        sc["IP"] = [{"tpl": ip_tpl, "pta": pta}]
    if dt_tpl:
        sc["DT"] = {"tpl": dt_tpl, "pta": pta}
    return sc


WAT_LOC = {
    "tpl": "WATRLMN",
    "ptd": "14:32",
    "dep": {"et": "14:35"},
    "plat": {"_text": "4", "conf": "true"},
}

FNH_LOC = {
    "tpl": "FARNHAM",
    "pta": "15:22",
    "arr": {"et": "15:28"},
}


# ---------------------------------------------------------------------------
# parse_kafka_value
# ---------------------------------------------------------------------------

class TestParseKafkaValue:
    def test_round_trip(self):
        pport = _pport_ts([WAT_LOC, FNH_LOC])
        assert parse_kafka_value(_wrap(pport)) == pport

    def test_missing_bytes_field(self):
        assert parse_kafka_value(json.dumps({"other": "data"}).encode()) is None

    def test_invalid_json(self):
        assert parse_kafka_value(b"not json") is None

    def test_inner_invalid_json(self):
        assert parse_kafka_value(json.dumps({"bytes": "not json"}).encode()) is None


# ---------------------------------------------------------------------------
# extract_wat_fnh_schedules
# ---------------------------------------------------------------------------

class TestExtractWatFnhSchedules:
    def test_basic_farnham_in_ip(self):
        pport = _pport_schedule(_schedule())
        result = extract_wat_fnh_schedules(pport)
        assert len(result) == 1
        assert result[0] == {"rid": "rid123", "std": "14:32", "pta_fnh": "15:22"}

    def test_farnham_as_destination(self):
        sc = _schedule(ip_tpl=None, dt_tpl="FARNHAM")
        result = extract_wat_fnh_schedules(_pport_schedule(sc))
        assert len(result) == 1
        assert result[0]["pta_fnh"] == "15:22"

    def test_not_from_watrlmn(self):
        sc = _schedule(or_tpl="WOKING")
        assert extract_wat_fnh_schedules(_pport_schedule(sc)) == []

    def test_no_farnham_stop(self):
        sc = _schedule(ip_tpl="WOKING")
        assert extract_wat_fnh_schedules(_pport_schedule(sc)) == []

    def test_multiple_schedules_filters_correctly(self):
        sc1 = _schedule(rid="r1")
        sc2 = _schedule(or_tpl="WOKING", rid="r2")  # not from WAT
        sc3 = _schedule(ip_tpl="WOKING", rid="r3")  # doesn't call FNH
        result = extract_wat_fnh_schedules(_pport_schedule([sc1, sc2, sc3]))
        assert len(result) == 1
        assert result[0]["rid"] == "r1"

    def test_single_schedule_dict_not_list(self):
        sc = _schedule()
        result = extract_wat_fnh_schedules(_pport_schedule(sc))
        assert len(result) == 1

    def test_no_schedule_key(self):
        pport = _pport_ts([WAT_LOC])
        assert extract_wat_fnh_schedules(pport) == []

    def test_ip_as_single_dict(self):
        sc = _schedule()
        sc["IP"] = {"tpl": "FARNHAM", "pta": "15:22"}  # dict, not list
        result = extract_wat_fnh_schedules(_pport_schedule(sc))
        assert len(result) == 1
        assert result[0]["pta_fnh"] == "15:22"


# ---------------------------------------------------------------------------
# extract_ts_update
# ---------------------------------------------------------------------------

KNOWN = {"rid123"}


class TestExtractTsUpdate:
    def test_watrlmn_update(self):
        pport = _pport_ts([WAT_LOC])
        result = extract_ts_update(pport, KNOWN)
        assert result is not None
        assert result["rid"] == "rid123"
        assert result["etd"] == "14:35"
        assert result["platform"] == "4"
        assert result["cancelled"] is False

    def test_farnham_update(self):
        pport = _pport_ts([FNH_LOC])
        result = extract_ts_update(pport, KNOWN)
        assert result is not None
        assert result["eta_fnh"] == "15:28"

    def test_both_stops(self):
        pport = _pport_ts([WAT_LOC, FNH_LOC])
        result = extract_ts_update(pport, KNOWN)
        assert result["etd"] == "14:35"
        assert result["eta_fnh"] == "15:28"

    def test_unknown_rid_returns_none(self):
        pport = _pport_ts([WAT_LOC])
        assert extract_ts_update(pport, set()) is None

    def test_on_time_when_etd_matches_std(self):
        loc = {**WAT_LOC, "ptd": "14:32", "dep": {"et": "14:32"}}
        result = extract_ts_update(_pport_ts([loc]), KNOWN)
        assert result["etd"] == "On time"

    def test_on_time_when_no_etd(self):
        loc = {**WAT_LOC, "dep": {}}
        result = extract_ts_update(_pport_ts([loc]), KNOWN)
        assert result["etd"] == "On time"

    def test_cancelled_flag(self):
        loc = {**WAT_LOC, "cancelled": "true"}
        result = extract_ts_update(_pport_ts([loc]), KNOWN)
        assert result["cancelled"] is True

    def test_platform_plain_string(self):
        loc = {**WAT_LOC, "plat": "7"}
        result = extract_ts_update(_pport_ts([loc]), KNOWN)
        assert result["platform"] == "7"

    def test_platform_empty_string_key(self):
        loc = {**WAT_LOC, "plat": {"platsrc": "A", "": "2"}}
        result = extract_ts_update(_pport_ts([loc]), KNOWN)
        assert result["platform"] == "2"

    def test_no_ts_returns_none(self):
        assert extract_ts_update({"uR": {"updateOrigin": "TD"}}, KNOWN) is None

    def test_unrelated_stop_only_returns_none(self):
        loc = {"tpl": "WOKING", "ptd": "14:55", "dep": {"et": "14:57"}}
        assert extract_ts_update(_pport_ts([loc]), KNOWN) is None

    def test_at_time_used_when_no_et(self):
        fnh = {"tpl": "FARNHAM", "pta": "15:22", "arr": {"at": "15:25"}}
        result = extract_ts_update(_pport_ts([fnh]), KNOWN)
        assert result["eta_fnh"] == "15:25"

    def test_no_fnh_arr_eta_skipped(self):
        fnh = {"tpl": "FARNHAM", "pta": "15:22"}  # no arr field
        result = extract_ts_update(_pport_ts([fnh]), KNOWN)
        assert result is None  # only rid in update dict
