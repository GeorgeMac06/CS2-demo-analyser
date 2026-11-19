# CS2 Demo Scout — Test Strategy (v1)

| Field | Value |
|---|---|
| Status | **Draft**, as of 2026-11-15 |
| Sources | [Delivery plan](delivery-plan.md) (WU-\*), [Target design §10](../architecture/target-design.md) (AT-1..11), [Product requirements](../product/requirements.md) |
| Existing tests | None (greenfield). Every portfolio action below is `ADD` or `NO_TEST`. |
| Stack | Python 3.13 and pytest. httpx `TestClient` for the API. Playwright (Chromium) for the browser checks (P-4). |

## 1. Principles for this project

- **Test through the API first.** Most tests import demos through `POST /api/imports` and assert on `GET /findings` or `GET /rounds`.
- **Two data sources, two jobs:**
  - Real demos (P-1, kept local) prove the parser and adapter are accurate.
    - The reference is **inside the demo**. A CS2 demo records two separate things: the event stream (kills, damage, round ends), which our stats are built from, and the game server's own scoreboard counters (per-player kills, deaths, assists, damage; team scores).
    - Comparing the two is an independent check, because the counters are not produced by our logic. They also already reflect any round restores done by admins.
    - The owner supplies no scoreboard data (decided 2026-11-15; this replaces the earlier `goldens.yaml`).
    - **Confirmed by S-1 (2026-11-15):** awpy reads the counters through `ticks()` raw fields, and our event-based K/D/A matched them for 40/40 players ([report](../../spikes/s1_report.md)).
    - The team-score oracle reads `CCSTeam` entities with `ticks(players_only=False)`. That call peaks at 5–9 GB of memory, so G-demos runs demos one at a time.
    - Fallbacks if it cannot: (a) read the counters with demoparser2 in the test only, which is an independent decoder (demoparser2 exposes them as `kills_total`, `deaths_total`, etc.); (b) as a last resort, owner-supplied FACEIT scoreboards.
  - Synthetic matches (WU-3, committed) prove our own logic. That covers team resolution, rounds, patterns, labels and filters, with exact known answers.
  - `FakeParserAdapter` replaces only awpy. Everything after the parser, including the child process, store and API, stays real.
- **Unit tests only where the API is a poor fit:** clustering edge cases, threshold boundaries, the grounding validator, and the archive limits.
- **Not tested:** FastAPI routing, Plotly or Polars behaviour, awpy internals (beyond what T-01 compares), template markup, or getters.

## 2. Risk → test matrix

Priority: **H** means wrong scouting conclusions, data loss or a data leak. **M** means a degraded or confusing result. **L** means cosmetic.

