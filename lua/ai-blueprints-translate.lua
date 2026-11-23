-- ai-blueprints-translate: the drawing turned (rotate) and translated into level
-- layouts in the exact shape ai-layouts makes them (one_zone, to_layouts).
--
-- (r9) A part of ai-blueprints, not a script of its own: ai-blueprints.lua loads it
-- into its own environment, so every name here is reqscript('ai-blueprints').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-blueprints-translate is a part of ai-blueprints; run ai-blueprints') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-blueprints-translate'] = '0.105.78'   -- (0.105.26) bumped with BRIDGE_VERSION

local ROCK_WALK, ROCK_DUG, SURF_WALK, is_letter, needs_floor, int, is_object, grids_of, cell, legend_of, item_of, N8, has_open, open_distances = PART_LOCALS.ROCK_WALK, PART_LOCALS.ROCK_DUG, PART_LOCALS.SURF_WALK, PART_LOCALS.is_letter, PART_LOCALS.needs_floor, PART_LOCALS.int, PART_LOCALS.is_object, PART_LOCALS.grids_of, PART_LOCALS.cell, PART_LOCALS.legend_of, PART_LOCALS.item_of, PART_LOCALS.N8, PART_LOCALS.has_open, PART_LOCALS.open_distances   -- (r9) the hub's and earlier parts' locals

-- q quarter turns clockwise (0-3), a real rotation of every level's grid:
-- row 0 (north) faces east after 1, south after 2, west after 3. The
-- bridge turns a drawing so row 0 faces the corridor that joins it.
-- (ai-layouts.orient_layout's four turns are mirrors and transposes, with
-- no half turn, so they can't face row 0 south.)
local function rotate_grid(rows)
    local h, w = #rows, #rows[1]
    local out = {}
    for r = 0, w - 1 do
        local chars = {}
        for c = 0, h - 1 do
            local src = rows[h - c]
            chars[c + 1] = src:sub(r + 1, r + 1)
        end
        out[r + 1] = table.concat(chars)
    end
    return out
end

function rotate(bp, q)
    q = (int(q) or 0) % 4
    local out = {}
    for k, v in pairs(bp) do out[k] = v end
    local levels = {}
    for i, lv in ipairs(bp.levels) do
        local copy = {}
        for k, v in pairs(lv) do copy[k] = v end
        local grid = lv.grid
        for _ = 1, q do grid = rotate_grid(grid) end
        copy.grid = grid
        levels[i] = copy
    end
    out.levels = levels
    return out
end

-- Greedy rectangles: each unclaimed cell with a key grows east as far as
-- the key runs, then south while the whole run matches. keys[r][c] (0-based
-- r, c) is a string or nil; (c0, r0) is the drawing's (0, 0).
local function merge(keys, h, w, c0, r0)
    local used, cells = {}, {}
    for r = 0, h - 1 do
        for c = 0, w - 1 do
            local k = keys[r] and keys[r][c]
            if k and not used[r * 64 + c] then
                local cw = 1
                while c + cw < w and keys[r][c + cw] == k and not used[r * 64 + c + cw] do cw = cw + 1 end
                local ch = 1
                while r + ch < h do
                    local row = keys[r + ch]
                    local ok = row ~= nil
                    for dc = 0, cw - 1 do
                        if ok and (row[c + dc] ~= k or used[(r + ch) * 64 + c + dc]) then ok = false end
                    end
                    if not ok then break end
                    ch = ch + 1
                end
                for dr = 0, ch - 1 do
                    for dc = 0, cw - 1 do used[(r + dr) * 64 + c + dc] = true end
                end
                table.insert(cells, {x = c - c0, y = r - r0,
                                     text = (cw == 1 and ch == 1) and k or ('%s(%dx%d)'):format(k, cw, ch)})
            end
        end
    end
    return cells
end

-- (r2 h8) A level's zone in more than one rectangle (a cross, a ring, a
-- star): Quickfort makes each cell with an extent its own zone, "separate
-- from adjacent cells, even if they have the same type" (internal/quickfort/
-- building.lua), and each m{location=temple} its own temple: B's two god
-- halls made 27 temples each, the great halls 34 dining halls. A label on
-- the zone key (m/<label>{...}) makes Quickfort merge every cell of it into
-- one zone (its global_label), so one temple.
ZONE_LABEL = 'aizone'

function one_zone(cells, level)
    if #cells <= 1 then return cells end
    local label = ZONE_LABEL .. tostring(math.tointeger(level) or 1)
    for _, c in ipairs(cells) do
        local key, rest = tostring(c.text):match('^(%a)(.*)$')
        if key and rest:sub(1, 1) ~= '/' then c.text = key .. '/' .. label .. rest end
    end
    return cells
end

local function mark(set, x, y)
    set[x] = set[x] or {}
    set[x][y] = true
end

local function bounds_of(set)
    local x1, y1, x2, y2 = math.huge, math.huge, -math.huge, -math.huge
    for x, col in pairs(set) do
        for y in pairs(col) do
            x1, x2 = math.min(x1, x), math.max(x2, x)
            y1, y2 = math.min(y1, y), math.max(y2, y)
        end
    end
    if x1 == math.huge then return {x1 = 0, y1 = 0, x2 = 0, y2 = 0} end
    return {x1 = x1, y1 = y1, x2 = x2, y2 = y2}
