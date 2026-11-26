-- ai-builder-keep: the keep: building above ground (the Surface ambition), its court's
-- site, walls, door and roof.
--
-- A part of ai-builder, not a script of its own (r8, split out of
-- ai-builder-surface.lua when it was 126 KB): ai-builder.lua loads it into its
-- own environment right after ai-builder-surface, so every name here is
-- reqscript('ai-builder').name and the helpers defined there (info,
-- quickfort_apply, ...) are in reach.

if not PARTS then qerror('ai-builder-keep is a part of ai-builder; run ai-builder') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-keep'] = '0.105.126'   -- bumped with BRIDGE_VERSION

local info, ez = info, ez

-- --- the keep: building above ground (the Surface ambition) ----------------------
--
-- A walled court around the fort's way in from the surface: a square ring of
-- constructed walls (radius 4-6 tiles from the entrance) with one door, then
-- a roof of constructed floor over the inside. Natural rock in the ring
-- counts as wall already; trees in the ring are felled first. Never put
-- around a trade depot (the wagons couldn't reach it), never over water,
-- buildings, zones or slopes. Built in stages, one action each:
--   clearing -> walls (+ door) -> stair (0.105.30, ROOF_STAIR) -> roof -> done
-- The state lives in the save (site data 'ai-overseer/keep').
KEEP_KEY = 'ai-overseer/keep'
KEEP_RADII = {4, 5, 6}
-- (0.105.30, construction 3.0.2) A stair up from the inside to the roof:
-- whether the game builds a roof over an enclosed court from below is
-- [verify]; set false once it is seen to. The keep (stage 'stair') and the
-- surface hall use it.
ROOF_STAIR = true

-- The inside corner for the roof stair (x1..x2, y1..y2: the inside at z),
-- the one farthest from `away` (the door): open flat ground with nothing on
-- it and the open sky above. {x, y, z} or nil (ROOF_STAIR off, no corner).
function roof_access(x1, y1, x2, y2, z, away)
    if not ROOF_STAIR then return nil end
    local corners = {{x = x1, y = y1}, {x = x2, y = y1}, {x = x1, y = y2}, {x = x2, y = y2}}
    local function far(c)
        if not away then return 0 end
        return math.abs(c.x - away.x) + math.abs(c.y - away.y)
    end
    table.sort(corners, function(a, b)
        local fa, fb = far(a), far(b)
        if fa ~= fb then return fa > fb end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    for _, c in ipairs(corners) do
        local t, up = tile_info(c.x, c.y, z), tile_info(c.x, c.y, z + 1)
        if t and up and t.shape == 'FLOOR' and not t.building and not t.liquid and not t.designated
                and up.shape == 'EMPTY' and not up.building then
            return {x = c.x, y = c.y, z = z}
        end
    end
    return nil
end

function keep_data()
    local d = site_get(KEEP_KEY)
    return d.x and d or nil
end

local function save_keep(d)
    site_put(KEEP_KEY, d or {})
end

local function ring_tiles(cx, cy, r)
    local out = {}
    for x = cx - r, cx + r do
        table.insert(out, {x = x, y = cy - r})
        table.insert(out, {x = x, y = cy + r})
    end
    for y = cy - r + 1, cy + r - 1 do
        table.insert(out, {x = cx - r, y = y})
        table.insert(out, {x = cx + r, y = y})
    end
    return out
end

-- What a ring tile is: 'ground' (a wall can go up), 'tree', 'wall' (rock or a
-- wall already: closed), 'planned' (a wall waiting to be built) or nil (no use).
-- (0.105.47) Ground under a tree's crown: DF marks it not outside (no sky
-- straight above), so keep_tile read it as "the fort's own rock or rooms
-- (under a roof)": F's field hall was refused 72 times on that (8-13 Nov),
-- and the keep's ring and court lost every tile in a grove. Ground that is
-- not subterranean, with only open air and then a tree's trunk, branches or
-- leaves within CANOPY_LEVELS above it, is the open surface; a built roof
-- (or rock) above is not. A tree's own trunk stays a tree (is_tree).
CANOPY_LEVELS = 6
CANOPY_MATERIALS = {TREE = true, ROOT = true, PLANT = true}
function canopy_ground(x, y, z, t)
    t = t or tile_info(x, y, z)
    if not t or t.outside or t.subterranean ~= false then return false end
    for dz = 1, CANOPY_LEVELS do
        local a = tile_info(x, y, z + dz)
        if not a then return false end
        if CANOPY_MATERIALS[a.material] then return true end
        if a.shape ~= 'EMPTY' and a.shape ~= 'NONE' then return false end
    end
    return false
end

function keep_tile(x, y, z)
    local t = tile_info(x, y, z)
    if not t or t.liquid or t.feature then return nil end
    if is_tree(t) then return 'tree' end
    if t.shape == 'WALL' then return 'wall' end
    if t.building then return 'planned' end
    if t.hidden or t.designated or tile_taken(x, y, z) then return nil end
    if not t.outside and not canopy_ground(x, y, z, t) then return nil end      -- (0.105.47) a grove is open ground
    if GROUND[t.shape] then return 'ground' end
    return nil
end

-- (0.105.33) A 'planned' ring tile that is a wall waiting to be built: a
-- Construction there (any other building, a trap, a statue, the player's
-- door, is a gap: counted as such it kept the keep "going up" forever).
-- When the building can't be read it is taken as a wall waiting (as before).
-- Tests swap it.
function keep_wall_waits(x, y, z)
    local ok, other = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        return b ~= nil and b:getType() ~= df.building_type.Construction
    end)
    return not (ok and other)