| T-ID | Protected outcome | Defect class | Pri | Action | Level / setup | Oracle | Gate | Plan / AT |
|---|---|---|---|---|---|---|---|---|
| T-01 | Numbers match the real match | Wrong success: parser mapping, round boundaries, side labels, warmup/knife kills counted, suicides or team kills misattributed, round restores double-counted | **H** | ADD | E2E through the API with the P-1 demos. **The reference is the game server's own scoreboard counters recorded in each demo**, read independently of our event-based stats (§1). | Per player K/D/A from our events equal the server's counters at the last tick, using the S-1 counting rules (live window only; kills = enemy kills, team kills ignored; deaths = all deaths; assists = assists on enemy victims, flash assists included). Team scores at the end of round 12 and at the end equal our round winners. Every round's side for the scouted team matches the half structure. A demo where neither team reached the win condition (13, or the overtime rule) is flagged incomplete (FR-IN-5). ADR within **±2.0** of server damage ÷ rounds (set in S-1: max observed 1.75). | G-demos | WU-2, 5, 6, 7 / AT-1 |
| T-02 | The right team, the right side | Boundary: half swap, overtime swaps (MR3), a stand-in in 1 demo, a 4-core demo, a nickname change, 1–2 demo bootstrap | **H** | ADD | E2E through the API, synthetic scenarios | Roster = the expected SteamIDs. Stand-in flagged. Side per round as scripted. `TEAM_NOT_FOUND` for a demo with 2 core players. | G-fast | WU-6 |
| T-03 | Buy classes are correct | Boundary: value exactly at a threshold, pistol rounds 1/13, overtime start rounds, custom thresholds from config | M | ADD | Unit tests on `core.rounds` with table-driven cases | Expected class per case. A non-default config changes the result. | G-fast | WU-6 |
| T-04 | Bad demos never corrupt an entry | Invalid input accepted: truncated demo, `HL2DEMO` header (CS:GO), random bytes, wrong map, the same demo renamed, the same match re-encoded, a parser that raises, a parser that calls `os._exit`, a parser that hangs past the timeout | **H** | ADD | E2E through the API. Truncated copies of P-1 demos (G-demos). Synthetic headers and `FakeParserAdapter` crash modes (G-fast). | Exact error code per file. A truncated demo is either rejected or accepted with the incomplete flag, never as a complete match. The other files import. Entry version and findings are unchanged. No orphaned `_partial` or tmp files. | G-fast + G-demos | WU-2, 5 / AT-4 |
| T-05 | Findings can be traced and recounted | Support or outcome drifting away from `round_refs`. Wrong recount under filters. | **H** | ADD | Property check run over every finding of the T-01 and synthetic entries, across a fixed set of filter combinations | For every finding, k, n and won recomputed from `round_refs` and `round_index` equal the stored values. Findings below support are hidden. The low-sample flag is set when n < limit. | G-fast + G-demos | WU-7, 10–12 / AT-3 |
| T-06 | Interruptions never leave a half-updated entry | Partial failure: server killed during S4–S6, cancel during an extract, a crash during the swap | **H** | ADD | Integration: run the server as a subprocess on a temp workspace, kill it at injected points, restart | `current_version` unchanged. No `building` rows left. Cancelling J1 creates no entry, and finished extracts stay. | G-fast | WU-4 / AT-6 |
| T-07 | Demos are never parsed twice. Stale extracts are never used. | Cache invalidation: the schema version is bumped, the source is retained or missing | M | ADD | E2E through the API with `FakeParserAdapter` counting calls | Adding 1 demo to an entry of N → 1 extract call. A schema bump re-extracts from the retained source. With no source, the demo gets a "stale data" warning and its old extract is kept. | G-fast | WU-4, 5 / AT-5 |
| T-08 | Hostile archives cannot hurt the PC | Abuse: a zip bomb (high ratio), a `../` member name, a multi-member zip, a nested archive, a `.gz` over the size limit | **H** | ADD | E2E through the import API. Archives are generated by the test in tmp. | `ARCHIVE_REJECTED`. No file outside the temp workspace (directory snapshot taken before and after). Peak tmp usage within the limit. | G-fast | WU-5 / AT-7 |
| T-09 | Same inputs, same findings | Nondeterminism: iteration order, clustering ties | **H** | ADD | Integration: run S3–S6 twice on the synthetic entry and the P-1 entry | Identical `findings.json` sha256 | G-fast + G-demos | WU-7, 10–12 / AT-2 |
| T-10 | Patterns reflect what the team really does | Wrong success: wrong site hit, a one-off forced into a cluster, "unresolved" guessed, a fake not detected, a lineup split or merged | **H** | ADD | E2E through the API on synthetic scenarios with known answers, e.g. 6× B fast exec + 5× A split + 1 one-off, a fake round, a no-plant round with no hit, 2 smoke lineups | Expected clusters and members. The one-off is "unique". The no-hit round is "unresolved". The fake is flagged. Lineup counts are exact. | G-fast | WU-10–12 |
| T-11 | User labels survive updates | A rename is lost on recompute, or attached to the wrong pattern | M | ADD | E2E through the API: rename a strategy, add a demo that keeps the pattern, then add one that dissolves it | The label stays on the matched pattern (Jaccard ≥ 0.5). An orphaned label is kept and not shown. | G-fast | WU-13 |
| T-12 | Filters show the right rounds | Wrong subset for round type, opponent buy, demo subset, dates or overtime | M | MERGE into T-05 | — | Covered by T-05's filter combinations | — | WU-7 |
| T-13 | The export works offline and matches the app | Network request in the export. Count mismatch. Personal data leak. | **H** | ADD | Browser: Playwright opens the exported file with network requests logged and routing blocked. A content check parses the export's embedded snapshot. | 0 requests. Every figure container rendered. Every chart has a table. Embedded k/n equal `GET /findings` for the same filter. No match for `7656119\d{10}` or a Windows path pattern. | G-browser | WU-14 / AT-10 |
| T-14 | AI sends nothing unconfirmed and nothing private | Send without confirmation. Token reuse. SteamIDs or paths in the payload. Upstream errors breaking the entry. | **H** | ADD | E2E through the API with a fake HTTP transport for the Anthropic SDK (the SDK runs for real, only the network is faked) | 0 requests before confirm. A token for a different payload → 403. Payload has no SteamID or path matches (synthetic fakes use the `7656119…` pattern on purpose). 401 and 429 → `AI_UPSTREAM`, entry unchanged. | G-fast | WU-15 / AT-9 |
| T-15 | The brief never states ungrounded patterns | A claim with no citation or an unknown citation shown as fact | **H** | ADD | Unit tests on the grounding validator with crafted model outputs | Uncited and unknown-ID claims dropped. More than 20% dropped → `AI_UNGROUNDED`. A brief becomes stale after a demo is added. | G-fast | WU-15 |
| T-16 | Positions land on the map | Wrong world-to-radar transform, wrong lower-level selection | M | ADD | Integration on P-1 extracts | Every live player position maps inside the radar image bounds. The plant positions for site A and site B fall in two separate pixel clusters. | G-demos | WU-8 |
| T-17 | The Analyst can complete J1→J3 (later J4) | UI wiring breaks the main journey | **H** | ADD | Browser: Playwright with semantic locators (roles and labels). P-1 demos for M1, synthetic data for routine runs. | Entry created. Roster confirmed. The overview shows support text. The round drawer lists the rounds. Delete needs the typed name. Every chart has a table (C-3). | G-browser | WU-9, 13 / J1–J3 |
| T-18 | The API cannot be driven from elsewhere | Exposure: LAN bind, DNS rebinding, CSRF | **H** | ADD | Integration: start the real server, inspect the bound socket, send forged Host, Origin and token requests | Bound to 127.0.0.1 only. Each forged request → 403. | G-fast | WU-0 / AT-8 |
| T-19 | Module boundaries hold, so the parser can be swapped | `core` importing awpy, FastAPI or SQLite | M | ADD | Static import-linter contracts | The contracts pass | G-fast | WU-0 / AT-11 |

