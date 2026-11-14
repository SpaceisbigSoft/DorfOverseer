"""(item5, group 5) The Hermit hold dies out. Fort D (Hammerstirred, Hermit
hold: Outsiders -150, Deference -60, Growth -60, Caution +60) sat at 15
dwarves y250-263 and then died to 8 by y269, 10 of them of thirst: the
queen's Make mandates (bucklers) went unmet (Deference -60 skipped every
mandate, and no recipe made shields), DF pinned 14 "production order
violations" on the fort's office holders, chained them in the jail, and with
no well (the inside-only spot refused, the cavern well "too young or small"
for 15 dwarves, 5 soldiers asked of a fort with 3) nobody could bring them
water: 9 died in their chains beside 22 drinks a dwarf.

The fixes tested here:
  * the floor: under `survival_floor` citizens DF's population cap opens to
    migrants and births whatever the sliders (not Extreme-low Growth), and
    DF's baby caps are raised (never lowered);
  * Make mandates met at low Deference while someone holds the guard's office;
    shields and bucklers have a recipe (wood, at the carpenter's);
  * prisoners count as a need for water: the well is urgent, a small fort may
    dig a cavern well, a small fort is asked for fewer soldiers;
  * prisoners with no water are let go (release_prisoners, the bridge);
  * the Lua: the new recipes, the release action, the baby caps.

    python tests/test_item5_hermit.py
"""

from __future__ import annotations

import ast
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_growth  # noqa: E402
import planner_society  # noqa: E402
import planner_wells  # noqa: E402
import overseer  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG
HERMIT = {"outsiders": -150, "trade": -100, "growth": -60, "caution": 60, "surface": -60, "fortification": 100,
          "deference": -60, "greed": 40, "stockpile": 60}


def fort(**changes) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    for path, value in changes.items():
        node = s
        keys = path.split("__")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
    return s


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


# ---- the floor ----------------------------------------------------------------------------

def cap_props(citizens: int, traits: dict, society: dict, goal: str = "expand") -> list:
    s = {"settings": {"traits": traits, "set_pop_cap": True, "fort_goal": goal},
         "society": society, "dwarves": {"total": citizens}, "date": {"year": 260, "season": "spring"}}
    props: list = []
    planner_growth._pop_cap_rule(s, Memory(), CFG, citizens, props, [])
    return props


@test("floor: a Hermit hold of 15 keeps its Growth cap (55); under a floor above the cap the cap rises to it")
def _():
    # D's own numbers: Growth -60 makes 55, above the floor: nothing to change
    assert not cap_props(15, HERMIT, {"pop_cap": 55, "strict_pop_cap": 75})
    # Growth -100 (25 dwarves wanted) with a floor of 30: the floor wins while under it
    cfg = dict(CFG, survival_floor=30)
    s = {"settings": {"traits": {"growth": -100}, "set_pop_cap": True, "fort_goal": "expand"},
         "society": {"pop_cap": 25, "strict_pop_cap": 45}, "dwarves": {"total": 12}, "date": {"year": 260}}
    props: list = []
    planner_growth._pop_cap_rule(s, Memory(), cfg, 12, props, [])
    assert props and props[0].action["cap"] == 30 and props[0].action["strict"] == 45, props
    assert "under its floor of 30" in props[0].reason, props[0].reason


@test("floor: Maintain and the strain hold don't shut a fort under its floor; Extreme-low Growth (shrink) still does")
def _():
    m = Memory()
    m.maintain_pop = 9
    s = {"settings": {"traits": {}, "set_pop_cap": True, "fort_goal": "maintain"},
         "society": {"pop_cap": 9, "strict_pop_cap": 9}, "dwarves": {"total": 9}, "date": {"year": 260}}
    props: list = []
    planner_growth._pop_cap_rule(s, m, CFG, 9, props, [])
    assert props and props[0].action["cap"] == CFG["survival_floor"], props
    assert props[0].action["strict"] == CFG["survival_floor"] + 10, props
    shrink = cap_props(9, {"growth": -150}, {"pop_cap": 7, "strict_pop_cap": 7})
    assert not shrink or shrink[0].action["cap"] == CFG["min_citizens"], shrink


