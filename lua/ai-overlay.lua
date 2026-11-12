-- On-screen panel for the AI Overseer (a DFHack overlay on the main fort
-- screen): what the AI is doing, its last actions and why, the building
-- project, and the co-pilot's questions with Yes/No buttons. Halt/Resume
-- works like Ctrl-Shift-H.
--
-- It's on by default, in the bottom-left corner. Move it with `gui/overlay` (DFHack's overlay editor);
-- hide it with `overlay disable ai-overlay.status`.
--@ module = true

local gui = require('gui')
local widgets = require('gui.widgets')
local overlay = require('plugins.overlay')

local WIDTH = 58
local STALE_SECONDS = 30      -- no check-in for this long: the overseer isn't running

-- Looked up once (not every frame); reqscript keeps the same module table
-- even when the file is reloaded.
local STATUS_MODULE = nil
local function status_module()
    if not STATUS_MODULE then
        local ok, m = pcall(reqscript, 'ai-status')
        STATUS_MODULE = ok and m or nil
    end
    return STATUS_MODULE
end

-- Text from the overseer is UTF-8; the game draws CP437.
local function df_text(s)
    if type(s) ~= 'string' then return '' end
    local ok, t = pcall(dfhack.utf2df, s)
    return ok and t or s
end

local function fit(s, w)
    s = df_text(s)
    return #s > w and (s:sub(1, w - 3) .. '...') or s
end

AIStatusOverlay = defclass(AIStatusOverlay, overlay.OverlayWidget)
AIStatusOverlay.ATTRS{
    desc = 'Shows what the AI Overseer is doing; halt it or answer its questions.',
    default_pos = {x = 1, y = -4},   -- (11 Nov) the bottom-left corner, anchored there when the window is resized (negative y counts from the bottom)
    default_enabled = true,
    viewscreens = 'dwarfmode/Default',
    frame = {w = WIDTH, h = 17},
    overlay_onupdate_max_freq_seconds = 1,
}

function AIStatusOverlay:init()
    local panel = widgets.Panel{
        frame_style = gui.FRAME_MEDIUM,
        frame_background = gui.CLEAR_PEN,
        frame_title = 'AI Overseer',
    }
    local views = {
        -- fixed sizes, no scrolling: the panel must never take the map's keys
        widgets.Label{view_id = 'head', frame = {t = 0, l = 0, r = 9, h = 1},
                      auto_height = false, scroll_keys = {}, text = ''},
        -- (0.104.90) the camera's two buttons, while it runs
        widgets.HotkeyLabel{
            frame = {t = 0, r = 23, w = 6, h = 1}, label = '[Next]', auto_width = false, scroll_keys = {},
            text_pen = COLOR_LIGHTCYAN, visible = function() return self:camera_on() end,
            on_activate = function() self:camera('skip') end,
        },
        widgets.HotkeyLabel{
            frame = {t = 0, r = 9, w = 13, h = 1}, auto_width = false, scroll_keys = {},
            label = function() return self.cam_pinned and '[Move on]' or '[Stay here]' end,
            text_pen = COLOR_LIGHTCYAN, visible = function() return self:camera_on() end,
            on_activate = function() self:camera('stay') end,
        },
        widgets.HotkeyLabel{
            view_id = 'halt', frame = {t = 0, r = 0, w = 8, h = 1},
            label = '[Halt]', auto_width = false, scroll_keys = {},
            on_activate = function() self:toggle_halt() end,
        },
        widgets.Label{view_id = 'body', frame = {t = 1, l = 0, r = 0, h = 11},
                      auto_height = false, scroll_keys = {}, text = ''},
    }
    -- up to 3 questions from the co-pilot, each with Yes / No
    for i = 1, 3 do
        local row = 11 + i
        table.insert(views, widgets.Label{
            view_id = 'ask' .. i, frame = {t = row, l = 0, r = 12, h = 1},
            auto_height = false, scroll_keys = {}, text = '',
            visible = function() return self:pending(i) ~= nil end,
        })
        table.insert(views, widgets.HotkeyLabel{
            frame = {t = row, r = 6, w = 5, h = 1}, label = '[Yes]', auto_width = false, scroll_keys = {},
            text_pen = COLOR_LIGHTGREEN,
            visible = function() return self:pending(i) ~= nil end,
            on_activate = function() self:decide(i, true) end,
        })
        table.insert(views, widgets.HotkeyLabel{
            frame = {t = row, r = 0, w = 4, h = 1}, label = '[No]', auto_width = false, scroll_keys = {},
            text_pen = COLOR_LIGHTRED,
            visible = function() return self:pending(i) ~= nil end,
            on_activate = function() self:decide(i, false) end,
        })
    end
    panel:addviews(views)
    self:addviews{panel}
    self:refresh()
end

local function camera_status()
    local ok, cam = pcall(function() return reqscript('ai-camera').status() end)
    return ok and cam or nil
end

function AIStatusOverlay:camera_on()
    local cam = camera_status()
    self.cam_pinned = cam and cam.pinned or false
    return cam ~= nil and cam.mode ~= nil and cam.mode ~= 'off'
end

function AIStatusOverlay:camera(what)
    pcall(function() local C = reqscript('ai-camera'); if what == 'skip' then C.skip() else C.stay() end end)
    self:refresh()
end

