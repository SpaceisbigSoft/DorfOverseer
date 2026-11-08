"""(0.105.24, 13b) Tests for lua/ai-mission-send.lua: the messenger sent on
"Make contact" by driving DF's World screen, on a fake screen that behaves
as the recorded steps say (world/NORMAL -> a click on the site ->
world/NEW_MISSION -> Diplomacy -> world/MISSION_DETAILS with a new army
controller), and the ways it can differ. Frames are pumped by hand.

    python tests/test_mission_send.py
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

SRC = (ROOT / "lua" / "ai-mission-send.lua").read_text(encoding="utf-8")


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
local src, setup = ...
local function enum(names)
  local e = {}
  for i, n in ipairs(names) do e[i - 1] = n; e[n] = i - 1 end
  return e
end
local MODES = enum({'NORMAL', 'CIVILIZATIONS', 'MISSIONS', 'MISSION_DETAILS', 'NEW_MISSION'})
local GOALS = enum({'SITE_INVASION', 'RECOVER_ARTIFACT', 'RESCUE_HF', 'MAKE_REQUEST', 'DIPLOMACY'})
local NEWM = enum({'OKAY', 'INACCESSIBLE', 'OWN_CIV', 'NOT_IN_CONTACT'})
local G = {persist = {}, files = {}, inputs = {}, clicks = {}, queue = {}, on = true, busy = nil,
           screen = nil, ctl = 0, diplomacy = 0, stuck = false, keep_ac = false,
           world_btn = {3, 38}, dip_btn = {50, 15}, settings_ok = true}
local env = setmetatable({}, {__index = _G})
G.env = env
-- the World screen's DF behaviour, as recorded; a test changes G.react to differ
function G.screen_new()
  local nm = {}
  nm[GOALS.DIPLOMACY] = G.diplomacy
  G.screen = {view_mode = MODES.NORMAL, focus_site = -1, new_mission = nm, selected_ac = -1}
end
function G.react_default(x, y)
  local s = G.screen
  if not s then
    if x == G.world_btn[1] and y == G.world_btn[2] then G.screen_new() end
    return
  end
  if s.view_mode == MODES.NORMAL then
    if s.focus_site >= 0 then s.view_mode = G.site_mode or MODES.NEW_MISSION end
  elseif s.view_mode == MODES.NEW_MISSION then
    if x == G.dip_btn[1] and y == G.dip_btn[2] then
      s.view_mode = MODES.MISSION_DETAILS
      G.ctl = G.ctl + 1
      s.selected_ac = 900 + G.ctl
    end
  end
end
G.react = G.react_default
local controllers = setmetatable({}, {__len = function() return G.ctl end})
env.df = {
  world_view_mode_type = MODES, army_controller_goal_type = GOALS, world_new_mission_type = NEWM,
  viewscreen_worldst = {},
  global = {
    cur_year = 120, cur_year_tick = 5000,
    gps = {mouse_x = 7, mouse_y = 9, dimx = 100, dimy = 40, tile_pixel_x = 8, tile_pixel_y = 12},
    world = {army_controllers = {all = controllers}},
    plotinfo = {group_id = 200},
  },
  world_site = {find = function(id) if id == 42 or id == 43 then return {id = id, name = {text = 'Cottageflings'}} end end},
  historical_entity = {find = function(id)
    if id ~= 200 then return nil end
    return {positions = {own = {{id = 9, code = 'MESSENGER'}},
                         assignments = {{position_id = 9, histfig = G.messenger_hf or 15}}}}
  end},
  historical_figure = {find = function(id) if id == 15 then return {unit_id = 5} end end},
  unit = {find = function(id)
    if id == 5 and not G.messenger_gone then return {id = 5, flags1 = {inactive = false}, flags2 = {killed = false}} end
  end},
}
local function focus()
  if G.screen then return 'world/' .. MODES[G.screen.view_mode] end
  return 'dwarfmode/Default'
end
env.dfhack = {
  getDFPath = function() return '/df' end,
  timeout = function(n, unit, fn) table.insert(G.queue, fn) end,
  persistent = {getSiteData = function(k, d) local v = G.persist[k]; if v == nil then return d end; return v end,
                saveSiteData = function(k, v) G.persist[k] = v end},
  filesystem = {mkdir_recursive = function() end},
  translation = {translateName = function(n) return n.text end},
  gui = {getCurFocus = function() return {focus()} end,
         getDFViewscreen = function() return {} end,
         getViewscreenByType = function() return G.screen end},
}
env.require = function(name)
  if name == 'json' then
    return {decode_file = function(p) if G.files[p] then return G.files[p] end error('none') end,
            encode_file = function(d, p) G.files[p] = d end}
  end
  if name == 'gui' then
    return {simulateInput = function(_, key)
      table.insert(G.inputs, key)
      local gps = env.df.global.gps
      if key == '_MOUSE_L' then
        table.insert(G.clicks, {gps.mouse_x, gps.mouse_y})
        G.react(gps.mouse_x, gps.mouse_y)
      elseif key == 'LEAVESCREEN' and G.screen and not G.stuck then
        G.screen = nil
        if not G.keep_ac and G.ctl > (G.ctl_start or 0) then G.ctl = G.ctl_start or 0 end
      end
    end}
  end
  error('require ' .. name)
end
env.reqscript = function(name)
  if name == 'ai-overseer-settings' then
    return {load_settings = function() return {send_messenger = G.on} end}
  end
  if name == 'ai-camera' then return {player_busy = function() return G.busy end} end
  if name == 'ai-missions' then return {probe_screen = function() return {screen = G.screen ~= nil, focus = focus()} end} end
  error('reqscript ' .. name)
end
-- run the queued frames' callbacks (each may queue more), at most n
function G.pump(n)
  local ran = 0
  while #G.queue > 0 and ran < (n or 1000) do
    local fn = table.remove(G.queue, 1)
    fn()
    ran = ran + 1
  end
  return ran
end
function G.calibrate_all()
  G.persist['ai-overseer/world-buttons'] = {
    World = {anchor = 'left-bottom', lx = G.world_btn[1], by = 40 - G.world_btn[2]},
    Diplomacy = {anchor = 'centre', dx = G.dip_btn[1] - 50, dy = G.dip_btn[2] - 20},
  }
end
G.MODES, G.NEWM = MODES, NEWM
assert(load(setup or '', 'setup', 't', setmetatable({G = G}, {__index = _G})))()
assert(load(src, 'ai-mission-send', 't', env))()
return env, G
"""

