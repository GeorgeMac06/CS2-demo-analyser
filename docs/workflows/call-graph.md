# Call graph

Which function calls which, from starting the app to each button the Analyst clicks. Every
box is a file and a function. Read top to bottom.

Use this page when you want to change something: find the button, then follow the arrows to
the function that does the work. The other pages explain *why* each step exists. This one only
says *where* it is.

## How to read the boxes

```mermaid
flowchart LR
  U(["The Analyst does something"]):::user
  W["web/ · a route or a page helper"]:::web
  J["jobs/ · background work"]:::job
  C["core/ · pure logic"]:::core
  S[("store/ · SQLite and files")]:::store
  P[["child process · the parser"]]:::child
  X{{"outside the PC"}}:::ext
  W -->|"calls"| C
  W -.->|"hands off to a job thread,<br/>returns at once"| J

  classDef user fill:#fde68a,stroke:#b45309,color:#000
  classDef web fill:#dbeafe,stroke:#1d4ed8,color:#000
  classDef job fill:#ede9fe,stroke:#6d28d9,color:#000
  classDef core fill:#dcfce7,stroke:#15803d,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
  classDef child fill:#fee2e2,stroke:#b91c1c,color:#000
  classDef ext fill:#fff,stroke:#000,color:#000,stroke-dasharray:4
```

- Paths are under `src/cs2scout/`.
- `ingest/`, `export/` and `ai/` are drawn blue like `web/`. They run in the server process,
  in the request thread, and are not pure.
- Small helpers (logging, error wrapping, `_page()` for most routes) are left out.

## 1. Start the app

```mermaid
flowchart TD
  U(["uv run cs2scout"]):::user --> M["__main__.py<br/>main()"]:::web
  M --> SE["settings.py<br/>Settings.from_env()"]:::web
  SE --> Q{"command?"}
  Q -->|"assets fetch or status"| AS["__main__.py<br/>_assets()"]:::web
  AS --> AF[("store/assets.py<br/>fetch() or available_maps()")]:::store
  Q -->|"none, or serve"| SV["__main__.py<br/>_serve()"]:::web
  SV --> CA["web/app.py<br/>create_app()"]:::web
  CA --> L1[("store/library.py<br/>Library()<br/>opens library.sqlite")]:::store
  CA --> L2[("store/library.py<br/>startup_cleanup()")]:::store
  CA --> JR["jobs/runner.py<br/>JobRunner()<br/>4 threads, 1 parse slot"]:::job
  CA --> RT["include_router(api.router)<br/>include_router(pages.router)"]:::web
  CA --> LG["web/security.py<br/>LocalGuard"]:::web
  SV --> WB["webbrowser.open()<br/>after 1.5 s"]:::web
  SV --> UV["uvicorn.run()<br/>127.0.0.1 only, waits for requests"]:::web
  UV --> EVERY["Every request:<br/>web/security.py LocalGuard.__call__() → _rejection()<br/>then one of the routes below"]:::web
  WB -.-> LIB(["Browser opens /"]):::user
  LIB --> LP["web/pages.py<br/>library_page()"]:::web
  LP --> LE["web/api.py<br/>list_entries()"]:::web
  LE --> LS[("store/library.py<br/>list_entries()")]:::store

  classDef user fill:#fde68a,stroke:#b45309,color:#000
  classDef web fill:#dbeafe,stroke:#1d4ed8,color:#000
  classDef job fill:#ede9fe,stroke:#6d28d9,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
```

`uv run cs2scout` finds `main()` through `[project.scripts]` in `pyproject.toml`.

## 2. Click "Import" on the New analysis page

The route returns at once with a progress card. The work happens in a job thread.

