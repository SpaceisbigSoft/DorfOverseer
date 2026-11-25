-- The fort's people and animals, things the AI sets up so the player
-- doesn't have to:
--   * a civilian-alert shelter: a burrow named "AI shelter" covering the
--     inside of the fort (not caverns, not outside), registered as the
--     civilian alert's burrow; (0.105.23) kept away from entrances not shut
--   * grazing animals put into a pasture with room for them (the AI makes
--     new pastures with ai-builder.make_pasture); nest boxes; war animals
--     trained; dogs at the gate; vermin hunters kept
--   * the population cap, and a dwarf sent away
--   * the dwarves' needs: idle crafting, trinkets to own, cups, the stress,
--     clothing and bones counts; the tavern, temple and library staffed
--   * (13c) the recreation, hospital and calm-down burrows are in
--     lua/ai-society-burrows.lua (their names still reachable here)
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

local utils = require('utils')

SHELTER_NAME = 'AI shelter'
-- (r1 g3) a well in the shelter gives water to this many civilians (E: one
-- cavern well, its shaft at times shut, on the level of 80-94: no widening)
SHELTER_CIVS_PER_WELL = 40

local OPEN = {FLOOR = true, STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true,
              RAMP = true, RAMP_TOP = true}

-- The civilian alert's own entry (as DFHack's gui/civ-alert keeps it).
local function civ_alert()
    local list = df.global.plotinfo.alerts.list
    while #list < 2 do
        local item = df.alert_statest:new()
        item.id = df.global.plotinfo.alerts.next_id
        df.global.plotinfo.alerts.next_id = df.global.plotinfo.alerts.next_id + 1
        item.name = 'civ-alert'
        list:insert('#', item)
    end
    return list[1]
end

function alert_has_burrow()
    local ok, n = pcall(function() return #civ_alert().burrows end)
    return ok and n > 0
end

function find_burrow(name)
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if tostring(b.name):lower() == name:lower() then return b end
    end
    return nil
end

function new_burrow(name)
    local b = df.burrow:new()
    b.id = df.global.plotinfo.burrows.next_id
    df.global.plotinfo.burrows.next_id = b.id + 1
    b.name = name
    df.global.plotinfo.burrows.list:insert('#', b)
    return b
end

-- The fort's inside: revealed, walkable tiles that are not outside, not in a
-- cavern or other map feature, and not under water or magma; only on the
-- levels where citizens live (lowest to highest citizen, plus 2).
-- (0.105.8) and every level with a stockpile or a well: B (Monastery, 2 Nov)
-- made its shelter on its first day with 7 dwarves; at 41 the alarm kept
-- everyone on those first levels, away from the stills and the drink, and
-- 31 died of thirst
local function fort_levels()
    local lo, hi
    local function add(z)
        if z and z >= 0 then
            lo = lo and math.min(lo, z) or z
            hi = hi and math.max(hi, z) or z
        end
    end
    for _, u in ipairs(report_citizens(true)) do add(u.pos.z) end
    if not lo then return nil, nil end
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.STOCKPILE) do add(b.z) end
    end)
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.WELL) do add(b.z) end
    end)
    return lo - 2, hi + 2
end

-- (0.105.23) The shelter keeps away from an entrance that can't be shut. A
-- (4-5 Nov): a Hill Titan came in by the founding stair at x108 y149, the
-- fort's only entrance, with no door; the alarm's shelter covered the whole
-- fort, the MeetingHall at x113-120 y146-151 beside the stair with it, and
-- 41 civilians died in that hall, most within seconds of the titan's fire.
-- Now, when the shelter is made, every entrance the gate scan knows that is
-- not shut at that moment (no gate, or a gate open, gone or still to come)
-- keeps the shelter off the tiles within SHELTER_MARGIN of it on its level
-- and SHELTER_MARGIN_Z levels above and below, and off its own stair column
-- (the stairs going on up and down from it, at any depth). A shelter left
-- with fewer than SHELTER_MIN_TILES tiles, or SHELTER_TILES_PER_CITIZEN a
-- citizen, takes back the left-out tiles farthest from those entrances
-- (never nothing), and says so.
SHELTER_MARGIN = 12            -- tiles across, on the entrance's own level
SHELTER_MARGIN_Z = 2           -- levels above and below it
SHELTER_MIN_TILES = 50
SHELTER_TILES_PER_CITIZEN = 2
SHELTER_LEVEL_TILES = 6        -- for "farthest": a level apart counts as this many tiles
local STAIRS = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true}

local function shape_at(x, y, z)
    local ok, s = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        if tt == nil then return nil end
        return df.tiletype_shape[df.tiletype.attrs[tt].shape]
    end)
    return ok and s or nil
end

