-- ai-builder-rooms: rooms and zones: the gate dogs' pen, walls built back, extra workshops,
-- feeder stockpiles, how full the stockpiles are, furniture into zones, slabs,
-- the planned buildings that wait.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-rooms'] = '0.105.41'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, has, ez = info, has, ez

-- (0.104.83) A small pen for war dogs just inside a gate: a free 3x3 of
-- inside floor (no building, zone, designation, water or sky) within 8
-- tiles of the gate, on its level or the two below, nearest first.
function gate_dog_pen(params, dry_run)
    OFFSET = elevation_offset()
    -- (0.105.33) the tile cache only for the search, cleared on every way out
    CACHE = {}
    local okp, best = pcall(function()
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
        return best
    end)
    CACHE = nil
    if not okp then return {ok = false, error = 'the pen search failed: ' .. tostring(best):sub(1, 160)} end
    if not best then return {ok = false, rejected = true, error = 'no free 3x3 of inside floor near the gate'} end
    local cell = {{x = 0, y = 0, text = ('n{name="%s"}(3x3)'):format(params.name or 'AI gate dogs')}}
    local good, failed = qf_try('zone', cell, best.z, best.x, best.y, dry_run)
    if not good then return {ok = false, rejected = failed == 'dry' or nil, error = 'the game refused the pen'} end
    return {ok = true, x = best.x, y = best.y, elevation = ez(best.z), dry_run = dry_run or nil}
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

-- --- soil floors finished with blocks (0.105.30, construction spec 3.3) -------------
--
-- Soil and sand can't be smoothed or engraved, so a hall dug in soil (the
-- Garden fort's dining on its farm level) stays a mud floor however grand
-- the fort. In a finished project of a hall kind, each interior floor tile
-- of SOIL material with nothing on it (no building, door, farm plot, stair,
-- zone furniture, dig mark or water) gets a constructed floor (`Cf`), at
-- most SOIL_FLOOR_MAX a call. Rock floors are left to smoothing. The tiles
-- placed go on the project's record (p.soil_floors, "x,y" at p.z).
-- Material: buildingplan's filter is left as it is [verify: no per-building
-- item filter is relied on]; the brain waits until free blocks cover the
-- tiles, so blocks are what lies nearest.
SOIL_FLOOR_KINDS = {dining = true, tavern = true, temple = true, library = true, memorial = true}
SOIL_FLOOR_MAX = 60
SOIL_FLOOR_PHASES = {decorate = true, done = true}       -- finished (finish_project has run)

