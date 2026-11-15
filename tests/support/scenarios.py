"""A scouted team with known habits, for the pattern tests (T-10, T-11).

Lineup A ("a1".."a5") is the scouted team: T in rounds 1-12, CT in rounds 13-24. Per demo:

T half
    r1      pistol B rush: 3 Apartments + 2 Underpass at 0:10, B site at 0:16, plant B 0:18
    r2-r6   the same B fast exec on full buys, with a smoke from a2 into B at 0:12
    r7-r9   A split: 2 PalaceInterior, 2 TRamp, 1 Connector at 0:10; A site 0:50, plant 0:52
    r10-r11 fake: 3 Apartments + 2 Underpass at 0:30, A site at 1:10, plant A 1:12
    r12     nothing: everyone TopofMid, no plant (stays "unresolved")
CT half (positions at 0:20)
    r13-r21 2-1-2: a1 a2 BombsiteA, a3 Connector, a4 a5 BombsiteB
    r22-r24 A stack: a1 a2 a3 BombsiteA, a4 Connector, a5 BombsiteB
"""

from __future__ import annotations

from support.synth import lineup

TEAM = lineup("a")
A_WINS = {1, 2, 3, 4, 5, 7, 8, 9, 13, 14, 15, 16, 24}  # 13-11


def _t_round(n: int, opp: list[str]) -> dict:
    a1, a2, a3, a4, a5 = TEAM
    rnd: dict = {}
    if n <= 6:
        rnd["places"] = {
            "10": {a1: "Apartments", a2: "Apartments", a3: "Apartments", a4: "Underpass",
                   a5: "Underpass"},
            "16": {a1: "BombsiteB", a2: "BombsiteB", a3: "BombsiteB"},
        }  # fmt: skip
        rnd["plant"] = {"t": 18, "site": "B", "player": a1}
        if n > 1:
            rnd["grenades"] = [{"t": 12, "thrower": a2, "type": "smoke", "land": [520.0, 480.0]}]
    elif n <= 9:
        rnd["places"] = {
            "10": {a1: "PalaceInterior", a2: "PalaceInterior", a3: "TRamp", a4: "TRamp",
                   a5: "Connector"},
            "50": {a1: "BombsiteA", a2: "BombsiteA", a3: "BombsiteA"},
        }  # fmt: skip
        rnd["plant"] = {"t": 52, "site": "A", "player": a3}
        rnd["duration"] = 70
    elif n <= 11:
        rnd["places"] = {
            "30": {a1: "Apartments", a2: "Apartments", a3: "Apartments", a4: "Underpass",
                   a5: "Underpass"},
            "70": {a1: "BombsiteA", a2: "BombsiteA", a3: "BombsiteA"},
        }  # fmt: skip
        rnd["plant"] = {"t": 72, "site": "A", "player": a1}
        rnd["duration"] = 90
    else:
        rnd["places"] = {"10": dict.fromkeys(TEAM, "TopofMid")}
    return rnd


def _ct_round(n: int) -> dict:
    a1, a2, a3, a4, a5 = TEAM
    if n <= 21:
        spots = {a1: "BombsiteA", a2: "BombsiteA", a3: "Connector", a4: "BombsiteB",
                 a5: "BombsiteB"}  # fmt: skip
    else:
        spots = {a1: "BombsiteA", a2: "BombsiteA", a3: "BombsiteA", a4: "Connector",
                 a5: "BombsiteB"}  # fmt: skip
    return {"places": {"5": spots}}


def scouted_match(opp_prefix: str, server: str) -> dict:
    opp = lineup(opp_prefix)
    rounds = []
    for n in range(1, 25):
        rnd = _t_round(n, opp) if n <= 12 else _ct_round(n)
        winner = "A" if n in A_WINS else "B"
        killer, victim = (TEAM, opp) if winner == "A" else (opp, TEAM)
        rnd["winner"] = winner
        rnd["kills"] = [{"t": 30, "attacker": killer[n % 5], "victim": victim[n % 5]}]
        rnd.setdefault("duration", 60)
        rounds.append(rnd)
    return {"map": "de_mirage", "server": server, "lineups": {"A": TEAM, "B": opp},
            "clan": {"A": "Scouted", "B": f"Opp {opp_prefix}"}, "rounds": rounds}  # fmt: skip
