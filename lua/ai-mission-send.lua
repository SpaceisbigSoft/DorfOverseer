-- (0.105.24, 13b) Sending the messenger on "Make contact" by driving DF's
-- World screen, as the player does. DFHack can't create a mission from data
-- safely (an army controller written by hand isn't known to be one DF will
-- run), so the AI presses the screen's own buttons, the way the trade and
-- meeting screens are driven (lua/ai-trade.lua, lua/ai-diplomacy.lua).
--
-- The screen's steps were recorded once (probe_missions.py --watch, 26 Oct,
-- the player's "Make contact at Cottageflings"):
--   world/NORMAL          hovering a site sets the screen's `focus_site`
--   (a click)          -> world/NEW_MISSION, `new_mission[DIPLOMACY]` OKAY
--   (the goal chosen)  -> world/MISSION_DETAILS, a new army controller in
--                         `selected_ac`
-- and it stopped there: choosing Make contact, the messenger and the confirm
-- have never been seen. So this is a state machine over those steps that
-- checks the screen after each one and stops at the FIRST step whose screen
-- differs from what was recorded (or that was never recorded), writes
-- exactly what it saw (mission-send.json and the `missions` report's
-- `send`), and closes the World screen: DF is never left on it.
--
-- It runs only when the Rules switch `send_messenger` is on (off by default),
-- the player isn't using the game (the camera director's player_busy), the
-- messenger is home and the screen to open (the World button) and the goal
-- button (Diplomacy) were shown to the AI once (probe_missions.py --here).
-- The planner sends it only when nothing threatens the fort.
--
-- (0.105.39) Generalized to every goal of the missions design: rescue,
-- recover_artifact, explore, raid, pillage, tribute, conquer besides
-- make_contact. Each goal's DF mission goal (the enum `new_mission` is
-- indexed by, df.army_controller_goal_type; explore/raid/pillage/tribute/
-- conquer are DF's SITE_INVASION with an intent chosen on Mission details)
-- is read at runtime, a fallback table only where the enum is missing; an
-- unknown goal is refused, never guessed. The steps are data: RECIPES (every
-- step a goal's mission takes) and RECORDED (the ones seen and given an act);
-- recording a step later means writing its act/check in STEP_DEFS and its
-- name in RECORDED. Everything after MISSION_DETAILS is unrecorded for every
-- goal: a run stops there, writes all the Mission details screen and its
-- army controller held (run.details), and closes the World screen.
--
--   start(a)        a = {site_id, goal = 'make_contact', squad_ids, hf_id,
--                   artifact_id, dry_run}: begin a run
--   status()        the run under way and the last one's outcome (small)
--   calibrate(name) the mouse is on that button now: remember where
--   buttons()       the buttons shown so far
--@ module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

SEND_KEY = 'ai-overseer/mission-send'        -- the last run's outcome (the save's site data)
BUTTONS_KEY = 'ai-overseer/world-buttons'    -- where the player showed the buttons
LOG_KEEP = 4                                 -- runs kept in mission-send.json
POLL_FRAMES = 2                              -- frames between looks at the screen
WAIT_FRAMES = 40                             -- frames a step may take to show its screen
RUN_FRAMES = 400                             -- a whole run, at most (then stopped)
CLOSE_TRIES = 4                              -- LEAVESCREEN presses to shut the World screen
-- the buttons the player shows the AI once, and what each is kept from:
-- the World button sits in the bottom-left toolbar; the goal buttons in the
-- middle of the New mission panel
BUTTON_ANCHORS = {World = 'left-bottom', Diplomacy = 'centre', Rescue = 'centre', Recover = 'centre',
                  Explore = 'centre', Raid = 'centre', Pillage = 'centre', Tribute = 'centre', Conquer = 'centre'}

