-- ai-builder-court: (0.105.47) the Garden fort's garden court above ground.
-- (13c) A part of ai-builder, not a script of its own (see below).
-- The player (14 Nov): "garden fort should have gardens". The Garden fort
-- (F) dug the most statue gardens of the six forts, but nothing of its
-- surface character stood: no court, no hall by its 12 fields.
--
-- A walled court on open ground by the surface fields (else by the way in):
-- a ring of constructed walls with one door, inside it the layout
-- ai-layouts.garden_court gives: four beds (farm plots of above-ground
-- crops: DF 53 has no job to plant a tree or a shrub), the trees already
-- standing inside kept, soil and grass between, a cross of block paths,
-- statues round the heart (free ones only), seats by the walls, and a
-- meeting area over it all named for the fort ("The <name> Garden Court").
--
-- (13c) A part of ai-builder (ai-builder.lua loads it into its own
-- environment): keep_tile, is_tree, fell_tree, GROUND, surface_anchors,
-- surface_farm_spots, citizen_groups, keep_data, halls_data, depot_inside,
-- hall_planned_at, hall_free_items, qf_try, stat are the other parts'.
--
-- Built in stages, one action each (place_garden_court), each waiting for
-- the last one's planned tiles:
--   (search) -> clearing (the ring's trees felled) -> walls (Cw ring, a door)
--   -> beds (farm plots on the soil quarters; the block paths, asked for)
--   -> furnish (statues, seats) -> secure (r9 c1) -> zone (the meeting area) -> done
--   (or 'plain': a court that cannot be secured stays a garden, no meeting area)
-- Every tile placed goes on the record. The state lives in the save (site
-- data 'ai-overseer/garden_court'). The brain decides (planner_garden.py):
-- {name, paths, statues} come in as opts; nothing here reads the sliders.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-court'] = '0.105.74'   -- (0.105.26) bumped with BRIDGE_VERSION

COURT_KEY = 'ai-overseer/garden_court'
COURT_RADII = {5, 4}              -- the bigger first (the inside 9x9, then 7x7)
COURT_REACH = 14                  -- tiles round a field (or the way in) looked at
COURT_LEVELS = 1                  -- levels above and below a field
COURT_SECONDS = 1.5
COURT_CANDIDATES = 300
COURT_CLEAR = 3                   -- tiles kept from the keep, a hall and a way in
COURT_SOIL_BONUS = 10            -- soil inside counts up to this many tiles nearer (a tile of score per 8 of soil)
COURT_MAX_TREES_INSIDE = 12       -- standing trees kept inside (more: a wood, not a court)
COURT_SOIL = {SOIL = true, GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true, GRASS_DEAD = true}
COURT_NAME_RE = "^[A-Za-z' ]+$"
-- (r9, audit A3 12) days the beds and furnish stages wait for their pieces:
-- a chair, a statue or a path's blocks that never come no longer hold the
-- court for ever; past this the court goes on and the pieces stay planned
-- (built when the items come)
COURT_WAIT_DAYS = 30

-- (r9 c1) The player (21 Nov): the court is a meeting area only while no
-- danger is about, and only once it is secured. The 'secure' stage (after
-- furnish, before the meeting area): every tile of the ring a wall (natural or
-- built), its one way in a door the AI locks (door_flags.forbidden, as the
-- gates lock theirs: ai-util lock_door). Walls gone missing are placed again,
-- a tree on the line felled. It cannot be secured (it stays a plain garden,
-- 'plain', the why on the record and in the report):
--   * a way into the fort inside it (its gate would shut the fort in);
--   * a tile of the ring that takes no wall (a building, water, a stockpile);
--   * the game refused its walls COURT_SECURE_TRIES times;
--   * its walls placed again COURT_SECURE_TRIES times and still not closed, or
--     waiting COURT_WAIT_DAYS for their material.
-- An older save past the zone ('done', not secured) gets 'secure' next, its
-- meeting area switched off until it is secured. garden_court_meeting (the
-- brain's danger watch, planner_garden) switches the meeting area off and on
-- (the civzone's spec_sub_flag.active) and locks the door while danger is
-- about, never with a citizen inside the court.
COURT_SECURE_TRIES = 3
SECURE_WALL = {WALL = true, FORTIFICATION = true}

-- (r9) days since the court entered its stage (nil: an older save, not known)
local function stage_days(c)
    local t = tonumber(c.stage_tick)
    if not t then return nil end
    return math.max(0, (now_tick() - t) // 1200)
end

function court_data()
    local d = site_get(COURT_KEY)
    if not d.x then return nil end
    -- (r9 c1) an older save past the zone: the 'secure' step next, its
    -- meeting area kept on the record (switched off until it is secured)
    if d.stage == 'done' and not d.secured and not d.plain then
        d.stage, d.stage_tick = 'secure', nil
        for _, p in ipairs(d.tiles or {}) do
            if tostring(p.t):sub(1, 1) == 'm' then d.zoned = true end
        end
    end
    return d
end

local function save_court(d)
    site_put(COURT_KEY, d or {})
end

-- (for the other parts' searches: the hall keeps clear of the court)
function court_rects()
    local c = court_data()
    if not c then return {} end
    return {{x1 = c.x - c.r, y1 = c.y - c.r, x2 = c.x + c.r, y2 = c.y + c.r, z = c.z}}
end

local function court_ring(cx, cy, r)
    local L = reqscript('ai-layouts').garden_court({r = r})
    local out = {}
    for _, p in ipairs(L.ring) do table.insert(out, {x = cx + p.x, y = cy + p.y}) end
    return out
end

local function soil_at(x, y, z)
    local t = tile_info(x, y, z)
    return t ~= nil and GROUND[t.shape] == true and COURT_SOIL[t.material] == true
end

-- The door: the middle of the side facing the nearest anchor (the way in)
-- whose ring tile takes a wall, open ground both sides of it.
local function court_door(cx, cy, z, r, anchors, reach)
    local sides = {{0, 1}, {1, 0}, {0, -1}, {-1, 0}}
    local function dist(d)
        local best = math.huge
        for _, a in ipairs(anchors) do
            local v = math.max(math.abs(cx + d[1] * (r + 1) - a.x), math.abs(cy + d[2] * (r + 1) - a.y))
            if v < best then best = v end
        end
        return best
    end
    table.sort(sides, function(a, b)
        local da, db = dist(a), dist(b)
        if da ~= db then return da < db end
        if a[2] ~= b[2] then return a[2] > b[2] end
        return a[1] > b[1]
    end)
    for _, d in ipairs(sides) do
        local x, y = cx + d[1] * r, cy + d[2] * r
        local inner, outer = tile_info(x - d[1], y - d[2], z), tile_info(x + d[1], y + d[2], z)
        if keep_tile(x, y, z) == 'ground' and inner and outer and GROUND[inner.shape] and GROUND[outer.shape]
                and not inner.building and not outer.building and not outer.liquid
                and reach(x + d[1], y + d[2], z) then
            return {x = x, y = y}
        end
    end
end

-- A site for the court: {x, y, z, r, door, trees (on the ring), kept
-- (trees inside), soil} or nil and why.
function find_garden_court_site()
    local anchors = surface_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to build the garden court near' end
    local groups = citizen_groups()
    local any_group = next(groups) == nil
    local function reach(x, y, z)
        local g = walk_group(x, y, z)
        return g ~= 0 and (any_group or groups[g] == true)
    end
    local cache = {}
    local function kt(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = keep_tile(x, y, z) or false; cache[k] = v end
        return v
    end
    local function open_above(x, y, z)
        local t = tile_info(x, y, z + 1)
        return t ~= nil and t.shape == 'EMPTY'
    end
    local farms = surface_farm_spots()
    local avoid = {}
    local okk, k = pcall(keep_data)
    if okk and k then table.insert(avoid, {x1 = k.x - k.r, y1 = k.y - k.r, x2 = k.x + k.r, y2 = k.y + k.r, z = k.z}) end
    local okh, hd = pcall(halls_data)
    for _, h in ipairs(okh and hd and hd.list or {}) do
        table.insert(avoid, {x1 = h.x1, y1 = h.y1, x2 = h.x2, y2 = h.y2, z = h.z})
    end
    local okm, mouth = pcall(deep_depot_mouth)
    mouth = okm and type(mouth) == 'table' and mouth or {}
    local mw, mh = map_size()
    -- the areas looked round: the fields first, else the ways in
    local areas = {}
    for i, f in ipairs(farms) do
        if i > 6 then break end
        table.insert(areas, {x = f.x, y = f.y, z1 = f.z - COURT_LEVELS, z2 = f.z + COURT_LEVELS})
    end
    if #areas == 0 then
        for _, a in ipairs(anchors) do table.insert(areas, {x = a.x, y = a.y, z1 = a.z - COURT_LEVELS, z2 = a.z + 1}) end
    end
    local function score_of(x, y, z)
        local best = math.huge
        for _, f in ipairs(#farms > 0 and farms or anchors) do
            local d = math.max(math.abs(x - f.x), math.abs(y - f.y)) + 3 * math.abs(z - f.z)
            if d < best then best = d end
        end
        return best
    end
    local cands, seen = {}, {}
    local deadline = os.clock() + COURT_SECONDS
    local cut = false
    for _, ar in ipairs(areas) do
        for z = ar.z1, ar.z2 do
            for y = ar.y - COURT_REACH, ar.y + COURT_REACH do
                if os.clock() > deadline then cut = true break end
                for x = ar.x - COURT_REACH, ar.x + COURT_REACH do
                    local key = (z * 4096 + y) * 4096 + x
                    if not seen[key] and kt(x, y, z) == 'ground' and open_above(x, y, z) and reach(x, y, z) then
                        seen[key] = true
                        table.insert(cands, {x = x, y = y, z = z, score = score_of(x, y, z)})
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
    local last = ('no open, flat ground the dwarves can reach within %d tiles of the %s'):format(
        COURT_REACH, #farms > 0 and 'fields' or 'way in')
    -- the biggest court that fits (COURT_RADII in turn), nearest the fields
    local best, best_score
    for _, r in ipairs(COURT_RADII) do
    for i, c in ipairs(cands) do
        if i > COURT_CANDIDATES or os.clock() > deadline + 2 * COURT_SECONDS then break end
        if best_score and c.score - COURT_SOIL_BONUS >= best_score then break end
        do
            local fits, why = true, nil
            if c.x - r < 2 or c.y - r < 2 or c.x + r > mw - 3 or c.y + r > mh - 3 then fits, why = false, 'the map\'s edge' end
            local kept, soil = {}, 0
            if fits then
                for y = c.y - r + 1, c.y + r - 1 do
                    for x = c.x - r + 1, c.x + r - 1 do
                        local v = kt(x, y, c.z)
                        if v == 'tree' then
                            table.insert(kept, {x = x, y = y})
                        elseif v ~= 'ground' or not open_above(x, y, c.z) then
                            fits, why = false, v == false and keep_tile_why(x, y, c.z) or 'no open sky over the ground'
                            break
                        elseif soil_at(x, y, c.z) then
                            soil = soil + 1
                        end
                    end
                    if not fits then break end
                end
            end
            if fits and #kept > COURT_MAX_TREES_INSIDE then fits, why = false, 'a wood, not open ground' end
            if fits then
                for _, a in ipairs(anchors) do
                    local clear = r + COURT_CLEAR
                    if math.abs(a.z - c.z) <= 1 and math.abs(a.x - c.x) <= clear and math.abs(a.y - c.y) <= clear then
                        fits, why = false, 'too near the way in (the wagons\' road)'
                    end
                end
            end
            if fits then
                for _, b in ipairs(avoid) do
                    if math.abs(b.z - c.z) <= 1 and c.x - r - COURT_CLEAR <= b.x2 and c.x + r + COURT_CLEAR >= b.x1
                            and c.y - r - COURT_CLEAR <= b.y2 and c.y + r + COURT_CLEAR >= b.y1 then
                        fits, why = false, 'too near the keep or a hall'
                    end
                end
            end
            if fits and depot_inside(c.x - r - 1, c.y - r - 1, c.x + r + 1, c.y + r + 1, c.z) then
                fits, why = false, 'the trade depot is there'
            end
            if fits then
                for _, m in ipairs(mouth) do
                    if math.abs(m.z - c.z) <= 1 and math.abs(m.x - c.x) <= r + 1 and math.abs(m.y - c.y) <= r + 1 then
                        fits, why = false, 'the underground depot\'s wagon road'
                    end
                end
            end
            local trees = {}
            if fits then
                for _, p in ipairs(court_ring(c.x, c.y, r)) do
                    local v = kt(p.x, p.y, c.z)
                    if not v or v == 'planned' then
                        fits, why = false, v == 'planned' and 'something being built where a wall goes'
                            or keep_tile_why(p.x, p.y, c.z)
                        break
                    end
                    if v == 'tree' then table.insert(trees, {x = p.x, y = p.y, z = c.z}) end
                end
            end
            if fits and #trees > SURFACE_MAX_TREES then fits, why = false, 'too many trees on the walls\' line' end
            local door = fits and court_door(c.x, c.y, c.z, r, anchors, reach) or nil
            if fits and not door then fits, why = false, 'no side has open ground the dwarves can reach for a door' end
            if fits then
                -- the soil counts (the beds want it), trees to fell cost, the bigger court first
                local score = c.score + SURFACE_TREE_COST * #trees - math.min(COURT_SOIL_BONUS, soil // 8)
                if not best_score or score < best_score then
                    best, best_score = {x = c.x, y = c.y, z = c.z, r = r, door = door, trees = trees, kept = #kept,
                                        soil = soil}, score
                end
            elseif why then
                last = why
            end
        end
    end
    if best then break end
    end
    if best then return best end
    local w = 'no site for the garden court: ' .. last
    if cut then return nil, 'search cut short: ' .. w, true end
    return nil, w
end

-- What a placed tile is now: 'built', 'planned' or 'none'.
local BUILT = {Cw = 'WALL', Cf = 'FLOOR'}
local function piece_state(p)
    local t = tile_info(p.x, p.y, p.z)
    if not t then return 'none' end
    local want = BUILT[p.t]
    if want then
        if t.building then return 'planned' end
        return t.shape == want and 'built' or 'none'
    end
    if hall_planned_at(p.x, p.y, p.z) then return 'planned' end
    return t.building and 'built' or 'none'
end

local function counts(c)
    local n = {walls_planned = 0, walls_left = 0, planned = 0, trees_left = 0, beds = 0, statues = 0, seats = 0,
               paths = 0}
    if c.stage == 'clearing' then
        for _, p in ipairs(court_ring(c.x, c.y, c.r)) do
            if is_tree(tile_info(p.x, p.y, c.z)) then n.trees_left = n.trees_left + 1 end
        end
    end
    for _, p in ipairs(c.tiles or {}) do
        local s = piece_state(p)
        local key = tostring(p.t):sub(1, 1)
        if p.t == 'Cw' then
            if s == 'planned' then n.walls_planned = n.walls_planned + 1 end
            if s ~= 'built' then n.walls_left = n.walls_left + 1 end
        elseif s == 'planned' and key ~= 'p' then
            -- (a bed, a farm plot, needs no materials and no builder's wait: not counted)
            n.planned = n.planned + 1
        end
        if s ~= 'none' then
            if key == 'p' then n.beds = n.beds + 1
            elseif p.t == 's' then n.statues = n.statues + 1
            elseif p.t == 'c' then n.seats = n.seats + 1
            elseif p.t == 'Cf' then n.paths = n.paths + 1 end
        end
    end
    return n
end

-- --- (r9 c1) the meeting area, the door, the court's people ------------------------
-- (each one a function of its own: tests swap them)

-- The court's meeting area (a civzone of type MeetingHall over its heart), or nil.
function court_zone(c)
    local ok, zn = pcall(function()
        for _, z in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(c.x, c.y, c.z)) or {}) do
            if z.type == df.civzone_type.MeetingHall then return z end
        end
    end)
    return ok and zn or nil
end

-- Is a zone on (DF's "active"; off: idle dwarves don't gather there)? nil: unread.
function zone_on(zn)
    local ok, v = pcall(function() return zn.spec_sub_flag.active end)
    if not ok or v == nil then return nil end
    return v == true or v == 1
end

-- Switch a zone on or off: true when it reads so after.
function set_zone_on(zn, on)
    pcall(function() zn.spec_sub_flag.active = on end)
    return zone_on(zn) == on
end

-- The court's door: 'built', 'planned' (waiting to be built), 'none' (nothing
-- there) or 'other' (some other building in its way in).
function court_door_state(c)
    local ok, st = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(c.door.x, c.door.y, c.z))
        if not b then return 'none' end
        if b:getType() ~= df.building_type.Door then return 'other' end
        return b:getBuildStage() < b:getMaxBuildStage() and 'planned' or 'built'
    end)
    return ok and st or 'none'
end

-- Is the court's door locked? nil: no door, or unread.
function court_door_locked(c)
    local ok, v = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(c.door.x, c.door.y, c.z))
        return b and b.door_flags.forbidden
    end)
    if not ok or v == nil then return nil end
    return v == true
end

-- Lock (true) or unlock (false) the court's door as the gates lock theirs.
function court_lock_door(c, locked)
    local ok, changed = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(c.door.x, c.door.y, c.z))
        if not b or b:getType() ~= df.building_type.Door then return false end
        return reqscript('ai-util').lock_door(b, locked, 'garden court')
    end)
    return ok and changed or false
