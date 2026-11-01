"""Tests for lua/ai-society.lua's recreation burrow (0.104.78), in a real Lua
engine with a stub DFHack (pip install lupa).

    python tests/test_society.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


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


FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end}})
end
local persist, assigned, tiles = {}, {}, {}
-- citizens: id -> {cat, squad, adult, sick}
local units = {}
local function unit(id, cat, opts)
    opts = opts or {}
    local u = {id = id, cat = cat, adult = opts.adult ~= false, military = {squad_id = opts.squad or -1},
               health = {flags = {needs_healthcare = opts.sick or false}}}
    units[id] = u
    return u
end
local cits = {unit(1, 0), unit(2, 1), unit(3, 1, {squad = 7}), unit(4, 0, {adult = false}), unit(5, 0, {sick = true}),
              unit(6, 4), unit(7, 1)}
local burrows = vec({})
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.require = function(name) if name == 'utils' then return {insert_sorted = function() end} end return require(name) end
local zone = {id = 50, x1 = 0, y1 = 0, x2 = 2, y2 = 1, z = 10, type = 1, getType = function() return 'Civzone' end}
env.df = {global = {cur_year = 76, cur_year_tick = 1000, plotinfo = {burrows = {list = burrows, next_id = 1}},
                    world = {buildings = {all = vec({zone})}}},
          burrow = {new = function() return {} end},
          building_type = {Civzone = 'Civzone', Stockpile = 'Stockpile'},
          civzone_type = {[1] = 'MeetingHall'},
          unit = {find = function(id) return units[id] end}}
env.dfhack = {
    persistent = {getSiteData = function(k, d) return persist[k] or d end, saveSiteData = function(k, v) persist[k] = v end},
    world = {getCurrentSite = function() return {buildings = vec({})} end},
    buildings = {containsTile = function() return true end},
    burrows = {clearTiles = function() tiles = {} end,
               setAssignedTile = function(b, p, on) tiles[p.x .. ',' .. p.y] = on; return true end,
               setAssignedUnit = function(b, u, on) assigned[u.id] = on or nil end},
    units = {getCitizens = function() return cits end, isAdult = function(u) return u.adult end,
             isCitizen = function(u) return true end, getStressCategory = function(u) return u.cat end,
             getReadableName = function(u) return 'dwarf ' .. u.id end}}
assert(load(src, 'ai-society', 't', env))()
return env, units, assigned, function() local n = 0; for _ in pairs(tiles) do n = n + 1 end; return n end, env.df.global
"""


def fresh():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute(FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))


@test("recreation (0.104.78): the burrow made over the halls; the unhappiest civilians moved in, never soldiers, children or patients")
def _():
    env, units, assigned, ntiles, g = fresh()
    r = env.recreation_tick(2, 28, False)
    assert r.ok and r.tiles == 6 and ntiles() == 6, dict(r)                 # the 3x2 meeting hall
    assert r.members == 2 and assigned[1] and assigned[2] and not assigned[7], dict(assigned)  # the worst first, at most 2
    assert not assigned[3] and not assigned[4] and not assigned[5] and not assigned[6]
    assert env.recreation_status().members == 2


@test("trinkets (0.104.141): the census sorts trinkets by where they are; free bones counted, never forbidden or unbutchered")
def _():
    env, units, assigned, ntiles, g = fresh()
    snippet = """
      local env = ...
      local function fl(t) t = t or {}; return t end
      local function item(flags) return {flags = fl(flags)} end
      local depot = {getType = function() return 'TradeDepot' end}
      env.df.building_type.TradeDepot = 'TradeDepot'
      env.dfhack.items = {getOwner = function(i) return i.owner end, getContainer = function() return nil end,
                          getHolderBuilding = function(i) return i.holder end}
      local d = item({in_building = true}); d.holder = depot
      local rings = {[0] = item({on_ground = true}), [1] = item({owned = true}), [2] = item({in_job = true}),
                     [3] = d, [4] = item({forbid = true, on_ground = true}), [5] = item({in_inventory = true})}
      local function b(cf, f) local x = item(f); x.corpse_flags = cf; return x end
      local bones = {[0] = b({bone = true}), [1] = b({bone = true}, {forbid = true}),
                     [2] = b({bone = true, unbutchered = true}), [3] = b({}), [4] = b({bone = true})}
      env.df.global.world.items = {other = {RING = rings, CORPSEPIECE = bones}}
    """
    env["load"](snippet, "t", "t", env)(env)
    c = env.trinket_census()
    assert (c.free, c.owned, c.in_job, c.trade, c.forbidden, c.carried) == (1, 1, 1, 1, 1, 1), dict(c)
    assert env.free_bones(100) == 2 and env.free_bones(1) == 1


