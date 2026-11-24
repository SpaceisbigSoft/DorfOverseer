-- ai-layouts-kinds: the levels themselves: the hub round the stair, the rooms
-- off it (corridors, cross and ring arms), every kind (bedrooms, suites, jail,
-- dining, storage, workshops, temple, ... farms), make(), tiles_from_dig()
-- and to_data().
--
-- (r9) A part of ai-layouts, not a script of its own: ai-layouts.lua loads it
-- into its own environment, so every name here is reqscript('ai-layouts').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-layouts-kinds is a part of ai-layouts; run ai-layouts') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-layouts-kinds'] = '0.105.101'   -- (0.105.26) bumped with BRIDGE_VERSION

local clamp, new_layout, dig_rect, dig_rect_except, mark, corners_of, add, rot_rect, virtual_slot, hall_open, own_pillar, hall_statues, hall_close, finish = PART_LOCALS.clamp, PART_LOCALS.new_layout, PART_LOCALS.dig_rect, PART_LOCALS.dig_rect_except, PART_LOCALS.mark, PART_LOCALS.corners_of, PART_LOCALS.add, PART_LOCALS.rot_rect, PART_LOCALS.virtual_slot, PART_LOCALS.hall_open, PART_LOCALS.own_pillar, PART_LOCALS.hall_statues, PART_LOCALS.hall_close, PART_LOCALS.finish   -- (r9) the hub's and earlier parts' locals

-- The 3x3 hub around the stair (the stair tile itself is left alone).
local function hub(L)
    for dx = -1, 1 do
        for dy = -1, 1 do
            if dx ~= 0 or dy ~= 0 then dig_rect(L, dx, dy, 1, 1) end
        end
    end
end

-- Corridors east and west of the hub with square rooms on both sides.
-- Returns room slots in order: east-north, east-south, west-north, west-south,
-- then the next column out. Each slot: {x, y, size, door = {x, y}, side}
-- where (x, y) is the room's top-left tile and side is the corridor side
-- ('N' rooms open south onto the corridor, 'S' rooms open north).
-- Spacing (the fort's trait) +50 or more: two tiles of rock between rooms.
function room_wall(L)
    return (L.style.spacing or 0) >= 50 and 2 or 1
end

-- (0.104.107, the 38-year soak: 1-wide halls jammed a fort of 300) How wide
-- each kind's corridor is: storage and workshops carry the hauling, 3 (the
-- hub's own width); every other kind 2. Rooms there open 3 wide (size 5+)
-- so haulers pass each other in the doorway.
CORRIDOR_WIDTH = {storage = 3, workshops = 3}
CORRIDOR_DEFAULT = 2
WIDE_OPENINGS = {storage = true, workshops = true}

function corridor_width(kind)
    return CORRIDOR_WIDTH[kind] or CORRIDOR_DEFAULT
end

local function corridor_rooms(L, nslots, size, round)
    hub(L)
    local width = corridor_width(L.kind)
    -- the corridor's rows: 3 wide is the hub's -1..1; 2 wide is 0..1
    local top = width == 3 and -1 or 0
    local bottom = top + width - 1
    local opening = (WIDE_OPENINGS[L.kind] and size >= 5) and 3 or 1
    local columns = math.max(1, math.ceil(nslots / 4))
    local slots = {}
    local reach = 0
    local wall = room_wall(L)
    for col = 0, columns - 1 do
        local x0 = 3 + col * (size + wall)       -- east rooms: x0 .. x0+size-1
        local door_dx = (size - 1) // 2
        local candidates = {
            {east = true, side = 'N'}, {east = true, side = 'S'},
            {east = false, side = 'N'}, {east = false, side = 'S'},
        }
        for _, c in ipairs(candidates) do
            if #slots >= nslots then break end
            local rx = c.east and x0 or -(x0 + size - 1)
            local ry = c.side == 'N' and (top - 1 - size) or (bottom + 2)
            local door_x = c.east and (x0 + door_dx) or -(x0 + door_dx)
            local door_y = c.side == 'N' and (top - 1) or (bottom + 1)
            table.insert(slots, {x = rx, y = ry, size = size, side = c.side,
                                 door = {x = door_x, y = door_y}, opening = opening})
            reach = math.max(reach, x0 + size - 1)
        end
    end
    -- corridors run the full length of the room columns on both sides
    dig_rect(L, 2, top, reach - 1, width)
    dig_rect(L, -reach, top, reach - 1, width)
    for _, s in ipairs(slots) do
        if round then
            dig_rect_except(L, s.x, s.y, s.size, s.size, corners_of(s.x, s.y, s.size, s.size))
        else
            dig_rect(L, s.x, s.y, s.size, s.size)
        end
        local half = (s.opening - 1) // 2
        dig_rect(L, s.door.x - half, s.door.y, s.opening, 1)
    end
    L.corridor = {width = width, top = top}
    return slots
end

-- (D0 G4) The design language's arms: rooms off the hub in a cross (four
-- arms) or round a ring (a loop corridor, four spokes from the hub). Both
-- return slot records exactly like corridor_rooms'; the kinds furnish them
-- unchanged (virtual_slot, realize). The corridor widths (CORRIDOR_WIDTH)
-- and the wide openings (WIDE_OPENINGS) are kept; the stair tile is never dug.
local function dig_turned(L, q, x, y, w, h, round)
    local nx, ny, nw, nh = rot_rect(q, x, y, w, h)
    if round then
        dig_rect_except(L, nx, ny, nw, nh, corners_of(nx, ny, nw, nh))
    else
        dig_rect(L, nx, ny, nw, nh)
    end
    return {x = nx, y = ny, w = nw, h = nh}
