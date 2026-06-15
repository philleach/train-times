# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Internet-connected embedded display showing upcoming Waterloo → Farnham train departures with predicted arrival times.

**Architecture:** Darwin RTII Kafka (Confluent Cloud) → bridge → MQTT broker (self-hosted Mosquitto over Tailscale Funnel, or HiveMQ Cloud) → Pico 2W → Pimoroni Display

## Project Structure

```
bridge/       Darwin→MQTT bridge (Python, runs anywhere)
pico/         Pico 2W MicroPython (deployed to device)
main.py       Desktop test tool (RTT API, verifies credentials)
```

### Bridge (`bridge/`)
- `bridge.py` — Kafka consumer + MQTT publisher; entry point
- `darwin.py` — Darwin Push Port JSON parser; filters WAT→FNH services
- `config.py` — credentials (gitignored; copy from `.env.example`)

### Pico (`pico/`)
- `main.py` — boot entry point; WiFi, NTP, MQTT subscribe loop
- `config.py` — WiFi + MQTT host (gitignored; copy from `config.example.py`)
- `mqtt.py` — MQTT subscriber; receives train list from bridge
- `trains.py` — status formatting (ON TIME / +Nm / CANC)
- `display.py` — Pimoroni picographics driver (320×240)

## Hardware

- **MCU:** Raspberry Pi Pico 2W (RP2350)
- **Display:** Pimoroni Pico Display Pack 2.8" (ST7789, 320×240)
- Display constant in picographics: `DISPLAY_PICO_DISPLAY_2`
- **Broker:** self-hosted Mosquitto exposed via Tailscale Funnel (bridge publishes to loopback with `MQTT_TLS=0`; Pico connects to the Funnel hostname on port 443 over TLS), or HiveMQ Cloud (TLS, port 8883)

## Bridge Setup

Bridge deps (`confluent-kafka`, `paho-mqtt`, `python-dotenv`) are declared in `pyproject.toml`, so use `uv` — no separate `pip install`. `config.py` loads `bridge/.env` automatically via `load_dotenv`.

```bash
uv sync
cp bridge/.env.example bridge/.env   # fill in credentials
uv run python bridge/bridge.py

# Debug: raw Darwin payloads + debug-level logging (verifies field names,
# and shows formation parse/apply/drop decisions)
DEBUG_RAW=1 uv run python bridge/bridge.py
```

## Pico 2W Setup

1. Flash [Pimoroni MicroPython firmware](https://github.com/pimoroni/pimoroni-pico/releases) — use the **pico2w** build (RP2350), not the pico/picow build
2. Copy `pico/` files to the Pico root (exclude `config.example.py`)
3. Copy `pico/config.example.py` → `pico/config.py` and fill in values
4. The Pico runs `main.py` on boot automatically

## Darwin RTII Kafka Feed

- **Bootstrap:** `pkc-z3p1v0.europe-west2.gcp.confluent.cloud:9092`
- **Auth:** SASL_SSL / PLAIN (Confluent API key + secret)
- **Topic:** JSON/AVRO topic (check Confluent Cloud console for exact name)
- **Message format:** outer JSON wrapper; `bytes` field is a JSON string of the Darwin Pport document
- **Pport structure:** `{ts, version, uR: {updateOrigin, TS?: {rid, uid, ssd, Location: [{tpl, ptd, dep: {et}, arr: {et}, plat}]}}}`
- **Tiplocs:** Waterloo = `WATLOO`, Farnham = `FARNHAM`
- `et` = estimated time (future), `at` = actual time (past)
- **scheduleFormations (SF):** `uR.scheduleFormations: {rid, formation: {fid, coaches: {coach: [{coachNumber, coachClass}]}}}` — coach makeup; we extract `length` (coach count) and `first` (First-class count). Element text content uses the `""` key in the JSON feed. **In practice Darwin rarely sends SF for the WAT↔FNH services we track** — see LDBSV fallback below.

## LDBSV (coach-count fallback)

Because Darwin's Push Port usually lacks `scheduleFormations` for our services, the bridge fills coach counts from **OpenLDBSVWS** — the Rail Data Marketplace product *"Live Arrival & Departure Boards - Staff Version"* (`bridge/ldbsv.py`).

- **REST/JSON with `x-apikey` header** (not the legacy SOAP service). Key in `bridge/.env` as `LDBSV_KEY`; optional — disabled if unset.
- **Gateway base URL** (default in `config.py`): `https://api1.raildata.org.uk/1010-live-arrival-and-departure-boards---staff-version1_0/LDBSVWS`. Hitting upstream `realtime.nationalrail.co.uk` directly gives 401.
- **Only `GetArrDepBoardWithDetails` routes** on this product — `GetServiceDetailsByRID` and `GetDepBoardWithDetails` return Apigee `RouteFailed`. So we fetch the board (origin CRS, `filterCrs`=dest, `filterType=to`) and read `formation` per service, keyed by RID. DateTime path param is `yyyyMMddTHHmmss`.
- Polled every 60s on the bridge's **main loop** (state stays single-threaded). `enrich_from_ldbsv` only fills `length` for tracked rids Darwin didn't cover (Darwin SF wins, and is the only source of `first`). The board confirms `length` only **near departure**, so typically just the next train (or two) gets a count.

## MQTT

- Train topics: `trains/WAT/FNH` (outbound) and `trains/FNH/WAT` (return); the Pico's A button toggles direction, B toggles departures ↔ calling-points view
- Payload: JSON array of up to 6 trains, sorted by `std`
- Schema: `[{rid, std, etd, platform, cancelled, eta_dest, length?, first?, reason?}, ...]` (`eta_dest` = predicted arrival at the destination; `length` = coach count from Darwin SF or the LDBSV fallback; `first` = First-class count, Darwin SF only, when available; `reason` = delay/cancel reason text from LDBSV when disrupted)
- Calling-points topics: `trains/WAT/FNH/calling` and `trains/FNH/WAT/calling` — the **next** train's stops for the B-button view, payload `{rid, std, stops: [{name, time, platform?}, ...]}` (from LDBSV `subsequentLocations`, up to the destination)
- Disruption topics: `trains/WAT/FNH/alerts` and `trains/FNH/WAT/alerts` — network disruption messages (LDBSV `nrccMessages`, HTML stripped), payload = JSON array of strings; the Pico scrolls them (plus per-train `reason`) in a bottom banner
- W&C line topic: `lines/waterloo-city`, payload `{status, reason}` (from the TfL API, polled every 60s by the bridge)
- All published with `retain=True` so the Pico gets current state on connect

## Desktop Test Tool

```bash
uv sync
RTT_USERNAME=rttapi_xxx RTT_PASSWORD=xxx uv run python main.py
```
