def format_status(train: dict) -> str:
    if train.get("cancelled"):
        return "CANC"
    etd = train.get("etd") or ""
    if etd == "On time":
        return "ON TIME"
    if etd == "Cancelled":
        return "CANC"
    if etd == "Delayed":
        return "DELAY"
    std = train.get("std") or ""
    if etd and etd != std:
        mins = _delay_mins(std, etd)
        if mins > 0:
            return f"+{mins}m"
        if mins < 0:
            return "EARLY"
    return etd or "?"


def _delay_mins(std: str, etd: str) -> int:
    try:
        sh, sm = int(std[:2]), int(std[3:5])
        eh, em = int(etd[:2]), int(etd[3:5])
        diff = (eh * 60 + em) - (sh * 60 + sm)
        # Wrap only genuine midnight crossings; a small negative diff means the
        # train is running early, not ~24h late.
        if diff > 720:
            diff -= 1440
        elif diff < -720:
            diff += 1440
        return diff
    except Exception:
        return 0


def short_status(train: dict) -> str:
    """Compact status for narrow rows: ON / +Nm / DLY / CANC."""
    full = format_status(train)
    if full == "ON TIME":
        return "ON"
    if full == "DELAY":
        return "DLY"
    return full  # CANC, +Nm, or raw etd


# severity: 0 = on time, 1 = delayed, 2 = cancelled
def severity(train: dict) -> int:
    status = format_status(train)
    if status == "CANC":
        return 2
    if status == "ON TIME" or status == "EARLY":
        return 0
    return 1


def mins_until(hhmm: str, now_mins: int):
    """Minutes from now_mins until hh:mm (local). None if unparseable.

    Handles midnight wrap: a time up to ~2h in the past reads as negative
    (just departed); anything further back is treated as tomorrow.
    """
    try:
        h, m = int(hhmm[:2]), int(hhmm[3:5])
    except Exception:
        return None
    diff = (h * 60 + m) - now_mins
    if diff < -120:
        diff += 1440
    return diff
