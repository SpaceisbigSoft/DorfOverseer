-- gui/ai-overseer-rules: the control panel's Rules tab (what the planner may
-- build and do on its own) and Army tab (the squads, the junk, the
-- prisoners), and their refresh.
--
-- (r9) A part of gui/ai-overseer, not a script of its own: gui/ai-overseer.lua
-- loads it into its own environment, so every name here is
-- reqscript('gui/ai-overseer').name, as when it was one file.

if not OVERSEER_PART_LOCALS then qerror('gui/ai-overseer-rules is a part of gui/ai-overseer; run gui/ai-overseer') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['gui/ai-overseer-rules'] = '0.105.128'   -- (0.105.26) bumped with BRIDGE_VERSION

local widgets, S = OVERSEER_PART_LOCALS.widgets, OVERSEER_PART_LOCALS.S   -- (r9) the hub's locals

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
        -- (D0) beside the memorials: how often a fort starts a landmark ((0.105.47, D1) Guided and Architect)
        widgets.CycleHotkeyLabel{
            view_id = 'landmark_pace',
            frame = {t = 2, l = 72, w = 46},
            label = 'Landmarks (Guided+):',
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
        -- (0.105.46, I4) beside the cap: a fallen fort DF sends no migrants to gets a
        -- wave called (DFHack's force Migrants; brain/planner_recovery.py)
        widgets.ToggleHotkeyLabel{
            view_id = 'call_migrants',
            frame = {t = 3, l = 62, w = 50},
            label = 'Call migrants to a fallen fort:',
            label_width = 33,
            initial_option = p.settings.call_migrants ~= false,
            on_change = function(v) p:set_field('call_migrants', v) end,
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
    -- (0.105.41, item 11) syndrome care, under the hospital burrow's help line (the row is free)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'syndrome_care',
        frame = {t = 6 + hrow, l = 56, w = 62},
        label = 'Keep syndrome carriers apart, clean it off:',
        label_width = 46,
        initial_option = p.settings.syndrome_care ~= false,
        on_change = function(v) p:set_field('syndrome_care', v) end,
    })
    -- (fix5, item 12) artifacts shown in the AI's own rooms: the right-hand
    -- column's free row under the traffic switch's help line, above the calm burrow's
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'display_artifacts',
        frame = {t = 9 + hrow, l = 56, w = 62},
        label = 'Show the AI\'s artifacts in its own rooms:',
        label_width = 46,
        initial_option = p.settings.display_artifacts ~= false,
        on_change = function(v) p:set_field('display_artifacts', v) end,
    })
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
    -- (0.105.24, 13b) the AI drives the World screen to send the messenger ((r10 p3) on by default: every fort makes initial contact; off: never)
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
    -- (0.105.41, item 7) spilt magma that cooled: the walls it left dug out
    -- (under the water works' switches; right of "Clear the alert icons", which ends at column 76)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'magma_reclaim',
        frame = {t = t + 10, l = 78, w = 40},
        label = 'Dig out spilt magma\'s walls:',
        label_width = 30,
        initial_option = p.settings.magma_reclaim ~= false,
        on_change = function(v) p:set_field('magma_reclaim', v) end,
    })
    -- (0.105.105) the in-game fight watcher: under "Dig out spilt magma's walls",
    -- right of the camera switch (which ends at column 76)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'fight_watch',
        frame = {t = t + 12, l = 78, w = 40},
        label = 'Break up citizens\' fights:',
        label_width = 30,
        initial_option = p.settings.fight_watch ~= false,
        on_change = function(v) p:set_field('fight_watch', v) end,
    })
    -- (item3) a tantrum that attacks a citizen ended by the watcher: under the
    -- fight watcher's switch, right of "Camera pace" (which ends at column 76)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'end_tantrums',
        frame = {t = t + 13, l = 78, w = 40},
        label = 'End a tantrum that attacks:',
        label_width = 30,
        initial_option = p.settings.end_tantrums ~= false,
        on_change = function(v) p:set_field('end_tantrums', v) end,
    })
    -- (R29 W8) DF's beating of a convict spared by the watcher (off: DF's own
    -- punishment left alone). (R29 fix) the right-hand column's free row 5,
    -- between "New levels" (row 4) and the hospital burrow (4 + hrow): under
    -- the tantrum switch it was row t + 14 = 28, past the window's last row 27
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'spare_beatings',
        frame = {t = 5, l = 56, w = 40},
        label = 'Spare convicts DF\'s beatings:',
        label_width = 30,
        initial_option = p.settings.spare_beatings ~= false,
        on_change = function(v) p:set_field('spare_beatings', v) end,
    })
    -- (item3) the guarded cavern way: row 5 right of "Spare convicts" (which ends at column 96)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'cavern_way',
        frame = {t = 5, l = 98, w = 20},
        label = 'Cavern way:',
        label_width = 12,
        initial_option = p.settings.cavern_way ~= false,
        on_change = function(v) p:set_field('cavern_way', v) end,
    })
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
    -- (layout B) how new levels are placed: along a main hall on each floor (the default) or each on
    -- its own (classic). The right-hand column's free row 4, beside the "Levels the AI may build"
    -- heading (which ends at column 36) and above the hospital burrow's switch (row 4 + hrow, 5 at least)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'floor_layout',
        frame = {t = 4, l = 56, w = 62},
        label = 'New levels:',
        label_width = 12,
        options = (function()
            local out = {}
            for _, m in ipairs(S.FLOOR_LAYOUT_CHOICES) do
                table.insert(out, {label = S.FLOOR_LAYOUT_NAMES[m], value = m})
            end
            return out
        end)(),
        initial_option = S.FLOOR_LAYOUT_NAMES[p.settings.floor_layout] and p.settings.floor_layout or 'hallway',
        on_change = function(v) p:set_field('floor_layout', v) end,
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
    -- (item5) siege works and the field guard: under the disposal rows (t+9..t+12, from
    -- l=56, clear of the military list's l=2..52 and of gear_weapon's row t+13)
    for _, f in ipairs({{'siege_engines', 'Ballistae at the gates:', 9},
                        {'archer_posts', 'Archers behind fortifications:', 10},
                        {'caravan_guard', 'Guard a caravan attacked:', 11},
                        {'wildlife_hunts', 'Hunt beasts near workers:', 12}}) do
        table.insert(views, widgets.ToggleHotkeyLabel{
            view_id = f[1],
            frame = {t = t + f[3], l = 56, w = 50},
            label = f[2],
            label_width = 32,
            initial_option = p.settings[f[1]] ~= false,
            on_change = function(v) p:set_field(f[1], v) end,
        })
    end
    -- (0.105.0) the squads hide with the civilians (the row under the list's seven; merge: was t+11, on appoint_nobles)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'squads_shelter',
        frame = {t = t + 12, l = 2, w = 50},
        label = 'When hiding, squads guard the way in:',   -- (0.105.45) between the threat and the shelter
        label_width = 42,
        initial_option = p.settings.squads_shelter ~= false,
        on_change = function(v) p:set_field('squads_shelter', v) end,
    })
    -- (0.105.41, item 8) a peace proposal from a civilisation's diplomat: the
    -- right-hand column's free rows t+15, t+16 (merge 0.105.41: t+9..t+12 hold the
    -- siege switches; gear_weapon and prisoners reach column 74 at t+13, t+14)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'peace',
        frame = {t = t + 15, l = 58, w = 50},
        label = 'Peace offered:',
        label_width = 20,
        options = (function()
            local out = {}
            for _, m in ipairs(S.PEACE_CHOICES) do table.insert(out, {label = S.PEACE_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = S.PEACE_NAMES[p.settings.peace] and p.settings.peace or 'ai',
        on_change = function(v) p:set_field('peace', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = t + 16, l = 60}, text = {
        {text = S.PEACE_HELP, pen = COLOR_GREY}}})
    -- (0.105.45) a great beast sealed in a cavern lured into a pocket: the right-hand
    -- column's free row t+3 (beside the Military heading, clear of the disposal rows)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'lure_beasts',
        frame = {t = t + 3, l = 56, w = 50},
        label = 'Lure a sealed beast into a trap:',
        label_width = 34,
        initial_option = p.settings.lure_beasts ~= false,
        on_change = function(v) p:set_field('lure_beasts', v) end,
    })
    -- (item10) cavern trees felled when wood is short and the caverns are watched
    -- (merge 0.105.41: right-hand column, row t+17, beside the provisions' switches)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'cavern_logging',
        frame = {t = t + 17, l = 58, w = 48},
        label = 'Fell cavern trees when safe:',
        label_width = 32,
        initial_option = p.settings.cavern_logging ~= false,
        on_change = function(v) p:set_field('cavern_logging', v) end,
    })
    -- (0.105.45) kill zones at the gates and cavern openings: the right-hand column's
    -- free row t+18 (the missions row ends at column 74)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'killzones',
        frame = {t = t + 18, l = 76, w = 40},
        label = 'Kill zones at the gates:',
        label_width = 28,
        initial_option = p.settings.killzones ~= false,
        on_change = function(v) p:set_field('killzones', v) end,
    })
    -- (0.105.47) the training squad: the right-hand column's free row t+13
    -- (gear_weapon ends at column 62 there)
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'training_squad',
        frame = {t = t + 13, l = 64, w = 44},
        label = 'Training squad (Welfare):',
        label_width = 27,
        initial_option = p.settings.training_squad ~= false,
        on_change = function(v) p:set_field('training_squad', v) end,
    })
    -- (0.105.47, J17) raids, inside "Missions to send out: all": the right-hand
    -- column's free row t+14 (prisoners beside it ends at column 74)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'raid_policy',
        frame = {t = t + 14, l = 76, w = 40},
        label = 'Raids:',
        label_width = 8,
        options = (function()
            local out = {}
            for _, m in ipairs(S.RAID_POLICY_CHOICES) do table.insert(out, {label = S.RAID_POLICY_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = S.RAID_POLICY_NAMES[p.settings.raid_policy] and p.settings.raid_policy or 'off',
        on_change = function(v) p:set_field('raid_policy', v) end,
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
    -- (0.105.45) hunting threats the squads can beat: the right-hand column's
    -- free row t+19 (send_missions ends at column 62 there)
    table.insert(views, widgets.CycleHotkeyLabel{
        view_id = 'hunt',
        frame = {t = t + 19, l = 64, w = 50},
        label = 'Hunt threats:',
        label_width = 14,
        options = (function()
            local out = {}
            for _, m in ipairs(S.HUNT_CHOICES) do table.insert(out, {label = S.HUNT_NAMES[m], value = m}) end
            return out
        end)(),
        initial_option = S.HUNT_NAMES[p.settings.hunt] and p.settings.hunt or 'ai',
        on_change = function(v) p:set_field('hunt', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = t + 21, l = 4}, text = {
        {text = 'a reserve stays home, one at a time, never with a threat near; off: you are told what to send',
         pen = COLOR_GREY}}})
    t = t + 20
    -- (R29 W2) a siege invited on purpose, once (a test of the defence): the free
    -- row t+2 (row 19) between the hunt's help line and the help text
    table.insert(views, widgets.ToggleHotkeyLabel{
        view_id = 'invite_siege',
        frame = {t = t + 2, l = 0, w = 44},
        label = 'Invite a siege (test, once):',
        label_width = 32,
        initial_option = p.settings.invite_siege == true,
        on_change = function(v) p:set_field('invite_siege', v) end,
    })
    table.insert(views, widgets.Label{frame = {t = t + 2, l = 46}, text = {
        {text = "DFHack's force calls one army of an enemy civ; then off for good", pen = COLOR_GREY}}})
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
    self.subviews.call_migrants:setOption(s.call_migrants ~= false, false)          -- (0.105.46, I4)
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
    self.subviews.syndrome_care:setOption(s.syndrome_care ~= false, false)         -- (0.105.41, item 11)
    self.subviews.calm_burrow:setOption(s.calm_burrow ~= false, false)             -- (0.104.169)
    self.subviews.fight_watch:setOption(s.fight_watch ~= false, false)             -- (item1)
    self.subviews.end_tantrums:setOption(s.end_tantrums ~= false, false)           -- (item3)
    self.subviews.spare_beatings:setOption(s.spare_beatings ~= false, false)       -- (R29 W8)
    self.subviews.cavern_way:setOption(s.cavern_way ~= false, false)               -- (item3)
    self.subviews.tribute:setOption(s.tribute or 'small', false)                   -- (0.105.0)
    self.subviews.make_contact:setOption(s.make_contact ~= false, false)           -- (0.105.0)
    self.subviews.send_messenger:setOption(s.send_messenger == true, false)        -- (0.105.24)
    self.subviews.heist_lockout:setOption(s.heist_lockout ~= false, false)         -- (0.105.24)
    self.subviews.shut_to_visitors:setOption(s.shut_to_visitors ~= false, false)   -- (0.105.24)
    self.subviews.construct:setOption(s.construct ~= false, false)                 -- (0.105.30)
    self.subviews.traffic:setOption(s.traffic ~= false, false)                     -- (0.105.41)
    self.subviews.display_artifacts:setOption(s.display_artifacts ~= false, false) -- (fix5, item 12)
    for _, k in ipairs({'moat', 'magma_workshops', 'irrigation', 'magma_reclaim'}) do   -- (0.105.0; 0.105.41)
        self.subviews[k]:setOption(s[k] ~= false, false)
    end
    self.subviews.open_caverns:setOption(S.open_caverns_choice(s.open_caverns), false)   -- (v35 fix) three-state
    self.subviews.world_cleanup:setOption(S.WORLD_CLEANUP_NAMES[s.world_cleanup] and s.world_cleanup or 'safe', false)   -- (0.105.40)
    self.subviews.floor_layout:setOption(S.FLOOR_LAYOUT_NAMES[s.floor_layout] and s.floor_layout or 'hallway', false)   -- (layout B)
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
    for _, k in ipairs({'siege_engines', 'archer_posts', 'caravan_guard', 'wildlife_hunts'}) do   -- (item5)
        self.subviews[k]:setOption(s[k] ~= false, false)
    end
    self.subviews.killzones:setOption(s.killzones ~= false, false)                  -- (0.105.45)
    self.subviews.training_squad:setOption(s.training_squad ~= false, false)        -- (0.105.47)
    self.subviews.invite_siege:setOption(s.invite_siege == true, false)             -- (R29 W2)
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
    self.subviews.cavern_logging:setOption(s.cavern_logging ~= false, false)        -- (item10)
    self.subviews.hunt:setOption(S.HUNT_NAMES[s.hunt] and s.hunt or 'ai', false)   -- (0.105.45)
    self.subviews.lure_beasts:setOption(s.lure_beasts ~= false, false)              -- (0.105.45)
    self.subviews.missions:setOption(S.MISSION_NAMES[s.missions] and s.missions or 'rescue', false)   -- (0.105.39)
    self.subviews.send_missions:setOption(s.send_missions == true, false)
    self.subviews.raid_policy:setOption(S.RAID_POLICY_NAMES[s.raid_policy] and s.raid_policy or 'off', false)   -- (0.105.47, J17)
    self.subviews.peace:setOption(S.PEACE_NAMES[s.peace] and s.peace or 'ai', false)   -- (0.105.41, item 8)
end

