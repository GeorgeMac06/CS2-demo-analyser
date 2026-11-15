"""T-01 (adapter part, AT-1) on real demos: the canonical extract carries the real match.

The reference is the game server's own scoreboard counters inside each demo. Counting
rules come from spike S-1 (spikes/s1_report.md §2). Team scores per lineup are checked
once lineups exist in core (WU-6).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from cs2scout.core.schema import TABLES
from cs2scout.jobs.extract_worker import run_extract

pytestmark = pytest.mark.demos


@pytest.fixture(scope="module")
def extract(
    real_demo: Path, tmp_path_factory: pytest.TempPathFactory
) -> tuple[dict, dict[str, pl.DataFrame]]:
    dest = tmp_path_factory.mktemp("extract") / real_demo.stem
    outcome = run_extract(real_demo, dest)
    assert outcome.ok, f"{outcome.code}: {outcome.message}"
    tables = {name: pl.read_parquet(dest / f"{name}.parquet") for name in TABLES}
    return outcome.manifest, tables


def test_extract_is_complete_and_clean(extract) -> None:
    manifest, t = extract
    assert manifest["missing_fields"] == []
    assert manifest["issues"] == []  # not even warnings on a normal league demo
    assert t["players"].height == 10
    assert t["server_counters"].height == 10

    for name, side_cols in {
        "kills": ["attacker_side", "victim_side"],
        "snapshots": ["side"],
        "round_economy": ["side"],
    }.items():
        for col in side_cols:
            assert set(t[name][col].drop_nulls().unique()) <= {"T", "CT"}, f"{name}.{col}"

    alive = t["snapshots"].filter(pl.col("health") > 0)
    assert alive["place"].null_count() == 0
    plants = t["bomb"].filter(pl.col("event") == "finish_plant")
    assert plants.height > 0 and plants["bombsite"].null_count() == 0
    assert t["grenades"].height > 0 and t["grenades"]["thrower_steamid"].null_count() == 0


def test_event_kda_equals_server_scoreboard(extract) -> None:
    _, t = extract
    live = t["kills"].filter(pl.col("tick") >= t["rounds"]["start_tick"].min())
    enemy = pl.col("attacker_side") != pl.col("victim_side")
    kills = live.filter((pl.col("attacker_steamid") != pl.col("victim_steamid")) & enemy)
    assists = live.drop_nulls("assister_steamid").filter(
        pl.col("assister_side") != pl.col("victim_side")
    )
    ours = (
        t["server_counters"]
        .select("steamid")
        .join(kills.group_by(steamid="attacker_steamid").len("k"), on="steamid", how="left")
        .join(live.group_by(steamid="victim_steamid").len("d"), on="steamid", how="left")
        .join(assists.group_by(steamid="assister_steamid").len("a"), on="steamid", how="left")
        .fill_null(0)
    )
    both = ours.join(t["server_counters"], on="steamid")
    mismatches = both.filter(
        (pl.col("k") != pl.col("kills"))
        | (pl.col("d") != pl.col("deaths"))
        | (pl.col("a") != pl.col("assists"))
    )
    assert mismatches.height == 0, mismatches.select("k", "kills", "d", "deaths", "a", "assists")
