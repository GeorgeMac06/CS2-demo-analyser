"""Team resolution and recompute (design §5.3 stages S3-S6, §6.2).

Recompute reads only extracts (never re-parses, DRV-4), writes ``entries/<id>/v<n+1>/`` and
swaps it in with one transaction; a failure or cancel leaves the current version untouched.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.errors import ErrorCode
from cs2scout.core.features import assign_rounds, player_rounds
from cs2scout.core.findings import SCHEMA_VERSION, all_findings, round_index_json
from cs2scout.core.grids import POSITION_COLUMNS, build_grids, live_positions, project
from cs2scout.core.labels import carry_over
from cs2scout.core.maps import Radar
from cs2scout.core.patterns_ct import ct_rounds, mine_ct, player_ct_summary
from cs2scout.core.patterns_t import mine_t, t_rounds
from cs2scout.core.patterns_util import demo_util, mine_util
from cs2scout.core.positions import PlaceIndex
from cs2scout.core.rounds import is_complete, lineup_score, match_result, team_rounds
from cs2scout.core.schema import EXTRACT_SCHEMA
from cs2scout.core.team import DemoLineups, assign_lineups, demo_lineups, propose_roster
from cs2scout.jobs.extract_worker import adapter_identity, run_extract
from cs2scout.jobs.runner import JobCancelled, JobContext
from cs2scout.store.assets import radar_info
from cs2scout.store.extracts import LINEUP_TABLES, read_tables
from cs2scout.store.library import TMP_PREFIX, Library

ROLE_ORDER = {"core": 0, "standin": 1}


@dataclass
class LoadedDemo:
    sha256: str
    label: str
    played_at: str | None
    tick_rate: float
    lineups: DemoLineups
    tables: dict[str, pl.DataFrame]


def demo_label(sha256: str) -> str:
    """Stable short label for a demo; round refs are '<label>:r<n>'."""
    return sha256[:8]


def load_demos(ctx: JobContext | None, lib: Library, shas: list[str], adapter: str,
               *, full: bool) -> tuple[list[LoadedDemo], list[dict]]:  # fmt: skip
    """Extracts for ``shas`` in chronological order (design §7, U-3).

    A missing extract for the current parser is rebuilt from the retained source. Without a
    source, an older extract of the same schema is used and reported as stale; only a demo
    with no readable extract at all is left out.
    """
    parser, version = adapter_identity(adapter)
    loaded, problems = [], []
    rows = sorted(
        (lib.get_demo(s) for s in shas), key=lambda r: (r["played_at"] or "", r["sha256"])
    )
    for row in rows:
        sha = row["sha256"]
        found = lib.find_extract(sha, parser, version, EXTRACT_SCHEMA)
        if found is None and ctx is not None:
            found = _reextract(ctx, lib, sha, adapter, parser, version)
        if found is None:
            found = lib.latest_compatible_extract(sha, EXTRACT_SCHEMA)
            old = f"{found['parser']} {found['parser_version']}" if found else None
            problems.append({
                "sha256": sha, "label": demo_label(sha), "code": str(ErrorCode.STALE_EXTRACT),
                "message": (f"parsed with {old}; re-import the demo file to refresh it" if old
                            else "no readable extract and no retained source; demo left out"),
            })  # fmt: skip
            if found is None:
                continue
        tables = read_tables(Path(found["path"]), None if full else LINEUP_TABLES)
        tick_rate = float(json.loads(found["manifest"])["header"]["tick_rate"])
        loaded.append(LoadedDemo(sha, demo_label(sha), row["played_at"], tick_rate,
                                 demo_lineups(sha, tables), tables))  # fmt: skip
    return loaded, problems


def _reextract(ctx: JobContext, lib: Library, sha: str, adapter: str, parser: str,
               version: str):  # fmt: skip
    """Parser or schema upgrade: rebuild the extract from the retained source (ADR-003)."""
    source = lib.source_path(sha)
    if not source.exists():
        return None
    tmp = lib.home / "tmp" / f"{TMP_PREFIX}{uuid.uuid4().hex}.dem"
    try:
        with gzip.open(source, "rb") as src, tmp.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        dest = lib.extract_dir(sha, parser, version, EXTRACT_SCHEMA)
        with ctx.parse_slot:
            outcome = run_extract(tmp, dest, adapter=adapter, cancel=ctx.cancel)
        if outcome.cancelled:
            raise JobCancelled
        if not outcome.ok:
            return None
        lib.record_extract(sha, parser, version, EXTRACT_SCHEMA, dest, outcome.manifest)
        return lib.find_extract(sha, parser, version, EXTRACT_SCHEMA)
    finally:
        tmp.unlink(missing_ok=True)


def demo_summary(d: LoadedDemo) -> dict:
    score = lineup_score(d.lineups, d.tables)
    hi, lo = max(score.values()), min(score.values())
    return {
        "sha256": d.sha256, "label": d.label, "played_at": d.played_at, "rounds": hi + lo,
        "score": f"{hi}-{lo}", "complete": is_complete(hi, lo),
        "lineups": {lu: [str(p) for p in sorted(m)] for lu, m in d.lineups.members.items()},
        "mixed_rounds": list(d.lineups.mixed_rounds),
    }  # fmt: skip


def roster_proposal(demos: list[LoadedDemo]) -> dict:
    proposal = propose_roster([d.lineups for d in demos])
    core, standins = set(proposal.core), set(proposal.standins)
    players = sorted(
        ({"steamid": str(p), "nick": proposal.nicks.get(p), "presence": n,
          "role": "core" if p in core else "standin" if p in standins else None}
         for p, n in proposal.presence.items()),
        key=lambda x: (ROLE_ORDER.get(x["role"], 2), -x["presence"], x["steamid"]),
    )  # fmt: skip
    return {"needs_pick": proposal.needs_pick, "team_name": proposal.team_name,
            "players": players, "scouted": proposal.scouted}  # fmt: skip


# ---------------------------------------------------------------- recompute


def player_key(steamid: int) -> str:
    """A stable pseudonym per player: unchanged by roster edits, so labels and per-player
    patterns never jump to another player. Exports carry this and the nickname, never the
    SteamID (I-3)."""
    return "p" + hashlib.sha256(str(steamid).encode()).hexdigest()[:6]


def roster_keys(roster_rows) -> list[dict]:
    """Active roster (core first, then stand-ins), each with its stable player key."""
    active = sorted((r for r in roster_rows if r["role"] in ROLE_ORDER),
                    key=lambda r: (ROLE_ORDER[r["role"]], r["steamid"]))  # fmt: skip
    return [{"player_key": player_key(r["steamid"]), "steamid": r["steamid"],
             "nick": r["last_nick"], "role": r["role"]} for r in active]  # fmt: skip


def run_recompute(ctx: JobContext, entry_id: int, adapter: str,
                  cfg: AnalysisConfig | None = None) -> dict:  # fmt: skip
    cfg = cfg or AnalysisConfig()
    lib = ctx.library
    entry = lib.get_entry(entry_id)
    entry_demos = lib.entry_demos(entry_id)
    overrides = {r["sha256"]: r["lineup_override"] for r in entry_demos if r["lineup_override"]}
    roster_rows = lib.roster(entry.team_id)
    core = {r["steamid"] for r in roster_rows if r["role"] == "core"}
    excluded = {r["steamid"] for r in roster_rows if r["role"] == "excluded"}
    roster = roster_keys(roster_rows)

    included = [r["sha256"] for r in entry_demos if r["included"]]
    ctx.progress(phase="loading", total=len(included))
    demos, problems = load_demos(ctx, lib, included, adapter, full=True)
    ctx.check_cancel()
    scouted = assign_lineups([d.lineups for d in demos], core, overrides)
    input_hash = _input_hash(demos, overrides, roster_rows, adapter_identity(adapter), cfg)
    previous = _patterns(lib.current_version_dir(entry_id))
    n, vdir = lib.begin_version(entry_id, cfg.digest(), input_hash)
    try:
        info = radar_info(lib.home, entry.map)  # None: no assets -> stats-only visuals
        radar = Radar.from_info(info) if info else None
        snapshot = _analyse(ctx, demos, scouted, roster, excluded, cfg, vdir, radar, entry.map)
        snapshot["radar"] = info
        snapshot |= {
            "schema_version": SCHEMA_VERSION,
            "entry": {"id": entry.entry_id, "name": entry.name, "map": entry.map, "version": n,
                      "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                      "config_hash": cfg.digest(), "input_hash": input_hash},
            "problems": problems,
            "roster": [{k: m[k] for k in ("player_key", "nick", "role")} for m in roster],
        }  # fmt: skip
        ctx.check_cancel()
        # Local only (never exported): lets filtered views rebuild findings per player key.
        (vdir / "players.json").write_text(json.dumps(roster), encoding="utf-8")
        (vdir / "findings.json").write_text(json.dumps(snapshot, indent=1, sort_keys=True),
                                            encoding="utf-8")  # fmt: skip
        # User labels follow their patterns when new demos reshape them (T-11).
        moves = carry_over(lib.labels(entry_id), previous, _patterns(vdir))
        for (kind, old_key), new_key in moves.items():
            lib.rekey_label(entry_id, kind, old_key, new_key)
        lib.commit_version(entry_id, n)
    except BaseException:
        lib.abandon_version(entry_id, n)
        raise
    return {"entry_id": entry_id, "version": n,
            "demos_used": sum(1 for d in snapshot["demos"] if d["used"]),
            "problems": problems}  # fmt: skip


def _patterns(version_dir: Path | None) -> list[dict]:
    path = version_dir / "patterns.json" if version_dir else None
    return json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else []


def _input_hash(demos, overrides, roster_rows, parser, cfg) -> str:
    blob = json.dumps({
        "demos": [d.sha256 for d in demos], "overrides": overrides,
        "roster": [[r["steamid"], r["role"]] for r in roster_rows], "parser": list(parser),
        "schema": EXTRACT_SCHEMA, "config": cfg.digest(),
    }, sort_keys=True).encode()  # fmt: skip
    return hashlib.sha256(blob).hexdigest()[:16]


def _analyse(ctx: JobContext, demos: list[LoadedDemo], scouted: dict, roster: list[dict],
             excluded: set[int], cfg: AnalysisConfig, vdir: Path,
             radar: Radar | None, map_name: str) -> dict:  # fmt: skip
    rounds_parts, player_parts, position_parts, summaries = [], [], [], []
    t_obs, ct_obs, util_obs = [], [], []
    for i, d in enumerate(demos):
        ctx.check_cancel()
        ctx.progress(phase="analysing", done=i, total=len(demos))
        lineup = scouted[d.sha256]
        summary = demo_summary(d) | {"scouted": lineup, "used": lineup is not None}
        if lineup is None:
            summaries.append(summary | {"code": str(ErrorCode.TEAM_NOT_FOUND)})
            continue
        rounds = team_rounds(d.lineups, lineup, d.tables, cfg, d.label).with_columns(
            demo_label=pl.lit(d.label), played_at=pl.lit(d.played_at, dtype=pl.String)
        )
        result = match_result(rounds)
        summaries.append(summary | {"score": f"{result['us']}-{result['them']}",
                                    "complete": result["complete"]})  # fmt: skip
        members = set(d.lineups.members[lineup]) - excluded
        windows = rounds.sort("start_tick").with_columns(
            window_end=pl.col("start_tick").shift(-1).fill_null(2**31 - 1)
        )
        plants = assign_rounds(d.tables["bomb"].filter(pl.col("event") == "finish_plant"), windows)
        rounds = rounds.with_columns(planted=pl.col("ref").is_in(plants["ref"].implode()))
        rounds_parts.append(rounds)
        player_parts.append(player_rounds(d.tables, rounds, members))
        t_obs.extend(t_rounds(d.tables, rounds, members, map_name, d.tick_rate, cfg))
        place_index = PlaceIndex(d.tables["snapshots"])
        ct_obs.extend(ct_rounds(d.tables, rounds, members, map_name, d.tick_rate, place_index))
        util_obs.append(demo_util(d.tables, rounds, members, d.tick_rate, place_index))
        position_parts.append(live_positions(
            d.tables["snapshots"].filter(pl.col("steamid").is_in(list(members))), rounds,
            plants.group_by("ref").agg(pl.col("tick").min()), cfg, d.tick_rate,
        ))  # fmt: skip

    used = [s["label"] for s in summaries if s["used"]]
    findings: list[dict] = []
    round_index: list[dict] = []
    if rounds_parts:
        rounds, players = pl.concat(rounds_parts), pl.concat(player_parts)
        keys = {m["steamid"]: m["player_key"] for m in roster}
        ct_pos, ct_rot = player_ct_summary(ct_obs, keys)
        patterns = (
            mine_t(t_obs, cfg)
            + mine_ct(ct_obs, keys, cfg)
            + mine_util(util_obs, ct_pos, ct_rot, players, keys, map_name, cfg)
        )
        (vdir / "patterns.json").write_text(json.dumps(patterns, sort_keys=True), encoding="utf-8")
        findings = all_findings(rounds, players, roster, patterns, cfg, recent_labels=used[-3:])
        round_index = round_index_json(rounds)
        rounds.write_parquet(vdir / "rounds.parquet")
        players.write_parquet(vdir / "player_rounds.parquet")
    positions = pl.concat(position_parts) if position_parts else pl.DataFrame(
        schema=POSITION_COLUMNS)  # fmt: skip
    projected, frame = project(positions, radar)
    subjects = {m["steamid"]: m["player_key"] for m in roster}
    grid_meta, grid_values = build_grids(projected, subjects, frame, cfg)
    grid_values.write_parquet(vdir / "grids.parquet")
    return {"demos": summaries, "round_index": round_index, "findings": findings,
            "grids": grid_meta}  # fmt: skip