@test("floor: DF's baby caps raised under the floor, never lowered, and not for a fort above it")
def _():
    p = cap_props(8, HERMIT, {"pop_cap": 55, "strict_pop_cap": 75, "baby_cap": 2, "baby_pct": 10})
    assert p and p[0].action.get("baby_cap") == CFG["floor_baby_cap"] and p[0].action.get("baby_pct") == CFG["floor_baby_pct"], p
    assert "baby cap" in p[0].reason, p[0].reason
    assert not cap_props(8, HERMIT, {"pop_cap": 55, "strict_pop_cap": 75, "baby_cap": 100, "baby_pct": 1000})
    assert not cap_props(30, HERMIT, {"pop_cap": 55, "strict_pop_cap": 75, "baby_cap": 2, "baby_pct": 10})
    # an older bridge without the baby caps: the cap alone
    assert not cap_props(8, HERMIT, {"pop_cap": 55, "strict_pop_cap": 75})


@test("floor: under it the AI says so, with the couples and children (homes report)")
def _():
    s = {"settings": {"traits": HERMIT, "set_pop_cap": True, "fort_goal": "expand"},
         "society": {"pop_cap": 55, "strict_pop_cap": 75}, "dwarves": {"total": 9}, "date": {"year": 268},
         "homes": {"couples": 0, "children": 2}}
    notes: list = []
    planner_growth._pop_cap_rule(s, Memory(), CFG, 9, [], notes)
    assert any("under its floor of 20" in n and "0 married couple(s), 2 child(ren)" in n and "strange moods" in n
               for n in notes), notes
    notes = []
    s["dwarves"]["total"] = 25
    planner_growth._pop_cap_rule(s, Memory(), CFG, 25, [], notes)
    assert not any("floor" in n for n in notes), notes


# ---- mandates -----------------------------------------------------------------------------

BUCKLERS = [{"by": "the queen", "days_left": 46, "item": "SHIELD", "kind": "Make", "material_is_stone": False,
             "remaining": 2, "subtype": "ITEM_SHIELD_BUCKLER", "total": 2}]


def with_guard(s: dict) -> dict:
    s.setdefault("offices", {}).setdefault("offices", {})["CAPTAIN_OF_THE_GUARD"] = {"held": ["Udil"], "vacant": 0}
    return s


@test("mandates: bucklers made in wood (the queen's mandate at Hammerstirred); a shield too")
def _():
    s = fort(mandates=copy.deepcopy(BUCKLERS))
    m = by_rule(plan(s, Memory())[0], "mandate")
    assert m and m[0].action == {"type": "work_order", "recipe": "wooden_buckler", "amount": 2}, m
    s["mandates"][0]["subtype"] = "ITEM_SHIELD_SHIELD"
    m = by_rule(plan(s, Memory())[0], "mandate")
    assert m and m[0].action["recipe"] == "wooden_shield", m


@test("mandates: low Deference (the Hermit's -60) meets them while the guard can jail someone; not without a guard")
def _():
    s = fort(mandates=copy.deepcopy(BUCKLERS))
    s["settings"]["traits"] = dict(HERMIT)
    p, notes = plan(s, Memory())
    assert not by_rule(p, "mandate"), "no guard: the low Deference leaves them"
    with_guard(s)
    p, notes = plan(s, Memory())
    assert by_rule(p, "mandate"), [x.rule for x in p]
    assert any("jails one of the fort's own" in n for n in notes), notes


