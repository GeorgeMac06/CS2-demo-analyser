# Import

How demo files become cached extracts. Code: `jobs/import_job.py`, `ingest/files.py`,
`jobs/extract_worker.py`, `parser/awpy_adapter.py`. Design: target design §6.1.

## Who talks to whom

The parser always runs in a spawned child process. A crash or hang in the parser can never
take the server down. One parse runs at a time across the app (`parse_slot`).

```mermaid
sequenceDiagram
  autonumber
  actor Analyst
  participant UI as Browser (htmx)
  participant API as web (FastAPI)
  participant Run as JobRunner thread
  participant Ing as ingest.files
  participant Child as Parse child (awpy)
  participant Lib as store.Library

  Analyst->>UI: pick files or a folder
  UI->>API: POST /ui/imports {paths}
  API->>Run: submit("import", run_import)
  API-->>UI: job page
  loop every second
    UI->>API: GET /ui/jobs/{id}
    API->>Lib: get_job
    API-->>UI: progress (checking / parsing)
  end
  Note over Run: Phase 1: check every file
  Run->>Ing: discover, materialize, check_magic, sha256_file
  Run->>Lib: get_demo(sha) — known demo?
  Run->>Child: run_probe (header only, 120 s)
  Child-->>Run: map name or error
  Note over Run: Phase 2: choose the map
  Note over Run: Phase 3: extract accepted demos, one at a time
  Run->>Lib: find_extract(sha, parser, version, schema)
  alt not cached
    Run->>Child: run_extract into dest._partial (15 min)
    Child-->>Run: manifest.json or error.json and exit code
    Run->>Ing: retain_source → demos/{sha}/source.dem.gz
    Run->>Lib: record_demo, record_extract
  end
  Run->>Lib: update_job(state=done, result)
  UI->>API: GET /ui/jobs/{id}
  API-->>UI: roster form (J1) or import report
```

## What happens to each file

Each file ends with one status: `accepted`, `rejected` (with a code) or `duplicate`.
A rejected file never stops the others.

```mermaid
flowchart TD
  A["Path from the Analyst"] --> B{"discover:<br/>.dem .dem.gz .dem.bz2 .zip?"}
  B -->|No| S["Skipped, listed in the report"]
  B -->|Yes| C["materialize: decompress into tmp/<br/>never use the name inside the archive"]
  C -->|too big, ratio over 50:1,<br/>zip without exactly one .dem| R1["ARCHIVE_REJECTED"]
  C --> D{"check_magic: PBDEMS2?"}
  D -->|CS:GO or other| R2["NOT_CS2"]
  D -->|Yes| E["sha256 of the .dem bytes"]
  E --> F{"Same hash already in this<br/>entry or this batch?"}
  F -->|Yes| DUP1["DUPLICATE"]
  F -->|No| G{"Demo already in the library?"}
  G -->|Yes| H["Reuse its map. No probe."]
  G -->|No| P["Probe header in a child"]
  P -->|parse error| R3["DEMO_UNREADABLE"]
  P -->|crash| R4["PARSER_CRASH"]
  P -->|over 120 s| R5["PARSER_TIMEOUT"]
  P -->|ok| H2["Map name from the header"]
  H --> M
  H2 --> M{"Map = entry map,<br/>or the most common map in J1?"}
  M -->|No| R6["MAP_MISMATCH"]
  M -->|Yes| X{"Extract cached for this<br/>parser version and schema?"}
  X -->|Yes| K
  X -->|No| Y["Extract in a child"]
  Y -->|exception in the parser,<br/>or a sanity check rejects it| R3
  Y -->|adapter broke the schema,<br/>or non-zero exit| R4
  Y -->|over 15 min| R5
  Y -->|ok| Z["Rename _partial to final<br/>retain gzip source<br/>record demo and extract"]
  Z --> K{"match_key already<br/>in this entry?"}
  K -->|Yes| DUP2["DUPLICATE: same match, other bytes"]
  K -->|No| OK["Accepted"]
  OK --> INC{"Complete match?"}
  INC -->|No| W["Accepted with INCOMPLETE_MATCH warning"]
```

## Cancel and crash

- **Cancel:** the job sets its cancel flag. The runner kills the parse child at once and deletes
  its `_partial` folder. Extracts that already finished stay cached. No entry is created.
- **Server crash:** on the next start, `Library.startup_cleanup` deletes `_partial` folders and
  `tmp/cs2scout-*` files and marks running jobs as failed. See [Runtime](runtime.md).
- **Temp files:** every decompressed `.dem` in `tmp/` is deleted when the job ends, success or
  not.

## Parser upgrades

An extract is keyed by `(sha256, parser, parser_version, schema_version)`. After a parser or
schema upgrade, the old extracts no longer match. Two things rebuild them:

- Importing the demo file again parses it with the current parser.
- A recompute rebuilds a missing extract from the retained source. Without a source it uses
  the older extract and reports `STALE_EXTRACT`. See [Analysis](analysis.md).
