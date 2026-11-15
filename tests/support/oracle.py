"""Test-only reference reads that are too expensive for the app (spike S-1 report §3).

Team scores come from CCSTeam entities via ``ticks(players_only=False)``, which peaks at
5-9 GB. Each read runs in its own spawned process so the memory is returned afterwards.
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path


def _team_scores(demo_path: str, half_tick: int) -> tuple[list[int], list[int]]:
    import polars as pl
    from awpy import Demo

    teams = (
        Demo(demo_path)
        .ticks(["m_iScore", "m_iTeamNum"], players_only=False)
        .filter((pl.col("class_name") == "CCSTeam") & pl.col("m_iTeamNum").is_in([2, 3]))
        .drop_nulls("m_iScore")
    )

    def at(tick: int) -> list[int]:
        rows = teams.filter(pl.col("tick") <= tick).sort("tick").group_by("entity_id").last()
        return sorted(rows["m_iScore"].to_list(), reverse=True)

    return at(int(teams["tick"].max())), at(half_tick)


def server_team_scores(demo_path: Path, half_time_tick: int) -> tuple[list[int], list[int]]:
    """(final, half-time) team scores as the game server recorded them, high score first."""
    with multiprocessing.get_context("spawn").Pool(1, maxtasksperchild=1) as pool:
        return pool.apply(_team_scores, (str(demo_path), half_time_tick))
