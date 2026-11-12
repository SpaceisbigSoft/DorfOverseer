-- ai-builder-surface: above ground: surface spots and clearing, river crossings, the keep,
-- the underground trade depot.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-surface'] = '0.105.38'   -- (0.105.26) bumped with BRIDGE_VERSION

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
        d.dig = df.tile_dig_designation.Default
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

-- --- the keep: building above ground (the Surface ambition) ----------------------
--
-- A walled court around the fort's way in from the surface: a square ring of
-- constructed walls (radius 4-6 tiles from the entrance) with one door, then
-- a roof of constructed floor over the inside. Natural rock in the ring
-- counts as wall already; trees in the ring are felled first. Never put
-- around a trade depot (the wagons couldn't reach it), never over water,
-- buildings, zones or slopes. Built in stages, one action each:
--   clearing -> walls (+ door) -> stair (0.105.30, ROOF_STAIR) -> roof -> done
-- The state lives in the save (site data 'ai-overseer/keep').
KEEP_KEY = 'ai-overseer/keep'
KEEP_RADII = {4, 5, 6}
-- (0.105.30, construction 3.0.2) A stair up from the inside to the roof:
-- whether the game builds a roof over an enclosed court from below is
-- [verify]; set false once it is seen to. The keep (stage 'stair') and the
-- surface hall use it.
ROOF_STAIR = true

-- The inside corner for the roof stair (x1..x2, y1..y2: the inside at z),
-- the one farthest from `away` (the door): open flat ground with nothing on
-- it and the open sky above. {x, y, z} or nil (ROOF_STAIR off, no corner).
function roof_access(x1, y1, x2, y2, z, away)
    if not ROOF_STAIR then return nil end
    local corners = {{x = x1, y = y1}, {x = x2, y = y1}, {x = x1, y = y2}, {x = x2, y = y2}}
    local function far(c)
        if not away then return 0 end
        return math.abs(c.x - away.x) + math.abs(c.y - away.y)
    end
    table.sort(corners, function(a, b)
        local fa, fb = far(a), far(b)
        if fa ~= fb then return fa > fb end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    for _, c in ipairs(corners) do
        local t, up = tile_info(c.x, c.y, z), tile_info(c.x, c.y, z + 1)
        if t and up and t.shape == 'FLOOR' and not t.building and not t.liquid and not t.designated
                and up.shape == 'EMPTY' and not up.building then
            return {x = c.x, y = c.y, z = z}
        end
    end
    return nil
end

function keep_data()
    local d = site_get(KEEP_KEY)
    return d.x and d or nil
end

local function save_keep(d)
    site_put(KEEP_KEY, d or {})
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
function keep_tile(x, y, z)
    local t = tile_info(x, y, z)
    if not t or t.liquid or t.feature then return nil end
    if is_tree(t) then return 'tree' end
    if t.shape == 'WALL' then return 'wall' end
    if t.building then return 'planned' end
    if t.hidden or not t.outside or t.designated or tile_taken(x, y, z) then return nil end
    if GROUND[t.shape] then return 'ground' end
    return nil
end

-- (0.105.33) A 'planned' ring tile that is a wall waiting to be built: a
-- Construction there (any other building, a trap, a statue, the player's
-- door, is a gap: counted as such it kept the keep "going up" forever).
-- When the building can't be read it is taken as a wall waiting (as before).
-- Tests swap it.
function keep_wall_waits(x, y, z)
    local ok, other = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        return b ~= nil and b:getType() ~= df.building_type.Construction
    end)
    return not (ok and other)
end

-- (0.105.30) Why keep_tile gives nil there, in words (the refusal names the
-- tile: F and C were refused 133 and 138 times with no tile named).
function keep_tile_why(x, y, z)
    local t = tile_info(x, y, z)
    if not t then return 'the map\'s edge' end
    if t.liquid then return 'water' end
    if t.feature then return 'a cavern' end
    if t.hidden then return 'unseen ground' end
    if not t.outside then return 'the fort\'s own rock or rooms (under a roof)' end
    if t.designated then return 'a tile designated for digging' end
    if tile_taken(x, y, z) then return 'a stockpile, zone or building' end
    return ('a %s tile'):format(tostring(t.shape):lower())
end

-- (0.105.30) The ways in, each on the level of the open ground. The gates
-- give a way in as its inside tile: for a stair up to the surface (the
-- founding stair under its hatch) that is the stair one level under the
-- ground, so every keep ring was looked for in the rock (F and C's 271
-- refusals, "no ring of open ground around the way in"). A stair that goes
-- on up to an outside tile is followed up (at most 2 levels).
function surface_anchors(anchors)
    local out = {}
    for _, a in ipairs(anchors or pasture_anchors()) do
        local z = a.z
        local t = tile_info(a.x, a.y, a.z)
        if t and not t.outside and stair_shape(a.x, a.y, a.z) then
            for zz = a.z + 1, a.z + 2 do
                local sh = stair_shape(a.x, a.y, zz)
                if not (sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN') then break end
                local up = tile_info(a.x, a.y, zz)
                if up and up.outside then z = zz break end
            end
        end
        table.insert(out, {x = a.x, y = a.y, z = z, below = z ~= a.z and a.z or nil})
    end
    return out
end

function depot_inside(x1, y1, x2, y2, z)
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

-- (0.105.23, 14.1 step 4c) The keep away from the way in: fort F (Garden
-- fort, Surface +80) asked 39 times and was refused every time ("no ring of
-- open ground around the way in"): its founding stair sits on a mountain
-- slope, so every ring round it ran into rock, ramps and the hillside. When
-- no way in has a ring, the keep goes on the flattest open ground near the
-- fort: a square court whose inside is all open, flat ground under the open
-- sky (on one level, nothing above it), within KEEP_COURT_REACH tiles of a
-- way in and up to KEEP_COURT_LEVELS levels below it (or within
-- KEEP_COURT_FARM_REACH of a surface field), the dwarves able to walk to it;
-- nearest the surface farm plots when there are any (a walled
-- garden court by the fields), else nearest the way in. Never over the
-- plots themselves (a building or zone inside rules a spot out), never round
-- the way in (that was the first try) nor within KEEP_COURT_CLEAR of it (the
-- caravans' road), never round the trade depot. A court away from the way
-- in can go up with the depot underground (the wagons pass it by).
KEEP_COURT_REACH = 30
KEEP_COURT_LEVELS = 4
KEEP_COURT_RADII = {4, 5}
KEEP_COURT_SECONDS = 1.5
KEEP_COURT_CANDIDATES = 400  -- centres checked in full, best first
KEEP_COURT_FARMS = 6         -- fields looked round (the first ones DF lists)
KEEP_COURT_FARM_REACH = 12   -- tiles round a field
KEEP_COURT_CLEAR = 3         -- open tiles kept between the court's walls and a way in (the wagons' road)

-- The centres of the farm plots under the sky: {{x, y, z}, ...}.
function surface_farm_spots()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.FARM_PLOT) do
            local cx, cy = (b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2
            local t = tile_info(cx, cy, b.z)
            if t and t.outside then table.insert(out, {x = cx, y = cy, z = b.z}) end
        end
    end)
    return out
end

-- A court site on open ground near the fort: {x, y, z, r, door, trees, court = true}, or nil and why.
function find_keep_court(anchors)
    local groups = citizen_groups()
    local any_group = next(groups) == nil
    local farms = surface_farm_spots()
    local okm, mouth = pcall(deep_depot_mouth)       -- (0.105.30)
    mouth = okm and mouth or nil
    local cache = {}
    local function kt(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = keep_tile(x, y, z) or false; cache[k] = v end
        return v
    end
    local function reach(x, y, z)
        local g = walk_group(x, y, z)
        return g ~= 0 and (any_group or groups[g] == true)
    end
    local function open_above(x, y, z)
        local t = tile_info(x, y, z + 1)
        return t ~= nil and t.shape == 'EMPTY'
    end
    -- the centres worth a full look: open, reachable ground under the open
    -- sky, scored by the walk from the fields (or the way in)
    -- (round the ways in, and round the first few fields: a field may lie
    -- further out than the reach)
    local areas = {}
    for _, a in ipairs(anchors) do
        table.insert(areas, {x = a.x, y = a.y, z1 = a.z - KEEP_COURT_LEVELS, z2 = a.z + 1, reach = KEEP_COURT_REACH})
    end
    for i, f in ipairs(farms) do
        if i > KEEP_COURT_FARMS then break end
        table.insert(areas, {x = f.x, y = f.y, z1 = f.z - 1, z2 = f.z + 1, reach = KEEP_COURT_FARM_REACH})
    end
    local cands, seen = {}, {}
    local deadline = os.clock() + KEEP_COURT_SECONDS
    local cut = false
    for _, ar in ipairs(areas) do
        for z = ar.z1, ar.z2 do
            for y = ar.y - ar.reach, ar.y + ar.reach do
                if os.clock() > deadline then cut = true break end
                for x = ar.x - ar.reach, ar.x + ar.reach do
                    local k = (z * 4096 + y) * 4096 + x
                    if not seen[k] and kt(x, y, z) == 'ground' and open_above(x, y, z) and reach(x, y, z) then
                        seen[k] = true
                        local score = math.huge
                        for _, a in ipairs(anchors) do
                            local ad = math.max(math.abs(x - a.x), math.abs(y - a.y)) + 3 * math.abs(z - a.z)
                            if ad < score then score = ad end
                        end
                        for _, f in ipairs(farms) do
                            local fd = math.max(math.abs(x - f.x), math.abs(y - f.y)) + 3 * math.abs(z - f.z)
                            if fd < score then score = fd end
                        end
                        table.insert(cands, {x = x, y = y, z = z, score = score})
                    end
                end
            end
            if cut then break end
        end
        if cut then break end
    end
    table.sort(cands, function(p, q)
        if p.score ~= q.score then return p.score < q.score end
        if p.z ~= q.z then return p.z > q.z end
        if p.y ~= q.y then return p.y < q.y end
        return p.x < q.x
    end)
    local last = 'no open, flat ground the dwarves can reach within ' .. KEEP_COURT_REACH .. ' tiles of the way in'
    local best, best_score
    for i, c in ipairs(cands) do
        if i > KEEP_COURT_CANDIDATES or os.clock() > deadline + KEEP_COURT_SECONDS then break end
        if best_score and c.score >= best_score then break end
        for _, r in ipairs(KEEP_COURT_RADII) do
            local fits = true
            -- the inside: open flat ground, the sky open above, the way in not in it
            for y = c.y - r + 1, c.y + r - 1 do
                for x = c.x - r + 1, c.x + r - 1 do
                    if kt(x, y, c.z) ~= 'ground' or not open_above(x, y, c.z) then fits = false break end
                end
                if not fits then break end
            end
            if fits then
                for _, a in ipairs(anchors) do
                    local clear = r + KEEP_COURT_CLEAR
                    if math.abs(a.z - c.z) <= 1 and math.abs(a.x - c.x) <= clear and math.abs(a.y - c.y) <= clear then
                        fits = false
                    end
                end
            end
            local trees, ground = {}, 0
            if fits then
                for _, p in ipairs(ring_tiles(c.x, c.y, r)) do
                    local k = kt(p.x, p.y, c.z)
                    if not k or k == 'planned' then fits = false break end
                    if k == 'tree' then table.insert(trees, {x = p.x, y = p.y, z = c.z}) end
                    if k == 'ground' then ground = ground + 1 end
                end
            end
            if fits and (#trees > SURFACE_MAX_TREES or ground == 0) then fits = false end
            if fits and depot_inside(c.x - r, c.y - r, c.x + r, c.y + r, c.z) then
                fits, last = false, 'the open ground near the fort holds the trade depot'
            end
            if fits and mouth then
                -- (0.105.30) no wall in front of the underground depot's road (the wagons turn in there)
                for _, m in ipairs(mouth) do
                    if math.abs(m.z - c.z) <= 1 and math.abs(m.x - c.x) <= r + 1 and math.abs(m.y - c.y) <= r + 1 then
                        fits, last = false, 'the open ground near the fort is the underground depot\'s wagon road'
                        break
                    end
                end
            end
            local door = fits and keep_door(c.x, c.y, c.z, r)
            if door then
                local d = {x = door.x - c.x, y = door.y - c.y}
                local ox, oy = door.x + (d.x > 0 and 1 or d.x < 0 and -1 or 0), door.y + (d.y > 0 and 1 or d.y < 0 and -1 or 0)
                if not reach(ox, oy, c.z) then door = nil end
            end
            if fits and door then
                local score = c.score + SURFACE_TREE_COST * #trees
                if not best_score or score < best_score then
                    best, best_score = {x = c.x, y = c.y, z = c.z, r = r, door = door, trees = trees, court = true}, score
                end
                break
            end
        end
    end
    if best then return best end
    return nil, last
end

-- A site for the keep around the surface entrance: {x, y, z, r, door, trees}.
-- (0.105.23) Every way in first; with no ring round any, a court on open
-- ground near the fields (find_keep_court).
function find_keep_site()
    local anchors = surface_anchors()          -- (0.105.30) on the open ground's level
    if #anchors == 0 then return nil, 'no surface entrance or staircase to build the keep around' end
    local site, last = find_keep_ring(anchors)
    if site then return site end
    local okc, court, why = pcall(find_keep_court, anchors)
    if okc and court then return court end
    return nil, ('%s; %s'):format(last, okc and why or ('the search for open ground failed: ' .. tostring(court)))
end

-- A ring round one of the ways in, or nil and why.
function find_keep_ring(anchors)
    local under = depot_underground()
    if under then return nil, under end
    local last, first_bad
    for _, a in ipairs(anchors) do
        for _, r in ipairs(KEEP_RADII) do
            local fits, trees, ground = true, {}, 0
            for _, p in ipairs(ring_tiles(a.x, a.y, r)) do
                local k = keep_tile(p.x, p.y, a.z)
                if not k or k == 'planned' then
                    -- (0.105.30) the first ring's first bad tile, named
                    first_bad = first_bad or ('r%d meets %s at x%d y%d, elevation %d'):format(r,
                        k and 'a wall waiting to be built' or keep_tile_why(p.x, p.y, a.z), p.x, p.y, ez(a.z))
                    fits = false
                    break
                end
                if k == 'tree' then table.insert(trees, {x = p.x, y = p.y, z = a.z}) end
                if k == 'ground' then ground = ground + 1 end
            end
            if fits and #trees > SURFACE_MAX_TREES then
                fits, last = false, ('too many trees around the way in (%d to fell)'):format(#trees)
            end
            if fits and ground == 0 and #trees == 0 then
                fits = false
                first_bad = first_bad or ('r%d is all rock'):format(r)
            end
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
    return nil, last or ('no ring of open ground around the way in (%s)'):format(
        first_bad or 'water, slopes, buildings or zones in the way')
end

-- How far it's got: {stage, x, y, z, r, walls_left, roof_left, trees_left}.
function keep_status()
    local k = keep_data()
    if not k then return nil end
    local out = {stage = k.stage, x = k.x, y = k.y, z = k.z, r = k.r, walls_left = 0, walls_planned = 0,
                 roof_left = 0, roof_planned = 0, trees_left = 0, court = k.court}
    for _, p in ipairs(ring_tiles(k.x, k.y, k.r)) do
        local t = keep_tile(p.x, p.y, k.z)
        if t == 'tree' then out.trees_left = out.trees_left + 1 end
        local is_door = k.door and p.x == k.door.x and p.y == k.door.y
        if not is_door and t ~= 'wall' then out.walls_left = out.walls_left + 1 end
        if not is_door and t == 'planned' and keep_wall_waits(p.x, p.y, k.z) then
            out.walls_planned = out.walls_planned + 1
        end
    end
    -- (0.105.30) the roof stair: its lower half waiting counts as roof to build
    if k.stage == 'stair' and k.stair then
        local t = tile_info(k.stair.x, k.stair.y, k.z)
        if t and t.building and t.shape ~= 'STAIR_UP' then
            out.stair_planned, out.roof_planned = 1, 1
        end
    end
    out.stair = k.stair
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
    -- (0.105.33) the blocks still to go into it, for the brain's stone-blocks
    -- order (it read keep.blocks_needed, which was never written): the walls
    -- not built yet (planned ones wait for blocks too), the roof (its whole
    -- inside before the roof stage) and the roof stair's two halves
    if k.stage == 'done' then
        out.blocks_needed = 0
    else
        local inner = math.max(0, 2 * k.r - 1)
        local roof = (k.stage == 'roof') and out.roof_left or inner * inner
        local stair = 0
        if ROOF_STAIR and k.stage ~= 'roof' then stair = (k.stage == 'stair') and 1 or 2 end
        out.blocks_needed = out.walls_left + roof + stair
    end
    out.elevation = ez(k.z)
    return out
end

local function keep_apply(cells, z, what, dry_run)
    local good, failed, res = qf_try('build', cells, z, 0, 0, dry_run)
    if failed == 'dry' then return nil, ('the game would not place %s'):format(what) end
    if not good then return nil, ('the game refused %s'):format(what) end
    return stat(res, 'build_designated')
end

-- (0.105.30) The roof at z+1 over the inside; over a built roof stair a
-- stair down (Cd), dropped if the game won't take it.
local function keep_roof(k, dry_run)
    local cells, stair_cell = {}, nil
    local built = k.stair and stair_shape(k.stair.x, k.stair.y, k.z) == 'STAIR_UP'
    for y = k.y - k.r + 1, k.y + k.r - 1 do
        for x = k.x - k.r + 1, k.x + k.r - 1 do
            local t = tile_info(x, y, k.z + 1)
            if t and t.shape == 'EMPTY' and not t.building then
                local is_stair = built and x == k.stair.x and y == k.stair.y
                table.insert(cells, {x = x, y = y, text = is_stair and 'Cd' or 'Cf'})
                if is_stair then stair_cell = cells[#cells] end
            end
        end
    end
    if #cells == 0 then
        if not dry_run then k.stage = 'done'; save_keep(k) end
        return {ok = true, stage = 'done', x = k.x, y = k.y, dry_run = dry_run or nil}
    end
    local n, why = keep_apply(cells, k.z + 1, 'the keep\'s roof', dry_run)
    if not n and stair_cell then                -- (a stair down the game won't take: a floor there)
        stair_cell.text = 'Cf'
        n, why = keep_apply(cells, k.z + 1, 'the keep\'s roof', dry_run)
        stair_cell = nil
    end
    if not n then return {ok = false, error = why} end
    if not dry_run then k.stage = 'roof'; save_keep(k) end
    return {ok = true, stage = 'roof', roof = n, stair = stair_cell and true or nil, x = k.x, y = k.y, r = k.r,
            elevation = ez(k.z + 1), dry_run = dry_run or nil}
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
        k = {x = site.x, y = site.y, z = site.z, r = site.r, door = site.door, stage = 'clearing',
             court = site.court or nil}
        if #site.trees > 0 then
            local out = {ok = true, stage = 'clearing', clearing = true, trees = #site.trees, x = k.x, y = k.y,
                         r = k.r, elevation = ez(k.z), court = k.court, dry_run = dry_run or nil}
            if dry_run then return out end
            for _, t in ipairs(site.trees) do fell_tree(t.x, t.y, t.z) end
            save_keep(k)
            return out
        end
    end
    local st = {}
    if k.stage == 'clearing' then
        -- (0.104.0) a depot dug underground since the site was chosen
        -- ((0.105.23) a court away from the way in doesn't stand in the wagons' way)
        local under = not k.court and depot_underground()
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
                     elevation = ez(k.z), court = k.court, dry_run = dry_run or nil}
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
        -- (0.105.30, construction 3.0.2) a stair up in an inside corner first,
        -- so the roof can be reached ([verify] in game; ROOF_STAIR = false
        -- once the game is seen building the roof from below). Refused: the
        -- roof goes on without it.
        local s = roof_access(k.x - k.r + 1, k.y - k.r + 1, k.x + k.r - 1, k.y + k.r - 1, k.z, k.door)
        if s then
            local good, failed = qf_try('build', {{x = s.x, y = s.y, text = 'Cu'}}, k.z, 0, 0, dry_run)
            if good then
                if not dry_run then k.stage = 'stair'; k.stair = {x = s.x, y = s.y}; save_keep(k) end
                return {ok = true, stage = 'stair', stair = {x = s.x, y = s.y}, x = k.x, y = k.y, r = k.r,
                        elevation = ez(k.z), dry_run = dry_run or nil}
            end
        end
        return keep_roof(k, dry_run)
    end
    if k.stage == 'stair' then
        st = keep_status() or {}
        if (st.stair_planned or 0) > 0 then
            return {ok = false, rejected = true, waiting = true, stage = 'stair', roof_left = st.roof_planned,
                    error = 'the keep\'s stair to the roof is being built'}
        end
        return keep_roof(k, dry_run)
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

-- --- the underground trade depot (the Deep mine) ----------------------------------
--
-- (0.105.23, 14.1 step 4c) Surface -80 or lower builds nothing above ground,
-- and the player's correction: a trade depot can be underground in Dwarf
-- Fortress when the wagons' way to it is right. The game's rules (the wiki's
-- "Trade depot" and "Wagon"): a wagon is 3x3, so its whole way from the map's
-- edge is 3 tiles wide; it can't use stairs, only ramps, and a ramp way is 3
-- wide too with the tile over each ramp open; trees, boulders and most
-- buildings stop it; the game itself marks a depot "accessible" to wagons.
-- So: a straight road, 3 wide, from open ground near the fort's way in, down
-- DEEP_DEPOT_LEVELS levels at most, one channel per level (a channel turns
-- the rock under it into a ramp and leaves the ramp's top open), a flat tile
-- between ramps, then a hall (DEEP_HALL x DEEP_HALL) with the 5x5 depot in
-- its middle and 2 tiles round it for the wagon to stand and turn:
--
--   surface   ..A A S             A approach (open ground, wagons come in)
--   level -1        R f S         S channel (ramp below, open above)
--   level -2            R f f H H H ... the hall       R ramp, f road floor
--
-- Every tile dug is untouched natural wall, safe (no aquifer, water,
-- cavern, warm stone), with solid rock round it, over it and under it (the
-- surface's own ground as the roof of the first level), within no level the
-- AI dug and next to no open space: the hall never opens into the fort (its
-- dwarves come by the surface, as to a depot outside; no new way into the
-- fort for the gates to guard). Hall and road stay under the gates' "ledge"
-- size (ai-gates LEDGE_MAX, 120 tiles): a hauler standing there at a scan
-- doesn't make the hall the fort. Built in stages, one action each:
--   (search) -> digging -> placed (the depot ordered) ; or no_road
-- The state lives in the save (site data 'ai-overseer/deep_depot').
DEEP_DEPOT_KEY = 'ai-overseer/deep_depot'
DEEP_DEPOT_LEVELS = 3        -- levels the road goes down at most
DEEP_DEPOT_REACH = 20        -- tiles from a way in to the road's start at most
DEEP_DEPOT_CLEAR = 3         -- tiles kept open round the way in (the dwarves' own door)
DEEP_DEPOT_SECONDS = 1.5     -- the search stops here (like KEEP_COURT_SECONDS)
DEEP_ROAD_MAX = 40           -- tiles of road dug (not the hall) at most
DEEP_ROAD_RUN = 2            -- flat road between the last ramp and the hall
DEEP_HALL = 9                -- the hall's side: the 5x5 depot and 2 tiles round it
DEEP_DEPOT_RETRY_TICKS = 403200   -- a search that found nothing is tried again after a year
DEEP_REDIG_MAX = 30          -- lost designations put back in one call
local DEEP_DIRS = {{0, -1}, {1, 0}, {0, 1}, {-1, 0}}
local DEEP_ROOF = {WALL = true, FLOOR = true, PEBBLES = true, BOULDER = true, TWIG = true, SAPLING = true,
                   SHRUB = true, RAMP = true}

function deep_depot_data()
    local d = site_get(DEEP_DEPOT_KEY)
    return d.stage and d or nil
end

local function save_deep_depot(d)
    site_put(DEEP_DEPOT_KEY, d or {})
end

local function deep_now()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and math.tointeger(t) or nil
end

-- The road and hall for a start (sx, sy) on the surface level z, heading d,
-- k levels down: {tiles = {{x, y, z, r}}, depot = {x, y, z}, hall = {x1, y1,
-- x2, y2, z}, road = n}. r: 'h' channel, 'd' dug floor, 'ramp' (the rock a
-- channel above turns into a ramp: not designated).
function deep_depot_layout(sx, sy, z, d, k)
    local dx, dy = d[1], d[2]
    local px, py = -dy, dx
    local function at(u, v) return sx + u * dx + v * px, sy + u * dy + v * py end
    local tiles, road = {}, 0
    local function row(u, zz, r, v1, v2)
        for v = v1 or -1, v2 or 1 do
            local x, y = at(u, v)
            table.insert(tiles, {x = x, y = y, z = zz, r = r})
        end
    end
    row(1, z, 'h')                                      -- the surface's channel
    for i = 1, k do
        local L, u = z - i, 1 + (i - 1) * 2
        row(u, L, 'ramp')
        if i < k then row(u + 1, L, 'd'); row(u + 2, L, 'h') end
    end
    local D, uk = z - k, 1 + (k - 1) * 2
    for u = uk + 1, uk + DEEP_ROAD_RUN do row(u, D, 'd') end
    road = #tiles
    local h0, half = uk + DEEP_ROAD_RUN + 1, DEEP_HALL // 2
    for u = h0, h0 + DEEP_HALL - 1 do row(u, D, 'd', -half, half) end
    local cx, cy = at(h0 + half, 0)
    local ax, ay = at(h0, -half)
    local bx, by = at(h0 + DEEP_HALL - 1, half)
    return {tiles = tiles, road = road, depot = {x = cx, y = cy, z = D}, levels = k,
            hall = {x1 = math.min(ax, bx), y1 = math.min(ay, by), x2 = math.max(ax, bx), y2 = math.max(ay, by), z = D}}
end

-- --- (0.105.30, deep depot) the wagons' way ---------------------------------------
--
-- Fort E (Deep mine) built its depot down a 1-level road; the game said the
-- wagons couldn't reach it, and a caravan came with pack animals only. The
-- search had checked the road's own 3x3 start and nothing between it and the
-- map's edge. The wagons' rule, as DFHack's own depot check models it
-- (plugins/pathable.cpp, getDepotAccessibleByWagons; the wiki's "Wagon"):
-- a wagon moves only straight (no diagonals) and every tile of the 3x3 round
-- its middle must be passable: no tree, boulder, stair, open space, minecart
-- track, murky pool or river floor, no door, trap, lever, statue or raised
-- bridge (a lowered bridge, a closed hatch or floor grate is fine; a hatch on
-- a ramp's top is not). It changes level by a ramp: standing on a ramp, the
-- rock beside it counts when the tile on top of that rock is walkable (the
-- wagon goes up there); the open top of a ramp counts when the ramp under it
-- is walkable (it goes down). And the 3-wide way must reach the map's edge.
DEEP_WAGON_NODES = 20000     -- wagon positions looked at, at most, between the road and the map's edge
DEEP_WAGON_SECONDS = 0.8     -- and that long at most
DEEP_WAGON_CHECK_TICKS = 1200    -- the report's check is kept this long (an in-game day)
DEEP_FIX_MAX = 9             -- blocking tiles a fix marks in one call

-- What stands on a tile, as a wagon sees it: nil (nothing), or {occ =
-- DF's tile_building_occ name (Passable, Floored, Dynamic, Obstacle...),
-- kind = building type name, closed, id, name}. Tests replace this.
function wagon_building(x, y, z)
    local ok, r = pcall(function()
        local _, occ = dfhack.maps.getTileFlags(x, y, z)
        if not occ or occ.building == df.tile_building_occ.None then return nil end
        local out = {occ = df.tile_building_occ[occ.building]}
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if b then
            out.kind, out.id, out.name = df.building_type[b:getType()], b.id, tostring(b.name or '')
            pcall(function() out.closed = b.door_flags.closed end)
            if out.closed == nil then pcall(function() out.closed = b.gate_flags.closed end) end
        end
        return out
    end)
    return ok and r or nil
end

-- DFHack's own wagon check of the depot, when this DFHack has it: true/false, or nil.
function dfhack_wagon_access()
    local ok, v = pcall(function()
        local p = require('plugins.pathable')
        return p.getDepotAccessibleByWagons(false)
    end)
    if ok and type(v) == 'boolean' then return v end
    return nil
end

local WAGON_STOP = {STAIR_UP = 'a staircase', STAIR_DOWN = 'a staircase', STAIR_UPDOWN = 'a staircase',
                    BOULDER = 'a boulder', EMPTY = 'open space', NONE = 'open space'}
local WAGON_BUILT = {Door = 'a door', Hatch = 'a hatch', Trap = 'a trap or lever', Statue = 'a statue',
                     Bridge = 'a raised bridge', Well = 'a well', Support = 'a support', Floodgate = 'a floodgate',
                     WindowGlass = 'a window', WindowGem = 'a window', GrateWall = 'a grate', BarsVertical = 'bars',
                     Weapon = 'a weapon trap'}

local function building_words(b)
    return WAGON_BUILT[b.kind or ''] or ('a building (%s)'):format(tostring(b.kind or b.occ):lower())
end

-- Why a wagon can't roll over this tile's ground, or nil (the tile check of
-- DFHack's is_wagon_tile_traversible, which lets walls through: they are
-- judged by the walking test after it).
local function wagon_ground(t)
    if t.shape == 'RAMP_TOP' then return nil end
    if WAGON_STOP[t.shape] then return WAGON_STOP[t.shape] end
    if t.track then return 'a minecart track' end
    if t.material == 'POOL' or t.material == 'RIVER' then return 'a pool or river bed' end
    return nil
end

-- What a blocking tile is, in words.
local function wall_words(t)
    if is_tree(t) or t.material == 'TREE' or t.material == 'ROOT' then return 'a tree' end
    if t.shape == 'WALL' then
        return t.material == 'CONSTRUCTION' and 'a built wall' or 'rock'
    end
    return ('%s the wagons can\'t reach'):format(tostring(t.shape):lower():gsub('_', ' '))
end

-- What a building on a tile does to a wagon: nil (passes), 'floored' (it
-- rolls over it: the depot, a lowered bridge), or what blocks it.
local function building_blocks(b, t)
    if not b then return nil end
    local occ = b.occ
    if occ == 'Obstacle' or occ == 'Well' or occ == 'Impassable' then return building_words(b) end
    if occ == 'Dynamic' then
        if b.kind == 'Hatch' then
            if t and t.shape == 'RAMP_TOP' then return 'a hatch over the ramp' end
            if not b.closed then return 'an open hatch' end
            return nil
        elseif (b.kind == 'GrateFloor' or b.kind == 'BarsFloor') and b.closed then
            return nil
        end
        return building_words(b)
    end
    if occ == 'Floored' then return 'floored' end
    return nil
end

-- One tile of a wagon's 3x3, as DFHack's is_wagon_traversible judges it.
-- true (and maybe a level change pushed), or false and what is there.
local function wagon_tile(look, x, y, z, centre_ramp, g, push)
    local t = look.tile(x, y, z)
    if not t then return false, 'the map\'s edge' end
    local b = look.building(x, y, z)
    local bb = building_blocks(b, t)
    if bb and bb ~= 'floored' then return false, bb, b end
    local floored = bb == 'floored'
    if not floored then
        local why = wagon_ground(t)
        if why then return false, why end
    end
    local wg = look.group(x, y, z)
    if wg ~= 0 and wg == g then return true end
    if t.shape == 'RAMP_TOP' then
        if look.group(x, y, z - 1) ~= 0 then push(x, y, z - 1) return true end
        return false, 'a ramp\'s top with no ramp under it'
    elseif t.shape == 'WALL' and centre_ramp and not is_tree(t) then
        if look.group(x, y, z + 1) ~= 0 then push(x, y, z + 1) return true end
    end
    if wg ~= 0 then return false, 'ground the wagons can\'t get to' end
    return false, wall_words(t)
end

local WAGON_AROUND = {{0, 0}, {-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1}}

-- Can a wagon stand with its middle here? true and the level changes it
-- opens, or false and every blocking tile of its 3x3 ({x, y, z, what, b}).
local function wagon_fits(look, cx, cy, cz, g)
    local ct = look.tile(cx, cy, cz)
    local ramp = ct ~= nil and ct.shape == 'RAMP'
    local pushes, blocks = {}, {}
    local function push(x, y, z) table.insert(pushes, {x = x, y = y, z = z}) end
    for _, o in ipairs(WAGON_AROUND) do
        local x, y = cx + o[1], cy + o[2]
        local ok, what, b = wagon_tile(look, x, y, cz, ramp, g, push)
        if not ok then table.insert(blocks, {x = x, y = y, z = cz, what = what, b = b}) end
    end
    if #blocks > 0 then return false, blocks end
    return true, pushes
end

-- The map look-ups the wagon check uses: `info` a cached tile_info.
local function wagon_look(info)
    local bcache, gcache = {}, {}
    return {
        tile = info,
        building = function(x, y, z)
            local k = (z * 4096 + y) * 4096 + x
            local v = bcache[k]
            if v == nil then v = wagon_building(x, y, z) or false; bcache[k] = v end
            return v or nil
        end,
        group = function(x, y, z)
            local k = (z * 4096 + y) * 4096 + x
            local v = gcache[k]
            if v == nil then v = walk_group(x, y, z) or 0; gcache[k] = v end
            return v
        end,
    }
end

-- One wagon position, read fresh (tests, and a look by hand): true and the
-- level changes, or false and the blocking tiles. g: the walking group
-- (default: the tile's own).
function wagon_fits_at(x, y, z, g)
    local look = wagon_look(tile_info)
    return wagon_fits(look, x, y, z, g or look.group(x, y, z))
end

-- A fresh look-up set for wagon_reaches_edge (tests, and a look by hand).
function wagon_lookup()
    return wagon_look(tile_info)
end

-- How a blocking tile could be cleared by the AI: 'fell', 'smooth', or nil.
local function wagon_fix_of(look, blk)
    if blk.b then return nil end
    local t = look.tile(blk.x, blk.y, blk.z)
    if not t then return nil end
    if is_tree(t) then return 'fell' end
    if t.shape == 'BOULDER' then return 'smooth' end
    return nil
end

-- From the road's mouth (seeds: the surface tiles a wagon comes up onto),
-- out to the map's edge, the way DFHack walks it (straight steps, the 3x3
-- round each). skip: tiles not to step back onto (the road itself).
-- Returns {reached, cut, n, blocks}: blocks are the blocking tiles round the
-- positions that failed, nearest the map's edge first, those the AI could
-- clear (trees, boulders) ahead of the rest. `dead`: positions already known
-- to lead nowhere (filled here when the edge isn't reached).
function wagon_reaches_edge(look, seeds, g, skip, dead)
    local W, H = map_size()
    local function edge_d(x, y) return math.min(x, y, W - 1 - x, H - 1 - y) end
    local seen, heap = {}, {}
    local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
    -- a binary heap by distance to the map's edge (nearest first: the way out is found soon on open ground)
    local function hpush(p)
        table.insert(heap, p)
        local i = #heap
        while i > 1 do
            local j = i // 2
            if heap[j].d <= heap[i].d then break end
            heap[i], heap[j] = heap[j], heap[i]
            i = j
        end
    end
    local function hpop()
        local top = heap[1]
        local last = table.remove(heap)
        if #heap > 0 then
            heap[1] = last
            local i = 1
            while true do
                local l, r, m = 2 * i, 2 * i + 1, i
                if l <= #heap and heap[l].d < heap[m].d then m = l end
                if r <= #heap and heap[r].d < heap[m].d then m = r end
                if m == i then break end
                heap[i], heap[m] = heap[m], heap[i]
                i = m
            end
        end
        return top
    end
    for k in pairs(skip or {}) do seen[k] = true end
    for _, s in ipairs(seeds) do
        local k = key(s.x, s.y, s.z)
        seen[k] = true
        hpush({x = s.x, y = s.y, z = s.z, d = edge_d(s.x, s.y)})
    end
    local deadline = os.clock() + DEEP_WAGON_SECONDS
    local n, failed = 0, {}
    local visited = {}
    while #heap > 0 do
        if n >= DEEP_WAGON_NODES or os.clock() > deadline then return {reached = false, cut = true, n = n} end
        local p = hpop()
        table.insert(visited, key(p.x, p.y, p.z))
        if dead and dead[key(p.x, p.y, p.z)] then
            -- (the search's earlier floods: from here nothing gets out)
        else
            for _, d in ipairs(DEEP_DIRS) do
                local x, y, z = p.x + d[1], p.y + d[2], p.z
                local k = key(x, y, z)
                if not seen[k] then
                    seen[k] = true
                    n = n + 1
                    local ok, r = wagon_fits(look, x, y, z, g)
                    if ok then
                        if x <= 1 or y <= 1 or x >= W - 2 or y >= H - 2 then
                            return {reached = true, n = n}
                        end
                        hpush({x = x, y = y, z = z, d = edge_d(x, y)})
                        for _, q in ipairs(r) do
                            local qk = key(q.x, q.y, q.z)
                            if not seen[qk] then
                                seen[qk] = true
                                hpush({x = q.x, y = q.y, z = q.z, d = edge_d(q.x, q.y)})
                            end
                        end
                    else
                        for _, blk in ipairs(r) do
                            blk.d = edge_d(x, y)
                            blk.fix = wagon_fix_of(look, blk)
                            table.insert(failed, blk)
                        end
                    end
                end
            end
        end
    end
    if dead then for _, k in ipairs(visited) do dead[k] = true end end
    table.sort(failed, function(a, b)
        if (a.fix ~= nil) ~= (b.fix ~= nil) then return a.fix ~= nil end
        if a.d ~= b.d then return a.d < b.d end
        if a.z ~= b.z then return a.z > b.z end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    -- one entry a tile
    local out, once = {}, {}
    for _, blk in ipairs(failed) do
        local k = key(blk.x, blk.y, blk.z)
        if not once[k] then once[k] = true; table.insert(out, blk) end
    end
    return {reached = false, n = n, blocks = out}
end

-- The road's heading: saved since 0.105.30, else from its start and the
-- middle of the surface channel (the plan's second tile).
local function deep_dir(d)
    if type(d.dir) == 'table' and d.dir[1] then return {d.dir[1], d.dir[2]} end
    local s, t = d.start, d.tiles and d.tiles[2]
    if not (s and t) then return nil end
    local dx, dy = t.x - s.x, t.y - s.y
    if math.abs(dx) + math.abs(dy) ~= 1 then return nil end
    return {dx, dy}
end

-- The surface tiles in front of the road's mouth where the wagons turn in:
-- {{x, y, z}, ...} (rows u = -2 .. 0, v = -2 .. 2 off the start). nil before
-- a road is planned. For the keep's court and the gatehouse: no wall there.
function deep_depot_mouth()
    local d = deep_depot_data()
    if not (d and d.start and d.stage ~= 'no_road') then return nil end
    local dir = deep_dir(d)
    if not dir then return nil end
    local px, py = -dir[2], dir[1]
    local out = {}
    for u = -2, 1 do
        for v = -2, 2 do
            table.insert(out, {x = d.start.x + u * dir[1] + v * px, y = d.start.y + u * dir[2] + v * py, z = d.start.z})
        end
    end
    return out
end

-- Is the plan safe to dig? true, or false and why. `surf` the surface level;
-- `reserved` the AI's levels; `info` a cached tile_info.
local function deep_plan_ok(plan, surf, reserved, info)
    if plan.road > DEEP_ROAD_MAX then return false, 'the road would be too long' end
    local mw, mh = map_size()
    local mine = {}
    for _, t in ipairs(plan.tiles) do mine[(t.z * 4096 + t.y) * 4096 + t.x] = t.r end
    local function planned(x, y, z) return mine[(z * 4096 + y) * 4096 + x] end
    for _, p in ipairs(plan.tiles) do
        if p.x < 2 or p.y < 2 or p.x > mw - 3 or p.y > mh - 3 then return false, 'off the map\'s edge' end
        if p.z < surf then
            local t = info(p.x, p.y, p.z)
            local ok, why = natural_wall(t)
            if not ok then return false, why end
            for ddx = -1, 1 do
                for ddy = -1, 1 do
                    if inside_any(reserved, p.x + ddx, p.y + ddy, p.z) then return false, 'by one of the fort\'s levels' end
                    if (ddx ~= 0 or ddy ~= 0) and not planned(p.x + ddx, p.y + ddy, p.z) then
                        local n = info(p.x + ddx, p.y + ddy, p.z)
                        if not n or n.shape ~= 'WALL' or n.aquifer or n.liquid or n.feature or n.designated then
                            return false, 'open space, water or an aquifer beside it'
                        end
                    end
                end
            end
            if not planned(p.x, p.y, p.z + 1) then
                local up = info(p.x, p.y, p.z + 1)
                local roof = up and not up.liquid and not up.aquifer and not up.designated
                    and (up.shape == 'WALL' or (p.z + 1 == surf and DEEP_ROOF[up.shape]))
                if not roof then return false, 'no solid roof over it' end
            end
            if not planned(p.x, p.y, p.z - 1) then
                local dn = info(p.x, p.y, p.z - 1)
                if not dn or dn.shape ~= 'WALL' or dn.aquifer or dn.liquid or dn.feature or dn.designated then
                    return false, 'no solid rock under it'
                end
            end
        end
    end
    return true
end

-- The road's start: three rows of open ground (the approach, the start, the
-- surface channel) a wagon can stand on, rock under the last two.
local function deep_start_ok(x, y, z, d, ground)
    local px, py = -d[2], d[1]
    for u = -1, 1 do
        for v = -1, 1 do
            local tx, ty = x + u * d[1] + v * px, y + u * d[2] + v * py
            if not ground(tx, ty, z) then return false end
        end
    end
    return true
end

-- The road and hall nearest the fort's ways in: the plan, or nil and why.
function find_deep_depot(reserved)
    local anchors = pasture_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to start from' end
    local groups = {}
    for _, p in ipairs(citizen_positions()) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
    end
    local mw, mh = map_size()
    local cache = {}
    local function info(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = tile_info(x, y, z) or false; cache[k] = v end
        return v or nil
    end
    local gcache = {}
    local function ground(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = gcache[k]
        if v ~= nil then return v end
        v = false
        if x >= 2 and y >= 2 and x <= mw - 3 and y <= mh - 3 then
            local t = info(x, y, z)
            v = t ~= nil and t.outside == true and not t.hidden and not t.liquid and not t.feature
                and not t.building and not t.designated and GROUND[t.shape] == true and not is_tree(t)
                and not tile_taken(x, y, z) and groups[walk_group(x, y, z)] == true
            for _, a in ipairs(anchors) do
                if v and a.z == z and math.max(math.abs(a.x - x), math.abs(a.y - y)) < DEEP_DEPOT_CLEAR then v = false end
            end
        end
        gcache[k] = v
        return v
    end
    local deadline = os.clock() + DEEP_DEPOT_SECONDS
    local cands, seen = {}, {}
    for _, a in ipairs(anchors) do
        for z = a.z + 1, a.z - 1, -1 do
            for y = a.y - DEEP_DEPOT_REACH, a.y + DEEP_DEPOT_REACH do
                if os.clock() > deadline then break end
                for x = a.x - DEEP_DEPOT_REACH, a.x + DEEP_DEPOT_REACH do
                    local k = (z * 4096 + y) * 4096 + x
                    if not seen[k] and ground(x, y, z) then
                        seen[k] = true
                        for i, d in ipairs(DEEP_DIRS) do
                            if deep_start_ok(x, y, z, d, ground) then
                                table.insert(cands, {x = x, y = y, z = z, d = d, i = i,
                                    dist = math.max(math.abs(a.x - x), math.abs(a.y - y)) + 3 * math.abs(a.z - z)})
                            end
                        end
                    end
                end
            end
        end
    end
    if #cands == 0 then
        return nil, ('no open ground 3 tiles wide within %d tiles of the way in for a wagon road to start on')
            :format(DEEP_DEPOT_REACH)
    end
    table.sort(cands, function(p, q)
        if p.dist ~= q.dist then return p.dist < q.dist end
        if p.z ~= q.z then return p.z > q.z end
        if p.y ~= q.y then return p.y < q.y end
        if p.x ~= q.x then return p.x < q.x end
        return p.i < q.i
    end)
    local last = 'no way down'
    -- (0.105.30) the wagons' way from the map's edge to the road's start
    local look, dead = wagon_look(info), {}
    local edge_ok = {}            -- start (x, y, z, dir) -> the flood's answer
    local function wagons_reach(c)
        local px, py = -c.d[2], c.d[1]
        local seeds = {}
        for v = -1, 1 do table.insert(seeds, {x = c.x + v * px, y = c.y + v * py, z = c.z}) end
        local g = look.group(c.x, c.y, c.z)
        if g == 0 then return false, 'its start is not ground the dwarves walk' end
        local res = wagon_reaches_edge(look, seeds, g, nil, dead)
        if res.reached or res.cut then return true end         -- (cut short: not known, not ruled out)
        local b = res.blocks and res.blocks[1]
        return false, b and ('no 3-wide way for wagons from the map\'s edge to its start (%s at x%d y%d)')
            :format(b.what, b.x, b.y) or 'no 3-wide way for wagons from the map\'s edge to its start'
    end
    for i, c in ipairs(cands) do
        if os.clock() > deadline then
            return nil, ('the search ran out of time after %d of %d starts (%s)'):format(i - 1, #cands, last)
        end
        for k = 1, DEEP_DEPOT_LEVELS do
            local plan = deep_depot_layout(c.x, c.y, c.z, c.d, k)
            -- the surface channel's ramp needs rock under the start row too
            local ok, why = true, nil
            local px, py = -c.d[2], c.d[1]
            for v = -1, 1 do
                local under = info(c.x + v * px, c.y + v * py, c.z - 1)
                if under and under.aquifer then
                    ok, why = false, 'an aquifer under the road\'s start'
                elseif not under or under.shape ~= 'WALL' or under.liquid then
                    ok, why = false, 'no rock under the road\'s start'
                end
            end
            if ok then ok, why = deep_plan_ok(plan, c.z, reserved, info) end
            if ok then
                local ek = ((c.z * 4096 + c.y) * 4096 + c.x) * 4 + c.i
                if edge_ok[ek] == nil then
                    local okw, w = wagons_reach(c)
                    edge_ok[ek] = okw and true or (w or false)
                end
                if edge_ok[ek] ~= true then
                    last = edge_ok[ek] or 'no way for wagons to its start'
                    break                  -- (the same start at any depth: the wagons still can't get to it)
                end
            end
            if ok then
                plan.start = {x = c.x, y = c.y, z = c.z}
                plan.dir = c.d
                return plan
            end
            last = why
        end
    end
    return nil, ('no wagon road of %d tiles at most and %d levels down through safe rock from near the way in (%s)')
        :format(DEEP_ROAD_MAX, DEEP_DEPOT_LEVELS, last)
end

-- The depot standing in the hall, if any.
local function deep_depot_building(d)
    if not (d and d.depot) then return nil end
    local ok, b = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
            if b.z == d.depot.z and b.x1 <= d.depot.x and b.x2 >= d.depot.x and b.y1 <= d.depot.y and b.y2 >= d.depot.y then
                return b
            end
        end
    end)
    return ok and b or nil
end

local function any_depot()
    local ok, n = pcall(function() return #df.global.world.buildings.other.TRADE_DEPOT end)
    return ok and n and n > 0
end

-- Built? (a planned or half-built depot is not)
local function depot_built(b)
    local ok, v = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    if ok then return v end
    return nil
end

-- What the game says of the wagons: true (accessible), false (not), or nil
-- when this DF/DFHack doesn't show it. building_tradedepotst.accessible is
-- set by the game's own wagon path check (the depot's sheet shows it).
function depot_wagon_access(b)
    if not b then return nil end
    local ok, v = pcall(function() return b.accessible end)
    if not ok or v == nil then return nil end
    if type(v) == 'boolean' then return v end
    if type(v) == 'number' then return v ~= 0 end
    return nil
end

-- A tile of the plan dug as it should be?
local function deep_tile_done(t, r)
    if not t then return false end
    if r == 'd' then return t.shape ~= 'WALL' end
    if r == 'h' then return t.shape == 'EMPTY' or t.shape == 'RAMP_TOP' end
    return t.shape == 'RAMP'
end

-- Tiles left to dig, and the ones that lost their designation (no job on them).
local function deep_dig_left(d)
    local left, stalled = 0, {}
    local jobs = job_tiles()
    local done = {}
    for _, p in ipairs(d.tiles or {}) do
        local t = tile_info(p.x, p.y, p.z)
        local ok = deep_tile_done(t, p.r)
        done[(p.z * 4096 + p.y) * 4096 + p.x] = ok
        if not ok then left = left + 1 end
    end
    for _, p in ipairs(d.tiles or {}) do
        if not done[(p.z * 4096 + p.y) * 4096 + p.x] then
            local t = tile_info(p.x, p.y, p.z)
            local px, py, pz = math.tointeger(p.x) or p.x, math.tointeger(p.y) or p.y, math.tointeger(p.z) or p.z
            local busy = jobs[px .. ',' .. py .. ',' .. pz] ~= nil
            if t and not t.designated and not busy then
                if p.r ~= 'ramp' then
                    table.insert(stalled, {x = p.x, y = p.y, z = p.z, key = p.r})
                elseif done[((p.z + 1) * 4096 + p.y) * 4096 + p.x] and t.shape == 'WALL' then
                    -- the channel above is open but the rock under it stayed: dig the ramp itself
                    table.insert(stalled, {x = p.x, y = p.y, z = p.z, key = 'r'})
                end
            end
        end
    end
    return left, stalled
end

-- --- (0.105.30) the built road, checked for the wagons ---------------------------
--
-- deep_wagon_check(d): the AI's best guess at what stops the wagons, along
-- its own road in the order a wagon drives it: the two rows of ground in
-- front of the mouth, the channel's open tops, the ramps, the road's floor,
-- the hall; then the way over the surface from the mouth to the map's edge.
-- {state = 'clear'|'blocked'|'unknown', block = {x, y, z, what, text, fix,
-- key, id, pending, tiles}, opens = {x, y, z}}. fix: 'fell' (a tree),
-- 'smooth' (a boulder), 'redig' (key: h channel, r ramp, d floor), 'remove'
-- (a door, hatch, trap... on the AI's own road), or nil (a Needs you).
-- opens: where the hall or road opens into the fort (it shouldn't: then a
-- door there guards the fort, and is not the AI's to take away).
local DEEP_WANT = {h = 'the ramp\'s open top', ramp = 'a ramp', d = 'dug floor'}
DEEP_REMOVING = DEEP_REMOVING or {}      -- building id -> true: its removal was ordered
DEEP_CHECK = DEEP_CHECK or {}            -- {tick, at, res}: the report's last check

-- (tests replace this) take a building down: DFHack's own call
function remove_building(id)
    local ok, r = pcall(function()
        local b = df.building.find(id)
        if not b then return false end
        dfhack.buildings.deconstruct(b)
        return true
    end)
    return ok and r == true
end

local function shape_words(t)
    if not t then return 'off the map' end
    if is_tree(t) then return 'a tree' end
    local s = tostring(t.shape)
    if s == 'WALL' then return t.material == 'CONSTRUCTION' and 'a built wall' or 'solid rock' end
    if s == 'EMPTY' then return 'open space' end
    if s == 'RAMP_TOP' then return 'a ramp\'s open top' end
    return s:lower():gsub('_', ' ')
end

function deep_wagon_check(d)
    local cache = {}
    local function info(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = tile_info(x, y, z) or false; cache[k] = v end
        return v or nil
    end
    local look = wagon_look(info)
    local dir = d and deep_dir(d)
    if not (dir and d.start and d.tiles and d.depot) then
        return {state = 'unknown', why = 'the road\'s plan is not in the save'}
    end
    local function k3(x, y, z) return (z * 4096 + y) * 4096 + x end
    local px, py = -dir[2], dir[1]
    local sx, sy, sz = d.start.x, d.start.y, d.start.z
    local plan = {}
    for _, p in ipairs(d.tiles) do plan[k3(p.x, p.y, p.z)] = p.r end
    -- where the hall or road opens into anything walkable that isn't its own
    local opens
    for _, p in ipairs(d.tiles) do
        if p.z < sz and not opens then
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local x, y = p.x + dx, p.y + dy
                    if not opens and (dx ~= 0 or dy ~= 0) and not plan[k3(x, y, p.z)] and look.group(x, y, p.z) ~= 0 then
                        local t = info(x, y, p.z)
                        -- (the rock round the ramps' foot is walked over from the surface: not an opening)
                        if t and t.shape ~= 'WALL' then opens = {x = x, y = y, z = p.z} end
                    end
                end
            end
        end
    end
    -- (0.105.30 fixes) and up or down from it: a stair (or a ramp, or a
    -- channel) out of the hall or road to a level that isn't the road's own
    -- (a stair down from the hall's floor into the fort)
    local UP = {STAIR_UP = true, STAIR_UPDOWN = true}
    local DOWN = {STAIR_DOWN = true, STAIR_UPDOWN = true}
    local function walk_tile(x, y, z)
        if plan[k3(x, y, z)] then return nil end
        local t = info(x, y, z)
        if not t or t.shape == 'WALL' or t.shape == 'EMPTY' then return nil end
        return t
    end
    for _, p in ipairs(d.tiles) do
        if opens then break end
        if p.z < sz then
            local t = info(p.x, p.y, p.z)
            local shape = t and t.shape
            if shape and DOWN[shape] then
                local dn = walk_tile(p.x, p.y, p.z - 1)
                if dn and UP[dn.shape] then opens = {x = p.x, y = p.y, z = p.z - 1} end
            end
            if not opens and shape and UP[shape] and p.z + 1 < sz then
                local up = walk_tile(p.x, p.y, p.z + 1)
                if up and DOWN[up.shape] then opens = {x = p.x, y = p.y, z = p.z + 1} end
            end
            if not opens and (shape == 'RAMP_TOP' or shape == 'EMPTY') and p.r ~= 'h' then
                -- the hall's floor channelled or holed: what is under it
                if walk_tile(p.x, p.y, p.z - 1) then opens = {x = p.x, y = p.y, z = p.z - 1} end
            end
            if not opens and shape == 'RAMP' and p.z + 1 < sz then
                -- a ramp of the road leads up beside it: to a level of the fort?
                for dx = -1, 1 do
                    for dy = -1, 1 do
                        if not opens and (dx ~= 0 or dy ~= 0) then
                            local up = walk_tile(p.x + dx, p.y + dy, p.z + 1)
                            if up and not up.outside and up.shape ~= 'RAMP_TOP' then
                                opens = {x = p.x + dx, y = p.y + dy, z = p.z + 1}
                            end
                        end
                    end
                end
            end
        end
    end
    local function block(x, y, z, what, fix, extra)
        local b = {x = x, y = y, z = z, elevation = ez(z), what = what, fix = fix}
        for k, v in pairs(extra or {}) do b[k] = v end
        b.text = b.text or ('%s at x%d y%d elevation %d on the depot road'):format(what, x, y, ez(z))
        local t = info(x, y, z)
        if fix == 'fell' or fix == 'redig' then
            b.pending = t ~= nil and t.designated == true
        elseif fix == 'smooth' then
            b.pending = t ~= nil and (t.smoothing == true or t.designated == true)
        elseif fix == 'remove' then
            b.pending = b.id ~= nil and DEEP_REMOVING[b.id] == true
        end
        return {state = 'blocked', block = b, opens = opens}
    end
    -- what a building on the AI's road does: removed only when the hall and
    -- road are found sealed from the fort on every level (no `opens`, above:
    -- the same level, stairs, ramps and holes). Opening into the fort,
    -- anything there may be closing the fort's passage (a door, hatch,
    -- floodgate, grate, bars, a bridge...): never the AI's to take away,
    -- a Needs you. (0.105.30 fixes) A bridge never: the wagon drawbridge
    -- the gates put on the road is raised at an alarm, and a raised one is
    -- the gate doing its work.
    local function building_fix(b)
        if opens or not b or not b.id then return nil end
        if b.kind == 'Bridge' then return nil end
        return 'remove'
    end
    -- 1. the ground in front of the mouth (u = -1, 0)
    for u = -1, 0 do
        for v = -1, 1 do
            local x, y = sx + u * dir[1] + v * px, sy + u * dir[2] + v * py
            local t = info(x, y, sz)
            local b = look.building(x, y, sz)
            local bb = building_blocks(b, t)
            if bb and bb ~= 'floored' then
                return block(x, y, sz, bb, nil, {id = b.id,
                    text = ('%s at x%d y%d elevation %d, in front of the depot road\'s mouth'):format(bb, x, y, ez(sz))})
            end
            local why = t and wagon_ground(t) or (not t and 'off the map') or nil
            if not why and t and (t.shape == 'WALL' or is_tree(t)) then why = shape_words(t) end
            if why then
                local fix = (t and is_tree(t)) and 'fell' or (t and t.shape == 'BOULDER') and 'smooth' or nil
                return block(x, y, sz, why, fix,
                    {text = ('%s at x%d y%d elevation %d, in front of the depot road\'s mouth'):format(why, x, y, ez(sz))})
            end
        end
    end
    -- 2. the road and the hall, as dug (the plan's own order: down the road)
    for _, p in ipairs(d.tiles) do
        local t = info(p.x, p.y, p.z)
        local b = look.building(p.x, p.y, p.z)
        local bb = building_blocks(b, t)
        if bb and bb ~= 'floored' then
            return block(p.x, p.y, p.z, bb, building_fix(b), {id = b.id, kind = b.kind})
        end
        local shape = t and t.shape
        if p.r == 'h' then
            if shape == 'EMPTY' then
                local dn = info(p.x, p.y, p.z - 1)
                return block(p.x, p.y, p.z, 'open space where a ramp\'s top should be (no ramp under it)',
                    (dn and dn.shape == 'WALL') and 'redig' or nil, {key = 'r', at = {x = p.x, y = p.y, z = p.z - 1}})
            elseif shape ~= 'RAMP_TOP' then
                return block(p.x, p.y, p.z, ('%s where %s should be'):format(shape_words(t), DEEP_WANT.h),
                    (shape == 'WALL' or GROUND[shape or '']) and 'redig' or nil, {key = 'h'})
            end
        elseif p.r == 'ramp' then
            if shape ~= 'RAMP' then
                local good = 0
                for _, q in ipairs(d.tiles) do
                    if q.r == 'ramp' and q.z == p.z then
                        local qt = info(q.x, q.y, q.z)
                        if qt and qt.shape == 'RAMP' then good = good + 1 end
                    end
                end
                return block(p.x, p.y, p.z, ('%s where a ramp should be'):format(shape_words(t)),
                    shape == 'WALL' and 'redig' or nil, {key = 'r',
                    text = ('the ramp at x%d y%d elevation %d is %s, so the ramp row is %d wide (a wagon needs 3)')
                        :format(p.x, p.y, ez(p.z), shape_words(t), good)})
            end
        else
            if shape == 'WALL' then
                return block(p.x, p.y, p.z, 'solid rock where the road\'s floor should be', 'redig', {key = 'd'})
            end
            local why = t and wagon_ground(t) or (not t and 'off the map') or nil
            if why then
                return block(p.x, p.y, p.z, why, shape == 'BOULDER' and 'smooth' or nil)
            end
        end
    end
    -- 3. from the mouth over the surface to the map's edge
    local g = look.group(sx, sy, sz)
    if g == 0 then
        return block(sx, sy, sz, ('%s at the road\'s start'):format(shape_words(info(sx, sy, sz))), nil)
    end
    local seeds, skip = {}, {}
    for v = -1, 1 do table.insert(seeds, {x = sx + v * px, y = sy + v * py, z = sz}) end
    for _, p in ipairs(d.tiles) do skip[k3(p.x, p.y, p.z)] = true end
    local res = wagon_reaches_edge(look, seeds, g, skip)
    if res.reached then return {state = 'clear', opens = opens} end
    if res.cut then return {state = 'unknown', opens = opens, why = 'the way to the map\'s edge is too long to check'} end
    local first = res.blocks and res.blocks[1]
    if not first then
        return block(sx, sy, sz, 'no room to turn', nil, {text = ('no 3-wide way for wagons from the depot road\'s '
            .. 'mouth at x%d y%d elevation %d to the map\'s edge'):format(sx, sy, ez(sz))})
    end
    local tiles = {}
    for _, b in ipairs(res.blocks) do
        if b.fix == first.fix and first.fix and #tiles < DEEP_FIX_MAX then
            table.insert(tiles, {x = b.x, y = b.y, z = b.z})
        end
    end
    return block(first.x, first.y, first.z, first.what, first.fix, {id = first.b and first.b.id,
        tiles = #tiles > 0 and tiles or nil,
        text = ('%s at x%d y%d elevation %d, on the wagons\' way from the depot road\'s mouth (x%d y%d) to the '
                .. 'map\'s edge (no 3-wide way past it)'):format(first.what, first.x, first.y, ez(first.z), sx, sy)})
end

-- The block for the report: {x, y, elevation, what, text, fix, pending}.
local function block_report(b)
    if not b then return nil end
    return {x = b.x, y = b.y, elevation = b.elevation, what = b.what, text = b.text, fix = b.fix,
            pending = b.pending or nil}
end

-- Clear a block: the number of tiles marked (or buildings taken down).
local function deep_fix(b)
    local n = 0
    if b.fix == 'fell' then
        for _, p in ipairs(b.tiles or {b}) do
            local t = tile_info(p.x, p.y, p.z)
            if t and is_tree(t) and not t.designated and fell_tree(p.x, p.y, p.z) then n = n + 1 end
        end
    elseif b.fix == 'smooth' then
        for _, p in ipairs(b.tiles or {b}) do
            local ok = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 's'}}, p.z, p.x, p.y)
            if ok then n = n + 1 end
        end
    elseif b.fix == 'redig' then
        local at = b.at or b
        local ok = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = b.key or 'd'}}, at.z, at.x, at.y)
        if ok then n = 1 end
    elseif b.fix == 'remove' and b.id then
        if remove_building(b.id) then DEEP_REMOVING[b.id] = true; n = 1 end
    end
    return n
end

local FIX_WORDS = {fell = 'tree(s) marked for felling', smooth = 'boulder(s) marked for smoothing',
                   redig = 'tile(s) marked for digging again', remove = 'building(s) taken down'}

-- The report's check, kept for an in-game day (the surface walk is not free).
local function deep_check_cached(d)
    local now = deep_now() or 0
    local at = d.depot and ('%s,%s,%s'):format(d.depot.x, d.depot.y, d.depot.z) or ''
    local c = DEEP_CHECK
    if c.res and c.at == at and c.tick and now >= c.tick and now - c.tick < DEEP_WAGON_CHECK_TICKS then return c.res end
    local ok, res = pcall(deep_wagon_check, d)
    res = ok and res or {state = 'unknown', why = tostring(res)}
    DEEP_CHECK = {tick = now, at = at, res = res}
    return res
end

-- The report's view, once begun: {stage, x, y, elevation, levels, road,
-- tiles_left, stalled, depot = none|building|built, wagon_access, why}.
-- (0.105.30) built and the wagons not known to get there: dfhack_wagon_access
-- (DFHack's own check), wagon_check (clear|blocked|unknown), wagon_block
-- ({x, y, elevation, what, text, fix, pending}), opens_fort ({x, y, elevation}).
function deep_depot_status()
    local d = deep_depot_data()
    if not d then return nil end
    if d.stage == 'no_road' then
        local now = deep_now()
        if now and d.tick and now - d.tick >= DEEP_DEPOT_RETRY_TICKS then return nil end
        return {stage = 'no_road', why = d.why}
    end
    local out = {stage = d.stage, levels = d.levels, road = d.road}
    if d.depot then out.x, out.y, out.elevation = d.depot.x, d.depot.y, ez(d.depot.z) end
    local left, stalled = deep_dig_left(d)
    out.tiles_left, out.stalled = left, #stalled
    if d.stage == 'placed' then
        local b = deep_depot_building(d)
        if not b then
            out.depot = 'none'
        else
            local built = depot_built(b)
            out.depot = built == false and 'building' or 'built'
            if built ~= false then out.wagon_access = depot_wagon_access(b) end
            if built ~= false and out.wagon_access ~= true then
                out.dfhack_wagon_access = dfhack_wagon_access()
                if out.dfhack_wagon_access ~= true then
                    local chk = deep_check_cached(d)
                    out.wagon_check = chk.state
                    out.wagon_block = block_report(chk.block)
                    if chk.opens then
                        out.opens_fort = {x = chk.opens.x, y = chk.opens.y, elevation = ez(chk.opens.z)}
                    end
                end
            end
        end
    end
    return out
end

-- One step of the underground depot (see above).
function place_deep_depot(dry_run)
    OFFSET = elevation_offset()
    local d = deep_depot_data()
    if d and d.stage == 'no_road' then
        local now = deep_now()
        if not (now and d.tick and now - d.tick >= DEEP_DEPOT_RETRY_TICKS) then
            return {ok = false, rejected = true, no_road = true,
                    error = 'no wagon road down was found (' .. tostring(d.why) .. '): the depot goes on the surface'}
        end
        d = nil
    end
    if not d then
        if any_depot() then
            return {ok = false, rejected = true, error = 'a trade depot already stands'}
        end
        local plan, why = find_deep_depot(level_areas())
        if not plan then
            if not dry_run then save_deep_depot({stage = 'no_road', why = why, tick = deep_now()}) end
            return {ok = false, rejected = true, no_road = true, error = why, dry_run = dry_run or nil}
        end
        local out = {ok = true, stage = 'digging', x = plan.depot.x, y = plan.depot.y,
                     elevation = ez(plan.depot.z), levels = plan.levels, road = plan.road,
                     tiles = #plan.tiles, start = {x = plan.start.x, y = plan.start.y, elevation = ez(plan.start.z)},
                     dry_run = dry_run or nil}
        if dry_run then return out end
        -- designated level by level, the surface first (the miners come down the road)
        local by_z, zs = {}, {}
        for _, p in ipairs(plan.tiles) do
            if p.r ~= 'ramp' then
                if not by_z[p.z] then by_z[p.z] = {}; table.insert(zs, p.z) end
                table.insert(by_z[p.z], {x = p.x, y = p.y, text = p.r})
            end
        end
        table.sort(zs, function(a, b) return a > b end)
        for _, z in ipairs(zs) do
            local okd, dry = pcall(quickfort_apply, 'dig', by_z[z], z, 0, 0, 'run', true)
            if not okd or stat(dry, 'dig_designated') < #by_z[z] then
                return {ok = false, error = ('the game would not designate the wagon road at elevation %d'):format(ez(z))}
            end
        end
        for _, z in ipairs(zs) do pcall(quickfort_apply, 'dig', by_z[z], z, 0, 0) end
        save_deep_depot({stage = 'digging', tiles = plan.tiles, depot = plan.depot, hall = plan.hall,
                         levels = plan.levels, road = plan.road, start = plan.start,
                         dir = {plan.dir[1], plan.dir[2]}})
        return out
    end
    if d.stage == 'digging' then
        local left, stalled = deep_dig_left(d)
        if left > 0 then
            if #stalled == 0 then
                return {ok = false, rejected = true, waiting = true, stage = 'digging', tiles_left = left,
                        error = ('the wagon road and depot hall are being dug: %d tile(s) left'):format(left)}
            end
            if dry_run then return {ok = true, stage = 'digging', redig = #stalled, dry_run = true} end
            local n = 0
            for i = 1, math.min(#stalled, DEEP_REDIG_MAX) do
                local s = stalled[i]
                local ok = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = s.key}}, s.z, s.x, s.y)
                if ok then n = n + 1 end
            end
            return {ok = n > 0, stage = 'digging', redig = n, tiles_left = left,
                    error = n == 0 and 'the game would not designate the road\'s lost tiles again' or nil}
        end
        d.stage = 'placed'          -- dug: the depot goes in (below)
    end
    -- placed: the depot in the hall's middle (again if it was taken down)
    local b = deep_depot_building(d)
    if b then
        local built, acc = depot_built(b), depot_wagon_access(b)
        local out = {ok = false, rejected = true, done = true, stage = 'placed',
                     depot = built == false and 'building' or 'built', wagon_access = acc,
                     error = 'the underground trade depot is placed'}
        -- (0.105.30) built, and the game doesn't say the wagons get there:
        -- the first thing in their way, cleared when the AI can
        if built == false or acc == true then return out end
        out.dfhack_wagon_access = dfhack_wagon_access()
        if out.dfhack_wagon_access == true then return out end
        local okc, chk = pcall(deep_wagon_check, d)
        if not okc then out.error = 'the wagons\' way could not be checked: ' .. tostring(chk) return out end
        DEEP_CHECK = {}                            -- the report looks again
        out.wagon_check = chk.state
        out.wagon_block = block_report(chk.block)
        if chk.state ~= 'blocked' then
            if chk.state == 'clear' then
                out.error = 'the underground trade depot is placed; the AI finds nothing in the wagons\' way'
            end
            return out
        end
        local blk = chk.block
        if blk.fix and not blk.pending then
            if dry_run then
                return {ok = true, stage = 'placed', fix = blk.fix, wagon_block = out.wagon_block, dry_run = true}
            end
            local n = deep_fix(blk)
            return {ok = n > 0, stage = 'placed', fixed = blk.fix, marked = n, wagon_block = out.wagon_block,
                    wagon_access = acc,
                    error = n == 0 and ('the game would not take the fix for ' .. blk.text) or nil,
                    note = n > 0 and ('%d %s: %s'):format(n, FIX_WORDS[blk.fix] or blk.fix, blk.text) or nil}
        elseif blk.fix then
            out.waiting = true
            out.error = 'the wagons\' way is being cleared: ' .. blk.text
        else
            out.needs_you = true
            out.error = 'the wagons can\'t reach the underground depot: ' .. blk.text .. ' (not the AI\'s to clear)'
        end
        return out
    end
    if any_depot() then return {ok = false, rejected = true, error = 'a trade depot already stands'} end
    local c = d.depot
    local good, failed = qf_try('build', {{x = 0, y = 0, text = 'D'}}, c.z, c.x, c.y, dry_run)
    if failed == 'dry' then
        return {ok = false, error = ('the game would not place the trade depot in the hall at x%d y%d elevation %d')
                    :format(c.x, c.y, ez(c.z))}
    elseif not good then
        return {ok = false, error = ('the game refused the trade depot at x%d y%d'):format(c.x, c.y)}
    end
    local out = {ok = true, stage = 'placed', x = c.x, y = c.y, elevation = ez(c.z), dry_run = dry_run or nil}
    if dry_run then return out end
    save_deep_depot(d)
    return out
end

-- --- the garbage dump (0.105.27 disposal) ------------------------------------------
--
-- place_dump_zone(inside, dry_run): a garbage dump zone, for the junk the AI
-- marks for dumping (lua/ai-disposal.lua, the bridge's place_dump).
--   inside false: outside on open ground, by place_surface('dump') (felling
--     trees first if it must; the zone comes on a later call);
--   inside true: a free 3x3 of inside floor near the main entrance, away from
--     the meeting hall, dining halls and the food, with no item or building
--     on it and no through-path (a dead end: one opening of at most 3 tiles,
--     no part of a hall or corridor); else a 3x3 room dug off a
--     corridor there (through a one-tile doorway), and the zone placed once
--     it is dug (a later call).
-- A dump zone already there on the same side of the walls is kept (no second
-- one). Returns {ok, zone_id, x, y, z, inside, why} (+ elevation, existing,
-- digging, waiting, dry_run).
DUMP_ROOM_KEY = 'ai-overseer/dump-room'
DUMP_NAME = 'AI dump'
DUMP_INSIDE_RADIUS = 20     -- how far from the entrance (x, y) the inside dump may be
DUMP_INSIDE_DEPTH = 4       -- the entrance's level and the ones below it searched
DUMP_KEEP_AWAY = 10         -- tiles from the meeting hall, dining halls and the food
DUMP_KEEP_ENTRANCE = 3      -- and never right at the way in
DUMP_OPENING = 3            -- (0.105.27 fixes) a free 3x3 inside: open to the rest in one run of this many tiles at most

local function dump_zone_type(zn)
    local ok, name = pcall(function() return df.civzone_type[zn.type] end)
    return ok and (name == 'Dump' or name == 'GarbageDump')
end

-- The dump zones in the game: {{id, x1, y1, x2, y2, z, inside}, ...}.
function dump_zones()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.Civzone and dump_zone_type(b) then
                local t = tile_info((b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2, b.z)
                table.insert(out, {id = b.id, x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
                                   inside = not (t and t.outside)})
            end
        end
    end)
    return out
end

-- The id of the dump zone on a tile, or nil.
function dump_zone_id_at(x, y, z)
    local ok, id = pcall(function()
        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(x, y, z)) or {}) do
            if dump_zone_type(zn) then return zn.id end
        end
    end)
    return ok and id or nil
end

local FOOD_WORKSHOPS = {Kitchen = true, Still = true, Butchers = true, Fishery = true, Farmers = true}
local KEEP_AWAY_ZONES = {MeetingHall = true, DiningHall = true, Tavern = true}

-- What a dump stays away from: the meeting hall and dining halls, food
-- stockpiles, kitchens, stills, butchers', farm plots: {{x1, y1, x2, y2, z}, ...}.
function dump_keep_away()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            local keep = false
            pcall(function()
                local bt = df.building_type[b:getType()]
                if bt == 'Civzone' then
                    keep = KEEP_AWAY_ZONES[df.civzone_type[b.type]] == true
                elseif bt == 'FarmPlot' then
                    keep = true
                elseif bt == 'Workshop' then
                    keep = FOOD_WORKSHOPS[df.workshop_type[b.type]] == true
                elseif bt == 'Stockpile' then
                    keep = b.settings.flags.food == true
                end
            end)
            if keep then table.insert(out, {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z}) end
        end
    end)
    return out
end

local function near_any(areas, x1, y1, x2, y2, z, d)
    for _, a in ipairs(areas) do
        if math.abs(a.z - z) <= 1 and x1 - d <= a.x2 and a.x1 <= x2 + d and y1 - d <= a.y2 and a.y1 <= y2 + d then
            return true
        end
    end
    return false
end

local function dump_text()
    return ('d{name="%s"}(3x3)'):format(DUMP_NAME)
end

local function dump_out(inside, x, y, z, why, extra)
    local out = {ok = true, inside = inside, x = x, y = y, z = z, elevation = z and ez(z) or nil, why = why}
    for k, v in pairs(extra or {}) do out[k] = v end
    return out
end

local function dump_fail(inside, why, extra)
    local out = {ok = false, inside = inside, why = why, error = why}
    for k, v in pairs(extra or {}) do out[k] = v end
    return out
end

-- The zone on a 3x3 at (x, y, z) inside.
local function zone_inside(x, y, z, dry_run, why)
    local good, failed = qf_try('zone', {{x = 0, y = 0, text = dump_text()}}, z, x, y, dry_run)
    if not good then
        return dump_fail(true, ('the game refused a garbage dump at x%d y%d elevation %d'):format(x, y, ez(z)),
                         {rejected = failed == 'dry' or nil})
    end
    return dump_out(true, x, y, z, why, {zone_id = (not dry_run) and dump_zone_id_at(x + 1, y + 1, z) or nil,
                                         dry_run = dry_run or nil})
end

-- (0.105.27 fixes) Only rock lies on the tile (what digging leaves): no item
-- of any other kind. False when it can't be read.
local function only_rock_on(x, y, z)
    local ok, yes = pcall(function()
        local block = dfhack.maps.getTileBlock(x, y, z)
        if not block then return false end
        for _, id in ipairs(block.items) do
            local it = df.item.find(id)
            if it and it.pos.x == x and it.pos.y == y and it.pos.z == z
                    and df.item_type[it:getType()] ~= 'BOULDER' then
                return false
            end
        end
        return true
    end)
    return ok and yes == true
end

-- A room being dug for the dump: its 3x3 all floor (dug), 'digging', or nil
-- (lost). (0.105.27 fixes) Dug, but something other than the dug rock lies
-- in it: 'digging' still (it is taken away first), with no tile left to dig.
local function dump_room_state(r)
    local dug, left = 0, 0
    for y = r.y, r.y + 2 do
        for x = r.x, r.x + 2 do
            local t = tile_info(x, y, r.z)
            if not t then return nil end
            if t.shape == 'FLOOR' and not t.building and not tile_taken(x, y, r.z) then
                if t.items and not only_rock_on(x, y, r.z) then return 'digging', 0, true end
                dug = dug + 1
            elseif t.shape == 'WALL' and t.designated then
                left = left + 1
            else
                return nil
            end
        end
    end
    if dug == 9 then return 'dug' end
    return 'digging', left
end

function place_dump_zone(inside, dry_run)
    OFFSET = elevation_offset()
    inside = inside == true
    -- one dump on each side of the walls is enough
    for _, d in ipairs(dump_zones()) do
        if (d.inside == true) == inside then
            return dump_out(inside, d.x1, d.y1, d.z, ('a garbage dump is already there (zone %d)'):format(d.id),
                            {zone_id = d.id, existing = true})
        end
    end
    if not inside then
        local r = place_surface('dump', dry_run)
        if not r.ok then return dump_fail(false, r.error or 'no spot for a garbage dump outside',
                                          {waiting = r.waiting, timed_out = r.timed_out, rejected = r.rejected}) end
        if r.clearing then
            return dump_out(false, r.x, r.y, r.z, ('trees are felled first to make room for the dump (%d)'):format(r.trees),
                            {clearing = true, dry_run = dry_run or nil})
        end
        return dump_out(false, r.x, r.y, r.z, 'a garbage dump on open ground outside',
                        {zone_id = (not dry_run) and dump_zone_id_at(r.x + 1, r.y + 1, r.z) or nil,
                         dry_run = dry_run or nil})
    end
    -- a room dug for it earlier: the zone once it is dug
    local rooms = site_get(DUMP_ROOM_KEY)
    if type(rooms.room) == 'table' then
        local r = rooms.room
        local state, left = dump_room_state(r)
        if state == 'dug' then
            local out = zone_inside(r.x, r.y, r.z, dry_run, 'a garbage dump in the room dug for it')
            if out.ok and not dry_run then site_put(DUMP_ROOM_KEY, {}) end
            return out
        elseif state == 'digging' then
            local cluttered = select(3, dump_room_state(r))
            return dump_fail(true, cluttered and 'items lie in the dump\'s room: they are hauled away first'
                                 or ('the dump\'s room is still being dug (%d tile(s) left)'):format(left),
                             {waiting = true, rejected = true, x = r.x, y = r.y, z = r.z, digging = true})
        end
        if not dry_run then site_put(DUMP_ROOM_KEY, {}) end      -- lost: look again
    end
    local anchors = pasture_anchors()
    if #anchors == 0 then return dump_fail(true, 'no entrance or staircase to start from') end
    local a = anchors[1]
    -- (0.105.33) the tile cache only for this search, cleared on every way
    -- out (an error in it left the module-wide cache live: every later read
    -- answered stale tiles)
    CACHE = {}
    local okf, best, on_floor = pcall(function()
        local reserved = {}
        for _, p in ipairs(open_projects(load_projects())) do table.insert(reserved, p.area) end
        local away = dump_keep_away()
        local function ok_spot(x1, y1, x2, y2, z)
            return not near_any(away, x1, y1, x2, y2, z, DUMP_KEEP_AWAY)
        end
        -- (0.105.27 fixes) no item on it (what lies in a dump zone may be removed)
        local function free(x, y, z)
            local t = info(x, y, z)
            return t and t.shape == 'FLOOR' and not t.liquid and not t.outside and not t.building and not t.items
                and not t.designated and not tile_taken(x, y, z) and walk_group(x, y, z) ~= 0
                and not inside_any(reserved, x, y, z)
        end
        -- (0.105.27 fixes) a dead end: the 16 tiles round the 3x3 open in ONE
        -- run of at most DUMP_OPENING tiles (a doorway or a corridor's end), so
        -- the dump is no through-path and no part of a hall or corridor
        local RING = {}
        for i = 0, 4 do table.insert(RING, {i - 1, -1}) end
        for i = 1, 4 do table.insert(RING, {3, i - 1}) end
        for i = 1, 4 do table.insert(RING, {3 - i, 3}) end
        for i = 1, 3 do table.insert(RING, {-1, 3 - i}) end
        local function dead_end(x, y, z)
            local open = {}
            for i, d in ipairs(RING) do
                local t = info(x + d[1], y + d[2], z)
                open[i] = t ~= nil and t.shape ~= 'WALL'
            end
            local n, runs = #RING, 0
            local total = 0
            for i = 1, n do
                if open[i] then
                    total = total + 1
                    if not open[(i - 2) % n + 1] then runs = runs + 1 end
                end
            end
            return runs == 1 and total <= DUMP_OPENING
        end
        local function dist(x, y, z) return math.max(math.abs(x + 1 - a.x), math.abs(y + 1 - a.y)) + 3 * math.abs(a.z - z) end
        -- 1) a free 3x3 of inside floor
        local best
        for z = a.z, a.z - DUMP_INSIDE_DEPTH + 1, -1 do
            for y = a.y - DUMP_INSIDE_RADIUS, a.y + DUMP_INSIDE_RADIUS do
                for x = a.x - DUMP_INSIDE_RADIUS, a.x + DUMP_INSIDE_RADIUS do
                    local d = dist(x, y, z)
                    if (not best or d < best.d) and math.max(math.abs(x + 1 - a.x), math.abs(y + 1 - a.y)) >= DUMP_KEEP_ENTRANCE
                            and ok_spot(x, y, x + 2, y + 2, z) then
                        local fits = true
                        for dy = 0, 2 do
                            for dx = 0, 2 do
                                if fits and not free(x + dx, y + dy, z) then fits = false end
                            end
                        end
                        if fits and dead_end(x, y, z) then best = {x = x, y = y, z = z, d = d} end
                    end
                end
            end
        end
        if best then return best, true end
        -- 2) a 3x3 room dug off a corridor, through a one-tile doorway
        local function solid(x, y, z) return (natural_wall(info(x, y, z))) end
        local function safe(x, y, z)
            local t = info(x, y, z)
            return t ~= nil and not t.liquid and not t.aquifer and not t.feature and not t.outside and not t.warm
        end
        local DIRS = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
        for z = a.z, a.z - DUMP_INSIDE_DEPTH + 1, -1 do
            for y = a.y - DUMP_INSIDE_RADIUS, a.y + DUMP_INSIDE_RADIUS do
                for x = a.x - DUMP_INSIDE_RADIUS, a.x + DUMP_INSIDE_RADIUS do
                    local t = info(x, y, z)
                    if t and t.shape == 'FLOOR' and not t.outside and not t.liquid and not t.building
                            and walk_group(x, y, z) ~= 0 then
                        for _, dv in ipairs(DIRS) do
                            local ex, ey = x + dv[1], y + dv[2]                 -- the doorway
                            local mx, my = ex + dv[1], ey + dv[2]               -- the room's middle of its near side
                            local rx, ry
                            if dv[1] ~= 0 then rx, ry = (dv[1] > 0) and mx or mx - 2, my - 1
                            else rx, ry = mx - 1, (dv[2] > 0) and my or my - 2 end
                            local d = dist(rx, ry, z)
                            if (not best or d < best.d) and ok_spot(rx, ry, rx + 2, ry + 2, z)
                                    and solid(ex, ey, z) and not inside_any(reserved, ex, ey, z) then
                                local fits = true
                                for yy = ry - 1, ry + 3 do
                                    for xx = rx - 1, rx + 3 do
                                        if fits then
                                            local in_room = xx >= rx and xx <= rx + 2 and yy >= ry and yy <= ry + 2
                                            if in_room then
                                                fits = solid(xx, yy, z) and not inside_any(reserved, xx, yy, z)
                                            elseif not (xx == ex and yy == ey) then
                                                fits = safe(xx, yy, z)
                                            end
                                        end
                                    end
                                end
                                if fits then best = {x = rx, y = ry, z = z, d = d, ex = ex, ey = ey} end
                            end
                        end
                    end
                end
            end
        end
        return best, false
    end)
    CACHE = nil
    if not okf then return dump_fail(true, 'the dump search failed: ' .. tostring(best):sub(1, 160)) end
    if best and on_floor then
        return zone_inside(best.x, best.y, best.z, dry_run, 'a garbage dump on free floor inside, near the entrance')
    end
    if not best then
        return dump_fail(true, 'no free floor and no solid rock for a small room near the entrance, '
            .. 'away from the meeting hall and the food')
    end
    local cells = {{x = 0, y = 0, text = 'd(3x3)'}, {x = best.ex - best.x, y = best.ey - best.y, text = 'd'}}
    local good, failed = qf_try('dig', cells, best.z, best.x, best.y, dry_run, 10)
    if not good then
        return dump_fail(true, ('the game would not dig a room for the dump at x%d y%d elevation %d')
            :format(best.x, best.y, ez(best.z)), {rejected = failed == 'dry' or nil})
    end
    if not dry_run then site_put(DUMP_ROOM_KEY, {room = {x = best.x, y = best.y, z = best.z}}) end
    return dump_out(true, best.x, best.y, best.z, 'a small room is dug for the dump near the entrance; '
        .. 'the zone follows once it is dug', {digging = true, door = {x = best.ex, y = best.ey},
                                                dry_run = dry_run or nil})
end
