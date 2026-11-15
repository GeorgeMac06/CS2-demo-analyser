"""T-13 (G-fast part): the export is self-contained, matches the app and leaks nothing."""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

import pytest

from cs2scout.export.inline import CSP, leaks
from support.api import Api
from support.scenarios import scouted_match
from support.synth import write_demo


@pytest.fixture
def entry(api: Api, tmp_path: Path) -> int:
    src = tmp_path / "in"
    src.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        write_demo(src / f"m{i}.dem", scouted_match(opp, f"ex{i}"))
    return api.confirm(api.run_import([src]), team_name="Scouted")


def export(api: Api, entry: int, **body) -> str:
    response = api.post(f"/api/entries/{entry}/export", body)
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        'attachment; filename="Scouted-de_mirage-scouting.html"'
    )
    return response.text


def test_export_is_self_contained(api: Api, entry: int) -> None:
    html = export(api, entry)
    meta = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html)
    assert meta and unescape(meta.group(1)) == CSP
    assert not re.search(r"<(script|img|iframe)[^>]+src=|<link[^>]+href=", html)
    assert "htmx" not in html.split("<script>")[0]  # no app controls in the page head
    assert "hx-post" not in html and "hx-get" not in html  # static: no live controls
    assert html.count('data-figure="') >= 5  # win rates, tempo, heatmaps, lineups
    assert leaks(html) == []


def test_export_numbers_match_the_app(api: Api, entry: int) -> None:
    snap = api.findings(entry)
    html = export(api, entry)
    b_rush = next(f for f in snap["findings"] if f["kind"] == "ts.strategy"
                  and f["params"]["site"] == "B")  # fmt: skip
    k, n = b_rush["support"]["k"], b_rush["support"]["n"]
    assert f">{k}/{n}<" in html and b_rush["title"] in html
    for section in ("Overview", "T side", "CT side", "Utility", "Players"):
        assert f"<h1>{section}</h1>" in html


def test_export_sections_and_filters(api: Api, entry: int) -> None:
    html = export(api, entry, sections=["ct"], side="CT")
    assert "<h1>CT side</h1>" in html and "<h1>T side</h1>" not in html
    assert "Filtered" in html and "side: CT" in html


def test_export_refuses_to_leak_a_steamid(api: Api, tmp_path: Path) -> None:
    src = tmp_path / "leaky"
    src.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        scenario = scouted_match(opp, f"lk{i}")
        scenario["names"] = {"a1": "76561198000000001"}  # a nickname that is a SteamID
        write_demo(src / f"m{i}.dem", scenario)
    entry = api.confirm(api.run_import([src]), team_name="Scouted")
    response = api.post(f"/api/entries/{entry}/export", {})
    assert response.status_code == 500 and response.json()["code"] == "EXPORT_BLOCKED"


def test_leak_detector() -> None:
    assert leaks("player 76561198012345678 here") == ["a SteamID"]
    assert leaks(r"saved in C:\Users\someone\Desktop") == ["a file path from this PC"]
    assert leaks("13/36 rounds, Ping 1.47 K/D") == []
