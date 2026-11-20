"""T-05 (recount + filters), T-09 (determinism), J2 flow and entry lifecycle, via the API."""

from __future__ import annotations

import json
import os
from pathlib import Path

import polars as pl
import pytest

from support.api import Api, finding, make_api
from support.synth import lineup, simple_match, steamid, write_demo

TEAM = lineup("a")


def rich_match(opp: str, server: str, score=(13, 9), calls: Path | None = None) -> dict:
    """Varied buys, kills with assists and trades, utility, a plant, so filters bite."""
    s = simple_match(TEAM, lineup(opp), score=score, server=server)
    for n, rnd in enumerate(s["rounds"], start=1):
        if n in (2, 14):
            rnd["equipment"] = {"A": 3000, "B": 21000}  # our eco vs their full
        elif n in (3, 15):
            rnd["equipment"] = {"A": 12000, "B": 4000}  # our force vs their eco
        rnd["kills"].append({"t": 50, "attacker": TEAM[(n + 1) % 5], "victim": lineup(opp)[n % 5],
                             "assister": TEAM[(n + 2) % 5], "flash_assist": n % 4 == 0,
                             "headshot": n % 2 == 0})  # fmt: skip
        rnd["grenades"] = [
            {"t": 8, "thrower": TEAM[n % 5], "type": "smoke", "land": [100.0, 200.0]},
            {"t": 9, "thrower": TEAM[(n + 3) % 5], "type": "flashbang", "land": [120.0, 210.0]},
        ]
        rnd["blinds"] = [{"t": 10, "attacker": TEAM[(n + 3) % 5], "victim": lineup(opp)[0],
                          "duration": 2.5}]  # fmt: skip
        if n % 3 == 0:
            planter = TEAM[0] if rnd["winner"] == "A" else lineup(opp)[0]
            rnd["plant"] = {"t": 45, "site": "A" if n % 2 else "B", "player": planter}
    if calls:
        s["call_log"] = str(calls)
    return s


def _write(folder: Path, name: str, scenario: dict, day: int) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = write_demo(folder / f"{name}.dem", scenario)
    stamp = 1_760_000_000 + 86400 * day
    os.utime(path, (stamp, stamp))
    return path


def _make_entry(api: Api, root: Path) -> int:
    calls = root / "calls.log"
    for day, (opp, score) in enumerate([("b", (13, 9)), ("c", (16, 14)), ("d", (13, 5))]):
        _write(root / "in", f"m{day}", rich_match(opp, f"srv{day}", score, calls), day)
    return api.confirm(api.run_import([root / "in"]), team_name="Dragons")


@pytest.fixture(scope="module")
def shared(tmp_path_factory: pytest.TempPathFactory):
    """One computed entry for the read-only tests (building it costs a few parses)."""
    root = tmp_path_factory.mktemp("shared")
    client, settings = make_api(root / "workspace")
    with client:
        api = Api(client, settings)
        yield api, _make_entry(api, root), root


@pytest.fixture
def entry(api: Api, tmp_path: Path) -> int:
    """A fresh entry for tests that change it."""
    return _make_entry(api, tmp_path)


def _eligible(rounds: list[dict], f: dict) -> list[dict]:
    side, buy = f["eligible"].get("side"), f["eligible"].get("buy")
    return [
        r for r in rounds if side in (None, "all", r["side"]) and buy in (None, "all", r["buy"])
    ]


def _check_recount(snapshot: dict) -> None:
    rounds = snapshot["round_index"]
    refs = {r["ref"] for r in rounds}
    for f in snapshot["findings"]:
        assert f["support"]["k"] == len(f["round_refs"]), f["id"]
        assert set(f["round_refs"]) <= refs, f["id"]
        demos = {r.split(":")[0] for r in f["round_refs"]}
        assert f["support"]["demos"] == len(demos), f["id"]
        assert ("low_sample" in f["flags"]) == (f["support"]["n"] < 10), f["id"]
        if f["kind"] == "team.winrate":
            eligible = _eligible(rounds, f)
            assert f["support"]["n"] == len(eligible), f["id"]
            assert set(f["round_refs"]) == {r["ref"] for r in eligible if r["won"]}, f["id"]
            assert f["outcome"]["won"] == f["support"]["k"]
        if f["kind"] in ("plr.stats", "util.player"):
            assert f["support"]["n"] == len(_eligible(rounds, f)), f["id"]


