# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

Internet-connected embedded display showing upcoming Waterloo → Farnham train departures with predicted arrival times.

**Architecture:** Darwin RTII Kafka (Confluent Cloud) → bridge → HiveMQ Cloud MQTT → Pico 2W → Pimoroni Display

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
- **Broker:** HiveMQ Cloud (TLS, port 8883)

## Bridge Setup

```bash
pip install confluent-kafka paho-mqtt
cp bridge/.env.example bridge/.env   # fill in credentials
python bridge/bridge.py

# Debug: print raw Darwin payloads to verify field names
DEBUG_RAW=1 python bridge/bridge.py
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

## MQTT

- Train topics: `trains/WAT/FNH` (outbound) and `trains/FNH/WAT` (return); the Pico's A button toggles which is shown
- Payload: JSON array of up to 6 trains, sorted by `std`
- Schema: `[{rid, std, etd, platform, cancelled, eta_dest}, ...]` (`eta_dest` = predicted arrival at the destination)
- W&C line topic: `lines/waterloo-city`, payload `{status, reason}` (from the TfL API, polled every 60s by the bridge)
- All published with `retain=True` so the Pico gets current state on connect

## Desktop Test Tool

```bash
uv sync
RTT_USERNAME=rttapi_xxx RTT_PASSWORD=xxx uv run python main.py
```
