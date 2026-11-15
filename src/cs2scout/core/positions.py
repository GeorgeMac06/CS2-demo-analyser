"""Where players are at given moments of a round, in zones (shared by WU-10..12)."""

from __future__ import annotations

from collections import Counter, defaultdict

import polars as pl

from cs2scout.core.schema import SNAPSHOT_STRIDE_TICKS
from cs2scout.core.zones import PlaceNameZones, Zone

CELL = 64.0  # world units per place-index cell
_NEIGHBOURS = [(dx, dy) for r in range(1, 4) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
               if max(abs(dx), abs(dy)) == r]  # fmt: skip


def positions_at(snapshots: pl.DataFrame, rounds: pl.DataFrame, seconds: list[float],
                 tick_rate: float) -> pl.DataFrame:  # fmt: skip
    """Every present player's position at ``seconds`` after each round's freeze end.

    Rows: ref, steamid, side, t (seconds), tick, x, y, place, alive. A moment after the
    round ended is skipped. The nearest snapshot within half a second is used.
    """
    targets = (
        rounds.select("ref", "freeze_end_tick", "end_tick")
        .join(pl.DataFrame({"t": [float(s) for s in seconds]}), how="cross")
        .with_columns(tick=(pl.col("freeze_end_tick") + pl.col("t") * tick_rate).cast(pl.Int32))
    )
    targets = targets.filter(pl.col("tick") <= pl.col("end_tick"))
    players = snapshots.select("steamid").unique()
    grid = targets.join(players, how="cross").sort("tick")
    snaps = snapshots.select("tick", "steamid", "side", "x", "y", "place", "health").sort("tick")
    joined = grid.join_asof(
        snaps, on="tick", by="steamid", strategy="nearest",
        tolerance=SNAPSHOT_STRIDE_TICKS * 2, check_sortedness=False,
    )  # fmt: skip
    return joined.drop_nulls("side").select(
        "ref", "steamid", "side", "t", "tick", "x", "y", "place", alive=pl.col("health") > 0
    )


class PlaceIndex:
    """Name any map coordinate after the place where players stood there (grenades, kills)."""

    def __init__(self, snapshots: pl.DataFrame) -> None:
        cells: dict[tuple[int, int], Counter] = defaultdict(Counter)
        frame = snapshots.drop_nulls("place").select(
            cx=(pl.col("x") / CELL).floor().cast(pl.Int32),
            cy=(pl.col("y") / CELL).floor().cast(pl.Int32), place=pl.col("place"),
        ).group_by("cx", "cy", "place").len()  # fmt: skip
        for cx, cy, place, n in frame.iter_rows():
            cells[(cx, cy)][place] += n
        self._cells = {k: c.most_common(1)[0][0] for k, c in cells.items()}

    def place(self, x: float | None, y: float | None) -> str:
        if x is None or y is None:
            return "Unknown"
        cx, cy = int(x // CELL), int(y // CELL)
        if (cx, cy) in self._cells:
            return self._cells[(cx, cy)]
        for dx, dy in _NEIGHBOURS:
            if (cx + dx, cy + dy) in self._cells:
                return self._cells[(cx + dx, cy + dy)]
        return "Unknown"


def zone_of(zones: PlaceNameZones, map_name: str, place: str | None) -> Zone:
    return zones.zone(map_name, place)


def group_label(zone: Zone) -> str:
    """The coarse group used for setups: the lane when known, otherwise the place itself."""
    return zone.lane or zone.name
