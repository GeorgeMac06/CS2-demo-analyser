"""Process settings read from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Fixed by design (C-1, DRV-5): the server is never reachable from the network.
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


@dataclass(frozen=True)
class Settings:
    home: Path
    port: int

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Settings:
        home_value = environ.get("CS2SCOUT_HOME")
        if home_value:
            home = Path(home_value)
        else:
            base = environ.get("LOCALAPPDATA")
            home = (Path(base) if base else Path.home()) / "CS2DemoScout"

        port_value = environ.get("CS2SCOUT_PORT", str(DEFAULT_PORT))
        try:
            port = int(port_value)
        except ValueError:
            raise ValueError(f"CS2SCOUT_PORT must be an integer, got {port_value!r}") from None
        if not 1 <= port <= 65535:
            raise ValueError(f"CS2SCOUT_PORT must be between 1 and 65535, got {port}")

        return cls(home=home, port=port)
