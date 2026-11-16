"""The brief's answer shape and the grounding check (FR-AI-3, design §6.5).

Claude answers in sections of claims. A claim is one play or habit: a short title ("B
execute: usually early") and a few short points under it. Every claim cites what it rests
on: finding IDs, round IDs (from the round stories), or both. A claim that cites nothing,
or cites an ID that was not in the payload, is dropped. If more than 20% of claims are
dropped, the whole brief is rejected (AI_UNGROUNDED).
"""

from __future__ import annotations

MAX_DROPPED_SHARE = 0.20
# Sections in the order the brief shows them. Owner feedback 2026-11-16 (second round): a
# short "what to expect" first, then each side as plays an IGL would write down.
SECTIONS = {
    "overview": "What to expect",
    "t_side": "T side",
    "ct_side": "CT side",
    "pistols": "Pistol rounds",
    "players": "Players",
    "counters": "Suggested counters",
    "watch": "Rounds to watch",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "enum": list(SECTIONS)},
                    "claims": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "points": {"type": "array", "items": {"type": "string"}},
                                "finding_ids": {"type": "array", "items": {"type": "string"}},
                                "rounds": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title", "points", "finding_ids", "rounds"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "claims"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sections"],
    "additionalProperties": False,
}


class Ungrounded(ValueError):
    pass


def ground(answer: dict, findings: list[dict], rounds: dict[str, dict] | None = None) -> dict:
    """The brief to store: kept claims with their cited findings (title, k/n) and rounds.

    ``rounds`` maps a round ID to what the app shows for it (demo, round, side, tick...).
    """
    known = {f["id"]: f for f in findings}
    rounds = rounds or {}
    total = dropped = 0
    sections = []
    for section in answer.get("sections") or []:
        kept = []
        for claim in section.get("claims") or []:
            total += 1
            title = str(claim.get("title") or "").strip()
            points = [str(p).strip() for p in claim.get("points") or [] if str(p).strip()]
            ids = list(dict.fromkeys(str(i) for i in claim.get("finding_ids") or []))
            refs = list(dict.fromkeys(str(r) for r in claim.get("rounds") or []))
            unknown = [i for i in ids if i not in known] + [r for r in refs if r not in rounds]
            if not (title or points) or not (ids or refs) or unknown:
                dropped += 1
                continue
            kept.append({"title": title, "points": points, "cites": [_cite(known[i]) for i in ids],
                         "rounds": [rounds[r] | {"ref": r} for r in refs]})  # fmt: skip
        sid = str(section.get("id"))
        if kept and sid in SECTIONS:
            sections.append({"id": sid, "title": SECTIONS[sid], "claims": kept})
        elif kept:
            dropped += len(kept)  # a section outside the schema: nothing to show it under
    if total == 0:
        raise Ungrounded("Claude returned no claims.")
    if dropped / total > MAX_DROPPED_SHARE:
        raise Ungrounded(
            f"{dropped} of {total} claims did not cite evidence from this analysis, so the "
            "brief was not saved. Try again."
        )
    order = list(SECTIONS)
    sections.sort(key=lambda s: order.index(s["id"]))
    return {"sections": sections, "claims": total, "dropped": dropped}


def _cite(f: dict) -> dict:
    support = f.get("support") or {}
    return {"id": f["id"], "title": f.get("label") or f["title"],
            "k": support.get("k"), "n": support.get("n")}  # fmt: skip
