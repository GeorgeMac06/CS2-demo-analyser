# Analysis

How cached extracts become a version with findings, round stories and heatmaps. Code:
`jobs/analysis.py` (`run_recompute`, `_analyse`), `core/*`, `web/findings_view.py`.
Design: target design §5.3 and §6.2–6.3.

## What starts a recompute

Each of these submits a recompute job for the entry. Only one job per entry runs at a time.

- J1: the Analyst confirms the roster (`POST /api/entries`).
- J2: new demos are accepted (`POST /api/entries/{id}/demos`; import and recompute in one job).
- A demo is included, excluded, given a lineup or a date (`PATCH .../demos/{sha}`).
- The roster changes (`PUT .../roster`).
- "Update now" (`POST .../recompute`), shown when the version is older than
  `core.findings.SCHEMA_VERSION` or was built with other thresholds.

## Data flow

Recompute never parses a demo it already has an extract for. Patterns are mined once, on all
included demos. Filters later only recount them.

```mermaid
flowchart TD
  subgraph IN["Inputs"]
    EX[("Extracts<br/>Parquet per demo")]
    ED["entry_demo<br/>included, lineup_override"]
    RO["team_player<br/>core, standin, excluded"]
    CFG["AnalysisConfig<br/>thresholds from settings.json"]
    RAD["Radar assets<br/>optional"]
  end

  EX --> LD["load_demos<br/>chronological order<br/>re-extract from source if missing"]
  LD --> S3["S3 Team resolve<br/>core.team: demo_lineups, assign_lineups"]
  ED --> S3
  RO --> S3
  S3 -->|no lineup matches| TNF["Demo marked TEAM_NOT_FOUND<br/>left out"]
  S3 --> S4["S4 Per-demo features<br/>core.rounds: team_rounds, buy class<br/>core.features: player_rounds, plants"]
  CFG --> S4
  S4 --> OBS["Observations<br/>t_rounds, ct_rounds, demo_util"]
  S4 --> ST["round_stories<br/>places at checkpoints, utility, opening duel, plant"]
  S4 --> POS["live_positions"]
  OBS --> S5["S5 Patterns<br/>mine_t, mine_ct, mine_util"]
  CFG --> S5
  S5 --> S6["S6 Findings<br/>all_findings: k of n, round_refs, flags"]
  POS --> GR["project + build_grids<br/>64×64 heatmaps"]
  RAD --> GR

  subgraph OUT["entries/{id}/v{n}/"]
    F1["findings.json"]
    F2["patterns.json"]
    F3["stories.json"]
    F4["rounds.parquet<br/>player_rounds.parquet"]
    F5["grids.parquet"]
    F6["players.json<br/>config.json"]
  end
  S6 --> F1
  S5 --> F2
  ST --> F3
  S4 --> F4
  GR --> F5
  RO --> F6
  CFG --> F6
```

## Atomic version swap

A version is written to a new folder while its row says `building`. Only one transaction makes
it current. A failed or cancelled job leaves the current version as it was.

```mermaid
sequenceDiagram
  autonumber
  participant Job as run_recompute
  participant Lib as store.Library
  participant FS as entries/{id}/

  Job->>Lib: begin_version(config_hash, input_hash)
  Lib->>FS: mkdir v{n+1}
  Lib-->>Job: n+1, status building
  Job->>FS: write findings, patterns, stories, grids, ...
  Job->>Lib: rekey_label for patterns that moved (carry_over)
  alt success
    Job->>Lib: commit_version(n+1)
    Note over Lib: one transaction: status ready,<br/>entry.current_version = n+1
    Lib->>FS: delete versions older than n
  else error or cancel
    Job->>Lib: abandon_version(n+1)
    Lib->>FS: delete v{n+1}
    Note over Lib: current version unchanged
  end
```

## Filtered views (S7)

Pages, the export and the AI brief all read a filtered view of the same snapshot.

```mermaid
flowchart LR
  A["findings.json<br/>current version"] --> B["RoundFilter<br/>side, buy, opp buy, demos, dates, overtime"]
  B --> C["Restrict rounds.parquet"]
  C --> D["all_findings again on the stored patterns<br/>k of n recounted from round_refs"]
  D --> E["Same thresholds as the version<br/>config.json, not today's settings"]
  E --> F["Overlay user labels"]
  F --> G1["Entry page tabs"]
  F --> G2["HTML export"]
  F --> G3["AI brief payload"]
```

Results are cached in memory per version and filter (`findings_view.filtered_snapshot`).
Because patterns are mined on the full set, a pattern keeps its id and its label under any
filter. The trade-off: a pattern that exists only inside a filtered subset is not found.
