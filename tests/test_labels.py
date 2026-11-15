"""T-11: user labels survive updates and never jump to the wrong pattern or player."""

from __future__ import annotations

from pathlib import Path

import pytest

from cs2scout.core.labels import carry_over
from support.api import Api
from support.scenarios import TEAM, scouted_match
from support.synth import steamid, write_demo


def _p(kind: str, key: str, refs: list[str], subject: str = "team") -> dict:
    return {"kind": kind, "stable_key": key, "subject": subject, "all_refs": refs}


def test_carry_over_rules() -> None:
    old = [_p("ts.strategy", "k1", ["a", "b", "c", "d"]), _p("ts.strategy", "k2", ["x", "y"])]
    new = [_p("ts.strategy", "n1", ["a", "b", "c", "e"]), _p("ts.strategy", "n2", ["q"])]
    labels = {("ts.strategy", "k1"): "B apps fast", ("ts.strategy", "k2"): "gone"}
    # k1 -> n1: 3 shared of 5 rounds (0.6 >= 0.5). k2 overlaps nothing: stays an orphan.
    assert carry_over(labels, old, new) == {("ts.strategy", "k1"): "n1"}

    unchanged = [_p("ts.strategy", "k1", ["a"])]
    assert carry_over({("ts.strategy", "k1"): "x"}, old, unchanged) == {}  # same key: no move

    other_kind = [_p("ct.setup", "n1", ["a", "b", "c", "d"])]
    assert carry_over(labels, old, other_kind) == {}  # never across kinds

    taken = {("ts.strategy", "k1"): "mine", ("ts.strategy", "n1"): "already named"}
    assert carry_over(taken, old, new) == {}  # never overwrite another label

    other_player = [_p("ct.position", "n9", ["a", "b"], subject="p2")]
    old_player = [_p("ct.position", "k9", ["a", "b"], subject="p1")]
    assert carry_over({("ct.position", "k9"): "x"}, old_player, other_player) == {}


@pytest.fixture
def entry(api: Api, tmp_path: Path) -> int:
    src = tmp_path / "in"
    src.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        write_demo(src / f"m{i}.dem", scouted_match(opp, f"lab{i}"))
    return api.confirm(api.run_import([src]))


def _find(snapshot: dict, kind: str, **params) -> dict | None:
    return next((f for f in snapshot["findings"] if f["kind"] == kind
                 and all(f["params"].get(k) == v for k, v in params.items())), None)  # fmt: skip


def test_label_shows_and_survives_adding_demos(api: Api, entry: int, tmp_path: Path) -> None:
    b_rush = _find(api.findings(entry), "ts.strategy", site="B", tempo="rush")
    response = api.put(f"/api/entries/{entry}/labels/{b_rush['id']}", {"label": "B apps fast"})
    assert response.json() == {"id": b_rush["id"], "label": "B apps fast"}
    assert (
        _find(api.findings(entry), "ts.strategy", site="B", tempo="rush")["label"] == "B apps fast"
    )

    more = write_demo(tmp_path / "m9.dem", scouted_match("e", "lab9"))
    job = api.wait(api.post(f"/api/entries/{entry}/demos", {"paths": [str(more)]}).json()["job_id"])
    assert job["state"] == "done"
    after = _find(api.findings(entry), "ts.strategy", site="B", tempo="rush")
    assert after["support"]["k"] == 24 and after["label"] == "B apps fast"


def test_player_label_hidden_while_player_left_and_back_after(api: Api, entry: int) -> None:
    snap = api.findings(entry)
    a5 = next(m["player_key"] for m in snap["roster"] if m["nick"] == TEAM[4])
    role = next(f for f in snap["findings"] if f["kind"] == "plr.role" and f["subject"] == a5)
    api.put(f"/api/entries/{entry}/labels/{role['id']}", {"label": "IGL"})

    roster = {"core": [str(steamid(k)) for k in TEAM[:4]], "excluded": [str(steamid(TEAM[4]))]}
    api.wait(api.put(f"/api/entries/{entry}/roster", roster).json()["job_id"])
    assert not any(f.get("label") == "IGL" for f in api.findings(entry)["findings"])

    api.wait(api.put(f"/api/entries/{entry}/roster",
                     {"core": [str(steamid(k)) for k in TEAM]}).json()["job_id"])  # fmt: skip
    back = next(f for f in api.findings(entry)["findings"]
                if f["kind"] == "plr.role" and f["subject"] == a5)  # fmt: skip
    assert back["label"] == "IGL"


def test_clearing_and_unknown_labels(api: Api, entry: int) -> None:
    f = _find(api.findings(entry), "ts.site", site="A")
    api.put(f"/api/entries/{entry}/labels/{f['id']}", {"label": "x"})
    api.put(f"/api/entries/{entry}/labels/{f['id']}", {"label": "  "})
    assert "label" not in _find(api.findings(entry), "ts.site", site="A")
    assert api.put(f"/api/entries/{entry}/labels/ts.nope.team.x", {"label": "y"}).status_code == 404
