import time

import ujson
from umqtt.robust import MQTTClient

_TOPIC_OUT = b"trains/WAT/FNH"   # outbound: Waterloo -> Farnham
_TOPIC_RET = b"trains/FNH/WAT"   # return:   Farnham -> Waterloo
_TOPIC_WC = b"lines/waterloo-city"
_TOPIC_HB = b"trains/heartbeat"  # periodic liveness ping from the bridge
_client = None
_trains_out = []
_trains_ret = []
_wc_status = None
_wc_reason = ""
_last_msg_ms = None


def _on_message(topic, payload):
    global _trains_out, _trains_ret, _wc_status, _wc_reason, _last_msg_ms
    _last_msg_ms = time.ticks_ms()
    try:
        if topic == _TOPIC_OUT:
            _trains_out = ujson.loads(payload)
        elif topic == _TOPIC_RET:
            _trains_ret = ujson.loads(payload)
        elif topic == _TOPIC_WC:
            doc = ujson.loads(payload)
            _wc_status = doc.get("status")
            _wc_reason = doc.get("reason", "") or ""
    except Exception as e:
        print("MQTT parse error:", e)


def connect(host, port=8883, user=None, password=None, client_id="pico-trains"):
    global _client
    ssl_params = {"server_hostname": host}
    _client = MQTTClient(
        client_id, host, port=port,
        user=user, password=password,
        keepalive=60, ssl=True, ssl_params=ssl_params,
    )
    _client.set_callback(_on_message)
    _client.connect()
    _client.subscribe(_TOPIC_OUT)
    _client.subscribe(_TOPIC_RET)
    _client.subscribe(_TOPIC_WC)
    _client.subscribe(_TOPIC_HB)


def check():
    if _client:
        _client.check_msg()


def get_trains(outbound=True):
    return _trains_out if outbound else _trains_ret


def get_wc_status():
    return _wc_status


def get_wc_reason():
    return _wc_reason


def seconds_since_message():
    """Seconds since the last MQTT message, or None if nothing received yet."""
    if _last_msg_ms is None:
        return None
    return time.ticks_diff(time.ticks_ms(), _last_msg_ms) // 1000
