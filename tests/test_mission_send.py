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
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = module_src("ai-mission-send.lua")


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
  for i = 0, 4 do nm[i] = NEWM.OKAY end                   -- (0.105.39) every goal OKAY unless a test says
  for k, v in pairs(G.allowed or {}) do nm[GOALS[k]] = v end
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
  squad = {find = function(id) if id < 100 then return {id = id} end end},
  army_controller = {find = function(id)
    if id > 900 then return {id = id, goal = G.ac_goal or GOALS.DIPLOMACY, entity_id = 200, site_id = 42,
                             data = {goal_site_invasion = {intent = -1, flag = 0}}} end
  end},
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
    return {load_settings = function() return G.settings or {send_messenger = G.on} end}
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
function G.calibrate_goal(name)
  G.persist['ai-overseer/world-buttons'][name] = {anchor = 'centre', dx = G.dip_btn[1] - 50, dy = G.dip_btn[2] - 20}
end
G.MODES, G.NEWM, G.GOALS = MODES, NEWM, GOALS
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



# ---------------------------------------------------------------------------
# (0.105.39) every goal: rescue, recover_artifact, explore, raid, pillage,
# tribute, conquer besides make_contact

ALL_ON = "G.settings = {missions = 'all', send_missions = true, send_messenger = true}"
GOALS7 = ["rescue", "recover_artifact", "explore", "raid", "pillage", "tribute", "conquer"]
BUTTON = {"rescue": "Rescue", "recover_artifact": "Recover", "explore": "Explore", "raid": "Raid",
          "pillage": "Pillage", "tribute": "Tribute", "conquer": "Conquer"}


def calibrated(extra: str = ""):
    names = "; ".join(f"G.calibrate_goal('{b}')" for b in BUTTON.values())
    return world(f"G.calibrate_all(); {names}; {ALL_ON}; {extra}")


def go(env, goal, **kw):
    a = {"site_id": 42, "goal": goal, "squad_ids": LUA.table_from([3, 4])}
    a.update(kw)
    return env.start(LUA.table_from(a))


@test("(0.105.39) each goal maps to DF's mission goal read at runtime (the site invasions with their intent); "
      "unknown goals and goals DF lacks are refused, never guessed")
def _():
    env, G = calibrated()
    want = {"make_contact": "DIPLOMACY", "rescue": "RESCUE_HF", "recover_artifact": "RECOVER_ARTIFACT",
            "explore": "SITE_INVASION", "raid": "SITE_INVASION", "pillage": "SITE_INVASION",
            "tribute": "SITE_INVASION", "conquer": "SITE_INVASION"}
    for g, dfname in want.items():
        assert env.df_goal(g) == G.GOALS[dfname], g
        r = go(env, g, dry_run=True)
        assert r.ok and r.dry_run and r.df_goal == dfname, (g, dict(r))
    assert go(env, "explore", dry_run=True).intent == "EXPLORE"
    assert go(env, "tribute", dry_run=True).intent == "DEMAND_TRIBUTE"
    assert go(env, "conquer", dry_run=True).intent == "TAKE_OVER_SITE"
    for bad in ("assassinate", "", 5):
        r = go(env, bad)
        assert not r.ok and r.rejected and "unknown goal" in r.error, (bad, dict(r))
    # DF's enum without the name: refused with why
    LUA.execute("local env = ...; env.df.army_controller_goal_type.RESCUE_HF = nil", env)
    r = go(env, "rescue")
    assert not r.ok and r.rejected and "RESCUE_HF" in r.error, dict(r)
    # no enum at all: the fallback table (df-structures 53.x values)
    LUA.execute("local env = ...; env.df.army_controller_goal_type = nil", env)
    assert env.df_goal("rescue") == 18 and env.df_goal("explore") == 2 and env.df_goal("make_contact") == 25
    assert len(G.clicks) == 0 and len(G.queue) == 0


@test("(0.105.39) the goal's button not shown: refused up front with needs_button and the probe command; "
      "the World button first")
