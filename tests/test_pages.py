"""Pages and htmx fragments render, and state changes outside /api still need the token.

The browser journey (T-17, G-browser) covers behaviour; this keeps template errors in G-fast.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from support.api import Api
from support.synth import lineup, simple_match, write_demo


@pytest.fixture
def entry(api: Api, tmp_path: Path) -> int:
    src = tmp_path / "in"
    src.mkdir()
    for i in range(3):
        write_demo(src / f"m{i}.dem", simple_match(lineup("a"), lineup(f"o{i}"), server=f"p{i}"))
    return api.confirm(api.run_import([src]), team_name="Dragons")


def test_library_and_new_pages(api: Api) -> None:
    page = api.client.get("/")
    assert page.status_code == 200
    assert "No analyses yet" in page.text and "assets fetch" in page.text  # no radar pack here
    assert 'name="cs2scout-token"' in page.text
    assert "Demo files or folders on this PC" in api.client.get("/new").text


def test_entry_page_tabs_and_fragments(api: Api, entry: int) -> None:
    page = api.client.get(f"/entries/{entry}")
    assert page.status_code == 200 and "Dragons - de_mirage" in page.text
    assert 'data-figure="fig-winrate"' in page.text
    for tab in ("overview", "players", "demos"):
        response = api.client.get(f"/ui/entries/{entry}/tab/{tab}", params={"f": "1", "ot": "on"})
        assert response.status_code == 200, tab
    players = api.client.get(f"/ui/entries/{entry}/tab/players", params={"f": "1", "side": "T"})
    assert "Players" in players.text and "(T)" in players.text

    heat = api.client.get(f"/ui/entries/{entry}/heatmap",
                          params={"subject": "team", "side": "T", "phase": "early"})  # fmt: skip
    assert "Most time spent" in heat.text and "data-figure" in heat.text

    refs = re.findall(r"refs=([0-9a-f]{8}%3Ar\d+)", page.text)[:2]
    drawer = api.client.get(f"/ui/entries/{entry}/rounds?title=x&refs={'&refs='.join(refs)}")
    assert drawer.status_code == 200 and drawer.text.count("<tr>") == len(refs) + 1


def test_ui_posts_need_the_session_token(api: Api, entry: int) -> None:
    origin = {"origin": api.headers["origin"]}
    no_token = api.client.post(f"/ui/entries/{entry}/rename", data={"name": "x"}, headers=origin)
    assert no_token.status_code == 403
    ok = api.client.post(
        f"/ui/entries/{entry}/rename", data={"name": "Renamed"}, headers=api.headers
    )
    assert ok.headers.get("HX-Refresh") == "true"
    assert api.get(f"/api/entries/{entry}").json()["name"] == "Renamed"


def test_match_date_can_be_corrected(api: Api, entry: int) -> None:
    sha = api.get(f"/api/entries/{entry}").json()["demos"][0]["sha256"]
    job = api.patch(f"/api/entries/{entry}/demos/{sha}", {"played_on": "2026-10-01"}).json()
    api.wait(job["job_id"])
    demos = api.findings(entry)["demos"]
    assert demos[0]["played_at"].startswith("2026-10-01")  # earliest date sorts first


def test_radar_image_is_404_without_assets(api: Api) -> None:
    assert api.client.get("/radar/de_mirage.png").status_code == 404