end

local function grand_ways(L, rects)
    if not L.style.grand then return end
    L.engrave_all = true
    for _, r in ipairs(rects) do table.insert(L.halls, r) end
end

-- Four arms: corridor_rooms' east arm, turned to the south, west and north.
-- Each arm's rooms start one room out, clear of the next arm's rooms.
local function cross_rooms(L, nslots, size, round)
    hub(L)
    local width = corridor_width(L.kind)
    local top = width == 3 and -1 or 0
    local bottom = top + width - 1
    local opening = (WIDE_OPENINGS[L.kind] and size >= 5) and 3 or 1
    local wall = room_wall(L)
    local first = size + 3 - top + (wall - 1)
    local door_dx = (size - 1) // 2
    local slots, reach, rooms = {}, {0, 0, 0, 0}, {}
    local col = 0
    while #slots < nslots do
        local x0 = first + col * (size + wall)
        for q = 0, 3 do
            for _, side in ipairs({'N', 'S'}) do
                if #slots < nslots then
                    local s = {x = x0, y = side == 'N' and (top - 1 - size) or (bottom + 2), size = size,
                               side = side, opening = opening,
                               door = {x = x0 + door_dx, y = side == 'N' and (top - 1) or (bottom + 1)}}
                    table.insert(rooms, {q = q, x = s.x, y = s.y, door = s.door})
                    table.insert(slots, virtual_slot(L, q, s))
                    reach[q + 1] = math.max(reach[q + 1], x0 + size - 1)
                end
            end
        end
        col = col + 1
    end
    local ways = {}
    for q = 0, 3 do
        if reach[q + 1] > 0 then table.insert(ways, dig_turned(L, q, 2, top, reach[q + 1] - 1, width)) end
    end
    local half = (opening - 1) // 2
    for _, r in ipairs(rooms) do
        dig_turned(L, r.q, r.x, r.y, size, size, round)
        dig_turned(L, r.q, r.door.x - half, r.door.y, opening, 1)
    end
    grand_ways(L, ways)
    L.corridor = {width = width, top = top, arms = 'cross'}
    return slots
end

