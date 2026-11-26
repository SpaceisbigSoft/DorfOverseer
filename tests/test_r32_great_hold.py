"""(R32 c) A great danger judged too strong is not gone out at: the squads
hold the choke and fight it there when it comes to them.

F (26 Nov 04:55-04:58): a Hydra the planner judged too strong (hiding, the
squads at the choke) was sent at by squad_attack a minute later (the bar
lowered x0.8 for a moment: "falling back"), 5 soldiers dead in 70 s, then
squad_recall "too weak now". One judgement now: held as too strong, the
full bar to go out at it; one inside the fort is judged as before. And the
player (26 Nov): "never attack" is no sortie outside, not an enemy loose
inside the walls (B's Giantess, 13 dead).

    python tests/test_r32_great_hold.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan  # noqa: E402
import planner_holdfast as HF  # noqa: E402
import planner_matchup as PM  # noqa: E402
from planner_military import fight_or_hide  # noqa: E402
from planner_great_hold import GREAT_HOLD_KEY  # noqa: E402
import digest  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
HID = 6001
CH = [{"x": 12, "y": 20, "z": 170, "from_src": 2, "to_shelter": 25, "width": 2}]


def hydra(**kw):
    t = {"id": HID, "name": "Hydra", "great_danger": True, "kinds": ["SemiMegabeast"], "size": 9000000,
         "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 50,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 10, "y": 10, "z": 170}}
    t.update(kw)
    return t


NEED = PM.judge([hydra()], [{"id": 1, "members": 7, "power": {"power": 1, "armed": 7, "melee_power": 1,
                                                                   "ranged_power": 0}}])["need"]


def sq(i, power, members=7, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": power, "armed": members, "melee_power": power, "ranged_power": 0}}
    q.update(kw)
    return q


def three(ratio, **kw):
    return [sq(10 + k, NEED * ratio / 3, **kw) for k in range(3)]


def fort(threats, squads, policy="ordinary", shelter=True, **extra) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = threats
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s["military"]["squads"] = squads
    s["civ_alert"] = True
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = policy
    if shelter:
        s["shelter_plan"] = {"danger": True, "civilians": 20, "barracks": [], "current": {"levels": [160]},
                             "dangers": [{"id": HID, "name": "Hydra", "great": True, "x": 10, "y": 10, "z": 170,
                                          "way_in": 1}],
                             "candidates": [{"z": 160, "d_threat": 45, "civ_p90": 5, "civ_med": 2, "civ_reached": 10,
                                             "civ_late": 0, "drink": 0, "wells": 1, "tiles": 200, "food": 200,
                                             "chokes": CH, "way_in": {"id": 1, "kind": "surface", "x": 10,
                                                                      "y": 20, "z": 170}}]}
    s.update(extra)
    return digest.normalize(s)


def falling_back(m):
    """The holdfast's distance record: the Hydra 10 tiles farther than last cycle."""
    m.holdfast["dist"] = {"tick": 0, "prev": {str(HID): 40}, "cur": {str(HID): 50}}


def attacks(props):
    return [p for p in props if p.rule == "squad_attack"]


def stationed(props):
    return [p for p in props if p.action.get("type") == "shelter_squads" and p.action.get("station")]


@test("F's Hydra: judged too strong (0.9x, about even needed): no kill order, the squads stationed at the choke, "
      "the reason says why with the numbers; booked as held")
def _():
    m = Memory()
    s = fort([hydra()], three(0.875))
    props, notes = plan(s, m)
    assert not attacks(props), [p.reason for p in attacks(props)]
    st = stationed(props)
    assert st and st[0].action["station"] == {"x": 12, "y": 20, "z": 170}, [p.action for p in props
                                                                            if "shelter" in p.rule]
    assert "too strong to go out at (" in st[0].reason and "1x needed): the squads hold the choke" in st[0].reason, \
        st[0].reason
    assert any("too strong to go out at" in n for n in notes), [n for n in notes if "great" in n]
    assert str(HID) in m.holdfast.get(GREAT_HOLD_KEY, {}), m.holdfast


@test("F's Hydra a minute later, \"falling back\" (the x0.8 bar): held, still no kill order (it was sent before "
      "R32), the squads stay at the choke; a fresh judgement without the hold would go")
