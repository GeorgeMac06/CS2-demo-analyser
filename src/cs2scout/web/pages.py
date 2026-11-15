"""HTML pages and htmx fragments (journeys J1-J3; design §5.6, ADR-001).

Pages are plain GET routes. Every state change is an htmx POST, so it carries the session
token header and passes the Origin check. Business rules live in ``api`` and the core; this
module only gathers data for templates and turns API errors into readable messages.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import polars as pl
from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from cs2scout import __version__
from cs2scout.core.findings import RoundFilter
from cs2scout.core.grids import PHASES
from cs2scout.ingest.files import is_candidate
from cs2scout.jobs.import_job import run_import
from cs2scout.store import assets
from cs2scout.store.library import TMP_PREFIX
from cs2scout.web import api
from cs2scout.web.errors import ApiError
from cs2scout.web.figures import heatmap_figure, lineups_figure, tempo_figure, winrate_figure
from cs2scout.web.findings_view import filtered_snapshot

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
TABS = ("overview", "t", "ct", "utility", "players", "demos")
BUYS = ("pistol", "eco", "force", "full")
ROLES = ("core", "standin", "excluded")


def _page(request: Request, name: str, **context) -> HTMLResponse:
    context |= {"token": request.app.state.token, "version": __version__}
    return templates.TemplateResponse(request, name, context)


def _error(request: Request, message: str) -> HTMLResponse:
    return _page(request, "_error.html", message=message)


def _redirect(url: str) -> Response:
    return Response(headers={"HX-Redirect": url})


def _filter(request: Request) -> RoundFilter:
    q = request.query_params
    submitted = "f" in q  # the filter form was used: an unticked box means "exclude"
    return RoundFilter(
        side=q.get("side") or None,
        buy=tuple(sorted(v for v in q.getlist("buy") if v in BUYS)),
        opp_buy=tuple(sorted(v for v in q.getlist("opp_buy") if v in BUYS)),
        demos=tuple(sorted(q.getlist("demos"))),
        date_from=q.get("from") or None,
        date_to=q.get("to") or None,
        include_ot=("ot" in q) if submitted else True,
    )


def _snapshot(request: Request, entry_id: int, flt: RoundFilter | None = None) -> dict | None:
    vdir = request.app.state.library.current_version_dir(entry_id)
    if vdir is None:
        return None
    return api.labelled(request, entry_id, filtered_snapshot(vdir, flt or RoundFilter()))


# ---------------------------------------------------------------- library and import


@router.get("/", response_class=HTMLResponse)
def library_page(request: Request) -> HTMLResponse:
    entries = api.list_entries(request)
    return _page(request, "library.html", entries=entries,
                 assets_ok=assets.installed(request.app.state.settings.home))  # fmt: skip


@router.get("/new", response_class=HTMLResponse)
def new_page(request: Request) -> HTMLResponse:
    return _page(request, "new.html", entry=None)


@router.get("/entries/{entry_id}/add", response_class=HTMLResponse)
def add_page(entry_id: int, request: Request) -> HTMLResponse:
    return _page(request, "new.html", entry=api.get_entry(entry_id, request))


@router.post("/ui/imports", response_class=HTMLResponse)
async def ui_import(request: Request) -> HTMLResponse:
    form = await request.form()
    paths = [line.strip().strip('"') for line in str(form.get("paths", "")).splitlines()]
    paths = [p for p in paths if p]
    entry_id = int(form["entry_id"]) if form.get("entry_id") else None
    if not paths:
        return _error(request, "Enter at least one demo file or folder path.")
    try:
        if entry_id is None:
            job = api.start_import(api.ImportRequest(paths=paths), request)
        else:
            job = api.add_demos(entry_id, api.AddDemos(paths=paths), request)
    except ApiError as exc:
        return _error(request, exc.message)
    then = f"/entries/{entry_id}" if entry_id else ""
    return _page(request, "_job.html", job=api.get_job(job["job_id"], request), then=then)


@router.post("/ui/uploads", response_class=HTMLResponse)
async def ui_upload(request: Request) -> HTMLResponse:
    """Drag-and-drop import: files are saved to workspace scratch, imported, then removed."""
    form = await request.form()
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename]
    entry_id = int(form["entry_id"]) if form.get("entry_id") else None
    state = request.app.state
    folder = state.settings.home / "tmp" / f"{TMP_PREFIX}upload-{uuid.uuid4().hex}"
    folder.mkdir(parents=True)
    saved = 0
    for upload in files:
        name = Path(upload.filename.replace("\\", "/")).name  # never trust a client path
        if not is_candidate(Path(name)):
            continue
        with (folder / name).open("wb") as out:
            shutil.copyfileobj(upload.file, out, 1 << 20)
        saved += 1
    if not saved:
        shutil.rmtree(folder, ignore_errors=True)
        return _error(request, "No .dem, .dem.gz, .dem.bz2 or .zip files were dropped.")
    options = api._options(request)
    adapter = state.settings.adapter

    def job(ctx):
        try:
            imported = run_import(ctx, [str(folder)], options, entry_id=entry_id)
            if entry_id is None or not imported["accepted"]:
                return imported if entry_id is None else {"import": imported, "recompute": None}
            return {"import": imported,
                    "recompute": api.run_recompute(ctx, entry_id, adapter)}  # fmt: skip
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    try:
        job_id = api._submit(request, "import" if entry_id is None else "add_demos", job,
                             entry_id)  # fmt: skip
    except ApiError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        return _error(request, exc.message)
    then = f"/entries/{entry_id}" if entry_id else ""
    return _page(request, "_job.html", job=api.get_job(job_id, request), then=then)


@router.get("/ui/jobs/{job_id}", response_class=HTMLResponse)
def ui_job(job_id: str, request: Request, then: str = "") -> Response:
    job = api.get_job(job_id, request)
    if job["state"] == "done" and job["kind"] == "import":
        return _roster_form(request, job)
    if job["state"] == "done" and then.startswith("/"):
        return _redirect(then)
    return _page(request, "_job.html", job=job, then=then)


def _roster_form(request: Request, job: dict) -> HTMLResponse:
    result = job["result"]
    if not result.get("accepted"):
        return _page(request, "_import_report.html", job=job, result=result)
    proposal = result["roster_proposal"]
    nicks = {p["steamid"]: p["nick"] for p in proposal["players"]}
    demos = [d | {"lineup_nicks": {lu: [nicks.get(s, s) for s in m]
                                   for lu, m in d["lineups"].items()}}
             for d in result.get("demos", [])]  # fmt: skip
    return _page(request, "_roster_form.html", job=job, result=result, proposal=proposal,
                 demos=demos, teams=request.app.state.library.list_teams())  # fmt: skip


@router.post("/ui/entries", response_class=HTMLResponse)
async def ui_create_entry(request: Request) -> Response:
    form = await request.form()
    roles = {k[5:]: v for k, v in form.items() if k.startswith("role_") and v in ROLES}
    overrides = {k[7:]: v for k, v in form.items() if k.startswith("lineup_") and v in ("A", "B")}
    team_id = int(form["team_id"]) if form.get("team_id") else None
    body = api.CreateEntry.model_construct(
        import_job_id=str(form.get("job_id", "")),
        team_name=(str(form.get("team_name", "")).strip() or None) if team_id is None else None,
        team_id=team_id, name=None,
        core=[s for s, r in roles.items() if r == "core"],
        standins=[s for s, r in roles.items() if r == "standin"],
        excluded=[s for s, r in roles.items() if r == "excluded"],
        lineup_overrides=overrides,
    )  # fmt: skip
    if not body.core:
        return _error(request, "Mark at least one player as core.")
    try:
        created = api.create_entry(body, request)
    except ApiError as exc:
        return _error(request, exc.message)
    job = api.get_job(created["job_id"], request)
    return _page(request, "_job.html", job=job, then=f"/entries/{created['entry_id']}")


# ---------------------------------------------------------------- entry page


@router.get("/entries/{entry_id}", response_class=HTMLResponse)
def entry_page(entry_id: int, request: Request, tab: str = "overview") -> HTMLResponse:
    entry = api.get_entry(entry_id, request)
    tab = tab if tab in TABS else "overview"
    snapshot = _snapshot(request, entry_id)
    tab_ctx = _tab_context(request, entry, tab, RoundFilter())
    tab_template = tab_ctx.pop("template")
    vdir = request.app.state.library.current_version_dir(entry_id)
    # Built before pattern mining existed (or by an older format): offer a recompute.
    outdated = vdir is not None and not (vdir / "patterns.json").exists()
    return _page(request, "entry.html", **(tab_ctx | {"entry": entry, "tab": tab,
                 "snapshot": snapshot, "buys": BUYS, "tab_template": tab_template,
                 "outdated": outdated}))  # fmt: skip


@router.get("/ui/entries/{entry_id}/tab/{tab}", response_class=HTMLResponse)
def ui_tab(entry_id: int, tab: str, request: Request) -> HTMLResponse:
    entry = api.get_entry(entry_id, request)
    ctx = _tab_context(request, entry, tab if tab in TABS else "overview", _filter(request))
    return _page(request, ctx.pop("template"), **ctx)


def _tab_context(request: Request, entry: dict, tab: str, flt: RoundFilter) -> dict:
    snapshot = _snapshot(request, entry["id"], flt)
    ctx = {"template": f"_tab_{tab}.html", "entry": entry, "snapshot": snapshot, "tab": tab,
           "filter": flt}  # fmt: skip
    if snapshot is None:
        return ctx | {"template": "_not_computed.html"}
    findings = {f["id"]: f for f in snapshot["findings"]}
    if tab == "overview":
        rows = sorted(
            (f for f in snapshot["findings"] if f["kind"] == "team.winrate"),
            key=lambda f: (f["params"]["side"], BUY_INDEX[f["params"]["buy"]]),
        )
        ctx |= {"winrates": rows, "winrate_fig": winrate_figure(snapshot["findings"]),
                "heat": _heat_choices(snapshot, "team")}  # fmt: skip
    elif tab in ("t", "ct", "utility"):
        ctx |= _pattern_context(snapshot, tab)
    elif tab == "players":
        side = flt.side or "all"
        ctx |= {"side": side, "players": [
            {"member": m, "stats": findings.get(f"plr.stats.{m['player_key']}.{side}"),
             "open": findings.get(f"plr.openings.{m['player_key']}.{side}"),
             "util": findings.get(f"util.player.{m['player_key']}.{side}")}
            for m in snapshot["roster"]
        ], "heat": _heat_choices(snapshot, snapshot["roster"][0]["player_key"]
                                 if snapshot["roster"] else "team")}  # fmt: skip
        ctx |= _player_patterns(snapshot)
    return ctx


def _visible(findings: list[dict], kind: str) -> list[dict]:
    """A kind's findings that pass support, strongest first (FR-CONF-1)."""
    shown = [f for f in findings if f["kind"] == kind and "below_support" not in f["flags"]]
    return sorted(shown, key=lambda f: (-f["support"]["k"], f["id"]))