```mermaid
flowchart TD
  U(["Paste paths, click Import<br/>templates/new.html → POST /ui/imports"]):::user --> UI["web/pages.py<br/>ui_import()"]:::web
  U2(["Or drop files<br/>POST /ui/uploads"]):::user --> UP["web/pages.py<br/>ui_upload()<br/>saves the files to tmp/"]:::web
  UI --> SI["web/api.py<br/>start_import()"]:::web
  SI --> SU["web/api.py<br/>_submit()"]:::web
  UP --> SU
  SU --> RS["jobs/runner.py<br/>JobRunner.submit()"]:::job
  RS --> CJ[("store/library.py<br/>create_job()")]:::store
  UI --> JC["templates/_job.html<br/>progress card"]:::web
  RS -.->|"job thread"| RUN["jobs/runner.py<br/>JobRunner._run()"]:::job
  RUN --> RI["jobs/import_job.py<br/>run_import()"]:::job

  RI --> DI["ingest/files.py<br/>discover()"]:::web
  RI --> CF["jobs/import_job.py<br/>_check_files()"]:::job
  CF --> MA["ingest/files.py<br/>materialize() → check_magic() → sha256_file()"]:::web
  CF --> GD[("store/library.py<br/>get_demo()")]:::store
  CF --> RP["jobs/extract_worker.py<br/>run_probe()"]:::job
  RP --> PC[["_run_child() → _probe_main()<br/>parser/awpy_adapter.py<br/>AwpyAdapter.read_header()"]]:::child

  RI --> CM["jobs/import_job.py<br/>_choose_map()"]:::job

  RI --> EA["jobs/import_job.py<br/>_extract_all()"]:::job
  EA --> FE[("store/library.py<br/>find_extract()")]:::store
  EA --> RE["jobs/extract_worker.py<br/>run_extract()"]:::job
  RE --> EC[["_run_child() → _extract_main()<br/>AwpyAdapter.extract()<br/>core/schema.py schema_problems()<br/>_write() → sanity_issues()"]]:::child
  EA --> RT["ingest/files.py<br/>retain_source()"]:::web
  EA --> RD[("store/library.py<br/>record_demo() · record_extract()")]:::store

  RI --> LD["jobs/analysis.py<br/>load_demos() → demo_summary()"]:::job
  RI --> RPR["jobs/analysis.py<br/>roster_proposal()"]:::job
  RPR --> PR["core/team.py<br/>propose_roster()"]:::core
  RUN --> UJ[("store/library.py<br/>update_job(state=done, result)")]:::store

  classDef user fill:#fde68a,stroke:#b45309,color:#000
  classDef web fill:#dbeafe,stroke:#1d4ed8,color:#000
  classDef job fill:#ede9fe,stroke:#6d28d9,color:#000
  classDef core fill:#dcfce7,stroke:#15803d,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
  classDef child fill:#fee2e2,stroke:#b91c1c,color:#000
```

## 3. Progress, then "Create analysis"

```mermaid
flowchart TD
  P(["Progress card polls every second<br/>GET /ui/jobs/{id}"]):::user --> UJ["web/pages.py<br/>ui_job()"]:::web
  UJ --> GJ["web/api.py<br/>get_job()"]:::web
  GJ --> LJ[("store/library.py<br/>get_job()")]:::store
  UJ --> Q{"import job done?"}
  Q -->|"still running"| JC["templates/_job.html<br/>polls again"]:::web
  Q -->|"done"| RF["web/pages.py<br/>_roster_form()"]:::web
  RF --> RFT["templates/_roster_form.html<br/>or _import_report.html if nothing was accepted"]:::web

  U(["Tick roles, click Create<br/>POST /ui/entries"]):::user --> CE["web/pages.py<br/>ui_create_entry()"]:::web
  CE --> ACE["web/api.py<br/>create_entry()"]:::web
  ACE --> ST[("store/library.py<br/>create_team() · create_entry()<br/>set_roster() · add_entry_demos()")]:::store
  ACE --> RJ["web/api.py<br/>_recompute_job() → _submit()"]:::web
  RJ --> RS["jobs/runner.py<br/>JobRunner.submit()"]:::job
  RS -.->|"job thread"| RR["jobs/analysis.py<br/>run_recompute()<br/>see section 4"]:::job
  CE --> JC2["templates/_job.html<br/>then = /entries/{id}"]:::web
  JC2 -.->|"when the job is done"| RD(["HX-Redirect to the entry page<br/>see section 5"]):::user

  classDef user fill:#fde68a,stroke:#b45309,color:#000
  classDef web fill:#dbeafe,stroke:#1d4ed8,color:#000
  classDef job fill:#ede9fe,stroke:#6d28d9,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
```

Other buttons that end in the same `_recompute_job()`:

- "Update now": `pages.ui_recompute()` → `api.recompute()`.
- The Demos tab: `pages.ui_change_demo()` → `api.change_demo()`.
- The roster: `pages.ui_roster()` → `api.put_roster()`.
- "Add demos" runs `run_import()` and then `run_recompute()` in one job (`api.add_demos()`).