FILTERS = [
    {}, {"side": "T"}, {"side": "CT", "buy": ["full"]}, {"opp_buy": ["eco"]},
    {"buy": ["eco", "force"]}, {"ot": "false"}, {"from": "2025-10-10"}, {"to": "2025-10-10"},
]  # fmt: skip


@pytest.mark.parametrize("params", FILTERS, ids=lambda p: json.dumps(p, sort_keys=True))
def test_every_finding_recounts_from_its_rounds(shared, params: dict) -> None:
    api, entry, _ = shared
    snapshot = api.findings(entry, **params)
    assert snapshot["findings"], "filter left nothing to check"
    _check_recount(snapshot)


def test_filters_restrict_the_round_index(shared) -> None:
    api, entry, root = shared
    full = api.findings(entry)["round_index"]
    t_only = api.findings(entry, side="T")["round_index"]
    assert {r["side"] for r in t_only} == {"T"} and 0 < len(t_only) < len(full)
    no_ot = api.findings(entry, ot="false")["round_index"]
    assert len(full) - len(no_ot) == 6  # the 16-14 demo has 6 overtime rounds
    eco = api.findings(entry, buy=["eco"])["round_index"]
    assert {r["buy"] for r in eco} == {"eco"} and len(eco) == 6  # rounds 2 and 14, 3 demos
    one_demo = api.findings(entry, demos=[full[0]["demo_label"]])["round_index"]
    assert {r["demo_label"] for r in one_demo} == {full[0]["demo_label"]}
    # Filtering never re-parses (DRV-4): still one parse per demo.
    assert len((root / "calls.log").read_text().splitlines()) == 3


def test_stats_match_what_happened(shared) -> None:
    api, entry, _ = shared
    snap = api.findings(entry)
    keys = {m["nick"]: m["player_key"] for m in snap["roster"]}
    total_kills = sum(finding(snap, f"plr.stats.{keys[k]}.all")["params"]["kills"] for k in TEAM)
    our_round_wins = sum(1 for r in snap["round_index"] if r["won"])
    total_rounds = len(snap["round_index"])
    # simple_match: one kill per round by the round winner + rich_match: one kill per round by us.
    assert total_kills == our_round_wins + total_rounds
    assert {d["score"] for d in snap["demos"]} == {"13-9", "16-14", "13-5"}
    assert snap["grids"] and all(g["extent"] for g in snap["grids"].values())
    assert snap["schema_version"] == 5 and snap["entry"]["version"] == 1


def test_recompute_is_deterministic(api: Api, entry: int) -> None:
    lib = api.library
    first = (lib.version_dir(entry, 1) / "findings.json").read_text()
    job = api.wait(api.post(f"/api/entries/{entry}/recompute").json()["job_id"])
    assert job["state"] == "done"
    second = (lib.version_dir(entry, 2) / "findings.json").read_text()

    def stable(text: str) -> dict:
        snap = json.loads(text)
        snap["entry"].pop("version")
        snap["entry"].pop("generated_at")
        return snap

    assert stable(first) == stable(second)
    grids = [pl.read_parquet(lib.version_dir(entry, n) / "grids.parquet") for n in (1, 2)]
    assert grids[0].equals(grids[1])


def test_adding_a_demo_recomputes_and_keeps_old_version_until_swap(
    api: Api, entry: int, tmp_path: Path
) -> None:
    new = _write(tmp_path / "more", "m9", rich_match("e", "srv9", (13, 11)), day=9)
    job = api.wait(api.post(f"/api/entries/{entry}/demos", {"paths": [str(new)]}).json()["job_id"])

    assert job["state"] == "done", job
    assert job["result"]["recompute"]["version"] == 2
    snap = api.findings(entry)
    assert len(snap["demos"]) == 4 and snap["entry"]["version"] == 2
    assert snap["demos"][-1]["played_at"].startswith("2025-10-18")  # newest last


def test_excluding_a_demo_and_editing_roster(api: Api, entry: int) -> None:
    detail = api.get(f"/api/entries/{entry}").json()
    sha = detail["demos"][0]["sha256"]
    api.wait(api.patch(f"/api/entries/{entry}/demos/{sha}", {"included": False}).json()["job_id"])
    assert len(api.findings(entry)["demos"]) == 2

    before = {m["nick"]: m["player_key"] for m in api.findings(entry)["roster"]}
    core = [str(steamid(k)) for k in TEAM[:4]]
    body = {"core": core, "excluded": [str(steamid(TEAM[4]))]}
    api.wait(api.put(f"/api/entries/{entry}/roster", body).json()["job_id"])
    snap = api.findings(entry)
    assert len(snap["roster"]) == 4
    assert not any(f["subject"] == before[TEAM[4]] for f in snap["findings"])
    after = {m["nick"]: m["player_key"] for m in snap["roster"]}
    assert all(after[k] == before[k] for k in TEAM[:4]), "keys must not shift on roster edits"


