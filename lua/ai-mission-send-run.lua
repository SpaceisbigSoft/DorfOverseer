-- ai-mission-send-run: the log and each goal's last outcome kept, the run's
-- state machine (tick, its stops for the player, the World screen shut),
-- the Rules, start(), leave_world() and status().
--
-- (r9) A part of ai-mission-send, not a script of its own: ai-mission-send.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-mission-send').name and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-mission-send-run is a part of ai-mission-send; run ai-mission-send') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-mission-send-run'] = '0.105.134'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, now_tick, log_path, focus_string, id_of, seen, click, first_name, contains = PART_LOCALS.U, PART_LOCALS.now_tick, PART_LOCALS.log_path, PART_LOCALS.focus_string, PART_LOCALS.id_of, PART_LOCALS.seen, PART_LOCALS.click, PART_LOCALS.first_name, PART_LOCALS.contains   -- (r9) the hub's and earlier parts' locals

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
                            left_ids = run.left_ids, left_open = run.left_open, goal_mismatch = run.goal_mismatch,
                            probe = run.probe,
                            -- (0.105.47) what was left as DF chose, the boxes ticked, the facts read
                            left = run.left, ticked = run.ticked, topics = run.topics, sent_ac = run.sent_ac,
                            unticked = run.unticked, untick_failed = run.untick_failed,     -- (r9)
                            intent_before = run.intent_before, intent_mismatch = run.intent_mismatch,
                            messenger_unverified = run.messenger_unverified,
                            messenger_flag_before = run.messenger_flag_before,
                            order_unverified = run.order_unverified,
                            screen = run.screen, pressed = run.pressed,      -- (0.105.74)
                            -- (R29) each step's result, DF's help window, the World screen's close
                            results = run.results, popup = run.popup, popup_closed = run.popup_closed,
                            site_clicks = run.site_clicks, dismissed = run.dismissed, close_presses = run.close_presses})
        while #runs > LOG_KEEP do table.remove(runs, 1) end
        pcall(function() dfhack.filesystem.mkdir_recursive(dfhack.getDFPath() .. '/dfhack-config/ai-overseer') end)
        json.encode_file({runs = runs}, log_path())
    end)
end

-- (0.105.39 review) the last outcome of EACH goal (`by_goal`, kept in the
-- same site data as the last one), so a run of one goal never hides
-- another's stopped run (the year-long retry block is per goal)
local function small(o)
    return {goal = o.goal or 'make_contact', site_id = o.site_id, site = o.site, result = o.result, step = o.step,
            reason = o.reason, why = o.why, tick = o.tick, closed = o.closed, controller_left = o.controller_left,
            hf_id = o.hf_id, artifact_id = o.artifact_id, left_ids = o.left_ids, left_open = o.left_open,
            goal_mismatch = o.goal_mismatch,
            -- (0.105.47) the mission's own controller once sent; what couldn't be checked
            sent_ac = o.sent_ac, intent_mismatch = o.intent_mismatch, messenger_unverified = o.messenger_unverified,
            order_unverified = o.order_unverified,
            -- (R29) each step's result ({step, result, frame, why}), DF's help window, the close
            results = o.results, popup = o.popup, popup_closed = o.popup_closed, dismissed = o.dismissed}
end

-- the per-goal outcomes of a saved record; an old save (no by_goal) has its
-- one outcome under its goal (make_contact when it has none)
local function by_goal_of(d)
    if type(d) ~= 'table' then return {} end
    if type(d.by_goal) == 'table' then return d.by_goal end
    if d.result == nil then return {} end
    local g = type(d.goal) == 'string' and GOALS[d.goal] and d.goal or 'make_contact'
    return {[g] = small(d)}
end

-- which save and site this is: the module's copy of the last outcome is
-- only good for the one it was written in
-- (r1g9) the world and the site (ai-util fort_id), not the save folder DF's
-- seasonal autosave renames (the outcome was dropped every season)
function save_tag()
    local ok, v = pcall(function() return U.fort_id() end)
    if ok and type(v) == 'string' then return v end
    local dir, site
    pcall(function() dir = df.global.world.cur_savegame.save_dir end)
    pcall(function() site = df.global.plotinfo.site_id end)
    return tostring(dir) .. '/' .. tostring(site)
end

