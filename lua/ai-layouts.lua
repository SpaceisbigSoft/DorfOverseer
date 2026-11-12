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
    for _, phase in ipairs({'build', 'place', 'zone'}) do
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
    local ring, per_half = 3, 0
    while true do
        local xmax = ring + width - 2
        per_half = (xmax - 3 + 1 + wall) // pitch
        if per_half >= 1 and 8 * per_half >= nslots then break end
        ring = ring + 1
    end
    local outer = -(ring + width - 1)          -- the loop's outer row on the north side
    local ry, door_y = outer - 1 - size, outer - 1
    local door_dx = (size - 1) // 2
    local slots, rooms = {}, {}
    for k = 0, per_half - 1 do
        local right = 3 + k * pitch
        for q = 0, 3 do
            for _, rx in ipairs({right, -(right + size - 1)}) do
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

-- The rooms of a room level, arranged as the style's arms say.
local function rooms_for(L, nslots, size, round)
    if L.style.arms == 'cross' then return cross_rooms(L, nslots, size, round) end
    if L.style.arms == 'ring' then return ring_rooms(L, nslots, size, round) end
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
function workshops(p)
    local shops = {}
    for _, name in ipairs(type(p.shops) == 'table' and p.shops or {}) do
        if WORKSHOPS[name] and #shops < 12 then table.insert(shops, name) end
    end
    if #shops == 0 then return nil, 'no valid workshop types' end
    local L = new_layout('workshops', p)
    -- (0.105.29, custom ore_piles) one room more, a 5x5 stone (and ore) pile, under 12 shops
    local ore = L.style.customs.ore_piles and #shops < 12
    local slots = rooms_for(L, #shops + (ore and 1 or 0), 5, L.style.hall ~= 'plain')
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
