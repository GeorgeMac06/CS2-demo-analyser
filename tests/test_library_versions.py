"""T-06 (store part, AT-6) and the job rules: interruptions never leave a half-updated entry."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from cs2scout.jobs.runner import JobConflict, JobRunner
from cs2scout.store.library import TMP_PREFIX, Library


def _entry_with_ready_version(home: Path) -> tuple[Library, int]:
    lib = Library(home)
    entry_id = lib.create_entry(lib.create_team("Team A"), "de_mirage", "Team A - Mirage")
    n, path = lib.begin_version(entry_id, "cfg", "in1")
    (path / "findings.json").write_text("{}")
    lib.commit_version(entry_id, n)
    return lib, entry_id


def test_process_killed_mid_recompute_leaves_previous_version(tmp_path: Path) -> None:
    lib, entry_id = _entry_with_ready_version(tmp_path)
    script = textwrap.dedent(f"""
        import os
        from pathlib import Path
        from cs2scout.store.library import Library
        lib = Library(Path(r"{tmp_path}"))
        n, path = lib.begin_version({entry_id}, "cfg", "in2")
        (path / "findings.json").write_text("half written")
        os._exit(1)  # killed between writing files and the swap
    """)
    subprocess.run([sys.executable, "-c", script], check=False)

    report = Library(tmp_path).startup_cleanup()

    assert report["building_versions"] == 1
    assert lib.get_entry(entry_id).current_version == 1
    assert (lib.version_dir(entry_id, 1) / "findings.json").read_text() == "{}"
    assert not lib.version_dir(entry_id, 2).exists()


def test_only_current_and_previous_versions_are_kept(tmp_path: Path) -> None:
    lib, entry_id = _entry_with_ready_version(tmp_path)
    for _ in range(3):
        n, _path = lib.begin_version(entry_id, "cfg", "x")
        lib.commit_version(entry_id, n)

    assert lib.get_entry(entry_id).current_version == 4
    kept = sorted(p.name for p in (tmp_path / "entries" / str(entry_id)).iterdir())
    assert kept == ["v3", "v4"]


def test_startup_cleanup_only_removes_own_scratch_files(tmp_path: Path) -> None:
    lib = Library(tmp_path)
    (tmp_path / "tmp" / f"{TMP_PREFIX}abc.dem").write_bytes(b"x")
    (tmp_path / "tmp" / "not-ours.txt").write_text("keep me")
    partial = tmp_path / "extracts" / "sha" / "awpy@1+s1._partial"
    partial.mkdir(parents=True)

    lib.startup_cleanup()

    assert not (tmp_path / "tmp" / f"{TMP_PREFIX}abc.dem").exists()
    assert (tmp_path / "tmp" / "not-ours.txt").exists()
    assert not partial.exists()


def test_running_jobs_are_marked_interrupted_after_restart(tmp_path: Path) -> None:
    lib = Library(tmp_path)
    lib.create_job("j1", "import", None)
    lib.update_job("j1", state="running")

    Library(tmp_path).startup_cleanup()

    job = lib.get_job("j1")
    assert (job["state"], job["error"]) == ("failed", "interrupted by restart")


def test_one_job_per_entry_and_cancel(tmp_path: Path) -> None:
    lib, entry_id = _entry_with_ready_version(tmp_path)
    runner = JobRunner(lib)
    started = threading.Event()

    def slow(ctx):
        started.set()
        while True:
            ctx.check_cancel()
            time.sleep(0.05)

    job_id = runner.submit("recompute", slow, entry_id=entry_id)
    assert started.wait(5)
    with pytest.raises(JobConflict):
        runner.submit("recompute", slow, entry_id=entry_id)

    runner.cancel(job_id)
    deadline = time.monotonic() + 5
    while lib.get_job(job_id)["state"] != "cancelled" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert lib.get_job(job_id)["state"] == "cancelled"
    assert not runner.busy(entry_id)
    runner.shutdown()
