# State machines

The lifecycle of each thing the app keeps. Each chart names the code that moves it between
states.

## Job

Table `job`, code `jobs/runner.py`. The page polls `GET /ui/jobs/{id}` every second.

```mermaid
stateDiagram-v2
  [*] --> queued: JobRunner.submit
  queued --> running: worker thread picks it up
  running --> done: function returned
  running --> cancelled: JobCancelled, or cancel flag set at the end
  running --> failed: any other exception
  queued --> failed: app restarted (startup_cleanup)
  running --> failed: app restarted (startup_cleanup)
  done --> [*]
  cancelled --> [*]
  failed --> [*]

  note right of queued
    submit refuses a second job for the
    same entry: CONFLICT_JOB_RUNNING
  end note
```

## Entry version

Table `entry_version`, folders `entries/{id}/v{n}/`, code `Library.begin_version`,
`commit_version`, `abandon_version`.

```mermaid
stateDiagram-v2
  [*] --> building: begin_version
  building --> current: commit_version (one transaction)
  building --> deleted: abandon_version (error or cancel)
  building --> deleted: startup_cleanup after a crash
  current --> previous: the next version is committed
  previous --> deleted: a newer version is committed
  deleted --> [*]

  note right of current
    entry.current_version points here.
    Pages, export and AI brief read only this one.
  end note
```

Only `current` and `previous` are kept on disk.

## Analysis freshness

What the entry page shows. Code `web/pages.py` (`entry_page`).

```mermaid
stateDiagram-v2
  [*] --> NotComputed: entry created
  NotComputed --> Computing: recompute job
  Computing --> UpToDate: version committed
  Computing --> NotComputed: first job failed or cancelled
  Computing --> UpToDate: later job failed, old version kept
  UpToDate --> Computing: demos, roster, lineup or date changed
  UpToDate --> Outdated: app update raised SCHEMA_VERSION
  UpToDate --> Outdated: thresholds changed in Settings
  Outdated --> Computing: Update now
```

`Outdated` means the version has no `patterns.json`, its `schema_version` is below
`core.findings.SCHEMA_VERSION`, or its `config_hash` differs from the saved thresholds. When
findings or round stories change, bump `SCHEMA_VERSION` so older analyses land here.

## Imported file

One row in the import report. Code `jobs/import_job.py`. The full decision tree is in
[Import](import.md#what-happens-to-each-file).

```mermaid
stateDiagram-v2
  [*] --> pending: discovered
  pending --> rejected: ARCHIVE_REJECTED, NOT_CS2, DEMO_UNREADABLE, PARSER_CRASH, PARSER_TIMEOUT, MAP_MISMATCH
  pending --> duplicate: same hash, or same match_key
  pending --> accepted: extract ready
  accepted --> accepted_with_warning: INCOMPLETE_MATCH
  rejected --> [*]
  duplicate --> [*]
  accepted --> [*]
  accepted_with_warning --> [*]
```

## Extract

Folders `extracts/{sha}/{parser}@{version}+s{schema}/`, code `jobs/extract_worker.py`.
Extracts are never changed after they are written.

```mermaid
stateDiagram-v2
  [*] --> partial: run_extract creates dest._partial
  partial --> ready: child exited 0 and no sanity rejection, rename
  partial --> [*]: error, timeout or cancel, folder deleted
  partial --> [*]: startup_cleanup deletes leftovers
  ready --> superseded: parser or extract schema upgraded
  superseded --> ready: new extract built from the retained source or a re-import
  superseded --> used_stale: no source, older extract used, STALE_EXTRACT shown
```

## AI brief

Code `web/api.py`, `ai/confirm.py`, table `ai_brief`.

```mermaid
stateDiagram-v2
  [*] --> Disabled: no ANTHROPIC_API_KEY
  [*] --> None: key set, no brief yet
  None --> Previewed: preview (token valid 10 min)
  Previewed --> Previewed: preview again
  Previewed --> None: token expired, payload changed or app restarted
  Previewed --> Writing: send with the token (single use)
  Writing --> Fresh: grounded, saved
  Writing --> None: AI_UPSTREAM or AI_UNGROUNDED, nothing saved
  Fresh --> Stale: analysis gets a new version
  Fresh --> Previewed: preview a new brief
  Stale --> Previewed: preview a new brief
```

A stale brief still shows in the app, marked as stale. The export leaves it out.
