"""(item1) lua/ai-spawn.lua: the tests' units set down (the siege test's war
party, ai-siege-invite spawn_party; the danger test, ai-military-duty
spawn_test_threat). DFHack 53.17-r1's modtools/create-unit is stale for DF 53
("create-unit.lua:164: Cannot read field world.arena_spawn: not found", A,
25 Nov 23:21), so spawn_units tries it and then makes them natively, as
DFHack's own fix of create-unit does (dfhack.units.create, world.units.active,
the tile's occupancy, the items put on by dfhack.items). The arena route of
0.105.124 is gone: DF 53 placed no unit from a simulated click (A, 26 Nov 00:35).

The source checks run anywhere; the fake-game ones need lupa (the PC).

    python tests/test_item1_spawn.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import code_has, finish, need_lua, test  # noqa: E402

LUA_DIR = ROOT / "lua"
CHANGED = ["ai-spawn.lua", "ai-siege-invite.lua", "ai-military-duty.lua", "ai-bridge.lua"]


def _src(name: str) -> str:
    return (LUA_DIR / name).read_text(encoding="utf-8")


LONG = re.compile(r"--\[(=*)\[.*?\]\1\]|\[(=*)\[.*?\]\2\]", re.S)
SHORT = re.compile(r"""("(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'|--[^\n]*)""")


def _code(name: str) -> str:
    """The source with comments and strings blanked (as tests/test_df_names.py reads it)."""
    src = _src(name)
    out, i = [], 0
    for m in re.finditer(LONG.pattern + "|" + SHORT.pattern, src, re.S):
        out.append(src[i:m.start()])
        out.append(re.sub(r"[^\n]", " ", m.group(0)))
        i = m.end()
    out.append(src[i:])
    return "".join(out)


# --- the sources (no lupa) --------------------------------------------------------------------

@test("every changed Lua file stays under 60 KB")
def _():
    for n in CHANGED:
        size = len(_src(n).encode("utf-8"))
        assert size < 60 * 1024, (n, size)


@test("Lua blocks balance in the changed files (function/if/do/repeat against end/until; brackets)")
def _():
    for n in CHANGED:
        code = _code(n)
        words = re.findall(r"(?<![\w.:])(function|if|do|repeat|end|until)(?![\w])", code)
        opens = sum(1 for w in words if w in ("function", "if", "do", "repeat"))
        closes = sum(1 for w in words if w in ("end", "until"))
        assert opens == closes, (n, opens, closes)
        for a, b in ("()", "{}", "[]"):
            assert code.count(a) == code.count(b), (n, a, code.count(a), code.count(b))


@test("ai-spawn is a module of the bridge and in the code map")
def _():
    s = _src("ai-spawn.lua")
    assert re.search(r"^--@ module = true", s, re.M)
    assert "'ai-spawn'," in _src("ai-bridge.lua").split("BRIDGE_MODULES = {", 1)[1].split("\n}", 1)[0]
    assert "`lua/ai-spawn.lua`" in (ROOT / "docs" / "code-map.md").read_text(encoding="utf-8")
    assert "PART_VERSIONS" not in s, "a plain module: no version mark of its own"


