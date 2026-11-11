"""(0.105.33 fix, area "people") The verifiers' findings fixed: the hospital
burrow's source cache, drink and food in barrels (recreation burrow, shelter),
the idle-driven rules' lines on the stricter idle measure, Gem-mad in neutral
forts, prune_remains' unburied count, the young fort's strain hold and the
recreation status in the report.

    python tests/test_r33_fix_people.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import quirks  # noqa: E402
import test_r33_society as T  # noqa: E402   (its fakes; its tests don't run here)
from lua_modules_util import module_src  # noqa: E402
from planner import Memory, plan  # noqa: E402
from planner_core import PLANNER_CONFIG, IDLE_OLD_LINES, _idle_share, idle_line, update_idle  # noqa: E402
from planner_growth import fort_strain  # noqa: E402
from planner_industry import _gems_rule  # noqa: E402
from planner_military import idle_hands  # noqa: E402

LUA_DIR = ROOT / "lua"
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)


def by_rule(ps, rule):
    return [p for p in ps if p.rule == rule]


# ------------------------------------------------------------------ hospital burrow cache

@test("fix hospital_sources_cached: a pile removed meanwhile is never read through its old object")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(T.HOSP, module_src("ai-society.lua"))
    env.hospital_burrow_tick(30, 10, False)
    env.hospital_burrow_status()
    lua.execute("""local env, W = ...
        env.TOUCHED = {}
        local real = env.dfhack.buildings.getStockpileContents
        env.dfhack.buildings.getStockpileContents = function(b) env.TOUCHED[b.id] = true; return real(b) end
        for i = #W.all, 1, -1 do if W.all[i] == W.drink then table.remove(W.all, i) end end""", env, w)
    env.hospital_burrow_status()
    assert not env.TOUCHED[80], "the removed pile 80 was read"
    src = (LUA_DIR / "ai-society-burrows.lua").read_text(encoding="utf-8")
    body = src[src.index("local function hospital_sources_cached"):src.index("-- The members' checks")]
    assert "ids = ids" in body and "src = c.src" not in body
    assert "dfhack.onStateChange['ai-society-burrows-hb']" in src and "HB_SRC = nil" in src


