# Copy to config.py and fill in values. Never commit config.py.
WIFI_SSID = "your-wifi-ssid"
WIFI_PASSWORD = "your-wifi-password"
# Optional fallback networks, tried in order if the primary fails (handy for
# offsite testing — e.g. a phone hotspot). Leave empty if not needed.
WIFI_FALLBACKS = [
    # ("hotspot-ssid", "hotspot-password"),
]
# Self-hosted Mosquitto exposed via Tailscale Funnel: connect on 443 over TLS
# (the Funnel terminates TLS and forwards to the broker). Use the Funnel
# hostname here, not a HiveMQ host.
MQTT_HOST = "rene.tail99dd83.ts.net"
MQTT_PORT = 443
MQTT_USER = "train-times"
MQTT_PASSWORD = "your-mqtt-password"
# GMT/BST is derived automatically from the (UTC) clock — no manual offset needed.
