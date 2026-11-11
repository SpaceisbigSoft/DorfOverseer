"""(0.105.33, group bridge) The bridge hub, the report, the actions and the
orders fixed in round 33, on the stub DFHack of test_hygiene_bridge in a real
Lua engine (pip install lupa), plus digest.normalize's failed-section list.

    python tests/test_r33_bridge.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
RESULTS = []

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

from digest import normalize  # noqa: E402

LUA_DIR = ROOT / "lua"
HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                    (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)
LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))


def t(d):
    if isinstance(d, dict):
        return LUA.table_from({k: t(v) for k, v in d.items()})
    if isinstance(d, list):
        return LUA.table_from([t(v) for v in d])
    return d


def test(name):
    def wrap(fn):
        H.scripts = LUA.table()
        H.halted = False
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


def src(name: str) -> str:
    return (LUA_DIR / f"{name}.lua").read_text(encoding="utf-8")


STONE = r"""
local env, H, flags = ...
local df = H.df
local n = 0
for _ in pairs(flags) do n = n + 1 end
local econ = setmetatable({}, {__len = function() return n end, __index = function(_, k) return flags[k] end})
df.global.plotinfo.economic_stone = econ
local function boulder(idx) return {flags = {}, mat_type = 0, mat_index = idx,
    getStackSize = function() return 5 end, getMaterial = function() return 0 end,
    getMaterialIndex = function() return idx end} end
df.global.world.items = {other = {BOULDER = {boulder(0), boulder(1)}}}
df.global.world.raws.descriptors.colors = {}
df.global.world.raws.inorganics.all = {[0] = {id = 'GRANITE', metal_ore = {mat_index = {}}, material = {reaction_class = {}}},
                                       [1] = {id = 'HEMATITE', metal_ore = {mat_index = {1}}, material = {reaction_class = {}}}}
local old = H.dfhack.matinfo.decode
H.dfhack.matinfo.decode = function(t, i) return {material = {flags = {IS_STONE = true},
    state_color = {Solid = -1}, state_name = {Solid = 'stone ' .. i}, material_value = 1},
    getToken = function() return 'INORGANIC:' .. i end} end
H.dfhack.df2utf = function(s) return s end
env.REPORT_MEMO = nil
local st = env.get_stone_types()
local use = env.get_stone_use()
H.dfhack.matinfo.decode = old
df.global.plotinfo.economic_stone = {}
local toks = {}
for _, s in ipairs(st) do table.insert(toks, s.token) end
return table.concat(toks, ','), use.usable, use.economic.HEMATITE ~= nil
"""


@test("L2 High report 497-503: get_stone_types keeps ordinary stone when economic_stone holds 0/1 numbers")
def _():
    env = H.module()
    toks, usable, hem = LUA.execute(STONE, env, H, LUA.table_from({0: 0, 1: 1}))
    assert toks == "INORGANIC:0", toks          # granite listed, the economic hematite left out
    assert usable == 5 and hem, (usable, hem)   # stone_use agrees (the same helper)
    # booleans (an older DF / the tests' stubs) still work
    toks, usable, hem = LUA.execute(STONE, env, H, LUA.table_from({0: False, 1: True}))
    assert toks == "INORGANIC:0" and usable == 5 and hem, (toks, usable, hem)


@test("L2 Med bridge 787: a throw in get_dwarves fails the dwarves section, not the whole report")
def _():
    env = H.module()
    r = LUA.execute("""local env = ...
      env.SECTIONS = {date = env.SECTIONS.date, dwarves = env.SECTIONS.dwarves, units = env.SECTIONS.units,
                      wealth = env.SECTIONS.wealth}
      env.get_dwarves = function() error('unit field gone') end
      env.get_date = function() return {year = 3} end
      local ok, s = pcall(env.build_state, true, 'daily')
      return ok, ok and s.dwarves.error or s, ok and s.date.year, ok and s.wealth, ok and s.units and s.units.error
    """, env)
    ok, err, year, wealth, uerr = r
    assert ok and "unit field gone" in err and year == 3 and wealth == 1234 and "unit field gone" in uerr, r


@test("L2 Med bridge 529-547/613-624: date, wealth, civ_alert, paused and the map header are wrapped")
def _():
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local df = H.df
      local alerts, tasks = df.global.plotinfo.alerts, df.global.plotinfo.tasks
      df.global.plotinfo.alerts, df.global.plotinfo.tasks = nil, nil
      env.get_date = function() error('no calendar') end
      local oldmap = df.global.world.map
      df.global.world.map = nil
      env.layers_summary = function() return {} end
      env.get_dwarf_levels = function() return {} end
      local S = env.SECTIONS
      local out = {S.civ_alert().error ~= nil, S.wealth().error ~= nil, S.date().error ~= nil,
                   type(S.paused()) == 'boolean', S.map().error ~= nil, S.map().size == nil}
      df.global.plotinfo.alerts, df.global.plotinfo.tasks, df.global.world.map = alerts, tasks, oldmap
      out[7] = S.civ_alert() == false and S.wealth() == 1234 and S.map().error == nil
      return table.unpack(out)
    """, env, H)
    assert all(r), r


