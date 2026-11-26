-- ai-builder-cistern: the cistern: its plan, its status, its gaps, one step a call.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-cistern'] = '0.105.121'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

-- --- the cistern (water step W2): planned only, nothing dug yet ----------------------
--
-- A cistern: a 5x5 room of solid rock right under a fort floor, at the level
-- of still water nearby (a pool, lake or cavern lake; (r2h1) a river or
-- brook only down the shaft way, through its diagonal step: its water can
-- be under pressure, which never passes a diagonal), joined to it by a one-tile tunnel through
-- solid rock. A floodgate in the tunnel beside the cistern (worked by a
-- lever on the fort floor above) lets water in and shuts it out; the well
-- stands on the fort floor over the cistern's middle. Still water only ever
-- rises to its own level, so it fills the cistern and never comes up the
-- well's hole into the fort. Dug later from the cistern outwards, the last
-- tile beside the water (the plug) cut last, once the floodgate stands.
CISTERN_HALF = 2                 -- a 5x5 room
CISTERN_RADIUS = 30              -- how far from the fort the water may be
CISTERN_MAX_TUNNEL = 30
CISTERN_MIN_WATER = 20           -- tiles of water near the intake (a puddle won't do)
-- (0.104.94) surface water evaporates and freezes: Teacheroar's cistern drew
-- from a stagnant surface pool's edge, which dried to a bare ramp. A surface
-- source needs a bigger body and counts as if 20 tiles further off.
CISTERN_MIN_SURFACE_WATER = 100
CISTERN_SURFACE_PENALTY = 60
CISTERN_DRY_DAYS = 28            -- the source dry this long while filling: the cistern is retired
CISTERN_LEVEL_MIN = 4        -- (0.104.119) this deep and not rising for CISTERN_LEVEL_DAYS: full enough
CISTERN_LEVEL_DAYS = 14
-- (0.104.100) a floodgate shut for a flood (dwarves in deep water) while filling
-- reopens when nobody has stood in deep water this many days; after
-- CISTERN_MAX_REOPENS floods in a row it stays shut and says so
CISTERN_REOPEN_DAYS = 3
CISTERN_MAX_REOPENS = 3

-- Citizens standing in deep water (4/7 or more, not magma) anywhere: the flood sign.
function citizens_in_deep_water()
    local n = 0
    pcall(function()
        for _, p in ipairs(citizen_positions()) do
            local t = tile_info(p.x, p.y, p.z)
            if t and t.liquid and not t.magma and t.depth >= 4 then n = n + 1 end
        end
    end)
    return n
end
CISTERN_LEVELS = 6               -- busiest fort levels tried
CISTERN_SECONDS = 3

local function still_water(t)
    return t ~= nil and t.liquid and not t.magma and not t.salt and t.depth >= 4
        and t.material ~= 'RIVER' and t.material ~= 'BROOK'
end

-- (r2h1) a river's or brook's water (fresh, 4/7 deep at least): a source
-- only down the shaft way, through the diagonal step (pressure never passes
-- a diagonal), never on the room's own level
local function river_water(t)
    return t ~= nil and t.liquid and not t.magma and not t.salt and (t.depth or 0) >= 4
        and (t.material == 'RIVER' or t.material == 'BROOK')
end
local function source_water(t, rivers)
    return still_water(t) or (rivers == true and river_water(t))
end

local DIR8 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}
local DIR4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

-- Water tiles connected to (x, y, z) on its level, counted up to `cap`.
local function water_extent(x, y, z, cap)
    local seen, queue, head = {[x .. ',' .. y] = true}, {{x, y}}, 1
    while head <= #queue and #queue < cap do
        local c = queue[head]
        head = head + 1
        for _, d in ipairs(DIR8) do
            local nx, ny = c[1] + d[1], c[2] + d[2]
            local k = nx .. ',' .. ny
            if not seen[k] then
                local t = tile_info(nx, ny, z)
                if t and t.liquid and not t.magma then
                    seen[k] = true
                    table.insert(queue, {nx, ny})
                end
            end
        end
    end
    return #queue
end

-- (0.100, review) Is this water safe to let into a cistern under the fort?
-- Water under pressure (falling from higher up) rises to one level below
-- its source: a body that also holds water a level up, or that meets a
-- river or brook, could push up the cistern's stair and the well's hole.
-- The connected water on its level (up to `cap` tiles) is checked for water
-- right above it and for river tiles. Returns ok, why.
function water_body_safe(x, y, z, cap)
    cap = cap or 3000
    local seen, queue, head = {[x .. ',' .. y] = true}, {{x, y}}, 1
    while head <= #queue do
        local c = queue[head]
        head = head + 1
        local here = tile_info(c[1], c[2], z)
        if here and (here.material == 'RIVER' or here.material == 'BROOK') then
            return false, 'that water joins a river or brook (it can be under pressure)'
        end
        local up = tile_info(c[1], c[2], z + 1)
        if up and up.liquid then
            return false, 'that water goes on up a level (its weight could push it up into the fort)'
        end
        if #queue < cap then
            for _, d in ipairs(DIR8) do
                local nx, ny = c[1] + d[1], c[2] + d[2]
                local k = nx .. ',' .. ny
                if not seen[k] then
                    seen[k] = true
                    local t = tile_info(nx, ny, z)
                    if t and t.liquid and not t.magma then table.insert(queue, {nx, ny}) end
                end
            end
        end
    end
    -- (review) too big to see all of: not known safe (a cavern lake may hold
    -- water higher up beyond what was looked at)
    if #queue >= cap then return false, 'that water is too big to check for water above it' end
    return true
end

