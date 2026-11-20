"""Economy reads (issue #6): force, save or full buy, with known answers.

Three demos of ``support.scenarios.economy_match``; every expected number follows from it.
"""

from __future__ import annotations

import json

import pytest

from cs2scout.ai.payload import build
from cs2scout.core.economy import buy_type_of, half_start, money_band
from support.api import Api, make_api
from support.scenarios import economy_match
from support.synth import write_demo


@pytest.fixture(scope="module")
def eco(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("economy")
    src = root / "in"
    src.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        write_demo(src / f"m{i}.dem", economy_match(opp, f"eco{i}"))
    client, settings = make_api(root / "workspace")
    with client:
        api = Api(client, settings)
        yield api, api.confirm(api.run_import([src]))


def one(snapshot: dict, kind: str, title: str) -> dict:
    found = [f for f in snapshot["findings"] if f["kind"] == kind and f["title"] == title]
    assert len(found) == 1, (kind, title, sorted(f["title"] for f in snapshot["findings"]
                                                 if f["kind"] == kind))  # fmt: skip
    return found[0]


def test_buy_type_rules() -> None:
    assert buy_type_of("pistol", 4000, 0) is None
    assert buy_type_of("full", None, 0) == "full"  # kept rifles: no need to see the cash
    assert buy_type_of("eco", 8000, 7500) == "save" and buy_type_of("force", 15000, 1000) == "force"
    assert buy_type_of("force", 10000, 5000) == "save"  # kept half: a save with armor
    assert buy_type_of("eco", None, 0) is None  # cash before buying not seen: no guess
    assert [n for n in range(1, 35) if half_start(n)] == [1, 13, 25, 28, 31, 34]
    assert money_band(1999) == "Under $2,000 a player" and money_band(5000) == "$5,000+ a player"


def test_each_round_gets_its_buy_type_and_money(eco) -> None:
    api, entry = eco
    index = api.findings(entry)["round_index"]
    rounds = {r["round_num"]: r for r in index if r["demo_label"] == index[0]["demo_label"]}
    buy_types = {n: r["buy_type"] for n, r in rounds.items()}
    assert buy_types[1] is None and buy_types[13] is None  # pistols are not a buy_type
    assert [n for n, c in buy_types.items() if c == "save"] == [2, 7, 19, 22]
    assert [n for n, c in buy_types.items() if c == "force"] == [6, 12, 14, 20]
    assert rounds[6]["money_pp"] == 3200  # $3,000 cash + $200 kept gear a player


def test_after_the_pistol(eco) -> None:
    api, entry = eco
    snap = api.findings(entry)
    lost = one(snap, "eco.pistol", "2nd round, pistol lost: save")
    assert lost["support"] == {"k": 3, "n": 3, "demos": 3} and "below_support" not in lost["flags"]
    won = one(snap, "eco.pistol", "2nd round, pistol won: force buy")
    assert won["support"]["k"] == 3 and won["outcome"]["win_pct"] == 100.0
    third = one(snap, "eco.pistol", "3rd round, pistol lost, 2nd round lost: full buy")
    assert third["support"] == {"k": 3, "n": 3, "demos": 3}


def test_force_or_save_by_situation(eco) -> None:
    api, entry = eco
    snap = api.findings(entry)
    # Lost full buys in r5, r18, r21 and r23: they force r6, save r19 and r22, full-buy r24.
    force = one(snap, "eco.situation", "After losing a full buy: force buy")
    save = one(snap, "eco.situation", "After losing a full buy: save")
    assert (force["support"]["k"], save["support"]["k"], force["support"]["n"]) == (3, 6, 12)
    last = one(snap, "eco.situation", "Last round of a half: force buy")
    assert last["support"] == {"k": 3, "n": 6, "demos": 3}
    band = one(snap, "eco.situation", "$2,000–3,499 a player: force buy")
    assert band["support"]["k"] == 9  # r6, r12 and r20


def test_saved_guns_and_force_buy_guns(eco) -> None:
    api, entry = eco
    snap = api.findings(entry)
    exit_ct = one(snap, "eco.exit", "Saves guns in a lost CT round")
    assert exit_ct["support"] == {"k": 3, "n": 12, "demos": 3}  # r18 of r18, r20, r21, r23
    assert exit_ct["params"]["guns"] == {"AWP": 3, "AK-47": 3}
    assert {p["rounds"] for p in exit_ct["params"]["players"]} == {3}
    assert not [
        f for f in snap["findings"] if f["kind"] == "eco.exit" and f["params"]["side"] == "T"
    ]
    galil = one(snap, "eco.guns", "T force buy: Galil AR (×2 when bought)")
    assert galil["support"] == {"k": 6, "n": 6, "demos": 3}
    deagle = one(snap, "eco.guns", "T force buy: Desert Eagle (×1 when bought)")
    assert deagle["support"]["k"] == 3
    assert one(snap, "eco.guns", "CT force buy: MP9 (×3 when bought)")["support"]["k"] == 3
    assert one(snap, "eco.play", "CT force buy: standard")["support"]["n"] == 6


def test_a_filter_recounts_economy_reads(eco) -> None:
    api, entry = eco
    t_only = api.findings(entry, side="T")
    titles = {f["title"] for f in t_only["findings"] if f["kind"].startswith("eco.")}
    assert "2nd round, pistol won: force buy" not in titles  # a CT round
    force = one(t_only, "eco.situation", "After losing a full buy: force buy")
    assert force["support"] == {"k": 3, "n": 3, "demos": 3}  # only r6 is on T


def test_story_tab_export_and_brief_show_the_economy(eco) -> None:
    api, entry = eco
    vdir = api.library.current_version_dir(entry)
    told = {s["ref"]: s["text"] for s in json.loads((vdir / "stories.json").read_text("utf-8"))}
    r6 = next(text for ref, text in told.items() if ref.endswith(":r6"))
    assert r6.splitlines()[0].endswith(" · force buy, $3,200 a player")
    r3 = next(text for ref, text in told.items() if ref.endswith(":r3"))
    assert "a player" not in r3.splitlines()[0]  # full buys need no money note

    tab = api.client.get(f"/ui/entries/{entry}/tab/economy").text
    assert "After the pistol" in tab and "2nd round, pistol lost: save" in tab
    assert "AWP (3)" in tab and "a4 (3)" in tab
    assert api.client.get(f"/entries/{entry}?tab=economy").status_code == 200

    html = api.post(f"/api/entries/{entry}/export", {"sections": ["economy"]}).text
    assert "After the pistol" in html and "2nd round, pistol lost: save" in html

    snap = api.findings(entry)
    payload = build(snap, {"team": "Scouted", "map": "de_mirage"}, {}, [])
    assert any(f["kind"] == "eco.pistol" for f in payload["findings"])
