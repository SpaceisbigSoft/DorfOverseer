-- ai-gates-fortify: a wide opening fortified in the fort's gate style: the hatches, water in an
-- opening, the sealed style, plan_gate and plan_line.
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-fortify'] = '0.105.38'   -- (0.105.26) bumped with BRIDGE_VERSION

local key, unkey, STAIR_UP, T, interior, moves, inside_or_courtyard, seals, ORTHO, WALL_GROUND = key, unkey, STAIR_UP, T, interior, moves, inside_or_courtyard, seals, ORTHO, WALL_GROUND   -- (13e) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- Fortifying a wide opening in the fort's gate style (brain/culture.py
-- gate_style): walls across it leaving a gap, doors in the gap, and by style
-- a second door behind, cage traps, flanking statues. Checked first: the
-- walls and doors must seal the opening and must not cut the fort apart.
---------------------------------------------------------------------------

-- (grand is 2, not 3: the middle door of a 3-wide gap would never have a wall
-- beside it, and DF only builds a door next to a wall)
-- (0.105.30) wagon: the underground depot's road, 3 wide: a 3-wide raising
-- drawbridge across it (a lowered bridge is floor to a wagon), never doors;
-- sealed: walls only, no door: a cavern opening walled for good (plan_sealed)
GAP = {plain = 2, narrow = 1, fortified = 1, gatehouse = 1, grand = 2, drawbridge = 2, wagon = 3,
       sealed = 0}

local function nbrs4(k)
    local x, y, z = unkey(k)
    return {key(x + 1, y, z), key(x - 1, y, z), key(x, y + 1, z), key(x, y - 1, z)}
end

-- The pieces, as keys: walls, doors, inner doors, traps, statues.
-- doors_present: keys of opening tiles that already have a door (built or
-- planned): they become the gate, and walls go on the rest.
-- Why a line of tiles can't take walls and doors, or nil if it can.
local function line_blocked(list, doors_present)
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local t = nil
        if not doors_present[k] then t = T(x, y, z) end
        if t and not WALL_GROUND[t.shape] then
            return ('the way in at x%d y%d is a %s, which walls and doors can\'t stand on'):format(
                x, y, tostring(t.shape):lower():gsub('_', ' ')), k
        end
        if t and (t.occupied or t.liquid) then
            local seen = what_is_there and what_is_there({x = x, y = y, z = z}) or ('at x%d y%d'):format(x, y)
            local hint = (t.liquid or seen:find('liquid')) and 'water or magma stands there'
                or seen:find('Bridge') and 'a bridge with no lever linked'
                or seen:find('Stockpile') and 'a stockpile the AI could not move'
                or 'something built there'
            return 'something is already in the opening ' .. seen .. ' (' .. hint .. ')', k
        end
    end
    return nil
end

-- The next line in: the inside tiles one step further from the outside.
-- Returns the new line and the outs grown by the old line.
MAX_STEPS_IN = 3
MAX_LINE_IN = 12
local function step_in(list, outs)
    local grown = {}
    for k in pairs(outs) do grown[k] = true end
    for _, k in ipairs(list) do grown[k] = true end
    local line, seen = {}, {}
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if grown[nk] or seen[nk] then return end
                if inside_or_courtyard(T(nx, ny, nz), nk) then
                    seen[nk] = true
                    table.insert(line, nk)
                end
            end)
        end
    end
    table.sort(line)
    return line, grown
end

-- Stairs as the way in, with the outside only straight below them: a hatch
-- on the stair closes the way down. {stair keys} or nil.
local STAIR_DOWN_SHAPES = {STAIR_DOWN = true, STAIR_UPDOWN = true}
local function hatch_spots(e)
    local spots = {}
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if not (t and STAIR_DOWN_SHAPES[t.shape] and not t.occupied and not t.liquid) then return nil end
        -- every outside tile it touches must be on the level below
        local touches, below_only = false, true
        moves(x, y, z, t, function(nx, ny, nz)
            if e.outs[key(nx, ny, nz)] then
                touches = true
                -- straight below only: a ramp beside it below would walk
                -- up onto a closed hatch (a hatch is only a lid)
                if not (nx == x and ny == y and nz == z - 1) then below_only = false end
            end
        end)
        if not (touches and below_only) then return nil end
        table.insert(spots, k)
    end
    return #spots > 0 and spots or nil
