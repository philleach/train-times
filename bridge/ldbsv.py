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


def formations(origin_crs: str, dest_crs: str, key: str,
               base_url: str = DEFAULT_BASE_URL) -> dict:
    """rid -> {length, first} for upcoming origin->dest services, or {}.

    Never raises — returns {} on any failure so callers can treat LDBSV as a
    best-effort enrichment."""
    if not key:
        return {}
    try:
        return formations_from_board(fetch_dep_board(origin_crs, dest_crs, key, base_url))
    except Exception as exc:  # network, HTTP, auth — never break the caller
        log.warning("LDBSV board lookup failed for %s->%s: %s", origin_crs, dest_crs, exc)
        return {}


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
    for s in svcs:
        coaches = (s.get("formation") or {}).get("coaches") or []
        print(" ", s.get("rid"), s.get("std"),
              "length=", s.get("length"),
              "coaches=", len(coaches),
              [c.get("coachClass") for c in coaches],
              "->", parse_service_formation(s))
