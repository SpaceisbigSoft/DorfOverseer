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
KINDS = {moat = true, pump = true, irrigation = true, magma = true}
MAGMA_SHOPS = {MagmaForge = 'wv', MagmaSmelter = 'el', MagmaGlassFurnace = 'ea'}   -- quickfort keys (guesses: wv/el/ea)

MOAT_GAP = 3            -- tiles from the gate's outside tile to the trench
MOAT_HALF = 3           -- the trench runs this far each side of the gate's line
MOAT_FEED_MAX = 40      -- tiles of feed channel from the river at most
PUMP_MAX_LIFT = 6       -- levels a pump stack lifts at most (one dwarf a pump)
PUMP_TEST_DAYS = 14     -- no rise in the reservoir this long: said so
IRR_REACH = 14          -- the farm room this near its water
IRR_DRY_DAYS = 28       -- still wet this long: said so
MAGMA_REACH = 10        -- the workshop's pit this near the magma
MAGMA_STAIR_MAX = 60    -- levels of stair down to the magma at most
PATH_MAX = 400          -- tiles the water may reach (outside, for a moat)
FILL_STALL_DAYS = 28    -- (0.105.33) filling with no rise this long: held, said why
REOPEN_AFTER_DAYS = 3   -- (0.105.33) a shut floodgate opened again no sooner than this
SHUTS_MAX = 3           -- (0.105.33) shut this often for a flood: held for the player
DAY = 1200

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
function plan_moat(opts)
    opts = opts or {}
    local w = water_survey()
    if not w then return nil, 'no water survey yet' end
    local river, river_z2
    for _, b in ipairs(w.bodies or {}) do if b.kind == 'river' then river, river_z2 = b.nearest, b.z2 end end
    if not river then return nil, 'no river or brook near the fort' end
    local es = entrances()
    if #es == 0 then return nil, 'no surface entrance found (scan the entrances first)' end
    local why
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
                local f = l_path(start, river, function(x, y) return ground(x, y, z) end, xfirst)
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
                              or 'no diggable ground for a channel from the river to the trench')
                goto next
            end
            if #feed < 3 then why = why or 'the river is too close to the trench for a floodgate between' goto next end
            if #feed > MOAT_FEED_MAX then why = why or ('the river is %d tiles from the trench (%d at most)'):format(#feed, MOAT_FEED_MAX) goto next end
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
            return p
        end
        ::next::
    end
    return nil, why or 'no gate fit for a moat'
end

-- W4: screw pumps lifting still water from a level below to a 3x3
-- reservoir under the fort's lowest level (a well goes over it later).
-- Worked by a dwarf (the pump operator labour).
function plan_pump(opts)
    local why_b
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local w = water_survey()
    if not w then return nil, 'no water survey yet' end
    local src
    for _, b in ipairs(w.bodies or {}) do
        if b.kind == 'pool' and b.nearest and b.nearest.z < fb.z_low then src = b.nearest end
    end
    if not src then return nil, 'no still water under the fort outside the caverns (cavern water is not tunnelled to)' end
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
        for _, wt in ipairs(waters) do
            for _, d in ipairs(N4) do
                for gap = 3, IRR_REACH do
                    local cx, cy = wt.x + d[1] * (gap + 2), wt.y + d[2] * (gap + 2)
                    local ok = true
                    for x = cx - 2, cx + 2 do for y = cy - 2, cy + 2 do
                        if not rock(T(x, y, z)) then ok = false end
                    end end
                    local above = T(cx - 2, cy - 2, zf)
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
function plan_magma(shop)
    shop = MAGMA_SHOPS[shop] and shop or 'MagmaForge'
    local why_b
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local w = water_survey()
    local m = w and w.magma and w.magma.top_nearest
    if not m then return nil, 'no magma found near the fort (or the survey is older than 0.105.0)' end
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