@test("L2 Med bridge 656-669: founding is keyed by save and site, and the map unload forgets it")
def _():
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local has = false
      H.scripts['ai-builder'] = {found_center = function() return {what = 'wagon'} end,
                                 has_staircase = function() return has end}
      env.FOUNDED_SITE, env.FOUNDED_NEAR = 7, 'wagon'      -- an old-style key from an earlier fort
      local a = env.SECTIONS.founding().stairs              -- scanned: false
      has = true
      local b = env.SECTIONS.founding().stairs              -- found and kept
      has = false
      local c = env.SECTIONS.founding().stairs              -- kept: no scan
      H.df.global.world.cur_savegame.save_dir = 'region1-copy'
      local d = env.SECTIONS.founding().stairs              -- another save of site 7: scanned again
      H.df.global.world.cur_savegame.save_dir = 'region1'
      return a, b, c, d, env.FOUNDED_SITE
    """, env, H)
    assert tuple(r[:4]) == (False, True, True, False), r
    s = src("ai-bridge-report")
    handler = s[s.index("dfhack.onStateChange[WATCH_KEY]"):]
    handler = handler[:handler.index("\n    end\n")]
    assert "SECTION_CACHE = {}" in handler and "FOUNDED_SITE, FOUNDED_NEAR = nil, nil" in handler, handler


@test("L2 Med bridge 763: a cached section from another save of the same site id is not sent")
def _():
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local built = 0
      env.SECTIONS = {industry = function() built = built + 1; return {n = built} end}
      env.SECTION_CACHE = {}
      env.get_dwarves = function() return {total = 0}, nil end
      local a = env.build_state(false, 'daily').industry.n
      local b = env.build_state(false, 'daily').industry.n      -- cached
      H.df.global.world.cur_savegame.save_dir = 'other world'
      local c = env.build_state(false, 'daily').industry.n      -- another save: rebuilt
      H.df.global.world.cur_savegame.save_dir = 'region1'
      return a, b, c
    """, env, H)
    assert tuple(r) == (1, 1, 2), r


@test("L2 Low bridge 760-762: an action that clears constructions makes the next survey skip its own cache")
def _():
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local got = {}
      H.scripts['ai-constructions'] = {survey = function(fresh) table.insert(got, fresh == true); return {} end}
      env.CONSTRUCTIONS_FRESH = true
      env.SECTIONS.constructions()
      env.SECTIONS.constructions()
      return got[1], got[2]
    """, env, H)
    assert tuple(r) == (True, False), r
    assert "if name == 'constructions' then CONSTRUCTIONS_FRESH = true end" in src("ai-bridge")


DWARVES = r"""
local env, H = ...
local function unit(job, squad, acts)
  return {job = {current_job = job}, military = {squad_id = squad}, health = nil,
          social_activities = acts, status = {current_soul = {skills = {}}}}
end
local list = {unit(nil, -1, {}), unit(nil, -1, {1}), unit(nil, -1, {1, 2}), unit({}, -1, {}), unit(nil, 3, {})}
local d = H.dfhack
local saved = d.units
d.units = {getCitizens = function() return list end, isChild = function() return false end,
           isBaby = function() return false end, getStressCategory = function() return 3 end,
           getProfessionName = function() return 'Miner' end}
