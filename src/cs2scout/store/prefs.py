"""The Analyst's settings, saved in the workspace as ``settings.json`` (WU-16).

Q1-Q3 analysis thresholds, source retention (ADR-003), the workspace cap (warning only) and
the port. A missing or unreadable file means defaults: settings never stop the app starting.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from cs2scout.core.config import AnalysisConfig

log = logging.getLogger(__name__)
FILE = "settings.json"
# The thresholds the Analyst may change (requirements Q1-Q3). Grid and phase sizes stay fixed.
TUNABLE = ("eco_max", "force_max", "min_support_rounds", "min_support_share",
           "min_support_demos", "low_sample_rounds", "checkpoints_s")  # fmt: skip


@dataclass(frozen=True)
class Prefs:
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    retain_sources: bool = True
    workspace_cap_gb: float | None = None  # None: no cap. Going over it only warns.
    port: int | None = None  # None: the default port. CS2SCOUT_PORT still wins.

    def to_json(self) -> dict:
        analysis = asdict(self.analysis)
        return {"analysis": {k: analysis[k] for k in TUNABLE},
                "retain_sources": self.retain_sources,
                "workspace_cap_gb": self.workspace_cap_gb, "port": self.port}  # fmt: skip


def from_json(data: dict) -> Prefs:
    analysis = {k: v for k, v in (data.get("analysis") or {}).items() if k in TUNABLE}
    if "checkpoints_s" in analysis:
        analysis["checkpoints_s"] = tuple(analysis["checkpoints_s"])
    return Prefs(analysis=replace(AnalysisConfig(), **analysis),
                 retain_sources=bool(data.get("retain_sources", True)),
                 workspace_cap_gb=data.get("workspace_cap_gb"), port=data.get("port"))  # fmt: skip


def load(home: Path) -> Prefs:
    path = home / FILE
    if not path.exists():
        return Prefs()
    try:
        return from_json(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError) as exc:
        log.warning("ignoring unreadable %s (%s); using defaults", path, exc)
        return Prefs()


def save(home: Path, prefs: Prefs) -> None:
    """Atomic: a crash mid-write leaves the previous settings in place."""
    home.mkdir(parents=True, exist_ok=True)
    tmp = home / (FILE + ".tmp")
    tmp.write_text(json.dumps(prefs.to_json(), indent=1), encoding="utf-8")
    os.replace(tmp, home / FILE)
