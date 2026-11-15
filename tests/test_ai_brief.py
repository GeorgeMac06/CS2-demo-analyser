"""T-14 (AT-9) and T-15: the AI brief sends nothing unconfirmed or private, and states only
what the findings show. The Anthropic SDK runs for real against a fake HTTP transport."""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx2
import pytest

from cs2scout.ai import confirm
from cs2scout.ai.grounding import Ungrounded, ground
from cs2scout.export.inline import leaks
from cs2scout.settings import Settings
from support.api import Api, make_api
from support.fake_claude import FakeClaude, error, sent_payload, stream
from support.scenarios import scouted_match
from support.synth import write_demo

KEY = "sk-ant-api03-fake-key-for-tests"
STEAMID = re.compile(r"7656119\d{10}")


@pytest.fixture
def claude() -> FakeClaude:
    return FakeClaude()


@pytest.fixture
def ai(tmp_path: Path, claude: FakeClaude):
    client, settings = make_api(tmp_path / "workspace", anthropic_api_key=KEY)
    with client:
        client.app.state.ai_http_client = claude.http_client()
        yield Api(client, settings)


def make_entry(api: Api, folder: Path, names: dict | None = None) -> int:
    folder.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        scenario = scouted_match(opp, f"{folder.name}{i}")
        if names:
            scenario["names"] = names
        write_demo(folder / f"m{i}.dem", scenario)
    return api.confirm(api.run_import([folder]), team_name="Scouted")


@pytest.fixture
def entry(ai: Api, tmp_path: Path) -> int:
    return make_entry(ai, tmp_path / "in")


def preview(api: Api, entry: int, **flt) -> dict:
    response = api.post(f"/api/entries/{entry}/ai-brief/preview", flt)
    assert response.status_code == 200, response.text
    return response.json()


def send(api: Api, entry: int, token: str, **flt):
    return api.post(f"/api/entries/{entry}/ai-brief", {"token": token, **flt})


# ---------------------------------------------------------------- T-14: nothing unconfirmed


def test_without_a_key_the_feature_is_off_and_the_rest_works(api: Api, tmp_path: Path) -> None:
    entry = make_entry(api, tmp_path / "in")
    response = api.post(f"/api/entries/{entry}/ai-brief/preview", {})
    assert response.status_code == 409 and response.json()["code"] == "AI_DISABLED"
    page = api.get(f"/entries/{entry}?tab=brief")
    assert page.status_code == 200 and "AI briefs are off" in page.text
    assert api.get(f"/api/entries/{entry}/findings").status_code == 200
    assert api.post(f"/api/entries/{entry}/export", {}).status_code == 200


def test_preview_sends_nothing_and_holds_no_personal_data(ai: Api, entry: int,
                                                         claude: FakeClaude) -> None:  # fmt: skip
    shown = preview(ai, entry)
    assert claude.requests == []  # QS-4: 0 network calls before confirmation
    text = json.dumps(shown["payload"])
    assert not STEAMID.search(text) and leaks(text) == []
    assert "round_refs" not in text and "grids" not in shown["payload"]
    assert {m["name"] for m in shown["payload"]["roster"]} >= {"a1", "a2"}
    snap = ai.findings(entry)
    supported = {f["id"] for f in snap["findings"] if "below_support" not in f["flags"]}
    assert {f["id"] for f in shown["payload"]["findings"]} == supported
    assert shown["model"] == "claude-opus-5-5" and shown["estimated_input_tokens"] > 100


def test_a_nickname_that_is_a_steamid_is_never_sent(ai: Api, tmp_path: Path,
                                                    claude: FakeClaude) -> None:  # fmt: skip
    entry = make_entry(ai, tmp_path / "leaky", names={"a1": "76561198000000001"})
    response = ai.post(f"/api/entries/{entry}/ai-brief/preview", {})
    assert response.status_code == 500 and response.json()["code"] == "EXPORT_BLOCKED"
    assert claude.requests == []


