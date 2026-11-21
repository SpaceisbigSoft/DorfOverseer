"""(x4) The arming hold, the all-out attack, the long alarm's lift and the
drink orders' copies (brain/planner_war_hold.py, planner_military, planner,
planner_orders).

  * V3 (verify-v56): arm_first held drafting up to 56 days under a siege,
    waiting for weapons a forge with no fuel, no smith or stalled orders
    could never make;
  * S2: the "unfought" all-out attack went at 0.25x and the recall hold
    kept the squads on it until a third were lost;
  * S3: the 60-day hard lift lowered the alarm with a titan inside beside
    the civilians;
  * S7: stalled duplicate drink and meal orders were never trimmed while
    drink was short.

    python tests/test_x4_war_hold.py
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
from planner import Memory, PLANNER_CONFIG, plan, note_cycle  # noqa: E402
from planner_core import abs_tick  # noqa: E402
import planner_war_hold as wh  # noqa: E402
import digest  # noqa: E402

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
OFF = {"type": "civ_alert", "on": False}
RULES = {"make_gear": True}


def offs(props):
    return [p for p in props if p.action == OFF]


# --- V3: the arming hold -------------------------------------------------------------------

def armed_fort(threats=(), fuel=5, magma=0, plain=1, holders=None, orders=(), tick=200000):
    """10 soldiers on duty, 2 armed, 80 iron bars (V3's numbers)."""
    s = copy.deepcopy(BASE)
    s["date"] = {"day": 1, "month": "Granite", "season": "spring", "tick": tick, "year": 260}
    s["others_on_map"]["threats"] = list(threats)
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats if t.get("can_reach_dwarves"))
    s = digest.normalize(s)
    ws = dict(s["buildings"]["workshops"])
    ws.pop("MagmaForge", None)
    ws.pop("MetalsmithsForge", None)
    if plain:
        ws["MetalsmithsForge"] = plain
    if magma:
        ws["MagmaForge"] = magma
    s["buildings"]["workshops"] = ws
    s["supplies"]["fuel"] = fuel
    s["military"]["gear"] = {"soldiers": 10, "on_duty": 10, "armed": 2, "bars": {"IRON": 80},
                             "forges": plain + magma, "spare": {"weapons": 0}}
    if holders is not None:
        s["order_desk"] = {"labor_holders": {"FORGE_WEAPON": holders}}
    s["orders"] = list(orders)
    return s


def goblin(**kw):
    t = {"id": 9, "name": "a goblin lasher", "invader": True, "can_reach_dwarves": True, "great_danger": False,
         "distance_to_nearest_dwarf": 40, "pos": {"x": 100, "y": 100, "z": 150}}
    t.update(kw)
    return t


def axe_order(oid=700, **jobs):
    return {"id": oid, "recipe": "metal_battle_axe", "material": "INORGANIC:IRON", "amount_left": 8,
            "amount_total": 8, "by_ai": True, "active": True, "validated": True,
            "jobs": {"n": 1, "suspended": 0, "working": 0, **jobs}}


@test("V3 arm_first: a quiet fort with fuel, a smith and a forge: the hold stands (the r1g5 fix kept)")
def _():
    s = armed_fort(holders=3)
    why = wh.arm_first(s, CFG, RULES)
    assert "2 of the 10 soldiers on duty armed" in why and "80 iron bars" in why, why


@test("V3 arm_first: no charcoal or coke and no magma forge: no hold (the weapons never come); a magma forge: held")
def _():
    s = armed_fort(fuel=0)
    assert wh.arm_first(s, CFG, RULES) == ""
    assert "no charcoal or coke" in wh.arm_check(s, CFG, RULES)[1], wh.arm_check(s, CFG, RULES)
    assert wh.arm_first(armed_fort(fuel=0, magma=1), CFG, RULES), "a magma forge needs no fuel"


@test("V3 arm_first: no citizen with the weaponsmith's labour, or no forge built (it stands on its anvil): no hold")
def _():
    assert wh.arm_first(armed_fort(holders=0), CFG, RULES) == ""
    s = armed_fort(plain=0)
    s["military"]["gear"]["forges"] = 1             # the gear count sees an unbuilt forge
    assert wh.arm_first(s, CFG, RULES) == ""


@test("V3 arm_first: an enemy in reach, inside, a great danger on the map or a siege: drafted anyway")
def _():
    assert wh.arm_first(armed_fort([goblin()]), CFG, RULES) == ""
    s = armed_fort()
    s["entrances"]["intruders_inside"] = [9]
    assert wh.arm_first(s, CFG, RULES) == ""
    titan = goblin(id=10, name="a titan", invader=False, great_danger=True, can_reach_dwarves=False,
                   layer="upper_levels")
    assert wh.arm_first(armed_fort([titan]), CFG, RULES) == ""
    s = armed_fort()
    m = Memory()
    m.holdfast = {"siege": {"since": abs_tick(s) - DAY, "last": abs_tick(s)}}
    assert wh.arm_first(s, CFG, RULES, m) == ""
    assert wh.arm_first(s, CFG, RULES, Memory()), "no siege: held"


