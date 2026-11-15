"""Filtered findings (design §5.3 S7): restrict the round index and recount. No re-parse."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.findings import RoundFilter, all_findings, round_index_json


def load_snapshot(version_dir: Path) -> dict:
    return json.loads((version_dir / "findings.json").read_text(encoding="utf-8"))


def filtered_snapshot(version_dir: Path, flt: RoundFilter) -> dict:
    """The snapshot recomputed for ``flt``.

    Cached per (version folder, its findings file's identity, filter). The file identity
    matters: SQLite reuses a deleted entry's id, so a brand-new entry can get the same
    ``entries/<id>/v1`` path as a deleted one, and must never be served the old results.
    """
    stat = (version_dir / "findings.json").stat()
    return _filtered(version_dir, (stat.st_mtime_ns, stat.st_size), flt)


@lru_cache(maxsize=64)
def _filtered(version_dir: Path, _stamp: tuple[int, int], flt: RoundFilter) -> dict:
    snapshot = load_snapshot(version_dir)
    if flt == RoundFilter() or not (version_dir / "rounds.parquet").exists():
        return snapshot | {"filter": None}
    rounds = flt.apply(pl.read_parquet(version_dir / "rounds.parquet"))
    players = pl.read_parquet(version_dir / "player_rounds.parquet")
    roster = json.loads((version_dir / "players.json").read_text(encoding="utf-8"))
    used = [d["label"] for d in snapshot["demos"] if d["used"]]
    # The same thresholds the version was built with, not today's settings.
    config_file = version_dir / "config.json"
    cfg = (
        AnalysisConfig.from_dict(json.loads(config_file.read_text(encoding="utf-8")))
        if config_file.exists()
        else AnalysisConfig()
    )
    patterns_file = version_dir / "patterns.json"
    patterns = (
        json.loads(patterns_file.read_text(encoding="utf-8")) if patterns_file.exists() else []
    )
    findings = all_findings(rounds, players, roster, patterns, cfg, used[-3:])
    return snapshot | {
        "round_index": round_index_json(rounds),
        "findings": findings,
        "filter": {k: v for k, v in vars(flt).items() if v not in ((), None, True)},
    }
