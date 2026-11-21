"""(r3, 21 Nov) The player's two choices: hunting ("do as you suggest": the
hunt rule takes targets in reach of the dwarves that no other rule takes, at
the hunt's own bar) and Welfare ("do what you think is best": a say in burial
and grief).

    python tests/test_r3_hunt_welfare.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG  # noqa: E402
import planner_hunt as PH  # noqa: E402
import planner_welfare as PW  # noqa: E402
import planner_society as PS  # noqa: E402
from planner_core import Proposal  # noqa: E402
from digest import normalize  # noqa: E402

CFG = dict(PLANNER_CONFIG)


def squad(i, soldiers=5, power=900.0):
    return {"id": i, "name": f"Squad {i}", "soldiers": soldiers, "power": power, "armed": soldiers,
            "armored": soldiers, "ranged": 0, "at_home": True, "hunting": None, "sheltering": False}


def target(i=500, **kw):
    t = {"id": i, "name": f"Beast {i}", "kinds": [], "great_danger": False, "size": 60000,
         "pos": {"x": 10, "y": 10, "z": 50}, "layer": "surface", "region": "surface", "flier": False,
         "fire_breather": False, "ambush": False, "thief": False, "wounded_visitor": False,
         "route": {"ok": True, "length": 40, "blocked_by": "none"}, "near_workers": 0, "seen_ticks": 600,
         "can_reach_dwarves": True}
    t.update(kw)
    return t


def state(targets, squads, threats=(), traits=None, **extra):
    s = {"date": {"year": 200, "tick": 50000, "day": 1, "month": "Granite", "season": "spring"},
         "dwarves": {"total": 60, "adults": 50},
         "settings": {"traits": dict(traits or {})},
         "others_on_map": {"threats": list(threats)}, "civ_alert": False,
         "hunt": {"targets": list(targets), "squads": list(squads), "hunts": []}}
    s.update(extra)
    return normalize(s)


def run(s, cfg=None, proposals=None, memory=None):
    props, notes = list(proposals or []), []
    PH._hunt_rule(s, dict(cfg or CFG), props, notes, memory)
    return [p for p in props if p.action.get("type") == "hunt_send"], notes


SQ = [squad(1), squad(2), squad(3)]


@test("a thief in reach of the dwarves (the military rules leave lone thieves) is hunted")
def _():
    sends, n = run(state([target(thief=True)], SQ))
    assert len(sends) == 1 and sends[0].action["target_id"] == 500, n


@test("a wild animal in reach but far from the dwarves is hunted; one in the guard's distance is the guard's")
def _():
    far = target(why="hostile_wild")
    fw = {"wild": [{"id": 500, "distance": 200, "distance_outside": 200, "reach": True}]}
    sends, n = run(state([far], SQ, field_watch=fw))
    assert len(sends) == 1, n
    sends, n = run(state([far], SQ))                       # no field watch read: the guard's
    assert not sends and any("wildlife guard" in x for x in n), n
    sends, n = run(state([target(why="hostile_wild", near_workers=2)], SQ, field_watch=fw))
    assert not sends and any("wildlife guard" in x for x in n), n
    s = state([far], SQ, field_watch={"wild": [{"id": 500, "distance": 5, "reach": True}]})
    sends, n = run(s)
    assert not sends and any("wildlife guard" in x for x in n), n


@test("a lone beast in reach that no rule sends a squad at is hunted at the hunt's bar, not when weak")
def _():
    t = target(kinds=["Troll"])
    th = [{"id": 500, "can_reach_dwarves": True}]
    sends, n = run(state([t], SQ, threats=th))
    assert len(sends) == 1, n
    sends, n = run(state([t], [squad(1, power=1.0), squad(2, power=1.0)], threats=th))
    assert not sends and any("too weak" in x for x in n), n


@test("the lone beast is left to the military rules when they send a squad, the alarm is up, or two threats reach")
def _():
    t = target(kinds=["Troll"])
    th = [{"id": 500, "can_reach_dwarves": True}]
    mil = Proposal("squad_attack", {"type": "squad_orders", "squad_id": 9, "kill": [500]}, "x", 1)
    sends, n = run(state([t], SQ, threats=th), proposals=[mil])
    assert not sends, n
    sends, n = run(state([t], SQ, threats=th, civ_alert=True))
    assert not sends, n
    sends, n = run(state([t], SQ, threats=th + [{"id": 501, "can_reach_dwarves": True}]))
    assert not sends and any("can reach the dwarves" in x for x in n), n


@test("an invader is never a lone beast; the switch off restores the old rule")
def _():
    t = target(kinds=["Goblin"], invader=True)
    sends, n = run(state([t], SQ, threats=[{"id": 500, "can_reach_dwarves": True, "invader": True}]))
    assert not sends, n
    cfg = dict(CFG, r3_hunt_reachable=False)
    sends, n = run(state([target(thief=True)], SQ), cfg=cfg)
    assert not sends and any("military rules' fight" in x for x in n), n


@test("Welfare sets the burial waits (halved at +100, doubled at -100, bounded) and the slab orders")
def _():
    st = lambda w: normalize({"settings": {"traits": {"welfare": w}}})  # noqa: E731
    base = CFG["burial_fallback_days"]
    assert PW.welfare_days(st(0), CFG, "burial_fallback_days") == base
    assert PW.welfare_days(st(100), CFG, "burial_fallback_days") == round(base / 2)
    assert PW.welfare_days(st(-100), CFG, "burial_fallback_days") == 2 * base
    assert PW.welfare_days(st(200), CFG, "burial_fallback_days") >= CFG["r3_welfare_days_min"]
    assert PW.welfare_days(st(-200), CFG, "burial_fallback_days") == 2 * base
    assert PW.welfare_slabs(st(80), CFG) == CFG["slabs_ahead_max"] + 2
    assert PW.welfare_slabs(st(-40), CFG) == CFG["slabs_ahead_max"]
    off = dict(CFG, r3_welfare_burial=False)
    assert PW.welfare_days(st(100), off, "burial_fallback_days") == base


@test("the coffins-anywhere fallback comes sooner in a high-Welfare fort")
def _():
    def s(w, tick):
        return normalize({"date": {"year": 200, "tick": tick}, "settings": {"traits": {"welfare": w}},
                          "dead": {"free_tombs": 0, "unburied": 3},
                          "projects": {"open": [{"kind": "tombs"}]}})
    for w, due in ((100, True), (0, False)):
        m = Memory()
        PW.burial_fallback_due(s(w, 1000), CFG, m)          # the shortfall begins
        assert PW.tombable_dead(s(w, 1000)) == 3
        short, _ = PW.burial_fallback_due(s(w, 1000 + 8 * 1200), CFG, m)
        assert (short > 0) == due, (w, short)


@test("grief: after a death, stress care reaches the very unhappy (Welfare 0+) and the unhappy (Welfare 50+)")
def _():
    m = Memory()
    s = normalize({"date": {"year": 200, "tick": 50000}, "settings": {"traits": {"welfare": 0}}})
    assert PS.grief_on(s, CFG, m) is False
    from planner_core import abs_tick
    m.deaths_seen = [abs_tick(s) - 1200]
    assert PS.grief_on(s, CFG, m) is True
    m.deaths_seen = [abs_tick(s) - 20 * 1200]
    assert PS.grief_on(s, CFG, m) is False
    assert PS.grief_on(s, dict(CFG, r3_welfare_grief=False), Memory()) is False


finish()
