-- Metal from the ground: what ore the fort has seen near it, and mining a
-- vein of the metal it needs. (Smelting is DFHack's own smelting orders, and
-- the furnaces come from a workshops level: brain/planner.py.)
--
-- Only ore the dwarves have uncovered counts as known: the AI doesn't look
-- through rock. Mining follows a known vein from an uncovered tile, as
-- DFHack's digv does, through rock the dwarves haven't seen yet, but never
-- next to water, magma, an aquifer, a cavern or open sky (every tile it marks
-- has only solid rock, the vein, or the fort's own dug tiles around it).
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

SURVEY_MARGIN = 40          -- tiles around the citizens looked at
LEVELS_BELOW = 12           -- levels below the deepest citizen looked at
VEIN_MAX = 80               -- tiles marked in one go (0.105.9: 80, Mining's top; was 60)

-- Pure: the order metals are wanted in for gear (steel comes from iron).

local function inorganic(idx)
    local ok, v = pcall(function() return df.global.world.raws.inorganics.all[idx] end)
    if ok and v then return v end
    ok, v = pcall(function() return df.global.world.raws.inorganics[idx] end)
    return ok and v or nil
end

-- The metals a stone smelts into: {'IRON', ...} (empty for plain stone).
-- (by material index, remembered: the survey asks it for every boulder in
-- the fort, thousands; the raws never change while the game runs)
METALS_OF = METALS_OF or {}
function metals_of(idx)
    local known = METALS_OF[idx]
    if known then return known end
    local inorg = inorganic(idx)
    local out = {}
    if not inorg then return out end
    pcall(function()
        for _, m in ipairs(inorg.metal_ore.mat_index) do
            local metal = inorganic(m)
            if metal then table.insert(out, metal.id) end
        end
    end)
    METALS_OF[idx] = out
    return out
end

local function area()
    local pos = reqscript('ai-builder').citizen_positions()
    if #pos == 0 then return nil end
    local x1, y1, x2, y2, z1, z2 = math.huge, math.huge, -math.huge, -math.huge, math.huge, -math.huge
    local sx, sy, sz = 0, 0, 0
    for _, p in ipairs(pos) do
        x1, x2, y1, y2 = math.min(x1, p.x), math.max(x2, p.x), math.min(y1, p.y), math.max(y2, p.y)
        z1, z2 = math.min(z1, p.z), math.max(z2, p.z)
        sx, sy, sz = sx + p.x, sy + p.y, sz + p.z
    end
    return {x1 = x1 - SURVEY_MARGIN, y1 = y1 - SURVEY_MARGIN, x2 = x2 + SURVEY_MARGIN, y2 = y2 + SURVEY_MARGIN,
            z1 = z1 - LEVELS_BELOW, z2 = z2 + 2, cx = sx // #pos, cy = sy // #pos, cz = sz // #pos}
end

local function is_wall(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    local a = tt and df.tiletype.attrs[tt]
    return a and df.tiletype_shape[a.shape] == 'WALL'
end

-- Each mineral vein event in the area: calls fn(block, ev, metals).
local function each_vein(a, fn)
    -- (0.104.140) only the area's own blocks, looked up by position, where
    -- DFHack can (the whole map's blocks were walked: ~460 ms a rebuild)
    local okg = dfhack.maps and dfhack.maps.getBlock ~= nil
    if okg then
        for z = a.z1, a.z2 do
            for by = a.y1 // 16, a.y2 // 16 do
                for bx = a.x1 // 16, a.x2 // 16 do
                    local block = dfhack.maps.getBlock(bx, by, z)
                    if block then
                        for _, ev in ipairs(block.block_events) do
                            if df.block_square_event_mineralst:is_instance(ev) then
                                local metals = metals_of(ev.inorganic_mat)
                                if #metals > 0 then fn(block, ev, metals) end
                            end
                        end
                    end
                end
            end
        end
        return
    end
    for _, block in ipairs(df.global.world.map.map_blocks) do
        local p = block.map_pos
        if p.z >= a.z1 and p.z <= a.z2 and p.x + 15 >= a.x1 and p.x <= a.x2 and p.y + 15 >= a.y1 and p.y <= a.y2 then
            for _, ev in ipairs(block.block_events) do
                if df.block_square_event_mineralst:is_instance(ev) then
                    local metals = metals_of(ev.inorganic_mat)
                    if #metals > 0 then fn(block, ev, metals) end
                end
            end
        end
    end
end

-- The report's "industry" section: uncovered ore near the fort, by metal:
-- {ores = {IRON = {tiles = n, ore = 'HEMATITE'}, ...}}.
function survey()
    local a = area()
    if not a then return {ores = {}, ore_stock = 0} end
    local ores = {}
    each_vein(a, function(block, ev, metals)
        local p = block.map_pos
        local n = 0
        for x = 0, 15 do
            for y = 0, 15 do
                if dfhack.maps.getTileAssignment(ev.tile_bitmask, x, y)
                        and not block.designation[x][y].hidden and is_wall(p.x + x, p.y + y, p.z) then
                    n = n + 1
                end
            end
        end
        if n > 0 then
            local inorg = inorganic(ev.inorganic_mat)
            for _, m in ipairs(metals) do
                local o = ores[m] or {tiles = 0}
                o.tiles = o.tiles + n
                o.ore = o.ore or (inorg and inorg.id)
                ores[m] = o
            end
        end
    end)
    -- ore already dug and lying about (the smelter's next work), by ore:
    -- {MAGNETITE = {n = 40, metals = {'IRON'}}}
    local stock, by_ore = 0, {}
    pcall(function()
        for _, item in ipairs(df.global.world.items.other.BOULDER) do
            local f = item.flags
            if item:getMaterial() == 0 and not (f.forbid or f.garbage_collect or f.removed or f.trader
                                                or f.in_job) then
                local metals = metals_of(item:getMaterialIndex())
                if #metals > 0 then
                    stock = stock + 1
                    local inorg = inorganic(item:getMaterialIndex())
                    local id = inorg and inorg.id or '?'
                    local o = by_ore[id] or {n = 0, metals = metals}
                    o.n = o.n + 1
                    by_ore[id] = o
                end
            end
        end
    end)
    -- flux stone dug and lying about (limestone, dolomite, marble, chalk,
    -- calcite...: steel takes it), by its reaction class FLUX
    local flux, flux_kind = 0, {}
    pcall(function()
        for _, item in ipairs(df.global.world.items.other.BOULDER) do
            local f = item.flags
            if item:getMaterial() == 0 and not (f.forbid or f.garbage_collect or f.removed or f.trader
                                                or f.in_job) then
                local idx = item:getMaterialIndex()
                if flux_kind[idx] == nil then
                    flux_kind[idx] = false
                    local inorg = inorganic(idx)
                    pcall(function()
                        for _, rc in ipairs(inorg.material.reaction_class) do
                            local v = type(rc) == 'string' and rc or rc.value
                            if v == 'FLUX' then flux_kind[idx] = true end
                        end
                    end)
                end
                if flux_kind[idx] then flux = flux + 1 end
            end
        end
    end)
    return {ores = ores, ore_stock = stock, ore_stock_by = by_ore, flux_stock = flux}
end

local function vein_at(x, y, z)
    local block = dfhack.maps.getTileBlock(x, y, z)
    if not block then return nil end
    for _, ev in ipairs(block.block_events) do
        if df.block_square_event_mineralst:is_instance(ev)
                and dfhack.maps.getTileAssignment(ev.tile_bitmask, x & 15, y & 15) then
            return ev.inorganic_mat
        end
    end
end

-- Safe to dig: solid rock or the vein around it, or the fort's own dug,
-- dry, roofed tiles; nothing wet, hot, aquifer, cavern or open to the sky.
local function warm(x, y, z)
    local block = dfhack.maps.getTileBlock(x, y, z)
    local ok, t = pcall(function() return block.temperature_1[x & 15][y & 15] end)
    return ok and t ~= nil and t >= 10075          -- DF cancels digging in warm stone
end

local function safe(x, y, z)
    if warm(x, y, z) then return false end
    -- (0.105.40b) never raw adamantine, the spire or the underworld, nor beside them
    if U.dig_forbidden(x, y, z) then return false end
    for dz = -1, 1 do
        for dy = -1, 1 do
            for dx = -1, 1 do
                local d = dfhack.maps.getTileFlags(x + dx, y + dy, z + dz)
                if not d then return false end
                if d.flow_size > 0 or d.water_table or d.feature_global or d.feature_local then return false end
                if d.outside then return false end
            end
        end
    end
    return true
end

local function walkable(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    local a = tt and df.tiletype.attrs[tt]
    if not a then return false end
    local shape = df.tiletype_shape.attrs[a.shape]
    return shape and shape.walkable == true
end

-- Mark up to `count` tiles of a vein of `metal`'s ore for digging, starting
-- from an uncovered tile beside ground the dwarves walk on, nearest the fort.
-- (0.104.0, map safety) The AI's levels (projects, finished or not), so a
-- vein is never followed into a room's walls or a level still to be dug.
local function project_areas()
    local B = reqscript('ai-builder')
    local ok, areas = pcall(function() return B.level_areas() end)
    if ok and type(areas) == 'table' then return areas end
    areas = {}
    pcall(function()
        for _, p in ipairs(B.load_projects().list) do
            if p.area then table.insert(areas, p.area) end
        end
    end)
    return areas
end

-- (0.104.19) A wall that belongs to a room, whoever dug it: smoothed, or
-- within ROOM_GUARD tiles of a building (a bed, door, table, workshop) or a
-- zone on its level. The quarry and vein mining never dig such a wall
-- (Enxah: the quarry, picking the wall nearest the fort's middle every few
-- days, opened the bedrooms into one hall).
ROOM_GUARD = 2

local function smoothed(x, y, z)
    local ok, sp = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        local a = tt and df.tiletype.attrs[tt]
        return a and df.tiletype_special[a.special]
    end)
    return ok and (sp == 'SMOOTH' or sp == 'SMOOTH_DEAD')
end

function room_wall(x, y, z)
    if smoothed(x, y, z) then return true end
    for dy = -ROOM_GUARD, ROOM_GUARD do
        for dx = -ROOM_GUARD, ROOM_GUARD do
            local _, occ = dfhack.maps.getTileFlags(x + dx, y + dy, z)
            if occ and occ.building ~= df.tile_building_occ.None then return true end
            local okz, zs = pcall(function() return dfhack.buildings.findCivzonesAt(xyz2pos(x + dx, y + dy, z)) end)
            if okz and zs and #zs > 0 then return true end
        end
    end
    return false
end

local function by_levels(x, y, z, areas)
    for _, a in ipairs(areas) do
        if a.z == z and x >= a.x1 - 2 and x <= a.x2 + 2 and y >= a.y1 - 2 and y <= a.y2 + 2 then return true end
    end
    return false
end

-- (0.105.9) A drift to a vein: searched back from the metal's vein tiles
-- (each well clear of the AI's levels, as a vein followed must be), through
-- natural wall that is safe to dig, never inside a level's area or within 1
-- tile of one, never a room's wall, along a level only (4 ways, so the
-- tunnel is a plain corridor), until a wall tile beside ground the citizens
-- walk on: that tile opens the drift. {path = {entry ... last rock}, vein,
-- mat} or nil. The vein tiles may be hidden: a drift is how a fort finds ore.
DRIFT_MAX = 30          -- tiles of rock to the vein at most
DRIFT_VISIT_MAX = 2500  -- tiles looked at in one search (each checks its 3x3x3 for safety)
DRIFT_SEEDS_MAX = 400   -- vein tiles it starts from, nearest the fort first
DRIFT_RETRY_TICKS = 7 * 1200   -- a search that found nothing isn't repeated for a week
DRIFT_FAILED = {}       -- metal -> absolute tick of the last empty search

local function abs_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or nil
end

local function near_levels(x, y, z, areas, m)
    for _, a in ipairs(areas) do
        if a.z == z and x >= a.x1 - m and x <= a.x2 + m and y >= a.y1 - m and y <= a.y2 + m then return true end
    end
    return false
end

function find_drift(a, metal, areas, groups, zs)
    local now = abs_tick()
    local last = DRIFT_FAILED[metal]
    if now and last and now >= last and now - last < DRIFT_RETRY_TICKS then return nil end
    local seen, queue, head = {}, {}, 1
    local function k(x, y, z) return x .. ',' .. y .. ',' .. z end
    local seeds = {}
    each_vein(a, function(block, ev, metals)
        local has = false
        for _, m in ipairs(metals) do if m == metal then has = true end end
        if not has then return end
        local p = block.map_pos
        for x = 0, 15 do
            for y = 0, 15 do
                local tx, ty = p.x + x, p.y + y
                -- (review) only on levels where citizens stand: elsewhere no
                -- drift can open onto the fort, and the search budget is spent
                if (not zs or zs[p.z]) and dfhack.maps.getTileAssignment(ev.tile_bitmask, x, y)
                        and not near_levels(tx, ty, p.z, areas, 2) then
                    table.insert(seeds, {x = tx, y = ty, z = p.z, mat = ev.inorganic_mat,
                                         d = math.abs(tx - a.cx) + math.abs(ty - a.cy) + 3 * math.abs(p.z - a.cz)})
                end
            end
        end
    end)
    table.sort(seeds, function(p1, p2) return p1.d < p2.d end)
    for i = 1, math.min(#seeds, DRIFT_SEEDS_MAX) do
        local t = seeds[i]
        local kk = k(t.x, t.y, t.z)
        if not seen[kk] and is_wall(t.x, t.y, t.z) and safe(t.x, t.y, t.z) and not room_wall(t.x, t.y, t.z) then
            seen[kk] = {d = 0, mat = t.mat}
            table.insert(queue, {x = t.x, y = t.y, z = t.z})
        end
    end
    local function opens(x, y, z)
        for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
            local nx, ny = x + d[1], y + d[2]
            local fl = dfhack.maps.getTileFlags(nx, ny, z)
            if fl and not fl.hidden and walkable(nx, ny, z) then
                local g = dfhack.maps.getWalkableGroup(xyz2pos(nx, ny, z))
                if g and groups[g] then return true end
            end
        end
        return false
    end
    while head <= #queue and head <= DRIFT_VISIT_MAX do
        local t = queue[head]
        head = head + 1
        local st = seen[k(t.x, t.y, t.z)]
        -- a vein tile itself beside the fort was the ordinary case (not here)
        if st.d > 0 and opens(t.x, t.y, t.z) then
            local path, c = {}, st
            local cx, cy = t.x, t.y
            while c and c.d > 0 do
                table.insert(path, {x = cx, y = cy, z = t.z})
                cx, cy = c.px, c.py
                c = seen[k(cx, cy, t.z)]
            end
            return {path = path, vein = {x = cx, y = cy, z = t.z}, mat = c and c.mat}
        end
        if st.d < DRIFT_MAX then
            for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
                local nx, ny = t.x + d[1], t.y + d[2]
                local nk = k(nx, ny, t.z)
                if not seen[nk] and is_wall(nx, ny, t.z) then
                    local fl = dfhack.maps.getTileFlags(nx, ny, t.z)
                    -- the opening tile may stand next to a level (it opens
                    -- onto the fort); the rest keeps a wall between.
                    -- (the cheap checks first: safe and room_wall read ~50 tiles)
                    -- never inside a level; within 1 tile of one only as the
                    -- drift's opening (opens is read only for those)
                    local place
                    if near_levels(nx, ny, t.z, areas, 0) then place = false
                    elseif near_levels(nx, ny, t.z, areas, 1) then place = opens(nx, ny, t.z)
                    else place = true end
                    -- (review) a tile already marked for digging is passed
                    -- through: a drift not dug yet is found again, not a second beside it
                    if fl and place and safe(nx, ny, t.z) and not room_wall(nx, ny, t.z) then
                        seen[nk] = {d = st.d + 1, px = t.x, py = t.y}
                        table.insert(queue, {x = nx, y = ny, z = t.z})
                    else
                        seen[nk] = {d = math.huge}       -- (looked at: not dug)
                    end
                end
            end
        end
    end
    if now then DRIFT_FAILED[metal] = now end
    return nil
end

function mine(metal, count, dry_run)
    local a = area()
    if not a then return {ok = false, error = 'no citizens'} end
    count = math.max(1, math.min(VEIN_MAX, count or VEIN_MAX))
    local areas = project_areas()
    local groups = {}
    for _, p in ipairs(reqscript('ai-builder').citizen_positions()) do
        local g = dfhack.maps.getWalkableGroup(xyz2pos(p.x, p.y, p.z))
        if g and g ~= 0 then groups[g] = true end
    end
    local best, best_d, best_mat
    each_vein(a, function(block, ev, metals)
        local has = false
        for _, m in ipairs(metals) do if m == metal then has = true end end
        if not has then return end
        local p = block.map_pos
        for x = 0, 15 do
            for y = 0, 15 do
                local tx, ty = p.x + x, p.y + y
                if dfhack.maps.getTileAssignment(ev.tile_bitmask, x, y) and not block.designation[x][y].hidden
                        and block.designation[x][y].dig == df.tile_dig_designation.No and is_wall(tx, ty, p.z) then
                    -- uncovered from a walkable tile the citizens can reach
                    local reach = false
                    for dy = -1, 1 do
                        for dx = -1, 1 do
                            if (dx ~= 0 or dy ~= 0) and walkable(tx + dx, ty + dy, p.z) then
                                local g = dfhack.maps.getWalkableGroup(xyz2pos(tx + dx, ty + dy, p.z))
                                if g and groups[g] then reach = true end
                            end
                        end
                    end
                    local d = math.abs(tx - a.cx) + math.abs(ty - a.cy) + 3 * math.abs(p.z - a.cz)
                    if reach and safe(tx, ty, p.z) and not by_levels(tx, ty, p.z, areas) and not room_wall(tx, ty, p.z)
                            and (not best_d or d < best_d) then
                        best, best_d, best_mat = {x = tx, y = ty, z = p.z}, d, ev.inorganic_mat
                    end
                end
            end
        end
    end)
    local drift
    if not best then
        -- (0.105.9) every uncovered vein lies in the walls of the AI's own
        -- levels (the six forts, y257: 29-30 refusals each, 0 veins ever
        -- mined): a drift, a 1-wide tunnel through plain rock from the fort
        -- to the nearest vein (hidden or not), then the vein
        local zs = {}
        for _, p in ipairs(reqscript('ai-builder').citizen_positions()) do zs[p.z] = true end
        drift = find_drift(a, metal, areas, groups, zs)
        if drift then best, best_mat = drift.vein, drift.mat end
    end
    if not best then
        return {ok = false, rejected = true,
                error = ('no uncovered %s ore the dwarves can reach safely, and no vein within %d tiles '
                         .. 'of the fort through safe rock'):format(metal:lower(), DRIFT_MAX)}
    end
    -- follow the vein (same stone, same level), safe tiles only
    local marked, seen, queue, head = {}, {}, {best}, 1
    seen[best.x .. ',' .. best.y] = true
    if drift then
        for _, t in ipairs(drift.path) do
            table.insert(marked, t)
            seen[t.x .. ',' .. t.y] = true
        end
        count = count + #drift.path
    end
    while head <= #queue and #marked < count do
        local t = queue[head]
        head = head + 1
        table.insert(marked, t)
        for dy = -1, 1 do
            for dx = -1, 1 do
                local nx, ny = t.x + dx, t.y + dy
                local k = nx .. ',' .. ny
                if not seen[k] then
                    seen[k] = true
                    if vein_at(nx, ny, t.z) == best_mat and is_wall(nx, ny, t.z) and safe(nx, ny, t.z)
                            and not by_levels(nx, ny, t.z, areas) and not room_wall(nx, ny, t.z) then
                        table.insert(queue, {x = nx, y = ny, z = t.z})
                    end
                end
            end
        end
    end
    local inorg = inorganic(best_mat)
    local out = {ok = true, metal = metal, ore = inorg and inorg.id or nil, tiles = #marked,
                 x = best.x, y = best.y, z = best.z, dry_run = dry_run or nil,
                 drift = drift and #drift.path or nil,
                 drift_from = drift and drift.path[1] or nil}
    -- (0.105.40b) the dig guard once more over what is marked (the vein's own
    -- stone too: a deep special one is never mined)
    if U.is_deep_inorganic(best_mat) then
        return {ok = false, rejected = true, error = ('the %s vein found is raw adamantine: left alone: it guards the underworld'):format(metal:lower())}
    end
    local why = U.dig_check_tiles(marked, nil, (not dry_run) and 'mine_ore' or nil)
    if why then
        return {ok = false, rejected = true, error = 'a tile of the vein is ' .. why .. ': left alone: it guards the underworld'}
    end
    if dry_run then return out end
    for _, t in ipairs(marked) do
        local d = dfhack.maps.getTileFlags(t.x, t.y, t.z)
        d.dig = df.tile_dig_designation.Default
        local block = dfhack.maps.getTileBlock(t.x, t.y, t.z)
        if block then block.flags.designated = true end
    end
    return out
end

-- --- a quarry: ordinary stone for the masons -------------------------------------

-- When every boulder in the fort is "economic" (ores, flux, coal...: kept
-- from ordinary jobs), the masons and crafters stand idle (region2, y52).
-- A small chamber is dug into a wall of ordinary stone beside ground the
-- dwarves walk on: each tile dug gives a boulder. Away from the AI's levels
-- (their walls are their rooms), never next to water, magma, an aquifer, a
-- cavern or open sky (the same check as ore veins).
QUARRY_MAX = 30
QUARRY_REACH = 3          -- tiles from the first one (a chamber, not a tunnel)
QUARRY_SCAN_MAX = 200000  -- (0.105.33 review) floor tiles read at most looking for the wall

local function economic(idx)
    local ok, v = pcall(function()
        local e = df.global.plotinfo.economic_stone
        return idx < #e and e[idx] and e[idx] ~= 0
    end)
    return ok and v or false
end

-- The stone of a natural wall tile: the vein there if any, else the
-- geological layer. Its inorganic index, or nil.
function stone_at(x, y, z)
    local v = vein_at(x, y, z)
    if v then return v end
    local ok, idx = pcall(function()
        local block = dfhack.maps.getTileBlock(x, y, z)
        local des = block.designation[x & 15][y & 15]
        local rx, ry = dfhack.maps.getTileBiomeRgn(x, y, z)
        if type(rx) == 'table' or type(rx) == 'userdata' then rx, ry = rx.x, rx.y end
        local okr, region = pcall(dfhack.maps.getRegionBiome, rx, ry)
        if not okr or not region then region = dfhack.maps.getRegionBiome(xy2pos(rx, ry)) end
        local biome = df.world_geo_biome.find(region.geo_index)
        return biome.layers[des.geolayer_index].mat_index
    end)
    return ok and idx or nil
end

-- Pure: may this stone be quarried? ordinary (not economic), not an ore.
function quarry_stone(idx, is_economic, is_ore)
    return idx ~= nil and not is_economic and not is_ore
end

-- (0.104.122) the chambers marked lately: Teacheroar's quarry marked the same
-- 8 kaolinite tiles at x71 y66 z166 three times in six hours (the marks went
-- undug), so no stone came. A spot tried is left alone for QUARRY_FORGET_DAYS.
QUARRY_FORGET_DAYS = 56
QUARRY_KEY = 'ai-overseer/quarry/tried'

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or nil
end

function quarry_tried()
    local out, now = {}, now_tick()
    for _, e in ipairs(U.site_get(QUARRY_KEY, {})) do
        if type(e) == 'table' and e.x and e.y and e.z and e.tick and now
                and now - e.tick >= 0 and now - e.tick < QUARRY_FORGET_DAYS * 1200 then
            table.insert(out, e)
        end
    end
    return out
end

local function remember_quarry(spot, tried)
    local now = now_tick()
    if not now then return end
    local list = {}
    for _, e in ipairs(tried) do table.insert(list, e) end
    table.insert(list, {x = spot.x, y = spot.y, z = spot.z, tick = now})
    while #list > 12 do table.remove(list, 1) end
    U.site_put(QUARRY_KEY, list)
end

local function tried_near(x, y, z, tried)
    for _, e in ipairs(tried) do
        if e.z == z and math.abs(x - e.x) <= QUARRY_REACH + 1 and math.abs(y - e.y) <= QUARRY_REACH + 1 then
            return true
        end
    end
    return false
end

local function near_levels(x, y, z, areas)
    for _, a in ipairs(areas) do
        if a.z == z and x >= a.x1 - 2 and x <= a.x2 + 2 and y >= a.y1 - 2 and y <= a.y2 + 2 then return true end
    end
    return false
end

function quarry(count, dry_run)
    local a = area()
    if not a then return {ok = false, error = 'no citizens'} end
    count = math.max(1, math.min(QUARRY_MAX, count or QUARRY_MAX))
    local areas = project_areas()
    local tried = quarry_tried()
    local groups = {}
    for _, p in ipairs(reqscript('ai-builder').citizen_positions()) do
        local g = dfhack.maps.getWalkableGroup(xyz2pos(p.x, p.y, p.z))
        if g and g ~= 0 then groups[g] = true end
    end
    local function ok_tile(x, y, z)
        if not is_wall(x, y, z) then return false end
        local d = dfhack.maps.getTileFlags(x, y, z)
        if not d or d.hidden or d.dig ~= df.tile_dig_designation.No then return false end
        local tt = dfhack.maps.getTileType(x, y, z)
        local at = tt and df.tiletype.attrs[tt]
        local mat = at and df.tiletype_material[at.material]
        if mat ~= 'STONE' and mat ~= 'MINERAL' then return false end      -- natural rock only
        if near_levels(x, y, z, areas) or not safe(x, y, z) then return false end
        if room_wall(x, y, z) then return false end          -- (0.104.19) never a room's wall
        if tried_near(x, y, z, tried) then return false end   -- (0.104.122) marked lately, never dug
        local idx = stone_at(x, y, z)
        local inorg = idx and inorganic(idx)
        return inorg ~= nil and quarry_stone(idx, economic(idx), #metals_of(idx) > 0), idx
    end
    -- (0.105.33 review) outward from the citizens' middle, nearest first,
    -- stopping once no nearer wall can come: the old scan read every tile of
    -- the citizens' box + 40 and 12 levels down (millions of tiles in one
    -- action, seconds of frozen game) to keep the nearest. A floor tile at
    -- distance D has its walls at D-1..D+1, so past best_d + 1 nothing wins.
    -- QUARRY_SCAN_MAX caps the floor tiles read when no wall is found.
    local best, best_d, best_idx
    local function try_floor(x, y, z)
        if not walkable(x, y, z) then return end
        local g = dfhack.maps.getWalkableGroup(xyz2pos(x, y, z))
        if not (g and groups[g]) then return end
        for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
            local tx, ty = x + d[1], y + d[2]
            local dist = math.abs(tx - a.cx) + math.abs(ty - a.cy) + 3 * math.abs(z - a.cz)
            if not best_d or dist < best_d then
                local good, idx = ok_tile(tx, ty, z)
                if good then best, best_d, best_idx = {x = tx, y = ty, z = z}, dist, idx end
            end
        end
    end
    local dx_max = math.max(math.abs(a.x1 - a.cx), math.abs(a.x2 - a.cx))
    local dy_max = math.max(math.abs(a.y1 - a.cy), math.abs(a.y2 - a.cy))
    local dz_max = math.max(math.abs(a.z1 - a.cz), math.abs(a.z2 - a.cz))
    local read = 0
    for D = 0, dx_max + dy_max + 3 * dz_max do
        if (best_d and D > best_d + 1) or read >= QUARRY_SCAN_MAX then break end
        for dz = 0, math.min(dz_max, D // 3) do
            local r = D - 3 * dz
            for _, z in ipairs(dz == 0 and {a.cz} or {a.cz - dz, a.cz + dz}) do
                if z >= a.z1 and z <= a.z2 then
                    for i = math.max(-r, a.x1 - a.cx), math.min(r, a.x2 - a.cx) do
                        local j = r - math.abs(i)
                        local x = a.cx + i
                        for _, y in ipairs(j == 0 and {a.cy} or {a.cy - j, a.cy + j}) do
                            if y >= a.y1 and y <= a.y2 then
                                read = read + 1
                                try_floor(x, y, z)
                            end
                        end
                    end
                end
            end
        end
    end
    if not best then
        return {ok = false, rejected = true,
                error = 'no wall of ordinary (non-economic) stone beside the dwarves\' ground, away from the levels'
                        .. (#tried > 0 and (' (%d spot(s) marked lately left alone)'):format(#tried) or '')}
    end
    local marked, seen, queue, head = {}, {}, {best}, 1
    seen[best.x .. ',' .. best.y] = true
    while head <= #queue and #marked < count do
        local t = queue[head]
        head = head + 1
        table.insert(marked, t)
        for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
            local nx, ny = t.x + d[1], t.y + d[2]
            local k = nx .. ',' .. ny
            if not seen[k] and math.abs(nx - best.x) <= QUARRY_REACH and math.abs(ny - best.y) <= QUARRY_REACH then
                seen[k] = true
                local good, idx = ok_tile(nx, ny, t.z)
                if good and idx == best_idx then table.insert(queue, {x = nx, y = ny, z = t.z}) end
            end
        end
    end
    local inorg = inorganic(best_idx)
    local out = {ok = true, stone = inorg and inorg.id or nil, tiles = #marked, x = best.x, y = best.y, z = best.z,
                 dry_run = dry_run or nil}
    -- (0.105.40b) the dig guard once more over what is marked
    local why = U.dig_check_tiles(marked, nil, (not dry_run) and 'quarry' or nil)
    if why then
        return {ok = false, rejected = true, error = 'a tile of the quarry is ' .. why .. ': left alone: it guards the underworld'}
    end
    if dry_run then return out end
    for _, t in ipairs(marked) do
        local d = dfhack.maps.getTileFlags(t.x, t.y, t.z)
        d.dig = df.tile_dig_designation.Default
        local block = dfhack.maps.getTileBlock(t.x, t.y, t.z)
        if block then block.flags.designated = true end
    end
    remember_quarry(best, tried)
    out.tried = #tried > 0 and #tried or nil
    return out
end