-- Is the entrance shut now? Every gate of it there and closed (a door or
-- hatch locked, a bridge raised), read from the game; a gate gone (a
-- building destroyer breaks them) or unreadable leaves it open.
-- (0.105.26) Read as ai-gates gate_buildings reads it: a door or hatch on a
-- lever (the gatehouse's, hatch_levers) is shut by DF's `closed`, not the
-- lock (set_lever_door unlocks it), a bridge by `raised`, any other door or
-- hatch by its lock. `live` (gate_buildings' list by id) when it could be
-- read: a gate missing from it is gone. A gate a building destroyer on the
-- map can walk to (`dgroups`, its walk groups) counts as open: it breaks it.
local function gate_shut(g, b, live)
    local l = live and live[g.id]
    if live and not l then return false end
    if g.kind == 'bridge' then return b.gate_flags.raised == true end
    if l and l.closed ~= nil then return l.closed == true end
    if g.lever_driven then return b.door_flags.closed == true end
    return b.door_flags.forbidden == true
end

-- (0.105.26) The walk groups of the building destroyers on the map (nil: none).
function destroyer_groups()
    local groups, any = {}, false
    for _, u in ipairs(report_units()) do
        local ok, yes = pcall(function()
            if not dfhack.units.isActive(u) or dfhack.units.isDead(u) or dfhack.units.isCitizen(u, true) then
                return false
            end
            if u.flags1.caged or u.flags1.chained or not dfhack.units.isDanger(u) then return false end
            local c = df.creature_raw.find(u.race).caste[u.caste]
            return (c.misc.buildingdestroyer or 0) > 0
        end)
        if ok and yes then
            local okg, g = pcall(dfhack.maps.getWalkableGroup, {x = u.pos.x, y = u.pos.y, z = u.pos.z})
            if okg and g and g ~= 0 then groups[g] = true; any = true end
        end
    end
    return any and groups or nil
end

-- (0.105.26) Can one of those walk to the gate (a tile round it, or above
-- and below a hatch, in its walk group)?
local function destroyer_at(b, dgroups)
    if not dgroups then return false end
    local zs = {b.z}
    pcall(function()
        if b:getType() == df.building_type.Hatch then zs = {b.z, b.z + 1, b.z - 1} end
    end)
    for _, z in ipairs(zs) do
        for x = b.x1 - 1, b.x2 + 1 do
            for y = b.y1 - 1, b.y2 + 1 do
                local ok, g = pcall(dfhack.maps.getWalkableGroup, {x = x, y = y, z = z})
                if ok and g and g ~= 0 and dgroups[g] then return true end
            end
        end
    end
    return false
end

-- (0.105.26) gate_buildings' reading by id (nil when ai-gates can't be read)
local function live_gates()
    local ok, list = pcall(function() return reqscript('ai-gates').gate_buildings() end)
    if not ok or type(list) ~= 'table' then return nil end
    local out = {}
    for _, g in ipairs(list) do
        if g.kind ~= 'pending' and g.id ~= nil then out[g.id] = g end
    end
    return out
end

-- (0.105.47, R2 item 7) held only by doors or hatches (no drawbridge in it
-- or in front of it): a building destroyer breaks it
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

local function entrance_shut(e, live, dgroups)
    if not e.sealed or type(e.equipment) ~= 'table' or #e.equipment == 0 then return false end
    -- (0.105.47) a building destroyer on the map: a door or hatch alone holds
    -- nothing, wherever it walks now (C's titans came in by a stair under a
    -- bare hatch while both gates read shut, its walk group cut off by them)
    if dgroups and door_only(e) then return false end
    for _, g in ipairs(e.equipment) do
        local ok, shut = pcall(function()
            local b = df.building.find(g.id)
            if not b then return false end
            if destroyer_at(b, dgroups) then return false end
            return gate_shut(g, b, live)
        end)
        if not ok or not shut then return false end
    end
    return true
end

-- The stair columns going on from an entrance: a stair on its tile or next
-- to it, followed up and down while the stairs go on. {x, y, lo, hi} each.
local function stair_columns(e)
    local out = {}
    for dx = -1, 1 do
        for dy = -1, 1 do
            local x, y = e.x + dx, e.y + dy
            if STAIRS[shape_at(x, y, e.z)] then
                local lo, hi = e.z, e.z
                while e.z - lo < 300 and STAIRS[shape_at(x, y, lo - 1)] do lo = lo - 1 end
                while hi - e.z < 300 and STAIRS[shape_at(x, y, hi + 1)] do hi = hi + 1 end
                table.insert(out, {x = x, y = y, lo = lo, hi = hi})
            end
        end
    end
    return out
end

-- The entrances the shelter keeps away from (the gate scan's, as it stands):
-- a list of {id, kind, x, y, z, why, columns}, and whether the scan was there.
function open_entrances()
    local ok, G = pcall(function() return reqscript('ai-gates').GATES end)
    if not ok or type(G) ~= 'table' or not G.scanned or type(G.entrances) ~= 'table' then return {}, false end
    local out = {}
    local live = live_gates()                                  -- (0.105.26)
    local okd, dgroups = pcall(destroyer_groups)
    dgroups = okd and dgroups or nil
    for _, e in ipairs(G.entrances) do
        local okp = pcall(function() return e.x + e.y + e.z end)
        if okp and not entrance_shut(e, live, dgroups) then
            local why = (not e.sealed or #(e.equipment or {}) == 0)
                and (e.closing and 'its gate still to come' or 'no gate') or 'its gate open or lost'
            local okc, cols = pcall(stair_columns, e)
            table.insert(out, {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z, why = why,
                               columns = okc and cols or {}})
        end
    end
    return out, true
end

-- How far a tile is from the open entrances (nil: not near any), and whether
-- it is near one (in the margin, or on its stair column).
local function near_entrance(list, x, y, z)
    local best, near = nil, false
    for _, e in ipairs(list) do
        local dz = math.abs(z - e.z)
        local d = math.max(math.abs(x - e.x), math.abs(y - e.y))
        if dz <= SHELTER_MARGIN_Z and d <= SHELTER_MARGIN then near = true end
        local far = d + SHELTER_LEVEL_TILES * dz
        for _, c in ipairs(e.columns) do
            if x == c.x and y == c.y and z >= c.lo and z <= c.hi then near, far = true, 0 end
        end
        if not best or far < best then best = far end
    end
    return near, best
end

-- The open entrances that could touch this block (its levels and its 16x16).
local function entrances_for_block(list, bx, by, z)
    local out
    for _, e in ipairs(list) do
        local hit = math.abs(z - e.z) <= SHELTER_MARGIN_Z
            and e.x >= bx - SHELTER_MARGIN and e.x <= bx + 15 + SHELTER_MARGIN
            and e.y >= by - SHELTER_MARGIN and e.y <= by + 15 + SHELTER_MARGIN
        if not hit then
            for _, c in ipairs(e.columns) do
                if c.x >= bx and c.x <= bx + 15 and c.y >= by and c.y <= by + 15 and z >= c.lo and z <= c.hi then
                    hit = true
                end
            end
        end
        if hit then out = out or {}; table.insert(out, e) end
    end
    return out
end

-- (0.105.26) The Deep mine's underground depot hall and its road (ai-builder-
-- surface's deep depot): open to the surface for the wagons, never shelter.
-- A set of "x,y,z" keys, and how many.
local function deep_depot_tiles()
    local ok, d = pcall(function() return reqscript('ai-builder').deep_depot_data() end)
    if not ok or type(d) ~= 'table' then return nil, 0 end
    local out, n = {}, 0
    local function add(x, y, z)
        local k = x .. ',' .. y .. ',' .. z
        if not out[k] then out[k] = true; n = n + 1 end
    end
    for _, p in ipairs(d.tiles or {}) do
        pcall(function() add(math.tointeger(p.x) or p.x, math.tointeger(p.y) or p.y, math.tointeger(p.z) or p.z) end)
    end
    local h = d.hall
    if type(h) == 'table' and h.x1 and h.x2 and h.y1 and h.y2 and h.z then
        for x = h.x1 - 1, h.x2 + 1 do          -- the hall and the ring round it
            for y = h.y1 - 1, h.y2 + 1 do add(x, y, h.z) end
        end
    end
    if n == 0 then return nil, 0 end
    return out, n
end

-- (0.105.26) Where drink and water are: "x,y,z" -> 'drink' or 'well'.
-- Drink: the tiles where (not forbidden) drink lies, in a pile's barrel or
-- loose; a well: one built (and, when ai-society-burrows can tell, giving
-- water). SHELTER_DRINK_SCAN drinks looked at at most.
-- (0.105.33) Also returns the drink units on each tile ("x,y,z" -> units),
-- the wells as a list {x, y, z} (a well stands on its channelled hole, a tile
-- of shape EMPTY that the inside scan never takes: they are added apart),
-- and the food units on each tile.
SHELTER_DRINK_SCAN = 4000
local function item_spots(list, out, units)
    local n = 0
    for _, it in ipairs(list) do
        n = n + 1
        if n > SHELTER_DRINK_SCAN then break end
        local ok, pos = pcall(function()
            if it.flags.forbid or it.flags.garbage_collect or it.flags.rotten then return nil end
            -- (0.105.33 fix) DF sets in_inventory on what lies in a barrel or
            -- bin too: only what a unit carries is skipped (U.item_unfree's
            -- rule), and what lies in a forbidden or carried container
            if it.flags.in_inventory then
                local okh, u = pcall(dfhack.items.getHolderUnit, it)
                if okh and u ~= nil then return nil end
            end
            local c = dfhack.items.getContainer and dfhack.items.getContainer(it)
            if c then
                if c.flags.forbid then return nil end
                local okh, u = pcall(dfhack.items.getHolderUnit, c)
                if c.flags.in_inventory and okh and u ~= nil then return nil end
            end
            local x, y, z = dfhack.items.getPosition(it)
            if type(x) == 'table' then return x end
            if x and x >= 0 then return {x = x, y = y, z = z} end
            return nil
        end)
        if ok and pos then
            local k = pos.x .. ',' .. pos.y .. ',' .. pos.z
            if out then out[k] = 'drink' end
            local st = 1
            pcall(function() if type(it.stack_size) == 'number' and it.stack_size > 0 then st = it.stack_size end end)
            units[k] = (units[k] or 0) + st
        end
    end
end

-- (r1 g3) the walk groups the citizens stand in (nil when the game can't say:
-- then every well giving water counts), and whether a well is reached from one
local function citizen_groups()
    local gs, any = {}, false
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(u.pos.x, u.pos.y, u.pos.z))
            if ok and type(g) == 'number' and g ~= 0 then gs[g] = true; any = true end
        end
    end)
    return any and gs or nil
end

local function well_reached(b, gs)
    if not gs then return true end
    for dy = -1, 1 do
        for dx = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(b.centerx + dx, b.centery + dy, b.z))
                if ok and type(g) == 'number' and g ~= 0 and gs[g] then return true end
            end
        end
    end
    return false
