# ADR-006: Map zones from the game's place names, behind a ZoneProvider port

| Field | Value |
|---|---|
| Status | **Accepted** on 2026-11-15. The owner accepted it conditionally on spike S-1, and S-1 confirmed place names are available ([report](../../../spikes/s1_report.md)). |
| Owner / decider | Repository owner |
| Source | [target-design.md §9](../target-design.md) (row ADR-006), §5.5 |
| Affects | DRV-7, A2, Q4. FR-TS-1 and FR-TS-2 (setups, site hits), FR-CT-1 and FR-CT-2 (positions, setups), FR-PLR-4 (habits). Delivery WU-8, WU-10..12. |

## Context

Setup, strategy and position findings need each player's location as a named zone, such as "A ramp" or "B apartments", not raw coordinates. The game records a place name for each player. Hand-drawing callout polygons for every map in the pool costs effort up front, and it has to be maintained whenever Valve edits a map.

**S-1 facts, from Mirage, 4 demos:**
- The raw field `m_szLastPlaceName` was never empty in 2,209 samples.
- It has 23 distinct names, covering lanes and sites: `TRamp`, `PalaceInterior`, `Connector`, `Jungle`, `Apartments`, `Underpass`, `BombsiteA`, and so on.
- Each bombsite is a **single** name. There are no names for spots inside a site, such as firebox or ticket booth.

## Decision drivers

1. Setup and strategy detection works at lane and site level (FR-TS-1, FR-CT-2)
2. Little authoring and maintenance effort for a solo owner
3. Finer precision can be added later without touching pattern code

## Considered options

| Option | Fit |
|---|---|
| **A. Game place names + a small per-map place → site/lane table** | No authoring beyond a ~25-row table per map. Lane and site precision. Updates with the game. |
| B. Hand-drawn callout polygons per map | Any precision we want. High authoring and upkeep cost. Coordinates have to be checked against map updates. |
| C. Clustering player coordinates inside each place | Finer spots appear automatically. Labels are unnamed or hard to name. Adds complexity before it is needed. |

## Decision

- Implement `ZoneProvider` with **`PlaceNameZones`**: the zone is the place name.
- A per-map table maps each place name to a site (A, B or none) and a lane (e.g. A-main, mid, B-main, CT side, T side).
- Pattern code depends only on the port.

**Deliberately undecided:**
- Finer spots inside a site (option B or C). The trigger below decides.
- The table rows for maps other than Mirage. WU-8 writes them from the place names seen in demos.

## Consequences

- **Positive:** v1 needs no polygon authoring, and zones get the same names players use in the game.
- **Negative:** findings cannot tell positions inside a site apart. "B anchor" is possible; "B anchor plays bench vs van" is not.
- **Neutral:** heatmaps (FR-PLR-3) use coordinates, so precision inside sites still shows up visually.
- **Accepted risk:** CT setups that differ only inside a site will merge into one setup. They show up as low-variance setups with high support.

## Validation

- **Done:** S-1 confirmed availability and lane/site granularity on Mirage.
- **Planned:**
  - T-10 (synthetic) proves the pattern logic on zones.
  - The M2 owner review judges whether lane/site setups are useful enough.

## Review triggers

- At M2, the owner marks CT setups or habits as "too coarse to act on". Then add option C (coordinate sub-clusters within a place) for site places first, and fall back to option B per map only if C's labels are unusable.
- A map in the pool has place names that are missing or too coarse in its demos (found in WU-8).
