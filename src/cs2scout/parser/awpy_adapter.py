"""awpy → canonical extract (ADR-002, spike S-1 report §3).

Rules from S-1:
- awpy returns an all-null column for an unknown raw field instead of raising, so every
  raw field we read is checked and reported in ``missing_fields``.
- ``ticks(players_only=False)`` costs 5-9 GB; it is never used here.
- awpy ``stats`` K/D/A disagree with the server, so they are not part of the extract.
"""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import polars as pl
from awpy import Demo

from cs2scout.core.schema import SNAPSHOT_STRIDE_TICKS, SORT_KEYS, TABLES, Extract

PLACE_FIELD = "m_szLastPlaceName"
COUNTER_PREFIX = "m_pActionTrackingServices.m_matchStats."
COUNTER_FIELDS = {"m_iKills": "kills", "m_iDeaths": "deaths", "m_iAssists": "assists",
                  "m_iDamage": "damage"}  # fmt: skip
DATASETS = (
    "players", "rounds", "round_economy", "kills", "damages", "bomb",
    "grenades", "smokes", "fires", "blinds",
)  # fmt: skip
_SIDE = {"terrorist": "T", "counter-terrorist": "CT"}


def _side(col: str) -> pl.Expr:
    return pl.col(col).replace_strict(_SIDE, default=None, return_dtype=pl.String)


def _conform(name: str, frame: pl.DataFrame) -> pl.DataFrame:
    """Select, cast and order columns exactly as the canonical schema says."""
    columns = TABLES[name]
    return frame.select([pl.col(c).cast(t) for c, t in columns.items()]).sort(
        list(SORT_KEYS[name]), nulls_last=True, maintain_order=True
    )


class AwpyAdapter:
    name = "awpy"
    version = version("awpy")

    def read_header(self, path: Path) -> dict:
        header = Demo(str(path)).header
        return {k: header.get(k) for k in ("map_name", "build_num", "demo_version_name")}

    def extract(self, path: Path) -> Extract:
        demo = Demo(str(path))
        demo.load(*DATASETS)
        raw = demo.header

        per_tick = demo.ticks([PLACE_FIELD, *(COUNTER_PREFIX + f for f in COUNTER_FIELDS)])
        per_tick = per_tick.filter(pl.col("steamid") != 0)
        missing = tuple(
            f
            for f in (PLACE_FIELD, *(COUNTER_PREFIX + f for f in COUNTER_FIELDS))
            if per_tick.height and per_tick[f].null_count() == per_tick.height
        )

        tables = {
            "players": demo.players.filter(pl.col("steamid") != 0),
            "rounds": demo.rounds.with_columns(
                winner_side=_side("winner_side"),
                reason=pl.col("reason_name"),
                is_knife=pl.col("is_knife_round"),
            ),  # fmt: skip
            "round_economy": demo.round_economy.with_columns(
                side=_side("side"), parser_buy_type=pl.col("buy_type")
            ),
            "kills": demo.kills.with_columns(
                _side("attacker_side"), _side("victim_side"), _side("assister_side")
            ),
            "damages": demo.damages.with_columns(_side("attacker_side"), _side("victim_side")),
            "bomb": demo.bomb,
            "grenades": self._grenades(demo.grenades),
            "smokes": demo.smokes.with_columns(_side("thrower_side")),
            "fires": demo.fires.with_columns(_side("thrower_side")),
            "blinds": demo.blinds.with_columns(_side("attacker_side"), _side("victim_side")),
            "snapshots": demo.snapshots(every=SNAPSHOT_STRIDE_TICKS)
            .with_columns(_side("side"))
            .join(
                per_tick.select("tick", "steamid", pl.col(PLACE_FIELD).alias("place")),
                on=["tick", "steamid"],
                how="left",
            ),
            "server_counters": per_tick.sort("tick")
            .group_by("steamid")
            .agg(
                pl.col(COUNTER_PREFIX + f).drop_nulls().last().alias(name)
                for f, name in COUNTER_FIELDS.items()
            ),
        }
        header = {
            "map_name": raw.get("map_name"),
            "tick_rate": float(demo.tick_rate),
            "build_num": raw.get("build_num"),
            "demo_version_name": raw.get("demo_version_name"),
            "playback_ticks": raw.get("playback_ticks"),
            "server_name": raw.get("server_name"),
        }
        return Extract(
            header=header,
            tables={name: _conform(name, frame) for name, frame in tables.items()},
            missing_fields=missing,
        )

    @staticmethod
    def _grenades(trajectories: pl.DataFrame) -> pl.DataFrame:
        """One row per observed trajectory: first point = throw, last point = landing."""
        ordered = trajectories.sort("tick")
        return ordered.group_by(["entity_id", "entity_serial", "start_tick"]).agg(
            pl.col("type").first(),
            pl.col("thrower_steamid").first(),
            _side("thrower_side").first().alias("thrower_side"),
            pl.col("tick").last().alias("land_tick"),
            pl.col("x").first().alias("throw_x"),
            pl.col("y").first().alias("throw_y"),
            pl.col("z").first().alias("throw_z"),
            pl.col("x").last().alias("land_x"),
            pl.col("y").last().alias("land_y"),
            pl.col("z").last().alias("land_z"),
        )
