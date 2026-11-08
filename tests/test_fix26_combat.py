"""(0.105.26, fix round: combat) The titan refight loop, the shelter's drink
and well, lever gates, the deep depot hall, the shelter timer mid-siege and
the soldiers' waterskins.

    python tests/test_fix26_combat.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

from planner import Memory, PLANNER_CONFIG, plan, TICKS_PER_DAY  # noqa: E402
from planner_core import abs_tick  # noqa: E402
from planner_military import threat_power  # noqa: E402

try:
    from lupa import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def by_rule(props, rule):
    return [p for p in props if p.rule == rule]


def titan(power=244, goblin=False, soldiers=20):
    """A's numbers (4-5 Nov): a breathing Hill Titan, squads worth 488."""
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    th = [{"id": 900, "name": "Hill Titan", "great_danger": True, "can_reach_dwarves": True,
           "kinds": ["Titan"], "size": 2_500_000, "abilities": 1}]
    if goblin:
        th.append({"id": 901, "name": "Goblin", "great_danger": False, "can_reach_dwarves": True, "invader": True})
    s["others_on_map"]["threats"] = th
    s["others_on_map"]["threats_that_can_reach_dwarves"] = len(th)
    for q in s["military"]["squads"]:
        q["power"] = {"power": power, "armored": 10, "skill": 10}
    s["military"]["soldiers"] = soldiers
    s["civ_alert_ready"] = True
    return s


def went_and_lost(goblin=False):
    """The squads went at the titan; 8 of 20 lost, still on it."""
    m = Memory()
    plan(titan(goblin=goblin), m)
    assert m.fight and m.fight["soldiers"] == 20, m.fight
    s = titan(goblin=goblin, soldiers=12)
    for q in s["military"]["squads"]:
        q.update(ai_orders=1, orders=1, kill_ids=[900] + ([901] if goblin else []))
    s["civ_alert"] = True
    return m, s


# --- 1. the titan refight loop ------------------------------------------------

@test("1. call-off: the squads on the titan come back even with a goblin in reach")
def _():
    m, s = went_and_lost(goblin=True)
    p, notes = plan(s, m)
    rc = {x.action["squad_id"] for x in by_rule(p, "squad_recall")}
    assert rc == {q["id"] for q in s["military"]["squads"]}, (rc, [(x.rule, x.action) for x in p])
    assert not [x for x in by_rule(p, "squad_attack") if 900 in x.action.get("kill", [])]
    assert "900" in m.called_off, m.called_off


@test("1. call-off: refilled after the freeze, the squads are never sent at the titan again while it's here")
def _():
    m, s = went_and_lost()
    plan(s, m)
    m.fight["tick"] -= 8 * TICKS_PER_DAY            # a week on: refills allowed again
    p, notes = plan(titan(soldiers=19), m)
    assert not [x for x in by_rule(p, "squad_attack") if 900 in x.action.get("kill", [])], \
        [(x.rule, x.action) for x in p]
    assert any("called off" in n for n in notes), notes
    # a goblin about: the squads go at the goblin only
    s = titan(goblin=True, soldiers=19)
    p, notes = plan(s, m)
    kills = [x.action.get("kill") for x in by_rule(p, "squad_attack")]
    assert kills and all(k == [901] for k in kills), kills


