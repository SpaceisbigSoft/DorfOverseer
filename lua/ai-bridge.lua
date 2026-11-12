-- ai-bridge: the AI's window into the fortress.
--
-- Usage (in the DFHack launcher, or from outside with dfhack-run):
--   ai-bridge version            versions, protocol and known actions
--   ai-bridge status             cheap check: in a fort? paused? date?
--   ai-bridge state              writes a full fort report to a JSON file
--   ai-bridge state --no-units   same, without the per-dwarf list (smaller)
--   ai-bridge state --tier pulse a small report (dwarves, stocks, threats,
--                                orders, projects...; never the units list)
--   ai-bridge state --tier daily the full report (the default); survey is
--                                the same for now
--   ai-bridge pause              pause the game (resume only via run, so
--                                the game can never be left running unattended)
--   ai-bridge run <ticks>        unpause, then pause again after <ticks>
--   ai-bridge act <json>         perform one action (see ACTIONS below)
--   ai-bridge watch              start the event feed (runs on map load)
--   ai-bridge events             hand over queued events, written to a file
--   ai-bridge map                cavern / magma / underworld layers and depths
--   ai-bridge probe_defence [x y z ...]  read-only: lever links, bridge, hatch
--                                and trap support, what's on the given tiles
--   ai-bridge memory             the overseer's memory from the save, written
--                                to memory-from-save.json (saved with the
--                                save_memory action from memory-to-save.json)
--   ai-bridge survey             staircases, the dwarves' busiest level and
--                                soil levels, as elevations (read-only; for
--                                the overseer's master plan)
--   ai-bridge modules            (0.105.26) loads every module and compiles
--                                every part; lists any that fail (self-test)
--
-- Every command prints exactly one line of JSON: {"ok": true, ...} or
-- {"ok": false, "error": "..."}. The fort report itself goes to a UTF-8 file
-- (dfhack-config/ai-overseer/state.json) because DF names can contain
-- characters that don't survive console output.
--
-- (13c) The bridge is in parts. This file keeps the commands, BRIDGE_VERSION,
-- the ACTIONS table (with DRY_OK and DISPLAY_ONLY, what may pass while the AI
-- is halted), the report's SECTIONS and their cache. Beside it, loaded into
-- its environment (BRIDGE_PARTS below): ai-bridge-report.lua (the report's
-- readers and the event feed), ai-bridge-orders.lua (work orders and tools),
-- ai-bridge-actions.lua (the other action handlers) and ai-bridge-probes.lua
-- (probes and screen recording). The five go to the game together.
--@ module = true

local json = require('json')
local utils = require('utils')

BRIDGE_VERSION = '0.105.39'
PROTOCOL = 1 -- bump when the report's shape changes in a breaking way

OUT_DIR = dfhack.getDFPath() .. '/dfhack-config/ai-overseer'   -- (a global: the parts write there too)
local STATE_FILE = OUT_DIR .. '/state.json'
local EVENTS_FILE = OUT_DIR .. '/events.json'
-- The overseer's memory travels through files (it's too big for a command line).
local MEMORY_FROM_SAVE = OUT_DIR .. '/memory-from-save.json'
MEMORY_KEY = 'ai-overseer/memory'          -- older bridges: everything in one table
MEMORY_KIND_PREFIX = 'ai-overseer/mem/'     -- now: one key per kind, as JSON text
MEMORY_KINDS = {'working', 'timeline', 'atlas', 'chronicle', 'knowledge'}

-- The bridge's shared helpers: globals, so its parts (below) use them too.
function txt(s)
    if s == nil then return nil end
    return dfhack.df2utf(s)
end

function reject(reason)
    return {ok = false, rejected = true, error = reason}
end

function sorted_keys(t)
    local out = {}
    for k in pairs(t) do table.insert(out, k) end
    table.sort(out)
    return out
end

function whole_number(v)
    return math.tointeger(tonumber(v))
end

-- A DF name in words (dfhack.TranslateName was renamed in DFHack 50.15).
function translate_name(name, english)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, english) end)
    if ok and s then return s end
    ok, s = pcall(function() return dfhack.TranslateName(name, english) end)
    return ok and s or nil
end

-- the game's time in ticks since year 0 (403,200 a year)
function abs_tick()
    return df.global.cur_year * 403200 + df.global.cur_year_tick
end

function int_in(v, lo, hi)
    local n = whole_number(v)
    if n == nil or n < lo or n > hi then return nil end
    return n
end

function in_fort()
    return dfhack.isMapLoaded() and dfhack.world.isFortressMode()
end

NOT_IN_FORT = {ok = false, error = 'no fortress is loaded (the game is at a menu or in another mode)'}

