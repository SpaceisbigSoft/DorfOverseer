-- Building projects for the AI overseer: finds a safe place for a new level
-- around the main staircase, digs it with Quickfort, then furnishes it.
--
-- The AI only ever names a level kind and a size; everything about WHERE is
-- decided here, and every tile is checked against the real map (including
-- hidden tiles) for aquifers, liquids, caverns and the surface first.
-- See docs/building.md.
--
-- (13c) This file holds the map reads and the helpers every part uses; the
-- rest is in its parts beside it (loaded at the end of this file, into this
-- module, so reqscript('ai-builder').name reaches all of them): sites (where
-- a level goes, the survey, stairwells), projects (their life from start to
-- polish; founding), farms (plots, crops, water and sand zones, pastures),
-- wells, cistern, surface (spots outside, crossings, the keep, the deep
-- depot), rooms (walls back, workshops, feeders, stockpiles, zones,
-- slabs, planned buildings) and halls (0.105.30: the surface hall). DFHack
-- reloads a module when its own file
-- changes: a change to a part alone is picked up once ai-builder.lua is
-- touched too, or the game restarts.
--@ module = true

layouts = reqscript('ai-layouts')

PROJECTS_KEY = 'ai-overseer/projects'
MAX_OPEN_PROJECTS = 2
URGENT_EXTRA = 2          -- (0.104.12) urgent projects beyond the limit
-- (0.104.142) a level dug and waiting this long only for its furniture lends
-- its slot (at most FURNISH_LEND_MAX of them): Teacheroar's dining hall, tavern
-- and tombs waited 26-93 days on the masons while the temple, the planters'
-- guildhall petition and the craft shops were refused for want of a slot
FURNISH_LEND_DAYS = 14
FURNISH_LEND_MAX = 3
MAX_LEVELS_BELOW = 15      -- how far below the staircase's bottom it may extend
STAIR_SAMPLE_LEVELS = 12   -- z-levels sampled when looking for the main staircase
STAIRS_TO_TRY = 5          -- staircases tried, most used first
MAX_CORRIDOR = 25          -- longest new corridor from a staircase to a new level
MAX_WALK_EXISTING = 15     -- how far a corridor may first follow existing fort space
SEARCH_SECONDS = 4         -- the search stops here (the game answers within 10 s)
DECOR_TIMEOUT_DAYS = 60    -- engrave anyway if smoothing hasn't finished by then
PREFER_SLACK = 3           -- (0.104.107) corridor tiles the plan's direction may cost over another
TRY_BESIDE = true          -- also try sites beside the stairs, joined by a corridor

-- DFHack counts z-levels from 0 at the bottom of the map; the game's screen
-- shows elevation. Messages use the elevation you see in the game.
OFFSET = 0
function elevation_offset()
    local ok, v = pcall(function() return df.global.world.map.region_z - 100 end)
    return ok and math.tointeger(v) or 0
end
function ez(z) return z + OFFSET end
KEEP_CLOSED_PROJECTS = 20  -- finished/cancelled projects kept in the save

---------------------------------------------------------------------------
-- Map access. Everything that reads the game map goes through these few
-- functions, so the tests can swap in a fake map.
---------------------------------------------------------------------------

NATURAL = {STONE = true, MINERAL = true, SOIL = true, LAVA_STONE = true}

-- {shape=<name>, material=<name>, aquifer, liquid, feature, outside, designated,
--  marked, building, track} or nil when off the map.
function tile_info(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    local attrs = df.tiletype.attrs[tt]
    local des, occ = dfhack.maps.getTileFlags(x, y, z)
    if not des then return nil end
    -- DF's own "warm stone" test (the same one DFHack's dig plugin uses):
    -- dig designations on warm, undiscovered stone get cancelled by the game.
    local block = dfhack.maps.getTileBlock(x, y, z)
    local warm = block ~= nil and block.temperature_1[x & 15][y & 15] >= 10075
    return {
        shape = df.tiletype_shape[attrs.shape],
        material = df.tiletype_material[attrs.material],
        aquifer = des.water_table,
        liquid = des.flow_size > 0,
        depth = des.flow_size,                                   -- 0-7
        -- (a boolean in DFHack 53.16, so the old == df.tile_liquid.Magma never matched)
        magma = des.flow_size > 0 and (des.liquid_type == true or des.liquid_type == 1),
        stagnant = des.water_stagnant,
        salt = des.water_salt,
        feature = des.feature_local or des.feature_global,
        outside = des.outside,
        -- (0.105.5) DF's underground test for a farm plot; (0.105.7 review)
        -- nil when this DFHack can't read it (pcall: a missing field throws)
        subterranean = (function() local ok, v = pcall(function() return des.subterranean end)
                            if ok then return v end end)(),
        designated = des.dig ~= df.tile_dig_designation.No,
        -- (0.105.31) which: 'Default' (dig), 'Channel', 'Ramp', the stairs
        dig = df.tile_dig_designation[des.dig],
        -- "marker only" (blueprint) designations: dwarves won't dig them
        marked = occ.dig_marked,
        smoothed = df.tiletype_special[attrs.special] == 'SMOOTH',
        track = df.tiletype_special[attrs.special] == 'TRACK',   -- (0.105.30) minecart track: wagons can't cross it
        smoothing = des.smooth ~= 0,          -- smooth/engrave job designated
        building = occ.building ~= df.tile_building_occ.None,
        warm = warm,
        hidden = des.hidden,
        items = occ.item,                     -- (0.104.47) something lies here
    }
