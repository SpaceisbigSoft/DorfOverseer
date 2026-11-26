"""(item2) Fort A, the War-hold: a war stock of bolts that holds.

A (25 Nov 21:35-23:00, at war with the goblins): 10 crossbow soldiers (squad
202, the only ranged squad, "Staggered training" at archery range 767) with 0
of the 500 bolts wanted and no quiver carried. The journal:
  * `arms`: "125 bolts for 10 crossbow soldiers (500 wanted): make 5 lot(s)
    of wooden bolts" at 21:37, 22:20, 22:21, 22:22, 22:23: the rule took the
    gap as 500 wanted less the lots queued, and capped each order at 5 lots,
    so a 5-lot order never closed it and another came every cycle;
  * `stuck_order`: "the AI's wooden_bolts order (2 left) hasn't moved in 28
    days: cancel it (not placed again for 28 days)" three times, the hold
    doubling to 56, with nothing else ordered in its place;
  * the stock 125 -> 61 -> 19 -> 0 in an hour: the squad's one ammunition
    entry was for combat and training, and the range shot it all away.

Fixed:
  1. one open bolts order at a time, sized to the gap (`bolts_order_max`
     lots) (planner_military_squads._bolts_order);
  2. an AI bolts order that has stood still `bolts_stall_days` gets another
     material beside it (metal at the forge, wood at the bowyer's, bone at the
     craftsdwarf's), and a recipe select() would hold (stuck lately, no
     input, fuel, workshop or worker) gives way to the next, the reason said;
  3. at war (a civilization at war, enemies in reach, a siege, a siege
     invitation open) a crossbow squad's entry is split: a combat-only reserve
     (`bolts_reserve_per_soldier`) the training doesn't use, filled first
     (lua/ai-military-gear-ammo.lua split_bolts; planner_army._bolts_rule).

    python tests/test_item2_war_bolts.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402
from planner_core import TICKS_PER_DAY, abs_tick  # noqa: E402
from planner_military_squads import _ranged_squad_rule  # noqa: E402
from planner_army import _bolts_rule, war_stock_due  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TEMPLATES = ["Melee, leather armor", "Melee, metal armor", "Crossbows, leather armor", "Crossbows, metal armor"]
MELEE = {"id": 185, "members": 10, "size": 10, "leader": True, "uniform": True, "ai_uniform": "Melee, metal armor"}
XBOW = {"id": 202, "members": 10, "size": 10, "leader": True, "uniform": True, "ai_uniform": "Crossbows, metal armor",
        "routine": "Staggered training",
        "ammo": {"assigned": 0, "items": 0, "specs": 1, "units": 0, "wanted": 500, "reserve": 0, "reserve_units": 0}}
GOBLINS = {"id": 7, "name": "the goblins", "relation": "TotalWar"}


def a_fort(**gear):
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"] = dict(s["buildings"].get("workshops") or {}, Bowyers=1, MetalsmithsForge=1,
                                       Craftsdwarfs=1)
    s["stocks"] = dict(s.get("stocks") or {}, wood=120)
    s["supplies"] = dict(s.get("supplies") or {}, fuel=40)
    g = {"soldiers": 20, "armed": 18, "ranged_armed": 10, "spare_crossbows": 0, "crossbows_total": 10,
         "bolts": 0, "bolts_free": 0, "ranged_places": 10, "quivers_assigned": 10, "quivers_free": 0,
         "weapon_gaps": 2, "bars": {"IRON": 49}, "forges": 1}
    g.update(gear)
    s["military"] = dict(s.get("military") or {}, gear=g, squads=[dict(MELEE), copy.deepcopy(XBOW)],
                         uniform_templates=list(TEMPLATES))
    s.setdefault("world", {})["civs"] = [dict(GOBLINS)]
    return s, g


def run(s, memory=None):
    props = []
    _ranged_squad_rule(s, s["military"]["gear"], s["military"]["squads"], TEMPLATES, CFG, props, [185, 202],
                       False, memory, {})
    return [p for p in props if p.rule == "arms" and str(p.action.get("recipe", "")).endswith("_bolts")]


def order(oid, recipe, left, total=5):
    return {"id": oid, "recipe": recipe, "amount_left": left, "amount_total": total, "by_ai": True,
            "validated": True, "active": True}


def watched(memory, s, oid, recipe, left, days):
    memory.order_watch[str(oid)] = {"left": left, "since": abs_tick(s) - days * TICKS_PER_DAY, "by_ai": True,
                                    "what": recipe}


# ---- 1. one open order at a time, sized to the gap -----------------------------------------------------

@test("A: no bolts, none ordered: one order sized to the gap (500 wanted: bolts_order_max lots), wood first")
def _():
    s, g = a_fort()
    p = run(s, Memory())
    assert len(p) == 1 and p[0].action["recipe"] == "wooden_bolts", [x.action for x in p]
    assert p[0].action["amount"] == min(CFG["bolts_order_max"], 20), p[0].action


@test("A 22:20-22:23: an open wooden bolts order that moves: no second order, whatever the gap")
def _():
    s, g = a_fort(bolts=0)
    m = Memory()
    s["orders"] = [order(901, "wooden_bolts", 5)]          # 5 lots left of 500 wanted, 0 in stock
    watched(m, s, 901, "wooden_bolts", 5, 1)
    assert not run(s, m), [x.action for x in run(s, m)]
    s["orders"][0]["by_ai"] = False                           # the player's own order counts too
    assert not run(s, m)


@test("the gap closed (stock at the wanted amount): nothing ordered; partly: the rest, in lots of 25")
def _():
    s, g = a_fort(bolts=500)
    assert not run(s, Memory())
    s, g = a_fort(bolts=450)
    p = run(s, Memory())
    assert p and p[0].action["amount"] == 2, [x.action for x in p]


# ---- 2. a stalled order: another material beside it; a held recipe gives way ----------------------------

@test("A: the wooden bolts order stands at 2 left for 10 days: iron bolts at the forge beside it, the reason said")
def _():
    s, g = a_fort()
    m = Memory()
    s["orders"] = [order(901, "wooden_bolts", 2)]
    s["orders"][0]["jobs"] = {"n": 1, "suspended": 0, "working": 0, "why": "no citizen has the labour BOWYER"}
    watched(m, s, 901, "wooden_bolts", 2, 10)
    p = run(s, m)
    assert len(p) == 1 and p[0].action["recipe"] == "metal_bolts", [x.action for x in p]
    assert p[0].action["material"] == "INORGANIC:IRON" and p[0].action["amount"] == CFG["bolts_order_max"], p[0].action
    assert "wooden bolts order (2 left) has stood 10 days (no citizen has the labour BOWYER)" in p[0].reason, p[0].reason


@test("a stall shorter than bolts_stall_days is still the one open order: nothing beside it")
def _():
    s, g = a_fort()
    m = Memory()
    s["orders"] = [order(901, "wooden_bolts", 2)]
    watched(m, s, 901, "wooden_bolts", 2, CFG["bolts_stall_days"] - 1)
    assert not run(s, m)


@test("wooden bolts cancelled as stuck lately (held 28 days): metal, or bone with no bars, instead of nothing")
def _():
    s, g = a_fort()
    m = Memory()
    m.stuck_cancelled["wooden_bolts"] = {"tick": abs_tick(s) - 3 * TICKS_PER_DAY, "n": 2}
    p = run(s, m)
    assert p and p[0].action["recipe"] == "metal_bolts", [x.action for x in p]
    assert "wooden bolts: cancelled as stuck 3 day(s) ago" in p[0].reason, p[0].reason
    s, g = a_fort(bars={})
    s.setdefault("needs", {})["bones"] = 60
    p = run(s, m)
    assert p and p[0].action["recipe"] == "bone_bolts", [x.action for x in p]
    assert p[0].action["amount"] == CFG["bolts_order_max"], p[0].action


@test("the forge without fuel (select would hold it): wood after a stuck metal order, never a held order")
def _():
    s, g = a_fort(weapon_gaps=0, armed=20)        # every soldier armed: metal would come first
    s["supplies"]["fuel"] = 0
    s["buildings"]["workshops"]["MagmaForge"] = 0             # (the fixture's magma forges need none)
    m = Memory()
    p = run(s, m)
    assert p and p[0].action["recipe"] == "wooden_bolts", [x.action for x in p]
    assert "metal bolts" in p[0].reason and "charcoal" in p[0].reason, p[0].reason


# ---- 3. the war reserve the range doesn't use ------------------------------------------------------------

def bolts_props(s, memory=None):
    props, notes = [], []
    _bolts_rule(s, memory or Memory(), CFG, props, notes)
    return props


@test("A at war with the goblins: the crossbow squad's entry split, a combat-only reserve of 25 a soldier")
def _():
    s, g = a_fort()
    assert war_stock_due(s, Memory(), CFG) == "at war with the goblins"
    p = bolts_props(s)
    assert p and p[0].action == {"type": "split_bolts", "squad_id": 202,
                                 "reserve": 10 * CFG["bolts_reserve_per_soldier"]}, [x.action for x in p]
    assert "training at the range" in p[0].reason, p[0].reason


@test("split once: a squad with its reserve gets its bolts handed out as before; peace or an older bridge: no split")
def _():
    s, g = a_fort(bolts_free=60)
    s["military"]["squads"][1]["ammo"].update(reserve=250)
    p = bolts_props(s)
    assert p and p[0].action["type"] == "assign_bolts", [x.action for x in p]
    s, g = a_fort(bolts_free=60)
    s["world"]["civs"] = [dict(GOBLINS, relation="Peace")]
    p = bolts_props(s)
    assert p and p[0].action["type"] == "assign_bolts", [x.action for x in p]
    s, g = a_fort(bolts_free=60)
    del s["military"]["squads"][1]["ammo"]["reserve"]          # a bridge before item2
    p = bolts_props(s)
    assert p and p[0].action["type"] == "assign_bolts", [x.action for x in p]
    cfg = dict(CFG, bolts_reserve_per_soldier=0)                 # turned off
    s, g = a_fort()
    assert war_stock_due(s, Memory(), cfg) == ""


@test("the bridge: split_bolts is an action, honours a dry run, and forwards from ai-military")
def _():
    cat = (LUA_DIR / "ai-bridge-catalog.lua").read_text(encoding="utf-8")
    assert "split_bolts = act_split_bolts" in cat and "'split_bolts'," in cat
    assert "function act_split_bolts(a)" in (LUA_DIR / "ai-bridge-actions-fort.lua").read_text(encoding="utf-8")
    assert "'split_bolts'" in (LUA_DIR / "ai-military.lua").read_text(encoding="utf-8")
    assert "function split_bolts(squad_id, reserve, dry_run)" in (LUA_DIR / "ai-military-gear-ammo.lua").read_text(
        encoding="utf-8")
    for n in ("ai-bridge-catalog.lua", "ai-bridge-actions-fort.lua", "ai-military.lua", "ai-military-gear-ammo.lua"):
        assert (LUA_DIR / n).stat().st_size < 60 * 1024, n


@test("lua: split_bolts: a combat-only reserve first, the stacks moved onto it, the training entry keeps the rest")
def _():
    need_lua()
    from test_r2_h4 import ammo_env
    lua, n, env, eq, sq7, sq8 = ammo_env()
    env.set_bolts(sq8, 500)
    r = env.assign_bolts(False, 20)
    assert r.ok, dict(r)
    a = env.squad_ammo(sq8)
    assert a.reserve == 0 and a.units == 120, dict(a)
    d = env.split_bolts(8, 50, True)
    assert d.ok and d.dry_run and d.training == 450, dict(d)
    r = env.split_bolts(8, 50, False)
    assert r.ok and r.reserve == 50 and r.training == 450 and r.moved_bolts >= 50, dict(r)
    v = sq8.ammo.ammunition
    assert n(v) == 2 and v[0].amount == 50 and v[0].flags.use_combat and not v[0].flags.use_training
    assert v[1].amount == 450 and v[1].flags.use_training
    a = env.squad_ammo(sq8)
    assert a.reserve == 50 and a.reserve_units >= 50 and a.wanted == 500 and a.units == 120, dict(a)
    assert env.split_bolts(8, 50, False).rejected                         # split once
    assert env.split_bolts(7, 50, False).rejected                         # the melee squad


if __name__ == "__main__":
    finish()
