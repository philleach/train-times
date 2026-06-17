import time

import machine
import network
import ntptime
from pimoroni import RGBLED, Button

import config
import display
import mqtt
from trains import london_offset, severity

# Pico Display Pack 2.8": onboard RGB LED + 4 buttons
_led = RGBLED(6, 7, 8)
_button_a = Button(12)   # toggle direction (WAT->FNH / FNH->WAT)
_button_b = Button(13)   # toggle view (departures / calling points)
_button_x = Button(14)   # brighter
_button_y = Button(15)   # dimmer

_LED_OFF = (0, 0, 0)
_LED_BY_SEVERITY = ((0, 80, 30), (90, 45, 0), (90, 0, 0))  # green / amber / red

# Brightness: None = follow the day/night schedule; a float overrides it.
_manual_brightness = None
# Direction: True = outbound (WAT->FNH), False = return (FNH->WAT)
_outbound = True
# View: False = departures board, True = next train's calling points
_calling_view = False
_STALE_SECS = 120


def _init_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    return wlan


def _networks():
    """Primary network first, then any optional fallbacks from config."""
    nets = [(config.WIFI_SSID, config.WIFI_PASSWORD)]
    nets += list(getattr(config, "WIFI_FALLBACKS", []))
    return nets


def _ensure_connected(wlan):
    if wlan.isconnected():
        return True
    for ssid, password in _networks():
        display.show_status("WiFi: " + ssid)
        wlan.connect(ssid, password)
        for _ in range(15):
            if wlan.isconnected():
                return True
            time.sleep(1)
    return False


def _auto_brightness():
    t = time.localtime()
    hour = (t[3] + london_offset(t)) % 24
    return 0.3 if (hour >= 23 or hour < 6) else 1.0


def _handle_buttons():
    global _manual_brightness, _outbound, _calling_view
    current = _manual_brightness if _manual_brightness is not None else _auto_brightness()
    if _button_a.read():
        _outbound = not _outbound  # flip travel direction
    elif _button_b.read():
        _calling_view = not _calling_view  # departures <-> calling points
    elif _button_x.read():
        _manual_brightness = min(1.0, current + 0.1)
    elif _button_y.read():
        _manual_brightness = max(0.2, current - 0.1)


def _apply_backlight():
    level = _manual_brightness if _manual_brightness is not None else _auto_brightness()
    display.display.set_backlight(level)


def _update_led(trains, stale):
    if stale:
        # pulse red so a dead feed is obvious from across the room
        _led.set_rgb(*(_LED_BY_SEVERITY[2] if (time.ticks_ms() // 500) % 2 == 0 else _LED_OFF))
    elif trains:
        worst = max(severity(t) for t in trains[:4])
        _led.set_rgb(*_LED_BY_SEVERITY[worst])
    else:
        _led.set_rgb(*_LED_OFF)


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

    # Retry the initial connect, then reboot — otherwise a transient DNS/uplink
    # blip at boot (e.g. the upstream router still coming up) would throw out of
    # main() and leave the Pico dead at the REPL until a manual power-cycle.
    display.show_status("Connecting MQTT...")
    for _ in range(10):
        try:
            mqtt.connect(config.MQTT_HOST, config.MQTT_PORT, config.MQTT_USER, config.MQTT_PASSWORD)
            break
        except OSError as e:
            print("MQTT connect failed:", e)
            display.show_status("MQTT retry...")
            time.sleep(6)
    else:
        display.show_status("MQTT failed")
        time.sleep(10)
        machine.reset()
    display.show_status("Waiting for trains...")

    while True:
        if not wlan.isconnected():
            display.show_status("WiFi lost")
            time.sleep(30)
            machine.reset()

        try:
            _handle_buttons()
            _apply_backlight()
            mqtt.check()

            secs = mqtt.seconds_since_message()
            stale = secs is not None and secs >= _STALE_SECS
            trains = mqtt.get_trains(_outbound)
            title = "WAT->FNH" if _outbound else "FNH->WAT"

            if _calling_view:
                display.render_calling(mqtt.get_calling(_outbound), title, secs)
            else:
                display.render(trains, title, mqtt.get_wc_status(), mqtt.get_wc_reason(),
                               secs, mqtt.get_alerts(_outbound))
            _update_led(trains, stale)
        except Exception as e:
            print("loop error:", e)

        time.sleep(0.2)


main()
