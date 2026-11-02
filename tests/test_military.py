"""Tests for the pure part of lua/ai-military.lua (who joins a squad), in a
real Lua engine (pip install lupa).

    python tests/test_military.py
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

LUA = LuaRuntime(unpack_returned_tuples=True)
M = LUA.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-military', 't', env))()
return env
""", (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))


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


def cands(*rows):
    t = LUA.table()
    for i, (uid, combat, craft) in enumerate(rows, 1):
        t[i] = LUA.table_from({"id": uid, "combat": combat, "best_craft": craft})
    return t


def ids(picked):
    return [picked[i].id for i in range(1, len(picked) + 1)]


@test("fighters are picked first")
def _():
    assert ids(M.pick_soldiers(cands((1, 0, 3), (2, 8, 3), (3, 4, 3)), 2)) == [2, 3]


@test("the legendary crafter stays home; ties go to the lower id")
def _():
    assert ids(M.pick_soldiers(cands((1, 0, 15), (2, 0, 2), (3, 0, 2)), 2)) == [2, 3]


@test("dwarves who long to fight or train come before a slightly better fighter")
def _():
    t = cands((1, 5, 3), (2, 0, 3), (3, 2, 3))
    t[2].wants_fight = True
    assert ids(M.pick_soldiers(t, 2)) == [2, 1]
    v = cands((1, 60, 3), (2, 0, 3))                       # (0.104.64) before a veteran too
    v[2].wants_fight = True
    assert ids(M.pick_soldiers(v, 1)) == [2]


@test("(0.104.138) the badly keen come first, keenest first; the avoided are never picked")
def _():
    t = cands((1, 60, 3), (2, 0, 3), (3, 0, 3))
    t[1].fight_focus = -1500                              # a veteran just past the wanting line
    t[1].wants_fight = True
    t[2].fight_focus = -12000
    t[3].fight_focus = -30000
    assert ids(M.pick_soldiers(t, 3)) == [3, 2, 1]
    avoid = LUA.table_from({3: True})
    assert ids(M.pick_soldiers(t, 3, avoid)) == [2, 1]


@test("asking for more than there are gives everyone, never more")
def _():
    assert ids(M.pick_soldiers(cands((5, 1, 1)), 4)) == [5]
    assert ids(M.pick_soldiers(cands(), 3)) == []



@test("uniform template: leather or metal as asked, melee before crossbows; else the first")
def _():
    names = LUA.table_from(["Crossbows, leather armor", "Melee, leather armor", "Crossbows, metal armor",
                            "Melee, metal armor"])
    assert M.pick_template(names, "leather") == 2
    assert M.pick_template(names, "metal") == 4
    assert M.pick_template(LUA.table_from(["Guards"]), "metal") == 1
    assert M.pick_template(names, "metal", True) == 3 and M.pick_template(names, "leather", True) == 1


UNIFORM_FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end,
                   erase = function(self, at)
                       local n = #self
                       for i = at, n - 2 do self[i] = self[i + 1] end
                       self[n - 1] = nil end}})
end
local function cats() local c = {}; for i = 0, 2 do c[i] = vec() end; return c end
local function template(name, it)
    local types, subs, info = cats(), cats(), cats()
    types[0] = vec({it}); subs[0] = vec({3}); info[0] = vec({{material_class = 7, mattype = -1, matindex = -1,
        item_color = -1, indiv_choice = {whole = 0}}})
    return {name = name, uniform_item_types = types, uniform_item_subtypes = subs, uniform_item_info = info,
            flags = {whole = 1}}
end
local fort = {uniforms = vec({template('Melee, leather armor', 10), template('Melee, metal armor', 20)})}
local function position() return {occupant = -1, equipment = {uniform = cats(), flags = {whole = 0}}} end
local sq = {id = 32, positions = vec({position(), position()}), ammo = {update = {}}}
local persist = {}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.df = {uniform_category = {_last_item = 2},
          squad_uniform_spec = {new = function() return {indiv_choice = {whole = 0}, delete = function() end} end},
          historical_entity = {find = function() return fort end},
          global = {plotinfo = {equipment = {update = {}}, group_id = 1}}}
env.dfhack = {persistent = {getSiteData = function(k, d) return persist[k] or d end,
                            saveSiteData = function(k, v) persist[k] = v end}}
assert(load(src, 'ai-military', 't', env))()
env.fort_squad = function(id) return id == 32 and sq or nil end
return env, sq
"""


@test("uniforms: a squad without one gets the template on every place; the AI may change its own, never yours")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, sq = lua.execute(UNIFORM_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    d = env.set_uniform(32, "leather", True)
    assert d.ok and d.dry_run and d.template == "Melee, leather armor" and sq.positions[0].equipment.uniform[0][0] is None, dict(d)
    r = env.set_uniform(32, "leather", False)
    assert r.ok and r["items"] == 2, dict(r)
    spec = sq.positions[1].equipment.uniform[0][0]
    assert spec.item == -1 and spec.item_type == 10 and spec.material_class == 7, dict(spec)
    assert sq.positions[1].equipment.flags.whole == 1, "flags"
    again = env.set_uniform(32, "leather", False)
    assert not again.ok and "already wears" in again.error, dict(again)
    m = env.set_uniform(32, "metal", False)
    u0 = sq.positions[0].equipment.uniform[0]
    assert m.ok and m.replaced and u0[0] is not None and u0[1] is None, dict(m)
    assert sq.positions[0].equipment.uniform[0][0].item_type == 20, "metal"
    # a uniform set by someone else is left alone
    lua2 = LuaRuntime(unpack_returned_tuples=True)
    env2, sq2 = lua2.execute(UNIFORM_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    lua2.eval('function(v, x) v:insert("#", x) end')(sq2.positions[0].equipment.uniform[0],
                                                    lua2.table_from({"item_type": 5}))
    r = env2.set_uniform(32, "metal", False)
    assert not r.ok and "someone set" in r.error, dict(r)


@test("uniform weapon: every place asks for the one weapon kind; only on a uniform the AI set")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, sq = lua.execute(UNIFORM_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    lua.execute("""local env = ... ; env.df.uniform_category.weapon = 0 ; env.df.item_type = {WEAPON = 24}
        env.df.global.world = {raws = {itemdefs = {weapons = {[0] = {id = 'ITEM_WEAPON_PICK', subtype = 6},
                                                           [1] = {id = 'ITEM_WEAPON_AXE_BATTLE', subtype = 7}}}}}""", env)
    r = env.set_uniform_weapon(32, "ITEM_WEAPON_AXE_BATTLE", False)
    assert not r.ok and "not a uniform the AI set" in r.error, dict(r)
    assert env.set_uniform(32, "leather", False).ok                       # template: item type 10 in category 0
    r = env.set_uniform_weapon(32, "ITEM_WEAPON_AXE_BATTLE", False)
    assert r.ok and r.places == 2, dict(r)
    for p in (0, 1):
        v = sq.positions[p].equipment.uniform[0]
        assert v[0].item_type == 24 and v[0].item_subtype == 7 and v[1] is None, (v[0].item_type, v[1])
    assert "|weapon:ITEM_WEAPON_AXE_BATTLE" in env.ai_uniform_names()["32"]
    assert not env.set_uniform_weapon(32, "ITEM_WEAPON_NOPE", False).ok
    again = env.set_uniform(32, "leather", False)                         # same template: still "already wears"
    assert not again.ok and "already wears" in again.error, dict(again)

STRAY_FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v)
                       local n = #self
                       if at == '#' then at = n end
                       for i = n, at + 1, -1 do self[i] = self[i - 1] end
                       self[at] = v end,
                   erase = function(self, at)
                       local n = #self
                       for i = at, n - 2 do self[i] = self[i + 1] end
                       self[n - 1] = nil end}})
end
local function item(id, flags, holder) return {id = id, flags = flags or {}, holder = holder} end
local items = {WEAPON = vec({item(5), item(7), item(9), item(11, {in_inventory = true}, 'u'), item(13, {owned = true}),
                             item(15), item(17), item(19)}),
               ARMOR = vec(), HELM = vec({item(20), item(22)}), PANTS = vec(), GLOVES = vec(), SHOES = vec(), SHIELD = vec()}
local function lists(w, h)
    return {WEAPON = vec(w), ARMOR = vec(), HELM = vec(h), PANTS = vec(), GLOVES = vec(), SHOES = vec(), SHIELD = vec()}
end
-- 5 claimed by a soldier (assigned), 7 assigned to no one, 9 on no list,
-- 11 held by a dwarf, 13 owned, 15 a woodcutter's axe, 17 unassigned already;
-- helm 20 assigned to no one, helm 22 on no list (reported, left alone)
-- 19 new from the forge, still unmanifested (not stray)
local eq = {items_assigned = lists({5, 7}, {20}), items_unassigned = lists({3, 17, 30}), update = {},
            items_unmanifested = lists({19}, {}),
            work_weapons = vec({15})}
local spec = {assigned = vec({5})}
local pos = {occupant = 1, equipment = {assigned_items = vec({5}), uniform = {[0] = vec({spec})}}}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.df = {uniform_category = {_last_item = 0},
          global = {plotinfo = {equipment = eq, group_id = 1},
                    world = {squads = {all = vec({{positions = vec({pos})}})}, items = {other = items}}}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
              items = {getHolderUnit = function(it) return it.holder end}}
assert(load(src, 'ai-military', 't', env))()
return env, eq
"""


