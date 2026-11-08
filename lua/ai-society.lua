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

local utils = require('utils')

SHELTER_NAME = 'AI shelter'

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
    for _, u in ipairs(dfhack.units.getCitizens(true)) do add(u.pos.z) end
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
    for _, u in ipairs(df.global.world.units.active) do
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

local function entrance_shut(e, live, dgroups)
    if not e.sealed or type(e.equipment) ~= 'table' or #e.equipment == 0 then return false end
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
SHELTER_DRINK_SCAN = 4000
local function drink_and_wells()
    local out = {}
    pcall(function()
        local n = 0
        for _, it in ipairs(df.global.world.items.other.DRINK) do
            n = n + 1
            if n > SHELTER_DRINK_SCAN then break end
            local ok, pos = pcall(function()
                if it.flags.forbid or it.flags.garbage_collect or it.flags.in_inventory then return nil end
                local c = dfhack.items.getContainer and dfhack.items.getContainer(it)
                if c and (c.flags.forbid or c.flags.in_inventory) then return nil end
                local x, y, z = dfhack.items.getPosition(it)
                if type(x) == 'table' then return x end
                if x and x >= 0 then return {x = x, y = y, z = z} end
                return nil
            end)
            if ok and pos then out[pos.x .. ',' .. pos.y .. ',' .. pos.z] = 'drink' end
        end
    end)
    pcall(function()
        local okb, B = pcall(reqscript, 'ai-society-burrows')
        for _, b in ipairs(df.global.world.buildings.other.WELL) do
            local ok, good = pcall(function()
                if b:getBuildStage() < b:getMaxBuildStage() then return false end
                if okb and B and B.well_gives_water then return B.well_gives_water(b) ~= false end
                return true
            end)
            if not ok or good then out[b.centerx .. ',' .. b.centery .. ',' .. b.z] = 'well' end
        end
    end)
    return out
end

SHELTER_OPEN_KEY = 'ai-overseer/shelter_open'       -- (0.105.26) the entrances open when it was made
SHELTER_DRINK_BACK = 30                             -- drink tiles taken back at most

local function entrance_keys(list)
    local keys = {}
    for _, e in ipairs(list or {}) do table.insert(keys, e.x .. ',' .. e.y .. ',' .. e.z) end
    table.sort(keys)
    return keys
end

-- Fills the burrow; returns the tiles in it and what was left out:
-- {excluded, open_entrances, entrances_scanned, fallback, note, why,
-- drink_tiles, well_tiles, deep_depot_tiles, drink_back}.
function fill_shelter(b)
    local info = {excluded = 0, margin = SHELTER_MARGIN, margin_levels = SHELTER_MARGIN_Z}
    local lo, hi = fort_levels()
    if not lo then return 0, info end
    local okl, open, scanned = pcall(open_entrances)
    if not okl then open, scanned, info.entrances_error = {}, false, tostring(open):sub(1, 120) end
    info.entrances_scanned = scanned
    info.open_entrances = #open
    pcall(function() U.site_put(SHELTER_OPEN_KEY, {keys = entrance_keys(open), scanned = scanned and true or false}) end)
    local deep, deep_n = deep_depot_tiles()                  -- (0.105.26)
    local okw, water = pcall(drink_and_wells)
    water = okw and water or {}
    local drink_tiles, well_tiles, deep_out = 0, 0, 0
    local n = 0
    local held = {}          -- the tiles left out: {block, x, y, far, kind}
    for _, block in ipairs(df.global.world.map.map_blocks) do
        local z = block.map_pos.z
        if z >= lo and z <= hi then
            local bx, by = block.map_pos.x or 0, block.map_pos.y or 0
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
                                table.insert(held, {block, x, y, far or 0, water[k]})
                            else
                                dfhack.burrows.setAssignedBlockTile(b, block, x, y, true)
                                n = n + 1
                                if water[k] == 'drink' then drink_tiles = drink_tiles + 1
                                elseif water[k] == 'well' then well_tiles = well_tiles + 1 end
                            end
                        end
                    end
                end
            end
        end
    end
    if deep_out > 0 then info.deep_depot_tiles = deep_out end
    -- (0.105.26) B (2 Nov) and A: a shelter with no drink nor well in it
    -- killed by thirst. Neither inside: the left-out drink and well tiles
    -- farthest from the open entrances come back first (a well, and up to
    -- SHELTER_DRINK_BACK drink tiles)
    local back = 0
    if drink_tiles + well_tiles == 0 and #held > 0 then
        table.sort(held, function(a, c) return a[4] > c[4] end)
        local rest = {}
        for _, h in ipairs(held) do
            if h[5] == 'well' and well_tiles == 0 then
                dfhack.burrows.setAssignedBlockTile(b, h[1], h[2], h[3], true)
                n, back, well_tiles = n + 1, back + 1, well_tiles + 1
            elseif h[5] == 'drink' and drink_tiles < SHELTER_DRINK_BACK then
                dfhack.burrows.setAssignedBlockTile(b, h[1], h[2], h[3], true)
                n, back, drink_tiles = n + 1, back + 1, drink_tiles + 1
            else
                table.insert(rest, h)
            end
        end
        held = rest
        if back > 0 then
            info.drink_back = back
            info.drink_note = ('no drink nor well away from the open entrances: %d drink and well tile%s near them taken back')
                :format(back, back == 1 and '' or 's')
        end
    end
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
        local okc, cits = pcall(function() return #dfhack.units.getCitizens(true) end)
        local need = math.max(SHELTER_MIN_TILES, SHELTER_TILES_PER_CITIZEN * (okc and cits or 0))
        if n < need then
            -- too few away from them: the farthest of the left-out tiles back
            table.sort(held, function(a, c) return a[4] > c[4] end)
            local fb = 0
            for _, t in ipairs(held) do
                if n >= need then break end
                dfhack.burrows.setAssignedBlockTile(b, t[1], t[2], t[3], true)
                n, fb = n + 1, fb + 1
                if t[5] == 'drink' then drink_tiles = drink_tiles + 1
                elseif t[5] == 'well' then well_tiles = well_tiles + 1 end
            end
            info.excluded = #held - fb
            info.fallback = true
            info.taken_back = fb
            info.note = ('only %d tiles away from the open entrances (needs %d): the %d farthest of the left-out tiles taken back')
                :format(n - fb, need, fb)
        end
    end
    info.drink_tiles, info.well_tiles = drink_tiles, well_tiles
    if drink_tiles + well_tiles == 0 then
        info.no_water = 'the shelter holds no drink and no well'
    end
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
    r.deep_depot_tiles = info.deep_depot_tiles
    return r
end

-- Make (or refresh) the "AI shelter" burrow and make it the civilian alert's.
function setup_shelter()
    if alert_has_burrow() then
        return {ok = false, rejected = true, error = 'the civilian alert already has a burrow'}
    end
    local b = find_burrow(SHELTER_NAME) or new_burrow(SHELTER_NAME)
    dfhack.burrows.clearTiles(b)
    local n, info = fill_shelter(b)
    if n == 0 then
        return {ok = false, error = 'found no inside tiles to shelter in'}
    end
    require('utils').insert_sorted(civ_alert().burrows, b.id)
    return shelter_result({ok = true, burrow_id = b.id, tiles = n}, info)
end

-- (0.105.8) The AI's shelter made again over the fort as it is now, when it
-- is the civilian alert's burrow (a player's own is never touched): before
-- each alarm the AI sounds. {refreshed, tiles, before} or nil.
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
    dfhack.burrows.clearTiles(b)
    local n, info = fill_shelter(b)
    return shelter_result({refreshed = true, tiles = n, blocks_before = before}, info)
end

-- Grass tiles a grazer needs: DF's rule of thumb, 20000 / its GRAZER value
-- (a cow about 38, a sheep about 6). 10 when the value can't be read.
function grazer_tiles(u)
    local ok, g = pcall(function()
        return df.creature_raw.find(u.race).caste[u.caste].misc.grazer
    end)
    if not ok or type(g) ~= 'number' or g <= 0 then return 10 end
    return math.max(1, math.ceil(20000 / g))
end

-- The grass in a pasture (what its animals can eat), not its whole area.
local function area_of(z)
    local ok, n = pcall(function()
        local B, g = reqscript('ai-builder'), 0
        for y = z.y1, z.y2 do
            for x = z.x1, z.x2 do
                if B.grass_at(x, y, z.z) then g = g + 1 end
            end
        end
        return g
    end)
    if ok then return n end
    return (z.x2 - z.x1 + 1) * (z.y2 - z.y1 + 1)
end

-- Grass the animals already in this pasture need.
local function pen_load(zone)
    local n = 0
    for _, id in ipairs(zone.assigned_units) do
        local u = df.unit.find(id)
        if u and dfhack.units.isAlive(u) then n = n + grazer_tiles(u) end
    end
    return n
end

-- Pastures that exist, with the room left in each: {zone, spare}, most room first.
local function pens()
    local out = {}
    for _, z in ipairs(df.global.world.buildings.all) do
        if z:getType() == df.building_type.Civzone and z.type == df.civzone_type.Pen then
            local area = area_of(z)
            table.insert(out, {zone = z, area = area, spare = area - pen_load(z)})
        end
    end
    table.sort(out, function(a, b) return a.spare > b.spare end)
    return out
end

function unpastured_grazers()
    local out = {}
    for _, u in ipairs(df.global.world.units.active) do
        if dfhack.units.isAlive(u) and dfhack.units.isTame(u) and dfhack.units.isOwnCiv(u)
                and not u.flags1.caged and dfhack.units.isGrazer(u)
                and not dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED) then
            table.insert(out, u)
        end
    end
    return out
end

