# Data model

Where the app keeps its data, and which data may leave the PC. Code: `store/library.py`
(SQLite schema), `store/extracts.py`, `store/prefs.py`. Design: target design §5.1.

## SQLite tables

`library.sqlite` holds metadata only. The heavy data is in Parquet and JSON files.

```mermaid
erDiagram
  team ||--o{ team_player : "has"
  team ||--o{ entry : "is scouted in"
  entry ||--o{ entry_demo : "uses"
  demo ||--o{ entry_demo : "is used by"
  demo ||--o{ extract : "is parsed into"
  entry ||--o{ entry_version : "is computed as"
  entry ||--o{ label : "has"
  entry ||--o{ ai_brief : "has"
  entry |o--o{ job : "runs"

  team {
    int team_id PK
    text display_name
  }
  team_player {
    int team_id FK
    int steamid
    text role "core, standin or excluded"
    text last_nick
  }
  entry {
    int entry_id PK
    int team_id FK
    text map "unique with team_id"
    text name
    int current_version
  }
  demo {
    text sha256 PK
    text match_key
    text map
    text played_at
    int rounds
    text original_path
    int source_retained
  }
  extract {
    text sha256 FK
    text parser
    text parser_version
    int schema_version
    text path
    text manifest
  }
  entry_demo {
    int entry_id FK
    text sha256 FK
    int included
    text lineup_override "A or B"
  }
  entry_version {
    int entry_id FK
    int n
    text status "building or ready"
    text config_hash
    text input_hash
  }
  label {
    int entry_id FK
    text pattern_kind
    text stable_key
    text user_label
  }
  ai_brief {
    int entry_id FK
    int entry_version
    text model
    text payload_hash
    text brief_json
  }
  job {
    text job_id PK
    text kind
    int entry_id
    text state
    text progress
    text result
  }
```

- A team is shared across maps. Its roster is shared too.
- A demo is shared across entries. It is parsed once per parser version.
- `label` uses the pattern's stable key, so a rename survives a recompute.

## Workspace folder

The root is `%LOCALAPPDATA%\CS2DemoScout\`, or `CS2SCOUT_HOME`.

```text
library.sqlite                         metadata (above)
settings.json                          thresholds, retain_sources, workspace cap, port
demos/{sha}/source.dem.gz              retained source, used to re-extract after upgrades
extracts/{sha}/{parser}@{ver}+s{schema}/
    *.parquet, manifest.json           one immutable extract per demo and parser version
entries/{id}/v{n}/
    findings.json                      the Findings Snapshot
    patterns.json                      mined patterns with stable keys
    stories.json                       one story per round (local only)
    rounds.parquet, player_rounds.parquet
    grids.parquet                      heatmap values
    players.json                       player key to SteamID (local only)
    config.json                        thresholds this version used
assets/awpy-data/{release}/            radar images and map data, from `cs2scout assets fetch`
tmp/                                   decompressed demos while importing, cleared on start
```

## What may leave the PC

```mermaid
flowchart LR
  subgraph PC["This PC only"]
    SID["SteamIDs<br/>team_player, players.json"]
    PATH["File paths<br/>demo.original_path"]
    DEM["Demos and extracts"]
    KEY["Anthropic API key<br/>env or .env"]
  end
  subgraph OUT["Can leave the PC"]
    EXP["HTML export<br/>player key + nickname"]
    PAY["AI payload<br/>aggregates + round stories"]
  end
  SNAP["Filtered snapshot"] --> EXP
  SNAP --> PAY
  EXP -. "leaks() blocks SteamIDs and paths" .-> G1{{"EXPORT_BLOCKED"}}
  PAY -. "payload.check() blocks the same" .-> G1
  PAY -->|"only after preview and confirm"| ANT["Anthropic API"]
```

A player's key (`p` plus 6 hex characters) is a hash of the SteamID. It is stable across
roster edits, so labels and per-player findings never move to another player.