local function save_outcome(run)
    local out = {goal = run.goal, site_id = run.site_id, site = run.site, result = run.result, step = run.stopped_at,
                 reason = run.reason, why = run.why, tick = now_tick(), closed = run.closed,
                 controller_left = run.controller_left, saw = run.saw, hf_id = run.hf_id,
                 artifact_id = run.artifact_id, left_ids = run.left_ids, left_open = run.left_open,
                 goal_mismatch = run.goal_mismatch, sent_ac = run.sent_ac, intent_mismatch = run.intent_mismatch,
                 messenger_unverified = run.messenger_unverified, order_unverified = run.order_unverified,
                 untick_failed = run.untick_failed,      -- (r9) squads a stopped run couldn't take off
                 results = run.results, popup = run.popup, popup_closed = run.popup_closed,   -- (R29)
                 dismissed = run.dismissed}
    local okp, old = pcall(function() return last_outcome() end)
    local by = by_goal_of(okp and old or nil)
    by[run.goal or 'make_contact'] = small(out)
    out.by_goal = by
    LAST, LAST_TAG = out, save_tag()
    local ok, put, err = pcall(U.site_put, SEND_KEY, out)
    if not ok or put == false then out.save_error = tostring(ok and err or put):sub(1, 120) end
    return out
end

function last_outcome()
    -- (0.105.39 review 2) the module's copy only for the save and site it came
    -- from: another fort loaded since reads its own site data
    if LAST and LAST_TAG ~= save_tag() then LAST, LAST_TAG = nil, nil end
    if LAST then return LAST end
    local ok, d = pcall(function() return U.site_get(SEND_KEY, nil) end)
    return ok and type(d) == 'table' and d or nil
end

-- {goal = its last outcome (small)}
function last_by_goal()
    return by_goal_of(last_outcome())
end

-- ---------------------------------------------------------------------------
-- the run

local finish     -- (below) the run's end once the screen is shut

local function later(n, fn)
    dfhack.timeout(n, 'frames', function()
        local ok, err = pcall(fn)
        if not ok and RUN then
            if RUN.stopping then
                -- (0.105.39 review) an error while closing: the run ends anyway
                local run = RUN
                run.why = (run.why and run.why .. '; ' or '') .. 'closing: ' .. tostring(err):sub(1, 120)
                pcall(finish, run, world_screen() == nil)
                if RUN == run then RUN = nil end
            else
                -- an error inside a step: stopped like any other surprise
                RUN.why = 'error: ' .. tostring(err):sub(1, 200)
                local run = RUN
                local oks = pcall(function() stop(run, 'error') end)
                if not oks and RUN == run then RUN = nil end
            end
        end
    end)
end

-- each step's look at the screen; a step's screen once it was right also in
-- full (probe_missions' dump), so the run records what each screen held
-- (R29) each step's result in a line of its own (run.results: {step, result,
-- frame[, why]}), kept with the outcome, so the journal says how far each
-- live run got and where it stopped
local function step_result(run, result, why)
    run.results = run.results or {}
    if #run.results >= 12 then return end
    table.insert(run.results, {step = run.step_name, result = result, frame = run.frames,
                             why = why and tostring(why):sub(1, 100) or nil,
                             tries = run.read_tries, clicks = run.step_name == 'site' and run.site_clicks or nil})
end

local function trail(run, what, st)
    if #run.trail < 24 then
        table.insert(run.trail, {step = run.step_name, what = what, frame = run.frames,
                                 saw = st and seen(st) or nil, probe = what == 'ok' and probe() or nil})
    end
end

-- the World screen is the top screen (the one a key press goes to)
function world_on_top()
    if not world_screen() then return false end
    return focus_string():match('^world') ~= nil
end

local function ms_now()
    local ok, t = pcall(function() return dfhack.getTickCount() end)
    if ok and type(t) == 'number' then return t end
    return nil
end

-- close the World screen (LEAVESCREEN, as Esc), checked a few frames later;
-- only ever that screen: if it isn't open, nothing is pressed. (0.105.39
-- review) A key is pressed only while the World screen is the top screen:
-- with the player's window over it, it waits (CLOSE_WAIT_MS) for the World
-- screen to come back on top; if it never does it is left open under the
-- player's window (run.left_open) and Needs you says so. The native screen
-- is never dismissed by hand.
-- (R29, live 25 Nov: D's and F's runs ended "closed": false, the World
-- screen left up with DF's help window or a site in focus; Esc pressed four
-- times two frames apart) DF's help window over it shut first; after each
-- Esc the screen is given CLOSE_SETTLE_FRAMES to go (a screen DF is
-- already taking down counts as going: no second Esc lands on the fort's
-- view, where Esc opens the main menu); after CLOSE_TRIES, DFHack's own
-- dismiss of the World screen (run.dismissed), so the game is never left
-- on it.
CLOSE_SETTLE_FRAMES = 12

