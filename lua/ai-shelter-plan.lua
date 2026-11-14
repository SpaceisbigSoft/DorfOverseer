-- (0.105.45, Phase 11 brief (c)) The civilians' shelter away from the way
-- the threat comes, and the squads between them and it.
--
-- F (27 Galena y257): a hill titan came in and killed 42 in the shelter,
-- where the civilians and two squads waited together. The shelter was the
-- whole fort (less the margins round the open entrances, 0.105.23), so the
-- titan walked into it, and the squads were inside it with the civilians.
--
-- Here, while a great danger or a siege is on the map:
--   * the way in of each danger: the entrance nearest it (the gate scan's,
--     ai-gates GATES.entrances), or its own tile when it already stands
--     inside the fort;
--   * the fort's levels as shelter candidates (the inside tiles of each
--     level, with the drink, wells and food on it); for the few farthest
--     from the threat, a walk (breadth-first over the walkable tiles, doors
--     ignored: a building destroyer breaks them) gives the threat's walk to
--     the level and every civilian's, so the brain picks the level the
--     threat reaches last and never one it reaches before the civilians;
--   * for each candidate, the choke points on the threat's walk to it (a
--     corridor or stair just inside the gate the threat faces) where the
--     squads stand between, and the barracks as the fall-back;
--   * the shelter now in use (the AI's pick, kept in the site data) and how
--     far each danger inside the fort is from it by walk.
-- The brain (brain/planner_shelter.py) chooses; `shelter_pick` redraws the
-- AI shelter over the chosen levels (ai-society fill_shelter's `only`), and
-- the squads get a station order (ai-military station).
--
-- The pure part (keys, the walk, the path, the chokes, plan()) needs no
-- game and is tested through lupa (tests/test_h5_shelter_plan.py).
--@module = true

local U = reqscript('ai-util')

-- a tile's key: x, y < 1024 (DF's maps are at most 768 across), z < 1024
function K(x, y, z) return x + y * 1024 + z * 1048576 end
function unkey(k)
    local z = k // 1048576
    local r = k - z * 1048576
    local y = r // 1024
    return r - y * 1024, y, z
end

-- a grid entry's flags
WALK, UP, DOWN, RAMP, INSIDE = 1, 2, 4, 8, 16

SHELTER_PLAN_MAX_BFS = 6          -- candidate levels walked at most
SHELTER_PLAN_CAP = 150000         -- tiles one walk reaches at most
SHELTER_PLAN_LEVEL_MIN = 20       -- inside tiles a level needs to be a candidate
SHELTER_PLAN_NEAR = 4             -- outside/cavern tiles kept this close to a way in (to join it to the inside)
SHELTER_PLAN_TICKS = 600          -- the plan walked again at most this often (half a game day)...
                                  -- ...or at once when the ways in or the AI's pick change
SHELTER_PLAN_CIVS = 300           -- civilians measured at most
CHOKE_MIN_FROM_SOURCE = 2         -- a choke this many steps in from the threat's way in, at least
CHOKE_MAX_WIDTH = 4               -- a choke's walkable neighbours on its level, at most (a corridor, a stair)
SHELTER_PICK_KEY = 'ai-overseer/shelter-pick'
SHELTER_PICK_MAX_TICKS = 10 * 1200   -- a pick older than this is dropped (the whole fort again)

local function has(f, bit) return f ~= nil and (f // bit) % 2 == 1 end

-- The walkable neighbours of k: the 8 round it on its level; up and down a
-- stair (an up stair under a down stair); a ramp up to the 8 round the tile
-- above it, and back down. Calls fn(nk) for each.
function neighbours(grid, k, fn)
    local f = grid[k]
    if not f then return end
    local x, y, z = unkey(k)
    for dy = -1, 1 do
        for dx = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                local nx, ny = x + dx, y + dy
                if nx >= 0 and ny >= 0 then
                    local nk = K(nx, ny, z)
                    if grid[nk] then fn(nk) end
                    -- a ramp here leads up to the tiles round the one above it
                    if has(f, RAMP) then
                        local uk = K(nx, ny, z + 1)
                        if grid[uk] then fn(uk) end
                    end
                    -- a ramp below, beside us, leads down
                    if z > 0 then
                        local dk = K(nx, ny, z - 1)
                        if has(grid[dk], RAMP) then fn(dk) end
                    end
                end
            end
        end
    end
    if has(f, UP) then
        local uk = K(x, y, z + 1)
        if has(grid[uk], DOWN) then fn(uk) end
    end
    if has(f, DOWN) and z > 0 then
        local dk = K(x, y, z - 1)
        if has(grid[dk], UP) then fn(dk) end
    end
end

-- Breadth-first walk from the seed keys: key -> steps, how many reached,
-- whether the cap stopped it.
function bfs(grid, seeds, cap)
    cap = cap or SHELTER_PLAN_CAP
    local dist, q, head, n = {}, {}, 1, 0
    for _, k in ipairs(seeds) do
        if grid[k] and not dist[k] then dist[k] = 0; n = n + 1; q[n] = k end
    end
    local capped = false
    while head <= n do
        local k = q[head]
        head = head + 1
        local d = dist[k] + 1
        neighbours(grid, k, function(nk)
            if not dist[nk] then
                if n >= cap then capped = true; return end
                dist[nk] = d
                n = n + 1
                q[n] = nk
            end
        end)
        if capped then break end
    end
    return dist, n, capped
end

-- The path from k down the walk's distances to a seed: a list of keys, k first.
function path_to(grid, dist, k)
    local out = {}
    if not dist[k] then return out end
    local cur, guard = k, 0
    while cur and guard < 100000 do
        guard = guard + 1
        table.insert(out, cur)
        local d = dist[cur]
        if d == 0 then break end
        local nxt
        neighbours(grid, cur, function(nk)
            if not nxt and dist[nk] == d - 1 then nxt = nk end
        end)
        cur = nxt
    end
    return out
end

-- How open a tile is: its walkable neighbours on its own level (a corridor
-- has 2-4, a room's floor 8); a stair counts as narrow (1 below the count)
function width_at(grid, k)
    local x, y, z = unkey(k)
    local n = 0
    for dy = -1, 1 do
        for dx = -1, 1 do
            if (dx ~= 0 or dy ~= 0) and x + dx >= 0 and y + dy >= 0 and grid[K(x + dx, y + dy, z)] then n = n + 1 end
        end
    end
    local f = grid[k]
    if has(f, UP) or has(f, DOWN) then n = math.max(0, n - 1) end
    return n
end

-- The choke points on the threat's path from src to the shelter (dist: the
-- walk from the shelter): tiles inside the fort, at least min_src steps from
-- the way in and min_to steps from the shelter, no wider than max_w. The
-- first (nearest the threat: just inside the gate it faces) and the
-- narrowest, at most 3, each {x, y, z, from_src, to_shelter, width}; and the
-- path's length.
function chokes(grid, dist, src, opts)
    opts = opts or {}
    local min_src = opts.min_src or CHOKE_MIN_FROM_SOURCE
    local min_to = opts.min_to or 6
    local max_w = opts.max_w or CHOKE_MAX_WIDTH
    local path = path_to(grid, dist, src)
    local found = {}
    for i, k in ipairs(path) do
        local from_src, to = i - 1, dist[k]
        if from_src >= min_src and to >= min_to and has(grid[k], INSIDE) then
            local w = width_at(grid, k)
            if w <= max_w then
                local x, y, z = unkey(k)
                table.insert(found, {x = x, y = y, z = z, from_src = from_src, to_shelter = to, width = w})
            end
        end
    end
    local out, seen = {}, {}
    local function add(c)
        if c and not seen[c] and #out < 3 then seen[c] = true; table.insert(out, c) end
    end
    add(found[1])
    local narrow
    for _, c in ipairs(found) do
        if not narrow or c.width < narrow.width then narrow = c end
    end
    add(narrow)
    -- a stair on the way (the narrowest kind of choke), if not one already
    for _, c in ipairs(found) do
        local f = grid[K(c.x, c.y, c.z)]
        if (has(f, UP) or has(f, DOWN)) and #out < 3 then add(c); break end
    end
    return out, #path
end

local function sorted_copy(t)
    local c = {}
    for i, v in ipairs(t) do c[i] = v end
    table.sort(c)
    return c
end

local function quantile(sorted, q)
    if #sorted == 0 then return nil end
    local i = math.max(1, math.min(#sorted, math.ceil(#sorted * q)))
    return sorted[i]
end

-- The plan, from a grid: cands {z, seeds = {keys}, ...} (each walked),
-- sources {key, ...} (the dangers' ways in), civs {key, ...} (the civilians'
-- tiles), inside {key, ...} (the dangers inside the fort). Each candidate
-- gets d_threat (the nearest source's walk to it; nil: none reaches it),
-- src (that source's index), civ_med / civ_p90 / civ_max (their walk to
-- it), civ_reached, civ_late (civilians the threat would beat there: their
-- walk at least the threat's), d_inside (the nearest danger inside's walk),
-- chokes and path. keep_dist: the candidate whose walk is kept (returned).
function plan(grid, cands, sources, civs, inside, opts)
    opts = opts or {}
    local kept
    for _, c in ipairs(cands) do
        local dist, n, capped = bfs(grid, c.seeds, opts.cap)
        c.reached, c.capped = n, capped or nil
        local best, bi
        for i, s in ipairs(sources) do
            local d = dist[s]
            if d and (not best or d < best) then best, bi = d, i end
        end
        c.d_threat, c.src = best, bi
        local ds, unreached = {}, 0
        for _, k in ipairs(civs) do
            local d = dist[k]
            if d then table.insert(ds, d) else unreached = unreached + 1 end
        end
        ds = sorted_copy(ds)
        c.civ_reached, c.civ_unreached = #ds, unreached
        c.civ_med, c.civ_p90, c.civ_max = quantile(ds, 0.5), quantile(ds, 0.9), ds[#ds]
        local late = 0
        if best then
            for _, d in ipairs(ds) do if d >= best then late = late + 1 end end
        end
        c.civ_late = late
        local din
        for _, k in ipairs(inside or {}) do
            local d = dist[k]
            if d and (not din or d < din) then din = d end
        end
        c.d_inside = din
        if bi then
            local okc, ch, plen = pcall(chokes, grid, dist, sources[bi], opts.choke)
            if okc then c.chokes, c.path = ch, plen end
        end
        c.seeds = nil
        if opts.keep and opts.keep == c.key then kept = dist end
    end
    return cands, kept
end

-- --- the game's side ---------------------------------------------------------------

local WALK_SHAPES = {FLOOR = WALK, STAIR_UP = WALK + UP, STAIR_DOWN = WALK + DOWN,
                     STAIR_UPDOWN = WALK + UP + DOWN, RAMP = WALK + RAMP, RAMP_TOP = WALK,
                     SAPLING = WALK, SHRUB = WALK, PEBBLES = WALK, BOULDER = WALK, TWIG = WALK,
                     BROOK_TOP = WALK}

-- The great dangers and invaders on the map, free and alive: {id, name, x, y, z, great, invader}
function dangers(txt)
    local out = {}
    local list = (U.REPORT_CTX and U.units_active) and U.units_active() or df.global.world.units.active
    for _, u in ipairs(list) do
        local ok, row = pcall(function()
            if not dfhack.units.isActive(u) or dfhack.units.isDead(u) or dfhack.units.isCitizen(u, true) then return nil end
            if u.flags1.caged or u.flags1.chained then return nil end
            if not dfhack.units.isDanger(u) then return nil end
            local great, inv = dfhack.units.isGreatDanger(u) == true, dfhack.units.isInvader(u) == true
            if not (great or inv) then return nil end
            return {id = u.id, x = u.pos.x, y = u.pos.y, z = u.pos.z, great = great or nil, invader = inv or nil,
                    name = (txt or tostring)(dfhack.units.getReadableName(u))}
        end)
        if ok and row and row.x >= 0 then table.insert(out, row) end
    end
    return out
end

local function entrances()
    local ok, G = pcall(function() return reqscript('ai-gates').GATES end)
    if not ok or type(G) ~= 'table' or not G.scanned or type(G.entrances) ~= 'table' then return {} end
    local out = {}
    for _, e in ipairs(G.entrances) do
        local okp = pcall(function() return e.x + e.y + e.z end)
        if okp then table.insert(out, {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z, sealed = e.sealed or nil}) end
    end
    return out
end

local function straight(a, b) return math.max(math.abs(a.x - b.x), math.abs(a.y - b.y)) + 3 * math.abs(a.z - b.z) end

-- The walkable tiles from z lo to hi: inside ones (not outside, not a cavern
-- or other feature), and outside or cavern ones only near the given points
-- (to join a way in to the inside). Deep water (4+) and magma are no way.
function build_grid(lo, hi, points)
    local grid = {}
    local near = SHELTER_PLAN_NEAR
    local per_z = {}
    for _, p in ipairs(points or {}) do
        per_z[p.z] = per_z[p.z] or {}
        table.insert(per_z[p.z], p)
    end
    local function close(x, y, z)
        for zz = z - 1, z + 1 do
            for _, p in ipairs(per_z[zz] or {}) do
                if math.abs(p.x - x) <= near and math.abs(p.y - y) <= near then return true end
            end
        end
        return false
    end
    local counts = {}
    for _, block in ipairs(df.global.world.map.map_blocks) do
        local z = block.map_pos.z
        if z >= lo and z <= hi then
            local bx, by = block.map_pos.x, block.map_pos.y
            for x = 0, 15 do
                for y = 0, 15 do
                    local d = block.designation[x][y]
                    if not d.hidden then
                        local shape = df.tiletype_shape[df.tiletype.attrs[block.tiletype[x][y]].shape]
                        local f = WALK_SHAPES[shape]
                        if f and d.flow_size > 0 and (d.flow_size >= 4 or d.liquid_type == true or d.liquid_type == 1) then
                            f = nil
                        end
                        if f then
                            local ins = not d.outside and not d.feature_local and not d.feature_global
                            if ins then
                                grid[K(bx + x, by + y, z)] = f + INSIDE
                                counts[z] = (counts[z] or 0) + 1
                            elseif close(bx + x, by + y, z) then
                                grid[K(bx + x, by + y, z)] = f
                            end
                        end
                    end
                end
            end
        end
    end
    return grid, counts
end

-- the grid tile at p, else the nearest within r on its level (a unit on a
-- tile the walk can't take: a door, a workshop's tile)
local function grid_key_near(grid, p, r)
    local k = K(p.x, p.y, p.z)
    if grid[k] then return k end
    for rr = 1, r or 2 do
        for dy = -rr, rr do
            for dx = -rr, rr do
                local nk = K(p.x + dx, p.y + dy, p.z)
                if p.x + dx >= 0 and p.y + dy >= 0 and grid[nk] then return nk end
            end
        end
    end
    return nil
end

-- The AI's pick now: {levels = {z...}, tick, why, way_in} or nil (the whole fort)
function current_pick()
    local p = U.site_get(SHELTER_PICK_KEY, nil)
    if type(p) ~= 'table' or type(p.levels) ~= 'table' or #p.levels == 0 then return nil end
    local okn, now = pcall(U.abs_tick)
    if okn and type(p.tick) == 'number' and now - p.tick > SHELTER_PICK_MAX_TICKS then return nil end
    return p
end

-- The levels of the pick as a set (ai-society fill_shelter's `only`), or nil
function pick_levels()
    local p = current_pick()
    if not p then return nil end
    local out = {}
    for _, z in ipairs(p.levels) do
        local n = tonumber(z)
        if n then out[math.floor(n)] = true end
    end
    return next(out) and out or nil
end

-- the barracks: {id, x, y, z, squads} (a walkable tile in it when there is one)
local function barracks(grid)
    local out = {}
    local okl, list = pcall(function() return df.global.world.buildings.other.ZONE_BARRACKS end)
    for _, b in ipairs(okl and list or {}) do
        pcall(function()
            local squads = {}
            for _, info in ipairs(b.squad_room_info) do table.insert(squads, info.squad_id) end
            local p = {x = b.centerx, y = b.centery, z = b.z}
            local k = grid_key_near(grid, p, 3)
            if k then p.x, p.y, p.z = unkey(k) end
            table.insert(out, {id = b.id, x = p.x, y = p.y, z = p.z, squads = squads, walkable = k ~= nil or nil})
        end)
    end
    return out
end

local MEMO = nil     -- {tick, sig, grid, cands, ..., keep_dist, keep_key}

local function supplies_by_level()
    local by = {}
    local ok, S = pcall(reqscript, 'ai-society')
    if not ok or not S.shelter_supplies then return by end
    local okw, water, units, wells, food = pcall(S.shelter_supplies)
    if not okw then return by end
    local function lvl(z)
        by[z] = by[z] or {drink = 0, wells = 0, food = 0}
        return by[z]
    end
    for k, n in pairs(units or {}) do
        local z = tonumber(tostring(k):match(',(%-?%d+)$'))
        if z then lvl(z).drink = lvl(z).drink + n end
    end
    for _, w in ipairs(wells or {}) do lvl(w.z).wells = lvl(w.z).wells + 1 end
    for k, n in pairs(food or {}) do
        local z = tonumber(tostring(k):match(',(%-?%d+)$'))
        if z then lvl(z).food = lvl(z).food + n end
    end
    return by
end

-- The report section `shelter_plan`.
function report(txt)
    local out = {current = nil}
    local cur = current_pick()
    if cur then out.current = {levels = cur.levels, why = cur.why, way_in = cur.way_in, tick = cur.tick} end
    local okd, list = pcall(dangers, txt)
    list = okd and list or {}
    if #list == 0 then
        out.danger = false
        MEMO = nil
        return out
    end
    out.danger = true
    local S = reqscript('ai-society')
    local lo, hi = S.shelter_level_range()
    if not lo then out.error = 'no citizens to measure from'; return out end
    local ents = entrances()
    -- each danger's way in: the nearest entrance (straight), cap 8 ways
    local ways, way_by = {}, {}
    for _, t in ipairs(list) do
        local best, bd
        for _, e in ipairs(ents) do
            local d = straight(t, e)
            if not bd or d < bd then best, bd = e, d end
        end
        t.way_in = best and best.id or nil
        if best and not way_by[best.id] and #ways < 8 then way_by[best.id] = true; table.insert(ways, best) end
    end
    local points = {}
    for _, e in ipairs(ways) do table.insert(points, e) end
    for _, t in ipairs(list) do table.insert(points, t) end
    local zlo, zhi = lo, hi
    for _, p in ipairs(points) do
        if p.z >= lo - 20 and p.z <= hi + 20 then zlo, zhi = math.min(zlo, p.z), math.max(zhi, p.z) end
    end
    local now = U.abs_tick()
    local sig = {}
    for _, e in ipairs(ways) do table.insert(sig, tostring(e.id)) end
    table.sort(sig)
    local pick_sig = cur and table.concat(cur.levels, ',') or 'whole'
    local signature = table.concat(sig, ',') .. '|' .. pick_sig .. '|' .. lo .. '-' .. hi
    local m = MEMO
    if not (m and m.sig == signature and now >= m.tick and now - m.tick < SHELTER_PLAN_TICKS) then
        local grid, counts = build_grid(zlo, zhi, points)
        -- the sources: the ways in (on the grid)
        local sources, src_rows = {}, {}
        for _, e in ipairs(ways) do
            local k = grid_key_near(grid, e, 2)
            if k then table.insert(sources, k); table.insert(src_rows, e) end
        end
        -- the civilians: citizens not in a squad
        local civs, civ_out = {}, 0
        for _, u in ipairs(U.citizens and U.citizens(true) or dfhack.units.getCitizens(true)) do
            if #civs >= SHELTER_PLAN_CIVS then break end
            pcall(function()
                if u.military.squad_id ~= -1 then return end
                local k = grid_key_near(grid, u.pos, 1)
                if k then table.insert(civs, k) else civ_out = civ_out + 1 end
            end)
        end
        -- the candidates: levels with enough inside tiles; the farthest
        -- (straight) from the ways in walked, the pick's own levels always
        local sup = supplies_by_level()
        local all = {}
        for z = lo, hi do
            if (counts[z] or 0) >= SHELTER_PLAN_LEVEL_MIN then
                local far = nil
                for _, e in ipairs(ways) do
                    local d = 3 * math.abs(z - e.z)
                    if not far or d < far then far = d end
                end
                local s = sup[z] or {}
                table.insert(all, {z = z, key = z, tiles = counts[z], drink = s.drink or 0, wells = s.wells or 0,
                                   food = s.food or 0, far = far or 0})
            end
        end
        local mine = {}
        for _, z in ipairs(cur and cur.levels or {}) do mine[tonumber(z) or -1] = true end
        table.sort(all, function(a, b)
            local ma, mb = mine[a.z] and 1 or 0, mine[b.z] and 1 or 0
            if ma ~= mb then return ma > mb end
            local wa = (a.wells > 0 or a.drink > 0) and 1 or 0
            local wb = (b.wells > 0 or b.drink > 0) and 1 or 0
            if a.far ~= b.far then return a.far > b.far end
            return wa > wb
        end)
        -- each level's inside tiles, in one pass over the grid
        local by_z = {}
        for k, f in pairs(grid) do
            if f >= INSIDE then
                local z = k // 1048576
                by_z[z] = by_z[z] or {}
                table.insert(by_z[z], k)
            end
        end
        local walk = {}
        for i, c in ipairs(all) do
            if i > SHELTER_PLAN_MAX_BFS then break end
            c.seeds = by_z[c.z] or {}
            table.insert(walk, c)
        end
        -- the shelter now (the AI's pick) as one candidate of its own: the
        -- dangers inside are measured against its walk (kept)
        local keep_key = nil
        if cur and #cur.levels > 0 then
            keep_key = 'pick'
            local seeds = {}
            for z in pairs(mine) do
                for _, k in ipairs(by_z[z] or {}) do table.insert(seeds, k) end
            end
            table.insert(walk, {key = 'pick', levels = cur.levels, pick = true, seeds = seeds})
        end
        local cands, kept = plan(grid, walk, sources, civs, {}, {keep = keep_key})
        for _, c in ipairs(cands) do
            if c.src then
                local e = src_rows[c.src]
                c.way_in = e and {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z} or nil
            end
            c.src, c.far = nil, nil
        end
        local rest = {}
        for i, c in ipairs(all) do
            if i > SHELTER_PLAN_MAX_BFS then
                table.insert(rest, {z = c.z, tiles = c.tiles, drink = c.drink, wells = c.wells, food = c.food})
            end
        end
        local bar = {}
        pcall(function() bar = barracks(grid) end)
        m = {tick = now, sig = signature, grid = grid, cands = cands, rest = rest, keep = kept,
             civs = #civs, civ_out = civ_out, ways = ways, barracks = bar, levels = {lo, hi}}
        MEMO = m
    end
    -- the dangers inside the fort, and their walk to the shelter now
    local any_inside = false
    for _, t in ipairs(list) do
        local f = m.grid[K(t.x, t.y, t.z)]
        local k = (f and f >= INSIDE) and K(t.x, t.y, t.z) or nil
        if not k then
            local nk = grid_key_near(m.grid, t, 1)
            if nk and m.grid[nk] >= INSIDE then k = nk end
        end
        if k then
            t.inside = true
            any_inside = true
            if m.keep then t.to_shelter = m.keep[k] end
        end
    end
    out.dangers = list
    out.any_inside = any_inside or nil
    out.ways_in = m.ways
    out.candidates = {}
    for _, c in ipairs(m.cands) do
        if c.pick then out.current_walk = c else table.insert(out.candidates, c) end
    end
    out.other_levels = m.rest
    out.civilians, out.civilians_off_grid = m.civs, m.civ_out
    out.barracks = m.barracks
    out.levels = m.levels
    out.walked_tick = m.tick
    return out
end

-- (shelter_pick) the AI shelter drawn over these levels (clear: the whole
-- fort again). Only when the civilian alert's burrow is the AI shelter.
function pick(levels, opts, dry_run)
    opts = opts or {}
    local S = reqscript('ai-society')
    local b = S.find_burrow(S.SHELTER_NAME)
    local mine = false
    pcall(function()
        for _, id in ipairs(df.global.plotinfo.alerts.list[1].burrows) do if b and id == b.id then mine = true end end
    end)
    if not mine then return {ok = false, rejected = true, error = 'the civilian alert\'s burrow is not the AI shelter'} end
    if opts.clear then
        if dry_run then return {ok = true, dry_run = true, clear = true} end
        U.site_put(SHELTER_PICK_KEY, {})
        MEMO = nil
        local r = S.refresh_shelter() or {}
        r.ok, r.clear = true, true
        return r
    end
    if type(levels) ~= 'table' or #levels == 0 or #levels > 6 then
        return {ok = false, rejected = true, error = 'shelter_pick needs levels: a list of 1-6 z levels'}
    end
    local lo, hi = S.shelter_level_range()
    for _, z in ipairs(levels) do
        if lo and (z < lo or z > hi) then
            return {ok = false, rejected = true, error = ('level %d is not one of the fort\'s (%d-%d)'):format(z, lo, hi)}
        end
    end
    if dry_run then return {ok = true, dry_run = true, levels = levels} end
    local before = U.site_get(SHELTER_PICK_KEY, {})
    U.site_put(SHELTER_PICK_KEY, {levels = levels, tick = U.abs_tick(), why = opts.why and tostring(opts.why):sub(1, 200),
                                  way_in = opts.way_in})
    MEMO = nil
    local r = S.refresh_shelter()
    if not r or (r.tiles or 0) == 0 then
        U.site_put(SHELTER_PICK_KEY, before)         -- nothing to shelter in there: as it was
        pcall(S.refresh_shelter)
        return {ok = false, rejected = true, error = 'no inside tiles on those levels'}
    end
    r.ok, r.levels = true, levels
    return r
end
