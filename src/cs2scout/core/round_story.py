"""One short story per round for the scouted team (owner decision 2026-11-16).

What a round looked like, as you would note it while watching the demo:
- where each player stood at the checkpoints, and each player's route through the map;
- the utility they threw;
- on T rounds, the hit: which site, when, where everyone was, and who was away from it;
- the opening duel and every kill;
- the plant and the result.

Times are on the round timer (1:55 when freeze time ends); after a plant they are
"plant+Ns". The AI brief reads these to find plays, lurks and rounds worth watching, and the
rounds drawer shows them. Players of the scouted team appear by nickname only, and
opponents as "opp".
"""

from __future__ import annotations

import math
from collections import defaultdict

import polars as pl

from cs2scout.core.economy import CHOICE_LABELS
from cs2scout.core.features import assign_rounds
from cs2scout.core.patterns import clock
from cs2scout.core.positions import PlaceIndex, positions_at
from cs2scout.core.zones import PlaceNameZones

NADES = {"smoke": "smoke", "flashbang": "flash", "molotov": "molly", "incendiary": "molly",
         "he": "HE"}  # fmt: skip
ENDINGS = {"terrorists_win": "CTs eliminated", "ct_win": "Ts eliminated",
           "target_bombed": "bomb exploded", "bomb_defused": "bomb defused",
           "target_saved": "time ran out"}  # fmt: skip
MIN_DWELL_S = 1.5  # a place a player only ran through faster than this is left out of a route
MAX_ROUTE_PLACES = 8  # longer routes keep the first places and the last one
SPAWNS = ("TSpawn", "CTSpawn")  # where every route starts: left out unless it is all there is
AWAY_UNITS = 1200.0  # this far from every teammate on the hit's side: away from the hit


def _when(seconds: float, plant_s: float | None) -> str:
    if plant_s is not None and seconds > plant_s + 0.5:
        return f"plant+{round(seconds - plant_s)}s"
    return clock(seconds)


def _site(value: str | None) -> str:
    text = str(value or "?")
    return text.removeprefix("Bombsite").removeprefix("bombsite_").upper() or "?"


def _where(rows: list[dict], names: dict[int, str]) -> str:
    """Players grouped by place: ``Apartments: a1, a2 · TopofMid: a3 · dead: a4``."""
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


def route_text(entered: list[tuple[str, float]], died_s: float | None = None) -> str:
    """``SideAlley 1:53 → Apartments 1:47 → BombsiteB 1:21 (dead 1:18)``.

    ``entered`` is each change of place in order, with the second it happened. A place
    left within ``MIN_DWELL_S`` is dropped, except the first and the last, so a player
    on the edge of two places, or running through one, does not fill the route. The
    spawn a route starts in is left out, since every route starts there.
    """
    kept = [(place, s) for i, (place, s) in enumerate(entered)
            if i in (0, len(entered) - 1) or entered[i + 1][1] - s >= MIN_DWELL_S]  # fmt: skip
    steps: list[tuple[str, float]] = []
    for place, s in kept:
        if not steps or steps[-1][0] != place:
            steps.append((place, s))
    if len(steps) > 1 and steps[0][0] in SPAWNS:
        steps = steps[1:]
    if len(steps) > MAX_ROUTE_PLACES:
        steps = steps[: MAX_ROUTE_PLACES - 1] + [("…", -1.0)] + steps[-1:]
    parts = [place if s < 0 or (i == 0 and place in SPAWNS) else f"{place} {clock(s)}"
             for i, (place, s) in enumerate(steps)] or ["?"]  # fmt: skip
    return " → ".join(parts) + (f" (dead {clock(died_s)})" if died_s is not None else "")


def away_from_hit(rows: list[dict], site: str, map_name: str,
                  zones: PlaceNameZones) -> list[int]:  # fmt: skip
    """Who is alive, off the hit's side of the map and far from every teammate on it."""
    alive = [r for r in rows if r["alive"] and r["x"] is not None]
    on_side = [r for r in alive if zones.zone(map_name, r["place"]).site == site]
    if not on_side:
        return []
    return [r["steamid"] for r in alive if r not in on_side and min(
        math.hypot(r["x"] - g["x"], r["y"] - g["y"]) for g in on_side) > AWAY_UNITS]  # fmt: skip


