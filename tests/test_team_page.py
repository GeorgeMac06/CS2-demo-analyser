"""The team page (FR-LIB-6, issue #14): one team's analyses, one row per map."""

from __future__ import annotations

from pathlib import Path

import pytest

from cs2scout.core.team import TeamSeen, group_teams
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
    Then 1 demo on Ancient with a stand-in, imported as a new team under another name: 4 of
    the main five played, so it is still Dragons. Wolves and Tigers must not show on the
    Dragons page; Tigers shares only 2 players with Dragons."""
    a = lineup("a")
    mirage = _import(api, tmp_path / "mirage", [
        simple_match(a, lineup(f"o{i}"), server=f"m{i}") for i in range(3)
    ], team_name="Dragons")  # fmt: skip
    team_id = api.get(f"/api/entries/{mirage}").json()["team_id"]
    inferno = _import(api, tmp_path / "inferno", [
        simple_match(a, lineup("p"), score=(13, 2), server="i0", map_name="de_inferno")
    ], team_id=team_id, core=_ids(a))  # fmt: skip
    nuke = api.library.create_entry(team_id, "de_nuke", "Dragons - de_nuke")
    with_sub = [*a[:4], "s1"]
    ancient = _import(api, tmp_path / "ancient", [
        simple_match(with_sub, lineup("q"), server="x0", map_name="de_ancient")
    ], team_name="Dragons Esports", core=_ids(with_sub))  # fmt: skip
    wolves = _import(api, tmp_path / "wolves", [simple_match(lineup("w"), server="w0")],
                     team_name="Wolves", core=_ids(lineup("w")))  # fmt: skip
    tigers_five = ["a1", "a2", "t3", "t4", "t5"]
    tigers = _import(api, tmp_path / "tigers", [simple_match(tigers_five, server="t0")],
                     team_name="Tigers", core=_ids(tigers_five))  # fmt: skip
    return {
        "id": team_id,
        "mirage": mirage,
        "inferno": inferno,
        "nuke": nuke,
        "ancient": ancient,
        "wolves": wolves,
        "tigers": tigers,
        "ancient_team": api.get(f"/api/entries/{ancient}").json()["team_id"],
    }


def test_team_lists_its_maps_most_demos_first_with_their_record(api: Api, team: dict) -> None:
    body = api.get(f"/api/teams/{team['id']}").json()

    assert body["name"] == "Dragons"
    assert [m["id"] for m in body["maps"]] == [
        team["mirage"], team["ancient"], team["inferno"], team["nuke"]]  # fmt: skip
    mirage, ancient, inferno, nuke = body["maps"]
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
    assert {team["wolves"], team["tigers"]}.isdisjoint(m["id"] for m in body["maps"])


def test_a_stand_in_or_a_new_name_does_not_split_a_team(api: Api, team: dict) -> None:
    """The core rule (owner, 2026-11-22): rows that share 3 of their main five are one team."""
    body = api.get(f"/api/teams/{team['id']}").json()
    assert body["ids"] == [team["id"], team["ancient_team"]]
    assert body["aliases"] == ["Dragons Esports"]
    assert api.get(f"/api/teams/{team['ancient_team']}").json() == body  # either row's link

    # Tigers has a1 and a2 too, but 2 of 5 is not the same team.
    tigers = api.get(f"/api/entries/{team['tigers']}").json()["team_id"]
    assert api.get(f"/api/teams/{tigers}").json()["ids"] == [tigers]


def test_team_roster_is_the_main_five_by_demos_played(api: Api, team: dict) -> None:
    response = api.get(f"/api/teams/{team['id']}")
    body = response.json()
    assert body["demos"] == 5  # 3 on Mirage, 1 on Ancient, 1 on Inferno
    main = {p["nick"]: p["demos"] for p in body["roster"] if p["main"]}
    assert main == {"a1": 5, "a2": 5, "a3": 5, "a4": 5, "a5": 4}
    assert [p["nick"] for p in body["roster"]] == ["a1", "a2", "a3", "a4", "a5", "s1"]
    assert [p for p in body["roster"] if not p["main"]] == [
        {"nick": "s1", "demos": 1, "main": False}]  # fmt: skip
    assert "7656119" not in response.text  # no SteamIDs on the team page


def test_core_rule_follows_the_main_five_as_the_roster_changes() -> None:
    """Five players qualify; two are swapped out, then one more: still the same team. Lose a
    third of the original five and it is a different team."""
    fred, patch, george, thomas, greg, n1, n2, n3 = range(1, 9)

    def seen(team_id: int, players: list[int], demos: int) -> TeamSeen:
        return TeamSeen(team_id, demos, dict.fromkeys(players, demos), frozenset(players))

    teams = [
        seen(1, [fred, patch, george, thomas, greg], 10),
        seen(2, [patch, george, greg, n1, n2], 4),  # fred and thomas out
        seen(3, [patch, george, greg, n1, n3], 3),  # n2 out too
        seen(4, [george, greg, n1, n2, n3], 2),  # patch out: 2 of the main five left
        TeamSeen(5, 0, {}, frozenset([fred, patch, george, 90, 91])),  # not computed yet
    ]
    assert group_teams(teams) == [[1, 2, 3, 5], [4]]


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
    assert library.count('class="team-heading"') == 3  # Dragons' two rows are one team
    assert f'<a href="/teams/{team["id"]}">Dragons</a>' in library
    assert "also named Dragons Esports" in library
    order = [library.index(f">{name}</a>") for name in ("Tigers", "Wolves", "Dragons")]
    assert order == sorted(order)  # last updated first

    page = api.client.get(f"/teams/{team['id']}")
    assert page.status_code == 200
    assert "de_mirage" in page.text and "de_inferno" in page.text and "de_ancient" in page.text
    assert "Main roster: a" in page.text and "Also played: s1" in page.text
    assert "Not computed yet" in page.text and "low sample: " in page.text
    assert f'href="/entries/{team["mirage"]}"' in page.text and "Wolves" not in page.text

    entry = api.client.get(f"/entries/{team['inferno']}").text
    assert f'<a href="/teams/{team["id"]}">Dragons</a>' in entry
