-- ai-builder-surface: above ground: surface spots and clearing, river crossings, the keep,
-- the underground trade depot.
-- (r8) The keep, the underground depot, its road and the garbage dump are the parts
-- loaded after it: ai-builder-keep, -deepdepot, -wagonroad, -dump.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-surface'] = '0.105.106'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, ez = info, ez

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
-- them as trees = {{x, y, z}, ...}. (13c) Out of time with nothing found:
-- nil, 'search cut short: ...', true.
-- (0.105.27 fixes) `empty`: no tile with an item on it (a garbage dump's spot).
function find_surface_rect(w, h, min_d, reserved, shapes, max_trees, empty)
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
                    and not (empty and t.items) and not inside_any(reserved or {}, x, y, z) and not tile_taken(x, y, z) then
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
    local best, best_d, cut
    local deadline = os.clock() + PASTURE_SEARCH_SECONDS
    for _, a in ipairs(anchors) do
        for z = a.z - 1, a.z + 1 do
            for y = a.y - SURFACE_RADIUS, a.y + SURFACE_RADIUS do
                if os.clock() > deadline then cut = true break end
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
                            -- (0.105.30) a level either side too: a stair's way in
                            -- is the inside tile, one level under the open ground
                            -- (F and C: the refuse pile went 4 tiles from it)
                            for _, b in ipairs(anchors) do
                                if math.abs(b.z - z) <= 1 and x - min_d < b.x and b.x < x + w + min_d
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
    return nil, (cut and 'search cut short: ' or '') .. ('no %dx%d patch of flat ground near the surface entrances%s'):format(w, h,
        max_trees > 0 and (' (with %d trees or fewer to fell)'):format(max_trees) or ''), cut
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
        d.dig = df.tile_dig_designation.Default   -- dig guard: a plant, not rock (0.105.40b)
        local block = dfhack.maps.getTileBlock(x, y, z)
        if block then block.flags.designated = true end
    end
    return ok or (d ~= nil and d.dig ~= df.tile_dig_designation.No)
end

-- Something placed outside: a refuse stockpile ('refuse') or a trade depot
-- ('depot'). Placed through Quickfort like everything else; the depot waits
-- for its materials (buildingplan).
GROUND = {FLOOR = true, BOULDER = true, PEBBLES = true, TWIG = true, SAPLING = true, SHRUB = true}
local SURFACE_THINGS = {
    refuse = {w = 5, h = 5, min_d = 6, mode = 'place', text = 'r(5x5)', what = 'a refuse pile', shapes = GROUND},
    depot = {w = 5, h = 5, min_d = 4, mode = 'build', text = 'D', what = 'a trade depot', shapes = GROUND},
    -- a garbage dump zone: things marked for dumping are taken there (the AI
    -- marks worn-out clothes lying about when the game runs slowly)
    -- (0.105.27 fixes) on tiles with no item on them (empty): what lies in a
    -- dump zone may be removed by DFHack's empty_dump
    dump = {w = 3, h = 3, min_d = 8, mode = 'zone', text = 'd(3x3)', what = 'a garbage dump', shapes = GROUND,
            empty = true},
    -- an animal stockpile: full cages from the cage traps go there, so the
    -- traps are loaded with empty cages again (prisoners stay in their cages)
    cages = {w = 3, h = 3, min_d = 6, mode = 'place', text = 'a(3x3)', what = 'a stockpile for full cages',
             shapes = GROUND},
}
CLEARING_KEY = 'ai-overseer/clearing'

-- Spots being cleared for something outside: kind -> {x, y, z, w, h}.
function clearing_spots()
    return site_get(CLEARING_KEY)
end

local function save_clearing(d)
    site_put(CLEARING_KEY, d)
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
    local spot, why, cut
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
        spot, why, cut = find_surface_rect(k.w, k.h, k.min_d, reserved, k.shapes, SURFACE_MAX_TREES, k.empty)
    end
    -- (0.105.27 fixes) a spot that must be empty (the dump), cleared of trees:
    -- the logs and whatever else lies there hauled away first
    if spot and k.empty and #spot.trees == 0 then
        local n = 0
        for y = spot.y, spot.y + k.h - 1 do
            for x = spot.x, spot.x + k.w - 1 do
                local t = tile_info(x, y, spot.z)
                if t and t.items then n = n + 1 end
            end
        end
        if n > 0 then
            if not dry_run and type(c) == 'table' then
                clearing[kind] = c
                save_clearing(clearing)
            end
            return {ok = false, rejected = true, waiting = true, kind = kind,
                    error = ('items still lie on %d tile(s) of the spot for %s at x%d y%d: they are hauled away first')
                        :format(n, k.what, spot.x, spot.y)}
        end
    end
    if not spot then return {ok = false, error = why, timed_out = cut or nil} end
    if #spot.trees > 0 then
        local out = {ok = true, kind = kind, clearing = true, trees = #spot.trees, x = spot.x, y = spot.y, z = spot.z,
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
    local good, failed = qf_try(k.mode, {{x = 0, y = 0, text = k.text}}, spot.z, ax, ay, dry_run)
    if failed == 'dry' then
        return {ok = false, error = ('the game would not place %s at x%d y%d'):format(k.what, spot.x, spot.y)}
    elseif not good then
        return {ok = false, error = ('the game refused %s at x%d y%d'):format(k.what, spot.x, spot.y)}
    end
    return {ok = true, kind = kind, x = spot.x, y = spot.y, z = spot.z, elevation = ez(spot.z), dry_run = dry_run or nil}
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
    local d = site_get(CROSS_KEY)
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
        -- (0.105.33) somebody else's bridge there is not the AI's one standing
        if bld and bld:getType() == df.building_type.Bridge and not crossing_is_mine(b, bld) then bld = nil end
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
    local good, failed = qf_try('build', {{x = 0, y = 0, text = text}}, z, x1, y1, dry_run, 1, true)
    if failed == 'dry' then
        return {ok = false, error = ('the game would not place a bridge at x%d y%d (%dx%d)'):format(x1, y1, w, h)}
    elseif not good then
        return {ok = false, error = ('the game refused the bridge at x%d y%d'):format(x1, y1)}
    end
    local out = {ok = true, x = x1, y = y1, elevation = ez(z), w = w, h = h, kind = kind, dry_run = dry_run or nil}
    if dry_run then return out end
    local data = crossings_data()
    -- (0.105.33) the bridge's building id, so only this one is ever taken down
    local okb, id = pcall(function()
        local bld = dfhack.buildings.findAtTile(xyz2pos(x1, y1, z))
        return bld and bld:getType() == df.building_type.Bridge and bld.id or nil
    end)
    id = okb and id or nil
    table.insert(data.list, {x = x1, y = y1, z = z, w = w, h = h, len = len, width = width, dir = dir,
                             kind = kind or 'cheap', tick = now, id = id})
    site_put(CROSS_KEY, data)
    return out
end

-- (0.105.33) Is this bridge building the one the record `b` is of?
function crossing_is_mine(b, bld)
    if b.id ~= nil then return bld.id == b.id end
    local w, h = b.w or 1, b.h or 1
    return bld.x1 == b.x and bld.y1 == b.y and bld.x2 == b.x + w - 1 and bld.y2 == b.y + h - 1 and bld.z == b.z
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
    -- (0.105.33) a bridge there that isn't the AI's (its id, or for a record
    -- without one its exact rectangle): the player's, left standing; the
    -- AI's record of a bridge gone is dropped
    if bld and not crossing_is_mine(b, bld) then bld = nil end
    if dry_run then return {ok = true, dry_run = true, index = index} end
    if bld then dfhack.buildings.deconstruct(bld) end
    table.remove(data.list, index)
    site_put(CROSS_KEY, data)
    return {ok = true, index = index, removed = bld ~= nil}
end