@test("V3 arm_first: the making stalls (a suspended job, nobody with the labour, 4+ days unmoved): the hold ends; "
      "an order at work keeps it")
def _():
    assert wh.arm_first(armed_fort(orders=[axe_order(suspended=1)]), CFG, RULES) == ""
    assert wh.arm_first(armed_fort(orders=[axe_order(holders=0)]), CFG, RULES) == ""
    s = armed_fort(orders=[axe_order()])
    m = Memory()
    m.order_watch = {"700": {"left": 8, "since": abs_tick(s) - 5 * DAY, "by_ai": True, "what": "metal_battle_axe"}}
    assert wh.arm_first(s, CFG, RULES, m) == ""
    m.order_watch["700"]["since"] = abs_tick(s) - 2 * DAY
    assert wh.arm_first(s, CFG, RULES, m), "two days: still coming"
    worked = armed_fort(orders=[axe_order(working=1)])
    m.order_watch["700"]["since"] = abs_tick(s) - 9 * DAY
    assert wh.arm_first(worked, CFG, RULES, m), "a smith at it now"
    # held 4 days with no weapon order at all and none spare: lifted
    s = armed_fort()
    m = Memory()
    note_cycle(s, m)
    assert wh.arm_first(s, CFG, RULES, m)
    later = copy.deepcopy(s)
    later["date"]["tick"] += 5 * DAY
    note_cycle(later, m)
    assert wh.arm_first(later, CFG, RULES, m) == ""


@test("V3 note_war_hold: the 56 days' clock runs on through a siege (not begun again after it)")
def _():
    s = armed_fort()
    m = Memory()
    note_cycle(s, m)
    t0 = m.atlas["arm_first"]["since"]
    war = armed_fort([goblin()], tick=s["date"]["tick"] + DAY)
    note_cycle(war, m)
    assert m.atlas.get("arm_first", {}).get("since") == t0, m.atlas.get("arm_first")


@test("V3 plan: 10 soldiers wanted more, 2 of 10 armed, 80 iron bars, no fuel, a goblin in reach: squads filled")
def _():
    s = armed_fort([goblin()], fuel=0)
    s["military"]["squads"] = [{"id": 11, "name": "The Axes", "members": 5, "size": 10, "leader": True,
                                "routine": "Staggered training", "orders": 0, "ai_orders": 0},
                               {"id": 12, "name": "The Bolts", "members": 5, "size": 10, "leader": True,
                                "routine": "Staggered training", "orders": 0, "ai_orders": 0}]
    s["military"]["soldiers"] = 10
    s["dwarves"]["total"] = 120
    s["dwarves"]["adults"] = 110
    s["settings"]["traits"] = {"militarism": 40}
    m = Memory()
    m.defence_floor = {"peak": {"power": 400.0, "tick": abs_tick(s) - DAY, "why": "goblins"}}
    p, notes = plan(s, m)
    assert not any("armed first" in n and "before more soldiers are drafted" in n for n in notes), \
        [n for n in notes if "armed first" in n]
    fills = [x for x in p if x.rule in ("squad_fill", "squad_make")]
    assert fills, [n for n in notes if "soldiers" in n][:6]
    assert any("drafted unarmed" in n and "enemies can reach the dwarves" in n for n in notes), \
        [n for n in notes if "soldiers" in n][:6]


# --- S2: the all-out attack's bar and the first losses --------------------------------------

def beast(**kw):
    t = {"id": 20001, "name": "Webspinner, Forgotten Beast", "invader": False, "great_danger": True,
         "flier": False, "fire_breather": False, "webs": True, "kinds": ["ForgottenBeast"],
         "can_reach_dwarves": True, "size": 900000, "layer": "fort_levels", "distance_to_nearest_dwarf": 80,
         "levels_from_nearest_dwarf": 0, "pos": {"x": 108, "y": 152, "z": 153}}
    t.update(kw)
    return t


def xbows(power, members=6, **kw):
    q = {"id": 2, "name": "The Bolts", "members": members, "size": 10, "leader": True, "orders": 0,
         "ai_orders": 0, "routine": "Staggered training", "ai_uniform": "metal crossbow",
         "power": {"power": power, "armed": members, "melee_power": 0, "ranged_power": power}}
    q.update(kw)
    return q


