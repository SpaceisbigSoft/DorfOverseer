-- ai-builder-wells: wells: the spot under the fort, on the shore, over a cavern or at the
-- end of a gallery; the cavern shaft's gate and lid; place_well.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-wells'] = '0.105.43'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

---------------------------------------------------------------------------
-- Wells. A well stands over a hole with a straight drop to clean water at
-- least 3/7 deep (or any water over 7/7). The AI looks for a natural floor
-- inside the fort, on a busy level, with such a drop under it, channels that
-- tile and builds the well over the hole (buildingplan waits for a block, a
-- bucket, a rope or chain and a mechanism). It never opens the fort into a
-- cavern, and never over water that fills the space right under the floor
-- (it could be under pressure and flood up). See docs/building.md.
---------------------------------------------------------------------------

WELL_MAX_DROP = 30         -- levels the bucket may go down
WELL_SCAN_MARGIN = 20
WELL_SEARCH_SECONDS = 2
-- zones a well may stand in (and is welcome in); any other zone is left alone
WELL_ZONES = {DiningHall = true, MeetingHall = true}

-- Usable water straight down from (x, y, z)? Returns the drop in levels, or
-- nil and why not.
function water_below(x, y, z)
    for k = 1, WELL_MAX_DROP do
        local t = tile_info(x, y, z - k)
        if not t then return nil, 'no water below' end
        if t.feature then return nil, 'the water below is in a cavern' end
        if t.outside then return nil, 'the drop opens to the sky' end
        if t.liquid then
            if t.magma then return nil, 'magma below' end
            if t.stagnant or t.salt then return nil, 'the water below is stagnant or salt' end
            if k == 1 and t.depth >= 7 then
                return nil, 'water fills the space right under the floor (it may be under pressure)'
            end
            if t.depth >= 3 then return k end
            local u = tile_info(x, y, z - k - 1)
            if t.shape == 'EMPTY' and u and u.liquid and not u.magma and not u.stagnant and not u.salt
                    and u.depth >= 7 then
                return k + 1
            end
            return nil, 'the water below is too shallow'
        end
        if t.shape ~= 'EMPTY' then return nil, nil end    -- solid: the common case, not worth a word
    end
    return nil, 'no water within reach'
end

