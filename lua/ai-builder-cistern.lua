-- ai-builder-cistern: the cistern: its plan, its status, its gaps, one step a call.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-cistern'] = '0.105.25'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

-- --- the cistern (water step W2): planned only, nothing dug yet ----------------------
--
-- A cistern: a 5x5 room of solid rock right under a fort floor, at the level
-- of still water nearby (a pool, lake or cavern lake: never a river, whose
-- water can be under pressure), joined to it by a one-tile tunnel through
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

local function source_kind(w)
    return w.feature and 'cavern lake' or (w.outside and 'surface pool' or 'underground pool')
end

-- The score's extra for a source (lower is better) and why, in words.
local function source_cost(w, extent, prefs)
    local kind = source_kind(w)
    local cost, why = 0, {}
    if kind == 'surface pool' then
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
local function shaft_to_water(c, z, water_z, deadline, maxlen)
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
function plan_cistern(first, last, opts)
    opts = type(opts) == 'table' and opts or {}
    local maxlen = math.tointeger(tonumber(opts.tunnel)) or CISTERN_MAX_TUNNEL
    if maxlen < 2 then maxlen = CISTERN_MAX_TUNNEL end
    local area = fort_scan_area(math.max(CISTERN_RADIUS, maxlen + CISTERN_HALF + 2))
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
        for zz = z, z + CISTERN_MAX_RISE do
            for y = area.y1, (wet_levels == nil or wet_levels[zz]) and area.y2 or area.y1 - 1, 2 do
                for x = area.x1, area.x2, 2 do
                    if still_water(tile_info(x, y, zz)) then
                        water_z[zz] = true
                        local k = (y - area.y1) * W_ + (x - area.x1)
                        if not dist[k] then dist[k] = 0; table.insert(queue, {x, y}) end
                    end
                end
            end
            if water_z[zz] then any = true end
        end
        if any then
            -- (0.105.3) every column's distance to the nearest still water
            -- (8-way spread: Chebyshev tiles), then the sites in reach, nearest first
            local reach = maxlen + CISTERN_HALF + 2
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
                            local shafts, scut = shaft_to_water(c, z, water_z, deadline, maxlen)
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
                                elseif body_has_river(tun.water.x, tun.water.y, zs) then
                                    why = 'that water joins a river or brook (it can be under pressure)'
                                else
                                    local cost, kind, whys = source_cost(w, ext, prefs)
                                    local score = #tun.path * 3 + o.rise * 4 + math.abs(x - area.cx) + math.abs(y - area.cy)
                                        + (i - 1) * 20 + cost
                                    if not considered[kind] or score < considered[kind] then considered[kind] = score end
                                    if not best_score or score < best_score then
                                        best_score = score
                                        best = {v = CISTERN_V, score = score, cistern = c, well = {x = x, y = y, z = zw},
                                                floodgate = tun.path[1], plug = tun.path[#tun.path],
                                                tunnel = #tun.path, tunnel_path = tun.path, water = tun.water,
                                                intake_z = zs, shaft = o.shaft, corner = o.corner, rise = o.rise,
                                                source = kind, source_why = #whys > 0 and table.concat(whys, ', ') or nil,
                                                stagnant = w.stagnant or nil, extent = ext,
                                                elevation = ez(z), intake_elevation = ez(zs)}
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
        -- a lever on the fort floor beside the well
        for _, d in ipairs(DIR8) do
            local lx, ly = best.well.x + d[1] * 2, best.well.y + d[2] * 2
            local t = tile_info(lx, ly, best.well.z)
            if t and t.shape == 'FLOOR' and not t.building and not building_at(lx, ly, best.well.z) then
                best.lever = {x = lx, y = ly, z = best.well.z}
                break
            end
        end
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

-- (0.104.145) Is the cistern still closed where the water goes? The room's
-- ring (rock but the well's stair and the corner or tunnel), rock under the
-- room, a floor or wall over it but the well; the tunnel and shaft rock all
-- round. Returns ok, where (in words) when not.
-- (0.104.168) and, when not, every open spot found: {x, y, z, fix = 'wall' |
-- 'floor' | nil (nothing the AI can build there), words}, so the AI can close
-- them itself (cistern_close_gaps); `where` is still the first.
function cistern_sealed(p, stage)
    local d_stage_hole = stage == 'hole' or stage == 'well' or stage == 'done'
    local c, z = p.cistern, p.cistern.z
    local zi = p.intake_z or z
    local open_ = {}
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

-- --- building the cistern: one step a call ------------------------------------------
--
--   dig       stairs down from the well spot into the cistern's middle, the
--             room and the tunnel dug (all but the plug)
--   build     the floodgate (first tunnel tile) and the lever placed
--   link      the lever linked to the floodgate
--   open      the floodgate opened (a pull) so the water can come through
--   plug      the plug dug: the water comes in (the miner goes back out
--             through the open floodgate and up the stairs)
--   fill      waiting for 6/7 in the cistern, then the floodgate shut
--   hole      the down stair over the cistern channelled into the well's hole
--   well      the well built over it
--   done      kept: the AI opens the floodgate when the cistern falls under
--             3/7 and shuts it at 6/7 (cistern_status reports it)
-- State in site data 'ai-overseer/cistern'.
CISTERN_KEY = 'ai-overseer/cistern'
CISTERN_FULL, CISTERN_LOW = 6, 3

function cistern_data()
    local d = site_get(CISTERN_KEY)
    return d.stage and d or nil
end

local function save_cistern(d) site_put(CISTERN_KEY, d) end

-- The game's own clock (not now_tick: the tests swap that one for the projects').
local function game_tick()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and t or 0
end

local function room_tiles(c)
    local out = {}
    for y = c.y1, c.y2 do
        for x = c.x1, c.x2 do table.insert(out, {x = x, y = y}) end
    end
    return out
end

-- {id, built, closed} of the building of `kind` at a tile, or nil.
local function building_info(x, y, z, kind)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b then return nil end
    local okt, t = pcall(function() return df.building_type[b:getType()] end)
    if kind and (not okt or t ~= kind) then return nil end
    local closed
    pcall(function() closed = b.gate_flags.closed end)
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage(), closed = closed}
end

-- (0.100, review) a pull already waiting for a dwarf: a second one queued
-- now would undo it (two pulls shut the floodgate and open it again)
function lever_pull_pending(lever_id)
    local ok, yes = pcall(function()
        local b = df.building.find(lever_id)
        for _, j in ipairs(b and b.jobs or {}) do
            if j.job_type == df.job_type.PullLever then return true end
        end
        return false
    end)
    return ok and yes