@test("1. call-off: the flag goes when the titan leaves the map (or dies)")
def _():
    m, s = went_and_lost()
    plan(s, m)
    assert "900" in m.called_off
    gone = titan(soldiers=12)
    gone["others_on_map"]["threats"] = []
    gone["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    plan(gone, m)
    assert "900" not in m.called_off, m.called_off


@test("1. call-off: the learned factor makes even the refilled squads hide (not x1.5)")
def _():
    m, s = went_and_lost()
    plan(s, m)
    ff = m.fight_factor["Titan"]
    t = titan()["others_on_map"]["threats"][0]
    assert 488 < PLANNER_CONFIG["fight_ratio"] * threat_power(t) * ff, ff
    # a new titan of the same kind (another id, the flag doesn't cover it): hide
    m.called_off = {}
    m.fight = {}
    s2 = titan()
    s2["others_on_map"]["threats"][0]["id"] = 950
    p, notes = plan(s2, m)
    assert not by_rule(p, "squad_attack"), notes
    # a later easy fight (x0.9) doesn't cut the lesson back to the old cap of 4
    from planner_military import _fight_outcome
    m.fight = {"tick": abs_tick(s2), "keys": ["Titan"], "soldiers": 20}
    quiet = titan()
    quiet["others_on_map"]["threats"] = []
    _fight_outcome(quiet, m, PLANNER_CONFIG)
    assert m.fight_factor["Titan"] > 4.0, m.fight_factor


# --- 5. the shelter timer mid-siege -------------------------------------------

def sheltered(dist):
    s = titan(power=10)
    s["others_on_map"]["threats"][0]["distance_to_nearest_dwarf"] = dist
    for q in s["military"]["squads"]:
        q.update(sheltering=True, ai_orders=1, orders=1)
    s["civ_alert"] = True
    return s


@test("5. the 3-day shelter limit waits while a great danger is within 20 tiles; counts when it's far")
def _():
    s = sheltered(8)
    m = Memory()
    t0 = abs_tick(s)
    m.shelter_since = {"11": t0 - 4 * TICKS_PER_DAY, "12": t0}
    p, _ = plan(copy.deepcopy(s), m)
    assert not by_rule(p, "squad_recall"), [(x.rule, x.action) for x in p]
    s = sheltered(60)
    p, _ = plan(copy.deepcopy(s), m)
    assert [x.action["squad_id"] for x in by_rule(p, "squad_recall")] == [11]


@test("5. a siege close by holds the timer too; the parched still go out at once")
def _():
    s = sheltered(60)
    s["others_on_map"]["threats"].append({"id": 905, "name": "Goblin", "invader": True, "great_danger": False,
                                          "can_reach_dwarves": False, "distance_to_nearest_dwarf": 15})
    s["military"]["squads"][1]["parched"] = 2
    m = Memory()
    t0 = abs_tick(s)
    m.shelter_since = {"11": t0 - 4 * TICKS_PER_DAY, "12": t0}
    p, _ = plan(copy.deepcopy(s), m)
    assert [x.action["squad_id"] for x in by_rule(p, "squad_recall")] == [12], [(x.rule, x.action) for x in p]


# --- 3. rebuild the shelter when a gate is lost (planner side) ---------------

@test("3. the alarm on and a gate lost (military.shelter_stale): the shelter is made again")
def _():
    s = titan(power=10)
    s["civ_alert"] = True
    p, _ = plan(copy.deepcopy(s), Memory())
    assert not by_rule(p, "shelter_refresh")
    s["military"]["shelter_stale"] = 1
    p, _ = plan(copy.deepcopy(s), Memory())
    assert [x.action for x in by_rule(p, "shelter_refresh")] == [{"type": "refresh_shelter"}]
    from overseer import SHORT_WORDS
    assert "refresh_shelter" in SHORT_WORDS
    src = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "refresh_shelter = act_refresh_shelter" in src and "'refresh_shelter'" in src


# --- 6. water for squads ------------------------------------------------------

def gear_fort(**g):
    s = titan(power=10)
    s["others_on_map"]["threats"] = []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["military"].setdefault("gear", {}).update(g)
    return s


@test("6. soldiers with no waterskin or flask: leather waterskins ordered, sized to them")
def _():
    s = gear_fort(flask_places=12, flasks_assigned=2, flasks_free=3)
    s["stocks"]["leather"] = 40
    s["buildings"].setdefault("workshops", {})["Leatherworks"] = 1
    p, _ = plan(copy.deepcopy(s), Memory())
    fo = by_rule(p, "flasks_order")
    assert fo and fo[0].action["recipe"] == "leather_waterskin", [(x.rule, x.action) for x in p]
    assert fo[0].action["amount"] == min(7, PLANNER_CONFIG["max_quiver_order"]), fo[0].action
    s = gear_fort(flask_places=12, flasks_assigned=9, flasks_free=3)
    s["stocks"]["leather"] = 40
    s["buildings"].setdefault("workshops", {})["Leatherworks"] = 1
    assert not by_rule(plan(copy.deepcopy(s), Memory())[0], "flasks_order")


@test("6. the recipes are real: MakeFlask (df-structures CONSTRUCT_FLASK) of leather, and of green glass")
def _():
    src = (ROOT / "lua" / "ai-bridge-orders.lua").read_text(encoding="utf-8")
    assert "leather_waterskin = {job = 'MakeFlask', material_category = {'leather'}}" in src
    assert "glass_vial = {job = 'MakeFlask', material = 'GLASS_GREEN'}" in src
    gsrc = (ROOT / "lua" / "ai-military-gear.lua").read_text(encoding="utf-8")
    assert "function flask_report()" in gsrc and "pos.equipment.flask" in gsrc


# --- 2, 3, 4. the shelter in Lua -----------------------------------------------

# A fort two blocks wide (x96-127, y144-159) on levels 160-180; the entrance
# at x108 y149 z170 (as in test_society); citizens on z170.
FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end})
end
local set = {}
local blocks = {}
for z = 160, 180 do
    for _, bx in ipairs({96, 112}) do
        local des, tt = {}, {}
        for x = 0, 15 do des[x], tt[x] = {}, {}
            for y = 0, 15 do des[x][y] = {hidden = false, outside = false, flow_size = 0}; tt[x][y] = 1 end
        end
        table.insert(blocks, {map_pos = {x = bx, y = 144, z = z}, designation = des, tiletype = tt})
    end
