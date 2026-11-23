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
-- (D0 G4, the Design track) four new hall shapes beside today's three; see hall_mask
HALLS = {plain = true, rounded = true, pillared = true,
         octagonal = true, round = true, cruciform = true, nave = true}
OLD_HALLS = {plain = true, rounded = true, pillared = true}
-- (D0 G4) the design language's other style keys (d0-spec 1.4); each has a
-- default that gives today's layout
ASPECTS = {square = true, long = true, wide = true}       -- default: the kind's own proportions
ARMS = {corridor = true, cross = true, ring = true}       -- rooms off the hub (rooms_for)
MOTIF_FORMS = {rows = true, ring = true, cross = true, spiral = true, star = true, wave = true}
SCALE_MIN, SCALE_MAX, SCALE_DEFAULT = 80, 150, 100
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
    ScrewPress = 'wp',          -- (item9) paper pressed from slurry (Quickfort's key: needs an in-game look)
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
            rhythm = clamp(st.rhythm or 4, 3, 6),       -- tiles between pillars
            -- (D0 G4) the design language (d0-spec 1.4); an unknown value reads as the default
            scale = clamp(st.scale or SCALE_DEFAULT, SCALE_MIN, SCALE_MAX),
            aspect = ASPECTS[st.aspect] and st.aspect or nil,
            arms = ARMS[st.arms] and st.arms or 'corridor',
            motif = MOTIF_FORMS[st.motif] and st.motif or 'rows',
            grand = st.grand == true}
end

