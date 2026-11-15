-- (layout B) A level cut into room units for a floor: pure functions, no
-- game access (like ai-layouts.lua).
--
-- An ordinary ai-layouts level (made with style.orient = 0 and style.arms =
-- 'corridor': unit_params) is cut into room UNITS: each room of a bedrooms,
-- suites, jail, storage or workshops level; the one hall of a dining hall,
-- temple, hospital... A unit is described in the BAY FRAME: bx = 0 .. w - 1
-- along the main hall, by = 0 the wall row (rock, but for the unit's opening
-- or door), by = 1 .. d the room, growing away from the hall. ai-floorplace
-- decides where each unit goes on a floor (its `placement`: one transform T,
-- bay -> stair-relative, a put); compose() turns the units' cells with those
-- transforms and adds the new main hall tiles: the layout a floor project is
-- dug and furnished from. Nothing here knows about floors or reads the map.
--
-- A transform T = {a, b, c, d, tx, ty}: (x, y) -> (a*x + b*y + tx,
-- c*x + d*y + ty), its linear part one of the 8 turns and mirrors of a
-- square. +x is east, +y south (DF's axes, ai-layouts' frame).
--
-- Tested with tests/test_b3_floorunits.py.
--@ module = true

-- A test may set this to its own ai-layouts module (or pass opts.layouts to
-- compose); in the game the module is fetched when compose first needs it,
-- never while this file loads.
LAYOUTS = nil

local function layouts_of(opts)
    if type(opts) == 'table' and type(opts.layouts) == 'table' then return opts.layouts end
    if type(LAYOUTS) == 'table' then return LAYOUTS end
    return reqscript('ai-layouts')
end

local PHASES = {'build', 'place', 'zone', 'rooms_at'}
-- hall levels whose doorway from the hub is the hub's whole 3-wide side
WIDE_HALLS = {dining = true, tavern = true, temple = true, garden = true, library = true}

---------------------------------------------------------------------------
-- Transforms
---------------------------------------------------------------------------

function xf(a, b, c, d, tx, ty)
    return {a = a, b = b, c = c, d = d, tx = tx or 0, ty = ty or 0}
end

function xf_point(T, x, y)
    return T.a * x + T.b * y + T.tx, T.c * x + T.d * y + T.ty
end

-- A w x h rectangle from its top-left (x, y): the image's top-left and size
-- (turned by its corners; w and h swap when the axes swap).
function xf_rect(T, x, y, w, h)
    local ax, ay = xf_point(T, x, y)
    local bx, by = xf_point(T, x + w - 1, y + h - 1)
    if T.a == 0 then w, h = h, w end
    return math.min(ax, bx), math.min(ay, by), w, h
end

-- T2 after T1.
function xf_compose(T2, T1)
    return {a = T2.a * T1.a + T2.b * T1.c, b = T2.a * T1.b + T2.b * T1.d,
            c = T2.c * T1.a + T2.d * T1.c, d = T2.c * T1.b + T2.d * T1.d,
            tx = T2.a * T1.tx + T2.b * T1.ty + T2.tx,
            ty = T2.c * T1.tx + T2.d * T1.ty + T2.ty}
end

local WORD_VEC = {north = {0, -1}, south = {0, 1}, east = {1, 0}, west = {-1, 0}}

-- A compass word through T's linear part ('west' under a quarter turn
-- clockwise is 'north'); any other word comes back as it is.
function turn_word(T, word)
    local v = WORD_VEC[word]
    if not v then return word end
    local x, y = T.a * v[1] + T.b * v[2], T.c * v[1] + T.d * v[2]
    for name, w in pairs(WORD_VEC) do
        if w[1] == x and w[2] == y then return name end
    end
    return word
end

-- The compass words a key holds: an archery range's shoot_from. (Only that:
-- a memorial's name may hold "West" and must stay as written.)
local function turn_key(T, key)
    return (key:gsub('shoot_from=(%a+)', function(d) return 'shoot_from=' .. turn_word(T, d) end))
end

-- 'key(WxH)' -> key, W, H; anything else -> nil (one tile, or a building
-- placed by its centre).
local function split_rect(text)
    local key, w, h = tostring(text):match('^(.-)%((%d+)x(%d+)%)$')
    if key then return key, math.tointeger(tonumber(w)), math.tointeger(tonumber(h)) end
    return nil
