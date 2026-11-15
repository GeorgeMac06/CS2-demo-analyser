"""Run the parser in a child process (ADR-005, design §6.1 steps 4-5).

A native parser crash or hang can never take the server down: the child is killed on
timeout or cancel, and nothing is published unless the whole extract is valid. Output goes
to ``<dest>._partial`` and is renamed to ``<dest>`` only on success.
"""

from __future__ import annotations

import importlib
import json
import multiprocessing
import shutil
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

from cs2scout.core.errors import ErrorCode

DEFAULT_ADAPTER = "cs2scout.parser.awpy_adapter:AwpyAdapter"
DEFAULT_TIMEOUT_S = 15 * 60
PROBE_TIMEOUT_S = 120
MANIFEST = "manifest.json"
_RESULT_FILE = "header.json"
_ERROR_FILE = "error.json"
_EXIT_DEMO_ERROR = 3
_EXIT_ADAPTER_BUG = 4
_POLL_S = 0.25


@dataclass(frozen=True)
class ExtractOutcome:
    ok: bool
    code: ErrorCode | None = None
    message: str = ""
    manifest: dict | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class ProbeOutcome:
    ok: bool
    code: ErrorCode | None = None
    message: str = ""
    header: dict | None = None
    cancelled: bool = False


def partial_dir(dest: Path) -> Path:
    return dest.with_name(dest.name + "._partial")


def _run_child(target, args: tuple, timeout_s: float, cancel: threading.Event | None):
    """Start ``target`` in a spawned child. Returns (exitcode, 'timeout' | 'cancelled' | None)."""
    child = multiprocessing.get_context("spawn").Process(target=target, args=args, daemon=True)
    child.start()
    deadline = time.monotonic() + timeout_s
    while child.is_alive():
        if cancel is not None and cancel.is_set():
            stop = "cancelled"
        elif time.monotonic() >= deadline:
            stop = "timeout"
        else:
            child.join(_POLL_S)
            continue
        child.kill()
        child.join()
        return None, stop
    return child.exitcode, None


def run_extract(
    demo_path: Path,
    dest: Path,
    *,
    adapter: str = DEFAULT_ADAPTER,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cancel: threading.Event | None = None,
) -> ExtractOutcome:
    """Extract ``demo_path`` into ``dest``. ``dest`` must not exist (extracts are immutable)."""
    if dest.exists():
        raise FileExistsError(dest)
    partial = partial_dir(dest)
    shutil.rmtree(partial, ignore_errors=True)  # leftover from a killed run
    partial.mkdir(parents=True)

    exitcode, stop = _run_child(_extract_main, (str(demo_path), str(partial), adapter),
                                timeout_s, cancel)  # fmt: skip
    if stop == "cancelled":
        outcome = ExtractOutcome(False, message="cancelled", cancelled=True)
    elif stop == "timeout":
        outcome = ExtractOutcome(False, ErrorCode.PARSER_TIMEOUT, f"no result after {timeout_s:g}s")
    else:
        outcome = _read_extract_outcome(exitcode, partial)
    if outcome.ok:
        partial.rename(dest)
    else:
        shutil.rmtree(partial, ignore_errors=True)
    return outcome


def run_probe(
    demo_path: Path,
    *,
    adapter: str = DEFAULT_ADAPTER,
    timeout_s: float = PROBE_TIMEOUT_S,
    cancel: threading.Event | None = None,
) -> ProbeOutcome:
    """Read only the demo header, in a child process (design §6.1 step 4)."""
    with tempfile.TemporaryDirectory(prefix="cs2scout-probe-") as out:
        exitcode, stop = _run_child(_probe_main, (str(demo_path), out, adapter), timeout_s, cancel)
        if stop == "cancelled":
            return ProbeOutcome(False, message="cancelled", cancelled=True)
        if stop == "timeout":
            return ProbeOutcome(
                False, ErrorCode.PARSER_TIMEOUT, f"header not read in {timeout_s:g}s"
            )
        if exitcode == _EXIT_DEMO_ERROR:
            error = json.loads((Path(out) / _ERROR_FILE).read_text(encoding="utf-8"))
            return ProbeOutcome(False, ErrorCode.DEMO_UNREADABLE, error["message"])
        if exitcode != 0:
            return ProbeOutcome(
                False, ErrorCode.PARSER_CRASH, f"parser exited with code {exitcode}"
            )
        header = json.loads((Path(out) / _RESULT_FILE).read_text(encoding="utf-8"))
        return ProbeOutcome(True, header=header)


