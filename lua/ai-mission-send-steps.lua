-- ai-mission-send-steps: the World screen's words read and pressed (labels,
-- tick boxes, the left panel's rows) and the steps of each goal's mission
-- (STEP_DEFS, RECIPES, RECORDED, steps_for).
--
-- (r9) A part of ai-mission-send, not a script of its own: ai-mission-send.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-mission-send').name and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-mission-send-steps is a part of ai-mission-send; run ai-mission-send') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-mission-send-steps'] = '0.105.103'   -- (0.105.26) bumped with BRIDGE_VERSION

local id_of, click, press = PART_LOCALS.id_of, PART_LOCALS.click, PART_LOCALS.press   -- (r9) the hub's and earlier parts' locals

-- ---------------------------------------------------------------------------
-- (0.105.47) the screen's words: a button is pressed where its label is read
-- off the screen (dfhack.screen.readTile, as lua/ai-screen-buttons.lua), a
-- tick box from the recorded spot beside "Done assigning", checked by its
-- row's words. Nothing is pressed where the words aren't read.

-- the recorded geometry (14 Nov, a 150 x 66 grid, both runs alike): the top
-- row's tick box (clicks at x83-86 y2-3) 24 tiles right of the centre of
-- "Done assigning" (clicks at x60-64 y39-40) and 37 rows above it; the rows
-- 3 apart (36 px rows of 12 px tiles, raid-details.png); the left panel
-- about 27 tiles each side of the button's centre
TICK_DX = 24
ROW1_DY = 37
ROW_STEP = 3
PANEL_HALF = 27
TEXT_WHY = 'the screen\'s text can\'t be read (dfhack.screen.readTile gave no letters: a TrueType font?), ' ..
           'so the AI can\'t find the button by its word and never clicks blind'

