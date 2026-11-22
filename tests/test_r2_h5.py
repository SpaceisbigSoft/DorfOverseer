"""(r2 h5) Trade has never made a deal: about 40 fort-years in six forts.

The steps from a caravan arriving to a deal, and where each fort stopped
(journals and keeper logs of the 14-16 Nov runs, /home/claude/run2/<A-F>/):
  1. the caravan comes: bring_goods, call_trader (A 69/53, B 25/21, C 73/69,
     E 65/78, F 25/39 calls, all ok);
  2. the broker (or anyone, after a day) walks to the depot;
  3. the merchants unload; the AI waits till their goods hold still;
  4. open_trade: the depot's sheet, its Trade button clicked. HERE every
     fort stopped. F's only click (14 Nov 00:51:04, x74 y15, the October
     place) opened no trade screen; the guess was retired at once, and in the
     15-16 Nov run no fort tried again: `trade.trader.can_open` false in
     A, B, C, E, F, the "can't open the trade screen" Needs you 3-38 times a
     fort, `open_trade` 0 times, `trade_deal` 0 times. (D, Trade -100, never
     trades, by design.)
  5. trade_deal ticks the goods and presses the screen's Trade button (its
     guess retired too: never reached);
  6. the caravan leaves; unload_depot takes the fort's goods back out.
Also: the merchants' own goods counted as "the fort's goods in the depot"
(D: unload_depot refused 50 times while its caravan was there; B: 48 times
over ten years, 325 goods of a caravan that never left), a child sent to
trade, "anyone" let in while the broker was on his way, the trade job left
standing after the caravans (E), and a caravan that never left (B y251)
said nowhere.

    python tests/test_r2_h5.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src, bridge_part_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_trade as TT  # noqa: E402  (its fakes; its tests don't run again)
import test_r47_meetings_trade as R47  # noqa: E402
from planner import PLANNER_CONFIG  # noqa: E402
from planner_trade import _trade_rules  # noqa: E402

TRADE_SRC = module_src("ai-trade.lua")
KEY = "ai-overseer/trade-buttons"


def lst(t):
    return [] if t is None else [t[i] for i in range(1, len(t) + 1)]


# --- step 4: the depot's Trade button ------------------------------------------------

# the click opens the trade screen only on the button (TX, TY); anywhere else the goods screen
CLICK_AT = r"""local env, tx, ty = ...
env.CLICKS = {}
env.require = function(name)
  if name == 'json' then
    return {decode_file = function(p) if env.FILES[p] then return env.FILES[p] end error('none') end,
            encode_file = function(d, p) env.FILES[p] = d end}
  end
  return {simulateInput = function(_, key)
    local mi = env.df.global.game.main_interface
    if key == '_MOUSE_L' then
      local g = env.df.global.gps
      table.insert(env.CLICKS, {g.mouse_x, g.mouse_y})
      if g.mouse_x == tx and g.mouse_y == ty then mi.trade.open = true else mi.assign_trade.open = true end
    end
    if key == 'LEAVESCREEN' then mi.assign_trade.open = false; mi.trade.open = false end
  end}
end"""


def depot_env(tx=92, ty=18):
    lua, env, B, mf, ff, clicks = R47.trade_env()
    lua.execute(R47.DEPOT_SETUP, env)
    lua.execute(CLICK_AT, env, tx, ty)
    return lua, env, B


def paint_sheet(lua, env, button=True):
    """DF 53.17's depot sheet as the AI might find it (120x60 screen): the
    title, the Trade button elsewhere than the October place (44, 15), the
    broker's line."""
    R47.paint(lua, env, 80, 3, "Trade depot")
    if button:
        R47.paint(lua, env, 90, 18, "Trade")
    R47.paint(lua, env, 90, 20, "Request trader")


def retire(B):
    B.miss(KEY, "Depot", "clicked and the trade screen did not open")
    B.miss(KEY, "Depot", "clicked and the trade screen did not open")