## 4. Inside a recompute

```mermaid
flowchart TD
  RR["jobs/analysis.py<br/>run_recompute()"]:::job
  RR --> GE[("store/library.py<br/>get_entry() · entry_demos() · roster()")]:::store
  RR --> RK["jobs/analysis.py<br/>roster_keys() → player_key()"]:::job
  RR --> LD["jobs/analysis.py<br/>load_demos()"]:::job
  LD --> FE[("store/library.py<br/>find_extract()")]:::store
  LD -->|"extract missing"| RX["jobs/analysis.py<br/>_reextract() → run_extract()"]:::job
  LD --> RT[("store/extracts.py<br/>read_tables()")]:::store
  LD --> DL["core/team.py<br/>demo_lineups()"]:::core
  RR --> AL["core/team.py<br/>assign_lineups()"]:::core
  RR --> BV[("store/library.py<br/>begin_version()")]:::store
  RR --> AN["jobs/analysis.py<br/>_analyse()"]:::job

  AN --> LOOP["for each demo"]:::job
  LOOP --> R1["core/rounds.py<br/>team_rounds() · match_result()"]:::core
  LOOP --> R2["core/features.py<br/>assign_rounds() · player_rounds()"]:::core
  LOOP --> R3["core/economy.py<br/>eco_rounds() · round_columns()"]:::core
  LOOP --> R4["core/patterns_t.py t_rounds()<br/>core/patterns_ct.py ct_rounds()<br/>core/patterns_util.py demo_util()"]:::core
  LOOP --> R5["core/round_story.py<br/>round_stories()"]:::core
  R4 -->|"t_list, ct_list"| R5
  LOOP --> R6["core/grids.py<br/>live_positions()"]:::core

  AN --> MI["core/patterns_t.py mine_t()<br/>core/patterns_ct.py mine_ct()<br/>core/patterns_util.py mine_util()<br/>core/economy.py mine_eco()"]:::core
  AN --> AF["core/findings.py<br/>all_findings() · round_index_json()"]:::core
  AN --> GR["core/grids.py<br/>project() · build_grids()"]:::core
  AN --> WR[("writes to v{n}/<br/>patterns.json · stories.json · rounds.parquet<br/>player_rounds.parquet · grids.parquet")]:::store

  RR --> WF[("writes findings.json · players.json · config.json")]:::store
  RR --> CO["core/labels.py<br/>carry_over()"]:::core
  CO --> RL[("store/library.py<br/>rekey_label()")]:::store
  RR -->|"success"| CV[("store/library.py<br/>commit_version()")]:::store
  RR -->|"error or cancel"| AV[("store/library.py<br/>abandon_version()")]:::store

  classDef job fill:#ede9fe,stroke:#6d28d9,color:#000
  classDef core fill:#dcfce7,stroke:#15803d,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
```

## 5. Open an analysis, switch tab, change a filter

```mermaid
flowchart TD
  U1(["Open an analysis<br/>GET /entries/{id}"]):::user --> EP["web/pages.py<br/>entry_page()"]:::web
  U2(["Click a tab or change a filter<br/>GET /ui/entries/{id}/tab/{tab}"]):::user --> UT["web/pages.py<br/>ui_tab() → _filter()"]:::web
  EP --> GE["web/api.py<br/>get_entry()"]:::web
  EP --> TC
  UT --> TC["web/pages.py<br/>_tab_context()"]:::web
  TC --> SN["web/pages.py<br/>_snapshot()"]:::web
  SN --> VD[("store/library.py<br/>current_version_dir()")]:::store
  SN --> FS["web/findings_view.py<br/>filtered_snapshot() → _filtered()<br/>cached per version and filter"]:::web
  FS --> RF["core/findings.py<br/>RoundFilter.apply() · all_findings()"]:::core
  SN --> LB["web/api.py<br/>labelled()"]:::web
  TC --> Q{"which tab?"}
  Q -->|"overview"| OV["web/figures.py winrate_figure()<br/>web/pages.py _heat_choices()"]:::web
  Q -->|"t, ct, utility"| PC["web/pages.py<br/>_pattern_context()"]:::web
  Q -->|"economy"| EC["web/pages.py<br/>_pattern_context() → _economy_context()"]:::web
  Q -->|"players"| PP["web/pages.py<br/>_player_patterns()"]:::web
  Q -->|"brief"| BR[("store/library.py<br/>latest_brief()")]:::store
  TC --> PG["templates/_tab_{tab}.html"]:::web

  U3(["Click a k/n number<br/>GET /ui/entries/{id}/rounds"]):::user --> UR["web/pages.py<br/>ui_rounds()"]:::web
  UR --> GR["web/api.py<br/>get_rounds() → filtered_snapshot() · stories()"]:::web
  U4(["Rename a pattern ✎<br/>POST /ui/entries/{id}/labels/{finding}"]):::user --> UL["web/pages.py<br/>ui_label()"]:::web
  UL --> PL["web/api.py<br/>put_label()"]:::web
  UL -.->|"HX-Trigger: labels-changed<br/>the open tab reloads"| U2

  classDef user fill:#fde68a,stroke:#b45309,color:#000
  classDef web fill:#dbeafe,stroke:#1d4ed8,color:#000
  classDef core fill:#dcfce7,stroke:#15803d,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
```

