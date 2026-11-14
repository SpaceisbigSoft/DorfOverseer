-- (0.105.47) A diplomat's or the liaison's meeting opened by the AI.
--
-- What the 8-13 Nov run showed: in all six forts no meeting was ever
-- answered (answer_meeting 0, no meeting-probe.json written anywhere): DF
-- queues a meeting in plotinfo.dipscript_popups ("cause viewscreen_meetingst
-- to pop up", df-structures; each with a moment_time_left) and lights the
-- purple diplomacy light by the alerts; the meeting screen opens only when
-- someone clicks that light. The AI only noted "a meeting waits to be shown
-- in DF ... the game runs on meanwhile" (A 6, B 19, C 11, E 15 times), the
-- popup ran out, and the gamelogs say "A diplomat could not complete a
-- meeting and has left unhappy" (A 25, B 72, C 93, D 29, E 21, F 34 in
-- their last 300-400 MB). So answer_meeting, which needs the screen open,
-- never had a meeting to answer.
--
-- Now the AI clicks the light itself: found on the screen by its own
-- picture (gps.graphical_interface / classic_interface texpos_diplomacy_light,
-- 3 x 3 tiles, read back from the screen's tiles), else where the player
-- showed it once (probe_meeting.py --here Light, kept for every save on the
-- PC). Only from the plain map (no menu of the player's open, no trade
-- screen), and the overseer sends it only in an unattended run, as it
-- answers meetings (brain/planner_meetings.py meeting_open_due). The meeting
-- screen it opens is answered by ai-diplomacy's answer_meeting and, if that
-- can't, left after 2 minutes as before.
--@ module = true

local U = reqscript('ai-util')

BUTTONS_KEY = 'ai-overseer/meeting-buttons'     -- ai-diplomacy's: the Light kept with Yes, No and Done
LAST = LAST or nil                               -- the last click and what came of it

function waiting()
    local ok, n = pcall(function() return #df.global.plotinfo.dipscript_popups end)
    return ok and n or 0
end

local function meeting_open()
    local ok, v = pcall(function() return df.global.game.main_interface.diplomacy.open end)
    return ok and v == true
end

-- The diplomacy light's pictures (texture numbers), both interface sets.
function light_textures()
    local set, n = {}, 0
    for _, which in ipairs({'graphical_interface', 'classic_interface'}) do
        pcall(function()
            local arr = df.global.gps[which].texpos_diplomacy_light
            for i = 0, 2 do
                for j = 0, 2 do
                    local okv, v = pcall(function() return arr[i][j] end)
                    if okv and type(v) == 'number' and v > 0 and not set[v] then set[v] = true; n = n + 1 end
                end
            end
        end)
    end
    return set, n
end

-- The picture on a screen tile: DFHack's readTile, else the screen's own array.
local function tile_at(x, y)
    local ok, t = pcall(function() return dfhack.screen.readTile(x, y) end)
    if ok and t and type(t.tile) == 'number' and t.tile > 0 then return t.tile end
    local ok2, v = pcall(function()
        local gps = df.global.gps
        return gps.screentexpos[x * gps.dimy + y]
    end)
    if ok2 and type(v) == 'number' then return v end
    return nil
end

-- Pure: the centre of the tiles that show the light (cells: {{x, y}, ...}).
function centre(cells)
    if not cells or #cells == 0 then return nil end
    local sx, sy = 0, 0
    for _, c in ipairs(cells) do sx, sy = sx + c[1], sy + c[2] end
    return math.floor(sx / #cells + 0.5), math.floor(sy / #cells + 0.5)
end

-- Where the light is on the screen now, or nil; how many tiles showed it.
function find_light()
    local set, n = light_textures()
    if n == 0 then return nil, 0, 0 end
    local gps, cells = df.global.gps, {}
    for x = 0, gps.dimx - 1 do
        for y = 0, gps.dimy - 1 do
            local t = tile_at(x, y)
            if t and set[t] then
                table.insert(cells, {x, y})
                if #cells >= 9 then break end
            end
        end
        if #cells >= 9 then break end
    end
    local cx, cy = centre(cells)
    return cx and {x = cx, y = cy} or nil, #cells, n
end

-- A word on the screen (a button's label), where its tiles can be read: the
-- places it starts at. TrueType text reads as nothing, so then none.
function find_word(word)
    local gps, hits = df.global.gps, {}
    for y = 0, gps.dimy - 1 do
        for x = 0, gps.dimx - #word do
            local ok, t = pcall(function() return dfhack.screen.readTile(x, y) end)
            if ok and t and t.ch == word:byte(1) then
                local m = true
                for k = 2, #word do
                    local okk, tk = pcall(function() return dfhack.screen.readTile(x + k - 1, y) end)
                    if not (okk and tk and tk.ch == word:byte(k)) then m = false; break end
                end
                if m then table.insert(hits, {x, y}) end
            end
        end
    end
    return hits
end

local function plain_map()
    local ok, yes = pcall(function() return dfhack.gui.matchFocusString('dwarfmode/Default') end)
    if ok then return yes == true end
    local okf, f = pcall(function() return dfhack.gui.getCurFocus(true)[1] end)
    return okf and tostring(f or '') == 'dwarfmode/Default'
end

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

-- Open the meeting that waits: click the light. dry_run finds it and clicks nothing.
function open(dry_run)
    if meeting_open() then return {ok = true, open = true, note = 'the meeting screen is already open'} end
    local n = waiting()
    if n == 0 then return {ok = true, waiting = true, error = 'no meeting waits to be shown'} end
    local okt, topen = pcall(function() return df.global.game.main_interface.trade.open end)
    if okt and topen then return {ok = true, waiting = true, error = 'the trade screen is open'} end
    if not plain_map() then return {ok = true, waiting = true, error = 'a menu is open (the player\'s): not now'} end
    local pos, cells, pics = find_light()
    local via = 'picture'
    if not pos then
        local b
        pcall(function() b = reqscript('ai-diplomacy').buttons().Light end)
        if b and type(b.x) == 'number' and type(b.y) == 'number' then
            pos, via = {x = b.x, y = b.y}, 'shown'
        end
    end
    if not pos then
        return {ok = false, rejected = true, popups = n, light_tiles = cells, pictures = pics,
                error = 'the diplomacy light was not found on the screen (its picture: ' .. tostring(pics)
                        .. ' known); show it once: python brain\\probe_meeting.py --here Light'}
    end
    if dry_run then return {ok = true, dry_run = true, at = {pos.x, pos.y}, via = via, popups = n} end
    local okc, err = pcall(click, pos.x, pos.y)
    LAST = {at = {pos.x, pos.y}, via = via, clicked = okc, error = not okc and tostring(err) or nil,
            opened = meeting_open()}
    -- the screen may come up a frame later: looked at again
    pcall(function()
        dfhack.timeout(5, 'frames', function() if LAST then LAST.opened = meeting_open() end end)
    end)
    return {ok = okc, clicking = true, at = {pos.x, pos.y}, via = via, popups = n, opened = LAST.opened or nil,
            error = not okc and ('the click failed: ' .. tostring(err):sub(1, 160)) or nil}
end

function last() return LAST end