def round_stories(tables: dict[str, pl.DataFrame], rounds: pl.DataFrame, members: set[int],
                  names: dict[int, str], tick_rate: float, places: PlaceIndex,
                  checkpoints: tuple[int, ...], map_name: str = "",
                  hits: dict[str, tuple[str, float]] | None = None) -> list[dict]:  # fmt: skip
    """``[{ref, demo, round, side, tick, text}]``; ``tick`` is where watching should start.

    ``hits`` maps a T round's ref to the site it hit and the second it began (from the T
    patterns); rounds without one read "no clear hit".
    """
    if rounds.is_empty() or not members:
        return []
    ids = list(members)
    zones = PlaceNameZones()
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
    hit_s: dict[str, tuple[str, float]] = {}
    for ref, (site, s) in (hits or {}).items():
        if ref in info and info[ref]["side"] == "T":
            plant = plants.get(ref)
            hit_s[ref] = (site, min(s, secs(ref, plant["tick"])) if plant else s)

    snaps = tables["snapshots"].filter(pl.col("steamid").is_in(ids))
    at: dict[str, dict[float, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for r in positions_at(snaps, rounds, [float(s) for s in checkpoints],
                          tick_rate).iter_rows(named=True):  # fmt: skip
        at[r["ref"]][r["t"]].append(r)
    at_plant = _at_ticks(snaps, rounds, {ref: b["tick"] for ref, b in plants.items()}, tick_rate)
    at_hit = _at_ticks(snaps, rounds, {ref: info[ref]["freeze_end_tick"] + int(s * tick_rate)
                                       for ref, (_, s) in hit_s.items()}, tick_rate)  # fmt: skip
    routes = _routes(snaps, windows, info, plants, secs)

    nades: dict[str, list[dict]] = defaultdict(list)
    thrown = assign_rounds(tables["grenades"].filter(pl.col("thrower_steamid").is_in(ids)),
                           windows, "start_tick").sort("start_tick")  # fmt: skip
    for g in thrown.iter_rows(named=True):
        if g["ref"] in info and g["type"] in NADES:
            nades[g["ref"]].append(g)

    first_kill: dict[str, dict] = {}
    kills: dict[str, list[dict]] = defaultdict(list)
    for k in assign_rounds(tables["kills"], windows).sort("tick").iter_rows(named=True):
        if k["ref"] not in info or k["tick"] > info[k["ref"]]["end_tick"]:
            continue
        kills[k["ref"]].append(k)
        enemy = k["attacker_side"] is not None and k["attacker_side"] != k["victim_side"]
        if enemy:
            first_kill.setdefault(k["ref"], k)

    stories = []
    for ref, r in info.items():
        plant = plants.get(ref)
        plant_s = secs(ref, plant["tick"]) if plant else None
        ending = ENDINGS.get(r["end_reason"], str(r["end_reason"]).replace("_", " "))
        header = (f"{ref} · {r['side']} · {r['buy']} vs {r['opp_buy']} · score "
                  f"{r['score_us']}-{r['score_them']} · {'WON' if r['won'] else 'lost'} "
                  f"({ending})")  # fmt: skip
        if r.get("choice") in ("force", "save"):
            header += f" · {CHOICE_LABELS[r['choice']]}, ${r['money_pp']:,} a player"
        lines = [header]
        for t in sorted(at[ref]):
            lines.append(f"{clock(t)} {_where(at[ref][t], names)}")
        for sid, text in sorted(routes.get(ref, {}).items(), key=lambda kv: names.get(kv[0], "")):
            lines.append(f"route {names.get(sid, '?')}: {text}")
        lines.append(_utility(nades[ref], names, places, lambda tick, ref=ref: secs(ref, tick),
                              plant_s))  # fmt: skip
        if ref in hit_s:
            site, s = hit_s[ref]
            line = f"hit {_site(site)} {clock(s)}; at the hit {_where(at_hit[ref], names)}"
            away = away_from_hit(at_hit[ref], site, map_name, zones)
            if away:
                line += "; away from the hit: " + ", ".join(sorted(names.get(a, "?") for a in away))
            lines.append(line)
        elif hits is not None and r["side"] == "T":
            lines.append("no clear hit")
        k = first_kill.get(ref)
        if k is not None:
            lines.append(_opening(k, members, names, places, _when(secs(ref, k["tick"]), plant_s)))
        if kills[ref]:
            lines.append("kills: " + "; ".join(
                _kill(k, members, names, places, _when(secs(ref, k["tick"]), plant_s))
                for k in kills[ref]))  # fmt: skip
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


def _at_ticks(snaps: pl.DataFrame, rounds: pl.DataFrame, ticks: dict[str, int],
              tick_rate: float) -> dict[str, list[dict]]:  # fmt: skip
    """Every player's position at one tick per round (the plant, the hit)."""
    out: dict[str, list[dict]] = defaultdict(list)
    if not ticks:
        return out
    moments = rounds.filter(pl.col("ref").is_in(list(ticks))).with_columns(
        freeze_end_tick=pl.col("ref").replace_strict(ticks, return_dtype=pl.Int32)
    )
    for r in positions_at(snaps, moments, [0.0], tick_rate).iter_rows(named=True):
        out[r["ref"]].append(r)
    return out


def _routes(snaps: pl.DataFrame, windows: pl.DataFrame, info: dict[str, dict],
            plants: dict[str, dict], secs) -> dict[str, dict[int, str]]:  # fmt: skip
    """Per round and player: where they went from freeze end until they died or the plant."""
    live = assign_rounds(snaps, windows).sort("ref", "steamid", "tick")
    entered: dict[tuple[str, int], list[tuple[str, float]]] = defaultdict(list)
    died: dict[tuple[str, int], float] = {}
    for ref, sid, tick, place, health in live.select(
        "ref", "steamid", "tick", "place", "health"
    ).iter_rows():
        r = info.get(ref)
        stop = plants[ref]["tick"] if ref in plants else r["end_tick"] if r else -1
        key = (ref, sid)
        if r is None or tick < r["freeze_end_tick"] or tick > stop or key in died:
            continue
        if health <= 0:
            died[key] = secs(ref, tick)
            continue
        if place and (not entered[key] or entered[key][-1][0] != place):
            entered[key].append((place, secs(ref, tick)))
    out: dict[str, dict[int, str]] = defaultdict(dict)
    for (ref, sid), steps in entered.items():
        out[ref][sid] = route_text(steps, died.get((ref, sid)))
    return out


def _utility(nades: list[dict], names: dict[int, str], places: PlaceIndex, secs,
             plant_s: float | None) -> str:  # fmt: skip
    """``smoke Catwalk 1:55 (a2); flash BombsiteB 1:27, 1:26 (a3, a4)``."""
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


def _kill(k: dict, members: set[int], names: dict[int, str], places: PlaceIndex,
          when: str) -> str:  # fmt: skip
    """``1:31 a3 (Catwalk) > opp (Connector) ak47 (trade)``; a death to the world or a
    teammate reads ``1:02 a4 died (world)``."""

    def who(role: str) -> str:
        sid = k[f"{role}_steamid"]
        name = names.get(sid, "?") if sid in members else "opp"
        return f"{name} ({places.place(k[f'{role}_x'], k[f'{role}_y'])})"

    victim = names.get(k["victim_steamid"], "?") if k["victim_steamid"] in members else "opp"
    enemy = k["attacker_side"] is not None and k["attacker_side"] != k["victim_side"]
    if not enemy:
        return f"{when} {victim} died ({k['weapon'] or 'world'})"
    return (f"{when} {who('attacker')} > {who('victim')} {k['weapon'] or '?'}"
            + (" (trade)" if k["is_trade"] else ""))  # fmt: skip