end

-- instant: the lever acts now, no dwarf needed (DFHack's lever --instant),
-- for a flood in the fort, when the lever may stand in the water
function pull(lever_id, instant)
    if not instant and lever_pull_pending(lever_id) then
        return true, 'a dwarf is already on the way to pull it', true
    end
    local args = {'lever', 'pull', '--id', tostring(lever_id)}
    if instant then table.insert(args, '--instant') end
    local out, rv = dfhack.run_command_silent(table.unpack(args))
    return rv == CR_OK, tostring(out or '')
end

-- Items of a kind the fort has: free (no building, job or trader holds them,
-- not forbidden) and reserved (a job holds them: a construction waiting is
-- getting its part).
function count_items(tname)
    local free, reserved = 0, 0
    pcall(function()
        for _, item in ipairs(df.global.world.items.other[tname]) do
            if not item_held(item) then
                if item.flags.in_job then reserved = reserved + 1 else free = free + 1 end
            end
        end
    end)
    return free, reserved
end

-- (0.104.94) What lies on the water's way in: each tunnel tile, the plug and
-- the source (shape and depth, or ice): Teacheroar's cistern sat at 0/7 for
-- hours with nothing to say why.
function cistern_path(p)
    local z = p.intake_z or p.cistern.z
    local function desc(pt)
        local t = pt and tile_info(pt.x, pt.y, z)
        if not t then return '?' end
        if t.material == 'FROZEN_LIQUID' then return 'ice' end
        local sh = tostring(t.shape):lower()
        if sh == 'wall' then sh = 'wall (' .. tostring(t.material):lower() .. (t.designated and ', marked' or '') .. ')' end
        return t.liquid and (sh .. ' ' .. t.depth .. '/7') or sh
    end
    local tunnel = {}
    for i = 1, #(p.tunnel_path or {}) - 1 do table.insert(tunnel, desc(p.tunnel_path[i])) end
    return {tunnel = tunnel, plug = desc(p.plug), source = desc(p.water)}
end

local function path_words(path)
    return ('tunnel %s; plug %s; source %s'):format(#path.tunnel > 0 and table.concat(path.tunnel, ', ') or 'none',
                                                    path.plug, path.source)
end

-- How it stands: stage, depth in the cistern's middle, the floodgate's state.
function cistern_status()
    local d = cistern_data()
    if not d then return nil end
    local p = d.plan
    local t = tile_info(p.well.x, p.well.y, p.cistern.z)
    local gate = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
    local out = {stage = d.stage, depth = t and t.liquid and t.depth or 0, source = p.source,
            gate = gate and (gate.built and (gate.closed and 'shut' or 'open') or 'planned') or nil,
            elevation = ez(p.cistern.z), x = p.well.x, y = p.well.y,
            -- (0.104.145) the design, where the water comes from, a leak seen
            v = p.v or 1, intake_elevation = p.intake_z and ez(p.intake_z) or nil, shaft = p.shaft and true or nil,
            source_why = p.source_why, leak = d.leak, unsealed = d.unsealed,
            -- (0.104.168) why the AI can't close a gap itself (the player's then),
            -- and how many walls/floors it placed to close them
            unsealed_why = d.unsealed and d.unsealed_why or nil, sealing = nil}
    if d.unsealed and type(d.sealing) == 'table' then
        local n = 0
        for _ in pairs(d.sealing) do n = n + 1 end
        out.sealing = n > 0 and n or nil
    end
    if d.stage == 'filling' or d.stage == 'plug' then
        local okp, path = pcall(cistern_path, p)
        out.path = okp and path or nil
    end
    -- (0.104.145, review) every report while water can come in: still closed?
    -- (a dig beside the shaft or tunnel later floods that level)
    if gate and gate.built and not gate.closed then
        local oks, sealed, where = pcall(cistern_sealed, p, d.stage)
        if oks then
            out.sealed_now = sealed == true
            out.unsealed = (sealed ~= true) and where or d.unsealed
        end
    end
    -- (0.92.1) while its parts wait: the lever's state, and the floodgates and
    -- mechanisms there are (free, or taken by a job): the floodgate waited two
    -- years in region2 for a floodgate nobody made, the lever for a mechanism
    if d.stage == 'building' or d.stage == 'linking' then
        local lever = p.lever and building_info(p.lever.x, p.lever.y, p.well.z, 'Trap')
        out.lever = lever and (lever.built and 'built' or 'planned') or nil
        -- (0.104.141) the relinks asked for, whether linked, where the lever and
        -- the gate are, and why DF dropped the last link job (when it said)
        if d.stage == 'linking' then
            out.relinks = math.tointeger(d.relinks) or 0
            pcall(function()
                local lv = df.building.find(d.lever_id)
                for _, j in ipairs(lv and lv.jobs or {}) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then
                        out.link_pending = true
                        -- (0.104.143) whether a dwarf has taken it, or it is suspended
                        out.link_worker = dfhack.job.getWorker(j) ~= nil
                        out.link_suspended = j.flags.suspend or nil
                    end
                end
            end)
            -- (0.104.143) can the dwarves get beside the lever and the floodgate
            -- (a linker carries the mechanisms to both)?
            local function reach(x, y, z)
                local groups = {}
                pcall(function()
                    for _, u in ipairs(dfhack.units.getCitizens(true)) do
                        local g = dfhack.maps.getWalkableGroup(xyz2pos(dfhack.units.getPosition(u)))
                        if g and g ~= 0 then groups[g] = true end
                    end
                end)
                local seen = false
                for dy = -1, 1 do
                    for dx = -1, 1 do
                        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x + dx, y + dy, z))
                        if okg and g and g ~= 0 then
                            if groups[g] then return 'reachable' end
                            seen = true
                        end
                    end
                end
                return seen and 'cut off from the dwarves' or 'no open ground beside it'
            end
            pcall(function()
                if p.lever then out.lever_reach = reach(p.lever.x, p.lever.y, p.well.z) end
                out.gate_reach = reach(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z)
            end)
            out.link_why = d.link_why
            -- (0.104.143) with the elevation the game's screen shows (e)
            out.lever_at = p.lever and {x = p.lever.x, y = p.lever.y, z = p.well.z, e = ez(p.well.z)} or nil
            out.gate_at = {x = p.floodgate.x, y = p.floodgate.y, z = p.intake_z or p.cistern.z, e = ez(p.intake_z or p.cistern.z)}
            pcall(function()
                for _, lid in ipairs(reqscript('ai-gates').lever_links()[d.gate_id] or {}) do
                    if lid == d.lever_id then out.linked = true end
                end
            end)
        end
        out.floodgates_free, out.floodgates_reserved = count_items('FLOODGATE')
        -- (0.94.1) counted as the lever's link takes them (ai-gates), with
        -- what holds the ones it can't use
        local okg, mc = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
        if okg and mc then
            out.mechanisms_free, out.mechanisms_reserved = mc.usable, mc.reserved
            if next(mc.why) then out.mechanisms_held = mc.why end
        else
            out.mechanisms_free, out.mechanisms_reserved = count_items('TRAPPARTS')
        end
    end
    return out