@test("0.104.157: the stress census sums DF's thoughts by stress (recent only); the clothes census counts wear and what's missing")
def _():
    env, units, assigned, ntiles, g = fresh()
    snippet = """
      local env = ...
      env.df.global.cur_year, env.df.global.cur_year_tick = 92, 200000
      env.df.unit_thought_type = {[1] = 'SawDeadBody', [2] = 'Ghost', [3] = 'Talked', [4] = 'GoodMeal'}
      env.df.emotion_type = {[10] = 'HORROR', [11] = 'TERROR', [12] = 'JOY',
                             attrs = {[10] = {divider = 1}, [11] = {divider = 2}, [12] = {divider = -1}}}
      local function em(th, ty, str, tick) return {thought = th, type = ty, strength = str, year = 92, year_tick = tick or 199000} end
      local function soul(list) return {status = {current_soul = {personality = {emotions = list}}}} end
      local a = soul({em(1, 10, 50), em(1, 10, 30), em(2, 11, 40), em(4, 12, 20)})
      local b = soul({em(1, 10, 10), em(3, 12, 25), em(2, 11, 100, 10)})     -- the ghost long ago: left out
      STRESS_UNITS = {a, b}
      local function inv(t, wear) return {mode = 2, item = {wear = wear, getType = function() return t end}} end
      env.df.item_type = {[1] = 'SHOES', [2] = 'PANTS', [3] = 'ARMOR', [4] = 'HELM'}
      env.df.unit_inventory_item = {T_mode = {Worn = 2}}
      env.dfhack.units.isBaby = function(u) return u.baby == true end
      env.df.global.world.items = {other = {SHOES = {[0] = {flags = {}}, [1] = {flags = {owned = true}},
                                                     [2] = {flags = {in_inventory = true}}},
                                            GOBLET = {[0] = {flags = {in_building = true}}}}}
      CLOTH_UNITS = {{inventory = {inv(1, 0), inv(2, 3), inv(3, 1)}},
                     {inventory = {inv(3, 2), {mode = 1, item = {wear = 3, getType = function() return 1 end}}}},
                     {baby = true, inventory = {}}}
    """
    env["load"](snippet, "t", "t", env)(env)
    c = env.stress_census(env.STRESS_UNITS)
    worst = [(x.thought, x.citizens, x.stress, x.emotion) for x in c.causes.values()]
    assert worst == [("SawDeadBody", 2, 90, "HORROR"), ("Ghost", 1, 20, "TERROR")], worst
    eased = [(x.thought, x.stress) for x in c.eased.values()]
    assert eased == [("Talked", -25), ("GoodMeal", -20)], eased
    assert c.citizens == 2 and c.read == 2
    k = env.clothing_census(env.CLOTH_UNITS)
    assert k.citizens == 2 and k.tattered_wearers == 1, dict(k)
    assert (k.worn.new, k.worn.worn, k.worn.threadbare, k.worn.tattered) == (1, 1, 1, 1), dict(k.worn)
    assert (k.without.shoes, k.without.legs, k.without.body) == (1, 1, 0), dict(k.without)
    assert k.free_shoes == 1 and k.free_cups == 0, (k.free_shoes, k.free_cups)


@test("recreation (0.104.127): never the hospital's zone (a meeting hall that is a hospital location), nor a Hospital zone")
def _():
    env, units, assigned, ntiles, g = fresh()
    env_ = env
    run = env_["load"]                                              # the Lua global load, to run a snippet in env
    snippet = """
      local env = ...
      local hall = {id = 60, x1 = 10, y1 = 0, x2 = 12, y2 = 1, z = 10, type = 1, getType = function() return 'Civzone' end}
      local ward = {id = 61, x1 = 20, y1 = 0, x2 = 21, y2 = 0, z = 10, type = 2, getType = function() return 'Civzone' end}
      local all = env.df.global.world.buildings.all
      all[1] = hall; all[2] = ward
      setmetatable(all, nil)
      env.df.civzone_type[2] = 'Hospital'
      env.df.abstract_building_type = {[7] = 'HOSPITAL'}
      local hosp = {getType = function() return 7 end, getContents = function() return {building_ids = {[0] = 60}} end}
      env.dfhack.world.getCurrentSite = function() return {buildings = {[0] = hosp}} end
    """
    f = run(snippet, "t", "t", env_)
    f(env_)
    r = env.recreation_tick(2, 28, False)
    assert r.ok and r.tiles == 6, dict(r)                           # only the first meeting hall, not the ward or the hospital hall