end
local shelter = {id = 4, name = 'AI shelter'}
local hatch = {id = 77, door_flags = {forbidden = false, closed = true}, x1 = 108, x2 = 108, y1 = 149, y2 = 149, z = 170,
               getType = function() return 'hatch' end}
local buildings = {[77] = hatch}
local gates = {scanned = true,
               entrances = {{id = 1, kind = 'surface', x = 108, y = 149, z = 170, sealed = true,
                             equipment = {{id = 77, kind = 'hatch', lever_driven = true, drive_lever = 5}}}}}
local live = {{id = 77, kind = 'hatch', closed = true, lever_driven = true}}
local deep = nil
local drinks = {}
local wells = {}
local units = {}
local site = {}
local cits = {{pos = {z = 170}}, {pos = {z = 170}}}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.df = {global = {world = {map = {map_blocks = blocks},
                             items = {other = {DRINK = drinks}},
                             units = {active = units},
                             buildings = {other = {STOCKPILE = vec({{z = 162}}), WELL = wells}}},
                    plotinfo = {burrows = {list = vec({shelter}), next_id = 5},
                                alerts = {civ_alert_idx = 1, list = vec({{}, {burrows = vec({4})}}), next_id = 3}}},
          tiletype = {attrs = {[1] = {shape = 1}}},
          tiletype_shape = {[1] = 'FLOOR'},
          building_type = {Hatch = 'hatch'},
          creature_raw = {find = function() return {caste = {[0] = {misc = {buildingdestroyer = 2}}}} end},
          building = {find = function(id) return buildings[id] end}}
env.require = function(name) if name == 'utils' then return {insert_sorted = function() end} end return require(name) end
env.reqscript = function(name)
    if name == 'ai-gates' then return {GATES = gates, gate_buildings = function() return live end} end
    if name == 'ai-builder' then return {deep_depot_data = function() return deep end} end
    if name == 'ai-util' then return env.U end
    error('no ' .. name)
end
env.dfhack = {units = {getCitizens = function() return cits end,
                       isActive = function() return true end, isDead = function() return false end,
                       isCitizen = function() return false end, isDanger = function() return true end},
              items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end},
              persistent = {getSiteData = function(k, d) return site[k] or d end,
                            saveSiteData = function(k, v) site[k] = v end},
              maps = {getTileType = function() return nil end,
                      getWalkableGroup = function(p) if p.x >= 96 and p.x <= 127 and p.y >= 144 and p.y <= 159 then return 1 end return 0 end},
              burrows = {setAssignedBlockTile = function(b, block, x, y, on)
                             set[(block.map_pos.x + x) .. ',' .. (block.map_pos.y + y) .. ',' .. block.map_pos.z] = on end,
                         clearTiles = function(b) for k in pairs(set) do set[k] = nil end end}}