local function soil_floor_tiles(p, limit)
    local out, total = {}, 0
    local a = anchor_of(p)
    if not a or not p.z then return out, 0 end
    local done = {}
    for _, k in ipairs(type(p.soil_floors) == 'table' and p.soil_floors or {}) do done[tostring(k)] = true end
    local xs = {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do table.insert(xs, {a.x + x, a.y + y}) end
    end
    table.sort(xs, function(u, v) return u[2] < v[2] or (u[2] == v[2] and u[1] < v[1]) end)
    for _, xy in ipairs(xs) do
        local x, y, z = xy[1], xy[2], p.z
        local t = tile_info(x, y, z)
        if t and t.shape == 'FLOOR' and t.material == 'SOIL' and not t.building and not t.designated
                and not t.liquid and not t.outside and not t.hidden and not done[x .. ',' .. y]
                and not building_at(x, y, z) then
            local farm = false
            for _, kz in ipairs(zone_types(x, y, z)) do
                if kz == 'FarmPlot' or kz == 'Pen' or kz == 'Pond' then farm = true end
            end
            if not farm then
                total = total + 1
                if #out < (limit or SOIL_FLOOR_MAX) then table.insert(out, {x = x, y = y, z = z}) end
            end
        end
    end
    return out, total
end

local function soil_floor_project(p)
    return type(p) == 'table' and SOIL_FLOOR_KINDS[p.kind] and SOIL_FLOOR_PHASES[p.phase] and type(p.cells) == 'table'
end

-- {projects = {{project_id, kind, elevation, tiles, floored}}, tiles, floored, blocks_needed}
function soil_floor_report()
    OFFSET = elevation_offset()
    local out = {projects = {}, tiles = 0, floored = 0, blocks_needed = 0}
    local ok, data = pcall(load_projects)
    if not ok or type(data) ~= 'table' then return out end
    for _, p in ipairs(data.list or {}) do
        if soil_floor_project(p) then
            local okt, _, n = pcall(soil_floor_tiles, p, 0)
            n = okt and n or 0
            local floored = type(p.soil_floors) == 'table' and #p.soil_floors or 0
            if n > 0 or floored > 0 then
                table.insert(out.projects, {project_id = p.id, kind = p.kind, elevation = ez(p.z),
                                            tiles = n, floored = floored})
                out.tiles = out.tiles + n
                out.floored = out.floored + floored
            end
        end
    end
    out.blocks_needed = out.tiles
    return out
end

function floor_soil_rooms(project_id, dry_run)
    OFFSET = elevation_offset()
    local data = load_projects()
    local p
    for _, q in ipairs(data.list or {}) do if q.id == project_id then p = q end end
    if not p then return {ok = false, rejected = true, error = 'no such project'} end
    if not SOIL_FLOOR_KINDS[p.kind] then
        return {ok = false, rejected = true, error = 'soil floors are finished in halls only (dining, tavern, temple, library, memorial)'}
    end
    if not SOIL_FLOOR_PHASES[p.phase] then
        return {ok = false, rejected = true, error = 'that project is not finished yet'}
    end
    local tiles, total = soil_floor_tiles(p, SOIL_FLOOR_MAX)
    if #tiles == 0 then return {ok = false, rejected = true, error = 'no soil floor left bare in that project'} end
    local cells = {}
    for _, t in ipairs(tiles) do table.insert(cells, {x = t.x, y = t.y, text = 'Cf'}) end
    local good, failed, stats = qf_try('build', cells, p.z, 0, 0, dry_run, 1, false)
    if not good then
        return {ok = false, rejected = failed == 'dry' or nil,
                error = 'the game would not place floors there' .. (failed == 'dry' and ' (dry run refused)' or '')}
    end
    local placed = stat(stats, 'build_designated')
    if not dry_run then
        p.soil_floors = type(p.soil_floors) == 'table' and p.soil_floors or {}
        for _, t in ipairs(tiles) do table.insert(p.soil_floors, t.x .. ',' .. t.y) end
        save_projects(data)
    end
    return {ok = true, project_id = p.id, kind = p.kind, floors = placed, tiles = total,
            left = math.max(0, total - #tiles), elevation = ez(p.z), blocks_needed = #tiles,
            dry_run = dry_run or nil}
end

-- --- extra workshops ----------------------------------------------------------------
--
-- Workshops the fort has far too many of (0.75.0 built 116 soap maker's:
-- the report didn't recognise them). All but `keep` taken down, the idle
-- ones (no job), up to `max` a call; the dug rooms are left as they are.
-- (13c) A workshop's name: DF's workshop type, and for the custom ones (the
-- soap maker's, the screw press) the AI's name or 'Custom:<the raws' code>'.
-- The same as the bridge's workshop_name (its report), which can use this one.
CUSTOM_SHOP_NAMES = {SOAP_MAKER = 'SoapMaker', SOAP_MAKERS = 'SoapMaker', SCREW_PRESS = 'ScrewPress'}
function workshop_name(b)
    local name = df.workshop_type[b.type] or tostring(b.type)
    if name == 'Custom' then
        local ok, code = pcall(function() return df.building_def.find(b.custom_type).code end)
        if ok and code then name = CUSTOM_SHOP_NAMES[code] or ('Custom:' .. code) end
    end
    return name
end

local function is_kind(b, kind)
    local ok, yes = pcall(function()
        return b:getType() == df.building_type.Workshop and workshop_name(b) == kind
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
    if not f.on_ground or f.in_job or f.in_inventory or item_held(item) then return false end
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
    local good, failed = qf_try('place', cell, r.z, r.x, r.y, dry_run)
    if failed == 'dry' then
        return {ok = false, error = ('the game would not place a stockpile at x%d y%d'):format(r.x, r.y)}
    elseif not good then
        return {ok = false, error = ('the game refused the stockpile at x%d y%d'):format(r.x, r.y)}
    end
    local out = {ok = true, kind = kind, what = f.what, x = r.x, y = r.y, elevation = ez(r.z), size = r.w,
                 dry_run = dry_run or nil}
    if dry_run then return out end
    -- (0.105.40b, M6) the kitchen's and still's food pile is the AI's own (its barrels set)
    if f.flag == 'food' then pcall(function() reqscript('ai-food-store').remember(r.x, r.y, r.z) end) end
    -- (0.105.41, item 2) every feeder booked as the AI's own, with its workshop (ai-pile-links)
    pcall(function() reqscript('ai-pile-links').remember_feeder(r.x, r.y, r.z, b.id, kind, f.flag) end)
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
        if qf_try('build', {{x = 0, y = 0, text = f.key}}, area.z, sp.x, sp.y, dry_run) then
            return {ok = true, zone_id = zone_id, what = f.what, x = sp.x, y = sp.y, elevation = ez(area.z),
                    dry_run = dry_run or nil}
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
                if qf_try('build', {{x = 0, y = 0, text = 'c'}}, z, best.x, best.y, dry_run) then
                    chairs[key(best.x, best.y)] = {x = best.x, y = best.y}
                    placed = placed + 1
                    table.insert(spots, {best.x, best.y})
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
            if not (item_held(it) or it.flags.in_job) and it.engraving_type == df.slab_engraving_type.Memorial then
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
    local good, failed, res = qf_try('zone', cell, best.z, best.x1, best.y1, dry_run)
    local words = type(res) == 'string' and res or 'no tiles'
    if failed == 'dry' then
        return {ok = false, rejected = true, error = 'quickfort refused the zone over the dining hall: ' .. words}
    elseif not good then
        return {ok = false, error = 'quickfort did not make the zone: ' .. words}
    end
    return {ok = true, kind = kind, x = best.x1, y = best.y1, elevation = ez(best.z), w = w, h = h, dry_run = dry_run or nil}
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
    -- (13c) counted over all, but described (buildingplan's words, its
    -- queue, suspendmanager's why: the costly part) only for the PLANNED_MAX kept
    local found, by_type, n = {}, {}, 0
    for _, b in ipairs(df.global.world.buildings.all) do
        local okp, planned = pcall(bp.isPlannedBuilding, b)
        if okp and planned then
            n = n + 1
            local kind = df.building_type[b:getType()] or tostring(b:getType())
            by_type[kind] = (by_type[kind] or 0) + 1
            table.insert(found, {b = b, id = b.id, kind = kind})
        end
    end
    table.sort(found, function(a, c) return a.id < c.id end)          -- older buildings first
    local list = {}
    for i = 1, math.min(PLANNED_MAX, #found) do
        local b = found[i].b
        local r = {id = b.id, kind = found[i].kind, x = b.centerx, y = b.centery, z = b.z, elevation = ez(b.z)}
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
            for k = 0, (okc and cnt or 0) - 1 do
                local okd, d = pcall(bp.getDescString, b, k)
                local okq, q = pcall(bp.getQueuePosition, b, k)
                table.insert(items, {want = okd and tostring(d):sub(1, 80) or nil, queue = okq and q or nil})
            end
            if #items > 0 then r.items = items end
        end
        list[i] = r
    end
    return {n = n, list = list, by_type = by_type}
end
