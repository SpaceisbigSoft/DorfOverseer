-- gui/ai-overseer: the AI Overseer's control panel.
--
-- Open it in fortress mode with Ctrl-Shift-O, or type gui/ai-overseer in the
-- DFHack launcher. Settings save automatically with the fort.
--@ module = true

local dialogs = require('gui.dialogs')
local gui = require('gui')
local widgets = require('gui.widgets')

local S = reqscript('ai-overseer-settings')

local NAME_W = 24      -- trait name column
local SLIDER_L = 25    -- slider starts here
local SLIDER_W = 67    -- 21 stops x 3 columns + 7 for the end caps
local VALUE_L = SLIDER_L + SLIDER_W + 1
local EXTREME_L = VALUE_L + 6
local EFFECTIVE_L = EXTREME_L + 13
local NUM_STOPS = (S.TRAIT_MAX - S.TRAIT_MIN) // S.TRAIT_STEP + 1  -- 21


local function fmt_signed(v) return v > 0 and ('+' .. v) or tostring(v) end

local function fmt_tokens(n)
    if n == 0 then return 'off' end
    if n >= 1000000 then return ('%gM'):format(n / 1000000) end
    if n >= 1000 then return ('%gk'):format(n / 1000) end
    return tostring(n)
end

-- 47312 -> "47,312"
local function fmt_count(n)
    local s = tostring(math.floor(n or 0))
    local out = s:reverse():gsub('(%d%d%d)', '%1,'):reverse()
    return (out:gsub('^,', ''))
end

local function options_from(list, label_fn)
    local out = {}
    for _, v in ipairs(list) do table.insert(out, {label = label_fn(v), value = v}) end
    return out
end

---------------------------------------------------------------------------
-- One tab of traits
---------------------------------------------------------------------------

TraitPage = defclass(TraitPage, widgets.Panel)
TraitPage.ATTRS{
    group = DEFAULT_NIL,
    panel = DEFAULT_NIL, -- the OverseerWindow, which owns the settings
}

