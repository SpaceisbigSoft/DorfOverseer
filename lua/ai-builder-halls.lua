-- ai-builder-halls: the surface hall (0.105.30, construction spec 3.1): one
-- fixed building above ground, a 9x7 footprint (a 7x5 inside), used as a
-- dining hall. The Garden fort's (field_hall) stands by the fields, the
-- Merchant city's (market_hall) by the trade depot.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers of the other parts (keep_tile, depot_inside, roof_access,
-- surface_anchors, citizen_groups, ...) are in reach.
--
-- Built in stages, one action each, every stage waiting for the last one's
-- planned tiles to be built:
--   (search) -> clearing (trees felled) -> walls (Cw ring, one door, windows)
--   -> floor (Cf on soil or grass inside; the roof stair's Cu) -> roof (Cf at
--   z+1 over the inside and the windows; the stair's Cd) -> furnish (tables,
--   chairs, a statue) -> zone (a dining hall) -> done
-- Every tile placed goes on the record (tiles), so it can be taken down
-- exactly. The state lives in the save (site data 'ai-overseer/halls').
--
-- What the brain decides (Grandeur, Craftsmanship) comes in as opts:
-- {windows = true} glass windows on the long sides (when free ones lie in
-- stock), {floor = true} block floors over soil, {statue = true} a statue.
-- Nothing is decided here from the traits.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-halls'] = '0.105.45'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, ez = info, ez

HALLS_KEY = 'ai-overseer/halls'
HALL_KINDS = {field_hall = 'the hall by the fields', market_hall = 'the market hall by the depot'}
HALL_W, HALL_H = 9, 7          -- the footprint (also tried turned: 7x9)
HALL_MAX_INTERIOR = 63         -- under ai-gates LEDGE_MAX (120): a dwarf eating there seeds no second fort
assert((HALL_W - 2) * (HALL_H - 2) <= HALL_MAX_INTERIOR, 'the hall\'s inside is too big for the gates')
HALLS_MAX = 1                  -- halls a fort builds (one this round)
HALL_SECONDS = 1.5             -- the search stops here (like KEEP_COURT_SECONDS)
HALL_CANDIDATES = 400          -- sites checked in full, best first
HALL_WATER_CLEAR = 2           -- no liquid this near
HALL_CHANNEL_CLEAR = 2         -- no channel, hole or drop this near (cave-in: a floor over a channel falls)
HALL_KEEP_CLEAR = 3            -- tiles kept between the hall and the keep
HALL_DEPOT_NEAR, HALL_DEPOT_FAR = 6, 15   -- the market hall from the depot
HALL_WINDOWS_MAX = 4
HALL_TABLES = 3
HALL_SOIL = {SOIL = true, GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true, GRASS_DEAD = true}
-- what a whole hall takes in blocks before its site is known (28 walls, 35
-- floor, 35 roof, the stair): the brain's first stage check
HALL_BLOCKS_EST = 100

function halls_data()
    local d = site_get(HALLS_KEY)
    if type(d.list) ~= 'table' then d.list = {} end
    return d
end

local function save_halls(d)
    site_put(HALLS_KEY, d)
end

-- The hall still being built (or nil), and the list.
local function open_hall(d)
    for _, h in ipairs(d.list) do
        if h.stage ~= 'done' then return h end
    end
end

-- A planned (not yet built) building on the tile: buildingplan still finding
-- its materials. Tests swap it.
function hall_planned_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    return ok and b ~= nil and is_planned(b) or false
end

-- Free items of a kind (glass windows, statues). Tests swap it.
function hall_free_items(tname)
    local ok, n = pcall(function() return (count_items(tname)) end)
    return ok and n or 0
end

-- The trade depots: {{x1, y1, x2, y2, z, outside}, ...}.
function hall_depots()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
            local cx, cy = (b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2
            local t = tile_info(cx, cy, b.z)
            table.insert(out, {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z, outside = t ~= nil and t.outside})
        end
    end)
    return out
end

