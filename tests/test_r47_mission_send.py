"""(0.105.47) The World-screen missions recorded live on 14 Nov (DF 53.17,
the War-hold A save): Make contact and a Raid sent end to end by
lua/ai-mission-send.lua on a fake World screen that steps through the
recorded states (NEW_MISSION -> Diplomacy / Attack -> MISSION_DETAILS with a
new controller -> the messenger's / a squad's tick box -> Done assigning ->
MISSIONS_LIST), its text read with dfhack.screen.readTile; the ways a run
stops (INACCESSIBLE, no messenger, text unreadable, a row that doesn't read
right); the sites DF can't reach dropped (ai-missions, the planner); the
departure watch; the way off the map (lua/ai-mission-way.lua, the gate
watcher's hold, the planner's opening).

    python tests/test_r47_mission_send.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = module_src("ai-mission-send.lua")

FAKE = r"""
local src, setup = ...
local function enum(names, first)
  local e = {}
  for i, n in ipairs(names) do e[(first or 0) + i - 1] = n; e[n] = (first or 0) + i - 1 end
  return e
end
local function vec(list)
  local v = setmetatable({_n = 0}, {__len = function(self) return rawget(self, '_n') end})
  for _, x in ipairs(list or {}) do v[v._n] = x; v._n = v._n + 1 end
  return v
end
local function push(v, x) v[v._n] = x; v._n = v._n + 1 end
local MODES = enum({'NORMAL', 'CIVILIZATIONS', 'MISSIONS_LIST', 'MISSION_DETAILS', 'NEWS', 'REPORTS',
                    'CITIZENS', 'ARTIFACTS', 'NEW_MISSION'})
local GOALS = enum({'HOLD_TERRITORY', 'HARASS', 'SITE_INVASION', 'RAMPAGE', 'CAMP', 'GUARD', 'HUNTING', 'PATROL',
                    'PACIFY_SITE', 'PACIFY_CONNECTED_HAMLET', 'WAIT', 'ESCAPE', 'MOVE_TO_SITE', 'RECLAIM_SITE',
                    'CREATE_NEW_SITE', 'POSSE', 'SITE_WORK', 'RECOVER_ARTIFACT', 'RESCUE_HF', 'MAKE_REQUEST',
                    'PERFORM_TASK', 'ASSASSINATE_HF', 'ABDUCT_HF', 'SABOTAGE_ENTITY', 'INFILTRATE_SOCIETY', 'DIPLOMACY'})
local NEWM = enum({'OKAY', 'NOT_DISPLAYED', 'OWN_SITE', 'OWN_CIV', 'NOT_UNDER_YOUR_CONTROL', 'NO_CIV',
                   'NO_REQUESTABLE_WORKERS', 'INACCESSIBLE', 'NO_MILITARY_GOALS_HF', 'NO_MEET_WORKERS_HF', 'NOT_IN_CONTACT'})
local INTENT = enum({'NONE', 'OBLITERATION', 'TAKE_OVER_SITE', 'INSTALL_PUPPET_GOVERNMENT', 'DEMAND_TRIBUTE',
                     'RAID', 'EXPLORE', 'PILLAGE'}, -1)
local TOPIC = enum({'DiscussCurrent', 'RequestPeace', 'TreeQuota', 'BecomeLandHolder', 'PromoteLandHolder',
                    'ExportAgreement', 'ImportAgreement', 'PleasantPlace', 'WorldStatus', 'TributeAgreement',
                    'DemandSurrender', 'InduceWar', 'InducePeace', 'DeclareWar', 'SeekAlliance', 'OpenTrade', 'ImproveTrade'})
local SQO = enum({'MOVE', 'KILL_LIST', 'DEFEND_BURROWS', 'PATROL_ROUTE', 'TRAIN', 'DRIVE_ENTITY_OFF_SITE',
                  'CAUSE_TROUBLE_FOR_ENTITY', 'KILL_HF', 'DRIVE_ARMIES_FROM_SITE', 'RETRIEVE_ARTIFACT', 'RAID_SITE', 'RESCUE_HF'})
local G = {persist = {}, files = {}, inputs = {}, clicks = {}, queue = {}, screen = nil,
           settings = {send_messenger = true, send_missions = true, missions = 'all'},
           allowed = {}, messengers = {{id = 77, histfig = 15}}, squad_ids = {3, 4, 5}, squads = {},
           controllers = vec(), next_ac = 3461425, blocked = {}}
local env = setmetatable({}, {__index = _G})
G.env, G.vec, G.push, G.MODES, G.NEWM, G.INTENT, G.GOALS = env, vec, push, MODES, NEWM, INTENT, GOALS
for _, id in ipairs(G.squad_ids) do
  G.squads[id] = {id = id, orders = vec(), positions = vec({{occupant = 100 + id}})}
end
function G.open_world()
  local nm = {}
  for i = 0, 25 do nm[i] = NEWM.NOT_DISPLAYED end
  nm[GOALS.DIPLOMACY] = NEWM.OKAY
  nm[GOALS.SITE_INVASION] = NEWM.OKAY
  for k, v in pairs(G.allowed) do nm[GOALS[k]] = NEWM[v] end
  local ms = vec()
  for _, m in ipairs(G.messengers) do push(ms, m) end
  local sq = vec()
  for _, id in ipairs(G.squad_ids) do push(sq, G.squads[id]) end
  G.screen = {view_mode = MODES.NORMAL, focus_site = -1, new_mission = nm, selected_ac = -1,
              army_controller = vec(), messenger_epp = ms, messenger_flag = vec({{LOCKED_IN = false}}),
              squad = sq, region_cent_x = 64, region_cent_y = 64}
