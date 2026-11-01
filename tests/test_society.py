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


# (0.104.167) the hospital burrow: a hospital location over zone 70 (staffed
# by unit 9), a drink pile (80, its barrel holds drink), a food pile (81), and
# a drink pile on a level nobody can walk to from the hospital (82). Burrows
# keep their units (and each unit its burrows) as DFHack does; a well's shaft
# is the column under it, its tiles set by W.tile(z, shape, mat, flow).
HOSP_FAKE = r"""
local src = ...
local persist, tiles = {}, {}
local units = {}
local function unit(id, o)
    o = o or {}
    local flags = {needs_healthcare = o.care ~= false and (o.rq or o.care) and true or false}
    if o.rq then flags['rq_' .. o.rq] = true end
    local u = {id = id, pos = o.pos or {x = 50, y = 50, z = 10}, military = {squad_id = o.squad or -1},
               health = {flags = flags}, counters = {soldier_mood = o.mood or -1}, baby = o.baby, burrows = o.burrows or {},
               job = {current_job = o.job}, insane = o.insane}
    units[id] = u
    return u
end
local cits = {unit(1, {rq = 'suture'}),                              -- walking about, a treatment asked
              unit(2, {rq = 'diagnosis', pos = {x = 1, y = 0, z = 10}}),   -- already in the hospital
              unit(3, {rq = 'suture', squad = 4}), unit(4, {rq = 'dressing', baby = true}),
              unit(5, {care = true}),                                -- infected only: no treatment asked
              unit(7, {rq = 'suture', mood = 1}), unit(8, {rq = 'suture', burrows = {99}}),
              unit(9, {rq = 'setting'}), unit(10, {}), unit(11, {rq = 'suture', insane = true})}
local function item(t, inner, forbid) return {t = t, flags = {forbid = forbid}, inner = inner,
                                              getType = function(self) return self.t end} end
local function bld(id, kind, x1, y1, x2, y2, z, extra)
    local b = {id = id, x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = z, kind = kind, getType = function(self) return self.kind end,
               stage = 3, getBuildStage = function(self) return self.stage end, getMaxBuildStage = function() return 3 end}
    for k, v in pairs(extra or {}) do b[k] = v end
    return b
end
local zone = bld(70, 'Civzone', 0, 0, 2, 1, 10, {type = 1})
local drink = bld(80, 'Stockpile', 20, 0, 21, 0, 10, {settings = {flags = {food = true}}, contents = {item(2, {item(1)})}})
local food = bld(81, 'Stockpile', 30, 0, 30, 0, 10, {settings = {flags = {food = true}}, contents = {item(3)}})
local far = bld(82, 'Stockpile', 5, 5, 5, 5, 20, {settings = {flags = {food = true}}, contents = {item(1)}})
local all = {zone, drink, food, far}
local hosp = {getType = function() return 7 end, occupations = {{unit_id = 9}, {unit_id = -1}}}
hosp.getContents = function() return {building_ids = hosp.ids} end
hosp.ids = {70}
local site = {buildings = {hosp}}
local burrows = {}
setmetatable(burrows, {__index = {insert = function(self, at, v) self[#self + 1] = v end}})
-- the well's shaft (x 10, y 10): z -> {shape, mat, flow, hatch}
local shaft = {}
local at_tile = {}                                 -- 'x,y,z' -> a building (a bed, a hatch)
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.require = function(name) if name == 'utils' then return {insert_sorted = function() end} end return require(name) end
env.df = {global = {cur_year = 76, cur_year_tick = 1000, plotinfo = {burrows = {list = burrows, next_id = 1}},
                    world = {buildings = {all = all}}},
          burrow = {new = function() return {units_ = {}} end},
          building_type = {Civzone = 'Civzone', Stockpile = 'Stockpile', Well = 'Well', Hatch = 'Hatch', Bed = 'Bed'},
          civzone_type = {[1] = 'Hospital'}, abstract_building_type = {[7] = 'HOSPITAL'},
          item_type = {[1] = 'DRINK', [2] = 'BARREL', [3] = 'FOOD'}, soldier_mood_type = {[1] = 'Tantrum'},
          job_type = {Rest = 'Rest'},
          tiletype = {attrs = setmetatable({}, {__index = function(_, tt) return {shape = tt.shape, material = tt.mat} end})},
          tiletype_shape = setmetatable({}, {__index = function(_, k) return k end}),
          tiletype_material = setmetatable({}, {__index = function(_, k) return k end}),
          unit = {find = function(id) return units[id] end}}
local function key(p) return p.x .. ',' .. p.y .. ',' .. p.z end
local fail_assign = {}
env.dfhack = {
    persistent = {getSiteData = function(k, d) return persist[k] or d end, saveSiteData = function(k, v) persist[k] = v end},
    world = {getCurrentSite = function() return site end},
    maps = {getWalkableGroup = function(p) return p.z == 20 and 2 or 1 end,
            getTileType = function(p)
                local t = p.x == 10 and p.y == 10 and shaft[p.z]
                return t and {shape = t.shape, mat = t.mat} or {shape = 'WALL', mat = 'STONE'} end,
            getTileFlags = function(p)
                local t = p.x == 10 and p.y == 10 and shaft[p.z]
                return {flow_size = t and t.flow or 0, liquid_type = false} end},
    items = {getContainedItems = function(it) return it.inner or {} end},
    buildings = {containsTile = function() return true end, getStockpileContents = function(b) return b.contents end,
                 findAtTile = function(p) return at_tile[key(p)] end},
    burrows = {clearTiles = function() for k in pairs(tiles) do tiles[k] = nil end end,
               setAssignedTile = function(b, p, on) tiles[key(p)] = on; return true end,
               setAssignedUnit = function(b, u, on)
                   if on and fail_assign[u.id] then error('assign failed') end
                   b.units_ = b.units_ or {}
                   b.units_[u.id] = on and u or nil
                   local keep = {}
                   for _, id in ipairs(u.burrows) do if id ~= b.id then table.insert(keep, id) end end
                   if on then table.insert(keep, b.id) end
                   u.burrows = keep
               end,
               listUnits = function(b) local l = {}; for _, u in pairs(b.units_ or {}) do table.insert(l, u) end; return l end},
    units = {getCitizens = function() return cits end, isCitizen = function(u) return true end,
             isSane = function(u) return not u.insane end,
             isBaby = function(u) return u.baby == true end,
             getReadableName = function(u) return 'dwarf ' .. u.id end}}
assert(load(src, 'ai-society', 't', env))()
local W = {units = units, all = all, drink = drink, food = food, hosp = hosp, persist = persist, burrows = burrows,
           shaft = shaft, at_tile = at_tile, fail_assign = fail_assign, g = env.df.global,
           bld = bld, item = item, ntiles = function() local n = 0; for _ in pairs(tiles) do n = n + 1 end; return n end}
function W.assigned()
    local out = {}
    for _, b in ipairs(burrows) do
        if b.name == 'AI hospital' or b.id == (persist['ai-overseer/hospital-burrow'] or {}).burrow_id then
            for id in pairs(b.units_ or {}) do out[id] = true end
        end
    end
    return out
end
function W.burrow() for _, b in ipairs(burrows) do if b.id == (persist['ai-overseer/hospital-burrow'] or {}).burrow_id then return b end end end
function W.day(n) env.df.global.cur_year_tick = 1000 + n * 1200 end
function W.listed() local n = 0; for _ in pairs((persist['ai-overseer/hospital-burrow'] or {}).members or {}) do n = n + 1 end; return n end
return env, W
"""


