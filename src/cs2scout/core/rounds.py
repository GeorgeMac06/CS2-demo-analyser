"""Round classification for the scouted team (FR-RND-1..3, FR-IN-5, FR-IN-6)."""

from __future__ import annotations

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.team import DemoLineups

REGULATION_ROUNDS = 24
PISTOL_ROUNDS = (1, 13)
BUYS = ("pistol", "eco", "force", "full")

ROUND_COLUMNS = {
    "demo": pl.String, "ref": pl.String, "round_num": pl.Int32, "side": pl.String,
    "won": pl.Boolean, "end_reason": pl.String, "buy": pl.String, "opp_buy": pl.String,
    "equipment": pl.Int32, "opp_equipment": pl.Int32, "score_us": pl.Int32,
    "score_them": pl.Int32, "is_ot": pl.Boolean, "start_tick": pl.Int32,
    "freeze_end_tick": pl.Int32, "end_tick": pl.Int32, "official_end_tick": pl.Int32,
}  # fmt: skip


def classify_buy(round_num: int, equipment_value: int | None, cfg: AnalysisConfig) -> str:
    """Pistol rounds by number; otherwise by team equipment value at freeze end (Q1)."""
    if round_num in PISTOL_ROUNDS:
        return "pistol"
    value = equipment_value or 0
    if value < cfg.eco_max:
        return "eco"
    if value < cfg.force_max:
        return "force"
    return "full"


def team_rounds(lineups: DemoLineups, scouted: str, tables: dict[str, pl.DataFrame],
                cfg: AnalysisConfig, demo_label: str) -> pl.DataFrame:  # fmt: skip
    """One row per live round, from the scouted team's point of view."""
    rounds = tables["rounds"].filter(~pl.col("is_knife")).sort("round_num")
    economy = {(r["round_num"], r["side"]): r["equipment_value"]
               for r in tables["round_economy"].iter_rows(named=True)}  # fmt: skip
    rows, us, them = [], 0, 0
    for r in rounds.iter_rows(named=True):
        rn = r["round_num"]
        side = lineups.side(scouted, rn)
        opp = "CT" if side == "T" else "T"
        won = r["winner_side"] == side
        eq, opp_eq = economy.get((rn, side)), economy.get((rn, opp))
        rows.append({
            "demo": lineups.demo, "ref": f"{demo_label}:r{rn}", "round_num": rn, "side": side,
            "won": won, "end_reason": r["reason"], "buy": classify_buy(rn, eq, cfg),
            "opp_buy": classify_buy(rn, opp_eq, cfg), "equipment": eq, "opp_equipment": opp_eq,
            "score_us": us, "score_them": them, "is_ot": rn > REGULATION_ROUNDS,
            "start_tick": r["start_tick"], "freeze_end_tick": r["freeze_end_tick"],
            "end_tick": r["end_tick"], "official_end_tick": r["official_end_tick"],
        })  # fmt: skip
        us, them = (us + 1, them) if won else (us, them + 1)
    return pl.DataFrame(rows, schema=ROUND_COLUMNS)


def is_complete(winner: int, loser: int) -> bool:
    """MR12; overtime is MR3 (first to 4 of 6 per period). A surrender is incomplete."""
    if winner == 13 and loser <= 11:
        return True
    return winner >= 16 and loser >= 12 and (winner - 12) % 3 == 1 and winner - loser >= 2


def lineup_score(lineups: DemoLineups, tables: dict[str, pl.DataFrame]) -> dict[str, int]:
    """Rounds won per lineup, using each lineup's observed side per round."""
    wins = {"A": 0, "B": 0}
    for r in tables["rounds"].filter(~pl.col("is_knife")).iter_rows(named=True):
        winner = "A" if r["winner_side"] == lineups.side_of_a[r["round_num"]] else "B"
        wins[winner] += 1
    return wins


def match_result(rounds: pl.DataFrame) -> dict:
    """Final score from the scouted team's view, and whether the match was played out."""
    us = int(rounds["won"].sum())
    them = rounds.height - us
    return {"us": us, "them": them, "rounds": rounds.height,
            "complete": is_complete(max(us, them), min(us, them))}  # fmt: skip
