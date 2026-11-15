"""Workspace layout (target design §5.1)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

SUBDIRS = ("demos", "extracts", "entries", "assets", "tmp", "logs")


def init_workspace(home: Path) -> Path:
    """Create the workspace folders if missing. Never deletes anything."""
    for name in SUBDIRS:
        (home / name).mkdir(parents=True, exist_ok=True)
    return home


# What each folder holds, in the words the settings page uses.
AREAS = {"demos": "Retained demos", "extracts": "Parsed data", "entries": "Analyses"}


def _size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:  # removed while walking
                pass
    return total


def usage(home: Path, cap_gb: float | None = None) -> dict:
    """Bytes used per area, free space on the drive, and whether the cap is exceeded."""
    areas = {name: _size(home / name) for name in AREAS}
    total = _size(home)
    cap = int(cap_gb * 1e9) if cap_gb else None
    return {"total_bytes": total, "areas": areas | {"other": total - sum(areas.values())},
            "free_bytes": shutil.disk_usage(home).free, "cap_bytes": cap,
            "over_cap": cap is not None and total > cap}  # fmt: skip
