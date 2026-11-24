-- ai-builder-projects-wayin: the emergency way in (dwarves stranded outside) and the second way in.
--
-- (r8) A part of ai-builder, not a script of its own: cut from ai-builder-projects.lua
-- (which had grown to 164 KB) at a section boundary, the code as it stood. ai-builder.lua
-- loads it into its own environment right after the part before it (PARTS), so every
-- name here is reqscript('ai-builder').name and the hub's helpers are in reach.
-- The top-level locals the ai-builder-projects files share come through
-- PROJECTS_PART_LOCALS (the same functions).

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-projects-wayin'] = '0.105.92'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, ez = info, ez
local founded_site = PROJECTS_PART_LOCALS.founded_site

---------------------------------------------------------------------------
-- (0.105.32, wayin) An emergency way in: E (8 Nov) lost 64 dwarves to
-- thirst outside a hatch that read open while DF's walk map was split at it,
-- and the brain could only ask the player to "dig or build them a way in".
-- dig_way_in digs one: a 1-wide stair column from a floor of the fort's
-- inside (near its top) up (or down) through solid ground to open ground in
-- the stranded dwarves' walk group, a short tunnel on the fort's level when
-- the column can't stand right beside the fort. Never through water, magma,
-- a cavern, an aquifer, warm stone, a building or another AI project, nor
-- beside open water or a cavern; at least WAY_IN_GATE_APART tiles from the
-- existing entrance's gate pieces; WAY_IN_MAX_DIG tiles of digging at most.
-- A project of kind 'way_in' (emergency = true: no hatch now; the gate scan
-- sees a new surface entrance and may fortify it later like any other).
---------------------------------------------------------------------------

WAY_IN_MAX_DIG = 30       -- tiles of digging, the column and its tunnel
WAY_IN_GATE_APART = 6     -- tiles (across) from every piece of the existing gates
WAY_IN_GATE_CLEAR = 3     -- and its tunnel, and the fort tile it opens on, this far (not into the gate's own shaft)
WAY_IN_RADIUS = 12        -- columns tried this far (across) from the stranded spot and the nearest inside tile
WAY_IN_TUNNEL = 8         -- longest tunnel on the fort's level to the column
WAY_IN_ZSPAN = 8          -- the stranded ground's end of the column: this many levels up or down
WAY_IN_PRIORITY = '1'     -- dig priority: they are dying of thirst out there
WAY_IN_SECONDS = 2        -- the search stops here
WAY_IN_INVADER_NEAR = 30  -- (merge32 review) no way in dug with an invader in sight this near its ends
WAY_IN_TRIES = 3          -- (0.105.33, L4) searches, each without the columns quickfort refused

-- (0.105.33, secondway) a second way to the surface by design: the same digger,
-- from open ground under the sky this far (across) from the existing entrance
WAY_IN_SECOND_MIN = 15
WAY_IN_SECOND_MAX = 40
WAY_IN_SECOND_PRIORITY = '4'   -- nobody is dying: the ordinary dig priority
WAY_IN_SECOND_CENTERS = 4      -- surface spots searched round (the best first)

local WAY_IN_SIDES = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
WAY_IN_NO_GROUND = 'no open ground of theirs to come up (or down) to'

-- (tests replace this) the gate scan's module, or nil
function way_in_gates()
    local ok, G = pcall(reqscript, 'ai-gates')
    return ok and type(G) == 'table' and G or nil
end

local function wkey(x, y, z) return (z * 4096 + y) * 4096 + x end   -- (ai-gates' key)

-- The fort's side: {group, set (the scan's inside, or nil), pieces = {{x1, y1, x2, y2}},
-- anchors = {{x, y, z}}: the founding stair or main stair}, or nil, why.
function way_in_fort()
    local out = {pieces = {}, anchors = {}}
    local G = way_in_gates()
    local GT = G and G.GATES
    if type(GT) == 'table' and GT.scanned and type(GT.inside) == 'table' then
        out.set = GT.inside
        local okf, fi = pcall(function() return G.fort_interior() end)
        if okf and type(fi) == 'table' and math.tointeger(fi.group) and fi.group ~= 0 then
            out.group = fi.group
            -- (0.105.33, L4) 'citizens inside' gives a group and no tile: no anchor
            if math.tointeger(fi.x) and math.tointeger(fi.y) and math.tointeger(fi.z) then
                table.insert(out.anchors, {x = fi.x, y = fi.y, z = fi.z})
            end
        end
        for _, e in ipairs(type(GT.entrances) == 'table' and GT.entrances or {}) do
            if math.tointeger(e.x) then table.insert(out.pieces, {x1 = e.x, y1 = e.y, x2 = e.x, y2 = e.y}) end
            for _, b in ipairs(type(e.equipment) == 'table' and e.equipment or {}) do
                local x1, y1 = math.tointeger(b.x1 or b.x), math.tointeger(b.y1 or b.y)
                if x1 and y1 then
                    table.insert(out.pieces, {x1 = x1, y1 = y1, x2 = math.tointeger(b.x2) or x1,
                                              y2 = math.tointeger(b.y2) or y1})
                end
            end
            for _, s in ipairs(type(e.split) == 'table' and e.split or {}) do
                if math.tointeger(s.x) then table.insert(out.pieces, {x1 = s.x, y1 = s.y, x2 = s.x, y2 = s.y}) end
            end
        end
    end
    -- else the walk group of the founding stair (or the main stair)
    local f = founded_site()
    if f and math.tointeger(f.x) and math.tointeger(f.y) and math.tointeger(f.z) then
        table.insert(out.pieces, {x1 = f.x, y1 = f.y, x2 = f.x, y2 = f.y})
        if not out.group then
            local g = walk_group(f.x, f.y, f.z - 1)
            if g ~= 0 then out.group = g; table.insert(out.anchors, {x = f.x, y = f.y, z = f.z - 1}) end
        end
    end
    if not out.group then
        local oks, stairs = pcall(find_stairs, 1)
        local s = oks and type(stairs) == 'table' and stairs[1] or nil
        if s then
            local g = walk_group(s.x, s.y, s.z_bottom)
            if g ~= 0 then out.group = g; table.insert(out.anchors, {x = s.x, y = s.y, z = s.z_bottom}) end
        end
    end
    if not out.group then return nil, 'no fort to dig from (no gate scan, founding stair or main stair found)' end
    return out
