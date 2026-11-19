# CS2 Demo Scout: notes for Claude

A local web app that scouts one CS2 team on one map across several demos. It finds the team's patterns, each with its evidence (k of n rounds), writes a short story for every round and can write an optional AI brief. The owner uses it to prepare league matches with their team.

Stack: Python 3.13, uv, FastAPI with Jinja and htmx (no SPA), Plotly, Polars, SQLite and Parquet, awpy 3.3.0 behind an adapter, the anthropic SDK.

## Rules

This repo is public.

- Never put real team names, player nicknames or SteamIDs into anything committed or posted. That covers code, docstrings, tests, docs, commit messages, issues and PRs. Tests use made-up names (`a1`–`a5`, `opp`).
- Never commit demos or anything in `tests/local_fixtures/`. Demos contain real SteamIDs.
- Never log, print or export the Anthropic API key. Tests never call the real API; they use a fake transport.
- Never commit to, push to or merge into `main`. Work on a feature branch. Changes reach `main` only through a PR the owner merges. Never force-push or rewrite history.

## Who works on what

- **Issues assigned to `gmac-claude`** are for Claude Code on the owner's PC. That copy has the real demos and runs every gate. It commits on a feature branch. When the branch is ready and the gates pass, it pushes the branch and opens a PR without asking first. It does not merge, and it does not comment on issues or PRs unless asked.
- **The Claude GitHub App** (`@claude` in an issue or PR) runs in GitHub Actions. Its current workflow cannot run the gates, so its PRs must say what was not tested.

## Working with the owner

- **Reviews happen in GitHub.** Don't wait for a go-ahead to push and open a PR. If the work is ready, open it. The owner reviews and merges.
- **When you finish something in chat,** say it informally: what you added, what it looks like, and how to use it. For example: "I added an Economy tab. It shows full, force or save for each round. Open any analysis and click Economy." This is welcome, not required.
- **Every PR description has a "Try it" section.** Walk the owner through the change in the app: which tab or page to open, what to click, what to look for, and which new setting to try and what it changes. Skip setup steps like checking out the branch or running `uv run cs2scout`; the owner knows those. If there is nothing to see in the app (a refactor, a test), say so in one line. Never use real team or player names in it.
- **Also in every PR:** what changed, the issue it closes, and which gates ran. Say plainly what was not tested.
- **Issues:** you may open an issue for a bug, gap or follow-up you find. Never assign it to anyone, yourself included. The owner reads the unassigned issues and decides who takes each one.

## Commands

```bash
uv run cs2scout                      # serves on 127.0.0.1:8765; CS2SCOUT_HOME and CS2SCOUT_PORT override
git config core.hooksPath .githooks  # once per clone: the pre-commit hook runs G-fast
```

| Gate | Command | Notes |
|---|---|---|
| G-fast | `uv run ruff format --check . && uv run ruff check . && uv run lint-imports && uv run pytest -n 8` | About 2 minutes. Must pass before every commit. |
| G-demos | `uv run pytest -m demos --require-demos` | Needs real demos in `tests/local_fixtures/demos/`. |
| G-browser | `uv run pytest -m browser` | Needs `uv run playwright install chromium` once. |

On Windows, a running `cs2scout.exe` locks the virtual environment, so `uv sync` fails. Use `uv run --no-sync`, commit with `UV_NO_SYNC=1`, and add packages with `uv add --no-sync` followed by `uv pip install`.

## Code

- `src/cs2scout/core` is pure logic. It imports no other `cs2scout` package, no framework and no storage. Only `cs2scout.parser` imports awpy. `lint-imports` enforces both rules (contracts in `pyproject.toml`).
- Other packages: `ingest` (files and archives), `store` (library, extracts), `jobs` (import and analysis), `web` (routes, templates), `export`, `ai`. The brief's instructions are in `src/cs2scout/ai/instructions.md`.
- Times shown to users are on the in-game round timer, where 1:55 is the end of freeze time. Use `core.patterns.clock`.
- Every finding keeps the round refs behind its k/n, so it can be recounted (test T-05).
- When findings or round stories change, bump `SCHEMA_VERSION` in `core/findings.py`. Older analyses then offer "Update now".
- Ruff, line length 100.

## Tests

- Prefer end-to-end tests through the API (`tests/support/api.py`) on synthetic demos (`tests/support/synth.py`, `scenarios.py`) over unit tests of internals.
- Fake parsers and a fake Claude live in `tests/support/`.
- Test IDs (T-xx) and gates are in `docs/delivery/test-strategy.md`.

## Docs

- `docs/product/requirements.md`: requirements (FR-xx) and acceptance tests (AT-xx).
- `docs/architecture/target-design.md`: the design. When the design changes, add a dated "Changed" note there.
- `docs/delivery/delivery-plan.md`: work units and milestones.
- Write UI text, docs, commit messages and PR descriptions in plain, short sentences.
