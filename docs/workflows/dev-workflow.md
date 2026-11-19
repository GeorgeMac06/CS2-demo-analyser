# Development workflow

How a change goes from an idea to `main`. The rules are in [CLAUDE.md](../../CLAUDE.md). The
gates and test IDs are in the [test strategy](../delivery/test-strategy.md).

## Who does what

Three people or agents can work on the code. Only the owner pushes to GitHub and merges.

```mermaid
flowchart TD
  subgraph Owner["Owner"]
    O1["Opens an issue"]
    O2["Pushes the local branch"]
    O3["Opens the PR"]
    O4["Reviews and merges into main"]
  end
  subgraph Local["Claude Code on the owner's PC<br/>issues assigned to gmac-claude"]
    L1["Reads the issue"]
    L2["Works on a local feature branch"]
    L3["Runs G-fast, G-demos and G-browser<br/>real demos are here"]
    L4["Commits locally<br/>never pushes, comments or opens PRs"]
  end
  subgraph Action["Claude GitHub App<br/>@claude in an issue or PR"]
    A1["Runs in GitHub Actions"]
    A2["Cannot run the gates"]
    A3["Opens a PR that says what was not tested"]
  end
  subgraph Review["Claude Code Review workflow"]
    R1["Runs on every PR update"]
  end

  O1 -->|assigned to gmac-claude| L1
  O1 -->|"mentions @claude"| A1
  L1 --> L2 --> L3 --> L4 --> O2 --> O3
  A1 --> A2 --> A3
  O3 --> R1
  A3 --> R1
  R1 --> O4
```

## One change, step by step

```mermaid
flowchart TD
  A["Start from main"] --> B["New feature branch<br/>never commit to main"]
  B --> C["Write a test first<br/>E2E through tests/support/api.py<br/>on a synthetic demo"]
  C --> D["Change the code"]
  D --> E{"Did findings or<br/>round stories change?"}
  E -->|Yes| F["Bump SCHEMA_VERSION<br/>in core/findings.py"]
  E -->|No| G
  F --> G{"Did the design change?"}
  G -->|Yes| H["Add a dated Changed note<br/>to target-design.md"]
  G -->|No| I
  H --> I{"Did a flow in docs/workflows change?"}
  I -->|Yes| J["Update the diagram"]
  I -->|No| K
  J --> K["git commit<br/>pre-commit hook runs G-fast"]
  K -->|fails| D
  K -->|passes| L{"Touches parsing, stats<br/>or the UI?"}
  L -->|parsing or stats| M["G-demos<br/>uv run pytest -m demos --require-demos"]
  L -->|UI| N["G-browser<br/>uv run pytest -m browser"]
  L -->|neither| P
  M --> P["Owner pushes and opens a PR"]
  N --> P
  P --> Q["Owner merges"]
```

## The gates

| Gate | What it runs | Where it can run |
|---|---|---|
| G-fast | `ruff format --check`, `ruff check`, `lint-imports`, `pytest -n 8` | Every clone. The pre-commit hook runs it. |
| G-demos | `pytest -m demos --require-demos` | Only the owner's PC. It needs real demos in `tests/local_fixtures/demos/`. |
| G-browser | `pytest -m browser` | Any clone after `uv run playwright install chromium`. |

## Before you commit

- No real team names, nicknames or SteamIDs anywhere. Tests use `a1`–`a5` and `opp`.
- No demos and nothing from `tests/local_fixtures/`.
- No API key in code, logs or output. Tests use the fake Claude transport.
- `core` imports nothing else from `cs2scout`. Only `parser` imports awpy. `lint-imports`
  checks both.
- On Windows, a running `cs2scout.exe` locks the virtual environment. Use `uv run --no-sync`
  and commit with `UV_NO_SYNC=1`.
