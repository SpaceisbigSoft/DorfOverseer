"""(item3) A caravan long done whose goods stay in the depot: taken away.

B, 24 Nov 22:55 (live state.json trade.overstay): "The Moral Wire" Leaving
2903 days, time_remaining 0, one merchant on the map (reach_depot 1,
in_depot 0), 115 of its goods still in the depot; C had the same caravan.
0.105.97's stuck-caravan steps (walk off, the map's edge, then DFHack's
fix/stuck-merchants + `caravan leave`) had run out: walk and edge were
tried, the merchant stayed, and the dismiss step waits for no merchant on
the map, so it never came; the goods were nobody's business. Now:
  * planner_trade's caravan_goods rule: a caravan Leaving, its time run
    out, caravan_goods_days past its leaving, its goods in the depot and
    none of its merchants at the depot: clear_caravan_goods (its goods taken
    out of the game as if packed, never the fort's), cooldown a week;
  * record()'s hook marks the clear in the caravan's book, and the stuck
    caravan's steps start again (its merchants have nothing to wait for).

    python tests/test_item3_caravan_goods.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import bridge_hub_src, module_src  # noqa: E402

from planner import PLANNER_CONFIG, Memory, NEEDS_YOU, Proposal  # noqa: E402
import planner_outside as O  # noqa: E402
from planner_trade import _trade_rules  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = PLANNER_CONFIG
DAY = 1200
YEAR = 403200


def b_overstay(**kw) -> dict:
    o = {"civ": "The Moral Wire", "entity": 308, "state": "Leaving", "days": 2903, "time_remaining": 0,
         "merchants": 1, "reach_depot": 1, "in_depot": 0, "wagons": 0, "depot_wagons": False,
         "goods_in_depot": 115, "holds": ["115 of their goods still in the depot"], "at": [[287, 32, 176]]}
    o.update(kw)
    return o


def trade_state(overstay, caravans=None) -> dict:
    return {"trade": {"depot": True, "caravans": caravans or [], "at_depot": 0, "goods": 0, "overstay": overstay,
                      "trader": {"at_depot": False, "can_open": True, "fresh": False}},
            "buildings": {}, "dwarves": {"adults": 57}}


def rule(overstay, caravans=None):
    props, notes = [], []
    _trade_rules(trade_state(overstay, caravans), CFG, 57, props, notes, {"trade": 0}, None)
    return [p for p in props if p.rule == "caravan_goods"], notes


@test("B's Moral Wire (2903 days, 115 goods, its merchant not coming): its goods taken away, never the fort's")
def _():
    ps, _ = rule([b_overstay()])
    assert len(ps) == 1, ps
    p = ps[0]
    assert p.action == {"type": "clear_caravan_goods", "entity": 308, "max": CFG["caravan_goods_max"]}, p.action
    assert "The Moral Wire" in p.reason and "2903 days" in p.reason and "115" in p.reason and "theft" in p.reason


@test("not: still trading, its time not run out, too soon, no goods, an old bridge (no entity), another caravan about")
def _():
    for kw in ({"state": "AtDepot"}, {"time_remaining": 500}, {"days": CFG["caravan_goods_days"] - 1},
               {"goods_in_depot": 0}, {"entity": None}, {"time_remaining": None}):
        ps, _ = rule([b_overstay(**kw)])
        assert not ps, kw
    ps, _ = rule([b_overstay()], caravans=[{"civ": "The Other", "state": "Approaching"}])
    assert not ps                                   # their goods would look the same
    ps, _ = rule([b_overstay(days=CFG["caravan_goods_days"])])
    assert ps                                       # at the mark: yes


@test("a merchant of it at the depot: left to pack, said, no clear")
def _():
    ps, notes = rule([b_overstay(in_depot=1)])
    assert not ps and any("left to pack them" in n for n in notes), notes


@test("cooldown: a week (caravan_goods_cooldown_ticks), the rule's default key")
def _():
    import planner_select
    assert CFG["caravan_goods_cooldown_ticks"] == 7 * DAY and CFG["caravan_goods_days"] == 30
    from planner_core import COOLDOWN_KEYS, NO_COOLDOWN
    assert "caravan_goods" not in COOLDOWN_KEYS and "caravan_goods" not in NO_COOLDOWN
    src = (ROOT / "brain" / "planner_select.py").read_text(encoding="utf-8")
    assert 'f"{p.rule}_cooldown_ticks"' in src
    assert planner_select.select is not None


# --- the stuck caravan's steps start again after a clear ---------------------------------------

def b_fort(tick: int, caravans) -> dict:
    return {"settings": {"traits": {"piety": 150}, "set_pop_cap": True, "fort_goal": "expand"},
            "society": {"pop_cap": 200, "strict_pop_cap": 220},
            "dwarves": {"total": 57}, "stocks": {"drink": 2000, "prepared_meals": 2000},
            "migration": {"civ": True, "force": "force", "hermit_tool": False, "queued": 0, "caravans": caravans},
            "others_on_map": {}, "date": {"year": 251 + tick // YEAR, "tick": tick % YEAR}}


CAR = {"entity": 308, "own": True, "state": "Leaving", "days_left": 0, "merchants": 1, "leaving": True,
       "can_leave": 1}


def cycle(m, d):
    s = b_fort(d * DAY, [dict(CAR)])
    props, notes = [], []
    O.note_outside(s, m, CFG)
    O._drought_rule(s, m, CFG, props, notes)
    now = 251 * YEAR + d * DAY
    for p in props:
        O.note_caravan_try(p, {"ok": True, "told": 1, "moved": 1, "step": p.action.get("step", "walk")}, m, now)
        m.last_fired["stuck_caravan"] = now
    return props, notes


@test("the steps ran out (walk, walk, edge, a Needs you); the goods cleared: walk off again, then the edge")
def _():
    m = Memory()
    st = []
    for d in range(0, 200):
        props, notes = cycle(m, d)
        st += [p.action.get("step", "walk") for p in props]
    assert st == ["walk", "walk", "edge"], st
    assert any(n.startswith(NEEDS_YOU) for n in notes), notes
    # the goods taken away (record()'s hook): the book marks it
    clear = Proposal("caravan_goods", {"type": "clear_caravan_goods", "entity": 308, "max": 200}, "x", 5)
    O.note_caravan_try(clear, {"ok": True, "removed": 20, "contents": 95, "left": 0}, m, 251 * YEAR + 200 * DAY)
    assert m.outside["stuck"]["308"]["goods_cleared"] == 251 * YEAR + 200 * DAY
    st2, last = [], None
    for d in range(201, 300):
        props, notes = cycle(m, d)
        st2 += [p.action.get("step", "walk") for p in props]
        last = notes
    assert st2 == ["walk", "walk", "edge"], st2
    assert "goods_cleared" in m.outside["stuck"]["308"]          # kept by the book across cycles
    assert any(n.startswith(NEEDS_YOU) for n in last)


@test("a refused, removed-nothing or dry clear marks nothing")
def _():
    m = Memory()
    clear = Proposal("caravan_goods", {"type": "clear_caravan_goods", "entity": 308, "max": 200}, "x", 5)
    O.note_caravan_try(clear, {"ok": False, "rejected": True, "error": "x"}, m, 5)
    O.note_caravan_try(clear, {"ok": True, "removed": 0, "contents": 0}, m, 6)
    dry = Proposal("caravan_goods", {"type": "clear_caravan_goods", "entity": 308, "dry_run": True}, "x", 5)
    O.note_caravan_try(dry, {"ok": True, "dry_run": True, "goods": 3}, m, 7)
    assert "goods_cleared" not in O._d(O._d(getattr(m, "outside", {})).get("stuck")).get("308", {})


@test("record() calls the hook for clear_caravan_goods")
def _():
    import planner
    m = Memory()
    s = b_fort(40 * DAY, [dict(CAR)])
    O.note_outside(s, m, CFG)
    p = Proposal("caravan_goods", {"type": "clear_caravan_goods", "entity": 308, "max": 200}, "x", 5)
    planner.record([(p, {"ok": True, "removed": 3})], s, m)
    assert isinstance(m.outside["stuck"]["308"].get("goods_cleared"), int), m.outside
    assert m.last_fired.get("caravan_goods") is not None


@test("wiring: the bridge action, its dry run, its words, its class, the overstay's entity, the digest note")
def _():
    b = bridge_hub_src()
    assert re.search(r"clear_caravan_goods = function\(a\)[\s\S]{0,500}\.clear_caravan_goods\(id, n, "
                     r"a\.dry_run == true, txt\)", b), "no bridge action"
    assert "'clear_caravan_goods'," in b                         # DRY_OK
    src = module_src("ai-trade.lua")
    assert "function clear_caravan_goods(entity, limit, dry_run, txt)" in src
    assert "entity = c.entity}" in src                          # overstay carries the civ id
    assert "dfhack.items.remove" in src and "ENTITY_ITEMOWNER" in src
    i = src.index("function clear_caravan_goods")
    body = src[i:src.index("\nend\n", i)]
    for word in ("'Leaving'", "in_job", "at_depot(u, dep)", "main_interface.trade.open"):
        assert word in body or word in src[src.index("local function goods_free"):i], word
    assert "flags.trader = false" not in body and "moveToGround" not in body     # never the fort's
    import overseer
    assert "never the fort" in overseer.SHORT_WORDS["clear_caravan_goods"]
    import hold_classes as H
    assert H.RULE_CLASS.get("caravan_goods") == H.RULE_CLASS.get("stuck_caravan")
    assert H.ACTION_CLASS.get("clear_caravan_goods") == H.ACTION_CLASS.get("free_caravan")
    assert "overstay" in (ROOT / "brain" / "digest.py").read_text(encoding="utf-8")
    assert len((ROOT / "lua" / "ai-trade.lua").read_bytes()) < 60 * 1024


# --- the Lua (on the PC: lupa) ---------------------------------------------------------------

SETUP = r"""local env = ...
env.df.building_item_role_type = {TEMP = 0, PERM = 1}
env.df.general_ref_type = {ENTITY_ITEMOWNER = 7, BUILDING_HOLDER = 9, BUILDING_CAGED = 11,
                           CONTAINED_IN_ITEM = 12}
