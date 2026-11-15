"""Team resolution (FR-TEAM-1..5, design §6.2).

Players are identified by SteamID. In each demo the ten players form two lineups: lineup A
is whoever played T in round 1. A lineup's side per round is *observed* at freeze end, not
derived from a swap rule (spike S-1). Across demos, the scouted team's core is the largest
group of players who keep turning up together on the same lineup.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

import polars as pl

from cs2scout.core.schema import SNAPSHOT_STRIDE_TICKS

LINEUPS = ("A", "B")


@dataclass(frozen=True)
class DemoLineups:
    demo: str
    members: dict[str, frozenset[int]]  # "A" / "B" -> steamids
    side_of_a: dict[int, str]  # round_num -> "T" / "CT"
    mixed_rounds: tuple[int, ...] = ()
    nicks: dict[int, str] = field(default_factory=dict)
    clans: dict[int, str | None] = field(default_factory=dict)

    def side(self, lineup: str, round_num: int) -> str:
        a = self.side_of_a[round_num]
        return a if lineup == "A" else ("CT" if a == "T" else "T")

    def lineup_of(self, steamid: int) -> str | None:
        return next((lu for lu, m in self.members.items() if steamid in m), None)


def demo_lineups(demo: str, tables: dict[str, pl.DataFrame]) -> DemoLineups:
    rounds = tables["rounds"].filter(~pl.col("is_knife")).sort("round_num")
    snaps = tables["snapshots"].select("tick", "steamid", "side").drop_nulls()
    starts = rounds.select("round_num", pl.col("freeze_end_tick").alias("tick")).sort("tick")
    at_start = _sides_at(starts, snaps)
    first_round = int(rounds["round_num"].min())
    t_round1 = set(
        at_start.filter((pl.col("round_num") == first_round) & (pl.col("side") == "T"))["steamid"]
    )
    members: dict[str, set[int]] = {"A": set(t_round1), "B": set()}
    side_of_a: dict[int, str] = {}
    mixed: list[int] = []
    for (rn,), grp in at_start.sort("round_num").group_by(["round_num"], maintain_order=True):
        sides = dict(zip(grp["steamid"], grp["side"], strict=True))
        a_sides = [s for p, s in sides.items() if p in members["A"]]
        if a_sides:
            side_a = Counter(a_sides).most_common(1)[0][0]
        else:  # nobody from A seen: infer from B
            b_sides = [s for p, s in sides.items() if p in members["B"]]
            side_a = "CT" if Counter(b_sides).most_common(1)[0][0] == "T" else "T"
        side_of_a[rn] = side_a
        for player, side in sides.items():
            lineup = "A" if side == side_a else "B"
            known = "A" if player in members["A"] else "B" if player in members["B"] else None
            if known is None:
                members[lineup].add(player)  # joined later (reconnect, substitute)
            elif known != lineup and rn not in mixed:
                mixed.append(rn)
    players = tables["players"]
    return DemoLineups(
        demo=demo,
        members={k: frozenset(v) for k, v in members.items()},
        side_of_a=side_of_a,
        mixed_rounds=tuple(mixed),
        nicks=dict(zip(players["steamid"], players["name"], strict=True)),
        clans=dict(zip(players["steamid"], players["team_clan_name"], strict=True)),
    )


def _sides_at(starts: pl.DataFrame, snaps: pl.DataFrame) -> pl.DataFrame:
    """Each player's side in their first snapshot within 1 s after each round's freeze end."""
    grid = starts.join(snaps.select("steamid").unique(), how="cross").sort("tick")
    return grid.join_asof(
        snaps.sort("tick"), on="tick", by="steamid", strategy="forward",
        tolerance=SNAPSHOT_STRIDE_TICKS * 4, check_sortedness=False,  # both sides sorted above
    ).drop_nulls("side")  # fmt: skip


@dataclass(frozen=True)
class RosterProposal:
    core: tuple[int, ...]
    standins: tuple[int, ...]
    scouted: dict[str, str | None]  # demo -> "A" / "B", or None when the team is not found
    nicks: dict[int, str]
    presence: dict[int, int]
    team_name: str | None
    needs_pick: bool  # too few demos or a tie: the Analyst must say which lineup


def propose_roster(demos: list[DemoLineups]) -> RosterProposal:
    """``demos`` in chronological order (the latest nickname wins, FR-TEAM-5)."""
    presence: Counter[int] = Counter()
    nicks: dict[int, str] = {}
    for d in demos:
        for members in d.members.values():
            presence.update(members)
        nicks.update(d.nicks)

    threshold = max(2, math.ceil(len(demos) / 2))
    candidates = {p for p, n in presence.items() if n >= threshold}
    clusters = _same_lineup_clusters(candidates, demos)
    ranked = sorted(clusters, key=lambda c: (len(c), sum(presence[p] for p in c)), reverse=True)
    tie = len(ranked) > 1 and (len(ranked[0]), sum(presence[p] for p in ranked[0])) == (
        len(ranked[1]), sum(presence[p] for p in ranked[1]))  # fmt: skip
    if not ranked or tie or len(ranked[0]) < 3:
        return RosterProposal((), (), {d.demo: None for d in demos}, nicks, dict(presence),
                              None, needs_pick=True)  # fmt: skip

    by_presence = sorted(ranked[0], key=lambda p: (-presence[p], p))
    core = tuple(sorted(by_presence[:5]))
    scouted = assign_lineups(demos, core)
    standins = sorted(
        {p for d in demos if scouted[d.demo] for p in d.members[scouted[d.demo]]} - set(core)
    )
    return RosterProposal(core, tuple(standins), scouted, nicks, dict(presence),
                          _team_name(demos, scouted), needs_pick=False)  # fmt: skip


def assign_lineups(demos: list[DemoLineups], core: tuple[int, ...] | set[int],
                   overrides: dict[str, str] | None = None) -> dict[str, str | None]:  # fmt: skip
    """The scouted lineup per demo: the one with >= 3 core players, unless overridden."""
    overrides = overrides or {}
    result: dict[str, str | None] = {}
    for d in demos:
        if d.demo in overrides:
            result[d.demo] = overrides[d.demo]
            continue
        counts = {lu: len(set(core) & d.members[lu]) for lu in LINEUPS}
        best = max(LINEUPS, key=lambda lu: counts[lu])
        result[d.demo] = best if counts[best] >= 3 else None
    return result


def _same_lineup_clusters(candidates: set[int], demos: list[DemoLineups]) -> list[set[int]]:
    parent = {p: p for p in candidates}

    def find(p: int) -> int:
        while parent[p] != p:
            parent[p] = parent[parent[p]]
            p = parent[p]
        return p

    for d in demos:
        for members in d.members.values():
            present = sorted(members & candidates)
            for other in present[1:]:
                parent[find(other)] = find(present[0])
    groups: dict[int, set[int]] = {}
    for p in candidates:
        groups.setdefault(find(p), set()).add(p)
    return list(groups.values())


def _team_name(demos: list[DemoLineups], scouted: dict[str, str | None]) -> str | None:
    names = Counter(
        d.clans.get(p)
        for d in demos
        if scouted[d.demo]
        for p in d.members[scouted[d.demo]]
        if d.clans.get(p)
    )
    return names.most_common(1)[0][0] if names else None