end

-- Shut the cistern's floodgate now (a flood in the fort), whatever the stage.
function cistern_shut(dry_run)
    local d = cistern_data()
    if not d or not d.lever_id then return {ok = false, rejected = true, error = 'no cistern lever linked yet'} end
    local p = d.plan
    local gate = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
    if not gate or gate.closed then return {ok = false, rejected = true, error = 'the floodgate is already shut'} end
    if dry_run then return {ok = true, dry_run = true} end
    -- (0.100, review) at once: a queued pull waits for a dwarf to wade to
    -- the lever, and the planner asks again every cycle while dwarves are wet
    local ok, out = pull(d.lever_id, true)
    return {ok = ok, shut = ok, instant = true, error = not ok and out or nil}
end

-- (0.104.0) The cistern's room and its tunnel (all but the plug), the tiles
-- the water fills first.
function cistern_inside(p, z)
    local out = room_tiles(p.cistern)
    for i = 1, #p.tunnel_path - 1 do table.insert(out, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y}) end
    return out
end

-- (0.104.145) The tunnel's tiles (all but the plug), on the source's level.
function cistern_way(p)
    local out = {}
    for i = 1, #(p.tunnel_path or {}) - 1 do table.insert(out, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y}) end
    return out
end

-- How many living creatures stand on these tiles of level z.
function units_on_tiles(tiles, z)
    local set = {}
    for _, t in ipairs(tiles) do set[t.x .. ',' .. t.y] = true end
    local n = 0
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if u.pos.z == z and set[u.pos.x .. ',' .. u.pos.y] and not dfhack.units.isDead(u) then n = n + 1 end
        end
    end)
    return n
end

-- Items lying on these tiles of level z forbidden (nobody fetches them); how many.
function forbid_items_on(tiles, z)
    local n = 0
    for _, t in ipairs(tiles) do
        pcall(function()
            local block = dfhack.maps.getTileBlock(xyz2pos(t.x, t.y, z))
            if not block then return end
            for _, id in ipairs(block.items) do
                local it = df.item.find(id)
                if it and it.pos.x == t.x and it.pos.y == t.y and it.pos.z == z and it.flags.on_ground then
                    if not it.flags.forbid then it.flags.forbid = true; n = n + 1 end
                end
            end
        end)
    end
    return n
end

-- (0.104.168) THE PLAYER'S RULE: what the AI can set up in the game it does
-- itself. Teacheroar's cistern waited 20+ steps on "the cistern's shaft is
-- open at x105 y128" for the player to wall it. Now the AI builds the wall
-- (or, over the room, the tunnel and the shaft's top, a floor) at each open
-- spot itself, but never:
--   - in water, on a building, or on a stair or a ramp (a way up or down the
--     dwarves may walk: the player decides those);
--   - where the wall would cut a way: the open tile's walkable neighbours
--     (the cistern's own tiles left out) must still meet round it without it;
--   - with anyone on the tile, or in a hollow the wall would close off (a
--     pocket with no way off its level but through the gap).
-- Any open tile beside the shaft, the tunnel or the room lets the water out
-- (the shaft and tunnel are under pressure), so every gap is one to close.
CISTERN_GAP_WALL_ON = {FLOOR = true, EMPTY = true, PEBBLES = true, BOULDER = true, SHRUB = true, SAPLING = true}
CISTERN_GAP_POCKET_MAX = 400       -- tiles looked at beyond a gap
-- (0.104.168, review) ground a dwarf can stand on (open air and deep water are not)
CISTERN_STANDABLE = {FLOOR = true, PEBBLES = true, BOULDER = true, SHRUB = true, SAPLING = true, TWIG = true,
                     STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true, RAMP_TOP = true,
                     BROOK_BED = true}
-- ...and of those, the ways off the level
CISTERN_WAY_OFF = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true, RAMP_TOP = true}
local function standable(t)
    return t ~= nil and CISTERN_STANDABLE[tostring(t.shape)] == true and not (t.liquid and (t.depth or 0) >= 4)
end

-- Is a construction (a wall or floor being built, by the AI or the player) on this tile?
function construction_at(x, y, z)
    local ok, yes = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        return b ~= nil and b:getType() == df.building_type.Construction
    end)
    return ok and yes == true
end