def long_alarm(rows, squads, days=31, inside=()):
    s = copy.deepcopy(BASE)
    s["date"] = {"day": 13, "month": "Timber", "season": "autumn", "tick": 100000, "year": 257}
    s["others_on_map"]["threats"] = rows
    s["others_on_map"]["threats_that_can_reach_dwarves"] = len(rows)
    s["military"]["squads"] = squads
    s["military"]["soldiers"] = sum(int(q.get("members") or 0) for q in squads)
    s["civ_alert"] = True
    s["civ_alert_ready"] = True
    s["settings"]["attack_policy"] = "ordinary"
    s["entrances"]["intruders_inside"] = list(inside)
    s["entrances"]["scanned_tick"] = 257 * 403200 + 100000 - 100
    s = digest.normalize(s)
    m = Memory(ai_alert_raised=True)
    m.alarm_gov = {"on": {"tick": abs_tick(s) - days * DAY, "cause": "reach", "key": "reach", "why": "1 threat(s)"}}
    return s, m


@test("S2 unfought: 0.4x against a beast out in the fort's reach (not among the dwarves): no all-out attack "
      "(was: at 0.25x); about even odds: it goes")
def _():
    s, m = long_alarm([beast()], [xbows(8.0)])
    uf = wh.unfought(s, m, CFG, [20001])
    assert uf["mode"] == "lift" and 0.3 < uf["ratio"] < 0.5 and "1x at least" in uf["why"], uf
    s, m = long_alarm([beast()], [xbows(30.0)])
    uf = wh.unfought(s, m, CFG, [20001])
    assert uf["mode"] == "fight" and uf["ratio"] >= 1.0, uf


@test("S2 unfought: a fire breather wants a clear win (2x); inside among the dwarves the bar is halved")
def _():
    bar, _ = wh.fight_bar_unfought({}, CFG, [beast(fire_breather=True)])
    assert bar == 2.0, bar
    s, m = long_alarm([beast(distance_to_nearest_dwarf=3)], [xbows(12.0)], inside=[20001])
    bar, why = wh.fight_bar_unfought(s, CFG, s["others_on_map"]["threats"])
    assert bar == 0.5 and "inside among the civilians" in why, (bar, why)
    uf = wh.unfought(s, m, CFG, [20001])
    assert uf["mode"] == "fight" and 0.5 <= uf["ratio"] < 1.0, uf


@test("S2 the all-out attack begun below even odds ends at its first soldier lost (was: a third), and the "
      "alarm comes down for a beast away from the dwarves")
def _():
    s, m = long_alarm([beast(distance_to_nearest_dwarf=3)], [xbows(12.0)], inside=[20001])
    uf = wh.unfought(s, m, CFG, [20001])
    assert uf["mode"] == "fight" and uf["ratio"] < 1.0, uf
    wh.book_unfought(s, m, uf)
    assert abs(m.atlas["unfought"]["ratio"] - uf["ratio"]) < 0.01, m.atlas["unfought"]
    # one of six lost, the beast gone off from the dwarves (far): lifted, the fight over
    later = copy.deepcopy(s)
    later["military"]["squads"][0].update(ai_orders=1, kill_ids=[20001], members=5)
    later["military"]["soldiers"] = 5
    later["others_on_map"]["threats"][0]["distance_to_nearest_dwarf"] = 80
    later["entrances"]["intruders_inside"] = []
    later["date"]["tick"] += 200
    uf2 = wh.unfought(later, m, CFG, [20001])
    assert uf2["mode"] == "lift" and "turned bad" in uf2["why"] and "1 of 6" in uf2["why"], uf2
    # at even odds or better, one lost is no reason to stop
    s, m = long_alarm([beast()], [xbows(80.0)])
    uf = wh.unfought(s, m, CFG, [20001])
    assert uf["mode"] == "fight" and uf["ratio"] >= 1.0, uf
    wh.book_unfought(s, m, uf)
    later = copy.deepcopy(s)
    later["military"]["squads"][0].update(ai_orders=1, kill_ids=[20001], members=5)
    later["military"]["soldiers"] = 5
    assert wh.unfought(later, m, CFG, [20001])["mode"] == "fight"


def c_fort(members=9, start=9):
    titan = {"id": 16481, "name": '"Chantbeaches", Mountain Titan', "great_danger": True, "kinds": ["Titan"],
             "can_reach_dwarves": True, "size": 3000000, "layer": "upper_levels", "distance_to_nearest_dwarf": 30,
             "pos": {"x": 93, "y": 154, "z": 168}}
    q = {"id": 185, "name": "Squad 185", "members": members, "size": 10, "leader": True, "orders": 0,
         "ai_orders": 1, "kill_ids": [16481], "routine": "Staggered training",
         "power": {"power": 2.6, "armed": members, "melee_power": 2.6, "ranged_power": 0}}
    s, m = long_alarm([titan], [q])
    m.kill_sent_at = {"185": abs_tick(s) - 400}
    m.holdfast = {"kill": {"185": {"members": start, "tick": abs_tick(s) - 400}}}
    return s, m, q, titan


