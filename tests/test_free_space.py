"""Free up space (issue #9): remove parsed data and demo copies that no analysis uses."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from cs2scout.__main__ import main
from support.api import Api
from support.synth import lineup, simple_match, write_demo


def _import(api: Api, root: Path, team: str, opps: str = "xy") -> dict:
    """One team's demos, imported and waiting for the roster to be confirmed."""
    root.mkdir(parents=True)
    for i, opp in enumerate(opps):
        write_demo(root / f"{team}{i}.dem",
                   simple_match(lineup(team), lineup(opp), server=f"{team}-{opp}{i}"))  # fmt: skip
    job = api.run_import([root])
    assert job["state"] == "done" and len(job["result"]["accepted"]) == len(opps)
    return job


def _deleted_analysis(api: Api, root: Path, team: str) -> list[str]:
    """Import, confirm and delete an analysis; returns its demos."""
    job = _import(api, root, team)
    entry = api.confirm(job, team_name=f"Team {team}")
    name = api.get(f"/api/entries/{entry}").json()["name"]
    assert api.delete(f"/api/entries/{entry}", params={"confirm": name}).status_code == 200
    return job["result"]["accepted"]


def _core(job: dict) -> list[str]:
    return [p["steamid"] for p in job["result"]["roster_proposal"]["players"]
            if p["role"] == "core"]  # fmt: skip


def test_freeing_space_removes_only_a_deleted_analysis_demos(api: Api, tmp_path: Path) -> None:
    home = api.settings.home
    kept = _import(api, tmp_path / "kept", "k")
    kept_entry = api.confirm(kept, team_name="Keepers")
    keep = kept["result"]["accepted"]
    assert api.get("/api/storage/unused").json()["demos"] == []
    gone = _deleted_analysis(api, tmp_path / "gone", "g")

    unused = api.get("/api/storage/unused").json()
    listed = {d["sha256"]: d for d in unused["demos"]}
    assert set(listed) == set(gone) and unused["busy"] is False and unused["kept"] == 0
    for d in listed.values():
        assert d["copy_bytes"] > 0 and d["parsed_bytes"] > 0 and d["file"].endswith(".dem")
        assert d["map"] == "de_mirage" and d["bytes"] == d["copy_bytes"] + d["parsed_bytes"]
    assert unused["total_bytes"] == sum(d["bytes"] for d in listed.values())

    # A demo of the kept analysis slipped into the request is not removed.
    freed = api.post("/api/storage/free", {"demos": gone + keep[:1]}).json()
    assert freed == {"removed_demos": 2, "removed_folders": 0,
                     "freed_bytes": unused["total_bytes"], "left": []}  # fmt: skip
    for sha in gone:
        assert not (home / "demos" / sha).exists() and not (home / "extracts" / sha).exists()
    for sha in keep:
        assert (home / "demos" / sha).exists() and (home / "extracts" / sha).exists()
    assert api.get("/api/storage/unused").json()["demos"] == []
    job = api.wait(api.post(f"/api/entries/{kept_entry}/recompute").json()["job_id"])
    assert job["state"] == "done", job
    # A removed demo can be imported again; it is parsed again.
    again = api.run_import([tmp_path / "gone"])
    assert sorted(again["result"]["accepted"]) == sorted(gone)


def test_an_import_waiting_for_its_roster_is_kept(api: Api, tmp_path: Path) -> None:
    waiting = _import(api, tmp_path / "new", "n")
    unused = api.get("/api/storage/unused").json()
    assert unused["demos"] == [] and unused["kept"] == 2
    asked = api.post("/api/storage/free", {"demos": waiting["result"]["accepted"]}).json()
    assert asked["removed_demos"] == 0
    api.confirm(waiting, team_name="Newcomers")
    assert api.get("/api/storage/unused").json()["kept"] == 0

    # A day later, an import nobody confirmed counts as abandoned. Confirming it after its
    # demos are gone says so instead of failing.
    old = _import(api, tmp_path / "old", "o")
    with closing(sqlite3.connect(api.settings.home / "library.sqlite")) as db, db:
        db.execute("UPDATE job SET updated_at = '2020-01-01T00:00:00+00:00' WHERE job_id = ?",
                   (old["job_id"],))  # fmt: skip
    listed = sorted(d["sha256"] for d in api.get("/api/storage/unused").json()["demos"])
    assert listed == sorted(old["result"]["accepted"])
    assert api.post("/api/storage/free", {"demos": listed}).json()["removed_demos"] == 2
    late = api.post("/api/entries", {"import_job_id": old["job_id"], "team_name": "Late",
                                     "core": _core(old)})  # fmt: skip
    assert late.status_code == 409 and late.json()["code"] == "IMPORT_NOT_READY"
    assert "Free up space" in late.json()["message"]
    assert [e["name"] for e in api.get("/api/entries").json()] == ["Newcomers - de_mirage"]


def test_nothing_is_removed_while_an_import_runs(api: Api, tmp_path: Path) -> None:
    home = api.settings.home
    gone = _deleted_analysis(api, tmp_path / "gone", "g")
    slow = tmp_path / "slow"
    slow.mkdir()
    write_demo(slow / "s.dem", simple_match(lineup("s"), lineup("x"), server="slow")
               | {"sleep_s": 60})  # fmt: skip
    job_id = api.post("/api/imports", {"paths": [str(slow)]}).json()["job_id"]
    try:
        assert api.get("/api/storage/unused").json() == {
            "busy": True, "demos": [], "folders": [], "kept": 0, "total_bytes": 0}  # fmt: skip
        blocked = api.post("/api/storage/free", {"demos": gone})
        assert blocked.status_code == 409 and blocked.json()["code"] == "CONFLICT_JOB_RUNNING"
        assert "import is running" in api.get("/ui/storage/unused").text
    finally:
        api.post(f"/api/jobs/{job_id}/cancel")
        assert api.wait(job_id)["state"] == "cancelled"
    assert all((home / "extracts" / sha).exists() for sha in gone)
    assert {d["sha256"] for d in api.get("/api/storage/unused").json()["demos"]} == set(gone)


def test_settings_page_and_command_line(api: Api, tmp_path: Path, capsys: pytest.CaptureFixture,
                                        monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    home = api.settings.home
    gone = _deleted_analysis(api, tmp_path / "gone", "g")
    stray = home / "extracts" / "leftover"  # a folder a crash left behind
    (stray / "x").mkdir(parents=True)
    (stray / "x" / "part.parquet").write_bytes(b"0" * 2000)

    page = api.get("/settings").text
    assert "Free up space" in page and "Check what can go" in page
    listing = api.get("/ui/storage/unused").text
    assert "No analysis uses these" in listing and "g0.dem" in listing
    assert "Leftover folder <code>extracts/leftover</code>" in listing and "Free up " in listing

    monkeypatch.setenv("CS2SCOUT_HOME", str(home))
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert main(["free-space"]) == 0
    out = capsys.readouterr().out
    assert "No analysis uses these:" in out and "g1.dem" in out and "leftover folder" in out
    assert "Nothing removed." in out and stray.exists()

    done = api.client.post("/ui/storage/free", headers=api.headers,
                           data={"demo": gone, "folder": ["extracts/leftover"]})  # fmt: skip
    assert "Freed " in done.text and "removed 2 demos and 1 leftover folder" in done.text
    assert not stray.exists() and not (home / "extracts" / gone[0]).exists()

    _deleted_analysis(api, tmp_path / "more", "m")
    assert main(["free-space", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "Freed " in out and "removed 2 demo(s)" in out
    assert main(["free-space", "--yes"]) == 0
    assert "Nothing to remove" in capsys.readouterr().out