@test("spawn_party and spawn_test_threat go through ai-spawn, never create-unit themselves")
def _():
    inv, duty = _code("ai-siege-invite.lua"), _code("ai-military-duty.lua")
    for code in (inv, duty):
        assert "createUnit" not in code
    for n in ("ai-siege-invite.lua", "ai-military-duty.lua"):
        assert "'modtools/create-unit'" not in _src(n)
        assert "pcall(reqscript, 'ai-spawn')" in _src(n)
    s = _src("ai-siege-invite.lua")
    assert code_has(s, "local ids, why, info = SP.spawn_units{race = civ.race, count = SPAWN_COUNT,")
    assert code_has(s, "equipped = info.equipped == true, equip_error = info.equip_error, route = info.route, ids = ids, "
                       "spawn_info = brief}")
    assert code_has(s, "equipped = sp.equipped, route = sp.route, spawn_info = sp.spawn_info}")
    assert code_has(s, "spawn_error = rec.spawn_error, spawn_info = rec.spawn_info,")
    # (26 Nov 00:35) 200 chars lost the diagnosis: 600 kept, and the spawner's info in the record
    assert "SPAWN_WHY = 600" in s
    assert code_has(s, "return nil, ('no war party placed: ' .. tostring(why or 'no unit')):sub(1, SPAWN_WHY), brief")
    assert code_has(s, "local sp, why, sinfo = spawn_party(top)")
    assert code_has(s, "rec.spawn_error = why and tostring(why):sub(1, SPAWN_WHY) or nil rec.spawn_info = sinfo")
    assert "'no war party placed: ' .. tostring(why or 'no unit'):sub(1, 200)" not in s
    d = _src("ai-military-duty.lua")
    assert code_has(d, "flags = {'marauder', 'active_invader', 'invader_origin'}}")
    assert code_has(d, "error = ('no invaders placed: ' .. tostring(why or 'no unit')):sub(1, 600), spawn_info = brief}")
    assert code_has(d, "route = info.route, spawn_info = brief}")


@test("ai-spawn: create-unit first, then the native route; no arena clicks, the stale names not used")
def _():
    s, code = _src("ai-spawn.lua"), _code("ai-spawn.lua")
    assert "arena_spawn" not in code and "D_LOOK_ARENA_CREATURE" not in s.split("--@ module = true", 1)[1]
    assert "viewscreen_dwarfmodest:new" not in code
    spawn = s.split("local function spawn(o)", 1)[1]
    assert spawn.index("by_create_unit(o)") < spawn.index("pcall(by_native, o)")
    # (26 Nov 00:35) DF 53 places no arena unit from a simulated click: the arena route is gone
    for gone in ("by_arena", "simulateInput", "DWARF_ARENA", "arena_unit", "world.arena", "gametype", "_MOUSE_L"):
        assert gone not in code, gone
    assert code_has(s, "function spawn_units(o) local ok, ids, why, info = pcall(spawn, o)")


@test("ai-spawn: the native route is DFHack's fix of create-unit: units.create, units.active, the tile, the flags")
def _():
    s = _src("ai-spawn.lua")
    nat = s.split("local function by_native(o)", 1)[1].split("\nend\n", 1)[0]
    assert "pcall(dfhack.units.create, rid, castes[math.random(1, #castes)])" in nat
    assert "active:insert('#', u)" in nat and "df.global.world.units.active" in nat
    assert "local okp, pe = pcall(place, u, tiles[i])" in nat
    assert "math.min(o.count, #tiles)" in nat, "one unit a tile"
    place = s.split("local function place(u, t)", 1)[1].split("\nend\n", 1)[0]
    for k in ("u.pos.x, u.pos.y, u.pos.z = t.x, t.y, t.z", "pcall(dfhack.units.teleport, u, xyz2pos(t.x, t.y, t.z))",
              "dfhack.maps.getTileBlock(t.x, t.y, t.z)", "b.occupancy[t.x % 16][t.y % 16].unit = true",
              "u.flags1.inactive = false", "u.flags1.hidden_in_ambush = false", "u.flags2.calculated_nerves = false",
              "u.flags3.weight_computed = false"):
        assert k in place, k
    arm = s.split("local function arm(u, rows)", 1)[1].split("\nend\n", 1)[0]
    assert "pcall(dfhack.items.createItem, u, r[1], r[2], r[3], r[4], false)" in arm
    assert "pcall(dfhack.items.moveToInventory, it, u, df.inv_item_role_type[how[2]], bp)" in arm
    assert "pcall(dfhack.items.remove, it)" in arm, "a piece not put on is taken away"
    assert "WEAR = {WEAPON = {'GRASP', 'Weapon'}, SHIELD = {'GRASP', 'Strapped'}, ARMOR = {'UPPERBODY', 'Worn'}," in s
    # the units are armed after civ and flags are set; no historical figure
    spawn = s.split("local function spawn(o)", 1)[1]
    assert spawn.index("local ids = finish(units, o, true)") < spawn.index("arm_all(units, info)")
    assert "createNemesis(" not in _code("ai-spawn.lua") and "createFigure(" not in _code("ai-spawn.lua")


