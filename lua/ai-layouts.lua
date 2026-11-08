-- Level layouts for the AI overseer: pure functions, no game access.
--
-- Every layout is centred on a staircase tile at (0, 0); +x is east, +y is
-- south. The stair tile itself is never in a layout (digging it would remove
-- the stairs). A layout is:
--   kind, summary   what it is, in words and numbers
--   dig             list of {x, y, text}: Quickfort dig cells ('d', 'd(3x1)')
--   build           list of {x, y, text}: doors, furniture, workshops
--   place           list of {x, y, text}: stockpiles
--   zone            list of {x, y, text}: bedroom / dining zones
--   tiles           every tile that gets dug, as a set: tiles[x][y] = true
--   bounds          {x1, y1, x2, y2} of the dug tiles
--   furniture       counts by building type, e.g. {Bed=8, Door=8}
--   halls           list of {x, y, w, h}: the halls (for engraving)
--   orient          0-3, how the level was turned (see orient_layout)
--
-- See docs/building.md. Tested with tests/test_layouts.py.
--@ module = true

KINDS = {'bedrooms', 'suites', 'jail', 'dining', 'storage', 'workshops', 'temple', 'memorial', 'hospital', 'barracks',
         'tombs', 'tavern', 'library', 'archery', 'garden'}
HALLS = {plain = true, rounded = true, pillared = true}
-- (0.105.29) Fort customs the layouts read (style.customs; brain/customs.py
-- LAYOUT): a cloister round the temple, an armoury alcove in the barracks,
-- a stone and ore pile on workshop levels. Unknown names are ignored.
LAYOUT_CUSTOMS = {cloister = true, armoury = true, ore_piles = true}

