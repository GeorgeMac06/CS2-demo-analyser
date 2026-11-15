"""`uv run cs2scout` / `python -m cs2scout`: start the local server."""

from __future__ import annotations

import argparse
import secrets
from collections.abc import Sequence

import uvicorn

from cs2scout import __version__
from cs2scout.settings import LOOPBACK_HOST, Settings
from cs2scout.store.workspace import init_workspace
from cs2scout.web.app import create_app


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cs2scout",
        description="CS2 Demo Scout local server. Configure with CS2SCOUT_HOME and CS2SCOUT_PORT.",
    )
    parser.add_argument("--version", action="version", version=f"cs2scout {__version__}")
    parser.parse_args(argv)

    settings = Settings.from_env()
    init_workspace(settings.home)
    app = create_app(settings, token=secrets.token_urlsafe(32))

    print(f"CS2 Demo Scout {__version__}: http://{LOOPBACK_HOST}:{settings.port}")
    print(f"Workspace: {settings.home}")
    uvicorn.run(app, host=LOOPBACK_HOST, port=settings.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
