"""Command line.

uv run cs2scout                  start the local server (default)
uv run cs2scout assets fetch     download and verify the pinned map radar pack (one-time)
uv run cs2scout assets status    show which maps have radar images installed
"""

from __future__ import annotations

import argparse
import secrets
from collections.abc import Sequence

from cs2scout import __version__
from cs2scout.settings import LOOPBACK_HOST, Settings


def _serve(settings: Settings, open_browser: bool) -> int:
    import threading
    import webbrowser

    import uvicorn

    from cs2scout.web.app import create_app

    app = create_app(settings, token=secrets.token_urlsafe(32))
    url = f"http://{LOOPBACK_HOST}:{settings.port}"
    print(f"CS2 Demo Scout {__version__}: {url}")
    print(f"Workspace: {settings.home}")
    if open_browser:
        threading.Timer(1.5, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=LOOPBACK_HOST, port=settings.port, log_level="info")
    return 0


def _assets(settings: Settings, action: str) -> int:
    from cs2scout.store import assets

    if action == "fetch":
        print(f"Downloading awpy-data release {assets.RELEASE} (radar images, map data)...")
        try:
            report = assets.fetch(settings.home)
        except (assets.AssetError, OSError) as exc:
            print(f"Failed: {exc}")
            return 1
        print(f"{report['status']}: {len(report['maps'])} maps with radar images")
    else:
        maps = assets.available_maps(settings.home)
        state = f"release {assets.RELEASE}, {len(maps)} maps" if maps else "not installed"
        print(f"Map assets: {state}")
        if maps:
            print("  " + ", ".join(maps))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cs2scout",
        description="CS2 Demo Scout. Configure with CS2SCOUT_HOME and CS2SCOUT_PORT.",
    )
    parser.add_argument("--version", action="version", version=f"cs2scout {__version__}")
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="start the local server (default)")
    serve.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    assets_cmd = commands.add_parser("assets", help="map radar images and coordinates")
    assets_cmd.add_argument("action", choices=["fetch", "status"])
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.command == "assets":
        return _assets(settings, args.action)
    return _serve(settings, open_browser=not getattr(args, "no_browser", False))


if __name__ == "__main__":
    raise SystemExit(main())
