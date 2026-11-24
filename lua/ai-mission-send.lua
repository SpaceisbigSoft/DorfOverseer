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
-- (r9, audit A8 #25) That was 0.105.24; since 0.105.47 Make contact and the
-- site invasions run end to end to "mission set up" (result 'sent', below);
-- only rescue and recover_artifact still stop at the site.
--
-- It runs only when the Rules switch `send_messenger` is on (on by default from r10 p3),
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
-- army controller held (run.details), and closes the World screen. (0.105.39
-- review) Only Diplomacy's goal button was seen pressed: the other goals'
-- runs stop before pressing theirs (RECORDED = open, site). A run also stops
-- when the player takes the game back (another screen on top, the pause
-- changed), and each goal's last outcome is kept (status().last_by_goal).
--
-- (0.105.47) The rest recorded live (14 Nov, DF 53.17, the player's "Make
-- contact at Peacemine" and "Raid Crackeddreamed", probe_missions --watch):
--   NEW_MISSION: Diplomacy / Attack (all the site invasions) -> MISSION_DETAILS
--                with a new controller of goal DIPLOMACY / SITE_INVASION at
--                the site (selected_ac: an index into the screen's
--                army_controller vector, 0 then 1 then 2)
--   MISSION_DETAILS: Make contact already chosen (green) for Diplomacy and
--                Raid for Attack (both left as they were); the messenger's /
--                a squad's tick box at the top row of the left panel (the
--                controller's squads 0 -> 1 the moment it was ticked); the
--                side orders left as they were; "Done assigning" ->
--                MISSIONS_LIST, the controller kept, the squad's order
--                "Raid ..." (the confirm: Mission details has no other
--                button but Remove, checked 17:17)
--   a site DF can't reach (an island): New mission's Attack, Request workers
--                and Diplomacy all INACCESSIBLE (new_mission[goal]); the run
--                stops there with reason 'inaccessible' and the planner
--                drops the site
-- A run ends at "mission set up" (result 'sent'): MISSIONS_LIST, the
-- controller with its squads / messenger and (raids) the squads' raid
-- order. Setting out is DF's business and takes game time (live 14 Nov
-- 17:07: neither mission had an army 15 game-minutes later); the missions
-- report watches for the controller's army (ai-missions `departed`).
-- The buttons are found by their words read off the screen
-- (dfhack.screen.readTile, as lua/ai-screen-buttons.lua): "Attack",
-- "Diplomacy", "Done assigning"; a tick box from the recorded spot beside
-- "Done assigning" (24 tiles right, 37 rows up, 3 rows a row), pressed only
-- where its row reads the messenger's name / a squad's "No specific orders".
-- A word not found (or text that can't be read) stops the run: never a
-- blind click. Only Diplomacy may still fall back to its calibrated place
-- when the screen's text can't be read (as before).
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
                  Explore = 'centre', Raid = 'centre', Pillage = 'centre', Tribute = 'centre', Conquer = 'centre',
                  Attack = 'centre'}   -- (0.105.47) the site invasions' one button on New mission

-- (0.105.39) the goals: DF's mission goal (army_controller_goal_type, the
-- index of the screen's new_mission), the button on New mission, the intent
-- (invasion_intent_type) chosen later on Mission details for the site
-- invasions, and what the player picks there (a prisoner, an artifact)
-- (0.105.47) `words`: the goal button's label on New mission, read off the
-- screen (recorded: Diplomacy, Attack; Explore is tried before Attack for a
-- ruin, unrecorded); `intent_word`: the intent's row on Mission details
-- (only Raid, DF's default, was recorded: the others are pressed only
-- where their row is read, and checked on the controller after);
-- `default_intent`: left as DF chose it (recorded)
GOALS = {
    make_contact     = {df = 'DIPLOMACY', button = 'Diplomacy', words = {'Diplomacy'}},
    rescue           = {df = 'RESCUE_HF', button = 'Rescue', target = 'hf_id', squads = true},
    recover_artifact = {df = 'RECOVER_ARTIFACT', button = 'Recover', target = 'artifact_id', squads = true},
    explore          = {df = 'SITE_INVASION', intent = 'EXPLORE', button = 'Attack', squads = true,
                        words = {'Explore', 'Attack'}, intent_word = 'Explore'},
    raid             = {df = 'SITE_INVASION', intent = 'RAID', button = 'Attack', squads = true,
                        words = {'Attack'}, intent_word = 'Raid', default_intent = true},
    pillage          = {df = 'SITE_INVASION', intent = 'PILLAGE', button = 'Attack', squads = true,
                        words = {'Attack'}, intent_word = 'Pillage'},
    tribute          = {df = 'SITE_INVASION', intent = 'DEMAND_TRIBUTE', button = 'Attack', squads = true,
                        words = {'Attack'}, intent_word = 'Demand one-time tribute'},
    conquer          = {df = 'SITE_INVASION', intent = 'TAKE_OVER_SITE', button = 'Attack', squads = true,
                        words = {'Attack'}, intent_word = 'Conquer and occupy'},
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
-- (0.105.39 review) the Rules choice `missions`: which goals each allows is
-- read from lua/ai-overseer-settings.lua's MISSION_GOALS (one table for the
-- bridge, the sender and the GUI); settings that can't load: refused
MISSIONS_DEFAULT = 'all'      -- (r10 p3) the settings' default (a missing value only)
-- the switches as the Army tab names them (lua/gui/ai-overseer.lua)
MISSIONS_LABEL = 'the Army tab\'s "Missions to send out"'
SEND_MISSIONS_LABEL = 'the Army tab\'s "Send missions by the World screen"'
STALE_MS = 5 * 60 * 1000                     -- a run older than 5 minutes of wall clock (getTickCount): stuck
CLOSE_WAIT_MS = 30 * 1000                    -- waiting for the World screen to come back on top, at most
CLOSE_WAIT_POLLS = 300                       -- ... in polls, without a clock
MESSENGER_LABEL = 'the Rules tab\'s "Send the messenger by the World screen"'
MAX_SQUADS = 20

RUN = RUN or nil                             -- the run under way (one at a time)

-- ---------------------------------------------------------------------------
-- small helpers

local function now_tick() return U.now_tick(0) end            -- (r6) ai-util's: 0 when it can't be read

local function log_path()
    local ok, p = pcall(function() return dfhack.getDFPath() .. '/dfhack-config/ai-overseer/mission-send.json' end)
    return ok and p or 'mission-send.json'
end

local function enum_name(enum, v) return U.enum_name(enum, v) end   -- (r6) ai-util's (no enum: nil there too)

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

-- (0.105.39 review 2) the army controllers: the ids at the end of
-- world.army_controllers.all before the run (DF appends a new one), and the
-- ones that weren't there then
BEFORE_KEEP = 64

function controller_ids_now()
    local out = {n = 0, ids = {}}
    pcall(function()
        local all = df.global.world.army_controllers.all
        out.n = #all
        for i = math.max(0, out.n - BEFORE_KEEP), out.n - 1 do
            local id = id_of(all[i])
            if id then out.ids[id] = true end
        end
    end)
    return out
end

-- the controllers in world.army_controllers.all that weren't there when the
-- run began (newest last)
function new_controllers(run)
    local out = {}
    local before = run and run.ac_before
    if not before then return out end
    pcall(function()
        local all = df.global.world.army_controllers.all
        for i = math.max(0, before.n - BEFORE_KEEP), #all - 1 do
            local c = all[i]
            local id = id_of(c)
            if c ~= nil and id and not before.ids[id] then table.insert(out, c) end
        end
    end)
    return out
end

-- the controller selected_ac names read both ways: an index into the
-- screen's army_controller vector (df-structures: an int32 next to it), and
-- an army controller's id
local function selected_both(scr, sel)
    if scr == nil or type(sel) ~= 'number' or sel < 0 then return nil, nil end
    local oki, ci = pcall(function()
        local v = scr.army_controller
        if v ~= nil and sel < #v then return v[sel] end
    end)
    local okf, cf = pcall(function() return df.army_controller.find(sel) end)
    return (oki and ci) or nil, (okf and cf) or nil
end

-- (0.105.39 review 2) The run's new army controller: the one that appeared
-- in world.army_controllers.all since the run began, cross-checked with
-- selected_ac (as an index and as an id). Returns the controller and how it
-- was found: 'index' / 'id' (selected_ac agrees), 'new' (no selected_ac to
-- check), 'ambiguous' (they disagree: the new one is taken, the
-- disagreement logged); without a new one, selected_ac alone when both
-- readings agree or only one exists, else nil and 'ambiguous'.
function selected_controller(scr, sel, run)
    local ci, cf = selected_both(scr, sel)
    local fresh = new_controllers(run)
    local nc = #fresh == 1 and fresh[1] or nil
    if nc then
        local nid = id_of(nc)
        if ci and id_of(ci) == nid then return nc, 'index' end
        if cf and id_of(cf) == nid then return nc, 'id' end
        if not ci and not cf then return nc, 'new' end
        return nc, 'ambiguous'
    end
    if #fresh > 1 then
        -- more than one new: the one selected_ac names among them
        for _, c in ipairs(fresh) do
            if ci and id_of(ci) == id_of(c) then return c, 'index' end
            if cf and id_of(cf) == id_of(c) then return c, 'id' end
        end
        return nil, 'ambiguous'
    end
    if ci and cf and id_of(ci) ~= id_of(cf) then return nil, 'ambiguous' end
    if ci then return ci, 'index' end
    if cf then return cf, 'id' end
    return nil
end

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
    -- (0.105.39 review) the controller selected_ac names: df-structures has it
    -- an int32 beside the screen's army_controller vector (an index into it,
    -- most likely); an army controller's id is read too, so either works
    local c, how = selected_controller(scr, st.selected_ac, run)
    st.ac_by = how
    if c then
        st.ac_id = id_of(c)
        pcall(function() st.ac_goal = c.goal end)
        st.ac_goal_name = enum_name(df.army_controller_goal_type, st.ac_goal)
        controller_facts(c, st)
    end
    return st
