"""Issue #1: the analyst edits the AI brief before sharing it. Claude's original is kept and
can be restored; the edit shows in the app, the export and the Markdown download."""

from __future__ import annotations

from pathlib import Path

import pytest

from cs2scout.export.inline import leaks
from support.api import Api, make_api
from support.fake_claude import FakeClaude
from support.scenarios import scouted_match
from support.synth import write_demo

KEY = "sk-ant-api03-fake-key-for-tests"


@pytest.fixture
def ai(tmp_path: Path):
    claude = FakeClaude()
    client, settings = make_api(tmp_path / "workspace", anthropic_api_key=KEY)
    with client:
        client.app.state.ai_http_client = claude.http_client()
        yield Api(client, settings)


@pytest.fixture
def entry(ai: Api, tmp_path: Path) -> int:
    folder = tmp_path / "in"
    folder.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        write_demo(folder / f"m{i}.dem", scouted_match(opp, f"in{i}"))
    return ai.confirm(ai.run_import([folder]), team_name="Scouted")


@pytest.fixture
def brief(ai: Api, entry: int) -> dict:
    token = ai.post(f"/api/entries/{entry}/ai-brief/preview", {}).json()["token"]
    created = ai.post(f"/api/entries/{entry}/ai-brief", {"token": token})
    assert created.status_code == 200, created.text
    return created.json()


def unchanged(brief: dict) -> list[dict]:
    """The edit body that keeps every item as it is."""
    return [{"id": s["id"], "claims": [{"source": j, "title": c["title"], "points": c["points"]}
                                       for j, c in enumerate(s["claims"])]}
            for s in brief["sections"]]  # fmt: skip


def t_side(brief: dict) -> dict:
    return next(s for s in brief["sections"] if s["id"] == "t_side")


def edit(ai: Api, entry: int, brief: dict) -> dict:
    """Swap the first two T plays, rename one, delete the third, add one of our own."""
    sections = unchanged(brief)
    plays = next(s for s in sections if s["id"] == "t_side")["claims"]
    first, second, _deleted, *rest = plays
    first = first | {"title": "Fast B, renamed", "points": ["Hit at 1:25", " ", "Lurk mid"]}
    own = {"title": "Their IGL calls late", "points": ["Hold mid until 1:00"]}
    plays[:] = [second, first, *rest, own]
    response = ai.put(f"/api/entries/{entry}/ai-brief",
                      {"sections": sections, "based_on": brief["created_at"]})  # fmt: skip
    assert response.status_code == 200, response.text
    return response.json()


def test_edit_reorders_deletes_adds_and_keeps_the_evidence(ai: Api, entry: int,
                                                           brief: dict) -> None:  # fmt: skip
    edited = edit(ai, entry, brief)
    before, after = t_side(brief)["claims"], t_side(edited)["claims"]

    assert edited["edited"] is True and edited["stale"] is False
    assert len(after) == len(before)  # one deleted, one added
    assert after[0] == before[1]
    assert after[1]["title"] == "Fast B, renamed"
    assert after[1]["points"] == ["Hit at 1:25", "Lurk mid"]  # blank points dropped
    assert after[1]["cites"] == before[0]["cites"]  # the evidence stays with the item
    assert before[2] not in after and after[2:-1] == before[3:]
    assert after[-1] == {"title": "Their IGL calls late", "points": ["Hold mid until 1:00"],
                         "cites": [], "rounds": [], "by": "analyst"}  # fmt: skip
    # Claude's original is kept, and the brief still says when Claude wrote it.
    assert edited["original_at"] == edited["written_at"] == brief["created_at"]
    assert ai.library.brief_at(entry, brief["created_at"])["sections"] == brief["sections"]
    assert ai.get(f"/api/entries/{entry}/ai-brief").json() == edited


def test_edited_brief_shows_in_the_app_export_and_markdown(ai: Api, entry: int,
                                                           brief: dict) -> None:  # fmt: skip
    edit(ai, entry, brief)
    page = ai.get(f"/entries/{entry}?tab=brief").text
    assert "AI-generated, edited by the analyst" in page and "Restore original" in page
    assert '<strong>Their IGL calls late</strong> <span class="chip">added by the analyst' in page

    html = ai.post(f"/api/entries/{entry}/export", {}).text
    assert "AI-generated, edited by the analyst" in html and "Their IGL calls late" in html
    assert "Restore original" not in html and leaks(html) == []

    text = ai.get(f"/ui/entries/{entry}/ai-brief.md").text
    assert f"on {brief['created_at'][:10]} from analysis version" in text
    assert "Edited by the analyst on" in text
    assert "**Their IGL calls late** *(added by the analyst)*\n- Hold mid until 1:00\n" in text
    assert "**Fast B, renamed**\n- Hit at 1:25\n- Lurk mid\n" in text
    body, appendix = text.split("## Evidence")
    assert "Fast B, renamed" in appendix and "Their IGL calls late" not in appendix


def test_edit_survives_a_restart(ai: Api, entry: int, brief: dict) -> None:
    edited = edit(ai, entry, brief)
    client, _ = make_api(ai.settings.home)
    with client:
        again = client.get(f"/api/entries/{entry}/ai-brief", headers=ai.headers).json()
    assert again["edited"] is True and again["sections"] == edited["sections"]


