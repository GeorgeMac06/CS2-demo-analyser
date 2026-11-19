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
        write_demo(src / f"m{i}.dem", scouted_match(opp, f"rs{i}"))
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
        assert [line[:5] for line in lines[1:4]] == ["1:40 ", "1:25 ", "1:10 "]
        assert sorted(line.split(":")[0] for line in lines if line.startswith("route ")) == [
            f"route a{i}" for i in range(1, 6)]  # fmt: skip
        assert any(line.startswith("utility: ") for line in lines)
        hit = [line for line in lines if line.startswith(("hit ", "no clear hit"))]
        assert len(hit) == (1 if r["side"] == "T" else 0)
        assert any(line.startswith("kills: ") for line in lines)
        assert any(line.startswith(("opening kill: ", "opening death: ")) for line in lines)
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