end

-- (0.105.30) Why keep_tile gives nil there, in words (the refusal names the
-- tile: F and C were refused 133 and 138 times with no tile named).
function keep_tile_why(x, y, z)
    local t = tile_info(x, y, z)
    if not t then return 'the map\'s edge' end
    if t.liquid then return 'water' end
    if t.feature then return 'a cavern' end
    if t.hidden then return 'unseen ground' end
    if not t.outside and not canopy_ground(x, y, z, t) then return 'the fort\'s own rock or rooms (under a roof)' end
    if t.designated then return 'a tile designated for digging' end
    if tile_taken(x, y, z) then return 'a stockpile, zone or building' end
    return ('a %s tile'):format(tostring(t.shape):lower())
end

-- (0.105.30) The ways in, each on the level of the open ground. The gates
-- give a way in as its inside tile: for a stair up to the surface (the
-- founding stair under its hatch) that is the stair one level under the
-- ground, so every keep ring was looked for in the rock (F and C's 271
-- refusals, "no ring of open ground around the way in"). A stair that goes
-- on up to an outside tile is followed up (at most 2 levels).
function surface_anchors(anchors)
    local out = {}
    for _, a in ipairs(anchors or pasture_anchors()) do
        local z = a.z
        local t = tile_info(a.x, a.y, a.z)
        if t and not t.outside and stair_shape(a.x, a.y, a.z) then
            for zz = a.z + 1, a.z + 2 do
                local sh = stair_shape(a.x, a.y, zz)
                if not (sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN') then break end
                local up = tile_info(a.x, a.y, zz)
                if up and up.outside then z = zz break end
            end
        end
        table.insert(out, {x = a.x, y = a.y, z = z, below = z ~= a.z and a.z or nil})
    end
    return out
end

function depot_inside(x1, y1, x2, y2, z)
    local ok, found = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
            if b.z == z and b.x2 >= x1 and b.x1 <= x2 and b.y2 >= y1 and b.y1 <= y2 then return true end
        end
        return false
    end)
    return ok and found
end

-- (0.104.0, map safety) A trade depot under a roof or underground: the
-- caravans' wagons reach it through the fort's way in, and the keep's ring
-- (one door, no 3-wide way) would shut them out. Returns why, or nil.
function depot_underground()
    local ok, why = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
            local cx, cy = math.floor((b.x1 + b.x2) / 2), math.floor((b.y1 + b.y2) / 2)
            local t = tile_info(cx, cy, b.z)
            if t and not t.outside then
                return ('the trade depot at x%d y%d is underground: a walled keep round the way in would shut '
                        .. 'out the caravans\' wagons'):format(cx, cy)
            end
        end
    end)
    return ok and why or nil