end

-- How many citizens stand inside the court's walls.
function court_citizens_inside(c)
    local n = 0
    local ok, list = pcall(citizen_positions)
    for _, p in ipairs(ok and list or {}) do
        if p.z == c.z and math.abs(p.x - c.x) < c.r and math.abs(p.y - c.y) < c.r then n = n + 1 end
    end
    return n
end

-- A way into the fort inside the court (a way in from the surface, a stair
-- down): why it can't be shut, or nil. ("Never sealed in": its gate locked
-- would shut that way.)
local function court_way_in(c)
    local ok, anchors = pcall(surface_anchors)
    for _, a in ipairs(ok and anchors or {}) do
        if math.abs(a.z - c.z) <= 1 and math.abs(a.x - c.x) <= c.r and math.abs(a.y - c.y) <= c.r then
            return 'a way into the fort is inside it (its gate shut would shut the fort in)'
        end
    end
    for y = c.y - c.r + 1, c.y + c.r - 1 do
        for x = c.x - c.r + 1, c.x + c.r - 1 do
            local oks, sh = pcall(stair_shape, x, y, c.z)
            if oks and sh then return 'a stair into the fort is inside it (its gate shut would shut that way)' end
        end
    end
    return nil
end

-- The ring as it stands: {built, planned, missing = {tiles}, trees = {tiles},
-- door ('built'|'planned'|'none'|'other'), door_missing, gap (why a tile takes
-- no wall), way_in, secured}.
function court_secure_scan(c)
    local s = {built = 0, planned = 0, missing = {}, trees = {}}
    for _, p in ipairs(court_ring(c.x, c.y, c.r)) do
        if not (p.x == c.door.x and p.y == c.door.y) then
            local t = tile_info(p.x, p.y, c.z)
            if t and SECURE_WALL[t.shape] then
                s.built = s.built + 1
            elseif t and t.building then
                if keep_wall_waits(p.x, p.y, c.z) then s.planned = s.planned + 1
                else s.gap = s.gap or ('a building stands where its wall goes (%d, %d)'):format(p.x, p.y) end
            elseif is_tree(t) then
                table.insert(s.trees, p)
            elseif keep_tile(p.x, p.y, c.z) == 'ground' then
                table.insert(s.missing, p)
            else
                s.gap = s.gap or ('its wall\'s line meets %s (%d, %d)'):format(keep_tile_why(p.x, p.y, c.z), p.x, p.y)
            end
        end
    end
    s.door = court_door_state(c)
    if s.door == 'planned' then
        s.planned = s.planned + 1
    elseif s.door == 'other' then
        s.gap = s.gap or 'something other than a door stands in its way in'
    elseif s.door == 'none' then
        if keep_tile(c.door.x, c.door.y, c.z) == 'ground' then s.door_missing = true
        else s.gap = s.gap or ('its way in is %s'):format(keep_tile_why(c.door.x, c.door.y, c.z)) end
    end
    s.way_in = court_way_in(c)
    s.secured = not s.gap and not s.way_in and #s.missing == 0 and #s.trees == 0 and s.planned == 0
        and s.door == 'built'
    return s
