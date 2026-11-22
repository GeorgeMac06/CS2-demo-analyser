"""A workspace copied to another folder still works (README "Backup": copy the folder back,
or set CS2SCOUT_HOME to wherever the copy is)."""

from __future__ import annotations

import shutil
from pathlib import Path

from support.api import Api, make_api
from support.synth import lineup, simple_match, write_demo


def test_a_copied_workspace_can_still_update_its_analyses(tmp_path: Path) -> None:
    first = tmp_path / "first"
    client, settings = make_api(first)
    with client:
        api = Api(client, settings)
        demos = tmp_path / "in"
        demos.mkdir()
        for i in range(2):
            write_demo(demos / f"m{i}.dem", simple_match(lineup("a"), lineup(f"o{i}"),
                                                         server=f"s{i}"))  # fmt: skip
        entry = api.confirm(api.run_import([demos]), team_name="Dragons")
        before = api.findings(entry)

    moved = tmp_path / "moved"
    shutil.copytree(first, moved)
    shutil.rmtree(first / "extracts")  # nothing may be read from the old folder

    client, settings = make_api(moved)
    with client:
        api = Api(client, settings)
        job = api.wait(api.post(f"/api/entries/{entry}/recompute").json()["job_id"])
        assert job["state"] == "done", job
        after = api.findings(entry)
    assert after["entry"]["version"] == before["entry"]["version"] + 1
    assert after["round_index"] == before["round_index"]
    assert not after.get("problems")