def _weaker(findings: list[dict], prefix: str) -> list[dict]:
    weak = [f for f in findings if f["kind"].startswith(prefix) and "below_support" in f["flags"]]
    return sorted(weak, key=lambda f: (-f["support"]["k"], f["id"]))


def _pattern_context(snapshot: dict, tab: str) -> dict:
    f = snapshot["findings"]
    nicks = {m["player_key"]: m["nick"] for m in snapshot["roster"]}
    if tab == "t":
        tempo = next((x for x in f if x["kind"] == "ts.tempo"), None)
        return {"nicks": nicks, "sites": _visible(f, "ts.site"), "tempos": _visible(f, "ts.tempo"),
                "tempo_fig": tempo_figure(tempo["params"]["hit_times_s"]) if tempo else None,
                "strategies": _visible(f, "ts.strategy"), "setups": _visible(f, "ts.setup"),
                "buy_rounds": _visible(f, "ts.buy"), "postplants": _visible(f, "ts.postplant"),
                "fakes": _visible(f, "ts.fake"), "weaker": _weaker(f, "ts.")}  # fmt: skip
    if tab == "ct":
        return {"nicks": nicks, "stacks": _visible(f, "ct.stack"),
                "setups": _visible(f, "ct.setup"),
                "positions": _visible(f, "ct.position"), "rotations": _visible(f, "ct.rotation"),
                "duels": _visible(f, "ct.aggression"), "retakes": _visible(f, "ct.retake"),
                "saves": _visible(f, "ct.save"), "weaker": _weaker(f, "ct.")}  # fmt: skip
    lineups = _visible(f, "util.lineup")
    radar = snapshot.get("radar")
    url = f"/radar/{radar['map']}.png" if radar else None
    sides = []
    for side in ("T", "CT"):
        mine = [x for x in lineups if x["params"]["side"] == side]
        top = mine[:LINEUPS_ON_MAP]
        sides.append({"side": side, "top": top, "more": mine[LINEUPS_ON_MAP:],
                      "figure": lineups_figure(top, radar, url) if top else None})  # fmt: skip
    return {"nicks": nicks, "lineup_sides": sides, "weaker": _weaker(f, "util.lineup")}


