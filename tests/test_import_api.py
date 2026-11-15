"""Import through the API: T-04 (import part), T-06 (cancel part), T-07, T-08."""

from __future__ import annotations

import gzip
import json
import os
import time
import zipfile
from pathlib import Path

import pytest

from cs2scout.ingest.files import Limits
from support.api import Api, make_api
from support.synth import lineup, simple_match, write_demo


def demo(folder: Path, name: str, **scenario_overrides) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    scenario = simple_match(lineup("a"), lineup(name[:2] + "x"), server=name) | scenario_overrides
    return write_demo(folder / f"{name}.dem", scenario)


def statuses(job: dict) -> dict[str, tuple]:
    result = job["result"].get("import", job["result"])  # J2 jobs nest the import result
    return {f["file"]: (f["status"], f.get("code")) for f in result["files"]}


def test_new_import_accepts_and_retains(api: Api, tmp_path: Path) -> None:
    for name in ("m1", "m2", "m3"):
        demo(tmp_path / "in", name)

    job = api.run_import([tmp_path / "in"])

    assert job["state"] == "done", job
    assert job["result"]["map"] == "de_mirage"
    assert len(job["result"]["accepted"]) == 3
    for sha in job["result"]["accepted"]:
        assert api.library.source_path(sha).exists()
        assert api.library.get_demo(sha)["rounds"] == 18


def test_bad_inputs_get_exact_codes_and_publish_nothing(api: Api, tmp_path: Path) -> None:
    src = tmp_path / "in"
    good = demo(src, "good")
    demo(src, "good2")
    (src / "copy_of_good.dem").write_bytes(good.read_bytes())
    scenario = json.loads(good.read_bytes()[len(b"PBDEMS2\x00CS2SCOUT-SYNTH\n") :])
    write_demo(src / "reencoded.dem", scenario | {"names": {"zz": "unused"}})
    (src / "csgo.dem").write_bytes(b"HL2DEMO\x00" + os.urandom(64))
    (src / "junk.dem").write_bytes(os.urandom(256))
    (src / "broken.dem").write_bytes(b"PBDEMS2\x00CS2SCOUT-SYNTH\n{not json")
    demo(src, "inferno", map="de_inferno")
    (src / "notes.txt").write_text("hi")

    job = api.run_import([src])

    assert statuses(job) == {
        "broken.dem": ("rejected", "DEMO_UNREADABLE"),
        "copy_of_good.dem": ("accepted", None),  # files are processed in name order
        "csgo.dem": ("rejected", "NOT_CS2"),
        "good.dem": ("duplicate", "DUPLICATE"),
        "good2.dem": ("accepted", None),
        "inferno.dem": ("rejected", "MAP_MISMATCH"),
        "junk.dem": ("rejected", "NOT_CS2"),
        "reencoded.dem": ("duplicate", "DUPLICATE"),
    }
    assert job["result"]["skipped"] == []  # other files in a folder are ignored (design §6.1)
    explicit = api.run_import([src / "notes.txt", src / "missing.dem"])
    assert explicit["result"]["skipped"] == [
        {"file": "notes.txt", "reason": "not a demo or supported archive"},
        {"file": "missing.dem", "reason": "not found"},
    ]
    assert list((api.settings.home / "tmp").iterdir()) == []
    assert not list((api.settings.home / "extracts").glob("*/*._partial"))


