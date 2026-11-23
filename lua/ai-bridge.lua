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
--   ai-bridge mapload            (0.105.48) the gate lockdown kept in the save re-checked after a load
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
-- (13c) The bridge is in parts. This file keeps the commands, BRIDGE_VERSION
-- and the loaders; (r8) the ACTIONS table (with DRY_OK and DISPLAY_ONLY, what
-- may pass while the AI is halted) is in ai-bridge-catalog.lua and the
-- report's SECTIONS and their cache in ai-bridge-sections.lua, each run where
-- it stood in this file (HUB_PARTS below). Beside it, loaded into
-- its environment (BRIDGE_PARTS below): ai-bridge-report.lua with
-- ai-bridge-report-supplies, -fort and -world (the report's readers and the
-- event feed), ai-bridge-orders.lua (work orders and tools),
-- ai-bridge-actions.lua with ai-bridge-actions-fort, -works and -civic (the
-- other action handlers), ai-bridge-probes.lua (probes and screen recording)
-- and ai-bridge-design.lua. All the parts go to the game together.
--@ module = true

local json = require('json')
local utils = require('utils')

BRIDGE_VERSION = '0.105.75'
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
-- (r6) ai-bridge-report and ai-bridge-actions each in four files (by theme;
-- each file's later parts right after it, in the order the one file had)
BRIDGE_PARTS = {'ai-bridge-report', 'ai-bridge-report-supplies', 'ai-bridge-report-fort', 'ai-bridge-report-world', 'ai-bridge-orders', 'ai-bridge-actions', 'ai-bridge-actions-fort', 'ai-bridge-actions-works', 'ai-bridge-actions-civic', 'ai-bridge-probes', 'ai-bridge-design'}
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

-- (r8) The hub's own tables, each in a file beside this one: run in this
-- environment like the parts above, but each where its lines stood in this
-- file (run_hub_part below): ai-bridge-catalog (ACTIONS, DRY_OK, DISPLAY_ONLY,
-- RELEASE_WHILE_HALTED) right after the parts, ai-bridge-sections (SECTIONS,
-- the tiers, the section cache) after the version and modules commands.
HUB_PARTS = {'ai-bridge-catalog', 'ai-bridge-sections'}
function run_hub_part(name)
    local path = bridge_part_path(name)
    if not path then error(('ai-bridge: %s.lua is missing (it goes beside ai-bridge.lua)'):format(name)) end
    part_chunk(path)()
end

run_hub_part('ai-bridge-catalog')   -- (r8) ACTIONS, DRY_OK, DISPLAY_ONLY, RELEASE_WHILE_HALTED

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
    'ai-artifacts', 'ai-bans', 'ai-benches', 'ai-blueprints', 'ai-builder', 'ai-camera', 'ai-captives', 'ai-census',
    'ai-cleanup', 'ai-constructions', 'ai-diplomacy', 'ai-disposal', 'ai-food-store', 'ai-forestry', 'ai-gates',
    'ai-hauling', 'ai-hazards', 'ai-health', 'ai-homes', 'ai-hunt', 'ai-leather-gear',
    'ai-industry', 'ai-insane', 'ai-joins', 'ai-killers', 'ai-killzone', 'ai-labor', 'ai-layouts', 'ai-military', 'ai-military-gear',
    'ai-mission-send', 'ai-missions', 'ai-moods', 'ai-noble-demands', 'ai-nobles', 'ai-overlay',
    'ai-overseer-settings', 'ai-paper', 'ai-pile-links', 'ai-ping', 'ai-provisions', 'ai-reports', 'ai-siege',
    'ai-shelter-plan', 'ai-society', 'ai-society-burrows', 'ai-status', 'ai-syndromes', 'ai-threats', 'ai-title', 'ai-trade', 'ai-traffic',
    'ai-stuck',   -- (0.105.45)
    'ai-util', 'ai-water', 'ai-waterworks', 'gui/ai-overseer',
    'ai-threat-facts',          -- (0.105.45) a threat's facts for the matchup (called from the report)
    'ai-lure',   -- (0.105.45)
    'ai-thirst',   -- (0.105.46, I2) the thirst watch
    'ai-recovery',   -- (0.105.46, I4)
    'ai-floorplan',   -- (layout B) the hallway-first floor plans
    'ai-slices', 'ai-cavern-scan',   -- (0.105.46, I6) walks spread over several reports; the caverns' seen samples
    'ai-mood-help',   -- (0.105.47, J1) job cancels, webs, the moods' tiles in the shelter
    'ai-screen-buttons', 'ai-meeting-open',   -- (0.105.47) buttons kept for every save; the meeting opened
    'ai-tantrums',   -- (0.105.47) the tantrum ledger, posts, hospital guards
    'ai-mission-way',   -- (0.105.47) a mission's travellers' way off the map, the gate hold
    'ai-way-out',   -- (0.105.47, J16) the citizens' way off the map, the fort left open
    'ai-training-squad',   -- (0.105.47) the training squad
    'ai-welfare',   -- (0.105.47, I7b) the unreachable dead, coffins anywhere, a cook trained
    'ai-floorplace',   -- (layout B) where halls and rooms go on a floor
    'ai-well-safety',   -- (0.105.47) cavern wells made safe
    'ai-near-gates', 'ai-ice',   -- (0.105.47, I7d) surface work near the gates; water zones off before the ice
    'ai-descent',   -- (0.105.47) the deep plan's stair past the first cavern
    'ai-herd',   -- (0.105.47) the herd by Husbandry
    'ai-raids',   -- (0.105.47, J17) the raid policy's sites; the raid party's pets let out and put back
    'ai-floorunits',   -- (layout B) a level cut into room units for a floor
    'ai-nobles-swap',   -- (r11 n1) the interim messenger swapped out, a vastly better office holder
}
-- the split-off modules that carry a version mark of their own
MARKED_MODULES = {'ai-military-gear', 'ai-society-burrows', 'ai-constructions', 'ai-nobles-swap'}   -- (r11 n1 fixes)