@test("stray gear (0.104.58): gear assigned to no one or on no list goes back on the unassigned list, in order")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq = lua.execute(STRAY_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    r = env.stray_report()
    assert r.n == 4 and r.orphan.WEAPON == 1 and r.unlisted.WEAPON == 1 and r.orphan.HELM == 1 and r.unlisted.HELM == 1, r.n
    n = lua.eval("function(v) return #v end")
    seq = lambda v: [v[i] for i in range(n(v))]
    d = env.free_stray_gear(True, 100)
    assert d.ok and d.dry_run and d.would_free == 3 and n(eq.items_unassigned.WEAPON) == 3, dict(d)
    f = env.free_stray_gear(False, 100)
    assert f.ok and f.freed == 3 and f.by_kind.WEAPON == 2 and f.by_kind.HELM == 1, dict(f)
    una, asg = seq(eq.items_unassigned.WEAPON), seq(eq.items_assigned.WEAPON)
    assert una == [3, 7, 9, 17, 30], una                 # in id order; never 11 (held), 13 (owned), 15 (a tool)
    assert asg == [5], asg                               # the soldier's own axe stays his
    assert n(eq.items_assigned.HELM) == 0 and seq(eq.items_unassigned.HELM) == [20]
    assert eq.update.weapon and eq.update.helm, "DF asked to redo its assignments"
    assert env.stray_report().n == 1 and env.free_stray_gear(False, 100).freed == 0, "only the unlisted helm: left"


@test("stray gear (0.104.58): the limit caps one call")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq = lua.execute(STRAY_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    assert env.free_stray_gear(False, 1).freed == 1 and env.stray_report().n == 3


ARMS_FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v)
                       local n = #self
                       if at == '#' then at = n end
                       for i = n, at + 1, -1 do self[i] = self[i - 1] end
                       self[at] = v end,
                   erase = function(self, at)
                       local n = #self
                       for i = at, n - 2 do self[i] = self[i + 1] end
                       self[n - 1] = nil end}})
end
local where = {}
local function axe(id, sub, x, flags) local it = {id = id, flags = flags or {}, sub = sub}
    function it:getSubtype() return self.sub end
    where[id] = {x, 0, 0}
    return it end
-- 31 an axe far off, 32 a near axe, 33 forbidden, 34 a spear, 35 a crossbow, 36 off the list
local items = {WEAPON = vec({axe(31, 1, 50), axe(32, 1, 3), axe(33, 1, 1, {forbid = true}), axe(34, 4, 2),
                             axe(35, 6, 2), axe(36, 1, 1)})}
local function lists(w) return {WEAPON = vec(w)} end
local eq = {items_assigned = lists({}), items_unassigned = lists({31, 32, 33, 34, 35}), items_unmanifested = lists({}),
            update = {}, work_weapons = vec({})}
local function place(occ, sub, given)
    return {occupant = occ, equipment = {assigned_items = vec(given and {given} or {}),
            uniform = {[0] = vec({{item_type = 24, item_subtype = sub, assigned = vec(given and {given} or {})}})}}}
end
-- squad 7: two axemen without, one with an axe already; squad 8: a crossbowman without
local sq7 = {id = 7, positions = vec({place(100, 1), place(101, 1), place(102, 1, 99)})}
local sq8 = {id = 8, positions = vec({place(103, 6)})}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.df = {uniform_category = {_last_item = 0, weapon = 0}, item_type = {WEAPON = 24},
          squad = {find = function(id) return id == 7 and sq7 or id == 8 and sq8 or nil end},
          historical_figure = {find = function(id) return {unit_id = id} end},
          unit = {find = function(id) return {id = id} end},
          historical_entity = {find = function() return {squads = vec({7, 8})} end},
          global = {plotinfo = {equipment = eq, group_id = 1},
                    world = {squads = {all = vec({sq7, sq8})}, items = {other = items},
                             raws = {itemdefs = {weapons = vec({{id = 'ITEM_WEAPON_CROSSBOW', subtype = 6}})}}}}}
env.dfhack = {persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end},
              items = {getHolderUnit = function() return nil end,
                       getPosition = function(it) local w = where[it.id]; return w[1], w[2], w[3] end,
                       getDescription = function(it) return 'item ' .. it.id end},
              units = {getPosition = function(u) return 0, 0, 0 end},
              maps = {canWalkBetween = function(a, b) return true end}}
