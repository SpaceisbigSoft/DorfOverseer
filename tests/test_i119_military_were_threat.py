"""(0.105.119 item32) A werebeast in beast form is a top threat at once.

Live 25 Nov (fresh run): F's Wereskink visitor killed two while three squads'
kill orders were dropped by the matchup filter (0.4x) and went only once it
had changed back; A's seven werepanther citizens got one squad a cycle. Now
every free squad goes at a were in beast form whatever the odds or the
policy, the alarm sounds and stays up, a peaceful fort doesn't hide from it,
and a kill order naming one of the fort's own back in their own form comes
off them (`kill_spared`). brain/planner_military_weres.py.

    python tests/test_i119_military_were_threat.py
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
import planner_military_weres as W  # noqa: E402
from planner_defence_floor import hidden_from  # noqa: E402
from planner_military import hazard_alert  # noqa: E402

CFG = dict(PLANNER_CONFIG)
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def skink(i=3110, **kw):
    t = {"id": i, "name": 'Atthem Luritisdi "Spotice", Wereskink', "can_reach_dwarves": True, "great_danger": False,
         "flier": False, "invader": False, "visitor": None, "layer": "upper levels", "size": 300000,
         "pos": {"x": 167, "y": 160, "z": 171}, "distance_to_nearest_dwarf": 1, "levels_from_nearest_dwarf": 0,
         "kinds": ["NightCreature"], "transformed": True, "destroyer": True}
    t.update(kw)
    return t


def sq(i, members=10, power=2, **kw):
    q = {"id": i, "name": f"Squad {i}", "members": members, "size": 10, "orders": 0, "ai_orders": 0,
         "power": {"power": power, "melee_power": power, "armed": members}, "routine": "Constant training"}
    q.update(kw)
    return q


def fort(threats=(), squads=None, berserk=None, **kw) -> dict:
    s = copy.deepcopy(BASE)
    s["others_on_map"]["threats"] = list(threats)
    s["military"]["squads"] = squads if squads is not None else [sq(183), sq(201), sq(209)]
    if berserk is not None:
        s["hazards"] = {"berserk": berserk}
    s.update(kw)
    return s


def attacks(props, uid):
    return [p for p in props if p.rule == "squad_attack" and uid in (p.action.get("kill") or [])]


@test("F's Wereskink inside, the squads far too weak by the matchup: every squad is sent at once (none dropped)")
def _():
    props, notes = plan(fort([skink()]), Memory())
    got = sorted(p.action["squad_id"] for p in attacks(props, 3110))
    assert got == [183, 201, 209], (got, [n for n in notes if "not sent" in n])
    assert not [n for n in notes if "not sent at" in n and "Wereskink" in n], notes


@test("an older bridge (no `transformed`): a night creature named ', Were<x>' counts; a bogeyman doesn't")
def _():
    t = skink(transformed=None)
    t.pop("transformed")
    assert W.were_ids(fort([t])) == {3110}
    assert W.were_ids(fort([skink(name="Bogeyman", transformed=None)])) == set()
    assert W.were_ids(fort([skink(transformed=False)])) == set()
    assert W.were_ids(fort([skink(caged=True)])) == set()


@test("Rules tab 'send squads against nothing': a were in beast form is still attacked")
def _():
    s = fort([skink()])
    s["settings"]["rules"] = {"attack_policy": "never"}
    props, _ = plan(s, Memory())
    assert attacks(props, 3110), props


@test("the alarm sounds for a visiting were in beast form, and isn't lowered while it is loose")
def _():
    s = fort([skink(can_reach_dwarves=None)])
    assert "werebeast in beast form" in hazard_alert(s, CFG)
    props, _ = plan(s, Memory())
    assert any(p.rule == "threat_alert" and p.action.get("on") is True for p in props), \
        [(p.rule, p.reason) for p in props if "alert" in p.rule]
    s = fort([skink(can_reach_dwarves=None)], civ_alert=True)
    m = Memory()
    m.ai_alert_raised = True
    m.quiet_cycles = 50
    props, _ = plan(s, m)
    assert not any(p.rule == "threat_alert" and p.action.get("on") is False for p in props), \
        [(p.rule, p.reason) for p in props if p.rule == "threat_alert"]


@test("A's werepanther citizens changed: every free squad (and one waiting in the shelter) goes, each at all of them")
def _():
    b = [{"id": 17608, "name": "Sakzul, Werepanther Trapper", "changed": True},
         {"id": 17627, "name": "Eral, Werepanther Administrator", "changed": True}]
    squads = [sq(186, power=60), sq(202, power=60), sq(205, power=60, ai_orders=1, sheltering=True),
              sq(210, power=60, orders=1)]           # 210: the player's own order, kept
    props, _ = plan(fort(berserk=b, squads=squads), Memory())
    got = sorted(p.action["squad_id"] for p in attacks(props, 17608))
    assert got == [186, 202, 205], got
    assert all(17627 in p.action["kill"] for p in attacks(props, 17608))


@test("a plain berserk dwarf (not changed): one squad as before")
def _():
    b = [{"id": 900, "name": "Urist, Miner"}]
    props, _ = plan(fort(berserk=b, squads=[sq(186, power=60), sq(202, power=60)]), Memory())
    assert len(attacks(props, 900)) == 1, attacks(props, 900)


@test("a kill order naming a citizen back in dwarf form (kill_spared): given again without them, or cleared")
def _():
    squads = [sq(186, ai_orders=1, kill_ids=[17608, 17627], kill_spared=[17608]),
              sq(202, ai_orders=1, kill_ids=[17608], kill_spared=[17608])]
    b = [{"id": 17627, "name": "Eral, Werepanther Administrator", "changed": True}]
    props, _ = plan(fort(berserk=b, squads=squads), Memory())
    again = [p for p in props if p.action.get("squad_id") == 186 and p.action.get("type") == "squad_orders"]
    assert again and again[0].action.get("kill") == [17627], again
    off = [p for p in props if p.action.get("squad_id") == 202 and p.action.get("clear")]
    assert off and off[0].rule == "squad_recall" and off[0].priority == 0, off
    assert not attacks(props, 17608)


@test("a dwarf in dwarf form is never a target: no changed row, no threat row, no kill order")
def _():
    s = fort(berserk=[], squads=[sq(186, power=60)])
    s["deep"] = {"cursed": [{"id": 555, "name": "Urist, Miner", "kind": "werebeast"}]}
    props, _ = plan(s, Memory())
    assert not attacks(props, 555)


@test("a peaceful fort doesn't hide from a were in beast form (hidden_from), but still from a great beast")
def _():
    s = fort([skink(great_danger=True)])
    s["settings"]["traits"] = {"militarism": -60}
    s["civ_alert"] = True
    assert hidden_from(s, Memory(), CFG) == ""
    s["others_on_map"]["threats"].append({"id": 9, "name": "Nol, Forgotten Beast", "great_danger": True,
                                          "can_reach_dwarves": True, "kinds": ["ForgottenBeast"],
                                          "size": 5000000})
    assert hidden_from(s, Memory(), CFG) != ""


@test("the bridge: threat rows say `transformed`, squad rows `kill_spared` (kill_target_ok refusing one of the fort's own)")
def _():
    w = (ROOT / "lua" / "ai-bridge-report-world.lua").read_text(encoding="utf-8")
    assert "transformed = (function()" in w
    m = (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8")
    assert "kill_spared = kill_spared" in m and "not kill_target_ok(u)" in m


finish()
