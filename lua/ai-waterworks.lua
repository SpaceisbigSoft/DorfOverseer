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

-- (0.105.48 r2) constructBuilding is in library/lua/dfhack/buildings.lua, added to
-- dfhack.buildings only by this require (without it, only after buildingplan loaded it)
pcall(function() require('dfhack.buildings') end)
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

-- (0.105.40b fix) why the dig guard refuses (x, y, z), or nil; `by`: the
-- refusal counted (once per tile)
function dig_guard_why(x, y, z, by)
    local okg, why = pcall(function() return reqscript('ai-builder').dig_forbidden(x, y, z) end)
    if not (okg and why) then return nil end
    if by then pcall(function() reqscript('ai-util').dig_refused(by, x, y, z, why) end) end
    return why
end

-- the guard's "could not read the tile" (lua/ai-util.lua GUARD_ERR)
function guard_err()
    local ok, e = pcall(function() return reqscript('ai-util').GUARD_ERR end)
    return ok and e or 'the dig guard could not read the tile'
end

function dig_now(x, y, z)
    -- (0.105.40b) the dig guard: never raw adamantine, the spire or the underworld (nor beside them)
    local why = dig_guard_why(x, y, z, 'dig_now')
    if why then return false, why end
    local pos = ('%d,%d,%d'):format(x, y, z)
    pcall(dfhack.run_command_silent, 'dig-now', pos, pos)
end

function citizens() return reqscript('ai-builder').citizen_positions() end
-- (0.105.38 review) the walk group of a tile (0: none), and the citizens' ({[group] = true})
function walk_group(x, y, z)
    local ok, g = pcall(function() return reqscript('ai-builder').walk_group(x, y, z) end)
    return ok and g or 0
end
function citizen_groups()
    local ok, g = pcall(function() return reqscript('ai-builder').citizen_groups() end)
    return ok and type(g) == 'table' and g or {}
end
-- (0.105.38 review) dig designations taken off tiles (a retired work's
-- tunnel left undug): how many
function undesignate(cells)
    local n = 0
    for _, c in ipairs(cells) do
        local ok = pcall(function()
            local des = dfhack.maps.getTileFlags(c.x, c.y, c.z)
            if des and des.dig ~= df.tile_dig_designation.No then
                des.dig = df.tile_dig_designation.No
                n = n + 1
            end
        end)
        if not ok then break end
    end
    return n
end
-- (0.105.38 review) the dig jobs already made for these tiles (the AI's own
-- plan tiles only) removed: how many
local DIG_JOBS = {Dig = true, DigChannel = true, CarveUpwardStaircase = true, CarveDownwardStaircase = true,
                  CarveUpDownStaircase = true, CarveRamp = true}
function cancel_dig_jobs(cells)
    local want = {}
    for _, c in ipairs(cells) do want[key(c.x, c.y, c.z)] = true end
    local n = 0
    pcall(function()
        local found = {}
        local link = df.global.world.jobs.list.next
        while link do
            local job = link.item
            link = link.next
            if job and DIG_JOBS[df.job_type[job.job_type]] and want[key(job.pos.x, job.pos.y, job.pos.z)] then
                table.insert(found, job)
            end
        end
        for _, job in ipairs(found) do
            if dfhack.job.removeJob(job) then n = n + 1 end
        end
    end)
    return n
end
-- (0.105.38 review) a line in DFHack's console (a retired work's half-dug tunnel)
function log_line(msg) pcall(function() print('[ai-waterworks] ' .. msg) end) end
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
    pcall(function() reqscript('ai-util').lock_door(df.building.find(id), true, 'water') end) -- (0.105.47) ai-util: the walk map redone
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

