-- Building projects for the AI overseer: finds a safe place for a new level
-- around the main staircase, digs it with Quickfort, then furnishes it.
--
-- The AI only ever names a level kind and a size; everything about WHERE is
-- decided here, and every tile is checked against the real map (including
-- hidden tiles) for aquifers, liquids, caverns and the surface first.
-- See docs/building.md.
--@ module = true

local layouts = reqscript('ai-layouts')

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
local function ez(z) return z + OFFSET end
KEEP_CLOSED_PROJECTS = 20  -- finished/cancelled projects kept in the save

---------------------------------------------------------------------------
-- Map access. Everything that reads the game map goes through these few
-- functions, so the tests can swap in a fake map.
---------------------------------------------------------------------------

local NATURAL = {STONE = true, MINERAL = true, SOIL = true, LAVA_STONE = true}

-- {shape=<name>, material=<name>, aquifer, liquid, feature, outside, designated,
--  marked, building} or nil when off the map.
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
        designated = des.dig ~= df.tile_dig_designation.No,
        -- "marker only" (blueprint) designations: dwarves won't dig them
        marked = occ.dig_marked,
        smoothed = df.tiletype_special[attrs.special] == 'SMOOTH',
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
local CACHE = nil
local function info(x, y, z)
    if not CACHE then return tile_info(x, y, z) end
    local k = (z * 4096 + y) * 4096 + x
    local v = CACHE[k]
    if v == nil then
        v = tile_info(x, y, z) or false
        CACHE[k] = v
    end
    return v or nil
end

local function overlaps(a, b)
    return a.z == b.z and a.x1 <= b.x2 and b.x1 <= a.x2 and a.y1 <= b.y2 and b.y1 <= a.y2
end

local function has(set, x, y)
    local col = set[x]
    return col ~= nil and col[y] == true
end

local function add(set, x, y)
    set[x] = set[x] or {}
    set[x][y] = true
end

