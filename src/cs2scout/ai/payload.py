"""What is sent to Claude (FR-AI-2, design §6.5): aggregated findings only.

The payload is a projection of the filtered Findings Snapshot. It holds no grids, no round
lists, no positions and no SteamIDs: players appear as their pseudonymous key and nickname.
The preview shows this exact object, and the confirmation token is bound to its hash.
"""

from __future__ import annotations

import hashlib
import json

from cs2scout.export.inline import leaks

# Map coordinates and per-round lists are raw data, not aggregates.
DROPPED_PARAMS = frozenset({"land", "throw", "hit_times_s"})
FINDING_FIELDS = ("id", "kind", "title", "label", "subject", "params", "support", "outcome",
                  "recency", "flags")  # fmt: skip


class PayloadLeak(RuntimeError):
    pass


def _finding(f: dict) -> dict:
    out = {k: f[k] for k in FINDING_FIELDS if f.get(k) not in (None, [], {})}
    if "params" in out:
        out["params"] = {k: v for k, v in out["params"].items() if k not in DROPPED_PARAMS}
    return out


def build(snapshot: dict, entry: dict, active_filter: dict) -> dict:
    """Only patterns that pass the support rule are sent: weaker ones are noise for a brief."""
    return {
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
    }  # fmt: skip


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