-- (0.105.38 review) a deep layer's tile (a cavern's, or the sea's): a
-- global feature. A local one is a magma pipe's, a pool's or (r2h1) a
-- river's or brook's (DF's river is a local feature), no cavern. A
-- tile reader without the two apart: its `feature` taken for a cavern.
local function cavern_tile(t)
    if t == nil then return false end
    if t.feature_global ~= nil or t.feature_local ~= nil then return t.feature_global == true end
    return t.feature == true
end

-- (0.105.38 review) the work's own source (p.src {x, y, z, magma}): its
-- liquid near the source's tile on its level is no other liquid (bypass,
-- walked again before each segment, still keeps it off every dug tile but
-- the plug); nil when the plan has none
local function own_source(p)
    local src = type(p.src) == 'table' and p.src or nil
    if not src then return nil end
    return function(x, y, z)
        local t = T(x, y, z)
        return t ~= nil and t.liquid and (t.magma == true) == (src.magma == true) and z == src.z
            and math.max(math.abs(x - src.x), math.abs(y - src.y)) <= 16
    end
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
-- (0.105.38 review) maxlen: a way longer is given up as soon as it is
local function l_path(a, b, ok, only, maxlen)
    for _, xfirst in ipairs(only == nil and {true, false} or {only}) do
        local path, x, y, good = {}, a.x, a.y, true
        local function walk(tx, ty)
            while (x ~= tx or y ~= ty) and good do
                table.insert(path, {x = x, y = y})
                if maxlen and #path > maxlen then good = false break end
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
-- (0.105.38 review) the 8 tiles round a tile and the one over it
local N8UP = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {1, 1, 0}, {1, -1, 0}, {-1, 1, 0}, {-1, -1, 0}, {0, 0, 1}}

-- (0.105.38 review) A far dig's tile: an aquifer or liquid among the 8 tiles
-- round it or over it (it would seep or flood once dug): why, or nil.
-- `own(x, y, z)`: a tile of the work's own source (allowed beside it).
local function wet_beside(x, y, z, own)
    for _, d in ipairs(N8UP) do
        local nx, ny, nz = x + d[1], y + d[2], z + d[3]
        local t = T(nx, ny, nz)
        if t and (t.aquifer or t.liquid) and not (own and own(nx, ny, nz)) then
            return ('%s %s the dug tile at x%d y%d, elevation %d'):format(t.aquifer and 'an aquifer' or (t.magma and 'magma' or 'water'),
                                                                         d[3] == 1 and 'over' or 'beside', x, y, ez(z))
        end
    end
    return nil
end

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

-- (0.105.38 review) A far plan's dig checked on the map itself (the
-- survey's estimate walked another way): no dug tile in an aquifer or with
-- one (or liquid) among the 8 tiles round it or over it (the plug, which
-- touches the source, excepted), none in a cavern unless `allow_cavern`
-- (the cavern switch). `feature_ok(z)`: a level whose deep feature is the
-- work's own source (the magma sea's layer). nil, or why (and `opens`: true
-- when it is a cavern the dig would open).
function far_route_check(p, allow_cavern, feature_ok)
    -- (review) the sea's own layer at and under p.deep_z (set on a sea plan)
    if not feature_ok and p.deep_z then feature_ok = function(z) return z <= p.deep_z end end
    local own = own_source(p)
    local exempt = {}
    if p.plug then exempt[key(p.plug.x, p.plug.y, p.plug.z)] = true end
    local seen = {}
    for _, list in ipairs({p.dig or {}, p.dig2 or {}}) do
        for _, c in ipairs(list) do
            local k = key(c.x, c.y, c.z)
            if not seen[k] and not exempt[k] then
                seen[k] = true
                local t = T(c.x, c.y, c.z)
                local fok = feature_ok and feature_ok(c.z)
                if cavern_tile(t) and not allow_cavern and not fok then
                    return ('the dig would open a cavern at x%d y%d, elevation %d (the cavern switch does not allow it)')
                        :format(c.x, c.y, ez(c.z)), true
                end
                if t and t.feature and not cavern_tile(t) and not fok then
                    return ('the dig would cross a magma pipe or a pool (a local feature) at x%d y%d, elevation %d')
                        :format(c.x, c.y, ez(c.z))
                end
                if t and t.aquifer then return ('the dig crosses an aquifer at x%d y%d, elevation %d'):format(c.x, c.y, ez(c.z)) end
                local wb = wet_beside(c.x, c.y, c.z, own)
                if wb then return wb end
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
-- (none or below 0); (0.105.38 review) 0: far sources off
function far_cap(w)
    local r = math.tointeger(tonumber(FAR.reach)) or FAR_REACH
    if r and r >= 0 then return r end
    local m = type(w) == 'table' and w.map or nil
    return type(m) == 'table' and math.tointeger(tonumber(m.w)) or 192
