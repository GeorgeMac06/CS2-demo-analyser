"""Zones: where a player is, in words (ADR-006, design §5.5).

``PlaceNameZones`` uses the game's own place names (spike S-1: always present, site- and
lane-level, nothing finer inside a site). A small per-map table adds the site and a lane
group. Only names whose meaning is certain are mapped; any other place is still a zone of
its own, just without a site or lane, so nothing is mislabelled. Pattern code depends only
on ``ZoneProvider``, so polygons or coordinate sub-zones can replace this later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Zone:
    name: str  # the zone id shown to the Analyst (here: the game's place name)
    site: str | None = None  # "A" / "B" when the place is part of a bombsite or its approach
    lane: str | None = None  # a coarser group, e.g. "A ramp", "mid", "B apartments"

    @property
    def on_site(self) -> str | None:
        """ "A"/"B" only when standing on the bombsite itself (not just on its approach)."""
        if self.lane in ("A site", "B site") or self.name in ("BombsiteA", "BombsiteB"):
            return self.site
        return None


class ZoneProvider(Protocol):
    version: str

    def zone(self, map_name: str, place: str | None) -> Zone: ...


# Mirage: the 23 place names seen in spike S-1. Unmapped on purpose (meaning not verified):
# Shop, Truck, SideAlley. BackAlley and House were mapped from evidence (WU-12, 4 real demos):
# T rounds with 4-5 players there at 0:15 went on to hit B in 6 of 8 cases.
_MIRAGE = {
    "BombsiteA": ("A", "A site"),
    "Scaffolding": ("A", "A site"),
    "TRamp": ("A", "A ramp"),
    "PalaceAlley": ("A", "A palace"),
    "PalaceInterior": ("A", "A palace"),
    "Stairs": ("A", "A CT side"),
    "Jungle": ("A", "A CT side"),
    "Connector": (None, "connector"),
    "TopofMid": (None, "mid"),
    "Middle": (None, "mid"),
    "SnipersNest": (None, "mid window"),
    "Ladder": (None, "mid"),
    "Catwalk": ("B", "B short"),
    "Underpass": ("B", "underpass"),
    "Apartments": ("B", "B apartments"),
    "House": ("B", "B apartments"),
    "BackAlley": ("B", "B back alley"),
    "BombsiteB": ("B", "B site"),
    "TSpawn": (None, "T spawn"),
    "CTSpawn": (None, "CT spawn"),
}
_TABLES: dict[str, dict[str, tuple[str | None, str]]] = {"de_mirage": _MIRAGE}
_GENERIC = {"BombsiteA": ("A", "A site"), "BombsiteB": ("B", "B site"),
            "TSpawn": (None, "T spawn"), "CTSpawn": (None, "CT spawn")}  # fmt: skip


class PlaceNameZones:
    version = "place-names-v1"

    def zone(self, map_name: str, place: str | None) -> Zone:
        name = place or "Unknown"
        site, lane = _TABLES.get(map_name, {}).get(name) or _GENERIC.get(name) or (None, None)
        return Zone(name=name, site=site, lane=lane)

    def mapped_maps(self) -> list[str]:
        return sorted(_TABLES)