@test("ai-spawn: the DFHack names the native route uses exist in 53.17-r1 (df-names.json)")
def _():
    import json
    names = json.loads((ROOT / "tests" / "fixtures" / "df-names.json").read_text(encoding="utf-8"))
    api = names["dfhack"]
    for mod, fn in (("units", "create"), ("units", "teleport"), ("items", "createItem"), ("items", "moveToInventory"),
                    ("items", "remove"), ("maps", "getTileBlock")):
        assert fn in api[mod], (mod, fn)
    roles = names["types"]["inv_item_role_type"]["v"]
    assert "Weapon" in roles and "Worn" in roles and "Strapped" in roles
    occ = names["types"]["tile_occupancy"]["v"]
    assert "unit" in occ
    for f in ("inactive", "hidden_in_ambush", "active_invader", "invader_origin", "marauder"):
        assert f in names["types"]["unit_flags1"]["v"], f


# --- in a fake game (lupa) --------------------------------------------------------------------

FAKE = r"""
local src, opts = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    local n = #(list or {})
    local mt = {}
    local m = {}
    function m.resize(self, k) for i = k, rawget(self, '_n') - 1 do rawset(self, i, nil) end; rawset(self, '_n', k) end
    function m.insert(self, at, v) local k = rawget(self, '_n'); rawset(self, k, v); rawset(self, '_n', k + 1) end
    t._n = n
    mt.__len = function(self) return rawget(self, '_n') end
    mt.__index = m
    return setmetatable(t, mt)
end
local function ipairs0(t)          -- DFHack's ipairs walks a game vector from 0
    if type(t) == 'table' and rawget(t, '_n') then
        local i = -1
        return function() i = i + 1; if i < rawget(t, '_n') then return i, t[i] end end
    end
    return ipairs(t)
end
local W = {teleported = {}, items = {}, occ = {}, removed = 0}
local env = setmetatable({ipairs = ipairs0}, {__index = _G})
local active, all = vec(), vec()
local by_id = {}
local creatures = vec({{creature_id = 'TOAD', caste = vec({{caste_id = 'MALE', misc = {adult_size = 50}}})},
                       {creature_id = 'GOBLIN', caste = vec({{caste_id = 'FEMALE', misc = {adult_size = 6000}},
                                                             {caste_id = 'MALE', misc = {adult_size = 6000}}})}})
local weapons = vec({{id = 'ITEM_WEAPON_SPEAR', subtype = 3, minimum_size = 500, skill_ranged = -1},
                     {id = 'ITEM_WEAPON_BOW', subtype = 4, minimum_size = 1500, skill_ranged = 51},
                     {id = 'ITEM_WEAPON_SCIMITAR', subtype = 5, minimum_size = 3250, skill_ranged = -1},
                     {id = 'ITEM_WEAPON_MAUL', subtype = 6, minimum_size = 6250, skill_ranged = -1}})
local wdef = {}
for i = 0, #weapons - 1 do wdef[weapons[i].subtype] = weapons[i] end
local ents = {[314] = {id = 314, resources = {weapon_type = vec(opts.civ_weapons or {5, 4, 6})}},
              [7] = {id = 7, resources = {weapon_type = vec()}}}
local g = {unit_next_id = 500,
           world = {units = {active = active, all = all},
                    raws = {creatures = {all = creatures},
                            itemdefs = {weapons = weapons, armor = vec({{id = 'ITEM_ARMOR_MAIL_SHIRT', subtype = 1}}),
                                        helms = vec({{id = 'ITEM_HELM_HELM', subtype = 0}}),
                                        shields = vec({{id = 'ITEM_SHIELD_BUCKLER', subtype = 1}})}}}}
W.g, W.active, W.all, W.by_id = g, active, all, by_id
env.df = {global = g,
          unit = {find = function(id) return by_id[id] end},
          historical_entity = {find = function(id) return ents[id] end},
          itemdef_weaponst = {find = function(st) return wdef[st] end},
          item_type = {WEAPON = 24, ARMOR = 25, HELM = 28, SHIELD = 27, PANTS = 29, SHOES = 26, GLOVES = 30, AMMO = 38},
          inv_item_role_type = {Weapon = 1, Worn = 2, Strapped = 10},
          profession = {STANDARD = 103, SOLDIER = 109},
          tiletype = {attrs = setmetatable({}, {__index = function(_, tt) return {shape = tt} end})},
          tiletype_shape = {attrs = {FLOOR = {walkable = true}, WALL = {walkable = false}}}}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local TYPE_OF = {[24] = 'WEAPON', [25] = 'ARMOR', [28] = 'HELM', [27] = 'SHIELD'}
-- the goblin body: upper and lower body, head, two hands, two feet
local function body()
    local parts = {}
    for _, p in ipairs({{'UB', 'UPPERBODY'}, {'LB', 'LOWERBODY'}, {'HD', 'HEAD'}, {'RH', 'GRASP'}, {'LH', 'GRASP'},
                        {'RF', 'STANCE'}, {'LF', 'STANCE'}}) do
        table.insert(parts, {token = p[1], flags = {[p[2]] = true}})
    end
    return {body_plan = {body_parts = vec(parts)}, components = {body_part_status = vec({})}}
end
local function new_unit(race, caste)
    if opts.create_error then error('boom in create') end
    if opts.create_nil then return nil end
    local id = g.unit_next_id
    g.unit_next_id = id + 1
    local u = {id = id, race = race, caste = caste, pos = {x = -30000, y = -30000, z = -30000}, civ_id = -1,
               profession = 103, flags1 = {inactive = true}, flags2 = {}, flags3 = {}, inventory = {},
               military = {uniform_drop = vec({1})}, animal = {leave_countdown = 0, vanish_countdown = 0},
               body = body(), name = {has_name = true}}
    by_id[id] = u
    all:insert('#', u)
    return u
end
local blocks = {}
env.dfhack = {
    isMapLoaded = function() return true end,
    maps = {isValidTilePos = function(x, y, z) return x >= 0 and y >= 0 and x < 200 and y < 200 end,
            getTileType = function(x, y, z) if x == 101 then return 'WALL' end return 'FLOOR' end,
            getTileFlags = function(x, y, z) return {outside = true, flow_size = 0} end,
            getWalkableGroup = function(p) return 1 end,
            getTileBlock = function(x, y, z)
                local k = (x // 16) .. ',' .. (y // 16) .. ',' .. z
                blocks[k] = blocks[k] or {occupancy = setmetatable({}, {__index = function(t, i)
                    local row = setmetatable({}, {__index = function(r, j) local o = {}; rawset(r, j, o); return o end})
                    rawset(t, i, row); return row end})}
                return blocks[k]
            end},
    buildings = {findAtTile = function() return nil end},
    matinfo = {find = function(s) if s == 'INORGANIC:IRON' then return {type = 0, index = 8} end return nil end},
    units = {teleport = function(u, p)
                 assert(u.pos.x == p.x and u.pos.y == p.y and u.pos.z == p.z, 'teleport from off the map')
                 table.insert(W.teleported, u.id)
                 if opts.teleport_false then return false end
                 W.occ[p.x .. ',' .. p.y .. ',' .. p.z] = (W.occ[p.x .. ',' .. p.y .. ',' .. p.z] or 0) + 1
                 return true
             end},
    items = {createItem = function(u, t, st, mt, mi, no_floor)
                 if opts.items_error then error('createItem failed') end
                 local it = {id = 7000 + #W.items, type = t, subtype = st, mat_type = mt, mat_index = mi, maker = u.id}
                 table.insert(W.items, it)
                 return {it}
             end,
             moveToInventory = function(it, u, role, bp)
                 if opts.refuse_shield and it.type == 27 then return false end
                 table.insert(u.inventory, {item = it, mode = role, body_part_id = bp})
                 return true
             end,
             remove = function(it) it.removed = true; W.removed = W.removed + 1 end},
}
if not opts.no_create then env.dfhack.units.create = new_unit end
W.blocks = blocks
W.TYPE_OF = TYPE_OF
env.reqscript = function(n)
    if n == 'modtools/create-unit' then
        if opts.cu_mode == 'equip_refused' then
            return {createUnit = function(race, caste, pos, range, lt, age, dom, civ, grp, ern, nick, van, qty, equip)
                if equip then error('Invalid equipment material: IRON') end
                local us = {}
                for i = 1, qty do us[i] = {id = 900 + i, flags1 = {}, civ_id = -1} end
                W.made = us
                return us
            end}
        end
        return {createUnit = function() error('create-unit.lua:164: Cannot read field world.arena_spawn: not found') end}
    end
    error('reqscript ' .. tostring(n))
end
assert(load(src, 'ai-spawn', 't', env))()
return env, W
"""