end

-- (0.105.38 review) 0: no far work at all (not the default's 600)
function far_job_max()
    local n = math.tointeger(tonumber(FAR.job_max))
    if n and n >= 0 then return n end
    return FAR_JOB_MAX
end
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
    if cap <= 0 or far_job_max() <= 0 then return out end     -- (0.105.38 review) far sources off
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
    if far_job_max() <= 0 then return 'far water works are off (the brain\'s water_job_max is 0)' end
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

-- (0.105.38 review) A staged dig's next segment, checked before it is
-- designated: each tile not dug yet still a wall of natural rock with no
-- liquid, no aquifer, no cavern (unless the plan opens one: its
-- source.opens_cavern) and nothing wet beside or over it; a tile dug
-- meanwhile only if dry and no cavern's. nil, or why.
function next_segment_bad(p, cells)
    local cav_ok = type(p.source) == 'table' and p.source.opens_cavern ~= nil
    local exempt = p.plug and key(p.plug.x, p.plug.y, p.plug.z) or nil
    local own = own_source(p)
    for _, c in ipairs(cells or {}) do
        local t = T(c.x, c.y, c.z)
        local where = ('x%d y%d, elevation %d'):format(c.x, c.y, ez(c.z))
        local deep_ok = p.deep_z ~= nil and c.z <= p.deep_z      -- (review) the sea's own layer
        if not t then return 'an unknown tile at ' .. where end
        if t.liquid then return 'liquid at ' .. where end
        if t.aquifer then return 'an aquifer at ' .. where end
        if cavern_tile(t) and not cav_ok and not deep_ok then return 'a cavern at ' .. where end
        if t.feature and not cavern_tile(t) and not deep_ok then return 'a magma pipe or a pool (a local feature) at ' .. where end
        if t.shape == 'WALL' then
            if NATURAL[t.material] ~= true then return 'no natural rock at ' .. where end
        elseif not OPEN[t.shape] or t.outside then
            return 'no longer solid rock at ' .. where
        end
        if key(c.x, c.y, c.z) ~= exempt then
            local wb = wet_beside(c.x, c.y, c.z, own)
            if wb then return wb end
        end
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

-- (r8) This file's locals the later parts use, handed on in one table (each
-- part takes back the ones it uses as locals of its own). All are functions
-- or tables that are never assigned again, so every part holds the same ones.
WATERWORKS_PART_LOCALS = {OPEN = OPEN, key = key, rock = rock, cavern_tile = cavern_tile, ground = ground, still_water = still_water, l_path = l_path, N4 = N4, N8 = N8, wet_beside = wet_beside, seg_cells = seg_cells}

---------------------------------------------------------------------------
-- (r8) The rest of the water works lives in parts beside this file
-- (ai-waterworks-<part>.lua): plans (the fort's box, the lever's spot, the
-- plans of the moat, the pump stack, the muddied farm level and the magma
-- workshop), power (the steps' helpers, and W7: the pump stack's power, its
-- plan and its step) and steps (step, one step of a work, and the report).
-- Each runs in this module's own environment, so its names stay
-- reqscript('ai-waterworks').name for the bridge and the other modules, and
-- a test's swap (W.T = ...) reaches every part. They load in this order, the
-- old file's. DFHack reloads a module when its own file changes: a change to
-- a part alone is picked up once ai-waterworks.lua is touched too, or the
-- game restarts.
---------------------------------------------------------------------------

PARTS = {'plans', 'power', 'steps'}
-- each part marks the version it came with (the bridge's `version` lists one
-- that differs from BRIDGE_VERSION); started afresh at each load, so a part
-- that failed to load shows as unmarked
PART_VERSIONS = {['ai-waterworks'] = '0.105.101'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-waterworks-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-waterworks: ' .. name .. '.lua is missing (it goes beside ai-waterworks.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