function AIStatusOverlay:pending(i)
    local st = status_module()
    local s = st and st.STATUS
    if not s or type(s.pending) ~= 'table' then return nil end
    local p = s.pending[i]
    if not p then return nil end
    local d = st.DECISIONS[p.id]
    return (d == nil) and p or nil      -- answered: hide it until the overseer acts
end

function AIStatusOverlay:decide(i, yes)
    local p = self:pending(i)
    local st = status_module()
    if p and st then st.decide(p.id, yes) end
    self:refresh()
end

function AIStatusOverlay:toggle_halt()
    local st = status_module()
    if st then st.set_halted(not st.is_halted()) end
    self:refresh()
end

function AIStatusOverlay:refresh()
    local st = status_module()
    if not st then return end
    local halted = st.is_halted()
    local s = st.STATUS
    self.subviews.halt:setLabel(halted and '[Resume]' or '[Halt]')

    local head
    if halted then
        head = {{text = 'HALTED', pen = COLOR_LIGHTRED}, ' - nothing will be changed'}
    elseif not st.LAST_SEEN or os.time() - st.LAST_SEEN > STALE_SECONDS then
        head = {{text = 'not running', pen = COLOR_GREY}, ' - start brain\\overseer.py'}
    elseif not s then
        -- (13c) seen (a status call came) but no report yet: just after a map load
        head = {{text = 'starting', pen = COLOR_GREY}, ' - waiting for the first report'}
    else
        head = {{text = s.mode, pen = COLOR_WHITE}, ' ', {text = s.acting,
                pen = s.acting == 'acting' and COLOR_LIGHTGREEN or COLOR_YELLOW}}
    end
    self.subviews.head:setText(head)

    local lines = {}
    local function line(t, pen) table.insert(lines, {text = fit(t, WIDTH - 4), pen = pen}); table.insert(lines, NEWLINE) end
    if s then
        if s.ai then line(s.ai, COLOR_GREY) end
        local todo = s.todo or {}
        if #todo > 0 then
            line(('Needs you (%d, Ctrl-Shift-O): %s'):format(#todo, todo[1]), COLOR_LIGHTMAGENTA)
        end
        for _, b in ipairs(s.building or {}) do line('Building: ' .. b, COLOR_CYAN) end
        if #(s.last or {}) > 0 then line('Last actions:', COLOR_GREY) end
        for i, t in ipairs(s.last or {}) do
            if i <= (#todo > 0 and 4 or 5) then line(' ' .. t) end
        end
        for _, n in ipairs(s.notes or {}) do line('Note: ' .. n, COLOR_YELLOW) end
        -- (0.104.88) what the camera director shows
        local okc, cam = pcall(function() return reqscript('ai-camera').status() end)
        if okc and cam and cam.mode ~= 'off' and cam.showing then
            line('Camera: ' .. cam.showing .. (cam.held and (' (waiting: ' .. cam.held .. ')') or ''), COLOR_LIGHTCYAN)
            line(('  %s next, %s stay; the AI window\'s Camera tab lists what it showed'):format(
                cam.keys and cam.keys.skip or '', cam.keys and cam.keys.stay or ''), COLOR_GREY)
        end
    else
        line('Waiting for the overseer to report.', COLOR_GREY)
    end
    self.subviews.body:setText(lines)
    for i = 1, 3 do
        local p = self:pending(i)
        self.subviews['ask' .. i]:setText(p and {{text = fit('Ask: ' .. p.text, WIDTH - 16), pen = COLOR_WHITE}} or '')
    end
    if self.frame_parent_rect then self:updateLayout() end
end

-- Clicks anywhere on the panel stay on the panel (not on the map below).
function AIStatusOverlay:onInput(keys)
    if AIStatusOverlay.super.onInput(self, keys) then return true end
    if keys._MOUSE_L and self:getMousePos() then return true end
end

function AIStatusOverlay:overlay_onupdate()
    self:refresh()
end

-- (0.104.90) The camera's caption: what it shows, in large letters across the
-- top of the map for a few seconds after each move (and the why below it).
AICameraCaption = defclass(AICameraCaption, overlay.OverlayWidget)
AICameraCaption.ATTRS{
    desc = 'The camera director\'s caption: what the view is showing.',
    default_pos = {x = 1, y = 1},
    default_enabled = true,
    viewscreens = 'dwarfmode/Default',
    frame = {w = 1, h = 1},
    overlay_onupdate_max_freq_seconds = 0,
}

local CAPTION_PEN = nil
local SUB_PEN = nil

function AICameraCaption:overlay_onupdate()
    local cam = camera_status()
    self.cap = cam and cam.mode ~= 'off' and cam.caption or nil
end

function AICameraCaption:render(dc)
    local c = self.cap
    if not c or not c.text then return end
    CAPTION_PEN = CAPTION_PEN or dfhack.pen.parse{fg = COLOR_WHITE, bg = COLOR_BLUE, bold = true}
    SUB_PEN = SUB_PEN or dfhack.pen.parse{fg = COLOR_LIGHTCYAN, bg = COLOR_BLACK}
    local w = dfhack.screen.getWindowSize()
    local function centred(text, y, pen)
        text = ' ' .. fit(text, w - 20) .. ' '
        dfhack.screen.paintString(pen, math.max(0, (w - #text) // 2), y, text)
    end
    centred(c.text, 3, CAPTION_PEN)
    if c.sub then centred(c.sub, 4, SUB_PEN) end
end

OVERLAY_WIDGETS = {status = AIStatusOverlay, caption = AICameraCaption}