def hosp_fresh():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(HOSP_FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))
    return lua, env, w


def _names(t):
    return [t[i] for i in range(1, len(t) + 1)] if t else []


def _ids(w):
    return sorted(dict(w.assigned()).keys())


@test("hospital burrow (0.104.167): over the hospital's zones and the nearest reachable drink and food; patients outside first; never soldiers, staff, babies, the raging, the insane, the infected only, or one in a player's burrow")
def _():
    lua, env, w = hosp_fresh()
    d = env.hospital_burrow_tick(30, 10, True)
    assert d.ok and d.dry_run and not _ids(w) and len(w.burrows) == 0, dict(d)    # a dry run changes nothing
    r = env.hospital_burrow_tick(30, 10, False)
    # the 3x2 ward + the 2-tile drink pile + the 1-tile food pile (never the pile nobody can walk to)
    assert r.ok and r.tiles == 9 and w.ntiles() == 9 and r.drink == "stockpile" and r.food, dict(r)
    assert _names(r.added) == ["dwarf 1", "dwarf 2"], _names(r.added)       # the one walking about first
    assert _ids(w) == [1, 2] and w.listed() == 2, _ids(w)
    s = env.hospital_burrow_status()
    assert s.members == 2 and s.outside == 0 and s.hospital_zones == 1 and s.patients == 8, dict(s)
    assert env.hospital_burrow_tick(30, 10, False).unchanged
    lua, env, w = hosp_fresh()
    r = env.hospital_burrow_tick(30, 1, False)                              # a cap a call
    assert _names(r.added) == ["dwarf 1"], _names(r.added)
    lua, env, w = hosp_fresh()
    assert env.hospital_burrow_status().outside == 1                        # dwarf 1, before the burrow


