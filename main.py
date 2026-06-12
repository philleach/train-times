"""Desktop test tool — verifies RTT credentials and prints upcoming departures with FNH arrivals."""
import os

import httpx


def _fmt(t):
    return t[:2] + ":" + t[2:] if t and len(t) == 4 else (t or "?")


def _fnh_arrival(client, auth, uid, run_date):
    date_path = run_date.replace("-", "/")
    r = client.get(
        f"https://api.rtt.io/api/v1/json/service/{uid}/{date_path}",
        auth=auth,
    )
    r.raise_for_status()
    for loc in r.json().get("locations") or []:
        if loc.get("crs") == "FNH":
            t = loc.get("realtimeArrival") or loc.get("gbttBookedArrival")
            return _fmt(t)
    return "--:--"


def main():
    auth = (os.environ["RTT_USERNAME"], os.environ["RTT_PASSWORD"])

    with httpx.Client() as client:
        r = client.get(
            "https://api.rtt.io/api/v1/json/search/WAT/to/FNH",
            auth=auth,
        )
        r.raise_for_status()

        services = r.json().get("services") or []
        upcoming = [
            s for s in services
            if not s.get("locationDetail", {}).get("realtimeDepartureActual")
        ][:8]

        print(f"{'DEP':<6}  {'ARR FNH':<8}  {'PLT':<4}  {'STATUS'}")
        print("-" * 40)
        for s in upcoming:
            d = s["locationDetail"]
            std = _fmt(d.get("gbttBookedDeparture"))
            etd = _fmt(d.get("realtimeDeparture"))
            plt = d.get("platform") or "-"
            display_as = d.get("displayAs", "")
            status = "CANC" if display_as == "CANCELLED_CALL" else ("ON TIME" if etd == std else f"+{etd}")
            arr = _fnh_arrival(client, auth, s["serviceUid"], s["runDate"])
            print(f"{std:<6}  {arr:<8}  {plt:<4}  {status}")


if __name__ == "__main__":
    main()
