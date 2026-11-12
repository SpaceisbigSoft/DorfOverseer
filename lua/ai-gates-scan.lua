-- ai-gates-scan: mapping the inside (explore, the openings and what seals them), the War-hold's
-- gatehouse plan, find_entrances, the levers' roles and scan().
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-scan'] = '0.105.41'   -- (0.105.26) bumped with BRIDGE_VERSION

local key, unkey, STAIR_UP, STAIR_DOWN = key, unkey, STAIR_UP, STAIR_DOWN   -- (13e) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- Mapping the inside (pure: uses tile() only)
---------------------------------------------------------------------------

cache = nil   -- (13e) a module name: the parts that read the map fresh reset it
local function T(x, y, z)
    local k = key(x, y, z)
    local v = cache[k]
    if v == nil then
        v = tile(x, y, z) or false
        cache[k] = v
    end
    return v or nil
end

-- (canopy: a surface tile DF counts as not outside only because a tree's
-- crown is over it: the surface, not the fort; 0.39.0 walled trees in)
local function interior(t)
    return t and t.walk and not t.outside and not t.canopy and not t.feature and not t.special and not t.hidden
end


-- Walking moves from (x, y, z): the 8 neighbours, stairs, ramps.
local function moves(x, y, z, t, fn)
    for dx = -1, 1 do
        for dy = -1, 1 do
            if dx ~= 0 or dy ~= 0 then fn(x + dx, y + dy, z) end
        end
    end
    if STAIR_UP[t.shape] then
        local a = T(x, y, z + 1)
        if a and STAIR_DOWN[a.shape] then fn(x, y, z + 1) end
    end
    if STAIR_DOWN[t.shape] then
        local b = T(x, y, z - 1)
        if b and STAIR_UP[b.shape] then fn(x, y, z - 1) end
    end
    for dx = -1, 1 do
        for dy = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                if t.shape == 'RAMP' then fn(x + dx, y + dy, z + 1) end
                local below = T(x + dx, y + dy, z - 1)
                if below and below.shape == 'RAMP' then fn(x + dx, y + dy, z - 1) end
            end
        end
    end
end

-- (0.105.40, 13e) The walks below (explore, seals, reaches_edge, the porch)
-- take each tile's neighbours from moves_k: the same moves in the same order
-- as moves(), with each neighbour's key handed over (worked out from the
-- tile's own), and the tiles read through the same cache as T: one call a
-- neighbour instead of three or four.
local KZ, KY = 4096 * 4096, 4096

-- T for a tile whose key is known (key(x, y, z) == k)
local function TK(k, x, y, z)
    local v = cache[k]
    if v == nil then
        v = tile(x, y, z) or false
        cache[k] = v
    end
    return v or nil
end