@test("step 4 (all six forts): the guess retired, the depot's Trade button is found by its word and the screen opens")
def _():
    lua, env, B = depot_env()
    retire(B)                                          # as in A, B, C, E, F after their first click
    paint_sheet(lua, env)
    assert env.buttons().Depot is None
    assert env.can_open_now() is True                  # before: can_open false, a Needs you every caravan
    r = env.open_screen(False, None)
    assert r.ok and r.clicking and r.search, dict(r)   # before: rejected, "here-depot"
    lua.execute("local env = ...; env.TIMERS[1]()", env)
    lo = env.LAST_OPEN
    assert lo.how == "found" and lst(lo.at) == [92, 18] and lo.opened, dict(lo)      # "Trade" 90-94: its middle
    assert env.df["global"].game.main_interface.trade.open and env.opened_by_ai()
    assert lst(env.CLICKS[1]) == [92, 18]               # never on the title "Trade depot" (x80 y3)


@test("step 4: the guess reads no Trade (DF 53.17's sheet laid out otherwise): looked for by its word, not given up")
def _():
    lua, env, B = depot_env()
    paint_sheet(lua, env)
    r = env.open_screen(False, None)
    assert r.ok and r.clicking and r.guessed and lst(r.at) == [44, 15], dict(r)
    lua.execute("local env = ...; env.TIMERS[1]()", env)
    assert env.LAST_OPEN.how == "found" and env.df["global"].game.main_interface.trade.open, dict(env.LAST_OPEN)
    assert B.read_file().misses[KEY].Depot == 1          # the guess's own miss still counted


@test("step 4: text that can't be read: nothing clicked blind, can_open false (the Needs you); no word: 3 tries a visit")
def _():
    lua, env, B = depot_env()
    retire(B)                                          # no paint: readTile answers nothing (TrueType)
    lua.execute("local env = ...; env.dfhack.screen = {readTile = function() return nil end}", env)
    r = env.open_screen(False, None)
    assert r.ok and r.clicking and r.search, dict(r)
    lua.execute("local env = ...; env.TIMERS[1]()", env)
    assert env.LAST_OPEN.clicked is False and env.LAST_OPEN.search == "unreadable", dict(env.LAST_OPEN)
    assert len(lst(env.CLICKS)) == 0 and env.can_open_now() is False
    assert env.df["global"].game.main_interface.view_sheets.open is False
    # readable, but no Trade button on the sheet (only the title and "Request trader")
    lua, env, B = depot_env()
    retire(B)
    paint_sheet(lua, env, button=False)
    for i in range(3):
        lua.execute("local env, i = ...; env.df.global.cur_year_tick = 5000 + i * 700; env.TIMERS = {}", env, i)
        r = env.open_screen(False, None)
        assert r.ok and r.clicking, (i, dict(r))
        lua.execute("local env = ...; env.TIMERS[1]()", env)
        assert env.LAST_OPEN.search == "none" and env.LAST_OPEN.tries == i + 1, dict(env.LAST_OPEN)
        assert env.LAST_OPEN.sheet is not None                # the sheet's text kept for the report
    lua.execute("local env = ...; env.df.global.cur_year_tick = 8000", env)
    r = env.open_screen(False, None)
    assert r.ok is False and "didn't find it" in r.error and env.can_open_now() is False, dict(r)
    assert len(lst(env.CLICKS)) == 0


@test("step 4: the survey says can_open by its word and what the last try did (the Needs you says it too)")
def _():
    lua, env, B = depot_env()
    retire(B)
    paint_sheet(lua, env, button=False)
    lua.execute(r"""local env = ...
        env.df.global.world.items.other.SMALLGEM = {}
        env.df.global.world.items.other.ROUGH = {}
        env.df.building_item_role_type = {TEMP = 0}
        env.df.global.world.units = {active = {}}
        env.df.historical_entity = {find = function() return nil end}""", env)
    s = env.survey(None)
    assert s.trader.can_open is True and s.trader.search == "by its word", dict(s.trader)
    env.open_screen(False, None)
    lua.execute("local env = ...; env.TIMERS[1]()", env)
    s = env.survey(None)
    assert s.trader.last_open.search == "none", dict(s.trader)
    st = {"trade": {"depot": True, "caravans": [{"civ": "The Moral Wire", "state": "AtDepot"}], "at_depot": 30,
                    "trader": {"at_depot": True, "can_open": False, "fresh": True,
                               "last_open": {"clicked": False, "error": "no Trade button found on the depot's sheet"}}},
          "buildings": {}, "dwarves": {"adults": 10}}
    props, notes = [], []
    _trade_rules(st, PLANNER_CONFIG, 10, props, notes, {"trade": 0}, None)
    assert any("no Trade button found" in str(n) for n in notes), notes


