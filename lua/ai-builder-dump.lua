-- ai-builder-dump: the garbage dump (0.105.27 disposal): the zone above ground or in a
-- small room dug for it.
--
-- A part of ai-builder, not a script of its own (r8, split out of
-- ai-builder-surface.lua when it was 126 KB): ai-builder.lua loads it into its
-- own environment right after ai-builder-wagonroad, so every name here is
-- reqscript('ai-builder').name and the helpers defined there (info,
-- quickfort_apply, ...) are in reach.

if not PARTS then qerror('ai-builder-dump is a part of ai-builder; run ai-builder') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-dump'] = '0.105.99'   -- bumped with BRIDGE_VERSION

local info, ez = info, ez

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