@test("hospital burrow (0.104.167): the healed let out; no drink reachable: everyone out and nobody in; no hospital: refused; the brain's release empties it")
def _():
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    w.units[1].health.flags.rq_suture = False                               # treated
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and _names(r.released) == ["dwarf 1"] and _ids(w) == [2], dict(r)
    lua.execute("local W = ...; W.drink.contents = {}", w)                  # the pile drunk dry
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and r.members == 0 and "no drink" in r.note and not _ids(w), dict(r)
    r = env.hospital_burrow_tick(30, 10, False)
    assert not r.ok and r.rejected and "no drink" in r.error and not _ids(w), dict(r)
    assert "no drink" in env.hospital_burrow_status().why
    lua, env, w = hosp_fresh()
    lua.execute("local W = ...; W.hosp.ids = {}", w)
    r = env.hospital_burrow_tick(30, 10, False)
    assert not r.ok and r.rejected and "no hospital" in r.error and not _ids(w), dict(r)
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    r = env.hospital_burrow_tick(30, 10, False, None, 28, True)
    assert r.ok and len(_names(r.released)) == 2 and not _ids(w) and w.listed() == 0, dict(r)
    assert env.hospital_burrow_tick(30, 10, False, None, 28, True).unchanged


@test("hospital burrow (0.104.167, review): a second hospital zone or a new drink pile: the tiles filled again at once")
def _():
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    lua.execute("local W = ...; table.insert(W.all, W.bld(71, 'Civzone', 40, 0, 40, 0, 10, {type = 1})); W.hosp.ids = {70, 71}", w)
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and r.tiles == 6 + 1 + 2 + 1, dict(r)
    # the status call (every report) refills too, when the sources change
    lua.execute("local W = ...; table.insert(W.all, W.bld(83, 'Stockpile', 3, 0, 3, 0, 10, "
                "{settings = {flags = {food = true}}, contents = {W.item(1)}}))", w)
    env.hospital_burrow_status()
    assert w.ntiles() == 6 + 1 + 1 + 1, w.ntiles()                         # the nearer drink pile (83) instead of 80


