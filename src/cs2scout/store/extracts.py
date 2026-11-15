"""Read canonical extracts back from the workspace."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from cs2scout.core.schema import TABLES

# What team resolution needs: cheap to load even for many demos.
LINEUP_TABLES = {
    "rounds": None,
    "players": None,
    "round_economy": None,
    "snapshots": ["tick", "steamid", "side"],
}


def read_tables(path: Path, wanted: dict[str, list[str] | None] | None = None
                ) -> dict[str, pl.DataFrame]:  # fmt: skip
    wanted = wanted if wanted is not None else dict.fromkeys(TABLES)
    return {name: pl.read_parquet(path / f"{name}.parquet", columns=cols)
            for name, cols in wanted.items()}  # fmt: skip
