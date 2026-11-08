-- The title screen, for the keeper's --revive: what is on it (probe), and
-- loading a save from it (load <folder>). DFHack's own load-save script was
-- written for the old interface and fails on DF 50+ (seen Oct 23).
--
--   ai-title probe            JSON: the screens open and the title screen's fields
--   ai-title load <folder>    load that save (from the title screen)
--   ai-title status           how the last load went, step by step
--@ module = true

local json = require('json')

local function kind(v)
    local ok, k = pcall(function() return v._kind end)
    return ok and k or nil
end

-- A readable copy of a game structure: scalars as they are, containers as
-- their size and first few items, structures field by field, `depth` deep.
local function dump(v, depth)
    local t = type(v)
    if t == 'number' or t == 'boolean' or t == 'string' or v == nil then return v end
    if t ~= 'userdata' then return tostring(v) end
    local k = kind(v)
    if depth <= 0 then
        local okn, n = pcall(function() return #v end)
        return k == 'container' and okn and ('[' .. n .. ' items]') or ('<' .. tostring(k) .. '>')
    end
    if k == 'container' then
        local out = {n = #v, items = {}}
        for i = 0, math.min(#v, 5) - 1 do
            local ok, item = pcall(function() return v[i] end)
            out.items[#out.items + 1] = ok and dump(item, depth - 1) or '?'
        end
        return out
    end
    local out = {}
    local ok = pcall(function()
        for name, val in pairs(v) do
            local okv, d = pcall(dump, val, depth - 1)
            out[tostring(name)] = okv and d or '?'
        end
    end)
    if not ok then return tostring(v) end
    return out
end

local function screens()
    local out = {}
    local s = dfhack.gui.getCurViewscreen(true)
    while s do
        local okn, name = pcall(function() return s._type end)
        table.insert(out, tostring(okn and name or s))
        s = s.parent
    end
    return out
end

function probe()
    local out = {world_loaded = dfhack.isWorldLoaded(), screens = screens()}
    pcall(function() out.focus = dfhack.gui.getFocusStrings(dfhack.gui.getDFViewscreen(true)) end)
    local okt, title = pcall(dfhack.gui.getViewscreenByType, df.viewscreen_titlest, 0)
    if okt and title then out.title = dump(title, 3) end
    local okl, lg = pcall(function() return dfhack.gui.getViewscreenByType(df.viewscreen_loadgamest, 0) end)
    if okl and lg then out.loadgame = dump(lg, 3) end
    pcall(function() out.enums = {main_choice = dump(df.main_choice_type, 1)} end)
    return out
end

-- Load `folder` from the title screen (DF 53: Continue -> the world -> the
-- save). One step every STEP_FRAMES frames, each checked; what happened is
-- kept in LOAD_LOG (ai-title status). The title screen's `selected` is the
-- highlighted line of whichever list it shows.
STEP_FRAMES = 15
LOAD_LOG = LOAD_LOG or {}

local function title_screen()
    return dfhack.gui.getViewscreenByType(df.viewscreen_titlest, 0)
end

local function snap(t)
    local out = {}
    for _, k in ipairs({'mode', 'selected', 'selected_r', 'game_start_proceed', 'scroll_position_world_choice',
                        'scroll_position_game_choice'}) do
        local ok, v = pcall(function() return t[k] end)
        out[k] = ok and v or nil
    end
    pcall(function() out.worlds = #t.savegame_header_world end)
    pcall(function() out.games = #t.savegame_header_game end)
    pcall(function() out.menu = {} for i = 0, #t.menu_line_id - 1 do out.menu[#out.menu + 1] = t.menu_line_id[i] end end)
    out.world_loaded = dfhack.isWorldLoaded()
    return out
end

local function say(step, t, extra)
    local e = {step = step, at = t and snap(t) or {world_loaded = dfhack.isWorldLoaded()}}
    for k, v in pairs(extra or {}) do e[k] = v end
    table.insert(LOAD_LOG.steps, e)
end

local function find_in(list, folder)
    for i = 0, #list - 1 do
        local ok, f = pcall(function() return list[i].filename_noext end)
        if ok and f == folder then return i end
    end
end

-- A left click on the title screen's top button (DFHack's ci/test.lua).
function click_top(scr)
    local sw, sh = dfhack.screen.getWindowSize()
    local gps = df.global.gps
    gps.mouse_x = sw // 2
    gps.mouse_y = sh < 60 and 25 or (sh // 2) + 3
    pcall(function()
        gps.precise_mouse_x = gps.mouse_x * gps.tile_pixel_x
        gps.precise_mouse_y = gps.mouse_y * gps.tile_pixel_y
    end)
    require('gui').simulateInput(scr, '_MOUSE_L')
end

-- A few frames after scrolling a list: go on only if the scroll held (DF
-- may pull it back when the list is short), else stop with a note.
function then_if_scrolled(scr, field, want, go)
    dfhack.timeout(3, 'frames', function()
        local ok, v = pcall(function() return scr[field] end)
        if ok and v == want then return go() end
        say('stopped: the list would not scroll to the save (' .. field .. ' is ' .. tostring(v) ..
            ', wanted ' .. tostring(want) .. '): not clicking, it could open another save', scr)
    end)
end

-- Check `test` every 5 frames, up to `frames`; then done(true|false).
function wait_for(test, done, frames)
    local left = frames or 600
    local function step()
        local ok, yes = pcall(test)
        if ok and yes then return done(true) end
        left = left - 5
        if left <= 0 then return done(false) end
        dfhack.timeout(5, 'frames', step)
    end
    dfhack.timeout(5, 'frames', step)
end

function load(folder)
    if dfhack.isWorldLoaded() then return {ok = false, error = 'a world is already loaded'} end
    local t = title_screen()
    if not t then return {ok = false, error = 'not at the title screen', screens = screens()} end
    -- (0.100.1, review) a list left open by an earlier try (the world or the
    -- save list): its top line is some other save, so back out to the menu
    -- first and let the next try start from there
    if t.mode == 2 or t.mode == 3 then
        pcall(function() require('gui').simulateInput(t, 'LEAVESCREEN') end)
        return {ok = false, error = 'a list was open on the title screen (mode ' .. tostring(t.mode) ..
                '): backed out to the menu; the next try starts from there'}
    end
    local i = find_in(t.savegame_header, folder)
    if not i then return {ok = false, error = 'no save called ' .. tostring(folder) .. ' on the title screen'} end
    local world = t.savegame_header[i].world_name
    local wi
    for j = 0, #t.savegame_header_world - 1 do
        if t.savegame_header_world[j].world_name == world then wi = j break end
    end
    if not wi then return {ok = false, error = 'the save\'s world ' .. tostring(world) .. ' is not listed'} end
    LOAD_LOG = {folder = folder, world = world, world_index = wi, steps = {}, started = os.time()}
    say('start', t)
    -- As DFHack's own test runner does on DF 50+ (ci/test.lua): a click on
    -- the top button of the title screen, three times: "Continue active
    -- game" (mode 2: the worlds), the top world (mode 3: its saves), the top
    -- save (the load starts). A list's top button is the line at its scroll
    -- position, so the world and the save are scrolled to the top first.
    click_top(t)
    wait_for(function() local x = title_screen() return x == nil or x.mode == 2 end, function(ok)
        local t2 = title_screen()
        say('worlds listed', t2, {ok = ok})
        if not ok or not t2 then return end
        pcall(function() t2.scroll_position_world_choice = wi end)
        t2.selected = wi
        -- (only if the scroll held: else the top button is another world)
        then_if_scrolled(t2, 'scroll_position_world_choice', wi, function()
        click_top(t2)
        wait_for(function() local x = title_screen() return x == nil or x.mode == 3 end, function(ok2)
            local t3 = title_screen()
            local gi = t3 and find_in(t3.savegame_header_game, folder)
            say('saves listed', t3, {ok = ok2, game_index = gi})
            if not ok2 or not t3 or not gi then return end
            pcall(function() t3.scroll_position_game_choice = gi end)
            t3.selected = gi
            then_if_scrolled(t3, 'scroll_position_game_choice', gi, function()
            click_top(t3)
            wait_for(function()
                return dfhack.isWorldLoaded() or dfhack.gui.matchFocusString('loadgame') or title_screen() == nil
            end, function(ok3)
                -- (the title screen is gone once the load starts: its memory isn't read again)
                say('save clicked', title_screen(), {ok = ok3, loading = ok3})
            end)
            end)
        end)
        end)
    end)
    return {ok = true, started = true, folder = folder, world = world}
end

-- Of `folders` (newest first), load the first whose save belongs to `world`
-- (DF's autosave folders are shared by every world).
function load_match(world, folders)
    if dfhack.isWorldLoaded() then return {ok = false, error = 'a world is already loaded'} end
    local t = title_screen()
    if not t then return {ok = false, error = 'not at the title screen'} end
    local seen = {}
    for _, f in ipairs(folders) do
        local i = find_in(t.savegame_header, f)
        if i then
            local w = t.savegame_header[i].world_name
            table.insert(seen, f .. ': ' .. tostring(w))
            -- (0.100.1, review) last-fort.json keeps the name in UTF-8; the
            -- game's own is in its code page (an accented world never matched)
            local okc, wu = pcall(dfhack.df2utf, w)
            if w == world or (okc and wu == world) then return load(f) end
        end
    end
    return {ok = false, error = 'no save of the world ' .. tostring(world) .. ' among ' .. table.concat(seen, '; ')}
end

function status()
    local out = {}
    for k, v in pairs(LOAD_LOG) do out[k] = v end
    out.world_loaded = dfhack.isWorldLoaded()
    out.screens = screens()
    return out
end

if dfhack_flags.module then return end

-- (through reqscript, so the load's step log outlives this run of the script)
local M = reqscript('ai-title')
local args = {...}
local r
if args[1] == 'status' then
    local ok, res = pcall(M.status)
    r = ok and res or {ok = false, error = tostring(res)}
elseif args[1] == 'load-match' then
    local folders = {}
    for f in tostring(args[3] or ''):gmatch('[^|]+') do table.insert(folders, f) end
    local ok, res = pcall(M.load_match, args[2], folders)
    r = ok and res or {ok = false, error = tostring(res)}
elseif args[1] == 'load' then
    local ok, res = pcall(M.load, table.concat(args, ' ', 2))
    r = ok and res or {ok = false, error = tostring(res)}
else
    local ok, res = pcall(M.probe)
    r = ok and res or {ok = false, error = tostring(res)}
end
print(json.encode(r, {pretty = false}))
