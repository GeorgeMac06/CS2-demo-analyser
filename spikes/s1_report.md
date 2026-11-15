# Spike S-1 report: awpy on real ESEA demos

| Field | Value |
|---|---|
| Date | 2026-11-15 |
| Work unit | WU-1 ([delivery plan](../docs/delivery/delivery-plan.md)) |
| Script | [`spikes/s1_parse.py`](s1_parse.py): `uv run python spikes/s1_parse.py OUT_DIR tests/local_fixtures/demos/*.dem` |
| Parser | awpy **3.3.0** (pinned in `pyproject.toml`), Polars 2.1.0, Python 3.13.7, Windows 11 |
| Sample | 4 ESEA Mirage demos of one team (current season), 208–361 MB each, 16–29 rounds. One went to overtime (16-13). |
| Privacy | Aggregates only. No SteamIDs, player names or team names appear in this report. |
| **Verdict** | **PASS.** awpy can supply everything the design needs. ADR-002 (awpy) and ADR-006 (place-name zones) are accepted, with the constraints below. |

## 1. Results per question

| Question (source) | Result | Evidence (4 demos) |
|---|---|---|
| All 10 players present? (A1, U-1) | **Yes** | 10 non-bot players in each demo. Team names present for all 10. |
| Kill, damage, bomb and grenade data populated? (U-1) | **Yes** | 136–222 kills and 492–859 damage events per demo. All plants have a bombsite (50/50). Grenade throwers resolved: 100% (1,725 trajectories). Smoke, fire and blind intervals present. |
| Warmup separable? (FR-IN-6) | **Yes** | 7–12 kills per demo happen before round 1 starts. Excluding them is required for the server counters to match. |
| Knife rounds? | None in ESEA demos | `is_knife_round` = 0 in all 4 |
| Can we read the server's scoreboard counters? (T-01 reference) | **Yes, via `ticks()`** | `m_pActionTrackingServices.m_matchStats.m_iKills` / `m_iDeaths` / `m_iAssists` / `m_iDamage` are populated for every player. Team scores come from `m_iScore` on `CCSTeam` entities. |
| Do our event-based K/D/A match the server? (QS-1) | **Yes, 40/40 players exact** | See the rules in §2 |
| Does awpy's own `stats` table match the server? | **No, 31/40** | awpy's `stats` K/D/A disagree for 2–3 players per demo. We must compute K/D/A ourselves. |
| ADR vs server | **Within 1.75 for 40/40** | The server's `m_iDamage` matches no event-based definition exactly: 76/160 player-rounds agree. awpy `stats.adr` differs from server damage ÷ rounds by at most 1.75. **Tolerance set: ±2.0 ADR.** |
| Final and half-time scores from round winners | **4/4 exact** | Example: 16-13 (overtime), 13-3, 13-9, 13-11. Half-time scores also match. |
| Complete-match rule (FR-IN-5) | 4/4 complete | 13 in regulation, or 16-13 under the MR3 overtime rule |
| Side tracking (FR-TEAM-4) | **Observed, not assumed** | Lineups never split across sides (0 mixed rounds). Sides swap at round 13. **In overtime, no swap at round 25; the swap comes at round 28** (OT half-time). Design §6.2 now uses observed sides per round. |
| Place names available? (A2, U-1, ADR-006) | **Yes, never empty** | Raw field `m_szLastPlaceName`: 0 nulls in 2,209 alive-player checkpoint samples. |
| Are place names fine-grained enough? (A2) | **Lane and site level: yes. Inside a site: no.** | Mirage has 23 distinct names: `BombsiteA`, `BombsiteB`, `TRamp`, `PalaceAlley`, `PalaceInterior`, `Stairs`, `SnipersNest`, `Jungle`, `Connector`, `Scaffolding`, `TopofMid`, `Middle`, `Catwalk`, `Ladder`, `Underpass`, `House`, `Apartments`, `BackAlley`, `SideAlley`, `Shop`, `Truck`, `TSpawn`, `CTSpawn`. A site is one bucket: there are no names for spots inside it, such as firebox or ticket booth. |
| Peak memory (U-2) | **0.5–0.8 GB** on the production path | Peak after loading datasets + snapshots + per-tick places/counters: 499–825 MB. The test-only `CCSTeam` query (`players_only=False`) raises the peak to **5.4–9.1 GB** and takes 7–12 s. |
| Parse time (informational, D5) | 4–10 s production path. 13–23 s with the test-only checks. | Sequential, one demo per process |
| Extract size (U-2) | **1.6–2.9 MB per demo** (estimate was 5–15 MB) | All datasets + 4 Hz snapshots as Parquet |
| Row counts (U-2) | Snapshots every 16 ticks: 76k–127k rows. Per-tick: 1.2–2.0 M rows. | — |

## 2. Counting rules that match the server exactly

These rules become part of T-01's oracle and `core` stats (WU-7):

| Stat | Rule (live window only: tick ≥ round 1 `start_tick`) |
|---|---|
| Kills | Kills where attacker ≠ victim **and attacker side ≠ victim side**. Team kills are not counted and are not subtracted. |
| Deaths | Every death of the player, including suicides and world or bomb deaths |
| Assists | Kill rows where the player is the assister **and the victim is an enemy**. Flash assists are included. |
| ADR | awpy `stats.adr`. Compared with server `m_iDamage ÷ rounds_played` within **±2.0**. |
| Team score | Count of round winners per lineup, using the observed side of each lineup per round |

## 3. Constraints for the adapter (WU-2)

1. **A misspelled raw field silently returns an all-null column. No error is raised.** The adapter must reject any requested raw field whose column is entirely null in a demo that has players, with `PARSER_FIELD_MISSING` recorded as a warning that fails the sanity checks.
2. **Never use `ticks(..., players_only=False)` on the production path.** It costs 5–9 GB of memory. Team scores in production come from round winners. The `CCSTeam` read is a T-01 oracle only, run one demo at a time.
3. Read place names and counters through one `ticks()` call per demo. Downsample to snapshot ticks before storing.
4. Do not use awpy `stats` for K/D/A. Use it for ADR only (within tolerance) and as a cross-check.

## 4. Decisions and document updates

- **ADR-002 accepted:** [`decisions/0002-demo-parser.md`](../docs/architecture/decisions/0002-demo-parser.md). awpy pinned at 3.3.0.
- **ADR-006 accepted:** [`decisions/0006-zones.md`](../docs/architecture/decisions/0006-zones.md). Place names give site- and lane-level zones. Finer spots inside a site are deferred to an M2 review trigger.
- U-1 and U-2 (baseline) resolved. A1 holds. A2 holds at lane and site level.
- Target design §3 (estimates), §5.2 (extract) and §6.2 (sides) updated. Test strategy T-01 updated with the rules in §2.

## 5. Limits of this evidence

- One map (Mirage), one team, 4 demos, one league. Other maps' place names are not checked yet. WU-8 builds the per-map place → site/lane table and will see them.
- One overtime demo. The OT swap rule (swap at 28, none at 25) rests on n=1. The design uses observed sides, so it does not depend on that rule.
- The server's exact damage formula is unknown [UNVERIFIED]. The ±2.0 ADR tolerance is set from 40 observations.