assert(load(src, 'ai-society', 't', env))()
return env, set, {gates = gates, hatch = hatch, live = live, buildings = buildings, drinks = drinks, wells = wells,
                  units = units, site = site, setdeep = function(d) deep = d end}
"""


def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, got, w = lua.execute(FAKE, module_src("ai-society.lua"))
    return lua, env, got, w


ALL = 13 * 512          # levels 160-172 (citizens on 170, plus 2; the pile on 162, less 2), two blocks each


@test("3. a lever-driven hatch shut by its link (closed, not locked) reads as shut: no tiles left out")
def _():
    if LuaRuntime is None:
        return
    lua, env, got, w = world()
    r = env.refresh_shelter()
    assert r.open_entrances == 0 and r.excluded_tiles == 0 and r.tiles == ALL, dict(r)
    lua.execute("local w = ...; w.live[1].closed = false; w.hatch.door_flags.closed = false", w)
    r = env.refresh_shelter()
    assert r.open_entrances == 1 and r.excluded_tiles > 0, dict(r)


@test("3. a building destroyer that can walk to the shut gate makes it open; the shelter is said stale")
def _():
    if LuaRuntime is None:
        return
    lua, env, got, w = world()
    r = env.refresh_shelter()
    assert r.open_entrances == 0, dict(r)
    assert env.shelter_stale() == 0
    lua.execute("""local w = ...
        w.units[1] = {id = 1, race = 1, caste = 0, pos = {x = 100, y = 150, z = 170}, flags1 = {caged = false, chained = false}}""", w)
    assert env.shelter_stale() == 1
    r = env.refresh_shelter()
    assert r.open_entrances == 1 and r.excluded_tiles > 0, dict(r)
    assert env.shelter_stale() == 0
    # a gate gone from gate_buildings' list (broken): open
    lua, env, got, w = world()
    env.refresh_shelter()
    lua.execute("local w = ...; w.live[1] = nil", w)
    assert env.shelter_stale() == 1


@test("4. the deep depot hall and its road are never shelter")
def _():
    if LuaRuntime is None:
        return
    lua, env, got, w = world()
    lua.execute("""local w = ...
        w.setdeep({stage = 'placed', tiles = {{x = 126, y = 158, z = 165, r = 'd'}},
                   hall = {x1 = 100, y1 = 146, x2 = 108, y2 = 154, z = 162}})""", w)
    r = env.refresh_shelter()
    assert r.deep_depot_tiles == 11 * 11 + 1, dict(r)
    assert not got["104,150,162"] and not got["99,145,162"] and not got["126,158,165"]
    assert got["104,150,163"] and got["110,150,162"]
    assert r.tiles == ALL - r.deep_depot_tiles, dict(r)


@test("2. the shelter's drink and well are counted; with neither away from the entrance, they're taken back")
def _():
    if LuaRuntime is None:
        return
    lua, env, got, w = world()
    lua.execute("""local w = ...
        w.drinks[1] = {flags = {}, pos = {x = 120, y = 150, z = 166}}
        w.wells[1] = {centerx = 125, centery = 150, z = 166,
                      getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}""", w)
    r = env.refresh_shelter()
    assert r.drink_tiles == 1 and r.well_tiles == 1 and not r.no_water, dict(r)
    # the entrance open now: the drink and the well are in its margin (12 tiles, 2 levels)
    lua.execute("""local w = ...
        w.live[1].closed = false; w.hatch.door_flags.closed = false
        w.drinks[1].pos = {x = 112, y = 150, z = 170}
        w.wells[1].centerx, w.wells[1].z = 110, 169""", w)
    r = env.refresh_shelter()
    assert r.open_entrances == 1 and r.drink_tiles == 1 and r.well_tiles == 1, dict(r)
    assert r.drink_back == 2 and got["112,150,170"] and got["110,150,169"], dict(r)
    # neither on the map at all: said so
    lua.execute("local w = ...; w.drinks[1] = nil; w.wells[1] = nil", w)
    r = env.refresh_shelter()
    assert r.drink_tiles == 0 and r.well_tiles == 0 and r.no_water, dict(r)


if __name__ == "__main__":
    finish()