-- One step of the work of `kind`. opts: {dry_run, shut, retire, shop, plain}
function step(kind, opts)
    opts = opts or {}
    if not KINDS[kind] then return {ok = false, rejected = true, error = 'water_work: unknown kind ' .. tostring(kind)} end
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
    local function hold(why)
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
        return hold(why)
    end

    -- the emergency stop, and retiring
    if opts.shut or opts.retire then
        if not wk then return {ok = false, rejected = true, error = 'no ' .. kind .. ' work to shut'} end
        local g = gate_of(wk.plan)
        if dry then return {ok = true, dry_run = true, stage = wk.stage} end
        local was_open = shut_now(g)
        if opts.retire then
            wk.stage = 'retired'; wk.why = opts.why or 'retired'
            wk.shut, wk.shut_open = nil, nil
        else
            -- (0.105.33) kept shut: the steps wait (and pull nothing) until the
            -- brain asks for it to be opened again (reopen)
            wk.shut = opts.why or 'shut'
            wk.shut_at = now()
            wk.shut_open = wk.shut_open or was_open or nil
            wk.shuts = (wk.shuts or 0) + 1
            if wk.shuts >= SHUTS_MAX and wk.stage ~= 'held' then
                wk.stage = 'held'
                wk.why = ('the floodgate was shut %d times (%s): mend it by hand, then retire it or let it go on')
                    :format(wk.shuts, wk.shut)
            end
        end
        save()
        return {ok = true, stage = wk.stage, shut = true}
    end

    if not wk or wk.stage == 'retired' then
        local plan, why
        if kind == 'moat' then plan, why = plan_moat({plain = opts.plain})
        elseif kind == 'magma' then plan, why = plan_magma(opts.shop)
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
    if wk.stage == 'held' then return {ok = false, rejected = true, stage = 'held', error = wk.why} end

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
        wk.shut, wk.shut_at, wk.shut_open = nil, nil, nil
        save()
        return {ok = true, stage = wk.stage, reopened = true, opening = opened or nil}
    end

    if wk.stage == 'planned' then
        if dry then return {ok = true, dry_run = true, stage = 'digging'} end
        local ok, z = designate_all(p.dig, 'dig')
        if not ok then return {ok = false, error = ('the game would not designate the dig (elevation %d)'):format(ez(z))} end
        return advance('digging')
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
            if wk.relinks > 3 then return hold('the lever\'s link to the floodgate was lost 3 times: link it by hand') end
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
            if wk.opened_at and now() - wk.opened_at > 2 * DAY and not dry then pull(wk.lever_id, false) wk.opened_at = now() save() end
            return wait('a dwarf is on the way to open the floodgate')
        end
        if not dry and not wk.opened_once then wk.opened_once = true; wk.test_from = now(); save() end
        local t = p.test
        -- (0.105.33) the last rise, for the stall test (a frozen or dry source, a blocked way)
        local function rose(d)
            if not dry and (wk.best == nil or d > wk.best) then wk.best = d; wk.rise_at = now() end
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
            local d = depth_at(t)
            if wk.start_depth == nil and not dry then wk.start_depth = d end
            wk.depth = d
            if d >= t.want then return advance('done', {depth = d, rose = d - (wk.start_depth or 0)}) end
            if rose(d) then
                return stalled(g, ('the reservoir has not risen in %d days (%d/7): the pumps are not worked, or the '
                                   .. 'water is gone; the floodgate was shut'):format(FILL_STALL_DAYS, d))
            end
            if now() - (wk.rise_at or wk.test_from or now()) > PUMP_TEST_DAYS * DAY then
                wk.stalled = true
                save()
                return wait(('the reservoir has not risen in %d days (%d/7): is a dwarf working the pumps (the pump operator labour)?'):format(PUMP_TEST_DAYS, d))
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
                return hold(('the farm room is still wet after %d days (%d tile(s)): water is still getting in '
                             .. '(the floodgate leaks, or a second way in); dry it by hand, or retire it'):format(IRR_DRY_DAYS, wet))
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
            if muddy == 0 then return hold('the floor dried without mud: let water in again by hand, or retire it') end
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
                     gate = g and (g.built and (g.closed and 'shut' or 'open') or 'planned') or nil,
                     linked = wk.lever_id and is_linked(wk.lever_id, wk.gate_id, links) or nil,
                     path_tiles = wk.path and wk.path.tiles, lift = p.lift, power = p.power, wheel = p.wheel,
                     shop = p.shop, bridge = p.bridge and (p.bridge.drawbridge and 'drawbridge' or 'bridge') or nil,
                     lever_at = p.lever and {x = p.lever.x, y = p.lever.y, e = ez(p.lever.z)} or nil,
                     gate_at = p.gate and {x = p.gate.x, y = p.gate.y, e = ez(p.gate.z)} or nil}
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