end

local function drink_and_wells()
    local out, units, wells, food = {}, {}, {}, {}
    pcall(function() item_spots(df.global.world.items.other.DRINK, out, units) end)
    -- food: the good food (meals among it), else the meals alone (pcall: an
    -- id this DF lacks)
    for _, id in ipairs({'ANY_GOOD_FOOD', 'FOOD'}) do
        local okf, list = pcall(function() return df.global.world.items.other[id] end)
        if okf and list then
            pcall(item_spots, list, nil, food)
            break
        end
    end
    pcall(function()
        local okb, B = pcall(reqscript, 'ai-society-burrows')
        local gs = citizen_groups()
        for _, b in ipairs(df.global.world.buildings.other.WELL) do
            -- (r1 g3) a well counts only when it serves: built, its shaft open
            -- and its water liquid (well_gives_water: no shut hatch, no ice, not
            -- dry), and a citizen can walk to it (a well the game can't read
            -- still counts, as before)
            local ok, good = pcall(function()
                if b:getBuildStage() < b:getMaxBuildStage() then return false end
                if okb and B and B.well_gives_water and B.well_gives_water(b) == false then return false end
                return well_reached(b, gs)
            end)
            if not ok or good then
                out[b.centerx .. ',' .. b.centery .. ',' .. b.z] = 'well'
                table.insert(wells, {x = b.centerx, y = b.centery, z = b.z})
            end
        end
    end)
    return out, units, wells, food
end

-- (0.105.45) for lua/ai-shelter-plan.lua: the drink, wells and food (as
-- drink_and_wells), and the fort's levels (as fort_levels)
function shelter_supplies() return drink_and_wells() end
function shelter_level_range() return fort_levels() end

-- (0.105.45) the levels the AI picked for the shelter, away from the threat's
-- way in (ai-shelter-plan pick_levels: a set of z), or nil for the whole fort
local function picked_levels()
    local ok, only = pcall(function() return reqscript('ai-shelter-plan').pick_levels() end)
    return ok and only or nil
end

SHELTER_OPEN_KEY = 'ai-overseer/shelter_open'       -- (0.105.26) the entrances open when it was made
SHELTER_DRINK_BACK = 30                             -- drink tiles taken back at most
SHELTER_DRINK_PER_CITIZEN = 2                       -- (0.105.33) drink units a citizen, short of a well
SHELTER_FOOD_PER_CITIZEN = 2                        -- (0.105.33) food units a citizen
SHELTER_FOOD_BACK = 30                              -- food tiles taken back at most

local function entrance_keys(list)
    local keys = {}
    for _, e in ipairs(list or {}) do table.insert(keys, e.x .. ',' .. e.y .. ',' .. e.z) end
    table.sort(keys)
    return keys
end

-- (0.105.30 fixes) The AI's own surface hall and keep (site data 'ai-
-- overseer/halls' and 'ai-overseer/keep'): their boxes (walls, inside, the
-- level above for the roof stair), never shelter whatever else happens. A
-- set of "x,y,z" keys, or nil.
local function ai_surface_boxes()
    local ok, B = pcall(reqscript, 'ai-builder')
    if not ok or type(B) ~= 'table' then return nil end
    local out, any = {}, false
    local function box(x1, y1, x2, y2, z)
        for zz = z, z + 1 do
            for x = x1, x2 do
                for y = y1, y2 do out[x .. ',' .. y .. ',' .. zz] = true end
            end
        end
        any = true
    end
    pcall(function()
        local k = B.keep_data and B.keep_data()
        if type(k) == 'table' and k.x and k.y and k.z and k.r then
            box(k.x - k.r, k.y - k.r, k.x + k.r, k.y + k.r, k.z)
        end
    end)
    pcall(function()
        local d = B.halls_data and B.halls_data()
        for _, h in ipairs(type(d) == 'table' and d.list or {}) do
            pcall(function()
                if h.x1 and h.y1 and h.x2 and h.y2 and h.z then box(h.x1, h.y1, h.x2, h.y2, h.z) end
            end)
        end
    end)
    return any and out or nil