def _():
    s = fort([hydra()], three(0.875))
    fresh = Memory()
    falling_back(fresh)
    assert fight_or_hide(s, fresh, CFG, [hydra()], s["military"]["squads"])[0]     # the old flip
    m = Memory()
    plan(s, m)                                   # judged too strong: held
    falling_back(m)
    info: dict = {}
    fight, why = fight_or_hide(s, m, CFG, [hydra()], s["military"]["squads"], info=info)
    assert not fight and info["held"] and info["bar"] == 1.0, (why, info)
    props, notes = plan(s, m)
    assert not attacks(props), [p.reason for p in attacks(props)]
    assert stationed(props) and "too strong to go out at" in stationed(props)[0].reason


@test("held, then strong enough at the full bar (1.2x): the squads go and the hold is lifted")
def _():
    m = Memory()
    plan(fort([hydra()], three(0.875)), m)
    s = fort([hydra()], three(1.2))
    props, _ = plan(s, m)
    assert sorted(p.action["squad_id"] for p in attacks(props)) == [10, 11, 12], [p.reason for p in props]
    assert str(HID) not in m.holdfast.get(GREAT_HOLD_KEY, {}), m.holdfast


@test("one judgement: a fight on (0.8x after losses) goes on, not recalled; once recalled (held) it isn't sent "
      "again at 0.8x")
def _():
    m = Memory()
    plan(fort([hydra()], three(1.2)), m)        # sent, the fight begun
    out = three(0.8, ai_orders=1, orders=1, kill_ids=[HID])
    props, _ = plan(fort([hydra()], out), m)
    assert not [p for p in props if p.rule == "squad_recall"], [p.reason for p in props if p.rule == "squad_recall"]
    # a hold (the recall's verdict booked): no sortie at 0.8x, nor the fight's 0.75 bar
    m2 = Memory()
    plan(fort([hydra()], three(0.6)), m2)
    props, _ = plan(fort([hydra()], three(0.8)), m2)
    assert not attacks(props), [p.reason for p in attacks(props)]


@test("the exception: the Hydra inside the fort among the dwarves (held before): the odds decide as before "
      "(x0.8 when falling back), said in the reason")
def _():
    m = Memory()
    plan(fort([hydra()], three(0.875)), m)
    falling_back(m)
    s = fort([hydra(inside=True)], three(0.875))
    props, _ = plan(s, m)
    a = attacks(props)
    assert a and all("inside the fort" in p.reason and "protects nobody" in p.reason for p in a), \
        [p.reason for p in a]


@test("an ordinary beatable great danger (1.2x) is still attacked, no hold")
def _():
    m = Memory()
    props, _ = plan(fort([hydra()], three(1.2)), m)
    assert len(attacks(props)) == 3 and not stationed(props), [p.reason for p in props]
    assert not m.holdfast.get(GREAT_HOLD_KEY)


@test("never attack (the player): a great danger outside: no kill order; inside and beatable: fought, the reason "
      "says why the switch gives way; inside and too strong: the choke held")
def _():
    m = Memory()
    props, _ = plan(fort([hydra()], three(1.5), policy="never"), m)
    assert not attacks(props), [p.reason for p in attacks(props)]
    gi = hydra(name="Giantess")
    m = Memory()
    s = fort([gi], three(1.5), policy="never", entrances={"intruders_inside": [HID]})
    props, _ = plan(s, m)
    a = attacks(props)
    assert len(a) == 3 and all("never attack means no sorties outside" in p.reason for p in a), \
        [p.reason for p in props]
    m = Memory()
    s = fort([gi], three(0.5), policy="never", entrances={"intruders_inside": [HID]})
    props, notes = plan(s, m)
    assert not attacks(props), [p.reason for p in attacks(props)]
    st = stationed(props)
    assert st and "too strong to go out at" in st[0].reason, [p.reason for p in props if "shelter" in p.rule]


@test("never attack: ordinary enemies inside the walls (more than the lone-intruder few) are fought too")
def _():
    gobs = [{"id": 8000 + i, "name": "goblin", "invader": True, "great_danger": False, "size": 60000,
             "can_reach_dwarves": True, "layer": "upper_levels", "distance_to_nearest_dwarf": 10,
             "levels_from_nearest_dwarf": 0, "pos": {"x": 60 + i, "y": 60, "z": 170}, "inside": True}
            for i in range(8)]
    m = Memory()
    s = fort(gobs, [sq(10, 400), sq(11, 400)], policy="never", shelter=False)
    props, _ = plan(s, m)
    a = attacks(props)
    assert a and any("never attack means no sorties outside" in p.reason for p in a), [p.reason for p in props]
    out = [dict(g, inside=None) for g in gobs]
    props, _ = plan(fort(out, [sq(10, 400), sq(11, 400)], policy="never", shelter=False), Memory())
    assert not attacks(props), [p.reason for p in attacks(props)]


if __name__ == "__main__":
    finish()
