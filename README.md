# train-times

Internet-connected embedded display showing upcoming Waterloo → Farnham train departures with live arrival predictions.

**Architecture:** Darwin RTII Kafka (Confluent Cloud) → Pi bridge → HiveMQ Cloud (MQTT TLS) → Pico 2W → Pimoroni 2.8" display

## Hardware

| Part | Notes |
|------|-------|
| Raspberry Pi (any model) | Runs the Darwin→MQTT bridge |
| Raspberry Pi Pico 2W | RP2350, drives the display |
| Pimoroni Pico Display Pack 2.8" | ST7789, 320×240, plugs onto Pico header |

## Prerequisites

- **Darwin RTII subscription** — sign up at [networkrail.co.uk](https://www.networkrail.co.uk/who-we-are/innovation-and-technology/information-feeds/), then find your Confluent Cloud credentials in the portal
- **HiveMQ Cloud account** — free tier at [hivemq.com/cloud](https://www.hivemq.com/cloud/); create a cluster and a set of credentials
- **Pimoroni MicroPython firmware** flashed to the Pico 2W — use the **pico2w** build (RP2350) from the [Pimoroni releases page](https://github.com/pimoroni/pimoroni-pico/releases), not the plain pico or picow build

## Pi bridge setup

```bash
# 1. Install dependencies
pip install confluent-kafka paho-mqtt

# 2. Set credentials
cp pi/.env.example pi/.env
# Edit pi/.env — fill in Confluent Cloud and HiveMQ credentials

# 3. Run
cd pi && set -a && source .env && set +a && python bridge.py
```

**Debug mode** — print raw Darwin payloads to verify JSON field names:

```bash
cd pi && set -a && source .env && set +a && DEBUG_RAW=1 python bridge.py
```

### Credentials (`pi/.env`)

```
KAFKA_API_KEY=your-confluent-api-key
KAFKA_API_SECRET=your-confluent-api-secret
MQTT_HOST=abc123.s2.eu.hivemq.cloud
MQTT_USER=your-hivemq-username
MQTT_PASSWORD=your-hivemq-password
```

### Run as a systemd service

```ini
# /etc/systemd/system/train-times.service
[Unit]
Description=Darwin → MQTT train times bridge
After=network-online.target

[Service]
WorkingDirectory=/home/pi/train-times/pi
EnvironmentFile=/home/pi/train-times/pi/.env
ExecStart=/usr/bin/python bridge.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now train-times
sudo journalctl -fu train-times
```

## Pico 2W setup

1. Flash the [Pimoroni pico2w MicroPython firmware](https://github.com/pimoroni/pimoroni-pico/releases) (RP2350 build)
2. Copy the `pico/` directory contents to the Pico root (exclude `config.example.py`)
3. Create `pico/config.py` from the example and fill in values:

```python
WIFI_SSID     = "your-wifi-ssid"
WIFI_PASSWORD = "your-wifi-password"
MQTT_HOST     = "abc123.s2.eu.hivemq.cloud"
MQTT_PORT     = 8883
MQTT_USER     = "your-hivemq-username"
MQTT_PASSWORD = "your-hivemq-password"
```

4. The Pico boots `main.py` automatically — it connects to WiFi, sets the time via NTP, subscribes to MQTT, and starts rendering departures.

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
pi/         Raspberry Pi bridge (Python)
  bridge.py         Kafka consumer + MQTT publisher
  darwin.py         Darwin Push Port JSON parser
  config.py         Non-secret config (bootstrap, topic)
  .env.example      Credentials template — copy to .env and fill in

pico/       Pico 2W MicroPython
  main.py           Boot entry point
  mqtt.py           MQTT subscriber (TLS)
  display.py        Pimoroni picographics driver (320×240)
  trains.py         Status formatting helpers
  config.example.py WiFi + MQTT credentials template

main.py     Desktop test tool (RTT API)
```