-- (0.105.39) the goals: DF's mission goal (army_controller_goal_type, the
-- index of the screen's new_mission), the button on New mission, the intent
-- (invasion_intent_type) chosen later on Mission details for the site
-- invasions, and what the player picks there (a prisoner, an artifact)
GOALS = {
    make_contact     = {df = 'DIPLOMACY', button = 'Diplomacy'},
    rescue           = {df = 'RESCUE_HF', button = 'Rescue', target = 'hf_id', squads = true},
    recover_artifact = {df = 'RECOVER_ARTIFACT', button = 'Recover', target = 'artifact_id', squads = true},
    explore          = {df = 'SITE_INVASION', intent = 'EXPLORE', button = 'Explore', squads = true},
    raid             = {df = 'SITE_INVASION', intent = 'RAID', button = 'Raid', squads = true},
    pillage          = {df = 'SITE_INVASION', intent = 'PILLAGE', button = 'Pillage', squads = true},
    tribute          = {df = 'SITE_INVASION', intent = 'DEMAND_TRIBUTE', button = 'Tribute', squads = true},
    conquer          = {df = 'SITE_INVASION', intent = 'TAKE_OVER_SITE', button = 'Conquer', squads = true},
}
GOAL_ORDER = {'make_contact', 'rescue', 'recover_artifact', 'explore', 'tribute', 'raid', 'pillage', 'conquer'}
-- only where df.army_controller_goal_type is missing (df-structures 53.x)
GOAL_FALLBACK = {SITE_INVASION = 2, RECOVER_ARTIFACT = 17, RESCUE_HF = 18, MAKE_REQUEST = 19, DIPLOMACY = 25}
-- world_new_mission_type by value, where that enum is missing
NEWM_FALLBACK = {[-1] = 'NONE', [0] = 'OKAY', 'NOT_DISPLAYED', 'OWN_SITE', 'OWN_CIV', 'NOT_UNDER_YOUR_CONTROL',
                 'NO_CIV', 'NO_REQUESTABLE_WORKERS', 'INACCESSIBLE', 'NO_MILITARY_GOALS_HF', 'NO_MEET_WORKERS_HF',
                 'NOT_IN_CONTACT', 'ALREADY_IN_CONTACT', 'ALREADY_AT_WAR', 'ALREADY_HAVE_PEACE',
                 'ALREADY_HAVE_ALLIANCE', 'AT_WAR', 'CANNOT_COMMUNICATE', 'HOSTILE_ENTITY', 'NOT_TRADING',
                 'ALREADY_TRADING', 'NO_CIVILIZATION_MILITARY_GOALS_HF'}
-- the Rules choice `missions` (lua/ai-overseer-settings.lua): which goals each allows
MISSIONS_ALLOW = {
    off = {},
    rescue = {rescue = true, recover_artifact = true},
    explore = {rescue = true, recover_artifact = true, explore = true},
    all = {rescue = true, recover_artifact = true, explore = true, raid = true, pillage = true,
           tribute = true, conquer = true},
}
MISSIONS_DEFAULT = 'rescue'
MAX_SQUADS = 20

RUN = RUN or nil                             -- the run under way (one at a time)

-- ---------------------------------------------------------------------------
-- small helpers

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function log_path()
    local ok, p = pcall(function() return dfhack.getDFPath() .. '/dfhack-config/ai-overseer/mission-send.json' end)
    return ok and p or 'mission-send.json'
end

local function enum_name(enum, v)
    if v == nil or enum == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return nil
end

local function focus_string()
    local ok, f = pcall(function() return dfhack.gui.getCurFocus(true)[1] end)
    return ok and tostring(f or '') or ''
end

-- the World screen when it is anywhere on the screen stack, else nil
function world_screen()
    if not df.viewscreen_worldst then return nil end
    local ok, scr = pcall(function() return dfhack.gui.getViewscreenByType(df.viewscreen_worldst, 0) end)
    if ok and scr then return scr end
    return nil
end

-- an id from a field that is an id (a number) or an object with one; -1 is none
local function id_of(v)
    if v == nil then return nil end
    if type(v) == 'number' then return v >= 0 and math.tointeger(v) or nil end
    local ok, id = pcall(function() return v.id end)
    if ok and type(id) == 'number' and id >= 0 then return math.tointeger(id) end
    return nil
end

-- ---------------------------------------------------------------------------
-- what the screen shows now: the few fields the steps are checked against

-- (0.105.39) a goal's index in new_mission: from DF's enum by name; the
-- fallback table only where the enum is missing; else nil and why
function df_goal(goal)
    local g = GOALS[goal]
    if not g then return nil, 'unknown goal ' .. tostring(goal) end
    local E = df.army_controller_goal_type
    if E ~= nil then
        local ok, v = pcall(function() return E[g.df] end)
        if ok and type(v) == 'number' then return math.tointeger(v) or v end
        return nil, 'DF has no mission goal ' .. g.df .. ' (for ' .. goal .. ')'
    end
    local v = GOAL_FALLBACK[g.df]
    if v then return v end
    return nil, 'mission goal ' .. g.df .. ' unknown here (for ' .. goal .. ')'
end

local function newm_name(v)
    if v == nil then return nil end
    return enum_name(df.world_new_mission_type, v) or NEWM_FALLBACK[v] or tostring(v)
end