env.df.caravan_state.T_trade_state = {Approaching = 1, AtDepot = 2, Leaving = 3,
                                     [1] = 'Approaching', [2] = 'AtDepot', [3] = 'Leaving'}
env.df.global.plotinfo.caravans = {{entity = 308, trade_state = 3, time_remaining = 0, flags = {tribute = false}}}
env.df.historical_entity = {find = function() return {name = 'x'} end}
env.dfhack.translation = {translateName = function() return 'The Moral Wire' end}
env.df.global.game = {main_interface = {trade = {open = false}}}
local function unit(x) return {id = 1, civ_id = 308, x = x, y = 2, z = 1, flags1 = {merchant = true, inactive = false}} end
env.df.global.world.units = {active = {unit(287)}}
env.dfhack.units = {isDead = function() return false end, getPosition = function(u) return u.x, u.y, u.z end}
REMOVED = {}
REFUSE = {}
-- as DFHack's Items::remove (detachItem): refused with a BUILDING_HOLDER ref
-- or neither on the ground nor in an inventory (B, 25 Nov: every depot good)
env.dfhack.items.remove = function(it)
    if REFUSE[it.id] then return false end
    for _, r in ipairs(it.general_refs) do if r:getType() == 9 then return false end end
    if not (it.flags.on_ground or it.flags.in_inventory) then return false end
    it.flags.on_ground, it.flags.removed, it.flags.garbage_collect = false, true, true
    table.insert(REMOVED, it.id); return true