end

function xf_cell(T, cell)
    local key, w, h = split_rect(cell.text)
    if key then
        local x, y, nw, nh = xf_rect(T, cell.x, cell.y, w, h)
        return {x = x, y = y, text = ('%s(%dx%d)'):format(turn_key(T, key), nw, nh)}
    end
    local x, y = xf_point(T, cell.x, cell.y)
    return {x = x, y = y, text = turn_key(T, tostring(cell.text))}
end

---------------------------------------------------------------------------
-- Small helpers
---------------------------------------------------------------------------

local function mark(set, x, y)
    set[x] = set[x] or {}
    set[x][y] = true
end

local function has(set, x, y) return set[x] ~= nil and set[x][y] == true end

local function deep_copy(v, seen)
    if type(v) ~= 'table' then return v end
    seen = seen or {}
    if seen[v] then return seen[v] end
    local out = {}
    seen[v] = out
    for k, x in pairs(v) do out[deep_copy(k, seen)] = deep_copy(x, seen) end
    return out
end

-- A set of tiles as dig cells, row by row: 'd' for one tile, 'd(Nx1)' for a
-- run. Rock inside a room (a rounded corner, a pillar) is in no run, so
-- Quickfort never touches it. Rows north to south, runs west to east.
local function row_runs(set)
    local rows, ys = {}, {}
    for x, col in pairs(set) do
        for y in pairs(col) do
            if not rows[y] then rows[y] = {}; table.insert(ys, y) end
            table.insert(rows[y], x)
        end
    end
    table.sort(ys)
    local cells = {}
    for _, y in ipairs(ys) do
        local xs = rows[y]
        table.sort(xs)
        local i = 1
        while i <= #xs do
            local j = i
            while j < #xs and xs[j + 1] == xs[j] + 1 do j = j + 1 end
            local n = j - i + 1
            table.insert(cells, {x = xs[i], y = y, text = n == 1 and 'd' or ('d(%dx1)'):format(n)})
            i = j + 1
        end
    end
    return cells
end

-- The tiles a list of dig cells covers ('d', 'd3', 'd(WxH)').
local function dig_tiles(cells)
    local set = {}
    for _, c in ipairs(cells or {}) do
        local _, w, h = split_rect(c.text)
        for dx = 0, (w or 1) - 1 do
            for dy = 0, (h or 1) - 1 do mark(set, c.x + dx, c.y + dy) end
        end
    end
    return set
end

---------------------------------------------------------------------------
-- unit_params
---------------------------------------------------------------------------

