# train-times

Internet-connected embedded display showing upcoming Waterloo → Farnham train departures with live arrival predictions.

**Architecture:** Darwin RTII Kafka (Confluent Cloud) → bridge → MQTT broker (self-hosted Mosquitto over Tailscale Funnel, or HiveMQ Cloud) → Pico 2W → Pimoroni 2.8" display

The display also shows Waterloo & City line status, coach counts (when available), and the return Farnham → Waterloo direction (toggled with the Pico's A button).

## Hardware

| Part | Notes |
|------|-------|
| Any always-on machine | Runs the Darwin→MQTT bridge (Pi, server, laptop) |
| Raspberry Pi Pico 2W | RP2350, drives the display |
| Pimoroni Pico Display Pack 2.8" | ST7789, 320×240, plugs onto Pico header |

## Prerequisites

- **Darwin RTII subscription** — sign up at [networkrail.co.uk](https://www.networkrail.co.uk/who-we-are/innovation-and-technology/information-feeds/), then find your Confluent Cloud credentials in the portal
- **An MQTT broker** — a self-hosted Mosquitto (e.g. exposed over [Tailscale Funnel](https://tailscale.com/kb/1223/funnel)), or a [HiveMQ Cloud](https://www.hivemq.com/cloud/) free-tier cluster
- **[uv](https://docs.astral.sh/uv/)** for running the Python bridge and tests
- **Pimoroni MicroPython firmware** flashed to the Pico 2W — use the **pico2w** build (RP2350) from the [Pimoroni releases page](https://github.com/pimoroni/pimoroni-pico/releases), not the plain pico or picow build

## Bridge setup

The bridge dependencies (`confluent-kafka`, `paho-mqtt`, `python-dotenv`) are declared in `pyproject.toml`, so `uv` handles them — no separate `pip install` needed.

```bash
# 1. Install dependencies
uv sync

# 2. Set credentials (config.py loads bridge/.env automatically)
cp bridge/.env.example bridge/.env
# Edit bridge/.env — fill in Confluent Cloud and MQTT credentials

# 3. Run
uv run python bridge/bridge.py
```

**Debug mode** — print raw Darwin payloads (and enable debug logging) to verify JSON field names:

```bash
DEBUG_RAW=1 uv run python bridge/bridge.py
```

### Credentials (`bridge/.env`)

Self-hosted Mosquitto (the default setup) — Tailscale Funnel terminates public TLS, so the bridge publishes to plaintext loopback:

```
KAFKA_API_KEY=your-confluent-api-key
KAFKA_API_SECRET=your-confluent-api-secret
MQTT_HOST=127.0.0.1
MQTT_PORT=1883
MQTT_TLS=0
MQTT_USER=your-mosquitto-username
MQTT_PASSWORD=your-mosquitto-password
```

Alternatively, for HiveMQ Cloud (or any direct TLS broker) just point at the host — `MQTT_PORT=8883` and `MQTT_TLS=1` are the defaults, so they can be omitted:

```
MQTT_HOST=abc123.s2.eu.hivemq.cloud
MQTT_USER=your-hivemq-username
MQTT_PASSWORD=your-hivemq-password
```

### Coach counts (LDBSV — optional)

Darwin's Push Port rarely carries coach formation for these services, so the bridge optionally fills the car count from the Rail Data Marketplace product **"Live Arrival & Departure Boards - Staff Version"** (OpenLDBSVWS). Subscribe on the [Rail Data Marketplace](https://raildata.org.uk/), then add your API key:

```
LDBSV_KEY=your-rdm-api-key
# LDBSV_BASE_URL defaults to the product's RDM gateway; override only if it differs
```

Leave `LDBSV_KEY` unset to disable the lookup. The board only confirms formation close to departure, so usually just the next train (or two) shows a coach count.

### Run as a systemd service

The deployed unit on the box (`rene`) is named **`train-bridge`** (not
`train-times`), runs from `/home/phil/projects/train-times`, and starts with
`--no-sync` so a restart doesn't re-resolve deps:

```ini
# /etc/systemd/system/train-bridge.service
[Unit]
Description=Darwin -> MQTT train bridge
After=network-online.target

[Service]
WorkingDirectory=/home/phil/projects/train-times
ExecStart=/usr/bin/env uv run --no-sync python bridge/bridge.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl restart train-bridge      # after a git pull, to deploy new code
sudo journalctl -fu train-bridge         # follow logs
```

Because of `--no-sync`, if you ever change the bridge's dependencies you must run
`uv sync` on the box before restarting.

## Pico 2W setup

1. Flash the [Pimoroni pico2w MicroPython firmware](https://github.com/pimoroni/pimoroni-pico/releases) (RP2350 build)
2. Copy the `pico/` directory contents to the Pico root (exclude `config.example.py`)
3. Create `pico/config.py` from the example and fill in values. The Pico always connects over TLS — with Tailscale Funnel that's the Funnel hostname on port 443:

```python
WIFI_SSID     = "your-wifi-ssid"
WIFI_PASSWORD = "your-wifi-password"
MQTT_HOST     = "your-machine.tailXXXX.ts.net"  # Funnel hostname (HiveMQ: abc123.s2.eu.hivemq.cloud)
MQTT_PORT     = 443                               # HiveMQ: 8883
MQTT_USER     = "your-mosquitto-username"
MQTT_PASSWORD = "your-mosquitto-password"
```

4. The Pico boots `main.py` automatically — it connects to WiFi, sets the time via NTP, subscribes to MQTT, and starts rendering departures. Buttons: **A** toggles direction (WAT→FNH / FNH→WAT), **B** toggles the departures ↔ calling-points view, **X/Y** adjust brightness.

## Desktop test tool (RTT API)

A standalone script that queries the [Realtime Trains API](https://www.realtimetrains.co.uk/) and prints the next Waterloo→Farnham departures — useful for checking credentials and data without any hardware.

```bash
uv sync
RTT_USERNAME=rttapi_xxx RTT_PASSWORD=xxx uv run python main.py
```

## Running tests

```bash
uv sync
uv run pytest
```

## Project layout

```
bridge/     Darwin→MQTT bridge (Python)
  bridge.py         Kafka consumer + MQTT publisher
  darwin.py         Darwin Push Port JSON parser
  config.py         Non-secret config + .env loader
  .env.example      Credentials template — copy to .env and fill in

pico/       Pico 2W MicroPython
  main.py           Boot entry point
  mqtt.py           MQTT subscriber (TLS)
  display.py        Pimoroni picographics driver (320×240)
  trains.py         Status formatting helpers
  config.example.py WiFi + MQTT credentials template

main.py     Desktop test tool (RTT API)
tests/      pytest suite for the bridge parser + display logic
```