# --- step 5: the trade screen's Trade button ----------------------------------------------

def press_env():
    lua, env, B, mf, ff, clicks = R47.trade_env()
    B.miss(KEY, "Trade", "pressed and the merchants said nothing")
    B.miss(KEY, "Trade", "pressed and the merchants said nothing")
    lua.execute("local env = ...; env.OPEN_CLICKED_AT = os.time(); env.OPENED_FOR = nil", env)
    return lua, env, B, clicks


@test("step 5: the Trade guess retired, the screen's Trade found on its bottom rows (away from Offer and Seize) and pressed")
def _():
    lua, env, B, clicks = press_env()
    R47.paint(lua, env, 50, 57, "Trade")
    R47.paint(lua, env, 62, 57, "Offer")
    R47.paint(lua, env, 72, 57, "Seize")
    assert env.buttons().Trade is None
    r = env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    assert r.ok and r.calibrated is False and r.can_search, dict(r)
    p = env.press("Trade", None)
    assert p.pressed == "Trade" and p.how == "found" and lst(p.at) == [52, 57] and p.traded and p.answer == "Trade", dict(p)
    # (the bridge presses on can_search, and closes its screen when nothing could be pressed)
    act = bridge_part_src("ai-bridge-actions")
    assert code_has(act, "a.press == true and (r.calibrated or r.can_search)")
    assert code_has(act, "if p.rejected and not p.pressed and not p.closed and a.close == true")


@test("step 5: a Trade label with a Seize by it is never pressed; unreadable text: nothing pressed")
def _():
    lua, env, B, clicks = press_env()
    R47.paint(lua, env, 50, 57, "Trade")
    R47.paint(lua, env, 51, 58, "Seize")              # just under it: the click could land on Seize
    env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    p = env.press("Trade", None)
    assert p.ok is False and p.rejected and p.search == "none", dict(p)
    assert all(lst(clicks[i])[2] != "_MOUSE_L" for i in range(1, len(clicks) + 1))
    lua, env, B, clicks = press_env()                  # no paint: readTile answers nothing
    env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    p = env.press("Trade", None)
    assert p.ok is False and p.search == "unreadable" and "calibrate" in p.error, dict(p)
    assert len(clicks) == 0


@test("label_hits: a standalone label only: not Trader, not 'Trade depot', not inside a word")
def _():
    lua, env, G = R47.store()
    t = lua.table_from
    hits = env.label_hits(t(["Trade depot   [Trade]  Request trader  Traders  ", " retrade Trade"]), "Trade",
                          t({"depot": True}))
    got = [lst(hits[i]) for i in range(1, len(hits) + 1)]
    assert got == [[16, 1], [10, 2]], got


# --- step 6 and the depot's goods ----------------------------------------------------------

UNLOAD = r"""local env, theirs, ours = ...
env.df.global.plotinfo.caravans = {}
env.df.building_item_role_type = {TEMP = 0, PERM = 2}
env.df.global.world.units = {active = {}}
env.df.global.world.items.other.SMALLGEM = {}
env.df.global.world.items.other.ROUGH = {}
env.df.historical_entity = {find = function() return nil end}
local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
dep.contained_items = {}
local moved = {}
-- the merchants' goods first, as B's 325: the game never lets them be moved
for i = 1, theirs do
  table.insert(dep.contained_items, {use_mode = 0, item = {id = i, flags = {in_building = true, trader = true}}})
end
for i = 1, ours do
  table.insert(dep.contained_items, {use_mode = 0, item = {id = 1000 + i, flags = {in_building = true}}})
end
env.dfhack.items.moveToGround = function(item, pos)
  if item.flags.trader then return false end
  item.flags.in_building = false; table.insert(moved, item.id); return true
end
return moved"""


