"""Round stories and the round timer (owner feedback 2026-11-16)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cs2scout.core.patterns import clock
from cs2scout.core.round_story import away_from_hit, route_text
from cs2scout.core.zones import PlaceNameZones
from cs2scout.web.figures import tempo_figure
from support.api import Api
from support.scenarios import scouted_match
from support.synth import write_demo


@pytest.fixture
def entry(api: Api, tmp_path: Path) -> int:
    src = tmp_path / "in"
    src.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        match = scouted_match(opp, f"rs{i}")
        # r12: an opponent hits a2 from CT spawn, and both live. r20: a1 hits first, then
        # dies to the same player at 1:15.
        match["rounds"][11]["damages"] = [{"t": 12, "attacker": f"{opp}1", "victim": "a2",
                                           "dmg": 30, "weapon": "awp"}]  # fmt: skip
        match["rounds"][19]["damages"] = [{"t": 38, "attacker": "a1", "victim": f"{opp}1",
                                           "dmg": 40}]  # fmt: skip
        write_demo(src / f"m{i}.dem", match)
    return api.confirm(api.run_import([src]), team_name="Scouted")


def stories(api: Api, entry: int) -> dict[str, str]:
    vdir = api.library.current_version_dir(entry)
    return {s["ref"]: s["text"] for s in json.loads((vdir / "stories.json").read_text("utf-8"))}


def test_clock_is_the_in_game_round_timer() -> None:
    assert clock(0) == "1:55" and clock(20) == "1:35" and clock(60) == "0:55"
    assert clock(115) == "0:00" and clock(130) == "0:00" and clock(None) == "?"
    axis = tempo_figure([20.0, 33.0])["layout"]["xaxis"]
    assert axis["autorange"] == "reversed" and axis["ticktext"][0] == "1:55"


def test_every_round_has_a_story_a_coach_can_read(api: Api, entry: int) -> None:
    told = stories(api, entry)
    rounds = api.findings(entry)["round_index"]
    assert set(told) == {r["ref"] for r in rounds}
    for r in rounds:
        lines = told[r["ref"]].splitlines()
        result = "WON" if r["won"] else "lost"
        header = (f"{r['ref']} · {r['side']} · {r['buy']} vs {r['opp_buy']} · "
                  f"score {r['score_us']}-{r['score_them']} · {result} (")  # fmt: skip
        assert lines[0].startswith(header)
        assert lines[1].startswith("label: ") and len(lines[1]) > len("label: ")
        assert [line[:5] for line in lines[2:5]] == ["1:40 ", "1:25 ", "1:10 "]
        assert sorted(line.split(":")[0] for line in lines if line.startswith("route ")) == [
            f"route a{i}" for i in range(1, 6)]  # fmt: skip
        assert any(line.startswith("utility: ") for line in lines)
        hit = [line for line in lines if line.startswith(("hit ", "no clear hit"))]
        assert len(hit) == (1 if r["side"] == "T" else 0)
        assert any(line.startswith("kills: ") for line in lines)
        assert any(line.startswith(("opening kill: ", "opening death: ")) for line in lines)
        assert sum(line.startswith("first damage: ") for line in lines) == 1
        if r["planted"]:
            plant = "plant " if r["side"] == "T" else "opponents planted "
            assert any(line.startswith(plant) and "; at plant " in line for line in lines)
    pistols = [told[r["ref"]] for r in rounds if r["round_num"] in (1, 13)]
    assert pistols and all(" · pistol vs pistol · " in p.splitlines()[0] for p in pistols)
    # Nicknames from the roster, never account numbers.
    assert "a1" in "\n".join(told.values()) and "7656119" not in json.dumps(told)


def test_a_story_follows_each_player_to_the_hit_and_lists_every_kill(api: Api, entry: int) -> None:
    demo = api.findings(entry)["round_index"][0]["ref"].split(":")[0]
    told = {ref.split(":")[1]: text.splitlines()
            for ref, text in stories(api, entry).items() if ref.startswith(demo)}  # fmt: skip
    # r2: the B execute. Routes stop at the plant; nobody is away from a B hit from underpass.
    assert "route a1: Apartments 1:45 → BombsiteB 1:39" in told["r2"]
    assert "route a4: Underpass 1:45" in told["r2"]
    assert "hit B 1:39; at the hit BombsiteB: a1, a2, a3 · Underpass: a4, a5" in told["r2"]
    # r12: everyone mid and no hit; a3 dies there at 1:15, killed from CT spawn.
    assert "no clear hit" in told["r12"]
    assert "route a3: TopofMid 1:45 (dead 1:15)" in told["r12"]
    assert "kills: 1:15 opp (CTSpawn) > a3 (TopofMid) ak47" in told["r12"]
    # r22 (CT): a3's early pick on A, then the late kill; no hit line on CT rounds.
    kills = next(line for line in told["r22"] if line.startswith("kills: "))
    assert kills.startswith("kills: 1:45 a3 (BombsiteA) > opp (TSpawn) ak47; 1:15 ")


def test_each_round_has_a_label_from_the_same_reads_as_the_patterns(api: Api, entry: int) -> None:
    demo = api.findings(entry)["round_index"][0]["ref"].split(":")[0]
    told = {ref.split(":")[1]: text.splitlines()
            for ref, text in stories(api, entry).items() if ref.startswith(demo)}  # fmt: skip
    label = {r: next(line.removeprefix("label: ") for line in lines if line.startswith("label: "))
             for r, lines in told.items()}  # fmt: skip
    assert label["r1"] == label["r2"] == "B rush 1:39"  # on B at 0:16, before 1:35
    assert label["r7"] == "A hit 1:05"  # a default-time hit with no utility
    assert label["r10"] == "Fake B, late A 0:45"  # all five B side at 1:25, then A
    assert label["r12"] == "Mid default, no clear hit"
    assert label["r13"] == "2 A · 1 mid · 2 B; B hit 1:30, retake"
    assert label["r19"] == "2 A · 1 mid · 2 B; B hit 1:30, saved"
    assert label["r22"] == "A stack"
    # The rounds drawer shows it next to each round.
    refs = [f"{demo}:r10", f"{demo}:r19"]
    rows = api.get(f"/api/entries/{entry}/rounds", params={"refs": refs}).json()
    assert [r["label"] for r in rows] == [label["r10"], label["r19"]]
    drawer = api.get(f"/ui/entries/{entry}/rounds", params={"refs": refs}).text
    assert '<span class="round-label">Fake B, late A 0:45</span> · Story' in drawer


def test_a_story_reads_the_first_fight_the_ct_side_and_after_the_plant(api: Api, entry: int):
    demo = api.findings(entry)["round_index"][0]["ref"].split(":")[0]
    told = {ref.split(":")[1]: text.splitlines()
            for ref, text in stories(api, entry).items() if ref.startswith(demo)}  # fmt: skip
    # First damage, and who won that fight: a hit nobody dies from, an opening pick, a
    # player who hits first but loses the fight, and the round's only kill.
    assert "first damage: 1:43 opp (CTSpawn) > a2 (TopofMid) awp for 30; both lived" in told["r12"]
    assert ("first damage: 1:45 a3 (BombsiteA) > opp (TSpawn) ak47 for 100; a3 won the fight"
            in told["r22"])  # fmt: skip
    assert "first damage: 1:17 a1 (BombsiteA) > opp (TSpawn) ak47 for 40; opp won the fight" in (
        told["r20"])  # fmt: skip
    assert ("first damage: 1:15 opp (CTSpawn) > a2 (Apartments) ak47 for 100; opp won the fight"
            in told["r11"])  # fmt: skip
    # CT: who rotated to the hit site and when, then a retake or a save after the plant.
    assert ("CT: B hit 1:30; a1 rotated in 7 s; a2, a3 did not get there; after the plant: "
            "retake") in told["r13"]  # fmt: skip
    assert "CT: A hit 1:30; a3, a4, a5 did not get there; after the plant: retake" in told["r17"]
    assert "CT: B hit 1:30; a1, a2, a3 did not get there; after the plant: saved" in told["r19"]
    assert not any(line.startswith("CT: ") for line in told["r22"])  # no hit, no plant
    # After the plant: where the Ts are, as the ts.postplant pattern reads it.
    assert "after planting B (plant+10s): 3 B site · 2 underpass" in told["r2"]
    assert "after planting A (plant+10s): 3 A site · 1 A ramp · 1 connector" in told["r7"]
    assert not any(line.startswith("after planting") for line in told["r12"])
    titles = [f["title"] for f in api.findings(entry)["findings"]]
    assert "After planting B: 3 B site · 2 underpass" in titles


def test_a_route_skips_places_a_player_only_brushed_past() -> None:
    entered = [("TSpawn", 0.0), ("SideAlley", 2.0), ("TopofMid", 7.0), ("Middle", 9.0),
               ("TopofMid", 9.5), ("Catwalk", 20.0)]  # fmt: skip
    route = route_text(entered, died_s=30.0)
    assert route == "SideAlley 1:53 → TopofMid 1:48 → Catwalk 1:35 (dead 1:25)"
    assert route_text([("CTSpawn", 0.0)]) == "CTSpawn"
    long = [(f"P{i}", float(i * 5)) for i in range(12)]
    assert route_text(long).endswith("P6 1:25 → … → P11 1:00")


def test_the_player_away_from_the_hit_is_the_lurker_not_the_one_coming_from_mid() -> None:
    def at(sid, place, x, alive=True):
        return {"steamid": sid, "place": place, "x": x, "y": 0.0, "alive": alive}

    rows = [at(1, "BombsiteB", 0.0), at(2, "BombsiteB", 100.0), at(3, "Underpass", -600.0),
            at(4, "PalaceInterior", 2500.0), at(5, "Middle", 800.0),
            at(6, "PalaceAlley", 2600.0, alive=False)]  # fmt: skip
    assert away_from_hit(rows, "B", "de_mirage", PlaceNameZones()) == [4]
    assert away_from_hit(rows[3:], "B", "de_mirage", PlaceNameZones()) == []


def test_pattern_titles_use_the_round_timer(api: Api, entry: int) -> None:
    titles = [f["title"] for f in api.findings(entry)["findings"]]
    assert any(t.startswith("Setup at 1:35: ") for t in titles)
    assert any(t.startswith("At 1:25: ") for t in titles)
    assert not any(" 0:20" in t or "0:30:" in t for t in titles)


def test_an_analysis_from_before_stories_offers_an_update(api: Api, entry: int) -> None:
    vdir = api.library.current_version_dir(entry)
    snapshot = json.loads((vdir / "findings.json").read_text("utf-8"))
    (vdir / "findings.json").write_text(json.dumps(snapshot | {"schema_version": 1}), "utf-8")
    assert "built by an older version of the app" in api.get(f"/entries/{entry}").text
    job = api.wait(api.post(f"/api/entries/{entry}/recompute").json()["job_id"])
    assert job["state"] == "done"
    assert "built by an older version of the app" not in api.get(f"/entries/{entry}").text
