# CS2 Demo Scout — Product Requirements

| Field | Value |
|---|---|
| Status | **Proposed**: decisions D1–D8 accepted by the owner on 2026-11-15. Open items are listed in §9. |
| Owner | Repository owner (sole decision maker) |
| Horizon | v1 = a personal scouting tool for league matches (FACEIT/ESEA) |
| Scope of this doc | Product behaviour only. Architecture, stack and task plan are separate artifacts. |

## 1. Problem and intended outcome

To prepare for a league match, a team has to watch the opponent's demos by hand to learn how that opponent plays one map. This takes hours, and it misses patterns that only show up across many rounds.

**Intended outcome:** the owner gives the app X demos of one team on one map. The app produces evidence-backed findings about:

- how the **team** plays each side, and
- how **each player** behaves.

Each finding comes with a frequency and a sample size. The owner can explore the findings in a local web app and export a brief for teammates.

### Actors

| Actor | Description |
|---|---|
| Analyst (owner) | Runs the app locally. Imports demos, reviews and confirms rosters, explores results, exports briefs. |
| Teammate (reader) | Receives an exported brief. Does not install anything. |
| Claude API (optional) | External service. Gets aggregated stats only, and only when the Analyst asks for an AI summary. |

### Accepted owner decisions (2026-11-15)

| ID | Decision |
|---|---|
| D1 | Interface is a **local web app** that runs on the Analyst's PC and opens in the browser. |
| D2 | Input is **downloaded FACEIT/ESEA `.dem` files** (compressed files also accepted, §3). The app **auto-detects the scouted team** and the Analyst confirms it. |
| D3 | In-scope insight areas: **T-side strategies, CT-side setups, utility usage, individual player profiles**. |
| D4 | Output is **deterministic stats and visuals first**. An **optional LLM summary** is added on request. The app works fully without an API key. |
| D5 | The number of demos per analysis varies widely, usually **more than 3**. **Analysis speed is not a requirement.** Correctness and depth come first. |
| D6 | Analyses are kept in a **saved library** of team + map entries. New demos can be added to an entry later. |
| D7 | **Exportable report** that teammates can open with no install. |
| D8 | The LLM provider is **Claude (Anthropic API)**. |

## 2. Scope

### In scope (v1)
- One analysis = one **team** + one **map** + N demos.
- The four insight areas in D3, each split by **side** and **round type**.
- Radar-based visuals (heatmaps, position plots, utility landing plots) for every supported map.
- Saved library, incremental updates, report export, optional AI brief.

### Non-goals (v1)
- Downloading demos automatically from FACEIT/ESEA or other sites (the "fetch by team URL" option was rejected).
- Analysis across several maps in one view, or "team overall" stats across maps.
- Scouting your own team for self-review. This is not prevented, but it is not a design target.
- Live or in-game overlays, 2D round replay with a playback scrubber (candidate for v2, see §9 Q6), and voice/comms analysis.
- Ratings or predictions of who wins.
- Multi-user hosting, accounts, and cloud sync.
- Speed targets (D5).

### Optional ideas (not committed)
- 2D round replay viewer for any round a finding refers to.
- Comparing two library entries, e.g. the same team at the start and end of a season.
- PDF export in addition to HTML.

## 3. Core journeys

### J1 — Create a new analysis
1. **Trigger:** the Analyst chooses "New analysis" and selects demo files or a folder.
2. **Preconditions:** the files are readable locally.
3. The app checks every demo (FR-IN-2). It shows each file's status: accepted, rejected with the reason, or duplicate.
4. The app finds the dominant map. Demos on any other map are rejected with the reason "map mismatch" (FR-IN-3).
5. The app proposes the scouted team (FR-TEAM-1). The Analyst confirms it or edits it.
6. The app parses the demos and computes the analysis. It shows progress per demo. The Analyst can cancel.
7. **Success:** a library entry exists for team + map. It opens on the overview dashboard.
8. **Alternatives:**
   - All demos are rejected: no entry is created, and the app shows a list of the reasons.
   - The Analyst cancels: no partial entry is saved. Parse results for demos that finished stay cached, so a retry does not re-parse them.