assert(load(src, 'ai-military', 't', env))()
return env, eq, sq7, sq8
"""


@test("assign weapons (0.104.60): empty weapon places get the nearest free weapon of their kind, as DF assigns")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq, sq7, sq8 = lua.execute(ARMS_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    n = lua.eval("function(v) return #v end")
    seq = lambda v: [v[i] for i in range(n(v))]
    assert env.weapon_gaps() == (3, 1)                   # 3 empty; one melee place has its axe
    d = env.assign_weapons(True, 10)
    assert d.ok and d.dry_run and d.would_assign == 3 and seq(eq.items_unassigned.WEAPON) == [31, 32, 33, 34, 35]
    r = env.assign_weapons(False, 10)
    assert r.ok and r.assigned == 3, dict(r)
    p0, p1 = sq7.positions[0].equipment, sq7.positions[1].equipment
    assert seq(p0.uniform[0][0].assigned) == [32] and seq(p0.assigned_items) == [32]    # the nearest axe first
    assert seq(p1.uniform[0][0].assigned) == [31]                                       # never the forbidden one
    assert seq(sq8.positions[0].equipment.uniform[0][0].assigned) == [35]               # a crossbow for the crossbowman
    assert seq(sq7.positions[2].equipment.uniform[0][0].assigned) == [99]               # his own axe kept
    assert seq(eq.items_unassigned.WEAPON) == [33, 34] and seq(eq.items_assigned.WEAPON) == [31, 32, 35]
    assert env.weapon_gaps() == (0, 3) and env.assign_weapons(False, 10).rejected     # nothing to hand out: refused


@test("assign weapons (0.104.60): the limit caps one call")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq, sq7, sq8 = lua.execute(ARMS_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    assert env.assign_weapons(False, 1).assigned == 1 and env.weapon_gaps()[0] == 2


@test("assign weapons (0.104.80): the ledger says what became of each weapon given")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq, sq7, sq8 = lua.execute(ARMS_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    r = env.assign_weapons(False, 10)
    assert r.assigned == 3 and r.ledger.booked == 0
    p0 = sq7.positions[0].equipment
    spec = p0.uniform[0][0].assigned
    spec.erase(spec, 0)                                   # the game takes axe 32 off the entry and the place
    p0.assigned_items.erase(p0.assigned_items, 0)
    r2 = env.assign_weapons(False, 10)
    led = r2.ledger
    assert led.booked == 3 and led.kept == 2, (led.booked, led.kept)
    keys = list(dict(led.why).keys())
    assert len(keys) == 1 and keys[0].startswith("off the entry and the place; assigned; routine then"), keys
    assert r2.rejected                                    # still on DF's assigned list: not free to hand out


@test("assign weapons (0.104.80): a weapon entry asking for a colour is put to any colour, and DF told to re-equip")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq, sq7, sq8 = lua.execute(ARMS_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    for p in (sq7.positions[0], sq7.positions[1], sq7.positions[2], sq8.positions[0]):
        p.equipment.uniform[0][0].color = -1
    sq7.positions[1].equipment.uniform[0][0].color = 0          # set_uniform_weapon's entry before 0.104.80
    assert env.fix_weapon_colours(True) == 1 and sq7.positions[1].equipment.uniform[0][0].color == 0
    r = env.assign_weapons(False, 10)
    assert r.colours_fixed == 1 and sq7.positions[1].equipment.uniform[0][0].color == -1, dict(r)
    assert eq.update.weapon is True
    assert env.assign_weapons(False, 10).colours_fixed is None   # (refused now: nothing left to do)


@test("hold the gate (0.104.83): a defend order on the gate guard burrow replaces the AI's orders, counts as the AI's")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, eq, sq7, sq8 = lua.execute(ARMS_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    lua.execute("""local env, sq7, sq8 = ...
        local function vec(list)
            local t = {}
            for i, v in ipairs(list or {}) do t[i - 1] = v end
            return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
                __index = {insert = function(self, at, v) self[#self] = v end,
                           erase = function(self, at) local n = #self; for i = at, n - 2 do self[i] = self[i + 1] end; self[n - 1] = nil end}})
        end
        local DEF = {}
        DEF.new = function() return setmetatable({burrows = vec({}), _defend = true}, {__index = {delete = function() end}}) end
        DEF.is_instance = function(self, o) return type(o) == 'table' and o._defend == true end
        env.df.squad_order_defend_burrowsst = DEF
        env.df.global.plotinfo.burrows = {list = vec({{id = 3, name = 'AI gate guard'}, {id = 4, name = 'mine'}})}
        sq7.orders = vec({setmetatable({title = 'AI overseer'}, {__index = {delete = function() end}})})
        sq8.orders = vec({setmetatable({title = 'the player'}, {__index = {delete = function() end}})})
        """, env, sq7, sq8)
    n = lua.eval("function(v) return #v end")
    r = env.defend(7, 3)
    assert r.ok and r.replaced == 1 and n(sq7.orders) == 1 and sq7.orders[0].burrows[0] == 3, dict(r)
    assert env.defend(7, 3).rejected                                       # already holding
    assert env.defend(8, 3).rejected and n(sq8.orders) == 1                # the player's order kept
    r = env.orders(7, None, True)
    assert r.ok and r.cleared == 1 and n(sq7.orders) == 0                  # the recall clears it: it is the AI's


@test("adopt: a copied crossbow uniform becomes the AI's by its template; back to melee drops the bolts")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, sq = lua.execute(UNIFORM_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    lua.execute("""local env, sq = ...
        env.df.entity_material_category = {Armor = 16}
        env.df.item_type = {WEAPON = 24}
        env.dfhack.items = {getSubtypeDef = function(t, st) return st == 3 and {id = 'ITEM_WEAPON_CROSSBOW'} or nil end}
        local fort = env.df.historical_entity.find()
        local n = #fort.uniforms
        for _, name in ipairs({'Crossbows, leather armor', 'Crossbows, metal armor'}) do
            local t = {}
            for k, v in pairs(fort.uniforms[0]) do t[k] = v end
            t.name = name
            fort.uniforms[n] = t; n = n + 1
        end
        -- the squad's uniform: metal armour (class 16) and a crossbow (weapon subtype 3)
        for p = 0, 1 do
            local u = sq.positions[p].equipment.uniform
            u[0]:insert('#', {item_type = 13, item_subtype = -1, material_class = 16})
            u[1]:insert('#', {item_type = 24, item_subtype = 3, material_class = -1})
        end
        sq.ammo.ammunition = {[0] = {delete = function() end}}
        setmetatable(sq.ammo.ammunition, getmetatable(sq.positions))""", env, sq)
    d = env.adopt_uniform(32, True)
    assert d.ok and d.dry_run and d.uniform == "Crossbows, metal armor", dict(d)
    r = env.adopt_uniform(32, False)
    assert r.ok and env.ai_uniform_names()["32"] == "Crossbows, metal armor", dict(r)
    again = env.adopt_uniform(32, False)
    assert not again.ok and "already the AI's" in again.error, dict(again)
    ax = env.set_uniform_weapon(32, "ITEM_WEAPON_AXE_BATTLE", False)    # (0.100) a crossbow squad keeps crossbows
    assert not ax.ok and "crossbow squad" in ax.error, dict(ax)
    m = env.set_uniform(32, "metal", False)          # back to melee
    assert m.ok and m.bolts_cleared and m.template == "Melee, metal armor", dict(m)
    assert lua.eval("function(v) return #v end")(sq.ammo.ammunition) == 0


@test("barracks: a squad given one to train in through DFHack's updateRoomAssignments; not twice; only a barracks")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local zone = {id = 900, type = 3, squad_room_info = {}}
local other = {id = 901, type = 1, squad_room_info = {}}
local range = {id = 902, type = 4, squad_room_info = {}}
env.df = {civzone_type = {Barracks = 3, ArcheryRange = 4},
          squad = {find = function(id) return id == 32 and {id = 32} or nil end},
          building = {find = function(id) return id == 900 and zone or id == 901 and other or id == 902 and range or nil end},
          global = {world = {buildings = {other = {ZONE_BARRACKS = {zone}}}}}}
env.CALLS = {}
env.dfhack = {military = {updateRoomAssignments = function(sid, zid, flags)
    table.insert(env.CALLS, flags)
    local z = zid == 902 and range or zone
    table.insert(z.squad_room_info, {squad_id = sid, mode = flags})
end}}
assert(load(src, 'ai-military', 't', env))()
return env
""", (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    assert env.assign_barracks(32, 901, False).error == "that is not a barracks zone"
    assert env.assign_barracks(7, 900, False).error == "no such squad"
    r = env.assign_barracks(32, 900, False)
    assert r.ok and env.CALLS[1] == 14, (dict(r), env.CALLS[1])           # train + indiv_eq + squad_eq, no sleep
    assert env.assign_barracks(32, 900, False).error == "the squad already uses it"
    r = env.assign_barracks(32, 902, False)                              # an archery range: train only
    assert r.ok and env.CALLS[2] == 2, (dict(r), env.CALLS[2])
    rep = env.barracks_report()
    assert rep[1].id == 900 and rep[1].squads[1] == 32


@test("defence test: invaders set down 15+ tiles out with a path to the depot; never during a real threat")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local units = {}
env.UNITS = units
env.df = {global = {world = {buildings = {other = {TRADE_DEPOT = {{centerx = 50, centery = 50, z = 10}}}},
                              units = {active = units},
                              entities = {all = {{id = 7, type = 0, entity_raw = {code = 'EVIL'}}}}}},
          historical_entity_type = {Civilization = 0}}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.dfhack = {
    maps = {getTileFlags = function(x, y, z)
                return {outside = true, hidden = false, flow_size = (x == 65 and y == 50) and 3 or 0}
            end,
            canWalkBetween = function(a, b) return a.x ~= 50 + 15 or a.y ~= 50 end},
    units = {isActive = function() return true end, isDead = function() return false end,
             isDanger = function(u) return u.danger end, isHidden = function() return false end},
}
env.reqscript = function(name)
    return {createUnit = function(race, caste, pos, rng, lt, age, dom, civ, grp, ern, nick, van, n, eq, sk, pr, cp, flags)
        env.MADE = {race = race, civ = civ, n = n, flags = flags, pos = pos}
        for i = 1, n do table.insert(units, {id = 100 + i}) end
    end}
end
assert(load(src, 'ai-military', 't', env))()
return env
""", (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    d = env.spawn_test_threat(3, None, True)
    assert d.ok and d.dry_run and d.spot.x == 35 and d.spot.y == 50 and d.civ == 7, dict(d.spot)   # (65,50) is water
    r = env.spawn_test_threat(3, None, False)
    assert r.ok and r.count == 3 and env.MADE.race == "GOBLIN" and env.MADE.civ == 7, dict(r)
    assert list(env.MADE.flags.values()) == ["marauder", "active_invader", "invader_origin"]
    env.UNITS[1].danger = True
    r = env.spawn_test_threat(3, None, False)
    assert r.ok is False and "already a threat" in r.error


POST_FAKE = r"""
local src, spec = ...
local real_ipairs = ipairs
local function vec(list)
    local t = {_v = true}
    for i, v in real_ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v) self[#self] = v end,
                   erase = function(self, at)
                       local n = #self
                       for i = at, n - 2 do self[i] = self[i + 1] end
                       self[n - 1] = nil end}})
