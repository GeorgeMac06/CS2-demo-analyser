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


@pytest.fixture(scope="session")
def local_demos(request: pytest.FixtureRequest) -> list[Path]:
    """Real demos, kept out of git (test strategy §4).

    No external reference data is needed: accuracy tests compare our event-based stats
    with the server's scoreboard counters recorded in the same demo (test strategy §1).
    """
    demos = sorted((LOCAL_FIXTURES / "demos").glob("*.dem"))
    if not demos:
        message = f"Real demo fixtures missing: put .dem files in {LOCAL_FIXTURES / 'demos'}"
        if request.config.getoption("--require-demos"):
            pytest.fail(message)
        pytest.skip(message)
    return demos