## 3. Gates

| Gate | Command (planned) | When it is required | Behaviour when prerequisites are missing |
|---|---|---|---|
| **G-fast** | `uv run pytest -m "not demos and not browser"` + `ruff check` + `lint-imports` | Before every commit. Also installed as a git pre-commit hook. | Always runnable |
| **G-demos** | `uv run pytest -m demos --require-demos` | Before completing any WU that touches the parser, ingest, team, rounds, stats, zones or patterns | **Fails** (does not skip) when `tests/local_fixtures/demos/` has no `.dem` files |
| **G-browser** | `uv run pytest -m browser` | Before completing WU-9, 13, 14 and 16 | Fails with install instructions when Chromium is missing (P-4) |
| **G-manual** | Owner review checklist | S-1 report. M1 (stats readability, radar alignment). M2 (pattern plausibility, top-5 per tab). M3 (J1–J5). | — |

**Order within a run:** G-fast first (seconds), then G-demos (minutes, sequential parsing by design), then G-browser.

**Where gates run** (CI added 2026-11-19, `.github/workflows/ci.yml`):

| Gate | On the owner's PC | In GitHub Actions |
|---|---|---|
| G-fast | Pre-commit hook | Every PR and every push to `main`, on Windows |
| G-browser | By hand | Every PR and every push to `main`, on Ubuntu with Chromium |
| G-demos | By hand | Never. Real demos contain SteamIDs and must not be uploaded. |
| Hygiene | — | Every PR. Fails if the PR adds demos, archives, `tests/local_fixtures/` files or a real-looking SteamID (`.github/scripts/hygiene.sh`). |

