"""Status formatting for the departures view.

Ported from the Pico's `trains.py` so the web client and the display agree, with
server-side conveniences (real datetime, a Tailwind colour class per status).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

_LONDON = ZoneInfo("Europe/London")


def now_london_mins() -> int:
    """Current minute-of-day in railway-local (Europe/London) time."""
    t = datetime.now(_LONDON)
    return t.hour * 60 + t.minute


def _delay_mins(std: str, etd: str) -> int:
    try:
        sh, sm = int(std[:2]), int(std[3:5])
        eh, em = int(etd[:2]), int(etd[3:5])
        diff = (eh * 60 + em) - (sh * 60 + sm)
        if diff > 720:
            diff -= 1440
        elif diff < -720:
            diff += 1440
        return diff
    except Exception:
        return 0


def format_status(train: dict) -> str:
    if train.get("cancelled"):
        return "Cancelled"
    etd = train.get("etd") or ""
    if etd == "On time":
        return "On time"
    if etd == "Cancelled":
        return "Cancelled"
    if etd == "Delayed":
        return "Delayed"
    std = train.get("std") or ""
    if etd and etd != std:
        mins = _delay_mins(std, etd)
        if mins > 0:
            return f"+{mins} min ({etd})"
        if mins < 0:
            return f"Early ({etd})"
    return etd or "?"


def severity(train: dict) -> int:
    """0 = on time/early, 1 = delayed, 2 = cancelled."""
    if train.get("cancelled"):
        return 2
    status = format_status(train)
    if status.startswith("Cancelled"):
        return 2
    if status == "On time" or status.startswith("Early"):
        return 0
    return 1


_STATUS_CLASS = {
    0: "text-emerald-400",
    1: "text-amber-400",
    2: "text-rose-400",
}


def mins_until(hhmm: str, now_mins: int):
    """Minutes from now until hh:mm. None if unparseable. A time up to ~2h in the
    past reads negative (just departed); further back is treated as tomorrow."""
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except Exception:
        return None
    diff = (h * 60 + m) - now_mins
    if diff < -120:
        diff += 1440
    return diff


def _due_text(mins) -> str:
    if mins is None:
        return ""
    if mins <= 0:
        return "due"
    if mins == 1:
        return "1 min"
    return f"{mins} min"


def view_model(train: dict, now_mins: int) -> dict:
    """Build a template-friendly dict for one train."""
    std = train.get("std") or "--:--"
    sev = severity(train)
    mins = mins_until(std, now_mins)
    return {
        "std": std,
        "status": format_status(train),
        "status_class": _STATUS_CLASS.get(sev, "text-slate-300"),
        "severity": sev,
        "platform": train.get("platform"),
        "eta_dest": train.get("eta_dest"),
        "length": train.get("length"),
        "first": train.get("first"),
        "reason": train.get("reason"),
        "due": _due_text(mins),
        "due_mins": mins,
    }