@test("step 6 (B, D): the merchants' goods aren't 'the fort's goods in the depot'; the fort's own are taken out past them")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(TT.FAKE, TRADE_SRC)
    moved = lua.execute(UNLOAD, env, 60, 12)
    s = env.survey(None)
    assert s.at_depot == 12 and s.merchant_goods == 60, (s.at_depot, s.merchant_goods)     # before: 72
    r = env.unload(50, False)
    # before: the first 50 were the merchants' ("none moved out of the depot: the game kept it in the depot")
    assert r.ok and r["items"] == 12 and len(lst(moved)) == 12, dict(r)
    env, marked = lua.execute(TT.FAKE, TRADE_SRC)
    lua.execute(UNLOAD, env, 325, 0)                    # B, y251-261: only the caravan's own goods
    s = env.survey(None)
    assert s.at_depot == 0, s.at_depot                  # so unload_depot isn't asked for (48 refusals)
    r = env.unload(50, False)
    assert r.rejected and r.merchant_goods == 325 and "merchants' own" in r.error, dict(r)


def state(caravans, goods_at_depot=20, **trader):
    return {"trade": {"depot": True, "caravans": caravans, "at_depot": goods_at_depot, "goods": 0,
                      "trader": dict({"at_depot": False, "can_open": True, "fresh": True}, **trader)},
            "buildings": {}, "dwarves": {"adults": 10}}


@test("step 6 (D, Trade -100): no unload_depot while the caravan it leaves alone is at the depot; after it, yes")
def _():
    s = state([{"civ": "The Moral Wire", "state": "AtDepot"}])
    props, notes = [], []
    _trade_rules(s, PLANNER_CONFIG, 10, props, notes, {"trade": -100}, None)
    assert not any(p.action["type"] == "unload_depot" for p in props), [p.action for p in props]   # before: 50 a run
    s = state([])
    props, notes = [], []
    _trade_rules(s, PLANNER_CONFIG, 10, props, notes, {"trade": -100}, None)
    assert any(p.action["type"] == "unload_depot" for p in props), [p.action for p in props]


@test("deal: a fort that needs nothing still trades its crafts (the fallback wants), not 'close the screen'")
def _():
    big = {k: 100000 for k in ("prepared_meals", "drink", "cloth", "leather", "thread", "wood")}
    s = state([{"civ": "The Moral Wire", "state": "AtDepot"}], goods_at_depot=40, at_depot=True)
    s["trade"]["screen"] = {"open": True, "ready": True, "by_ai": True}
    s["stocks"] = big
    s["supplies"] = {"fuel": 100000, "soap": 100}
    s["military"] = {"gear": {"bars": {"STEEL": 1000, "IRON": 1000}}}
    props, notes = [], []
    _trade_rules(s, PLANNER_CONFIG, 10, props, notes, {"trade": 0}, None)
    kinds = [p.action["type"] for p in props]
    assert "trade_deal" in kinds and "close_trade" not in kinds, kinds
    deal = next(p for p in props if p.action["type"] == "trade_deal")
    keys = [w["key"] for w in deal.action["wants"]]
    assert set(PLANNER_CONFIG["h5_trade_fallback_wants"]) <= set(keys), keys


@test("deal: none of what the fort needs on sale: it buys what any fort can use (extra) instead of no deal")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, mf, ff, clicks = lua.execute(TT.SCREEN, TRADE_SRC)
    t = lua.table_from
    wants = t([t({"key": "SOAP", "count": 5})])                     # the merchants have no soap
    r = env.deal(wants, 1.2, False, None)
    assert r.ok is False and "nothing the fort wants" in r.error, dict(r)      # before: the deal ended here
    r = env.deal(wants, 1.2, False, None, t([t({"key": "CLOTH", "count": 1})]))
    assert r.ok and r.fallback and r.buy_value == 8 and mf[4].selected, dict(r)
    act = bridge_part_src("ai-bridge-actions")
    assert code_has(act, "T.deal(wants, margin, a.dry_run == true, txt, #extra > 0 and extra or nil)")