def _():
    env, G = world(f"G.calibrate_all(); {ALL_ON}")
    for g in GOALS7:
        r = go(env, g)
        assert not r.ok and r.rejected and r.needs_button == BUTTON[g], (g, dict(r))
        assert "probe_missions.py --here " + BUTTON[g] in r.error, dict(r)
    env, G = world(ALL_ON)
    r = go(env, "rescue")
    assert r.needs_button == "World" and "--here World" in r.error, dict(r)
    assert len(G.clicks) == 0 and len(G.queue) == 0
    # calibration takes every goal button's name
    G.screen_new()
    G.screen.view_mode = G.MODES.NEW_MISSION
    for b in BUTTON.values():
        assert env.calibrate(b).ok, b


@test("(0.105.39) the Rules: make_contact needs make_contact + send_messenger; the rest the missions choice "
      "(off / rescue / explore / all) and send_missions")
def _():
    cases = [
        ("{missions = 'all', send_missions = false, send_messenger = true}", "rescue", "Send missions"),
        ("{missions = 'off', send_missions = true}", "rescue", "is off: rescue is not allowed"),
        ("{missions = 'rescue', send_missions = true}", "explore", "explore is not allowed"),
        ("{missions = 'explore', send_missions = true}", "raid", "raid is not allowed"),
        ("{missions = 'explore', send_missions = true}", "conquer", "not allowed"),
        ("{missions = 'nonsense', send_missions = true}", "rescue", "not known"),
        ("{send_missions = true}", "tribute", "is rescue: tribute"),        # the default choice: rescue
        ("{make_contact = false, send_messenger = true}", "make_contact", "Make contact"),
        ("{missions = 'all', send_missions = true}", "make_contact", "Send the messenger"),
    ]
    for settings, goal, why in cases:
        env, G = calibrated(f"G.settings = {settings}")
        r = go(env, goal)
        assert not r.ok and r.rejected and why in r.error, (settings, goal, dict(r))
        assert len(G.queue) == 0
    for settings, goal in [("{send_missions = true}", "rescue"), ("{send_missions = true}", "recover_artifact"),
                           ("{missions = 'explore', send_missions = true}", "explore"),
                           ("{missions = 'all', send_missions = true}", "pillage")]:
        env, G = calibrated(f"G.settings = {settings}")
        assert go(env, goal, dry_run=True).ok, (settings, goal)
    # the Rules unreadable: refused
    env, G = calibrated()
    LUA.execute("""local env = ...; local rq = env.reqscript
      env.reqscript = function(n) if n == 'ai-overseer-settings' then error('gone') end return rq(n) end""", env)
    r = go(env, "rescue")
    assert not r.ok and "could not be read" in r.error, dict(r)


@test("(0.105.39) not while the player is busy; one run at a time; squads needed and checked; a dry run says "
      "what it would do and touches nothing")
def _():
    env, G = calibrated("G.busy = 'the squads screen is open'")
    r = go(env, "explore")
    assert not r.ok and r.waiting and "squads screen" in r.error, dict(r)
    env, G = calibrated()
    r = env.start(LUA.table_from({"site_id": 42, "goal": "explore"}))
    assert not r.ok and r.rejected and "squad_ids" in r.error, dict(r)
    r = go(env, "explore", squad_ids=LUA.table_from([3, 500]))
    assert not r.ok and "no squad 500" in r.error, dict(r)
    r = go(env, "rescue", hf_id=-3)
    assert not r.ok and r.rejected, dict(r)
    r = go(env, "rescue", hf_id=77, dry_run=True)
    assert r.ok and r.dry_run and r.hf_id == 77 and lst(r.squad_ids) == [3, 4] and r.button == "Rescue", dict(r)
    assert lst(r.steps) == ["open", "site", "goal", "target", "squads", "details", "confirm"]
    assert lst(r.recorded) == ["open", "site", "goal"] and r.stops_at == "target"
    assert r.messenger is None                                    # no messenger asked for a rescue
    r = go(env, "explore", dry_run=True)
    assert lst(r.steps) == ["open", "site", "goal", "intent", "squads", "details", "confirm"] and r.stops_at == "intent"
    assert len(G.clicks) == 0 and len(G.queue) == 0 and len(G.inputs) == 0 and G.screen is None
    assert env.RUN is None
    assert go(env, "explore").ok
    r = go(env, "rescue")
    assert not r.ok and r.waiting and "already" in r.error, dict(r)
    r = start(env)
    assert not r.ok and r.waiting, dict(r)
    G.pump()
    assert G.screen is None and env.RUN is None


