"""Tests for lua/ai-trade.lua (goods for the depot), in a real Lua engine
with a small fake of the game's items (pip install lupa).

    python tests/test_trade.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
from harness import test, finish  # noqa: E402

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = module_src("ai-trade.lua")

FAKE = r"""
local src = ...
local TYPES = {FIGURINE = 1, AMULET = 2, BIN = 3}
TYPES[1], TYPES[2], TYPES[3] = 'FIGURINE', 'AMULET', 'BIN'    -- (both ways, as DFHack's enums)
local function item(id, t, mat, extra)
    local it = {id = id, t = t, mat = mat, value = 10,
                flags = {on_ground = true, in_inventory = false}}
    for k, v in pairs(extra or {}) do it.flags[k] = v end
    it.getType = function(self) return self.t end
    it.getMaterial = function(self) return self.mat end
    return it
end
-- a bin of 3 stone figurines; a bin with a wooden figurine among them; a
-- loose stone amulet; a loose wooden figurine; a forbidden amulet
local bin1, bin2 = item(100, 3, 0), item(101, 3, 0)
local inside = {[100] = {}, [101] = {}}
local container = {}
local figs, amulets = {}, {}
for i = 1, 3 do
    local f = item(i, 1, 0, {on_ground = false, in_inventory = true})
    table.insert(figs, f); table.insert(inside[100], f); container[f.id] = bin1
end
local wood = item(10, 1, 420, {on_ground = false, in_inventory = true})
local stone_in_2 = item(11, 1, 0, {on_ground = false, in_inventory = true})
table.insert(figs, wood); table.insert(figs, stone_in_2)
table.insert(inside[101], wood); table.insert(inside[101], stone_in_2)
container[10], container[11] = bin2, bin2
table.insert(amulets, item(20, 2, 0))
table.insert(figs, item(21, 1, 420))
table.insert(amulets, item(22, 2, 0, {forbid = true}))
local marked = {}
local env = setmetatable({}, {__index = _G})
env.df = {item_type = TYPES,
          global = {world = {items = {other = {FIGURINE = figs, AMULET = amulets}},
                             buildings = {other = {TRADE_DEPOT = {}}}},
                    plotinfo = {caravans = {}}},
          caravan_state = {T_trade_state = {Approaching = 1, AtDepot = 2}}}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
env.dfhack = {items = {getValue = function(it) return it.value end,
                       getPosition = function() return 1, 1, 1 end,
                       getContainer = function(it) return container[it.id] end,
                       getContainedItems = function(c) return inside[c.id] or {} end,
                       markForTrade = function(it) table.insert(marked, it.id); return true end},
              maps = {canWalkBetween = function() return true end}}
assert(load(src, 'ai-trade', 't', env))()
local depot = {centerx = 5, centery = 5, z = 1, contained_items = {},
               getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
env.df.global.world.buildings.other.TRADE_DEPOT = {depot}
return env, marked
"""


@test("goods in a bin count (0.46's bins hid every craft); a bin with a wooden one among them stays")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(FAKE, SRC)
    s = env.survey()
    assert s.depot and s.goods == 4 and s.loads == 2 and s.goods_value == 40, dict(s)   # bin1 (3) + amulet


@test("trade_material (0.104.95): stone, metal, gems and the three glasses sell; wood and animal goods don't")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(FAKE, SRC)
    item = lua.eval("function(mt) return {getMaterial = function() return mt end} end")
    assert [env.trade_material(item(m)) for m in (0, 3, 4, 5)] == [True] * 4
    assert [env.trade_material(item(m)) for m in (1, 7, 419, 420)] == [False] * 4


@test("bring: the whole bin goes to the depot, with the loose goods")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(FAKE, SRC)
    lua.execute("""local env = ...
        env.df.global.plotinfo.caravans = {{entity = 1, trade_state = 1, time_remaining = 100,
                                            flags = {tribute = false}}}
        env.df.historical_entity = {find = function() return nil end}""", env)
    r = env.bring(40, False)
    got = sorted(marked[i] for i in range(1, len(marked) + 1))
    assert r.ok and r["items"] == 4 and got == [20, 100], (dict(r), got)


@test("bring (0.96): a grasping fort keeps gems and precious metal home; others still go")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(FAKE, SRC)
    lua.execute("""local env = ...
        env.df.global.plotinfo.caravans = {{entity = 1, trade_state = 1, time_remaining = 100,
                                            flags = {tribute = false}}}
        env.df.historical_entity = {find = function() return nil end}
        env.dfhack.matinfo = {decode = function(it)
            if it.id == 20 then return {inorganic = {id = 'GOLD'}} end
            return {inorganic = {id = 'GRANITE'}} end}""", env)
    r = env.bring(40, False, None, True)
    got = sorted(marked[i] for i in range(1, len(marked) + 1))
    assert r.ok and r["items"] == 3 and got == [100], (dict(r), got)          # the gold amulet stays
    r = env.bring(40, True)
    assert r.ok and r["items"] == 4, dict(r)                                  # not asked: it goes


SCREEN = r"""
local src = ...
local NAMES = {'BAR', 'CLOTH', 'FIGURINE', 'AMULET', 'BIN', 'BARREL', 'DRINK', 'WOOD', 'GEM'}
local item_type = {}
for i, n in ipairs(NAMES) do item_type[n] = i; item_type[i] = n end
local function vec(list)            -- a DF vector: 0-based, # its length
    local v = {}
    for i, x in ipairs(list) do v[i - 1] = x end
    return setmetatable(v, {__len = function() return #list end})
end
local function item(t, value, extra)
    local it = {t = item_type[t], value = value, n = 1, mat = 0, token = 'INORGANIC:STONE', inside = {}}
    for k, v in pairs(extra or {}) do it[k] = v end
    it.getType = function(self) return self.t end
    it.getMaterial = function(self) return self.mat end
    it.getStackSize = function(self) return self.n end
    return it
end
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if getmetatable(t) and getmetatable(t).__len then
        local i, n = -1, #t
        return function() i = i + 1; if i < n then return i, t[i] end end
    end
    return ipairs(t)
end
-- merchants: steel bars 2x (40 each), iron bar (10), cloth (8), a barrel of drink
-- (5 + 6x 2), gold bar (150, not wanted); fort: a bin (30) with 3 figurines (25 each),
-- an amulet (20), a wooden figurine (15)
local drink = item('DRINK', 2, {n = 6})
local barrel = item('BARREL', 5, {inside = {drink}})
local merch = {item('BAR', 40, {token = 'INORGANIC:STEEL'}), item('BAR', 40, {token = 'INORGANIC:STEEL'}),
               item('BAR', 10, {token = 'INORGANIC:IRON'}), item('CLOTH', 8, {mat = 420}),
               barrel, drink, item('BAR', 150, {token = 'INORGANIC:GOLD'})}
local mflags = {}
for i = 1, #merch do mflags[i] = {selected = false, contained = (merch[i] == drink)} end
local figs = {item('FIGURINE', 25), item('FIGURINE', 25), item('FIGURINE', 25)}
local bin = item('BIN', 30, {inside = figs})
local fort = {bin, figs[1], figs[2], figs[3], item('AMULET', 20), item('FIGURINE', 15, {mat = 420})}
local fflags = {}
for i = 1, #fort do fflags[i] = {selected = false, contained = (i >= 2 and i <= 4)} end
local saved = {}
env.df = {item_type = item_type,
          talk_line_type = {[8] = 'Trade', [23] = 'Haggle', [24] = 'CounterOffer'},
          global = {world = {items = {other = {}}, buildings = {other = {TRADE_DEPOT = {}}}},
                    plotinfo = {caravans = {}},
                    gps = {mouse_x = 40, mouse_y = 50, dimx = 120, dimy = 60, tile_pixel_x = 8, tile_pixel_y = 12},
                    game = {main_interface = {trade = {open = true, havetalker = 1, stillunloading = 0,
                        counter_offer = false, talkline = -1, mer = {},
                        good = {[0] = vec(merch), [1] = vec(fort)},
                        goodflag = {[0] = vec(mflags), [1] = vec(fflags)},
                        good_amount = {[0] = vec({}), [1] = vec({})}}}}},
          caravan_state = {T_trade_state = {Approaching = 1, AtDepot = 2}}}
env.dfhack = {items = {getValue = function(it) return it.value end,
                       getContainedItems = function(c) return c.inside end,
                       getDescription = function(it) return item_type[it.t]:lower() end},
              matinfo = {decode = function(it) return {getToken = function() return it.token end} end},
              persistent = {getSiteData = function(k, d) return saved[k] or d end,
                            saveSiteData = function(k, v) saved[k] = v end},
              screen = {readTile = function() return nil end},
              gui = {getDFViewscreen = function() return {} end}}
env.reqscript = function() error('no DFHack scripts here') end
local clicks = {}
env.require = function(name)
    if name == 'gui' then
        return {simulateInput = function(scr, key)
            table.insert(clicks, {env.df.global.gps.mouse_x, env.df.global.gps.mouse_y, key})
            local t = env.df.global.game.main_interface.trade
            if key == 'LEAVESCREEN' then t.open = false; return end
            -- COUNTER: the first click gets a counter-offer: one more craft ticked
            if env.COUNTER and not t.countered then
                t.countered, t.talkline, t.counter_offer = true, 24, true
                for i = 0, #t.goodflag[1] - 1 do
                    if not t.goodflag[1][i].selected and i ~= 0 and i ~= 5 then t.goodflag[1][i].selected = true; break end
                end
                return
            end
            -- the fake merchants accept: the ticked goods leave both lists
            t.talkline = 8
            t.good[0] = vec({merch[7]}); t.goodflag[0] = vec({{selected = false}})
        end}
    end
    return require(name)
end
assert(load(src, 'ai-trade', 't', env))()
return env, mflags, fflags, clicks
"""


@test("bring (0.103.9): rings, figurines and the like stay home when asked; unload takes the goods back out")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(FAKE, SRC)
    lua.execute("""local env = ...
        env.df.global.plotinfo.caravans = {{entity = 1, trade_state = 1, time_remaining = 100,
                                            flags = {tribute = false}}}
        env.df.historical_entity = {find = function() return nil end}""", env)
    r = env.bring(40, False, None, False, True)
    assert not r.ok and len(marked) == 0, dict(r)                 # only figurines and amulets here: all stay
    r = env.bring(40, True)
    assert r.ok and r["items"] == 4, dict(r)                      # not asked: they go
    # unload: refused while a caravan is about; then the depot's TEMP items set down
    r = env.unload(50, False)
    assert not r.ok and "caravan" in r.error, dict(r)
    moved = lua.execute("""local env = ...
        env.df.global.plotinfo.caravans = {}
        env.df.building_item_role_type = {TEMP = 0, PERM = 2}
        local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
        local moved = {}
        local function it(id) return {id = id, flags = {in_building = true}} end
        dep.contained_items = {{use_mode = 2, item = it(1)}, {use_mode = 0, item = it(2)}, {use_mode = 0, item = it(3)}}
        env.dfhack.items.moveToGround = function(item, pos)
            item.flags.in_building = false; table.insert(moved, item.id); return true end
        return moved""", env)
    r = env.unload(50, True)
    assert r.ok and r.dry_run and r["items"] == 2 and len(moved) == 0, dict(r)
    r = env.unload(1, False)
    assert r.ok and r["items"] == 1 and r.left == 1 and [moved[i] for i in range(1, len(moved) + 1)] == [2], dict(r)


@test("trade probe: merchants on side 0, the fort on side 1; what they have that's useful; survives a closed screen")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(FAKE, SRC)
    r = env.probe_screen(None)
    assert r.open is False, dict(r)
    env, mf, ff, clicks = lua.execute(SCREEN, SRC)
    r = env.probe_screen(None)
    assert r.open and r.sides[1].who == "merchants" and r.sides[1].count == 7 and r.sides[2].count == 6
    have = dict(r.merchants_have)
    assert have == {"BAR:STEEL": 2, "BAR:IRON": 1, "BAR:GOLD": 1, "CLOTH": 1, "DRINK": 6}, have
    assert r.fort_can_give.goods == 4 and r.fort_can_give.value == 95, dict(r.fort_can_give)  # 3 figs + amulet, no wood


@test("pick_buys: wants in order, cheapest a unit first, within the budget")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, *_ = lua.execute(SCREEN, SRC)
    t = lua.table_from
    cands = t([t({"idx": 1, "cat": "BAR:STEEL", "n": 1, "value": 40}), t({"idx": 2, "cat": "BAR:STEEL", "n": 1, "value": 30}),
               t({"idx": 3, "cat": "CLOTH", "n": 1, "value": 8})])
    picks, spent = env.pick_buys(cands, t([t({"key": "BAR:STEEL", "count": 5}), t({"key": "CLOTH", "count": 1})]), 75)
    got = [picks[i].idx for i in range(1, len(picks) + 1)]
    assert got == [2, 1] and spent == 70, (got, spent)      # 30 then 40; the cloth (8) no longer fits


@test("pick_offers: covers the target with little over")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, *_ = lua.execute(SCREEN, SRC)
    t = lua.table_from
    offers = t([t({"idx": i, "value": v}) for i, v in enumerate([25, 25, 25, 20], start=1)])
    picks, total = env.pick_offers(offers, 46)
    assert total == 50 and len(picks) == 2, total


@test("deal: ticks wanted goods and enough crafts (margin); dry run ticks nothing; press clicks the calibrated spot")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, mf, ff, clicks = lua.execute(SCREEN, SRC)
    t = lua.table_from
    wants = t([t({"key": "BAR:STEEL", "count": 1}), t({"key": "DRINK", "count": 10}), t({"key": "BAR:GOLD", "count": 0})])
    r = env.deal(wants, 1.2, True, None)
    assert r.ok and r.dry_run and not any(mf[i].selected for i in range(1, 8)), dict(r)
    r = env.deal(wants, 1.2, False, None)
    # budget 95 / 1.2 = 79: one steel (40) + the barrel of drink (5 + 2) = 47; give >= 57: 25+25+20
    assert r.buy_value == 47 and r.give_value == 70, dict(r)
    ticked = [i for i in range(1, 8) if mf[i].selected]
    assert ticked == [1, 5], ticked                       # the barrel, not the drink inside it
    assert not ff[1].selected and not ff[6].selected      # never the bin itself, never wood
    assert r.calibrated is False
    p = env.press("Trade", None)
    assert p.ok is False and "calibrate" in p.error
    env.calibrate("Trade")                                 # the mouse is at 40, 50 on a 120x60 screen
    p = env.press("Trade", None)
    assert p.ok and p.answer == "Trade" and p.traded and clicks[1][1] == 40 and clicks[1][2] == 50, dict(p)
    assert clicks[2][3] == "LEAVESCREEN" and p.closed, dict(p)          # the screen closed after the trade


@test("press: a counter-offer of a few more crafts is given and pressed again; the margin is learned")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, mf, ff, clicks = lua.execute(SCREEN, SRC)
    t = lua.table_from
    env.COUNTER = True
    env.deal(t([t({"key": "BAR:STEEL", "count": 1})]), 1.2, False, None)   # steel 40, give 50 (2 figurines)
    env.calibrate("Trade")
    p = env.press("Trade", None)
    assert p.ok and p.counter.accepted and p.counter["items"] == 1 and p.answer == "Trade" and p.traded, dict(p)
    assert env.learned_margin() > 1.2, env.learned_margin()
    env, *_ = lua.execute(SCREEN, SRC)                     # the next caravan: the learned margin is used
    env.save_margin(1.5)
    r = env.deal(t([t({"key": "BAR:STEEL", "count": 1})]), 1.2, True, None)
    assert r.margin == 1.5, dict(r)


@test("call_trader: the broker asked for; anyone may trade a day after the caravan got there; back off once it's gone")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(FAKE, SRC)
    lua.execute("""local env = ...
        local saved = {}
        env.dfhack.persistent = {getSiteData = function(k, d) return saved[k] or d end,
                                 saveSiteData = function(k, v) saved[k] = v end}
        env.dfhack.job = {getWorker = function() return nil end}
        local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
        dep.trade_flags = {trader_requested = false, anyone_can_trade = false}
        dep.jobs = {}
        env.DEP = dep
        env.df.global.plotinfo.caravans = {{entity = 1, trade_state = 2, time_remaining = 100,
                                            flags = {tribute = false}}}
        env.df.historical_entity = {find = function() return nil end}
        env.df.caravan_state.T_trade_state[2] = 'AtDepot'""", env)
    r = env.call_trader(1000, 1200, False, None)
    assert r.requested and env.DEP.trade_flags.trader_requested and not env.DEP.trade_flags.anyone_can_trade, dict(r)
    r = env.call_trader(1500, 1200, False, None)
    assert not r.anyone and r.waiting_ticks == 500, dict(r)
    r = env.call_trader(2300, 1200, False, None)
    assert r.anyone and env.DEP.trade_flags.anyone_can_trade, dict(r)
    lua.execute("local env = ...; env.df.global.plotinfo.caravans = {}", env)
    r = env.call_trader(3000, 1200, False, None)
    assert r.waiting and not env.DEP.trade_flags.anyone_can_trade, dict(r)


@test("open_screen: the depot's sheet, then a click on its Trade button a few frames later; once a visit")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, mf, ff, clicks = lua.execute(SCREEN, SRC)
    lua.execute("""local env = ...
        local t = env.df.global.game.main_interface.trade
        t.open = false
        local mer = {entity = 7, import_value = 1000, trade_state = 2}
        t.mer = mer
        env.df.global.plotinfo.caravans = {mer}
        env.df.caravan_state.T_trade_state.AtDepot = 2
        local broker = {x = 5, y = 5, z = 1}
        local job = {job_type = 99}
        local dep = {id = 3, x1 = 4, x2 = 6, y1 = 4, y2 = 6, z = 1, centerx = 5, centery = 5, jobs = {job},
                     trade_flags = {}, contained_items = {{item = {flags = {trader = true}}}},
                     getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
        env.df.global.world.buildings.other.TRADE_DEPOT = {dep}
        env.df.job_type = {TradeAtDepot = 99}
        env.df.view_sheet_type = {BUILDING = 2, NONE = -1}
        env.df.global.game.main_interface.view_sheets = {open = false}
        env.dfhack.job = {getWorker = function() return broker end}
        env.dfhack.units = {getPosition = function(u) return u.x, u.y, u.z end}
        env.dfhack.gui.matchFocusString = function(f) return f == 'dwarfmode/Default' end
        env.dfhack.timeout = function(n, unit, fn) env.PENDING = fn end
        local saved_sim = env.require('gui').simulateInput
        env.require = function(name)
            return {simulateInput = function(scr, key)
                table.insert(env.CLICKS, {env.df.global.gps.mouse_x, env.df.global.gps.mouse_y, key})
                if key == 'LEAVESCREEN' then t.open = false
                elseif env.df.global.game.main_interface.view_sheets.open then t.open = true end
            end}
        end
        env.CLICKS = {}
        env.df.global.cur_year, env.df.global.cur_year_tick = 50, 1000""", env)
    r = env.open_screen(False, None)
    assert r.waiting and "still unloading" in r.error, dict(r)      # goods only just seen
    lua.execute("local env = ...; env.df.global.cur_year_tick = 1400", env)
    r = env.open_screen(False, None)
    assert r.ok is False and "here-depot" in r.error, dict(r)       # not shown the button yet
    lua.execute("""local env = ...
        env.dfhack.persistent.saveSiteData('ai-overseer/trade-buttons',
            {Depot = {anchor = 'right-top', rx = 20, ty = 10}})""", env)
    r = env.open_screen(False, None)
    assert r.ok and r.clicking and list(r.at.values()) == [100, 10], dict(r)    # 120 - 20
    env.PENDING()
    tr = env.df["global"].game.main_interface.trade
    assert tr.open and env.opened_by_ai() and env.df["global"].game.main_interface.view_sheets.open is False
    c = env.close_screen(True)                          # opened too early: closed, not done
    assert c.closed and not tr.open
    r = env.open_screen(False, None)
    assert r.waiting and "unloaded" in r.error, dict(r)
    lua.execute("local env = ...; env.df.global.cur_year_tick = 2100", env)
    r = env.open_screen(False, None)
    assert r.ok and r.clicking, dict(r)                 # tried again later
    env.PENDING()
    c = env.close_screen()
    assert c.closed and not tr.open
    r = env.open_screen(False, None)                    # this caravan is done for this visit
    assert r.waiting and "already traded" in r.error, dict(r)


@test("category: soap bars and tallow globs (for the hospital's soap)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, *_ = lua.execute(SCREEN, SRC)
    lua.execute("""local env = ...
        env.df.item_type.GLOB = 20; env.df.item_type[20] = 'GLOB'
        local function it(t, tok) return {t = env.df.item_type[t], token = tok,
            getType = function(self) return self.t end} end
        env.SOAP = it('BAR', 'CREATURE_MAT:COW:SOAP')
        env.TALLOW = it('GLOB', 'CREATURE_MAT:COW:TALLOW')
        env.FAT = it('GLOB', 'CREATURE_MAT:COW:FAT')""", env)
    assert env.category(env.SOAP) == "SOAP" and env.category(env.TALLOW) == "TALLOW" and env.category(env.FAT) is None


if __name__ == "__main__":
    finish()
