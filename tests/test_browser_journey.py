"""T-17 (G-browser): the Analyst can complete J1 -> J3 in a real browser, then delete.

The app runs for real (uvicorn, loopback, guard on) with the synthetic parser. Locators are
roles and accessible names, so the test follows what a person sees, not page structure.
"""

from __future__ import annotations

import re
import secrets
import socket
import threading
import time

import pytest
import uvicorn

from cs2scout.settings import Settings
from cs2scout.web.app import create_app
from support.api import SYNTH
from support.synth import lineup, simple_match, write_demo

pytestmark = pytest.mark.browser
playwright = pytest.importorskip("playwright.sync_api")
expect = playwright.expect
expect.set_options(timeout=60_000)  # imports and recomputes run in background jobs


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def app_url(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("browser")
    demos = root / "demos"
    demos.mkdir()
    for i, score in enumerate([(13, 9), (13, 6), (16, 14)]):
        scenario = simple_match(lineup("a"), lineup(f"o{i}"), score=score, server=f"b{i}")
        scenario["clan"] = {"A": "Dragons", "B": f"Opp {i}"}
        write_demo(demos / f"match{i}.dem", scenario)
    port = _free_port()
    settings = Settings(home=root / "workspace", port=port, adapter=SYNTH)
    app = create_app(settings, secrets.token_urlsafe(16))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        assert time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", demos
    server.should_exit = True
    thread.join(10)


def test_import_confirm_explore_and_delete(page, app_url) -> None:
    base, demos = app_url
    page.set_default_timeout(60_000)

    # Library, empty.
    page.goto(base + "/")
    expect(page.get_by_role("heading", name="Scouting library")).to_be_visible()
    expect(page.get_by_text("No analyses yet")).to_be_visible()

    # J1: import a folder.
    page.get_by_role("main").get_by_role("link", name="New analysis").click()
    page.get_by_label("Demo files or folders on this PC").fill(str(demos))
    page.get_by_role("button", name="Import", exact=True).click()

    # Roster: the proposal is pre-filled; confirm it.
    expect(page.get_by_role("heading", name="Confirm the team you are scouting")).to_be_visible()
    expect(page.get_by_label("Team name")).to_have_value("Dragons")
    expect(page.get_by_label("Role of a1")).to_have_value("core")
    page.get_by_role("button", name="Create analysis").click()

    # J3: the computed entry.
    page.wait_for_url(re.compile(r".*/entries/\d+$"))
    expect(page.get_by_role("heading", name="Dragons - de_mirage")).to_be_visible()
    expect(page.get_by_role("cell", name="16-14")).to_be_visible()

    # Every chart has a table next to it (C-3), and the heatmap draws.
    page.locator("#heat .js-plotly-plot").wait_for()
    missing = page.evaluate("""() => [...document.querySelectorAll('[data-figure]')]
        .filter(el => !el.closest('.grid2')?.querySelector('table')).length""")
    assert missing == 0

    # Support numbers open the rounds behind them (FR-CONF-3).
    page.get_by_role("button", name=re.compile(r"^\d+\D\d+$")).first.click()  # "k/n"
    drawer = page.get_by_role("dialog")
    expect(drawer).to_be_visible()
    assert drawer.get_by_role("row").count() > 1
    drawer.get_by_role("button", name="Close").click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    # Players tab, then a side filter.
    page.get_by_role("link", name="Players", exact=True).click()
    expect(page.get_by_role("heading", name="Opening duels")).to_be_visible()
    expect(page.get_by_role("cell", name="a3", exact=True).first).to_be_visible()
    page.get_by_role("radio", name="T", exact=True).check()
    expect(page.get_by_role("heading", name="Players (T)")).to_be_visible()

    # Demos tab: leave one demo out; the analysis is recomputed.
    page.get_by_role("link", name="Demos", exact=True).click()
    first = page.get_by_role("form").filter(has=page.get_by_role("checkbox", name="include")).first
    first.get_by_role("checkbox", name="include").uncheck()
    first.get_by_role("button", name="Apply").click()
    expect(page.get_by_text("version 2")).to_be_visible()  # the job finished; page reloaded
    expect(page.get_by_text("3 demos (2 included)")).to_be_visible()
    page.get_by_role("link", name="Overview", exact=True).click()
    matches = page.get_by_role("table", name="Demos in this analysis")
    expect(matches.get_by_role("row")).to_have_count(3)  # header + 2 included demos

    # Delete needs the typed name.
    page.get_by_text("Delete", exact=True).click()
    page.get_by_label("Type the analysis name to confirm").fill("wrong")
    page.get_by_role("button", name="Delete analysis").click()
    expect(page.get_by_role("alert")).to_contain_text("type the analysis name")
    page.get_by_label("Type the analysis name to confirm").fill("Dragons - de_mirage")
    page.get_by_role("button", name="Delete analysis").click()
    page.wait_for_url(base + "/")
    expect(page.get_by_text("No analyses yet")).to_be_visible()


def test_pages_render_without_console_errors(page, app_url) -> None:
    base, _ = app_url
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    for path in ("/", "/new"):
        page.goto(base + path)
    assert errors == []


@pytest.fixture
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1280, "height": 900}}