def _read_extract_outcome(exitcode: int | None, partial: Path) -> ExtractOutcome:
    if exitcode in (_EXIT_DEMO_ERROR, _EXIT_ADAPTER_BUG):
        error = json.loads((partial / _ERROR_FILE).read_text(encoding="utf-8"))
        code = ErrorCode.DEMO_UNREADABLE if exitcode == _EXIT_DEMO_ERROR else ErrorCode.PARSER_CRASH
        return ExtractOutcome(False, code, error["message"])
    if exitcode != 0:
        return ExtractOutcome(False, ErrorCode.PARSER_CRASH, f"parser exited with code {exitcode}")

    manifest = json.loads((partial / MANIFEST).read_text(encoding="utf-8"))
    rejections = [i["message"] for i in manifest["issues"] if i["severity"] == "reject"]
    if rejections:
        return ExtractOutcome(False, ErrorCode.DEMO_UNREADABLE, "; ".join(rejections), manifest)
    return ExtractOutcome(True, manifest=manifest)


def adapter_identity(adapter_spec: str) -> tuple[str, str]:
    """(name, version) of an adapter, without parsing anything."""
    cls = _load(adapter_spec)
    return cls.name, cls.version


def _load(adapter_spec: str):
    module_name, _, attr = adapter_spec.partition(":")
    return getattr(importlib.import_module(module_name), attr)


# ---------------------------------------------------------------- child process side


def _probe_main(demo_path: str, out: str, adapter_spec: str) -> None:
    adapter = _load(adapter_spec)()
    try:
        header = adapter.read_header(Path(demo_path))
    except Exception as exc:
        _fail(Path(out), _EXIT_DEMO_ERROR, f"{type(exc).__name__}: {exc}")
    (Path(out) / _RESULT_FILE).write_text(json.dumps(header), encoding="utf-8")


def _extract_main(demo_path: str, partial: str, adapter_spec: str) -> None:
    from cs2scout.core.schema import schema_problems

    out = Path(partial)
    started = time.perf_counter()
    adapter = _load(adapter_spec)()
    try:
        extract = adapter.extract(Path(demo_path))
    except Exception as exc:  # the demo could not be parsed
        _fail(out, _EXIT_DEMO_ERROR, f"{type(exc).__name__}: {exc}")
    problems = schema_problems(extract)
    if problems:  # our adapter broke the contract: a bug, not a bad demo
        _fail(out, _EXIT_ADAPTER_BUG, "adapter produced an invalid extract: " + "; ".join(problems))
    _write(out, extract, adapter, started)


def _fail(out: Path, exitcode: int, message: str) -> None:
    detail = traceback.format_exc(limit=5)
    (out / _ERROR_FILE).write_text(
        json.dumps({"message": message, "detail": detail}), encoding="utf-8"
    )
    sys.exit(exitcode)


def _write(out: Path, extract, adapter, started: float) -> None:
    from cs2scout.core.schema import EXTRACT_SCHEMA, sanity_issues

    for name, frame in extract.tables.items():
        frame.write_parquet(out / f"{name}.parquet")
    manifest = {
        "extract_schema": EXTRACT_SCHEMA,
        "parser": adapter.name,
        "parser_version": adapter.version,
        "header": extract.header,
        "row_counts": {name: frame.height for name, frame in extract.tables.items()},
        "missing_fields": list(extract.missing_fields),
        "notes": list(extract.notes),
        "issues": [vars(i) for i in sanity_issues(extract)],
        "duration_s": round(time.perf_counter() - started, 1),
        "peak_memory_mb": _peak_memory_mb(),
    }
    (out / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _peak_memory_mb() -> int | None:
    try:
        import psutil

        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None) or info.rss
        return round(peak / 1e6)
    except Exception:  # diagnostics only
        return None
