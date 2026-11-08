"""(0.105.27, disposal round, group census) census.items.forbidden: the
forbidden items by type, reason and where; and get_dead's standing orders
(dead.standing) read as 0/1, the `== true` bug on forbid_own_dead fixed."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from lupa.lua53 import LuaRuntime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

CENSUS = (ROOT / "lua" / "ai-census.lua").read_text(encoding="utf-8")
REPORT = (ROOT / "lua" / "ai-bridge-report.lua").read_text(encoding="utf-8")

# A fake world: the fort is dwarves (race 1, civ 7) on level 10. Tiles: x >= 70
# is a cavern, y >= 80 outside, (90, 90) a walk group no citizen stands in.
# The cistern's room is x 5-6 y 5-6 z 10 and its tunnel (2,2)-(3,2) on z 9
# (the last tile the plug). A dump zone x 20-22 y 20-22, a stockpile at (41, 41),
# an invader at (60, 60).
FAKE = r"""
local src, util_exports = ...
local env = setmetatable({}, {__index = _G})
local function vec(l) local t = {_v = true}; for i, v in ipairs(l) do t[i - 1] = v end; return t end
local real = ipairs
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, '_v') then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return real(t)
end
local TYPES = {'BOULDER', 'AMMO', 'CORPSE', 'CORPSEPIECE', 'WEAPON', 'PANTS', 'BAR'}
local TYPE_ID = {}
for i, n in real(TYPES) do TYPE_ID[n] = i end
local function it(t, x, y, z, flags, extra)
    local f = flags or {}
    if f.on_ground == nil and not f.in_building then f.on_ground = true end
    if f.forbid == nil then f.forbid = true end
    local o = {t = TYPE_ID[t], pos = {x = x, y = y, z = z}, flags = f, wear = 0, quality = 0, metal = false,
               getType = function(self) return self.t end, getQuality = function(self) return self.quality end}
    for k, v in pairs(extra or {}) do o[k] = v end
    return o
end
local owner_dead = {id = 1, dead = true, flags2 = {}}
local ITEMS = {
    it('BOULDER', 5, 5, 10),                                    -- ai: the cistern's room
    it('BOULDER', 2, 2, 9),                                     -- ai: its tunnel
    it('BOULDER', 21, 21, 10),                                  -- dumped
    it('PANTS', 30, 30, 10, {dead_dwarf = true}, {wear = 2}),   -- own_dead (worn)
    it('PANTS', 31, 30, 10, {owned = true}, {owner = owner_dead}), -- own_dead: the owner is dead
    it('CORPSE', 32, 30, 10, nil, {race = 1, unit_id = 11}),    -- own_dead: a citizen's corpse
    it('AMMO', 40, 40, 10, nil, {metal = true}),                -- used_ammo
    it('AMMO', 41, 41, 10),                                     -- unknown: in a stockpile
    it('CORPSE', 50, 50, 10, nil, {race = 2, unit_id = 12}),    -- other_dead
    it('CORPSEPIECE', 50, 52, 10, nil, {race = 1, unit_id = 13}), -- other_dead: a dwarf of another civ
    it('WEAPON', 51, 51, 10, nil, {metal = true, quality = 5}), -- other_dead: lying by the goblin
    it('BOULDER', 61, 60, 10),                                  -- unknown, near danger
    it('BOULDER', 75, 10, 10),                                  -- unknown, caverns
    it('BAR', 10, 85, 10, {artifact = true}, {metal = true}),   -- unknown, surface, valuable
    it('BOULDER', 90, 90, 10),                                  -- unknown, unreachable
    it('BOULDER', -30000, -30000, -30000),                      -- off the map: not counted
    it('BOULDER', 12, 12, 10, {forbid = false}),                -- not forbidden
}
local UNITS = {[11] = {civ_id = 7}, [12] = {civ_id = 9}, [13] = {civ_id = 8}}
local enemy = {pos = {x = 60, y = 60, z = 10}, flags1 = {}, enemy = true}
local cit = {pos = {x = 30, y = 31, z = 10}, flags1 = {}}
local BT = {Civzone = 1, Stockpile = 2}
local function bld(t, x1, y1, x2, y2, z, extra)
    local b = {t = t, x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = z, getType = function(self) return self.t end}
    for k, v in pairs(extra or {}) do b[k] = v end
    return b
