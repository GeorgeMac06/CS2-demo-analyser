"""AnalysisConfig: every tunable analysis threshold (requirements Q1-Q3), hashed into results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AnalysisConfig:
    # Q1: team equipment value at freeze end (pistol rounds are classified by round number).
    eco_max: int = 5000
    force_max: int = 20000
    # Q2: a finding needs this much support to count as a pattern; warn below low_sample.
    min_support_rounds: int = 3
    min_support_share: float = 0.15
    low_sample_rounds: int = 10
    # Q3: seconds after freeze end at which T setups are read.
    checkpoints_s: tuple[int, ...] = (15, 30, 45)
    # Heatmap resolution (cells per side) and round phases in seconds after freeze end.
    grid_cells: int = 64
    phase_early_s: int = 20
    phase_mid_s: int = 60

    def digest(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]
