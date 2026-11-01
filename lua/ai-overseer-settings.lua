-- ai-overseer-settings: the player's settings for the AI overseer.
--
-- Shared by the in-game panel (gui/ai-overseer) and the bridge (ai-bridge),
-- which hands them to the AI. Saved per fortress in the save file
-- (dfhack.persistent), so each fort keeps its own personality.
--
-- Run on its own, it prints the current settings as one line of JSON.
--@ module = true

local json = require('json')

SETTINGS_KEY = 'ai-overseer/settings'
SETTINGS_VERSION = 2   -- 2 (0.94): Hostility and Hospitality became Outsiders
TRAIT_MIN, TRAIT_MAX, TRAIT_STEP = -100, 100, 10
PRESET_DIR = dfhack.getDFPath() .. '/dfhack-config/ai-overseer/presets'

-- Each trait: id, name, what -100 and +100 mean. Grouped by tab.
TRAIT_GROUPS = {
    {name = 'Temperament', traits = {
        {id = 'caution', name = 'Caution',
         low = 'Bold, accepts big risks', high = 'Careful, always plays safe'},
        {id = 'outsiders', name = 'Outsiders',
         low = 'Closed: no residents, no new citizens', high = 'Welcoming: guests, residents, a bigger tavern'},
        {id = 'greed', name = 'Greed',
         low = 'Generous: pays the caravans well', high = 'Grasping: hard bargains, gems kept home'},
        {id = 'piety', name = 'Piety',
         low = 'Ignores religion', high = 'Devout: temples and shrines'},
        {id = 'industriousness', name = 'Industry',
         low = 'Leisurely: leaves stone where it lies', high = 'Driven: busy, tidy, polished'},
        {id = 'craftsmanship', name = 'Craft',
         low = 'Practical: quantity over quality', high = 'Masterwork: fine materials, fine work'},
        {id = 'justice', name = 'Justice',
         low = 'Lenient: no jail', high = 'Harsh: an early, big jail'},
    }},
    {name = 'Construction', traits = {
        {id = 'surface', name = 'Surface vs underground',
         low = 'Underground: few woodcutters', high = 'Surface: a keep, more woodcutters'},
        {id = 'size', name = 'Room size',
         low = 'Small rooms (2x2)', high = 'Large rooms (4x4)'},
        {id = 'spacing', name = 'Spacing',
         low = 'Tightly packed, new halls hug the fort', high = 'Spread far apart, long halls between'},
        {id = 'verticality', name = 'Depth',
         low = 'Wide and flat', high = 'Deep: tall stacks of levels'},
        {id = 'grandeur', name = 'Grandeur',
         low = 'Rough rock is fine', high = 'Smoothed, engraved, statues everywhere'},
        {id = 'fortification', name = 'Fortification',
         low = 'Open layout', high = 'Walls, moats, drawbridges, traps'},
        {id = 'mining', name = 'Mining ambition',
         low = 'Only what it needs, metal by trade', high = 'Big veins and quarries'},
        {id = 'engineering', name = 'Engineering',
         low = 'Simple: a cistern late or never', high = 'Mechanical: traps, spare mechanisms, early cistern'},
    }},
    {name = 'Economy', traits = {
        {id = 'trade', name = 'Trade focus',
         low = 'Keep the surplus (self-sufficient)', high = 'Trade the surplus away (trading hub)'},
        {id = 'stockpile', name = 'Reserves',
         low = 'Lives hand to mouth', high = 'Large reserves of everything'},
        {id = 'agriculture', name = 'Farming',
         low = 'Hunt and gather', high = 'Big farms'},
        {id = 'husbandry', name = 'Animals',
         low = 'Few animals', high = 'Large herds'},
    }},
    {name = 'Society', traits = {
        {id = 'militarism', name = 'Militarism',
         low = 'Small army: 5% soldiers (Extreme: down to none)', high = 'Large army: 40% (Extreme: up to 90%)'},
        {id = 'growth', name = 'Growth',
         low = 'Low: about 25 dwarves (Extreme: dwarves slowly sent away)',
         high = 'High: about 250 (Extreme: up to no cap); 0 = about 100'},
        {id = 'welfare', name = 'Welfare',
         low = 'Ignore happiness', high = 'Pamper the dwarves'},
        {id = 'deference', name = 'Noble deference',
         low = 'Ignore nobles: no mandates, no rooms', high = 'Indulge them: every room, suites early'},
    }},
}

