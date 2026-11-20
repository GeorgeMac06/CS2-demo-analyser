"""Economy reads (issue #6): when the team forces, saves or full-buys, and what it buys.

Per round of the scouted team, money is read twice from the snapshots: at round start (cash
plus the gear players kept) and at freeze end, after buying. The round's *buy type* is:

- ``full``: the buy class is "full" (team equipment at freeze end reaches ``force_max``);
- ``save``: not a full buy, and the team kept at least half of its cash;
- ``force``: not a full buy, and the team spent more than half of its cash.

Pistol rounds have no buy type. Patterns are then mined for the rounds after each pistol,
by situation (money, score, the previous round), for saving guns in lost rounds, and for
the guns and plays on force buys and saves. Each pattern's ``n`` is the set of rounds in its
situation (``eligible_refs``), so filters recount it like any other pattern.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import polars as pl

from cs2scout.core.patterns import pattern
from cs2scout.core.rounds import PISTOL_ROUNDS, REGULATION_ROUNDS

BUY_TYPES = ("full", "force", "save")
BUY_TYPE_LABELS = {"full": "full buy", "force": "force buy", "save": "save"}
SAVE_KEEPS = 0.5  # a save keeps at least half of the team's cash
LOADOUT_WINDOW_S = 10  # a player's pistol is the one they hold in the first seconds
ARMOR_PLAYERS = 3  # "armor" on a buy: at least this many players have it

DEFAULT_PISTOLS = frozenset({"glock", "usp_silencer", "hkp2000"})
PISTOLS = DEFAULT_PISTOLS | {"p250", "tec9", "fiveseven", "cz75a", "deagle", "elite", "revolver"}
GUN_NAMES = {
    "ak47": "AK-47", "m4a1": "M4A4", "m4a1_silencer": "M4A1-S", "awp": "AWP",
    "galilar": "Galil AR", "famas": "FAMAS", "ssg08": "SSG 08", "sg556": "SG 553",
    "aug": "AUG", "g3sg1": "G3SG1", "scar20": "SCAR-20", "mac10": "MAC-10", "mp9": "MP9",
    "mp7": "MP7", "mp5sd": "MP5-SD", "ump45": "UMP-45", "p90": "P90", "bizon": "PP-Bizon",
    "nova": "Nova", "xm1014": "XM1014", "sawedoff": "Sawed-Off", "mag7": "MAG-7",
    "m249": "M249", "negev": "Negev", "deagle": "Desert Eagle", "p250": "P250",
    "tec9": "Tec-9", "fiveseven": "Five-SeveN", "cz75a": "CZ75-Auto",
    "elite": "Dual Berettas", "revolver": "R8 Revolver", "armor": "Armor (3+ players)",
}  # fmt: skip

# Money per player at round start (cash + kept gear): a rifle with armor costs about
# $3,700 and a full buy with utility about $5,000.
MONEY_BANDS = ((2000, "Under $2,000 a player"), (3500, "$2,000–3,499 a player"),
               (5000, "$3,500–4,999 a player"), (None, "$5,000+ a player"))  # fmt: skip
SCORE_BANDS = ("Behind by 3+", "Score within 2", "Ahead by 3+")
PREVIOUS = ("After losing a full buy", "After losing a force or save", "After a win")


def gun_name(gun: str) -> str:
    return GUN_NAMES.get(gun, gun.replace("_", " ").title())


@dataclass
class EcoRound:
    ref: str
    side: str
    round_num: int
    won: bool
    buy: str
    is_ot: bool
    score_us: int
    score_them: int
    money_start: int = 0  # team cash at round start
    gear_start: int = 0  # equipment value players kept from the last round
    money_left: int = 0  # team cash after buying (freeze end)
    players: int = 0
    buy_type: str | None = None  # full / force / save; None on pistol rounds
    guns: Counter = field(default_factory=Counter)  # bought or kept, default pistols left out
    survivors: dict[int, str | None] = field(default_factory=dict)  # steamid -> primary
    previous: EcoRound | None = None  # the round before, in the same half

    @property
    def money_pp(self) -> int:
        return round((self.money_start + self.gear_start) / self.players) if self.players else 0


def buy_type_of(buy: str, money_start: int | None, money_left: int) -> str | None:
    """None for a pistol round, or when the money before buying was not seen."""
    if buy == "pistol" or (money_start is None and buy != "full"):
        return None
    if buy == "full":
        return "full"
    return "save" if money_start <= 0 or money_left >= SAVE_KEEPS * money_start else "force"


def half_start(round_num: int) -> bool:
    """Money resets: the pistol rounds, and the first round of each overtime half."""
    return round_num in PISTOL_ROUNDS or (
        round_num > REGULATION_ROUNDS and (round_num - REGULATION_ROUNDS - 1) % 3 == 0
    )


def eco_rounds(tables: dict[str, pl.DataFrame], rounds: pl.DataFrame, lineup: set[int],
               tick_rate: float) -> list[EcoRound]:  # fmt: skip
    """``rounds``: one demo's round index for the scouted team. ``lineup``: every player of
    the scouted lineup (team money counts all of them, stand-ins and excluded players too)."""
    snaps = tables["snapshots"].filter(pl.col("steamid").is_in(list(lineup)))
    deaths = tables["kills"].filter(pl.col("victim_steamid").is_in(list(lineup)))
    ticks = snaps["tick"].unique().sort()
    window = int(LOADOUT_WINDOW_S * tick_rate)

    def first_at(tick: int, before: int | None = None) -> pl.DataFrame:
        later = ticks.filter(ticks >= tick)
        if later.is_empty() or (before is not None and later[0] >= before):
            return snaps.clear()
        return snaps.filter(pl.col("tick") == later[0])

    out: list[EcoRound] = []
    prev: EcoRound | None = None
    for r in rounds.sort("round_num").iter_rows(named=True):
        obs = EcoRound(r["ref"], r["side"], r["round_num"], r["won"], r["buy"], r["is_ot"],
                       r["score_us"], r["score_them"])  # fmt: skip
        start = first_at(r["start_tick"], before=r["freeze_end_tick"])
        bought = first_at(r["freeze_end_tick"])
        obs.money_start = int(start["money"].sum() or 0)
        obs.gear_start = int(start["equipment_value"].sum() or 0)
        obs.money_left = int(bought["money"].sum() or 0)
        obs.players = bought.height or start.height
        obs.buy_type = buy_type_of(
            r["buy"], obs.money_start if start.height else None, obs.money_left
        )

        early = snaps.filter(pl.col("tick").is_between(r["freeze_end_tick"],
                                                       r["freeze_end_tick"] + window))  # fmt: skip
        for _steamid, grp in early.sort("tick").group_by("steamid", maintain_order=True):
            primary = grp["primary_weapon"].drop_nulls()
            if primary.len():
                obs.guns[primary[0]] += 1
                continue
            pistols = [w for w in grp["active_weapon"].drop_nulls() if w in PISTOLS]
            if pistols:
                gun = Counter(pistols).most_common(1)[0][0]
                if gun not in DEFAULT_PISTOLS:
                    obs.guns[gun] += 1
        if (bought["armor"] > 0).sum() >= ARMOR_PLAYERS:
            obs.guns["armor"] += 1

        # The last death often falls between two snapshots, so the kills decide who lived.
        died = set(deaths.filter(pl.col("tick").is_between(r["start_tick"], r["end_tick"]))[
            "victim_steamid"])  # fmt: skip
        last = snaps.filter(pl.col("tick") <= r["end_tick"]).filter(
            pl.col("tick") == pl.col("tick").max()
        )
        obs.survivors = {s: w for s, h, w in last.select("steamid", "health", "primary_weapon")
                         .iter_rows() if h > 0 and s not in died}  # fmt: skip
        obs.previous = None if half_start(r["round_num"]) else prev
        out.append(obs)
        prev = obs
    return out


def money_band(money_pp: int) -> str:
    return next(label for top, label in MONEY_BANDS if top is None or money_pp < top)


def score_band(us: int, them: int) -> str:
    diff = us - them
    return SCORE_BANDS[0] if diff <= -3 else SCORE_BANDS[2] if diff >= 3 else SCORE_BANDS[1]


def previous_band(prev: EcoRound | None) -> str | None:
    if prev is None or prev.buy == "pistol" or prev.buy_type is None:
        return None  # first round of a half, or right after a pistol (see the pistol reads)
    if prev.won:
        return PREVIOUS[2]
    return PREVIOUS[0] if prev.buy_type == "full" else PREVIOUS[1]


def situations(r: EcoRound) -> list[tuple[str, str]]:
    """(group, situation) pairs a decision round belongs to."""
    out = [("money", money_band(r.money_pp)), ("score", score_band(r.score_us, r.score_them))]
    prev = previous_band(r.previous)
    if prev:
        out.append(("previous", prev))
    if r.round_num in (12, REGULATION_ROUNDS):
        out.append(("moment", "Last round of a half"))
    if not r.is_ot and r.score_them == 12:
        out.append(("moment", "Facing match point"))
    return out


def pistol_context(r: EcoRound) -> tuple[str, ...] | None:
    """('won',) for the round after a won pistol; ('won', 'lost') for the round after that
    when the 2nd round was lost; None for other rounds."""
    prev = r.previous
    if prev is None or r.buy_type is None:
        return None
    result = lambda x: "won" if x.won else "lost"  # noqa: E731
    if prev.buy == "pistol":
        return (result(prev),)
    if prev.previous is not None and prev.previous.buy == "pistol":
        return (result(prev.previous), result(prev))
    return None


def pistol_title(ctx: tuple[str, ...], buy_type: str) -> str:
    if len(ctx) == 1:
        return f"2nd round, pistol {ctx[0]}: {BUY_TYPE_LABELS[buy_type]}"
    return f"3rd round, pistol {ctx[0]}, 2nd round {ctx[1]}: {BUY_TYPE_LABELS[buy_type]}"


def mine_eco(rounds: list[EcoRound], plays_t: dict[str, tuple[str | None, str]],
             stacks_ct: dict[str, str], keys: dict[int, str]) -> list[dict]:  # fmt: skip
    """``plays_t``: T round ref -> (site hit, tempo). ``stacks_ct``: CT round ref -> stack."""
    out: list[dict] = []

    def by_buy_type(kind: str, key: tuple, title: str, params: dict, eligible: dict,
                  members: list[EcoRound]) -> None:  # fmt: skip
        """One pattern per buy type seen among ``members`` (n = all of them)."""
        refs = [r.ref for r in members]
        for buy_type in BUY_TYPES:
            mine = [r.ref for r in members if r.buy_type == buy_type]
            if mine:
                out.append(pattern(kind, (*key, buy_type), "team",
                                   f"{title}: {BUY_TYPE_LABELS[buy_type]}",
                                   params | {"buy_type": buy_type}, eligible, mine,
                                   eligible_refs=refs))  # fmt: skip

    contexts: dict[tuple[str, ...], list[EcoRound]] = defaultdict(list)
    for r in rounds:
        ctx = pistol_context(r)
        if ctx:
            contexts[ctx].append(r)
    for ctx, members in sorted(contexts.items()):
        refs = [r.ref for r in members]
        for buy_type in BUY_TYPES:
            mine = [r.ref for r in members if r.buy_type == buy_type]
            if mine:
                out.append(pattern("eco.pistol", (ctx, buy_type), "team",
                                   pistol_title(ctx, buy_type),
                                   {"after": list(ctx), "buy_type": buy_type}, {}, mine,
                                   eligible_refs=refs))  # fmt: skip

    decisions = [r for r in rounds if r.buy_type is not None]
    groups: dict[tuple[str, str], list[EcoRound]] = defaultdict(list)
    for r in decisions:
        for group, label in situations(r):
            groups[(group, label)].append(r)
    for (group, label), members in sorted(groups.items()):
        by_buy_type("eco.situation", (group, label), label, {"group": group, "situation": label},
                  {}, members)  # fmt: skip

    for side in ("T", "CT"):
        lost = [r for r in decisions if r.side == side and not r.won and r.buy_type != "save"]
        saved = [r for r in lost if any(w for w in r.survivors.values())]
        if saved:
            guns = Counter(gun_name(w) for r in saved for w in r.survivors.values() if w)
            savers = Counter(keys[s] for r in saved for s, w in r.survivors.items()
                             if w and s in keys)  # fmt: skip
            out.append(pattern("eco.exit", (side,), "team",
                               f"Saves guns in a lost {side} round", {
                                   "side": side, "guns": dict(guns.most_common(4)),
                                   "players": [{"player": k, "rounds": n}
                                               for k, n in savers.most_common(3)],
                               }, {"side": side}, [r.ref for r in saved],
                               eligible_refs=[r.ref for r in lost]))  # fmt: skip

        for buy_type in ("force", "save"):
            mine = [r for r in decisions if r.side == side and r.buy_type == buy_type]
            refs = [r.ref for r in mine]
            if not mine:
                continue
            seen: dict[str, list[str]] = defaultdict(list)
            for r in mine:
                for gun in r.guns:
                    seen[gun].append(r.ref)
            for gun, gun_refs in seen.items():
                per_round = round(sum(r.guns[gun] for r in mine) / len(gun_refs), 1)
                title = f"{side} {BUY_TYPE_LABELS[buy_type]}: {gun_name(gun)}"
                if gun != "armor":
                    title += f" (×{per_round:g} when bought)"
                out.append(pattern("eco.guns", (side, buy_type, gun), "team", title, {
                    "side": side, "buy_type": buy_type, "gun": gun, "per_round": per_round,
                }, {"side": side}, gun_refs, eligible_refs=refs))  # fmt: skip

            plays: dict[tuple, list[str]] = defaultdict(list)
            for r in mine:
                if side == "T" and r.ref in plays_t:
                    plays[plays_t[r.ref]].append(r.ref)
                elif side == "CT" and r.ref in stacks_ct:
                    plays[(stacks_ct[r.ref],)].append(r.ref)
            for play, play_refs in plays.items():
                if side == "T":
                    site, tempo = play
                    what = f"{site} {tempo}" if site else "no clear hit"
                else:
                    what = play[0]
                out.append(pattern("eco.play", (side, buy_type, *play), "team",
                                   f"{side} {BUY_TYPE_LABELS[buy_type]}: {what}",
                                   {"side": side, "buy_type": buy_type, "play": list(play)},
                                   {"side": side}, play_refs, eligible_refs=refs))  # fmt: skip
    return out


def round_columns(rounds: list[EcoRound]) -> pl.DataFrame:
    """Per-round economy columns joined onto the round index."""
    return pl.DataFrame(
        [{"ref": r.ref, "buy_type": r.buy_type, "money_pp": r.money_pp,
          "money_left": r.money_left} for r in rounds],
        schema={"ref": pl.String, "buy_type": pl.String, "money_pp": pl.Int32,
                "money_left": pl.Int32},
    )  # fmt: skip