-- Can the AI close this gap, and how: 'build' (with the quickfort text),
-- 'building' (its construction already placed), 'wait' (someone is in the
-- way) or 'no' (the player's), with why. (0.104.168, review) `recheck`: the
-- AI's own wall is placed and waits for a builder: is it still safe to finish?
function cistern_gap_plan(p, g, inside_set, recheck)
    local t = tile_info(g.x, g.y, g.z)
    if not t then return 'no', 'off the map' end
    if t.liquid then return 'no', 'water stands there' end
    if t.building and not recheck then return 'building', 'a construction or building stands there' end
    if not g.fix then return 'no', 'only a stair or a dug way can be there' end
    local sh = tostring(t.shape)
    if g.fix == 'floor' and sh ~= 'EMPTY' then
        return 'no', ('it is %s (a way the dwarves walk, or nothing a floor can be built on)'):format(sh:lower())
    end
    if g.fix == 'wall' and not CISTERN_GAP_WALL_ON[sh] then
        return 'no', ('it is %s (a way up or down the dwarves may walk)'):format(sh:lower())
    end
    if units_on_tiles({{x = g.x, y = g.y}}, g.z) > 0 then return 'wait', 'a creature stands there' end
    if g.fix == 'wall' then
        -- the gap's open neighbours on its level, the cistern's own tiles left out
        local function key(x, y) return x .. ',' .. y end
        -- (0.104.168, review) only ground a dwarf can stand on: never through open air or deep water
        local function open_at(x, y)
            if x == g.x and y == g.y then return false end
            if inside_set[key(x, y) .. ',' .. g.z] then return false end
            return standable(tile_info(x, y, g.z))
        end
        local starts = {}
        for _, e in ipairs(DIR8) do
            if open_at(g.x + e[1], g.y + e[2]) then table.insert(starts, {x = g.x + e[1], y = g.y + e[2]}) end
        end
        if #starts > 0 then
            -- one walk from the first neighbour: it must meet every other one
            -- (else the wall cuts a way), and if it ends small with no way off
            -- the level it is a hollow: nobody may be in it
            local seen, queue, tiles, way_off, capped_ = {[key(starts[1].x, starts[1].y)] = true}, {starts[1]}, {}, false, false
            local i = 1
            while i <= #queue do
                local q = queue[i]; i = i + 1
                table.insert(tiles, q)
                if #tiles > CISTERN_GAP_POCKET_MAX then capped_ = true break end
                -- a way off the level: a stair or a ramp, or the surface's open ground
                -- (never a channel or open air: no dwarf walks off through it)
                local qt = tile_info(q.x, q.y, g.z)
                if qt and (CISTERN_WAY_OFF[tostring(qt.shape)] or qt.outside) then
                    way_off = true
                end
                for _, e in ipairs(DIR8) do
                    local nx, ny = q.x + e[1], q.y + e[2]
                    if not seen[key(nx, ny)] and open_at(nx, ny) then
                        seen[key(nx, ny)] = true
                        table.insert(queue, {x = nx, y = ny})
                    end
                end
            end
            for _, s0 in ipairs(starts) do
                if not seen[key(s0.x, s0.y)] then
                    return 'no', capped_ and 'a wall there could cut a way the dwarves walk'
                                         or 'a wall there would cut a way the dwarves walk'
                end
            end
            -- (0.104.168, review) past the tiles looked at, unsure: only safe with
            -- a way off the level found (then it is no hollow); else the player's
            if capped_ and not way_off then
                return 'no', 'too much ground beyond it to be sure the wall shuts nobody in'
            end
            if not way_off and units_on_tiles(tiles, g.z) > 0 then
                return 'wait', 'someone is in the hollow beyond it (the wall would shut them in)'
            end
        end
    end
    return 'build', g.fix == 'wall' and 'Cw' or 'Cf'
end

-- (0.104.168, review) Take back a wall the AI placed that isn't built yet.
function cancel_construction(x, y, z)
    local ok, done = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if not b or b:getType() ~= df.building_type.Construction then return false end
        if b:getBuildStage() >= b:getMaxBuildStage() then return false end
        return dfhack.buildings.deconstruct(b)
    end)
    return ok and done and true or false
end

-- Close what the AI can of the cistern's gaps (cistern_sealed's list).
-- Returns the step's answer: a wait while walls/floors are being built, or
-- needs_player (with why) for a gap the AI must leave to the player.
function cistern_close_gaps(d, p, gaps, dry_run, save)
    local c, z = p.cistern, p.cistern.z
    local zi = p.intake_z or z
    local inside_set = {}
    for yy = c.y1, c.y2 do for xx = c.x1, c.x2 do inside_set[xx .. ',' .. yy .. ',' .. z] = true end end
    for _, t in ipairs(p.tunnel_path or {}) do inside_set[t.x .. ',' .. t.y .. ',' .. zi] = true end
    if p.shaft then for zz = z, zi do inside_set[p.shaft.x .. ',' .. p.shaft.y .. ',' .. zz] = true end end
    local placed, building, waiting, refused = {}, 0, nil, nil
    local by_z = {}
    for _, g in ipairs(gaps or {}) do
        local how, what = cistern_gap_plan(p, g, inside_set)
        local mine = (d.sealing and d.sealing[g.x .. ',' .. g.y .. ',' .. g.z]) or construction_at(g.x, g.y, g.z)
        if how == 'building' and mine then
            -- (0.104.168, review) still safe to finish? Someone gone into the
            -- hollow behind it since: the wall is taken back
            -- (one only passing over the tile: DF waits for it to step off itself)
            local how2, what2 = cistern_gap_plan(p, g, inside_set, true)
            if how2 == 'wait' and tostring(what2):find('hollow') then
                if not dry_run and cancel_construction(g.x, g.y, g.z) then
                    if d.sealing then d.sealing[g.x .. ',' .. g.y .. ',' .. g.z] = nil end
                end
                waiting = waiting or (g.words .. ': ' .. what2 .. '; the wall placed there is taken back')
            else
                building = building + 1
            end
        elseif how == 'building' or how == 'no' then
            refused = refused or (g.words .. ': ' .. what)
        elseif how == 'wait' then
            waiting = waiting or (g.words .. ': ' .. what)
        else
            by_z[g.z] = by_z[g.z] or {}
            table.insert(by_z[g.z], {x = g.x, y = g.y, z = g.z, text = what, g = g})
        end
    end
    for zz, cells in pairs(by_z) do
        for _, cell in ipairs(cells) do
            if dry_run or designate({{x = cell.x, y = cell.y, text = cell.text}}, zz, 'build') then
                table.insert(placed, cell)
            else
                refused = refused or (cell.g.words .. ': the game would not place a '
                                      .. (cell.text == 'Cw' and 'wall' or 'floor') .. ' there')
            end
        end
    end
    if not dry_run then
        d.sealing = d.sealing or {}
        for _, cell in ipairs(placed) do d.sealing[cell.x .. ',' .. cell.y .. ',' .. cell.z] = cell.text end
        d.unsealed_why = refused
        d.unsealed = gaps and gaps[1] and gaps[1].words or d.unsealed
        save(d)
    end
    local walls, floors = 0, 0
    for _, cell in ipairs(placed) do if cell.text == 'Cw' then walls = walls + 1 else floors = floors + 1 end end
    local words = {}
    if walls > 0 then table.insert(words, walls .. ' wall(s)') end
    if floors > 0 then table.insert(words, floors .. ' floor(s)') end
    local where = gaps and gaps[1] and gaps[1].words or '?'
    if refused then
        return {ok = false, rejected = true, needs_player = true, unsealed = where,
                unsealed_why = refused, walls = walls, floors = floors, dry_run = dry_run or nil,
                error = 'the cistern is not closed where the water goes (' .. refused .. '): the AI can\'t close that itself'}
    end
    if #placed > 0 then
        return {ok = true, stage = d.stage, sealing = true, walls = walls, floors = floors, dry_run = dry_run or nil,
                error = ('the cistern is not closed where the water goes (%s): the AI builds %s there first')
                        :format(where, table.concat(words, ' and '))}
    end
    return {ok = false, rejected = true, waiting = true, stage = d.stage, unsealed = where,
            error = 'the cistern is not closed where the water goes (' .. where .. '): '
                    .. (waiting or (building .. ' wall(s)/floor(s) the AI placed are being built'))}
