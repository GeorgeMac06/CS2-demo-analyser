"""The brief's answer shape and the grounding check (FR-AI-3, design §6.5).

Claude answers in sections of claims, and every claim cites the finding IDs it rests on.
A claim with no citation, or citing an ID that was not in the payload, is dropped. If more
than 20% of claims are dropped, the whole brief is rejected (AI_UNGROUNDED).
"""

from __future__ import annotations

MAX_DROPPED_SHARE = 0.20
SECTIONS = {
    "t_side": "T side",
    "ct_side": "CT side",
    "utility": "Utility",
    "players": "Players",
    "counters": "Suggested counters",
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
                                "text": {"type": "string"},
                                "finding_ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["text", "finding_ids"],
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


def ground(answer: dict, findings: list[dict]) -> dict:
    """The brief to store: kept claims, each with its cited findings' titles and support."""
    known = {f["id"]: f for f in findings}
    total = dropped = 0
    sections = []
    for section in answer.get("sections") or []:
        kept = []
        for claim in section.get("claims") or []:
            total += 1
            text = str(claim.get("text") or "").strip()
            ids = list(dict.fromkeys(str(i) for i in claim.get("finding_ids") or []))
            if not text or not ids or any(i not in known for i in ids):
                dropped += 1
                continue
            kept.append({"text": text, "cites": [_cite(known[i]) for i in ids]})
        sid = str(section.get("id"))
        if kept and sid in SECTIONS:
            sections.append({"id": sid, "title": SECTIONS[sid], "claims": kept})
        elif kept:
            dropped += len(kept)  # a section outside the schema: nothing to show it under
    if total == 0:
        raise Ungrounded("Claude returned no claims.")
    if dropped / total > MAX_DROPPED_SHARE:
        raise Ungrounded(
            f"{dropped} of {total} claims did not cite findings from this analysis, so the "
            "brief was not saved. Try again."
        )
    order = list(SECTIONS)
    sections.sort(key=lambda s: order.index(s["id"]))
    return {"sections": sections, "claims": total, "dropped": dropped}


def _cite(f: dict) -> dict:
    support = f.get("support") or {}
    return {"id": f["id"], "title": f.get("label") or f["title"],
            "k": support.get("k"), "n": support.get("n")}  # fmt: skip