def test_restore_brings_back_claudes_original(ai: Api, entry: int, brief: dict) -> None:
    edited = edit(ai, entry, brief)
    restored = ai.post(f"/api/entries/{entry}/ai-brief/restore")
    assert restored.status_code == 200, restored.text
    restored = restored.json()
    assert restored["sections"] == brief["sections"] and "edited" not in restored
    assert restored["written_at"] == brief["created_at"]
    assert ai.library.brief_at(entry, edited["created_at"])["edited"] is True  # history stays
    page = ai.get(f"/entries/{entry}?tab=brief").text
    assert "edited by the analyst" not in page and "Restore original" not in page
    again = ai.post(f"/api/entries/{entry}/ai-brief/restore")
    assert again.status_code == 409

    # Editing the restored brief still points back at Claude's original.
    assert edit(ai, entry, restored)["original_at"] == brief["created_at"]


def test_edited_brief_goes_stale_when_the_analysis_changes(ai: Api, entry: int, brief: dict,
                                                           tmp_path: Path) -> None:  # fmt: skip
    edit(ai, entry, brief)
    more = tmp_path / "more"
    more.mkdir()
    write_demo(more / "m9.dem", scouted_match("e", "late9"))
    job = ai.wait(ai.post(f"/api/entries/{entry}/demos", {"paths": [str(more)]}).json()["job_id"])
    assert job["state"] == "done", job
    stale = ai.get(f"/api/entries/{entry}/ai-brief").json()
    assert stale["edited"] is True and stale["stale"] is True
    assert "<h1>AI brief</h1>" not in ai.post(f"/api/entries/{entry}/export", {}).text


@pytest.mark.parametrize(("change", "status", "code"), [
    ("no title", 422, "INVALID_REQUEST"),
    ("unknown item", 422, "INVALID_REQUEST"),
    ("missing section", 422, "INVALID_REQUEST"),
    ("steamid", 422, "EXPORT_BLOCKED"),
    ("changed since", 409, "INVALID_REQUEST"),
])  # fmt: skip
def test_edit_rules(ai: Api, entry: int, brief: dict, change: str, status: int,
                    code: str) -> None:  # fmt: skip
    sections = unchanged(brief)
    plays = next(s for s in sections if s["id"] == "t_side")["claims"]
    based_on = brief["created_at"]
    if change == "no title":
        plays.append({"title": " ", "points": ["a point with no title"]})
    elif change == "unknown item":
        plays.append({"source": 99, "title": "x"})
    elif change == "missing section":
        sections.pop()
    elif change == "steamid":
        plays.append({"title": "Their AWPer", "points": ["76561198000000001"]})  # hygiene: allow
    else:
        based_on = "2000-01-01T00:00:00+00:00"
    response = ai.put(f"/api/entries/{entry}/ai-brief",
                      {"sections": sections, "based_on": based_on})  # fmt: skip
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert ai.get(f"/api/entries/{entry}/ai-brief").json() == brief  # nothing saved


def test_no_brief_to_edit(ai: Api, entry: int) -> None:
    response = ai.put(f"/api/entries/{entry}/ai-brief", {"sections": []})
    assert response.status_code == 404
    assert "no brief to edit" in ai.get(f"/ui/entries/{entry}/ai-brief/edit").text


def test_editor_form_saves_an_edit(ai: Api, entry: int, brief: dict) -> None:
    form = ai.get(f"/ui/entries/{entry}/ai-brief/edit").text
    assert 'name="t-1-0"' in form and 'name="t-1-new"' in form and "Save edit" in form
    i = [s["id"] for s in brief["sections"]].index("t_side")
    plays = t_side(brief)["claims"]
    data = {"based_on": brief["created_at"]}
    for j, c in enumerate(plays):
        data |= {f"o-{i}-{j}": str(j + 1), f"t-{i}-{j}": c["title"],
                 f"p-{i}-{j}": "\n".join(c["points"])}  # fmt: skip
    data |= {f"o-{i}-0": "4", f"d-{i}-1": "on",  # move the first play down, delete the second
             f"o-{i}-new": "1", f"t-{i}-new": "Default into a mid split",
             f"p-{i}-new": "Smoke window\r\nTwo through connector\r\n"}  # fmt: skip
    for k, s in enumerate(brief["sections"]):
        if k != i:
            for j, c in enumerate(s["claims"]):
                data |= {f"t-{k}-{j}": c["title"], f"p-{k}-{j}": "\n".join(c["points"])}
    # "1" on a new item puts it first, ahead of the item that already had 1.
    o = [s["id"] for s in brief["sections"]].index("overview")
    data |= {f"o-{o}-new": "1", f"t-{o}-new": "Their AWPer peeks mid early"}
    saved = ai.client.post(f"/ui/entries/{entry}/ai-brief/edit", data=data, headers=ai.headers)
    assert saved.headers.get("HX-Redirect") == f"/entries/{entry}?tab=brief", saved.text
    edited = ai.get(f"/api/entries/{entry}/ai-brief").json()
    claims = t_side(edited)["claims"]
    assert claims[0]["title"] == "Default into a mid split" and claims[0]["by"] == "analyst"
    assert claims[0]["points"] == ["Smoke window", "Two through connector"]
    assert claims[1:] == [plays[2], plays[0], *plays[3:]]  # plays[1] was deleted
    overview = [c["title"] for c in edited["sections"][o]["claims"]]
    assert overview == ["Their AWPer peeks mid early", brief["sections"][o]["claims"][0]["title"]]

    restore = ai.client.post(f"/ui/entries/{entry}/ai-brief/restore", headers=ai.headers)
    assert restore.headers.get("HX-Redirect") == f"/entries/{entry}?tab=brief"