end

-- The door: the middle of a side whose ring tile takes a wall and has open
-- ground on both sides of it (south, east, north, west in turn).
local function keep_door(cx, cy, z, r)
    for _, d in ipairs({{0, 1}, {1, 0}, {0, -1}, {-1, 0}}) do
        local x, y = cx + d[1] * r, cy + d[2] * r
        local inner = tile_info(x - d[1], y - d[2], z)
        local outer = tile_info(x + d[1], y + d[2], z)
        if keep_tile(x, y, z) == 'ground' and inner and outer and GROUND[inner.shape] and GROUND[outer.shape]
                and not inner.building and not outer.building and not outer.liquid then
            return {x = x, y = y}
        end
    end
end

-- (0.105.23, 14.1 step 4c) The keep away from the way in: fort F (Garden
-- fort, Surface +80) asked 39 times and was refused every time ("no ring of
-- open ground around the way in"): its founding stair sits on a mountain
-- slope, so every ring round it ran into rock, ramps and the hillside. When
-- no way in has a ring, the keep goes on the flattest open ground near the
-- fort: a square court whose inside is all open, flat ground under the open
-- sky (on one level, nothing above it), within KEEP_COURT_REACH tiles of a
-- way in and up to KEEP_COURT_LEVELS levels below it (or within
-- KEEP_COURT_FARM_REACH of a surface field), the dwarves able to walk to it;
-- nearest the surface farm plots when there are any (a walled
-- garden court by the fields), else nearest the way in. Never over the
-- plots themselves (a building or zone inside rules a spot out), never round
-- the way in (that was the first try) nor within KEEP_COURT_CLEAR of it (the
-- caravans' road), never round the trade depot. A court away from the way
-- in can go up with the depot underground (the wagons pass it by).
KEEP_COURT_REACH = 30
KEEP_COURT_LEVELS = 4
KEEP_COURT_RADII = {4, 5}
KEEP_COURT_SMALL = {3}       -- (0.105.47) a 5x5 court, only where no 7x7 or 9x9 fits: B and F's hillsides
KEEP_COURT_SECONDS = 1.5
KEEP_COURT_CANDIDATES = 400  -- centres checked in full, best first
KEEP_COURT_FARMS = 6         -- fields looked round (the first ones DF lists)
KEEP_COURT_FARM_REACH = 12   -- tiles round a field
KEEP_COURT_CLEAR = 3         -- open tiles kept between the court's walls and a way in (the wagons' road)

-- The centres of the farm plots under the sky: {{x, y, z}, ...}.
function surface_farm_spots()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.FARM_PLOT) do
            local cx, cy = (b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2
            local t = tile_info(cx, cy, b.z)
            if t and t.outside then table.insert(out, {x = cx, y = cy, z = b.z}) end
        end
    end)
    return out
end

