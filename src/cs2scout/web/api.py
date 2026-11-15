"""JSON API under /api (design §5.6). Every route here is behind the loopback guard.

SteamIDs travel as strings: they exceed JavaScript's safe integer range.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from cs2scout.core.errors import ErrorCode
from cs2scout.core.findings import RoundFilter
from cs2scout.jobs.analysis import run_recompute
from cs2scout.jobs.import_job import ImportOptions, run_import
from cs2scout.jobs.runner import JobConflict, JobContext
from cs2scout.web.errors import ApiError, not_found
from cs2scout.web.findings_view import filtered_snapshot

router = APIRouter(prefix="/api")
Lineup = Literal["A", "B"]
Buy = Literal["pistol", "eco", "force", "full"]


# ---------------------------------------------------------------- helpers


def _state(request: Request):
    return request.app.state


def _options(request: Request) -> ImportOptions:
    s = _state(request).settings
    return ImportOptions(adapter=s.adapter, retain_sources=s.retain_sources,
                         limits=s.archive_limits, parse_timeout_s=s.parse_timeout_s)  # fmt: skip


def _submit(request: Request, kind: str, fn, entry_id: int | None) -> str:
    try:
        return _state(request).runner.submit(kind, fn, entry_id=entry_id)
    except JobConflict as exc:
        raise ApiError(409, ErrorCode.CONFLICT_JOB_RUNNING, str(exc)) from exc


def _entry(request: Request, entry_id: int):
    entry = _state(request).library.get_entry(entry_id)
    if entry is None:
        raise not_found("entry")
    return entry


def _recompute_job(request: Request, entry_id: int) -> str:
    adapter = _state(request).settings.adapter
    return _submit(request, "recompute", lambda ctx: run_recompute(ctx, entry_id, adapter),
                   entry_id)  # fmt: skip


def _steamids(values: list[str]) -> list[int]:
    try:
        return [int(v) for v in values]
    except ValueError as exc:
        raise ApiError(422, ErrorCode.INVALID_REQUEST, "SteamIDs must be numeric strings") from exc


# ---------------------------------------------------------------- jobs


class ImportRequest(BaseModel):
    paths: list[str] = Field(min_length=1, description="Demo files or folders on this PC")
    entry_id: int | None = None


@router.post("/imports", status_code=202)
def start_import(body: ImportRequest, request: Request) -> dict:
    """Import demos. With ``entry_id`` this is J2 (add demos, then recompute)."""
    if body.entry_id is not None:
        return add_demos(body.entry_id, AddDemos(paths=body.paths), request)
    options = _options(request)
    job_id = _submit(request, "import", lambda ctx: run_import(ctx, body.paths, options), None)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, request: Request) -> dict:
    job = _state(request).library.get_job(job_id)
    if job is None:
        raise not_found("job")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, request: Request) -> dict:
    if _state(request).library.get_job(job_id) is None:
        raise not_found("job")
    return {"cancel_requested": _state(request).runner.cancel(job_id)}


# ---------------------------------------------------------------- entries


class CreateEntry(BaseModel):
    import_job_id: str
    team_name: str | None = Field(default=None, min_length=1, max_length=80)
    team_id: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    core: list[str] = Field(min_length=1, max_length=10)
    standins: list[str] = []
    excluded: list[str] = []
    lineup_overrides: dict[str, Lineup] = {}


@router.post("/entries", status_code=202)
def create_entry(body: CreateEntry, request: Request) -> dict:
    """J1 step 5: the Analyst confirms the roster; the entry is created and computed."""
    lib = _state(request).library
    job = lib.get_job(body.import_job_id)
    if job is None or job["kind"] != "import":
        raise not_found("import job")
    if job["state"] != "done" or not (job["result"] or {}).get("accepted"):
        raise ApiError(
            409, ErrorCode.IMPORT_NOT_READY, "the import has not finished or accepted no demos"
        )
    result = job["result"]
    nicks = {p["steamid"]: p["nick"] for p in result["roster_proposal"]["players"]}
    if body.team_id is not None:
        team = lib.get_team(body.team_id)
        if team is None:
            raise not_found("team")
        team_id, team_name = body.team_id, team["display_name"]
    elif body.team_name:
        team_id, team_name = None, body.team_name
    else:
        raise ApiError(422, ErrorCode.INVALID_REQUEST, "give team_name or team_id")
    roles = ([(s, "core") for s in body.core] + [(s, "standin") for s in body.standins]
             + [(s, "excluded") for s in body.excluded])  # fmt: skip
    _steamids([s for s, _ in roles])
    players = [(int(s), role, nicks.get(s)) for s, role in roles]
    try:
        team_id = team_id or lib.create_team(team_name)
        entry_id = lib.create_entry(
            team_id, result["map"], body.name or f"{team_name} - {result['map']}"
        )
    except sqlite3.IntegrityError as exc:
        raise ApiError(
            409, ErrorCode.ENTRY_EXISTS, "this team already has an analysis for this map"
        ) from exc
    lib.set_roster(team_id, players)
    lib.add_entry_demos(entry_id, result["accepted"])
    for sha, lineup in body.lineup_overrides.items():
        lib.set_entry_demo(entry_id, sha, lineup_override=lineup)
    return {"entry_id": entry_id, "team_id": team_id, "job_id": _recompute_job(request, entry_id)}


def _entry_json(request: Request, entry) -> dict:
    lib = _state(request).library
    demos = lib.entry_demos(entry.entry_id)
    dates = [d["played_at"] for d in demos if d["played_at"]]
    return {
        "id": entry.entry_id, "name": entry.name, "map": entry.map, "team_id": entry.team_id,
        "team": lib.get_team(entry.team_id)["display_name"], "version": entry.current_version,
        "updated_at": entry.updated_at, "demo_count": len(demos),
        "included_count": sum(1 for d in demos if d["included"]),
        "date_range": [min(dates), max(dates)] if dates else None,
        "busy": _state(request).runner.busy(entry.entry_id),
    }  # fmt: skip


@router.get("/entries")
def list_entries(request: Request) -> list[dict]:
    return [_entry_json(request, e) for e in _state(request).library.list_entries()]


@router.get("/entries/{entry_id}")
def get_entry(entry_id: int, request: Request) -> dict:
    entry = _entry(request, entry_id)
    lib = _state(request).library
    return _entry_json(request, entry) | {
        "demos": [{"sha256": d["sha256"], "label": d["sha256"][:8], "played_at": d["played_at"],
                   "rounds": d["rounds"], "included": bool(d["included"]),
                   "lineup_override": d["lineup_override"],
                   "file": (d["original_path"] or "").replace("\\", "/").rsplit("/", 1)[-1]}
                  for d in lib.entry_demos(entry_id)],
        "roster": [{"steamid": str(r["steamid"]), "role": r["role"], "nick": r["last_nick"]}
                   for r in lib.roster(entry.team_id)],
    }  # fmt: skip


class RenameEntry(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.patch("/entries/{entry_id}")
def rename_entry(entry_id: int, body: RenameEntry, request: Request) -> dict:
    _entry(request, entry_id)
    _state(request).library.rename_entry(entry_id, body.name)
    return get_entry(entry_id, request)


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: int, request: Request, confirm: Annotated[str, Query()]) -> dict:
    """FR-LIB-2: deleting needs the entry's name typed back as ``confirm``."""
    entry = _entry(request, entry_id)
    if confirm != entry.name:
        raise ApiError(
            409, ErrorCode.CONFIRMATION_MISMATCH, "type the analysis name exactly to delete it"
        )
    if _state(request).runner.busy(entry_id):
        raise ApiError(409, ErrorCode.CONFLICT_JOB_RUNNING, "wait for the running job to finish")
    _state(request).library.delete_entry(entry_id)
    return {"deleted": entry_id}


