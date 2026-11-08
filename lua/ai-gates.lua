-- The fort's gates, found and run by the AI.
--
--   scan()   maps the inside of the fort, starting from where the citizens
--            are, and finds every opening onto the surface or into a cavern
--            (an "entrance"). For each it looks for doors, hatches and
--            drawbridges (with a lever) that close it, checks that closing
--            them really seals that entrance, and names them "AI gate N".
--   arm()    starts a watcher that closes an entrance when every citizen is
--            inside, or when danger is within IMMINENT tiles of it, so
--            dwarves out working have time to get back in.
--   open()   stops the watcher and opens everything it closed.
--
-- Doors and hatches are locked by DFHack directly (no lever, no dwarf has to
-- run anywhere). A drawbridge needs a lever that is already linked to it.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

IMMINENT = 12         -- tiles: closer than this to an entrance, close it now
WIDE = 60             -- tiles: danger this close counts as "coming"
CHECK_TICKS = 100     -- the watcher looks this often (12 times an in-game day)
MAX_TILES = 250000    -- safety limit for the map of the inside
MAX_DOORS = 3         -- an open entrance up to this wide gets doors

GATES = GATES or {scanned = false}

local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
local function unkey(k) return k % 4096, (k // 4096) % 4096, k // (4096 * 4096) end

---------------------------------------------------------------------------
-- The map, through two functions tests can replace.
---------------------------------------------------------------------------

local STAIR_UP = {STAIR_UP = true, STAIR_UPDOWN = true}
local STAIR_DOWN = {STAIR_DOWN = true, STAIR_UPDOWN = true}

-- {walk, shape, outside, feature, special, hidden} or nil off the map.
-- feature: caverns, the magma sea, the underworld (the world's layers);
-- special: a local feature (a deep pit, a magma pipe...): never walked into
-- and never an entrance.
-- Magma or water? DFHack gives this 1-bit flag as a boolean in 53.16 (the
-- defence probe read water as false); a number is handled too.
local function is_magma(des)
    local lt = des.liquid_type
    return lt == true or lt == 1
end

-- A tree's trunk, branches or leaves within a few levels straight above?
function under_tree(x, y, z)
    for dz = 1, 6 do
        local tt = dfhack.maps.getTileType(x, y, z + dz)
        if not tt then return false end
        local attrs = df.tiletype.attrs[tt]
        local m = df.tiletype_material[attrs.material]
        if m == 'TREE' or m == 'ROOT' or m == 'PLANT' then return true end
        local shape = df.tiletype_shape[attrs.shape]
        if shape ~= 'EMPTY' and shape ~= 'NONE' then return false end      -- a roof or rock: not a tree's shade
    end
    return false
end

function tile(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    local des, occ = dfhack.maps.getTileFlags(x, y, z)
    if not des then return nil end
    local shape = df.tiletype.attrs[tt].shape
    return {
        walk = df.tiletype_shape.attrs[shape].walkable == true,
        shape = df.tiletype_shape[shape],
        outside = des.outside,
        feature = des.feature_global,
        special = des.feature_local,
        hidden = des.hidden,
        liquid = des.flow_size > 0,
        depth = des.flow_size,                              -- 0-7
        magma = des.flow_size > 0 and is_magma(des),
        salt = des.water_salt, stagnant = des.water_stagnant, aquifer = des.water_table,
        material = df.tiletype_material[df.tiletype.attrs[tt].material],   -- RIVER, POOL, CONSTRUCTION...
        occupied = occ ~= nil and occ.building ~= df.tile_building_occ.None,   -- something built or planned
        canopy = not des.outside and not des.subterranean and under_tree(x, y, z),
    }
end

-- The kind of building on a tile ('Well', 'ScrewPump', 'Floodgate'...) or
-- nil (tests replace this).
function building_at(x, y, z)
    local ok, kind = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        return b and df.building_type[b:getType()] or nil
    end)
    return ok and kind or nil
end

function map_size()
    local x, y, z = dfhack.maps.getTileSize()
    return x, y, z
end

-- Doors, hatches and bridges: {id, kind, x1, y1, x2, y2, z, name, lever_id,
-- levers, closed}. levers: {{id, x, y, z}, ...} linked to it (a bridge needs
-- one); lever_id: the first of them (scan() then picks the best).
--
-- Where DF 53.16 keeps a link (checked with the defence probe): each of a
-- lever's linked mechanisms sits in its target, with a BUILDING_HOLDER
-- reference to that target; the target holds a mechanism with a
-- BUILDING_TRIGGER reference back to the lever. Both sides are read.
local function ref_ids(item, ref_type)
    local ids = {}
    for _, ref in ipairs(item.general_refs or {}) do
        if ref:getType() == ref_type then table.insert(ids, ref.building_id) end
    end
    return ids
end

function lever_links()
    local levers, pos = {}, {}
    local function add(target_id, lever_id)
        levers[target_id] = levers[target_id] or {}
        for _, l in ipairs(levers[target_id]) do if l == lever_id then return end end
        table.insert(levers[target_id], lever_id)
    end
    for _, b in ipairs(df.global.world.buildings.other.TRAP) do
        if b.trap_type == df.trap_type.Lever then
            pos[b.id] = {x = b.centerx, y = b.centery, z = b.z, name = tostring(b.name or '')}
            for _, mech in ipairs(b.linked_mechanisms) do
                local ids = ref_ids(mech, df.general_ref_type.BUILDING_HOLDER)
                if #ids == 0 then ids = ref_ids(mech, df.general_ref_type.BUILDING_TRIGGERTARGET) end
                for _, tid in ipairs(ids) do
                    if tid ~= b.id then add(tid, b.id) end
                end
            end
        end
    end
    return levers, pos
end

-- (0.105.23) Everything a lever works ({target id, ...}), from lever_links'
-- map (target -> levers). A lever pulled for one gate toggles all of them.
function lever_targets(levers, lever_id)
    local out = {}
    for tid, lids in pairs(levers or {}) do
        for _, l in ipairs(lids) do if l == lever_id then table.insert(out, tid) break end end
    end
    table.sort(out)
    return out
end

-- Set by gate_buildings: an "AI gate..." lever with no link yet (built or
-- planned) exists, so a bridge no lever works may be waiting for it.
AI_LEVER_WAITING = false

function gate_buildings()
    local levers, lever_pos = lever_links()
    AI_LEVER_WAITING = false
    for _, b in ipairs(df.global.world.buildings.other.TRAP) do
        if b.trap_type == df.trap_type.Lever and tostring(b.name or ''):lower():find('^ai gate')
                and #b.linked_mechanisms == 0 then
            AI_LEVER_WAITING = true
        end
    end
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        local kind = (t == df.building_type.Door and 'door') or (t == df.building_type.Hatch and 'hatch')
            or (t == df.building_type.Bridge and 'bridge') or nil
        local built = b:getBuildStage() >= b:getMaxBuildStage()
        if not built and (kind or (t == df.building_type.Construction
                and (b.type == df.construction_type.Wall or b.type == df.construction_type.Fortification))) then
            -- planned or being built (the AI's own walls and doors, or the
            -- player's): it will close the opening once it's done
            table.insert(out, {id = b.id, kind = 'pending', what = kind or 'wall',
                               x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z, name = b.name})
        end
        if kind and built then
            -- the target's own side of a link: its mechanisms point at the lever
            for _, ci in ipairs(b.contained_items or {}) do
                for _, lid in ipairs(ref_ids(ci.item, df.general_ref_type.BUILDING_TRIGGER)) do
                    if lever_pos[lid] then
                        levers[b.id] = levers[b.id] or {}
                        local dup = false
                        for _, l in ipairs(levers[b.id]) do if l == lid then dup = true end end
                        if not dup then table.insert(levers[b.id], lid) end
                    end
                end
            end
            local closed, lever_driven
            if kind == 'bridge' then
                -- (13c) a bridge has no `closed` flag (building_bridge_flag: raised,
                -- raising, lowering...): raised blocks the way, so it reads as closed
                local ok, c = pcall(function() return b.gate_flags.raised end)
                closed = ok and c or false
            elseif levers[b.id] and #levers[b.id] > 0 then
                -- (0.105.23, 14.1 step 4a) a door or hatch on a lever: the link
                -- shuts it and only the lever opens it (a lock does nothing), so
                -- it reads by DF's `closed` and the watcher drives it by the lever
                lever_driven = true
                local ok, c = pcall(function() return b.door_flags.closed end)
                closed = ok and c or false
            else
                closed = b.door_flags.forbidden
            end
            local list = {}
            for _, lid in ipairs(levers[b.id] or {}) do
                local p = lever_pos[lid]
                table.insert(list, {id = lid, x = p.x, y = p.y, z = p.z, name = p.name,
                                    targets = lever_targets(levers, lid)})
            end
            table.insert(out, {id = b.id, kind = kind, x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2,
                               z = b.z, name = b.name, lever_id = list[1] and list[1].id or nil,
                               levers = list, closed = closed, lever_driven = lever_driven})
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Mapping the inside (pure: uses tile() only)
---------------------------------------------------------------------------

local cache
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

-- An "outside" tile that can't reach the map's edge without going indoors
-- is a courtyard, not the surface: part of the fort. Found by walking the
-- open-air tiles from it (cached for everything walked).
COURTYARD_LIMIT = 6000
local edge_cache
local function reaches_edge(k)
    local known = edge_cache[k]
    if known ~= nil then return known end
    local W, H = map_size()
    local seen, queue, head, result = {[k] = true}, {k}, 1, nil
    while head <= #queue do
        local ck = queue[head]
        head = head + 1
        local x, y, z = unkey(ck)
        if x <= 0 or y <= 0 or x >= W - 1 or y >= H - 1 then result = true break end
        if #queue > COURTYARD_LIMIT then result = true break end   -- that big: the surface
        local t = T(x, y, z)
        moves(x, y, z, t, function(nx, ny, nz)
            local nk = key(nx, ny, nz)
            if seen[nk] then return end
            local nt = T(nx, ny, nz)
            if nt and nt.walk and nt.outside and not nt.hidden then
                seen[nk] = true
                table.insert(queue, nk)
            end
        end)
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
    for _, p in ipairs(starts) do
        local k = key(p.x, p.y, p.z)
        if not seen[k] and inside_or_courtyard(T(p.x, p.y, p.z), k) and not blocked[k] then
            seen[k] = true
            table.insert(queue, k)
        end
    end
    while head <= #queue and n < MAX_TILES do
        local k = queue[head]
        head = head + 1
        n = n + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        moves(x, y, z, t, function(nx, ny, nz)
            local nk = key(nx, ny, nz)
            if seen[nk] or blocked[nk] then return end
            local nt = T(nx, ny, nz)
            -- (0.104.104) a treetop is neither the fort nor a way in
            if not nt or not nt.walk or nt.hidden or nt.special or treetop(nt) then return end
            if inside_or_courtyard(nt, nk) then
                seen[nk] = true
                table.insert(queue, nk)
            else
                table.insert(openings, {inside = k, out = nk, kind = nt.feature and 'cavern' or 'surface'})
            end
        end)
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
    while head <= #queue do
        local k = queue[head]
        head = head + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if seen[nk] or blocked[nk] then return end
                local nt = T(nx, ny, nz)
                if inside_or_courtyard(nt, nk) then
                    seen[nk] = true
                    inside_count = inside_count + 1
                    if home[nk] then reached = true end
                    table.insert(queue, nk)
                end
            end)
        end
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

-- The whole scan. starts: tiles where citizens stand (inside).
function find_entrances(starts, buildings)
    cache, edge_cache = {}, {}
    local inside, n, openings = explore(starts)
    local groups = cluster(openings)
    local entrances = {}
    local cut_checked = 0        -- (0.105.0 review)
    for i, g in ipairs(groups) do
        local e = {id = i, kind = g.kind, width = #g.inside_list, inside_list = g.inside_list,
                   outs = g.outs, equipment = {}, sealed = false, door_spots = {}}
        local x, y, z = unkey(g.inside_list[1])
        e.x, e.y, e.z = x, y, z
        -- the gates near it that can be closed (a bridge only with a lever)
        local cands, pending = {}, {}
        e.bridges_unworked = {}
        local gatehouse_here, gatehouse_bridge = false, nil
        for _, b in ipairs(buildings) do
            if near(b, g) and is_gatehouse(b) then                             -- (0.105.23)
                gatehouse_here = true
                gatehouse_bridge = {x = b.x1, y = b.y1, z = b.z}               -- (0.105.30) for the wings
            end
            if near(b, g) then
                if b.kind == 'pending' then
                    table.insert(pending, b)
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
            for k in pairs(building_keys(b)) do blocked[k] = true end
        end
        if #cands > 0 and seals(starts, g, blocked) then
            -- keep only the ones it needs
            local keep = {}
            for _, b in ipairs(cands) do keep[b.id] = b end
            for _, b in ipairs(cands) do
                local without = {}
                for id, c in pairs(keep) do
                    if id ~= b.id then for k in pairs(building_keys(c)) do without[k] = true end end
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
                else
                    local okp, plan, why = pcall(plan_gatehouse, e, h)
                    if okp and plan then e.gatehouse = 'possible'
                    else e.gatehouse, e.gatehouse_why = 'none', okp and why or tostring(plan) end
                end
            end
        end
        if not e.sealed and #e.bridges_unworked > 0 and AI_LEVER_WAITING then
            -- a drawbridge there waits for its lever to be linked (the lever
            -- rule does it): it's being closed, not open
            e.closing = true
        end
        if not e.sealed and not e.closing and #pending > 0 then
            -- walls or doors planned there (the AI's own, or yours) would
            -- close it once built: it's being closed, leave it be
            for _, b in ipairs(cands) do
                for k in pairs(building_keys(b)) do blocked[k] = true end
            end
            for _, b in ipairs(pending) do
                for k in pairs(building_keys(b)) do blocked[k] = true end
            end
            if seals(starts, g, blocked) then e.closing = true end
        end
        if not e.sealed and not e.closing and e.width <= MAX_DOORS then
            -- no gate that closes it: doors on the opening's inside tiles.
            -- Tiles that already have a door (built or planned: some of an
            -- earlier set may have been refused) are left as they are; every
            -- other tile must be able to take one (plain floor, dry, free).
            local doors_here, walls_coming = {}, {}
            for _, b in ipairs(buildings) do
                if near(b, g) and (b.kind == 'door' or (b.kind == 'pending' and b.what == 'door')) then
                    for k in pairs(building_keys(b)) do doors_here[k] = true end
                elseif near(b, g) and b.kind == 'pending' and b.what == 'wall' then
                    for k in pairs(building_keys(b)) do walls_coming[k] = true end
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

function scan(now_tick)
    cache, edge_cache = {}, {}
    -- (0.105.0) citizens on a ledge or a treetop don't seed a fort of their own
    local fstarts = fort_starts(citizen_starts())
    local entrances, inside, n = find_entrances(fstarts, gate_buildings())
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
    -- number them anew: what was closed is carried by its spot, and the
    -- watcher's timers are kept
    local closed_at = {}
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed and GATES.closed[e.id] then closed_at[key(e.x, e.y, e.z)] = true end
    end
    local closed = {}
    for _, e in ipairs(entrances) do
        if closed_at[key(e.x, e.y, e.z)] then closed[e.id] = true end
    end
    GATES = {scanned = true, entrances = entrances, inside = inside, inside_tiles = n,
             scanned_tick = now_tick, armed = GATES.armed, closed = closed,
             closing_since = since, timer = GATES.timer, reopen_timer = GATES.reopen_timer,
             watch_error = GATES.watch_error, gone_ids = GATES.gone_ids, repulled = GATES.repulled,
             peak = GATES.peak, clear_looks = GATES.clear_looks}      -- (0.105.4 review)
    -- (0.105.23) a hatch its new lever link shut, with no watcher holding it: opened
    if not GATES.armed then pcall(open_lever_hatches) end
    return summary()
end

-- (0.105.0 review) a cut entrance's porch (the open area above its hatches)
-- reads as inside on the map, but a dwarf there is shut out when the hatches
-- lock: counted as outside
function citizens_outside()
    if not GATES.inside then return 0 end
    local porches = {}
    for _, e in ipairs(GATES.entrances or {}) do
        if e.porch then table.insert(porches, e.porch) end
    end
    local n = 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local k = key(u.pos.x, u.pos.y, u.pos.z)
        local out = not GATES.inside[k]
        for _, p in ipairs(porches) do if p[k] then out = true end end
        if out then n = n + 1 end
    end
    return n
end

-- (0.105.3) B (2 Nov): one thief left inside after a siege kept the only
-- hatch shut for 2.5 real hours (1-3 FPS, 6 citizens and 51 visitors shut
-- out). DF's walk groups ignore locked doors and hatches, so "can reach the
-- dwarves" can't tell an enemy inside from one queued at a shut door; the
-- map of the inside can. Inside: on that map, not on a cut entrance's porch,
-- and more than INTRUDER_GATE_MARGIN tiles from every opening (the bit of
-- tunnel in front of a gate reads as inside). nil: no map yet (a reload).
INTRUDER_GATE_MARGIN = 10
function inside_fort(pos)
    if not GATES.scanned or not GATES.inside then return nil end
    local k = key(pos.x, pos.y, pos.z)
    if not GATES.inside[k] then return false end
    for _, e in ipairs(GATES.entrances or {}) do
        if e.porch and e.porch[k] then return false end
        for _, ik in ipairs(e.inside_list or {}) do
            local x, y, z = unkey(ik)
            if math.abs(z - pos.z) <= 2 and math.abs(x - pos.x) <= INTRUDER_GATE_MARGIN
                    and math.abs(y - pos.y) <= INTRUDER_GATE_MARGIN then
                return false
            end
        end
    end
    return true
end

-- The ids of live, loose enemies standing inside the fort (at most 50), or
-- nil without a map of the inside
function intruders_inside()
    if not GATES.scanned or not GATES.inside then return nil end
    local out = {}
    for _, u in ipairs(df.global.world.units.active) do
        local ok, yes = pcall(function()
            return dfhack.units.isAlive(u) and not u.flags1.caged and not u.flags1.chained
                and not dfhack.units.isCitizen(u) and (dfhack.units.isDanger(u) or dfhack.units.isInvader(u))
                and inside_fort(u.pos) == true
        end)
        if ok and yes then table.insert(out, u.id) end
        if #out >= 50 then break end
    end
    return out
end

-- (0.105.4 review) visitors outside the map of the inside (or on a cut
-- entrance's porch): the ones a shut gate keeps out. nil without a map
function visitors_outside()
    if not GATES.scanned or not GATES.inside then return nil end
    local n = 0
    for _, u in ipairs(df.global.world.units.active) do
        local ok, yes = pcall(function()
            if not (dfhack.units.isAlive(u) and dfhack.units.isVisitor(u) and not dfhack.units.isCitizen(u)) then
                return false
            end
            local k = key(u.pos.x, u.pos.y, u.pos.z)
            if not GATES.inside[k] then return true end
            for _, e in ipairs(GATES.entrances or {}) do
                if e.porch and e.porch[k] then return true end
            end
            return false
        end)
        if ok and yes then n = n + 1 end
    end
    return n
end

local function pull(lever_id)
    -- (0.100, review) a pull already waiting at the lever: a second would undo it
    local okp, pending = pcall(function()
        local lv = df.building.find(lever_id)
        for _, j in ipairs(lv and lv.jobs or {}) do
            if j.job_type == df.job_type.PullLever then return true end
        end
        return false
    end)
    if okp and pending then return false end
    local out, rv = dfhack.run_command_silent('lever', 'pull', '--id', tostring(lever_id))
    return rv == CR_OK
end

-- (0.100, review) a lowering drawbridge crushes whatever stands where it
-- comes down: it isn't lowered while a creature is on its tiles
function bridge_occupied(b)
    local ok, yes = pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if not dfhack.units.isDead(u) and u.pos.z == b.z and u.pos.x >= b.x1 and u.pos.x <= b.x2
                    and u.pos.y >= b.y1 and u.pos.y <= b.y2 then
                return true
            end
        end
        return false
    end)
    return not ok or yes       -- can't tell: treat it as occupied
end

-- (0.105.23, 14.1 step 4a) A lever pulled at once (DFHack's `lever pull
-- --instant`: no dwarf runs to it), as ai-builder's shaft gate does. A pull
-- a dwarf is on the way to make is called off first: arriving late it would
-- toggle the gate back. Tests replace this.
function pull_instant(lever_id)
    pcall(function()
        local lv = df.building.find(lever_id)
        local jobs = {}
        for _, j in ipairs(lv and lv.jobs or {}) do
            if j.job_type == df.job_type.PullLever then table.insert(jobs, j) end
        end
        for _, j in ipairs(jobs) do dfhack.job.removeJob(j) end
    end)
    local ok, out, rv = pcall(dfhack.run_command_silent, 'lever', 'pull', '--id', tostring(lever_id), '--instant')
    return ok and rv == CR_OK
end

-- (0.105.23) Is this door or hatch shut now (DF's `closed`)? nil if unread.
function door_shut(b)
    local ok, c = pcall(function() return b.door_flags.closed end)
    if ok then return c == true end
    return nil
end

-- (0.105.26 seal fix) What the cavern seal (ai-threats) holds: {ids =
-- {building id = true}, levers = {lever id = true}}. While it stands the
-- watcher opens none of them (F lost 54 and C 12 to forgotten beasts that
-- came up through the caverns): not by its reopen, open_all or a lever's
-- hatch. Empty when it can't be read. Tests replace this.
function seal_holds()
    local ok, r = pcall(function() return reqscript('ai-threats').seal_holds() end)
    if ok and type(r) == 'table' and type(r.ids) == 'table' then
        r.levers = type(r.levers) == 'table' and r.levers or {}
        return r
    end
    return {ids = {}, levers = {}}
end

-- Is this gate held by the seal (h: seal_holds())?
function seal_has(h, g)
    if not h or not g then return false end
    return (h.ids[g.id] or (g.drive_lever ~= nil and h.levers[g.drive_lever])
        or (g.lever_id ~= nil and h.levers[g.lever_id])) and true or false
end

-- Does the seal hold any gate of this entrance?
function sealed_entrance(e, h)
    h = h or seal_holds()
    for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
        for _, g in ipairs(list) do
            if seal_has(h, g) then return true end
        end
    end
    return false
end

-- (0.105.23) A door or hatch on a lever, set by its lever: true if it was
-- pulled. Without a lever of this entrance's own to pull, it's only locked
-- (as before 0.105.23). `pulled` keeps one pull per lever per call.
local function set_lever_door(g, b, close, pulled)
    if not g.drive_lever then
        if b.door_flags.forbidden ~= close then b.door_flags.forbidden = close; return true end
        return false
    end
    if not close and b.door_flags.forbidden then b.door_flags.forbidden = false end   -- (a lock left from before the link)
    local shut = door_shut(b)
    if shut == nil or shut == close or pulled[g.drive_lever] then return false end
    pulled[g.drive_lever] = true
    return pull_instant(g.drive_lever)
end

local function set_bridge(g, b, close)
    local ok, c = pcall(function() return b.gate_flags.raised end)   -- (13c) not `closed`
    -- lowering (opening) waits while anyone stands where it comes down;
    -- raising goes ahead (a threat is why it's raised)
    return ok and c ~= close and g.lever_id and #b.jobs == 0 and (close or not bridge_occupied(b))
        and pull(g.lever_id) or false
end

-- Close (or open) one entrance's gates. (0.105.23) A gatehouse's outer
-- drawbridge is raised before the hatch shuts, and lowered after it opens.
local function set_entrance(e, close)
    local done, pulled = 0, {}
    -- (0.105.26 seal fix) opening: what the cavern seal holds stays shut
    -- (and keeps the entrance closed: tried again once the seal is gone)
    local held, kept = not close and seal_holds() or nil, 0
    local function outer()
        for _, g in ipairs(e.outer or {}) do
            local b = df.building.find(g.id)
            if b and held and seal_has(held, g) then
                kept = kept + 1
            elseif b and set_bridge(g, b, close) then done = done + 1 end
        end
    end
    if close then outer() end
    for _, g in ipairs(e.equipment) do
        local b = df.building.find(g.id)
        if b and held and seal_has(held, g) then
            kept = kept + 1
        elseif b then
            if g.kind == 'bridge' then
                if set_bridge(g, b, close) then done = done + 1 end
            elseif g.lever_driven then
                if set_lever_door(g, b, close, pulled) then done = done + 1 end
            else
                if b.door_flags.forbidden ~= close then
                    b.door_flags.forbidden = close
                    done = done + 1
                end
            end
        end
    end
    if not close then outer() end
    -- (0.100, review) a bridge left up (someone on it, a pull waiting) keeps
    -- the entrance closed, so opening tries it again; (0.105.23) so does a
    -- lever's hatch still shut, and the gatehouse's bridge
    local waiting = kept
    if not close then
        for _, list in ipairs({e.equipment, e.outer or {}}) do
            for _, g in ipairs(list) do
                local b = df.building.find(g.id)
                if b and held and seal_has(held, g) then
                    -- (counted above)
                elseif b and g.kind == 'bridge' then
                    local ok, raised = pcall(function() return b.gate_flags.raised end)
                    if ok and raised then waiting = waiting + 1 end
                elseif b and g.lever_driven and g.drive_lever and door_shut(b) then
                    waiting = waiting + 1
                end
            end
        end
    end
    GATES.closed[e.id] = (close or waiting > 0) or nil   -- (a pull on its way still reads raised: retried harmlessly)
    return done
end

-- (0.105.23, 14.1 step 4a) A hatch (or door) its lever's link shut: DF
-- shuts a door or hatch when a lever is linked to it, and the founding
-- stair's hatch is every fort's way in, so it would stay shut with the
-- dwarves on either side of it. Opened at once by its lever wherever the
-- watcher doesn't hold the entrance shut. Only the surface's gates, and
-- only by an "AI gate..." lever that works nothing outside this entrance (a
-- cavern well's shaft hatch is its own rule's; the player's own levers are
-- theirs). only_e: that entrance alone. Returns how many were opened.
function open_lever_hatches(only_e)
    local opened = 0
    for _, e in ipairs(only_e and {only_e} or GATES.entrances or {}) do
        if e.kind == 'surface' and not (GATES.closed and GATES.closed[e.id]) then
            local pulled, held = {}, nil
            for _, g in ipairs(e.equipment or {}) do
                if g.lever_driven and g.drive_lever and g.drive_ai and not pulled[g.drive_lever] then
                    local b = df.building.find(g.id)
                    held = (b and door_shut(b)) and (held or seal_holds()) or held   -- (0.105.26 seal fix)
                    if b and door_shut(b) and not seal_has(held, g) then
                        pulled[g.drive_lever] = true
                        if pull_instant(g.drive_lever) then opened = opened + 1 end
                    end
                end
            end
        end
    end
    if opened > 0 then
        GATES.lever_opened = (GATES.lever_opened or 0) + opened
        pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %d gate(s) on a lever opened (no danger near)'):format(opened),
              COLOR_GREEN, false)
    end
    return opened
end

-- (0.105.23) A link the mechanic has just made: the gate takes the lever at
-- once (no wait for the weekly scan), so the watcher can work it and the
-- hatch the link shut is opened; a full rescan is asked for too (the
-- report's `rescan`). Returns how many gates took a lever.
function attach_links()
    local levers, pos = lever_links()
    local n = 0
    for _, e in ipairs(GATES.entrances or {}) do
        for _, g in ipairs(e.equipment or {}) do
            if g.kind ~= 'bridge' and levers[g.id] then
                local have = {}
                for _, l in ipairs(g.levers or {}) do have[l.id] = true end
                local new = false
                for _, lid in ipairs(levers[g.id]) do
                    if not have[lid] and pos[lid] then
                        g.levers = g.levers or {}
                        local p = pos[lid]
                        table.insert(g.levers, {id = lid, x = p.x, y = p.y, z = p.z, name = p.name,
                                                targets = lever_targets(levers, lid)})
                        new = true
                    end
                end
                if new then
                    g.lever_driven = true
                    g.lever_id = g.lever_id or g.levers[1].id
                    n = n + 1
                end
            end
        end
    end
    if n > 0 then
        drive_levers(GATES.entrances)
        GATES.rescan = true
    end
    return n
end

-- A link job waiting at an "AI gate..." lever?
function link_jobs_pending()
    local ok, yes = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and ai_lever_name(b.name) then
                for _, j in ipairs(b.jobs) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then return true end
                end
            end
        end
        return false
    end)
    return ok and yes
end

-- The link watch: while a link job waits at an AI lever, every CHECK_TICKS
-- the new links are taken up and a hatch they shut is opened.
LINK_WATCH = LINK_WATCH or {}
local function link_watch_tick()
    LINK_WATCH.timer = nil
    pcall(attach_links)
    if not GATES.armed then pcall(open_lever_hatches) end
    if link_jobs_pending() then
        LINK_WATCH.timer = dfhack.timeout(CHECK_TICKS, 'ticks', link_watch_tick)
    end
end

function link_watch_start()
    local ok, active = pcall(function() return LINK_WATCH.timer and dfhack.timeout_active(LINK_WATCH.timer) end)
    if ok and active then return false end
    LINK_WATCH.timer = dfhack.timeout(CHECK_TICKS, 'ticks', link_watch_tick)
    return true
end

-- (0.105.3) A (2 Nov, 09:36): "The Human Swordsman was spotted sneaking
-- around!", the hatch shut with 9 citizens outside, then he hid again and
-- nothing visible was left, yet the hatch stayed shut (1 FPS). Only VISIBLE
-- dangers count now (a hidden one isn't seen by anyone; the brain's report
-- leaves them out too): {pos, invader}. Tests replace this.
function visible_dangers()
    local out = {}
    for _, u in ipairs(df.global.world.units.active) do
        local ok, yes = pcall(function()
            return dfhack.units.isAlive(u) and not u.flags1.caged and not u.flags1.chained
                and not dfhack.units.isCitizen(u) and not dfhack.units.isHidden(u)
                and (dfhack.units.isDanger(u) or dfhack.units.isInvader(u))
        end)
        if ok and yes then
            local oki, inv = pcall(dfhack.units.isInvader, u)
            local okg, great = pcall(dfhack.units.isGreatDanger, u)      -- (0.105.4 review)
            table.insert(out, {pos = u.pos, invader = oki and inv or false, great = okg and great or false})
        end
    end
    return out
end

local function dangers()
    local out = {}
    for _, d in ipairs(visible_dangers()) do table.insert(out, d.pos) end
    return out
end

-- (0.105.3) A gate the watcher shut opens again (the watcher stays armed and
-- shuts it again if danger comes) once, for REOPEN_CHECKS looks in a row
-- (half a day), no visible invader is on the map and no other visible
-- danger is within REOPEN_CLEAR tiles of it. A siege in sight keeps it shut.
-- (0.105.4 review) Not while a great danger (titan, forgotten beast) is in
-- sight, however far; not after more than REOPEN_PEAK_MAX dangers were seen
-- at once since the watcher was armed (a bigger ambush that hid again keeps
-- the brain's normal quiet wait; unknown after a reload: kept shut too); and
-- the clear distance is WIDE, the same the watcher shuts at, so no band
-- between them flips the gate every half day.
REOPEN_CHECKS = 6
REOPEN_PEAK_MAX = 2
function may_reopen(nearest, invaders, great, peak)
    return invaders == 0 and (great or 0) == 0 and type(peak) == 'number' and peak <= REOPEN_PEAK_MAX
        and nearest > WIDE
end

function distance_to(e, pos)
    local best = math.huge
    local function near(x, y, z)
        if math.abs(z - pos.z) <= 3 then
            local d = math.max(math.abs(x - pos.x), math.abs(y - pos.y))
            if d < best then best = d end
        end
    end
    for k in pairs(e.outs) do near(unkey(k)) end
    -- (0.105.0 review) a cut entrance: its hatches too (a beast deep in a big
    -- porch is far from the opening but close to the way down)
    for _, k in ipairs(e.hatch_keys or {}) do near(unkey(k)) end
    return best
end

-- Close an entrance now? Danger right at it, or danger coming and nobody
-- left outside.
function should_close(nearest, outside)
    return nearest <= IMMINENT or (nearest <= WIDE and outside == 0)
end

-- One look by the watcher: close what needs closing.
function check()
    if not GATES.armed or not GATES.entrances then return end
    local vis = visible_dangers()
    local ds, invaders, great = {}, 0, 0
    for _, d in ipairs(vis) do
        table.insert(ds, d.pos)
        if d.invader then invaders = invaders + 1 end
        if d.great then great = great + 1 end
    end
    if type(GATES.peak) == 'number' then GATES.peak = math.max(GATES.peak, #vis) end
    local outside = citizens_outside()
    GATES.clear_looks = GATES.clear_looks or {}
    for _, e in ipairs(GATES.entrances) do
        if GATES.closed[e.id] and #e.equipment > 0 then
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            if may_reopen(nearest, invaders, great, GATES.peak) then
                GATES.clear_looks[e.id] = (GATES.clear_looks[e.id] or 0) + 1
                -- (0.105.26 seal fix) not while the cavern seal holds any of
                -- its gates (a hidden forgotten beast is out of sight, not
                -- gone): kept shut, and opened at the first look after the seal
                if GATES.clear_looks[e.id] >= REOPEN_CHECKS and sealed_entrance(e) then
                    GATES.seal_kept = (GATES.seal_kept or 0) + 1
                elseif GATES.clear_looks[e.id] >= REOPEN_CHECKS then
                    GATES.clear_looks[e.id] = nil
                    set_entrance(e, false)
                    GATES.reopened = (GATES.reopened or 0) + 1
                    pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s opened again (no danger in sight, %d citizens outside)')
                        :format(gate_name(e), outside), COLOR_GREEN, true)
                    goto continue
                end
            else
                GATES.clear_looks[e.id] = nil
            end
        end
        local watched = {}                    -- (0.105.23) the gatehouse's bridge watched too
        for _, g in ipairs(e.equipment) do table.insert(watched, g) end
        for _, g in ipairs(e.outer or {}) do table.insert(watched, g) end
        local repulled, drift_open = {}, false
        for _, g in ipairs(watched) do
            local b = df.building.find(g.id)
            GATES.gone_ids = GATES.gone_ids or {}
            GATES.repulled = GATES.repulled or {}
            if not b then
                -- (0.104.139) a gate gone (Teacheroar's hatch 278, toppled in a
                -- tantrum) left the entrance open until the weekly scan: scan
                -- again (once for each one gone)
                if not GATES.gone_ids[g.id] then
                    GATES.gone_ids[g.id] = true
                    GATES.scanned = false
                    GATES.gone = (GATES.gone or 0) + 1
                end
            elseif GATES.closed[e.id] and g.kind == 'bridge' and g.lever_id then
                -- (0.104.139) closed, but the pull's job was lost: the bridge is
                -- still down, not moving. Pulled again, not within 10 checks of
                -- the last (a pull is a dwarf's job: a second undoes the first)
                local ok, still = pcall(function()
                    local f = b.gate_flags
                    return not f.raised and not f.raising and not f.lowering
                end)
                local now = df.global.cur_year_tick or 0
                local last = GATES.repulled[g.id]
                if ok and still and #b.jobs == 0 and (not last or now < last or now - last > 10 * CHECK_TICKS) then
                    GATES.repulled[g.id] = now
                    pcall(pull, g.lever_id)
                end
            elseif GATES.closed[e.id] and g.kind ~= 'bridge' and g.lever_driven and g.drive_lever
                    and door_shut(b) == false then
                -- (0.105.26 seal fix) a lever's hatch the watcher holds shut
                -- reads open (the seal opened it, the player pulled it, a pull
                -- went astray): its lever pulled again, at once. Still open
                -- after: the watcher's view corrected (not closed), so its
                -- next look decides again
                if not repulled[g.drive_lever] then
                    repulled[g.drive_lever] = true
                    local okp, done = pcall(pull_instant, g.drive_lever)
                    GATES.hatch_repulled = (GATES.hatch_repulled or 0) + 1
                    if not (okp and done) then drift_open = true end
                end
                if door_shut(b) == false then drift_open = true end
            end
        end
        if drift_open then GATES.closed[e.id] = nil end
        if not GATES.closed[e.id] and #e.equipment > 0 then
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            if should_close(nearest, outside) then
                set_entrance(e, true)
                pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s closed (danger %s tiles away, %d citizens outside)')
                    :format(gate_name(e), nearest == math.huge and '?' or tostring(nearest), outside), COLOR_YELLOW, true)
            else
                -- (0.105.23) open while the watcher doesn't shut it: a lever's
                -- hatch its link shut is opened (citizens outside get back in)
                pcall(open_lever_hatches, e)
            end
        end
        ::continue::
    end
end

-- (0.104.81, 13c) a watcher that errors closes nothing: its error is kept
-- for the report (the brain says it) instead of vanishing in the pcall
local function watched_check()
    local ok, err = pcall(check)
    if ok then
        GATES.watch_error = nil
    else
        local w = GATES.watch_error or {n = 0}
        w.n, w.error, w.tick = w.n + 1, tostring(err):sub(1, 200), df.global.cur_year_tick
        GATES.watch_error = w
    end
end

local function tick()
    if not GATES.armed then return end
    watched_check()
    GATES.timer = dfhack.timeout(CHECK_TICKS, 'ticks', tick)
end

function arm()
    if not GATES.scanned then return {ok = false, rejected = true, error = 'entrances not scanned yet'} end
    if not GATES.armed then
        -- (0.100, review) gates still waiting to open: forgotten; the watcher
        -- closes what needs closing from the bridges as they stand
        if GATES.reopen_timer then pcall(dfhack.timeout_active, GATES.reopen_timer, nil) end
        GATES.reopen_timer, GATES.closed = nil, {}
        GATES.peak, GATES.clear_looks = 0, {}       -- (0.105.4 review) dangers seen at once since armed
        GATES.armed = true
        GATES.timer = dfhack.timeout(CHECK_TICKS, 'ticks', tick)
        watched_check()
    end
    return {ok = true, armed = true}
end

-- (0.100, review) gates left closed when the rest opened (someone stood on
-- a bridge): tried again every CHECK_TICKS until they're open, or the
-- watcher is armed again
local function reopen_tick()
    GATES.reopen_timer = nil
    if GATES.armed or not GATES.closed or next(GATES.closed) == nil then return end
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed[e.id] then pcall(set_entrance, e, false) end
    end
    if next(GATES.closed) ~= nil then
        GATES.reopen_timer = dfhack.timeout(CHECK_TICKS, 'ticks', reopen_tick)
    end
end

function open_all()
    GATES.armed = false
    if GATES.timer then dfhack.timeout_active(GATES.timer, nil) end
    GATES.timer = nil
    local opened = 0
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed and GATES.closed[e.id] then
            set_entrance(e, false)
            if not GATES.closed[e.id] then opened = opened + 1 end
        end
    end
    GATES.closed = GATES.closed or {}
    pcall(open_lever_hatches)            -- (0.105.23) a lever's hatch its link shut
    local waiting = 0
    for _ in pairs(GATES.closed) do waiting = waiting + 1 end
    if waiting > 0 and not (GATES.reopen_timer and dfhack.timeout_active(GATES.reopen_timer)) then
        GATES.reopen_timer = dfhack.timeout(CHECK_TICKS, 'ticks', reopen_tick)
    end
    return {ok = true, opened = opened, waiting = waiting > 0 and waiting or nil}
end

-- Placing one building with quickfort; returns placed (bool) and, when it
-- isn't, what quickfort counted instead (e.g. build_unsuitable), so a refusal
-- can say why.
place_hook = nil       -- tests replace this
local function place(key_text, pos)
    if place_hook then return place_hook(key_text, pos) end
    local qf = reqscript('quickfort')
    -- the same data shape ai-builder uses: {[z] = {[y] = {[x] = text}}}
    local data = {[pos.z] = {[pos.y] = {[pos.x] = key_text}}}
    local ok, stats = pcall(qf.apply_blueprint, {mode = 'build', data = data,
                                                 pos = {x = 0, y = 0, z = 0}, command = 'run'})
    if not ok then return false, tostring(stats):sub(1, 80) end
    if stats.build_designated and stats.build_designated.value > 0 then return true end
    local why = {}
    for name, v in pairs(stats) do
        if type(v) == 'table' and (v.value or 0) > 0 and name ~= 'build_designated' then
            table.insert(why, name)
        end
    end
    local seen = what_is_there(pos)
    return false, (#why > 0 and table.concat(why, ',') or 'not placed') .. (seen and (' ' .. seen) or '')
end

-- What's on a tile, in a few words, so a refusal says why ("SAPLING, a
-- building"). nil if it can't be read.
function what_is_there(pos)
    local ok, text = pcall(function()
        local tt = dfhack.maps.getTileType(pos.x, pos.y, pos.z)
        if not tt then return nil end
        local attrs = df.tiletype.attrs[tt]
        local bits = {df.tiletype_shape[attrs.shape] or '?', df.tiletype_material[attrs.material] or '?'}
        local des, occ = dfhack.maps.getTileFlags(pos.x, pos.y, pos.z)
        if des and des.flow_size > 0 then table.insert(bits, ('liquid %d/7'):format(des.flow_size)) end
        local b = dfhack.buildings.findAtTile(xyz2pos(pos.x, pos.y, pos.z))
        if b then
            local kind = df.building_type[b:getType()] or 'building'
            table.insert(bits, kind .. (b:getBuildStage() < b:getMaxBuildStage() and ' (planned)' or ''))
        end
        if des and des.dig ~= df.tile_dig_designation.No then table.insert(bits, 'designated to dig') end
        return ('at x%d y%d (%s)'):format(pos.x, pos.y, table.concat(bits, ', '))
    end)
    return ok and text or nil
end

local function entrance(id)
    for _, x in ipairs(GATES.entrances or {}) do if x.id == id then return x end end
    return nil
end

-- Doors on an open entrance's narrow opening (buildingplan waits for doors).
function build_doors(id)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if #e.door_spots == 0 then return {ok = false, rejected = true, error = 'no door spots for this entrance'} end
    local placed, why = 0, {}
    for _, sp in ipairs(e.door_spots) do
        local ok, reason = place('d', sp)
        if ok then placed = placed + 1 else table.insert(why, reason) end
    end
    if placed == 0 then
        return {ok = false, error = 'no door could be placed there (' .. table.concat(why, '; ') .. ')'}
    end
    return {ok = true, doors = placed}
end

---------------------------------------------------------------------------
-- Fortifying a wide opening in the fort's gate style (brain/culture.py
-- gate_style): walls across it leaving a gap, doors in the gap, and by style
-- a second door behind, cage traps, flanking statues. Checked first: the
-- walls and doors must seal the opening and must not cut the fort apart.
---------------------------------------------------------------------------

-- (grand is 2, not 3: the middle door of a 3-wide gap would never have a wall
-- beside it, and DF only builds a door next to a wall)
GAP = {plain = 2, narrow = 1, fortified = 1, gatehouse = 1, grand = 2, drawbridge = 2,
       sealed = 0}       -- (0.105.30) walls only, no door: a cavern opening walled for good (plan_sealed)

local function nbrs4(k)
    local x, y, z = unkey(k)
    return {key(x + 1, y, z), key(x - 1, y, z), key(x, y + 1, z), key(x, y - 1, z)}
end

-- The pieces, as keys: walls, doors, inner doors, traps, statues.
-- doors_present: keys of opening tiles that already have a door (built or
-- planned): they become the gate, and walls go on the rest.
-- Why a line of tiles can't take walls and doors, or nil if it can.
local function line_blocked(list, doors_present)
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local t = nil
        if not doors_present[k] then t = T(x, y, z) end
        if t and not WALL_GROUND[t.shape] then
            return ('the way in at x%d y%d is a %s, which walls and doors can\'t stand on'):format(
                x, y, tostring(t.shape):lower():gsub('_', ' ')), k
        end
        if t and (t.occupied or t.liquid) then
            local seen = what_is_there and what_is_there({x = x, y = y, z = z}) or ('at x%d y%d'):format(x, y)
            local hint = (t.liquid or seen:find('liquid')) and 'water or magma stands there'
                or seen:find('Bridge') and 'a bridge with no lever linked'
                or seen:find('Stockpile') and 'a stockpile the AI could not move'
                or 'something built there'
            return 'something is already in the opening ' .. seen .. ' (' .. hint .. ')', k
        end
    end
    return nil
end

-- The next line in: the inside tiles one step further from the outside.
-- Returns the new line and the outs grown by the old line.
MAX_STEPS_IN = 3
MAX_LINE_IN = 12
local function step_in(list, outs)
    local grown = {}
    for k in pairs(outs) do grown[k] = true end
    for _, k in ipairs(list) do grown[k] = true end
    local line, seen = {}, {}
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if grown[nk] or seen[nk] then return end
                if inside_or_courtyard(T(nx, ny, nz), nk) then
                    seen[nk] = true
                    table.insert(line, nk)
                end
            end)
        end
    end
    table.sort(line)
    return line, grown
end

-- Stairs as the way in, with the outside only straight below them: a hatch
-- on the stair closes the way down. {stair keys} or nil.
local STAIR_DOWN_SHAPES = {STAIR_DOWN = true, STAIR_UPDOWN = true}
local function hatch_spots(e)
    local spots = {}
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if not (t and STAIR_DOWN_SHAPES[t.shape] and not t.occupied and not t.liquid) then return nil end
        -- every outside tile it touches must be on the level below
        local touches, below_only = false, true
        moves(x, y, z, t, function(nx, ny, nz)
            if e.outs[key(nx, ny, nz)] then
                touches = true
                -- straight below only: a ramp beside it below would walk
                -- up onto a closed hatch (a hatch is only a lid)
                if not (nx == x and ny == y and nz == z - 1) then below_only = false end
            end
        end)
        if not (touches and below_only) then return nil end
        table.insert(spots, k)
    end
    return #spots > 0 and spots or nil
end

-- The other way round: stairs whose outside is only straight ABOVE them (a
-- fort's first shaft: the way out is the stair's top on the surface). A
-- hatch on that top stair is a lid on the shaft. {top keys} or nil.
local function hatch_spots_above(e)
    local spots, seen = {}, {}
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if not (t and STAIR_UP[t.shape]) then return nil end
        local touches, above_only = false, true
        moves(x, y, z, t, function(nx, ny, nz)
            if e.outs[key(nx, ny, nz)] then
                touches = true
                if not (nx == x and ny == y and nz == z + 1) then above_only = false end
            end
        end)
        if not (touches and above_only) then return nil end
        local top = T(x, y, z + 1)
        if not (top and STAIR_DOWN_SHAPES[top.shape] and not top.occupied and not top.liquid) then return nil end
        local tk = key(x, y, z + 1)
        if not seen[tk] then
            seen[tk] = true
            table.insert(spots, tk)
        end
    end
    return #spots > 0 and spots or nil
end

---------------------------------------------------------------------------
-- Water in an opening: the AI looks before it acts. investigate_water()
-- follows the water from the opening (on its level and the ones below, up to
-- WATER_SCAN_MAX tiles) and says what it is: how big and deep, natural (a
-- river, brook, pool or the aquifer) or made by dwarves (constructed walls
-- or floors round it, a pump or floodgate in it), and what uses it (a well
-- over it). plan_gate then picks, safest first: a dry line further in; the
-- dry shore around the water, with the water left outside (not if a well or
-- the fort's waterworks use it); or, when only deep water connects the
-- opening to the outside, nothing at all: walkers can't cross deep water, so
-- the water itself is the gate, and the AI notes it rather than asking you.
---------------------------------------------------------------------------

WATER_SCAN_MAX = 3000
DEEP = 4                -- 4/7 and deeper: walkers don't path through it
MAX_SHORE = 16          -- longest shore line the AI walls

local WORKS = {Well = true, ScrewPump = true, Floodgate = true, WaterWheel = true}

function investigate_water(e)
    local start = {}
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then table.insert(start, k) end
    end
    for k in pairs(e.outs) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then table.insert(start, k) end
    end
    if #start == 0 then return nil end
    local W, H = map_size()
    local seen, queue, head = {}, {}, 1
    for _, k in ipairs(start) do if not seen[k] then seen[k] = true; table.insert(queue, k) end end
    local r = {tiles = 0, deep = 0, shallow = 0, max_depth = 0, salt = false, stagnant = false, magma = false,
               aquifer = false, outside = 0, edge = false, materials = {}, levels = {}, rim = 0,
               rim_built = 0, works = {}, wells = 0, truncated = false, region = seen}
    while head <= #queue do
        local k = queue[head]
        head = head + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        r.tiles = r.tiles + 1
        if r.tiles >= WATER_SCAN_MAX then r.truncated = true break end
        local d = t.depth or (t.liquid and 7 or 0)
        if d >= DEEP then r.deep = r.deep + 1 else r.shallow = r.shallow + 1 end
        r.max_depth = math.max(r.max_depth, d)
        r.salt = r.salt or t.salt == true
        r.stagnant = r.stagnant or t.stagnant == true
        r.magma = r.magma or t.magma == true
        r.aquifer = r.aquifer or t.aquifer == true
        if t.outside then r.outside = r.outside + 1 end
        if x <= 0 or y <= 0 or x >= W - 1 or y >= H - 1 then r.edge = true end
        if t.material then r.materials[t.material] = (r.materials[t.material] or 0) + 1 end
        r.levels[z] = true
        local b = building_at(x, y, z)
        if b and WORKS[b] then r.works[b] = (r.works[b] or 0) + 1 end
        -- a well's bucket drops through open levels, and a pump stands over the
        -- water it draws: look up to 6 levels above
        for dz = 1, 6 do
            local above = building_at(x, y, z + dz)
            if above == 'Well' then r.wells = r.wells + 1 break end
            if above == 'ScrewPump' then r.works.ScrewPump = (r.works.ScrewPump or 0) + 1 break end
            local at = T(x, y, z + dz)
            if at and at.shape == 'WALL' then break end
        end
        for dx = -1, 1 do
            for dy = -1, 1 do
                for dz = -1, 0 do
                    if dx ~= 0 or dy ~= 0 or dz ~= 0 then
                        local nk = key(x + dx, y + dy, z + dz)
                        if not seen[nk] then
                            local nt = T(x + dx, y + dy, z + dz)
                            if nt and nt.liquid then
                                seen[nk] = true
                                table.insert(queue, nk)
                            elseif nt and dz == 0 and (dx == 0 or dy == 0) then
                                -- the rim: is it built by dwarves?
                                r.rim = r.rim + 1
                                if nt.material == 'CONSTRUCTION' then r.rim_built = r.rim_built + 1 end
                            end
                        end
                    end
                end
            end
        end
    end
    -- what it is
    -- (what made the water decides the kind; works in it are said separately:
    -- a lake with a floodgate is natural water the dwarves use, not a cistern)
    local m = r.materials
    if r.magma then r.kind = 'magma'
    elseif (m.RIVER or 0) + (m.BROOK or 0) > 0 then r.kind = 'river'
    elseif (r.rim > 0 and r.rim_built * 4 >= r.rim) or (m.CONSTRUCTION or 0) * 4 >= r.tiles then
        r.kind = 'dwarf-made'
    elseif r.aquifer then r.kind = 'aquifer'
    elseif (m.POOL or 0) > 0 or r.outside > 0 or r.tiles >= 500 then r.kind = 'natural water'
    else r.kind = 'standing water' end
    r.natural = r.kind ~= 'dwarf-made'
    -- can walkers get in at all? Block the deep water and walk in from the outside.
    local deep_keys = {}
    for k in pairs(seen) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and (t.depth or 7) >= DEEP then deep_keys[k] = true end
    end
    r.walkers_blocked = next(deep_keys) ~= nil and seals(e.starts or {}, {outs = e.outs}, deep_keys)
    return r
end

-- The investigation in plain words.
function describe_water(r)
    if not r then return 'no water found there' end
    local works = {}
    for kind, n in pairs(r.works) do table.insert(works, ('%d %s'):format(n, kind:lower())) end
    if r.wells > 0 then table.insert(works, ('%d well(s) drawing from it'):format(r.wells)) end
    local lv = 0
    for _ in pairs(r.levels) do lv = lv + 1 end
    local bits = {('%s, %s%d tiles over %d level(s), up to %d/7 deep (%d tiles 4/7 or deeper)'):format(
        r.kind, r.truncated and 'more than ' or '', r.tiles, lv, r.max_depth, r.deep)}
    if r.salt then table.insert(bits, 'salt') end
    if r.stagnant then table.insert(bits, 'stagnant') end
    if r.edge then table.insert(bits, 'runs off the map') end
    if r.rim > 0 then table.insert(bits, ('%d of %d tiles of its edge built by dwarves'):format(r.rim_built, r.rim)) end
    if #works > 0 then table.insert(bits, 'used by ' .. table.concat(works, ', ')) end
    return table.concat(bits, '; ')
end

-- The dry shore round the water, inside the fort: the water (and the
-- opening) left outside. A line plan_line can wall, or nil.
local function shore_line(e, r)
    local outs = {}
    for k in pairs(e.outs) do outs[k] = true end
    for k in pairs(r.region) do outs[k] = true end
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then outs[k] = true end
    end
    local line, seen = {}, {}
    for k in pairs(r.region) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if outs[nk] or seen[nk] then return end
                local nt = T(nx, ny, nz)
                if nt and not nt.liquid and inside_or_courtyard(nt, nk) then
                    seen[nk] = true
                    table.insert(line, nk)
                end
            end)
        end
    end
    table.sort(line)
    return line, outs
end

-- The pieces, as keys: walls, doors, inner doors, traps, statues, support
-- walls (a wall beside a door that has none, so DF will build the door) and
-- hatches. When the opening itself can't take a gate (stairs, water, a
-- building, an unlinked bridge), the gate goes on the first clear line
-- further in (plan.moved_in steps), or a hatch closes stairs whose outside is
-- straight below. doors_present: keys of opening tiles that already have a
-- door (built or planned): they become the gate, and walls go on the rest.
---------------------------------------------------------------------------
-- (0.105.30, construction spec 3.4) The `sealed` style: a cavern opening up
-- to SEALED_MAX_WIDTH tiles walled shut, no door (the Hermit's hold). Only
-- when the fort uses nothing on that cavern layer (no cavern well, no
-- cistern drawing on a cavern lake there), no citizen stands beyond it (in
-- the cavern, in the walk group of its outside tiles, or on the opening),
-- and the walls cut nothing of the fort off (not a tile but the walls'
-- own). The pieces are recorded like any gate's, and clear_gate takes
-- built walls in a cavern opening down again.
---------------------------------------------------------------------------
SEALED_MAX_WIDTH = 3

local function layer_gid(x, y, z)
    local ok, gid = pcall(function()
        local b = dfhack.maps.getTileBlock(xyz2pos(x, y, z))
        return b and b.global_feature
    end)
    return ok and gid or nil
end

-- Why the fort uses this opening's cavern layer, or nil (tests replace this).
function sealed_layer_use(e)
    local out_k = next(e.outs or {})
    if not out_k then return 'its cavern side could not be read' end
    local gid = layer_gid(unkey(out_k))
    if gid == nil or gid < 0 then return 'its cavern layer could not be read' end
    local B
    local okb = pcall(function() B = reqscript('ai-builder') end)
    if not okb or not B then return 'the cavern wells could not be read' end
    local okw, wells = pcall(B.well_lids, false)
    if not okw then return 'the cavern wells could not be read' end
    for _, w in ipairs(wells or {}) do
        local h = type(w.shaft_hatch) == 'table' and w.shaft_hatch or w
        if h.x and layer_gid(h.x, h.y, h.z) == gid then
            return ('cavern well %s draws on that cavern'):format(tostring(w.project_id))
        end
    end
    local okc, d = pcall(B.cistern_data)
    if okc and type(d) == 'table' and type(d.plan) == 'table' then
        local p = d.plan
        if p.source == 'cavern lake' and type(p.water) == 'table' then
            local z = p.water.z or p.intake_z or (p.cistern and p.cistern.z)
            if z and layer_gid(p.water.x, p.water.y, z) == gid then return 'the cistern draws on a lake in that cavern' end
        end
    end
    return nil
end

-- Citizens beyond the opening: in the cavern, in the walk group of its
-- outside tiles, or standing on the opening (tests replace this).
function citizens_beyond(e)
    local groups, on = {}, {}
    for k in pairs(e.outs or {}) do
        local x, y, z = unkey(k)
        local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
        if ok and g and g ~= 0 then groups[g] = true end
    end
    for _, k in ipairs(e.inside_list or {}) do on[k] = true end
    local n = 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local p = u.pos
        if on[key(p.x, p.y, p.z)] then
            n = n + 1
        else
            local ok, yes = pcall(function()
                local des = dfhack.maps.getTileFlags(p.x, p.y, p.z)
                if not (des and (des.feature_global or des.feature_local)) then return false end
                local g = dfhack.maps.getWalkableGroup(xyz2pos(p.x, p.y, p.z))
                return g ~= 0 and groups[g] == true
            end)
            if not ok or yes then n = n + 1 end
        end
    end
    return n
end

function plan_sealed(e, starts)
    if e.kind ~= 'cavern' then return nil, 'a sealed gate walls a cavern opening only' end
    local width = #(e.inside_list or {})
    if width == 0 then return nil, 'the opening has no tiles' end
    if width > SEALED_MAX_WIDTH then
        return nil, ('the opening is %d wide: the AI walls cavern openings up to %d'):format(width, SEALED_MAX_WIDTH)
    end
    local why = line_blocked(e.inside_list, {})
    if why then return nil, why end
    local okl, use = pcall(sealed_layer_use, e)
    if not okl then return nil, 'the cavern layer could not be checked' end
    if use then return nil, 'the fort uses that cavern: ' .. use end
    local okc, n = pcall(citizens_beyond, e)
    if not okc then return nil, 'the citizens beyond it could not be counted' end
    if n > 0 then return nil, ('%d citizen%s beyond it in the cavern'):format(n, n == 1 and '' or 's') end
    local memo = {}
    local plan, why2 = plan_line(e, 'sealed', starts, {}, memo)
    if not plan then return nil, why2 end
    if #plan.walls ~= width or #plan.doors > 0 then return nil, 'the opening could not be walled whole' end
    -- the cistern's rule: the walls cut nothing of the fort off
    local wall_only = {}
    for _, k in ipairs(plan.walls) do wall_only[k] = true end
    local _, after = explore(starts, wall_only)
    if (memo.before or 0) - after > #plan.walls then
        return nil, ('walls there would cut off %d tiles of the fort'):format(memo.before - after - #plan.walls)
    end
    plan.sealed = true
    return plan
end

function plan_gate(e, style, starts, doors_present)
    if style == 'sealed' then return plan_sealed(e, starts) end         -- (0.105.30)
    doors_present = doors_present or {}
    -- (13c) the fort's size before any wall, flooded once for every line tried
    -- here (each plan_line flooded it again: up to 8 floods of the fort a plan)
    local memo = {}
    local why = line_blocked(e.inside_list, doors_present)
    if not why then return plan_line(e, style, starts, doors_present, memo) end
    cache = cache or {}
    edge_cache = edge_cache or {}
    local hatches, lid = hatch_spots(e), false
    if not hatches then hatches, lid = hatch_spots_above(e), true end
    if hatches then
        local blocked, outs = {}, {}
        for _, k in ipairs(hatches) do blocked[k] = true end
        if lid then
            -- a lid on the outside tiles: nothing gets down through them; the
            -- rest of the opening's outside (if any) must still be shut out
            for k in pairs(e.outs) do if not blocked[k] then outs[k] = true end end
            blocked = {}
        else
            outs = e.outs
        end
        if next(outs) == nil or seals(starts, {outs = outs}, blocked) then
            return {walls = {}, doors = {}, inner = {}, traps = {}, statues = {}, support = {},
                    hatches = hatches, kept_doors = 0}
        end
    end
    local line, outs = e.inside_list, e.outs
    local last
    for step = 1, MAX_STEPS_IN do
        line, outs = step_in(line, outs)
        if #line == 0 or #line > MAX_LINE_IN then break end
        if not line_blocked(line, {}) then
            local ve = {id = e.id, kind = e.kind, inside_list = line, outs = outs, width = #line}
            local plan, why2 = plan_line(ve, style, starts, {}, memo)
            if plan then
                plan.moved_in = step
                plan.moved_why = why
                return plan
            end
            last = why2
        end
    end
    -- water: look at it, then wall its dry shore, or let deep water be the gate
    local water = nil
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then water = true end
    end
    if water then
        e.starts = starts
        local r = investigate_water(e)
        e.starts = nil
        if r then
            local text = describe_water(r)
            if r.magma then
                return nil, why .. '; the AI looked: ' .. text .. ' (magma is never walled near by the AI)'
            end
            local uses = r.wells > 0 or next(r.works) ~= nil
            if not uses and not r.truncated then
                local shore, outs2 = shore_line(e, r)
                if #shore > 0 and #shore <= MAX_SHORE and not line_blocked(shore, {}) then
                    local ve = {id = e.id, kind = e.kind, inside_list = shore, outs = outs2, width = #shore}
                    local plan = plan_line(ve, style, starts, {}, memo)
                    if plan then
                        plan.shore, plan.water = true, text
                        plan.moved_why = why
                        return plan
                    end
                end
            end
            if r.walkers_blocked then
                -- nothing to build: deep water is the gate (swimmers aside)
                return {walls = {}, doors = {}, inner = {}, traps = {}, statues = {}, support = {},
                        hatches = {}, kept_doors = 0, water_gate = true, water = text}
            end
            return nil, why .. '; the AI looked: ' .. text .. (uses
                and ' (the fort uses this water, so the AI won\'t wall it off)'
                or ' (its dry shore is too long or blocked to wall)')
        end
    end
    local shape_hint = why:find('stair') and ' (a hatch only closes stairs whose way out is straight down)' or ''
    return nil, why .. shape_hint .. ', and no clear line for a gate within ' .. MAX_STEPS_IN
        .. ' tiles further in' .. (last and (': ' .. last) or '')
end

-- A wall beside a door tile that has none (DF builds a door only next to a
-- wall): an inside tile across the way in, not in the line, that walls off
-- nothing of the fort. nil if there's none.
local function support_for(k, in_list, outs, taken, walls_keys)
    local x, y, z = unkey(k)
    -- the way in runs along the axis where an outside tile (for an inner door:
    -- the gate door in front of it) touches the door; the support goes across it
    local axis
    for _, d in ipairs(ORTHO) do
        if outs[key(x + d[1], y + d[2], z)] then axis = d[1] ~= 0 and 'x' or 'y' end
    end
    for _, d in ipairs(ORTHO) do
        local across = (axis == 'x' and d[1] == 0) or (axis == 'y' and d[2] == 0) or axis == nil
        local nk = key(x + d[1], y + d[2], z)
        local t = T(x + d[1], y + d[2], z)
        -- (open space or a ramp top beside it can take a wall too: DF builds
        -- constructions there)
        if across and not in_list[nk] and not outs[nk] and not taken[nk] and t
                and WALL_GROUND[t.shape] and not t.occupied and not t.liquid
                and not t.outside and not t.feature and not t.special and not t.hidden then
            -- the door must still lead on into the fort past the new wall
            -- (checked here locally; the whole fort is checked with the plan)
            local onward = false
            moves(x, y, z, T(x, y, z), function(mx, my, mz)
                local mk = key(mx, my, mz)
                if mk ~= nk and not in_list[mk] and not outs[mk] and not walls_keys[mk]
                        and inside_or_courtyard(T(mx, my, mz), mk) then onward = true end
            end)
            if onward then return nk end
        end
    end
    return nil
end

-- memo (optional, one plan's): keeps the fort's size before walls between calls.
function plan_line(e, style, starts, doors_present, memo)
    local gap_n = GAP[style] or 2
    if style == 'plain' and e.kind == 'cavern' then gap_n = 1 end
    local list = e.inside_list
    -- the gap: the opening tile nearest the middle, grown along the opening
    local sx, sy, n = 0, 0, #list
    for _, k in ipairs(list) do
        local x, y = unkey(k)
        sx, sy = sx + x, sy + y
    end
    local cx, cy = sx / n, sy / n
    local in_list = {}
    for _, k in ipairs(list) do in_list[k] = true end
    local function d2(k) local x, y = unkey(k) return (x - cx) ^ 2 + (y - cy) ^ 2 end
    local first = list[1]
    for _, k in ipairs(list) do if d2(k) < d2(first) then first = k end end
    local gap, in_gap = {first}, {[first] = true}
    if gap_n == 0 then gap, in_gap = {}, {} end        -- (0.105.30) sealed: walls on every tile
    while #gap < gap_n do
        local best
        for _, g in ipairs(gap) do
            for _, nk in ipairs(nbrs4(g)) do
                if in_list[nk] and not in_gap[nk] and (not best or d2(nk) < d2(best)) then best = nk end
            end
        end
        if not best then break end
        table.insert(gap, best)
        in_gap[best] = true
    end
    if next(doors_present) then
        -- the doors already there are the gate: wall the rest around them
        gap, in_gap = {}, {}
        for _, k in ipairs(list) do
            if doors_present[k] then table.insert(gap, k); in_gap[k] = true end
        end
    end
    local walls = {}
    for _, k in ipairs(list) do if not in_gap[k] then table.insert(walls, k) end end
    -- inside the gap: the next tiles in (not the opening, not outside)
    local behind = {}
    for _, g in ipairs(gap) do
        for _, nk in ipairs(nbrs4(g)) do
            local x, y, z = unkey(nk)
            if not in_list[nk] and not e.outs[nk] and interior(T(x, y, z)) then
                table.insert(behind, nk)
                break
            end
        end
    end
    local new_doors = {}
    for _, k in ipairs(gap) do if not doors_present[k] then table.insert(new_doors, k) end end
    local plan = {walls = walls, doors = new_doors, inner = {}, traps = {}, statues = {},
                  support = {}, hatches = {}, kept_doors = #gap - #new_doors}
    if style == 'fortified' or style == 'gatehouse' then plan.inner = behind end
    if style == 'drawbridge' and #new_doors == #gap and #gap > 0 then
        -- a raising drawbridge over the gap instead of doors (worked by a
        -- lever inside, placed and linked afterwards). It must be a straight
        -- run of tiles, raised toward the outside.
        local x1, y1, x2, y2, z0
        for _, k in ipairs(gap) do
            local x, y, z = unkey(k)
            x1, y1 = math.min(x1 or x, x), math.min(y1 or y, y)
            x2, y2 = math.max(x2 or x, x), math.max(y2 or y, y)
            if z0 and z ~= z0 then x1 = nil break end
            z0 = z
        end
        if x1 and (x2 - x1 + 1) * (y2 - y1 + 1) == #gap then
            local dir = 'gx'
            for _, k in ipairs(gap) do
                local x, y, z = unkey(k)
                if e.outs[key(x, y - 1, z)] then dir = 'gw'
                elseif e.outs[key(x + 1, y, z)] then dir = 'gd'
                elseif e.outs[key(x, y + 1, z)] then dir = 'gx'
                elseif e.outs[key(x - 1, y, z)] then dir = 'ga' end
            end
            plan.bridge = {x = x1, y = y1, z = z0, w = x2 - x1 + 1, h = y2 - y1 + 1, dir = dir, keys = gap}
            plan.doors = {}
            new_doors = {}
        end
    end
    if style == 'gatehouse' then
        -- cage traps: the tiles just behind the inner doors
        local taken = {}
        for _, k in ipairs(behind) do taken[k] = true end
        for _, b in ipairs(behind) do
            for _, nk in ipairs(nbrs4(b)) do
                local x, y, z = unkey(nk)
                if #plan.traps < 3 and not taken[nk] and not in_list[nk] and interior(T(x, y, z)) then
                    table.insert(plan.traps, nk)
                    taken[nk] = true
                end
            end
        end
    end
    if style == 'grand' then
        -- statues: inside, against the new wall, either side of the gap
        for _, w in ipairs(walls) do
            for _, g in ipairs(gap) do
                local wx, wy = unkey(w)
                local gx, gy = unkey(g)
                if math.abs(wx - gx) + math.abs(wy - gy) == 1 then
                    for _, nk in ipairs(nbrs4(w)) do
                        local x, y, z = unkey(nk)
                        if #plan.statues < 2 and not in_list[nk] and not e.outs[nk] and interior(T(x, y, z)) then
                            table.insert(plan.statues, nk)
                            break
                        end
                    end
                end
            end
        end
    end
    -- doors with no wall beside them (built or in this plan): a support wall
    local walls_keys, taken = {}, {}
    for _, k in ipairs(walls) do walls_keys[k] = true; taken[k] = true end
    for _, k in ipairs(gap) do taken[k] = true end
    for _, k in ipairs(plan.inner) do taken[k] = true end
    for _, k in ipairs(plan.traps) do taken[k] = true end
    for _, k in ipairs(plan.statues) do taken[k] = true end
    local function needs_support(k)
        local x, y, z = unkey(k)
        if wall_beside(x, y, z) then return false end
        for _, nk in ipairs(nbrs4(k)) do if walls_keys[nk] then return false end end
        return true
    end
    local gap_keys = {}
    for _, k in ipairs(gap) do gap_keys[k] = true end
    for i, list2 in ipairs({new_doors, plan.inner}) do
        for _, k in ipairs(list2) do
            if needs_support(k) then
                local sk = support_for(k, in_list, i == 1 and e.outs or gap_keys, taken, walls_keys)
                if sk then
                    table.insert(plan.support, sk)
                    walls_keys[sk], taken[sk] = true, true
                end
            end
        end
    end
    -- checks: the walls and doors seal it; the walls don't cut the fort apart
    local blocked = {}
    for _, k in ipairs(walls) do blocked[k] = true end
    for _, k in ipairs(gap) do blocked[k] = true end
    if not seals(starts, {outs = e.outs}, blocked) then
        return nil, 'walls there would not seal it (the opening is irregular)'
    end
    local wall_only = {}
    for _, k in ipairs(walls) do wall_only[k] = true end
    for _, k in ipairs(plan.support) do wall_only[k] = true end
    memo = memo or {}
    if not memo.before then
        local _, n = explore(starts)
        memo.before = n
    end
    local before = memo.before
    if before >= MAX_TILES then
        return nil, 'the fort is too big for the AI to check that walls there would not cut it apart'
    end
    local _, after = explore(starts, wall_only)
    local n_walls = #walls + #plan.support
    if before - after > n_walls + 30 then
        return nil, ('walls there would cut off %d tiles of the fort'):format(before - after - n_walls)
    end
    return plan
end

---------------------------------------------------------------------------
-- A stockpile in the way of a gate: the AI moves it itself. The new pile
-- gets the old one's settings (DFHack's stockpiles export/import) and goes
-- on the part of the old pile that's clear of the opening, or, if too little
-- is left, on free floor nearby inside the fort. Items left on the old tiles
-- are hauled to it by the dwarves.
---------------------------------------------------------------------------

MOVE_CLEARANCE = 2     -- tiles kept free between the opening and the pile
MOVE_RADIUS = 25       -- how far from the old pile a new spot may be
MOVE_MIN_TILES = 4

-- The opening's tiles that already have a door, built or planned: {key = true}
-- (tests replace this).
function doors_in(list)
    local out = {}
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if b and b:getType() == df.building_type.Door then out[k] = true end
    end
    return out
end

-- The stockpiles on an opening's tiles: {building, ...} (tests replace this).
function stockpiles_in(list)
    local out, seen = {}, {}
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if b and b:getType() == df.building_type.Stockpile and not seen[b.id] then
            seen[b.id] = true
            table.insert(out, b)
        end
    end
    return out
end

-- The largest rectangle of tiles that pass ok(x, y), inside the box, no
-- bigger than max_side: {x, y, w, h} or nil.
local function best_rect(x1, y1, x2, y2, ok, max_side)
    local best, best_n
    for y = y1, y2 do
        for x = x1, x2 do
            if ok(x, y) then
                local w = 1
                while w < max_side and x + w <= x2 and ok(x + w, y) do w = w + 1 end
                local h = 1
                while h < max_side and y + h <= y2 do
                    local row = true
                    for dx = 0, w - 1 do if not ok(x + dx, y + h) then row = false break end end
                    if not row then break end
                    h = h + 1
                end
                if not best_n or w * h > best_n then best, best_n = {x = x, y = y, w = w, h = h}, w * h end
            end
        end
    end
    return best
end

-- Where the moved pile goes: {x, y, z, w, h} or nil, why.
function new_pile_spot(pile, avoid)
    local z = pile.z
    local function clear(x, y)
        for dx = -MOVE_CLEARANCE, MOVE_CLEARANCE do
            for dy = -MOVE_CLEARANCE, MOVE_CLEARANCE do
                if avoid[key(x + dx, y + dy, z)] then return false end
            end
        end
        return true
    end
    -- 1. what's left of the old pile, clear of the opening
    local inside_old = function(x, y)
        return dfhack.buildings.containsTile(pile, x, y) and clear(x, y)
    end
    local r = best_rect(pile.x1, pile.y1, pile.x2, pile.y2, inside_old, 20)
    if r and r.w * r.h >= MOVE_MIN_TILES then
        r.z, r.kept = z, true
        return r
    end
    -- 2. free floor inside the fort nearby, about as big as the old pile
    local want = math.max(MOVE_MIN_TILES, math.min(100, (pile.x2 - pile.x1 + 1) * (pile.y2 - pile.y1 + 1)))
    local side = math.max(2, math.min(10, math.ceil(math.sqrt(want))))
    local W, H = map_size()
    local function free(x, y)
        if x < 1 or y < 1 or x > W - 2 or y > H - 2 or not clear(x, y) then return false end
        local t = T(x, y, z)
        return t ~= nil and interior(t) and DOOR_GROUND[t.shape] and not t.liquid and not t.occupied
    end
    r = best_rect(pile.x1 - MOVE_RADIUS, pile.y1 - MOVE_RADIUS, pile.x2 + MOVE_RADIUS, pile.y2 + MOVE_RADIUS,
                  free, side)
    if r and r.w * r.h >= MOVE_MIN_TILES then
        r.z = z
        return r
    end
    return nil, 'no free floor inside the fort near it'
end

move_hook = nil        -- tests replace this
-- Move one stockpile out of an opening. Returns ok, text.
function move_stockpile(pile, avoid)
    if move_hook then return move_hook(pile, avoid) end
    local spot, why = new_pile_spot(pile, avoid)
    if not spot then return false, why end
    local qf = reqscript('quickfort')
    local function put(r, command, dry)
        local cell = ('c(%dx%d)'):format(r.w, r.h)
        local ok, stats = pcall(qf.apply_blueprint, {mode = 'place', data = {[r.z] = {[r.y] = {[r.x] = cell}}},
                                                     pos = {x = 0, y = 0, z = 0}, command = command or 'run',
                                                     dry_run = dry})
        return ok and stats and stats.place_designated and stats.place_designated.value > 0
    end
    local old_name, old_id = pile.name, pile.id
    local file = ('ai-move-%d'):format(old_id)
    -- (0.100) the command's own result too: pcall only catches a Lua error, and a
    -- failed export meant the pile was moved without its settings
    local okx, _, rvx = pcall(dfhack.run_command_silent, 'stockpiles', 'export', file, '-s', tostring(old_id))
    if not okx or rvx ~= CR_OK then return false, 'could not copy its settings' end
    local old_box = {x = pile.x1, y = pile.y1, z = pile.z, w = pile.x2 - pile.x1 + 1, h = pile.y2 - pile.y1 + 1}
    if not spot.kept and not put(spot, 'run', true) then return false, 'the game would not take a stockpile there' end
    dfhack.buildings.deconstruct(pile)        -- a stockpile goes at once; its items stay where they lie
    if not put(spot) then
        put(old_box)                         -- put it back where it was, rather than lose it
        return false, 'the game refused the new stockpile, so the old one was put back'
    end
    local new = dfhack.buildings.findAtTile(xyz2pos(spot.x, spot.y, spot.z))
    if new and new:getType() == df.building_type.Stockpile then
        pcall(dfhack.run_command_silent, 'stockpiles', 'import', file, '-s', tostring(new.id))
        if old_name and #old_name > 0 then new.name = old_name end
    end
    cache = {}                               -- the opening's tiles are free now
    return true, ('%s %dx%d at x%d y%d'):format(spot.kept and 'kept' or 'moved to', spot.w, spot.h, spot.x, spot.y)
end

function fortify(id, style, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if not GAP[style] then return {ok = false, rejected = true, error = 'unknown gate style ' .. tostring(style)} end
    cache, edge_cache = {}, {}      -- the map may have changed since the scan
    -- stockpiles in the opening are moved out of the way first
    local moved = {}
    local avoid = {}
    for _, k in ipairs(e.inside_list) do avoid[k] = true end
    for k in pairs(e.outs) do avoid[k] = true end
    local ok_list, piles = pcall(stockpiles_in, e.inside_list)
    for _, pile in ipairs(ok_list and piles or {}) do
        local ok, text = move_stockpile(pile, avoid)
        if not ok then
            return {ok = false, error = 'a stockpile is in the opening and could not be moved: ' .. tostring(text)}
        end
        table.insert(moved, text)
    end
    local okd, doors_present = pcall(doors_in, e.inside_list)
    local plan, why = plan_gate(e, style, starts or citizen_starts(), okd and doors_present or {})
    if not plan then return {ok = false, error = why} end
    local out, failed = {walls = 0, doors = 0, inner_doors = 0, traps = 0, statues = 0, doors_later = 0,
                         support_walls = 0, hatches = 0}, {}
    out.pieces = {}                 -- every tile it placed on ("x,y,z"), so the gate can be taken down exactly
    local function put(list, key_text, field)
        for _, k in ipairs(list) do
            local x, y, z = unkey(k)
            if key_text == 'd' and not wall_beside(x, y, z) then
                -- its walls are only planned: the door is added once they're
                -- built (the next scans see a narrow gap between walls)
                out.doors_later = out.doors_later + 1
            else
                local ok, reason = place(key_text, {x = x, y = y, z = z})
                if ok then
                    out[field] = out[field] + 1
                    if #out.pieces < 80 then table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z)) end
                else
                    table.insert(failed, key_text .. ':' .. tostring(reason))
                end
            end
        end
    end
    put(plan.walls, 'Cw', 'walls')
    put(plan.support, 'Cw', 'support_walls')
    put(plan.hatches, 'H', 'hatches')
    put(plan.doors, 'd', 'doors')
    if plan.bridge then
        -- the lever first: where the dwarves are, away from this gate. No such
        -- spot, or the game refuses the bridge: doors in the gap instead, so
        -- the opening is never left with nothing to close it
        local br = plan.bridge
        local spot = lever_spot(starts or citizen_starts(), e)
        local placed_bridge = false
        if spot then
            local text = ('%s(%dx%d)'):format(br.dir, br.w, br.h)
            local ok, reason = place(text, {x = br.x, y = br.y, z = br.z})
            if ok then
                placed_bridge = true
                out.bridge = {x = br.x, y = br.y, z = br.z, w = br.w, h = br.h}
                local okl, why = place('Tl', spot)
                if okl then
                    name_at(spot, LEVER_NAME)
                    out.lever = spot
                else
                    -- the player's own "AI gate" lever, if free, is linked instead
                    table.insert(failed, 'Tl:' .. tostring(why))
                end
            else
                table.insert(failed, text .. ':' .. tostring(reason))
            end
        else
            out.bridge_note = 'no free floor for its lever where the dwarves are, away from the gate: doors instead'
        end
        if not placed_bridge then
            put(br.keys, 'd', 'doors')
            out.style = 'plain'
        end
    end
    put(plan.inner, 'd', 'inner_doors')
    put(plan.traps, 'Tc', 'traps')
    put(plan.statues, 's', 'statues')
    out.kept_doors = plan.kept_doors
    if plan.water then out.water = plan.water end
    if plan.water_gate then
        out.ok, out.water_gate, out.style = true, true, style
        return out
    end
    if plan.shore then
        local x, y, z = unkey(plan.walls[1] or plan.doors[1] or e.inside_list[1])
        out.shore, out.line = true, {x = x, y = y, z = z}
    end
    if plan.moved_in then
        local x, y, z = unkey((plan.walls[1] or plan.doors[1] or plan.support[1]) or e.inside_list[1])
        out.moved_in, out.moved_why = plan.moved_in, plan.moved_why
        out.line = {x = x, y = y, z = z}
    end
    out.ok = out.walls + out.doors + out.support_walls + out.hatches + (out.bridge and 1 or 0) > 0
    out.style = out.style or style
    if #failed > 0 then out.failed = table.concat(failed, '; '):sub(1, 300) end
    if #moved > 0 then out.stockpiles_moved = table.concat(moved, '; ') end
    if out.ok and out.support_walls > 0 and out.doors_later > 0 then
        out.note = 'a wall goes beside the door first; the door follows once it is built'
    end
    if not out.ok and out.doors_later > 0 and not out.failed then
        local x, y = unkey(plan.doors[1] or e.inside_list[1])
        out.error = ('a door needs a wall beside it, and there is none at x%d y%d (nothing to hang a door on '
            .. 'there, and walling it shut would cut the way through)'):format(x, y)
    elseif not out.ok then
        out.error = 'nothing could be placed (' .. (out.failed or '?') .. ')'
    end
    return out
end

---------------------------------------------------------------------------
-- Linking a lever to a bridge, door or hatch. Quickfort can't link, so the AI
-- makes DF's own LinkBuildingToTrigger job on the lever, with two free
-- mechanisms: one goes into the target (LinkToTarget), one into the lever
-- (LinkToTrigger). A dwarf with the mechanic labour does it. The defence
-- probe found every part of this in DF 53.16; dry_run checks without acting.
---------------------------------------------------------------------------

LINK_TARGETS = {Bridge = true, Door = true, Hatch = true, Floodgate = true, GrateFloor = true, BarsFloor = true}

-- Mechanisms no one is using: {item, ...} (tests replace this).
-- (0.94.1) Why a mechanism can't be used for a link (nil when it can).
-- The cistern counted its mechanisms more loosely than the link takes them
-- (region2: "2 free" in the report, "0 free" at the link, 146 refusals), so
-- both now use this one test, and the report says what holds the others.
local function item_pos(it)
    local ok, x, y, z = pcall(dfhack.items.getPosition, it)
    if not ok or x == nil then return nil end
    if type(x) == 'table' or type(x) == 'userdata' then
        local okp, p = pcall(function() return {x = x.x, y = x.y, z = x.z} end)
        return okp and p or nil
    end
    return {x = x, y = y, z = z}
end

local function group_at(p)
    if not p or not (dfhack.maps and dfhack.maps.getWalkableGroup) then return nil end
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(p.x, p.y, p.z))
    return ok and g or nil
end

-- The walkable group a dwarf reaches the item from: its own tile, or for
-- one held in a workshop (whose own tiles may be impassable) a walkable tile
-- beside it. nil when unread (no map API: the tests), 0 when none.
local function reach_group(it, in_shop)
    local p = item_pos(it)
    if not p then return nil end
    local g = group_at(p)
    if g == nil or g ~= 0 or not in_shop then return g, p end
    for dy = -1, 1 do
        for dx = -1, 1 do
            local g2 = group_at({x = p.x + dx, y = p.y + dy, z = p.z})
            if g2 and g2 ~= 0 then return g2, p end
        end
    end
    return 0, p
end

UNWALKABLE_AT = {}       -- (0.104.156) where the last unwalkable mechanisms lay (3 at most)

function mechanism_unusable(it)
    local _, why = U.item_unfree(it)       -- (lua/ai-util.lua's list)
    if why then return why end
    local okb, b = pcall(dfhack.items.getHolderBuilding, it)
    if okb and b then
        local okt, t = pcall(function() return df.building_type[b:getType()] end)
        -- (0.95.1) one made and left in its workshop (no stockpile takes it
        -- yet) is a stored product, not a part of the building: a job takes
        -- it from there. region2's 5 mechanisms all sat in the Mechanic's
        -- workshop, and the cistern ordered more that sat there too.
        if okt and (t == 'Workshop' or t == 'Furnace') then return nil end
        return 'held in a ' .. tostring(okt and t or 'building')
    end
    -- (0.104.156) Teacheroar, 1 Nov: 2 of the 3 "free" mechanisms lay at x92
    -- y106 z168, a tile no dwarf can walk to; every link took them first and
    -- DF cancelled it ("Item inaccessible"), and no rule ordered more
    local g, p = reach_group(it, false)
    if g == 0 then
        if p and #UNWALKABLE_AT < 3 then table.insert(UNWALKABLE_AT, ('x%d y%d z%d'):format(p.x, p.y, p.z)) end
        return 'where no dwarf can walk'
    end
    return nil
end

-- (0.104.156) `near` (a position): only mechanisms a dwarf can walk to from
-- there (the same walkable group), nearest first. Teacheroar, 1 Nov: the
-- cavern well's link job took the first two in the item list and DF
-- cancelled it each time ("Link a building to trigger: Item inaccessible"),
-- 25 times in 2 hours; the cistern's lever lost its link 3 times the same
-- way on 31 Oct. Returns the list and how many usable ones were out of reach.
function free_mechanisms(n, near)
    local out, cands, unreachable, far_at = {}, {}, 0, {}
    local want = near and group_at(near) or nil
    if want == 0 then want = nil end            -- the lever's own tile unread: no filter
    for _, it in ipairs(df.global.world.items.other.TRAPPARTS) do
        if not mechanism_unusable(it) then
            if want then
                local okb, hb = pcall(dfhack.items.getHolderBuilding, it)
                local g, p = reach_group(it, okb and hb ~= nil)
                if p and g == want then
                    local d = math.abs(p.x - near.x) + math.abs(p.y - near.y) + 3 * math.abs(p.z - near.z)
                    table.insert(cands, {it = it, d = d})
                else
                    unreachable = unreachable + 1
                    if p and #far_at < 3 then
                        table.insert(far_at, ('x%d y%d z%d (group %s)'):format(p.x, p.y, p.z, tostring(g)))
                    end
                end
            else
                table.insert(out, it)
                if #out >= n then break end
            end
        end
    end
    if want then
        table.sort(cands, function(a, b) return a.d < b.d end)
        for i = 1, math.min(n, #cands) do table.insert(out, cands[i].it) end
    end
    return out, unreachable, far_at
end

-- (0.94.1) The mechanisms there are: usable, taken by a job, and the rest by
-- why they can't be used (for the cistern's and the gates' reports).
function mechanism_counts()
    local out = {usable = 0, reserved = 0, why = {}}
    UNWALKABLE_AT = {}
    for _, it in ipairs(df.global.world.items.other.TRAPPARTS) do
        local why = mechanism_unusable(it)
        if not why then out.usable = out.usable + 1
        elseif why == 'taken by a job' then out.reserved = out.reserved + 1
        elseif why ~= 'gone' and why ~= 'in a building' then out.why[why] = (out.why[why] or 0) + 1 end
    end
    if #UNWALKABLE_AT > 0 then out.unwalkable_at = table.concat(UNWALKABLE_AT, '; ') end
    return out
end

-- The roles a job's items play. DF 53.16's structures call the enum
-- job_role_type (older ones: job_item_ref.T_role); found by name, never
-- assumed (an unknown name used to stop the link with a Lua error).
function link_roles()
    for _, get in ipairs({function() return df.job_role_type end,
                          function() return df.job_item_ref.T_role end}) do
        local ok, r = pcall(get)
        if ok and r ~= nil then
            local ok2, has = pcall(function() return r.LinkToTarget ~= nil and r.LinkToTrigger ~= nil end)
            if ok2 and has then return r end
        end
    end
    return nil
end

function link_lever(lever_id, target_id, dry_run)
    local lever = df.building.find(lever_id)
    if not lever or lever:getType() ~= df.building_type.Trap or lever.trap_type ~= df.trap_type.Lever then
        return {ok = false, rejected = true, error = 'no lever with id ' .. tostring(lever_id)}
    end
    local target = df.building.find(target_id)
    local tname = target and df.building_type[target:getType()]
    if not target or not LINK_TARGETS[tname] then
        return {ok = false, rejected = true, error = 'building ' .. tostring(target_id) .. ' is not a bridge, door or hatch'}
    end
    for _, b in ipairs({lever, target}) do
        if b:getBuildStage() < b:getMaxBuildStage() then
            return {ok = false, rejected = true, error = 'building ' .. b.id .. ' is not built yet'}
        end
    end
    local levers = lever_links()
    for _, lid in ipairs(levers[target_id] or {}) do
        if lid == lever_id then return {ok = false, rejected = true, error = 'that lever is already linked to it'} end
    end
    for _, j in ipairs(lever.jobs) do
        if j.job_type == df.job_type.LinkBuildingToTrigger then
            return {ok = false, rejected = true, error = 'a link job is already waiting at that lever'}
        end
    end
    local roles = link_roles()
    if not (roles and df.job_type.LinkBuildingToTrigger and roles.LinkToTarget and roles.LinkToTrigger
            and dfhack.job.addGeneralRef and dfhack.job.attachJobItem and dfhack.job.linkIntoWorld) then
        return {ok = false, rejected = true, error = 'this DF version has no lever-link job'}
    end
    local mechs, unreachable = free_mechanisms(2, {x = lever.centerx, y = lever.centery, z = lever.z})
    if #mechs < 2 then
        local held = {}
        local okc, c = pcall(mechanism_counts)
        if okc then for why, n in pairs(c.why) do table.insert(held, n .. ' ' .. why) end end
        if (unreachable or 0) > 0 then table.insert(held, unreachable .. ' out of reach of the lever') end
        table.sort(held)
        return {ok = false, error = ('a link needs 2 free mechanisms (%d free%s)'):format(#mechs,
                    #held > 0 and ('; ' .. table.concat(held, ', ')) or ''), mechanisms = #mechs}
    end
    if dry_run then return {ok = true, dry_run = true, target = tname, mechanisms = #mechs} end
    local job = df.job:new()
    job.job_type = df.job_type.LinkBuildingToTrigger
    job.pos = xyz2pos(lever.centerx, lever.centery, lever.z)
    dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, lever.id)
    dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_TRIGGERTARGET, target.id)
    if not (dfhack.job.attachJobItem(job, mechs[1], roles.LinkToTarget, -1, -1)
            and dfhack.job.attachJobItem(job, mechs[2], roles.LinkToTrigger, -1, -1)) then
        dfhack.job.linkIntoWorld(job, true)
        dfhack.job.removeJob(job)
        return {ok = false, error = 'the game would not attach the items to the link job'}
    end
    dfhack.job.linkIntoWorld(job, true)
    lever.jobs:insert('#', job)
    -- (0.105.23) once the mechanic links it, a door or hatch is shut by the
    -- link: the watch opens it again and gives it its lever at once
    if tname == 'Hatch' or tname == 'Door' then pcall(link_watch_start) end
    local ids = {}
    for _, m in ipairs(mechs) do table.insert(ids, m.id) end
    return {ok = true, job_id = job.id, target = tname, mechanism_ids = ids}
end

---------------------------------------------------------------------------
-- A lever the AI places itself for a drawbridge: on free floor where the
-- dwarves are (the middle of the citizens, on their busiest level), beside a
-- wall where it's out of the way. Named "AI gate lever" so the AI knows it.
---------------------------------------------------------------------------

LEVER_NAME = 'AI gate lever'

function lever_spot(starts, e)
    if not starts or #starts == 0 then return nil end
    -- away from the gate it works (as the watcher wants: 20+ tiles or 4+ levels)
    local function away(x, y, z)
        if not e then return true end
        return math.abs(z - e.z) > 3 or math.max(math.abs(x - e.x), math.abs(y - e.y)) >= LEVER_AWAY
    end
    -- the busiest level, then the middle of the citizens on it
    local per_z = {}
    for _, p in ipairs(starts) do per_z[p.z] = (per_z[p.z] or 0) + 1 end
    local bz, bn = nil, -1
    for z, n in pairs(per_z) do if n > bn or (n == bn and z < bz) then bz, bn = z, n end end
    local xs, ys = {}, {}
    for _, p in ipairs(starts) do if p.z == bz then table.insert(xs, p.x); table.insert(ys, p.y) end end
    table.sort(xs); table.sort(ys)
    local cx, cy = xs[(#xs + 1) // 2], ys[(#ys + 1) // 2]
    local best, best_d
    for r = 0, 24 do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = cx + dx, cy + dy
                    local t = T(x, y, bz)
                    if t and interior(t) and DOOR_GROUND[t.shape] and not t.liquid and not t.occupied
                            and wall_beside(x, y, bz) and away(x, y, bz) then
                        local d = dx * dx + dy * dy
                        if not best_d or d < best_d then best, best_d = {x = x, y = y, z = bz}, d end
                    end
                end
            end
        end
        if best then return best end
    end
    return nil
end

-- Take down a gate the AI built at an entrance that turned out not to be one
-- (0.39 walled the shade of trees): the pieces it recorded, or, for gates
-- from before pieces were recorded, the walls, doors, hatches, traps and
-- statues within GATE_CLEAR_RADIUS of the spot on the surface only (never a
-- tile under rock: those are the fort's own). Planned pieces are cancelled,
-- built ones are marked for removal by the dwarves.
GATE_CLEAR_RADIUS = 4
GATE_PIECES_MAX, GATE_PIECE_REACH = 80, 15
local function surface_tile(x, y, z)
    local d = dfhack.maps.getTileFlags(x, y, z)
    return d ~= nil and not d.subterranean
end

-- (0.105.30) A wall the AI built in a cavern opening (a sealed gate): a
-- construction with a cavern tile beside it. Only such walls are taken
-- down under rock.
local function sealed_wall_tile(x, y, z)
    local ok, yes = pcall(function()
        local pos = xyz2pos(x, y, z)
        local built = dfhack.constructions.findAtTile(pos)
        if not built then
            local b = dfhack.buildings.findAtTile(pos)
            built = b and df.building_type[b:getType()] == 'Construction'
        end
        if not built then return false end
        for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
            local des = dfhack.maps.getTileFlags(x + d[1], y + d[2], z)
            if des and (des.feature_global or des.feature_local) then return true end
        end
        return false
    end)
    return ok and yes or false
end

function clear_gate(x, y, z, pieces, dry_run)
    if not surface_tile(x, y, z) and not sealed_wall_tile(x, y, z) then
        return {ok = false, rejected = true, error = 'that gate is under rock: part of the fort, kept'}
    end
    if not GATES.scanned then return {ok = false, rejected = true, error = 'map the entrances first'} end
    -- The fort's live entrances: their tiles inside, the tiles out from
    -- them, and the gates that close them. A hatch over a stair is a level
    -- above the stair (0.42's cleanup took the main stair's hatch with a
    -- tree gate 4 tiles off, checking the same level only).
    local live, keep_ids = {}, {}
    for _, e in ipairs(GATES.entrances or {}) do
        for _, k in ipairs(e.inside_list or {}) do table.insert(live, {unkey(k)}) end
        for k in pairs(e.outs or {}) do table.insert(live, {unkey(k)}) end
        for _, b in ipairs(e.equipment or {}) do keep_ids[b.id] = true end
    end
    local function near_live(px, py, pz, r)
        for _, t in ipairs(live) do
            if math.abs(t[3] - pz) <= 1 and math.abs(t[1] - px) <= r and math.abs(t[2] - py) <= r then
                return true
            end
        end
        return false
    end
    if near_live(x, y, z, 3) then
        return {ok = false, rejected = true, error = 'it is still an entrance of the fort: kept'}
    end
    local spots = {}
    if type(pieces) == 'table' and #pieces > 0 then
        -- (0.100, security pass) the pieces a fortify recorded lie round its
        -- gate on the surface: anything else (under rock, far off, a list of
        -- thousands) isn't one, and is skipped
        for i, k in ipairs(pieces) do
            if i > GATE_PIECES_MAX then break end
            local px, py, pz = tostring(k):match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
            px, py, pz = tonumber(px), tonumber(py), tonumber(pz)
            if px and math.abs(px - x) <= GATE_PIECE_REACH and math.abs(py - y) <= GATE_PIECE_REACH
                    and math.abs(pz - z) <= 1 then
                if surface_tile(px, py, pz) then
                    table.insert(spots, {x = px, y = py, z = pz})
                elseif sealed_wall_tile(px, py, pz) then
                    table.insert(spots, {x = px, y = py, z = pz, cavern = true})   -- (0.105.30) walls only
                end
            end
        end
    else
        -- (0.100, review) no record of what was placed (a gate from before
        -- 0.4x): the area round it holds the player's doors and the keep's
        -- walls too, so nothing is guessed at; it's left
        return {ok = false, rejected = true,
                error = 'no record of that gate\'s pieces: left standing (take it down by hand if it\'s in the way)'}
    end
    local removed, cancelled = 0, 0
    local KINDS = {Door = true, Hatch = true, Trap = true, Statue = true, Bridge = true}
    for _, p in ipairs(spots) do
        local pos = xyz2pos(p.x, p.y, p.z)
        local b = dfhack.buildings.findAtTile(pos)
        local kind = b and df.building_type[b:getType()]
        if near_live(p.x, p.y, p.z, 1) or (b and keep_ids[b.id]) then
            -- beside a live entrance, or one of its gates: never a leftover
        elseif p.cavern and b and kind ~= 'Construction' then
            -- (0.105.30) under rock only the sealed gate's walls
        elseif b and kind == 'Trap' and b.trap_type == df.trap_type.Lever then
            -- a lever is never a gate piece (it may work the fort's real gate)
        elseif b and (KINDS[kind] or kind == 'Construction') then
            if not dry_run then
                if kind == 'Construction' then
                    local ok, only_planned = dfhack.constructions.designateRemove(pos)
                    if ok then if only_planned then cancelled = cancelled + 1 else removed = removed + 1 end end
                else
                    local built = b:getBuildStage() >= b:getMaxBuildStage()
                    dfhack.buildings.deconstruct(b)
                    if built then removed = removed + 1 else cancelled = cancelled + 1 end
                end
            else
                removed = removed + 1
            end
        elseif dfhack.constructions.findAtTile(pos) then
            local t = dfhack.maps.getTileType(pos)
            local shape = t and df.tiletype_shape[df.tiletype.attrs[t].shape]
            if shape == 'WALL' then                     -- a built wall (not a floor someone made)
                if not dry_run then dfhack.constructions.designateRemove(pos) end
                removed = removed + 1
            end
        end
    end
    if removed + cancelled == 0 then
        return {ok = false, rejected = true, error = 'nothing of that gate is left to take down'}
    end
    return {ok = true, removed = removed, cancelled = cancelled, dry_run = dry_run or nil}
end

-- Name the building just placed at pos (quickfort can't name a lever).
name_hook = nil       -- tests replace this
function name_at(pos, name)
    if name_hook then return name_hook(pos, name) end
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(pos.x, pos.y, pos.z))
        if b then b.name = name end
    end)
end

-- (0.105.12, 14.1 step 4) A lever of the AI's own for a gate that has none
-- (the founding stair's hatch: a lever-worked hatch is the machinery of a
-- fort that cares for its engineering and its walls). Placed where the
-- dwarves are, away from the gate, named "AI gate lever"; the gate rule
-- links it once built. Refused (waiting) while an unlinked AI lever stands
-- or is being built anywhere.
function place_gate_lever(id, dry_run, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if #(e.equipment or {}) == 0 then
        return {ok = false, rejected = true, error = 'that entrance has no gate yet: a lever works a gate'}
    end
    local waiting = false
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and tostring(b.name or ''):lower():find('^ai gate')
                    and #b.linked_mechanisms == 0 then
                waiting = true
            end
        end
    end)
    if waiting then
        return {ok = false, waiting = true, error = 'an AI gate lever stands unlinked or is being built: it goes first'}
    end
    cache, edge_cache = {}, {}
    -- (0.105.23) where the fort's citizens are (fort_starts: not one on a ledge or a treetop)
    local spot = lever_spot(starts or fort_starts(citizen_starts()), e)
    if not spot then return {ok = false, error = 'no free floor for a lever where the dwarves are, away from the gate'} end
    if dry_run then return {ok = true, dry_run = true, at = spot} end
    local ok, why = place('Tl', spot)
    if not ok then return {ok = false, error = 'the lever could not be placed: ' .. tostring(why)} end
    name_at(spot, LEVER_NAME)
    return {ok = true, at = spot}
end

-- Levers the AI may link: named "AI gate..." (the player's "AI gate", or the
-- AI's own "AI gate lever"), built, with no link and no job. {{id,x,y,z}}.
function free_levers()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and tostring(b.name or ''):lower():find('^ai gate')
                    and #b.linked_mechanisms == 0 and #b.jobs == 0
                    and b:getBuildStage() >= b:getMaxBuildStage() then
                table.insert(out, {id = b.id, x = b.centerx, y = b.centery, z = b.z})
            end
        end
    end)
    return out
end

-- Mechanisms free to use (for traps and links), counted up to `cap`.
function free_mechanism_count(cap)
    local ok, list = pcall(free_mechanisms, cap or 200)
    return ok and #list or 0
end

---------------------------------------------------------------------------
-- Traps behind a gate: on the way in, just inside the gate line (never
-- outside it, never on the tile right behind a door, where an inner door
-- may go), nearest first, in the fort's trap style.
---------------------------------------------------------------------------

TRAP_KEYS = {cage = 'Tc', stonefall = 'Ts', weapon = 'Tw'}
MAX_TRAPS = 8

function trap_tiles(e, n, starts)
    -- the gate's own tiles: what closes it (doors, bridges, hatches). (0.105.9)
    -- hatches too: every fort's only gate was the founding stair's hatch, so
    -- no fort ever had a trap (the six forts, y257). Behind a hatch the way
    -- in goes down its stair; the traps go on the floor at the stair's foot
    -- (stairs are never trapped: only floor is)
    local gate, only_hatch = {}, true
    for _, b in ipairs(e.equipment or {}) do
        if b.x1 and b.x2 and b.y1 and b.y2 and b.z then
            for x = b.x1, b.x2 do for y = b.y1, b.y2 do gate[key(x, y, b.z)] = true end end
            if b.kind ~= 'hatch' then only_hatch = false end
        end
    end
    if not next(gate) then return {} end
    -- inside the gate: what the dwarves reach without crossing it, less what
    -- the outside reaches without crossing it (a pocket between a moved-in
    -- gate and the opening, where a dwarf may stand)
    local inside = explore(starts, gate)
    local pocket, q, h = {}, {}, 1
    -- (a hatch sits on the opening itself: its stair down is the fort, no pocket)
    for _, k in ipairs(only_hatch and {} or e.inside_list or {}) do
        if not gate[k] and not pocket[k] then pocket[k] = true; table.insert(q, k) end
    end
    while h <= #q and #q < 5000 do
        local k = q[h]
        h = h + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if pocket[nk] or gate[nk] then return end
                if not (e.outs and e.outs[nk]) and inside_or_courtyard(T(nx, ny, nz), nk) then
                    pocket[nk] = true                -- (inside tiles only: never round by another way in)
                    table.insert(q, nk)
                end
            end)
        end
    end
    for k in pairs(pocket) do inside[k] = nil end
    local dist, queue, head = {}, {}, 1
    for k in pairs(gate) do dist[k] = 0; table.insert(queue, k) end
    local picks = {}
    while head <= #queue and #picks < n do
        local k = queue[head]
        head = head + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if dist[nk] or not inside[nk] then return end
                dist[nk] = dist[k] + 1
                if dist[nk] <= 8 then table.insert(queue, nk) end
            end)
        end
        local d = dist[k]
        if d >= 2 and #picks < n then
            local tt = T(x, y, z)
            if tt and DOOR_GROUND[tt.shape] and not tt.liquid and not tt.occupied then
                table.insert(picks, k)
            end
        end
    end
    return picks
end

function place_traps(id, kind, n, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    local k = TRAP_KEYS[kind]
    if not k then return {ok = false, rejected = true, error = 'unknown trap kind ' .. tostring(kind)} end
    n = math.max(1, math.min(MAX_TRAPS, math.floor(tonumber(n) or 0)))
    if #(e.equipment or {}) == 0 then
        return {ok = false, rejected = true, error = 'that entrance has no gate yet: traps go behind a gate'}
    end
    cache, edge_cache = {}, {}
    local tiles = trap_tiles(e, n, starts or citizen_starts())
    if #tiles == 0 then return {ok = false, error = 'no free floor just inside that gate for traps'} end
    local placed, failed = 0, {}
    local first
    for _, tk in ipairs(tiles) do
        local x, y, z = unkey(tk)
        local ok, why = place(k, {x = x, y = y, z = z})
        if ok then
            placed = placed + 1
            first = first or {x = x, y = y, z = z}
        else
            table.insert(failed, tostring(why))
        end
    end
    if placed == 0 then return {ok = false, error = 'no trap could be placed (' .. table.concat(failed, '; '):sub(1, 200) .. ')'} end
    return {ok = true, traps = placed, kind = kind, at = first,
            failed = #failed > 0 and table.concat(failed, '; '):sub(1, 200) or nil}
end

-- (0.105.23, 14.1 step 4a) Build the gatehouse in front of an entrance's lid
-- hatch (plan_gatehouse): the drawbridge first (refused, nothing else is
-- placed), named "AI gatehouse bridge" so the scan knows it; then the walls,
-- the corridor's traps in the fort's style, and a lever where the dwarves
-- are (unless an AI lever stands unlinked: that one is linked instead). The
-- gate rule links the lever to the bridge once both are built.
function build_gatehouse(id, kind, n, dry_run, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    local tk = TRAP_KEYS[kind or 'cage']
    if not tk then return {ok = false, rejected = true, error = 'unknown trap kind ' .. tostring(kind)} end
    if not e.sealed then return {ok = false, rejected = true, error = 'that entrance has no gate yet: the hatch first'} end
    if e.gatehouse == 'standing' then return {ok = false, rejected = true, error = 'a gatehouse stands there already'} end
    local h = lid_hatch(e)
    if not h then
        return {ok = false, rejected = true, error = 'a gatehouse goes in front of a hatch over the founding stair'}
    end
    cache, edge_cache = {}, {}            -- the map may have changed since the scan
    local plan, why = plan_gatehouse(e, h)
    if not plan then return {ok = false, error = why} end
    n = math.max(0, math.min(#plan.corridor, math.floor(tonumber(n) or #plan.corridor)))
    local br = plan.bridge
    local out = {ok = true, bridge = {x = br.x, y = br.y, z = br.z}, dir = br.dir, length = plan.len,
                 walls = 0, natural_walls = plan.natural, traps = 0, kind = kind or 'cage', pieces = {}}
    if dry_run then
        out.dry_run, out.walls, out.traps = true, #plan.walls, n
        return out
    end
    local okb, whyb = place(('%s(1x1)'):format(br.dir), {x = br.x, y = br.y, z = br.z})
    if not okb then return {ok = false, error = 'the game would not place the drawbridge: ' .. tostring(whyb)} end
    name_at({x = br.x, y = br.y, z = br.z}, GATEHOUSE_NAME)
    table.insert(out.pieces, ('%d,%d,%d'):format(br.x, br.y, br.z))
    local failed = {}
    for _, k in ipairs(plan.walls) do
        local x, y, z = unkey(k)
        local ok, w = place('Cw', {x = x, y = y, z = z})
        if ok then
            out.walls = out.walls + 1
            table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, 'Cw:' .. tostring(w))
        end
    end
    for i = 1, n do
        local x, y, z = unkey(plan.corridor[i])
        local ok, w = place(tk, {x = x, y = y, z = z})
        if ok then
            out.traps = out.traps + 1
            table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, tk .. ':' .. tostring(w))
        end
    end
    local waiting = false
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and ai_lever_name(b.name) and #b.linked_mechanisms == 0 then
                waiting = true
            end
        end
    end)
    if waiting then
        out.lever_note = 'an AI gate lever stands unlinked: it works the bridge'
    else
        local spot = lever_spot(starts or fort_starts(citizen_starts()), e)
        if spot and place('Tl', spot) then
            name_at(spot, LEVER_NAME)
            out.lever = spot
        else
            out.lever_note = 'no lever placed (no free floor where the dwarves are, away from the gate): the gate rule places one'
        end
    end
    if #failed > 0 then out.failed = table.concat(failed, '; '):sub(1, 300) end
    return out
end

---------------------------------------------------------------------------
-- (0.105.30, construction spec 3.2) The War-hold's wing walls: once a
-- gatehouse stands, two straight arms of wall run from its front corners
-- (beside the drawbridge), across the corridor's line, WING_LEN tiles each,
-- a barbican's funnel on the surface. Seen from above, the corridor going
-- north (B the bridge, W the gatehouse walls, A the arms):
--     A A A A A W B W A A A A A
--               W T W
--               W H W
-- Each arm tile: ground a wall stands on (not open space, not a ramp top),
-- the open surface (open_ground: nothing built, no water, not a courtyard),
-- in no zone, with no farm plot, pasture or depot within WING_KEEP_OFF and
-- no water within WING_WATER. An arm stops at its first bad tile and is
-- dropped when shorter than WING_MIN. The arms must close no courtyard:
-- with them and the gatehouse's walls standing, every open tile beside an
-- arm, and the tile in front of the bridge, still reaches the map's edge;
-- an arm that would close one is dropped. The pieces go on the gate's record.
---------------------------------------------------------------------------
WING_LEN, WING_MIN = 5, 3
WING_KEEP_OFF, WING_WATER = 3, 2

-- Zones, farm plots and depots on level z: {{x1, y1, x2, y2, kind}} with kind
-- 'zone', 'pasture', 'farm' or 'depot' (tests replace this).
function wing_keepouts(z)
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b.z == z then
                local t = df.building_type[b:getType()]
                local kind
                if t == 'Civzone' then
                    kind = (df.civzone_type[b.type] == 'Pen') and 'pasture' or 'zone'
                elseif t == 'FarmPlot' then kind = 'farm'
                elseif t == 'TradeDepot' then kind = 'depot' end
                if kind then table.insert(out, {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, kind = kind}) end
            end
        end
    end)
    return out
end

-- An outside tile walks to the map's edge with `blocked` standing (no cache).
local function edge_without(k, blocked)
    local W, H = map_size()
    local seen, queue, head = {[k] = true}, {k}, 1
    while head <= #queue do
        local ck = queue[head]
        head = head + 1
        local x, y, z = unkey(ck)
        if x <= 0 or y <= 0 or x >= W - 1 or y >= H - 1 then return true end
        if #queue > COURTYARD_LIMIT then return true end
        moves(x, y, z, T(x, y, z), function(nx, ny, nz)
            local nk = key(nx, ny, nz)
            if seen[nk] or blocked[nk] then return end
            local nt = T(nx, ny, nz)
            if nt and nt.walk and nt.outside and not nt.hidden then
                seen[nk] = true
                table.insert(queue, nk)
            end
        end)
    end
    return false
end

-- The wings for an entrance whose gatehouse stands: {arms = {{keys}, ...},
-- walls = {keys}, dropped = {why...}, len, dir} or nil and why.
function plan_wings(e)
    if e.gatehouse ~= 'standing' then return nil, 'no gatehouse stands there' end
    local h = lid_hatch(e)
    local br = e.gatehouse_bridge
    if not h or type(br) ~= 'table' then return nil, 'the gatehouse\'s hatch or bridge could not be found' end
    local dx, dy = br.x - h.x, br.y - h.y
    if br.z ~= h.z or (dx ~= 0 and dy ~= 0) or (dx == 0 and dy == 0) then
        return nil, 'the gatehouse does not run straight from its hatch'
    end
    local d = {dx > 0 and 1 or (dx < 0 and -1 or 0), dy > 0 and 1 or (dy < 0 and -1 or 0)}
    local len = math.max(math.abs(dx), math.abs(dy)) - 1
    local z = h.z
    local px, py = math.abs(d[2]), math.abs(d[1])
    local function at(u, v) return h.x + d[1] * u + px * v, h.y + d[2] * u + py * v end
    -- the gatehouse's own walls, as they stand once built
    local house = {}
    local function wall(u, v) local x, y = at(u, v); house[key(x, y, z)] = true end
    wall(-1, 0)
    for u = -1, len + 1 do wall(u, -1); wall(u, 1) end
    local keepouts = wing_keepouts(z) or {}
    local function kept_off(x, y)
        for _, r in ipairs(keepouts) do
            local m = (r.kind == 'zone') and 0 or WING_KEEP_OFF
            if x >= r.x1 - m and x <= r.x2 + m and y >= r.y1 - m and y <= r.y2 + m then return r.kind end
        end
        return nil
    end
    local function wet(x, y)
        for ax = x - WING_WATER, x + WING_WATER do
            for ay = y - WING_WATER, y + WING_WATER do
                local t = T(ax, ay, z)
                if t and t.liquid then return true end
            end
        end
        return false
    end
    local arms, dropped, standing = {}, {}, 0
    for _, side in ipairs({-1, 1}) do
        local arm, stop = {}, nil
        for i = 1, WING_LEN do
            local x, y = at(len + 1, side * (1 + i))
            local t = T(x, y, z)
            if i == 1 and t and t.shape == 'WALL' and t.material == 'CONSTRUCTION' then standing = standing + 1 end
            local why
            if not t then why = 'off the map'
            elseif not WALL_GROUND[t.shape] or t.shape == 'EMPTY' or t.shape == 'RAMP_TOP' then
                why = tostring(t.shape):lower():gsub('_', ' ')
            elseif not open_ground(x, y, z) then why = 'not open ground'
            elseif wet(x, y) then why = 'water near'
            else
                local k = kept_off(x, y)
                if k then why = (k == 'zone') and 'a zone' or ('a ' .. k .. ' near') end
            end
            if why then stop = ('x%d y%d (%s)'):format(x, y, why) break end
            table.insert(arm, key(x, y, z))
        end
        if #arm >= WING_MIN then
            table.insert(arms, arm)
        else
            table.insert(dropped, ('the %s arm stops after %d tile%s at %s'):format(side < 0 and 'first' or 'second',
                #arm, #arm == 1 and '' or 's', tostring(stop)))
        end
    end
    if standing == 2 then return nil, 'the wings stand there already' end
    -- no courtyard: with the arms and the gatehouse standing, the tiles by
    -- each arm and in front of the bridge still reach the map's edge
    local fx, fy = at(len + 2, 0)
    local function closes(list)
        local blocked = {}
        for k in pairs(house) do blocked[k] = true end
        for _, arm in ipairs(list) do for _, k in ipairs(arm) do blocked[k] = true end end
        local check = {[key(fx, fy, z)] = true}
        for _, arm in ipairs(list) do
            for _, k in ipairs(arm) do
                local x, y = unkey(k)
                for ax = -1, 1 do
                    for ay = -1, 1 do
                        local nk = key(x + ax, y + ay, z)
                        local nt = T(x + ax, y + ay, z)
                        if not blocked[nk] and nt and nt.walk and nt.outside and not nt.hidden then check[nk] = true end
                    end
                end
            end
        end
        for k in pairs(check) do
            if not edge_without(k, blocked) then
                local x, y = unkey(k)
                return ('x%d y%d'):format(x, y)
            end
        end
        return nil
    end
    if #arms > 0 and closes(arms) then
        local kept = {}
        for _, arm in ipairs(arms) do
            local where = closes({arm})
            if where then
                table.insert(dropped, ('an arm would close a courtyard at %s'):format(where))
            else
                table.insert(kept, arm)
            end
        end
        if #kept == 2 and closes(kept) then kept = {kept[1]} end
        arms = kept
    end
    if #arms == 0 then
        return nil, 'no room for wing walls: ' .. (dropped[1] or 'no arm fits')
            .. (dropped[2] and ('; ' .. dropped[2]) or '')
    end
    local walls = {}
    for _, arm in ipairs(arms) do for _, k in ipairs(arm) do table.insert(walls, k) end end
    return {arms = arms, walls = walls, dropped = dropped, len = len, dir = d}
end

-- Build the wings (plan_wings): walls only, any material (buildingplan).
function build_wings(id, dry_run)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if e.gatehouse ~= 'standing' then return {ok = false, rejected = true, error = 'wings go on a gatehouse that stands'} end
    cache, edge_cache = {}, {}            -- the map may have changed since the scan
    local plan, why = plan_wings(e)
    if not plan then return {ok = false, rejected = true, error = why} end
    local arms = {}
    for _, arm in ipairs(plan.arms) do table.insert(arms, #arm) end
    local note = #plan.dropped > 0 and table.concat(plan.dropped, '; ') or nil
    if dry_run then
        return {ok = true, dry_run = true, walls = #plan.walls, arms = arms, blocks_needed = #plan.walls, note = note}
    end
    local out = {walls = 0, arms = arms, pieces = {}, blocks_needed = #plan.walls, note = note}
    local failed = {}
    for _, k in ipairs(plan.walls) do
        local x, y, z = unkey(k)
        local ok, w = place('Cw', {x = x, y = y, z = z})
        if ok then
            out.walls = out.walls + 1
            table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, 'Cw:' .. tostring(w))
        end
    end
    out.ok = out.walls > 0
    if #failed > 0 then out.failed = table.concat(failed, '; '):sub(1, 300) end
    if not out.ok then out.error = 'no wing wall could be placed (' .. (out.failed or '?') .. ')' end
    return out
end

-- (0.104.105) Gate parts in stock: free, and held by a job (on their way to
-- one). A planned hatch or door is built only from one the fort has.
GATE_PARTS = {hatch_covers = 'HATCH_COVER', doors = 'DOOR'}
function gate_parts()
    local out = {}
    for name, tname in pairs(GATE_PARTS) do
        local free, held = 0, 0
        pcall(function()
            for _, item in ipairs(df.global.world.items.other[tname]) do
                local f = item.flags
                -- (0.104.139) nor an artifact, an owned or carried one, or one
                -- to melt: buildingplan won't take them (Teacheroar: an heirloom
                -- hatch cover counted free, the hatch at x109 y38 waited 90 days)
                if not (f.forbid or f.in_building or f.construction or f.removed or f.garbage_collect
                        or f.trader or f.dump or f.hostile or f.artifact or f.owned or f.in_inventory
                        or f.melt or f.on_fire) then
                    if f.in_job then held = held + 1 else free = free + 1 end
                end
            end
        end)
        out[name], out[name .. '_held'] = free, held
    end
    return out
end

local DAY_TICKS = 1200
function closing_days(e)
    local since = e.closing and GATES.closing_since and GATES.closing_since[key(e.x, e.y, e.z)]
    if not since or not GATES.scanned_tick then return nil end
    return math.floor((GATES.scanned_tick - since) / DAY_TICKS)
end

function summary()
    local list = {}
    for _, e in ipairs(GATES.entrances or {}) do
        local eq = {}
        for _, b in ipairs(e.equipment) do
            local ids = {}
            for _, l in ipairs(b.levers or {}) do table.insert(ids, l.id) end
            local shut
            if b.lever_driven then                     -- (0.105.23) live: a link may have shut it
                local okb, bb = pcall(df.building.find, b.id)
                if okb and bb then shut = door_shut(bb) end
            end
            table.insert(eq, {id = b.id, kind = b.kind, lever_id = b.lever_id, levers = ids,
                              lever_away = b.lever_away == true,
                              lever_driven = b.lever_driven or nil, drive_lever = b.drive_lever,
                              shut = shut})
        end
        local outer = {}
        for _, b in ipairs(e.outer or {}) do
            table.insert(outer, {id = b.id, kind = b.kind, lever_id = b.lever_id})
        end
        table.insert(list, {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z, width = e.width,
                            sealed = e.sealed, closing = e.closing == true, equipment = eq,
                            bridges_unworked = e.bridges_unworked or {},
                            door_spots = #e.door_spots,
                            cut = e.cut,                    -- (0.105.0) closed by hatches on its stairs down
                            cut_hatches = e.cut_hatches, cut_why = e.cut_why,
                            waiting = e.waiting,
                            closing_days = closing_days(e),
                            closed = GATES.closed and GATES.closed[e.id] or false,
                            -- (0.105.23) the founding stair's lid, a gatehouse in front of it
                            lid = e.lid, gatehouse = e.gatehouse, gatehouse_why = e.gatehouse_why,
                            outer = #outer > 0 and outer or nil})
    end
    local okf, fl = pcall(free_levers)
    -- (0.105.3) enemies inside the fort (nil without a map: the brain acts as before)
    local oki, intr = pcall(intruders_inside)
    return {intruders_inside = oki and intr or nil,
            scanned = GATES.scanned == true, scanned_tick = GATES.scanned_tick, inside_tiles = GATES.inside_tiles,
            -- (0.100, review) the map of the inside hit its size limit: entrances
            -- past it weren't seen (not gone), and walls aren't planned on it
            capped = (GATES.inside_tiles or 0) >= MAX_TILES or nil,
            free_levers = okf and fl or {}, free_mechanisms = GATES.scanned and free_mechanism_count(200) or nil,
            entrances = list, armed = GATES.armed == true, watch_error = GATES.watch_error,
            -- (0.105.23) a lever linked since the scan: map the entrances again
            rescan = GATES.rescan or nil, lever_opened = GATES.lever_opened,
            parts = GATES.scanned and gate_parts() or nil,
            citizens_outside = GATES.scanned and citizens_outside() or nil,
            -- (0.105.4 review) visitors outside the fort (a tavern's inside don't count)
            visitors_outside = GATES.scanned and (function()
                local okv, n = pcall(visitors_outside); return okv and n or nil end)() or nil}
end

---------------------------------------------------------------------------
-- (0.105.0) Citizens on ledges, and the vertical cut.
--
-- Ledges: the map of the inside starts from where the citizens stand. One
-- on a tree's branches, a cliff ledge or a small roofed pocket outside the
-- fort seeded a little "inside" of its own, and every edge of it became an
-- entrance (Teacheroar: "the way in at x30 y187 is a branch", refused six
-- times). fort_starts keeps the citizens who stand in the fort: a start on a
-- treetop never counts; one in a small pocket (under LEDGE_MAX tiles) only
-- when no citizen stands anywhere bigger and that pocket holds the most.
--
-- The cut: an opening wider than the AI walls (50 tiles: titans walked into
-- Teacheroar through one) or one refused for what stands in it. The open
-- area behind it (the "porch": everything reachable from the opening without
-- going below its level) leads down into the fort somewhere: each stair
-- going down from it gets a hatch, which the gate watcher locks like any
-- other gate. Checked first: the hatches must seal the opening off from the
-- dwarves, the porch must not be where the dwarves live, and a ramp down
-- (no hatch fits one) is refused with where it is.
---------------------------------------------------------------------------

LEDGE_MAX = 120          -- tiles: a pocket this small with a citizen in it is a ledge, not the fort
CUT_MAX_PORCH = 6000     -- tiles: an open area bigger than this is the fort itself, not a porch
CUT_MAX_HATCHES = 12
-- (0.105.0 review) the brain's fortify_max_width: a narrower opening is
-- walled, and the scan looks for a cut there only where the AI cut one
FORTIFY_MAX_WIDTH = 50
CUT_SPOTS_KEY = 'ai-overseer/cuts'

-- the entrances the AI cut (key(x, y, z) -> true), kept with the save
function cut_spots()
    if CUT_SPOTS == nil then
        CUT_SPOTS = {}
        for k, v in pairs(U.site_get(CUT_SPOTS_KEY, {})) do if v then CUT_SPOTS[tonumber(k) or k] = true end end
    end
    return CUT_SPOTS
end

-- (each tile of the opening: a rescan may anchor the entrance on another of them)
function was_cut(e)
    local spots = cut_spots()
    for _, k in ipairs(e.inside_list or {}) do if spots[k] then return true end end
    return spots[key(e.x, e.y, e.z)] == true
end

local function note_cut_spot(e)
    local spots = cut_spots()
    spots[key(e.x, e.y, e.z)] = true
    for _, k in ipairs(e.inside_list or {}) do spots[k] = true end
    local out = {}
    for k in pairs(spots) do out[tostring(k)] = true end
    U.site_put(CUT_SPOTS_KEY, out)
end

function fort_starts(starts)
    cache, edge_cache = {}, {}           -- (read fresh: it runs before a scan or a cut)
    local big, groups, order = {}, {}, {}
    local keep_big, seen_tile = {}, {}
    for _, p in ipairs(starts or {}) do
        local k = key(p.x, p.y, p.z)
        local t = T(p.x, p.y, p.z)
        if t and not seen_tile[k] and not treetop(t) and inside_or_courtyard(t, k) then
            seen_tile[k] = true
            if big[k] then
                table.insert(keep_big, p)
            else
                -- a flood from it, stopped at LEDGE_MAX tiles
                local seen, queue, head = {[k] = true}, {k}, 1
                local small = true
                while head <= #queue do
                    if #queue > LEDGE_MAX then small = false break end
                    local ck = queue[head]
                    head = head + 1
                    local x, y, z = unkey(ck)
                    moves(x, y, z, T(x, y, z), function(nx, ny, nz)
                        local nk = key(nx, ny, nz)
                        if seen[nk] then return end
                        local nt = T(nx, ny, nz)
                        if nt and nt.walk and not nt.hidden and not nt.special and not treetop(nt)
                                and inside_or_courtyard(nt, nk) then
                            seen[nk] = true
                            table.insert(queue, nk)
                        end
                    end)
                end
                if small then
                    local id = math.huge
                    for sk in pairs(seen) do if sk < id then id = sk end end
                    if not groups[id] then groups[id] = {}; table.insert(order, id) end
                    table.insert(groups[id], p)
                else
                    for sk in pairs(seen) do big[sk] = true end
                    table.insert(keep_big, p)
                end
            end
        end
    end
    if #keep_big > 0 then return keep_big end
    -- no citizen in a big place (a new fort's first room): the pocket(s) with the most
    local most = 0
    for _, id in ipairs(order) do most = math.max(most, #groups[id]) end
    local out = {}
    for _, id in ipairs(order) do
        if #groups[id] == most then for _, p in ipairs(groups[id]) do table.insert(out, p) end end
    end
    return out
end

-- The porch and its ways down: {n = tiles, stairs = {key...}, ramps = {key...},
-- home = true when a dwarf stands on it, capped = true when too big}.
function porch_of(e, starts)
    cache = cache or {}
    edge_cache = edge_cache or {}
    local home = {}
    for _, p in ipairs(starts or {}) do home[key(p.x, p.y, p.z)] = true end
    local z0 = e.z
    local seen, queue, head = {}, {}, 1
    for _, k in ipairs(e.inside_list) do
        local _, _, kz = unkey(k)
        z0 = math.min(z0, kz)                    -- (the opening may span two levels)
        if not seen[k] then seen[k] = true; table.insert(queue, k) end
    end
    local out = {n = 0, stairs = {}, ramps = {}}
    local stair_seen, ramp_seen = {}, {}
    while head <= #queue do
        if #queue > CUT_MAX_PORCH then out.capped = true break end
        local k = queue[head]
        head = head + 1
        if home[k] then out.home = true end
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        moves(x, y, z, t, function(nx, ny, nz)
            local nk = key(nx, ny, nz)
            if seen[nk] or e.outs[nk] then return end
            local nt = T(nx, ny, nz)
            if not nt or not nt.walk or nt.hidden or nt.special or treetop(nt) or not inside_or_courtyard(nt, nk) then
                return
            end
            if nz < z0 then
                -- a way down below the opening's level: a stair (hatch on the
                -- stair it leaves from) or a ramp
                if nx == x and ny == y then
                    if not stair_seen[k] then stair_seen[k] = true; table.insert(out.stairs, k) end
                elseif not ramp_seen[nk] then
                    ramp_seen[nk] = true
                    table.insert(out.ramps, nk)
                end
                return
            end
            seen[nk] = true
            table.insert(queue, nk)
        end)
    end
    out.n = #queue
    out.tiles = seen             -- (0.105.0 review) the porch's tiles (citizens there are outside)
    table.sort(out.stairs)
    table.sort(out.ramps)
    return out
end

-- Does blocking these keys keep the outside from the dwarves, however big
-- the porch? (seals() with the pocket the porch's size)
local function cut_seals(starts, e, blocked, porch_n)
    local was = POCKET
    POCKET = math.max(POCKET, porch_n + 50)
    local ok, sealed = pcall(seals, starts, {outs = e.outs}, blocked)
    POCKET = was
    return ok and sealed
end

-- The cut for one entrance: {hatches = {key...}, porch = n} or nil, why.
function plan_cut(e, starts)
    cache = cache or {}
    edge_cache = edge_cache or {}
    starts = fort_starts(starts)
    local p = porch_of(e, starts)
    if p.capped then
        return nil, ('the open area behind it runs on for more than %d tiles (it is the fort, not a porch)'):format(CUT_MAX_PORCH)
    end
    if p.home then return nil, 'dwarves live in the open area behind it: no cut that leaves them outside' end
    if #p.ramps > 0 then
        local x, y, z = unkey(p.ramps[1])
        return nil, ('a ramp leads down from the open area at x%d y%d (no hatch fits a ramp): wall it'):format(x, y)
    end
    if #p.stairs == 0 then return nil, 'nothing leads down from the open area behind it' end
    if #p.stairs > CUT_MAX_HATCHES then
        return nil, ('%d stairs lead down from the open area: too many to close with hatches'):format(#p.stairs)
    end
    for _, k in ipairs(p.stairs) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if not t or t.liquid then return nil, ('water on the stair at x%d y%d'):format(x, y) end
    end
    local blocked = {}
    for _, k in ipairs(p.stairs) do blocked[k] = true end
    if not cut_seals(starts, e, blocked, p.n) then
        return nil, 'hatches on its stairs would not seal it (another way leads in)'
    end
    return {hatches = p.stairs, porch = p.n}
end

-- In the scan: hatches (built or planned) on the porch's stairs close an
-- entrance the doors and walls can't. Fills e.equipment / e.sealed /
-- e.closing / e.waiting / e.cut; never changes an entrance it can't close.
function cut_equipment(e, buildings, starts, inside)
    if e.sealed or e.closing or e.kind ~= 'surface' or #e.door_spots > 0 then return end
    local hatch_at, pending_at, any = {}, {}, false
    for _, b in ipairs(buildings) do
        if b.x1 == b.x2 and b.y1 == b.y2 then
            if b.kind == 'hatch' then hatch_at[key(b.x1, b.y1, b.z)] = b; any = true
            elseif b.kind == 'pending' and b.what == 'hatch' then pending_at[key(b.x1, b.y1, b.z)] = b; any = true end
        end
    end
    if not any then return end
    local p = porch_of(e, starts)
    if p.capped or p.home or #p.ramps > 0 or #p.stairs == 0 then return end
    local built, waiting = {}, 0
    for _, k in ipairs(p.stairs) do
        if hatch_at[k] then table.insert(built, hatch_at[k])
        elseif pending_at[k] then waiting = waiting + 1
        else return end                          -- a stair with nothing: not the cut
    end
    if waiting > 0 then
        e.closing, e.cut = true, true
        e.waiting = e.waiting or {}
        e.waiting.hatch = math.max(e.waiting.hatch or 0, waiting)   -- (the scan may have counted them near)
        return
    end
    local blocked = {}
    for _, b in ipairs(built) do blocked[key(b.x1, b.y1, b.z)] = true end
    if cut_seals(starts, e, blocked, p.n) then
        for _, b in ipairs(built) do table.insert(e.equipment, b) end
        table.sort(e.equipment, function(a, b) return a.id < b.id end)
        e.sealed, e.cut = true, true
        -- (0.105.0 review) for the watcher: the porch (outside) and the hatches
        e.porch = p.tiles
        e.hatch_keys = {}
        for k in pairs(blocked) do table.insert(e.hatch_keys, k) end
    end
end

-- For the scan: which open surface entrances a cut would close
-- (e.cut_hatches) or why not (e.cut_why); the widest first, CUT_SURVEY_MAX
-- of them (each is a walk of its open area).
CUT_SURVEY_MAX = 6
function cut_survey(entrances, starts)
    local list = {}
    for _, e in ipairs(entrances) do
        if not e.sealed and not e.closing and e.kind == 'surface' and #e.door_spots == 0 then
            table.insert(list, e)
        end
    end
    table.sort(list, function(a, b) return a.width > b.width end)
    for i = 1, math.min(#list, CUT_SURVEY_MAX) do
        local e = list[i]
        local ok, plan, why = pcall(plan_cut, e, starts)
        if ok and plan then e.cut_hatches = #plan.hatches
        else e.cut_why = ok and why or ('error: ' .. tostring(plan):sub(1, 100)) end
    end
end

-- The action: hatches on the porch's stairs (buildingplan waits for hatch
-- covers; the masons are asked by the gate parts rule).
function cut_entrance(id, starts, dry_run)
    local e
    for _, x in ipairs(GATES.entrances or {}) do if x.id == id then e = x end end
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    cache, edge_cache = {}, {}
    local plan, why = plan_cut(e, starts or citizen_starts())
    if not plan then return {ok = false, error = why} end
    if dry_run then                    -- (0.105.0 review) the plan, nothing placed
        local spots = {}
        for _, k in ipairs(plan.hatches) do
            local x, y, z = unkey(k)
            table.insert(spots, ('%d,%d,%d'):format(x, y, z))
        end
        return {ok = true, dry_run = true, style = 'cut', hatches = #plan.hatches, pieces = spots, porch = plan.porch}
    end
    local placed, failed, pieces = 0, {}, {}
    for _, k in ipairs(plan.hatches) do
        local x, y, z = unkey(k)
        local ok, reason = place('H', {x = x, y = y, z = z})
        if ok then
            placed = placed + 1
            table.insert(pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, ('x%d y%d: %s'):format(x, y, tostring(reason)))
        end
    end
    if placed == 0 then
        return {ok = false, error = 'no hatch could be placed (' .. table.concat(failed, '; '):sub(1, 200) .. ')'}
    end
    note_cut_spot(e)                   -- (0.105.0 review) the scan looks for its hatches from now on
    return {ok = true, style = 'cut', hatches = placed, pieces = pieces, porch = plan.porch,
            failed = #failed > 0 and table.concat(failed, '; '):sub(1, 300) or nil}
end

-- A new fort: forget the old one's gates.
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-gates'] = function(sc)
        if sc == SC_MAP_UNLOADED then GATES = {scanned = false}; CUT_SPOTS = nil end   -- (0.105.0 review CUT_SPOTS)
    end
end

---------------------------------------------------------------------------
-- (0.105.0) The watcher's state kept with the save. GATES lives only in
-- Lua memory and is cleared when the map unloads: a drawbridge the watcher
-- raised before a reload (or a crash and the reviver's load) was never
-- lowered by open_all, which knew nothing of it. What the watcher holds
-- (armed, and each closed entrance's gates by building id: entrance ids are
-- list places and change) goes into the site data whenever it changes, and
-- comes back after a load: the watcher re-armed once the entrances are
-- scanned again, closed gates matched to their entrances; before the scan,
-- open_all opens the saved gates directly.
-- Kept in its own functions: wrappers round arm, open_all, check and summary.
---------------------------------------------------------------------------
GATES_SAVE_KEY = 'ai-overseer/gates'
-- (apart from GATES, which a scan rebuilds): read back yet, what was read, what was last written
GATES_SAVE = GATES_SAVE or {}

local function saved_read()
    return U.site_get(GATES_SAVE_KEY, {})
end

-- What the watcher holds now, by building id.
function gates_snapshot()
    local gates = {}
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed and GATES.closed[e.id] then
            for _, g in ipairs(e.equipment or {}) do
                table.insert(gates, {id = g.id, kind = g.kind, lever_id = g.lever_id,
                                     drive_lever = g.lever_driven and g.drive_lever or nil})     -- (0.105.23)
            end
            for _, g in ipairs(e.outer or {}) do         -- (0.105.23) the gatehouse's bridge
                table.insert(gates, {id = g.id, kind = g.kind, lever_id = g.lever_id})
            end
        end
    end
    return {armed = GATES.armed == true, gates = gates}
end

local function same_snapshot(a, b)
    if (a.armed == true) ~= (b.armed == true) then return false end
    local ga, gb = a.gates or {}, b.gates or {}
    if #ga ~= #gb then return false end
    for i = 1, #ga do
        if ga[i].id ~= gb[i].id or ga[i].lever_id ~= gb[i].lever_id then return false end
    end
    return true
end

-- Into the save when it changed. Not before the saved state was read back
-- (a fresh GATES after a reload must not write over what the save holds).
function gates_persist()
    -- (nor while the saved state waits for a scan to be matched up)
    if not GATES_SAVE.restored or GATES_SAVE.saved then return false end
    local snap = gates_snapshot()
    if GATES_SAVE.persisted and same_snapshot(snap, GATES_SAVE.persisted) then return false end
    local ok = U.site_put(GATES_SAVE_KEY, snap)
    if ok then GATES_SAVE.persisted = snap end
    return ok
end

local function lever_pull_pending(lever_id)
    local okp, pending = pcall(function()
        local lv = df.building.find(lever_id)
        for _, j in ipairs(lv and lv.jobs or {}) do
            if j.job_type == df.job_type.PullLever then return true end
        end
        return false
    end)
    return okp and pending
end

-- Open the saved gates straight from their building ids (no scan needed).
-- Returns opened, still waiting.
function open_saved_gates(saved)
    local opened, waiting = 0, 0
    local held = seal_holds()            -- (0.105.26 seal fix) the cavern seal's stay shut
    for _, g in ipairs(saved.gates or {}) do
        local b = df.building.find(g.id)
        if b and seal_has(held, g) then
            waiting = waiting + 1
        elseif b then
            if g.kind == 'bridge' then
                local ok, raised = pcall(function() return b.gate_flags.raised end)
                if ok and raised then
                    if g.lever_id and #b.jobs == 0 and not bridge_occupied(b) and not lever_pull_pending(g.lever_id) then
                        local _, rv = dfhack.run_command_silent('lever', 'pull', '--id', tostring(g.lever_id))
                        if rv == CR_OK then opened = opened + 1 end
                    end
                    waiting = waiting + 1
                end
            else
                local ok = pcall(function()
                    if b.door_flags.forbidden then b.door_flags.forbidden = false opened = opened + 1 end
                end)
                if not ok then waiting = waiting + 1 end
                -- (0.105.23) a hatch on a lever: its lever opens it (at once)
                if ok and g.drive_lever and door_shut(b) then
                    if pull_instant(g.drive_lever) then opened = opened + 1 else waiting = waiting + 1 end
                end
            end
        end
    end
    return opened, waiting
end

-- After a load: the saved state read back once; once the entrances are
-- scanned, the watcher re-armed and the closed gates matched up.
function gates_restore()
    if not GATES_SAVE.restored then
        GATES_SAVE.restored = true
        local saved = saved_read()
        GATES_SAVE.persisted = saved
        -- (nothing closed and not armed: nothing to bring back)
        if saved.armed or next(saved.gates or {}) ~= nil then GATES_SAVE.saved = saved end
    end
    local saved = GATES_SAVE.saved
    if not saved or not GATES.scanned or not GATES.entrances then return nil end
    GATES_SAVE.saved = nil
    local ids = {}
    for _, g in ipairs(saved.gates or {}) do ids[g.id] = true end
    local closed = {}
    for _, e in ipairs(GATES.entrances) do
        for _, g in ipairs(e.equipment or {}) do
            if ids[g.id] then closed[e.id] = true end
        end
    end
    if saved.armed and not GATES.armed then
        pcall(GATES_ORIG.arm)
    end
    GATES.closed = GATES.closed or {}
    for id in pairs(closed) do GATES.closed[id] = true end
    if not GATES.armed and next(GATES.closed) ~= nil then
        pcall(GATES_ORIG.open_all)     -- (waiting gates: its reopen timer tries again)
    end
    GATES_SAVE.restored_from_save = {armed = saved.armed == true, gates = #(saved.gates or {})}
    return GATES_SAVE.restored_from_save
end

---------------------------------------------------------------------------
-- (0.105.26) Citizens stranded outside. E (3-5 Nov): 8 citizens were shut
-- out after a surface fire and died there; nothing saw it. A citizen is
-- stranded when they stand outside the map of the inside (or on a cut
-- entrance's porch) and can't walk back in: their walk group isn't the
-- fort's interior (the founding stair under its lid, else a meeting hall,
-- else where most citizens inside stand), or every way in from where they
-- stand is shut. Why, when it can be told: a gate the watcher holds shut
-- ("lockdown"), another gate shut ("gate_shut": a raised bridge, a locked
-- door, a lever's hatch), or no way at all ("no_path": a collapse, a fire's
-- ruin, a channel). How long each has been out is counted from the first
-- report that saw them out (a reload starts the count again).
---------------------------------------------------------------------------

STRANDED_SINCE = STRANDED_SINCE or {}      -- unit id -> abs tick first seen outside
STRANDED_MAX = 20                          -- rows reported at most
STRANDED_OUTS = 40                         -- each entrance's outside tiles read for their walk groups

local function wgroup(x, y, z)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    return ok and type(g) == 'number' and g or 0
end

-- The fort's interior: {what, x, y, z, group}, or nil.
function fort_interior()
    for _, e in ipairs(GATES.entrances or {}) do
        if e.lid then
            local okh, h = pcall(lid_hatch, e)
            if okh and h then
                local g = wgroup(h.x, h.y, h.z - 1)
                if g ~= 0 then return {what = 'founding stair', x = h.x, y = h.y, z = h.z - 1, group = g} end
            end
        end
    end
    local okz, zones = pcall(function() return df.global.world.buildings.other.ZONE_MEETING_HALL end)
    for _, zn in ipairs(okz and zones or {}) do
        local okp, x, y, z = pcall(function() return zn.centerx, zn.centery, zn.z end)
        if okp and x then
            local g = wgroup(x, y, z)
            if g ~= 0 then return {what = 'meeting hall', x = x, y = y, z = z, group = g} end
        end
    end
    if GATES.inside then
        local count, best, bg = {}, 0, nil
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            if GATES.inside[key(u.pos.x, u.pos.y, u.pos.z)] then
                local g = wgroup(u.pos.x, u.pos.y, u.pos.z)
                if g ~= 0 then
                    count[g] = (count[g] or 0) + 1
                    if count[g] > best then best, bg = count[g], g end
                end
            end
        end
        if bg then return {what = 'citizens inside', group = bg} end
    end
end

-- Is one gate shut now? A lever's door or hatch by DF's `closed`, a bridge
-- raised, any other door or hatch locked.
local function gate_shut_now(g)
    local okb, b = pcall(df.building.find, g.id)
    if not okb or not b then return false end
    if g.kind == 'bridge' then
        local ok, r = pcall(function() return b.gate_flags.raised end)
        return ok and r or false
    end
    if g.lever_driven then return door_shut(b) == true end
    local ok, f = pcall(function() return b.door_flags.forbidden end)
    return ok and f or false
end

-- One entrance: shut (and by the AI's watcher?), and the walk groups of its
-- outside tiles (where a citizen stands who would come in by it).
local function entrance_ways(e)
    local groups, n = {}, 0
    for k in pairs(e.outs or {}) do
        local x, y, z = unkey(k)
        local g = wgroup(x, y, z)
        if g ~= 0 then groups[g] = true end
        n = n + 1
        if n >= STRANDED_OUTS then break end
    end
    local shut, by_ai = false, false
    if GATES.closed and GATES.closed[e.id] then
        shut, by_ai = true, true
    elseif #(e.equipment or {}) > 0 then
        -- shut when every gate it needs is shut (each one seals it alone? no:
        -- the scan keeps only the ones it needs, so any one open lets them in)
        shut = true
        for _, g in ipairs(e.equipment) do
            if not gate_shut_now(g) then shut = false end
        end
    end
    return {e = e, groups = groups, shut = shut, by_ai = by_ai}
end

local function readable(u)
    local ok, n = pcall(dfhack.units.getReadableName, u)
    if not ok then return 'unit ' .. tostring(u.id) end
    if dfhack.df2utf then
        local okc, c = pcall(dfhack.df2utf, n)
        if okc and c then n = c end
    end
    return n
end

local function on_cavern_tile(p)
    local ok, des = pcall(dfhack.maps.getTileFlags, p.x, p.y, p.z)
    return ok and des and (des.feature_global or des.feature_local) and true or false
end

-- Pure: why a citizen outside can't come in, from their walk group, the
-- interior's, and the ways in. nil: not stranded. Returns cause, way.
function stranded_cause(g, interior_group, ways)
    local mine, open_way = {}, false
    for _, w in ipairs(ways) do
        if g ~= 0 and w.groups[g] then
            table.insert(mine, w)
            if not w.shut then open_way = true end
        end
    end
    local cut_off = interior_group ~= nil and g ~= 0 and g ~= interior_group
    if #mine > 0 and not open_way then
        -- every way in from where they stand is shut
        local w = mine[1]
        for _, m in ipairs(mine) do if m.by_ai then w = m break end end
        return w.by_ai and (GATES.armed and 'lockdown' or 'gate_shut') or 'gate_shut', w
    end
    if cut_off then return 'no_path', nil end
    return nil
end

-- {interior, list = [{id, name, x, y, z, out_ticks, out_days, cause,
-- in_cavern?, entrance?, by_ai?, danger_near?, gate_danger?}], total} or
-- nil without a map of the inside.
function stranded_citizens()
    if not GATES.scanned or not GATES.inside then return nil end
    local now = U.abs_tick()
    local interior = fort_interior()
    local ways = {}
    for _, e in ipairs(GATES.entrances or {}) do
        local ok, w = pcall(entrance_ways, e)
        if ok and w then table.insert(ways, w) end
    end
    local porches = {}
    for _, e in ipairs(GATES.entrances or {}) do if e.porch then table.insert(porches, e.porch) end end
    local okv, vis = pcall(visible_dangers)
    vis = okv and vis or {}
    local seen, list, total = {}, {}, 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        seen[u.id] = true
        local p = u.pos
        local k = key(p.x, p.y, p.z)
        local out = not GATES.inside[k]
        for _, po in ipairs(porches) do if po[k] then out = true end end
        if not out then
            STRANDED_SINCE[u.id] = nil
        else
            STRANDED_SINCE[u.id] = STRANDED_SINCE[u.id] or now
            local g = wgroup(p.x, p.y, p.z)
            local cause, w = stranded_cause(g, interior and interior.group or nil, ways)
            if cause then
                total = total + 1
                if #list < STRANDED_MAX then
                    local t = now - STRANDED_SINCE[u.id]
                    local row = {id = u.id, name = readable(u), x = p.x, y = p.y, z = p.z, cause = cause,
                                 out_ticks = t, out_days = t // DAY_TICKS, group = g}
                    if on_cavern_tile(p) then row.in_cavern = true end
                    local near = math.huge
                    for _, d in ipairs(vis) do
                        near = math.min(near, math.max(math.abs(d.pos.x - p.x), math.abs(d.pos.y - p.y))
                                        + 3 * math.abs(d.pos.z - p.z))
                    end
                    if near < math.huge then row.danger_near = near end
                    if w then
                        row.entrance = {id = w.e.id, kind = w.e.kind, x = w.e.x, y = w.e.y, z = w.e.z}
                        row.by_ai = w.by_ai
                        local gd = math.huge
                        for _, d in ipairs(vis) do
                            local okd, dd = pcall(distance_to, w.e, d.pos)
                            if okd then gd = math.min(gd, dd) end
                        end
                        if gd < math.huge then row.gate_danger = gd end
                    end
                    table.insert(list, row)
                end
            end
        end
    end
    for id in pairs(STRANDED_SINCE) do if not seen[id] then STRANDED_SINCE[id] = nil end end
    return {interior = interior, list = list, total = total}
end

-- (the file's own functions, as just defined above: a reload of the script takes the new ones)
GATES_ORIG = {arm = arm, open_all = open_all, check = check, summary = summary}

function arm()
    pcall(gates_restore)
    local r = GATES_ORIG.arm()
    pcall(gates_persist)
    return r
end

function open_all()
    pcall(gates_restore)
    local saved = GATES_SAVE.saved
    local r = GATES_ORIG.open_all()
    if saved and not GATES.scanned then
        -- no map of the entrances yet: the saved gates opened by their ids;
        -- the saved state is kept (unarmed) until they are all down
        local ok, opened, waiting = pcall(open_saved_gates, saved)
        if ok then
            r.opened = (r.opened or 0) + opened
            if waiting > 0 then r.waiting = (r.waiting or 0) + waiting end
            saved.armed = false
            if waiting == 0 then GATES_SAVE.saved = {armed = false, gates = {}} end
            U.site_put(GATES_SAVE_KEY, GATES_SAVE.saved)
            GATES_SAVE.persisted = GATES_SAVE.saved
        end
        return r
    end
    pcall(gates_persist)
    return r
end

function check()
    GATES_ORIG.check()
    pcall(gates_persist)
end

function summary()
    pcall(gates_restore)
    -- (0.105.23) a link made while no watch ran (a reload): taken up, and a
    -- hatch it shut opened, at the next report at the latest
    if GATES.scanned then
        pcall(attach_links)
        if not GATES.armed then pcall(open_lever_hatches) end
        if link_jobs_pending() then pcall(link_watch_start) end
    end
    local out = GATES_ORIG.summary()
    -- (0.105.26) citizens outside who can't walk back in (nil without a map of the inside)
    local oks, st = pcall(stranded_citizens)
    if oks and st then
        out.stranded, out.stranded_total = st.list, st.total
        out.interior = st.interior
    elseif not oks then
        out.stranded_error = tostring(st):sub(1, 160)
    end
    pcall(gates_persist)
    -- what came back from the save after a load (the brain says it once)
    out.restored = GATES_SAVE.restored_from_save
    if GATES_SAVE.saved and next(GATES_SAVE.saved.gates or {}) ~= nil then
        -- gates the save says are closed, not yet matched to a scan: the
        -- planner may open them (open_gates) before the scan
        out.saved_closed = #GATES_SAVE.saved.gates
        if GATES_SAVE.saved.armed then out.armed = true end
    end
    return out
end

if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-gates-save'] = function(sc)
        if sc == SC_MAP_UNLOADED then GATES_SAVE = {} end
    end
end
