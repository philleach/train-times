import pytest

from pico.trains import format_status, _delay_mins


class TestDelayMins:
    def test_on_time(self):
        assert _delay_mins("14:32", "14:32") == 0

    def test_five_minutes_late(self):
        assert _delay_mins("14:32", "14:37") == 5

    def test_midnight_crossing(self):
        # Train due 23:58, now expected 00:03
        assert _delay_mins("23:58", "00:03") == 5

    def test_invalid_input(self):
        assert _delay_mins("bad", "data") == 0


class TestFormatStatus:
    def test_cancelled_flag(self):
        assert format_status({"cancelled": True, "etd": "14:37", "std": "14:32"}) == "CANC"

    def test_cancelled_string_in_etd(self):
        assert format_status({"cancelled": False, "etd": "Cancelled", "std": "14:32"}) == "CANC"

    def test_on_time(self):
        assert format_status({"cancelled": False, "etd": "On time", "std": "14:32"}) == "ON TIME"

    def test_delayed_string(self):
        assert format_status({"cancelled": False, "etd": "Delayed", "std": "14:32"}) == "DELAY"

    def test_late_by_five(self):
        assert format_status({"cancelled": False, "etd": "14:37", "std": "14:32"}) == "+5m"

    def test_early_or_zero_delay(self):
        # etd equals std — treat as on time (delay = 0, falls through to returning etd)
        result = format_status({"cancelled": False, "etd": "14:32", "std": "14:32"})
        assert result == "14:32"

    def test_missing_etd(self):
        assert format_status({"cancelled": False, "std": "14:32"}) == "?"

    def test_empty_etd(self):
        assert format_status({"cancelled": False, "etd": "", "std": "14:32"}) == "?"
