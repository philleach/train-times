# Copy to config.py and fill in values. Never commit config.py.
WIFI_SSID = "your-wifi-ssid"
WIFI_PASSWORD = "your-wifi-password"
# Optional fallback networks, tried in order if the primary fails (handy for
# offsite testing — e.g. a phone hotspot). Leave empty if not needed.
WIFI_FALLBACKS = [
    # ("hotspot-ssid", "hotspot-password"),
]
MQTT_HOST = "efac7ce3a9e7452cb6acc38d6349b2f6.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_USER = "train-times-bridge"
MQTT_PASSWORD = "your-mqtt-password"
UTC_OFFSET = 1  # BST = UTC+1; change to 0 in winter