end

-- (0.105.47) what the run's controller holds that the later steps are
-- checked against: its site, its squads (recorded: 0 -> 1 as a squad was
-- ticked), its messengers (assigned_epp_epp_id), the Diplomacy topics and
-- the invasion's intent. A field that can't be read stays nil (unknown).
local function int_list(v)
    local out
    pcall(function()
        local n = #v
        out = {}
        for i = 0, n - 1 do
            local x = v[i]
            if type(x) == 'number' then table.insert(out, math.tointeger(x) or x) end
        end
    end)
    return out
end

function controller_facts(c, st)
    pcall(function() st.ac_site = math.tointeger(c.site_id) or c.site_id end)
    local okq, sq = pcall(function() return c.assigned_squads end)
    if okq and sq ~= nil then st.ac_squads = int_list(sq) end
    local oke, epp = pcall(function() return c.assigned_epp_epp_id end)
    if oke and epp ~= nil then st.ac_epp = int_list(epp) end
    -- `data` is a union of pointers: each read only for its own goal
    local gname = enum_name(df.army_controller_goal_type, st.ac_goal)
    if gname == 'DIPLOMACY' then pcall(function()
        local d = c.data.goal_diplomacy
        if d == nil then return end
        local t = d.topic
        local names = {}
        for i = 0, #t - 1 do
            local v = t[i]
            if v ~= nil then table.insert(names, enum_name(df.meeting_topic, v) or tostring(v)) end
        end
        st.topics = names
    end) end
    if gname == 'SITE_INVASION' then pcall(function()
        local inv = c.data.goal_site_invasion
        if inv == nil then return end
        local v = inv.invasion_intent
        st.intent = enum_name(df.invasion_intent_type, v) or (v ~= nil and tostring(v) or nil)
    end) end
