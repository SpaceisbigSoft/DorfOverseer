-- ai-builder-sites: where a new level goes: the site checks, the staircases, the site search; the
-- fort scan area and the survey; new stairwells.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-sites'] = '0.105.39'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, has, add, overlaps, ez = info, has, add, overlaps, ez

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
        -- (0.105.40b) the dig guard: never raw adamantine, the spire or the underworld, nor beside them
        local deep = dig_forbidden(ax + x, ay + y, z)
        if deep then return false, ('%s at x%d y%d z%d (left alone: it guards the underworld)'):format(deep, ax + x, ay + y, ez(z)) end
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

-- Can the staircase at (sx, sy) be extended from its bottom (zb) down to z?
-- Each new stair tile and its 8 neighbours must be untouched natural wall.
-- (0.105.33) all_last: the 8 neighbours on z are read too (a new stairwell
-- has no hub check on its bottom level to cover them)
function check_extension(sx, sy, zb, z, all_last)
    for zz = zb - 1, z, -1 do
        for dx = -1, 1 do
            for dy = -1, 1 do
                -- on the target level, the hub check covers the neighbours
                if zz ~= z or all_last or (dx == 0 and dy == 0) then
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
function entry_point(L, d)
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
function corridor_path(stair, d, first, corridor, side)
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

function offset_sites(L, stair, z, reserved, try, dirs, grammar)
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
                                           -- (0.105.33) the new corridor alone (Spacing's
                                           -- scorecard line: walked tiles aren't dug)
                                           new_corridor = corridor,
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
function plan_band(plan)
    if type(plan) ~= 'table' then return nil end
    local lo, hi = math.tointeger(plan.elev_lo), math.tointeger(plan.elev_hi)
    if not lo or not hi or lo > hi then return nil end
    local t = math.tointeger(plan.elev_target) or (lo + (hi - lo) // 2)
    local ext = math.tointeger(plan.extend)
    return {lo = lo - OFFSET, hi = hi - OFFSET, target = t - OFFSET,
            extend = ext and math.max(0, math.min(30, ext)) or nil}
end

-- Walking areas the citizens are in (empty when unknown).
function citizen_groups()
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
function stair_levels(stair, band, only_band, may_extend)
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
            -- (0.105.14) a deep fort's plan says how far (DEEP_EXTEND); others PLAN_EXTEND
            if may_extend == nil or z >= stair.z_bottom - (band.extend or PLAN_EXTEND) then table.insert(near, z) end
        end
        band_part(near, true)
    end
    if not only_band then
        for _, z in ipairs(through) do if not inside(z) then table.insert(out, {z = z, extend = false}) end end
        for _, z in ipairs(below) do if not inside(z) then table.insert(out, {z = z, extend = true}) end end
    end
    return out
end

function choose_site(L, stairs, reserved, plan, ceil_z)
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
                    -- (0.105.23) above the ceiling (at or above the surface, the Deep mine): never
                    if ceil_z and z > ceil_z then goto continue end
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
                                     extra = {}, area = area, stair = stair, corridor = 0, new_corridor = 0}
                            return
                        end
                        note('below', why, z)
                    else
                        if ok then
                            found = {z = z, extend = false, anchor = {x = stair.x, y = stair.y},
                                     extra = {}, area = area, stair = stair, corridor = 0, new_corridor = 0}
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
    if ceil_z then head = head .. (', none above elevation %d (under the surface only)'):format(ez(ceil_z)) end
    return nil, head .. ' (' .. table.concat(tried, '; ') .. ')'
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

function inside_any(areas, x, y, z)
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

local stairwell_search

function dig_stairwell(params, dry_run)
    OFFSET = elevation_offset()
    -- (0.105.33) the tile cache only for this search, cleared on every way
    -- out (it was left live: every later info() read answered stale tiles)
    CACHE = {}
    local ok, r = pcall(stairwell_search, params, dry_run)
    CACHE = nil
    if not ok then return {ok = false, error = 'the stairwell search failed: ' .. tostring(r):sub(1, 160)} end
    return r
end

stairwell_search = function(params, dry_run)
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
                        local okx, w = check_extension(x, y, z, lo_z, true)
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
