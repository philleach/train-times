# web — mobile train client

A mobile-friendly web client for the Waterloo ↔ Farnham departures, for use in
transit. It's a pure **view** over the same retained MQTT topics the bridge
already publishes (departures, W&C line status, disruption alerts) — no copy of
the Darwin/LDBSV logic. Rendered as htmx-swappable HTML styled with Tailwind.

## Architecture

```
browser ──HTTP──> Flask (htmx fragments) ──MQTT sub──> broker <──pub── bridge
```

`state.py` subscribes once and caches the latest retained payload per topic; the
board self-refreshes every 15s (`hx-trigger="every 15s"`) and the direction
toggle swaps the `/board` fragment.

## Run

Deps are in the repo-root `pyproject.toml`, so use the shared `uv` env:

```bash
uv sync
cp web/.env.example web/.env   # broker host + a read login
uv run python web/server.py    # http://localhost:8000
```

Tailwind and htmx load from CDNs — no front-end build step.

## Deploy

Intended to run on the same box as the bridge/broker, exposed via Tailscale
Funnel. Bind loopback (`WEB_HOST`) and let Funnel terminate TLS. If pointing at
the local Mosquitto, set `MQTT_TLS=0` and `MQTT_HOST` to loopback. Prefer a
read-only broker login rather than reusing the bridge's publish credentials.
