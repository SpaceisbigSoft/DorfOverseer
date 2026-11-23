-- gui/ai-overseer-culture: the control panel's Needs you tab, the Culture
-- tab's words, the Camera tab and the Culture tab (the fort's style, what
-- it learned, the wipe).
--
-- (r9) A part of gui/ai-overseer, not a script of its own: gui/ai-overseer.lua
-- loads it into its own environment, so every name here is
-- reqscript('gui/ai-overseer').name, as when it was one file.

if not OVERSEER_PART_LOCALS then qerror('gui/ai-overseer-culture is a part of gui/ai-overseer; run gui/ai-overseer') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['gui/ai-overseer-culture'] = '0.105.72'   -- (0.105.26) bumped with BRIDGE_VERSION

local dialogs, widgets, S = OVERSEER_PART_LOCALS.dialogs, OVERSEER_PART_LOCALS.widgets, OVERSEER_PART_LOCALS.S   -- (r9) the hub's locals

---------------------------------------------------------------------------
-- The Needs you tab: what the AI can't do itself and asks the player to set
-- up (a civilian-alert burrow, linking the gate lever, a uniform...).
---------------------------------------------------------------------------

NeedsPage = defclass(NeedsPage, widgets.Panel)
NeedsPage.ATTRS{panel = DEFAULT_NIL}

function NeedsPage:init()
    self:addviews{
        widgets.WrappedLabel{view_id = 'text', frame = {t = 0, l = 0, r = 2, b = 0},
                             auto_height = false, text_to_wrap = ''},
    }
    self:refresh()
end

function NeedsPage:refresh()
    local ok, st = pcall(reqscript, 'ai-status')
    local s = ok and st.STATUS or nil
    local lines = {'Things the AI can\'t do itself and needs you to set up in the game.',
                   'They disappear here once they\'re done (at the AI\'s next check).', ''}
    if not s then
        table.insert(lines, 'The overseer hasn\'t reported yet: start brain\\overseer.py.')
    elseif #(s.todo or {}) == 0 then
        table.insert(lines, 'Nothing needs you right now.')
    else
        for i, t in ipairs(s.todo) do
            table.insert(lines, ('%d. %s'):format(i, t))
            table.insert(lines, '')
        end
    end
    if s and s.date then table.insert(lines, ''); table.insert(lines, 'As of ' .. s.date .. '.') end
    self.subviews.text.text_to_wrap = lines
end