-- The best spot for a well: {x, y, z, drop, zone}, or nil, why and (13c)
-- timed_out when the search ran out of time.
function find_well_spot(reserved)
    local area = fort_scan_area(WELL_SCAN_MARGIN)
    if not area then return nil, 'no citizens' end
    local best, best_score, cut
    local why_not = {}
    local deadline = os.clock() + WELL_SEARCH_SECONDS
    for i = 1, math.min(FARM_SCAN_LEVELS, #area.levels) do
        local z = area.levels[i].z
        for y = area.y1, area.y2 do
            if os.clock() > deadline then cut = true break end
            for x = area.x1, area.x2 do
                local mat = floor_material(x, y, z)
                if mat and mat ~= 'CONSTRUCTION' then        -- built floors can't be channelled
                    local t = tile_info(x, y, z)
                    if t and not t.liquid and not t.feature and not t.outside and not t.building
                            and not t.designated and not inside_any(reserved, x, y, z)
                            and area.groups[walk_group(x, y, z)] and not building_at(x, y, z) then
                        local zones, ok_zone, liked = zone_types(x, y, z), true, false
                        for _, k in ipairs(zones) do
                            if WELL_ZONES[k] then liked = true else ok_zone = false end
                        end
                        if ok_zone then
                            local drop, why = water_below(x, y, z)
                            if drop then
                                -- in a dining or meeting hall first, then near the middle
                                -- of the fort, on the busiest level
                                local score = (liked and 0 or 1000) + (i - 1) * 50
                                    + math.abs(x - area.cx) + math.abs(y - area.cy)
                                if not best_score or score < best_score then
                                    best, best_score = {x = x, y = y, z = z, drop = drop, zone = liked}, score
                                end
                            elseif why then
                                why_not[why] = true
                            end
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    local reasons = {}
    for w in pairs(why_not) do table.insert(reasons, w) end
    table.sort(reasons)
    return nil, (cut and 'search cut short: ' or '') .. 'no open drop from a free floor inside the fort to clean water'
        .. (#reasons > 0 and (' (' .. table.concat(reasons, '; ') .. ')') or ''), cut
end

-- A well on the shore, when the fort has no water under it (its water is a
-- pond, brook or river on the surface, above the fort or beside it): a dry
-- floor tile on the bank whose tile below has water beside it, one level
-- down. Channelling it opens that tile below into a ramp the water flows
-- into (only that one tile: everything else around it on that level must be
-- rock or the water itself, so nothing else can flood), and the well stands
-- on the bank over it, the bucket going down one level. Fresh water first,
-- then the nearest; salt water never, stagnant only if there's nothing else
-- (it gives a bad thought, but a fort without water dies of thirst).
WELL_SHORE_RADIUS = 40

-- (0.105.3) Hammerstirred (2 Nov): the log said only "no pond within 40 tiles",
-- and the player couldn't tell how far the water was. The water survey's
-- nearest tile of each kind asked for, and how far it is from `from` (a list
-- of {x, y, z}: the entrances, or the dwarves), in words: "the nearest
-- surface pond is 77 tiles off (x59 y200 elevation 43)". "" when unknown.
local REACH_WORDS = {surface = 'surface pond', pool = 'underground pool', cavern = 'cavern water', river = 'river'}
function water_reach_words(kinds, from)
    local ok, w = pcall(function() return reqscript('ai-water').last() end)
    if not ok or type(w) ~= 'table' or #(from or {}) == 0 then return '' end
    local best
    for _, b in ipairs(w.bodies or {}) do
        local n = b.nearest
        if kinds[b.kind] and type(n) == 'table' and n.x and n.y and n.z then
            for _, f in ipairs(from) do
                local d = math.max(math.abs(n.x - f.x), math.abs(n.y - f.y))
                if not best or d < best.d then best = {d = d, n = n, kind = b.kind} end
            end
        end
    end
    if not best then return '' end
    return ('the nearest %s is %d tiles off (x%d y%d elevation %d)'):format(REACH_WORDS[best.kind] or best.kind,
        best.d, best.n.x, best.n.y, ez(best.n.z))
end

-- (0.105.3) Hammerstirred (2 Nov): the surface pond lay 51 tiles from the
-- gate, past the 40 looked at. Beyond WELL_SHORE_RADIUS the AI looks only
-- round the water survey's nearest surface water (WELL_SHORE_NEAR tiles
-- round it, so the scan stays small), and only if that is within `reach`
-- tiles of an entrance (the brain's well_shore_reach) and the dwarves can
-- walk to the bank (the same walk-group test as before).
WELL_SHORE_NEAR = 8
-- (0.105.38) how far a far bank may lie: the brain's water_far_reach
-- (SHORE_FAR_REACH, set per call), else the map's width
SHORE_FAR_REACH = nil
function shore_far_cap(w)
    local r = math.tointeger(tonumber(SHORE_FAR_REACH))
    if r and r >= 0 then return r end                 -- (0.105.38 review) 0: far banks off
    local m = type(w) == 'table' and w.map or nil
    return type(m) == 'table' and math.tointeger(tonumber(m.w)) or 192
end
WELL_SHORE_FAR_MAX = 3         -- (0.105.4 review) far ponds looked round at most (the nearest first)
function find_shore_well_spot(reserved, reach)
    local entrances = pasture_anchors()
    if #entrances == 0 then return nil, 'no surface entrance or staircase to look around' end
    reach = math.tointeger(tonumber(reach)) or WELL_SHORE_RADIUS
    local anchors = {}
    for _, a in ipairs(entrances) do table.insert(anchors, {x = a.x, y = a.y, z = a.z, r = WELL_SHORE_RADIUS}) end
    local function from_gate(x, y)
        local d
        for _, a in ipairs(entrances) do
            local k = math.max(math.abs(a.x - x), math.abs(a.y - y))
            if not d or k < d then d = k end
        end
        return d or 0
    end
    if reach > WELL_SHORE_RADIUS then
        local okw, w = pcall(function() return reqscript('ai-water').last() end)
        local far = {}
        for _, b in ipairs(okw and type(w) == 'table' and w.bodies or {}) do
            local n = b.nearest
            if (b.kind == 'surface' or b.kind == 'river') and type(n) == 'table' and n.x and n.y and n.z
                    and from_gate(n.x, n.y) > WELL_SHORE_RADIUS - WELL_SHORE_NEAR
                    and from_gate(n.x, n.y) <= reach then
                -- the bank is a level over the water (the anchor's z is the bank's level)
                table.insert(far, {x = n.x, y = n.y, z = n.z + 1, r = WELL_SHORE_NEAR, far = true,
                                   d = from_gate(n.x, n.y)})
            end
        end
        -- (0.105.4 review) the review: no cap on far ponds: the nearest 3 only
        table.sort(far, function(p, q) return p.d < q.d end)
        for i = 1, math.min(#far, WELL_SHORE_FAR_MAX) do table.insert(anchors, far[i]) end
        -- (0.105.38) the whole-map survey's fresh surface water beyond `reach`
        -- (up to the map's width, or the brain's water_far_reach), nearest
        -- first: a well there only where the dwarves can walk (the walk-group
        -- test below); further than any near bank, so a near one still wins
        local cap = shore_far_cap(okw and w or nil)
        local far2 = {}
        for _, b in ipairs(okw and type(w) == 'table' and type(w.waters) == 'table' and w.waters or {}) do
            local n = type(b) == 'table' and b.nearest or nil
            if (b.flow == 'flowing' or (b.flow == 'stagnant' and not b.underground)) and (tonumber(b.salt_share) or 0) == 0
                    and type(n) == 'table' and n.x and n.y and n.z then
                local d = from_gate(n.x, n.y)
                if d > reach and d <= cap then
                    table.insert(far2, {x = n.x, y = n.y, z = n.z + 1, r = WELL_SHORE_NEAR, far = true, d = d})
                end
            end
        end
        table.sort(far2, function(p, q) return p.d < q.d end)
        for i = 1, math.min(#far2, WELL_SHORE_FAR_MAX) do table.insert(anchors, far2[i]) end
    end
    local groups = {}
    for _, p in ipairs(citizen_positions()) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
    end
    local function rock(t) return t and t.shape == 'WALL' and not t.aquifer and not t.feature end
    local best, best_score, why, cut
    local deadline = os.clock() + WELL_SEARCH_SECONDS
    local seen = {}
    -- (0.105.4 review) one deadline for the whole search, far ponds included:
    -- the near scan has 2/3 of it, the far ponds what's left
    local near_deadline = os.clock() + WELL_SEARCH_SECONDS * 2 / 3
    for _, a in ipairs(anchors) do
        if os.clock() > deadline then cut = true break end
        local stop = a.far and deadline or near_deadline
        for z = a.z - 3, a.z + 3 do
            for y = a.y - a.r, a.y + a.r do
                if os.clock() > stop then cut = true break end
                for x = a.x - a.r, a.x + a.r do
                    local k = x .. ',' .. y .. ',' .. z
                    if not seen[k] then
                        seen[k] = true
                        local t = tile_info(x, y, z)
                        if t and t.shape == 'FLOOR' and t.material ~= 'CONSTRUCTION' and not t.liquid
                                and not t.feature and not t.building and not t.designated
                                and not inside_any(reserved, x, y, z) and groups[walk_group(x, y, z)] then
                            local under = tile_info(x, y, z - 1)
                            -- water beside the tile below (that level is the water's)
                            local water, ok_around, stagnant = nil, rock(under), false
                            if ok_around then
                                for dy = -2, 2 do
                                    for dx = -2, 2 do
                                        if dx ~= 0 or dy ~= 0 then
                                            local n = tile_info(x + dx, y + dy, z - 1)
                                            if n and n.liquid and not n.magma and not n.feature then
                                                if n.salt then ok_around = false end
                                                if math.abs(dx) <= 1 and math.abs(dy) <= 1 and n.depth >= 3 then
                                                    water = water or n
                                                    stagnant = stagnant or n.stagnant
                                                end
                                            elseif not rock(n) then
                                                ok_around = false        -- open ground or the fort down there
                                            end
                                        end
                                    end
                                end
                            end
                            -- (0.100, review) river or brook water can be under
                            -- pressure and rise up the channel: only outside,
                            -- where it runs off, never under the fort's roof
                            local flowing = water and (water.material == 'RIVER' or water.material == 'BROOK')
                            if water and ok_around and flowing and not t.outside then
                                why = 'the only river water near the entrances is under a roof (it could rise up the well)'
                            elseif water and ok_around then
                                -- a dry floor beside it for the builder to stand on
                                -- (quickfort wants a floor beside the well, not just at a corner)
                                local stand = false
                                for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
                                    local n = tile_info(x + d[1], y + d[2], z)
                                    if n and n.shape == 'FLOOR' and not n.liquid then stand = true end
                                end
                                if stand then
                                    -- (0.105.3) far from the gate counts by its distance to the gate
                                    local score = (stagnant and 1000 or 0)
                                        + (a.far and 2 * from_gate(x, y) or (math.abs(x - a.x) + math.abs(y - a.y)))
                                        + 5 * math.abs(z - a.z)
                                    if not best_score or score < best_score then
                                        best, best_score = {x = x, y = y, z = z, drop = 1, shore = true,
                                                            stagnant = stagnant or nil,
                                                            from_gate = a.far and from_gate(x, y) or nil}, score
                                    end
                                end
                            elseif water then
                                why = 'the only water near the surface entrances has open ground or the fort beside it, one level down (a channel there could flood it)'
                            end
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    local cut_words = cut and 'search cut short: ' or ''
    if why then return nil, cut_words .. why, cut end
    -- (0.105.3) how far the nearest surface water really is
    local okr, far = pcall(water_reach_words, {surface = true, river = true}, entrances)
    return nil, cut_words .. ('no pond, brook or river within %d tiles of the surface entrances to put a well beside'):format(
        math.max(reach, WELL_SHORE_RADIUS))
        .. (okr and far ~= '' and (' (' .. far .. ')') or ''), cut
end

-- A cavern well (only when the AI decides it must: brain/planner.py
-- _well_rule). A floor inside the fort with solid natural rock straight
-- under it, then a cavern's open air, then fresh water at least 3/7 deep:
-- a one-tile shaft is channelled down through the rock, one level after the
-- other, and the well stands over it. The shaft's walls touch nothing but
-- rock (no aquifer, water or open space beside them), so nothing can flood
-- in, and walkers can't climb out of the cavern up a one-tile drop.
-- (The rock's layout is read even where it's undiscovered, as for every
-- other safety check of the AI.)
CAVERN_WELL_MIN_DEPTH = 3
-- (0.105.4 review) the review: the cavern search (4 s) then the gallery (4 s),
-- CPU time on DF's main thread, uncached: the game froze up to 8 s a try.
-- Now 1 s each and 1.5 s in all, and a "no spot" answer is kept until the
-- next water survey or CAVERN_NO_SPOT_DAYS, whichever is first.
CAVERN_SEARCH_SECONDS = 1
CAVERN_TOTAL_SECONDS = 1.5
CAVERN_NO_SPOT_DAYS = 28
CAVERN_NO_SPOT = CAVERN_NO_SPOT or nil

function solid_rock(t)
    return t ~= nil and t.shape == 'WALL' and not t.aquifer and not t.liquid and not t.feature and not t.warm
        and t.material ~= 'CONSTRUCTION' and not is_tree(t)
end

-- (0.104.13) The shaft's stairs. A miner channels a tile standing beside it
-- on the same level, so a one-tile shaft can't be dug past its first level
-- or two (Enxah's crept to 2 of 24 tiles in six game years while patients
-- died of thirst every winter). A stair column right beside the shaft goes
-- down with it: a down stair in the hall's floor, up/down stairs through the
-- rock, an up stair at the bottom, and each level of the shaft is channelled
-- from the stair beside it. The column keeps to the same solid rock as the
-- shaft (nothing but rock and the shaft round it), so it opens into nothing.
-- {x, y} of the column's top, or nil, why.
function shaft_stairs_side(x, y, z, rock, reserved, group)
    for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
        local sx, sy = x + d[1], y + d[2]
        local t = tile_info(sx, sy, z)
        local mat = floor_material(sx, sy, z)
        local ok = t ~= nil and mat ~= nil and mat ~= 'CONSTRUCTION' and t.shape == 'FLOOR' and not t.liquid
            and not t.feature and not t.outside and not t.building and not t.designated
            and not inside_any(reserved or {}, sx, sy, z) and not building_at(sx, sy, z)
            and (group == nil or walk_group(sx, sy, z) == group)
        if ok then
            for _, k in ipairs(zone_types(sx, sy, z)) do
                if not WELL_ZONES[k] then ok = false end
            end
        end
        for k = 1, ok and rock or 0 do
            local c = tile_info(sx, sy, z - k)
            if not solid_rock(c) then ok = false break end
            for _, e in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                local nx, ny = sx + e[1], sy + e[2]
                if not (nx == x and ny == y) then
                    local n = tile_info(nx, ny, z - k)
                    if not n or n.liquid or n.aquifer or n.shape ~= 'WALL' then ok = false break end
                end
            end
            if not ok then break end
        end
        if ok then return {x = sx, y = sy} end
    end
    return nil, 'no room beside the shaft for the stairs it is dug from'
end

-- The stair column's cells, top to bottom: {x, y, z, key}.
function shaft_stair_cells(side, z, rock)
    local cells = {{x = side.x, y = side.y, z = z, key = 'j'}}
    for k = 1, rock do
        table.insert(cells, {x = side.x, y = side.y, z = z - k, key = (k == rock) and 'u' or 'i'})
    end
    return cells
end

STAIR_SHAPES = {j = 'STAIR_DOWN', i = 'STAIR_UPDOWN', u = 'STAIR_UP'}

-- (0.105.24) A floor beside the well. C and F (3 Nov): both cavern wells
-- came out at the end of a gallery (0.105.3) and quickfort refused the Well
-- over the dug shaft ("the game would not place the well over the hole at
-- x131 y129 z24", the project cancelled for good). Quickfort's test for a
-- well ('l'; DFHack's quickfort build.lua, is_tile_empty_and_floor_adjacent
-- as we know it, not yet seen failing live): the tile open space or a ramp
-- top, and a floor beside it on one of its four sides (a floor-shaped tile
-- with no building, not hidden). The shore wells had learned the same
-- (find_shore_well_spot), and the refusal now says what the game showed
-- (well_diagnosis) in case it is something else. A gallery's shaft top
-- has its stair column's down stair on one side (a stair isn't a floor) and
-- solid rock on the other three, so no well could ever go on it; a hall's
-- shaft has hall floor round it. Now the shaft top gets a floor beside it: a
-- "landing", one more tile dug to floor on the fort level next to it (rock
-- with rock under it and a dry cap, nothing but rock or the fort's dry space
-- round it), dug with the gallery.
WELL_FLOOR_SHAPES = {FLOOR = true, BOULDER = true, PEBBLES = true, TWIG = true, SAPLING = true, SHRUB = true}
local W_DIR4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
local W_DIR8 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}

-- a side of (x, y, z) quickfort takes as the well's floor: {x, y} or nil
-- (`floors`: "x,y" -> true for tiles that will be dug to floor, counted too;
-- `except`: {x, y}, a side that won't stay a floor: the shaft's stair)
function well_floor_beside(x, y, z, floors, except)
    for _, d in ipairs(W_DIR4) do
        local nx, ny = x + d[1], y + d[2]
        if except and nx == except.x and ny == except.y then
            -- the stair column's top: a down stair, never the well's floor
        elseif floors and floors[nx .. ',' .. ny] then return {x = nx, y = ny} end
        local n = not (except and nx == except.x and ny == except.y) and tile_info(nx, ny, z) or nil
        if n and WELL_FLOOR_SHAPES[n.shape] and not n.building and not n.hidden then      -- (occupancy, as quickfort)
            return {x = nx, y = ny}
        end
    end
    return nil
end

-- The landing for a shaft top at (x, y, z) whose stair column's top is
-- `stair` ({x, y}): a side of the shaft (not the stair) that can be dug to a
-- floor safely, and a miner reaches (next to the stair, a gallery tile or a
-- walkable floor, diagonals too). `floors` as above. {x, y} or nil, why.
function well_landing(x, y, z, stair, floors)
    floors = floors or {}
    local best, why = nil, 'no rock beside the shaft to dig a floor in for the well'
    for _, d in ipairs(W_DIR4) do
        local lx, ly = x + d[1], y + d[2]
        if not (stair and lx == stair.x and ly == stair.y) and not floors[lx .. ',' .. ly] then
            local t, under, up = tile_info(lx, ly, z), tile_info(lx, ly, z - 1), tile_info(lx, ly, z + 1)
            local ok = solid_rock(t) and not t.designated and not t.building and solid_rock(under)
                and up ~= nil and not up.liquid and not up.aquifer and (up.shape == 'WALL' or up.shape == 'FLOOR')
            local reach = false
            for _, e in ipairs(ok and W_DIR8 or {}) do
                local nx, ny = lx + e[1], ly + e[2]
                if not (nx == x and ny == y) then
                    local n = tile_info(nx, ny, z)
                    if not n or n.liquid or n.aquifer or n.outside or n.feature then ok = false break end
                    if (stair and nx == stair.x and ny == stair.y) or floors[nx .. ',' .. ny]
                            or (n.shape == 'FLOOR' and walk_group(nx, ny, z) ~= 0) then
                        reach = true
                    end
                end
            end
            if ok and not reach then why = 'no floor beside the shaft a miner could reach to dig' end
            if ok and reach then
                -- next to the stair first (the well's builder steps off it)
                local by_stair = stair and math.max(math.abs(lx - stair.x), math.abs(ly - stair.y)) == 1
                if not best or (by_stair and not best.by_stair) then
                    best = {x = lx, y = ly, by_stair = by_stair or nil}
                end
            end
        end
    end
    if best then best.by_stair = nil return best end
    return nil, why
end

-- (0.105.24) What the game shows at a well spot, for the next live look at a
-- refusal: the tile and the two below (DF's tiletype names), its four sides,
-- any building on it. {levels = {...}, beside = {...}, text}
local function tiletype_name(x, y, z)
    local ok, n = pcall(function() return df.tiletype[dfhack.maps.getTileType(x, y, z)] end)
    if ok and n then return tostring(n) end
    local t = tile_info(x, y, z)
    return t and t.shape or 'off the map'
end

function well_diagnosis(x, y, z)
    local out, words = {x = x, y = y, elevation = ez(z), levels = {}, beside = {}}, {}
    for k = 0, 2 do
        local t = tile_info(x, y, z - k)
        local l = {elevation = ez(z - k), tiletype = tiletype_name(x, y, z - k),
                   building = t and t.building or nil, hidden = t and t.hidden or nil,
                   designated = t and t.designated or nil}
        table.insert(out.levels, l)
        table.insert(words, ('z%d %s%s'):format(l.elevation, l.tiletype, l.building and ' (a building)' or ''))
    end
    local side = {}
    for _, d in ipairs(W_DIR4) do
        local nx, ny = x + d[1], y + d[2]
        local t = tile_info(nx, ny, z)
        local b = (t and t.building) or building_at(nx, ny, z) or nil
        table.insert(out.beside, {x = nx, y = ny, tiletype = tiletype_name(nx, ny, z), building = b or nil})
        table.insert(side, tiletype_name(nx, ny, z) .. (b and ' (a building)' or ''))
    end
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if b then out.building_type = tostring(df.building_type[b:getType()]) end
    end)
    out.floor_beside = well_floor_beside(x, y, z) ~= nil
    out.text = 'tiles: ' .. table.concat(words, ', ') .. '; beside: ' .. table.concat(side, ', ')
        .. (out.building_type and ('; on it: ' .. out.building_type) or '')
    return out
end

function cavern_below(x, y, z)
    local rock = 0
    for k = 1, WELL_MAX_DROP do
        local t = tile_info(x, y, z - k)
        if not t then return nil, 'no cavern water within reach' end
        if rock == k - 1 and not t.feature then
            if not solid_rock(t) then return nil, 'not solid rock all the way down to the cavern' end
            for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                local n = tile_info(x + d[1], y + d[2], z - k)
                if not n or n.liquid or n.aquifer or n.shape ~= 'WALL' then
                    return nil, 'the shaft would pass open space, water or an aquifer'
                end
            end
            rock = rock + 1
        elseif t.feature then
            if rock == 0 then return nil, 'the floor is the cavern\'s ceiling' end
            if t.liquid then
                if t.magma then return nil, 'magma below' end
                if t.salt then return nil, 'the cavern water is salt' end
                if k == rock + 1 and t.depth >= 7 then
                    return nil, 'the cavern water fills the space right under the rock (it may be under pressure)'
                end
                -- (0.105.4 review) the cavern's air right under the rock unseen: the
                -- shaft would be the first way into it (forgotten beasts come after)
                local air = tile_info(x, y, z - rock - 1)
                if t.depth >= CAVERN_WELL_MIN_DEPTH then
                    return {drop = k, rock = rock, stagnant = t.stagnant, hidden = (air and air.hidden) or t.hidden or nil}
                end
                return nil, 'the cavern water there is too shallow'
            end
            if t.shape ~= 'EMPTY' then return nil, 'cavern floor, not water, below' end
        else
            return nil, 'not a cavern below'
        end
    end
    return nil, 'no cavern water within reach'
end

function find_cavern_well_spot(reserved)
    local area = fort_scan_area(WELL_SCAN_MARGIN)
    if not area then return nil, 'no citizens' end
    local best, best_score, why_not = nil, nil, {}
    -- (0.105.4 review) 1 s (was 4): the search runs on DF's own thread, the game stands still meanwhile
    -- (13c) out of time: nil, why (with 'the search ran out of time'), true. The
    -- words keep their start: the brain reads "no floor inside the fort over
    -- cavern water" (planner_building's gallery retry)
    local deadline = os.clock() + CAVERN_SEARCH_SECONDS
    for i = 1, math.min(FARM_SCAN_LEVELS, #area.levels) do
        local z = area.levels[i].z
        for y = area.y1, area.y2 do
            if os.clock() > deadline then why_not['the search ran out of time'] = true break end   -- (0.105.4 review)
            for x = area.x1, area.x2 do
                local mat = floor_material(x, y, z)
                if mat and mat ~= 'CONSTRUCTION' then
                    local t = tile_info(x, y, z)
                    if t and not t.liquid and not t.feature and not t.outside and not t.building
                            and not t.designated and not inside_any(reserved, x, y, z)
                            and area.groups[walk_group(x, y, z)] and not building_at(x, y, z) then
                        local zones, ok_zone, liked = zone_types(x, y, z), true, false
                        for _, k in ipairs(zones) do
                            if WELL_ZONES[k] then liked = true else ok_zone = false end
                        end
                        if ok_zone then
                            local c, why = cavern_below(x, y, z)
                            local side
                            if c then
                                side, why = shaft_stairs_side(x, y, z, c.rock, reserved, walk_group(x, y, z))
                                if not side then c = nil end
                            end
                            if c then
                                -- fresh water, a short shaft, a hall, near the middle
                                local score = (c.stagnant and 2000 or 0) + c.rock * 40 + (liked and 0 or 300)
                                    + (i - 1) * 50 + math.abs(x - area.cx) + math.abs(y - area.cy)
                                if not best_score or score < best_score then
                                    best, best_score = {x = x, y = y, z = z, drop = c.drop, rock = c.rock,
                                                        zone = liked, cavern = true, stagnant = c.stagnant,
                                                        side = side, hidden = c.hidden}, score
                                end
                            elseif why then
                                why_not[why] = true
                            end
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    local reasons = {}
    for w in pairs(why_not) do table.insert(reasons, w) end
    table.sort(reasons)
    local cut = why_not['the search ran out of time'] == true
    return nil, 'no floor inside the fort over cavern water with solid rock between'
        .. (#reasons > 0 and (' (' .. table.concat(reasons, '; ') .. ')') or ''), cut
end

-- --- the cavern well at the end of a gallery (0.105.3) ------------------------------
--
-- (0.105.3) Hammerstirred (2 Nov): neither fort of the overnight pair had a
-- well, B with 4 injured waiting for water. The cavern lake (12,412 tiles,
-- z114-136) lies under the map beside the fort, not under any fort floor:
-- every floor's column met cavern floor, not water ("cavern floor, not water,
-- below; no cavern water within reach"). So the fort reaches out to it: a
-- one-tile gallery dug through solid rock on a fort level, from a fort floor
-- to a column over the lake, and there the same cavern well as before (the
-- shaft channelled down through rock, the stair column beside it, the shaft
-- gate on a lever). Safety as for the shaft: every gallery tile solid rock
-- (no aquifer, water, cavern, warm stone), its 8 neighbours rock (only the
-- first tile may touch the fort's own dry floors), rock under it, a wall or
-- floor over it (no water, no aquifer); the shaft's column and the stair
-- column are checked by cavern_below and the stair test as before. Nothing
-- moves water: the bucket goes down to the lake, which never rises (a lake
-- that fills the space right under the rock is refused, as before).
-- The columns tried are those round the water survey's nearest cavern water
-- (or the points the brain passes), so the search stays small.
WELL_GALLERY_MAX = 80          -- gallery tiles at most (the brain's cavern_well_gallery; 0.105.4: 80)
WELL_GALLERY_WINDOW = 8        -- columns tried this far round each point of cavern water
WELL_GALLERY_SECONDS = 1       -- (0.105.4 review) was 4

local G_DIR4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
local G_DIR8 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}

-- The points of cavern water to dig toward: the brain's, else the last survey's nearest.
local function gallery_targets(toward)
    local out = {}
    for _, p in ipairs(type(toward) == 'table' and toward or {}) do
        local x, y, z = math.tointeger(p.x), math.tointeger(p.y), math.tointeger(p.z)
        if x and y and z then table.insert(out, {x = x, y = y, z = z}) end
    end
    if #out == 0 then
        local ok, w = pcall(function() return reqscript('ai-water').last() end)
        for _, b in ipairs(ok and type(w) == 'table' and w.bodies or {}) do
            local n = b.nearest
            if b.kind == 'cavern' and type(n) == 'table' and n.x and n.y and n.z then
                table.insert(out, {x = n.x, y = n.y, z = n.z})
            end
        end
    end
    return out
end

-- {x, y, z, drop, rock, side, gallery = {{x, y}...} (fort end first, the
-- stair tile beside the shaft not in it), cavern = true} or nil, why.
function find_gallery_well_spot(reserved, opts)
    opts = opts or {}
    local max = math.tointeger(tonumber(opts.max)) or WELL_GALLERY_MAX
    if max < 1 then return nil, 'galleries are switched off' end
    local targets = gallery_targets(opts.toward)
    if #targets == 0 then return nil, 'the water survey knows no cavern water to dig a gallery toward' end
    local area = fort_scan_area(0)
    if not area then return nil, 'no citizens' end
    local cache = {}
    local function ti(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = tile_info(x, y, z) or false; cache[k] = v end
        return v or nil
    end
    local function rock(x, y, z) return solid_rock(ti(x, y, z)) end
    -- a tile the gallery may be dug through: rock, rock under it, a cap over it
    local function diggable(x, y, z)
        local t = ti(x, y, z)
        if not solid_rock(t) or t.designated or t.building or inside_any(reserved, x, y, z) then return false end
        local up = ti(x, y, z + 1)
        if not up or up.liquid or up.aquifer or (up.shape ~= 'WALL' and up.shape ~= 'FLOOR') then return false end
        return rock(x, y, z - 1)
    end
    local function ring_rock(x, y, z, allow)
        for _, e in ipairs(G_DIR8) do
            local nx, ny = x + e[1], y + e[2]
            if not rock(nx, ny, z) and not (allow and allow(nx, ny)) then return false end
        end
        return true
    end
    local function welcome(x, y, z)
        for _, k in ipairs(zone_types(x, y, z)) do if not WELL_ZONES[k] then return false end end
        return true
    end
    -- the fort's floor the gallery starts from
    local function fort_floor(x, y, z)
        local t = ti(x, y, z)
        return t and t.shape == 'FLOOR' and not t.liquid and not t.outside and not t.feature
            and area.groups[walk_group(x, y, z)] and not building_at(x, y, z) and welcome(x, y, z)
    end
    -- the first tile's other neighbours may be the fort's own dry space (no zone but a hall)
    local function dry_inside(x, y, z)
        local t = ti(x, y, z)
        return t and t.shape ~= 'WALL' and not t.liquid and not t.aquifer and not t.outside and not t.feature
            and welcome(x, y, z)
    end
    -- how far a column is from the dwarves' box (the walk the gallery must make, at least)
    local bx1, by1, bx2, by2 = math.huge, math.huge, -math.huge, -math.huge
    local zlo, zhi = math.huge, -math.huge
    for _, p in ipairs(citizen_positions()) do
        bx1, by1 = math.min(bx1, p.x), math.min(by1, p.y)
        bx2, by2 = math.max(bx2, p.x), math.max(by2, p.y)
    end
    for _, l in ipairs(area.levels) do zlo, zhi = math.min(zlo, l.z), math.max(zhi, l.z) end
    local function away(x, y) return math.max(0, bx1 - x, x - bx2, by1 - y, y - by2) end
    local deadline = os.clock() + math.min(WELL_GALLERY_SECONDS, opts.seconds or WELL_GALLERY_SECONDS)
    local why_not, nearest_away, best, no_way = {}, nil, nil, {}
    local W, H = map_size()
    for _, tg in ipairs(targets) do
        -- the fort levels a well could stand on over this water (lowest first: the shortest shaft)
        for z = math.max(zlo, tg.z + 2), math.min(zhi, tg.z + WELL_MAX_DROP) do
            if os.clock() > deadline then why_not['the search ran out of time'] = true break end   -- (0.105.4 review)
            -- the shaft columns round the water, each with its stair tile(s) beside it
            local sources = {}
            for y = math.max(1, tg.y - WELL_GALLERY_WINDOW), math.min(H - 2, tg.y + WELL_GALLERY_WINDOW) do
                for x = math.max(1, tg.x - WELL_GALLERY_WINDOW), math.min(W - 2, tg.x + WELL_GALLERY_WINDOW) do
                    local a = away(x, y)
                    -- (cheap first: cavern water in this column near the survey's level)
                    local wet = false
                    for zz = tg.z - 2, tg.z + 2 do
                        local wt = ti(x, y, zz)
                        if wt and wt.liquid and wt.feature then wet = true break end
                    end
                    if wet and a <= max + 1 and diggable(x, y, z) and ring_rock(x, y, z) then
                        local c, why = cavern_below(x, y, z)
                        if c then
                            nearest_away = math.min(nearest_away or a, a)
                            for _, d in ipairs(G_DIR4) do
                                local sx, sy = x + d[1], y + d[2]
                                local ok = diggable(sx, sy, z)
                                for k = 1, ok and c.rock or 0 do
                                    if not rock(sx, sy, z - k) then ok = false break end
                                    for _, e in ipairs(G_DIR8) do
                                        local nx, ny = sx + e[1], sy + e[2]
                                        local n = ti(nx, ny, z - k)
                                        if not (nx == x and ny == y) and (not n or n.liquid or n.aquifer or n.shape ~= 'WALL') then
                                            ok = false break
                                        end
                                    end
                                    if not ok then break end
                                end
                                if ok then
                                    table.insert(sources, {x = sx, y = sy, shaft = {x = x, y = y}, c = c})
                                else
                                    why_not['no room beside the shaft for its stairs'] = true
                                end
                            end
                        elseif why then
                            why_not[why] = true
                        end
                    elseif wet and a > max + 1 then
                        nearest_away = math.min(nearest_away or a, a)
                    end
                end
            end
            -- one search from every stair tile at once back to the fort: the
            -- shortest gallery wins. It never passes through its own shaft.
            local prev, queue, head = {}, {}, 1
            for i, s in ipairs(sources) do
                local k = s.x .. ',' .. s.y
                if prev[k] == nil then prev[k] = false; table.insert(queue, {s.x, s.y, 1, i}) end
            end
            local found
            while head <= #queue and not found do
                if os.clock() > deadline then why_not['the search ran out of time'] = true break end
                local x, y, n, i = table.unpack(queue[head])
                head = head + 1
                local s = sources[i]
                local function own_shaft(nx, ny) return nx == s.shaft.x and ny == s.shaft.y end
                local start
                for _, d in ipairs(G_DIR4) do
                    if not start and fort_floor(x + d[1], y + d[2], z) then start = {x = x + d[1], y = y + d[2]} end
                end
                if start then
                    if ring_rock(x, y, z, function(nx, ny) return own_shaft(nx, ny) or dry_inside(nx, ny, z) end) then
                        found = {x = x, y = y, n = n, i = i, from = start}
                    else
                        why_not['the gallery would open beside a room or open ground'] = true
                    end
                elseif n < max + 1 and ring_rock(x, y, z) then
                    for _, d in ipairs(G_DIR4) do
                        local nx, ny = x + d[1], y + d[2]
                        local k = nx .. ',' .. ny
                        if prev[k] == nil and not own_shaft(nx, ny) then
                            if diggable(nx, ny, z) then
                                prev[k] = {x, y}
                                table.insert(queue, {nx, ny, n + 1, i})
                            end
                        end
                    end
                end
            end
            if #sources > 0 and not found then table.insert(no_way, ez(z)) end
            if found then
                local s = sources[found.i]
                -- the gallery, fort end first; the last tile walked (the stair tile) left out
                local path, px, py = {}, found.x, found.y
                while true do
                    local pr = prev[px .. ',' .. py]
                    if not pr then break end
                    table.insert(path, {x = px, y = py})
                    px, py = pr[1], pr[2]
                end
                local score = #path * 3 + s.c.rock + (s.c.stagnant and 200 or 0)
                if not best or score < best.score then
                    best = {x = s.shaft.x, y = s.shaft.y, z = z, drop = s.c.drop, rock = s.c.rock, cavern = true,
                            stagnant = s.c.stagnant, side = {x = s.x, y = s.y}, gallery = path, from = found.from,
                            hidden = s.c.hidden,
                            zone = false, score = score}
                end
                break        -- the lowest fort level that reaches it: the shortest shaft
            end
        end
    end
    if best then return best end
    if #no_way > 0 then
        table.sort(no_way)
        why_not[('no way of at most %d tiles through solid rock (no aquifer, water or open space beside it) from a fort floor at elevation %s')
            :format(max, no_way[1] == no_way[#no_way] and tostring(no_way[1]) or (no_way[1] .. '-' .. no_way[#no_way]))] = true
    end
    local reasons = {}
    for w in pairs(why_not) do table.insert(reasons, w) end
    table.sort(reasons)
    local tg = targets[1]
    local head_ = ('no gallery to the cavern water at x%d y%d elevation %d'):format(tg.x, tg.y, ez(tg.z))
    if tg.z + 2 > zhi or tg.z + WELL_MAX_DROP < zlo then
        head_ = head_ .. (' (the fort\'s levels, elevations %d-%d, are not 2-%d levels above it)'):format(ez(zlo), ez(zhi), WELL_MAX_DROP)
    elseif nearest_away and nearest_away > max then
        head_ = head_ .. (' (its nearest column is %d tiles from the dwarves; a gallery reaches %d)'):format(nearest_away, max)
    end
    local cut = why_not['the search ran out of time'] == true
    return nil, head_ .. (#reasons > 0 and (': ' .. table.concat(reasons, '; ')) or ''), cut
end

-- Every cell designated in the dry run, then for real (cells in map coordinates).
function designate(cells, z, mode)
    return (qf_try(mode, cells, z, 0, 0, false, #cells, true))
end

-- (0.104.151-152) A cavern well's two ways in from the cavern, closed.
-- The well is a hole (the wiki: no obstruction; swimmers path in through
-- wells), and its shaft is dug from a stair column beside it (0.104.13) that
-- runs down beside the shaft at every level. The one tile that opens into the
-- cavern is the shaft's lowest (its floor channelled away over the cavern's
-- air; the column's bottom step is an up stair, a floor under it). So:
--   the shaft gate: a hatch on that lowest shaft tile, on a lever beside the
--     well. A shut hatch stops the bucket, so it is opened once linked and
--     shut only while a danger is near (DFHack's lever --instant: no dwarf
--     runs to it), then opened again. Built from the column's bottom step.
--     The lever first; the hatch only once the lever stands and 2 mechanisms
--     are free for the link, so the well is never left blocked waiting.
--   the stair lid: only when the game won't build the gate, a hatch over the
--     column's top step, locked (DFHack forbids it); unlocked again while
--     dwarves must go down to build or relink a gate.
-- Kept in the project (`shaft_gate` = {lever = {x, y, z}, lever_id,
-- hatch_id, link_fails, impossible}). The review's points are marked "rv".
local STAIR_DOWN_SHAPE = {STAIR_DOWN = true, STAIR_UPDOWN = true}
SHAFT_LINK_FAILS_MAX = 3

local function shaft_bottom(p)
    local low
    for _, z in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
        if not low or z < low then low = z end
    end
    return low or (p.z - 1)
end

local function hatch_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b or b:getType() ~= df.building_type.Hatch then return nil end
    local closed = true
    pcall(function() closed = b.door_flags.closed end)
    local forbidden = false
    pcall(function() forbidden = b.door_flags.forbidden end)
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage(), closed = closed, forbidden = forbidden, b = b}
end

-- rv 14: a lever, not any trap
local function lever_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b or b:getType() ~= df.building_type.Trap then return nil end
    local okl, lever = pcall(function() return b.trap_type == df.trap_type.Lever end)
    if okl and not lever then return nil end
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage()}
end

local function free_floor(x, y, z, group)
    local t = tile_info(x, y, z)
    local g = walk_group(x, y, z)
    return t and t.shape == 'FLOOR' and not t.building and not t.designated and not t.liquid
        and not building_at(x, y, z) and g ~= 0 and (group == nil or g == group)
end

-- rv 12: outside the well's 3x3 (its furnishing would wait for the lever)
local function shaft_lever_spot(p)
    local a = anchor_of(p)
    local top = type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] or nil
    for _, r in ipairs({2, 3}) do
        for dy = -r, r do
            for dx = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = a.x + dx, a.y + dy
                    -- rv2 5: reachable from the stairs (the same walk group as their top)
                    if not (top and x == top.x and y == top.y)
                            and free_floor(x, y, p.z, top and walk_group(top.x, top.y, top.z) or nil) then
                        return {x = x, y = y, z = p.z}
                    end
                end
            end
        end
    end
end

local function job_of(building_id, jt)
    local ok, j = pcall(function()
        local b = df.building.find(building_id)
        for _, job in ipairs(b and b.jobs or {}) do
            if job.job_type == jt then return job end
        end
    end)
    return ok and j or nil
end

function shaft_gate_state(p)
    local g = p.shaft_gate or {}
    local a = anchor_of(p)
    local h = hatch_at(a.x, a.y, shaft_bottom(p))
    local lv = g.lever and lever_at(g.lever.x, g.lever.y, g.lever.z or p.z) or nil
    if g.impossible then return {state = 'none_possible', hatch = h, lever = lv} end
    if not g.lever then return {state = h and 'stray' or 'none', hatch = h} end
    if not lv then return {state = 'no_lever', hatch = h} end
    if not lv.built then return {state = 'building', hatch = h, lever = lv} end
    if not h then return {state = 'no_hatch', lever = lv} end
    if not h.built then return {state = 'building', hatch = h, lever = lv} end
    local linked = false
    local okl, links = pcall(function() return reqscript('ai-gates').lever_links() end)
    for _, lid in ipairs(okl and links[h.id] or {}) do if lid == lv.id then linked = true end end
    if not linked then
        return {state = job_of(lv.id, df.job_type.LinkBuildingToTrigger) and 'linking' or 'unlinked', hatch = h, lever = lv}
    end
    if job_of(lv.id, df.job_type.PullLever) then return {state = 'pulling', hatch = h, lever = lv} end
    return {state = h.closed and 'closed' or 'open', hatch = h, lever = lv}
end

local function free_mechanism_count()
    -- (0.104.156) by the link's own test when there is one (none where no dwarf can walk)
    local okc, c = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
    if okc and type(c) == 'table' and type(c.usable) == 'number' then return c.usable end
    local ok, n = pcall(function() return (count_items('TRAPPARTS')) end)
    return ok and n or 0
end

-- (0.105.4 review) the shaft's lowest level dug open (the hatch can go on it)
function shaft_bottom_open(p)
    local a = anchor_of(p)
    local t = tile_info(a.x, a.y, shaft_bottom(p))
    return t ~= nil and t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP'
end

-- (0.105.4 review) hatch covers in store (free), for the hold on the shaft's last level
function shaft_hatch_covers()
    local ok, n = pcall(function() return (count_items('HATCH_COVER')) end)
    return ok and n or 0
end

-- (0.105.33 L5) A cavern well given up (the game refused the well, or it was
-- cancelled) over a shaft dug open into the cavern: its shaft still opens
-- the fort to the cavern, so its gate and lid are still kept (the gate
-- always shut: no bucket goes down it).
function shaft_left_open(p)
    return p.kind == 'well' and p.phase == 'cancelled' and not p.held
        and type(p.shaft) == 'table' and #p.shaft > 0
        and type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] ~= nil
        and shaft_bottom_open(p)
end

-- The cavern wells whose shaft gate and lid the AI keeps.
local function shaft_kept(p)
    local st = p.shaft_stairs
    if p.kind ~= 'well' or type(st) ~= 'table' or not st[1] then return false end
    if p.phase == 'furnish' or p.phase == 'done' then return true end
    if p.phase == 'dig' and (p.held or p.released) then return true end   -- (0.105.4 review) the gate before the breach
    return shaft_left_open(p)
end

SHAFT_WATCH = SHAFT_WATCH or {on = false}

local function abs_now()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and t or 0
end

local function gate_mem(pid)
    SHAFT_WATCH.gates = SHAFT_WATCH.gates or {}
    local g = SHAFT_WATCH.gates[pid]
    if not g then g = {}; SHAFT_WATCH.gates[pid] = g end
    return g
end

-- One step for each cavern well's shaft gate toward `want_closed` (a given-up
-- shaft's always toward shut). {ok, wells = [{project_id, was, stage?, error?}]}
-- (group 2) Shutting shuts the gates the watcher's test (shaft_judge) finds
-- a danger for (every gate when it finds none: the brain's own reason);
-- opening opens only a gate with no danger near and its hold (shaft_hold)
-- run out: "held_shut" otherwise, with the danger and the ticks left.
-- `dry` (true/false; nil: unchanged): the brain says the fort is short of
-- water (a far walker doesn't keep the shaft shut, no hold).
function well_shaft_step(want_closed, dry_run, dry)
    local data = load_projects()
    local wells, changed = {}, false
    local all_closed = want_closed
    local dry_changed = false
    if dry ~= nil and (SHAFT_WATCH.dry == true) ~= (dry == true) then
        dry_changed = true
        if not dry_run then SHAFT_WATCH.dry = (dry == true) or nil end
    end
    -- the linked gates' dangers now, by the watcher's own test
    local judged, hits = {}, {}
    for _, p in ipairs(data.list) do
        local sg = p.shaft_gate
        if p.kind == 'well' and shaft_kept(p) and type(sg) == 'table' and sg.lever and not sg.impossible then
            local a = anchor_of(p)
            local h = hatch_at(a.x, a.y, shaft_bottom(p))
            if h and h.built then
                table.insert(judged, {x = a.x, y = a.y, z = p.z, hz = shaft_bottom(p), id = p.id,
                                      shut = h.closed and true or false})
            end
        end
    end
    if #judged > 0 then
        local okt, t = pcall(shaft_threats, judged)
        if okt and type(t) == 'table' then
            for i, hit in pairs(t) do hits[judged[i].id] = hit end
        end
    end
    local any_hit = next(hits) ~= nil
    local now = abs_now()
    for _, p in ipairs(data.list) do
        local st = p.shaft_stairs
        if shaft_kept(p) then
            local hit = hits[p.id]
            local want_closed = (all_closed and (hit ~= nil or not any_hit)) or p.phase == 'cancelled'
            local leave = all_closed and not want_closed      -- another gate's danger: this one left as it is
            local a, hz = anchor_of(p), shaft_bottom(p)
            local g = shaft_gate_state(p)
            local r = {project_id = p.id, was = g.state, cancelled = p.phase == 'cancelled' or nil}
            local sg = p.shaft_gate
            -- rv 3: work below needs the stairs: a locked lid is unlocked
            if g.state ~= 'open' and g.state ~= 'closed' and g.state ~= 'none_possible' and not dry_run then
                local top = st[1]
                local lid = hatch_at(top.x, top.y, top.z)
                if lid and lid.forbidden then lid.b.door_flags.forbidden = false; r.unlocked_lid = true end
            end
            if g.state == 'none' or g.state == 'stray' or g.state == 'no_lever' then
                -- rv 2, 8: the lever first (a stray hatch kept: linked when the lever stands)
                local lv = (sg and sg.lever and free_floor(sg.lever.x, sg.lever.y, sg.lever.z or p.z)) and sg.lever
                    or shaft_lever_spot(p)
                if not lv then
                    r.error = 'no free floor near the well for the lever'
                elseif dry_run then
                    r.stage = 'place_lever'
                elseif designate({{x = lv.x, y = lv.y, text = 'Tl'}}, lv.z or p.z, 'build') then
                    p.shaft_gate = {lever = lv, link_fails = sg and sg.link_fails or nil}
                    r.stage, changed = 'lever_placed', true
                else
                    r.error = 'the game would not place the lever near the well'
                end
            elseif g.state == 'no_hatch' and p.held then
                -- (0.105.4 review) the lever stands: the shaft breaks into the cavern
                -- only once a hatch cover and 2 mechanisms (its link) are in store,
                -- so the hatch goes in straight after, before anything comes up
                local mech, covers = free_mechanism_count(), shaft_hatch_covers()
                if mech < 2 or covers < 1 then
                    r.stage, r.mechanisms, r.hatch_covers = 'waiting_parts', mech, covers
                elseif dry_run then
                    r.stage = 'break_through'
                else
                    local hd = p.held
                    local pri = type(p.params) == 'table' and p.params.pri or ''
                    local okh = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'h' .. (pri or '')}}, hd.z, a.x, a.y)
                    for _, c in ipairs(st) do
                        if c.z == hd.z then
                            pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. (pri or '')}}, c.z, c.x, c.y)
                        end
                    end
                    if okh then
                        p.held, p.released, changed = nil, true, true
                        r.stage = 'break_started'
                    else
                        r.error = 'the game would not dig the shaft\'s last level'
                    end
                end
            elseif g.state == 'no_hatch' and p.phase == 'dig' and not shaft_bottom_open(p) then
                r.stage = 'breaking_through'      -- (0.105.4 review) the hatch once the last level is dug
            elseif g.state == 'no_hatch' then
                -- rv 6: only with the lever up and 2 mechanisms free for the link
                local mech = free_mechanism_count()
                if mech < 2 then
                    r.stage, r.mechanisms = 'waiting_mechanisms', mech
                elseif dry_run then
                    r.stage = 'place_hatch'
                else
                    local okd, s = pcall(quickfort_apply, 'build', {{x = 0, y = 0, text = 'H'}}, hz, a.x, a.y, 'run', true)
                    if not okd or stat(s, 'build_designated') ~= 1 then
                        -- rv2 3: three refusals, not one, before the lid instead
                        sg.hatch_fails, changed = (sg.hatch_fails or 0) + 1, true
                        if sg.hatch_fails >= SHAFT_LINK_FAILS_MAX then sg.impossible = true end
                        r.error = 'the game would not build a hatch at the bottom of the shaft'
                            .. (sg.impossible and ' (3 times: the stair lid instead)' or '')
                    elseif designate({{x = a.x, y = a.y, text = 'H'}}, hz, 'build') then
                        r.stage = 'hatch_placed'
                    else
                        r.error = 'the game refused the hatch at the bottom of the shaft'
                    end
                end
            elseif g.state == 'unlinked' then
                -- (0.104.156) a link job asked for and gone with no link: DF
                -- cancelled it ("Item inaccessible", 25 times on 1 Nov). Lost 3
                -- times with the same mechanisms: no new job until others are free.
                local G = reqscript('ai-gates')
                if sg.link_asked and not dry_run then
                    sg.link_lost, sg.link_asked, changed = (sg.link_lost or 0) + 1, nil, true
                end
                local lp = sg.lever or {}
                local okf, cand = pcall(G.free_mechanisms, 2, {x = lp.x or a.x, y = lp.y or a.y, z = lp.z or p.z})
                local key = {}
                for _, m in ipairs(okf and type(cand) == 'table' and cand or {}) do table.insert(key, tostring(m.id)) end
                key = table.concat(key, ',')
                local lost = sg.link_lost or 0
                if lost >= SHAFT_LINK_FAILS_MAX and key == (sg.link_mechs or '') then
                    r.error = ('the link job was lost %d times (DF cancels it; mechanisms %s): waits for others')
                        :format(lost, key ~= '' and key or 'none')
                    r.link_lost = lost
                else
                    if lost >= SHAFT_LINK_FAILS_MAX and not dry_run then
                        sg.link_lost, changed = 0, true          -- other mechanisms: a fresh try
                    end
                    local res = dry_run and {ok = true} or G.link_lever(g.lever.id, g.hatch.id, false)
                    if res.ok then
                        r.stage = dry_run and 'link' or 'linking'
                        if not dry_run then
                            sg.link_asked, sg.link_mechs, changed = true, key, true
                            r.link_lost = sg.link_lost
                        end
                    else
                        r.error, r.mechanisms = res.error, res.mechanisms
                        -- rv 6: a link that keeps failing for another reason: the hatch
                        -- comes down (it would block the bucket for good), the lid instead
                        if not dry_run and not tostring(res.error or ''):find('mechanism') then
                            sg.link_fails, changed = (sg.link_fails or 0) + 1, true
                            if sg.link_fails >= SHAFT_LINK_FAILS_MAX then
                                pcall(dfhack.buildings.deconstruct, g.hatch.b)
                                sg.impossible = true
                                r.error = r.error .. ' (3 times: the shaft hatch taken down, the stair lid instead)'
                            end
                        end
                    end
                end
            elseif leave and (g.state == 'pulling' or g.state == 'closed' or g.state == 'open') then
                r.stage = g.state
            elseif not want_closed and (g.state == 'pulling' or g.state == 'closed')
                    and (hit or shaft_hold(p.id, sg, now) > 0) then
                -- (group 2) a danger near, or not away long enough: kept shut
                r.stage = 'held_shut'
                r.wait = shaft_hold(p.id, sg, now)
                if hit then
                    local okr, nm = pcall(dfhack.units.getReadableName, hit.u)
                    r.danger = okr and nm or ('unit ' .. tostring(hit.u and hit.u.id))
                end
            elseif g.state == 'pulling' then
                -- rv 9: a dwarf on the way to pull it: called off (a late pull would
                -- toggle the gate the wrong way), and the gate set at once
                if not dry_run then
                    local j = job_of(g.lever.id, df.job_type.PullLever)
                    if j then pcall(dfhack.job.removeJob, j) end
                    if g.hatch.closed ~= (want_closed == true) then
                        local ok, out = pull(g.lever.id, true)
                        if not ok then r.error = 'lever pull failed: ' .. tostring(out):sub(1, 120) end
                    end
                    if want_closed and not r.error then
                        gate_mem(p.id).shut_at, gate_mem(p.id).seen = now, hit and now or gate_mem(p.id).seen
                        if sg then sg.shut_at, changed = now, true end
                    end
                end
                if not r.error then r.stage = want_closed and 'closed' or 'opened' end
            elseif g.state == 'open' or g.state == 'closed' then
                if sg.link_lost or sg.link_asked then sg.link_lost, sg.link_asked, changed = nil, nil, true end
                if sg.lever_id ~= g.lever.id or sg.hatch_id ~= g.hatch.id then
                    sg.lever_id, sg.hatch_id, changed = g.lever.id, g.hatch.id, true   -- rv 13
                end
                if (g.state == 'closed') ~= (want_closed == true) then
                    if dry_run then
                        r.stage = want_closed and 'close' or 'open'
                    else
                        -- (0.104.164) opened at once too: a dwarf's pull never came (Teacheroar,
                        -- 1 Nov: well 218 "open its shaft again" 49 times in 90 minutes, the
                        -- gate still shut), and the hatch only opens while no danger is near
                        local ok, out = pull(g.lever.id, true)
                        if ok then r.stage = want_closed and 'closed' or 'opened'
                        else r.error = 'lever pull failed: ' .. tostring(out):sub(1, 120) end
                        if ok and want_closed then
                            gate_mem(p.id).shut_at, gate_mem(p.id).seen = now, hit and now or gate_mem(p.id).seen
                            sg.shut_at, changed = now, true
                        end
                    end
                else
                    r.stage = g.state
                end
            else
                r.stage = g.state            -- building, linking, none_possible: waits
            end
            table.insert(wells, r)
        end
    end
    if changed and not dry_run then save_projects(data) end
    if #wells == 0 then return {ok = false, rejected = true, error = 'no cavern well'} end
    local watch_started = false
    for _, r in ipairs(wells) do
        local linked = r.was == 'open' or r.was == 'closed' or r.was == 'pulling'
        if linked and not dry_run and shaft_watch_start() then watch_started = true end
    end
    local acted = watch_started or dry_changed
    for _, r in ipairs(wells) do
        if not r.error and r.stage and r.stage ~= r.was and r.stage ~= 'waiting_mechanisms'
                and r.stage ~= 'waiting_parts' and r.stage ~= 'breaking_through' and r.stage ~= 'held_shut' then
            acted = true
        end
    end
    local dry_now = SHAFT_WATCH.dry == true or nil
    if dry_run then return {ok = true, dry_run = true, wells = wells, dry = dry_now} end
    if acted then return {ok = true, wells = wells, dry = dry_now, dry_changed = dry_changed or nil} end
    local why = wells[1].error
    for _, r in ipairs(wells) do
        if not why and r.stage == 'held_shut' then
            why = 'kept shut: ' .. (r.danger and (tostring(r.danger) .. ' is near') or
                                    ('the danger has been away too short a while, ' .. tostring(r.wait) .. ' ticks to go'))
        end
    end
    return {ok = false, rejected = true, wells = wells,
            error = why or ('nothing to do: ' .. tostring(wells[1].stage or wells[1].was))}
end

-- (0.104.153) A wild animal that attacks: a large predator, or one DF has
-- agitated. (Most of the caverns' thousands of creatures are neither.)
function hostile_wild(u)
    if not dfhack.units.isAnimal(u) or dfhack.units.isFortControlled(u) then return false end
    local okt, tame = pcall(dfhack.units.isTame, u)
    if okt and tame then return false end
    local oka, agit = pcall(function() return u.flags4.agitated_wilderness_creature end)
    if oka and agit then return true end
    local okp, pred = pcall(function() return df.creature_raw.find(u.race).caste[u.caste].flags.LARGE_PREDATOR end)
    return okp and pred or false
end

local function unit_flies(u)
    local ok, f = pcall(function() return u.enemy.caste_flags.FLIER end)
    return ok and f or false
end

-- (0.104.153) The shaft watcher: every SHAFT_WATCH_TICKS inside the game
-- (the brain reads the fort once a game day: a flier crosses 60 tiles
-- sooner), an open shaft gate is shut at once when a real danger comes near
-- below it. It only shuts; the brain opens it again (well_shaft) once
-- shaft_hold says the danger has been away long enough. Lives while the
-- game runs; `well_lids` says whether it is on, and the `well_shaft`
-- action starts it.
--
-- (group 2, 14 Nov) E and F: the shafts shut for Lizard Devil, Brine
-- Specter, Steam Monster (demons down in the underworld, z 0-2, 140 levels
-- under the shaft: the old "a great danger anywhere below, however far"),
-- and opened again whenever a citizen stepped into a cavern (that rule's
-- exception), well_shaft 49 and 32 times, 186 dead of thirst over the
-- forts. Now (shaft_judge, the brain reads the same verdict in well_lids):
--   * only a danger (isDanger: forgotten beasts, invaders, ...) or a hostile
--     wild animal (agitated, a large predator); never tame, caged, chained,
--     peaceful wildlife (vermin are no units);
--   * only in the shaft itself (its column, 2 tiles round) or in the very
--     cavern the shaft opens into (its map feature; another cavern layer, the
--     magma sea or the underworld is walled off by rock);
--   * by how it could come up: a flier or a climber (grasping parts) within
--     SHAFT_NEAR (a great one within SHAFT_FAR), one that only walks or
--     swims within SHAFT_CLOSE (a great one within SHAFT_NEAR, but only
--     SHAFT_CLOSE while the brain says the fort is short of water: `dry`);
--   * a shut gate counts it SHAFT_MARGIN tiles further (no flapping at the
--     edge), stays shut SHAFT_MIN_SHUT ticks at least and opens only once no
--     danger was seen for SHAFT_CLEAR ticks (not while short of water).
SHAFT_WATCH_TICKS = 100
SHAFT_CLOSE = 20        -- a walker or swimmer this near below (tiles, levels counted too)
SHAFT_NEAR = 60         -- a flier or climber (or a great walker) this near
SHAFT_FAR = 80          -- a great flier or climber (a forgotten beast) this near
SHAFT_MARGIN = 15       -- a shut gate: counted this much further (hysteresis)
SHAFT_DRY_MARGIN = 5    -- ...a walker's, while the fort is short of water
SHAFT_LEVELS = 15       -- the cavern unknown (no map feature): only this many levels below
SHAFT_MIN_SHUT = 1200   -- ticks (a game day) a shut gate stays shut at least
SHAFT_CLEAR = 600       -- ticks no danger may be seen before it opens again
SHAFT_WATCH = SHAFT_WATCH or {on = false}

-- Pure: may this creature come up this shaft? c = {x, y, z, great, flier,
-- climber (nil: unknown, taken as yes), layer_match (true: the shaft's own
-- cavern, false: another, nil: unknown)}, w = {x, y, z (the well), hz (the
-- shaft's bottom)}, opts = {shut, dry}. The verdict {d, in_shaft, mobile,
-- great, reach} or nil.
function shaft_judge(c, w, opts)
    opts = opts or {}
    local dx = math.max(math.abs(c.x - w.x), math.abs(c.y - w.y))
    if c.z >= w.hz then
        if c.z < w.z and dx <= 2 then
            return {d = dx, in_shaft = true, mobile = true, great = c.great or nil, reach = 2}
        end
        return nil                       -- above the cavern, not in the shaft: the fort's own watch
    end
    if c.layer_match == false then return nil end
    local dz = w.hz - c.z
    if c.layer_match == nil and dz > SHAFT_LEVELS then return nil end
    local d = math.max(dx, dz)
    local mobile = (c.flier == true) or (c.climber ~= false)
    local reach
    if mobile then
        reach = c.great and SHAFT_FAR or SHAFT_NEAR
    else
        reach = (c.great and not opts.dry) and SHAFT_NEAR or SHAFT_CLOSE
    end
    if opts.shut then
        -- short of water a walker's margin is smaller (the brain's SHAFT_DRY_REACH: 20 + 5)
        reach = reach + ((opts.dry and not mobile) and SHAFT_DRY_MARGIN or SHAFT_MARGIN)
    end
    if d > reach then return nil end
    return {d = d, mobile = mobile, great = c.great or nil, reach = reach}
end

-- Ticks before a shut gate may be opened again (0: now).
function shaft_hold(pid, sg, now)
    if SHAFT_WATCH.dry then return 0 end
    now = now or abs_now()
    local g = (SHAFT_WATCH.gates or {})[pid] or {}
    local shut_at = g.shut_at or (type(sg) == 'table' and sg.shut_at) or nil
    if not shut_at or now < shut_at then return 0 end
    local seen = g.seen or shut_at
    if now < seen then seen = shut_at end
    return math.max(0, SHAFT_MIN_SHUT - (now - shut_at), SHAFT_CLEAR - (now - seen))
end

-- (0.105.33 L5) DFHack cancels every non-'frames' timer when the world
-- unloads, so a saved timer id can be dead: ask DFHack, not the id.
local function shaft_watch_alive()
    if not (SHAFT_WATCH.on and SHAFT_WATCH.timer) then return false end
    if type(dfhack.timeout_active) ~= 'function' then return true end   -- (no way to ask: the id taken at its word)
    local ok, active = pcall(dfhack.timeout_active, SHAFT_WATCH.timer)
    return (ok and active) and true or false
end

if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-builder-wells-watch'] = function(sc)
        if sc == SC_MAP_UNLOADED then SHAFT_WATCH = {on = false} end
    end
end

-- (group 2) climbing takes a grasping part (DF: no hands, no climbing).
-- nil when the raws can't be read (then taken as a climber).
local function unit_climbs(u)
    local ok, yes = pcall(function()
        for _, bp in ipairs(df.creature_raw.find(u.race).caste[u.caste].body_info.body_parts) do
            if bp.flags.GRASP then return true end
        end
        return false
    end)
    if ok then return yes end
    return nil
end

-- the map feature (a cavern layer) a tile's block belongs to; nil: none or unknown
local function feature_at(x, y, z)
    local ok, f = pcall(function()
        local b = dfhack.maps.getTileBlock(x, y, z)
        return b and b.global_feature
    end)
    if ok and type(f) == 'number' and f >= 0 then return f end
    return nil
end

-- The worst danger for each well: {[i] = {u, v}} (v: shaft_judge's verdict),
-- the nearest one, one in the shaft first. wells: {x, y, z, hz, shut}.
function shaft_threats(wells)
    local out = {}
    for _, w in ipairs(wells) do
        if w.cave == nil then w.cave = feature_at(w.x, w.y, w.hz - 1) or feature_at(w.x, w.y, w.hz) or false end
    end
    local dry = SHAFT_WATCH.dry == true
    for _, u in ipairs(df.global.world.units.active) do
        pcall(function()
            if not dfhack.units.isActive(u) or dfhack.units.isDead(u) or dfhack.units.isCitizen(u, true) then return end
            if u.flags1.caged or u.flags1.chained then return end
            local okf, fort = pcall(dfhack.units.isFortControlled, u)
            if okf and fort then return end
            local okt, tame = pcall(dfhack.units.isTame, u)
            if okt and tame then return end
            local danger = dfhack.units.isDanger(u)
            if not (danger or hostile_wild(u)) then return end
            local okg, great = pcall(dfhack.units.isGreatDanger, u)
            local c = {x = u.pos.x, y = u.pos.y, z = u.pos.z, great = (okg and great) or nil,
                       flier = unit_flies(u)}
            local uf, asked
            for i, w in ipairs(wells) do
                if c.z < w.hz then
                    if not asked and c.flier ~= true then c.climber, asked = unit_climbs(u), true end
                    if w.cave then
                        if uf == nil then uf = feature_at(c.x, c.y, c.z) or false end
                        c.layer_match = (uf == w.cave)
                    else
                        c.layer_match = nil
                    end
                end
                local v = shaft_judge(c, w, {shut = w.shut, dry = dry})
                if v then
                    v.flier = c.flier or nil
                    v.climber = (c.climber == true) or nil
                    local old = out[i]
                    if not old or (v.in_shaft and not old.v.in_shaft)
                            or (not old.v.in_shaft and v.d < old.v.d) then
                        out[i] = {u = u, v = v}
                    end
                end
            end
        end)
    end
    return out
end

-- (kept for callers of the old name) the first well with a danger, and the unit
function shaft_threat_near(wells)
    local hits = shaft_threats(wells)
    for i, w in ipairs(wells) do
        if hits[i] then return w, hits[i].u, hits[i].v end
    end
end

local function shaft_watch_tick()
    SHAFT_WATCH.timer = nil
    if not SHAFT_WATCH.on then return end
    local ok, err = pcall(function()
        local wells = {}
        local data = load_projects()
        for _, p in ipairs(data.list) do
            -- a linked gate (its ids saved): only its hatch and lever read, not every
            -- building's links (this runs 12 times a game day)
            local sg = p.shaft_gate
            if p.kind == 'well' and sg and sg.lever_id and sg.hatch_id and not sg.impossible then
                local a = anchor_of(p)
                local h = hatch_at(a.x, a.y, shaft_bottom(p))
                if h and h.built and h.id == sg.hatch_id then
                    table.insert(wells, {x = a.x, y = a.y, z = p.z, hz = shaft_bottom(p), id = p.id, p = p,
                                         lever_id = sg.lever_id, shut = h.closed and true or false})
                end
            end
        end
        if #wells == 0 then return end
        local now, saved = abs_now(), false
        for i, hit in pairs(shaft_threats(wells)) do
            local w = wells[i]
            local g = gate_mem(w.id)
            g.seen = now
            if not w.shut then
                local pending = job_of(w.lever_id, df.job_type.PullLever)
                if pending then pcall(dfhack.job.removeJob, pending) end
                pull(w.lever_id, true)
                g.shut_at = now
                w.p.shaft_gate.shut_at = now
                saved = true
                SHAFT_WATCH.last = {project_id = w.id, tick = df.global.cur_year_tick, year = df.global.cur_year,
                                    unit = hit.u and hit.u.id or nil}
            end
        end
        if saved and save_projects then pcall(save_projects, data) end
    end)
    SHAFT_WATCH.error = (not ok) and tostring(err):sub(1, 160) or nil
    SHAFT_WATCH.timer = dfhack.timeout(SHAFT_WATCH_TICKS, 'ticks', shaft_watch_tick)
end

function shaft_watch_start()
    if shaft_watch_alive() then return false end
    SHAFT_WATCH.on = true
    SHAFT_WATCH.timer = dfhack.timeout(SHAFT_WATCH_TICKS, 'ticks', shaft_watch_tick)
    return true
end

-- Each cavern well: {project_id, x, y, z, elevation (the column's top step),
-- state (the lid: none, planned, open, locked, blocked, gone), gate (the
-- shaft gate's state), gate_mechanisms?}.
function well_lids(probe, data)
    OFFSET = elevation_offset()
    local out = {}
    data = data or load_projects()      -- (13c) projects_report passes its own
    for _, p in ipairs(data.list) do
        local st = p.shaft_stairs
        if shaft_kept(p) then
            local top = st[1]
            local r = {project_id = p.id, x = top.x, y = top.y, z = top.z, elevation = ez(top.z)}
            if p.phase == 'cancelled' then r.cancelled = true end    -- (0.105.33 L5) given up, its shaft open
            -- (0.105.26) the shaft's opening into the cavern (where its gate's hatch goes)
            local an0 = anchor_of(p)
            r.shaft_hatch = {x = an0.x, y = an0.y, z = shaft_bottom(p)}
            -- (0.105.4 review) the shaft's last level held undug till the gate's parts are in store
            if p.held then r.held = true; r.hatch_covers = shaft_hatch_covers() end
            if p.released and p.phase == 'dig' then r.breaking = true end
            local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(top.x, top.y, top.z))
            if okb and b then
                if b:getType() ~= df.building_type.Hatch then
                    r.state = 'blocked'
                elseif b:getBuildStage() < b:getMaxBuildStage() then
                    r.state = 'planned'
                else
                    local okf, f = pcall(function() return b.door_flags.forbidden end)
                    r.state = (okf and f) and 'locked' or 'open'
                    r.hatch_id = b.id
                end
            else
                local tl = tile_info(top.x, top.y, top.z)
                r.state = (tl and STAIR_DOWN_SHAPE[tl.shape]) and 'none' or 'gone'
            end
            local okg, g = pcall(shaft_gate_state, p)
            if okg and g then
                r.gate = g.state
                if g.state == 'no_hatch' or g.state == 'unlinked' then r.gate_mechanisms = free_mechanism_count() end
                -- (0.104.156) the ones the lever can reach (a link with others is cancelled)
                local sg = p.shaft_gate or {}
                if g.state == 'unlinked' and sg.lever then
                    local okm, m, far, far_at = pcall(reqscript('ai-gates').free_mechanisms, 2,
                                                      {x = sg.lever.x, y = sg.lever.y, z = sg.lever.z or p.z})
                    if okm and type(m) == 'table' then
                        r.gate_mechanisms_reachable = #m
                        if (far or 0) > 0 then r.gate_mechanisms_far = far end
                        if type(far_at) == 'table' and #far_at > 0 then
                            r.gate_mechanisms_far_at = table.concat(far_at, '; ')
                        end
                        local okg, lg = pcall(walk_group, sg.lever.x, sg.lever.y, sg.lever.z or p.z)
                        if okg then r.gate_lever_group = lg end
                    end
                end
                if sg.link_lost then r.gate_link_lost = sg.link_lost end
                if g.hatch then r.gate_hatch_built = g.hatch.built and true or false end
                r.gate_hatch_standing = g.hatch ~= nil or nil     -- rv2 1: a hatch still at the shaft's bottom
                if g.state == 'open' or g.state == 'closed' or g.state == 'pulling' then     -- (0.104.153)
                    r.watching = shaft_watch_alive()
                    r.watch_error = SHAFT_WATCH.error
                    if SHAFT_WATCH.last and SHAFT_WATCH.last.project_id == p.id then r.watch_last = SHAFT_WATCH.last end
                    -- (0.104.165) what the watcher would shut it for now, by its own test: the
                    -- report's wild list holds only animals in a "Cavern" layer, and the brain
                    -- reopened the gate under a predator the watcher saw (Teacheroar, unit
                    -- 6300), the watcher shutting it again at once. (group 2) The same
                    -- verdict the watcher and well_shaft act on (shaft_judge), and the hold
                    -- left before a shut gate may open (shaft_hold): the brain decides by them.
                    local an = anchor_of(p)
                    local shut = g.state ~= 'open'
                    r.watch_rule = 2
                    local okn, hits = pcall(shaft_threats, {{x = an.x, y = an.y, z = p.z, hz = shaft_bottom(p), shut = shut}})
                    local hit = okn and type(hits) == 'table' and hits[1] or nil
                    if hit and hit.u then
                        local u, v = hit.u, hit.v
                        local okr, nm = pcall(dfhack.units.getReadableName, u)
                        if okr and dfhack.df2utf then local okc, c = pcall(dfhack.df2utf, nm); if okc and c then nm = c end end
                        r.watch_near = {id = u.id, name = okr and nm or nil,
                                        pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z},
                                        d = v.d, reach = v.reach, great = v.great, flier = v.flier,
                                        climber = v.climber, mobile = v.mobile and true or false,
                                        in_shaft = v.in_shaft}
                    end
                    if shut then
                        local okh, hold = pcall(shaft_hold, p.id, p.shaft_gate)
                        r.shut_hold = okh and hold or 0
                    end
                    if SHAFT_WATCH.dry then r.watch_dry = true end
                end
            else
                r.gate_error = tostring(g):sub(1, 120)
            end
            table.insert(out, r)
        end
    end
    return out
end

-- The stair lid, only where the shaft gate can't be built: a hatch planned
-- where there is none (buildingplan waits for a hatch cover), a built one
-- locked. {ok, planned, locked, waiting}.
function seal_well_stairs(dry_run)
    local planned, locked, waiting = 0, 0, 0
    for _, r in ipairs(well_lids(false)) do
        if r.gate ~= 'none_possible' then
            -- the gate seals the cavern: the lid stays unlocked (the way down to it)
        elseif r.gate_hatch_standing then
            -- rv2 1: a failed hatch still stands shut at the shaft's bottom: a
            -- dwarf must go down these stairs to take it away first
            waiting = waiting + 1
        elseif r.state == 'none' then
            if dry_run then
                planned = planned + 1
            else
                local okq, s = pcall(quickfort_apply, 'build', {{x = 0, y = 0, text = 'H'}}, r.z, r.x, r.y)
                if okq and stat(s, 'build_designated') == 1 then planned = planned + 1 else waiting = waiting + 1 end
            end
        elseif r.state == 'open' then
            if not dry_run then
                local b = df.building.find(r.hatch_id)
                if b then b.door_flags.forbidden = true end
            end
            locked = locked + 1
        elseif r.state == 'planned' then
            waiting = waiting + 1
        end
    end
    if planned + locked == 0 then
        return {ok = false, rejected = true, error = 'no cavern well stair to close', waiting = waiting}
    end
    return {ok = true, planned = planned, locked = locked, waiting = waiting, dry_run = dry_run or nil}
end

-- (0.105.24) A cavern well given up over a dug shaft (the game wouldn't place
-- the well: C's #110, F's #114, 3 Nov) taken up again, once: its shaft still
-- open all the way down, nothing built on its top, a floor beside the top
-- (or a landing to dig, as place_well digs one). The project goes back to
-- digging (the landing), then to furnish as before. nil when there is none
-- (or none that can be taken up: then `why` is kept for the next look).
OPEN_SHAPE = function(t) return t ~= nil and t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP' end

function revive_cavern_well(data, pri, dry_run)
    for _, p in ipairs(data.list) do
        if p.kind == 'well' and p.phase == 'cancelled' and type(p.shaft) == 'table' and #p.shaft > 0
                and type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] and not p.revived and not p.unreached
                and not p.held then
            local a = anchor_of(p)
            local top = tile_info(a.x, a.y, p.z)
            local open = top ~= nil and (top.shape == 'EMPTY' or top.shape == 'RAMP_TOP') and not top.building
            for _, zk in ipairs(p.shaft) do
                if not OPEN_SHAPE(tile_info(a.x, a.y, zk)) then open = false end
            end
            if open then
                local st = p.shaft_stairs[1]
                local floors = {}
                for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do floors[g.x .. ',' .. g.y] = true end
                local landing, lwhy
                if not well_floor_beside(a.x, a.y, p.z, floors, st) then
                    landing, lwhy = well_landing(a.x, a.y, p.z, st, floors)
                    if not landing then
                        p.revive_why = lwhy
                        if not dry_run then save_projects(data) end
                        return nil
                    end
                end
                local out = {ok = true, project_id = p.id, revived = true, cavern = true, x = a.x, y = a.y,
                             elevation = ez(p.z), landing = landing and {x = landing.x, y = landing.y} or nil,
                             dry_run = dry_run or nil}
                if dry_run then return out end
                if landing then
                    local s = quickfort_apply('dig', {{x = 0, y = 0, text = 'd' .. (pri or '')}}, p.z, landing.x, landing.y)
                    if stat(s, 'dig_designated') ~= 1 then
                        return {ok = false, error = ('the game would not dig a floor beside the old well shaft at x%d y%d elevation %d')
                            :format(landing.x, landing.y, ez(p.z))}
                    end
                    p.gallery = type(p.gallery) == 'table' and p.gallery or {}
                    table.insert(p.gallery, {x = landing.x, y = landing.y})
                    p.landing = {x = landing.x, y = landing.y}
                end
                p.phase, p.revived = 'dig', true
                p.well_refusals, p.well_retry_at = nil, nil
                if not save_projects(data) then return {ok = false, error = 'could not save the project with the fort'} end
                return out
            end
        end
    end
    return nil
end

-- (0.105.33 L5) A cavern well's other designations taken back: the shaft's
-- levels, the stair column beside it and the gallery (the top channel is
-- cells.dig, undone by the caller). Tiles already dug stay dug.
function undo_well_cells(p)
    local a = anchor_of(p)
    local pri = type(p.params) == 'table' and p.params.pri or ''
    for _, zk in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'h' .. pri}}, zk, a.x, a.y, 'undo')
    end
    for _, c in ipairs(type(p.shaft_stairs) == 'table' and p.shaft_stairs or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'undo')
    end
    for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. pri}}, p.z, g.x, g.y, 'undo')
    end
end

-- Start a well: channel the spot now; the well itself is placed when the
-- hole is dug (furnish), like any other project.
function place_well(params, now, dry_run)
    OFFSET = elevation_offset()
    local data = load_projects()
    local open = open_projects(data)
    -- (0.104.13) a well the injured or the parched wait for takes an urgent
    -- slot, like soap and tombs (Enxah: "no well yet: waiting for a free
    -- building slot" while patients died of thirst)
    if #open >= slot_cap(open) + (params.urgent == true and URGENT_EXTRA or 0) then
        return {ok = false, rejected = true,
                error = ('already %d unfinished building projects'):format(#open)}
    end
    -- (0.104.13) dug first while the injured wait (quickfort's priority digit:
    -- 1 is the highest; 4, the game's default, otherwise)
    local pri = params.urgent == true and '1' or ''
    local reserved = {}
    for _, p in ipairs(open) do table.insert(reserved, p.area) end
    -- (0.105.31) nor where a well was given up as out of reach lately: E's
    -- shore well went on the same tile (x67 y124) four times, a year each
    for _, a in ipairs(well_spots_unreached(data)) do table.insert(reserved, a) end
    local spot, why, cut      -- (13c) cut: a search ran out of time
    if params.cavern then
        -- (0.105.24) a cavern well given up because the game wouldn't place
        -- the well over its dug shaft (C, F) is taken up again first, with a
        -- floor dug beside the shaft's top: no second shaft into the cavern
        local okr, rv = pcall(revive_cavern_well, data, pri, dry_run)
        if okr and rv then return rv end
        -- (0.105.4 review) a "no spot" kept since the last survey: not searched again
        -- (third review: the near box's save counts as a survey, near_tick)
        local okw, wl = pcall(function() return reqscript('ai-water').last() end)
        local stamp = ('%s/%s'):format(okw and type(wl) == 'table' and tostring(wl.near_tick or wl.tick) or '-', tostring(params.gallery))
        local today = type(now) == 'table' and ((tonumber(now.year) or 0) * 403200 + (tonumber(now.tick) or 0)) // 1200 or nil
        local c = CAVERN_NO_SPOT
        if c and c.stamp == stamp and today and c.day and today >= c.day and today - c.day < CAVERN_NO_SPOT_DAYS then
            return {ok = false, error = c.why, cached = true}
        end
        local started = os.clock()
        spot, why, cut = find_cavern_well_spot(reserved)
        -- (0.105.3) Hammerstirred (2 Nov): no fort floor over the cavern lake
        -- (it lies beside the fort, 80 tiles off by the survey): a gallery
        -- through solid rock out to a column over it, unless the brain says no
        if not spot and params.gallery ~= 0 then
            local left = math.max(0.1, CAVERN_TOTAL_SECONDS - (os.clock() - started))
            local g, gwhy, gcut = find_gallery_well_spot(reserved, {max = params.gallery, toward = params.toward, seconds = left})
            if g then spot = g else why, cut = why .. '; ' .. gwhy, cut or gcut end
        end
        if not spot then
            -- (a search cut short by its time is not kept: it may find one next time)
            if not cut then CAVERN_NO_SPOT = {stamp = stamp, day = today, why = why} end
            return {ok = false, error = why, timed_out = cut or nil}
        end
        CAVERN_NO_SPOT = nil
        -- (0.105.4 review) Hammerstirred's Cavern1 was undiscovered: the first
        -- breach changes the fort's dangers, so only when the player allows it
        if spot.hidden and params.open_caverns ~= true then
            return {ok = false, rejected = true, unfound = true,
                    error = 'the shaft would open a cavern no dwarf has seen yet: allowed only from the Rules tab '
                        .. '("Cavern well into an unfound cavern")'}
        end
    else
        spot, why, cut = find_well_spot(reserved)
    end
    if not spot and params.inside_only then
        return {ok = false, timed_out = cut or nil, error = why .. '; and the water near the surface freezes in winter (a well over '
                .. 'it would be taken down), so the AI looks only inside the fort'}
    end
    if not spot then
        local shore, why2, cut2 = find_shore_well_spot(reserved, params.shore_reach)
        if not shore then return {ok = false, error = why .. '; ' .. why2, timed_out = (cut or cut2) or nil} end
        spot = shore
    end
    local dig = {{x = 0, y = 0, text = 'h' .. pri}}
    local dry = quickfort_apply('dig', dig, spot.z, spot.x, spot.y, 'run', true)
    if stat(dry, 'dig_designated') ~= 1 then
        return {ok = false, error = ('the game would not channel the well spot at x%d y%d z%d'):format(
            spot.x, spot.y, ez(spot.z)) .. dig_guard_note(dry)}   -- (0.105.40b fix) the guard's why
    end
    -- a cavern well's shaft: every rock level under the floor channelled too,
    -- each from the stair column beside it (0.104.13)
    local shaft = {}
    for k = 1, spot.cavern and spot.rock or 0 do
        local zk = spot.z - k
        local d = quickfort_apply('dig', dig, zk, spot.x, spot.y, 'run', true)
        if stat(d, 'dig_designated') ~= 1 then
            return {ok = false, error = ('the game would not channel the shaft at elevation %d'):format(ez(zk))
                    .. dig_guard_note(d)}   -- (0.105.40b fix) the guard's why
        end
        table.insert(shaft, zk)
    end
    -- (0.105.24) the well needs a floor on one of its sides (quickfort's well
    -- test): the gallery's or the hall's; else a landing dug beside the shaft
    local galls = {}
    for _, g in ipairs(spot.gallery or {}) do galls[g.x .. ',' .. g.y] = true end
    local landing
    if spot.cavern then
        if not well_floor_beside(spot.x, spot.y, spot.z, galls, spot.side) then
            local lwhy
            landing, lwhy = well_landing(spot.x, spot.y, spot.z, spot.side, galls)
            if not landing then
                return {ok = false, error = ('no floor beside the well spot at x%d y%d elevation %d for its builder (%s)')
                    :format(spot.x, spot.y, ez(spot.z), lwhy)}
            end
            spot.gallery = spot.gallery or {}
            table.insert(spot.gallery, {x = landing.x, y = landing.y})
        end
    end
    -- (0.105.3) the gallery out to the shaft, dug as plain floor through the rock
    local gallery = {}
    for _, g in ipairs(spot.gallery or {}) do
        local d = quickfort_apply('dig', {{x = 0, y = 0, text = 'd' .. pri}}, spot.z, g.x, g.y, 'run', true)
        if stat(d, 'dig_designated') ~= 1 then
            return {ok = false, error = ('the game would not dig the gallery at x%d y%d elevation %d'):format(g.x, g.y, ez(spot.z))}
        end
        table.insert(gallery, {x = g.x, y = g.y})
    end
    -- (0.105.4 review) the review: the last channel opened the cavern while the
    -- project was still digging, and the gate's lever and hatch came only at
    -- furnish (links lost 3+ times on 1 Nov). That level and the stair step
    -- beside it are held undug until the lever stands and a hatch cover and 2
    -- mechanisms are in store (well_shaft_step lets them go)
    local held = spot.cavern and #shaft > 0 and {z = shaft[#shaft], stair = spot.side and {x = spot.side.x, y = spot.side.y}} or nil
    local stairs = {}
    if spot.cavern then
        if not spot.side then return {ok = false, error = 'no room beside the shaft for the stairs it is dug from'} end
        for _, c in ipairs(shaft_stair_cells(spot.side, spot.z, spot.rock)) do
            local d = quickfort_apply('dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'run', true)
            if stat(d, 'dig_designated') ~= 1 then
                return {ok = false, error = ('the game would not dig the shaft\'s stairs at elevation %d'):format(ez(c.z))}
            end
            table.insert(stairs, c)
        end
    end
    local where = {x = spot.x, y = spot.y, elevation = ez(spot.z), drop = spot.drop, in_hall = spot.zone,
                   shore = spot.shore, stagnant = spot.stagnant, cavern = spot.cavern, shaft = #shaft,
                   stairs = #stairs > 0 and #stairs or nil, urgent = params.urgent == true or nil,
                   gallery = #gallery > 0 and #gallery or nil, from = spot.from, from_gate = spot.from_gate,
                   held = held and 2 or nil, landing = landing and {x = landing.x, y = landing.y} or nil}   -- (0.105.24)
    if dry_run then
        where.ok, where.dry_run = true, true
        return where
    end
    local real = quickfort_apply('dig', dig, spot.z, spot.x, spot.y)
    if stat(real, 'dig_designated') ~= 1 then
        pcall(quickfort_apply, 'dig', dig, spot.z, spot.x, spot.y, 'undo')
        return {ok = false, error = 'the game refused to channel the well spot'}
    end
    for _, zk in ipairs(shaft) do
        if not (held and zk == held.z) then pcall(quickfort_apply, 'dig', dig, zk, spot.x, spot.y) end
    end
    for _, g in ipairs(gallery) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. pri}}, spot.z, g.x, g.y)
    end
    for _, c in ipairs(stairs) do
        if not (held and c.z == held.z) then
            pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y)
        end
    end
    local p = {
        id = data.next_id, kind = 'well', phase = 'dig', params = {pri = pri ~= '' and pri or nil},
        stair = {x = spot.x, y = spot.y}, anchor = {x = spot.x, y = spot.y}, z = spot.z,
        area = {x1 = spot.x - 1, y1 = spot.y - 1, x2 = spot.x + 1, y2 = spot.y + 1, z = spot.z},
        corridor = 0, stairs = {}, dig_done = 'open', shaft = #shaft > 0 and shaft or nil,
        shaft_stairs = #stairs > 0 and stairs or nil, urgent = params.urgent == true or nil,
        gallery = #gallery > 0 and gallery or nil,      -- (0.105.3)
        held = held,                                    -- (0.105.4 review)
        landing = landing,                              -- (0.105.24) the floor dug beside the shaft's top
        summary = {well = 1, drop = spot.drop, cavern = spot.cavern}, furniture = {Well = 1},
        cells = {dig = dig, build = {{x = 0, y = 0, text = 'l'}}, place = {}, zone = {},
                 smooth = {}, engrave = {}},
        started = now, designated = 1,
    }
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    if not save_projects(data) then
        -- (0.105.33 L5) every cell designated taken back, not the top channel only
        pcall(quickfort_apply, 'dig', dig, spot.z, spot.x, spot.y, 'undo')
        undo_well_cells(p)
        return {ok = false, error = 'could not save the project with the fort, so it was undone'}
    end
    where.ok, where.project_id = true, p.id
    return where
end


-- --- (0.105.31) a well's channel nobody digs ---------------------------------
--
-- Shore wells in every fort sat at "0 of 1 tiles dug" for 14 to 80 days, a
-- year in E (x67 y124, four times): a DigChannel job DF made and no miner
-- took (free_dig_jobs freed nothing: it had no worker), and the dig_first
-- rule couldn't raise a channel (prioritize_project raises rock only). Now
-- the bridge says why (well_dig_check), the brain renews the channel
-- (renew_well_dig: the unworked job taken away, the tile designated a
-- channel again at a higher priority; DF makes a fresh job) and a spot given
-- up as out of reach isn't chosen again for UNREACHED_YEARS.

-- The areas of wells given up as out of reach, or (0.105.33 B4) whose well
-- the game refused to place, in the last UNREACHED_YEARS.
function well_spots_unreached(data)
    local out = {}
    local okc, year = pcall(function() return df.global.cur_year end)
    for _, p in ipairs(type(data) == 'table' and data.list or {}) do
        if p.kind == 'well' and (p.unreached or p.refused) and type(p.area) == 'table' then
            local y = tonumber(p.cancelled_year)
            if not (okc and y) or year - y < (UNREACHED_YEARS or 5) then table.insert(out, p.area) end
        end
    end
    return out
end

-- The citizens with the mining labour ({x, y, z} each), or nil when it
-- can't be read. Tests replace this.
function well_miners()
    local ok, out = pcall(function()
        local out = {}
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local okl, mine = pcall(function() return u.status.labors.MINE end)
            if okl and mine then
                local x, y, z = dfhack.units.getPosition(u)
                if x then table.insert(out, {x = x, y = y, z = z}) end
            end
        end
        return out
    end)
    return ok and out or nil
end

-- Why a well level's channel isn't dug: {cause, text, x, y, elevation} or
-- nil. cause: 'no_designation' (gone and no job), 'wrong_designation' (a
-- dig of another kind on the floor), 'marked' (marker only), 'no_miners',
-- 'no_ground' (nothing to stand on beside it), 'unreached' (no miner walks
-- to beside it), 'held' (a cavern shaft's last level waits for its gate),
-- 'unworked' (a job no miner takes), 'waiting' (designated, no job yet).
-- A miner channels from beside the tile, on its own level.
function well_dig_check(p, jobs)
    local a = anchor_of(p)
    local x, y, z = a.x, a.y, p.z
    local t = tile_info(x, y, z)
    if not t then return nil end
    local function out(cause, text)
        return {cause = cause, text = text, x = x, y = y, elevation = ez(z)}
    end
    jobs = jobs or job_tiles()
    local job = jobs[x .. ',' .. y .. ',' .. z]
    if not job and not t.designated then
        return out('no_designation', 'its channel designation is gone and no job is on it')
    end
    if t.marked then
        return out('marked', 'it is designated as a marker only, which no dwarf digs')
    end
    if not job and t.dig and t.dig ~= 'Channel' then
        return out('wrong_designation', ('it is designated "%s", not a channel'):format(tostring(t.dig)))
    end
    local miners = well_miners()
    if miners and #miners == 0 then
        return out('no_miners', 'no citizen has the mining labour')
    end
    if miners then
        local groups = {}
        for _, m in ipairs(miners) do
            local g = walk_group(m.x, m.y, m.z)
            if g ~= 0 then groups[g] = true end
        end
        local ground, reached = false, false
        for dy = -1, 1 do
            for dx = -1, 1 do
                if dx ~= 0 or dy ~= 0 then
                    local g = walk_group(x + dx, y + dy, z)
                    if g ~= 0 then
                        ground = true
                        if groups[g] then reached = true end
                    end
                end
            end
        end
        if not ground then return out('no_ground', 'no floor beside it for a miner to stand on') end
        if not reached then
            return out('unreached', ('none of the %d miners can walk to beside it'):format(#miners))
        end
    end
    if type(p.held) == 'table' and not job then
        return out('held', 'the shaft\'s last level waits for its gate (lever, hatch cover, mechanisms)')
    end
    if job then
        return out('unworked', 'DF made the channel job but no miner takes it (a stale job, other digging '
                               .. 'first, or a shut door, burrow or raised bridge on the way)')
    end
    return out('waiting', 'designated as a channel, waiting for a miner')
end

-- (0.105.31 reserve fixes) the jobs renew_well_dig may take away: the
-- channel (or a dig) on the well's tile, never another job standing there
-- (a construction, a haul, a building's)
WELL_RENEW_JOBS = {DigChannel = true, Dig = true}
function well_dig_job(j)
    local ok, name = pcall(function() return df.job_type[j.job_type] end)
    return ok and name ~= nil and WELL_RENEW_JOBS[name] == true
end

-- The well level's channel renewed: its unworked channel (or dig) job taken away
-- and the floor designated a channel again at priority `pri` (DF makes a
-- fresh job from it). Rock left under a cavern shaft is not touched here.
function renew_well_dig(id, pri, dry_run)
    pri = math.max(1, math.min(3, math.tointeger(pri) or 2))
    local data = load_projects()
    local p
    for _, q in ipairs(data.list or {}) do if q.id == id then p = q end end
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.kind ~= 'well' or p.dig_done ~= 'open' then
        return {ok = false, rejected = true, error = 'only a well level\'s channel is renewed'}
    end
    if p.phase ~= 'dig' then return {ok = false, rejected = true, error = 'project is not being dug'} end
    local a = anchor_of(p)
    local t = tile_info(a.x, a.y, p.z)
    if not (t and t.shape == 'FLOOR') then
        return {ok = false, rejected = true, error = 'nothing left to channel'}
    end
    local okc, check = pcall(well_dig_check, p)
    if dry_run then
        return {ok = true, dry_run = true, priority = pri, cause = okc and check and check.cause or nil}
    end
    local gone = 0
    pcall(function()
        local link = df.global.world.jobs.list.next
        while link do
            local j, nxt = link.item, link.next
            if j and j.pos.x == a.x and j.pos.y == a.y and j.pos.z == p.z and well_dig_job(j) then
                local okw, w = pcall(dfhack.job.getWorker, j)
                if not (okw and w) and pcall(dfhack.job.removeJob, j) then gone = gone + 1 end
            end
            link = nxt
        end
    end)
    local s = quickfort_apply('dig', {{x = 0, y = 0, text = 'h' .. pri}}, p.z, a.x, a.y)
    if stat(s, 'dig_designated') ~= 1 then
        return {ok = false, error = ('the game would not channel the well spot at x%d y%d elevation %d again')
                    :format(a.x, a.y, ez(p.z)), renewed = gone}
    end
    p.dig_pri, p.renewed = pri, (tonumber(p.renewed) or 0) + 1
    save_projects(data)
    return {ok = true, priority = pri, renewed = gone, times = p.renewed,
            cause = okc and check and check.cause or nil}
end
