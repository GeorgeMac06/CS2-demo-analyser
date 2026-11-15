"""Process settings read from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cs2scout.ingest.files import Limits
from cs2scout.jobs.extract_worker import DEFAULT_ADAPTER, DEFAULT_TIMEOUT_S
from cs2scout.store import prefs

# Fixed by design (C-1, DRV-5): the server is never reachable from the network.
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
DEFAULT_AI_MODEL = "claude-opus-5-5"  # mirrors cs2scout.ai.client (settings stays SDK-free)


def read_dotenv(path: Path) -> dict[str, str]:
    """``KEY=value`` lines from a ``.env`` file; a missing file is empty."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    out = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        out[key.strip()] = value.strip().strip("'\"")
    return out


@dataclass(frozen=True)
class Settings:
    home: Path
    port: int
    # Not read from the environment: tests inject a synthetic parser and smaller limits.
    adapter: str = DEFAULT_ADAPTER
    retain_sources: bool = True
    archive_limits: Limits = field(default_factory=Limits)
    parse_timeout_s: float = DEFAULT_TIMEOUT_S
    # FR-AI-1, DEP-4: optional. Never printed: repr=False keeps it out of logs and tracebacks.
    anthropic_api_key: str | None = field(default=None, repr=False)
    ai_model: str = DEFAULT_AI_MODEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> Settings:
        home_value = environ.get("CS2SCOUT_HOME")
        if home_value:
            home = Path(home_value)
        else:
            base = environ.get("LOCALAPPDATA")
            home = (Path(base) if base else Path.home()) / "CS2DemoScout"

        # The port: CS2SCOUT_PORT, else the one saved in Settings, else the default.
        port_value = environ.get("CS2SCOUT_PORT") or str(prefs.load(home).port or DEFAULT_PORT)
        try:
            port = int(port_value)
        except ValueError:
            raise ValueError(f"CS2SCOUT_PORT must be an integer, got {port_value!r}") from None
        if not 1 <= port <= 65535:
            raise ValueError(f"CS2SCOUT_PORT must be between 1 and 65535, got {port}")

        # The key may live in the environment or a .env file (workspace first, then cwd).
        dotenv = read_dotenv(Path.cwd() / ".env") | read_dotenv(home / ".env")

        def value(name: str) -> str | None:
            return environ.get(name) or dotenv.get(name) or None

        return cls(home=home, port=port, anthropic_api_key=value("ANTHROPIC_API_KEY"),
                   ai_model=value("CS2SCOUT_AI_MODEL") or DEFAULT_AI_MODEL)  # fmt: skip
