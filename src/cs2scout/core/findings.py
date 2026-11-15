"""Findings Snapshot v1: the single output contract (design §5.4, ADR-004).

Every finding carries ``round_refs`` and a support ``{k, n, demos}`` computed from them
(invariant I-2). The same function builds the unfiltered snapshot and every filtered view
(S7), so a filter only restricts the round index and recounts.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.patterns import recount
from cs2scout.core.rounds import BUYS

SCHEMA_VERSION = 1
SIDES = ("T", "CT")


@dataclass(frozen=True)
class RoundFilter:
    side: str | None = None
    buy: tuple[str, ...] = ()
    opp_buy: tuple[str, ...] = ()
    demos: tuple[str, ...] = ()  # demo labels to keep (empty = all)
    date_from: str | None = None
    date_to: str | None = None
    include_ot: bool = True

    def apply(self, rounds: pl.DataFrame) -> pl.DataFrame:
        out = rounds
        if self.side:
            out = out.filter(pl.col("side") == self.side)
        if self.buy:
            out = out.filter(pl.col("buy").is_in(self.buy))
        if self.opp_buy:
            out = out.filter(pl.col("opp_buy").is_in(self.opp_buy))
        if self.demos:
            out = out.filter(pl.col("demo_label").is_in(self.demos))
        day = pl.col("played_at").str.slice(0, 10)  # filters are whole days (YYYY-MM-DD)
        if self.date_from:
            out = out.filter(day >= self.date_from)
        if self.date_to:
            out = out.filter(day <= self.date_to)
        if not self.include_ot:
            out = out.filter(~pl.col("is_ot"))
        return out


def _support(refs: list[str], n: int, rounds: pl.DataFrame) -> dict:
    demos = rounds.filter(pl.col("ref").is_in(refs))["demo_label"].n_unique() if refs else 0
    return {"k": len(refs), "n": n, "demos": demos}


def _recency(refs: list[str], rounds: pl.DataFrame, recent_labels: list[str]) -> dict:
    mine = rounds.filter(pl.col("ref").is_in(refs))
    if mine.height == 0:
        return {"last_seen": None, "share_last_3_demos": 0.0}
    recent = mine.filter(pl.col("demo_label").is_in(recent_labels)).height
    return {
        "last_seen": mine["played_at"].max(),
        "share_last_3_demos": round(recent / mine.height, 3),
    }


def _flags(n: int, cfg: AnalysisConfig) -> list[str]:
    return ["low_sample"] if n < cfg.low_sample_rounds else []


def _pct(a: float, b: float) -> float | None:
    return round(100 * a / b, 1) if b else None


def _per(a: float, b: float, digits: int = 2) -> float | None:
    return round(a / b, digits) if b else None


def build_findings(rounds: pl.DataFrame, players: pl.DataFrame, roster: list[dict],
                   cfg: AnalysisConfig, recent_labels: list[str]) -> list[dict]:  # fmt: skip
    """``rounds``: round index (filtered or not). ``players``: player-round features."""
    findings: list[dict] = []
    refs_all = set(rounds["ref"])
    players = players.filter(pl.col("ref").is_in(list(refs_all)))

    def add(fid: str, kind: str, subject: str, title: str, params: dict, eligible: dict,
            refs: list[str], n: int, outcome: dict | None = None) -> None:  # fmt: skip
        refs = sorted(refs)
        findings.append({
            "id": fid, "kind": kind, "subject": subject, "title": title, "params": params,
            "eligible": eligible, "round_refs": refs, "support": _support(refs, n, rounds),
            "outcome": outcome or {}, "recency": _recency(refs, rounds, recent_labels),
            "flags": _flags(n, cfg),
        })  # fmt: skip

    for side in SIDES:
        side_rounds = rounds.filter(pl.col("side") == side)
        for buy in ("all", *BUYS):
            subset = side_rounds if buy == "all" else side_rounds.filter(pl.col("buy") == buy)
            if subset.height == 0:
                continue
            won = subset.filter(pl.col("won"))["ref"].to_list()
            add(f"team.winrate.{side}.{buy}", "team.winrate", "team",
                f"{side} win rate ({buy})", {"side": side, "buy": buy,
                "win_pct": _pct(len(won), subset.height)}, {"side": side, "buy": buy},
                won, subset.height, {"won": len(won)})  # fmt: skip

    for member in roster:
        key, steamid = member["player_key"], member["steamid"]
        mine = players.filter(pl.col("steamid") == steamid)
        for side in (*SIDES, "all"):
            rows = mine if side == "all" else mine.filter(pl.col("side") == side)
            eligible_n = rounds.height if side == "all" else rounds.filter(
                pl.col("side") == side).height  # fmt: skip
            if rows.height == 0:
                continue
            refs = rows["ref"].to_list()
            r = rows.height
            s = {c: rows[c].sum() for c in (
                "kills", "deaths", "assists", "headshots", "damage", "utility_damage",
                "trade_kills", "smokes", "flashes", "hes", "molotovs", "enemies_flashed",
                "team_flashed", "flash_assists", "saved_utility")}  # fmt: skip
            add(f"plr.stats.{key}.{side}", "plr.stats", key, f"{member['nick']} ({side})", {
                "side": side, "rounds": r, "kills": s["kills"], "deaths": s["deaths"],
                "assists": s["assists"], "kd": _per(s["kills"], s["deaths"]),
                "adr": _per(s["damage"], r, 1), "kast_pct": _pct(rows["kast"].sum(), r),
                "hs_pct": _pct(s["headshots"], s["kills"]),
                "trade_kills": s["trade_kills"], "traded_deaths": int(rows["traded_death"].sum()),
            }, {"side": side}, refs, eligible_n)  # fmt: skip

            ok, od = int(rows["opening_kill"].sum()), int(rows["opening_death"].sum())
            opening_refs = rows.filter(pl.col("opening_kill") | pl.col("opening_death"))["ref"]
            add(f"plr.openings.{key}.{side}", "plr.openings", key,
                f"{member['nick']} opening duels ({side})", {
                "side": side, "attempts": ok + od, "kills": ok, "deaths": od,
                "success_pct": _pct(ok, ok + od), "attempt_pct": _pct(ok + od, r),
            }, {"side": side}, opening_refs.to_list(), r, {"won": ok})  # fmt: skip

            thrown = s["smokes"] + s["flashes"] + s["hes"] + s["molotovs"]
            by_buy = {
                buy: _per(
                    grp.select(pl.sum_horizontal("smokes", "flashes", "hes", "molotovs"))
                    .to_series()
                    .sum(),
                    grp.height,
                )  # fmt: skip
                for (buy,), grp in rows.join(rounds.select("ref", "buy"), on="ref").group_by(
                    ["buy"], maintain_order=True
                )
            }
            add(f"util.player.{key}.{side}", "util.player", key,
                f"{member['nick']} utility ({side})", {
                "side": side, "thrown_per_round": _per(thrown, r),
                "per_round": {k: _per(s[k], r) for k in ("smokes", "flashes", "hes", "molotovs")},
                "thrown_per_round_by_buy": dict(sorted(by_buy.items())),
                "enemies_flashed": s["enemies_flashed"],
                "enemies_per_flash": _per(s["enemies_flashed"], s["flashes"]),
                "flash_duration": round(float(rows["flash_duration"].sum()), 1),
                "team_flashed": s["team_flashed"], "flash_assists": s["flash_assists"],
                "utility_damage_per_round": _per(s["utility_damage"], r, 1),
                "saved_per_round": _per(s["saved_utility"], r),
            }, {"side": side}, refs, eligible_n)  # fmt: skip
    return sorted(findings, key=lambda f: f["id"])


def all_findings(
    rounds: pl.DataFrame,
    players: pl.DataFrame,
    roster: list[dict],
    patterns: list[dict],
    cfg: AnalysisConfig,
    recent_labels: list[str],
) -> list[dict]:
    """Stats rebuilt for ``rounds`` plus mined patterns recounted for them (one code path for
    the snapshot and every filtered view, so they cannot disagree)."""
    keys = {m["steamid"]: m["player_key"] for m in roster}
    in_view = players.filter(pl.col("ref").is_in(rounds["ref"].implode()))
    player_refs: dict[str, set[str]] = {}
    for steamid, ref in in_view.select("steamid", "ref").iter_rows():
        if steamid in keys:
            player_refs.setdefault(keys[steamid], set()).add(ref)
    stats = build_findings(rounds, players, roster, cfg, recent_labels)
    mined = recount(patterns, rounds, player_refs, cfg, recent_labels)
    return sorted(stats + mined, key=lambda f: f["id"])


ROUND_INDEX_FIELDS = (
    "ref", "demo_label", "round_num", "side", "buy", "opp_buy", "score_us", "score_them",
    "won", "end_reason", "played_at", "is_ot", "planted",
)  # fmt: skip


def round_index_json(rounds: pl.DataFrame) -> list[dict]:
    return rounds.select(ROUND_INDEX_FIELDS).sort("played_at", "demo_label", "round_num").to_dicts()
