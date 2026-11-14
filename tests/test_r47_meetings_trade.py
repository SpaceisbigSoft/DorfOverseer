"""(0.105.47, R2) Meetings and trade in an unattended run.

The 8-13 Nov run (six forts, new saves of 11 Nov) made no trade deal and
answered no meeting. The causes, tested here:
  * trade: the depot's and the trade screen's Trade buttons were kept in the
    save's site data only, so no new fort had them: `can_open` false, never an
    open_trade. Now the save's, else this PC's file (shown in any save), else
    the AI's own guess from its October clicks (lua/ai-screen-buttons.lua); a
    guess is checked, kept for every save when it works, retired when it
    misses twice (at once when goods moved without the merchants answering);
  * meetings: DF queues a meeting behind its diplomacy light and opens the
    screen only on a click; the AI only noted it. Now the overseer clicks the
    light (lua/ai-meeting-open.lua, found by its picture) only unattended
    (brain/planner_meetings.py meeting_open_due);
  * a liaison's meeting brings several topics, and "exactly one topic or
    nothing is pressed" left every one of them: now yes when every open topic
    is one the AI always agrees to; and with no button shown the answer is
    found by its word or DF's confirm key (never a click for No);
  * the wiring: the action, its dry run, the pulse, the label, the batch
    exclusions, the config, the note.

    python tests/test_r47_meetings_trade.py
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, code_has  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import planner_meetings as PM  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
import test_trade as TT  # noqa: E402  (its fakes; its tests don't run again)

LUA_DIR = ROOT / "lua"
BUTTONS_SRC = module_src("ai-screen-buttons.lua")
OPEN_SRC = module_src("ai-meeting-open.lua")
TRADE_SRC = module_src("ai-trade.lua")


def lst(t):
    return [] if t is None else [t[i] for i in range(1, len(t) + 1)]


# --- the button store (lua/ai-screen-buttons.lua) -------------------------------------

STORE = r"""
local src = ...
local G = {persist = {}, files = {}}
local env = setmetatable({}, {__index = _G})
env.dfhack = {getDFPath = function() return '/df' end,
              filesystem = {mkdir_recursive = function() end},
              persistent = {getSiteData = function(k, d) local v = G.persist[k]; if v == nil then return d end; return v end,
                            saveSiteData = function(k, v) G.persist[k] = v end}}
env.require = function(name)
  if name == 'json' then
    return {decode_file = function(p) if G.files[p] then return G.files[p] end error('none') end,
            encode_file = function(d, p) G.files[p] = d end}
  end
  error('require ' .. name)
end
assert(load(src, 'ai-screen-buttons', 't', env))()
return env, G
"""


def store():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, G = lua.execute(STORE, BUTTONS_SRC)
    return lua, env, G


@test("store: a new save has the AI's guesses for the depot's and the trade screen's Trade buttons (none for meetings)")
def _():
    lua, env, G = store()
    b = env.get("ai-overseer/trade-buttons")
    assert b.Depot.default is True and b.Depot["from"] == "guess" and b.Depot.anchor == "right-top", dict(b.Depot)
    assert (b.Depot.rx, b.Depot.ty) == (76, 15) and (b.Trade.dx, b.Trade.dy) == (-2, 2)
    # the October clicks it comes from: x94 on a 170-wide grid; x73 and x60 on 149 and 136
    assert env.at(b.Depot, 170, 64) == (94, 15) and env.at(b.Depot, 149, 66)[0] == 73 and env.at(b.Depot, 136, 62)[0] == 60
    assert env.at(b.Trade, 149, 66) == (72, 64) and env.at(b.Trade, 136, 62) == (66, 60)
    assert len(list(env.get("ai-overseer/meeting-buttons").items())) == 0


@test("store: the save's place over the PC's over the guess; a place shown in one save serves every save on the PC")
def _():
    lua, env, G = store()
    key = "ai-overseer/trade-buttons"
    env.share(key, "Depot", lua.table_from({"anchor": "right-top", "rx": 70, "ty": 14}))
    b = env.get(key)
    assert b.Depot["from"] == "pc" and b.Depot.rx == 70 and b.Depot.default is None, dict(b.Depot)
    assert b.Trade["from"] == "guess"                    # the other one still the guess
    G.persist[key] = lua.table_from({"Depot": lua.table_from({"anchor": "right-top", "rx": 66, "ty": 13})})
    assert env.get(key).Depot["from"] == "save" and env.get(key).Depot.rx == 66
    G.persist[key] = None                                  # another save: the PC's
    assert env.get(key).Depot.rx == 70


@test("store: a guess that misses twice is retired (at once when it did harm); a guess that worked is kept as known")
def _():
    lua, env, G = store()
    key = "ai-overseer/trade-buttons"
    assert env.miss(key, "Depot", "no screen") is False
    assert env.get(key).Depot is not None
    assert env.miss(key, "Depot", "no screen") is True
    assert env.get(key).Depot is None                      # the old Needs you comes back
    assert env.miss(key, "Trade", "goods moved one way", True) is True
    assert env.get(key).Trade is None
    lua2, env2, G2 = store()
    env2.miss(key, "Depot", "once")
    env2.share(key, "Depot", env2.get(key).Depot)        # it worked: known now, the miss forgotten
    f = env2.read_file()
    assert f.buttons[key].Depot.rx == 76 and f.buttons[key].Depot.default is None and f.misses[key].Depot is None
    assert env2.get(key).Depot["from"] == "pc"
    assert env.on_screen(94, 15, 170, 64) and not env.on_screen(94, 64, 170, 64) and not env.on_screen(-1, 3, 170, 64)


# --- trade with the guess (lua/ai-trade.lua) --------------------------------------------

def trade_env():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, mf, ff, clicks = lua.execute(TT.SCREEN, TRADE_SRC)
    B = lua.execute(r"""
