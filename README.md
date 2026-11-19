# CS2 Demo Scout

A local web app for scouting a league opponent. Give it several demos of one team on one map. It finds the team's patterns and each player's habits, shows how often each one happened, and exports a brief for your teammates.

Status: v1 feature-complete (WU-0 to WU-16). Milestone M3 still needs the owner's final run-through on real demos. See the [delivery plan](docs/delivery/delivery-plan.md).

- Requirements: `docs/product/requirements.md`
- Architecture: `docs/architecture/` (baseline, target design, ADRs)
- Delivery: `docs/delivery/` (delivery plan, test strategy, versioning)
- Versions and what changed in each: [Releases](https://github.com/GeorgeMac06/CS2-demo-analyser/releases). `uv run cs2scout --version` shows the version you have.

## Install

You need Windows 11 and [uv](https://docs.astral.sh/uv/). uv installs Python 3.13 if it is missing.

```bash
uv sync
uv run cs2scout assets fetch
```

`assets fetch` only needs to run once. It downloads the map radar images and coordinates (about 3 MB) from a pinned awpy-data release, and checks them against pinned SHA-256 hashes. Without them, stats still work, but heatmaps and lineups are not drawn on the map.

## Run

```bash
uv run cs2scout
```

The app opens in your browser at `http://127.0.0.1:8765`. Stop it with Ctrl+C in the terminal. `uv run cs2scout serve --no-browser` starts it without opening a browser.

## Use it

Times everywhere are the in-game round timer, which shows 1:55 when freeze time ends: "at 1:35" means 20 seconds into the round.

1. **New analysis.** Drop `.dem`, `.dem.gz`, `.dem.bz2` or `.zip` files (FACEIT and ESEA downloads work as they are), or paste a folder path. The app finds the team that appears in every demo. You confirm the roster, marking stand-ins and anyone to leave out.
2. **Add demos** as the season goes on. Only new demos are parsed. Each update is a new version of the analysis, and labels you gave to patterns carry over to it.
3. **Explore.** The tabs are Overview, T side, CT side, Utility, Players and Demos. Use the filters for side, buy type, dates and overtime. Every number is shown as "k/n" (seen in k of n eligible rounds); click it to list those rounds. Name any pattern with ✎.
4. **Export.** The Export menu downloads one HTML file. Teammates can open it in any browser, offline. You choose the sections, whether to apply the current filters, and whether to include the map images.
5. **AI brief** (optional, see below).

## Settings

The **Settings** page (top bar) saves these in the workspace:

- **Buy classes:** eco up to $5,000 and force buy up to $20,000 of team equipment value. Pistol rounds are always rounds 1 and 13.
- **When a pattern counts:** at least 3 rounds, at least 10% of eligible rounds, and seen in at least 2 demos. Numbers based on fewer than 10 rounds are marked "low sample".
- **T setup checkpoints:** 15, 30 and 45 s after freeze time ends.
- **Keep a compressed copy of each demo:** on by default. The copy lets the app re-read demos after a parser upgrade, at about 150–260 MB per demo.
- **Workspace size limit:** shows a warning only, and never blocks anything.
- **Port:** applies after a restart.

Changed thresholds apply to an analysis when you update it. Its page offers "Update now". Updating does not re-parse any demo. The Settings page also shows disk use.

| Variable | Default | Purpose |
|---|---|---|
| `CS2SCOUT_HOME` | `%LOCALAPPDATA%\CS2DemoScout` | Workspace: library, parsed data, retained demos, settings, logs |
| `CS2SCOUT_PORT` | `8765`, or the port saved in Settings | Local port (wins over Settings) |
| `ANTHROPIC_API_KEY` | not set | Turns on the AI brief |
| `CS2SCOUT_AI_MODEL` | `claude-opus-5-5` | Claude model for the AI brief |

These variables can also go in a `.env` file in the workspace folder, or in the folder you start the app from.

## AI brief (optional)

With a Claude API key, the **AI brief** tab turns the analysis into a short anti-strat brief of what to expect, written like an IGL's notes. It starts with a few lines that sum the team up. Then come their T plays, each with where the five go, the utility that starts it, its pace and what they do after an early pick. After those: CT setups and reactions, pistol rounds, each player's habits, suggested counters and rounds worth watching.

- Put `ANTHROPIC_API_KEY=sk-ant-...` in `.env` in the workspace folder, then restart the app.
- **Preview what is sent** shows the exact data and instructions before anything leaves your PC. Nothing is sent until you click **Send to Claude**. The preview is valid for 10 minutes, and changing the filters needs a new one.
- What is sent: patterns that pass the support rule, with their counts; a short summary of each round (where each player was at 1:40, 1:25 and 1:10, each player's route, their utility, on T rounds the hit and who was away from it, every kill, the plant and the result); player nicknames; and demo dates and scores. It never includes demo files, SteamIDs or coordinates.
- Every claim must cite findings or rounds from the analysis, and is shown with them. A cited round shows its demo file and a `demo_gototick` command: open the demo in CS2 (`playdemo`) and paste the command into the console to jump to that round. Claims that cite nothing are dropped. If too many are dropped, the brief is rejected, and you can try again.
- A brief goes stale when the analysis changes. Only a brief that is not stale goes into exports, labelled "AI-generated".
- **Download as Markdown** saves the brief as a `.md` file that pastes cleanly into Discord and reads fine as plain text. The plays come first. What each one rests on, and the demo files, are in an appendix at the end. In the app, click **Evidence** under a play to see it.
- Each brief is one paid API call: about 65,000 input tokens for a 4-demo analysis (about $0.26 with the default model), plus the answer. Most of that is the round summaries. The brief shows the tokens it used and the list-price cost. `CS2SCOUT_AI_MODEL=claude-sonnet-5-5` halves the price, probably at some cost in quality.
- The instructions Claude gets are in `src/cs2scout/ai/instructions.md`. Edit them to change what the brief focuses on, then restart the app.
- `src/cs2scout/ai/callouts.json` turns the game's place names into the callouts players use (for example, Mirage's House is TV and Truck is car). Only Mirage is listed so far. On other maps, Claude uses the usual callouts. Edit the file to match your team's calls, then restart.

## Privacy

- The server listens on `127.0.0.1` only. Every API call and every change needs a per-launch session token, and requests from other sites are refused. Nothing is sent anywhere automatically, and there is no telemetry.
- The app makes only two outbound connections: `cs2scout assets fetch`, which you run yourself, and the AI brief, which runs after you confirm its preview.
- Demo files contain players' SteamIDs. They stay in the workspace. Exports and AI payloads contain nicknames and statistics only. A leak guard refuses to write an export, or send a payload, that contains a SteamID or a file path from this PC.
- The API key is read from the environment or `.env`. It is never logged, exported or shown.

## Backup

Everything lives in the workspace folder. Its path is shown on the Settings page.

- **Back up:** stop the app, then copy the whole folder.
- **Restore:** copy the folder back, or set `CS2SCOUT_HOME` to wherever the copy is.
- **Disk space:** deleting an analysis removes its results only. The parsed data and retained copies of its demos stay, so importing them again is instant; there is no cleanup command yet. Retained copies are the largest part, so turning them off in Settings saves the most space on new imports.

## Map images and sharing exports

The radar images come from [awpy](https://github.com/pnxenopoulos/awpy)'s awpy-data release (pinned to `2000943`), and are derived from Counter-Strike 2 game files. awpy's code is MIT-licensed. Neither its README nor its documentation states terms for the images (checked 2026-11-15).

Sharing an export with your own team is private, non-commercial use, but no licence explicitly grants it. Whether that is acceptable is your call. To share without the images, untick **include map images** in the Export menu: heatmaps and lineups keep their axes and numbers, on a blank background.

## Develop

Enable the pre-commit hook once per clone. It runs the G-fast gate:

```bash
git config core.hooksPath .githooks
```

| Gate | Command |
|---|---|
| G-fast | `uv run ruff format --check . && uv run ruff check . && uv run lint-imports && uv run pytest -n 8` |
| G-demos | `uv run pytest -m demos --require-demos` (needs `tests/local_fixtures/`, not in git) |
| G-browser | `uv run pytest -m browser` (one-time setup: `uv run playwright install chromium`) |

GitHub Actions runs G-fast and G-browser on every pull request. It also runs a hygiene check that refuses demos and real-looking SteamIDs. G-demos runs only on a PC that has the demos.

Real demos go in `tests/local_fixtures/demos/`. That folder is never committed, because demos contain real players' SteamIDs. No scoreboard data is needed: the accuracy tests check our stats against the server's own counters, which are recorded in each demo.

The AI tests run the real Anthropic SDK against a fake HTTP transport, so they need no key and make no network calls.
