-- Joining the fort's areas on one level (0.104.107b, phase 12g, the player's
-- findings after a 38-year run: areas side by side on the same level met only
-- through the stairs, and corridors ended in rock).
--
-- On a level the AI has built on, the fort's open space falls into separate
-- areas (2D: what a dwarf can walk to without stairs). Two areas whose
-- corridors or halls come within MAX_JOIN tiles through solid rock are joined
-- by a corridor 2 wide (1 wide where it meets each area: a doorway), straight
-- or with one bend. Dead-end corridors are preferred as its ends.
--
-- Never digs into a room: both ends are passage tiles (no building, no zone),
-- every tile dug is plain natural rock, and nothing it digs opens onto any
-- other space than the two ends. One corridor a call.
--
-- The core (components, plan_join) takes a tile reader T(x, y) so it can be
-- tested without the game: T returns nil off the map, else
--   {open = walkable fort floor, rock = safe natural rock to dig,
--    passage = open with no building or zone on it, danger = water, magma,
--    aquifer or warm stone}
--@ module = true

MAX_JOIN = 20              -- longest corridor between two areas (tiles)
MAX_AREA = 8000            -- tiles read per area
MAX_EDGE = 300             -- edge tiles kept per area
MAX_TRIES = 40             -- routes tried per call
MAX_AREAS = 12
DEAD_END_BONUS = 4         -- a dead end counts as this many tiles nearer
SCAN_SECONDS = 2.0

local ORTHO = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
local function key(x, y) return y * 4096 + x end

-- The separate areas holding the seed tiles. Returns areas, owner (key -> area index).
function components(T, seeds, cap)
    cap = cap or MAX_AREA
    local areas, owner = {}, {}
    for _, s in ipairs(seeds) do
        local k = key(s.x, s.y)
        local t = T(s.x, s.y)
        if t and t.open and not owner[k] and #areas < MAX_AREAS then
            local id = #areas + 1
            local area = {id = id, tiles = {}}
            owner[k] = id
            local queue, head = {{s.x, s.y}}, 1
            while head <= #queue and #area.tiles < cap do
                local x, y = queue[head][1], queue[head][2]
                head = head + 1
                table.insert(area.tiles, {x = x, y = y})
                for _, d in ipairs(ORTHO) do
                    local nx, ny = x + d[1], y + d[2]
                    local nk = key(nx, ny)
                    if not owner[nk] then
                        local nt = T(nx, ny)
                        if nt and nt.open then
                            owner[nk] = id
                            table.insert(queue, {nx, ny})
                        end
                    end
                end
            end
            area.capped = head <= #queue
            table.insert(areas, area)
        end
    end
    return areas, owner
end