-- The tunnel: from the cistern's wall outwards through solid rock (each
-- tile's 8 neighbours rock, the cistern, the tunnel or, for the plug, the
-- water) to a tile beside still water. {path = {{x, y}...}, water = {x, y}}.
local function tunnel_to_water(c, z, maxlen)
    maxlen = maxlen or CISTERN_MAX_TUNNEL         -- (0.105.3) the brain's cistern_tunnel_max
    local function in_room(x, y) return x >= c.x1 and x <= c.x2 and y >= c.y1 and y <= c.y2 end
    local starts = {}
    for x = c.x1, c.x2 do
        table.insert(starts, {x, c.y1 - 1}); table.insert(starts, {x, c.y2 + 1})
    end
    for y = c.y1, c.y2 do
        table.insert(starts, {c.x1 - 1, y}); table.insert(starts, {c.x2 + 1, y})
    end
    local prev, queue, head = {}, {}, 1
    for _, p in ipairs(starts) do
        local k = p[1] .. ',' .. p[2]
        prev[k] = false
        table.insert(queue, {p[1], p[2], 1})
    end
    while head <= #queue do
        local x, y, n = table.unpack(queue[head])
        head = head + 1
        local t = tile_info(x, y, z)
        if solid_rock(t) then
            -- beside still water: this is the plug
            for _, d in ipairs(DIR4) do
                local w = tile_info(x + d[1], y + d[2], z)
                if still_water(w) then
                    local ok = true
                    for _, e in ipairs(DIR8) do
                        local nx, ny = x + e[1], y + e[2]
                        local nt = tile_info(nx, ny, z)
                        if not (solid_rock(nt) or (nt and nt.liquid and not nt.magma) or in_room(nx, ny)
                                or prev[nx .. ',' .. ny] ~= nil) then
                            ok = false
                        end
                    end
                    if ok and prev[x .. ',' .. y] then      -- (at least two tiles: a floodgate, then the plug)
                        local path = {}
                        local px, py = x, y
                        while true do
                            table.insert(path, 1, {x = px, y = py})
                            local pr = prev[px .. ',' .. py]
                            if not pr then break end
                            px, py = pr[1], pr[2]
                        end
                        return {path = path, water = {x = x + d[1], y = y + d[2]}}
                    end
                end
            end
            if n < maxlen then
                -- (no water even at a corner: water flows diagonally too, so a
                -- tunnel tile touching it would flood when dug)
                local clear = true
                for _, e in ipairs(DIR8) do
                    local nt = tile_info(x + e[1], y + e[2], z)
                    if not (solid_rock(nt) or in_room(x + e[1], y + e[2])) then clear = false end
                end
                if clear then
                    for _, d in ipairs(DIR4) do
                        local nx, ny = x + d[1], y + d[2]
                        local k = nx .. ',' .. ny
                        if prev[k] == nil and not in_room(nx, ny) then
                            prev[k] = {x, y}
                            table.insert(queue, {nx, ny, n + 1})
                        end
                    end
                end
            end
        end
    end
    return nil
end

-- --- the cistern, second design (0.104.145) ------------------------------------
--
-- The player, 31 Oct: the first cistern couldn't work and would have flooded
-- the fort. Water in DF has PRESSURE: water falling onto full water
-- teleports along full tiles to as high as one level under where it came
-- from. The first design dug the cistern on its source's own level (z168)
-- beside a pond that stands on z168-170: pressure could reach z169, the
-- well's level. Its source tile had also dried to a bare ramp.
--
-- Two ways in, both pressure-safe:
--   level  the source on the cistern's own level, its water with nothing above
--          it anywhere in the body (it can never stand higher than the room)
--   shaft  the source up to CISTERN_MAX_RISE levels higher (a deep pond or a
--          cavern lake): a tunnel on the source's level to a shaft of stairs
--          straight down through solid rock to a tile DIAGONAL to the room's
--          corner. Pressure never passes a diagonal, so past it the water
--          only spreads level: it fills the room and can't climb the well's
--          stair. The tunnel and shaft (under pressure) are rock all round,
--          above and below.
-- The AI picks among the sources itself (surface, underground pool, cavern
-- lake), by distance, size, and what the brain tells it (`prefs`: the
-- climate freezes, a danger in the caverns).
CISTERN_V = 2
CISTERN_MAX_RISE = 8
CISTERN_CAVERN_PENALTY = 40
CISTERN_FREEZE_PENALTY = 60
CISTERN_DANGER_PENALTY = 1000
CISTERN_STAGNANT_PENALTY = 20
CISTERN_PREFS_KEY = 'ai-overseer/cistern_prefs'

function cistern_prefs(set)
    if type(set) == 'table' then
        site_put(CISTERN_PREFS_KEY, {freezes = set.freezes == true, cavern_danger = set.cavern_danger == true})
    end
    return site_get(CISTERN_PREFS_KEY)
end

-- every one of the 8 neighbours solid rock (or allowed)
local function ring_solid(x, y, z, allowed)
    for _, e in ipairs(DIR8) do
        local nx, ny = x + e[1], y + e[2]
        if not (allowed and allowed(nx, ny)) and not solid_rock(tile_info(nx, ny, z)) then return false end
    end
    return true
end

-- A river or brook in the body (always under pressure: never a source).
local function body_has_river(x, y, z, cap)
    local seen, queue, head = {[x .. ',' .. y] = true}, {{x, y}}, 1
    while head <= #queue and #queue < (cap or 400) do
        local c = queue[head]
        head = head + 1
        local here = tile_info(c[1], c[2], z)
        if here and (here.material == 'RIVER' or here.material == 'BROOK') then return true end
        for _, d in ipairs(DIR8) do
            local nx, ny = c[1] + d[1], c[2] + d[2]
            local k = nx .. ',' .. ny
            if not seen[k] then
                seen[k] = true
                local t = tile_info(nx, ny, z)
                if t and t.liquid and not t.magma then table.insert(queue, {nx, ny}) end
            end
        end
    end
    return false