function TraitPage:init()
    local p = self.panel
    local views = {
        widgets.Label{frame = {t = 0, l = 0}, text = {{text = 'Trait', pen = COLOR_GREY}}},
        widgets.Label{frame = {t = 0, l = SLIDER_L}, text = {{text = '-100', pen = COLOR_GREY}}},
        widgets.Label{frame = {t = 0, l = SLIDER_L + SLIDER_W // 2 - 1}, text = {{text = '0', pen = COLOR_GREY}}},
        widgets.Label{frame = {t = 0, l = SLIDER_L + SLIDER_W - 5}, text = {{text = '+100', pen = COLOR_GREY}}},
        widgets.Label{frame = {t = 0, l = VALUE_L}, text = {{text = 'Value', pen = COLOR_GREY}}},
        widgets.Label{frame = {t = 0, l = EXTREME_L}, text = {{text = 'Extreme (x2)', pen = COLOR_GREY}}},
    }
    self.toggles = {}
    for i, trait in ipairs(self.group.traits) do
        local id, row = trait.id, 2 * i
        table.insert(views, widgets.Label{
            frame = {t = row, l = 0, w = NAME_W},
            text = {{text = trait.name, pen = function()
                return p.selected == id and COLOR_YELLOW or COLOR_WHITE
            end}},
            on_click = function() p:select(id) end,
        })
        table.insert(views, widgets.Slider{
            frame = {t = row, l = SLIDER_L, w = SLIDER_W},
            num_stops = NUM_STOPS,
            get_idx_fn = function() return p:slider_idx(id) end,
            on_change = function(idx) p:set_from_slider(id, idx) end,
        })
        table.insert(views, widgets.Label{
            frame = {t = row, l = VALUE_L, w = 5},
            text = {{text = function() return ('%4s'):format(fmt_signed(p:trait(id).value)) end,
                     pen = function() return p:trait(id).value == 0 and COLOR_GREY or COLOR_WHITE end}},
            on_click = function() p:select(id) end,
        })
        local toggle = widgets.ToggleHotkeyLabel{
            frame = {t = row, l = EXTREME_L, w = 12},
            label = 'Extreme',
            options = {{label = 'On', value = true, pen = COLOR_LIGHTRED},
                       {label = 'Off', value = false, pen = COLOR_GREY}},
            initial_option = p:trait(id).extreme,
            on_change = function(val) p:set_extreme(id, val) end,
        }
        self.toggles[id] = toggle
        table.insert(views, toggle)
        table.insert(views, widgets.Label{
            frame = {t = row, l = EFFECTIVE_L, w = 6},
            text = {{text = function()
                local t = p:trait(id)
                return t.extreme and ('= ' .. fmt_signed(S.effective(t))) or ''
            end, pen = COLOR_LIGHTRED}},
        })
    end
    self:addviews(views)
end

function TraitPage:refresh()
    for id, toggle in pairs(self.toggles) do
        toggle:setOption(self.panel:trait(id).extreme, false)
    end
end

---------------------------------------------------------------------------
-- The AI & tokens tab
---------------------------------------------------------------------------

AIPage = defclass(AIPage, widgets.Panel)
AIPage.ATTRS{panel = DEFAULT_NIL}

local MODEL_WORDS = {small = 'small model', large = 'large model', top = 'largest model'}

function AIPage:init()
    local p = self.panel
    local function plan()
        local sl = p.settings.ai_sliders
        return S.ai_plan(S.effective(sl.ai_frequency), S.effective(sl.ai_effort))
    end
    local views = {
        widgets.Label{frame = {t = 0, l = 0}, text = {
            {text = 'How often the AI strategist reviews the fort, and how long it thinks each time.',
             pen = COLOR_GREY},
        }},
    }
    self.toggles = {}
    for i, a in ipairs(S.AI_SLIDERS) do
        local id, row = a.id, 2 * i
        table.insert(views, widgets.Label{
            frame = {t = row, l = 0, w = NAME_W},
            text = {{text = a.name, pen = function() return p.selected == id and COLOR_YELLOW or COLOR_WHITE end}},
            on_click = function() p:select(id) end,
        })
        table.insert(views, widgets.Slider{
            frame = {t = row, l = SLIDER_L, w = SLIDER_W},
            num_stops = NUM_STOPS,
            get_idx_fn = function() return p:slider_idx(id) end,
            on_change = function(idx) p:set_from_slider(id, idx) end,
        })
        table.insert(views, widgets.Label{
            frame = {t = row, l = VALUE_L, w = 5},
            text = {{text = function() return ('%4s'):format(fmt_signed(p:trait(id).value)) end,
                     pen = function() return p:trait(id).value == 0 and COLOR_GREY or COLOR_WHITE end}},
            on_click = function() p:select(id) end,
        })
        local toggle = widgets.ToggleHotkeyLabel{
            frame = {t = row, l = EXTREME_L, w = 12},
            label = 'Extreme',
            options = {{label = 'On', value = true, pen = COLOR_LIGHTRED},
                       {label = 'Off', value = false, pen = COLOR_GREY}},
            initial_option = p:trait(id).extreme,
            on_change = function(val) p:set_extreme(id, val) end,
        }
        self.toggles[id] = toggle
        table.insert(views, toggle)
        table.insert(views, widgets.Label{
            frame = {t = row, l = EFFECTIVE_L, w = 8},       -- (r5) inside the 120 columns: "Very " shown as "V. "
            text = {{text = function() return (S.slider_word(a, S.effective(p:trait(id))):gsub('^Very ', 'V. ')) end,
                     pen = COLOR_LIGHTCYAN}},
        })
        table.insert(views, widgets.Label{
            frame = {t = row + 1, l = SLIDER_L},
            text = {{text = ('%s  <-  Normal  ->  %s'):format(a.low, a.high),
                     pen = COLOR_GREY}},
        })
    end
    -- (D0) the Design selector, under the two sliders: who designs how the
    -- fort looks (independent of what the AI may do, below)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'design',
        frame = {t = 7, l = 0, w = 46},
        label = 'Design (who designs the look):',
        label_width = 32,
        options = (function()
            local out = {}
            for _, m in ipairs(S.DESIGN_MODES) do
                table.insert(out, {label = S.DESIGN_NAMES[m], value = m,
                                   pen = m == 'scripts' and COLOR_GREY or COLOR_LIGHTCYAN})
            end
            return out
        end)(),
        initial_option = p.settings.design or S.DESIGN_DEFAULT,
        on_change = function(v) p:set_field('design', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = 8, l = 2}, text = {
        {text = function()
            local d = p.settings.design
            return (S.DESIGN_NAMES[d] or S.DESIGN_NAMES[S.DESIGN_DEFAULT]) .. ': '
                .. (S.DESIGN_WORDS[d] or S.DESIGN_WORDS[S.DESIGN_DEFAULT])
        end, pen = COLOR_WHITE},
    }})
    table.insert(views, widgets.Label{frame = {t = 9, l = 2}, text = {
        {text = S.DESIGN_TOKENS .. '. Switching down removes nothing.', pen = COLOR_GREY},
    }})
    table.insert(views, widgets.Label{frame = {t = 10, l = 0}, text = {
        {text = function()
            local pl = plan()
            return ('A routine review every %d days, and up to %s event reviews a month'):format(
                pl.interval_days, ('%g'):format(math.floor(pl.events_per_month * 100 + 0.5) / 100))
        end, pen = COLOR_GREY},
    }})
    table.insert(views, widgets.Label{frame = {t = 11, l = 0}, text = {
        {text = function()
            local pl = plan()
            local function think(n) return n > 0 and ('thinks up to %s'):format(fmt_tokens(n)) or 'no extra thinking' end
            return ('Routine: %s, %s.   Events: %s, %s.'):format(MODEL_WORDS[pl.model_routine],
                think(pl.thinking_routine), MODEL_WORDS[pl.model_events], think(pl.thinking_events))
        end, pen = COLOR_GREY},
    }})
    table.insert(views, widgets.Label{frame = {t = 12, l = 0}, text = {
        {text = function()
            local pl = plan()
            return ('Estimated cost: about %s tokens a review, about %s reviews and %s tokens per in-game year'):format(
                fmt_tokens(math.floor(pl.est_routine / 100 + 0.5) * 100), pl.reviews_per_year,
                fmt_tokens(math.floor(pl.tokens_per_year / 1000 + 0.5) * 1000))
        end, pen = COLOR_WHITE},
    }})
    table.insert(views, widgets.Label{frame = {t = 13, l = 0}, text = {
        {text = function()
            local ok, st = pcall(reqscript, 'ai-status')
            local t = ok and st.STATUS and st.STATUS.tokens
            if not t then return 'Token use shows here while the overseer runs with --ai.' end
            return ('Now: %s tokens saved, %s used today, %s used in total'):format(
                fmt_count(t.saved), fmt_count(t.today), fmt_count(t.total))
        end, pen = COLOR_CYAN},
    }})
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'real_cap',
        frame = {t = 15, l = 0, w = 44},
        label = 'Cap per real-world day:',
        label_width = 30,
        options = options_from(S.REAL_DAY_CAP_OPTIONS, fmt_tokens),
        initial_option = p.settings.real_day_token_cap,
        on_change = function(v) p:set_field('real_day_token_cap', v) end,
    })
    table.insert(views, widgets.WrappedLabel{
        frame = {t = 17, l = 0, r = 2},
        text_to_wrap = 'Longer thinking uses larger models and more tokens per review; more often means more '
            .. 'reviews. Big events (sieges, beasts, deaths) can add a review between routine ones. The '
            .. 'real-world cap is a hard ceiling whatever happens in game. Estimates assume a normal fort '
            .. 'report; the actual use shows above.',
        text_pen = COLOR_GREY,
    })
    self:addviews(views)
    self:addviews{
        widgets.Label{frame = {t = 22, l = 0}, text = {
            {text = 'The strategist runs when the overseer is started with --ai (see docs\\ai-setup.md).',
             pen = COLOR_GREY},
        }},
        widgets.CycleHotkeyLabel{
            view_id = 'mode',
            frame = {t = 23, l = 0, w = 70},
            label = 'What the AI may do:',
            label_width = 30,
            options = (function()
                local out = {}
                for _, m in ipairs(S.MODES) do table.insert(out, {label = S.MODE_NAMES[m], value = m}) end
                return out
            end)(),
            initial_option = p.settings.mode,
            on_change = function(v) p:set_field('mode', v) end,
        },
        widgets.ToggleHotkeyLabel{
            view_id = 'save_first',
            frame = {t = 24, l = 0, w = 50},
            label = 'Save the game before each new level:',
            label_width = 38,
            initial_option = p.settings.save_before_projects,
            on_change = function(v) p:set_field('save_before_projects', v) end,
        },
        widgets.ToggleHotkeyLabel{
            view_id = 'ai_chronicle',
            frame = {t = 25, l = 0, w = 70},
            label = ('AI-written story each season (~%s tokens):'):format(fmt_tokens(S.STORY_TOKENS)),
            label_width = 46,
            initial_option = p.settings.ai_chronicle,
            on_change = function(v) p:set_field('ai_chronicle', v) end,
        },
        widgets.Label{frame = {t = 27, l = 0}, text = {
            {text = 'Ctrl-Shift-H halts or resumes the AI at any time. Its on-screen panel shows what it does.',
             pen = COLOR_GREY},
        }},
    }
