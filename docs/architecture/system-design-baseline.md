# CS2 Demo Scout — System Design Baseline

| Field | Value |
|---|---|
| Status | **Draft v1**, as of 2026-11-15 |
| Owner | Repository owner. The owner is the only stakeholder, operator and decision maker. |
| Readers | The owner, and anyone (human or agent) who designs or builds the system |
| Product source | [docs/product/requirements.md](../product/requirements.md). That document owns all functional rules. This baseline does not copy them. It refers to them by ID. |
| Scope | Architecture-driving requirements and constraints only. The solution design belongs in a separate proposal. |

**Shared metadata.** Every register row has owner = repository owner and as-of = 2026-11-15, unless the row says otherwise.

**Evidence status:**
- `CONFIRMED`: observed in the repository or the environment, or stated by the owner.
- `ASSUMED`: a working estimate. It must be checked against the trigger given.
- `UNKNOWN`: no value exists yet.

## 1. Business context

- **Problem:** manual demo review to scout league opponents is slow, and it misses patterns that span many rounds.
- **Actors:** the Analyst (owner), Teammates who read the exports, and the optional Claude API.
- **Horizon:** a personal tool for ongoing league seasons. It has no external users or commercial commitments.
- **Critical journeys:** J1 create an analysis, J2 add demos, J3 explore findings, J4 export a brief, J5 generate an AI brief. All are defined in the product source, §3.
- **Non-goals that matter for architecture** (product source §2):
  - no demo downloading,
  - no multi-user hosting or accounts,
  - no cloud sync,
  - no speed targets,
  - no cross-map aggregation.

## 2. Driver register

Criticality: `DRIVER` shapes the structure. `SUPPORTING` constrains choices. `INFORMATIONAL` gives context.

| ID | Theme / parameter | Applicability | Criticality | Evidence | Value / measure | Source | Review trigger |
|---|---|---|---|---|---|---|---|
| DRV-1 | Correctness: computed stats match the demo's own events | APPLICABLE | DRIVER | CONFIRMED | 100% match on kills, deaths, round results and score, checked on a reference demo set | FR-PLR-5, FR-RND-3, FR-UTIL-1 | Any mismatch found in use |
| DRV-2 | Evidence traceability: every finding links to the rounds behind it | APPLICABLE | DRIVER | CONFIRMED | Every finding can be resolved to its rounds (demo, round, tick range) | FR-CONF-1..4, FR-TS-3 | — |
| DRV-3 | Parser fidelity, and CS2 demo-format changes over time | APPLICABLE | DRIVER | CONFIRMED (risk), ASSUMED (rate) | A parse failure gives a clear rejection, never data that looks valid but is wrong | DEP-1, DEP-3, FR-IN-2 | A CS2 update or a parser release |
| DRV-4 | Recompute without re-parsing | APPLICABLE | DRIVER | CONFIRMED | Demos already imported: 0 re-parsed on reopen, on a filter change, or when another demo is added or removed | FR-LIB-3, J2 | — |
| DRV-5 | Local-only trust boundary and privacy | APPLICABLE | DRIVER | CONFIRMED | Server reachable on loopback only. Two outbound calls are allowed: (1) the Claude API, after the Analyst confirms; (2) an explicit, one-time, pinned and checksummed map-asset fetch (`cs2scout assets fetch`). The second was added 2026-11-15 by the plan review. Exports contain no SteamIDs. | C-1, C-2, FR-AI-2, DEP-4, Q7 | Owner wants LAN or hosted access |
| DRV-6 | Self-contained export | APPLICABLE | DRIVER | CONFIRMED | The exported file makes 0 network requests when opened. All charts and heatmaps render offline. | FR-EXP-1 | — |
| DRV-7 | Map geometry: radar images, world-to-radar calibration, location granularity | APPLICABLE | DRIVER | CONFIRMED for Mirage (S-1). Other maps ASSUMED. | All current Active Duty maps have radar visuals. Setup detection works at place-name granularity (site and lane level, ADR-006). | DEP-2, A2, Q4 | A2 fails on real demos. The map pool changes. |
| DRV-8 | Pattern-mining quality: clustering of setups, strategies and lineups | APPLICABLE | DRIVER | UNKNOWN | Owner judgement on real demos. No numeric target exists. | FR-TS-1..3, FR-CT-2, FR-UTIL-2, Q2, Q3 | First real-data review |
| DRV-9 | Durability of library entries | APPLICABLE | SUPPORTING | CONFIRMED | A crash or cancel during import or recompute leaves the previous entry state intact. No partial entries. | J1, J2, FR-LIB-4 | — |
| DRV-10 | Idempotent import | APPLICABLE | SUPPORTING | CONFIRMED | Re-importing the same demo never adds it twice or changes stats | FR-IN-4 | — |
| DRV-11 | Untrusted input: demo files and archives | APPLICABLE | SUPPORTING | CONFIRMED | Archive extraction is bounded in size and file count. It never writes outside the app workspace. | FR-IN-1 | — |
| DRV-12 | Optional, isolated LLM integration | APPLICABLE | SUPPORTING | CONFIRMED | Every non-AI feature works with no key and no network | D4, FR-AI-1, FR-AI-4 | — |
| DRV-13 | LLM cost per brief | APPLICABLE | SUPPORTING | UNKNOWN | No cost envelope has been set | DEP-4 | Owner sets a budget |
| DRV-14 | Analysis latency and throughput | NOT_APPLICABLE | — | CONFIRMED | No target. "Speed of analysis does not matter at all." | D5 | Owner changes D5 |
| DRV-15 | Responsiveness of filters on already-computed data | APPLICABLE | SUPPORTING | UNKNOWN | No target. Handling rule: filters must run on precomputed tables, never by re-parsing. | J3, FR-LIB-3 | The UI feels slow in use |
| DRV-16 | Accessibility of visuals | APPLICABLE | SUPPORTING | CONFIRMED | Colour-vision-safe palettes. Every chart has an equivalent table or text form. | C-3 | — |
| DRV-17 | Asset licensing: radar images and map data | APPLICABLE | SUPPORTING | UNKNOWN | Only redistributable assets are used | C-4 | Before the first export is shared |
| DRV-18 | Availability, SLOs, multi-region, compliance regimes | NOT_APPLICABLE | — | CONFIRMED | Single-user local app with no hosted service (product §2 non-goals) | — | Hosting becomes a goal |

