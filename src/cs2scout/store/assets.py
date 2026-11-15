"""Map assets: radar images and world-to-radar data (design §5.5, DRV-5, DRV-7).

The only download besides the optional Claude API. It happens solely through the explicit
``cs2scout assets fetch`` command, from one pinned awpy-data release, and every file is
checked against a SHA-256 pinned here. The app never downloads at runtime.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import struct
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

RELEASE = "2000943"  # awpy-data release for CS2 client 2000943 (published 2026-11-12)
SOURCE = "https://github.com/pnxenopoulos/awpy-data/releases/download/{release}/{name}"
PINNED_SHA256 = {
    "map_data.json": "b0c8e7e95839b283f311e01c7d7022e5fe701bcfbb44134e7cedccec0f916e67",
    "images.zip": "b1c463c2d3566d77d60247424c756f6e8198473b19e5006268d74b682599e052",
}
MAX_FILE_BYTES = 20_000_000
_RADAR_NAME = re.compile(r"^(?P<map>[a-z0-9_]+?)(?P<lower>_lower)?\.png$")


class AssetError(Exception):
    pass


def assets_dir(home: Path) -> Path:
    return home / "assets" / "awpy-data" / RELEASE


def installed(home: Path) -> bool:
    return (assets_dir(home) / "map_data.json").exists()


def _download(name: str, opener: Callable) -> bytes:
    url = SOURCE.format(release=RELEASE, name=name)
    with opener(url, timeout=60) as response:  # noqa: S310 - fixed https URL
        data = response.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise AssetError(f"{name} is larger than expected")
    digest = hashlib.sha256(data).hexdigest()
    if digest != PINNED_SHA256[name]:
        raise AssetError(
            f"{name} failed verification (sha256 {digest[:12]}..., not the pinned file)"
        )
    return data


def fetch(home: Path, opener: Callable = urllib.request.urlopen) -> dict:
    """Download, verify and install the pinned assets. Idempotent; atomic on success."""
    target = assets_dir(home)
    if installed(home):
        return {"release": RELEASE, "status": "already installed", "maps": available_maps(home)}
    map_data = _download("map_data.json", opener)
    images = _download("images.zip", opener)

    partial = target.with_name(target.name + "._partial")
    shutil.rmtree(partial, ignore_errors=True)
    (partial / "radars").mkdir(parents=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(images)) as archive:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/").rsplit("/", 1)[-1]
            if member.is_dir() or not _RADAR_NAME.match(name):
                continue  # only flat radar PNGs; never trust paths inside the archive
            if member.file_size > MAX_FILE_BYTES:
                raise AssetError(f"{name} in images.zip is too large")
            (partial / "radars" / name).write_bytes(archive.read(member))
            count += 1
    (partial / "map_data.json").write_bytes(map_data)
    (partial / "installed.json").write_text(
        json.dumps({"release": RELEASE, "sha256": PINNED_SHA256, "radars": count}, indent=1),
        encoding="utf-8",
    )
    shutil.rmtree(target, ignore_errors=True)
    partial.rename(target)
    return {"release": RELEASE, "status": "installed", "radars": count,
            "maps": available_maps(home)}  # fmt: skip


def load_map_data(home: Path) -> dict:
    path = assets_dir(home) / "map_data.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def radar_path(home: Path, map_name: str, lower: bool = False) -> Path | None:
    path = assets_dir(home) / "radars" / f"{map_name}{'_lower' if lower else ''}.png"
    return path if path.exists() else None


def radar_size(path: Path) -> tuple[int, int]:
    """(width, height) from the PNG header, without an imaging library."""
    with path.open("rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssetError(f"{path.name} is not a PNG")
    width, height = struct.unpack(">II", head[16:24])
    return width, height


def available_maps(home: Path) -> list[str]:
    data = load_map_data(home)
    return sorted(m for m in data if radar_path(home, m) is not None)


def radar_info(home: Path, map_name: str) -> dict | None:
    """Everything the core needs to place positions on this map's radar, or None."""
    data = load_map_data(home).get(map_name)
    path = radar_path(home, map_name)
    if not data or path is None:
        return None
    width, height = radar_size(path)
    lower = (data.get("verticalsections") or {}).get("lower")
    return {
        "map": map_name, "release": RELEASE, "pos_x": float(data["pos_x"]),
        "pos_y": float(data["pos_y"]), "scale": float(data["scale"]), "width": width,
        "height": height,
        "lower_max_z": float(lower["AltitudeMax"]) if lower else None,
        "has_lower_image": radar_path(home, map_name, lower=True) is not None,
    }  # fmt: skip