@test("hospital burrow (0.104.167, review): a well counts only built, its shaft open, over unfrozen water deep enough")
def _():
    lua, env, w = hosp_fresh()
    lua.execute("""local W = ...
      W.drink.contents = {}
      W.well = W.bld(90, 'Well', 10, 10, 10, 10, 10, {centerx = 10, centery = 10})
      table.insert(W.all, W.well)
      W.shaft[9] = {shape = 'EMPTY', mat = 'AIR', flow = 0}
      W.shaft[8] = {shape = 'EMPTY', mat = 'AIR', flow = 0}
      W.shaft[7] = {shape = 'FLOOR', mat = 'STONE', flow = 4}
    """, w)
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and r.drink == "well" and r.tiles == 6 + 1 + 9 and _ids(w) == [1, 2], dict(r)
    def no_drink(setup):
        lua2, env2, w2 = hosp_fresh()
        lua2.execute("""local W = ...
          W.drink.contents = {}
          W.well = W.bld(90, 'Well', 10, 10, 10, 10, 10, {centerx = 10, centery = 10})
          table.insert(W.all, W.well)
          W.shaft[9] = {shape = 'EMPTY', mat = 'AIR', flow = 0}
          W.shaft[8] = {shape = 'EMPTY', mat = 'AIR', flow = 0}
          W.shaft[7] = {shape = 'FLOOR', mat = 'STONE', flow = 4}
        """ + setup, w2)
        r2 = env2.hospital_burrow_tick(30, 10, False)
        return not r2.ok and "no drink" in r2.error and not _ids(w2)
    assert no_drink("W.well.stage = 1"), "a well still being built"
    assert no_drink("W.at_tile['10,10,8'] = {getType = function() return 'Hatch' end, door_flags = {closed = true}}"), \
        "the shaft gate shut"
    assert no_drink("W.shaft[7] = {shape = 'FLOOR', mat = 'FROZEN_LIQUID', flow = 0}"), "frozen"
    assert no_drink("W.shaft[7].flow = 1"), "too shallow"
    assert no_drink("W.shaft[8] = {shape = 'FLOOR', mat = 'STONE', flow = 0}"), "the shaft ends dry"
    assert not no_drink("W.at_tile['10,10,8'] = {getType = function() return 'Hatch' end, door_flags = {closed = false}}"), \
        "an open shaft gate gives water"


@test("hospital burrow (0.104.167, review): found by its saved id (renamed: still ours); removed by the player: its list cleared")
def _():
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    lua.execute("local W = ...; W.burrow().name = 'Ward'", w)              # renamed
    w.units[1].health.flags.rq_suture = False
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and _names(r.released) == ["dwarf 1"] and len(w.burrows) == 1, dict(r)   # not a second burrow
    assert env.hospital_burrow_status().members == 1
    lua.execute("""local W = ...
      local b = table.remove(W.burrows, 1)                              -- removed (DF takes it off its units too)
      for _, u in pairs(W.units) do
          local keep = {}
          for _, id in ipairs(u.burrows) do if id ~= b.id then table.insert(keep, id) end end
          u.burrows = keep
      end""", w)
    s = env.hospital_burrow_status()
    assert s.members == 0 and s.burrow is None and w.listed() == 0, dict(s)
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and _names(r.added) == ["dwarf 2"] and len(w.burrows) == 1, (_names(r.added), _names(r.released))  # a new one


@test("hospital burrow (0.104.167, review): every report re-checks the members: no drink, no hospital, assigned but unlisted all let out")
def _():
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    lua.execute("local W = ...; W.drink.contents = {}", w)
    s = env.hospital_burrow_status()
    assert s.members == 0 and not _ids(w) and "no drink" in s.why and len(_names(s.released_now)) == 2, dict(s)
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    lua.execute("local W = ...; W.hosp.ids = {}", w)
    s = env.hospital_burrow_status()
    assert s.members == 0 and not _ids(w), dict(s)
    # assigned but not listed (a throw, a player's hand): out; listed but not assigned: dropped
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    lua.execute("""local W, env = ...
      local b = W.burrow()
      env.dfhack.burrows.setAssignedUnit(b, W.units[10], true)
      env.dfhack.burrows.setAssignedUnit(b, W.units[2], false)""", w, env)
    s = env.hospital_burrow_status()
    assert _ids(w) == [1] and s.members == 1 and w.listed() == 1, (_ids(w), dict(s))


