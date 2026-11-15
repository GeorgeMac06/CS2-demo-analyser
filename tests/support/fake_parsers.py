"""Parser adapters that misbehave on purpose (T-04). Loaded by spec in the parse child."""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path

import polars as pl

from cs2scout.core.schema import TABLES, Extract, empty_table

FAKE_STEAMID_BASE = 76561190000000000  # obviously fake, but matches the SteamID pattern


def rows(name: str, records: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(records, schema=TABLES[name])


def tiny_extract() -> Extract:
    """Smallest schema-valid, sane extract: 10 players, 1 round, positions with places."""
    ids = [FAKE_STEAMID_BASE + i for i in range(1, 11)]
    sides = ["T"] * 5 + ["CT"] * 5
    tables = {name: empty_table(name) for name in TABLES}
    tables["players"] = rows(
        "players",
        [{"steamid": s, "name": f"fake{i}", "team_clan_name": "Fake A" if i < 5 else "Fake B"}
         for i, s in enumerate(ids)],
    )  # fmt: skip
    tables["rounds"] = rows(
        "rounds",
        [{"round_num": 1, "start_tick": 100, "freeze_end_tick": 1000, "end_tick": 5000,
          "official_end_tick": 5448, "winner_side": "T", "reason": "terrorists_win",
          "is_knife": False}],
    )  # fmt: skip
    tables["snapshots"] = rows(
        "snapshots",
        [{"tick": 1008, "steamid": s, "side": side, "x": 0.0, "y": 0.0, "z": 0.0, "health": 100,
          "place": f"{side}Spawn"} for s, side in zip(ids, sides, strict=True)],
    )  # fmt: skip
    tables["kills"] = rows(
        "kills",
        [{"tick": 2000, "attacker_steamid": ids[0], "attacker_side": "T",
          "victim_steamid": ids[5], "victim_side": "CT", "weapon": "ak47"}],
    )  # fmt: skip
    tables["grenades"] = rows(
        "grenades",
        [{"entity_id": 1, "entity_serial": 1, "type": "smoke", "thrower_steamid": ids[1],
          "thrower_side": "T", "start_tick": 1100, "land_tick": 1200}],
    )  # fmt: skip
    tables["server_counters"] = rows(
        "server_counters",
        [{"steamid": s, "kills": int(s == ids[0]), "deaths": int(s == ids[5]), "assists": 0,
          "damage": 100 * int(s == ids[0])} for s in ids],
    )  # fmt: skip
    header = {"map_name": "de_fake", "tick_rate": 64.0, "build_num": 1,
              "demo_version_name": "valve_demo_2", "playback_ticks": 6000}  # fmt: skip
    return Extract(header=header, tables=tables)


class TinyAdapter:
    name = "fake"
    version = "0"

    def extract(self, path: Path) -> Extract:
        return tiny_extract()


class RaisingAdapter(TinyAdapter):
    def extract(self, path: Path) -> Extract:
        raise ValueError("corrupt packet at tick 123")


class ExitingAdapter(TinyAdapter):
    def extract(self, path: Path) -> Extract:
        os._exit(13)  # a native crash: no exception, no cleanup


class HangingAdapter(TinyAdapter):
    def extract(self, path: Path) -> Extract:
        time.sleep(600)
        raise AssertionError("unreachable")


class BadSchemaAdapter(TinyAdapter):
    def extract(self, path: Path) -> Extract:
        extract = tiny_extract()
        tables = dict(extract.tables, players=extract.tables["players"].drop("name"))
        return dataclasses.replace(extract, tables=tables)


class NoRoundsAdapter(TinyAdapter):
    def extract(self, path: Path) -> Extract:
        extract = tiny_extract()
        return dataclasses.replace(
            extract, tables=dict(extract.tables, rounds=empty_table("rounds"))
        )


class MissingFieldAdapter(TinyAdapter):
    def extract(self, path: Path) -> Extract:
        return dataclasses.replace(tiny_extract(), missing_fields=("m_szLastPlaceName",))