end
-- DFHack's ipairs walks a game vector from 0
local function ipairs0(t)
    if type(t) == 'table' and rawget(t, '_v') then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return real_ipairs(t)
end
local positions = vec({{id = 1, code = 'MILITIA_COMMANDER', squad_size = 10, number = 1, responsibilities = {}},
                       {id = 2, code = 'MILITIA_CAPTAIN', squad_size = 10, number = spec.number or -1,
                        responsibilities = {}}})
local assignments = vec({{id = 50, position_id = 1, histfig = spec.commander and 900 or -1, squad_id = 32,
                          flags = {active = true}}})
local fort = {id = 77, squads = vec({32}), positions = {own = positions, assignments = assignments,
              next_assignment_id = 60}, assignments_by_type = vec({vec()})}   -- (0.104.138) on the entity
local made = {}
local env = setmetatable({ipairs = ipairs0}, {__index = _G})
env.df = {
    entity_position_assignment = {new = function() return {flags = {}, delete = function() end} end},
    global = {plotinfo = {group_id = 77, equipment = {update = {}}}, cur_year = 61},
    historical_entity = {find = function() return fort end},
    historical_figure = {find = function(id) return {id = id, entity_links = vec()} end},
    uniform_category = {_last_item = 0},
    squad = {find = function() return nil end},
}
env.dfhack = {
    units = {getCitizens = function() return {} end, getReadableName = function() return 'Urist' end},
    military = {makeSquad = function(aid)
        if spec.no_squad then return nil end
        local sq = {id = 40, positions = vec({{occupant = -1}}), ammo = {update = {}}}
        made.aid = aid
        return sq
    end, getSquadName = function() return 'x' end},
    persistent = {getSiteData = function(_, d) return d end},
}
env.reqscript = function() return {write_appointment = function(f, a, idx, p, u) made.idx = idx; a.histfig = 901; return true end,
                                   undo_appointment = function(a) a.histfig = -1 end} end