@test("recreation (0.104.78): the recovered and those in long enough go back to work")
def _():
    env, units, assigned, ntiles, g = fresh()
    env.recreation_tick(8, 28, False)
    assert assigned[1] and assigned[2] and assigned[7]
    units[1].cat = 3                                                       # no longer unhappy
    g.cur_year_tick = 1000 + 5 * 1200
    r = env.recreation_tick(8, 28, False)
    assert r.ok and not assigned[1] and assigned[2], dict(assigned)
    g.cur_year_tick = 1000 + 30 * 1200                                     # 30 days in: out, the rest too
    r = env.recreation_tick(8, 28, False)
    assert not assigned[2] and not assigned[7], dict(assigned)
    units[2].cat, units[7].cat = 3, 3
    g.cur_year_tick = 1000 + 31 * 1200
    r = env.recreation_tick(8, 28, False)
    assert r.ok and r.unchanged, "nobody low and nobody in: nothing to do (not a refusal)"


@test("recreation (0.104.80): a few places for civilians badly wanting friends, a week each or until the need is met")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, units, assigned, ntiles, g = lua.execute(FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))
    lua.execute("""local env, units = ...
        env.df.need_type = {[9] = 'BeWithFriends'}
        local function needs(f) return {current_soul = {personality = {needs = {[0] = {id = 9, focus_level = f}}}}} end
        units[6].status = needs(-20000)        -- content, badly wants friends
        units[3].status = needs(-50000)        -- a soldier: never
        """, env, units)
    r = env.recreation_tick(2, 28, False, None, 1, 7)
    assert r.ok and r.members == 3 and assigned[6], (dict(r), dict(assigned))     # 2 unhappiest + 1 for friends
    assert not assigned[3] and env.recreation_status().for_friends == 1
    g.cur_year_tick = 1000 + 2 * 1200
    env.recreation_tick(2, 28, False, None, 1, 7)
    assert assigned[6], "kept while the need is unmet and the week not out"
    lua.execute("local units = ...; units[6].status.current_soul.personality.needs[0].focus_level = 0", units)
    g.cur_year_tick = 1000 + 3 * 1200
    r = env.recreation_tick(2, 28, False, None, 1, 7)
    assert not assigned[6] and env.recreation_status().for_friends is None, dict(r)   # met: back to work


NEST_FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end}})
end
local function zone(id, name, x1) return {id = id, name = name, x1 = x1, y1 = 0, x2 = x1 + 4, y2 = 4, z = 10, type = 'Pen',
    assigned_units = vec({}), getType = function() return 'Civzone' end} end
local pen1, pen2 = zone(60, 'AI pasture', 0), zone(61, 'cows', 20)
local all = vec({pen1, pen2})
local function hen(id, layer, opts)
    opts = opts or {}
    local u = {id = id, race = layer and 1 or 2, caste = 0, flags1 = {caged = opts.caged or false},
               female = opts.male ~= true, general_refs = vec({})}
    if opts.pen then u.ref = {building_id = opts.pen} end
    return u
end
-- 1, 2 penned in 61; 3, 4 loose; 5 caged; 6 a rooster; 7 a cow
local active = vec({hen(1, true, {pen = 61}), hen(2, true, {pen = 61}), hen(3, true), hen(4, true),
                    hen(5, true, {caged = true}), hen(6, true, {male = true}), hen(7, false)})
