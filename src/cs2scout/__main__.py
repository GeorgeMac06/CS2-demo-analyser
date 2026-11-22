"""Command line.

uv run cs2scout                  start the local server (default)
uv run cs2scout assets fetch     download and verify the pinned map radar pack (one-time)
uv run cs2scout assets status    show which maps have radar images installed
uv run cs2scout free-space       list parsed data and demo copies no analysis uses, then remove
                                 them after you confirm (--yes: without asking)
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


def _free_space(settings: Settings, assume_yes: bool) -> int:
    from cs2scout.store import cleanup
    from cs2scout.store.library import Library
    from cs2scout.store.workspace import readable

    lib = Library(settings.home)
    report = cleanup.unused(lib)
    print(f"Workspace: {settings.home}")
    if report["busy"]:
        print("An import is running. Try again when it has finished. If the app was closed "
              "during an import, start it once to clear it.")  # fmt: skip
        return 1
    kept = report["kept"]
    note = f"Kept: {kept} demo(s) from an import waiting for its roster to be confirmed."
    if not report["demos"] and not report["folders"]:
        print("Nothing to remove. Every demo in the workspace belongs to an analysis.")
        if kept:
            print(note)
        return 0
    print("No analysis uses these:")
    for d in report["demos"]:
        date = (d["played_at"] or "")[:10] or "?"
        print(f"  {date:<10}  {d['map']:<12} {readable(d['bytes']):>9}  {d['file']}")
    for f in report["folders"]:
        print(f"  leftover folder {f['path']}  {readable(f['bytes'])}")
    if kept:
        print(note)
    print(f"Removing them frees {readable(report['total_bytes'])}.")
    if not assume_yes and input("Remove them? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Nothing removed.")
        return 0
    try:
        result = cleanup.free(lib, [d["sha256"] for d in report["demos"]],
                              [f["path"] for f in report["folders"]])  # fmt: skip
    except cleanup.StorageBusy:
        print("An import started. Nothing removed; try again when it has finished.")
        return 1
    print(f"Freed {readable(result['freed_bytes'])}: removed {result['removed_demos']} demo(s)"
          f" and {result['removed_folders']} leftover folder(s).")  # fmt: skip
    for path in result["left"]:
        print(f"  still there (a file is in use): {path}")
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
    free = commands.add_parser(
        "free-space", help="remove parsed data and demo copies no analysis uses"
    )
    free.add_argument("--yes", action="store_true", help="remove without asking")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.command == "assets":
        return _assets(settings, args.action)
    if args.command == "free-space":
        return _free_space(settings, args.yes)
    return _serve(settings, open_browser=not getattr(args, "no_browser", False))


if __name__ == "__main__":
    raise SystemExit(main())