end

-- Fills the burrow; returns the tiles in it and what was left out:
-- {excluded, open_entrances, entrances_scanned, fallback, note, why,
-- drink_tiles, well_tiles, deep_depot_tiles, drink_back, surface_out,
-- surface_back, surface_mode, ai_hall_tiles, short}.
--
-- (0.105.30 fixes) The roofed surface. DF's `subterranean` flag is not
-- reliable on a fort's top levels: a dark level under a hill can read as
-- not subterranean, and a fort can read as all not subterranean. The rule:
--   * a sunlit tile (inside, not subterranean, lit) is the roofed surface
--     (a keep's court, a tree's shade): never shelter;
--   * the AI's own hall and keep boxes: never shelter (above);
--   * a dark not-subterranean tile is taken as the fort itself (0.105.29's
--     shelter: the entrances' margins still apply) whenever those tiles
--     are most of the inside, or leaving them out would leave the shelter
--     short. Otherwise (a few stray dark ones) they stay out, the whole
--     lot at once: all or none, so the shelter stays one piece rather
--     than a scatter.
--   * drink and wells: with neither inside, the left-out drink and well
--     tiles come back from the margins and from the not-subterranean ones
--     (dark first, sunlit only when there is nothing else; never the
--     AI's hall or keep), farthest from the open entrances first.
-- (0.105.45) only: a set of z levels (the AI's pick away from the threat):
-- the shelter is drawn over those levels alone; nil: the whole fort.
function fill_shelter(b, only)
    local info = {excluded = 0, margin = SHELTER_MARGIN, margin_levels = SHELTER_MARGIN_Z}
    local lo, hi = fort_levels()
    if not lo then return 0, info end
    if only then
        info.levels = {}
        for z in pairs(only) do
            lo, hi = math.min(lo, z), math.max(hi, z)
            table.insert(info.levels, z)
        end
        table.sort(info.levels)
    end
    local okl, open, scanned = pcall(open_entrances)
    if not okl then open, scanned, info.entrances_error = {}, false, tostring(open):sub(1, 120) end
    info.entrances_scanned = scanned
    info.open_entrances = #open
    pcall(function() U.site_put(SHELTER_OPEN_KEY, {keys = entrance_keys(open), scanned = scanned and true or false}) end)
    local deep, deep_n = deep_depot_tiles()                  -- (0.105.26)
    local okw, water, dunits, wells, food = pcall(drink_and_wells)
    if not okw then water = nil end
    water, dunits, wells, food = water or {}, dunits or {}, wells or {}, food or {}
    local okh, ai_box = pcall(ai_surface_boxes)
    ai_box = okh and ai_box or nil
    local drink_tiles, well_tiles, deep_out, ai_out = 0, 0, 0, 0
    local drink_units, food_units, food_tiles = 0, 0, 0
    local n = 0
    -- (0.105.33) each well's own tile and its 8 neighbours: "x,y,z" -> wells
    local wkey, blocks = {}, {}
    for _, w in ipairs(wells) do
        w.members = {}
        for dy = -1, 1 do
            for dx = -1, 1 do
                local k = (w.x + dx) .. ',' .. (w.y + dy) .. ',' .. w.z
                wkey[k] = wkey[k] or {}
                table.insert(wkey[k], w)
            end
        end
    end
    -- the tiles left out: {block, x, y, far, kind, light, surface}
    local held = {}          -- near an open entrance
    local dark_surface = {}  -- (0.105.30) inside, not subterranean, dark: {.., near}
    local sunlit = {}        -- inside, not subterranean, sunlit
    local function take(t)
        dfhack.burrows.setAssignedBlockTile(b, t[1], t[2], t[3], true)
        t.taken = true
        n = n + 1
        if t[5] == 'drink' then
            drink_tiles = drink_tiles + 1
            drink_units = drink_units + (dunits[t.k] or 1)
        end
        if food[t.k] then
            food_tiles = food_tiles + 1
            food_units = food_units + food[t.k]
        end
    end
    -- (0.105.33) L6: a well stands on its channelled hole (shape EMPTY), so
    -- the scan never takes the well's own tile, the one DF checks. A well
    -- with a neighbour in the shelter gets its own tile too; `all` (a well
    -- taken back) takes its neighbours as well.
    local function take_well(w, all)
        if w.taken then return end
        if all then
            for _, m in ipairs(w.members) do if not m.taken then take(m) end end
        end
        if not w.self_taken then
            for _, m in ipairs(w.members) do
                if m[1].map_pos.x + m[2] == w.x and m[1].map_pos.y + m[3] == w.y then
                    if not m.taken then take(m) end
                    w.self_taken = true
                end
            end
        end
        if not w.self_taken then
            local blk = blocks[(w.x - w.x % 16) .. ',' .. (w.y - w.y % 16) .. ',' .. w.z]
            if blk then
                dfhack.burrows.setAssignedBlockTile(b, blk, w.x % 16, w.y % 16, true)
                n = n + 1
                w.self_taken = true
            end
        end
        if w.self_taken then
            w.taken = true
            well_tiles = well_tiles + 1
        end
    end
    local function wells_inside()
        for _, w in ipairs(wells) do
            if not w.taken then
                for _, m in ipairs(w.members) do
                    if m.taken then take_well(w, false); break end
                end
            end
        end
    end
    for _, block in ipairs(df.global.world.map.map_blocks) do
        local z = block.map_pos.z
        if z >= lo and z <= hi and (not only or only[z]) then
            local bx, by = block.map_pos.x or 0, block.map_pos.y or 0
            blocks[bx .. ',' .. by .. ',' .. z] = block
            local near_list = #open > 0 and entrances_for_block(open, bx, by, z) or nil
            for x = 0, 15 do
                for y = 0, 15 do
                    local d = block.designation[x][y]
                    if not d.hidden and not d.outside and not d.feature_local and not d.feature_global
                            and d.flow_size == 0 then
                        local tt = block.tiletype[x][y]
                        local shape = df.tiletype_shape[df.tiletype.attrs[tt].shape]
                        local k = (bx + x) .. ',' .. (by + y) .. ',' .. z
                        if OPEN[shape] and deep and deep[k] then
                            deep_out = deep_out + 1
                        elseif OPEN[shape] and ai_box and ai_box[k] then
                            ai_out = ai_out + 1
                        elseif OPEN[shape] then
                            local near, far = false, nil
                            if near_list then near = near_entrance(near_list, bx + x, by + y, z) end
                            if near then
                                -- how far, from every open entrance (for the fallback)
                                if #open > #near_list then
                                    far = select(2, near_entrance(open, bx + x, by + y, z))
                                else
                                    far = select(2, near_entrance(near_list, bx + x, by + y, z))
                                end
                            elseif #open > 0 and d.subterranean == false then
                                far = select(2, near_entrance(open, bx + x, by + y, z))
                            end
                            local t = {block, x, y, far or 0, water[k] == 'drink' and 'drink' or nil, d.light == true}
                            t.k = k
                            for _, w in ipairs(wkey[k] or {}) do table.insert(w.members, t) end
                            if d.subterranean == false then
                                t.surface, t.near = true, near and true or false
                                table.insert(t[6] and sunlit or dark_surface, t)
                            elseif near then
                                table.insert(held, t)
                            else
                                take(t)
                            end
                        end
                    end
                end
            end
        end
    end
    if deep_out > 0 then info.deep_depot_tiles = deep_out end
    if ai_out > 0 then info.ai_hall_tiles = ai_out end
    local okc, cits = pcall(function() return #report_citizens(true) end)
    local need = math.max(SHELTER_MIN_TILES, SHELTER_TILES_PER_CITIZEN * (okc and cits or 0))
    -- the dark not-subterranean tiles: the fort itself, or left out (above)
    local inside = n + #held + #dark_surface + #sunlit
    local surface_back = 0
    if #dark_surface > 0 then
        local most = (#dark_surface + #sunlit) * 2 > inside
        local short = n < need
        if most or short then
            for _, t in ipairs(dark_surface) do
                if t.near then table.insert(held, t) else take(t); surface_back = surface_back + 1 end
            end
            info.surface_mode = most and 'unflagged' or 'short'
            info.surface_note = most
                and ('%d of %d inside tiles read as not subterranean: the dark ones taken as the fort (only the %d sunlit left out)')
                    :format(#dark_surface + #sunlit, inside, #sunlit)
                or ('only %d tiles under rock (needs %d): the %d dark not-subterranean tiles taken as the fort, the %d sunlit ones not')
                    :format(n - surface_back, need, #dark_surface, #sunlit)
            dark_surface = {}
        end
    end
    -- (0.105.26) B (2 Nov) and A: a shelter with no drink nor well in it
    -- killed by thirst. Neither inside: the left-out drink and well tiles
    -- farthest from the open entrances come back first (a well, and up to
    -- SHELTER_DRINK_BACK drink tiles); (0.105.30 fixes) from the margins and
    -- the dark not-subterranean tiles alike, the sunlit ones last.
    -- (0.105.33) L6: and with too little: a mug is not drink for forty. Under
    -- SHELTER_DRINK_PER_CITIZEN units a citizen and no well, the same.
    wells_inside()
    local okc0, cits0 = pcall(function() return #report_citizens(true) end)
    cits0 = okc0 and cits0 or 0
    local want_drink = math.max(1, SHELTER_DRINK_PER_CITIZEN * cits0)
    local want_food = math.max(1, SHELTER_FOOD_PER_CITIZEN * cits0)
    -- (r1 g3) water enough: the drink, and each well for SHELTER_CIVS_PER_WELL
    -- civilians (a well for any number was water enough before)
    local function watered()
        return well_tiles * SHELTER_CIVS_PER_WELL * SHELTER_DRINK_PER_CITIZEN + drink_units >= want_drink
    end
    local back = 0
    if not watered() then
        local cand = {}
        for _, list in ipairs({held, dark_surface, sunlit}) do
            for _, t in ipairs(list) do
                if t[5] == 'drink' and not t.taken then table.insert(cand, t) end
            end
        end
        for _, w in ipairs(wells) do
            if not w.taken and #w.members > 0 then
                local far, light = nil, true
                for _, m in ipairs(w.members) do
                    if far == nil or m[4] < far then far = m[4] end
                    if not m[6] then light = false end
                end
                table.insert(cand, {nil, nil, nil, far or 0, 'well', light, well = w})
            end
        end
        table.sort(cand, function(a, c)
            if a[6] ~= c[6] then return not a[6] end
            if a[5] ~= c[5] then return a[5] == 'drink' end
            return a[4] > c[4]
        end)
        for _, t in ipairs(cand) do
            -- (a sunlit one only when nothing in the dark gave drink or a well)
            if t[6] and drink_tiles + well_tiles > 0 then break end
            if t[5] == 'drink' and drink_tiles < SHELTER_DRINK_BACK and drink_units < want_drink then
                take(t); back = back + 1
            elseif t[5] == 'well' and not watered() then
                take_well(t.well, true)
                if t.well.taken then back = back + 1 end
            end
            if watered() then break end
        end
        if back > 0 then
            info.drink_back = back
            info.drink_note = ('no drink nor well away from the open entrances and the surface: %d drink and well tile%s taken back')
                :format(back, back == 1 and '' or 's')
        end
    end
    -- (0.105.33) food the same way: under SHELTER_FOOD_PER_CITIZEN units a
    -- citizen, the left-out food tiles come back, dark and far first
    if food_units < want_food then
        local cand = {}
        for _, list in ipairs({held, dark_surface, sunlit}) do
            for _, t in ipairs(list) do
                if food[t.k] and not t.taken then table.insert(cand, t) end
            end
        end
        table.sort(cand, function(a, c)
            if a[6] ~= c[6] then return not a[6] end
            return a[4] > c[4]
        end)
        local fb = 0
        for _, t in ipairs(cand) do
            if t[6] and food_units > 0 then break end
            if fb >= SHELTER_FOOD_BACK or food_units >= want_food then break end
            take(t); fb = fb + 1
        end
        if fb > 0 then
            info.food_back = fb
            info.food_note = ('too little food away from the open entrances and the surface: %d food tile%s taken back')
                :format(fb, fb == 1 and '' or 's')
        end
    end
    local rest = {}
    for _, t in ipairs(held) do if not t.taken then table.insert(rest, t) end end
    held = rest
    info.excluded = #held
    if #held > 0 then
        local where = {}
        for i, e in ipairs(open) do
            if i <= 4 then
                table.insert(where, ('x%d y%d z%d (%s, %s)'):format(e.x, e.y, e.z, tostring(e.kind), e.why))
            end
        end
        info.why = ('%d tiles left out: within %d tiles (and %d levels) of, or on the stairs of, %d entrance%s not shut: %s')
            :format(#held, SHELTER_MARGIN, SHELTER_MARGIN_Z, #open, #open == 1 and '' or 's',
                    table.concat(where, '; ') .. (#open > 4 and '; ...' or ''))
        if n < need then
            -- too few away from them: the farthest of the left-out tiles back
            table.sort(held, function(a, c) return a[4] > c[4] end)
            local fb = 0
            for _, t in ipairs(held) do
                if n >= need then break end
                take(t)
                fb = fb + 1
                if t.surface then surface_back = surface_back + 1 end
            end
            info.excluded = #held - fb
            info.fallback = true
            info.taken_back = fb
            info.note = ('only %d tiles away from the open entrances (needs %d): the %d farthest of the left-out tiles taken back')
                :format(n - fb, need, fb)
        end
    end
    local surface_out = 0
    for _, list in ipairs({dark_surface, sunlit}) do
        for _, t in ipairs(list) do
            if t.taken then surface_back = surface_back + 1 else surface_out = surface_out + 1 end
        end
    end
    if surface_out > 0 or surface_back > 0 then info.surface_out = surface_out end
    if surface_back > 0 then info.surface_back = surface_back end
    wells_inside()                -- (a well beside the tiles taken back above)
    if n < need then info.short = ('the shelter holds %d tiles (needs %d): the sunlit surface and the AI\'s hall and keep stay out'):format(n, need) end
    info.drink_tiles, info.well_tiles = drink_tiles, well_tiles
    info.drink_units, info.food_units, info.food_tiles = drink_units, food_units, food_tiles
    if drink_tiles + well_tiles == 0 then
        info.no_water = 'the shelter holds no drink and no well'
    elseif well_tiles == 0 and drink_units < want_drink then
        info.drink_short = ('the shelter holds %d drink for %d citizens and no well'):format(drink_units, cits0)
    elseif not watered() then
        info.drink_short = ('the shelter holds %d drink and %d well(s) for %d citizens (a well for every %d)')
            :format(drink_units, well_tiles, cits0, SHELTER_CIVS_PER_WELL)
    end
    info.civs = cits0
    if not watered() then info.water_short = true end
    if food_units == 0 then
        info.no_food = 'the shelter holds no food'
    end
    -- (0.105.47, J1) a gathering strange mood's workshop and the items it
    -- still needs go in too: I7a, five moods cancelled "Forbidden area" when
    -- the AI's alarm kept the dwarf from them (lua/ai-mood-help.lua)
    pcall(function()
        local r = reqscript('ai-mood-help').add_mood_spots(b, false)
        if r and (r.added or 0) > 0 then n = n + r.added; info.mood_tiles = r.added end
    end)
    return n, info
end

-- (0.105.26) Entrances open now that were shut (or not yet known) when the
-- AI's shelter was made: a gate lost (broken, or a building destroyer at
-- it) while the alarm is on. How many (0: none, or the shelter isn't the
-- AI's on an alarm sounding).
function shelter_stale()
    local okc, on = pcall(function() return df.global.plotinfo.alerts.civ_alert_idx ~= 0 end)
    if not (okc and on) then return 0 end
    local b = find_burrow(SHELTER_NAME)
    if not b then return 0 end
    local mine = false
    pcall(function()
        for _, id in ipairs(civ_alert().burrows) do if id == b.id then mine = true end end
    end)
    if not mine then return 0 end
    local saved = U.site_get(SHELTER_OPEN_KEY, {})
    if type(saved) ~= 'table' or type(saved.keys) ~= 'table' then return 0 end
    local was = {}
    for _, k in ipairs(saved.keys) do was[k] = true end
    local okl, open, scanned = pcall(open_entrances)
    if not okl or not scanned then return 0 end
    local n = 0
    for _, k in ipairs(entrance_keys(open)) do if not was[k] then n = n + 1 end end
    return n
end

-- (0.105.23) what the shelter left out near open entrances, in an action's result
function shelter_result(r, info)
    if type(info) ~= 'table' then return r end
    r.excluded_tiles = info.excluded
    r.open_entrances = info.open_entrances
    if info.entrances_scanned == false then r.entrances_scanned = false end
    r.entrances_error = info.entrances_error
    r.excluded_why = info.why
    r.fallback = info.fallback
    r.taken_back = info.taken_back
    r.note = info.note
    r.drink_tiles, r.well_tiles = info.drink_tiles, info.well_tiles      -- (0.105.26)
    r.drink_back, r.drink_note, r.no_water = info.drink_back, info.drink_note, info.no_water
    r.drink_units, r.drink_short = info.drink_units, info.drink_short                     -- (0.105.33)
    r.water_short, r.civs = info.water_short, info.civs                                   -- (r1 g3)
    r.food_units, r.food_tiles, r.food_back = info.food_units, info.food_tiles, info.food_back
    r.food_note, r.no_food = info.food_note, info.no_food
    r.deep_depot_tiles = info.deep_depot_tiles
    r.surface_out, r.surface_back, r.surface_note = info.surface_out, info.surface_back, info.surface_note   -- (0.105.30)
    r.surface_mode, r.ai_hall_tiles, r.short = info.surface_mode, info.ai_hall_tiles, info.short
    r.levels = info.levels                                   -- (0.105.45) the AI's pick, when there is one
    r.mood_tiles = info.mood_tiles                           -- (0.105.47, J1) a strange mood's tiles added
    return r
end

-- (item4) when the shelter was last drawn: an alarm sounded again within
-- SHELTER_REDRAW_TICKS uses it as it is (the alarm flapped 150 times a run
-- in C and F, the shelter drawn afresh each time); a gate lost while the
-- alarm is on still redraws it (refresh_shelter, the planner's shelter_stale)
SHELTER_DRAWN_KEY = 'ai-overseer/shelter-drawn'
SHELTER_REDRAW_TICKS = 1200

-- (0.105.48, K3) and what it held: its tiles, no drink at all, drink short
local function shelter_drawn(n, info)
    if n and n > 0 then
        pcall(function()
            local i = type(info) == 'table' and info or {}
            U.site_put(SHELTER_DRAWN_KEY, {tick = U.abs_tick(), tiles = n, no_water = i.no_water and true or nil,
                                           drink_short = i.drink_short and true or nil})
        end)
    end
end

-- (0.105.48, K3) The AI shelter's burrow as the evil-weather keep-in needs
-- it: drawn again (over the fort as it is now, and the AI's pick) unless
-- drawn within SHELTER_REDRAW_TICKS with what it held known (force: always,
-- the first keep-in of a spell); the keep-in used the shelter as last drawn,
-- maybe days before, with no look at its drink (A7: the shape of B's thirst
-- deaths). {tiles, no_water, drink_short, redrawn}; nil: no AI shelter.
function shelter_for_keep_in(force)
    local b = find_burrow(SHELTER_NAME)
    if not b then return nil end
    if not force then
        local last = U.site_get(SHELTER_DRAWN_KEY, {})
        local t = type(last) == 'table' and tonumber(last.tick) or nil
        local okn, now = pcall(U.abs_tick)
        local okb, blocks = pcall(function() return #dfhack.burrows.listBlocks(b) end)
        if t and okn and now and now >= t and now - t < SHELTER_REDRAW_TICKS and okb and blocks > 0
                and tonumber(last.tiles) then
            return {tiles = tonumber(last.tiles), no_water = last.no_water or nil,
                    drink_short = last.drink_short or nil, redrawn = false}
        end
    end
    -- (r9) the tiles before, put back when the redraw finds none or fails
    -- (the shelter is the alarm's burrow too)
    local snap = shelter_snapshot(b)
    local okd, n, info = pcall(function()
        dfhack.burrows.clearTiles(b)
        return fill_shelter(b, picked_levels())
    end)
    if not okd or (tonumber(n) or 0) == 0 then
        shelter_restore(b, snap)
        if not okd then error(n, 0) end
        return {tiles = 0, redrawn = false}
    end
    local okc, cut_tiles = pcall(cover_cut_off, b)            -- (0.105.52)
    if okc and tonumber(cut_tiles) then n = (n or 0) + cut_tiles end
    shelter_drawn(n, info)
    info = type(info) == 'table' and info or {}
    return {tiles = n or 0, no_water = info.no_water and true or nil, drink_short = info.drink_short and true or nil,
            redrawn = true}
end

-- The shelter drawn again before an alarm unless drawn within the last
-- SHELTER_REDRAW_TICKS (and still covering tiles); force: always.
function refresh_shelter_due(force)
    if not force then
        local last = U.site_get(SHELTER_DRAWN_KEY, {})
        local t = type(last) == 'table' and tonumber(last.tick) or nil
        local okn, now = pcall(U.abs_tick)
        if not okn then now = nil end
        local b = find_burrow(SHELTER_NAME)
        local okb, blocks = pcall(function() return #dfhack.burrows.listBlocks(b) end)
        if t and now and b and okb and blocks > 0 and now >= t and now - t < SHELTER_REDRAW_TICKS then
            -- (0.105.47, J1) not drawn again, but a mood that began since gets its tiles
            local okm, mr = pcall(function() return reqscript('ai-mood-help').add_mood_spots(b, false) end)
            return {refreshed = false, drawn_ticks_ago = now - t,
                    mood_tiles = okm and mr and (mr.added or 0) > 0 and mr.added or nil}
        end
    end
    return refresh_shelter()
end

-- Make (or refresh) the "AI shelter" burrow and make it the civilian alert's.
function setup_shelter()
    if alert_has_burrow() then
        return {ok = false, rejected = true, error = 'the civilian alert already has a burrow'}
    end
    local b = find_burrow(SHELTER_NAME) or new_burrow(SHELTER_NAME)
    dfhack.burrows.clearTiles(b)
    local n, info = fill_shelter(b, picked_levels())        -- (0.105.45)
    if n == 0 then
        return {ok = false, error = 'found no inside tiles to shelter in'}
    end
    local okc, cut_tiles, cut_people = pcall(cover_cut_off, b)      -- (0.105.52)
    if okc and tonumber(cut_tiles) then n = n + cut_tiles end
    require('utils').insert_sorted(civ_alert().burrows, b.id)
    shelter_drawn(n, info)
    local r = shelter_result({ok = true, burrow_id = b.id, tiles = n}, info)
    if okc and (cut_people or 0) > 0 then r.cut_off_covered = cut_people end
    return r
end

-- (0.105.8) The AI's shelter made again over the fort as it is now, when it
-- is the civilian alert's burrow (a player's own is never touched): before
-- each alarm the AI sounds. {refreshed, tiles, before} or nil.
-- (0.105.52) A citizen who can't walk to any tile of the AI shelter gets a
-- patch of it where they stand (their own walk group, within CUT_OFF_RADIUS on
-- their level): DF sends every citizen to the alarm's burrow, and one who
-- can't reach it fails a whole-map path search every few ticks, which brought
-- R3's B to 2 FPS (25,000 "Milling Burrow" path fails in DF's errorlog). One
-- patch per cut-off walk group. Returns tiles added, citizens covered.
CUT_OFF_RADIUS = 8
function cover_cut_off(b)
    local groups, any = {}, false
    local ok = pcall(function()
        for _, blk in ipairs(dfhack.burrows.listBlocks(b)) do
            local bx, by, bz = blk.map_pos.x, blk.map_pos.y, blk.map_pos.z
            for y = 0, 15 do
                for x = 0, 15 do
                    if dfhack.burrows.isAssignedBlockTile(b, blk, x, y) then
                        local g = dfhack.maps.getWalkableGroup(xyz2pos(bx + x, by + y, bz))
                        if g and g > 0 then groups[g] = true; any = true end
                    end
                end
            end
        end
    end)
    if not ok or not any then return 0, 0 end
    local added, people = 0, 0
    for _, u in ipairs(dfhack.units.getCitizens()) do
        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(u.pos.x, u.pos.y, u.pos.z))
        if okg and g and g > 0 and not groups[g] then
            people = people + 1
            for dy = -CUT_OFF_RADIUS, CUT_OFF_RADIUS do
                for dx = -CUT_OFF_RADIUS, CUT_OFF_RADIUS do
                    local p = xyz2pos(u.pos.x + dx, u.pos.y + dy, u.pos.z)
                    if dfhack.maps.isValidTilePos(p) and dfhack.maps.getWalkableGroup(p) == g then
                        if pcall(dfhack.burrows.setAssignedTile, b, p, true) then added = added + 1 end
                    end
                end
            end
            groups[g] = true
        end
    end
    return added, people
end

-- (r1 g3) The shelter's water test: the civilians its water serves (drink
-- units / SHELTER_DRINK_PER_CITIZEN, a well SHELTER_CIVS_PER_WELL), and
-- whether that is short of them (with no count of them: no drink nor well).
function shelter_water_cover(info)
    info = type(info) == 'table' and info or {}
    return (tonumber(info.drink_units) or 0) / SHELTER_DRINK_PER_CITIZEN
        + (tonumber(info.well_tiles) or 0) * SHELTER_CIVS_PER_WELL
end

function shelter_water_short(info)
    info = type(info) == 'table' and info or {}
    local civs = tonumber(info.civs)
    if not civs or civs <= 0 then
        return (tonumber(info.drink_units) or 0) <= 0 and (tonumber(info.well_tiles) or 0) <= 0
    end
    return shelter_water_cover(info) < civs
end

-- (r9) The shelter's tiles as they are (each block and tile), to be put back
-- when a redraw finds no tiles or fails part-way: the redraw cleared the
-- alarm's own burrow first, and a fill of 0 (no citizen's level found) or a
-- throw mid-fill left the alarm sending the fort to an empty or half-drawn
-- burrow. nil when the burrow can't be read (nothing put back then).
function shelter_snapshot(b)
    local out = {}
    local ok = pcall(function()
        for _, blk in ipairs(dfhack.burrows.listBlocks(b)) do
            for y = 0, 15 do
                for x = 0, 15 do
                    if dfhack.burrows.isAssignedBlockTile(b, blk, x, y) then out[#out + 1] = {blk, x, y} end
                end
            end
        end
    end)
    return ok and out or nil
end

function shelter_restore(b, snap)
    if type(snap) ~= 'table' then return 0 end
    pcall(dfhack.burrows.clearTiles, b)
    local n = 0
    for _, t in ipairs(snap) do
        if pcall(dfhack.burrows.setAssignedBlockTile, b, t[1], t[2], t[3], true) then n = n + 1 end
    end
    return n
end

-- (r9) The civilian alert's burrow is the AI shelter and covers nothing: the
-- alarm is not sounded into it (ai-bridge-actions act_civ_alert).
function shelter_empty()
    local b = find_burrow(SHELTER_NAME)
    if not b then return false end
    local mine = false
    pcall(function()
        for _, id in ipairs(civ_alert().burrows) do if id == b.id then mine = true end end
    end)
    if not mine then return false end
    local ok, n = pcall(function() return #dfhack.burrows.listBlocks(b) end)
    return ok and n == 0
end

function refresh_shelter()
    local b = find_burrow(SHELTER_NAME)
    if not b then return nil end
    local mine = false
    pcall(function()
        for _, id in ipairs(civ_alert().burrows) do if id == b.id then mine = true end end
    end)
    if not mine then return nil end
    local before = 0
    pcall(function() before = dfhack.burrows.listBlocks and #dfhack.burrows.listBlocks(b) or 0 end)
    local snap = shelter_snapshot(b)
    local okd, n, info, widened = pcall(refresh_fill, b)
    if not okd or (tonumber(n) or 0) == 0 then
        -- (r9) the old shelter put back, the redraw said (not recorded as a
        -- fill: the next alarm draws it again)
        local back = shelter_restore(b, snap)
        return {ok = false, refreshed = false, tiles = back, kept_old = back > 0 or nil, blocks_before = before,
                error = okd and 'the redraw found no inside tiles to shelter in'
                    or 'the redraw failed: ' .. tostring(n):sub(1, 120)}
    end
    local okc, cut_tiles, cut_people = pcall(cover_cut_off, b)
    if okc and (cut_people or 0) > 0 then n = n + (cut_tiles or 0) end
    shelter_drawn(n, info)
    local r = shelter_result({refreshed = true, tiles = n, blocks_before = before}, info)
    if widened then r.widened_for_drink = true end
    if okc and (cut_people or 0) > 0 then r.cut_off_covered = cut_people; r.cut_off_tiles = cut_tiles end
    -- still none (drink near an open entrance only, or none in the fort):
    -- the planner's thirst rule lowers the AI's alarm rather than hold them dry
    if (tonumber(info.drink_units) or 0) <= 0 and (tonumber(info.well_tiles) or 0) <= 0 then r.dry = true end
    return r
end

-- refresh_shelter's drawing: n, info, widened (may raise)
function refresh_fill(b)
    dfhack.burrows.clearTiles(b)
    local only = picked_levels()
    local n, info = fill_shelter(b, only)        -- (0.105.45) the pick away from the threat
    -- (0.105.52) drink beats distance: a picked shelter with no drink and no
    -- well is redrawn over the whole fort (R3 15 Nov: B's 20 thirst deaths in
    -- a dry shelter level while a Hill Titan was on the map; the redraw kept
    -- redrawing the same dry level)
    local widened = false
    -- (r1 g3) and a pick whose water is short for its civilians (E: one
    -- well, its shaft at times shut, for 80-94): redrawn too, the whole fort
    -- taken when it holds more water for them
    if only and shelter_water_short(info) then
        dfhack.burrows.clearTiles(b)
        local n2, info2 = fill_shelter(b, nil)
        if shelter_water_cover(info2) > shelter_water_cover(info) then
            n, info, widened = n2, info2, true
        else
            -- the whole fort is dry too: the safer pick kept (the planner lowers
            -- the alarm for the dehydrated instead)
            dfhack.burrows.clearTiles(b)
            n, info = fill_shelter(b, only)
        end
    end
    return n, type(info) == 'table' and info or {}, widened
end

-- (r8) this file's locals the later parts use, handed on (each takes them
-- back as locals of its own)
SOCIETY_PART_LOCALS = {U = U, report_citizens = report_citizens, report_units = report_units, utils = utils}

---------------------------------------------------------------------------
-- (r8) The rest of the society lives in parts beside this file
-- (ai-society-<part>.lua): animals (pastures, nest boxes, war training, the
-- gate guard's burrow and the gate dogs), needs (the population cap and
-- leaving, idle crafting, trinkets, what stresses the fort, clothes and the
-- cups) and posts (the locations' posts, the vermin hunters, the burrows'
-- forwarders, the AI's own alarm and standing down). Each runs in this
-- module's own environment, so its names stay reqscript('ai-society').name
-- for the bridge and the other modules, and a test's swap (S.fn = ...)
-- reaches every part. They load in this order, the old file's. DFHack reloads
-- a module when its own file changes: a change to a part alone is picked up
-- once ai-society.lua is touched too, or the game restarts.
-- (lua/ai-society-burrows.lua is no part: a module of its own, as before.)
---------------------------------------------------------------------------

PARTS = {'animals', 'needs', 'posts'}
-- each part marks the version it came with; started afresh at each load, so a
-- part that failed to load shows as unmarked
PART_VERSIONS = {['ai-society'] = '0.105.116'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-society-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-society: ' .. name .. '.lua is missing (it goes beside ai-society.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