## 3. Workload and data

| Parameter | Evidence | Value | Source / note | Review trigger |
|---|---|---|---|---|
| Demos per analysis | CONFIRMED (shape), ASSUMED (upper bound) | Usually more than 3. Varies a lot. Design ceiling: **50 per entry**. **Update 2026-11-15:** only current-season ESEA demos can be downloaded from FACEIT, so the realistic range is about **3–8** per map. The first sample is 4. | Owner answer (D5) and owner observation of FACEIT. The ceiling stays as a harmless upper bound. | Any entry exceeds 50. FACEIT access changes. |
| Demo file size | CONFIRMED (n=4) | **208–361 MB** uncompressed (the first 4 Mirage demos). Compressed files are smaller. | Measured on 2026-11-15 | A demo over 500 MB |
| Rounds per demo | CONFIRMED (format), ASSUMED (distribution) | MR12: 13–24 regulation rounds, plus overtime | A3 | Other formats appear |
| Players per demo | ASSUMED | 10, from GOTV/server demos | A1 | Inspect the first real demos |
| Grenade and kill events | ASSUMED | Hundreds per demo | — | Measure |
| Library size | UNKNOWN | No value. Grows by team × map. | — | — |
| Retention | CONFIRMED | Entries are kept until the Analyst deletes them. Source demos are not needed after import. | FR-LIB-2, FR-LIB-4 | — |
| Concurrency | CONFIRMED | 1 user and 1 browser session | D1 | — |

**Implication:** raw tick-level position data is the largest volume. It is on the order of 10⁵–10⁶ player-position rows per demo. The design must define:
- what is kept at full resolution,
- what is downsampled,
- what is discarded after features are extracted.

This is a design decision, not a fixed constraint.

## 4. Environment and platform constraints