-- (13e) The modules split into a hub and parts beside it, each listing its
-- parts in PARTS and marking them in PART_VERSIONS
SPLIT_MODULES = {'ai-builder', 'ai-gates'}

-- (r8) Any other module of BRIDGE_MODULES whose file has a PARTS line is a
-- hub with parts too (ai-gates' way: PARTS = {'<theme>', ...}, the files
-- <module>-<theme>.lua, the hub and each part marked in the hub's
-- PART_VERSIONS): found from the files, so a module split later needs no
-- line here. Each file is read once and again only when it changes
-- (SPLIT_SCAN, by path and modification time, as PART_CHUNKS).
SPLIT_SCAN = SPLIT_SCAN or {}
function module_has_parts(mod)
    local okp, path = pcall(bridge_part_path, mod)
    if not okp or not path then return false end
    local okm, mtime = pcall(function() return dfhack.filesystem.mtime(path) end)
    mtime = okm and mtime or nil
    local c = SPLIT_SCAN[path]
    if c and mtime ~= nil and c.mtime == mtime then return c.has end
    local has = false
    pcall(function()
        local f = io.open(path, 'rb')
        local src = f:read('*a')
        f:close()
        has = ('\n' .. src):find('\nPARTS = %b{}') ~= nil
    end)
    SPLIT_SCAN[path] = {has = has, mtime = mtime}
    return has
end

-- SPLIT_MODULES, then every other module of BRIDGE_MODULES with a PARTS line.
function split_modules()
    local out, seen = {}, {}
    for _, m in ipairs(SPLIT_MODULES) do
        if not seen[m] then table.insert(out, m); seen[m] = true end
    end
    for _, m in ipairs(BRIDGE_MODULES) do
        if not seen[m] and module_has_parts(m) then table.insert(out, m); seen[m] = true end
    end
    return out
end

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
    for _, n in ipairs(HUB_PARTS) do check(n, PART_VERSIONS) end
    for _, mod in ipairs(split_modules()) do
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
    for _, n in ipairs(HUB_PARTS) do table.insert(parts, n) end
    for _, mod in ipairs(split_modules()) do
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