-- A ring: a square loop corridor `ring` tiles out from the stair, spokes
-- from the hub along the four axes, and rooms outside the loop opening onto
-- it, none across an axis (where a corridor from the fort comes in). Laid
-- out on the north side and turned to the east, south and west.
local function ring_rooms(L, nslots, size, round)
    hub(L)
    local width = corridor_width(L.kind)
    local top = width == 3 and -1 or 0
    local bottom = top + width - 1
    local opening = (WIDE_OPENINGS[L.kind] and size >= 5) and 3 or 1
    local wall = room_wall(L)
    local pitch = size + wall
    -- (0.105.54, layout A) the loop sized from the room count: the fewest
    -- rooms per half side (8 a round: two on each side, one either side of
    -- the axis) and the smallest loop whose side holds them, rooms starting
    -- 3 tiles off the axis: x 3 .. 3 + per_half * pitch - wall - 1 <= the
    -- side's last tile (ring + width - 2)
    local per_half = math.max(1, (nslots + 7) // 8)
    local ring = math.max(3, per_half * pitch - wall + 4 - width)
    local outer = -(ring + width - 1)          -- the loop's outer row on the north side
    local ry, door_y = outer - 1 - size, outer - 1
    local door_dx = (size - 1) // 2
    local slots, rooms = {}, {}
    -- (0.105.54) spread round the loop: one room on each side before a
    -- second on any (4 rooms: one a side, not two sides of two)
    for k = 0, per_half - 1 do
        local right = 3 + k * pitch
        for _, rx in ipairs({right, -(right + size - 1)}) do
            for q = 0, 3 do
                if #slots < nslots then
                    local s = {x = rx, y = ry, size = size, side = 'N', opening = opening,
                               door = {x = rx + door_dx, y = door_y}}
                    table.insert(rooms, {q = q, x = s.x, y = s.y, door = s.door})
                    table.insert(slots, virtual_slot(L, q, s))
                end
            end
        end
    end
    local ways = {}
    for q = 0, 3 do
        table.insert(ways, dig_turned(L, q, top, -(ring - 1), width, ring - 2))            -- the spoke
        table.insert(ways, dig_turned(L, q, outer, outer, 2 * ring + width - 1, width))    -- the loop's side
    end
    local half = (opening - 1) // 2
    for _, r in ipairs(rooms) do
        dig_turned(L, r.q, r.x, r.y, size, size, round)
        dig_turned(L, r.q, r.door.x - half, r.door.y, opening, 1)
    end
    grand_ways(L, ways)
    L.corridor = {width = width, top = top, arms = 'ring', ring = ring}
    return slots
end

-- (0.105.54, layout A) A ring only for a big level: under RING_MIN_ROOMS
-- rooms a loop round the stair is mostly corridor (one workshop had a 17x17
-- loop, ~250 tiles, four squares of rock between): such a level is laid out
-- like the corridor style's. The culture's ring stays for halls and homes
-- with many rooms. BIG_LEVEL_ROOMS: from this many rooms a hall style may
-- round a workshop's corners (workshops).
RING_MIN_ROOMS = 4
BIG_LEVEL_ROOMS = 4

-- The rooms of a room level, arranged as the style's arms say.
local function rooms_for(L, nslots, size, round)
    if L.style.arms == 'cross' then return cross_rooms(L, nslots, size, round) end
    -- (0.105.54 merge) workshop levels never ring: rooms along a corridor
    -- (the player: halls with rooms along them), and a level keeps its shape
    -- as it grows (a ring re-laid at 4 rooms would move every room dug)
    if L.style.arms == 'ring' and nslots >= RING_MIN_ROOMS and not L.no_ring then return ring_rooms(L, nslots, size, round) end
    local slots = corridor_rooms(L, nslots, size, round)
    if L.style.grand then
        local width, top = L.corridor.width, L.corridor.top
        local reach = 0
        for _, s in ipairs(slots) do reach = math.max(reach, math.abs(s.x), math.abs(s.x + s.size - 1)) end
        grand_ways(L, {{x = 2, y = top, w = reach - 1, h = width}, {x = -reach, y = top, w = reach - 1, h = width}})
    end
    return slots
end

-- Corner tiles of a room, named from the corridor's point of view.
local function corners(s)
    local far_y = s.side == 'N' and s.y or (s.y + s.size - 1)       -- row away from the door
    local near_y = s.side == 'N' and (s.y + s.size - 1) or s.y
    local step = s.side == 'N' and 1 or -1                           -- towards the door
    return far_y, near_y, step
end

-- bedrooms{rooms = 1-32, room_size = 2-4}
function bedrooms(p)
    local rooms = clamp(p.rooms, 1, 32)
    local size = clamp(p.room_size, 2, 4)
    local L = new_layout('bedrooms', p)
    local slots = rooms_for(L, rooms, size)
    for _, s in ipairs(slots) do
        local far_y, _, step = corners(s)
        local left, right = s.x, s.x + s.size - 1
        add(L, 'build', s.door.x, s.door.y, 'd', 'Door')
        -- bed in the far corner, away from the door column
        local bed_x = (s.door.x - left <= right - s.door.x) and right or left
        add(L, 'build', bed_x, far_y, 'b', 'Bed')
        if size >= 3 then
            local other_x = bed_x == left and right or left
            add(L, 'build', other_x, far_y, 'f', 'Cabinet')
            add(L, 'build', other_x, far_y + step, 'h', 'Box')
        end
        add(L, 'zone', s.x, s.y, ('b(%dx%d)'):format(s.size, s.size))
    end
    L.summary = {rooms = #slots, room_size = size, beds = #slots}
    return finish(L)
end

-- suites{suites = 1-8}: rooms for the fort's nobles, a pair each: a bedroom
-- (bed, cabinet, chest, statue) and an office (chair and table, statue),
-- 4x4, doors, and their zones; the nobles are given them by the AI.
function suites(p)
    local n = clamp(p.suites, 1, 8)
    local size = 4
    local L = new_layout('suites', p)
    local slots = rooms_for(L, n * 2, size)
    local beds, offices = 0, 0
    for i, s in ipairs(slots) do
        local far_y, _, step = corners(s)
        local left, right = s.x, s.x + s.size - 1
        add(L, 'build', s.door.x, s.door.y, 'd', 'Door')
        local a_x = (s.door.x - left <= right - s.door.x) and right or left
        local b_x = a_x == left and right or left
        if i % 2 == 1 then
            add(L, 'build', a_x, far_y, 'b', 'Bed')
            add(L, 'build', b_x, far_y, 'f', 'Cabinet')
            add(L, 'build', b_x, far_y + step, 'h', 'Box')
            add(L, 'build', a_x, far_y + 2 * step, 's', 'Statue')
            add(L, 'zone', s.x, s.y, ('b(%dx%d)'):format(s.size, s.size))
            beds = beds + 1
        else
            add(L, 'build', a_x, far_y, 'c', 'Chair')
            add(L, 'build', a_x, far_y + step, 't', 'Table')
            add(L, 'build', b_x, far_y, 's', 'Statue')
            add(L, 'zone', s.x, s.y, ('o(%dx%d)'):format(s.size, s.size))
            offices = offices + 1
        end
    end
    L.summary = {suites = math.min(beds, offices), beds = beds, offices = offices}
    return finish(L)
end

-- jail{cells = 1-8}: 3x3 cells off a corridor, each with a door, a
-- restraint (a rope or chain: a prisoner is chained to it) and its own
-- dungeon zone. The sheriff or captain of the guard puts convicts there; a
-- fort without a jail punishes by beating, or not at all.
function jail(p)
    local n = clamp(p.cells, 1, 8)
    local L = new_layout('jail', p)
    local slots = rooms_for(L, n, 3)
    for _, s in ipairs(slots) do
        local far_y = corners(s)
        add(L, 'build', s.door.x, s.door.y, 'd', 'Door')
        add(L, 'build', s.x + 1, far_y, 'v', 'Chain')
        add(L, 'zone', s.x, s.y, 'j(3x3)')
    end
    L.summary = {cells = #slots, restraints = #slots}
    return finish(L)
end

-- dining{tables = 4-90}
function dining(p)
    local tables = clamp(p.tables, 4, 90)
    local L = new_layout('dining', p)
    hub(L)
    -- Hall east of the hub, 11 tall: three rows of table+chair pairs.
    local cols = math.min(30, math.ceil(tables / 3))
    local width = 2 * cols + 2
    -- (D0 G4) the hall as the style shapes and sizes it (hall_open); the tables
    -- keep their rows, centred in it
    local H = hall_open(L, 2, -5, width, 11, L.style.hall)
    if L.style.hall == 'pillared' then
        -- pillars on the two walkways between table rows, every `rhythm` tiles
        for x = 4, H.x + H.w - 3, L.style.rhythm do own_pillar(H, x, -2); own_pillar(H, x, 1) end
    end
    -- statues along the free row at the far side
    local spots = {}
    for x = 4, 2 + width - 3, 4 do table.insert(spots, {x = x, y = H.y + H.h - 1}) end
    local placed_statues = hall_statues(L, H, L.style.statues, spots)
    local placed = 0
    for col = 0, cols - 1 do
        for _, ty in ipairs({-4, -1, 2}) do
            if placed < tables then
                local x = 3 + 2 * col
                add(L, 'build', x, ty, 't', 'Table')
                add(L, 'build', x, ty + 1, 'c', 'Chair')
                placed = placed + 1
            end
        end
    end
    hall_close(L, H)
    add(L, 'zone', H.x, H.y, ('h(%dx%d)'):format(H.w, H.h))
    L.summary = {tables = placed, chairs = placed, statues = placed_statues, hall = L.style.hall}
    return finish(L)
end

-- storage{piles = {'food', 'stone', ...}, room_size = 5-11}
function storage(p)
    local piles = {}
    for _, name in ipairs(type(p.piles) == 'table' and p.piles or {}) do
        if STOCKPILES[name] and #piles < 12 then table.insert(piles, name) end
    end
    if #piles == 0 then return nil, 'no valid stockpile types' end
    local size = clamp(p.room_size, 5, 11)
    local L = new_layout('storage', p)
    local slots = rooms_for(L, #piles, size, L.style.hall ~= 'plain')
    for i, s in ipairs(slots) do
        add(L, 'place', s.x, s.y, ('%s(%dx%d)'):format(STOCKPILES[piles[i]], s.size, s.size))
    end
    L.summary = {stockpiles = piles, room_size = size}
    return finish(L)
end

-- workshops{shops = {'Still', 'Kitchen', ...}} (5x5 rooms, workshop centred)
-- (0.105.54, layout A part 2) spare = n: n rooms more, dug but left empty
-- (after the shops and the ore pile), each a free slot a later workshop is
-- put in (ai-builder-projects join_workshop_level); spare_for names the
-- shops they are planned for (in order; a slot without a name is free for
-- any). L.rooms_at lists every room by its centre tile: text 'shop:<name>',
-- 'pile' or 'free' / 'free:<name>', turned with the level. 12 rooms at most.
WORKSHOP_ROOMS_MAX = 12
function workshops(p)
    local shops = {}
    for _, name in ipairs(type(p.shops) == 'table' and p.shops or {}) do
        if WORKSHOPS[name] and #shops < WORKSHOP_ROOMS_MAX then table.insert(shops, name) end
    end
    if #shops == 0 then return nil, 'no valid workshop types' end
    local L = new_layout('workshops', p)
    L.no_ring = true          -- (0.105.54 merge) see rooms_for
    -- (0.105.29, custom ore_piles) one room more, a 5x5 stone (and ore) pile, under 12 shops
    local ore = L.style.customs.ore_piles and #shops < WORKSHOP_ROOMS_MAX
    local spare = clamp(p.spare or 0, 0, WORKSHOP_ROOMS_MAX - #shops - (ore and 1 or 0))
    local planned = {}
    for _, name in ipairs(type(p.spare_for) == 'table' and p.spare_for or {}) do
        if WORKSHOPS[name] and #planned < spare then table.insert(planned, name) end
    end
    -- (0.105.54, layout A) square rooms opening 3 wide onto the corridor; a
    -- hall style rounds their corners only on a big level (BIG_LEVEL_ROOMS)
    local n = #shops + (ore and 1 or 0) + spare
    local slots = rooms_for(L, n, 5, L.style.hall ~= 'plain' and n >= BIG_LEVEL_ROOMS)
    for i, s in ipairs(slots) do
        local cx, cy = s.x + 2, s.y + 2
        if shops[i] then
            add(L, 'build', cx, cy, WORKSHOPS[shops[i]], shops[i])
            add(L, 'rooms_at', cx, cy, 'shop:' .. shops[i])
        elseif ore and i == #shops + 1 then
            add(L, 'place', s.x, s.y, ('%s(5x5)'):format(STOCKPILES.stone))
            add(L, 'rooms_at', cx, cy, 'pile')
        else
            local k = i - #shops - (ore and 1 or 0)
            add(L, 'rooms_at', cx, cy, planned[k] and ('free:' .. planned[k]) or 'free')
        end
    end
    L.summary = {workshops = shops, ore_pile = ore or nil, free_rooms = spare > 0 and spare or nil}
    return finish(L)
end

-- temple{size = 'shrine' | 'grand'}: a hall east of the hub with statues and
-- a temple zone (open to all gods).
function temple(p)
    local grand = p.size == 'grand'
    local L = new_layout('temple', p)
    hub(L)
    local bw, bh = grand and 15 or 7, grand and 11 or 7
    -- (D0 G4) the hall as the style shapes and sizes it; a grand temple's is
    -- at least rounded
    local shape = L.style.hall
    if shape == 'plain' and grand then shape = 'rounded' end
    local H = hall_open(L, 2, -(bh // 2), bw, bh, shape)
    local w, h, top = H.w, H.h, H.y
    local cloister = L.style.customs.cloister
    if cloister then
        -- (0.105.29, custom cloister) a pillared walk 1 tile in from the walls:
        -- pillars on the second and second-last rows and the west column (not
        -- the doorway row); the statue column (2+w-2) stays clear. In a grand
        -- temple the ring takes the place of its own two pillar rows. The rows
        -- start at x = 5, one clear of the west column's pillar at x = 3 (from
        -- 4 the corners read as 2-tile pillars).
        H.cloister = true
        for x = 5, 2 + w - 3, 2 do
            own_pillar(H, x, top + 1); own_pillar(H, x, top + h - 2)
        end
        for y = top + 1, top + h - 2, 2 do
            if math.abs(y) > 1 then own_pillar(H, 3, y) end
        end
    elseif grand then
        for x = 5, 2 + w - 4, L.style.rhythm do
            own_pillar(H, x, top + 2); own_pillar(H, x, top + h - 3)
        end
    end
    -- statues along the far (east) wall, centre first, then outwards (as
    -- many as the kind's own size has room for)
    local n = (grand and 2 or 1) + (grand and L.style.statues or L.style.statues // 2)
    local ex = 2 + w - 2
    local btop = -(bh // 2)
    local spots = {}
    for _, dy in ipairs({0, -2, 2, -4, 4, -1, 1, -3, 3}) do
        if dy > btop and dy < btop + bh - 1 then table.insert(spots, {x = ex, y = dy}) end
    end
    local placed = hall_statues(L, H, n, spots)
    hall_close(L, H)
    -- (0.89) a guildhall asked for by a petition: the same hall, for a profession
    -- (quickfort sets it); a temple's deity is set once the zone stands
    local prof = type(p.profession) == 'string' and p.profession:match('^[%u_]+$') and p.profession:lower() or nil
    local loc = prof and ('location=guildhall profession=' .. prof) or 'location=temple'
    add(L, 'zone', 2, top, ('m{%s}(%dx%d)'):format(loc, w, h))
    -- one asked for by a petition must reach its value (2000 for a temple or
    -- guildhall): every wall and floor of the hall engraved
    if p.deity_hf or p.religion or prof then L.engrave_all = true end
    L.summary = {temple = grand and 'grand' or 'shrine', statues = placed, guildhall = prof,
                 deity_hf = p.deity_hf, religion = p.religion, cloister = cloister or nil}
    return finish(L)
end

-- memorial{name = 'Shulmik the Jackalowls'}: a round 9x9 hall with a
-- central statue, always smoothed and engraved, named for the slain beast.
function memorial(p)
    local name = tostring(p.name or '')
    if not name:match("^[A-Za-z' ]+$") or #name > 40 then
        return nil, 'memorial needs a plain name (letters, spaces, apostrophes; up to 40)'
    end
    local L = new_layout('memorial', p)
    L.engrave_all = true
    hub(L)
    -- (D0 G4) round (today's corners) unless the style gives a new shape
    local H = hall_open(L, 2, -4, 9, 9, OLD_HALLS[L.style.hall] and 'rounded' or L.style.hall)
    local cx = H.x + H.w // 2
    local spots = {{x = cx, y = 0}}
    for _, d in ipairs({{-2, -2}, {2, 2}, {2, -2}, {-2, 2}}) do table.insert(spots, {x = cx + d[1], y = d[2]}) end
    local n = hall_statues(L, H, 1 + math.min(4, L.style.statues), spots)
    hall_close(L, H)
    add(L, 'zone', H.x, H.y, ('m{name="Hall of %s"}(%dx%d)'):format(name, H.w, H.h))
    L.summary = {memorial = name, statues = n}
    return finish(L)
end

-- garden{name}: a set piece for good times: a great 13x9 hall of statues in
-- rows (every other tile), a table and chairs at its heart, always smoothed
-- and engraved, and a meeting area named for it ("The <name> Garden").
function garden(p)
    local name = tostring(p.name or '')
    if not name:match("^[A-Za-z' ]+$") or #name > 40 then
        return nil, 'garden needs a plain name (letters, spaces, apostrophes; up to 40)'
    end
    local L = new_layout('garden', p)
    L.engrave_all = true
    hub(L)
    -- (D0 G4) rounded corners unless the style gives a new shape
    local H = hall_open(L, 2, -4, 13, 9, OLD_HALLS[L.style.hall] and 'rounded' or L.style.hall)
    local cx = H.x + H.w // 2
    local spots = {}
    for x = cx - 4, cx + 4, 2 do
        for _, y in ipairs({-2, 2}) do table.insert(spots, {x = x, y = y}) end
    end
    local statues = hall_statues(L, H, #spots, spots)
    add(L, 'build', cx, 0, 't', 'Table')
    add(L, 'build', cx - 1, 0, 'c', 'Chair')
    add(L, 'build', cx + 1, 0, 'c', 'Chair')
    hall_close(L, H)
    add(L, 'zone', H.x, H.y, ('m{name="The %s Garden"}(%dx%d)'):format(name, H.w, H.h))
    L.summary = {garden = name, statues = statues}
    return finish(L)
end

-- (0.105.47) garden_court{r, statues, paths}: the Garden fort's walled court
-- above ground (built by ai-builder-court on the open ground by the fields,
-- not dug: no stair, no dig cells). Centred on (0, 0); the ring of walls at
-- radius r (4-6), its inside the (2r-1) square. DF 53 has no job to plant a
-- tree or a shrub, so the court's green is what DF allows: four beds (farm
-- plots of above-ground crops, 'p(WxH)') in the quarters, the trees already
-- standing inside left as they are, and the soil and grass between. A cross
-- of paths (block floors, 'Cf', with paths = true) from each side's middle
-- to the heart; statues round the heart (up to `statues`, the ones lying
-- free); seats (chairs: DF has no bench) against the walls where the walks
-- meet them. DF has no fountain either: the heart is left open (a well
-- wants water under it). Returns {kind, r, inside = {x1, y1, x2, y2},
-- ring, paths, beds = {{x, y, w, h}}, statues, seats, heart, summary}.
GARDEN_COURT_RADII = {min = 4, max = 6}
function garden_court(p)
    p = type(p) == 'table' and p or {}
    local r = clamp(p.r, GARDEN_COURT_RADII.min, GARDEN_COURT_RADII.max)
    local q = r - 1                       -- the inside reaches -q .. q
    local L = {kind = 'garden_court', r = r, inside = {x1 = -q, y1 = -q, x2 = q, y2 = q},
               ring = {}, paths = {}, beds = {}, statues = {}, seats = {}, heart = {x = 0, y = 0}}
    for x = -r, r do
        table.insert(L.ring, {x = x, y = -r})
        table.insert(L.ring, {x = x, y = r})
    end
    for y = -r + 1, r - 1 do
        table.insert(L.ring, {x = -r, y = y})
        table.insert(L.ring, {x = r, y = y})
    end
    if p.paths == true then
        for i = -q, q do
            table.insert(L.paths, {x = i, y = 0})
            if i ~= 0 then table.insert(L.paths, {x = 0, y = i}) end
        end
    end
    -- the beds: each quarter from 2 out to the wall (a walk of one tile
    -- between the bed and the path)
    local n = q - 1
    if n >= 2 then
        for _, s in ipairs({{-1, -1}, {1, -1}, {-1, 1}, {1, 1}}) do
            local x1 = s[1] < 0 and -q or 2
            local y1 = s[2] < 0 and -q or 2
            table.insert(L.beds, {x = x1, y = y1, w = n, h = n})
        end
    end
    -- statues round the heart (the corners of the crossing), as many as free
    local want = clamp(p.statues, 0, 4)
    for i, c in ipairs({{-1, -1}, {1, 1}, {1, -1}, {-1, 1}}) do
        if i <= want then table.insert(L.statues, {x = c[1], y = c[2]}) end
    end
    -- seats where the walks between path and bed meet the walls
    for _, c in ipairs({{-1, -q}, {1, -q}, {-1, q}, {1, q}}) do table.insert(L.seats, {x = c[1], y = c[2]}) end
    if q >= 4 then
        for _, c in ipairs({{-q, -1}, {-q, 1}, {q, -1}, {q, 1}}) do table.insert(L.seats, {x = c[1], y = c[2]}) end
    end
    L.summary = {garden_court = true, r = r, beds = #L.beds, bed_tiles = #L.beds * n * n, statues = #L.statues,
                 seats = #L.seats, paths = #L.paths}
    return L
end

-- The rows along a hall's long walls: (D0 G4) in a new shape, one row in
-- from them, so the shape's cut has room.
local function wall_rows(H)
    local ry = (H.h - 1) // 2 - (OLD_HALLS[H.shape] and 0 or 1)
    return {-ry, ry}
end

-- A hall east of the hub with beds along both long walls (odd x), for the
-- hospital and the barracks. Returns the number placed, the hall's far
-- column, its width and the hall (H: x, y, w, h). far_items(far) adds what
-- stands at the far end, before the hall is dug (D0 G4: so its shape keeps them).
local function bed_hall(L, beds, extra_on_wall, key, ftype, each, far_items)
    hub(L)
    local per_row = math.ceil(beds / 2)
    local width = 2 * per_row + 3
    local H = hall_open(L, 2, -3, width, 7, L.style.hall)
    local placed = 0
    for i = 0, per_row - 1 do
        for _, y in ipairs(wall_rows(H)) do
            if placed < beds then
                local x = 3 + 2 * i
                add(L, 'build', x, y, key or 'b', ftype or 'Bed')
                if extra_on_wall then
                    -- beds get their extra beside them; other things (key given)
                    -- get it at their own spot, the callback decides where
                    if key then extra_on_wall(x, y) else extra_on_wall(x + 1, y) end
                end
                if each then each(x, y) end
                placed = placed + 1
            end
        end
    end
    local far = H.x + H.w - 1
    if far_items then far_items(far) end
    hall_close(L, H)
    return placed, far, H.w, H
end

-- hospital{beds = 4-20}: beds, plus tables and chests for supplies at the far
-- end, and a hospital zone.
function hospital(p)
    local L = new_layout('hospital', p)
    local beds, _, width, H = bed_hall(L, clamp(p.beds, 4, 20), nil, nil, nil, nil, function(far)
        add(L, 'build', far, 0, 't', 'Table')
        add(L, 'build', far, -1, 'h', 'Box')
        add(L, 'build', far, 1, 'h', 'Box')
    end)
    add(L, 'zone', 2, H.y, ('m{location=hospital}(%dx%d)'):format(width, H.h))
    L.summary = {hospital_beds = beds}
    return finish(L)
end

-- barracks{beds = 4-20}: beds with an armor stand beside each, weapon racks at
-- the far end, and a barracks zone (squads are assigned in the game).
function barracks(p)
    local L = new_layout('barracks', p)
    local stands = 0
    local beds, far, width, H = bed_hall(L, clamp(p.beds, 4, 20), function(x, y)
        add(L, 'build', x, y, 'a', 'Armorstand')
        stands = stands + 1
    end, nil, nil, nil, function(f)
        add(L, 'build', f, -1, 'r', 'Weaponrack')
        add(L, 'build', f, 1, 'r', 'Weaponrack')
    end)
    add(L, 'zone', 2, H.y, ('B(%dx%d)'):format(width, H.h))
    local armoury = L.style.customs.armoury
    if armoury then
        -- (0.105.29, custom armoury) a 2x5 alcove past the racks: a weapon pile
        -- north, an armour pile south, the middle row (y = 0) open
        dig_rect(L, far + 1, -2, 2, 5)
        add(L, 'place', far + 1, -2, ('%s(2x2)'):format(STOCKPILES.weapons))
        add(L, 'place', far + 1, 1, ('%s(2x2)'):format(STOCKPILES.armor))
    end
    L.summary = {barracks_beds = beds, armor_stands = stands, armoury = armoury or nil}
    return finish(L)
end

-- archery{lanes = 1-3, length = 8-16}: a range running east from the hub,
-- one archery target a lane at the far end, and an archery range zone at the
-- near end where the crossbow soldiers stand, shooting east at the targets.
function archery(p)
    local L = new_layout('archery', p)
    hub(L)
    local lanes, len = clamp(p.lanes or 2, 1, 3), clamp(p.length or 12, 8, 16)
    local h, y0 = 2 * lanes + 1, -lanes
    dig_rect(L, 2, y0, len, h)
    table.insert(L.halls, {x = 2, y = y0, w = len, h = h})
    for i = 0, lanes - 1 do add(L, 'build', 2 + len - 1, y0 + 1 + 2 * i, 'A') end
    add(L, 'zone', 2, y0, ('a{shoot_from=west}(2x%d)'):format(h))
    L.summary = {archery_targets = lanes, range_length = len}
    return finish(L)
end

-- (D0 G4) tombs with cross or ring arms: crypts, 3x3 rooms off the arms,
-- three coffins along each one's far wall, each in its own tomb zone.
local function crypts(L, coffins)
    local slots = rooms_for(L, (coffins + 2) // 3, 3)
    local n = 0
    for _, s in ipairs(slots) do
        local far_y = corners(s)
        for dx = 0, 2 do
            if n < coffins then
                add(L, 'build', s.x + dx, far_y, 'n', 'Coffin')
                add(L, 'zone', s.x + dx, far_y, 'T{citizens=true}')
                n = n + 1
            end
        end
    end
    L.summary = {coffins = n}
    return finish(L)
end

-- tombs{coffins = 4-30}: coffins along both walls, each in its own 1x1 tomb
-- zone, so every coffin can take one burial.
function tombs(p)
    local L = new_layout('tombs', p)
    if L.style.arms ~= 'corridor' then return crypts(L, clamp(p.coffins, 4, 30)) end
    local n = bed_hall(L, clamp(p.coffins, 4, 30), nil, 'n', 'Coffin',
                       -- (0.104.17) automatic burial of citizens asked for outright:
                       -- Enxah's tombs stood free with it off while 104 lay unburied
                       function(x, y) add(L, 'zone', x, y, 'T{citizens=true}') end)
    L.summary = {coffins = n}
    return finish(L)
end

-- tavern{tables = 4-20}: along both walls, tables in pairs with their chairs
-- side by side between them (table, chair, chair, table): (0.104.76) dwarves
-- talk only with those beside them, not on a diagonal, so the old layout (a
-- chair on the inner side of each table, two tiles apart) sat no one next to
-- anyone (Enxah: 42 badly wanting friends with a proper tavern). The middle
-- stays open floor to stand and dance on; chests for mugs at the far end, and
-- a tavern zone.
function tavern(p)
    local L = new_layout('tavern', p)
    local tables = clamp(p.tables, 4, 20)
    hub(L)
    local per_row = math.ceil(tables / 2)
    local groups = math.ceil(per_row / 2)
    local H = hall_open(L, 2, -3, 5 * groups + 2, 7, L.style.hall)
    local width = H.w
    local placed = 0
    for _, y in ipairs(wall_rows(H)) do
        local in_row = 0
        for g = 0, groups - 1 do
            local x0 = 3 + 5 * g
            for k, dx in ipairs({0, 3}) do
                if placed < tables and in_row < per_row then
                    add(L, 'build', x0 + dx, y, 't', 'Table')
                    add(L, 'build', x0 + (k == 1 and 1 or 2), y, 'c', 'Chair')
                    placed = placed + 1
                    in_row = in_row + 1
                end
            end
        end
    end
    local far = 2 + width - 1
    add(L, 'build', far, -1, 'h', 'Box')
    add(L, 'build', far, 1, 'h', 'Box')
    hall_close(L, H)
    add(L, 'zone', 2, H.y, ('m{location=tavern}(%dx%d)'):format(width, H.h))
    L.summary = {tavern_tables = placed}
    return finish(L)
end

-- library{bookcases = 4-20}: bookcases along both walls, reading tables with
-- chairs at the far end, and a library zone.
function library(p)
    local L = new_layout('library', p)
    local cases, _, width, H = bed_hall(L, clamp(p.bookcases, 4, 20), nil, '~c', 'Bookcase', nil, function(far)
        add(L, 'build', far, -1, 't', 'Table')
        add(L, 'build', far - 1, -1, 'c', 'Chair')
        add(L, 'build', far, 1, 't', 'Table')
        add(L, 'build', far - 1, 1, 'c', 'Chair')
    end)
    add(L, 'zone', 2, H.y, ('m{location=library}(%dx%d)'):format(width, H.h))
    L.summary = {bookcases = cases}
    return finish(L)
end

-- farms{plots = 1-12, plot_w = 3-6}: a field east of the hub, farm plots
-- 3 deep in two rows either side of a walkway. Crops need soil: the tiles the
-- plots cover are listed in L.soil, and the builder only digs this level
-- where every one of them is natural soil. Soil can't be smoothed, so the
-- style's smoothing isn't used here. Not in KINDS: farms are started by the
-- farm_plots action (which first uses soil floor the fort already has).
function farms(p)
    local plots = clamp(p.plots, 1, 12)
    local pw = clamp(p.plot_w or 5, 3, 6)
    local L = new_layout('farms', p)
    L.style.smooth, L.style.statues = 0, 0
    L.soil = {}
    hub(L)
    local cols = math.ceil(plots / 2)
    dig_rect(L, 2, -3, cols * pw, 7)
    local placed = 0
    for col = 0, cols - 1 do
        for _, y in ipairs({-3, 1}) do
            if placed < plots then
                local x = 2 + col * pw
                add(L, 'build', x, y, ('p(%dx3)'):format(pw))
                for dx = 0, pw - 1 do
                    for dy = 0, 2 do mark(L.soil, x + dx, y + dy) end
                end
                placed = placed + 1
            end
        end
    end
    L.summary = {farm_plots = placed, farm_tiles = placed * pw * 3}
    return finish(L)
end

-- (0.103.11) dormitory: bedrooms{rooms = 4-20, dormitory = true}: one hall of
-- beds, a chest beside each, and a dormitory zone (a Communal fort)
local function dormitory(p)
    local L = new_layout('bedrooms', p)
    local beds, _, width, H = bed_hall(L, clamp(p.rooms, 4, 20), function(x, y)
        add(L, 'build', x, y, 'h', 'Box')
    end)
    add(L, 'zone', 2, H.y, ('D(%dx%d)'):format(width, H.h))
    L.summary = {rooms = beds, room_size = 0, beds = beds, dormitory = true}
    return finish(L)
end

local function sleeping(p)
    if type(p) == 'table' and p.dormitory == true then return dormitory(p) end
    return bedrooms(p)
end

local MAKERS = {farms = farms, bedrooms = sleeping, suites = suites, dining = dining, storage = storage,
                workshops = workshops, temple = temple, memorial = memorial, hospital = hospital,
                barracks = barracks, tombs = tombs, tavern = tavern, library = library, jail = jail,
                archery = archery, garden = garden}

-- Build the level, then turn it as the style says.
function make(kind, params)
    params = type(params) == 'table' and params or {}
    local fn = type(kind) == 'string' and MAKERS[kind] or nil
    if not fn then return nil, ('unknown level kind: %s'):format(tostring(kind)) end
    local L, err = fn(params)
    if not L then return nil, err end
    return orient_layout(L, L.style.orient)
end

-- The set of tiles a list of dig cells covers ('d' or 'd(WxH)'), as
-- tiles[x][y] = true. Projects store their cells, so progress is always
-- measured against what was actually designated, even if layouts change.
function tiles_from_dig(cells)
    local tiles = {}
    for _, c in ipairs(cells or {}) do
        local w, h = 1, 1
        local ew, eh = tostring(c.text):match('^d%((%d+)x(%d+)%)$')
        if ew then w, h = tonumber(ew), tonumber(eh) end
        for dx = 0, w - 1 do
            for dy = 0, h - 1 do
                tiles[c.x + dx] = tiles[c.x + dx] or {}
                tiles[c.x + dx][c.y + dy] = true
            end
        end
    end
    return tiles
end

-- Quickfort API data for one phase at z: data[z][y][x] = text, shifted by
-- the stair position. Two cells on the same tile would be a layout bug.
function to_data(cells, z)
    local grid = {}
    for _, c in ipairs(cells) do
        grid[c.y] = grid[c.y] or {}
        assert(grid[c.y][c.x] == nil, ('two cells at %d,%d'):format(c.x, c.y))
        grid[c.y][c.x] = c.text
    end
    return {[z] = grid}
end
