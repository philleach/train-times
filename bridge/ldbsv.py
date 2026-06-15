"""
OpenLDBSVWS (Live Arrival & Departure Boards, Staff Version) REST client.

Darwin's Push Port doesn't always carry scheduleFormations for the services we
track, so we fill in coach counts from LDBSV (Rail Data Marketplace REST API).

The per-RID operation (GetServiceDetailsByRID) isn't routed on the RDM product,
but GetDepBoardWithDetails is — and its response carries `formation` per
service. So we fetch the departure board for a direction (origin CRS, filtered
to the destination CRS) and read coach counts straight from it, keyed by RID.

Run directly to inspect a board (key/base URL come from bridge/.env):

    uv run python bridge/ldbsv.py WAT FNH
"""

import logging
import re
import sys
from datetime import datetime

import httpx

log = logging.getLogger(__name__)

# RDM gateway for the "Live Arrival & Departure Boards - Staff Version" product.
DEFAULT_BASE_URL = ("https://api1.raildata.org.uk/"
                    "1010-live-arrival-and-departure-boards---staff-version1_0/LDBSVWS")
_API_VERSION = "20220120"
# The dep-only board (GetDepBoardWithDetails) and GetServiceDetailsByRID are not
# routed on this RDM product (gateway returns RouteFailed); the arr+dep board is.
_OP = "GetArrDepBoardWithDetails"

# Waterloo / Farnham CRS codes (the bridge works in tiplocs; these are the
# public station codes LDBSV expects).
WAT = "WAT"
FNH = "FNH"


def _coach_counts(coaches: list) -> tuple[int, int]:
    length = len(coaches)
    # coachClass is "First", "Mixed" or "Standard"; only "First" counts.
    first = sum(1 for c in coaches
                if str(c.get("coachClass", "")).strip().lower() == "first")
    return length, first


def parse_service_formation(service: dict) -> dict | None:
    """Derive {length, first} from one board service, or None."""
    coaches = (service.get("formation") or {}).get("coaches") or []
    length, first = (_coach_counts(coaches) if coaches else (0, 0))
    if not length:
        length = service.get("length") or 0  # car count without per-coach detail
    if not length:
        return None
    return {"length": length, "first": first}


def formations_from_board(board: dict) -> dict:
    """Map rid -> {length, first} for every service on a board that has one."""
    out = {}
    for s in board.get("trainServices") or []:
        rid = s.get("rid")
        if not rid:
            continue
        fo = parse_service_formation(s)
        if fo:
            out[rid] = fo
    return out