-- A court site on open ground near the fort: {x, y, z, r, door, trees, court = true}, or nil and why.
function find_keep_court(anchors)
    local groups = citizen_groups()
    local any_group = next(groups) == nil
    -- (0.105.47) the open ground the way in leads out to is the dwarves'
    -- too: with the gate shut (the hatch locked, every citizen inside) the
    -- surface is another walk group, and no tile out there was "reachable"
    if not any_group then
        local g2 = {}
        for g in pairs(groups) do g2[g] = true end
        for _, a in ipairs(anchors) do
            local g = walk_group(a.x, a.y, a.z)
            if g ~= 0 then g2[g] = true end
        end
        groups = g2
    end
    -- (0.105.47) why the centres and courts failed, counted: B and F were
    -- refused 31 and 63 times with the bare "no open, flat ground" whatever
    -- had ruled each court out
    local tally = {}
    local function fail(why) tally[why] = (tally[why] or 0) + 1 end
    local farms = surface_farm_spots()
    local okm, mouth = pcall(deep_depot_mouth)       -- (0.105.30)
    mouth = okm and mouth or nil
    local cache = {}
    local function kt(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = keep_tile(x, y, z) or false; cache[k] = v end
        return v
    end
    local function reach(x, y, z)
        local g = walk_group(x, y, z)
        return g ~= 0 and (any_group or groups[g] == true)
    end
    local function open_above(x, y, z)
        local t = tile_info(x, y, z + 1)
        return t ~= nil and t.shape == 'EMPTY'
    end
    -- the centres worth a full look: open, reachable ground under the open
    -- sky, scored by the walk from the fields (or the way in)
    -- (round the ways in, and round the first few fields: a field may lie
    -- further out than the reach)
    local areas = {}
    for _, a in ipairs(anchors) do
        table.insert(areas, {x = a.x, y = a.y, z1 = a.z - KEEP_COURT_LEVELS, z2 = a.z + 1, reach = KEEP_COURT_REACH})
    end
    for i, f in ipairs(farms) do
        if i > KEEP_COURT_FARMS then break end
        table.insert(areas, {x = f.x, y = f.y, z1 = f.z - 1, z2 = f.z + 1, reach = KEEP_COURT_FARM_REACH})
    end
    local cands, seen = {}, {}
    local deadline = os.clock() + KEEP_COURT_SECONDS
    local cut = false
    for _, ar in ipairs(areas) do
        for z = ar.z1, ar.z2 do
            for y = ar.y - ar.reach, ar.y + ar.reach do
                if os.clock() > deadline then cut = true break end
                for x = ar.x - ar.reach, ar.x + ar.reach do
                    local k = (z * 4096 + y) * 4096 + x
                    local g = not seen[k] and kt(x, y, z) == 'ground'
                    if g and not open_above(x, y, z) then
                        fail('ground with no open sky above'); g = false
                    elseif g and not reach(x, y, z) then
                        fail('ground the dwarves can\'t walk to'); g = false
                    end
                    if g then
                        seen[k] = true
                        local score = math.huge
                        for _, a in ipairs(anchors) do
                            local ad = math.max(math.abs(x - a.x), math.abs(y - a.y)) + 3 * math.abs(z - a.z)
                            if ad < score then score = ad end
                        end
                        for _, f in ipairs(farms) do
                            local fd = math.max(math.abs(x - f.x), math.abs(y - f.y)) + 3 * math.abs(z - f.z)
                            if fd < score then score = fd end
                        end
                        table.insert(cands, {x = x, y = y, z = z, score = score})
                    end
                end
            end
            if cut then break end
        end
        if cut then break end
    end
    table.sort(cands, function(p, q)
        if p.score ~= q.score then return p.score < q.score end
        if p.z ~= q.z then return p.z > q.z end
        if p.y ~= q.y then return p.y < q.y end
        return p.x < q.x
    end)
    local last = 'no open, flat ground the dwarves can reach within ' .. KEEP_COURT_REACH .. ' tiles of the way in'
    local best, best_score
    for _, radii in ipairs({KEEP_COURT_RADII, KEEP_COURT_SMALL}) do
        if best then break end
        for i, c in ipairs(cands) do
            if i > KEEP_COURT_CANDIDATES or os.clock() > deadline + KEEP_COURT_SECONDS then break end
            if best_score and c.score >= best_score then break end
            for _, r in ipairs(radii) do
                local fits = true
                -- the inside: open flat ground, the sky open above, the way in not in it
                for y = c.y - r + 1, c.y + r - 1 do
                    for x = c.x - r + 1, c.x + r - 1 do
                        local v = kt(x, y, c.z)
                        if v ~= 'ground' then
                            fits = false
                            fail('inside: ' .. (v == 'tree' and 'a tree' or v == 'wall' and 'rock or a wall'
                                or v == 'planned' and 'something being built' or keep_tile_why(x, y, c.z)))
                            break
                        elseif not open_above(x, y, c.z) then
                            fits = false
                            fail('inside: no open sky above')
                            break
                        end
                    end
                    if not fits then break end
                end
                if fits then
                    for _, a in ipairs(anchors) do
                        local clear = r + KEEP_COURT_CLEAR
                        if math.abs(a.z - c.z) <= 1 and math.abs(a.x - c.x) <= clear and math.abs(a.y - c.y) <= clear then
                            fits = false
                        end
                    end
                    if not fits then fail('too near the way in') end
                end
                local trees, ground = {}, 0
                if fits then
                    for _, p in ipairs(ring_tiles(c.x, c.y, r)) do
                        local k = kt(p.x, p.y, c.z)
                        if not k or k == 'planned' then
                            fits = false
                            fail('its walls: ' .. (k and 'something being built' or keep_tile_why(p.x, p.y, c.z)))
                            break
                        end
                        if k == 'tree' then table.insert(trees, {x = p.x, y = p.y, z = c.z}) end
                        if k == 'ground' then ground = ground + 1 end
                    end
                end
                if fits and (#trees > SURFACE_MAX_TREES or ground == 0) then
                    fits = false
                    fail(ground == 0 and 'its walls: all rock' or 'too many trees to fell')
                end
                if fits and depot_inside(c.x - r, c.y - r, c.x + r, c.y + r, c.z) then
                    fits, last = false, 'the open ground near the fort holds the trade depot'
                end
                if fits and mouth then
                    -- (0.105.30) no wall in front of the underground depot's road (the wagons turn in there)
                    for _, m in ipairs(mouth) do
                        if math.abs(m.z - c.z) <= 1 and math.abs(m.x - c.x) <= r + 1 and math.abs(m.y - c.y) <= r + 1 then
                            fits, last = false, 'the open ground near the fort is the underground depot\'s wagon road'
                            break
                        end
                    end
                end
                local door = fits and keep_door(c.x, c.y, c.z, r)
                if door then
                    local d = {x = door.x - c.x, y = door.y - c.y}
                    local ox, oy = door.x + (d.x > 0 and 1 or d.x < 0 and -1 or 0), door.y + (d.y > 0 and 1 or d.y < 0 and -1 or 0)
                    if not reach(ox, oy, c.z) then door = nil end
                end
                if fits and not door then fail('no side with open ground for a door') end
                if fits and door then
                    local score = c.score + SURFACE_TREE_COST * #trees
                    if not best_score or score < best_score then
                        best, best_score = {x = c.x, y = c.y, z = c.z, r = r, door = door, trees = trees, court = true}, score
                    end
                    break
                end
            end
        end
    end
    if best then return best end
    return nil, last .. court_tally(tally, #cands)
end

-- (0.105.47) The court search's failures in words, the commonest first:
-- " (N open tiles looked at; inside: a ramp_top tile 40, too near the way in 12)".
function court_tally(tally, n)
    local list = {}
    for why, k in pairs(tally or {}) do table.insert(list, {why = why, n = k}) end
    if #list == 0 and not n then return '' end
    table.sort(list, function(a, b) if a.n ~= b.n then return a.n > b.n end return a.why < b.why end)
    local parts = {}
    for i, e in ipairs(list) do
        if i > 4 then break end
        table.insert(parts, ('%s %d'):format(e.why, e.n))
    end
    return (' (%d open tile(s) looked at%s)'):format(n or 0, #parts > 0 and ('; ' .. table.concat(parts, ', ')) or '')
end

-- A site for the keep around the surface entrance: {x, y, z, r, door, trees}.
-- (0.105.23) Every way in first; with no ring round any, a court on open
-- ground near the fields (find_keep_court).
function find_keep_site()
    local anchors = surface_anchors()          -- (0.105.30) on the open ground's level
    if #anchors == 0 then return nil, 'no surface entrance or staircase to build the keep around' end
    local site, last = find_keep_ring(anchors)
    if site then return site end
    local okc, court, why = pcall(find_keep_court, anchors)
    if okc and court then return court end
    return nil, ('%s; %s'):format(last, okc and why or ('the search for open ground failed: ' .. tostring(court)))
end

-- A ring round one of the ways in, or nil and why.
function find_keep_ring(anchors)
    local under = depot_underground()
    if under then return nil, under end
    local last, first_bad
    local bads = {}       -- (0.105.47) each way in's first bad tile (only the first was named)
    for _, a in ipairs(anchors) do
        first_bad = nil
        for _, r in ipairs(KEEP_RADII) do
            local fits, trees, ground = true, {}, 0
            for _, p in ipairs(ring_tiles(a.x, a.y, r)) do
                local k = keep_tile(p.x, p.y, a.z)
                if not k or k == 'planned' then
                    -- (0.105.30) the first ring's first bad tile, named
                    first_bad = first_bad or ('r%d meets %s at x%d y%d, elevation %d'):format(r,
                        k and 'a wall waiting to be built' or keep_tile_why(p.x, p.y, a.z), p.x, p.y, ez(a.z))
                    fits = false
                    break
                end
                if k == 'tree' then table.insert(trees, {x = p.x, y = p.y, z = a.z}) end
                if k == 'ground' then ground = ground + 1 end
            end
            if fits and #trees > SURFACE_MAX_TREES then
                fits, last = false, ('too many trees around the way in (%d to fell)'):format(#trees)
            end
            if fits and ground == 0 and #trees == 0 then
                fits = false
                first_bad = first_bad or ('r%d is all rock'):format(r)
            end
            if fits and depot_inside(a.x - r, a.y - r, a.x + r, a.y + r, a.z) then
                fits, last = false, 'the trade depot is right by the way in (a wall round it would shut out the wagons)'
            end
            local door = fits and keep_door(a.x, a.y, a.z, r)
            if fits and not door then last = 'no side of the ring has open ground for a door' end
            if fits and door then
                return {x = a.x, y = a.y, z = a.z, r = r, door = door, trees = trees}
            end
        end
        if first_bad and #bads < 3 then table.insert(bads, first_bad) end
    end
    return nil, last or ('no ring of open ground around the way in (%s)'):format(
        #bads > 0 and table.concat(bads, '; ') or 'water, slopes, buildings or zones in the way')
end

-- How far it's got: {stage, x, y, z, r, walls_left, roof_left, trees_left}.
function keep_status()
    local k = keep_data()
    if not k then return nil end
    local out = {stage = k.stage, x = k.x, y = k.y, z = k.z, r = k.r, walls_left = 0, walls_planned = 0,
                 roof_left = 0, roof_planned = 0, trees_left = 0, court = k.court}
    for _, p in ipairs(ring_tiles(k.x, k.y, k.r)) do
        local t = keep_tile(p.x, p.y, k.z)
        if t == 'tree' then out.trees_left = out.trees_left + 1 end
        local is_door = k.door and p.x == k.door.x and p.y == k.door.y
        if not is_door and t ~= 'wall' then out.walls_left = out.walls_left + 1 end
        if not is_door and t == 'planned' and keep_wall_waits(p.x, p.y, k.z) then
            out.walls_planned = out.walls_planned + 1
        end
    end
    -- (0.105.30) the roof stair: its lower half waiting counts as roof to build
    if k.stage == 'stair' and k.stair then
        local t = tile_info(k.stair.x, k.stair.y, k.z)
        if t and t.building and t.shape ~= 'STAIR_UP' then
            out.stair_planned, out.roof_planned = 1, 1
        end
    end
    out.stair = k.stair
    if k.stage == 'roof' or k.stage == 'done' then
        for y = k.y - k.r + 1, k.y + k.r - 1 do
            for x = k.x - k.r + 1, k.x + k.r - 1 do
                local t = tile_info(x, y, k.z + 1)
                if t and t.shape == 'EMPTY' then
                    out.roof_left = out.roof_left + 1
                    if t.building then out.roof_planned = out.roof_planned + 1 end
                end
            end
        end
    end
    -- (0.105.33) the blocks still to go into it, for the brain's stone-blocks
    -- order (it read keep.blocks_needed, which was never written): the walls
    -- not built yet (planned ones wait for blocks too), the roof (its whole
    -- inside before the roof stage) and the roof stair's two halves
    if k.stage == 'done' then
        out.blocks_needed = 0
    else
        local inner = math.max(0, 2 * k.r - 1)
        local roof = (k.stage == 'roof') and out.roof_left or inner * inner
        local stair = 0
        if ROOF_STAIR and k.stage ~= 'roof' then stair = (k.stage == 'stair') and 1 or 2 end
        out.blocks_needed = out.walls_left + roof + stair
    end
    out.elevation = ez(k.z)
    return out
end

local function keep_apply(cells, z, what, dry_run)
    local good, failed, res = qf_try('build', cells, z, 0, 0, dry_run)
    if failed == 'dry' then return nil, ('the game would not place %s'):format(what) end
    if not good then return nil, ('the game refused %s'):format(what) end
    return stat(res, 'build_designated')
end

-- (0.105.30) The roof at z+1 over the inside; over a built roof stair a
-- stair down (Cd), dropped if the game won't take it.
local function keep_roof(k, dry_run)
    local cells, stair_cell = {}, nil
    local built = k.stair and stair_shape(k.stair.x, k.stair.y, k.z) == 'STAIR_UP'
    for y = k.y - k.r + 1, k.y + k.r - 1 do
        for x = k.x - k.r + 1, k.x + k.r - 1 do
            local t = tile_info(x, y, k.z + 1)
            if t and t.shape == 'EMPTY' and not t.building then
                local is_stair = built and x == k.stair.x and y == k.stair.y
                table.insert(cells, {x = x, y = y, text = is_stair and 'Cd' or 'Cf'})
                if is_stair then stair_cell = cells[#cells] end
            end
        end
    end
    if #cells == 0 then
        if not dry_run then k.stage = 'done'; save_keep(k) end
        return {ok = true, stage = 'done', x = k.x, y = k.y, dry_run = dry_run or nil}
    end
    local n, why = keep_apply(cells, k.z + 1, 'the keep\'s roof', dry_run)
    if not n and stair_cell then
        -- (r9, audit A3 13) a stair down the game won't take: that tile left
        -- open, not floored (a floor over the roof stair, laid from the roof,
        -- shut its builder up there with no way down)
        for i, c in ipairs(cells) do
            if c == stair_cell then table.remove(cells, i) break end
        end
        stair_cell = nil
        n, why = 0, nil
        if #cells > 0 then n, why = keep_apply(cells, k.z + 1, 'the keep\'s roof', dry_run) end
    end
    if not n then return {ok = false, error = why} end
    if not dry_run then k.stage = 'roof'; save_keep(k) end
    return {ok = true, stage = 'roof', roof = n, stair = stair_cell and true or nil, x = k.x, y = k.y, r = k.r,
            elevation = ez(k.z + 1), dry_run = dry_run or nil}
end

-- One step of the keep (see above).
function place_keep(dry_run)
    OFFSET = elevation_offset()
    local k = keep_data()
    if k and k.stage == 'done' then
        return {ok = false, rejected = true, done = true, error = 'the keep is finished'}
    end
    if not k then
        local site, why = find_keep_site()
        if not site then return {ok = false, error = why} end
        k = {x = site.x, y = site.y, z = site.z, r = site.r, door = site.door, stage = 'clearing',
             court = site.court or nil}
        if #site.trees > 0 then
            local out = {ok = true, stage = 'clearing', clearing = true, trees = #site.trees, x = k.x, y = k.y,
                         r = k.r, elevation = ez(k.z), court = k.court, dry_run = dry_run or nil}
            if dry_run then return out end
            for _, t in ipairs(site.trees) do fell_tree(t.x, t.y, t.z) end
            save_keep(k)
            return out
        end
    end
    local st = {}
    if k.stage == 'clearing' then
        -- (0.104.0) a depot dug underground since the site was chosen
        -- ((0.105.23) a court away from the way in doesn't stand in the wagons' way)
        local under = not k.court and depot_underground()
        if under then
            if not dry_run then save_keep(nil) end
            return {ok = false, error = under}
        end
        local trees = {}
        for _, p in ipairs(ring_tiles(k.x, k.y, k.r)) do
            local t = keep_tile(p.x, p.y, k.z)
            if t == 'tree' then table.insert(trees, p) end
            if t == nil then
                if not dry_run then save_keep(nil) end
                return {ok = false, error = 'something was put in the way of the keep\'s walls: looking again next time'}
            end
        end
        if #trees > 0 then
            if not dry_run then for _, p in ipairs(trees) do fell_tree(p.x, p.y, k.z) end end
            return {ok = false, rejected = true, waiting = true, stage = 'clearing', trees = #trees,
                    error = ('the dwarves are still felling %d tree(s) for the keep\'s walls'):format(#trees)}
        end
        local cells = {}
        for _, p in ipairs(ring_tiles(k.x, k.y, k.r)) do
            if keep_tile(p.x, p.y, k.z) == 'ground' then
                local door = p.x == k.door.x and p.y == k.door.y
                table.insert(cells, {x = p.x, y = p.y, text = door and 'd' or 'Cw'})
            end
        end
        local n, why = keep_apply(cells, k.z, 'the keep\'s walls', dry_run)
        if not n then return {ok = false, error = why} end
        local out = {ok = true, stage = 'walls', walls = n, x = k.x, y = k.y, r = k.r, door = k.door,
                     elevation = ez(k.z), court = k.court, dry_run = dry_run or nil}
        if not dry_run then k.stage = 'walls'; save_keep(k) end
        return out
    end
    if k.stage == 'walls' then
        st = keep_status() or {}
        -- (a wall tile the game refused never gets built: the roof goes on
        -- once nothing of the walls waits to be built)
        if (st.walls_planned or 0) > 0 then
            return {ok = false, rejected = true, waiting = true, stage = 'walls', walls_left = st.walls_planned,
                    error = ('the keep\'s walls are going up: %d to build'):format(st.walls_planned)}
        end
        -- (0.105.30, construction 3.0.2) a stair up in an inside corner first,
        -- so the roof can be reached ([verify] in game; ROOF_STAIR = false
        -- once the game is seen building the roof from below). Refused: the
        -- roof goes on without it.
        local s = roof_access(k.x - k.r + 1, k.y - k.r + 1, k.x + k.r - 1, k.y + k.r - 1, k.z, k.door)
        if s then
            local good, failed = qf_try('build', {{x = s.x, y = s.y, text = 'Cu'}}, k.z, 0, 0, dry_run)
            if good then
                if not dry_run then k.stage = 'stair'; k.stair = {x = s.x, y = s.y}; save_keep(k) end
                return {ok = true, stage = 'stair', stair = {x = s.x, y = s.y}, x = k.x, y = k.y, r = k.r,
                        elevation = ez(k.z), dry_run = dry_run or nil}
            end
        end
        return keep_roof(k, dry_run)
    end
    if k.stage == 'stair' then
        st = keep_status() or {}
        if (st.stair_planned or 0) > 0 then
            return {ok = false, rejected = true, waiting = true, stage = 'stair', roof_left = st.roof_planned,
                    error = 'the keep\'s stair to the roof is being built'}
        end
        return keep_roof(k, dry_run)
    end
    -- the roof is going up
    st = keep_status() or {}
    if (st.roof_planned or 0) > 0 then
        return {ok = false, rejected = true, waiting = true, stage = 'roof', roof_left = st.roof_planned,
                error = ('the keep\'s roof is going up: %d tile(s) to build'):format(st.roof_planned)}
    end
    if not dry_run then k.stage = 'done'; save_keep(k) end
    return {ok = true, stage = 'done', x = k.x, y = k.y, holes = st.roof_left, dry_run = dry_run or nil}
end
