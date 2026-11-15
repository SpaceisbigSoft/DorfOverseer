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

-- (0.105.48, K1) the citizens' walk groups (DF's path data): a set, or nil unread
local function citizen_groups()
    local ok, set = pcall(function()
        local out, any = {}, false
        for _, u in ipairs(U.citizens and U.citizens(true) or dfhack.units.getCitizens(true)) do
            local g = dfhack.maps.getWalkableGroup(u.pos)
            if g and g ~= 0 then out[g] = true; any = true end
        end
        return any and out or nil
    end)
    return ok and set or nil
end

-- (0.105.48, K1) Where a danger stands, from DF's tile flags: 'hidden' (an
-- unrevealed tile: a cavern or the underworld not yet dug into), 'surface'
-- (under the sky), 'feature' (a cavern, the underworld), 'fort' (the rock
-- the fort is dug in); nil unread.
local function where_at(x, y, z)
    local ok, w = pcall(function()
        local d = dfhack.maps.getTileFlags(x, y, z)
        if not d then return nil end
        if d.hidden then return 'hidden' end
        if d.outside then return 'surface' end
        if d.feature_local or d.feature_global then return 'feature' end
        return 'fort'
    end)
    return ok and w or nil
end

-- (0.105.48, K1) Can this danger come to the civilians? War-hold: the
-- shelter shrank to one level of 90 tiles, 28 drinks and no food for 34
-- for 3 forgotten beasts in unrevealed caverns and 5 demons at z3, none of
-- which could come. Not: a unit DF hides (isHidden: an ambusher not seen,
-- a beast in a cavern not yet opened), one on an unrevealed tile, one in a
-- cavern or the underworld whose walk group no citizen shares (sealed off),
-- unless it breaks buildings and some entrance is held only by doors or
-- hatches. Always: one on the surface (the gates may open) or in the fort's
-- own rock, and one DF's path data can't place. Returns true, or false and
-- why ('hidden' or 'sealed').
function can_come(u, row, groups, any_door_only)
    local okh, hid = pcall(dfhack.units.isHidden, u)
    if okh and hid then return false, 'hidden' end
    local where = where_at(row.x, row.y, row.z)
    if where == 'hidden' then return false, 'hidden' end
    if where ~= 'feature' or not groups then return true end
    local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos and xyz2pos(row.x, row.y, row.z) or u.pos)
    if not okg or not g or g == 0 or groups[g] then return true end
    if row.destroyer and any_door_only then return true end
    return false, 'sealed'
end

-- The great dangers and invaders on the map, free and alive, that can come
-- to the civilians: {id, name, x, y, z, great, invader}; and (0.105.48) the
-- ones left out: {id, name, z, why} ('hidden', 'sealed')
function dangers(txt, ents)
    local out, away = {}, {}
    local list = (U.REPORT_CTX and U.units_active) and U.units_active() or df.global.world.units.active
    local groups, door_only_any = nil, false
    local function setup()
        if groups ~= nil then return end
        groups = citizen_groups() or false
        for _, e in ipairs(ents or {}) do
            if e.door_only and e.kind ~= 'cavern' then door_only_any = true end
        end
    end
    -- (0.105.51) and a wild pack (ai-gates wild_pack_ids: C's 9 giant dingoes
    -- left the plan at danger = false while they killed 10 of 14)
    local pack = {}
    pcall(function()
        local p = reqscript('ai-gates').wild_pack_ids(list)
        if type(p) == 'table' then pack = p end
    end)
    for _, u in ipairs(list) do
        local ok, row = pcall(function()
            if not dfhack.units.isActive(u) or dfhack.units.isDead(u) or dfhack.units.isCitizen(u, true) then return nil end
            if u.flags1.caged or u.flags1.chained then return nil end
            local wild = pack[u.id] == true
            if not wild and not dfhack.units.isDanger(u) then return nil end
            local great, inv = dfhack.units.isGreatDanger(u) == true, dfhack.units.isInvader(u) == true
            if not (great or inv or wild) then return nil end
            return {id = u.id, x = u.pos.x, y = u.pos.y, z = u.pos.z, great = great or nil, invader = inv or nil,
                    wild = wild or nil,
                    destroyer = destroyer_of(u) or nil,           -- (0.105.47)
                    name = (txt or tostring)(dfhack.units.getReadableName(u))}
        end)
        if ok and row and row.x >= 0 then
            setup()
            local okc, yes, why = pcall(can_come, u, row, groups or nil, door_only_any)
            if not okc or yes then
                table.insert(out, row)
            elseif #away < 20 then
                table.insert(away, {id = row.id, name = row.name, z = row.z, great = row.great, why = why})
            end
        end
    end
    return out, away
