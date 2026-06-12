# Pimoroni Pico Display Pack 2.8" (ST7789, 320x240)
import time

from picographics import DISPLAY_PICO_DISPLAY_2, PicoGraphics

import config
from trains import format_status, mins_until, severity, short_status

display = PicoGraphics(display=DISPLAY_PICO_DISPLAY_2)
WIDTH, HEIGHT = display.get_bounds()  # 320x240

_TEXT = display.create_pen(20, 20, 20)
_GREEN = display.create_pen(0, 140, 60)
_AMBER = display.create_pen(180, 100, 0)
_RED = display.create_pen(190, 20, 20)
_GREY = display.create_pen(140, 140, 150)
_LIGHT_BLUE = display.create_pen(80, 180, 230)
_BG = display.create_pen(180, 230, 190)
_BAND = display.create_pen(165, 218, 178)   # alternating row shade

# bitmap8: scale 2 = 16px tall/wide, scale 3 = 24px (monospaced)
_FONT = "bitmap8"
_SCALE = 2
_BIG = 3
_CHAR_H = 16

# Vertical layout
_HEADER_Y = 4
_HEADER_LINE = 24
_WC_Y = 30
_WC_LINE = 50
_NEXT_Y = 54           # big departure time
_NEXT_L2_Y = 84        # platform / arrival / status
_NEXT_LINE = 104
_COMPACT_START = 106
_COMPACT_ROW_H = 44    # 3 rows: 106, 150, 194 -> 238
_COMPACT_ROWS = 3

# Compact-row columns
_C_STD = 4
_C_PLT = 90
_C_ARR = 150

_STALE_SECS = 120      # no heartbeat for this long -> feed considered stale