-- The strip between a depot and its nearest map edge: the wagons' road
-- ({x1, y1, x2, y2}, the depot's width and a tile each side).
function depot_strip(dp)
    local mw, mh = map_size()
    local d = {w = dp.x1, e = mw - 1 - dp.x2, n = dp.y1, s = mh - 1 - dp.y2}
    local best = 'w'
    for _, k in ipairs({'e', 'n', 's'}) do if d[k] < d[best] then best = k end end
    if best == 'w' then return {x1 = 0, y1 = dp.y1 - 1, x2 = dp.x1 - 1, y2 = dp.y2 + 1, z = dp.z} end
    if best == 'e' then return {x1 = dp.x2 + 1, y1 = dp.y1 - 1, x2 = mw - 1, y2 = dp.y2 + 1, z = dp.z} end
    if best == 'n' then return {x1 = dp.x1 - 1, y1 = 0, x2 = dp.x2 + 1, y2 = dp.y1 - 1, z = dp.z} end
    return {x1 = dp.x1 - 1, y1 = dp.y2 + 1, x2 = dp.x2 + 1, y2 = mh - 1, z = dp.z}
end

local function rect_dist(x1, y1, x2, y2, px, py)
    local dx = math.max(x1 - px, px - x2, 0)
    local dy = math.max(y1 - py, py - y2, 0)
    return math.max(dx, dy)
end

local function rects_dist(a, b)
    local dx = math.max(a.x1 - b.x2, b.x1 - a.x2, 0)
    local dy = math.max(a.y1 - b.y2, b.y1 - a.y2, 0)
    return math.max(dx, dy)
end

-- The ring of a rectangle (its outer tiles), corners once.
local function rect_ring(x1, y1, x2, y2)
    local out = {}
    for x = x1, x2 do
        table.insert(out, {x = x, y = y1})
        table.insert(out, {x = x, y = y2})
    end
    for y = y1 + 1, y2 - 1 do
        table.insert(out, {x = x1, y = y})
        table.insert(out, {x = x2, y = y})
    end
    return out
end

-- Channels the AI dug or planned: the deep depot road's channel tiles
-- ("x,y,z" -> true).
local function planned_channels()
    local out = {}
    pcall(function()
        local d = deep_depot_data()
        for _, t in ipairs(d and d.tiles or {}) do
            if t.r == 'h' then out[t.x .. ',' .. t.y .. ',' .. t.z] = true end
        end
    end)
    return out
end

-- The door (mid-side, toward the nearest way in) and the window slots
-- (every third non-corner tile of the long sides, never beside the door).
local function hall_door(s, anchors, kt, reach)
    local x1, y1, x2, y2, z = s.x1, s.y1, s.x2, s.y2, s.z
    local mx, my = (x1 + x2) // 2, (y1 + y2) // 2
    local sides = {
        {x = mx, y = y1, ox = 0, oy = -1}, {x = mx, y = y2, ox = 0, oy = 1},
        {x = x1, y = my, ox = -1, oy = 0}, {x = x2, y = my, ox = 1, oy = 0},
    }
    for _, sd in ipairs(sides) do
        sd.d = math.huge
        for _, a in ipairs(anchors) do
            local d = math.max(math.abs(sd.x + sd.ox - a.x), math.abs(sd.y + sd.oy - a.y)) + 3 * math.abs(a.z - z)
            if d < sd.d then sd.d = d end
        end
    end
    table.sort(sides, function(a, b)
        if a.d ~= b.d then return a.d < b.d end
        if a.y ~= b.y then return a.y > b.y end
        return a.x < b.x
    end)
    for _, sd in ipairs(sides) do
        local ox, oy = sd.x + sd.ox, sd.y + sd.oy
        local outer = info(ox, oy, z)
        if kt(sd.x, sd.y, z) == 'ground' and outer and GROUND[outer.shape] and not outer.building
                and not outer.liquid and reach(ox, oy, z) then
            return {x = sd.x, y = sd.y}
        end
    end
end

local function window_slots(s, door)
    local out = {}
    local long_x = (s.x2 - s.x1) >= (s.y2 - s.y1)
    local len = long_x and (s.x2 - s.x1) or (s.y2 - s.y1)
    for _, side in ipairs({1, 2}) do
        for off = 3, len - 1, 3 do
            local x, y
            if long_x then x, y = s.x1 + off, side == 1 and s.y1 or s.y2
            else x, y = side == 1 and s.x1 or s.x2, s.y1 + off end
            if not (door and math.abs(door.x - x) + math.abs(door.y - y) <= 1) and #out < HALL_WINDOWS_MAX then
                table.insert(out, {x = x, y = y})
            end
        end
    end
    return out
end

-- A site for a hall of this kind: {x1, y1, x2, y2, z, door, windows,
-- trees, kind} or nil and why (and true when the search was cut short).
function find_hall_site(kind)
    if not HALL_KINDS[kind] then return nil, 'unknown hall kind: ' .. tostring(kind) end
    local anchors = surface_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to build the hall near' end
    local groups = citizen_groups()
    local any_group = next(groups) == nil
    local function reach(x, y, z)
        local g = walk_group(x, y, z)
        return g ~= 0 and (any_group or groups[g] == true)
    end
    local cache = {}
    local function kt(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = keep_tile(x, y, z) or false; cache[k] = v end
        return v
    end
    local function open_above(x, y, z)
        local t = info(x, y, z + 1)
        return t ~= nil and t.shape == 'EMPTY'
    end
    local farms = kind == 'field_hall' and surface_farm_spots() or {}
    local depots = hall_depots()
    local market_depots = {}
    for _, dp in ipairs(depots) do if dp.outside then table.insert(market_depots, dp) end end
    if kind == 'market_hall' and #market_depots == 0 then
        return nil, 'no trade depot under the sky to build the market hall by'
    end
    local strips = {}
    for _, dp in ipairs(depots) do table.insert(strips, depot_strip(dp)) end
    local avoid = {}                      -- the keep and the other halls, with room kept round them
    local k = keep_data()
    if k then table.insert(avoid, {x1 = k.x - k.r, y1 = k.y - k.r, x2 = k.x + k.r, y2 = k.y + k.r, z = k.z}) end
    for _, h in ipairs(halls_data().list) do
        table.insert(avoid, {x1 = h.x1, y1 = h.y1, x2 = h.x2, y2 = h.y2, z = h.z})
    end
    local channels = planned_channels()
    local mw, mh = map_size()
    -- (0.105.33) the underground depot road's mouth, where the wagons turn
    -- in (the keep's court keeps clear of it too)
    local okm, mouth = pcall(deep_depot_mouth)
    mouth = okm and type(mouth) == 'table' and mouth or {}

    local function score_of(cx, cy, z)
        local best = math.huge
        if kind == 'market_hall' then
            for _, dp in ipairs(market_depots) do
                local d = math.max(math.abs(cx - (dp.x1 + dp.x2) // 2), math.abs(cy - (dp.y1 + dp.y2) // 2))
                    + 3 * math.abs(z - dp.z)
                if d < best then best = d end
            end
            return best
        end
        for _, f in ipairs(farms) do
            local d = math.max(math.abs(cx - f.x), math.abs(cy - f.y)) + 3 * math.abs(z - f.z)
            if d < best then best = d end
        end
        if best == math.huge then
            for _, a in ipairs(anchors) do
                local d = math.max(math.abs(cx - a.x), math.abs(cy - a.y)) + 3 * math.abs(z - a.z)
                if d < best then best = d end
            end
        end
        return best
    end

    -- the rules a rectangle meets before its tiles are read
    local function placed_ok(s)
        if s.x1 < 2 or s.y1 < 2 or s.x2 > mw - 3 or s.y2 > mh - 3 then return false, 'the map\'s edge' end
        local within = false
        for _, a in ipairs(anchors) do
            local d = rect_dist(s.x1, s.y1, s.x2, s.y2, a.x, a.y)
            if math.abs(a.z - s.z) <= 1 and d <= KEEP_COURT_CLEAR then
                return false, 'too near the way in (the wagons\' road)'
            end
            if d <= KEEP_COURT_REACH and math.abs(a.z - s.z) <= KEEP_COURT_LEVELS + 1 then within = true end
        end
        if not within then return false, 'too far from the way in' end
        for _, r in ipairs(avoid) do
            if math.abs(r.z - s.z) <= 1 and rects_dist(s, r) <= HALL_KEEP_CLEAR then
                return false, 'too near the keep or another hall'
            end
        end
        for _, dp in ipairs(depots) do
            if dp.z == s.z and rects_dist(s, dp) == 0 then return false, 'the trade depot is there' end
        end
        for _, m in ipairs(mouth) do
            if math.abs(m.z - s.z) <= 1 and rect_dist(s.x1, s.y1, s.x2, s.y2, m.x, m.y) <= 1 then
                return false, 'the underground depot\'s wagon road'
            end
        end
        for _, st in ipairs(strips) do
            if rects_dist(s, st) == 0 and math.abs(s.z - st.z) <= 1 then
                return false, 'the wagons\' road between the depot and the map\'s edge'
            end
        end
        if kind == 'market_hall' then
            local near = false
            for _, dp in ipairs(market_depots) do
                local d = rects_dist(s, dp)
                if dp.z == s.z and d >= HALL_DEPOT_NEAR and d <= HALL_DEPOT_FAR then near = true end
            end
            if not near then return false, ('not %d-%d tiles from the depot'):format(HALL_DEPOT_NEAR, HALL_DEPOT_FAR) end
        end
        return true
    end

    -- the full look: ground, sky, water, channels, the door
    local function full(s)
        local trees, ground = {}, 0
        for y = s.y1, s.y2 do
            for x = s.x1, s.x2 do
                local v = kt(x, y, s.z)
                if v == 'tree' then
                    table.insert(trees, {x = x, y = y, z = s.z})
                    if #trees > SURFACE_MAX_TREES then return nil, 'too many trees to fell' end
                elseif v == 'ground' then
                    if not open_above(x, y, s.z) then return nil, 'no open sky above the ground' end
                    ground = ground + 1
                else
                    return nil, v == 'planned' and 'something being built there'
                        or ('%s inside the footprint'):format(keep_tile_why(x, y, s.z))
                end
            end
        end
        if ground == 0 then return nil, 'no open ground' end
        local cw = math.max(HALL_WATER_CLEAR, HALL_CHANNEL_CLEAR)
        for y = s.y1 - cw, s.y2 + cw do
            for x = s.x1 - cw, s.x2 + cw do
                local inside = x >= s.x1 and x <= s.x2 and y >= s.y1 and y <= s.y2
                if not inside then
                    local t = info(x, y, s.z)
                    local wd = rect_dist(s.x1, s.y1, s.x2, s.y2, x, y)
                    if t and t.liquid and wd <= HALL_WATER_CLEAR then return nil, 'water within 2 tiles', 2 end
                    if wd <= HALL_CHANNEL_CLEAR then
                        if channels[x .. ',' .. y .. ',' .. s.z] then return nil, 'a channel being dug nearby', 2 end
                        if t and (t.shape == 'EMPTY' or t.shape == 'RAMP_TOP' or t.shape == 'RAMP'
                                  or (t.designated and not is_tree(t))) then
                            return nil, 'a channel, a hole or a slope within 2 tiles (cave-in)', 2
                        end
                    end
                end
            end
        end
        local door = hall_door(s, anchors, kt, reach)
        if not door then return nil, 'no side has open ground the dwarves can reach for a door', 2 end
        return {x1 = s.x1, y1 = s.y1, x2 = s.x2, y2 = s.y2, z = s.z, door = door, trees = trees,
                windows = window_slots(s, door), kind = kind}
    end

    -- candidates: the centres of open, reachable ground under the sky
    local cands, seen = {}, {}
    local deadline = os.clock() + HALL_SECONDS
    local cut = false
    local shapes = {{HALL_W, HALL_H}, {HALL_H, HALL_W}}
    local last = 'no open, flat ground the dwarves can reach within ' .. KEEP_COURT_REACH .. ' tiles of the way in'
    local nearest_why
    for _, a in ipairs(anchors) do
        for z = a.z - KEEP_COURT_LEVELS, a.z + 1 do
            for y = a.y - KEEP_COURT_REACH, a.y + KEEP_COURT_REACH do
                if os.clock() > deadline then cut = true break end
                for x = a.x - KEEP_COURT_REACH, a.x + KEEP_COURT_REACH do
                    local key = (z * 4096 + y) * 4096 + x
                    if not seen[key] and kt(x, y, z) == 'ground' and open_above(x, y, z) and reach(x, y, z) then
                        seen[key] = true
                        for _, wh in ipairs(shapes) do
                            local s = {x1 = x - wh[1] // 2, y1 = y - wh[2] // 2, z = z}
                            s.x2, s.y2 = s.x1 + wh[1] - 1, s.y1 + wh[2] - 1
                            local ok, why = placed_ok(s)
                            if ok then
                                s.score = score_of(x, y, z)
                                table.insert(cands, s)
                            else
                                nearest_why = nearest_why or why
                            end
                        end
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
        if p.y1 ~= q.y1 then return p.y1 < q.y1 end
        if p.x1 ~= q.x1 then return p.x1 < q.x1 end
        return (p.x2 - p.x1) > (q.x2 - q.x1)
    end)
    if #cands == 0 and nearest_why then last = nearest_why end
    -- (the reason told: the best site's, else one whose ground was fine)
    local best, best_score, last_rank = nil, nil, 0
    for i, c in ipairs(cands) do
        if i > HALL_CANDIDATES or os.clock() > deadline + HALL_SECONDS then cut = true break end
        if best_score and c.score >= best_score then break end
        local site, why, rank = full(c)
        if site then
            local score = c.score + SURFACE_TREE_COST * #site.trees
            if not best_score or score < best_score then best, best_score = site, score end
        elseif (rank or 1) > last_rank then
            last, last_rank = why, rank or 1
        end
    end
    if best then return best end
    local why = ('no site for %s: %s'):format(HALL_KINDS[kind], last)
    if cut then return nil, 'search cut short: ' .. why, true end
    return nil, why
end

-- The tiles of a hall: {ring, inside, door, windows}.
local function hall_inside(h)
    local out = {}
    for y = h.y1 + 1, h.y2 - 1 do
        for x = h.x1 + 1, h.x2 - 1 do table.insert(out, {x = x, y = y}) end
    end
    return out
end

local function is_at(list, x, y)
    for _, p in ipairs(list or {}) do if p.x == x and p.y == y then return true end end
    return false
end

-- What a planned tile is, by what its tile now shows: 'built', 'planned' or 'none'.
local BUILT_SHAPE = {Cw = 'WALL', Cf = 'FLOOR', Cu = 'STAIR_UP', Cd = 'STAIR_DOWN'}
local function piece_state(p)
    local t = tile_info(p.x, p.y, p.z)
    if not t then return 'none' end
    local want = BUILT_SHAPE[p.t]
    if want then
        -- a construction waiting is a building on the tile; built, it is the tile
        if t.building then return 'planned' end
        return t.shape == want and 'built' or 'none'
    end
    -- a building (door, window, table, chair, statue)
    if hall_planned_at(p.x, p.y, p.z) then return 'planned' end
    return t.building and 'built' or 'none'
end

-- How far a hall has got: counts by stage. `h` a record (else the open one).
local function hall_counts(h)
    local c = {walls_planned = 0, walls_left = 0, floor_planned = 0, stair_planned = 0, roof_planned = 0,
               roof_left = 0, furniture_planned = 0, doors_planned = 0, windows_planned = 0, trees_left = 0}
    if h.stage == 'clearing' then
        for y = h.y1, h.y2 do
            for x = h.x1, h.x2 do
                if is_tree(tile_info(x, y, h.z)) then c.trees_left = c.trees_left + 1 end
            end
        end
    end
    for _, p in ipairs(h.tiles or {}) do
        local s = piece_state(p)
        if p.t == 'Cw' then
            if s == 'planned' then c.walls_planned = c.walls_planned + 1 end
            if s ~= 'built' then c.walls_left = c.walls_left + 1 end
        elseif p.t == 'Cf' and p.z == h.z then
            -- (once furnished, a table stands on a built floor: not counted)
            if s == 'planned' and h.stage == 'floor' then c.floor_planned = c.floor_planned + 1 end
        elseif p.t == 'Cf' or p.t == 'Cd' then
            if s == 'planned' then c.roof_planned = c.roof_planned + 1 end
        elseif p.t == 'Cu' then
            if s == 'planned' and h.stage == 'floor' then c.stair_planned = c.stair_planned + 1 end
        elseif p.t == 'd' then
            if s == 'planned' then c.doors_planned = c.doors_planned + 1 end
        elseif p.t == 'y' then
            if s == 'planned' then c.windows_planned = c.windows_planned + 1 end
        else
            if s == 'planned' then c.furniture_planned = c.furniture_planned + 1 end
        end
    end
    if h.stage == 'roof' or h.stage == 'furnish' or h.stage == 'done' then
        for _, p in ipairs(hall_inside(h)) do
            local t = tile_info(p.x, p.y, h.z + 1)
            if t and t.shape == 'EMPTY' and not t.building then c.roof_left = c.roof_left + 1 end
        end
    end
    return c
end

-- The blocks a hall still takes: walls not standing, the inside's soil
-- floor (when asked for), the roof and the stair.
local STAGE_ORDER = {clearing = 1, walls = 2, floor = 3, roof = 4, furnish = 5, zone = 6, done = 7}
local function hall_blocks(h)
    local n, by = 0, {walls = 0, floor = 0, roof = 0}
    local placed = {}
    for _, p in ipairs(h.tiles or {}) do placed[p.x .. ',' .. p.y .. ',' .. p.z] = p end
    local order = STAGE_ORDER[h.stage] or 1
    if order <= 2 then
        for _, p in ipairs(rect_ring(h.x1, h.y1, h.x2, h.y2)) do
            local t = tile_info(p.x, p.y, h.z)
            if not (h.door and p.x == h.door.x and p.y == h.door.y) and not is_at(h.windows_placed, p.x, p.y)
                    and not (t and t.shape == 'WALL' and not is_tree(t)) then
                by.walls = by.walls + 1
            end
        end
    end
    if order <= 3 and not (h.opts and h.opts.floor == false) then
        for _, p in ipairs(hall_inside(h)) do
            local t = tile_info(p.x, p.y, h.z)
            if t and t.shape == 'FLOOR' and HALL_SOIL[t.material] then by.floor = by.floor + 1 end
        end
    end
    if order <= 4 then
        for _, p in ipairs(hall_inside(h)) do
            local t = tile_info(p.x, p.y, h.z + 1)
            if not t or t.shape == 'EMPTY' then by.roof = by.roof + 1 end
        end
        by.roof = by.roof + #(h.windows_placed or {}) + (ROOF_STAIR and 2 or 0)
    end
    n = by.walls + by.floor + by.roof
    return n, by
end

-- The report's view of the hall being built (else the last one built):
-- {kind, stage, x1, y1, x2, y2, elevation, walls_planned, walls_left,
-- floor_planned, stair_planned, roof_planned, roof_left, furniture_planned,
-- trees_left, blocks_needed, next_blocks, halls}, or nil with no hall.
function halls_status()
    local d = halls_data()
    local h = open_hall(d) or d.list[#d.list]
    if not h then return nil end
    local out = hall_counts(h)
    out.kind, out.stage = h.kind, h.stage
    out.x1, out.y1, out.x2, out.y2 = h.x1, h.y1, h.x2, h.y2
    out.elevation = ez(h.z)
    out.door = h.door
    out.windows = #(h.windows_placed or {})
    out.halls = #d.list
    if h.stage ~= 'done' then
        local n, by = hall_blocks(h)
        out.blocks_needed = n
        local st = ROOF_STAIR and 1 or 0
        local next_of = {clearing = by.walls, walls = by.floor + st, floor = math.max(by.roof - st, 0), roof = 0}
        out.next_blocks = next_of[h.stage] or 0
    else
        out.blocks_needed, out.next_blocks = 0, 0
    end
    return out
end

-- Quickfort build at one level; ok, count or why.
local function hall_apply(mode, cells, z, what, dry_run)
    if #cells == 0 then return 0 end
    local good, failed, res = qf_try(mode, cells, z, 0, 0, dry_run)
    if failed == 'dry' then return nil, ('the game would not place %s'):format(what) end
    if not good then return nil, ('the game refused %s'):format(what) end
    return stat(res, mode .. '_designated')
end

local function record(h, cells, z)
    h.tiles = h.tiles or {}
    for _, c in ipairs(cells) do table.insert(h.tiles, {x = c.x, y = c.y, z = z, t = c.text}) end
end

-- The furniture spots: tables in the middle row (or column), chairs beside
-- them, a statue in a corner; never on the door's inside tile, the stair or
-- the window's inside.
local function furniture_cells(h, statue)
    local blocked = {}
    local function block(x, y) blocked[x .. ',' .. y] = true end
    if h.door then
        local ix = h.door.x == h.x1 and h.x1 + 1 or h.door.x == h.x2 and h.x2 - 1 or h.door.x
        local iy = h.door.y == h.y1 and h.y1 + 1 or h.door.y == h.y2 and h.y2 - 1 or h.door.y
        block(ix, iy)
    end
    if h.stair then block(h.stair.x, h.stair.y) end
    local function free(x, y)
        if blocked[x .. ',' .. y] then return false end
        local t = tile_info(x, y, h.z)
        return t ~= nil and not t.building and (GROUND[t.shape] or t.shape == 'FLOOR')
    end
    local cells = {}
    local long_x = (h.x2 - h.x1) >= (h.y2 - h.y1)
    local iw = long_x and (h.x2 - h.x1 - 1) or (h.y2 - h.y1 - 1)
    local ih = long_x and (h.y2 - h.y1 - 1) or (h.x2 - h.x1 - 1)
    local function at(u, v)          -- u along the long side, v across (both 0-based inside)
        if long_x then return h.x1 + 1 + u, h.y1 + 1 + v end
        return h.x1 + 1 + v, h.y1 + 1 + u
    end
    local mid = ih // 2
    local placed = 0
    for u = 1, iw - 2, 2 do
        if placed >= HALL_TABLES then break end
        local tx, ty = at(u, mid)
        local cx, cy = at(u, mid + 1)
        if not free(cx, cy) then cx, cy = at(u, mid - 1) end
        if free(tx, ty) and free(cx, cy) then
            table.insert(cells, {x = tx, y = ty, text = 't'})
            table.insert(cells, {x = cx, y = cy, text = 'c'})
            block(tx, ty); block(cx, cy)
            placed = placed + 1
        end
    end
    if statue then
        for _, uv in ipairs({{0, 0}, {iw - 1, 0}, {0, ih - 1}, {iw - 1, ih - 1}}) do
            local sx, sy = at(uv[1], uv[2])
            if free(sx, sy) then table.insert(cells, {x = sx, y = sy, text = 's'}) break end
        end
    end
    return cells
end

-- One step of a hall of this kind (see the top). opts: {windows, floor,
-- statue} (the brain's, by the sliders).
function place_hall(kind, dry_run, opts)
    OFFSET = elevation_offset()
    opts = type(opts) == 'table' and opts or {}
    if not HALL_KINDS[kind] then
        return {ok = false, rejected = true, error = 'unknown hall kind: ' .. tostring(kind)}
    end
    local d = halls_data()
    local h = open_hall(d)
    if h and h.kind ~= kind then
        return {ok = false, rejected = true, error = ('%s is being built first'):format(HALL_KINDS[h.kind] or 'a hall')}
    end
    if not h then
        if #d.list >= HALLS_MAX then
            return {ok = false, rejected = true, done = true, error = 'the fort has its hall'}
        end
        local site, why, cut = find_hall_site(kind)
        if not site then return {ok = false, error = why, timed_out = cut or nil} end
        h = {kind = kind, x1 = site.x1, y1 = site.y1, x2 = site.x2, y2 = site.y2, z = site.z, door = site.door,
             windows = site.windows, stage = 'clearing', tiles = {}}
        if #site.trees > 0 then
            local out = {ok = true, kind = kind, stage = 'clearing', clearing = true, trees = #site.trees,
                         x1 = h.x1, y1 = h.y1, x2 = h.x2, y2 = h.y2, elevation = ez(h.z), dry_run = dry_run or nil}
            if dry_run then return out end
            for _, t in ipairs(site.trees) do fell_tree(t.x, t.y, t.z) end
            table.insert(d.list, h)
            save_halls(d)
            return out
        end
        if not dry_run then table.insert(d.list, h) end   -- (saved only when a stage is placed)
    end
    local function save() save_halls(d) end
    local function forget()
        if dry_run then return end
        for i, x in ipairs(d.list) do if x == h then table.remove(d.list, i) break end end
        save_halls(d)
    end
    local function out(t)
        t.ok = t.ok ~= false
        t.kind, t.x1, t.y1, t.x2, t.y2 = kind, h.x1, h.y1, h.x2, h.y2
        t.elevation = t.elevation or ez(h.z)
        t.dry_run = dry_run or nil
        return t
    end
    local function wait(stage, n, what)
        return out({ok = false, rejected = true, waiting = true, stage = stage, left = n,
                    error = ('%s: %d %s still to build'):format(HALL_KINDS[kind], n, what)})
    end

    if h.stage == 'clearing' then
        local trees = {}
        for y = h.y1, h.y2 do
            for x = h.x1, h.x2 do
                local v = keep_tile(x, y, h.z)
                if v == 'tree' then table.insert(trees, {x = x, y = y})
                elseif v ~= 'ground' then
                    forget()
                    return out({ok = false, error = ('something was put in the way of %s: looking again next time')
                        :format(HALL_KINDS[kind])})
                end
            end
        end
        if #trees > 0 then
            if not dry_run then for _, t in ipairs(trees) do fell_tree(t.x, t.y, h.z) end end
            return out({ok = false, rejected = true, waiting = true, stage = 'clearing', trees = #trees,
                        error = ('the dwarves are still felling %d tree(s) for %s'):format(#trees, HALL_KINDS[kind])})
        end
        -- the walls, the door and the windows (glass ones lying free)
        local windows = {}
        if opts.windows then
            local free = hall_free_items('WINDOW')
            for _, w in ipairs(h.windows or {}) do
                if #windows < free then table.insert(windows, w) end
            end
        end
        local cells = {}
        for _, p in ipairs(rect_ring(h.x1, h.y1, h.x2, h.y2)) do
            local text = 'Cw'
            if p.x == h.door.x and p.y == h.door.y then text = 'd'
            elseif is_at(windows, p.x, p.y) then text = 'y' end
            table.insert(cells, {x = p.x, y = p.y, text = text})
        end
        local n, why = hall_apply('build', cells, h.z, 'the hall\'s walls', dry_run)
        if not n and #windows > 0 then            -- (windows [verify]: a refusal drops them, not the walls)
            for _, c in ipairs(cells) do if c.text == 'y' then c.text = 'Cw' end end
            windows = {}
            n, why = hall_apply('build', cells, h.z, 'the hall\'s walls', dry_run)
        end
        if not n then forget() return out({ok = false, error = why}) end
        if not dry_run then
            h.stage, h.windows_placed, h.opts = 'walls', windows, {floor = opts.floor == true, statue = opts.statue == true}
            record(h, cells, h.z)
            save()
        end
        return out({stage = 'walls', walls = n, door = h.door, windows = #windows})
    end

    local c = hall_counts(h)
    if h.stage == 'walls' then
        if c.walls_planned > 0 then return wait('walls', c.walls_planned, 'wall tile(s)') end
        -- the floor (blocks over soil and grass, asked for) and the roof stair's lower half
        local floor = opts.floor == true or (opts.floor == nil and h.opts and h.opts.floor)
        local s = roof_access(h.x1 + 1, h.y1 + 1, h.x2 - 1, h.y2 - 1, h.z, h.door)
        local cells = {}
        if floor then
            for _, p in ipairs(hall_inside(h)) do
                local t = tile_info(p.x, p.y, h.z)
                if t and t.shape == 'FLOOR' and HALL_SOIL[t.material] and not t.building
                        and not (s and s.x == p.x and s.y == p.y) then
                    table.insert(cells, {x = p.x, y = p.y, text = 'Cf'})
                end
            end
        end
        local nf, why = hall_apply('build', cells, h.z, 'the hall\'s floor', dry_run)
        if not nf then return out({ok = false, error = why}) end
        local stair
        if s then                                -- ([verify] Cu; refused: the roof goes on without it)
            local good = qf_try('build', {{x = s.x, y = s.y, text = 'Cu'}}, h.z, 0, 0, dry_run)
            if good then stair = {x = s.x, y = s.y} end
        end
        if not dry_run then
            h.stage, h.stair = 'floor', stair
            record(h, cells, h.z)
            if stair then record(h, {{x = stair.x, y = stair.y, text = 'Cu'}}, h.z) end
            save()
        end
        return out({stage = 'floor', floor = nf, stair = stair})
    end

    if h.stage == 'floor' then
        if c.floor_planned + c.stair_planned > 0 then
            return wait('floor', c.floor_planned + c.stair_planned, 'floor or stair tile(s)')
        end
        local built_stair = h.stair and stair_shape(h.stair.x, h.stair.y, h.z) == 'STAIR_UP'
        local cells, stair_cell = {}, nil
        local over = hall_inside(h)
        for _, w in ipairs(h.windows_placed or {}) do table.insert(over, w) end
        for _, p in ipairs(over) do
            local t = tile_info(p.x, p.y, h.z + 1)
            if t and t.shape == 'EMPTY' and not t.building then
                local is_stair = built_stair and p.x == h.stair.x and p.y == h.stair.y
                table.insert(cells, {x = p.x, y = p.y, text = is_stair and 'Cd' or 'Cf'})
                if is_stair then stair_cell = cells[#cells] end
            end
        end
        local n, why = hall_apply('build', cells, h.z + 1, 'the hall\'s roof', dry_run)
        if not n and stair_cell then
            stair_cell.text, stair_cell = 'Cf', nil
            n, why = hall_apply('build', cells, h.z + 1, 'the hall\'s roof', dry_run)
        end
        if not n then return out({ok = false, error = why}) end
        if not dry_run then
            h.stage = 'roof'
            record(h, cells, h.z + 1)
            save()
        end
        return out({stage = 'roof', roof = n, stair = stair_cell and true or nil, elevation = ez(h.z + 1)})
    end

    if h.stage == 'roof' then
        if c.roof_planned > 0 then return wait('roof', c.roof_planned, 'roof tile(s)') end
        local statue = (opts.statue == true or (opts.statue == nil and h.opts and h.opts.statue))
            and hall_free_items('STATUE') > 0
        local cells = furniture_cells(h, statue)
        local n, why = hall_apply('build', cells, h.z, 'the hall\'s tables and chairs', dry_run)
        if not n then return out({ok = false, error = why}) end
        if not dry_run then
            h.stage = 'furnish'
            record(h, cells, h.z)
            save()
        end
        local tables, statues = 0, 0
        for _, cl in ipairs(cells) do
            if cl.text == 't' then tables = tables + 1 elseif cl.text == 's' then statues = statues + 1 end
        end
        return out({stage = 'furnish', tables = tables, chairs = tables, statue = statues > 0 or nil})
    end

    if h.stage == 'furnish' then
        if c.furniture_planned > 0 then return wait('furnish', c.furniture_planned, 'table(s), chair(s) or statue') end
        local iw, ih = h.x2 - h.x1 - 1, h.y2 - h.y1 - 1
        local cell = {{x = h.x1 + 1, y = h.y1 + 1, text = ('h(%dx%d)'):format(iw, ih)}}
        local good, failed = qf_try('zone', cell, h.z, 0, 0, dry_run)
        if not good then
            return out({ok = false, rejected = failed == 'dry' or nil, error = 'the game refused the hall\'s dining zone'})
        end
        if not dry_run then
            h.stage, h.zone = 'done', {x = h.x1 + 1, y = h.y1 + 1, w = iw, h = ih}
            save()
        end
        return out({stage = 'zone', zone = true, done = true})
    end

    return out({ok = false, rejected = true, done = true, stage = 'done', error = ('%s is finished'):format(HALL_KINDS[kind])})
end
