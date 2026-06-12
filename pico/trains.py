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
    return etd or "?"


def _delay_mins(std: str, etd: str) -> int:
    try:
        sh, sm = int(std[:2]), int(std[3:5])
        eh, em = int(etd[:2]), int(etd[3:5])
        diff = (eh * 60 + em) - (sh * 60 + sm)
        return diff if diff >= 0 else diff + 1440
    except Exception:
        return 0