-- Is the tile below (key bk) a ramp? From the cache when it was read, else
-- tile_is_ramp (kept apart, by the cache it belongs to: cache itself holds
-- only tile()'s answers), or tile() when a test has its own in place.
local RAMPS, RAMPS_OF = nil, nil
local function ramp_below(bk, x, y, z)
    if tile ~= GAME_TILE then
        local b = TK(bk, x, y, z)
        return b and b.shape == 'RAMP'
    end
    if RAMPS_OF ~= cache then RAMPS, RAMPS_OF = {}, cache end
    local r = RAMPS[bk]
    if r == nil then
        r = tile_is_ramp(x, y, z)
        RAMPS[bk] = r
    end
    return r
end

local function moves_k(k, x, y, z, t, fn)
    local c = cache
    fn(k - KY - 1, x - 1, y - 1, z)
    fn(k - 1, x - 1, y, z)
    fn(k + KY - 1, x - 1, y + 1, z)
    fn(k - KY, x, y - 1, z)
    fn(k + KY, x, y + 1, z)
    fn(k - KY + 1, x + 1, y - 1, z)
    fn(k + 1, x + 1, y, z)
    fn(k + KY + 1, x + 1, y + 1, z)
    local shape = t.shape
    if STAIR_UP[shape] then
        local a = TK(k + KZ, x, y, z + 1)
        if a and STAIR_DOWN[a.shape] then fn(k + KZ, x, y, z + 1) end
    end
    if STAIR_DOWN[shape] then
        local b = TK(k - KZ, x, y, z - 1)
        if b and STAIR_UP[b.shape] then fn(k - KZ, x, y, z - 1) end
    end
    if shape == 'RAMP' then
        -- (each neighbour: up its ramp, then down to a ramp below, as moves() goes)
        for dx = -1, 1 do
            for dy = -1, 1 do
                if dx ~= 0 or dy ~= 0 then
                    local d = dy * KY + dx
                    fn(k + KZ + d, x + dx, y + dy, z + 1)
                    local bk = k - KZ + d
                    local below, r = c[bk], nil
                    if below == nil then r = ramp_below(bk, x + dx, y + dy, z - 1) else r = below and below.shape == 'RAMP' end
                    if r then fn(bk, x + dx, y + dy, z - 1) end
                end
            end
        end
        return
    end
    -- the ramps below, written out (the walks' hottest lines)
    local kb, zb = k - KZ, z - 1
    local bk, b, r
    bk = kb - KY - 1; b = c[bk]; if b == nil then r = ramp_below(bk, x - 1, y - 1, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x - 1, y - 1, zb) end
    bk = kb - 1; b = c[bk]; if b == nil then r = ramp_below(bk, x - 1, y, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x - 1, y, zb) end
    bk = kb + KY - 1; b = c[bk]; if b == nil then r = ramp_below(bk, x - 1, y + 1, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x - 1, y + 1, zb) end
    bk = kb - KY; b = c[bk]; if b == nil then r = ramp_below(bk, x, y - 1, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x, y - 1, zb) end
    bk = kb + KY; b = c[bk]; if b == nil then r = ramp_below(bk, x, y + 1, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x, y + 1, zb) end
    bk = kb - KY + 1; b = c[bk]; if b == nil then r = ramp_below(bk, x + 1, y - 1, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x + 1, y - 1, zb) end
    bk = kb + 1; b = c[bk]; if b == nil then r = ramp_below(bk, x + 1, y, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x + 1, y, zb) end
    bk = kb + KY + 1; b = c[bk]; if b == nil then r = ramp_below(bk, x + 1, y + 1, zb) else r = b and b.shape == 'RAMP' end
    if r then fn(bk, x + 1, y + 1, zb) end
end

-- An "outside" tile that can't reach the map's edge without going indoors
-- is a courtyard, not the surface: part of the fort. Found by walking the
-- open-air tiles from it (cached for everything walked).
COURTYARD_LIMIT = 6000
edge_cache = nil   -- (13e) a module name, as cache
local function reaches_edge(k)
    local known = edge_cache[k]
    if known ~= nil then return known end
    local W, H = map_size()
    local seen, queue, head, result = {[k] = true}, {k}, 1, nil
    local tail = 1
    local function visit(nk, nx, ny, nz)
        if seen[nk] then return end
        local nt = TK(nk, nx, ny, nz)
        if nt and nt.walk and nt.outside and not nt.hidden then
            seen[nk] = true
            tail = tail + 1
            queue[tail] = nk
        end
    end
    while head <= tail do
        local ck = queue[head]
        head = head + 1
        local x, y, z = unkey(ck)
        if x <= 0 or y <= 0 or x >= W - 1 or y >= H - 1 then result = true break end
        if tail > COURTYARD_LIMIT then result = true break end   -- that big: the surface
        local t = TK(ck, x, y, z)
        moves_k(ck, x, y, z, t, visit)
    end
    result = result or false
    for vk in pairs(seen) do edge_cache[vk] = result end
    return result
end

-- (0.104.104) a tree's branches and twigs are never a courtyard: a treetop is
-- walkable open air ringed by empty sky, so it never "reaches the edge", and
-- Teacheroar's forest became dozens of fort "entrances" on branches (none
-- buildable, x30-185, 2-91 wide) while the real way in stood open to titans
TREE_PARTS = {BRANCH = true, TRUNK_BRANCH = true, TWIG = true}
TREE_MATERIALS = {TREE = true, ROOT = true, PLANT = true, MUSHROOM = true}
local function treetop(t)
    return t ~= nil and (TREE_PARTS[t.shape] or TREE_MATERIALS[t.material]) or false
end

local function inside_or_courtyard(t, k)
    if interior(t) then return true end
    return t and t.walk and t.outside and not t.feature and not t.special and not t.hidden
        and not treetop(t) and not reaches_edge(k)
end

-- Flood the inside from the start tiles. blocked: set of keys that can't be
-- passed (a closed door). Returns the inside set, its size, and the openings:
-- {inside = key, out = key, kind = 'surface'|'cavern'}.
function explore(starts, blocked)
    blocked = blocked or {}
    local seen, queue, head, n = {}, {}, 1, 0
    local openings = {}
    local tail = 0
    for _, p in ipairs(starts) do
        local k = key(p.x, p.y, p.z)
        if not seen[k] and inside_or_courtyard(T(p.x, p.y, p.z), k) and not blocked[k] then
            seen[k] = true
            tail = tail + 1
            queue[tail] = k
        end
    end
    local k             -- the tile walked from
    local c = cache
    local function visit(nk, nx, ny, nz)
        if seen[nk] or blocked[nk] then return end
        local nt = c[nk]
        if nt == nil then nt = TK(nk, nx, ny, nz) end
        -- (0.104.104) a treetop is neither the fort nor a way in
        if not nt or not nt.walk or nt.hidden or nt.special or treetop(nt) then return end
        if inside_or_courtyard(nt, nk) then
            seen[nk] = true
            tail = tail + 1
            queue[tail] = nk
        else
            openings[#openings + 1] = {inside = k, out = nk, kind = nt.feature and 'cavern' or 'surface'}
        end
    end
    while head <= tail and n < MAX_TILES do
        k = queue[head]
        head = head + 1
        n = n + 1
        local x, y, z = unkey(k)
        local t = TK(k, x, y, z)
        moves_k(k, x, y, z, t, visit)
    end
    return seen, n, openings
end

-- Openings close together (2 tiles, 1 level) are one entrance.
local function cluster(openings)
    local groups = {}
    for _, o in ipairs(openings) do
        local x, y, z = unkey(o.inside)
        local home
        for _, g in ipairs(groups) do
            if g.kind == o.kind then
                for _, ik in ipairs(g.inside_list) do
                    local gx, gy, gz = unkey(ik)
                    if math.abs(gx - x) <= 2 and math.abs(gy - y) <= 2 and math.abs(gz - z) <= 1 then
                        home = g
                        break
                    end
                end
            end
            if home then break end
        end
        if not home then
            home = {kind = o.kind, inside = {}, inside_list = {}, outs = {}}
            table.insert(groups, home)
        end
        if not home.inside[o.inside] then
            home.inside[o.inside] = true
            table.insert(home.inside_list, o.inside)
        end
        home.outs[o.out] = true
    end
    return groups
end

local function building_keys(b)
    local out = {}
    for x = b.x1, b.x2 do
        for y = b.y1, b.y2 do out[key(x, y, b.z)] = true end
    end
    return out
end

local function near(b, g)
    for _, ik in ipairs(g.inside_list) do
        local x, y, z = unkey(ik)
        if math.abs(b.z - z) <= 2 and x >= b.x1 - 8 and x <= b.x2 + 8 and y >= b.y1 - 8 and y <= b.y2 + 8 then
            return true
        end
    end
    return false
end

POCKET = 1500        -- tiles: walking in from an entrance this far means it isn't sealed

-- Does blocking these keys cut this entrance off from the inside? Walk in
-- from the entrance's outside tiles: if only a small pocket (the bit of
-- tunnel before the gate) can be reached, it's sealed. Cheap: it never maps
-- the whole fort.
local function seals(starts, g, blocked)
    local home = {}
    for _, p in ipairs(starts) do home[key(p.x, p.y, p.z)] = true end
    local seen, queue, head = {}, {}, 1
    for k in pairs(g.outs) do
        -- an outside tile with a gate on it (a hatch on a shaft's top) is
        -- no way in at all: nothing walks in from it
        if not blocked[k] then
            seen[k] = true
            table.insert(queue, k)
        end
    end
    local inside_count, reached = 0, false
    local tail = #queue
    local function visit(nk, nx, ny, nz)
        if seen[nk] or blocked[nk] then return end
        local nt = TK(nk, nx, ny, nz)
        if inside_or_courtyard(nt, nk) then
            seen[nk] = true
            inside_count = inside_count + 1
            if home[nk] then reached = true end
            tail = tail + 1
            queue[tail] = nk
        end
    end
    while head <= tail do
        local k = queue[head]
        head = head + 1
        local x, y, z = unkey(k)
        local t = TK(k, x, y, z)
        if t then moves_k(k, x, y, z, t, visit) end
        -- reached where the dwarves are, or walked too far: not sealed
        if reached or inside_count > POCKET then return false end
    end
    return true
end

-- DF (and quickfort) only builds a door with a wall or fortification right
-- beside it (north, south, east or west). Planned walls don't count until
-- they're built.
local DOOR_SUPPORT = {WALL = true, FORTIFICATION = true}
local ORTHO = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
function wall_beside(x, y, z)
    for _, d in ipairs(ORTHO) do
        local t = T(x + d[1], y + d[2], z)
        if t and DOOR_SUPPORT[t.shape] then return true end
    end
    return false
end

-- Tile shapes a door can stand on, and ones a wall can be built on.
local DOOR_GROUND = {FLOOR = true, SHRUB = true, SAPLING = true, BOULDER = true, PEBBLES = true, TWIG = true}
local WALL_GROUND = {FLOOR = true, SHRUB = true, SAPLING = true, BOULDER = true, PEBBLES = true, TWIG = true,
                     EMPTY = true, RAMP_TOP = true}

---------------------------------------------------------------------------
-- (0.105.23, 14.1 step 4a) The War-hold's gate: a gatehouse in front of the
-- founding stair's hatch. On the surface, a 1-wide corridor runs out from
-- the hatch between walls (and a wall behind the hatch), its floor set with
-- traps, ended by a raising drawbridge toward the open ground. Seen from
-- above, the corridor going east (H the hatch, T traps, B the bridge, W
-- walls; the open ground east of B):
--     W W W W W W W
--     W H T T T T B   ->
--     W W W W W W W
-- The hatch stays the gate that seals the fort; the bridge is an outer gate
-- the watcher raises with it, and the traps catch what comes down the
-- corridor. Nothing seals the fort until the watcher closes it (a bridge
-- stands lowered when built), so no one is shut in or out by the building.
---------------------------------------------------------------------------

GATEHOUSE_NAME = 'AI gatehouse bridge'
GATEHOUSE_LENGTHS = {4, 3, 2}       -- corridor tiles (traps) tried, longest first
BRIDGE_DIR = {['1,0'] = 'gd', ['-1,0'] = 'ga', ['0,1'] = 'gx', ['0,-1'] = 'gw'}

function is_gatehouse(b)
    return tostring(b and b.name or ''):lower():find('^ai gatehouse') ~= nil
end

-- The hatch on the founding stair's top (the lid on a shaft whose outside is
-- straight above), {x, y, z}, or nil.
function lid_hatch(e)
    local tops = {}
    for _, k in ipairs(e.inside_list or {}) do
        local x, y, z = unkey(k)
        tops[key(x, y, z + 1)] = true
    end
    for _, b in ipairs(e.equipment or {}) do
        if b.kind == 'hatch' and b.x1 == b.x2 and b.y1 == b.y2 and tops[key(b.x1, b.y1, b.z)] then
            return {x = b.x1, y = b.y1, z = b.z, id = b.id}
        end
    end
    return nil
end

-- The surface proper (not a courtyard, not the fort, nothing hidden).
local function open_ground(x, y, z)
    local t = T(x, y, z)
    if not (t and t.walk and t.outside and not t.hidden and not t.liquid and not t.occupied
            and not t.feature and not t.special) then
        return nil
    end
    if inside_or_courtyard(t, key(x, y, z)) then return nil end
    return t
end

-- The layout for one way out from the hatch and one length, or nil and why.
local function gatehouse_layout(h, d, len)
    local px, py = math.abs(d[2]), math.abs(d[1])
    local function at(u, v) return h.x + d[1] * u + px * v, h.y + d[2] * u + py * v end
    local plan = {walls = {}, natural = 0, corridor = {}, len = len}
    -- the walls: either side from behind the hatch to the bridge, and behind it
    local wall_uv = {{-1, 0}}
    for u = -1, len + 1 do table.insert(wall_uv, {u, -1}); table.insert(wall_uv, {u, 1}) end
    -- (0.105.30) nothing of it on the depot's wagon road or in front of its mouth
    local road = deep_road_keys(true)
    if next(road) then
        for u = -1, len + 3 do
            for v = -1, 1 do
                local x, y = at(u, v)
                if road[key(x, y, h.z)] then
                    return nil, ('x%d y%d is the underground depot\'s wagon road'):format(x, y)
                end
            end
        end
    end
    for _, uv in ipairs(wall_uv) do
        local x, y = at(uv[1], uv[2])
        local t = T(x, y, h.z)
        if t and t.shape == 'WALL' then
            plan.natural = plan.natural + 1           -- rock already there: nothing to build
        elseif not (t and WALL_GROUND[t.shape] and t.shape ~= 'EMPTY' and open_ground(x, y, h.z)) then
            return nil, ('no wall can go at x%d y%d (%s)'):format(x, y, t and tostring(t.shape):lower() or 'off the map')
        else
            table.insert(plan.walls, key(x, y, h.z))
        end
    end
    for u = 1, len + 1 do
        local x, y = at(u, 0)
        local t = open_ground(x, y, h.z)
        if not (t and DOOR_GROUND[t.shape]) then
            return nil, ('the corridor is blocked at x%d y%d'):format(x, y)
        end
        if u <= len then table.insert(plan.corridor, key(x, y, h.z)) end
    end
    -- the way on from the bridge: open ground, two tiles out
    for u = len + 2, len + 3 do
        local x, y = at(u, 0)
        if not open_ground(x, y, h.z) then
            return nil, ('no open ground in front of the bridge at x%d y%d'):format(x, y)
        end
    end
    local bx, by = at(len + 1, 0)
    plan.bridge = {x = bx, y = by, z = h.z, dir = BRIDGE_DIR[d[1] .. ',' .. d[2]]}
    plan.hatch = {x = h.x, y = h.y, z = h.z}
    return plan
end

-- The gatehouse for this entrance's lid hatch h: the way out toward the
-- nearest map edge first (where the roads come from), the longest corridor
-- that fits. Returns the plan, or nil and why.
function plan_gatehouse(e, h)
    h = h or lid_hatch(e)
    if not h then return nil, 'no hatch over a stair to build a gatehouse in front of' end
    local W, H = map_size()
    local dirs = {}
    for i, d in ipairs(ORTHO) do
        local edge = (d[1] == 1 and W - 1 - h.x) or (d[1] == -1 and h.x) or (d[2] == 1 and H - 1 - h.y) or h.y
        table.insert(dirs, {d = d, edge = edge, i = i})
    end
    table.sort(dirs, function(a, b) return a.edge < b.edge or (a.edge == b.edge and a.i < b.i) end)
    local why
    for _, len in ipairs(GATEHOUSE_LENGTHS) do
        for _, dd in ipairs(dirs) do
            local plan, w = gatehouse_layout(h, dd.d, len)
            if plan then return plan end
            why = why or w
        end
    end
    return nil, 'no room for a gatehouse round the hatch: ' .. tostring(why)
end

-- (0.105.30, deep depot) The underground trade depot's wagon road: its dug
-- tiles and the ground in front of its mouth (key -> true), from the
-- builder's save; empty when there is none. Wagons pass no door and no
-- hatch on a ramp (the wiki's "Wagon"; DFHack's pathable plugin), so no
-- door goes on it, a gate there is a 3-wide drawbridge (lowered, wagons roll
-- over it), and no gatehouse wall goes in front of it. with_mouth: the
-- ground in front of the mouth too (for walls; an entrance is the road's
-- only by its dug tiles: the fort's own way in may be a few tiles off the
-- mouth). Tests replace this.
function deep_road_keys(with_mouth)
    local out = {}
    pcall(function()
        local B = reqscript('ai-builder')
        local d = B.deep_depot_data()
        if d and type(d.tiles) == 'table' and d.stage ~= 'no_road' then
            for _, t in ipairs(d.tiles) do out[key(t.x, t.y, t.z)] = true end
        end
        if with_mouth then
            for _, t in ipairs(B.deep_depot_mouth() or {}) do out[key(t.x, t.y, t.z)] = true end
        end
    end)
    return out
end

local function on_deep_road(g, road)
    if not next(road) then return false end
    for _, k in ipairs(g.inside_list or {}) do if road[k] then return true end end
    for k in pairs(g.outs or {}) do if road[k] then return true end end
    return false
end

-- The whole scan. starts: tiles where citizens stand (inside). (0.105.33)
-- now_tick, wait_since ({bridge id = tick}): since when a drawbridge waits
-- for an unlinked lever (optional)
function find_entrances(starts, buildings, now_tick, wait_since)
    -- (13e) within scan() the map was read fresh at its start (and can't
    -- change while it runs): what fort_starts read is kept
    if not SCAN_MEMO then cache, edge_cache = {}, {} end
    local inside, n, openings = explore(starts)
    -- (13e) each building's tiles worked out once a call (only walked, never changed)
    local bkeys = {}
    local function building_keys_of(b)
        local ks = bkeys[b]
        if not ks then ks = building_keys(b); bkeys[b] = ks end
        return ks
    end
    local groups = cluster(openings)
    local entrances = {}
    local cut_checked = 0        -- (0.105.0 review)
    local road = deep_road_keys()        -- (0.105.30)
    for i, g in ipairs(groups) do
        local e = {id = i, kind = g.kind, width = #g.inside_list, inside_list = g.inside_list,
                   outs = g.outs, equipment = {}, sealed = false, door_spots = {}}
        e.deep_road = on_deep_road(g, road) or nil
        local x, y, z = unkey(g.inside_list[1])
        e.x, e.y, e.z = x, y, z
        -- the gates near it that can be closed (a bridge only with a lever)
        local cands, pending = {}, {}
        e.bridges_unworked = {}
        local gatehouse_here, gatehouse_bridge = false, nil
        local near_g = {}           -- (13e) near(b, g) once for each building, by its place in the list
        for i, b in ipairs(buildings) do
            local nb = near(b, g)
            near_g[i] = nb
            if nb and is_gatehouse(b) then                             -- (0.105.23)
                gatehouse_here = true
                gatehouse_bridge = {x = b.x1, y = b.y1, z = b.z}               -- (0.105.30) for the wings
            end
            if nb then
                if b.kind == 'pending' then
                    table.insert(pending, b)
                    -- (0.105.35) its id: free_gate_jobs unsuspends its building job
                    e.pending_ids = e.pending_ids or {}
                    table.insert(e.pending_ids, b.id)
                    -- (0.104.105) what it waits for, by kind: a hatch planned
                    -- over the main stair waited 15 hours for a hatch cover
                    -- nobody made, and the entrance read "closing" all along
                    e.waiting = e.waiting or {}
                    e.waiting[b.what or 'wall'] = (e.waiting[b.what or 'wall'] or 0) + 1
                elseif b.kind ~= 'bridge' then
                    table.insert(cands, b)
                else
                    -- a drawbridge is a gate only if a lever inside the fort
                    -- works it (no dwarf should have to go out to close it)
                    local worked = false
                    for _, l in ipairs(b.levers or {}) do
                        if inside[key(l.x, l.y, l.z)] then worked = true end
                    end
                    if worked then table.insert(cands, b) else table.insert(e.bridges_unworked, b.id) end
                end
            end
        end
        local blocked = {}
        for _, b in ipairs(cands) do
            for k in pairs(building_keys_of(b)) do blocked[k] = true end
        end
        if #cands > 0 and seals(starts, g, blocked) then
            -- keep only the ones it needs
            local keep = {}
            for _, b in ipairs(cands) do keep[b.id] = b end
            for _, b in ipairs(cands) do
                local without = {}
                for id, c in pairs(keep) do
                    if id ~= b.id then for k in pairs(building_keys_of(c)) do without[k] = true end end
                end
                if next(without) and seals(starts, g, without) then keep[b.id] = nil end
            end
            for _, b in pairs(keep) do table.insert(e.equipment, b) end
            table.sort(e.equipment, function(a, b) return a.id < b.id end)
            e.sealed = true
            -- (0.105.23, 14.1 step 4a) a gatehouse's drawbridge in front of the
            -- hatch isn't needed to seal it (the hatch does): it's the outer
            -- gate, raised with the hatch and lowered with it
            e.outer = {}
            for _, b in ipairs(cands) do
                if b.kind == 'bridge' and not keep[b.id] and is_gatehouse(b) then table.insert(e.outer, b) end
            end
        end
        -- (0.105.23) the founding stair's lid: a gatehouse can stand in front of it
        if e.sealed and e.kind == 'surface' then
            local h = lid_hatch(e)
            if h then
                e.lid = true
                if gatehouse_here then
                    e.gatehouse = 'standing'
                    e.gatehouse_bridge = gatehouse_bridge
                    -- (0.105.30 seams) its wing walls, as recorded when placed
                    local okw, wp = pcall(wing_pieces_of, e)
                    if okw and wp then e.wing_pieces = wp end
                else
                    local okp, plan, why = pcall(plan_gatehouse, e, h)
                    if okp and plan then e.gatehouse = 'possible'
                    else e.gatehouse, e.gatehouse_why = 'none', okp and why or tostring(plan) end
                end
            end
        end
        if not e.sealed and #e.bridges_unworked > 0 and lever_waiting_for(e, inside) then
            -- a drawbridge there waits for its lever to be linked (the lever
            -- rule does it): it's being closed, not open. (0.105.33) Only for
            -- a lever that can work it (inside, away from the gate), and for
            -- LEVER_WAIT_DAYS at most (since: by the bridges' ids)
            local since
            for _, bid in ipairs(e.bridges_unworked) do
                local t = wait_since and wait_since[bid]
                if type(t) == 'number' and (not since or t < since) then since = t end
            end
            if type(now_tick) == 'number' and since and since > now_tick then since = nil end   -- (a new year's tick)
            since = since or now_tick
            e.lever_wait_since = since
            if type(now_tick) == 'number' and type(since) == 'number'
                    and now_tick - since >= LEVER_WAIT_DAYS * 1200 then
                e.lever_wait_over = math.floor((now_tick - since) / 1200)
            else
                e.closing = true
            end
        end
        if not e.sealed and not e.closing and #pending > 0 then
            -- walls or doors planned there (the AI's own, or yours) would
            -- close it once built: it's being closed, leave it be
            for _, b in ipairs(cands) do
                for k in pairs(building_keys_of(b)) do blocked[k] = true end
            end
            for _, b in ipairs(pending) do
                for k in pairs(building_keys_of(b)) do blocked[k] = true end
            end
            if seals(starts, g, blocked) then e.closing = true end
        end
        -- (0.105.30) never doors on the depot's wagon road: a wagon passes no door
        if not e.sealed and not e.closing and e.width <= MAX_DOORS and not e.deep_road then
            -- no gate that closes it: doors on the opening's inside tiles.
            -- Tiles that already have a door (built or planned: some of an
            -- earlier set may have been refused) are left as they are; every
            -- other tile must be able to take one (plain floor, dry, free).
            local doors_here, walls_coming = {}, {}
            for i, b in ipairs(buildings) do
                if near_g[i] and (b.kind == 'door' or (b.kind == 'pending' and b.what == 'door')) then
                    for k in pairs(building_keys_of(b)) do doors_here[k] = true end
                elseif near_g[i] and b.kind == 'pending' and b.what == 'wall' then
                    for k in pairs(building_keys_of(b)) do walls_coming[k] = true end
                end
            end
            local block, spots, all_ok, waiting = {}, {}, true, false
            for _, ik in ipairs(g.inside_list) do
                block[ik] = true
                if not doors_here[ik] and not walls_coming[ik] then    -- (a wall on its way blocks it too)
                    local sx2, sy2, sz2 = unkey(ik)
                    local st = T(sx2, sy2, sz2)
                    if not st or not DOOR_GROUND[st.shape] or st.liquid or st.occupied then
                        all_ok = false
                    elseif not wall_beside(sx2, sy2, sz2) then
                        -- no wall beside it: a door can't go there, unless walls
                        -- planned beside it are still to be built
                        local coming = false
                        for _, d in ipairs(ORTHO) do
                            if walls_coming[key(sx2 + d[1], sy2 + d[2], sz2)] then coming = true end
                        end
                        if coming then waiting = true else all_ok = false end
                    end
                    table.insert(spots, ik)
                end
            end
            if all_ok and waiting then
                e.closing = true          -- doors follow once the walls beside them are built
            elseif all_ok and #spots > 0 and seals(starts, g, block) then
                for _, ik in ipairs(spots) do
                    local dx, dy, dz = unkey(ik)
                    table.insert(e.door_spots, {x = dx, y = dy, z = dz})
                end
            end
        end
        -- (0.105.0) hatches on the stairs down from a wide opening. (0.105.0
        -- review) in a pcall (an error lost the whole scan); only an opening
        -- too wide to wall, or one the AI cut; at most CUT_SURVEY_MAX of
        -- them a scan (each is a walk of up to CUT_MAX_PORCH tiles)
        if cut_checked < CUT_SURVEY_MAX and not e.sealed and not e.closing and e.kind == 'surface'
                and (e.width > FORTIFY_MAX_WIDTH or was_cut(e)) then
            cut_checked = cut_checked + 1
            pcall(cut_equipment, e, buildings, starts, inside)
        end
        table.insert(entrances, e)
    end
    return entrances, inside, n
end

---------------------------------------------------------------------------
-- In the game
---------------------------------------------------------------------------

local function citizen_starts()
    local out = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if u.pos.z >= 0 then table.insert(out, {x = u.pos.x, y = u.pos.y, z = u.pos.z}) end
    end
    return out
end

local function gate_name(e)
    return ('AI gate %d (%s)'):format(e.id, e.kind)
end

local function set_name(id, name)
    local b = df.building.find(id)
    if not b then return end
    local current = tostring(b.name or '')
    if current:lower() == 'ai gate' then return end      -- the player's own gate lever keeps its name
    if current == '' or current:find('^AI gate') then b.name = name end
end

-- A lever a dwarf can pull without running to the gate: inside the fort, and
-- at least LEVER_AWAY tiles or 4 levels from the entrance.
LEVER_AWAY = 20
function lever_away(e, l, inside)
    if not (inside and inside[key(l.x, l.y, l.z)]) then return false end
    if math.abs(l.z - e.z) > 3 then return true end
    return math.max(math.abs(l.x - e.x), math.abs(l.y - e.y)) >= LEVER_AWAY
end

-- For each bridge: the lever the watcher pulls (one away from the gate if
-- there is one, else one inside, else any).
function pick_levers(entrances, inside)
    for _, e in ipairs(entrances) do
        local gates = {}
        for _, b in ipairs(e.equipment) do table.insert(gates, b) end
        for _, b in ipairs(e.outer or {}) do table.insert(gates, b) end     -- (0.105.23) a gatehouse's bridge
        for _, b in ipairs(gates) do
            if b.levers and #b.levers > 0 then
                local best, rank = nil, -1
                for _, l in ipairs(b.levers) do
                    local r = lever_away(e, l, inside) and 2 or (inside and inside[key(l.x, l.y, l.z)] and 1 or 0)
                    if r > 0 and r > rank then best, rank = l, r end
                end
                if best then b.lever_id, b.lever_away = best.id, rank == 2 end
            end
        end
    end
end

-- (0.105.23, 14.1 step 4a) For each door or hatch on a lever: the lever the
-- watcher pulls (at once: DFHack's `lever pull --instant`, no dwarf runs, so
-- where it stands doesn't matter). One lever per entrance: a lever that also
-- works a gate of another entrance (or anything else) is never pulled for
-- this one, as the pull would toggle the others too; such a gate has none.
function drive_levers(entrances)
    for _, e in ipairs(entrances) do
        local mine = {}
        for _, b in ipairs(e.equipment or {}) do mine[b.id] = true end
        for _, b in ipairs(e.outer or {}) do mine[b.id] = true end
        for _, b in ipairs(e.equipment or {}) do
            if b.lever_driven then
                b.drive_lever = nil
                local order = {}
                for _, l in ipairs(b.levers or {}) do
                    if l.id == b.lever_id then table.insert(order, 1, l) else table.insert(order, l) end
                end
                for _, l in ipairs(order) do
                    local only_here = true
                    for _, tid in ipairs(l.targets or {b.id}) do
                        if not mine[tid] then only_here = false end
                    end
                    if only_here then b.drive_lever, b.drive_ai = l.id, ai_lever_name(l.name) break end
                end
            end
        end
    end
end

-- A lever the AI may work: named "AI gate..." (the AI's own "AI gate lever",
-- the player's "AI gate", or a drawbridge's lever the scan named).
function ai_lever_name(name)
    return tostring(name or ''):lower():find('^ai gate') ~= nil
end

-- (0.105.33) The building ids of an entrance's gates (its equipment and the
-- gatehouse's outer drawbridge): a set.
function entrance_gate_ids(e)
    local ids = {}
    for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
        for _, g in ipairs(list) do if g.id ~= nil then ids[g.id] = true end end
    end
    return ids
end

-- (0.105.33) Which new entrance each old one is, across a rescan: {old id =
-- new id}. The one holding any of its gates; else (none of its gates in a
-- new entrance: one gone) the one at its spot.
function carry_ids(old, new)
    local owner = {}
    for _, e in ipairs(new or {}) do
        for id in pairs(entrance_gate_ids(e)) do owner[id] = owner[id] or e.id end
    end
    local at = {}
    for _, e in ipairs(new or {}) do
        if e.x then at[key(e.x, e.y, e.z)] = at[key(e.x, e.y, e.z)] or e.id end
    end
    local out = {}
    for _, e in ipairs(old or {}) do
        local nid
        for id in pairs(entrance_gate_ids(e)) do
            if owner[id] and (not nid or owner[id] < nid) then nid = owner[id] end
        end
        if not nid and e.x then nid = at[key(e.x, e.y, e.z)] end
        out[e.id] = nid
    end
    return out
end

-- (0.105.40, 13e) SCAN_MEMO: set while scan() maps the fort (nil otherwise).
-- The game stands still while a script runs, so the map read at the scan's
-- start holds for all of it: fort_starts and find_entrances keep the tiles
-- already read (each read them afresh), and porch_of keeps each entrance's
-- porch (cut_equipment and the cut survey walked the same porch twice).
-- Cleared before the hatches are opened and the summary is made.
SCAN_MEMO = nil

function scan(now_tick)
    cache, edge_cache = {}, {}
    SCAN_MEMO = {porch = {}}
    local ok, err = pcall(scan_map, now_tick)
    SCAN_MEMO = nil
    if not ok then error(err, 0) end
    -- (0.105.23) a hatch its new lever link shut, with no watcher holding it: opened
    if not GATES.armed then pcall(open_lever_hatches) end
    return summary()
end

-- scan() without its end: maps the fort and sets GATES
function scan_map(now_tick)
    pcall(gate_planned_since, true)       -- (0.105.36 fix) the records' start, kept once
    -- (0.105.0) citizens on a ledge or a treetop don't seed a fort of their own
    local fstarts = fort_starts(citizen_starts())
    local entrances, inside, n = find_entrances(fstarts, gate_buildings(), now_tick, GATES.lever_wait_since)
    local lever_wait = {}             -- (0.105.33) since when each bridge waits for a lever
    for _, e in ipairs(entrances) do
        if e.lever_wait_since then
            for _, bid in ipairs(e.bridges_unworked or {}) do lever_wait[bid] = e.lever_wait_since end
        end
    end
    pick_levers(entrances, inside)
    drive_levers(entrances)
    pcall(cut_survey, entrances, fstarts)        -- (0.105.0)
    for _, e in ipairs(entrances) do
        for _, b in ipairs(e.equipment) do
            set_name(b.id, gate_name(e))
            -- (0.105.23) a door's or hatch's lever keeps its name: an unnamed one
            -- (the player's, a cavern well's shaft gate) would read as the AI's
            -- and its hatch be held open by the AI
            if b.lever_id and b.kind == 'bridge' then set_name(b.lever_id, gate_name(e) .. ' lever') end
        end
    end
    -- (0.104.105) since when each entrance has read "closing" (by its spot):
    -- one that stays so for days waits for something
    local since_old, since = GATES.closing_since or {}, {}
    for _, e in ipairs(entrances) do
        if e.closing and not e.sealed then
            local k = key(e.x, e.y, e.z)
            since[k] = since_old[k] or now_tick
        end
    end
    -- (0.104.139, review) the entrances' ids are list places and a rescan can
    -- number them anew: what was closed is carried, and the watcher's timers
    -- are kept. (0.105.33) Carried by the gates' building ids (the entrance's
    -- spot is the first opening tile the map reached, and moves with where
    -- the citizens stand); by the spot only for an entrance none of whose
    -- gates is in the new one (a gate gone)
    local new_of = carry_ids(GATES.entrances or {}, entrances)
    local function carried(t)
        local out = {}
        for old_id, v in pairs(t or {}) do
            local nid = new_of[old_id]
            if nid and out[nid] == nil then out[nid] = v end
        end
        return out
    end
    local closed = carried(GATES.closed)
    GATES = {scanned = true, entrances = entrances, inside = inside, inside_tiles = n,
             scanned_tick = now_tick, armed = GATES.armed, closed = closed,
             opening = carried(GATES.opening),                        -- (0.105.33)
             lever_wait_since = lever_wait,                           -- (0.105.33)
             closing_since = since, timer = GATES.timer, reopen_timer = GATES.reopen_timer,
             watch_error = GATES.watch_error, gone_ids = GATES.gone_ids, repulled = GATES.repulled,
             peak = GATES.peak, clear_looks = carried(GATES.clear_looks),      -- (0.105.4 review)
             stuck_removed = GATES.stuck_removed, split_seen = GATES.split_seen,   -- (0.105.32)
             mine = GATES.mine}                    -- (0.105.36 fix) by building id: kept as it is
end

-- (13e) this file's locals the later parts use, as module names (each takes
-- them back as locals of its own)
_ENV.T, _ENV.TK, _ENV.moves_k, _ENV.interior, _ENV.moves, _ENV.treetop, _ENV.inside_or_courtyard, _ENV.seals, _ENV.ORTHO, _ENV.DOOR_GROUND, _ENV.WALL_GROUND, _ENV.open_ground, _ENV.citizen_starts, _ENV.gate_name = T, TK, moves_k, interior, moves, treetop, inside_or_courtyard, seals, ORTHO, DOOR_GROUND, WALL_GROUND, open_ground, citizen_starts, gate_name
