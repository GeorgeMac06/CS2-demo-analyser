"""WU-16: settings (Q1-Q3, source retention, workspace cap, port) and disk usage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cs2scout.settings import Settings
from support.api import Api
from support.scenarios import scouted_match
from support.synth import write_demo

DEFAULTS = {"eco_max": 5000, "force_max": 20000, "min_support_rounds": 3,
            "min_support_share": 0.1, "min_support_demos": 2, "low_sample_rounds": 10,
            "checkpoints_s": [15, 30, 45]}  # fmt: skip


def body(**analysis) -> dict:
    return {"analysis": DEFAULTS | analysis, "retain_sources": True}


def make_entry(api: Api, folder: Path) -> int:
    folder.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        write_demo(folder / f"m{i}.dem", scouted_match(opp, f"{folder.name}{i}"))
    return api.confirm(api.run_import([folder]), team_name="Scouted")


def test_defaults_then_saved_settings_persist(api: Api) -> None:
    got = api.get("/api/settings").json()
    assert got["analysis"] == DEFAULTS and got["retain_sources"] is True
    assert got["workspace_cap_gb"] is None and got["port"] is None
    assert got["usage"]["total_bytes"] > 0 and got["usage"]["over_cap"] is False

    saved = api.put("/api/settings", body(eco_max=4000, checkpoints_s=[10, 25]) | {"port": 9001})
    assert saved.status_code == 200, saved.text
    assert api.get("/api/settings").json()["analysis"]["eco_max"] == 4000
    on_disk = json.loads((api.settings.home / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["analysis"]["checkpoints_s"] == [10, 25] and on_disk["port"] == 9001
    # The saved port is used at the next start, unless CS2SCOUT_PORT says otherwise.
    home = str(api.settings.home)
    assert Settings.from_env({"CS2SCOUT_HOME": home}).port == 9001
    assert Settings.from_env({"CS2SCOUT_HOME": home, "CS2SCOUT_PORT": "9100"}).port == 9100


@pytest.mark.parametrize(
    "change",
    [{"force_max": 4000}, {"checkpoints_s": [30, 15]}, {"checkpoints_s": [200]},
     {"min_support_share": 1.5}, {"min_support_rounds": 0}],
    ids=["force-below-eco", "checkpoints-order", "checkpoint-range", "share", "rounds"],
)  # fmt: skip
def test_invalid_settings_are_refused(api: Api, change: dict) -> None:
    response = api.put("/api/settings", body(**change))
    assert response.status_code == 422 and response.json()["code"] == "INVALID_REQUEST"
    assert not (api.settings.home / "settings.json").exists()


def test_thresholds_apply_when_an_analysis_is_updated(api: Api, tmp_path: Path) -> None:
    entry = make_entry(api, tmp_path / "in")
    buys = {r["buy"] for r in api.get(f"/api/entries/{entry}/rounds").json()}
    assert "full" in buys
    filtered = api.findings(entry, side="T")

    assert api.put("/api/settings", body(eco_max=59000, force_max=60000)).status_code == 200
    page = api.get(f"/entries/{entry}").text
    assert "thresholds in Settings have changed" in page
    # Until it is updated, the analysis (filtered views too) keeps the thresholds it was built with.
    assert api.findings(entry, side="T") == filtered

    job = api.wait(api.post(f"/api/entries/{entry}/recompute").json()["job_id"])
    assert job["state"] == "done", job
    buys = {r["buy"] for r in api.get(f"/api/entries/{entry}/rounds").json()}
    assert buys <= {"pistol", "eco"}
    assert "thresholds in Settings have changed" not in api.get(f"/entries/{entry}").text


def test_retention_setting_applies_to_new_imports(api: Api, tmp_path: Path) -> None:
    saved = api.put("/api/settings", body() | {"retain_sources": False})
    assert saved.status_code == 200
    make_entry(api, tmp_path / "in")
    assert api.get("/api/settings").json()["usage"]["areas"]["demos"] == 0
    assert not any((api.settings.home / "demos").rglob("*.gz"))


def test_workspace_cap_warns_but_does_not_block(api: Api, tmp_path: Path) -> None:
    assert api.put("/api/settings", body() | {"workspace_cap_gb": 0.000001}).status_code == 200
    usage = api.get("/api/settings").json()["usage"]
    assert usage["over_cap"] is True and usage["cap_bytes"] == 1000
    assert "over the limit" in api.get("/").text
    make_entry(api, tmp_path / "in")  # imports still work


def test_settings_page_saves_through_the_form(api: Api) -> None:
    page = api.get("/settings")
    assert (
        page.status_code == 200
        and "Save settings" in page.text
        and "Free on this drive" in page.text
    )
    form = {"eco_max": "4500", "force_max": "19000", "min_support_rounds": "3",
            "min_support_share_pct": "12.5", "min_support_demos": "2", "low_sample_rounds": "10",
            "checkpoints_s": "15, 30, 45", "retain_sources": "on", "workspace_cap_gb": "",
            "port": ""}  # fmt: skip
    saved = api.client.post("/ui/settings", data=form, headers=api.headers)
    assert "Saved." in saved.text
    got = api.get("/api/settings").json()["analysis"]
    assert got["eco_max"] == 4500 and got["min_support_share"] == 0.125
    refused = api.client.post("/ui/settings", data=form | {"force_max": "100"}, headers=api.headers)
    assert "Not saved" in refused.text and "force-buy limit" in refused.text


def test_an_unreadable_settings_file_means_defaults(api: Api) -> None:
    (api.settings.home / "settings.json").write_text("{not json", encoding="utf-8")
    assert api.get("/api/settings").json()["analysis"] == DEFAULTS
