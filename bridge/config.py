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
MQTT_USER = os.environ["MQTT_USER"]
MQTT_PASSWORD = os.environ["MQTT_PASSWORD"]
MQTT_TOPIC = "trains/WAT/FNH"
MQTT_TOPIC_RETURN = "trains/FNH/WAT"
MQTT_WC_TOPIC = "lines/waterloo-city"