@test("fix hospital_sources_cached: the cached pile still there is found again by id (a cache hit)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(T.HOSP, module_src("ai-society.lua"))
    env.hospital_burrow_tick(30, 10, False)
    a = env.hospital_burrow_status()
    b = env.hospital_burrow_status()
    assert a.drink == b.drink and b.drink is not None, (a.drink, b.drink)


# ------------------------------------------------------------------ drink in barrels

ITEMS = """local env = ...
    env.dfhack.items.getHolderUnit = function(i) return i.holder end
    env.dfhack.items.getContainer = function(i) return i.container end
"""


@test("fix rec_water: drink in a barrel (in_inventory, no holder) is drink in the burrow; carried or forbidden barrel isn't")
def _():
    def run(flags, extra=""):
        lua, env, units, assigned, ntiles, g = T.soc()
        lua.execute(ITEMS + "env.df.global.world.items.other.DRINK[0].flags = %s\n%s" % (flags, extra), env)
        r = env.recreation_tick(8, 28, False)
        return env.recreation_status(), r
    s, r = run("{in_inventory = true}")
    assert s.water == "drink" and s.members == 3 and r.error is None, (s.water, s.members, r.error)
    s, r = run("{in_inventory = true}", "env.df.global.world.items.other.DRINK[0].holder = {id = 5}")
    assert s.water != "drink", s.water
    s, r = run("{in_inventory = true}",
               "env.df.global.world.items.other.DRINK[0].container = {flags = {forbid = true}}")
    assert s.water != "drink", s.water


@test("fix shelter item_spots: drink and food in a barrel or bin count; a carried one doesn't")
def _():
    def run(extra):
        lua, env, got, w = T.shelter_world()
        lua.execute(ITEMS + """local w = select(2, ...)
            for i = 1, 20 do env.dfhack.units.getCitizens()[i] = {pos = {z = 170}} end
            w.drinks[1] = {flags = {in_inventory = true}, pos = {x = 120, y = 150, z = 166}, stack_size = 60}
            env.df.global.world.items.other.ANY_GOOD_FOOD = {{flags = {in_inventory = true},
                pos = {x = 121, y = 150, z = 166}, stack_size = 60}}
            """ + extra, env, w)
        return env.refresh_shelter()
    r = run("")
    assert r.drink_units == 60 and r.food_units == 60 and not r.no_food, (r.drink_units, r.food_units, r.no_food)
    r = run("w.drinks[1].holder = {id = 3}; env.df.global.world.items.other.ANY_GOOD_FOOD[1].container = "
            "{flags = {forbid = true}}")
    assert not r.drink_units and not r.food_units, (r.drink_units, r.food_units)


# ------------------------------------------------------------------ idle lines

def idle_state(free=None, idle_adults=0, adults=60, squads=10, traits=None):
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = dict(traits or {})
    s["dwarves"]["adults"] = adults
    s["dwarves"]["in_squads"] = squads
    s["dwarves"]["idle_adults"] = idle_adults
    if free is not None:
        s["dwarves"]["idle_free"] = free
    return s


@test("fix idle lines: lowered for the stricter measure (polish 0.15, blocks 0.14, garden 0.14, train 0.20/0.14)")
def _():
    assert (CFG["polish_idle_share"], CFG["idle_blocks_share"], CFG["garden_idle_share"],
            CFG["idle_train_share"], CFG["idle_train_off_share"]) == (0.15, 0.14, 0.14, 0.2, 0.14)
    assert CFG["idle_share"] == 0.25                        # the old-measure rules (industry, trade, world) unchanged
    s = idle_state(free=8)                                  # 8 of 50 outside squads: 16%
    assert abs(_idle_share(s) - 0.16) < 1e-9
    assert idle_line(s, CFG, "polish_idle_share") == 0.15
    old = idle_state(idle_adults=8)                         # no idle_free: the old measure and the old lines
    for k, v in IDLE_OLD_LINES.items():
        assert abs(idle_line(old, CFG, k) - v) < 1e-9, (k, idle_line(old, CFG, k))
    tuned = dict(CFG, polish_idle_share=0.3)                # a tuned line keeps its lean on the old measure
    assert abs(idle_line(old, tuned, "polish_idle_share") - 0.6) < 1e-9


@test("fix idle lines: 22% truly idle trains (on at 0.20, off under 0.14); 16% polishes (0.15), 12% doesn't")
def _():
    assert idle_hands(idle_state(free=11), None, CFG)       # 22%: not at the old 0.40
    assert not idle_hands(idle_state(free=8), None, CFG)    # 16%
    m = Memory()
    for _ in range(40):
        update_idle(idle_state(free=11), m, CFG)
    assert m.idle_hands
    for _ in range(40):
        update_idle(idle_state(free=8), m, CFG)             # 16%: over the off line, stays on
    assert m.idle_hands
    for _ in range(40):
        update_idle(idle_state(free=5), m, CFG)             # 10%: off
    assert not m.idle_hands

    def polish(free):
        s = idle_state(free=free)
        s["projects"]["done_total"] = 3
        return by_rule(plan(s, Memory())[0], "polish")
    assert polish(8) and not polish(6), (polish(8), polish(6))


@test("fix idle lines: the blocks rule fires from 15% truly idle; the industry rules keep idle_share on idle_adults")
def _():
    s = idle_state(free=8)                                  # 16% > 0.14
    s["stocks"]["blocks"] = 0
    s["stocks"]["boulders"] = 500
    s.pop("stone_use", None)
    got = by_rule(plan(s, Memory())[0], "idle")
    s2 = idle_state(free=6)                                 # 12% < 0.14
    s2["stocks"]["blocks"] = 0
    s2["stocks"]["boulders"] = 500
    s2.pop("stone_use", None)
    none = by_rule(plan(s2, Memory())[0], "idle")
    assert got and not none, (got, none)
    src = (ROOT / "brain" / "planner.py").read_text(encoding="utf-8")
    assert 'idle_line(s, cfg, "idle_blocks_share") * cfg["idle_share"]' in src


@test("fix idle lines: over the 8 Nov run the new lines fire about as often as the old did (run data, if present)")
def _():
    import glob
    files = glob.glob("/home/claude/run8nov/*/forts/region4-1430/states/*.json")
    if not files:
        return
    old_n = new_n = 0
    for p in files:
        st = json.load(open(p))
        dw = st.get("dwarves") or {}
        soc = (st.get("needs") or {}).get("social") or {}
        if not isinstance(soc.get("idle"), int) or not dw.get("adults"):
            continue
        old_n += (dw.get("idle_adults") or 0) / dw["adults"] >= 0.30
        new_n += soc["idle"] / max(1, dw["adults"] - (dw.get("in_squads") or 0)) >= CFG["polish_idle_share"]
    assert old_n and abs(new_n - old_n) <= max(3, old_n // 10), (old_n, new_n)


# ------------------------------------------------------------------ Gem-mad

@test("fix gem_mad: a Greed-0 fort no longer earns it (and keeps encrusting); Greed +1 does")
def _():
    def earn(g):
        h = {}
        for days in (0, 90):
            quirks.update(h, {"greed": g}, {"cut_gems": 30, "rough_gems": 30}, {"year": 252, "tick": days * 1200},
                          extra={"jewelers": 1, "gems": 60, "cut_gems": 30})
        return h
    h0 = earn(0)
    assert "gem_mad" not in (h0.get("quirks") or {}), h0.get("quirks")
    assert "gem_mad" in (earn(1).get("quirks") or {})
    m = Memory()
    m.culture = h0
    s = {"trade": {"goods": 40, "cut_gem": {"n": 20, "total": 30, "token": "INORGANIC:AMETHYST"}},
         "settings": {"traits": {"greed": 0}}, "buildings": {"workshops": {"Jewelers": 1}}, "orders": [],
         "moods": {"list": []}}
    p, notes = [], []
    _gems_rule(s, CFG, p, {"greed": 0}, m, notes)
    assert p and p[0].action["recipe"] == "encrust_goods" and not notes, (p, notes)


# ------------------------------------------------------------------ prune_remains

HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                    (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)


@test("fix prune_remains: a non-dwarf citizen's corpse stops the one pass; a visitor's of another civ doesn't")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    H = lua.execute(HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))
    env = H.module()
    n_goblin, n_visitor, n_lost, cmds = lua.execute(r"""
      local env, H = ...
      local df = H.df
      df.global.plotinfo = {race_id = 1, civ_id = 7}
      local units = {[10] = {civ_id = 7}, [11] = {civ_id = 99}}
      df.unit = {find = function(id) return units[id] end}
      local W = df.global.world
      W.items = W.items or {}
      W.items.other = W.items.other or {}
      W.items.other.CORPSE = {{race = 5, unit_id = 10, flags = {}}}         -- a goblin citizen
      local a = env.unburied_citizens()
      W.items.other.CORPSE = {{race = 1, unit_id = 11, flags = {}},          -- a dwarf of another civ
                              {race = 5, unit_id = 10, flags = {in_building = true}}}   -- ours, entombed
      local b = env.unburied_citizens()
      W.items.other.CORPSE = {{race = 1, unit_id = 404, flags = {}}}        -- unit gone: our race counts
      local c = env.unburied_citizens()
      W.items.other.CORPSE = {{race = 5, unit_id = 10, flags = {}}}
      H.cmds = {}
      H.dfhack.findScript = function() return '/df/hack/scripts/deteriorate.lua' end
      H.dfhack.run_command_silent = function(...) table.insert(H.cmds, table.concat({...}, ' ')); return 'ok', 0 end
      env.act_prune_remains({})
      return a, b, c, table.concat(H.cmds, '|')
    """, env, H)
    assert (n_goblin, n_visitor, n_lost) == (1, 0, 1), (n_goblin, n_visitor, n_lost)
    assert "now corpses" not in cmds, cmds


# ------------------------------------------------------------------ young fort strain

def strained(pop=7, drink=None, meals=None, unhappy=0):
    s = copy.deepcopy(BASE)
    s["settings"]["traits"] = {}
    s["dwarves"]["total"] = pop
    s["dwarves"]["stress"] = {"content": pop - unhappy, "unhappy": unhappy}
    s["stocks"]["drink"] = pop * 10 if drink is None else drink
    s["stocks"]["prepared_meals"] = pop * 10 if meals is None else meals
    s["farms"] = {}
    return s


@test("fix fort_strain: a young fort short of drink is held; its meals and unhappy lines are skipped")
def _():
    from planner_core import young_fort
    s = strained(drink=0, meals=0, unhappy=4)
    assert young_fort(s, CFG)
    got = fort_strain(s, CFG)
    assert any("drink" in x for x in got) and not any("meals" in x or "unhappy" in x for x in got), got
    assert fort_strain(strained(meals=0, unhappy=4), CFG) == []


# ------------------------------------------------------------------ the report's recreation section

@test("fix report: recreation_status gets txt; a failure is {error=...}, so the brain lets everyone out")
def _():
    src = (LUA_DIR / "ai-bridge-report.lua").read_text(encoding="utf-8")
    assert "pcall(soc.recreation_status, txt)" in src
    assert "out.recreation = {error = tostring(rec):sub(1, 160)}" in src
    import planner_society as PS
    s = copy.deepcopy(BASE)
    s.setdefault("society", {})["recreation"] = {"error": "boom"}
    s["dwarves"]["total"] = 60
    props = []
    PS._recreation_rule(s, CFG, [], props)
    assert props and props[0].action.get("release") is True, props


if __name__ == "__main__":
    finish()