local placed = {}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.require = function(name) if name == 'utils' then return {insert_sorted = function(v, x) v:insert('#', x) end} end return require(name) end
env.reqscript = function(name)
    return {place_in_zone = function(id, what, dry)
                if what ~= 'nest_box' then return {ok = false, error = 'bad'} end
                if #placed >= 3 then return {ok = false, rejected = true, error = 'no free floor in zone ' .. id} end
                table.insert(placed, id)
                if not dry then all:insert('#', {x1 = 21 + #placed, y1 = 1, z = 10, getType = function() return 'NestBox' end}) end
                return {ok = true} end,
            grass_at = function() return true end}
end
local castes = {[1] = {caste = {[0] = {flags = {LAYS_EGGS = true}, misc = {grazer = 0}}}},
                [2] = {caste = {[0] = {flags = {}, misc = {grazer = 38}}}}}
env.df = {global = {cur_year = 76, cur_year_tick = 1000, world = {buildings = {all = all}, units = {active = active}}},
          building_type = {Civzone = 'Civzone', NestBox = 'NestBox'}, civzone_type = {Pen = 'Pen'},
          general_ref_type = {BUILDING_CIVZONE_ASSIGNED = 'CZA'},
          general_ref_building_civzone_assignedst = {new = function() return {} end},
          creature_raw = {find = function(r) return castes[r] end},
          unit = {find = function(id) return nil end}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
    units = {isAlive = function() return true end, isTame = function() return true end, isOwnCiv = function() return true end,
             isAdult = function() return true end, isFemale = function(u) return u.female end,
             getGeneralRef = function(u, t) return u.ref end}}
assert(load(src, 'ai-society', 't', env))()
return env, pen1, pen2, placed, active
"""


@test("nest boxes (0.104.80): the loose hens join the pasture with the most hens; a nest box a hen there, a few a call")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, pen1, pen2, placed, active = lua.execute(NEST_FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))
    n = lua.eval("function(v) return #v end")
    d = env.nest_boxes(3, True)
    assert d.ok and d.dry_run and d.zone_id == 61 and d.penned == 2 and n(pen2.assigned_units) == 0, dict(d)
    r = env.nest_boxes(3, False)
    assert r.ok and r.zone_id == 61 and r.hens == 4 and r.penned == 2, dict(r)   # not the caged hen nor the rooster
    assert n(pen2.assigned_units) == 2 and n(pen1.assigned_units) == 0
    assert r.placed == 2 and r.note and "no free floor" in r.note, dict(r)        # the stub's floor holds 3 (1 used by the dry run)


WAR_FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end}})
end
local function animal(id, race, opts)
    opts = opts or {}
    return {id = id, race = race, caste = 0, profession = opts.prof or 0, citizen = opts.citizen,
            adult = opts.adult ~= false, relationship_ids = {PetOwner = opts.pet or -1},
            status = {labors = {[7] = opts.trainer or false}}}
end
-- 10, 11 dogs; 12 a dog someone keeps as a pet; 13 a war dog already; 14 a puppy; 15 a cow; 16 a dog in training; 2 a trainer
local active = vec({animal(10, 1), animal(11, 1), animal(12, 1, {pet = 2}), animal(13, 1, {prof = 99}),
                    animal(14, 1, {adult = false}), animal(15, 2), animal(16, 1)})
local cits = vec({animal(2, 3, {citizen = true, trainer = true})})
local training = vec({{animal_id = 16, trainer_id = -1, flags = {}}})
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.require = function(name) if name == 'utils' then return {insert_sorted = function(v, x) v:insert('#', x) end} end return require(name) end
local castes = {[1] = {caste = {[0] = {flags = {TRAINABLE_WAR = true}}}}, [2] = {caste = {[0] = {flags = {}}}},
                [3] = {caste = {[0] = {flags = {}}}}}
env.df = {global = {plotinfo = {training = {training_assignments = training}}, world = {units = {active = active}}},
          creature_raw = {find = function(r) return castes[r] end},
          profession = {[99] = 'TRAINED_WAR', [0] = 'NONE'}, unit_labor = {ANIMALTRAIN = 7},
          training_assignment = {new = function() return {flags = {}} end}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
    units = {isAlive = function() return true end, isTame = function() return true end, isOwnCiv = function() return true end,
             isAdult = function(u) return u.adult end, isCitizen = function(u) return u.citizen == true end,
             getCitizens = function() return cits end, getReadableName = function(u) return 'dog ' .. u.id end}}
assert(load(src, 'ai-society', 't', env))()
return env, training
"""


@test("war animals (0.104.81): tame adult dogs put to war training, never a pet, a puppy, a war dog or one in training")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, training = lua.execute(WAR_FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))
    n = lua.eval("function(v) return #v end")
    r = env.animal_training_report()
    assert (r.war_candidates, r.war_trained, r.in_training, r.trainers) == (2, 1, 1, 1), dict(r)
    d = env.train_war(1, True)
    assert d.ok and d.dry_run and d.assigned == 1 and n(training) == 1
    w = env.train_war(5, False)
    assert w.ok and w.assigned == 2 and w.left == 0 and n(training) == 3, dict(w)
    a = training[1]
    assert a.animal_id == 10 and a.flags.any_trainer and a.flags.train_war and a.trainer_id == -1
    assert env.train_war(5, False).rejected


GATE_FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end}})
end
local burrows, tiles, defended = vec({}), {}, {}
local all = vec({})
local function dog(id, prof, opts)
    opts = opts or {}
    return {id = id, profession = prof, flags1 = {caged = false}, relationship_ids = {PetOwner = opts.pet or -1},
            ref = opts.pen and {building_id = opts.pen} or nil, general_refs = vec({})}
