"""(0.105.115 item19) The fort's goods left in the depot: taken out by hand.

unload_depot answered "none moved out of the depot: the game kept it in the
depot" in B, C and F (25 Nov). Probe (C and E, 25 Nov 10:49): every one of
the fort's goods in the depot (174 in C, 166 in E) is flags.in_building with
a BUILDING_HOLDER ref to the depot and a UNIT_TRADEBRINGER ref, none
on_ground, as item17 found for the merchants' goods; DFHack's moveToGround
(detachItem) refuses those. unload() now takes each out as out_of_depot does
(the depot's contained_items entry, the holder and bringer refs gone,
in_building off, on the ground at its tile) and checks each one.

    python tests/test_item19_unload.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

SRC = split_src("ai-trade.lua")   # (0.105.119) unload in the part ai-trade-unload


@test("static: unload no longer uses moveToGround; it reuses out_of_depot and checks each one; refuses an open screen")
def _():
    i = SRC.index("function unload(limit, dry_run, txt)")
    body = SRC[i:SRC.index("\nend\n", i)]
    assert "moveToGround" not in body
    for word in ("out_of_depot, item, dep, also, at", "out_check(item, dep)", "merchant_item(ci.item)",
                 "main_interface.trade.open", "#caravans(txt) > 0", "held_why(ci.item, dep.id)",
                 "'UNIT_TRADEBRINGER'", "building_item_role_type.TEMP"):
        assert word in body, word
    assert SRC.index("local function out_of_depot") < i      # an upvalue only if defined before
    assert len((ROOT / "lua" / "ai-trade.lua").read_bytes().replace(b"\r", b"")) < 60000


SETUP = r"""local env = ...
env.df.building_item_role_type = {TEMP = 0, PERM = 1}
env.df.general_ref_type = {ENTITY_ITEMOWNER = 7, BUILDING_HOLDER = 9, BUILDING_CAGED = 11,
                           CONTAINED_IN_ITEM = 12, UNIT_TRADEBRINGER = 13}
env.df.global.plotinfo.caravans = {}
env.df.global.game = {main_interface = {trade = {open = false}}}
BLOCK = {items = {}, occupancy = {}}
env.dfhack.maps.getTileBlock = function() return BLOCK end
env.dfhack.items.getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end
local inside = {}
env.dfhack.items.getContainedItems = function(c) return inside[c.id] or {} end
local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
dep.id = 134
local function ref(t, f) local r = f or {}; r.getType = function() return t end; return r end
-- as the probe saw them: in_building, the depot's holder ref and the bringer's
local function item(id, trader, extra)
    local it = {id = id, flags = {trader = trader, in_building = true, on_ground = false, in_inventory = false},
                general_refs = {ref(9, {building_id = 134}), ref(13)}, specific_refs = {},
                world_data_id = -1, pos = {x = 5, y = 5, z = 1}}
    for k, v in pairs(extra or {}) do it.flags[k] = v end
    return it
