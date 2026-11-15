"""T-02 (team resolution through the API) and T-03 (buy classification boundaries)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.rounds import classify_buy, is_complete
from support.api import Api, finding
from support.synth import lineup, side_of_a, simple_match, steamid, write_demo

_BASE_TIME = 1_760_000_000  # 2025-10-09; each written demo is one day later than the last


def _write(folder: Path, name: str, scenario: dict) -> Path:
    """Write a synthetic demo with an explicit, increasing file time (the match-date proxy)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = write_demo(folder / f"{name}.dem", scenario)
    stamp = _BASE_TIME + 86400 * len(list(folder.glob("*.dem")))
    os.utime(path, (stamp, stamp))
    return path


def ids(keys: list[str]) -> set[str]:
    return {str(steamid(k)) for k in keys}


def test_core_standin_and_nickname(api: Api, tmp_path: Path) -> None:
    team = lineup("a")
    sub = [*team[:4], "sub1"]  # a5 missing once: a stand-in plays
    for i, (players, opp) in enumerate([(team, "b"), (team, "c"), (sub, "d")]):
        scenario = simple_match(players, lineup(opp), score=(13, 4 + i), server=f"s{i}")
        scenario["names"] = {"a1": "Ace" if i < 2 else "Ace-"}  # renamed in the latest demo
        scenario["clan"] = {"A": "Dragons", "B": f"Opp{i}"}
        _write(tmp_path / "in", f"m{i}", scenario)

    job = api.run_import([tmp_path / "in"])
    proposal = job["result"]["roster_proposal"]
    roles = {p["steamid"]: p["role"] for p in proposal["players"]}

    assert proposal["needs_pick"] is False
    assert proposal["team_name"] == "Dragons"
    assert {s for s, r in roles.items() if r == "core"} == ids(team)
    assert {s for s, r in roles.items() if r == "standin"} == ids(["sub1"])
    nick = next(p["nick"] for p in proposal["players"] if p["steamid"] == str(steamid("a1")))
    assert nick == "Ace-"


def test_team_found_on_either_lineup_and_sides_follow_swaps(api: Api, tmp_path: Path) -> None:
    team = lineup("a")
    # The scouted team starts CT in one demo, i.e. it is lineup B there; one goes to overtime.
    s1 = simple_match(lineup("b"), team, score=(13, 9), server="x1")  # team loses as lineup B
    s2 = simple_match(team, lineup("c"), score=(16, 14), server="x2")
    s3 = simple_match(team, lineup("d"), score=(13, 2), server="x3")
    for i, s in enumerate((s1, s2, s3)):
        _write(tmp_path / "in", f"m{i}", s)

    job = api.run_import([tmp_path / "in"])
    entry_id = api.confirm(job)
    snap = api.findings(entry_id)

    assert [d["scouted"] for d in snap["demos"]].count("B") == 1
    ot = next(d for d in snap["demos"] if d["rounds"] == 30)
    assert (ot["score"], ot["complete"]) == ("16-14", True)
    sides = {
        r["round_num"]: r["side"] for r in snap["round_index"] if r["demo_label"] == ot["label"]
    }
    assert sides == {rn: side_of_a(rn) for rn in range(1, 31)}  # 13 swap, none at 25, swap at 28
    lost = next(d for d in snap["demos"] if d["scouted"] == "B")
    assert lost["score"] == "9-13"


def test_demo_without_three_core_players_is_flagged(api: Api, tmp_path: Path) -> None:
    team = lineup("a")
    mostly_subs = [team[0], team[1], "x1", "x2", "x3"]
    for i, players in enumerate([team, team, team, mostly_subs]):
        _write(tmp_path / "in", f"m{i}", simple_match(players, lineup(f"o{i}"), server=f"t{i}"))

    entry_id = api.confirm(api.run_import([tmp_path / "in"]))
    demos = api.findings(entry_id)["demos"]

    flagged = [d for d in demos if not d["used"]]
    assert len(flagged) == 1 and flagged[0]["code"] == "TEAM_NOT_FOUND"
    assert all(d["used"] for d in demos if d is not flagged[0])


def test_one_demo_needs_a_pick_and_override_assigns_lineup(api: Api, tmp_path: Path) -> None:
    path = _write(tmp_path / "in", "only", simple_match(lineup("a"), lineup("b"), score=(13, 6)))
    job = api.run_import([path])
    assert job["result"]["roster_proposal"]["needs_pick"] is True

    sha = job["result"]["accepted"][0]
    entry_id = api.confirm(job, core=sorted(ids(lineup("b"))), lineup_overrides={sha: "B"})
    snap = api.findings(entry_id)

    assert snap["demos"][0]["scouted"] == "B"
    assert snap["demos"][0]["score"] == "6-13"
    assert finding(snap, "team.winrate.T.all")["support"]["n"] + finding(
        snap, "team.winrate.CT.all")["support"]["n"] == 19  # fmt: skip


@pytest.mark.parametrize(
    ("round_num", "value", "expected"),
    [
        (1, 30000, "pistol"), (13, 0, "pistol"), (25, 4000, "eco"),  # OT start is not a pistol
        (2, 4999, "eco"), (2, 5000, "force"), (2, 19999, "force"), (2, 20000, "full"),
        (2, None, "eco"),
    ],
)  # fmt: skip
def test_buy_class_boundaries(round_num: int, value: int | None, expected: str) -> None:
    assert classify_buy(round_num, value, AnalysisConfig()) == expected


def test_buy_thresholds_follow_config() -> None:
    cfg = AnalysisConfig(eco_max=8000, force_max=15000)
    assert [classify_buy(5, v, cfg) for v in (7999, 8000, 15000)] == ["eco", "force", "full"]


@pytest.mark.parametrize(
    ("winner", "loser", "complete"),
    [(13, 11, True), (13, 12, False), (9, 3, False), (16, 14, True), (16, 13, True),
     (15, 15, False), (19, 17, True), (17, 15, False)],
)  # fmt: skip
def test_complete_match_rule(winner: int, loser: int, complete: bool) -> None:
    assert is_complete(winner, loser) is complete