def _lua(**opts):
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    _lua.rt = lua
    env, w = lua.execute(FAKE, _src("ai-spawn.lua"), _t(opts))
    return env, w


def _t(d):
    rt = _lua.rt
    if isinstance(d, dict):
        return rt.table_from({k: _t(v) for k, v in d.items()})
    if isinstance(d, list):
        return rt.table_from([_t(v) for v in d])
    return d


def _vals_list(t):
    return [t[i] for i in range(1, len(t) + 1)]


def _inv(w, u):
    """A unit's inventory as (kind, subtype, body part, role) rows."""
    return [(w.TYPE_OF[i.item.type], i.item.subtype, i.body_part_id, i.mode) for i in _vals_list(u.inventory)]


EQUIP = ["ITEM_WEAPON_SPEAR:INORGANIC:IRON", "ITEM_ARMOR_MAIL_SHIRT:INORGANIC:IRON",
         "ITEM_HELM_HELM:INORGANIC:IRON", "ITEM_SHIELD_BUCKLER:INORGANIC:IRON"]
SPEC = {"race": "GOBLIN", "count": 4, "pos": {"x": 120, "y": 80, "z": 5}, "spread": 2, "civ_id": 314,
        "flags": ["active_invader", "invader_origin"], "equip": EQUIP}