def _player_patterns(snapshot: dict) -> dict:
    f = snapshot["findings"]
    by_player: dict[str, dict[str, list[dict]]] = {}
    for kind in ("plr.habit", "plr.weapon", "plr.clutch"):
        for x in _visible(f, kind):
            by_player.setdefault(x["subject"], {}).setdefault(kind, []).append(x)
    roles = {x["subject"]: x for x in f if x["kind"] == "plr.role"}
    return {"roles": roles, "habits": by_player}


BUY_INDEX = {b: i for i, b in enumerate(("all", *BUYS))}
LINEUPS_ON_MAP = 10


def _heat_choices(snapshot: dict, subject: str) -> dict:
    levels = sorted({g["level"] for g in snapshot["grids"].values()})
    return {"subject": subject, "side": "T", "phase": "early", "level": "default",
            "phases": PHASES, "levels": levels, "has_grids": bool(snapshot["grids"]),
            "subjects": [("team", "Whole team")] + [(m["player_key"], m["nick"])
                                                    for m in snapshot["roster"]]}  # fmt: skip


@router.get("/ui/entries/{entry_id}/heatmap", response_class=HTMLResponse)
def ui_heatmap(entry_id: int, request: Request, subject: str = "team", side: str = "T",
               phase: str = "early", level: str = "default") -> HTMLResponse:  # fmt: skip
    vdir = request.app.state.library.current_version_dir(entry_id)
    snapshot = _snapshot(request, entry_id)
    if vdir is None or snapshot is None:
        return _error(request, "This analysis has not been computed yet.")
    grid_id = f"{subject}.{side}.{phase}" + (".lower" if level == "lower" else "")
    meta = snapshot["grids"].get(grid_id)
    if meta is None:
        return _page(request, "_heatmap.html", meta=None, figure=None, grid_id=grid_id)
    cells = pl.read_parquet(vdir / "grids.parquet").filter(pl.col("grid_id") == grid_id)
    radar = snapshot.get("radar")
    url = None
    if radar and meta["space"] == "radar":
        lower = level == "lower" and radar.get("has_lower_image")
        url = f"/radar/{radar['map']}{'_lower' if lower else ''}.png"
    return _page(request, "_heatmap.html", meta=meta, grid_id=grid_id,
                 figure=heatmap_figure(meta, cells, url))  # fmt: skip