end

local function straight(a, b) return math.max(math.abs(a.x - b.x), math.abs(a.y - b.y)) + 3 * math.abs(a.z - b.z) end

-- (0.105.47, R2 item 7) A building destroyer (it breaks doors and hatches),
-- from its caste's raws; nil unread.
function destroyer_of(u)
    local ok, v = pcall(function()
        return (df.creature_raw.find(u.race).caste[u.caste].misc.buildingdestroyer or 0) > 0
    end)
    if ok then return v end
    return nil
end

-- (0.105.47) An entrance held only by doors or hatches (no drawbridge in it
-- or in front of it): a building destroyer breaks it.
function door_only(e)
    if type(e.equipment) ~= 'table' or #e.equipment == 0 then return false end
    for _, g in ipairs(e.equipment) do
        if g.kind ~= 'door' and g.kind ~= 'hatch' then return false end
    end
    for _, g in ipairs(type(e.outer) == 'table' and e.outer or {}) do
        if g.kind == 'bridge' then return false end
    end
    return true
end

local function entrances()
    local ok, G = pcall(function() return reqscript('ai-gates').GATES end)
    if not ok or type(G) ~= 'table' or not G.scanned or type(G.entrances) ~= 'table' then return {} end
    local out = {}
    for _, e in ipairs(G.entrances) do
        local okp = pcall(function() return e.x + e.y + e.z end)
        if okp then
            local okd, d = pcall(door_only, e)
            table.insert(out, {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z, sealed = e.sealed or nil,
                               door_only = (okd and d) or nil})
        end
    end
    return out
end

-- Each danger's ways in (pure): the entrance nearest it (straight); and
-- (0.105.47, R2 item 7) for a building destroyer every entrance held only
-- by doors or hatches too, shut or not (C's titans came in by a stair under
-- a bare hatch while the nearest gate, a raised bridge, held). Sets t.way_in
-- (the nearest) and t.door_ways; returns the ways (8 at most).
function ways_in(list, ents)
    local ways, way_by = {}, {}
    local function add(e)
        if not way_by[e.id] and #ways < 8 then way_by[e.id] = true; table.insert(ways, e) end
    end
    for _, t in ipairs(list) do
        local best, bd
        for _, e in ipairs(ents) do
            local d = straight(t, e)
            if not bd or d < bd then best, bd = e, d end
        end
        t.way_in = best and best.id or nil
        if best then add(best) end
    end
    for _, t in ipairs(list) do
        if t.destroyer then
            for _, e in ipairs(ents) do
                if e.door_only and e.kind ~= 'cavern' then
                    t.door_ways = t.door_ways or {}
                    table.insert(t.door_ways, e.id)
                    add(e)
                end
            end
        end
    end
    return ways, way_by
end


-- (0.105.48, A1) A tile's grid flags from its block: nil (no way: not
-- walkable, hidden, deep water, magma), and whether it is inside (not under
-- the sky, not a cavern or other feature). The designation is read as one
-- number where DF gives it (`whole`: flow_size bits 0-2, hidden 9, outside
-- 16, liquid_type 21, feature_local 28, feature_global 29; df-structures
-- tile_designation), the tile type's shape kept by type: the walk was
-- 8.2 s of a 10 s pulse on the War-hold, a dozen DF reads a tile.
local TT_FLAG = {}
local function tt_flag(tt)
    local f = TT_FLAG[tt]
    if f == nil then
        local ok, v = pcall(function() return WALK_SHAPES[df.tiletype_shape[df.tiletype.attrs[tt].shape]] end)
        f = (ok and v) or false
        TT_FLAG[tt] = f
    end
    return f
end

