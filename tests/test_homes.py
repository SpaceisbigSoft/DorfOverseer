"""Tests for lua/ai-homes.lua (0.104.168: the households' bedrooms), in a real
Lua engine with a small fake of the game's records (pip install lupa).

    python tests/test_homes.py
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

SRC = (ROOT / "lua" / "ai-homes.lua").read_text(encoding="utf-8")

# spec: units = [{id, child, spouse, mother, father, cat, likes_mat = [mt, mi], likes_item = [it, st],
#                 thoughts = [name], noble, far}], zones = [{id, owner, bed, statue, items = [{v, mt, mi, it, st}]}]
FAKE = r"""
local src, spec = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return t
end
local function vlen(t) local n = 0; while rawget(t, n) ~= nil do n = n + 1 end; return n end
local function vpush(t, v) t[vlen(t)] = v end
local function verase(t, v)
    local n = vlen(t)
    for i = 0, n - 1 do
        if t[i] == v then
            for j = i, n - 2 do t[j] = t[j + 1] end
            t[n - 1] = nil
            return
        end
    end
end
local BT = {Civzone = 1, Bed = 2, Statue = 3, Cabinet = 4}
local THOUGHTS = {[1] = 'SleptGrass', [2] = 'LackBedroom', [3] = 'Rest'}
local THOUGHT_ID = {SleptGrass = 1, LackBedroom = 2, Rest = 3}
local units, by_id = {}, {}
for _, s in ipairs(spec.units) do
    local prefs = {}
    if s.likes_mat then table.insert(prefs, {type = 0, mattype = s.likes_mat[1], matindex = s.likes_mat[2]}) end
    if s.likes_item then table.insert(prefs, {type = 4, item_type = s.likes_item[1], item_subtype = s.likes_item[2]}) end
    local ems = {}
    for _, th in ipairs(s.thoughts or {}) do table.insert(ems, {thought = THOUGHT_ID[th], year = 50, year_tick = 1000}) end
    local u = {id = s.id, pos = {x = s.far and 999 or 1, y = 1, z = 1}, child = s.child, cat = s.cat or 4,
               noble = s.noble,
               relationship_ids = {Spouse = s.spouse or -1, Mother = s.mother or -1, Father = s.father or -1},
               owned_buildings = vec(),
               status = {current_soul = {preferences = vec(prefs), personality = {emotions = vec(ems)}}}}
    table.insert(units, u)
    by_id[u.id] = u
end
local zones = {}
for _, s in ipairs(spec.zones) do
    local subs = {}
    local function item(i) return {getMaterial = function() return i.mt or 0 end,
                                    getMaterialIndex = function() return i.mi or 0 end,
                                    getType = function() return i.it or 0 end,
                                    getSubtype = function() return i.st or -1 end, v = i.v or 0} end
    local items = {}
    for _, i in ipairs(s.items or {}) do table.insert(items, {item = item(i)}) end
    if s.bed ~= false then
        table.insert(subs, {getType = function() return BT.Bed end, centerx = 1, centery = 1, z = 1,
                            contained_items = vec(items)})
    end
    if s.statue then table.insert(subs, {getType = function() return BT.Statue end, contained_items = vec()}) end
    local z = {id = s.id, type = 7, assigned_unit_id = -1, contained_buildings = vec(subs),
               getType = function() return BT.Civzone end}
    table.insert(zones, z)
end
-- DFHack's Buildings::setOwner: the zone's owner, the owner's list and the spouse's
local function set_owner(z, u)
    local id = u and u.id or -1
    if z.assigned_unit_id == id then return true end
    if z.assigned_unit_id ~= -1 then
        local old = by_id[z.assigned_unit_id]
        if old then
            verase(old.owned_buildings, z)
            local sp = by_id[old.relationship_ids.Spouse]
            if sp then verase(sp.owned_buildings, z) end
        end
    end
    z.assigned_unit_id = id
    if u then
        vpush(u.owned_buildings, z)
        local sp = by_id[u.relationship_ids.Spouse]
        if sp then
            local has = false
            for i = 0, vlen(sp.owned_buildings) - 1 do if sp.owned_buildings[i] == z then has = true end end
            if not has then vpush(sp.owned_buildings, z) end
        end
    end
    return true