@test("hospital burrow (0.104.167, review): at most 28 days, then out a week; no food in reach: only those in a hospital bed, the rest out after 3 days")
def _():
    lua, env, w = hosp_fresh()
    env.hospital_burrow_tick(30, 10, False)
    w.day(29)
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and len(_names(r.released)) == 2 and not _ids(w) and not _names(r.added), dict(r)
    w.day(37)
    r = env.hospital_burrow_tick(30, 10, False)
    assert _ids(w) == [1, 2], dict(r)                                       # a week later: back in
    # no food pile: only one lying in a hospital bed is moved in
    lua, env, w = hosp_fresh()
    lua.execute("""local W = ...
      W.food.contents = {}
      W.at_tile['1,0,10'] = {getType = function() return 'Bed' end}
      W.units[2].job.current_job = {job_type = 'Rest'}""", w)
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and _names(r.added) == ["dwarf 2"] and not r.food, dict(r)
    w.units[2].job.current_job = None                                       # up and about
    w.day(2)
    assert _ids(w) == [2] and env.hospital_burrow_tick(30, 10, False).unchanged
    w.day(4)
    r = env.hospital_burrow_tick(30, 10, False)
    assert _names(r.released) == ["dwarf 2"] and not _ids(w), dict(r)


@test("hospital burrow (0.104.167, review): a patient in the AI's recreation burrow is taken out of it and moved in")
def _():
    lua, env, w = hosp_fresh()
    lua.execute("""local W, env = ...
      local rec = {name = 'AI recreation', id = 40, units_ = {}}
      table.insert(W.burrows, rec)
      env.dfhack.burrows.setAssignedUnit(rec, W.units[1], true)
      W.persist['ai-overseer/recreation'] = {members = {['1'] = 1000}, out = {}}
      W.rec = rec""", w, env)
    r = env.hospital_burrow_tick(30, 10, False)
    assert "dwarf 1 (from the recreation burrow)" in _names(r.added) and _ids(w) == [1, 2], dict(r)
    assert lua.eval("function(W) return W.rec.units_[1] == nil and W.persist['ai-overseer/recreation'].members['1'] == nil end")(w)
    assert lua.eval("function(W) return #W.units[1].burrows end")(w) == 1


@test("hospital burrow (0.104.167, review): a forbidden barrel's drink doesn't count; a failed assignment is never listed")
def _():
    lua, env, w = hosp_fresh()
    lua.execute("local W = ...; W.drink.contents = {W.item(2, {W.item(1)}, true)}", w)
    r = env.hospital_burrow_tick(30, 10, False)
    assert not r.ok and "no drink" in r.error, dict(r)
    lua, env, w = hosp_fresh()
    lua.execute("local W = ...; W.fail_assign[1] = true", w)
    r = env.hospital_burrow_tick(30, 10, False)
    assert r.ok and _names(r.added) == ["dwarf 2"] and _ids(w) == [2] and w.listed() == 1, dict(r)


