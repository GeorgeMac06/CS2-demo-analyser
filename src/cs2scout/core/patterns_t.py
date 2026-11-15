"""T-side patterns (FR-TS-1..6, FR-UTIL-4; design §6.3). WU-10.

Per T round: setups at the checkpoints, the site hit and when, tempo, utility before the hit,
an early "show" of the other site, and the post-plant setup. Then patterns across rounds.
A round with no plant and no clear site presence stays "unresolved"; it is never guessed.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import polars as pl

from cs2scout.core.config import AnalysisConfig
from cs2scout.core.features import assign_rounds
from cs2scout.core.patterns import (
    clock,
    describe,
    greedy_clusters,
    median,
    pattern,
    signature,
)
from cs2scout.core.positions import family, group_label, positions_at
from cs2scout.core.zones import PlaceNameZones

UTILITY = {"smoke": "smokes", "flashbang": "flashes", "molotov": "molotovs",
           "incendiary": "molotovs", "he": "hes"}  # fmt: skip
STRATEGY_SIMILARITY = 0.6
SETUP_SIMILARITY = 0.75
HIT_SITE_PLAYERS = 2  # players on the site at once: the hit has begun
SITE_PRESENCE = 3  # players on a site that make it "their" site without a plant


@dataclass
class TRound:
    ref: str
    buy: str
    won: bool
    setups: dict[int, Counter] = field(default_factory=dict)  # lanes, for descriptions
    families: dict[int, Counter] = field(default_factory=dict)  # A side / B side / mid
    site: str | None = None
    hit_s: float | None = None
    planted: bool = False
    early_site: str | None = None
    utility: Counter = field(default_factory=Counter)
    postplant: Counter | None = None

    @property
    def tempo(self) -> str:
        if self.site is None or self.hit_s is None:
            return "unresolved"
        return "rush" if self.hit_s < 20 else "default" if self.hit_s < 60 else "late"


def t_rounds(tables: dict[str, pl.DataFrame], rounds: pl.DataFrame, members: set[int],
             map_name: str, tick_rate: float, cfg: AnalysisConfig,
             zones: PlaceNameZones | None = None) -> list[TRound]:  # fmt: skip
    zones = zones or PlaceNameZones()
    t = rounds.filter(pl.col("side") == "T")
    if t.height == 0:
        return []
    ids = list(members)
    snaps = tables["snapshots"].filter(pl.col("steamid").is_in(ids))
    # Windows from *all* rounds: a side's last round must end where the next round starts.
    windows = rounds.sort("start_tick").with_columns(
        window_end=pl.col("start_tick").shift(-1).fill_null(2**31 - 1)
    )
    zone = lambda place: zones.zone(map_name, place)  # noqa: E731

    checkpoints = positions_at(snaps, t, list(cfg.checkpoints_s), tick_rate).filter("alive")
    setups: dict[str, dict[int, Counter]] = defaultdict(dict)
    families: dict[str, dict[int, Counter]] = defaultdict(dict)
    early: dict[str, str] = {}
    for (ref, sec), grp in checkpoints.group_by(["ref", "t"], maintain_order=True):
        zs = [zone(p) for p in grp["place"]]
        setups[ref][int(sec)] = Counter(group_label(z) for z in zs)
        families[ref][int(sec)] = Counter(family(z) for z in zs)
        sites = Counter(z.site for z in zs if z.site)
        top = sites.most_common(1)
        if int(sec) >= 30 and top and top[0][1] >= SITE_PRESENCE and ref not in early:
            early[ref] = top[0][0]

    plants = assign_rounds(tables["bomb"].filter(pl.col("event") == "finish_plant"), windows)
    first_plant = {r["ref"]: r for r in plants.sort("tick").group_by("ref").first().iter_rows(
        named=True)}  # fmt: skip

    live = assign_rounds(snaps, windows).join(
        t.select("ref", "freeze_end_tick", "end_tick"), on="ref"
    ).filter(
        (pl.col("tick") >= pl.col("freeze_end_tick")) & (pl.col("tick") <= pl.col("end_tick"))
        & (pl.col("health") > 0)
    )  # fmt: skip
    on_site: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for (ref, tick), grp in live.group_by(["ref", "tick"], maintain_order=True):
        counts = Counter(zone(p).on_site for p in grp["place"])
        for site in ("A", "B"):
            if counts.get(site, 0) >= HIT_SITE_PLAYERS:
                on_site[ref][site + ":hit"].append(tick)
            if counts.get(site, 0) >= SITE_PRESENCE:
                on_site[ref][site + ":held"].append(tick)

    grenades = assign_rounds(tables["grenades"].filter(pl.col("thrower_steamid").is_in(ids)),
                             windows, "start_tick")  # fmt: skip
    out = []
    for r in t.sort("ref").iter_rows(named=True):
        ref, fe = r["ref"], r["freeze_end_tick"]
        obs = TRound(
            ref, r["buy"], r["won"], setups=setups.get(ref, {}), families=families.get(ref, {})
        )
        plant = first_plant.get(ref)
        presence = on_site.get(ref, {})
        if plant is not None:
            obs.planted, obs.site = True, plant["bombsite"]
            hits = presence.get(f"{obs.site}:hit")
            obs.hit_s = ((min(hits) if hits else plant["tick"]) - fe) / tick_rate
        else:
            held = [(min(presence[f"{s}:held"]), s) for s in ("A", "B")
                    if presence.get(f"{s}:held")]  # fmt: skip
            if held:
                tick0, obs.site = min(held)
                hits = presence.get(f"{obs.site}:hit")
                obs.hit_s = ((min(hits) if hits else tick0) - fe) / tick_rate
        obs.early_site = early.get(ref)
        horizon = fe + int(((obs.hit_s if obs.hit_s is not None else 45) + 5) * tick_rate)
        thrown = grenades.filter((pl.col("ref") == ref) & (pl.col("start_tick") <= horizon))
        obs.utility = Counter(UTILITY[g] for g in thrown["type"] if g in UTILITY)
        if plant is not None:
            obs.postplant = _groups_at(snaps, plant["tick"] + int(10 * tick_rate),
                                       r["end_tick"], map_name, zones)  # fmt: skip
        out.append(obs)
    return out


def _groups_at(snaps: pl.DataFrame, tick: int, end_tick: int, map_name: str,
               zones: PlaceNameZones) -> Counter:  # fmt: skip
    if tick > end_tick:
        return Counter()
    near = snaps.filter((pl.col("tick") - tick).abs() <= 16).filter(pl.col("health") > 0)
    latest = near.sort("tick").group_by("steamid").last()
    return Counter(group_label(zones.zone(map_name, p)) for p in latest["place"])


def mine_t(rounds: list[TRound], cfg: AnalysisConfig) -> list[dict]:
    out: list[dict] = []
    side = {"side": "T"}

    at30 = [r for r in rounds if 30 in r.families]
    lookup30 = {r.ref: r for r in at30}
    for cluster in greedy_clusters([(r.ref, r.families[30]) for r in at30], SETUP_SIMILARITY):
        if len(cluster) < 2:
            continue
        rs = [lookup30[ref] for ref in cluster]
        sig = Counter(signature(r.families[30].elements()) for r in rs).most_common(1)[0][0]
        usual = Counter(signature(r.setups[30].elements()) for r in rs).most_common(1)[0][0]
        out.append(pattern("ts.setup", (sig,), "team",
                           f"At 0:30: {describe(sig)} (usually {describe(usual)})",
                           {"checkpoint_s": 30, "groups": dict(sig), "usual": dict(usual)},
                           side, cluster))  # fmt: skip

    for site in ("A", "B", None):
        mine = [r for r in rounds if r.site == site]
        if mine:
            name = f"Hits {site}" if site else "No clear site (no plant, no site take)"
            out.append(pattern("ts.site", (site,), "team", name, {
                "site": site, "median_hit_s": median(r.hit_s for r in mine),
            }, side, [r.ref for r in mine]))  # fmt: skip

    hit_times = sorted(r.hit_s for r in rounds if r.hit_s is not None)
    for band in ("rush", "default", "late"):
        mine = [r for r in rounds if r.tempo == band]
        if mine:
            label = {"rush": "under 0:20", "default": "0:20–1:00", "late": "after 1:00"}[band]
            out.append(pattern("ts.tempo", (band,), "team", f"{band.capitalize()} hit ({label})",
                               {"band": band, "hit_times_s": [round(h, 1) for h in hit_times]},
                               side, [r.ref for r in mine]))  # fmt: skip

    groups: dict[tuple, list[TRound]] = defaultdict(list)
    for r in rounds:
        if r.site is not None:
            groups[(r.site, r.tempo)].append(r)
    for (site, band), members in sorted(groups.items()):
        items = [(r.ref, r.families.get(15) or r.families.get(30) or Counter()) for r in members]
        lookup = {r.ref: r for r in members}
        for cluster in greedy_clusters(items, STRATEGY_SIMILARITY):
            if len(cluster) < 2:
                continue
            rs = [lookup[ref] for ref in cluster]
            lanes = Counter(
                signature((r.setups.get(15) or r.setups.get(30) or Counter()).elements())
                for r in rs
            )
            seed = lanes.most_common(1)[0][0]
            util = {k: median(r.utility.get(k, 0) for r in rs)
                    for k in ("smokes", "flashes", "molotovs", "hes")}  # fmt: skip
            hit = median(r.hit_s for r in rs)
            title = f"{site} {band} ~{clock(hit)} from {describe(seed)}"
            out.append(pattern("ts.strategy", (site, band, seed), "team", title, {
                "site": site, "tempo": band, "median_hit_s": hit, "setup_15s": dict(seed),
                "utility_median": util,
            }, side, cluster))  # fmt: skip

    for buy in ("pistol", "eco", "force"):
        mine: dict[tuple, list[str]] = defaultdict(list)
        for r in rounds:
            if r.buy == buy:
                mine[(r.site, r.tempo)].append(r.ref)
        for (site, band), refs in mine.items():
            what = f"{site} {band}" if site else "no clear hit"
            out.append(pattern("ts.buy", (buy, site, band), "team", f"{buy.capitalize()}: {what}",
                               {"buy": buy, "site": site, "tempo": band},
                               {"side": "T", "buy": buy}, refs))  # fmt: skip

    post: dict[tuple, list[str]] = defaultdict(list)
    for r in rounds:
        if r.postplant:
            post[(r.site, signature(r.postplant.elements()))].append(r.ref)
    for (site, sig), refs in post.items():
        if len(refs) >= 2:
            out.append(pattern("ts.postplant", (site, sig), "team",
                               f"After planting {site}: {describe(sig)}",
                               {"site": site, "groups": dict(sig)},
                               {"side": "T", "planted": True}, refs))  # fmt: skip

    fakes: dict[tuple, list[str]] = defaultdict(list)
    for r in rounds:
        if r.early_site and r.site and r.early_site != r.site:
            fakes[(r.early_site, r.site)].append(r.ref)
    for (shown, hit), refs in fakes.items():
        out.append(pattern("ts.fake", (shown, hit), "team", f"Shows {shown}, then hits {hit}",
                           {"shown": shown, "site": hit}, side, refs))  # fmt: skip
    return out
