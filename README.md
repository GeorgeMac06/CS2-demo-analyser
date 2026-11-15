# CS2 Demo Scout

Multi-demo, single-map CS2 analyser that profiles a team's patterns and playstyles (team-wide and per player) for league scouting.

Status: WU-0 to WU-7 done (import, team detection, stats and findings API; no UI yet). See the [delivery plan](docs/delivery/delivery-plan.md) for what comes next.

- Requirements: `docs/product/requirements.md`
- Architecture: `docs/architecture/` (baseline, target design, ADRs)
- Delivery: `docs/delivery/` (delivery plan WU-0..16, test strategy)

## Run

Needs [uv](https://docs.astral.sh/uv/) and Windows 11. uv installs Python 3.13 if needed.

```bash
uv sync
uv run cs2scout assets fetch
uv run cs2scout
```

`assets fetch` runs once. It downloads the map radar images and coordinates (about 3 MB) from a pinned awpy-data release and checks them against pinned SHA-256 hashes. This is the app's only download. Without it, stats still work but heatmaps cannot be drawn on the map.

The server listens on `http://127.0.0.1:8765` only. It never listens on the network.

| Variable | Default | Purpose |
|---|---|---|
| `CS2SCOUT_HOME` | `%LOCALAPPDATA%\CS2DemoScout` | Workspace: library, extracts, retained demos, logs |
| `CS2SCOUT_PORT` | `8765` | Local port |

## Develop

Enable the pre-commit hook once per clone. It runs the G-fast gate:

```bash
git config core.hooksPath .githooks
```

| Gate | Command |
|---|---|
| G-fast | `uv run ruff format --check . && uv run ruff check . && uv run lint-imports && uv run pytest` |
| G-demos | `uv run pytest -m demos --require-demos` (needs `tests/local_fixtures/`, not in git) |
| G-browser | `uv run pytest -m browser` (one-time setup: `uv run playwright install chromium`) |

Real demos go in `tests/local_fixtures/demos/`. That folder is never committed, because demos contain real players' SteamIDs. No scoreboard data is needed: accuracy tests check our stats against the server's own counters recorded in each demo.