def test_send_needs_the_token_of_the_previewed_payload(ai: Api, entry: int, claude: FakeClaude,
                                                       monkeypatch) -> None:  # fmt: skip
    token = preview(ai, entry)["token"]
    other = send(ai, entry, token, side="T")  # a different payload than the one previewed
    assert other.status_code == 403 and other.json()["code"] == "FORBIDDEN"
    expires, _, mac = token.partition(".")
    assert send(ai, entry, f"{int(expires) + 600}.{mac}").status_code == 403  # tampered
    assert send(ai, entry, "garbage").status_code == 403
    monkeypatch.setattr("cs2scout.web.api._now", lambda: int(expires) + 1)
    assert send(ai, entry, token).status_code == 403  # expired after 10 minutes
    monkeypatch.undo()
    assert claude.requests == []


def test_sends_exactly_the_preview_once(ai: Api, entry: int, claude: FakeClaude) -> None:
    shown = preview(ai, entry, side="CT")
    response = send(ai, entry, shown["token"], side="CT")
    assert response.status_code == 200, response.text
    assert len(claude.requests) == 1
    request = claude.requests[0]
    assert request["url"].endswith("/v1/messages")
    assert sent_payload(request["body"]) == shown["payload"]  # FR-AI-2: preview == sent
    assert request["body"]["system"] == shown["instructions"]
    assert request["body"]["model"] == "claude-opus-5-5" and request["body"]["stream"] is True
    assert request["body"]["output_config"]["format"]["type"] == "json_schema"
    assert request["body"]["fallbacks"] == "default"  # a declined request is re-run server-side
    assert "server-side-fallback" in request["headers"]["anthropic-beta"]
    assert not STEAMID.search(request["raw"]) and leaks(request["raw"]) == []
    again = send(ai, entry, shown["token"], side="CT")  # a token confirms one call only
    assert again.status_code == 403 and len(claude.requests) == 1


@pytest.mark.parametrize(
    ("reply", "says"),
    [
        (lambda b: error(401, "authentication_error", "invalid x-api-key"), "API key (401)"),
        (lambda b: error(429, "rate_limit_error", "slow down"), "rate limiting"),
        (lambda b: error(529, "overloaded_error", "overloaded"), "(529)"),
        (lambda b: stream({"sections": []}, stop_reason="refusal"), "declined"),
        (lambda b: stream('{"sections": [', stop_reason="max_tokens"), "cut off"),
    ],
    ids=["bad-key", "rate-limit", "overloaded", "refusal", "truncated"],
)
def test_upstream_failures_are_clear_and_change_nothing(
    ai: Api, entry: int, claude: FakeClaude, reply, says
) -> None:
    before = (ai.get(f"/api/entries/{entry}").json(), ai.findings(entry))
    claude.reply = reply
    response = send(ai, entry, preview(ai, entry)["token"])
    assert response.status_code == 502, response.text
    body = response.json()
    assert body["code"] == "AI_UPSTREAM" and says in body["message"]
    assert KEY not in response.text
    assert (ai.get(f"/api/entries/{entry}").json(), ai.findings(entry)) == before  # FR-AI-4
    assert ai.get(f"/api/entries/{entry}/ai-brief").status_code == 404


def test_network_failure_is_reported(ai: Api, entry: int, claude: FakeClaude) -> None:
    def offline(body: dict) -> httpx2.Response:
        raise httpx2.ConnectError("no route to host")

    claude.reply = offline
    ai.client.app.state.ai_http_client = claude.http_client()
    response = send(ai, entry, preview(ai, entry)["token"])
    assert response.status_code == 502 and "Could not reach" in response.json()["message"]


# ---------------------------------------------------------------- T-15: grounded claims only

FINDINGS = [{"id": f"ts.site.team.{i}", "title": f"Hits {i}", "support": {"k": i + 3, "n": 20}}
            for i in range(10)]  # fmt: skip


def claims(*ids_per_claim: list[str]) -> dict:
    found = [{"text": f"claim {n}", "finding_ids": ids} for n, ids in enumerate(ids_per_claim)]
    return {"sections": [{"id": "t_side", "claims": found}]}