local function tile_from(d, tcol, ly)
    local w = d.whole
    local hidden, flow, magma, outside, feature
    if type(w) == 'number' then
        hidden = (w // 512) % 2 == 1
        if hidden then return nil end
        flow = w % 8
        magma = (w // 2097152) % 2 == 1
        outside = (w // 65536) % 2 == 1
        feature = (w // 268435456) % 4 ~= 0
    else
        if d.hidden then return nil end
        flow = d.flow_size or 0
        magma = d.liquid_type == true or d.liquid_type == 1
        outside = d.outside == true
        feature = d.feature_local == true or d.feature_global == true
    end
    local f = tt_flag(tcol[ly])
    if not f then return nil end
    if flow > 0 and (flow >= 4 or magma) then return nil end
    return f, not outside and not feature
end

local function tile_at(block, lx, ly)
    return tile_from(block.designation[lx][ly], block.tiletype[lx], ly)
end

-- the map's blocks on levels lo..hi, as {bx, by, z} (block coordinates; the
-- block itself is fetched when walked: nothing of DF is kept between reports)
local function block_list(lo, hi)
    local out = {}
    local okm = pcall(function()
        local bx, by, bz = dfhack.maps.getSize()
        for z = math.max(0, lo), math.min(hi, bz - 1) do
            for x = 0, bx - 1 do
                for y = 0, by - 1 do table.insert(out, {x, y, z}) end
            end
        end
    end)
    if okm and #out > 0 then return out end
    out = {}
    for i, block in ipairs(df.global.world.map.map_blocks) do
        local z = block.map_pos.z
        if z >= lo and z <= hi then table.insert(out, {block.map_pos.x // 16, block.map_pos.y // 16, z, i = i}) end
    end
    return out
end

local function block_of(item)
    if item.i then return df.global.world.map.map_blocks[item.i] end
    return dfhack.maps.getBlock(item[1], item[2], item[3])
end

-- the block holding map tile x, y, z (or nil)
local FAKE_BLOCKS = nil
local function block_at(x, y, z)
    if x < 0 or y < 0 or z < 0 then return nil end
    local ok, b = pcall(function() return dfhack.maps.getTileBlock(x, y, z) end)
    if ok then return b end
    if not FAKE_BLOCKS then
        FAKE_BLOCKS = {}
        for _, block in ipairs(df.global.world.map.map_blocks) do
            FAKE_BLOCKS[K(block.map_pos.x // 16, block.map_pos.y // 16, block.map_pos.z)] = block
        end
    end
    return FAKE_BLOCKS[K(x // 16, y // 16, z)]
end

-- One block's walkable inside tiles into the grid (acc.grid, acc.counts)
local function grid_visit(acc, item)
    local block = block_of(item)
    if not block then return end
    local bx, by, z = block.map_pos.x, block.map_pos.y, block.map_pos.z
    local grid, n = acc.grid, 0
    local des, tts = block.designation, block.tiletype
    for x = 0, 15 do
        local dcol, tcol = des[x], tts[x]
        for y = 0, 15 do
            local f, ins = tile_from(dcol[y], tcol, y)
            if f and ins then
                grid[K(bx + x, by + y, z)] = f + INSIDE
                n = n + 1
            end
        end
    end
    if n > 0 then acc.counts[z] = (acc.counts[z] or 0) + n end
end

-- The tiles within SHELTER_PLAN_NEAR of each point (outside, cavern ones
-- too: to join a way in to the inside), added to grid.
local function grid_near(grid, points)
    local near = SHELTER_PLAN_NEAR
    local done = {}
    for _, p in ipairs(points or {}) do
        for z = p.z - 1, p.z + 1 do
            for x = p.x - near, p.x + near do
                for y = p.y - near, p.y + near do
                    local k = K(x, y, z)
                    if x >= 0 and y >= 0 and z >= 0 and not done[k] then
                        done[k] = true
                        if not grid[k] then
                            local block = block_at(x, y, z)
                            if block then
                                local okt, f, ins = pcall(tile_at, block, x % 16, y % 16)
                                if okt and f then grid[k] = ins and f + INSIDE or f end
                            end
                        end
                    end
                end
            end
        end
    end
end

-- The walkable tiles from z lo to hi: inside ones (not outside, not a cavern
-- or other feature), and outside or cavern ones only near the given points
-- (to join a way in to the inside). Deep water (4+) and magma are no way.
-- (Whole, at once: report() walks the same in slices.)
function build_grid(lo, hi, points)
    local acc = {grid = {}, counts = {}}
    for _, item in ipairs(block_list(lo, hi)) do grid_visit(acc, item) end
    grid_near(acc.grid, points)
    return acc.grid, acc.counts
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

-- (0.105.48, A1) The walk in slices (lua/ai-slices.lua): the War-hold's
-- pulse spent 8.2 s of its 10 s limit here, the game frozen, with one
-- threat on the map. Two walks, each a time budget a report: the fort's
-- inside tiles (block by block, kept SHELTER_GRID_TICKS) and the levels'
-- walks (one candidate level an item). Until a walk is whole the last
-- finished plan is sent (`stale` when it was made for other ways in or
-- another pick), or none (`walking`).
-- (0.105.51) R3 (15 Nov): with the full report's 3000 ms the plan took
-- 1-2.3 s median of each full report during a danger (report time 1.0 ->
-- 2.1 s): now 700 ms (more slices, the pulses' between them), 1000 ms
-- while there is no plan at all yet (the first within a few reports of a
-- new danger); and with nothing changed (the same ways in and pick, the same
-- dangers, none of them inside the fort) the last plan is kept up to
-- SHELTER_PLAN_KEEP_TICKS and nothing is walked.
SHELTER_SLICE_MS_PULSE = 150      -- a pulse's budget...
SHELTER_SLICE_MS_FIRST = 1000     -- ...a pulse's or a full report's with no plan at all yet (a danger just come)
SHELTER_SLICE_MS_FULL = 700       -- ...a full report's (0.105.51: was 3000)
SHELTER_GRID_TICKS = 1200         -- the inside tiles walked again at most this often
SHELTER_PLAN_KEEP_TICKS = 2 * 1200   -- (0.105.51) nothing changed and calm inside: the plan kept this long

local function run_slices(name, spec)
    local ok, SL = pcall(reqscript, 'ai-slices')
    if ok and type(SL) == 'table' and SL.run then return SL.run(name, spec) end
    -- no slices module (a test's fake): whole, at once
    local list = spec.items() or {}
    local acc = spec.init()
    for _, it in ipairs(list) do pcall(spec.visit, acc, it) end
    return spec.finish(acc), 'done', #list, #list
end

local RANGE = nil    -- (0.105.52) the citizens' level range while a danger stays (only widens)
local MEMO = nil     -- the last finished plan: {tick, sig, grid, cands, rest, keep, ...}
local WALK_CTX = nil -- the levels' walk under way: what it walks over
CALM_SINCE = nil     -- (0.105.48, K1) the tick since which no danger that can come is on the map

-- the levels' walk: its items (one candidate each), over the inside tiles
-- (base) and the tiles near the ways in and the dangers
local function walk_items(base, info)
    local grid = {}
    for k, f in pairs(base.grid) do grid[k] = f end
    grid_near(grid, info.points)
    local counts = base.counts
    -- the sources: the ways in (on the grid)
    local sources, src_rows = {}, {}
    for _, e in ipairs(info.ways) do
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
    for z = info.lo, info.hi do
        if (counts[z] or 0) >= SHELTER_PLAN_LEVEL_MIN then
            local far = nil
            for _, e in ipairs(info.ways) do
                local d = 3 * math.abs(z - e.z)
                if not far or d < far then far = d end
            end
            local sp = sup[z] or {}
            table.insert(all, {z = z, key = z, tiles = counts[z], drink = sp.drink or 0, wells = sp.wells or 0,
                               food = sp.food or 0, far = far or 0})
        end
    end
    local cur = info.cur
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
    local rest = {}
    for i, c in ipairs(all) do
        if i > SHELTER_PLAN_MAX_BFS then
            table.insert(rest, {z = c.z, tiles = c.tiles, drink = c.drink, wells = c.wells, food = c.food})
        end
    end
    local ctx = {grid = grid, sources = sources, src_rows = src_rows, civs = civs, civ_out = civ_out,
                 keep_key = keep_key, rest = rest, info = info}
    WALK_CTX = ctx
    local items = {}
    for _, c in ipairs(walk) do table.insert(items, {c = c, ctx = ctx}) end
    return items
end

local function walk_visit(acc, it)
    local ctx = it.ctx
    local cands, kept = plan(ctx.grid, {it.c}, ctx.sources, ctx.civs, {}, {keep = ctx.keep_key})
    table.insert(acc.cands, cands[1])
    if kept then acc.keep = kept end
end

local function walk_finish(acc)
    local ctx = WALK_CTX
    if not ctx then return nil end
    for _, c in ipairs(acc.cands) do
        if c.src then
            local e = ctx.src_rows[c.src]
            c.way_in = e and {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z} or nil
        end
        c.src, c.far = nil, nil
    end
    local bar = {}
    pcall(function() bar = barracks(ctx.grid) end)
    local info = ctx.info
    return {tick = info.now, sig = info.sig, dsig = info.dsig, grid = ctx.grid, cands = acc.cands, rest = ctx.rest, keep = acc.keep,
            civs = #ctx.civs, civ_out = ctx.civ_out, ways = info.ways, barracks = bar, levels = {info.lo, info.hi}}
end

-- (0.105.51) The time a report may walk the plan for: a pulse's, a full
-- report's, or with no plan at all yet the first plan's (the larger).
function shelter_budget(tier, have_plan)
    if tier == 'pulse' then return have_plan and SHELTER_SLICE_MS_PULSE or SHELTER_SLICE_MS_FIRST end
    if have_plan then return SHELTER_SLICE_MS_FULL end
    return math.max(SHELTER_SLICE_MS_FULL, SHELTER_SLICE_MS_FIRST)
end

-- (0.105.51) the dangers as one string: their ids, sorted
function danger_sig(list)
    local ids = {}
    for _, t in ipairs(list or {}) do table.insert(ids, tostring(t.id)) end
    table.sort(ids)
    return table.concat(ids, ',')
end

-- (0.105.51) is any danger on (or beside) an inside tile of the grid? (no grid: false)
function inside_any(grid, list)
    if type(grid) ~= 'table' then return false end
    for _, t in ipairs(list or {}) do
        local f = grid[K(t.x, t.y, t.z)]
        if f and f >= INSIDE then return true end
        local nk = grid_key_near(grid, t, 1)
        if nk and grid[nk] >= INSIDE then return true end
    end
    return false
end

-- (0.105.51) Is the last plan m good as it is? Walked for these ways in and
-- this pick (sig) within SHELTER_PLAN_TICKS; or, nothing changed (the same
-- dangers, none inside the fort), within SHELTER_PLAN_KEEP_TICKS. Returns
-- fresh, and whether it is fresh only by the second rule (kept).
function plan_fresh(m, sig, dsig, now, any_inside)
    if not m or m.sig ~= sig or type(now) ~= 'number' or type(m.tick) ~= 'number' or now < m.tick then
        return false, false
    end
    local age = now - m.tick
    if age < SHELTER_PLAN_TICKS then return true, false end
    if age < SHELTER_PLAN_KEEP_TICKS and m.dsig ~= nil and m.dsig == dsig and not any_inside then
        return true, true
    end
    return false, false
end

-- The report section `shelter_plan`. tier: the report's ('pulse': the
-- small budget).
function report(txt, tier)
    local out = {current = nil}
    local cur = current_pick()
    if cur then out.current = {levels = cur.levels, why = cur.why, way_in = cur.way_in, tick = cur.tick} end
    local okn, now = pcall(U.abs_tick)
    now = okn and now or 0
    local ents = entrances()
    local okd, list, away = pcall(dangers, txt, ents)
    if not okd then
        -- unread is not "no danger" (0.105.48: no danger widens the shelter back)
        out.error = 'dangers unread: ' .. tostring(list):sub(1, 160)
        return out
    end
    if type(away) == 'table' and #away > 0 then out.left_out = away end
    if #list == 0 then
        out.danger = false
        MEMO = nil
        RANGE = nil
        if CALM_SINCE == nil or CALM_SINCE > now then CALM_SINCE = now end
        out.calm_ticks = now - CALM_SINCE
        return out
    end
    CALM_SINCE = nil
    out.danger = true
    local S = reqscript('ai-society')
    local lo, hi = S.shelter_level_range()
    if not lo then out.error = 'no citizens to measure from'; return out end
    -- (0.105.52) the range only widens while the dangers stay: the citizens'
    -- levels change as they move, hide and die, and each change restarted the
    -- grid and the walk (R3 15 Nov: B's plan was 'still being walked' for two
    -- hours of a Hill Titan's siege, the dry shelter kept meanwhile)
    if RANGE and RANGE[1] <= lo and RANGE[2] >= hi then
        lo, hi = RANGE[1], RANGE[2]
    elseif RANGE then
        lo, hi = math.min(lo, RANGE[1]), math.max(hi, RANGE[2])
    end
    RANGE = {lo, hi}
    -- each danger's way in: the nearest entrance (straight), and a building
    -- destroyer's every door-only one (0.105.47), cap 8 ways
    local ways = ways_in(list, ents)
    local points = {}
    for _, e in ipairs(ways) do table.insert(points, e) end
    for _, t in ipairs(list) do table.insert(points, t) end
    local sig = {}
    for _, e in ipairs(ways) do table.insert(sig, tostring(e.id)) end
    table.sort(sig)
    local pick_sig = cur and table.concat(cur.levels, ',') or 'whole'
    local signature = table.concat(sig, ',') .. '|' .. pick_sig .. '|' .. lo .. '-' .. hi
    local budget = shelter_budget(tier, MEMO ~= nil)
    local dsig = danger_sig(list)
    local m = MEMO
    local fresh, kept = plan_fresh(m, signature, dsig, now, inside_any(m and m.grid, list))
    if kept then out.kept = true end           -- (0.105.51) nothing changed: nothing walked
    local t0 = os.clock()
    local base, gst, gdone, gtotal
    if not fresh then
        base, gst, gdone, gtotal = run_slices('shelter_grid', {
            key = lo .. '-' .. hi, now = now, ttl = SHELTER_GRID_TICKS,
            items = function() return block_list(lo, hi) end,
            init = function() return {grid = {}, counts = {}} end,
            visit = grid_visit, finish = function(acc) return acc end, max_ms = budget})
    end
    if base and not fresh then
        local info = {points = points, ways = ways, lo = lo, hi = hi, cur = cur, now = now, sig = signature, dsig = dsig}
        local left = math.max(1, budget - (os.clock() - t0) * 1000)
        -- (0.105.52) keyed by the ways in and the range only: a new shelter
        -- pick (the flee) no longer throws the unfinished walk away; the plan
        -- it finishes is marked stale against the pick and redone after
        local r, wst, wdone, wtotal = run_slices('shelter_walk', {
            key = table.concat(sig, ',') .. '|' .. lo .. '-' .. hi, now = now, ttl = 0,
            items = function() return walk_items(base, info) end,
            init = function() return {cands = {}} end,
            visit = walk_visit, finish = walk_finish, max_ms = left})
        if wst == 'done' and r then MEMO = r end
        if wst == 'partial' then out.walk = {done = wdone, total = wtotal} end
    end
    if gst == 'partial' then out.grid_walk = {done = gdone, total = gtotal} end
    m = MEMO
    if not m then
        -- nothing walked whole yet: the dangers and their ways in, no levels
        out.walking = true
        out.dangers = list
        out.ways_in = ways
        out.levels = {lo, hi}
        return out
    end
    local stale = m.sig ~= signature
    out.stale = stale or nil
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
            if m.keep and not stale then t.to_shelter = m.keep[k] end
        end
    end
    out.dangers = list
    out.any_inside = any_inside or nil
    out.ways_in = stale and ways or m.ways
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

-- (0.105.48) a new map: the last plan and the calm count start afresh
if dfhack and dfhack.onStateChange then
    pcall(function()
        dfhack.onStateChange['ai-shelter-plan'] = function(sc)
            if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then
                MEMO, WALK_CTX, CALM_SINCE, FAKE_BLOCKS = nil, nil, nil, nil
            end
        end
    end)
end