end
local dump = bld(BT.Civzone, 20, 20, 22, 22, 10, {type = 3})
local pile = bld(BT.Stockpile, 41, 41, 41, 41, 10)
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {global = {world = {units = {active = vec({enemy, cit})}, items = {all = vec(ITEMS)},
                             buildings = {all = vec({dump, pile})}, jobs = {list = {next = nil}}},
                    plotinfo = {race_id = 1, civ_id = 7}},
          item_type = TYPES, building_type = BT, civzone_type = {[3] = 'Dump'},
          unit = {find = function(id) return UNITS[id] end},
          creature_raw = {find = function() return {creature_id = 'X'} end}}
local SITE = {['ai-overseer/cistern'] = {stage = 'done', plan = {cistern = {x1 = 5, y1 = 5, x2 = 6, y2 = 6, z = 10},
              intake_z = 9, tunnel_path = {{x = 2, y = 2}, {x = 3, y = 2}, {x = 4, y = 2}}}}}
local util = {site_get = function(k, d) return SITE[k] or d end}
for k, v in pairs(util_exports or {}) do util[k] = v end
env.UTIL = util
env.reqscript = function(n)
    if n == 'ai-util' then return util end
    error('no module ' .. n)
end
env.dfhack = {
    units = {isDead = function(u) return u.dead == true end, isDanger = function(u) return u.enemy == true end,
             isInvader = function() return false end, getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end,
             getCitizens = function() return vec({cit}) end, isCitizen = function(u) return u == cit end,
             isActive = function() return true end, isTame = function() return false end,
             isDomesticated = function() return false end, isVisitor = function() return false end,
             isMerchant = function() return false end, isDiplomat = function() return false end,
             isAnimal = function() return false end},
    items = {getPosition = function(i)
                 if i.pos.x < 0 then return nil end
                 return i.pos.x, i.pos.y, i.pos.z end,
             getOwner = function(i) return i.owner end},
    matinfo = {decode = function(i) return {material = {flags = {IS_METAL = i.metal}}} end},
    maps = {getTileFlags = function(x, y, z) return {feature_global = x >= 70, outside = y >= 80} end,
            getWalkableGroup = function(p) return (p.x == 90 and p.y == 90) and 2 or 1 end},
    buildings = {findAtTile = function(p)
        if p.x == 41 and p.y == 41 and p.z == 10 then return pile end
        if p.x >= 20 and p.x <= 22 and p.y >= 20 and p.y <= 22 then return dump end
        return nil end},
}
assert(load(src, 'ai-census', 't', env))()
return env
"""


def world(util_exports=None):
    lua = LuaRuntime(unpack_returned_tuples=True)
    exports = lua.table_from(util_exports or {})
    return lua, lua.execute(FAKE, CENSUS, exports)


def forbidden(env):
    return env.census()["items"].forbidden


@test("census.items.forbidden: one item for each reason, counted by its reason")
def _():
    _, env = world()
    fb = forbidden(env)
    assert fb.total == 15, fb.total
    r = dict(fb.by_reason)
    assert r == {"ai": 2, "dumped": 1, "own_dead": 3, "used_ammo": 1, "other_dead": 3, "unknown": 5}, r
    assert sum(r.values()) == fb.total


@test("census.items.forbidden: by where (surface/inside/caverns, near danger, unreachable)")
def _():
    _, env = world()
    w = dict(forbidden(env).by_where)
    # near the invader at (60, 60): the boulder beside it and the goblin's three
    assert w == {"surface": 1, "inside": 12, "caverns": 2, "near_danger": 4, "unreachable": 1}, w


@test("census.items.forbidden: by type (a map, top 12), metal, worn and valuable")
def _():
    _, env = world()
    fb = forbidden(env)
    t = dict(fb.by_type)
    assert t == {"BOULDER": 6, "PANTS": 2, "CORPSE": 2, "AMMO": 2, "CORPSEPIECE": 1, "WEAPON": 1, "BAR": 1}, t
    assert (fb.metal, fb.worn, fb.valuable) == (3, 1, 2), (fb.metal, fb.worn, fb.valuable)


@test("census.items.forbidden: the old counts stay (counts.forbidden counts every forbidden item)")
def _():
    _, env = world()
    c = env.census()["items"].counts
    assert c.forbidden == 16 and c.off_map == 1, (c.forbidden, c.off_map)


@test("census.items.forbidden: danger_spots / near_danger taken from ai-util when it has them")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    exports = lua.execute("""
        local calls = {spots = 0, near = 0}
        return {calls = calls,
                danger_spots = function() calls.spots = calls.spots + 1; return {{x = 10, y = 85, z = 10}} end,
                near_danger = function(sp, x, y, z) calls.near = calls.near + 1; return x == 10 and y == 85 end}
    """)
    env = lua.execute(FAKE, CENSUS, exports)
    ds, nd, src = env.danger_helpers()
    assert src == "ai-util", src
    w = env.census()["items"].forbidden.by_where
    calls = exports.calls
    assert w.near_danger == 1 and calls.spots == 1 and calls.near == 15, (w.near_danger, calls.spots, calls.near)


@test("census.items.forbidden: no forbidden item, every reason and place still at 0")
def _():
    lua, env = world()
    lua.execute("local env = ...; for _, i in env.ipairs(env.df.global.world.items.all) do i.flags.forbid = false end", env)
    fb = forbidden(env)
    assert fb.total == 0 and all(v == 0 for v in dict(fb.by_reason).values()) and len(dict(fb.by_reason)) == 6
    assert len(dict(fb.by_where)) == 5


@test("census.items.forbidden: reaches memory.census (the brain keeps the census' items whole)")
def _():
    src = (ROOT / "brain" / "planner_core.py").read_text(encoding="utf-8")
    assert re.search(r'memory\.census = \{"tick": now, "units": _d\(r\.get\("units"\)\), "items": _d\(r\.get\("items"\)\)', src)


# the standing orders, read from get_dead's helper on its own
STANDING = re.search(r"^STANDING_DEAD_ORDERS = \{.*?^end\n(?=\nfunction get_dead)", REPORT, re.S | re.M).group(0)


def standing(globals_):
    lua = LuaRuntime(unpack_returned_tuples=True)
    run = lua.execute(r"""
        local src, g = ...
        local env = setmetatable({df = {global = g}}, {__index = _G})
        assert(load(src, 'standing', 't', env))()
        return env.standing_orders_dead()
    """, STANDING, lua.table_from(globals_))
    return dict(run)


@test("dead.standing: each standing_orders_* global that exists, as 0/1; others left out")
def _():
    s = standing({"standing_orders_forbid_own_dead": 1, "standing_orders_forbid_own_dead_items": 0,
                  "standing_orders_forbid_used_ammo": 1, "standing_orders_gather_refuse": 1,
                  "standing_orders_gather_refuse_outside": 0, "standing_orders_dump_bones": 3,
                  "standing_orders_forbid_other_dead_items": True,
                  "standing_orders_petition_citizenship": 1, "standing_orders_zoneonly_drink": 1})
    assert s == {"forbid_own_dead": 1, "forbid_own_dead_items": 0, "forbid_used_ammo": 1, "gather_refuse": 1,
                 "gather_refuse_outside": 0, "dump_bones": 1, "forbid_other_dead_items": 1}, s


@test("dead: forbid_own_dead and _items no longer compared `== true` (0/1 numbers)")
def _():
    assert "standing_orders_forbid_own_dead == true" not in REPORT
    assert "standing_orders_forbid_own_dead_items == true" not in REPORT
    assert "out.standing = standing_orders_dead()" in REPORT
    assert "out.forbid_own_dead = (out.standing.forbid_own_dead or 0) ~= 0" in REPORT


@test("the census and the report compile under Lua 5.3")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    for src in (CENSUS, REPORT):
        ok = lua.execute("local s = ...; local f, e = load(s); return f ~= nil, e", src)
        assert ok[0], ok[1]


if __name__ == "__main__":
    finish()
