"""One short story per round for the scouted team (owner decision 2026-11-16).

What a round looked like, as you would note it while watching the demo: where each player
stood at the checkpoints, the utility they threw, the opening duel, the plant and the
result. Times are on the round timer (1:55 when freeze time ends); after a plant they are
"plant+Ns". The AI brief reads these to find lurk paths, pistol strats and rounds worth
watching, and the rounds drawer shows them. Players appear by nickname only.
"""

from __future__ import annotations

from collections import defaultdict

import polars as pl

from cs2scout.core.features import assign_rounds
from cs2scout.core.patterns import clock
from cs2scout.core.positions import PlaceIndex, positions_at

NADES = {"smoke": "smoke", "flashbang": "flash", "molotov": "molly", "incendiary": "molly",
         "he": "HE"}  # fmt: skip
ENDINGS = {"terrorists_win": "CTs eliminated", "ct_win": "Ts eliminated",
           "target_bombed": "bomb exploded", "bomb_defused": "bomb defused",
           "target_saved": "time ran out"}  # fmt: skip


def _when(seconds: float, plant_s: float | None) -> str:
    if plant_s is not None and seconds > plant_s + 0.5:
        return f"plant+{round(seconds - plant_s)}s"
    return clock(seconds)


def _site(value: str | None) -> str:
    text = str(value or "?")
    return text.removeprefix("Bombsite").removeprefix("bombsite_").upper() or "?"


def _where(rows: list[dict], names: dict[int, str]) -> str:
    """Players grouped by place: ``Apartments: rizzy, Zyrx · TopofMid: Ping · dead: Salty``."""
    by_place: dict[str, list[str]] = defaultdict(list)
    dead = []
    for r in sorted(rows, key=lambda r: names.get(r["steamid"], "")):
        name = names.get(r["steamid"], "?")
        if r["alive"]:
            by_place[r["place"] or "?"].append(name)
        else:
            dead.append(name)
    parts = [f"{place}: {', '.join(who)}"
             for place, who in sorted(by_place.items(), key=lambda kv: -len(kv[1]))]  # fmt: skip
    if dead:
        parts.append(f"dead: {', '.join(dead)}")
    return " · ".join(parts)


