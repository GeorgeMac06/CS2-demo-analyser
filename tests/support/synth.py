"""Synthetic matches with known answers (WU-3).

A scenario is a JSON-serialisable dict. ``write_demo`` stores it in a file that starts with
the real CS2 magic bytes, so it travels through ingest and the parse child like a real demo.
``SynthAdapter`` turns it into a canonical extract. No real player data is involved.

Scenario shape (all keys optional unless marked)::

    {"map": "de_mirage", "server": "synthetic", "a_starts": "T",
     "lineups": {"A": ["a1", ...5], "B": ["b1", ...5]},          # required
     "clan": {"A": "Team A", "B": "Team B"}, "names": {"a1": "Nick"},
     "rounds": [{                                                   # required
        "winner": "A",                       # lineup that wins the round (required)
        "reason": "ct_win",                  # default from winner side / plant
        "duration": 60,                      # seconds from freeze end to round end
        "places": {"15": {"a1": "TRamp"}, "30": {...}},   # player places from second N
        "kills": [{"t": 40, "attacker": "a1", "victim": "b2", "weapon": "ak47",
                   "assister": "a2", "flash_assist": false, "headshot": false}],
        "plant": {"t": 50, "site": "A", "player": "a3"},
        "grenades": [{"t": 10, "thrower": "a2", "type": "smoke",
                      "throw": [x, y], "land": [x, y]}],
        "blinds": [{"t": 12, "attacker": "a2", "victim": "b1", "duration": 2.5}],
        "equipment": {"A": 24000, "B": 4500}}]}
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import polars as pl

from cs2scout.core.schema import SNAPSHOT_STRIDE_TICKS, SORT_KEYS, TABLES, Extract

MAGIC = b"PBDEMS2\x00"
TAG = b"CS2SCOUT-SYNTH\n"
TICK_RATE = 64
FREEZE_S = 15
POST_ROUND_S = 7
FIRST_ROUND_TICK = 1000
STEAMID_BASE = 76561190000000000
SPAWN = {"T": "TSpawn", "CT": "CTSpawn"}
PISTOL_EQUIPMENT = 4200
FULL_EQUIPMENT = 25000


def steamid(key: str) -> int:
    """Stable fake SteamID per player key, so a key is the same player in every demo."""
    return STEAMID_BASE + int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) % 10**9


def place_xy(place: str, key: str = "") -> tuple[float, float]:
    """Deterministic synthetic coordinates for a place, with a small per-player spread."""
    h = hashlib.sha256(place.encode()).digest()
    x = (int.from_bytes(h[:2], "big") / 65535) * 4000 - 2000
    y = (int.from_bytes(h[2:4], "big") / 65535) * 4000 - 2000
    if key:
        k = hashlib.sha256(key.encode()).digest()
        x += k[0] % 50 - 25
        y += k[1] % 50 - 25
    return round(x, 1), round(y, 1)


def side_of_a(round_num: int, a_starts: str = "T") -> str:
    """Observed swap rule (S-1): swap at 13; in overtime only at each OT half-time (28, 34, ...)."""
    swaps = int(round_num >= 13) + sum(1 for s in range(28, round_num + 1, 6))
    other = "CT" if a_starts == "T" else "T"
    return a_starts if swaps % 2 == 0 else other


def write_demo(path: Path, scenario: dict) -> Path:
    path.write_bytes(MAGIC + TAG + json.dumps(scenario).encode())
    return path


def read_scenario(path: Path) -> dict:
    data = path.read_bytes()
    if not data.startswith(MAGIC + TAG):
        raise ValueError("not a synthetic demo")
    return json.loads(data[len(MAGIC + TAG) :])


class SynthAdapter:
    name = "synth"
    version = "1"

    def read_header(self, path: Path) -> dict:
        scenario = read_scenario(path)
        return {"map_name": scenario.get("map", "de_mirage"), "build_num": 1,
                "demo_version_name": "valve_demo_2"}  # fmt: skip

    def extract(self, path: Path) -> Extract:
        scenario = read_scenario(path)
        if "call_log" in scenario:  # lets tests count parses across processes (T-07)
            with open(scenario["call_log"], "a", encoding="utf-8") as log:
                log.write(path.name + "\n")
        if "sleep_s" in scenario:  # a slow parse, for cancel tests
            import time

            time.sleep(scenario["sleep_s"])
        return build_extract(scenario)


class SynthAdapterV2(SynthAdapter):
    """The same parser after an upgrade: its extracts are not reusable (T-07)."""

    version = "2"


def build_extract(scenario: dict) -> Extract:  # noqa: C901 - a linear table builder
    lineups: dict[str, list[str]] = scenario["lineups"]
    a_starts = scenario.get("a_starts", "T")
    names = scenario.get("names", {})
    clan = scenario.get("clan", {"A": "Team A", "B": "Team B"})
    weapons = scenario.get("weapons", {})  # player key -> primary weapon (default ak47)
    lineup_of = {k: lu for lu, keys in lineups.items() for k in keys}

    rec: dict[str, list[dict]] = {name: [] for name in TABLES}
    rec["players"] = [
        {"steamid": steamid(k), "name": names.get(k, k), "team_clan_name": clan.get(lineup_of[k])}
        for k in lineup_of
    ]

    tick = FIRST_ROUND_TICK
    for i, spec in enumerate(scenario["rounds"], start=1):
        side_a = side_of_a(i, a_starts)
        side = {"A": side_a, "B": "CT" if side_a == "T" else "T"}
        player_side = {k: side[lineup_of[k]] for k in lineup_of}
        start, freeze_end = tick, tick + FREEZE_S * TICK_RATE
        end = freeze_end + int(spec.get("duration", 60) * TICK_RATE)
        official_end = end + POST_ROUND_S * TICK_RATE
        tick = official_end

        def at(seconds: float, _fe: int = freeze_end) -> int:
            return _fe + int(seconds * TICK_RATE)

        winner_side = side[spec["winner"]]
        plant = spec.get("plant")
        default_reason = (
            "target_bombed" if plant and winner_side == "T"
            else "bomb_defused" if plant else
            "terrorists_win" if winner_side == "T" else "ct_win"
        )  # fmt: skip
        rec["rounds"].append({
            "round_num": i, "start_tick": start, "freeze_end_tick": freeze_end, "end_tick": end,
            "official_end_tick": official_end, "winner_side": winner_side,
            "reason": spec.get("reason", default_reason), "is_knife": False,
        })  # fmt: skip

        pistol = i in (1, 13)
        for lu in ("A", "B"):
            default = PISTOL_EQUIPMENT if pistol else FULL_EQUIPMENT
            value = spec.get("equipment", {}).get(lu, default)
            rec["round_economy"].append({
                "round_num": i, "side": side[lu], "equipment_value": value, "n_players": 5,
                "parser_buy_type": None,
            })  # fmt: skip

        # Places per player over time (piecewise constant from each checkpoint).
        checkpoints = sorted((float(s), p) for s, p in spec.get("places", {}).items())

        def place_at(key: str, seconds: float, _cps=checkpoints, _ps=player_side) -> str:
            current = SPAWN[_ps[key]]
            for s, places in _cps:
                if seconds >= s and key in places:
                    current = places[key]
            return current

        death_tick = {k["victim"]: at(k["t"]) for k in spec.get("kills", [])}
        for t in range(start, official_end, SNAPSHOT_STRIDE_TICKS):
            seconds = (t - freeze_end) / TICK_RATE
            for key in lineup_of:
                place = place_at(key, seconds)
                x, y = place_xy(place, key)
                alive = t < death_tick.get(key, official_end + 1)
                rec["snapshots"].append({
                    "tick": t, "steamid": steamid(key), "side": player_side[key], "x": x, "y": y,
                    "z": 0.0, "yaw": 0.0, "health": 100 if alive else 0, "armor": 100 if alive
                    else 0, "active_weapon": weapons.get(key, "ak47"),
                    "primary_weapon": weapons.get(key, "ak47"), "money": 1000,
                    "equipment_value": 5000 if alive else 0, "place": place,
                })  # fmt: skip

        for k in spec.get("kills", []):
            t, att, vic = at(k["t"]), k.get("attacker"), k["victim"]
            ax, ay = place_xy(place_at(att, k["t"]), att) if att else (None, None)
            vx, vy = place_xy(place_at(vic, k["t"]), vic)
            assister = k.get("assister")
            rec["kills"].append({
                "tick": t,
                "attacker_steamid": steamid(att) if att else None,
                "attacker_side": player_side[att] if att else None,
                "attacker_x": ax, "attacker_y": ay, "attacker_z": 0.0 if att else None,
                "victim_steamid": steamid(vic), "victim_side": player_side[vic],
                "victim_x": vx, "victim_y": vy, "victim_z": 0.0,
                "assister_steamid": steamid(assister) if assister else None,
                "assister_side": player_side[assister] if assister else None,
                "weapon": k.get("weapon", "ak47"), "headshot": k.get("headshot", False),
                "thrusmoke": False, "assist_flash": k.get("flash_assist", False),
                "is_trade": k.get("is_trade", False), "victim_traded": k.get("traded", False),
            })  # fmt: skip
            if att:
                rec["damages"].append({
                    "tick": t, "attacker_steamid": steamid(att), "attacker_side": player_side[att],
                    "victim_steamid": steamid(vic), "victim_side": player_side[vic],
                    "weapon": k.get("weapon", "ak47"), "dmg_health": 100, "dmg_armor": 0,
                    "health_pre": 100, "health_post": 0,
                })  # fmt: skip

        if plant:
            px, py = place_xy(place_at(plant["player"], plant["t"]), plant["player"])
            for event, dt in (("start_plant", -3), ("finish_plant", 0)):
                rec["bomb"].append({
                    "tick": at(plant["t"] + dt), "event": event,
                    "steamid": steamid(plant["player"]), "bombsite": plant["site"],
                    "x": px, "y": py, "z": 0.0,
                })  # fmt: skip

        for n, g in enumerate(spec.get("grenades", [])):
            thrower = g["thrower"]
            tx, ty = g.get("throw") or place_xy(place_at(thrower, g["t"]), thrower)
            lx, ly = g["land"]
            rec["grenades"].append({
                "entity_id": 100 + n, "entity_serial": i, "type": g["type"],
                "thrower_steamid": steamid(thrower), "thrower_side": player_side[thrower],
                "start_tick": at(g["t"]), "land_tick": at(g["t"] + 2),
                "throw_x": tx, "throw_y": ty, "throw_z": 0.0,
                "land_x": lx, "land_y": ly, "land_z": 0.0,
            })  # fmt: skip
            interval = {"start_tick": at(g["t"] + 2), "end_tick": at(g["t"] + 20),
                        "thrower_steamid": steamid(thrower), "thrower_side": player_side[thrower],
                        "x": lx, "y": ly, "z": 0.0}  # fmt: skip
            if g["type"] == "smoke":
                rec["smokes"].append(interval)
            elif g["type"] in ("molotov", "incendiary"):
                rec["fires"].append(interval | {"type": g["type"]})

        for b in spec.get("blinds", []):
            rec["blinds"].append({
                "tick": at(b["t"]), "attacker_steamid": steamid(b["attacker"]),
                "attacker_side": player_side[b["attacker"]],
                "victim_steamid": steamid(b["victim"]), "victim_side": player_side[b["victim"]],
                "duration": b.get("duration", 2.0),
            })  # fmt: skip

    rec["server_counters"] = _server_counters(rec, lineup_of, FIRST_ROUND_TICK)
    tables = {
        name: pl.DataFrame(rows, schema=TABLES[name]).sort(list(SORT_KEYS[name]), nulls_last=True)
        for name, rows in rec.items()
    }
    header = {"map_name": scenario.get("map", "de_mirage"), "tick_rate": float(TICK_RATE),
              "build_num": 1, "demo_version_name": "valve_demo_2", "playback_ticks": tick,
              "server_name": scenario.get("server", "synthetic")}  # fmt: skip
    return Extract(header=header, tables=tables)


def _server_counters(rec: dict, lineup_of: dict, live_start: int) -> list[dict]:
    """What the game server would count, using the S-1 rules."""
    counts = {steamid(k): {"kills": 0, "deaths": 0, "assists": 0, "damage": 0} for k in lineup_of}
    for k in rec["kills"]:
        if k["tick"] < live_start:
            continue
        counts[k["victim_steamid"]]["deaths"] += 1
        enemy = k["attacker_side"] != k["victim_side"]
        if k["attacker_steamid"] and k["attacker_steamid"] != k["victim_steamid"] and enemy:
            counts[k["attacker_steamid"]]["kills"] += 1
        if k["assister_steamid"] and k["assister_side"] != k["victim_side"]:
            counts[k["assister_steamid"]]["assists"] += 1
    for d in rec["damages"]:
        if d["attacker_side"] != d["victim_side"]:
            counts[d["attacker_steamid"]]["damage"] += d["dmg_health"]
    return [{"steamid": s, **c} for s, c in counts.items()]


# ---------------------------------------------------------------- scenario helpers


def lineup(prefix: str) -> list[str]:
    return [f"{prefix}{i}" for i in range(1, 6)]


def simple_match(
    a: list[str] | None = None,
    b: list[str] | None = None,
    score: tuple[int, int] = (13, 5),
    *,
    server: str = "synthetic",
    map_name: str = "de_mirage",
) -> dict:
    """A plain match won ``score`` by lineup A, with one kill per round by the winner."""
    a, b = a or lineup("a"), b or lineup("b")
    wins_a, wins_b = score
    # Deterministic interleave (every third round to B while it has wins); A wins the last.
    order: list[str] = []
    left_a, left_b = wins_a - 1, wins_b
    while left_a or left_b:
        if left_b and (len(order) % 3 == 2 or not left_a):
            order.append("B")
            left_b -= 1
        else:
            order.append("A")
            left_a -= 1
    order.append("A")
    rounds = []
    for n, w in enumerate(order):
        att, vic = (a, b) if w == "A" else (b, a)
        rounds.append({"winner": w, "kills": [{"t": 30, "attacker": att[n % 5],
                                               "victim": vic[n % 5]}]})  # fmt: skip
    return {"map": map_name, "server": server, "lineups": {"A": a, "B": b}, "rounds": rounds}