-- Quickfort stockpile keys the AI may use, and what they hold.
STOCKPILES = {
    food = 'f', stone = 's', wood = 'w', furniture = 'u', bars_blocks = 'b',
    finished_goods = 'g', cloth = 'h', leather = 'l', gems = 'e',
    ammo = 'z', weapons = 'p', armor = 'd',
}
-- Workshops the AI may place (Quickfort build keys), all 3x3.
WORKSHOPS = {
    Carpenters = 'wc', Masons = 'wm', Craftsdwarfs = 'wr', Still = 'wl',
    Kitchen = 'wz', Butchers = 'wu', Tanners = 'wn', Leatherworks = 'we',
    Loom = 'wo', Clothiers = 'wk', Farmers = 'ww', Fishery = 'wh',
    Mechanics = 'wt', Jewelers = 'wj', Ashery = 'wy', Millstone = 'wM',
    Quern = 'wq', Bowyers = 'wb', SoapMaker = 'wS',
    -- furnaces and the forge (metal: brain/planner.py's industry rule)
    WoodFurnace = 'ew', Smelter = 'es', MetalsmithsForge = 'wf', Kiln = 'ek',
    GlassFurnace = 'eg',        -- (0.104.95) glass from bags of sand, with fuel
}

local function clamp(v, lo, hi)
    v = math.tointeger(tonumber(v)) or lo
    return math.max(lo, math.min(hi, v))
end

-- The fort's style for this level (from its culture; see docs/culture.md).
-- Without a style, levels are plain and undecorated.
local function style_of(p)
    local st = type(p.style) == 'table' and p.style or {}
    local customs = {}
    for _, c in ipairs(type(st.customs) == 'table' and st.customs or {}) do
        if LAYOUT_CUSTOMS[c] then customs[c] = true end
    end
    return {customs = customs,                          -- (0.105.29) a set: customs.cloister = true
            hall = HALLS[st.hall] and st.hall or 'plain',
            smooth = clamp(st.smooth or 0, 0, 3),
            statues = clamp(st.statues or 0, 0, 4),
            spacing = clamp(st.spacing or 0, -200, 200),
            orient = clamp(st.orient or 0, 0, 3),       -- how the level is turned (orient_layout)
            rhythm = clamp(st.rhythm or 4, 3, 6)}       -- tiles between pillars
end

local function new_layout(kind, p)
    return {kind = kind, dig = {}, build = {}, place = {}, zone = {},
            tiles = {}, furniture = {}, summary = {}, halls = {},
            style = style_of(p or {}), engrave_all = false}
end

-- Dig a w x h rectangle with its top-left corner at (x, y).
local function dig_rect(L, x, y, w, h)
    table.insert(L.dig, {x = x, y = y,
        text = (w == 1 and h == 1) and 'd' or ('d(%dx%d)'):format(w, h)})
    for dx = 0, w - 1 do
        for dy = 0, h - 1 do
            L.tiles[x + dx] = L.tiles[x + dx] or {}
            L.tiles[x + dx][y + dy] = true
        end
    end
end

-- Dig a rectangle except some tiles (left as wall: rounded corners, pillars).
-- Emitted as row segments so Quickfort never touches the skipped tiles.
local function dig_rect_except(L, x, y, w, h, skip)
    for dy = 0, h - 1 do
        local run_start = nil
        for dx = 0, w do
            local keep = dx < w and not (skip[x + dx] and skip[x + dx][y + dy])
            if keep and not run_start then run_start = dx end
            if not keep and run_start then
                dig_rect(L, x + run_start, y + dy, dx - run_start, 1)
                run_start = nil
            end
        end
    end
end

local function mark(set, x, y)
    set[x] = set[x] or {}
    set[x][y] = true
end

-- The corners of a rectangle, for rounded halls and rooms.
local function corners_of(x, y, w, h, skip)
    skip = skip or {}
    if w >= 4 and h >= 4 then
        mark(skip, x, y); mark(skip, x + w - 1, y)
        mark(skip, x, y + h - 1); mark(skip, x + w - 1, y + h - 1)
    end
    return skip
end

local function add(L, phase, x, y, text, furniture_type)
    table.insert(L[phase], {x = x, y = y, text = text})
    if furniture_type then
        L.furniture[furniture_type] = (L.furniture[furniture_type] or 0) + 1
    end
end

-- Smoothing and engraving cells, from the style (see docs/culture.md):
--   smooth 1: floors; 2: floors and walls; 3: also engrave the halls' walls.
-- Engraving needs smoothed stone, so the builder applies L.engrave only after
-- the smoothing is done.
local function decorate(L)
    L.smooth, L.engrave = {}, {}
    local lvl = L.style.smooth
    local walls, hall_walls = {}, {}
    local function in_hall(x, y)
        for _, h in ipairs(L.halls) do
            if x >= h.x - 1 and x <= h.x + h.w and y >= h.y - 1 and y <= h.y + h.h then return true end
        end
        return false
    end
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            if lvl >= 1 or (L.engrave_all and in_hall(x, y)) then
                table.insert(L.smooth, {x = x, y = y, text = 's'})
            end
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local nx, ny = x + dx, y + dy
                    if not (L.tiles[nx] and L.tiles[nx][ny]) and not (nx == 0 and ny == 0) then
                        mark(walls, nx, ny)
                        if in_hall(nx, ny) then mark(hall_walls, nx, ny) end
                    end
                end
            end
        end
    end
    local want_walls = lvl >= 2
    local want_engrave = lvl >= 3 or L.engrave_all
    for x, col in pairs(walls) do
        for y in pairs(col) do
            local hall = hall_walls[x] and hall_walls[x][y]
            if want_walls or (L.engrave_all and hall) then
                table.insert(L.smooth, {x = x, y = y, text = 's'})
            end
            if want_engrave and hall then
                table.insert(L.engrave, {x = x, y = y, text = 'e'})
            end
        end
    end
    -- engraved hall floors too, when the walls are engraved
    if want_engrave then
        for x, col in pairs(L.tiles) do
            for y in pairs(col) do
                if in_hall(x, y) then table.insert(L.engrave, {x = x, y = y, text = 'e'}) end
            end
        end
    end
end

local function set_bounds(L)
    local x1, y1, x2, y2 = math.huge, math.huge, -math.huge, -math.huge
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            x1, x2 = math.min(x1, x), math.max(x2, x)
            y1, y2 = math.min(y1, y), math.max(y2, y)
        end
    end
    L.bounds = {x1 = x1, y1 = y1, x2 = x2, y2 = y2}
end

local function finish(L)
    decorate(L)
    set_bounds(L)
    return L
end

-- Turning a finished level (style.orient), all around the stair at (0, 0):
--   0 as built (halls and corridors run east-west), 1 mirrored east-west,
--   2 transposed (x, y) -> (y, x) so they run north-south, 3 transposed
--   then mirrored.
-- A cell written 'key(WxH)' covers W x H tiles from its top-left corner, so
-- it is turned as a rectangle (new top-left, W and H swapped on transpose).
-- Any other cell is a single tile, or a building placed by its centre tile
-- (workshops), and just moves.
local function turn_rect(o, x, y, w, h)
    if o >= 2 then x, y, w, h = y, x, h, w end
    if o == 1 or o == 3 then x = -(x + w - 1) end
    return x, y, w, h
end

-- An archery range's shooting direction, turned with the level: mirrored
-- east-west (1) swaps west and east; transposed (2, 3) makes west north and
-- east south (north and south become west and east).
local SHOOT_TURN = {
    [1] = {west = 'east', east = 'west', north = 'north', south = 'south'},
    [2] = {west = 'north', east = 'south', north = 'west', south = 'east'},
    [3] = {west = 'north', east = 'south', north = 'east', south = 'west'},
}
function turn_shoot(o, key)
    return (key:gsub('shoot_from=(%a+)', function(d)
        return 'shoot_from=' .. ((SHOOT_TURN[o] or {})[d] or d)
    end))
end

local function turn_cell(o, c)
    local key, w, h = tostring(c.text):match('^(.-)%((%d+)x(%d+)%)$')
    if key then
        key = turn_shoot(o, key)
        local x, y, nw, nh = turn_rect(o, c.x, c.y, tonumber(w), tonumber(h))
        return {x = x, y = y, text = ('%s(%dx%d)'):format(key, nw, nh)}
    end
    local x, y = turn_rect(o, c.x, c.y, 1, 1)
    return {x = x, y = y, text = c.text}
end

local function turn_set(o, set)
    local out = {}
    for x, col in pairs(set) do
        for y in pairs(col) do
            local nx, ny = turn_rect(o, x, y, 1, 1)
            mark(out, nx, ny)
        end
    end
    return out
end

function orient_layout(L, o)
    o = clamp(o or 0, 0, 3)
    L.orient = o
    if o == 0 then return L end
    for _, phase in ipairs({'dig', 'build', 'place', 'zone', 'smooth', 'engrave'}) do
        local cells = {}
        for _, c in ipairs(L[phase] or {}) do table.insert(cells, turn_cell(o, c)) end
        L[phase] = cells
    end
    for i, r in ipairs(L.halls) do
        local x, y, w, h = turn_rect(o, r.x, r.y, r.w, r.h)
        L.halls[i] = {x = x, y = y, w = w, h = h}
    end
    L.tiles = turn_set(o, L.tiles)
    if L.soil then L.soil = turn_set(o, L.soil) end
    set_bounds(L)
    return L
end

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
    local slots = corridor_rooms(L, rooms, size)
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
    local slots = corridor_rooms(L, n * 2, size)
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
    local slots = corridor_rooms(L, n, 3)
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
    local skip = {}
    if L.style.hall ~= 'plain' then corners_of(2, -5, width, 11, skip) end
    if L.style.hall == 'pillared' then
        -- pillars on the two walkways between table rows, every `rhythm` tiles
        for x = 4, 2 + width - 3, L.style.rhythm do mark(skip, x, -2); mark(skip, x, 1) end
    end
    dig_rect_except(L, 2, -5, width, 11, skip)
    table.insert(L.halls, {x = 2, y = -5, w = width, h = 11})
    -- statues along the free row at the far side
    local placed_statues = 0
    for x = 4, 2 + width - 3, 4 do
        if placed_statues < L.style.statues then
            add(L, 'build', x, 5, 's', 'Statue')
            placed_statues = placed_statues + 1
        end
    end
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
    add(L, 'zone', 2, -5, ('h(%dx%d)'):format(width, 11))
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
    local slots = corridor_rooms(L, #piles, size, L.style.hall ~= 'plain')
    for i, s in ipairs(slots) do
        add(L, 'place', s.x, s.y, ('%s(%dx%d)'):format(STOCKPILES[piles[i]], s.size, s.size))
    end
    L.summary = {stockpiles = piles, room_size = size}
    return finish(L)
end

-- workshops{shops = {'Still', 'Kitchen', ...}} (5x5 rooms, workshop centred)
function workshops(p)
    local shops = {}
    for _, name in ipairs(type(p.shops) == 'table' and p.shops or {}) do
        if WORKSHOPS[name] and #shops < 12 then table.insert(shops, name) end
    end
    if #shops == 0 then return nil, 'no valid workshop types' end
    local L = new_layout('workshops', p)
    -- (0.105.29, custom ore_piles) one room more, a 5x5 stone (and ore) pile, under 12 shops
    local ore = L.style.customs.ore_piles and #shops < 12
    local slots = corridor_rooms(L, #shops + (ore and 1 or 0), 5, L.style.hall ~= 'plain')
    for i, s in ipairs(slots) do
        if shops[i] then
            add(L, 'build', s.x + 2, s.y + 2, WORKSHOPS[shops[i]], shops[i])
        else
            add(L, 'place', s.x, s.y, ('%s(5x5)'):format(STOCKPILES.stone))
        end
    end
    L.summary = {workshops = shops, ore_pile = ore or nil}
    return finish(L)
end

-- temple{size = 'shrine' | 'grand'}: a hall east of the hub with statues and
-- a temple zone (open to all gods).
function temple(p)
    local grand = p.size == 'grand'
    local L = new_layout('temple', p)
    hub(L)
    local w, h = grand and 15 or 7, grand and 11 or 7
    local top = -(h // 2)
    local skip = {}
    if L.style.hall ~= 'plain' or grand then corners_of(2, top, w, h, skip) end
    local cloister = L.style.customs.cloister
    if cloister then
        -- (0.105.29, custom cloister) a pillared walk 1 tile in from the walls:
        -- pillars on the second and second-last rows and the west column (not
        -- the doorway row); the statue column (2+w-2) stays clear. In a grand
        -- temple the ring takes the place of its own two pillar rows.
        for x = 4, 2 + w - 3, 2 do
            mark(skip, x, top + 1); mark(skip, x, top + h - 2)
        end
        for y = top + 1, top + h - 2, 2 do
            if math.abs(y) > 1 then mark(skip, 3, y) end
        end
    elseif grand then
        for x = 5, 2 + w - 4, L.style.rhythm do
            mark(skip, x, top + 2); mark(skip, x, top + h - 3)
        end
    end
    dig_rect_except(L, 2, top, w, h, skip)
    table.insert(L.halls, {x = 2, y = top, w = w, h = h})
    -- statues along the far (east) wall, centre first, then outwards
    local n = (grand and 2 or 1) + (grand and L.style.statues or L.style.statues // 2)
    local ex = 2 + w - 2
    local spots = {0, -2, 2, -4, 4, -1, 1, -3, 3}
    local placed = 0
    for _, dy in ipairs(spots) do
        if placed < n and dy > top and dy < top + h - 1 then
            add(L, 'build', ex, dy, 's', 'Statue')
            placed = placed + 1
        end
    end
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
    dig_rect_except(L, 2, -4, 9, 9, corners_of(2, -4, 9, 9))
    table.insert(L.halls, {x = 2, y = -4, w = 9, h = 9})
    add(L, 'build', 6, 0, 's', 'Statue')
    local around = {{4, -2}, {8, 2}, {8, -2}, {4, 2}}
    for i = 1, math.min(4, L.style.statues) do
        add(L, 'build', around[i][1], around[i][2], 's', 'Statue')
    end
    add(L, 'zone', 2, -4, ('m{name="Hall of %s"}(9x9)'):format(name))
    L.summary = {memorial = name, statues = 1 + math.min(4, L.style.statues)}
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
    dig_rect_except(L, 2, -4, 13, 9, corners_of(2, -4, 13, 9))
    table.insert(L.halls, {x = 2, y = -4, w = 13, h = 9})
    local statues = 0
    for x = 4, 12, 2 do
        for _, y in ipairs({-2, 2}) do
            add(L, 'build', x, y, 's', 'Statue')
            statues = statues + 1
        end
    end
    add(L, 'build', 8, 0, 't', 'Table')
    add(L, 'build', 7, 0, 'c', 'Chair')
    add(L, 'build', 9, 0, 'c', 'Chair')
    add(L, 'zone', 2, -4, ('m{name="The %s Garden"}(13x9)'):format(name))
    L.summary = {garden = name, statues = statues}
    return finish(L)
end

-- A hall east of the hub with beds along both long walls (odd x), for the
-- hospital and the barracks. Returns the layout and the hall's far column.
local function bed_hall(L, beds, extra_on_wall, key, ftype, each)
    hub(L)
    local per_row = math.ceil(beds / 2)
    local width = 2 * per_row + 3
    local skip = {}
    if L.style.hall ~= 'plain' then corners_of(2, -3, width, 7, skip) end
    dig_rect_except(L, 2, -3, width, 7, skip)
    table.insert(L.halls, {x = 2, y = -3, w = width, h = 7})
    local placed = 0
    for i = 0, per_row - 1 do
        for _, y in ipairs({-3, 3}) do
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
    return placed, 2 + width - 1, width
end

-- hospital{beds = 4-20}: beds, plus tables and chests for supplies at the far
-- end, and a hospital zone.
function hospital(p)
    local L = new_layout('hospital', p)
    local beds, far, width = bed_hall(L, clamp(p.beds, 4, 20))
    add(L, 'build', far, 0, 't', 'Table')
    add(L, 'build', far, -1, 'h', 'Box')
    add(L, 'build', far, 1, 'h', 'Box')
    add(L, 'zone', 2, -3, ('m{location=hospital}(%dx7)'):format(width))
    L.summary = {hospital_beds = beds}
    return finish(L)
end

-- barracks{beds = 4-20}: beds with an armor stand beside each, weapon racks at
-- the far end, and a barracks zone (squads are assigned in the game).
function barracks(p)
    local L = new_layout('barracks', p)
    local stands = 0
    local beds, far, width = bed_hall(L, clamp(p.beds, 4, 20), function(x, y)
        add(L, 'build', x, y, 'a', 'Armorstand')
        stands = stands + 1
    end)
    add(L, 'build', far, -1, 'r', 'Weaponrack')
    add(L, 'build', far, 1, 'r', 'Weaponrack')
    add(L, 'zone', 2, -3, ('B(%dx7)'):format(width))
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

-- tombs{coffins = 4-30}: coffins along both walls, each in its own 1x1 tomb
-- zone, so every coffin can take one burial.
function tombs(p)
    local L = new_layout('tombs', p)
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
    local width = 5 * groups + 2
    local skip = {}
    if L.style.hall ~= 'plain' then corners_of(2, -3, width, 7, skip) end
    dig_rect_except(L, 2, -3, width, 7, skip)
    table.insert(L.halls, {x = 2, y = -3, w = width, h = 7})
    local placed = 0
    for _, y in ipairs({-3, 3}) do
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
    add(L, 'zone', 2, -3, ('m{location=tavern}(%dx7)'):format(width))
    L.summary = {tavern_tables = placed}
    return finish(L)
end

-- library{bookcases = 4-20}: bookcases along both walls, reading tables with
-- chairs at the far end, and a library zone.
function library(p)
    local L = new_layout('library', p)
    local cases, far, width = bed_hall(L, clamp(p.bookcases, 4, 20), nil, '~c', 'Bookcase')
    add(L, 'build', far, -1, 't', 'Table')
    add(L, 'build', far - 1, -1, 'c', 'Chair')
    add(L, 'build', far, 1, 't', 'Table')
    add(L, 'build', far - 1, 1, 'c', 'Chair')
    add(L, 'zone', 2, -3, ('m{location=library}(%dx7)'):format(width))
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
    local beds, _, width = bed_hall(L, clamp(p.rooms, 4, 20), function(x, y)
        add(L, 'build', x, y, 'h', 'Box')
    end)
    add(L, 'zone', 2, -3, ('D(%dx7)'):format(width))
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