class AddDemos(BaseModel):
    paths: list[str] = Field(min_length=1)


@router.post("/entries/{entry_id}/demos", status_code=202)
def add_demos(entry_id: int, body: AddDemos, request: Request) -> dict:
    """J2: import into the entry, then recompute in the same job."""
    _entry(request, entry_id)
    options, adapter = _options(request), _state(request).settings.adapter

    def job(ctx: JobContext) -> dict:
        imported = run_import(ctx, body.paths, options, entry_id=entry_id)
        if not imported["accepted"]:
            return {"import": imported, "recompute": None}
        return {"import": imported, "recompute": run_recompute(ctx, entry_id, adapter)}

    return {"job_id": _submit(request, "add_demos", job, entry_id)}


class DemoChange(BaseModel):
    included: bool | None = None
    lineup: Lineup | None = None
    clear_lineup: bool = False
    played_on: date | None = Field(default=None, description="Corrected match date")


@router.patch("/entries/{entry_id}/demos/{sha256}", status_code=202)
def change_demo(entry_id: int, sha256: str, body: DemoChange, request: Request) -> dict:
    """Include/exclude a demo or assign the team's lineup in it (FR-TEAM-3)."""
    _entry(request, entry_id)
    lib = _state(request).library
    if sha256 not in {d["sha256"] for d in lib.entry_demos(entry_id)}:
        raise not_found("demo in this analysis")
    lib.set_entry_demo(entry_id, sha256, included=body.included, lineup_override=body.lineup,
                       clear_override=body.clear_lineup)  # fmt: skip
    if body.played_on is not None:
        lib.set_played_at(sha256, f"{body.played_on.isoformat()}T00:00:00+00:00")
    return {"job_id": _recompute_job(request, entry_id)}


