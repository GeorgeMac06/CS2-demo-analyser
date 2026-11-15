"""Demo files on disk: discovery, bounded decompression, hashing, retention (design §6.1).

Archives are untrusted input (DRV-11, QS-7): output is written to a name we choose (never
the name inside the archive), and size and compression ratio are bounded while streaming.
"""

from __future__ import annotations

import bz2
import gzip
import hashlib
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEMO_MAGIC = b"PBDEMS2\x00"
CSGO_MAGIC = b"HL2DEMO\x00"
SUFFIXES = (".dem", ".dem.bz2", ".dem.gz", ".zip")
_CHUNK = 1 << 20


@dataclass(frozen=True)
class Limits:
    max_bytes: int = 2_000_000_000
    max_ratio: float = 50.0


class ArchiveRejected(Exception):
    pass


class NotCS2(Exception):
    pass


def is_candidate(path: Path) -> bool:
    return path.name.lower().endswith(SUFFIXES)


def discover(paths: list[str]) -> tuple[list[Path], list[dict]]:
    """Expand files and folders (one level) into candidate demo files, in stable order."""
    found: list[Path] = []
    skipped: list[dict] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            for child in sorted(path.iterdir()):
                if child.is_file() and is_candidate(child):
                    found.append(child)
        elif path.is_file() and is_candidate(path):
            found.append(path)
        elif path.exists():
            skipped.append({"file": path.name, "reason": "not a demo or supported archive"})
        else:
            skipped.append({"file": path.name, "reason": "not found"})
    unique = list(dict.fromkeys(p.resolve() for p in found))
    return unique, skipped


def materialize(path: Path, tmp_dir: Path, limits: Limits, prefix: str) -> tuple[Path, bool]:
    """Return a readable .dem path and whether it is a temporary copy we must delete."""
    name = path.name.lower()
    if name.endswith(".dem"):
        return path, False
    out = tmp_dir / f"{prefix}{uuid.uuid4().hex}.dem"
    compressed_size = max(path.stat().st_size, 1)
    try:
        if name.endswith(".zip"):
            _from_zip(path, out, limits, compressed_size)
        else:
            opener = bz2.open if name.endswith(".bz2") else gzip.open
            with opener(path, "rb") as src:
                _bounded_copy(src, out, limits, compressed_size)
    except ArchiveRejected:
        out.unlink(missing_ok=True)
        raise
    except (OSError, EOFError, zipfile.BadZipFile, ValueError) as exc:
        out.unlink(missing_ok=True)
        raise ArchiveRejected(f"cannot decompress: {exc}") from exc
    return out, True


def _from_zip(path: Path, out: Path, limits: Limits, compressed_size: int) -> None:
    with zipfile.ZipFile(path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(members) != 1 or not members[0].filename.lower().endswith(".dem"):
            raise ArchiveRejected("a zip must contain exactly one .dem file")
        member = members[0]
        if member.file_size > limits.max_bytes:
            raise ArchiveRejected("archive content is larger than the size limit")
        with archive.open(member) as src:  # streamed: declared sizes are not trusted
            _bounded_copy(src, out, limits, compressed_size)


def _bounded_copy(src, out: Path, limits: Limits, compressed_size: int) -> None:
    cap = min(limits.max_bytes, int(compressed_size * limits.max_ratio))
    written = 0
    with out.open("wb") as dst:
        while chunk := src.read(_CHUNK):
            written += len(chunk)
            if written > cap:
                reason = "size limit" if cap == limits.max_bytes else "compression-ratio limit"
                raise ArchiveRejected(f"archive expands beyond the {reason}")
            dst.write(chunk)


def check_magic(path: Path) -> None:
    with path.open("rb") as f:
        head = f.read(len(DEMO_MAGIC))
    if head == DEMO_MAGIC:
        return
    if head == CSGO_MAGIC:
        raise NotCS2("this is a CS:GO demo; only CS2 demos are supported")
    raise NotCS2("not a CS2 demo file")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def retain_source(dem: Path, dest: Path) -> None:
    """Keep a compressed copy so parser upgrades can re-extract (ADR-003). Atomic rename."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + ".partial")
    with dem.open("rb") as src, gzip.open(partial, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst, _CHUNK)
    partial.replace(dest)


def file_time(path: Path) -> str:
    """Best available match time: the file's modification time (demos carry no date).

    Kept to the second so demos downloaded on the same day still have an order.
    """
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def match_key(header: dict) -> str:
    """Identity of the recorded match, independent of file bytes (FR-IN-4)."""
    parts = [str(header.get(k)) for k in ("map_name", "server_name", "playback_ticks", "build_num")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