end
local bin = item(50, false)
local c1 = item(51, false, {in_building = false, in_inventory = true})
c1.general_refs = {ref(12), ref(13)}
inside[50] = {c1}
local other = item(7, false)
other.general_refs = {ref(9, {building_id = 999})}            -- held by another building: left
local nopos = item(8, false)
nopos.pos = {x = -30000, y = -30000, z = -30000}
dep.contained_items = {
    {use_mode = 1, item = item(1, false)},                          -- the depot's own blocks: never
    {use_mode = 0, item = item(2, false)}, {use_mode = 0, item = item(3, false)},
    {use_mode = 0, item = bin},
    {use_mode = 0, item = item(4, true)},                           -- the merchants': never
    {use_mode = 0, item = item(5, false, {in_job = true})},         -- a hauler's: left to him
    {use_mode = 0, item = other}, {use_mode = 0, item = nopos},
}
ITEMS = {}
for _, ci in ipairs(dep.contained_items) do ITEMS[ci.item.id] = ci.item end
ITEMS[51] = c1
"""


def lua_env():
    import test_trade as TT
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, _marked = lua.execute(TT.FAKE, module_src("ai-trade.lua"))
    lua.execute(SETUP, env)
    return lua, env


def left_ids(lua, env):
    return lua.eval("(function(d) local o = {} for _, ci in ipairs(d.contained_items) do "
                    "table.insert(o, ci.item.id) end return table.concat(o, ',') end)")(
        env.df["global"].world.buildings.other.TRADE_DEPOT[1])


def refs_of(lua, it):
    return lua.eval("(function(it) local o = {} for _, r in ipairs(it.general_refs) do "
                    "table.insert(o, r:getType()) end return table.concat(o, ',') end)")(it)


@test("lua: the fort's goods (and a bin with what it holds) out onto the floor, checked; "
      "the building, the merchants', a busy one and another building's stay")
def _():
    need_lua()
    lua, env = lua_env()
    r = env.unload(50, True)
    assert r.ok and r.dry_run and r["items"] == 4 and r.kept["other_building"] == 1, dict(r)
    assert left_ids(lua, env) == "1,2,3,50,4,5,7,8"                  # a dry run touches nothing
    r = env.unload(50, False)
    assert r.ok and r["items"] == 4 and r.left == 0 and r.failed is None and r.first_failure is None, dict(r)
    assert left_ids(lua, env) == "1,4,5,7", left_ids(lua, env)
    items = lua.globals().ITEMS
    for i in (2, 3, 50, 8):
        it = items[i]
        assert it.flags.on_ground and not it.flags.in_building and refs_of(lua, it) == "", (i, dict(it.flags))
        assert not it.flags.trader and not it.flags.forbid             # the fort's still, for the haulers
    assert (items[8].pos.x, items[8].pos.y) == (5, 5)                  # no position: the depot's centre
    c = items[51]                                                     # in the bin: stays in it, refs cleared
    assert c.flags.in_inventory and not c.flags.on_ground and not c.flags.in_building and refs_of(lua, c) == "12"
    for i in (1, 4, 5, 7):
        assert items[i].flags.in_building and "9" in refs_of(lua, items[i]), i
    blk = lua.globals().BLOCK["items"]
    assert sorted(blk[i] for i in range(1, len(blk) + 1)) == [2, 3, 8, 50]


@test("lua: never with a caravan about or the trade screen open; a failure is said with the first one's reason")
def _():
    need_lua()
    lua, env = lua_env()
    lua.execute("""local env = ...
        env.df.global.game.main_interface.trade.open = true""", env)
    r = env.unload(50, False)
    assert not r.ok and r.rejected and "trade screen" in r.error, dict(r)
    lua.execute("""local env = ...
        env.df.global.game.main_interface.trade.open = false
        env.df.global.plotinfo.caravans = {{entity = 1, trade_state = 2, time_remaining = 100,
                                            flags = {tribute = false}}}
        env.df.historical_entity = {find = function() return nil end}""", env)
    r = env.unload(50, False)
    assert not r.ok and r.rejected and "caravan" in r.error, dict(r)
    assert left_ids(lua, env) == "1,2,3,50,4,5,7,8"
    lua.execute("""local env = ...
        env.df.global.plotinfo.caravans = {}
        env.dfhack.maps.getTileBlock = function() return nil end""", env)
    r = env.unload(50, False)
    assert not r.ok and r.failed == 4 and "no map block" in r.first_failure, dict(r)
    assert "none moved out of the depot" in r.error
    assert left_ids(lua, env) == "1,2,3,50,4,5,7,8"                  # nothing changed for one that failed


@test("lua: only the merchants' and a busy one left: said as before")
def _():
    need_lua()
    lua, env = lua_env()
    lua.execute("""local env = ...
        local d = env.df.global.world.buildings.other.TRADE_DEPOT[1]
        d.contained_items = {d.contained_items[1], d.contained_items[5]}""", env)
    r = env.unload(50, False)
    assert not r.ok and r.merchant_goods == 1 and "nothing of the fort's" in r.error, dict(r)


finish()