def test_rounds_endpoint_lists_refs(shared) -> None:
    api, entry, _ = shared
    f = finding(api.findings(entry), "team.winrate.T.all")
    rounds = api.get(f"/api/entries/{entry}/rounds", params={"refs": f["round_refs"][:3]}).json()
    assert [r["ref"] for r in rounds] == f["round_refs"][:3]
    assert all({"demo_label", "round_num", "score_us", "score_them"} <= r.keys() for r in rounds)


def test_entry_lifecycle(api: Api, entry: int) -> None:
    assert [e["name"] for e in api.get("/api/entries").json()] == ["Dragons - de_mirage"]
    assert api.patch(f"/api/entries/{entry}", {"name": "SEA Mirage"}).json()["name"] == "SEA Mirage"
    wrong = api.delete(f"/api/entries/{entry}", params={"confirm": "nope"})
    assert wrong.status_code == 409 and wrong.json()["code"] == "CONFIRMATION_MISMATCH"
    assert api.delete(f"/api/entries/{entry}", params={"confirm": "SEA Mirage"}).status_code == 200
    assert api.get(f"/api/entries/{entry}").status_code == 404
    assert not (api.settings.home / "entries" / str(entry)).exists()


def test_same_team_and_map_twice_is_refused(api: Api, entry: int, tmp_path: Path) -> None:
    team_id = api.get(f"/api/entries/{entry}").json()["team_id"]
    path = _write(tmp_path / "again", "x", rich_match("z", "srvz"), day=20)
    job = api.run_import([path])
    response = api.post("/api/entries", {"import_job_id": job["job_id"], "team_id": team_id,
                                         "core": [str(steamid(k)) for k in TEAM]})  # fmt: skip
    assert response.status_code == 409 and response.json()["code"] == "ENTRY_EXISTS"


@pytest.mark.parametrize("retained", [True, False], ids=["source-retained", "no-source"])
def test_parser_upgrade_rebuilds_from_retained_sources(tmp_path: Path, retained: bool) -> None:
    """T-07 second half: an upgrade re-extracts from kept sources, or reports stale demos."""
    calls = tmp_path / "calls.log"
    for day in range(3):
        _write(tmp_path / "in", f"m{day}", rich_match("bcd"[day], f"u{day}", calls=calls), day)
    client, settings = make_api(tmp_path / "workspace", retain_sources=retained)
    with client:
        api = Api(client, settings)
        entry_id = api.confirm(api.run_import([tmp_path / "in"]))
    assert len(calls.read_text().splitlines()) == 3

    upgraded, settings2 = make_api(tmp_path / "workspace", adapter="support.synth:SynthAdapterV2",
                                   retain_sources=retained)  # fmt: skip
    with upgraded:
        api2 = Api(upgraded, settings2)
        job = api2.wait(api2.post(f"/api/entries/{entry_id}/recompute").json()["job_id"])
        snap = api2.findings(entry_id)
    assert job["state"] == "done", job
    if retained:
        assert len(calls.read_text().splitlines()) == 6  # each demo re-parsed once, from source
        assert snap["problems"] == [] and len(snap["demos"]) == 3
    else:
        assert len(calls.read_text().splitlines()) == 3  # nothing to rebuild from
        assert [p["code"] for p in snap["problems"]] == ["STALE_EXTRACT"] * 3
        assert len(snap["demos"]) == 3, "old extracts are kept and used, not dropped"


def test_new_entry_reusing_a_deleted_id_never_shows_old_results(api: Api, tmp_path: Path) -> None:
    """SQLite reuses the id of a deleted entry; cached views must not leak across entries."""
    first = _make_entry(api, tmp_path / "one")
    old_rounds = len(api.findings(first)["round_index"])
    deleted = api.delete(f"/api/entries/{first}", params={"confirm": "Dragons - de_mirage"})
    assert deleted.status_code == 200
    src = tmp_path / "two"
    _write(src, "only", rich_match("q", "fresh", score=(13, 0)), day=30)
    job = api.run_import([src])
    second = api.confirm(job, team_name="Other", core=[str(steamid(k)) for k in TEAM])
    assert second == first  # the id really is reused
    snap = api.findings(second)
    assert len(snap["round_index"]) == 13 != old_rounds
    assert [d["score"] for d in snap["demos"]] == ["13-0"]
