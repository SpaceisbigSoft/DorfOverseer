-- (0.105.0) Water works and magma: the moat (W3), the pump stack (W4), the
-- muddied farm level (W5) and magma workshops, each a staged project.
--
-- Every work is one plan, built a step at a time (the `water_work` action):
--   planned    the plan made and its dry run: the path the water (or magma)
--              would take, from the plug to where it stops, walked tile by
--              tile before anything is dug; refused when it reaches a
--              citizen, a workshop, a bed, a stockpile or the fort's inside
--   digging    the dig designated (a second dig, e.g. a ramp removed under
--              the floodgate, once the first is done)
--   building   the floodgate, its lever ("AI moat", "AI pump"...) and the
--              work's own buildings (a drawbridge, screw pumps, a hatch)
--   linking    the lever linked to the floodgate (lua/ai-gates.lua)
--   filling    the path walked again, the plug dug with nobody near
--              (DFHack dig-now) while the floodgate is shut, then opened;
--              then the test: the moat deep enough, the reservoir rising,
--              the farm floor wet, the pit full of magma
--   drying     (irrigation) the floodgate shut, waiting for the floor to dry
--   finishing  what comes last: farm plots on the mud, the magma workshop
--   done       kept; held/retired when something went wrong (said why)
-- The floodgate is the emergency stop: `shut` closes it at once (DFHack's
-- lever --instant), and water seen outside the work's own tiles shuts it.
--
-- All map access goes through the hooks at the top, so the tests can run it
-- on a fake map. State in site data 'ai-overseer/waterworks'.
--@module = true

STATE_KEY = 'ai-overseer/waterworks'
KINDS = {moat = true, pump = true, irrigation = true, magma = true, power = true}   -- (0.105.37 E3) power: W7
MAGMA_SHOPS = {MagmaForge = 'wv', MagmaSmelter = 'el', MagmaGlassFurnace = 'ea'}   -- quickfort keys (guesses: wv/el/ea)

MOAT_GAP = 3            -- tiles from the gate's outside tile to the trench
MOAT_HALF = 3           -- the trench runs this far each side of the gate's line
MOAT_FEED_MAX = 40      -- tiles of feed channel from the river at most
RETIRE_MAX = 2          -- (0.105.35) a work retired this often (held, retired by the AI) is not begun again
PUMP_MAX_LIFT = 6       -- levels a pump stack lifts at most (one dwarf a pump)
PUMP_TEST_DAYS = 14     -- no rise in the reservoir this long: said so
IRR_REACH = 14          -- the farm room this near its water
IRR_DRY_DAYS = 28       -- still wet this long: said so
MAGMA_REACH = 10        -- the workshop's pit this near the magma
MAGMA_STAIR_MAX = 60    -- levels of stair down to the magma at most
PATH_MAX = 400          -- tiles the water may reach (outside, for a moat)
FILL_STALL_DAYS = 28    -- (0.105.33) filling with no rise this long: held, said why
REOPEN_AFTER_DAYS = 3   -- (0.105.33) a shut floodgate opened again no sooner than this
SHUTS_MAX = 3           -- (0.105.33) shut this often for a flood (within SHUTS_WINDOW_DAYS): held, then retired by the AI
SHUTS_WINDOW_DAYS = 28  -- (0.105.36) only the shuts this recent count (floods years apart don't add up)
FLOOD_NEAR = 30         -- (0.105.36) a shut counts only with a citizen in deep water this near the work's tiles
DAY = 1200
-- (0.105.38) far sources (the player, 12 Nov: "'working' shouldn't be limited
-- to local proximity of embarks"). Each work tries its near source first, as
-- before (a fort with water near makes the same choices); when none fits, the
-- whole-map survey's bodies (lua/ai-water.lua `waters`) further off, the
-- cheapest first (the dig's length: the survey's reach estimate, or the
-- distance), up to FAR_REACH tiles away (nil: the map's width) and
-- FAR_JOB_MAX tiles dug and built in all. A long dig is designated
-- DIG_SEGMENT tiles a step, the dry run walked again before each segment.
-- The brain's water_far_reach, water_job_max and water_dig_segment set these
-- per call (opts.far_reach, job_max, segment).
FAR_REACH = nil
FAR_JOB_MAX = 600
DIG_SEGMENT = 40
FAR_TRIES = 4           -- far bodies a plan tries at most (the cheapest)
MAGMA_NEAR = 12         -- (0.105.38) a magma workshop's stair this far from the fort's middle: a tunnel joins it to the fort

local NATURAL = {STONE = true, MINERAL = true, SOIL = true, LAVA_STONE = true}
-- (0.105.33) open space is 'EMPTY' in df.tiletype_shape (what tile_info gives);
-- 'OPEN_SPACE' is no shape name, so tests for it never matched in the game
local OPEN = {FLOOR = true, RAMP = true, RAMP_TOP = true, STAIR_UP = true,
              STAIR_DOWN = true, STAIR_UPDOWN = true, SHRUB = true, SAPLING = true, PEBBLES = true,
              BOULDER = true, EMPTY = true, BROOK_TOP = true}
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

---------------------------------------------------------------------------
-- Hooks (the game; the tests swap these)
---------------------------------------------------------------------------

local BUILDER
function T(x, y, z)
    BUILDER = BUILDER or reqscript('ai-builder')
    local ok, t = pcall(BUILDER.tile_info, x, y, z)
    return ok and t or nil
end

-- What stands on these tiles that water must never reach: {key = why}
-- (a citizen, a workshop, a bed, a stockpile, any other building)
function occupants(box)
    local out = {}
    local function inside(x, y, z)
        return z >= box.z1 and z <= box.z2 and x >= box.x1 and x <= box.x2 and y >= box.y1 and y <= box.y2
    end
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x and inside(x, y, z) then out[key(x, y, z)] = 'a citizen' end
        end
    end)
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b.z >= box.z1 and b.z <= box.z2 and b.x2 >= box.x1 and b.x1 <= box.x2
                    and b.y2 >= box.y1 and b.y1 <= box.y2 then
                local t = df.building_type[b:getType()]
                local why = (t == 'Workshop' or t == 'Furnace') and 'a workshop' or t == 'Bed' and 'a bed'
                    or t == 'Stockpile' and 'a stockpile' or ('a building (' .. tostring(t):lower() .. ')')
                for x = b.x1, b.x2 do for y = b.y1, b.y2 do out[key(x, y, b.z)] = why end end
            end
        end
    end)
    return out
end

-- (13c) the builder's: every cell in the dry run, then for real
function designate(cells, z, mode)
    local ok, r = pcall(function() return reqscript('ai-builder').designate(cells, z, mode) end)
    return ok and r == true
end

-- {id, built, closed} of a building of `kind` (a df.building_type name) at a tile
function building(x, y, z, kind)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b then return nil end
    local okt, t = pcall(function() return df.building_type[b:getType()] end)
    if kind and (not okt or t ~= kind) then return nil end
    local closed
    pcall(function() closed = b.gate_flags.closed end)
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage(), closed = closed}
end

function link(lever_id, target_id) return reqscript('ai-gates').link_lever(lever_id, target_id, false) end

-- every lever's links (ai-gates), or nil
function lever_links()
    local ok, links = pcall(function() return reqscript('ai-gates').lever_links() end)
    return ok and type(links) == 'table' and links or nil
end

-- links: lever_links() already fetched (the report fetches them once)
function is_linked(lever_id, target_id, links)
    links = links or lever_links()
    if not links then return false end
    for _, l in ipairs(links[target_id] or {}) do if l == lever_id then return true end end
    return false
end

function link_pending(lever_id)
    local ok, yes = pcall(function()
        for _, j in ipairs(df.building.find(lever_id).jobs) do
            if j.job_type == df.job_type.LinkBuildingToTrigger then return true end
        end
        return false
    end)
    return ok and yes
end

-- (13c) the builder's (a pull already on its way counts as done)
function pull(lever_id, instant)
    return reqscript('ai-builder').pull(lever_id, instant) == true
end

-- (0.105.33) a dwarf's pull on its way called off: after an instant shut,
-- a late pull would toggle the floodgate open again. (0.105.33 merge) the
-- builder's one copy (ai-builder-cistern.lua cancel_lever_pulls); this loop
-- only when it can't be had
function cancel_pulls(lever_id)
    local okb, B = pcall(reqscript, 'ai-builder')
    if okb and type(B) == 'table' and type(B.cancel_lever_pulls) == 'function' then
        local okc, n = pcall(B.cancel_lever_pulls, lever_id)
        if okc then return n end
    end
    pcall(function()
        local list = {}
        for _, j in ipairs(df.building.find(lever_id).jobs) do
            if j.job_type == df.job_type.PullLever then table.insert(list, j) end
        end
        for _, j in ipairs(list) do dfhack.job.removeJob(j) end
    end)
end

function dig_now(x, y, z)
    local pos = ('%d,%d,%d'):format(x, y, z)
    pcall(dfhack.run_command_silent, 'dig-now', pos, pos)
end

function citizens() return reqscript('ai-builder').citizen_positions() end
function water_survey() return reqscript('ai-water').last() end
function mud(x, y, z) return reqscript('ai-builder').mud_at(x, y, z) end
function now()
    local ok, v = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and v or 0
end

-- surface entrances from the gate scan (lua/ai-gates.lua): {x, y, z} inside tiles
function entrances()
    local out = {}
    pcall(function()
        for _, e in ipairs(reqscript('ai-gates').summary().entrances or {}) do
            if e.kind == 'surface' then table.insert(out, {x = e.x, y = e.y, z = e.z, id = e.id}) end
        end
    end)
    return out
end

function set_name(id, name)
    pcall(function() df.building.find(id).name = name end)
end

-- (0.105.36) a screw pump set to be worked by hand (DF's "Start pump
-- manually"; df-structures building_screw_pumpst.pump_manually, the game's
-- wants_to_pump): without it no dwarf with the pump operator labour works it
function set_pump_manual(id, on)
    local ok = pcall(function() df.building.find(id).pump_manually = on == true end)
    return ok
end

-- (0.105.37 E3) W7, the power's machines (df-structures df.building.xml,
-- df.machine.xml): a building's machine (machine_info.machine_id into
-- world.machines.all) has cur_power (total_power) and min_power
-- (total_power_needed); {cur, need} or nil
function machine_power(id)
    local ok, r = pcall(function()
        local b = df.building.find(id)
        local m = df.machine.find(b.machine.machine_id)
        return {cur = math.tointeger(m.cur_power) or 0, need = math.tointeger(m.min_power) or 0}
    end)
    return ok and r or nil
end

-- a water wheel turning (building_water_wheelst.gives_power, the game's
-- in_flow: water flowing under it); nil: not known
function wheel_turning(id)
    local ok, v = pcall(function() return df.building.find(id).gives_power == true end)
    if ok then return v end
    return nil
end