end

-- the few fields, as words, for the log and the report
local function seen(st)
    return {focus = st.focus, world = st.world, mode = st.mode, focus_site = st.focus_site,
            diplomacy = st.diplomacy, goal_ok = st.goal_ok, selected_ac = st.selected_ac,
            ac_id = st.ac_id, ac_by = st.ac_by, ac_goal = st.ac_goal_name, controllers = st.controllers,
            -- (0.105.47) the controller's site, squads, messengers, topics, intent
            ac_site = st.ac_site, ac_squads = st.ac_squads and #st.ac_squads or nil,
            ac_epp = st.ac_epp and #st.ac_epp or nil, topics = st.topics, intent = st.intent}
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
        local ac = selected_controller(scr, id, RUN)
        if ac then
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

-- (0.105.48, K9) the save's, else this PC's (shown in any save here:
-- lua/ai-screen-buttons.lua, as the trade and meeting buttons since 0.105.47),
-- so a new fort finds the World button the player showed in another
-- A place shown in this save before 0.105.48 (kept in the save only) is
-- copied to the PC's file once a session, so the next new fort has it too.
SHARED_FROM_SAVE = SHARED_FROM_SAVE or {}
function buttons()
    pcall(function()
        local site, new = U.site_get(BUTTONS_KEY, {}), {}
        for name, place in pairs(site) do
            if type(place) == 'table' and not SHARED_FROM_SAVE[name] then
                SHARED_FROM_SAVE[name] = true
                new[name] = place
            end
        end
        if next(new) == nil then return end
        local B = reqscript('ai-screen-buttons')
        local pc = B.read_file().buttons[BUTTONS_KEY] or {}
        for name, place in pairs(new) do
            if pc[name] == nil then B.share(BUTTONS_KEY, name, place) end
        end
    end)
    local ok, d = pcall(function() return reqscript('ai-screen-buttons').get(BUTTONS_KEY) end)
    if ok and type(d) == 'table' then return d end
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
    local d = U.site_get(BUTTONS_KEY, {})   -- (0.105.48) the save's own, not the merged ones
    d[name] = {anchor = anchor, dx = x - gps.dimx // 2, dy = y - gps.dimy // 2, lx = x, by = gps.dimy - y,
               x = x, y = y, w = gps.dimx, h = gps.dimy}
    dfhack.persistent.saveSiteData(BUTTONS_KEY, d)
    -- (0.105.48, K9) and for every save on this PC
    pcall(function() reqscript('ai-screen-buttons').share(BUTTONS_KEY, name, d[name]) end)
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

-- (r12) DF's World screen opened by its own interface key (D_WORLD) when the
-- World button's place was never shown in this save or on this PC (every new
-- fort: live 22 Nov, all six refused "can't find DF's World button"). Tried
-- once a DF session: a run whose World screen didn't open that way marks it
-- failed (WORLD_KEY_FAILED) and the old ask (show the button once) returns.
WORLD_KEY_FAILED = WORLD_KEY_FAILED or false
function world_by_key()
    if WORLD_KEY_FAILED then return false end
    local ok, k = pcall(function() return df.interface_key.D_WORLD end)
    return ok and k ~= nil