@test("native (Lua): create-unit stale: dfhack.units.create makes them, active, on their tiles round pos, invaders")
def _():
    need_lua()
    env, w = _lua()
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is not None, why
    assert _vals_list(ids) == [500, 501, 502, 503], _vals_list(ids)
    assert info.route == "native" and "arena_spawn" in info.cu_error, dict(info)
    assert (info.asked, info.made, info.placed) == (4, 4, 4) and info.capped is None, dict(info)
    assert w.active._n == 4 and w.all._n == 4
    tiles = set()
    for i in range(4):
        u = w.active[i]
        assert u.race == 1 and abs(u.pos.x - 120) <= 2 and abs(u.pos.y - 80) <= 2 and u.pos.z == 5, dict(u.pos)
        tiles.add((u.pos.x, u.pos.y))
        assert u.civ_id == 314 and u.flags1.active_invader and u.flags1.invader_origin and u.flags1.marauder
        assert u.flags1.inactive is False and u.flags1.hidden_in_ambush is False
        assert u.flags2.calculated_bodyparts is False and u.flags3.weight_computed is False
    assert len(tiles) == 4, "one unit a tile"
    assert len(w.teleported) == 4 and sum(w.occ.values()) == 4, "the tiles' occupancy set by teleport"


@test("native (Lua): armed: the civ's weapon in a hand, the mail shirt, the helm, the buckler strapped on the other hand")
def _():
    need_lua()
    env, w = _lua()
    ids, why, info = env.spawn_units(_t(SPEC))
    assert info.equipped is True and info.armed == 4 and info.equip_error is None, dict(info)
    for i in range(4):
        u = w.active[i]
        # civ 314 makes no spear: its scimitar (the bow is ranged, the maul too big for a goblin)
        assert _inv(w, u) == [("WEAPON", 5, 3, 1), ("ARMOR", 1, 0, 2), ("HELM", 0, 2, 2), ("SHIELD", 1, 4, 10)], _inv(w, u)
        assert u.military.uniform_drop._n == 0
    env, w = _lua(civ_weapons=[3, 5])                    # the civ makes spears: the spear asked
    env.spawn_units(_t(SPEC))
    assert _inv(w, w.active[0])[0] == ("WEAPON", 3, 3, 1)
    env, w = _lua(civ_weapons=[4])                       # only bows: the one asked
    env.spawn_units(_t(SPEC))
    assert _inv(w, w.active[0])[0] == ("WEAPON", 3, 3, 1)