local env, src = ...
env.dfhack.getDFPath = function() return '/df' end
env.dfhack.filesystem = {mkdir_recursive = function() end}
env.FILES = {}
local gui_require = env.require
env.require = function(name)
  if name == 'json' then
    return {decode_file = function(p) if env.FILES[p] then return env.FILES[p] end error('none') end,
            encode_file = function(d, p) env.FILES[p] = d end}
  end
  return gui_require(name)
end
local e2 = setmetatable({}, {__index = env})
assert(load(src, 'ai-screen-buttons', 't', e2))()
env.reqscript = function(n) if n == 'ai-screen-buttons' then return e2 end error('reqscript ' .. n) end
env.df.talk_line_type[-1] = 'NONE'                 -- as DF's enum: no answer
env.df.global.cur_year, env.df.global.cur_year_tick = 50, 5000
return e2
""", env, BUTTONS_SRC)
    return lua, env, B, mf, ff, clicks


PAINT = r"""
local env, x, y, word = ...
env.TEXT = env.TEXT or {}
env.TEXT[y] = env.TEXT[y] or {}
for i = 1, #word do env.TEXT[y][x + i - 1] = word:byte(i) end
env.dfhack.screen = {readTile = function(tx, ty)
  local row = env.TEXT[ty]
  return {ch = row and row[tx] or 32}
end}
"""


def paint(lua, env, x, y, word):
    """Draw a word on the fake screen (every other tile a blank, readable)."""
    lua.execute(PAINT, env, x, y, word)


@test("trade (the 8-13 Nov cause): a new save with no button shown still presses Trade, by the guess; known after")
def _():
    lua, env, B, mf, ff, clicks = trade_env()
    paint(lua, env, 56, 58, "Trade")                   # the screen reads Trade at the guess (58, 58)
    lua.execute("local env = ...; env.OPEN_CLICKED_AT = os.time(); env.OPENED_FOR = nil", env)
    assert env.buttons().Trade.default is True
    r = env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    assert r.ok and r.calibrated, dict(r)                 # before 0.105.47: calibrated false, never pressed
    p = env.press("Trade", None)
    assert p.ok and p.pressed == "Trade" and p.guessed is True and p.answer == "Trade", dict(p)
    assert lst(clicks[1])[:2] == [58, 58], lst(clicks[1])          # 120 // 2 - 2, 60 - 2
    f = B.read_file()
    assert f.buttons["ai-overseer/trade-buttons"].Trade.dx == -2          # it worked: kept for every save
    assert env.buttons().Trade["from"] == "pc"


@test("trade: a guessed Trade press the merchants don't answer is a miss; goods moving with no answer retire it at once")
def _():
    lua, env, B, mf, ff, clicks = trade_env()
    lua.execute(r"""local env = ...
        env.require = function(name)
          if name == 'json' then
            return {decode_file = function(p) if env.FILES[p] then return env.FILES[p] end error('none') end,
                    encode_file = function(d, p) env.FILES[p] = d end}
          end
          return {simulateInput = function() end}      -- nothing happens on the click
        end""", env)
    paint(lua, env, 56, 58, "Trade")
    env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    p = env.press("Trade", None)
    assert p.ok and p.guessed and not p.traded, dict(p)
    f = B.read_file()
    assert f.misses["ai-overseer/trade-buttons"].Trade == 1 and not f.retired["ai-overseer/trade-buttons"]
    lua.execute(r"""local env = ...
        local t = env.df.global.game.main_interface.trade
        env.require = function(name)
          if name == 'json' then
            return {decode_file = function(p) if env.FILES[p] then return env.FILES[p] end error('none') end,
                    encode_file = function(d, p) env.FILES[p] = d end}
          end
          return {simulateInput = function()                     -- a seize: their goods go, nobody speaks
            local v = {[0] = t.good[0][6]}
            t.good[0] = setmetatable(v, {__len = function() return 1 end})
            t.goodflag[0] = setmetatable({[0] = {selected = false}}, {__len = function() return 1 end})
          end}
        end""", env)
    env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    p = env.press("Trade", None)
    f = B.read_file()
    assert f.retired["ai-overseer/trade-buttons"].Trade, dict(p)
    assert env.buttons().Trade is None                    # not pressed again: the Needs you comes back


@test("review: the word check: Trade at the tile -> ok; Seize or Offer there -> forbidden; blank or unread -> unreadable")
def _():
    lua, env, G = store()
    T = lambda rows, col: lua.table_from({"rows": lua.table_from(rows), "col": col})   # noqa: E731
    assert env.judge(T(["   [ Trade ]   "], 7), "Trade") == "ok"
    assert env.judge(T(["  Seize   Trade  "], 4), "Trade") == ("forbidden", "Seize")
    assert env.judge(T(["Trade  Offer    "], 9), "Trade") == ("forbidden", "Offer")
    assert env.judge(T(["Seize        Trade   "], 16), "Trade") == "ok"          # Seize far off the tile
    assert env.judge(T(["   nothing here   "], 5), "Trade") == "missing"
    assert env.judge(T(["          "], 5), "Trade") == "unreadable"
    assert env.judge(None, "Trade") == "unreadable"


@test("review: a guessed Trade press where the screen reads Seize: refused, nothing pressed, the guess retired, the screen closed")
def _():
    lua, env, B, mf, ff, clicks = trade_env()
    paint(lua, env, 55, 58, "Seize")
    env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    p = env.press("Trade", None)
    assert p.ok is False and p.rejected and p.guess_refused == "forbidden" and "Seize" in p.error, dict(p)
    assert all(lst(clicks[i])[2] != "_MOUSE_L" for i in range(1, len(clicks) + 1)), [lst(clicks[i]) for i in range(1, len(clicks) + 1)]
    assert B.read_file().retired["ai-overseer/trade-buttons"].Trade
    assert env.buttons().Trade is None
    tr = env.df["global"].game.main_interface.trade
    assert not tr.open and not any(tr.goodflag[0][i].selected for i in range(len(tr.goodflag[0])))


@test("review: a guessed Trade press where the text can't be read: no press, the guess retired, the Needs you back")
def _():
    lua, env, B, mf, ff, clicks = trade_env()          # this fake's readTile answers nothing (TrueType)
    env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    p = env.press("Trade", None)
    assert p.ok is False and p.guess_refused == "unreadable" and "can't be read" in p.error, dict(p)
    assert all(lst(clicks[i])[2] != "_MOUSE_L" for i in range(1, len(clicks) + 1))
    assert env.buttons().Trade is None and B.read_file().retired["ai-overseer/trade-buttons"].Trade
    # a button the player showed is pressed as before, text or no text
    lua.execute("""local env = ...
        env.dfhack.persistent.saveSiteData('ai-overseer/trade-buttons',
            {Trade = {anchor = 'centre-bottom', dx = 0, dy = 5}})
        local t = env.df.global.game.main_interface.trade
        t.open = true
        t.mer = {entity = 99, import_value = 5}           -- the next caravan""", env)
    env.deal(lua.table_from([lua.table_from({"key": "BAR:STEEL", "count": 2})]), 1.2, False, None)
    p = env.press("Trade", None)
    assert p.pressed == "Trade" and p.guessed is None, dict(p)


@test("trade: the survey can open the screen by the guess (can_open, where from); a guess off the screen isn't used")
def _():
    lua, env, B, *_ = trade_env()
    lua.execute(r"""local env = ...
        local dep = {id = 3, x1 = 4, x2 = 6, y1 = 4, y2 = 6, z = 1, centerx = 5, centery = 5, jobs = {},
                     trade_flags = {trader_requested = true, anyone_can_trade = false}, contained_items = {},
                     getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
        env.df.global.world.buildings.other.TRADE_DEPOT = {dep}
        env.df.job_type = {TradeAtDepot = 99}
        env.dfhack.job = {getWorker = function() return nil end}
        env.dfhack.persistent.getSiteData = function(k, d) return d end
        env.df.global.world.items.other.SMALLGEM = {}
        env.df.global.world.items.other.ROUGH = {}""", env)
    s = env.survey(None)
    assert s.trader.can_open is True and s.trader.button == "guess", dict(s.trader)
    lua.execute("local env = ...; env.df.global.gps.dimx = 60", env)      # 60 - 76 < 0: off the screen
    lua.execute(r"""local env = ...
        local t = env.df.global.game.main_interface.trade
        t.open = false
        local mer = {entity = 7, import_value = 1000, trade_state = 2}
        env.df.global.plotinfo.caravans = {mer}
        env.df.caravan_state.T_trade_state.AtDepot = 2
        local dep = env.df.global.world.buildings.other.TRADE_DEPOT[1]
        dep.jobs = {{job_type = 99}}
        env.dfhack.job = {getWorker = function() return {x = 5, y = 5, z = 1} end}
        env.dfhack.units = {getPosition = function(u) return u.x, u.y, u.z end}
        env.dfhack.gui.matchFocusString = function(f) return f == 'dwarfmode/Default' end
        env.LOAD_WATCH = {n = 0, dep = 3, since = -100000}""", env)
    r = env.open_screen(False, None)
    assert r.ok is False and "here-depot" in r.error, dict(r)


DEPOT_SETUP = r"""local env = ...
        local t = env.df.global.game.main_interface.trade
        t.open = false
        local mer = {entity = 7, import_value = 1000, trade_state = 2}
        env.df.global.plotinfo.caravans = {mer}
        env.df.caravan_state.T_trade_state.AtDepot = 2
        local dep = {id = 3, x1 = 4, x2 = 6, y1 = 4, y2 = 6, z = 1, centerx = 5, centery = 5, jobs = {{job_type = 99}},
                     trade_flags = {}, contained_items = {},
                     getBuildStage = function() return 1 end, getMaxBuildStage = function() return 1 end}
        env.df.global.world.buildings.other.TRADE_DEPOT = {dep}
        env.df.job_type = {TradeAtDepot = 99}
        env.df.view_sheet_type = {BUILDING = 2, NONE = -1}
        env.df.global.game.main_interface.view_sheets = {open = false}
        env.df.global.game.main_interface.assign_trade = {open = false}
        env.dfhack.job = {getWorker = function() return {x = 5, y = 5, z = 1} end}
        env.dfhack.units = {getPosition = function(u) return u.x, u.y, u.z end}
        env.dfhack.gui.matchFocusString = function(f) return f == 'dwarfmode/Default' end
        env.TIMERS = {}
        env.dfhack.timeout = function(n, unit, fn) table.insert(env.TIMERS, fn) end
        env.LOAD_WATCH = {n = 0, dep = 3, since = -100000}
        env.dfhack.persistent.getSiteData = function(k, d) return d end
        local json_req = env.require
        env.require = function(name)
          if name == 'json' then return json_req('json') end
          return {simulateInput = function(_, key)                 -- the click opens the goods screen
            if key == '_MOUSE_L' then env.df.global.game.main_interface.assign_trade.open = true end
            if key == 'LEAVESCREEN' then env.df.global.game.main_interface.assign_trade.open = false end
          end}
        end"""


@test("trade: a guessed depot click that opens no trade screen is judged later, the sheet closed, the miss counted")
def _():
    lua, env, B, *_ = trade_env()
    lua.execute(DEPOT_SETUP, env)
    paint(lua, env, 42, 15, "Trade")                  # the sheet reads Trade at the guess
    r = env.open_screen(False, None)
    assert r.ok and r.clicking and r.guessed and lst(r.at) == [44, 15], dict(r)     # 120 - 76
    lua.execute("local env = ...; env.TIMERS[1]()", env)           # the click, 3 frames on
    lua.execute("local env = ...; env.TIMERS[2]()", env)           # judged 30 frames on
    mi = env.df["global"].game.main_interface
    assert mi.assign_trade.open is False and mi.view_sheets.open is False
    assert B.read_file().misses["ai-overseer/trade-buttons"].Depot == 1
    # (review) the sheet reads Offer at the guess, or nothing readable: never clicked, the guess retired
    for word, verdict in (("Offer", "forbidden"), (None, "unreadable")):
        lua2, env2, B2, *_ = trade_env()
        lua2.execute(DEPOT_SETUP, env2)
        if word:
            paint(lua2, env2, 43, 15, word)
        r = env2.open_screen(False, None)
        assert r.ok and r.clicking, dict(r)            # the sheet opened; the click waits for the layout
        lua2.execute("local env = ...; env.TIMERS[1]()", env2)
        assert env2.LAST_OPEN.clicked is False and env2.LAST_OPEN.guess_refused == verdict, dict(env2.LAST_OPEN)
        assert env2.df["global"].game.main_interface.assign_trade.open is False       # nothing clicked
        assert env2.df["global"].game.main_interface.view_sheets.open is False
        assert B2.read_file().retired["ai-overseer/trade-buttons"].Depot and env2.buttons().Depot is None


# --- the meeting light (lua/ai-meeting-open.lua) ------------------------------------------

LIGHT = r"""
local src = ...
local function vec(n) return setmetatable({}, {__len = function() return n end}) end
local G = {clicks = {}, focus = 'dwarfmode/Default', tiles = {}}
local env = setmetatable({}, {__index = _G})
local pics = {}
for i = 0, 2 do pics[i] = {}; for j = 0, 2 do pics[i][j] = 9000 + i * 3 + j end end
env.df = {global = {
  plotinfo = {dipscript_popups = vec(1)},
  gps = {dimx = 40, dimy = 20, mouse_x = 1, mouse_y = 1, tile_pixel_x = 8, tile_pixel_y = 12,
         graphical_interface = {texpos_diplomacy_light = pics}, classic_interface = {texpos_diplomacy_light = {}}},
  game = {main_interface = {diplomacy = {open = false}, trade = {open = false}}}}}
env.dfhack = {getDFPath = function() return '/df' end,
  screen = {readTile = function(x, y) local t = G.tiles[x .. ',' .. y]; return {ch = 32, tile = t or 0} end},
  gui = {matchFocusString = function(f) return f == G.focus end, getDFViewscreen = function() return {} end,
         getCurFocus = function() return {G.focus} end},
  timeout = function() end,
  persistent = {getSiteData = function(k, d) return d end, saveSiteData = function() end}}
env.require = function(name)
  return {simulateInput = function(_, key)
    if key == '_MOUSE_L' then
      table.insert(G.clicks, {env.df.global.gps.mouse_x, env.df.global.gps.mouse_y})
      if G.light_at and env.df.global.gps.mouse_x == G.light_at[1] and env.df.global.gps.mouse_y == G.light_at[2] then
        env.df.global.game.main_interface.diplomacy.open = true
      end
    end
  end}
end
env.reqscript = function(n) error('reqscript ' .. n) end
assert(load(src, 'ai-meeting-open', 't', env))()
-- the light drawn at x 2-4, y 5-7
for i = 0, 2 do for j = 0, 2 do G.tiles[(2 + j) .. ',' .. (5 + i)] = 9000 + i * 3 + j end end
G.light_at = {3, 6}
return env, G
"""


def light():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, G = lua.execute(LIGHT, OPEN_SRC)
    return lua, env, G


@test("meeting light (the 8-13 Nov cause): found on the screen by its picture and clicked: the meeting screen opens")
def _():
    lua, env, G = light()
    pos, cells, pics = env.find_light()
    assert pos and (pos.x, pos.y) == (3, 6) and cells == 9 and pics == 9, (dict(pos) if pos else None, cells, pics)
    d = env.open(True)
    assert d.ok and d.dry_run and lst(d.at) == [3, 6] and len(G.clicks) == 0, dict(d)    # a dry run clicks nothing
    r = env.open(False)
    assert r.ok and r.clicking and r.via == "picture" and r.opened is True, dict(r)
    assert getattr(env.df, "global").game.main_interface.diplomacy.open is True
    again = env.open(False)
    assert again.open and len(G.clicks) == 1                       # already open: no second click


@test("meeting light: never with a menu of the player's open, the trade screen up, or no meeting waiting")
def _():
    lua, env, G = light()
    G.focus = "dwarfmode/Stockpile"
    r = env.open(False)
    assert r.waiting and "menu" in r.error and len(G.clicks) == 0, dict(r)
    G.focus = "dwarfmode/Default"
    getattr(env.df, "global").game.main_interface.trade.open = True
    assert env.open(False).waiting and len(G.clicks) == 0
    getattr(env.df, "global").game.main_interface.trade.open = False
    lua.execute("local env = ...; env.df.global.plotinfo.dipscript_popups = setmetatable({}, {__len = function() return 0 end})", env)
    assert "no meeting" in env.open(False).error and len(G.clicks) == 0


@test("meeting light: not on the screen and never shown: refused, saying how to show it; the centre of the cells")
def _():
    lua, env, G = light()
    lua.execute("local env, G = ...; G.tiles = {}", env, G)
    r = env.open(False)
    assert r.ok is False and r.rejected and "--here Light" in r.error and len(G.clicks) == 0, dict(r)
    assert env.centre(lua.table_from([lua.table_from([2, 5]), lua.table_from([4, 7])])) == (3, 6)
    assert env.centre(lua.table_from([])) is None


# --- the meeting answers (lua/ai-diplomacy.lua) -------------------------------------------

@test("answers: several open topics the AI always says yes to are answered yes; with peace or tribute among them, not")
def _():
    import test_world as TW
    env, _ = TW.world()
    T = lambda *a: TW.LUA.table_from(list(a))   # noqa: E731
    assert env.press_guard(T("OpenTrade", "ExportAgreement", "ImportAgreement"), "small") is None
    assert env.press_guard(T("PleasantPlace", "TreeQuota"), "small") is None
    assert "2 topics" in env.press_guard(T("OpenTrade", "RequestPeace"), "small")     # peace is weighed
    assert "tribute" in env.press_guard(T("OpenTrade", "TributeAgreement"), "small")
    assert "DeclareWar" in env.press_guard(T("OpenTrade", "DeclareWar"), "pay")
    assert "left to you" in env.press_guard(T("OpenTrade", "BecomeLandHolder"), "small")


@test("answers: No is never pressed by a key (leaving is the AI's no); Yes by its word when the text can be read")
def _():
    import test_world as TW
    env, G = TW.world(TW.MEETING)
    assert env.press_named("No", None) is None and len(lst(G.inputs)) == 0
    TW.LUA.execute(r"""local env = ...
        env.reqscript = function(n)
          if n == 'ai-meeting-open' then return {find_word = function(w)
            if w == 'Yes' then return {{30, 33}} end return {} end} end
          error('reqscript ' .. n)
        end""", env)
    how, place = env.press_named("Yes", None)
    assert how == "word" and place.x == 31 and place.y == 33 and lst(G.clicks[1]) == [31, 33], (how, lst(G.clicks[1]))


@test("answers: every topic concluded: the text stepped on with the confirm key, never a click")
def _():
    import test_world as TW
    done = TW.MEETING + "df.global.game.main_interface.diplomacy.dipev.agreement_topic = G.vec({7, 2})"
    env, G = TW.world(done)
    g = getattr(env.df, "global")
    G.on_click = None
    TW.LUA.execute(r"""local env, G = ...
        local sim = env.require('gui').simulateInput
        local req = env.require
        env.require = function(n)
          if n == 'gui' then return {simulateInput = function(s, key)
            sim(s, key)
            if key == 'SELECT' then env.df.global.game.main_interface.diplomacy.environment.dipev.cur_step = 4 end
          end} end
          return req(n)
        end""", env, G)
    r = env.answer_meeting(TW.LUA.table_from({}))
    assert r.ok and r.answer == "continue" and r.via == "key" and len(G.clicks) == 0, dict(r)
    d = env.answer_meeting(TW.LUA.table_from({"dry_run": True}))
    assert d.ok and d.answer == "continue" and d.pressed is None


# --- the overseer's rule (brain/planner_meetings.py) ----------------------------------------

@test("rule: the light clicked only unattended, in autopilot, not halted or pinned or stopped, nothing else open, once a minute")
def _():
    st = {"in_fort": True, "meeting_waiting": 1}
    assert PM.meeting_open_due(st, True, True, False, None, False, 61)
    assert not PM.meeting_open_due(st, True, False, False, None, False, 61)        # the player at the game
    assert not PM.meeting_open_due(st, False, True, False, None, False, 61)        # not autopilot
    assert not PM.meeting_open_due(st, True, True, True, None, False, 61)          # halted
    assert not PM.meeting_open_due(st, True, True, False, "held", False, 61)       # the keeper's pin
    assert not PM.meeting_open_due(st, True, True, False, None, True, 61)          # the stop file
    assert not PM.meeting_open_due(st, True, True, False, None, False, 10)         # tried 10 s ago
    for k in ("meeting", "trade_open", "saving"):
        assert not PM.meeting_open_due(dict(st, **{k: True}), True, True, False, None, False, 61), k
    assert not PM.meeting_open_due({"in_fort": True}, True, True, False, None, False, 61)
    assert not PM.meeting_open_due({"meeting_waiting": 1}, True, True, False, None, False, 61)
    assert PM.MEETING_OPEN_EVERY_S == PLANNER_CONFIG["meeting_open_every_s"] == 60
    assert "clicked the light" in PM.meeting_open_said({"clicking": True, "via": "picture", "popups": 2})
    assert "couldn't open" in PM.meeting_open_said({"rejected": True, "error": "x"})
    assert PM.meeting_open_said({"waiting": True}) is None
    # a meeting it couldn't answer and left: the light waits half an hour (no 1-minute open/leave loop)
    assert PM.meeting_reopen_wait() == PLANNER_CONFIG["meeting_reopen_after_s"] == 1800
    assert not PM.meeting_open_due(st, True, True, False, None, False, 0 - PM.meeting_reopen_wait() + 120)
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert "open_meeting_tried = nowt + meeting_reopen_wait()" in src


@test("note: a waiting meeting says the AI opens it unattended (it said 'the game runs on meanwhile' and nobody did)")
def _():
    import json
    s = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    s["meetings"] = {"activities": [{"actor": "Reg, outpost liaison", "noble": "Inod, expedition leader", "flags": []}],
                     "popups": 1, "screen": "dwarfmode/Default"}
    notes = plan(s, Memory())[1]
    n = [x for x in notes if x.startswith("a meeting waits to be shown in DF (Reg")]
    assert n and "the AI opens it" in n[0] and not any(x.startswith("[you]") and "meeting" in x for x in notes), notes


# --- the wiring --------------------------------------------------------------------------

@test("wiring: open_meeting in ACTIONS and DRY_OK, never batched (Lua and Python), the pulse's meeting_waiting, the modules")
def _():
    hub = (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8")
    assert code_has(hub, "open_meeting = function(a)") and code_has(hub, "reqscript('ai-meeting-open').open(a.dry_run == true)")
    assert code_has(hub, "'open_meeting',    -- (0.105.47)")
    assert code_has(hub, "BATCH_NEVER.open_meeting = true")
    assert code_has(hub, "meeting_waiting = (function()")
    assert code_has(hub, "'ai-screen-buttons', 'ai-meeting-open',")
    import bridge
    assert "open_meeting" in bridge.BATCH_NEVER
    import overseer
    assert "open_meeting" in overseer.ACTION_LABELS if hasattr(overseer, "ACTION_LABELS") else True
    src = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
    assert '"open_meeting": "open the meeting waiting behind DF\'s diplomacy light"' in src
    assert "meeting_open_due(st, args.autopilot, meeting_unattended(args)" in src
    assert 'bridge.act({"type": "open_meeting"})' in src
    tr = (LUA_DIR / "ai-trade.lua").read_text(encoding="utf-8")
    assert code_has(tr, "reqscript('ai-screen-buttons').get(BUTTONS_KEY)")
    dip = (LUA_DIR / "ai-diplomacy.lua").read_text(encoding="utf-8")
    assert code_has(dip, "reqscript('ai-screen-buttons').get(BUTTONS_KEY)")


@test("Lua: the new modules compile (Lua 5.3)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    for name in ("ai-screen-buttons.lua", "ai-meeting-open.lua", "ai-trade.lua", "ai-diplomacy.lua", "ai-bridge.lua"):
        src = (LUA_DIR / name).read_text(encoding="utf-8")
        ok = lua.execute("local s, n = ...; local f, e = load(s, n, 't', {}); return f ~= nil, e", src, name)
        assert ok[0], (name, ok[1])


if __name__ == "__main__":
    finish()