LUA = None


def world(setup: str = ""):
    global LUA
    LUA = LuaRuntime(unpack_returned_tuples=True)
    env, G = LUA.execute(FAKE, SRC, setup)
    return env, G


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def start(env, site=42, **kw):
    return env.start(LUA.table_from(dict({"site_id": site, "goal": "make_contact"}, **kw)))


@test("the recorded steps: World opened, the site clicked, Diplomacy chosen; stops at Make contact (never recorded), the screen shut")
def _():
    env, G = world("G.calibrate_all()")
    r = start(env)
    assert r.ok and r.sending and r.site == "Cottageflings", dict(r)
    assert lst(r.steps) == ["open", "site", "goal", "make_contact", "messenger", "confirm"]
    G.pump()
    assert G.screen is None, "the World screen was left open"
    assert env.RUN is None
    st = env.status()
    last = st.last
    assert last.result == "stopped" and last.step == "make_contact" and last.reason == "not_recorded", dict(last)
    assert "probe_missions.py --watch" in last.why and last.closed is True and last.controller_left is None, dict(last)
    clicks = [tuple(lst(c)) for c in lst(G.clicks)]
    assert clicks == [(3, 38), (50, 20), (50, 15)], clicks          # World, the map's middle, Diplomacy
    assert lst(G.inputs)[-1] == "LEAVESCREEN"
    gps = getattr(env.df, "global").gps
    assert (gps.mouse_x, gps.mouse_y) == (7, 9)                       # the mouse put back
    run = G.files["/df/dfhack-config/ai-overseer/mission-send.json"].runs[1]
    oks = [t.step for t in lst(run.trail) if t.what == "ok"]
    assert oks == ["open", "site", "goal"], oks
    assert run.saw.mode == "MISSION_DETAILS" and run.saw.selected_ac == 901 and run.saw.focus_site == 42, dict(run.saw)
    assert run.probe.screen is True and run.probe.focus == "world/MISSION_DETAILS"      # the full dump, before closing
    assert all(t.probe is not None for t in lst(run.trail) if t.what == "ok")
    assert G.persist["ai-overseer/mission-send"].step == "make_contact"
    assert lst(st.buttons) == ["Diplomacy", "World"] and st.on is True


@test("not started: switch off, the player busy, the messenger away, no such site, the World button unknown, one at a time; a dry run presses nothing")
def _():
    env, G = world("G.calibrate_all(); G.on = false")
    r = start(env)
    assert not r.ok and r.rejected and "switch" in r.error, dict(r)
    env, G = world("G.calibrate_all(); G.busy = 'a menu is open'")
    r = start(env)
    assert not r.ok and r.waiting and "a menu is open" in r.error, dict(r)
    env, G = world("G.calibrate_all(); G.messenger_gone = true")
    r = start(env)
    assert not r.ok and r.rejected and "away" in r.error, dict(r)
    env, G = world("G.calibrate_all(); G.messenger_hf = -1")
    r = start(env)
    assert not r.ok and "nobody holds" in r.error, dict(r)
    env, G = world("G.calibrate_all()")
    r = start(env, site=7)
    assert not r.ok and r.rejected and "no site 7" in r.error, dict(r)
    r = start(env, goal="raid")
    assert not r.ok and r.rejected, dict(r)
    env, G = world()
    r = start(env)
    assert not r.ok and r.needs_button == "World" and "--here World" in r.error, dict(r)
    env, G = world("G.calibrate_all()")
    r = start(env, dry_run=True)
    assert r.ok and r.dry_run and len(G.clicks) == 0 and len(G.queue) == 0, dict(r)
    assert start(env).ok
    r = start(env)
    assert not r.ok and r.waiting and "already" in r.error, dict(r)
    assert len(G.inputs) == 0                                         # nothing pressed before the frames run
    G.pump()
    assert G.screen is None


