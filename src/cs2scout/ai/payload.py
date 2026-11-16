"""What is sent to Claude (FR-AI-2, design §6.5): findings plus one story per round.

The payload is a projection of the filtered Findings Snapshot, plus the round stories
(owner decision 2026-11-16: Claude needs them to see lurk paths, pistol strats and opening
duels). It holds no grids, coordinates, ticks or SteamIDs: players appear as their
pseudonymous key and nickname. Times are on the round timer. The preview shows this exact
object, and the confirmation token is bound to its hash.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cs2scout.core.patterns import clock
from cs2scout.export.inline import leaks

# Map coordinates and per-round lists are raw data, not aggregates.
DROPPED_PARAMS = frozenset({"land", "throw", "hit_times_s"})
FINDING_FIELDS = ("id", "kind", "title", "label", "subject", "params", "support", "outcome",
                  "recency", "flags")  # fmt: skip


# What players call the map's place names (owner feedback 2026-11-16: "house" is TV, "shop"
# is market, "truck" is car). Edit callouts.json to match your team's calls.
CALLOUTS: dict[str, dict[str, str]] = json.loads(
    (Path(__file__).parent / "callouts.json").read_text(encoding="utf-8")
)


class PayloadLeak(RuntimeError):
    pass


# Moments in seconds after freeze time become round-timer clocks, so the brief never has
# to convert them. (A rotation's median_s is a duration and stays in seconds.)
CLOCK_PARAMS = {"median_hit_s": "median_hit_at", "checkpoint_s": "at"}


def _params(kind: str, params: dict) -> dict:
    out = {}
    for k, v in params.items():
        if k in DROPPED_PARAMS:
            continue
        if k in CLOCK_PARAMS or (k == "median_s" and kind == "util.lineup"):
            out[CLOCK_PARAMS.get(k, "at")] = clock(v) if v is not None else None
        elif k == "median_s":
            out["median_duration_s"] = v
        else:
            out[k] = v
    return out


def _finding(f: dict) -> dict:
    out = {k: f[k] for k in FINDING_FIELDS if f.get(k) not in (None, [], {})}
    if "params" in out:
        out["params"] = _params(f["kind"], out["params"])
    return out


def build(snapshot: dict, entry: dict, active_filter: dict, stories: list[dict]) -> dict:
    """Only patterns that pass the support rule are sent: weaker ones are noise for a brief.
    Stories are limited to the rounds the filter keeps."""
    kept = {r["ref"] for r in snapshot["round_index"]}
    payload = {
        "team": entry["team"],
        "map": entry["map"],
        "analysis_version": snapshot["entry"]["version"],
        "filter": active_filter,
        "demos": [{"label": d["label"], "played_on": (d["played_at"] or "")[:10],
                   "score": d.get("score"), "rounds": d["rounds"]}
                  for d in snapshot["demos"] if d["used"]],
        "roster": [{"key": m["player_key"], "name": m["nick"], "role": m["role"]}
                   for m in snapshot["roster"]],
        "findings": [_finding(f) for f in snapshot["findings"]
                     if "below_support" not in f["flags"]],
        "rounds": [s["text"] for s in stories if s["ref"] in kept],
    }  # fmt: skip
    if entry["map"] in CALLOUTS:
        payload["callouts"] = CALLOUTS[entry["map"]]
    return payload


def canonical(payload: dict) -> str:
    """The exact text that is sent and hashed (stable key order, no whitespace)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode("utf-8")).hexdigest()


def check(payload: dict) -> None:
    """Refuse to send personal data, whatever upstream code put in the snapshot."""
    problems = leaks(canonical(payload))
    if problems:
        raise PayloadLeak("not sent: the payload would contain " + " and ".join(problems))


def estimate_tokens(text: str) -> int:
    """A rough local estimate (JSON runs ~3 characters per token). Counting exactly would
    need a call to the API, and nothing is sent before the Analyst confirms."""
    return len(text) // 3 + 1