end
-- 1, 2, 3 war dogs; 4 a war dog someone's pet; 5 a war dog already penned; 6 an ordinary dog
local active = vec({dog(1, 9), dog(2, 9), dog(3, 9), dog(4, 9, {pet = 77}), dog(5, 9, {pen = 40}), dog(6, 0)})
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.require = function(name) if name == 'utils' then return {insert_sorted = function(v, x) v:insert('#', x) end} end return require(name) end
env.reqscript = function(name)
    if name == 'ai-military' then
        return {defend = function(sid, bid)
            if sid == 99 then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
            defended[sid] = bid; return {ok = true} end}
    end
    return {gate_dog_pen = function(p, dry)
        if not dry then all:insert('#', {id = 41, name = p.name, type = 'Pen', assigned_units = vec({}),
                                        getType = function() return 'Civzone' end}) end
        return {ok = true, x = p.x, y = p.y} end}
end
env.df = {global = {plotinfo = {burrows = {list = burrows, next_id = 3}}, world = {buildings = {all = all}, units = {active = active}}},
          burrow = {new = function() return {} end},
          building_type = {Civzone = 'Civzone'}, civzone_type = {Pen = 'Pen'}, profession = {[9] = 'TRAINED_WAR', [0] = 'NONE'},
          general_ref_type = {BUILDING_CIVZONE_ASSIGNED = 'CZA'},
          general_ref_building_civzone_assignedst = {new = function() return {} end}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
    maps = {getTileFlags = function(p) return {outside = p.z == 50 and p.y < 10, flow_size = 0} end,
            getWalkableGroup = function(p) if p.x >= 8 and p.x <= 12 and p.y >= 8 and p.y <= 12 then return 1 end return 0 end},
    burrows = {clearTiles = function() tiles = {} end,
               setAssignedTile = function(b, p, on) tiles[p.x .. ',' .. p.y .. ',' .. p.z] = on end},
    units = {isAlive = function() return true end, isOwnCiv = function() return true end,
             getGeneralRef = function(u) return u.ref or u.general_refs[0] end}}
assert(load(src, 'ai-society', 't', env))()
local function ntiles() local n = 0; for _ in pairs(tiles) do n = n + 1 end; return n end
return env, defended, ntiles, all
"""


@test("hold the gate (0.104.83): the gate guard burrow over the inside tiles near the gate; the squads told to defend it")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, defended, ntiles, all_ = lua.execute(GATE_FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))
    d = env.guard_gate(lua.table_from([11, 12]), 10, 10, 50, 3, True)
    assert d.ok and d.dry_run and ntiles() == 0
    r = env.guard_gate(lua.table_from([11, 99]), 10, 10, 50, 3, False)
    # 5x5 walkable on each of 3 levels; on z50 the rows y8-9 are open to the sky
    assert r.ok and r.tiles == 25 * 3 - 10 and ntiles() == 65, dict(r)
    assert defended[11] == r.burrow_id and defended[99] is None and len(list(r.refused.values())) == 1
    assert env.guard_gate(lua.table_from([99]), 10, 10, 50, 3, False).rejected


@test("gate dogs (0.104.83): the war dogs with no post go to a pen made inside the gate; never a pet or a penned dog")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, defended, ntiles, all_ = lua.execute(GATE_FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))
    n = lua.eval("function(v) return #v end")
    assert env.gate_dogs_report().free == 3
    r = env.gate_dogs(10, 10, 50, 2, False)
    assert r.ok and r.pen_made and r.posted == 2 and r.left == 1 and n(all_[0].assigned_units) == 2, dict(r)
    r = env.gate_dogs(10, 10, 50, 4, False)
    assert r.ok and not r.pen_made and r.posted == 1 and n(all_) == 1, dict(r)     # the same pen
    assert env.gate_dogs(10, 10, 50, 4, False).rejected


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
