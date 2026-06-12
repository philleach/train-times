# Pimoroni Pico Display Pack 2.8" (ST7789, 320x240)
import time

from picographics import DISPLAY_PICO_DISPLAY_2, PicoGraphics

import config
from trains import format_status

display = PicoGraphics(display=DISPLAY_PICO_DISPLAY_2)
WIDTH, HEIGHT = display.get_bounds()  # 320x240

_WHITE = display.create_pen(255, 255, 255)
_GREEN = display.create_pen(0, 210, 90)
_AMBER = display.create_pen(255, 160, 0)
_RED = display.create_pen(220, 30, 30)
_GREY = display.create_pen(80, 80, 100)
_BG = display.create_pen(0, 0, 40)

# bitmap8 scale=2: 16px tall, 16px wide per character (monospaced)
_FONT = "bitmap8"
_SCALE = 2
_CHAR_H = 16

_ROW_H = 44
_FIRST_ROW_Y = 38
_MAX_TRAINS = 4

_COL_TIME = 4
_COL_PLT = 92     # 4 + 5 chars*16 + 8
_COL_STATUS = 148  # 92 + 3 chars*16 + 8


def _status_colour(status):
    if status == "CANC":
        return _RED
    if status == "ON TIME":
        return _GREEN
    return _AMBER


def _draw_header():
    t = time.localtime()
    hour = (t[3] + config.UTC_OFFSET) % 24
    clock = "{:02d}:{:02d}".format(hour, t[4])
    display.set_font(_FONT)
    display.set_pen(_WHITE)
    display.text("WAT->FNH", _COL_TIME, 8, scale=_SCALE)
    tw = display.measure_text(clock, scale=_SCALE)
    display.text(clock, WIDTH - tw - 4, 8, scale=_SCALE)
    display.set_pen(_GREY)
    display.line(0, 30, WIDTH, 30)


def _draw_train(train, y):
    std = train.get("std") or "--:--"
    platform = train.get("platform") or "-"
    eta_fnh = train.get("eta_fnh")
    status = format_status(train)

    display.set_font(_FONT)

    # Line 1: departure time, platform, status
    display.set_pen(_WHITE)
    display.text(std, _COL_TIME, y, scale=_SCALE)
    display.text("P" + str(platform), _COL_PLT, y, scale=_SCALE)
    display.set_pen(_status_colour(status))
    display.text(status, _COL_STATUS, y, scale=_SCALE)

    # Line 2: predicted arrival at Farnham
    arr_y = y + _CHAR_H + 6
    display.set_pen(_GREY)
    display.text("arr", _COL_TIME, arr_y, scale=_SCALE)
    display.set_pen(_WHITE if eta_fnh else _GREY)
    display.text(eta_fnh or "--:--", _COL_TIME + 56, arr_y, scale=_SCALE)


def render(trains):
    display.set_pen(_BG)
    display.clear()
    _draw_header()

    visible = trains[:_MAX_TRAINS]
    for i, train in enumerate(visible):
        _draw_train(train, _FIRST_ROW_Y + i * _ROW_H)

    if not visible:
        display.set_pen(_GREY)
        display.set_font(_FONT)
        display.text("No trains", _COL_TIME, HEIGHT // 2, scale=_SCALE)

    display.update()


def show_status(message):
    display.set_pen(_BG)
    display.clear()
    display.set_pen(_WHITE)
    display.set_font(_FONT)
    display.text(message, _COL_TIME, HEIGHT // 2, scale=_SCALE)
    display.update()
