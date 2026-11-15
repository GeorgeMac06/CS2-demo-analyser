"""Position heatmap grids (FR-PLR-3, design §6.3). Precomputed so app and export match.

With a radar (WU-8) grids are binned in radar pixels over the whole image, so every entry on
a map shares one frame and the grid lines up with the picture. Without map assets they fall
back to world coordinates over the data's extent ("stats only" visuals, DEP-2).
"""

from __future__ import annotations

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.maps import Radar

PHASES = ("early", "mid", "late", "post_plant")
GRID_COLUMNS = {"grid_id": pl.String, "cx": pl.UInt16, "cy": pl.UInt16, "count": pl.UInt32}
POSITION_COLUMNS = {"ref": pl.String, "steamid": pl.UInt64, "side": pl.String, "x": pl.Float32,
                    "y": pl.Float32, "z": pl.Float32, "place": pl.String,
                    "phase": pl.String}  # fmt: skip
TOP_PLACES = 8


def live_positions(snapshots: pl.DataFrame, rounds: pl.DataFrame, plants: pl.DataFrame,
                   cfg: AnalysisConfig, tick_rate: float) -> pl.DataFrame:  # fmt: skip
    """Alive positions during live play, tagged with round ref and phase."""
    windows = rounds.select(
        "ref", "end_tick", tick="freeze_end_tick", freeze_end="freeze_end_tick"
    ).join(plants.select("ref", plant_tick="tick"), on="ref", how="left")
    joined = snapshots.sort("tick").join_asof(windows.sort("tick"), on="tick", strategy="backward")
    live = joined.filter(
        pl.col("ref").is_not_null()
        & (pl.col("tick") <= pl.col("end_tick"))
        & (pl.col("health") > 0)
    )
    seconds = (pl.col("tick") - pl.col("freeze_end")) / tick_rate
    phase = (
        pl.when(pl.col("plant_tick").is_not_null() & (pl.col("tick") >= pl.col("plant_tick")))
        .then(pl.lit("post_plant"))
        .when(seconds < cfg.phase_early_s).then(pl.lit("early"))
        .when(seconds < cfg.phase_mid_s).then(pl.lit("mid"))
        .otherwise(pl.lit("late"))
    )  # fmt: skip
    return live.select("ref", "steamid", "side", "x", "y", "z", "place", phase=phase)


def project(positions: pl.DataFrame, radar: Radar | None) -> tuple[pl.DataFrame, dict]:
    """Add grid coordinates (gx, gy) and level; return the frame the grids are drawn in."""
    if radar is not None:
        projected = positions.with_columns(gx=radar.px(), gy=radar.py(), level=radar.level())
        frame = {"space": "radar", "map": radar.map, "extent": [0.0, float(radar.width), 0.0,
                 float(radar.height)]}  # fmt: skip
        return projected, frame
    projected = positions.with_columns(gx=pl.col("x"), gy=pl.col("y"), level=pl.lit("default"))
    return projected, {"space": "world", "map": None, "extent": extent_of(projected)}


def extent_of(positions: pl.DataFrame, pad: float = 0.02) -> list[float]:
    """[x_min, x_max, y_min, y_max] covering all positions (world fallback only)."""
    if positions.height == 0:
        return [0.0, 1.0, 0.0, 1.0]
    x0, x1 = float(positions["gx"].min()), float(positions["gx"].max())
    y0, y1 = float(positions["gy"].min()), float(positions["gy"].max())
    dx, dy = max(x1 - x0, 1.0) * pad, max(y1 - y0, 1.0) * pad
    return [round(x0 - dx, 1), round(x1 + dx, 1), round(y0 - dy, 1), round(y1 + dy, 1)]


def build_grids(positions: pl.DataFrame, subjects: dict[int, str], frame: dict,
                cfg: AnalysisConfig) -> tuple[dict[str, dict], pl.DataFrame]:  # fmt: skip
    """Counts per cell for the team and each player, per side, phase and level.

    ``positions`` must come from ``project``. Cell (0, 0) is the top-left of the radar.
    """
    if not subjects:  # no confirmed roster yet: nothing to draw
        return {}, pl.DataFrame(schema=GRID_COLUMNS)
    n = cfg.grid_cells
    x0, x1, y0, y1 = frame["extent"]
    inside = (pl.col("gx") >= x0) & (pl.col("gx") < x1) & (pl.col("gy") >= y0) & (pl.col("gy") < y1)
    binned = positions.filter(pl.col("steamid").is_in(list(subjects)) & inside).with_columns(
        cx=((pl.col("gx") - x0) / (x1 - x0) * n).floor().clip(0, n - 1).cast(pl.UInt16),
        cy=((pl.col("gy") - y0) / (y1 - y0) * n).floor().clip(0, n - 1).cast(pl.UInt16),
        subject=pl.col("steamid").replace_strict(subjects, return_dtype=pl.String),
    )
    team = binned.with_columns(subject=pl.lit("team"))
    grid_id = pl.concat_str("subject", "side", "phase", separator=".")
    cells = (
        pl.concat([team, binned])
        .group_by("subject", "side", "phase", "level", "cx", "cy")
        .agg(count=pl.len().cast(pl.UInt32))
        .with_columns(
            grid_id=pl.when(pl.col("level") == "lower").then(grid_id + ".lower").otherwise(grid_id)
        )
    )
    places = _top_places(pl.concat([team, binned]), grid_id)
    meta = {
        row["grid_id"]: {"subject": row["subject"], "side": row["side"], "phase": row["phase"],
                         "level": row["level"], "shape": [n, n], "samples": row["samples"],
                         "top_places": places.get(row["grid_id"], [])} | frame
        for row in cells.group_by("grid_id", "subject", "side", "phase", "level")
        .agg(samples=pl.col("count").sum())
        .sort("grid_id")
        .iter_rows(named=True)
    }  # fmt: skip
    values = cells.select([pl.col(c).cast(t) for c, t in GRID_COLUMNS.items()]).sort(
        "grid_id", "cx", "cy"
    )
    return meta, values


def _top_places(binned: pl.DataFrame, grid_id: pl.Expr) -> dict[str, list[dict]]:
    """The text form of each heatmap (C-3): where the time was spent, by place name."""
    ids = binned.with_columns(
        grid_id=pl.when(pl.col("level") == "lower").then(grid_id + ".lower").otherwise(grid_id),
        place=pl.col("place").fill_null("Unknown"),
    )
    counts = (
        ids.group_by("grid_id", "place")
        .agg(n=pl.len())
        .with_columns(share=(pl.col("n") / pl.col("n").sum().over("grid_id") * 100).round(1))
    )
    top = counts.sort(["grid_id", "n", "place"], descending=[False, True, False])
    out: dict[str, list[dict]] = {}
    for (gid,), grp in top.group_by(["grid_id"], maintain_order=True):
        out[gid] = grp.head(TOP_PLACES).select("place", "share").to_dicts()
    return out