TRAITS_BY_ID = {}
for _, group in ipairs(TRAIT_GROUPS) do
    for _, t in ipairs(group.traits) do
        t.group = group.name
        TRAITS_BY_ID[t.id] = t
    end
end

-- The AI's two sliders (the AI & tokens tab), -100..100 like the traits, with
-- Extreme doubling them. Not traits: they set how the strategist works, not
-- what the fort is like. Their words: Very rare / Rare / Normal / Often / Very often.
AI_SLIDERS = {
    {id = 'ai_frequency', name = 'How often it reviews', group = 'AI & tokens',
     low = 'Rare', high = 'Often', xlow = 'Very rare', xhigh = 'Very often',
     words = {'Very rare', 'Rare', 'Normal', 'Often', 'Very often'}},
    {id = 'ai_effort', name = 'How long it thinks', group = 'AI & tokens',
     low = 'Short', high = 'Long', xlow = 'Very short', xhigh = 'Very long',
     words = {'Very short', 'Short', 'Normal', 'Long', 'Very long'}},
}
AI_SLIDERS_BY_ID = {}
for _, a in ipairs(AI_SLIDERS) do AI_SLIDERS_BY_ID[a.id] = a end
STORY_TOKENS = 1000   -- about what one AI-written season story costs (brain/storyteller.py)
REAL_DAY_CAP_OPTIONS = {0, 100000, 250000, 500000, 1000000, 2000000} -- 0 = no cap

-- One of the 5 words for an effective value (-200..200).
function slider_word(def, v)
    local i = v <= -150 and 1 or v <= -50 and 2 or v < 50 and 3 or v < 150 and 4 or 5
    return def.words[i]
end

-- What the two sliders mean, in numbers (the same formula as brain/tokens.py
-- ai_plan; tests/test_strategist.py checks they agree). f, e: effective values.
function ai_plan(f, e)
    local interval = math.max(1, math.floor(14 * 2 ^ (-f / 100) + 0.5))
    local events = 2 ^ (f / 100)
    local think_r = (e * 20 >= 1024) and math.floor(e * 20) or 0
    local think_e = (e * 30 >= 1024) and math.floor(e * 30) or 0
    local base = math.floor(3100 * 2 ^ (e / 200))
    local est_r, est_e = base + think_r, base + think_e
    local routine_year, events_year = 336 / interval, 12 * events
    return {
        interval_days = interval, events_per_month = events,
        model_routine = e >= 100 and 'large' or 'small',
        model_events = e <= -100 and 'small' or (e >= 200 and 'top' or 'large'),
        thinking_routine = think_r, thinking_events = think_e,
        est_routine = est_r, est_event = est_e,
        reviews_per_year = math.floor(routine_year + events_year + 0.5),
        tokens_per_year = math.floor(routine_year * est_r + events_year * est_e),
    }
end

-- How much the AI may do on its own (the overseer must also be started with
-- --autopilot before it acts at all):
--   advisor:   only suggests (shown in the on-screen panel)
--   copilot:   routine actions on its own; asks you before big moves
--   autopilot: does everything on its own
MODES = {'advisor', 'copilot', 'autopilot'}
MODE_NAMES = {advisor = 'Advisor (suggests only)', copilot = 'Co-pilot (asks before big moves)',
              autopilot = 'Autopilot (does everything)'}

-- What the planner may build and do on its own (the Rules tab).
MEMORIAL_PACES = {'every', 'season', 'year', 'never'}
MEMORIAL_PACE_NAMES = {every = 'one for every slain beast', season = 'at most one per season',
                       year = 'at most one per year', never = 'never'}
