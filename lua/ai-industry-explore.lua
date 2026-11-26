-- (r34a) Exploratory tunnels for idle miners: split off lua/ai-industry.lua
-- (its size), whose helpers it takes (XI). reqscript('ai-industry').explore
-- calls explore here.
--@module = true

local U = reqscript('ai-util')
local I = reqscript('ai-industry')
local X = I.XI
local area, is_wall, safe, walkable = X.area, X.is_wall, X.safe, X.walkable
local project_areas, vein_at, near_levels, now_tick = X.project_areas, X.vein_at, X.near_levels, X.now_tick
local room_wall, metals_of, is_gem = I.room_wall, I.metals_of, I.is_gem

-- --- (r34a) exploratory tunnels: work for idle miners ------------------------------

-- E, the Deep mine (26 Nov): 27 miners, nothing to dig (its plan dug out,
-- no vein within a drift's reach), 32-36% of the fort idle. Straight 1-wide
-- tunnels from the dwarves' ground into rock nobody has seen, away from the
-- AI's levels and rooms, through rock that is safe to dig (as a drift's):
-- they uncover veins for the vein rule and exploratory mining, and leave a
-- boulder about every fourth tile for the masons. A tunnel is dug one face at
-- a time, so several at once (one miner each); each call goes on from the
-- ends of the last tunnels first (they reach farther, never wider), within
-- the survey's box (the citizens' + SURVEY_MARGIN). The ends are kept in the
-- site's data. Among the new ones the longest win, then those touching most
-- veins, then the nearest; never beside the main stair's hub.
EXPLORE_MAX = 80            -- tiles marked in one call at most
EXPLORE_MIN_RUN = 4         -- a tunnel this long at least (shorter: not worth a miner's walk)
EXPLORE_FACES = 60          -- new faces weighed in one call
EXPLORE_SCAN_MAX = 60000    -- floor tiles read at most looking for them
EXPLORE_KEY = 'ai-overseer/explore/ends'
EXPLORE_KEEP = 12           -- tunnel ends kept
EXPLORE_PENDING_TICKS = 67200  -- (r35b) a tunnel still marked holds its slot two months at most
EXPLORE_GAP = 2             -- tiles of rock between two new tunnels at least
EXPLORE_STAIR_GAP = 4       -- never this near the main stair's column (its hub, where the halls start)

-- Pure: the straight run from (x, y) along (dx, dy): its tiles while ok(x, y), at most n.
function straight_run(x, y, dx, dy, n, ok)
    local out = {}
    for i = 0, n - 1 do
        local tx, ty = x + dx * i, y + dy * i
        if not ok(tx, ty) then break end
        out[#out + 1] = {x = tx, y = ty}
    end
    return out
end

-- Pure: is every tile of run at least EXPLORE_GAP + 1 tiles (Chebyshev) from every tile of the runs taken?
function run_clear(run, z, taken)
    for _, r in ipairs(taken) do
        if r.z == z then
            for _, t in ipairs(run) do
                for _, u in ipairs(r.tiles) do
                    if math.abs(t.x - u.x) <= EXPLORE_GAP and math.abs(t.y - u.y) <= EXPLORE_GAP then return false end
                end
            end
        end
    end
    return true
end

local function explore_ends()
    local out = {}
    for _, e in ipairs(U.site_get(EXPLORE_KEY, {})) do
        if type(e) == 'table' and math.tointeger(e.x) and math.tointeger(e.y) and math.tointeger(e.z)
                and math.tointeger(e.dx) and math.tointeger(e.dy) then
            out[#out + 1] = e
        end
    end
    return out
end

function explore(count, tunnels, dry_run)
    local a = area()
    if not a then return {ok = false, error = 'no citizens'} end
    count = math.max(EXPLORE_MIN_RUN, math.min(EXPLORE_MAX, count or 40))
    tunnels = math.max(1, math.min(6, tunnels or 1))
    local per = math.max(EXPLORE_MIN_RUN, count // tunnels)
    local areas = project_areas()
    local groups = {}
    for _, p in ipairs(reqscript('ai-builder').citizen_positions()) do
        local g = dfhack.maps.getWalkableGroup(xyz2pos(p.x, p.y, p.z))
        if g and g ~= 0 then groups[g] = true end
    end
    local function ground(x, y, z)          -- walkable, seen, and the citizens reach it
        local fl = dfhack.maps.getTileFlags(x, y, z)
        if not fl or fl.hidden or not walkable(x, y, z) then return false end
        local g = dfhack.maps.getWalkableGroup(xyz2pos(x, y, z))
        return g and groups[g] or false
    end
    local okst, stair = pcall(function() return reqscript('ai-builder').find_main_stair() end)
    if not (okst and type(stair) == 'table' and stair.x and stair.y) then stair = nil end
    local rock = {}
    local function ok_rock(x, y, z)
        local kk = x .. ',' .. y .. ',' .. z
        local v = rock[kk]
        if v == nil then
            v = false
            local by_stair = stair and math.abs(x - stair.x) <= EXPLORE_STAIR_GAP and math.abs(y - stair.y) <= EXPLORE_STAIR_GAP
            if not by_stair and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 and is_wall(x, y, z) then
                local d = dfhack.maps.getTileFlags(x, y, z)
                local okm, mat = pcall(function()
                    local at = df.tiletype.attrs[dfhack.maps.getTileType(x, y, z)]
                    return df.tiletype_material[at.material]
                end)
                local natural = not okm or mat == nil or mat == 'STONE' or mat == 'MINERAL'
                if d and d.dig == df.tile_dig_designation.No and natural and not near_levels(x, y, z, areas)
                        and safe(x, y, z) and not room_wall(x, y, z) then
                    v = true
                end
            end
            rock[kk] = v
        end
        return v
    end
    local function veins_in(run, z)
        local n = 0
        for _, t in ipairs(run) do
            local m = vein_at(t.x, t.y, z)
            if m and (#metals_of(m) > 0 or is_gem(m)) then n = n + 1 end
        end
        return n
    end
    local taken, continued = {}, 0
    -- (r35b) a tunnel whose end is still marked for digging holds its slot: the miners
    -- finish it before new faces are opened (B, D, E 26 Nov: a fresh set of stubs every
    -- game day, continued 0, since an end is gone on from only once it is dug)
    local pending = 0
    local okn, nowt = pcall(now_tick)
    nowt = okn and math.tointeger(nowt) or nil
    for _, e in ipairs(explore_ends()) do
        local fl = dfhack.maps.getTileFlags(e.x, e.y, e.z)
        -- (two months on, a tunnel nobody reaches gives its slot up)
        local fresh = not (nowt and math.tointeger(e.tick) and nowt - e.tick > EXPLORE_PENDING_TICKS)
        if fresh and fl and fl.dig ~= df.tile_dig_designation.No and not ground(e.x, e.y, e.z) then
            pending = pending + 1
        end
    end
    if pending >= tunnels then
        return {ok = true, tiles = 0, tunnels = 0, continued = 0, veins = 0, pending = pending,
                waiting = ('%d exploratory tunnel(s) still being dug: no new ones until they are'):format(pending),
                dry_run = dry_run or nil}
    end
    tunnels = tunnels - pending
    -- the last tunnels' ends first: once dug, straight on (or turned aside when blocked)
    for _, e in ipairs(explore_ends()) do
        if #taken >= tunnels then break end
        if ground(e.x, e.y, e.z) then
            local dirs = {{e.dx, e.dy}, {e.dy, e.dx}, {-e.dy, -e.dx}}
            for _, d in ipairs(dirs) do
                local run = straight_run(e.x + d[1], e.y + d[2], d[1], d[2], per,
                                         function(x, y) return ok_rock(x, y, e.z) end)
                if #run >= EXPLORE_MIN_RUN and run_clear(run, e.z, taken) then
                    taken[#taken + 1] = {tiles = run, z = e.z, dx = d[1], dy = d[2], veins = veins_in(run, e.z)}
                    continued = continued + 1
                    break
                end
            end
        end
    end
    -- new faces: walls beside the dwarves' ground, outward from the citizens' middle (as the quarry's scan)
    if #taken < tunnels then
        local faces, seen_face = {}, {}
        local function try_floor(x, y, z)
            if not ground(x, y, z) then return end
            for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
                local tx, ty = x + d[1], y + d[2]
                local fk = tx .. ',' .. ty .. ',' .. z .. ',' .. d[1] .. ',' .. d[2]
                if not seen_face[fk] then
                    seen_face[fk] = true
                    local run = straight_run(tx, ty, d[1], d[2], per, function(rx, ry) return ok_rock(rx, ry, z) end)
                    if #run >= EXPLORE_MIN_RUN then
                        faces[#faces + 1] = {tiles = run, z = z, dx = d[1], dy = d[2], veins = veins_in(run, z),
                                             dist = math.abs(tx - a.cx) + math.abs(ty - a.cy) + 3 * math.abs(z - a.cz)}
                    end
                end
            end
        end
        local dx_max = math.max(math.abs(a.x1 - a.cx), math.abs(a.x2 - a.cx))
        local dy_max = math.max(math.abs(a.y1 - a.cy), math.abs(a.y2 - a.cy))
        local dz_max = math.max(math.abs(a.z1 - a.cz), math.abs(a.z2 - a.cz))
        local read = 0
        for D = 0, dx_max + dy_max + 3 * dz_max do
            if #faces >= EXPLORE_FACES or read >= EXPLORE_SCAN_MAX then break end
            for dz = 0, math.min(dz_max, D // 3) do
                local r = D - 3 * dz
                for _, z in ipairs(dz == 0 and {a.cz} or {a.cz - dz, a.cz + dz}) do
                    if z >= a.z1 and z <= a.z2 then
                        for i = math.max(-r, a.x1 - a.cx), math.min(r, a.x2 - a.cx) do
                            local j = r - math.abs(i)
                            local x = a.cx + i
                            for _, y in ipairs(j == 0 and {a.cy} or {a.cy - j, a.cy + j}) do
                                if y >= a.y1 and y <= a.y2 then
                                    read = read + 1
                                    try_floor(x, y, z)
                                end
                            end
                        end
                    end
                end
            end
        end
        -- the longest runs first, then those touching most veins, then the nearest
        table.sort(faces, function(f1, f2)
            if #f1.tiles ~= #f2.tiles then return #f1.tiles > #f2.tiles end
            if f1.veins ~= f2.veins then return f1.veins > f2.veins end
            return f1.dist < f2.dist
        end)
        for _, f in ipairs(faces) do
            if #taken >= tunnels then break end
            if run_clear(f.tiles, f.z, taken) then taken[#taken + 1] = f end
        end
    end
    if #taken == 0 then
        return {ok = false, rejected = true,
                error = ('no wall beside the dwarves\' ground with %d tiles of safe rock straight behind it, '
                         .. 'away from the AI\'s levels and rooms, within %d tiles of the fort'):format(EXPLORE_MIN_RUN, I.SURVEY_MARGIN)}
    end
    local marked, veins = {}, 0
    for _, r in ipairs(taken) do
        veins = veins + (r.veins or 0)
        for _, t in ipairs(r.tiles) do marked[#marked + 1] = {x = t.x, y = t.y, z = r.z} end
    end
    -- (0.105.40b) the dig guard once more over what is marked
    local why = U.dig_check_tiles(marked, nil, (not dry_run) and 'explore' or nil)
    if why then
        return {ok = false, rejected = true, error = 'a tile of the tunnel is ' .. why .. ': left alone: it guards the underworld'}
    end
    local first = marked[1]
    local out = {ok = true, tiles = #marked, tunnels = #taken, continued = continued, veins = veins, pending = pending,
                 x = first.x, y = first.y, z = first.z, dry_run = dry_run or nil}
    if dry_run then return out end
    for _, t in ipairs(marked) do
        local d = dfhack.maps.getTileFlags(t.x, t.y, t.z)
        d.dig = df.tile_dig_designation.Default
        local block = dfhack.maps.getTileBlock(t.x, t.y, t.z)
        if block then block.flags.designated = true end
    end
    -- the new ends first, then the older ones not gone on from
    local ends = {}
    for _, r in ipairs(taken) do
        local e = r.tiles[#r.tiles]
        ends[#ends + 1] = {x = e.x, y = e.y, z = r.z, dx = r.dx, dy = r.dy, tick = now_tick()}
    end
    for _, e in ipairs(explore_ends()) do
        if #ends >= EXPLORE_KEEP then break end
        local used = false
        for _, r in ipairs(taken) do
            local s0 = r.tiles[1]
            if r.z == e.z and math.abs(s0.x - e.x) + math.abs(s0.y - e.y) == 1 then used = true end
        end
        if not used then ends[#ends + 1] = e end
    end
    U.site_put(EXPLORE_KEY, ends)
    return out
end