-- A "site" puts a layout's (0, 0) at anchor (ax, ay) on level z, plus
-- extra dug tiles (a connecting corridor; the layout's centre when it isn't
-- a staircase). Checks every dug tile and a 1-tile border on that level.
--   skip:   relative tile not checked at all (the staircase, when centred on it)
--   exempt: function(x, y, t) -> true for border tiles allowed to be open
--           (where the corridor joins the fort's existing space)
-- Returns ok, reason, area.
function check_site(L, extra, ax, ay, z, reserved, skip, exempt)
    local w, h = map_size()
    local b = L.bounds
    local x1, y1, x2, y2 = b.x1, b.y1, b.x2, b.y2
    for x, col in pairs(extra) do
        for y in pairs(col) do
            x1, x2, y1, y2 = math.min(x1, x), math.max(x2, x), math.min(y1, y), math.max(y2, y)
        end
    end
    local area = {x1 = ax + x1 - 1, y1 = ay + y1 - 1, x2 = ax + x2 + 1, y2 = ay + y2 + 1, z = z}
    if area.x1 < 1 or area.y1 < 1 or area.x2 > w - 2 or area.y2 > h - 2 then
        return false, 'too close to the map edge'
    end
    for _, r in ipairs(reserved or {}) do
        if overlaps(area, r) then return false, 'overlaps another AI project' end
    end
    local function dug(x, y) return has(L.tiles, x, y) or has(extra, x, y) end
    local function check(x, y)
        if skip and x == skip.x and y == skip.y then return true end
        local t = info(ax + x, ay + y, z)
        local ok, why = natural_wall(t)
        if not ok and not dug(x, y) and exempt and exempt(ax + x, ay + y, t) then ok = true end
        -- farm plots: the tiles under them must be soil (dug soil leaves soil floor)
        if ok and L.soil and has(L.soil, x, y) and t.material ~= 'SOIL' then
            ok, why = false, 'not soil (crops need soil)'
        end
        if not ok then return false, ('%s at x%d y%d z%d'):format(why, ax + x, ay + y, ez(z)) end
        return true
    end
    -- dug tiles first (most likely to fail), then their borders
    local function each_dug(fn)
        for _, set in ipairs({extra, L.tiles}) do
            for x, col in pairs(set) do
                for y in pairs(col) do
                    local ok, why = fn(x, y)
                    if not ok then return false, why end
                end
            end
        end
        return true
    end
    local ok, why = each_dug(check)
    if not ok then return false, why end
    -- Water, magma or aquifer directly above a tile makes it "damp" stone,
    -- and the game cancels digging there (and it would be unsafe anyway).
    ok, why = each_dug(function(x, y)
        local up = info(ax + x, ay + y, z + 1)
        if up and (up.aquifer or up.liquid) then
            return false, ('%s directly above x%d y%d z%d'):format(
                up.aquifer and 'aquifer' or 'water or magma', ax + x, ay + y, ez(z))
        end
        return true
    end)
    if not ok then return false, why end
    local seen = {}
    ok, why = each_dug(function(x, y)
        for dx = -1, 1 do
            for dy = -1, 1 do
                local nx, ny = x + dx, y + dy
                if not dug(nx, ny) and not has(seen, nx, ny) then
                    add(seen, nx, ny)
                    local good, reason = check(nx, ny)
                    if not good then return false, reason end
                end
            end
        end
        return true
    end)
    if not ok then return false, why end
    return true, nil, area
end

-- A layout centred on a staircase at (sx, sy): the stair tile is not checked.
function check_level(L, sx, sy, z, reserved)
    return check_site(L, {}, sx, sy, z, reserved, {x = 0, y = 0})
end

-- Can the staircase at (sx, sy) be extended from its bottom (zb) down to z?
-- Each new stair tile and its 8 neighbours must be untouched natural wall.
function check_extension(sx, sy, zb, z)
    for zz = zb - 1, z, -1 do
        for dx = -1, 1 do
            for dy = -1, 1 do
                -- on the target level, the hub check covers the neighbours
                if zz ~= z or (dx == 0 and dy == 0) then
                    local ok, why = natural_wall(info(sx + dx, sy + dy, zz))
                    if ok and dx == 0 and dy == 0 then
                        local up = info(sx, sy, zz + 1)
                        if up and (up.aquifer or up.liquid) then ok, why = false, 'water or aquifer above' end
                    end
                    if not ok then
                        return false, ('stairs down to z%d: %s at x%d y%d z%d'):format(
                            ez(z), why, sx + dx, sy + dy, ez(zz))
                    end
                end
            end
        end
    end
    return true
end

---------------------------------------------------------------------------
-- Staircases
---------------------------------------------------------------------------

local GOES_UP = {STAIR_UP = true, STAIR_UPDOWN = true}
local GOES_DOWN = {STAIR_DOWN = true, STAIR_UPDOWN = true}

-- The stretch of stairs through (x, y, z) that a dwarf can actually walk:
-- each step needs an up-going stair below a down-going one.
function stair_run(x, y, z)
    local zt, zb = z, z
    while GOES_UP[stair_shape(x, y, zt)] and GOES_DOWN[stair_shape(x, y, zt + 1)] do zt = zt + 1 end
    while zb > 0 and GOES_DOWN[stair_shape(x, y, zb)] and GOES_UP[stair_shape(x, y, zb - 1)] do zb = zb - 1 end
    return zt, zb
end

-- The most-used staircases where the dwarves live: stair columns ranked by
-- how many of the busiest levels they reach, then by walkable length.
function find_stairs(n)
    local pos = citizen_positions()
    if #pos == 0 then return nil, 'no citizens' end
    local by_z, x1, y1, x2, y2 = {}, math.huge, math.huge, -math.huge, -math.huge
    for _, p in ipairs(pos) do
        by_z[p.z] = (by_z[p.z] or 0) + 1
        x1, x2 = math.min(x1, p.x), math.max(x2, p.x)
        y1, y2 = math.min(y1, p.y), math.max(y2, p.y)
    end
    local levels = {}
    for z, c in pairs(by_z) do table.insert(levels, {z = z, n = c}) end
    table.sort(levels, function(a, b) return a.n > b.n or (a.n == b.n and a.z > b.z) end)
    local sample = math.min(STAIR_SAMPLE_LEVELS, #levels)
    local w, h = map_size()
    x1, y1 = math.max(0, x1 - 10), math.max(0, y1 - 10)
    x2, y2 = math.min(w - 1, x2 + 10), math.min(h - 1, y2 + 10)
    local counts = {}
    for i = 1, sample do
        local z = levels[i].z
        for x = x1, x2 do
            for y = y1, y2 do
                if stair_shape(x, y, z) then
                    local k = x * 100000 + y
                    counts[k] = (counts[k] or 0) + 1
                end
            end
        end
    end
    local stairs = {}
    for k, c in pairs(counts) do
        local sx, sy = k // 100000, k % 100000
        for i = 1, sample do
            if stair_shape(sx, sy, levels[i].z) then
                local zt, zb = stair_run(sx, sy, levels[i].z)
                table.insert(stairs, {x = sx, y = sy, z_top = zt, z_bottom = zb, count = c,
                                      len = zt - zb, k = k, citizen_z = levels[1].z,
                                      bottom_shape = stair_shape(sx, sy, zb)})
                break
            end
        end
    end
    if #stairs == 0 then return nil, 'no staircase found where the dwarves live' end
    table.sort(stairs, function(a, b)
        if a.count ~= b.count then return a.count > b.count end
        if a.len ~= b.len then return a.len > b.len end
        return a.k < b.k
    end)
    local out = {}
    for i = 1, math.min(n or STAIRS_TO_TRY, #stairs) do out[i] = stairs[i] end
    return out
end

-- The single most-used staircase (kept for callers that want just one).
function find_main_stair()
    local stairs, why = find_stairs(1)
    if not stairs then return nil, why end
    return stairs[1]
end

---------------------------------------------------------------------------
-- Choosing a site
---------------------------------------------------------------------------

local DIRS = {{x = 0, y = 1}, {x = 0, y = -1}, {x = 1, y = 0}, {x = -1, y = 0}}

-- Where a corridor travelling in direction d first meets the layout: the
-- layout tile on its centre line nearest the side it comes from.
local function entry_point(L, d)
    local best
    if d.x == 0 then
        for y = L.bounds.y1, L.bounds.y2 do
            if has(L.tiles, 0, y) or y == 0 then
                if best == nil or (d.y > 0 and y < best) or (d.y < 0 and y > best) then best = y end
            end
        end
        return {x = 0, y = best}
    end
    for x = L.bounds.x1, L.bounds.x2 do
        if has(L.tiles, x, 0) or x == 0 then
            if best == nil or (d.x > 0 and x < best) or (d.x < 0 and x > best) then best = x end
        end
    end
    return {x = best, y = 0}
end

local function open_fort_tile(t, x, y, z, group)
    return t and t.shape ~= 'WALL' and not t.liquid and not t.aquifer and not t.feature
        and not t.outside and group ~= 0 and walk_group(x, y, z) == group
end

-- On level z, a site beside the staircase: walk out from the stairs (first
-- through existing fort space, then through new corridor) and put the
-- layout where the corridor ends.
-- The fort's Spacing trait -> the new corridor's length, from the stairs or
-- the edge of the existing fort to the new level:
--   tightly packed (-100): 0 to 8 tiles; 0: 0 to 25 (the old rule);
--   spread far apart (+100): 10 to 25, so the level stands on its own.
-- Extreme (+-200) goes no further than +-100.
function corridor_range(L)
    local sp = math.max(-100, math.min(100, (L.style and L.style.spacing) or 0))
    if sp >= 0 then
        return math.floor(sp / 10), MAX_CORRIDOR
    end
    return 0, MAX_CORRIDOR - math.floor((MAX_CORRIDOR - 8) * -sp / 100 + 0.5)
end

-- The plan's directions first (DF's y grows southward), then the rest of
-- DIRS in their usual order.
local DIR_OF = {north = {x = 0, y = -1}, south = {x = 0, y = 1}, east = {x = 1, y = 0}, west = {x = -1, y = 0}}
function plan_dirs(plan)
    if type(plan) ~= 'table' or type(plan.dirs) ~= 'table' then return DIRS end
    local out, used = {}, {}
    for _, name in ipairs(plan.dirs) do
        local d = DIR_OF[name]
        if d and not used[d.x .. ',' .. d.y] then
            used[d.x .. ',' .. d.y] = true
            table.insert(out, d)
        end
    end
    for _, d in ipairs(DIRS) do
        if not used[d.x .. ',' .. d.y] then table.insert(out, d) end
    end
    return out
end

-- The plan's corridor grammar (see parse_plan in ai-bridge), or nil when the
-- plan has none of it (then corridors are exactly as they always were):
--   avenue 1-3      corridor width (2: one extra row on the +perpendicular
--                   side; 3: one on each side). The first and last tiles stay
--                   1 wide: a doorway at each end, with rock to hang a door
--                   on, and the wide part never brushes the level's walls
--   dogleg          corridors of 4+ tiles jog 2 tiles sideways half way
--   doors           'open' (no doors), 'doored' (the style decides, today's
--                   rule), 'fortified' (a door at both ends of the corridor)
function plan_grammar(plan)
    if type(plan) ~= 'table' then return nil end
    local avenue = math.tointeger(plan.avenue)
    local g = {avenue = (avenue and avenue >= 1 and avenue <= 3) and avenue or 1,
               dogleg = plan.corridors == 'dog-leg',
               doors = (plan.doors == 'open' or plan.doors == 'fortified') and plan.doors or nil}
    if g.avenue == 1 and not g.dogleg and not g.doors then return nil end
    return g
end

-- 90 degrees from direction d (the +perpendicular side).
local function perp(d) return {x = -d.y, y = d.x} end

-- The new corridor's tiles in map coordinates: {x, y, t = direction of
-- travel, step}. Straight, or (side = +-1) jogging 2 tiles that way half way.
-- Returns the tiles and the sideways shift of the corridor's end.
local function corridor_path(stair, d, first, corridor, side)
    local tiles, sx, sy = {}, 0, 0
    local half = side ~= 0 and corridor // 2 or nil
    local p = perp(d)
    for i = 0, corridor - 1 do
        if half and i == half then
            -- the jog: 2 tiles sideways from the last straight tile
            local bx, by = stair.x + d.x * (first + i - 1), stair.y + d.y * (first + i - 1)
            local t = {x = p.x * side, y = p.y * side}
            for k = 1, 2 do
                table.insert(tiles, {x = bx + t.x * k, y = by + t.y * k, t = t, step = i - 1})
            end
            sx, sy = t.x * 2, t.y * 2
        end
        table.insert(tiles, {x = stair.x + d.x * (first + i) + sx, y = stair.y + d.y * (first + i) + sy,
                             t = d, step = i})
    end
    return tiles, sx, sy
end

local function offset_sites(L, stair, z, reserved, try, dirs, grammar)
    local group = walk_group(stair.x, stair.y, z)
    if group == 0 then return nil end
    local shortest, longest = corridor_range(L)
    -- (0.104.107) the plan's own direction (dirs[1]) may take up to
    -- PREFER_SLACK more corridor tiles than another direction before that
    -- one wins: wider corridors made the levels lopsided (2 wide is 1 row off
    -- centre) and a shorter fit the other way always won
    local fallback, fallback_at
    for corridor = shortest, longest do
        if fallback and corridor > fallback_at + PREFER_SLACK then return fallback end
        for di, d in ipairs(dirs or DIRS) do
          if not fallback or (dirs and di == 1) then
            -- existing fort space next to the stairs, in this direction
            local walked = 0
            while walked < MAX_WALK_EXISTING do
                local x, y = stair.x + d.x * (walked + 1), stair.y + d.y * (walked + 1)
                if not open_fort_tile(info(x, y, z), x, y, z, group) then break end
                walked = walked + 1
            end
            local e = entry_point(L, d)
            local first = walked + 1                         -- first new tile, in steps
            -- a dog-leg is tried jogging to the +perpendicular side, then the other
            local sides = (grammar and grammar.dogleg and corridor >= 4) and {1, -1} or {0}
            for _, side in ipairs(sides) do
                local path, sx, sy = corridor_path(stair, d, first, corridor, side)
                local ex, ey = stair.x + d.x * (first + corridor) + sx, stair.y + d.y * (first + corridor) + sy
                local ax, ay = ex - e.x, ey - e.y               -- layout anchor
                local extra = {}
                add(extra, 0, 0)
                local joins = {}                               -- first-step tiles (map coordinates)
                local avenue = grammar and grammar.avenue or 1
                for _, c in ipairs(path) do
                    add(extra, c.x - ax, c.y - ay)
                    if c.step == 0 and c.t == d then table.insert(joins, {x = c.x, y = c.y}) end
                    if avenue > 1 and c.step > 0 and c.step < corridor - 1 then
                        -- the avenue: rows beside the corridor, across its direction of
                        -- travel (not on the first and last tiles: those are doorways)
                        local q = perp(c.t)
                        local wide = avenue == 2 and {1} or {1, -1}
                        for _, k in ipairs(wide) do
                            add(extra, c.x + q.x * k - ax, c.y + q.y * k - ay)
                        end
                    end
                end
                local fx, fy = stair.x + d.x * first, stair.y + d.y * first
                local exempt = function(x, y, t)
                    local near = math.max(math.abs(x - fx), math.abs(y - fy)) <= 1
                    for _, j in ipairs(joins) do
                        if near then break end
                        near = math.max(math.abs(x - j.x), math.abs(y - j.y)) <= 1
                    end
                    return near and open_fort_tile(t, x, y, z, group)
                end
                local ok, why, area = true, nil, nil
                -- a wide or jogging corridor must not run into the level or open
                -- onto it anywhere but around its entry tile
                -- (touching a hall, or the hub the corridor comes in by, is fine: it's
                -- the same open space; touching a room past its door is not)
                local function open_space(nx, ny)
                    if math.max(math.abs(nx - e.x), math.abs(ny - e.y)) <= 1 then return true end
                    if math.abs(e.x) <= 1 and math.abs(e.y) <= 1 and math.abs(nx) <= 1 and math.abs(ny) <= 1 then
                        return true
                    end
                    for _, h in ipairs(L.halls or {}) do
                        if nx >= h.x and nx < h.x + h.w and ny >= h.y and ny < h.y + h.h then return true end
                    end
                    return false
                end
                if grammar and (avenue > 1 or side ~= 0) then
                    for x, col in pairs(extra) do
                        for y in pairs(col) do
                            if ok and not (x == 0 and y == 0) then
                                if has(L.tiles, x, y) then ok, why = false, 'corridor runs into the level' end
                                for dx = -1, 1 do
                                    for dy = -1, 1 do
                                        local nx, ny = x + dx, y + dy
                                        if ok and (has(L.tiles, nx, ny) or (nx == 0 and ny == 0))
                                                and not open_space(nx, ny) then
                                            ok, why = false, 'corridor would open onto the level beside its entry'
                                        end
                                    end
                                end
                            end
                        end
                    end
                end
                if ok then
                    ok, why, area = check_site(L, extra, ax, ay, z, reserved, nil, exempt)
                end
                local function dug(x, y) return (x == 0 and y == 0) or has(L.tiles, x, y) or has(extra, x, y) end
                -- a door needs rock on both sides across the corridor
                local function walled(x, y, t)
                    local q = perp(t)
                    return not dug(x + q.x, y + q.y) and not dug(x - q.x, y - q.y)
                end
                local join = corridor > 0 and {x = fx - ax, y = fy - ay} or nil
                if join and avenue > 1 and not walled(join.x, join.y, d) then join = nil end
                local inner
                if grammar and grammar.doors == 'fortified' and corridor >= 2 then
                    local last = path[#path]
                    local ix, iy = last.x - ax, last.y - ay
                    if walled(ix, iy, last.t) then inner = {x = ix, y = iy} end
                end
                local site = try(ok, why, {z = z, extend = false, anchor = {x = ax, y = ay},
                                           extra = extra, area = area,
                                           corridor = corridor + walked + (side ~= 0 and 2 or 0),
                                           -- first new corridor tile, where a fortified fort puts a door
                                           join = join,
                                           -- the plan's doors, and the inner door's tile (fortified)
                                           doors = grammar and grammar.doors or nil, inner = inner})
                if site then
                    if not dirs or di == 1 then return site end
                    if not fallback then fallback, fallback_at = site, corridor end
                    break
                end
            end
          end
        end
    end
    return fallback
end

-- Pick a site. For each staircase (most used first): levels it already
-- passes through, nearest the dwarves first, centred on the stairs or beside
-- them; then levels just below its bottom (the stairs are extended down).
-- Stops after SEARCH_SECONDS with the reasons found so far.
--
-- plan (optional, the overseer's master plan, see parse_plan in ai-bridge):
-- the spine staircase goes first, levels in the elevation band first
-- (nearest the target), the plan's directions first. A first pass tries
-- only the band, for at most PLAN_SHARE of SEARCH_SECONDS, and extends only
-- the spine stair, by at most PLAN_EXTEND levels. If that finds nothing, the
-- ordinary search runs in today's order with its own SEARCH_SECONDS, skipping
-- what the first pass already tried, so a plan never loses a site (the two
-- together stay under the game's 10 s).
-- The site gets in_district = true/false (nil without a band).
PLAN_SHARE = 0.4
PLAN_EXTEND = 3

-- The plan's elevation band as z: {lo, hi, target}, or nil.
local function plan_band(plan)
    if type(plan) ~= 'table' then return nil end
    local lo, hi = math.tointeger(plan.elev_lo), math.tointeger(plan.elev_hi)
    if not lo or not hi or lo > hi then return nil end
    local t = math.tointeger(plan.elev_target) or (lo + (hi - lo) // 2)
    return {lo = lo - OFFSET, hi = hi - OFFSET, target = t - OFFSET}
end

-- Walking areas the citizens are in (empty when unknown).
local function citizen_groups()
    local g = {}
    for _, p in ipairs(citizen_positions()) do
        local n = walk_group(p.x, p.y, p.z)
        if n ~= 0 then g[n] = true end
    end
    return g
end

-- The stair list with the plan's spine first. If the spine isn't one of the
-- listed stairs, look for a staircase there the dwarves can walk to (on
-- their busiest level, then the band from its target outward) and add it.
-- The other stairs always stay, as the fallback.
function spine_first(stairs, plan, band)
    local sp = type(plan) == 'table' and plan.spine or nil
    if type(sp) ~= 'table' then return stairs end
    local sx, sy = math.tointeger(sp.x), math.tointeger(sp.y)
    if not sx or not sy then return stairs end
    local out = {}
    for i, st in ipairs(stairs) do
        if st.x == sx and st.y == sy then
            table.insert(out, st)
            for j, o in ipairs(stairs) do if j ~= i then table.insert(out, o) end end
            return out
        end
    end
    local cz = stairs[1] and stairs[1].citizen_z
    local zs = {}
    if cz then table.insert(zs, cz) end
    if band then
        for d = 0, band.hi - band.lo do
            for _, z in ipairs(d == 0 and {band.target} or {band.target - d, band.target + d}) do
                if z >= band.lo and z <= band.hi then table.insert(zs, z) end
            end
            if band.target - d < band.lo and band.target + d > band.hi then break end
        end
    end
    local _, _, zmax = map_size()
    local groups = citizen_groups()
    local any_group = next(groups) == nil
    for _, z in ipairs(zs) do
        if z >= 0 and (not zmax or z < zmax) and stair_shape(sx, sy, z) then
            local g = walk_group(sx, sy, z)
            if g ~= 0 and (any_group or groups[g]) then
                local zt, zb = stair_run(sx, sy, z)
                table.insert(out, {x = sx, y = sy, z_top = zt, z_bottom = zb, count = 0,
                                   len = zt - zb, k = sx * 100000 + sy, citizen_z = cz or z,
                                   bottom_shape = stair_shape(sx, sy, zb), spine = true})
                for _, o in ipairs(stairs) do table.insert(out, o) end
                return out
            end
        end
    end
    return stairs
end

-- One staircase's levels to try, in order: {z, extend}. Levels it passes
-- through (nearest the dwarves first), then levels below its bottom. With a
-- band: the band's levels first (nearest the target), the rest in that same
-- order after; only_band leaves the rest out.
local function stair_levels(stair, band, only_band, may_extend)
    local through, below = {}, {}
    for z = stair.z_bottom, stair.z_top do table.insert(through, z) end
    table.sort(through, function(a, b)
        return math.abs(a - stair.citizen_z) < math.abs(b - stair.citizen_z)
    end)
    for z = stair.z_bottom - 1, math.max(1, stair.z_bottom - MAX_LEVELS_BELOW), -1 do
        table.insert(below, z)
    end
    local out = {}
    if not band then
        for _, z in ipairs(through) do table.insert(out, {z = z, extend = false}) end
        for _, z in ipairs(below) do table.insert(out, {z = z, extend = true}) end
        return out
    end
    local function inside(z) return z >= band.lo and z <= band.hi end
    local function band_part(list, extend)
        local part = {}
        for _, z in ipairs(list) do if inside(z) then table.insert(part, z) end end
        table.sort(part, function(a, b)
            local da, db = math.abs(a - band.target), math.abs(b - band.target)
            if da ~= db then return da < db end
            return a > b
        end)
        for _, z in ipairs(part) do table.insert(out, {z = z, extend = extend}) end
    end
    band_part(through, false)
    if may_extend ~= false then
        local near = {}
        for _, z in ipairs(below) do
            if may_extend == nil or z >= stair.z_bottom - PLAN_EXTEND then table.insert(near, z) end
        end
        band_part(near, true)
    end
    if not only_band then
        for _, z in ipairs(through) do if not inside(z) then table.insert(out, {z = z, extend = false}) end end
        for _, z in ipairs(below) do if not inside(z) then table.insert(out, {z = z, extend = true}) end end
    end
    return out
end

function choose_site(L, stairs, reserved, plan)
    CACHE = {}
    local started = os.clock()
    local reasons = {centred = {}, beside = {}, below = {}}
    local timed_out = false
    local function note(kind, why, z)
        local list = reasons[kind]
        if #list < 2 then table.insert(list, ('z%d: %s'):format(ez(z), why)) end
    end
    local band = plan_band(plan)
    local dirs = plan_dirs(plan)
    local grammar = plan_grammar(plan)
    stairs = spine_first(stairs, plan, band)
    local found
    local tried = {}
    -- one pass over every staircase; returns true when it ran out of time.
    -- The band pass (first) extends only the spine, a little; the ordinary
    -- pass (second) is today's search, skipping what the band pass tried.
    local function pass(deadline, band_pass)
        local out_of_time = false
        local ok_run, err = pcall(function()
            for i, stair in ipairs(stairs) do
                local levels
                if band_pass then
                    local is_spine = i == 1 and type(plan) == 'table' and type(plan.spine) == 'table'
                        and stair.x == math.tointeger(plan.spine.x) and stair.y == math.tointeger(plan.spine.y)
                    levels = stair_levels(stair, band, true, is_spine and 'near' or false)
                else
                    levels = stair_levels(stair, nil, false)
                end
                for _, lv in ipairs(levels) do
                    local z = lv.z
                    if os.clock() > deadline then out_of_time = true return end
                    local key = ('%d,%d,%d,%s'):format(stair.x, stair.y, z, tostring(lv.extend))
                    if tried[key] then goto continue end
                    tried[key] = band_pass or nil
                    local ok, why, area = check_site(L, {}, stair.x, stair.y, z, reserved, {x = 0, y = 0})
                    if lv.extend then
                        if ok then
                            ok, why = check_extension(stair.x, stair.y, stair.z_bottom, z)
                        end
                        if ok then
                            found = {z = z, extend = true, anchor = {x = stair.x, y = stair.y},
                                     extra = {}, area = area, stair = stair, corridor = 0}
                            return
                        end
                        note('below', why, z)
                    else
                        if ok then
                            found = {z = z, extend = false, anchor = {x = stair.x, y = stair.y},
                                     extra = {}, area = area, stair = stair, corridor = 0}
                            return
                        end
                        note('centred', why, z)
                        local site = TRY_BESIDE and offset_sites(L, stair, z, reserved, function(good, reason, s)
                            if good then return s end
                            note('beside', reason, z)
                            if os.clock() > deadline then out_of_time = true error('timeout') end
                        end, dirs, grammar)
                        if site then
                            site.stair = stair
                            found = site
                            return
                        end
                    end
                    ::continue::
                end
            end
        end)
        if not ok_run and not out_of_time then error(err) end
        return out_of_time
    end
    local ok_all, err = pcall(function()
        if band then
            if pass(started + SEARCH_SECONDS * PLAN_SHARE, true) then
                tried = {}                      -- cut short: the ordinary pass tries everything again
            end
        end
        if not found then timed_out = pass(os.clock() + SEARCH_SECONDS, false) end
    end)
    CACHE = nil
    if not ok_all then error(err) end
    if found then
        if band then found.in_district = found.z >= band.lo and found.z <= band.hi end
        return found
    end
    local tried = {}
    for _, kind in ipairs({'below', 'beside', 'centred'}) do
        for _, w in ipairs(reasons[kind]) do table.insert(tried, w) end
    end
    local head = timed_out and 'no safe level found within the time limit' or
        ('no safe level found near %d staircase(s)'):format(#stairs)
    return nil, head .. ' (' .. table.concat(tried, '; ') .. ')'
end

---------------------------------------------------------------------------
-- Projects, saved with the fort
---------------------------------------------------------------------------

function load_projects()
    local data = dfhack.persistent.getSiteData(PROJECTS_KEY, {next_id = 1, list = {}})
    data.next_id = math.tointeger(data.next_id) or 1
    data.list = type(data.list) == 'table' and data.list or {}
    return data
end

OLD_AREAS_MAX = 600       -- (0.104.19) outlines of levels dropped from the list, kept for safety

function save_projects(data)
    -- keep every open project, and only the most recent closed ones;
    -- (0.104.19) a dropped level's outline is kept (`old_areas`): the quarry
    -- and vein mining stay out of every level the AI ever dug, not only the
    -- last 20 (Enxah: the quarry ate the walls of the older bedroom levels)
    local closed = 0
    data.old_areas = type(data.old_areas) == 'table' and data.old_areas or {}
    for i = #data.list, 1, -1 do
        local p = data.list[i]
        -- (0.104.152, review) a cavern well is never dropped: its shaft gate and
        -- stair lid are run from its project for as long as the well stands
        local cavern_well = p.kind == 'well' and (type(p.shaft_stairs) == 'table' or p.shaft_gate ~= nil)
        if p.phase ~= 'dig' and p.phase ~= 'furnish' and p.phase ~= 'decorate' and not cavern_well then
            closed = closed + 1
            if closed > KEEP_CLOSED_PROJECTS then
                local a = p.area
                if type(a) == 'table' then
                    table.insert(data.old_areas, {x1 = a.x1, y1 = a.y1, x2 = a.x2, y2 = a.y2, z = a.z})
                end
                table.remove(data.list, i)
            end
        end
    end
    while #data.old_areas > OLD_AREAS_MAX do table.remove(data.old_areas, 1) end
    return pcall(dfhack.persistent.saveSiteData, PROJECTS_KEY, data)
end

-- (0.104.19) Every level the AI has dug or is digging: the open and recent
-- projects' areas and the outlines of older ones.
function level_areas()
    local data = load_projects()
    local out = {}
    for _, p in ipairs(data.list) do
        if type(p.area) == 'table' then table.insert(out, p.area) end
    end
    for _, a in ipairs(type(data.old_areas) == 'table' and data.old_areas or {}) do
        table.insert(out, a)
    end
    return out
end

local function open_projects(data)
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
local function quickfort_apply(mode, cells, z, ax, ay, command, dry_run)
    local qf = reqscript('quickfort')
    return qf.apply_blueprint{mode = mode, command = command or 'run', dry_run = dry_run,
                              data = layouts.to_data(cells, z), pos = {x = ax, y = ay, z = 0}}
end

local function stat(stats, name)
    return stats and stats[name] and stats[name].value or 0
end

local function count(tiles)
    local n = 0
    for _, col in pairs(tiles) do for _ in pairs(col) do n = n + 1 end end
    return n
end

-- Designate the stair extension: 'i' on the old bottom if it was an up-only
-- stair, 'i' on the levels between, 'u' on the new level.
local function stair_cells(stair, z)
    local cells = {}
    if stair.bottom_shape == 'STAIR_UP' then
        table.insert(cells, {z = stair.z_bottom, text = 'i'})
    end
    for zz = stair.z_bottom - 1, z + 1, -1 do table.insert(cells, {z = zz, text = 'i'}) end
    table.insert(cells, {z = z, text = 'u'})
    return cells
end

local function undo_dig(dig_cells, stairs, z, anchor, stair)
    pcall(quickfort_apply, 'dig', dig_cells, z, anchor.x, anchor.y, 'undo')
    for _, c in ipairs(stairs or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.text}}, c.z, stair.x, stair.y, 'undo')
    end
end

-- The layout's dig cells plus the site's extra tiles (corridor, centre).
-- (0.104.128) an urgent level dug before the rest: Teacheroar's new hospital
-- sat at 0 of 175 tiles with 260 others waiting for 10 miners, all at the
-- default priority 4. Its tiles are designated one by one at this priority.
URGENT_DIG_PRIORITY = 2

function prioritized(cells, pri)
    local out = {}
    for _, c in ipairs(cells) do
        local w, h = 1, 1
        local ew, eh = tostring(c.text):match('^d%((%d+)x(%d+)%)$')
        if ew then w, h = tonumber(ew), tonumber(eh) end
        if ew or c.text == 'd' then
            for dx = 0, w - 1 do
                for dy = 0, h - 1 do table.insert(out, {x = c.x + dx, y = c.y + dy, text = 'd' .. pri}) end
            end
        else
            table.insert(out, c)
        end
    end
    return out
end

local function site_dig_cells(L, extra)
    local cells = {}
    for _, c in ipairs(L.dig) do table.insert(cells, c) end
    for x, col in pairs(extra) do
        for y in pairs(col) do table.insert(cells, {x = x, y = y, text = 'd'}) end
    end
    return cells
end

-- A fortified fort closes each new level off with a door where its corridor
-- leaves the existing fort (only when there is a new corridor to put it in).
-- The plan's doors can say otherwise: 'open' puts no door there, 'fortified'
-- puts one there and a second where the corridor meets the level (site.inner).
function entry_door(L, site, style)
    local build, furniture = {}, {}
    for _, c in ipairs(L.build) do table.insert(build, c) end
    for k, v in pairs(L.furniture) do furniture[k] = v end
    local want = type(style) == 'table' and style.entry_door
    if site.doors == 'open' then want = false end
    if site.doors == 'fortified' then want = true end
    local doors = {}
    if want and site.join then table.insert(doors, site.join) end
    if site.doors == 'fortified' and site.inner then table.insert(doors, site.inner) end
    for _, d in ipairs(doors) do
        table.insert(build, {x = d.x, y = d.y, text = 'd'})
        furniture.Door = (furniture.Door or 0) + 1
    end
    return build, furniture
end

-- Smoothing and engraving: only on this level's own new tiles and on rock
-- walls that were untouched natural rock when the site was checked (never on
-- the player's existing rooms), and never on floors where furniture or a
-- workshop will stand.
function decoration_cells(L, site, build)
    local a, z = site.anchor, site.z
    local covered = {}
    for _, c in ipairs(build) do
        local r = (#c.text >= 2 and c.text:sub(1, 1) == 'w') and 1 or 0   -- workshops are 3x3
        for dx = -r, r do
            for dy = -r, r do
                covered[(c.x + dx) .. ',' .. (c.y + dy)] = true
            end
        end
    end
    local function ours(x, y)
        return (L.tiles[x] and L.tiles[x][y]) or (site.extra[x] and site.extra[x][y])
    end
    local function keep(c)
        if covered[c.x .. ',' .. c.y] then return false end
        if ours(c.x, c.y) then return true end
        return natural_wall(info(a.x + c.x, a.y + c.y, z)) == true
    end
    local out = {smooth = {}, engrave = {}}
    for _, phase in ipairs({'smooth', 'engrave'}) do
        for _, c in ipairs(L[phase] or {}) do
            if keep(c) then table.insert(out[phase], c) end
        end
    end
    return out
end

-- params: kind + layout params (rooms, room_size, tables, piles, shops).
-- dry_run: find the site and check it with Quickfort, but change nothing.
function start_project(params, now, dry_run)
    OFFSET = elevation_offset()
    local kind = params.kind
    local L, err = layouts.make(kind, params)
    if not L then return {ok = false, rejected = true, error = err} end
    local data = load_projects()
    local open = open_projects(data)
    -- (a farm level gets one more slot: food comes before everything else)
    -- (urgent: what a well or a strange mood is waiting for; a dwarf's
    -- sanity or the fort's water doesn't wait for a bedroom level)
    -- (0.104.12) two urgent ones beyond the two (Enxah: soap for festering
    -- wounds and tombs for 35 dead both waited on one extra slot)
    if #open >= slot_cap(open) + (params.urgent == true and URGENT_EXTRA or (kind == 'farms' and 1 or 0)) then
        return {ok = false, rejected = true,
                error = ('already %d unfinished building projects'):format(#open)}
    end
    local stairs, why = find_stairs(STAIRS_TO_TRY)
    if not stairs then return {ok = false, error = why} end
    local reserved = {}
    for _, p in ipairs(open) do table.insert(reserved, p.area) end
    local plan = type(params.plan) == 'table' and params.plan or nil
    local site, why2 = choose_site(L, stairs, reserved, plan)
    if not site then return {ok = false, error = why2} end

    -- Dry run: Quickfort must agree that every tile can be designated.
    local dig = site_dig_cells(L, site.extra)
    if params.urgent == true then dig = prioritized(dig, URGENT_DIG_PRIORITY) end   -- (0.104.128)
    local expected = count(L.tiles) + count(site.extra)
    local a, stair = site.anchor, site.stair
    local dry = quickfort_apply('dig', dig, site.z, a.x, a.y, 'run', true)
    if stat(dry, 'dig_designated') ~= expected or stat(dry, 'dig_invalid_tiles') > 0
            or stat(dry, 'out_of_bounds') > 0 or stat(dry, 'invalid_keys') > 0 then
        return {ok = false, error = ('dry run disagreed: %d of %d tiles designatable'):format(
            stat(dry, 'dig_designated'), expected)}
    end

    local stairs_cells = site.extend and stair_cells(stair, site.z) or {}
    local build, furniture = entry_door(L, site, params.style)
    local decor = decoration_cells(L, site, build)
    local where = {stair = {x = stair.x, y = stair.y, z_top = stair.z_top, z_bottom = stair.z_bottom,
                            elevation_top = ez(stair.z_top), elevation_bottom = ez(stair.z_bottom)},
                   anchor = a, corridor = site.corridor}
    if dry_run then
        return {ok = true, dry_run = true, kind = kind, z = site.z, elevation = ez(site.z),
                extends_stairs = site.extend, in_district = site.in_district,
                stair = where.stair, anchor = a, corridor = site.corridor,
                area = site.area, tiles = expected, summary = L.summary, furniture = furniture,
                decoration = {smooth = #decor.smooth, engrave = #decor.engrave}}
    end

    -- The level first, then the stairs; if anything goes wrong part-way,
    -- take back everything this call designated.
    local done, result = pcall(function()
        local real = quickfort_apply('dig', dig, site.z, a.x, a.y)
        local n = stat(real, 'dig_designated')
        for _, c in ipairs(stairs_cells) do
            local s = quickfort_apply('dig', {{x = 0, y = 0, text = c.text}}, c.z, stair.x, stair.y)
            if stat(s, 'dig_designated') ~= 1 then
                error(('could not designate the stairs on z%d'):format(ez(c.z)))
            end
        end
        return n
    end)
    if not done then
        undo_dig(dig, stairs_cells, site.z, a, stair)
        return {ok = false, error = 'designating failed and was undone: ' .. tostring(result)}
    end
    local p = {
        id = data.next_id, kind = kind, phase = 'dig',
        params = {rooms = params.rooms, room_size = params.room_size, tables = params.tables, beds = params.beds,
                  dormitory = params.dormitory,
                  piles = params.piles, shops = params.shops, size = params.size,
                  plots = params.plots, plot_w = params.plot_w,
                  name = params.name, style = params.style,
                  deity_hf = params.deity_hf, religion = params.religion, profession = params.profession},
        stair = {x = stair.x, y = stair.y}, anchor = {x = a.x, y = a.y},
        z = site.z, area = site.area, corridor = site.corridor,
        stairs = stairs_cells, summary = L.summary, furniture = furniture,
        -- the exact cells, so later steps never depend on regenerating the layout
        cells = {dig = dig, build = build, place = L.place, zone = L.zone,
                 smooth = decor.smooth, engrave = decor.engrave},
        started = now, designated = result,
        plan = plan, in_district = site.in_district,   -- the overseer's hint, and whether it was met
    }
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    local saved = save_projects(data)
    if not saved then
        undo_dig(dig, stairs_cells, site.z, a, stair)
        return {ok = false, error = 'could not save the project with the fort, so it was undone'}
    end
    return {ok = true, project_id = p.id, kind = kind, z = site.z, elevation = ez(site.z),
            extends_stairs = site.extend, in_district = site.in_district,
            stair = {x = stair.x, y = stair.y},
            anchor = a, corridor = site.corridor,
            tiles = expected, designated = result, summary = L.summary,
            warning = (result ~= expected) and ('only %d of %d tiles designated'):format(result, expected) or nil}
end

local function cells_of(p, phase)
    return (type(p.cells) == 'table' and type(p.cells[phase]) == 'table') and p.cells[phase] or {}
end

-- How far the digging has got, and whether it's stuck.
function dig_progress(p)
    local total, dug, stuck, marked, digging = 0, 0, 0, 0, 0
    local jobs = job_tiles()
    local waiting = {}             -- (0.104.110) what the tiles left wait on: up to 5, with their jobs
    -- (0.104.127) can a dwarf get beside a waiting tile? (Teacheroar: the new
    -- hospital 0 of 175 and a bedrooms level 0 of 89 for years, each one dig
    -- job with "no worker")
    local groups
    local function reach_words(x, y, z)
        if groups == nil then
            groups = {}
            pcall(function()
                for _, cp in ipairs(citizen_positions()) do
                    local g = dfhack.maps.getWalkableGroup(xyz2pos(cp.x, cp.y, cp.z))
                    if g and g ~= 0 then groups[g] = true end
                end
            end)
        end
        local seen_walk = false
        for dz = 0, 0 do                -- (a wall is dug from beside it, on its own level)
            for dy = -1, 1 do
                for dx = -1, 1 do
                    if dx ~= 0 or dy ~= 0 then
                        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x + dx, y + dy, z + dz))
                        if okg and g and g ~= 0 then
                            if groups[g] then return 'reachable' end
                            seen_walk = true
                        end
                    end
                end
            end
        end
        return seen_walk and 'beside ground the dwarves can\'t reach' or 'no open ground beside it'
    end
    -- (0.104.136) what DF cancels digging for: warm stone, damp stone (water or
    -- an aquifer beside it), a hidden tile (Teacheroar: two hospital levels began
    -- at x109 y40 z157 beside the cistern and neither was ever dug)
    local function risk_words(x, y, z)
        local out = {}
        local t = tile_info(x, y, z)
        if t and t.warm then table.insert(out, 'warm stone') end
        if t and t.hidden then table.insert(out, 'hidden') end
        if t and t.aquifer then table.insert(out, 'aquifer') end
        local wet = false
        for dz = -1, 1 do
            for dy = -1, 1 do
                for dx = -1, 1 do
                    local n = tile_info(x + dx, y + dy, z + dz)
                    if n and (n.liquid or n.aquifer) then wet = true end
                end
            end
        end
        if wet then table.insert(out, 'damp (water or an aquifer beside it)') end
        return out
    end
    local function check(x, y, z, done)
        total = total + 1
        local t = tile_info(x, y, z)
        if t and done(t) then
            dug = dug + 1
        elseif jobs[x .. ',' .. y .. ',' .. z] then
            digging = digging + 1  -- a dwarf is on it now
            if #waiting < 5 then
                local okr, rw = pcall(reach_words, x, y, z)
                local okk, risk = pcall(risk_words, x, y, z)
                table.insert(waiting, ('x%d y%d z%d: %s%s%s'):format(x, y, z, job_words(jobs[x .. ',' .. y .. ',' .. z]),
                                                                    okr and rw ~= 'reachable' and (', ' .. rw) or '',
                                                                    okk and #risk > 0 and (', ' .. table.concat(risk, ', ')) or ''))
            end
        elseif t and t.marked then
            marked = marked + 1    -- marker-only designation: nobody will dig it
        elseif t and not t.designated then
            stuck = stuck + 1      -- still wall, and not designated any more
        end
    end
    local not_wall = function(t) return t.shape ~= 'WALL' end
    if p.dig_done == 'open' then        -- a channel: done once the floor is gone
        not_wall = function(t) return t.shape ~= 'WALL' and t.shape ~= 'FLOOR' end
    end
    local anchor = anchor_of(p)
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do check(anchor.x + x, anchor.y + y, p.z, not_wall) end
    end
    for _, c in ipairs(p.stairs or {}) do
        local want = c.text == 'u' and 'STAIR_UP' or 'STAIR_UPDOWN'
        check(p.stair.x, p.stair.y, c.z, function(t) return t.shape == want end)
    end
    -- a cavern well's shaft: each rock level open (no wall, floor or ramp left)
    -- (0.104.13) and the stairs it is dug from. A shaft tile or stair the game
    -- dropped (a channel above turns the rock below it into a ramp) is
    -- designated again, so the shaft never stalls on a lost designation, and
    -- the well waits for every level of it.
    local open_shape = function(t) return t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP' end
    local pri = type(p.params) == 'table' and p.params.pri or ''
    local shaft_open, redug = true, 0
    local function keep(x, y, z, done, key)
        local before = stuck
        check(x, y, z, done)
        local t = tile_info(x, y, z)
        if not (t and done(t)) then shaft_open = false end
        if stuck > before and t and not t.marked then
            local ok, s = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = key .. (pri or '')}}, z, x, y)
            if ok and stat(s, 'dig_designated') == 1 then
                stuck, redug = stuck - 1, redug + 1
            end
        end
    end
    for _, zk in ipairs(p.shaft or {}) do
        keep(anchor.x, anchor.y, zk, open_shape, 'h')
    end
    for _, c in ipairs(p.shaft_stairs or {}) do
        local want = STAIR_SHAPES[c.key]
        keep(c.x, c.y, c.z, function(t) return t.shape == want end, c.key)
    end
    local out = {total = total, dug = dug, stuck = stuck, marked = marked, digging = digging,
                 waiting = #waiting > 0 and waiting or nil}
    if p.shaft then out.shaft_open, out.redesignated = shaft_open, redug > 0 and redug or nil end
    return out
end

-- Buildings inside the project's area: placed, built, and still waiting for
-- materials (only buildingplan's own "planned" list counts as waiting, so
-- furniture that already has its materials isn't ordered again).
function furnish_progress(p)
    local placed, done, waiting = 0, 0, {}
    local a = p.area
    for _, b in ipairs(df.global.world.buildings.all) do
        if b.z == a.z and b.x1 >= a.x1 and b.x2 <= a.x2 and b.y1 >= a.y1 and b.y2 <= a.y2 then
            local t = b:getType()
            if t ~= df.building_type.Stockpile and t ~= df.building_type.Civzone then
                placed = placed + 1
                -- 'exists' = actually built, not just planned
                if b.flags.exists then
                    done = done + 1
                elseif is_planned(b) then
                    local name = df.building_type[t] or tostring(t)
                    waiting[name] = (waiting[name] or 0) + 1
                end
            end
        end
    end
    return {placed = placed, done = done, waiting = waiting}
end

-- Smoothing progress: how many cells still have a smoothing job waiting.
function now_tick()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and t or 0
end

local function tick_of(d)
    return type(d) == 'table' and (tonumber(d.year) or 0) * 403200 + (tonumber(d.tick) or 0) or nil
end

-- (0.104.142) The open-project cap: the base, plus a slot for each level
-- furnishing FURNISH_LEND_DAYS or more (FURNISH_LEND_MAX at most).
function slot_cap(open)
    local lent = 0
    for _, p in ipairs(open or {}) do
        if p.phase == 'furnish' then
            local since = tick_of(p.furnish_started)
            if since and (now_tick() - since) // 1200 >= FURNISH_LEND_DAYS then lent = lent + 1 end
        end
    end
    return MAX_OPEN_PROJECTS + math.min(FURNISH_LEND_MAX, lent)
end


function decor_progress(p)
    local a = anchor_of(p)
    local total, waiting, done, marked = 0, 0, 0, 0
    for _, c in ipairs(cells_of(p, 'smooth')) do
        total = total + 1
        local t = tile_info(a.x + c.x, a.y + c.y, p.z)
        if t and t.smoothing and t.marked then marked = marked + 1   -- marker mode: never dug
        elseif t and t.smoothing then waiting = waiting + 1
        elseif t and t.smoothed then done = done + 1 end
    end
    local since = tick_of(p.decorate_started)
    local days = since and math.max(0, (now_tick() - since) // 1200) or 0
    return {smooth_total = total, smooth_waiting = waiting, smooth_done = done, smooth_marked = marked,
            engrave_total = #cells_of(p, 'engrave'), days_waiting = days,
            timed_out = p.phase == 'decorate' and days >= DECOR_TIMEOUT_DAYS}
end

-- What the overseer should do next for this project, if anything.
local function next_step(p, r)
    if p.phase == 'dig' and r.dig and r.dig.total > 0 and r.dig.dug == r.dig.total then
        return 'furnish'
    elseif p.phase == 'dig' and r.dig and r.dig.stuck > 0 and r.dig.shaft_open ~= false
            and r.dig.dug + r.dig.stuck + r.dig.marked == r.dig.total then
        -- Everything still designated is dug; the rest was cancelled (by the
        -- game, e.g. damp stone, or by the player). A few rock spots are
        -- fine: furnish what's there. Too many: give up on this site.
        return r.dig.stuck * 5 <= r.dig.total and 'furnish' or 'cancel'
    elseif p.phase == 'furnish' and r.furnish and r.furnish.done == r.furnish.placed then
        return 'finish'
    elseif p.phase == 'decorate' and r.decor and (r.decor.smooth_waiting == 0 or r.decor.timed_out) then
        return 'engrave'
    end
    return false      -- (false, not nil, so the key reaches Python)
end

-- Report section: every unfinished project. Projects that are only waiting
-- for decoration (engraving) are listed separately and don't use up a slot.
function projects_report()
    OFFSET = elevation_offset()
    local data = load_projects()
    local out, decorating, finished = {}, {}, 0
    for _, p in ipairs(data.list) do
        if p.phase == 'dig' or p.phase == 'furnish' or p.phase == 'decorate' then
            local r = {id = p.id, kind = p.kind, phase = p.phase, z = p.z, elevation = ez(p.z),
                       summary = p.summary, furniture = p.furniture, started = p.started}
            if p.phase == 'dig' then r.dig = dig_progress(p) end
            -- (0.92) a hall built for a petition: what it's dedicated to
            local pr = type(p.params) == 'table' and p.params or {}
            if pr.profession or pr.deity_hf or pr.religion then
                r.dedication = {profession = pr.profession, deity_hf = pr.deity_hf, religion = pr.religion}
            end
            if p.phase == 'furnish' then
                r.furnish = furnish_progress(p)
                local since = tick_of(p.furnish_started)
                r.furnish.days = since and math.max(0, (now_tick() - since) // 1200) or 0
            end
            if p.phase ~= 'dig' then r.decor = decor_progress(p) end
            r.next = next_step(p, r) or false
            table.insert(p.phase == 'decorate' and decorating or out, r)
        elseif p.phase == 'done' then
            finished = finished + 1
        end
    end
    local okc, cap = pcall(slot_cap, open_projects(data))
    local okl, lids = pcall(well_lids, true)     -- (0.104.151)
    return {open = out, decorating = decorating, finished = finished, max_open = okc and cap or MAX_OPEN_PROJECTS,
            max_open_base = MAX_OPEN_PROJECTS, well_lids = (okl and #lids > 0) and lids or nil,
            well_lids_error = (not okl) and tostring(lids):sub(1, 120) or nil}
end

-- The box a project covers, in map coordinates: {x1, y1, x2, y2, z}, from
-- its dig cells (or its build cells if nothing was dug). nil if no cells.
function bounds_of(p)
    local a = anchor_of(p)
    if type(a) ~= 'table' or type(p.cells) ~= 'table' then return nil end
    local cells = type(p.cells.dig) == 'table' and p.cells.dig or {}
    if #cells == 0 then cells = type(p.cells.build) == 'table' and p.cells.build or {} end
    local x1, y1, x2, y2
    for _, c in ipairs(cells) do
        if type(c) == 'table' and type(c.x) == 'number' and type(c.y) == 'number' then
            x1 = math.min(x1 or c.x, c.x); x2 = math.max(x2 or c.x, c.x)
            y1 = math.min(y1 or c.y, c.y); y2 = math.max(y2 or c.y, c.y)
        end
    end
    if not x1 then return nil end
    return {x1 = a.x + x1, y1 = a.y + y1, x2 = a.x + x2, y2 = a.y + y2, z = p.z}
end

REGISTRY_MAX = 400

-- Report section: every AI project still on record (any phase), newest
-- last, for the overseer's map of what it built where.
function registry_report()
    OFFSET = elevation_offset()
    local list = load_projects().list
    local out = {}
    for i = math.max(1, #list - REGISTRY_MAX + 1), #list do
        local p = list[i]
        local params = type(p.params) == 'table' and p.params or {}
        local plan = type(p.plan) == 'table' and p.plan or {}
        table.insert(out, {id = p.id, kind = p.kind, phase = p.phase, z = p.z,
                           elevation = p.z and ez(p.z) or nil, bounds = bounds_of(p),
                           style = params.style, name = params.name, started = p.started,
                           district = plan.district, in_district = p.in_district})
    end
    return out
end

local function find(data, id)
    for _, p in ipairs(data.list) do
        if p.id == id then return p end
    end
end

-- (0.89) The temple location quickfort just made for a project's zone,
-- dedicated to the deity (or religion) a petition asked for. Returns the
-- location id, or false if none was found. Swapped by the tests.
function dedicate_temple(p, pr)
    local site = dfhack.world.getCurrentSite()
    local a = anchor_of(p)
    for _, c in ipairs(cells_of(p, 'zone')) do
        local zones = dfhack.buildings.findCivzonesAt({x = a.x + c.x, y = a.y + c.y, z = p.z}) or {}
        for _, z in ipairs(zones) do
            if z.location_id and z.location_id >= 0 then
                for _, loc in ipairs(site.buildings) do
                    if loc.id == z.location_id and df.abstract_building_type[loc:getType()] == 'TEMPLE'
                            and df.religious_practice_type[loc.deity_type] ~= 'WORSHIP_HFID'
                            and df.religious_practice_type[loc.deity_type] ~= 'RELIGION_ENID' then
                        if pr.religion then
                            loc.deity_type = df.religious_practice_type.RELIGION_ENID
                            loc.deity_data.Religion = pr.religion
                        else
                            loc.deity_type = df.religious_practice_type.WORSHIP_HFID
                            loc.deity_data.Deity = pr.deity_hf
                        end
                        return loc.id
                    end
                end
            end
        end
    end
    return false
end

-- (0.92) A hall still being dug for a petition that something else has
-- answered meanwhile (region2: the player made the metalsmiths' guildhall
-- while the AI dug one) is given to the next petition instead: its params
-- and its zone (placed only once the digging is done) change. target:
-- {profession = 'FARMER'} or {deity_hf = n} or {religion = n}.
function retarget_hall(id, target, dry_run)
    local data = load_projects()
    local p = find(data, id)
    if not p or p.kind ~= 'temple' then return {ok = false, rejected = true, error = 'no such hall project'} end
    if p.phase ~= 'dig' then
        return {ok = false, rejected = true, error = ('the hall is already %s: its zone stands'):format(p.phase)}
    end
    local loc
    if target.profession then
        if not tostring(target.profession):match('^[%u_]+$') then return {ok = false, rejected = true, error = 'bad profession'} end
        loc = 'location=guildhall profession=' .. target.profession:lower()
    elseif target.deity_hf or target.religion then
        loc = 'location=temple'
    else
        return {ok = false, rejected = true, error = 'retarget_hall needs profession, deity_hf or religion'}
    end
    local changed = 0
    for _, c in ipairs(type(p.cells) == 'table' and p.cells.zone or {}) do
        if type(c.text) == 'string' and c.text:find('location=') then
            c.text = c.text:gsub('m{[^}]*}', 'm{' .. loc .. '}', 1)
            changed = changed + 1
        end
    end
    if changed == 0 then return {ok = false, rejected = true, error = 'the hall has no location zone'} end
    local out = {ok = true, project_id = id, zone = loc, dry_run = dry_run or nil}
    if dry_run then return out end
    p.params = type(p.params) == 'table' and p.params or {}
    p.params.profession, p.params.deity_hf, p.params.religion = target.profession, target.deity_hf, target.religion
    if type(p.summary) == 'table' then
        p.summary.guildhall = target.profession and target.profession:lower() or nil
        p.summary.deity_hf, p.summary.religion = target.deity_hf, target.religion
    end
    save_projects(data)
    return out
end

-- Dig finished -> place doors, furniture, workshops, stockpiles and zones.
-- (0.104.110) Dig jobs on a stalled level let go of their workers, so other
-- miners take them (a dwarf who took a job and then lay in the hospital for
-- years held it all along). Returns {ok, freed}.
function free_dig_jobs(id)
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then return {ok = false, rejected = true, error = 'project is not being dug'} end
    local anchor, tiles = anchor_of(p), {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do tiles[(anchor.x + x) .. ',' .. (anchor.y + y) .. ',' .. p.z] = true end
    end
    local freed = 0
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j and tiles[j.pos.x .. ',' .. j.pos.y .. ',' .. j.pos.z] then
            local okw, w = pcall(dfhack.job.getWorker, j)
            if okw and w and pcall(dfhack.job.removeWorker, j, 0) then freed = freed + 1 end
        end
        link = link.next
    end
    return {ok = true, freed = freed}
end

-- (0.104.128) the tiles of an open level still to dig raised to priority `pri`
function prioritize_project(id, pri, dry_run)
    pri = math.max(1, math.min(3, math.tointeger(pri) or URGENT_DIG_PRIORITY))
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then return {ok = false, rejected = true, error = 'project is not being dug'} end
    -- (0.104.134) the dig jobs DF made before at the old priority keep it: those
    -- nobody holds are taken away, and DF makes them again from the raised
    -- designation (Teacheroar's hospital: raised to 2, still 0 of 175 dug 18
    -- days on, its one job "no worker")
    -- (0.104.135) DF drops a tile's dig designation with its job: each tile is
    -- designated again at the new priority (0.104.134 left the hospital's first
    -- tile bare, and the stuck-level rule gave the level up a minute later)
    local function renew_jobs(level)
        local anchor, at = anchor_of(p), {}
        for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
            for y in pairs(col) do at[(anchor.x + x) .. ',' .. (anchor.y + y) .. ',' .. p.z] = true end
        end
        local gone, cleared, link = 0, {}, df.global.world.jobs.list.next
        while link do
            local j, nxt = link.item, link.next
            if j and at[j.pos.x .. ',' .. j.pos.y .. ',' .. j.pos.z] then
                local okw, w = pcall(dfhack.job.getWorker, j)
                if not (okw and w) then
                    local pos = {x = j.pos.x, y = j.pos.y, z = j.pos.z}
                    if pcall(dfhack.job.removeJob, j) then
                        gone = gone + 1
                        table.insert(cleared, pos)
                    end
                end
            end
            link = nxt
        end
        for _, c in ipairs(cleared) do
            local t = tile_info(c.x, c.y, c.z)
            if t and t.shape == 'WALL' and not t.designated then
                pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. level}}, c.z, c.x, c.y)
            end
        end
        return gone
    end
    if p.dig_pri and p.dig_pri <= pri then          -- done before: its old jobs renewed
        if dry_run then return {ok = true, dry_run = true, already = true, priority = p.dig_pri} end
        local okr, gone = pcall(renew_jobs, p.dig_pri)
        return {ok = true, already = true, priority = p.dig_pri, tiles = 0, renewed = okr and gone or 0}
    end
    local anchor, cells = anchor_of(p), {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do
            local t = tile_info(anchor.x + x, anchor.y + y, p.z)
            if t and t.shape == 'WALL' then table.insert(cells, {x = x, y = y, text = 'd' .. pri}) end
        end
    end
    if #cells == 0 then return {ok = false, rejected = true, error = 'nothing left to dig'} end
    if dry_run then return {ok = true, dry_run = true, tiles = #cells, priority = pri} end
    local s = quickfort_apply('dig', cells, p.z, anchor.x, anchor.y)
    local n = stat(s, 'dig_designated')
    if n == 0 then return {ok = false, error = 'the game took none of the tiles at the new priority'} end
    p.dig_pri = pri
    save_projects(data)
    local okr, gone = pcall(renew_jobs, pri)
    return {ok = true, tiles = n, priority = pri, renewed = okr and gone or 0}
end

-- (0.104.110) a level 90%+ dug whose last tiles haven't moved for weeks
-- (Teacheroar's tomb level: 235 of 240 for three game years, holding one of
-- the two building slots) is furnished without them when the brain says so
STALLED_SHARE = 0.9

function furnish_project(id, buildingplan_on, stalled)
    OFFSET = elevation_offset()
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then
        return {ok = false, rejected = true, error = ('project is already %s'):format(p.phase)}
    end
    local prog = dig_progress(p)
    local accept_rock = prog.stuck > 0 and prog.dug + prog.stuck + prog.marked == prog.total
        and prog.stuck * 5 <= prog.total and prog.shaft_open ~= false    -- (0.104.13) never over a closed shaft
    if stalled and prog.dug >= STALLED_SHARE * prog.total and prog.shaft_open ~= false then
        accept_rock = true
    end
    if prog.dug < prog.total and not accept_rock then
        return {ok = false, rejected = true,
                error = ('digging not finished (%d of %d tiles)'):format(prog.dug, prog.total)}
    end
    if not buildingplan_on then
        return {ok = false, rejected = true,
                error = 'buildingplan is off: furniture without materials would vanish'}
    end
    local results = {}
    for _, mode in ipairs({'build', 'place', 'zone'}) do
        local cells = cells_of(p, mode)
        if #cells > 0 then
            local ok, s = pcall(quickfort_apply, mode, cells, p.z, anchor_of(p).x, anchor_of(p).y)
            results[mode] = ok and stat(s, mode .. '_designated') or ('failed: ' .. tostring(s))
        end
    end
    -- smoothing (a dig-mode designation) goes on at the same time, but only
    -- on the level's own tiles and on rock that is still untouched rock (the
    -- player may have dug next to the level since it was started)
    local own = layouts.tiles_from_dig(cells_of(p, 'dig'))
    local a = anchor_of(p)
    local smooth = {}
    for _, c in ipairs(cells_of(p, 'smooth')) do
        if (own[c.x] and own[c.x][c.y]) or natural_wall(tile_info(a.x + c.x, a.y + c.y, p.z)) then
            table.insert(smooth, c)
        end
    end
    if #smooth > 0 then
        local ok, s = pcall(quickfort_apply, 'dig', smooth, p.z, anchor_of(p).x, anchor_of(p).y)
        results.smooth = ok and stat(s, 'dig_designated') or ('failed: ' .. tostring(s))
    end
    -- (0.89) a temple asked for by a petition: its new location dedicated
    local pr = type(p.params) == 'table' and p.params or {}
    if p.kind == 'temple' and (pr.deity_hf or pr.religion) and results.zone and results.zone ~= 0 then
        local okd, ded = pcall(dedicate_temple, p, pr)
        results.dedicated = okd and ded or ('failed: ' .. tostring(ded))
    end
    if p.kind == 'well' and results.build ~= 1 then
        -- the hole is dug but the game won't put a well over it: stop here
        -- (a new well would only dig another hole)
        p.phase = 'cancelled'
        save_projects(data)
        return {ok = false, project_id = id, placed = results,
                error = ('the game would not place the well over the hole at x%d y%d z%d'):format(
                    anchor_of(p).x, anchor_of(p).y, ez(p.z))}
    end
    p.phase = 'furnish'
    p.furnish_started = {year = now_tick() // 403200, tick = now_tick() % 403200}
    local saved = save_projects(data)
    return {ok = true, project_id = id, placed = results,
            warning = (not saved) and 'not recorded' or nil}
end

-- Furnishing finished (everything built, or nothing to build, e.g. a storage
-- level) -> done. Reports never change anything, so the overseer asks.
-- (0.104.12) decor_only: finished while only statues wait (they stay planned
-- and go up when there's stone; the slot goes to the next level). Enxah's
-- suites held a building slot 257 days for 4 statues with no stone to carve.
DECOR_ONLY = {Statue = true}

function finish_project(id, decor_only, stalled)
    local data = load_projects()
    local p = find(data, id)
    if not p or p.phase ~= 'furnish' then
        return {ok = false, rejected = true, error = 'not a project being furnished'}
    end
    local f = furnish_progress(p)
    local left = false
    for name, n in pairs(f.waiting or {}) do
        if n > 0 and not (decor_only and DECOR_ONLY[name]) then left = true end
    end
    -- (0.104.141) stalled: everything placed, nothing missing, buildings DF
    -- never finished (a 20-bed hospital at 30 of 31 for 134 days): finished,
    -- the slot freed; DF goes on building what is placed
    if stalled and not left and f.placed > 0 then
        -- falls through to finish
    elseif f.done < f.placed and (left or not decor_only) then
        return {ok = false, rejected = true, error = ('%d buildings still waiting'):format(f.placed - f.done)}
    end
    -- Engraving still to come: the project frees its slot but stays on the
    -- list until the walls are smooth enough to engrave.
    p.phase = #cells_of(p, 'engrave') > 0 and 'decorate' or 'done'
    if p.phase == 'decorate' then p.decorate_started = {year = now_tick() // 403200, tick = now_tick() % 403200} end
    save_projects(data)
    return {ok = true, project_id = id, phase = p.phase}
end

-- Smoothing finished -> engrave the halls (Quickfort only engraves smooth
-- stone, so anything not smoothed is skipped).
function engrave_project(id)
    local data = load_projects()
    local p = find(data, id)
    if not p or p.phase ~= 'decorate' then
        return {ok = false, rejected = true, error = 'not a project waiting to be engraved'}
    end
    local d = decor_progress(p)
    if d.smooth_waiting > 0 and not d.timed_out then
        return {ok = false, rejected = true, error = ('%d tiles still being smoothed'):format(d.smooth_waiting)}
    end
    local ok, s = pcall(quickfort_apply, 'dig', cells_of(p, 'engrave'), p.z, anchor_of(p).x, anchor_of(p).y)
    p.phase = 'done'
    save_projects(data)
    return {ok = true, project_id = id, engraved = ok and stat(s, 'dig_designated') or 0}
end

-- Only while digging: removes dig designations on the project's own tiles
-- (dug tiles stay dug, stairs are never removed).
---------------------------------------------------------------------------
-- Founding (a fresh embark): the fort's first staircase. Every level the AI
-- digs grows from a staircase where the dwarves live, and a new embark has
-- none, so the first step is a stair shaft from a surface tile near the
-- wagon down into the ground: a down stair on the surface, up/down stairs
-- through the soil, an up stair on the first level of rock (or 3 levels down
-- when there's no rock near). Never into an aquifer, water, a cavern or warm
-- stone: the whole column is checked before anything is designated. After
-- that, the usual rules dig every level from it.
---------------------------------------------------------------------------

FOUND_RADIUS = 10        -- tiles from the wagon (or the dwarves) to look for the shaft (the builder
                         -- finds stairs within 10 of where the dwarves are)
FOUND_MAX_DEPTH = 8      -- levels the shaft may go down to reach rock
FOUND_SURFACE = {FLOOR = true, PEBBLES = true, SHRUB = true, BOULDER = false}

-- Where the dwarves' wagon stands (a fresh embark), else the middle of the
-- citizens on their busiest level. {x, y, z, what}
function found_center()
    local ok, w = pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.Wagon then
                return {x = b.centerx, y = b.centery, z = b.z, what = 'the wagon'}
            end
        end
    end)
    if ok and w then return w end
    local pos = citizen_positions()
    if #pos == 0 then return nil end
    local by_z = {}
    for _, p in ipairs(pos) do by_z[p.z] = (by_z[p.z] or 0) + 1 end
    local bz, bn = nil, -1
    for z, n in pairs(by_z) do if n > bn then bz, bn = z, n end end
    local xs, ys = {}, {}
    for _, p in ipairs(pos) do if p.z == bz then table.insert(xs, p.x); table.insert(ys, p.y) end end
    table.sort(xs); table.sort(ys)
    return {x = xs[(#xs + 1) // 2], y = ys[(#ys + 1) // 2], z = bz, what = 'the dwarves'}
end

-- The column under a surface tile: {depth to the first rock level, or nil}
-- or nil, why (aquifer, water, cavern, warm stone, open space, not natural).
function found_column(x, y, z)
    local rock
    for d = 1, FOUND_MAX_DEPTH do
        local t = tile_info(x, y, z - d)
        if not t then return nil, 'the map ends' end
        if t.aquifer then return nil, ('an aquifer %d level(s) down'):format(d) end
        if t.liquid then return nil, ('water or magma %d level(s) down'):format(d) end
        if t.feature then return nil, ('a cavern %d level(s) down'):format(d) end
        if t.warm then return nil, ('warm stone %d level(s) down'):format(d) end
        if t.shape ~= 'WALL' then return nil, ('open space %d level(s) down'):format(d) end
        if not NATURAL[t.material] then return nil, ('%s %d level(s) down'):format(tostring(t.material), d) end
        -- and around it: digging the stair opens its sides to anything beside
        for _, n in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
            local nt = tile_info(x + n[1], y + n[2], z - d)
            if nt and nt.aquifer then return nil, ('an aquifer beside it %d level(s) down'):format(d) end
            if nt and nt.liquid then return nil, ('water or magma beside it %d level(s) down'):format(d) end
            if nt and nt.feature then return nil, ('a cavern beside it %d level(s) down'):format(d) end
            -- (0.100, review) open space beside the shaft (a ravine, a river's
            -- channel): the shaft would open into it
            if nt and nt.shape ~= 'WALL' then return nil, ('open space beside it %d level(s) down'):format(d) end
        end
        if t.material ~= 'SOIL' and not rock then rock = d end
        if rock and d >= rock then break end
    end
    return {rock = rock}
end

function found_site()
    local c = found_center()
    if not c then return nil, 'no citizens and no wagon' end
    local best, best_score, why_not = nil, nil, {}
    local w, h = map_size()
    for r = 2, FOUND_RADIUS do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = c.x + dx, c.y + dy
                    local t = (x > 1 and y > 1 and x < w - 2 and y < h - 2) and tile_info(x, y, c.z) or nil
                    if t and FOUND_SURFACE[t.shape] and not t.liquid and not t.building and not t.designated then
                        local col, why = found_column(x, y, c.z)
                        if col then
                            -- near the wagon, and rock not far down
                            local score = r + (col.rock and col.rock * 2 or 20)
                            if not best_score or score < best_score then
                                best, best_score = {x = x, y = y, z = c.z, rock = col.rock}, score
                            end
                        elseif why then
                            why_not[why:gsub('%d+ level%(s%) down', 'below')] = true
                        end
                    end
                end
            end
        end
        if best and r >= 6 then break end          -- (looked far enough for a good one)
    end
    if not best then
        local list = {}
        for k in pairs(why_not) do table.insert(list, k) end
        table.sort(list)
        return nil, ('no tile within %d of %s with solid, dry ground under it%s'):format(
            FOUND_RADIUS, c.what, #list > 0 and (' (found: ' .. table.concat(list, ', ') .. ')') or '')
    end
    best.near = c.what
    return best
end

-- A down stair on the founding level near the wagon or the dwarves (one the
-- AI dug, or yours), even if the dwarves have wandered from it.
function stair_near_center()
    local c = found_center()
    if not c then return nil end
    for dx = -FOUND_RADIUS, FOUND_RADIUS do
        for dy = -FOUND_RADIUS, FOUND_RADIUS do
            local sh = stair_shape(c.x + dx, c.y + dy, c.z)
            if sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN' then return {x = c.x + dx, y = c.y + dy, z = c.z} end
        end
    end
    return nil
end

FOUNDED_KEY = 'ai-overseer/founded'     -- where the AI laid out the first staircase (in the save)

local function founded_site()
    local ok, f = pcall(dfhack.persistent.getSiteData, FOUNDED_KEY, nil)
    return ok and type(f) == 'table' and tonumber(f.x) and f or nil
end

function has_staircase()
    if find_stairs(1) ~= nil or stair_near_center() ~= nil then return true end
    -- the AI's own first shaft, wherever the dwarves have gone since
    local f = founded_site()
    if f then
        local sh = stair_shape(f.x, f.y, f.z)
        return sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN'
    end
    return false
end

function found_fort(dry_run)
    if has_staircase() then return {ok = false, rejected = true, error = 'the fort already has a staircase'} end
    -- a shaft already designated (by the AI earlier, or by you) that the miners
    -- haven't dug yet: wait for it rather than start a second
    local f = founded_site()
    if f then
        local t = tile_info(f.x, f.y, f.z)
        if t and (t.designated or (t.shape or ''):find('^STAIR')) then
            return {ok = false, rejected = true, waiting = true,
                    error = ('the first staircase at x%d y%d is being dug; waiting for the miners'):format(f.x, f.y)}
        end
    end
    local c = found_center()
    if c then
        for dx = -FOUND_RADIUS, FOUND_RADIUS do
            for dy = -FOUND_RADIUS, FOUND_RADIUS do
                local t = tile_info(c.x + dx, c.y + dy, c.z)
                local below = t and t.designated and tile_info(c.x + dx, c.y + dy, c.z - 1)
                if below and below.designated then
                    return {ok = false, rejected = true, waiting = true,
                            error = ('a staircase is designated at x%d y%d; waiting for the miners to dig it'):format(
                                c.x + dx, c.y + dy)}
                end
            end
        end
    end
    local site, why = found_site()
    if not site then return {ok = false, error = why} end
    local depth = site.rock or 3
    local cells = {{z = site.z, text = 'j'}}
    for d = 1, depth - 1 do table.insert(cells, {z = site.z - d, text = 'i'}) end
    table.insert(cells, {z = site.z - depth, text = 'u'})
    local out = {ok = true, x = site.x, y = site.y, z = site.z, elevation = ez(site.z), levels = depth,
                 rock = site.rock ~= nil, near = site.near}
    if dry_run then out.dry_run = true return out end
    local done, err = pcall(function()
        for _, c in ipairs(cells) do
            local st = quickfort_apply('dig', {{x = 0, y = 0, text = c.text}}, c.z, site.x, site.y)
            if stat(st, 'dig_designated') ~= 1 then error(('could not designate the stair on z%d'):format(ez(c.z))) end
        end
    end)
    if not done then
        for _, c in ipairs(cells) do
            pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.text}}, c.z, site.x, site.y, 'undo')
        end
        return {ok = false, error = 'designating the first stair failed and was undone: ' .. tostring(err)}
    end
    pcall(dfhack.persistent.saveSiteData, FOUNDED_KEY, {x = site.x, y = site.y, z = site.z})
    return out
end

function cancel_project(id)
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then
        return {ok = false, rejected = true, error = 'only projects still being dug can be cancelled'}
    end
    undo_dig(cells_of(p, 'dig'), p.stairs, p.z, anchor_of(p), p.stair)
    p.phase = 'cancelled'
    save_projects(data)
    return {ok = true, project_id = id}
end

---------------------------------------------------------------------------
-- Farm plots. Crops grow on soil, or on stone that has been muddied (by
-- water). The AI first lays plots on such floor the fort already has, inside
-- and walkable from where the dwarves are; if that isn't enough, it digs a
-- farm level in a soil layer (layouts.farms). See docs/building.md.
---------------------------------------------------------------------------

FARM_MAX_SIDE = 6          -- plots on existing floor: at most 6x6 each
FARM_MIN_SIDE = 2          -- and at least 2x2 (never a 1-wide corridor)
FARM_SCAN_LEVELS = 12      -- levels searched: the ones most dwarves are on
FARM_SCAN_MARGIN = 20      -- tiles searched around where the dwarves are
FARM_PLOT_W = 5            -- a dug farm level's plots are 5x3
FARM_SEARCH_SECONDS = 2

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

-- Where the dwarves are: their walking areas, their levels (busiest first)
-- and the box around them (plus a margin), for searches near the fort.
function fort_scan_area(margin)
    local pos = citizen_positions()
    if #pos == 0 then return nil end
    local groups, by_z = {}, {}
    local x1, y1, x2, y2 = math.huge, math.huge, -math.huge, -math.huge
    local sx, sy = 0, 0
    for _, p in ipairs(pos) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
        by_z[p.z] = (by_z[p.z] or 0) + 1
        x1, x2 = math.min(x1, p.x), math.max(x2, p.x)
        y1, y2 = math.min(y1, p.y), math.max(y2, p.y)
        sx, sy = sx + p.x, sy + p.y
    end
    local levels = {}
    for z, n in pairs(by_z) do table.insert(levels, {z = z, n = n}) end
    table.sort(levels, function(a, b) return a.n > b.n or (a.n == b.n and a.z > b.z) end)
    local w, h = map_size()
    return {groups = groups, levels = levels,
            x1 = math.max(1, x1 - margin), y1 = math.max(1, y1 - margin),
            x2 = math.min(w - 2, x2 + margin), y2 = math.min(h - 2, y2 + margin),
            cx = sx / #pos, cy = sy / #pos}
end

local function inside_any(areas, x, y, z)
    for _, a in ipairs(areas) do
        if a.z == z and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 then return true end
    end
    return false
end

-- (0.99.7) The levels the ground outside is on near the fort: for a grid
-- of columns around the dwarves, the highest walkable floor under the sky;
-- the commonest first (a hillside site has several).
function surface_levels(area)
    local count = {}
    local _, _, zc = map_size()
    local top = (zc or 1) - 1
    for x = area.x1, area.x2, 6 do
        for y = area.y1, area.y2, 6 do
            for z = top, 0, -1 do
                local t = tile_info(x, y, z)
                if t and t.shape == 'FLOOR' and t.outside then
                    count[z] = (count[z] or 0) + 1
                    break
                elseif t and t.shape ~= 'EMPTY' and t.shape ~= 'NONE' and not t.outside then
                    break
                end
            end
        end
    end
    local out = {}
    for z, n in pairs(count) do table.insert(out, {z = z, n = n}) end
    table.sort(out, function(a, b) return a.n > b.n or (a.n == b.n and a.z > b.z) end)
    local zs = {}
    for _, e in ipairs(out) do table.insert(zs, e.z) end
    return zs
end

-- Rectangles of free soil or muddy floor near the dwarves, adding up to about
-- `want` tiles: {x, y, z, w, h}, busiest levels first.
-- (13c) its own name: the pastures' living-grass list below (no dead grass)
-- used to reassign this one when the module loaded, so dead grass never farmed
local FARM_GRASS = {GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true, GRASS_DEAD = true}

-- outside: also soil and grass under the sky, when there is too little
-- inside (surface crops only grow there; a site whose soil is all on the
-- surface farms there until it has more)
function find_farm_spots(want, reserved, outside)
    local area = fort_scan_area(FARM_SCAN_MARGIN)
    if not area then return {}, 'no citizens' end
    local groups, levels = area.groups, area.levels
    local x1, y1, x2, y2 = area.x1, area.y1, area.x2, area.y2

    local good_cache, used = {}, {}
    local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
    local function good(x, y, z)
        local k = key(x, y, z)
        if used[k] then return false end
        local v = good_cache[k]
        if v ~= nil then return v end
        if not floor_material(x, y, z) then
            good_cache[k] = false
            return false
        end
        local t = tile_info(x, y, z)
        if PASS_OUTSIDE and t and t.outside and SURFACE_SCAN then
            -- (0.99.8) why the surface's tiles were turned down, for the refusal
            local why = (t.shape ~= 'FLOOR' and ('shape ' .. tostring(t.shape)))
                or (not (t.material == 'SOIL' or FARM_GRASS[t.material]) and ('material ' .. tostring(t.material)))
                or (t.liquid and 'water') or (t.building and 'building') or (t.designated and 'designated')
                or (inside_any(reserved, x, y, z) and 'reserved')
                or (groups[walk_group(x, y, z)] ~= true and 'out of reach')
                or (tile_taken(x, y, z) and 'taken') or 'ok'
            SURFACE_SCAN.seen[why] = (SURFACE_SCAN.seen[why] or 0) + 1
        end
        v = t ~= nil and t.shape == 'FLOOR' and not t.liquid and not t.feature
            and (not t.outside or (PASS_OUTSIDE and (t.material == 'SOIL' or FARM_GRASS[t.material])))
            and not t.building and not t.designated
            and not inside_any(reserved, x, y, z)
            and groups[walk_group(x, y, z)] == true
            and (t.material == 'SOIL' or FARM_GRASS[t.material] or mud_at(x, y, z))
            and not tile_taken(x, y, z)
        good_cache[k] = v
        return v
    end

    local spots, total = {}, 0
    local deadline
    for pass = 1, outside and 2 or 1 do
    PASS_OUTSIDE = pass == 2
    good_cache = {}
    -- (0.99.7) each pass gets its own time, and the outdoor pass searches
    -- the surface's levels, not only those most dwarves stand on (region2:
    -- "no free soil" with the surface out of the 12 busiest levels)
    deadline = os.clock() + FARM_SEARCH_SECONDS
    local scan = levels
    if PASS_OUTSIDE then
        scan = {}
        SURFACE_SCAN = {levels = {}, seen = {}}
        for _, z in ipairs(surface_levels(area)) do
            table.insert(scan, {z = z})
            table.insert(SURFACE_SCAN.levels, ez(z))
        end
    end
    for i = 1, math.min(FARM_SCAN_LEVELS, #scan) do
        local z = scan[i].z
        for y = y1, y2 do
            if total >= want or os.clock() > deadline then break end
            for x = x1, x2 do
                if total >= want then break end
                if good(x, y, z) then
                    local rw = 1
                    while rw < FARM_MAX_SIDE and good(x + rw, y, z) do rw = rw + 1 end
                    local rh = 1
                    while rh < FARM_MAX_SIDE do
                        local row_ok = true
                        for dx = 0, rw - 1 do
                            if not good(x + dx, y + rh, z) then row_ok = false break end
                        end
                        if not row_ok then break end
                        rh = rh + 1
                    end
                    -- no bigger than what's still wanted (but never under the minimum)
                    rh = math.max(FARM_MIN_SIDE, math.min(rh, math.ceil((want - total) / rw)))
                    if rw >= FARM_MIN_SIDE and rh >= FARM_MIN_SIDE then
                        local fits = true
                        for dy = 0, rh - 1 do
                            for dx = 0, rw - 1 do
                                if not good(x + dx, y + dy, z) then fits = false end
                            end
                        end
                        if fits then
                            for dy = 0, rh - 1 do
                                for dx = 0, rw - 1 do used[key(x + dx, y + dy, z)] = true end
                            end
                            table.insert(spots, {x = x, y = y, z = z, w = rw, h = rh})
                            total = total + rw * rh
                        end
                    end
                end
            end
        end
    end
    end
    PASS_OUTSIDE = false
    return spots
end

SOIL_RADIUS = 30          -- around each staircase, when looking for soil
SOIL_STEP = 4             -- sample every 4th tile (soil layers are wide)

-- Levels with natural soil (untouched soil wall) near the staircases, from
-- the deepest the builder may extend down to the top: {z = true}. Only used
-- to say clearly why no farm level could be dug.
function soil_levels(stairs)
    local found, done = {}, {}
    local deadline = os.clock() + FARM_SEARCH_SECONDS
    for _, st in ipairs(stairs) do
        for z = math.max(1, st.z_bottom - MAX_LEVELS_BELOW), st.z_top do
            if os.clock() > deadline then return found end
            local k = st.x .. ',' .. st.y .. ',' .. z
            if not found[z] and not done[k] then
                done[k] = true
                for dx = -SOIL_RADIUS, SOIL_RADIUS, SOIL_STEP do
                    for dy = -SOIL_RADIUS, SOIL_RADIUS, SOIL_STEP do
                        local t = tile_info(st.x + dx, st.y + dy, z)
                        if t and t.shape == 'WALL' and t.material == 'SOIL' then
                            found[z] = true
                            break
                        end
                    end
                    if found[z] then break end
                end
            end
        end
    end
    return found
end

-- The busiest citizen level (ties: the higher one, as find_stairs), or nil.
function busiest_level()
    local by_z, best, n = {}, nil, 0
    for _, p in ipairs(citizen_positions()) do by_z[p.z] = (by_z[p.z] or 0) + 1 end
    for z, c in pairs(by_z) do
        if c > n or (c == n and z > best) then best, n = z, c end
    end
    return best
end

-- For `ai-bridge survey` (the overseer's master plan): the main staircases,
-- the dwarves' busiest level and the levels with soil, as elevations.
-- Read-only. Each part is tried on its own; a failed part gives <part>_error.
-- Empty lists are left out (soil, when there is none).
function survey()
    OFFSET = elevation_offset()
    local out = {ok = true, elevation_offset = OFFSET}
    local ok, stairs, why = pcall(find_stairs, 3)
    if not ok then
        out.stairs_error, stairs = tostring(stairs), nil
    elseif not stairs then
        out.stairs_error = tostring(why)
    else
        local list = {}
        for _, s in ipairs(stairs) do
            table.insert(list, {x = s.x, y = s.y, z_top = s.z_top, z_bottom = s.z_bottom,
                                elev_top = ez(s.z_top), elev_bottom = ez(s.z_bottom), count = s.count})
        end
        if #list > 0 then out.stairs = list end
        local okw, nw = pcall(stairwell_count)        -- (0.104.82)
        if okw then out.stairwells = nw end
    end
    local ok2, cz = pcall(busiest_level)
    if not ok2 then out.citizen_error = tostring(cz)
    elseif cz == nil then out.citizen_error = 'no citizens'
    else out.citizen_elevation = ez(cz) end
    if stairs then
        local ok3, soil = pcall(soil_levels, stairs)
        if not ok3 then
            out.soil_error = tostring(soil)
        else
            local list = {}
            for z in pairs(soil) do table.insert(list, ez(z)) end
            table.sort(list)
            if #list > 0 then out.soil = list end
        end
    else
        out.soil_error = 'no staircase to look around'
    end
    return out
end

-- Why no farm level could be dug, in words: no soil near the staircases at
-- all, or soil on some levels but no safe spot there (with the first reason).
local function farm_level_why(level_error, reserved)
    local stairs = find_stairs(STAIRS_TO_TRY)
    if not stairs then return 'no farm level: ' .. tostring(level_error) end
    local soil = soil_levels(stairs)
    local zs = {}
    for z in pairs(soil) do table.insert(zs, z) end
    if #zs == 0 then
        return ('no soil on any level the staircases reach (elevation %d to %d)'):format(
            ez(math.max(1, stairs[1].z_bottom - MAX_LEVELS_BELOW)), ez(stairs[1].z_top))
    end
    table.sort(zs)
    -- the first reason a farm level centred on the main stairs fails at a soil level
    local L = layouts.make('farms', {plots = 2, plot_w = FARM_PLOT_W})
    local reason
    CACHE = {}
    for _, z in ipairs(zs) do
        local ok, why = check_site(L, {}, stairs[1].x, stairs[1].y, z, reserved, {x = 0, y = 0})
        if not ok then reason = why break end
    end
    CACHE = nil
    local range = #zs == 1 and ('elevation %d'):format(ez(zs[1]))
        or ('elevation %d to %d'):format(ez(zs[1]), ez(zs[#zs]))
    return ('there is soil at %s, but no safe spot for a farm level there%s'):format(
        range, reason and (' (' .. reason .. ')') or '')
end

-- params: tiles (how many farm tiles are wanted), dig (may start a farm level
-- if existing floor isn't enough), style (the fort's, for that level).
-- dry_run: says what it would do, changes nothing.
function farm_plots(params, now, dry_run)
    OFFSET = elevation_offset()
    local want = math.tointeger(tonumber(params.tiles)) or 0
    local data = load_projects()
    local reserved = {}
    for _, p in ipairs(open_projects(data)) do table.insert(reserved, p.area) end
    SURFACE_SCAN = nil
    local spots, why = find_farm_spots(want, reserved, params.outside == true)
    local placed, refused, tiles = {}, 0, 0
    for _, sp in ipairs(spots) do
        local cell = {{x = 0, y = 0, text = ('p(%dx%d)'):format(sp.w, sp.h)}}
        local ok, dry = pcall(quickfort_apply, 'build', cell, sp.z, sp.x, sp.y, 'run', true)
        local good = ok and stat(dry, 'build_designated') >= 1 and stat(dry, 'invalid_keys') == 0
        if good and not dry_run then
            local ok2, real = pcall(quickfort_apply, 'build', cell, sp.z, sp.x, sp.y)
            good = ok2 and stat(real, 'build_designated') >= 1
        end
        if good then
            table.insert(placed, {x = sp.x, y = sp.y, elevation = ez(sp.z), w = sp.w, h = sp.h})
            tiles = tiles + sp.w * sp.h
        else
            refused = refused + 1
        end
    end
    local out = {ok = true, dry_run = dry_run or nil, placed = placed, tiles = tiles,
                 refused = refused > 0 and refused or nil}
    local short = want - tiles
    if short > 0 and params.dig then
        local plots = math.max(1, math.min(12, math.ceil(short / (FARM_PLOT_W * 3))))
        out.level = start_project({kind = 'farms', plots = plots, plot_w = FARM_PLOT_W, style = params.style},
                                  now, dry_run)
    end
    if tiles == 0 and not (out.level and out.level.ok) then
        local reasons = {}
        if why then table.insert(reasons, why) end
        table.insert(reasons, #spots == 0 and 'no free soil or muddy floor near the dwarves'
            or ('the game refused plots on %d spot(s)'):format(refused))
        if out.level and out.level.rejected then
            table.insert(reasons, 'no farm level now: ' .. tostring(out.level.error))
        elseif out.level then
            local ok, text = pcall(farm_level_why, out.level.error, reserved)
            table.insert(reasons, ok and text or ('no farm level: ' .. tostring(out.level.error)))
        elseif not params.dig then
            table.insert(reasons, 'and no new level may be dug now')
        end
        if SURFACE_SCAN then
            -- (0.99.8) what the surface held, so a refusal says why
            local parts = {}
            for k, n in pairs(SURFACE_SCAN.seen) do table.insert(parts, {k = k, n = n}) end
            table.sort(parts, function(a, b) return a.n > b.n end)
            local words = {}
            for i = 1, math.min(5, #parts) do table.insert(words, parts[i].k .. ' ' .. parts[i].n) end
            local lv = {}
            for _, e in ipairs(SURFACE_SCAN.levels) do table.insert(lv, tostring(e)) end
            table.insert(reasons, ('the surface (elevation %s): %s'):format(
                #lv > 0 and table.concat(lv, ', ') or 'none found', #words > 0 and table.concat(words, ', ') or 'no tiles'))
            out.surface = SURFACE_SCAN
        end
        out.ok, out.error = false, table.concat(reasons, '; ')
    end
    return out
end

-- Report section: the fort's farm plots (built or still waiting to be built).
-- (0.99.6) What a plant brews from: 'plant' (the plant itself, its
-- STRUCTURAL material makes a drink), 'growth' (a fruit or other growth
-- does), or nil. From the raws' MATERIAL_REACTION_PRODUCT:DRINK_MAT.
function plant_brews(raw)
    local out = nil
    for _, m in ipairs(raw.material) do
        local ok, ids = pcall(function() return m.reaction_product.id end)
        if ok and ids then
            for _, id in ipairs(ids) do
                local v = type(id) == 'string' and id or id.value
                if v == 'DRINK_MAT' then
                    if m.id == 'STRUCTURAL' then return 'plant' end
                    out = 'growth'
                end
            end
        end
    end
    return out
end

-- (0.104.11) Does a plant give thread (a THREAD material: pig tails, rope
-- reeds, hemp...)? Processed at a farmer's workshop, the thread goes to
-- the hospital's sutures and the loom.
function plant_thread(raw)
    local ok, yes = pcall(function()
        for _, m in ipairs(raw.material) do if m.id == 'THREAD' then return true end end
        return false
    end)
    return ok and yes or false
end

local SEASON_FLAGS = {'SPRING', 'SUMMER', 'AUTUMN', 'WINTER'}

-- (0.99.6) The crops the fort has seeds for: seeds and stock of each, what it
-- brews from, the seasons it grows in, above or below ground; and what the
-- plots grow this season. For steering autofarm toward drink.
local function crops_report()
    local crops, other = {}, df.global.world.items.other
    local function crop(idx)
        local raw = df.plant_raw.find(idx)
        if not raw then return nil end
        local c = crops[raw.id]
        if not c then
            local seasons = {}
            for _, f in ipairs(SEASON_FLAGS) do
                if raw.flags[f] then table.insert(seasons, f:lower()) end
            end
            local under = false
            pcall(function() under = raw.flags.BIOME_SUBTERRANEAN_WATER or (raw.underground_depth_min or 0) > 0 end)
            c = {name = raw.name, seeds = 0, stock = 0, brews = plant_brews(raw), seasons = seasons,
                 underground = under, planted = 0, thread = plant_thread(raw) or nil}
            crops[raw.id] = c
        end
        return c
    end
    local function free(it)
        local f = it.flags
        return not (f.forbid or f.garbage_collect or f.rotten or f.trader or f.removed or f.dump)
    end
    for _, it in ipairs(other.SEEDS) do
        if free(it) then
            local c = crop(it:getMaterialIndex())
            if c then c.seeds = c.seeds + it:getStackSize() end
        end
    end
    for _, it in ipairs(other.PLANT) do
        if free(it) then
            local raw = df.plant_raw.find(it:getMaterialIndex())
            local c = raw and crops[raw.id]
            if c then c.stock = c.stock + it:getStackSize() end
        end
    end
    local season = math.max(0, math.min(3, df.global.cur_year_tick // 100800))   -- 3 months of 28 days
    local plots_under, plots_above = 0, 0
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.FarmPlot then
            local d = dfhack.maps.getTileFlags(b.centerx, b.centery, b.z)
            if d and d.outside then plots_above = plots_above + 1 else plots_under = plots_under + 1 end
            local id = b.plant_id[season]
            if id and id >= 0 then
                local c = crop(id)
                if c then c.planted = c.planted + 1 end
            end
        end
    end
    return {crops = crops, season = SEASON_FLAGS[season + 1]:lower(),
            plots_underground = plots_under, plots_surface = plots_above}
end

function farms_report()
    local plots, tiles, built = 0, 0, 0
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.FarmPlot then
            plots = plots + 1
            tiles = tiles + (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1)
            if b.flags.exists then built = built + 1 end
        end
    end
    local out = {plots = plots, tiles = tiles, built = built}
    local ok, cr = pcall(crops_report)
    if ok and cr then
        out.crops, out.season = cr.crops, cr.season
        out.plots_underground, out.plots_surface = cr.plots_underground, cr.plots_surface
    else
        out.crops_error = tostring(cr):sub(1, 120)
    end
    return out
end

---------------------------------------------------------------------------
-- Wells. A well stands over a hole with a straight drop to clean water at
-- least 3/7 deep (or any water over 7/7). The AI looks for a natural floor
-- inside the fort, on a busy level, with such a drop under it, channels that
-- tile and builds the well over the hole (buildingplan waits for a block, a
-- bucket, a rope or chain and a mechanism). It never opens the fort into a
-- cavern, and never over water that fills the space right under the floor
-- (it could be under pressure and flood up). See docs/building.md.
---------------------------------------------------------------------------

WELL_MAX_DROP = 30         -- levels the bucket may go down
WELL_SCAN_MARGIN = 20
WELL_SEARCH_SECONDS = 2
-- zones a well may stand in (and is welcome in); any other zone is left alone
WELL_ZONES = {DiningHall = true, MeetingHall = true}

-- Usable water straight down from (x, y, z)? Returns the drop in levels, or
-- nil and why not.
function water_below(x, y, z)
    for k = 1, WELL_MAX_DROP do
        local t = tile_info(x, y, z - k)
        if not t then return nil, 'no water below' end
        if t.feature then return nil, 'the water below is in a cavern' end
        if t.outside then return nil, 'the drop opens to the sky' end
        if t.liquid then
            if t.magma then return nil, 'magma below' end
            if t.stagnant or t.salt then return nil, 'the water below is stagnant or salt' end
            if k == 1 and t.depth >= 7 then
                return nil, 'water fills the space right under the floor (it may be under pressure)'
            end
            if t.depth >= 3 then return k end
            local u = tile_info(x, y, z - k - 1)
            if t.shape == 'EMPTY' and u and u.liquid and not u.magma and not u.stagnant and not u.salt
                    and u.depth >= 7 then
                return k + 1
            end
            return nil, 'the water below is too shallow'
        end
        if t.shape ~= 'EMPTY' then return nil, nil end    -- solid: the common case, not worth a word
    end
    return nil, 'no water within reach'
end

-- The best spot for a well: {x, y, z, drop, zone}, or nil and why.
function find_well_spot(reserved)
    local area = fort_scan_area(WELL_SCAN_MARGIN)
    if not area then return nil, 'no citizens' end
    local best, best_score
    local why_not = {}
    local deadline = os.clock() + WELL_SEARCH_SECONDS
    for i = 1, math.min(FARM_SCAN_LEVELS, #area.levels) do
        local z = area.levels[i].z
        for y = area.y1, area.y2 do
            if os.clock() > deadline then break end
            for x = area.x1, area.x2 do
                local mat = floor_material(x, y, z)
                if mat and mat ~= 'CONSTRUCTION' then        -- built floors can't be channelled
                    local t = tile_info(x, y, z)
                    if t and not t.liquid and not t.feature and not t.outside and not t.building
                            and not t.designated and not inside_any(reserved, x, y, z)
                            and area.groups[walk_group(x, y, z)] and not building_at(x, y, z) then
                        local zones, ok_zone, liked = zone_types(x, y, z), true, false
                        for _, k in ipairs(zones) do
                            if WELL_ZONES[k] then liked = true else ok_zone = false end
                        end
                        if ok_zone then
                            local drop, why = water_below(x, y, z)
                            if drop then
                                -- in a dining or meeting hall first, then near the middle
                                -- of the fort, on the busiest level
                                local score = (liked and 0 or 1000) + (i - 1) * 50
                                    + math.abs(x - area.cx) + math.abs(y - area.cy)
                                if not best_score or score < best_score then
                                    best, best_score = {x = x, y = y, z = z, drop = drop, zone = liked}, score
                                end
                            elseif why then
                                why_not[why] = true
                            end
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    local reasons = {}
    for w in pairs(why_not) do table.insert(reasons, w) end
    table.sort(reasons)
    return nil, 'no open drop from a free floor inside the fort to clean water'
        .. (#reasons > 0 and (' (' .. table.concat(reasons, '; ') .. ')') or '')
end

-- A well on the shore, when the fort has no water under it (its water is a
-- pond, brook or river on the surface, above the fort or beside it): a dry
-- floor tile on the bank whose tile below has water beside it, one level
-- down. Channelling it opens that tile below into a ramp the water flows
-- into (only that one tile: everything else around it on that level must be
-- rock or the water itself, so nothing else can flood), and the well stands
-- on the bank over it, the bucket going down one level. Fresh water first,
-- then the nearest; salt water never, stagnant only if there's nothing else
-- (it gives a bad thought, but a fort without water dies of thirst).
WELL_SHORE_RADIUS = 40
function find_shore_well_spot(reserved)
    local anchors = pasture_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to look around' end
    local groups = {}
    for _, p in ipairs(citizen_positions()) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
    end
    local function rock(t) return t and t.shape == 'WALL' and not t.aquifer and not t.feature end
    local best, best_score, why
    local deadline = os.clock() + WELL_SEARCH_SECONDS
    local seen = {}
    for _, a in ipairs(anchors) do
        for z = a.z - 3, a.z + 3 do
            for y = a.y - WELL_SHORE_RADIUS, a.y + WELL_SHORE_RADIUS do
                if os.clock() > deadline then break end
                for x = a.x - WELL_SHORE_RADIUS, a.x + WELL_SHORE_RADIUS do
                    local k = x .. ',' .. y .. ',' .. z
                    if not seen[k] then
                        seen[k] = true
                        local t = tile_info(x, y, z)
                        if t and t.shape == 'FLOOR' and t.material ~= 'CONSTRUCTION' and not t.liquid
                                and not t.feature and not t.building and not t.designated
                                and not inside_any(reserved, x, y, z) and groups[walk_group(x, y, z)] then
                            local under = tile_info(x, y, z - 1)
                            -- water beside the tile below (that level is the water's)
                            local water, ok_around, stagnant = nil, rock(under), false
                            if ok_around then
                                for dy = -2, 2 do
                                    for dx = -2, 2 do
                                        if dx ~= 0 or dy ~= 0 then
                                            local n = tile_info(x + dx, y + dy, z - 1)
                                            if n and n.liquid and not n.magma and not n.feature then
                                                if n.salt then ok_around = false end
                                                if math.abs(dx) <= 1 and math.abs(dy) <= 1 and n.depth >= 3 then
                                                    water = water or n
                                                    stagnant = stagnant or n.stagnant
                                                end
                                            elseif not rock(n) then
                                                ok_around = false        -- open ground or the fort down there
                                            end
                                        end
                                    end
                                end
                            end
                            -- (0.100, review) river or brook water can be under
                            -- pressure and rise up the channel: only outside,
                            -- where it runs off, never under the fort's roof
                            local flowing = water and (water.material == 'RIVER' or water.material == 'BROOK')
                            if water and ok_around and flowing and not t.outside then
                                why = 'the only river water near the entrances is under a roof (it could rise up the well)'
                            elseif water and ok_around then
                                -- a dry floor beside it for the builder to stand on
                                -- (quickfort wants a floor beside the well, not just at a corner)
                                local stand = false
                                for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
                                    local n = tile_info(x + d[1], y + d[2], z)
                                    if n and n.shape == 'FLOOR' and not n.liquid then stand = true end
                                end
                                if stand then
                                    local score = (stagnant and 1000 or 0) + math.abs(x - a.x) + math.abs(y - a.y)
                                        + 5 * math.abs(z - a.z)
                                    if not best_score or score < best_score then
                                        best, best_score = {x = x, y = y, z = z, drop = 1, shore = true,
                                                            stagnant = stagnant or nil}, score
                                    end
                                end
                            elseif water then
                                why = 'the only water near the surface entrances has open ground or the fort beside it, one level down (a channel there could flood it)'
                            end
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    return nil, why or ('no pond, brook or river within %d tiles of the surface entrances to put a well beside'):format(WELL_SHORE_RADIUS)
end

-- A cavern well (only when the AI decides it must: brain/planner.py
-- _well_rule). A floor inside the fort with solid natural rock straight
-- under it, then a cavern's open air, then fresh water at least 3/7 deep:
-- a one-tile shaft is channelled down through the rock, one level after the
-- other, and the well stands over it. The shaft's walls touch nothing but
-- rock (no aquifer, water or open space beside them), so nothing can flood
-- in, and walkers can't climb out of the cavern up a one-tile drop.
-- (The rock's layout is read even where it's undiscovered, as for every
-- other safety check of the AI.)
CAVERN_WELL_MIN_DEPTH = 3

local function solid_rock(t)
    return t ~= nil and t.shape == 'WALL' and not t.aquifer and not t.liquid and not t.feature and not t.warm
        and t.material ~= 'CONSTRUCTION' and not is_tree(t)
end

-- (0.104.13) The shaft's stairs. A miner channels a tile standing beside it
-- on the same level, so a one-tile shaft can't be dug past its first level
-- or two (Enxah's crept to 2 of 24 tiles in six game years while patients
-- died of thirst every winter). A stair column right beside the shaft goes
-- down with it: a down stair in the hall's floor, up/down stairs through the
-- rock, an up stair at the bottom, and each level of the shaft is channelled
-- from the stair beside it. The column keeps to the same solid rock as the
-- shaft (nothing but rock and the shaft round it), so it opens into nothing.
-- {x, y} of the column's top, or nil, why.
function shaft_stairs_side(x, y, z, rock, reserved, group)
    for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
        local sx, sy = x + d[1], y + d[2]
        local t = tile_info(sx, sy, z)
        local mat = floor_material(sx, sy, z)
        local ok = t ~= nil and mat ~= nil and mat ~= 'CONSTRUCTION' and t.shape == 'FLOOR' and not t.liquid
            and not t.feature and not t.outside and not t.building and not t.designated
            and not inside_any(reserved or {}, sx, sy, z) and not building_at(sx, sy, z)
            and (group == nil or walk_group(sx, sy, z) == group)
        if ok then
            for _, k in ipairs(zone_types(sx, sy, z)) do
                if not WELL_ZONES[k] then ok = false end
            end
        end
        for k = 1, ok and rock or 0 do
            local c = tile_info(sx, sy, z - k)
            if not solid_rock(c) then ok = false break end
            for _, e in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                local nx, ny = sx + e[1], sy + e[2]
                if not (nx == x and ny == y) then
                    local n = tile_info(nx, ny, z - k)
                    if not n or n.liquid or n.aquifer or n.shape ~= 'WALL' then ok = false break end
                end
            end
            if not ok then break end
        end
        if ok then return {x = sx, y = sy} end
    end
    return nil, 'no room beside the shaft for the stairs it is dug from'
end

-- The stair column's cells, top to bottom: {x, y, z, key}.
function shaft_stair_cells(side, z, rock)
    local cells = {{x = side.x, y = side.y, z = z, key = 'j'}}
    for k = 1, rock do
        table.insert(cells, {x = side.x, y = side.y, z = z - k, key = (k == rock) and 'u' or 'i'})
    end
    return cells
end

STAIR_SHAPES = {j = 'STAIR_DOWN', i = 'STAIR_UPDOWN', u = 'STAIR_UP'}


-- (0.104.83) A small pen for war dogs just inside a gate: a free 3x3 of
-- inside floor (no building, zone, designation, water or sky) within 8
-- tiles of the gate, on its level or the two below, nearest first.
function gate_dog_pen(params, dry_run)
    OFFSET = elevation_offset()
    CACHE = {}
    local gx, gy, gz = params.x, params.y, params.z
    local function free(x, y, z)
        local t = info(x, y, z)
        return t and t.shape == 'FLOOR' and not t.liquid and not t.outside and not t.building
            and not t.designated and not tile_taken(x, y, z) and walk_group(x, y, z) ~= 0
    end
    local best
    for zz = gz, gz - 2, -1 do
        for x = gx - 8, gx + 6 do
            for y = gy - 8, gy + 6 do
                local d = math.max(math.abs(x + 1 - gx), math.abs(y + 1 - gy)) + 3 * (gz - zz)
                if (not best or d < best.d) and d >= 2 then
                    local ok = true
                    for dx = 0, 2 do
                        for dy = 0, 2 do
                            if ok and not free(x + dx, y + dy, zz) then ok = false end
                        end
                    end
                    if ok then best = {x = x, y = y, z = zz, d = d} end
                end
            end
        end
    end
    if not best then return {ok = false, rejected = true, error = 'no free 3x3 of inside floor near the gate'} end
    local cell = {{x = 0, y = 0, text = ('n{name="%s"}(3x3)'):format(params.name or 'AI gate dogs')}}
    local okd, dry = pcall(quickfort_apply, 'zone', cell, best.z, best.x, best.y, 'run', true)
    if not (okd and stat(dry, 'zone_designated') >= 1 and stat(dry, 'invalid_keys') == 0) then
        return {ok = false, rejected = true, error = 'the game refused the pen'}
    end
    local out = {ok = true, x = best.x, y = best.y, elevation = ez(best.z), dry_run = dry_run or nil}
    if dry_run then return out end
    local okr, real = pcall(quickfort_apply, 'zone', cell, best.z, best.x, best.y)
    if not (okr and stat(real, 'zone_designated') >= 1) then return {ok = false, error = 'the game refused the pen'} end
    return out
end

-- (0.104.82) Stairwells: how many separate stair columns the fort has (3+
-- levels each, at least STAIRWELL_APART tiles from the next: a 2x2 stair or
-- the shaft's side stair counts once). For the survey.
STAIRWELL_APART = 6

function stairwell_count()
    local stairs = find_stairs(10)
    if not stairs then return 0 end
    local kept = {}
    for _, s in ipairs(stairs) do
        if s.z_top - s.z_bottom >= 2 then
            local alone = true
            for _, k in ipairs(kept) do
                if math.max(math.abs(k.x - s.x), math.abs(k.y - s.y)) < STAIRWELL_APART then alone = false break end
            end
            if alone then table.insert(kept, s) end
        end
    end
    return #kept
end

-- (0.104.82) A new stairwell for a district of the master plan: a down stair
-- in a free floor tile of a level the main stair reaches, `dir` of it and
-- min_dist..max_dist tiles out (never within min_dist of another stair),
-- up/down stairs through untouched rock and an up stair on the district's
-- lowest level (elev_lo). The builder then grows the district's levels from
-- it. params: dir, elev_lo, elev_hi, min_dist, max_dist, spine {x, y}.
local STAIR_DIRS = {north = {0, -1}, south = {0, 1}, east = {1, 0}, west = {-1, 0}}

function dig_stairwell(params, dry_run)
    OFFSET = elevation_offset()
    CACHE = {}
    local v = STAIR_DIRS[params.dir]
    if not v then return {ok = false, rejected = true, error = 'dir must be north, east, south or west'} end
    local stairs = find_stairs(10) or {}
    local spine
    if type(params.spine) == 'table' then
        for _, s in ipairs(stairs) do
            if s.x == params.spine.x and s.y == params.spine.y then spine = s break end
        end
    end
    spine = spine or stairs[1]
    if not spine then return {ok = false, rejected = true, error = 'no main stair found'} end
    local lo_z = params.elev_lo - OFFSET
    local hi_z = (params.elev_hi or params.elev_lo) - OFFSET
    local min_d, max_d = params.min_dist or 10, params.max_dist or 40
    -- the levels to start from: on the main stair, from the district's top
    -- (or the nearest above it) upward, at least 2 levels above its bottom
    local tops = {}
    for z = spine.z_top, spine.z_bottom, -1 do
        if z - lo_z >= 2 and z - lo_z <= 10 then table.insert(tops, z) end
    end
    table.sort(tops, function(a, b)
        local pa, pb = (a < hi_z) and 100 or 0, (b < hi_z) and 100 or 0
        if pa ~= pb then return pa < pb end
        return math.abs(a - hi_z) < math.abs(b - hi_z)
    end)
    if #tops == 0 then
        return {ok = false, rejected = true, error = ('the main stair reaches no level 2-10 above elevation %d')
            :format(params.elev_lo)}
    end
    local deadline, why = os.clock() + 0.4, 'no free floor tile there'
    local px, py = -v[2], v[1]
    local W, H = map_size()
    for i = 1, math.min(#tops, 6) do
        local z = tops[i]
        local group = walk_group(spine.x, spine.y, z)
        -- every stair on this level within reach of the search (not only
        -- those where the dwarves stand): none may be within min_dist
        local near = {}
        local r = max_d + min_d
        for x = math.max(0, spine.x - r), math.min(W - 1, spine.x + r) do
            for y = math.max(0, spine.y - r), math.min(H - 1, spine.y + r) do
                if stair_shape(x, y, z) then table.insert(near, {x = x, y = y}) end
            end
        end
        for d = min_d, max_d do
            for s = 0, d // 2 do
                for _, sg in ipairs(s == 0 and {1} or {1, -1}) do
                    if os.clock() > deadline then
                        return {ok = false, rejected = true, error = 'search cut short: ' .. why, timed_out = true}
                    end
                    local x, y = spine.x + v[1] * d + px * s * sg, spine.y + v[2] * d + py * s * sg
                    local tt = info(x, y, z)
                    local ok = tt and tt.shape == 'FLOOR' and not tt.liquid and not tt.outside and not tt.building
                        and not tt.designated and group ~= 0 and walk_group(x, y, z) == group
                        and not building_at(x, y, z) and #zone_types(x, y, z) == 0
                    if ok then
                        for _, st in ipairs(near) do
                            if math.max(math.abs(st.x - x), math.abs(st.y - y)) < min_d then ok = false end
                        end
                        if not ok then why = 'too near another stair' end
                    end
                    if ok then
                        local okx, w = check_extension(x, y, z, lo_z)
                        if not okx then ok, why = false, w end
                    end
                    if ok then
                        local cells = {{z = z, key = 'j'}}
                        for zz = z - 1, lo_z + 1, -1 do table.insert(cells, {z = zz, key = 'i'}) end
                        table.insert(cells, {z = lo_z, key = 'u'})
                        local all = true
                        for _, c in ipairs(cells) do
                            local dr = quickfort_apply('dig', {{x = 0, y = 0, text = c.key}}, c.z, x, y, 'run', true)
                            if stat(dr, 'dig_designated') ~= 1 then all = false why = 'the game would not dig it' break end
                        end
                        if all then
                            local out = {ok = true, x = x, y = y, elev_top = ez(z), elev_bottom = ez(lo_z),
                                         levels = #cells, dir = params.dir, dry_run = dry_run or nil}
                            if dry_run then return out end
                            for _, c in ipairs(cells) do
                                quickfort_apply('dig', {{x = 0, y = 0, text = c.key}}, c.z, x, y)
                            end
                            return out
                        end
                    end
                end
            end
        end
    end
    return {ok = false, rejected = true, error = ('no place for a stairwell %s of the main stair: %s'):format(params.dir, why)}
end

-- {drop, rock = levels of rock to channel, cavern_z} or nil, why.
function cavern_below(x, y, z)
    local rock = 0
    for k = 1, WELL_MAX_DROP do
        local t = tile_info(x, y, z - k)
        if not t then return nil, 'no cavern water within reach' end
        if rock == k - 1 and not t.feature then
            if not solid_rock(t) then return nil, 'not solid rock all the way down to the cavern' end
            for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                local n = tile_info(x + d[1], y + d[2], z - k)
                if not n or n.liquid or n.aquifer or n.shape ~= 'WALL' then
                    return nil, 'the shaft would pass open space, water or an aquifer'
                end
            end
            rock = rock + 1
        elseif t.feature then
            if rock == 0 then return nil, 'the floor is the cavern\'s ceiling' end
            if t.liquid then
                if t.magma then return nil, 'magma below' end
                if t.salt then return nil, 'the cavern water is salt' end
                if k == rock + 1 and t.depth >= 7 then
                    return nil, 'the cavern water fills the space right under the rock (it may be under pressure)'
                end
                if t.depth >= CAVERN_WELL_MIN_DEPTH then return {drop = k, rock = rock, stagnant = t.stagnant} end
                return nil, 'the cavern water there is too shallow'
            end
            if t.shape ~= 'EMPTY' then return nil, 'cavern floor, not water, below' end
        else
            return nil, 'not a cavern below'
        end
    end
    return nil, 'no cavern water within reach'
end

function find_cavern_well_spot(reserved)
    local area = fort_scan_area(WELL_SCAN_MARGIN)
    if not area then return nil, 'no citizens' end
    local best, best_score, why_not = nil, nil, {}
    local deadline = os.clock() + WELL_SEARCH_SECONDS * 2
    for i = 1, math.min(FARM_SCAN_LEVELS, #area.levels) do
        local z = area.levels[i].z
        for y = area.y1, area.y2 do
            if os.clock() > deadline then break end
            for x = area.x1, area.x2 do
                local mat = floor_material(x, y, z)
                if mat and mat ~= 'CONSTRUCTION' then
                    local t = tile_info(x, y, z)
                    if t and not t.liquid and not t.feature and not t.outside and not t.building
                            and not t.designated and not inside_any(reserved, x, y, z)
                            and area.groups[walk_group(x, y, z)] and not building_at(x, y, z) then
                        local zones, ok_zone, liked = zone_types(x, y, z), true, false
                        for _, k in ipairs(zones) do
                            if WELL_ZONES[k] then liked = true else ok_zone = false end
                        end
                        if ok_zone then
                            local c, why = cavern_below(x, y, z)
                            local side
                            if c then
                                side, why = shaft_stairs_side(x, y, z, c.rock, reserved, walk_group(x, y, z))
                                if not side then c = nil end
                            end
                            if c then
                                -- fresh water, a short shaft, a hall, near the middle
                                local score = (c.stagnant and 2000 or 0) + c.rock * 40 + (liked and 0 or 300)
                                    + (i - 1) * 50 + math.abs(x - area.cx) + math.abs(y - area.cy)
                                if not best_score or score < best_score then
                                    best, best_score = {x = x, y = y, z = z, drop = c.drop, rock = c.rock,
                                                        zone = liked, cavern = true, stagnant = c.stagnant,
                                                        side = side}, score
                                end
                            elseif why then
                                why_not[why] = true
                            end
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    local reasons = {}
    for w in pairs(why_not) do table.insert(reasons, w) end
    table.sort(reasons)
    return nil, 'no floor inside the fort over cavern water with solid rock between'
        .. (#reasons > 0 and (' (' .. table.concat(reasons, '; ') .. ')') or '')
end

-- --- rooms opened up: their walls built back (0.104.20) -----------------------------
--
-- Enxah's quarry (before 0.104.19 kept it out of rooms) dug through the walls
-- of the old bedroom levels, so bedrooms, doors and beds stood in one open
-- hall (the player's screenshot). Those levels' layouts were long gone from
-- the project list, so the rooms are read from the game itself: a bedroom
-- zone with a bed in it (or an office zone) whose wall ring holds a door is
-- a room; every tile of that ring that is now plain open floor (not the door,
-- no building, no zone, not a stair, not a built floor, not dug on purpose by
-- a level the AI still lists) is a gap, and a wall is built there again
-- (buildingplan finds blocks or stone). The room's own walls, nothing more:
-- the corridor the door opens onto lies outside the ring.
REPAIR_MAX = 40          -- walls placed in one go
ROOM_DOORLESS_MAX = 4    -- (0.104.26) a doorless bedroom up to 4x4 gets a door back

function room_zones()
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone
                and (b.type == df.civzone_type.Bedroom or b.type == df.civzone_type.Office) then
            table.insert(out, {id = b.id, x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
                               office = b.type == df.civzone_type.Office or nil})
        end
    end
    return out
end

function building_kind_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if ok and b then return df.building_type[b:getType()] end
    return nil
end

-- Tiles the levels the AI still lists dug on purpose ("x,y,z" -> true).
local function designed_open()
    local set = {}
    for _, p in ipairs(load_projects().list) do
        if type(p.cells) == 'table' and p.z then
            local a = anchor_of(p)
            if a then
                for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
                    for y in pairs(col) do set[(a.x + x) .. ',' .. (a.y + y) .. ',' .. p.z] = true end
                end
            end
        end
    end
    return set
end

function room_gaps(limit)
    local open_set = designed_open()
    local seen, out, rooms, total = {}, {}, 0, 0
    for _, r in ipairs(room_zones()) do
        local ring = {}
        for x = r.x1 - 1, r.x2 + 1 do
            table.insert(ring, {x = x, y = r.y1 - 1})
            table.insert(ring, {x = x, y = r.y2 + 1})
        end
        for y = r.y1, r.y2 do
            table.insert(ring, {x = r.x1 - 1, y = y})
            table.insert(ring, {x = r.x2 + 1, y = y})
        end
        local door, bed = false, r.office == true
        for _, p in ipairs(ring) do
            if building_kind_at(p.x, p.y, r.z) == 'Door' then door = true end
        end
        if not bed then
            for x = r.x1, r.x2 do
                for y = r.y1, r.y2 do
                    if building_kind_at(x, y, r.z) == 'Bed' then bed = true end
                end
            end
        end
        -- (0.104.26) a bedroom with a bed whose door went with its walls
        -- (Enxah: 7 of 99, among them the rooms in the player's screenshot):
        -- a door again on an open side tile that leads out to open floor in
        -- no room (the way in), walls on the rest; at most 4x4, never an office
        local doorless = not door and bed and not r.office
            and (r.x2 - r.x1) < ROOM_DOORLESS_MAX and (r.y2 - r.y1) < ROOM_DOORLESS_MAX
        if (door and bed) or doorless then
            local open_ring = {}
            for _, p in ipairs(ring) do
                local k = p.x .. ',' .. p.y .. ',' .. r.z
                if not seen[k] then
                    local t = tile_info(p.x, p.y, r.z)
                    if t and t.shape == 'FLOOR' and not t.building and not t.designated and not t.liquid
                            and not t.outside and t.material ~= 'CONSTRUCTION' and #zone_types(p.x, p.y, r.z) == 0
                            and not open_set[k] and not building_at(p.x, p.y, r.z) then
                        table.insert(open_ring, {x = p.x, y = p.y, z = r.z, k = k})
                    end
                end
            end
            local door_at
            if doorless then
                for _, p in ipairs(open_ring) do
                    local ox, oy
                    if p.y == r.y1 - 1 and p.x >= r.x1 and p.x <= r.x2 then ox, oy = p.x, p.y - 1
                    elseif p.y == r.y2 + 1 and p.x >= r.x1 and p.x <= r.x2 then ox, oy = p.x, p.y + 1
                    elseif p.x == r.x1 - 1 and p.y >= r.y1 and p.y <= r.y2 then ox, oy = p.x - 1, p.y
                    elseif p.x == r.x2 + 1 and p.y >= r.y1 and p.y <= r.y2 then ox, oy = p.x + 1, p.y end
                    if ox and not door_at then
                        local o = tile_info(ox, oy, r.z)
                        local in_room = false
                        for _, kz in ipairs(zone_types(ox, oy, r.z)) do
                            if kz == 'Bedroom' or kz == 'Office' then in_room = true end
                        end
                        if o and o.shape ~= 'WALL' and not o.liquid and not in_room then door_at = p end
                    end
                end
            end
            -- a doorless room with no way in found is left as it is (never walled shut)
            if not doorless or door_at then
                local gaps = 0
                for _, p in ipairs(open_ring) do
                    seen[p.k] = true
                    gaps = gaps + 1
                    total = total + 1
                    if #out < (limit or REPAIR_MAX) then
                        table.insert(out, {x = p.x, y = p.y, z = p.z, door = (p == door_at) or nil})
                    end
                end
                if gaps > 0 then rooms = rooms + 1 end
            end
        end
    end
    return out, rooms, total
end

-- (0.104.25) Walls planned but held: DFHack's suspendmanager keeps a
-- construction suspended while its tile is marked for smoothing or
-- engraving (so the mark isn't lost), and the AI's polish had marked the
-- floors where the rooms' walls go (Enxah: 40 walls suspended, 236 smoothing
-- jobs waiting). The mark is cleared under every planned, unbuilt wall.
function smooth_marked(x, y, z)
    local ok, v = pcall(function()
        local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
        return d and d.smooth ~= 0
    end)
    return ok and v or false
end

function clear_smooth(x, y, z)
    pcall(function()
        local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
        if d and d.smooth ~= 0 then d.smooth = 0 end
    end)
end

function planned_walls()
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Construction and b:getBuildStage() < b:getMaxBuildStage() then
            table.insert(out, {x = b.centerx, y = b.centery, z = b.z, b = b})
        end
    end
    return out
end

function stalled_walls(fix)
    local n = 0
    for _, w in ipairs(planned_walls()) do
        if smooth_marked(w.x, w.y, w.z) then
            n = n + 1
            if fix then
                clear_smooth(w.x, w.y, w.z)
                pcall(function() for _, j in ipairs(w.b.jobs) do j.flags.suspend = false end end)
            end
        end
    end
    return n
end

-- (0.104.26) What the rooms look like to the repair: bedroom and office
-- zones, how many have a door in their ring and a bed; beds in no bedroom
-- zone (a room whose zone is gone can't be read as a room)
function room_census()
    local c = {zones = 0, with_door = 0, with_bed = 0, rooms = 0, loose_beds = 0, samples = {}}
    local zones = room_zones()
    c.zones = #zones
    for _, r in ipairs(zones) do
        local door, bed = false, r.office == true
        for x = r.x1 - 1, r.x2 + 1 do
            for _, y in ipairs({r.y1 - 1, r.y2 + 1}) do
                if building_kind_at(x, y, r.z) == 'Door' then door = true end
            end
        end
        for y = r.y1, r.y2 do
            for _, x in ipairs({r.x1 - 1, r.x2 + 1}) do
                if building_kind_at(x, y, r.z) == 'Door' then door = true end
            end
        end
        if not r.office then
            for x = r.x1, r.x2 do for y = r.y1, r.y2 do
                if building_kind_at(x, y, r.z) == 'Bed' then bed = true end
            end end
        end
        if door then c.with_door = c.with_door + 1 end
        if bed then c.with_bed = c.with_bed + 1 end
        if door and bed then c.rooms = c.rooms + 1 end
        if not door and #c.samples < 6 then
            table.insert(c.samples, {x1 = r.x1, y1 = r.y1, x2 = r.x2, y2 = r.y2, z = r.z, bed = bed or nil})
        end
    end
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.BED) do
            local inzone = false
            for _, k in ipairs(zone_types(b.centerx, b.centery, b.z)) do
                if k == 'Bedroom' or k == 'Dormitory' or k == 'Hospital' or k == 'Barracks' then inzone = true end
            end
            if not inzone then c.loose_beds = c.loose_beds + 1 end
        end
    end)
    return c
end

-- Report: rooms with gaps in their walls, and planned walls held by a mark.
function room_gaps_report()
    local _, rooms, total = room_gaps(0)
    local ok, census = pcall(room_census)
    return {rooms = rooms, gaps = total, stalled = stalled_walls(false), census = ok and census or nil}
end

-- Build walls back in the gaps (REPAIR_MAX at a time), level by level.
function repair_rooms(dry_run)
    local gaps, rooms, total = room_gaps(REPAIR_MAX)
    local freed = stalled_walls(not dry_run)
    if #gaps == 0 then
        if freed > 0 then return {ok = true, walls = 0, freed = freed, dry_run = dry_run or nil} end
        return {ok = false, rejected = true, error = 'no room has a gap in its walls'}
    end
    local by_z = {}
    for _, g in ipairs(gaps) do
        if not dry_run then clear_smooth(g.x, g.y, g.z) end
        by_z[g.z] = by_z[g.z] or {}
        table.insert(by_z[g.z], {x = g.x, y = g.y, text = g.door and 'd' or 'Cw'})
    end
    local placed = 0
    for z, cells in pairs(by_z) do
        local okd, dry = pcall(quickfort_apply, 'build', cells, z, 0, 0, 'run', true)
        if okd and stat(dry, 'build_designated') > 0 then
            if dry_run then
                placed = placed + stat(dry, 'build_designated')
            else
                local okr, real = pcall(quickfort_apply, 'build', cells, z, 0, 0)
                if okr then placed = placed + stat(real, 'build_designated') end
            end
        end
    end
    if placed == 0 then return {ok = false, error = 'the game would not place walls in the rooms\' gaps'} end
    return {ok = true, walls = placed, rooms = rooms, gaps = total, freed = freed > 0 and freed or nil,
            dry_run = dry_run or nil}
end

-- --- the cistern (water step W2): planned only, nothing dug yet ----------------------
--
-- A cistern: a 5x5 room of solid rock right under a fort floor, at the level
-- of still water nearby (a pool, lake or cavern lake: never a river, whose
-- water can be under pressure), joined to it by a one-tile tunnel through
-- solid rock. A floodgate in the tunnel beside the cistern (worked by a
-- lever on the fort floor above) lets water in and shuts it out; the well
-- stands on the fort floor over the cistern's middle. Still water only ever
-- rises to its own level, so it fills the cistern and never comes up the
-- well's hole into the fort. Dug later from the cistern outwards, the last
-- tile beside the water (the plug) cut last, once the floodgate stands.
CISTERN_HALF = 2                 -- a 5x5 room
CISTERN_RADIUS = 30              -- how far from the fort the water may be
CISTERN_MAX_TUNNEL = 30
CISTERN_MIN_WATER = 20           -- tiles of water near the intake (a puddle won't do)
-- (0.104.94) surface water evaporates and freezes: Teacheroar's cistern drew
-- from a stagnant surface pool's edge, which dried to a bare ramp. A surface
-- source needs a bigger body and counts as if 20 tiles further off.
CISTERN_MIN_SURFACE_WATER = 100
CISTERN_SURFACE_PENALTY = 60
CISTERN_DRY_DAYS = 28            -- the source dry this long while filling: the cistern is retired
CISTERN_LEVEL_MIN = 4        -- (0.104.119) this deep and not rising for CISTERN_LEVEL_DAYS: full enough
CISTERN_LEVEL_DAYS = 14
-- (0.104.100) a floodgate shut for a flood (dwarves in deep water) while filling
-- reopens when nobody has stood in deep water this many days; after
-- CISTERN_MAX_REOPENS floods in a row it stays shut and says so
CISTERN_REOPEN_DAYS = 3
CISTERN_MAX_REOPENS = 3

-- Citizens standing in deep water (4/7 or more, not magma) anywhere: the flood sign.
function citizens_in_deep_water()
    local n = 0
    pcall(function()
        for _, p in ipairs(citizen_positions()) do
            local t = tile_info(p.x, p.y, p.z)
            if t and t.liquid and not t.magma and t.depth >= 4 then n = n + 1 end
        end
    end)
    return n
end
CISTERN_LEVELS = 6               -- busiest fort levels tried
CISTERN_SECONDS = 3

local function still_water(t)
    return t ~= nil and t.liquid and not t.magma and not t.salt and t.depth >= 4
        and t.material ~= 'RIVER' and t.material ~= 'BROOK'
end

local DIR8 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}
local DIR4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

-- Water tiles connected to (x, y, z) on its level, counted up to `cap`.
local function water_extent(x, y, z, cap)
    local seen, queue, head = {[x .. ',' .. y] = true}, {{x, y}}, 1
    while head <= #queue and #queue < cap do
        local c = queue[head]
        head = head + 1
        for _, d in ipairs(DIR8) do
            local nx, ny = c[1] + d[1], c[2] + d[2]
            local k = nx .. ',' .. ny
            if not seen[k] then
                local t = tile_info(nx, ny, z)
                if t and t.liquid and not t.magma then
                    seen[k] = true
                    table.insert(queue, {nx, ny})
                end
            end
        end
    end
    return #queue
end

-- (0.100, review) Is this water safe to let into a cistern under the fort?
-- Water under pressure (falling from higher up) rises to one level below
-- its source: a body that also holds water a level up, or that meets a
-- river or brook, could push up the cistern's stair and the well's hole.
-- The connected water on its level (up to `cap` tiles) is checked for water
-- right above it and for river tiles. Returns ok, why.
function water_body_safe(x, y, z, cap)
    cap = cap or 3000
    local seen, queue, head = {[x .. ',' .. y] = true}, {{x, y}}, 1
    while head <= #queue do
        local c = queue[head]
        head = head + 1
        local here = tile_info(c[1], c[2], z)
        if here and (here.material == 'RIVER' or here.material == 'BROOK') then
            return false, 'that water joins a river or brook (it can be under pressure)'
        end
        local up = tile_info(c[1], c[2], z + 1)
        if up and up.liquid then
            return false, 'that water goes on up a level (its weight could push it up into the fort)'
        end
        if #queue < cap then
            for _, d in ipairs(DIR8) do
                local nx, ny = c[1] + d[1], c[2] + d[2]
                local k = nx .. ',' .. ny
                if not seen[k] then
                    seen[k] = true
                    local t = tile_info(nx, ny, z)
                    if t and t.liquid and not t.magma then table.insert(queue, {nx, ny}) end
                end
            end
        end
    end
    -- (review) too big to see all of: not known safe (a cavern lake may hold
    -- water higher up beyond what was looked at)
    if #queue >= cap then return false, 'that water is too big to check for water above it' end
    return true
end

-- The tunnel: from the cistern's wall outwards through solid rock (each
-- tile's 8 neighbours rock, the cistern, the tunnel or, for the plug, the
-- water) to a tile beside still water. {path = {{x, y}...}, water = {x, y}}.
local function tunnel_to_water(c, z)
    local function in_room(x, y) return x >= c.x1 and x <= c.x2 and y >= c.y1 and y <= c.y2 end
    local starts = {}
    for x = c.x1, c.x2 do
        table.insert(starts, {x, c.y1 - 1}); table.insert(starts, {x, c.y2 + 1})
    end
    for y = c.y1, c.y2 do
        table.insert(starts, {c.x1 - 1, y}); table.insert(starts, {c.x2 + 1, y})
    end
    local prev, queue, head = {}, {}, 1
    for _, p in ipairs(starts) do
        local k = p[1] .. ',' .. p[2]
        prev[k] = false
        table.insert(queue, {p[1], p[2], 1})
    end
    while head <= #queue do
        local x, y, n = table.unpack(queue[head])
        head = head + 1
        local t = tile_info(x, y, z)
        if solid_rock(t) then
            -- beside still water: this is the plug
            for _, d in ipairs(DIR4) do
                local w = tile_info(x + d[1], y + d[2], z)
                if still_water(w) then
                    local ok = true
                    for _, e in ipairs(DIR8) do
                        local nx, ny = x + e[1], y + e[2]
                        local nt = tile_info(nx, ny, z)
                        if not (solid_rock(nt) or (nt and nt.liquid and not nt.magma) or in_room(nx, ny)
                                or prev[nx .. ',' .. ny] ~= nil) then
                            ok = false
                        end
                    end
                    if ok and prev[x .. ',' .. y] then      -- (at least two tiles: a floodgate, then the plug)
                        local path = {}
                        local px, py = x, y
                        while true do
                            table.insert(path, 1, {x = px, y = py})
                            local pr = prev[px .. ',' .. py]
                            if not pr then break end
                            px, py = pr[1], pr[2]
                        end
                        return {path = path, water = {x = x + d[1], y = y + d[2]}}
                    end
                end
            end
            if n < CISTERN_MAX_TUNNEL then
                -- (no water even at a corner: water flows diagonally too, so a
                -- tunnel tile touching it would flood when dug)
                local clear = true
                for _, e in ipairs(DIR8) do
                    local nt = tile_info(x + e[1], y + e[2], z)
                    if not (solid_rock(nt) or in_room(x + e[1], y + e[2])) then clear = false end
                end
                if clear then
                    for _, d in ipairs(DIR4) do
                        local nx, ny = x + d[1], y + d[2]
                        local k = nx .. ',' .. ny
                        if prev[k] == nil and not in_room(nx, ny) then
                            prev[k] = {x, y}
                            table.insert(queue, {nx, ny, n + 1})
                        end
                    end
                end
            end
        end
    end
    return nil
end

-- --- the cistern, second design (0.104.145) ------------------------------------
--
-- The player, 31 Oct: the first cistern couldn't work and would have flooded
-- the fort. Water in DF has PRESSURE: water falling onto full water
-- teleports along full tiles to as high as one level under where it came
-- from. The first design dug the cistern on its source's own level (z168)
-- beside a pond that stands on z168-170: pressure could reach z169, the
-- well's level. Its source tile had also dried to a bare ramp.
--
-- Two ways in, both pressure-safe:
--   level  the source on the cistern's own level, its water with nothing above
--          it anywhere in the body (it can never stand higher than the room)
--   shaft  the source up to CISTERN_MAX_RISE levels higher (a deep pond or a
--          cavern lake): a tunnel on the source's level to a shaft of stairs
--          straight down through solid rock to a tile DIAGONAL to the room's
--          corner. Pressure never passes a diagonal, so past it the water
--          only spreads level: it fills the room and can't climb the well's
--          stair. The tunnel and shaft (under pressure) are rock all round,
--          above and below.
-- The AI picks among the sources itself (surface, underground pool, cavern
-- lake), by distance, size, and what the brain tells it (`prefs`: the
-- climate freezes, a danger in the caverns).
CISTERN_V = 2
CISTERN_MAX_RISE = 8
CISTERN_CAVERN_PENALTY = 40
CISTERN_FREEZE_PENALTY = 60
CISTERN_DANGER_PENALTY = 1000
CISTERN_STAGNANT_PENALTY = 20
CISTERN_PREFS_KEY = 'ai-overseer/cistern_prefs'

function cistern_prefs(set)
    if type(set) == 'table' then
        pcall(dfhack.persistent.saveSiteData, CISTERN_PREFS_KEY,
              {freezes = set.freezes == true, cavern_danger = set.cavern_danger == true})
    end
    local ok, d = pcall(dfhack.persistent.getSiteData, CISTERN_PREFS_KEY, {})
    return ok and type(d) == 'table' and d or {}
end

-- every one of the 8 neighbours solid rock (or allowed)
local function ring_solid(x, y, z, allowed)
    for _, e in ipairs(DIR8) do
        local nx, ny = x + e[1], y + e[2]
        if not (allowed and allowed(nx, ny)) and not solid_rock(tile_info(nx, ny, z)) then return false end
    end
    return true
end

-- A river or brook in the body (always under pressure: never a source).
local function body_has_river(x, y, z, cap)
    local seen, queue, head = {[x .. ',' .. y] = true}, {{x, y}}, 1
    while head <= #queue and #queue < (cap or 400) do
        local c = queue[head]
        head = head + 1
        local here = tile_info(c[1], c[2], z)
        if here and (here.material == 'RIVER' or here.material == 'BROOK') then return true end
        for _, d in ipairs(DIR8) do
            local nx, ny = c[1] + d[1], c[2] + d[2]
            local k = nx .. ',' .. ny
            if not seen[k] then
                seen[k] = true
                local t = tile_info(nx, ny, z)
                if t and t.liquid and not t.magma then table.insert(queue, {nx, ny}) end
            end
        end
    end
    return false
end

-- A tile over water that holds it down: a wall, or a floor (a dug tile's
-- floor belongs to it, so water can't rise through it). Not open space, a
-- stair, a ramp or a channel.
local function capped(t)
    return t ~= nil and (t.shape == 'WALL' or t.shape == 'FLOOR') and not t.liquid
end

-- the tunnel under pressure: capped over every tile but the plug
local function tunnel_closed(path, z)
    for i = 1, #path - 1 do
        if not capped(tile_info(path[i].x, path[i].y, z + 1)) then return false end
    end
    return true
end

local function source_kind(w)
    return w.feature and 'cavern lake' or (w.outside and 'surface pool' or 'underground pool')
end

-- The score's extra for a source (lower is better) and why, in words.
local function source_cost(w, extent, prefs)
    local kind = source_kind(w)
    local cost, why = 0, {}
    if kind == 'surface pool' then
        cost = cost + CISTERN_SURFACE_PENALTY
        if prefs.freezes then cost = cost + CISTERN_FREEZE_PENALTY; table.insert(why, 'it freezes in winter') end
    elseif kind == 'cavern lake' then
        cost = cost + CISTERN_CAVERN_PENALTY
        if prefs.cavern_danger then cost = cost + CISTERN_DANGER_PENALTY; table.insert(why, 'a danger in the caverns') end
    end
    if w.stagnant then cost = cost + CISTERN_STAGNANT_PENALTY; table.insert(why, 'stagnant') end
    cost = cost - math.min(30, extent // 20)
    return cost, kind, why
end

-- The shaft way in, from one of the room's four outer corners.
local function shaft_to_water(c, z, water_z, deadline)
    local corners = {{c.x1 - 1, c.y1 - 1, c.x1, c.y1}, {c.x2 + 1, c.y1 - 1, c.x2, c.y1},
                     {c.x1 - 1, c.y2 + 1, c.x1, c.y2}, {c.x2 + 1, c.y2 + 1, c.x2, c.y2}}
    local found = {}
    for _, k in ipairs(corners) do
        local bx, by, rx, ry = k[1], k[2], k[3], k[4]
        local function is_corner(nx, ny) return nx == rx and ny == ry end
        if solid_rock(tile_info(bx, by, z)) and ring_solid(bx, by, z, is_corner) then
            for rise = 1, CISTERN_MAX_RISE do
                if deadline and os.clock() > deadline then break end
                local zs = z + rise
                if not solid_rock(tile_info(bx, by, zs)) or not ring_solid(bx, by, zs) then break end
                if water_z[zs] and capped(tile_info(bx, by, zs + 1)) then
                    local tun = tunnel_to_water({x1 = bx, y1 = by, x2 = bx, y2 = by}, zs)
                    if tun and tunnel_closed(tun.path, zs) then
                        table.insert(found, {tun = tun, zs = zs, shaft = {x = bx, y = by}, corner = {x = rx, y = ry},
                                             rise = rise})
                    end
                end
            end
        end
    end
    return found
end

-- The plan (nothing is designated): {v, source, cistern = {x1, y1, x2, y2, z},
-- well, floodgate, plug, tunnel = n tiles, tunnel_path, intake_z, shaft?, lever}
-- or nil, why. first, last: which of the busiest levels to look at (the
-- bridge asks one level a call). The plan carries its `score` (lower is
-- better) and `considered` (the best score of each kind of source).
function plan_cistern(first, last)
    local area = fort_scan_area(CISTERN_RADIUS)
    if not area then return nil, 'no citizens' end
    local prefs = cistern_prefs()
    local deadline = os.clock() + CISTERN_SECONDS
    local best, best_score, why = nil, nil, nil
    local considered = {}
    for i = first or 1, math.min(last or CISTERN_LEVELS, #area.levels) do
        local zw = area.levels[i].z
        local z = zw - 1
        -- the levels with still water near the fort, from the cistern's up
        local water_z, any = {}, false
        for zz = z, z + CISTERN_MAX_RISE do
            for y = area.y1, area.y2, 2 do
                for x = area.x1, area.x2, 2 do
                    if still_water(tile_info(x, y, zz)) then water_z[zz] = true break end
                end
                if water_z[zz] then any = true break end
            end
        end
        if any then
            for y = area.y1 + 4, area.y2 - 4 do
                if os.clock() > deadline then break end
                for x = area.x1 + 4, area.x2 - 4 do
                    if os.clock() > deadline then break end
                    -- a fort floor for the well, a solid 7x7 of rock under it, and
                    -- nothing over the room the water could climb into (a floor or a wall)
                    local f = tile_info(x, y, zw)
                    if f and f.shape == 'FLOOR' and not f.outside and not f.building and not f.liquid
                            and area.groups[walk_group(x, y, zw)] and not building_at(x, y, zw) then
                        local ok = true
                        for dy = -CISTERN_HALF - 1, CISTERN_HALF + 1 do
                            for dx = -CISTERN_HALF - 1, CISTERN_HALF + 1 do
                                if not solid_rock(tile_info(x + dx, y + dy, z)) then ok = false break end
                                if math.abs(dx) <= CISTERN_HALF and math.abs(dy) <= CISTERN_HALF then
                                    if not capped(tile_info(x + dx, y + dy, zw)) then ok = false break end
                                end
                            end
                            if not ok then break end
                        end
                        if ok then
                            local c = {x1 = x - CISTERN_HALF, y1 = y - CISTERN_HALF,
                                       x2 = x + CISTERN_HALF, y2 = y + CISTERN_HALF, z = z}
                            local options = {}
                            -- level: the source on the room's level, nothing over its water
                            if water_z[z] then
                                local tun = tunnel_to_water(c, z)
                                if tun and water_body_safe(tun.water.x, tun.water.y, z) then
                                    table.insert(options, {tun = tun, zs = z, rise = 0})
                                elseif tun then
                                    local _, unsafe = water_body_safe(tun.water.x, tun.water.y, z)
                                    why = why or unsafe
                                end
                            end
                            -- shaft: the source higher up, through a diagonal
                            for _, o in ipairs(shaft_to_water(c, z, water_z, deadline)) do table.insert(options, o) end
                            if #options == 0 then
                                why = why or 'no tunnel through solid rock from a cistern site to still water'
                            end
                            for _, o in ipairs(options) do
                                local tun, zs = o.tun, o.zs
                                local w = tile_info(tun.water.x, tun.water.y, zs)
                                local ext = water_extent(tun.water.x, tun.water.y, zs, 600)
                                if not w then
                                    -- (gone)
                                elseif ext < CISTERN_MIN_WATER then
                                    why = 'the still water reachable is only a puddle'
                                elseif w.outside and ext < CISTERN_MIN_SURFACE_WATER then
                                    why = 'the surface water reachable is too small (it dries up and freezes)'
                                elseif body_has_river(tun.water.x, tun.water.y, zs) then
                                    why = 'that water joins a river or brook (it can be under pressure)'
                                else
                                    local cost, kind, whys = source_cost(w, ext, prefs)
                                    local score = #tun.path * 3 + o.rise * 4 + math.abs(x - area.cx) + math.abs(y - area.cy)
                                        + (i - 1) * 20 + cost
                                    if not considered[kind] or score < considered[kind] then considered[kind] = score end
                                    if not best_score or score < best_score then
                                        best_score = score
                                        best = {v = CISTERN_V, score = score, cistern = c, well = {x = x, y = y, z = zw},
                                                floodgate = tun.path[1], plug = tun.path[#tun.path],
                                                tunnel = #tun.path, tunnel_path = tun.path, water = tun.water,
                                                intake_z = zs, shaft = o.shaft, corner = o.corner, rise = o.rise,
                                                source = kind, source_why = #whys > 0 and table.concat(whys, ', ') or nil,
                                                stagnant = w.stagnant or nil, extent = ext,
                                                elevation = ez(z), intake_elevation = ez(zs)}
                                    end
                                end
                            end
                        end
                    end
                end
            end
        end
    end
    if best then
        best.considered = considered
        -- a lever on the fort floor beside the well
        for _, d in ipairs(DIR8) do
            local lx, ly = best.well.x + d[1] * 2, best.well.y + d[2] * 2
            local t = tile_info(lx, ly, best.well.z)
            if t and t.shape == 'FLOOR' and not t.building and not building_at(lx, ly, best.well.z) then
                best.lever = {x = lx, y = ly, z = best.well.z}
                break
            end
        end
        return best
    end
    return nil, why or 'no still, fresh water near the fort within reach of a cistern under a fort level'
end

-- (0.104.145) Is the cistern still closed where the water goes? The room's
-- ring (rock but the well's stair and the corner or tunnel), rock under the
-- room, a floor or wall over it but the well; the tunnel and shaft rock all
-- round. Returns ok, where (in words) when not.
-- (0.104.168) and, when not, every open spot found: {x, y, z, fix = 'wall' |
-- 'floor' | nil (nothing the AI can build there), words}, so the AI can close
-- them itself (cistern_close_gaps); `where` is still the first.
function cistern_sealed(p, stage)
    local d_stage_hole = stage == 'hole' or stage == 'well' or stage == 'done'
    local c, z = p.cistern, p.cistern.z
    local zi = p.intake_z or z
    local open_ = {}
    local function mark(x, y, zz) open_[x .. ',' .. y .. ',' .. zz] = true end
    for yy = c.y1, c.y2 do for xx = c.x1, c.x2 do mark(xx, yy, z) end end
    for _, t in ipairs(p.tunnel_path or {}) do mark(t.x, t.y, zi) end
    if p.shaft then
        for zz = z, zi do mark(p.shaft.x, p.shaft.y, zz) end
    end
    local function closed(x, y, zz)
        if open_[x .. ',' .. y .. ',' .. zz] then return true end
        local t = tile_info(x, y, zz)
        -- (review) any wall holds water, a built one too (the player's repair)
        return (t ~= nil and t.shape == 'WALL' and not t.liquid)
            or (t and t.liquid and zz == zi and x == p.water.x and y == p.water.y)
    end
    local function where(x, y, zz) return ('x%d y%d elevation %d'):format(x, y, ez(zz)) end
    -- (0.104.168) every gap collected (each tile once), not just the first
    local gaps, seen_gap = {}, {}
    local function gap(fix, words, x, y, zz)
        local k = x .. ',' .. y .. ',' .. zz
        if seen_gap[k] then return end
        seen_gap[k] = true
        table.insert(gaps, {x = x, y = y, z = zz, fix = fix, words = words .. where(x, y, zz)})
    end
    -- the room: its ring and what lies under and over it
    for yy = c.y1 - 1, c.y2 + 1 do
        for xx = c.x1 - 1, c.x2 + 1 do
            local inside = xx >= c.x1 and xx <= c.x2 and yy >= c.y1 and yy <= c.y2
            if not inside and not closed(xx, yy, z) then gap('wall', 'the cistern\'s wall is open at ', xx, yy, z) end
            if inside then
                local here = tile_info(xx, yy, z)
                if here and (here.shape == 'EMPTY' or here.shape == 'RAMP_TOP' or here.shape == 'STAIR_DOWN'
                        or here.shape == 'STAIR_UPDOWN' or here.shape == 'RAMP')
                        and not (xx == p.well.x and yy == p.well.y and d_stage_hole) then
                    gap('floor', 'the cistern\'s floor is open at ', xx, yy, z)
                end
                if not (xx == p.well.x and yy == p.well.y) and not capped(tile_info(xx, yy, z + 1)) then
                    gap('floor', 'the cistern\'s roof is open at ', xx, yy, z + 1)
                end
            end
        end
    end
    -- the tunnel (under pressure): rock all round, over and under; the plug's water side excepted
    local path = p.tunnel_path or {}
    for i = 1, #path - 1 do
        local q = path[i]
        for _, e in ipairs(DIR8) do
            local nx, ny = q.x + e[1], q.y + e[2]
            local zz = zi
            local inroom = zi == z and nx >= c.x1 and nx <= c.x2 and ny >= c.y1 and ny <= c.y2
            if not inroom and not closed(nx, ny, zz) then
                -- (water beside the plug's neighbours is the source itself)
                local t = tile_info(nx, ny, zz)
                if not (t and t.liquid and math.abs(nx - p.plug.x) <= 1 and math.abs(ny - p.plug.y) <= 1) then
                    gap('wall', 'the cistern\'s tunnel is open at ', nx, ny, zz)
                end
            end
        end
        if p.shaft and not capped(tile_info(q.x, q.y, zi + 1)) then
            gap('floor', 'the tunnel\'s roof is open at ', q.x, q.y, zi + 1)
        end
    end
    -- the tunnel's own tiles: dug floors (a channel or a stair would let it down)
    for i = 1, #path - 1 do
        local q = tile_info(path[i].x, path[i].y, zi)
        if q and (q.shape == 'EMPTY' or q.shape == 'RAMP_TOP' or q.shape == 'STAIR_DOWN' or q.shape == 'STAIR_UPDOWN') then
            gap('floor', 'the cistern\'s tunnel floor is open at ', path[i].x, path[i].y, zi)
        end
    end
    -- the shaft: rock all round on every level, the corner diagonal at the bottom
    if p.shaft then
        local foot = tile_info(p.shaft.x, p.shaft.y, z)
        if foot and foot.shape ~= 'STAIR_UP' and foot.shape ~= 'WALL' then
            gap(nil, 'the shaft\'s foot is open below at ', p.shaft.x, p.shaft.y, z)
        end
        for zz = z, zi do
            for _, e in ipairs(DIR8) do
                local nx, ny = p.shaft.x + e[1], p.shaft.y + e[2]
                local ok_ = closed(nx, ny, zz) or (zz == z and p.corner and nx == p.corner.x and ny == p.corner.y)
                if not ok_ then gap('wall', 'the cistern\'s shaft is open at ', nx, ny, zz) end
            end
        end
        if not capped(tile_info(p.shaft.x, p.shaft.y, zi + 1)) then
            gap('floor', 'the shaft\'s top is open at ', p.shaft.x, p.shaft.y, zi + 1)
        end
    end
    if #gaps > 0 then return false, gaps[1].words, gaps end
    return true
end

-- --- building the cistern: one step a call ------------------------------------------
--
--   dig       stairs down from the well spot into the cistern's middle, the
--             room and the tunnel dug (all but the plug)
--   build     the floodgate (first tunnel tile) and the lever placed
--   link      the lever linked to the floodgate
--   open      the floodgate opened (a pull) so the water can come through
--   plug      the plug dug: the water comes in (the miner goes back out
--             through the open floodgate and up the stairs)
--   fill      waiting for 6/7 in the cistern, then the floodgate shut
--   hole      the down stair over the cistern channelled into the well's hole
--   well      the well built over it
--   done      kept: the AI opens the floodgate when the cistern falls under
--             3/7 and shuts it at 6/7 (cistern_status reports it)
-- State in site data 'ai-overseer/cistern'.
CISTERN_KEY = 'ai-overseer/cistern'
CISTERN_FULL, CISTERN_LOW = 6, 3

function cistern_data()
    local ok, d = pcall(dfhack.persistent.getSiteData, CISTERN_KEY, {})
    return ok and type(d) == 'table' and d.stage and d or nil
end

local function save_cistern(d) pcall(dfhack.persistent.saveSiteData, CISTERN_KEY, d) end

local function room_tiles(c)
    local out = {}
    for y = c.y1, c.y2 do
        for x = c.x1, c.x2 do table.insert(out, {x = x, y = y}) end
    end
    return out
end

-- {id, built, closed} of the building of `kind` at a tile, or nil.
local function building_info(x, y, z, kind)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b then return nil end
    local okt, t = pcall(function() return df.building_type[b:getType()] end)
    if kind and (not okt or t ~= kind) then return nil end
    local closed
    pcall(function() closed = b.gate_flags.closed end)
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage(), closed = closed}
end

-- (0.100, review) a pull already waiting for a dwarf: a second one queued
-- now would undo it (two pulls shut the floodgate and open it again)
function lever_pull_pending(lever_id)
    local ok, yes = pcall(function()
        local b = df.building.find(lever_id)
        for _, j in ipairs(b and b.jobs or {}) do
            if j.job_type == df.job_type.PullLever then return true end
        end
        return false
    end)
    return ok and yes
end

-- instant: the lever acts now, no dwarf needed (DFHack's lever --instant),
-- for a flood in the fort, when the lever may stand in the water
local function pull(lever_id, instant)
    if not instant and lever_pull_pending(lever_id) then
        return true, 'a dwarf is already on the way to pull it', true
    end
    local args = {'lever', 'pull', '--id', tostring(lever_id)}
    if instant then table.insert(args, '--instant') end
    local out, rv = dfhack.run_command_silent(table.unpack(args))
    return rv == CR_OK, tostring(out or '')
end

-- Items of a kind the fort has: free (no building, job or trader holds them,
-- not forbidden) and reserved (a job holds them: a construction waiting is
-- getting its part).
function count_items(tname)
    local free, reserved = 0, 0
    pcall(function()
        for _, item in ipairs(df.global.world.items.other[tname]) do
            local f = item.flags
            if not (f.forbid or f.in_building or f.construction or f.removed or f.garbage_collect
                    or f.trader or f.dump or f.hostile) then
                if f.in_job then reserved = reserved + 1 else free = free + 1 end
            end
        end
    end)
    return free, reserved
end

-- (0.104.94) What lies on the water's way in: each tunnel tile, the plug and
-- the source (shape and depth, or ice): Teacheroar's cistern sat at 0/7 for
-- hours with nothing to say why.
function cistern_path(p)
    local z = p.intake_z or p.cistern.z
    local function desc(pt)
        local t = pt and tile_info(pt.x, pt.y, z)
        if not t then return '?' end
        if t.material == 'FROZEN_LIQUID' then return 'ice' end
        local sh = tostring(t.shape):lower()
        if sh == 'wall' then sh = 'wall (' .. tostring(t.material):lower() .. (t.designated and ', marked' or '') .. ')' end
        return t.liquid and (sh .. ' ' .. t.depth .. '/7') or sh
    end
    local tunnel = {}
    for i = 1, #(p.tunnel_path or {}) - 1 do table.insert(tunnel, desc(p.tunnel_path[i])) end
    return {tunnel = tunnel, plug = desc(p.plug), source = desc(p.water)}
end

local function path_words(path)
    return ('tunnel %s; plug %s; source %s'):format(#path.tunnel > 0 and table.concat(path.tunnel, ', ') or 'none',
                                                    path.plug, path.source)
end

-- How it stands: stage, depth in the cistern's middle, the floodgate's state.
function cistern_status()
    local d = cistern_data()
    if not d then return nil end
    local p = d.plan
    local t = tile_info(p.well.x, p.well.y, p.cistern.z)
    local gate = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
    local out = {stage = d.stage, depth = t and t.liquid and t.depth or 0, source = p.source,
            gate = gate and (gate.built and (gate.closed and 'shut' or 'open') or 'planned') or nil,
            elevation = ez(p.cistern.z), x = p.well.x, y = p.well.y,
            -- (0.104.145) the design, where the water comes from, a leak seen
            v = p.v or 1, intake_elevation = p.intake_z and ez(p.intake_z) or nil, shaft = p.shaft and true or nil,
            source_why = p.source_why, leak = d.leak, unsealed = d.unsealed,
            -- (0.104.168) why the AI can't close a gap itself (the player's then),
            -- and how many walls/floors it placed to close them
            unsealed_why = d.unsealed and d.unsealed_why or nil, sealing = nil}
    if d.unsealed and type(d.sealing) == 'table' then
        local n = 0
        for _ in pairs(d.sealing) do n = n + 1 end
        out.sealing = n > 0 and n or nil
    end
    if d.stage == 'filling' or d.stage == 'plug' then
        local okp, path = pcall(cistern_path, p)
        out.path = okp and path or nil
    end
    -- (0.104.145, review) every report while water can come in: still closed?
    -- (a dig beside the shaft or tunnel later floods that level)
    if gate and gate.built and not gate.closed then
        local oks, sealed, where = pcall(cistern_sealed, p, d.stage)
        if oks then
            out.sealed_now = sealed == true
            out.unsealed = (sealed ~= true) and where or d.unsealed
        end
    end
    -- (0.92.1) while its parts wait: the lever's state, and the floodgates and
    -- mechanisms there are (free, or taken by a job): the floodgate waited two
    -- years in region2 for a floodgate nobody made, the lever for a mechanism
    if d.stage == 'building' or d.stage == 'linking' then
        local lever = p.lever and building_info(p.lever.x, p.lever.y, p.well.z, 'Trap')
        out.lever = lever and (lever.built and 'built' or 'planned') or nil
        -- (0.104.141) the relinks asked for, whether linked, where the lever and
        -- the gate are, and why DF dropped the last link job (when it said)
        if d.stage == 'linking' then
            out.relinks = math.tointeger(d.relinks) or 0
            pcall(function()
                local lv = df.building.find(d.lever_id)
                for _, j in ipairs(lv and lv.jobs or {}) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then
                        out.link_pending = true
                        -- (0.104.143) whether a dwarf has taken it, or it is suspended
                        out.link_worker = dfhack.job.getWorker(j) ~= nil
                        out.link_suspended = j.flags.suspend or nil
                    end
                end
            end)
            -- (0.104.143) can the dwarves get beside the lever and the floodgate
            -- (a linker carries the mechanisms to both)?
            local function reach(x, y, z)
                local groups = {}
                pcall(function()
                    for _, u in ipairs(dfhack.units.getCitizens(true)) do
                        local g = dfhack.maps.getWalkableGroup(xyz2pos(dfhack.units.getPosition(u)))
                        if g and g ~= 0 then groups[g] = true end
                    end
                end)
                local seen = false
                for dy = -1, 1 do
                    for dx = -1, 1 do
                        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x + dx, y + dy, z))
                        if okg and g and g ~= 0 then
                            if groups[g] then return 'reachable' end
                            seen = true
                        end
                    end
                end
                return seen and 'cut off from the dwarves' or 'no open ground beside it'
            end
            pcall(function()
                if p.lever then out.lever_reach = reach(p.lever.x, p.lever.y, p.well.z) end
                out.gate_reach = reach(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z)
            end)
            out.link_why = d.link_why
            -- (0.104.143) with the elevation the game's screen shows (e)
            out.lever_at = p.lever and {x = p.lever.x, y = p.lever.y, z = p.well.z, e = ez(p.well.z)} or nil
            out.gate_at = {x = p.floodgate.x, y = p.floodgate.y, z = p.intake_z or p.cistern.z, e = ez(p.intake_z or p.cistern.z)}
            pcall(function()
                for _, lid in ipairs(reqscript('ai-gates').lever_links()[d.gate_id] or {}) do
                    if lid == d.lever_id then out.linked = true end
                end
            end)
        end
        out.floodgates_free, out.floodgates_reserved = count_items('FLOODGATE')
        -- (0.94.1) counted as the lever's link takes them (ai-gates), with
        -- what holds the ones it can't use
        local okg, mc = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
        if okg and mc then
            out.mechanisms_free, out.mechanisms_reserved = mc.usable, mc.reserved
            if next(mc.why) then out.mechanisms_held = mc.why end
        else
            out.mechanisms_free, out.mechanisms_reserved = count_items('TRAPPARTS')
        end
    end
    return out
end

local function designate(cells, z, mode)
    local okd, dry = pcall(quickfort_apply, mode, cells, z, 0, 0, 'run', true)
    local key = mode .. '_designated'
    if not okd or stat(dry, key) < #cells then return false end
    local okr, real = pcall(quickfort_apply, mode, cells, z, 0, 0)
    return okr and stat(real, key) >= 1
end

-- (0.104.151-152) A cavern well's two ways in from the cavern, closed.
-- The well is a hole (the wiki: no obstruction; swimmers path in through
-- wells), and its shaft is dug from a stair column beside it (0.104.13) that
-- runs down beside the shaft at every level. The one tile that opens into the
-- cavern is the shaft's lowest (its floor channelled away over the cavern's
-- air; the column's bottom step is an up stair, a floor under it). So:
--   the shaft gate: a hatch on that lowest shaft tile, on a lever beside the
--     well. A shut hatch stops the bucket, so it is opened once linked and
--     shut only while a danger is near (DFHack's lever --instant: no dwarf
--     runs to it), then opened again. Built from the column's bottom step.
--     The lever first; the hatch only once the lever stands and 2 mechanisms
--     are free for the link, so the well is never left blocked waiting.
--   the stair lid: only when the game won't build the gate, a hatch over the
--     column's top step, locked (DFHack forbids it); unlocked again while
--     dwarves must go down to build or relink a gate.
-- Kept in the project (`shaft_gate` = {lever = {x, y, z}, lever_id,
-- hatch_id, link_fails, impossible}). The review's points are marked "rv".
local STAIR_DOWN_SHAPE = {STAIR_DOWN = true, STAIR_UPDOWN = true}
SHAFT_LINK_FAILS_MAX = 3

local function shaft_bottom(p)
    local low
    for _, z in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
        if not low or z < low then low = z end
    end
    return low or (p.z - 1)
end

local function hatch_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b or b:getType() ~= df.building_type.Hatch then return nil end
    local closed = true
    pcall(function() closed = b.door_flags.closed end)
    local forbidden = false
    pcall(function() forbidden = b.door_flags.forbidden end)
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage(), closed = closed, forbidden = forbidden, b = b}
end

-- rv 14: a lever, not any trap
local function lever_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b or b:getType() ~= df.building_type.Trap then return nil end
    local okl, lever = pcall(function() return b.trap_type == df.trap_type.Lever end)
    if okl and not lever then return nil end
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage()}
end

local function free_floor(x, y, z, group)
    local t = tile_info(x, y, z)
    local g = walk_group(x, y, z)
    return t and t.shape == 'FLOOR' and not t.building and not t.designated and not t.liquid
        and not building_at(x, y, z) and g ~= 0 and (group == nil or g == group)
end

-- rv 12: outside the well's 3x3 (its furnishing would wait for the lever)
local function shaft_lever_spot(p)
    local a = anchor_of(p)
    local top = type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] or nil
    for _, r in ipairs({2, 3}) do
        for dy = -r, r do
            for dx = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = a.x + dx, a.y + dy
                    -- rv2 5: reachable from the stairs (the same walk group as their top)
                    if not (top and x == top.x and y == top.y)
                            and free_floor(x, y, p.z, top and walk_group(top.x, top.y, top.z) or nil) then
                        return {x = x, y = y, z = p.z}
                    end
                end
            end
        end
    end
end

local function job_of(building_id, jt)
    local ok, j = pcall(function()
        local b = df.building.find(building_id)
        for _, job in ipairs(b and b.jobs or {}) do
            if job.job_type == jt then return job end
        end
    end)
    return ok and j or nil
end

function shaft_gate_state(p)
    local g = p.shaft_gate or {}
    local a = anchor_of(p)
    local h = hatch_at(a.x, a.y, shaft_bottom(p))
    local lv = g.lever and lever_at(g.lever.x, g.lever.y, g.lever.z or p.z) or nil
    if g.impossible then return {state = 'none_possible', hatch = h, lever = lv} end
    if not g.lever then return {state = h and 'stray' or 'none', hatch = h} end
    if not lv then return {state = 'no_lever', hatch = h} end
    if not lv.built then return {state = 'building', hatch = h, lever = lv} end
    if not h then return {state = 'no_hatch', lever = lv} end
    if not h.built then return {state = 'building', hatch = h, lever = lv} end
    local linked = false
    local okl, links = pcall(function() return reqscript('ai-gates').lever_links() end)
    for _, lid in ipairs(okl and links[h.id] or {}) do if lid == lv.id then linked = true end end
    if not linked then
        return {state = job_of(lv.id, df.job_type.LinkBuildingToTrigger) and 'linking' or 'unlinked', hatch = h, lever = lv}
    end
    if job_of(lv.id, df.job_type.PullLever) then return {state = 'pulling', hatch = h, lever = lv} end
    return {state = h.closed and 'closed' or 'open', hatch = h, lever = lv}
end

local function free_mechanism_count()
    -- (0.104.156) by the link's own test when there is one (none where no dwarf can walk)
    local okc, c = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
    if okc and type(c) == 'table' and type(c.usable) == 'number' then return c.usable end
    local ok, n = pcall(function() return (count_items('TRAPPARTS')) end)
    return ok and n or 0
end

-- One step for each cavern well's shaft gate toward `want_closed`.
-- {ok, wells = [{project_id, was, stage?, error?}]}
function well_shaft_step(want_closed, dry_run)
    local data = load_projects()
    local wells, changed = {}, false
    for _, p in ipairs(data.list) do
        local st = p.shaft_stairs
        if p.kind == 'well' and type(st) == 'table' and st[1] and (p.phase == 'furnish' or p.phase == 'done') then
            local a, hz = anchor_of(p), shaft_bottom(p)
            local g = shaft_gate_state(p)
            local r = {project_id = p.id, was = g.state}
            local sg = p.shaft_gate
            -- rv 3: work below needs the stairs: a locked lid is unlocked
            if g.state ~= 'open' and g.state ~= 'closed' and g.state ~= 'none_possible' and not dry_run then
                local top = st[1]
                local lid = hatch_at(top.x, top.y, top.z)
                if lid and lid.forbidden then lid.b.door_flags.forbidden = false; r.unlocked_lid = true end
            end
            if g.state == 'none' or g.state == 'stray' or g.state == 'no_lever' then
                -- rv 2, 8: the lever first (a stray hatch kept: linked when the lever stands)
                local lv = (sg and sg.lever and free_floor(sg.lever.x, sg.lever.y, sg.lever.z or p.z)) and sg.lever
                    or shaft_lever_spot(p)
                if not lv then
                    r.error = 'no free floor near the well for the lever'
                elseif dry_run then
                    r.stage = 'place_lever'
                elseif designate({{x = lv.x, y = lv.y, text = 'Tl'}}, lv.z or p.z, 'build') then
                    p.shaft_gate = {lever = lv, link_fails = sg and sg.link_fails or nil}
                    r.stage, changed = 'lever_placed', true
                else
                    r.error = 'the game would not place the lever near the well'
                end
            elseif g.state == 'no_hatch' then
                -- rv 6: only with the lever up and 2 mechanisms free for the link
                local mech = free_mechanism_count()
                if mech < 2 then
                    r.stage, r.mechanisms = 'waiting_mechanisms', mech
                elseif dry_run then
                    r.stage = 'place_hatch'
                else
                    local okd, s = pcall(quickfort_apply, 'build', {{x = 0, y = 0, text = 'H'}}, hz, a.x, a.y, 'run', true)
                    if not okd or stat(s, 'build_designated') ~= 1 then
                        -- rv2 3: three refusals, not one, before the lid instead
                        sg.hatch_fails, changed = (sg.hatch_fails or 0) + 1, true
                        if sg.hatch_fails >= SHAFT_LINK_FAILS_MAX then sg.impossible = true end
                        r.error = 'the game would not build a hatch at the bottom of the shaft'
                            .. (sg.impossible and ' (3 times: the stair lid instead)' or '')
                    elseif designate({{x = a.x, y = a.y, text = 'H'}}, hz, 'build') then
                        r.stage = 'hatch_placed'
                    else
                        r.error = 'the game refused the hatch at the bottom of the shaft'
                    end
                end
            elseif g.state == 'unlinked' then
                -- (0.104.156) a link job asked for and gone with no link: DF
                -- cancelled it ("Item inaccessible", 25 times on 1 Nov). Lost 3
                -- times with the same mechanisms: no new job until others are free.
                local G = reqscript('ai-gates')
                if sg.link_asked and not dry_run then
                    sg.link_lost, sg.link_asked, changed = (sg.link_lost or 0) + 1, nil, true
                end
                local lp = sg.lever or {}
                local okf, cand = pcall(G.free_mechanisms, 2, {x = lp.x or a.x, y = lp.y or a.y, z = lp.z or p.z})
                local key = {}
                for _, m in ipairs(okf and type(cand) == 'table' and cand or {}) do table.insert(key, tostring(m.id)) end
                key = table.concat(key, ',')
                local lost = sg.link_lost or 0
                if lost >= SHAFT_LINK_FAILS_MAX and key == (sg.link_mechs or '') then
                    r.error = ('the link job was lost %d times (DF cancels it; mechanisms %s): waits for others')
                        :format(lost, key ~= '' and key or 'none')
                    r.link_lost = lost
                else
                    if lost >= SHAFT_LINK_FAILS_MAX and not dry_run then
                        sg.link_lost, changed = 0, true          -- other mechanisms: a fresh try
                    end
                    local res = dry_run and {ok = true} or G.link_lever(g.lever.id, g.hatch.id, false)
                    if res.ok then
                        r.stage = dry_run and 'link' or 'linking'
                        if not dry_run then
                            sg.link_asked, sg.link_mechs, changed = true, key, true
                            r.link_lost = sg.link_lost
                        end
                    else
                        r.error, r.mechanisms = res.error, res.mechanisms
                        -- rv 6: a link that keeps failing for another reason: the hatch
                        -- comes down (it would block the bucket for good), the lid instead
                        if not dry_run and not tostring(res.error or ''):find('mechanism') then
                            sg.link_fails, changed = (sg.link_fails or 0) + 1, true
                            if sg.link_fails >= SHAFT_LINK_FAILS_MAX then
                                pcall(dfhack.buildings.deconstruct, g.hatch.b)
                                sg.impossible = true
                                r.error = r.error .. ' (3 times: the shaft hatch taken down, the stair lid instead)'
                            end
                        end
                    end
                end
            elseif g.state == 'pulling' then
                -- rv 9: a dwarf on the way to pull it: called off (a late pull would
                -- toggle the gate the wrong way), and the gate set at once
                if not dry_run then
                    local j = job_of(g.lever.id, df.job_type.PullLever)
                    if j then pcall(dfhack.job.removeJob, j) end
                    if g.hatch.closed ~= (want_closed == true) then
                        local ok, out = pull(g.lever.id, true)
                        if not ok then r.error = 'lever pull failed: ' .. tostring(out):sub(1, 120) end
                    end
                end
                if not r.error then r.stage = want_closed and 'closed' or 'opened' end
            elseif g.state == 'open' or g.state == 'closed' then
                if sg.link_lost or sg.link_asked then sg.link_lost, sg.link_asked, changed = nil, nil, true end
                if sg.lever_id ~= g.lever.id or sg.hatch_id ~= g.hatch.id then
                    sg.lever_id, sg.hatch_id, changed = g.lever.id, g.hatch.id, true   -- rv 13
                end
                if (g.state == 'closed') ~= (want_closed == true) then
                    if dry_run then
                        r.stage = want_closed and 'close' or 'open'
                    else
                        -- (0.104.164) opened at once too: a dwarf's pull never came (Teacheroar,
                        -- 1 Nov: well 218 "open its shaft again" 49 times in 90 minutes, the
                        -- gate still shut), and the hatch only opens while no danger is near
                        local ok, out = pull(g.lever.id, true)
                        if ok then r.stage = want_closed and 'closed' or 'opened'
                        else r.error = 'lever pull failed: ' .. tostring(out):sub(1, 120) end
                    end
                else
                    r.stage = g.state
                end
            else
                r.stage = g.state            -- building, linking, none_possible: waits
            end
            table.insert(wells, r)
        end
    end
    if changed and not dry_run then save_projects(data) end
    if #wells == 0 then return {ok = false, rejected = true, error = 'no cavern well'} end
    local watch_started = false
    for _, r in ipairs(wells) do
        local linked = r.was == 'open' or r.was == 'closed' or r.was == 'pulling'
        if linked and not dry_run and shaft_watch_start() then watch_started = true end
    end
    local acted = watch_started
    for _, r in ipairs(wells) do
        if not r.error and r.stage and r.stage ~= r.was and r.stage ~= 'waiting_mechanisms' then acted = true end
    end
    if dry_run then return {ok = true, dry_run = true, wells = wells} end
    if acted then return {ok = true, wells = wells} end
    return {ok = false, rejected = true, wells = wells,
            error = wells[1].error or ('nothing to do: ' .. tostring(wells[1].stage or wells[1].was))}
end

-- (0.104.154) Planned buildings that wait (DFHack buildingplan): what each
-- still lacks, in buildingplan's own words ("Bucket (any material)"), its
-- place in the queue for that item, and why its job is suspended
-- (suspendmanager). Teacheroar, 1 Nov: the cavern well 85 days and its lever
-- waited with every part in store, a gate hatch 129 days "though 1 hatch
-- cover is free": the report said only "waiting". {n, list (40 at most,
-- the longest waiting first), by_type}.
PLANNED_MAX = 40

function planned_report()
    OFFSET = elevation_offset()
    local okb, bp = pcall(require, 'plugins.buildingplan')
    if not okb or not bp or not bp.isPlannedBuilding then return {error = 'no buildingplan'} end
    local oks, sm = pcall(require, 'plugins.suspendmanager')
    local why_fn
    if oks and sm then
        for _, fn in ipairs({'suspendmanager_suspensionDescription', 'suspensionDescription'}) do
            if sm[fn] then why_fn = sm[fn] break end
        end
    end
    local out, by_type, n = {}, {}, 0
    for _, b in ipairs(df.global.world.buildings.all) do
        local okp, planned = pcall(bp.isPlannedBuilding, b)
        if okp and planned then
            n = n + 1
            local kind = df.building_type[b:getType()] or tostring(b:getType())
            by_type[kind] = (by_type[kind] or 0) + 1
            local r = {id = b.id, kind = kind, x = b.centerx, y = b.centery, z = b.z, elevation = ez(b.z)}
            local j = b.jobs and b.jobs[0]
            if j then
                r.suspended = j.flags.suspend or nil
                if why_fn and j.flags.suspend then
                    local okw, w = pcall(why_fn, j)
                    if okw and w and tostring(w) ~= '' then r.why = tostring(w):sub(1, 100) end
                end
                local items = {}
                -- DF 53: job_items holds its list in `elements` (# fails on it)
                local okc, cnt = pcall(function() return #j.job_items end)
                if not okc then okc, cnt = pcall(function() return #j.job_items.elements end) end
                for i = 0, (okc and cnt or 0) - 1 do
                    local okd, d = pcall(bp.getDescString, b, i)
                    local okq, q = pcall(bp.getQueuePosition, b, i)
                    table.insert(items, {want = okd and tostring(d):sub(1, 80) or nil, queue = okq and q or nil})
                end
                if #items > 0 then r.items = items end
            end
            table.insert(out, r)
        end
    end
    table.sort(out, function(a, c) return a.id < c.id end)          -- older buildings first
    local list = {}
    for i = 1, math.min(PLANNED_MAX, #out) do list[i] = out[i] end
    return {n = n, list = list, by_type = by_type}
end

-- (0.104.153) A wild animal that attacks: a large predator, or one DF has
-- agitated. (Most of the caverns' thousands of creatures are neither.)
function hostile_wild(u)
    if not dfhack.units.isAnimal(u) or dfhack.units.isFortControlled(u) then return false end
    local okt, tame = pcall(dfhack.units.isTame, u)
    if okt and tame then return false end
    local oka, agit = pcall(function() return u.flags4.agitated_wilderness_creature end)
    if oka and agit then return true end
    local okp, pred = pcall(function() return df.creature_raw.find(u.race).caste[u.caste].flags.LARGE_PREDATOR end)
    return okp and pred or false
end

local function unit_flies(u)
    local ok, f = pcall(function() return u.enemy.caste_flags.FLIER end)
    return ok and f or false
end

-- (0.104.153) The shaft watcher: every SHAFT_WATCH_TICKS inside the game
-- (the brain reads the fort once a game day: a flier crosses 60 tiles
-- sooner), an open shaft gate is shut at once when an enemy comes near
-- below it: a danger (isDanger) or a flying hostile animal within
-- SHAFT_NEAR tiles, any hostile one within SHAFT_CLOSE tiles, or anything
-- hostile in the shaft itself. It only shuts; the brain opens it again once
-- the cavern is clear. Lives while the game runs; `well_lids` says whether
-- it is on, and the `well_shaft` action starts it.
SHAFT_WATCH_TICKS = 100
SHAFT_NEAR = 60
SHAFT_CLOSE = 20
SHAFT_WATCH = SHAFT_WATCH or {on = false}

local function shaft_threat_near(wells)
    for _, u in ipairs(df.global.world.units.active) do
        local ok, hit = pcall(function()
            if not dfhack.units.isActive(u) or dfhack.units.isDead(u) or dfhack.units.isCitizen(u, true) then return false end
            if u.flags1.caged or u.flags1.chained then return false end
            local danger = dfhack.units.isDanger(u)
            local wild = not danger and hostile_wild(u)
            if not (danger or wild) then return false end
            local fly = unit_flies(u)
            for _, w in ipairs(wells) do
                local d = math.max(math.abs(u.pos.x - w.x), math.abs(u.pos.y - w.y))
                if u.pos.z < w.hz then
                    if d <= SHAFT_CLOSE or (d <= SHAFT_NEAR and (danger or fly)) then return w end
                elseif u.pos.z < w.z and d <= 2 then
                    return w                        -- in the shaft or on its stairs
                end
            end
            return false
        end)
        if ok and hit then return hit, u end
    end
end

local function shaft_watch_tick()
    SHAFT_WATCH.timer = nil
    if not SHAFT_WATCH.on then return end
    local ok, err = pcall(function()
        local wells = {}
        for _, p in ipairs(load_projects().list) do
            -- a linked gate (its ids saved): only its hatch and lever read, not every
            -- building's links (this runs 12 times a game day)
            local sg = p.shaft_gate
            if p.kind == 'well' and sg and sg.lever_id and sg.hatch_id and not sg.impossible then
                local a = anchor_of(p)
                local h = hatch_at(a.x, a.y, shaft_bottom(p))
                if h and h.built and h.id == sg.hatch_id and not h.closed then
                    local pending = job_of(sg.lever_id, df.job_type.PullLever)
                    table.insert(wells, {x = a.x, y = a.y, z = p.z, hz = shaft_bottom(p), id = p.id,
                                         lever_id = sg.lever_id, pending = pending})
                end
            end
        end
        if #wells == 0 then return end
        local w, u = shaft_threat_near(wells)
        if w then
            if w.pending then pcall(dfhack.job.removeJob, w.pending) end
            pull(w.lever_id, true)
            SHAFT_WATCH.last = {project_id = w.id, tick = df.global.cur_year_tick, year = df.global.cur_year,
                                unit = u and u.id or nil}
        end
    end)
    SHAFT_WATCH.error = (not ok) and tostring(err):sub(1, 160) or nil
    SHAFT_WATCH.timer = dfhack.timeout(SHAFT_WATCH_TICKS, 'ticks', shaft_watch_tick)
end

function shaft_watch_start()
    if SHAFT_WATCH.on and SHAFT_WATCH.timer then return false end
    SHAFT_WATCH.on = true
    SHAFT_WATCH.timer = dfhack.timeout(SHAFT_WATCH_TICKS, 'ticks', shaft_watch_tick)
    return true
end

-- Each cavern well: {project_id, x, y, z, elevation (the column's top step),
-- state (the lid: none, planned, open, locked, blocked, gone), gate (the
-- shaft gate's state), gate_mechanisms?}.
function well_lids(probe)
    OFFSET = elevation_offset()
    local out = {}
    local data = load_projects()
    for _, p in ipairs(data.list) do
        local st = p.shaft_stairs
        if p.kind == 'well' and type(st) == 'table' and st[1] and (p.phase == 'furnish' or p.phase == 'done') then
            local top = st[1]
            local r = {project_id = p.id, x = top.x, y = top.y, z = top.z, elevation = ez(top.z)}
            local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(top.x, top.y, top.z))
            if okb and b then
                if b:getType() ~= df.building_type.Hatch then
                    r.state = 'blocked'
                elseif b:getBuildStage() < b:getMaxBuildStage() then
                    r.state = 'planned'
                else
                    local okf, f = pcall(function() return b.door_flags.forbidden end)
                    r.state = (okf and f) and 'locked' or 'open'
                    r.hatch_id = b.id
                end
            else
                local tl = tile_info(top.x, top.y, top.z)
                r.state = (tl and STAIR_DOWN_SHAPE[tl.shape]) and 'none' or 'gone'
            end
            local okg, g = pcall(shaft_gate_state, p)
            if okg and g then
                r.gate = g.state
                if g.state == 'no_hatch' or g.state == 'unlinked' then r.gate_mechanisms = free_mechanism_count() end
                -- (0.104.156) the ones the lever can reach (a link with others is cancelled)
                local sg = p.shaft_gate or {}
                if g.state == 'unlinked' and sg.lever then
                    local okm, m, far, far_at = pcall(reqscript('ai-gates').free_mechanisms, 2,
                                                      {x = sg.lever.x, y = sg.lever.y, z = sg.lever.z or p.z})
                    if okm and type(m) == 'table' then
                        r.gate_mechanisms_reachable = #m
                        if (far or 0) > 0 then r.gate_mechanisms_far = far end
                        if type(far_at) == 'table' and #far_at > 0 then
                            r.gate_mechanisms_far_at = table.concat(far_at, '; ')
                        end
                        local okg, lg = pcall(walk_group, sg.lever.x, sg.lever.y, sg.lever.z or p.z)
                        if okg then r.gate_lever_group = lg end
                    end
                end
                if sg.link_lost then r.gate_link_lost = sg.link_lost end
                if g.hatch then r.gate_hatch_built = g.hatch.built and true or false end
                r.gate_hatch_standing = g.hatch ~= nil or nil     -- rv2 1: a hatch still at the shaft's bottom
                if g.state == 'open' or g.state == 'closed' or g.state == 'pulling' then     -- (0.104.153)
                    r.watching = (SHAFT_WATCH.on and SHAFT_WATCH.timer ~= nil) and true or false
                    r.watch_error = SHAFT_WATCH.error
                    if SHAFT_WATCH.last and SHAFT_WATCH.last.project_id == p.id then r.watch_last = SHAFT_WATCH.last end
                    -- (0.104.165) what the watcher would shut it for now, by its own test: the
                    -- report's wild list holds only animals in a "Cavern" layer, and the brain
                    -- reopened the gate under a predator the watcher saw (Teacheroar, unit
                    -- 6300), the watcher shutting it again at once
                    local an = anchor_of(p)
                    local okn, hit, u = pcall(shaft_threat_near, {{x = an.x, y = an.y, z = p.z, hz = shaft_bottom(p)}})
                    if okn and hit and u then
                        local okr, nm = pcall(dfhack.units.getReadableName, u)
                        if okr and dfhack.df2utf then local okc, c = pcall(dfhack.df2utf, nm); if okc and c then nm = c end end
                        r.watch_near = {id = u.id, name = okr and nm or nil,
                                        pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}}
                    end
                end
            else
                r.gate_error = tostring(g):sub(1, 120)
            end
            table.insert(out, r)
        end
    end
    return out
end

-- The stair lid, only where the shaft gate can't be built: a hatch planned
-- where there is none (buildingplan waits for a hatch cover), a built one
-- locked. {ok, planned, locked, waiting}.
function seal_well_stairs(dry_run)
    local planned, locked, waiting = 0, 0, 0
    for _, r in ipairs(well_lids(false)) do
        if r.gate ~= 'none_possible' then
            -- the gate seals the cavern: the lid stays unlocked (the way down to it)
        elseif r.gate_hatch_standing then
            -- rv2 1: a failed hatch still stands shut at the shaft's bottom: a
            -- dwarf must go down these stairs to take it away first
            waiting = waiting + 1
        elseif r.state == 'none' then
            if dry_run then
                planned = planned + 1
            else
                local okq, s = pcall(quickfort_apply, 'build', {{x = 0, y = 0, text = 'H'}}, r.z, r.x, r.y)
                if okq and stat(s, 'build_designated') == 1 then planned = planned + 1 else waiting = waiting + 1 end
            end
        elseif r.state == 'open' then
            if not dry_run then
                local b = df.building.find(r.hatch_id)
                if b then b.door_flags.forbidden = true end
            end
            locked = locked + 1
        elseif r.state == 'planned' then
            waiting = waiting + 1
        end
    end
    if planned + locked == 0 then
        return {ok = false, rejected = true, error = 'no cavern well stair to close', waiting = waiting}
    end
    return {ok = true, planned = planned, locked = locked, waiting = waiting, dry_run = dry_run or nil}
end

-- Shut the cistern's floodgate now (a flood in the fort), whatever the stage.
function cistern_shut(dry_run)
    local d = cistern_data()
    if not d or not d.lever_id then return {ok = false, rejected = true, error = 'no cistern lever linked yet'} end
    local p = d.plan
    local gate = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
    if not gate or gate.closed then return {ok = false, rejected = true, error = 'the floodgate is already shut'} end
    if dry_run then return {ok = true, dry_run = true} end
    -- (0.100, review) at once: a queued pull waits for a dwarf to wade to
    -- the lever, and the planner asks again every cycle while dwarves are wet
    local ok, out = pull(d.lever_id, true)
    return {ok = ok, shut = ok, instant = true, error = not ok and out or nil}
end

-- (0.104.0) The cistern's room and its tunnel (all but the plug), the tiles
-- the water fills first.
function cistern_inside(p, z)
    local out = room_tiles(p.cistern)
    for i = 1, #p.tunnel_path - 1 do table.insert(out, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y}) end
    return out
end

-- (0.104.145) The tunnel's tiles (all but the plug), on the source's level.
function cistern_way(p)
    local out = {}
    for i = 1, #(p.tunnel_path or {}) - 1 do table.insert(out, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y}) end
    return out
end

-- How many living creatures stand on these tiles of level z.
function units_on_tiles(tiles, z)
    local set = {}
    for _, t in ipairs(tiles) do set[t.x .. ',' .. t.y] = true end
    local n = 0
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if u.pos.z == z and set[u.pos.x .. ',' .. u.pos.y] and not dfhack.units.isDead(u) then n = n + 1 end
        end
    end)
    return n
end

-- Items lying on these tiles of level z forbidden (nobody fetches them); how many.
function forbid_items_on(tiles, z)
    local n = 0
    for _, t in ipairs(tiles) do
        pcall(function()
            local block = dfhack.maps.getTileBlock(xyz2pos(t.x, t.y, z))
            if not block then return end
            for _, id in ipairs(block.items) do
                local it = df.item.find(id)
                if it and it.pos.x == t.x and it.pos.y == t.y and it.pos.z == z and it.flags.on_ground then
                    if not it.flags.forbid then it.flags.forbid = true; n = n + 1 end
                end
            end
        end)
    end
    return n
end

-- (0.104.168) THE PLAYER'S RULE: what the AI can set up in the game it does
-- itself. Teacheroar's cistern waited 20+ steps on "the cistern's shaft is
-- open at x105 y128" for the player to wall it. Now the AI builds the wall
-- (or, over the room, the tunnel and the shaft's top, a floor) at each open
-- spot itself, but never:
--   - in water, on a building, or on a stair or a ramp (a way up or down the
--     dwarves may walk: the player decides those);
--   - where the wall would cut a way: the open tile's walkable neighbours
--     (the cistern's own tiles left out) must still meet round it without it;
--   - with anyone on the tile, or in a hollow the wall would close off (a
--     pocket with no way off its level but through the gap).
-- Any open tile beside the shaft, the tunnel or the room lets the water out
-- (the shaft and tunnel are under pressure), so every gap is one to close.
CISTERN_GAP_WALL_ON = {FLOOR = true, EMPTY = true, PEBBLES = true, BOULDER = true, SHRUB = true, SAPLING = true}
CISTERN_GAP_POCKET_MAX = 400       -- tiles looked at beyond a gap
-- (0.104.168, review) ground a dwarf can stand on (open air and deep water are not)
CISTERN_STANDABLE = {FLOOR = true, PEBBLES = true, BOULDER = true, SHRUB = true, SAPLING = true, TWIG = true,
                     STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true, RAMP_TOP = true,
                     BROOK_BED = true}
-- ...and of those, the ways off the level
CISTERN_WAY_OFF = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true, RAMP_TOP = true}
local function standable(t)
    return t ~= nil and CISTERN_STANDABLE[tostring(t.shape)] == true and not (t.liquid and (t.depth or 0) >= 4)
end

-- Is a construction (a wall or floor being built, by the AI or the player) on this tile?
function construction_at(x, y, z)
    local ok, yes = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        return b ~= nil and b:getType() == df.building_type.Construction
    end)
    return ok and yes == true
end

-- Can the AI close this gap, and how: 'build' (with the quickfort text),
-- 'building' (its construction already placed), 'wait' (someone is in the
-- way) or 'no' (the player's), with why. (0.104.168, review) `recheck`: the
-- AI's own wall is placed and waits for a builder: is it still safe to finish?
function cistern_gap_plan(p, g, inside_set, recheck)
    local t = tile_info(g.x, g.y, g.z)
    if not t then return 'no', 'off the map' end
    if t.liquid then return 'no', 'water stands there' end
    if t.building and not recheck then return 'building', 'a construction or building stands there' end
    if not g.fix then return 'no', 'only a stair or a dug way can be there' end
    local sh = tostring(t.shape)
    if g.fix == 'floor' and sh ~= 'EMPTY' then
        return 'no', ('it is %s (a way the dwarves walk, or nothing a floor can be built on)'):format(sh:lower())
    end
    if g.fix == 'wall' and not CISTERN_GAP_WALL_ON[sh] then
        return 'no', ('it is %s (a way up or down the dwarves may walk)'):format(sh:lower())
    end
    if units_on_tiles({{x = g.x, y = g.y}}, g.z) > 0 then return 'wait', 'a creature stands there' end
    if g.fix == 'wall' then
        -- the gap's open neighbours on its level, the cistern's own tiles left out
        local function key(x, y) return x .. ',' .. y end
        -- (0.104.168, review) only ground a dwarf can stand on: never through open air or deep water
        local function open_at(x, y)
            if x == g.x and y == g.y then return false end
            if inside_set[key(x, y) .. ',' .. g.z] then return false end
            return standable(tile_info(x, y, g.z))
        end
        local starts = {}
        for _, e in ipairs(DIR8) do
            if open_at(g.x + e[1], g.y + e[2]) then table.insert(starts, {x = g.x + e[1], y = g.y + e[2]}) end
        end
        if #starts > 0 then
            -- one walk from the first neighbour: it must meet every other one
            -- (else the wall cuts a way), and if it ends small with no way off
            -- the level it is a hollow: nobody may be in it
            local seen, queue, tiles, way_off, capped_ = {[key(starts[1].x, starts[1].y)] = true}, {starts[1]}, {}, false, false
            local i = 1
            while i <= #queue do
                local q = queue[i]; i = i + 1
                table.insert(tiles, q)
                if #tiles > CISTERN_GAP_POCKET_MAX then capped_ = true break end
                -- a way off the level: a stair or a ramp, or the surface's open ground
                -- (never a channel or open air: no dwarf walks off through it)
                local qt = tile_info(q.x, q.y, g.z)
                if qt and (CISTERN_WAY_OFF[tostring(qt.shape)] or qt.outside) then
                    way_off = true
                end
                for _, e in ipairs(DIR8) do
                    local nx, ny = q.x + e[1], q.y + e[2]
                    if not seen[key(nx, ny)] and open_at(nx, ny) then
                        seen[key(nx, ny)] = true
                        table.insert(queue, {x = nx, y = ny})
                    end
                end
            end
            for _, s0 in ipairs(starts) do
                if not seen[key(s0.x, s0.y)] then
                    return 'no', capped_ and 'a wall there could cut a way the dwarves walk'
                                         or 'a wall there would cut a way the dwarves walk'
                end
            end
            -- (0.104.168, review) past the tiles looked at, unsure: only safe with
            -- a way off the level found (then it is no hollow); else the player's
            if capped_ and not way_off then
                return 'no', 'too much ground beyond it to be sure the wall shuts nobody in'
            end
            if not way_off and units_on_tiles(tiles, g.z) > 0 then
                return 'wait', 'someone is in the hollow beyond it (the wall would shut them in)'
            end
        end
    end
    return 'build', g.fix == 'wall' and 'Cw' or 'Cf'
end

-- (0.104.168, review) Take back a wall the AI placed that isn't built yet.
function cancel_construction(x, y, z)
    local ok, done = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if not b or b:getType() ~= df.building_type.Construction then return false end
        if b:getBuildStage() >= b:getMaxBuildStage() then return false end
        return dfhack.buildings.deconstruct(b)
    end)
    return ok and done and true or false
end

-- Close what the AI can of the cistern's gaps (cistern_sealed's list).
-- Returns the step's answer: a wait while walls/floors are being built, or
-- needs_player (with why) for a gap the AI must leave to the player.
function cistern_close_gaps(d, p, gaps, dry_run, save)
    local c, z = p.cistern, p.cistern.z
    local zi = p.intake_z or z
    local inside_set = {}
    for yy = c.y1, c.y2 do for xx = c.x1, c.x2 do inside_set[xx .. ',' .. yy .. ',' .. z] = true end end
    for _, t in ipairs(p.tunnel_path or {}) do inside_set[t.x .. ',' .. t.y .. ',' .. zi] = true end
    if p.shaft then for zz = z, zi do inside_set[p.shaft.x .. ',' .. p.shaft.y .. ',' .. zz] = true end end
    local placed, building, waiting, refused = {}, 0, nil, nil
    local by_z = {}
    for _, g in ipairs(gaps or {}) do
        local how, what = cistern_gap_plan(p, g, inside_set)
        local mine = (d.sealing and d.sealing[g.x .. ',' .. g.y .. ',' .. g.z]) or construction_at(g.x, g.y, g.z)
        if how == 'building' and mine then
            -- (0.104.168, review) still safe to finish? Someone gone into the
            -- hollow behind it since: the wall is taken back
            -- (one only passing over the tile: DF waits for it to step off itself)
            local how2, what2 = cistern_gap_plan(p, g, inside_set, true)
            if how2 == 'wait' and tostring(what2):find('hollow') then
                if not dry_run and cancel_construction(g.x, g.y, g.z) then
                    if d.sealing then d.sealing[g.x .. ',' .. g.y .. ',' .. g.z] = nil end
                end
                waiting = waiting or (g.words .. ': ' .. what2 .. '; the wall placed there is taken back')
            else
                building = building + 1
            end
        elseif how == 'building' or how == 'no' then
            refused = refused or (g.words .. ': ' .. what)
        elseif how == 'wait' then
            waiting = waiting or (g.words .. ': ' .. what)
        else
            by_z[g.z] = by_z[g.z] or {}
            table.insert(by_z[g.z], {x = g.x, y = g.y, z = g.z, text = what, g = g})
        end
    end
    for zz, cells in pairs(by_z) do
        for _, cell in ipairs(cells) do
            if dry_run or designate({{x = cell.x, y = cell.y, text = cell.text}}, zz, 'build') then
                table.insert(placed, cell)
            else
                refused = refused or (cell.g.words .. ': the game would not place a '
                                      .. (cell.text == 'Cw' and 'wall' or 'floor') .. ' there')
            end
        end
    end
    if not dry_run then
        d.sealing = d.sealing or {}
        for _, cell in ipairs(placed) do d.sealing[cell.x .. ',' .. cell.y .. ',' .. cell.z] = cell.text end
        d.unsealed_why = refused
        d.unsealed = gaps and gaps[1] and gaps[1].words or d.unsealed
        save(d)
    end
    local walls, floors = 0, 0
    for _, cell in ipairs(placed) do if cell.text == 'Cw' then walls = walls + 1 else floors = floors + 1 end end
    local words = {}
    if walls > 0 then table.insert(words, walls .. ' wall(s)') end
    if floors > 0 then table.insert(words, floors .. ' floor(s)') end
    local where = gaps and gaps[1] and gaps[1].words or '?'
    if refused then
        return {ok = false, rejected = true, needs_player = true, unsealed = where,
                unsealed_why = refused, walls = walls, floors = floors, dry_run = dry_run or nil,
                error = 'the cistern is not closed where the water goes (' .. refused .. '): the AI can\'t close that itself'}
    end
    if #placed > 0 then
        return {ok = true, stage = d.stage, sealing = true, walls = walls, floors = floors, dry_run = dry_run or nil,
                error = ('the cistern is not closed where the water goes (%s): the AI builds %s there first')
                        :format(where, table.concat(words, ' and '))}
    end
    return {ok = false, rejected = true, waiting = true, stage = d.stage, unsealed = where,
            error = 'the cistern is not closed where the water goes (' .. where .. '): '
                    .. (waiting or (building .. ' wall(s)/floor(s) the AI placed are being built'))}
end

-- (0.104.144) THE PLAYER, 31 Oct 20:51: the cistern as built doesn't work,
-- and working it would flood the fort. Until a new design: its floodgate is
-- never opened by the AI (it may still be shut), and no new cistern is begun.
CISTERN_HOLD = false          -- (0.104.145) the second design: released
CISTERN_HOLD_WHY = 'the cistern is on hold (the player: as built it would flood the fort): the floodgate stays shut'

function cistern_step(dry_run, prefs)
    OFFSET = elevation_offset()
    if prefs then cistern_prefs(prefs) end
    local d = cistern_data()
    -- (0.104.145) a cistern of the first design is retired: its floodgate
    -- shut (it could flood the fort) and the next one planned afresh
    if d and (d.plan.v or 1) < CISTERN_V then
        local p0 = d.plan
        local g = building_info(p0.floodgate.x, p0.floodgate.y, p0.cistern.z, 'Floodgate')
        if g and g.built and not g.closed and not d.lever_id then
            return {ok = false, rejected = true, needs_player = true,
                    error = 'the old cistern\'s floodgate is open and no lever is linked to it: shut it by hand'}
        end
        if g and g.built and not g.closed and d.lever_id then
            if dry_run then return {ok = true, dry_run = true, retire = true} end
            if not lever_pull_pending(d.lever_id) then pull(d.lever_id, true) end
            return {ok = true, stage = d.stage, shut = true,
                    error = 'the old cistern\'s floodgate is being shut before it is retired (its design could flood the fort)'}
        end
        if dry_run then return {ok = true, dry_run = true, retire = true} end
        local old = dfhack.persistent.getSiteData(CISTERN_KEY .. '/retired', {}) or {}
        table.insert(old, {cistern = p0.cistern, source = p0.source, why = 'the first design (pressure could flood the fort)'})
        pcall(dfhack.persistent.saveSiteData, CISTERN_KEY .. '/retired', old)
        pcall(dfhack.persistent.saveSiteData, CISTERN_KEY, {})
        return {ok = true, stage = 'retired', retired = true,
                error = 'the old cistern (first design) retired, its floodgate shut: a new one is planned next'}
    end
    if not d and CISTERN_HOLD then
        return {ok = false, rejected = true, held = true, error = 'no new cistern while the design is on hold'}
    end
    if not d then
        local plan, why = plan_cistern()
        if not plan then return {ok = false, error = why} end
        if dry_run then return {ok = true, dry_run = true, stage = 'dig', plan = plan} end
        d = {stage = 'dig', plan = plan}
    end
    local p, z = d.plan, d.plan.cistern.z
    local zw, wx, wy = p.well.z, p.well.x, p.well.y
    local zi = p.intake_z or z                 -- (0.104.145) the source's level: the tunnel, floodgate and plug
    local function wait(why) return {ok = false, rejected = true, waiting = true, stage = d.stage, error = why} end
    local function advance(stage, extra)
        if not dry_run then d.stage = stage; save_cistern(d) end
        local out = {ok = true, stage = stage, dry_run = dry_run or nil}
        for k, v in pairs(extra or {}) do out[k] = v end
        return out
    end

    -- (0.104.144) on hold: past the link (opening, the plug, filling, the
    -- well) nothing more is done; an open floodgate is shut
    if CISTERN_HOLD and d.stage ~= 'dig' and d.stage ~= 'building' and d.stage ~= 'linking' then
        local g = building_info(p.floodgate.x, p.floodgate.y, zi, 'Floodgate')
        if not dry_run and g and g.built and not g.closed and d.lever_id and not lever_pull_pending(d.lever_id) then
            pull(d.lever_id)
            return {ok = true, held = true, shut = true, error = CISTERN_HOLD_WHY}
        end
        return {ok = false, rejected = true, held = true, error = CISTERN_HOLD_WHY}
    end
    if d.stage == 'dig' then
        if dry_run then return {ok = true, dry_run = true, stage = 'dig', plan = p} end
        local room = {}
        for _, c in ipairs(room_tiles(p.cistern)) do
            if not (c.x == wx and c.y == wy) then table.insert(room, {x = c.x, y = c.y, text = 'd'}) end
        end
        local tunnel = {}
        for i = 1, #p.tunnel_path - 1 do
            table.insert(tunnel, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y, text = 'd'})
        end
        if not designate({{x = wx, y = wy, text = 'j'}}, zw, 'dig')
                or not designate({{x = wx, y = wy, text = 'u'}}, z, 'dig')
                or not designate(room, z, 'dig') or (#tunnel > 0 and not designate(tunnel, zi, 'dig')) then
            return {ok = false, error = 'the game would not designate the cistern\'s digging'}
        end
        -- (0.104.145) the shaft: a down stair on the source's level, up/down
        -- stairs through the rock, an up stair at the bottom (diagonal to the room)
        if p.shaft then
            for zz = z, zi do
                local ch = zz == zi and 'j' or (zz == z and 'u' or 'i')
                if not designate({{x = p.shaft.x, y = p.shaft.y, text = ch}}, zz, 'dig') then
                    return {ok = false, error = 'the game would not designate the cistern\'s shaft'}
                end
            end
        end
        return advance('digging', {x = wx, y = wy, elevation = ez(z), tunnel = p.tunnel})
    end
    if d.stage == 'digging' then
        local left = 0
        for _, c in ipairs(room_tiles(p.cistern)) do
            local t = tile_info(c.x, c.y, z)
            if t and t.shape == 'WALL' then left = left + 1 end
        end
        for i = 1, #p.tunnel_path - 1 do
            local t = tile_info(p.tunnel_path[i].x, p.tunnel_path[i].y, zi)
            if t and t.shape == 'WALL' then left = left + 1 end
        end
        if p.shaft then
            for zz = z, zi do
                local t = tile_info(p.shaft.x, p.shaft.y, zz)
                if t and t.shape == 'WALL' then left = left + 1 end
            end
        end
        local top = tile_info(wx, wy, zw)
        if not top or top.shape ~= 'STAIR_DOWN' and top.shape ~= 'STAIR_UPDOWN' then left = left + 1 end
        if left > 0 then return wait(('the cistern is being dug: %d tile(s) left'):format(left)) end
        if dry_run then return {ok = true, dry_run = true, stage = 'build'} end
        local fg, lv = p.floodgate, p.lever
        if not lv then return {ok = false, error = 'no spot for the lever beside the well'} end
        if not designate({{x = fg.x, y = fg.y, text = 'x'}}, zi, 'build')
                or not designate({{x = lv.x, y = lv.y, text = 'Tl'}}, zw, 'build') then
            return {ok = false, error = 'the game would not place the floodgate or the lever'}
        end
        return advance('building')
    end
    local gate = building_info(p.floodgate.x, p.floodgate.y, zi, 'Floodgate')
    local lever = p.lever and building_info(p.lever.x, p.lever.y, zw, 'Trap')
    if d.stage == 'building' then
        if not gate or not lever then return {ok = false, error = 'the floodgate or the lever is gone'} end
        if not gate.built or not lever.built then return wait('the floodgate and the lever are being built') end
        if dry_run then return {ok = true, dry_run = true, stage = 'link'} end
        local okg, G = pcall(reqscript, 'ai-gates')
        if not okg then return {ok = false, error = 'ai-gates missing'} end
        local r = G.link_lever(lever.id, gate.id, false)
        if not r.ok then return r end
        d.lever_id, d.gate_id = lever.id, gate.id
        return advance('linking')
    end
    if d.stage == 'linking' then
        -- (0.104.138) the lever (or the gate) itself gone (Teacheroar: "no
        -- lever with id 273", toppled in a tantrum?) used up the 3 relinks on
        -- a building that wasn't there: take the one standing on its spot, or
        -- place it again, and count afresh
        local function gone(id)
            local ok, b = pcall(function() return df.building.find(id) end)
            return ok and id ~= nil and b == nil
        end
        if gone(d.lever_id) or gone(d.gate_id) then
            if dry_run then return wait('the lever or floodgate is gone: placed again') end
            if lever and lever.built and gate and gate.built then
                d.lever_id, d.gate_id, d.relinks = lever.id, gate.id, 0
                save_cistern(d)
                local r = reqscript('ai-gates').link_lever(d.lever_id, d.gate_id, false)
                if not r.ok then return r end
                return wait('the lever or floodgate was replaced: linked again')
            end
            if (not lever and p.lever and not designate({{x = p.lever.x, y = p.lever.y, text = 'Tl'}}, zw, 'build'))
                    or (not gate and not designate({{x = p.floodgate.x, y = p.floodgate.y, text = 'x'}}, zi, 'build')) then
                return {ok = false, error = 'the lever or floodgate is gone and the game would not place it again'}
            end
            d.relinks = 0
            return advance('building')
        end
        local links = reqscript('ai-gates').lever_links()
        local linked = false
        for _, lid in ipairs(links[d.gate_id] or {}) do if lid == d.lever_id then linked = true end end
        if not linked then
            -- (0.104.110) the link job was lost (cancelled, its mechanisms
            -- taken): Teacheroar waited on it 3,259 steps. Asked for again,
            -- 3 times at most
            local pending = false
            pcall(function()
                local lv = df.building.find(d.lever_id)
                for _, j in ipairs(lv and lv.jobs or {}) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then pending = true end
                end
            end)
            if pending or dry_run then return wait('the lever is being linked to the floodgate') end
            if (math.tointeger(d.relinks) or 0) >= 3 then
                return {ok = false, rejected = true, needs_player = true,
                    error = 'the link from the lever to the floodgate was lost 3 times; '
                    .. 'link it by hand (the lever beside the well)'}
            end
            -- (0.104.141) why the last one was dropped: DF's newest "cancels
            -- Link a Building" announcement, kept for the Needs you line
            pcall(function()
                local reps = df.global.world.status.reports
                for i = #reps - 1, math.max(0, #reps - 400), -1 do
                    local txt = reps[i].text
                    if txt:find('cancels Link') then d.link_why = txt:gsub('^.-cancels ', ''):sub(1, 120) break end
                end
            end)
            local r = reqscript('ai-gates').link_lever(d.lever_id, d.gate_id, false)
            if not r.ok then return r end
            d.relinks = (math.tointeger(d.relinks) or 0) + 1     -- (0.104.138) only a link really asked for
            save_cistern(d)
            return wait(('the lever link was lost: asked for again (%d)'):format(d.relinks))
        end
        if CISTERN_HOLD then return {ok = false, rejected = true, held = true, error = CISTERN_HOLD_WHY} end
        -- (0.104.145) closed all round, and its source still there, before any water
        local sealed, where, gaps = cistern_sealed(p, d.stage)
        if not dry_run and d.unsealed ~= (where or nil) then d.unsealed = where; save_cistern(d) end
        if not sealed then
            -- (0.104.168) the AI walls it up itself where it safely can
            return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
        end
        if not dry_run and (d.sealing or d.unsealed_why) then d.sealing, d.unsealed_why = nil, nil; save_cistern(d) end
        if not still_water(tile_info(p.water.x, p.water.y, zi)) then
            return {ok = false, rejected = true, error = 'the cistern\'s source is gone (no still water beside the plug)'}
        end
        if dry_run then return {ok = true, dry_run = true, stage = 'open'} end
        -- (0.104.145, review) the gate stays shut: the plug is dug first with
        -- nobody inside (DFHack dig-now), then the gate opened at once. A miner
        -- digging it by hand had to flee back down a shaft filling faster than
        -- the room, through water a dwarf won't wade
        return advance('opening')
    end
    if d.stage == 'opening' then
        if gate and gate.closed and d.plug_by_hand then
            return wait('a dwarf is on the way to pull the lever (open the floodgate)')
        end
        -- (0.104.0, map safety) the water comes in when the plug is dug: no one
        -- else may be in the cistern or its tunnel then. The plug waits until
        -- both are empty, and what lies there is forbidden (no hauler goes in
        -- for it); only the miner who digs the plug goes in, and out through
        -- the open floodgate
        local inside = cistern_inside(p, z)
        local n = zi == z and units_on_tiles(inside, z)
            or (units_on_tiles(room_tiles(p.cistern), z) + units_on_tiles(cistern_way(p), zi))
        if p.shaft then
            for zz = z, zi do n = n + units_on_tiles({{x = p.shaft.x, y = p.shaft.y}}, zz) end
        end
        if n > 0 then
            return wait(('%d creature(s) in the cistern or its tunnel: the plug waits until it is empty'):format(n))
        end
        local sealed, where, gaps = cistern_sealed(p, d.stage)
        if not dry_run and d.unsealed ~= (where or nil) then d.unsealed = where; save_cistern(d) end
        if not sealed then
            -- (0.104.168) the AI walls it up itself where it safely can; the plug waits
            return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
        end
        if not dry_run and (d.sealing or d.unsealed_why) then d.sealing, d.unsealed_why = nil, nil; save_cistern(d) end
        if dry_run then return {ok = true, dry_run = true, stage = 'plug'} end
        if zi == z then
            forbid_items_on(inside, z)
        else
            forbid_items_on(room_tiles(p.cistern), z)
            forbid_items_on(cistern_way(p), zi)
        end
        -- dig-now: the plug gone at once, the gate still shut; then the gate opened
        if not d.plug_by_hand and gate and gate.closed then
            designate({{x = p.plug.x, y = p.plug.y, text = 'd'}}, zi, 'dig')
            local pos = ('%d,%d,%d'):format(p.plug.x, p.plug.y, zi)
            pcall(dfhack.run_command_silent, 'dig-now', pos, pos)
            local pt = tile_info(p.plug.x, p.plug.y, zi)
            if pt and pt.shape ~= 'WALL' then
                local ok, out = pull(d.lever_id, true)
                if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
                return advance('filling', {plug = 'dug at once', opened = true})
            end
            -- no dig-now here: the old way (the gate opened, a miner digs it),
            -- never down a shaft (the miner would drown fleeing it)
            if p.shaft then
                return {ok = false, rejected = true, needs_player = true,
                        error = 'DFHack\'s dig-now didn\'t dig the plug, and a miner digging it would drown in the shaft'}
            end
            d.plug_by_hand = true
            save_cistern(d)
            local ok, out = pull(d.lever_id)
            if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
            return wait('dig-now isn\'t here: the gate opened, a miner digs the plug')
        end
        if not designate({{x = p.plug.x, y = p.plug.y, text = 'd'}}, zi, 'dig') then
            return {ok = false, error = 'the game would not designate the plug'}
        end
        return advance('plug')
    end
    local st = cistern_status()
    -- (0.104.145) the leak guard: water over the cistern (on the well's level
    -- over the room or round it) means it is getting out: the floodgate is
    -- shut at once and the player told
    if d.stage ~= 'dig' and d.stage ~= 'digging' and d.stage ~= 'building' and d.stage ~= 'linking' then
        local leak
        -- (review) the shaft's own column and the tunnel hold water by design
        local own = {}
        if p.shaft then own[p.shaft.x .. ',' .. p.shaft.y] = true end
        if zi == zw then for _, q in ipairs(p.tunnel_path or {}) do own[q.x .. ',' .. q.y] = true end end
        for yy = p.cistern.y1 - 1, p.cistern.y2 + 1 do
            for xx = p.cistern.x1 - 1, p.cistern.x2 + 1 do
                local tt = tile_info(xx, yy, zw)
                if tt and tt.liquid and not tt.magma and not own[xx .. ',' .. yy] then
                    leak = leak or ('x%d y%d elevation %d'):format(xx, yy, ez(zw))
                end
            end
        end
        if not leak and d.leak and gate and gate.closed then
            -- the water gone from over it and it is closed again: tried once
            -- more (a second leak keeps it shut for good)
            local ok_ = cistern_sealed(p, d.stage)
            if ok_ == true and (d.leaks or 0) < 2 and not dry_run then d.leak = nil; save_cistern(d) end
        end
        if d.leak and not leak then
            return {ok = false, rejected = true, needs_player = true, leak = d.leak,
                    error = 'the cistern leaked at ' .. d.leak .. ': its floodgate stays shut'}
        end
        if leak then
            if gate and gate.built and not gate.closed and d.lever_id and not dry_run then pull(d.lever_id, true) end
            d.leak = leak
            d.leaks = (d.leaks or 0) + 1
            if not dry_run then save_cistern(d) end
            return {ok = false, needs_player = true, leak = leak, shut = true,
                    error = 'water over the cistern at ' .. leak .. ': its floodgate shut at once'}
        end
    end
    if d.stage == 'plug' then
        local t = tile_info(p.plug.x, p.plug.y, zi)
        if t and t.shape == 'WALL' then return wait('the plug is being dug (then the water comes in)') end
        return advance('filling')
    end
    if d.stage == 'filling' then
        if st.depth < CISTERN_FULL then
            local why = st.path and (' (gate %s; %s)'):format(st.gate or '?', path_words(st.path)) or ''
            if dry_run then return wait(('the cistern is filling: %d/7%s'):format(st.depth, why)) end
            -- (0.104.100) the gate shut (the flood rule, while dwarves stood in deep
            -- water): reopened after CISTERN_REOPEN_DAYS with nobody in deep water
            -- (Teacheroar sat at 5/7 behind a shut gate from 03:18 all night)
            if gate and gate.built and gate.closed and d.lever_id then
                local okn, now_t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
                now_t = okn and now_t or 0
                local wet = citizens_in_deep_water()
                if wet > 0 or not d.shut_seen then
                    d.shut_seen = now_t
                    save_cistern(d)
                end
                if (d.reopens or 0) >= CISTERN_MAX_REOPENS then
                    return wait(('the cistern is filling: %d/7, its floodgate shut after %d floods: it stays shut '
                                 .. '(open it by its lever when the cause is found)'):format(st.depth, d.reopens))
                end
                local days = (now_t - d.shut_seen) // 1200
                if wet == 0 and days >= CISTERN_REOPEN_DAYS and not CISTERN_HOLD then
                    if lever_pull_pending(d.lever_id) then
                        return wait('a dwarf is on the way to pull the cistern\'s lever (reopening it)')
                    end
                    -- (0.104.168) never reopened while it isn't closed where the water
                    -- goes (the gate may have been shut for exactly that): closed first
                    local sealed, where, gaps = cistern_sealed(p, d.stage)
                    if not sealed then
                        if not dry_run then d.unsealed = where; save_cistern(d) end
                        return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
                    end
                    d.unsealed, d.sealing, d.unsealed_why = nil, nil, nil
                    local ok, out = pull(d.lever_id)
                    if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
                    d.reopens, d.shut_seen = (d.reopens or 0) + 1, nil
                    save_cistern(d)
                    return {ok = true, stage = 'filling', reopened = true, depth = st.depth,
                            error = ('the floodgate was shut for a flood; nobody has stood in deep water for %d days: '
                                     .. 'reopened to finish filling (%d of %d)'):format(days, d.reopens, CISTERN_MAX_REOPENS)}
                end
                return wait(('the cistern is filling: %d/7, its floodgate shut (%s): it reopens after %d days with '
                             .. 'nobody in deep water'):format(st.depth, wet > 0 and (wet .. ' in deep water now')
                                                              or (days .. ' day(s) dry so far'), CISTERN_REOPEN_DAYS))
            end
            -- (0.104.94) the source dried up (a surface pool evaporates): after
            -- CISTERN_DRY_DAYS with no water there and none in the cistern, the
            -- floodgate is shut and the cistern retired; the next one is planned
            -- afresh (this room no longer counts as solid rock)
            local src = tile_info(p.water.x, p.water.y, zi)
            local dry = st.depth == 0 and not (src and src.liquid)
            local okn, now_t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
            now_t = okn and now_t or 0
            if dry then
                d.dry_since = d.dry_since or now_t
                save_cistern(d)
                if now_t - d.dry_since >= CISTERN_DRY_DAYS * 1200 then
                    if gate and gate.built and not gate.closed and d.lever_id then pull(d.lever_id) end
                    local old = dfhack.persistent.getSiteData(CISTERN_KEY .. '/retired', {}) or {}
                    table.insert(old, {cistern = p.cistern, source = p.source, why = 'the source dried up', at = now_t})
                    pcall(dfhack.persistent.saveSiteData, CISTERN_KEY .. '/retired', old)
                    pcall(dfhack.persistent.saveSiteData, CISTERN_KEY, {})
                    return {ok = true, stage = 'retired', retired = true,
                            error = ('the cistern\'s source (%s) dried up for %d days: its floodgate shut and the cistern '
                                     .. 'retired; the next one is planned afresh'):format(tostring(p.source), CISTERN_DRY_DAYS)}
                end
                return wait(('the cistern is filling: 0/7; its source (%s) is dry for %d day(s)%s')
                            :format(tostring(p.source), (now_t - d.dry_since) // 1200, why))
            elseif d.dry_since then
                d.dry_since = nil
                save_cistern(d)
            end
            -- (0.104.96) the tunnel cleared only while there is water to let in
            -- (it ran first and kept the dry check from ever counting)
            -- (0.104.94) a tree grown in the tunnel (a trunk is a wall), or rock
            -- left: felled or dug again
            local blocked = 0
            local way = {}
            for i = 1, #p.tunnel_path - 1 do table.insert(way, p.tunnel_path[i]) end
            table.insert(way, p.plug)
            for _, c in ipairs(way) do
                local t = tile_info(c.x, c.y, zi)
                if t and t.shape == 'WALL' and t.material ~= 'FROZEN_LIQUID' and not t.designated then
                    blocked = blocked + 1
                    if t.material == 'TREE' or t.material == 'ROOT' then
                        fell_tree(c.x, c.y, zi)
                    else
                        designate({{x = c.x, y = c.y, text = 'd'}}, zi, 'dig')
                    end
                end
            end
            if blocked > 0 then
                return wait(('the cistern is filling: %d/7; %d tile(s) on the water\'s way blocked: felled or dug again%s')
                            :format(st.depth, blocked, why))
            end
            -- (0.104.119) water stands no higher than its source: a cistern at
            -- 4/7 or more that hasn't risen for CISTERN_LEVEL_DAYS with its
            -- gate open is as full as it gets (it waited at 5/7 for good)
            local okn, now_t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
            now_t = okn and now_t or 0
            if d.depth_seen ~= st.depth or st.gate == 'shut' then
                d.depth_seen, d.depth_tick = st.depth, now_t
                save_cistern(d)
            end
            local still = (now_t - (math.tointeger(d.depth_tick) or now_t)) // 1200
            if not (st.depth >= CISTERN_LEVEL_MIN and still >= CISTERN_LEVEL_DAYS) then
                return wait(('the cistern is filling: %d/7%s'):format(st.depth, why))
            end
        end
        if dry_run then return {ok = true, dry_run = true, stage = 'hole'} end
        if gate and not gate.closed then pull(d.lever_id) end
        if not designate({{x = wx, y = wy, text = 'h'}}, zw, 'dig') then
            return {ok = false, error = 'the game would not channel the well\'s hole'}
        end
        return advance('hole', {depth = st.depth})
    end
    if d.stage == 'hole' then
        local t = tile_info(wx, wy, zw)
        if t and t.shape ~= 'EMPTY' and t.shape ~= 'RAMP_TOP' then return wait('the well\'s hole is being dug') end
        if dry_run then return {ok = true, dry_run = true, stage = 'well'} end
        if not designate({{x = wx, y = wy, text = 'l'}}, zw, 'build') then
            return {ok = false, error = 'the game would not place the well'}
        end
        return advance('well')
    end
    if d.stage == 'well' then
        local w = building_info(wx, wy, zw, 'Well')
        if not w or not w.built then return wait('the well is being built') end
        return advance('done', {depth = st.depth})
    end
    -- done: keep it topped up
    if gate and gate.built and d.lever_id then
        if gate.closed and st.depth < CISTERN_LOW and not CISTERN_HOLD then
            local sealed, where, gaps = cistern_sealed(p, d.stage)
            if not sealed then
                if not dry_run then d.unsealed = where; save_cistern(d) end
                -- (0.104.168) the AI walls it up itself where it safely can; not refilled till then
                return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
            end
            if not dry_run and (d.unsealed or d.sealing or d.unsealed_why) then
                d.unsealed, d.sealing, d.unsealed_why = nil, nil, nil; save_cistern(d)
            end
            if dry_run then return {ok = true, dry_run = true, refill = true} end
            local ok, out, pending = pull(d.lever_id)
            return {ok = ok, stage = 'done', refill = true, depth = st.depth, pending = pending,
                    error = not ok and out or nil}
        elseif not gate.closed and st.depth >= CISTERN_FULL then
            if dry_run then return {ok = true, dry_run = true, shut = true} end
            local ok, out, pending = pull(d.lever_id)
            return {ok = ok, stage = 'done', shut = true, depth = st.depth, pending = pending,
                    error = not ok and out or nil}
        end
    end
    return {ok = false, rejected = true, done = true, stage = 'done', depth = st.depth,
            error = 'the cistern is built and full enough'}
end

-- Start a well: channel the spot now; the well itself is placed when the
-- hole is dug (furnish), like any other project.
function place_well(params, now, dry_run)
    OFFSET = elevation_offset()
    local data = load_projects()
    local open = open_projects(data)
    -- (0.104.13) a well the injured or the parched wait for takes an urgent
    -- slot, like soap and tombs (Enxah: "no well yet: waiting for a free
    -- building slot" while patients died of thirst)
    if #open >= slot_cap(open) + (params.urgent == true and URGENT_EXTRA or 0) then
        return {ok = false, rejected = true,
                error = ('already %d unfinished building projects'):format(#open)}
    end
    -- (0.104.13) dug first while the injured wait (quickfort's priority digit:
    -- 1 is the highest; 4, the game's default, otherwise)
    local pri = params.urgent == true and '1' or ''
    local reserved = {}
    for _, p in ipairs(open) do table.insert(reserved, p.area) end
    local spot, why
    if params.cavern then
        spot, why = find_cavern_well_spot(reserved)
        if not spot then return {ok = false, error = why} end
    else
        spot, why = find_well_spot(reserved)
    end
    if not spot and params.inside_only then
        return {ok = false, error = why .. '; and the water near the surface freezes in winter (a well over '
                .. 'it would be taken down), so the AI looks only inside the fort'}
    end
    if not spot then
        local shore, why2 = find_shore_well_spot(reserved)
        if not shore then return {ok = false, error = why .. '; ' .. why2} end
        spot = shore
    end
    local dig = {{x = 0, y = 0, text = 'h' .. pri}}
    local dry = quickfort_apply('dig', dig, spot.z, spot.x, spot.y, 'run', true)
    if stat(dry, 'dig_designated') ~= 1 then
        return {ok = false, error = ('the game would not channel the well spot at x%d y%d z%d'):format(
            spot.x, spot.y, ez(spot.z))}
    end
    -- a cavern well's shaft: every rock level under the floor channelled too,
    -- each from the stair column beside it (0.104.13)
    local shaft = {}
    for k = 1, spot.cavern and spot.rock or 0 do
        local zk = spot.z - k
        local d = quickfort_apply('dig', dig, zk, spot.x, spot.y, 'run', true)
        if stat(d, 'dig_designated') ~= 1 then
            return {ok = false, error = ('the game would not channel the shaft at elevation %d'):format(ez(zk))}
        end
        table.insert(shaft, zk)
    end
    local stairs = {}
    if spot.cavern then
        if not spot.side then return {ok = false, error = 'no room beside the shaft for the stairs it is dug from'} end
        for _, c in ipairs(shaft_stair_cells(spot.side, spot.z, spot.rock)) do
            local d = quickfort_apply('dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'run', true)
            if stat(d, 'dig_designated') ~= 1 then
                return {ok = false, error = ('the game would not dig the shaft\'s stairs at elevation %d'):format(ez(c.z))}
            end
            table.insert(stairs, c)
        end
    end
    local where = {x = spot.x, y = spot.y, elevation = ez(spot.z), drop = spot.drop, in_hall = spot.zone,
                   shore = spot.shore, stagnant = spot.stagnant, cavern = spot.cavern, shaft = #shaft,
                   stairs = #stairs > 0 and #stairs or nil, urgent = params.urgent == true or nil}
    if dry_run then
        where.ok, where.dry_run = true, true
        return where
    end
    local real = quickfort_apply('dig', dig, spot.z, spot.x, spot.y)
    if stat(real, 'dig_designated') ~= 1 then
        pcall(quickfort_apply, 'dig', dig, spot.z, spot.x, spot.y, 'undo')
        return {ok = false, error = 'the game refused to channel the well spot'}
    end
    for _, zk in ipairs(shaft) do pcall(quickfort_apply, 'dig', dig, zk, spot.x, spot.y) end
    for _, c in ipairs(stairs) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y)
    end
    local p = {
        id = data.next_id, kind = 'well', phase = 'dig', params = {pri = pri ~= '' and pri or nil},
        stair = {x = spot.x, y = spot.y}, anchor = {x = spot.x, y = spot.y}, z = spot.z,
        area = {x1 = spot.x - 1, y1 = spot.y - 1, x2 = spot.x + 1, y2 = spot.y + 1, z = spot.z},
        corridor = 0, stairs = {}, dig_done = 'open', shaft = #shaft > 0 and shaft or nil,
        shaft_stairs = #stairs > 0 and stairs or nil, urgent = params.urgent == true or nil,
        summary = {well = 1, drop = spot.drop, cavern = spot.cavern}, furniture = {Well = 1},
        cells = {dig = dig, build = {{x = 0, y = 0, text = 'l'}}, place = {}, zone = {},
                 smooth = {}, engrave = {}},
        started = now, designated = 1,
    }
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    if not save_projects(data) then
        pcall(quickfort_apply, 'dig', dig, spot.z, spot.x, spot.y, 'undo')
        return {ok = false, error = 'could not save the project with the fort, so it was undone'}
    end
    where.ok, where.project_id = true, p.id
    return where
end

-- (0.104.2) A Water Source zone over open water the dwarves can walk to:
-- buckets are filled there for the injured (and the thirsty) while the fort
-- has no well. `points` are candidate water tiles {x, y, z}, best first (the
-- planner's choice from the water survey); the first one that is liquid
-- water now (not ice, magma or salt) with a bank the citizens reach gets a
-- 3x3 zone centred on it. Kept in site data 'ai-overseer/water_zones'.
WATER_ZONES_KEY = 'ai-overseer/water_zones'
BANK_SHAPES = {FLOOR = true, BOULDER = true, PEBBLES = true, TWIG = true, SAPLING = true, SHRUB = true, RAMP = true}

function water_zones()
    local ok, d = pcall(dfhack.persistent.getSiteData, WATER_ZONES_KEY, {})
    return ok and type(d) == 'table' and d or {}
end

function water_zone(points, dry_run)
    local groups = citizen_groups()
    local last = 'no open water the dwarves can walk to'
    local whys = {}
    local function note(w) last = w; table.insert(whys, w) end
    for _, p in ipairs(points or {}) do
        local x, y, z = math.tointeger(p.x), math.tointeger(p.y), math.tointeger(p.z)
        local t = x and y and z and tile_info(x, y, z)
        if not t then
            note('no such tile')
        elseif not t.liquid or t.magma or t.salt then
            note(('the water at x%d y%d is frozen, salt or gone'):format(x, y))
        else
            -- a bank beside the water, or (a pond sunk below the ground) on the level above it
            local bank
            for _, dz in ipairs({0, 1}) do
                for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                    local n = tile_info(x + d[1], y + d[2], z + dz)
                    if n and not n.liquid and BANK_SHAPES[n.shape] and groups[walk_group(x + d[1], y + d[2], z + dz)] then
                        bank = {x = x + d[1], y = y + d[2], above = dz == 1 or nil}
                        break
                    end
                end
                if bank then break end
            end
            if not bank then
                note(('no bank the dwarves reach beside the water at x%d y%d'):format(x, y))
            else
                local cell = {{x = 0, y = 0, text = 'w(3x3)'}}
                local ok, dry = pcall(quickfort_apply, 'zone', cell, z, x - 1, y - 1, 'run', true)
                if ok and stat(dry, 'zone_designated') >= 1 and stat(dry, 'invalid_keys') == 0 then
                    local out = {ok = true, x = x, y = y, elevation = ez(z), bank = bank, stagnant = t.stagnant or nil,
                                 cavern = t.feature or nil, outside = t.outside or nil, dry_run = dry_run or nil}
                    if dry_run then return out end
                    local ok2, real = pcall(quickfort_apply, 'zone', cell, z, x - 1, y - 1)
                    if ok2 and stat(real, 'zone_designated') >= 1 then
                        local list = water_zones()
                        table.insert(list, {x = x, y = y, z = z})
                        pcall(dfhack.persistent.saveSiteData, WATER_ZONES_KEY, list)
                        return out
                    end
                    note('the game refused the water source zone')
                else
                    note(('the game would not place a water source at x%d y%d'):format(x, y))
                end
            end
        end
    end
    return {ok = false, error = #whys > 1 and table.concat(whys, '; ') or last}
end

-- (0.104.95) A sand collection zone: glass is made from bags of sand, which a
-- hauler fills at a glass furnace from a Sand zone. The zone must lie on a
-- sand floor or beside a sand wall (diagonally too; DF wiki "Sand"). The
-- nearest such floor the dwarves walk to, on the ground outside first (sand
-- is in the soil layers), then the fort's levels. Kept in site data.
SAND_ZONES_KEY = 'ai-overseer/sand_zones'
SAND_RADIUS = 40
SAND_SECONDS = 1.0

-- Is the natural soil at this tile sand? (its layer's inorganic has SOIL_SAND)
function sand_tile(x, y, z)
    local t = tile_info(x, y, z)
    if not t or t.material ~= 'SOIL' then return false end
    local ok, yes = pcall(function()
        local idx = reqscript('ai-industry').stone_at(x, y, z)
        local inorg = idx and df.global.world.raws.inorganics.all[idx]
        return inorg ~= nil and inorg.flags.SOIL_SAND == true
    end)
    return ok and yes or false
end

function sand_zones()
    local ok, d = pcall(dfhack.persistent.getSiteData, SAND_ZONES_KEY, {})
    return ok and type(d) == 'table' and d or {}
end

-- A floor tile the dwarves reach, on sand or beside it: {x, y, z} or nil, why.
function find_sand_spot()
    local area = fort_scan_area(SAND_RADIUS)
    if not area then return nil, 'no citizens' end
    local deadline = os.clock() + SAND_SECONDS
    local zs, seen = {}, {}
    local okS, surf = pcall(surface_levels, area)
    for _, z in ipairs(okS and surf or {}) do if not seen[z] then seen[z] = true; table.insert(zs, z) end end
    for _, l in ipairs(area.levels) do if not seen[l.z] then seen[l.z] = true; table.insert(zs, l.z) end end
    local best, best_d
    for _, z in ipairs(zs) do
        for y = area.y1, area.y2 do
            if os.clock() > deadline then break end
            for x = area.x1, area.x2 do
                local f = tile_info(x, y, z)
                if f and f.shape == 'FLOOR' and not f.liquid and not f.building
                        and area.groups[walk_group(x, y, z)] then
                    local d = math.abs(x - area.cx) + math.abs(y - area.cy)
                    if (not best_d or d < best_d) then
                        local sandy = sand_tile(x, y, z)
                        if not sandy then
                            for _, e in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                                local n = tile_info(x + e[1], y + e[2], z)
                                if n and n.shape == 'WALL' and sand_tile(x + e[1], y + e[2], z) then sandy = true break end
                            end
                        end
                        if sandy then best, best_d = {x = x, y = y, z = z}, d end
                    end
                end
            end
        end
        if best then break end          -- the first level with sand (the ground outside before the fort)
    end
    if best then return best end
    return nil, 'no sand floor or sand wall the dwarves walk to near the fort'
end

function sand_zone(dry_run)
    if #sand_zones() > 0 then
        return {ok = false, rejected = true, error = 'the fort has a sand zone already'}
    end
    local spot, why = find_sand_spot()
    if not spot then return {ok = false, rejected = true, error = why} end
    local cell = {{x = 0, y = 0, text = 's'}}
    local ok, dry = pcall(quickfort_apply, 'zone', cell, spot.z, spot.x, spot.y, 'run', true)
    if not ok or stat(dry, 'zone_designated') < 1 or stat(dry, 'invalid_keys') > 0 then
        return {ok = false, error = ('the game would not place a sand zone at x%d y%d'):format(spot.x, spot.y)}
    end
    local out = {ok = true, x = spot.x, y = spot.y, elevation = ez(spot.z), dry_run = dry_run or nil}
    if dry_run then return out end
    local ok2, real = pcall(quickfort_apply, 'zone', cell, spot.z, spot.x, spot.y)
    if not ok2 or stat(real, 'zone_designated') < 1 then
        return {ok = false, error = 'the game refused the sand zone'}
    end
    local list = sand_zones()
    table.insert(list, spot)
    pcall(dfhack.persistent.saveSiteData, SAND_ZONES_KEY, list)
    return out
end

---------------------------------------------------------------------------
-- Pastures. Grazers eat living grass (dead grass doesn't feed them). A new
-- pasture goes on grass near the fort's surface entrances, walkable from
-- where the dwarves are, sized for the herd that needs it. Grazers are put
-- in it by ai-society. See docs/building.md.
---------------------------------------------------------------------------

PASTURE_RADIUS = 40        -- tiles around a surface entrance
PASTURE_LEVELS = 2         -- levels above and below it (the surface is uneven)
PASTURE_MAX_SIDE = 15
PASTURE_MIN_SIDE = 3
PASTURE_MAX_ZONES = 4
PASTURE_BIG_SIDE = 31        -- one pasture as big as this (a herd grazes in one zone, not across several)
PASTURE_KEEP_CLEAR = 3     -- tiles kept free around an entrance (its gate)
PASTURE_SEARCH_SECONDS = 2
PASTURE_NAME = 'AI pasture'

PASTURE_GRASS = {GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true}   -- living grass: animals graze it
local GRAZE_SHAPES = {FLOOR = true, SHRUB = true, SAPLING = true}

-- Living grass on this tile? Tile types looked up once.
local GRASS_TT = nil
function grass_at(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return false end
    if not GRASS_TT then
        GRASS_TT = {}
        for t, _ in ipairs(df.tiletype) do
            local attrs = df.tiletype.attrs[t]
            if attrs and PASTURE_GRASS[df.tiletype_material[attrs.material]]
                    and GRAZE_SHAPES[df.tiletype_shape[attrs.shape]] then
                GRASS_TT[t] = true
            end
        end
    end
    return GRASS_TT[tt] == true
end

-- Where pastures should be near: the fort's surface entrances (once the
-- overseer has mapped them), else the top of the main staircase.
function pasture_anchors()
    local out = {}
    local ok, s = pcall(function() return reqscript('ai-gates').summary() end)
    if ok and s and s.scanned then
        for _, e in ipairs(s.entrances or {}) do
            if e.kind == 'surface' then table.insert(out, {x = e.x, y = e.y, z = e.z}) end
        end
    end
    if #out == 0 then
        local stair = find_main_stair()
        if stair then table.insert(out, {x = stair.x, y = stair.y, z = stair.z_top}) end
    end
    return out
end

-- Rectangles of free living grass near the anchors, adding up to about
-- `want` tiles, nearest first: {x, y, z, w, h}.
function find_pasture_spots(want, reserved)
    local anchors = pasture_anchors()
    if #anchors == 0 then return {}, 'no surface entrance or staircase to start from' end
    local groups = {}
    for _, p in ipairs(citizen_positions()) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
    end
    local w, h = map_size()
    local function near_anchor(x, y, z)
        for _, a in ipairs(anchors) do
            if math.abs(a.z - z) <= 1 and math.max(math.abs(a.x - x), math.abs(a.y - y)) <= PASTURE_KEEP_CLEAR then
                return true
            end
        end
        return false
    end
    local cache, used = {}, {}
    local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
    local function good(x, y, z)
        local k = key(x, y, z)
        if used[k] then return false end
        local v = cache[k]
        if v ~= nil then return v end
        v = false
        if x >= 1 and y >= 1 and x <= w - 2 and y <= h - 2 and grass_at(x, y, z) then
            local t = tile_info(x, y, z)
            v = t ~= nil and not t.liquid and not t.feature and not t.building and not t.designated
                and groups[walk_group(x, y, z)] == true
                and not inside_any(reserved, x, y, z) and not near_anchor(x, y, z)
                and not tile_taken(x, y, z)
        end
        cache[k] = v
        return v
    end
    -- every grass tile in reach, nearest an anchor first
    local cands = {}
    local deadline = os.clock() + PASTURE_SEARCH_SECONDS
    for _, a in ipairs(anchors) do
        for z = a.z - PASTURE_LEVELS, a.z + PASTURE_LEVELS do
            for y = a.y - PASTURE_RADIUS, a.y + PASTURE_RADIUS do
                if os.clock() > deadline then break end
                for x = a.x - PASTURE_RADIUS, a.x + PASTURE_RADIUS do
                    if good(x, y, z) then
                        table.insert(cands, {x = x, y = y, z = z,
                                             d = math.abs(a.x - x) + math.abs(a.y - y) + 3 * math.abs(a.z - z)})
                    end
                end
            end
        end
    end
    table.sort(cands, function(p, q)
        if p.d ~= q.d then return p.d < q.d end
        if p.z ~= q.z then return p.z > q.z end
        if p.y ~= q.y then return p.y < q.y end
        return p.x < q.x
    end)
    local spots, total = {}, 0
    for _, c in ipairs(cands) do
        if total >= want or #spots >= PASTURE_MAX_ZONES then break end
        local x, y, z = c.x, c.y, c.z
        if good(x, y, z) then
            local rw = 1
            while rw < PASTURE_MAX_SIDE and good(x + rw, y, z) do rw = rw + 1 end
            local rh = 1
            while rh < PASTURE_MAX_SIDE do
                local row_ok = true
                for dx = 0, rw - 1 do
                    if not good(x + dx, y + rh, z) then row_ok = false break end
                end
                if not row_ok then break end
                rh = rh + 1
            end
            rh = math.max(PASTURE_MIN_SIDE, math.min(rh, math.ceil((want - total) / rw)))
            if rw >= PASTURE_MIN_SIDE and rh >= PASTURE_MIN_SIDE then
                local fits = true
                for dy = 0, rh - 1 do
                    for dx = 0, rw - 1 do
                        if not good(x + dx, y + dy, z) then fits = false end
                    end
                end
                if fits then
                    for dy = 0, rh - 1 do
                        for dx = 0, rw - 1 do used[key(x + dx, y + dy, z)] = true end
                    end
                    table.insert(spots, {x = x, y = y, z = z, w = rw, h = rh})
                    total = total + rw * rh
                end
            end
        end
    end
    return spots, (#cands == 0)
        and 'no living grass the dwarves can walk to near the fort\'s surface entrances' or nil
end

-- One rectangle near the anchors holding at least `want` tiles of living
-- grass (other open ground inside it is fine: animals walk it, they only
-- graze the grass), nearest first: {x, y, z, w, h, grass} or nil. An animal
-- grazes inside its own pasture only, so several small zones that add up to
-- enough grass feed nobody (bridge 0.38 made those).
function find_pasture_rect(want, reserved, until_clock)
    local anchors = pasture_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to start from' end
    local groups = {}
    for _, p in ipairs(citizen_positions()) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
    end
    local mw, mh = map_size()
    -- A zone may cover any tile the dwarves have seen (quickfort's only
    -- rule): trees, boulders and slopes too; animals walk round what they
    -- can't cross. Grass is counted; the rest is just inside it.
    local OPEN_SHAPES = {FLOOR = true, SHRUB = true, SAPLING = true, BOULDER = true, PEBBLES = true,
                         TWIG = true, RAMP = true}
    local function near_anchor(x, y, z)
        for _, a in ipairs(anchors) do
            if math.abs(a.z - z) <= 1 and math.max(math.abs(a.x - x), math.abs(a.y - y)) <= PASTURE_KEEP_CLEAR then
                return true
            end
        end
        return false
    end
    -- per tile: false (can't be in a pasture), 1 (grass), 0 (open ground)
    local cache = {}
    local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
    local function tile(x, y, z)
        local k = key(x, y, z)
        local v = cache[k]
        if v ~= nil then return v end
        v = false
        if x >= 1 and y >= 1 and x <= mw - 2 and y <= mh - 2 then
            local t = tile_info(x, y, z)
            local tree = t and is_tree(t)
            if t and not t.hidden and (OPEN_SHAPES[t.shape] or tree) and not t.liquid and not t.feature
                    and not t.building and (tree or not t.designated)
                    and (tree or groups[walk_group(x, y, z)] == true)
                    and not inside_any(reserved, x, y, z) and not near_anchor(x, y, z)
                    and not tile_taken(x, y, z) then
                v = grass_at(x, y, z) and 1 or 0
            end
        end
        cache[k] = v
        return v
    end
    local function rect(x0, y0, z, w, h)
        local grass = 0
        for y = y0, y0 + h - 1 do
            for x = x0, x0 + w - 1 do
                local v = tile(x, y, z)
                if v == false then return nil end
                grass = grass + v
            end
        end
        return grass
    end
    -- grass tiles nearest the anchors first, as places to centre a pasture on
    local cands = {}
    local deadline = until_clock or (os.clock() + PASTURE_SEARCH_SECONDS)
    for _, a in ipairs(anchors) do
        for z = a.z - PASTURE_LEVELS, a.z + PASTURE_LEVELS do
            if os.clock() > deadline then break end
            for y = a.y - PASTURE_RADIUS, a.y + PASTURE_RADIUS, 2 do
                for x = a.x - PASTURE_RADIUS, a.x + PASTURE_RADIUS, 2 do
                    if tile(x, y, z) == 1 then
                        table.insert(cands, {x = x, y = y, z = z,
                                             d = math.abs(a.x - x) + math.abs(a.y - y) + 3 * math.abs(a.z - z)})
                    end
                end
            end
        end
    end
    if #cands == 0 then return nil, 'no living grass the dwarves can walk to near the fort\'s surface entrances' end
    table.sort(cands, function(p, q)
        if p.d ~= q.d then return p.d < q.d end
        if p.z ~= q.z then return p.z > q.z end
        if p.y ~= q.y then return p.y < q.y end
        return p.x < q.x
    end)
    local s0 = math.max(PASTURE_MIN_SIDE, math.ceil(math.sqrt(want)))
    for i, c in ipairs(cands) do
        if os.clock() > deadline then break end
        for side = s0, PASTURE_BIG_SIDE, 3 do
            local x0, y0 = c.x - side // 2, c.y - side // 2
            local g = rect(x0, y0, c.z, side, side)
            if g == nil then break end                  -- (a bigger square holds the same blocked tile)
            if g >= want then return {x = x0, y = y0, z = c.z, w = side, h = side, grass = g} end
        end
    end
    return nil, ('no single patch near the fort with %d tiles of grass the dwarves can reach'):format(want)
end

-- A w x h rectangle of open, flat ground under the sky near the surface
-- entrances (at least `min_d` tiles away, so the way in stays clear; at most
-- SURFACE_RADIUS), every tile walkable from the fort and free: {x, y, z} or
-- nil and why. For things that belong outside: the refuse pile (rot makes
-- miasma indoors) and the trade depot (caravans come to it).
SURFACE_RADIUS = 35
SURFACE_MAX_TREES = 8        -- trees the dwarves may fell to make room
SURFACE_TREE_COST = 6        -- a tree to fell counts as this many tiles further away

-- A tree's trunk at ground level (the canopy above isn't in the way).
function is_tree(t)
    return t ~= nil and t.material == 'TREE' and (t.shape == 'WALL' or t.shape == 'TRUNK_BRANCH')
end

-- shapes: which tile shapes may lie under it (what quickfort's own check
-- for a building or stockpile accepts: floor, boulders, pebbles, twigs,
-- saplings, shrubs). Tree trunks are in the way but can be felled: up to
-- max_trees of them (a spot with fewer trees is better); the result lists
-- them as trees = {{x, y, z}, ...}.
function find_surface_rect(w, h, min_d, reserved, shapes, max_trees)
    shapes = shapes or {FLOOR = true}
    max_trees = max_trees or 0
    local anchors = pasture_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to start from' end
    local groups = {}
    for _, p in ipairs(citizen_positions()) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
    end
    local mw, mh = map_size()
    local cache = {}
    local function ok(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v ~= nil then return v end
        v = false
        if x >= 2 and y >= 2 and x <= mw - 3 and y <= mh - 3 then
            local t = tile_info(x, y, z)
            if t ~= nil and t.outside and not t.hidden and not t.liquid and not t.feature and not t.building
                    and not inside_any(reserved or {}, x, y, z) and not tile_taken(x, y, z) then
                if is_tree(t) then
                    v = max_trees > 0 and 'tree'
                elseif shapes[t.shape] == true and not t.designated and groups[walk_group(x, y, z)] == true then
                    v = true
                end
            end
        end
        cache[k] = v
        return v
    end
    local best, best_d
    local deadline = os.clock() + PASTURE_SEARCH_SECONDS
    for _, a in ipairs(anchors) do
        for z = a.z - 1, a.z + 1 do
            for y = a.y - SURFACE_RADIUS, a.y + SURFACE_RADIUS do
                if os.clock() > deadline then break end
                for x = a.x - SURFACE_RADIUS, a.x + SURFACE_RADIUS do
                    local d = math.max(math.abs(x + w // 2 - a.x), math.abs(y + h // 2 - a.y))
                    if d >= min_d and (not best_d or d < best_d) then
                        local fits, trees, open = true, {}, 0
                        for dy = 0, h - 1 do
                            for dx = 0, w - 1 do
                                local v = ok(x + dx, y + dy, z)
                                if not v then fits = false break end
                                if v == 'tree' then
                                    table.insert(trees, {x = x + dx, y = y + dy, z = z})
                                else
                                    open = open + 1
                                end
                            end
                            if not fits or #trees > max_trees then fits = false break end
                        end
                        if fits and open == 0 then fits = false end
                        d = d + SURFACE_TREE_COST * #trees
                        -- and nothing of it within min_d of the way in
                        if fits then
                            for _, b in ipairs(anchors) do
                                if b.z == z and x - min_d < b.x and b.x < x + w + min_d
                                        and y - min_d < b.y and b.y < y + h + min_d then
                                    fits = false
                                end
                            end
                        end
                        if fits and (not best_d or d < best_d) then
                            best, best_d = {x = x, y = y, z = z, trees = trees}, d
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    return nil, ('no %dx%d patch of flat ground near the surface entrances%s'):format(w, h,
        max_trees > 0 and (' (with %d trees or fewer to fell)'):format(max_trees) or '')
end

-- Mark a tree for felling (DFHack's own call; else the dig flag DF uses for
-- felling, as autochop does). True when it is marked.
function fell_tree(x, y, z)
    local ok = pcall(function()
        local plant = dfhack.maps.getPlantAtTile(x, y, z)
        if plant then dfhack.designations.markPlant(plant) end
    end)
    local d = dfhack.maps.getTileFlags(x, y, z)
    if d and d.dig == df.tile_dig_designation.No then
        d.dig = df.tile_dig_designation.Default
        local block = dfhack.maps.getTileBlock(x, y, z)
        if block then block.flags.designated = true end
    end
    return ok or (d ~= nil and d.dig ~= df.tile_dig_designation.No)
end

-- Something placed outside: a refuse stockpile ('refuse') or a trade depot
-- ('depot'). Placed through Quickfort like everything else; the depot waits
-- for its materials (buildingplan).
local GROUND = {FLOOR = true, BOULDER = true, PEBBLES = true, TWIG = true, SAPLING = true, SHRUB = true}
local SURFACE_THINGS = {
    refuse = {w = 5, h = 5, min_d = 6, mode = 'place', text = 'r(5x5)', what = 'a refuse pile', shapes = GROUND},
    depot = {w = 5, h = 5, min_d = 4, mode = 'build', text = 'D', what = 'a trade depot', shapes = GROUND},
    -- a garbage dump zone: things marked for dumping are taken there (the AI
    -- marks worn-out clothes lying about when the game runs slowly)
    dump = {w = 3, h = 3, min_d = 8, mode = 'zone', text = 'd(3x3)', what = 'a garbage dump', shapes = GROUND},
    -- an animal stockpile: full cages from the cage traps go there, so the
    -- traps are loaded with empty cages again (prisoners stay in their cages)
    cages = {w = 3, h = 3, min_d = 6, mode = 'place', text = 'a(3x3)', what = 'a stockpile for full cages',
             shapes = GROUND},
}
CLEARING_KEY = 'ai-overseer/clearing'

-- Spots being cleared for something outside: kind -> {x, y, z, w, h}.
function clearing_spots()
    local ok, d = pcall(dfhack.persistent.getSiteData, CLEARING_KEY, {})
    return ok and type(d) == 'table' and d or {}
end

local function save_clearing(d)
    pcall(dfhack.persistent.saveSiteData, CLEARING_KEY, d)
end

-- Trees still standing in a spot being cleared: {{x, y, z}, ...}, or nil if
-- the spot can't take the thing any more (something else built there).
local function trees_left(c, shapes)
    local out = {}
    for y = c.y, c.y + c.h - 1 do
        for x = c.x, c.x + c.w - 1 do
            local t = tile_info(x, y, c.z)
            if not t or t.liquid or t.building then return nil end
            if is_tree(t) then
                table.insert(out, {x = x, y = y, z = c.z})
            elseif not shapes[t.shape] then
                return nil
            end
        end
    end
    return out
end

-- The report's view: kind -> trees left to fell.
function clearing_status()
    local out = {}
    for kind, c in pairs(clearing_spots()) do
        local k = SURFACE_THINGS[kind]
        local left = k and type(c) == 'table' and trees_left(c, k.shapes)
        if left then out[kind] = #left end
    end
    return out
end

function place_surface(kind, dry_run)
    OFFSET = elevation_offset()
    local k = SURFACE_THINGS[kind]
    if not k then return {ok = false, rejected = true, error = 'unknown surface thing: ' .. tostring(kind)} end
    local data = load_projects()
    local reserved = {}
    for _, p in ipairs(open_projects(data)) do table.insert(reserved, p.area) end
    -- a spot already being cleared: wait for the trees, then place there
    local clearing = clearing_spots()
    local spot, why
    local c = clearing[kind]
    if type(c) == 'table' then
        local left = trees_left(c, k.shapes)
        if left and #left > 0 then
            if not dry_run then for _, t in ipairs(left) do fell_tree(t.x, t.y, t.z) end end
            return {ok = false, rejected = true, waiting = true, kind = kind, trees = #left,
                    error = ('the dwarves are still felling %d tree(s) to make room for %s at x%d y%d')
                        :format(#left, k.what, c.x, c.y)}
        elseif left then
            spot = {x = c.x, y = c.y, z = c.z, trees = {}}
        end
        if not dry_run then
            clearing[kind] = nil
            save_clearing(clearing)
        end
    end
    if not spot then
        spot, why = find_surface_rect(k.w, k.h, k.min_d, reserved, k.shapes, SURFACE_MAX_TREES)
    end
    if not spot then return {ok = false, error = why} end
    if #spot.trees > 0 then
        local out = {ok = true, kind = kind, clearing = true, trees = #spot.trees, x = spot.x, y = spot.y,
                     elevation = ez(spot.z), dry_run = dry_run or nil}
        if dry_run then return out end
        local marked = 0
        for _, t in ipairs(spot.trees) do if fell_tree(t.x, t.y, t.z) then marked = marked + 1 end end
        if marked == 0 then
            return {ok = false, error = ('the game would not mark the trees at x%d y%d for felling'):format(spot.x, spot.y)}
        end
        clearing[kind] = {x = spot.x, y = spot.y, z = spot.z, w = k.w, h = k.h}
        save_clearing(clearing)
        return out
    end
    -- a depot's 5x5 is placed from its centre in Quickfort
    local ax, ay = spot.x, spot.y
    if kind == 'depot' then ax, ay = spot.x + 2, spot.y + 2 end
    local cell = {{x = 0, y = 0, text = k.text}}
    local okd, dry = pcall(quickfort_apply, k.mode, cell, spot.z, ax, ay, 'run', true)
    local stat_name = k.mode .. '_designated'
    if not okd or stat(dry, stat_name) < 1 or stat(dry, 'invalid_keys') > 0 then
        return {ok = false, error = ('the game would not place %s at x%d y%d'):format(k.what, spot.x, spot.y)}
    end
    local out = {ok = true, kind = kind, x = spot.x, y = spot.y, elevation = ez(spot.z), dry_run = dry_run or nil}
    if dry_run then return out end
    local okr, real = pcall(quickfort_apply, k.mode, cell, spot.z, ax, ay)
    if not okr or stat(real, stat_name) < 1 then
        return {ok = false, error = ('the game refused %s at x%d y%d'):format(k.what, spot.x, spot.y)}
    end
    return out
end

-- --- river crossings (0.101) ------------------------------------------------------
--
-- Water on the surface can cut the fort off from land its dwarves would use
-- (trees, shrubs, grass for the herds, the map's edge where caravans come in).
-- The survey (crossings_report, a slow report section, rebuilt weekly) maps the
-- fort's side of the water from its surface entrance, then the shortest
-- straight crossings of water or ice to land on another side, and what lies
-- over there. The planner weighs it (brain/planner.py _crossing_rule): a cheap
-- narrow bridge early, a wider one once the fort is established, the old one
-- then taken down. Only the AI's own bridges (recorded in the save) are ever
-- taken down. Water counts whether it's flowing, still or frozen (ice melts).
CROSS_KEY = 'ai-overseer/crossings'
CROSS_RADIUS = 45          -- how far from the entrance each side is mapped
CROSS_MAX_SPAN = 9         -- the widest water a bridge here spans
CROSS_SIDE_CAP = 6000      -- tiles mapped per side (time)
CROSS_SECONDS = 1.0   -- (0.104.140, review: kept at 1.0; a cut survey is cached for a week)
CROSS_CANDIDATES = 6       -- the shortest crossings looked across
local CROSS_WALK = {FLOOR = true, SHRUB = true, SAPLING = true, PEBBLES = true, BOULDER = true, TWIG = true,
                    RAMP = true, BROOK_TOP = true}
local CROSS_GRASS = {GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true}
local CROSS_DIRS = {n = {0, -1}, s = {0, 1}, w = {-1, 0}, e = {1, 0}}

function cross_tile(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    local attrs = df.tiletype.attrs[tt]
    local des = dfhack.maps.getTileFlags(x, y, z)
    if not des then return nil end
    return df.tiletype_shape[attrs.shape], df.tiletype_material[attrs.material],
           des.flow_size > 0 and not (des.liquid_type == true or des.liquid_type == 1), des.flow_size > 0
end

-- water or ice to bridge at z (or open air over it, the river a level down)
function cross_gap(x, y, z)
    local shape, mat, water, liquid = cross_tile(x, y, z)
    if not shape then return false end
    if water or mat == 'FROZEN_LIQUID' then return true end
    if liquid then return false                              -- magma: never
    end
    if shape == 'EMPTY' or shape == 'RAMP_TOP' then
        local s2, m2, w2 = cross_tile(x, y, z - 1)
        return s2 ~= nil and (w2 or m2 == 'FROZEN_LIQUID')
    end
    return false
end

function cross_ground(x, y, z)
    local shape, mat, _, liquid = cross_tile(x, y, z)
    return shape ~= nil and CROSS_WALK[shape] == true and not liquid and mat ~= 'FROZEN_LIQUID'
end

-- One side of the water: the ground walked to from (sx, sy) within the
-- radius of (cx, cy), never into `other`. Counts what's there.
local function cross_side(sx, sy, z, cx, cy, other, cap, deadline)
    local W, H = map_size()
    local seen, queue, head = {[sx .. ',' .. sy] = true}, {{sx, sy}}, 1
    local n = {tiles = 0, shrubs = 0, saplings = 0, grass = 0, trees = 0, edge = false}
    local trees = {}
    while head <= #queue and #queue < cap do
        if os.clock() > deadline then n.cut = true break end
        local x, y = queue[head][1], queue[head][2]
        head = head + 1
        n.tiles = n.tiles + 1
        local shape, mat = cross_tile(x, y, z)
        if shape == 'SHRUB' then n.shrubs = n.shrubs + 1 elseif shape == 'SAPLING' then n.saplings = n.saplings + 1 end
        if CROSS_GRASS[mat] then n.grass = n.grass + 1 end
        if x <= 1 or y <= 1 or x >= W - 2 or y >= H - 2 then n.edge = true end
        for _, d in pairs(CROSS_DIRS) do
            local nx, ny = x + d[1], y + d[2]
            local k = nx .. ',' .. ny
            if not seen[k] and not (other and other[k]) and math.abs(nx - cx) <= CROSS_RADIUS
                    and math.abs(ny - cy) <= CROSS_RADIUS then
                local s2, m2 = cross_tile(nx, ny, z)
                if m2 == 'TREE' and not trees[k] then trees[k] = true; n.trees = n.trees + 1 end
                if cross_ground(nx, ny, z) then
                    seen[k] = true
                    table.insert(queue, {nx, ny})
                end
            end
        end
    end
    n.capped = #queue >= cap or nil
    return seen, n
end

-- A straight crossing from a ground tile at (x, y) heading `dir`: the water
-- tiles and the far bank, or nil.
local function cross_line(x, y, z, dir, near)
    local d = CROSS_DIRS[dir]
    local cx, cy, len = x + d[1], y + d[2], 0
    while len < CROSS_MAX_SPAN and cross_gap(cx, cy, z) and not dfhack.buildings.findAtTile(xyz2pos(cx, cy, z)) do
        len = len + 1
        cx, cy = cx + d[1], cy + d[2]
    end
    if len == 0 or len >= CROSS_MAX_SPAN and cross_gap(cx, cy, z) then return nil end
    if not cross_ground(cx, cy, z) or near[cx .. ',' .. cy] then return nil end
    return {x = x + d[1], y = y + d[2], len = len, far = {x = cx, y = cy}}
end

-- How many crossings of the same length lie side by side (for a wider bridge),
-- from this one sideways: the width available, up to `want`.
local function cross_width(c, z, dir, near, want)
    local d = CROSS_DIRS[dir]
    local sx, sy = d[2] ~= 0 and 1 or 0, d[1] ~= 0 and 1 or 0     -- sideways
    local w = 1
    for i = 1, want - 1 do
        local bx, by = c.x - d[1] + sx * i, c.y - d[2] + sy * i
        local o = cross_ground(bx, by, z) and cross_line(bx, by, z, dir, near)
        if not o or o.len ~= c.len then break end
        w = w + 1
    end
    return w
end

function crossings_data()
    local ok, d = pcall(dfhack.persistent.getSiteData, CROSS_KEY, {})
    d = ok and type(d) == 'table' and d or {}
    d.list = type(d.list) == 'table' and d.list or {}
    return d
end

-- The report section: the fort's side, the crossings and the far sides, the
-- AI's bridges and whether each is built.
function crossings_report()
    local okoff, off = pcall(elevation_offset)
    OFFSET = okoff and off or OFFSET or 0
    local anchors = pasture_anchors()
    if #anchors == 0 then return {none = true, why = 'no surface entrance or staircase yet'} end
    local a = anchors[1]
    local deadline = os.clock() + CROSS_SECONDS
    -- the ground beside the way in: the entrance is kept at the stair's top,
    -- and the open ground can be a level or two up (a hatch over the stair)
    local sx, sy, z
    for dz = 0, 2 do
        local zz = a.z + dz
        if cross_ground(a.x, a.y, zz) then sx, sy, z = a.x, a.y, zz
        else
            for _, d in pairs(CROSS_DIRS) do
                if cross_ground(a.x + d[1], a.y + d[2], zz) then sx, sy, z = a.x + d[1], a.y + d[2], zz break end
            end
        end
        if sx then break end
    end
    if not sx then return {none = true, why = 'no open ground beside the surface entrance'} end
    local near, ncount = cross_side(sx, sy, z, a.x, a.y, nil, CROSS_SIDE_CAP, deadline)
    local cands, seen_far = {}, {}
    for k in pairs(near) do
        local x, y = k:match('^(%-?%d+),(%-?%d+)$')
        x, y = tonumber(x), tonumber(y)
        for dir in pairs(CROSS_DIRS) do
            local d = CROSS_DIRS[dir]
            if cross_gap(x + d[1], y + d[2], z) then
                local c = cross_line(x, y, z, dir, near)
                if c then
                    c.dir, c.z = dir, z
                    c.dist = math.abs(x - a.x) + math.abs(y - a.y)
                    table.insert(cands, c)
                end
            end
        end
    end
    table.sort(cands, function(p, q) if p.len ~= q.len then return p.len < q.len end return p.dist < q.dist end)
    local out = {}
    for _, c in ipairs(cands) do
        if #out >= CROSS_CANDIDATES or os.clock() > deadline then break end
        local fk = c.far.x .. ',' .. c.far.y
        if not seen_far[fk] then
            local far, fcount = cross_side(c.far.x, c.far.y, z, c.far.x, c.far.y, near,
                                           math.floor(CROSS_SIDE_CAP / 2), deadline)
            for k2 in pairs(far) do seen_far[k2] = true end      -- one crossing per far side
            c.width = cross_width(c, z, c.dir, near, 3)
            c.far_side = fcount
            c.elevation = ez(z)
            table.insert(out, c)
        end
    end
    local d = crossings_data()
    local mine = {}
    for i, b in ipairs(d.list) do
        local bld = b.x and dfhack.buildings.findAtTile(xyz2pos(b.x, b.y, b.z))
        local built = bld and bld:getType() == df.building_type.Bridge
            and bld:getBuildStage() >= bld:getMaxBuildStage() or false
        table.insert(mine, {index = i, x = b.x, y = b.y, z = b.z, len = b.len, width = b.width, kind = b.kind,
                            tick = b.tick, present = bld ~= nil, built = built})
    end
    return {z = z, elevation = ez(z), entrance = {x = a.x, y = a.y}, near = ncount, crossings = out, mine = mine}
end

-- Build a bridge across: (x, y) the first water tile, `dir` across, `len`
-- water tiles, `width` side by side. Checked again tile by tile here.
function build_crossing(x, y, z, dir, len, width, kind, now, dry_run)
    local d = CROSS_DIRS[dir]
    if not d then return {ok = false, rejected = true, error = 'dir must be n, s, e or w'} end
    if len < 1 or len > CROSS_MAX_SPAN or width < 1 or width > 3 then
        return {ok = false, rejected = true, error = 'a crossing is 1-' .. CROSS_MAX_SPAN .. ' long and 1-3 wide'}
    end
    local sx, sy = d[2] ~= 0 and 1 or 0, d[1] ~= 0 and 1 or 0
    for i = 0, width - 1 do
        local bx, by = x + sx * i, y + sy * i
        if not cross_ground(bx - d[1], by - d[2], z) then
            return {ok = false, rejected = true, error = 'no bank to start from at that spot'}
        end
        for j = 0, len - 1 do
            local tx, ty = bx + d[1] * j, by + d[2] * j
            if not cross_gap(tx, ty, z) then
                return {ok = false, rejected = true, error = ('x%d y%d is no longer water or ice'):format(tx, ty)}
            end
            if dfhack.buildings.findAtTile(xyz2pos(tx, ty, z)) then
                return {ok = false, rejected = true, error = ('something is built at x%d y%d'):format(tx, ty)}
            end
        end
        if not cross_ground(bx + d[1] * len, by + d[2] * len, z) then
            return {ok = false, rejected = true, error = 'no bank on the far side at that spot'}
        end
    end
    -- the rectangle: top-left corner and size
    local x1 = math.min(x, x + d[1] * (len - 1), x + sx * (width - 1))
    local y1 = math.min(y, y + d[2] * (len - 1), y + sy * (width - 1))
    local w = d[1] ~= 0 and len or width
    local h = d[2] ~= 0 and len or width
    local text = ('gx(%dx%d)'):format(w, h)       -- (never linked to a lever: it stays down)
    local cell = {{x = 0, y = 0, text = text}}
    local okd, dry = pcall(quickfort_apply, 'build', cell, z, x1, y1, 'run', true)
    if not okd or stat(dry, 'build_designated') < 1 then
        return {ok = false, error = ('the game would not place a bridge at x%d y%d (%dx%d)'):format(x1, y1, w, h)}
    end
    local out = {ok = true, x = x1, y = y1, elevation = ez(z), w = w, h = h, kind = kind, dry_run = dry_run or nil}
    if dry_run then return out end
    local okr, real = pcall(quickfort_apply, 'build', cell, z, x1, y1)
    if not okr or stat(real, 'build_designated') < 1 then
        return {ok = false, error = ('the game refused the bridge at x%d y%d'):format(x1, y1)}
    end
    local data = crossings_data()
    table.insert(data.list, {x = x1, y = y1, z = z, w = w, h = h, len = len, width = width, dir = dir,
                             kind = kind or 'cheap', tick = now})
    pcall(dfhack.persistent.saveSiteData, CROSS_KEY, data)
    return out
end

-- Take down one of the AI's own bridges (an older, narrower one once its
-- replacement stands). The player's bridges are never touched.
function remove_crossing(index, dry_run)
    local data = crossings_data()
    local b = data.list[index]
    if not b then return {ok = false, rejected = true, error = 'no AI crossing number ' .. tostring(index)} end
    local bld = dfhack.buildings.findAtTile(xyz2pos(b.x, b.y, b.z))
    if bld and bld:getType() ~= df.building_type.Bridge then
        return {ok = false, rejected = true, error = 'that spot holds something else now: left alone'}
    end
    if dry_run then return {ok = true, dry_run = true, index = index} end
    if bld then dfhack.buildings.deconstruct(bld) end
    table.remove(data.list, index)
    pcall(dfhack.persistent.saveSiteData, CROSS_KEY, data)
    return {ok = true, index = index, removed = bld ~= nil}
end

-- --- the keep: building above ground (the Surface ambition) ----------------------
--
-- A walled court around the fort's way in from the surface: a square ring of
-- constructed walls (radius 4-6 tiles from the entrance) with one door, then
-- a roof of constructed floor over the inside. Natural rock in the ring
-- counts as wall already; trees in the ring are felled first. Never put
-- around a trade depot (the wagons couldn't reach it), never over water,
-- buildings, zones or slopes. Built in stages, one action each:
--   clearing -> walls (+ door) -> roof -> done
-- The state lives in the save (site data 'ai-overseer/keep').
KEEP_KEY = 'ai-overseer/keep'
KEEP_RADII = {4, 5, 6}

function keep_data()
    local ok, d = pcall(dfhack.persistent.getSiteData, KEEP_KEY, {})
    return ok and type(d) == 'table' and d.x and d or nil
end

local function save_keep(d)
    pcall(dfhack.persistent.saveSiteData, KEEP_KEY, d or {})
end

local function ring_tiles(cx, cy, r)
    local out = {}
    for x = cx - r, cx + r do
        table.insert(out, {x = x, y = cy - r})
        table.insert(out, {x = x, y = cy + r})
    end
    for y = cy - r + 1, cy + r - 1 do
        table.insert(out, {x = cx - r, y = y})
        table.insert(out, {x = cx + r, y = y})
    end
    return out
end

-- What a ring tile is: 'ground' (a wall can go up), 'tree', 'wall' (rock or a
-- wall already: closed), 'planned' (a wall waiting to be built) or nil (no use).
local function keep_tile(x, y, z)
    local t = tile_info(x, y, z)
    if not t or t.liquid or t.feature then return nil end
    if is_tree(t) then return 'tree' end
    if t.shape == 'WALL' then return 'wall' end
    if t.building then return 'planned' end
    if t.hidden or not t.outside or t.designated or tile_taken(x, y, z) then return nil end
    if GROUND[t.shape] then return 'ground' end
    return nil
end

local function depot_inside(x1, y1, x2, y2, z)
    local ok, found = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
            if b.z == z and b.x2 >= x1 and b.x1 <= x2 and b.y2 >= y1 and b.y1 <= y2 then return true end
        end
        return false
    end)
    return ok and found
end

-- (0.104.0, map safety) A trade depot under a roof or underground: the
-- caravans' wagons reach it through the fort's way in, and the keep's ring
-- (one door, no 3-wide way) would shut them out. Returns why, or nil.
function depot_underground()
    local ok, why = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
            local cx, cy = math.floor((b.x1 + b.x2) / 2), math.floor((b.y1 + b.y2) / 2)
            local t = tile_info(cx, cy, b.z)
            if t and not t.outside then
                return ('the trade depot at x%d y%d is underground: a walled keep round the way in would shut '
                        .. 'out the caravans\' wagons'):format(cx, cy)
            end
        end
    end)
    return ok and why or nil
end

-- The door: the middle of a side whose ring tile takes a wall and has open
-- ground on both sides of it (south, east, north, west in turn).
local function keep_door(cx, cy, z, r)
    for _, d in ipairs({{0, 1}, {1, 0}, {0, -1}, {-1, 0}}) do
        local x, y = cx + d[1] * r, cy + d[2] * r
        local inner = tile_info(x - d[1], y - d[2], z)
        local outer = tile_info(x + d[1], y + d[2], z)
        if keep_tile(x, y, z) == 'ground' and inner and outer and GROUND[inner.shape] and GROUND[outer.shape]
                and not inner.building and not outer.building and not outer.liquid then
            return {x = x, y = y}
        end
    end
end

-- A site for the keep around the surface entrance: {x, y, z, r, door, trees}.
function find_keep_site()
    local anchors = pasture_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to build the keep around' end
    local under = depot_underground()
    if under then return nil, under end
    local last
    for _, a in ipairs(anchors) do
        for _, r in ipairs(KEEP_RADII) do
            local fits, trees, ground = true, {}, 0
            for _, p in ipairs(ring_tiles(a.x, a.y, r)) do
                local k = keep_tile(p.x, p.y, a.z)
                if not k or k == 'planned' then fits = false break end
                if k == 'tree' then table.insert(trees, {x = p.x, y = p.y, z = a.z}) end
                if k == 'ground' then ground = ground + 1 end
            end
            if fits and #trees > SURFACE_MAX_TREES then
                fits, last = false, ('too many trees around the way in (%d to fell)'):format(#trees)
            end
            if fits and ground == 0 and #trees == 0 then fits = false end
            if fits and depot_inside(a.x - r, a.y - r, a.x + r, a.y + r, a.z) then
                fits, last = false, 'the trade depot is right by the way in (a wall round it would shut out the wagons)'
            end
            local door = fits and keep_door(a.x, a.y, a.z, r)
            if fits and not door then last = 'no side of the ring has open ground for a door' end
            if fits and door then
                return {x = a.x, y = a.y, z = a.z, r = r, door = door, trees = trees}
            end
        end
    end
    return nil, last or 'no ring of open ground around the way in (water, slopes, buildings or zones in the way)'
end

-- How far it's got: {stage, x, y, z, r, walls_left, roof_left, trees_left}.
function keep_status()
    local k = keep_data()
    if not k then return nil end
    local out = {stage = k.stage, x = k.x, y = k.y, z = k.z, r = k.r, walls_left = 0, walls_planned = 0,
                 roof_left = 0, roof_planned = 0, trees_left = 0}
    for _, p in ipairs(ring_tiles(k.x, k.y, k.r)) do
        local t = keep_tile(p.x, p.y, k.z)
        if t == 'tree' then out.trees_left = out.trees_left + 1 end
        local is_door = k.door and p.x == k.door.x and p.y == k.door.y
        if not is_door and t ~= 'wall' then out.walls_left = out.walls_left + 1 end
        if not is_door and t == 'planned' then out.walls_planned = out.walls_planned + 1 end
    end
    if k.stage == 'roof' or k.stage == 'done' then
        for y = k.y - k.r + 1, k.y + k.r - 1 do
            for x = k.x - k.r + 1, k.x + k.r - 1 do
                local t = tile_info(x, y, k.z + 1)
                if t and t.shape == 'EMPTY' then
                    out.roof_left = out.roof_left + 1
                    if t.building then out.roof_planned = out.roof_planned + 1 end
                end
            end
        end
    end
    out.elevation = ez(k.z)
    return out
end

local function keep_apply(cells, z, what, dry_run)
    local okd, dry = pcall(quickfort_apply, 'build', cells, z, 0, 0, 'run', true)
    if not okd or stat(dry, 'build_designated') < 1 or stat(dry, 'invalid_keys') > 0 then
        return nil, ('the game would not place %s'):format(what)
    end
    if dry_run then return stat(dry, 'build_designated') end
    local okr, real = pcall(quickfort_apply, 'build', cells, z, 0, 0)
    if not okr or stat(real, 'build_designated') < 1 then return nil, ('the game refused %s'):format(what) end
    return stat(real, 'build_designated')
end

-- One step of the keep (see above).
function place_keep(dry_run)
    OFFSET = elevation_offset()
    local k = keep_data()
    if k and k.stage == 'done' then
        return {ok = false, rejected = true, done = true, error = 'the keep is finished'}
    end
    if not k then
        local site, why = find_keep_site()
        if not site then return {ok = false, error = why} end
        k = {x = site.x, y = site.y, z = site.z, r = site.r, door = site.door, stage = 'clearing'}
        if #site.trees > 0 then
            local out = {ok = true, stage = 'clearing', clearing = true, trees = #site.trees, x = k.x, y = k.y,
                         r = k.r, elevation = ez(k.z), dry_run = dry_run or nil}
            if dry_run then return out end
            for _, t in ipairs(site.trees) do fell_tree(t.x, t.y, t.z) end
            save_keep(k)
            return out
        end
    end
    local st = {}
    if k.stage == 'clearing' then
        local under = depot_underground()     -- (0.104.0) a depot dug underground since the site was chosen
        if under then
            if not dry_run then save_keep(nil) end
            return {ok = false, error = under}
        end
        local trees = {}
        for _, p in ipairs(ring_tiles(k.x, k.y, k.r)) do
            local t = keep_tile(p.x, p.y, k.z)
            if t == 'tree' then table.insert(trees, p) end
            if t == nil then
                if not dry_run then save_keep(nil) end
                return {ok = false, error = 'something was put in the way of the keep\'s walls: looking again next time'}
            end
        end
        if #trees > 0 then
            if not dry_run then for _, p in ipairs(trees) do fell_tree(p.x, p.y, k.z) end end
            return {ok = false, rejected = true, waiting = true, stage = 'clearing', trees = #trees,
                    error = ('the dwarves are still felling %d tree(s) for the keep\'s walls'):format(#trees)}
        end
        local cells = {}
        for _, p in ipairs(ring_tiles(k.x, k.y, k.r)) do
            if keep_tile(p.x, p.y, k.z) == 'ground' then
                local door = p.x == k.door.x and p.y == k.door.y
                table.insert(cells, {x = p.x, y = p.y, text = door and 'd' or 'Cw'})
            end
        end
        local n, why = keep_apply(cells, k.z, 'the keep\'s walls', dry_run)
        if not n then return {ok = false, error = why} end
        local out = {ok = true, stage = 'walls', walls = n, x = k.x, y = k.y, r = k.r, door = k.door,
                     elevation = ez(k.z), dry_run = dry_run or nil}
        if not dry_run then k.stage = 'walls'; save_keep(k) end
        return out
    end
    if k.stage == 'walls' then
        st = keep_status() or {}
        -- (a wall tile the game refused never gets built: the roof goes on
        -- once nothing of the walls waits to be built)
        if (st.walls_planned or 0) > 0 then
            return {ok = false, rejected = true, waiting = true, stage = 'walls', walls_left = st.walls_planned,
                    error = ('the keep\'s walls are going up: %d to build'):format(st.walls_planned)}
        end
        local cells = {}
        for y = k.y - k.r + 1, k.y + k.r - 1 do
            for x = k.x - k.r + 1, k.x + k.r - 1 do
                local t = tile_info(x, y, k.z + 1)
                if t and t.shape == 'EMPTY' and not t.building then
                    table.insert(cells, {x = x, y = y, text = 'Cf'})
                end
            end
        end
        if #cells == 0 then
            if not dry_run then k.stage = 'done'; save_keep(k) end
            return {ok = true, stage = 'done', x = k.x, y = k.y, dry_run = dry_run or nil}
        end
        local n, why = keep_apply(cells, k.z + 1, 'the keep\'s roof', dry_run)
        if not n then return {ok = false, error = why} end
        if not dry_run then k.stage = 'roof'; save_keep(k) end
        return {ok = true, stage = 'roof', roof = n, x = k.x, y = k.y, r = k.r, elevation = ez(k.z + 1),
                dry_run = dry_run or nil}
    end
    -- the roof is going up
    st = keep_status() or {}
    if (st.roof_planned or 0) > 0 then
        return {ok = false, rejected = true, waiting = true, stage = 'roof', roof_left = st.roof_planned,
                error = ('the keep\'s roof is going up: %d tile(s) to build'):format(st.roof_planned)}
    end
    if not dry_run then k.stage = 'done'; save_keep(k) end
    return {ok = true, stage = 'done', x = k.x, y = k.y, holes = st.roof_left, dry_run = dry_run or nil}
end

-- --- extra workshops ----------------------------------------------------------------
--
-- Workshops the fort has far too many of (0.75.0 built 116 soap maker's:
-- the report didn't recognise them). All but `keep` taken down, the idle
-- ones (no job), up to `max` a call; the dug rooms are left as they are.
local CUSTOM_CODES = {SoapMaker = {SOAP_MAKER = true, SOAP_MAKERS = true}, ScrewPress = {SCREW_PRESS = true}}

local function is_kind(b, kind)
    local ok, yes = pcall(function()
        if b:getType() ~= df.building_type.Workshop then return false end
        local codes = CUSTOM_CODES[kind]
        if codes then
            return df.workshop_type[b.type] == 'Custom' and codes[df.building_def.find(b.custom_type).code] == true
        end
        return df.workshop_type[b.type] == kind
    end)
    return ok and yes
end

function remove_workshops(kind, keep, max, dry_run)
    local all = {}
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        if is_kind(b, kind) then table.insert(all, b) end
    end
    keep = math.max(1, keep or 1)
    if #all <= keep then return {ok = false, rejected = true, error = ('only %d %s'):format(#all, kind)} end
    -- keep the ones at work, then the oldest
    table.sort(all, function(a, b)
        if (#a.jobs > 0) ~= (#b.jobs > 0) then return #a.jobs > 0 end
        return a.id < b.id
    end)
    local removed = 0
    for i = keep + 1, #all do
        if removed >= (max or 20) then break end
        local b = all[i]
        if #b.jobs == 0 then
            if not dry_run then
                local ok = pcall(dfhack.buildings.deconstruct, b)
                if ok then removed = removed + 1 end
            else
                removed = removed + 1
            end
        end
    end
    return {ok = removed > 0, kind = kind, had = #all, removed = removed, dry_run = dry_run or nil,
            error = removed == 0 and 'the extra ones are all at work' or nil}
end

-- --- feeder stockpiles ------------------------------------------------------------
--
-- A small stockpile beside a workshop for what it uses (stone by the masons,
-- wood by the carpenters, bars by the forge, food by the kitchen...), and one
-- for finished goods beside the trade depot: new stone, logs and goods go to
-- the nearest pile, so the walk to the workshop shrinks (hauling distance is
-- what slows a big fort most). Placed on free floor 2-6 tiles from the
-- building (a tile of space left around it), 3x3 else 2x2, through Quickfort.

FEEDERS = {
    Masons = {key = 's', flag = 'stone', what = 'stone'},
    Craftsdwarfs = {key = 's', flag = 'stone', what = 'stone'},
    Smelter = {key = 's', flag = 'stone', what = 'ore'},
    Carpenters = {key = 'w', flag = 'wood', what = 'wood'},
    Bowyers = {key = 'w', flag = 'wood', what = 'wood'},
    WoodFurnace = {key = 'w', flag = 'wood', what = 'wood'},
    MetalsmithsForge = {key = 'b', flag = 'bars_blocks', what = 'bars'},
    Kitchen = {key = 'f', flag = 'food', what = 'food'},
    Still = {key = 'f', flag = 'food', what = 'food'},
    Clothiers = {key = 'h', flag = 'cloth', what = 'cloth'},
    Loom = {key = 'h', flag = 'cloth', what = 'thread'},
    Leatherworks = {key = 'l', flag = 'leather', what = 'leather'},
    Depot = {key = 'g', flag = 'finished_goods', what = 'goods for the caravans', ground = true, reach = 8},
}
FEEDER_NEAR = 6

local function bkind(b)
    local t = b:getType()
    if t == df.building_type.Workshop then
        local n = df.workshop_type[b.type]
        if n == 'MagmaForge' then n = 'MetalsmithsForge' end
        return n
    elseif t == df.building_type.Furnace then
        local n = df.furnace_type[b.type]
        if n == 'MagmaSmelter' then n = 'Smelter' end
        return n
    elseif t == df.building_type.TradeDepot then
        return 'Depot'
    end
end

-- A stockpile taking `flag` within `r` tiles of the box.
local function pile_near(flag, x1, y1, x2, y2, z, r)
    for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
        if sp.z == z and sp.x2 >= x1 - r and sp.x1 <= x2 + r and sp.y2 >= y1 - r and sp.y1 <= y2 + r then
            local ok, on = pcall(function() return sp.settings.flags[flag] end)
            if ok and on then return true end
        end
    end
    return false
end

local function free_floor(x, y, z, ground)
    local t = tile_info(x, y, z)
    if not t or t.hidden or t.liquid or t.building or t.designated or t.marked then return false end
    local okp, pile = pcall(function()
        local des = dfhack.maps.getTileFlags(x, y, z)
        return des.pile
    end)
    if okp and pile then return false end
    if ground then return GROUND[t.shape] == true end
    return t.shape == 'FLOOR'
end

-- The nearest w x h of free floor 2..reach tiles from the box (never touching it).
function feeder_rect(x1, y1, x2, y2, z, w, h, ground, reach)
    for d = 2, reach or FEEDER_NEAR do
        for ry = y1 - d - h + 1, y2 + d do
            for rx = x1 - d - w + 1, x2 + d do
                -- the rect's distance from the box is exactly d (a ring at a time)
                local gx = math.max(x1 - (rx + w - 1), rx - x2, 0)
                local gy = math.max(y1 - (ry + h - 1), ry - y2, 0)
                if math.max(gx, gy) == d then
                    local ok = true
                    for yy = ry, ry + h - 1 do
                        for xx = rx, rx + w - 1 do
                            if not free_floor(xx, yy, z, ground) then ok = false break end
                        end
                        if not ok then break end
                    end
                    if ok then return {x = rx, y = ry, z = z, w = w, h = h} end
                end
            end
        end
    end
end

-- Workshops (and the depot) of a kind that wants a feeder, and whether one is near.
function feeder_survey()
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        local kind = bkind(b)
        local f = kind and FEEDERS[kind]
        if f and b:getBuildStage() >= b:getMaxBuildStage() then
            local row = {id = b.id, kind = kind, what = f.what, x = b.centerx, y = b.centery, z = b.z,
                         has = pile_near(f.flag, b.x1, b.y1, b.x2, b.y2, b.z, f.reach or FEEDER_NEAR)}
            -- (0.104.138) whether a pile would fit at all (the Masons had no
            -- room and were asked for one 91 times, the rest never asked)
            if not row.has then
                local okr, r = pcall(feeder_rect, b.x1, b.y1, b.x2, b.y2, b.z, 2, 2, f.ground, f.reach)
                row.room = (okr and r ~= nil) and true or false
            end
            table.insert(out, row)
        end
    end
    return out
end

-- --- how full the stockpiles are --------------------------------------------------
--
-- For each kind of stockpile: its tiles, how many hold an item, and how many
-- items of that kind lie loose outside any pile (on the ground, not in a
-- building or a job, not forbidden). Full piles and loose things around them
-- are the clutter that slows a fort: the planner adds storage for that kind.

STORE_KINDS = {
    food = {'MEAT', 'FISH', 'FISH_RAW', 'PLANT', 'PLANT_GROWTH', 'CHEESE', 'EGG', 'DRINK', 'FOOD', 'SEEDS'},
    wood = {'WOOD'},
    stone = {'BOULDER'},
    bars_blocks = {'BAR', 'BLOCKS'},
    furniture = {'BED', 'TABLE', 'CHAIR', 'DOOR', 'BOX', 'CABINET', 'ARMORSTAND', 'WEAPONRACK', 'STATUE',
                 'COFFIN', 'BARREL', 'BIN', 'BUCKET', 'HATCH_COVER', 'GRATE', 'FLOODGATE', 'SLAB', 'QUERN',
                 'MILLSTONE', 'TRACTION_BENCH', 'ANVIL'},
    finished_goods = {'FIGURINE', 'AMULET', 'BRACELET', 'EARRING', 'RING', 'CROWN', 'SCEPTER', 'GOBLET', 'TOY',
                      'INSTRUMENT', 'TOTEM'},
    cloth = {'CLOTH', 'THREAD'},
    leather = {'SKIN_TANNED'},
    gems = {'ROUGH', 'SMALLGEM'},
    -- (0.99.12) the forge's products: with no pile for them they stayed in
    -- the forge, where the game won't hand them to soldiers (region2: 10 of
    -- 18 battle axes and the squads' helms and greaves at 74,91,166)
    weapons = {'WEAPON', 'TRAPCOMP'},
    armor = {'ARMOR', 'HELM', 'PANTS', 'GLOVES', 'SHOES', 'SHIELD'},
    ammo = {'AMMO'},   -- (0.100) bolts: with no pile they wait at the bowyer's and forge
}
-- kinds whose products waiting in a workshop count as wanting storage
STORE_FROM_WORKSHOPS = {weapons = true, armor = true, ammo = true,   -- (0.100) ammo too
                        finished_goods = true,   -- (0.104.157) cups and crafts left in the craftsdwarf's
                        food = true}   -- (0.104.159) meat left at the butcher's rots: miasma (Teacheroar, 1 Nov)

local function in_workshop(item)
    local f = item.flags
    if f.in_job or f.forbid or f.in_inventory or f.removed or f.garbage_collect then return false end
    local ok, b = pcall(dfhack.items.getHolderBuilding, item)
    return ok and b ~= nil and b:getType() == df.building_type.Workshop
end

local function loose(item)
    local f = item.flags
    if not f.on_ground or f.forbid or f.in_building or f.in_job or f.construction or f.removed
            or f.garbage_collect or f.trader or f.dump or f.hostile or f.in_inventory then
        return false
    end
    -- (0.93) spider webs are thread no one hauls until it's collected:
    -- region2 counted 7261 "loose cloth" beside a cloth pile 7 of 49 full
    local okw, web = pcall(function() return f.spider_web end)
    return not (okw and web)
end

function storage_survey()
    local out = {}
    for kind in pairs(STORE_KINDS) do out[kind] = {tiles = 0, used = 0, loose = 0, piles = 0} end
    for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
        local kinds = {}
        for kind in pairs(STORE_KINDS) do
            local ok, on = pcall(function() return sp.settings.flags[kind] end)
            if ok and on then table.insert(kinds, kind) end
        end
        if #kinds > 0 then
            local tiles, used = 0, 0
            for y = sp.y1, sp.y2 do
                for x = sp.x1, sp.x2 do
                    local des, occ = dfhack.maps.getTileFlags(x, y, sp.z)
                    if des and des.pile then
                        tiles = tiles + 1
                        if occ.item then used = used + 1 end
                    end
                end
            end
            for _, kind in ipairs(kinds) do
                local o = out[kind]
                o.tiles, o.used, o.piles = o.tiles + tiles, o.used + used, o.piles + 1
            end
        end
    end
    local other = df.global.world.items.other
    for kind, types in pairs(STORE_KINDS) do
        for _, tname in ipairs(types) do
            local okl, list = pcall(function() return other[tname] end)
            if okl and list then
                for _, item in ipairs(list) do
                    if loose(item) then
                        local x, y, z = dfhack.items.getPosition(item)
                        local des = x and dfhack.maps.getTileFlags(x, y, z)
                        if des and not des.pile then out[kind].loose = out[kind].loose + 1 end
                    elseif STORE_FROM_WORKSHOPS[kind] and in_workshop(item) then
                        out[kind].loose = out[kind].loose + 1
                        out[kind].in_workshops = (out[kind].in_workshops or 0) + 1
                    end
                end
            end
        end
    end
    return out
end

function place_feeder(building_id, dry_run)
    OFFSET = elevation_offset()
    local b = df.building.find(building_id)
    local kind = b and bkind(b)
    local f = kind and FEEDERS[kind]
    if not f then return {ok = false, rejected = true, error = 'not a workshop that takes a feeder stockpile'} end
    if pile_near(f.flag, b.x1, b.y1, b.x2, b.y2, b.z, f.reach or FEEDER_NEAR) then
        return {ok = false, rejected = true, stale = {'logistics'},
                error = ('the %s already has a %s pile beside it'):format(kind, f.what)}
    end
    local r = feeder_rect(b.x1, b.y1, b.x2, b.y2, b.z, 3, 3, f.ground, f.reach)
        or feeder_rect(b.x1, b.y1, b.x2, b.y2, b.z, 2, 2, f.ground, f.reach)
    if not r then
        return {ok = false, error = ('no free floor beside the %s for a stockpile'):format(kind)}
    end
    local cell = {{x = 0, y = 0, text = ('%s(%dx%d)'):format(f.key, r.w, r.h)}}
    local okd, dry = pcall(quickfort_apply, 'place', cell, r.z, r.x, r.y, 'run', true)
    if not okd or stat(dry, 'place_designated') < 1 or stat(dry, 'invalid_keys') > 0 then
        return {ok = false, error = ('the game would not place a stockpile at x%d y%d'):format(r.x, r.y)}
    end
    local out = {ok = true, kind = kind, what = f.what, x = r.x, y = r.y, elevation = ez(r.z), size = r.w,
                 dry_run = dry_run or nil}
    if dry_run then return out end
    local okr, real = pcall(quickfort_apply, 'place', cell, r.z, r.x, r.y)
    if not okr or stat(real, 'place_designated') < 1 then
        return {ok = false, error = ('the game refused the stockpile at x%d y%d'):format(r.x, r.y)}
    end
    return out
end

-- Make pasture zones for about `tiles` tiles of grass. Returns the zones made.
-- One zone big enough when there's room for it; else the old way (several
-- patches), but never one smaller than the hungriest waiting animal needs.
function make_pasture(params, dry_run)
    OFFSET = elevation_offset()
    local want = math.tointeger(tonumber(params.tiles)) or 0
    local data = load_projects()
    local reserved = {}
    for _, p in ipairs(open_projects(data)) do table.insert(reserved, p.area) end
    local need = 20
    pcall(function()
        local soc = reqscript('ai-society')
        for _, u in ipairs(soc.unpastured_grazers()) do need = math.max(need, soc.grazer_tiles(u)) end
    end)
    local spots, why = {}, nil
    local big, why_big = find_pasture_rect(math.max(want, need), reserved)
    if big then
        spots = {big}
    else
        -- no room for the whole herd in one: pastures that each feed at least
        -- the hungriest animal (the herd is shared out over them)
        local got, taken, stop = 0, {}, os.clock() + 2 * PASTURE_SEARCH_SECONDS
        for _, r in ipairs(reserved) do table.insert(taken, r) end
        while got < want and #spots < PASTURE_MAX_ZONES do
            if os.clock() > stop then break end
            local r = find_pasture_rect(need, taken, stop)
            if not r then break end
            table.insert(spots, r)
            table.insert(taken, {x1 = r.x, y1 = r.y, x2 = r.x + r.w - 1, y2 = r.y + r.h - 1, z = r.z})
            got = got + r.grass
        end
        if #spots == 0 then why = why_big end
    end
    local made, tiles, refused = {}, 0, 0
    for _, sp in ipairs(spots) do
        local cell = {{x = 0, y = 0, text = ('n{name="%s"}(%dx%d)'):format(PASTURE_NAME, sp.w, sp.h)}}
        local ok, dry = pcall(quickfort_apply, 'zone', cell, sp.z, sp.x, sp.y, 'run', true)
        local good = ok and stat(dry, 'zone_designated') >= 1 and stat(dry, 'invalid_keys') == 0
        if good and not dry_run then
            local ok2, real = pcall(quickfort_apply, 'zone', cell, sp.z, sp.x, sp.y)
            good = ok2 and stat(real, 'zone_designated') >= 1
        end
        if good then
            table.insert(made, {x = sp.x, y = sp.y, z = sp.z, elevation = ez(sp.z), w = sp.w, h = sp.h})
            tiles = tiles + sp.w * sp.h
        else
            refused = refused + 1
        end
    end
    if tiles == 0 then
        return {ok = false, error = why or (#spots == 0
            and 'no free patch of living grass (3x3 or more) near the fort\'s surface entrances'
            or ('the game refused the pasture on %d spot(s)'):format(refused))}
    end
    return {ok = true, dry_run = dry_run or nil, zones = made, tiles = tiles,
            refused = refused > 0 and refused or nil}
end

---------------------------------------------------------------------------
-- Polish: idle hands smooth, then engrave, a finished level dug plain (a
-- young fort builds plain; region2 then stood 40% idle for a year with
-- every level rough). Smoothing and engraving make the rooms nicer to live
-- in and add to the fort's wealth (migrants follow wealth). One level at a
-- time, the rooms dwarves use most first; engraving two weeks after the
-- smoothing was asked for (only smooth stone takes an engraving).
---------------------------------------------------------------------------

POLISH_ORDER = {dining = 1, tavern = 2, suites = 3, hospital = 4, temple = 5, library = 6, bedrooms = 7,
                barracks = 8, memorial = 9, jail = 10, archery = 11, garden = 12}
POLISH_ENGRAVE_AFTER = 14 * 1200

local function room_cells(p, key)
    local cells = {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do table.insert(cells, {x = x, y = y, text = key}) end
    end
    return cells
end

-- Pure: the next project to polish and what to do: (project, 'smooth' |
-- 'engrave') or nil. projects: the registry's list; now: game tick.
function polish_pick(projects, now)
    local best, best_rank, what
    for _, p in ipairs(projects) do
        local rank = POLISH_ORDER[p.kind]
        local pol = p.polish or {}
        if p.phase == 'done' and rank then
            local step
            if not pol.step then step = 'smooth'
            elseif pol.step == 'smooth' and type(pol.at) == 'number' and now - pol.at >= POLISH_ENGRAVE_AFTER then
                step = 'engrave'
            end
            if pol.step == 'smooth' and not step then return nil, 'a level is being smoothed' end
            if step and (not best_rank or rank < best_rank) then best, best_rank, what = p, rank, step end
        end
    end
    return best, what
end

function polish_next(dry_run)
    OFFSET = elevation_offset()
    local data = load_projects()
    local now = now_tick()
    local p, what = polish_pick(data.list, now)
    if not p then
        return {ok = false, rejected = true, waiting = what ~= nil or nil,
                error = what or 'every finished level is polished'}
    end
    local cells = room_cells(p, what == 'smooth' and 's' or 'e')
    if #cells == 0 then return {ok = false, rejected = true, error = 'nothing dug in that level'} end
    local out = {ok = true, project_id = p.id, kind = p.kind, step = what, elevation = ez(p.z), tiles = #cells,
                 dry_run = dry_run or nil}
    if dry_run then return out end
    local ok, s = pcall(quickfort_apply, 'dig', cells, p.z, anchor_of(p).x, anchor_of(p).y)
    local n = ok and stat(s, 'dig_designated') or 0
    p.polish = {step = what == 'smooth' and 'smooth' or 'engraved', at = now}
    save_projects(data)
    out.designated = n
    if n == 0 then
        -- nothing took (soil, built floors, already done): the level counts as polished
        out.note = 'nothing there could be ' .. (what == 'smooth' and 'smoothed' or 'engraved')
    end
    return out
end

-- --- furniture into a zone the AI or the player already has ------------------------
--
-- (0.88) A hospital needs a traction bench for broken bones that want
-- traction (DF wiki, Hospital); the AI's hospital layout never had one. One
-- piece of furniture is placed on a free floor tile inside the zone, beside a
-- wall and away from doors so it doesn't block the way, through quickfort
-- (a dry run first). The game builds it once the item exists.

ZONE_FURNITURE = {traction_bench = {key = 'R', what = 'a traction bench'},
                  statue = {key = 's', what = 'a statue'},    -- (0.90) a location's value
                  chest = {key = 'h', what = 'a chest'},       -- (0.104.4) a tavern's goblets, a temple's instruments
                  chain = {key = 'v', what = 'a chain'},       -- (0.104.52) a jail's restraint
                  nest_box = {key = 'N', what = 'a nest box'}} -- (0.104.80) where the hens lay

-- The zone's tiles: {x1, y1, x2, y2, z, has(x, y)} or nil (swapped by the tests).
function zone_area(id)
    local b = df.building.find(id)
    if not b then return nil end
    return {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
            has = function(x, y)
                local ok, yes = pcall(dfhack.buildings.containsTile, b, x, y)
                return not ok or yes
            end}
end

local ORTHO = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

-- A door or hatch on the tile (swapped by the tests).
function door_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, x, y, z)
    if not ok or not b then return false end
    local t = df.building_type[b:getType()]
    return t == 'Door' or t == 'Hatch'
end

function zone_spots(area)
    local spots = {}
    for y = area.y1, area.y2 do
        for x = area.x1, area.x2 do
            local t = area.has(x, y) and tile_info(x, y, area.z)
            -- (0.104.47) and nothing lying there: a slab put on a tile with an
            -- item nobody may move stayed suspended for good (Enxah: 5)
            if t and t.shape == 'FLOOR' and not t.building and not t.liquid and not t.items then
                local walls, door, open = 0, false, 0
                for _, d in ipairs(ORTHO) do
                    local n = tile_info(x + d[1], y + d[2], area.z)
                    if n and n.shape == 'WALL' then walls = walls + 1
                    elseif n and n.building then door = door or door_at(x + d[1], y + d[2], area.z)
                    elseif n and n.shape == 'FLOOR' then open = open + 1 end
                end
                -- beside a wall, not a dead end, and not in front of a door;
                -- (0.104.68) else in the open with room all round (Enxah's
                -- second temple: no free floor by its walls, so no chest)
                if walls >= 1 and open >= 1 and not door then
                    table.insert(spots, {x = x, y = y, walls = walls})
                elseif walls == 0 and open >= 4 and not door then
                    table.insert(spots, {x = x, y = y, walls = 0})
                end
            end
        end
    end
    -- one wall beside it first (a corner can be the only way past), then reading order
    table.sort(spots, function(a, b)
        if (a.walls == 0) ~= (b.walls == 0) then return b.walls == 0 end    -- the open floor last
        if (a.walls == 1) ~= (b.walls == 1) then return a.walls == 1 end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    return spots
end

function place_in_zone(zone_id, what, dry_run)
    OFFSET = elevation_offset()
    local f = ZONE_FURNITURE[what]
    if not f then return {ok = false, rejected = true, error = 'unknown furniture: ' .. tostring(what)} end
    local area = zone_area(zone_id)
    if not area then return {ok = false, rejected = true, error = 'no zone ' .. tostring(zone_id)} end
    local spots = zone_spots(area)
    if #spots == 0 then
        return {ok = false, rejected = true, error = 'no free floor in zone ' .. zone_id}
    end
    for i = 1, math.min(#spots, 12) do
        local sp = spots[i]
        local cell = {{x = 0, y = 0, text = f.key}}
        local ok, dry = pcall(quickfort_apply, 'build', cell, area.z, sp.x, sp.y, 'run', true)
        if ok and stat(dry, 'build_designated') >= 1 and stat(dry, 'invalid_keys') == 0 then
            local out = {ok = true, zone_id = zone_id, what = f.what, x = sp.x, y = sp.y, elevation = ez(area.z),
                         dry_run = dry_run or nil}
            if dry_run then return out end
            local ok2, real = pcall(quickfort_apply, 'build', cell, area.z, sp.x, sp.y)
            if ok2 and stat(real, 'build_designated') >= 1 then return out end
        end
    end
    return {ok = false, rejected = true, error = ('quickfort refused %s at every spot tried in zone %d'):format(f.what, zone_id)}
end

-- (0.104.77) The building kind standing on a tile, or nil (swapped by the tests).
function building_kind_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, x, y, z)
    if not ok or not b then return nil end
    return df.building_type[b:getType()]
end

-- (0.104.77) A tavern built before 0.104.76 seats no one beside anyone (a
-- chair on the inner side of each table, two tiles from the next): a chair
-- is put beside each lone chair, on free floor in the zone, beside a table
-- where there is one, never in front of a door; at most `max` a call.
function pair_chairs(zone_id, dry_run, max)
    OFFSET = elevation_offset()
    max = max or 5
    local area = zone_area(zone_id)
    if not area then return {ok = false, rejected = true, error = 'no zone ' .. tostring(zone_id)} end
    local z = area.z
    local chairs, tables = {}, {}
    local function key(x, y) return x .. ',' .. y end
    for y = area.y1, area.y2 do
        for x = area.x1, area.x2 do
            if area.has(x, y) then
                local k = building_kind_at(x, y, z)
                if k == 'Chair' then chairs[key(x, y)] = {x = x, y = y}
                elseif k == 'Table' then tables[key(x, y)] = true end
            end
        end
    end
    local function beside(set, x, y)
        for _, d in ipairs(ORTHO) do if set[key(x + d[1], y + d[2])] then return true end end
        return false
    end
    local lone = {}
    for _, c in pairs(chairs) do if not beside(chairs, c.x, c.y) then table.insert(lone, c) end end
    table.sort(lone, function(a, b) if a.y ~= b.y then return a.y < b.y end return a.x < b.x end)
    local placed, spots = 0, {}
    for _, c in ipairs(lone) do
        if placed >= max then break end
        if not beside(chairs, c.x, c.y) then
            local best
            for _, d in ipairs(ORTHO) do
                local x, y = c.x + d[1], c.y + d[2]
                local t = area.has(x, y) and tile_info(x, y, z)
                if t and t.shape == 'FLOOR' and not t.building and not t.liquid and not t.items then
                    local door = false
                    for _, e in ipairs(ORTHO) do door = door or door_at(x + e[1], y + e[2], z) end
                    if not door then
                        local by_table = beside(tables, x, y)
                        if not best or (by_table and not best.by_table) then best = {x = x, y = y, by_table = by_table} end
                    end
                end
            end
            if best then
                local cell = {{x = 0, y = 0, text = 'c'}}
                local ok, dry = pcall(quickfort_apply, 'build', cell, z, best.x, best.y, 'run', true)
                if ok and stat(dry, 'build_designated') >= 1 and stat(dry, 'invalid_keys') == 0 then
                    local done = dry_run
                    if not dry_run then
                        local ok2, real = pcall(quickfort_apply, 'build', cell, z, best.x, best.y)
                        done = ok2 and stat(real, 'build_designated') >= 1
                    end
                    if done then
                        chairs[key(best.x, best.y)] = {x = best.x, y = best.y}
                        placed = placed + 1
                        table.insert(spots, {best.x, best.y})
                    end
                end
            end
        end
    end
    local n_chairs = 0
    for _ in pairs(chairs) do n_chairs = n_chairs + 1 end
    if n_chairs == 0 then return {ok = false, rejected = true, chairs = 0, error = 'no chairs in zone ' .. zone_id} end
    if #lone == 0 then return {ok = false, rejected = true, chairs = n_chairs, error = 'every chair in zone ' .. zone_id .. ' has one beside it'} end
    if placed == 0 then return {ok = false, rejected = true, error = 'no free floor beside the lone chairs in zone ' .. zone_id} end
    return {ok = true, zone_id = zone_id, lone = #lone, placed = placed, spots = spots, dry_run = dry_run or nil}
end

---------------------------------------------------------------------------
-- (0.103.16) Memorial slabs put up: DFHack's autoslab engraves a slab for
-- each ghost but doesn't build it, and a ghost rests only once its slab
-- stands (Enxah: 3 ghosts for days, 5 slabs in store). Each engraved slab no
-- building holds is built on a free floor beside a wall in a tomb zone, then
-- a meeting or dining hall, with that very slab (constructBuilding's items).
SLAB_ZONES = {'ZONE_TOMB', 'ZONE_MEETING_HALL', 'ZONE_DINING_HALL'}

function memorial_slabs()
    local out = {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.SLAB) do
            local f = it.flags
            if not (f.in_building or f.in_job or f.construction or f.removed or f.forbid or f.garbage_collect)
                    and it.engraving_type == df.slab_engraving_type.Memorial then
                table.insert(out, it)
            end
        end
    end)
    return out
end

function place_slabs(max, dry_run)
    OFFSET = elevation_offset()
    local slabs = memorial_slabs()
    if #slabs == 0 then return {ok = false, rejected = true, error = 'no engraved memorial slab waits to be put up'} end
    local n = math.min(#slabs, max or 5)
    if dry_run then return {ok = true, dry_run = true, slabs = n, waiting = #slabs} end
    local spots = {}
    for _, list in ipairs(SLAB_ZONES) do
        local okl, zs = pcall(function() return df.global.world.buildings.other[list] end)
        for _, z in ipairs(okl and zs or {}) do
            local area = zone_area(z.id)
            if area then
                for _, sp in ipairs(zone_spots(area)) do table.insert(spots, {x = sp.x, y = sp.y, z = area.z}) end
            end
        end
    end
    if #spots == 0 then return {ok = false, rejected = true, error = 'no free floor beside a wall in a tomb, meeting or dining hall'} end
    local placed, si, last = {}, 1, nil
    for i = 1, n do
        local it = slabs[i]
        while si <= #spots do
            local sp = spots[si]
            si = si + 1
            local ok, b, err = pcall(dfhack.buildings.constructBuilding,
                                     {type = df.building_type.Slab, pos = xyz2pos(sp.x, sp.y, sp.z), items = {it}})
            if ok and b then
                table.insert(placed, {x = sp.x, y = sp.y, elevation = ez(sp.z)})
                break
            end
            last = ok and tostring(err) or tostring(b)
        end
    end
    if #placed == 0 then return {ok = false, error = 'the game took none of the slabs: ' .. tostring(last):sub(1, 120)} end
    return {ok = true, placed = placed, waiting = #slabs - #placed}
end

---------------------------------------------------------------------------
-- (0.102.5) A temple or tavern laid over the fort's dining hall at once, no
-- digging: a young fort's dwarves broke down for want of somewhere to pray
-- and make merry while every building slot went to food and farms (Enxah,
-- y53: 6 miserable, 7 of 8 missing prayer). Players stack the first shrine
-- and tavern on the dining room the same way; a proper hall comes later.
QUICK_LOCATIONS = {temple = 'location=temple', tavern = 'location=tavern'}

function quick_location(kind, dry_run)
    local loc = QUICK_LOCATIONS[kind]
    if not loc then return {ok = false, rejected = true, error = 'quick_location makes a temple or tavern'} end
    local best, best_a
    for _, z in ipairs(df.global.world.buildings.other.ZONE_DINING_HALL) do
        local a = (z.x2 - z.x1 + 1) * (z.y2 - z.y1 + 1)
        if not best or a > best_a then best, best_a = z, a end
    end
    if not best then return {ok = false, rejected = true, error = 'no dining hall to put it in'} end
    local w, h = best.x2 - best.x1 + 1, best.y2 - best.y1 + 1
    local cell = {{x = 0, y = 0, text = ('m{%s}(%dx%d)'):format(loc, w, h)}}
    local ok, dry = pcall(quickfort_apply, 'zone', cell, best.z, best.x1, best.y1, 'run', true)
    if not (ok and stat(dry, 'zone_designated') >= 1 and stat(dry, 'invalid_keys') == 0) then
        return {ok = false, rejected = true, error = 'quickfort refused the zone over the dining hall: ' .. tostring(ok and 'no tiles' or dry)}
    end
    local out = {ok = true, kind = kind, x = best.x1, y = best.y1, elevation = ez(best.z), w = w, h = h, dry_run = dry_run or nil}
    if dry_run then return out end
    local ok2, real = pcall(quickfort_apply, 'zone', cell, best.z, best.x1, best.y1)
    if not (ok2 and stat(real, 'zone_designated') >= 1) then
        return {ok = false, error = 'quickfort did not make the zone: ' .. tostring(ok2 and 'no tiles' or real)}
    end
    return out
end