d.df2utf = function(s) return s end
local s = env.get_dwarves(false)
d.units = saved
return s.idle_adults, s.in_activity, s.idle_free, s.in_squads
"""


@test("industry change 1: get_dwarves splits idle_adults into in_activity and idle_free")
def _():
    env = H.module()
    r = LUA.execute(DWARVES, env, H)
    assert tuple(r) == (3, 2, 1, 1), r


@test("moods.md 1: thread and cloth in a hospital's chests are counted apart, not in the kinds")
def _():
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local d = H.dfhack
      local chest_h, chest_f = {id = 50}, {id = 51}
      local hosp = {getType = function() return 1 end, getContents = function() return {building_ids = {9}} end}
      H.df.abstract_building_type = {[1] = 'HOSPITAL'}
      d.world.getCurrentSite = function() return {buildings = {hosp}} end
      d.items = {getContainer = function(it) return it.box end,
                 getHolderBuilding = function(c) return c == chest_h and {centerx = 1, centery = 1, z = 1}
                                                    or {centerx = 2, centery = 2, z = 1} end}
      d.buildings = {findCivzonesAt = function(p) return p.x == 1 and {{id = 9}} or {{id = 4}} end}
      env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
      local test = env.hospital_store_test()
      return test({box = chest_h}), test({box = chest_f}), test({}), test({box = chest_h})
    """, env, H)
    assert tuple(r) == (True, False, False, True), r
    s = src("ai-bridge-report")
    body = s[s.index("function get_supplies()"):s.index("-- The dead: ghosts of the fort's own")]
    assert body.count("if in_hospital(it) then") == 2 and "out.hospital = {thread = 0, cloth = 0}" in body


ORDERS = r"""
local env, H = ...
local df = H.df
df.job_type = {ConstructSlab = 1, EngraveSlab = 2, [1] = 'ConstructSlab', [2] = 'EngraveSlab'}
df.workshop_type = {[0] = 'Masons', Masons = 0}
H.dfhack.job = {createLinked = function() return {} end, assignToWorkshop = function() end,
                getWorker = function() return nil end}
local jobs = {}
local function job(oid) table.insert(jobs, {job_type = 2, order_id = oid}) end
job(-1); job(-1)           -- the player's own, added at the bench
job(11)                    -- the AI's order
for i = 1, 7 do job(20 + i) end   -- orders that are not the AI's
df.global.world.buildings = {other = {WORKSHOP_ANY = {{type = 0, jobs = jobs,
    getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}}}}
df.global.world.manager_orders = {all = {}}
H.persist['ai-overseer/orders'] = {ids = {['11'] = true}}
env.AI_ORDERS_KEY = 'ai-overseer/orders'
local r = env.act_bench_jobs({kind = 'slab', count = 5, make_room = true, dry_run = true})
return r.ok, r.lifted
"""


@test("L3 Med orders 754-757: bench_jobs' make_room never lifts a job that belongs to no order")
def _():
    env = H.module()
    ok, lifted = LUA.execute(ORDERS, env, H)
    # 5 wanted, 0 slots free: 5 to lift, from the 7 foreign-order jobs only
    assert ok and lifted == 5, (ok, lifted)
    ok, lifted = LUA.execute(ORDERS.replace("for i = 1, 7 do", "for i = 1, 2 do").replace(
        "job(-1); job(-1)", "for _ = 1, 7 do job(-1) end"), env, H)
    assert lifted == 2, lifted                # 7 player jobs + 1 AI + 2 foreign: only the 2


INSTR = r"""
local env, H = ...
local df = H.df
local function o(id, left) return {id = id, reaction_name = 'MAKE_ENT89 INK1', amount_left = left, amount_total = 3} end
df.global.world.manager_orders = {all = {o(1, 3), o(2, 3), o(3, 3), o(4, 3)}}
H.persist['ai-overseer/orders'] = {ids = {['2'] = true, ['3'] = true}}
env.AI_ORDERS_KEY = 'ai-overseer/orders'
local cancelled = {}
env.act_cancel_work_order = function(a) table.insert(cancelled, a.order_id); return {ok = true} end
local r = env.act_trim_instrument_orders({keep = 1})
local ids = H.persist['ai-overseer/orders'].ids
return r.found, table.concat(cancelled, ','), ids['1'] == nil and ids['4'] == nil
"""