-- a windmill turning (building_windmillst.is_working, the game's in_flow:
-- the map's wind on it); nil: not known
function windmill_turning(id)
    local ok, v = pcall(function() return (tonumber(df.building.find(id).is_working) or 0) > 0 end)
    if ok then return v end
    return nil
end

-- a gear assembly engaged (building_gear_assemblyst.gear_flags.disengaged
-- unset; a lever linked to it toggles it); nil: not known
function gear_engaged(id)
    local ok, v = pcall(function() return not df.building.find(id).gear_flags.disengaged end)
    if ok then return v end
    return nil
end

-- the windmill placed (quickfort has no windmill key): a 3x3 construction
-- centred on (x, y), its parts fetched by the dwarves (DFHack's default filters)
function place_windmill(x, y, z)
    local ok, b = pcall(function()
        return dfhack.buildings.constructBuilding({type = df.building_type.Windmill, x = x - 1, y = y - 1, z = z,
                                                   width = 3, height = 3})
    end)
    return ok and b ~= nil
end

-- a hatch locked (DFHack forbids it, as the gates do): nothing walks through
function lock_hatch(id)
    pcall(function() df.building.find(id).door_flags.forbidden = true end)
end

-- (0.105.0 review) Pure: is a material magma-safe, from its heat numbers
-- (material.heat: mat_fixed_temp, melting_point, boiling_point, ignite_point,
-- heatdam_point; 60001 = none)? As DF reckons it: a material held at a
-- fixed temperature is safe; otherwise none of its points may be at or under
-- magma's 12000 degrees (60001, "none", is above it).
MAGMA_TEMP = 12000
function magma_safe_heat(h)
    if type(h) ~= 'table' then return false end
    local fixed = tonumber(h.mat_fixed_temp)
    if fixed and fixed ~= 60001 then return true end      -- held at its own temperature
    for _, k in ipairs({'melting_point', 'boiling_point', 'ignite_point', 'heatdam_point'}) do
        local v = tonumber(h[k])
        if v == nil or v <= MAGMA_TEMP then return false end
    end
    return true
end

local function item_magma_safe(it)
    local ok, yes = pcall(function()
        local mi = dfhack.matinfo.decode(it)
        local h = mi.material.heat
        return magma_safe_heat({mat_fixed_temp = h.mat_fixed_temp, melting_point = h.melting_point,
                                boiling_point = h.boiling_point, ignite_point = h.ignite_point,
                                heatdam_point = h.heatdam_point})
    end)
    return ok and yes or false
end

-- (0.105.0 review) the free magma-safe parts a magma work needs:
-- {floodgates, hatches, mechanisms} (free: not forbidden, in a building or a job)
MAGMA_PARTS = {floodgates = 'FLOODGATE', hatches = 'HATCH_COVER', mechanisms = 'TRAPPARTS'}
function magma_parts()
    local out = {}
    for k, tname in pairs(MAGMA_PARTS) do
        out[k] = 0
        pcall(function()
            local B = reqscript('ai-builder')       -- (13c) its item_held, the one copy
            for _, it in ipairs(df.global.world.items.other[tname]) do
                if not (B.item_held(it) or it.flags.in_job) and item_magma_safe(it) then
                    out[k] = out[k] + 1
                end
            end
        end)
    end
    return out
end

-- (0.105.0 review) a built building's material magma-safe (its construction material)
function building_magma_safe(id)
    local ok, yes = pcall(function()
        local b = df.building.find(id)
        local mi = dfhack.matinfo.decode(b.mat_type, b.mat_index)
        local h = mi.material.heat
        return magma_safe_heat({mat_fixed_temp = h.mat_fixed_temp, melting_point = h.melting_point,
                                boiling_point = h.boiling_point, ignite_point = h.ignite_point,
                                heatdam_point = h.heatdam_point})
    end)
    if not ok then return nil end
    return yes
end

-- (0.105.0 review) buildingplan's heat-safety filter (0 none, 1 fire, 2 magma)
-- for the floodgate and the hatch, set before they are placed (buildingplan
-- applies its filters to buildings quickfort places). on: the player's own
-- filters kept and returned (a table); pass that table back to restore them.
-- nil: not available.
function magma_filter(on)
    local ok, r = pcall(function()
        local bp = require('plugins.buildingplan')
        local kept = {}
        for _, t in ipairs({df.building_type.Floodgate, df.building_type.Hatch}) do
            if on == true then
                local okg, h = pcall(bp.getHeatSafetyFilter, t, -1, -1)
                kept[t] = okg and tonumber(h) or 0
                bp.setHeatSafetyFilter(t, -1, -1, 2)
            else
                bp.setHeatSafetyFilter(t, -1, -1, type(on) == 'table' and on[t] or 0)
            end
        end
        return kept
    end)
    return ok and r or nil
end

-- the elevation the game shows
function ez(z)
    local ok, v = pcall(function() return df.global.world.map.region_z - 100 end)
    return z + (ok and math.tointeger(v) or 0)
end

---------------------------------------------------------------------------
-- State
---------------------------------------------------------------------------

function load_state()
    local ok, d = pcall(dfhack.persistent.getSiteData, STATE_KEY, {})
    d = ok and type(d) == 'table' and d or {}
    d.works = type(d.works) == 'table' and d.works or {}
    d.refused = type(d.refused) == 'table' and d.refused or {}
    return d
end
function save_state(d) pcall(dfhack.persistent.saveSiteData, STATE_KEY, d) end

---------------------------------------------------------------------------
-- Tiles
---------------------------------------------------------------------------

-- solid natural rock with nothing in it (water, magma, aquifer, cavern, sky)
local function rock(t, warm_ok)
    return t ~= nil and t.shape == 'WALL' and not t.liquid and not t.aquifer and not t.feature
        and not t.outside and NATURAL[t.material] == true and (warm_ok or not t.warm)
end

-- open ground under the sky with natural rock or soil under it (a channel there)
local function ground(x, y, z)
    local t, b = T(x, y, z), T(x, y, z - 1)
    return t ~= nil and t.outside and (t.shape == 'FLOOR' or t.shape == 'SHRUB' or t.shape == 'SAPLING'
        or t.shape == 'PEBBLES') and not t.liquid and not t.building
        and b ~= nil and b.shape == 'WALL' and not b.aquifer and not b.feature and NATURAL[b.material] == true
end

local function still_water(t)
    return t ~= nil and t.liquid and not t.magma and (t.depth or 0) >= 1 and not t.salt
        and t.material ~= 'RIVER' and t.material ~= 'BROOK' and not t.feature
end

-- An L-shaped run of tiles from a (included) to b (excluded) on one level,
-- each passing ok(x, y); the x-first or the y-first way, whichever passes
-- (only: true or false, that way alone).
local function l_path(a, b, ok, only)
    for _, xfirst in ipairs(only == nil and {true, false} or {only}) do
        local path, x, y, good = {}, a.x, a.y, true
        local function walk(tx, ty)
            while (x ~= tx or y ~= ty) and good do
                table.insert(path, {x = x, y = y})
                if not ok(x, y) then good = false end
                if x ~= tx then x = x + (tx > x and 1 or -1) else y = y + (ty > y and 1 or -1) end
            end
        end
        if xfirst then walk(b.x, a.y); walk(b.x, b.y) else walk(a.x, b.y); walk(b.x, b.y) end
        if good and #path > 0 then return path end
    end
    return nil
end

local N4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
local N8 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}

---------------------------------------------------------------------------
-- The dry run: where the water (or magma) would go
---------------------------------------------------------------------------

-- (0.105.33) The source's side of the floodgate: the plug's wet tile and
-- the plan's `upstream` tiles (a tunnel between the plug and the gate).
local function upstream_of(p)
    local up = {}
    if p.plug and p.gate then up[key(p.plug.x, p.plug.y, p.gate.z)] = true end
    for _, c in ipairs(p.upstream or {}) do up[key(c.x, c.y, c.z)] = true end
    return up
end

-- (0.105.33) Pure: does the liquid get round the floodgate? Water and magma
-- flow diagonally, so a dug tile (other than the plug) with liquid among its
-- 8 neighbours fills as soon as it is dug, before the floodgate is built;
-- and a tile on the fort's side (other than the gate) touching the source's
-- side lets the liquid skip the gate. nil, or {why, x, y, z}.
function bypass(p)
    local up = upstream_of(p)
    local gk = p.gate and key(p.gate.x, p.gate.y, p.gate.z)
    local exempt = {}
    if p.plug then
        exempt[key(p.plug.x, p.plug.y, p.plug.z)] = true
        if p.gate then exempt[key(p.plug.x, p.plug.y, p.gate.z)] = true end
    end
    local seen = {}
    for _, list in ipairs({p.tiles or {}, p.wet or {}, p.dig or {}, p.dig2 or {}}) do
        for _, c in ipairs(list) do
            local k = key(c.x, c.y, c.z)
            if not seen[k] then
                seen[k] = true
                for _, d in ipairs(N8) do
                    local x, y = c.x + d[1], c.y + d[2]
                    local nk = key(x, y, c.z)
                    if not exempt[k] then
                        local t = T(x, y, c.z)
                        if t and t.liquid then
                            return {why = ('liquid beside the dug tile at x%d y%d (only the plug may touch it): '
                                           .. 'it would get round the floodgate'):format(c.x, c.y), x = x, y = y, z = c.z}
                        end
                    end
                    if not up[k] and k ~= gk and up[nk] then
                        return {why = ('the tile at x%d y%d touches the source\'s side of the floodgate: '
                                       .. 'the liquid would go round the floodgate'):format(c.x, c.y), x = c.x, y = c.y, z = c.z}
                    end
                end
            end
        end
    end
    return nil
end

-- Walks the liquid from the work's own tiles (the plan's `wet`), over its
-- planned tiles and any open tile beside them, on the level and down through
-- open space (and, under pressure, up: a pumped stack, or a river whose
-- higher reaches push it, to `pressure_top` at most). Liquid met from the
-- source's side is the source; met from any other tile, the floodgate is
-- bypassed: refused (0.105.33). Refuses at a citizen, workshop, bed,
-- stockpile or other building, the fort's inside (a moat), or any tile
-- outside the plan underground. {ok, tiles, outside, why, at}
function path_check(p)
    local planned, wet = {}, {}
    for _, c in ipairs(p.tiles) do planned[key(c.x, c.y, c.z)] = true end
    local box = {x1 = math.huge, y1 = math.huge, z1 = math.huge, x2 = -math.huge, y2 = -math.huge, z2 = -math.huge}
    for _, c in ipairs(p.tiles) do
        box.x1, box.y1, box.z1 = math.min(box.x1, c.x - 30), math.min(box.y1, c.y - 30), math.min(box.z1, c.z - 3)
        box.x2, box.y2, box.z2 = math.max(box.x2, c.x + 30), math.max(box.y2, c.y + 30), math.max(box.z2, c.z + 1)
    end
    local occ = occupants(box)
    local seen, queue, head, outside_n = {}, {}, 1, 0
    local function refuse(why, x, y, z)
        return {ok = false, tiles = #queue, why = why, at = {x = x, y = y, z = z, e = ez(z)}}
    end
    local by = bypass(p)
    if by then return refuse(by.why, by.x, by.y, by.z) end
    local up_side = upstream_of(p)
    for _, c in ipairs(p.wet) do
        local k = key(c.x, c.y, c.z)
        if not seen[k] then seen[k] = true; table.insert(queue, c) end
    end
    while head <= #queue do
        local c = queue[head]
        head = head + 1
        local k = key(c.x, c.y, c.z)
        if occ[k] then return refuse(occ[k] .. ' in the way', c.x, c.y, c.z) end
        if not planned[k] then
            local t = T(c.x, c.y, c.z)
            if p.kind == 'moat' and t and t.outside then
                outside_n = outside_n + 1
            else
                return refuse(p.kind == 'moat' and 'the water would reach the fort\'s inside'
                              or 'the ' .. (p.kind == 'magma' and 'magma' or 'water')
                                 .. ' would spread past the planned tiles', c.x, c.y, c.z)
            end
        end
        if #queue > PATH_MAX then return refuse('the water could spread past ' .. PATH_MAX .. ' tiles', c.x, c.y, c.z) end
        local from_source, met = up_side[k], nil
        local function visit(x, y, z)
            local nk = key(x, y, z)
            if seen[nk] or (p.stops and p.stops[nk]) then return end
            local t = T(x, y, z)
            if not t then return end
            if planned[nk] then seen[nk] = true; table.insert(queue, {x = x, y = y, z = z}) return end
            if t.liquid then                                -- the source itself, from its side only
                if not from_source then met = met or {x = x, y = y, z = z} end
                return
            end
            if OPEN[t.shape] then seen[nk] = true; table.insert(queue, {x = x, y = y, z = z}) end
        end
        for _, d in ipairs(N8) do visit(c.x + d[1], c.y + d[2], c.z) end
        if p.pressure and (p.pressure_top == nil or c.z + 1 <= p.pressure_top) then
            -- (water under pressure climbs through any opening above: the work's
            -- own channels count, dug or not)
            local uk = key(c.x, c.y, c.z + 1)
            local up = T(c.x, c.y, c.z + 1)
            if up and (up.shape == 'EMPTY' or up.shape == 'STAIR_DOWN' or up.shape == 'STAIR_UPDOWN'
                       or up.shape == 'RAMP_TOP' or (p.channels and p.channels[uk]))
                    and not (p.stops and p.stops[uk]) then
                visit(c.x, c.y, c.z + 1)
            end
        end
        local below = T(c.x, c.y, c.z - 1)
        local here = T(c.x, c.y, c.z)
        if below and (here == nil or here.shape == 'EMPTY' or here.shape == 'STAIR_DOWN'
                      or here.shape == 'STAIR_UPDOWN' or planned[k] and p.down and p.down[k]) then
            visit(c.x, c.y, c.z - 1)
        end
        if met then
            return refuse('liquid that is not the work\'s source lies beside its water\'s way: '
                          .. 'it would get round the floodgate', met.x, met.y, met.z)
        end
    end
    return {ok = true, tiles = #queue, outside = outside_n}
end

---------------------------------------------------------------------------
-- (0.105.38) Far sources: the whole-map survey's bodies, by cost
---------------------------------------------------------------------------

FAR = {}                -- this call's settings: {reach, job_max, segment}

-- the reach a far source may lie at most: the brain's, or the map's width
function far_cap(w)
    local r = math.tointeger(tonumber(FAR.reach)) or FAR_REACH
    if r and r > 0 then return r end
    local m = type(w) == 'table' and w.map or nil
    return type(m) == 'table' and math.tointeger(tonumber(m.w)) or 192
end

function far_job_max() return math.tointeger(tonumber(FAR.job_max)) or FAR_JOB_MAX end
function dig_segment() return math.max(5, math.tointeger(tonumber(FAR.segment)) or DIG_SEGMENT) end

-- A body's cost: its reach estimate (a dig through safe rock), else the
-- distance plus a half (a channel over ground, or a dig the estimate could
-- not walk), plus `extra(b)`.
function source_cost(b, extra)
    local base = tonumber(b.reach) or ((tonumber(b.reach_through) or tonumber(b.d) or 1e6) * 3 // 2)
    return base + (extra and extra(b) or 0)
end

-- The survey's bodies `want(b)` takes, within the far cap, cheapest first
-- (FAR_TRIES at most); `skip` a nearest tile already tried {x, y, z}.
function far_sources(w, want, skip, extra, tries)
    local out = {}
    local cap = far_cap(w)
    for _, b in ipairs(type(w) == 'table' and type(w.waters) == 'table' and w.waters or {}) do
        local n = type(b) == 'table' and b.nearest or nil
        if type(n) == 'table' and n.x and n.y and n.z and want(b) and (tonumber(b.d) or math.huge) <= 2 * cap
                and not (skip and skip.x == n.x and skip.y == n.y and skip.z == n.z) then
            table.insert(out, {b = b, cost = source_cost(b, extra)})
        end
    end
    table.sort(out, function(a, b) return a.cost < b.cost end)
    local res = {}
    for i = 1, math.min(#out, tries or FAR_TRIES) do res[i] = out[i].b end
    return res
end

-- A plan's dig in segments (p.stages: {first, last} indices into p.dig),
-- when it is longer than a segment; and the plan's size checked against the
-- job cap. nil, or why not.
function job_too_big(p)
    local n = #(p.dig or {}) + #(p.dig2 or {}) + #(p.builds or {})
    if n > far_job_max() then
        return ('the work would dig and build %d tiles (%d at most)'):format(n, far_job_max())
    end
    return nil
end

function stage_plan(p)
    local big = job_too_big(p)
    if big then return big end
    local seg = dig_segment()
    if #(p.dig or {}) > seg then
        p.stages = {}
        for i = 1, #p.dig, seg do table.insert(p.stages, {i, math.min(#p.dig, i + seg - 1)}) end
    end
    return nil
end

local function seg_cells(p, i)
    local st = p.stages and p.stages[i]
    if not st then return p.dig end
    local out = {}
    for k = st[1], st[2] do table.insert(out, p.dig[k]) end
    return out
end

---------------------------------------------------------------------------
-- Plans. Each: {kind, dig = {{x,y,z,text}}, dig2, gate = {x,y,z}, plug =
-- {x,y,z,text}, lever = {x,y,z,name}, builds = {{x,y,z,text,kind}},
-- finish = {...}, wet = tiles the liquid fills, tiles = every tile it may
-- reach, test = {mode, x,y,z | tiles}}
---------------------------------------------------------------------------

local function fort_box()
    local cs = citizens() or {}
    if #cs == 0 then return nil end
    local xs, ys, zs = 0, 0, {}
    local per = {}
    for _, c in ipairs(cs) do
        xs, ys = xs + c.x, ys + c.y
        table.insert(zs, c.z)
        per[c.z] = (per[c.z] or 0) + 1
    end
    table.sort(zs)
    local busy, bn = zs[1], 0
    for z, n in pairs(per) do if n > bn or (n == bn and z < busy) then busy, bn = z, n end end
    return {x = xs // #cs, y = ys // #cs, z_low = zs[1], z_high = zs[#zs], z_busy = busy}
end

-- A free floor inside the fort on level z near (x, y) for a lever.
function lever_spot(x, y, z, avoid)
    for r = 0, 20 do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local tx, ty = x + dx, y + dy
                    local t = T(tx, ty, z)
                    if t and t.shape == 'FLOOR' and not t.outside and not t.liquid and not t.building
                            and not t.designated and not (avoid and avoid[key(tx, ty, z)]) then
                        return {x = tx, y = ty, z = z}
                    end
                end
            end
        end
    end
    return nil
end

local function add_tiles(p, list)
    for _, c in ipairs(list) do table.insert(p.tiles, {x = c.x, y = c.y, z = c.z}) end
end

-- W3: a trench across the approach to a surface gate, fed from the river
-- through a floodgate, crossed by a drawbridge (a plain bridge: no lever).
-- (0.105.38) one river's moat: the river's nearest tile, its highest level,
-- the feed's length at most; far: the channel's ground checked for an
-- aquifer or a cavern under it (said by name), the dig staged
local function moat_for(river, river_z2, feed_max, opts, es, far)
    local why
    local bad                                   -- (0.105.38) why the far channel's ground won't do
    local function feed_ground(x, y, z)
        if ground(x, y, z) then return true end
        if far and not bad then
            local b = T(x, y, z - 1)
            if b and b.aquifer then bad = ('an aquifer under the channel at x%d y%d'):format(x, y)
            elseif b and b.feature then bad = ('a cavern under the channel at x%d y%d'):format(x, y)
            elseif b and b.liquid and b.magma then bad = ('magma under the channel at x%d y%d'):format(x, y) end
        end
        return false
    end
    for _, e in ipairs(es) do
        -- the side the outside lies on
        local dir
        for _, d in ipairs(N4) do
            local t = T(e.x + d[1], e.y + d[2], e.z)
            if t and t.outside and OPEN[t.shape] and not t.liquid then dir = d break end
        end
        if not dir then why = why or 'the gate has no open ground outside it' goto next end
        do
            local z = e.z
            if river.z ~= z - 1 then
                why = why or ('the river\'s water is not one level under the ground at the gate (river at elevation %d, '
                              .. 'ground %d): a moat there would overflow or stay dry'):format(ez(river.z), ez(z))
                goto next
            end
            local px, py = -dir[2], dir[1]                  -- along the trench
            local cx, cy = e.x + dir[1] * (MOAT_GAP + 1), e.y + dir[2] * (MOAT_GAP + 1)
            local trench = {}
            for i = -MOAT_HALF, MOAT_HALF do
                local x, y = cx + px * i, cy + py * i
                if not ground(x, y, z) then why = why or ('the ground across the approach is not diggable at x%d y%d'):format(x, y) goto next end
                table.insert(trench, {x = x, y = y, z = z, i = i})
            end
            -- the trench end nearer the river, then the feed to the river's edge
            local a, b = trench[1], trench[#trench]
            local function dist(t) return math.max(math.abs(t.x - river.x), math.abs(t.y - river.y)) end
            local from = dist(a) <= dist(b) and a or b
            local start = {x = from.x + (from == a and -px or px), y = from.y + (from == a and -py or py)}
            -- (0.105.33) the feed stops at the tile beside the river (the plug);
            -- its corner never at the floodgate: the tile before the gate would
            -- touch the plug diagonally and the water go round the gate
            local feed, cornered
            for _, xfirst in ipairs({true, false}) do
                local f = l_path(start, river, function(x, y) return feed_ground(x, y, z) end, xfirst)
                while f and #f > 0 do
                    local l = f[#f]
                    local nb = T(l.x, l.y, z)
                    if math.max(math.abs(l.x - river.x), math.abs(l.y - river.y)) <= 1 then break end
                    if nb and nb.liquid then table.remove(f) else break end
                end
                if f and #f >= 3 and math.max(math.abs(f[#f - 2].x - f[#f].x), math.abs(f[#f - 2].y - f[#f].y)) <= 1 then
                    cornered, f = true, nil
                end
                if f then feed = f break end
            end
            if not feed then
                why = why or (cornered and 'the feed channel would turn its corner at the floodgate (the water would go round it)'
                              or (bad and ('no safe ground for a channel from the river to the trench: ' .. bad))
                              or 'no diggable ground for a channel from the river to the trench')
                goto next
            end
            if #feed < 3 then why = why or 'the river is too close to the trench for a floodgate between' goto next end
            if #feed > feed_max then why = why or ('the river is %d tiles from the trench (%d at most)'):format(#feed, feed_max) goto next end
            local plug = feed[#feed]
            local gate = feed[#feed - 1]
            local cs = citizens() or {}
            local lever = lever_spot(e.x - dir[1] * 3, e.y - dir[2] * 3, z)
                or (cs[1] and lever_spot(cs[1].x, cs[1].y, cs[1].z))
            if not lever then why = why or 'no free floor inside for the moat\'s lever' goto next end
            lever.name = 'AI moat'
            local p = {kind = 'moat', entrance = e.id, dig = {}, dig2 = {}, builds = {}, tiles = {}, wet = {},
                       gate = {x = gate.x, y = gate.y, z = z - 1}, lever = lever,
                       plug = {x = plug.x, y = plug.y, z = z, text = 'h'}, river = river,
                       test = {mode = 'deep', x = cx, y = cy, z = z - 1, want = 3}}
            for _, t in ipairs(trench) do
                table.insert(p.dig, {x = t.x, y = t.y, z = z, text = 'h'})
                table.insert(p.wet, {x = t.x, y = t.y, z = z - 1})
            end
            for i = 1, #feed - 1 do
                table.insert(p.dig, {x = feed[i].x, y = feed[i].y, z = z, text = 'h'})
                table.insert(p.wet, {x = feed[i].x, y = feed[i].y, z = z - 1})
            end
            table.insert(p.wet, {x = plug.x, y = plug.y, z = z - 1})
            -- (0.105.33) river water can be under pressure (from the river's
            -- higher reaches): the dry run lets it climb to one level under the
            -- river's highest water the survey saw, up through the channels dug
            p.pressure = true
            p.pressure_top = math.max(tonumber(river_z2) or river.z, river.z) - 1
            p.channels = {}
            for _, c in ipairs(p.dig) do p.channels[key(c.x, c.y, c.z)] = true end
            p.channels[key(plug.x, plug.y, z)] = true
            -- the floodgate stands on a floor: the ramp a channel leaves under it removed
            table.insert(p.dig2, {x = gate.x, y = gate.y, z = z - 1, text = 'z'})
            add_tiles(p, p.wet)
            -- the crossing: three trench tiles on the gate's line
            local bx1, by1 = cx + px * -1, cy + py * -1
            local bw, bh = (px ~= 0) and 3 or 1, (py ~= 0) and 3 or 1
            local bdir = dir[2] == 1 and 'gx' or dir[2] == -1 and 'gw' or dir[1] == 1 and 'gd' or 'ga'
            local bx, by = math.min(bx1, cx + px), math.min(by1, cy + py)
            p.bridge = {x = bx, y = by, z = z, w = bw, h = bh, drawbridge = opts.plain ~= true}
            table.insert(p.builds, {x = bx, y = by, z = z, text = ('%s(%dx%d)'):format(bdir, bw, bh), kind = 'Bridge'})
            local by = bypass(p)             -- (0.105.33) the water never round the floodgate
            if by then why = why or by.why goto next end
            if far then
                p.far = {d = #feed, kind = 'channel'}
                local big = stage_plan(p)
                if big then why = why or big goto next end
            end
            return p
        end
        ::next::
    end
    return nil, why or 'no gate fit for a moat'
end

function plan_moat(opts)
    opts = opts or {}
    local w = water_survey()
    if not w then return nil, 'no water survey yet' end
    local river, river_z2
    for _, b in ipairs(w.bodies or {}) do if b.kind == 'river' then river, river_z2 = b.nearest, b.z2 end end
    -- (0.105.38) the far rivers and brooks, the cheapest first
    local far = far_sources(w, function(b) return b.flow == 'flowing' end, river)
    if not river and #far == 0 then return nil, 'no river or brook near the fort' end
    local es = entrances()
    if #es == 0 then return nil, 'no surface entrance found (scan the entrances first)' end
    local why
    if river then
        local p, w1 = moat_for(river, river_z2, MOAT_FEED_MAX, opts, es, false)
        if p then return p end
        why = w1
    end
    for _, b in ipairs(far) do
        local p, w2 = moat_for(b.nearest, b.z2, far_cap(w), opts, es, true)
        if p then return p end
        why = why or (('the %s %d tiles off: '):format(b.kind or 'river', tonumber(b.d) or 0) .. tostring(w2))
    end
    return nil, why
end

-- W4: screw pumps lifting still water from a level below to a 3x3
-- reservoir under the fort's lowest level (a well goes over it later).
-- Worked by a dwarf (the pump operator labour).
local function pump_at(src, fb, w)
    local why_b
    local zt = fb.z_low - 1                         -- the reservoir, under the lowest fort level
    local zs = src.z
    local lift = zt - zs
    if lift < 1 then return nil, 'the water is not below the reservoir level' end
    if lift > PUMP_MAX_LIFT then return nil, ('the water is %d levels under the fort (%d at most)'):format(lift, PUMP_MAX_LIFT) end
    local s = T(src.x, src.y, zs)
    if not still_water(s) then return nil, 'the water under the fort is not still and fresh' end
    for _, d in ipairs(N4) do
        -- water W, plug P, gate G, sump A, then B beside A and the stair C
        local P = {x = src.x + d[1], y = src.y + d[2]}
        local G = {x = P.x + d[1], y = P.y + d[2]}
        local A = {x = G.x + d[1], y = G.y + d[2]}
        local B = {x = A.x + d[1], y = A.y + d[2]}
        local C = {x = A.x - d[2], y = A.y + d[1]}           -- beside A, off the line
        local ok = rock(T(P.x, P.y, zs)) and rock(T(G.x, G.y, zs)) and rock(T(A.x, A.y, zs)) and rock(T(C.x, C.y, zs))
        for z = zs + 1, zt do
            for _, q in ipairs({A, B, C}) do if not rock(T(q.x, q.y, z)) then ok = false end end
        end
        -- the reservoir beyond B on the top level
        local R = {}
        local rx, ry = B.x + d[1] * 2, B.y + d[2] * 2
        for dx = -1, 1 do for dy = -1, 1 do
            local x, y = rx + dx, ry + dy
            if not rock(T(x, y, zt)) then ok = false end
            table.insert(R, {x = x, y = y, z = zt})
        end end
        local top = T(rx, ry, zt + 1)
        local ctop = T(C.x, C.y, zt + 1)
        if not (top and top.shape == 'FLOOR' and not top.outside and not top.building) then ok = false end
        if not (ctop and ctop.shape == 'FLOOR' and not ctop.outside and not ctop.building) then ok = false end
        if ok then
            local p = {kind = 'pump', dig = {}, builds = {}, tiles = {}, wet = {}, down = {},
                       gate = {x = G.x, y = G.y, z = zs}, plug = {x = P.x, y = P.y, z = zs, text = 'd'},
                       lift = lift, power = 'dwarf', source = {x = src.x, y = src.y, z = zs},
                       reservoir = {x = rx, y = ry, z = zt},
                       test = {mode = 'rise', x = rx, y = ry, z = zt, want = 4}}
            table.insert(p.dig, {x = G.x, y = G.y, z = zs, text = 'd'})
            table.insert(p.dig, {x = A.x, y = A.y, z = zs, text = 'd'})
            table.insert(p.dig, {x = C.x, y = C.y, z = zs, text = 'u'})
            for _, q in ipairs({P, G, A, C}) do table.insert(p.wet, {x = q.x, y = q.y, z = zs}) end
            for z = zs + 1, zt do
                local k = z - zs
                local intake, out = (k % 2 == 1) and A or B, (k % 2 == 1) and B or A
                table.insert(p.dig, {x = intake.x, y = intake.y, z = z, text = 'h'})
                table.insert(p.dig, {x = out.x, y = out.y, z = z, text = 'd'})
                table.insert(p.dig, {x = C.x, y = C.y, z = z, text = 'i'})
                -- the pump: 1x2 over the intake, pumping from the intake's side
                -- (quickfort Ms + u/k/m/h = from north/east/south/west: a guess)
                local fx, fy = intake.x - out.x, intake.y - out.y
                local from = fy == -1 and 'u' or fx == 1 and 'k' or fy == 1 and 'm' or 'h'
                local w_, h_ = (fx ~= 0) and 2 or 1, (fy ~= 0) and 2 or 1
                table.insert(p.builds, {x = math.min(intake.x, out.x), y = math.min(intake.y, out.y), z = z,
                                        text = ('Ms%s(%dx%d)'):format(from, w_, h_), kind = 'ScrewPump'})
                for _, q in ipairs({A, B, C}) do table.insert(p.tiles, {x = q.x, y = q.y, z = z}) end
                p.down[key(intake.x, intake.y, z)] = true
            end
            for _, r in ipairs(R) do
                if not (r.x == rx and r.y == ry) then table.insert(p.dig, {x = r.x, y = r.y, z = zt, text = 'd'}) end
            end
            table.insert(p.dig, {x = rx, y = ry, z = zt, text = 'd'})
            table.insert(p.dig, {x = C.x, y = C.y, z = zt + 1, text = 'j'})
            -- the stair into the stack covered by a locked hatch on the fort
            -- floor: pumped water is under pressure and would climb it
            table.insert(p.builds, {x = C.x, y = C.y, z = zt + 1, text = 'H', kind = 'Hatch', lock = true})
            p.stops = {[key(C.x, C.y, zt + 1)] = true}
            p.pressure = true
            -- (the top pump's output joins the reservoir: B or A on zt to it)
            local link_tiles = l_path({x = ((lift % 2 == 1) and B or A).x, y = ((lift % 2 == 1) and B or A).y},
                                      {x = rx, y = ry}, function(x, y)
                                          return rock(T(x, y, zt)) or (x == A.x and y == A.y) or (x == B.x and y == B.y) end)
            for _, l in ipairs(link_tiles or {}) do
                if not ((l.x == A.x and l.y == A.y) or (l.x == B.x and l.y == B.y)) then
                    table.insert(p.dig, {x = l.x, y = l.y, z = zt, text = 'd'})
                    table.insert(p.tiles, {x = l.x, y = l.y, z = zt})
                end
            end
            add_tiles(p, R)
            add_tiles(p, p.wet)
            p.wet = p.tiles          -- pumped water may stand anywhere in the stack
            local lv = lever_spot(C.x, C.y, zt + 1, {[key(rx, ry, zt + 1)] = true, [key(C.x, C.y, zt + 1)] = true})
            if not lv then return nil, 'no free floor for the pump\'s lever' end
            lv.name = 'AI pump'
            p.lever = lv
            -- the pump's water wheel: only beside a river (said, not built yet)
            for _, b in ipairs(w.bodies or {}) do if b.kind == 'river' then p.wheel = 'possible on the river' end end
            local by = bypass(p)         -- (0.105.33) the water never round the floodgate
            if not by then return p end
            why_b = why_b or by.why
        end
    end
    return nil, why_b or 'no solid rock beside the water for a sump, pumps and a reservoir'
end

function plan_pump(opts)
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local w = water_survey()
    if not w then return nil, 'no water survey yet' end
    local src
    for _, b in ipairs(w.bodies or {}) do
        if b.kind == 'pool' and b.nearest and b.nearest.z < fb.z_low then src = b.nearest end
    end
    -- (0.105.38) the whole map's other underground pools under the fort, the
    -- cheapest first (the stack stands beside its water, under a fort floor)
    local far = far_sources(w, function(b)
        return b.underground == true and b.nearest.z < fb.z_low and (tonumber(b.salt_share) or 0) == 0 end, src)
    if not src and #far == 0 then
        return nil, 'no still water under the fort outside the caverns (cavern water is not tunnelled to)'
    end
    local why
    if src then
        local p, w1 = pump_at(src, fb, w)
        if p then return p end
        why = w1
    end
    for _, b in ipairs(far) do
        local p, w2 = pump_at(b.nearest, fb, w)
        if p then p.far = {d = tonumber(b.d) or 0, kind = 'pool'} return p end
        why = why or w2
    end
    return nil, why
end

-- W5: a 5x5 room in stone under a fort level, muddied by a little water
-- let in through a floodgate, dried, then farm plots on the mud.
function plan_irrigation()
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local why
    for zf = fb.z_high, math.max(fb.z_low, fb.z_high - 3), -1 do
        local z = zf - 1
        -- still water on the room's level near the fort (the nearest 12 tiles)
        local waters = {}
        for dx = -30, 30 do for dy = -30, 30 do
            local t = T(fb.x + dx, fb.y + dy, z)
            if still_water(t) then table.insert(waters, {x = fb.x + dx, y = fb.y + dy, d = math.max(math.abs(dx), math.abs(dy))}) end
        end end
        table.sort(waters, function(a, b) return a.d < b.d end)
        while #waters > 12 do table.remove(waters) end
        -- (0.105.38) none near on this level: the survey's still water
        -- further off, the cheapest first, reached by a long tunnel (staged)
        if #waters == 0 then
            local w = water_survey()
            for _, b in ipairs(far_sources(w, function(b)
                    return b.flow == 'stagnant' and b.nearest.z == z and (tonumber(b.salt_share) or 0) == 0 end)) do
                local n = b.nearest
                if still_water(T(n.x, n.y, z)) then
                    local dd = math.max(math.abs(n.x - fb.x), math.abs(n.y - fb.y))
                    table.insert(waters, {x = n.x, y = n.y, d = dd, far = math.min(far_cap(w), dd + 2 * IRR_REACH)})
                end
            end
        end
        for _, wt in ipairs(waters) do
            for _, d in ipairs(N4) do
                for gap = 3, wt.far or IRR_REACH do
                    local cx, cy = wt.x + d[1] * (gap + 2), wt.y + d[2] * (gap + 2)
                    local above = T(cx - 2, cy - 2, zf)
                    local ok = true
                    -- (0.105.38) the fort floor over it first (a far source's long line is cheap to try)
                    if wt.far and not (above and above.shape == 'FLOOR' and not above.outside) then ok = false end
                    for x = cx - 2, cx + 2 do for y = cy - 2, cy + 2 do
                        if ok and not rock(T(x, y, z)) then ok = false end
                    end end
                    if ok and above and above.shape == 'FLOOR' and not above.outside and not above.building then
                        -- the tunnel from the room's side to the water
                        local edge = {x = cx - d[1] * 3, y = cy - d[2] * 3}
                        local path = l_path(edge, wt, function(x, y) return rock(T(x, y, z)) end)
                        if path and #path >= 2 then
                            local p = {kind = 'irrigation', dig = {}, builds = {}, tiles = {}, wet = {},
                                       gate = {x = path[1].x, y = path[1].y, z = z},
                                       plug = {x = path[#path].x, y = path[#path].y, z = z, text = 'd'},
                                       room = {x1 = cx - 2, y1 = cy - 2, x2 = cx + 2, y2 = cy + 2, z = z},
                                       test = {mode = 'wet', z = z}}
                            for x = cx - 2, cx + 2 do for y = cy - 2, cy + 2 do
                                local stair = x == cx - 2 and y == cy - 2
                                table.insert(p.dig, {x = x, y = y, z = z, text = stair and 'u' or 'd'})
                                table.insert(p.wet, {x = x, y = y, z = z})
                            end end
                            table.insert(p.dig, {x = cx - 2, y = cy - 2, z = zf, text = 'j'})
                            p.upstream = {}     -- (0.105.33) the tunnel between the gate and the plug
                            for i = 1, #path - 1 do
                                table.insert(p.dig, {x = path[i].x, y = path[i].y, z = z, text = 'd'})
                                table.insert(p.wet, {x = path[i].x, y = path[i].y, z = z})
                                if i >= 2 then table.insert(p.upstream, {x = path[i].x, y = path[i].y, z = z}) end
                            end
                            table.insert(p.wet, {x = p.plug.x, y = p.plug.y, z = z})
                            add_tiles(p, p.wet)
                            local lv = lever_spot(cx, cy, zf, {[key(cx - 2, cy - 2, zf)] = true})
                            if not lv then why = why or 'no free floor for the lever' goto skip end
                            lv.name = 'AI irrigation'
                            p.lever = lv
                            local by = bypass(p)     -- (0.105.33) the water never round the floodgate
                            if not by and wt.far then
                                p.far = {d = #path, kind = 'tunnel'}
                                local big = stage_plan(p)
                                if big then why = why or big goto skip end
                            end
                            if not by then return p end
                            why = why or by.why
                        end
                    end
                    ::skip::
                end
            end
        end
    end
    return nil, why or 'no still, fresh water beside solid rock under a fort level within reach'
end

-- Magma: a 5x5 room on the level over the magma, a stair down to it from the
-- fort, a pit under the workshop's middle, a tunnel from the pit to the
-- magma with a (magma-safe) floodgate; the service stair to the tunnel's
-- level covered by a locked hatch. Never through a cavern.
-- (0.105.38) A tunnel on the fort's lowest level from (x, y) toward the
-- fort's middle, through solid rock until it meets an open floor inside the
-- fort: its tiles (the first one excluded), or nil, why.
local function fort_tunnel(x, y, fb)
    local z = fb.z_low
    local why
    for _, xfirst in ipairs({true, false}) do
        local out, cx, cy, ok, met = {}, x, y, true, false
        local function walk(tx, ty)
            while ok and not met and (cx ~= tx or cy ~= ty) do
                if cx ~= tx and (xfirst or cy == ty) then cx = cx + (tx > cx and 1 or -1) else cy = cy + (ty > cy and 1 or -1) end
                local t = T(cx, cy, z)
                if t and OPEN[t.shape] and t.shape ~= 'EMPTY' and not t.outside and not t.liquid then met = true
                elseif not rock(t, true) then
                    ok = false
                    why = why or ('the tunnel to the fort would cross something other than solid rock at x%d y%d'):format(cx, cy)
                else table.insert(out, {x = cx, y = cy, z = z}) end
            end
        end
        if xfirst then walk(fb.x, y); walk(fb.x, fb.y) else walk(x, fb.y); walk(fb.x, fb.y) end
        if ok and met then return out end
        why = why or 'the tunnel to the fort met no fort floor'
    end
    return nil, why
end

local function magma_at(m, shop, fb)
    local why_b
    local zm, zw = m.z, m.z + 1
    if fb.z_low - zw > MAGMA_STAIR_MAX then return nil, 'the magma is too deep for a stair' end
    if zw >= fb.z_low then return nil, 'the magma is not below the fort' end
    for _, d in ipairs(N4) do
        for gap = 3, MAGMA_REACH do
            local P = {x = m.x + d[1] * gap, y = m.y + d[2] * gap}
            local path = l_path(P, m, function(x, y) return rock(T(x, y, zm), true) end)
            local ok = path ~= nil and #path >= 3
            -- the room on zw around P, all rock
            for x = P.x - 2, P.x + 2 do for y = P.y - 2, P.y + 2 do
                if not rock(T(x, y, zw), true) then ok = false end
            end end
            local S1 = {x = P.x - 2, y = P.y - 2}            -- the stair up to the fort
            local S2 = {x = P.x + 2, y = P.y + 2}            -- the service stair to the tunnel
            local S2t = T(S2.x, S2.y, zm)
            if ok and not rock(S2t, true) then ok = false end
            -- the service stair's foot must touch the tunnel on the pit's side
            -- of the floodgate (0.105.33: it joined the gate's own tile, and the
            -- tile beside the gate touched the tunnel on the magma's side too)
            local touches = path ~= nil and math.abs(path[1].x - S2.x) <= 1 and math.abs(path[1].y - S2.y) <= 1
            local why_s
            if ok then
                for z = zw + 1, fb.z_low do
                    local t = T(S1.x, S1.y, z)
                    if not t then ok = false break end
                    if t.feature then why_s = 'the way down crosses a cavern' ok = false break end
                    if z < fb.z_low and not rock(t, true) then ok = false break end
                end
            end
            if why_s then return nil, why_s end
            if ok then
                local p = {kind = 'magma', shop = shop, dig = {}, builds = {}, finish = {}, tiles = {}, wet = {}, down = {},
                           gate = {x = path[2].x, y = path[2].y, z = zm},
                           plug = {x = path[#path].x, y = path[#path].y, z = zm, text = 'd'},
                           pit = {x = P.x, y = P.y, z = zm}, room = {x = P.x, y = P.y, z = zw},
                           test = {mode = 'deep', x = P.x, y = P.y, z = zm, want = 4}}
                for x = P.x - 2, P.x + 2 do for y = P.y - 2, P.y + 2 do
                    local text = (x == S1.x and y == S1.y) and 'u' or (x == S2.x and y == S2.y) and 'j'
                        or (x == P.x and y == P.y) and 'h' or 'd'
                    table.insert(p.dig, {x = x, y = y, z = zw, text = text})
                end end
                for z = zw + 1, fb.z_low do
                    table.insert(p.dig, {x = S1.x, y = S1.y, z = z, text = z == fb.z_low and 'j' or 'i'})
                end
                -- (0.105.38) a stair far from the fort: a tunnel joins its top to the fort
                if math.max(math.abs(S1.x - fb.x), math.abs(S1.y - fb.y)) > MAGMA_NEAR then
                    local tun, twhy = fort_tunnel(S1.x, S1.y, fb)
                    if not tun then return nil, twhy end
                    for _, c in ipairs(tun) do table.insert(p.dig, {x = c.x, y = c.y, z = c.z, text = 'd'}) end
                    p.access = #tun
                end
                table.insert(p.dig, {x = S2.x, y = S2.y, z = zm, text = 'u'})
                if not touches then
                    local con = l_path({x = S2.x, y = S2.y}, path[1], function(x, y) return rock(T(x, y, zm), true) or (x == S2.x and y == S2.y) end)
                    for i = 2, #(con or {}) do
                        table.insert(p.dig, {x = con[i].x, y = con[i].y, z = zm, text = 'd'})
                        table.insert(p.wet, {x = con[i].x, y = con[i].y, z = zm})
                    end
                end
                p.upstream = {}                 -- (0.105.33) the tunnel between the gate and the plug
                for i = 1, #path - 1 do
                    table.insert(p.dig, {x = path[i].x, y = path[i].y, z = zm, text = 'd'})
                    table.insert(p.wet, {x = path[i].x, y = path[i].y, z = zm})
                    if i >= 3 then table.insert(p.upstream, {x = path[i].x, y = path[i].y, z = zm}) end
                end
                table.insert(p.wet, {x = S2.x, y = S2.y, z = zm})
                table.insert(p.wet, {x = p.plug.x, y = p.plug.y, z = zm})
                add_tiles(p, p.wet)
                -- the room's floor over the magma's level is not in its way
                p.builds = {{x = S2.x, y = S2.y, z = zw, text = 'H', kind = 'Hatch', lock = true}}
                p.finish = {{x = P.x, y = P.y, z = zw, text = MAGMA_SHOPS[shop], kind = shop == 'MagmaForge' and 'Workshop' or 'Furnace'}}
                local lv = lever_spot(P.x, P.y, zw, {[key(S1.x, S1.y, zw)] = true, [key(S2.x, S2.y, zw)] = true,
                                                     [key(P.x, P.y, zw)] = true})
                -- (the room is still rock when planned: the lever goes in its corner)
                lv = lv or {x = P.x + 2, y = P.y - 2, z = zw}
                lv.name = 'AI magma'
                p.lever = lv
                local by = bypass(p)             -- (0.105.33) the magma never round the floodgate
                if not by then return p end
                why_b = why_b or by.why
            end
        end
    end
    return nil, why_b or 'no solid rock between the magma and a workshop site within reach'
end

-- (0.105.38) the magma's kinds in the order a workshop takes them (cost
-- comes after): a pipe or anything else outside the deep layers, the sea last
MAGMA_RANK = {pipe = 0, volcano = 0, pool = 0, surface = 1, cavern = 2, sea = 3}

-- The magma workshop's magma: the near box's highest magma first (as
-- before 0.105.38), then the whole map's magma bodies by kind and cost (a
-- pipe before the sea); one whose dig opens a cavern only when the cavern
-- switch allows it (opts.open_caverns: the brain's Rules choice, Never /
-- Always / AI decides), never by this rule alone.
function plan_magma(shop, opts)
    shop = MAGMA_SHOPS[shop] and shop or 'MagmaForge'
    opts = type(opts) == 'table' and opts or {}
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local w = water_survey()
    local m = w and w.magma and w.magma.top_nearest
    local cands, why, held = {}, nil, nil
    if m then table.insert(cands, {m = m}) end
    for _, b in ipairs(far_sources(w, function(b) return b.kind == 'magma' end, nil, function(b)
            return 10000 * (MAGMA_RANK[b.magma] or 2) end, 8)) do
        if b.opens_cavern and opts.open_caverns ~= true then
            held = held or ('the %s magma %d tiles off: reaching it opens %s (the cavern switch does not allow it)')
                :format(tostring(b.magma), tonumber(b.d) or 0, tostring(b.opens_cavern))
        elseif b.aquifer and not b.reach then
            why = why or ('the %s magma: the way down crosses an aquifer'):format(tostring(b.magma))
        else
            local t = b.top or b.nearest
            if not (m and t.x == m.x and t.y == m.y and t.z == m.z) then
                table.insert(cands, {m = {x = t.x, y = t.y, z = t.z}, b = b})
            end
        end
    end
    if #cands == 0 then
        return nil, held or why or 'no magma found near the fort (or the survey is older than 0.105.0)'
    end
    for _, c in ipairs(cands) do
        local p, w1 = magma_at(c.m, shop, fb)
        if p and c.b then
            p.source = {magma = c.b.magma, d = c.b.d, opens_cavern = c.b.opens_cavern}
            local big = stage_plan(p)
            if big then p, w1 = nil, big end
        end
        if p then return p end
        why = why or (c.b and (('the %s magma: '):format(tostring(c.b.magma)) .. tostring(w1)) or w1)
    end
    return nil, why or held
end

PLANNERS = {moat = plan_moat, pump = plan_pump, irrigation = plan_irrigation, magma = plan_magma}

---------------------------------------------------------------------------
-- The steps
---------------------------------------------------------------------------

local function dug(t, text)
    if not t then return false end
    if text == 'h' then return t.shape == 'EMPTY' or t.shape == 'RAMP_TOP' end
    if text == 'j' then return t.shape == 'STAIR_DOWN' or t.shape == 'STAIR_UPDOWN' end
    if text == 'u' then return t.shape == 'STAIR_UP' or t.shape == 'STAIR_UPDOWN' end
    if text == 'i' then return t.shape == 'STAIR_UPDOWN' end
    if text == 'z' then return t.shape == 'FLOOR' end
    return t.shape ~= 'WALL'
end

local function by_z(cells)
    local out, zs = {}, {}
    for _, c in ipairs(cells) do
        if not out[c.z] then out[c.z] = {}; table.insert(zs, c.z) end
        table.insert(out[c.z], {x = c.x, y = c.y, text = c.text})
    end
    table.sort(zs, function(a, b) return a > b end)
    return out, zs
end

local function designate_all(cells, mode)
    local g, zs = by_z(cells)
    for _, z in ipairs(zs) do
        if not designate(g[z], z, mode) then return false, z end
    end
    return true
end

-- (0.105.37 fix) the cells not dug yet (a power planned again over its own
-- old shaft designates only what is left)
local function undug(cells)
    local out = {}
    for _, c in ipairs(cells or {}) do if not dug(T(c.x, c.y, c.z), c.text) then table.insert(out, c) end end
    return out
end

local function left_to_dig(cells)
    local n = 0
    for _, c in ipairs(cells or {}) do if not dug(T(c.x, c.y, c.z), c.text) then n = n + 1 end end
    return n
end

-- liquid seen outside the work's tiles, beside its wet tiles (a leak)
local function leak(p)
    local planned = {}
    for _, c in ipairs(p.tiles) do planned[key(c.x, c.y, c.z)] = true end
    local src = p.plug
    for _, c in ipairs(p.wet) do
        for _, d in ipairs(N8) do
            local x, y = c.x + d[1], c.y + d[2]
            if not planned[key(x, y, c.z)] and math.max(math.abs(x - src.x), math.abs(y - src.y)) > 1 then
                local t = T(x, y, c.z)
                if t and t.liquid and not (p.kind == 'moat' and t.outside) then return {x = x, y = y, z = c.z} end
            end
        end
    end
    return nil
end

local function depth_at(c)
    local t = T(c.x, c.y, c.z)
    return t and t.liquid and (t.depth or 0) or 0, t
end

---------------------------------------------------------------------------
-- (0.105.37 E3) W7: power for the pump stack
---------------------------------------------------------------------------
-- The pump stack (W4) is worked by hand. Its power: a water wheel on the
-- river (flowing water under it) or a windmill (the map's wind), joined to
-- the stack by a shaft of vertical axles straight down over the top pump's
-- output tile (DF: a screw pump "accepts and transfers power using either
-- tile of the pump, in all orthogonal directions, including above and
-- below"; the pumps pass power on to each other), and on the surface by
-- horizontal axles and gear assemblies. Begun only when the stack is done
-- (its floodgate, the water's stop, built and tested).
--
-- (0.105.37 fix) The power never joins the fort to the outside or the sky.
-- Gears and axles block nothing, and floors block power between levels (the
-- wiki's Axle page), so every link between levels is an open tile; the seals
-- are machines nothing passes: a screw pump's output tile ("blocks liquid
-- flow and creature movement") and a standing windmill's centre ("does not
-- permit passage"). The shaft and its access stair are a pocket in solid
-- rock from zt + 2 to the ground's level less one: every tile beside them on
-- their levels is rock. At its foot (zt + 1, the fort's level over the top
-- pump) a screw pump's output fills the shaft's column over the top pump's
-- output, so the shaft opens onto two outputs and nothing else; that pump's
-- intake is a nook of the fort (dug and built from the fort's side), over
-- solid rock with nothing to pump. The pocket's floor at zt + 2 stays a rock
-- plug until that pump stands. Its top is roofed by the rock: the switch
-- gear at ztop - 1 under the ground; the windmill's centre over its gear;
-- for a wheel, a second screw pump under the ground (the top seal) whose
-- output lies under the ground's gear D, the power's one opening to the sky.
-- The stair's hatch is built last and locked. Pumped water rises at most to
-- the pump's own level (the water rules, design-notes W1), so none climbs
-- into the shaft; any water seen in it stops the power, shuts the stack's
-- floodgate and holds the work. The shaft's top and stair are kept 2 tiles
-- from any water (dry_near).
--
-- The power's stop: a gear assembly on a lever ("AI pump power") that bears
-- nothing (a wheel or an axle resting on a disengaged gear falls), pulled
-- at once on a flood, water in the shaft or the stack held, and pulled to
-- keep the reservoir between POWER_LOW and POWER_HIGH. A wheel that stops
-- (its river frozen or low) is paused: the power off, the pumps worked by
-- hand, on again when it turns; retired only when it stood still through
-- WHEEL_RETIRE_DAYS of unfrozen river (a full thawed season). Held when the
-- wind is too weak or the power falls short.
--
-- The power check, DF's numbers (the wiki's Power page): a screw pump needs
-- 10 (the two seals too), a gear assembly 5, an axle 1 a tile; a water wheel
-- gives 100 in flowing water (10 of it turning itself), a windmill 40 (20,
-- or 0, in poor wind; the same all the map's life).
POWER_PUMP = 10
POWER_GEAR = 5
POWER_AXLE = 1
POWER_WHEEL = 100
POWER_WHEEL_OWN = 10
POWER_WINDMILL = 40
POWER_SHAFT_MAX = 30    -- levels from the top pump to the surface at most
POWER_RUN_MAX = 30      -- tiles of axle on the surface at most
AXLE_SEG = 10           -- a horizontal axle this long at most (several in a row)
WHEELS_MAX = 3          -- side by side over the river, each on the last's centre
POWER_LOW = 3           -- the reservoir this low: the power on
POWER_HIGH = 5          -- this high: off
WHEEL_DRY_DAYS = 14     -- (unused since 0.105.37 fix: a still wheel is paused, see WHEEL_RETIRE_DAYS)
WHEEL_RETIRE_DAYS = 84  -- (0.105.37 fix) a still wheel over unfrozen water this long (a season): held, retired
WIND_DAYS = 14          -- the windmill still this long: held
POWER_SHORT_DAYS = 14   -- less power than the machine needs this long: held
POWER_PULL_DAYS = 2     -- a pull to switch the power on asked again no sooner

local OWN = {}           -- (0.105.37 fix) the plan being made: the older plan's tiles (own_tiles)

-- open space over flowing river water: a water wheel's tile; the water's depth, or nil
local function wheel_tile(x, y, z)
    local t, b = T(x, y, z), T(x, y, z - 1)
    if not (t and t.shape == 'EMPTY' and not t.liquid and (not t.building or OWN[key(x, y, z)])) then return nil end
    if not (b and b.liquid and not b.magma and (b.material == 'RIVER' or b.material == 'BROOK')) then return nil end
    return b.depth or 0
end

-- no water within r tiles, on the level and the one under it
local function dry_near(x, y, z, r)
    for dz = -1, 0 do
        for dx = -r, r do for dy = -r, r do
            local t = T(x + dx, y + dy, z + dz)
            if t and t.liquid then return false end
        end end
    end
    return true
end

-- the pump stack's top screw pump: its intake tile {x, y, z} and its
-- output tile {x, y} (the plan's `down` marks the intakes)
local function top_pump(pp)
    local best
    for _, b in ipairs(pp.builds or {}) do
        if b.kind == 'ScrewPump' and (not best or b.z > best.z) then best = b end
    end
    if not best or type(pp.down) ~= 'table' then return nil end
    local w, h = tostring(best.text or ''):match('%((%d+)x(%d+)%)')
    w, h = tonumber(w) or 1, tonumber(h) or 1
    local a, b = {x = best.x, y = best.y}, {x = best.x + w - 1, y = best.y + h - 1}
    if pp.down[key(a.x, a.y, best.z)] then return {x = a.x, y = a.y, z = best.z}, b end
    if pp.down[key(b.x, b.y, best.z)] then return {x = b.x, y = b.y, z = best.z}, a end
    return nil
end

-- A screw pump with its intake on tile a and its output on b (orthogonal
-- neighbours): its quickfort key ("pumps from" the intake's side) and its
-- top-left corner.
local function pump_text(a, b)
    if b.x == a.x + 1 then return 'Msh(2x1)', a.x, a.y end
    if b.x == a.x - 1 then return 'Msk(2x1)', b.x, b.y end
    if b.y == a.y + 1 then return 'Msu(1x2)', a.x, a.y end
    return 'Msm(1x2)', b.x, b.y
end

-- (0.105.37 fix) The power's own tiles from an older plan (planned again
-- after a retire): dug, channelled or built by it. Seen as its own, never as
-- "not solid rock": the planner reuses its old shaft and machines.
local function own_tiles(old)
    local own = {}
    if type(old) ~= 'table' then return own end
    for _, list in ipairs({old.dig or {}, old.dig2 or {}, old.dig3 or {}, old.pocket or {}}) do
        for _, c in ipairs(list) do own[key(c.x, c.y, c.z)] = true end
    end
    for _, b in ipairs(old.builds or {}) do
        local w, h = tostring(b.text or ''):match('%((%d+)x(%d+)%)')
        w, h = tonumber(w) or 1, tonumber(h) or 1
        for x = b.x, b.x + w - 1 do for y = b.y, b.y + h - 1 do own[key(x, y, b.z)] = true end end
    end
    if type(old.hatch) == 'table' then own[key(old.hatch.x, old.hatch.y, old.hatch.z)] = true end
    return own
end

local function rock_or_own(x, y, z) return OWN[key(x, y, z)] or rock(T(x, y, z)) end
local function ground_or_own(x, y, z)
    if OWN[key(x, y, z)] or ground(x, y, z) then return true end
    -- (open ground over the old plan's own dug tile: its shaft's roof)
    local t = T(x, y, z)
    return OWN[key(x, y, z - 1)] == true and t ~= nil and t.outside == true and not t.liquid
        and (t.shape == 'FLOOR' or t.shape == 'SHRUB' or t.shape == 'SAPLING' or t.shape == 'PEBBLES')
end

-- The shaft and its access stair: the shaft C (over the top pump's output)
-- and the stair S = C + d, from zt + 2 to ztop - 1, with `extra` tiles: all
-- solid rock, and every tile beside them on their level rock or their own.
-- The pocket joins nothing: not the fort, not the pump stack, not the river.
-- Its floor at zt + 2 is the rock plug over the foot (cut only once the
-- foot's pump stands). {S, list} or nil, why
local function power_pocket(C, zt, ztop, d, extra)
    local S = {x = C.x + d[1], y = C.y + d[2]}
    local list, set = {}, {}
    local function add(x, y, z) table.insert(list, {x = x, y = y, z = z}); set[key(x, y, z)] = true end
    for z = zt + 2, ztop - 1 do add(C.x, C.y, z) end      -- (the shaft first: its reasons said first)
    for z = zt + 2, ztop - 1 do add(S.x, S.y, z) end
    for _, c in ipairs(extra or {}) do add(c.x, c.y, c.z) end
    for _, c in ipairs(list) do
        if not rock_or_own(c.x, c.y, c.z) then
            return nil, ('the shaft\'s stair would cross something other than solid rock at x%d y%d, elevation %d')
                :format(c.x, c.y, ez(c.z))
        end
    end
    for _, c in ipairs(list) do
        for _, n in ipairs(N8) do
            local x, y = c.x + n[1], c.y + n[2]
            if not set[key(x, y, c.z)] and not rock_or_own(x, y, c.z) then
                return nil, ('the shaft would touch something other than solid rock at x%d y%d, elevation %d '
                             .. '(it must join nothing of the fort)'):format(x, y, ez(c.z))
            end
        end
    end
    if not ground_or_own(S.x, S.y, ztop) then
        return nil, ('no dry open ground for the shaft\'s stair at x%d y%d, elevation %d'):format(S.x, S.y, ez(ztop))
    end
    return {S = S, list = list}
end

local WALK_SHAPES = {FLOOR = true, STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true}

-- The foot: a screw pump on the level over the top pump (zt + 1), its
-- output tile C over the top pump's output (both impassable: DF's screw
-- pump output "blocks liquid flow and creature movement"), its intake I0
-- beside it on dug floor over solid rock (nothing under it to pump). It
-- takes the shaft's power down into the stack through the channel at C and
-- seals the shaft from the fort's level and from the stack: nothing walks,
-- flies or flows between them. Dug and built from the fort's side (a fort
-- tile beside I0). {I0, text, x, y} or nil, why
local function power_foot(pp, C, zt)
    local z = zt + 1
    if not rock_or_own(C.x, C.y, z) then
        return nil, ('the foot of the shaft over the top pump is not solid rock at x%d y%d, elevation %d')
            :format(C.x, C.y, ez(z))
    end
    local stack = {}
    for _, c in ipairs(pp.dig or {}) do stack[key(c.x, c.y, c.z)] = true end
    local why
    for _, f in ipairs(N4) do
        local I = {x = C.x + f[1], y = C.y + f[2]}
        local ok = not stack[key(I.x, I.y, z)] and rock_or_own(I.x, I.y, z) and rock(T(I.x, I.y, z - 1))
        if not ok then
            why = why or 'no solid rock beside the shaft\'s foot for its pump (with rock under its intake)'
        else
            -- nothing beside the foot open to the sky or holding water; a fort
            -- tile beside the intake to dig and build it from
            local reach = false
            for _, c in ipairs({C, I}) do
                for _, n in ipairs(N8) do
                    local x, y = c.x + n[1], c.y + n[2]
                    local t = T(x, y, z)
                    if t and (t.liquid or t.outside or t.feature or t.aquifer) then
                        ok = false
                        why = why or ('the shaft\'s foot would be beside water or open air at x%d y%d, elevation %d')
                            :format(x, y, ez(z))
                    end
                    if c == I and not (x == C.x and y == C.y) and t and WALK_SHAPES[t.shape] and not t.outside
                            and not t.liquid then
                        reach = true
                    end
                end
            end
            if ok and not reach then
                ok = false
                why = why or 'no fort floor beside the shaft\'s foot to dig and build its pump from'
            end
            if ok then
                local text, x, y = pump_text(I, C)
                return {I = I, text = text, x = x, y = y}
            end
        end
    end
    return nil, why
end

-- the digs every power plan shares: the stair and the shaft dug from the
-- surface down to zt + 2 (the plug: its floor kept), the foot dug from the
-- fort's side (its pump's intake floor, the channel over the top pump's
-- output); then the shaft's floors channelled down to zt + 3 (dig2); the
-- plug cut (dig3) only once the foot's pump stands
local function power_digs(p, C, S, zt, ztop, foot, chan_top)
    for z = zt + 2, ztop - 1 do
        table.insert(p.dig, {x = S.x, y = S.y, z = z, text = z == zt + 2 and 'u' or 'i'})
        table.insert(p.dig, {x = C.x, y = C.y, z = z, text = 'd'})
    end
    table.insert(p.dig, {x = S.x, y = S.y, z = ztop, text = 'j'})
    table.insert(p.dig, {x = foot.I.x, y = foot.I.y, z = zt + 1, text = 'd'})
    table.insert(p.dig, {x = C.x, y = C.y, z = zt + 1, text = 'h'})
    for z = zt + 3, chan_top do table.insert(p.dig2, {x = C.x, y = C.y, z = z, text = 'h'}) end
    p.dig3 = {{x = C.x, y = C.y, z = zt + 2, text = 'h'}}
    -- the foot's tiles (watched for water with the pocket)
    table.insert(p.pocket, {x = C.x, y = C.y, z = zt + 1})
    table.insert(p.pocket, {x = foot.I.x, y = foot.I.y, z = zt + 1})
end

local function power_need(pumps, gears, axles)
    return pumps * POWER_PUMP + gears * POWER_GEAR + axles * POWER_AXLE
end

-- the horizontal axles between two gears on one line (a and b excluded), in
-- pieces of AXLE_SEG at most
local function axle_run(a, b, z, out)
    local dx, dy = (b.x > a.x and 1 or b.x < a.x and -1 or 0), (b.y > a.y and 1 or b.y < a.y and -1 or 0)
    local tiles = {}
    local x, y = a.x + dx, a.y + dy
    while not (x == b.x and y == b.y) do table.insert(tiles, {x = x, y = y}); x, y = x + dx, y + dy end
    local i = 1
    while i <= #tiles do
        local j = math.min(#tiles, i + AXLE_SEG - 1)
        local n = j - i + 1
        local x1, y1 = math.min(tiles[i].x, tiles[j].x), math.min(tiles[i].y, tiles[j].y)
        table.insert(out, {x = x1, y = y1, z = z, kind = 'AxleHorizontal',
                           text = dx ~= 0 and ('Mh(%dx1)'):format(n) or ('Mhs(1x%d)'):format(n)})
        i = j + 1
    end
    return #tiles
end

local function power_lever(pp, old)
    -- (planned again) the old lever where it stands
    if type(old) == 'table' and type(old.lever) == 'table' and building(old.lever.x, old.lever.y, old.lever.z, 'Trap') then
        return {x = old.lever.x, y = old.lever.y, z = old.lever.z, name = 'AI pump power'}
    end
    if type(pp.lever) ~= 'table' then return nil end
    local lv = lever_spot(pp.lever.x, pp.lever.y, pp.lever.z, {[key(pp.lever.x, pp.lever.y, pp.lever.z)] = true})
    if lv then lv.name = 'AI pump power' end
    return lv
end

-- the foot's pump, the shaft's axles and its switch (a gear at ztop - 1,
-- under the ground: the shaft stays roofed); the switch's index
local function shaft_builds(p, add, C, zt, ztop, foot)
    local prev = add({x = foot.x, y = foot.y, z = zt + 1, text = foot.text, kind = 'ScrewPump', seal = 'foot'})
    p.foot = prev
    local plug = true
    for z = zt + 2, ztop - 2 do
        prev = add({x = C.x, y = C.y, z = z, text = 'Mv', kind = 'AxleVertical', after = prev, plug = plug or nil})
        plug = false
    end
    p.switch = add({x = C.x, y = C.y, z = ztop - 1, text = 'Mg', kind = 'GearAssembly', after = prev,
                    plug = plug or nil})
    return p.switch
end

-- A water wheel (or two or three side by side) over the river one level
-- under the shaft's ground, a gear on the bank beside its centre, gears and
-- axles along the ground to a gear D over the top seal: a screw pump under
-- the ground (its output under D, its intake beside the switch) that takes
-- the power down and is the shaft's roof where D's channel opens (nothing
-- walks, flies or flows through a pump's output). The axles and gears on the
-- ground stay outside; the shaft is roofed by rock everywhere else.
local function power_wheel(pp, C, zt, ztop, pumps, w, foot)
    local river
    for _, b in ipairs(w and w.bodies or {}) do
        if b.kind == 'river' and (tonumber(b.tiles) or 0) > 0 then river = b end
    end
    -- (0.105.38) and the far ones (tried when none near is within reach)
    local far = far_sources(w, function(b) return b.flow == 'flowing' end)
    if not river and #far == 0 then return nil, 'no river near the fort for a water wheel' end
    local best, why
    for _, e in ipairs(N4) do
        for _, d in ipairs(N4) do
            if d[1] * e[1] + d[2] * e[2] == 0 then
                local I1 = {x = C.x + e[1], y = C.y + e[2]}
                local U = {x = C.x + 2 * e[1], y = C.y + 2 * e[2]}
                local pk, pwhy = power_pocket(C, zt, ztop, d, {{x = I1.x, y = I1.y, z = ztop - 1}, {x = U.x, y = U.y, z = ztop - 1}})
                if not pk then why = why or pwhy goto nexte end
                if not (rock(T(I1.x, I1.y, ztop - 2)) and rock(T(U.x, U.y, ztop - 2))) then
                    why = why or 'no solid rock under the shaft\'s top seal'
                    goto nexte
                end
                if not ground_or_own(U.x, U.y, ztop) then
                    why = why or ('no dry open ground over the shaft\'s top seal at x%d y%d'):format(U.x, U.y)
                    goto nexte
                end
                do
                    local S = pk.S
                    if not (dry_near(S.x, S.y, ztop, 2) and dry_near(U.x, U.y, ztop, 2) and dry_near(C.x, C.y, ztop, 2)) then
                        why = why or 'the shaft\'s top would be within 2 tiles of water'
                        goto nexte
                    end
                    local function walk(x, y)
                        return ground_or_own(x, y, ztop) and not (x == S.x and y == S.y)
                    end
                    local D = U
                    -- (0.105.38) one wheel's centre tried: the axle's run to it this long at most
                    local function try_c(c, runmax, far)
                        if wheel_tile(c.x, c.y, ztop) then
                            for _, u in ipairs({{1, 0}, {0, 1}}) do
                                local v = {u[2], u[1]}
                                for _, s in ipairs({1, -1}) do
                                    local G0 = {x = c.x + v[1] * s, y = c.y + v[2] * s}
                                    if walk(G0.x, G0.y) and not (G0.x == D.x and G0.y == D.y) then
                                        local path = l_path(D, G0, walk)
                                        if path and #path <= runmax then
                                            table.insert(path, G0)
                                            -- the gears: D, the corner, the bank
                                            local gears = {1}
                                            for i = 2, #path - 1 do
                                                local a, b2, n = path[i - 1], path[i], path[i + 1]
                                                if (b2.x - a.x) ~= (n.x - b2.x) or (b2.y - a.y) ~= (n.y - b2.y) then
                                                    table.insert(gears, i)
                                                end
                                            end
                                            table.insert(gears, #path)
                                            local axles = {}
                                            local h = 0
                                            for i = 2, #gears do h = h + axle_run(path[gears[i - 1]], path[gears[i]], ztop, axles) end
                                            local vert = ztop - zt - 3
                                            -- the stack's pumps and the two seals; the switch and the ground's gears
                                            local need = power_need(pumps + 2, #gears + 1, vert + h)
                                            local n = (need + POWER_WHEEL - POWER_WHEEL_OWN - 1) // (POWER_WHEEL - POWER_WHEEL_OWN)
                                            n = math.max(1, n)
                                            local ok = n <= WHEELS_MAX
                                            local wheels = {}
                                            for k = 0, (ok and n or 0) - 1 do
                                                local ck = {x = c.x - v[1] * s * k, y = c.y - v[2] * s * k}
                                                local deep = false
                                                for j = -1, 1 do
                                                    local dd = wheel_tile(ck.x + u[1] * j, ck.y + u[2] * j, ztop)
                                                    if not dd then ok = false end
                                                    if dd and dd >= 4 then deep = true end
                                                end
                                                if not deep then ok = false end
                                                table.insert(wheels, ck)
                                            end
                                            if not ok and n > WHEELS_MAX then
                                                why = why or ('the pumps need %d power, more than %d water wheels give (%d each)')
                                                    :format(need, WHEELS_MAX, POWER_WHEEL - POWER_WHEEL_OWN)
                                            end
                                            local score = n * 1000 + #path
                                            if ok and (not best or score < best.score) then
                                                best = {score = score, S = S, pocket = pk.list, path = path, gears = gears,
                                                        axles = axles, wheels = wheels, u = u, need = need + n * POWER_WHEEL_OWN,
                                                        have = n * POWER_WHEEL, n = n, vert = vert, h = h, I1 = I1, U = U,
                                                        far = far}
                                            end
                                        end
                                    end
                                end
                            end
                        end
                    end
                    for dx = -POWER_RUN_MAX, POWER_RUN_MAX do for dy = -POWER_RUN_MAX, POWER_RUN_MAX do
                        try_c({x = D.x + dx, y = D.y + dy}, POWER_RUN_MAX)
                    end end
                    -- (0.105.38) no river within reach of the shaft's top: the far
                    -- ones the survey found, the cheapest first (a long run of axles)
                    if not best then
                        for _, fr in ipairs(far) do
                            local fn = fr.nearest
                            if fn.z == ztop - 1 then
                                for dx = -6, 6 do for dy = -6, 6 do
                                    try_c({x = fn.x + dx, y = fn.y + dy}, far_cap(w), true)
                                end end
                            end
                        end
                    end
                end
            end
            ::nexte::
        end
    end
    if not best then
        return nil, why or ('no flowing river water (4/7 deep) under open space within %d tiles of the shaft\'s top, '
                            .. 'with dry ground to join them'):format(POWER_RUN_MAX)
    end
    local p = {kind = 'power', v = 2, source = 'wheel', dig = {}, dig2 = {}, builds = {}, pocket = best.pocket,
               far = best.far and {d = #best.path, kind = 'axles'} or nil,
               shaft = {x = C.x, y = C.y, z1 = zt + 1, z2 = ztop - 1}, need = best.need, have = best.have,
               pumps = pumps, wheels = best.n, sources = {}, reservoir = pp.reservoir, test = pp.test}
    power_digs(p, C, best.S, zt, ztop, foot, ztop - 1)
    table.insert(p.dig, {x = best.I1.x, y = best.I1.y, z = ztop - 1, text = 'd'})
    table.insert(p.dig, {x = best.U.x, y = best.U.y, z = ztop - 1, text = 'd'})
    table.insert(p.dig2, {x = best.U.x, y = best.U.y, z = ztop, text = 'h'})       -- D: over the top seal
    local function add(b) table.insert(p.builds, b) return #p.builds end
    shaft_builds(p, add, C, zt, ztop, foot)
    local st, sx, sy = pump_text(best.I1, best.U)
    local seal = add({x = sx, y = sy, z = ztop - 1, text = st, kind = 'ScrewPump', seal = 'top'})
    p.top = seal
    local dgear = add({x = best.U.x, y = best.U.y, z = ztop, text = 'Mg', kind = 'GearAssembly', after = seal})
    for i = 2, #best.gears do
        local g = best.path[best.gears[i]]
        add({x = g.x, y = g.y, z = ztop, text = 'Mg', kind = 'GearAssembly'})
    end
    local bank = #p.builds
    if #best.gears < 2 then bank = dgear end
    for _, a in ipairs(best.axles) do add(a) end
    local prev = bank
    for _, ck in ipairs(best.wheels) do
        local ew = best.u[1] ~= 0
        prev = add({x = ew and ck.x - 1 or ck.x, y = ew and ck.y or ck.y - 1, z = ztop, cx = ck.x, cy = ck.y,
                    text = ew and 'Mws(3x1)' or 'Mw(1x3)', kind = 'WaterWheel', after = prev})
        table.insert(p.sources, prev)
    end
    p.hatch = {x = best.S.x, y = best.S.y, z = ztop, text = 'H', kind = 'Hatch', lock = true}
    p.lever = power_lever(pp, pp.old_)
    if not p.lever then return nil, 'no free floor for the power\'s lever' end
    if p.far then
        local big = job_too_big(p)             -- (0.105.38) a far wheel's run within the job cap
        if big then return nil, big end
    end
    return p
end

-- A windmill on open ground beside the shaft: its centre over a gear under
-- the ground, an axle to the shaft's top gear (the switch, under the ground:
-- the shaft stays roofed; the windmill's centre is its roof over the gear,
-- DF: "this does not permit passage as long as the windmill stands").
local function power_windmill(pp, C, zt, ztop, pumps, foot)
    local why
    for _, d in ipairs(N4) do
        for _, e in ipairs(N4) do
            if d[1] * e[1] + d[2] * e[2] == 0 then
                local E = {x = C.x + e[1], y = C.y + e[2]}
                local M = {x = C.x + 2 * e[1], y = C.y + 2 * e[2]}
                local pk, pwhy = power_pocket(C, zt, ztop, d, {{x = E.x, y = E.y, z = ztop - 1}, {x = M.x, y = M.y, z = ztop - 1}})
                local ok = pk ~= nil
                if not ok then why = why or pwhy end
                if ok then
                    for dx = -1, 1 do for dy = -1, 1 do
                        if not ground_or_own(M.x + dx, M.y + dy, ztop) then ok = false end
                    end end
                    if not ok then why = why or ('no 3x3 of open ground under the sky for the windmill at x%d y%d'):format(M.x, M.y) end
                end
                if ok and not (dry_near(pk.S.x, pk.S.y, ztop, 2) and dry_near(M.x, M.y, ztop, 2)) then
                    ok = false
                    why = why or 'the windmill or the shaft\'s stair would be within 2 tiles of water'
                end
                if ok then
                    local vert = ztop - zt - 3
                    -- the stack's pumps and the foot's; the switch and the windmill's gear
                    local need = power_need(pumps + 1, 2, vert + 1)
                    if need > POWER_WINDMILL then
                        return nil, ('the pumps need %d power, more than a windmill gives (%d at most)'):format(need, POWER_WINDMILL)
                    end
                    local p = {kind = 'power', v = 2, source = 'windmill', dig = {}, dig2 = {}, builds = {}, pocket = pk.list,
                               shaft = {x = C.x, y = C.y, z1 = zt + 1, z2 = ztop - 1}, need = need, have = POWER_WINDMILL,
                               pumps = pumps, sources = {}, reservoir = pp.reservoir, test = pp.test}
                    power_digs(p, C, pk.S, zt, ztop, foot, ztop - 1)
                    table.insert(p.dig, {x = E.x, y = E.y, z = ztop - 1, text = 'd'})
                    table.insert(p.dig, {x = M.x, y = M.y, z = ztop - 1, text = 'd'})
                    table.insert(p.dig2, {x = M.x, y = M.y, z = ztop, text = 'h'})     -- the windmill's centre
                    local function add(b) table.insert(p.builds, b) return #p.builds end
                    shaft_builds(p, add, C, zt, ztop, foot)
                    add({x = E.x, y = E.y, z = ztop - 1, text = e[1] ~= 0 and 'Mh(1x1)' or 'Mhs(1x1)', kind = 'AxleHorizontal'})
                    local wm = add({x = M.x, y = M.y, z = ztop - 1, text = 'Mg', kind = 'GearAssembly'})
                    table.insert(p.sources, add({x = M.x, y = M.y, z = ztop, text = 'windmill', kind = 'Windmill', after = wm}))
                    p.hatch = {x = pk.S.x, y = pk.S.y, z = ztop, text = 'H', kind = 'Hatch', lock = true}
                    p.lever = power_lever(pp, pp.old_)
                    if not p.lever then return nil, 'no free floor for the power\'s lever' end
                    return p
                end
            end
        end
    end
    return nil, why or 'no site for a windmill over the shaft'
end

-- The power for a done pump stack (pw, its work). src: 'wheel', 'windmill'
-- or nil (a wheel if it can, else a windmill). old: the power's earlier plan
-- (planned again after a retire: its shaft and machines are its own, reused
-- where they stand; its own source tried first). The plan, or nil, why.
--
-- (0.105.37 fix) The shaft never joins the fort to the outside or the sky:
-- it runs over the top pump's output and is sealed at both ends by screw
-- pumps' outputs (impassable to creatures and water) or the windmill's
-- centre: the foot's pump on the fort's lowest level, the top seal under the
-- wheel's gear on the ground. Every tile beside the pocket on its levels is
-- rock; its floor at zt + 2 stays a rock plug until the foot's pump stands.
-- Gears and axles block nothing, so nothing of the power opens a way.
function plan_power(pw, src, old)
    local pp = type(pw) == 'table' and pw.plan
    if type(pp) ~= 'table' or pp.kind ~= 'pump' then return nil, 'no pump stack to power' end
    local top, out = top_pump(pp)
    if not top then return nil, 'the pump stack\'s top screw pump is not in its plan' end
    local C, zt = {x = out.x, y = out.y}, top.z
    local pumps = 0
    for _, b in ipairs(pp.builds or {}) do if b.kind == 'ScrewPump' then pumps = pumps + 1 end end
    old = (type(old) == 'table' and old.v == 2) and old or nil
    OWN = own_tiles(old)
    local function done(...) OWN = {} return ... end
    -- the shaft: solid rock straight up from over the top pump's output to the surface
    local ztop
    for z = zt + 1, zt + POWER_SHAFT_MAX + 1 do
        if not rock_or_own(C.x, C.y, z) then
            if ground_or_own(C.x, C.y, z) then ztop = z break end
            return done(nil, ('the shaft over the top pump would cross something other than solid rock at x%d y%d, '
                              .. 'elevation %d (a room, water, a cavern, the aquifer)'):format(C.x, C.y, ez(z)))
        end
    end
    if not ztop then return done(nil, ('the surface is more than %d levels over the top pump'):format(POWER_SHAFT_MAX)) end
    if ztop < zt + 3 then return done(nil, 'too little rock over the top pump for the shaft\'s seals and gears') end
    local foot, fwhy = power_foot(pp, C, zt)
    if not foot then return done(nil, fwhy) end
    pp = setmetatable({old_ = old}, {__index = pp})
    local kinds = (src == 'wheel' or src == 'windmill') and {src} or {'wheel', 'windmill'}
    if not src and old and old.source == 'windmill' then kinds = {'windmill', 'wheel'} end
    local why
    for _, k in ipairs(kinds) do
        local p, w2
        if k == 'wheel' then p, w2 = power_wheel(pp, C, zt, ztop, pumps, water_survey(), foot)
        else p, w2 = power_windmill(pp, C, zt, ztop, pumps, foot) end
        if p then return done(p) end
        why = why and (why .. '; ' .. w2) or w2
    end
    return done(nil, why)
end

-- One step of the pump stack's power. opts: {dry_run, shut, retire, reopen, why, source}
function power_step(opts)
    opts = opts or {}
    local st = load_state()
    local id = 'power'
    local wk = st.works[id]
    local dry = opts.dry_run == true
    local function save() if not dry then st.works[id] = wk; save_state(st) end end
    local function wait(why) return {ok = false, rejected = true, waiting = true, stage = wk.stage, error = why} end
    local function advance(stage, extra)
        if not dry then wk.stage = stage; wk.since = now(); save() end
        local out = {ok = true, kind = 'power', stage = stage, dry_run = dry or nil}
        for k, v in pairs(extra or {}) do out[k] = v end
        return out
    end
    local function hold(why)
        if not dry then wk.stage = 'held'; wk.why = why; save() end
        return {ok = false, rejected = true, stage = 'held', error = why}
    end
    local function bld(b) return building(b.cx or b.x, b.cy or b.y, b.z, b.kind) end
    local function switch_of()
        local p = wk and wk.plan
        local b = p and p.switch and p.builds[p.switch]
        return b and bld(b) or nil
    end
    local function engaged(g)
        local e = g and gear_engaged(g.id)
        if e == nil then return wk.engaged ~= false end
        return e
    end
    -- the power off at once (a pull on its way called off); true: it was on
    local function stop_power()
        if dry or not wk or not wk.lever_id then return false end
        local g = switch_of()
        if not g or not g.built or not engaged(g) then return false end
        cancel_pulls(wk.lever_id)
        pull(wk.lever_id, true)
        wk.engaged = false
        return true
    end
    local function shaft_wet(p)
        for _, c in ipairs(p.pocket or {}) do
            local d = depth_at(c)
            if d > 0 then return c, d end
        end
        return nil
    end
    local function pump_shut(why)
        if dry then return end
        pcall(step, 'pump', {shut = true, why = why})
        st = load_state()        -- (the pump's step saved its own work)
    end

    if opts.shut or opts.retire then
        if not wk then return {ok = false, rejected = true, error = 'no power work to shut'} end
        if dry then return {ok = true, dry_run = true, stage = wk.stage} end
        stop_power()
        if opts.retire then
            wk.stage = 'retired'; wk.why = opts.why or 'retired'
            wk.shut, wk.shut_at = nil, nil
            st.retired_n = type(st.retired_n) == 'table' and st.retired_n or {}
            st.retired_n[id] = (math.tointeger(st.retired_n[id]) or 0) + 1
            st.refused[id] = {tick = now(), why = 'retired: ' .. wk.why, retired = st.retired_n[id]}
        else
            wk.shut = opts.why or 'shut'
            wk.shut_at = now()
        end
        save()
        return {ok = true, stage = wk.stage, shut = true}
    end

    if not wk or wk.stage == 'retired' then
        local n_ret = type(st.retired_n) == 'table' and math.tointeger(st.retired_n[id]) or 0
        if n_ret >= RETIRE_MAX then
            local why0 = ('retired %d times already: not begun again'):format(n_ret)
            if not dry then
                local old = type(st.refused[id]) == 'table' and st.refused[id] or {}
                st.refused[id] = {tick = now(), why = old.why or why0, retired = n_ret}
                save_state(st)
            end
            return {ok = false, rejected = true, retired = n_ret, error = why0}
        end
        local pw = st.works.pump
        local plan, why
        if type(pw) ~= 'table' or pw.stage ~= 'done' then
            why = 'the pump stack is not done yet (its floodgate built and its reservoir filled once): no power for it'
        elseif pw.shut then
            why = 'the pump stack\'s floodgate is shut: no power for it now'
        else
            -- (0.105.37 fix) planned again after a retire: its own old shaft and machines reused
            plan, why = plan_power(pw, opts.source, wk and wk.plan)
        end
        if not plan then
            if not dry then st.refused[id] = {tick = now(), why = why}; save_state(st) end
            return {ok = false, rejected = true, error = why}
        end
        if dry then return {ok = true, dry_run = true, stage = 'planned', plan = plan} end
        st.refused[id] = nil
        wk = {kind = 'power', plan = plan}
        return advance('planned', {source = plan.source, need = plan.need, have = plan.have})
    end
    local p = wk.plan
    if wk.stage == 'held' then return {ok = false, rejected = true, stage = 'held', error = wk.why} end
    if type(p) ~= 'table' or p.v ~= 2 then
        -- (0.105.37 fix) an older plan's shaft could open onto the fort: stopped and held (retired, planned afresh)
        if dry then return {ok = true, dry_run = true, stage = 'held'} end
        stop_power()
        return hold('planned before the shaft was sealed at both ends: the power stopped, the AI plans it again')
    end

    if wk.shut then
        local again = opts.reopen == true or (type(opts.why) == 'string' and opts.why:match('^reopen') ~= nil)
        if not again then return wait(('the power is off (%s): waiting to be switched on again'):format(wk.shut)) end
        if now() - (wk.shut_at or 0) < REOPEN_AFTER_DAYS * DAY then
            return wait(('the power was switched off (%s) under %d days ago: not on yet'):format(wk.shut, REOPEN_AFTER_DAYS))
        end
        if dry then return {ok = true, dry_run = true, stage = wk.stage, reopen = true} end
        wk.shut, wk.shut_at = nil, nil      -- (switched on by the running step when the reservoir is low)
        save()
        return {ok = true, stage = wk.stage, reopened = true}
    end

    -- water in the shaft or its stair: stopped, the stack's floodgate shut, held
    local wc, wd = shaft_wet(p)
    if wc and wk.stage ~= 'planned' then
        if dry then return {ok = true, dry_run = true, stage = 'held'} end
        stop_power()
        pump_shut('water in the power shaft')
        return hold(('water (%d/7) in the power shaft at x%d y%d, elevation %d: the power stopped and the pump '
                     .. 'stack\'s floodgate shut'):format(wd, wc.x, wc.y, ez(wc.z)))
    end

    if wk.stage == 'planned' then
        if dry then return {ok = true, dry_run = true, stage = 'digging'} end
        local ok, z = designate_all(undug(p.dig), 'dig')
        if not ok then return {ok = false, error = ('the game would not designate the shaft (elevation %d)'):format(ez(z))} end
        return advance('digging')
    end
    if wk.stage == 'digging' then
        local n = left_to_dig(p.dig)
        if n > 0 then return wait(('%d tile(s) of the shaft and its stair left to dig'):format(n)) end
        if not wk.dig2 and #undug(p.dig2) > 0 then
            if dry then return {ok = true, dry_run = true, stage = 'digging'} end
            if not designate_all(undug(p.dig2), 'dig') then return {ok = false, error = 'the game would not designate the shaft\'s channels'} end
            wk.dig2 = true
            save()
            return wait('the shaft\'s floors are being channelled')
        end
        if not dry then wk.dig2 = true end
        n = left_to_dig(p.dig2)
        if n > 0 then return wait(('%d of the shaft\'s floors left to channel'):format(n)) end
        -- (0.105.37 fix) the plug over the foot (dig3) waits for the foot's pump: cut in the building stage
        if dry then return {ok = true, dry_run = true, stage = 'building'} end
        if not building(p.lever.x, p.lever.y, p.lever.z, 'Trap') and not designate_all({{x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}}, 'build') then
            return {ok = false, error = 'the game would not place the power\'s lever'}
        end
        wk.placed = {}
        return advance('building')
    end
    if wk.stage == 'building' then
        -- placed a wave at a time: a piece over open space only once what bears it is built
        local placed = type(wk.placed) == 'table' and wk.placed or {}
        local left, put = {}, 0
        -- (0.105.37 fix) the rock plug over the foot cut once the foot's pump
        -- stands (the shaft then opens onto its output, nothing else)
        local foot = p.foot and p.builds[p.foot]
        local fb = foot and bld(foot)
        if not wk.dig3 and fb and fb.built and not dry then
            if not designate_all(undug(p.dig3), 'dig') then return {ok = false, error = 'the game would not designate the plug over the shaft\'s foot'} end
            wk.dig3 = true
        end
        local plug_cut = wk.dig3 and left_to_dig(p.dig3) == 0
        for i, b in ipairs(p.builds) do
            local have = bld(b)
            if not (have and have.built) then table.insert(left, b.kind) end
            local pk = tostring(i)
            local again = placed[pk] and not have and now() - (tonumber(placed[pk]) or 0) > 2 * DAY
            if not have and (not placed[pk] or again) then
                local under = b.after and p.builds[b.after]
                local bears = not under or (function() local u = bld(under) return u ~= nil and u.built end)()
                if b.plug and not plug_cut then bears = false end
                if bears and not dry then
                    local ok
                    if b.kind == 'Windmill' then ok = place_windmill(b.x, b.y, b.z)
                    else ok = designate({{x = b.x, y = b.y, text = b.text}}, b.z, 'build') end
                    if ok then placed[pk] = now(); put = put + 1 end
                end
            end
        end
        wk.placed = placed
        if #left > 0 then
            save()
            return wait(('being built: %d piece(s) (%s)'):format(#left, table.concat(left, ', ', 1, math.min(#left, 4))))
        end
        local l = building(p.lever.x, p.lever.y, p.lever.z, 'Trap')
        if not l then
            if not dry then designate_all({{x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}}, 'build') end
            return wait('the power\'s lever is placed again')
        end
        if not l.built then return wait('being built: the power\'s lever') end
        -- the stair's hatch last (the dwarves came down it), then locked
        local h = building(p.hatch.x, p.hatch.y, p.hatch.z, 'Hatch')
        if not h then
            if dry then return {ok = true, dry_run = true, stage = 'building'} end
            designate_all({p.hatch}, 'build')
            save()
            return wait('the hatch over the shaft\'s stair is placed')
        end
        if not h.built then return wait('being built: the hatch over the shaft\'s stair') end
        if dry then return {ok = true, dry_run = true, stage = 'linking'} end
        lock_hatch(h.id)
        set_name(l.id, p.lever.name)
        local g = switch_of()
        local r = link(l.id, g.id)
        if not r.ok then return r end
        wk.lever_id, wk.gate_id = l.id, g.id
        return advance('linking')
    end
    if wk.stage == 'linking' then
        if not is_linked(wk.lever_id, wk.gate_id) then
            if link_pending(wk.lever_id) or dry then return wait('the lever is being linked to the power\'s gear') end
            wk.relinks = (wk.relinks or 0) + 1
            if wk.relinks > 3 then return hold('the lever\'s link to the power\'s gear was lost 3 times: the AI retires it') end
            local r = link(wk.lever_id, wk.gate_id)
            save()
            if not r.ok then return r end
            return wait('the link was lost: asked for again')
        end
        if dry then return {ok = true, dry_run = true, stage = 'running'} end
        wk.engaged = true
        return advance('running')
    end
    if wk.stage == 'running' then
        local pw = st.works.pump
        if type(pw) ~= 'table' or pw.stage == 'retired' or pw.stage == 'held' then
            if dry then return {ok = true, dry_run = true, stage = 'held'} end
            stop_power()
            return hold(('the pump stack is %s: its power stopped'):format(type(pw) == 'table' and pw.stage or 'gone'))
        end
        local g = switch_of()
        if not g then
            if dry then return {ok = true, dry_run = true, stage = 'held'} end
            return hold('the power\'s gear is gone: the AI retires it')
        end
        if pw.shut then
            if stop_power() then save() end
            return wait(('the pump stack\'s floodgate is shut (%s): its power off meanwhile'):format(pw.shut))
        end
        -- the source turning
        local turning, known = false, false
        for _, i in ipairs(p.sources or {}) do
            local b = bld(p.builds[i])
            local t
            if b then
                if p.source == 'wheel' then t = wheel_turning(b.id) else t = windmill_turning(b.id) end
            end
            if t ~= nil then known = true end
            if t then turning = true end
        end
        local function stack_manual(on)
            if dry then return end
            for _, b in ipairs(pw.plan and pw.plan.builds or {}) do
                if b.kind == 'ScrewPump' then
                    local bb = building(b.x, b.y, b.z, 'ScrewPump')
                    if bb and bb.built then set_pump_manual(bb.id, on) end
                end
            end
        end
        if known and not turning and p.source == 'wheel' then
            -- (0.105.37 fix) a still wheel (its river frozen or low) is paused, not
            -- retired: the power off, the stack's pumps worked by hand meanwhile, on
            -- again when it turns. Retired only after WHEEL_RETIRE_DAYS still over
            -- unfrozen water (a full thawed season); frozen days don't count.
            local frozen, low = false, false
            for _, i in ipairs(p.sources or {}) do
                local b = p.builds[i]
                local t = T(b.cx or b.x, b.cy or b.y, b.z - 1)
                if t and (t.material == 'FROZEN_LIQUID' or t.frozen) then frozen = true
                elseif not (t and t.liquid) or (t.depth or 0) < 4 then low = true end
            end
            if not dry then
                wk.still_from = wk.still_from or now()
                local last = tonumber(wk.still_seen) or now()
                if not frozen then wk.dry_thawed = (tonumber(wk.dry_thawed) or 0) + math.max(0, now() - last) end
                wk.still_seen = now()
            end
            if (tonumber(wk.dry_thawed) or 0) > WHEEL_RETIRE_DAYS * DAY then
                if dry then return {ok = true, dry_run = true, stage = 'held'} end
                stop_power()
                stack_manual(true)
                return hold(('the water wheel has stood still through %d days of unfrozen river (the river dry or '
                             .. 'still under it): the power stopped, the pumps worked by hand, the AI retires it')
                            :format(WHEEL_RETIRE_DAYS))
            end
            local why = frozen and 'its river frozen' or low and 'its river too low' or 'the river still under it'
            if not dry then
                if stop_power() then wk.pull_at = nil end
                stack_manual(true)
                wk.paused = why
                save()
            end
            return wait(('paused: the water wheel stands still (%s): the power off, the pumps worked by hand until it '
                         .. 'turns again'):format(why))
        elseif known and not turning then
            if not dry and not wk.still_from then wk.still_from = now() end
            if now() - (wk.still_from or now()) > WIND_DAYS * DAY then
                if dry then return {ok = true, dry_run = true, stage = 'held'} end
                stop_power()
                return hold(('the windmill has not turned in %d days (no wind on this map): the power stopped, '
                             .. 'the AI retires it'):format(WIND_DAYS))
            end
        elseif not dry then
            wk.still_from, wk.still_seen, wk.dry_thawed = nil, nil, nil
            if wk.paused then wk.paused, wk.resumed = nil, now() end    -- (turning again: the reservoir rule below)
        end
        -- the power check: the machine's power against what it needs
        local on = engaged(g)
        local mp = machine_power(g.id)
        if mp and not dry then wk.power, wk.power_need = mp.cur, mp.need end
        if on and mp and mp.cur < mp.need then
            if not dry and not wk.short_from then wk.short_from = now() end
            if now() - (wk.short_from or now()) > POWER_SHORT_DAYS * DAY then
                if dry then return {ok = true, dry_run = true, stage = 'held'} end
                stop_power()
                return hold(('the machine has %d power for the %d it needs, for %d days: the power stopped, the AI '
                             .. 'retires it'):format(mp.cur, mp.need, POWER_SHORT_DAYS))
            end
        elseif not dry then
            wk.short_from = nil
        end
        -- the reservoir kept between POWER_LOW and POWER_HIGH
        local d = depth_at(p.test or p.reservoir or {x = 0, y = 0, z = 0})
        if not dry then wk.depth = d end
        local did
        if on and d >= POWER_HIGH then
            if not dry then stop_power() end
            did, on = 'switched off', false
        elseif not on and d <= POWER_LOW and now() - (wk.pull_at or -math.huge) > POWER_PULL_DAYS * DAY then
            if not dry then
                pull(wk.lever_id, false)
                wk.pull_at = now()
                wk.engaged = true
            end
            did, on = 'switched on', true
        end
        -- (no dwarf needed at a powered pump)
        stack_manual(false)
        save()
        return wait(('running: the reservoir %d/7, the power %s%s%s'):format(d, on and 'on' or 'off',
            mp and (' (%d for %d needed)'):format(mp.cur, mp.need) or '', did and (': ' .. did) or ''))
    end
    return {ok = false, rejected = true, error = 'unknown stage ' .. tostring(wk.stage)}
end

-- One step of the work of `kind`. opts: {dry_run, shut, retire, shop, plain}
function step(kind, opts)
    opts = opts or {}
    FAR = {reach = opts.far_reach, job_max = opts.job_max, segment = opts.segment}      -- (0.105.38)
    if not KINDS[kind] then return {ok = false, rejected = true, error = 'water_work: unknown kind ' .. tostring(kind)} end
    if kind == 'power' then return power_step(opts) end      -- (0.105.37 E3) its own steps (no floodgate of its own)
    local st = load_state()
    local id = kind == 'magma' and ('magma:' .. (MAGMA_SHOPS[opts.shop] and opts.shop or 'MagmaForge')) or kind
    local wk = st.works[id]
    local dry = opts.dry_run == true
    local function save() if not dry then st.works[id] = wk; save_state(st) end end
    local function wait(why) return {ok = false, rejected = true, waiting = true, stage = wk.stage, error = why} end
    local function advance(stage, extra)
        if not dry then wk.stage = stage; wk.since = now(); save() end
        local out = {ok = true, kind = kind, stage = stage, dry_run = dry or nil}
        for k, v in pairs(extra or {}) do out[k] = v end
        return out
    end
    local function gate_of(p) return building(p.gate.x, p.gate.y, p.gate.z, 'Floodgate') end
    local function lever_of(p) return building(p.lever.x, p.lever.y, p.lever.z, 'Trap') end
    -- (0.105.36) the pump stack's screw pumps set to be worked by hand while
    -- it fills (DF's "Start pump manually"), unset when it stops; how many
    local function pumps_manual(on)
        if dry or not wk or type(wk.plan) ~= 'table' or wk.plan.kind ~= 'pump' then return 0 end
        local n = 0
        for _, b in ipairs(wk.plan.builds or {}) do
            if b.kind == 'ScrewPump' then
                local bb = building(b.x, b.y, b.z, 'ScrewPump')
                if bb and bb.built and set_pump_manual(bb.id, on) then n = n + 1 end
            end
        end
        if on and n > 0 then
            wk.manual = n
            wk.manual_since = wk.manual_since or now()
        elseif not on then
            wk.manual, wk.manual_since = nil, nil
        end
        return n
    end
    local function hold(why)
        pumps_manual(false)        -- (0.105.36) a held stack isn't worked
        if not dry then wk.stage = 'held'; wk.why = why; save() end
        return {ok = false, rejected = true, stage = 'held', error = why}
    end
    -- (0.105.33) the floodgate shut at once, any pull on its way called off;
    -- true: it was open (and so pulled)
    local function shut_now(g)
        if dry or not wk.lever_id then return false end
        cancel_pulls(wk.lever_id)
        if g and g.built and not g.closed then pull(wk.lever_id, true) return true end
        return false
    end
    -- (0.105.33) filling that never ends: the floodgate shut, held, with why
    local function stalled(g, why)
        shut_now(g)
        pumps_manual(false)
        return hold(why)
    end
    -- (0.105.36) a citizen in deep water near the work's own tiles (a flood
    -- shut counts toward SHUTS_MAX only then: the report's "dwarves in deep
    -- water" is anywhere on the map). Unknown (no citizens): counted.
    local function flood_near()
        local okc, cs = pcall(citizens)
        local tiles = type(wk.plan) == 'table' and (wk.plan.tiles or wk.plan.wet) or nil
        if not okc or type(cs) ~= 'table' or type(tiles) ~= 'table' or next(tiles) == nil then return true end
        for _, c in ipairs(cs) do
            if type(c) == 'table' and c.x and depth_at(c) >= 4 then
                for _, t in ipairs(tiles) do
                    if math.abs(c.z - t.z) <= 3 and math.max(math.abs(c.x - t.x), math.abs(c.y - t.y)) <= FLOOD_NEAR then
                        return true
                    end
                end
            end
        end
        return false
    end

    -- the emergency stop, and retiring
    if opts.shut or opts.retire then
        if not wk then return {ok = false, rejected = true, error = 'no ' .. kind .. ' work to shut'} end
        -- (v35 fix) a hold that watches for water still getting in (or whose
        -- floodgate is gone) is never retired: the watch would stop
        if opts.retire and wk.stage == 'held' and type(wk.why) == 'string'
                and (wk.why:find('water is still getting in', 1, true) or wk.why:find('the floodgate is gone', 1, true)) then
            return {ok = false, rejected = true, stage = 'held', leak_watch = true,
                    error = 'held while water may still get in (' .. wk.why:sub(1, 80) .. '): not retired, kept watched'}
        end
        local g = gate_of(wk.plan)
        if dry then return {ok = true, dry_run = true, stage = wk.stage} end
        local was_open = shut_now(g)
        pumps_manual(false)
        if opts.retire then
            wk.stage = 'retired'; wk.why = opts.why or 'retired'
            wk.shut, wk.shut_open = nil, nil
            -- (0.105.35) retired by the AI (a held work): not begun again for a
            -- while (the brain's retry wait), and never after RETIRE_MAX times
            st.retired_n = type(st.retired_n) == 'table' and st.retired_n or {}
            st.retired_n[id] = (math.tointeger(st.retired_n[id]) or 0) + 1
            st.refused[id] = {tick = now(), why = 'retired: ' .. wk.why, retired = st.retired_n[id]}
        else
            -- (0.105.33) kept shut: the steps wait (and pull nothing) until the
            -- brain asks for it to be opened again (reopen)
            wk.shut = opts.why or 'shut'
            wk.shut_at = now()
            wk.shut_open = wk.shut_open or was_open or nil
            -- (0.105.36) only the shuts of the last SHUTS_WINDOW_DAYS count,
            -- and only with a citizen in deep water near the work (floods
            -- elsewhere, years apart, never hold a work)
            local recent = {}
            for _, t in ipairs(type(wk.shut_ticks) == 'table' and wk.shut_ticks or {}) do
                if math.tointeger(t) and now() - t < SHUTS_WINDOW_DAYS * DAY then table.insert(recent, t) end
            end
            if flood_near() then table.insert(recent, now()) end
            wk.shut_ticks = recent
            wk.shuts = #recent
            if wk.shuts >= SHUTS_MAX and wk.stage ~= 'held' then
                wk.stage = 'held'
                wk.why = ('the floodgate was shut %d times in %d days (%s), with dwarves in deep water near it: '
                          .. 'the AI retires it, its floodgate shut for good'):format(wk.shuts, SHUTS_WINDOW_DAYS, wk.shut)
            end
        end
        save()
        return {ok = true, stage = wk.stage, shut = true}
    end

    if not wk or wk.stage == 'retired' then
        local n_ret = type(st.retired_n) == 'table' and math.tointeger(st.retired_n[id]) or 0
        if n_ret >= RETIRE_MAX then
            -- (0.105.36) the refusal stamped (with `retired`, so the brain
            -- skips this work and goes on to the next kind)
            local why0 = ('retired %d times already: not begun again'):format(n_ret)
            if not dry then
                local old = type(st.refused[id]) == 'table' and st.refused[id] or {}
                st.refused[id] = {tick = now(), why = old.why or why0, retired = n_ret}
                save_state(st)
            end
            return {ok = false, rejected = true, retired = n_ret, error = why0}
        end
        local plan, why
        if kind == 'moat' then plan, why = plan_moat({plain = opts.plain})
        elseif kind == 'magma' then plan, why = plan_magma(opts.shop, {open_caverns = opts.open_caverns == true})
        else plan, why = PLANNERS[kind]() end
        if not plan then
            if not dry then st.refused[id] = {tick = now(), why = why}; save_state(st) end
            return {ok = false, rejected = true, error = why}
        end
        local path = path_check(plan)
        if not path.ok then
            local why2 = ('dry run: %s at x%d y%d, elevation %d'):format(path.why, path.at.x, path.at.y, path.at.e)
            if not dry then st.refused[id] = {tick = now(), why = why2}; save_state(st) end
            return {ok = false, rejected = true, error = why2, path = path}
        end
        if dry then return {ok = true, dry_run = true, stage = 'planned', plan = plan, path = path} end
        st.refused[id] = nil
        wk = {kind = kind, plan = plan, path = path}
        return advance('planned', {path = path})
    end
    local p = wk.plan
    if wk.stage == 'held' then
        -- (0.105.36) a leak-watch hold looked at again (the brain asks for a
        -- `recheck`, or a why starting "recheck"): the floodgate rebuilt if it
        -- is gone, the farm room's wet tiles counted again; un-held when dry
        local again = opts.recheck == true or (type(opts.why) == 'string' and opts.why:match('^recheck') ~= nil)
        local why0 = type(wk.why) == 'string' and wk.why or ''
        local gone_hold = why0:find('the floodgate is gone', 1, true) ~= nil
        local wet_hold = why0:find('water is still getting in', 1, true) ~= nil
        if not (again and (gone_hold or wet_hold)) then
            return {ok = false, rejected = true, stage = 'held', error = wk.why}
        end
        if dry then return {ok = true, dry_run = true, stage = 'held', recheck = true} end
        local function watching(why) save() return {ok = false, rejected = true, waiting = true, stage = 'held', error = why} end
        local g, l = gate_of(p), lever_of(p)
        if not g or not l then
            -- gone (a building destroyer): a new one placed where it stood
            -- (magma: magma-safe, the building stage checks it)
            if not gone_hold then wk.why = 'the floodgate is gone (destroyed while held): a new one is placed' end
            local cells = {}
            if not g then table.insert(cells, {x = p.gate.x, y = p.gate.y, z = p.gate.z, text = 'x'}) end
            if not l then table.insert(cells, {x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}) end
            local filtered = p.kind == 'magma' and magma_filter(true) or nil
            local ok = designate_all(cells, 'build')
            if filtered then magma_filter(filtered) end
            if not ok then
                return watching(('the floodgate or its lever is gone and the game would not place a new one at x%d y%d, '
                                 .. 'elevation %d: kept watched, tried again in a few days'):format(p.gate.x, p.gate.y, ez(p.gate.z)))
            end
            return watching('the floodgate or its lever is gone: a new one is placed where it stood')
        end
        if gone_hold then
            -- a floodgate stands there again: built, linked and opened as before
            wk.why, wk.opened_once, wk.open_from, wk.opened_at, wk.relinks = nil, nil, nil, nil, nil
            wk.rise_at, wk.test_from = nil, nil
            return advance('building')
        end
        if g.built and not g.closed then shut_now(g) end
        if p.room then
            local r = p.room
            local wet = 0
            for x = r.x1, r.x2 do for y = r.y1, r.y2 do if depth_at({x = x, y = y, z = r.z}) > 0 then wet = wet + 1 end end end
            wk.wet = wet
            if wet == 0 then
                wk.why, wk.slow = nil, nil
                return advance('drying', {wet = 0})       -- dry now: the next step finishes it
            end
            return watching(('the farm room is still wet (%d tile(s)): kept watched, its floodgate shut'):format(wet))
        end
        wk.why = nil
        return advance('filling')
    end

    -- (0.105.33) shut by the emergency stop: nothing pulled until the brain
    -- asks for it again (reopen; the bridge passes `why`, so a why starting
    -- "reopen" asks too), and then no sooner than REOPEN_AFTER_DAYS
    if wk.shut then
        local again = opts.reopen == true or (type(opts.why) == 'string' and opts.why:match('^reopen') ~= nil)
        if not again then return wait(('the floodgate is shut (%s): waiting to be opened again'):format(wk.shut)) end
        local since = now() - (wk.shut_at or 0)
        if since < REOPEN_AFTER_DAYS * DAY then
            return wait(('the floodgate was shut (%s) under %d days ago: not opened yet'):format(wk.shut, REOPEN_AFTER_DAYS))
        end
        if dry then return {ok = true, dry_run = true, stage = wk.stage, reopen = true} end
        local g = gate_of(p)
        local opened = false
        if wk.shut_open and g and g.built and g.closed and wk.lever_id
                and (wk.stage == 'filling' or wk.stage == 'done') then
            pull(wk.lever_id, false)
            opened = true
            if wk.stage == 'filling' then wk.opened_at = now() end
        end
        if wk.stage == 'filling' then
            -- (0.105.36) the stall clocks start again: the days shut don't
            -- count, and a pull not made yet is waited on (and asked again)
            -- as at the first opening
            if opened then wk.opened_once, wk.open_from = nil, now() end
            wk.rise_at, wk.test_from, wk.stalled = nil, now(), nil
        end
        wk.shut, wk.shut_at, wk.shut_open = nil, nil, nil
        save()
        return {ok = true, stage = wk.stage, reopened = true, opening = opened or nil}
    end

    if wk.stage == 'planned' then
        if dry then return {ok = true, dry_run = true, stage = 'digging'} end
        -- (0.105.38) a long dig a segment at a time (the first one now)
        local ok, z = designate_all(seg_cells(p, 1), 'dig')
        if not ok then return {ok = false, error = ('the game would not designate the dig (elevation %d)'):format(ez(z))} end
        if p.stages then wk.seg = 1 end
        return advance('digging', p.stages and {segment = 1, segments = #p.stages} or nil)
    end
    if wk.stage == 'digging' and p.stages and (wk.seg or 1) < #p.stages then
        -- (0.105.38) the segment dug: the dry run walked again over the whole
        -- plan (something may have opened beside it meanwhile), then the next
        local i = wk.seg or 1
        local n = left_to_dig(seg_cells(p, i))
        if n > 0 then return wait(('%d tile(s) left to dig (segment %d of %d)'):format(n, i, #p.stages)) end
        local chk = path_check(p)
        if not chk.ok then
            return hold(('dry run before segment %d of %d: %s at x%d y%d, elevation %d'):format(
                i + 1, #p.stages, chk.why, chk.at.x, chk.at.y, chk.at.e))
        end
        if dry then return {ok = true, dry_run = true, stage = 'digging', segment = i + 1} end
        local ok, z = designate_all(seg_cells(p, i + 1), 'dig')
        if not ok then return {ok = false, error = ('the game would not designate the dig (elevation %d)'):format(ez(z))} end
        wk.seg = i + 1
        save()
        return wait(('segment %d of %d designated'):format(i + 1, #p.stages))
    end
    if wk.stage == 'digging' then
        local n = left_to_dig(p.dig)
        if n > 0 then return wait(('%d tile(s) left to dig'):format(n)) end
        if p.dig2 and not wk.dig2 then
            if dry then return {ok = true, dry_run = true, stage = 'digging'} end
            local ok = designate_all(p.dig2, 'dig')
            if not ok then return {ok = false, error = 'the game would not designate the floodgate\'s floor'} end
            wk.dig2 = true
            save()
            return wait('the floodgate\'s floor is being dug')
        end
        if p.dig2 and left_to_dig(p.dig2) > 0 then return wait('the floodgate\'s floor is being dug') end
        -- (0.105.0 review) magma: only with magma-safe parts at hand (a wooden
        -- or iron floodgate would melt or burn, and the magma flood the fort);
        -- buildingplan's magma filter on while they are placed
        local filtered = nil
        if p.kind == 'magma' then
            local have = magma_parts()
            local want = {floodgates = 1, hatches = 1, mechanisms = 3}
            local short = {}
            for _, k in ipairs({'floodgates', 'hatches', 'mechanisms'}) do
                if (have[k] or 0) < want[k] then
                    table.insert(short, ('%d magma-safe %s (has %d)'):format(want[k], k, have[k] or 0))
                end
            end
            if #short > 0 then
                return wait('magma works need magma-safe parts (e.g. of green glass, or of a metal like steel): '
                            .. table.concat(short, ', '))
            end
        end
        if dry then return {ok = true, dry_run = true, stage = 'building'} end
        if p.kind == 'magma' then filtered = magma_filter(true) end
        local cells = {{x = p.gate.x, y = p.gate.y, z = p.gate.z, text = 'x'},
                       {x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}}
        for _, b in ipairs(p.builds or {}) do table.insert(cells, b) end
        local ok = designate_all(cells, 'build')
        if filtered then magma_filter(filtered) end
        if not ok then return {ok = false, error = 'the game would not place the floodgate, lever or the work\'s buildings'} end
        return advance('building')
    end
    if wk.stage == 'building' then
        local g, l = gate_of(p), lever_of(p)
        if not g or not l then return {ok = false, error = 'the floodgate or the lever is gone'} end
        local left = {}
        if not g.built then table.insert(left, 'the floodgate') end
        if not l.built then table.insert(left, 'the lever') end
        for _, b in ipairs(p.builds or {}) do
            local bb = building(b.x, b.y, b.z, b.kind)
            if not bb or not bb.built then table.insert(left, b.kind:lower()) end
        end
        if #left > 0 then return wait('being built: ' .. table.concat(left, ', ')) end
        -- (0.105.0 review) magma: what was built must be magma-safe (nothing flows yet)
        if p.kind == 'magma' then
            local bad = {}
            if building_magma_safe(g.id) == false then table.insert(bad, 'the floodgate') end
            for _, b in ipairs(p.builds or {}) do
                local bb = building(b.x, b.y, b.z, b.kind)
                if bb and building_magma_safe(bb.id) == false then table.insert(bad, b.kind:lower()) end
            end
            if #bad > 0 then
                return hold(table.concat(bad, ' and ') .. ' was built of a material that is not magma-safe: '
                            .. 'take it down and build it of a magma-safe one')
            end
        end
        if dry then return {ok = true, dry_run = true, stage = 'linking'} end
        set_name(l.id, p.lever.name)
        for _, b in ipairs(p.builds or {}) do
            local bb = building(b.x, b.y, b.z, b.kind)
            if b.lock then lock_hatch(bb.id) end
            if b.kind == 'Bridge' then wk.bridge_id = bb.id end
        end
        local r = link(l.id, g.id)
        if not r.ok then return r end
        wk.lever_id, wk.gate_id = l.id, g.id
        return advance('linking')
    end
    if wk.stage == 'linking' then
        if not is_linked(wk.lever_id, wk.gate_id) then
            if link_pending(wk.lever_id) or dry then return wait('the lever is being linked to the floodgate') end
            wk.relinks = (wk.relinks or 0) + 1
            if wk.relinks > 3 then return hold('the lever\'s link to the floodgate was lost 3 times: the AI retires it') end
            local r = link(wk.lever_id, wk.gate_id)
            save()
            if not r.ok then return r end
            return wait('the link was lost: asked for again')
        end
        -- (moat) the drawbridge is not on the moat's lever (one pull would
        -- work both): the gate scan finds it unworked and the gate rules give
        -- it its own "AI gate lever", which the gate watcher pulls
        if p.kind == 'moat' and p.bridge and p.bridge.drawbridge and not dry and not wk.gates_rescanned then
            pcall(function() reqscript('ai-gates').scan(now()) end)
            wk.gates_rescanned = true
            save()
        end
        if dry then return {ok = true, dry_run = true, stage = 'filling'} end
        return advance('filling', {})
    end
    if wk.stage == 'filling' then
        local g = gate_of(p)
        if not g then return hold('the floodgate is gone') end
        local lk = leak(p)
        if lk then
            shut_now(g)
            return hold(('liquid got out at x%d y%d, elevation %d: the floodgate was shut'):format(lk.x, lk.y, ez(lk.z)))
        end
        -- the plug: dug with the gate shut, after the path is walked again
        if not dug(T(p.plug.x, p.plug.y, p.plug.z), p.plug.text) then
            local path = path_check(p)
            if not path.ok then
                wk.path = path
                return wait(('the plug waits: %s at x%d y%d, elevation %d'):format(path.why, path.at.x, path.at.y, path.at.e))
            end
            if dry then return {ok = true, dry_run = true, stage = 'filling', plug = true} end
            if not g.closed then pull(wk.lever_id, true) return wait('the floodgate is shut before the plug is dug') end
            designate({{x = p.plug.x, y = p.plug.y, text = p.plug.text}}, p.plug.z, 'dig')
            dig_now(p.plug.x, p.plug.y, p.plug.z)
            if not dug(T(p.plug.x, p.plug.y, p.plug.z), p.plug.text) then
                return wait('the plug is being dug (DFHack dig-now did not dig it)')
            end
            wk.opened_at = now()
            pull(wk.lever_id, false)
            save()
            return {ok = true, stage = 'filling', plug_dug = true, opening = true}
        end
        if g.closed and not wk.opened_once then
            -- (0.105.33) not waited on for ever: held when nobody opened it
            if not dry and not wk.open_from then wk.open_from = wk.opened_at or now() save() end
            if now() - (wk.open_from or now()) > FILL_STALL_DAYS * DAY then
                return hold(('the floodgate was not opened in %d days: can a dwarf reach its lever?'):format(FILL_STALL_DAYS))
            end
            -- (0.105.36) no pull yet (a floodgate placed again after it was gone): one now
            if (not wk.opened_at or now() - wk.opened_at > 2 * DAY) and not dry then pull(wk.lever_id, false) wk.opened_at = now() save() end
            return wait('a dwarf is on the way to open the floodgate')
        end
        if not dry and not wk.opened_once then wk.opened_once = true; wk.test_from = now(); save() end
        local t = p.test
        -- (0.105.33) the last rise, for the stall test (a frozen or dry source, a blocked way)
        local function rose(d)
            if not dry and (wk.best == nil or d > wk.best) then
                wk.best = d; wk.rise_at = now()
                wk.stalled = nil             -- (0.105.36) rising again: no more pump labour asked
            end
            return now() - (wk.rise_at or wk.test_from or now()) > FILL_STALL_DAYS * DAY
        end
        if t.mode == 'deep' then
            local d = depth_at(t)
            wk.depth = d
            if d < t.want then
                if rose(d) then
                    return stalled(g, ('%s has not risen in %d days (%d/7): the source may be frozen or dry, or its way '
                                       .. 'blocked; the floodgate was shut'):format(kind == 'moat' and 'the moat' or 'the magma pit',
                                                                                    FILL_STALL_DAYS, d))
                end
                save()
                return wait(('filling: %d/7 (wants %d/7)'):format(d, t.want))
            end
            return advance('finishing', {depth = d})
        elseif t.mode == 'rise' then
            -- (0.105.36) the pumps worked by hand (set again each step: cheap)
            local manual = pumps_manual(true)
            local d = depth_at(t)
            if wk.start_depth == nil and not dry then wk.start_depth = d end
            wk.depth = d
            if d >= t.want then
                pumps_manual(false)
                return advance('done', {depth = d, rose = d - (wk.start_depth or 0)})
            end
            -- (said in the stall text; the stall wait still runs, so it never waits for ever)
            if not dry then wk.manual_failed = manual == 0 or nil end
            if rose(d) then
                return stalled(g, ('the reservoir has not risen in %d days (%d/7): the pumps are not worked, or the '
                                   .. 'water is gone; the floodgate was shut'):format(FILL_STALL_DAYS, d))
            end
            if now() - (wk.rise_at or wk.test_from or now()) > PUMP_TEST_DAYS * DAY then
                wk.stalled = true
                save()
                return wait(('the reservoir has not risen in %d days (%d/7): is a dwarf working the pumps (the pump operator labour)?%s')
                    :format(PUMP_TEST_DAYS, d, wk.manual_failed and ' (the pumps could not be set to "Start pump manually")' or ''))
            end
            save()
            return wait(('pumping: the reservoir %d/7 (from %d/7)'):format(d, wk.start_depth or 0))
        elseif t.mode == 'wet' then
            local r = p.room
            local wet = 0
            for x = r.x1, r.x2 do for y = r.y1, r.y2 do if depth_at({x = x, y = y, z = r.z}) > 0 then wet = wet + 1 end end end
            if wet == 0 then
                if now() - (wk.test_from or now()) > FILL_STALL_DAYS * DAY then
                    return stalled(g, ('no water reached the farm room in %d days: the source may be frozen or dry, '
                                       .. 'or the tunnel blocked; the floodgate was shut'):format(FILL_STALL_DAYS))
                end
                return wait('the water is on its way into the farm room')
            end
            if dry then return {ok = true, dry_run = true, stage = 'drying'} end
            -- enough: a little water muddies the floor. (0.105.33) Shut, not
            -- toggled: the lever pulled only while the floodgate is open
            shut_now(g)
            return advance('drying', {wet = wet})
        end
    end
    if wk.stage == 'drying' then
        local r = p.room
        local wet = 0
        for x = r.x1, r.x2 do for y = r.y1, r.y2 do if depth_at({x = x, y = y, z = r.z}) > 0 then wet = wet + 1 end end end
        wk.wet = wet
        if wet > 0 then
            -- (0.105.0 review) not waited on for ever: held, with why
            if now() - (wk.since or now()) > IRR_DRY_DAYS * DAY then
                wk.slow = true
                shut_now(gate_of(p))
                return hold(('the farm room is still wet after %d days (%d tile(s)): water is still getting in '
                             .. '(the floodgate leaks, or a second way in); the AI keeps it watched, its floodgate shut, '
                             .. 'and looks again every few days'):format(IRR_DRY_DAYS, wet))
            end
            save()
            return wait(('the farm room is drying: %d tile(s) still wet'):format(wet))
        end
        return advance('finishing')
    end
    if wk.stage == 'finishing' then
        if p.kind == 'irrigation' then
            local r = p.room
            local cells, muddy = {}, 0
            for x = r.x1, r.x2 do for y = r.y1, r.y2 do
                if not (x == r.x1 and y == r.y1) and mud(x, y, r.z) then
                    muddy = muddy + 1
                    table.insert(cells, {x = x, y = y, z = r.z, text = 'p'})
                end
            end end
            if muddy == 0 then return hold('the floor dried without mud: the AI retires it') end
            if dry then return {ok = true, dry_run = true, stage = 'done', muddy = muddy} end
            if not designate_all(cells, 'build') then return {ok = false, error = 'the game would not place the farm plots'} end
            return advance('done', {muddy = muddy})
        end
        if p.kind == 'magma' then
            local f = p.finish[1]
            local b = building(f.x, f.y, f.z, f.kind)
            if b and b.built then return advance('done') end
            if b then return wait('the ' .. p.shop .. ' is being built') end
            if dry then return {ok = true, dry_run = true, stage = 'finishing'} end
            if not designate_all(p.finish, 'build') then return {ok = false, error = 'the game would not place the ' .. p.shop} end
            save()
            return wait('the ' .. p.shop .. ' is placed over the magma')
        end
        return advance('done')
    end
    if wk.stage == 'done' then
        local lk = leak(p)
        local g = gate_of(p)
        if lk and g and not g.closed then
            shut_now(g)
            return hold(('liquid got out at x%d y%d, elevation %d: the floodgate was shut'):format(lk.x, lk.y, ez(lk.z)))
        end
        -- (0.105.0 review) waiting: the planner looks again in a few days (the leak check)
        return {ok = false, rejected = true, waiting = true, stage = 'done', error = 'the ' .. kind .. ' is done (no leak)'}
    end
    return {ok = false, rejected = true, error = 'unknown stage ' .. tostring(wk.stage)}
end

-- The report: each work's stage and what it waits for, and the refusals.
function report()
    local st = load_state()
    local out = {works = {}, refused = {}}
    local parts          -- (13c) the parts in store, counted once a report (not once a work)
    local links          -- (0.105.33) the levers' links, fetched once a report (not once a work)
    for id, wk in pairs(st.works) do
        if wk.lever_id and not links then links = lever_links() or {} end
        local p = wk.plan or {}
        local g = p.gate and building(p.gate.x, p.gate.y, p.gate.z, 'Floodgate')
        local row = {kind = wk.kind, stage = wk.stage, why = wk.why, depth = wk.depth, wet = wk.wet,
                     stalled = wk.stalled or nil, slow = wk.slow or nil, shut = wk.shut,
                     manual = wk.manual, manual_since = wk.manual_since,
                     gate = g and (g.built and (g.closed and 'shut' or 'open') or 'planned') or nil,
                     linked = wk.lever_id and is_linked(wk.lever_id, wk.gate_id, links) or nil,
                     path_tiles = wk.path and wk.path.tiles, lift = p.lift, power = p.power, wheel = p.wheel,
                     shop = p.shop, bridge = p.bridge and (p.bridge.drawbridge and 'drawbridge' or 'bridge') or nil,
                     lever_at = p.lever and {x = p.lever.x, y = p.lever.y, e = ez(p.lever.z)} or nil,
                     gate_at = p.gate and {x = p.gate.x, y = p.gate.y, e = ez(p.gate.z)} or nil}
        if wk.kind == 'power' then
            -- (0.105.37 E3) the power: its source, the power check, on or off
            row.source, row.need, row.have, row.wheels = p.source, p.need, p.have, p.wheels
            row.engaged = wk.stage == 'running' and wk.engaged ~= false or nil
            row.power, row.power_need = wk.power, wk.power_need
            row.still = wk.still_from and true or nil
            row.paused = wk.stage == 'running' and wk.paused or nil      -- (0.105.37 fix) a still wheel: why
        end
        pcall(function()
            if wk.stage == 'linking' or wk.stage == 'building' then
                if not parts then
                    local B = reqscript('ai-builder')
                    parts = {floodgates = B.count_items('FLOODGATE'), mechanisms = B.count_items('TRAPPARTS'),
                             pipes = B.count_items('PIPE_SECTION')}
                end
                row.floodgates_free, row.mechanisms_free, row.pipes_free = parts.floodgates, parts.mechanisms, parts.pipes
            end
        end)
        out.works[id] = row
    end
    for id, r in pairs(st.refused) do out.refused[id] = r end
    return out
end
