# Development workflow

How a change goes from an idea to `main`, and from `main` to a release. The rules are in
[CLAUDE.md](../../CLAUDE.md). The gates are in the [test strategy](../delivery/test-strategy.md).
Labels and releases are in [versioning](../delivery/versioning.md).

## Who does what

Only the owner merges. Claude may open issues but never assigns them.

```mermaid
flowchart TD
  subgraph Owner["Owner"]
    O1["Opens an issue<br/>assigns gmac-claude or mentions @claude"]
    O2["Reviews the PR in GitHub"]
    O3["Merges into main"]
  end
  subgraph Local["Claude Code on the owner's PC<br/>issues assigned to gmac-claude"]
    L1["Own worktree and branch<br/>from origin/main"]
    L2["Runs G-fast, G-browser, G-demos<br/>real demos are here"]
    L3["Pushes the branch and opens the PR<br/>without asking"]
  end
  subgraph App["Claude GitHub App<br/>@claude in an issue or PR"]
    A1["Runs in GitHub Actions"]
    A2["Opens a PR that says<br/>which gates did not run"]
  end
  subgraph Actions["GitHub Actions on every PR"]
    C1["CI: G-fast, G-browser, Hygiene"]
    C2["Version label check"]
    C3["Claude Code Review"]
  end
  UN["Unassigned issue<br/>a bug or follow-up Claude found"]

  O1 --> L1 --> L2 --> L3
  O1 --> A1 --> A2
  L3 --> Actions
  A2 --> Actions
  Actions --> O2 --> O3
  L2 -.-> UN
  UN -.->|owner decides who takes it| O1
```

Claude does not comment on issues or PRs unless asked.

## One change, step by step

```mermaid
flowchart TD
  A["git worktree add, new branch from origin/main<br/>never work in main or in another session's checkout"] --> B["Own CS2SCOUT_HOME and free CS2SCOUT_PORT<br/>copy tests/local_fixtures/ in if G-demos is needed"]
  B --> C["Write a test first<br/>E2E through tests/support/api.py<br/>on a synthetic demo"]
  C --> D["Change the code"]
  D --> E{"Did findings or<br/>round stories change?"}
  E -->|Yes| F["Bump SCHEMA_VERSION<br/>in core/findings.py"]
  E -->|No| G
  F --> G{"Did the design or<br/>a flow change?"}
  G -->|Yes| H["Dated Changed note in target-design.md<br/>update the diagram in docs/workflows/"]
  G -->|No| K
  H --> K["git commit<br/>pre-commit hook runs G-fast"]
  K -->|fails| D
  K -->|passes| L["G-browser if the UI changed<br/>G-demos if parsing or stats changed"]
  L --> M{"git log origin/main..HEAD<br/>only my commits?"}
  M -->|No| STOP["Stop and tell the owner"]
  M -->|Yes| N["Push and open the PR"]
  N --> P["One label: semver:minor, patch or none<br/>plus breaking on 0.x if needed"]
  P --> Q["CI and review run"]
  Q --> R{"main moved and both<br/>bumped SCHEMA_VERSION?"}
  R -->|Yes| S["Merge main in, take the next free number<br/>never rebase"]
  S --> Q
  R -->|No| T["Owner merges"]
```

Every PR follows the template: what changed, the issue it closes, a **Try it** section that
walks the owner through the change in the app, which gates ran and what was not tested.

## The gates

| Gate | What it runs | On the owner's PC | In GitHub Actions |
|---|---|---|---|
| G-fast | `ruff format --check`, `ruff check`, `lint-imports`, `pytest` | Pre-commit hook | Every PR and push to `main`, on Windows |
| G-browser | `pytest -m browser` | By hand, after `playwright install chromium` | Every PR and push to `main`, on Ubuntu |
| G-demos | `pytest -m demos --require-demos` | By hand, with real demos | Never. Demos contain SteamIDs. |
| Hygiene | `.github/scripts/hygiene.sh` | — | Every PR. Fails on demos, archives, local fixtures or a real-looking SteamID. |
| Version label | `pr-labels.yml` | — | Every PR. Fails until there is exactly one `semver:*` label. |

## Release

```mermaid
flowchart LR
  A["PRs merge into main"] --> B["release-notes.yml<br/>updates the draft release<br/>next version from the labels"]
  B --> C["Release X.Y.Z PR<br/>uv version X.Y.Z<br/>labels: release, semver:none"]
  C --> D["Owner merges"]
  D --> E["Owner publishes the draft<br/>tag vX.Y.Z on main"]
  E --> F["release.yml<br/>tag = pyproject version?<br/>G-fast and G-browser on the tag"]
  F --> G["Wheel and sdist<br/>attached to the release"]
```

## Before you commit

- No real team names, nicknames or SteamIDs anywhere. Tests use `a1`–`a5` and `opp`.
- No demos and nothing from `tests/local_fixtures/`.
- No API key in code, logs or output. Tests use the fake Claude transport.
- `core` imports nothing else from `cs2scout`. Only `parser` imports awpy. `lint-imports`
  checks both.
- Keep edits to shared files small (`core/findings.py`, `docs/`). Branches collide there.
- On Windows, a running `cs2scout.exe` locks the virtual environment. Use `uv run --no-sync`
  and commit with `UV_NO_SYNC=1`.