end
for i, s in ipairs(spec.zones) do
    if s.owner then
        set_owner(zones[i], by_id[s.owner])
        -- (unlinked: married after the room was assigned)
        if s.unlinked then local sp = by_id[by_id[s.owner].relationship_ids.Spouse]; verase(sp.owned_buildings, zones[i]) end
    end
end
local env = setmetatable({}, {__index = _G})
env.df = {
    global = {cur_year = 50, cur_year_tick = 5000,
              world = {buildings = {other = {ZONE_BEDROOM = vec(zones)}, all = vec(zones)}}},
    civzone_type = {[7] = 'Bedroom', Bedroom = 7},
    building_type = BT,
    unit_thought_type = THOUGHTS,
    unitpref_type = {[0] = 'LikeMaterial', [4] = 'LikeItem'},
    unit = {find = function(id) return by_id[id] end},
}
env.dfhack = {
    units = {getCitizens = function() return units end,
             isChild = function(u) return u.child == true end, isBaby = function() return false end,
             getReadableName = function(u) return 'dwarf ' .. u.id end,
             getStressCategory = function(u) return u.cat end,
             getNoblePositions = function(u)
                 if u.noble then return {{position = {required_bedroom = 1}}} end
                 return nil
             end},
    buildings = {setOwner = set_owner},
    items = {getValue = function(i) return i.v end},
    maps = {canWalkBetween = function(a, b) return a.x ~= 999 end,
            getWalkableGroup = function(pos) return pos.x == 999 and 2 or 1 end},
}
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
assert(load(src, 'ai-homes', 't', env))()
local function owner_of(id) for _, z in ipairs(zones) do if z.id == id then return z.assigned_unit_id end end end
local function rooms_of(uid)
    local out = {}
    local u = by_id[uid]
    for i = 0, vlen(u.owned_buildings) - 1 do table.insert(out, u.owned_buildings[i].id) end
    table.sort(out)
    return table.concat(out, ',')
