-- ai-builder-wells: wells: the spot under the fort, on the shore, over a cavern or at the
-- end of a gallery. (r8) The rest is in the parts loaded right after this one:
-- ai-builder-wells-shaft (the cavern shaft's gate and lid), ai-builder-wells-watch
-- (the watch on what comes up a shaft; the wells' lids) and ai-builder-wells-place
-- (a shaft taken up again or undone, the winter cistern, place_well, a well's dig renewed).
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-wells'] = '0.105.98'   -- (0.105.26) bumped with BRIDGE_VERSION

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
