"""Flask web client: renders the departures board as htmx-swappable HTML.

Run from the repo root:  uv run python web/server.py
"""

import logging
from pathlib import Path

from flask import Flask, abort, render_template, request

import config
import formatting as fmt
import state as state_mod

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))

STATE = state_mod.start()

_STALE_SECS = 120  # no heartbeat for this long -> feed considered stale


def _board_context(direction: str) -> dict:
    if direction not in config.DIRECTIONS:
        abort(404)
    now_mins = fmt.now_london_mins()
    trains = [fmt.view_model(t, now_mins) for t in STATE.trains(direction)]
    secs = STATE.seconds_since_heartbeat()
    other = "ret" if direction == "out" else "out"
    return {
        "dir": direction,
        "other": other,
        "meta": config.DIRECTIONS[direction],
        "other_meta": config.DIRECTIONS[other],
        "trains": trains,
        "alerts": STATE.alerts(direction),
        "wc": STATE.wc(),
        "stale": secs is None or secs >= _STALE_SECS,
        "connected": STATE.connected,
    }


@app.route("/")
def index():
    direction = request.args.get("dir", "out")
    if direction not in config.DIRECTIONS:
        direction = "out"
    return render_template("index.html", **_board_context(direction))


@app.route("/board")
def board():
    direction = request.args.get("dir", "out")
    return render_template("_board.html", **_board_context(direction))


if __name__ == "__main__":
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, threaded=True)