assert(load(src, 'ai-military', 't', env))()
env.candidates = nil
-- one fighter to lead (pick_soldiers takes candidates() rows)
env.pick_soldiers = function() return {{unit = {id = 5, hist_figure_id = 901, military = {squad_id = -1}}}} end
return env, fort, made
"""


def post_env(**spec):
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8")
    # candidates() is local in the module: give the fake a pick_soldiers that ignores it
    src = src.replace("local okc, cands = pcall(candidates)\n        local pick = okc and pick_soldiers(cands, 1)[1]",
                      "local pick = pick_soldiers({}, 1)[1]")
    return lua, lua.execute(POST_FAKE, src, lua.table_from(spec))


@test("no free post: a captain's post is added (AS_NEEDED), its captain appointed, the squad made")
def _():
    lua, (env, fort, made) = post_env(commander=True)
    d = env.make_squad(True, None)
    assert d.ok and d.dry_run and d.new_post and d.office == "militia captain", dict(d)
    n = lua.eval("function(v) return #v end")
    assert n(fort.positions.assignments) == 1, "a dry run adds nothing"
    r = env.make_squad(False, None)
    assert r.ok and r.new_post and r.squad_id == 40, dict(r)
    a = fort.positions.assignments[1]
    assert a.id == 60 and a.position_id == 2 and a.squad_id == -1 and a.histfig == 901 and a.flags.active is True
    assert fort.positions.next_assignment_id == 61 and made.aid == 60 and made.idx == 1


@test("a captain's post is taken back when the squad can't be made")
def _():
    lua, (env, fort, made) = post_env(commander=True, no_squad=True)
    r = env.make_squad(False, None)
    assert r.ok is False and "could not make a squad" in r.error, dict(r)
    assert lua.eval("function(v) return #v end")(fort.positions.assignments) == 1


@test("no captain's post without a militia commander, or when the raws give a fixed number in use")
def _():
    lua, (env, fort, made) = post_env(commander=False)
    r = env.make_squad(False, None)
    assert r.ok is False and r.rejected and "no militia commander" in r.error, dict(r)
    lua, (env, fort, made) = post_env(commander=True, number=0)
    r = env.make_squad(False, None)
    assert r.ok is False and "posts are in use" in r.error, dict(r)



@test("kill orders (0.100 security): only threats or berserk dwarves, never citizens, merchants or pets")
def _():
    LUA.execute(r"""
    local M = ...
    M.df = {mood_type = {Berserk = 7}}
    local function has(k) return function(u) return u[k] == true end end
    M.dfhack = {units = {isMerchant = has('merchant'), isDiplomat = has('diplomat'), isTame = has('tame'),
        isCitizen = has('citizen'), isDanger = has('danger'), isInvader = has('invader')}}
    """, M)
    ok = M.kill_target_ok
    t = lambda **kw: LUA.table_from(kw)
    assert ok(t(danger=True)) and ok(t(invader=True))
    assert ok(t(citizen=True, mood=7))                          # a berserk dwarf
    assert not ok(t(citizen=True)) and not ok(t(citizen=True, danger=True))
    assert not ok(t(merchant=True)) and not ok(t(diplomat=True, invader=True)) and not ok(t(tame=True))
    assert not ok(t())                                          # a peaceful visitor
    # (0.104.140) a citizen changed into a beast (its race not its own), never one at its own race
    assert ok(t(citizen=True, race=5, enemy=t(normal_race=1)))
    assert not ok(t(citizen=True, race=1, enemy=t(normal_race=1)))
    assert not ok(t(citizen=True, race=1, enemy=t(normal_race=-1)))


@test("trim (0.102): the least soldierly go back to work first; never a leader, a dwarf longing to fight, or a squad on orders")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    assert(load(src, 'ai-military', 't', env))()
    local removed = {}
    local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
        while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
    local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
    local units, hfs = {}, {}
    local function dwarf(id, combat, craft, fight)
        local needs = zl()
        if fight then needs = zl({id = 1, focus_level = -2000}) end
        units[id] = {id = id, citizen = true, status = {current_soul = {
            skills = zl({id = 1, rating = combat}, {id = 2, rating = craft}),
            personality = {needs = needs}}}}
        hfs[100 + id] = {unit_id = id}
        return 100 + id
    end
    local sq1 = {orders = zl(), positions = zl({occupant = dwarf(1, 0, 0)}, {occupant = dwarf(2, 5, 1)},
        {occupant = dwarf(3, 0, 9)}, {occupant = dwarf(4, 0, 9, true)}, {occupant = -1})}
    local sq2 = {orders = zl({}), positions = zl({occupant = dwarf(5, 0, 0)}, {occupant = dwarf(6, 0, 15)})}
    env.ipairs = function(t)
        if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
        return ipairs(t)
    end
    env.df = {squad = {find = function(id) return ({[10] = sq1, [11] = sq2})[id] end},
        historical_figure = {find = function(id) return hfs[id] end},
        unit = {find = function(id) return units[id] end},
        job_skill = {[1] = 'AXE', [2] = 'MASONRY'}, need_type = {[1] = 'Fight'},
        global = {plotinfo = {group_id = 1}}, historical_entity = {find = function() return {squads = zl(10, 11)} end}}
    env.dfhack = {units = {isCitizen = function(u) return u.citizen end, getReadableName = function(u) return 'd' .. u.id end},
        military = {removeFromSquad = function(id) table.insert(removed, id); return true end}}
    return env, removed
    """, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    env, removed = env
    r = env.trim(5, False, None)
    assert r.ok, dict(r)
    got = [removed[i] for i in range(1, len(removed) + 1)]
    assert got == [3, 2], got                       # the mason first, then the axedwarf; not 1, 4, 5, 6
    removed2 = env.trim(1, True, None)
    assert removed2.dry_run

@test("fill (0.103.8): a dwarf very unhappy or worse isn't drafted (the stress care took him out)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, added = lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    assert(load(src, 'ai-military', 't', env))()
    local added = {}
    local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
        while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
    local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
    local function dwarf(id, stress)
        return {id = id, stress = stress, military = {squad_id = -1}, relationship_ids = {Mother = -1},
                status = {current_soul = {skills = zl(), personality = {needs = zl()}}}, health = nil}
    end
    local citizens = {dwarf(1, 0), dwarf(2, 1), dwarf(3, 3), dwarf(4, 5)}
    local sq = {id = 10, orders = zl(), positions = zl({occupant = 99}, {occupant = -1}, {occupant = -1}, {occupant = -1})}
    env.ipairs = function(t)
        if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
        return ipairs(t)
    end
    env.df = {squad = {find = function(id) return id == 10 and sq or nil end}, job_skill = {}, need_type = {},
        global = {plotinfo = {group_id = 1}}, historical_entity = {find = function() return {squads = zl(10)} end}}
    env.dfhack = {units = {getCitizens = function() return citizens end, isAdult = function() return true end,
            isBaby = function() return false end, getNoblePositions = function() return {} end,
            getStressCategory = function(u) return u.stress end, getReadableName = function(u) return 'd' .. u.id end},
        military = {addToSquad = function(id) table.insert(added, id); return true end}}
    return env, added
    """, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    r = env.fill(10, 3, env.tostring)
    assert r.ok, dict(r)
    got = sorted(added[i] for i in range(1, len(added) + 1))
    assert got == [3, 4], got                       # not 1 (miserable) or 2 (very unhappy)


def _fill_env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    return lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    assert(load(src, 'ai-military', 't', env))()
    local added = {}
    local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
        while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
    local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
    local function dwarf(id, stress, focus, o)
        o = o or {}
        return {id = id, stress = stress, military = {squad_id = -1}, relationship_ids = {Mother = -1}, noble = o.noble,
                status = {current_soul = {skills = zl(), personality = {needs = zl({id = 5, focus_level = focus})}}},
                health = o.sick and {flags = {needs_healthcare = true}} or nil}
    end
    -- 1 miserable and keen, 2 very unhappy and keen, 3 content and keen, 4 content, not keen,
    -- 5 keen but a noble, 6 keen but a patient
    local citizens = {dwarf(1, 0, -20000), dwarf(2, 1, -20000), dwarf(3, 3, -20000), dwarf(4, 5, 0),
                      dwarf(5, 4, -20000, {noble = true}), dwarf(6, 4, -20000, {sick = true})}
    local sq = {id = 10, orders = zl(), positions = zl({occupant = 99}, {occupant = -1}, {occupant = -1}, {occupant = -1})}
    env.ipairs = function(t)
        if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
        return ipairs(t)
    end
    env.df = {squad = {find = function(id) return id == 10 and sq or nil end}, job_skill = {}, need_type = {[5] = 'MartialTraining'},
        global = {plotinfo = {group_id = 1}}, historical_entity = {find = function() return {squads = zl(10)} end}}
    env.dfhack = {units = {getCitizens = function() return citizens end, isAdult = function() return true end,
            isBaby = function() return false end,
            getNoblePositions = function(u) if u.noble then return {{}} end return {} end,
            getStressCategory = function(u) return u.stress end, getReadableName = function(u) return 'd' .. u.id end},
        military = {addToSquad = function(id) table.insert(added, id); return true end}}
    env.CITIZENS = citizens
    return env, added
    """, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))