### J2 — Add demos to an existing entry
- Same flow as J1, starting from a library entry. The map must match the entry's map.
- Demos already in the entry are reported as duplicates and skipped.
- The roster check runs again. New players are proposed as stand-ins or roster changes for the Analyst to confirm.
- All findings are computed again over the full demo set.

### J3 — Explore findings
- The Analyst moves between Overview, T side, CT side, Utility, and Players.
- Filters: round type, demo subset (include or exclude single demos), date range, and per player.
- Every finding shows **support**: "seen in k of n eligible rounds (across m demos)". The Analyst can open the list of matching rounds (demo, round number, score).

### J4 — Export a brief
- The Analyst picks the sections to include and exports one self-contained HTML file (FR-EXP-1).

### J5 — Generate an AI summary (optional)
- Available only when a Claude API key is set up.
- The app shows the Analyst what will be sent (findings and short round summaries, no raw demos) before anything is sent (FR-AI-2).

## 4. Functional requirements

Status for every item below: **Proposed**.

### 4.1 Input and validation (IN)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-IN-1 | The app accepts `.dem` files. It also accepts `.dem` files compressed as `.bz2`, `.gz` or `.zip`, which FACEIT/ESEA downloads often use. It accepts single files and folders. | Given a folder with 2 `.dem` files and 1 `.dem.bz2` file, all 3 are listed as candidates. |
| FR-IN-2 | Each demo is checked. A demo that is unreadable, truncated, or not CS2 is rejected with a reason that says what went wrong. Other demos keep processing. | One corrupt file in a set of 6 gives 5 accepted demos and 1 rejected with a reason. |
| FR-IN-3 | All demos in an analysis must be on the same map. Mismatched demos are rejected with the reason "map mismatch (found X, expected Y)". | Adding a Mirage demo to an Inferno entry is rejected. The entry is unchanged. |
| FR-IN-4 | Duplicate demos are found by content and match identity, not by filename, and are skipped. | The same demo under two filenames is imported only once. |
| FR-IN-5 | Incomplete matches are accepted, but they are flagged and their round count is shown. Examples: an early surrender, or a demo that starts mid-match. | A 9-round surrender demo is accepted with the label "incomplete (9 rounds)". |
| FR-IN-6 | Warmup and knife rounds are excluded from all statistics, and so are rounds that are not live. Overtime rounds are included and labelled; a filter can exclude them. | Warmup kills never appear in any stat. The OT filter changes the round count. |

### 4.2 Team identification (TEAM)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-TEAM-1 | The app proposes the scouted team. Players are identified by **SteamID**, not nickname. The **core roster** is the players who appear on the same team in at least half of the accepted demos. The team name from the demo metadata is shown, but it is not trusted on its own. | 6 demos, 5 players in all 6, and 1 stand-in in a single demo: the core roster is 5 players, and the stand-in is listed separately. |
| FR-TEAM-2 | The Analyst can confirm or edit the roster, mark stand-ins, and set a display name for the team. | The edits are kept and used in every later recompute. |
| FR-TEAM-3 | A demo where the scouted team is not detected is flagged for the Analyst. Detected means at least 3 core players on one side. The Analyst can exclude the demo or assign the team in it. | A demo with only 2 core players triggers the flag. |
| FR-TEAM-4 | Side swaps at halftime and in overtime are tracked. Every round is labelled with the side the scouted team played. | Rounds 1–12 T and 13–24 CT (MR12) are labelled correctly. So are swaps in overtime. |
| FR-TEAM-5 | Player nickname changes across demos are merged under one SteamID. The most recent nickname is shown. | A player who is "abc" in one demo and "abc-" in another is one profile. |