end

local function press(name)
    local b = buttons()[name]
    if not b and name == 'World' and world_by_key() then
        local ok, err = pcall(function()
            require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'D_WORLD')
        end)
        if not ok then
            WORLD_KEY_FAILED = true
            return false, 'needs_button', 'DF\'s World key failed (' .. tostring(err):sub(1, 80) ..
                ') and the AI doesn\'t know where the World button is: python brain\\probe_missions.py --here World'
        end
        WORLD_VIA_KEY = true
        return true
    end
    if not b then
        return false, 'needs_button', 'the AI doesn\'t know where the ' .. name ..
            ' button is yet: python brain\\probe_missions.py --here ' .. name
    end
    local x, y = button_at(b)
    local ok, err = pcall(click, x, y)
    if not ok then return false, 'click_failed', 'the click failed: ' .. tostring(err):sub(1, 160) end
    return true
end

-- (r9) this file's locals the later parts use (each takes back the ones it
-- uses as locals of its own): all functions and fixed values, set once here
PART_LOCALS = {U = U, now_tick = now_tick, log_path = log_path, focus_string = focus_string, id_of = id_of, seen = seen, click = click, press = press}

---------------------------------------------------------------------------
-- (r9) The rest of the sender lives in parts beside this file
-- (ai-mission-send-<part>.lua): steps (the screen's words read and pressed,
-- the steps of each goal's mission: STEP_DEFS, RECIPES, RECORDED) and run
-- (the log and the outcomes kept, the run's state machine and its stops,
-- the Rules, start(), leave_world(), status()). Each runs in this module's
-- own environment, so its names stay reqscript('ai-mission-send').name for
-- the bridge and the other modules, and a test's swap (M.start = ...)
-- reaches every part. They load in this order. DFHack reloads a module when
-- its own file changes: a change to a part alone is picked up once
-- ai-mission-send.lua is touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'steps', 'run'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-mission-send'] = '0.105.104'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-mission-send-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-mission-send: ' .. name .. '.lua is missing (it goes beside ai-mission-send.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