@test("L3 Med actions 1894-1927: trim_instrument_orders touches only the AI's own instrument orders")
def _():
    env = H.module()
    found, cancelled, untouched = LUA.execute(INSTR, env, H)
    assert found == 2 and cancelled == "3" and untouched, (found, cancelled, untouched)


@test("L3 Low orders 826-828: a cancelled order's leftover jobs only, not every orphan in the fort")
def _():
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local df = H.df
      df.global.world.manager_orders = {all = {}}
      local removed = {}
      local function link(items)
        local head = {next = nil}; local cur = head
        for _, j in ipairs(items) do cur.next = {item = j}; cur = cur.next end
        return head
      end
      df.global.world.jobs = {list = link({{order_id = 5, job_type = 1}, {order_id = 6, job_type = 1}})}
      H.dfhack.job = {getWorker = function() return nil end, getHolder = function() return {} end,
                      removeJob = function(j) table.insert(removed, j.order_id) end}
      df.job_type = {[1] = 'X'}
      local n = env.orphan_jobs(false, 30, 5)
      return n, table.concat(removed, ',')
    """, env, H)
    assert tuple(r) == (1, "5"), r
    assert "orphan_jobs(false, 30, id)" in src("ai-bridge-orders")


PRUNE = r"""
local env, H, unburied = ...
H.cmds = {}
H.dfhack.findScript = function() return '/df/hack/scripts/deteriorate.lua' end
H.dfhack.run_command_silent = function(...) table.insert(H.cmds, table.concat({...}, ' ')); return 'Deteriorated 3 items', 0 end
env.unburied_citizens = function() return unburied end   -- (0.105.33 fix: test_r33_fix_people)
local r = env.act_prune_remains({extra = {'clothes'}})
local d = env.act_prune_remains({dry_run = true})
return r.ok, table.concat(H.cmds, '|'), r.corpses, d.corpses_now
"""


@test("L3 Med actions 1968-1990: prune_remains never puts corpses on deteriorate's timer; one pass only with no unburied")
def _():
    env = H.module()
    ok, cmds, corpses, dry = LUA.execute(PRUNE, env, H, 0)
    assert ok and cmds == ("deteriorate disable corpses|deteriorate enable unusable-parts,clothes|"
                           "enable deteriorate|deteriorate now corpses"), cmds
    assert "Deteriorated" in corpses and dry is True, (corpses, dry)
    ok, cmds, corpses, dry = LUA.execute(PRUNE, env, H, 2)
    assert ok and "now corpses" not in cmds and "enable corpses" not in cmds and "2 citizen" in corpses, cmds
    assert dry is False


RESTRICT = r"""
local env, H, n, r = ...
local tiles = 0
H.dfhack.maps = {getTileSize = function() return 200, 200, 200 end,
  getTileFlags = function(p) tiles = tiles + 1; return {flow_size = (p.x == 98 and p.y == 88) and 7 or 0,
                                                         liquid_type = false, traffic = 0} end,
  getTileType = function() return 1 end}
