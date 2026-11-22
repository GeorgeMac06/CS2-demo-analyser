# User journeys

What the Analyst does, page by page. The journeys J1–J5 are defined in the
[requirements](../product/requirements.md#3-core-journeys).

## Overview

```mermaid
flowchart LR
  LIB["Library page /"] -->|New analysis| J1["J1 Create an analysis"]
  LIB -->|open an entry| ENTRY["Entry page /entries/{id}"]
  J1 --> ENTRY
  ENTRY -->|Add demos| J2["J2 Add demos"]
  J2 --> ENTRY
  ENTRY -->|tabs and filters| J3["J3 Explore findings"]
  ENTRY -->|Export| J4["J4 Export HTML"]
  ENTRY -->|AI brief tab| J5["J5 AI brief"]
  LIB -->|Settings| SET["Settings /settings"]
  SET -.->|thresholds changed| UPD["Entry offers Update now"]
  SET -->|Free up space| FREE["Lists demos no analysis uses, with sizes<br/>removes them after the Analyst confirms"]
```

## J1: Create an analysis

The import job parses the demos before the Analyst sees the roster. So the roster form can
show who played in each demo. The recompute then reads only the cached extracts.

```mermaid
flowchart TD
  A["/new: pick files or a folder"] --> B["POST /ui/imports or /ui/uploads"]
  B --> C["Import job runs<br/>page polls /ui/jobs/{id} every second"]
  C -->|Cancel| X["Job cancelled<br/>finished extracts stay cached<br/>no entry is created"]
  C --> D{"Any demo accepted?"}
  D -->|No| R["Import report: every file with its reason"]
  D -->|Yes| E["Roster form<br/>proposed core players, stand-ins, lineups per demo"]
  E --> F["Analyst confirms: team name, roles, lineup overrides"]
  F --> G{"Entry for this team and map exists?"}
  G -->|Yes| H["Error ENTRY_EXISTS"]
  G -->|No| I["Entry, team and roster saved<br/>import job marked with the entry<br/>recompute job starts"]
  I --> J["Page polls the recompute job"]
  J --> K["Redirect to /entries/{id}, Overview tab"]
```

## J2: Add demos

```mermaid
flowchart TD
  A["/entries/{id}/add: pick files"] --> B["POST /api/entries/{id}/demos"]
  B --> C{"Entry already has a running job?"}
  C -->|Yes| Y["CONFLICT_JOB_RUNNING"]
  C -->|No| D["One job: import, then recompute"]
  D --> E["Import checks files<br/>the map must match the entry"]
  E --> F{"Any demo accepted?"}
  F -->|No| G["Job ends. The analysis is unchanged."]
  F -->|Yes| H["Demos added to the entry<br/>recompute over all included demos"]
  H --> I["New version is current<br/>labels carry over to reshaped patterns"]
```

## J3: Explore findings

Other changes on the entry page also start a recompute: include or exclude a demo, set a
demo's lineup or date, or edit the roster.

```mermaid
flowchart TD
  A["Entry page"] --> B{"Version older than SCHEMA_VERSION<br/>or built with other thresholds?"}
  B -->|Yes| U["Banner: Update now → recompute job"]
  B -->|No| C["Tabs: Overview, T, CT, Economy, Utility,<br/>Players, Demos, AI brief"]
  U --> C
  C --> D["Filter: buy, opponent buy, demos, dates, overtime"]
  D --> E["Findings recounted in memory<br/>k of n changes, pattern identity does not"]
  E --> F["Open a finding's rounds<br/>demo file, round, score, round story"]
  E --> G["Rename a pattern<br/>label kept across recomputes"]
  C --> H["Demos tab: include, exclude, lineup, date"]
  C --> I["Roster: core, stand-in, excluded"]
  H --> RC["Recompute job"]
  I --> RC
  RC --> A
```

## J4 and J5

These are short from the Analyst's side. The detail is in
[AI brief and export](ai-brief-and-export.md).

```mermaid
flowchart LR
  subgraph J4["J4 Export"]
    E1["Pick sections and maps on or off"] --> E2["GET /ui/entries/{id}/export"]
    E2 --> E3["One HTML file downloads"]
  end
  subgraph J5["J5 AI brief"]
    A1["AI brief tab"] --> A2["Preview: exact payload, tokens, price"]
    A2 --> A3["Send within 10 minutes"]
    A3 --> A4["Brief shown with evidence<br/>Markdown download"]
  end
```