### 4.3 Round classification (RND)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-RND-1 | Every round is classified by the scouted team's buy: **pistol, eco, force/half-buy, full buy**. The class comes from the team's equipment value at freeze-time end. Thresholds can be configured. Defaults are open item Q1. | Rounds 1 and 13 are always pistol. A full-buy round with rifles and utility is classified "full buy". |
| FR-RND-2 | The opponent's buy class is recorded too, so results can be filtered by matchup, e.g. "our full buy vs their eco". | The filter "vs opponent eco" shows only those rounds. |
| FR-RND-3 | The round outcome and how the round ended are recorded: elimination, bomb exploded, defused, or time ran out. Score and time-to-end are recorded too. | Round results agree with the scoreboard in the demo. |

### 4.4 T-side strategies (TS)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-TS-1 | **Default setups:** at set checkpoints in a T round, the app records each player's **map area**. Proposed checkpoints are 15s, 30s and 45s after freeze-time end. Area means the demo's built-in place name, or a callout overlay if one exists. The most common setups are reported with their frequency. | Each listed setup shows "k/n T rounds" and links to those rounds. |
| FR-TS-2 | **Execute and hit detection:** for each T round the app finds the **site hit** (A, B or mid-to-site). It uses bomb plant site, attacker concentration, and utility landing areas. It also records **hit timing**: the round time of first site contact or of the plant. | Every T round where the bomb was planted has a site. Rounds with no plant and no clear hit are labelled "no hit / unresolved". They are not guessed. |
| FR-TS-3 | **Strategy clustering:** similar T rounds are grouped into recurring **strategies**. Rounds count as similar when they share setup, site, timing band and utility. Each strategy gets an automatic name (e.g. "B fast exec, ~0:25, 3 smokes"), its frequency, its win rate, and example rounds. The Analyst can rename a strategy. | With at least 2 support rounds, each cluster lists its member rounds. One-off rounds are shown as "unique" and are never forced into a cluster. |
| FR-TS-4 | **Tempo profile:** the app shows the distribution of first-contact time and plant time. Rounds are labelled rush, default, or late. | A histogram is shown per round type. |
| FR-TS-5 | **Economy behaviour:** the app reports what the team does on pistol, eco and force rounds. This covers where they go, whether they stack, and whether they rush. It also covers the after-plant setup: player positions after the plant. | The Players → Pistol view shows a separate pistol-round breakdown. |
| FR-TS-6 | **Mid-round adaptation:** the app finds rounds where the team's mass moves from one site to the other after the 45s checkpoint (rotations/fakes). It reports how often this happens and after which events. | Fakes are shown as their own pattern category. |

### 4.5 CT-side setups (CT)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-CT-1 | **Standard positions:** the app finds each player's usual area at round start. It reports each player's main position and their alternates with frequencies, e.g. "Player X: B anchor 70%, connector 20%". | Every core player has a position distribution in their CT rounds. |
| FR-CT-2 | **Setups:** the app finds the team's recurring CT setups, i.e. the combination of player positions such as 2-1-2 or a 3-man A stack. It reports frequency and win rate, split by round type. | Each setup links to its rounds. |
| FR-CT-3 | **Aggression and info plays:** the app finds early pushes, peeks for information, and early kills or deaths away from the default positions. It reports who does them, where, and how often. | Each event is tied to a player, a round, and a time. |
| FR-CT-4 | **Rotations:** after first contact or the first utility on a site, the app measures who rotates and how fast. | Rotation time is shown per player. |
| FR-CT-5 | **Retake vs save:** in rounds where the bomb is planted, the app records retake attempts, saves, and how the retakes turned out. | Save rate and retake win rate are shown. |

### 4.5a Economy (ECO)