-- An area's passage tiles with rock beside them (where a corridor can leave),
-- each {x, y, dead = a dead end (one open tile beside it)}.
function edge_tiles(T, area)
    local out, dead_ends = {}, 0
    for _, p in ipairs(area.tiles) do
        local t = T(p.x, p.y)
        if t and t.passage then
            local open, rock = 0, false
            for _, d in ipairs(ORTHO) do
                local n = T(p.x + d[1], p.y + d[2])
                if n and n.open then open = open + 1 end
                if n and n.rock then rock = true end
            end
            if rock then
                local dead = open == 1
                if dead then dead_ends = dead_ends + 1 end
                table.insert(out, {x = p.x, y = p.y, dead = dead})
            end
        end
    end
    if #out > MAX_EDGE then
        -- keep the dead ends, then an even sample of the rest
        local keep, rest = {}, {}
        for _, e in ipairs(out) do table.insert(e.dead and keep or rest, e) end
        local step = math.max(1, #rest / math.max(1, MAX_EDGE - #keep))
        local i = 1
        while i <= #rest and #keep < MAX_EDGE do
            table.insert(keep, rest[math.floor(i)])
            i = i + step
        end
        out = keep
    end
    return out, dead_ends
end

-- The tiles of a corridor from a to b (both open, not dug), straight or with
-- one bend (x first or y first), 2 wide but for its first and last tiles.
-- Returns {tiles = {{x, y}}, length} or nil, why.
function route(T, a, b, owner, ia, ib, y_first)
    local path = {}
    local x, y = a.x, a.y
    local function walk(dx, dy, tx, ty)
        while x ~= tx or y ~= ty do
            x, y = x + dx, y + dy
            if x == b.x and y == b.y then return end
            table.insert(path, {x = x, y = y, dx = dx, dy = dy})
        end
    end
    local sx = b.x > a.x and 1 or -1
    local sy = b.y > a.y and 1 or -1
    if y_first then
        if b.y ~= a.y then walk(0, sy, a.x, b.y) end
        if b.x ~= a.x then walk(sx, 0, b.x, b.y) end
    else
        if b.x ~= a.x then walk(sx, 0, b.x, a.y) end
        if b.y ~= a.y then walk(0, sy, b.x, b.y) end
    end
    if #path == 0 then return nil, 'the areas already touch' end
    local dug, list = {}, {}
    local function add(px, py)
        local k = key(px, py)
        if not dug[k] then dug[k] = true; table.insert(list, {x = px, y = py}) end
    end
    for i, p in ipairs(path) do
        add(p.x, p.y)
        if i > 1 and i < #path then add(p.x - p.dy, p.y + p.dx) end      -- the second row
    end
    for _, p in ipairs(list) do
        local t = T(p.x, p.y)
        if not t or not t.rock then return nil, ('not plain rock at x%d y%d'):format(p.x, p.y) end
    end
    -- nothing but the two ends may open onto it
    for _, p in ipairs(list) do
        for dx = -1, 1 do
            for dy = -1, 1 do
                local nx, ny = p.x + dx, p.y + dy
                if not dug[key(nx, ny)] then
                    local n = T(nx, ny)
                    if not n then return nil, 'off the map' end
                    if n.danger then return nil, ('water, magma or warm stone beside x%d y%d'):format(nx, ny) end
                    if n.open then
                        local o = owner[key(nx, ny)]
                        local near_a = o == ia and math.max(math.abs(nx - a.x), math.abs(ny - a.y)) <= 1
                        local near_b = o == ib and math.max(math.abs(nx - b.x), math.abs(ny - b.y)) <= 1
                        if not near_a and not near_b then
                            return nil, ('it would open onto other space at x%d y%d'):format(nx, ny)
                        end
                    end
                end
            end
        end
    end
    return {tiles = list, length = #path}
end

-- The best corridor joining two of the areas, or nil, why. stats: areas, dead ends.
function plan_join(T, seeds)
    local areas, owner = components(T, seeds)
    local stats = {areas = #areas, dead_ends = 0}
    if #areas < 2 then return nil, 'one area', stats end
    local edges = {}
    for i, a in ipairs(areas) do
        local e, dead = edge_tiles(T, a)
        edges[i] = e
        stats.dead_ends = stats.dead_ends + dead
    end
    local cands = {}
    for i = 1, #areas - 1 do
        for j = i + 1, #areas do
            for _, a in ipairs(edges[i]) do
                for _, b in ipairs(edges[j]) do
                    local dist = math.abs(a.x - b.x) + math.abs(a.y - b.y)
                    if dist >= 2 and dist <= MAX_JOIN + 1 then
                        local score = dist - (a.dead and DEAD_END_BONUS or 0) - (b.dead and DEAD_END_BONUS or 0)
                        table.insert(cands, {a = a, b = b, ia = i, ib = j, score = score})
                    end
                end
            end
        end
    end
    if #cands == 0 then return nil, ('%d areas, none within %d tiles of another'):format(#areas, MAX_JOIN), stats end
    table.sort(cands, function(p, q)
        if p.score ~= q.score then return p.score < q.score end
        if p.a.y ~= q.a.y then return p.a.y < q.a.y end
        if p.a.x ~= q.a.x then return p.a.x < q.a.x end
        if p.b.y ~= q.b.y then return p.b.y < q.b.y end
        return p.b.x < q.b.x
    end)
    local last
    for n = 1, math.min(#cands, MAX_TRIES) do
        local c = cands[n]
        for _, yf in ipairs({false, true}) do
            local r, why = route(T, c.a, c.b, owner, c.ia, c.ib, yf)
            if r then
                r.from, r.to = {x = c.a.x, y = c.a.y}, {x = c.b.x, y = c.b.y}
                r.dead_end = c.a.dead or c.b.dead
                return r, nil, stats
            end
            last = why
        end
    end
    return nil, ('%d areas; no safe way between them (%s)'):format(#areas, tostring(last)), stats
end

---------------------------------------------------------------------------
-- In the game
---------------------------------------------------------------------------

local OPEN_SHAPES = {FLOOR = true, STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true,
                     BOULDER = true, PEBBLES = true, TWIG = true, SAPLING = true, SHRUB = true}

function game_reader(z)
    local B = reqscript('ai-builder')
    local cache = {}
    return function(x, y)
        local k = key(x, y)
        local v = cache[k]
        if v ~= nil then return v or nil end
        local t = B.tile_info(x, y, z)
        if not t then cache[k] = false return nil end
        local open = OPEN_SHAPES[t.shape] == true and not t.outside and not t.feature and not t.liquid
        local passage = false
        if open and not t.building then
            local pos = xyz2pos(x, y, z)
            local okz, zones = pcall(dfhack.buildings.findCivzonesAt, pos)
            local okb, bld = pcall(dfhack.buildings.findAtTile, pos)          -- a stockpile, a workshop
            passage = not (okz and zones and #zones > 0) and not (okb and bld)
        end
        v = {open = open, passage = passage, rock = (B.natural_wall(t)) == true,
             danger = t.liquid or t.aquifer or t.warm or false}
        cache[k] = v
        return v
    end
end

local function designate(tiles, z)
    local n = 0
    for _, p in ipairs(tiles) do
        local d = dfhack.maps.getTileFlags(p.x, p.y, z)
        if d and d.dig == df.tile_dig_designation.No then
            d.dig = df.tile_dig_designation.Default
            local block = dfhack.maps.getTileBlock(p.x, p.y, z)
            if block then block.flags.designated = true end
            n = n + 1
        end
    end
    return n
end

JOIN_CURSOR = JOIN_CURSOR or 0

-- One call: the next levels the AI built on, in turn, until a corridor is
-- dug or the time is up. {ok, joined = {z, from, to, length, dead_end} or nil,
-- scanned, wrapped (every level looked at since the last join)}.
function join_levels(dry_run)
    local B = reqscript('ai-builder')
    local seeds_by_z, zs = {}, {}
    for _, p in ipairs(B.load_projects().list or {}) do
        local z = math.tointeger(p.z)
        if z and p.phase ~= 'dig' then
            if not seeds_by_z[z] then seeds_by_z[z] = {}; table.insert(zs, z) end
            for _, s in ipairs({p.anchor, p.stair}) do
                if type(s) == 'table' and math.tointeger(s.x) and math.tointeger(s.y) then
                    table.insert(seeds_by_z[z], {x = math.tointeger(s.x), y = math.tointeger(s.y)})
                end
            end
        end
    end
    table.sort(zs)
    if #zs == 0 then return {ok = true, scanned = 0, wrapped = true, note = 'no levels built yet'} end
    local started, scanned, notes, dead = os.clock(), 0, {}, 0
    local wrapped = false
    while scanned < #zs and os.clock() - started < SCAN_SECONDS do
        JOIN_CURSOR = JOIN_CURSOR % #zs + 1
        if JOIN_CURSOR == #zs then wrapped = true end
        local z = zs[JOIN_CURSOR]
        scanned = scanned + 1
        local r, why, stats = plan_join(game_reader(z), seeds_by_z[z])
        dead = dead + (stats and stats.dead_ends or 0)
        if r then
            local n = dry_run and #r.tiles or designate(r.tiles, z)
            return {ok = true, scanned = scanned, dead_ends = dead,
                    joined = {z = z, from = r.from, to = r.to, length = r.length, tiles = n,
                              dead_end = r.dead_end == true}, dry_run = dry_run or nil}
        end
        if stats and stats.areas > 1 and #notes < 3 then table.insert(notes, ('z%d: %s'):format(z, why)) end
    end
    return {ok = true, scanned = scanned, wrapped = wrapped, dead_ends = dead,
            note = #notes > 0 and table.concat(notes, '; ') or nil}
end