H.df.tiletype = {attrs = {[1] = {material = 0}}}
H.df.tiletype_material = {FROZEN_LIQUID = 9}
H.df.tile_traffic = {Normal = 0, Restricted = 2}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local zs = {}
for i = 1, n do zs[i] = 160 + i end
local res = env.act_restrict_water({levels = zs, x = 98, y = 88, radius = r, dry_run = true})
return res.ok, res.marked, res.error
"""


@test("L3 Med actions 2220: restrict_water takes the 9 levels the brain sends; 10 refused")
def _():
    env = H.module()
    ok, marked, err = LUA.execute(RESTRICT, env, H, 9, 5)
    assert ok and marked == 9, (ok, marked, err)
    ok, marked, err = LUA.execute(RESTRICT, env, H, 10, 5)
    assert not ok and "1-9" in err, err
    sys.path.insert(0, str(ROOT / "brain"))
    import planner_wells as pw
    s = {"water": {"middle": {"x": 98, "y": 88, "z_high": 170},
                   "bodies": [{"z1": 168, "z2": 170}, {"z1": 160, "z2": 166}, {"z1": 175, "z2": 178}]}}
    props = []
    pw._water_traffic_rule(s, props)
    assert props and len(props[0].action["levels"]) <= 9, props


@test("L3 Low actions 2272-2318: free_slabs counts a shut-in slab in a dry run too")
def _():
    s = src("ai-bridge-actions")
    body = s[s.index("function act_free_slabs(a)"):]
    assert re.search(r"if a\.dry_run then\s+moved = moved \+ 1", body[:3000]), "dry-run count missing"


@test("L3 Low actions 144-149: parse_style keeps the customs ai-layouts knows (a new one too)")
def _():
    a = src("ai-bridge-actions")
    body = a[a.index("local function parse_style(st)"):]
    body = body[:body.index("\nend\n") + 5].replace("local function parse_style", "function parse_style")
    run = LUA.eval("""function(body, known)
      local env = setmetatable({}, {__index = _G})
      env.int_in = function(v) return v end
      env.reqscript = function(name)
        if known then return {LAYOUT_CUSTOMS = known} end
        error('no ' .. name)
      end
      assert(load(body, 'parse_style', 't', env))()
      local st = env.parse_style({customs = {'cloister', 'garden_walk', 'bogus'}})
      return table.concat(st.customs or {}, ',')
    end""")
    known = LUA.table_from({"cloister": True, "armoury": True, "ore_piles": True, "garden_walk": True})
    assert run(body, known) == "cloister,garden_walk", run(body, known)
    assert run(body, None) == "cloister", run(body, None)       # no ai-layouts: the three old names


@test("L3 Low actions 1375-1445 / orders 628-646: the kitchen bans and the bench jobs share one helper")
def _():
    a, o = src("ai-bridge-actions"), src("ai-bridge-orders")
    assert a.count("dfhack.kitchen.addExclusion") == 1 and "local function kitchen_ban(" in a
    assert o.count("dfhack.job.createLinked()") == 1 and "local function bench_job(" in o
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local added = {}
      H.dfhack.kitchen = {addExclusion = function(_, t, s, mt, mi) table.insert(added, mt); return true end,
                          removeExclusion = function() return true end}
      H.df.item_type = {GLOB = 7}
      H.df.global.world.items = {other = {GLOB = {}}}
      local none = env.act_kitchen_fat({ban = true})
      env.brewable_cook_keys = function() return {{t = 1, s = -1, mt = 3, mi = 4}} end
      local b = env.act_kitchen_brewables({ban = true})
      local l = env.act_kitchen_brewables({ban = false})
      return none.ok, b.banned, b.held, l.lifted
    """, env, H)
    assert tuple(r) == (False, 1, 1, 1), r


@test("L2 Low digest: a failed needs/deep/water/... section is listed in _errors, its value kept")
def _():
    s = normalize({"needs": {"error": "boom"}, "deep": {"error": "deep gone"}, "civ_alert_ready": {"error": "x"},
                   "disposal": {"error": "d"}, "civ_alert": {"error": "alerts gone"},
                   "map": {"error": "no size", "layers": [], "dwarves": {}}})
    e = s["_errors"]
    for k in ("needs", "deep", "civ_alert_ready", "disposal", "civ_alert", "map.size"):
        assert k in e, (k, e)
    assert s["needs"] == {"error": "boom"} and s["disposal"] == {"error": "d"}    # the rules' own guards still see it
    assert s["civ_alert"] is False                  # a failed read is not "the alarm is on"
    assert s["map"]["layers"] == []
    ok = normalize({"civ_alert": True, "needs": {"social": {}}})
    assert ok["civ_alert"] is True and "needs" not in ok["_errors"] and "civ_alert" not in ok["_errors"]


if __name__ == "__main__":
    for name, ok, why in RESULTS:
        print(f"[{'ok' if ok else 'FAIL'}] {name}" + ("" if ok else f"\n       {why}"))
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"{passed} passed, {len(RESULTS) - passed} failed")
    sys.exit(0 if passed == len(RESULTS) else 1)