# --- step 2: who goes to the depot ---------------------------------------------------------

CALL = r"""local env = ...
local saved = {}
env.dfhack.persistent = {getSiteData = function(k, d) return saved[k] or d end,
                         saveSiteData = function(k, v) saved[k] = v end}
env.REMOVED, env.JOB_REMOVED = {}, {}
env.WORKER = nil
env.dfhack.job = {getWorker = function() return env.WORKER end,
                  removeWorker = function(j, cd) table.insert(env.REMOVED, env.WORKER.id); env.WORKER = nil; return true end,
                  removeJob = function(j) table.insert(env.JOB_REMOVED, j); return true end}
env.dfhack.units = {getPosition = function(u) return u.x, u.y, u.z end,
                    getReadableName = function(u) return u.name end,
                    isChild = function(u) return u.child == true end, isBaby = function() return false end,
                    getNoblePositions = function(u)
                      if u.broker then return {{position = {code = 'BROKER'}}} end
                      return {}
                    end}
env.df.job_type = {TradeAtDepot = 99}
local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
dep.trade_flags = {trader_requested = false, anyone_can_trade = false}
dep.x1, dep.x2, dep.y1, dep.y2 = 4, 6, 4, 6
dep.jobs = {{job_type = 99}}
env.DEP = dep
env.df.global.plotinfo.caravans = {{entity = 1, trade_state = 2, time_remaining = 100, flags = {tribute = false}}}
env.df.historical_entity = {find = function() return nil end}
env.df.caravan_state.T_trade_state[2] = 'AtDepot'"""


@test("step 2 (B: 'the only one coming a Dwarven Child'): a child who took the trade job is let go")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(TT.FAKE, TRADE_SRC)
    lua.execute(CALL, env)
    lua.execute("local env = ...; env.WORKER = {id = 7, x = 40, y = 40, z = 1, child = true, name = 'a Dwarven Child'}", env)
    r = env.call_trader(1000, 1200, False, None)
    assert r.let_go and "child" in r.let_go and lst(env.REMOVED) == [7], dict(r)
    assert r.coming is None


@test("step 2 (C y250): 'anyone' waits while the broker himself is on the way; a trader stuck on the way is let go")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(TT.FAKE, TRADE_SRC)
    lua.execute(CALL, env)
    lua.execute("local env = ...; env.WORKER = {id = 3, x = 40, y = 40, z = 1, broker = true, name = 'Sibrek, broker'}", env)
    env.call_trader(1000, 1200, False, None)
    r = env.call_trader(2400, 1200, False, None)          # a day and more: before, anyone let in at 1,344 ticks
    assert not r.anyone and r.broker_coming and not env.DEP.trade_flags.anyone_can_trade, dict(r)
    r = env.call_trader(1000 + 3 * 1200, 1200, False, None)
    assert r.anyone and env.DEP.trade_flags.anyone_can_trade, dict(r)
    # C y253: a carpenter "coming" from 5,323 to 31,750 ticks: let go after 4 days on the way
    lua.execute("local env = ...; env.WORKER = {id = 9, x = 40, y = 40, z = 1, name = 'Litast, Carpenter'}", env)
    r = env.call_trader(5000, 1200, False, None)
    assert not r.let_go, dict(r)
    r = env.call_trader(5000 + 4 * 1200, 1200, False, None)
    assert r.let_go and lst(env.REMOVED) == [9], dict(r)


@test("step 6 (E: a dwarf stood at the depot on the trade job, no caravan): the call and its job end with the caravans")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(TT.FAKE, TRADE_SRC)
    lua.execute(CALL, env)
    lua.execute("""local env = ...
        env.DEP.trade_flags.trader_requested = true
        env.df.global.plotinfo.caravans = {}""", env)
    r = env.call_trader(9000, 1200, False, None)
    assert r.unrequested and r.job_removed and not env.DEP.trade_flags.trader_requested, dict(r)
    assert len(lst(env.JOB_REMOVED)) == 1
    # the planner asks for it: no caravan, the call or its job still standing (E's last state)
    s = state([], goods_at_depot=0, requested=True, job=True, coming=True, at_depot=True)
    props, notes = [], []
    _trade_rules(s, PLANNER_CONFIG, 10, props, notes, {"trade": 0}, None)
    assert any(p.action["type"] == "call_trader" for p in props), [p.action for p in props]
    s = state([], goods_at_depot=0)
    props, notes = [], []
    _trade_rules(s, PLANNER_CONFIG, 10, props, notes, {"trade": 0}, None)
    assert not any(p.action["type"] == "call_trader" for p in props)          # nothing standing: no call