| ID | Constraint | Evidence | Value |
|---|---|---|---|
| ENV-1 | Operating system | CONFIRMED | Windows 11 Home (owner's PC) |
| ENV-2 | Available runtimes | CONFIRMED | Python 3.11 and 3.13 (`py -0`), Node 20.19, Git 2.51 |
| ENV-3 | Hardware | CONFIRMED | 16 logical CPUs, 32 GB RAM, about 597 GB free on `C:` |
| ENV-4 | Parser ecosystem | CONFIRMED (availability), UNVERIFIED (fit) | `demoparser2` 0.42.2 and `awpy` 3.3.0 are on PyPI. awpy wraps demoparser2 and adds map data. The owner has used demoparser2 before (ESEA-Analyst). It has not yet been tested here on real demos. |
| ENV-5 | Network | CONFIRMED | Offline-capable. The Claude API is the only outbound dependency, and it is optional. |
| ENV-6 | Operations | CONFIRMED | One operator (the owner). No CI, no on-call, no deployment target. Delivery cadence: UNKNOWN. |

## 5. Critical quality scenarios

| ID | Source → stimulus | Environment | Artifact | Response | Measure |
|---|---|---|---|---|---|
| QS-1 Correctness | Analyst imports a real demo | Normal operation | Parsing + stats | Per-player K/D, round winners and final score computed from events equal the server's own scoreboard counters recorded in the demo | 100% on the reference set |
| QS-2 Format change | A CS2 update changes the demo format | The installed parser version is outdated | Import | The demo is rejected with a parser error. Existing entries still open from their stored data. | 0 corrupted entries. 0 silent partial imports. |
| QS-3 Incremental update | Analyst adds 1 demo to an entry with N demos | Normal operation | Library + recompute | Only the new demo is parsed. The findings are recomputed over N+1 demos. | Already-imported demos re-parsed = 0 |
| QS-4 Privacy | Analyst asks for an AI brief | Key is set up | AI integration | A payload preview is shown. One call goes to the Anthropic API after confirmation. The payload has no SteamIDs and no raw tick data. | Network calls before confirmation = 0 |
| QS-5 Export | A teammate opens an exported brief | Offline browser | Export | All sections and visuals render | External requests = 0 |
| QS-6 Interruption | The app crashes, or the Analyst cancels, during import or recompute | Any | Library | The entry is unchanged or fully updated. Never half-updated. | 0 partial entries after restart |
| QS-7 Hostile input | An archive that is malformed or oversized is imported | Any | Import | It is rejected with a reason. No writes outside the workspace. Decompression is bounded. | 0 writes outside the workspace |
| QS-8 Exposure | Another device on the LAN tries to reach the app | App running | Web server | The connection is refused | Server binds to loopback only |

## 6. Data semantics and recovery

- **Consistency:** each entry has one consistent state per recompute, and recompute swaps in the new state atomically (DRV-9). Findings and their support counts come from the same state.
- **Idempotency:** a demo's identity is its content hash plus match identity. Importing it again does nothing (DRV-10).
- **Cache validity:** a cached parse is valid only for the same content hash, parser version and extraction schema version. When any of these changes, the cached parse is invalid and the demo is re-parsed, which needs the source demo.
  - Gap: FR-LIB-4 says source demos are not needed after import. So a parser or schema upgrade can re-extract only demos whose source files are still available.
  - The design must handle this: keep compact source copies, or keep enough extracted data, or warn the Analyst.
  - This is listed as `UNKNOWN` decision U-3.
- **Recovery:** RTO is not applicable (local app). The target is no loss of data already saved (RPO = last completed import or recompute). Backups are the owner's own file backups. The app does not provide a backup feature in v1.

## 7. Security and privacy

- **Trust boundary 1, loopback:** the browser and the local server are the only participants. There are no accounts or auth, because there is a single local user (DRV-5).
- **Trust boundary 2, files:** demo files and archives are untrusted input. The parser is third-party native code. Archive handling must be bounded (DRV-11).
- **Trust boundary 3, outbound:** only to the Anthropic API, only after confirmation, and only aggregated data. The key is read from local configuration. It is never logged, exported, or included in a payload.
- **Data classification:** SteamIDs and nicknames of real players are personal data. They stay local. Exports contain nicknames only (C-2, Q7 default).
- **Destructive actions:** deleting an entry needs confirmation (FR-LIB-2).
- **Compliance regimes:** not applicable (DRV-18).

## 8. Operations and cost

- One owner runs, updates and fixes the app. Setup and dependency updates must be doable by one person on Windows without admin rights. This is ASSUMED; check it when packaging is designed.
- The Claude API cost is per brief. No budget exists (DRV-13). The safe handling rule: briefs are generated only when the Analyst explicitly asks for one.

## 9. Assumptions and unknowns

| ID | Item | Status | Owner / next evidence action |
|---|---|---|---|
| U-1 | A1/A2: GOTV demos contain all 10 players and full grenade events. Place names are fine-grained enough. | **CONFIRMED** (S-1, 2026-11-15). A1 holds. A2 holds at site and lane level, not for spots inside a site. | Resolved. See `spikes/s1_report.md` and ADR-006. |
| U-2 | Demo size and row counts (§3) | **CONFIRMED** (n=4). 208–361 MB. 76k–127k snapshot rows. 1.6–2.9 MB extracts. 0.5–0.8 GB parse peak. | Resolved. See `spikes/s1_report.md`. |
| U-3 | How the app re-extracts data after a parser or schema upgrade when source demos are gone | UNKNOWN → handling proposed | `target-design.md` ADR-003 proposes keeping a compressed copy of each source demo (a setting, on by default). The decision is Proposed until the owner accepts it. |
| U-4 | Responsiveness target for filters (DRV-15) | UNKNOWN | Owner. Revisit only if the app feels slow. |
| U-5 | LLM cost envelope (DRV-13) | UNKNOWN | Owner. Optional. |
| U-6 | Licence of the radar images and map data source (DRV-17) | UNKNOWN | Check the chosen asset source's licence before sharing the first export |
| U-7 | Quality bar for pattern mining (DRV-8) | UNKNOWN | Owner reviews the first clustering output on real demos |

## 10. Review triggers

- A CS2 update, or a major parser release. Re-run the QS-1 reference set.
- An entry goes over 50 demos, or the host runs short of memory or disk.
- The owner wants teammates to use the app live, beyond exports. This changes DRV-5 and DRV-18 substantially.
- The Active Duty map pool changes (DRV-7).
- A2 fails. Custom callout polygons then become a v1 dependency.