end

-- (0.104.144) THE PLAYER, 31 Oct 20:51: the cistern as built doesn't work,
-- and working it would flood the fort. Until a new design: its floodgate is
-- never opened by the AI (it may still be shut), and no new cistern is begun.
CISTERN_HOLD = false          -- (0.104.145) the second design: released
CISTERN_HOLD_WHY = 'the cistern is on hold (the player: as built it would flood the fort): the floodgate stays shut'

CISTERN_TUNNEL_ASKED = nil       -- (0.105.3) the brain's cistern_tunnel_max, set by cistern_step's caller
function cistern_step(dry_run, prefs, tunnel)
    CISTERN_TUNNEL_ASKED = math.tointeger(tonumber(tunnel))
    OFFSET = elevation_offset()
    if prefs then cistern_prefs(prefs) end
    local d = cistern_data()
    -- (0.104.145) a cistern of the first design is retired: its floodgate
    -- shut (it could flood the fort) and the next one planned afresh
    if d and (d.plan.v or 1) < CISTERN_V then
        local p0 = d.plan
        local g = building_info(p0.floodgate.x, p0.floodgate.y, p0.cistern.z, 'Floodgate')
        if g and g.built and not g.closed and not d.lever_id then
            return {ok = false, rejected = true, needs_player = true,
                    error = 'the old cistern\'s floodgate is open and no lever is linked to it: shut it by hand'}
        end
        if g and g.built and not g.closed and d.lever_id then
            if dry_run then return {ok = true, dry_run = true, retire = true} end
            if not lever_pull_pending(d.lever_id) then pull(d.lever_id, true) end
            return {ok = true, stage = d.stage, shut = true,
                    error = 'the old cistern\'s floodgate is being shut before it is retired (its design could flood the fort)'}
        end
        if dry_run then return {ok = true, dry_run = true, retire = true} end
        local old = site_get(CISTERN_KEY .. '/retired')
        table.insert(old, {cistern = p0.cistern, source = p0.source, why = 'the first design (pressure could flood the fort)'})
        site_put(CISTERN_KEY .. '/retired', old)
        site_put(CISTERN_KEY, {})
        return {ok = true, stage = 'retired', retired = true,
                error = 'the old cistern (first design) retired, its floodgate shut: a new one is planned next'}
    end
    if not d and CISTERN_HOLD then
        return {ok = false, rejected = true, held = true, error = 'no new cistern while the design is on hold'}
    end
    if not d then
        -- (0.105.3) the same tunnel reach the survey planned it with
        local plan, why, cut = plan_cistern(nil, nil, {tunnel = CISTERN_TUNNEL_ASKED})
        if not plan then return {ok = false, error = why, timed_out = cut or nil} end
        if dry_run then return {ok = true, dry_run = true, stage = 'dig', plan = plan} end
        d = {stage = 'dig', plan = plan}
    end
    local p, z = d.plan, d.plan.cistern.z
    local zw, wx, wy = p.well.z, p.well.x, p.well.y
    local zi = p.intake_z or z                 -- (0.104.145) the source's level: the tunnel, floodgate and plug
    local function wait(why) return {ok = false, rejected = true, waiting = true, stage = d.stage, error = why} end
    local function advance(stage, extra)
        if not dry_run then d.stage = stage; save_cistern(d) end
        local out = {ok = true, stage = stage, dry_run = dry_run or nil}
        for k, v in pairs(extra or {}) do out[k] = v end
        return out
    end

    -- (0.104.144) on hold: past the link (opening, the plug, filling, the
    -- well) nothing more is done; an open floodgate is shut
    if CISTERN_HOLD and d.stage ~= 'dig' and d.stage ~= 'building' and d.stage ~= 'linking' then
        local g = building_info(p.floodgate.x, p.floodgate.y, zi, 'Floodgate')
        if not dry_run and g and g.built and not g.closed and d.lever_id and not lever_pull_pending(d.lever_id) then
            pull(d.lever_id)
            return {ok = true, held = true, shut = true, error = CISTERN_HOLD_WHY}
        end
        return {ok = false, rejected = true, held = true, error = CISTERN_HOLD_WHY}
    end
    if d.stage == 'dig' then
        if dry_run then return {ok = true, dry_run = true, stage = 'dig', plan = p} end
        local room = {}
        for _, c in ipairs(room_tiles(p.cistern)) do
            if not (c.x == wx and c.y == wy) then table.insert(room, {x = c.x, y = c.y, text = 'd'}) end
        end
        local tunnel = {}
        for i = 1, #p.tunnel_path - 1 do
            table.insert(tunnel, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y, text = 'd'})
        end
        if not designate({{x = wx, y = wy, text = 'j'}}, zw, 'dig')
                or not designate({{x = wx, y = wy, text = 'u'}}, z, 'dig')
                or not designate(room, z, 'dig') or (#tunnel > 0 and not designate(tunnel, zi, 'dig')) then
            return {ok = false, error = 'the game would not designate the cistern\'s digging'}
        end
        -- (0.104.145) the shaft: a down stair on the source's level, up/down
        -- stairs through the rock, an up stair at the bottom (diagonal to the room)
        if p.shaft then
            for zz = z, zi do
                local ch = zz == zi and 'j' or (zz == z and 'u' or 'i')
                if not designate({{x = p.shaft.x, y = p.shaft.y, text = ch}}, zz, 'dig') then
                    return {ok = false, error = 'the game would not designate the cistern\'s shaft'}
                end
            end
        end
        return advance('digging', {x = wx, y = wy, elevation = ez(z), tunnel = p.tunnel})
    end
    if d.stage == 'digging' then
        local left = 0
        for _, c in ipairs(room_tiles(p.cistern)) do
            local t = tile_info(c.x, c.y, z)
            if t and t.shape == 'WALL' then left = left + 1 end
        end
        for i = 1, #p.tunnel_path - 1 do
            local t = tile_info(p.tunnel_path[i].x, p.tunnel_path[i].y, zi)
            if t and t.shape == 'WALL' then left = left + 1 end
        end
        if p.shaft then
            for zz = z, zi do
                local t = tile_info(p.shaft.x, p.shaft.y, zz)
                if t and t.shape == 'WALL' then left = left + 1 end
            end
        end
        local top = tile_info(wx, wy, zw)
        if not top or top.shape ~= 'STAIR_DOWN' and top.shape ~= 'STAIR_UPDOWN' then left = left + 1 end
        if left > 0 then return wait(('the cistern is being dug: %d tile(s) left'):format(left)) end
        if dry_run then return {ok = true, dry_run = true, stage = 'build'} end
        local fg, lv = p.floodgate, p.lever
        if not lv then return {ok = false, error = 'no spot for the lever beside the well'} end
        if not designate({{x = fg.x, y = fg.y, text = 'x'}}, zi, 'build')
                or not designate({{x = lv.x, y = lv.y, text = 'Tl'}}, zw, 'build') then
            return {ok = false, error = 'the game would not place the floodgate or the lever'}
        end
        return advance('building')
    end
    local gate = building_info(p.floodgate.x, p.floodgate.y, zi, 'Floodgate')
    local lever = p.lever and building_info(p.lever.x, p.lever.y, zw, 'Trap')
    if d.stage == 'building' then
        if not gate or not lever then return {ok = false, error = 'the floodgate or the lever is gone'} end
        if not gate.built or not lever.built then return wait('the floodgate and the lever are being built') end
        if dry_run then return {ok = true, dry_run = true, stage = 'link'} end
        local okg, G = pcall(reqscript, 'ai-gates')
        if not okg then return {ok = false, error = 'ai-gates missing'} end
        local r = G.link_lever(lever.id, gate.id, false)
        if not r.ok then return r end
        d.lever_id, d.gate_id = lever.id, gate.id
        return advance('linking')
    end
    if d.stage == 'linking' then
        -- (0.104.138) the lever (or the gate) itself gone (Teacheroar: "no
        -- lever with id 273", toppled in a tantrum?) used up the 3 relinks on
        -- a building that wasn't there: take the one standing on its spot, or
        -- place it again, and count afresh
        local function gone(id)
            local ok, b = pcall(function() return df.building.find(id) end)
            return ok and id ~= nil and b == nil
        end
        if gone(d.lever_id) or gone(d.gate_id) then
            if dry_run then return wait('the lever or floodgate is gone: placed again') end
            if lever and lever.built and gate and gate.built then
                d.lever_id, d.gate_id, d.relinks = lever.id, gate.id, 0
                save_cistern(d)
                local r = reqscript('ai-gates').link_lever(d.lever_id, d.gate_id, false)
                if not r.ok then return r end
                return wait('the lever or floodgate was replaced: linked again')
            end
            if (not lever and p.lever and not designate({{x = p.lever.x, y = p.lever.y, text = 'Tl'}}, zw, 'build'))
                    or (not gate and not designate({{x = p.floodgate.x, y = p.floodgate.y, text = 'x'}}, zi, 'build')) then
                return {ok = false, error = 'the lever or floodgate is gone and the game would not place it again'}
            end
            d.relinks = 0
            return advance('building')
        end
        local links = reqscript('ai-gates').lever_links()
        local linked = false
        for _, lid in ipairs(links[d.gate_id] or {}) do if lid == d.lever_id then linked = true end end
        if not linked then
            -- (0.104.110) the link job was lost (cancelled, its mechanisms
            -- taken): Teacheroar waited on it 3,259 steps. Asked for again,
            -- 3 times at most
            local pending = false
            pcall(function()
                local lv = df.building.find(d.lever_id)
                for _, j in ipairs(lv and lv.jobs or {}) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then pending = true end
                end
            end)
            if pending or dry_run then return wait('the lever is being linked to the floodgate') end
            if (math.tointeger(d.relinks) or 0) >= 3 then
                return {ok = false, rejected = true, needs_player = true,
                    error = 'the link from the lever to the floodgate was lost 3 times; '
                    .. 'link it by hand (the lever beside the well)'}
            end
            -- (0.104.141) why the last one was dropped: DF's newest "cancels
            -- Link a Building" announcement, kept for the Needs you line
            pcall(function()
                local reps = df.global.world.status.reports
                for i = #reps - 1, math.max(0, #reps - 400), -1 do
                    local txt = reps[i].text
                    if txt:find('cancels Link') then d.link_why = txt:gsub('^.-cancels ', ''):sub(1, 120) break end
                end
            end)
            local r = reqscript('ai-gates').link_lever(d.lever_id, d.gate_id, false)
            if not r.ok then return r end
            d.relinks = (math.tointeger(d.relinks) or 0) + 1     -- (0.104.138) only a link really asked for
            save_cistern(d)
            return wait(('the lever link was lost: asked for again (%d)'):format(d.relinks))
        end
        if CISTERN_HOLD then return {ok = false, rejected = true, held = true, error = CISTERN_HOLD_WHY} end
        -- (0.104.145) closed all round, and its source still there, before any water
        local sealed, where, gaps = cistern_sealed(p, d.stage)
        if not dry_run and d.unsealed ~= (where or nil) then d.unsealed = where; save_cistern(d) end
        if not sealed then
            -- (0.104.168) the AI walls it up itself where it safely can
            return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
        end
        if not dry_run and (d.sealing or d.unsealed_why) then d.sealing, d.unsealed_why = nil, nil; save_cistern(d) end
        if not still_water(tile_info(p.water.x, p.water.y, zi)) then
            return {ok = false, rejected = true, error = 'the cistern\'s source is gone (no still water beside the plug)'}
        end
        if dry_run then return {ok = true, dry_run = true, stage = 'open'} end
        -- (0.104.145, review) the gate stays shut: the plug is dug first with
        -- nobody inside (DFHack dig-now), then the gate opened at once. A miner
        -- digging it by hand had to flee back down a shaft filling faster than
        -- the room, through water a dwarf won't wade
        return advance('opening')
    end
    if d.stage == 'opening' then
        if gate and gate.closed and d.plug_by_hand then
            return wait('a dwarf is on the way to pull the lever (open the floodgate)')
        end
        -- (0.104.0, map safety) the water comes in when the plug is dug: no one
        -- else may be in the cistern or its tunnel then. The plug waits until
        -- both are empty, and what lies there is forbidden (no hauler goes in
        -- for it); only the miner who digs the plug goes in, and out through
        -- the open floodgate
        local inside = cistern_inside(p, z)
        local n = zi == z and units_on_tiles(inside, z)
            or (units_on_tiles(room_tiles(p.cistern), z) + units_on_tiles(cistern_way(p), zi))
        if p.shaft then
            for zz = z, zi do n = n + units_on_tiles({{x = p.shaft.x, y = p.shaft.y}}, zz) end
        end
        if n > 0 then
            return wait(('%d creature(s) in the cistern or its tunnel: the plug waits until it is empty'):format(n))
        end
        local sealed, where, gaps = cistern_sealed(p, d.stage)
        if not dry_run and d.unsealed ~= (where or nil) then d.unsealed = where; save_cistern(d) end
        if not sealed then
            -- (0.104.168) the AI walls it up itself where it safely can; the plug waits
            return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
        end
        if not dry_run and (d.sealing or d.unsealed_why) then d.sealing, d.unsealed_why = nil, nil; save_cistern(d) end
        if dry_run then return {ok = true, dry_run = true, stage = 'plug'} end
        if zi == z then
            forbid_items_on(inside, z)
        else
            forbid_items_on(room_tiles(p.cistern), z)
            forbid_items_on(cistern_way(p), zi)
        end
        -- dig-now: the plug gone at once, the gate still shut; then the gate opened
        if not d.plug_by_hand and gate and gate.closed then
            designate({{x = p.plug.x, y = p.plug.y, text = 'd'}}, zi, 'dig')
            local pos = ('%d,%d,%d'):format(p.plug.x, p.plug.y, zi)
            pcall(dfhack.run_command_silent, 'dig-now', pos, pos)
            local pt = tile_info(p.plug.x, p.plug.y, zi)
            if pt and pt.shape ~= 'WALL' then
                local ok, out = pull(d.lever_id, true)
                if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
                return advance('filling', {plug = 'dug at once', opened = true})
            end
            -- no dig-now here: the old way (the gate opened, a miner digs it),
            -- never down a shaft (the miner would drown fleeing it)
            if p.shaft then
                return {ok = false, rejected = true, needs_player = true,
                        error = 'DFHack\'s dig-now didn\'t dig the plug, and a miner digging it would drown in the shaft'}
            end
            d.plug_by_hand = true
            save_cistern(d)
            local ok, out = pull(d.lever_id)
            if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
            return wait('dig-now isn\'t here: the gate opened, a miner digs the plug')
        end
        if not designate({{x = p.plug.x, y = p.plug.y, text = 'd'}}, zi, 'dig') then
            return {ok = false, error = 'the game would not designate the plug'}
        end
        return advance('plug')
    end
    local st = cistern_status()
    -- (0.104.145) the leak guard: water over the cistern (on the well's level
    -- over the room or round it) means it is getting out: the floodgate is
    -- shut at once and the player told
    if d.stage ~= 'dig' and d.stage ~= 'digging' and d.stage ~= 'building' and d.stage ~= 'linking' then
        local leak
        -- (review) the shaft's own column and the tunnel hold water by design
        local own = {}
        if p.shaft then own[p.shaft.x .. ',' .. p.shaft.y] = true end
        if zi == zw then for _, q in ipairs(p.tunnel_path or {}) do own[q.x .. ',' .. q.y] = true end end
        for yy = p.cistern.y1 - 1, p.cistern.y2 + 1 do
            for xx = p.cistern.x1 - 1, p.cistern.x2 + 1 do
                local tt = tile_info(xx, yy, zw)
                if tt and tt.liquid and not tt.magma and not own[xx .. ',' .. yy] then
                    leak = leak or ('x%d y%d elevation %d'):format(xx, yy, ez(zw))
                end
            end
        end
        if not leak and d.leak and gate and gate.closed then
            -- the water gone from over it and it is closed again: tried once
            -- more (a second leak keeps it shut for good)
            local ok_ = cistern_sealed(p, d.stage)
            if ok_ == true and (d.leaks or 0) < 2 and not dry_run then d.leak = nil; save_cistern(d) end
        end
        if d.leak and not leak then
            return {ok = false, rejected = true, needs_player = true, leak = d.leak,
                    error = 'the cistern leaked at ' .. d.leak .. ': its floodgate stays shut'}
        end
        if leak then
            if gate and gate.built and not gate.closed and d.lever_id and not dry_run then pull(d.lever_id, true) end
            d.leak = leak
            d.leaks = (d.leaks or 0) + 1
            if not dry_run then save_cistern(d) end
            return {ok = false, needs_player = true, leak = leak, shut = true,
                    error = 'water over the cistern at ' .. leak .. ': its floodgate shut at once'}
        end
    end
    if d.stage == 'plug' then
        local t = tile_info(p.plug.x, p.plug.y, zi)
        if t and t.shape == 'WALL' then return wait('the plug is being dug (then the water comes in)') end
        return advance('filling')
    end
    if d.stage == 'filling' then
        if st.depth < CISTERN_FULL then
            local why = st.path and (' (gate %s; %s)'):format(st.gate or '?', path_words(st.path)) or ''
            if dry_run then return wait(('the cistern is filling: %d/7%s'):format(st.depth, why)) end
            -- (0.104.100) the gate shut (the flood rule, while dwarves stood in deep
            -- water): reopened after CISTERN_REOPEN_DAYS with nobody in deep water
            -- (Teacheroar sat at 5/7 behind a shut gate from 03:18 all night)
            if gate and gate.built and gate.closed and d.lever_id then
                local now_t = game_tick()
                local wet = citizens_in_deep_water()
                if wet > 0 or not d.shut_seen then
                    d.shut_seen = now_t
                    save_cistern(d)
                end
                if (d.reopens or 0) >= CISTERN_MAX_REOPENS then
                    return wait(('the cistern is filling: %d/7, its floodgate shut after %d floods: it stays shut '
                                 .. '(open it by its lever when the cause is found)'):format(st.depth, d.reopens))
                end
                local days = (now_t - d.shut_seen) // 1200
                if wet == 0 and days >= CISTERN_REOPEN_DAYS and not CISTERN_HOLD then
                    if lever_pull_pending(d.lever_id) then
                        return wait('a dwarf is on the way to pull the cistern\'s lever (reopening it)')
                    end
                    -- (0.104.168) never reopened while it isn't closed where the water
                    -- goes (the gate may have been shut for exactly that): closed first
                    local sealed, where, gaps = cistern_sealed(p, d.stage)
                    if not sealed then
                        if not dry_run then d.unsealed = where; save_cistern(d) end
                        return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
                    end
                    d.unsealed, d.sealing, d.unsealed_why = nil, nil, nil
                    local ok, out = pull(d.lever_id)
                    if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
                    d.reopens, d.shut_seen = (d.reopens or 0) + 1, nil
                    save_cistern(d)
                    return {ok = true, stage = 'filling', reopened = true, depth = st.depth,
                            error = ('the floodgate was shut for a flood; nobody has stood in deep water for %d days: '
                                     .. 'reopened to finish filling (%d of %d)'):format(days, d.reopens, CISTERN_MAX_REOPENS)}
                end
                return wait(('the cistern is filling: %d/7, its floodgate shut (%s): it reopens after %d days with '
                             .. 'nobody in deep water'):format(st.depth, wet > 0 and (wet .. ' in deep water now')
                                                              or (days .. ' day(s) dry so far'), CISTERN_REOPEN_DAYS))
            end
            -- (0.104.94) the source dried up (a surface pool evaporates): after
            -- CISTERN_DRY_DAYS with no water there and none in the cistern, the
            -- floodgate is shut and the cistern retired; the next one is planned
            -- afresh (this room no longer counts as solid rock)
            local src = tile_info(p.water.x, p.water.y, zi)
            local dry = st.depth == 0 and not (src and src.liquid)
            local now_t = game_tick()
            if dry then
                d.dry_since = d.dry_since or now_t
                save_cistern(d)
                if now_t - d.dry_since >= CISTERN_DRY_DAYS * 1200 then
                    if gate and gate.built and not gate.closed and d.lever_id then pull(d.lever_id) end
                    local old = site_get(CISTERN_KEY .. '/retired')
                    table.insert(old, {cistern = p.cistern, source = p.source, why = 'the source dried up', at = now_t})
                    site_put(CISTERN_KEY .. '/retired', old)
                    site_put(CISTERN_KEY, {})
                    return {ok = true, stage = 'retired', retired = true,
                            error = ('the cistern\'s source (%s) dried up for %d days: its floodgate shut and the cistern '
                                     .. 'retired; the next one is planned afresh'):format(tostring(p.source), CISTERN_DRY_DAYS)}
                end
                return wait(('the cistern is filling: 0/7; its source (%s) is dry for %d day(s)%s')
                            :format(tostring(p.source), (now_t - d.dry_since) // 1200, why))
            elseif d.dry_since then
                d.dry_since = nil
                save_cistern(d)
            end
            -- (0.104.96) the tunnel cleared only while there is water to let in
            -- (it ran first and kept the dry check from ever counting)
            -- (0.104.94) a tree grown in the tunnel (a trunk is a wall), or rock
            -- left: felled or dug again
            local blocked = 0
            local way = {}
            for i = 1, #p.tunnel_path - 1 do table.insert(way, p.tunnel_path[i]) end
            table.insert(way, p.plug)
            for _, c in ipairs(way) do
                local t = tile_info(c.x, c.y, zi)
                if t and t.shape == 'WALL' and t.material ~= 'FROZEN_LIQUID' and not t.designated then
                    blocked = blocked + 1
                    if t.material == 'TREE' or t.material == 'ROOT' then
                        fell_tree(c.x, c.y, zi)
                    else
                        designate({{x = c.x, y = c.y, text = 'd'}}, zi, 'dig')
                    end
                end
            end
            if blocked > 0 then
                return wait(('the cistern is filling: %d/7; %d tile(s) on the water\'s way blocked: felled or dug again%s')
                            :format(st.depth, blocked, why))
            end
            -- (0.104.119) water stands no higher than its source: a cistern at
            -- 4/7 or more that hasn't risen for CISTERN_LEVEL_DAYS with its
            -- gate open is as full as it gets (it waited at 5/7 for good)
            local now_t = game_tick()
            if d.depth_seen ~= st.depth or st.gate == 'shut' then
                d.depth_seen, d.depth_tick = st.depth, now_t
                save_cistern(d)
            end
            local still = (now_t - (math.tointeger(d.depth_tick) or now_t)) // 1200
            if not (st.depth >= CISTERN_LEVEL_MIN and still >= CISTERN_LEVEL_DAYS) then
                return wait(('the cistern is filling: %d/7%s'):format(st.depth, why))
            end
        end
        if dry_run then return {ok = true, dry_run = true, stage = 'hole'} end
        if gate and not gate.closed then pull(d.lever_id) end
        if not designate({{x = wx, y = wy, text = 'h'}}, zw, 'dig') then
            return {ok = false, error = 'the game would not channel the well\'s hole'}
        end
        return advance('hole', {depth = st.depth})
    end
    if d.stage == 'hole' then
        local t = tile_info(wx, wy, zw)
        if t and t.shape ~= 'EMPTY' and t.shape ~= 'RAMP_TOP' then return wait('the well\'s hole is being dug') end
        if dry_run then return {ok = true, dry_run = true, stage = 'well'} end
        if not designate({{x = wx, y = wy, text = 'l'}}, zw, 'build') then
            return {ok = false, error = 'the game would not place the well'}
        end
        return advance('well')
    end
    if d.stage == 'well' then
        local w = building_info(wx, wy, zw, 'Well')
        if not w or not w.built then return wait('the well is being built') end
        return advance('done', {depth = st.depth})
    end
    -- done: keep it topped up
    if gate and gate.built and d.lever_id then
        if gate.closed and st.depth < CISTERN_LOW and not CISTERN_HOLD then
            local sealed, where, gaps = cistern_sealed(p, d.stage)
            if not sealed then
                if not dry_run then d.unsealed = where; save_cistern(d) end
                -- (0.104.168) the AI walls it up itself where it safely can; not refilled till then
                return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
            end
            if not dry_run and (d.unsealed or d.sealing or d.unsealed_why) then
                d.unsealed, d.sealing, d.unsealed_why = nil, nil, nil; save_cistern(d)
            end
            if dry_run then return {ok = true, dry_run = true, refill = true} end
            local ok, out, pending = pull(d.lever_id)
            return {ok = ok, stage = 'done', refill = true, depth = st.depth, pending = pending,
                    error = not ok and out or nil}
        elseif not gate.closed and st.depth >= CISTERN_FULL then
            if dry_run then return {ok = true, dry_run = true, shut = true} end
            local ok, out, pending = pull(d.lever_id)
            return {ok = ok, stage = 'done', shut = true, depth = st.depth, pending = pending,
                    error = not ok and out or nil}
        end
    end
    return {ok = false, rejected = true, done = true, stage = 'done', depth = st.depth,
            error = 'the cistern is built and full enough'}
end