@test("(0.105.39) a non-contact run: World, the site, the goal's button; stops at the first unrecorded step, "
      "Mission details written down in full, the World screen shut")
def _():
    for goal, first in (("explore", "intent"), ("rescue", "target"), ("recover_artifact", "target"),
                        ("raid", "intent")):
        env, G = calibrated(f"G.ac_goal = 0")
        r = go(env, goal, hf_id=12 if goal == "rescue" else None)
        assert r.ok and r.sending and r.goal == goal and r.stops_at == first, dict(r)
        st = env.status()
        assert st.running.goal == goal
        G.pump()
        assert G.screen is None and env.RUN is None, goal
        last = env.status().last
        assert last.goal == goal and last.result == "stopped" and last.step == first, dict(last)
        assert last.reason == "not_recorded" and "probe_missions.py --watch" in last.why and last.closed is True
        clicks = [tuple(lst(c)) for c in lst(G.clicks)]
        assert clicks == [(3, 38), (50, 20), (50, 15)], clicks
        assert lst(G.inputs)[-1] == "LEAVESCREEN"
        run = G.files["/df/dfhack-config/ai-overseer/mission-send.json"].runs[1]
        assert run.goal == goal and lst(run.squad_ids) == [3, 4] and run.step == first
        assert [t.step for t in lst(run.trail) if t.what == "ok"] == ["open", "site", "goal"]
        assert run.saw.mode == "MISSION_DETAILS" and run.saw.goal_ok == "OKAY" and run.saw.selected_ac == 901
        d = run.details
        assert d.mode == "MISSION_DETAILS" and d.selected_ac == 901, goal
        assert d.ac.id == 901 and d.ac.entity_id == 200 and d.ac.goal_name == "SITE_INVASION", dict(d.ac)
        assert d.ac_data.goal_site_invasion.intent == -1
        assert d.new_mission.DIPLOMACY == "OKAY" and d.new_mission.RESCUE_HF == "OKAY"
        if goal == "rescue":
            assert run.hf_id == 12


@test("(0.105.39) a goal not OKAY on New mission for the site stops at the site step with DF's reason")
def _():
    env, G = calibrated("G.allowed = {SITE_INVASION = G.NEWM.INACCESSIBLE}")
    go(env, "explore")
    G.pump()
    last = env.status().last
    assert last.goal == "explore" and last.step == "site" and "Explore is INACCESSIBLE" in last.why, dict(last)
    assert G.screen is None and len(lst(G.clicks)) == 2


@test("(0.105.39) status: goals with button shown and last recorded step; last.goal; the steps data-driven "
      "(a step added to RECORDED with an act is run)")
def _():
    env, G = world("G.calibrate_all(); G.calibrate_goal('Rescue')")
    st = env.status()
    goals = st.goals
    assert set(goals.keys()) == {"make_contact"} | set(GOALS7)
    assert goals.make_contact.button is True and goals.rescue.button is True and goals.explore.button is False
    assert all(goals[g].recorded == "goal" for g in goals.keys())
    assert st.last is None and st.on is True
    start(env)
    G.pump()
    assert env.status().last.goal == "make_contact"
    # an old outcome saved before goals existed reads as make_contact
    LUA.execute("local env = ...; env.LAST = nil", env)
    G.persist["ai-overseer/mission-send"] = LUA.table_from({"site_id": 42, "result": "stopped"})
    assert env.status().last.goal == "make_contact"
    # recording a step later: its act/check in STEP_DEFS, its name in RECORDED
    env, G = calibrated()
    LUA.execute("""local env = ...
      env.STEP_DEFS.intent = {name = 'intent', expect = function() return true end,
                              act = function() return true end, check = function() return 'ok' end}
      table.insert(env.RECORDED.explore, 'intent')""", env)
    assert env.last_recorded("explore") == "intent" and env.last_recorded("raid") == "goal"
    go(env, "explore")
    G.pump()
    last = env.status().last
    assert last.step == "squads" and last.reason == "not_recorded", dict(last)


