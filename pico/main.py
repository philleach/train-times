import time

import machine
import network
import ntptime

import config
import display
import mqtt


def _init_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    return wlan


def _ensure_connected(wlan):
    if wlan.isconnected():
        return True
    display.show_status("Connecting WiFi...")
    wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
    for _ in range(20):
        if wlan.isconnected():
            return True
        time.sleep(1)
    return False


def main():
    wlan = _init_wifi()

    if not _ensure_connected(wlan):
        display.show_status("WiFi failed")
        time.sleep(30)
        machine.reset()

    try:
        ntptime.settime()
    except Exception:
        pass

    display.show_status("Connecting MQTT...")
    mqtt.connect(config.MQTT_HOST, config.MQTT_PORT, config.MQTT_USER, config.MQTT_PASSWORD)
    display.show_status("Waiting for trains...")

    while True:
        if not wlan.isconnected():
            display.show_status("WiFi lost")
            time.sleep(30)
            machine.reset()

        try:
            mqtt.check()
            display.render(mqtt.get_trains())
        except Exception as e:
            print("loop error:", e)

        time.sleep(1)


main()