# --- the caravan that never left (B, y251) ---------------------------------------------------

OVERSTAY = r"""local env = ...
env.df.building_item_role_type = {TEMP = 0}
env.df.global.world.items.other.SMALLGEM = {}
env.df.global.world.items.other.ROUGH = {}
env.df.global.cur_year, env.df.global.cur_year_tick = 251, 248000
env.df.caravan_state.T_trade_state[3] = 'Leaving'
env.df.global.plotinfo.caravans = {{entity = 77, trade_state = 3, time_remaining = 0, import_value = 9,
                                    flags = {tribute = false}}}
env.df.historical_entity = {find = function() return {name = 'x'} end}
env.dfhack.translation = {translateName = function() return 'Tumamshorast' end}
local function unit(id, race) return {id = id, race = race, civ_id = 77, x = 96, y = 166, z = 169,
                                      flags1 = {merchant = true, inactive = false}} end
env.df.global.world.units = {active = {unit(1, 5), unit(2, 5), unit(3, 9), {id = 4, race = 5, civ_id = 1,
                             flags1 = {merchant = false}}}}
env.df.creature_raw = {find = function(r) return {creature_id = r == 9 and 'WAGON' or 'DWARF'} end}
env.dfhack.units = {isDead = function() return false end, getPosition = function(u) return u.x, u.y, u.z end}
local saved = {}
env.dfhack.persistent = {getSiteData = function(k, d) return saved[k] or d end,
                         saveSiteData = function(k, v) saved[k] = v end}
env.dfhack.maps.canWalkBetween = function() return false end
local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
dep.x1, dep.x2, dep.y1, dep.y2, dep.accessible = 1, 3, 1, 3, false
dep.contained_items = {}
for i = 1, 5 do table.insert(dep.contained_items, {use_mode = 0, item = {id = i, flags = {trader = true}}}) end"""


@test("overstay (B y251): a caravan past its leaving with merchants on the map is reported with what holds it")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, marked = lua.execute(TT.FAKE, TRADE_SRC)
    lua.execute(OVERSTAY, env)
    s = env.survey(None)
    assert s.overstay is not None, "no overstay"
    o = s.overstay[1]
    assert o.merchants == 2 and o.wagons == 1 and o.goods_in_depot == 5 and o.days == 0, dict(o)
    holds = " / ".join(lst(o.holds))
    assert "5 of their goods" in holds and "wagon" in holds and "can't walk to the depot" in holds, holds
    lua.execute("local env = ...; env.df.global.cur_year_tick = 248000 + 8 * 1200", env)
    s = env.survey(None)
    o = s.overstay[1]
    assert o.days == 8, o.days
    st = state([], goods_at_depot=0)
    st["trade"]["overstay"] = [dict(o.items()) | {"holds": lst(o.holds)}]
    props, notes = [], []
    _trade_rules(st, PLANNER_CONFIG, 10, props, notes, {"trade": 0}, None)
    said = [n for n in notes if "past its leaving" in str(n)]
    assert said and "Tumamshorast" in said[0] and "8 days" in said[0], notes
    st["trade"]["overstay"][0]["days"] = 3                 # not yet a week: not said
    notes = []
    _trade_rules(st, PLANNER_CONFIG, 10, [], notes, {"trade": 0}, None)
    assert not any("past its leaving" in str(n) for n in notes)
    # gone: forgotten
    lua.execute("local env = ...; env.df.global.plotinfo.caravans = {}", env)
    s = env.survey(None)
    assert s.overstay is None


finish()