end
-- the labels each mode shows: {x, y, text}
function G.labels()
  local s = G.screen
  if not s then return {} end
  local m = MODES[s.view_mode]
  local out = {}
  local function L(x, y, t) table.insert(out, {x, y, t}) end
  if m == 'NEW_MISSION' then
    L(98, 2, 'Peacemine'); L(98, 5, 'Attack'); L(98, 8, 'Request workers'); L(98, 12, 'Diplomacy')
  elseif m == 'MISSION_DETAILS' then
    L(55, 39, 'Done assigning')
    local ac = G.ac()
    if ac.goal == GOALS.DIPLOMACY then
      L(95, 1, 'Make contact at Peacemine'); L(96, 5, 'Make peace'); L(96, 17, 'Make contact')
      for i = 0, #s.messenger_epp - 1 do
        L(40, 2 + 3 * i, G.messenger_text or 'Led Glidedgorges')
      end
      if #s.messenger_epp == 0 then L(40, 2, 'No messengers available') end
    else
      L(95, 1, 'Raid Crackeddreamed')
      L(96, 5, 'Raid (squads will try to avoid detection)'); L(96, 8, 'Pillage (openly attack)')
      L(96, 11, 'Raze (openly attack and destroy site)'); L(96, 14, 'Demand one-time tribute')
      L(96, 17, 'Demand ongoing tribute'); L(96, 20, 'Conquer and occupy')
      for i = 0, #s.squad - 1 do
        local on = false
        for j = 0, #ac.assigned_squads - 1 do if ac.assigned_squads[j] == s.squad[i].id then on = true end end
        L(40, 3 + 3 * i, (G.row_text and G.row_text[i]) or (on and 'On this mission' or 'No specific orders'))
      end
    end
  elseif m == 'MISSIONS_LIST' then
    L(20, 1, '1 messenger here, no messengers traveling')
  end
  return out
end
function G.ac() return G.screen.army_controller[G.screen.selected_ac] end
local function label_at(x, y)
  for _, l in ipairs(G.labels()) do
    if l[2] == y and x >= l[1] and x < l[1] + #l[3] then return l[3] end
  end
end
function G.new_ac(goal)
  local s = G.screen
  local ac = {id = G.next_ac, goal = goal, site_id = s.focus_site, entity_id = 200,
              assigned_squads = vec(), assigned_epp_epp_id = vec(), year = 120, year_tick = 5000, data = {}}
  G.next_ac = G.next_ac + 1
  if goal == GOALS.DIPLOMACY then
    ac.data.goal_diplomacy = {topic = G.topics_empty and vec() or vec({TOPIC.OpenTrade})}
  else
    ac.data.goal_site_invasion = {invasion_intent = G.intent0 or INTENT.RAID}
  end
  push(G.controllers, ac)
  push(s.army_controller, ac)
  s.selected_ac = #s.army_controller - 1
  s.view_mode = MODES.MISSION_DETAILS
end
function G.react(x, y)
  local s = G.screen
  if not s then
    if x == 3 and y == 38 then G.open_world() end
    return
  end
  local m = MODES[s.view_mode]
  if m == 'NORMAL' then
    if s.focus_site >= 0 then s.view_mode = MODES.NEW_MISSION end
  elseif m == 'NEW_MISSION' then
    local l = label_at(x, y)
    if l == 'Attack' and s.new_mission[GOALS.SITE_INVASION] == NEWM.OKAY then G.new_ac(GOALS.SITE_INVASION)
    elseif l == 'Diplomacy' and s.new_mission[GOALS.DIPLOMACY] == NEWM.OKAY then G.new_ac(GOALS.DIPLOMACY) end
  elseif m == 'MISSION_DETAILS' then
    local ac = G.ac()
    if x == 85 and (y - 2) % 3 == 0 and not G.tick_noop then
      local i = (y - 2) // 3
      if ac.goal == GOALS.DIPLOMACY then
        if i < #s.messenger_epp then push(ac.assigned_epp_epp_id, s.messenger_epp[i].id) end
      elseif i < #s.squad then push(ac.assigned_squads, s.squad[i].id) end
      table.insert(G.ticks, {x, y})
      return
    end
    local l = label_at(x, y)
    if l == 'Done assigning' then
      s.view_mode = MODES.MISSIONS_LIST
      if ac.goal == GOALS.SITE_INVASION and not G.no_order then
        for j = 0, #ac.assigned_squads - 1 do
          push(G.squads[ac.assigned_squads[j]].orders, {_raid = true, site_id = ac.site_id})
        end
      end
    elseif l == 'Make contact' then push(ac.data.goal_diplomacy.topic, TOPIC.OpenTrade)
    elseif not G.intent_frozen and l == 'Pillage (openly attack)' then ac.data.goal_site_invasion.invasion_intent = INTENT.PILLAGE
    elseif not G.intent_frozen and l == 'Demand one-time tribute' then ac.data.goal_site_invasion.invasion_intent = INTENT.DEMAND_TRIBUTE
    elseif not G.intent_frozen and l == 'Conquer and occupy' then ac.data.goal_site_invasion.invasion_intent = INTENT.TAKE_OVER_SITE end
  end
