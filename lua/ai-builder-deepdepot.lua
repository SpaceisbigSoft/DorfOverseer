-- ai-builder-deepdepot: the underground trade depot (the Deep mine): its plan, the wagons'
-- way down to it, its site and its digging.
--
-- A part of ai-builder, not a script of its own (r8, split out of
-- ai-builder-surface.lua when it was 126 KB): ai-builder.lua loads it into its
-- own environment right after ai-builder-keep, so every name here is
-- reqscript('ai-builder').name and the helpers defined there (info,
-- quickfort_apply, ...) are in reach. The local helpers ai-builder-wagonroad
-- uses too are handed on through DEPOT_PART_LOCALS.

if not PARTS then qerror('ai-builder-deepdepot is a part of ai-builder; run ai-builder') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-deepdepot'] = '0.105.64'   -- bumped with BRIDGE_VERSION

local info, ez = info, ez

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

-- (r8) The local helpers ai-builder-wagonroad (loaded after this file) uses too:
-- the same functions, handed on.
DEPOT_PART_LOCALS = {save_deep_depot = save_deep_depot, deep_now = deep_now, wagon_ground = wagon_ground,
                     building_blocks = building_blocks, wagon_look = wagon_look, deep_dir = deep_dir,
                     deep_depot_building = deep_depot_building, any_depot = any_depot, depot_built = depot_built,
                     deep_dig_left = deep_dig_left}