@test("S2 recall_hold: at poor odds (0.5x) the first soldier lost ends the hold; at even odds it doesn't")
def _():
    s, m, q, t = c_fort()
    assert wh.recall_hold(s, m, CFG, q, [t], 0.5), "not losing: held (C y255)"
    s, m, q, t = c_fort(members=8)
    assert wh.recall_hold(s, m, CFG, q, [t], 0.5) == ""
    assert wh.recall_hold(s, m, CFG, q, [t], 1.5), "even odds, one lost: held on"


# --- S3: no lift with a great danger among the civilians -----------------------------------

def titan(**kw):
    t = {"id": 20001, "name": "Fishlobster, Hill Titan", "great_danger": True, "fire_breather": False,
         "kinds": ["Titan"], "can_reach_dwarves": True, "size": 5000000, "layer": "fort_levels",
         "distance_to_nearest_dwarf": 2, "pos": {"x": 108, "y": 152, "z": 153}}
    t.update(kw)
    return t


@test("S3 the 60-day hard lift: never with a titan inside near the dwarves (the alarm stays, a note says the "
      "shelter keeps them and what it holds); a goblin there, or the titan far off: lifted")
def _():
    sq = {"id": 1, "name": "Squad 1", "members": 6, "size": 10, "leader": True, "orders": 0, "ai_orders": 1,
          "kill_ids": [20001], "routine": "Staggered training",
          "power": {"power": 20.0, "armed": 6, "melee_power": 20.0, "ranged_power": 0}}
    s, m = long_alarm([titan()], [dict(sq)], days=61, inside=[20001])
    m.shelter_supply = {"tick": abs_tick(s) - 100, "tiles": 400, "drink_short": "drink 12 for 40"}
    uf = wh.unfought(s, m, CFG, [20001])
    assert uf["mode"] == "keep" and "drink 12 for 40" in uf["why"] and "shelter" in uf["why"], uf
    p, notes = plan(s, m)
    assert not offs(p), [x.reason for x in offs(p)]
    assert any("Fishlobster is inside the fort near the dwarves" in n for n in notes), \
        [n for n in notes if "alarm" in n][:4]
    gob = titan(name="a goblin", great_danger=False, kinds=[], invader=True)
    s, m = long_alarm([gob], [dict(sq)], days=61, inside=[20001])
    assert wh.unfought(s, m, CFG, [20001])["mode"] == "lift"
    s, m = long_alarm([titan(distance_to_nearest_dwarf=90)], [dict(sq)], days=61, inside=[20001])
    assert wh.unfought(s, m, CFG, [20001])["mode"] == "lift"
    s, m = long_alarm([titan()], [dict(sq)], days=61, inside=[])       # out in the open, not inside
    assert wh.unfought(s, m, CFG, [20001])["mode"] == "lift"


# --- S7: drink orders' stalled copies -------------------------------------------------------

def drink_fort(drink):
    s = copy.deepcopy(BASE)
    s["date"] = {"day": 1, "month": "Granite", "season": "spring", "tick": 200000, "year": 260}
    s = digest.normalize(s)
    s["civ_alert"] = False
    s["stocks"]["drink"] = drink
    s["dwarves"]["total"] = 50
    s["orders"] = [{"id": i, "recipe": "brew_drink", "amount_left": 5, "amount_total": 5, "by_ai": True,
                    "active": True, "validated": True} for i in (801, 802, 803)]
    m = Memory()
    now = abs_tick(s)
    m.order_watch = {str(i): {"left": 5, "since": now - d * DAY, "by_ai": True, "what": "brew_drink"}
                     for i, d in ((801, 60), (802, 50), (803, 35))}
    return s, m


@test("S7 _stuck_orders_rule: drink short (100 for 50): the two stalled extra brew orders are cancelled, the "
      "one that moved last stands, nothing banned (no `stuck`); drink plentiful: the last is cancelled too")
def _():
    from planner_orders import _stuck_orders_rule
    s, m = drink_fort(100)
    props = []
    _stuck_orders_rule(s, m, CFG, props)
    ids = sorted(p.action["order_id"] for p in props if p.action.get("type") == "cancel_work_order")
    assert ids == [801, 802], [(p.action, p.reason) for p in props]
    assert not any(p.action.get("stuck") for p in props), [p.action for p in props]
    assert all("the one that moved last stands" in p.reason for p in props), [p.reason for p in props]
    s, m = drink_fort(5000)
    props = []
    _stuck_orders_rule(s, m, CFG, props)
    ids = sorted(p.action["order_id"] for p in props if p.action.get("type") == "cancel_work_order")
    assert ids == [801, 802, 803], [(p.action, p.reason) for p in props]


if __name__ == "__main__":
    finish()
