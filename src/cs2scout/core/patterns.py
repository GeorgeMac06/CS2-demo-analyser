"""Pattern plumbing shared by the miners (design §6.3, ADR-004, FR-CONF-1).

A *pattern* is mined once over every included round and stored with all its round refs and
a stable key. Any view (unfiltered or filtered) recounts it against the rounds in view:
k = its refs in view, n = eligible rounds in view. Patterns below the minimum support are
kept but flagged ``below_support`` so the UI can hide them from the main lists.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from collections import Counter
from collections.abc import Iterable

import polars as pl

from cs2scout.core.config import AnalysisConfig


def stable_key(*parts) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:10]


def pattern(kind: str, key_parts: tuple, subject: str, title: str, params: dict,
            eligible: dict, refs: Iterable[str]) -> dict:  # fmt: skip
    key = stable_key(kind, subject, *key_parts)
    return {"id": f"{kind}.{subject}.{key}", "kind": kind, "subject": subject,
            "stable_key": key, "title": title, "params": params, "eligible": eligible,
            "all_refs": sorted(set(refs))}  # fmt: skip


def passes(k: int, n: int, cfg: AnalysisConfig) -> bool:
    return k >= cfg.min_support_rounds and n > 0 and k / n >= cfg.min_support_share


def recount(patterns: list[dict], rounds: pl.DataFrame, player_refs: dict[str, set[str]],
            cfg: AnalysisConfig, recent_labels: list[str]) -> list[dict]:  # fmt: skip
    """Patterns as findings for the rounds in view (``rounds`` = filtered round index)."""
    by_ref = {r["ref"]: r for r in rounds.iter_rows(named=True)}
    out = []
    for p in patterns:
        elig = p["eligible"]
        eligible = [
            ref for ref, r in by_ref.items()
            if elig.get("side") in (None, r["side"]) and elig.get("buy") in (None, r["buy"])
            and (not elig.get("planted") or r["planted"])
            and (elig.get("player") is None or ref in player_refs.get(elig["player"], set()))
        ]  # fmt: skip
        eligible_set = set(eligible)
        refs = [r for r in p["all_refs"] if r in eligible_set]
        n, k = len(eligible), len(refs)
        if k == 0:
            continue
        won = sum(1 for r in refs if by_ref[r]["won"])
        demos = {by_ref[r]["demo_label"] for r in refs}
        recent = sum(1 for r in refs if by_ref[r]["demo_label"] in recent_labels)
        flags = [] if passes(k, n, cfg) else ["below_support"]
        if n < cfg.low_sample_rounds:
            flags.append("low_sample")
        out.append({
            "id": p["id"], "kind": p["kind"], "subject": p["subject"],
            "stable_key": p["stable_key"], "title": p["title"], "params": p["params"],
            "eligible": elig, "round_refs": refs,
            "support": {"k": k, "n": n, "demos": len(demos)},
            "outcome": {"won": won, "win_pct": round(100 * won / k, 1)},
            "recency": {"last_seen": max(by_ref[r]["played_at"] or "" for r in refs) or None,
                        "share_last_3_demos": round(recent / k, 3)},
            "flags": flags,
        })  # fmt: skip
    return out


# ---------------------------------------------------------------- small shared helpers


def signature(groups: Iterable[str]) -> tuple[tuple[str, int], ...]:
    """A multiset of zone groups as a sorted, hashable signature."""
    return tuple(sorted(Counter(groups).items(), key=lambda kv: (-kv[1], kv[0])))


def describe(sig: tuple[tuple[str, int], ...]) -> str:
    return " · ".join(f"{n} {name}" for name, n in sig) or "nobody alive"


def multiset_similarity(a: Counter, b: Counter) -> float:
    keys = set(a) | set(b)
    top = sum(min(a[k], b[k]) for k in keys)
    bottom = sum(max(a[k], b[k]) for k in keys)
    return top / bottom if bottom else 1.0


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = max(0, round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def median(values: Iterable[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.median(vals), 1) if vals else None


def greedy_clusters(items: list[tuple[str, Counter]], threshold: float) -> list[list[str]]:
    """Deterministic single-pass clustering: each item joins the first cluster whose seed is
    at least ``threshold`` similar, else starts a new one. Items arrive in a fixed order."""
    clusters: list[tuple[Counter, list[str]]] = []
    for ref, groups in items:
        for seed, members in clusters:
            if multiset_similarity(seed, groups) >= threshold:
                members.append(ref)
                break
        else:
            clusters.append((groups, [ref]))
    return [members for _, members in clusters]