@test("fill (0.104.168, review): strict (a crisis) never drafts the very unhappy, keen or not; keen_only only the keen; draftable is the fill's test")
def _():
    env, added = _fill_env()
    got = lambda: sorted(added[i] for i in range(1, len(added) + 1))
    assert env.fill(10, 3, env.tostring).ok and got() == [1, 2, 3], got()      # out of crisis: the keen, unhappy or not
    env, added = _fill_env()
    assert env.fill(10, 3, env.tostring, None, True).ok and got() == [3, 4], got()   # strict: never 1 or 2
    env, added = _fill_env()
    assert env.fill(10, 3, env.tostring, None, True, True).ok and got() == [3], got()  # strict and keen only
    c = env.CITIZENS
    mothers = env.nursing_mothers()
    yes = [i + 1 for i in range(6) if env.draftable(c[i + 1], mothers, True)]
    assert yes == [3, 4], yes                                                  # never a noble or a patient
    yes = [i + 1 for i in range(6) if env.draftable(c[i + 1], mothers, False)]
    assert yes == [1, 2, 3, 4], yes


@test("fill (0.104.5): soldiers go to numbered open places, never 'any' (the empty leader seat DFHack refuses)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, added = lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    assert(load(src, 'ai-military', 't', env))()
    local added = {}
    local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
        while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
    local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
    local function dwarf(id) return {id = id, military = {squad_id = -1}, relationship_ids = {Mother = -1},
        status = {current_soul = {skills = zl(), personality = {needs = zl()}}}} end
    local citizens = {dwarf(1), dwarf(2), dwarf(3)}
    -- the leader's seat (0) empty, places 1 and 3 open, 2 taken
    local sq = {id = 10, orders = zl(), positions = zl({occupant = -1}, {occupant = -1}, {occupant = 7}, {occupant = -1})}
    env.ipairs = function(t)
        if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
        return ipairs(t)
    end
    env.df = {squad = {find = function(id) return id == 10 and sq or nil end}, job_skill = {}, need_type = {},
        global = {plotinfo = {group_id = 1}},
        historical_entity = {find = function() return {squads = zl(10), positions = {assignments = {}}} end}}
    env.dfhack = {units = {getCitizens = function() return citizens end, isAdult = function() return true end,
            isBaby = function() return false end, getNoblePositions = function() return {} end,
            getStressCategory = function() return 4 end, getReadableName = function(u) return 'd' .. u.id end},
        military = {addToSquad = function(id, squad, pos)
            if pos == -1 or pos == 0 then return false end      -- as DFHack: the leader's seat refused
            table.insert(added, pos); sq.positions[pos].occupant = id; return true end}}
    return env, added
    """, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    r = env.fill(10, 5, env.tostring)
    assert r.ok and len(r.added) == 2, dict(r)
    assert sorted(added[i] for i in range(1, len(added) + 1)) == [1, 3]


@test("fill (0.104.5): a squad whose leader's office is empty gets the best fighter appointed and seated")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, log = lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    assert(load(src, 'ai-military', 't', env))()
    local log = {appointed = nil, added = {}}
    local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
        while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
    local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
    local function dwarf(id) return {id = id, hist_figure_id = 100 + id, military = {squad_id = -1, squad_position = -1},
        relationship_ids = {Mother = -1}, status = {current_soul = {skills = zl(), personality = {needs = zl()}}}} end
    local citizens = {dwarf(1), dwarf(2)}
    local sq = {id = 10, entity_id = 1, leader_assignment = 5, orders = zl(), ammo = {update = {}},
                positions = zl({occupant = -1}, {occupant = -1}, {occupant = -1})}
    local assignment = {id = 5, histfig = -1, position_id = 3, squad_id = 10}
    local fort = {squads = zl(10), positions = {assignments = zl(assignment), own = zl({id = 3, code = 'MILITIA_COMMANDER'})}}
    env.ipairs = function(t)
        if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
        return ipairs(t)
    end
    env.df = {squad = {find = function(id) return id == 10 and sq or nil end}, job_skill = {}, need_type = {},
        global = {plotinfo = {group_id = 1, equipment = {update = {}}}},
        historical_entity = {find = function() return fort end},
        historical_figure = {find = function(id) return {id = id, entity_links = {insert = function() end}} end},
        histfig_entity_link_squadst = {}}
    env.reqscript = function(name)
        return {write_appointment = function(ent, a, idx, pos, u) a.histfig = u.hist_figure_id; log.appointed = u.id; return true end}
    end
    env.dfhack = {units = {getCitizens = function() return citizens end, isAdult = function() return true end,
            isBaby = function() return false end, getNoblePositions = function() return {} end,
            getStressCategory = function() return 4 end, getReadableName = function(u) return 'd' .. u.id end},
        military = {addToSquad = function(id, squad, pos)
            if pos <= 0 then return false end
            table.insert(log.added, id); sq.positions[pos].occupant = id; return true end}}
    return env, log
    """, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    r = env.fill(10, 5, env.tostring)
    assert r.ok and r.leader_appointed and log.appointed is not None, dict(r)
    assert len(r.added) == 1 and log.added[1] != log.appointed, (dict(r), log.added[1], log.appointed)


@test("release (0.103.10): a stressed soldier goes back to work, but not one who longs to fight or train")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, removed = lua.execute(r"""
    local src = ...
    local env = setmetatable({}, {__index = _G})
    assert(load(src, 'ai-military', 't', env))()
    local removed = {}
    local function vec(t) t = t or {}; return setmetatable(t, {__len = function(v) local n = 0
        while rawget(v, n) ~= nil do n = n + 1 end return n end}) end
    local function zl(...) local t = {}; for i, v in ipairs({...}) do t[i - 1] = v end return vec(t) end
    local units = {
        [1] = {id = 1, military = {squad_id = 10, squad_position = 2}, status = {current_soul = {personality = {needs = zl()}}}},
        [2] = {id = 2, military = {squad_id = 10, squad_position = 3},
               status = {current_soul = {personality = {needs = zl({id = 1, focus_level = -3000})}}}}}
    env.ipairs = function(t)
        if getmetatable(t) then return function(v, i) i = i + 1; if rawget(v, i) ~= nil then return i, v[i] end end, t, -1 end
        return ipairs(t)
    end
    env.df = {unit = {find = function(id) return units[id] end}, need_type = {[1] = 'MartialTraining'},
              squad = {find = function() return {id = 10, orders = zl()} end}}
    env.dfhack = {units = {isCitizen = function() return true end, getReadableName = function(u) return 'd' .. u.id end},
                  military = {removeFromSquad = function(id) table.insert(removed, id); return true end}}
    return env, removed
    """, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    r = env.release(2, False, None)
    assert not r.ok and r.rejected and "longs to fight" in r.error, dict(r)
    r = env.release(1, False, None)
    assert r.ok and removed[1] == 1, dict(r)
    # (0.104.159) a mother with a baby goes home even longing to train; not one without a baby
    lua.execute("""local env = ...
        env.dfhack.units.getCitizens = function() return {{id = 9, relationship_ids = {Mother = 2}}} end
        env.dfhack.units.isBaby = function(u) return u.id == 9 end""", env)
    r = env.release(2, False, None, True)
    assert r.ok and removed[2] == 2, dict(r)
    r = env.release(1, False, None, True)
    assert not r.ok and "no baby" in r.error, dict(r)


# --- (0.105.0, round 2) an army that can fight ---------------------------------------

ARMY_FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v)
                       local n = #self
                       if at == '#' then at = n end
                       for i = n, at + 1, -1 do self[i] = self[i - 1] end
                       self[at] = v end,
                   erase = function(self, at)
                       local n = #self
                       for i = at, n - 2 do self[i] = self[i + 1] end
                       self[n - 1] = nil end}})