function read_state(run)
    local st = {focus = focus_string()}
    pcall(function() st.controllers = #df.global.world.army_controllers.all end)
    local scr = world_screen()
    st.world = scr ~= nil
    if not scr then return st end
    -- the mode: from the focus string as recorded (world/NEW_MISSION), else
    -- the screen's view_mode by name
    st.mode = st.focus:match('^world/([%u_]+)')
    if not st.mode then
        local okm, m = pcall(function() return scr.view_mode end)
        st.mode = okm and enum_name(df.world_view_mode_type, m) or nil
    end
    local okf, fs = pcall(function() return scr.focus_site end)
    if okf then st.focus_site = id_of(fs) else st.unreadable = 'focus_site' end
    pcall(function()
        local g = df.army_controller_goal_type.DIPLOMACY
        local v = scr.new_mission[g]
        st.diplomacy = newm_name(v)
    end)
    -- (0.105.39) the run's goal: what New mission says of it
    if run and run.df_goal then
        if run.goal == 'make_contact' then st.goal_ok = st.diplomacy
        else pcall(function() st.goal_ok = newm_name(scr.new_mission[run.df_goal]) end) end
    end
    local oka, ac = pcall(function() return scr.selected_ac end)
    if oka then st.selected_ac = id_of(ac) end
    return st
end

-- the few fields, as words, for the log and the report
local function seen(st)
    return {focus = st.focus, world = st.world, mode = st.mode, focus_site = st.focus_site,
            diplomacy = st.diplomacy, goal_ok = st.goal_ok, selected_ac = st.selected_ac,
            controllers = st.controllers}
end

-- (0.105.39) all the Mission details screen and its new army controller
-- hold that can be read: what the later steps (the squads, the target,
-- the intent, the confirm) will be recorded from. Game text is data:
-- strings truncated; at most a few dozen fields each.
local function plain(v)
    local tv = type(v)
    if tv == 'number' or tv == 'boolean' then return v end
    if tv == 'string' then return v:sub(1, 60) end
    return nil
end

local function fields_of(obj, cap)
    local out, n = {}, 0
    pcall(function()
        for k, v in pairs(obj) do
            if n >= (cap or 40) then break end
            local pv = plain(v)
            if pv == nil and type(v) == 'userdata' then pv = id_of(v) end
            if pv ~= nil then out[tostring(k)] = pv; n = n + 1 end
        end
    end)
    return out
end

local function ids_of(vec, cap)
    local out = {}
    pcall(function()
        for i = 0, math.min(#vec, cap or 20) - 1 do
            local v = vec[i]
            local id = id_of(v)
            if id == nil then
                local okw, w = pcall(function() return v.whole end)
                id = okw and plain(w) or nil
            end
            table.insert(out, id == nil and -1 or id)
        end
    end)
    return out
end

function details(st)
    local scr = world_screen()
    if not scr then return nil end
    local d = {mode = st and st.mode or nil}
    for _, f in ipairs({'squad', 'squad_flag', 'focus_site_prisoner', 'focus_site_artifact',
                        'focus_site_requestable_worker', 'messenger_epp', 'messenger_ent', 'messenger_flag',
                        'request_nem', 'army_controller'}) do
        local ok, vec = pcall(function() return scr[f] end)
        if ok and vec ~= nil then d[f] = ids_of(vec) end
    end
    pcall(function() d.focus_site_messenger_candidate = scr.focus_site_messenger_candidate end)
    pcall(function() d.selected_ac = scr.selected_ac end)
    local oks, nm = pcall(function()
        local out = {}
        local E = df.army_controller_goal_type
        for _, g in ipairs(GOAL_ORDER) do
            local i = E and E[GOALS[g].df] or GOAL_FALLBACK[GOALS[g].df]
            if i then out[GOALS[g].df] = newm_name(scr.new_mission[i]) end
        end
        return out
    end)
    if oks then d.new_mission = nm end
    local id = st and st.selected_ac
    if id and df.army_controller then
        local oka, ac = pcall(function() return df.army_controller.find(id) end)
        if oka and ac then
            d.ac = fields_of(ac, 40)
            pcall(function() d.ac.goal_name = enum_name(df.army_controller_goal_type, ac.goal) end)
            local okd, data = pcall(function() return ac.data end)
            if okd and data ~= nil then
                d.ac_data = {}
                pcall(function()
                    for k, v in pairs(data) do
                        local tv = type(v)
                        if tv == 'userdata' or tv == 'table' then d.ac_data[tostring(k)] = fields_of(v, 30) end
                    end
                end)
            end
        end
    end
    return d
end

-- ---------------------------------------------------------------------------
-- the buttons, shown to the AI once (as the trade and meeting screens')

function buttons()
    return U.site_get(BUTTONS_KEY, {})
end

-- Remember where a button is: the mouse is on it now (the player put it
-- there). The World button from the screen's left and bottom edges, the
-- goal buttons from its centre, so a resized window still finds them.
function calibrate(name)
    local anchor = BUTTON_ANCHORS[name]
    if not anchor then
        local names = {}
        for k in pairs(BUTTON_ANCHORS) do table.insert(names, k) end
        table.sort(names)
        return {ok = false, error = 'buttons: ' .. table.concat(names, ', ')}
    end
    local gps = df.global.gps
    local x, y = gps.mouse_x, gps.mouse_y
    if x < 0 or y < 0 then return {ok = false, error = 'the game doesn\'t know where the mouse is: put it on the button in DF'} end
    if name ~= 'World' then
        local st = read_state()
        if st.mode ~= 'NEW_MISSION' then
            return {ok = false, error = 'open the World screen, click a site so New mission shows, then put the mouse on ' .. name}
        end
    end
    local d = buttons()
    d[name] = {anchor = anchor, dx = x - gps.dimx // 2, dy = y - gps.dimy // 2, lx = x, by = gps.dimy - y,
               x = x, y = y, w = gps.dimx, h = gps.dimy}
    dfhack.persistent.saveSiteData(BUTTONS_KEY, d)
    return {ok = true, button = name, x = x, y = y, screen = {gps.dimx, gps.dimy}}
end

function button_at(b)
    local gps = df.global.gps
    if b.anchor == 'left-bottom' then return b.lx, gps.dimy - b.by end
    return gps.dimx // 2 + b.dx, gps.dimy // 2 + b.dy
end

-- a left click at (x, y), the mouse put back afterwards
local function click(x, y)
    local gps = df.global.gps
    local ox, oy = gps.mouse_x, gps.mouse_y
    gps.mouse_x, gps.mouse_y = x, y
    pcall(function()
        gps.precise_mouse_x = x * gps.tile_pixel_x + gps.tile_pixel_x // 2
        gps.precise_mouse_y = y * gps.tile_pixel_y + gps.tile_pixel_y // 2
    end)
    require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), '_MOUSE_L')
    gps.mouse_x, gps.mouse_y = ox, oy
end

local function press(name)
    local b = buttons()[name]
    if not b then
        return false, 'needs_button', 'the AI doesn\'t know where the ' .. name ..
            ' button is yet: python brain\\probe_missions.py --here ' .. name
    end
    local x, y = button_at(b)
    local ok, err = pcall(click, x, y)
    if not ok then return false, 'click_failed', 'the click failed: ' .. tostring(err):sub(1, 160) end
    return true
end

-- ---------------------------------------------------------------------------
-- the steps. Each: `expect` (the screen it starts from; else the run stops),
-- `act` (what the player did), `check` (after acting: 'ok' when the next
-- recorded screen shows and its fields are right, 'wait' while it may still
-- come, else 'bad' with why). A step not yet recorded has no act: the run
-- stops there, every field it saw written down.

STEP_DEFS = {
    open = {name = 'open',
     expect = function(st) return not st.world, 'the World screen is open already' end,
     act = function(run) return press('World') end,
     check = function(st)
         if not st.world then return 'wait', 'the World screen did not open' end
         if st.mode == 'NORMAL' then return 'ok' end
         return 'bad', 'the World screen opened in ' .. tostring(st.mode) .. ', not NORMAL (world/NORMAL was recorded)'
     end},
    -- the site: hovering one set focus_site (recorded); here it is written and
    -- the map clicked in its middle, the click the player made on the site
    site = {name = 'site',
     expect = function(st) return st.world and st.mode == 'NORMAL', 'not on world/NORMAL' end,
     act = function(run)
         local scr = world_screen()
         if not scr then return false, 'gone', 'the World screen closed' end
         local okw, err = pcall(function()
             if type(scr.focus_site) == 'number' then scr.focus_site = run.site_id
             else scr.focus_site = df.world_site.find(run.site_id) end
         end)
         if not okw then return false, 'unwritable', 'focus_site could not be set: ' .. tostring(err):sub(1, 120) end
         local gps = df.global.gps
         local ok, e = pcall(click, gps.dimx // 2, gps.dimy // 2)
         if not ok then return false, 'click_failed', 'the click failed: ' .. tostring(e):sub(1, 160) end
         return true
     end,
     check = function(st, run)
         if not st.world then return 'bad', 'the World screen closed' end
         if st.mode == 'NORMAL' then return 'wait', 'still on world/NORMAL after the click' end
         if st.mode ~= 'NEW_MISSION' then
             return 'bad', 'the click led to world/' .. tostring(st.mode) .. ', not NEW_MISSION (recorded)'
         end
         if st.focus_site ~= run.site_id then
             return 'bad', 'New mission is for site ' .. tostring(st.focus_site) .. ', not ' .. tostring(run.site_id)
         end
         if st.goal_ok ~= 'OKAY' then
             return 'bad', run.button .. ' is ' .. tostring(st.goal_ok) .. ' there, not OKAY'
         end
         return 'ok'
     end},
    -- the goal's button on New mission -> Mission details with a new army
    -- controller (recorded for Diplomacy; the other goals' buttons go the same way)
    goal = {name = 'goal',
     expect = function(st, run)
         return st.mode == 'NEW_MISSION' and st.goal_ok == 'OKAY' and st.focus_site == run.site_id,
                'not on world/NEW_MISSION with ' .. run.button .. ' OKAY for the site'
     end,
     act = function(run) return press(run.button) end,
     check = function(st, run)
         if not st.world then return 'bad', 'the World screen closed' end
         if st.mode == 'NEW_MISSION' then return 'wait', 'still on world/NEW_MISSION after ' .. run.button end
         if st.mode ~= 'MISSION_DETAILS' then
             return 'bad', run.button .. ' led to world/' .. tostring(st.mode) .. ', not MISSION_DETAILS (recorded)'
         end
         if not st.selected_ac then return 'bad', 'MISSION_DETAILS shows no new army controller (selected_ac)' end
         run.selected_ac = st.selected_ac
         return 'ok'
     end},
    -- never seen yet (no act): the next live run with the player watching
    -- records them (probe_missions.py --watch while sending one by hand)
}

-- every step each goal's mission takes, in order
local INVASION = {'open', 'site', 'goal', 'intent', 'squads', 'details', 'confirm'}
RECIPES = {
    make_contact     = {'open', 'site', 'goal', 'make_contact', 'messenger', 'confirm'},
    rescue           = {'open', 'site', 'goal', 'target', 'squads', 'details', 'confirm'},
    recover_artifact = {'open', 'site', 'goal', 'target', 'squads', 'details', 'confirm'},
    explore = INVASION, raid = INVASION, pillage = INVASION, tribute = INVASION, conquer = INVASION,
}
-- the steps recorded (seen, with an act in STEP_DEFS), per goal
RECORDED = {}
for g in pairs(GOALS) do RECORDED[g] = {'open', 'site', 'goal'} end

-- a goal's steps: the recorded ones from STEP_DEFS, the rest bare (no act)
function steps_for(goal)
    local rec = {}
    for _, n in ipairs(RECORDED[goal] or {}) do rec[n] = true end
    local out = {}
    for _, n in ipairs(RECIPES[goal] or {}) do
        local d = STEP_DEFS[n]
        if rec[n] and d and d.act then table.insert(out, d) else table.insert(out, {name = n}) end
    end
    return out
end

-- the last recorded step of a goal (the step before the run stops)
function last_recorded(goal)
    local last
    for _, st in ipairs(steps_for(goal)) do
        if not st.act then break end
        last = st.name
    end
    return last
end

STEPS = steps_for('make_contact')      -- (0.105.24) the Make contact steps, as before

function step_names(goal)
    local out = {}
    for _, s in ipairs(goal and steps_for(goal) or STEPS) do table.insert(out, s.name) end
    return out
end

-- ---------------------------------------------------------------------------
-- the log: each run's steps and what the screen held, the last LOG_KEEP runs

local function probe()
    local ok, p = pcall(function() return reqscript('ai-missions').probe_screen() end)
    return ok and p or nil
end

local function save_log(run)
    pcall(function()
        local json = require('json')
        local runs = {}
        local okr, old = pcall(json.decode_file, log_path())
        if okr and type(old) == 'table' and type(old.runs) == 'table' then runs = old.runs end
        table.insert(runs, {goal = run.goal, df_goal = run.df_goal_name, intent = run.intent,
                            squad_ids = run.squad_ids, hf_id = run.hf_id, artifact_id = run.artifact_id,
                            details = run.details,
                            site_id = run.site_id, site = run.site, started = run.started, result = run.result,
                            step = run.stopped_at, why = run.why, reason = run.reason, saw = run.saw,
                            closed = run.closed, controllers = run.controllers, trail = run.trail,
                            probe = run.probe})
        while #runs > LOG_KEEP do table.remove(runs, 1) end
        pcall(function() dfhack.filesystem.mkdir_recursive(dfhack.getDFPath() .. '/dfhack-config/ai-overseer') end)
        json.encode_file({runs = runs}, log_path())
    end)
end

local function save_outcome(run)
    local out = {goal = run.goal, site_id = run.site_id, site = run.site, result = run.result, step = run.stopped_at,
                 reason = run.reason, why = run.why, tick = now_tick(), closed = run.closed,
                 controller_left = run.controller_left, saw = run.saw}
    U.site_put(SEND_KEY, out)
    LAST = out
    return out
end

function last_outcome()
    if LAST then return LAST end
    local d = U.site_get(SEND_KEY, nil)
    return type(d) == 'table' and d or nil
end

-- ---------------------------------------------------------------------------
-- the run

local function later(n, fn)
    dfhack.timeout(n, 'frames', function()
        local ok, err = pcall(fn)
        if not ok and RUN then
            -- an error inside a step: stopped like any other surprise
            RUN.why = 'error: ' .. tostring(err):sub(1, 200)
            pcall(function() stop(RUN, 'error') end)
        end
    end)
end

-- each step's look at the screen; a step's screen once it was right also in
-- full (probe_missions' dump), so the run records what each screen held
local function trail(run, what, st)
    if #run.trail < 24 then
        table.insert(run.trail, {step = run.step_name, what = what, frame = run.frames,
                                 saw = st and seen(st) or nil, probe = what == 'ok' and probe() or nil})
    end
end

-- close the World screen (LEAVESCREEN, as Esc), checked a few frames later;
-- only ever that screen: if it isn't open, nothing is pressed
function close_world(run, tries, done)
    tries = tries or 0
    if not world_screen() then return done(true) end
    if tries >= CLOSE_TRIES then return done(false) end
    pcall(function() require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN') end)
    if not world_screen() then return done(true) end
    later(POLL_FRAMES, function() close_world(run, tries + 1, done) end)
end

-- Stop the run: what it saw written down, the World screen shut, the
-- outcome kept for the report. result: 'stopped' (a surprise or a step
-- never recorded), 'error', 'sent' (all steps done: not reachable until the
-- last steps are recorded).
function stop(run, result, reason)
    if run.stopping then return end
    run.stopping = true
    run.result = result
    run.reason = reason or run.reason
    run.stopped_at = run.step_name
    local st = read_state(run)
    run.saw = seen(st)
    run.probe = probe()
    -- (0.105.39) on Mission details: all it holds, for the steps to come
    if st.mode == 'MISSION_DETAILS' then run.details = details(st) end
    trail(run, 'stop', st)
    close_world(run, 0, function(closed)
        run.closed = closed
        local after = read_state(run)
        run.controllers = {before = run.controllers_before, after = after.controllers}
        -- a new army controller left behind once the screen shut (DF's own
        -- planned mission, or one nobody leads): written down for the player
        if run.controllers_before and after.controllers and after.controllers > run.controllers_before then
            run.controller_left = true
        end
        save_log(run)
        save_outcome(run)
        if RUN == run then RUN = nil end
    end)
end

-- one look at the screen: the current step's check, then the next step
local function tick(run)
    if RUN ~= run or run.stopping then return end
    run.frames = run.frames + POLL_FRAMES
    if run.frames > RUN_FRAMES then
        run.why = 'the run took longer than ' .. RUN_FRAMES .. ' frames'
        return stop(run, 'stopped', 'timeout')
    end
    local step = run.steps[run.step]
    local st = read_state(run)
    if run.acted then
        local verdict, why = step.check(st, run)
        if verdict == 'wait' then
            run.waited = run.waited + POLL_FRAMES
            if run.waited <= WAIT_FRAMES then return later(POLL_FRAMES, function() tick(run) end) end
            run.why = why .. ' (' .. WAIT_FRAMES .. ' frames)'
            return stop(run, 'stopped', 'unexpected')
        elseif verdict ~= 'ok' then
            run.why = why
            return stop(run, 'stopped', 'unexpected')
        end
        trail(run, 'ok', st)
        run.step, run.acted, run.waited = run.step + 1, false, 0
        step = run.steps[run.step]
        if not step then return stop(run, 'sent') end
    end
    run.step_name = step.name
    if not step.act then
        run.why = 'the step "' .. step.name .. '" has never been recorded: send one by hand while ' ..
                  'python brain\\probe_missions.py --watch records it'
        return stop(run, 'stopped', 'not_recorded')
    end
    local fine, why = step.expect(st, run)
    if not fine then
        run.why = why
        return stop(run, 'stopped', 'unexpected')
    end
    trail(run, 'act', st)
    local ok, reason, err = step.act(run)
    if not ok then
        run.why = err or reason
        return stop(run, 'stopped', reason)
    end
    run.acted, run.waited = true, 0
    later(POLL_FRAMES, function() tick(run) end)
end

-- the messenger, home: the holder of the fort's MESSENGER post, on the map
function messenger_home()
    local ok, r1, r2 = pcall(function()
        local ent = U.fort_entity()
        if not ent then return nil, 'no fort government' end
        local pos_id
        for _, p in ipairs(ent.positions.own) do if p.code == 'MESSENGER' then pos_id = p.id end end
        if not pos_id then return nil, 'the fort has no messenger\'s post' end
        for _, a in ipairs(ent.positions.assignments) do
            if a.position_id == pos_id and a.histfig ~= -1 then
                local hf = df.historical_figure.find(a.histfig)
                local u = hf and df.unit.find(hf.unit_id)
                if not u then return nil, 'the messenger is away' end
                if u.flags1.inactive or u.flags2.killed then return nil, 'the messenger is away or dead' end
                return u.id
            end
        end
        return nil, 'nobody holds the messenger\'s post'
    end)
    if not ok then return nil, 'the messenger could not be read: ' .. tostring(r1):sub(1, 120) end
    return r1, r2
end

local function settings()
    local ok, s = pcall(function() return reqscript('ai-overseer-settings').load_settings() end)
    if ok and type(s) == 'table' then return s end
    return nil
end

-- (0.105.39) the Rules for a goal: make_contact needs make_contact (on by
-- default) and send_messenger; the others the `missions` choice allowing the
-- goal and send_missions. Returns true, or false and why.
function goal_allowed(goal, s)
    if type(s) ~= 'table' then return false, 'the Rules could not be read' end
    if goal == 'make_contact' then
        if s.make_contact == false then return false, 'the Rules switch "Make contact" is off' end
        if s.send_messenger ~= true then
            return false, 'the Rules switch "Send the messenger by the World screen" is off'
        end
        return true
    end
    if not GOALS[goal] then return false, 'unknown goal ' .. tostring(goal) end
    local m = s.missions
    if m == nil then m = MISSIONS_DEFAULT end
    local allow = MISSIONS_ALLOW[m]
    if not allow then return false, 'the Rules choice "Missions" is ' .. tostring(m):sub(1, 20) .. ': not known' end
    if not allow[goal] then
        return false, 'the Rules choice "Missions" is ' .. m .. ': ' .. goal .. ' is not allowed'
    end
    if s.send_missions ~= true then return false, 'the Rules switch "Send missions by the World screen" is off' end
    return true
end

local function switch_on(goal)
    return goal_allowed(goal or 'make_contact', settings())
end

local function player_busy()
    local ok, why = pcall(function() return reqscript('ai-camera').player_busy() end)
    if not ok then return 'the game\'s screen could not be read' end
    return why
end

local function sorted_buttons()
    local o = {}
    for k in pairs(buttons()) do table.insert(o, k) end
    table.sort(o)
    return o
end

local function opt_id(v)
    if v == nil then return true, nil end
    local n = math.tointeger(tonumber(v))
    if not n or n < 0 then return false end
    return true, n
end

-- Begin a run: a = {site_id, goal = 'make_contact', squad_ids, hf_id,
-- artifact_id, dry_run}. Returns at once; the steps run over the next
-- frames and their outcome shows in status() (the `missions` report's `send`).
function start(a)
    a = a or {}
    local goal = a.goal
    if goal == nil then goal = 'make_contact' end
    local G = type(goal) == 'string' and GOALS[goal] or nil
    if not G then
        return {ok = false, rejected = true, error = 'unknown goal ' .. tostring(goal):sub(1, 30) .. ': one of ' ..
                table.concat(GOAL_ORDER, ', ')}
    end
    local gi, gwhy = df_goal(goal)
    if not gi then return {ok = false, rejected = true, error = gwhy} end
    local site_id = math.tointeger(tonumber(a.site_id))
    if not site_id or site_id < 0 then return {ok = false, rejected = true, error = 'site_id is a site\'s id'} end
    local squad_ids = {}
    if a.squad_ids ~= nil then
        if type(a.squad_ids) ~= 'table' then return {ok = false, rejected = true, error = 'squad_ids is a list of squad ids'} end
        for i = 1, MAX_SQUADS + 1 do
            local v = a.squad_ids[i]
            if v == nil then break end
            if i > MAX_SQUADS then return {ok = false, rejected = true, error = 'at most ' .. MAX_SQUADS .. ' squads'} end
            local okv, n = opt_id(v)
            if not okv or n == nil then return {ok = false, rejected = true, error = 'squad_ids is a list of squad ids'} end
            table.insert(squad_ids, n)
        end
    end
    if G.squads and #squad_ids == 0 then
        return {ok = false, rejected = true, error = goal .. ' needs squad_ids: the squads to send'}
    end
    local okh, hf_id = opt_id(a.hf_id)
    local oka, artifact_id = opt_id(a.artifact_id)
    if not okh or not oka then return {ok = false, rejected = true, error = 'hf_id / artifact_id are ids'} end
    if RUN then
        return {ok = false, waiting = true, error = 'a mission is being sent already (step ' .. tostring(RUN.step_name) .. ')'}
    end
    local on, off_why = switch_on(goal)
    if not on then return {ok = false, rejected = true, error = off_why} end
    local busy = player_busy()
    if busy then return {ok = false, waiting = true, error = 'the player is using the game: ' .. busy} end
    local mid
    if goal == 'make_contact' then
        local why
        mid, why = messenger_home()
        if not mid then return {ok = false, rejected = true, error = why} end
    end
    local site = df.world_site.find(site_id)
    if not site then return {ok = false, rejected = true, error = 'no site ' .. site_id} end
    local name
    pcall(function() name = dfhack.translation.translateName(site.name, true) end)
    if name then name = tostring(name):sub(1, 40) end
    if G.squads and df.squad then
        for _, sq in ipairs(squad_ids) do
            local okq, found = pcall(function() return df.squad.find(sq) end)
            if okq and not found then return {ok = false, rejected = true, error = 'no squad ' .. sq} end
        end
    end
    if not buttons().World then
        return {ok = false, rejected = true, needs_button = 'World',
                error = 'the AI doesn\'t know where the World button is yet: python brain\\probe_missions.py --here World'}
    end
    -- (0.105.39) the goal's button known before a run starts (Make contact,
    -- as before, starts and stops at its goal step)
    if goal ~= 'make_contact' and not buttons()[G.button] then
        return {ok = false, rejected = true, needs_button = G.button,
                error = 'the AI doesn\'t know where the ' .. G.button .. ' button is yet: with a site\'s New mission ' ..
                        'showing, python brain\\probe_missions.py --here ' .. G.button}
    end
    local steps = step_names(goal)
    local stops_at
    for _, st in ipairs(steps_for(goal)) do if not st.act then stops_at = st.name break end end
    if a.dry_run then
        return {ok = true, dry_run = true, goal = goal, df_goal = G.df, intent = G.intent, button = G.button,
                site_id = site_id, site = name, messenger = mid, squad_ids = squad_ids, hf_id = hf_id,
                artifact_id = artifact_id, steps = steps, recorded = RECORDED[goal], stops_at = stops_at,
                buttons = sorted_buttons()}
    end
    local run = {goal = goal, df_goal = gi, df_goal_name = G.df, intent = G.intent, button = G.button,
                 squad_ids = squad_ids, hf_id = hf_id, artifact_id = artifact_id,
                 site_id = site_id, site = name, messenger = mid, steps = steps_for(goal), step = 1, acted = false,
                 waited = 0, frames = 0, trail = {}, started = now_tick()}
    run.step_name = run.steps[1].name
    run.controllers_before = read_state(run).controllers
    RUN = run
    later(1, function() tick(run) end)
    return {ok = true, sending = true, goal = goal, site_id = site_id, site = name, steps = steps, stops_at = stops_at}
end

-- The run under way and the last one's outcome, for the report.
function status()
    local out = {}
    if RUN then out.running = {goal = RUN.goal, site_id = RUN.site_id, step = RUN.step_name, frames = RUN.frames} end
    local last = last_outcome()
    if last then
        out.last = {goal = last.goal or 'make_contact', site_id = last.site_id, site = last.site, result = last.result,
                    step = last.step, reason = last.reason, why = last.why, tick = last.tick, closed = last.closed,
                    controller_left = last.controller_left}
    end
    out.buttons = sorted_buttons()
    out.on = switch_on('make_contact') == true
    local known = buttons()
    out.goals = {}
    for g, G in pairs(GOALS) do
        out.goals[g] = {button = known[G.button] ~= nil, recorded = last_recorded(g)}
    end
    return out
end