-- The params a level is made with before it is cut: a deep copy (the
-- caller's are used again for the classic layout) with style.orient = 0 and
-- style.arms = 'corridor'; a workshops level (params.kind, or one that
-- names shops) also without spare rooms.
function unit_params(params)
    local p = type(params) == 'table' and deep_copy(params) or {}
    if type(p.style) ~= 'table' then p.style = {} end
    p.style.orient = 0
    p.style.arms = 'corridor'
    if p.kind == 'workshops' or (p.kind == nil and p.shops ~= nil) then
        p.spare = 0
        p.spare_for = nil
    end
    return p
end

---------------------------------------------------------------------------
-- cut
---------------------------------------------------------------------------

local function new_unit(mode, w, d)
    return {w = w, d = d, mode = mode, open = nil, dig = {}, build = {}, place = {}, zone = {},
            rooms_at = {}, halls = {}, tiles = {}, tag = nil}
end

-- The unit's dig cells from its tiles, and a last check of the bay frame.
local function close_unit(u)
    for x, col in pairs(u.tiles) do
        for y in pairs(col) do
            if x < 0 or x > u.w - 1 or y < 0 or y > u.d then return nil, 'a tile outside its bay' end
            if y == 0 and (x < u.open[1] or x > u.open[2]) then return nil, 'a wall row tile outside the opening' end
        end
    end
    for x = u.open[1], u.open[2] do
        if not has(u.tiles, x, 0) or not has(u.tiles, x, 1) then return nil, 'an opening onto rock' end
    end
    u.dig = row_runs(u.tiles)
    return u
end

-- Room mode: the rooms either side of the corridor, one unit each.
local function cut_rooms(L)
    local top = math.tointeger(L.corridor.top)
    local width = math.tointeger(L.corridor.width)
    if not top or not width or width < 1 then return nil, 'not cuttable: no corridor rows' end
    local bottom = top + width - 1
    -- which side of the corridor a row is on, and whether it is a room's row
    local function side_of(y)
        if y <= top - 1 then return 'N' end
        if y >= bottom + 1 then return 'S' end
        return nil
    end
    local function in_hub(x, y) return math.abs(x) <= 1 and math.abs(y) <= 1 end
    -- the columns that hold room tiles, by side
    local cols = {N = {}, S = {}}
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            if not in_hub(x, y) then
                if y <= top - 2 then cols.N[x] = true elseif y >= bottom + 2 then cols.S[x] = true end
            end
        end
    end
    local units = {}
    for _, side in ipairs({'N', 'S'}) do
        local xs = {}
        for x in pairs(cols[side]) do table.insert(xs, x) end
        table.sort(xs)
        local i = 1
        while i <= #xs do
            local j = i
            while j < #xs and xs[j + 1] == xs[j] + 1 do j = j + 1 end
            local u = new_unit('room', xs[j] - xs[i] + 1, 0)
            u.side, u.xa, u.xb = side, xs[i], xs[j]
            u.T = side == 'N' and xf(1, 0, 0, -1, -u.xa, top - 1) or xf(1, 0, 0, 1, -u.xa, -(bottom + 1))
            table.insert(units, u)
            i = j + 1
        end
    end
    if #units == 0 then return nil, 'not cuttable: no rooms' end
    local function unit_at(x, y)
        local side = side_of(y)
        if not side then return nil end
        for _, u in ipairs(units) do
            if u.side == side and x >= u.xa and x <= u.xb then return u end
        end
        return nil
    end
    -- the tiles: hub and corridor dropped, every other one in its unit
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            if not in_hub(x, y) and side_of(y) then
                local u = unit_at(x, y)
                if not u then return nil, ('not cuttable: the tile %d,%d is in no room'):format(x, y) end
                local bx, by = xf_point(u.T, x, y)
                mark(u.tiles, bx, by)
                u.d = math.max(u.d, by)
                if by == 0 then
                    u.open = u.open or {bx, bx}
                    u.open[1], u.open[2] = math.min(u.open[1], bx), math.max(u.open[2], bx)
                end
            end
        end
    end
    -- the cells: each to the unit its tile (a rectangle's top-left) lies in
    for _, phase in ipairs(PHASES) do
        for _, c in ipairs(L[phase] or {}) do
            local u = unit_at(c.x, c.y)
            if not u or in_hub(c.x, c.y) then
                return nil, ('not cuttable: the %s cell at %d,%d is in no room'):format(phase, c.x, c.y)
            end
            local c2 = xf_cell(u.T, c)
            table.insert(u[phase], c2)
            if phase == 'rooms_at' then u.tag = tostring(c.text) end
        end
    end
    -- the layout's own slot order: nearest column first, east before west,
    -- north before south
    local function near(u) return u.xa > 0 and u.xa or -u.xb end
    table.sort(units, function(p, q)
        if near(p) ~= near(q) then return near(p) < near(q) end
        if (p.xa > 0) ~= (q.xa > 0) then return p.xa > 0 end
        return p.side == 'N' and q.side ~= 'N'
    end)
    for _, u in ipairs(units) do
        if not u.open then return nil, 'not cuttable: a room without a door' end
        local ok, why = close_unit(u)
        if not ok then return nil, 'not cuttable: ' .. why end
        u.side, u.xa, u.xb, u.T = nil, nil, nil, nil
    end
    return units
end

-- Hall mode: the one hall east of the hub.
local function cut_hall(L, entry_door)
    if not has(L.tiles, 2, 0) then return nil, 'not cuttable' end
    local ymin, ymax, xmax = math.huge, -math.huge, -math.huge
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            local hub = math.abs(x) <= 1 and math.abs(y) <= 1
            if not hub and x < 2 then return nil, 'not cuttable' end
            if not hub then
                ymin, ymax, xmax = math.min(ymin, y), math.max(ymax, y), math.max(xmax, x)
            end
        end
    end
    local T = xf(0, 1, 1, 0, -ymin, -1)          -- (x, y) -> (y - ymin, x - 1)
    local u = new_unit('hall', ymax - ymin + 1, xmax - 1)
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            if x >= 2 then mark(u.tiles, xf_point(T, x, y)) end
        end
    end
    local c = -ymin                               -- the level's own entry row, y = 0
    local wide = WIDE_HALLS[L.kind] and not entry_door and has(L.tiles, 2, -1) and has(L.tiles, 2, 1)
    u.open = wide and {c - 1, c + 1} or {c, c}
    for bx = u.open[1], u.open[2] do mark(u.tiles, bx, 0) end
    for _, phase in ipairs(PHASES) do
        for _, cell in ipairs(L[phase] or {}) do
            if cell.x < 2 then
                return nil, ('not cuttable: the %s cell at %d,%d is at the hub'):format(phase, cell.x, cell.y)
            end
            table.insert(u[phase], xf_cell(T, cell))
            if phase == 'rooms_at' then u.tag = tostring(cell.text) end
        end
    end
    for _, r in ipairs(L.halls or {}) do
        if r.x >= 2 then
            local x, y, w, h = xf_rect(T, r.x, r.y, r.w, r.h)
            table.insert(u.halls, {x = x, y = y, w = w, h = h})
        end
    end
    local door = false
    if entry_door then
        -- the fort doors its levels: a door on the opening, unless the kind has one there
        door = true
        for _, b in ipairs(u.build) do
            if b.x == c and b.y == 0 then door = false end
        end
        if door then table.insert(u.build, {x = c, y = 0, text = 'd'}) end
    end
    local ok, why = close_unit(u)
    if not ok then return nil, 'not cuttable: ' .. why end
    return {u}, door
end

-- cut(L): L = layouts.make(kind, unit_params(params)). Returns units, info;
-- or nil, why (the caller then places the level the classic way).
--
-- ai-layouts' own style (L.style) does not carry the fort's entry_door, so
-- the caller may hand it over: cut(L, params) reads params.style.entry_door
-- (an L.style.entry_door = true set by the caller works too). It is then
-- info.style.entry_door.
function cut(L, params)
    if type(L) ~= 'table' or type(L.tiles) ~= 'table' or type(L.style) ~= 'table' then
        return nil, 'not cuttable: not a layout'
    end
    if (L.orient or 0) ~= 0 then return nil, 'not cuttable: a turned level (make it with unit_params)' end
    if L.soil then return nil, 'not cuttable: farms follow the soil' end
    if L.virtual then return nil, 'not cuttable: rooms on turned arms' end
    local entry_door = L.style.entry_door == true
        or (type(params) == 'table' and type(params.style) == 'table' and params.style.entry_door == true)
    local units, why, mode
    local furniture = L.furniture
    if L.corridor ~= nil then
        if type(L.corridor) ~= 'table' or L.corridor.arms ~= nil then
            return nil, 'not cuttable: cross or ring arms (make it with unit_params)'
        end
        mode = 'room'
        units, why = cut_rooms(L)
    else
        mode = 'hall'
        units, why = cut_hall(L, entry_door)
        if units and why == true then
            furniture = {}
            for k, v in pairs(L.furniture or {}) do furniture[k] = v end
            furniture.Door = (furniture.Door or 0) + 1
        end
    end
    if not units then return nil, why or 'not cuttable' end
    if entry_door then L.style.entry_door = true end
    return units, {kind = L.kind, mode = mode, summary = L.summary, furniture = furniture,
                   style = L.style, engrave_all = L.engrave_all}
end

---------------------------------------------------------------------------
-- compose
---------------------------------------------------------------------------

-- compose(units, info, placement, opts) -> L2: the layout a floor project is
-- dug and furnished from, stair-relative (the stair at 0, 0).
--   placement   ai-floorplace's: puts[i].T is bay -> stair-relative
--   opts        hall_pri (3; 1 for an urgent level): the new hall's dig
--               priority; statues: how many of placement.statues get one;
--               door_neck: the neck's door tile is dug (the door itself is
--               the caller's, entry_door); extra_units: units that are not
--               this level's (a workshop's pile rooms), see below;
--               layouts: the ai-layouts module (a test's own)
-- Which unit a put means: puts[i].unit counts through opts.extra_units
-- first, then `units` (the pile rooms go first in the request's units); a
-- put may also carry the unit itself as a table.
function compose(units, info, placement, opts)
    opts = type(opts) == 'table' and opts or {}
    info = type(info) == 'table' and info or {}
    placement = type(placement) == 'table' and placement or {}
    local layouts = layouts_of(opts)
    local pri = math.tointeger(tonumber(opts.hall_pri)) or 3
    local all = {}
    for _, u in ipairs(type(opts.extra_units) == 'table' and opts.extra_units or {}) do table.insert(all, u) end
    for _, u in ipairs(type(units) == 'table' and units or {}) do table.insert(all, u) end

    local L2 = {kind = info.kind, dig = {}, build = {}, place = {}, zone = {}, rooms_at = {},
                smooth = {}, engrave = {}, tiles = {}, halls = {}, furniture = {}, summary = {},
                style = info.style or {smooth = 0}, engrave_all = info.engrave_all == true, orient = 0}
    for k, v in pairs(type(info.furniture) == 'table' and info.furniture or {}) do L2.furniture[k] = v end
    for k, v in pairs(type(info.summary) == 'table' and info.summary or {}) do L2.summary[k] = v end
    L2.summary.floor = placement.floor_id

    -- the new hall tiles first (and the hub's, for a floor's first project);
    -- never the stair tile, never a tile twice
    local function hall_tile(x, y)
        if (x == 0 and y == 0) or has(L2.tiles, x, y) then return end
        mark(L2.tiles, x, y)
        table.insert(L2.dig, {x = x, y = y, text = 'd' .. pri})
    end
    for _, t in ipairs(type(placement.hall) == 'table' and placement.hall or {}) do hall_tile(t.x, t.y) end
    if opts.door_neck and type(placement.neck) == 'table' then hall_tile(placement.neck.x, placement.neck.y) end

    -- then each put's unit through its T. The unit's tiles are dug as row
    -- runs made here, so a tile already given (the hall's, another unit's)
    -- is in no second cell.
    local taken = {build = {}, place = {}, zone = {}, rooms_at = {}}
    for _, put in ipairs(type(placement.puts) == 'table' and placement.puts or {}) do
        local u = type(put.unit) == 'table' and put.unit or all[put.unit]
        assert(type(u) == 'table', ('compose: no unit %s'):format(tostring(put.unit)))
        local T = put.T
        assert(type(T) == 'table', 'compose: a put without its T')
        local set = {}
        for x, col in pairs(dig_tiles(u.dig)) do
            for y in pairs(col) do
                local nx, ny = xf_point(T, x, y)
                if not (nx == 0 and ny == 0) and not has(L2.tiles, nx, ny) then mark(set, nx, ny) end
            end
        end
        for _, c in ipairs(row_runs(set)) do table.insert(L2.dig, c) end
        for x, col in pairs(set) do
            for y in pairs(col) do mark(L2.tiles, x, y) end
        end
        for _, phase in ipairs(PHASES) do
            for _, c in ipairs(u[phase] or {}) do
                local c2 = xf_cell(T, c)
                assert(not has(taken[phase], c2.x, c2.y),
                       ('compose: two %s cells at %d,%d'):format(phase, c2.x, c2.y))
                mark(taken[phase], c2.x, c2.y)
                table.insert(L2[phase], c2)
            end
        end
        for _, r in ipairs(u.halls or {}) do
            local x, y, w, h = xf_rect(T, r.x, r.y, r.w, r.h)
            table.insert(L2.halls, {x = x, y = y, w = w, h = h})
        end
    end

    -- a grand level engraves its stretch of the main hall
    if type(info.style) == 'table' and info.style.grand and type(placement.hall_rects) == 'table' then
        for _, r in ipairs(placement.hall_rects) do
            table.insert(L2.halls, {x = r.x, y = r.y, w = r.w, h = r.h})
        end
    end

    -- statues on a new node's corners
    local want = math.tointeger(tonumber(opts.statues)) or 0
    if want > 0 and type(placement.statues) == 'table' then
        local n = 0
        for _, t in ipairs(placement.statues) do
            if n >= want then break end
            if not has(taken.build, t.x, t.y) and not (t.x == 0 and t.y == 0) then
                mark(taken.build, t.x, t.y)
                table.insert(L2.build, {x = t.x, y = t.y, text = 's'})
                L2.furniture.Statue = (L2.furniture.Statue or 0) + 1
                n = n + 1
            end
        end
    end

    layouts.decorate(L2)
    layouts.set_bounds(L2)
    return L2
end
