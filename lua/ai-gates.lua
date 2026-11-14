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

-- (0.105.40, 13e) A tile type's fixed attributes, read once: {walk, shape,
-- material} (names), as tile() and under_tree() read them from DF's tables
-- (the same for every tile of that type, for as long as the game runs; kept
-- per df.tiletype.attrs, so a test's own fake tables get their own)
local TT_INFO, TT_INFO_OF, TT_INFO_DF = {}, nil, nil
local function tt_info(tt)
    local attrs_of = df.tiletype.attrs
    if TT_INFO_OF ~= attrs_of or TT_INFO_DF ~= df then TT_INFO, TT_INFO_OF, TT_INFO_DF = {}, attrs_of, df end
    local i = TT_INFO[tt]
    if i == nil then
        local attrs = attrs_of[tt]
        local shape = attrs.shape
        i = {walk = df.tiletype_shape.attrs[shape].walkable == true, shape = df.tiletype_shape[shape],
             material = df.tiletype_material[attrs.material]}
        TT_INFO[tt] = i
    end
    return i
end

-- A tree's trunk, branches or leaves within a few levels straight above?
function under_tree(x, y, z)
    for dz = 1, 6 do
        local tt = dfhack.maps.getTileType(x, y, z + dz)
        if not tt then return false end
        local info = tt_info(tt)
        local m = info.material
        if m == 'TREE' or m == 'ROOT' or m == 'PLANT' then return true end
        local shape = info.shape
        if shape ~= 'EMPTY' and shape ~= 'NONE' then return false end      -- a roof or rock: not a tree's shade
    end
    return false
end

-- (13e) each flag read once (every read is a call into DFHack)
function tile(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    local des, occ = dfhack.maps.getTileFlags(x, y, z)
    if not des then return nil end
    local info = tt_info(tt)
    local flow, outside = des.flow_size, des.outside
    return {
        walk = info.walk,
        shape = info.shape,
        outside = outside,
        feature = des.feature_global,
        special = des.feature_local,
        hidden = des.hidden,
        liquid = flow > 0,
        depth = flow,                                       -- 0-7
        magma = flow > 0 and is_magma(des),
        salt = des.water_salt, stagnant = des.water_stagnant, aquifer = des.water_table,
        material = info.material,                           -- RIVER, POOL, CONSTRUCTION...
        occupied = occ ~= nil and occ.building ~= df.tile_building_occ.None,   -- something built or planned
        canopy = not outside and not des.subterranean and under_tree(x, y, z),
    }
end

-- (0.105.40, 13e) Is tile(x, y, z) a ramp? The same answer as
-- `local t = tile(x, y, z); t and t.shape == 'RAMP'` from the two reads it
-- rests on, not tile()'s twenty-odd: the walks look at the eight tiles below
-- every tile they cross for a ramp up, and most are never looked at again.
-- GAME_TILE: the game's own tile(); with a test's in its place the walks read
-- tile() itself.
function tile_is_ramp(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return false end
    local des = dfhack.maps.getTileFlags(x, y, z)
    if not des then return false end
    return tt_info(tt).shape == 'RAMP'
end
GAME_TILE = tile

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

-- (0.105.33) The "AI gate..." levers with no link yet (built or planned):
-- {{id, x, y, z}}. Empty when they can't be read.
function unlinked_ai_levers()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and tostring(b.name or ''):lower():find('^ai gate')
                    and #b.linked_mechanisms == 0 then
                table.insert(out, {id = b.id, x = b.x1, y = b.y1, z = b.z})
            end
        end
    end)
    return out
end

-- (0.105.33) Can this unlinked lever work this entrance's drawbridge? Inside
-- the fort (when the map of the inside is given) and away from the gate (20+
-- tiles or 4+ levels: the brain's _lever_far_enough, the one it links).
-- Unknown position: yes.
function lever_serves(l, e, inside)
    if type(l.x) ~= 'number' or type(l.y) ~= 'number' or type(l.z) ~= 'number' then return true end
    if inside and not inside[key(l.x, l.y, l.z)] then return false end
    local ex, ey, ez = e.x or 0, e.y or 0, e.z or 0
    return math.abs(l.z - ez) > 3 or math.max(math.abs(l.x - ex), math.abs(l.y - ey)) >= 20
end

-- (0.105.33) An unlinked AI lever that can serve this entrance (inside: the map of the inside, or nil)?
function lever_waiting_for(e, inside, levers)
    for _, l in ipairs(levers or AI_LEVERS_WAITING or {}) do
        if lever_serves(l, e, inside) then return l end
    end
    return nil
end

-- Set by gate_buildings: the unlinked "AI gate..." levers (unlinked_ai_levers),
-- so a bridge no lever works may be waiting for one. AI_LEVER_WAITING: any.
AI_LEVERS_WAITING = {}
AI_LEVER_WAITING = false
-- (0.105.33) An entrance whose drawbridge waits for such a lever reads
-- "closing" for at most LEVER_WAIT_DAYS days (the lever never linked: open
-- again, so the brain closes it some other way)
LEVER_WAIT_DAYS = 7

function gate_buildings()
    local levers, lever_pos = lever_links()
    AI_LEVERS_WAITING = unlinked_ai_levers()
    AI_LEVER_WAITING = #AI_LEVERS_WAITING > 0
    local out = {}
    -- (13e) the types looked up once, and a building's build stage read only
    -- for a gate or a construction (every other building in the fort was asked)
    local DOOR, HATCH, BRIDGE, CONSTRUCTION = df.building_type.Door, df.building_type.Hatch,
        df.building_type.Bridge, df.building_type.Construction
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        local kind = (t == DOOR and 'door') or (t == HATCH and 'hatch')
            or (t == BRIDGE and 'bridge') or nil
        local built = (kind or t == CONSTRUCTION) and b:getBuildStage() >= b:getMaxBuildStage()
        if not built and (kind or (t == CONSTRUCTION
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

-- (13e) this file's locals the later parts use, as module names (each takes
-- them back as locals of its own)
_ENV.U, _ENV.key, _ENV.unkey, _ENV.STAIR_UP, _ENV.STAIR_DOWN, _ENV.ref_ids = U, key, unkey, STAIR_UP, STAIR_DOWN, ref_ids

---------------------------------------------------------------------------
-- (13e) The rest of the gates lives in parts beside this file
-- (ai-gates-<part>.lua): scan (the map of the inside, find_entrances, scan),
-- watch (the watcher, check, arm, open_all, doors), fortify (the gate style's
-- plans), works (stockpiles moved, fortify, lever links, levers, clear_gate,
-- traps, the gatehouse), wings (wing walls, summary, the vertical cut), save
-- (the state kept with the save, stranded citizens) and stuck (a gate the
-- game treats as shut; the save-aware arm/open_all/check/summary). Each runs
-- in this module's own environment, so its names stay reqscript('ai-gates').name
-- for the bridge and the other modules, and a test's swap (G.tile = ...)
-- reaches every part. They load in this order (the last one wraps the
-- watcher's arm/open_all/check/summary defined before it). DFHack reloads a
-- module when its own file changes: a change to a part alone is picked up
-- once ai-gates.lua is touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'scan', 'watch', 'fortify', 'works', 'wings', 'save', 'stuck'}
-- each part marks the version it came with (the bridge's `version` lists one
-- that differs from BRIDGE_VERSION); started afresh at each load, so a part
-- that failed to load shows as unmarked
PART_VERSIONS = {['ai-gates'] = '0.105.44'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-gates-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-gates: ' .. name .. '.lua is missing (it goes beside ai-gates.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
