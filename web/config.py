import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
# TLS to the broker. On for a cloud/Funnel broker; off for a local plaintext
# Mosquitto on loopback (Funnel terminates the public TLS).
MQTT_TLS = os.getenv("MQTT_TLS", "1") not in ("0", "false", "False", "")
MQTT_USER = os.environ["MQTT_USER"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]

WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))

# Topic layout published by the bridge (all retained, so we get current state on
# connect). Keyed by direction: "out" = WAT->FNH, "ret" = FNH->WAT.
TOPICS = {
    "out": "trains/WAT/FNH",
    "ret": "trains/FNH/WAT",
}
WC_TOPIC = "lines/waterloo-city"
HEARTBEAT_TOPIC = "trains/heartbeat"

# Per direction we also subscribe to <topic>/alerts and <topic>/calling.
ALL_SUBSCRIPTIONS = (
    [t for t in TOPICS.values()]
    + [t + "/alerts" for t in TOPICS.values()]
    + [t + "/calling" for t in TOPICS.values()]
    + [WC_TOPIC, HEARTBEAT_TOPIC]
)

DIRECTIONS = {
    "out": {"title": "WAT → FNH", "from": "Waterloo", "to": "Farnham"},
    "ret": {"title": "FNH → WAT", "from": "Farnham", "to": "Waterloo"},
}