end
local DEFS = {[1] = {id = 'ITEM_WEAPON_AXE_BATTLE'}, [2] = {id = 'ITEM_WEAPON_PICK'},
              [6] = {id = 'ITEM_WEAPON_CROSSBOW', ranged_ammo = 'BOLT'}}
local where = {}
local function item(id, sub, x, mat, flags)
    local it = {id = id, flags = flags or {}, sub = sub, mat = mat or 0, subtype = DEFS[sub]}
    function it:getSubtype() return self.sub end
    function it:getMaterial() return self.mat end
    function it:getMaterialIndex() return 0 end
    where[id] = {x, 0, 0}
    return it
end
-- weapons: 41 a copper axe (mat 0), 42 a wooden axe (mat 9, not metal), 43 a pick, 44 a crossbow,
-- 45 an axe stale on soldier 103's place list; shields: 61, 62
local W = {item(41, 1, 5), item(42, 1, 4, 9), item(43, 2, 1), item(44, 6, 2), item(45, 1, 3)}
local S = {item(61, 0, 5), item(62, 0, 6)}
local Q = {item(81, 0, 1), item(82, 0, 2)}
local items = {WEAPON = vec(W), SHIELD = vec(S), QUIVER = vec(Q)}
local eq = {items_assigned = {WEAPON = vec({}), SHIELD = vec({})},
            items_unassigned = {WEAPON = vec({41, 42, 43, 44, 45}), SHIELD = vec({61, 62})},
            items_unmanifested = {WEAPON = vec({}), SHIELD = vec({})}, update = {}, work_weapons = vec({})}
local function spec(sub, cls, choice)
    return {item_type = 24, item_subtype = sub, material_class = cls or -1, mattype = -1, matindex = -1,
            color = -1, indiv_choice = choice or {}, assigned = vec({})}
end
local function place(occ, wspec, extra)
    local u = {[0] = vec({}), [1] = vec({}), [2] = vec(wspec and {wspec} or {})}
    return {occupant = occ, equipment = {assigned_items = vec(extra or {}), uniform = u, quiver = -1,
                                         backpack = -1, flask = -1}}
