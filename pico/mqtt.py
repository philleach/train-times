import ujson
from umqtt.robust import MQTTClient

_TOPIC = b"trains/WAT/FNH"
_client = None
_trains = []


def _on_message(topic, payload):
    global _trains
    try:
        _trains = ujson.loads(payload)
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
    _client.subscribe(_TOPIC)


def check():
    """Call regularly to process incoming messages."""
    if _client:
        _client.check_msg()


def get_trains():
    return _trains
