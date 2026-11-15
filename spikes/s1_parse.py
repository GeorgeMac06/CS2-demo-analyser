"""Spike S-1 (WU-1): can awpy give us what the design needs from real demos?

Usage:
    uv run python spikes/s1_parse.py OUT_DIR DEMO [DEMO ...]

Each demo is parsed in its own child process so peak memory is measured per demo.
Output is aggregates only: no SteamIDs, player names or team names (test strategy §4).
Findings are written up in spikes/s1_report.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

MATCH_STATS = "m_pActionTrackingServices.m_matchStats."
COUNTER_FIELDS = ("m_iKills", "m_iDeaths", "m_iAssists", "m_iDamage")
DATASETS = (
    "players", "rounds", "round_economy", "kills", "damages", "bomb",
    "grenades", "smokes", "fires", "blinds", "stats",
)  # fmt: skip
ADR_TOLERANCE = 2.0


def match_complete(winner: int, loser: int) -> bool:
    """MR12 with MR3 overtime: 13 wins regulation; OT periods are first to 4 of 6."""
    if winner == 13 and loser <= 11:
        return True
    return winner >= 16 and loser >= 12 and (winner - 12) % 3 == 1 and winner - loser >= 2


def analyse(demo_path: Path, out_dir: Path) -> dict:
    import polars as pl
    import psutil
    from awpy import Demo

    proc = psutil.Process()
    timings: dict[str, float] = {}
    peak_mb: dict[str, int] = {}

    def checkpoint(stage: str, started: float) -> None:
        timings[stage] = round(time.perf_counter() - started, 1)
        peak_mb[stage] = round(proc.memory_info().peak_wset / 1e6)

    # ---------- production-like path: what the WU-2 adapter will read ----------
    t = time.perf_counter()
    demo = Demo(str(demo_path))
    header, tick_rate = demo.header, demo.tick_rate
    demo.load(*DATASETS)
    checkpoint("load_datasets", t)

    t = time.perf_counter()
    snaps = demo.snapshots(every=16)
    checkpoint("snapshots_every16", t)

    rounds = demo.rounds.sort("round_num")
    t = time.perf_counter()
    per_tick = demo.ticks(
        ["m_szLastPlaceName", "health", "team_num"] + [MATCH_STATS + f for f in COUNTER_FIELDS]
    ).rename({MATCH_STATS + f: f for f in COUNTER_FIELDS})
    checkpoint("per_tick_places_and_counters", t)

    # ---------- server counters (last observed value per player) ----------
    null_fields = [f for f in COUNTER_FIELDS if per_tick[f].null_count() == per_tick.height]
    final = (
        per_tick.filter(pl.col("steamid") != 0)
        .sort("tick")
        .group_by("steamid")
        .agg([pl.col(f).drop_nulls().last() for f in COUNTER_FIELDS])
    )
    live_start = rounds["start_tick"].drop_nulls().min()
    kills = demo.kills.filter(pl.col("tick") >= live_start)
    not_self = pl.col("attacker_steamid") != pl.col("victim_steamid")
    k_enemy = (
        kills.filter(not_self & (pl.col("attacker_side") != pl.col("victim_side")))
        .group_by("attacker_steamid")
        .len("k_events")
    )
    deaths = kills.group_by("victim_steamid").len("d_events")
    assists = (
        kills.drop_nulls("assister_steamid")
        .filter(pl.col("assister_side") != pl.col("victim_side"))
        .group_by("assister_steamid")
        .len("a_events")
    )
    cmp = final
    for frame, key in [
        (k_enemy, "attacker_steamid"), (deaths, "victim_steamid"), (assists, "assister_steamid")
    ]:  # fmt: skip
        cmp = cmp.join(frame.rename({key: "steamid"}), on="steamid", how="left")
    cmp = cmp.fill_null(0).join(
        demo.stats.select("steamid", "kills", "deaths", "assists", "adr", "rounds_played"),
        on="steamid",
        how="left",
    )
    adr_diff = (cmp["m_iDamage"] / cmp["rounds_played"] - cmp["adr"]).abs()
    kda = {
        "players_compared": cmp.height,
        "kills_events_eq_server": int((cmp["m_iKills"] == cmp["k_events"]).sum()),
        "deaths_events_eq_server": int((cmp["m_iDeaths"] == cmp["d_events"]).sum()),
        "assists_events_eq_server": int((cmp["m_iAssists"] == cmp["a_events"]).sum()),
        "awpy_stats_kda_eq_server": int(
            (
                (cmp["m_iKills"] == cmp["kills"])
                & (cmp["m_iDeaths"] == cmp["deaths"])
                & (cmp["m_iAssists"] == cmp["assists"])
            ).sum()
        ),
        "adr_awpy_vs_server_max_abs_diff": round(float(adr_diff.max()), 2),
        "adr_within_tolerance": int((adr_diff <= ADR_TOLERANCE).sum()),
    }

    # ---------- lineups: observe each player's side at every freeze end ----------
    sides = (
        per_tick.filter(
            pl.col("tick").is_in(rounds["freeze_end_tick"].drop_nulls().to_list())
            & (pl.col("steamid") != 0)
        )
        .join(rounds.select(pl.col("freeze_end_tick").alias("tick"), "round_num"), on="tick")
        .select("round_num", "steamid", "team_num")
    )
    lineup_a = set(sides.filter((pl.col("round_num") == 1) & (pl.col("team_num") == 2))["steamid"])
    side_of_a: dict[int, int] = {}
    lineup_mixed_rounds = 0
    for (rn,), grp in sides.group_by(["round_num"]):
        in_a = pl.col("steamid").is_in(list(lineup_a))
        a_sides = set(grp.filter(in_a)["team_num"])
        b_sides = set(grp.filter(~in_a)["team_num"]) - {1}
        if len(a_sides) != 1 or len(b_sides) > 1 or a_sides & b_sides:
            lineup_mixed_rounds += 1
        if a_sides:
            side_of_a[rn] = min(a_sides)
    swap_rounds = [rn for rn in sorted(side_of_a) if rn > 1 and side_of_a[rn] != side_of_a[rn - 1]]
    wins_a = sum(
        1 for r in rounds.iter_rows(named=True) if r["winner"] == side_of_a[r["round_num"]]
    )
    our_scores = sorted([wins_a, rounds.height - wins_a], reverse=True)

    # ---------- place names at checkpoints (alive players, 15/30/45 s) ----------
    checkpoints = [
        int(ft + s * tick_rate)
        for ft in rounds["freeze_end_tick"].drop_nulls().to_list()
        for s in (15, 30, 45)
    ]
    sampled = per_tick.filter(pl.col("tick").is_in(checkpoints) & (pl.col("health") > 0))
    place_counts = Counter(sampled["m_szLastPlaceName"].fill_null("<null>").to_list())

    # ---------- extract size on disk ----------
    extract_dir = out_dir / demo_path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)
    for name in DATASETS:
        getattr(demo, name).write_parquet(extract_dir / f"{name}.parquet")
    snaps.write_parquet(extract_dir / "snapshots.parquet")
    extract_bytes = sum(p.stat().st_size for p in extract_dir.glob("*.parquet"))

    # ---------- test-only oracle: team scores from CCSTeam entities ----------
    t = time.perf_counter()
    teams = (
        demo.ticks(["m_iScore", "m_iTeamNum"], players_only=False)
        .filter(pl.col("class_name") == "CCSTeam")
        .filter(pl.col("m_iTeamNum").is_in([2, 3]))
        .drop_nulls("m_iScore")
    )
    checkpoint("test_only_team_entities", t)

    def score_at(tick: int) -> list[int]:
        rows = teams.filter(pl.col("tick") <= tick).sort("tick").group_by("entity_id").last()
        return sorted(rows["m_iScore"].to_list(), reverse=True)

    server_final = score_at(int(teams["tick"].max()))
    r12 = (
        rounds.filter(pl.col("round_num") == 12).row(0, named=True) if rounds.height >= 12 else None
    )
    server_half = score_at(r12["official_end_tick"] or r12["end_tick"]) if r12 else None
    wins_a_half = sum(
        1
        for r in rounds.filter(pl.col("round_num") <= 12).iter_rows(named=True)
        if r["winner"] == side_of_a[r["round_num"]]
    )

    grenades = demo.grenades.unique(["entity_id", "entity_serial", "start_tick"])
    return {
        "file_mb": round(demo_path.stat().st_size / 1e6, 1),
        "map": header.get("map_name"),
        "tick_rate": tick_rate,
        "playback_minutes": round(float(header.get("playback_time") or 0) / 60, 1),
        "players_non_bot": demo.players.filter(pl.col("steamid") != 0).height,
        "team_names_present": int(demo.players["team_clan_name"].is_not_null().sum()),
        "rounds": rounds.height,
        "knife_rounds": int(rounds["is_knife_round"].sum()),
        "round_end_reasons": dict(Counter(rounds["reason_name"].to_list())),
        "scores": {
            "server_final": server_final,
            "ours_final": our_scores,
            "final_match": server_final == our_scores,
            "server_half": server_half,
            "ours_half": sorted([wins_a_half, 12 - wins_a_half], reverse=True) if r12 else None,
            "match_complete": match_complete(*server_final),
        },
        "lineups": {
            "lineup_a_size": len(lineup_a),
            "side_swap_rounds": swap_rounds,
            "mixed_rounds": lineup_mixed_rounds,
        },
        "counter_fields_all_null": null_fields,
        "kda_vs_server": kda,
        "events": {
            "kills": demo.kills.height,
            "kills_before_live": demo.kills.height - kills.height,
            "kills_no_attacker": int(demo.kills["attacker_steamid"].null_count()),
            "damages": demo.damages.height,
            "bomb_events": dict(Counter(demo.bomb["event"].to_list())),
            "plants_with_site": int(
                demo.bomb.filter(pl.col("event") == "finish_plant")["bombsite"].is_not_null().sum()
            ),
            "plants": int((demo.bomb["event"] == "finish_plant").sum()),
            "grenade_trajectories": dict(Counter(grenades["type"].to_list())),
            "grenade_thrower_unresolved": int(grenades["thrower_steamid"].null_count()),
            "smokes": demo.smokes.height,
            "fires": demo.fires.height,
            "blinds": demo.blinds.height,
            "buy_types": dict(Counter(demo.round_economy["buy_type"].to_list())),
        },
        "places": {
            "checkpoint_rows": sampled.height,
            "null_or_empty": place_counts.get("<null>", 0) + place_counts.get("", 0),
            "distinct": len(place_counts),
            "counts": dict(place_counts.most_common()),
        },
        "rows": {"snapshots_every16": snaps.height, "per_tick": per_tick.height},
        "extract_mb": round(extract_bytes / 1e6, 1),
        "timings_s": timings,
        "peak_memory_mb_after": peak_mb,
    }


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "--one":
        out_dir, demo_path = Path(argv[1]), Path(argv[2])
        started = time.perf_counter()
        result = analyse(demo_path, out_dir)
        result["total_s"] = round(time.perf_counter() - started, 1)
        print(json.dumps(result))
        return 0

    if len(argv) < 2:
        print(__doc__)
        return 2
    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {}
    for i, demo in enumerate(argv[1:], start=1):
        proc = subprocess.run(  # noqa: S603 - fixed argv, our own script
            [sys.executable, __file__, "--one", str(out_dir), demo],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        key = f"demo_{i}"
        if proc.returncode != 0:
            report[key] = {"error": proc.stderr.strip().splitlines()[-5:]}
        else:
            report[key] = json.loads(proc.stdout.strip().splitlines()[-1])
        print(f"{key}: done (exit {proc.returncode})", file=sys.stderr)
    (out_dir / "s1_results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