Added 2026-11-19 (issue #6). Each round outside the pistols is a **full buy** (the FR-RND-1 full class), a **force buy** (not full, and the team spent more than half its cash) or a **save** (not full, and the team kept at least half). Cash and kept gear are read from the players at round start and at freeze-time end.

| ID | Requirement | Acceptance |
|---|---|---|
| FR-ECO-1 | **After the pistol:** the buy in the 2nd round of each half, split by the pistol result, and in the 3rd round, split by both earlier results. | "2nd round, pistol lost: save" shows k/n over the rounds after a lost pistol. |
| FR-ECO-2 | **Force or save by situation:** the buy split by money a player at round start (cash plus kept gear, in bands), by score (behind by 3+, within 2, ahead by 3+), by the round before (lost a full buy, lost a force or save, won), on the last round of a half and when facing match point. | Each situation's n is the rounds in that situation, and a filter recounts it. |
| FR-ECO-3 | **Saving guns:** per side, how often someone is still alive with a gun at the end of a round lost on a force or full buy, which guns, and who. | The saved guns and the players are listed. |
| FR-ECO-4 | **Forces and saves:** per side, the guns bought (upgraded pistols and armor included) and the plays (T: site and pace; CT: stack) on force buys and on saves. | Each gun and play shows k of that side's force buys or saves. |

### 4.6 Utility (UTIL)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-UTIL-1 | Every grenade is recorded: smoke, flash, HE, molotov/incendiary and decoy. The record has the thrower, the throw position, the landing position, round time, side, and round type. | Grenade counts agree with the demo's events. |
| FR-UTIL-2 | **Recurring lineups:** throws with a similar landing spot and throw spot are grouped into lineups. Each lineup has a name or label, who throws it, how often, and when. | A smoke thrown into the same spot in many rounds shows as one lineup with its count. |
| FR-UTIL-3 | **Flash effectiveness:** for each player, the app reports enemies flashed, flash duration, teammates flashed, and kills that follow a flash. | These values are shown per player. |
| FR-UTIL-4 | **Utility per round:** the app reports the average utility thrown and saved per player and per round type. It also shows the utility used in each strategy and setup. | The strategy and setup views list their utility. |

### 4.7 Player profiles (PLR)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-PLR-1 | **Role inference:** each player gets a suggested role with evidence, e.g. entry, lurk, AWP, support, anchor or rotator. Roles are suggestions shown with the metrics behind them. They are not presented as facts. | Each role label lists the metrics behind it. The Analyst can override the label. |
| FR-PLR-2 | **Opening duels:** the app reports opening kills and deaths, their locations, timing and weapons, split by side. | Each player has opening stats per side. |
| FR-PLR-3 | **Positional heatmaps** per player, per side, and per round phase (early, mid, late, post-plant), drawn on the map radar. | A heatmap is drawn for every supported map (§5 DEP-2). |
| FR-PLR-4 | **Habits and tells:** the app reports repeated behaviour such as the same peek in the same spot, a repeated early death area, a favourite weapon by buy type, and clutch behaviour (1vX attempts and outcomes). Each habit has its frequency. | Every habit has at least the minimum support (FR-CONF-1). |
| FR-PLR-5 | **Core stats** per side: kills, deaths, ADR, KAST, trade rate (traded and trading), and utility damage. | The values agree with the demo's events. Formulas are documented in the app. |

### 4.8 Confidence and evidence (CONF): applies to all findings

| ID | Requirement | Acceptance |
|---|---|---|
| FR-CONF-1 | Every pattern shows its **support** (k/n rounds, m demos). A pattern below a configurable minimum support is not shown as a "pattern". | A pattern seen in 1 of 40 rounds is not listed among the top patterns. |
| FR-CONF-2 | If the sample is too small for a side or round type, the app shows a **low-sample warning**. The default limit is fewer than 10 rounds (open item Q2). | With 2 demos, the pistol views show the warning. |
| FR-CONF-3 | Every finding can be traced to its rounds. The Analyst can always see which rounds make up a stat. | Opening a finding lists demo, round and score for each round. |
| FR-CONF-4 | Every finding is labelled with **recency**. Findings can be weighted toward or filtered to recent demos, since teams change their strategies. | The date-range filter changes the findings. The demo date is shown on every round. |

### 4.9 Library (LIB)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-LIB-1 | The library lists entries (team + map) with demo count, date range, and last updated time. | A new entry appears after J1. |
| FR-LIB-2 | Entries can be renamed, deleted (after confirmation), and changed by adding or removing demos. | Removing a demo recomputes the findings without it. |
| FR-LIB-3 | Parse results are cached per demo. Recomputing does not re-parse demos that have not changed. | Reopening an entry or changing a filter does not re-parse. |
| FR-LIB-4 | The library survives app restarts. The source `.dem` files are not needed again after import. The original paths are remembered, and re-import is supported. | Moving the original demos away does not break an existing entry. |
| FR-LIB-5 | The same team can have one entry per map. The team identity (roster, name) is shared across those entries. | Team "X" on Mirage and on Inferno shares its roster edits. |
| FR-LIB-6 | The library groups entries by team. Two team rows are **one team** when at least 3 of their main five players are the same, as in a Major's core rule. The main five are the players seen in the most demos. So a stand-in, or an import saved as a new team, doesn't split a team. *Added 2026-11-22 by the owner.* A **team page** shows the team's name, its main five and other players with the number of demos each played (nicknames only), and one row per map: demos, rounds, won and lost (overall, T and CT), date range, a low-sample warning per side, and a link to the map's analysis. Maps are sorted by demo count. A map not computed yet shows its demo count and "not computed". No veto analysis and no stats pooled across maps. | Team "X" with Mirage (3 demos) and Inferno (1 demo) shows Mirage first, and Inferno's short side is marked low sample. An Ancient import with a stand-in, saved as a new team, shows on X's page; a team sharing only 2 players with X does not. |

### 4.10 Export (EXP)

| ID | Requirement | Acceptance |
|---|---|---|
| FR-EXP-1 | The app exports one **self-contained HTML file**: no external requests, images embedded. The Analyst picks the sections. Teammates open it in any browser. | The file opens offline and shows heatmaps and tables. |
| FR-EXP-2 | The export includes support and sample size for every finding, the demo list with dates, and the time it was generated. | Support values in the export match the app. |
| FR-EXP-3 | The optional AI summary can be included. It is labelled as AI-generated. | The label is visible. |

### 4.11 AI summary (AI): optional

| ID | Requirement | Acceptance |
|---|---|---|
| FR-AI-1 | When a Claude API key is set up, the Analyst can generate an "anti-strat brief". It covers the team's tendencies, each player's tendencies, and suggested counters. Without a key, the feature is hidden or disabled with an explanation, and everything else works. | With no key, every non-AI feature still works. |
| FR-AI-2 | Only **findings and round summaries** are sent: patterns, stats, support values, player nicknames, and one short summary per round (positions by place name at the checkpoints, utility, the opening duel, the plant, the result). Raw demos, SteamIDs and coordinates are not sent. *Changed 2026-11-16 by the owner: aggregates alone could not show lurk paths, pistol strats or rounds to watch.* The Analyst can preview the payload, and confirmation is required before sending. | The preview matches what is sent. |
| FR-AI-3 | The brief must refer to findings by their support. It must not state patterns that are not in the stats. A brief is saved with the entry and the date it was generated. It goes stale when the demo set changes, and the app shows a "stale" label. | Adding a demo marks the brief stale. |
| FR-AI-4 | API errors (bad key, rate limit, network) are shown clearly. They never damage the entry. | Generating with a wrong key shows an error, and the entry is unchanged. |

## 5. Constraints, dependencies and data

| ID | Item |
|---|---|
| DEP-1 | **Demo parsing library:** the owner has used `demoparser2` before (see the ESEA-Analyst repo). The library choice belongs to the architecture artifact. Requirement: the chosen parser must produce ticks, player positions, grenade events and economy for current CS2 demos. |
| DEP-2 | **Map assets:** heatmaps need a radar image and world-to-radar calibration for each map. v1 covers the **current Active Duty pool**. If a map has no assets, all stats still work, and radar visuals are replaced by a notice. |
| DEP-3 | **CS2 updates** can change the demo format. A parse failure must give a clear error (FR-IN-2), never wrong data that looks fine. |
| DEP-4 | **Claude API:** optional and paid per use. The key is stored locally (e.g. in `.env`) and is never written to exports or logs. |
| C-1 | Runs locally on Windows 11. The web UI is served on `localhost` only, never exposed to the network. |
| C-2 | **Privacy:** demos contain SteamIDs and nicknames of real players. The data stays on the PC. Exports contain nicknames and stats only, not SteamIDs; Q7 asks whether to change this. |
| C-3 | **Accessibility:** heatmap and chart colours must also work for colour-vision-deficient readers. Every chart also has a table or text form. |
| C-4 | **Copyright:** the app uses only map radar assets it is allowed to redistribute. It uses no FACEIT/ESEA branding. |

## 6. States to handle

- **Empty library:** the app shows a first-run prompt to create an analysis.
- **Importing / parsing:** per-demo progress and a cancel button. Partial cancel behaves as described in J1.
- **Partial failure:** the accepted demos continue, and the rejected ones are listed with reasons.
- **Low sample:** see FR-CONF-2.
- **Stale AI brief:** see FR-AI-3.
- **Unsupported map visuals:** see DEP-2.

## 7. Outcome measures

| Measure | Baseline | Target | Evidence |
|---|---|---|---|
| Time to prepare a scouting brief for one map | Unknown. The owner's current manual process has not been measured. | Unknown. Set after the first real use. | The owner times one manual prep and one prep with the app. |
| Prediction usefulness | None | Unknown | After a match, the owner notes which reported tendencies actually happened. |

Functional acceptance (§4) says the app works. It does not show that the app improves match prep. Product impact is checked separately, using the measures above.

## 8. Assumptions that could change scope

- A1: FACEIT/ESEA demos are GOTV/server demos that contain all 10 players and full grenade events. If some are POV demos, coverage drops. **Confirmed 2026-11-15** on 4 ESEA Mirage demos (spike S-1).
- A2: The built-in place names in the demo data are fine-grained enough for setup detection. If not, hand-drawn callout polygons per map become a v1 dependency (DEP-2). **Partly confirmed 2026-11-15:** place names are always present and work at site and lane level (e.g. "A ramp", "palace", "B apartments"). They do not name spots inside a site (e.g. firebox vs ticket booth). v1 accepts this. The M2 review decides whether finer positions are needed (ADR-006).
- A3: The usual competitive format is MR12. Other formats (MR15, wingman) are out of scope.
- A4: 5+ demos per map is enough for strategy clustering to be useful. Below that, the app depends on low-sample warnings.
  - **At risk (2026-11-15).** The owner found that FACEIT no longer allows downloading demos from earlier ESEA seasons. Only the current season's demos are available. The first sample is **4 Mirage demos** for one team.
  - Consequences:
    - Analyses will often be built from about 3–8 demos per map.
    - The low-sample warnings (FR-CONF-2) and the support labels (FR-CONF-1) carry more weight than planned.
    - Adding demos as the season goes on (J2) becomes the normal workflow.
    - The minimum-support defaults (Q2) must be re-checked against 4 demos at milestone M2.
  - Scope is unchanged.

## 9. Open questions (none block the architecture work)

| ID | Question | Default if not answered |
|---|---|---|
| Q1 | Buy-class thresholds (team equipment value) | Common community thresholds, e.g. eco < $5k, force $5k–$20k, full > $20k. Adjustable in settings. |
| Q2 | Minimum support and low-sample limits | **Decided 2026-11-15 (M2 tuning on 4 real demos):** a team pattern needs at least 3 rounds, at least **10%** of eligible rounds, and to appear in at least **2 demos**. Per-player measures (habits, positions, rotations, weapons, clutches, roles) need at least 3 rounds; a share of all rounds is not meaningful for them. Warning below 10 rounds. The earlier 15% default hid every real T strategy (best was 7 of 50 rounds). |
| Q3 | Strategy checkpoint times (FR-TS-1) | 15s, 30s and 45s after freeze-time end |
| Q4 | Use only built-in place names, or also add custom callout polygons? | Built-in place names first. Polygons are added only if A2 fails. |
| Q5 | Scope of the "suggested counters" text in the AI brief | Included, labelled as suggestions |
| Q6 | Is a 2D round replay viewer wanted in v1? | No (v2 candidate) |
| Q7 | Include SteamIDs or profile links in exports? | No |