end

-- A tile over water that holds it down: a wall, or a floor (a dug tile's
-- floor belongs to it, so water can't rise through it). Not open space, a
-- stair, a ramp or a channel.
local function capped(t)
    return t ~= nil and (t.shape == 'WALL' or t.shape == 'FLOOR') and not t.liquid
end

-- the tunnel under pressure: capped over every tile but the plug
local function tunnel_closed(path, z)
    for i = 1, #path - 1 do
        if not capped(tile_info(path[i].x, path[i].y, z + 1)) then return false end
    end
    return true
end

-- (r2h1) The tunnel to a far source by a best-first search toward `goal`
-- ({x, y}: the survey's nearest tile of the river): the same rules as
-- tunnel_to_water (each tile's 8 neighbours rock, the room or the tunnel; the
-- plug's rock, liquid or the tunnel; at least two tiles), and `capped` (the
-- shaft way: every tile but the plug held down by a wall or floor over it).
-- A river 90-170 tiles off would make the plain search walk a disc of rock
-- that wide (tens of seconds on DF's main thread); this one looks at
-- CISTERN_SEARCH_MAX tiles at most and stops at the deadline. Its `water`
-- is a river's or still water's (source_water(t, true)). nil when none.
CISTERN_SEARCH_MAX = 6000
local function tunnel_to_goal(c, z, maxlen, goal, deadline, need_cap)
    local function in_room(x, y) return x >= c.x1 and x <= c.x2 and y >= c.y1 and y <= c.y2 end
    local function h(x, y) return math.abs(x - goal.x) + math.abs(y - goal.y) end
    local heap = {}
    local function push(e)
        table.insert(heap, e)
        local i = #heap
        while i > 1 do
            local pa = i // 2
            if heap[pa].f <= heap[i].f then break end
            heap[pa], heap[i] = heap[i], heap[pa]
            i = pa
        end
    end
    local function pop()
        local top = heap[1]
        local last = table.remove(heap)
        if #heap > 0 then
            heap[1] = last
            local i = 1
            while true do
                local l, r, m = 2 * i, 2 * i + 1, i
                if l <= #heap and heap[l].f < heap[m].f then m = l end
                if r <= #heap and heap[r].f < heap[m].f then m = r end
                if m == i then break end
                heap[m], heap[i] = heap[i], heap[m]
                i = m
            end
        end
        return top
    end
    local prev, looked = {}, 0
    local starts = {}
    for x = c.x1, c.x2 do table.insert(starts, {x, c.y1 - 1}); table.insert(starts, {x, c.y2 + 1}) end
    for y = c.y1, c.y2 do table.insert(starts, {c.x1 - 1, y}); table.insert(starts, {c.x2 + 1, y}) end
    for _, p in ipairs(starts) do
        local k = p[1] .. ',' .. p[2]
        if prev[k] == nil then prev[k] = false; push({x = p[1], y = p[2], n = 1, f = 1 + h(p[1], p[2])}) end
    end
    while #heap > 0 do
        looked = looked + 1
        if looked > CISTERN_SEARCH_MAX or (deadline and looked % 32 == 0 and os.clock() > deadline) then return nil end
        local e = pop()
        local x, y, n = e.x, e.y, e.n
        local t = tile_info(x, y, z)
        if solid_rock(t) then
            for _, d in ipairs(DIR4) do
                local w = tile_info(x + d[1], y + d[2], z)
                if source_water(w, true) and prev[x .. ',' .. y] then
                    local ok = true
                    for _, q in ipairs(DIR8) do
                        local nx, ny = x + q[1], y + q[2]
                        local nt = tile_info(nx, ny, z)
                        if not (solid_rock(nt) or (nt and nt.liquid and not nt.magma) or in_room(nx, ny)
                                or prev[nx .. ',' .. ny] ~= nil) then
                            ok = false
                        end
                    end
                    if ok then
                        local path = {}
                        local px, py = x, y
                        while true do
                            table.insert(path, 1, {x = px, y = py})
                            local pr = prev[px .. ',' .. py]
                            if not pr then break end
                            px, py = pr[1], pr[2]
                        end
                        return {path = path, water = {x = x + d[1], y = y + d[2]}}
                    end
                end
            end
            if n < maxlen and (not need_cap or capped(tile_info(x, y, z + 1))) then
                local clear = true
                for _, q in ipairs(DIR8) do
                    local nt = tile_info(x + q[1], y + q[2], z)
                    if not (solid_rock(nt) or in_room(x + q[1], y + q[2])) then clear = false break end
                end
                if clear then
                    for _, d in ipairs(DIR4) do
                        local nx, ny = x + d[1], y + d[2]
                        local k = nx .. ',' .. ny
                        if prev[k] == nil and not in_room(nx, ny) then
                            prev[k] = {x, y}
                            push({x = nx, y = ny, n = n + 1, f = n + 1 + h(nx, ny)})
                        end
                    end
                end
            end
        end
    end
    return nil
end

-- (r2h1) a river or brook by its tile's material first (a DF river is a
-- local feature: its tiles carry the feature flag), a cavern lake by a
-- global feature (a tile reader without the two apart: its `feature`)
local function source_kind(w)
    if w.material == 'RIVER' then return 'river' end
    if w.material == 'BROOK' then return 'brook' end
    local cavern = w.feature
    if w.feature_global ~= nil or w.feature_local ~= nil then cavern = w.feature_global == true end
    return cavern and 'cavern lake' or (w.outside and 'surface pool' or 'underground pool')
end

CISTERN_RIVER = true             -- (r2h1) a river or brook a source (down the shaft way only)
CISTERN_RIVER_PENALTY = 20       -- (r2h1) a river's extra: a long tunnel, and its water stops in winter
CISTERN_RIVER_LEVELS = 10        -- (r2h1) fort levels past the busiest tried for a river's shaft (act_survey_water)

-- The score's extra for a source (lower is better) and why, in words.
local function source_cost(w, extent, prefs)
    local kind = source_kind(w)
    local cost, why = 0, {}
    if kind == 'river' or kind == 'brook' then
        -- (r2h1) no freeze penalty: the cistern is filled while it flows and
        -- holds its water underground through the winter (that is its use)
        cost = cost + CISTERN_RIVER_PENALTY
        if prefs.freezes then table.insert(why, 'it freezes in winter: the cistern is filled while it flows') end
    elseif kind == 'surface pool' then
        cost = cost + CISTERN_SURFACE_PENALTY
        if prefs.freezes then cost = cost + CISTERN_FREEZE_PENALTY; table.insert(why, 'it freezes in winter') end
    elseif kind == 'cavern lake' then
        cost = cost + CISTERN_CAVERN_PENALTY
        if prefs.cavern_danger then cost = cost + CISTERN_DANGER_PENALTY; table.insert(why, 'a danger in the caverns') end
    end
    if w.stagnant then cost = cost + CISTERN_STAGNANT_PENALTY; table.insert(why, 'stagnant') end
    cost = cost - math.min(30, extent // 20)
    return cost, kind, why
end

-- The shaft way in, from one of the room's four outer corners. (13c) Also
-- whether the deadline cut it short.
local function shaft_to_water(c, z, water_z, deadline, maxlen, river)
    local corners = {{c.x1 - 1, c.y1 - 1, c.x1, c.y1}, {c.x2 + 1, c.y1 - 1, c.x2, c.y1},
                     {c.x1 - 1, c.y2 + 1, c.x1, c.y2}, {c.x2 + 1, c.y2 + 1, c.x2, c.y2}}
    local found, cut = {}, false
    for _, k in ipairs(corners) do
        local bx, by, rx, ry = k[1], k[2], k[3], k[4]
        local function is_corner(nx, ny) return nx == rx and ny == ry end
        if solid_rock(tile_info(bx, by, z)) and ring_solid(bx, by, z, is_corner) then
            for rise = 1, CISTERN_MAX_RISE do
                if deadline and os.clock() > deadline then cut = true break end
                local zs = z + rise
                if not solid_rock(tile_info(bx, by, zs)) or not ring_solid(bx, by, zs) then break end
                if water_z[zs] and capped(tile_info(bx, by, zs + 1)) then
                    local tun = tunnel_to_water({x1 = bx, y1 = by, x2 = bx, y2 = by}, zs, maxlen)
                    if tun and tunnel_closed(tun.path, zs) then
                        table.insert(found, {tun = tun, zs = zs, shaft = {x = bx, y = by}, corner = {x = rx, y = ry},
                                             rise = rise})
                    end
                end
                -- (r2h1) a river on this level: the goal-directed tunnel to it
                -- (its own reach), through the diagonal step at the shaft's foot
                local rg = river and river.goals[zs]
                if rg and capped(tile_info(bx, by, zs + 1)) then
                    local tun = tunnel_to_goal({x1 = bx, y1 = by, x2 = bx, y2 = by}, zs, river.len, rg, deadline, true)
                    if deadline and os.clock() > deadline then cut = true end
                    if tun and tunnel_closed(tun.path, zs) then
                        local wt = tile_info(tun.water.x, tun.water.y, zs)
                        table.insert(found, {tun = tun, zs = zs, shaft = {x = bx, y = by}, corner = {x = rx, y = ry},
                                             rise = rise, river = river_water(wt) or nil})
                    end
                end
            end
        end
    end
    return found, cut
end

-- The plan (nothing is designated): {v, source, cistern = {x1, y1, x2, y2, z},
-- well, floodgate, plug, tunnel = n tiles, tunnel_path, intake_z, shaft?, lever}
-- or nil, why. first, last: which of the busiest levels to look at (the
-- bridge asks one level a call). The plan carries its `score` (lower is
-- better) and `considered` (the best score of each kind of source).
-- (0.105.3) Hammerstirred (2 Nov): "no tunnel through solid rock from a
-- cistern site to still water" while a 40-tile underground pool lay 53-66
-- survey tiles from the fort, beyond the 30 tiles the tunnel was allowed.
-- `opts.tunnel` (the brain's cistern_tunnel_max) lets the tunnel go further;
-- the area looked at grows with it. Sites that couldn't reach any still water
-- within that many tiles (as the crow flies, a tunnel is never shorter) are
-- skipped, and the rest are tried nearest the water first, so the longer
-- reach costs no more time. The refusal says how far the water was.
-- (13c) Out of time with nothing found: nil, 'search cut short: ...', true.
-- (0.105.38) The tunnel's reach when the survey found no still water near
-- enough for it: the cheapest still, fresh body further off on the whole map
-- (its reach estimate through safe rock, else its distance), up to the map's
-- width (CISTERN_FAR_REACH, the brain's water_far_reach, when set). nil: the
-- asked reach stands (water near enough, or none further off), so a fort
-- with water near plans as before. The tunnel is dug CISTERN_SEGMENT tiles
-- at a time.
CISTERN_FAR_REACH = nil
CISTERN_SEGMENT = 40
-- (0.105.38 review) A tile of the cistern tunnel's next stretch, checked
-- before it is designated: solid rock, or a tile dug open meanwhile that
-- holds no liquid, is no cavern's or aquifer's and is not open sky (review:
-- EMPTY or outside refused).
function tunnel_stretch_ok(t)
    return t ~= nil and (solid_rock(t) or (t.shape ~= 'WALL' and t.shape ~= 'EMPTY' and not t.outside
                                            and not t.liquid and not t.feature and not t.aquifer))
end

function cistern_far_len(maxlen)
    local okw, w = pcall(function() return reqscript('ai-water').last() end)
    if not okw or type(w) ~= 'table' or type(w.waters) ~= 'table' then return nil end
    for _, b in ipairs(type(w.bodies) == 'table' and w.bodies or {}) do
        if b.kind ~= 'river' and b.kind ~= 'cavern' and type(b.nearest) == 'table'
                and (tonumber(b.nearest.d) or math.huge) <= maxlen + CISTERN_HALF + 2 then return nil end
    end
    local m = type(w.map) == 'table' and math.tointeger(tonumber(w.map.w)) or 192
    local cap = math.tointeger(tonumber(CISTERN_FAR_REACH))
    if cap == 0 then return nil end                   -- (0.105.38 review) 0: far sources off
    if not cap or cap < 0 then cap = m end
    local best
    for _, b in ipairs(w.waters) do
        if type(b) == 'table' and b.flow == 'stagnant' and (tonumber(b.salt_share) or 0) == 0 and type(b.nearest) == 'table' then
            local cost = tonumber(b.reach) or tonumber(b.d)
            if cost and cost > maxlen and cost <= cap and (not best or cost < best) then best = cost end
        end
    end
    return best and math.min(cap, math.tointeger(best) + CISTERN_HALF + 4) or nil
end

-- (r2h1) The rivers and brooks the last survey found (region4's: ~90 tiles
-- from the stair, ten levels down, so no moat or wheel takes it): {goals =
-- {[z] = {x, y}} (each level's nearest tile, the tunnel's heading), len =
-- the tunnel's reach for them (the dearest one's reach estimate, else its
-- distance, and a margin), levels = {z...}} or nil (none, rivers off, far
-- sources off: CISTERN_FAR_REACH 0). Up to the map's width or the brain's
-- water_far_reach, as for far still water.
function cistern_rivers()
    if not CISTERN_RIVER then return nil end
    local okw, w = pcall(function() return reqscript('ai-water').last() end)
    if not okw or type(w) ~= 'table' then return nil end
    local m = type(w.map) == 'table' and math.tointeger(tonumber(w.map.w)) or 192
    local cap = math.tointeger(tonumber(CISTERN_FAR_REACH))
    if cap == 0 then return nil end
    if not cap or cap < 0 then cap = m end
    local out, len = {goals = {}, levels = {}}, nil
    local function add(b, flowing)
        if type(b) ~= 'table' or not flowing or (tonumber(b.salt_share) or 0) > 0 then return end
        local n = type(b.nearest) == 'table' and b.nearest or nil
        local nz = n and math.tointeger(tonumber(n.z))
        if not nz or not tonumber(n.x) or not tonumber(n.y) then return end
        local cost = tonumber(b.reach) or tonumber(b.reach_through) or tonumber(b.d)
        if not cost or cost > cap then return end
        if not out.goals[nz] then
            out.goals[nz] = {x = math.tointeger(tonumber(n.x)), y = math.tointeger(tonumber(n.y))}
            table.insert(out.levels, nz)
        end
        local l = math.min(cap, math.tointeger(math.floor(cost)) + CISTERN_HALF + 6)
        if not len or l > len then len = l end
    end
    for _, b in ipairs(type(w.waters) == 'table' and w.waters or {}) do
        add(b, type(b) == 'table' and b.flow == 'flowing')
    end
    for _, b in ipairs(type(w.bodies) == 'table' and w.bodies or {}) do
        add(b, type(b) == 'table' and (b.kind == 'river' or b.kind == 'brook'))
    end
    if not len then return nil end
    out.len = len
    return out
end

function plan_cistern(first, last, opts)
    opts = type(opts) == 'table' and opts or {}
    local maxlen = math.tointeger(tonumber(opts.tunnel)) or CISTERN_MAX_TUNNEL
    if maxlen < 2 then maxlen = CISTERN_MAX_TUNNEL end
    local okf, far_len = pcall(cistern_far_len, maxlen)
    if okf and far_len and far_len > maxlen then maxlen = far_len end
    -- (r2h1) a river or brook, reached down the shaft way by its own tunnel
    local okr, river = pcall(cistern_rivers)
    if not okr or opts.rivers == false then river = nil end
    local reach_len = math.max(maxlen, river and river.len or 0)
    local area = fort_scan_area(math.max(CISTERN_RADIUS, reach_len + CISTERN_HALF + 2))
    if not area then return nil, 'no citizens' end
    local prefs = cistern_prefs()
    local deadline = os.clock() + CISTERN_SECONDS
    local best, best_score, why, cut = nil, nil, nil, false
    local considered = {}
    local nearest_water        -- (0.105.3) the nearest still water to any fort floor looked at
    -- (0.105.3) the wider box costs time: only the levels the last survey
    -- found still water on are sampled (all of them when there's no survey),
    -- and fort floors are looked for only within the old margin of the dwarves
    local wet_levels
    local okw, wl = pcall(function() return reqscript('ai-water').last() end)
    if okw and type(wl) == 'table' and type(wl.bodies) == 'table' then
        wet_levels = {}
        for _, b in ipairs(wl.bodies) do
            if b.kind ~= 'river' and tonumber(b.z1) and tonumber(b.z2) then
                for zz = b.z1, b.z2 do wet_levels[zz] = true end
            end
        end
        -- (0.105.38) a reach grown past the near box: the whole map's still water's levels too
        if okf and far_len then
            for _, b in ipairs(type(wl.waters) == 'table' and wl.waters or {}) do
                if type(b) == 'table' and b.flow == 'stagnant' and tonumber(b.z1) and tonumber(b.z2) then
                    for zz = b.z1, b.z2 do wet_levels[zz] = true end
                end
            end
        end
        if river then for _, zz in ipairs(river.levels) do wet_levels[zz] = true end end    -- (r2h1)
    end
    local inner = fort_scan_area(CISTERN_RADIUS)
    for i = first or 1, math.min(last or CISTERN_LEVELS, #area.levels) do
        local zw = area.levels[i].z
        local z = zw - 1
        -- the levels with still water near the fort, from the cistern's up
        -- (0.105.3) and the tiles of it, sampled, for the reach test
        local water_z, any = {}, false
        local W_ = area.x2 - area.x1 + 1
        local dist, queue = {}, {}
        local river_any = false       -- (r2h1) a river 1-8 levels over the cistern's level
        for zz = z, z + CISTERN_MAX_RISE do
            local rl = river and zz > z and river.goals[zz] ~= nil
            for y = area.y1, (wet_levels == nil or wet_levels[zz]) and area.y2 or area.y1 - 1, 2 do
                for x = area.x1, area.x2, 2 do
                    local t = tile_info(x, y, zz)
                    local st_ = still_water(t)
                    if st_ or (rl and river_water(t)) then
                        if st_ then water_z[zz] = true else river_any = true end
                        local k = (y - area.y1) * W_ + (x - area.x1)
                        if not dist[k] then dist[k] = 0; table.insert(queue, {x, y}) end
                    end
                end
            end
            if water_z[zz] then any = true end
        end
        if river_any then any = true end
        if any then
            -- (0.105.3) every column's distance to the nearest still water
            -- (8-way spread: Chebyshev tiles), then the sites in reach, nearest first
            local reach = maxlen + CISTERN_HALF + 2
            if river_any then reach = math.max(reach, river.len + CISTERN_HALF + 2) end
            local head = 1
            while head <= #queue do
                -- (0.105.4 review) the spread over the wider box under the plan's own deadline
                if os.clock() > deadline then cut = true break end
                local q = queue[head]
                head = head + 1
                local d0 = dist[(q[2] - area.y1) * W_ + (q[1] - area.x1)]
                for _, e in ipairs(DIR8) do
                    local nx, ny = q[1] + e[1], q[2] + e[2]
                    if nx >= area.x1 and nx <= area.x2 and ny >= area.y1 and ny <= area.y2 then
                        local k = (ny - area.y1) * W_ + (nx - area.x1)
                        if not dist[k] then dist[k] = d0 + 1; table.insert(queue, {nx, ny}) end
                    end
                end
            end
            local sites = {}
            for y = math.max(area.y1, inner.y1) + 4, math.min(area.y2, inner.y2) - 4 do
                for x = math.max(area.x1, inner.x1) + 4, math.min(area.x2, inner.x2) - 4 do
                    local f = tile_info(x, y, zw)
                    if f and f.shape == 'FLOOR' and not f.outside and area.groups[walk_group(x, y, zw)] then
                        local d = dist[(y - area.y1) * W_ + (x - area.x1)]
                        if d then
                            if not nearest_water or d < nearest_water then nearest_water = d end
                            if d <= reach then table.insert(sites, {x, y, d}) end
                        end
                    end
                end
            end
            table.sort(sites, function(a, b) return a[3] < b[3] end)
            for _, site in ipairs(sites) do
                if os.clock() > deadline then cut = true break end
                do
                    local x, y = site[1], site[2]
                    -- a fort floor for the well, a solid 7x7 of rock under it, and
                    -- nothing over the room the water could climb into (a floor or a wall)
                    local f = tile_info(x, y, zw)
                    if f and f.shape == 'FLOOR' and not f.outside and not f.building and not f.liquid
                            and area.groups[walk_group(x, y, zw)] and not building_at(x, y, zw) then
                        local ok = true
                        for dy = -CISTERN_HALF - 1, CISTERN_HALF + 1 do
                            for dx = -CISTERN_HALF - 1, CISTERN_HALF + 1 do
                                if not solid_rock(tile_info(x + dx, y + dy, z)) then ok = false break end
                                if math.abs(dx) <= CISTERN_HALF and math.abs(dy) <= CISTERN_HALF then
                                    if not capped(tile_info(x + dx, y + dy, zw)) then ok = false break end
                                end
                            end
                            if not ok then break end
                        end
                        if ok then
                            local c = {x1 = x - CISTERN_HALF, y1 = y - CISTERN_HALF,
                                       x2 = x + CISTERN_HALF, y2 = y + CISTERN_HALF, z = z}
                            local options = {}
                            -- level: the source on the room's level, nothing over its water
                            if water_z[z] then
                                local tun = tunnel_to_water(c, z, maxlen)
                                if tun and water_body_safe(tun.water.x, tun.water.y, z) then
                                    table.insert(options, {tun = tun, zs = z, rise = 0})
                                elseif tun then
                                    local _, unsafe = water_body_safe(tun.water.x, tun.water.y, z)
                                    why = why or unsafe
                                end
                            end
                            -- shaft: the source higher up, through a diagonal
                            local shafts, scut = shaft_to_water(c, z, water_z, deadline, maxlen, river_any and river or nil)
                            if scut then cut = true end
                            for _, o in ipairs(shafts) do table.insert(options, o) end
                            if #options == 0 then
                                why = why or 'no tunnel through solid rock from a cistern site to still water'
                            end
                            for _, o in ipairs(options) do
                                local tun, zs = o.tun, o.zs
                                local w = tile_info(tun.water.x, tun.water.y, zs)
                                local ext = water_extent(tun.water.x, tun.water.y, zs, 600)
                                if not w then
                                    -- (gone)
                                elseif ext < CISTERN_MIN_WATER then
                                    why = 'the still water reachable is only a puddle'
                                elseif w.outside and ext < CISTERN_MIN_SURFACE_WATER then
                                    why = 'the surface water reachable is too small (it dries up and freezes)'
                                elseif not o.river and body_has_river(tun.water.x, tun.water.y, zs) then
                                    why = 'that water joins a river or brook (it can be under pressure)'
                                else
                                    local cost, kind, whys = source_cost(w, ext, prefs)
                                    local score = #tun.path * 3 + o.rise * 4 + math.abs(x - area.cx) + math.abs(y - area.cy)
                                        + (i - 1) * 20 + cost
                                    if not considered[kind] or score < considered[kind] then considered[kind] = score end
                                    -- (0.105.33 L5) only a plan with a spot for its lever: one
                                    -- without was dug in full and then stalled at the lever for ever
                                    local lever = (not best_score or score < best_score) and cistern_lever_spot(x, y, zw) or nil
                                    if (not best_score or score < best_score) and not lever then
                                        why = 'no free floor for the floodgate\'s lever near the well'
                                    elseif not best_score or score < best_score then
                                        best_score = score
                                        best = {v = CISTERN_V, score = score, cistern = c, well = {x = x, y = y, z = zw},
                                                floodgate = tun.path[1], plug = tun.path[#tun.path],
                                                tunnel = #tun.path, tunnel_path = tun.path, water = tun.water,
                                                intake_z = zs, shaft = o.shaft, corner = o.corner, rise = o.rise,
                                                source = kind, source_why = #whys > 0 and table.concat(whys, ', ') or nil,
                                                stagnant = w.stagnant or nil, extent = ext,
                                                elevation = ez(z), intake_elevation = ez(zs), lever = lever,
                                                river = o.river or nil}
                                    end
                                end
                            end
                        end
                    end
                end
            end
        end
    end
    if best then
        best.considered = considered
        -- a lever on the fort floor beside the well (found as `best` was chosen)
        return best
    end
    if cut then
        return nil, 'search cut short: the cistern search ran out of time' .. (why and ('; ' .. why) or ''), true
    end
    why = why or 'no still, fresh water near the fort within reach of a cistern under a fort level'
    -- (0.105.3) how far it was, and how far a tunnel may go
    if nearest_water then
        why = why .. (' (the nearest still water on a cistern\'s levels is %d tiles from a fort floor; a tunnel reaches %d)')
            :format(nearest_water, maxlen)
    else
        local okr, far = pcall(water_reach_words, {pool = true, cavern = true, surface = true}, {{x = area.cx, y = area.cy}})
        if okr and far ~= '' then why = why .. ' (' .. far .. ', not on a level 0-' .. CISTERN_MAX_RISE .. ' over a cistern under a fort floor)' end
    end
    return nil, why
end

-- (0.105.33 L5) A spot for the floodgate's lever: a free fort floor 2 tiles
-- from the well (as before), else 3 tiles off. nil when there is none.
function cistern_lever_spot(wx, wy, zw)
    for r = 2, 3 do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local lx, ly = wx + dx, wy + dy
                    local t = tile_info(lx, ly, zw)
                    if t and t.shape == 'FLOOR' and not t.building and not building_at(lx, ly, zw) then
                        return {x = lx, y = ly, z = zw}
                    end
                end
            end
        end
    end
    return nil
end

-- (0.104.145) Is the cistern still closed where the water goes? The room's
-- ring (rock but the well's stair and the corner or tunnel), rock under the
-- room, a floor or wall over it but the well; the tunnel and shaft rock all
-- round. Returns ok, where (in words) when not.
-- (0.104.168) and, when not, every open spot found: {x, y, z, fix = 'wall' |
-- 'floor' | nil (nothing the AI can build there), words}, so the AI can close
-- them itself (cistern_close_gaps); `where` is still the first.
-- (r2h1) The water works' outlets from this cistern: the muddied farm
-- level fed from a river-fed cistern (ai-waterworks plan_irrigation, its plan
-- `cistern_fed`) cuts its plug through the room's wall, its own floodgate in
-- its tunnel (that tunnel checked by the water works). Its plug and tunnel
-- are no gap in the cistern's wall: {["x,y,z"] = true}.
function cistern_outlets(p)
    local out = {}
    pcall(function()
        local st = reqscript('ai-waterworks').load_state()
        local wk = type(st) == 'table' and type(st.works) == 'table' and st.works.irrigation or nil
        local q = type(wk) == 'table' and wk.plan or nil
        if type(q) ~= 'table' or type(q.cistern_fed) ~= 'table' or wk.stage == 'retired' then return end
        local f = q.cistern_fed
        if f.x1 ~= p.cistern.x1 or f.y1 ~= p.cistern.y1 or f.z ~= p.cistern.z then return end
        for _, list in ipairs({{q.plug or {}}, q.upstream or {}, {q.gate or {}}}) do
            for _, c in ipairs(list) do
                if c.x and c.y and c.z then out[c.x .. ',' .. c.y .. ',' .. c.z] = true end
            end
        end
    end)
    return out
end

function cistern_sealed(p, stage)
    local d_stage_hole = stage == 'hole' or stage == 'well' or stage == 'done'
    local c, z = p.cistern, p.cistern.z
    local zi = p.intake_z or z
    local open_ = cistern_outlets(p)
    local function mark(x, y, zz) open_[x .. ',' .. y .. ',' .. zz] = true end
    for yy = c.y1, c.y2 do for xx = c.x1, c.x2 do mark(xx, yy, z) end end
    for _, t in ipairs(p.tunnel_path or {}) do mark(t.x, t.y, zi) end
    if p.shaft then
        for zz = z, zi do mark(p.shaft.x, p.shaft.y, zz) end
    end
    local function closed(x, y, zz)
        if open_[x .. ',' .. y .. ',' .. zz] then return true end
        local t = tile_info(x, y, zz)
        -- (review) any wall holds water, a built one too (the player's repair)
        return (t ~= nil and t.shape == 'WALL' and not t.liquid)
            or (t and t.liquid and zz == zi and x == p.water.x and y == p.water.y)
    end
    local function where(x, y, zz) return ('x%d y%d elevation %d'):format(x, y, ez(zz)) end
    -- (0.104.168) every gap collected (each tile once), not just the first
    local gaps, seen_gap = {}, {}
    local function gap(fix, words, x, y, zz)
        local k = x .. ',' .. y .. ',' .. zz
        if seen_gap[k] then return end
        seen_gap[k] = true
        table.insert(gaps, {x = x, y = y, z = zz, fix = fix, words = words .. where(x, y, zz)})
    end
    -- the room: its ring and what lies under and over it
    for yy = c.y1 - 1, c.y2 + 1 do
        for xx = c.x1 - 1, c.x2 + 1 do
            local inside = xx >= c.x1 and xx <= c.x2 and yy >= c.y1 and yy <= c.y2
            if not inside and not closed(xx, yy, z) then gap('wall', 'the cistern\'s wall is open at ', xx, yy, z) end
            if inside then
                local here = tile_info(xx, yy, z)
                if here and (here.shape == 'EMPTY' or here.shape == 'RAMP_TOP' or here.shape == 'STAIR_DOWN'
                        or here.shape == 'STAIR_UPDOWN' or here.shape == 'RAMP')
                        and not (xx == p.well.x and yy == p.well.y and d_stage_hole) then
                    gap('floor', 'the cistern\'s floor is open at ', xx, yy, z)
                end
                if not (xx == p.well.x and yy == p.well.y) and not capped(tile_info(xx, yy, z + 1)) then
                    gap('floor', 'the cistern\'s roof is open at ', xx, yy, z + 1)
                end
            end
        end
    end
    -- the tunnel (under pressure): rock all round, over and under; the plug's water side excepted
    local path = p.tunnel_path or {}
    for i = 1, #path - 1 do
        local q = path[i]
        for _, e in ipairs(DIR8) do
            local nx, ny = q.x + e[1], q.y + e[2]
            local zz = zi
            local inroom = zi == z and nx >= c.x1 and nx <= c.x2 and ny >= c.y1 and ny <= c.y2
            if not inroom and not closed(nx, ny, zz) then
                -- (water beside the plug's neighbours is the source itself)
                local t = tile_info(nx, ny, zz)
                if not (t and t.liquid and math.abs(nx - p.plug.x) <= 1 and math.abs(ny - p.plug.y) <= 1) then
                    gap('wall', 'the cistern\'s tunnel is open at ', nx, ny, zz)
                end
            end
        end
        if p.shaft and not capped(tile_info(q.x, q.y, zi + 1)) then
            gap('floor', 'the tunnel\'s roof is open at ', q.x, q.y, zi + 1)
        end
    end
    -- the tunnel's own tiles: dug floors (a channel or a stair would let it down)
    for i = 1, #path - 1 do
        local q = tile_info(path[i].x, path[i].y, zi)
        if q and (q.shape == 'EMPTY' or q.shape == 'RAMP_TOP' or q.shape == 'STAIR_DOWN' or q.shape == 'STAIR_UPDOWN') then
            gap('floor', 'the cistern\'s tunnel floor is open at ', path[i].x, path[i].y, zi)
        end
    end
    -- the shaft: rock all round on every level, the corner diagonal at the bottom
    if p.shaft then
        local foot = tile_info(p.shaft.x, p.shaft.y, z)
        if foot and foot.shape ~= 'STAIR_UP' and foot.shape ~= 'WALL' then
            gap(nil, 'the shaft\'s foot is open below at ', p.shaft.x, p.shaft.y, z)
        end
        for zz = z, zi do
            for _, e in ipairs(DIR8) do
                local nx, ny = p.shaft.x + e[1], p.shaft.y + e[2]
                local ok_ = closed(nx, ny, zz) or (zz == z and p.corner and nx == p.corner.x and ny == p.corner.y)
                if not ok_ then gap('wall', 'the cistern\'s shaft is open at ', nx, ny, zz) end
            end
        end
        if not capped(tile_info(p.shaft.x, p.shaft.y, zi + 1)) then
            gap('floor', 'the shaft\'s top is open at ', p.shaft.x, p.shaft.y, zi + 1)
        end
    end
    if #gaps > 0 then return false, gaps[1].words, gaps end
    return true
end

-- (r8) The file goes on in ai-builder-cistern-status.lua (the saved cistern, its status,
-- its levers, retiring it, closing its gaps) and ai-builder-cistern-step.lua (one step a
-- call), loaded right after this one. The top-level locals they use, handed on:
CISTERN_PART_LOCALS = {DIR8 = DIR8, still_water = still_water, river_water = river_water}
