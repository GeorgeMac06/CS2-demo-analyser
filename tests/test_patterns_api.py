"""T-10: patterns reflect what the team really does (known-answer synthetic matches).

Three demos of the team in ``support.scenarios``; every expected number follows from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from support.api import Api, make_api
from support.scenarios import scouted_match
from support.synth import write_demo


@pytest.fixture(scope="module")
def mined(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("patterns")
    src = root / "in"
    src.mkdir()
    for i, opp in enumerate(("b", "c", "d")):
        write_demo(src / f"m{i}.dem", scouted_match(opp, f"pat{i}"))
    client, settings = make_api(root / "workspace")
    with client:
        api = Api(client, settings)
        entry_id = api.confirm(api.run_import([src]))
        yield api, entry_id


def _of(snapshot: dict, kind: str, **params) -> list[dict]:
    return [f for f in snapshot["findings"] if f["kind"] == kind
            and all(f["params"].get(k) == v for k, v in params.items())]  # fmt: skip


def test_t_strategies_found_with_exact_support(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    b_rush = _of(snap, "ts.strategy", site="B", tempo="rush")
    a_default = _of(snap, "ts.strategy", site="A", tempo="default")
    assert len(b_rush) == 1 and b_rush[0]["support"] == {"k": 18, "n": 36, "demos": 3}
    assert b_rush[0]["params"]["utility_median"]["smokes"] == 1  # the a2 smoke, most rounds
    assert len(a_default) == 1 and a_default[0]["support"]["k"] == 9
    for f in b_rush + a_default:
        assert "below_support" not in f["flags"]


def test_fake_unresolved_and_buy_rounds(mined) -> None:
    api, entry = mined
    snap = api.findings(entry)
    fake = _of(snap, "ts.fake", shown="B", site="A")
    assert len(fake) == 1 and fake[0]["support"]["k"] == 6  # 6/36 = 17%: passes support
    assert "below_support" not in fake[0]["flags"]
    unresolved = _of(snap, "ts.site", site=None)
    assert unresolved[0]["support"]["k"] == 3 and "below_support" in unresolved[0]["flags"]
    pistol = _of(snap, "ts.buy", buy="pistol", site="B", tempo="rush")
    assert pistol[0]["support"] == {"k": 3, "n": 3, "demos": 3}
    post_b = _of(snap, "ts.postplant", site="B")
    assert post_b and post_b[0]["eligible"] == {"side": "T", "planted": True}


def test_t_patterns_recount_under_filters(mined) -> None:
    api, entry = mined
    assert not [f for f in api.findings(entry, side="CT")["findings"]
                if f["kind"].startswith("ts.")]  # fmt: skip
    full_only = api.findings(entry, buy=["full"])
    b_rush = _of(full_only, "ts.strategy", site="B", tempo="rush")
    assert b_rush[0]["support"]["k"] == 15  # pistol rounds filtered out
    one_demo = api.findings(entry, demos=[full_only["round_index"][0]["demo_label"]])
    assert _of(one_demo, "ts.strategy", site="B", tempo="rush")[0]["support"]["k"] == 6


def test_patterns_are_saved_with_the_version(mined) -> None:
    api, entry = mined
    vdir: Path = api.library.current_version_dir(entry)
    assert (vdir / "patterns.json").exists()