class Roster(BaseModel):
    core: list[str] = Field(min_length=1, max_length=10)
    standins: list[str] = []
    excluded: list[str] = []


@router.put("/entries/{entry_id}/roster", status_code=202)
def put_roster(entry_id: int, body: Roster, request: Request) -> dict:
    entry = _entry(request, entry_id)
    lib = _state(request).library
    nicks = {r["steamid"]: r["last_nick"] for r in lib.roster(entry.team_id)}
    roles = ([(s, "core") for s in _steamids(body.core)]
             + [(s, "standin") for s in _steamids(body.standins)]
             + [(s, "excluded") for s in _steamids(body.excluded)])  # fmt: skip
    lib.set_roster(entry.team_id, [(s, role, nicks.get(s)) for s, role in roles])
    return {"job_id": _recompute_job(request, entry_id)}


@router.post("/entries/{entry_id}/recompute", status_code=202)
def recompute(entry_id: int, request: Request) -> dict:
    _entry(request, entry_id)
    return {"job_id": _recompute_job(request, entry_id)}


# ---------------------------------------------------------------- findings


def _version_dir(request: Request, entry_id: int):
    _entry(request, entry_id)
    vdir = _state(request).library.current_version_dir(entry_id)
    if vdir is None:
        raise ApiError(409, ErrorCode.NOT_COMPUTED, "this analysis has not been computed yet")
    return vdir


@router.get("/entries/{entry_id}/findings")
def get_findings(
    entry_id: int, request: Request,
    side: Literal["T", "CT"] | None = None,
    buy: Annotated[list[Buy], Query()] = [],  # noqa: B006 - FastAPI copies defaults
    opp_buy: Annotated[list[Buy], Query()] = [],  # noqa: B006
    demos: Annotated[list[str], Query()] = [],  # noqa: B006
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    ot: bool = True,
) -> dict:  # fmt: skip
    flt = RoundFilter(side=side, buy=tuple(sorted(buy)), opp_buy=tuple(sorted(opp_buy)),
                      demos=tuple(sorted(demos)), date_from=date_from, date_to=date_to,
                      include_ot=ot)  # fmt: skip
    return filtered_snapshot(_version_dir(request, entry_id), flt)


@router.get("/entries/{entry_id}/rounds")
def get_rounds(
    entry_id: int,
    request: Request,
    refs: Annotated[list[str], Query()] = [],  # noqa: B006
) -> list[dict]:
    """FR-CONF-3: the rounds behind a finding (demo, round number, score)."""
    rounds = filtered_snapshot(_version_dir(request, entry_id), RoundFilter())["round_index"]
    wanted = set(refs)
    return [r for r in rounds if not wanted or r["ref"] in wanted]
