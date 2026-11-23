"""(0.105.82) Soldiers short of leisure get turns off: planner_military's
"many idle hands, every squad trains" stands aside while a fifth of the
soldiers (3 at least) badly miss drink, merriment, company, prayer or rest
(B, 23 Nov: 20 of 20 missing drink were soldiers; 28 miserable).

    python tests/test_leisure_rotation.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402
import json  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s

sys.path.insert(0, str(ROOT / "brain"))
from planner import plan, Memory, PLANNER_CONFIG  # noqa: E402
import planner_leisure as PM  # noqa: E402

CFG = dict(PLANNER_CONFIG)


def needs(**badly_soldiers):
    return {"needs": {k: {"badly": v, "badly_soldiers": v, "distracted": v} for k, v in badly_soldiers.items()}}


@test("B's numbers: drink 20 of 37 soldiers trips it; BeWithFriends alone never does; no soldier count: nothing")
def _():
    s = {"dwarves": {"in_squads": 37}, "needs": needs(DrinkAlcohol=20, MakeMerry=13, BeWithFriends=26)}
    assert PM.soldiers_short_of_leisure(s, CFG) == "DrinkAlcohol"
    s = {"dwarves": {"in_squads": 59}, "needs": needs(BeWithFriends=54)}
    assert PM.soldiers_short_of_leisure(s, CFG) == ""
    s = {"dwarves": {"in_squads": 68}, "needs": needs(PrayOrMeditate=3)}           # C: 3 of 68
    assert PM.soldiers_short_of_leisure(s, CFG) == ""
    s = {"dwarves": {}, "needs": needs(DrinkAlcohol=20)}
    assert PM.soldiers_short_of_leisure(s, CFG) == ""
    s = {"dwarves": {"in_squads": 37}, "needs": {"needs": {"DrinkAlcohol": {"badly": 20}}}}   # an older bridge
    assert PM.soldiers_short_of_leisure(s, CFG) == ""


def b_fort(short: bool):
    s = fort()
    sq = s["military"]["squads"]
    s["military"]["routines"] = ["Off duty", "Staggered training", "Constant training", "Ready"]
    for q in sq:
        q["routine"], q["members"], q["ai_orders"] = "Constant training", 5, False
    s["settings"]["militarism"] = -60
    s.setdefault("settings", {}).setdefault("traits", {})["militarism"] = -60
    s["dwarves"]["in_squads"] = 5 * len(sq)
    s["needs"] = needs(DrinkAlcohol=10 if short else 0, MartialTraining=1)
    return s, [q["id"] for q in sq]


@test("many idle hands: every squad keeps training unless the soldiers are short of leisure; then half go off duty")
def _():
    for short in (False, True):
        s, ids = b_fort(short)
        m = Memory()
        m.squads_trained = list(ids)
        m.idle_avg, m.idle_hands = 0.3, True                    # B: 20-34% truly idle
        moved = {p.action["squad_id"]: p.action["routine"] for p in plan(copy.deepcopy(s), m)[0]
                 if p.rule == "train"}
        off = [i for i, r in moved.items() if r == "Off duty"]
        if short:
            assert len(off) == len(ids) // 2, (short, moved)
        else:
            assert not off, (short, moved)


if __name__ == "__main__":
    finish()
