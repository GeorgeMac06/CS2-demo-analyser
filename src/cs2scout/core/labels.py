"""User labels on patterns (FR-TS-3, FR-PLR-1; design §6.3 "stable identity and labels").

Layer 1: a pattern's ``stable_key`` comes from its defining parameters, so most labels
survive a recompute untouched. Layer 2: when new demos reshape a pattern (new key), a label
moves to the new pattern of the same kind and subject whose rounds overlap the old one's
most (Jaccard >= 0.5). A label that matches nothing is kept, unshown, in case it returns.
"""

from __future__ import annotations

JACCARD_MIN = 0.5


def jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def carry_over(labels: dict[tuple[str, str], str], old: list[dict], new: list[dict]
               ) -> dict[tuple[str, str], str]:  # fmt: skip
    """Moves: ``{(kind, old_key): new_key}`` for labels whose pattern changed key."""
    new_keys = {(p["kind"], p["stable_key"]) for p in new}
    old_by_key = {(p["kind"], p["stable_key"]): p for p in old}
    taken: set[tuple[str, str]] = set()
    moves: dict[tuple[str, str], str] = {}
    for kind_key in sorted(labels):
        if kind_key in new_keys or kind_key not in old_by_key:
            continue  # still present, or an orphan from an older version
        before = old_by_key[kind_key]
        refs = set(before["all_refs"])
        best, score = None, JACCARD_MIN
        for p in new:
            target = (p["kind"], p["stable_key"])
            if p["kind"] != before["kind"] or p["subject"] != before["subject"]:
                continue
            if target in taken or target in labels:
                continue
            s = jaccard(refs, set(p["all_refs"]))
            if s >= score:
                best, score = p, s
        if best is not None:
            moves[kind_key] = best["stable_key"]
            taken.add((best["kind"], best["stable_key"]))
    return moves


def apply(findings: list[dict], labels: dict[tuple[str, str], str]) -> list[dict]:
    """Overlay labels at view time (they can change without a recompute)."""
    out = []
    for f in findings:
        label = labels.get((f["kind"], f.get("stable_key"))) if f.get("stable_key") else None
        out.append(f | {"label": label} if label else f)
    return out