@test("a step that differs stops there, says what it saw, and shuts the screen: the click goes elsewhere; Diplomacy not OKAY")
def _():
    env, G = world("G.calibrate_all(); G.site_mode = G.MODES.MISSIONS")
    start(env)
    G.pump()
    last = env.status().last
    assert last.step == "site" and last.reason == "unexpected" and "world/MISSIONS" in last.why, dict(last)
    assert G.screen is None and last.closed
    env, G = world("G.calibrate_all(); G.diplomacy = G.NEWM.NOT_IN_CONTACT")
    start(env)
    G.pump()
    last = env.status().last
    assert last.step == "site" and "NOT_IN_CONTACT" in last.why, dict(last)
    assert G.screen is None
    # New mission comes up for another site (the click took the mouse's site, not the one written)
    env, G = world("""G.calibrate_all()
G.react = function(x, y)
  G.react_default(x, y)
  if G.screen and G.screen.view_mode == G.MODES.NEW_MISSION then G.screen.focus_site = 77 end
end""")
    start(env)
    G.pump()
    last = env.status().last
    assert last.step == "site" and "site 77, not 42" in last.why, dict(last)
    assert len([c for c in lst(G.clicks)]) == 2                        # Diplomacy never pressed


@test("a screen that never comes: waited for, then stopped; nothing pressed to close what isn't open")
def _():
    env, G = world("G.calibrate_all(); G.world_btn = {3, 38}; G.react = function() end")
    start(env)
    n = G.pump()
    last = env.status().last
    assert last.step == "open" and last.reason == "unexpected" and "did not open" in last.why, dict(last)
    assert "LEAVESCREEN" not in lst(G.inputs) and last.closed is True
    assert n >= env.WAIT_FRAMES // env.POLL_FRAMES                     # it waited


@test("the Diplomacy button not shown yet: stopped at the goal, the screen shut; a controller left behind is noted")
def _():
    env, G = world("""G.calibrate_all()
G.persist['ai-overseer/world-buttons'].Diplomacy = nil""")
    start(env)
    G.pump()
    last = env.status().last
    assert last.step == "goal" and last.reason == "needs_button" and "--here Diplomacy" in last.why, dict(last)
    assert G.screen is None
    env, G = world("G.calibrate_all(); G.keep_ac = true")
    start(env)
    G.pump()
    last = env.status().last
    assert last.step == "make_contact" and last.controller_left is True, dict(last)


@test("a World screen that won't shut: Esc pressed a few times, then said (closed false)")
def _():
    env, G = world("G.calibrate_all(); G.stuck = true")
    start(env)
    G.pump()
    last = env.status().last
    assert last.closed is False and lst(G.inputs).count("LEAVESCREEN") == env.CLOSE_TRIES, (dict(last), lst(G.inputs))
    assert env.RUN is None


@test("calibrate: World kept from the bottom-left (follows a taller window), Diplomacy only on New mission")
def _():
    env, G = world()
    gps = getattr(env.df, "global").gps
    gps.mouse_x, gps.mouse_y = 4, 37
    r = env.calibrate("World")
    assert r.ok, dict(r)
    gps.dimy = 50
    x, y = env.button_at(env.buttons().World)
    assert (x, y) == (4, 47), (x, y)
    r = env.calibrate("Diplomacy")
    assert not r.ok and "New mission" in r.error, dict(r)
    G.screen_new()
    G.screen.view_mode = G.MODES.NEW_MISSION
    gps.mouse_x, gps.mouse_y = 60, 30
    r = env.calibrate("Diplomacy")
    assert r.ok and env.button_at(env.buttons().Diplomacy) == (60, 30)
    assert not env.calibrate("Confirm").ok


@test("an error inside a step stops the run and still shuts the screen")
def _():
    env, G = world("G.calibrate_all()")
    LUA.execute("local env = ...; env.STEPS[2].check = function() error('boom') end", env)
    start(env)
    G.pump()
    last = env.status().last
    assert last.result == "error" and last.step == "site" and "boom" in last.why and G.screen is None, dict(last)
    assert env.RUN is None


@test("a screen that comes a few frames late is waited for (the trade screen's lesson)")
def _():
    env, G = world("""G.calibrate_all()
G.react = function(x, y)
  if not G.screen then
    -- the World screen shows three frames after the click
    table.insert(G.queue, function() table.insert(G.queue, function() table.insert(G.queue, function()
      G.screen_new() end) end) end)
    return
  end
  G.react_default(x, y)
end""")
    start(env)
    G.pump()
    last = env.status().last
    assert last.step == "make_contact" and last.reason == "not_recorded", dict(last)
    run = G.files["/df/dfhack-config/ai-overseer/mission-send.json"].runs[1]
    assert [t.step for t in lst(run.trail) if t.what == "ok"] == ["open", "site", "goal"]


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
