-- ai-builder-rooms-walls: rooms opened up, their walls built back (room_gaps,
-- repair_rooms, the room census and the walls that stall on smoothing marks).
--
-- (0.105.113) Split off ai-builder-rooms (which had reached the size limit).
-- A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-rooms-walls'] = '0.105.129'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, has, ez = info, has, ez

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

-- (0.105.33 L5) May a wall go on this room's gap? Not with a creature on it,
-- and not where it cuts a way the dwarves walk: the gap's walkable
-- neighbours on its level (the walls already accepted this pass counted as
-- built) must still meet round it, by a walk that stops once they all have
-- met (ROOM_WALL_WALK_MAX tiles at most: past that, unsure, so no wall). As
-- the cistern's gap filler does (cistern_gap_plan). true, or false and why.
ROOM_WALL_WALK_MAX = 2000
local R_DIR8 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}
function room_wall_ok(g, walled)
    local function key(x, y) return x .. ',' .. y end
    local function open_at(x, y)
        if (x == g.x and y == g.y) or walled[key(x, y) .. ',' .. g.z] then return false end
        local t = tile_info(x, y, g.z)
        return t ~= nil and (CISTERN_STANDABLE or {})[tostring(t.shape)] == true
            and not (t.liquid and (t.depth or 0) >= 4)
    end
    if units_on_tiles({{x = g.x, y = g.y}}, g.z) > 0 then return false, 'a creature stands there' end
    local starts, want = {}, {}
    for _, e in ipairs(R_DIR8) do
        local nx, ny = g.x + e[1], g.y + e[2]
        if open_at(nx, ny) then table.insert(starts, {x = nx, y = ny}); want[key(nx, ny)] = true end
    end
    if #starts < 2 then return true end
    local left = #starts - 1
    local seen, queue, i = {[key(starts[1].x, starts[1].y)] = true}, {starts[1]}, 1
    while i <= #queue do
        if i > ROOM_WALL_WALK_MAX then return false, 'too much ground round it to be sure the wall cuts no way' end
        local q = queue[i]; i = i + 1
        for _, e in ipairs(R_DIR8) do
            local nx, ny = q.x + e[1], q.y + e[2]
            local k = key(nx, ny)
            if not seen[k] and open_at(nx, ny) then
                seen[k] = true
                if want[k] then
                    left = left - 1
                    if left == 0 then return true end
                end
                table.insert(queue, {x = nx, y = ny})
            end
        end
    end
    return false, 'a wall there would cut a way the dwarves walk'
end

function room_gaps(limit)
    local open_set = designed_open()
    local walled = {}           -- (0.105.33 L5) the walls accepted so far
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
                    -- (0.105.33 L5) a wall only where it cuts no way and shuts nobody in
                    local ok = p == door_at or room_wall_ok(p, walled)
                    if ok then
                        if p ~= door_at then walled[p.k] = true end
                        gaps = gaps + 1
                        total = total + 1
                        if #out < (limit or REPAIR_MAX) then
                            table.insert(out, {x = p.x, y = p.y, z = p.z, door = (p == door_at) or nil})
                        end
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
