# ADR-002: awpy 3.3.0 behind our own adapter and canonical schema

| Field | Value |
|---|---|
| Status | **Accepted** on 2026-11-15. The owner accepted the stack conditionally on spike S-1, and S-1 passed ([report](../../../spikes/s1_report.md)). |
| Owner / decider | Repository owner |
| Source | [target-design.md §9](../target-design.md) (row ADR-002) |
| Affects | DEP-1, DEP-3, DRV-1, DRV-3, U-1, U-2. Design §5.2 (canonical extract), §6.1 (parse worker). Delivery WU-2. |

## Context

The app must read CS2 demos accurately. Every number it shows must trace back to the demo (DRV-1, DRV-2). The demo format changes with CS2 updates (DEP-3). The owner used demoparser2 before, for kill events only. awpy 3.x has its own Rust decoder (pbdems2) and higher-level datasets: rounds, buy types, trades, grenade trajectories, bomb sites and map assets. awpy 3.3.0 was released on 2026-11-12, three days before this decision.

## Decision drivers

1. Correctness against the game server's own numbers (QS-1)
2. Coverage of what the design needs: positions, place names, grenades, economy, round structure
3. Less custom code in high-risk areas: round reconstruction, entity resolution
4. The ability to swap parsers when CS2 or the library changes (DRV-3)
5. Memory and stability on the owner's PC

## Considered options

| Option | Fit to drivers |
|---|---|
| **A. awpy 3.x behind our adapter** | Rounds come from `CCSGameRules`, so they work without round events. Typed Polars datasets. Raw fields via `ticks()`. Map data via awpy-data. Small maintainer base, and a very new release. |
| B. demoparser2 directly | Mature raw access, and the owner knows it. We would write round reconstruction, trades, buy types and grenade trajectory handling ourselves. |
| C. Both in production | Two decoders to keep updated. No requirement needs both. |

## Decision

- Use **awpy, pinned exactly at `3.3.0`**, and only inside `cs2scout.parser`. An import-linter contract enforces this.
- The adapter maps awpy output to our canonical extract schema. Everything downstream depends only on that schema.
- Usage rules from S-1:
  1. Validate every requested raw field. A column that is entirely null in a demo with players is an error, because awpy does not raise on misspelled names.
  2. Never call `ticks(players_only=False)` on the production path. It peaks at 5–9 GB of memory.
  3. Compute K/D/A from events with the rules in the S-1 report §2. awpy's `stats` K/D/A disagree with the server for 9 of 40 players.
  4. Use awpy `stats.adr` for ADR, within ±2.0 of the server.

**Deliberately undecided:**
- When to upgrade past 3.3.0. Upgrades are allowed only when G-demos passes.
- Whether a test-only demoparser2 reader is ever needed. Today awpy reads the server counters itself.

## Consequences

- **Positive:**
  - S-1 matched the server for 40/40 players on K/D/A and 4/4 on scores.
  - The production path parses a demo in 4–10 s and peaks at 0.5–0.8 GB.
  - Extracts are 1.6–2.9 MB per demo.
- **Negative:**
  - We depend on a young release with a small maintainer base.
  - The silent-null behaviour needs defensive checks.
  - awpy's ready-made `stats` cannot be trusted for K/D/A.
- **Neutral:** awpy's map data comes from the same project (ADR-006, WU-8).
- **Accepted risk:** a CS2 update can break parsing until awpy ships a fix. Imports fail clearly in the meantime (QS-2), and entries already imported keep working.

## Validation

- **Done:** spike S-1 (report linked above).
- **Ongoing:**
  - G-demos runs T-01 against the server counters before any parser-related WU completes, and after every awpy or CS2 update.
  - T-04 covers crash, timeout and truncated-file behaviour.

## Review triggers

- T-01 fails after a CS2 or awpy update and no awpy fix arrives within a reasonable time. Then write a demoparser2 adapter against the same schema.
- awpy stops being maintained.
- A new requirement needs data that awpy cannot read.