end

function AIPage:refresh()
    local s = self.panel.settings
    for id, toggle in pairs(self.toggles) do
        toggle:setOption(self.panel:trait(id).extreme, false)
    end
    self.subviews.real_cap:setOption(s.real_day_token_cap, false)
    self.subviews.mode:setOption(s.mode, false)
    self.subviews.design:setOption(s.design or S.DESIGN_DEFAULT, false)     -- (D0)
    self.subviews.save_first:setOption(s.save_before_projects, false)
    self.subviews.ai_chronicle:setOption(s.ai_chronicle, false)
end

---------------------------------------------------------------------------
-- (r9) The rest of the panel's tabs lives in parts beside this file, in
-- lua/gui/ (gui/ai-overseer-<part>.lua):
--
-- gui/ai-overseer-rules    the Rules tab and the Army tab, and their refresh
-- gui/ai-overseer-culture  the Needs you tab, the Culture tab's words, the
--                          Camera tab, the Culture tab
--
-- Each is loaded into THIS script's environment (as ai-gates loads its
-- parts), so every name stays reqscript('gui/ai-overseer').<name> (RulesPage,
-- CulturePage...), and the window below (in this file, as it was) finds
-- them. This file's locals the parts use go to them in OVERSEER_PART_LOCALS
-- (each takes them back as locals of its own): the same modules and tables,
-- none reassigned after this line. The culture part hands CULTURE_KEY back.
-- The parts are loaded each time this file runs (as a command or by
-- reqscript), as its classes were defined each time; DFHack reloads a
-- module when its own file changes: a change to a part alone is picked up
-- once gui/ai-overseer.lua is touched too, or the game restarts.
---------------------------------------------------------------------------
OVERSEER_PART_LOCALS = {dialogs = dialogs, widgets = widgets, S = S}