---------------------------------------------------------------------------
-- The Culture tab: the fort's building style, written into the save by the
-- overseer (read only here; the sliders and the fort's history shape it).
---------------------------------------------------------------------------

local CULTURE_KEY = 'ai-overseer/culture'
local HALL_TEXT = {plain = 'square and practical', rounded = 'rounded corners', pillared = 'grand, with pillars',
                   -- (D0) the Design track's four
                   octagonal = 'octagonal, corners cut', round = 'round', cruciform = 'cross-shaped',
                   nave = 'a long nave between two aisles of pillars'}
local SMOOTH_TEXT = {[0] = 'rough rock', 'smoothed floors', 'smoothed floors and walls',
                     'smoothed and engraved halls'}
local PALETTE_TEXT = {any = 'whatever stone is plentiful', dark = 'dark stone', light = 'pale stone',
                      warm = 'warm-coloured stone', cool = 'cool-coloured stone', precious = 'the most valuable stone',
                      purpose = 'a stone for each kind of furniture', wood = 'wood where it will do'}
local TEMPLE_TEXT = {none = 'none wanted', shrine = 'a shrine', grand = 'a grand temple'}

---------------------------------------------------------------------------
-- (0.104.90) The Camera tab: what the camera director is showing, what it
-- showed lately (pick one to go back there), next and stay.
---------------------------------------------------------------------------

CameraPage = defclass(CameraPage, widgets.Panel)
CameraPage.ATTRS{panel = DEFAULT_NIL}

local function camera_module()
    local ok, C = pcall(reqscript, 'ai-camera')
    return ok and C or nil
end

function CameraPage:init()
    self:addviews{
        widgets.WrappedLabel{view_id = 'head', frame = {t = 0, l = 0, r = 2, h = 5},
                             auto_height = false, text_to_wrap = ''},
        widgets.Label{frame = {t = 5, l = 0}, text = {{text = 'What it showed lately (Enter: go back there; it stays until Next):', pen = COLOR_GREY}}},
        widgets.List{view_id = 'list', frame = {t = 6, l = 0, r = 2, b = 2},
                     on_submit = function(idx)
                         local C = camera_module()
                         if C then C.go(idx) end
                         self:refresh()
                     end},
        widgets.HotkeyLabel{frame = {b = 0, l = 0}, key = 'CUSTOM_SHIFT_N', label = 'Next thing', auto_width = true,
                            on_activate = function() local C = camera_module(); if C then C.skip() end; self:refresh() end},
        widgets.HotkeyLabel{frame = {b = 0, l = 20}, key = 'CUSTOM_SHIFT_Y', auto_width = true,
                            label = function()
                                local C = camera_module()
                                return (C and C.status().pinned) and 'Let it move on' or 'Stay here'
                            end,
                            on_activate = function() local C = camera_module(); if C then C.stay() end; self:refresh() end},
    }
    self:refresh()
end

function CameraPage:refresh()
    local C = camera_module()
    local s = C and C.status() or nil
    local lines = {}
    if not s then
        lines = {'The camera director isn\'t loaded.'}
    else
        local mode = ({on = 'on: it follows what happens and tours between', tour = 'tour only',
                       off = 'off'})[s.mode] or tostring(s.mode)
        table.insert(lines, 'Camera: ' .. mode .. '. It runs while the keeper runs unattended (the Rules tab sets it and its pace).')
        table.insert(lines, s.showing and ('Showing: ' .. s.showing .. (s.pinned and ' (staying here)' or ''))
            or 'Showing nothing yet.')
        if s.held then table.insert(lines, 'Waiting: ' .. s.held) end
        table.insert(lines, ('In the game: %s the next thing, %s stay here (again to let go).'):format(s.keys.skip, s.keys.stay))
    end
    self.subviews.head.text_to_wrap = lines
    local choices = {}
    for _, h in ipairs(s and s.history or {}) do
        table.insert(choices, {text = {{text = ('%-18s'):format(h.date or ''), pen = COLOR_GREY},
                                       {text = dfhack.utf2df(h.label or '')}}})
    end
    if #choices == 0 then choices = {{text = 'Nothing yet: fights, arrivals, moods and the like are kept here.'}} end
    self.subviews.list:setChoices(choices)
end

CulturePage = defclass(CulturePage, widgets.Panel)
CulturePage.ATTRS{panel = DEFAULT_NIL}

function CulturePage:init()
    self.learned = false        -- false: the fort's culture; true: what the AI has learned
    self:addviews{
        -- fills the page and scrolls (mouse wheel) when the history gets long
        widgets.WrappedLabel{view_id = 'text', frame = {t = 0, l = 0, r = 2, b = 2},
                             auto_height = false, text_to_wrap = ''},
        widgets.HotkeyLabel{
            frame = {b = 0, l = 0, w = 36},
            key = 'CUSTOM_SHIFT_V',
            label = function() return self.learned and 'Back to the fort\'s culture' or 'What the AI has learned' end,
            on_activate = function()
                self.learned = not self.learned
                self:refresh()
                self:updateLayout()
            end,
        },
        widgets.HotkeyLabel{
            frame = {b = 0, l = 38},
            key = 'CUSTOM_SHIFT_W',
            label = 'Wipe what it learned',
            auto_width = true,
            visible = function() return self.learned end,
            on_activate = self:callback('confirm_wipe'),
        },
    }
    self:refresh()
end

function CulturePage:confirm_wipe()
    local choices = {
        {text = 'This fort only (lessons from your other forts are kept for them)', all = false},
        {text = 'This fort and the lessons shared by all your forts', all = true},
    }
    dialogs.showListPrompt('Wipe what the AI learned',
        'Forget your preferences and lessons, the self-tuned targets and the outcome log?\n'
        .. 'The overseer clears them at its next check.',
        COLOR_WHITE, choices,
        function(_, choice)
            if type(choice) ~= 'table' then return end
            local key = choice.all and 'wipe_learned_all' or 'wipe_learned'
            local p = self.panel
            p.settings[key] = (math.tointeger(tonumber(p.settings[key])) or 0) + 1
            p:persist()
            self.wipe_asked = choice.all and 'all' or 'fort'
            self:refresh()
            self:updateLayout()
        end)
end

-- What the AI has learned: written into the save by the overseer (read only
-- here, apart from the wipe).
local LEARNED_KEY = 'ai-overseer/learned'

function CulturePage:learned_lines()
    local l = dfhack.persistent.getSiteData(LEARNED_KEY, nil)
    local lines = {}
    if self.wipe_asked then
        table.insert(lines, ('Wipe asked for (%s): the overseer clears it at its next check.'):format(
            self.wipe_asked == 'all' and 'this fort and all your forts\' lessons' or 'this fort'))
        table.insert(lines, '')
    end
    if type(l) ~= 'table' then
        table.insert(lines, 'Nothing learned yet.')
        table.insert(lines, '')
        table.insert(lines, 'The AI learns from what you decline, undo or correct (a No in co-pilot, an AI '
            .. 'pasture you remove, a slider you move right after it acts), tunes a few targets to this fort, '
            .. 'and judges its own decisions by the fort\'s numbers. It appears here once the overseer has '
            .. 'run on autopilot.')
        return lines
    end
    -- the fort's memory (timeline, atlas, chronicle): shown first, when there is any
    local function section(title, list, indent)
        if type(list) ~= 'table' or #list == 0 then return end
        table.insert(lines, title)
        for _, x in ipairs(list) do table.insert(lines, (indent or '  ') .. tostring(x)) end
        table.insert(lines, '')
    end
    section('TRENDS  (this season against the last, from the fort\'s daily numbers)', l.trends)
    section('NOTABLE PLACES  (where things happened)', l.places)
    section('THE FORT\'S STORY', l.story)
    table.insert(lines, 'WHAT YOU DON\'T WANT  (from your corrections; two of a kind make a lesson)')
    local prefs = type(l.prefs) == 'table' and l.prefs or {}
    if #prefs == 0 then table.insert(lines, '  Nothing yet.') end
    for _, p in ipairs(prefs) do
        table.insert(lines, ('  %s%s: %s'):format(tostring(p.text),
            p.lesson and '  [lesson]' or (p.inherited and '  [from your other forts]' or ''), tostring(p.effect)))
        if p.how and p.how ~= '' then table.insert(lines, '      ' .. tostring(p.how)) end
    end
    table.insert(lines, '')
    table.insert(lines, 'TARGETS TUNED TO THIS FORT  (slowly, within fixed bounds)')
    local tuned = type(l.tuned) == 'table' and l.tuned or {}
    if #tuned == 0 then table.insert(lines, '  None moved yet: the starting guesses fit so far.') end
    for _, t in ipairs(tuned) do
        table.insert(lines, ('  %s: %s (started at %s)'):format(tostring(t.name), tostring(t.value), tostring(t.default)))
        if t.why and t.why ~= '' then
            table.insert(lines, ('      %s%s'):format(t.why, t.date ~= '' and (' (' .. t.date .. ')') or ''))
        end
    end
    table.insert(lines, '')
    table.insert(lines, 'HOW ITS DECISIONS TURNED OUT  (judged by the fort\'s numbers, no tokens)')
    local lessons = type(l.lessons) == 'table' and l.lessons or {}
    for _, x in ipairs(lessons) do table.insert(lines, '  ' .. tostring(x)) end
    local verdicts = type(l.verdicts) == 'table' and l.verdicts or {}
    if #verdicts == 0 and #lessons == 0 then table.insert(lines, '  Nothing judged yet.') end
    for _, x in ipairs(verdicts) do table.insert(lines, '  ' .. tostring(x)) end
    local waiting = type(l.waiting) == 'table' and l.waiting or {}
    if #waiting > 0 then
        table.insert(lines, '  Still to judge:')
        for _, x in ipairs(waiting) do table.insert(lines, '    ' .. tostring(x)) end
    end
    local log = type(l.log) == 'table' and l.log or {}
    if #log > 0 then
        table.insert(lines, '')
        table.insert(lines, 'LATELY')
        for _, x in ipairs(log) do table.insert(lines, '  ' .. tostring(x)) end
    end
    return lines
end

function CulturePage:refresh()
    if self.learned then
        self.subviews.text.text_to_wrap = self:learned_lines()
        return
    end
    local c = dfhack.persistent.getSiteData(CULTURE_KEY, nil)
    local lines = {}
    if type(c) ~= 'table' or type(c.profile) ~= 'table' then
        lines = {'No culture recorded yet.', '',
                 'It appears here once the overseer has run on autopilot. It follows your trait sliders '
                 .. '(mainly Grandeur, Piety, Fortification, Greed and Outsiders) and changes with what '
                 .. 'happens to the fort.'}
    else
        local pr = c.profile
        if type(c.phase) == 'string' and c.phase ~= '' then
            table.insert(lines, 'PHASE  ' .. c.phase)
            table.insert(lines, '')
        end
        local plan = type(c.plan) == 'table' and c.plan or {}
        if #plan > 0 then
            -- the master plan: one design for the whole fort (brain/masterplan.py)
            table.insert(lines, 'THE MASTER PLAN  (drawn once; new eras add wings)')
            for _, x in ipairs(plan) do table.insert(lines, '  ' .. tostring(x)) end
            table.insert(lines, '')
        end
        -- (D0) the fort's design language (brain/design.py lines), when it has one
        local design = type(c.design) == 'table' and c.design or {}
        if #design > 0 then
            table.insert(lines, 'THE DESIGN LANGUAGE  (Design on the AI & tokens tab: '
                .. (S.DESIGN_NAMES[self.panel.settings.design] or 'Scripts') .. ')')
            for i, x in ipairs(design) do
                if i > 6 then break end
                table.insert(lines, '  ' .. tostring(x))
            end
            table.insert(lines, '')
        end
        table.insert(lines, 'STYLE GUIDE')
        table.insert(lines, '  ' .. (c.guide ~= '' and c.guide or '(none yet)'))
        table.insert(lines, '')
        local choices = type(c.choices) == 'table' and c.choices or {}
        if #choices > 0 then
            -- the weights engine: each area's choice and what pushed it
            table.insert(lines, 'CHOICES  (what the sliders and the fort\'s history chose, and why)')
            for _, ch in ipairs(choices) do
                table.insert(lines, ('  %s: %s%s'):format(tostring(ch.name), tostring(ch.choice),
                    ch.by_ai and '  [AI]' or ''))
                table.insert(lines, '      ' .. (ch.by_ai and 'AI strategist: ' or '') .. tostring(ch.why or '')
                    .. (ch.later and ch.later ~= '' and ('  (' .. ch.later .. ')') or ''))
            end
            if c.stone then table.insert(lines, '  Signature stone: ' .. c.stone) end
        else
            table.insert(lines, 'HOW NEW LEVELS ARE BUILT')
            table.insert(lines, '  Halls: ' .. (HALL_TEXT[pr.hall] or tostring(pr.hall)))
            table.insert(lines, '  Finish: ' .. (SMOOTH_TEXT[pr.smooth] or tostring(pr.smooth)))
            table.insert(lines, ('  Statues per hall: %s'):format(tostring(pr.statues)))
            table.insert(lines, '  Furniture: ' .. (PALETTE_TEXT[pr.palette] or tostring(pr.palette))
                .. (c.stone and (' (' .. c.stone .. ')') or ''))
            table.insert(lines, '  Doors closing off each new level: ' .. (pr.entry_doors and 'yes' or 'no'))
            table.insert(lines, '  Temple: ' .. (TEMPLE_TEXT[pr.temple] or tostring(pr.temple)))
        end
        table.insert(lines, '')
        table.insert(lines, 'QUIRKS  (earned by the fort, never chosen)')
        local quirks = type(c.quirks) == 'table' and c.quirks or {}
        if #quirks == 0 then
            table.insert(lines, '  None yet. A fort earns quirks when its sliders lean far one way for a season')
            table.insert(lines, '  and the right things happen to it.')
        end
        for _, q in ipairs(quirks) do
            table.insert(lines, ('  %s  (since year %s: %s)'):format(tostring(q.name), tostring(q.since), tostring(q.why)))
            table.insert(lines, '      ' .. tostring(q.does))
            table.insert(lines, '      Fades if: ' .. tostring(q.fade))
        end
        if type(pr.memorials) == 'table' and #pr.memorials > 0 then
            table.insert(lines, '  Memorial halls still owed: ' .. table.concat(pr.memorials, ', '))
        end
        table.insert(lines, '')
        table.insert(lines, ('HISTORY  Great beasts slain: %d   Sieges survived: %d'):format(
            tonumber(c.beasts_slain) or 0, tonumber(c.sieges) or 0))
        table.insert(lines, '')
        table.insert(lines, 'ERAS')
        local eras = type(c.eras) == 'table' and c.eras or {}
        if #eras == 0 then table.insert(lines, '  (none yet)') end
        for _, e in ipairs(eras) do
            table.insert(lines, ('  Year %s: %s'):format(tostring(e.year), tostring(e.title)))
        end
        table.insert(lines, '')
        table.insert(lines, 'Shaped by your trait sliders and the fort\'s history; the AI strategist may refine it.')
    end
    self.subviews.text.text_to_wrap = lines
end

OVERSEER_PART_LOCALS.CULTURE_KEY = CULTURE_KEY   -- (r9) handed back: the window (in the hub) reads it