local function world_going(scr)
    local ok, b = pcall(function() return scr.breakdown_level end)
    return ok and type(b) == 'number' and b ~= 0
end

local function dismiss_world(run, done)
    local scr = world_screen()
    if not scr then return done(true) end
    local ok = pcall(function() dfhack.screen.dismiss(scr) end)
    if run then run.dismissed = ok or nil end
    if not ok then return done(false) end
    later(POLL_FRAMES * 2, function()
        local w = world_screen()
        done(w == nil or world_going(w))
    end)
end

function close_world(run, tries, done, waited, settle)
    tries = tries or 0
    local scr = world_screen()
    if not scr then return done(true) end
    if world_going(scr) then return done(true) end      -- DF takes it down this frame
    if settle and settle > 0 and world_on_top() then
        -- the last Esc's frames: DF given time to take the screen down
        return later(POLL_FRAMES, function() close_world(run, tries, done, nil, settle - POLL_FRAMES) end)
    end
    if tries >= CLOSE_TRIES then
        if world_on_top() then return dismiss_world(run, done) end
        return done(false)
    end
    if world_on_top() then
        pcall(world_popup_close)
        pcall(function() require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN') end)
        if run then run.close_presses = (run.close_presses or 0) + 1 end
        if not world_screen() then return done(true) end
        return later(POLL_FRAMES, function() close_world(run, tries + 1, done, nil, CLOSE_SETTLE_FRAMES) end)
    end
    waited = waited or {polls = 0, since = ms_now()}
    waited.polls = waited.polls + 1
    local t = ms_now()
    local over = (t and waited.since) and (t - waited.since > CLOSE_WAIT_MS) or waited.polls > CLOSE_WAIT_POLLS
    if over then
        if run then run.left_open = true end
        return done(false)
    end
    later(POLL_FRAMES, function() close_world(run, tries, done, waited) end)
end

-- Stop the run: what it saw written down, the World screen shut, the
-- outcome kept for the report. result: 'stopped' (a surprise or a step
-- never recorded), 'error', 'sent' (all steps done: (0.105.47) Make contact
-- and the site invasions, recorded end to end).
-- (0.105.39 review) Every part inside pcall and RUN always cleared: an
-- error while stopping (or in the callback once the screen shut) never
-- leaves a run stuck that start() would wait on for ever.
finish = function(run, closed)
    pcall(function()
        run.closed = closed
        local after = read_state(run)
        run.controllers = {before = run.controllers_before, after = after.controllers}
        -- a new army controller left behind once the screen shut (DF's own
        -- planned mission, or one nobody leads): written down for the player.
        -- (R29) only the fort's own (new_controllers, below): the count of all
        -- the world's controllers grows with other entities' armies too
        -- (0.105.39 review) which ones: their ids, so the brain doesn't take a
        -- leftover for a mission out
        local ids = new_controllers(run)
        -- (0.105.47) a mission sent: its own controller is the mission out,
        -- not one left behind (run.sent_ac); only others are written down
        if run.result == 'sent' and run.ac_id then
            run.sent_ac = run.ac_id
            local others = {}
            for _, c in ipairs(ids) do if id_of(c) ~= run.ac_id then table.insert(others, c) end end
            ids = others
            run.controller_left = nil
        end
        if #ids > 0 then
            run.controller_left = true
            run.left_ids = {}
            for i = 1, math.min(#ids, 4) do run.left_ids[i] = id_of(ids[i]) end
        end
    end)
    -- (r9, audit A8 #15) the fort attacked them only when the mission went:
    -- a run that stopped at a step books nobody (their peace stays open)
    if run.result == 'sent' and run.attacks and #run.attacks > 0 then
        pcall(function()
            local D = reqscript('ai-diplomacy')
            local done = {}
            for _, id in ipairs(run.attacks) do
                if not done[id] then done[id] = true; D.note_attacked(id) end
            end
        end)
    end
    pcall(save_log, run)
    if not run.key_failed then pcall(save_outcome, run) end   -- (r12 v5) a failed World key books no outcome
    if RUN == run then RUN = nil end
end

function stop(run, result, reason)
    if run.stopping then return end
    run.stopping = true
    run.result = result
    run.reason = reason or run.reason
    run.stopped_at = run.step_name
    if result ~= 'sent' then pcall(step_result, run, 'stop: ' .. tostring(reason or run.reason), run.why) end
    -- (r12) the World screen didn't open by DF's key: not tried again this DF
    -- session (the ask to show the button returns)
    -- (r12 v5) only the AI's own surprise (the open step timed out, or the key
    -- changed the screen): a halt or the player taking over doesn't mark it.
    -- The run's outcome isn't booked (finish): the planner sees World unknown
    -- and asks for the button once, with no year's block on Make contact.
    if run.world_via_key and run.step_name == 'open' and result ~= 'sent' and reason == 'unexpected' then
        local okw, open = pcall(world_screen)
        if not (okw and open) then
            WORLD_KEY_FAILED = true
            run.key_failed = true
            run.why = (run.why and run.why .. '; ' or '') .. 'DF\'s World key (D_WORLD) did not open the World screen'
            -- another panel the key opened instead: shut once (the run began on dwarfmode/Default)
            pcall(function()
                local f = dfhack.gui.getCurFocus(true)
                f = type(f) == 'table' and f[1] or f
                if f and not tostring(f):find('^dwarfmode/Default') and not tostring(f):find('^world') then
                    require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
                    run.why = run.why .. ' (' .. tostring(f) .. ' shut)'
                end
            end)
        end
    end
    -- (r12) DF didn't take the click on the site (live 22 Nov): 'click_missed',
    -- tried again the next day, up to 3 times a DF session; then a surprise
    if run.step_name == 'site' and run.reason == 'unexpected' and tostring(run.why or ''):find('still on world/NORMAL', 1, true) then
        SITE_MISSES = (SITE_MISSES or 0) + 1
        if SITE_MISSES <= 3 then run.reason = 'click_missed' end
        run.why = run.why .. ' (miss ' .. SITE_MISSES .. ' this DF session)'
    end
    -- (0.105.74) the goal's word not read on New mission (live 22 Nov, A and
    -- E): 'goal_unread', tried again the next day (the screen kept in the
    -- log each time), up to 3 times a DF session; then a step nobody recorded
    -- (verifier) a capitals press DF didn't take counts the same; the misses
    -- are this DF session's, every goal and site together (as SITE_MISSES)
    if run.step_name == 'goal' and ((run.reason == 'not_found' and run.goal_unread)
            or (run.reason == 'unexpected' and run.goal_ci
                and tostring(run.why or ''):find('still on world/NEW_MISSION', 1, true))) then
        GOAL_MISSES = (GOAL_MISSES or 0) + 1
        if GOAL_MISSES <= 3 then run.reason = 'goal_unread' end
        run.why = run.why .. ' (unread ' .. GOAL_MISSES .. ' this DF session)'
    end
    local ok, err = pcall(function()
        local st = read_state(run)
        run.saw = seen(st)
        run.probe = probe()
        -- (0.105.39) on Mission details: all it holds, for the steps to come
        if st.mode == 'MISSION_DETAILS' then run.details = details(st) end
        trail(run, 'stop', st)
    end)
    if not ok then run.why = (run.why and run.why .. '; ' or '') .. 'while stopping: ' .. tostring(err):sub(1, 120) end
    local called = false
    local function shut()
        local okc, cerr = pcall(close_world, run, 0, function(closed)
            if called then return end
            called = true
            finish(run, closed)
        end)
        if not okc and not called then
            run.why = (run.why and run.why .. '; ' or '') .. 'closing: ' .. tostring(cerr):sub(1, 120)
            called = true
            finish(run, world_screen() == nil)
        end
    end
    -- (r9, audit A8 #13) a run that stops after ticking squads (a later check
    -- failed): the controller stays after Mission details is left, so the
    -- squads ticked would go out as a smaller party than the matchup counted.
    -- Each box is a toggle: the run's own ticks still on the controller are
    -- pressed again (only on Mission details, its own controller, never for
    -- 'sent', when the player took over or the AI was halted), then read back a few frames later
    -- (run.unticked, or run.untick_failed with what is still there).
    local again = {}
    if result ~= 'sent' and reason ~= 'player_busy' and reason ~= 'halted' and run.ticked_ids and #run.ticked_ids > 0 then
        pcall(function()
            local st = read_state(run)
            if st.mode ~= 'MISSION_DETAILS' or (run.ac_id and st.ac_id ~= run.ac_id) or st.ac_squads == nil then return end
            for i, sid in ipairs(run.ticked_ids) do
                local p = run.ticked[i]
                if p and contains(st.ac_squads, sid) then
                    local okk = pcall(click, p[1], p[2])
                    if okk then table.insert(again, sid) end
                end
            end
        end)
    end
    if #again == 0 then return shut() end
    later(POLL_FRAMES, function()
        pcall(function()
            local st = read_state(run)
            local still = {}
            for _, sid in ipairs(again) do
                if st.ac_squads == nil or contains(st.ac_squads, sid) then table.insert(still, sid) end
            end
            if #still == 0 then run.unticked = again
            else
                run.untick_failed = still
                run.why = (run.why and run.why .. '; ' or '') .. 'squad(s) ' .. table.concat(still, ', ') ..
                          ' still on the mission after unticking'
            end
        end)
        shut()
    end)
end

local function pause_state()
    local ok, p = pcall(function() return df.global.pause_state end)
    if ok and type(p) == 'boolean' then return p end
    return nil
end

-- Why the run must stop for the player, or nil: before the World screen
-- opened the screen must be the one the run began on; once it opened, the
-- World screen must be on top; the pause state must be as it was (DF's own
-- change as the World screen opens is taken at the open step)
function player_took_over(run, st)
    local f = st.focus or ''
    if run.world_seen then
        if not st.world then
            return 'the World screen was closed by someone else'
        end
        if not f:match('^world') then return 'another screen (' .. f:sub(1, 40) .. ') is over the World screen' end
    elseif st.world then
        if not f:match('^world') then return 'another screen (' .. f:sub(1, 40) .. ') is over the World screen' end
    elseif run.focus0 and f ~= run.focus0 then
        return 'the screen changed (' .. f:sub(1, 40) .. ', not ' .. run.focus0:sub(1, 40) .. ')'
    end
    -- (0.105.39 review 2) the pause only before the World button is pressed:
    -- once the World screen is up, DF may pause it itself; the top-screen
    -- check above catches the player's own windows
    if not st.world and not run.world_seen and not run.pressed_world then
        local p = pause_state()
        if run.pause0 ~= nil and p ~= nil and p ~= run.pause0 then
            return 'the game was ' .. (p and 'paused' or 'unpaused') .. ' during the run'
        end
    end
    return nil
end

-- one look at the screen: the current step's check, then the next step
local function tick(run)
    if RUN ~= run or run.stopping then return end
    -- (0.105.48, K3) the AI halted mid-run: no further click, the screen shut
    local okh, halted = pcall(function() return reqscript('ai-status').is_halted() end)
    if okh and halted == true then
        run.why = 'the AI was halted in the game'
        return stop(run, 'stopped', 'halted')
    end
    run.frames = run.frames + POLL_FRAMES
    if run.frames > RUN_FRAMES then
        run.why = 'the run took longer than ' .. RUN_FRAMES .. ' frames'
        return stop(run, 'stopped', 'timeout')
    end
    local step = run.steps[run.step]
    -- (R29) DF's help window over the World screen (POPUP_WORLD): closed
    if world_screen() then
        local closed = world_popup_close()
        if closed then run.popup_closed = closed end
    end
    local st = read_state(run)
    -- (0.105.39 review) the player took the game back mid-run: another
    -- screen on top, or the game paused / unpaused by hand: stopped at once
    local busy = player_took_over(run, st)
    if busy then
        run.why = busy
        -- the tick right after the AI's own click: the click did it (unexpected)
        if run.acted and run.waited == 0 then return stop(run, 'stopped', 'unexpected') end
        -- (r12 v6) or the tick right after the site's delayed click (hover_click)
        if run.clicked_waited ~= nil and run.waited <= run.clicked_waited + POLL_FRAMES then
            return stop(run, 'stopped', 'unexpected')
        end
        return stop(run, 'stopped', 'player_busy')
    end
    if run.acted then
        local verdict, why, reason = step.check(st, run)
        if verdict == 'wait' then
            run.waited = run.waited + POLL_FRAMES
            local limit = step.wait or WAIT_FRAMES               -- (R29) the site's own, longer
            if run.waited <= limit then return later(POLL_FRAMES, function() tick(run) end) end
            run.why = why .. ' (' .. limit .. ' frames)'
            return stop(run, 'stopped', 'unexpected')
        elseif verdict ~= 'ok' then
            run.why = why
            -- (0.105.47) a check may name its reason (inaccessible, ...)
            return stop(run, 'stopped', reason or 'unexpected')
        end
        trail(run, 'ok', st)
        step_result(run, 'ok')
        if st.world then run.world_seen = true end
        run.step, run.acted, run.waited = run.step + 1, false, 0
        run.read_waited, run.read_tries = 0, nil
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
    if (run.read_waited or 0) == 0 then trail(run, 'act', st) end
    if step.name == 'open' then run.pressed_world = true end
    local ok, reason, err = step.act(run)
    if not ok then
        -- (R29) the words not on the screen yet: DF draws a new panel a few
        -- frames after its mode changes; read again for READ_WAIT_FRAMES
        if step.read_retry and READ_RETRY[reason] and (run.read_waited or 0) < READ_WAIT_FRAMES then
            run.read_waited = (run.read_waited or 0) + POLL_FRAMES
            run.read_tries = (run.read_tries or 1) + 1
            return later(POLL_FRAMES, function() tick(run) end)
        end
        run.why = err or reason
        if run.read_tries then run.why = run.why .. ' (read ' .. run.read_tries .. ' times over ' ..
                                         (run.read_waited or 0) .. ' frames)' end
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
        -- (r10 p2) the post by its duty (DELIVER_MESSAGES) too, and why there is none
        if not pos_id then
            pcall(function()
                local p = reqscript('ai-nobles').position_by_code(ent, 'MESSENGER')
                pos_id = p and p.id or nil
            end)
        end
        if not pos_id then
            local okw, st = pcall(function() return reqscript('ai-nobles').messenger_status(nil, ent) end)
            local why = okw and type(st) == 'table' and st.why
            return nil, 'the fort has no messenger\'s post' .. (why and (': ' .. tostring(why)) or '')
        end
        -- (r14 m1) every holder of the post looked at: one at home is sent; "away"
        -- only when none is; one who left the fort (no unit, on no mission of
        -- the fort's: ai-nobles-swap stale_holder) is never "away"
        local S
        pcall(function() S = reqscript('ai-nobles-swap') end)
        local away, gone
        for _, a in ipairs(ent.positions.assignments) do
            if a.position_id == pos_id and a.histfig ~= -1 then
                local hf = df.historical_figure.find(a.histfig)
                local okS, st = pcall(function() return S and hf and S.stale_holder(hf, ent, nil, true) end)
                if okS and type(st) == 'table' then
                    gone = gone or S.stale_why('MESSENGER', st)
                else
                    local u = hf and df.unit.find(hf.unit_id)
                    if not u then
                        away = away or 'the messenger is away'
                    elseif u.flags1.inactive or u.flags2.killed then
                        away = away or 'the messenger is away or dead'
                    else
                        -- (0.105.47) the figure too: their row on Mission details
                        MESSENGER_HF, MESSENGER_NAME = a.histfig, first_name(hf)
                        return u.id
                    end
                end
            end
        end
        if away then return nil, away end
        if gone then return nil, gone end
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

-- (0.105.39 review) the goals each `missions` level allows, from
-- ai-overseer-settings' MISSION_GOALS (the one table): {level = {goal = true}},
-- or nil when the settings module can't load (then every goal is refused)
function mission_goals()
    local ok, t = pcall(function() return reqscript('ai-overseer-settings').MISSION_GOALS end)
    if not ok or type(t) ~= 'table' then return nil end
    local out = {}
    for level, list in pairs(t) do
        if type(level) == 'string' and type(list) == 'table' then
            local set = {}
            for _, g in ipairs(list) do if type(g) == 'string' then set[g] = true end end
            out[level] = set
        end
    end
    return out
end

-- (0.105.39) the Rules for a goal: make_contact needs make_contact (on by
-- default) and send_messenger; the others the `missions` choice allowing the
-- goal and send_missions. Returns true, or false and why.
function goal_allowed(goal, s, levels)
    if type(s) ~= 'table' then return false, 'the Rules could not be read' end
    if goal == 'make_contact' then
        if s.make_contact == false then return false, 'the Rules switch "Make contact" is off' end
        if s.send_messenger ~= true then
            return false, MESSENGER_LABEL .. ' is off'
        end
        return true
    end
    if not GOALS[goal] then return false, 'unknown goal ' .. tostring(goal) end
    if type(levels) ~= 'table' then return false, 'the Rules\' mission goals (ai-overseer-settings) could not be read' end
    local m = s.missions
    if m == nil then m = MISSIONS_DEFAULT end
    local allow = levels[m]
    if not allow then return false, MISSIONS_LABEL .. ' is ' .. tostring(m):sub(1, 20) .. ': not known' end
    if not allow[goal] then
        return false, MISSIONS_LABEL .. ' is ' .. m .. ': ' .. goal .. ' is not allowed'
    end
    if s.send_missions ~= true then return false, SEND_MISSIONS_LABEL .. ' is off' end
    return true
end

local function switch_on(goal)
    goal = goal or 'make_contact'
    return goal_allowed(goal, settings(), goal ~= 'make_contact' and mission_goals() or nil)
end

local function player_busy()
    local ok, why = pcall(function() return reqscript('ai-camera').player_busy() end)
    if not ok then return 'the game\'s screen could not be read' end
    return why
end

local function sorted_buttons()
    local o = {}
    local b = buttons()
    for k in pairs(b) do table.insert(o, k) end
    if not b.World and world_by_key() then table.insert(o, 'World') end   -- (r12) by DF's key
    table.sort(o)
    return o
end

-- a run older than 2 x RUN_FRAMES by its own frame count, or older than
-- STALE_MS (5 minutes) by the wall clock (dfhack.getTickCount)
function run_stale(run)
    if (run.frames or 0) > 2 * RUN_FRAMES then return true end
    local t = ms_now()
    return t ~= nil and run.started_ms ~= nil and t - run.started_ms > STALE_MS
end

local function opt_id(v)
    if v == nil then return true, nil end
    local n = math.tointeger(tonumber(v))
    if not n or n < 0 then return false end
    return true, n
end

-- (0.105.47) can the travellers walk out? units: unit ids; squads: squad
-- ids (their members' units). nil when it can't be told.
function travellers_way(units, squads)
    local ids = {}
    for _, u in ipairs(units or {}) do table.insert(ids, u) end
    for _, sid in ipairs(squads or {}) do
        pcall(function()
            local sq = df.squad.find(sid)
            for i = 0, #sq.positions - 1 do
                local occ = sq.positions[i].occupant
                if occ and occ >= 0 then
                    local hf = df.historical_figure.find(occ)
                    if hf and hf.unit_id >= 0 then table.insert(ids, hf.unit_id) end
                end
            end
        end)
    end
    if #ids == 0 then return nil end
    local ok, r = pcall(function() return reqscript('ai-mission-way').way(ids) end)
    if ok and type(r) == 'table' then return r end
    return nil
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
    -- (0.105.39 review) a run long past its time (its frames never came, or
    -- it never ended): dropped, so one stuck run doesn't block every other
    if RUN and run_stale(RUN) then
        local old = RUN
        RUN = nil
        pcall(function()
            old.why = 'dropped: the run was older than ' .. (2 * RUN_FRAMES) .. ' frames'
            old.result, old.reason, old.stopped_at = 'error', 'stale', old.step_name
            save_outcome(old)
        end)
        -- its World screen shut (only while on top: the player's windows stay)
        pcall(close_world, nil, 0, function() end)
    end
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
    if not buttons().World and not world_by_key() then   -- (r12) else DF's World key
        return {ok = false, rejected = true, needs_button = 'World',
                error = 'the AI doesn\'t know where the World button is yet: python brain\\probe_missions.py --here World'}
    end
    -- (0.105.39) the goal's button known before a run starts (Make contact,
    -- as before, starts and stops at its goal step)
    -- (0.105.47) a goal whose button is found by its word needs no calibration
    if goal ~= 'make_contact' and not G.words and not buttons()[G.button] then
        return {ok = false, rejected = true, needs_button = G.button,
                error = 'the AI doesn\'t know where the ' .. G.button .. ' button is yet: with a site\'s New mission ' ..
                        'showing, python brain\\probe_missions.py --here ' .. G.button}
    end
    -- (0.105.47, live 17:09) the travellers must be able to walk off the
    -- map: the messenger, every member of the squads (lua/ai-mission-way.lua;
    -- the planner opens one of the AI's gates first). Unknown: not refused.
    local way = travellers_way(goal == 'make_contact' and {mid} or nil, G.squads and squad_ids or nil)
    if way and way.known and #way.blocked > 0 then
        return {ok = false, waiting = true, no_way_out = true, blocked = way.blocked,
                error = #way.blocked .. ' traveller(s) can\'t walk off the map (a gate shut?): the mission waits'}
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
                 waited = 0, frames = 0, trail = {}, started = now_tick(),
                 messenger_hf = mid and MESSENGER_HF or nil, messenger_name = mid and MESSENGER_NAME or nil}
    -- (r9, audit A8 #15) whom an offensive mission attacks (the bridge's
    -- send_mission): booked in the save only once the run is 'sent' (finish)
    if type(a.attacks) == 'table' then
        run.attacks = {}
        for _, id in pairs(a.attacks) do
            if type(id) == 'number' and id >= 0 then table.insert(run.attacks, id) end
        end
    end
    run.step_name = run.steps[1].name
    local st0 = read_state(run)
    run.controllers_before = st0.controllers
    run.ac_before = controller_ids_now()
    run.focus0, run.pause0, run.started_ms = st0.focus, pause_state(), ms_now()
    RUN = run
    later(1, function() tick(run) end)
    return {ok = true, sending = true, goal = goal, site_id = site_id, site = name, steps = steps, stops_at = stops_at}
end

-- (0.105.48, K9) The overseer's backstop (unattended only, brain/overseer.py
-- WORLD_CLOSE_S): DF's World screen holds the game (the date stands still,
-- no daily cycle comes, no new start() to close it), so after a few minutes
-- with nobody at the game it is left (LEAVESCREEN while it is on top, as
-- close_world). A run under way and not stale is never cut short; a stale
-- one is dropped as start() drops it. Returns at once; the presses run over
-- the next frames (LEAVE says how it ended; the pulse's world_open shows it).
LEAVE = LEAVE or nil
function leave_world(dry_run)
    if not world_screen() then return {ok = false, rejected = true, screen = false, error = 'the World screen is not open'} end
    if RUN and not run_stale(RUN) then
        return {ok = false, waiting = true, screen = true,
                error = 'a mission is being sent (step ' .. tostring(RUN.step_name) .. '): the World screen is its'}
    end
    if dry_run then return {ok = true, dry_run = true, screen = true, on_top = world_on_top()} end
    if RUN then
        local old = RUN
        RUN = nil
        pcall(function()
            old.why = 'dropped: the World screen was left by the overseer (nobody at the game)'
            old.result, old.reason, old.stopped_at = 'error', 'stale', old.step_name
            save_outcome(old)
        end)
    end
    LEAVE = {started = ms_now()}
    local leave = LEAVE
    close_world(nil, 0, function(closed) leave.closed = closed end)
    return {ok = true, screen = true, closing = true, on_top = world_on_top()}
end

-- The run under way and the last one's outcome, for the report.
function status()
    local out = {}
    if RUN then out.running = {goal = RUN.goal, site_id = RUN.site_id, step = RUN.step_name, frames = RUN.frames} end
    local last = last_outcome()
    if last then
        out.last = small(last)
        -- (0.105.39 review) each goal's last outcome: the retry block per goal
        out.last_by_goal = {}
        for g, o in pairs(by_goal_of(last)) do
            if type(o) == 'table' then out.last_by_goal[g] = small(o) end
        end
    end
    out.buttons = sorted_buttons()
    out.on = switch_on('make_contact') == true
    local known = buttons()
    out.goals = {}
    for g, G in pairs(GOALS) do
        -- (0.105.47) `button`: the goal's button can be pressed (shown, or
        -- found by its word); `all_recorded`: a run can go to the confirm
        local stops
        for _, st in ipairs(steps_for(g)) do if not st.act then stops = st.name break end end
        out.goals[g] = {button = known[G.button] ~= nil or G.words ~= nil, recorded = last_recorded(g),
                        words = G.words ~= nil or nil, all_recorded = stops == nil}
    end
    return out
end