def test_grounding_drops_uncited_and_unknown_claims() -> None:
    good = [[f["id"]] for f in FINDINGS[:8]]
    brief = ground(claims(*good, [], ["ts.site.team.0", "made.up.id"]), FINDINGS)
    assert brief["claims"] == 10 and brief["dropped"] == 2  # 20%: still accepted
    kept = brief["sections"][0]["claims"]
    assert len(kept) == 8 and kept[0]["cites"] == [{"id": "ts.site.team.0", "title": "Hits 0",
                                                    "k": 3, "n": 20}]  # fmt: skip
    with pytest.raises(Ungrounded):
        ground(claims(*good[:7], [], [], ["nope"]), FINDINGS)  # 30% dropped
    with pytest.raises(Ungrounded):
        ground({"sections": []}, FINDINGS)


def test_an_ungrounded_brief_is_rejected_and_not_saved(ai: Api, entry: int,
                                                       claude: FakeClaude) -> None:  # fmt: skip
    claude.reply = lambda body: stream(claims([], [], ["not.a.finding"], [sent_payload(body)
                                                       ["findings"][0]["id"]]))  # fmt: skip
    response = send(ai, entry, preview(ai, entry)["token"])
    assert response.status_code == 422 and response.json()["code"] == "AI_UNGROUNDED"
    assert ai.get(f"/api/entries/{entry}/ai-brief").status_code == 404


def test_brief_is_saved_exported_and_goes_stale_after_a_demo_is_added(
    ai: Api, entry: int, tmp_path: Path
) -> None:
    created = send(ai, entry, preview(ai, entry)["token"]).json()
    assert created["stale"] is False and created["dropped"] == 0
    assert [s["id"] for s in created["sections"]] == ["t_side", "counters"]
    page = ai.get(f"/entries/{entry}?tab=brief").text
    assert "AI-generated" in page and created["sections"][0]["claims"][0]["text"] in page
    html = ai.post(f"/api/entries/{entry}/export", {}).text
    assert "<h1>AI brief</h1>" in html and "AI-generated" in html and leaks(html) == []

    more = tmp_path / "more"
    more.mkdir()
    write_demo(more / "m9.dem", scouted_match("e", "late9"))
    job = ai.wait(ai.post(f"/api/entries/{entry}/demos", {"paths": [str(more)]}).json()["job_id"])
    assert job["state"] == "done", job
    brief = ai.get(f"/api/entries/{entry}/ai-brief").json()
    assert brief["stale"] is True and brief["current_version"] > brief["entry_version"]
    assert "stale" in ai.get(f"/entries/{entry}?tab=brief").text
    assert "<h1>AI brief</h1>" not in ai.post(f"/api/entries/{entry}/export", {}).text


def test_ui_flow_previews_then_sends(ai: Api, entry: int, claude: FakeClaude) -> None:
    form = {"f": "1", "side": "", "ot": "on"}
    shown = ai.client.post(f"/ui/entries/{entry}/ai-brief/preview", data=form,
                           headers=ai.headers)  # fmt: skip
    assert shown.status_code == 200 and "Send to Claude" in shown.text and claude.requests == []
    token = re.search(r'name="token" value="([^"]+)"', shown.text).group(1)
    sent = ai.client.post(f"/ui/entries/{entry}/ai-brief", data=form | {"token": token},
                          headers=ai.headers)  # fmt: skip
    assert sent.headers.get("HX-Redirect") == f"/entries/{entry}?tab=brief"
    assert len(claude.requests) == 1


# ---------------------------------------------------------------- key handling


def test_key_comes_from_dotenv_and_is_never_shown(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        f'ANTHROPIC_API_KEY="{KEY}"\nCS2SCOUT_AI_MODEL=claude-sonnet-5-5\n'
    )
    settings = Settings.from_env({"CS2SCOUT_HOME": str(tmp_path)})
    assert settings.anthropic_api_key == KEY and settings.ai_model == "claude-sonnet-5-5"
    assert KEY not in repr(settings)


def test_token_is_bound_to_entry_payload_and_time() -> None:
    secret = b"s" * 32
    token = confirm.make(secret, 1, "abc", now=1000)
    assert confirm.valid(secret, token, 1, "abc", now=1599)
    assert not confirm.valid(secret, token, 1, "abc", now=1601)
    assert not confirm.valid(secret, token, 2, "abc", now=1000)
    assert not confirm.valid(secret, token, 1, "abd", now=1000)
    assert not confirm.valid(b"t" * 32, token, 1, "abc", now=1000)