end
BLOCK = {items = {}, occupancy = {}}
env.dfhack.maps.getTileBlock = function() return BLOCK end
local inside = {}
env.dfhack.items.getContainedItems = function(c) return inside[c.id] or {} end
local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
dep.id = 1328
dep.x1, dep.x2, dep.y1, dep.y2, dep.z = 4, 6, 4, 6, 1
local function ref(t, f) local r = f or {}; r.getType = function() return t end; return r end
local function item(id, trader, extra)
    local it = {id = id, flags = {trader = trader, in_building = true, on_ground = false, foreign = true},
                general_refs = {ref(7, {entity_id = 308}), ref(9, {building_id = 1328})}, specific_refs = {},
                world_data_id = -1, pos = {x = 1, y = 1, z = 1}}
    for k, v in pairs(extra or {}) do it.flags[k] = v end
    return it
end
local function content(id, trader)
    local it = item(id, trader, {in_building = false, in_inventory = true})
    it.general_refs = {ref(7, {entity_id = 308}), ref(12)}           -- CONTAINED_IN_ITEM, no holder
    return it
end
ITEM = item
local bin = item(50, true)
inside[50] = {content(51, true), content(52, true)}
local mixed = item(60, true)
inside[60] = {content(61, true), content(62, false)}            -- one of the fort's inside: the bin stays
dep.contained_items = {
    {use_mode = 0, item = item(1, true)}, {use_mode = 0, item = item(2, true)},
    {use_mode = 0, item = bin}, {use_mode = 0, item = mixed},
    {use_mode = 0, item = item(3, true, {in_job = true})},                -- a merchant's pick-up: left
    {use_mode = 0, item = item(4, false)},                                -- the fort's own goods: never
    {use_mode = 1, item = item(5, true)},                                 -- part of the building: never
}
"""


def lua_env():
    import test_trade as TT
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, _marked = lua.execute(TT.FAKE, module_src("ai-trade.lua"))
    lua.execute(SETUP, env)
    return lua, env


def removed(lua):
    r = lua.globals().REMOVED
    return sorted(r[i] for i in range(1, len(r) + 1))


@test("lua: B's goods go (a bin with its contents first); the fort's, a mixed bin, a busy one and the building stay")
def _():
    need_lua()
    lua, env = lua_env()
    r = env.clear_caravan_goods(308, 200, True, None)
    assert r.ok and r.dry_run and r.goods == 3 and r["items"] == 5 and removed(lua) == [], dict(r)
    r = env.clear_caravan_goods(308, 200, False, None)
    assert r.ok and r.removed == 3 and r.contents == 2 and r.left == 2, dict(r)
    assert removed(lua) == [1, 2, 50, 51, 52], removed(lua)
    assert r.kept.not_theirs == 1 and r.kept.busy == 1, dict(r.kept)
    assert r.civ == "The Moral Wire" and r.failed is None and r.first_failure is None
    left = lua.eval("(function(d) local o = {} for _, ci in ipairs(d.contained_items) do "
                    "table.insert(o, ci.item.id) end return table.concat(o, ',') end)")(
        env.df["global"].world.buildings.other.TRADE_DEPOT[1])
    assert left == "60,3,4,5", left                     # the removed goods out of the depot's list
    chk = lua.execute("""local found
        for _, b in ipairs(BLOCK.items) do if b == 1 then found = true end end
        return found""")
    assert chk, "the good was not set on its tile before its removal"


@test("lua (item17): DFHack's refusal of a depot good is no longer the end: out of the depot first, "
      "its holder ref gone, its owner and trader flag kept")
def _():
    need_lua()
    lua, env = lua_env()
    it = lua.execute("""local env = ...
        return env.df.global.world.buildings.other.TRADE_DEPOT[1].contained_items[1].item""", env)
    r = env.clear_caravan_goods(308, 1, False, None)
    assert r.ok and r.removed == 1 and removed(lua) == [1], (dict(r), removed(lua))
    assert it.flags.removed and not it.flags.in_building and it.flags.trader, dict(it.flags)
    types = lua.eval("(function(it) local o = {} for _, r in ipairs(it.general_refs) do "
                     "table.insert(o, r:getType()) end return table.concat(o, ',') end)")(it)
    assert types == "7", types                          # the BUILDING_HOLDER ref gone, ENTITY_ITEMOWNER kept


@test("lua (item17): a good DFHack would refuse anyway (specific ref, cage, world data) is kept untouched")
def _():
    need_lua()
    lua, env = lua_env()
    lua.execute("""local env = ...
        local ci = env.df.global.world.buildings.other.TRADE_DEPOT[1].contained_items
        ci[1].item.specific_refs = {{type = 1}}
        table.insert(ci[2].item.general_refs, {getType = function() return 11 end})""", env)
    r = env.clear_caravan_goods(308, 200, True, None)
    assert r.ok and r.goods == 1 and r.kept.specific_ref == 1 and r.kept["ref BUILDING_CAGED"] == 1, dict(r.kept)
    r = env.clear_caravan_goods(308, 200, False, None)
    assert removed(lua) == [50, 51, 52], removed(lua)
    flags = lua.execute("""local env = ...
        local ci = env.df.global.world.buildings.other.TRADE_DEPOT[1].contained_items
        return ci[1].item.flags.in_building and ci[2].item.flags.in_building""", env)
    assert flags


@test("lua (item17): a refusal is counted with the first one's reason; the good left on the floor is forbidden")
def _():
    need_lua()
    lua, env = lua_env()
    lua.execute("REFUSE[2] = true")
    it2 = lua.execute("""local env = ...
        return env.df.global.world.buildings.other.TRADE_DEPOT[1].contained_items[2].item""", env)
    r = env.clear_caravan_goods(308, 200, False, None)
    assert r.ok and r.removed == 2 and r.failed == 1 and "item 2" in str(r.first_failure), dict(r)
    assert it2.flags.forbid and it2.flags.trader and not it2.flags.removed
    lua, env = lua_env()
    lua.execute("for _, i in ipairs({1, 2, 50, 51, 52}) do REFUSE[i] = true end")
    r = env.clear_caravan_goods(308, 200, False, None)
    assert not r.ok and r.failed == 3 and "refused" in str(r.error) and "item 1" in str(r.error), dict(r)


@test("lua: refused while trading, its time not run out, a merchant at the depot, another caravan coming, the screen open")
def _():
    need_lua()
    for setup, word in (("env.df.global.plotinfo.caravans[1].trade_state = 2", "AtDepot"),
                        ("env.df.global.plotinfo.caravans[1].time_remaining = 300", "ticks left"),
                        ("env.df.global.world.units.active[1].x = 5; env.df.global.world.units.active[1].y = 5",
                         "at the depot"),
                        ("table.insert(env.df.global.plotinfo.caravans, {entity = 9, trade_state = 1, "
                         "time_remaining = 900, flags = {tribute = false}})", "another caravan"),
                        ("env.df.global.game.main_interface.trade.open = true", "trade screen")):
        lua, env = lua_env()
        lua.execute("local env = ...; " + setup, env)
        r = env.clear_caravan_goods(308, 200, False, None)
        assert not r.ok and r.rejected and word in str(r.error) and removed(lua) == [], (word, dict(r))
    lua, env = lua_env()
    r = env.clear_caravan_goods(999, 200, False, None)
    assert not r.ok and "no caravan" in str(r.error)


@test("lua: another civilisation's goods (ENTITY_ITEMOWNER) stay; the limit holds whole bins")
def _():
    need_lua()
    lua, env = lua_env()
    lua.execute("""local env = ...
        local it = env.df.global.world.buildings.other.TRADE_DEPOT[1].contained_items[1].item
        it.general_refs = {{entity_id = 77, getType = function() return 7 end}}""", env)
    r = env.clear_caravan_goods(308, 2, False, None)
    assert r.ok and removed(lua) == [2], removed(lua)          # 1 is another's; the bin (3) is past the limit
    assert r.kept.other_owner == 1


finish()