end

-- The other way round: stairs whose outside is only straight ABOVE them (a
-- fort's first shaft: the way out is the stair's top on the surface). A
-- hatch on that top stair is a lid on the shaft. {top keys} or nil.
local function hatch_spots_above(e)
    local spots, seen = {}, {}
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if not (t and STAIR_UP[t.shape]) then return nil end
        local touches, above_only = false, true
        moves(x, y, z, t, function(nx, ny, nz)
            if e.outs[key(nx, ny, nz)] then
                touches = true
                if not (nx == x and ny == y and nz == z + 1) then above_only = false end
            end
        end)
        if not (touches and above_only) then return nil end
        local top = T(x, y, z + 1)
        if not (top and STAIR_DOWN_SHAPES[top.shape] and not top.occupied and not top.liquid) then return nil end
        local tk = key(x, y, z + 1)
        if not seen[tk] then
            seen[tk] = true
            table.insert(spots, tk)
        end
    end
    return #spots > 0 and spots or nil
end

---------------------------------------------------------------------------
-- Water in an opening: the AI looks before it acts. investigate_water()
-- follows the water from the opening (on its level and the ones below, up to
-- WATER_SCAN_MAX tiles) and says what it is: how big and deep, natural (a
-- river, brook, pool or the aquifer) or made by dwarves (constructed walls
-- or floors round it, a pump or floodgate in it), and what uses it (a well
-- over it). plan_gate then picks, safest first: a dry line further in; the
-- dry shore around the water, with the water left outside (not if a well or
-- the fort's waterworks use it); or, when only deep water connects the
-- opening to the outside, nothing at all: walkers can't cross deep water, so
-- the water itself is the gate, and the AI notes it rather than asking you.
---------------------------------------------------------------------------

WATER_SCAN_MAX = 3000
DEEP = 4                -- 4/7 and deeper: walkers don't path through it
MAX_SHORE = 16          -- longest shore line the AI walls

local WORKS = {Well = true, ScrewPump = true, Floodgate = true, WaterWheel = true}

function investigate_water(e)
    local start = {}
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then table.insert(start, k) end
    end
    for k in pairs(e.outs) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then table.insert(start, k) end
    end
    if #start == 0 then return nil end
    local W, H = map_size()
    local seen, queue, head = {}, {}, 1
    for _, k in ipairs(start) do if not seen[k] then seen[k] = true; table.insert(queue, k) end end
    local r = {tiles = 0, deep = 0, shallow = 0, max_depth = 0, salt = false, stagnant = false, magma = false,
               aquifer = false, outside = 0, edge = false, materials = {}, levels = {}, rim = 0,
               rim_built = 0, works = {}, wells = 0, truncated = false, region = seen}
    while head <= #queue do
        local k = queue[head]
        head = head + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        r.tiles = r.tiles + 1
        if r.tiles >= WATER_SCAN_MAX then r.truncated = true break end
        local d = t.depth or (t.liquid and 7 or 0)
        if d >= DEEP then r.deep = r.deep + 1 else r.shallow = r.shallow + 1 end
        r.max_depth = math.max(r.max_depth, d)
        r.salt = r.salt or t.salt == true
        r.stagnant = r.stagnant or t.stagnant == true
        r.magma = r.magma or t.magma == true
        r.aquifer = r.aquifer or t.aquifer == true
        if t.outside then r.outside = r.outside + 1 end
        if x <= 0 or y <= 0 or x >= W - 1 or y >= H - 1 then r.edge = true end
        if t.material then r.materials[t.material] = (r.materials[t.material] or 0) + 1 end
        r.levels[z] = true
        local b = building_at(x, y, z)
        if b and WORKS[b] then r.works[b] = (r.works[b] or 0) + 1 end
        -- a well's bucket drops through open levels, and a pump stands over the
        -- water it draws: look up to 6 levels above
        for dz = 1, 6 do
            local above = building_at(x, y, z + dz)
            if above == 'Well' then r.wells = r.wells + 1 break end
            if above == 'ScrewPump' then r.works.ScrewPump = (r.works.ScrewPump or 0) + 1 break end
            local at = T(x, y, z + dz)
            if at and at.shape == 'WALL' then break end
        end
        for dx = -1, 1 do
            for dy = -1, 1 do
                for dz = -1, 0 do
                    if dx ~= 0 or dy ~= 0 or dz ~= 0 then
                        local nk = key(x + dx, y + dy, z + dz)
                        if not seen[nk] then
                            local nt = T(x + dx, y + dy, z + dz)
                            if nt and nt.liquid then
                                seen[nk] = true
                                table.insert(queue, nk)
                            elseif nt and dz == 0 and (dx == 0 or dy == 0) then
                                -- the rim: is it built by dwarves?
                                r.rim = r.rim + 1
                                if nt.material == 'CONSTRUCTION' then r.rim_built = r.rim_built + 1 end
                            end
                        end
                    end
                end
            end
        end
    end
    -- what it is
    -- (what made the water decides the kind; works in it are said separately:
    -- a lake with a floodgate is natural water the dwarves use, not a cistern)
    local m = r.materials
    if r.magma then r.kind = 'magma'
    elseif (m.RIVER or 0) + (m.BROOK or 0) > 0 then r.kind = 'river'
    elseif (r.rim > 0 and r.rim_built * 4 >= r.rim) or (m.CONSTRUCTION or 0) * 4 >= r.tiles then
        r.kind = 'dwarf-made'
    elseif r.aquifer then r.kind = 'aquifer'
    elseif (m.POOL or 0) > 0 or r.outside > 0 or r.tiles >= 500 then r.kind = 'natural water'
    else r.kind = 'standing water' end
    r.natural = r.kind ~= 'dwarf-made'
    -- can walkers get in at all? Block the deep water and walk in from the outside.
    local deep_keys = {}
    for k in pairs(seen) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and (t.depth or 7) >= DEEP then deep_keys[k] = true end
    end
    r.walkers_blocked = next(deep_keys) ~= nil and seals(e.starts or {}, {outs = e.outs}, deep_keys)
    return r
end

-- The investigation in plain words.
function describe_water(r)
    if not r then return 'no water found there' end
    local works = {}
    for kind, n in pairs(r.works) do table.insert(works, ('%d %s'):format(n, kind:lower())) end
    if r.wells > 0 then table.insert(works, ('%d well(s) drawing from it'):format(r.wells)) end
    local lv = 0
    for _ in pairs(r.levels) do lv = lv + 1 end
    local bits = {('%s, %s%d tiles over %d level(s), up to %d/7 deep (%d tiles 4/7 or deeper)'):format(
        r.kind, r.truncated and 'more than ' or '', r.tiles, lv, r.max_depth, r.deep)}
    if r.salt then table.insert(bits, 'salt') end
    if r.stagnant then table.insert(bits, 'stagnant') end
    if r.edge then table.insert(bits, 'runs off the map') end
    if r.rim > 0 then table.insert(bits, ('%d of %d tiles of its edge built by dwarves'):format(r.rim_built, r.rim)) end
    if #works > 0 then table.insert(bits, 'used by ' .. table.concat(works, ', ')) end
    return table.concat(bits, '; ')
end

-- The dry shore round the water, inside the fort: the water (and the
-- opening) left outside. A line plan_line can wall, or nil.
local function shore_line(e, r)
    local outs = {}
    for k in pairs(e.outs) do outs[k] = true end
    for k in pairs(r.region) do outs[k] = true end
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then outs[k] = true end
    end
    local line, seen = {}, {}
    for k in pairs(r.region) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if outs[nk] or seen[nk] then return end
                local nt = T(nx, ny, nz)
                if nt and not nt.liquid and inside_or_courtyard(nt, nk) then
                    seen[nk] = true
                    table.insert(line, nk)
                end
            end)
        end
    end
    table.sort(line)
    return line, outs