-- For the report: grass the waiting grazers need, the smallest single need,
-- and the most room left in any pasture.
function pasture_needs()
    local need, smallest = 0, nil
    for _, u in ipairs(unpastured_grazers()) do
        local t = grazer_tiles(u)
        need = need + t
        smallest = smallest and math.min(smallest, t) or t
    end
    local list = pens()
    return {need = need, smallest = smallest or 0, spare = #list > 0 and math.max(0, list[1].spare) or 0}
end

-- Put up to `count` grazing animals into pastures with room for them (the
-- same links DFHack's old zone tool made: the zone lists the unit, the unit
-- points at the zone). Big animals first, so they get the big pastures.
function pasture(count)
    local list = pens()
    if #list == 0 then return {ok = false, rejected = true, error = 'the fort has no pasture zone'} end
    local waiting = unpastured_grazers()
    if #waiting == 0 then return {ok = false, rejected = true, error = 'no grazing animal needs a pasture'} end
    table.sort(waiting, function(a, b) return grazer_tiles(a) > grazer_tiles(b) end)
    local done, zones = 0, {}
    for _, u in ipairs(waiting) do
        if done >= count then break end
        local need = grazer_tiles(u)
        table.sort(list, function(a, b) return a.spare > b.spare end)
        local pen = list[1]
        if pen.spare >= need then
            utils.insert_sorted(pen.zone.assigned_units, u.id)     -- (kept in order, as the game keeps it)
            local ref = df.general_ref_building_civzone_assignedst:new()
            ref.building_id = pen.zone.id
            u.general_refs:insert('#', ref)
            pen.spare = pen.spare - need
            zones[pen.zone.id] = true
            done = done + 1
        end
    end
    if done == 0 then
        return {ok = false, rejected = true, error = 'no pasture has room for the waiting animals'}
    end
    local ids = {}
    for id in pairs(zones) do table.insert(ids, id) end
    return {ok = true, assigned = done, zone_ids = ids, left = #waiting - done}
end

-- (0.104.80) Eggs: a hen lays only in a nest box she can reach (DF wiki,
-- Nest box), and Enxah had none (no eggs, 28 dwarves wanting a good meal).
-- The hens with no pasture are put in the one holding the most hens (else
-- the AI's pasture with the most room: a hen needs no grass), then nest
-- boxes are planned in it, one a hen, up to `max` a call (the game builds
-- each once a nest box item is free).
local function egg_layer(u)
    if not (dfhack.units.isAlive(u) and dfhack.units.isTame(u) and dfhack.units.isOwnCiv(u)
            and dfhack.units.isAdult(u) and dfhack.units.isFemale(u)) or u.flags1.caged then
        return false
    end
    local ok, e = pcall(function() return df.creature_raw.find(u.race).caste[u.caste].flags.LAYS_EGGS end)
    return ok and e and true or false
end

local function boxes_in(zone)
    local n = 0
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.NestBox and b.z == zone.z and b.x1 >= zone.x1 and b.x1 <= zone.x2 and b.y1 >= zone.y1 and b.y1 <= zone.y2 then
            n = n + 1
        end
    end
    return n
end

function nest_boxes(max, dry_run)
    max = max or 3
    local list = pens()
    if #list == 0 then return {ok = false, rejected = true, error = 'the fort has no pasture zone'} end
    local hens, loose, by_zone = 0, {}, {}
    for _, u in ipairs(df.global.world.units.active) do
        if egg_layer(u) then
            hens = hens + 1
            local ref = dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED)
            if ref then by_zone[ref.building_id] = (by_zone[ref.building_id] or 0) + 1
            else table.insert(loose, u) end
        end
    end
    if hens == 0 then return {ok = false, rejected = true, error = 'no hen lays eggs here'} end
    local pen, best = nil, 0
    for _, p in ipairs(list) do
        local n = by_zone[p.zone.id] or 0
        if n > best then pen, best = p.zone, n end
    end
    if not pen then
        for _, p in ipairs(list) do
            if tostring(p.zone.name or '') == AI_PASTURE_NAME then pen = p.zone; break end
        end
        pen = pen or list[1].zone
    end
    local penned = 0
    if not dry_run then
        for _, u in ipairs(loose) do
            utils.insert_sorted(pen.assigned_units, u.id)
            local ref = df.general_ref_building_civzone_assignedst:new()
            ref.building_id = pen.id
            u.general_refs:insert('#', ref)
            penned = penned + 1
        end
    else
        penned = #loose
    end
    local have = boxes_in(pen)
    local want = math.min(max, math.max(0, (by_zone[pen.id] or 0) + penned - have))
    local placed, err = 0, nil
    for _ = 1, want do
        local r = reqscript('ai-builder').place_in_zone(pen.id, 'nest_box', dry_run)
        if not (r and r.ok) then err = r and r.error; break end
        placed = placed + 1
        if dry_run then placed = want; break end
    end
    if placed == 0 and penned == 0 then
        return {ok = false, rejected = true,
                error = err or ('every hen in pasture %d has a nest box (%d)'):format(pen.id, have)}
    end
    return {ok = true, zone_id = pen.id, hens = hens, penned = penned, boxes = have, placed = placed,
            note = err, dry_run = dry_run or nil}
end

-- (0.104.81) War animals: tame dogs and the like trained for war fight
-- beside the dwarves (DF wiki, Animal trainer). Enxah: 124 tame animals,
-- one animal trainer, none trained. Up to `max` a call get a training
-- assignment (any trainer, war training), as DF's animals screen makes it;
-- DF's trainers do the rest.
local function training_list()
    -- (where DF keeps it moved between versions: both are tried)
    local ok, v = pcall(function() return df.global.plotinfo.training.training_assignments end)
    if ok and v then return v end
    ok, v = pcall(function() return df.global.plotinfo.equipment.training_assignments end)
    if ok and v then return v end
    error('no animal training list in this DF')
end

local function war_trainable(u)
    if not (dfhack.units.isAlive(u) and dfhack.units.isTame(u) and dfhack.units.isOwnCiv(u)
            and dfhack.units.isAdult(u)) or dfhack.units.isCitizen(u) then
        return false
    end
    local ok, yes = pcall(function() return df.creature_raw.find(u.race).caste[u.caste].flags.TRAINABLE_WAR end)
    if not (ok and yes) then return false end
    local okp, prof = pcall(function() return df.profession[u.profession] end)
    if okp and (prof == 'TRAINED_WAR' or prof == 'TRAINED_HUNTER') then return false end
    local okw, pet = pcall(function() return u.relationship_ids.PetOwner end)
    if okw and type(pet) == 'number' and pet ~= -1 then return false end      -- someone's pet: theirs
    return true
end

function animal_training_report()
    local out = {war_candidates = 0, war_trained = 0, in_training = 0, trainers = 0}
    local assigned = {}
    for _, a in ipairs(training_list()) do assigned[a.animal_id] = true; out.in_training = out.in_training + 1 end
    for _, u in ipairs(df.global.world.units.active) do
        local okp, prof = pcall(function() return df.profession[u.profession] end)
        if okp and prof == 'TRAINED_WAR' and dfhack.units.isAlive(u) and dfhack.units.isOwnCiv(u) then
            out.war_trained = out.war_trained + 1
        elseif not assigned[u.id] and war_trainable(u) then
            out.war_candidates = out.war_candidates + 1
        end
    end
    local labor = df.unit_labor.ANIMALTRAIN
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if labor and u.status.labors[labor] then out.trainers = out.trainers + 1 end
    end
    return out
end

function train_war(max, dry_run, txt)
    max = max or 3
    local list = training_list()
    local assigned = {}
    for _, a in ipairs(list) do assigned[a.animal_id] = true end
    local cands = {}
    for _, u in ipairs(df.global.world.units.active) do
        if not assigned[u.id] and war_trainable(u) then table.insert(cands, u) end
    end
    if #cands == 0 then return {ok = false, rejected = true, error = 'no tame animal here can be trained for war'} end
    table.sort(cands, function(a, b) return a.id < b.id end)
    local names = {}
    for i = 1, math.min(max, #cands) do
        local u = cands[i]
        if not dry_run then
            local a = df.training_assignment:new()
            a.animal_id = u.id
            a.trainer_id = -1
            a.flags.any_trainer = true
            a.flags.train_war = true
            utils.insert_sorted(list, a, 'animal_id')
        end
        local okn, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
        table.insert(names, okn and n or ('#' .. u.id))
    end
    return {ok = true, assigned = #names, animals = names, left = #cands - #names, dry_run = dry_run or nil}
end

-- (0.104.83) The gate guard burrow: the walkable inside tiles within
-- `radius` of the gate, on its level and the two below (a gate on a stair's
-- top leads down), not open to the sky, no water or magma.
GUARD_NAME = 'AI gate guard'

local function inside_tile(x, y, z)
    local okd, d = pcall(dfhack.maps.getTileFlags, xyz2pos(x, y, z))
    if not okd or not d or d.outside or d.flow_size > 0 then return false end
    return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) ~= 0
end

function guard_gate(squad_ids, x, y, z, radius, dry_run)
    radius = radius or 5
    local tiles = {}
    for zz = z, z - 2, -1 do
        for xx = x - radius, x + radius do
            for yy = y - radius, y + radius do
                if inside_tile(xx, yy, zz) then table.insert(tiles, xyz2pos(xx, yy, zz)) end
            end
        end
    end
    if #tiles == 0 then return {ok = false, rejected = true, error = 'no inside floor near the gate to hold'} end
    if dry_run then return {ok = true, dry_run = true, tiles = #tiles} end
    local b = find_burrow(GUARD_NAME) or new_burrow(GUARD_NAME)
    pcall(dfhack.burrows.clearTiles, b)
    for _, p in ipairs(tiles) do dfhack.burrows.setAssignedTile(b, p, true) end
    local M = reqscript('ai-military')
    local sent, refused = {}, {}
    for _, sid in ipairs(squad_ids) do
        local r = M.defend(sid, b.id)
        if r.ok then table.insert(sent, sid) else table.insert(refused, sid .. ': ' .. tostring(r.error)) end
    end
    if #sent == 0 then
        return {ok = false, rejected = true, error = 'no squad took the order (' .. table.concat(refused, '; ') .. ')'}
    end
    return {ok = true, burrow_id = b.id, tiles = #tiles, squads = sent, refused = #refused > 0 and refused or nil}
end

-- (0.104.83) War dogs at the gate: the war-trained animals put in the gate
-- dog pen (made by ai-builder gate_dog_pen), where they meet what comes in.
GATE_DOGS_NAME = 'AI gate dogs'

local function gate_pen()
    for _, z in ipairs(df.global.world.buildings.all) do
        if z:getType() == df.building_type.Civzone and z.type == df.civzone_type.Pen
                and tostring(z.name or '') == GATE_DOGS_NAME then
            return z
        end
    end
end

function war_dogs_free()
    local out = {}
    for _, u in ipairs(df.global.world.units.active) do
        local okp, prof = pcall(function() return df.profession[u.profession] end)
        if okp and prof == 'TRAINED_WAR' and dfhack.units.isAlive(u) and dfhack.units.isOwnCiv(u)
                and not u.flags1.caged
                and not dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED) then
            local okw, pet = pcall(function() return u.relationship_ids.PetOwner end)
            if not (okw and type(pet) == 'number' and pet ~= -1) then table.insert(out, u) end
        end
    end
    return out
end

function gate_dogs(x, y, z, max, dry_run)
    local dogs = war_dogs_free()
    if #dogs == 0 then return {ok = false, rejected = true, error = 'no war-trained animal waits for a post'} end
    local pen = gate_pen()
    local made
    if not pen then
        made = reqscript('ai-builder').gate_dog_pen({x = x, y = y, z = z, name = GATE_DOGS_NAME}, dry_run)
        if not (made and made.ok) then
            return {ok = false, rejected = true, error = 'no pen at the gate: ' .. tostring(made and made.error)}
        end
        if dry_run then return {ok = true, dry_run = true, pen = made, dogs = math.min(max or 4, #dogs)} end
        pen = gate_pen()
        if not pen then return {ok = false, error = 'the pen was designated but is not there yet'} end
    end
    local n = 0
    for _, u in ipairs(dogs) do
        if n >= (max or 4) then break end
        if not dry_run then
            utils.insert_sorted(pen.assigned_units, u.id)
            local ref = df.general_ref_building_civzone_assignedst:new()
            ref.building_id = pen.id
            u.general_refs:insert('#', ref)
        end
        n = n + 1
    end
    return {ok = true, zone_id = pen.id, posted = n, left = #dogs - n, pen_made = made and true or nil,
            dry_run = dry_run or nil}
end

function gate_dogs_report()
    local pen = gate_pen()
    return {free = #war_dogs_free(), pen = pen and pen.id or nil, posted = pen and #pen.assigned_units or 0}
end

function pasture_count()
    local ok, list = pcall(pens)
    return ok and #list or 0
end

-- The pastures the AI made itself (zones named "AI pasture"): how many, their
-- grass tiles and how much of it is free. The overseer notices when one is
-- removed (you didn't want it) and how full they run (it sizes the next one).
AI_PASTURE_NAME = 'AI pasture'

function ai_pastures()
    local n, tiles, spare = 0, 0, 0
    for _, p in ipairs(pens()) do
        if tostring(p.zone.name or '') == AI_PASTURE_NAME then
            n = n + 1
            tiles = tiles + area_of(p.zone)
            spare = spare + math.max(0, p.spare)
        end
    end
    return {count = n, tiles = tiles, spare = spare}
end

-- (13c) The bridge's report in one pass: the pastures listed once and the
-- grazers once (the report asked pasture_count, pasture_needs and
-- ai_pastures in turn, three walks of every building). The same numbers.
function pasture_report()
    local list, waiting = pens(), unpastured_grazers()
    local need, smallest = 0, nil
    for _, u in ipairs(waiting) do
        local t = grazer_tiles(u)
        need = need + t
        smallest = smallest and math.min(smallest, t) or t
    end
    local n, tiles, spare = 0, 0, 0
    for _, p in ipairs(list) do
        if tostring(p.zone.name or '') == AI_PASTURE_NAME then
            n = n + 1
            tiles = tiles + p.area
            spare = spare + math.max(0, p.spare)
        end
    end
    return {grazers = #waiting, count = #list,
            needs = {need = need, smallest = smallest or 0, spare = #list > 0 and math.max(0, list[1].spare) or 0},
            ai = {count = n, tiles = tiles, spare = spare}}
end

-- The population cap (DF's own setting: migrants stop coming at it). Where
-- the game keeps it moved between versions, so a few places are tried.
-- A change lasts for this session; the overseer sets it again after a restart.
local function popcap_holder()
    local tries = {
        function() return df.global.d_init.dwarf end,
        function() return df.global.d_init end,
    }
    for _, f in ipairs(tries) do
        local ok, t = pcall(f)
        if ok and t then
            local ok2, v = pcall(function() return t.population_cap end)
            if ok2 and type(v) == 'number' then return t end
        end
    end
    return nil
end

function get_popcap()
    local t = popcap_holder()
    if not t then return nil end
    local ok, strict = pcall(function() return t.strict_population_cap end)
    return {cap = t.population_cap, strict = ok and strict or nil}
end

function set_popcap(cap, strict)
    local t = popcap_holder()
    if not t then return {ok = false, error = 'this DF version keeps the population cap somewhere the AI can\'t find'} end
    t.population_cap = cap
    pcall(function() t.strict_population_cap = strict end)
    return {ok = true, cap = cap, strict = strict}
end

-- Extreme low Growth: the fort slowly shrinks. One dwarf leaves, the way
-- DFHack's own emigration tool sends dwarves away: the least skilled adult
-- citizen who isn't a noble, a soldier or chained (emigration's canLeave).
-- unit_id: that citizen (a vampire the AI sends away), whatever their skills
function expel_one(txt, unit_id)
    local ok, em = pcall(reqscript, 'emigration')
    if not ok or type(em.desert) ~= 'function' or type(em.canLeave) ~= 'function' then
        return {ok = false, error = "DFHack's emigration tool isn't available"}
    end
    local best, best_score
    if unit_id then
        best = df.unit.find(unit_id)
        if not best or not dfhack.units.isCitizen(best, true) then
            return {ok = false, rejected = true, error = 'no citizen with id ' .. tostring(unit_id)}
        end
        -- (0.100, security pass) a named dwarf is sent away only for being a
        -- vampire (the rule's one use); anyone else goes by the usual pick,
        -- which leaves nobles, soldiers and children
        local okb, vamp = pcall(dfhack.units.isBloodsucker, best)
        if not (okb and vamp) then
            return {ok = false, rejected = true, error = 'only a vampire is sent away by name'}
        end
    end
    for _, u in ipairs(unit_id and {} or dfhack.units.getCitizens(true)) do
        local okc, can = pcall(em.canLeave, u)
        if okc and can then
            local score = 0
            local soul = u.status.current_soul
            if soul then for _, sk in ipairs(soul.skills) do score = score + sk.rating end end
            if not best or score < best_score then best, best_score = u, score end
        end
    end
    if not best then
        return {ok = false, rejected = true, error = 'nobody can leave (nobles, soldiers and children stay)'}
    end
    local civ = df.global.plotinfo.civ_id
    pcall(function()
        local fort = U.fort_entity()
        civ = fort.entity_links[0].target           -- as emigration does when nobody visits
    end)
    local name = txt and txt(dfhack.units.getReadableName(best)) or tostring(best.id)
    local okd, err = pcall(em.desert, best, 'wild', civ)
    if not okd then return {ok = false, error = 'emigration failed: ' .. tostring(err)} end
    return {ok = true, unit_id = best.id, name = name}
end

-- --- recreational crafting (DFHack's idle-crafting) ----------------------------------
--
-- Dwarves who need to craft (the CraftObject need) can craft for themselves
-- at a Craftsdwarf's workshop marked for it: what idle-crafting's toggle on
-- the workshop's Workers tab does. Done through its saved state (enabled, the
-- allowed workshops) and its own map-loaded handler, which reads that state
-- and starts it.
IC_KEY = 'idle-crafting'

local function ic_state()
    return U.site_get(IC_KEY, {})
end

function idle_crafting_status()
    local d = ic_state()
    local n = 0
    for _ in pairs(type(d.allowed) == 'table' and d.allowed or {}) do n = n + 1 end
    return {enabled = d.enabled == true, workshops = n}
end

function idle_crafting(dry_run)
    local ok = pcall(reqscript, 'idle-crafting')
    if not ok then return {ok = false, rejected = true, error = 'DFHack has no idle-crafting script'} end
    -- every finished Craftsdwarf's workshop not kept for certain workers
    -- and not already allowed (one served a hundred dwarves poorly: Oct 23)
    local d = ic_state()
    d.allowed = type(d.allowed) == 'table' and d.allowed or {}
    local picks = {}
    local okl, list = pcall(function() return df.global.world.buildings.other.WORKSHOP_ANY end)
    for _, b in ipairs(okl and list or df.global.world.buildings.all) do
        local okt, is = pcall(function()
            return b:getType() == df.building_type.Workshop and b.type == df.workshop_type.Craftsdwarfs
                and b:getBuildStage() >= b:getMaxBuildStage() and #b.profile.permitted_workers == 0
        end)
        if okt and is and d.allowed[tostring(b.id)] == nil then table.insert(picks, b) end
    end
    if #picks == 0 then return {ok = false, rejected = true, error = 'no Craftsdwarf\'s workshop free for it'} end
    local pick = picks[1]
    if dry_run then return {ok = true, dry_run = true, workshop = pick.id, workshops = #picks} end
    for _, b in ipairs(picks) do d.allowed[tostring(b.id)] = -1 end
    d.enabled = true
    dfhack.persistent.saveSiteData(IC_KEY, d)
    local handler = dfhack.onStateChange[IC_KEY]
    if not handler then return {ok = false, error = 'idle-crafting is not loaded'} end
    local okh, err = pcall(handler, SC_MAP_LOADED)
    if not okh then return {ok = false, error = 'idle-crafting did not start: ' .. tostring(err):sub(1, 160)} end
    return {ok = true, workshop = pick.id, added = #picks}
end

-- Count of finished Craftsdwarf's workshops (for the report).
function craft_shops()
    local n = 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            if b:getType() == df.building_type.Workshop and b.type == df.workshop_type.Craftsdwarfs
                    and b:getBuildStage() >= b:getMaxBuildStage() then n = n + 1 end
        end
    end)
    return n
end

-- --- things to own (the AcquireObject need) -----------------------------------------
--
-- A dwarf who wants to own things gets one by picking up an item while
-- hauling it, which rarely happens in a fort that stores crafts in bins and
-- sells the rest (79 of 100 dwarves badly wanted something on Oct 23). The AI
-- gives each such dwarf a free trinket: the item becomes theirs (the game's
-- own ownership: they keep it in their room) and the need counts as met, as
-- when they pick one up themselves.
TRINKETS = {'RING', 'EARRING', 'AMULET', 'BRACELET', 'CROWN', 'SCEPTER', 'FIGURINE', 'TOTEM'}
ACQUIRE_DISTRACTED = -1000
SATISFIED_FOCUS = 400              -- the top of the "not distracted" range

local function free_trinket(item)
    local f = item.flags
    if not U.item_free(item, {held = true}) then return false end   -- (on the ground or in a bin, below)
    local ok, owner = pcall(dfhack.items.getOwner, item)
    if ok and owner then return false end
    -- loose on the ground, or in a bin (a container on the ground)
    if f.on_ground then return true end
    local okc, c = pcall(dfhack.items.getContainer, item)
    return okc and c ~= nil and c.flags.on_ground and not c.flags.in_building and not c.flags.forbid
end

function free_trinkets(limit)
    local out = {}
    for _, name in ipairs(TRINKETS) do
        local ok, list = pcall(function() return df.global.world.items.other[name] end)
        if ok and list then
            for _, item in ipairs(list) do
                if limit and #out >= limit then return out end
                if free_trinket(item) then table.insert(out, item) end
            end
        end
    end
    return out
end

-- (0.104.141) The trinkets there are, by where they are: free (to give),
-- owned, in a job, at the depot or a trader's, forbidden, in a building
-- (a bin in a workshop...), carried, other.
-- (13c) `where` (what holds those in a job or "other") is a sample of the
-- first WHERE_SAMPLE: Teacheroar's 7,000 such took a container or job
-- look-up and a string each, every daily report; `where_sampled` says how many
WHERE_SAMPLE = 300
function trinket_census()
    local out = {free = 0, owned = 0, in_job = 0, trade = 0, forbidden = 0, in_building = 0, carried = 0, other = 0}
    local sampled = 0
    for _, name in ipairs(TRINKETS) do
        local ok, list = pcall(function() return df.global.world.items.other[name] end)
        if ok and list then
            for _, item in ipairs(list) do
                local okk, k = pcall(function()
                    local f = item.flags
                    if f.removed or f.garbage_collect or f.artifact then return nil end
                    if free_trinket(item) then return 'free' end
                    if f.owned then return 'owned' end
                    if f.in_job then return 'in_job' end
                    if f.trader then return 'trade' end
                    if f.in_building then
                        local b = dfhack.items.getHolderBuilding(item)
                        if b and b:getType() == df.building_type.TradeDepot then return 'trade' end
                    end
                    if f.forbid then return 'forbidden' end
                    if f.in_inventory then return 'carried' end
                    if f.in_building then return 'in_building' end
                    return 'other'
                end)
                if okk and k then out[k] = out[k] + 1 end
                -- (0.104.141) what holds the ones not free: Teacheroar showed 0
                -- free, 16 owned, 1,232 in jobs and 5,884 "other"
                if okk and (k == 'other' or k == 'in_job') and sampled < WHERE_SAMPLE then
                    sampled = sampled + 1
                    pcall(function()
                        local where
                        if k == 'in_job' then
                            local ref = dfhack.items.getSpecificRef(item, df.specific_ref_type.JOB)
                            local j = ref and ref.data.job
                            where = 'job ' .. (j and df.job_type[j.job_type] or '?')
                        else
                            local c = dfhack.items.getContainer(item)
                            if not c then
                                where = 'loose'
                            else
                                local cf = c.flags
                                local cb = cf.in_building and dfhack.items.getHolderBuilding(c)
                                where = df.item_type[c:getType()] .. (cf.forbid and ' forbidden' or '')
                                    .. (cf.in_job and ' in a job' or '') .. (cf.in_inventory and ' carried' or '')
                                    .. (cb and (' in ' .. (df.building_type[cb:getType()] or '?')) or '')
                                    .. (cf.on_ground and '' or ' not on ground')
                            end
                        end
                        out.where = out.where or {}
                        out.where[where] = (out.where[where] or 0) + 1
                    end)
                end
            end
        end
    end
    if sampled > 0 then out.where_sampled = sampled end
    return out
end

-- (0.104.141) Butchered bones a craftsdwarf could carve (loose or in a bin,
-- not forbidden or in a job), counted up to `limit`.
-- (0.104.157) What is stressing the fort, in DF's own words: each citizen's
-- emotions of the last STRESS_DAYS days by the thought behind them
-- (df.unit_thought_type), summed by how much stress each adds (strength /
-- the emotion's divider; a negative divider eases stress). Teacheroar, 1 Nov:
-- 9 miserable, 21 very unhappy, and miserable children with no unmet need:
-- the needs alone can't say why. {causes = [{thought, citizens, stress,
-- emotions}] (the worst first, 15), eased = [...] (8), citizens, read}.
STRESS_DAYS = 28
STRESS_TOP, EASED_TOP = 15, 8

local function emotion_divider(t)
    local ok, d = pcall(function() return df.emotion_type.attrs[t].divider end)
    if ok and type(d) == 'number' then return d end
    return nil
end

-- (0.104.168) what a few thoughts were about (DF's subthought, its
-- circumstance): a complaint nobody heard (UnableComplain, COMPLAINT_UNREGISTERED)
-- carries DF's reason (history_event_reason: insufficient_work,
-- work_request, make_weapon, vent_at_boss, cry_on_boss), and a hated
-- vermin seen (AnnoyedVermin, NEAR_HATED_VERMIN) the creature (assumed the
-- race id: the caption is "accosted by [vermin]"). Tallied per thought as
-- `about` = {word = n}. Teacheroar, 1 Nov: 24 citizens unable to complain,
-- 15 accosted by vermin, and the census couldn't say why or by what.
local function about_reason(sub) return df.history_event_reason[sub] end
local function about_creature(sub)
    local cr = df.creature_raw.find(sub)
    return cr and cr.creature_id or nil
end
STRESS_ABOUT = {UnableComplain = about_reason, Complained = about_reason,
                AnnoyedVermin = about_creature, NearVermin = about_creature}

function stress_census(units)
    local now = U.abs_tick()
    local since = now - STRESS_DAYS * 1200
    local by, citizens, read, no_divider = {}, 0, 0, 0
    for _, u in ipairs(units or dfhack.units.getCitizens()) do
        citizens = citizens + 1
        local ok, ems = pcall(function() return u.status.current_soul.personality.emotions end)
        if ok and ems then
            read = read + 1
            local seen = {}
            local okc, child = pcall(function() return dfhack.units.isChild(u) or dfhack.units.isBaby(u) end)
            child = okc and child or false
            for _, em in ipairs(ems) do
                local okt, when = pcall(function() return U.abs_tick(em.year, em.year_tick) end)
                if not okt or when >= since then
                    local name = df.unit_thought_type[em.thought] or tostring(em.thought)
                    local d = emotion_divider(em.type)
                    local stress = 0
                    if d and d ~= 0 then stress = (em.strength or 0) / d else no_divider = no_divider + 1 end
                    local e = by[name] or {thought = name, citizens = 0, stress = 0, emotions = 0, kinds = {}}
                    e.stress, e.emotions = e.stress + stress, e.emotions + 1
                    local ek = df.emotion_type[em.type] or tostring(em.type)
                    e.kinds[ek] = (e.kinds[ek] or 0) + 1
                    local about = STRESS_ABOUT[name]          -- (0.104.168)
                    if about then
                        local okw, w = pcall(function() return about(em.subthought) end)
                        if okw and w ~= nil then
                            e.about = e.about or {}
                            e.about[tostring(w)] = (e.about[tostring(w)] or 0) + 1
                        end
                    end
                    if not seen[name] then
                        seen[name], e.citizens = true, e.citizens + 1
                        if child then e.children = (e.children or 0) + 1 end   -- (0.104.159)
                    end
                    by[name] = e
                end
            end
        end
    end
    local worse, eased = {}, {}
    for _, e in pairs(by) do
        e.stress = math.floor(e.stress + 0.5)
        local top, topn = nil, 0
        for k, n in pairs(e.kinds) do if n > topn then top, topn = k, n end end
        e.emotion, e.kinds = top, nil
        if e.stress > 0 then table.insert(worse, e) elseif e.stress < 0 then table.insert(eased, e) end
    end
    table.sort(worse, function(a, b) return a.stress > b.stress end)
    table.sort(eased, function(a, b) return a.stress < b.stress end)
    while #worse > STRESS_TOP do table.remove(worse) end
    while #eased > EASED_TOP do table.remove(eased) end
    return {causes = worse, eased = eased, citizens = citizens, read = read, days = STRESS_DAYS,
            no_divider = no_divider > 0 and no_divider or nil}
end

-- (0.104.157) The citizens' clothes: worn items by wear (DF's 0 new .. 3
-- tattered, "XX"), and how many go without shoes, something on the legs
-- (trousers, skirt) or the body (shirt, robe, armour). Babies left out.
-- {citizens, worn = {new, worn, threadbare, tattered}, without = {shoes,
-- legs, body}, tattered_wearers}.
-- Items of one kind (df.items_other_id) no one holds: not owned, worn,
-- carried, forbidden, in a job, at the depot or kept in a building (a
-- location's chest).
-- With `detail`, also what the free ones are (0.104.157: 118 free shoes and
-- 34 free cups lay in store while 63 went barefoot and 149 drank without a
-- cup): {n, kinds = {subtype = n}, races = {maker race = n}, stored = {in a
-- container, loose}}.
-- (0.104.168) WHY THE USED CUPS AREN'T HAULED. Teacheroar, 1 Nov: 34 free
-- cups lay loose in a dining hall (10) and a meeting hall (24) for hours with
-- 79 of 107 finished goods tiles free, 137 citizens drinking without a cup
-- (dwarves drink only from cups on a stockpile). For each free cup off the
-- piles, the first reason found (free_cups_detail.why):
--   location            in a zone of a location (a tavern keeps its own cups:
--                       DF doesn't haul them away; why_locations by type)
--   pile_refuses        no finished goods pile takes goblets at all
--   pile_refuses_material  piles take goblets, not of this material
--   pile_refuses_quality   ... not of this quality
--   links_only          the only piles that take it take from links only
--   no_room             the piles that take it are full
--   unreachable         on a tile walked to by no citizen
--   should_haul         nothing found: DF should haul it (a hauling backlog)
-- And every cup's flags (free_cups_detail.flags: forbid, owned, dump...), so
-- what is still unknown can be read from the next report in the game.
CUP_FLAGS = {'forbid', 'owned', 'dump', 'in_job', 'in_building', 'in_inventory', 'trader', 'on_ground', 'hidden'}
-- DF's finished goods "other materials" (DFHack's stockpiles plugin order):
-- wood first, bone, tooth, horn, pearl, shell (2-6), the glasses at 11-13
CUP_OTHER_MATS = {wood = 0, bone = 2, tooth = 3, horn = 4, pearl = 5, shell = 6,
                  green_glass = 11, clear_glass = 12, crystal_glass = 13}
CUP_DEPOT_REACH = 8      -- (0.104.168, review) a finished goods pile this near a depot is the caravans' (FEEDERS.Depot)

-- The cup's material: {kind = 'inorganic' | 'wood' | <glass> | 'other', index}.
function cup_material(it)
    local out = {kind = 'other'}
    pcall(function()
        local mi = dfhack.matinfo.decode(it)
        if not mi then return end
        if mi.inorganic then out.kind, out.index = 'inorganic', mi.index return end
        local tok = tostring(mi:getToken() or '')
        if tok:find('GLASS_GREEN') then out.kind = 'green_glass'
        elseif tok:find('GLASS_CLEAR') then out.kind = 'clear_glass'
        elseif tok:find('GLASS_CRYSTAL') then out.kind = 'crystal_glass'
        elseif mi.plant and mi.material and mi.material.flags.WOOD then out.kind = 'wood'
        elseif mi.material then
            -- (0.104.168, review) bone, horn, shell... by the material's own flags
            for _, k in ipairs({'BONE', 'TOOTH', 'HORN', 'PEARL', 'SHELL'}) do
                local okf, on = pcall(function() return mi.material.flags[k] end)
                if okf and on then out.kind = k:lower() break end
            end
        end
    end)
    return out
end

-- The fort's finished goods piles: {b, takes_goblets, links_only, free,
-- depot (the caravans' pile beside a depot), outdoor, x, y, z (its middle)}.
function cup_piles()
    local out = {}
    local depots = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do table.insert(depots, b) end
    end)
    pcall(function()
        local gob = df.item_type.GOBLET
        for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
            local okf, on = pcall(function() return sp.settings.flags.finished_goods end)
            if okf and on then
                local p = {b = sp, free = 0, x = (sp.x1 + sp.x2) // 2, y = (sp.y1 + sp.y2) // 2, z = sp.z}
                for _, dp in ipairs(depots) do
                    if dp.z == sp.z and sp.x2 >= dp.x1 - CUP_DEPOT_REACH and sp.x1 <= dp.x2 + CUP_DEPOT_REACH
                            and sp.y2 >= dp.y1 - CUP_DEPOT_REACH and sp.y1 <= dp.y2 + CUP_DEPOT_REACH then
                        p.depot = true
                    end
                end
                pcall(function() p.outdoor = dfhack.maps.getTileFlags(p.x, p.y, p.z).outside == true end)
                pcall(function() p.takes_goblets = sp.settings.finished_goods.type[gob] and true or false end)
                pcall(function() p.links_only = (sp.use_links_only == true or (tonumber(sp.use_links_only) or 0) ~= 0) end)
                pcall(function()
                    for y = sp.y1, sp.y2 do
                        for x = sp.x1, sp.x2 do
                            local des, occ = dfhack.maps.getTileFlags(x, y, sp.z)
                            if des and des.pile and not occ.item then p.free = p.free + 1 end
                        end
                    end
                end)
                table.insert(out, p)
            end
        end
    end)
    return out
end

-- Does this pile take this cup? true, or false and why.
function pile_takes_cup(p, it, mat)
    if not p.takes_goblets then return false, 'pile_refuses' end
    local fg = p.b.settings.finished_goods
    local okm, matok = pcall(function()
        if mat.kind == 'inorganic' then return fg.mats[mat.index] and true or false end
        local i = CUP_OTHER_MATS[mat.kind]
        if i then return fg.other_mats[i] and true or false end
        -- (0.104.168, review) a material not known here: taken only if the
        -- pile takes some "other material" at all
        for _, v in ipairs(fg.other_mats) do if v then return true end end
        return false
    end)
    if okm and matok == false then return false, 'pile_refuses_material' end
    local okq, qok = pcall(function() return fg.quality_core[it:getQuality()] and true or false end)
    if okq and qok == false then return false, 'pile_refuses_quality' end
    -- (0.104.168, review) the overall quality (with its decorations) too
    local okt, tok = pcall(function() return fg.quality_total[it:getOverallQuality()] and true or false end)
    if okt and tok == false then return false, 'pile_refuses_quality' end
    if p.links_only then return false, 'links_only' end
    if p.free <= 0 then return false, 'no_room' end
    return true
end

-- The location (its type) whose zone holds this tile, or nil.
function location_at(pos)
    local t
    pcall(function()
        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(pos) or {}) do
            local lid = zn.location_id
            if lid and lid >= 0 and not t then
                t = 'location'
                pcall(function()
                    local site = dfhack.world.getCurrentSite()
                    for _, b in ipairs(site.buildings) do
                        if b.id == lid then t = df.abstract_building_type[b:getType()] or 'location' end
                    end
                end)
            end
        end
    end)
    return t
end

function cup_citizen_groups()
    local g = {}
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local okg, w = pcall(dfhack.maps.getWalkableGroup, xyz2pos(dfhack.units.getPosition(u)))
            if okg and w and w ~= 0 then g[w] = true end
        end
    end)
    return g
end

local CUP_RANK = {pile_refuses = 1, pile_refuses_material = 2, pile_refuses_quality = 3, links_only = 4, no_room = 5}

-- Why this free cup (off the piles, at pos) isn't hauled: the first reason
-- (and, for a location, its type).
function cup_why(it, pos, ctx)
    local loc = location_at(pos)
    if loc then return 'location', loc end
    local mat = cup_material(it)
    local best, rank = nil, 0
    for _, p in ipairs(ctx.piles) do
        local ok, why = pile_takes_cup(p, it, mat)
        if ok then rank = 99 break end
        if (CUP_RANK[why] or 0) > rank then best, rank = why, CUP_RANK[why] end
    end
    if rank ~= 99 then return best or 'pile_refuses' end
    if next(ctx.groups) then
        local okg, w = pcall(dfhack.maps.getWalkableGroup, pos)
        if okg and w and w ~= 0 and not ctx.groups[w] then return 'unreachable' end
    end
    return 'should_haul'
end

-- (0.104.168, review) A tile in a zone indoors (a hall, a dining room), not
-- a location's (a tavern keeps its own) and not under the sky (a pasture).
function cup_in_indoor_hall(pos)
    local okz, zs = pcall(dfhack.buildings.findCivzonesAt, pos)
    if not okz or not zs or #zs == 0 or location_at(pos) then return false end
    local oko, out_ = pcall(function() return dfhack.maps.getTileFlags(pos.x, pos.y, pos.z).outside end)
    return not (oko and out_)
end

-- (0.104.168) What the AI can fix of it itself (`accept_cups` in the bridge):
-- when loose cups lie that no pile takes, the finished goods pile with the
-- most room is set to take goblets (and those cups' materials and quality);
-- loose forbidden cups in a hall (a zone, not a location's) are unforbidden.
-- Never the cups of a location (a tavern's), on a pile, or held by anything.
function accept_cups(dry_run)
    local ok, list = pcall(function() return df.global.world.items.other.GOBLET end)
    if not ok or not list then return {ok = false, error = 'no item list for cups'} end
    local piles = cup_piles()
    local out = {ok = true, dry_run = dry_run or nil, unforbidden = 0, piles_set = 0, materials_set = 0}
    local refused, forbidden = {}, {}
    for _, it in ipairs(list) do
        pcall(function()
            local f = it.flags
            if f.removed or f.garbage_collect or f.artifact or f.owned or f.in_inventory or f.in_job or f.trader
                    or f.in_building or f.dump or f.construction or not f.on_ground then return end
            local x, y, z = dfhack.items.getPosition(it)
            local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
            local okb, b = pcall(dfhack.buildings.findAtTile, pos)
            if okb and b and b:getType() == df.building_type.Stockpile then return end
            if location_at(pos) then return end
            if f.forbid then
                if cup_in_indoor_hall(pos) and dfhack.maps.getWalkableGroup(pos) ~= 0 then table.insert(forbidden, it) end
                return
            end
            -- (0.104.168, review) as the census counts them: in a container never here
            if dfhack.items.getContainer(it) then return end
            local mat = cup_material(it)
            local takes = false
            for _, p in ipairs(piles) do
                local okp, yes, why = pcall(pile_takes_cup, p, it, mat)
                if okp and (yes or why == 'no_room' or why == 'links_only') then takes = true break end
            end
            if not takes then table.insert(refused, {it = it, mat = mat, pos = pos}) end
        end)
    end
    out.cups_refused, out.cups_forbidden = #refused, #forbidden
    if #refused == 0 and #forbidden == 0 then
        return {ok = false, rejected = true,
                error = 'no loose cup is refused by every finished goods pile, nor forbidden in a hall'}
    end
    -- (0.104.168, review) the pile nearest the cups, with room, indoors and
    -- not the caravans' pile beside the depot (cups sent there would be sold)
    local best, best_d
    if #refused > 0 then
        for _, p in ipairs(piles) do
            if not p.links_only and p.free > 0 and not p.depot and not p.outdoor then
                local dist = 0
                for _, r in ipairs(refused) do
                    dist = dist + math.abs(r.pos.x - p.x) + math.abs(r.pos.y - p.y) + 10 * math.abs(r.pos.z - p.z)
                end
                if not best or dist < best_d then best, best_d = p, dist end
            end
        end
        if not best and #forbidden == 0 then
            return {ok = false, rejected = true,
                    error = ('%d loose cup(s) no pile takes, and no indoor finished goods pile with room (the '
                             .. 'depot\'s left to the caravans) to take them'):format(#refused)}
        end
    end
    if best then
        out.pile_id = best.b.id
        if dry_run then
            out.piles_set = best.takes_goblets and 0 or 1
        else
            local fg = best.b.settings.finished_goods
            pcall(function()
                if not fg.type[df.item_type.GOBLET] then fg.type[df.item_type.GOBLET] = true; out.piles_set = 1 end
            end)
            local seen = {}
            for _, r in ipairs(refused) do
                local key = r.mat.kind .. tostring(r.mat.index or '')
                if not seen[key] then
                    seen[key] = true
                    pcall(function()
                        if r.mat.kind == 'inorganic' then
                            if not fg.mats[r.mat.index] then
                                fg.mats[r.mat.index] = true; out.materials_set = out.materials_set + 1
                            end
                        elseif CUP_OTHER_MATS[r.mat.kind] and not fg.other_mats[CUP_OTHER_MATS[r.mat.kind]] then
                            fg.other_mats[CUP_OTHER_MATS[r.mat.kind]] = true; out.materials_set = out.materials_set + 1
                        end
                    end)
                end
                pcall(function()
                    local q = r.it:getQuality()
                    if not fg.quality_core[q] then fg.quality_core[q] = true; out.materials_set = out.materials_set + 1 end
                end)
                pcall(function()
                    local q = r.it:getOverallQuality()
                    if not fg.quality_total[q] then fg.quality_total[q] = true; out.materials_set = out.materials_set + 1 end
                end)
            end
        end
    end
    if dry_run then
        out.unforbidden = #forbidden
    else
        for _, it in ipairs(forbidden) do
            pcall(function() it.flags.forbid = false; out.unforbidden = out.unforbidden + 1 end)
        end
    end
    return out
end

local function bump(t, k) k = tostring(k or '?'); t[k] = (t[k] or 0) + 1 end

function free_items_count(kind, detail)
    local ok, list = pcall(function() return df.global.world.items.other[kind] end)
    if not ok or not list then return nil end
    local n = 0
    local d = detail and {kinds = {}, races = {}, stored = {}, wear = {}, place = {}} or nil
    -- (0.104.168) for cups: why each free one off the piles isn't hauled, and every cup's flags
    local cup_ctx
    if d and kind == 'GOBLET' then
        cup_ctx = {piles = cup_piles(), groups = cup_citizen_groups()}
        d.why, d.why_locations, d.flags, d.mats, d.why_at = {}, {}, {}, {}, {}
        d.piles = {finished_goods = #cup_ctx.piles, take_goblets = 0}
        for _, p in ipairs(cup_ctx.piles) do
            if p.takes_goblets then d.piles.take_goblets = d.piles.take_goblets + 1 end
        end
    end
    for _, it in ipairs(list) do
        if cup_ctx then
            pcall(function()
                if it.flags.removed or it.flags.garbage_collect then return end
                for _, fl in ipairs(CUP_FLAGS) do
                    local okv, v = pcall(function() return it.flags[fl] end)
                    if okv and v then bump(d.flags, fl) end
                end
                -- forbidden, loose in a hall (a zone, not a location's): accept_cups frees these
                if it.flags.forbid and it.flags.on_ground and not it.flags.in_inventory then
                    local x, y, z = dfhack.items.getPosition(it)
                    local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
                    if cup_in_indoor_hall(pos) and dfhack.maps.getWalkableGroup(pos) ~= 0 then
                        d.forbidden_in_halls = (d.forbidden_in_halls or 0) + 1
                    end
                end
            end)
        end
        local okf, free = pcall(function()
            local f = it.flags
            return not (f.removed or f.garbage_collect or f.artifact or f.owned or f.in_inventory or f.forbid
                        or f.in_job or f.trader or f.in_building or f.dump or f.hostile or f.construction)
        end)
        -- (0.104.157) a product still in its workshop (Teacheroar: 34 cups in the
        -- craftsdwarf's, the finished goods piles full) or one on a tile no
        -- dwarf can walk to (91 of 118 shoes) is no use to anyone yet
        local where = 'free'
        if okf and free then
            pcall(function()
                local hb = dfhack.items.getHolderBuilding(it)
                if hb and hb:getType() == df.building_type.Workshop then where = 'workshop' return end
                local x, y, z = dfhack.items.getPosition(it)
                local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
                if pos and dfhack.maps.getWalkableGroup(pos) == 0 then where = 'unwalkable' end
            end)
            if where ~= 'free' then
                if d then bump(d.place, where) end
                free = false
            end
        end
        if okf and free then
            n = n + 1
            if d then
                pcall(function() bump(d.kinds, it.subtype and it.subtype.id or 'none') end)
                pcall(function()
                    local cr = df.creature_raw.find(it.maker_race)
                    bump(d.races, cr and cr.creature_id or 'unknown')
                end)
                pcall(function() bump(d.stored, dfhack.items.getContainer(it) and 'container' or 'loose') end)
                pcall(function() bump(d.wear, it.wear) end)
                -- where: on a stockpile, on a tile no dwarf can walk to, or elsewhere
                pcall(function()
                    local x, y, z = dfhack.items.getPosition(it)
                    local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
                    local okb, b = pcall(dfhack.buildings.findAtTile, pos)
                    -- in a zone: the garbage dump (the old `tidy` sent owned things
                    -- there), a tavern, a dining hall... by DF's zone type
                    local zt
                    pcall(function()
                        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(pos) or {}) do
                            zt = zt or df.civzone_type[zn.type]
                        end
                    end)
                    if okb and b and b:getType() == df.building_type.Stockpile then bump(d.place, 'stockpile')
                    elseif zt then bump(d.place, 'zone ' .. tostring(zt))
                    else bump(d.place, 'elsewhere') end
                    -- (0.104.168) a cup off the piles: why DF leaves it there
                    if cup_ctx and not (okb and b and b:getType() == df.building_type.Stockpile) then
                        bump(d.mats, cup_material(it).kind)
                        local okw, why, loc = pcall(cup_why, it, pos, cup_ctx)
                        why = okw and why or 'unknown'
                        -- (0.104.168, review) in a bin or barrel: hauled with it, never by accept_cups
                        if dfhack.items.getContainer(it) then why, loc = 'in_container', nil end
                        bump(d.why, why)
                        if loc then bump(d.why_locations, loc) end
                        if #d.why_at < 4 then
                            table.insert(d.why_at, ('%s at x%d y%d z%d'):format(why, pos.x, pos.y, pos.z))
                        end
                    end
                    if not (okb and b and b:getType() == df.building_type.Stockpile) then
                        d.elsewhere_at = d.elsewhere_at or {}
                        if #d.elsewhere_at < 4 then
                            table.insert(d.elsewhere_at, ('x%d y%d z%d'):format(pos.x, pos.y, pos.z))
                        end
                    end
                end)
            end
        end
    end
    if d then d.n = n; return d end
    return n
end

local WORN_MODE
local function worn_mode()
    if WORN_MODE == nil then
        local ok, v = pcall(function() return df.unit_inventory_item.T_mode.Worn end)
        if not ok or v == nil then ok, v = pcall(function() return df.inv_item_role_type.Worn end) end
        WORN_MODE = (ok and v ~= nil) and v or 2
    end
    return WORN_MODE
end

local WEAR_NAMES = {[0] = 'new', [1] = 'worn', [2] = 'threadbare', [3] = 'tattered'}

function clothing_census(units)
    local out = {citizens = 0, worn = {new = 0, worn = 0, threadbare = 0, tattered = 0},
                 without = {shoes = 0, legs = 0, body = 0}, tattered_wearers = 0}
    local mode = worn_mode()
    for _, u in ipairs(units or dfhack.units.getCitizens()) do
        local okb, baby = pcall(dfhack.units.isBaby, u)
        if not (okb and baby) then
            out.citizens = out.citizens + 1
            local has, tattered = {}, false
            pcall(function()
                for _, inv in ipairs(u.inventory) do
                    if inv.mode == mode and inv.item then
                        local it = inv.item
                        local okt, tn = pcall(function() return df.item_type[it:getType()] end)
                        if okt and tn then has[tn] = true end
                        local okw, w = pcall(function() return it.wear end)
                        w = (okw and type(w) == 'number') and math.max(0, math.min(3, w)) or 0
                        local k = WEAR_NAMES[w]
                        out.worn[k] = out.worn[k] + 1
                        if w >= 3 then tattered = true end
                    end
                end
            end)
            if not has.SHOES then out.without.shoes = out.without.shoes + 1 end
            if not has.PANTS then out.without.legs = out.without.legs + 1 end
            if not has.ARMOR then out.without.body = out.without.body + 1 end
            if tattered then out.tattered_wearers = out.tattered_wearers + 1 end
        end
    end
    -- in store, free for a dwarf to take: footwear (DFHack's tailor only
    -- replaces worn-out clothes, so the barefoot never get any: Teacheroar,
    -- 1 Nov, 63 of 150 barefoot, "NoShoes" the worst stress) and cups (149 of
    -- 150 drank without one; the taverns keep theirs in their own chests)
    out.free_shoes, out.free_cups = free_items_count('SHOES'), free_items_count('GOBLET')
    out.free_shoes_detail = free_items_count('SHOES', true)
    out.free_cups_detail = free_items_count('GOBLET', true)
    return out
end

function free_bones(limit)
    local n = 0
    local ok, list = pcall(function() return df.global.world.items.other.CORPSEPIECE end)
    if not ok or not list then return 0 end
    for _, item in ipairs(list) do
        if limit and n >= limit then break end
        local f = item.flags
        local okb, bone = pcall(function() return item.corpse_flags.bone and not item.corpse_flags.unbutchered end)
        if okb and bone and not (f.forbid or f.in_job or f.removed or f.garbage_collect or f.dump
                or f.in_inventory or f.rotten) then
            n = n + 1
        end
    end
    return n
end

local function acquire_need(u)
    local ok, needs = pcall(function() return u.status.current_soul.personality.needs end)
    if not ok or not needs then return nil end
    for _, nd in ipairs(needs) do
        if df.need_type[nd.id] == 'AcquireObject' then return nd end
    end
end

-- Does `u` like what `item` is made of, or its kind (their preferences)?
local function pref_name(p)
    -- (13c) the global enum: unit_preference.type is a unitpref_type (there is
    -- no T_type), so this was always nil and no trinket matched a dwarf's likes
    local ok, n = pcall(function() return df.unitpref_type[p.type] end)
    return ok and n or nil
end

function likes(u, item)
    local ok, prefs = pcall(function() return u.status.current_soul.preferences end)
    if not ok or not prefs then return false end
    local okm, mt, mi = pcall(function() return item:getMaterial(), item:getMaterialIndex() end)
    local okt, it, st = pcall(function() return item:getType(), item:getSubtype() end)
    for _, p in ipairs(prefs) do
        local n = pref_name(p)
        if n == 'LikeMaterial' and okm and p.mattype == mt and p.matindex == mi then return true end
        if n == 'LikeItem' and okt and p.item_type == it and (p.item_subtype == -1 or p.item_subtype == st) then
            return true
        end
    end
    return false
end

-- Up to `max` dwarves who badly want something get a trinket each (most
-- distracted first; to each the most valuable one they like, else the most
-- valuable left).
function give_trinkets(max, dry_run)
    local wanting = {}
    -- (residents too: the fort's poets and bards count in the needs report,
    -- and getCitizens(true) left them out: "nobody wants" while 16 did)
    for _, u in ipairs(dfhack.units.getCitizens()) do
        local nd = acquire_need(u)
        if nd and nd.focus_level <= ACQUIRE_DISTRACTED and dfhack.units.isAdult(u) and u.mood == -1 then
            table.insert(wanting, {u = u, nd = nd})
        end
    end
    table.sort(wanting, function(a, b) return a.nd.focus_level < b.nd.focus_level end)
    if #wanting == 0 then return {ok = false, rejected = true, error = 'nobody wants something to own'} end
    local items = free_trinkets(200)
    table.sort(items, function(a, b) return dfhack.items.getValue(a) > dfhack.items.getValue(b) end)
    if #items == 0 then
        return {ok = false, rejected = true, wanting = #wanting,
                error = 'no free rings, amulets, figurines or other trinkets to give'}
    end
    local n = math.min(max or 10, #wanting, #items)
    if dry_run then return {ok = true, dry_run = true, would_give = n, wanting = #wanting, trinkets = #items} end
    local given, liked = 0, 0
    for i = 1, n do
        local w, pick = wanting[i], 1
        for j, item in ipairs(items) do
            if likes(w.u, item) then pick = j break end
        end
        local item = table.remove(items, pick)
        local okg, r = pcall(dfhack.items.setOwner, item, w.u)
        if okg and r ~= false then
            w.nd.focus_level = math.max(w.nd.focus_level, SATISFIED_FOCUS)
            given = given + 1
            if pick > 1 or likes(w.u, item) then liked = liked + 1 end
        end
    end
    return {ok = given > 0, given = given, liked = liked, wanting = #wanting, trinkets_left = #items,
            error = given == 0 and 'the game took no trinket' or nil}
end


-- --- staffing locations (0.84) ---------------------------------------------------
--
-- A location's occupations (DF's location screen: a hospital's doctor,
-- diagnostician, surgeon and bone doctor, a library's scribes, a tavern's
-- keeper) are records the game makes vacant; the player gives each to a
-- citizen. DFHack's own notifications count a hospital as working only with
-- someone in its posts (internal/notify: DOCTOR or DIAGNOSTICIAN, BONE_DOCTOR,
-- SURGEON), and region2's patients waited 130 days for a diagnosis. The AI
-- fills a vacant post with the citizen best at its trade: never a child, a
-- soldier, an office holder, one already holding a post, or one in a mood.
-- The record gets the dwarf's figure and unit, the dwarf's occupations list
-- the record (as the screen does); read back, undone if not seen.
STAFF_SKILLS = {DOCTOR = {'DRESS_WOUNDS', 'DIAGNOSE', 'SURGERY', 'SET_BONE', 'SUTURE'}, DIAGNOSTICIAN = {'DIAGNOSE'},
                SURGEON = {'SURGERY'}, BONE_DOCTOR = {'SET_BONE'}, SCRIBE = {'WRITING'},
                TAVERN_KEEPER = {}}

local function find_location(loc_id)
    local site = dfhack.world.getCurrentSite()
    for _, b in ipairs(site and site.buildings or {}) do
        if b.id == loc_id then return b end
    end
end

local function skill_of(u, names)
    local n = 0
    for _, name in ipairs(names) do
        pcall(function() n = n + dfhack.units.getNominalSkill(u, df.job_skill[name], true) end)
    end
    return n
end

STAFF_HURT_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
                 'rq_setting', 'rq_traction', 'rq_crutch'}

local function can_staff(u)
    if not dfhack.units.isAdult(u) or u.military.squad_id ~= -1 then return false end
    local okm, mood = pcall(function() return u.mood end)
    if okm and mood ~= nil and mood ~= -1 then return false end
    local okn, list = pcall(dfhack.units.getNoblePositions, u)
    if okn and list and #list > 0 then return false end
    -- (0.104.111) never a wounded dwarf: Teacheroar's surgeon and bone
    -- doctor were patients themselves while five waited up to 820 days
    -- (0.104.150) wounded = bleeding or waiting for a treatment (DF's rq_
    -- flags): the wound list keeps old scars, so after Teacheroar's massacre
    -- nobody was "free" and a tavern stood without a keeper for days
    local okw, wounded = pcall(function()
        if (u.body.blood_count or 0) < (u.body.blood_max or 0) then return true end
        local f = u.health and u.health.flags
        if not f then return false end
        for _, k in ipairs(STAFF_HURT_RQ) do if f[k] then return true end end
        return false
    end)
    if okw and wounded then return false end
    local oko, n = pcall(function() return #u.occupations end)
    return oko and n == 0
end

-- (0.104.111) A post given back: its holder (a doctor who is a patient
-- himself) leaves it, so the staffing rule fills it with someone who can
-- work. {ok, post, name}.
function vacate_post(loc_id, unit_id, dry_run, txt)
    local loc = find_location(loc_id)
    if not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local post
    for _, o in ipairs(loc.occupations) do
        if o.unit_id == unit_id then post = o; break end
    end
    if not post then return {ok = false, rejected = true, error = 'that dwarf holds no post there'} end
    local u = df.unit.find(unit_id)
    local name = u and (txt or tostring)(dfhack.units.getReadableName(u)) or tostring(unit_id)
    local job = tostring(df.occupation_type[post.type] or 'post'):lower():gsub('_', ' ')
    if dry_run then return {ok = true, dry_run = true, post = job, name = name} end
    post.histfig_id, post.unit_id = -1, -1
    if u then
        for i = #u.occupations - 1, 0, -1 do
            if u.occupations[i] == post or u.occupations[i].id == post.id then u.occupations:erase(i) end
        end
    end
    return {ok = true, post = job, name = name}
end

function staff_location(loc_id, occ_type, dry_run, txt)
    local loc = find_location(loc_id)
    if not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local want = STAFF_SKILLS[occ_type]
    if not want then return {ok = false, rejected = true, error = 'the AI does not fill ' .. tostring(occ_type) .. ' posts'} end
    local post
    for _, o in ipairs(loc.occupations) do
        if df.occupation_type[o.type] == occ_type and o.histfig_id == -1 and o.unit_id == -1 then post = o; break end
    end
    if not post then return {ok = false, rejected = true, error = 'no vacant ' .. occ_type:lower() .. ' post there'} end
    local best, best_n
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if can_staff(u) and u.hist_figure_id ~= -1 then
            local n = skill_of(u, want)
            if not best or n > best_n then best, best_n = u, n end
        end
    end
    if not best then return {ok = false, rejected = true, error = 'nobody free to take the post'} end
    local name = (txt or tostring)(dfhack.units.getReadableName(best))
    local job = occ_type:lower():gsub('_', ' ')
    if dry_run then return {ok = true, dry_run = true, post = job, unit_id = best.id, name = name, skill = best_n} end
    post.histfig_id = best.hist_figure_id
    post.unit_id = best.id
    best.occupations:insert('#', post)
    -- read back: the post names the dwarf, and the dwarf lists the post
    local seen = false
    for _, o in ipairs(best.occupations) do
        if o == post or o.id == post.id then seen = true end
    end
    if post.unit_id ~= best.id or not seen then
        post.histfig_id, post.unit_id = -1, -1
        for i = #best.occupations - 1, 0, -1 do
            if best.occupations[i] == post then best.occupations:erase(i) end
        end
        return {ok = false, error = 'the post did not take ' .. name .. ', so it was undone'}
    end
    local okl, labors = pcall(function() return give_post_labors(best, occ_type) end)
    return {ok = true, post = job, unit_id = best.id, name = name, skill = best_n,
            labors = okl and #labors > 0 and labors or nil}
end

-- (0.84) Read only: what the game writes for an occupation, so the AI can
-- one day create a post itself (the fort's locations have no post records
-- until the player assigns one: region2, spring y62). Every occupation the
-- world has (up to 12, this site's first), its fields, and its holder's
-- figure links that point at it; the fort's locations with their post counts.
local function fields_of(o, names)
    local out = {}
    for _, k in ipairs(names) do
        local ok, v = pcall(function() return o[k] end)
        if ok and (type(v) == 'number' or type(v) == 'string' or type(v) == 'boolean') then out[k] = v end
    end
    return out
end

function probe_occupations(txt)
    local site = dfhack.world.getCurrentSite()
    local out = {next_id = nil, total = 0, here = {}, elsewhere = {}, locations = {}}
    pcall(function() out.next_id = df.global.occupation_next_id end)
    local all = df.global.world.occupations.all
    out.total = #all
    for _, o in ipairs(all) do
        local here = site and o.site_id == site.id
        local list = here and out.here or out.elsewhere
        if #out.here + #out.elsewhere < 12 and (here or #out.elsewhere < 4) then
            local e = fields_of(o, {'id', 'histfig_id', 'unit_id', 'location_id', 'site_id', 'group_id',
                                    'next_service_order_id'})
            e.type = df.occupation_type[o.type] or tostring(o.type)
            local hf = o.histfig_id ~= -1 and df.historical_figure.find(o.histfig_id)
            if hf then
                e.links = {}
                for _, l in ipairs(hf.entity_links) do
                    local okid, oid = pcall(function() return l.occupation_id end)
                    if okid and oid == o.id then
                        table.insert(e.links, {kind = tostring(l._type), fields = fields_of(l, {'entity_id',
                            'link_strength', 'occupation_id', 'start_year', 'end_year'})})
                    end
                end
                for _, l in ipairs(hf.site_links) do
                    local okid, oid = pcall(function() return l.occupation_id end)
                    if okid and oid == o.id then
                        table.insert(e.links, {kind = tostring(l._type), fields = fields_of(l, {'site', 'sub_id',
                            'entity', 'occupation_id', 'link_strength'})})
                    end
                end
                pcall(function() e.hf_occupation = hf:getOccupation() end)
            end
            local u = o.unit_id ~= -1 and df.unit.find(o.unit_id)
            if u then
                e.unit_lists_it = false
                for _, uo in ipairs(u.occupations) do if uo.id == o.id then e.unit_lists_it = true end end
                e.name = (txt or tostring)(dfhack.units.getReadableName(u))
            end
            table.insert(list, e)
        end
    end
    for _, b in ipairs(site and site.buildings or {}) do
        local okp, n = pcall(function() return #b.occupations end)
        if okp then
            table.insert(out.locations, {id = b.id, type = df.abstract_building_type[b:getType()], posts = n})
        end
    end
    return out
end

-- (0.85) A post the game hasn't made yet, made as DF makes it. Read from the
-- game (region2, spring y62, logs/probe-occupations.json): opening the
-- hospital's posts screen made one vacant record of each kind (doctor,
-- diagnostician, surgeon, bone doctor): its id from occupation_next_id, its
-- type, location_id = the location's id, site_id = the fort's site, holder
-- -1 (figure and unit), group_id -1; in world.occupations.all and the
-- location's occupations; a fort's post has no figure links (a filled one
-- only names the figure and unit, and the dwarf lists it). Only kinds the
-- AI staffs (POST_KINDS), one record a kind, never one that exists.
POST_KINDS = {HOSPITAL = {'DOCTOR', 'DIAGNOSTICIAN', 'SURGEON', 'BONE_DOCTOR'}, INN_TAVERN = {'TAVERN_KEEPER'},
              LIBRARY = {'SCRIBE'}}

function add_posts(loc_id, kinds, dry_run)
    local site = dfhack.world.getCurrentSite()
    local loc = find_location(loc_id)
    if not site or not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local ltype = df.abstract_building_type[loc:getType()]
    local allowed = {}
    for _, k in ipairs(POST_KINDS[ltype] or {}) do allowed[k] = true end
    local have = {}
    for _, o in ipairs(loc.occupations) do have[df.occupation_type[o.type] or ''] = true end
    local add = {}
    for _, k in ipairs(kinds or POST_KINDS[ltype] or {}) do
        if allowed[k] and not have[k] and df.occupation_type[k] ~= nil then table.insert(add, k) end
    end
    if #add == 0 then return {ok = false, rejected = true, error = 'no post to add there'} end
    if dry_run then return {ok = true, dry_run = true, posts = add} end
    local made = {}
    for _, k in ipairs(add) do
        local o = df.occupation:new()
        o.id = df.global.occupation_next_id
        o.type = df.occupation_type[k]
        o.histfig_id, o.unit_id = -1, -1
        o.location_id = loc.id
        o.site_id = site.id
        o.group_id = -1
        df.global.occupation_next_id = o.id + 1
        df.global.world.occupations.all:insert('#', o)
        loc.occupations:insert('#', o)
        table.insert(made, k)
    end
    return {ok = true, posts = made}
end

-- (0.87.3) A post's labours. Read from the game (region2, 6 Timber y62): the
-- diagnostician you gave by hand had DIAGNOSE, but the surgeon, bone doctor
-- and doctor the AI seated had none of SURGERY, BONE_SETTING or DIAGNOSE, so
-- a dwarf needing a bone set lay in a hospital bed 355 days with no job ever
-- made. The game's screen evidently turns a post's labours on; the AI does
-- the same: each holder of a post gets its labours (the unit's own labour
-- flags), read back.
POST_LABORS = {DOCTOR = {'DIAGNOSE', 'SURGERY', 'BONE_SETTING', 'SUTURING', 'DRESSING_WOUNDS'},
               DIAGNOSTICIAN = {'DIAGNOSE'}, SURGEON = {'SURGERY', 'SUTURING'},
               BONE_DOCTOR = {'BONE_SETTING'}}

function give_post_labors(u, post)
    local added = {}
    for _, l in ipairs(POST_LABORS[post] or {}) do
        local id = df.unit_labor[l]
        if id ~= nil and not u.status.labors[id] then
            u.status.labors[id] = true
            if u.status.labors[id] then table.insert(added, l) end
        end
    end
    return added
end

function staff_labors(loc_id, dry_run, txt)
    local loc = find_location(loc_id)
    if not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local out = {}
    for _, o in ipairs(loc.occupations) do
        local post = df.occupation_type[o.type]
        local u = o.unit_id ~= -1 and df.unit.find(o.unit_id)
        if u and POST_LABORS[post] then
            local missing = {}
            for _, l in ipairs(POST_LABORS[post]) do
                local id = df.unit_labor[l]
                if id ~= nil and not u.status.labors[id] then table.insert(missing, l) end
            end
            if #missing > 0 then
                local added = dry_run and missing or give_post_labors(u, post)
                table.insert(out, {name = (txt or tostring)(dfhack.units.getReadableName(u)), post = post:lower():gsub('_', ' '),
                                   labors = added})
            end
        end
    end
    if #out == 0 then return {ok = false, rejected = true, error = 'every post holder has the labours of the post'} end
    return {ok = true, dry_run = dry_run or nil, given = out}
end

-- --- (0.104.168) vermin hunters ----------------------------------------------
--
-- Teacheroar, 1 Nov: 15-16 citizens a month upset at being "accosted by"
-- vermin they hate (NEAR_HATED_VERMIN, stress 25-50 each). The fort's
-- answer in DF is a vermin hunter (a creature whose caste has HUNTS_VERMIN:
-- the cat), loose in the fort, catching the vermin in the halls and food
-- stores. DFHack's autobutcher (on in this fort, for a herd of 1,077) culls
-- every kind down to 2/4/2/4 and spares only the named or nicknamed, pets,
-- war and hunting animals, the pregnant and those up for adoption
-- (plugins/autobutcher.cpp, isProtectedUnit): the cats went with the ducks.
-- The AI keeps a few by giving them a nickname (MOUSER_NICK), which
-- autobutcher respects and the player can see and change.
MOUSER_NICK = 'Mouser'

local function hunts_vermin(u)
    local ok, yes = pcall(function()
        local cr = df.creature_raw.find(u.race)
        return cr ~= nil and cr.caste[u.caste].flags.HUNTS_VERMIN
    end)
    return ok and yes == true
end

local function fort_animal(u)
    local ok, yes = pcall(function()
        if dfhack.units.isDead(u) or not dfhack.units.isAnimal(u) then return false end
        return dfhack.units.isFortControlled(u) or (dfhack.units.isTame(u) and dfhack.units.isOwnCiv(u))
    end)
    return ok and yes == true
end

local function nickname(u)
    local ok, n = pcall(function() return u.name.nickname end)
    return ok and n or ''
end

local function kept_hunter(u)
    local ok, yes = pcall(function()
        return dfhack.units.isPet(u) or u.name.has_name or (u.name.nickname or '') ~= ''
            or dfhack.units.isAvailableForAdoption(u)
    end)
    return ok and yes == true
end

-- The fort's vermin hunters: {n, loose, caged, marked (for slaughter),
-- kept (loose and safe from autobutcher: pets, named, up for adoption), mousers
-- (nicknamed by the AI), races = {CAT = n}}.
function vermin_hunters(units)
    local out = {n = 0, loose = 0, caged = 0, marked = 0, kept = 0, mousers = 0, races = {}}
    for _, u in ipairs(units or df.global.world.units.active) do
        if fort_animal(u) and hunts_vermin(u) then
            out.n = out.n + 1
            local okr, r = pcall(function() return df.creature_raw.find(u.race).creature_id end)
            r = okr and r or tostring(u.race)
            out.races[r] = (out.races[r] or 0) + 1
            local okc, caged = pcall(function() return u.flags1.caged end)
            local in_cage = okc and caged
            if in_cage then out.caged = out.caged + 1 else out.loose = out.loose + 1 end
            local okm, marked = pcall(function() return u.flags2.slaughter end)
            if okm and marked then out.marked = out.marked + 1 end
            if kept_hunter(u) and not in_cage then out.kept = out.kept + 1 end     -- loose and safe
            if nickname(u) == MOUSER_NICK then out.mousers = out.mousers + 1 end
        end
    end
    return out
end

-- Keep `want` vermin hunters safe from the butcher: those already safe
-- count; then loose ones, adults first, the marked unmarked, each given the
-- nickname MOUSER_NICK. Never a caged one (it hunts nothing).
function keep_mousers(want, dry_run, txt, units)
    want = math.max(1, math.min(tonumber(want) or 6, 20))
    local kept, cands = 0, {}
    for _, u in ipairs(units or df.global.world.units.active) do
        if fort_animal(u) and hunts_vermin(u) then
            local okc, caged = pcall(function() return u.flags1.caged end)
            if kept_hunter(u) then
                if not (okc and caged) then kept = kept + 1 end
            elseif not (okc and caged) then
                local oka, adult = pcall(dfhack.units.isAdult, u)
                table.insert(cands, {u = u, adult = oka and adult or false})
            end
        end
    end
    if kept >= want then return {ok = true, unchanged = true, kept = kept} end
    if #cands == 0 then
        return {ok = false, rejected = true, kept = kept,
                error = kept > 0 and 'no other loose vermin hunter to keep' or 'no loose cat or other vermin hunter in the fort'}
    end
    table.sort(cands, function(a, b)
        if a.adult ~= b.adult then return a.adult end
        return a.u.id < b.u.id
    end)
    local named, unmarked = {}, 0
    for _, c in ipairs(cands) do
        if kept >= want then break end
        if not dry_run then
            local okm, marked = pcall(function() return c.u.flags2.slaughter end)
            if okm and marked then c.u.flags2.slaughter = false; unmarked = unmarked + 1 end
            pcall(dfhack.units.setNickname, c.u, MOUSER_NICK)
            if nickname(c.u) ~= MOUSER_NICK then
                return {ok = #named > 0, kept = kept, named = named, unmarked = unmarked,
                        error = 'the game did not take the nickname'}
            end
        end
        kept = kept + 1
        local okn, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(c.u)) end)
        table.insert(named, okn and n or tostring(c.u.id))
    end
    return {ok = true, kept = kept, named = named, unmarked = unmarked, dry_run = dry_run or nil}
end

-- --- the burrows that hold dwarves (lua/ai-society-burrows.lua) ---------------------
--
-- (13c) The recreation, hospital and calm-down burrows moved there; every
-- name they export is still reachable here (the bridge calls them as
-- reqscript('ai-society').<name>). Looked up on call: that module loads this
-- one, so this one must not load it while loading.
local function burrows() return reqscript('ai-society-burrows') end
for _, name in ipairs({'fill_recreation', 'badly_wants_friends', 'recreation_status', 'recreation_tick', 'hospital_zones',
                       'well_gives_water', 'is_patient', 'hospital_burrow_status', 'hospital_burrow_tick', 'calm_burrow_status',
                       'calm_burrow_tick'}) do
    _ENV[name] = function(...) return burrows()[name](...) end
end
