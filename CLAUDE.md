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

- **Issues assigned to `gmac-claude`** are for Claude Code on the owner's PC. That copy has the real demos and runs every gate. It reads GitHub but never pushes, comments or opens PRs: it commits on a local branch and the owner pushes.
- **The Claude GitHub App** (`@claude` in an issue or PR) runs in GitHub Actions. Its current workflow cannot run the gates, so its PRs must say what was not tested.

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

CI (`.github/workflows/ci.yml`) runs G-fast and G-browser on every PR, including the GitHub App's, plus a hygiene check. The hygiene check fails if a PR adds demos, archives, `tests/local_fixtures/` files or a real-looking SteamID. A made-up SteamID in a test can stay if its line has the comment `hygiene: allow`. G-demos never runs in CI, so every PR says whether it ran.

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
- `docs/delivery/versioning.md`: semantic versioning, the PR labels and how a release works.
- Write UI text, docs, commit messages and PR descriptions in plain, short sentences.

## Versions

- Every PR into `main` gets exactly one label: `semver:minor`, `semver:patch` or `semver:none`. `docs/delivery/versioning.md` says which. While on 0.x, a breaking change also gets `breaking`.
- A `SCHEMA_VERSION` bump means at least `semver:minor`.
- Only a PR with the `release` label changes `version` in `pyproject.toml`. Use `uv version X.Y.Z`.
- To prepare a release: take X.Y.Z from the draft release on GitHub, then open a "Release X.Y.Z" PR with the `release` and `semver:none` labels. The owner merges it and publishes the draft. `release.yml` then checks the tag, runs the gates and attaches the wheel.