So every PR must still say whether G-demos ran.

## 4. Test data and privacy

- Real demos stay in `tests/local_fixtures/demos/`, which is gitignored. They are never committed or exported, because they contain the real SteamIDs and nicknames of players (C-2).
- Synthetic scenarios use obviously fake nicknames. Their SteamIDs match the `7656119…` pattern, so the leak checks in T-13 and T-14 have something real to catch.
- Every test runs with `CS2SCOUT_HOME` pointing to a temp directory. The owner's real library is never touched.
- The S-1 report records aggregates only, with no identities.

## 5. Explicit `NO_TEST` and exclusions

| Item | Decision | Reason / alternative control |
|---|---|---|
| Clustering quality on real teams (DRV-8) | NO_TEST (automated) | No objective oracle exists. Covered by the M2 owner review (G-manual). Synthetic T-10 proves the mechanics. Accepted residual risk. |
| Heatmap visual quality and palette | NO_TEST (automated) | Covered by the M1 owner review. T-16 covers the geometry. |
| SQLite migrations | NO_TEST now | Only schema v1 exists. Trigger: the first migration adds a test that a v1 workspace upgrades. |
| Synthetic builder (WU-3) on its own | NO_TEST | Test support code. A defect in it shows up as T-02/T-10 failures against hand-written expected answers. |
| Performance and parse speed | NO_TEST | D5: not a requirement. Peak memory is recorded in S-1 and in job logs for information only. |
| Live Claude API quality | NO_TEST (automated) | Costs money and gives nondeterministic output. The optional live check is G-manual with P-3. T-15 guards grounding. |
| Framework behaviour (FastAPI, Jinja, Plotly, Polars, awpy internals) | Excluded | Dependency guarantee. T-01 covers the awpy outputs we rely on. |
| Browser and OS matrix | Excluded | Single local user on Windows 11 with Chromium-based testing. Exports are checked in Chromium only. Trigger: a teammate reports a rendering issue in another browser. |

## 6. Review and retirement triggers

| Trigger | Action |
|---|---|
| awpy version bump or CS2 update | Re-run G-demos. Update the ADR tolerance only with evidence. |
| `EXTRACT_SCHEMA` or snapshot `schema_version` bump | Update T-07 and T-13 expectations. Keep the old-version cases until old extracts are garbage-collected. |
| ADR-006 switches to polygons | Add zone-assignment cases to T-10 per map. Keep the T-16 bounds check. |
| Q6 replay viewer accepted | Add a browser journey for the replay. No change to the existing tests. |

**Net portfolio:** 18 ADD, 1 MERGE, and 6 justified NO_TEST.

## 7. Status (2026-11-15)