-- The screen's text, rows 0..dimy-1 (a string each), or nil when a tile
-- can't be read or nothing but blanks is read.
function screen_rows()
    local gps = df.global.gps
    local rows, any = {}, false
    local okd, w, h = pcall(function() return gps.dimx, gps.dimy end)
    if not okd or type(w) ~= 'number' or type(h) ~= 'number' then return nil end
    for y = 0, h - 1 do
        local chars = {}
        for x = 0, w - 1 do
            local ok, t = pcall(function() return dfhack.screen.readTile(x, y) end)
            local ch = ok and type(t) ~= 'nil' and tonumber(t.ch) or nil
            if ch == nil then return nil end
            if ch > 32 and ch < 127 then any = true end
            chars[#chars + 1] = (ch >= 32 and ch < 127) and string.char(ch) or ' '
        end
        rows[y] = table.concat(chars)
    end
    return any and rows or nil
end

-- (0.105.74) What the screen held when a word wasn't found (live 22 Nov: A's
-- raid "none of Attack is on New mission", E's Make contact "none of
-- Diplomacy"; reading words off New mission never seen working): the rows
-- with any letter (trimmed, at most SCREEN_DUMP_ROWS), and how its tiles read
-- (letters, texture tiles with no letter, top_of_text), for mission-send.json.
SCREEN_DUMP_ROWS = 70
function screen_dump(rows)
    local out = {rows = {}, letters = 0, glyphless = 0, top_of_text = 0, blank = 0}
    for y = 0, SCREEN_DUMP_ROWS * 2 do
        local r = type(rows) == 'table' and rows[y] or nil
        if type(r) == 'string' and r:find('%a') and #out.rows < SCREEN_DUMP_ROWS then
            table.insert(out.rows, ('%02d|'):format(y) .. (r:gsub('%s+$', '')))
        end
    end
    pcall(function()
        local gps = df.global.gps
        for y = 0, gps.dimy - 1 do
            for x = 0, gps.dimx - 1 do
                local ok, t = pcall(function() return dfhack.screen.readTile(x, y) end)
                if ok and t then
                    local ch = tonumber(t.ch) or 0
                    if ch > 32 and ch < 127 then out.letters = out.letters + 1
                    elseif (tonumber(t.tile) or 0) > 0 then out.glyphless = out.glyphless + 1
                    else out.blank = out.blank + 1 end
                    local okt, top = pcall(function() return t.top_of_text end)
                    if okt and top then out.top_of_text = out.top_of_text + 1 end
                end
            end
        end
    end)
    return out
end

-- Pure: `word` found as in find_words, the case ignored (rows and word
-- lowered: the matches' places are the same)
function find_words_ci(rows, word, area)
    if type(rows) ~= 'table' or type(word) ~= 'string' then return {} end
    local low = {}
    for k, r in pairs(rows) do low[k] = type(r) == 'string' and r:lower() or r end
    return find_words(low, word:lower(), area)
end

-- Pure: where `word` stands as a label in the rows (a whole word: no letter
-- or digit touching it), inside `area` {x0, x1, y0, y1} when given. Each
-- {x, x_end, y, cx, after}, top to bottom, left to right.
function find_words(rows, word, area)
    local out = {}
    if type(rows) ~= 'table' or type(word) ~= 'string' or word == '' then return out end
    area = area or {}
    local y0 = area.y0 or 0
    local y1 = area.y1
    if not y1 then
        y1 = -1
        for k in pairs(rows) do if type(k) == 'number' and k > y1 then y1 = k end end
    end
    for y = y0, y1 do
        local row = rows[y]
        if type(row) == 'string' then
            local from = 1
            while true do
                local a, b = row:find(word, from, true)
                if not a then break end
                local before = a > 1 and row:sub(a - 1, a - 1) or ' '
                local after = row:sub(b + 1, b + 1)
                local x0, x1 = a - 1, b - 1
                if not before:match('%w') and not after:match('%w')
                        and (area.x0 == nil or x0 >= area.x0) and (area.x1 == nil or x1 <= area.x1) then
                    table.insert(out, {x = x0, x_end = x1, y = y, cx = x0 + (x1 - x0) // 2, after = row:sub(b + 1, b + 4)})
                end
                from = b + 1
            end
        end
    end
    return out
end

-- Pure: the label to press among the matches: the bottom-most (a panel's
-- title, which can carry the same words, "Make contact at ...", "Raid
-- ...", stands above its rows), never one followed by `not_followed`.
function pick_word(matches, not_followed)
    local best
    for _, m in ipairs(matches) do
        if not (not_followed and m.after:sub(1, #not_followed) == not_followed) then best = m end
    end
    return best
end

-- Press the label `word`: true and the match, or false, reason, why.
function press_word(word, opts)
    opts = opts or {}
    local rows = opts.rows or screen_rows()
    if not rows then return false, 'unreadable', TEXT_WHY end
    local m = pick_word(find_words(rows, word, opts.area), opts.not_followed)
    if not m then return false, 'not_found', '"' .. word .. '" is not on the screen' end
    local ok, err = pcall(click, m.cx, m.y)
    if not ok then return false, 'click_failed', 'the click failed: ' .. tostring(err):sub(1, 160) end
    return true, m
end

-- Pure: "Done assigning" on Mission details (the panel's anchor), or nil.
function done_anchor(rows)
    return pick_word(find_words(rows, 'Done assigning'))
end

-- Pure: the text of a row's three lines in the left panel, left of its tick box
function row_text(rows, done, y)
    local x0 = math.max(0, done.cx - PANEL_HALF)
    local x1 = done.cx + TICK_DX - 2
    local parts = {}
    for yy = y - 1, y + 1 do
        local r = rows[yy]
        if type(r) == 'string' then table.insert(parts, r:sub(x0 + 1, x1 + 1)) end
    end
    return table.concat(parts, ' | ')
end

-- Pure: the tick box of the left panel's row `index` (0 = top), as recorded
-- beside "Done assigning", when its row reads one of `want` (plain words,
-- case ignored). Returns x, y or nil and why.
function tick_spot(rows, done, index, want)
    if not done then return nil, '"Done assigning" is not on the screen' end
    local x, y = done.cx + TICK_DX, done.y - ROW1_DY + ROW_STEP * index
    if y < 0 or y > done.y - 3 then
        return nil, 'row ' .. (index + 1) .. ' is beyond what the panel shows (a longer list than the screen holds)'
    end
    local text = row_text(rows, done, y)
    local low = text:lower()
    for _, w in ipairs(want or {}) do
        if type(w) == 'string' and w ~= '' and low:find(w:lower(), 1, true) then return x, y end
    end
    return nil, 'row ' .. (index + 1) .. ' reads "' .. text:gsub('%s+', ' '):sub(1, 60) .. '", not ' ..
                table.concat(want or {}, ' / ')
end

-- the messenger's first name as DF writes it (the row shows "Led Glidedgorges")
local function first_name(hf)
    local ok, n = pcall(function() return hf.name.first_name end)
    if not ok or type(n) ~= 'string' or n == '' then return nil end
    return n:sub(1, 1):upper() .. n:sub(2)
end

-- the index of a vector's item whose `field` (or id) is `want`
local function index_of(vec, want, field)
    local found
    pcall(function()
        for i = 0, #vec - 1 do
            local v = vec[i]
            local okf, x = pcall(function() return field and v[field] or id_of(v) end)
            if okf and x == want then found = i; return end
        end
    end)
    return found
end

local function contains(list, x)
    for _, v in ipairs(list or {}) do if v == x then return true end end
    return false
end

-- ---------------------------------------------------------------------------
-- the steps. Each: `expect` (the screen it starts from; else the run stops),
-- `act` (what the player did), `check` (after acting: 'ok' when the next
-- recorded screen shows and its fields are right, 'wait' while it may still
-- come, else 'bad' with why). A step not yet recorded has no act: the run
-- stops there, every field it saw written down.

SITE_HOVER_FRAMES, SITE_RECLICK_FRAMES = 4, 20   -- (r12) the hover before the site's click; a second click

-- (r12 v6) the site's click: the mouse on (x, y) for SITE_HOVER_FRAMES, then
-- the click, only while this run is still on its site step with the World
-- screen on top (never on a window the player opened meanwhile, never after
-- the run stopped); the mouse put back (both readings) whatever happened.
-- False when the frame timer can't be set (the caller clicks at once).
function hover_click(run, x, y)
    local gps = df.global.gps
    local ox, oy = gps.mouse_x, gps.mouse_y
    local opx, opy
    pcall(function() opx, opy = gps.precise_mouse_x, gps.precise_mouse_y end)
    local ok = pcall(function()
        gps.mouse_x, gps.mouse_y = x, y
        pcall(function()
            gps.precise_mouse_x = x * gps.tile_pixel_x + gps.tile_pixel_x // 2
            gps.precise_mouse_y = y * gps.tile_pixel_y + gps.tile_pixel_y // 2
        end)
        dfhack.timeout(SITE_HOVER_FRAMES, 'frames', function()
            local okt, top = pcall(world_on_top)
            if RUN == run and not run.stopping and run.step_name == 'site' and okt and top then
                run.clicked_waited = run.waited or 0       -- the AI's own click (tick: not the player's)
                pcall(click, x, y)
            end
            gps.mouse_x, gps.mouse_y = ox, oy
            if opx ~= nil then pcall(function() gps.precise_mouse_x, gps.precise_mouse_y = opx, opy end) end
        end)
    end)
    if not ok then gps.mouse_x, gps.mouse_y = ox, oy end
    return ok
end

STEP_DEFS = {
    open = {name = 'open',
     expect = function(st) return not st.world, 'the World screen is open already' end,
     act = function(run)
         WORLD_VIA_KEY = false
         local ok, a, b = press('World')
         run.world_via_key = WORLD_VIA_KEY or nil          -- (r12) opened by DF's key, not a click
         return ok, a, b
     end,
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
         -- (0.105.47) the map centred on the site first (region_cent_x/y in
         -- world tiles, as recorded: the tile under the screen's middle is the
         -- centre), so the hover under the click agrees with focus_site
         pcall(function()
             local s = df.world_site.find(run.site_id)
             scr.region_cent_x, scr.region_cent_y = s.pos.x, s.pos.y
         end)
         local okw, err = pcall(function()
             if type(scr.focus_site) == 'number' then scr.focus_site = run.site_id
             else scr.focus_site = df.world_site.find(run.site_id) end
         end)
         if not okw then return false, 'unwritable', 'focus_site could not be set: ' .. tostring(err):sub(1, 120) end
         -- (r12, live 22 Nov: the click at once left the World screen on
         -- NORMAL) the mouse put on the map's middle first and left there a
         -- few frames, so DF draws the hover under it (its click takes the
         -- hovered site), then the click (hover_click); once more later in check
         local gps = df.global.gps
         local mx, my = gps.dimx // 2, gps.dimy // 2
         if not hover_click(run, mx, my) then
             local ok, e = pcall(click, mx, my)
             if not ok then return false, 'click_failed', 'the click failed: ' .. tostring(e):sub(1, 160) end
         end
         run.site_xy = {mx, my}
         return true
     end,
     check = function(st, run)
         if not st.world then return 'bad', 'the World screen closed' end
         if st.mode == 'NORMAL' then
             if not run.reclicked and (run.waited or 0) >= SITE_RECLICK_FRAMES and run.site_xy then
                 run.reclicked = true
                 pcall(function()
                     local scr = world_screen()
                     local s = df.world_site.find(run.site_id)
                     scr.region_cent_x, scr.region_cent_y = s.pos.x, s.pos.y
                     if type(scr.focus_site) == 'number' then scr.focus_site = run.site_id
                     else scr.focus_site = s end
                 end)
                 hover_click(run, run.site_xy[1], run.site_xy[2])     -- (r12 v6) hovered too
             end
             return 'wait', 'still on world/NORMAL after the click'
         end
         if st.mode ~= 'NEW_MISSION' then
             return 'bad', 'the click led to world/' .. tostring(st.mode) .. ', not NEW_MISSION (recorded)'
         end
         if st.focus_site ~= run.site_id then
             return 'bad', 'New mission is for site ' .. tostring(st.focus_site) .. ', not ' .. tostring(run.site_id)
         end
         if st.goal_ok ~= 'OKAY' then
             -- (0.105.47) recorded: an island's Attack, Request workers and
             -- Diplomacy all INACCESSIBLE; the planner drops such a site
             if st.goal_ok == 'INACCESSIBLE' then
                 return 'bad', run.button .. ' is INACCESSIBLE there: DF says its people can\'t get there', 'inaccessible'
             end
             return 'bad', run.button .. ' is ' .. tostring(st.goal_ok) .. ' there, not OKAY', 'unavailable'
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
     -- (0.105.47) the button by its word (Diplomacy, Attack: recorded);
     -- with text that can't be read, Diplomacy's calibrated place only
     act = function(run)
         local G = GOALS[run.goal] or {}
         if not G.words then return press(run.button) end
         local rows = screen_rows()
         if not rows then
             if run.goal == 'make_contact' then return press(run.button) end   -- (needs_button when never shown)
             return false, 'unreadable', TEXT_WHY
         end
         for _, w in ipairs(G.words) do
             local ok, m, why = press_word(w, {rows = rows})
             if ok then run.pressed = w; return true end
             if m ~= 'not_found' then return false, m, why end
         end
         -- (0.105.74) the word in capitals (DIPLOMACY, ATTACK; never a lowercase
         -- word in a sentence, verifier), the screen kept either way
         for _, w in ipairs(G.words) do
             local m
             for _, c in ipairs(find_words_ci(rows, w)) do
                 if rows[c.y]:sub(c.x + 1, c.x_end + 1) == w:upper() then m = c end
             end
             if m then
                 local okc, err = pcall(click, m.cx, m.y)
                 if not okc then return false, 'click_failed', 'the click failed: ' .. tostring(err):sub(1, 160) end
                 run.pressed = w .. ' (case ignored)'
                 run.screen = screen_dump(rows)
                 run.goal_ci = true
                 return true
             end
         end
         run.screen = screen_dump(rows)
         run.goal_unread = true
         return false, 'not_found', 'none of ' .. table.concat(G.words, ' / ') .. ' is on New mission'
     end,
     check = function(st, run)
         if not st.world then return 'bad', 'the World screen closed' end
         if st.mode == 'NEW_MISSION' then return 'wait', 'still on world/NEW_MISSION after ' .. (run.pressed or run.button) end
         if st.mode ~= 'MISSION_DETAILS' then
             return 'bad', run.button .. ' led to world/' .. tostring(st.mode) .. ', not MISSION_DETAILS (recorded)'
         end
         -- (0.105.39 review) the new controller is the run's goal, not another's
         if not st.ac_id then
             return 'bad', 'no new army controller on MISSION_DETAILS (selected_ac ' .. tostring(st.selected_ac) ..
                           (st.ac_by == 'ambiguous' and ', its readings disagree' or '') .. ')'
         end
         if st.ac_goal ~= run.df_goal then
             local why = 'the new army controller\'s goal is ' .. tostring(st.ac_goal_name or st.ac_goal) ..
                         ', not ' .. tostring(run.df_goal_name)
             -- Make contact's step was recorded live: a mismatch is written
             -- down for the record, not taken as a failure
             if run.goal ~= 'make_contact' then return 'bad', why end
             run.goal_mismatch = why
         end
         -- (0.105.47) recorded: the new controller is at the site (59, 73)
         if st.ac_site ~= nil and st.ac_site ~= run.site_id then
             return 'bad', 'the new army controller is for site ' .. tostring(st.ac_site) .. ', not ' .. run.site_id
         end
         run.selected_ac = st.selected_ac
         run.ac_id = st.ac_id
         return 'ok'
     end},
}

-- (0.105.47) the Mission details steps, recorded 14 Nov. Each act that
-- presses nothing (a choice DF made already, as recorded) says so in
-- run.left; every check is on the run's own controller.
local function on_details(st, run, goal_name)
    if not st.world then return false, 'the World screen closed' end
    if st.mode ~= 'MISSION_DETAILS' then return false, 'not on world/MISSION_DETAILS (' .. tostring(st.mode) .. ')' end
    if not st.ac_id or st.ac_id ~= run.ac_id then
        return false, 'Mission details doesn\'t show the run\'s army controller (' .. tostring(st.ac_id) .. ')'
    end
    if goal_name and st.ac_goal_name and st.ac_goal_name ~= goal_name then
        return false, 'the controller\'s goal is ' .. tostring(st.ac_goal_name) .. ', not ' .. goal_name
    end
    return true
end

local function left(run, what)
    run.left = run.left or {}
    table.insert(run.left, what)
end

local function still_details(st, run)
    local ok, why = on_details(st, run)
    if ok then return 'ok' end
    return 'bad', why
end

-- Make contact: chosen by DF for Diplomacy (green on both recordings, the
-- player never chose it): left as it is. Only a topic list read empty gets
-- the "Make contact" row pressed (by its word, never the title "Make
-- contact at ..."); a list that can't be read is left too (as recorded).
STEP_DEFS.make_contact = {name = 'make_contact',
    expect = function(st, run) return on_details(st, run, 'DIPLOMACY') end,
    act = function(run)
        local st = read_state(run)
        run.topics = st.topics
        if st.topics == nil then left(run, 'make_contact: the topics can\'t be read; left as DF chose (recorded: Make contact)'); return true end
        if #st.topics > 0 then left(run, 'make_contact: DF chose ' .. table.concat(st.topics, ', ')); return true end
        local ok, r, why = press_word('Make contact', {not_followed = ' at'})
        if not ok then return false, r, why end
        run.topic_pressed = true
        return true
    end,
    check = function(st, run)
        local ok, why = on_details(st, run)
        if not ok then return 'bad', why end
        if run.topic_pressed then
            if st.topics and #st.topics > 0 then run.topics = st.topics; return 'ok' end
            return 'wait', 'no topic chosen after pressing Make contact'
        end
        return 'ok'
    end}

-- The messenger: ticked in the left panel (recorded: the top row, "Led
-- Glidedgorges ... On this mission", the box at x83-86 y2-3). Its row is the
-- messenger's place in the screen's messenger_epp list; the box is pressed
-- only where that row reads the messenger's first name. DF listing none
-- ("No messengers available", recorded before one was appointed): stopped,
-- the planner appoints one. Checked on the controller's messengers
-- (assigned_epp_epp_id; DF's own field, not seen in the recording).
STEP_DEFS.messenger = {name = 'messenger',
    expect = function(st, run) return on_details(st, run, 'DIPLOMACY') end,
    act = function(run)
        local st = read_state(run)
        if st.ac_epp and #st.ac_epp > 0 then left(run, 'messenger: on the mission already'); return true end
        local scr = world_screen()
        if not scr then return false, 'gone', 'the World screen closed' end
        local okn, n = pcall(function() return #scr.messenger_epp end)
        if okn and n == 0 then
            return false, 'no_messenger', 'Mission details lists no messenger ("No messengers available"): the fort needs one appointed'
        end
        local idx = run.messenger_hf and index_of(scr.messenger_epp, run.messenger_hf, 'histfig')
        if not idx then return false, 'no_messenger', 'the fort\'s messenger isn\'t on Mission details\' list' end
        pcall(function() run.messenger_flag_before = scr.messenger_flag[idx].LOCKED_IN end)
        local rows = screen_rows()
        if not rows then return false, 'unreadable', TEXT_WHY end
        local want = {run.messenger_name}
        local x, y = tick_spot(rows, done_anchor(rows), idx, want)
        if not x then return false, 'not_found', y end
        local ok, err = pcall(click, x, y)
        if not ok then return false, 'click_failed', 'the click failed: ' .. tostring(err):sub(1, 160) end
        run.ticked = {{x, y}}
        return true
    end,
    check = function(st, run)
        local ok, why = on_details(st, run)
        if not ok then return 'bad', why end
        if st.ac_epp == nil then
            run.messenger_unverified = true
            return 'ok'
        end
        if #st.ac_epp > 0 then return 'ok' end
        return 'wait', 'the controller has no messenger after the tick'
    end}

-- (0.105.47) Does a squad hold a raid order for the site? true / false, or
-- nil when its orders can't be read
function squad_raid_order(squad_id, site_id)
    local ok, r = pcall(function()
        local sq = df.squad.find(squad_id)
        if not sq then return nil end
        local found = false
        for i = 0, #sq.orders - 1 do
            local o = sq.orders[i]
            local raid = false
            pcall(function() raid = df.squad_order_raid_sitest:is_instance(o) end)
            if not raid then pcall(function() raid = df.squad_order_type[o:getType()] == 'RAID_SITE' end) end
            if raid then
                local oks, sid = pcall(function() return o.site_id end)
                if not oks or sid == site_id then found = true end
            end
        end
        return found
    end)
    if ok then return r end
    return nil
end

-- The intent: Raid is DF's default for Attack (green, recorded, left as
-- it is). Another goal's intent is pressed only where its row is read in
-- the right panel ("Pillage", "Demand one-time tribute", "Conquer and
-- occupy", "Explore": never seen pressed) and must show on the
-- controller after; an intent that can't be read then stops the run.
STEP_DEFS.intent = {name = 'intent',
    expect = function(st, run) return on_details(st, run, 'SITE_INVASION') end,
    act = function(run)
        local G = GOALS[run.goal] or {}
        local st = read_state(run)
        run.intent_before = st.intent
        if st.intent ~= nil and st.intent == G.intent then left(run, 'intent: ' .. st.intent .. ' already'); return true end
        if G.default_intent and (st.intent == nil or st.intent == 'NONE') then left(run, 'intent: DF\'s default (' .. tostring(G.intent_word) .. ', recorded)'); return true end
        if not G.intent_word then return false, 'not_recorded', 'no word for the intent ' .. tostring(G.intent) end
        local rows = screen_rows()
        if not rows then return false, 'unreadable', TEXT_WHY end
        local done = done_anchor(rows)
        if not done then return false, 'not_found', '"Done assigning" is not on the screen' end
        local ok, r, why = press_word(G.intent_word, {rows = rows, area = {x0 = done.cx + PANEL_HALF}})
        if not ok then return false, r, why end
        run.intent_pressed = true
        return true
    end,
    check = function(st, run)
        local ok, why = on_details(st, run)
        if not ok then return 'bad', why end
        if not run.intent_pressed then return 'ok' end
        local G = GOALS[run.goal] or {}
        if st.intent == nil then return 'bad', 'the controller\'s intent can\'t be read to check ' .. tostring(G.intent_word), 'not_recorded' end
        if st.intent == G.intent then return 'ok' end
        return 'wait', 'the intent is ' .. tostring(st.intent) .. ', not ' .. tostring(G.intent) .. ' after pressing ' .. G.intent_word
    end}

-- The squads: each of the run's squads ticked in the left panel (recorded:
-- the controller's squads 0 -> 1 as the top row's box was ticked). A
-- squad's row is its place in the screen's squad list; every box is found
-- and its row read ("No specific orders") before any is pressed.
STEP_DEFS.squads = {name = 'squads',
    expect = function(st, run) return on_details(st, run, 'SITE_INVASION') end,
    act = function(run)
        local st = read_state(run)
        local scr = world_screen()
        if not scr then return false, 'gone', 'the World screen closed' end
        local spots, rows, done, ids = {}, nil, nil, {}
        for _, sid in ipairs(run.squad_ids or {}) do
            if not contains(st.ac_squads, sid) then
                local idx = index_of(scr.squad, sid)
                if not idx then return false, 'not_found', 'squad ' .. sid .. ' isn\'t on Mission details\' list' end
                if not rows then
                    rows = screen_rows()
                    if not rows then return false, 'unreadable', TEXT_WHY end
                    done = done_anchor(rows)
                end
                local x, y = tick_spot(rows, done, idx, {'No specific orders'})
                if not x then return false, 'not_found', 'squad ' .. sid .. ': ' .. y end
                table.insert(spots, {x, y})
                table.insert(ids, sid)
            end
        end
        if #spots == 0 then left(run, 'squads: on the mission already'); return true end
        run.ticked, run.ticked_ids = {}, {}
        for i, p in ipairs(spots) do
            local ok, err = pcall(click, p[1], p[2])
            if not ok then return false, 'click_failed', 'the click failed: ' .. tostring(err):sub(1, 160) end
            -- (r9) kept as pressed, so a run that stops later unticks them (stop)
            table.insert(run.ticked, p)
            table.insert(run.ticked_ids, ids[i])
        end
        return true
    end,
    check = function(st, run)
        local ok, why = on_details(st, run)
        if not ok then return 'bad', why end
        if st.ac_squads == nil then return 'bad', 'the controller\'s squads can\'t be read' end
        for _, sid in ipairs(run.squad_ids or {}) do
            if not contains(st.ac_squads, sid) then
                return 'wait', 'squad ' .. sid .. ' is not on the controller after the tick (' .. #st.ac_squads .. ' there)'
            end
        end
        return 'ok'
    end}

-- The side orders (free captives, loot...): left as DF set them (recorded).
STEP_DEFS.details = {name = 'details',
    expect = function(st, run) return on_details(st, run) end,
    act = function(run) left(run, 'details: the side orders as DF set them (recorded)'); return true end,
    check = still_details}

-- Done assigning -> MISSIONS_LIST (recorded), the run's controller still
-- there with its goal, site, squads / messenger. The intent read wrong
-- after it is written down (not undone). (0.105.47, 17:17: the player
-- checked both Mission details screens: only "Done assigning" and "Remove",
-- no other confirmation: Done assigning is the confirm.)
STEP_DEFS.confirm = {name = 'confirm',
    expect = function(st, run) return on_details(st, run) end,
    act = function(run) return press_word('Done assigning') end,
    check = function(st, run)
        if not st.world then return 'bad', 'the World screen closed' end
        if st.mode == 'MISSION_DETAILS' then return 'wait', 'still on Mission details after Done assigning' end
        if st.mode ~= 'MISSIONS_LIST' then
            return 'bad', 'Done assigning led to world/' .. tostring(st.mode) .. ', not MISSIONS_LIST (recorded)'
        end
        if st.ac_id ~= run.ac_id then return 'bad', 'the mission\'s army controller is gone after Done assigning' end
        if st.ac_goal ~= run.df_goal then return 'bad', 'the controller\'s goal changed to ' .. tostring(st.ac_goal_name) end
        if st.ac_site ~= nil and st.ac_site ~= run.site_id then return 'bad', 'the controller\'s site changed to ' .. tostring(st.ac_site) end
        local G = GOALS[run.goal] or {}
        if G.squads then
            if st.ac_squads == nil then return 'bad', 'the controller\'s squads can\'t be read' end
            for _, sid in ipairs(run.squad_ids or {}) do
                if not contains(st.ac_squads, sid) then return 'bad', 'squad ' .. sid .. ' is no longer on the mission' end
            end
        end
        -- (0.105.47, live 17:07) after Done assigning the raiding squad's
        -- order on DF's Squads screen read "Raid Crackeddreamed": each squad
        -- must hold a raid order for the site (squad.orders, a
        -- squad_order_raid_sitest / RAID_SITE with its site_id) before the
        -- run counts the mission set up; orders that can't be read are
        -- written down (run.order_unverified), not taken for an answer
        if G.squads and G.df == 'SITE_INVASION' then
            for _, sid in ipairs(run.squad_ids or {}) do
                local has = squad_raid_order(sid, run.site_id)
                if has == false then return 'wait', 'squad ' .. sid .. ' has no raid order for site ' .. run.site_id end
                if has == nil then run.order_unverified = true end
            end
        end
        if run.goal == 'make_contact' and st.ac_epp ~= nil and #st.ac_epp == 0 then
            return 'bad', 'the mission has no messenger after Done assigning'
        end
        if G.intent and st.intent ~= nil and st.intent ~= G.intent then
            run.intent_mismatch = 'the mission\'s intent reads ' .. st.intent .. ', not ' .. G.intent
        end
        run.squads_sent = st.ac_squads and #st.ac_squads or nil
        return 'ok'
    end}

-- every step each goal's mission takes, in order
local INVASION = {'open', 'site', 'goal', 'intent', 'squads', 'details', 'confirm'}
RECIPES = {
    make_contact     = {'open', 'site', 'goal', 'make_contact', 'messenger', 'confirm'},
    rescue           = {'open', 'site', 'goal', 'target', 'squads', 'details', 'confirm'},
    recover_artifact = {'open', 'site', 'goal', 'target', 'squads', 'details', 'confirm'},
    explore = INVASION, raid = INVASION, pillage = INVASION, tribute = INVASION, conquer = INVASION,
}
-- the steps recorded (seen, with an act in STEP_DEFS), per goal. (0.105.39
-- review) Only Diplomacy's goal button was ever seen pressed: the other
-- goals' runs stop before their goal button (a button nobody saw pressed is
-- never pressed)
RECORDED = {}
for g in pairs(GOALS) do RECORDED[g] = {'open', 'site'} end
RECORDED.make_contact = {'open', 'site', 'goal'}
-- (0.105.47) recorded 14 Nov end to end: Make contact, and the Raid (Attack,
-- the intent left at Raid, a squad ticked, Done assigning). Pillage, tribute,
-- conquer and explore share every screen but their intent's row, which is
-- pressed only where its word is read (and checked on the controller).
-- Rescue and recover_artifact stay at the site: their goal button and
-- target lists were never seen.
RECORDED.make_contact = {'open', 'site', 'goal', 'make_contact', 'messenger', 'confirm'}
for _, g in ipairs({'raid', 'pillage', 'tribute', 'conquer', 'explore'}) do
    RECORDED[g] = {'open', 'site', 'goal', 'intent', 'squads', 'details', 'confirm'}
end

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

-- (r9) this part's locals the next part uses
PART_LOCALS.first_name, PART_LOCALS.contains = first_name, contains
