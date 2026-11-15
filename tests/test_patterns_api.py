"""T-10: patterns reflect what the team really does (known-answer synthetic matches).

Three demos of the team in ``support.scenarios``; every expected number follows from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from support.api import Api, make_api
from support.scenarios import scouted_match
from support.synth import write_demo


@pytest.fixture(scope="module")
def mined(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("patterns")
    src = root / "in"
    src.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        write_demo(src / f"m{i}.dem", scouted_match(opp, f"pat{i}"))
    client, settings = make_api(root / "workspace")
    with client:
        api = Api(client, settings)
        entry_id = api.confirm(api.run_import([src]))
        yield api, entry_id


def _of(snapshot: dict, kind: str, **params) -> list[dict]:
    return [f for f in snapshot["findings"] if f["kind"] == kind
            and all(f["params"].get(k) == v for k, v in params.items())]  # fmt: skip


def test_t_strategies_found_with_exact_support(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    b_rush = _of(snap, "ts.strategy", site="B", tempo="rush")
    a_default = _of(snap, "ts.strategy", site="A", tempo="default")
    assert len(b_rush) == 1 and b_rush[0]["support"] == {"k": 18, "n": 36, "demos": 3}
    assert b_rush[0]["params"]["utility_median"]["smokes"] == 1  # the a2 smoke, most rounds
    assert len(a_default) == 1 and a_default[0]["support"]["k"] == 9
    for f in b_rush + a_default:
        assert "below_support" not in f["flags"]


def test_fake_unresolved_and_buy_rounds(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    fake = _of(snap, "ts.fake", shown="B", site="A")
    assert len(fake) == 1 and fake[0]["support"]["k"] == 6  # 6/36 = 17%: passes support
    assert "below_support" not in fake[0]["flags"]
    unresolved = _of(snap, "ts.site", site=None)
    assert unresolved[0]["support"]["k"] == 3 and "below_support" in unresolved[0]["flags"]
    pistol = _of(snap, "ts.buy", buy="pistol", site="B", tempo="rush")
    assert pistol[0]["support"] == {"k": 3, "n": 3, "demos": 3}
    post_b = _of(snap, "ts.postplant", site="B")
    assert post_b and post_b[0]["eligible"] == {"side": "T", "planted": True}


def test_t_patterns_recount_under_filters(mined) -> None:
    api, entry = mined
    assert not [f for f in api.findings(entry, side="CT")["findings"]
                if f["kind"].startswith("ts.")]  # fmt: skip
    full_only = api.findings(entry, buy=["full"])
    b_rush = _of(full_only, "ts.strategy", site="B", tempo="rush")
    assert b_rush[0]["support"]["k"] == 15  # pistol rounds filtered out
    one_demo = api.findings(entry, demos=[full_only["round_index"][0]["demo_label"]])
    assert _of(one_demo, "ts.strategy", site="B", tempo="rush")[0]["support"]["k"] == 6


def test_patterns_are_saved_with_the_version(mined) -> None:
    api, entry = mined
    vdir: Path = api.library.current_version_dir(entry)
    assert (vdir / "patterns.json").exists()


def _player(snapshot: dict, key_of: str) -> str:
    """Player key of synthetic player ``a1``..``a5`` (nick == key in the scenario)."""
    return next(m["player_key"] for m in snapshot["roster"] if m["nick"] == key_of)


def test_ct_setups_and_positions(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    setups = {tuple(sorted(f["params"]["groups"].items())): f["support"]
              for f in snap["findings"] if f["kind"] == "ct.setup"}  # fmt: skip
    assert setups[(("A", 2), ("B", 2), ("mid", 1))] == {"k": 27, "n": 36, "demos": 3}
    assert setups[(("A", 3), ("B", 1), ("mid", 1))]["k"] == 9
    a3 = _of(snap, "ct.position")
    a3 = next(f for f in a3 if f["subject"] == _player(snap, "a3"))
    assert a3["params"]["main"] == "Connector" and a3["support"]["k"] == 27


def test_ct_rotation_aggression_retake_save(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    a1 = _player(snap, "a1")
    rotation = next(f for f in _of(snap, "ct.rotation") if f["subject"] == a1)
    assert rotation["params"] == {"considered": 15, "rotated": 12, "median_s": 7.0}
    early = next(f for f in _of(snap, "ct.aggression") if f["subject"] == _player(snap, "a3"))
    assert early["params"]["won"] == 9 and early["params"]["places"][0]["place"] == "BombsiteA"
    retake = _of(snap, "ct.retake")[0]
    assert retake["support"]["k"] == 18 and retake["params"]["won"] == 12
    assert retake["support"]["n"] == 21  # CT rounds with an enemy plant
    save = _of(snap, "ct.save")[0]
    assert save["support"]["k"] == 3 and "below_support" not in save["flags"]  # 3/21, 3 demos


def test_smoke_lineup_found(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    smokes = [f for f in _of(snap, "util.lineup", type="smoke", side="T")
              if f["support"]["k"] >= 10]  # fmt: skip
    assert len(smokes) == 1
    lineup = smokes[0]
    assert lineup["support"] == {"k": 15, "n": 36, "demos": 3}  # r2-r6 in each demo
    assert lineup["params"]["throw_place"] == "Apartments"
    assert lineup["params"]["throwers"] == [{"player": _player(snap, "a2"), "throws": 15}]
    assert lineup["params"]["median_s"] == 12.0


def test_habits_weapons_and_roles(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    a3, a4 = _player(snap, "a3"), _player(snap, "a4")
    opening = [f for f in _of(snap, "plr.habit", habit="opening_kill", side="CT")
               if f["subject"] == a3]  # fmt: skip
    assert opening and opening[0]["params"]["place"] == "BombsiteA"
    assert opening[0]["support"]["k"] == 9
    awp = [f for f in _of(snap, "plr.weapon", weapon="awp") if f["subject"] == a4]
    assert awp and all(f["params"]["weapon"] == "awp" for f in awp)
    roles = {f["subject"]: f for f in _of(snap, "plr.role")}
    assert "AWPer" in roles[a4]["params"]["roles"]
    assert len(roles) == 5 and all("metrics" in f["params"] for f in roles.values())


def test_ct_stacks_and_single_demo_coincidences(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    stacks = {f["params"]["stack"]: f["support"]["k"] for f in _of(snap, "ct.stack")}
    assert stacks == {"standard": 27, "A stack": 9}
    # The same B rush seen in one demo only: enough rounds, but not "a pattern" (2+ demos).
    one = api.findings(entry, demos=[snap["round_index"][0]["demo_label"]])
    b_rush = _of(one, "ts.strategy", site="B", tempo="rush")[0]
    assert b_rush["support"]["k"] == 6 and "below_support" in b_rush["flags"]
