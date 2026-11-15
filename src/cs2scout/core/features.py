"""Per player-round features for the scouted team (design §5.3 S4).

Counting rules match the game server exactly (spike S-1 report §2):
- kills: enemy victims only, never self; team kills are ignored, not subtracted;
- deaths: every death, including suicides and world damage;
- assists: on enemy victims only, flash assists included.
Damage is capped at each victim's remaining health per round, across all attackers.
"""

from __future__ import annotations

import polars as pl

UTILITY_DAMAGE_WEAPONS = ("hegrenade", "inferno", "molotov", "incgrenade")
THROWN = {"smoke": "smokes", "flashbang": "flashes", "he": "hes", "molotov": "molotovs",
          "incendiary": "molotovs"}  # fmt: skip
HELD = ("smoke_grenades", "flashbangs", "he_grenades", "fire_grenades")

PLAYER_ROUND_COLUMNS = {
    "ref": pl.String, "demo": pl.String, "steamid": pl.UInt64, "side": pl.String,
    "kills": pl.UInt32, "deaths": pl.UInt32, "assists": pl.UInt32, "flash_assists": pl.UInt32,
    "headshots": pl.UInt32, "damage": pl.Int64, "utility_damage": pl.Int64,
    "opening_kill": pl.Boolean, "opening_death": pl.Boolean, "trade_kills": pl.UInt32,
    "traded_death": pl.Boolean, "survived": pl.Boolean, "kast": pl.Boolean,
    "smokes": pl.UInt32, "flashes": pl.UInt32, "hes": pl.UInt32, "molotovs": pl.UInt32,
    "enemies_flashed": pl.UInt32, "flash_duration": pl.Float64, "team_flashed": pl.UInt32,
    "saved_utility": pl.Int64,
}  # fmt: skip


def assign_rounds(events: pl.DataFrame, windows: pl.DataFrame, tick_col: str = "tick"
               ) -> pl.DataFrame:  # fmt: skip
    """Attach the round (ref) an event belongs to: from round start to the next round start."""
    keyed = events.with_columns(pl.col(tick_col).alias("_t")).sort("_t")
    return (
        keyed.join_asof(
            windows.select("ref", pl.col("start_tick").alias("_t"), "window_end"),
            on="_t",
            strategy="backward",
        )  # fmt: skip
        .filter(pl.col("ref").is_not_null() & (pl.col("_t") < pl.col("window_end")))
        .drop("_t", "window_end")
    )


