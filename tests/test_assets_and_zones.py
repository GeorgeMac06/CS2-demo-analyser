"""Map assets fetch (DRV-5/DRV-7), radar transform, zones; T-16 on real demos (G-demos)."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import polars as pl
import pytest

from cs2scout.core.maps import Radar
from cs2scout.core.zones import PlaceNameZones
from cs2scout.jobs.extract_worker import DEFAULT_ADAPTER, adapter_identity
from cs2scout.store import assets
from cs2scout.store.extracts import read_tables
from support.api import Api, make_api
from support.synth import lineup, simple_match, write_demo

LOCAL_ASSETS = Path(__file__).parent / "local_fixtures" / "awpy-data" / assets.RELEASE
PNG_1024 = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1024).to_bytes(4, "big") * 2
            + b"\x08\x06\x00\x00\x00")  # fmt: skip


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_release(files: dict[str, bytes]):
    def opener(url: str, timeout: float):
        name = url.rsplit("/", 1)[-1]
        assert url.startswith("https://github.com/pnxenopoulos/awpy-data/releases/download/")
        return FakeResponse(files[name])

    return opener


def release_files() -> dict[str, bytes]:
    images = io.BytesIO()
    with zipfile.ZipFile(images, "w") as z:
        z.writestr("radars/de_mirage.png", PNG_1024)
        z.writestr("../../escape.png", PNG_1024)  # path inside the archive is ignored
        z.writestr("radars/readme.txt", b"not a radar")
    map_data = json.dumps({"de_mirage": {"pos_x": -3230, "pos_y": 1713, "scale": 5.0}}).encode()
    return {"images.zip": images.getvalue(), "map_data.json": map_data}


def test_fetch_installs_only_verified_flat_radars(tmp_path: Path, monkeypatch) -> None:
    files = release_files()
    monkeypatch.setattr(assets, "PINNED_SHA256",
                        {k: hashlib.sha256(v).hexdigest() for k, v in files.items()})  # fmt: skip
    report = assets.fetch(tmp_path, opener=fake_release(files))

    assert report["status"] == "installed" and report["maps"] == ["de_mirage"]
    radars = sorted(p.name for p in (assets.assets_dir(tmp_path) / "radars").iterdir())
    assert radars == ["de_mirage.png", "escape.png"]  # flattened into radars/, nothing outside
    assert not list(tmp_path.glob("**/readme.txt"))
    assert assets.radar_info(tmp_path, "de_mirage")["width"] == 1024
    assert assets.fetch(tmp_path, opener=fake_release(files))["status"] == "already installed"


def test_tampered_download_installs_nothing(tmp_path: Path) -> None:
    files = release_files()  # hashes do not match the real pinned release
    with pytest.raises(assets.AssetError, match="failed verification"):
        assets.fetch(tmp_path, opener=fake_release(files))
    assert not assets.installed(tmp_path)
    assert not (tmp_path / "assets").exists() or not any((tmp_path / "assets").rglob("*.png"))


def test_radar_transform_and_levels() -> None:
    mirage = Radar("de_mirage", -3230.0, 1713.0, 5.0, 1024, 1024)
    assert mirage.to_px(-3230.0, 1713.0) == (0.0, 0.0)
    assert mirage.to_px(-3230.0 + 5 * 512, 1713.0 - 5 * 512) == (512.0, 512.0)
    nuke = Radar("de_nuke", -3453.0, 2887.0, 7.0, 1024, 1024, lower_max_z=-495.0)
    levels = pl.DataFrame({"z": [-600.0, -495.0, 0.0]}).select(nuke.level())["literal"]
    assert levels.to_list() == ["lower", "default", "default"]


def test_zones_map_only_known_places() -> None:
    zones = PlaceNameZones()
    assert zones.zone("de_mirage", "TRamp") == zones.zone("de_mirage", "TRamp")
    assert (zones.zone("de_mirage", "Apartments").site, zones.zone("de_mirage", "Apartments").lane
            ) == ("B", "B apartments")  # fmt: skip
    house = zones.zone("de_mirage", "House")
    assert (house.name, house.site, house.lane) == ("House", None, None)
    assert zones.zone("de_dust2", "BombsiteB").site == "B"  # generic rule for unmapped maps
    assert zones.zone("de_dust2", None).name == "Unknown"


def test_findings_use_radar_space_when_assets_exist(tmp_path: Path, monkeypatch) -> None:
    files = release_files()
    monkeypatch.setattr(assets, "PINNED_SHA256",
                        {k: hashlib.sha256(v).hexdigest() for k, v in files.items()})  # fmt: skip
    home = tmp_path / "workspace"
    assets.fetch(home, opener=fake_release(files))
    src = tmp_path / "in"
    src.mkdir()
    for i in range(3):
        write_demo(src / f"m{i}.dem", simple_match(lineup("a"), lineup(f"o{i}"), server=f"r{i}"))
    client, settings = make_api(home)
    with client:
        api = Api(client, settings)
        snap = api.findings(api.confirm(api.run_import([src])))
    assert snap["radar"]["map"] == "de_mirage"
    assert {g["space"] for g in snap["grids"].values()} == {"radar"}
    assert all(g["extent"] == [0.0, 1024.0, 0.0, 1024.0] for g in snap["grids"].values())


def test_no_assets_means_world_space_stats_only(api: Api, tmp_path: Path) -> None:
    src = tmp_path / "in"
    src.mkdir()
    for i in range(3):
        write_demo(src / f"m{i}.dem", simple_match(lineup("a"), lineup(f"o{i}"), server=f"w{i}"))
    snap = api.findings(api.confirm(api.run_import([src])))
    assert snap["radar"] is None
    assert {g["space"] for g in snap["grids"].values()} == {"world"}


# ---------------------------------------------------------------- T-16 on real demos


@pytest.mark.demos
def test_real_positions_land_on_the_radar(real_demo: Path, tmp_path: Path) -> None:
    if not LOCAL_ASSETS.exists():
        pytest.fail(f"copy the radar pack to {LOCAL_ASSETS} (uv run cs2scout assets fetch)")
    home = tmp_path / "workspace"
    shutil.copytree(LOCAL_ASSETS, assets.assets_dir(home))
    client, settings = make_api(home, adapter=DEFAULT_ADAPTER)
    with client:
        api = Api(client, settings)
        job = api.run_import([real_demo], timeout=900)
        sha = job["result"]["accepted"][0]
        parser, version = adapter_identity(DEFAULT_ADAPTER)
        extract = Path(api.library.find_extract(sha, parser, version, 1)["path"])
    t = read_tables(extract, {"snapshots": ["x", "y", "health"], "bomb": None})
    radar = Radar.from_info(assets.radar_info(home, job["result"]["map"]))

    alive = t["snapshots"].filter(pl.col("health") > 0).select(px=radar.px(), py=radar.py())
    inside = alive.filter(pl.col("px").is_between(0, radar.width)
                          & pl.col("py").is_between(0, radar.height))  # fmt: skip
    assert inside.height == alive.height, "every live position must fall on the radar image"

    plants = (
        t["bomb"]
        .filter(pl.col("event") == "finish_plant")
        .with_columns(px=radar.px(), py=radar.py())
    )
    centres = plants.group_by("bombsite").agg(pl.col("px", "py").mean()).sort("bombsite")
    assert centres["bombsite"].to_list() == ["A", "B"] or centres.height == 1
    if centres.height == 2:
        (ax, ay), (bx, by) = centres.select("px", "py").rows()
        assert ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 > 200  # the sites are far apart
        for row in plants.iter_rows(named=True):
            own = (ax, ay) if row["bombsite"] == "A" else (bx, by)
            other = (bx, by) if row["bombsite"] == "A" else (ax, ay)
            d_own = ((row["px"] - own[0]) ** 2 + (row["py"] - own[1]) ** 2) ** 0.5
            d_other = ((row["px"] - other[0]) ** 2 + (row["py"] - other[1]) ** 2) ** 0.5
            assert d_own < d_other, "each plant sits nearer its own site"
