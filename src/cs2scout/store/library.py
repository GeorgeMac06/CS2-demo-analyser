"""Library: SQLite metadata plus the workspace folders (design §5.1, §5.3).

Every public method opens a short-lived connection, so the library is safe to share between
the web threads and the job threads. SQLite WAL mode lets readers run during a write.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cs2scout.store.workspace import init_workspace

SCHEMA_VERSION = 1
TMP_PREFIX = "cs2scout-"

_SCHEMA = """
CREATE TABLE demo (
    sha256 TEXT PRIMARY KEY,
    match_key TEXT NOT NULL,
    map TEXT NOT NULL,
    played_at TEXT,
    rounds INTEGER,
    original_path TEXT,
    source_retained INTEGER NOT NULL DEFAULT 0,
    imported_at TEXT NOT NULL
);
CREATE INDEX demo_match_key ON demo(match_key);
CREATE TABLE extract (
    sha256 TEXT NOT NULL REFERENCES demo(sha256) ON DELETE CASCADE,
    parser TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    path TEXT NOT NULL,
    manifest TEXT NOT NULL,
    PRIMARY KEY (sha256, parser, parser_version, schema_version)
);
CREATE TABLE team (
    team_id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL
);
CREATE TABLE team_player (
    team_id INTEGER NOT NULL REFERENCES team(team_id) ON DELETE CASCADE,
    steamid INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('core', 'standin', 'excluded')),
    last_nick TEXT,
    PRIMARY KEY (team_id, steamid)
);
CREATE TABLE entry (
    entry_id INTEGER PRIMARY KEY,
    team_id INTEGER NOT NULL REFERENCES team(team_id),
    map TEXT NOT NULL,
    name TEXT NOT NULL,
    current_version INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (team_id, map)
);
CREATE TABLE entry_demo (
    entry_id INTEGER NOT NULL REFERENCES entry(entry_id) ON DELETE CASCADE,
    sha256 TEXT NOT NULL REFERENCES demo(sha256),
    included INTEGER NOT NULL DEFAULT 1,
    lineup_override TEXT CHECK (lineup_override IN ('A', 'B')),
    PRIMARY KEY (entry_id, sha256)
);
CREATE TABLE entry_version (
    entry_id INTEGER NOT NULL REFERENCES entry(entry_id) ON DELETE CASCADE,
    n INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('building', 'ready')),
    config_hash TEXT,
    input_hash TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, n)
);
CREATE TABLE label (
    entry_id INTEGER NOT NULL REFERENCES entry(entry_id) ON DELETE CASCADE,
    pattern_kind TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    user_label TEXT NOT NULL,
    PRIMARY KEY (entry_id, pattern_kind, stable_key)
);
CREATE TABLE ai_brief (
    entry_id INTEGER NOT NULL REFERENCES entry(entry_id) ON DELETE CASCADE,
    entry_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    model TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    brief_json TEXT NOT NULL,
    PRIMARY KEY (entry_id, created_at)
);
CREATE TABLE job (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    entry_id INTEGER,
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done', 'failed', 'cancelled')),
    progress TEXT,
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class WorkspaceVersionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Entry:
    entry_id: int
    team_id: int
    map: str
    name: str
    current_version: int | None
    created_at: str
    updated_at: str


class Library:
    def __init__(self, home: Path) -> None:
        self.home = init_workspace(home)
        self.db_path = home / "library.sqlite"
        with self._connect() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                db.executescript(_SCHEMA)
                db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            elif version > SCHEMA_VERSION:
                raise WorkspaceVersionError(
                    f"{self.db_path} was written by a newer cs2scout (schema {version})"
                )

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._connect() as db:
            return db.execute(sql, params).fetchall()

    # ------------------------------------------------------------------ paths

    def extract_dir(self, sha256: str, parser: str, parser_version: str, schema: int) -> Path:
        return self.home / "extracts" / sha256 / f"{parser}@{parser_version}+s{schema}"

    def source_path(self, sha256: str) -> Path:
        return self.home / "demos" / sha256 / "source.dem.gz"

    def version_dir(self, entry_id: int, n: int) -> Path:
        return self.home / "entries" / str(entry_id) / f"v{n}"

    # ------------------------------------------------------------------ demos

    def get_demo(self, sha256: str) -> sqlite3.Row | None:
        rows = self._query("SELECT * FROM demo WHERE sha256 = ?", (sha256,))
        return rows[0] if rows else None

    def demos_with_match_key(self, match_key: str) -> list[str]:
        return [r["sha256"] for r in self._query(
            "SELECT sha256 FROM demo WHERE match_key = ?", (match_key,))]  # fmt: skip

    def record_demo(
        self, *, sha256: str, match_key: str, map_name: str, played_at: str | None,
        rounds: int | None, original_path: str | None, source_retained: bool,
    ) -> None:  # fmt: skip
        with self.transaction() as db:
            db.execute(
                "INSERT OR IGNORE INTO demo VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (sha256, match_key, map_name, played_at, rounds, original_path,
                 int(source_retained), now()),
            )  # fmt: skip

    def record_extract(
        self, sha256: str, parser: str, parser_version: str, schema: int, path: Path,
        manifest: dict,
    ) -> None:  # fmt: skip
        with self.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO extract VALUES (?, ?, ?, ?, ?, ?)",
                (sha256, parser, parser_version, schema, str(path), json.dumps(manifest)),
            )

    def find_extract(
        self, sha256: str, parser: str, parser_version: str, schema: int
    ) -> sqlite3.Row | None:
        rows = self._query(
            "SELECT * FROM extract WHERE sha256 = ? AND parser = ? AND parser_version = ?"
            " AND schema_version = ?",
            (sha256, parser, parser_version, schema),
        )
        return rows[0] if rows else None

    def latest_compatible_extract(self, sha256: str, schema: int) -> sqlite3.Row | None:
        """Any extract readable by this code (same schema), newest parser version first."""
        rows = self._query(
            "SELECT * FROM extract WHERE sha256 = ? AND schema_version = ?"
            " ORDER BY parser_version DESC LIMIT 1",
            (sha256, schema),
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------ AI briefs (FR-AI-3)

    def save_brief(self, entry_id: int, entry_version: int, model: str, payload_hash: str,
                   brief: dict) -> str:  # fmt: skip
        created = datetime.now(UTC).isoformat(timespec="microseconds")
        with self.transaction() as db:
            db.execute(
                "INSERT INTO ai_brief VALUES (?, ?, ?, ?, ?, ?)",
                (entry_id, entry_version, created, model, payload_hash, json.dumps(brief)),
            )
        return created

    def latest_brief(self, entry_id: int) -> dict | None:
        """The newest brief; ``stale`` once the analysis has a newer version.

        An analyst's edit (#1) is saved as a newer row, so it is the latest; the brief it
        came from stays, under ``original_at``.
        """
        return self._brief(entry_id, "ORDER BY b.created_at DESC LIMIT 1", ())

    def brief_at(self, entry_id: int, created_at: str) -> dict | None:
        """One saved brief, as ``latest_brief`` returns it."""
        return self._brief(entry_id, "AND b.created_at = ?", (created_at,))

    def _brief(self, entry_id: int, where: str, params: tuple) -> dict | None:
        # ``where`` is one of the two constants above, never user input.
        sql = "SELECT b.*, e.current_version FROM ai_brief b JOIN entry e USING (entry_id) "
        rows = self._query(sql + f"WHERE entry_id = ? {where}", (entry_id, *params))  # noqa: S608
        if not rows:
            return None
        r = rows[0]
        return {"entry_version": r["entry_version"], "created_at": r["created_at"],
                "model": r["model"], "payload_hash": r["payload_hash"],
                "stale": r["entry_version"] != r["current_version"],
                "current_version": r["current_version"]} | json.loads(r["brief_json"])  # fmt: skip

    # ------------------------------------------------------------------ labels (FR-TS-3)

    def labels(self, entry_id: int) -> dict[tuple[str, str], str]:
        rows = self._query(
            "SELECT pattern_kind, stable_key, user_label FROM label WHERE entry_id = ?",
            (entry_id,),
        )
        return {(r["pattern_kind"], r["stable_key"]): r["user_label"] for r in rows}

    def set_label(self, entry_id: int, kind: str, key: str, label: str | None) -> None:
        with self.transaction() as db:
            db.execute(
                "DELETE FROM label WHERE entry_id = ? AND pattern_kind = ? AND stable_key = ?",
                (entry_id, kind, key),
            )
            if label:
                db.execute("INSERT INTO label VALUES (?, ?, ?, ?)", (entry_id, kind, key, label))

    def rekey_label(self, entry_id: int, kind: str, old_key: str, new_key: str) -> None:
        with self.transaction() as db:
            db.execute(
                "UPDATE OR IGNORE label SET stable_key = ?"
                " WHERE entry_id = ? AND pattern_kind = ? AND stable_key = ?",
                (new_key, entry_id, kind, old_key),
            )

    def set_played_at(self, sha256: str, played_at: str) -> None:
        """The Analyst's correction of a match date (demos carry none; FR-CONF-4)."""
        with self.transaction() as db:
            db.execute("UPDATE demo SET played_at = ? WHERE sha256 = ?", (played_at, sha256))

    def orphan_demos(self) -> list[str]:
        """Demos no entry references: candidates for garbage collection (asks first)."""
        sql = "SELECT sha256 FROM demo WHERE sha256 NOT IN (SELECT sha256 FROM entry_demo)"
        return [r["sha256"] for r in self._query(sql)]

    def delete_demos(self, shas: list[str]) -> None:
        with self.transaction() as db:
            for sha in shas:
                db.execute("DELETE FROM demo WHERE sha256 = ?", (sha,))
        for sha in shas:
            shutil.rmtree(self.home / "demos" / sha, ignore_errors=True)
            shutil.rmtree(self.home / "extracts" / sha, ignore_errors=True)

    # ------------------------------------------------------------------ teams

    def create_team(self, display_name: str) -> int:
        with self.transaction() as db:
            return db.execute("INSERT INTO team (display_name) VALUES (?)",
                              (display_name,)).lastrowid  # fmt: skip

    def list_teams(self) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM team ORDER BY display_name COLLATE NOCASE")

    def get_team(self, team_id: int) -> sqlite3.Row | None:
        rows = self._query("SELECT * FROM team WHERE team_id = ?", (team_id,))
        return rows[0] if rows else None

    def set_roster(self, team_id: int, players: list[tuple[int, str, str | None]]) -> None:
        """Replace the roster: (steamid, role, last_nick) per player."""
        with self.transaction() as db:
            db.execute("DELETE FROM team_player WHERE team_id = ?", (team_id,))
            db.executemany(
                "INSERT INTO team_player VALUES (?, ?, ?, ?)",
                [(team_id, s, role, nick) for s, role, nick in players],
            )

    def roster(self, team_id: int) -> list[sqlite3.Row]:
        return self._query(
            "SELECT steamid, role, last_nick FROM team_player WHERE team_id = ? ORDER BY steamid",
            (team_id,),
        )

    # ------------------------------------------------------------------ entries

    def create_entry(self, team_id: int, map_name: str, name: str) -> int:
        with self.transaction() as db:
            return db.execute(
                "INSERT INTO entry (team_id, map, name, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (team_id, map_name, name, now(), now()),
            ).lastrowid

    def get_entry(self, entry_id: int) -> Entry | None:
        rows = self._query("SELECT * FROM entry WHERE entry_id = ?", (entry_id,))
        return Entry(**dict(rows[0])) if rows else None

    def list_entries(self) -> list[Entry]:
        return [
            Entry(**dict(r)) for r in self._query("SELECT * FROM entry ORDER BY updated_at DESC")
        ]

    def rename_entry(self, entry_id: int, name: str) -> None:
        with self.transaction() as db:
            db.execute("UPDATE entry SET name = ?, updated_at = ? WHERE entry_id = ?",
                       (name, now(), entry_id))  # fmt: skip

    def delete_entry(self, entry_id: int) -> None:
        with self.transaction() as db:
            db.execute("DELETE FROM entry WHERE entry_id = ?", (entry_id,))
        shutil.rmtree(self.home / "entries" / str(entry_id), ignore_errors=True)

    def add_entry_demos(self, entry_id: int, shas: list[str]) -> None:
        with self.transaction() as db:
            db.executemany("INSERT OR IGNORE INTO entry_demo (entry_id, sha256) VALUES (?, ?)",
                           [(entry_id, s) for s in shas])  # fmt: skip

    def entry_demos(self, entry_id: int) -> list[sqlite3.Row]:
        return self._query(
            "SELECT d.*, ed.included, ed.lineup_override FROM entry_demo ed"
            " JOIN demo d USING (sha256) WHERE ed.entry_id = ? ORDER BY d.played_at, d.sha256",
            (entry_id,),
        )

    def set_entry_demo(
        self, entry_id: int, sha256: str, *, included: bool | None = None,
        lineup_override: str | None = None, clear_override: bool = False,
    ) -> None:  # fmt: skip
        with self.transaction() as db:
            if included is not None:
                db.execute("UPDATE entry_demo SET included = ? WHERE entry_id = ? AND sha256 = ?",
                           (int(included), entry_id, sha256))  # fmt: skip
            if lineup_override is not None or clear_override:
                db.execute(
                    "UPDATE entry_demo SET lineup_override = ? WHERE entry_id = ? AND sha256 = ?",
                    (lineup_override, entry_id, sha256),
                )

    # ------------------------------------------------------------------ versions

    def begin_version(self, entry_id: int, config_hash: str, input_hash: str) -> tuple[int, Path]:
        with self.transaction() as db:
            n = db.execute("SELECT COALESCE(MAX(n), 0) + 1 FROM entry_version WHERE entry_id = ?",
                           (entry_id,)).fetchone()[0]  # fmt: skip
            db.execute(
                "INSERT INTO entry_version VALUES (?, ?, 'building', ?, ?, ?)",
                (entry_id, n, config_hash, input_hash, now()),
            )
        path = self.version_dir(entry_id, n)
        shutil.rmtree(path, ignore_errors=True)
        path.mkdir(parents=True)
        return n, path

    def commit_version(self, entry_id: int, n: int) -> None:
        """Atomic swap (design §5.3): one transaction makes version n current."""
        with self.transaction() as db:
            db.execute("UPDATE entry_version SET status = 'ready' WHERE entry_id = ? AND n = ?",
                       (entry_id, n))  # fmt: skip
            db.execute(
                "UPDATE entry SET current_version = ?, updated_at = ? WHERE entry_id = ?",
                (n, now(), entry_id),
            )
            older = "FROM entry_version WHERE entry_id = ? AND n < ?"
            stale = [r[0] for r in db.execute(f"SELECT n {older}", (entry_id, n - 1))]  # noqa: S608
            db.execute("DELETE FROM entry_version WHERE entry_id = ? AND n < ?", (entry_id, n - 1))
        for old in stale:
            shutil.rmtree(self.version_dir(entry_id, old), ignore_errors=True)

    def abandon_version(self, entry_id: int, n: int) -> None:
        with self.transaction() as db:
            db.execute(
                "DELETE FROM entry_version WHERE entry_id = ? AND n = ? AND status = 'building'",
                (entry_id, n),
            )
        shutil.rmtree(self.version_dir(entry_id, n), ignore_errors=True)

    def current_version_dir(self, entry_id: int) -> Path | None:
        entry = self.get_entry(entry_id)
        if entry is None or entry.current_version is None:
            return None
        return self.version_dir(entry_id, entry.current_version)

    # ------------------------------------------------------------------ jobs

    def create_job(self, job_id: str, kind: str, entry_id: int | None) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO job VALUES (?, ?, ?, 'queued', NULL, NULL, NULL, ?, ?)",
                (job_id, kind, entry_id, now(), now()),
            )

    def update_job(self, job_id: str, *, state: str | None = None, progress: dict | None = None,
                   result: dict | None = None, error: str | None = None) -> None:  # fmt: skip
        sets, params = ["updated_at = ?"], [now()]
        for column, value in (("state", state), ("progress", progress), ("result", result),
                              ("error", error)):  # fmt: skip
            if value is not None:
                sets.append(f"{column} = ?")
                params.append(json.dumps(value) if isinstance(value, dict) else value)
        with self.transaction() as db:
            db.execute(f"UPDATE job SET {', '.join(sets)} WHERE job_id = ?", (*params, job_id))  # noqa: S608

    def mark_import_confirmed(self, job_id: str, entry_id: int) -> None:
        """A first import became this entry: its demos are no longer waiting for a roster."""
        with self.transaction() as db:
            db.execute("UPDATE job SET entry_id = ? WHERE job_id = ? AND kind = 'import'",
                       (entry_id, job_id))  # fmt: skip

    def get_job(self, job_id: str) -> dict | None:
        rows = self._query("SELECT * FROM job WHERE job_id = ?", (job_id,))
        if not rows:
            return None
        job = dict(rows[0])
        for key in ("progress", "result"):
            job[key] = json.loads(job[key]) if job[key] else None
        return job

    # ------------------------------------------------------------------ startup

    def startup_cleanup(self) -> dict:
        """Undo whatever a crash left behind (QS-6). Never touches ready data."""
        with self.transaction() as db:
            building = db.execute(
                "SELECT entry_id, n FROM entry_version WHERE status = 'building'"
            ).fetchall()
            db.execute("DELETE FROM entry_version WHERE status = 'building'")
            interrupted = db.execute(
                "UPDATE job SET state = 'failed', error = 'interrupted by restart', updated_at = ?"
                " WHERE state IN ('queued', 'running')",
                (now(),),
            ).rowcount
        for entry_id, n in building:
            shutil.rmtree(self.version_dir(entry_id, n), ignore_errors=True)
        partials = list((self.home / "extracts").glob("*/*._partial"))
        for path in partials:
            shutil.rmtree(path, ignore_errors=True)
        # Only our own scratch files (prefixed), so a mistyped CS2SCOUT_HOME cannot wipe user data.
        for child in (self.home / "tmp").glob(f"{TMP_PREFIX}*"):
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        return {"building_versions": len(building), "interrupted_jobs": interrupted,
                "partial_extracts": len(partials)}  # fmt: skip
