"""Workspace layout (target design §5.1)."""

from __future__ import annotations

from pathlib import Path

SUBDIRS = ("demos", "extracts", "entries", "assets", "tmp", "logs")


def init_workspace(home: Path) -> Path:
    """Create the workspace folders if missing. Never deletes anything."""
    for name in SUBDIRS:
        (home / name).mkdir(parents=True, exist_ok=True)
    return home