run_hub_part('ai-bridge-sections')   -- (r8) safe, fort_key, SECTIONS, the tiers, the section cache

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
    local ctx = {tier = tier}       -- (0.105.48, A1) a section may budget its walk by the tier
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
        -- (0.105.48, K7c) one past its SECTION_MAX_DAYS always is, outside the count
        local max_days = type(SECTION_MAX_DAYS) == 'table' and SECTION_MAX_DAYS or {}
        for _, name in ipairs(names) do
            local days, c = SECTION_CACHE_DAYS[name], SECTION_CACHE[name]
            if days and c and c.site == site and now >= c.tick and now - c.tick >= days * 1200 then
                local cap = tonumber(max_days[name])
                if cap and now - c.tick >= math.max(cap, days) * 1200 then
                    rebuild[name] = true
                else
                    table.insert(due, {name = name, age = now - c.tick})
                end
            end
        end
        table.sort(due, function(a, b) return a.age > b.age end)
        for i = 1, math.min(SECTION_REBUILDS, #due) do rebuild[due[i].name] = true end
    end
    -- (0.105.48, K7c) each cached copy's age (game days, 0.1) and whether it
    -- is past its SECTION_CACHE_DAYS (waiting for the rotation)
    local cache_age, cache_due = {}, {}
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
            cache_age[name] = math.floor((now - c.tick) / 120 + 0.5) / 10
            if now - c.tick >= days * 1200 then cache_due[name] = true end
        else
            -- a section may return a second value, true: don't keep this copy
            -- (logistics with a part that failed)
            local v, nocache = SECTIONS[name](ctx)
            -- (0.105.51) a module DFHack read half written (scripts copied over while
            -- the game ran): its flags dropped and the section tried once more
            if type(v) == 'table' and type(v.error) == 'string' and v.error:find('Cannot be used as a module', 1, true) then
                local okr, mod = pcall(function() return reqscript('ai-util').module_flags_reset(v.error) end)
                if okr and mod then v, nocache = SECTIONS[name](ctx) end
            end
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
    if type(state.perf) == 'table' and not state.perf.error then
        state.perf.cache_age, state.perf.cache_due = cache_age, cache_due   -- (0.105.48, K7c)
    end
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
        -- (0.105.46, I6) the sliced walks: passes finished, and the one under way
        local slices
        pcall(function()
            local S = reqscript('ai-slices')
            for _, n in ipairs({'industry_veins', 'deep_hazard', 'cavern_scan', 'shelter_grid', 'shelter_walk', 'forest_census'}) do
                local st = S.status(n)
                if st then
                    slices = slices or {}
                    slices[n] = {passes = st.passes, under_way = st.under_way}
                end
            end
        end)
        return {
            slices = slices,
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
    -- (0.105.48, K2) the overseer's poll is the gate watcher's heartbeat: a slow
    -- brain is not read as away (lua/ai-gates-watch-look.lua brain_away)
    pcall(function() reqscript('ai-gates').brain_ping() end)
    -- (fix41) evil weather coming (a cloud near the map's edge, DF's
    -- announcement, evil rain): an event, so a cycle reads it now
    pcall(function()
        local ev = reqscript('ai-threats').weather_watch(abs_tick(), fort_key())
        if ev then push_event(ev) end
    end)
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
        -- (0.105.48, K9) DF's World screen is open (the overseer leaves it unattended after a while)
        world_open = (function()
            local ok, v = pcall(function() return reqscript('ai-mission-send').world_screen() ~= nil end)
            return ok and v or nil
        end)(),
        -- (0.105.47) meetings queued behind DF's diplomacy light (the overseer opens them unattended)
        meeting_waiting = (function()
            local ok, n = pcall(function() return #df.global.plotinfo.dipscript_popups end)
            return ok and n > 0 and n or nil
        end)(),
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
    -- (0.105.48 round 2) halted: the game is the player's, never unpaused by the AI
    if reqscript('ai-status').is_halted() then
        return {ok = false, rejected = true, halted = true,
                error = 'the AI is halted in the game (Ctrl-Shift-H to resume)'}
    end
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
        if not RELEASE_WHILE_HALTED[action.type] then
            return {ok = false, rejected = true, halted = true, action = action.type,
                    error = 'the AI is halted in the game (Ctrl-Shift-H to resume)'}
        end
        action[RELEASE_WHILE_HALTED[action.type]] = true    -- (0.105.40b fix) the undoing step only
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
BATCH_NEVER.open_meeting = true   -- (0.105.47) drives a screen
BATCH_NEVER.close_world = true    -- (0.105.48, K9) drives a screen over later frames

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

-- (0.105.48, K2) ai-bridge mapload: run by DFHack on each map load (the init
-- file dfhack-config/init/onMapLoad-ai-overseer.init, which lua/ai-gates-stuck.lua
-- writes): a gate lockdown kept in the save is re-checked before any brain
-- reports (opened unless a danger is near; else the watcher holds it)
function cmd_mapload()
    if not in_fort() then return NOT_IN_FORT end
    return reqscript('ai-gates').on_map_loaded()
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
        for _, ev in ipairs(found) do
            -- (r1 g7) a hero spotted after an artifact: a target at once (ai-threats TURNED)
            pcall(function() reqscript('ai-threats').note_report(ev, txt) end)
            push_event(ev)
        end
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
    mapload = cmd_mapload,                -- (0.105.48, K2) the gates after a load
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
