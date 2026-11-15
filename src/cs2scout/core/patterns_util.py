"""Grenade lineups, player habits and suggested roles (FR-UTIL-2, FR-PLR-1, FR-PLR-4). WU-12.

Lineups: throws that land and start in about the same spots, clustered per side and type.
Habits: where a player wins or loses the round's first duel, their weapon per buy type,
and clutches. Roles are rule-based suggestions shown with the numbers behind them; the
Analyst can override them (WU-13).
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.features import assign_rounds
from cs2scout.core.patterns import clock, median, pattern
from cs2scout.core.positions import PlaceIndex, positions_at
from cs2scout.core.zones import PlaceNameZones

KINDS = {"smoke": "smoke", "flashbang": "flash", "molotov": "molotov", "incendiary": "molotov",
         "he": "HE"}  # fmt: skip
LAND_RADIUS = 150.0
THROW_RADIUS = 300.0
WEAPON_AT_S = 20
LURK_AT_S = 30


@dataclass
class DemoUtil:
    """What one demo contributes; patterns are mined across all demos together."""

    throws: list[dict] = field(default_factory=list)
    first_duels: list[dict] = field(default_factory=list)
    weapons: list[dict] = field(default_factory=list)
    clutches: list[dict] = field(default_factory=list)
    spread: list[dict] = field(default_factory=list)  # T distance from teammates at 0:30


def demo_util(tables: dict[str, pl.DataFrame], rounds: pl.DataFrame, members: set[int],
              tick_rate: float, places: PlaceIndex) -> DemoUtil:  # fmt: skip
    out = DemoUtil()
    ids = list(members)
    windows = rounds.sort("start_tick").with_columns(
        window_end=pl.col("start_tick").shift(-1).fill_null(2**31 - 1)
    )
    meta = rounds.select("ref", "side", "buy", "won", "freeze_end_tick")
    info = {r["ref"]: r for r in meta.iter_rows(named=True)}

    nades = assign_rounds(tables["grenades"].filter(pl.col("thrower_steamid").is_in(ids)),
                          windows, "start_tick").join(meta, on="ref")  # fmt: skip
    for g in nades.sort("ref", "start_tick").iter_rows(named=True):
        kind = KINDS.get(g["type"])
        if kind is None or g["land_x"] is None:
            continue
        out.throws.append({
            "ref": g["ref"], "side": g["side"], "kind": kind, "thrower": g["thrower_steamid"],
            "s": (g["start_tick"] - g["freeze_end_tick"]) / tick_rate,
            "throw": (g["throw_x"], g["throw_y"]), "land": (g["land_x"], g["land_y"]),
            "throw_place": places.place(g["throw_x"], g["throw_y"]),
            "land_place": places.place(g["land_x"], g["land_y"]),
        })  # fmt: skip

    kills = assign_rounds(tables["kills"], windows).sort("tick")
    for ref, grp in kills.group_by("ref", maintain_order=True):
        ref = ref[0] if isinstance(ref, tuple) else ref
        if ref not in info:
            continue
        first = grp.row(0, named=True)
        side = info[ref]["side"]
        if first["victim_steamid"] in members:
            spot = places.place(first["victim_x"], first["victim_y"])
            out.first_duels.append({"ref": ref, "side": side, "won": False, "place": spot,
                                    "player": first["victim_steamid"]})  # fmt: skip
        enemy = first["attacker_side"] != first["victim_side"]
        if first["attacker_steamid"] in members and enemy:
            spot = places.place(first["attacker_x"], first["attacker_y"])
            out.first_duels.append({"ref": ref, "side": side, "won": True, "place": spot,
                                    "player": first["attacker_steamid"]})  # fmt: skip
        out.clutches.extend(_clutch(ref, grp, tables, info[ref], members))

    snaps = tables["snapshots"]
    held = positions_at(snaps.filter(pl.col("steamid").is_in(ids)), rounds, [WEAPON_AT_S],
                        tick_rate, columns=("primary_weapon",)).filter("alive")  # fmt: skip
    for ref, steamid, gun in held.select("ref", "steamid", "primary_weapon").iter_rows():
        if gun:
            out.weapons.append({"ref": ref, "player": steamid, "buy": info[ref]["buy"],
                                "weapon": gun})  # fmt: skip

    t_rounds = rounds.filter(pl.col("side") == "T")
    at30 = positions_at(snaps.filter(pl.col("steamid").is_in(ids)), t_rounds, [LURK_AT_S],
                        tick_rate).filter("alive")  # fmt: skip
    for ref, grp in at30.group_by("ref", maintain_order=True):
        ref = ref[0] if isinstance(ref, tuple) else ref
        pts = list(grp.select("steamid", "x", "y").iter_rows())
        if len(pts) < 3:
            continue
        for steamid, x, y in pts:
            others = [(ox, oy) for s, ox, oy in pts if s != steamid]
            cx = sum(o[0] for o in others) / len(others)
            cy = sum(o[1] for o in others) / len(others)
            out.spread.append(
                {"ref": ref, "player": steamid, "distance": math.hypot(x - cx, y - cy)}
            )
    return out


def _clutch(ref: str, kills: pl.DataFrame, tables: dict[str, pl.DataFrame], round_info: dict,
            members: set[int]) -> list[dict]:  # fmt: skip
    """1vX: our last player alive while enemies remain (FR-PLR-4)."""
    start = tables["snapshots"].filter(
        (pl.col("tick") - round_info["freeze_end_tick"]).abs() <= 16
    ).group_by("steamid").last()  # fmt: skip
    ours = {s for s in start["steamid"] if s in members}
    theirs = {s for s in start["steamid"] if s not in members}
    for victim in kills["victim_steamid"]:
        ours.discard(victim)
        theirs.discard(victim)
        if len(ours) == 1 and theirs:
            return [{"ref": ref, "player": next(iter(ours)), "vs": len(theirs),
                     "won": round_info["won"]}]  # fmt: skip
    return []


def mine_util(demos: list[DemoUtil], ct_positions: dict[int, dict], ct_rotation: dict[int, dict],
              players_rounds: pl.DataFrame, keys: dict[int, str], map_name: str,
              cfg: AnalysisConfig) -> list[dict]:  # fmt: skip
    out: list[dict] = []
    throws = [t for d in demos for t in d.throws]
    by_group: dict[tuple, list[dict]] = defaultdict(list)
    for t in throws:
        by_group[(t["side"], t["kind"])].append(t)
    for (side, kind), items in sorted(by_group.items()):
        for cluster in _cluster_throws(items):
            refs = {t["ref"] for t in cluster}
            if len(refs) < 2:
                continue
            land_place = Counter(t["land_place"] for t in cluster).most_common(1)[0][0]
            throw_place = Counter(t["throw_place"] for t in cluster).most_common(1)[0][0]
            lx, ly = _mid(cluster, "land")
            tx, ty = _mid(cluster, "throw")
            when = median(t["s"] for t in cluster)
            throwers = Counter(keys.get(t["thrower"], "?") for t in cluster)
            out.append(pattern("util.lineup", (side, kind, round(lx / 100), round(ly / 100)),
                               "team", f"{kind.capitalize()} into {land_place} from {throw_place}"
                               f" ~{clock(when)}", {
                "type": kind, "side": side, "land_place": land_place, "throw_place": throw_place,
                "land": [round(lx), round(ly)], "throw": [round(tx), round(ty)],
                "median_s": when, "throws": len(cluster),
                "throwers": [{"player": k, "throws": n} for k, n in throwers.most_common()],
            }, {"side": side}, refs))  # fmt: skip

    # Distinct titles for distinct lineups that land and start in the same named places.
    seen_titles: Counter = Counter()
    for p in sorted((p for p in out if p["kind"] == "util.lineup"),
                    key=lambda p: -len(p["all_refs"])):  # fmt: skip
        seen_titles[p["title"]] += 1
        if seen_titles[p["title"]] > 1:
            p["title"] += f" (spot {seen_titles[p['title']]})"

    duels = [d for demo in demos for d in demo.first_duels if d["player"] in keys]
    groups: dict[tuple, list[str]] = defaultdict(list)
    for d in duels:
        groups[(keys[d["player"]], d["side"], d["won"], d["place"])].append(d["ref"])
    for (key, side, won, place), refs in groups.items():
        if len(refs) >= 2:
            what = f"Takes the opening kill at {place}" if won else f"Dies first at {place}"
            out.append(pattern("plr.habit", ("opening", side, won, place), key, what,
                               {"habit": "opening_kill" if won else "opening_death",
                                "side": side, "place": place},
                               {"side": side, "player": key}, refs, stat=True))  # fmt: skip

    weapons = [w for demo in demos for w in demo.weapons if w["player"] in keys]
    by_buy: dict[tuple, Counter] = defaultdict(Counter)
    refs_by: dict[tuple, list[str]] = defaultdict(list)
    for w in weapons:
        by_buy[(keys[w["player"]], w["buy"])][w["weapon"]] += 1
        refs_by[(keys[w["player"]], w["buy"], w["weapon"])].append(w["ref"])
    for (key, buy), counts in by_buy.items():
        gun, _ = counts.most_common(1)[0]
        out.append(pattern("plr.weapon", (buy, gun), key, f"{gun.upper()} on {buy} buys",
                           {"buy": buy, "weapon": gun, "rounds_seen": sum(counts.values())},
                           {"buy": buy, "player": key}, refs_by[(key, buy, gun)],
                           stat=True))  # fmt: skip

    clutches = [c for demo in demos for c in demo.clutches if c["player"] in keys]
    per_player: dict[str, list[dict]] = defaultdict(list)
    for c in clutches:
        per_player[keys[c["player"]]].append(c)
    for key, cs in per_player.items():
        won = sum(1 for c in cs if c["won"])
        sizes = Counter(f"1v{c['vs']}" for c in cs)
        out.append(pattern("plr.clutch", (), key, f"Clutches: {won} of {len(cs)} won", {
            "attempts": len(cs), "won": won, "by_size": dict(sorted(sizes.items())),
        }, {"player": key}, [c["ref"] for c in cs], stat=True))  # fmt: skip

    out.extend(_roles(demos, ct_positions, ct_rotation, players_rounds, keys, map_name))
    return out


def _cluster_throws(items: list[dict]) -> list[list[dict]]:
    clusters: list[tuple[dict, list[dict]]] = []
    for t in sorted(items, key=lambda t: (t["ref"], t["s"])):
        for seed, members in clusters:
            if (math.dist(seed["land"], t["land"]) <= LAND_RADIUS
                    and math.dist(seed["throw"], t["throw"]) <= THROW_RADIUS):  # fmt: skip
                members.append(t)
                break
        else:
            clusters.append((t, [t]))
    # Second pass: merge clusters whose medians ended up within the radii (seed order effect).
    merged: list[list[dict]] = []
    for _, members in clusters:
        for other in merged:
            if (
                math.dist(_mid(other, "land"), _mid(members, "land")) <= LAND_RADIUS
                and math.dist(_mid(other, "throw"), _mid(members, "throw")) <= THROW_RADIUS
            ):
                other.extend(members)
                break
        else:
            merged.append(list(members))
    return merged


def _mid(throws: list[dict], key: str) -> tuple[float, float]:
    return (statistics.median(t[key][0] for t in throws),
            statistics.median(t[key][1] for t in throws))  # fmt: skip


def _roles(demos: list[DemoUtil], ct_positions: dict[int, dict], ct_rotation: dict[int, dict],
           players_rounds: pl.DataFrame, keys: dict[int, str],
           map_name: str) -> list[dict]:  # fmt: skip
    zones = PlaceNameZones()
    metrics: dict[int, dict] = {}
    for steamid in keys:
        mine = players_rounds.filter(pl.col("steamid") == steamid)
        t_rows = mine.filter(pl.col("side") == "T")
        guns = [w["weapon"] for d in demos for w in d.weapons if w["player"] == steamid]
        spread = [s["distance"] for d in demos for s in d.spread if s["player"] == steamid]
        pos = ct_positions.get(steamid, {})
        rot = ct_rotation.get(steamid, {})
        metrics[steamid] = {
            "rounds": mine.height,
            "awp_share": round(guns.count("awp") / len(guns), 2) if guns else 0.0,
            "t_opening_rate": round((t_rows["opening_kill"] | t_rows["opening_death"]).sum()
                                    / t_rows.height, 2) if t_rows.height else 0.0,
            "flashes_per_round": round(mine["flashes"].sum() / mine.height, 2)
            if mine.height else 0.0,
            "t_spread": round(statistics.mean(spread)) if spread else 0,
            "ct_main_share": round(pos.get("share", 0.0), 2),
            "ct_main_place": pos.get("main"),
            "rotation_rate": round(rot["rotated"] / rot["considered"], 2)
            if rot.get("considered", 0) >= 3 else 0.0,
        }  # fmt: skip
    if not metrics:
        return []

    def top(metric: str) -> int:
        return max(metrics, key=lambda s: (metrics[s][metric], -s))

    spreads = sorted(m["t_spread"] for m in metrics.values())
    typical = statistics.median(spreads) if spreads else 0
    roles: dict[int, list[str]] = {s: [] for s in metrics}
    for s, m in metrics.items():
        if m["awp_share"] >= 0.4:
            roles[s].append("AWPer")
        main = m["ct_main_place"]
        if m["ct_main_share"] >= 0.6 and main and zones.zone(map_name, main).on_site:
            roles[s].append("Anchor")
    if metrics[top("t_opening_rate")]["t_opening_rate"] >= 0.2:
        roles[top("t_opening_rate")].append("Entry")
    lurker = top("t_spread")
    if metrics[lurker]["t_spread"] >= max(600, 1.3 * typical):
        roles[lurker].append("Lurker")
    if metrics[top("flashes_per_round")]["flashes_per_round"] >= 0.6:
        roles[top("flashes_per_round")].append("Support")
    if metrics[top("rotation_rate")]["rotation_rate"] >= 0.4:
        roles[top("rotation_rate")].append("Rotator")

    out = []
    for s, m in metrics.items():
        refs = players_rounds.filter(pl.col("steamid") == s)["ref"].to_list()
        title = ", ".join(roles[s]) or "No clear role"
        out.append(pattern("plr.role", (), keys[s], title, {"roles": roles[s], "metrics": m},
                           {"player": keys[s]}, refs, stat=True))  # fmt: skip
    return out
