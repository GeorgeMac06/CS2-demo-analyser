"""The team page (FR-LIB-6, issue #14): one team's analyses, one row per map."""

from __future__ import annotations

from pathlib import Path

import pytest

from support.api import Api, finding
from support.synth import lineup, simple_match, steamid, write_demo


def _import(api: Api, folder: Path, matches: list[dict], **confirm) -> int:
    folder.mkdir(parents=True)
    for i, match in enumerate(matches):
        write_demo(folder / f"m{i}.dem", match)
    return api.confirm(api.run_import([folder]), **confirm)


def _ids(keys: list[str]) -> list[str]:
    return [str(steamid(k)) for k in keys]


@pytest.fixture
def team(api: Api, tmp_path: Path) -> dict:
    """Dragons: 3 demos on Mirage, 1 on Inferno and an analysis that was never computed.
    Wolves: another team on Mirage, which must not show on the Dragons page."""
    a = lineup("a")
    mirage = _import(api, tmp_path / "mirage", [
        simple_match(a, lineup(f"o{i}"), server=f"m{i}") for i in range(3)
    ], team_name="Dragons")  # fmt: skip
    team_id = api.get(f"/api/entries/{mirage}").json()["team_id"]
    inferno = _import(api, tmp_path / "inferno", [
        simple_match(a, lineup("p"), score=(13, 2), server="i0", map_name="de_inferno")
    ], team_id=team_id, core=_ids(a))  # fmt: skip
    nuke = api.library.create_entry(team_id, "de_nuke", "Dragons - de_nuke")
    wolves = _import(api, tmp_path / "wolves", [simple_match(lineup("w"), server="w0")],
                     team_name="Wolves", core=_ids(lineup("w")))  # fmt: skip
    return {"id": team_id, "mirage": mirage, "inferno": inferno, "nuke": nuke, "wolves": wolves}


def test_team_lists_its_maps_most_demos_first_with_their_record(api: Api, team: dict) -> None:
    body = api.get(f"/api/teams/{team['id']}").json()

    assert body["name"] == "Dragons"
    assert [m["id"] for m in body["maps"]] == [team["mirage"], team["inferno"], team["nuke"]]
    mirage, inferno, nuke = body["maps"]
    assert (mirage["map"], mirage["demo_count"], inferno["demo_count"]) == ("de_mirage", 3, 1)

    # The record is the saved analysis's own count, side by side.
    snap = api.findings(team["mirage"])
    assert mirage["rounds"] == len(snap["round_index"])
    assert mirage["won"] == sum(1 for r in snap["round_index"] if r["won"])
    for side in ("T", "CT"):
        support = finding(snap, f"team.winrate.{side}.all")["support"]
        assert (mirage["sides"][side]["won"], mirage["sides"][side]["rounds"]) == (
            support["k"], support["n"])  # fmt: skip
    assert mirage["won"] + mirage["lost"] == mirage["rounds"]

    # One 15-round demo: 12 rounds on one side, 3 on the other, below the default limit of 10.
    assert inferno["rounds"] == 15
    assert mirage["low_sample"] == []
    low = [s for s, v in inferno["sides"].items() if v["rounds"] < body["low_sample_rounds"]]
    assert inferno["low_sample"] == low and len(low) == 1

    assert nuke["computed"] is False and nuke["demo_count"] == 0 and "rounds" not in nuke
    assert team["wolves"] not in [m["id"] for m in body["maps"]]


def test_team_roster_shows_nicknames_only(api: Api, team: dict) -> None:
    response = api.get(f"/api/teams/{team['id']}")
    assert [p["nick"] for p in response.json()["roster"]] == lineup("a")
    assert "7656119" not in response.text  # no SteamIDs on the team page


def test_low_sample_follows_the_setting(api: Api, team: dict) -> None:
    settings = api.get("/api/settings").json()
    settings["analysis"]["low_sample_rounds"] = 100
    assert api.put("/api/settings", settings).status_code == 200
    body = api.get(f"/api/teams/{team['id']}").json()
    assert body["low_sample_rounds"] == 100
    assert body["maps"][0]["low_sample"] == ["T", "CT"]


def test_unknown_team_is_404(api: Api) -> None:
    assert api.get("/api/teams/999").status_code == 404
    assert api.client.get("/teams/999").status_code == 404


def test_library_groups_by_team_and_links_the_team_page(api: Api, team: dict) -> None:
    library = api.client.get("/").text
    assert f'<a href="/teams/{team["id"]}">Dragons</a>' in library
    assert ">Wolves</a>" in library
    assert library.index(">Wolves</a>") < library.index(">Dragons</a>")  # last updated first

    page = api.client.get(f"/teams/{team['id']}")
    assert page.status_code == 200
    assert "de_mirage" in page.text and "de_inferno" in page.text
    assert "Not computed yet" in page.text and "low sample: " in page.text
    assert f'href="/entries/{team["mirage"]}"' in page.text and "Wolves" not in page.text

    entry = api.client.get(f"/entries/{team['inferno']}").text
    assert f'<a href="/teams/{team["id"]}">Dragons</a>' in entry