| T-ID | Status | Where |
|---|---|---|
| T-01 | **PASS** (G-demos): adapter part, plus full end to end through the API with server team scores, K/D/A and ADR | `tests/test_awpy_adapter_demos.py`, `tests/test_real_demos_e2e.py` |
| T-02, T-03 | **PASS** | `tests/test_team_and_rounds.py` |
| T-04 | **PASS**: worker crash modes, import-level bad inputs, truncated real demo | `tests/test_extract_worker.py`, `tests/test_import_api.py`, `tests/test_real_demos_e2e.py` |
| T-05 (+T-12 merged) | **PASS** across 8 filter combinations | `tests/test_findings_api.py` |
| T-06 | **PASS**: process killed mid-recompute, cancel during parse, restart cleanup | `tests/test_library_versions.py`, `tests/test_import_api.py` |
| T-07 | **PASS**: one parse per demo, reuse across entries, filters never parse, parser upgrade rebuilds from source or keeps a stale extract | `tests/test_import_api.py`, `tests/test_findings_api.py` |
| T-08 | **PASS** | `tests/test_import_api.py` |
| T-09 | **PASS** | `tests/test_findings_api.py` |
| T-18, T-19 | **PASS** | `tests/test_local_guard.py`, import-linter |
| T-16 | **PASS** (G-demos): all live positions on the radar; A and B plants in separate clusters. Visual overlay checked on one demo. | `tests/test_assets_and_zones.py` |
| T-17 | **PASS** (G-browser): J1→J3 + exclude demo + delete, semantic locators, chart/table pairing (C-3), no console errors | `tests/test_browser_journey.py`; page and template smoke tests in G-fast: `tests/test_pages.py` |
| T-10 | **PASS**: known-answer scenario (`tests/support/scenarios.py`) for T strategies, fakes, unresolved rounds, buy rounds, post-plants, CT setups and stacks, positions, rotations, early duels, retakes and saves, lineups, habits, weapons, roles, and the 2-demo rule | `tests/test_patterns_api.py` |
| T-11 | **PASS**: carry-over rules; label survives an added demo; a role label hides while its player is excluded and returns; clear/unknown label; player keys stable through roster edits | `tests/test_labels.py`, `tests/test_findings_api.py` |
| T-17 (extended) | **PASS**: rename a strategy in the browser, and it persists after a reload | `tests/test_browser_journey.py` |
| T-13 | **PASS**: self-contained, strict CSP, no live controls, counts equal the app, sections/filters, leak guard blocks a SteamID-like nickname; offline in Chromium with 0 requests, all figures drawn, 0 console errors | `tests/test_export.py`, `tests/test_browser_journey.py` |
| T-14 | **PASS**: 0 requests before confirmation (preview and every rejected send). A token for another payload, a tampered, expired or reused token → 403. The payload and the request body have no SteamID or path. A SteamID-like nickname blocks the preview. 401, 429, 529, network failure, refusal and truncation → `AI_UPSTREAM` with the entry and findings unchanged and no brief saved. The request carries exactly the previewed payload. With no key → `AI_DISABLED` and everything else works. | `tests/test_ai_brief.py` |
| WU-16 settings | **PASS**: defaults; saved settings persist; the port is read at start and the variable wins; invalid values are refused and nothing is saved; thresholds apply only on update (filtered views keep the version's thresholds); retention off keeps no copies; the size limit warns without blocking; the form saves and shows errors; an unreadable file means defaults. An export without map images still has every figure. | `tests/test_settings.py`, `tests/test_assets_and_zones.py` |
| Brief rework (2026-11-16) | **PASS**: round timer (clock, titles, tempo axis); a story for every round, with the header, three checkpoints, utility, the opening duel and the plant; nicknames only; the payload carries stories for the filtered rounds and clock params; claims cite rounds, and unknown rounds are dropped; usage and cost are stored and shown; Markdown download (leak-checked); the rounds drawer shows stories and `demo_gototick`; schema 1 offers "Update now". | `tests/test_round_story.py`, `tests/test_ai_brief.py` |
| G-manual M3 | **Pending**: the owner's J1–J5 on their own demos (J5 needs P-3). | — |
| T-15 | **PASS**: uncited and unknown-ID claims dropped. 20% dropped is accepted; more → `AI_UNGROUNDED`, and nothing is saved. The brief goes stale after a demo is added, and only a brief that is not stale is exported, labelled "AI-generated". | `tests/test_ai_brief.py` |