end

-- (0.104.110) a job in words: its type and who has it (only for the few
-- tiles a stalled level reports)
function job_words(j)
    local ok, what = pcall(function()
        local s = tostring(df.job_type[j.job_type] or 'job')
        local okw, w = pcall(dfhack.job.getWorker, j)
        if okw and w then
            local okn, n = pcall(dfhack.units.getReadableName, w)
            -- (0.104.154) the name in UTF-8 (DF's own code page broke the report's JSON)
            if okn and dfhack.df2utf then local okc, c = pcall(dfhack.df2utf, n); if okc and c then n = c end end
            return s .. ' by ' .. ((okn and n or 'a dwarf'):gsub(',.*', ''))
        end
        -- (0.104.128) why a dig job nobody takes waits: its flags and the
        -- tile's dig priority (Teacheroar: the new hospital's first tile)
        local extra = {}
        pcall(function()
            for k, v in pairs(j.flags) do if v == true then table.insert(extra, k) end end
        end)
        pcall(function()
            local b = dfhack.maps.getTileBlock(j.pos)
            for _, ev in ipairs(b.block_events) do
                if df.block_square_event_designation_priorityst:is_instance(ev) then
                    local pr = ev.priority[j.pos.x % 16][j.pos.y % 16]
                    if pr and pr > 0 then table.insert(extra, 'priority ' .. (pr // 1000)) end
                end
            end
        end)
        table.sort(extra)
        return s .. ', no worker' .. (#extra > 0 and (' (' .. table.concat(extra, ', ') .. ')') or '')
    end)
    return ok and what or 'a job'
end

-- The game's moment as ticks since year 0 (0 when it can't be read).
function now_tick()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and t or 0
end

-- Tiles a job is working on right now ("x,y,z" -> true). DF takes the dig
-- designation off a tile while a dwarf is digging it, so without this a tile
-- being dug looks like one the game cancelled.
-- (0.100) once per game moment: every project still being dug asked for it,
-- each a walk of the whole job list (in the pulse report too)
local JOB_TILES = {at = nil, set = nil}
function job_tiles()
    local okt, now = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    if okt and JOB_TILES.at == now and JOB_TILES.set then return JOB_TILES.set end
    local set = {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        -- (0.104.110) the job's type, so a tile under some other job (a
        -- tomb's burial, a smoothing) isn't taken for one being dug
        if j then set[j.pos.x .. ',' .. j.pos.y .. ',' .. j.pos.z] = j end
        link = link.next
    end
    if okt then JOB_TILES.at, JOB_TILES.set = now, set end
    return set
end

function map_size()
    return dfhack.maps.getTileSize()
end

-- Tile types that are stairs, looked up once (much faster than reading each
-- tile's attributes while scanning big areas).
local STAIR_TT = nil
local function stair_types()
    if not STAIR_TT then
        STAIR_TT = {}
        for tt, _ in ipairs(df.tiletype) do
            local attrs = df.tiletype.attrs[tt]
            local shape = attrs and df.tiletype_shape[attrs.shape]
            if shape == 'STAIR_UP' or shape == 'STAIR_DOWN' or shape == 'STAIR_UPDOWN' then
                STAIR_TT[tt] = shape
            end
        end
    end
    return STAIR_TT
end

-- 'STAIR_UP' / 'STAIR_DOWN' / 'STAIR_UPDOWN', or nil.
function stair_shape(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    return tt and stair_types()[tt] or nil
end

-- Positions of citizens (where the fort is).
function citizen_positions()
    local out = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local x, y, z = dfhack.units.getPosition(u)
        if x then table.insert(out, {x = x, y = y, z = z}) end
    end
    return out
end

-- Which connected walking area a tile belongs to (0 = not walkable).
function walk_group(x, y, z)
    return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) or 0
end

-- Is this building still waiting for buildingplan to find its materials?
function is_planned(b)
    local ok, bp = pcall(require, 'plugins.buildingplan')
    return ok and bp and bp.isPlannedBuilding and bp.isPlannedBuilding(b) or false
end

---------------------------------------------------------------------------
-- Safety checks
---------------------------------------------------------------------------

-- Untouched natural wall with nothing dangerous in it. Returns ok, reason.
function natural_wall(t)
    if not t then return false, 'off the map' end
    if t.aquifer then return false, 'aquifer' end
    if t.liquid then return false, 'water or magma' end
    if t.feature then return false, 'cavern, magma sea or special vein' end
    if t.outside then return false, 'open to the sky' end
    if t.warm then return false, 'warm stone (magma nearby)' end
    if t.shape ~= 'WALL' then return false, 'not solid rock (already dug or open)' end
    if not NATURAL[t.material] then return false, ('not natural rock (%s)'):format(tostring(t.material)) end
    if t.designated then return false, 'already designated for digging' end
    if t.building then return false, 'a building is there' end
    return true
end

-- Tile reads are cached for the length of one site search: the same tiles
-- get looked at many times while trying nearby positions.
CACHE = nil
function info(x, y, z)
    if not CACHE then return tile_info(x, y, z) end
    local k = (z * 4096 + y) * 4096 + x
    local v = CACHE[k]
    if v == nil then
        v = tile_info(x, y, z) or false
        CACHE[k] = v
    end
    return v or nil
end

function overlaps(a, b)
    return a.z == b.z and a.x1 <= b.x2 and b.x1 <= a.x2 and a.y1 <= b.y2 and b.y1 <= a.y2
end

function has(set, x, y)
    local col = set[x]
    return col ~= nil and col[y] == true
end

function add(set, x, y)
    set[x] = set[x] or {}
    set[x][y] = true
end

---------------------------------------------------------------------------
-- Helpers every part uses
---------------------------------------------------------------------------

-- The projects still being dug or furnished.
function open_projects(data)
    local out = {}
    for _, p in ipairs(data.list) do
        if p.phase == 'dig' or p.phase == 'furnish' then table.insert(out, p) end
    end
    return out
end

-- Where a project's cells are anchored (older records used the stair).
function anchor_of(p)
    return p.anchor or p.stair
end

-- Quickfort, through its API.
function quickfort_apply(mode, cells, z, ax, ay, command, dry_run)
    local qf = reqscript('quickfort')
    return qf.apply_blueprint{mode = mode, command = command or 'run', dry_run = dry_run,
                              data = layouts.to_data(cells, z), pos = {x = ax, y = ay, z = 0}}
end

function stat(stats, name)
    return stats and stats[name] and stats[name].value or 0
end

-- (0.105.33, L8) ai-util, the modules' shared helpers: reqscript in the game;
-- where reqscript doesn't know it (a test's stand-in), the file beside this
-- one, loaded into its own environment (as reqscript would)
local UTIL
local function util()
    if UTIL then return UTIL end
    local ok, m = pcall(reqscript, 'ai-util')
    if not (ok and type(m) == 'table') then
        local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
        local path = dir and (dir .. 'ai-util.lua') or (dfhack.findScript and dfhack.findScript('ai-util'))
        local env = setmetatable({}, {__index = _G})
        assert(loadfile(assert(path, 'ai-util.lua not found'), 't', env))()
        m = env
    end
    UTIL = m
    return UTIL
end

-- (13c) A table kept in the save's site data: {} when it's missing, can't be
-- read or isn't a table. site_put: saved, never an error (ok, why).
-- (0.105.33, L8) ai-util's own copies, not a second pair
function site_get(key) return util().site_get(key, {}) end
function site_put(key, d) return util().site_put(key, d) end

-- (13c) An item nobody may take as it lies. Whether a job holds it is the
-- caller's to say (some count those as reserved).
-- (0.105.33, L8) ai-util's one list (UNFREE), so rotten, encased, on fire, a
-- web, owned, an artifact, murder evidence, a dead dwarf's or an item a unit
-- carries count too (the builder's own list had drifted from it)
-- (0.105.36 D3) `also` (optional): more of item_unfree's names the caller
-- doesn't mind, e.g. {held = true} for a part carried to its job
function item_held(it, also)
    local allow = {in_job = true}
    for k, v in pairs(also or {}) do allow[k] = v end
    return not util().item_free(it, allow)
end

-- (13c) Quickfort's dry run, then the real one unless dry_run: the one copy
-- of what a dozen callers wrote out by hand. The dry run must designate at
-- least `need` (default 1) and meet no key quickfort doesn't know (`loose`:
-- unknown keys let by, as the bridge and designate always did); the real run
-- at least 1. Returns ok, the run that failed ('dry' or 'run', nil when ok),
-- and that run's stats (the dry run's on a dry run; the error text when the
-- call itself failed).
function qf_try(mode, cells, z, ax, ay, dry_run, need, loose)
    local key = mode .. '_designated'
    local okd, dry = pcall(quickfort_apply, mode, cells, z, ax, ay, 'run', true)
    if not okd or stat(dry, key) < (need or 1) or (not loose and stat(dry, 'invalid_keys') > 0) then
        return false, 'dry', dry
    end
    if dry_run then return true, nil, dry end
    local okr, real = pcall(quickfort_apply, mode, cells, z, ax, ay)
    if not okr or stat(real, key) < 1 then return false, 'run', real end
    return true, nil, real
end

function count(tiles)
    local n = 0
    for _, col in pairs(tiles) do for _ in pairs(col) do n = n + 1 end end
    return n
end

---------------------------------------------------------------------------
-- More map reads: mud, floors, buildings and zones on a tile
---------------------------------------------------------------------------

-- Is there mud on this tile? (DF keeps it as a "material spatter" event on
-- the map block.)
local MUD = nil
function mud_at(x, y, z)
    local block = dfhack.maps.getTileBlock(x, y, z)
    if not block then return false end
    if MUD == nil then
        local ok, mi = pcall(dfhack.matinfo.find, 'MUD')
        MUD = (ok and mi and mi.type) or 12          -- builtin material 12 is mud
    end
    for _, ev in ipairs(block.block_events) do
        if df.block_square_event_material_spatterst:is_instance(ev) and ev.mat_type == MUD
                and ev.amount[x & 15][y & 15] > 0 then
            return true
        end
    end
    return false
end

-- The material of a floor tile, or nil if it isn't floor. Tile types looked up
-- once, so scanning the area around the fort stays quick.
local FLOOR_TT = nil
function floor_material(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    if not FLOOR_TT then
        FLOOR_TT = {}
        for t, _ in ipairs(df.tiletype) do
            local attrs = df.tiletype.attrs[t]
            if attrs and df.tiletype_shape[attrs.shape] == 'FLOOR' then
                FLOOR_TT[t] = df.tiletype_material[attrs.material] or '?'
            end
        end
    end
    return FLOOR_TT[tt]
end

-- Is something already on this tile: a building, a stockpile or a zone (a
-- bedroom or dining hall on soil floor stays what it is)?
function building_at(x, y, z)
    return dfhack.buildings.findAtTile(xyz2pos(x, y, z)) ~= nil
end

-- The kinds of zone covering this tile ('DiningHall', 'Bedroom', ...).
function zone_types(x, y, z)
    local out = {}
    local ok, zones = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(x, y, z))
    if ok and zones then
        for _, zn in ipairs(zones) do
            table.insert(out, df.civzone_type[zn.type] or tostring(zn.type))
        end
    end
    return out
end

function tile_taken(x, y, z)
    return building_at(x, y, z) or #zone_types(x, y, z) > 0
end

---------------------------------------------------------------------------
-- (13c) The rest of the builder lives in parts beside this file
-- (ai-builder-<part>.lua). Each runs in this module's own environment, so
-- its names stay reqscript('ai-builder').name for the bridge and the other
-- modules, and a test's swap (B.tile_info = ...) reaches every part.
---------------------------------------------------------------------------

PARTS = {'sites', 'projects', 'farms', 'wells', 'cistern', 'surface', 'rooms', 'halls'}   -- (0.105.30) halls
-- (0.105.26) each part marks the version it came with (the bridge's
-- `version` lists one that differs from BRIDGE_VERSION); started afresh at
-- each load, so a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-builder'] = '0.105.36'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

for _, part in ipairs(PARTS) do
    local name = 'ai-builder-' .. part
    local path = part_path(name)
    if not path then error('ai-builder: ' .. name .. '.lua is missing (it goes beside ai-builder.lua)') end
    assert(loadfile(path, 't', _ENV))()
end