end
G.ticks = {}
local function site(id, name, x, y) return {id = id, name = {text = name}, pos = {x = x, y = y}} end
local SITES = {[59] = site(59, 'Peacemine', 40, 60), [73] = site(73, 'Crackeddreamed', 28, 54)}
env.df = {
  world_view_mode_type = MODES, army_controller_goal_type = GOALS, world_new_mission_type = NEWM,
  invasion_intent_type = INTENT, meeting_topic = TOPIC, squad_order_type = SQO,
  squad_order_raid_sitest = {is_instance = function(_, o) return o._raid == true end},
  viewscreen_worldst = {},
  global = {cur_year = 120, cur_year_tick = 5000,
            gps = {mouse_x = 7, mouse_y = 9, dimx = 150, dimy = 66, tile_pixel_x = 8, tile_pixel_y = 12},
            world = {army_controllers = {all = G.controllers}}, plotinfo = {group_id = 200, site_id = 1430}},
  squad = {find = function(id) return G.squads[id] end},
  army_controller = {find = function(id)
    for i = 0, #G.controllers - 1 do if G.controllers[i].id == id then return G.controllers[i] end end
  end},
  world_site = {find = function(id) return SITES[id] end},
  historical_entity = {find = function(id)
    if id ~= 200 then return nil end
    return {positions = {own = {{id = 9, code = 'MESSENGER'}},
                         assignments = {{id = 77, position_id = 9, histfig = G.no_messenger and -1 or 15}}}}
  end},
  historical_figure = {find = function(id)
    if id == 15 then return {unit_id = 5, name = {first_name = 'led'}} end
    if id > 100 then return {unit_id = id + 1000} end
  end},
  unit = {find = function(id) if id == 5 then return {id = 5, flags1 = {inactive = false}, flags2 = {killed = false}} end end},
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
  gui = {getCurFocus = function() return {focus()} end, getDFViewscreen = function() return {} end,
         getViewscreenByType = function() return G.screen end},
  screen = {readTile = function(x, y)
    if G.unreadable then return nil end
    for _, l in ipairs(G.labels()) do
      if l[2] == y and x >= l[1] and x < l[1] + #l[3] then return {ch = string.byte(l[3], x - l[1] + 1)} end
    end
    return {ch = 32}
  end},
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
      elseif key == 'LEAVESCREEN' and G.screen then G.screen = nil end
    end}
  end
  error('require ' .. name)