end
return env, owner_of, rooms_of
"""


def game(units, zones):
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(v):
        if isinstance(v, dict):
            return lua.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return lua.table_from([lt(x) for x in v])
        return v
    return lua.execute(FAKE, SRC, lt({"units": units, "zones": zones}))


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


BED = [{"v": 10}]


@test("census: couples in two rooms, in none, children by their parents' room, free rooms, rough sleepers")
def _():
    units = [{"id": 1, "spouse": 2}, {"id": 2, "spouse": 1},                    # two rooms
             {"id": 3, "spouse": 4, "thoughts": ["SleptGrass"]}, {"id": 4, "spouse": 3},   # none
             {"id": 5, "child": True, "mother": 1},                               # a parent's room
             {"id": 6, "child": True},                                            # no parent here, no room
             {"id": 7, "thoughts": ["SleptGrass", "LackBedroom"]},                # single, no room
             {"id": 8, "thoughts": ["SleptGrass"], "far": True}]                  # a room, can't walk to it
    zones = [{"id": 10, "owner": 1, "items": BED}, {"id": 11, "owner": 2, "items": BED},
             {"id": 12, "owner": 8, "items": BED}, {"id": 13, "items": BED}, {"id": 14, "statue": True},
             {"id": 15, "bed": False}]
    env, _, _ = game(units, zones)
    c = env.census()
    assert c.couples == 2 and c.couples_apart == 1 and c.couples_none == 1, dict(c)
    assert c.children == 2 and c.children_roomless == 1, dict(c)
    assert c.adults_roomless == 3 and c.rooms_wanted == 3, dict(c)     # couple 3+4 (one room), 7, child 6
    assert c.free_bedrooms == 1 and c.free_suites == 1 and c.free_bedless == 1, dict(c)
    assert c.rough == 3 and c.rough_housed == 1 and c.rough_unreachable == 1 and c.lack_room == 1, dict(c)


@test("a couple in two rooms keeps the better one for both and frees the other; both have it")
def _():
    units = [{"id": 1, "spouse": 2}, {"id": 2, "spouse": 1, "likes_mat": [0, 5]}]
    zones = [{"id": 10, "owner": 1, "items": [{"v": 20}]}, {"id": 11, "owner": 2, "items": [{"v": 12, "mi": 5}]}]
    env, owner_of, rooms_of = game(units, zones)
    dry = env.house(5, 0, True)
    assert dry.ok and dry.merged == 1 and owner_of(11) == 2, dict(dry)          # a dry run changes nothing
    r = env.house(5, 0, False)
    assert r.ok and r.merged == 1 and r.freed == 1, dict(r)
    # room 10: 20 + 20 = 40 for the two; room 11: 12 + 24 (the one who likes its material) = 36
    assert owner_of(10) == 1 and owner_of(11) == -1, (owner_of(10), owner_of(11))
    assert rooms_of(1) == "10" and rooms_of(2) == "10", (rooms_of(1), rooms_of(2))
    assert env.census().couples_apart == 0


@test("the room a spouse likes wins when it counts for more; a noble's own room is always kept")
def _():
    units = [{"id": 1, "spouse": 2}, {"id": 2, "spouse": 1, "likes_mat": [0, 5]}]
    zones = [{"id": 10, "owner": 1, "items": [{"v": 15}]}, {"id": 11, "owner": 2, "items": [{"v": 12, "mi": 5}]}]
    env, owner_of, rooms_of = game(units, zones)
    env.house(5, 0, False)                                                    # 30 against 12 + 24 = 36
    assert owner_of(11) == 2 and owner_of(10) == -1 and rooms_of(1) == "11", (owner_of(10), owner_of(11))
    units[0]["noble"] = True
    env, owner_of, _ = game(units, zones)
    env.house(5, 0, False)
    assert owner_of(10) == 1 and owner_of(11) == -1


@test("a couple whose room is in one spouse's list only: given again, now in both")
def _():
    units = [{"id": 1, "spouse": 2}, {"id": 2, "spouse": 1}]
    zones = [{"id": 10, "owner": 1, "items": BED, "unlinked": True}]
    env, owner_of, rooms_of = game(units, zones)
    assert env.census().couples_unlinked == 1 and rooms_of(2) == ""
    r = env.house(5, 0, False)
    assert r.ok and r.merged == 1 and rooms_of(2) == "10" and owner_of(10) == 1, dict(r)


@test("households with none get the best free room they can reach, couples one, a parent's child none")
def _():
    units = [{"id": 1, "spouse": 2}, {"id": 2, "spouse": 1}, {"id": 3, "child": True, "mother": 1},
             {"id": 4, "far": True}, {"id": 5, "cat": 0}]
    zones = [{"id": 10, "items": [{"v": 5}]}, {"id": 11, "items": [{"v": 30}]}, {"id": 12, "items": [{"v": 8}]},
             {"id": 13, "statue": True, "items": [{"v": 500}]}]
    env, owner_of, rooms_of = game(units, zones)
    r = env.house(10, 0, False)
    assert r.ok and r.housed == 2, dict(r)                                    # the couple and dwarf 5
    assert owner_of(13) == -1                                                  # a suite never
    assert owner_of(11) == 5, owner_of(11)                                    # the most stressed first: the best
    assert rooms_of(1) == rooms_of(2) and rooms_of(1) == "12", (rooms_of(1), rooms_of(2))
    assert rooms_of(3) == "" and rooms_of(4) == "", (rooms_of(3), rooms_of(4))   # rides on mother's; can't reach


@test("the stressed move to a free room much better for them (a liked kind of furniture counts double)")
def _():
    units = [{"id": 1, "cat": 1, "likes_item": [7, -1]}, {"id": 2, "cat": 1}, {"id": 3, "cat": 5}]
    zones = [{"id": 10, "owner": 1, "items": [{"v": 20}]}, {"id": 11, "owner": 2, "items": [{"v": 20}]},
             {"id": 12, "owner": 3, "items": [{"v": 1}]},
             {"id": 13, "items": [{"v": 25, "it": 7}]}]
    env, owner_of, _ = game(units, zones)
    r = env.house(0, 5, False)
    assert r.ok and r.upgraded == 1 and owner_of(13) == 1 and owner_of(10) == -1, dict(r)   # 50 vs 20
    # dwarf 2 (no liking: 25 vs 20, not 1.5x) stays; content dwarf 3 isn't moved; then nothing to do
    assert owner_of(11) == 2 and owner_of(12) == 3
    again = env.house(0, 5, False)
    assert not again.ok and again.rejected


@test("a dwarf owning two bedrooms keeps the best")
def _():
    env, owner_of, rooms_of = game([{"id": 1}], [{"id": 10, "owner": 1, "items": [{"v": 3}]},
                                                  {"id": 11, "owner": 1, "items": [{"v": 9}]}])
    assert env.census().hoarders == 1
    r = env.house(3, 0, False)
    assert r.merged == 1 and rooms_of(1) == "11" and owner_of(10) == -1, dict(r)


@test("review: a noble spouse's room is never left in an upgrade; two nobles in two rooms keep both")
def _():
    units = [{"id": 1, "spouse": 2, "cat": 0}, {"id": 2, "spouse": 1, "noble": True}]
    zones = [{"id": 10, "owner": 1, "items": [{"v": 5}]}, {"id": 11, "items": [{"v": 500}]}]
    env, owner_of, rooms_of = game(units, zones)
    r = env.house(0, 5, False)
    assert not r.ok and owner_of(10) == 1 and owner_of(11) == -1 and rooms_of(2) == "10", dict(r)
    units = [{"id": 1, "spouse": 2, "noble": True}, {"id": 2, "spouse": 1, "noble": True}]
    zones = [{"id": 10, "owner": 1, "items": BED}, {"id": 11, "owner": 2, "items": BED}]
    env, owner_of, _ = game(units, zones)
    c = env.census()
    assert c.couples_apart == 0 and c.couples_nobles == 1, dict(c)
    assert not env.house(5, 0, False).ok and owner_of(10) == 1 and owner_of(11) == 2


@test("review: the census counts only what the action does (a noble's two rooms; a roomless dwarf cut off)")
def _():
    env, _, _ = game([{"id": 1, "noble": True}], [{"id": 10, "owner": 1, "items": BED},
                                                   {"id": 11, "owner": 1, "items": BED}])
    assert env.census().hoarders == 0
    env, _, _ = game([{"id": 1, "far": True}, {"id": 2}], [{"id": 10, "items": BED}])
    c = env.census()
    assert c.rooms_wanted == 2 and c.rooms_reachable == 1 and c.rooms_unreachable == 1, dict(c)


@test("review: a room freed in this call (the old owner's things still in it) isn't given out in the same call")
def _():
    units = [{"id": 1, "spouse": 2}, {"id": 2, "spouse": 1}, {"id": 3}]
    zones = [{"id": 10, "owner": 1, "items": [{"v": 20}]}, {"id": 11, "owner": 2, "items": [{"v": 10}]}]
    env, owner_of, rooms_of = game(units, zones)
    r = env.house(5, 0, False)
    assert r.merged == 1 and r.housed == 0 and owner_of(11) == -1 and rooms_of(3) == "", dict(r)
    assert env.house(5, 0, False).housed == 1 and owner_of(11) == 3                  # the next call may
    units = [{"id": 1, "cat": 0}, {"id": 2, "cat": 0}]
    zones = [{"id": 10, "owner": 1, "items": [{"v": 1}]}, {"id": 11, "owner": 2, "items": [{"v": 2}]},
             {"id": 12, "items": [{"v": 100}]}]
    env, owner_of, _ = game(units, zones)
    r = env.house(0, 5, False)
    assert r.upgraded == 1 and owner_of(10) == -1 and owner_of(11) == 2, dict(r)    # 10 not given to dwarf 2


@test("0.104.169 (review): a room an AI calm burrow holds (a dwarf in a tantrum kept there) is never given out")
def _():
    units = [{"id": 5, "cat": 0}]
    zones = [{"id": 10, "items": [{"v": 5}]}, {"id": 11, "items": [{"v": 30}]}]
    env, owner_of, _ = game(units, zones)
    env["load"]("dfhack.persistent = {getSiteData = function(k, d) if k == 'ai-overseer/calm-burrow' then "
                "return {members = {['7'] = {room = 11, burrow = 3}}} end return d end}", "p", "t", env)()
    r = env.house(5, 0, False)
    assert r.housed == 1 and owner_of(10) == 5 and owner_of(11) == -1, (dict(r), owner_of(10), owner_of(11))


for name, ok, why in RESULTS:
    print(("[ ok ] " if ok else "[FAIL] ") + name + ("" if ok else "\n    " + why))
passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"{passed} passed, {len(RESULTS) - passed} failed")
sys.exit(0 if passed == len(RESULTS) else 1)