end

-- A tile of the fort's inside a dwarf can stand on.
local function way_in_inside(fort, memo, x, y, z)
    local k = wkey(x, y, z)
    local v = memo[k]
    if v ~= nil then return v end
    v = false
    if not fort.set or fort.set[k] then
        local t = info(x, y, z)
        v = t ~= nil and t.shape ~= 'WALL' and not t.outside and not t.feature and not t.liquid
            and walk_group(x, y, z) == fort.group
    end
    memo[k] = v
    return v
end

-- Open ground of the stranded group under the sky, fit to step off a stair onto (not
-- the deep depot's road or hall, which share their walk group: E's group A).
local function way_in_ground(t, x, y, z, target)
    return t ~= nil and t.shape == 'FLOOR' and t.outside and not t.liquid and not t.feature
        and walk_group(x, y, z) == target
end

-- plan = {x, y, cells = {{x, y, z, key}} (the column), tunnel = {{x, y}}, z_fort, from, to, tiles}
-- or nil, why. The column at (cx, cy); fort_below: the fort is under the stranded ground.
local function way_in_column(ctx, cx, cy, fort_below)
    local sz, target = ctx.z, ctx.target
    -- the stranded ground's end: the first level (from the far side) where it can be reached
    local top, top_key, out_tile, first
    local zs, ze, step = sz + WAY_IN_ZSPAN, sz - WAY_IN_ZSPAN, -1
    if not fort_below then zs, ze, step = sz - WAY_IN_ZSPAN, sz + WAY_IN_ZSPAN, 1 end
    local why = WAY_IN_NO_GROUND
    for z = zs, ze, step do
        local t = info(cx, cy, z)
        -- (0.105.33, L4) the top 'j' goes into natural ground: quickfort
        -- won't dig one into a built floor
        if fort_below and way_in_ground(t, cx, cy, z, target) and NATURAL[t.material] and not t.designated
                and not t.building and not building_at(cx, cy, z) then
            local ok, w = ctx.safe(cx, cy, z - 1)
            local okn, wn = ctx.dry_beside(cx, cy, z)
            if ok and okn then top, top_key, out_tile, first = z, 'j', {x = cx, y = cy, z = z}, z - 1 break end
            why = (not ok) and w or wn
        elseif t and t.shape == 'WALL' then
            for _, s in ipairs(WAY_IN_SIDES) do
                local nx, ny = cx + s[1], cy + s[2]
                if way_in_ground(info(nx, ny, z), nx, ny, z, target) then
                    local ok, w = ctx.safe(cx, cy, z)
                    if ok then
                        top, top_key, out_tile, first = z, fort_below and 'j' or 'u', {x = nx, y = ny, z = z}, z
                    else
                        why = w
                    end
                    break
                end
            end
            if top then break end
        end
    end
    if not top then return nil, why end
    -- then toward the fort, a level at a time, until a level joins it
    local cells = {}
    if top_key == 'j' and first ~= top then table.insert(cells, {x = cx, y = cy, z = top, key = 'j'}) end
    local dz = fort_below and -1 or 1
    local z = first
    while true do
        local n = #cells + 1
        if n > WAY_IN_MAX_DIG or n >= ctx.best_cost then
            return nil, ('more than %d tiles of digging'):format(math.min(WAY_IN_MAX_DIG, ctx.best_cost - 1)), true
        end
        local ok, w = ctx.safe(cx, cy, z)
        if not ok then return nil, w end
        table.insert(cells, {x = cx, y = cy, z = z, key = (z == top) and top_key or 'i'})
        if z ~= top and ctx.near(z, cx, cy) then
            local budget = math.min(WAY_IN_TUNNEL, WAY_IN_MAX_DIG - #cells, ctx.best_cost - 1 - #cells)
            local tunnel, from = ctx.tunnel(cx, cy, z, budget)
            if tunnel then
                cells[#cells].key = fort_below and 'u' or 'j'
                return {x = cx, y = cy, cells = cells, tunnel = tunnel, z_fort = z, from = from, to = out_tile,
                        tiles = #cells + #tunnel}
            end
        end
        z = z + dz
        if math.abs(z - top) > WAY_IN_MAX_DIG then return nil, 'no fort level within reach' end
    end
end

-- (0.105.33) Open ground under the sky (not a building, not dug, not a cavern
-- or water) a stair can come up to.
local function way_in_sky(t)
    return t ~= nil and t.shape == 'FLOOR' and t.outside and not t.subterranean and not t.hidden
        and not t.liquid and not t.feature and not t.building and not t.designated
end

-- (0.105.33) The second way in's surface end: the fort's one surface entrance
-- (the gate scan's) and the surface spots 15-40 tiles from it in the outside
-- walk group, best first (over the fort's inside, then nearer the entrance).
-- Returns {entrance = {x, y, z}, group, spots = {{x, y, z}}} or nil, why.
function way_in_second_spots(fort, GM, deadline_all, near)
    local GT = GM and GM.GATES
    if not (type(GT) == 'table' and GT.scanned and type(GT.entrances) == 'table') then
        return nil, 'the entrances are not mapped yet (scan them first)'
    end
    local surf = {}
    for _, e in ipairs(GT.entrances) do
        if e.kind == 'surface' and math.tointeger(e.x) then table.insert(surf, e) end
    end
    if #surf == 0 then return nil, 'the fort has no surface entrance to keep the new one apart from' end
    if #surf > 1 then
        return nil, ('the fort already has %d ways to the surface: no second one is needed'):format(#surf)
    end
    local e = surf[1]
    -- the outside walk group: the entrance's outside tiles (or the ground over it)
    local group = 0
    for k in pairs(type(e.outs) == 'table' and e.outs or {}) do
        local kk = math.tointeger(k)
        if kk then
            local g = walk_group(kk % 4096, (kk // 4096) % 4096, kk // (4096 * 4096))
            if g ~= 0 then group = g break end
        end
    end
    if group == 0 then
        for dz = 1, 2 do
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local t = info(e.x + dx, e.y + dy, e.z + dz)
                    if group == 0 and t and t.outside and t.shape ~= 'WALL' and t.shape ~= 'EMPTY' then
                        group = walk_group(e.x + dx, e.y + dy, e.z + dz)
                    end
                end
            end
        end
    end
    if group == 0 then return nil, 'no outside ground found at the entrance' end
    local W, H = map_size()
    local R = WAY_IN_SECOND_MAX
    local bx1, by1 = math.max(2, e.x - R), math.max(2, e.y - R)
    local bx2, by2 = math.min(W - 3, e.x + R), math.min(H - 3, e.y + R)
    -- how far (across) each column is from the fort's inside: a distance map from
    -- the inside's columns, over the box
    local dist, queue, head = {}, {}, 1
    local function ck(x, y) return y * 4096 + x end
    if fort.set then
        for k in pairs(fort.set) do
            local x, y = k % 4096, (k // 4096) % 4096
            if x >= bx1 and x <= bx2 and y >= by1 and y <= by2 and not dist[ck(x, y)] then
                dist[ck(x, y)] = 0
                table.insert(queue, {x, y})
            end
        end
        while head <= #queue do
            local c = queue[head]
            head = head + 1
            local d = dist[ck(c[1], c[2])] + 1
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local nx, ny = c[1] + dx, c[2] + dy
                    if nx >= bx1 and nx <= bx2 and ny >= by1 and ny <= by2 and not dist[ck(nx, ny)] then
                        dist[ck(nx, ny)] = d
                        table.insert(queue, {nx, ny})
                    end
                end
            end
        end
    end
    local zs = {0}
    for i = 1, WAY_IN_ZSPAN do table.insert(zs, i); table.insert(zs, -i) end
    local spots = {}
    local deadline = math.min(os.clock() + WAY_IN_SECONDS, deadline_all or math.huge)
    for x = bx1, bx2 do
        if os.clock() > deadline then break end
        for y = by1, by2 do
            local de = math.max(math.abs(x - e.x), math.abs(y - e.y))
            if de >= WAY_IN_SECOND_MIN and de <= WAY_IN_SECOND_MAX and (x + y) % 2 == 0 then
                for _, dz in ipairs(zs) do
                    local z = e.z + 1 + dz
                    local t = info(x, y, z)
                    -- (fix33) not on the fort's inside (a walled courtyard the
                    -- scan counts in): the top there is no second way out
                    if way_in_sky(t) and not (fort.set and fort.set[wkey(x, y, z)])
                            and walk_group(x, y, z) == group and not building_at(x, y, z) then
                        local di = dist[ck(x, y)] or 999
                        -- (0.105.47) with near (the fields): nearest them first, the fort's inside after
                        if near then di = math.max(math.abs(x - near.x), math.abs(y - near.y)) * 1000 + di end
                        table.insert(spots, {x = x, y = y, z = z, rank = di * 1000 + de})
                        break
                    end
                end
            end
        end
    end
    if #spots == 0 then
        return nil, ('no open ground under the sky %d-%d tiles from the entrance'):format(WAY_IN_SECOND_MIN, WAY_IN_SECOND_MAX)
    end
    table.sort(spots, function(a, b)
        if a.rank ~= b.rank then return a.rank < b.rank end
        if a.x ~= b.x then return a.x < b.x end
        return a.y < b.y
    end)
    -- the best few, apart from each other (round different sides of the fort)
    local picked = {}
    for _, sp in ipairs(spots) do
        local apart = true
        for _, q in ipairs(picked) do
            if math.max(math.abs(q.x - sp.x), math.abs(q.y - sp.y)) < 2 * WAY_IN_RADIUS then apart = false break end
        end
        if apart then table.insert(picked, sp) end
        if #picked >= WAY_IN_SECOND_CENTERS then break end
    end
    return {entrance = {x = e.x, y = e.y, z = e.z}, group = group, spots = picked}
end

-- dig_way_in{x, y, z}: the stranded spot (map coordinates). (0.105.33)
-- dig_way_in{second = true}: no stranded spot; a second way to the surface,
-- its top 15-40 tiles from the fort's one surface entrance. Returns
-- {ok, project_id, from, to, tiles, levels, column, tunnel, dry_run} or
-- {ok = false, rejected = true, error = why, why = why}.
function dig_way_in(params, now, dry_run)
    OFFSET = elevation_offset()
    CACHE = {}
    local ok, r = pcall(function() return way_in_plan_and_dig(params, now, dry_run) end)
    CACHE = nil
    if not ok then return {ok = false, error = 'the way-in search failed: ' .. tostring(r):sub(1, 160)} end
    return r
end

local function refuse(why) return {ok = false, rejected = true, error = why, why = why} end

local function pos_out(p)
    return p and {x = p.x, y = p.y, z = p.z, elevation = ez(p.z)} or nil
end

function way_in_plan_and_dig(params, now, dry_run)
    local second = params.second == true
    local sx, sy, sz = math.tointeger(params.x), math.tointeger(params.y), math.tointeger(params.z)
    if not second and (not sx or not sy or not sz) then return refuse('dig_way_in needs x, y, z') end
    local W, H, D = map_size()
    if not second and (sx < 0 or sy < 0 or sx >= W or sy >= H or sz < 0 or (D and sz >= D)) then
        return refuse('that spot is off the map')
    end
    local data = load_projects()
    -- (fix33) the second way to the surface never holds the emergency way in
    -- for dwarves cut off (the two dig side by side; reserved keeps them apart)
    for _, p in ipairs(data.list) do
        if p.kind == 'way_in' and p.phase == 'dig' and (second or not p.second) then
            return refuse(('a way in is already being dug (project %d)'):format(p.id))
        end
    end
    -- (fix33) one deadline for the whole search (the second way's spot scan
    -- and every column search): the game's freeze stays short
    local deadline_all = os.clock() + WAY_IN_SECONDS * WAY_IN_TRIES
    -- (merge32 review) not during a siege: a new hole in the fort while the
    -- gate watcher has it shut lets the enemy in by it
    local GM = way_in_gates()
    if GM and type(GM.GATES) == 'table' and GM.GATES.armed then
        return refuse('the gate watcher is armed (enemies about): no new way in is dug until the alarm is over')
    end
    local target, extra_centers, second_e, fort0
    if second then
        local fwhy0
        fort0, fwhy0 = way_in_fort()
        if not fort0 then return refuse(fwhy0) end
        -- (0.105.47) near: the Garden fort's fields (the stair up to them), when the brain sends them
        local near = type(params.near) == 'table' and math.tointeger(params.near.x) and math.tointeger(params.near.y)
            and {x = math.tointeger(params.near.x), y = math.tointeger(params.near.y)} or nil
        local pick, pwhy = way_in_second_spots(fort0, GM, deadline_all, near)
        if not pick then return refuse(pwhy) end
        target, second_e = pick.group, pick.entrance
        sx, sy, sz = pick.spots[1].x, pick.spots[1].y, pick.spots[1].z
        extra_centers = {}
        for i = 2, #pick.spots do table.insert(extra_centers, {x = pick.spots[i].x, y = pick.spots[i].y}) end
    else
        local here = info(sx, sy, sz)
        target = walk_group(sx, sy, sz)
        if not here or target == 0 then
            return refuse(('nobody can stand at x%d y%d z%d (no walkable ground there)'):format(sx, sy, ez(sz)))
        end
        if here.feature then
            return refuse('that spot is in a cavern: no way in is dug from a cavern (it would open the fort to it)')
        end
    end
    local fort, fwhy = fort0, nil
    if not fort then fort, fwhy = way_in_fort() end
    if not fort then return refuse(fwhy) end
    if not second and target == fort.group then
        return refuse('that spot already joins the fort\'s inside (the same walk group): no way in is needed')
    end
    -- (0.105.33) the second way's top: 15-40 tiles (across) from the entrance
    local function in_band(x, y)
        if not second_e then return true end
        local d = math.max(math.abs(x - second_e.x), math.abs(y - second_e.y))
        return d >= WAY_IN_SECOND_MIN and d <= WAY_IN_SECOND_MAX
    end
    -- the AI's other projects, by level
    local areas = {}
    local oka, list = pcall(level_areas)
    for _, a in ipairs(oka and list or {}) do
        if type(a) == 'table' and math.tointeger(a.z) then
            areas[a.z] = areas[a.z] or {}
            table.insert(areas[a.z], a)
        end
    end
    local function reserved(x, y, z)
        for _, a in ipairs(areas[z] or {}) do
            if x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 then return true end
        end
        return false
    end
    local function gate_dist(x, y)
        local d = math.huge
        for _, p in ipairs(fort.pieces) do
            local dx = (x < p.x1) and (p.x1 - x) or ((x > p.x2) and (x - p.x2) or 0)
            local dy = (y < p.y1) and (p.y1 - y) or ((y > p.y2) and (y - p.y2) or 0)
            d = math.min(d, math.max(dx, dy))
        end
        return d
    end
    local memo_in = {}
    local function inside(x, y, z) return way_in_inside(fort, memo_in, x, y, z) end
    -- no open water, magma, aquifer or cavern beside (and over, under) a dug tile
    local function wet(x, y, z)
        for dz = -1, 1 do
            for dx = -1, 1 do
                for dy = -1, 1 do
                    if (dx ~= 0 or dy ~= 0 or dz ~= 0) and (dz == 0 or (dx == 0 and dy == 0)) then
                        local n = info(x + dx, y + dy, z + dz)
                        if n and n.liquid then return ('water or magma beside x%d y%d z%d'):format(x, y, ez(z)) end
                        if n and n.feature then return ('a cavern beside x%d y%d z%d'):format(x, y, ez(z)) end
                        if n and n.aquifer then return ('an aquifer beside x%d y%d z%d'):format(x, y, ez(z)) end
                    end
                end
            end
        end
    end
    local memo_safe = {}
    local function safe(x, y, z)
        local k = wkey(x, y, z)
        local v = memo_safe[k]
        if v == nil then
            local okw, w = natural_wall(info(x, y, z))
            if okw and reserved(x, y, z) then okw, w = false, 'another AI project' end
            if okw then
                local wt = wet(x, y, z)
                if wt then okw, w = false, wt end
            elseif w then
                w = ('%s at x%d y%d z%d'):format(w, x, y, ez(z))
            end
            v = okw and true or w
            memo_safe[k] = v
        end
        if v == true then return true end
        return false, v
    end
    local function dry_beside(x, y, z)
        if reserved(x, y, z) then return false, 'another AI project' end
        local wt = wet(x, y, z)
        if wt then return false, wt end
        return true
    end
    -- where to look: around the stranded spot and around the fort's inside tile nearest it
    local centers = {{x = sx, y = sy}}
    local best_in, best_d
    if fort.set then
        for k in pairs(fort.set) do
            local x, y, z = k % 4096, (k // 4096) % 4096, k // (4096 * 4096)
            local d = math.max(math.abs(x - sx), math.abs(y - sy)) + 2 * math.abs(z - sz)
            if (not best_d or d < best_d) and inside(x, y, z) then best_in, best_d = {x = x, y = y, z = z}, d end
        end
    end
    best_in = best_in or fort.anchors[1]
    if best_in and (best_in.x ~= sx or best_in.y ~= sy) then table.insert(centers, {x = best_in.x, y = best_in.y}) end
    for _, c in ipairs(extra_centers or {}) do table.insert(centers, c) end      -- (0.105.33)
    -- "is the fort within reach of a tunnel on this level?": inside tiles per level, as
    -- prefix sums over the box (round the center being searched) the columns and their
    -- tunnels can reach
    local reach = WAY_IN_RADIUS + WAY_IN_TUNNEL + 1
    local cur                                 -- the center being searched: {x, y, box, sums}
    local function level_sums(z)
        local s = cur.sums[z]
        if s then return s end
        local b = cur.box
        s = {}
        for x = b.x1 - 1, b.x2 do s[x] = {} end
        for y = b.y1 - 1, b.y2 do s[b.x1 - 1][y] = 0 end
        for x = b.x1, b.x2 do
            s[x][b.y1 - 1] = 0
            for y = b.y1, b.y2 do
                s[x][y] = (inside(x, y, z) and 1 or 0) + s[x - 1][y] + s[x][y - 1] - s[x - 1][y - 1]
            end
        end
        cur.sums[z] = s
        return s
    end
    local function near(z, x, y)
        local r, b = WAY_IN_TUNNEL + 1, cur.box
        local x1, y1 = math.max(b.x1, x - r), math.max(b.y1, y - r)
        local x2, y2 = math.min(b.x2, x + r), math.min(b.y2, y + r)
        if x1 > x2 or y1 > y2 then return false end
        local s = level_sums(z)
        return s[x2][y2] - s[x1 - 1][y2] - s[x2][y1 - 1] + s[x1 - 1][y1 - 1] > 0
    end
    for _, c in ipairs(centers) do
        c.box = {x1 = math.max(0, c.x - reach), y1 = math.max(0, c.y - reach),
                 x2 = math.min(W - 1, c.x + reach), y2 = math.min(H - 1, c.y + reach)}
        c.sums = {}
    end
    -- a tunnel on level z from the column's foot (x, y) to a tile beside the fort's inside
    local function tunnel(x, y, z, budget)
        local seen, queue, head = {[wkey(x, y, z)] = 0}, {{x = x, y = y, d = 0}}, 1
        while head <= #queue do
            local c = queue[head]
            head = head + 1
            for _, s in ipairs(WAY_IN_SIDES) do
                local nx, ny = c.x + s[1], c.y + s[2]
                if inside(nx, ny, z) and gate_dist(nx, ny) >= WAY_IN_GATE_CLEAR then
                    local path, p = {}, c
                    while p.parent do table.insert(path, 1, {x = p.x, y = p.y}); p = p.parent end
                    return path, {x = nx, y = ny, z = z}
                end
            end
            if c.d < budget then
                for _, s in ipairs(WAY_IN_SIDES) do
                    local nx, ny = c.x + s[1], c.y + s[2]
                    local k = wkey(nx, ny, z)
                    if not seen[k] and gate_dist(nx, ny) >= WAY_IN_GATE_CLEAR and safe(nx, ny, z) then
                        seen[k] = true
                        table.insert(queue, {x = nx, y = ny, d = c.d + 1, parent = c})
                    end
                end
            end
        end
    end
    local ctx = {z = sz, target = target, safe = safe, dry_beside = dry_beside, near = near, tunnel = tunnel,
                 best_cost = WAY_IN_MAX_DIG + 1}
    -- (0.105.33, L4) a column whose cells quickfort's dry run refuses is
    -- left out and the search run again (WAY_IN_TRIES times in all)
    local banned, refused_last = {}, nil
    local pri = second and WAY_IN_SECOND_PRIORITY or WAY_IN_PRIORITY
    local best, cells, out
    for attempt = 1, WAY_IN_TRIES do
    ctx.best_cost = WAY_IN_MAX_DIG + 1
    local best_rank
    best = nil
    local whys, tried, near_gate, too_long, no_ground, off_band = {}, {}, 0, 0, 0, 0
    for k in pairs(banned) do tried[k] = true end
    local deadline = math.min(os.clock() + WAY_IN_SECONDS, deadline_all)
    local timed_out = false
    for _, c in ipairs(centers) do
        cur = c
        for r = 0, WAY_IN_RADIUS do
            for dx = -r, r do
                for dy = -r, r do
                    if math.max(math.abs(dx), math.abs(dy)) == r then
                        local x, y = c.x + dx, c.y + dy
                        local k = y * 4096 + x
                        if not tried[k] and x > 1 and y > 1 and x < W - 2 and y < H - 2 then
                            tried[k] = true
                            if os.clock() > deadline then timed_out = true break end
                            if gate_dist(x, y) < WAY_IN_GATE_APART then
                                near_gate = near_gate + 1
                            elseif not in_band(x, y) then
                                off_band = off_band + 1
                            else
                                for _, below in ipairs({true, false}) do
                                    local plan, why, long = way_in_column(ctx, x, y, below)
                                    if plan and second and not (plan.to and in_band(plan.to.x, plan.to.y)
                                            and not (fort.set and fort.set[wkey(plan.to.x, plan.to.y, plan.to.z)])) then
                                        plan, why = nil, nil       -- (its top steps off out of the band, or
                                    end                            -- (fix33) into the fort's inside: a courtyard)
                                    if plan then
                                        local rank = plan.tiles * 1000000 + (x - sx) ^ 2 + (y - sy) ^ 2
                                        if not best_rank or rank < best_rank then
                                            best, best_rank = plan, rank
                                            ctx.best_cost = plan.tiles + 1     -- (a tie: the one nearer them)
                                        end
                                    elseif long then
                                        too_long = too_long + 1
                                    elseif why == WAY_IN_NO_GROUND then
                                        no_ground = no_ground + 1
                                    elseif why then
                                        local w = why:gsub(' at x%d+ y%d+ z%-?%d+', '')
                                        w = w:gsub(' beside x%d+ y%d+ z%-?%d+', ' beside it')
                                        whys[w] = (whys[w] or 0) + 1
                                    end
                                end
                            end
                        end
                    end
                end
                if timed_out then break end
            end
            if timed_out then break end
        end
        if timed_out then break end
    end
    if not best then
        if refused_last then return refuse(refused_last) end
        local words = {}
        for w, n in pairs(whys) do table.insert(words, {w = w, n = n}) end
        table.sort(words, function(a, b) if a.n ~= b.n then return a.n > b.n end return a.w < b.w end)
        local bits = {}
        if too_long > 0 then table.insert(bits, ('the fort is more than %d tiles of digging away'):format(WAY_IN_MAX_DIG)) end
        for i = 1, math.min(2, #words) do table.insert(bits, words[i].w) end
        if #bits == 0 and no_ground > 0 then table.insert(bits, WAY_IN_NO_GROUND) end
        if near_gate > 0 then table.insert(bits, ('the nearer spots are within %d tiles of the gate'):format(WAY_IN_GATE_APART)) end
        return refuse(('no safe %s found near x%d y%d z%d%s%s'):format(second and 'second way in' or 'way in', sx, sy, ez(sz),
            #bits > 0 and ': ' or '', table.concat(bits, '; ')) .. (timed_out and ' (search cut short)' or ''))
    end
    -- (merge32 review) an invader in sight near either end: not now
    -- (0.105.33, L4) nor a great danger (a forgotten beast, a megabeast)
    if GM and type(GM.visible_dangers) == 'function' then
        local okv, vis = pcall(GM.visible_dangers)
        for _, d in ipairs(okv and type(vis) == 'table' and vis or {}) do
            if (d.invader or d.great) and d.pos then
                for _, e in ipairs({best.from, best.to}) do
                    local dd = e and math.max(math.abs(d.pos.x - e.x), math.abs(d.pos.y - e.y), math.abs(d.pos.z - e.z))
                    if dd and dd <= WAY_IN_INVADER_NEAR then
                        return refuse(('%s is in sight %d tiles from where the way in would come out: '
                            .. 'not dug until they are gone'):format(d.invader and 'an invader' or 'a great danger', dd))
                    end
                end
            end
        end
    end
    -- the keys, at the way-in's priority: each tile one quickfort cell
    cells = {}
    for _, c in ipairs(best.cells) do table.insert(cells, {x = c.x, y = c.y, z = c.z, key = c.key}) end
    for _, t in ipairs(best.tunnel) do table.insert(cells, {x = t.x, y = t.y, z = best.z_fort, key = 'd'}) end
    local zlo, zhi = best.z_fort, best.z_fort
    for _, c in ipairs(best.cells) do zlo, zhi = math.min(zlo, c.z), math.max(zhi, c.z) end
    out = {ok = true, from = pos_out(best.from), to = pos_out(best.to), tiles = best.tiles,
           levels = zhi - zlo + 1, column = {x = best.x, y = best.y, elevation_top = ez(zhi), elevation_bottom = ez(zlo)},
           tunnel = #best.tunnel, dry_run = dry_run or nil, second = second or nil}
    if second_e then
        out.entrance = pos_out(second_e)
        out.apart = math.max(math.abs(best.to.x - second_e.x), math.abs(best.to.y - second_e.y))
    end
    for _, c in ipairs(cells) do
        local okd, st = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'run', true)
        if not okd or stat(st, 'dig_designated') ~= 1 then
            refused_last = ('the game would not dig x%d y%d z%d (%s)'):format(c.x, c.y, ez(c.z), c.key)
                .. (okd and dig_guard_note(st) or '')   -- (0.105.40b fix) the guard's why
            banned[best.y * 4096 + best.x] = true
            best = nil
            break
        end
    end
    if best then break end
    end
    if not best then return refuse(refused_last) end
    if dry_run then return out end
    local done, err = pcall(function()
        for _, c in ipairs(cells) do
            local st = quickfort_apply('dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y)
            if stat(st, 'dig_designated') ~= 1 then error(('could not designate x%d y%d z%d'):format(c.x, c.y, ez(c.z))) end
        end
    end)
    local function undo()
        for _, c in ipairs(cells) do pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'undo') end
    end
    if not done then undo() return {ok = false, error = 'designating the way in failed and was undone: ' .. tostring(err)} end
    local x1, y1, x2, y2 = best.x, best.y, best.x, best.y
    local gallery = {}
    for _, t in ipairs(best.tunnel) do
        x1, y1, x2, y2 = math.min(x1, t.x), math.min(y1, t.y), math.max(x2, t.x), math.max(y2, t.y)
        table.insert(gallery, {x = t.x, y = t.y})
    end
    -- (0.105.33, L4) the column's other levels kept out of the quarry, the
    -- vein drifts and other projects too (level_areas)
    local col_areas = {}
    for _, c in ipairs(best.cells) do
        if c.z ~= best.z_fort then
            table.insert(col_areas, {x1 = c.x, y1 = c.y, x2 = c.x, y2 = c.y, z = c.z})
        end
    end
    local p = {
        id = data.next_id, kind = 'way_in', phase = 'dig', emergency = (not second) or nil, second = second or nil,
        params = {pri = pri}, z = best.z_fort, anchor = {x = best.x, y = best.y}, stair = {x = best.x, y = best.y},
        area = {x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = best.z_fort},
        areas = col_areas,
        cells = {dig = {}}, shaft_stairs = best.cells, gallery = gallery,
        from = best.from, to = best.to,
        stranded = (not second) and {x = sx, y = sy, z = sz, group = target} or nil,
        entrance = second_e,
        summary = {way_in = true, emergency = (not second) or nil, second = second or nil, tiles = best.tiles,
                   levels = out.levels, tunnel = #gallery},
        started = now, designated = #cells,
    }
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    if not save_projects(data) then
        undo()
        return {ok = false, error = 'could not save the way in with the fort, so it was undone'}
    end
    out.project_id = p.id
    return out
end