## 6. Click "Export"

```mermaid
flowchart TD
  U(["Pick sections, click Export<br/>GET /ui/entries/{id}/export"]):::user --> UE["web/pages.py<br/>ui_export() → _filter()"]:::web
  UE --> RE["web/export_view.py<br/>render()"]:::web
  RE --> SN["web/pages.py<br/>_snapshot()<br/>same as section 5"]:::web
  RE --> TC["web/pages.py<br/>_tab_context() for each section<br/>rendered with static=True"]:::web
  RE --> LB[("store/library.py<br/>latest_brief()<br/>left out if stale")]:::store
  RE --> DU["export/inline.py<br/>data_uri()<br/>radar images"]:::web
  RE --> EX["templates/export.html<br/>inline CSS, Plotly.js, export.js"]:::web
  RE --> LK["export/inline.py<br/>leaks()"]:::web
  LK -->|"SteamID or path found"| ER["ExportLeak → templates/_error.html"]:::web
  LK -->|"clean"| DL(["Browser downloads one .html file"]):::user

  classDef user fill:#fde68a,stroke:#b45309,color:#000
  classDef web fill:#dbeafe,stroke:#1d4ed8,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
```

## 7. AI brief: "Preview", then "Send"

```mermaid
flowchart TD
  U1(["Click Preview<br/>POST /ui/entries/{id}/ai-brief/preview"]):::user --> UP["web/pages.py<br/>ui_brief_preview()"]:::web
  UP --> PB["web/api.py<br/>preview_brief()"]:::web
  PB --> AK["web/api.py<br/>_ai_key()"]:::web
  PB --> BP["web/api.py<br/>_brief_payload()"]:::web
  BP --> FS["web/findings_view.py filtered_snapshot()<br/>web/api.py labelled() · stories()"]:::web
  BP --> PBU["ai/payload.py<br/>build() → check()"]:::web
  PB --> DG["ai/payload.py<br/>digest() · estimate_tokens()"]:::web
  PB --> MK["ai/confirm.py<br/>make()"]:::web
  UP --> PV["templates/_ai_preview.html"]:::web

  U2(["Click Send<br/>POST /ui/entries/{id}/ai-brief"]):::user --> US["web/pages.py<br/>ui_brief_send()"]:::web
  US --> CB["web/api.py<br/>create_brief()"]:::web
  CB --> BP2["web/api.py _brief_payload()<br/>ai/payload.py digest()<br/>built again"]:::web
  CB --> VA["ai/confirm.py<br/>valid()"]:::web
  CB --> WB["ai/client.py<br/>write_brief()"]:::web
  WB --> ANT{{"Anthropic API<br/>messages.stream"}}:::ext
  CB --> GD["ai/grounding.py<br/>ground()"]:::web
  CB --> SB[("store/library.py<br/>save_brief()")]:::store
  US --> RD(["HX-Redirect to the AI brief tab"]):::user

  classDef user fill:#fde68a,stroke:#b45309,color:#000
  classDef web fill:#dbeafe,stroke:#1d4ed8,color:#000
  classDef store fill:#f3f4f6,stroke:#4b5563,color:#000
  classDef ext fill:#fff,stroke:#000,color:#000,stroke-dasharray:4
```
