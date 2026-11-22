"""Free up space: remove parsed data and demo copies that no analysis uses (issue #9).

Deleting an analysis removes its results only. Its demos stay in the library, so importing
them again is instant, but they hold about 150-260 MB each. ``unused`` lists what could go
and how much space that frees; ``free`` removes only what the Analyst saw in that list and
is still unused.

What is never removed:
- a demo that any analysis uses, included or not;
- a demo from an import that is waiting for its roster to be confirmed (finished in the last
  ``PENDING_IMPORT_H`` hours, and not turned into an analysis yet);
- anything while an import is queued or running, because an import writes its files before it
  records the demo, and may reuse an unused demo's parsed data.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cs2scout.store.library import Library
from cs2scout.store.workspace import folder_size

PENDING_IMPORT_H = 24  # an unconfirmed import older than this counts as abandoned
AREAS = ("demos", "extracts")  # per-demo folders: retained copy, parsed data


class StorageBusy(RuntimeError):
    """An import is queued or running: nothing can be removed safely now."""


def _running_imports(db: sqlite3.Connection) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM job WHERE kind = 'import' AND state IN ('queued', 'running')"
    ).fetchone()[0]


def _pending(db: sqlite3.Connection, used: set[str]) -> set[str]:
    """Demos of recent imports still waiting for roster confirmation. A confirmed import
    carries its new entry's id (``Library.mark_import_confirmed``), so the demos of an
    analysis that was deleted later are not kept."""
    cutoff = (datetime.now(UTC) - timedelta(hours=PENDING_IMPORT_H)).isoformat(timespec="seconds")
    rows = db.execute(
        "SELECT result FROM job WHERE kind = 'import' AND entry_id IS NULL AND state = 'done'"
        " AND updated_at >= ?",
        (cutoff,),
    ).fetchall()
    waiting: set[str] = set()
    for (result,) in rows:
        waiting |= set((json.loads(result) if result else {}).get("accepted") or []) - used
    return waiting


def _scan(db: sqlite3.Connection) -> tuple[list[sqlite3.Row], set[str], set[str]]:
    """(unused demo rows, demos kept for a pending import, every known demo)."""
    every = {r[0] for r in db.execute("SELECT sha256 FROM demo")}
    used = {r[0] for r in db.execute("SELECT sha256 FROM entry_demo")}
    waiting = _pending(db, used)
    unused = db.execute(
        "SELECT sha256, map, played_at, original_path FROM demo"
        " WHERE sha256 NOT IN (SELECT sha256 FROM entry_demo) ORDER BY played_at, sha256"
    ).fetchall()
    return [r for r in unused if r["sha256"] not in waiting], waiting, every


def _strays(home: Path, every: set[str]) -> list[str]:
    """Per-demo folders the library has no record of (left by a crash): ``extracts/<sha>``."""
    out = []
    for area in AREAS:
        root = home / area
        if root.is_dir():
            out += [f"{area}/{p.name}" for p in sorted(root.iterdir())
                    if p.is_dir() and p.name not in every]  # fmt: skip
    return out


def _file_name(path: str | None) -> str:
    return (path or "").replace("\\", "/").rsplit("/", 1)[-1]


def unused(lib: Library) -> dict:
    """What would go, with sizes. ``busy`` is true while an import runs (nothing listed)."""
    with lib.transaction() as db:
        if _running_imports(db):
            return {"busy": True, "demos": [], "folders": [], "kept": 0, "total_bytes": 0}
        rows, waiting, every = _scan(db)
    demos = []
    for r in rows:
        sizes = {area: folder_size(lib.home / area / r["sha256"]) for area in AREAS}
        demos.append({"sha256": r["sha256"], "map": r["map"], "played_at": r["played_at"],
                      "file": _file_name(r["original_path"]),
                      "copy_bytes": sizes["demos"], "parsed_bytes": sizes["extracts"],
                      "bytes": sum(sizes.values())})  # fmt: skip
    folders = [{"path": p, "bytes": folder_size(lib.home / p)} for p in _strays(lib.home, every)]
    total = sum(d["bytes"] for d in demos) + sum(f["bytes"] for f in folders)
    return {"busy": False, "demos": demos, "folders": folders, "kept": len(waiting),
            "total_bytes": total}  # fmt: skip


def free(lib: Library, demos: list[str], folders: list[str]) -> dict:
    """Remove the given demos and stray folders, if they are still unused right now.

    The library rows go first, in one locked transaction that checks again, so an import
    or a confirmation that started since the list was shown is never broken. The folders
    go after; one that cannot be removed (a file in use) is left and listed as a stray
    next time. Raises ``StorageBusy`` while an import is queued or running."""
    with lib.transaction() as db:
        if _running_imports(db):
            raise StorageBusy("an import is running")
        rows, _, every = _scan(db)
        drop = sorted({r["sha256"] for r in rows} & set(demos))
        for sha in drop:
            db.execute("DELETE FROM demo WHERE sha256 = ?", (sha,))
    strays = sorted(set(_strays(lib.home, every)) & set(folders))
    targets = [lib.home / area / sha for sha in drop for area in AREAS]
    targets += [lib.home / p for p in strays]
    freed, left = 0, []
    for path in targets:
        size = folder_size(path)
        shutil.rmtree(path, ignore_errors=True)
        if path.exists():
            left.append(os.path.relpath(path, lib.home).replace("\\", "/"))
            size -= folder_size(path)
        freed += size
    return {"removed_demos": len(drop), "removed_folders": len(strays), "freed_bytes": freed,
            "left": left}  # fmt: skip