def _blink(period_ms=500):
    return (time.ticks_ms() // period_ms) % 2 == 0


def _now_mins():
    t = time.localtime()
    hour = (t[3] + config.UTC_OFFSET) % 24
    return hour * 60 + t[4]


def _text_right(s, x_right, y, scale=_SCALE):
    tw = display.measure_text(s, scale=scale)
    display.text(s, x_right - tw, y, scale=scale)


def _status_colour(status):
    if status == "CANC":
        return _RED
    if status == "ON TIME":
        return _GREEN
    return _AMBER


def _severity_colour(train):
    return (_GREEN, _AMBER, _RED)[severity(train)]


def _wc_colour(status):
    if status is None:
        return _GREY
    s = status.lower()
    if "good" in s:
        return _GREEN
    if "delay" in s or "part" in s or "minor" in s:
        return _AMBER
    return _RED


# ---------------------------------------------------------------- header

def _draw_header(title, stale):
    t = time.localtime()
    hour = (t[3] + config.UTC_OFFSET) % 24
    clock = "{:02d}:{:02d}".format(hour, t[4])
    display.set_font(_FONT)
    display.set_pen(_TEXT)
    display.text(title, _C_STD, _HEADER_Y, scale=_SCALE)

    # heartbeat dot: green pulse when live, solid red when stale
    dot_x, dot_y = WIDTH - 8, _HEADER_Y + 8
    if stale:
        display.set_pen(_RED)
        display.circle(dot_x, dot_y, 4)
    elif _blink():
        display.set_pen(_GREEN)
        display.circle(dot_x, dot_y, 4)

    display.set_pen(_TEXT)
    _text_right(clock, WIDTH - 18, _HEADER_Y)
    display.set_pen(_GREY)
    display.line(0, _HEADER_LINE, WIDTH, _HEADER_LINE)


# ------------------------------------------------------------------- W&C

def _draw_wc(status, reason, stale, now_mins):
    display.set_font(_FONT)
    label = "W&C:"
    label_w = display.measure_text(label, scale=_SCALE) + 12
    text_x = _C_STD + label_w

    disrupted = status is not None and "good" not in status.lower()
    if disrupted and reason:
        # scroll "<status> - <reason>" through the area right of the label
        msg = status + " - " + reason + "    "
        msg_w = display.measure_text(msg, scale=_SCALE)
        avail = WIDTH - text_x - 4
        offset = (time.ticks_ms() // 40) % msg_w
        display.set_pen(_wc_colour(status))
        x = text_x - offset
        # draw twice so it wraps seamlessly
        while x < text_x + avail:
            display.text(msg, x, _WC_Y, scale=_SCALE)
            x += msg_w
    else:
        display.set_pen(_wc_colour(status))
        display.text(status or "Unknown", text_x, _WC_Y, scale=_SCALE)

    # label drawn last (over a bg patch) so scrolling text passes behind it
    display.set_pen(_BG)
    display.rectangle(0, _WC_Y - 2, text_x, _CHAR_H + 4)
    display.set_pen(_LIGHT_BLUE)
    display.text(label, _C_STD, _WC_Y, scale=_SCALE)

    if stale:
        display.set_pen(_RED if _blink() else _GREY)
        _text_right("STALE", WIDTH - 4, _WC_Y)

    display.set_pen(_GREY)
    display.line(0, _WC_LINE, WIDTH, _WC_LINE)


# ------------------------------------------------------- next-train block

def _countdown_text(mins):
    if mins is None:
        return "", _GREY
    if mins <= 0:
        return "DEP", _RED
    if mins == 1:
        return "1 min", _RED
    if mins <= 5:
        return "in {}m".format(mins), _AMBER
    return "in {}m".format(mins), _TEXT


def _draw_next(train, muted, now_mins):
    std = train.get("std") or "--:--"
    platform = train.get("platform")
    eta_dest = train.get("eta_dest")
    status = format_status(train)
    mins = mins_until(std, now_mins)
    departing = mins is not None and mins <= 0

    display.set_font(_FONT)

    # Big departure time (blink if departing)
    if departing and not _blink():
        display.set_pen(_GREY)
    else:
        display.set_pen(_GREY if muted else _TEXT)
    display.text(std, _C_STD, _NEXT_Y, scale=_BIG)

    # Countdown beside it
    cd_text, cd_pen = _countdown_text(mins)
    if muted:
        cd_pen = _GREY
    if not (mins is not None and mins <= 1 and not _blink()):  # blink when imminent
        display.set_pen(cd_pen)
        display.text(cd_text, _C_STD + 5 * 24 + 14, _NEXT_Y + 4, scale=_SCALE)

    # Coach count from scheduleFormation, top-right (grey, away from status)
    length = train.get("length")
    if length:
        display.set_pen(_GREY)
        _text_right("{} cars".format(length), WIDTH - 4, _NEXT_Y + 4)

    # Line 2: platform, arrival, status
    if platform:
        display.set_pen(_GREY if muted else _TEXT)
        display.text("P" + str(platform), _C_STD, _NEXT_L2_Y, scale=_SCALE)
    else:
        display.set_pen(_GREY)
        display.text("P--", _C_STD, _NEXT_L2_Y, scale=_SCALE)

    display.set_pen(_GREY if (muted or not eta_dest) else _severity_colour(train))
    display.text(">" + (eta_dest or "--:--"), 70, _NEXT_L2_Y, scale=_SCALE)

    display.set_pen(_GREY if muted else _status_colour(status))
    _text_right(status, WIDTH - 4, _NEXT_L2_Y)

    display.set_pen(_GREY)
    display.line(0, _NEXT_LINE, WIDTH, _NEXT_LINE)


# ---------------------------------------------------------- compact rows

def _draw_compact(train, index, muted, now_mins):
    row_y = _COMPACT_START + index * _COMPACT_ROW_H
    y = row_y + (_COMPACT_ROW_H - _CHAR_H) // 2

    # alternating band
    if index % 2 == 1:
        display.set_pen(_BAND)
        display.rectangle(0, row_y, WIDTH, _COMPACT_ROW_H)

    std = train.get("std") or "--:--"
    platform = train.get("platform")
    eta_dest = train.get("eta_dest")
    short = short_status(train)
    mins = mins_until(std, now_mins)
    departing = mins is not None and mins <= 0

    display.set_font(_FONT)

    if departing and not _blink():
        display.set_pen(_GREY)
    else:
        display.set_pen(_GREY if muted else _TEXT)
    display.text(std, _C_STD, y, scale=_SCALE)

    if platform:
        display.set_pen(_GREY if muted else _TEXT)
        display.text("P" + str(platform), _C_PLT, y, scale=_SCALE)
    else:
        display.set_pen(_GREY)
        display.text("P--", _C_PLT, y, scale=_SCALE)

    display.set_pen(_GREY if (muted or not eta_dest) else _severity_colour(train))
    display.text(">" + (eta_dest or "--:--"), _C_ARR, y, scale=_SCALE)

    display.set_pen(_GREY if muted else _status_colour(format_status(train)))
    _text_right(short, WIDTH - 4, y)


# --------------------------------------------------------------- public

def render(trains, title="WAT->FNH", wc_status=None, wc_reason="", stale_secs=None):
    stale = stale_secs is not None and stale_secs >= _STALE_SECS
    muted = stale  # grey everything out when the feed is stale
    now_mins = _now_mins()

    display.set_pen(_BG)
    display.clear()
    _draw_header(title, stale)
    _draw_wc(wc_status, wc_reason, stale, now_mins)

    if not trains:
        display.set_pen(_GREY)
        display.set_font(_FONT)
        display.text("No trains", _C_STD, _NEXT_Y + 10, scale=_SCALE)
        display.update()
        return

    _draw_next(trains[0], muted, now_mins)
    for i, train in enumerate(trains[1:1 + _COMPACT_ROWS]):
        _draw_compact(train, i, muted, now_mins)

    display.update()


def show_status(message):
    display.set_pen(_BG)
    display.clear()
    display.set_pen(_TEXT)
    display.set_font(_FONT)
    display.text(message, _C_STD, HEIGHT // 2, scale=_SCALE)
    display.update()