end
env.reqscript = function(name)
  if name == 'ai-overseer-settings' then
    return {load_settings = function() return G.settings end,
            MISSION_GOALS = {off = {}, rescue = {'rescue', 'recover_artifact'},
                             all = {'rescue', 'recover_artifact', 'explore', 'raid', 'pillage', 'tribute', 'conquer'}}}
  end
  if name == 'ai-camera' then return {player_busy = function() return nil end} end
  if name == 'ai-missions' then return {probe_screen = function() return {screen = G.screen ~= nil, focus = focus()} end} end
  if name == 'ai-mission-way' then
    return {way = function(ids) G.way_ids = ids; return {known = true, n = #ids, blocked = G.blocked} end}
  end
  error('reqscript ' .. name)
end
function G.pump(n)
  local ran = 0
  while #G.queue > 0 and ran < (n or 2000) do
    local fn = table.remove(G.queue, 1)
    fn()
    ran = ran + 1
  end
  return ran
end
G.persist['ai-overseer/world-buttons'] = {World = {anchor = 'left-bottom', lx = 3, by = 28}}
assert(load(setup or '', 'setup', 't', setmetatable({G = G}, {__index = _G})))()
assert(load(src, 'ai-mission-send', 't', env))()
return env, G
"""

LUA = None


def world(setup: str = ""):
    global LUA
    LUA = LuaRuntime(unpack_returned_tuples=True)
    return LUA.execute(FAKE, SRC, setup)


def lst(t):
    return [t[i] for i in range(1, len(t) + 1)] if t is not None else []


def clicks(G):
    return [tuple(lst(c)) for c in lst(G.clicks)]


def send(env, G, **kw):
    a = {"site_id": 59, "goal": "make_contact"}
    a.update(kw)
    if "squad_ids" in a:
        a["squad_ids"] = LUA.table_from(a["squad_ids"])
    r = env.start(LUA.table_from(a))
    G.pump()
    return r, env.status().last


# --- the recorded runs, end to end ------------------------------------------------------

@test("Make contact end to end as recorded: World, the site, Diplomacy by its word, Make contact left as DF chose, "
      "the messenger's box (24 right / 37 up of Done assigning), Done assigning -> MISSIONS_LIST; the mission set up")
def _():
    env, G = world()
    r, last = send(env, G)
    assert r.ok and r.stops_at is None, dict(r)
    assert last.result == "sent" and last.reason is None, dict(last)
    assert clicks(G) == [(3, 38), (75, 33), (102, 12), (85, 2), (61, 39)], clicks(G)
    ac = G.controllers[0]
    assert ac.goal == G.GOALS.DIPLOMACY and ac.site_id == 59 and ac.assigned_epp_epp_id._n == 1
    assert last.sent_ac == ac.id and last.controller_left is None and last.left_ids is None, dict(last)
    assert G.screen is None and lst(G.inputs)[-1] == "LEAVESCREEN"           # the World screen shut after
    run = G.files["/df/dfhack-config/ai-overseer/mission-send.json"].runs[1]
    assert [t.step for t in lst(run.trail) if t.what == "ok"] == ["open", "site", "goal", "make_contact", "messenger",
                                                                  "confirm"]
    assert lst(run.topics) == ["OpenTrade"] and any("make_contact" in x for x in lst(run.left))
    assert run.messenger_flag_before is False


@test("Raid end to end as recorded: Attack by its word, Raid left (DF's default), the chosen squad's box on its row, "
      "the side orders left, Done assigning; the squad's raid order checked; the World button the only calibration")
def _():
    env, G = world()
    r, last = send(env, G, goal="raid", site_id=73, squad_ids=[4])
    assert r.ok, dict(r)
    assert last.result == "sent", dict(last)
    assert clicks(G) == [(3, 38), (75, 33), (100, 5), (85, 5), (61, 39)], clicks(G)    # squad 4: the second row
    ac = G.controllers[0]
    assert ac.goal == G.GOALS.SITE_INVASION and ac.site_id == 73 and ac.assigned_squads._n == 1 and ac.assigned_squads[0] == 4
    assert G.squads[4].orders._n == 1 and G.squads[4].orders[0].site_id == 73
    assert G.squads[3].orders._n == 0
    assert last.order_unverified is None and last.sent_ac == ac.id
    st = env.status()
    assert st.goals.raid.button is True and st.goals.raid.all_recorded is True and st.goals.raid.words is True
    assert st.goals.make_contact.all_recorded is True and st.goals.rescue.all_recorded is False


@test("two squads ticked in one go, each on its row; a squad without its raid order after Done assigning: "
      "waited for, then stopped (not counted set up)")
def _():
    env, G = world()
    r, last = send(env, G, goal="raid", site_id=73, squad_ids=[3, 5])
    assert last.result == "sent" and clicks(G)[3:5] == [(85, 2), (85, 8)], (dict(last), clicks(G))
    env, G = world("G.no_order = true")
    r, last = send(env, G, goal="raid", site_id=73, squad_ids=[3])
    assert last.result == "stopped" and last.step == "confirm" and "raid order" in last.why, dict(last)


@test("pillage: its intent row pressed by its word in the right panel and read back on the controller; "
      "an intent that doesn't change stops the run at the intent before any squad is ticked")
def _():
    env, G = world()
    r, last = send(env, G, goal="pillage", site_id=73, squad_ids=[3])
    assert last.result == "sent", dict(last)
    assert (99, 8) in clicks(G) and G.controllers[0].data.goal_site_invasion.invasion_intent == G.INTENT.PILLAGE
    env, G = world("G.intent_frozen = true")
    r, last = send(env, G, goal="tribute", site_id=73, squad_ids=[3])
    assert last.step == "intent" and last.result == "stopped", dict(last)
    assert not any(c[0] == 85 for c in clicks(G))                       # no squad ticked
    # Raid's default left as it is even when another intent is pressed elsewhere
    env, G = world()
    r, last = send(env, G, goal="conquer", site_id=73, squad_ids=[3])
    assert last.result == "sent" and G.controllers[0].data.goal_site_invasion.invasion_intent == G.INTENT.TAKE_OVER_SITE


@test("Make contact with no topic chosen: the 'Make contact' row pressed (never the title 'Make contact at ...')")
def _():
    env, G = world("G.topics_empty = true")
    r, last = send(env, G)
    assert last.result == "sent", dict(last)
    assert (101, 17) in clicks(G) and (100, 1) not in clicks(G), clicks(G)


# --- the ways a run stops ---------------------------------------------------------------

@test("an island: New mission says INACCESSIBLE: stopped at the site, reason 'inaccessible', nothing pressed there")
def _():
    env, G = world("G.allowed = {SITE_INVASION = 'INACCESSIBLE', DIPLOMACY = 'INACCESSIBLE'}")
    r, last = send(env, G, goal="raid", site_id=73, squad_ids=[3])
    assert last.step == "site" and last.reason == "inaccessible" and "INACCESSIBLE" in last.why, dict(last)
    assert clicks(G) == [(3, 38), (75, 33)] and G.screen is None


@test("DF lists no messenger (recorded before one was appointed): stopped at the messenger, reason no_messenger; "
      "a row that doesn't read the messenger's name: nothing ticked")
def _():
    env, G = world("G.messengers = {}")
    r, last = send(env, G)
    assert last.step == "messenger" and last.reason == "no_messenger", dict(last)
    env, G = world("G.messenger_text = 'Someone Else'")
    r, last = send(env, G)
    assert last.step == "messenger" and last.reason == "not_found" and "Led" in last.why, dict(last)
    assert (85, 2) not in clicks(G)


@test("text that can't be read (TrueType): Attack never clicked blind (stopped 'unreadable'); "
      "Diplomacy falls back to its calibrated place only")
def _():
    env, G = world("G.unreadable = true")
    r, last = send(env, G, goal="raid", site_id=73, squad_ids=[3])
    assert last.step == "goal" and last.reason == "unreadable", dict(last)
    assert clicks(G) == [(3, 38), (75, 33)]
    env, G = world("G.unreadable = true")
    r, last = send(env, G)
    assert last.step == "goal" and last.reason == "needs_button", dict(last)


@test("a squad row reading something else (another order): stopped before any box is pressed; "
      "a tick that changes nothing on the controller: waited for, then stopped")
def _():
    env, G = world("G.row_text = {[1] = 'Patrol the walls'}")
    r, last = send(env, G, goal="raid", site_id=73, squad_ids=[3, 4])
    assert last.step == "squads" and last.reason == "not_found" and "squad 4" in last.why, dict(last)
    assert not any(c[0] == 85 for c in clicks(G))
    env, G = world("G.tick_noop = true")
    r, last = send(env, G, goal="raid", site_id=73, squad_ids=[3])
    assert last.step == "squads" and last.reason == "unexpected", dict(last)


@test("travellers who can't walk off the map: the send refused (waiting, no_way_out), nothing pressed")
def _():
    env, G = world("G.blocked = {1104}")
    r = env.start(LUA.table_from({"site_id": 73, "goal": "raid", "squad_ids": LUA.table_from([4])}))
    assert not r.ok and r.waiting and r.no_way_out and "walk off the map" in r.error, dict(r)
    assert len(G.queue) == 0 and lst(G.way_ids) == [1104]
    env, G = world("G.blocked = {5}")
    r = env.start(LUA.table_from({"site_id": 59, "goal": "make_contact"}))
    assert not r.ok and r.no_way_out, dict(r)


# --- the word finder and the recorded geometry (pure) ------------------------------------

@test("find_words: whole words only, inside an area; pick_word takes the bottom-most, never the title "
      "'Make contact at'; tick_spot from the recorded spot beside Done assigning, row by row")
def _():
    env, G = world()
    rows = LUA.table_from({0: " Make contact at Peacemine ", 1: " Raider Raid ", 2: " Make contact  ", 3: "xAttack Attack"})
    m = env.find_words(rows, "Raid")
    assert len(m) == 1 and m[1].x == 8, [(x.x, x.y) for x in lst(m)]
    assert [x.x for x in lst(env.find_words(rows, "Attack"))] == [8]
    p = env.pick_word(env.find_words(rows, "Make contact"), " at")
    assert p.y == 2 and p.cx == 6
    assert env.pick_word(env.find_words(rows, "Make contact", LUA.table_from({"y1": 1})), " at") is None
    # the recorded numbers: Done assigning clicked x60-64 y39-40, the tick x83-86 y2-3
    text = {y: " " * 150 for y in range(66)}
    text[39] = " " * 55 + "Done assigning" + " " * 81
    text[2] = " " * 40 + "Led Glidedgorges" + " " * 94
    rows = LUA.table_from(text)
    done = env.done_anchor(rows)
    assert (done.cx, done.y) == (61, 39)
    x, y = env.tick_spot(rows, done, 0, LUA.table_from(["Led"]))
    assert (x, y) == (85, 2) and 83 <= x <= 86 and 2 <= y <= 3
    x, why = env.tick_spot(rows, done, 1, LUA.table_from(["Led"]))
    assert x is None and "row 2" in why
    x, why = env.tick_spot(rows, done, 13, LUA.table_from(["Led"]))
    assert x is None and "beyond" in why


# --- ai-missions: inaccessible sites, the allowed map, the departure watch ----------------

MISSIONS_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local RM = {}
env.df = {global = {world = {world_data = {region_map = RM}}}}
assert(load(src, 'ai-missions', 't', env))()
return env, RM
"""


@test("ai-missions: a site on another landmass than the fort is DF's INACCESSIBLE (other_landmass); "
      "an unreadable landmass says nothing")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, RM = lua.execute(MISSIONS_FAKE, (ROOT / "lua" / "ai-missions.lua").read_text(encoding="utf-8"))
    lua.execute("""local RM = ...
      RM[40] = {[60] = {landmass_id = 1}}
      RM[98] = {[104] = {landmass_id = 2}}""", RM)
    assert env.landmass_at(40, 60) == 1 and env.landmass_at(98, 104) == 2 and env.landmass_at(5, 5) is None
    assert env.other_landmass(1, 2) is True and env.other_landmass(1, 1) is False
    assert env.other_landmass(1, None) is False
    s1 = lua.eval("{pos = {x = 40, y = 60}}")
    assert env.site_landmass(s1) == 1
    assert env.ALLOWED_MODES.NEW_MISSION and env.ALLOWED_MODES.MISSION_DETAILS and not env.ALLOWED_MODES.NORMAL


# --- ai-mission-way: the way off the map, the hold -----------------------------------------

WAY_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
local W = {now = 1000, opened = {}, refuse = nil}
local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
W.GATES = {scanned = true, closed = {[1] = true},
           entrances = {{id = 1, kind = 'hatch', x = 108, y = 149, z = 171, outs = {[key(108, 151, 171)] = true}},
                        {id = 2, kind = 'cavern', x = 5, y = 5, z = 20, outs = {[key(5, 6, 20)] = true}, },
                        {id = 3, kind = 'door', x = 121, y = 133, z = 166, outs = {[key(121, 135, 166)] = true}}}}
env.reqscript = function(name)
  if name == 'ai-gates' then
    return {GATES = W.GATES, open_entrance = function(id, dry, cav)
      if W.refuse then return {ok = false, rejected = true, waiting = true, error = W.refuse} end
      if not dry then table.insert(W.opened, id) end
      return {ok = true, dry_run = dry or nil, entrance = id}
    end}
  end
  if name == 'ai-util' then return {abs_tick = function() return W.now end} end
  error(name)
end
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
-- walk groups: the surface outside is group 7; the fort inside 3 (shut off); cavern 9
env.dfhack = {maps = {getWalkableGroup = function(p)
  if p.z == 20 then return 9 end
  if p.y >= 150 or p.y == 135 then return 7 end
  return W.inside_group or 3
end}}
env.df = {unit = {find = function(id)
  return {pos = {x = 110, y = id == 2 and 160 or 140, z = 171}, flags1 = {inactive = false}, flags2 = {killed = false}}
end}}
assert(load(src, 'ai-mission-way', 't', env))()
return env, W
"""


def way_world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, W = lua.execute(WAY_FAKE, (ROOT / "lua" / "ai-mission-way.lua").read_text(encoding="utf-8"))
    return lua, env, W


@test("ai-mission-way: travellers inside a fort whose surface ways are shut can't walk out (the cavern's group "
      "doesn't count); one already outside can; the AI's shut surface gates listed (not the player's, not a cavern's)")
def _():
    lua, env, W = way_world()
    g = env.out_groups()
    assert g[7] is True and g[9] is None
    r = env.way(lua.table_from([1, 2]))
    assert r.known is True and r.n == 2 and lst(r.blocked) == [1], (r.n, lst(r.blocked))
    W.inside_group = 7                                        # the way open: inside joins the outside's group
    assert len(env.way(lua.table_from([1])).blocked) == 0
    shut = lst(env.shut_ai())
    assert [e.id for e in shut] == [1] and shut[0].kind == "hatch"
    W.GATES.scanned = False
    assert env.way(lua.table_from([1])).known is False       # the entrances not mapped: can't tell


@test("ai-mission-way: open_way opens by open_entrance and holds the gate a day against the watcher; "
      "a dry run holds nothing; open_entrance's refusal (an enemy near) passes through with no hold")
def _():
    lua, env, W = way_world()
    r = env.open_way(1, "make_contact 59", True)
    assert r.ok and r.dry_run and not env.mission_held(1) and len(W.opened) == 0
    r = env.open_way(1, "make_contact 59")
    assert r.ok and lst(W.opened) == [1] and r.hold_until == 1000 + env.HOLD_TICKS and env.mission_held(1)
    assert lst(env.holds())[0].key == "make_contact 59"
    W.now = 1000 + env.HOLD_TICKS + 1
    assert not env.mission_held(1)                            # the hold ends by itself
    W.refuse = "an enemy is 5 tiles from this entrance"
    r = env.open_way(3, "raid 73")
    assert not r.ok and r.waiting and not env.mission_held(3)


GATES_WATCH = r"""
local M, held = ...
PULLED = {}
df = {building = {find = function(id) return {door_flags = {forbidden = false}, jobs = {}} end},
      global = {world = {units = {active = {}}}, cur_year_tick = 0}}
dfhack = dfhack or {}
dfhack.units = {getCitizens = function() return {} end}
dfhack.timeout = function() return nil end
dfhack.gui = {showAnnouncement = function() end}
M.reqscript = function(name)
  if name == 'ai-mission-way' then return {mission_held = function(id) return held[id] == true end} end
  error(name)
end
M.visible_dangers = function() return {{pos = {x = 0, y = 0, z = 0}}} end
M.citizens_outside = function() return 0 end
M.distance_to = function(e, p) return M.DIST end
M.ai_piece = function() return true end
M.lure_holds = function() return {} end
"""


@test("the gate watcher: an entrance held for a mission isn't shut on the 'danger coming, nobody outside' look; "
      "an enemy within IMMINENT still shuts it; one not held is shut as before")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    M = lua.execute(r"""
      local src = ...
      local env = setmetatable({}, {__index = _G})
      assert(load(src, 'ai-gates', 't', env))()
      return env""", module_src("ai-gates.lua"))
    for dist, held, shut in ((20, True, False), (5, True, True), (20, False, True)):
        lua.execute(GATES_WATCH, M, lua.table_from({1: held}))
        M.DIST = dist
        e = lua.table_from({"id": 1, "kind": "door", "outs": lua.table(),
                            "equipment": lua.table_from({1: lua.table_from({"id": 10, "kind": "door"})})})
        M.GATES = lua.table_from({"armed": True, "scanned": True, "closed": lua.table(), "peak": 1,
                                  "entrances": lua.table_from({1: e})})
        M.check()
        assert (M.GATES.closed[1] is True) == shut, (dist, held, M.GATES.closed[1])
        if held and not shut:
            assert M.GATES.mission_held_skips == 1
    lua.execute("df = nil; dfhack = nil")


# --- the planner -------------------------------------------------------------------------

def _state(**kw):
    s = {"date": {"year": 120, "tick": 5000}, "missions": {}, "others_on_map": {"threats_that_can_reach_dwarves": 0},
         "settings": {"traits": {}}}
    s.update(kw)
    return s


class _Mem:
    def __init__(self):
        self.missions_seen = {}


@test("planner: a site DF said INACCESSIBLE is remembered (note_missions) and never the target again, for every "
      "goal; that stop blocks neither the goal nor asks the player")
def _():
    import planner_missions as pm
    send = {"last_by_goal": {"raid": {"goal": "raid", "result": "stopped", "reason": "inaccessible", "step": "site",
                                      "site_id": 1600, "tick": 120 * 403200 + 4000}}}
    targets = [{"goal": "raid", "site_id": 1600, "hostile": True, "dist": 3},
               {"goal": "raid", "site_id": 73, "hostile": True, "dist": 9}]
    s = _state(missions={"send": send, "targets": targets})
    m = _Mem()
    pm.note_missions(s, m)
    assert m.missions_seen["unreachable"] == {"1600": 120 * 403200 + 4000}
    s2 = _state(missions={"targets": targets}, settings={"traits": {}})
    s2["settings"]["missions"] = "all"
    import planner_core
    orig = planner_core.player_rules
    try:
        pm.player_rules = lambda st: {**orig(st), "missions": "all"}
        t, stopped = pm.mission_target(s2, pm.PLANNER_CONFIG, m)
        assert t["site_id"] == 73 and stopped == [], (t, stopped)
        s3 = _state(missions={"send": send, "targets": targets})
        t, stopped = pm.mission_target(s3, pm.PLANNER_CONFIG)
        assert t["site_id"] == 73 and stopped == [], (t, stopped)       # the run's own outcome, without memory
        notes = []
        pm._stopped_needs_you(s3, "raid", pm.PLANNER_CONFIG, notes)
        assert notes == []
        # forgotten after mission_unreachable_ticks
        s4 = _state(date={"year": 124, "tick": 0}, missions={})
        pm.note_unreachable(s4, m)
        assert m.missions_seen["unreachable"] == {}
    finally:
        pm.player_rules = orig


@test("planner: Make contact skips a site on another landmass and one DF said INACCESSIBLE; "
      "a send that found no messenger listed waits a day without a Needs you")
def _():
    import planner_world as pw
    s = _state(missions={"sites": {"nearest": [
        {"id": 1600, "relation": "NoContact", "dist": 2, "inaccessible": "another landmass"},
        {"id": 61, "relation": "NoContact", "dist": 4},
        {"id": 59, "relation": "NoContact", "dist": 6}]},
        "send": {"last_by_goal": {"make_contact": {"result": "stopped", "reason": "inaccessible", "site_id": 61,
                                                   "tick": 120 * 403200}}}},
        offices={"offices": {"MESSENGER": {"held": ["Led Glidedgorges"]}}})
    site = pw._contact_site(s, None)
    assert site["id"] == 59, site
    s["missions"]["send"] = {"buttons": ["World"], "last_by_goal": {"make_contact": {
        "result": "stopped", "reason": "no_messenger", "step": "messenger", "site_id": 59, "tick": 120 * 403200 + 4900}}}
    orig = pw.player_rules
    try:
        pw.player_rules = lambda st: {**orig(st), "send_messenger": True, "make_contact": True}
        props, notes = [], []
        pw._contact_rule(s, pw.PLANNER_CONFIG, props, notes, None)
        assert props == [] and any("no messenger" in n for n in notes), notes
        assert not any(n.startswith("Needs you") for n in notes), notes
    finally:
        pw.player_rules = orig


@test("planner: the messenger is appointed in a young fort too once the AI sends it by the World screen")
def _():
    import planner_world as pw
    s = _state(offices={"offices": {"MESSENGER": {"held": [], "vacant": 1}}})
    orig, oy = pw.player_rules, pw.young_fort
    try:
        pw.young_fort = lambda st, cfg: True
        pw.player_rules = lambda st: {**orig(st), "make_contact": True, "appoint_nobles": True, "send_messenger": False}
        props = []
        pw._messenger_rule(s, pw.PLANNER_CONFIG, props, [])
        assert props == []
        pw.player_rules = lambda st: {**orig(st), "make_contact": True, "appoint_nobles": True, "send_messenger": True}
        pw._messenger_rule(s, pw.PLANNER_CONFIG, props, [])
        assert props and props[0].action == {"type": "appoint", "office": "MESSENGER"}
    finally:
        pw.player_rules, pw.young_fort = orig, oy


@test("planner: a mission set up but not set out (no army for its controller) is said with its days; past "
      "mission_depart_wait_days, once, with who it waits on; its setting out noted; no second one sent meanwhile")
def _():
    import planner_missions as pm
    T = 403200
    c = {"id": 3466393, "goal": "SITE_INVASION", "site": "Crackeddreamed", "site_id": 73, "squads": [4],
         "departed": False, "since": {"year": 120, "tick": 0},
         "waiting": [{"unit_id": 1104, "path_goal": "None", "on_map": True}]}
    send = {"last_by_goal": {"raid": {"goal": "raid", "result": "sent", "site_id": 73, "sent_ac": 3466393}}}
    s = _state(date={"year": 120, "tick": 2 * 1200}, missions={"controllers": [c], "send": send})
    assert "set up 2 day(s) ago, not yet set out" in pm.departure_words(s, c)
    m = _Mem()
    assert pm.note_departures(s, m) == []
    s = _state(date={"year": 120, "tick": 15 * 1200}, missions={"controllers": [c], "send": send})
    n = pm.note_departures(s, m)
    assert len(n) == 1 and "15 days ago and still hasn't set out" in n[0] and "unit 1104" in n[0], n
    assert pm.note_departures(s, m) == []                                      # said once
    c2 = dict(c, departed=True)
    s = _state(date={"year": 120, "tick": 16 * 1200}, missions={"controllers": [c2], "send": send})
    n = pm.note_departures(s, m)
    assert n and "set out" in n[0], n
    # the controller with the fort's squad counts as a mission out: one at a time
    s = _state(missions={"controllers": [c], "squads": [{"id": 4, "members": 9, "away": 0, "controller": 3466393}],
                         "targets": [{"goal": "raid", "site_id": 74, "hostile": True}]})
    out = pm._fort_missions_out(s)
    assert out and out[0]["id"] == 3466393


WAY = {"known": True, "squads": {"4": 9, "5": 0}, "messenger_blocked": True,
       "shut": [{"id": 1, "kind": "hatch", "x": 108, "y": 149, "z": 171}]}


@test("planner: travellers shut in by the AI's own gate and nothing threatening: mission_way proposed for that "
      "gate and the send waits; with a threat about: 'the gates are shut for ...: the mission waits'; "
      "no AI gate holds it: said, no gate touched; free to walk out: the send goes")
def _():
    import planner_missions as pm
    cfg = pm.PLANNER_CONFIG
    s = _state(missions={"way_out": WAY})
    props, notes = [], []
    assert pm.way_out_gate(s, cfg, 9, "a mission to raid X", "raid 73", props, notes) is False
    assert [p.action for p in props] == [{"type": "mission_way", "id": 1, "mission": "raid 73"}], props
    s = _state(missions={"way_out": WAY}, others_on_map={"threats_that_can_reach_dwarves": 2})
    props, notes = [], []
    assert pm.way_out_gate(s, cfg, 9, "a mission to raid X", "raid 73", props, notes) is False
    assert props == [] and any("the gates are shut for a threat" in n and "waits" in n for n in notes), notes
    s = _state(missions={"way_out": dict(WAY, shut=[])})
    props, notes = [], []
    assert pm.way_out_gate(s, cfg, 9, "m", "k", props, notes) is False and props == []
    assert "none of the AI's gates" in notes[0]
    props, notes = [], []
    assert pm.way_out_gate(_state(missions={"way_out": WAY}), cfg, 0, "m", "k", props, notes) is True
    assert pm.way_out_gate(_state(missions={}), cfg, 9, "m", "k", props, notes) is True       # unknown: not held
    assert props == []


@test("planner: Make contact with the messenger shut in: the gate opened first, no send_mission this cycle")
def _():
    import planner_world as pw
    s = _state(missions={"sites": {"nearest": [{"id": 59, "relation": "NoContact", "dist": 6, "name": "Peacemine"}]},
                         "send": {"buttons": ["World"]}, "way_out": WAY},
               offices={"offices": {"MESSENGER": {"held": ["Led Glidedgorges"]}}})
    orig = pw.player_rules
    try:
        pw.player_rules = lambda st: {**orig(st), "send_messenger": True, "make_contact": True}
        props, notes = [], []
        pw._contact_rule(s, pw.PLANNER_CONFIG, props, notes, None)
        assert [p.action["type"] for p in props] == ["mission_way"], [p.action for p in props]
        s["missions"]["way_out"] = dict(WAY, messenger_blocked=False)
        props = []
        pw._contact_rule(s, pw.PLANNER_CONFIG, props, [], None)
        assert [p.action["type"] for p in props] == ["send_mission"], [p.action for p in props]
    finally:
        pw.player_rules = orig


@test("planner: a set-up mission whose travellers can't walk out for mission_way_stuck_hours: the gate opened "
      "once (booked from the gate's hold), then only said; plan() writes no memory")
def _():
    import json
    import planner_missions as pm
    T = 403200
    c = {"id": 3461425, "goal": "DIPLOMACY", "site": "Peacemine", "site_id": 59, "departed": False,
         "since": {"year": 120, "tick": 0}, "way_blocked": 1, "waiting": [{"unit_id": 5, "path_goal": "MarauderMill"}]}
    m = _Mem()
    s = _state(date={"year": 120, "tick": 100}, missions={"controllers": [c], "way_out": WAY})
    props, notes = [], []
    pm._mission_way_rule(s, pm.PLANNER_CONFIG, props, notes, m)
    assert props == []                                                          # 2 hours: not yet
    s = _state(date={"year": 120, "tick": 400}, missions={"controllers": [c], "way_out": WAY})
    before = json.dumps(m.missions_seen, sort_keys=True)
    pm._mission_way_rule(s, pm.PLANNER_CONFIG, props, notes, m)
    assert [p.action for p in props] == [{"type": "mission_way", "id": 1, "mission": "ac 3461425"}]
    assert json.dumps(m.missions_seen, sort_keys=True) == before
    # the bridge held the gate for "ac 3461425": booked by note_missions; next time only said
    s = _state(date={"year": 120, "tick": 500},
               missions={"controllers": [c], "way_out": dict(WAY, holds=[{"id": 1, "key": "ac 3461425"}])})
    pm.note_missions(s, m)
    props, notes = [], []
    pm._mission_way_rule(s, pm.PLANNER_CONFIG, props, notes, m)
    assert props == [] and any("opened a gate for them once" in n for n in notes), notes


@test("the bridge: mission_way in the action table (dry run allowed), its label; ai-mission-way a bridge module; "
      "the settings comment and the watch list updated")
def _():
    br = (ROOT / "lua" / "ai-bridge.lua").read_text(encoding="utf-8")
    assert "mission_way = function(a)" in br and "'mission_way'," in br and "'ai-mission-way'," in br
    import overseer
    assert "mission_way" in overseer.SHORT_WORDS
    w = (ROOT / "docs" / "watch-in-game.md").read_text(encoding="utf-8")
    assert "Done assigning" in w


if __name__ == "__main__":
    finish()