@test("(0.105.39) make_contact unchanged: no goal means make_contact; its steps and stop as recorded")
def _():
    env, G = world("G.calibrate_all()")
    r = env.start(LUA.table_from({"site_id": 42}))
    assert r.ok and r.goal == "make_contact" and lst(r.steps) == ["open", "site", "goal", "make_contact", "messenger", "confirm"]
    G.pump()
    last = env.status().last
    assert last.step == "make_contact" and last.reason == "not_recorded" and G.screen is None
    assert lst(env.step_names()) == ["open", "site", "goal", "make_contact", "messenger", "confirm"]


@test("(0.105.39) the bridge: every goal passed on with squads and target; bad goals, squads, ids and the Rules "
      "switches refused there before the sender")
def _():
    import test_bridge_memory as tbm
    tbm.reset()
    M = tbm.H.module()
    tbm.LUA.execute("""local M, H = ...
      H.calls = {}
      H.rules = {missions = 'all', send_missions = true, send_messenger = true}
      H.scripts = {['ai-mission-send'] = {start = function(a) table.insert(H.calls, a); return {ok = true, sending = true} end},
                   ['ai-overseer-settings'] = {load_settings = function() return H.rules end}}
    """, M, tbm.H)
    T = tbm.t
    for g in ["make_contact"] + GOALS7:
        r = M.act_send_mission(T({"site_id": 42, "goal": g, "squad_ids": T([1, 2]), "hf_id": 5, "artifact_id": 6}))
        assert r.ok, (g, dict(r))
    c = tbm.H.calls[2]
    assert c.goal == "rescue" and c.site_id == 42 and [c.squad_ids[1], c.squad_ids[2]] == [1, 2]
    assert c.hf_id == 5 and c.artifact_id == 6 and c.dry_run is False
    r = M.act_send_mission(T({"site_id": 42}))
    assert r.ok and tbm.H.calls[len(tbm.H.calls)].goal == "make_contact"
    n = len(tbm.H.calls)
    for bad in ({"site_id": 4, "goal": "assassinate", "squad_ids": T([1])},
                {"site_id": 4, "goal": "explore"},
                {"site_id": 4, "goal": "explore", "squad_ids": T([-1])},
                {"site_id": 4, "goal": "explore", "squad_ids": "1"},
                {"site_id": 4, "goal": "explore", "squad_ids": T(list(range(21)))},
                {"site_id": 4, "goal": "rescue", "squad_ids": T([1]), "hf_id": "x"}):
        r = M.act_send_mission(T(bad))
        assert not r.ok and r.rejected, bad
    for rules, goal, why in (({"missions": "all", "send_missions": False}, "raid", "Send missions"),
                             ({"missions": "explore", "send_missions": True}, "raid", "not allowed"),
                             ({"missions": "off", "send_missions": True}, "rescue", "not allowed"),
                             ({"send_missions": True}, "explore", "not allowed"),
                             ({"missions": "all", "send_missions": True}, "make_contact", "Send the messenger"),
                             ({"make_contact": False, "send_messenger": True}, "make_contact", "Make contact")):
        tbm.H.rules = T(rules)
        r = M.act_send_mission(T({"site_id": 4, "goal": goal, "squad_ids": T([1])}))
        assert not r.ok and r.rejected and why in r.error, (rules, goal, dict(r))
    assert len(tbm.H.calls) == n

if __name__ == "__main__":
    finish()