@test("native (Lua): arming fails: placed unarmed, said why; a piece refused is taken away")
def _():
    need_lua()
    env, w = _lua(items_error=True)
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is not None and len(ids) == 4 and info.equipped is False and info.armed == 0, dict(info)
    assert "createItem WEAPON" in info.equip_error and "createItem SHIELD" in info.equip_error, info.equip_error
    env, w = _lua(refuse_shield=True)
    ids, why, info = env.spawn_units(_t(SPEC))
    assert info.equipped is True and info.equip_error == "SHIELD not put on: refused", dict(info)
    assert w.removed == 4 and len(_inv(w, w.active[0])) == 3
    env, w = _lua()
    ids, why, info = env.spawn_units(_t({k: v for k, v in SPEC.items() if k != "equip"}))
    assert info.equipped is False and info.equip_error is None and len(w["items"]) == 0, dict(info)


@test("native (Lua): teleport refuses: the occupancy set by hand; more units than tiles: one a tile")
def _():
    need_lua()
    env, w = _lua(teleport_false=True)
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is not None and info.placed == 4, dict(info)
    u = w.active[0]
    b = w.blocks[f"{u.pos.x // 16},{u.pos.y // 16},5"]
    assert b.occupancy[u.pos.x % 16][u.pos.y % 16].unit is True
    env, w = _lua()
    ids, why, info = env.spawn_units(_t({"race": "GOBLIN", "count": 30, "pos": {"x": 120, "y": 80, "z": 5}, "spread": 1}))
    assert len(ids) == 9 and info.capped == 9 and info.asked == 30, dict(info)


@test("native (Lua): no units.create, an error in it, no unit: nil and both routes' reasons; nothing half-made")
def _():
    need_lua()
    for opts, words in (({"no_create": True}, "no dfhack.units.create"), ({"create_error": True}, "boom in create"),
                        ({"create_nil": True}, "made no unit")):
        env, w = _lua(**opts)
        ids, why, info = env.spawn_units(_t(SPEC))
        assert ids is None and words in why and "create-unit: " in why and "native: " in why, (opts, why)
        assert info.route == "none" and words in info.native_error and "arena_spawn" in info.cu_error, dict(info)
        assert w.active._n == 0
        b = env.brief(info)
        assert b.route == "none" and b.rows is None, dict(b)


@test("create-unit (Lua): when it works it is used (equipment refused: placed unarmed); garbage in: nil, no throw")
def _():
    need_lua()
    env, w = _lua(cu_mode="equip_refused")
    ids, why, info = env.spawn_units(_t(SPEC))
    assert ids is not None and len(ids) == 4 and info.route == "create-unit", why
    assert info.equipped is False and "IRON" in info.equip_error, dict(info)
    assert w.active._n == 0, "dfhack.units.create left alone"
    assert all(u.civ_id == 314 and u.flags1.active_invader and not u.flags1.marauder for u in w.made.values())
    for bad in (None, 5, _t({"race": "GOBLIN"}), _t({"pos": {"x": 1, "y": 1, "z": 1}})):
        r = env.spawn_units(bad)
        assert r[0] is None and isinstance(r[1], str), r
    env, w = _lua()
    ids, why, info = env.spawn_units(_t({**SPEC, "race": "NOSUCH"}))
    assert ids is None and "no creature NOSUCH" in why, why


@test("every changed Lua file compiles under Lua 5.3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    chk = LuaRuntime().eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
    for n in CHANGED:
        ok, err = chk(_src(n), n)
        assert ok, (n, err)


if __name__ == "__main__":
    finish()
