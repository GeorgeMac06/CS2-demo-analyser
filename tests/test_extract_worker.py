"""T-04 (crash/timeout part, AT-4): a bad parse never publishes a partial or broken extract."""

from __future__ import annotations

import time
from pathlib import Path

import polars as pl
import pytest

from cs2scout.core.errors import ErrorCode
from cs2scout.core.schema import EXTRACT_SCHEMA, TABLES
from cs2scout.jobs.extract_worker import partial_dir, run_extract

FAKES = "support.fake_parsers:"


@pytest.fixture
def demo_file(tmp_path: Path) -> Path:
    path = tmp_path / "input.dem"
    path.write_bytes(b"PBDEMS2\x00not really a demo")
    return path


def test_valid_extract_is_published_with_exact_schema(demo_file: Path, tmp_path: Path) -> None:
    dest = tmp_path / "extracts" / "abc" / "fake@0+s1"
    outcome = run_extract(demo_file, dest, adapter=FAKES + "TinyAdapter")

    assert outcome.ok, outcome.message
    assert not partial_dir(dest).exists()
    for name, columns in TABLES.items():
        assert dict(pl.read_parquet(dest / f"{name}.parquet").schema) == columns, name
    manifest = outcome.manifest
    assert (manifest["parser"], manifest["extract_schema"]) == ("fake", EXTRACT_SCHEMA)
    assert manifest["row_counts"]["players"] == 10
    assert manifest["issues"] == []


@pytest.mark.parametrize(
    ("adapter", "code", "message_part"),
    [
        ("RaisingAdapter", ErrorCode.DEMO_UNREADABLE, "corrupt packet at tick 123"),
        ("ExitingAdapter", ErrorCode.PARSER_CRASH, "code 13"),
        ("BadSchemaAdapter", ErrorCode.PARSER_CRASH, "players"),
        ("NoRoundsAdapter", ErrorCode.DEMO_UNREADABLE, "no rounds"),
        ("MissingFieldAdapter", ErrorCode.DEMO_UNREADABLE, "m_szLastPlaceName"),
    ],
)
def test_failed_parse_publishes_nothing(
    demo_file: Path, tmp_path: Path, adapter: str, code: ErrorCode, message_part: str
) -> None:
    dest = tmp_path / "out"
    outcome = run_extract(demo_file, dest, adapter=FAKES + adapter)

    assert (outcome.ok, outcome.code) == (False, code)
    assert message_part in outcome.message
    assert not dest.exists()
    assert not partial_dir(dest).exists()


def test_hung_parser_is_killed(demo_file: Path, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    started = time.monotonic()
    outcome = run_extract(demo_file, dest, adapter=FAKES + "HangingAdapter", timeout_s=5)

    assert outcome.code == ErrorCode.PARSER_TIMEOUT
    assert time.monotonic() - started < 30
    assert not dest.exists()
    assert not partial_dir(dest).exists()


def test_existing_extract_is_never_overwritten(demo_file: Path, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(FileExistsError):
        run_extract(demo_file, dest, adapter=FAKES + "TinyAdapter")


def test_leftover_partial_from_killed_run_is_discarded(demo_file: Path, tmp_path: Path) -> None:
    dest = tmp_path / "out"
    partial_dir(dest).mkdir()
    (partial_dir(dest) / "stale.parquet").write_bytes(b"junk")

    assert run_extract(demo_file, dest, adapter=FAKES + "TinyAdapter").ok
    assert not (dest / "stale.parquet").exists()