@test("mandates: the Lua recipes exist (wood, at the carpenter's) and the brain finds their workshop")
def _():
    src = (ROOT / "lua" / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert "wooden_buckler = {job = 'MakeShield', item_subtype = 'ITEM_SHIELD_BUCKLER', material_category = {'wood'}}" in src
    assert "wooden_shield = {job = 'MakeShield', item_subtype = 'ITEM_SHIELD_SHIELD', material_category = {'wood'}}" in src
    from planner_core import recipe_shop
    assert recipe_shop("wooden_buckler") == "Carpenters" and recipe_shop("wooden_shield") == "Carpenters"


# ---- water for the jail -------------------------------------------------------------------

def jail(prisoners: list, wells: int = 0, citizens: int = 15) -> dict:
    return {"justice": {"prisoners": prisoners, "punish": {"n": len(prisoners), "prison": len(prisoners)}},
            "buildings": {"other": {"Well": wells} if wells else {}},
            "projects": {"open": []}, "dwarves": {"total": citizens}}


@test("prisoners: no well, so every citizen in the jail is let go before thirst kills them")
def _():
    s = jail([{"id": 17235, "name": "Iden", "thirst": 1000, "days": 300}])
    props: list = []
    planner_society._prisoner_water_rule(s, CFG, props, [])
    assert props and props[0].action == {"type": "release_prisoners"}, props
    assert "no well" in props[0].reason and "Iden" in props[0].reason, props[0].reason
    assert props[0].priority <= 1


@test("prisoners: with a well only the thirsty ones go; none in the jail: nothing")
def _():
    s = jail([{"id": 1, "thirst": 1000}, {"id": 2, "thirst": 45000}], wells=1)
    props: list = []
    planner_society._prisoner_water_rule(s, CFG, props, [])
    assert props and props[0].action == {"type": "release_prisoners", "ids": [2]}, props
    s = jail([{"id": 1, "thirst": 1000}], wells=1)
    props = []
    planner_society._prisoner_water_rule(s, CFG, props, [])
    assert not props
    props = []
    planner_society._prisoner_water_rule(jail([]), CFG, props, [])
    assert not props
    # a cavern well whose shaft gate is shut gives no water: as no well
    s = jail([{"id": 3, "thirst": 10}], wells=1)
    s["projects"]["well_lids"] = [{"gate": "closed", "project_id": 9}]
    props = []
    planner_society._prisoner_water_rule(s, CFG, props, [])
    assert props and "ids" not in props[0].action, props


@test("prisoners: the rule is wired into the plan, and the action has words")
def _():
    s = fort()
    s["justice"] = {"prisoners": [{"id": 5, "name": "Zasit", "thirst": 0}], "punish": {"n": 1, "prison": 1}}
    s["buildings"]["other"].pop("Well", None)
    p, _n = plan(s, Memory())
    assert by_rule(p, "prisoners_water"), [x.rule for x in p]
    assert overseer.short({"type": "release_prisoners"}) == "let the jailed go (no water for them)"


@test("wells: a jailed dwarf makes the missing well urgent; the cavern well need names them")
def _():
    assert planner_wells.jailed({"justice": {"prisoners": [{"id": 1}, {"id": 2}]}}) == 2
    assert planner_wells.jailed({"justice": {"punish": {"prison": 3}}}) == 3
    assert planner_wells.jailed({}) == 0
    s = {"dwarves": {"total": 15}, "stocks": {"drink": 300}, "justice": {"prisoners": [{"id": 1}]}}
    assert "in the jail need water" in planner_wells.cavern_well_need(s, CFG, 0)
    s = fort()
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["justice"] = {"prisoners": [{"id": 1, "thirst": 0}], "punish": {"prison": 1}}
    s["dwarves"]["needs_medical_care"] = 0
    s["society"]["parched"] = 0
    p, _n = plan(s, Memory())
    w = by_rule(p, "well")
    assert w and w[0].action.get("urgent") is True and "1 jailed" in w[0].reason, w


@test("cavern well: a small fort with no well and the thirsty or jailed may dig one; not when nobody waits")
def _():
    s = {"dwarves": {"total": 15}, "settings": {"traits": {}}, "stocks": {"drink": 300}}
    assert planner_wells.cavern_well_safe(s, CFG) == "the fort is too young or small"
    assert planner_wells.cavern_well_safe(s, CFG, urgent=True) is True


@test("cavern well: soldiers asked of a small fort scale with it (a soldier for every 5 dwarves at most)")
def _():
    def army(n):
        return {"soldiers": n, "squads": [{"id": 1, "members": n, "power": {"armed": n}}]}
    s = {"settings": {"traits": {"caution": 60}}, "dwarves": {"total": 15}, "military": army(3)}
    ok, have, need = planner_wells.cavern_soldiers_ready(s, CFG)
    assert ok and need == 3, (ok, have, need)       # D: 15 dwarves, 3 soldiers, Caution +60 (5 asked before)
    s["dwarves"]["total"] = 40
    ok, have, need = planner_wells.cavern_soldiers_ready(s, CFG)
    assert not ok and need == 5, (ok, have, need)   # a big fort: as before
    # the AI opens the unfound cavern for the jailed too
    s = {"settings": {"traits": {"caution": 60}}, "dwarves": {"total": 15, "needs_medical_care": 0},
         "society": {"parched": 0}, "stocks": {"drink": 300}, "military": army(3),
         "justice": {"prisoners": [{"id": 1}]}}
    ok, why = planner_wells.ai_opens_cavern(s, CFG)
    assert ok and "1 jailed" in why, why


@test("Hammerstirred's case end to end: Hermit sliders, the queen's bucklers, a guard, a convict in chains, no well")
def _():
    s = with_guard(fort(mandates=copy.deepcopy(BUCKLERS)))
    s["settings"]["traits"] = dict(HERMIT)
    s["buildings"]["other"].pop("Well", None)
    s["projects"]["open"] = []
    s["justice"] = {"prisoners": [{"id": 16783, "name": "Zasit", "thirst": 30000}], "punish": {"n": 1, "prison": 1}}
    p, notes = plan(s, Memory())
    rules = [x.rule for x in p]
    assert "mandate" in rules and "prisoners_water" in rules, rules
    assert by_rule(p, "mandate")[0].action["recipe"] == "wooden_buckler"
    w = by_rule(p, "well")
    assert w and w[0].action.get("urgent") is True, rules


# ---- the bridge (Lua) ---------------------------------------------------------------------

def _harness() -> str:
    tree = ast.parse((ROOT / "tests" / "test_bridge_memory.py").read_text(encoding="utf-8"))
    return next(n.value.value for n in tree.body
                if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", None) == "HARNESS")


def lua_test(name):
    def deco(fn):
        if LuaRuntime is None:
            return fn
        return test(name)(fn)
    return deco


@lua_test("bridge: release_prisoners cuts a citizen's sentence to its last day; the dead, strangers and the free are left")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(_harness(), (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
    M = H.module()
    r = lua.execute(r"""
    local M, H = ...
    local df, dfhack = H.df, H.dfhack
    local units = {[1] = {id = 1, cit = true}, [2] = {id = 2, cit = true, dead = true},
                   [3] = {id = 3, cit = false}, [4] = {id = 4, cit = true}}
    df.unit = {find = function(id) return units[id] end}
    dfhack.units = {isCitizen = function(u) return u.cit end, isDead = function(u) return u.dead == true end,
                    getReadableName = function(u) return 'dwarf ' .. u.id end}
    dfhack.df2utf = function(s) return s end
    local pun = {{criminal = units[1], prison_counter = 3000}, {criminal = units[2], prison_counter = 3000},
                 {criminal = 3, prison_counter = 3000}, {criminal = units[4], prison_counter = 0}}
    df.global.plotinfo.punishments = pun
    local act = M.ACTIONS.release_prisoners
    local bad = act({ids = 'x'})
    local none_left = act({ids = {4}})
    local r = act({})
    return bad.ok, none_left.ok, r.ok, r.released, r.names[1], pun[1].prison_counter, pun[2].prison_counter,
           pun[3].prison_counter, pun[4].prison_counter
    """, M, H)
    bad, none_left, ok, n, name, c1, c2, c3, c4 = r
    assert bad is False and none_left is False
    assert ok and n == 1 and name == "dwarf 1", r
    assert (c1, c2, c3, c4) == (1, 3000, 3000, 0), r


@lua_test("bridge: the justice report lists the prisoners with their thirst")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(_harness(), (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8"), str(ROOT / "lua"))
    M = H.module()
    r = lua.execute(r"""
    local M, H = ...
    local df, dfhack = H.df, H.dfhack
    local u = {id = 7, counters2 = {thirst_timer = 52000}}
    df.unit = {find = function(id) return id == 7 and u or nil end}
    dfhack.units = {isDead = function() return false end, getReadableName = function() return 'Iden' end}
    dfhack.df2utf = function(s) return s end
    df.global.plotinfo.punishments = {{criminal = 7, prison_counter = 900}, {criminal = 8, prison_counter = 0}}
    df.global.world.buildings = {other = {ZONE_DUNGEON = {}, CHAIN = {}, CAGE = {}}}
    df.global.world.crimes = {all = {}}
    local j = M.get_justice()
    return #j.prisoners, j.prisoners[1].id, j.prisoners[1].thirst, j.prisoners[1].name, j.punish.prison
    """, M, H)
    assert r == (1, 7, 52000, "Iden", 1), r


@lua_test("ai-society: the baby caps read, and raised (never lowered) by set_popcap")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    env.require = function(name) if name == 'utils' then return {insert_sorted = function() end} end return require(name) end
    env.df = {global = {d_init = {dwarf = {population_cap = 55, strict_population_cap = 75,
                                           baby_cap_absolute = 2, baby_cap_percent = 500}}}}
    env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end}}
    assert(load(src, 'ai-society', 't', env))()
    return env
    """, module_src("ai-society.lua"))
    c = env.get_popcap()
    assert (c.cap, c.strict, c.baby_cap, c.baby_pct) == (55, 75, 2, 500), dict(c)
    r = env.set_popcap(55, 75, 10, 100)
    d = env.df["global"]["d_init"]["dwarf"]
    assert r.ok and d.baby_cap_absolute == 10 and d.baby_cap_percent == 500, (dict(r), dict(d))
    assert r.baby_cap == 10 and r.baby_pct is None


@test("bridge: release_prisoners is in the action table; set_population_cap passes the baby caps on")
def _():
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "release_prisoners = act_release_prisoners" in src
    acts = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "set_popcap(cap, strict, babies, pct)" in acts


if __name__ == "__main__":
    finish()
