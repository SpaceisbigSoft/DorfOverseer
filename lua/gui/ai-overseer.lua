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
            frame = {t = row, l = EFFECTIVE_L, w = 12},
            text = {{text = function() return S.slider_word(a, S.effective(p:trait(id))) end,
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
-- The Rules tab: what the planner may build and do on its own.
---------------------------------------------------------------------------

RulesPage = defclass(RulesPage, widgets.Panel)
RulesPage.ATTRS{panel = DEFAULT_NIL}

function RulesPage:init()
    local p = self.panel
    local views = {
        widgets.Label{frame = {t = 0, l = 0}, text = {
            {text = 'What the AI may build and do on its own. Changes apply on its next check.',
             pen = COLOR_GREY},
        }},
        widgets.CycleHotkeyLabel{
            view_id = 'fort_goal',
            frame = {t = 1, l = 0, w = 74},
            label = 'The fort should:',
            label_width = 34,
            options = (function()
                local out = {}
                for _, m in ipairs(S.FORT_GOALS) do table.insert(out, {label = S.FORT_GOAL_NAMES[m], value = m}) end
                return out
            end)(),
            initial_option = p.settings.fort_goal,
            on_change = function(v) p:set_field('fort_goal', v) end,
        },
        widgets.CycleHotkeyLabel{
            view_id = 'memorial_pace',
            frame = {t = 2, l = 0, w = 70},
            label = 'Memorial halls for slain beasts:',
            label_width = 34,
            options = (function()
                local out = {}
                for _, m in ipairs(S.MEMORIAL_PACES) do
                    table.insert(out, {label = S.MEMORIAL_PACE_NAMES[m], value = m})
                end
                return out
            end)(),
            initial_option = p.settings.memorial_pace,
            on_change = function(v) p:set_field('memorial_pace', v) end,
        },
        -- (D0) beside the memorials: how often an Architect fort starts a landmark
        widgets.CycleHotkeyLabel{
            view_id = 'landmark_pace',
            frame = {t = 2, l = 72, w = 46},
            label = 'Landmarks (Architect):',
            label_width = 24,
            options = (function()
                local out = {}
                for _, m in ipairs(S.LANDMARK_PACES) do
                    table.insert(out, {label = S.LANDMARK_PACE_NAMES[m], value = m})
                end
                return out
            end)(),
            initial_option = p.settings.landmark_pace or 'season',
            on_change = function(v) p:set_field('landmark_pace', v) end,
        },
        widgets.ToggleHotkeyLabel{
            view_id = 'set_pop_cap',
            frame = {t = 3, l = 0, w = 60},
            label = 'DF pop cap from Growth/Maintain:',
            label_width = 34,
            initial_option = p.settings.set_pop_cap,
            on_change = function(v) p:set_field('set_pop_cap', v) end,
        },
        widgets.Label{frame = {t = 4, l = 0}, text = {{text = 'Levels the AI may build when needed:'}}},
    }
    for i, l in ipairs(S.OPTIONAL_LEVELS) do
        table.insert(views, widgets.ToggleHotkeyLabel{
            view_id = 'level_' .. l.id,
            frame = {t = 4 + i, l = 2, w = 50},
            label = l.name .. ':',
            label_width = 34,
            initial_option = p.settings.levels[l.id] ~= false,
            on_change = function(v)
                p.settings.levels[l.id] = v
                p:persist()
            end,
        })
    end
    -- (0.104.168) the hospital burrow's switch, beside the Hospital level (the
    -- right-hand column is free; the rows below are full), with its help line
    local hrow = 2
    for i, l in ipairs(S.OPTIONAL_LEVELS) do if l.id == 'hospital' then hrow = i end end
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'hospital_burrow',
        frame = {t = 4 + hrow, l = 56, w = 62},
        label = 'Keep the wounded in an "AI hospital" burrow:',
        label_width = 46,
        initial_option = p.settings.hospital_burrow ~= false,
        on_change = function(v) p:set_field('hospital_burrow', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = 5 + hrow, l = 58}, text = {
        {text = 'patients stay by the beds, drink and food; off: all let out', pen = COLOR_GREY}}})
    -- (0.105.41, 13e) traffic zones on the AI's own levels: the right-hand
    -- column's free rows under the hospital burrow's help line
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'traffic',
        frame = {t = 7 + hrow, l = 56, w = 62},
        label = 'Traffic zones on the AI\'s own levels:',
        label_width = 46,
        initial_option = p.settings.traffic ~= false,
        on_change = function(v) p:set_field('traffic', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = 8 + hrow, l = 58}, text = {
        {text = 'high on its corridors and stairs, low on rooms and fields', pen = COLOR_GREY}}})
    -- (0.104.169) the calm-down burrows' switch, beside the Jail level (the
    -- jail is the other answer to a tantrum), with its help line
    local jrow = 8
    for i, l in ipairs(S.OPTIONAL_LEVELS) do if l.id == 'jail' then jrow = i end end
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'calm_burrow',
        frame = {t = 4 + jrow, l = 56, w = 62},
        label = 'Keep a dwarf in a tantrum in an "AI calm" burrow:',
        label_width = 50,
        initial_option = p.settings.calm_burrow ~= false,
        on_change = function(v) p:set_field('calm_burrow', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = 5 + jrow, l = 58}, text = {
        {text = 'a free bedroom away from the patients, with drink, till calm', pen = COLOR_GREY}}})
    -- (0.105.0) the world outside: tribute asked of the fort, and Make contact
    -- (the right-hand column below the calm-down switch, clear of the left one's rows)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'tribute',
        frame = {t = 7 + jrow, l = 62, w = 56},
        label = 'Tribute a civilisation asks:',
        label_width = 30,
        options = (function()
            local out = {}
            for _, m in ipairs(S.TRIBUTE_CHOICES) do table.insert(out, {label = S.TRIBUTE_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = p.settings.tribute or 'small',
        on_change = function(v) p:set_field('tribute', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'make_contact',
        frame = {t = 8 + jrow, l = 62, w = 46},
        label = 'Appoint a messenger, make contact:',
        label_width = 36,
        initial_option = p.settings.make_contact ~= false,
        on_change = function(v) p:set_field('make_contact', v) end,
    })
    -- (0.105.24, 13b) the AI drives the World screen to send the messenger (a trial: off by default)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'send_messenger',
        frame = {t = 9 + jrow, l = 62, w = 56},
        label = 'Send the messenger by the World screen:',
        label_width = 41,
        initial_option = p.settings.send_messenger == true,
        on_change = function(v) p:set_field('send_messenger', v) end,
    })
    -- (0.105.24) the tavern, temples and library shut to visitors a while: after a
    -- theft (or a visitor's killing), and when the mayor's meetings are mostly visitors
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'heist_lockout',
        frame = {t = 10 + jrow, l = 62, w = 56},
        label = 'Shut to visitors a while after a theft:',
        label_width = 44,
        initial_option = p.settings.heist_lockout ~= false,
        on_change = function(v) p:set_field('heist_lockout', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'shut_to_visitors',
        frame = {t = 11 + jrow, l = 62, w = 56},
        label = 'Shut to visitors when mayor swamped:',
        label_width = 44,
        initial_option = p.settings.shut_to_visitors ~= false,
        on_change = function(v) p:set_field('shut_to_visitors', v) end,
    })
    -- (0.105.30) construction: the surface hall, the gate wings, soil floors
    -- (the right-hand column's free row under the visitors' switches)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'construct',
        frame = {t = 12 + jrow, l = 62, w = 56},
        label = 'Construct halls, gate wings, floors:',
        label_width = 44,
        initial_option = p.settings.construct ~= false,
        on_change = function(v) p:set_field('construct', v) end,
    })
    -- (0.105.33 review) one row up (the blank row under the levels): the
    -- camera pace is the page's last row, 27 of the 28 the window shows
    local t = 5 + #S.OPTIONAL_LEVELS
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'order_supplies',
        frame = {t = t, l = 0, w = 60},
        label = 'Order barrels, pots, bags, hospital supplies:',
        label_width = 46,
        initial_option = p.settings.order_supplies,
        on_change = function(v) p:set_field('order_supplies', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'mood_workshops',
        frame = {t = t + 1, l = 0, w = 60},
        label = 'Build the workshop a strange mood needs:',
        label_width = 46,
        initial_option = p.settings.mood_workshops,
        on_change = function(v) p:set_field('mood_workshops', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'engrave_slabs',
        frame = {t = t + 2, l = 0, w = 60},
        label = 'Memorial slabs for ghosts (autoslab):',
        label_width = 46,
        initial_option = p.settings.engrave_slabs,
        on_change = function(v) p:set_field('engrave_slabs', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'import_smelting',
        frame = {t = t + 3, l = 0, w = 60},
        label = 'Smelt ore when metal runs low:',
        label_width = 46,
        initial_option = p.settings.import_smelting,
        on_change = function(v) p:set_field('import_smelting', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'alert_shelter',
        frame = {t = t + 4, l = 0, w = 60},
        label = 'Set up an "AI shelter" for the alarm:',
        label_width = 46,
        initial_option = p.settings.alert_shelter,
        on_change = function(v) p:set_field('alert_shelter', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'pasture_animals',
        frame = {t = t + 5, l = 0, w = 60},
        label = 'Put grazing animals in a pasture:',
        label_width = 46,
        initial_option = p.settings.pasture_animals,
        on_change = function(v) p:set_field('pasture_animals', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'give_trinkets',
        frame = {t = t + 6, l = 0, w = 60},
        label = 'Give trinkets to dwarves who want to own:',
        label_width = 46,
        initial_option = p.settings.give_trinkets,
        on_change = function(v) p:set_field('give_trinkets', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'water_works',
        frame = {t = t + 7, l = 0, w = 60},
        label = 'Build water works (a cistern, ...):',
        label_width = 46,
        initial_option = p.settings.water_works,
        on_change = function(v) p:set_field('water_works', v) end,
    })
    -- (0.105.0) the water works' own switches, beside "Build water works" (the right-hand column is free there)
    for i, f in ipairs({{'moat', 'A moat from the river at the gate:'},
                        {'magma_workshops', 'Magma workshops (forge, smelter, glass):'},
                        {'irrigation', 'Muddy a stone farm level with water:'}}) do
        table.insert(views, widgets.ToggleHotkeyLabel{
            view_id = f[1],
            frame = {t = t + 6 + i, l = 62, w = 56},
            label = f[2],
            label_width = 42,
            initial_option = p.settings[f[1]] ~= false,
            on_change = function(v) p:set_field(f[1], v) end,
        })
    end
    -- (0.105.4 review) a cavern well may open a cavern nobody has found yet.
    -- (v35 fix) three-state: AI decides (the default: only when the fort is
    -- short of water and has armed soldiers for what comes out), Always, Never
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'open_caverns',
        frame = {t = t + 11, l = 62, w = 56},
        label = 'Cavern well into an unfound cavern:',
        label_width = 42,
        options = {{label = 'AI decides', value = 'ai', pen = COLOR_YELLOW},
                   {label = 'Always', value = 'always', pen = COLOR_GREEN},
                   {label = 'Never', value = 'never', pen = COLOR_RED}},
        initial_option = S.open_caverns_choice(p.settings.open_caverns),
        on_change = function(v) p:set_field('open_caverns', v) end,
    })
    -- (0.105.40, 13e) world cleanup for the game's speed: the right-hand column's
    -- free row t (beside "Order barrels...", under the calm burrow's help line)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'world_cleanup',
        frame = {t = t, l = 62, w = 56},
        label = 'World cleanup (speed):',
        label_width = 23,
        options = (function()
            local out = {}
            for _, m in ipairs(S.WORLD_CLEANUP_CHOICES) do
                table.insert(out, {label = S.WORLD_CLEANUP_NAMES[m], value = m})
            end
            return out
        end)(),
        initial_option = S.WORLD_CLEANUP_NAMES[p.settings.world_cleanup] and p.settings.world_cleanup or 'safe',
        on_change = function(v) p:set_field('world_cleanup', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'expel_vampires',
        frame = {t = t + 8, l = 0, w = 60},
        label = 'Send away vampires found among the dwarves:',
        label_width = 46,
        initial_option = p.settings.expel_vampires,
        on_change = function(v) p:set_field('expel_vampires', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'accept_visitors',
        frame = {t = t + 9, l = 0, w = 60},
        label = 'Let useful visitors stay (and become citizens):',
        label_width = 46,
        initial_option = p.settings.accept_visitors,
        on_change = function(v) p:set_field('accept_visitors', v) end,
    })
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'clear_alerts',
        frame = {t = t + 10, l = 0, w = 76},
        label = 'Clear the alert icons:',
        label_width = 46,
        options = (function()
            local out = {}
            for _, m in ipairs(S.CLEAR_ALERTS) do table.insert(out, {label = S.CLEAR_ALERTS_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = p.settings.clear_alerts,
        on_change = function(v) p:set_field('clear_alerts', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'answer_locations',
        frame = {t = t + 11, l = 0, w = 60},
        label = 'Build the temples and guildhalls asked for:',
        label_width = 46,
        initial_option = p.settings.answer_locations,
        on_change = function(v) p:set_field('answer_locations', v) end,
    })
    -- (0.104.88) the camera director, while the keeper runs unattended
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'camera',
        frame = {t = t + 12, l = 0, w = 76},
        label = 'Camera (when the keeper runs unattended):',
        label_width = 46,
        options = (function()
            local out = {}
            for _, m in ipairs(S.CAMERA_MODES) do table.insert(out, {label = S.CAMERA_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = p.settings.camera,
        on_change = function(v) p:set_field('camera', v) end,
    })
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'camera_pace',
        frame = {t = t + 13, l = 2, w = 74},
        label = 'Camera pace:',
        label_width = 44,
        options = (function()
            local out = {}
            for _, m in ipairs(S.CAMERA_PACES) do table.insert(out, {label = S.CAMERA_PACE_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = p.settings.camera_pace,
        on_change = function(v) p:set_field('camera_pace', v) end,
    })
    self:addviews(views)
end

---------------------------------------------------------------------------
-- (0.105.33 review) The Army tab: the squads, the junk and the prisoners.
-- They were rows 29-43 of the Rules page, past the 28 rows the window shows
-- at its size (a Panel clips and does not scroll): unseen, unclickable.
---------------------------------------------------------------------------

MilitaryPage = defclass(MilitaryPage, widgets.Panel)
MilitaryPage.ATTRS{panel = DEFAULT_NIL}

function MilitaryPage:init()
    local p = self.panel
    local views = {}
    local t = -3          -- the header at row 0 (the rows below are t + n)
    table.insert(views, widgets.Label{frame = {t = t + 3, l = 0}, text = {{text = 'Military (the AI makes and sends squads):'}}})
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'attack_policy',
        frame = {t = t + 4, l = 2, w = 72},
        label = 'Send squads against:',
        label_width = 32,
        options = (function()
            local out = {}
            for _, m in ipairs(S.ATTACK_POLICIES) do
                table.insert(out, {label = S.ATTACK_POLICY_NAMES[m], value = m})
            end
            return out
        end)(),
        initial_option = p.settings.attack_policy,
        on_change = function(v) p:set_field('attack_policy', v) end,
    })
    for i, f in ipairs({{'fill_squads', 'Raise and fill squads:'},
                        {'train_squads', 'Put idle squads on training:'},
                        {'gate_lever', 'Close gates and link levers:'},
                        {'build_gate_doors', 'Put doors on entrances that have none:'},
                        {'fortify_entrances', 'Wall entrances, trap behind:'},
                        {'make_gear', 'Make weapons, armour and helms:'},
                        {'appoint_nobles', 'Appoint the six officials:'}}) do
        table.insert(views, widgets.ToggleHotkeyLabel{
            view_id = f[1],
            frame = {t = t + 4 + i, l = 2, w = 50},
            label = f[2],
            label_width = 34,
            initial_option = p.settings[f[1]],
            on_change = function(v) p:set_field(f[1], v) end,
        })
    end
    -- (0.105.27) forbidden items and junk: the right-hand column beside the
    -- military switches (rows t+5..t+8; the left column ends at l=52 there).
    -- (0.105.27 fixes) short labels, l=56 w=50: they end at column 106 of the
    -- window's ~120 inside (they ended at 118 before)
    table.insert(views, widgets.Label{frame = {t = t + 5, l = 56}, text = {{text = 'Forbidden items and junk:'}}})
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'disposal',
        frame = {t = t + 6, l = 56, w = 50},
        label = 'Dispose:',
        label_width = 20,
        options = (function()
            local out = {}
            for _, m in ipairs(S.DISPOSAL_CHOICES) do table.insert(out, {label = S.DISPOSAL_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = p.settings.disposal or 'destroy',
        on_change = function(v) p:set_field('disposal', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'disposal_player_items',
        frame = {t = t + 7, l = 56, w = 50},
        label = 'Yours too:',
        label_width = 20,
        initial_option = p.settings.disposal_player_items == true,
        on_change = function(v) p:set_field('disposal_player_items', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'keep_enemy_gear',
        frame = {t = t + 8, l = 56, w = 50},
        label = 'Keep enemy gear:',
        label_width = 20,
        initial_option = p.settings.keep_enemy_gear == true,
        on_change = function(v) p:set_field('keep_enemy_gear', v) end,
    })
    -- (0.105.0) the squads hide with the civilians (the row under the list's seven; merge: was t+11, on appoint_nobles)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'squads_shelter',
        frame = {t = t + 12, l = 2, w = 50},
        label = 'When hiding, squads wait in the shelter:',
        label_width = 42,
        initial_option = p.settings.squads_shelter ~= false,
        on_change = function(v) p:set_field('squads_shelter', v) end,
    })
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'gear_weapon',
        frame = {t = t + 13, l = 2, w = 60},
        label = 'Weapon to make:',
        label_width = 34,
        options = (function()
            local out = {}
            for _, m in ipairs(S.GEAR_WEAPONS) do table.insert(out, {label = S.GEAR_WEAPON_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = p.settings.gear_weapon,
        on_change = function(v) p:set_field('gear_weapon', v) end,
    })
    -- (0.105.0) round 3: prisoners, werebeasts' cells, the caverns sealed
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'prisoners',
        frame = {t = t + 14, l = 2, w = 72},
        label = 'Invaders caught in cages:',
        label_width = 34,
        options = (function()
            local out = {}
            for _, m in ipairs(S.PRISONER_CHOICES) do table.insert(out, {label = S.PRISONER_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = p.settings.prisoners or 'keep',
        on_change = function(v) p:set_field('prisoners', v) end,
    })
    for i, f in ipairs({{'moon_cells', 'Lock werebeasts in at the full moon:'},
                        {'seal_caverns', 'Seal a cavern a beast is in:'}}) do
        table.insert(views, widgets.ToggleHotkeyLabel{
            view_id = f[1],
            frame = {t = t + 14 + i, l = 2, w = 50},
            label = f[2],
            label_width = 36,
            initial_option = p.settings[f[1]] ~= false,
            on_change = function(v) p:set_field(f[1], v) end,
        })
    end
    -- (0.105.41, item 4) food from the land: the free row t+17 under the caverns'
    -- switches, two short switches side by side (the left column, ending by l=56)
    for i, f in ipairs({{'hunting', 'Hunters (when safe):'},
                        {'cavern_farms', 'Cavern-soil farms:'}}) do
        table.insert(views, widgets.ToggleHotkeyLabel{
            view_id = f[1],
            frame = {t = t + 17, l = 2 + (i - 1) * 28, w = 26},
            label = f[2],
            label_width = 21,
            initial_option = p.settings[f[1]] ~= false,
            on_change = function(v) p:set_field(f[1], v) end,
        })
    end
    -- (0.105.39, 13b) missions out into the world: which kinds, and whether the
    -- AI drives the World screen to send them (rows t+17..t+20, under the caverns)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'missions',
        frame = {t = t + 18, l = 2, w = 72},
        label = 'Missions to send out:',
        label_width = 34,
        options = (function()
            local out = {}
            for _, m in ipairs(S.MISSION_CHOICES) do table.insert(out, {label = S.MISSION_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = S.MISSION_NAMES[p.settings.missions] and p.settings.missions or 'rescue',
        on_change = function(v) p:set_field('missions', v) end,
    })
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'send_missions',
        frame = {t = t + 19, l = 2, w = 60},
        label = 'Send missions by the World screen:',
        label_width = 40,
        initial_option = p.settings.send_missions == true,
        on_change = function(v) p:set_field('send_missions', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = t + 20, l = 4}, text = {
        {text = S.MISSION_HELP, pen = COLOR_GREY}}})
    table.insert(views, widgets.Label{frame = {t = t + 21, l = 4}, text = {
        {text = 'a reserve stays home, one at a time, never with a threat near; off: you are told what to send',
         pen = COLOR_GREY}}})
    t = t + 20
    table.insert(views, widgets.WrappedLabel{
        frame = {t = t + 3, l = 0, r = 2},
        text_to_wrap = 'Bedrooms, the dining hall, basic workshops and stockpiles are always built when '
            .. 'missing: a fort can\'t do without them. Switch the overseer to Advisor or halt it '
            .. '(Ctrl-Shift-H) to stop all building. Click a setting to change it.',
        text_pen = COLOR_GREY,
    })
    self:addviews(views)
end

function RulesPage:refresh()
    local s = self.panel.settings
    self.subviews.memorial_pace:setOption(s.memorial_pace, false)
    self.subviews.landmark_pace:setOption(s.landmark_pace or 'season', false)     -- (D0)
    self.subviews.fort_goal:setOption(s.fort_goal, false)
    self.subviews.set_pop_cap:setOption(s.set_pop_cap, false)
    for _, l in ipairs(S.OPTIONAL_LEVELS) do
        self.subviews['level_' .. l.id]:setOption(s.levels[l.id] ~= false, false)
    end
    self.subviews.order_supplies:setOption(s.order_supplies, false)
    self.subviews.mood_workshops:setOption(s.mood_workshops, false)
    self.subviews.give_trinkets:setOption(s.give_trinkets, false)
    self.subviews.water_works:setOption(s.water_works, false)
    self.subviews.expel_vampires:setOption(s.expel_vampires, false)
    self.subviews.accept_visitors:setOption(s.accept_visitors, false)
    self.subviews.clear_alerts:setOption(s.clear_alerts, false)
    self.subviews.camera:setOption(s.camera, false)
    self.subviews.camera_pace:setOption(s.camera_pace, false)
    self.subviews.answer_locations:setOption(s.answer_locations, false)
    self.subviews.hospital_burrow:setOption(s.hospital_burrow ~= false, false)     -- (0.104.168)
    self.subviews.calm_burrow:setOption(s.calm_burrow ~= false, false)             -- (0.104.169)
    self.subviews.tribute:setOption(s.tribute or 'small', false)                   -- (0.105.0)
    self.subviews.make_contact:setOption(s.make_contact ~= false, false)           -- (0.105.0)
    self.subviews.send_messenger:setOption(s.send_messenger == true, false)        -- (0.105.24)
    self.subviews.heist_lockout:setOption(s.heist_lockout ~= false, false)         -- (0.105.24)
    self.subviews.shut_to_visitors:setOption(s.shut_to_visitors ~= false, false)   -- (0.105.24)
    self.subviews.construct:setOption(s.construct ~= false, false)                 -- (0.105.30)
    self.subviews.traffic:setOption(s.traffic ~= false, false)                     -- (0.105.41)
    for _, k in ipairs({'moat', 'magma_workshops', 'irrigation'}) do               -- (0.105.0)
        self.subviews[k]:setOption(s[k] ~= false, false)
    end
    self.subviews.open_caverns:setOption(S.open_caverns_choice(s.open_caverns), false)   -- (v35 fix) three-state
    self.subviews.world_cleanup:setOption(S.WORLD_CLEANUP_NAMES[s.world_cleanup] and s.world_cleanup or 'safe', false)   -- (0.105.40)
    self.subviews.engrave_slabs:setOption(s.engrave_slabs, false)
    self.subviews.import_smelting:setOption(s.import_smelting, false)
    self.subviews.alert_shelter:setOption(s.alert_shelter, false)
    self.subviews.pasture_animals:setOption(s.pasture_animals, false)
end

function MilitaryPage:refresh()
    local s = self.panel.settings
    self.subviews.attack_policy:setOption(s.attack_policy, false)
    for _, k in ipairs({'fill_squads', 'train_squads', 'gate_lever', 'build_gate_doors', 'fortify_entrances',
                        'make_gear', 'appoint_nobles'}) do
        self.subviews[k]:setOption(s[k], false)
    end
    self.subviews.squads_shelter:setOption(s.squads_shelter ~= false, false)       -- (0.105.0)
    self.subviews.gear_weapon:setOption(s.gear_weapon, false)
    self.subviews.prisoners:setOption(s.prisoners or 'keep', false)                -- (0.105.0)
    self.subviews.moon_cells:setOption(s.moon_cells ~= false, false)
    self.subviews.seal_caverns:setOption(s.seal_caverns ~= false, false)
    self.subviews.disposal:setOption(s.disposal or 'destroy', false)                      -- (0.105.27)
    self.subviews.disposal_player_items:setOption(s.disposal_player_items == true, false)
    self.subviews.keep_enemy_gear:setOption(s.keep_enemy_gear == true, false)
    for _, k in ipairs({'hunting', 'cavern_farms'}) do                              -- (0.105.41, item 4)
        self.subviews[k]:setOption(s[k] ~= false, false)
    end
    self.subviews.missions:setOption(S.MISSION_NAMES[s.missions] and s.missions or 'rescue', false)   -- (0.105.39)
    self.subviews.send_missions:setOption(s.send_missions == true, false)
end

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
