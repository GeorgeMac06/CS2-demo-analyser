"""Import demos (journeys J1 and J2; design §6.1).

Phase 1 checks every file (archive, magic bytes, hash, duplicates, header). Phase 2 picks the
map. Phase 3 extracts the accepted demos one at a time and records them. A cancel keeps the
extracts that already finished (J1 alternative) and creates no entry.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from cs2scout.core.errors import ErrorCode
from cs2scout.core.schema import EXTRACT_SCHEMA
from cs2scout.ingest.files import (
    ArchiveRejected,
    Limits,
    NotCS2,
    check_magic,
    discover,
    file_time,
    match_key,
    materialize,
    retain_source,
    sha256_file,
)
from cs2scout.jobs.analysis import demo_summary, load_demos, roster_proposal
from cs2scout.jobs.extract_worker import adapter_identity, run_extract, run_probe
from cs2scout.jobs.runner import JobCancelled, JobContext
from cs2scout.store.library import TMP_PREFIX, Library


@dataclass(frozen=True)
class ImportOptions:
    adapter: str
    retain_sources: bool = True
    limits: Limits = field(default_factory=Limits)
    parse_timeout_s: float = 15 * 60


@dataclass
class _Candidate:
    source: Path
    report: dict
    dem: Path | None = None
    temporary: bool = False
    sha256: str | None = None
    map_name: str | None = None
    known: bool = False  # already in the library


def run_import(ctx: JobContext, paths: list[str], options: ImportOptions,
               entry_id: int | None = None) -> dict:  # fmt: skip
    lib = ctx.library
    files, skipped = discover(paths)
    entry = lib.get_entry(entry_id) if entry_id is not None else None
    in_entry = {row["sha256"] for row in lib.entry_demos(entry_id)} if entry else set()
    parser, parser_version = adapter_identity(options.adapter)
    candidates = [_Candidate(f, {"file": f.name, "status": "pending"}) for f in files]
    try:
        _check_files(ctx, lib, candidates, options, in_entry)
        map_name = _choose_map(candidates, entry.map if entry else None)
        accepted = _extract_all(ctx, lib, candidates, options, parser, parser_version, in_entry)
    finally:
        for c in candidates:
            if c.temporary and c.dem is not None:
                c.dem.unlink(missing_ok=True)
    if entry is not None and accepted:
        lib.add_entry_demos(entry.entry_id, accepted)
    result = {
        "map": map_name,
        "accepted": accepted,
        "files": [c.report for c in candidates],
        "skipped": skipped,
    }
    if accepted:
        demos, _ = load_demos(None, lib, accepted, options.adapter, full=False)
        summaries = {d.sha256: demo_summary(d) for d in demos}
        for c in candidates:
            s = summaries.get(c.sha256) if c.report["status"] == "accepted" else None
            if s is None:
                continue
            c.report.update(rounds=s["rounds"], score=s["score"], complete=s["complete"])
            if not s["complete"]:  # FR-IN-5: accepted, but flagged with its round count
                message = f"incomplete match ({s['rounds']} rounds, {s['score']})"
                c.report.update(code=str(ErrorCode.INCOMPLETE_MATCH), message=message)
        result["demos"] = [summaries[s] for s in accepted if s in summaries]
        if entry is None:  # J1: propose the scouted team for the Analyst to confirm
            result["roster_proposal"] = roster_proposal(demos)
    return result


def _reject(c: _Candidate, code: ErrorCode, message: str) -> None:
    c.report.update(status="rejected", code=str(code), message=message)


def _check_files(ctx: JobContext, lib: Library, candidates: list[_Candidate],
                 options: ImportOptions, in_entry: set[str]) -> None:  # fmt: skip
    seen: set[str] = set()
    for i, c in enumerate(candidates):
        ctx.check_cancel()
        ctx.progress(phase="checking", done=i, total=len(candidates))
        try:
            c.dem, c.temporary = materialize(c.source, lib.home / "tmp", options.limits, TMP_PREFIX)
            check_magic(c.dem)
        except ArchiveRejected as exc:
            _reject(c, ErrorCode.ARCHIVE_REJECTED, str(exc))
            continue
        except NotCS2 as exc:
            _reject(c, ErrorCode.NOT_CS2, str(exc))
            continue
        c.sha256 = sha256_file(c.dem)
        c.report["sha256"] = c.sha256
        if c.sha256 in in_entry or c.sha256 in seen:
            c.report.update(status="duplicate", code=str(ErrorCode.DUPLICATE),
                            message="this demo is already in the analysis")  # fmt: skip
            continue
        seen.add(c.sha256)
        known = lib.get_demo(c.sha256)
        if known is not None:
            c.known, c.map_name = True, known["map"]
            continue
        with ctx.parse_slot:
            probe = run_probe(c.dem, adapter=options.adapter, cancel=ctx.cancel)
        if probe.cancelled:
            raise JobCancelled
        if not probe.ok:
            _reject(c, probe.code, probe.message)
            continue
        c.map_name = probe.header.get("map_name")


def _choose_map(candidates: list[_Candidate], entry_map: str | None) -> str | None:
    maps = [c.map_name for c in candidates if c.report["status"] == "pending"]
    target = entry_map or (Counter(maps).most_common(1)[0][0] if maps else None)
    for c in candidates:
        if c.report["status"] == "pending" and c.map_name != target:
            _reject(c, ErrorCode.MAP_MISMATCH,
                    f"map mismatch (found {c.map_name}, expected {target})")  # fmt: skip
    return target


def _extract_all(ctx: JobContext, lib: Library, candidates: list[_Candidate],
                 options: ImportOptions, parser: str, parser_version: str,
                 in_entry: set[str]) -> list[str]:  # fmt: skip
    pending = [c for c in candidates if c.report["status"] == "pending"]
    entry_keys = {lib.get_demo(sha)["match_key"] for sha in in_entry}
    accepted: list[str] = []
    for i, c in enumerate(pending):
        ctx.check_cancel()
        ctx.progress(phase="parsing", done=i, total=len(pending), file=c.source.name)
        cached = lib.find_extract(c.sha256, parser, parser_version, EXTRACT_SCHEMA)
        if cached is not None:
            key = lib.get_demo(c.sha256)["match_key"]
        else:
            dest = lib.extract_dir(c.sha256, parser, parser_version, EXTRACT_SCHEMA)
            with ctx.parse_slot:
                outcome = run_extract(
                    c.dem, dest, adapter=options.adapter,
                    timeout_s=options.parse_timeout_s, cancel=ctx.cancel,
                )  # fmt: skip
            if outcome.cancelled:
                raise JobCancelled
            if not outcome.ok:
                _reject(c, outcome.code, outcome.message)
                continue
            manifest = outcome.manifest
            key = match_key(manifest["header"])
            if not c.known:
                if options.retain_sources:
                    retain_source(c.dem, lib.source_path(c.sha256))
                lib.record_demo(
                    sha256=c.sha256, match_key=key, map_name=manifest["header"]["map_name"],
                    played_at=file_time(c.source), rounds=manifest["row_counts"]["rounds"],
                    original_path=str(c.source), source_retained=options.retain_sources,
                )  # fmt: skip
            lib.record_extract(c.sha256, parser, parser_version, EXTRACT_SCHEMA, dest, manifest)
        if key in entry_keys:
            c.report.update(status="duplicate", code=str(ErrorCode.DUPLICATE),
                            message="the same match is already in the analysis")  # fmt: skip
            continue
        entry_keys.add(key)
        c.report.update(status="accepted")
        accepted.append(c.sha256)
    return accepted