end

-- The pieces, as keys: walls, doors, inner doors, traps, statues, support
-- walls (a wall beside a door that has none, so DF will build the door) and
-- hatches. When the opening itself can't take a gate (stairs, water, a
-- building, an unlinked bridge), the gate goes on the first clear line
-- further in (plan.moved_in steps), or a hatch closes stairs whose outside is
-- straight below. doors_present: keys of opening tiles that already have a
-- door (built or planned): they become the gate, and walls go on the rest.
---------------------------------------------------------------------------
-- (0.105.30, construction spec 3.4) The `sealed` style: a cavern opening up
-- to SEALED_MAX_WIDTH tiles walled shut, no door (the Hermit's hold). Only
-- when the fort uses nothing on that cavern layer (no cavern well, no
-- cistern drawing on a cavern lake there), no citizen stands beyond it (in
-- the cavern, in the walk group of its outside tiles, or on the opening),
-- and the walls cut nothing of the fort off (not a tile but the walls'
-- own). The pieces are recorded like any gate's, and clear_gate takes
-- built walls in a cavern opening down again.
---------------------------------------------------------------------------
SEALED_MAX_WIDTH = 3

local function layer_gid(x, y, z)
    local ok, gid = pcall(function()
        local b = dfhack.maps.getTileBlock(xyz2pos(x, y, z))
        return b and b.global_feature
    end)
    return ok and gid or nil
end

-- Why the fort uses this opening's cavern layer, or nil (tests replace this).
function sealed_layer_use(e)
    local out_k = next(e.outs or {})
    if not out_k then return 'its cavern side could not be read' end
    local gid = layer_gid(unkey(out_k))
    if gid == nil or gid < 0 then return 'its cavern layer could not be read' end
    local B
    local okb = pcall(function() B = reqscript('ai-builder') end)
    if not okb or not B then return 'the cavern wells could not be read' end
    local okw, wells = pcall(B.well_lids, false)
    if not okw then return 'the cavern wells could not be read' end
    for _, w in ipairs(wells or {}) do
        local h = type(w.shaft_hatch) == 'table' and w.shaft_hatch or w
        if h.x and layer_gid(h.x, h.y, h.z) == gid then
            return ('cavern well %s draws on that cavern'):format(tostring(w.project_id))
        end
    end
    local okc, d = pcall(B.cistern_data)
    if okc and type(d) == 'table' and type(d.plan) == 'table' then
        local p = d.plan
        if p.source == 'cavern lake' and type(p.water) == 'table' then
            local z = p.water.z or p.intake_z or (p.cistern and p.cistern.z)
            if z and layer_gid(p.water.x, p.water.y, z) == gid then return 'the cistern draws on a lake in that cavern' end
        end
    end
    return nil
end

-- Citizens beyond the opening (tests replace this): standing on the
-- opening; in the cavern, in the walk group of its outside tiles; or
-- (0.105.30 fixes) anywhere inside that the fort's own inside can't reach
-- without crossing the opening: a miner's outpost dug from the cavern is
-- not cavern-flagged, yet walled out all the same. The fort's inside is
-- flooded from the opening's fort side with the opening shut (the gates'
-- own explore); an inside citizen it doesn't reach counts (a keep or
-- tower joined to the fort only over the surface counts too: refused, not
-- risked). Citizens out on the surface don't count, as before.
function citizens_beyond(e)
    cache = cache or {}
    edge_cache = edge_cache or {}
    local groups, on = {}, {}
    for k in pairs(e.outs or {}) do
        local x, y, z = unkey(k)
        local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
        if ok and g and g ~= 0 then groups[g] = true end
    end
    for _, k in ipairs(e.inside_list or {}) do on[k] = true end
    -- the fort's side of the opening, the opening shut
    local seeds = {}
    for _, k in ipairs(e.inside_list or {}) do
        local x, y, z = unkey(k)
        for dx = -1, 1 do
            for dy = -1, 1 do
                local nk = key(x + dx, y + dy, z)
                if not on[nk] and not (e.outs or {})[nk] and interior(T(x + dx, y + dy, z)) then
                    table.insert(seeds, {x = x + dx, y = y + dy, z = z})
                end
            end
        end
    end
    local okf, fort = pcall(explore, seeds, on)
    if not okf then fort = nil end
    local n = 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local p = u.pos
        local k = key(p.x, p.y, p.z)
        if on[k] then
            n = n + 1
        elseif not (fort and fort[k]) then
            local ok, yes = pcall(function()
                local t = T(p.x, p.y, p.z)
                if interior(t) then return true end            -- inside, apart from the fort
                local des = dfhack.maps.getTileFlags(p.x, p.y, p.z)
                if not (des and (des.feature_global or des.feature_local)) then return false end
                local g = dfhack.maps.getWalkableGroup(xyz2pos(p.x, p.y, p.z))
                return g ~= 0 and groups[g] == true
            end)
            if not ok or yes then n = n + 1 end
        end
    end
    return n
