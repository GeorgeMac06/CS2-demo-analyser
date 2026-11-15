"""T-01 end to end (AT-1, QS-1) on the owner's real demos, through the API, real parser.

J1 for real: import -> proposed roster -> confirm -> recompute -> findings. The reference is
the game server's own data inside each demo: player scoreboard counters and team scores.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
import pytest

from cs2scout.jobs.extract_worker import DEFAULT_ADAPTER, adapter_identity
from cs2scout.store.extracts import read_tables
from support.api import Api, make_api
from support.oracle import server_team_scores

pytestmark = pytest.mark.demos
DEMOS = Path(__file__).parent / "local_fixtures" / "demos"
ADR_TOLERANCE = 2.0  # spike S-1: max observed difference 1.75
SLOW = 1800  # seconds; real parsing plus gzip retention, and speed is not a goal (D5)


@pytest.fixture(scope="module")
def computed(tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest):
    demos = sorted(DEMOS.glob("*.dem"))
    if not demos:
        if request.config.getoption("--require-demos"):
            pytest.fail(f"Real demo fixtures missing: put .dem files in {DEMOS}")
        pytest.skip("no real demos")
    root = tmp_path_factory.mktemp("real")
    client, settings = make_api(root / "workspace", adapter=DEFAULT_ADAPTER)
    with client:
        api = Api(client, settings)
        job = api.run_import(demos, timeout=SLOW)
        assert job["state"] == "done", job
        entry_id = api.confirm(job, team_name="Scouted", timeout=SLOW)
        yield api, job, entry_id, demos


def _counters(api: Api, sha: str) -> pl.DataFrame:
    parser, version = adapter_identity(DEFAULT_ADAPTER)
    row = api.library.find_extract(sha, parser, version, 1)
    return read_tables(Path(row["path"]), {"server_counters": None})["server_counters"]


def test_import_accepts_all_and_proposes_one_clear_roster(computed) -> None:
    _, job, _, demos = computed
    result = job["result"]
    assert [f["status"] for f in result["files"]] == ["accepted"] * len(demos)
    proposal = result["roster_proposal"]
    assert proposal["needs_pick"] is False
    assert sum(p["role"] == "core" for p in proposal["players"]) == 5
    assert all(lu is not None for lu in proposal["scouted"].values())


def test_scores_match_the_server(computed) -> None:
    api, _, entry_id, _ = computed
    snap = api.findings(entry_id)
    by_label = {d["label"]: d for d in snap["demos"]}
    for d in api.get(f"/api/entries/{entry_id}").json()["demos"]:
        summary = by_label[d["label"]]
        assert summary["used"] and summary["complete"], summary
        rounds = [r for r in snap["round_index"] if r["demo_label"] == d["label"]]
        us = sum(r["won"] for r in rounds)
        half_us = sum(r["won"] for r in rounds if r["round_num"] <= 12)
        path = api.library.get_demo(d["sha256"])["original_path"]
        half_tick = _round12_end(api, d["sha256"])
        final, half = server_team_scores(Path(path), half_tick)
        assert final == sorted([us, len(rounds) - us], reverse=True), d["label"]
        assert half == sorted([half_us, 12 - half_us], reverse=True), d["label"]


def _round12_end(api: Api, sha: str) -> int:
    parser, version = adapter_identity(DEFAULT_ADAPTER)
    path = Path(api.library.find_extract(sha, parser, version, 1)["path"])
    r12 = (
        read_tables(path, {"rounds": None})["rounds"]
        .filter(pl.col("round_num") == 12)
        .row(0, named=True)
    )
    return r12["official_end_tick"] or r12["end_tick"]


def test_player_kda_and_adr_match_the_server(computed) -> None:
    api, _, entry_id, _ = computed
    snap = api.findings(entry_id)
    vdir = api.library.current_version_dir(entry_id)
    keys = {m["steamid"]: m["player_key"]
            for m in json.loads((vdir / "players.json").read_text())}  # fmt: skip
    server = (
        pl.concat(_counters(api, d["sha256"]) for d in snap["demos"])
        .filter(pl.col("steamid").is_in(list(keys)))
        .group_by("steamid")
        .agg(pl.col("kills", "deaths", "assists", "damage").sum())
    )
    assert server.height == len(keys) == 5
    for row in server.iter_rows(named=True):
        stats = next(f for f in snap["findings"]
                     if f["id"] == f"plr.stats.{keys[row['steamid']]}.all")["params"]  # fmt: skip
        ours = (stats["kills"], stats["deaths"], stats["assists"])
        assert ours == (row["kills"], row["deaths"], row["assists"]), keys[row["steamid"]]
        server_adr = row["damage"] / stats["rounds"]
        assert abs(stats["adr"] - server_adr) <= ADR_TOLERANCE, (stats["adr"], server_adr)


def test_findings_are_sane_on_real_data(computed) -> None:
    api, _, entry_id, _ = computed
    snap = api.findings(entry_id)
    assert snap["problems"] == []
    assert len(snap["roster"]) == 5
    assert snap["grids"]
    t_side = api.findings(entry_id, side="T")
    assert {r["side"] for r in t_side["round_index"]} == {"T"}


def test_truncated_demo_is_never_accepted_as_complete(tmp_path: Path) -> None:
    demos = sorted(DEMOS.glob("*.dem"), key=lambda p: p.stat().st_size)
    if not demos:
        pytest.skip("no real demos")
    cut = tmp_path / "in" / "truncated.dem"
    cut.parent.mkdir()
    with demos[0].open("rb") as src, cut.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1 << 20)
        dst.truncate(demos[0].stat().st_size // 2)
    client, settings = make_api(tmp_path / "workspace", adapter=DEFAULT_ADAPTER)
    with client:
        job = Api(client, settings).run_import([cut], timeout=SLOW)
    report = job["result"]["files"][0]
    assert report["status"] == "rejected" or report.get("complete") is False, report
