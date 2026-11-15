"""Render the shareable export: the app's own section templates in static mode (ADR-001).

One renderer, two modes: what a teammate sees is what the Analyst saw, minus the controls.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
from fastapi import Request

from cs2scout import __version__
from cs2scout.core.findings import RoundFilter
from cs2scout.export.inline import CSP, data_uri, filename, leaks
from cs2scout.store import assets
from cs2scout.web import api, pages
from cs2scout.web.figures import heatmap_figure

SECTIONS = {"overview": "Overview", "t": "T side", "ct": "CT side", "utility": "Utility",
            "players": "Players", "brief": "AI brief"}  # fmt: skip
STATIC = Path(__file__).parent / "static"
GALLERY = [("T", "early"), ("T", "mid"), ("T", "late"), ("T", "post_plant"), ("CT", "early"),
           ("CT", "mid"), ("CT", "late")]  # fmt: skip


class ExportLeak(RuntimeError):
    pass


def _radar_placeholders(spec: dict) -> dict:
    """App figures point at /radar/<name>.png; the export resolves radar://<name> inline."""
    for image in spec.get("layout", {}).get("images", []):
        source = image.get("source", "")
        if source.startswith("/radar/"):
            image["source"] = "radar://" + source.removeprefix("/radar/").removesuffix(".png")
    return spec


def _heat_gallery(request: Request, entry_id: int, snapshot: dict) -> list[dict]:
    vdir = request.app.state.library.current_version_dir(entry_id)
    if not snapshot["grids"] or not (vdir / "grids.parquet").exists():
        return []
    cells = pl.read_parquet(vdir / "grids.parquet")
    radar = snapshot.get("radar")
    out = []
    for side, phase in GALLERY:
        grid_id = f"team.{side}.{phase}"
        meta = snapshot["grids"].get(grid_id)
        if meta is None:
            continue
        url = f"radar://{radar['map']}" if radar and meta["space"] == "radar" else None
        figure = heatmap_figure(meta, cells.filter(pl.col("grid_id") == grid_id), url)
        out.append({"id": grid_id.replace(".", "-"), "side": side,
                    "phase": phase.replace("_", " "), "meta": meta, "figure": figure})  # fmt: skip
    return out


def render(request: Request, entry_id: int, sections: list[str], flt: RoundFilter
           ) -> tuple[str, str]:  # fmt: skip
    """(filename, html). Raises ExportLeak rather than ever writing personal data out."""
    entry = api.get_entry(entry_id, request)
    snapshot = pages._snapshot(request, entry_id, flt)
    if snapshot is None:
        raise api.ApiError(409, "NOT_COMPUTED", "this analysis has not been computed yet")
    chosen = [s for s in SECTIONS if s in sections] or list(SECTIONS)
    rendered = []
    brief = request.app.state.library.latest_brief(entry_id)
    for tab in chosen:
        if tab == "brief" and (brief is None or brief["stale"]):
            continue  # FR-EXP-3: only a brief that matches this analysis is shared
        ctx = pages._tab_context(request, entry, tab, flt)
        template = ctx.pop("template")
        for side in ctx.get("lineup_sides", []):
            if side["figure"]:
                side["figure"] = _radar_placeholders(side["figure"])
        if tab == "overview":
            ctx["heat_gallery"] = _heat_gallery(request, entry_id, snapshot)
        html = pages.templates.get_template(template).render(**ctx, static=True)
        rendered.append({"id": tab, "title": SECTIONS[tab], "html": html})

    home = request.app.state.settings.home
    radars = {}
    if snapshot.get("radar"):
        name = snapshot["radar"]["map"]
        for lower in (False, True):
            path = assets.radar_path(home, name, lower=lower)
            if path is not None:
                radars[name + ("_lower" if lower else "")] = data_uri(path)
    used = [d for d in snapshot["demos"] if d["used"]]
    active = api.active_filter(flt)
    page = pages.templates.get_template("export.html").render(
        csp=CSP, entry=entry, snapshot=snapshot, sections=rendered, demos=used,
        filter=active, version=__version__, radars=json.dumps(radars),
        generated=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        css=(STATIC / "app.css").read_text(encoding="utf-8"),
        plotly=(STATIC / "vendor" / "plotly-4.2.0.min.js").read_text(encoding="utf-8")
        .replace("</script", r"<\/script"),  # never end the inline script early
        script=(STATIC / "export.js").read_text(encoding="utf-8"),
    )  # fmt: skip
    problems = leaks(page)
    if problems:
        raise ExportLeak("export blocked: it would contain " + " and ".join(problems))
    return filename(entry["team"], entry["map"], "scouting"), page
