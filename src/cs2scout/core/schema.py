"""Canonical extract: the contract between any parser adapter and the core (design §5.2).

The extract holds parser facts only. Derived meaning (round types, lineups, zones, stats)
is computed in core from these tables, so a parser swap never changes analysis logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl

EXTRACT_SCHEMA = 1
SIDES = ("T", "CT")
SNAPSHOT_STRIDE_TICKS = 16

_XYZ = {"x": pl.Float32, "y": pl.Float32, "z": pl.Float32}


def _who(prefix: str, xyz: bool = True) -> dict[str, pl.DataType]:
    cols: dict[str, pl.DataType] = {f"{prefix}_steamid": pl.UInt64, f"{prefix}_side": pl.String}
    if xyz:
        cols |= {f"{prefix}_{axis}": dtype for axis, dtype in _XYZ.items()}
    return cols


TABLES: dict[str, dict[str, pl.DataType]] = {
    "players": {"steamid": pl.UInt64, "name": pl.String, "team_clan_name": pl.String},
    "rounds": {
        "round_num": pl.Int32,
        "start_tick": pl.Int32,
        "freeze_end_tick": pl.Int32,
        "end_tick": pl.Int32,
        "official_end_tick": pl.Int32,
        "winner_side": pl.String,
        "reason": pl.String,
        "is_knife": pl.Boolean,
    },
    "round_economy": {
        "round_num": pl.Int32,
        "side": pl.String,
        "equipment_value": pl.Int32,
        "n_players": pl.Int32,
        "parser_buy_type": pl.String,  # cross-check only; core classifies buys itself
    },
    "kills": {
        "tick": pl.Int32,
        **_who("attacker"),
        **_who("victim"),
        **_who("assister", xyz=False),
        "weapon": pl.String,
        "headshot": pl.Boolean,
        "thrusmoke": pl.Boolean,
        "assist_flash": pl.Boolean,
        "is_trade": pl.Boolean,
        "victim_traded": pl.Boolean,
    },
    "damages": {
        "tick": pl.Int32,
        **_who("attacker", xyz=False),
        **_who("victim", xyz=False),
        "weapon": pl.String,
        "dmg_health": pl.Int32,
        "dmg_armor": pl.Int32,
        "health_pre": pl.Int32,
        "health_post": pl.Int32,
    },
    "bomb": {"tick": pl.Int32, "event": pl.String, "steamid": pl.UInt64, "bombsite": pl.String}
    | _XYZ,
    "grenades": {
        "entity_id": pl.Int32,
        "entity_serial": pl.UInt32,
        "type": pl.String,
        **_who("thrower", xyz=False),
        "start_tick": pl.Int32,
        "land_tick": pl.Int32,
        "throw_x": pl.Float32,
        "throw_y": pl.Float32,
        "throw_z": pl.Float32,
        "land_x": pl.Float32,
        "land_y": pl.Float32,
        "land_z": pl.Float32,
    },
    "smokes": {"start_tick": pl.Int32, "end_tick": pl.Int32, **_who("thrower", xyz=False)} | _XYZ,
    "fires": {
        "start_tick": pl.Int32,
        "end_tick": pl.Int32,
        "type": pl.String,
        **_who("thrower", xyz=False),
    }
    | _XYZ,
    "blinds": {
        "tick": pl.Int32,
        **_who("attacker", xyz=False),
        **_who("victim", xyz=False),
        "duration": pl.Float32,
    },
    "snapshots": {
        "tick": pl.Int32,
        "steamid": pl.UInt64,
        "side": pl.String,
        **_XYZ,
        "yaw": pl.Float32,
        "health": pl.Int32,
        "armor": pl.Int32,
        "has_helmet": pl.Boolean,
        "has_defuser": pl.Boolean,
        "has_bomb": pl.Boolean,
        "active_weapon": pl.String,
        "primary_weapon": pl.String,
        "smoke_grenades": pl.Int32,
        "flashbangs": pl.Int32,
        "he_grenades": pl.Int32,
        "fire_grenades": pl.Int32,
        "money": pl.Int32,
        "equipment_value": pl.Int32,
        "place": pl.String,
    },
    # The game server's own scoreboard counters (last value per player): the T-01 reference.
    "server_counters": {
        "steamid": pl.UInt64,
        "kills": pl.Int32,
        "deaths": pl.Int32,
        "assists": pl.Int32,
        "damage": pl.Int32,
    },
}

# Stable row order per table, so identical demos give byte-identical extracts (I-1).
SORT_KEYS: dict[str, tuple[str, ...]] = {
    "players": ("steamid",),
    "rounds": ("round_num",),
    "round_economy": ("round_num", "side"),
    "kills": ("tick", "victim_steamid"),
    "damages": ("tick", "attacker_steamid", "victim_steamid", "dmg_health", "dmg_armor", "weapon"),
    "bomb": ("tick", "event", "steamid"),
    "grenades": ("start_tick", "entity_id", "entity_serial"),
    "smokes": ("start_tick", "thrower_steamid", "x", "y"),
    "fires": ("start_tick", "thrower_steamid", "x", "y"),
    "blinds": ("tick", "attacker_steamid", "victim_steamid", "duration"),
    "snapshots": ("tick", "steamid"),
    "server_counters": ("steamid",),
}

HEADER_KEYS = ("map_name", "tick_rate", "build_num", "demo_version_name", "playback_ticks")


@dataclass(frozen=True)
class Extract:
    header: dict
    tables: dict[str, pl.DataFrame]
    missing_fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class Issue:
    severity: str  # "reject" | "warn"
    message: str


def empty_table(name: str) -> pl.DataFrame:
    return pl.DataFrame(schema=TABLES[name])


def schema_problems(extract: Extract) -> list[str]:
    """Contract violations by an adapter. Any problem means the adapter is wrong."""
    problems = [f"header missing {k}" for k in HEADER_KEYS if k not in extract.header]
    for name, columns in TABLES.items():
        frame = extract.tables.get(name)
        if frame is None:
            problems.append(f"table {name} missing")
            continue
        actual = dict(frame.schema)
        if list(actual) != list(columns):
            problems.append(f"table {name}: columns {list(actual)} != {list(columns)}")
            continue
        for col, dtype in columns.items():
            if actual[col] != dtype:
                problems.append(f"table {name}.{col}: {actual[col]} != {dtype}")
    extra = set(extract.tables) - set(TABLES)
    if extra:
        problems.append(f"unexpected tables {sorted(extra)}")
    return problems


def sanity_issues(extract: Extract) -> list[Issue]:
    """Plausibility of a schema-valid extract (design §6.1 step 6)."""
    t = extract.tables
    issues: list[Issue] = []

    def reject(message: str) -> None:
        issues.append(Issue("reject", message))

    def warn(message: str) -> None:
        issues.append(Issue("warn", message))

    for name in extract.missing_fields:
        reject(f"parser returned no data for required field {name}")
    if t["rounds"].height == 0:
        reject("no rounds")
    if t["players"].height == 0:
        reject("no players")
    if t["snapshots"].height == 0:
        reject("no player positions")
    if issues:
        return issues

    if t["players"].height != 10:
        warn(f"{t['players'].height} players (expected 10)")
    if t["kills"].height == 0:
        warn("no kills")
    if t["grenades"].height == 0:
        warn("no grenades")
    if t["server_counters"].height == 0:
        warn("no server scoreboard counters")
    alive = t["snapshots"].filter(pl.col("health") > 0)
    if alive.height and alive["place"].null_count() == alive.height:
        warn("no place names for alive players")
    return issues