end

function plan_sealed(e, starts)
    if e.kind ~= 'cavern' then return nil, 'a sealed gate walls a cavern opening only' end
    local width = #(e.inside_list or {})
    if width == 0 then return nil, 'the opening has no tiles' end
    if width > SEALED_MAX_WIDTH then
        return nil, ('the opening is %d wide: the AI walls cavern openings up to %d'):format(width, SEALED_MAX_WIDTH)
    end
    local why = line_blocked(e.inside_list, {})
    if why then return nil, why end
    local okl, use = pcall(sealed_layer_use, e)
    if not okl then return nil, 'the cavern layer could not be checked' end
    if use then return nil, 'the fort uses that cavern: ' .. use end
    local okc, n = pcall(citizens_beyond, e)
    if not okc then return nil, 'the citizens beyond it could not be counted' end
    if n > 0 then return nil, ('%d citizen%s beyond it (in the cavern, or where the fort can\'t reach but through it)'):format(n, n == 1 and '' or 's') end
    local memo = {}
    local plan, why2 = plan_line(e, 'sealed', starts, {}, memo)
    if not plan then return nil, why2 end
    if #plan.walls ~= width or #plan.doors > 0 then return nil, 'the opening could not be walled whole' end
    -- the cistern's rule: the walls cut nothing of the fort off
    local wall_only = {}
    for _, k in ipairs(plan.walls) do wall_only[k] = true end
    local _, after = explore(starts, wall_only)
    if (memo.before or 0) - after > #plan.walls then
        return nil, ('walls there would cut off %d tiles of the fort'):format(memo.before - after - #plan.walls)
    end
    plan.sealed = true
    return plan
end

function plan_gate(e, style, starts, doors_present)
    if style == 'sealed' then return plan_sealed(e, starts) end         -- (0.105.30)
    doors_present = doors_present or {}
    -- (13c) the fort's size before any wall, flooded once for every line tried
    -- here (each plan_line flooded it again: up to 8 floods of the fort a plan)
    local memo = {}
    local why = line_blocked(e.inside_list, doors_present)
    if not why then return plan_line(e, style, starts, doors_present, memo) end
    cache = cache or {}
    edge_cache = edge_cache or {}
    local hatches, lid = hatch_spots(e), false
    if not hatches then hatches, lid = hatch_spots_above(e), true end
    if hatches then
        local blocked, outs = {}, {}
        for _, k in ipairs(hatches) do blocked[k] = true end
        if lid then
            -- a lid on the outside tiles: nothing gets down through them; the
            -- rest of the opening's outside (if any) must still be shut out
            for k in pairs(e.outs) do if not blocked[k] then outs[k] = true end end
            blocked = {}
        else
            outs = e.outs
        end
        if next(outs) == nil or seals(starts, {outs = outs}, blocked) then
            return {walls = {}, doors = {}, inner = {}, traps = {}, statues = {}, support = {},
                    hatches = hatches, kept_doors = 0}
        end
    end
    local line, outs = e.inside_list, e.outs
    local last
    for step = 1, MAX_STEPS_IN do
        line, outs = step_in(line, outs)
        if #line == 0 or #line > MAX_LINE_IN then break end
        if not line_blocked(line, {}) then
            local ve = {id = e.id, kind = e.kind, inside_list = line, outs = outs, width = #line}
            local plan, why2 = plan_line(ve, style, starts, {}, memo)
            if plan then
                plan.moved_in = step
                plan.moved_why = why
                return plan
            end
            last = why2
        end
    end
    -- water: look at it, then wall its dry shore, or let deep water be the gate
    local water = nil
    for _, k in ipairs(e.inside_list) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t and t.liquid then water = true end
    end
    if water then
        e.starts = starts
        local r = investigate_water(e)
        e.starts = nil
        if r then
            local text = describe_water(r)
            if r.magma then
                return nil, why .. '; the AI looked: ' .. text .. ' (magma is never walled near by the AI)'
            end
            local uses = r.wells > 0 or next(r.works) ~= nil
            if not uses and not r.truncated then
                local shore, outs2 = shore_line(e, r)
                if #shore > 0 and #shore <= MAX_SHORE and not line_blocked(shore, {}) then
                    local ve = {id = e.id, kind = e.kind, inside_list = shore, outs = outs2, width = #shore}
                    local plan = plan_line(ve, style, starts, {}, memo)
                    if plan then
                        plan.shore, plan.water = true, text
                        plan.moved_why = why
                        return plan
                    end
                end
            end
            if r.walkers_blocked then
                -- nothing to build: deep water is the gate (swimmers aside)
                return {walls = {}, doors = {}, inner = {}, traps = {}, statues = {}, support = {},
                        hatches = {}, kept_doors = 0, water_gate = true, water = text}
            end
            return nil, why .. '; the AI looked: ' .. text .. (uses
                and ' (the fort uses this water, so the AI won\'t wall it off)'
                or ' (its dry shore is too long or blocked to wall)')
        end
    end
    local shape_hint = why:find('stair') and ' (a hatch only closes stairs whose way out is straight down)' or ''
    return nil, why .. shape_hint .. ', and no clear line for a gate within ' .. MAX_STEPS_IN
        .. ' tiles further in' .. (last and (': ' .. last) or '')
end

-- A wall beside a door tile that has none (DF builds a door only next to a
-- wall): an inside tile across the way in, not in the line, that walls off
-- nothing of the fort. nil if there's none.
local function support_for(k, in_list, outs, taken, walls_keys)
    local x, y, z = unkey(k)
    -- the way in runs along the axis where an outside tile (for an inner door:
    -- the gate door in front of it) touches the door; the support goes across it
    local axis
    for _, d in ipairs(ORTHO) do
        if outs[key(x + d[1], y + d[2], z)] then axis = d[1] ~= 0 and 'x' or 'y' end
    end
    for _, d in ipairs(ORTHO) do
        local across = (axis == 'x' and d[1] == 0) or (axis == 'y' and d[2] == 0) or axis == nil
        local nk = key(x + d[1], y + d[2], z)
        local t = T(x + d[1], y + d[2], z)
        -- (open space or a ramp top beside it can take a wall too: DF builds
        -- constructions there)
        if across and not in_list[nk] and not outs[nk] and not taken[nk] and t
                and WALL_GROUND[t.shape] and not t.occupied and not t.liquid
                and not t.outside and not t.feature and not t.special and not t.hidden then
            -- the door must still lead on into the fort past the new wall
            -- (checked here locally; the whole fort is checked with the plan)
            local onward = false
            moves(x, y, z, T(x, y, z), function(mx, my, mz)
                local mk = key(mx, my, mz)
                if mk ~= nk and not in_list[mk] and not outs[mk] and not walls_keys[mk]
                        and inside_or_courtyard(T(mx, my, mz), mk) then onward = true end
            end)
            if onward then return nk end
        end
    end
    return nil
end

-- memo (optional, one plan's): keeps the fort's size before walls between calls.
function plan_line(e, style, starts, doors_present, memo)
    local gap_n = GAP[style] or 2
    if style == 'plain' and e.kind == 'cavern' then gap_n = 1 end
    local list = e.inside_list
    -- the gap: the opening tile nearest the middle, grown along the opening
    local sx, sy, n = 0, 0, #list
    for _, k in ipairs(list) do
        local x, y = unkey(k)
        sx, sy = sx + x, sy + y
    end
    local cx, cy = sx / n, sy / n
    local in_list = {}
    for _, k in ipairs(list) do in_list[k] = true end
    local function d2(k) local x, y = unkey(k) return (x - cx) ^ 2 + (y - cy) ^ 2 end
    local first = list[1]
    for _, k in ipairs(list) do if d2(k) < d2(first) then first = k end end
    local gap, in_gap = {first}, {[first] = true}
    if gap_n == 0 then gap, in_gap = {}, {} end        -- (0.105.30) sealed: walls on every tile
    while #gap < gap_n do
        local best
        for _, g in ipairs(gap) do
            for _, nk in ipairs(nbrs4(g)) do
                if in_list[nk] and not in_gap[nk] and (not best or d2(nk) < d2(best)) then best = nk end
            end
        end
        if not best then break end
        table.insert(gap, best)
        in_gap[best] = true
    end
    if next(doors_present) then
        -- the doors already there are the gate: wall the rest around them
        gap, in_gap = {}, {}
        for _, k in ipairs(list) do
            if doors_present[k] then table.insert(gap, k); in_gap[k] = true end
        end
    end
    local walls = {}
    for _, k in ipairs(list) do if not in_gap[k] then table.insert(walls, k) end end
    -- inside the gap: the next tiles in (not the opening, not outside)
    local behind = {}
    for _, g in ipairs(gap) do
        for _, nk in ipairs(nbrs4(g)) do
            local x, y, z = unkey(nk)
            if not in_list[nk] and not e.outs[nk] and interior(T(x, y, z)) then
                table.insert(behind, nk)
                break
            end
        end
    end
    local new_doors = {}
    for _, k in ipairs(gap) do if not doors_present[k] then table.insert(new_doors, k) end end
    local plan = {walls = walls, doors = new_doors, inner = {}, traps = {}, statues = {},
                  support = {}, hatches = {}, kept_doors = #gap - #new_doors}
    if style == 'fortified' or style == 'gatehouse' then plan.inner = behind end
    if (style == 'drawbridge' or style == 'wagon') and #new_doors == #gap and #gap > 0 then
        -- a raising drawbridge over the gap instead of doors (worked by a
        -- lever inside, placed and linked afterwards). It must be a straight
        -- run of tiles, raised toward the outside.
        local x1, y1, x2, y2, z0
        for _, k in ipairs(gap) do
            local x, y, z = unkey(k)
            x1, y1 = math.min(x1 or x, x), math.min(y1 or y, y)
            x2, y2 = math.max(x2 or x, x), math.max(y2 or y, y)
            if z0 and z ~= z0 then x1 = nil break end
            z0 = z
        end
        if x1 and (x2 - x1 + 1) * (y2 - y1 + 1) == #gap then
            local dir = 'gx'
            for _, k in ipairs(gap) do
                local x, y, z = unkey(k)
                if e.outs[key(x, y - 1, z)] then dir = 'gw'
                elseif e.outs[key(x + 1, y, z)] then dir = 'gd'
                elseif e.outs[key(x, y + 1, z)] then dir = 'gx'
                elseif e.outs[key(x - 1, y, z)] then dir = 'ga' end
            end
            plan.bridge = {x = x1, y = y1, z = z0, w = x2 - x1 + 1, h = y2 - y1 + 1, dir = dir, keys = gap}
            plan.doors = {}
            new_doors = {}
        end
    end
    if style == 'wagon' and not plan.bridge then
        -- (0.105.30) the depot's wagon road: doors would shut the wagons out
        return nil, 'the underground depot\'s wagon road takes no door, and a straight 3-wide drawbridge '
            .. 'does not fit across it'
    end
    if style == 'gatehouse' then
        -- cage traps: the tiles just behind the inner doors
        local taken = {}
        for _, k in ipairs(behind) do taken[k] = true end
        for _, b in ipairs(behind) do
            for _, nk in ipairs(nbrs4(b)) do
                local x, y, z = unkey(nk)
                if #plan.traps < 3 and not taken[nk] and not in_list[nk] and interior(T(x, y, z)) then
                    table.insert(plan.traps, nk)
                    taken[nk] = true
                end
            end
        end
    end
    if style == 'grand' then
        -- statues: inside, against the new wall, either side of the gap
        for _, w in ipairs(walls) do
            for _, g in ipairs(gap) do
                local wx, wy = unkey(w)
                local gx, gy = unkey(g)
                if math.abs(wx - gx) + math.abs(wy - gy) == 1 then
                    for _, nk in ipairs(nbrs4(w)) do
                        local x, y, z = unkey(nk)
                        if #plan.statues < 2 and not in_list[nk] and not e.outs[nk] and interior(T(x, y, z)) then
                            table.insert(plan.statues, nk)
                            break
                        end
                    end
                end
            end
        end
    end
    -- doors with no wall beside them (built or in this plan): a support wall
    local walls_keys, taken = {}, {}
    for _, k in ipairs(walls) do walls_keys[k] = true; taken[k] = true end
    for _, k in ipairs(gap) do taken[k] = true end
    for _, k in ipairs(plan.inner) do taken[k] = true end
    for _, k in ipairs(plan.traps) do taken[k] = true end
    for _, k in ipairs(plan.statues) do taken[k] = true end
    local function needs_support(k)
        local x, y, z = unkey(k)
        if wall_beside(x, y, z) then return false end
        for _, nk in ipairs(nbrs4(k)) do if walls_keys[nk] then return false end end
        return true
    end
    local gap_keys = {}
    for _, k in ipairs(gap) do gap_keys[k] = true end
    for i, list2 in ipairs({new_doors, plan.inner}) do
        for _, k in ipairs(list2) do
            if needs_support(k) then
                local sk = support_for(k, in_list, i == 1 and e.outs or gap_keys, taken, walls_keys)
                if sk then
                    table.insert(plan.support, sk)
                    walls_keys[sk], taken[sk] = true, true
                end
            end
        end
    end
    -- checks: the walls and doors seal it; the walls don't cut the fort apart
    local blocked = {}
    for _, k in ipairs(walls) do blocked[k] = true end
    for _, k in ipairs(gap) do blocked[k] = true end
    if not seals(starts, {outs = e.outs}, blocked) then
        return nil, 'walls there would not seal it (the opening is irregular)'
    end
    local wall_only = {}
    for _, k in ipairs(walls) do wall_only[k] = true end
    for _, k in ipairs(plan.support) do wall_only[k] = true end
    memo = memo or {}
    if not memo.before then
        local _, n = explore(starts)
        memo.before = n
    end
    local before = memo.before
    if before >= MAX_TILES then
        return nil, 'the fort is too big for the AI to check that walls there would not cut it apart'
    end
    local _, after = explore(starts, wall_only)
    local n_walls = #walls + #plan.support
    if before - after > n_walls + 30 then
        return nil, ('walls there would cut off %d tiles of the fort'):format(before - after - n_walls)
    end
    return plan
end