def round_stories(tables: dict[str, pl.DataFrame], rounds: pl.DataFrame, members: set[int],
                  names: dict[int, str], tick_rate: float, places: PlaceIndex,
                  checkpoints: tuple[int, ...]) -> list[dict]:  # fmt: skip
    """``[{ref, demo, round, side, tick, text}]``; ``tick`` is where watching should start."""
    if rounds.is_empty() or not members:
        return []
    ids = list(members)
    windows = rounds.sort("start_tick").with_columns(
        window_end=pl.col("start_tick").shift(-1).fill_null(2**31 - 1)
    )
    info = {r["ref"]: r for r in rounds.iter_rows(named=True)}

    def secs(ref: str, tick: int) -> float:
        return (tick - info[ref]["freeze_end_tick"]) / tick_rate

    plants: dict[str, dict] = {}
    for b in assign_rounds(tables["bomb"].filter(pl.col("event") == "finish_plant"),
                           windows).sort("tick").iter_rows(named=True):  # fmt: skip
        plants.setdefault(b["ref"], b)

    snaps = tables["snapshots"].filter(pl.col("steamid").is_in(ids))
    at: dict[str, dict[float, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in positions_at(snaps, rounds, [float(s) for s in checkpoints],
                          tick_rate).iter_rows(named=True):  # fmt: skip
        at[r["ref"]][r["t"]].append(r)
    at_plant: dict[str, list[dict]] = defaultdict(list)
    if plants:
        moments = rounds.filter(pl.col("ref").is_in(list(plants))).with_columns(
            freeze_end_tick=pl.col("ref").replace_strict(
                {ref: b["tick"] for ref, b in plants.items()}, return_dtype=pl.Int32)
        )  # fmt: skip
        for r in positions_at(snaps, moments, [0.0], tick_rate).iter_rows(named=True):
            at_plant[r["ref"]].append(r)

    nades: dict[str, list[dict]] = defaultdict(list)
    thrown = assign_rounds(tables["grenades"].filter(pl.col("thrower_steamid").is_in(ids)),
                           windows, "start_tick").sort("start_tick")  # fmt: skip
    for g in thrown.iter_rows(named=True):
        if g["ref"] in info and g["type"] in NADES:
            nades[g["ref"]].append(g)

    first_kill: dict[str, dict] = {}
    for k in assign_rounds(tables["kills"], windows).sort("tick").iter_rows(named=True):
        enemy = k["attacker_side"] is not None and k["attacker_side"] != k["victim_side"]
        if k["ref"] in info and enemy:
            first_kill.setdefault(k["ref"], k)

    stories = []
    for ref, r in info.items():
        plant = plants.get(ref)
        plant_s = secs(ref, plant["tick"]) if plant else None
        ending = ENDINGS.get(r["end_reason"], str(r["end_reason"]).replace("_", " "))
        lines = [f"{ref} · {r['side']} · {r['buy']} vs {r['opp_buy']} · score "
                 f"{r['score_us']}-{r['score_them']} · {'WON' if r['won'] else 'lost'} "
                 f"({ending})"]  # fmt: skip
        for t in sorted(at[ref]):
            lines.append(f"{clock(t)} {_where(at[ref][t], names)}")
        lines.append(_utility(nades[ref], names, places, lambda tick, ref=ref: secs(ref, tick),
                              plant_s))  # fmt: skip
        k = first_kill.get(ref)
        if k is not None:
            lines.append(_opening(k, members, names, places, _when(secs(ref, k["tick"]), plant_s)))
        if plant is not None:
            site = _site(plant["bombsite"])
            if r["side"] == "T":
                who = names.get(plant["steamid"])
                what = f"plant {site} {clock(plant_s)}" + (f" by {who}" if who else "")
            else:
                what = f"opponents planted {site} {clock(plant_s)}"
            lines.append(f"{what}; at plant {_where(at_plant[ref], names)}")
        stories.append({"ref": ref, "demo": r.get("demo_label"), "round": r["round_num"],
                        "side": r["side"], "tick": r["freeze_end_tick"],
                        "text": "\n".join(line for line in lines if line)})  # fmt: skip
    return stories


def _utility(nades: list[dict], names: dict[int, str], places: PlaceIndex, secs,
             plant_s: float | None) -> str:  # fmt: skip
    """``smoke Catwalk 1:55 (Zyrx); flash BombsiteB 1:27, 1:26 (Ping, Salty)``."""
    groups: dict[tuple[str, str], dict] = {}
    for g in nades:
        key = (NADES[g["type"]], places.place(g["land_x"], g["land_y"]))
        entry = groups.setdefault(key, {"times": [], "who": []})
        entry["times"].append(_when(secs(g["start_tick"]), plant_s))
        who = names.get(g["thrower_steamid"], "?")
        if who not in entry["who"]:
            entry["who"].append(who)
    if not groups:
        return "utility: none"
    parts = [f"{kind} {place} {', '.join(e['times'])} ({', '.join(e['who'])})"
             for (kind, place), e in groups.items()]  # fmt: skip
    return "utility: " + "; ".join(parts)


def _opening(k: dict, members: set[int], names: dict[int, str], places: PlaceIndex,
             when: str) -> str:  # fmt: skip
    weapon = k["weapon"] or "?"
    killer_at = places.place(k["attacker_x"], k["attacker_y"])
    victim_at = places.place(k["victim_x"], k["victim_y"])
    if k["attacker_steamid"] in members:
        who = names.get(k["attacker_steamid"], "?")
        return (
            f"opening kill: {who} ({weapon}) from {killer_at} on an opponent at {victim_at} {when}"
        )
    if k["victim_steamid"] in members:
        who = names.get(k["victim_steamid"], "?")
        return f"opening death: {who} at {victim_at} {when} ({weapon} from {killer_at})"
    return ""