CUP_WORLD = """
  local env = ...
  local W = {}
  env.df.item_type = {GOBLET = 7}
  env.df.building_type.Stockpile = 'Stockpile'
  env.df.abstract_building_type = {[3] = 'INN_TAVERN'}
  -- the finished goods piles: A (2 free tiles) refuses goblets; B (5 free) takes them but no wood
  local function pile(id, free, goblets, wood)
    return {id = id, x1 = id, y1 = 0, x2 = id, y2 = free - 1, z = 1, free_ = free, use_links_only = 0,
            settings = {flags = {finished_goods = true},
                        finished_goods = {type = {[7] = goblets}, mats = {[5] = true}, other_mats = {[0] = wood},
                                          quality_core = {[0] = true}}},
            getType = function() return 'Stockpile' end}
  end
  W.A, W.B = pile(100, 2, false, true), pile(200, 5, true, false)
  env.df.global.world.buildings.other = {STOCKPILE = {W.A, W.B}}
  -- tiles: x 100/200 are piles (all free); the halls at y 10 (dining, a zone) and 20 (a tavern's)
  env.dfhack.maps = {getTileFlags = function(x, y, z) return {pile = (x == 100 or x == 200)}, {item = false} end,
                     getWalkableGroup = function(p) return (p.x == 99) and 2 or 1 end}
  local hall = {location_id = -1}
  local tavern = {location_id = 3}
  env.dfhack.buildings.findCivzonesAt = function(p)
    if p.y == 10 then return {hall} elseif p.y == 20 then return {tavern} end
    return {} end
  env.dfhack.buildings.findAtTile = function(p) return nil end
  env.dfhack.world.getCurrentSite = function()
    return {buildings = {{id = 3, getType = function() return 3 end}}} end
  env.dfhack.units.getPosition = function(u) return 1, 1, 1 end
  env.dfhack.units.getCitizens = function() return {{}} end
  env.dfhack.items = {getPosition = function(i) return i.x, i.y, 1 end, getHolderBuilding = function() return nil end,
                      getContainer = function() return nil end}
  env.dfhack.matinfo = {decode = function(i)
    if i.mat == 'wood' then return {plant = {}, material = {flags = {WOOD = true}}, getToken = function() return 'PLANT:X:WOOD' end} end
    return {inorganic = {}, index = 5, getToken = function() return 'INORGANIC:X' end} end}
  local function cup(x, y, mat, flags)
    local f = flags or {}
    f.on_ground = true
    return {x = x, y = y, mat = mat, flags = f, getQuality = function() return 0 end, maker_race = -1}
  end
  W.cups = {[0] = cup(5, 10, 'wood'), [1] = cup(6, 10, 'stone'), [2] = cup(7, 20, 'stone'),
            [3] = cup(99, 10, 'stone'), [4] = cup(8, 10, 'stone', {forbid = true})}
  env.df.global.world.items = {other = {GOBLET = W.cups}}
  return W
"""


@test("cups (0.104.168): the census says why each loose cup stays (a tavern's, the piles refuse it, cut off, should be hauled) and every cup's flags")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))[0]
    W = env["load"](CUP_WORLD, "t", "t", env)(env)
    d = env.free_items_count("GOBLET", True)
    why = dict(d.why)
    # wood: B takes goblets but not wood, A no goblets -> material; the tavern's; x99 cut off; the stone one in the hall: B takes it
    assert why == {"pile_refuses_material": 1, "location": 1, "unreachable": 1, "should_haul": 1}, why
    assert dict(d.why_locations) == {"INN_TAVERN": 1} and d.n == 4, (dict(d.why_locations), d.n)
    assert d.flags.forbid == 1 and d.flags.on_ground == 5 and d.forbidden_in_halls == 1, dict(d.flags)
    assert (d.piles.finished_goods, d.piles.take_goblets) == (2, 1)
    assert dict(d.mats) == {"wood": 1, "inorganic": 3}, dict(d.mats)


@test("cups (0.104.168): accept_cups sets the pile with the most room to take the refused cups (their material too); unforbids those in a hall")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(FAKE, (ROOT / "lua" / "ai-society.lua").read_text(encoding="utf-8"))[0]
    W = env["load"](CUP_WORLD, "t", "t", env)(env)
    r = env.accept_cups(True)
    assert r.ok and r.dry_run and r.cups_refused == 1 and r.unforbidden == 1 and r.pile_id == 200, dict(r)
    assert not W.B.settings.finished_goods.other_mats[0] and W.cups[4].flags.forbid       # a dry run changes nothing
    r = env.accept_cups(False)
    assert r.ok and r.pile_id == 200 and r.materials_set == 1 and r.unforbidden == 1, dict(r)
    assert W.B.settings.finished_goods.other_mats[0] is True and not W.cups[4].flags.forbid
    assert W.A.settings.finished_goods.type[7] is False                    # the other pile left as it was
    assert not W.cups[2].flags.forbid                                      # (the tavern's never touched)
    r = env.accept_cups(False)
    assert not r.ok and r.rejected, dict(r)                                # nothing left to fix
    # no pile takes goblets at all: the one with the most room is set to
    W.B.settings.finished_goods.type[7] = False
    r = env.accept_cups(False)
    assert r.ok and r.piles_set == 1 and W.B.settings.finished_goods.type[7] is True and not W.A.settings.finished_goods.type[7], dict(r)


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