local function new_layout(kind, p)
    return {kind = kind, dig = {}, build = {}, place = {}, zone = {},
            tiles = {}, furniture = {}, summary = {}, halls = {},
            rooms_at = {},     -- (0.105.54) a workshops level's rooms by their centre tile (workshops())
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

---------------------------------------------------------------------------
-- (D0 G4, the Design track) Shapes, proportions and motifs
---------------------------------------------------------------------------

-- Quarter turns clockwise about the stair at (0, 0) (+y is south, so east
-- turns to south): q = 0-3. A rectangle turns by its corners.
local function rot_pt(q, x, y)
    if q == 1 then return -y, x elseif q == 2 then return -x, -y elseif q == 3 then return y, -x end
    return x, y
end

local function rot_rect(q, x, y, w, h)
    local ax, ay = rot_pt(q, x, y)
    local bx, by = rot_pt(q, x + w - 1, y + h - 1)
    local nw, nh = w, h
    if q == 1 or q == 3 then nw, nh = h, w end
    return math.min(ax, bx), math.min(ay, by), nw, nh
end

-- Rooms on a turned arm or ring side (cross_rooms, ring_rooms) are handed to
-- the kinds as ordinary slot records in a "virtual" frame: slot i lies VX * i
-- tiles east, unturned, so the kinds furnish it as they furnish a corridor
-- room. realize(L) then moves each furnished cell back by VX * i and turns it
-- (q quarter turns). The rooms themselves are dug where they really are.
local VX = 10000

local function virtual_slot(L, q, s)
    L.virtual = L.virtual or {}
    table.insert(L.virtual, {q = q})
    local i = #L.virtual
    s.x = s.x + VX * i
    s.door = {x = s.door.x + VX * i, y = s.door.y}
    return s
end

local function realize(L)
    if not L.virtual then return end
    for _, phase in ipairs({'build', 'place', 'zone', 'rooms_at'}) do
        for _, c in ipairs(L[phase]) do
            if c.x >= VX // 2 then
                local i = (c.x + VX // 2) // VX
                local q = L.virtual[i].q
                local x = c.x - VX * i
                local key, w, h = tostring(c.text):match('^(.-)%((%d+)x(%d+)%)$')
                if key then
                    local nx, ny, nw, nh = rot_rect(q, x, c.y, tonumber(w), tonumber(h))
                    c.x, c.y, c.text = nx, ny, ('%s(%dx%d)'):format(key, nw, nh)
                else
                    c.x, c.y = rot_pt(q, x, c.y)
                end
            end
        end
    end
    L.virtual = nil
end

-- The largest hall each kind grows to (scale, aspect, grand, a new shape's
-- margin); a kind's own size at its largest parameters is never cut.
HALL_MAX = {dining = {w = 64, h = 17}, temple = {w = 23, h = 17}, memorial = {w = 15, h = 15},
            garden = {w = 21, h = 15}, hospital = {w = 31, h = 11}, barracks = {w = 31, h = 11},
            tombs = {w = 41, h = 11}, library = {w = 31, h = 11}, bedrooms = {w = 31, h = 11},
            tavern = {w = 35, h = 11}}
GRAND_SCALE = 120         -- a grand level's halls are at least this scale
ASPECT_STRETCH = 1.25     -- long: 1.25 x the length; wide: 1.25 x the depth

-- A hall's size under the style: scale (80-150 %), aspect (square, long or
-- wide, at the same area), grand (at least GRAND_SCALE), and for the new
-- shapes (octagonal, round, cruciform, nave) a margin of 2 so the shape has
-- room round the furniture. Only floor is added: never smaller than (w, h),
-- never past HALL_MAX (unless (w, h) already is), and the depth keeps its
-- parity so the hall stays centred on the hub's row. A nave is long unless
-- the style says otherwise. Kinds without a HALL_MAX keep (w, h).
function scaled(kind, w, h, style)
    style = type(style) == 'table' and style or {}
    local max = HALL_MAX[kind]
    if not max then return w, h end
    local s = clamp(style.scale or SCALE_DEFAULT, SCALE_MIN, SCALE_MAX) / 100
    if style.grand == true then s = math.max(s, GRAND_SCALE / 100) end
    local aspect = ASPECTS[style.aspect] and style.aspect or (style.hall == 'nave' and 'long' or nil)
    local tw, th = w * s, h * s
    if aspect == 'long' then tw, th = tw * ASPECT_STRETCH, th / ASPECT_STRETCH
    elseif aspect == 'wide' then tw, th = tw / ASPECT_STRETCH, th * ASPECT_STRETCH
    elseif aspect == 'square' then
        local side = math.sqrt(w * h) * s
        tw, th = side, side
    end
    local mw, mh = math.max(w, max.w), math.max(h, max.h)
    local rw = math.max(w, math.min(mw, math.floor(tw + 0.5)))
    local rh = math.max(h, math.min(mh, math.floor(th + 0.5)))
    if HALLS[style.hall] and not OLD_HALLS[style.hall] then
        rw = math.max(rw, math.min(mw, w + 2))
        rh = math.max(rh, math.min(mh, h + 2))
    end
    if (rh - h) % 2 == 1 then rh = (rh + 1 <= mh) and rh + 1 or rh - 1 end
    return rw, rh
end

-- The tiles of a hall's rectangle (x, y, w, h) left as rock for its shape,
-- added to skip (a set, made if nil). Returns skip and, for a nave, its
-- pillars (a list of {x, y}: the kind places them where they fit).
--   plain       nothing
--   rounded,    the four corners (as today; a pillared hall's pillars are
--   pillared    the kind's or the motif's)
--   octagonal   the corners cut on the diagonal, min(w, h) // 4 deep
--   round       a circle when square; a long hall gets round ends (a stadium)
--   cruciform   a cross whose arms are half the hall's width and depth
--   nave        a long hall with two aisles of pillars, a quarter in from
--               each long wall, every `rhythm` tiles
function hall_mask(shape, x, y, w, h, skip, rhythm)
    skip = skip or {}
    local pillars = {}
    if shape == 'rounded' or shape == 'pillared' then
        corners_of(x, y, w, h, skip)
    elseif shape == 'octagonal' then
        local c = math.max(1, math.min(w, h) // 4)
        for i = 0, w - 1 do
            for j = 0, h - 1 do
                if math.min(i, w - 1 - i) + math.min(j, h - 1 - j) < c then mark(skip, x + i, y + j) end
            end
        end
    elseif shape == 'round' then
        local r = math.min(w, h) / 2
        for i = 0, w - 1 do
            for j = 0, h - 1 do
                local px, py = i + 0.5, j + 0.5
                local qx = math.max(r, math.min(w - r, px))
                local qy = math.max(r, math.min(h - r, py))
                if (px - qx) ^ 2 + (py - qy) ^ 2 > r * r then mark(skip, x + i, y + j) end
            end
        end
    elseif shape == 'cruciform' then
        local cx, cy = (w - 1) / 2, (h - 1) / 2
        for i = 0, w - 1 do
            for j = 0, h - 1 do
                if math.abs(i - cx) > w / 4 and math.abs(j - cy) > h / 4 then mark(skip, x + i, y + j) end
            end
        end
    elseif shape == 'nave' then
        rhythm = clamp(rhythm or 4, 3, 6)
        local a = math.max(1, h // 4)
        if h >= 5 then
            for px = x + 2, x + w - 3, rhythm do
                table.insert(pillars, {x = px, y = y + a})
                table.insert(pillars, {x = px, y = y + h - 1 - a})
            end
        end
    end
    return skip, pillars
end

-- Where a hall's pillars and statues stand for a motif's form (the design
-- language's motif, as a shape: brain/design.py MOTIF_FORM). Returns two
-- lists of {x, y}, in the order they are wanted: pillars, statue_spots. All
-- inside the hall, off its outer rows and columns; the kind keeps only those
-- that are floor, free and block no way through (place_blockers).
--   rows    today's: two rows of pillars, statues down the far (east) wall
--   ring    a ring of pillars, statues on an inner ring
--   cross   pillars along both axes, statues at the centre and the arms' ends
--   spiral  a two-armed spiral: statues on one arm, pillars on the other
--   star    eight rays of pillars, statues at the centre and the rays' tips
--   wave    two waves of pillars, statues on the middle line
function motif_mask(form, x, y, w, h, rhythm)
    rhythm = clamp(rhythm or 4, 3, 6)
    local pillars, statues, seen = {}, {}, {{}, {}}
    local cx, cy = x + (w - 1) / 2, y + (h - 1) / 2
    local ax, ay = math.max(1, (w - 1) / 2 - 1), math.max(1, (h - 1) / 2 - 1)
    local function put(list, which, px, py)
        px, py = math.floor(px + 0.5), math.floor(py + 0.5)
        if px <= x or px >= x + w - 1 or py <= y or py >= y + h - 1 then return end
        local k = px .. ',' .. py
        if not seen[which][k] then
            seen[which][k] = true
            table.insert(list, {x = px, y = py})
        end
    end
    local function pillar(px, py) put(pillars, 1, px, py) end
    local function statue(px, py) put(statues, 2, px, py) end
    local tau = 2 * math.pi
    if form == 'ring' then
        local a, b = math.max(1, ax - 0.5), math.max(1, ay - 0.5)
        local n = math.max(4, math.floor(tau * math.sqrt((a * a + b * b) / 2) / rhythm))
        for k = 0, n - 1 do
            local t = tau * k / n
            pillar(cx + a * math.cos(t), cy + b * math.sin(t))
        end
        for _, k in ipairs({0, 4, 2, 6, 1, 5, 3, 7}) do
            local t = tau * k / 8
            statue(cx + a * 0.5 * math.cos(t), cy + b * 0.5 * math.sin(t))
        end
    elseif form == 'cross' then
        for d = rhythm, math.max(ax, ay) + 1, rhythm do
            pillar(cx + d, cy); pillar(cx - d, cy); pillar(cx, cy + d); pillar(cx, cy - d)
        end
        statue(cx, cy)
        statue(cx + ax, cy); statue(cx - ax, cy); statue(cx, cy - ay); statue(cx, cy + ay)
        statue(cx + ax / 2, cy); statue(cx - ax / 2, cy); statue(cx, cy - ay / 2); statue(cx, cy + ay / 2)
    elseif form == 'spiral' then
        local turns = 2
        local tmax = tau * turns
        local function arm(phase, step, fn)
            local lastx, lasty
            local t = 0
            while t <= tmax do
                local f = t / tmax
                local px, py = cx + ax * f * math.cos(t + phase), cy + ay * f * math.sin(t + phase)
                if not lastx or (px - lastx) ^ 2 + (py - lasty) ^ 2 >= step * step then
                    fn(px, py)
                    lastx, lasty = px, py
                end
                t = t + 0.05
            end
        end
        arm(0, 3, statue)
        arm(math.pi, rhythm, pillar)
    elseif form == 'star' then
        local reach = math.max(ax, ay)
        for k = 0, 7 do
            local t = tau * k / 8
            for d = rhythm, reach, rhythm do
                local f = d / reach
                pillar(cx + ax * f * math.cos(t), cy + ay * f * math.sin(t))
            end
        end
        statue(cx, cy)
        for _, k in ipairs({0, 4, 2, 6, 1, 5, 3, 7}) do
            local t = tau * k / 8
            statue(cx + ax * math.cos(t), cy + ay * math.sin(t))
        end
        for _, k in ipairs({0, 4, 2, 6}) do
            local t = tau * k / 8
            statue(cx + ax * 0.5 * math.cos(t), cy + ay * 0.5 * math.sin(t))
        end
    elseif form == 'wave' then
        local period = 2 * rhythm + 2
        local amp = math.max(1, ay * 0.4)
        for px = x + 2, x + w - 3, rhythm do
            local s = math.sin(tau * (px - x) / period)
            pillar(px, cy - ay * 0.6 + amp * s)
            pillar(px, cy + ay * 0.6 + amp * s)
        end
        local spots = {}
        for px = x + 2, x + w - 3, math.max(2, period // 2) do table.insert(spots, px) end
        table.sort(spots, function(a, b)
            local da, db = math.abs(a - cx), math.abs(b - cx)
            if da ~= db then return da < db end
            return a < b
        end)
        for _, px in ipairs(spots) do statue(px, cy) end
    else   -- rows
        if h >= 7 then
            for px = x + 3, x + w - 4, rhythm do pillar(px, y + 2); pillar(px, y + h - 3) end
        end
        for _, dy in ipairs({0, -2, 2, -4, 4, -1, 1, -3, 3}) do statue(x + w - 2, math.floor(cy) + dy) end
    end
    return pillars, statues
end

-- Can a tile become rock or a statue without cutting any way through? Its
-- open neighbours (open(x, y) -> bool) must be one group among themselves
-- (dwarves step diagonally), and there must be one: then no walk anywhere
-- else is cut either.
local RING8 = {{-1, -1}, {0, -1}, {1, -1}, {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}}
local function can_block(open, x, y)
    local pts = {}
    for _, d in ipairs(RING8) do
        if open(x + d[1], y + d[2]) then table.insert(pts, d) end
    end
    if #pts == 0 then return false end
    local seen, stack, n = {[1] = true}, {1}, 1
    while #stack > 0 do
        local i = table.remove(stack)
        for j = 1, #pts do
            if not seen[j] and math.abs(pts[i][1] - pts[j][1]) <= 1 and math.abs(pts[i][2] - pts[j][2]) <= 1 then
                seen[j] = true
                n = n + 1
                table.insert(stack, j)
            end
        end
    end
    return n == #pts
end

-- A hall in the making: hall_open, then the kind's furniture (add), its
-- statues (hall_statues) and pillars (own_pillar), then hall_close digs it.
-- With today's shapes and the rows motif (H.legacy) everything is placed
-- exactly as before; otherwise the shape's cut never takes a tile with
-- furniture on it (nor the doorway from the hub), and statues and pillars
-- stand only where they cut no way through.
local function has_tile(set, x, y) return set[x] ~= nil and set[x][y] == true end

local function hall_open(L, x, top, w, h, shape)
    local st = L.style
    local rw, rh = scaled(L.kind, w, h, {scale = st.scale, aspect = st.aspect, grand = st.grand, hall = shape})
    local H = {x = x, y = top - (rh - h) // 2, w = rw, h = rh, base = {x = x, y = top, w = w, h = h},
               shape = shape, legacy = OLD_HALLS[shape] == true and st.motif == 'rows',
               own = {}, statue_req = nil}
    H.skip, H.nave = hall_mask(shape, H.x, H.y, H.w, H.h, nil, st.rhythm)
    if st.grand then L.engrave_all = true end
    return H
end

-- A pillar the kind itself wants (today's rows, a cloister).
local function own_pillar(H, x, y)
    if H.legacy then mark(H.skip, x, y) else table.insert(H.own, {x = x, y = y}) end
end

-- The kind's own statue spots, in order; it wants n of them (fewer when it
-- has fewer spots: that count never changes with the style).
local function hall_statues(L, H, n, spots)
    n = math.min(n, #spots)
    if H.legacy then
        for i = 1, n do add(L, 'build', spots[i].x, spots[i].y, 's', 'Statue') end
    else
        H.statue_req = {n = n, own = spots}
    end
    return n
end

local function in_rect(H, x, y)
    return x >= H.x and x < H.x + H.w and y >= H.y and y < H.y + H.h
end

-- Give back a cut tile that must be floor, and a way from it towards the
-- hall's middle (along its row, then its column) until it meets floor.
local function restore(H, x, y)
    local cx, cy = H.x + H.w // 2, H.y + H.h // 2
    while has_tile(H.skip, x, y) do
        H.skip[x][y] = nil
        if x ~= cx then x = x + (cx > x and 1 or -1)
        elseif y ~= cy then y = y + (cy > y and 1 or -1) end
    end
end

local function hall_close(L, H)
    if not H.legacy then
        local keep, blocked = {}, {}
        local function keep_at(x, y)
            if in_rect(H, x, y) then mark(keep, x, y); restore(H, x, y) end
        end
        for _, phase in ipairs({'build', 'place'}) do
            for _, c in ipairs(L[phase]) do keep_at(c.x, c.y) end
        end
        for dy = -1, 1 do keep_at(H.x, dy) end              -- the doorway from the hub
        local function floor(x, y)
            if in_rect(H, x, y) then return not has_tile(H.skip, x, y) and not has_tile(blocked, x, y) end
            return has_tile(L.tiles, x, y)
        end
        local function free(x, y)
            return in_rect(H, x, y) and x > H.x and not has_tile(H.skip, x, y) and not has_tile(keep, x, y)
                and not has_tile(blocked, x, y)
        end
        -- the local test first; when it can't tell, a walk over the whole hall
        -- and what is dug so far (the hub) from the hub's east tile
        local function ok_block(bx, by)
            if can_block(floor, bx, by) then return true end
            local total = 0
            for x = H.x, H.x + H.w - 1 do
                for y = H.y, H.y + H.h - 1 do
                    if floor(x, y) and not (x == bx and y == by) then total = total + 1 end
                end
            end
            for x, col in pairs(L.tiles) do
                for y in pairs(col) do
                    if not in_rect(H, x, y) and not (x == bx and y == by) then total = total + 1 end
                end
            end
            local seen, stack, n = {}, {{H.x - 1, 0}}, 1
            mark(seen, H.x - 1, 0)
            while #stack > 0 do
                local c = table.remove(stack)
                for _, d in ipairs(RING8) do
                    local nx, ny = c[1] + d[1], c[2] + d[2]
                    if not (nx == bx and ny == by) and not has_tile(seen, nx, ny) and floor(nx, ny) then
                        mark(seen, nx, ny)
                        n = n + 1
                        table.insert(stack, {nx, ny})
                    end
                end
            end
            return n == total
        end
        -- statues: the motif's spots, then the kind's own, then any spot that fits
        local req = H.statue_req
        if req and req.n > 0 then
            local placed = 0
            local function try(list, checked)
                for _, p in ipairs(list) do
                    if placed >= req.n then return end
                    local ok = checked and free(p.x, p.y) and ok_block(p.x, p.y)
                    if not checked then
                        ok = in_rect(H, p.x, p.y) and not has_tile(keep, p.x, p.y) and not has_tile(blocked, p.x, p.y)
                        if ok then restore(H, p.x, p.y) end
                    end
                    if ok then
                        mark(blocked, p.x, p.y); mark(keep, p.x, p.y)
                        add(L, 'build', p.x, p.y, 's', 'Statue')
                        placed = placed + 1
                    end
                end
            end
            if L.style.motif ~= 'rows' then
                local _, spots = motif_mask(L.style.motif, H.x, H.y, H.w, H.h, L.style.rhythm)
                try(spots, true)
            end
            try(req.own, true)
            local any = {}                                   -- from the far wall's middle
            for x = H.x + H.w - 2, H.x + 1, -1 do
                for _, dy in ipairs({0, -1, 1, -2, 2, -3, 3, -4, 4, -5, 5, -6, 6, -7, 7, -8, 8}) do
                    local y = H.y + H.h // 2 + dy
                    if y > H.y and y < H.y + H.h - 1 then table.insert(any, {x = x, y = y}) end
                end
            end
            try(any, true)
            try(req.own, false)
        end
        -- pillars: a cloister's, else the nave's aisles, else the motif's (in a
        -- pillared hall, or where the kind has pillars), else the kind's own
        local list = H.own
        if not H.cloister then
            if H.shape == 'nave' then list = H.nave
            elseif L.style.motif ~= 'rows' and (H.shape == 'pillared' or #H.own > 0) then
                list = motif_mask(L.style.motif, H.x, H.y, H.w, H.h, L.style.rhythm)
            end
        end
        for _, p in ipairs(list) do
            if free(p.x, p.y) and ok_block(p.x, p.y) then mark(H.skip, p.x, p.y) end
        end
    end
    dig_rect_except(L, H.x, H.y, H.w, H.h, H.skip)
    table.insert(L.halls, {x = H.x, y = H.y, w = H.w, h = H.h})
end

-- Smoothing and engraving cells, from the style (see docs/culture.md):
--   smooth 1: floors; 2: floors and walls; 3: also engrave the halls' walls.
-- Engraving needs smoothed stone, so the builder applies L.engrave only after
-- the smoothing is done.
function decorate(L)
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

function set_bounds(L)
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
    realize(L)                    -- (D0 G4) rooms on turned arms (cross_rooms, ring_rooms)
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
    for _, phase in ipairs({'dig', 'build', 'place', 'zone', 'smooth', 'engrave', 'rooms_at'}) do
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

-- (r9) this file's locals the later parts use (each takes back the ones it
-- uses as locals of its own): all functions and fixed values, set once here
PART_LOCALS = {clamp = clamp, new_layout = new_layout, dig_rect = dig_rect, dig_rect_except = dig_rect_except, mark = mark, corners_of = corners_of, add = add, rot_rect = rot_rect, virtual_slot = virtual_slot, hall_open = hall_open, own_pillar = own_pillar, hall_statues = hall_statues, hall_close = hall_close, finish = finish}

---------------------------------------------------------------------------
-- (r9) The rest of the layouts lives in a part beside this file
-- (ai-layouts-kinds.lua): the hub round the stair, the rooms off it
-- (corridors, cross and ring arms), every kind's level (bedrooms ...
-- farms), make(), tiles_from_dig() and to_data(). It runs in this module's
-- own environment, so its names stay reqscript('ai-layouts').name for the
-- builder, the bridge and ai-blueprints, and a test's swap (L.scaled = ...)
-- reaches it. DFHack reloads a module when its own file changes: a change
-- to the part alone is picked up once ai-layouts.lua is touched too, or the
-- game restarts.
---------------------------------------------------------------------------

PARTS = {'kinds'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-layouts'] = '0.105.73'}   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local name = 'ai-layouts-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-layouts: ' .. name .. '.lua is missing (it goes beside ai-layouts.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