@router.get("/radar/{name}.png")
def radar_image(name: str, request: Request) -> FileResponse:
    map_name, lower = (name[:-6], True) if name.endswith("_lower") else (name, False)
    path = assets.radar_path(request.app.state.settings.home, map_name, lower=lower)
    if path is None:
        raise ApiError(404, "NOT_FOUND", "no radar image for this map")
    return FileResponse(path, media_type="image/png")


@router.get("/ui/entries/{entry_id}/rounds", response_class=HTMLResponse)
def ui_rounds(entry_id: int, request: Request, title: str = "Rounds") -> HTMLResponse:
    refs = request.query_params.getlist("refs")
    rounds = api.get_rounds(entry_id, request, refs=refs)
    return _page(request, "_rounds.html", rounds=rounds, title=title)


# ---------------------------------------------------------------- entry changes


def _job_or_error(request: Request, call, then: str) -> HTMLResponse:
    try:
        started = call()
    except ApiError as exc:
        return _error(request, exc.message)
    return _page(request, "_job.html", job=api.get_job(started["job_id"], request), then=then)


@router.post("/ui/entries/{entry_id}/demos/{sha256}", response_class=HTMLResponse)
async def ui_change_demo(entry_id: int, sha256: str, request: Request) -> HTMLResponse:
    form = await request.form()
    lineup = form.get("lineup")
    change = api.DemoChange(
        included="included" in form if form.get("has_included") else None,
        lineup=lineup if lineup in ("A", "B") else None,
        clear_lineup=lineup == "auto",
        played_on=form.get("played_on") or None,
    )
    return _job_or_error(request, lambda: api.change_demo(entry_id, sha256, change, request),
                         f"/entries/{entry_id}?tab=demos")  # fmt: skip