-- (13c) The bridge in parts, each a file beside this one (lua/), run in
-- this script's own environment, so their globals are the bridge's as when
-- they were one file. ACTIONS, SECTIONS, the commands and BRIDGE_VERSION
-- stay here. Read from this file's own folder (DFHack loads a script by its
-- path), else wherever DFHack finds them.
-- (D0) ai-bridge-design: the Design track's landmarks
BRIDGE_PARTS = {'ai-bridge-report', 'ai-bridge-orders', 'ai-bridge-actions', 'ai-bridge-probes', 'ai-bridge-design'}
-- (0.105.26) Each part carries a marker, PART_VERSIONS['<part>'] = '<version>',
-- the same string as BRIDGE_VERSION: one find-replace of the quoted version
-- across lua/*.lua bumps them all. `version` lists a part whose marker differs
-- (stale_parts): one left behind at delivery, or a builder part still loaded
-- from before.
PART_VERSIONS = PART_VERSIONS or {}

-- (0.105.26) `dfhack-run ai-bridge ...` runs this file again on every
-- command, and the parts with it (~364 KB). Their compiled chunks are kept
-- here (a global: DFHack keeps a script's environment between runs), by path
-- and modification time, so a part is compiled again only when its file
-- changes; it still runs every time. The chunk is bound to this environment
-- (the same table each run), so the env is kept and checked too.
PART_CHUNKS = PART_CHUNKS or {}

function part_chunk(path)
    local okm, mtime = pcall(function() return dfhack.filesystem.mtime(path) end)
    mtime = okm and mtime or nil
    local c = PART_CHUNKS[path]
    if c and mtime ~= nil and c.mtime == mtime and c.env == _ENV then return c.fn end
    local fn, err = loadfile(path, 't', _ENV)
    if not fn then error(err, 0) end
    PART_CHUNKS[path] = {fn = fn, mtime = mtime, env = _ENV}
    return fn
end

-- A bridge part's file: beside this one, else wherever DFHack finds it.
local HERE = tostring(debug.getinfo(1, 'S').source or ''):match('^@(.*[/\\])')
function bridge_part_path(name)
    local path = HERE and HERE .. name .. '.lua'
    local f = path and io.open(path, 'rb')
    if f then f:close() return path end
    return dfhack.findScript(name)
end

for _, name in ipairs(BRIDGE_PARTS) do
    local path = bridge_part_path(name)
    if not path then error(('ai-bridge: %s.lua is missing (it goes beside ai-bridge.lua)'):format(name)) end
    part_chunk(path)()
end

ACTIONS = {
    join_levels = act_join_levels,
    set_rules = act_set_rules,           -- (0.105.20) logs/rules-request.json
    apply_preset = act_apply_preset,     -- (0.105.4) keeper.py --preset
    census = act_census,
    clear_webs = act_clear_webs,
    remove_webs = act_remove_webs,       -- (0.105.3)
    scrub_dead_units = act_scrub_dead_units,
    scan_entrances = act_scan_entrances,
    build_gate_doors = act_build_gate_doors,
    fortify_entrance = act_fortify_entrance,
    arm_gates = act_arm_gates,
    link_lever = act_link_lever,
    place_traps = act_place_traps,
    place_gate_lever = act_place_gate_lever,          -- (0.105.12)
    build_gatehouse = act_build_gatehouse,            -- (0.105.23)
    unstick_gate = act_unstick_gate,                  -- (0.105.32)
    location_access = act_location_access,            -- (0.105.12)
    unpause = act_unpause,
    found_fort = act_found_fort,
    quiet_announcements = act_quiet_announcements,
    save_game = act_save_game,
    open_gates = act_open_gates,
    open_entrance = act_open_entrance,     -- (0.105.34)
    close_threatened_gates = act_close_threatened_gates,   -- (0.105.35) the watcher failing
    free_gate_jobs = act_free_gate_jobs,                   -- (0.105.35) a planned gate's suspended jobs
    setup_shelter = act_setup_shelter,
    refresh_shelter = act_refresh_shelter,       -- (0.105.26)
    set_population_cap = act_set_population_cap,
    expel_dwarf = act_expel_dwarf,
    pasture = act_pasture,
    nest_boxes = act_nest_boxes,             -- (0.104.80)
    train_war = act_train_war,               -- (0.104.81)
    dig_stairwell = act_dig_stairwell,       -- (0.104.82)
    dig_way_in = act_dig_way_in,             -- (0.105.32) an emergency way in for the stranded
    guard_gate = act_guard_gate,             -- (0.104.83)
    -- (0.105.0, round 2) an army that can fight
    fix_gear_gaps = act_fix_gear_gaps, assign_quivers = act_assign_quivers, squad_bolts = act_squad_bolts,
    shelter_squads = act_shelter_squads, cut_entrance = act_cut_entrance,
    gate_dogs = act_gate_dogs,               -- (0.104.83)
    make_pasture = act_make_pasture,
    import_orders = act_import_orders,
    squad_fill = act_squad_fill,
    squad_swap = act_squad_swap,          -- (0.104.65)
    pair_chairs = act_pair_chairs,        -- (0.104.77)
    recreation = act_recreation,          -- (0.104.78)
    hospital_burrow = act_hospital_burrow,   -- (0.104.167)
    calm_burrow = act_calm_burrow,           -- (0.104.169)
    -- (0.105.0) round 3: threats answered (lua/ai-threats.lua)
    fire_guard = act_fire_guard,
    prisoner_room = act_prisoner_room,
    moon_cell = act_moon_cell,
    seal_cavern = act_seal_cavern,
    accept_cups = act_accept_cups,           -- (0.104.168)
    rest_infected = act_rest_infected,       -- (0.104.168)
    traction_rest = act_traction_rest,       -- (0.105.24)
    mood_free_items = act_mood_free_items,   -- (0.105.24) a mood's forbidden or dumped materials freed
    add_doctor_post = act_add_doctor_post,   -- (0.104.168)
    squad_trim = act_squad_trim,
    squad_release = act_squad_release,
    quick_location = function(a)
        if a.kind ~= 'temple' and a.kind ~= 'tavern' then return reject('quick_location needs kind temple or tavern') end
        return reqscript('ai-builder').quick_location(a.kind, a.dry_run == true)
    end,
    assign_labor = act_assign_labor,
    appoint = act_appoint,
    place_surface = act_place_surface,
    build_crossing = act_build_crossing,
    remove_crossing = act_remove_crossing,
    place_keep = act_place_keep,
    -- (0.105.30) construction: a surface hall, the gatehouse's wing walls, soil floors finished
    place_hall = act_place_hall,
    build_wings = act_build_wings,
    floor_rooms = act_floor_rooms,
    deep_depot = act_deep_depot,                 -- (0.105.23)
    narrow_detail = act_narrow_detail,
    trim_labor = act_trim_labor,
    order_instrument = act_order_instrument,
    trim_instrument_orders = act_trim_instrument_orders,   -- (0.104.69)
    slaughter_one = act_slaughter_one,
    prune_remains = act_prune_remains,
    ledger_set = act_ledger_set,
    mark_run = act_mark_run,      -- (0.105.0) a scenario copy's run id
    make_squad = act_make_squad,
    mine_ore = act_mine_ore,
    clear_gate = act_clear_gate,
    bring_goods = act_bring_goods,
    unload_depot = act_unload_depot,
    kitchen_skill = act_kitchen_skill,
    place_slabs = act_place_slabs,
    free_slabs = act_free_slabs,
    restrict_water = act_restrict_water,
    trade_deal = act_trade_deal,
    squad_barracks = act_squad_barracks,
    call_trader = act_call_trader,
    feeder_pile = act_feeder_pile,
    idle_crafting = act_idle_crafting,
    give_trinkets = act_give_trinkets,
    house_dwarves = act_house_dwarves,   -- (0.104.168)
    furnish_liked = act_furnish_liked,   -- (E4) a piece a dwarf likes in their own room
    staff_location = act_staff_location,
    add_posts = act_add_posts,
    staff_labors = act_staff_labors,
    vacate_post = act_vacate_post,
    dismiss_alerts = act_dismiss_alerts,
    answer_petition = act_answer_petition,
    retarget_hall = act_retarget_hall,
    place_in_zone = act_place_in_zone,
    survey_water = act_survey_water,
    cistern_step = act_cistern_step,
    water_work = act_water_work,          -- (0.105.0) moat, pumps, irrigation, magma workshops
    remove_workshops = act_remove_workshops,
    open_trade = act_open_trade,
    close_trade = act_close_trade,
    close_meeting = act_close_meeting,
    answer_meeting = act_answer_meeting,  -- (0.105.0)
    send_mission = act_send_mission,      -- (0.105.24) Make contact by the World screen (lua/ai-mission-send.lua)
    keep_mousers = act_keep_mousers,      -- (0.104.168)
    water_zone = act_water_zone,
    sand_zone = act_sand_zone,
    give_room = act_give_room,
    gather_plants = act_gather_plants,
    farm_thresholds = act_farm_thresholds,
    set_farm_crops = act_set_farm_crops,   -- (0.105.5) each plot's crop set by the AI (Hammerstirred: fallow plots)
    kitchen_brewables = act_kitchen_brewables,   -- (0.100) cooking keeps brewables while drink is short
    unstick_uniforms = act_unstick_uniforms,
    break_fights = act_break_fights,
    free_stray_gear = act_free_stray_gear,   -- (0.104.58)
    assign_weapons = act_assign_weapons,     -- (0.104.60)
    assign_kit = act_assign_kit,             -- (0.105.8)
    trim_gathering = act_trim_gathering,
    squad_routine = act_squad_routine,
    set_uniform = act_set_uniform,
    petition_orders = act_petition_orders,
    adopt_uniform = act_adopt_uniform,
    set_uniform_weapon = act_set_uniform_weapon,
    allow_stone = act_allow_stone,
    quarry = act_quarry,
    polish = act_polish,
    squad_orders = act_squad_orders,
    pull_gate = act_pull_gate,
    work_order = act_work_order,
    cancel_work_order = act_cancel_work_order,
    approve_orders = act_approve_orders,
    unsuspend_orders = act_unsuspend_orders,
    unforbid_dead = act_unforbid_dead,
    allow_burial = act_allow_burial,
    bench_jobs = act_bench_jobs,
    clear_orphan_jobs = act_clear_orphan_jobs,
    order_slots = act_order_slots,
    kitchen_fat = act_kitchen_fat,
    convict = act_convict,
    repair_rooms = function(a) return reqscript('ai-builder').repair_rooms(a.dry_run == true) end,
    bootstrap_chair = act_bootstrap_chair,
    sync_offices = function(a) return reqscript('ai-nobles').sync_offices(a.dry_run == true) end,
    tool = act_tool,
    civ_alert = act_civ_alert,
    start_project = act_start_project,
    farm_plots = act_farm_plots,
    place_well = act_place_well,
    furnish_project = act_furnish_project,
    free_dig_jobs = act_free_dig_jobs,
    prioritize_dig = act_prioritize_dig,
    renew_well_dig = act_renew_well_dig,      -- (0.105.31)
    unmark_project_dig = act_unmark_project_dig,   -- (0.105.35) a level's marker-only dig tiles made real
    seal_well_stairs = act_seal_well_stairs,
    well_shaft = act_well_shaft,
    finish_project = act_finish_project,
    engrave_project = act_engrave_project,
    set_culture = act_set_culture,
    set_learned = act_set_learned,
    report_status = act_report_status,
    save_memory = act_save_memory,
    cancel_project = act_cancel_project,
    -- (0.105.27) disposal: the forbidden things lying about (lua/ai-disposal.lua)
    unforbid_items = act_unforbid_items,
    mark_melt = act_mark_melt,
    mark_dump = act_mark_dump,
    empty_dump = act_empty_dump,
    set_standing_orders = act_set_standing_orders,
    place_dump = act_place_dump,
    -- (0.105.40, 13e) world cleanup: what no dwarf can clean up (lua/ai-cleanup.lua)
    cleanup_items = act_cleanup_items,
    cleanup_units = act_cleanup_units,
    cleanup_spatter = act_cleanup_spatter,
    cleanup_dead_units = act_cleanup_dead_units,
    -- (0.105.40b, M6) the food store: a food pile near the kitchen and still, its barrels (lua/ai-food-store.lua)
    food_pile = act_food_pile,
    food_barrels = act_food_barrels,
    -- (D0) the Design track: a landmark's sites, its drawing built, its next stage (ai-bridge-design.lua)
    blueprint_sites = act_blueprint_sites,
    build_blueprint = act_build_blueprint,
    landmark_step = act_landmark_step,
}

-- (13c) The actions whose dry run changes nothing in the fort, all the way
-- down: their dry runs get through while the AI is halted (cmd_act). A new
-- action whose dry run is read-only goes here too. (Was a chain of names kept
-- by hand in cmd_act; farm_thresholds, unstick_uniforms and set_rules were
-- missing.) (0.105.26) Only these take a dry run at all: cmd_act refuses
-- dry_run for any other action, as their handlers ignored it and acted for
-- real. The second list was checked handler by handler (each one's dry run
-- returns before it changes anything); unpause, pull_gate and narrow_detail
-- (its widen writes before its dry-run return) are not on it.
DRY_OK = {}
for _, name in ipairs({
    'start_project', 'farm_plots', 'place_well', 'make_pasture', 'link_lever', 'save_game',
    'quiet_announcements', 'found_fort', 'assign_labor', 'gather_plants', 'trim_gathering', 'appoint',
    'place_surface', 'place_keep', 'deep_depot', 'make_squad', 'mine_ore', 'clear_gate', 'bring_goods',
    'unload_depot', 'kitchen_skill', 'place_slabs', 'give_room', 'set_uniform', 'adopt_uniform',
    'petition_orders', 'set_uniform_weapon', 'allow_stone', 'prioritize_dig', 'renew_well_dig', 'convict', 'quarry', 'polish',
    'trade_deal', 'call_trader', 'open_trade', 'close_trade', 'squad_barracks', 'feeder_pile',
    'idle_crafting', 'give_trinkets', 'staff_location', 'vacate_post', 'add_posts', 'staff_labors',
    'dismiss_alerts', 'place_in_zone', 'answer_petition', 'retarget_hall', 'remove_workshops',
    'survey_water', 'cistern_step', 'water_zone', 'sand_zone', 'water_work', 'set_farm_crops',
    'kitchen_brewables', 'farm_thresholds', 'unstick_uniforms', 'set_rules',
    -- (0.105.26) honoured all the way down, not listed before
    'accept_cups', 'add_doctor_post', 'allow_burial', 'answer_meeting', 'apply_preset', 'approve_orders',
    'assign_kit', 'assign_quivers', 'assign_weapons', 'bench_jobs', 'bootstrap_chair', 'break_fights',
    'build_crossing', 'build_gatehouse', 'calm_burrow', 'clear_orphan_jobs', 'clear_webs', 'close_meeting',
    'cut_entrance', 'dig_stairwell', 'fire_guard', 'fix_gear_gaps', 'free_slabs', 'free_stray_gear',
    'gate_dogs', 'guard_gate', 'hospital_burrow', 'house_dwarves', 'furnish_liked', 'join_levels', 'keep_mousers',
    'kitchen_fat', 'ledger_set', 'location_access', 'mark_run', 'mood_free_items', 'moon_cell', 'nest_boxes',
    'order_instrument', 'order_slots', 'pair_chairs', 'place_gate_lever', 'prisoner_room', 'prune_remains',
    'quick_location', 'recreation', 'remove_crossing', 'remove_webs', 'repair_rooms', 'rest_infected',
    'restrict_water', 'scrub_dead_units', 'seal_cavern', 'seal_well_stairs', 'send_mission', 'shelter_squads',
    'slaughter_one', 'squad_bolts', 'squad_release', 'squad_swap', 'squad_trim', 'sync_offices',
    'traction_rest', 'train_war', 'trim_instrument_orders', 'trim_labor', 'unforbid_dead',
    'unsuspend_orders', 'well_shaft',
    'refresh_shelter',   -- (0.105.26)
    -- (0.105.27) disposal: each dry run returns before it changes anything
    'unforbid_items', 'mark_melt', 'mark_dump', 'empty_dump', 'set_standing_orders', 'place_dump',
    -- (0.105.30) construction: each plans and returns before it places anything
    'place_hall', 'build_wings', 'floor_rooms',
    'open_entrance',     -- (0.105.34) its dry run checks the distance and changes nothing
    'close_threatened_gates', 'free_gate_jobs',   -- (0.105.35) each dry run only counts
    'unstick_gate',      -- (0.105.32) its dry run says what it would do, and changes nothing
    -- (0.105.32) the way in: planned (and quickfort's dry run) before anything is designated
    'dig_way_in',
    'unmark_project_dig',   -- (0.105.35) its dry run counts the marked tiles and changes nothing
    -- (D0) each checks the drawing (and quickfort's dry run) before it designates or places anything
    'build_blueprint', 'landmark_step',
    -- (0.105.40) world cleanup: each dry run counts and returns before it removes anything
    'cleanup_items', 'cleanup_units', 'cleanup_spatter', 'cleanup_dead_units',
    -- (0.105.40b, M6) the food store: each dry run finds the spot (quickfort's dry run) and changes nothing
    'food_pile', 'food_barrels',
}) do DRY_OK[name] = true end

-- These only change what's displayed, so they still work while halted, dry
-- run or not. (save_memory, ledger_set and (0.105.0) mark_run are the AI's own
-- bookkeeping, not a change to the fort; (0.105.4) apply_preset sets the
-- player's settings (keeper --preset), not the fort.)
DISPLAY_ONLY = {report_status = true, set_culture = true, set_learned = true, save_memory = true,
                ledger_set = true, mark_run = true, apply_preset = true,
                -- (D0) changes no tile: the sites it finds are kept in the AI's own site data
                blueprint_sites = true}

---------------------------------------------------------------------------
-- Time control. Globals (not locals) so they survive between script runs.
---------------------------------------------------------------------------

MAX_RUN_TICKS = 100800 -- one season

local function cancel_run()
    if run_timer_id then dfhack.timeout_active(run_timer_id, nil) end
    run_timer_id = nil
    run_until = nil
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------

function version_info()
    return {
        ok = true,
        bridge = 'ai-bridge',
        bridge_version = BRIDGE_VERSION,
        protocol = PROTOCOL,
        dfhack_version = dfhack.getDFHackVersion(),
        df_version = dfhack.getDFVersion(),
        world_loaded = dfhack.isWorldLoaded(),
        map_loaded = dfhack.isMapLoaded(),
        df_path = dfhack.getDFPath(),     -- the game's folder (saves are in save/)
        actions = sorted_keys(ACTIONS),
        -- (0.105.40) the commands this bridge knows (the brain sends `batch` only when listed)
        commands = BRIDGE_COMMANDS and sorted_keys(BRIDGE_COMMANDS) or nil,
        recipes = sorted_keys(ORDER_RECIPES),
        tools = sorted_keys(TOOL_ALLOWLIST),
        level_kinds = reqscript('ai-layouts').KINDS,
        stockpiles = sorted_keys(reqscript('ai-layouts').STOCKPILES),
        workshops = sorted_keys(reqscript('ai-layouts').WORKSHOPS),
        -- (0.105.26) parts whose version mark isn't BRIDGE_VERSION (nil: none)
        stale_parts = (function() local s = stale_parts(); return #s > 0 and s or nil end)(),
        -- (D0) ai-blueprints' limits and legend items, for brain/blueprint.py's mirror check
        blueprint_limits = (blueprint_mirror()),
        blueprint_items = select(2, blueprint_mirror()),
    }
end

-- (0.105.26) Every module the AI's Lua is made of (lua/*.lua with
-- `--@ module = true`, but this one and the parts, which are no modules);
-- `modules` loads each. tests/test_fix26_bridge.py keeps it in step with lua/.
BRIDGE_MODULES = {
    'ai-blueprints', 'ai-builder', 'ai-camera', 'ai-census', 'ai-cleanup', 'ai-constructions', 'ai-diplomacy', 'ai-disposal', 'ai-food-store', 'ai-gates', 'ai-health', 'ai-homes',
    'ai-industry', 'ai-joins', 'ai-labor', 'ai-layouts', 'ai-military', 'ai-military-gear',
    'ai-mission-send', 'ai-missions', 'ai-moods', 'ai-nobles', 'ai-overlay', 'ai-overseer-settings',
    'ai-ping', 'ai-reports', 'ai-society', 'ai-society-burrows', 'ai-status', 'ai-threats', 'ai-title',
    'ai-trade', 'ai-util', 'ai-water', 'ai-waterworks', 'gui/ai-overseer',
}
-- the split-off modules that carry a version mark of their own
MARKED_MODULES = {'ai-military-gear', 'ai-society-burrows', 'ai-constructions'}

-- (13e) The modules split into a hub and parts beside it, each listing its
-- parts in PARTS and marking them in PART_VERSIONS
SPLIT_MODULES = {'ai-builder', 'ai-gates'}

-- A split module's parts by name ('ai-builder-sites', ...): from the loaded
-- hub, else read from its file (a hub that fails to load).
function split_part_names(mod)
    local parts
    local ok, B = pcall(reqscript, mod)
    if ok and type(B) == 'table' and type(B.PARTS) == 'table' then
        parts = B.PARTS
    else
        pcall(function()
            local f = io.open(bridge_part_path(mod), 'rb')
            local src = f:read('*a')
            f:close()
            local list = src:match('\nPARTS = (%b{})')
            parts = {}
            for p in list:gmatch("'([%w_-]+)'") do table.insert(parts, p) end
        end)
    end
    local out = {}
    for _, p in ipairs(parts or {}) do table.insert(out, mod .. '-' .. p) end
    return out
end

-- The builder's parts by name ('ai-builder-sites', ...).
function builder_part_names() return split_part_names('ai-builder') end

-- (0.105.26) The parts whose version mark isn't BRIDGE_VERSION, as
-- 'name (mark)': a file left behind at delivery, or (the builder's) still the
-- one loaded before it changed (touch ai-builder.lua, ai-gates.lua). The bridge's own parts
-- run each command, so theirs is the file's.
function stale_parts()
    local out = {}
    local function check(name, marks)
        local v = type(marks) == 'table' and marks[name] or nil
        if v ~= BRIDGE_VERSION then table.insert(out, ('%s (%s)'):format(name, v and tostring(v) or 'no version mark')) end
    end
    for _, n in ipairs(BRIDGE_PARTS) do check(n, PART_VERSIONS) end
    for _, mod in ipairs(SPLIT_MODULES) do
        local okb, B = pcall(reqscript, mod)
        if okb then
            check(mod, B.PART_VERSIONS)
            for _, n in ipairs(split_part_names(mod)) do check(n, B.PART_VERSIONS) end
        else
            table.insert(out, mod .. ' (does not load: ' .. tostring(B):sub(1, 160) .. ')')
        end
    end
    for _, m in ipairs(MARKED_MODULES) do
        local ok, M = pcall(reqscript, m)
        if ok then check(m, M.PART_VERSIONS)
        else table.insert(out, m .. ' (does not load: ' .. tostring(M):sub(1, 160) .. ')') end
    end
    return out
end

-- ai-bridge modules: (0.105.26) every module loaded (reqscript) and every
-- part's file compiled, for the self-test: a broken module or part showed only
-- as a report section's error, or not at all. {ok, modules, parts, failed =
-- {{name, error}...}, stale_parts}; ok is false when anything failed.
local function cmd_modules()
    local failed, loaded = {}, 0
    for _, m in ipairs(BRIDGE_MODULES) do
        local ok, err = pcall(reqscript, m)
        -- compiled too: a module whose load failed once is not loaded again
        -- by DFHack until its file changes (reqscript then hands back what it
        -- got of it, without the error), so a file that doesn't compile is
        -- caught here every time
        if ok then
            local okp, path = pcall(function() return dfhack.findScript(m) end)
            local fn, cerr = true, nil
            if okp and path then fn, cerr = loadfile(path, 't', {}) end
            if fn then loaded = loaded + 1 else ok, err = false, cerr end
        end
        if not ok then table.insert(failed, {name = m, error = tostring(err):sub(1, 300)}) end
    end
    local parts = {}
    for _, n in ipairs(BRIDGE_PARTS) do table.insert(parts, n) end
    for _, mod in ipairs(SPLIT_MODULES) do
        local names = split_part_names(mod)
        for _, n in ipairs(names) do table.insert(parts, n) end
        if #names == 0 then table.insert(failed, {name = mod, error = 'its list of parts could not be read'}) end
    end
    for _, n in ipairs(parts) do
        local path = bridge_part_path(n)
        if not path then
            table.insert(failed, {name = n, error = n .. '.lua is missing'})
        else
            local fn, err = loadfile(path, 't', {})     -- compiled only: the hub runs it
            if not fn then table.insert(failed, {name = n, error = tostring(err):sub(1, 300)}) end
        end
    end
    local stale = stale_parts()
    return {ok = #failed == 0 and #stale == 0, modules = loaded, parts = #parts,
            failed = #failed > 0 and failed or nil, stale_parts = #stale > 0 and stale or nil}
end

-- Run one section of the report; if it fails, keep the rest of the report
-- and put the error where that section would have been.
local function safe(fn, ...)
    local ok, result = pcall(fn, ...)
    if ok then return result end
    return {error = tostring(result)}
end

-- (0.105.33) which fort a per-site memory belongs to: the save folder and the
-- site, so a save of the same site id (another copy, another world) loaded in
-- the same DF session is not taken for the fort seen before
function fort_key()
    local okd, dir = pcall(function() return df.global.world.cur_savegame.save_dir end)
    return tostring(okd and dir or '?') .. '#' .. tostring(df.global.plotinfo.site_id)
end

-- The report's sections: name -> function(ctx) returning that section.
-- ctx.dwarves / ctx.units come from one get_dwarves call shared by both.
SECTIONS = {   -- (0.100) a module field: the tests swap in their own
    bridge_version = function() return BRIDGE_VERSION end,
    -- (0.105.33) the plain reads are wrapped too: one throw used to lose the whole report
    paused = function() return safe(function() return df.global.pause_state end) end,
    fort = function()
        return safe(function()
            local okw, world = pcall(function() return txt(translate_name(df.global.world.world_data.name)) end)
            local okn, name = pcall(function()
                return txt(translate_name(df.world_site.find(df.global.plotinfo.site_id).name, true))
            end)
            return {save_dir = df.global.world.cur_savegame.save_dir,
                    site_id = df.global.plotinfo.site_id,
                    world = okw and world or nil,
                    name = okn and name or nil,
                    run_id = run_mark()}       -- (0.105.0) a scenario copy's mark, or nil
        end)
    end,
    date = function() return safe(get_date) end,
    wealth = function() return safe(function() return df.global.plotinfo.tasks.wealth.total end) end,
    dwarves = function(ctx) return ctx.dwarves end,
    units = function(ctx) return ctx.units end,
    stocks = function() return safe(get_stocks) end,
    supplies = function() return safe(get_supplies) end,
    dead = function() return safe(get_dead) end,
    -- (0.104.20) rooms whose walls were dug open
    room_gaps = function() return safe(function() return reqscript('ai-builder').room_gaps_report() end) end,
    planned = function() return safe(function() return reqscript('ai-builder').planned_report() end) end,   -- (0.104.154)
    justice = function() return safe(get_justice) end,
    society = function() return safe(get_society) end,
    entrances = function() return safe(function() return reqscript('ai-gates').summary() end) end,
    military = function() return safe(function() return reqscript('ai-military').report(txt) end) end,
    moods = function() return safe(get_moods) end,
    buildings = function() return safe(get_buildings) end,
    jobs = function() return safe(get_jobs) end,
    others_on_map = function() return safe(get_others_on_map) end,
    deep = function() return safe(get_deep) end,
    -- (0.104.95, 13b) the fort's world-map missions, read only (lua/ai-missions.lua)
    -- (0.105.24) with `send`: the World-screen sender's run under way and its last outcome
    missions = function() return safe(function()
        local r = reqscript('ai-missions').report()
        local oks, send = pcall(function() return reqscript('ai-mission-send').status() end)
        if oks then r.send = send end
        return r
    end) end,
    needs = function() return safe(get_needs) end,
    hazards = function() return safe(get_hazards) end,
    -- (0.105.0) round 3: fire places, prisoners, thieves, undead, werebeasts, the wounded (lua/ai-threats.lua)
    threats = function() return safe(function() return reqscript('ai-threats').survey(txt) end) end,
    health = function() return safe(get_health) end,
    -- (0.104.168) the infected: untreated, bleeding, beds free (lua/ai-health.lua)
    infection = function() return safe(function() return reqscript('ai-health').survey(txt) end) end,
    -- the last water survey (lua/ai-water.lua), from the save: no scan here
    water = function()
        return safe(function()
            -- (0.105.38 third review) a copy without the river's blocks (kept
            -- in the save for a frozen river later, not sent to the brain)
            local w = reqscript('ai-water').report_copy()
            -- a survey under way (in slices): the planner asks for the next slice
            if reqscript('ai-water').scanning() or WATER_PLAN then w.scanning = true end
            local okc, st = pcall(function() return reqscript('ai-builder').cistern_status() end)
            w.cistern_status = okc and st or nil
            return w
        end)
    end,
    -- (0.105.0) the water works and magma workshops: each one's stage, and the refusals
    waterworks = function() return safe(function() return reqscript('ai-waterworks').report() end) end,
    -- (13c) a feeder or storage survey that failed is not kept for 3 days
    -- (the second value: don't cache), only the next report tries it again
    logistics = function()
        local r = safe(function()
            local B = reqscript('ai-builder')
            local okf, feeders = pcall(B.feeder_survey)
            local oks, storage = pcall(B.storage_survey)
            local counts = {}
            pcall(function()
                counts.items = #df.global.world.items.all
                counts.units = #df.global.world.units.active
                local n, link = 0, df.global.world.jobs.list.next
                while link do n = n + 1; link = link.next end
                counts.jobs = n
            end)
            return {feeders = okf and feeders or {error = tostring(feeders):sub(1, 160)},
                    storage = oks and storage or {error = tostring(storage):sub(1, 160)},
                    counts = counts}
        end)
        return r, r.error == nil and (type(r.feeders) == 'table' and r.feeders.error ~= nil
                                      or type(r.storage) == 'table' and r.storage.error ~= nil)
    end,
    map = function()
        local okh, size, off = pcall(function()
            -- add to a z-level to get the elevation the game shows on screen
            return {dfhack.maps.getTileSize()}, df.global.world.map.region_z - 100
        end)
        return {
            size = okh and size or nil,
            elevation_offset = okh and off or nil,
            error = (not okh) and tostring(size) or nil,   -- (0.105.33) the header failed: said
            layers = safe(layers_summary),
            dwarves = safe(get_dwarf_levels),
        }
    end,
    nobles = function() return safe(get_nobles) end,
    mandates = function() return safe(get_mandates) end,
    civ_alert = function() return safe(function() return df.global.plotinfo.alerts.civ_alert_idx ~= 0 end) end,
    -- Read directly: gui/civ-alert's can_sound_alarm() creates alert
    -- entries when they're missing, and a report must not change the game.
    civ_alert_ready = function()
        return safe(function()
            local l = df.global.plotinfo.alerts.list
            return (#l >= 2 and #l[1].burrows > 0)
                or df.global.plotinfo.alerts.civ_alert_idx ~= 0
        end)
    end,
    -- (0.105.36 fix) whose burrow the civilian alert sends citizens to: 'ai'
    -- (the AI shelter only), 'player' (a burrow of the player's), 'none'.
    -- Read directly, as civ_alert_ready (nothing created)
    civ_alert_shelter = function()
        return safe(function()
            local l = df.global.plotinfo.alerts.list
            if #l < 2 or #l[1].burrows == 0 then return 'none' end
            local names = {}
            for _, b in ipairs(df.global.plotinfo.burrows.list) do names[b.id] = tostring(b.name):lower() end
            for _, id in ipairs(l[1].burrows) do
                if names[id] ~= 'ai shelter' then return 'player' end
            end
            return 'ai'
        end)
    end,
    orders = function() return safe(get_orders) end,
    -- (0.101.6) why orders don't start (get_order_desk)
    order_desk = function() return safe(get_order_desk) end,
    stone_types = function() return safe(get_stone_types) end,
    -- stone the masons may use, and the economic stone lying about
    stone_use = function() return safe(get_stone_use) end,
    locations = function() return safe(get_locations) end,
    petitions = function() return safe(get_petitions) end,
    diplomacy = function() return safe(get_diplomacy) end,
    meetings = function() return safe(get_meetings) end,
    -- (0.105.0, 12b) the world outside: civs at war or peace, sieges, tribute,
    -- the caravans' trade agreements, the meeting screen (lua/ai-diplomacy.lua)
    world = function() return safe(function() return reqscript('ai-diplomacy').world_report(txt) end) end,
    -- (0.88) the alert icons down the left of the screen, by type (lua/ai-reports.lua)
    alerts = function() return safe(function() return reqscript('ai-reports').alerts_report() end) end,
    projects = function() return safe(function() return reqscript('ai-builder').projects_report() end) end,
    -- every AI project on record, with where it is (small: ids and boxes)
    registry = function() return safe(function() return reqscript('ai-builder').registry_report() end) end,
    -- (D0) the Design track's landmarks: name, purpose, status, stage, levels (ai-bridge-design.lua)
    landmarks = function() return safe(get_landmarks) end,
    farms = function() return safe(function() return reqscript('ai-builder').farms_report() end) end,
    -- (0.101) water on the surface and the crossings over it (weekly: slow, changes slowly)
    crossings = function() return safe(function() return reqscript('ai-builder').crossings_report() end) end,
    -- a fresh embark: has the fort a staircase yet (lua/ai-builder.lua found_fort)?
    founding = function()
        return safe(function()
            -- (0.100) a fort with its staircase keeps it: the scan (up to 12
            -- levels across the fort, ~12 ms a report) runs until it's found,
            -- then not again this session for that site
            -- (0.105.33) keyed by save and site, and forgotten when the map
            -- unloads: a fresh copy of a site seen earlier is scanned again
            local site = fort_key()
            if FOUNDED_SITE == site then return {stairs = true, near = FOUNDED_NEAR} end
            local B = reqscript('ai-builder')
            local c = B.found_center()
            local stairs = B.has_staircase()
            if stairs then FOUNDED_SITE, FOUNDED_NEAR = site, c and c.what or nil end
            return {stairs = stairs, near = c and c.what or nil}
        end)
    end,
    -- who digs: miners, picks, digging waiting (lua/ai-labor.lua)
    labor = function() return safe(function() return reqscript('ai-labor').survey() end) end,
    -- caravans, the depot and goods for it (lua/ai-trade.lua)
    trade = function() return safe(function() return reqscript('ai-trade').survey(txt) end) end,
    -- uncovered ore near the fort, by metal (lua/ai-industry.lua)
    industry = function() return safe(function() return reqscript('ai-industry').survey() end) end,
    -- the fort's offices: holders, vacancies (lua/ai-nobles.lua)
    offices = function() return safe(function() return reqscript('ai-nobles').survey(txt) end) end,
    -- the rooms the nobles' offices ask for and don't have (lua/ai-nobles.lua)
    noble_rooms = function() return safe(function() return reqscript('ai-nobles').rooms_survey(txt) end) end,
    -- (0.104.168) the households: who has a bedroom, couples in one room or two, who slept rough (lua/ai-homes.lua)
    homes = function() return safe(function() return reqscript('ai-homes').census(nil, txt) end) end,
    -- (E4) the citizens' personalities, dreams and likes, summed (lua/ai-homes.lua citizens_taste)
    citizens_taste = function() return safe(function() return reqscript('ai-homes').citizens_taste(nil, txt) end) end,
    tools = function() return safe(get_tools) end,
    -- the player's settings from the control panel (gui/ai-overseer)
    settings = function()
        return safe(function()
            local S = reqscript('ai-overseer-settings')
            local out = S.for_ai(S.load_settings())
            out.preset = S.current_preset()     -- (0.105.4) the preset last applied (window or keeper)
            return out
        end)
    end,
    events_waiting = function() return #EVENT_QUEUE end,
    -- (0.104.0) the AI's ledger, as saved with this game
    ledger = function() return safe(ledger_data) end,
    recent_announcements = function() return safe(get_recent_announcements, 15) end,
    -- (0.105.27) the dump zones, the melt and dump marks, the smelters, the
    -- seal and the siege (lua/ai-disposal.lua); cached a day, cleared by the
    -- disposal actions
    disposal = function() return safe(function() return reqscript('ai-disposal').report() end) end,
    -- (0.105.40, 13e) world cleanup: items by state, the unreachable ones and
    -- creatures and for how long, spatter, the dead units (lua/ai-cleanup.lua).
    -- Not in SECTION_CACHE_DAYS: the module walks in slices of its own budget
    -- (a pass spans many reports; a new one starts a game day after the last
    -- started at the soonest) and sends its last finished pass between
    cleanup = function() return safe(function() return reqscript('ai-cleanup').report() end) end,
    -- (0.105.40b, M6) the food store: the piles that take food (barrels, size,
    -- fullness, the AI's own), the kitchens and stills, the food lying out of
    -- piles and barrels and the rotten (lua/ai-food-store.lua; cached a day)
    food_store = function() return safe(function() return reqscript('ai-food-store').report() end) end,
    -- (0.105.30) what the fort has built: finished constructions by shape and
    -- material, above or below ground, roofed surface tiles, the waiting ones
    -- and the AI's own (lua/ai-constructions.lua; one pass, every 3 days)
    -- (0.105.33) after an action cleared it, the module's own day-long survey
    -- cache is passed by too (else the "read again" copy was up to a day old)
    constructions = function()
        local fresh = CONSTRUCTIONS_FRESH == true
        local r = safe(function() return reqscript('ai-constructions').survey(fresh) end)
        if fresh and not (type(r) == 'table' and r.error) then CONSTRUCTIONS_FRESH = nil end
        return r
    end,
}

-- The pulse: a small report for the frequent check between full ones.
PULSE_SECTIONS = {
    'bridge_version', 'paused', 'fort', 'date', 'wealth', 'dwarves', 'stocks',
    'others_on_map', 'civ_alert', 'civ_alert_ready', 'civ_alert_shelter', 'orders', 'projects', 'entrances',
    'moods', 'military', 'settings', 'events_waiting', 'hazards', 'ledger',
}
TIERS = {pulse = true, daily = true, survey = true}
-- report sections rebuilt only every so many game days (the lag pass, Oct 23:
-- each full report froze the game ~0.5 s; these walk every item or stockpile)
SECTION_CACHE_DAYS = {logistics = 3, industry = 7,   -- industry: 300-450 ms live (veins and every boulder)
    -- (0.100) slow and slow-changing, read only for slow decisions: rebuilt
    -- in rotation (SECTION_REBUILDS a report, the stalest first), so no one
    -- report pays for all of them (region2: a full report froze ~250 ms)
    -- (supplies isn't cached: "have + queued" rules read it against live
    -- orders, and a stale count made them order twice; review 24 Oct)
    room_gaps = 3, planned = 1, needs = 1, registry = 3, noble_rooms = 3, locations = 2, petitions = 2, diplomacy = 7, crossings = 7,
    missions = 1,   -- (0.104.95) every world site walked
    homes = 1,      -- (0.104.168) each citizen's thoughts and every bedroom zone read
    citizens_taste = 3,   -- (E4) each citizen's soul and the free furniture read
    disposal = 1}   -- (0.105.27) every item in play walked once for the marks
SECTION_CACHE_DAYS.constructions = 3   -- (0.105.30) every built tile walked once
SECTION_CACHE_DAYS.food_store = 1      -- (0.105.40b, M6) every food item walked once
SECTION_REBUILDS = 2       -- expired cached sections rebuilt in one report (a missing one always is)
-- (0.100) the cached sections each action changes (cleared when it succeeds)
CACHE_INVALIDATES = {
    place_in_zone = {'justice'}, convict = {'justice'},
    give_room = {'noble_rooms'}, appoint = {'noble_rooms'}, quick_location = {'locations'},
    send_mission = {'missions'},   -- (0.105.24) the sender's status read again
    add_posts = {'locations'}, staff_location = {'locations'}, vacate_post = {'locations', 'health'}, retarget_hall = {'locations', 'registry'},
    answer_petition = {'petitions', 'locations'}, petition_orders = {'petitions'},
    give_trinkets = {'needs'}, idle_crafting = {'needs'}, unload_depot = {'needs'},
    keep_mousers = {'needs'},     -- (0.104.168) the cats kept: read again
    -- (review) furnishing makes the temple, hospital, offices and rooms: the
    -- rules that read locations and noble_rooms would start a second level
    start_project = {'registry'}, furnish_project = {'registry', 'locations', 'noble_rooms'},
    finish_project = {'registry', 'locations', 'noble_rooms'},
    cancel_project = {'registry', 'locations', 'noble_rooms'}, engrave_project = {'registry'},
    build_crossing = {'crossings'}, remove_crossing = {'crossings'},
    unforbid_dead = {'dead'}, allow_burial = {'dead'}, repair_rooms = {'room_gaps'},
    -- (0.104.141) a pile placed: the cached logistics section said "none" for
    -- 3 days and the rule asked again each cycle (17 refusals in 1.5 h)
    feeder_pile = {'logistics'},
    add_doctor_post = {'locations'},   -- (0.104.168)
    house_dwarves = {'homes', 'noble_rooms'},   -- (0.104.168)
    furnish_liked = {'homes', 'citizens_taste'},   -- (E4)
}
CACHE_INVALIDATES.set_farm_crops = {'farms'}   -- (0.105.5) the plots' crops read again
CACHE_INVALIDATES.accept_cups = {'needs'}       -- (0.104.168) the cups census shows what it changed
CACHE_INVALIDATES.mood_free_items = {'moods'}  -- (0.105.24) what the mood can reach now
CACHE_INVALIDATES.location_access = {'locations'}  -- (0.105.26) shut places read shut, not "opened by you"
-- (0.105.27) the disposal section read again after each disposal action
for _, name in ipairs({'unforbid_items', 'mark_melt', 'mark_dump', 'empty_dump', 'place_dump'}) do
    CACHE_INVALIDATES[name] = {'disposal'}
end
CACHE_INVALIDATES.set_standing_orders = {'disposal', 'dead'}
-- (0.105.40 review) world cleanup: items deleted (the disposal marks and dump
-- counts, industry's boulders and stocks), creatures vaporized (disposal's
-- invaders), dead units off the active list; the spatter is in no cached section
CACHE_INVALIDATES.cleanup_items = {'disposal', 'industry'}
CACHE_INVALIDATES.cleanup_units = {'disposal'}
CACHE_INVALIDATES.cleanup_dead_units = {'disposal', 'dead'}
CACHE_INVALIDATES.food_pile = {'food_store', 'logistics'}   -- (0.105.40b, M6) the new pile read again
CACHE_INVALIDATES.food_barrels = {'food_store'}
CACHE_INVALIDATES.renew_well_dig = {'registry'}   -- (0.105.31) as start_project
CACHE_INVALIDATES.build_blueprint = {'registry'}   -- (D0) a landmark's levels are projects
CACHE_INVALIDATES.landmark_step = {'registry'}
-- (0.105.30) construction placed: the waiting count read again
for _, name in ipairs({'place_hall', 'build_wings', 'floor_rooms', 'place_keep'}) do
    CACHE_INVALIDATES[name] = {'constructions'}
end
SECTION_CACHE = SECTION_CACHE or {}
-- (0.104.8) a new bridge starts with an empty cache: DFHack keeps a script's
-- globals across runs, so a section cached by older code (0.104.7's
-- instruments with raw names) outlived the fix for 28 days
if SECTION_CACHE_VERSION ~= BRIDGE_VERSION then
    SECTION_CACHE = {}
    SECTION_CACHE_VERSION = BRIDGE_VERSION
end

-- tier: 'pulse' (PULSE_SECTIONS only), or 'daily' / 'survey' (everything;
-- survey is the same as daily for now). Default daily.
local build_state_body
function build_state(include_units, tier)
    -- (0.105.40 E3) the report's shared walks (REPORT_CTX, lua/ai-util.lua),
    -- cleared however the report ends: an action after it walks afresh
    report_ctx_begin()
    local ok, state = pcall(build_state_body, include_units, tier)
    report_ctx_end()
    REPORT_MEMO = nil
    if not ok then error(state, 0) end
    return state
end

build_state_body = function(include_units, tier)
    tier = tier or 'daily'
    local names
    if tier == 'pulse' then
        names = PULSE_SECTIONS
        include_units = false
    else
        names = sorted_keys(SECTIONS)
    end
    local ctx = {}
    local clock = os.clock
    local t0 = clock()
    REPORT_MEMO = {}       -- (13c) lists more than one section reads, walked once
    -- (0.105.33) a throw here no longer loses the whole report: the section
    -- says it failed (the brain plans nothing without it) and the rest is sent
    local okd, dw, units = pcall(get_dwarves, include_units)
    if okd then
        ctx.dwarves, ctx.units = dw, units
    else
        ctx.dwarves = {error = tostring(dw)}
        ctx.units = include_units and {error = tostring(dw)} or nil
    end
    -- how long each section takes inside the game (the lag pass, Oct 23):
    -- sections over 5 ms, in the report's _timing
    local timing = {dwarves = math.floor((clock() - t0) * 1000 + 0.5)}
    local state = {}
    local now = abs_tick()
    local site = fort_key()     -- (0.105.33) save and site: another save of the same site id is another fort
    -- (0.100) which expired cached sections are rebuilt this time: the
    -- stalest SECTION_REBUILDS of them; the rest send their last copy a
    -- report longer (a section never built, or from another site, always is)
    local rebuild = {}
    do
        local due = {}
        for _, name in ipairs(names) do
            local days, c = SECTION_CACHE_DAYS[name], SECTION_CACHE[name]
            if days and c and c.site == site and now >= c.tick and now - c.tick >= days * 1200 then
                table.insert(due, {name = name, age = now - c.tick})
            end
        end
        table.sort(due, function(a, b) return a.age > b.age end)
        for i = 1, math.min(SECTION_REBUILDS, #due) do rebuild[due[i].name] = true end
    end
    -- (0.105.40, 13e) every section's time (os.clock, ms) and the ones sent
    -- from the cache, for the perf section built last
    local perf_ms, perf_cached = {}, {}
    for _, name in ipairs(names) do
        local t = clock()
        -- slow sections that change slowly are rebuilt only every few game
        -- days (SECTION_CACHE_DAYS); between, the last copy is sent
        local days, c = SECTION_CACHE_DAYS[name], SECTION_CACHE[name]
        local fresh = c and c.site == site and now >= c.tick
        if days and fresh and (now - c.tick < days * 1200 or not rebuild[name]) then
            state[name] = c.value
            perf_cached[name] = true
        else
            -- a section may return a second value, true: don't keep this copy
            -- (logistics with a part that failed)
            local v, nocache = SECTIONS[name](ctx)
            state[name] = v
            if days and not nocache and not (type(v) == 'table' and v.error) then   -- (an error is tried again next time)
                SECTION_CACHE[name] = {tick = now, site = site, value = v}
            end
        end
        local dt = (clock() - t) * 1000
        local ms = math.floor(dt + 0.5)
        if ms >= 5 then timing[name] = ms end
        perf_ms[name] = math.floor(dt * 10 + 0.5) / 10
    end
    state.perf = perf_section(perf_ms, perf_cached, (clock() - t0) * 1000, now)
    REPORT_MEMO = nil
    state.tier = tier
    state._timing = timing
    return state
end

-- (0.105.40, 13e) The perf section: what this report cost the game. Built
-- last, from numbers already measured (no walk of its own); never fails the
-- report. sections: ms per section this report (0.1 ms, a cached one is
-- the time to hand its copy over); cached: the sections sent from the cache;
-- total_ms: the whole report so far (the dwarves' walk included); the
-- shared walks of units and items this report (REPORT_CTX's counters, 0
-- where nothing counts them); the game's FPS; the absolute tick.
function perf_section(sections, cached, total_ms, tick)
    local ok, r = pcall(function()
        -- (merge) the counters live in ai-util's REPORT_CTX.walks (E3)
        local okc, ctx = pcall(function() return reqscript('ai-util').REPORT_CTX end)
        local w = okc and type(ctx) == 'table' and type(ctx.walks) == 'table' and ctx.walks or {}
        local walks = {units_walks = w.units, items_walks = w.items}
        if w.units == nil and type(REPORT_CTX) == 'table' then walks = REPORT_CTX end
        local fps_ok, fps = pcall(function() return df.global.enabler.calculated_fps end)
        return {
            sections = sections, cached = cached,
            total_ms = math.floor(total_ms * 10 + 0.5) / 10,
            units_walks = tonumber(walks.units_walks) or 0,
            items_walks = tonumber(walks.items_walks) or 0,
            fps = fps_ok and tonumber(fps) or nil,
            game_tick = tick,
        }
    end)
    if ok then return r end
    return {error = tostring(r)}
end

local function ensure_watching()
    if WATCHING ~= BRIDGE_VERSION then start_watching() end
end

local function cmd_status()
    if not in_fort() then
        return {ok = true, in_fort = false, world_loaded = dfhack.isWorldLoaded()}
    end
    local remaining = nil
    if run_timer_id and dfhack.timeout_active(run_timer_id) and run_until then
        remaining = math.max(0, run_until - abs_tick())
    end
    ensure_watching()
    local st = reqscript('ai-status')
    st.mark_seen()
    return {
        ok = true, in_fort = true, paused = df.global.pause_state,
        date = get_date(), run_ticks_remaining = remaining,
        events_waiting = #EVENT_QUEUE,
        -- in-game controls: the halt switch, and your answers to the co-pilot
        halted = st.is_halted(),
        decisions = st.decisions(),
        -- simulation and graphics frames per second, as DF measures them
        fps = df.global.enabler.calculated_fps,
        gfps = df.global.enabler.calculated_gfps,
        -- DF's trade screen holds time still while it's open (seen 0.58.0): the
        -- overseer trades then without waiting for the next day
        trade_open = trade_screen_open(),
        -- (0.104.138) DF saving itself: time stands still and calls wait (99% of
        -- the keeper's "DFHack did not answer" lines fell in seasonal autosaves)
        saving = saving_now() or nil,
        -- (0.105.0) DF's meeting screen is open (the overseer answers it)
        meeting = meeting_focus() ~= nil or nil,
    }
end

function trade_screen_open()
    local ok, v = pcall(function() return df.global.game.main_interface.trade.open end)
    return ok and v == true
end

local function cmd_state(args)
    if not in_fort() then return NOT_IN_FORT end
    ensure_watching()
    local flags = utils.invert(args)
    local include_units = not flags['--no-units']
    local tier = 'daily'
    if flags['--tier'] then
        tier = args[flags['--tier'] + 1]
        if not TIERS[tier] then return reject('--tier must be pulse, daily or survey') end
    end
    local start = os.clock()
    local state = build_state(include_units, tier)
    local built = os.clock()
    dfhack.filesystem.mkdir_recursive(OUT_DIR)
    json.encode_file(state, STATE_FILE, {pretty = false})
    -- the five slowest sections, and the time to write the file, for bridge.log
    local slow = {}
    for name, ms in pairs(state._timing or {}) do table.insert(slow, {name, ms}) end
    table.sort(slow, function(a, b) return a[2] > b[2] end)
    local top = {}
    for i = 1, math.min(6, #slow) do top[i] = slow[i][1] .. ' ' .. slow[i][2] end
    return {
        ok = true,
        file = STATE_FILE,
        build_ms = math.floor((os.clock() - start) * 1000 + 0.5),
        write_ms = math.floor((os.clock() - built) * 1000 + 0.5),
        slowest = table.concat(top, ', '),
        citizens = state.dwarves.total,
        tier = tier,
    }
end

local function cmd_pause(paused) -- only ever called with true
    if not in_fort() then return NOT_IN_FORT end
    cancel_run() -- a manual pause/unpause replaces any timed run
    df.global.pause_state = paused
    return {ok = true, paused = df.global.pause_state}
end

-- ai-bridge run <ticks>: unpause, then pause again after that many game ticks.
local function cmd_run(args)
    if not in_fort() then return NOT_IN_FORT end
    local ticks = whole_number(args[1])
    if not ticks or ticks < 1 or ticks > MAX_RUN_TICKS then
        return reject(('ticks must be a whole number from 1 to %d (1200 ticks = 1 day)'):format(MAX_RUN_TICKS))
    end
    cancel_run()
    local id = dfhack.timeout(ticks, 'ticks', function()
        df.global.pause_state = true
        run_timer_id = nil
        run_until = nil
    end)
    if not id then return {ok = false, error = 'could not start the timer'} end
    run_timer_id = id
    run_until = abs_tick() + ticks
    df.global.pause_state = false
    return {ok = true, running = true, ticks = ticks}
end

-- ai-bridge act <json>: run one action, e.g.
--   ai-bridge act {"type":"work_order","recipe":"brew_drink","amount":10}
-- (0.105.40) run_action: one decoded action, as `act` and `batch` run it
-- (validation, DRY_OK, the halt, the handler, CACHE_INVALIDATES)
function run_action(action)
    if type(action) ~= 'table' then
        return reject('act needs one JSON object, e.g. {"type":"tool","name":"autochop","enabled":true}')
    end
    local fn = ACTIONS[action.type]
    if not fn then
        return reject(('unknown action type: %s (known: %s)'):format(
            tostring(action.type), table.concat(sorted_keys(ACTIONS), ', ')))
    end
    -- (0.105.26) a dry run only for an action whose handler honours it
    -- (DRY_OK): the others ignored dry_run and acted for real
    if action.dry_run ~= nil and action.dry_run ~= false then
        if action.dry_run ~= true then return reject('dry_run must be true or false') end
        if not DRY_OK[action.type] then
            return reject(('%s has no dry run (it would act for real)'):format(action.type))
        end
    end
    -- The in-game kill switch: while halted, nothing that changes the fort
    -- gets through, whatever the overseer asks. A dry run of an action in
    -- DRY_OK changes nothing, so it's allowed while halted.
    local dry = action.dry_run == true and DRY_OK[action.type] == true
    if not DISPLAY_ONLY[action.type] and not dry and reqscript('ai-status').is_halted() then
        return {ok = false, rejected = true, halted = true, action = action.type,
                error = 'the AI is halted in the game (Ctrl-Shift-H to resume)'}
    end
    local result = fn(action)
    result.action = action.type
    -- (0.100) an action that changed what a cached section shows: built again
    -- in the next report (else e.g. a room given looked still free for days)
    if result.ok == true and not action.dry_run then
        for _, name in ipairs(CACHE_INVALIDATES[action.type] or {}) do
            SECTION_CACHE[name] = nil
            if name == 'constructions' then CONSTRUCTIONS_FRESH = true end
        end
    end
    -- (0.104.141) a refusal that says the report is out of date ("already
    -- has a pile") clears the sections it names too
    if type(result.stale) == 'table' and not action.dry_run then
        for _, name in ipairs(result.stale) do SECTION_CACHE[name] = nil end
    end
    return result
end

local function cmd_act(args)
    if not in_fort() then return NOT_IN_FORT end
    local text = table.concat(args, ' ')
    local ok, action = pcall(json.decode, text)
    if not ok or type(action) ~= 'table' then
        return reject('act needs one JSON object, e.g. {"type":"tool","name":"autochop","enabled":true}')
    end
    return run_action(action)
end

-- (0.105.40, Phase 13e) ai-bridge batch <json list of actions>: several
-- actions in one dfhack-run call (each call costs ~35 ms before it does
-- anything; the brain's per-cycle bookkeeping was 3-5 of them). Each action
-- runs exactly as `act` runs it (run_action), in order, each in its own
-- protected call: one that fails or is refused doesn't stop the rest. The
-- answer: {ok, results = {<each act's answer>}, times = {ms each}, ms}.
-- The ones that drive a screen over later frames or run long are refused
-- here (send them alone with `act`), so a batch never outlasts its time limit.
BATCH_MAX_ACTIONS = 20
BATCH_MAX_BYTES = 60000
BATCH_NEVER = {}
for _, name in ipairs({'send_mission', 'trade_deal', 'open_trade', 'close_trade', 'call_trader',
                       'answer_meeting', 'close_meeting', 'save_game', 'unpause', 'quiet_announcements',
                       'found_fort', 'survey_water', 'scan_entrances', 'place_well', 'restrict_water',
                       'cistern_step'}) do
    BATCH_NEVER[name] = true
end

function cmd_batch(args)
    if not in_fort() then return NOT_IN_FORT end
    local text = table.concat(args, ' ')
    if #text > BATCH_MAX_BYTES then
        return reject(('batch: %d bytes, more than %d (send fewer actions)'):format(#text, BATCH_MAX_BYTES))
    end
    local ok, list = pcall(json.decode, text)
    if not ok or type(list) ~= 'table' or #list == 0 or list.type ~= nil then
        return reject('batch needs a JSON list of action objects, e.g. [{"type":"report_status","status":{}}]')
    end
    if #list > BATCH_MAX_ACTIONS then
        return reject(('batch: %d actions, at most %d'):format(#list, BATCH_MAX_ACTIONS))
    end
    local clock = os.clock
    local start = clock()
    local results, times = {}, {}
    for i = 1, #list do
        local action = list[i]
        local t = clock()
        local result
        if type(action) == 'table' and BATCH_NEVER[action.type] then
            result = reject(('%s is not run in a batch (send it alone with act)'):format(tostring(action.type)))
            result.action = action.type
        else
            local okr, r = xpcall(run_action, debug.traceback, action)
            if not okr then
                result = {ok = false, error = tostring(r),
                          action = type(action) == 'table' and action.type or nil}
            elseif type(r) ~= 'table' then
                result = {ok = false, error = 'the action gave no answer'}
            else
                result = r
            end
        end
        results[i] = result
        times[i] = math.floor((clock() - t) * 1000 + 0.5)
    end
    return {ok = true, results = results, times = times,
            ms = math.floor((clock() - start) * 1000 + 0.5)}
end

-- ai-bridge watch: start the event feed (run from onMapLoad.init).
local function cmd_watch()
    if not in_fort() then return NOT_IN_FORT end
    return {ok = start_watching(), watching = WATCHING == BRIDGE_VERSION}
end

-- ai-bridge events: hand over queued events (written to a file, since unit
-- names can contain characters the console can't carry) and clear the queue.
local function cmd_events()
    if not in_fort() then return NOT_IN_FORT end
    ensure_watching()
    -- announcements (moods, tantrums, ghosts, crimes...) become events too
    local ok, found, newest = pcall(function()
        return reqscript('ai-reports').scan(LAST_REPORT_ID, txt)
    end)
    if ok then
        LAST_REPORT_ID = newest
        for _, ev in ipairs(found) do push_event(ev) end
    end
    local events = EVENT_QUEUE
    EVENT_QUEUE = {}
    dfhack.filesystem.mkdir_recursive(OUT_DIR)
    json.encode_file({events = events}, EVENTS_FILE, {pretty = false})
    return {ok = true, file = EVENTS_FILE, count = #events,
            reports_error = (not ok) and tostring(found) or nil}
end

-- ai-bridge map: the layer summary on its own (cheap after the first call).
local function cmd_map()
    if not in_fort() then return NOT_IN_FORT end
    local x, y, z = dfhack.maps.getTileSize()
    return {ok = true, size = {x, y, z}, layers = layers_summary()}
end

-- ai-bridge memory: hand the memory stored in the save to the overseer, as
-- {kinds = {working = {fort, text}, ...}, legacy = <old single table>}.
local function cmd_memory(args)
    if not in_fort() then return NOT_IN_FORT end
    local out, present = {kinds = {}}, false
    -- (0.104.62) raw files only for a brain that asks (`memory raw`): an older
    -- one would take the raw JSON for the text
    local want_raw = type(args) == 'table' and args[1] == 'raw'
    for _, kind in ipairs(MEMORY_KINDS) do
        -- (0.104.62) a long kind goes to a file as the save keeps it, JSON
        -- text, undecoded: DFHack's Lua JSON decoder took 14 s on Enxah's
        -- 200 KB at each keeper start, the game frozen meanwhile; Python reads it
        local raw_file
        pcall(function()
            local okr, raw = pcall(dfhack.persistent.getSiteDataString, MEMORY_KIND_PREFIX .. kind)
            if want_raw and okr and type(raw) == 'string' and #raw > 20000 and raw:sub(1, 1) == '{' then
                dfhack.filesystem.mkdir_recursive(OUT_DIR)
                local path = OUT_DIR .. '/memory-from-save.' .. kind .. '.json'
                local f = io.open(path, 'wb')
                if f then f:write(raw) f:close() raw_file = path end
            end
        end)
        local ok, v
        if raw_file then
            ok, v = true, nil
            out.kinds[kind] = {raw = raw_file}
            present = true
        else
            ok, v = pcall(dfhack.persistent.getSiteData, MEMORY_KIND_PREFIX .. kind, nil)
        end
        if ok and type(v) == 'table' and type(v.text) == 'string' then
            -- (0.104.44) a long text goes to a file of its own as it is: the
            -- Lua JSON encoder took 9.5 s on Enxah's 200 KB (over the 10 s
            -- limit, so from 08:36 the save's memory was never read or written)
            local file
            if #v.text > 20000 then
                pcall(function()
                    dfhack.filesystem.mkdir_recursive(OUT_DIR)
                    local path = OUT_DIR .. '/memory-from-save.' .. kind .. '.txt'
                    local f = io.open(path, 'wb')
                    if f then f:write(v.text) f:close() file = path end
                end)
            end
            out.kinds[kind] = file and {fort = v.fort, file = file} or {fort = v.fort, text = v.text}
            present = true
        end
    end
    local ok, legacy = pcall(dfhack.persistent.getSiteData, MEMORY_KEY, nil)
    -- a table without .fort is the "dropped" marker, not memory
    if ok and type(legacy) == 'table' and legacy.fort ~= nil then
        out.legacy = legacy
        present = true
    end
    if not present then return {ok = true, present = false} end
    if next(out.kinds) == nil then out.kinds = nil end -- (an empty table would encode as [])
    dfhack.filesystem.mkdir_recursive(OUT_DIR)
    json.encode_file(out, MEMORY_FROM_SAVE, {pretty = false})
    return {ok = true, present = true, file = MEMORY_FROM_SAVE}
end

-- ai-bridge survey: the staircases, the dwarves' busiest level and the levels
-- with soil, as elevations, for the overseer's master plan. Read-only.
local function cmd_survey()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-builder').survey() end)
    if not ok or type(r) ~= 'table' then return {ok = false, error = 'survey failed: ' .. tostring(r)} end
    return r
end

-- ai-bridge halt [on|off|toggle]: the kill switch (Ctrl-Shift-H in game).
local function cmd_halt(args)
    if not in_fort() then return NOT_IN_FORT end
    local st = reqscript('ai-status')
    local arg = args[1] or 'toggle'
    local now = st.is_halted()
    if arg == 'on' then now = st.set_halted(true)
    elseif arg == 'off' then now = st.set_halted(false)
    elseif arg == 'toggle' then now = st.set_halted(not now)
    elseif arg ~= 'show' then return reject('use: ai-bridge halt on|off|toggle|show') end
    return {ok = true, halted = now}
end

local COMMANDS = {
    halt = cmd_halt,
    memory = cmd_memory,
    survey = cmd_survey,
    watch = cmd_watch,
    events = cmd_events,
    reports = cmd_reports,
    probe = cmd_probe,
    probe_defence = cmd_probe_defence,
    probe_squads = cmd_probe_squads,
    probe_occupations = cmd_probe_occupations,
    probe_trade = cmd_probe_trade,
    probe_missions = cmd_probe_missions,
    mission_here = cmd_mission_here,      -- (0.105.24)
    probe_meeting = cmd_probe_meeting,    -- (0.105.0)
    meeting_here = cmd_meeting_here,      -- (0.105.0)
    probe_justice = cmd_probe_justice,
    trade_here = cmd_trade_here,
    test_threat = cmd_test_threat,
    trade_press = cmd_trade_press,
    assumptions = cmd_assumptions,
    modules = cmd_modules,                -- (0.105.26) every module and part loads
    map = cmd_map,
    version = function() return version_info() end,
    status = cmd_status,
    state = cmd_state,
    pause = function() return cmd_pause(true) end,
    run = cmd_run,
    act = cmd_act,
    batch = cmd_batch,                    -- (0.105.40) several actions in one call
}
BRIDGE_COMMANDS = COMMANDS               -- (0.105.40) for version's `commands`

local function main(args)
    local name = table.remove(args, 1) or 'version'
    local fn = COMMANDS[name]
    if not fn then
        return {ok = false, error = ('unknown command: %s (known: %s)'):format(
            tostring(name), table.concat(sorted_keys(COMMANDS), ', '))}
    end
    local ok, result = xpcall(fn, debug.traceback, args)
    if not ok then
        return {ok = false, error = tostring(result)}
    end
    return result
end

if dfhack_flags.module then
    return
end

print(json.encode(main({...}), {pretty = false}))
