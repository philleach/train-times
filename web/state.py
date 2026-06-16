"""MQTT subscriber holding the latest retained payload for every topic.

The bridge publishes everything with retain=True, so on connect we immediately
receive current state. We just cache the most recent payload per topic behind a
lock; the web routes read from the cache (no blocking on MQTT per request).
"""

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

import config

log = logging.getLogger(__name__)


class State:
    def __init__(self):
        self._lock = threading.Lock()
        self._payloads: dict[str, str] = {}
        self._last_heartbeat: float = 0.0
        self._connected = False

    # ---- MQTT callbacks ------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            log.warning("MQTT connect failed: %s", reason_code)
            return
        self._connected = True
        for topic in config.ALL_SUBSCRIPTIONS:
            client.subscribe(topic)
        log.info("MQTT connected; subscribed to %d topics", len(config.ALL_SUBSCRIPTIONS))

    def _on_disconnect(self, client, userdata, *args):
        self._connected = False
        log.warning("MQTT disconnected")

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", "replace")
        if msg.topic == config.HEARTBEAT_TOPIC:
            self._last_heartbeat = time.monotonic()
            return
        with self._lock:
            self._payloads[msg.topic] = payload

    # ---- accessors ----------------------------------------------------
    def _json(self, topic: str, default):
        with self._lock:
            raw = self._payloads.get(topic)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except ValueError:
            return default

    def trains(self, direction: str) -> list:
        return self._json(config.TOPICS[direction], [])

    def alerts(self, direction: str) -> list:
        return self._json(config.TOPICS[direction] + "/alerts", [])

    def calling(self, direction: str) -> dict:
        return self._json(config.TOPICS[direction] + "/calling", {})

    def wc(self) -> dict:
        return self._json(config.WC_TOPIC, {})

    def seconds_since_heartbeat(self):
        if not self._last_heartbeat:
            return None
        return time.monotonic() - self._last_heartbeat

    @property
    def connected(self) -> bool:
        return self._connected


def start() -> State:
    """Create the State and a background MQTT client connected to the broker."""
    state = State()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config.MQTT_TLS:
        client.tls_set()
    client.username_pw_set(config.MQTT_USER, config.MQTT_PASSWORD)
    client.on_connect = state._on_connect
    client.on_disconnect = state._on_disconnect
    client.on_message = state._on_message
    client.reconnect_delay_set(min_delay=2, max_delay=30)
    client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    client.loop_start()
    return state
