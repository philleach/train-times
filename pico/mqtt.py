import time

import ujson
from umqtt.simple import MQTTClient

_TOPIC_OUT = b"trains/WAT/FNH"   # outbound: Waterloo -> Farnham
_TOPIC_RET = b"trains/FNH/WAT"   # return:   Farnham -> Waterloo
_TOPIC_CALL_OUT = b"trains/WAT/FNH/calling"  # next outbound train's calling points
_TOPIC_CALL_RET = b"trains/FNH/WAT/calling"  # next return train's calling points
_TOPIC_WC = b"lines/waterloo-city"
_TOPIC_HB = b"trains/heartbeat"  # periodic liveness ping from the bridge
_TOPICS = (_TOPIC_OUT, _TOPIC_RET, _TOPIC_CALL_OUT, _TOPIC_CALL_RET, _TOPIC_WC, _TOPIC_HB)

# We only ever subscribe, never publish, so the broker would drop our idle
# connection after ~1.5x keepalive. Ping well inside that window to stay alive.
_KEEPALIVE = 60
_PING_INTERVAL_MS = 30_000

_client = None
_conn = None          # saved params for reconnect
_last_ping_ms = 0
_trains_out = []
_trains_ret = []
_calling_out = None
_calling_ret = None
_wc_status = None
_wc_reason = ""
_last_msg_ms = None


def _on_message(topic, payload):
    global _trains_out, _trains_ret, _calling_out, _calling_ret
    global _wc_status, _wc_reason, _last_msg_ms
    _last_msg_ms = time.ticks_ms()
    try:
        if topic == _TOPIC_OUT:
            _trains_out = ujson.loads(payload)
        elif topic == _TOPIC_RET:
            _trains_ret = ujson.loads(payload)
        elif topic == _TOPIC_CALL_OUT:
            _calling_out = ujson.loads(payload)
        elif topic == _TOPIC_CALL_RET:
            _calling_ret = ujson.loads(payload)
        elif topic == _TOPIC_WC:
            doc = ujson.loads(payload)
            _wc_status = doc.get("status")
            _wc_reason = doc.get("reason", "") or ""
        # _TOPIC_HB needs no handling beyond the freshness stamp above
    except Exception as e:
        print("MQTT parse error:", e)


def _make_client():
    host = _conn["host"]
    return MQTTClient(
        _conn["client_id"], host, port=_conn["port"],
        user=_conn["user"], password=_conn["password"],
        keepalive=_KEEPALIVE, ssl=True, ssl_params={"server_hostname": host},
    )


def _connect_and_subscribe():
    global _client, _last_ping_ms
    _client = _make_client()
    _client.set_callback(_on_message)
    _client.connect()
    for topic in _TOPICS:
        _client.subscribe(topic)
    _last_ping_ms = time.ticks_ms()


def connect(host, port=8883, user=None, password=None, client_id="pico-trains"):
    global _conn
    _conn = {"host": host, "port": port, "user": user,
             "password": password, "client_id": client_id}
    _connect_and_subscribe()


def check():
    """Process incoming messages and keep the connection alive. Reconnects and
    re-subscribes if the link drops (otherwise the broker stops delivering)."""
    global _last_ping_ms
    if _client is None:
        return
    try:
        _client.check_msg()
        if time.ticks_diff(time.ticks_ms(), _last_ping_ms) >= _PING_INTERVAL_MS:
            _client.ping()
            _last_ping_ms = time.ticks_ms()
    except (OSError, MemoryError) as e:
        print("MQTT reconnecting:", e)
        try:
            _connect_and_subscribe()
        except OSError as e2:
            print("MQTT reconnect failed:", e2)


def get_trains(outbound=True):
    return _trains_out if outbound else _trains_ret


def get_calling(outbound=True):
    return _calling_out if outbound else _calling_ret


def get_wc_status():
    return _wc_status


def get_wc_reason():
    return _wc_reason


def seconds_since_message():
    """Seconds since the last MQTT message, or None if nothing received yet."""
    if _last_msg_ms is None:
        return None
    return time.ticks_diff(time.ticks_ms(), _last_msg_ms) // 1000