end
-- squad 7 (the AI's metal melee): 100 any melee, 101 axes of the WeaponMelee class, 102 axes, 103 axes (45 stale)
-- squad 8 (crossbows): 104 crossbow, 105 any ranged
local sq7 = {id = 7, orders = vec({}), ammo = {update = {}, ammunition = vec({}), ammo_items = vec({})},
             positions = vec({place(100, spec(-1, -1, {melee = true})), place(101, spec(1, 12)),
                              place(102, spec(1)), place(103, spec(1), {45})})}
local sq8 = {id = 8, orders = vec({}), ammo = {update = {}, ammunition = vec({}), ammo_items = vec({})},
             positions = vec({place(104, spec(6)), place(105, spec(-1, -1, {ranged = true}))})}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local persist = {['ai-overseer/uniforms'] = {['7'] = 'Melee, metal armor |weapon:ITEM_WEAPON_AXE_BATTLE'}}
local DEF = {}
DEF.new = function() return setmetatable({burrows = vec({}), _defend = true}, {__index = {delete = function() end}}) end
DEF.is_instance = function(self, o) return type(o) == 'table' and o._defend == true end
env.df = {uniform_category = {_last_item = 2, body = 0, shield = 1, weapon = 2},
          item_type = {WEAPON = 24, SHIELD = 27},
          entity_material_category = {[-1] = 'None', [12] = 'WeaponMelee'},
          squad_order_defend_burrowsst = DEF,
          squad_uniform_spec = {new = function() return {indiv_choice = {}, assigned = vec({}), delete = function() end} end},
          squad = {find = function(id) return id == 7 and sq7 or id == 8 and sq8 or nil end},
          historical_figure = {find = function(id) return {unit_id = id} end},
          unit = {find = function(id) return {id = id} end},
          item = {find = function(id) return nil end},
          historical_entity = {find = function() return {squads = vec({7, 8})} end},
          global = {plotinfo = {equipment = eq, group_id = 1,
                                alerts = {list = vec({{burrows = vec({})}, {burrows = vec({5})}})},
                                burrows = {list = vec({})}},
                    world = {squads = {all = vec({sq7, sq8})}, items = {other = items},
                             raws = {itemdefs = {weapons = vec({{id = 'ITEM_WEAPON_CROSSBOW', subtype = 6}})}}}}}
env.dfhack = {persistent = {getSiteData = function(k, d) return persist[k] or d end, saveSiteData = function() end},
              matinfo = {decode = function(it)
                  return {inorganic = {id = it.mat == 0 and 'COPPER' or 'X'}, material = {flags = {IS_METAL = it.mat == 0}}}
              end},
              items = {getHolderUnit = function() return nil end,
                       getPosition = function(it) local w = where[it.id]; return w[1], w[2], w[3] end,
                       getSubtypeDef = function(t, st) return DEFS[st] end,
                       getDescription = function(it) return 'item ' .. it.id end},
              units = {getPosition = function(u) return 0, 0, 0 end},
              maps = {canWalkBetween = function(a, b) return b.x ~= 5 end}}     -- x5 is behind a closed door
assert(load(src, 'ai-military', 't', env))()
return env, eq, sq7, sq8
"""


def army():
    lua = LuaRuntime(unpack_returned_tuples=True)
    out = lua.execute(ARMY_FAKE, (ROOT / "lua" / "ai-military.lua").read_text(encoding="utf-8"))
    n = lua.eval("function(v) return #v end")
    return (lua, n) + tuple(out)


@test("0.105.0: weapon_fits reads the entry: its kind, melee or ranged for 'any', never a pick, a metal class")
def _():
    lua, n, env, eq, sq7, sq8 = army()
    items = env.df["global"].world["items"].other.WEAPON
    axe, wood_axe, pick, xbow = items[0], items[1], items[2], items[3]
    any_melee = sq7.positions[0].equipment.uniform[2][0]
    metal_axe = sq7.positions[1].equipment.uniform[2][0]
    any_ranged = sq8.positions[1].equipment.uniform[2][0]
    assert env.weapon_fits(any_melee, axe) is True
    assert env.weapon_fits(any_melee, pick) == (False, "pick")                # a miner's pick is never "any"
    assert env.weapon_fits(any_melee, xbow) == (False, "melee")
    assert env.weapon_fits(any_ranged, xbow) is True and env.weapon_fits(any_ranged, axe) == (False, "ranged")
    assert env.weapon_fits(metal_axe, axe) is True
    assert env.weapon_fits(metal_axe, wood_axe) == (False, "material")      # the WeaponMelee class: metal only
    assert env.weapon_fits(metal_axe, xbow) == (False, "kind")


@test("0.105.0: weapon_gaps_why says why each entry is empty (unreachable, wrong material, stale, a crossbow for the crossbows)")
def _():
    lua, n, env, eq, sq7, sq8 = army()
    w = env.gaps_why("weapon", "WEAPON")
    why = dict(w.why)
    # 100 any melee: 41 behind a door, 45 stale (on 103's place list): stale is further along; 101 the class:
    # the copper axe 41 fits but is unreachable... each gap takes the furthest stage any item reached
    assert w.places == 6 and w.entries == 6 and w.given == 0, (w.places, w.entries, w.given)
    # place 1 asks for metal axes: the copper one is behind a door, the wooden one isn't metal
    assert why == {"unreachable": 1, "fillable": 5}, why
    assert w.ranged == 2, w.ranged
    det = [w.detail[i] for i in range(1, len(w.detail) + 1)]
    assert "squad 7 place 1 wants ITEM_WEAPON_AXE_BATTLE WeaponMelee: unreachable" in det, det
    assert "squad 8 place 1 wants any ranged: fillable" in det, det
    # the copper and wooden axes someone's own: axe 45 is the best left, stale
    # on soldier 103's list (each gap takes the furthest any item got)
    lua.execute('''local env = ...
        local W = env.df.global.world.items.other.WEAPON
        W[0].flags = {owned = true}; W[1].flags = {owned = true}''', env)
    why = dict(env.gaps_why("weapon", "WEAPON").why)
    assert why == {"stale on a soldier's list": 4, "fillable": 2}, why


@test("0.105.0: fix_gear_gaps clears a stale claim, adds shields to the AI's metal melee uniform, hands weapons out")
def _():
    lua, n, env, eq, sq7, sq8 = army()
    d = env.fix_gear_gaps(True, True)
    assert d.ok and d.dry_run and d.stale == 1 and d.shields_added == 4, dict(d)
    assert n(sq7.positions[3].equipment.assigned_items) == 1                      # a dry run changes nothing
    r = env.fix_gear_gaps(False, True)
    assert r.ok and r.stale == 1 and r.shields_added == 4 and r.weapons >= 1, dict(r)
    seq = lambda v: [v[i] for i in range(n(v))]
    assert seq(sq7.positions[3].equipment.assigned_items) == []                  # the stale 45 cleared off 103
    assert seq(sq7.positions[0].equipment.uniform[2][0].assigned) == [45]         # and handed out again
    assert seq(sq7.positions[1].equipment.uniform[2][0].assigned) == []           # metal only: none it can reach
    assert seq(sq8.positions[0].equipment.uniform[2][0].assigned) == [44]
    assert all(n(sq7.positions[i].equipment.uniform[1]) == 1 for i in range(4))    # a shield entry each
    assert n(sq8.positions[0].equipment.uniform[1]) == 0                          # never the crossbow squad
    assert eq.update.weapon and eq.update.shield
    # the pick never goes to 'any melee'
    assigned = [sq7.positions[0].equipment.uniform[2][0].assigned[i]
                for i in range(n(sq7.positions[0].equipment.uniform[2][0].assigned))]
    assert 43 not in assigned, assigned


@test("0.105.0: quivers: each crossbow place gets a free one (its quiver field), DF told to look again")
def _():
    lua, n, env, eq, sq7, sq8 = army()
    rep = env.quiver_report()
    assert (rep.ranged_places, rep.quivers_assigned, rep.quivers_free) == (2, 0, 2), dict(rep)
    d = env.assign_quivers(True, 10)
    assert d.ok and d.would_assign == 2 and sq8.positions[0].equipment.quiver == -1
    r = env.assign_quivers(False, 10)
    assert r.ok and r.assigned == 2, dict(r)
    assert {sq8.positions[0].equipment.quiver, sq8.positions[1].equipment.quiver} == {81, 82}
    assert sq7.positions[0].equipment.quiver == -1                    # melee soldiers get none
    assert sq8.ammo.update.quiver and eq.update.quiver
    again = env.assign_quivers(False, 10)
    assert not again.ok and again.rejected


@test("0.105.0: bolts: a crossbow squad without an ammunition entry gets one; a melee squad never")
def _():
    lua, n, env, eq, sq7, sq8 = army()
    lua.execute("""local env = ...
        env.df.squad_ammo_spec = {new = function() return {flags = {}, assigned = {}, delete = function() end} end}
        env.df.item_type.AMMO = 38
        env.df.global.world.raws.itemdefs.ammo = {{id = 'ITEM_AMMO_BOLTS', subtype = 0}}
        env.fort_squad = function(id) return env.df.squad.find(id) end""", env)
    assert env.squad_ammo(sq7) is None
    a = env.squad_ammo(sq8)
    assert a.specs == 0 and a.wanted == 0, dict(a)
    assert env.squad_bolts(7, False).rejected
    r = env.squad_bolts(8, False)
    assert r.ok and r.bolts == 100 and n(sq8.ammo.ammunition) == 1, dict(r)
    assert env.squad_bolts(8, False).rejected                         # set already


@test("0.105.0: shelter: the squad holds the civilian alert's burrow; counts as the AI's order; the player's kept")
def _():
    lua, n, env, eq, sq7, sq8 = army()
    lua.execute("""local env, sq8 = ...
        env.fort_squad = function(id) return env.df.squad.find(id) end
        sq8.orders:insert('#', setmetatable({title = 'the player'}, {__index = {delete = function() end}}))""", env, sq8)
    r = env.shelter(7, False)
    assert r.ok and r.burrows == 1 and n(sq7.orders) == 1 and sq7.orders[0].burrows[0] == 5, dict(r)
    assert env.is_shelter_order(sq7.orders[0]) is True
    assert env.shelter(7, False).rejected                              # in already
    assert env.shelter(8, False).rejected and n(sq8.orders) == 1      # the player's order kept
    c = env.orders(7, None, True)
    assert c.ok and c.cleared == 1 and n(sq7.orders) == 0             # the recall clears it
    lua.execute("local env = ... env.df.global.plotinfo.alerts.list[1].burrows = {}", env)
    assert env.shelter(7, False).rejected                              # no shelter burrow


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