end

local function zone_text(bp, kind)
    local z = ZONES[kind]
    if kind == 'meeting' and type(bp.name) == 'string' and #bp.name <= 40 and bp.name:match("^[A-Za-z' ]+$") then
        return ('m{name="%s"}'):format(bp.name)
    end
    return z
end

-- The drawing as Quickfort layouts, one per level, after q quarter turns
-- (rotate). Returns {levels = {L1..Ln}, dz = {0, -1, ...} (rock) or
-- {0, 1, ...} (surface), quarter = q, cost = cost(bp)}, or nil and the
-- reasons when check_format refuses it. Each L is shaped as ai-layouts
-- makes one (kind = 'landmark'), with level 1's '@' at (0, 0) and every
-- level in the same frame (so the stairs line up):
--   dig        rock: 'd' / 'd(WxH)' over the floors (greedy rectangles), one
--              'u' 'j' 'i' 'r' cell per stair and ramp tile
--   build      doors 'd', furniture by its key, a workshop at its centre
--   place      stockpiles ('f(3x2)'), one rectangle per run of a pile type
--   zone       the bp.zone over the level's floor (rectangles; contiguous
--              ones make one zone in Quickfort), a tomb on each coffin
--   construct  surface: one 'Cw' 'Cf' 'Cr' 'Cu' 'Cd' 'Cx' 'CF' cell per tile;
--              rock (E1): a 'CF' cell per rail ('O'), built once the
--              level's openings are cut
--   open       rock (E1): one 'h' (channel) cell per opening ('*'), each with
--              its wave (1 is cut first: the farthest from the rails); cut
--              only once this level and the one below are dug
--   tiles      the dug tiles (rock; empty on the surface)
--   built      the constructed tiles (surface)
--   solid      the tiles nothing walks through once built (surface W and O)
--   footprint  every tile of the drawing that isn't '_'
--   bounds     of the tiles (rock) or the footprint (surface)
--   furniture  counts by building type, as ai-layouts counts them
--   halls      one rectangle round the level's tiles (for engraving)
--   smooth, engrave  rock only: ',' floors always; finish.smooth 1 every
--              plain floor, 2 also the '#' walls touching a dug tile, 3 or
--              engrave 'all' engraves them all; 'halls' engraves the '#'
--              walls touching ',' floors
function to_layouts(bp, q)
    local ok, reasons = check_format(bp)
    if not ok then return nil, reasons end
    q = (int(q) or 0) % 4
    local total = cost(bp)
    local rb = rotate(bp, q)
    local g = grids_of(rb)
    local n, h, w = #g, #g[1], #g[1][1]
    local surface = bp.ground == 'surface'
    local legend = legend_of(bp)
    local r0, c0
    for r = 0, h - 1 do
        local c = g[1][r + 1]:find('@', 1, true)
        if c then r0, c0 = r, c - 1 end
    end
    local zone = is_object(bp.zone) and bp.zone or nil
    local zkind = zone and zone.kind or 'none'
    local zlevel = zone and (int(zone.level) or 1) or 0
    local finish = is_object(bp.finish) and bp.finish or {}
    local smooth_lv = int(finish.smooth) or 0
    local engrave = finish.engrave or 'none'
    local out = {levels = {}, dz = {}, quarter = q, cost = total}
    for i = 1, n do
        out.dz[i] = surface and (i - 1) or -(i - 1)
        local L = {kind = 'landmark', level = i, dig = {}, build = {}, place = {}, zone = {}, construct = {},
                   open = {}, tiles = {}, built = {}, solid = {}, footprint = {}, furniture = {}, halls = {},
                   smooth = {}, engrave = {}, summary = {}, orient = 0, engrave_all = false,
                   style = {}}
        local digkeys, pilekeys, zonekeys = {}, {}, {}
        local ztext = (i == zlevel) and zone_text(bp, zkind) or ''
        local function furn(t) L.furniture[t] = (L.furniture[t] or 0) + 1 end
        local dist, far = {}, 0
        if not surface and has_open(g[i]) then
            dist, far = open_distances(function(c, r) return cell(g, i, c, r) end, h, w)
        end
        local cuts = {}
        for r = 0, h - 1 do
            digkeys[r], pilekeys[r], zonekeys[r] = {}, {}, {}
            local row = g[i][r + 1]
            for c = 0, w - 1 do
                local ch = row:sub(c + 1, c + 1)
                local x, y = c - c0, r - r0
                if ch ~= '_' then mark(L.footprint, x, y) end
                local name = is_letter(ch) and item_of(legend, ch) or nil
                local floorish
                if surface then
                    floorish = SURF_WALK[ch] or is_letter(ch)
                    local below = i > 1 and g[i - 1][r + 1]:sub(c + 1, c + 1) or nil
                    local key = CONSTRUCT[ch] or (needs_floor(i, ch, below) and 'Cf') or nil
                    if key then
                        table.insert(L.construct, {x = x, y = y, text = key})
                        mark(L.built, x, y)
                        if ch == 'W' or ch == 'O' then mark(L.solid, x, y) end
                    end
                else
                    local dug = ROCK_DUG[ch] or is_letter(ch)
                    floorish = dug and ch ~= '*' and ch ~= 'O'
                    if dug then
                        mark(L.tiles, x, y)
                        if DIG_KEY[ch] then
                            table.insert(L.dig, {x = x, y = y, text = DIG_KEY[ch]})
                        else
                            digkeys[r][c] = 'd'
                        end
                    end
                    if ch == 'O' then
                        table.insert(L.construct, {x = x, y = y, text = RAIL_KEY})
                        mark(L.built, x, y)
                        mark(L.solid, x, y)
                    elseif ch == '*' then
                        local d = dist[r * 64 + c] or far
                        table.insert(cuts, {x = x, y = y, text = OPEN_KEY, wave = far - d + 1})
                    end
                end
                if ch == '+' then
                    table.insert(L.build, {x = x, y = y, text = 'd'})
                    furn('Door')
                elseif name then
                    local kind = ITEM_KIND[name]
                    if kind == 'pile' then
                        pilekeys[r][c] = ITEMS[name]
                    else
                        table.insert(L.build, {x = x, y = y, text = ITEMS[name]})
                        furn(kind == 'furniture' and (FURNITURE_TYPE[name] or name) or name)
                    end
                end
                if ztext ~= '' and floorish then
                    if zkind == 'tomb' then
                        if name == 'Coffin' then table.insert(L.zone, {x = x, y = y, text = ztext}) end
                    else
                        zonekeys[r][c] = ztext
                    end
                end
            end
        end
        -- the floors first, then the stairs and ramps (each one cell)
        table.sort(cuts, function(a, b)
            if a.wave ~= b.wave then return a.wave < b.wave end
            if a.y ~= b.y then return a.y < b.y end
            return a.x < b.x
        end)
        L.open = cuts
        local floors = merge(digkeys, h, w, c0, r0)
        for _, cc in ipairs(L.dig) do table.insert(floors, cc) end
        L.dig = floors
        L.place = merge(pilekeys, h, w, c0, r0)
        if zkind ~= 'tomb' then L.zone = one_zone(merge(zonekeys, h, w, c0, r0), i) end
        -- smoothing and engraving (rock)
        if not surface then
            local sm_floor, en_floor, walls = {}, {}, {}
            local seen_wall = {}
            for r = 0, h - 1 do
                local row = g[i][r + 1]
                for c = 0, w - 1 do
                    local ch = row:sub(c + 1, c + 1)
                    local x, y = c - c0, r - r0
                    local plain = ch == '.' or ch == ',' or ch == '@'
                    if plain and (ch == ',' or smooth_lv >= 1 or engrave == 'all') then
                        table.insert(sm_floor, {x = x, y = y, text = 's'})
                    end
                    if plain and (ch == ',' or engrave == 'all') then
                        table.insert(en_floor, {x = x, y = y, text = 'e'})
                    end
                    if ch == '#' then
                        local touches, touches_engraved = false, false
                        for _, d in ipairs(N8) do
                            local nc = cell(g, i, c + d[1], r + d[2])
                            if nc and (ROCK_WALK[nc] or is_letter(nc)) then touches = true end
                            if nc == ',' then touches_engraved = true end
                        end
                        if touches then table.insert(walls, {x = x, y = y, e = touches_engraved}) end
                    end
                end
            end
            for _, cc in ipairs(sm_floor) do table.insert(L.smooth, cc) end
            for _, wl in ipairs(walls) do
                local eng = smooth_lv >= 3 or engrave == 'all' or (engrave == 'halls' and wl.e)
                if smooth_lv >= 2 or eng then table.insert(L.smooth, {x = wl.x, y = wl.y, text = 's'}) end
            end
            for _, cc in ipairs(en_floor) do table.insert(L.engrave, cc) end
            for _, wl in ipairs(walls) do
                local eng = smooth_lv >= 3 or engrave == 'all' or (engrave == 'halls' and wl.e)
                if eng then table.insert(L.engrave, {x = wl.x, y = wl.y, text = 'e'}) end
            end
        end
        L.bounds = bounds_of(surface and L.footprint or L.tiles)
        local b = L.bounds
        L.halls = {{x = b.x1, y = b.y1, w = b.x2 - b.x1 + 1, h = b.y2 - b.y1 + 1}}
        local count, rails = 0, 0
        for _, col in pairs(surface and L.built or L.tiles) do for _ in pairs(col) do count = count + 1 end end
        if not surface then rails = #L.construct end
        L.summary = {landmark = bp.name, purpose = bp.purpose, level = i, levels = n,
                     dug = (not surface) and count or 0, built = surface and count or rails,
                     opened = #cuts > 0 and #cuts or nil}
        out.levels[i] = L
    end
    return out
end

-- (r9) this part's locals the next part uses
PART_LOCALS.mark = mark