def test_hostile_archives_are_bounded(tmp_path: Path) -> None:
    src, ws = tmp_path / "in", tmp_path / "workspace"
    payload = demo(tmp_path / "plain", "arch").read_bytes()
    src.mkdir()
    with gzip.open(src / "ok.dem.gz", "wb") as f:
        f.write(payload)
    with zipfile.ZipFile(src / "escape.zip", "w") as z:
        z.writestr("../../escape.dem", payload)
    with zipfile.ZipFile(src / "bomb.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.dem", b"\0" * 20_000_000)
    with zipfile.ZipFile(src / "multi.zip", "w") as z:
        z.writestr("a.dem", payload)
        z.writestr("b.dem", payload)
    with zipfile.ZipFile(src / "nested.zip", "w") as z:
        z.writestr("inner.zip", b"PK")
    with gzip.open(src / "big.dem.gz", "wb", compresslevel=1) as f:
        f.write(os.urandom(6_000_000))
    before = {p for p in tmp_path.rglob("*") if ws not in p.parents and p != ws}

    client, _ = make_api(ws, archive_limits=Limits(max_bytes=5_000_000, max_ratio=50))
    with client:
        job = Api(client, _).run_import([src])

    result = statuses(job)
    # Same demo bytes inside both archives: one is accepted, the other is its duplicate.
    assert {result["ok.dem.gz"], result["escape.zip"]} == {
        ("accepted", None),
        ("duplicate", "DUPLICATE"),
    }
    for name in ("bomb.zip", "multi.zip", "nested.zip", "big.dem.gz"):
        assert result[name] == ("rejected", "ARCHIVE_REJECTED"), name
    after = {p for p in tmp_path.rglob("*") if ws not in p.parents and p != ws}
    assert after == before, "nothing may be written outside the workspace"
    assert list((ws / "tmp").iterdir()) == []


def test_only_new_demos_are_parsed(api: Api, tmp_path: Path) -> None:
    calls = tmp_path / "calls.log"
    src = tmp_path / "in"
    first = [demo(src, n, call_log=str(calls)) for n in ("m1", "m2", "m3")]
    lib = api.library
    entry_id = lib.create_entry(lib.create_team("Team A"), "de_mirage", "Team A - Mirage")

    api.run_import(first, entry_id=entry_id)
    fourth = demo(src, "m4", call_log=str(calls))
    job = api.run_import([*first, fourth], entry_id=entry_id)

    assert [s for s, _ in statuses(job).values()].count("duplicate") == 3
    assert len(calls.read_text().splitlines()) == 4  # each demo parsed exactly once

    other = lib.create_entry(lib.create_team("Team B"), "de_mirage", "Team B - Mirage")
    reuse = api.run_import(first[:1], entry_id=other)
    assert statuses(reuse)["m1.dem"] == ("accepted", None)
    assert len(calls.read_text().splitlines()) == 4  # reused from the library, not re-parsed


def test_entry_map_is_enforced(api: Api, tmp_path: Path) -> None:
    lib = api.library
    entry_id = lib.create_entry(lib.create_team("Team A"), "de_inferno", "Team A - Inferno")
    job = api.run_import([demo(tmp_path, "mirage")], entry_id=entry_id)
    assert statuses(job)["mirage.dem"] == ("rejected", "MAP_MISMATCH")


def test_cancel_keeps_finished_extracts(api: Api, tmp_path: Path) -> None:
    src = tmp_path / "in"
    demo(src, "a_fast")
    demo(src, "b_slow", sleep_s=60)
    job_id = api.post("/api/imports", {"paths": [str(src)]}).json()["job_id"]
    deadline = time.monotonic() + 60
    while (api.get(f"/api/jobs/{job_id}").json().get("progress") or {}).get("file") != "b_slow.dem":
        assert time.monotonic() < deadline
        time.sleep(0.1)

    assert api.post(f"/api/jobs/{job_id}/cancel").json() == {"cancel_requested": True}
    job = api.wait(job_id, timeout=30)

    assert job["state"] == "cancelled"
    extracts = list((api.settings.home / "extracts").glob("*/*"))
    assert len(extracts) == 1 and not extracts[0].name.endswith("._partial")
    assert api.library.list_entries() == []


def test_unknown_job_and_entry_are_404(api: Api) -> None:
    assert api.get("/api/jobs/nope").json()["code"] == "NOT_FOUND"
    assert api.post("/api/imports", {"paths": ["x"], "entry_id": 99}).status_code == 404
    assert api.post("/api/imports", {"paths": []}).json()["code"] == "INVALID_REQUEST"


@pytest.fixture(autouse=True)
def _no_real_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CS2SCOUT_HOME", raising=False)
