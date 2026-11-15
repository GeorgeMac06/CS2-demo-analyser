from __future__ import annotations

from pathlib import Path

import pytest

LOCAL_FIXTURES = Path(__file__).parent / "local_fixtures"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--require-demos",
        action="store_true",
        help="Fail (instead of skip) when real demo fixtures are missing (G-demos).",
    )


def _local_demos() -> list[Path]:
    return sorted((LOCAL_FIXTURES / "demos").glob("*.dem"))


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    # One test case per local demo. Ids are positional so match IDs never reach test output.
    if "real_demo_path" in metafunc.fixturenames:
        demos = _local_demos()
        ids = [f"demo{i}" for i in range(1, len(demos) + 1)] or ["no-demos"]
        metafunc.parametrize("real_demo_path", demos or [None], ids=ids, scope="module")


@pytest.fixture
def api(tmp_path: Path):
    """The real app (synthetic parser) behind its HTTP API, on a temp workspace."""
    from support.api import Api, make_api

    client, settings = make_api(tmp_path / "workspace")
    with client:
        yield Api(client, settings)


@pytest.fixture(scope="module")
def real_demo(request: pytest.FixtureRequest, real_demo_path: Path | None) -> Path:
    """A real demo, kept out of git (test strategy §4).

    No external reference data is needed: accuracy tests compare our event-based stats
    with the server's scoreboard counters recorded in the same demo (test strategy §1).
    """
    if real_demo_path is None:
        message = f"Real demo fixtures missing: put .dem files in {LOCAL_FIXTURES / 'demos'}"
        if request.config.getoption("--require-demos"):
            pytest.fail(message)
        pytest.skip(message)
    return real_demo_path
