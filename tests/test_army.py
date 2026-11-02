"""(0.105.0, round 2) An army that can fight: the planner's rules
(brain/planner_army.py) on the real test fort, one thing changed per test.

    python tests/test_army.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

from planner import Memory, PLANNER_CONFIG, plan, record  # noqa: E402
import planner_army  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
RESULTS = []


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def teacheroar_gear(**kw) -> dict:
    """The live report of 1 Nov, as the 0.105.0 bridge reads it."""
    s = fort()
    g = {"soldiers": 39, "on_duty": 35, "armed": 23, "armored": 30, "helmed": 30, "melee_given": 21,
         "weapon_gaps": 16, "weapon_gaps_fillable": 0, "squads": 4, "squads_with_uniform": 4,
         "spare_weapons": {"ITEM_WEAPON_AXE_BATTLE": 8, "ITEM_WEAPON_PICK": 10}, "spare_crossbows": 10,
         "ranged_armed": 8, "bolts": 524, "shielded": 0, "legged": 30, "gloved": 30, "booted": 30,
         "spare": {"weapons": 18, "body": 0, "helms": 0, "shields": 4}, "bars": {"IRON": 200}, "forges": 2,
         "shields": {"places": 39, "no_entry": 29, "entries": 10, "given": 0}}
    g.update(kw)
    s["military"]["gear"] = g
    for q in s["military"]["squads"]:
        q["ai_uniform"] = "Melee, metal armor |weapon:ITEM_WEAPON_AXE_BATTLE"
    return s


@test("the gaps' reasons: stale claims and a material the fort lacks are mended, spare shields go on the metal uniforms")
def _():
    s = teacheroar_gear(weapon_gaps_why={"stale on a soldier's list": 8, "wrong material": 6, "none of its kind": 2})
    p = by_rule(plan(s, Memory())[0], "gear_fix")
    assert p and p[0].action == {"type": "fix_gear_gaps", "shields": True}, p
    assert "8 stale" in p[0].reason and "6 wrong material" in p[0].reason and "4 spare shields" in p[0].reason, p[0].reason
    # nothing the AI can mend, no spare shields: nothing asked
    s = teacheroar_gear(weapon_gaps_why={"none of its kind": 16}, spare={"weapons": 0, "shields": 0})
    assert not by_rule(plan(s, Memory())[0], "gear_fix")
    # an older bridge (no reasons): no fix, and no shields without a count
    s = teacheroar_gear(spare={"weapons": 0})
    s["military"]["gear"].pop("shields")
    assert not by_rule(plan(s, Memory())[0], "gear_fix")
    # Rules tab: no gear making, no mending
    s = teacheroar_gear(weapon_gaps_why={"wrong material": 6})
    s["settings"]["make_gear"] = False
    assert not by_rule(plan(s, Memory())[0], "gear_fix")


@test("an entry naming a weapon the fort has none of: made (axes at the forge, crossbows at the bowyer's)")
def _():
    s = teacheroar_gear(weapon_gaps_why={"none of its kind": 4}, weapon_gaps_wanted={"ITEM_WEAPON_SPEAR": 4})
    s["orders"] = []
    p = by_rule(plan(s, Memory())[0], "gear_fix_order")
    assert p and p[0].action == {"type": "work_order", "recipe": "metal_spear", "amount": 4,
                                 "material": "INORGANIC:IRON"}, p
    s["military"]["gear"]["weapon_gaps_wanted"] = {"ITEM_WEAPON_CROSSBOW": 3}
    s["buildings"]["workshops"]["Bowyers"] = 1
    s["stocks"]["wood"] = 50
    p = by_rule(plan(s, Memory())[0], "gear_fix_order")
    assert p and p[0].action == {"type": "work_order", "recipe": "wooden_crossbow", "amount": 3}, p


@test("unreachable weapons are put to the player; forbidden ones noted")
def _():
    s = teacheroar_gear(weapon_gaps_why={"unreachable": 5, "forbidden, dumped or to melt": 2})
    _, notes = plan(s, Memory())
    assert any(n.startswith("[you] 5 soldier(s) can't get to the free weapons") for n in notes), notes
    assert any("forbidden, dumped or set to melt" in n for n in notes), notes


@test("quivers: free ones handed out to the crossbow places; leather ones made for a squad the 0.100 rule doesn't cover")
def _():
    s = teacheroar_gear(ranged_places=10, quivers_assigned=0, quivers_free=4)
    s["stocks"]["leather"] = 20
    s["buildings"]["workshops"]["Leatherworks"] = 1
    s["orders"] = []
    props = plan(s, Memory())[0]
    q = by_rule(props, "quivers")
    assert q and q[0].action == {"type": "assign_quivers", "limit": 10}, q
    o = by_rule(props, "quivers_order")
    assert o and o[0].action == {"type": "work_order", "recipe": "leather_quiver", "amount": 5}, o
    # the AI's own crossbow squad: its quivers are the 0.100 rule's to order (no double order)
    s["military"]["squads"][1]["ai_uniform"] = "Crossbows, metal armor"
    assert not by_rule(plan(s, Memory())[0], "quivers_order")
    # every place has one: nothing
    s = teacheroar_gear(ranged_places=10, quivers_assigned=10, quivers_free=4)
    assert not by_rule(plan(s, Memory())[0], "quivers")
    # an older bridge: nothing
    assert not by_rule(plan(teacheroar_gear(), Memory())[0], "quivers")


@test("bolts: a squad with crossbows and no ammunition entry gets one; set but none handed out is noted")
def _():
    s = teacheroar_gear()
    s["military"]["squads"][0]["ammo"] = {"specs": 0, "wanted": 0, "assigned": 0, "items": 0}
    b = by_rule(plan(s, Memory())[0], "bolts")
    assert b and b[0].action == {"type": "squad_bolts", "squad_id": s["military"]["squads"][0]["id"]}, b
    s["military"]["squads"][0]["ammo"] = {"specs": 1, "wanted": 500, "assigned": 0, "items": 0}
    props, notes = plan(s, Memory())
    assert not by_rule(props, "bolts") and any("bolts set but none handed out" in n for n in notes), notes


@test("ammo storage: a few stacks of bolts in the workshops and no ammo pile at all: a pile for them")
def _():
    from planner import full_stores
    s = fort()
    s.setdefault("logistics", {})["storage"] = {
        "ammo": {"tiles": 0, "used": 0, "loose": 6, "in_workshops": 6, "piles": 0},
        "food": {"tiles": 900, "used": 500, "loose": 0}}
    assert "ammo" in full_stores(s, PLANNER_CONFIG)          # 6 stacks (150 bolts) < the usual 20 items
    s["logistics"]["storage"]["ammo"].update(tiles=9, used=9, loose=6)
    assert "ammo" not in full_stores(s, PLANNER_CONFIG)      # a pile, full: the usual 20 loose before more


def titan(power):
    s = fort()
    s["others_on_map"]["threats"] = [{"id": 900, "name": "Ume, Swamp Titan", "great_danger": True,
                                      "can_reach_dwarves": True, "kinds": ["Titan"], "size": 2_500_000}]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    for q in s["military"]["squads"]:
        q["power"] = {"power": power, "armored": 10, "skill": 10}
    s["military"]["soldiers"] = 20
    s["civ_alert_ready"] = True
    return s


@test("hide: the squads go to the shelter with the civilians; not when they fight; not with the switch off")
def _():
    s = titan(10)                                              # 20 < 50: hide
    props, notes = plan(s, Memory())
    sh = by_rule(props, "shelter_squads")
    assert sh and sh[0].action == {"type": "shelter_squads", "squads": [11, 12]} and sh[0].priority == 0, sh
    assert any("hide behind the gates" in n for n in notes), notes
    assert not by_rule(plan(titan(40), Memory())[0], "shelter_squads")      # 80 >= 50: they fight
    s["settings"]["squads_shelter"] = False
    assert not by_rule(plan(s, Memory())[0], "shelter_squads")
    s = titan(10)
    s["civ_alert_ready"] = False                               # no shelter burrow yet
    assert not by_rule(plan(s, Memory())[0], "shelter_squads")
    s = titan(10)
    s["military"]["squads"][0]["orders"] = 1                   # a squad on the player's orders: left alone
    sh = by_rule(plan(s, Memory())[0], "shelter_squads")
    assert sh and sh[0].action["squads"] == [12], sh


@test("hide: the squads in the shelter stay while the alarm is up, come out when it clears, and go when sent")
def _():
    s = titan(10)
    for q in s["military"]["squads"]:
        q.update(sheltering=True, ai_orders=1, orders=1)
    s["civ_alert"] = True
    props = plan(s, Memory())[0]
    assert not by_rule(props, "shelter_squads") and not by_rule(props, "squad_recall"), props
    # the titan gone, the alarm still up (the quiet days): they stay
    gone = copy.deepcopy(s)
    gone["others_on_map"]["threats"] = []
    gone["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    assert not by_rule(plan(gone, Memory())[0], "squad_recall")
    # the alarm lowered: out
    gone["civ_alert"] = False
    r = by_rule(plan(gone, Memory())[0], "squad_recall")
    assert len(r) == 2 and all(p.action.get("clear") for p in r), r
    # strong enough after all: sent at it (the kill order replaces the shelter's)
    strong = titan(40)
    for q in strong["military"]["squads"]:
        q.update(sheltering=True, ai_orders=1, orders=1)
    strong["civ_alert"] = True
    a = by_rule(plan(strong, Memory())[0], "squad_attack")
    assert len(a) == 2 and a[0].action["kill"] == [900], a


@test("hiding(): what the AI does about the great dangers in reach, by the Rules tab's attack policy")
def _():
    s = titan(10)
    assert planner_army.hiding(s, Memory(), PLANNER_CONFIG) == (True, [])
    s["settings"]["attack_policy"] = "all"
    assert planner_army.hiding(s, Memory(), PLANNER_CONFIG) == (False, [900])
    s["others_on_map"]["threats"].append({"id": 901, "name": "goblin", "can_reach_dwarves": True})
    s["settings"]["attack_policy"] = "ordinary"
    assert planner_army.hiding(s, Memory(), PLANNER_CONFIG) == (False, [901])   # a goblin to fight: no hiding


def wide_entrance(**kw):
    s = fort()
    e = {"id": 7, "kind": "surface", "x": 40, "y": 50, "z": 160, "width": 64, "sealed": False, "closing": False,
         "equipment": [], "door_spots": 0, "bridges_unworked": []}
    e.update(kw)
    s["entrances"] = {"scanned": True, "scanned_tick": s["date"]["tick"] + s["date"]["year"] * 403200,
                      "entrances": [e], "armed": False}
    return s


@test("gates: a 64-wide opening is cut below (hatches on its stairs down), not left to the player")
def _():
    s = wide_entrance(cut_hatches=3)
    props, notes = plan(s, Memory())
    c = by_rule(props, "gate_cut")
    assert c and c[0].action == {"type": "cut_entrance", "entrance_id": 7}, c
    assert "3 stair(s)" in c[0].reason and "64 wide" in c[0].reason, c[0].reason
    assert not any("can't be closed with doors" in n for n in notes), notes
    # no cut possible: the player is told, with why
    s = wide_entrance(cut_why="a ramp leads down from the open area at x41 y52 (no hatch fits a ramp): wall it")
    props, notes = plan(s, Memory())
    assert not by_rule(props, "gate_cut")
    assert any("can't be closed with doors" in n for n in notes), notes
    assert any("can't be cut off below either: a ramp" in n for n in notes), notes
    # a narrow one is the walls' (fortify), never cut
    s = wide_entrance(width=6, cut_hatches=2)
    assert not by_rule(plan(s, Memory())[0], "gate_cut")
    # a refused narrow one is cut
    m = Memory()
    m.gate_failures["40,50,160"] = "the way in at x40 y50 is a branch"
    assert by_rule(plan(wide_entrance(width=6, cut_hatches=2), m)[0], "gate_cut")


@test("gates: the cut's outcome is booked like a fortified gate (built, or refused with why)")
def _():
    s = wide_entrance(cut_hatches=3)
    m = Memory()
    p = by_rule(plan(s, m)[0], "gate_cut")[0]
    record([(p, {"ok": True, "style": "cut", "hatches": 3})], s, m)
    assert m.gates_fortified.get("40,50,160") == "cut", m.gates_fortified
    m2 = Memory()
    record([(p, {"ok": False, "error": "no hatch could be placed"})], s, m2)
    # (0.105.0 review) under its own key: a wall's refusal there is kept
    assert "no hatch" in m2.gate_failures.get("cut:40,50,160", ""), m2.gate_failures
    assert not by_rule(plan(s, m)[0], "gate_cut")          # cut already: not asked again before the scan


@test("0.105.0 review gates: a refused cut waits gate_retry_ticks; the wall's refusal text is kept")
def _():
    s = wide_entrance(width=6, cut_hatches=2)
    m = Memory()
    m.gate_failures["40,50,160"] = "the way in at x40 y50 is a branch"
    p = by_rule(plan(s, m)[0], "gate_cut")[0]
    record([(p, {"ok": False, "error": "no hatch could be placed"})], s, m)
    assert m.gate_failures["40,50,160"] == "the way in at x40 y50 is a branch", m.gate_failures
    props, notes = plan(s, m)
    assert not by_rule(props, "gate_cut")                    # refused just now: not asked every cycle
    assert any("couldn't be cut off below: no hatch" in n for n in notes), notes
    m.gate_failure_ticks["cut:40,50,160"] -= PLANNER_CONFIG["gate_retry_ticks"] + 1
    assert by_rule(plan(s, m)[0], "gate_cut")                # two weeks on: tried again
    # a dry run books nothing
    m3 = Memory()
    record([(p.__class__(p.rule, dict(p.action, dry_run=True), p.reason, p.priority), {"ok": False, "error": "x"})], s, m3)
    assert not m3.gate_failures, m3.gate_failures


@test("0.105.0 review: spare shields count only the metal melee squads' places without a shield entry")
def _():
    s = teacheroar_gear()
    ids = [q["id"] for q in s["military"]["squads"]]
    s["military"]["gear"]["shields"]["no_entry_squads"] = {"999": 29}       # only a squad that isn't the AI's metal one
    assert not any(p.action.get("shields") for p in by_rule(plan(s, Memory())[0], "gear_fix"))
    s["military"]["gear"]["shields"]["no_entry_squads"] = {str(ids[0]): 5}
    assert any(p.action.get("shields") for p in by_rule(plan(s, Memory())[0], "gear_fix"))


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
