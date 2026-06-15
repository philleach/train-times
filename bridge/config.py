import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

KAFKA_BOOTSTRAP = "pkc-z3p1v0.europe-west2.gcp.confluent.cloud:9092"
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "darwin-pushport-json")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "train-times-bridge")

KAFKA_API_KEY = os.environ["KAFKA_API_KEY"]
KAFKA_API_SECRET = os.environ["KAFKA_API_SECRET"]

MQTT_HOST = os.environ["MQTT_HOST"]
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
# TLS to the broker. Off when publishing to a local plaintext Mosquitto on
# loopback (Tailscale Funnel terminates the public TLS); on for direct cloud brokers.
MQTT_TLS = os.getenv("MQTT_TLS", "1") not in ("0", "false", "False", "")
MQTT_USER = os.environ["MQTT_USER"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]

# OpenLDBSVWS (Live Departure Boards, Staff Version) REST API — used to fill in
# coach formation when Darwin's Push Port doesn't carry it. Optional: leave
# LDBSV_KEY unset to disable the lookup.
LDBSV_KEY = os.getenv("LDBSV_KEY", "")
LDBSV_BASE_URL = os.getenv("LDBSV_BASE_URL", "https://realtime.nationalrail.co.uk/LDBSVWS")

MQTT_TOPIC = "trains/WAT/FNH"
MQTT_TOPIC_RETURN = "trains/FNH/WAT"
MQTT_WC_TOPIC = "lines/waterloo-city"
MQTT_HEARTBEAT_TOPIC = "trains/heartbeat"