ATTACK_POLICIES = {'ordinary', 'all', 'never'}
-- (0.88) the alert icons down the left of the screen: which the AI clears
CLEAR_ALERTS = {'quiet', 'all', 'none'}
-- (0.104.88) the camera director (lua/ai-camera.lua), while the keeper runs unattended
CAMERA_MODES = {'on', 'tour', 'off'}
CAMERA_NAMES = {on = 'follows what happens, tours between', tour = 'tours the fort only', off = 'off (the view is yours)'}
-- (0.104.90) how long the camera stays at each place
CAMERA_PACES = {'normal', 'slow', 'fast'}
CAMERA_PACE_NAMES = {normal = 'normal (20-40 s a place)', slow = 'slow (longer at each place)', fast = 'fast (shorter stops)'}
CLEAR_ALERTS_NAMES = {quiet = 'old ones; dangers kept a week', all = 'all once a day old', none = 'none (yours)'}
ATTACK_POLICY_NAMES = {ordinary = 'ordinary enemies, not great beasts', all = 'everything that can reach us',
                       never = 'never (alert and gate only)'}
GEAR_WEAPONS = {'axe', 'spear', 'mace'}
GEAR_WEAPON_NAMES = {axe = 'battle axes', spear = 'spears', mace = 'maces'}
OPTIONAL_LEVELS = {
    {id = 'tombs', name = 'Tombs (coffins for the dead)'},
    {id = 'hospital', name = 'Hospital'},
    {id = 'tavern', name = 'Tavern'},
    {id = 'library', name = 'Library'},
    {id = 'barracks', name = 'Barracks (militant forts)'},
    {id = 'archery', name = 'Archery range (crossbow squads)'},
    {id = 'garden', name = 'Statue gardens (in good times)'},
    {id = 'jail', name = 'Jail (cells for the sheriff)'},
    {id = 'temple', name = 'Temple (devout forts)'},
}

-- What the fort works toward:
--   expand:   grow toward the Growth target (bedrooms ahead of migrants,
--             new halls)
--   maintain: hold the population where it is (no new migrants) and keep
--             everything running; no new prestige halls
FORT_GOALS = {'expand', 'maintain'}
FORT_GOAL_NAMES = {expand = 'Expand toward the Growth target', maintain = 'Maintain: keep it as it is'}

-- The population the Growth slider stands for (same numbers as the planner,
-- brain/planner.py growth_mode), from the effective value (Extreme doubles it,
-- as on every slider since 0.94): 25 at -100, 100 at 0, 250 at +100, rising
-- past +100 to no cap at +200; past -100 no newcomers, and every
-- SHRINK_DAYS * 100/(|v|-100) in-game days one dwarf is sent away.
GROWTH_POINTS = {low = 25, average = 100, high = 250}
SHRINK_DAYS = 28

function growth_target(t)
    local v = effective(t)
    local p = GROWTH_POINTS
    if v >= 200 or v < -100 then return nil end
    if v > 100 then return math.floor(p.high * 4 ^ ((v - 100) / 100) + 0.5) end
    local edge = v >= 0 and p.high or p.low
    return math.floor(p.average + (edge - p.average) * math.abs(v) / 100 + 0.5)
end

function growth_text(t)
    local v = effective(t)
    if v >= 200 then return 'no population cap' end
    if v < -100 then
        return ('shrinking: one dwarf sent away every %d days'):format(math.floor(SHRINK_DAYS * 100 / (math.abs(v) - 100) + 0.5))
    end
    return ('target: about %d dwarves'):format(growth_target(t))
end