def fetch_dep_board(origin_crs: str, dest_crs: str, key: str,
                    base_url: str = DEFAULT_BASE_URL, when: str | None = None,
                    timeout: float = 10.0) -> dict:
    when = when or datetime.now().strftime("%Y%m%dT%H%M%S")
    url = "%s/api/%s/%s/%s/%s" % (
        base_url, _API_VERSION, _OP, origin_crs.upper(), when)
    params = {"filterCrs": dest_crs.upper(), "filterType": "to", "numRows": 10}
    resp = httpx.get(url, params=params, timeout=timeout,
                     headers={"x-apikey": key, "Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


def board(origin_crs: str, dest_crs: str, key: str,
          base_url: str = DEFAULT_BASE_URL) -> dict | None:
    """Fetch the arr+dep board for a direction, or None on any failure.

    Never raises so callers can treat LDBSV as best-effort enrichment."""
    if not key:
        return None
    try:
        return fetch_dep_board(origin_crs, dest_crs, key, base_url)
    except Exception as exc:  # network, HTTP, auth
        log.warning("LDBSV board lookup failed for %s->%s: %s", origin_crs, dest_crs, exc)
        return None


def formations(origin_crs: str, dest_crs: str, key: str,
               base_url: str = DEFAULT_BASE_URL) -> dict:
    """rid -> {length, first} for upcoming origin->dest services, or {}."""
    b = board(origin_crs, dest_crs, key, base_url)
    return formations_from_board(b) if b else {}


def _hhmm(iso: str | None) -> str | None:
    """'2026-06-15T20:30:00' -> '20:30'."""
    return iso[11:16] if iso and len(iso) >= 16 else None


def calling_points_from_service(service: dict, dest_crs: str) -> list:
    """Public calling points for a service, up to and including dest_crs.

    Each stop: {name, time, platform?}. Skips passing points and junctions
    (no CRS / isPass), and stops once the destination is reached."""
    dest_crs = dest_crs.upper()
    out = []
    for loc in service.get("subsequentLocations") or []:
        crs = loc.get("crs")
        if not crs or loc.get("isPass"):
            continue
        stop = {"name": loc.get("locationName") or crs,
                "time": _hhmm(loc.get("eta") or loc.get("etd") or loc.get("std"))}
        if loc.get("platform") and not loc.get("platformIsHidden"):
            stop["platform"] = str(loc["platform"])
        out.append(stop)
        if crs.upper() == dest_crs:
            break
    return out


def calling_for_rid(board_doc: dict, rid: str, dest_crs: str) -> list:
    """Calling points for one rid on a board, or [] if not present."""
    for s in (board_doc or {}).get("trainServices") or []:
        if s.get("rid") == rid:
            return calling_points_from_service(s, dest_crs)
    return []


# ----------------------------------------------------- disruption & reasons

_TAG_RE = re.compile(r"<[^>]+>")


def nrcc_messages_from_board(board_doc: dict) -> list:
    """Plain-text network disruption messages from a board (HTML stripped)."""
    out = []
    for m in (board_doc or {}).get("nrccMessages") or []:
        text = " ".join(_TAG_RE.sub("", m.get("xhtmlMessage") or "").split())
        if text:
            out.append(text)
    return out


_REASON_PATHS = ("api/%s/GetReasonCodeList" % _API_VERSION,
                 "api/ref/20211101/GetReasonCodeList")


def fetch_reason_map(key: str, base_url: str = DEFAULT_BASE_URL) -> dict:
    """code -> {late, canc} from GetReasonCodeList, or {} if unavailable."""
    if not key:
        return {}
    headers = {"x-apikey": key, "Accept": "application/json"}
    for path in _REASON_PATHS:
        try:
            resp = httpx.get("%s/%s" % (base_url, path), headers=headers, timeout=10.0)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("LDBSV reason list %s: %s", path, exc)
            continue
        out = {}
        for r in data or []:
            code = r.get("code")
            if code is None:
                continue
            out[int(code)] = {"late": r.get("lateReason") or "",
                              "canc": r.get("cancReason") or ""}
        if out:
            log.info("LDBSV reason map: %d codes via %s", len(out), path)
            return out
    return {}


def reason_for_service(service: dict, reason_map: dict) -> str | None:
    """Human-readable delay/cancel reason for a board service, or None."""
    if not reason_map:
        return None
    if service.get("isCancelled"):
        rc, kind = service.get("cancelReason"), "canc"
    else:
        rc, kind = service.get("delayReason"), "late"
    if not rc:
        return None
    try:
        code = int(rc.get("Value"))
    except (TypeError, ValueError):
        return None
    entry = reason_map.get(code)
    return (entry.get(kind) or None) if entry else None


def reasons_from_board(board_doc: dict, reason_map: dict) -> dict:
    """rid -> reason text for services on the board that have one."""
    out = {}
    for s in (board_doc or {}).get("trainServices") or []:
        rid = s.get("rid")
        text = reason_for_service(s, reason_map) if rid else None
        if text:
            out[rid] = text
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import config  # noqa: E402  (bridge/ is on sys.path[0]; loads .env)

    if len(sys.argv) < 3:
        print("usage: python bridge/ldbsv.py <originCRS> <destCRS>   (e.g. WAT FNH)")
        raise SystemExit(2)
    origin, dest = sys.argv[1].upper(), sys.argv[2].upper()
    key = getattr(config, "LDBSV_KEY", "")
    base_url = getattr(config, "LDBSV_BASE_URL", "") or DEFAULT_BASE_URL
    if not key:
        print("No LDBSV_KEY set in bridge/.env")
        raise SystemExit(2)

    when = datetime.now().strftime("%Y%m%dT%H%M%S")
    url = "%s/api/%s/%s/%s/%s" % (base_url, _API_VERSION, _OP, origin, when)
    resp = httpx.get(url, params={"filterCrs": dest, "filterType": "to", "numRows": 10},
                     headers={"x-apikey": key, "Accept": "application/json"}, timeout=10.0)
    print("GET", resp.url)
    print("HTTP", resp.status_code, "  bytes:", len(resp.content))
    if resp.status_code != 200:
        print(resp.text[:1000])
        raise SystemExit(1)

    board = resp.json()
    svcs = board.get("trainServices") or []
    print("services:", len(svcs))
    print("board nrccMessages:", board.get("nrccMessages"))
    for s in svcs:
        coaches = (s.get("formation") or {}).get("coaches") or []
        print(" ", s.get("rid"), s.get("std"),
              "length=", s.get("length"),
              "coaches=", len(coaches),
              [c.get("coachClass") for c in coaches],
              "->", parse_service_formation(s))

    # `dump` as a 3rd arg prints the first service in full so we can see which
    # rich fields (loading, reasons, alerts, calling points) are actually
    # populated for these services.
    if len(sys.argv) > 3 and sys.argv[3] == "dump" and svcs:
        import json
        print("\n=== first service (full) ===")
        print(json.dumps(svcs[0], indent=2))