end

-- The meeting area's and the door's state for the report.
local function meeting_view(c, out)
    out.secured, out.plain, out.plain_why, out.zoned = c.secured or nil, c.plain or nil, c.plain_why, c.zoned or nil
    if c.zoned then
        local zn = court_zone(c)
        if zn then out.meeting_on = zone_on(zn) else out.zone_gone = true end
    end
    if c.secured or c.zoned or c.stage == 'secure' then
        local ds = court_door_state(c)
        out.door_built = ds == 'built' or nil
        if ds == 'built' then out.locked = court_door_locked(c) end
        out.inside = court_citizens_inside(c)
        out.lockable = ds == 'built' and not court_way_in(c) or false
    end
end

-- The report's view (section garden_court): nil with no court.
-- {stage, x, y, elevation, r, name, walls_planned, walls_left, planned,
-- trees_left, beds, statues, seats, paths, blocks_needed, done}
function garden_court_status()
    local c = court_data()
    if not c then return nil end
    local out = counts(c)
    out.stage, out.x, out.y, out.r, out.name, out.door = c.stage, c.x, c.y, c.r, c.name, c.door
    out.elevation = ez(c.z)
    out.kept_trees = c.kept
    out.done = c.stage == 'done' or nil
    -- blocks still to go in: the ring (before the walls) and the paths (asked for)
    local need = 0
    if c.stage == 'clearing' then need = #court_ring(c.x, c.y, c.r) - 1 end
    if (c.stage == 'clearing' or c.stage == 'walls') and c.paths then need = need + 4 * (c.r - 1) end
    out.blocks_needed = need
    -- (r9) how long the stage has waited; past COURT_WAIT_DAYS the brain
    -- asks the next step anyway (place_garden_court goes on)
    out.stage_days = stage_days(c)
    out.wait_over = (c.stage == 'beds' or c.stage == 'furnish' or c.stage == 'secure')
        and (out.stage_days or 0) >= COURT_WAIT_DAYS or nil
    -- (r9 c1) secured, the meeting area and its door
    out.done = (c.stage == 'done' or c.stage == 'plain') or nil
    if c.stage == 'secure' then
        local sc = court_secure_scan(c)
        out.secure_planned, out.secure_missing = sc.planned, #sc.missing + (sc.door_missing and 1 or 0)
        out.secure_trees, out.secure_gap = #sc.trees, sc.gap or sc.way_in
    end
    meeting_view(c, out)
    return out