@router.post("/ui/entries/{entry_id}/recompute", response_class=HTMLResponse)
def ui_recompute(entry_id: int, request: Request) -> HTMLResponse:
    return _job_or_error(request, lambda: api.recompute(entry_id, request), f"/entries/{entry_id}")


@router.post("/ui/entries/{entry_id}/roster", response_class=HTMLResponse)
async def ui_roster(entry_id: int, request: Request) -> HTMLResponse:
    form = await request.form()
    roles = {k[5:]: v for k, v in form.items() if k.startswith("role_") and v in ROLES}
    if not any(r == "core" for r in roles.values()):
        return _error(request, "Keep at least one core player.")
    body = api.Roster(core=[s for s, r in roles.items() if r == "core"],
                      standins=[s for s, r in roles.items() if r == "standin"],
                      excluded=[s for s, r in roles.items() if r == "excluded"])  # fmt: skip
    return _job_or_error(request, lambda: api.put_roster(entry_id, body, request),
                         f"/entries/{entry_id}?tab=players")  # fmt: skip


@router.post("/ui/entries/{entry_id}/rename")
async def ui_rename(entry_id: int, request: Request) -> Response:
    name = str((await request.form()).get("name", "")).strip()
    if not name:
        return _error(request, "The name cannot be empty.")
    api.rename_entry(entry_id, api.RenameEntry(name=name[:120]), request)
    return Response(headers={"HX-Refresh": "true"})


@router.post("/ui/entries/{entry_id}/delete")
async def ui_delete(entry_id: int, request: Request) -> Response:
    confirm = str((await request.form()).get("confirm", ""))
    try:
        api.delete_entry(entry_id, request, confirm=confirm)
    except ApiError as exc:
        return _error(request, exc.message)
    return _redirect("/")


@router.post("/ui/entries/{entry_id}/labels/{finding_id}", response_class=HTMLResponse)
async def ui_label(entry_id: int, finding_id: str, request: Request) -> HTMLResponse:
    text = str((await request.form()).get("label", ""))[:80]
    try:
        saved = api.put_label(entry_id, finding_id, api.Label(label=text), request)
    except ApiError as exc:
        return _error(request, exc.message)
    response = _page(request, "_label_saved.html", label=saved["label"])
    response.headers["HX-Trigger"] = "labels-changed"  # the open tab reloads with the name
    return response


@router.get("/ui/entries/{entry_id}/export")
def ui_export(entry_id: int, request: Request) -> Response:
    """Download the shareable brief (FR-EXP-1). Sections and filters come from the query."""
    from cs2scout.web.export_view import ExportLeak, render

    sections = request.query_params.getlist("sections")
    try:
        name, html = render(request, entry_id, sections, _filter(request))
    except (ApiError, ExportLeak) as exc:
        return _error(request, getattr(exc, "message", str(exc)))
    return Response(html, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})  # fmt: skip