def player_rounds(tables: dict[str, pl.DataFrame], rounds: pl.DataFrame,
                  members: set[int]) -> pl.DataFrame:  # fmt: skip
    """One row per (round, scouted player who played it). ``rounds`` from core.rounds."""
    if rounds.height == 0:
        return pl.DataFrame(schema=PLAYER_ROUND_COLUMNS)
    windows = rounds.sort("start_tick").with_columns(
        window_end=pl.col("start_tick").shift(-1).fill_null(2**31 - 1)
    )
    ids = pl.Series(sorted(members), dtype=pl.UInt64)
    mine = lambda col: pl.col(col).is_in(ids.implode())  # noqa: E731

    snaps = assign_rounds(tables["snapshots"], windows).join(
        rounds.select("ref", "freeze_end_tick", "end_tick", pl.col("side").alias("team_side")),
        on="ref",
    )
    live = snaps.filter(pl.col("tick") >= pl.col("freeze_end_tick"))
    base = (
        live.filter(mine("steamid"))
        .group_by("ref", "steamid")
        .agg(pl.col("side").first(), pl.lit(rounds["demo"][0]).alias("demo"))
    )

    kills = assign_rounds(tables["kills"], windows)
    enemy = pl.col("attacker_side") != pl.col("victim_side")
    first_kill = kills.sort("tick").group_by("ref").first()
    counts = [
        kills.filter(enemy & (pl.col("attacker_steamid") != pl.col("victim_steamid")))
        .group_by("ref", steamid="attacker_steamid")
        .agg(
            kills=pl.len(), headshots=pl.col("headshot").sum(), trade_kills=pl.col("is_trade").sum()
        ),
        kills.group_by("ref", steamid="victim_steamid").agg(
            deaths=pl.len(), traded_death=pl.col("victim_traded").any()
        ),
        kills.drop_nulls("assister_steamid")
        .filter(pl.col("assister_side") != pl.col("victim_side"))
        .group_by("ref", steamid="assister_steamid")
        .agg(assists=pl.len(), flash_assists=pl.col("assist_flash").sum()),
        first_kill.filter(enemy)
        .select("ref", steamid="attacker_steamid")
        .with_columns(opening_kill=pl.lit(True)),
        first_kill.select("ref", steamid="victim_steamid").with_columns(opening_death=pl.lit(True)),
        _damage(tables["damages"], windows),
        _thrown(tables["grenades"], windows),
        _blinds(tables["blinds"], windows),
        _saved(snaps),
    ]
    out = base
    for frame in counts:
        out = out.join(frame, on=["ref", "steamid"], how="left")
    out = out.with_columns(
        pl.col(c).fill_null(0) for c, t in PLAYER_ROUND_COLUMNS.items()
        if c in out.columns and t != pl.Boolean and c not in ("ref", "demo", "steamid", "side")
    ).with_columns(
        pl.col("opening_kill", "opening_death", "traded_death").fill_null(False),
    ).with_columns(
        survived=pl.col("deaths") == 0,
    ).with_columns(
        kast=(pl.col("kills") > 0) | (pl.col("assists") > 0) | pl.col("survived")
        | pl.col("traded_death"),
    )  # fmt: skip
    return out.select([pl.col(c).cast(t) for c, t in PLAYER_ROUND_COLUMNS.items()]).sort(
        "ref", "steamid"
    )


def _damage(damages: pl.DataFrame, windows: pl.DataFrame) -> pl.DataFrame:
    dm = (
        assign_rounds(damages, windows)
        .with_row_index("_order")
        .sort("ref", "victim_steamid", "tick", "_order")
    )
    cum = pl.col("dmg_health").cum_sum().over("ref", "victim_steamid")
    dm = dm.with_columns(
        real=pl.min_horizontal(cum, 100) - pl.min_horizontal(cum - pl.col("dmg_health"), 100)
    ).filter(pl.col("attacker_side") != pl.col("victim_side"))
    return dm.group_by("ref", steamid="attacker_steamid").agg(
        damage=pl.col("real").sum(),
        utility_damage=pl.col("real").filter(pl.col("weapon").is_in(UTILITY_DAMAGE_WEAPONS)).sum(),
    )


def _thrown(grenades: pl.DataFrame, windows: pl.DataFrame) -> pl.DataFrame:
    g = assign_rounds(grenades, windows, "start_tick").with_columns(
        kind=pl.col("type").replace_strict(THROWN, default=None)
    )
    return (
        g.drop_nulls("kind")
        .group_by("ref", steamid="thrower_steamid")
        .agg(**{k: (pl.col("kind") == k).sum() for k in ("smokes", "flashes", "hes", "molotovs")})
    )


def _blinds(blinds: pl.DataFrame, windows: pl.DataFrame) -> pl.DataFrame:
    b = assign_rounds(blinds, windows)
    enemy = pl.col("attacker_side") != pl.col("victim_side")
    team = ~enemy & (pl.col("attacker_steamid") != pl.col("victim_steamid"))
    return b.group_by("ref", steamid="attacker_steamid").agg(
        enemies_flashed=enemy.sum(),
        flash_duration=pl.col("duration").filter(enemy).sum().cast(pl.Float64),
        team_flashed=team.sum(),
    )


def _saved(snaps: pl.DataFrame) -> pl.DataFrame:
    """Grenades still held by players alive at the end of the round (FR-UTIL-4)."""
    at_end = snaps.filter(pl.col("tick") <= pl.col("end_tick")).sort("tick")
    last = at_end.group_by("ref", "steamid").last().filter(pl.col("health") > 0)
    return last.select("ref", "steamid", saved_utility=pl.sum_horizontal(*HELD).cast(pl.Int64))
