"""CT-side patterns (FR-CT-1..5; design §6.3). WU-11.

Per CT round: where each player stands at 0:20 and the team setup that makes, early duels,
the first enemy contact on a site and who rotates to it, and what happens after a plant.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.features import assign_rounds
from cs2scout.core.patterns import describe, median, pattern, signature
from cs2scout.core.positions import PlaceIndex, positions_at
from cs2scout.core.zones import PlaceNameZones

SETUP_AT_S = 20
EARLY_S = 20
CONTACT_PLAYERS = 2  # enemies on a site at once = contact
RETAKE_PLAYERS = 2


@dataclass
class CTRound:
    ref: str
    buy: str
    won: bool
    places: dict[int, str] = field(default_factory=dict)  # steamid -> place at 0:20 (alive)
    setup: tuple = ()
    early: list[dict] = field(default_factory=list)  # {steamid, won, place}
    contact_site: str | None = None
    rotations: dict[int, float | None] = field(default_factory=dict)
    plant_site: str | None = None
    retake: bool = False
    saved: bool = False


def ct_rounds(tables: dict[str, pl.DataFrame], rounds: pl.DataFrame, members: set[int],
              map_name: str, tick_rate: float, places: PlaceIndex,
              zones: PlaceNameZones | None = None) -> list[CTRound]:  # fmt: skip
    zones = zones or PlaceNameZones()
    ct = rounds.filter(pl.col("side") == "CT")
    if ct.height == 0:
        return []
    zone = lambda place: zones.zone(map_name, place)  # noqa: E731
    ids = list(members)
    # Windows from *all* rounds: a side's last round must end where the next round starts.
    windows = rounds.sort("start_tick").with_columns(
        window_end=pl.col("start_tick").shift(-1).fill_null(2**31 - 1)
    )
    snaps = assign_rounds(tables["snapshots"], windows).join(
        ct.select("ref", "freeze_end_tick", "end_tick"), on="ref"
    ).filter(
        (pl.col("tick") >= pl.col("freeze_end_tick")) & (pl.col("tick") <= pl.col("end_tick"))
    )  # fmt: skip
    ours = snaps.filter(pl.col("steamid").is_in(ids))
    theirs = snaps.filter(~pl.col("steamid").is_in(ids) & (pl.col("health") > 0))

    at20 = positions_at(tables["snapshots"].filter(pl.col("steamid").is_in(ids)), ct,
                        [SETUP_AT_S], tick_rate).filter("alive")  # fmt: skip
    places_at: dict[str, dict[int, str]] = defaultdict(dict)
    for ref, steamid, place in at20.select("ref", "steamid", "place").iter_rows():
        places_at[ref][steamid] = place or "Unknown"

    kills = (
        assign_rounds(tables["kills"], windows)
        .join(ct.select("ref", "freeze_end_tick"), on="ref")
        .filter(pl.col("tick") < pl.col("freeze_end_tick") + int(EARLY_S * tick_rate))
    )
    plants = assign_rounds(tables["bomb"].filter(pl.col("event") == "finish_plant"), windows)
    first_plant = {r["ref"]: r for r in plants.sort("tick").group_by("ref").first().iter_rows(
        named=True)}  # fmt: skip

    contact: dict[str, tuple[str, int]] = {}
    for (ref, tick), grp in theirs.sort("tick").group_by(["ref", "tick"], maintain_order=True):
        if ref in contact:
            continue
        counts = Counter(zone(p).on_site for p in grp["place"])
        for site in ("A", "B"):
            if counts.get(site, 0) >= CONTACT_PLAYERS:
                contact[ref] = (site, tick)
                break

    out = []
    for r in ct.sort("ref").iter_rows(named=True):
        ref = r["ref"]
        obs = CTRound(ref, r["buy"], r["won"], places=places_at.get(ref, {}))
        obs.setup = signature((zone(p).site or "mid") for p in obs.places.values())
        for k in kills.filter(pl.col("ref") == ref).iter_rows(named=True):
            if k["attacker_steamid"] in members and k["victim_side"] != k["attacker_side"]:
                obs.early.append(
                    {
                        "steamid": k["attacker_steamid"],
                        "won": True,
                        "place": places.place(k["attacker_x"], k["attacker_y"]),
                    }
                )
            if k["victim_steamid"] in members:
                obs.early.append(
                    {
                        "steamid": k["victim_steamid"],
                        "won": False,
                        "place": places.place(k["victim_x"], k["victim_y"]),
                    }
                )
        mine = ours.filter(pl.col("ref") == ref).sort("tick")
        if ref in contact:
            obs.contact_site, tick0 = contact[ref]
            obs.rotations = _rotations(mine, tick0, obs.contact_site, tick_rate, zone)
        plant = first_plant.get(ref)
        if plant is not None:
            obs.plant_site = plant["bombsite"]
            after = mine.filter((pl.col("tick") > plant["tick"]) & (pl.col("health") > 0))
            on_site = after.with_columns(
                site=pl.col("place").map_elements(lambda p: zone(p).on_site,
                                                  return_dtype=pl.String))  # fmt: skip
            per_tick = on_site.filter(pl.col("site") == obs.plant_site).group_by("tick").len()
            obs.retake = bool(per_tick.filter(pl.col("len") >= RETAKE_PLAYERS).height)
            alive_end = mine.filter(pl.col("tick") <= r["end_tick"]).group_by("steamid").last()
            obs.saved = (not r["won"] and not obs.retake
                         and bool(alive_end.filter(pl.col("health") > 0).height))  # fmt: skip
        out.append(obs)
    return out


def _rotations(mine: pl.DataFrame, tick0: int, site: str, tick_rate: float, zone
               ) -> dict[int, float | None]:  # fmt: skip
    """Players away from the contacted site when it is hit, and how long they take to get
    there (None: they never came, or died first)."""
    result: dict[int, float | None] = {}
    at_contact = mine.filter((pl.col("tick") - tick0).abs() <= 16).group_by("steamid").last()
    for steamid, place, health in at_contact.select("steamid", "place", "health").iter_rows():
        if health <= 0 or zone(place).site == site:
            continue
        later = mine.filter((pl.col("steamid") == steamid) & (pl.col("tick") > tick0)
                            & (pl.col("health") > 0))  # fmt: skip
        arrived = [t for t, p in later.select("tick", "place").iter_rows() if zone(p).site == site]
        result[steamid] = round((arrived[0] - tick0) / tick_rate, 1) if arrived else None
    return result


def mine_ct(rounds: list[CTRound], keys: dict[int, str], cfg: AnalysisConfig) -> list[dict]:
    out: list[dict] = []
    side = {"side": "CT"}

    setups: dict[tuple, list[str]] = defaultdict(list)
    for r in rounds:
        if r.setup:
            setups[r.setup].append(r.ref)
    for sig, refs in setups.items():
        if len(refs) >= 2:
            out.append(pattern("ct.setup", (sig,), "team", f"Setup at 0:20: {describe(sig)}",
                               {"groups": dict(sig)}, side, refs))  # fmt: skip

    for steamid, key in keys.items():
        seen = [(r.ref, r.places[steamid]) for r in rounds if steamid in r.places]
        if not seen:
            continue
        counts = Counter(place for _, place in seen)
        main = counts.most_common(1)[0][0]
        spots = [{"place": p, "rounds": n} for p, n in counts.most_common(4)]
        out.append(pattern("ct.position", (), key, f"Usually {main} at 0:20", {
            "main": main, "positions": spots, "observed": len(seen),
        }, {"side": "CT", "player": key}, [ref for ref, p in seen if p == main]))  # fmt: skip

        duels = [(r.ref, d) for r in rounds for d in r.early if d["steamid"] == steamid]
        if duels:
            won = sum(1 for _, d in duels if d["won"])
            where = Counter(d["place"] for _, d in duels).most_common(3)
            out.append(pattern("ct.aggression", (), key, "Early duels (before 0:20)", {
                "duels": len(duels), "won": won, "lost": len(duels) - won,
                "places": [{"place": p, "duels": n} for p, n in where],
            }, {"side": "CT", "player": key}, [ref for ref, _ in duels]))  # fmt: skip

        considered = [(r.ref, r.rotations[steamid]) for r in rounds if steamid in r.rotations]
        rotated = [(ref, s) for ref, s in considered if s is not None]
        if rotated:
            m = median(s for _, s in rotated)
            out.append(pattern("ct.rotation", (), key, f"Rotates to a hit site in ~{m:g} s", {
                "considered": len(considered), "rotated": len(rotated), "median_s": m,
            }, {"side": "CT", "player": key}, [ref for ref, _ in rotated]))  # fmt: skip

    planted = [r for r in rounds if r.plant_site]
    retakes = [r for r in planted if r.retake]
    if retakes:
        wins = sum(1 for r in retakes if r.won)
        out.append(pattern("ct.retake", (), "team", f"Retakes after a plant ({wins} won)", {
            "attempts": len(retakes), "won": wins,
        }, {"side": "CT", "planted": True}, [r.ref for r in retakes]))  # fmt: skip
    saves = [r for r in planted if r.saved]
    if saves:
        out.append(pattern("ct.save", (), "team", "Saves instead of retaking",
                           {"saves": len(saves)}, {"side": "CT", "planted": True},
                           [r.ref for r in saves]))  # fmt: skip
    return out