function defaults()
    local traits = {}
    for id in pairs(TRAITS_BY_ID) do
        traits[id] = {value = 0, extreme = false}
    end
    return {
        version = SETTINGS_VERSION,
        traits = traits,
        ai_sliders = {ai_frequency = {value = 0, extreme = false},
                      ai_effort = {value = 0, extreme = false}},
        real_day_token_cap = 0,
        mode = 'autopilot',
        save_before_projects = false,
        memorial_pace = 'season',
        levels = (function()
            local out = {}
            for _, l in ipairs(OPTIONAL_LEVELS) do out[l.id] = true end
            return out
        end)(),
        order_supplies = true,     -- containers, bags, hospital supplies
        mood_workshops = true,     -- build the workshop a strange mood needs
        attack_policy = 'ordinary',
        fill_squads = true,
        train_squads = true,
        appoint_nobles = true,     -- appoint the manager, bookkeeper, broker, chief medical dwarf
        gate_lever = true,
        make_gear = true,
        gear_weapon = 'axe',
        engrave_slabs = true,      -- DFHack autoslab for ghosts, and blank slabs for it
        import_smelting = true,    -- DFHack's smelting orders when metal runs low
        alert_shelter = true,      -- make an "AI shelter" burrow for the civilian alert
        pasture_animals = true,    -- put grazing animals into an existing pasture
        build_gate_doors = true,   -- doors across an entrance that has nothing to close it
        fortify_entrances = true,  -- wall wide entrances down to a gate in the fort's own style
        fort_goal = 'expand',
        set_pop_cap = true,        -- set DF's population cap from Growth / Maintain
        ai_chronicle = false,
        give_trinkets = true,      -- a free trinket for dwarves who badly want something to own
        water_works = true,        -- cisterns and other water works the AI decides on
        accept_visitors = true,    -- (0.87) let useful visitors stay (DF's petition standing orders)
        clear_alerts = 'quiet',    -- (0.88) the alert icons the AI clears (CLEAR_ALERTS)
        camera = 'on',             -- (0.104.88) the camera director, when the keeper runs unattended (CAMERA_MODES)
        camera_pace = 'normal',    -- (0.104.90) how long it stays at each place (CAMERA_PACES)
        answer_locations = true,   -- (0.89) agree to and build the temples and guildhalls petitions ask for
        hospital_burrow = true,    -- (0.104.168) keep the wounded in the "AI hospital" burrow (off: all let out)
        expel_vampires = true,     -- a vampire found among the citizens is sent away      -- with --ai: a short AI-written story of each season (costs tokens)
        -- "Wipe what the AI learned" (Culture tab, Shift-V): each press adds 1;
        -- the overseer wipes when it sees the number go up
        wipe_learned = 0,          -- this fort only
        wipe_learned_all = 0,      -- this fort and the lessons shared by all your forts
    }
end

local function clamp_trait(v)
    v = math.tointeger(tonumber(v)) or 0
    return math.max(TRAIT_MIN, math.min(TRAIT_MAX, v))
end

local function one_of(v, options, default)
    for _, o in ipairs(options) do
        if o == v then return v end
    end
    return default
end

-- Repair whatever was loaded (old versions, hand edits, missing traits).
function sanitize(s)
    local d = defaults()
    if type(s) ~= 'table' then return d end
    local out = d
    if type(s.traits) == 'table' then
        for id in pairs(TRAITS_BY_ID) do
            local t = s.traits[id]
            if type(t) == 'table' then
                out.traits[id] = {value = clamp_trait(t.value), extreme = t.extreme == true}
            end
        end
        -- (0.94) an older save: Hospitality minus Hostility, halved, becomes Outsiders
        if type(s.traits.outsiders) ~= 'table'
                and (type(s.traits.hostility) == 'table' or type(s.traits.hospitality) == 'table') then
            local function eff(t) return type(t) == 'table' and effective({value = clamp_trait(t.value), extreme = t.extreme == true}) or 0 end
            local v = (eff(s.traits.hospitality) - eff(s.traits.hostility)) / 2
            local extreme = math.abs(v) > TRAIT_MAX
            local slider = extreme and v / 2 or v
            out.traits.outsiders = {value = clamp_trait(math.floor(slider / 10 + 0.5) * 10), extreme = extreme}
        end
    end
    if type(s.ai_sliders) == 'table' then
        for _, a in ipairs(AI_SLIDERS) do
            local t = s.ai_sliders[a.id]
            if type(t) == 'table' then
                out.ai_sliders[a.id] = {value = clamp_trait(t.value), extreme = t.extreme == true}
            end
        end
    elseif tonumber(s.activity) then
        -- a save from before the two sliders: its activity % (50 = Normal,
        -- 100 = twice as often, 10 = about Very rare) becomes How often
        local v = 100 * math.log(math.max(10, math.min(100, tonumber(s.activity))) / 50, 2)
        local extreme = math.abs(v) > 100
        local slider = extreme and v / 2 or v
        out.ai_sliders.ai_frequency = {value = clamp_trait(math.floor(slider / 10 + 0.5) * 10), extreme = extreme}
    end
    out.real_day_token_cap = one_of(math.tointeger(tonumber(s.real_day_token_cap)),
        REAL_DAY_CAP_OPTIONS, d.real_day_token_cap)
    out.mode = one_of(s.mode, MODES, d.mode)
    out.save_before_projects = s.save_before_projects == true
    out.memorial_pace = one_of(s.memorial_pace, MEMORIAL_PACES, d.memorial_pace)
    if type(s.levels) == 'table' then
        for _, l in ipairs(OPTIONAL_LEVELS) do
            if s.levels[l.id] ~= nil then out.levels[l.id] = s.levels[l.id] == true end
        end
    end
    if s.order_supplies ~= nil then out.order_supplies = s.order_supplies == true end
    if s.mood_workshops ~= nil then out.mood_workshops = s.mood_workshops == true end
    out.attack_policy = one_of(s.attack_policy, ATTACK_POLICIES, d.attack_policy)
    out.fort_goal = one_of(s.fort_goal, FORT_GOALS, d.fort_goal)
    out.clear_alerts = one_of(s.clear_alerts, CLEAR_ALERTS, d.clear_alerts)
    out.camera = one_of(s.camera, CAMERA_MODES, d.camera)
    out.camera_pace = one_of(s.camera_pace, CAMERA_PACES, d.camera_pace)
    for _, k in ipairs({'fill_squads', 'train_squads', 'appoint_nobles', 'gate_lever', 'make_gear', 'engrave_slabs',
                        'import_smelting', 'alert_shelter', 'pasture_animals', 'build_gate_doors',
                        'fortify_entrances', 'set_pop_cap', 'ai_chronicle', 'give_trinkets', 'water_works', 'expel_vampires', 'accept_visitors', 'answer_locations',
                        'hospital_burrow'}) do      -- (0.104.168) the hospital burrow's switch
        if s[k] ~= nil then out[k] = s[k] == true end
    end
    out.gear_weapon = one_of(s.gear_weapon, GEAR_WEAPONS, d.gear_weapon)
    for _, k in ipairs({'wipe_learned', 'wipe_learned_all'}) do
        local n = math.tointeger(tonumber(s[k]))
        out[k] = (n and n >= 0) and n or 0
    end
    return out
end

function load_settings()
    if not dfhack.isMapLoaded() then return defaults() end
    return sanitize(dfhack.persistent.getSiteData(SETTINGS_KEY, defaults()))
end

function save_settings(s)
    dfhack.persistent.saveSiteData(SETTINGS_KEY, sanitize(s))
end

-- What a trait actually means to the AI: the slider value, doubled if Extreme.
function effective(trait_setting)
    local v = trait_setting.value or 0
    return trait_setting.extreme and v * 2 or v
end

-- The compact form the AI reads: only traits that differ from neutral.
function for_ai(s)
    s = sanitize(s)
    local traits, extreme = {}, {}
    for id, t in pairs(s.traits) do
        local e = effective(t)
        if e ~= 0 then traits[id] = e end
        if t.extreme and t.value ~= 0 then table.insert(extreme, id) end
    end
    table.sort(extreme)
    return {
        traits = traits, -- effective values, -200..200; missing = 0 (balanced)
        extreme = extreme, -- traits with Extreme on (some rules read the slider and the switch apart)
        ai_frequency = effective(s.ai_sliders.ai_frequency),   -- the two AI sliders, -200..200
        ai_effort = effective(s.ai_sliders.ai_effort),
        real_day_token_cap = s.real_day_token_cap,
        mode = s.mode,
        save_before_projects = s.save_before_projects,
        memorial_pace = s.memorial_pace,
        levels = s.levels,
        order_supplies = s.order_supplies,
        mood_workshops = s.mood_workshops,
        attack_policy = s.attack_policy,
        fill_squads = s.fill_squads,
        train_squads = s.train_squads,
        appoint_nobles = s.appoint_nobles,
        gate_lever = s.gate_lever,
        make_gear = s.make_gear,
        gear_weapon = s.gear_weapon,
        engrave_slabs = s.engrave_slabs,
        import_smelting = s.import_smelting,
        alert_shelter = s.alert_shelter,
        pasture_animals = s.pasture_animals,
        build_gate_doors = s.build_gate_doors,
        fortify_entrances = s.fortify_entrances,
        fort_goal = s.fort_goal,
        set_pop_cap = s.set_pop_cap,
        ai_chronicle = s.ai_chronicle,
        give_trinkets = s.give_trinkets,
        water_works = s.water_works,
        expel_vampires = s.expel_vampires,
        accept_visitors = s.accept_visitors,
        clear_alerts = s.clear_alerts,
        camera = s.camera,
        camera_pace = s.camera_pace,
        answer_locations = s.answer_locations,
        hospital_burrow = s.hospital_burrow,       -- (0.104.168)
        wipe_learned = s.wipe_learned,
        wipe_learned_all = s.wipe_learned_all,
    }
end

---------------------------------------------------------------------------
-- Presets: named trait sets shared between forts, stored as JSON files.
---------------------------------------------------------------------------

local function preset_path(name)
    return PRESET_DIR .. '/' .. name .. '.json'
end

function valid_preset_name(name)
    return type(name) == 'string' and name:match('^[%w _%-]+$') ~= nil and #name <= 40
end

-- Ready-made fort characters (effective values, -200..200; past 100 is the
-- slider's extreme). A saved preset of the same name takes their place.
-- (0.99) Rebuilt on the graded sliders (0.96) so each is unmistakable, in
-- opposite pairs (War-hold and Monastery, Merchant city and Hermit hold,
-- Deep mine and Garden fort), and each carries the Rules choices that go
-- with it (BUILTIN_PRESET_RULES).
BUILTIN_PRESETS = {
    ['War-hold'] = {militarism = 150, fortification = 120, caution = 60, engineering = 60, justice = 80,
                    deference = 40, outsiders = -80, grandeur = -40, welfare = -40, piety = -30,
                    spacing = -60, mining = 40},
    ['Monastery'] = {piety = 150, welfare = 80, outsiders = 60, grandeur = 60, craftsmanship = 40,
                     militarism = -60, justice = -60, greed = -60, trade = -30, industriousness = -20},
    ['Merchant city'] = {trade = 120, greed = 80, outsiders = 100, craftsmanship = 60, stockpile = 40,
                         growth = 60, surface = 40, deference = 40},
    ['Hermit hold'] = {outsiders = -150, trade = -100, growth = -60, caution = 60, surface = -60,
                       deference = -60, greed = 40, stockpile = 60},
    ['Deep mine'] = {mining = 150, verticality = 120, surface = -100, engineering = 60, industriousness = 60,
                     caution = -40, spacing = -30, agriculture = -20},
    ['Garden fort'] = {agriculture = 120, husbandry = 80, surface = 80, welfare = 40, grandeur = 40,
                       piety = 20, mining = -60, militarism = -30},
}

-- (0.99) The Rules choices a preset brings (anything not named is left as
-- it is). Saved presets keep the same keys.
PRESET_RULE_KEYS = {'attack_policy', 'fill_squads', 'train_squads', 'gate_lever', 'fortify_entrances',
                    'build_gate_doors', 'accept_visitors', 'answer_locations', 'pasture_animals', 'make_gear',
                    'water_works', 'fort_goal'}
BUILTIN_PRESET_RULES = {
    ['War-hold'] = {attack_policy = 'all', fill_squads = true, train_squads = true, gate_lever = true,
                    fortify_entrances = true, levels = {garden = false}},
    ['Monastery'] = {attack_policy = 'never', levels = {barracks = false, archery = false, jail = false}},
    ['Merchant city'] = {accept_visitors = true, answer_locations = true},
    ['Hermit hold'] = {accept_visitors = false, answer_locations = false, fortify_entrances = true},
    ['Deep mine'] = {water_works = true, levels = {garden = false}},
    ['Garden fort'] = {pasture_animals = true, levels = {archery = false}},
}

local function apply_rules(merged, rules)
    if type(rules) ~= 'table' then return merged end
    for _, k in ipairs(PRESET_RULE_KEYS) do
        local v = rules[k]
        if v ~= nil and type(v) == type(merged[k]) then merged[k] = v end
    end
    if type(rules.levels) == 'table' and type(merged.levels) == 'table' then
        for k, v in pairs(rules.levels) do
            if type(v) == 'boolean' and merged.levels[k] ~= nil then merged.levels[k] = v end
        end
    end
    return sanitize(merged)
end

local function rules_of(s)
    local out = {levels = {}}
    for _, k in ipairs(PRESET_RULE_KEYS) do out[k] = s[k] end
    for k, v in pairs(s.levels or {}) do out.levels[k] = v end
    return out
end

-- A built-in preset as stored traits: {id = {value, extreme}}.
function builtin_traits(name)
    local b = BUILTIN_PRESETS[name]
    if not b then return nil end
    local out = {}
    for id, v in pairs(b) do
        if math.abs(v) > TRAIT_MAX then
            out[id] = {value = v // 2, extreme = true}
        else
            out[id] = {value = v, extreme = false}
        end
    end
    return out
end

function list_presets()
    local out, seen = {}, {}
    if dfhack.filesystem.isdir(PRESET_DIR) then
        for _, f in ipairs(dfhack.filesystem.listdir(PRESET_DIR) or {}) do
            local name = f:match('^(.*)%.json$')
            if name and not seen[name] then table.insert(out, name); seen[name] = true end
        end
    end
    for name in pairs(BUILTIN_PRESETS) do
        if not seen[name] then table.insert(out, name); seen[name] = true end
    end
    table.sort(out)
    return out
end

function save_preset(name, s)
    if not valid_preset_name(name) then return false, 'use letters, numbers, spaces, - or _' end
    dfhack.filesystem.mkdir_recursive(PRESET_DIR)
    local data = sanitize(s)
    json.encode_file({version = SETTINGS_VERSION, traits = data.traits, rules = rules_of(data)}, preset_path(name))
    return true
end

-- Applies a preset's traits and (0.99) the Rules choices it carries; keeps
-- the current activity and token settings.
function load_preset(name, s)
    if not valid_preset_name(name) then return nil, 'bad preset name' end
    local ok, data = pcall(json.decode_file, preset_path(name))
    if (not ok or type(data) ~= 'table') and BUILTIN_PRESETS[name] then
        ok, data = true, {traits = builtin_traits(name), rules = BUILTIN_PRESET_RULES[name]}
    end
    if not ok or type(data) ~= 'table' then return nil, 'could not read preset' end
    local merged = sanitize(s)
    merged.traits = sanitize({traits = data.traits}).traits
    return apply_rules(merged, data.rules)
end

if dfhack_flags.module then
    return
end

print(json.encode({ok = true, settings = for_ai(load_settings())}, {pretty = false}))