end

local function apply(mode, cells, z, what, dry_run)
    if #cells == 0 then return 0 end
    local good, failed, res = qf_try(mode, cells, z, 0, 0, dry_run)
    if failed == 'dry' then return nil, ('the game would not place %s'):format(what) end
    if not good then return nil, ('the game refused %s'):format(what) end
    return stat(res, mode .. '_designated')
end

local function record(c, cells, z)
    c.tiles = c.tiles or {}
    for _, cl in ipairs(cells) do table.insert(c.tiles, {x = cl.x, y = cl.y, z = z, t = cl.text}) end
end

-- A bed (farm plot) only where all its tiles are bare soil or grass.
local function bed_ok(x1, y1, w, h, z)
    for y = y1, y1 + h - 1 do
        for x = x1, x1 + w - 1 do
            local t = tile_info(x, y, z)
            if not (soil_at(x, y, z) and not t.building and keep_tile(x, y, z) == 'ground') then return false end
        end
    end
    return true
end

-- One step of the court (see the top). opts: {name, paths, statues}.
function place_garden_court(dry_run, opts)
    OFFSET = elevation_offset()
    opts = type(opts) == 'table' and opts or {}
    local name = type(opts.name) == 'string' and opts.name or 'Green'
    if not name:match(COURT_NAME_RE) or #name > 40 then
        return {ok = false, rejected = true, error = 'the garden court needs a plain name (letters, spaces, apostrophes; up to 40)'}
    end
    local c = court_data()
    if c and c.stage == 'done' then
        return {ok = false, rejected = true, done = true, error = 'the garden court is finished'}
    end
    if c and c.stage == 'plain' then      -- (r9 c1)
        return {ok = false, rejected = true, done = true, plain = true,
                error = 'the garden court stays a plain garden: ' .. tostring(c.plain_why)}
    end
    local function out(t)
        t.ok = t.ok ~= false
        t.x, t.y, t.r = c.x, c.y, c.r
        t.elevation = t.elevation or ez(c.z)
        t.dry_run = dry_run or nil
        t.garden_court = true
        return t
    end
    local function wait(stage, n, what)
        -- (r9) an older save's stage gets its start now, so its wait ends too
        if not dry_run and (stage == 'beds' or stage == 'furnish') and not c.stage_tick then
            c.stage_tick = now_tick(); save_court(c)
        end
        return out({ok = false, rejected = true, waiting = true, stage = stage, left = n,
                    error = ('the garden court: %d %s still to build'):format(n, what)})
    end
    if not c then
        local site, why, cut = find_garden_court_site()
        if not site then return {ok = false, error = why, timed_out = cut or nil} end
        c = {x = site.x, y = site.y, z = site.z, r = site.r, door = site.door, stage = 'clearing', name = name,
             paths = opts.paths == true, kept = site.kept, tiles = {}}
        if #site.trees > 0 then
            if not dry_run then
                for _, t in ipairs(site.trees) do fell_tree(t.x, t.y, t.z) end
                save_court(c)
            end
            return out({stage = 'clearing', clearing = true, trees = #site.trees, soil = site.soil})
        end
    end
    local n = counts(c)

    if c.stage == 'clearing' then
        local trees = {}
        for _, p in ipairs(court_ring(c.x, c.y, c.r)) do
            local v = keep_tile(p.x, p.y, c.z)
            if v == 'tree' then table.insert(trees, p)
            elseif v == nil or v == 'planned' then
                if not dry_run then save_court(nil) end
                return out({ok = false, error = 'something was put where the garden court\'s walls go: looking again next time'})
            end
        end
        if #trees > 0 then
            if not dry_run then for _, p in ipairs(trees) do fell_tree(p.x, p.y, c.z) end end
            return wait('clearing', #trees, 'tree(s) to fell')
        end
        local cells = {}
        for _, p in ipairs(court_ring(c.x, c.y, c.r)) do
            if keep_tile(p.x, p.y, c.z) == 'ground' then
                local door = p.x == c.door.x and p.y == c.door.y
                table.insert(cells, {x = p.x, y = p.y, text = door and 'd' or 'Cw'})
            end
        end
        local placed, why = apply('build', cells, c.z, 'the garden court\'s walls', dry_run)
        if not placed then return out({ok = false, error = why}) end
        if not dry_run then
            c.stage = 'walls'
            record(c, cells, c.z)
            save_court(c)
        end
        return out({stage = 'walls', walls = placed, door = c.door})
    end

    local L = reqscript('ai-layouts').garden_court({r = c.r, paths = c.paths, statues = 4})
    local function free(x, y)
        local t = tile_info(x, y, c.z)
        return t ~= nil and not t.building and GROUND[t.shape] == true and not is_tree(t)
    end
    local inside_door = {x = c.door.x - (c.door.x > c.x and 1 or c.door.x < c.x and -1 or 0),
                         y = c.door.y - (c.door.y > c.y and 1 or c.door.y < c.y and -1 or 0)}

    if c.stage == 'walls' then
        if n.walls_planned > 0 then return wait('walls', n.walls_planned, 'wall tile(s)') end
        -- the beds: the soil quarters (a quarter with rock, a tree or a building in it stays as it is)
        local beds, cells, paths = 0, {}, 0
        for _, b in ipairs(L.beds) do
            local x1, y1 = c.x + b.x, c.y + b.y
            if bed_ok(x1, y1, b.w, b.h, c.z) then
                local cell = {x = x1, y = y1, text = ('p(%dx%d)'):format(b.w, b.h)}
                local placed = apply('build', {cell}, c.z, 'a bed', dry_run)
                if placed then beds = beds + 1; if not dry_run then record(c, {cell}, c.z) end end
            end
        end
        -- the paths: block floors over soil (asked for); rock ground is a path already
        if c.paths then
            for _, p in ipairs(L.paths) do
                local x, y = c.x + p.x, c.y + p.y
                if free(x, y) and soil_at(x, y, c.z) then table.insert(cells, {x = x, y = y, text = 'Cf'}) end
            end
            local placed = apply('build', cells, c.z, 'the garden court\'s paths', dry_run)
            if placed then paths = placed; if not dry_run then record(c, cells, c.z) end end
        end
        if not dry_run then c.stage = 'beds'; c.stage_tick = now_tick(); save_court(c) end
        return out({stage = 'beds', beds = beds, paths = paths})
    end

    if c.stage == 'beds' then
        local over = (stage_days(c) or 0) >= COURT_WAIT_DAYS      -- (r9) the rest stays planned
        if n.planned > 0 and not over then return wait('beds', n.planned, 'bed(s) or path tile(s)') end
        local cells = {}
        local statues = math.min(#L.statues, math.max(0, math.tointeger(opts.statues) or 0), hall_free_items('STATUE'))
        for i, p in ipairs(L.statues) do
            local x, y = c.x + p.x, c.y + p.y
            if i <= statues and free(x, y) then table.insert(cells, {x = x, y = y, text = 's'}) end
        end
        for _, p in ipairs(L.seats) do
            local x, y = c.x + p.x, c.y + p.y
            if free(x, y) and not (x == inside_door.x and y == inside_door.y) then
                table.insert(cells, {x = x, y = y, text = 'c'})
            end
        end
        local placed, why = 0, nil
        if #cells > 0 then
            placed, why = apply('build', cells, c.z, 'the garden court\'s statues and seats', dry_run)
            if not placed then
                -- (no statue lying free after all, a chair short: the court goes on without them)
                placed, why = 0, nil
                cells = {}
            end
        end
        if not dry_run then
            c.stage = 'furnish'
            c.stage_tick = now_tick()      -- (r9)
            record(c, cells, c.z)
            save_court(c)
        end
        local st, se = 0, 0
        for _, cl in ipairs(cells) do if cl.text == 's' then st = st + 1 else se = se + 1 end end
        return out({stage = 'furnish', statues = st, seats = se})
    end

    if c.stage == 'furnish' then
        local over = (stage_days(c) or 0) >= COURT_WAIT_DAYS      -- (r9) the rest stays planned
        if n.planned > 0 and not over then return wait('furnish', n.planned, 'statue(s) or seat(s)') end
        -- (r9 c1) secured before it is a meeting place
        if not dry_run then c.stage = 'secure'; c.stage_tick = now_tick(); save_court(c) end
        return out({stage = 'secure'})
    end

    -- (r9 c1) the walls closed all round, the way in a door the AI locks
    if c.stage == 'secure' then
        if not dry_run and not c.stage_tick then c.stage_tick = now_tick(); save_court(c) end
        -- an older save's meeting area: off until the court is secured
        if c.zoned and not dry_run then
            local zn = court_zone(c)
            if zn then set_zone_on(zn, false) end
        end
        local sc = court_secure_scan(c)
        local function plain(why)
            if not dry_run then
                c.stage, c.plain, c.plain_why, c.stage_tick = 'plain', true, why, nil
                if court_door_state(c) == 'built' then court_lock_door(c, false) end
                save_court(c)
            end
            return out({stage = 'plain', plain = true, why = why})
        end
        if sc.way_in then return plain(sc.way_in) end
        if sc.gap then return plain(sc.gap) end
        if sc.secured then
            local zoned = c.zoned
            if not zoned then
                local q = c.r - 1
                local cell = {{x = c.x - q, y = c.y - q, text = ('m{name="The %s Garden Court"}(%dx%d)'):format(c.name, 2 * q + 1, 2 * q + 1)}}
                local good = qf_try('zone', cell, c.z, 0, 0, dry_run)
                if not good then
                    cell[1].text = ('m(%dx%d)'):format(2 * q + 1, 2 * q + 1)     -- (a name the game won't take: none)
                    good = qf_try('zone', cell, c.z, 0, 0, dry_run)
                end
                if not good then return out({ok = false, error = 'the game would not place the garden court\'s meeting area'}) end
                if not dry_run then record(c, cell, c.z); c.zoned = true end
            end
            if not dry_run then
                c.stage, c.secured, c.stage_tick = 'done', true, nil
                save_court(c)
            end
            -- (an older save's area stays off: the brain's danger watch switches it on)
            return out({stage = 'done', secured = true, zone = not zoned or nil, zone_kept = zoned or nil, name = c.name})
        end
        if #sc.trees > 0 then
            if not dry_run then for _, p in ipairs(sc.trees) do fell_tree(p.x, p.y, c.z) end end
            return wait('secure', #sc.trees, 'tree(s) to fell on its walls\' line')
        end
        if #sc.missing > 0 or sc.door_missing then
            if (c.secure_tries or 0) >= COURT_SECURE_TRIES then
                return plain(('its walls were put up %d times and still do not close it (no blocks or stone for them?)')
                    :format(c.secure_tries))
            end
            local cells = {}
            for _, p in ipairs(sc.missing) do table.insert(cells, {x = p.x, y = p.y, text = 'Cw'}) end
            if sc.door_missing then table.insert(cells, {x = c.door.x, y = c.door.y, text = 'd'}) end
            local placed, why = apply('build', cells, c.z, 'the garden court\'s walls', dry_run)
            if not placed then
                if not dry_run then
                    c.secure_refused = (c.secure_refused or 0) + 1
                    save_court(c)
                    if c.secure_refused >= COURT_SECURE_TRIES then
                        return plain(('the game refused its walls %d times (%s)'):format(c.secure_refused, tostring(why)))
                    end
                end
                return out({ok = false, error = why})
            end
            if not dry_run then
                c.secure_tries = (c.secure_tries or 0) + 1
                record(c, cells, c.z)
                save_court(c)
            end
            return out({stage = 'secure', walls = placed, door = sc.door_missing or nil})
        end
        -- walls (or the door) planned: built when the material comes, COURT_WAIT_DAYS at most
        if (stage_days(c) or 0) >= COURT_WAIT_DAYS then
            return plain(('%d wall or door piece(s) waited %d days unbuilt (no blocks or stone for them?)')
                :format(sc.planned, stage_days(c)))
        end
        return wait('secure', sc.planned, 'wall or door piece(s)')
    end
    return out({ok = false, rejected = true, error = 'the garden court is in an unknown stage: ' .. tostring(c.stage)})
end

-- (r9 c1) The meeting area switched on or off by the brain's danger watch
-- (planner_garden: off at once while danger is about, on again once it has
-- been gone garden_court_lift_ticks). opts: {on, lock}. Off: the zone made
-- inactive (idle dwarves stop gathering there); with lock (danger about) the
-- door locked too, but never with a citizen inside the court nor with a way
-- into the fort inside it (never sealed in). On: only a secured court; its
-- door unlocked.
function garden_court_meeting(dry_run, opts)
    opts = type(opts) == 'table' and opts or {}
    local on = opts.on == true
    local c = court_data()
    if not c then return {ok = false, rejected = true, error = 'there is no garden court'} end
    if on and (not c.secured or c.plain) then
        return {ok = false, rejected = true, error = 'the garden court is not secured: its meeting area stays off'}
    end
    local res = {ok = true, garden_court = true, on = on, x = c.x, y = c.y, elevation = ez(c.z),
                 dry_run = dry_run or nil}
    local zn = c.zoned and court_zone(c) or nil
    if zn then
        if not dry_run and not set_zone_on(zn, on) then
            return {ok = false, error = ('the game would not switch the garden court\'s meeting area %s'):format(on and 'on' or 'off')}
        end
        res.zone = true
    elseif c.zoned then
        res.zone_gone = true
    end
    local door = court_door_state(c) == 'built'
    local inside = court_citizens_inside(c)
    local way_in = court_way_in(c)
    local lock = door and not on and opts.lock == true and inside == 0 and not way_in
    if door and not dry_run then court_lock_door(c, lock) end
    res.locked, res.inside = lock, inside
    if not on and opts.lock == true and not lock then
        res.unlocked_why = not door and 'no door built' or inside > 0 and ('%d citizen(s) inside'):format(inside)
            or way_in
    end
    if not zn and not door then
        return {ok = false, rejected = true, error = 'the garden court has no meeting area or door to switch'}
    end
    if not dry_run then
        c.meeting_off = (not on) or nil
        save_court(c)
    end
    return res
end