PARTS = {'rules', 'culture'}
-- each part marks the version it came with (the bridge's `version` lists one
-- that differs from BRIDGE_VERSION); started afresh at each load, so a part
-- that failed to load shows as unmarked
PART_VERSIONS = {['gui/ai-overseer'] = '0.105.124'}   -- (0.105.26) bumped with BRIDGE_VERSION

-- a part's file beside this one (lua/gui/<file>.lua), else DFHack's search
-- for it by its script name (gui/<file>)
local function part_path(file, name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. file .. '.lua', 'r')
        if f then f:close() return dir .. file .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/gui_behaviour.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'gui/ai-overseer-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path('ai-overseer-' .. part, name)
        if not path then error('gui/ai-overseer: ' .. name .. '.lua is missing (it goes beside ai-overseer.lua in gui/)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
local CULTURE_KEY = OVERSEER_PART_LOCALS.CULTURE_KEY   -- (r9) the culture part's, for the window
-- (r9) the parts end here; what follows stood at the end of the one file

---------------------------------------------------------------------------
-- The window
---------------------------------------------------------------------------

OverseerWindow = defclass(OverseerWindow, widgets.Window)
OverseerWindow.ATTRS{
    frame_title = 'AI Overseer: fortress personality',
    frame = {w = EFFECTIVE_L + 10, h = 42},
    resizable = true,
    resize_min = {w = EFFECTIVE_L + 10, h = 40},
}

-- (0.105.33 review) The window's settings and the ones saved under it.
-- The keeper (act_set_rules, act_apply_preset) may save while the window is
-- open: a save from here writes only what the window changed since it last
-- read them (a deep diff against `base`) onto a fresh read, so a Rules
-- switch the keeper set is not turned back by the next slider move.
local function deep_copy(v)
    if type(v) ~= 'table' then return v end
    local out = {}
    for k, x in pairs(v) do out[k] = deep_copy(x) end
    return out
end

local function deep_equal(a, b)
    if type(a) ~= 'table' or type(b) ~= 'table' then return a == b end
    for k, x in pairs(a) do if not deep_equal(x, b[k]) then return false end end
    for k in pairs(b) do if a[k] == nil then return false end end
    return true
end

-- every leaf of `cur` that differs from `base`, written into `into`
function merge_changes(cur, base, into)
    for k, v in pairs(cur) do
        local b = nil
        if type(base) == 'table' then b = base[k] end      -- (a false value kept: not `and ... or nil`)
        if type(v) == 'table' and type(b) == 'table' and type(into[k]) == 'table' then
            merge_changes(v, b, into[k])
        elseif not deep_equal(v, b) then
            into[k] = deep_copy(v)
        end
    end
    if type(base) == 'table' then
        for k in pairs(base) do if cur[k] == nil then into[k] = nil end end
    end
    return into
end

function OverseerWindow:reload()
    self.settings = S.load_settings()
    self.base = deep_copy(self.settings)
end

function OverseerWindow:init()
    self:reload()
    self.selected = S.TRAIT_GROUPS[1].traits[1].id

    local labels, pages = {}, {}
    for _, group in ipairs(S.TRAIT_GROUPS) do
        table.insert(labels, group.name)
        table.insert(pages, TraitPage{group = group, panel = self})
    end
    table.insert(labels, 'AI & tokens')
    table.insert(pages, AIPage{panel = self})
    table.insert(labels, 'Rules')
    table.insert(pages, RulesPage{panel = self})
    -- (0.105.33 review) 'Army': ten tabs of #label + 4 columns must fit the
    -- 120 inside on one row (the pages start at t = 3); 'Military' made 123
    table.insert(labels, 'Army')
    table.insert(pages, MilitaryPage{panel = self})
    table.insert(labels, 'Needs you')
    table.insert(pages, NeedsPage{panel = self})
    table.insert(labels, 'Culture')
    table.insert(pages, CulturePage{panel = self})
    table.insert(labels, 'Camera')
    table.insert(pages, CameraPage{panel = self})

    self:addviews{
        widgets.TabBar{
            frame = {t = 0, l = 0},
            labels = labels,
            on_select = function(idx)
                self:reload()            -- (0.105.33 review) what the keeper saved meanwhile
                self.subviews.pages:setSelected(idx)
                self.subviews.pages:getSelectedPage():refresh()
                self:updateLayout()
            end,
            get_cur_page = function() return self.subviews.pages:getSelected() end,
        },
        widgets.Pages{
            view_id = 'pages',
            frame = {t = 3, l = 0, r = 0, b = 9},
            subviews = pages,
        },
        widgets.Divider{frame = {b = 8, h = 1}, frame_style_l = false, frame_style_r = false},
        widgets.Label{
            frame = {b = 6, l = 0},
            text = {{text = function() return self:selected_summary() end}},
        },
        widgets.Label{
            frame = {b = 5, l = 2},
            text = {{text = function() return self:selected_ends() end, pen = COLOR_GREY}},
        },
        widgets.Label{
            frame = {b = 4, l = 2},
            text = {{text = function() return self:selected_now() end, pen = COLOR_LIGHTCYAN}},
        },
        widgets.Label{
            frame = {b = 2, l = 2},
            text = {{text = function() return self:selected_leans() end, pen = COLOR_GREY}},
        },
        widgets.EditField{
            view_id = 'exact',
            frame = {b = 3, l = 0, w = 60},
            label_text = 'Exact value for the selected trait (-100 to 100): ',
            key = 'CUSTOM_CTRL_E',
            on_char = function(ch, text) return ch:match('%d') or (ch == '-' and #text == 0) end,
            on_submit = function(text) self:set_exact(text) end,
        },
        widgets.HotkeyLabel{
            frame = {b = 1, l = 0},
            key = 'CUSTOM_SHIFT_R',
            label = 'Reset trait',
            auto_width = true,
            on_activate = function() self:set_value(self.selected, 0, false) end,
        },
        widgets.HotkeyLabel{
            frame = {b = 1, l = 20},
            key = 'CUSTOM_SHIFT_X',
            label = 'Reset all',
            auto_width = true,
            on_activate = self:callback('confirm_reset_all'),
        },
        widgets.HotkeyLabel{
            frame = {b = 1, l = 38},
            key = 'CUSTOM_SHIFT_S',
            label = 'Save preset',
            auto_width = true,
            on_activate = self:callback('save_preset'),
        },
        widgets.HotkeyLabel{
            frame = {b = 1, l = 58},
            key = 'CUSTOM_SHIFT_L',
            label = 'Load preset',
            auto_width = true,
            on_activate = self:callback('load_preset'),
        },
        widgets.Label{
            frame = {b = 0, l = 0},
            text = {{text = 'Click a trait name to select it. Settings save automatically with this fort.',
                     pen = COLOR_GREY}},
        },
    }
end

function OverseerWindow:trait(id)
    return self.settings.traits[id] or self.settings.ai_sliders[id]
end

function OverseerWindow:select(id)
    self.selected = id
end

function OverseerWindow:persist()
    local fresh = S.load_settings()
    merge_changes(self.settings, self.base or {}, fresh)
    S.save_settings(fresh)
    self.settings = fresh
    self.base = deep_copy(fresh)
end

function OverseerWindow:slider_idx(id)
    local v = self:trait(id).value
    return math.floor((v - S.TRAIT_MIN) / S.TRAIT_STEP + 0.5) + 1
end

function OverseerWindow:set_value(id, value, select)
    value = math.max(S.TRAIT_MIN, math.min(S.TRAIT_MAX, math.tointeger(value) or 0))
    self:trait(id).value = value
    if select ~= false then self.selected = id end
    self:persist()
end

function OverseerWindow:set_from_slider(id, idx)
    self:set_value(id, S.TRAIT_MIN + (idx - 1) * S.TRAIT_STEP)
end

function OverseerWindow:set_extreme(id, on)
    self:trait(id).extreme = on == true
    self.selected = id
    self:persist()
end

function OverseerWindow:set_exact(text)
    local v = math.tointeger(tonumber(text))
    if not v then return end
    self:set_value(self.selected, v)
    self.subviews.exact:setText('')
end

function OverseerWindow:set_field(field, value)
    self.settings[field] = value
    self:persist()
end

function OverseerWindow:selected_summary()
    local def = S.TRAITS_BY_ID[self.selected] or S.AI_SLIDERS_BY_ID[self.selected]
    local t = self:trait(self.selected)
    local ai = S.effective(t)
    local extra = ''
    if self.selected == 'growth' then
        extra = '   ' .. S.growth_text(t)
    elseif S.AI_SLIDERS_BY_ID[self.selected] then
        extra = '   ' .. S.slider_word(def, ai)
    end
    return ('Selected: %s (%s)   value %s%s   the AI sees %s%s'):format(
        def.name, def.group, fmt_signed(t.value), t.extreme and ', Extreme on' or '', fmt_signed(ai), extra)
end

function OverseerWindow:selected_ends()
    local def = S.TRAITS_BY_ID[self.selected] or S.AI_SLIDERS_BY_ID[self.selected]
    return ('-100: %s      +100: %s'):format(def.low, def.high)
end

-- (0.94) What the selected slider does in this fort now, as the overseer
-- last wrote it (brain/temperament.py, through the culture page's data);
-- read from the save at most once a second.
function OverseerWindow:selected_now()
    if not S.TRAITS_BY_ID[self.selected] then return '' end
    local now = dfhack.getTickCount()
    if not self.effects_read or now - self.effects_read > 1000 then
        self.effects_read = now
        local ok, c = pcall(dfhack.persistent.getSiteData, CULTURE_KEY, nil)
        self.effects = ok and type(c) == 'table' and type(c.effects) == 'table' and c.effects or {}
        self.leans = ok and type(c) == 'table' and type(c.leanings) == 'table' and c.leanings or {}
    end
    local e = self.effects[self.selected]
    return 'Now: ' .. (e or '(the overseer shows this after its next cycle)')
end

-- (0.95) What leans the selected slider beyond your setting: this fort's own
-- leaning, the site's and its history's (brain/leanings.py). They tip the
-- style's close calls only; your setting is what the planner reads.
function OverseerWindow:selected_leans()
    if not S.TRAITS_BY_ID[self.selected] then return '' end
    self:selected_now()                     -- (reads the save at most once a second)
    local l = self.leans and self.leans[self.selected]
    return l and ('This fort ' .. l .. ' (style only)') or ''
end

function OverseerWindow:refresh_all()
    for _, page in ipairs(self.subviews.pages.subviews) do
        if page.refresh then page:refresh() end
    end
end

function OverseerWindow:confirm_reset_all()
    dialogs.showYesNoPrompt('Reset all traits',
        'Set every trait back to 0 and turn Extreme off?\nThe AI & tokens settings are kept.',
        COLOR_WHITE,
        function()
            for _, t in pairs(self.settings.traits) do
                t.value, t.extreme = 0, false
            end
            self:persist()
            self:refresh_all()
        end)
end

function OverseerWindow:save_preset()
    dialogs.showInputPrompt('Save preset',
        'Name for this set of traits (letters, numbers, spaces, - and _):', COLOR_WHITE, '',
        function(name)
            local ok, err = S.save_preset(name, self.settings)
            if not ok then dialogs.showMessage('Not saved', err, COLOR_LIGHTRED) end
        end)
end

function OverseerWindow:load_preset()
    local names = S.list_presets()
    if #names == 0 then
        dialogs.showMessage('No presets', 'Save one first with Shift-S.', COLOR_WHITE)
        return
    end
    dialogs.showListPrompt('Load preset', 'Choose a preset. Its traits replace the current ones.',
        COLOR_WHITE, names,
        function(_, choice)
            local name = type(choice) == 'table' and choice.text or choice
            local merged, err = S.apply_preset(name, self.settings, 'window')   -- (0.105.4) its name kept too
            if not merged then
                dialogs.showMessage('Not loaded', err, COLOR_LIGHTRED)
                return
            end
            self.settings = merged
            self:persist()
            self:refresh_all()
        end)
end

OverseerScreen = defclass(OverseerScreen, gui.ZScreen)
OverseerScreen.ATTRS{
    focus_path = 'ai-overseer',
}

function OverseerScreen:init()
    self:addviews{OverseerWindow{}}
end

function OverseerScreen:onDismiss()
    view = nil
end

if dfhack_flags.module then
    return
end

if not dfhack.isMapLoaded() or not dfhack.world.isFortressMode() then
    qerror('The AI Overseer panel needs a loaded fortress.')
end

view = view and view:raise() or OverseerScreen{}:show()
