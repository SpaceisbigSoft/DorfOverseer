-- Things the AI sets up so the player doesn't have to:
--   * a civilian-alert shelter: a burrow named "AI shelter" covering the
--     inside of the fort (not caverns, not outside), registered as the
--     civilian alert's burrow; (0.105.23) kept away from entrances not shut
--   * grazing animals put into a pasture with room for them (the AI makes
--     new pastures with ai-builder.make_pasture)
--@module = true

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

local function find_burrow(name)
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if tostring(b.name):lower() == name:lower() then return b end
    end
    return nil
end

local function new_burrow(name)
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
local function entrance_shut(e)
    if not e.sealed or type(e.equipment) ~= 'table' or #e.equipment == 0 then return false end
    for _, g in ipairs(e.equipment) do
        local ok, shut = pcall(function()
            local b = df.building.find(g.id)
            if not b then return false end
            if g.kind == 'bridge' then return b.gate_flags.raised == true end
            return b.door_flags.forbidden == true
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
    for _, e in ipairs(G.entrances) do
        local okp = pcall(function() return e.x + e.y + e.z end)
        if okp and not entrance_shut(e) then
            local why = (not e.sealed or #(e.equipment or {}) == 0)
                and (e.closing and 'its gate still to come' or 'no gate') or 'its gate open'
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

-- Fills the burrow; returns the tiles in it and what was left out:
-- {excluded, open_entrances, entrances_scanned, fallback, note, why}.
function fill_shelter(b)
    local info = {excluded = 0, margin = SHELTER_MARGIN, margin_levels = SHELTER_MARGIN_Z}
    local lo, hi = fort_levels()
    if not lo then return 0, info end
    local okl, open, scanned = pcall(open_entrances)
    if not okl then open, scanned, info.entrances_error = {}, false, tostring(open):sub(1, 120) end
    info.entrances_scanned = scanned
    info.open_entrances = #open
    local n = 0
    local held = {}          -- the tiles left out: {block, x, y, far}
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
                        if OPEN[shape] then
                            local near, far = false, nil
                            if near_list then near = near_entrance(near_list, bx + x, by + y, z) end
                            if near then
                                -- how far, from every open entrance (for the fallback)
                                if #open > #near_list then
                                    far = select(2, near_entrance(open, bx + x, by + y, z))
                                else
                                    far = select(2, near_entrance(near_list, bx + x, by + y, z))
                                end
                                table.insert(held, {block, x, y, far or 0})
                            else
                                dfhack.burrows.setAssignedBlockTile(b, block, x, y, true)
                                n = n + 1
                            end
                        end
                    end
                end
            end
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
            local back = 0
            for _, t in ipairs(held) do
                if n >= need then break end
                dfhack.burrows.setAssignedBlockTile(b, t[1], t[2], t[3], true)
                n, back = n + 1, back + 1
            end
            info.excluded = #held - back
            info.fallback = true
            info.taken_back = back
            info.note = ('only %d tiles away from the open entrances (needs %d): the %d farthest of the left-out tiles taken back')
                :format(n - back, need, back)
        end
    end
    return n, info
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
            table.insert(out, {zone = z, spare = area_of(z) - pen_load(z)})
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
        local fort = df.historical_entity.find(df.global.plotinfo.group_id)
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
    local ok, d = pcall(dfhack.persistent.getSiteData, IC_KEY, {})
    return ok and type(d) == 'table' and d or {}
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
    if f.owned or f.forbid or f.in_job or f.trader or f.in_building or f.removed or f.garbage_collect
            or f.construction or f.encased or f.hostile or f.dump or f.artifact or f.on_fire then
        return false
    end
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
function trinket_census()
    local out = {free = 0, owned = 0, in_job = 0, trade = 0, forbidden = 0, in_building = 0, carried = 0, other = 0}
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
                if okk and (k == 'other' or k == 'in_job') then
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
    local now = df.global.cur_year * 403200 + df.global.cur_year_tick
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
                local okt, when = pcall(function() return em.year * 403200 + em.year_tick end)
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

-- --- (0.104.78) the recreation burrow ----------------------------------------
--
-- Players' cure for dwarves too busy to meet their needs (Steam forum, 2024):
-- a burrow over the taverns, temples and library, the low-mood moved in, so
-- they take no work and spend their time where the friends, the drink and the
-- gods are. Enxah: 42 badly wanting friends, 18 miserable, hardly anyone idle.
-- The burrow also covers the dining halls, the bedrooms and the food and
-- drink piles (never the hospital: 0.104.127), so nobody in it goes hungry, thirsty or sleepless.
-- At most `max` dwarves at a time: very unhappy or worse, not a soldier, not
-- a child, not a patient; each goes back to work when no longer unhappy, or
-- after `days` days. Its members are kept in the save.
RECREATION_NAME = 'AI recreation'
RECREATION_KEY = 'ai-overseer/recreation'
-- (0.104.127) never the hospital: Teacheroar's massacre (31 Oct, ~45 dead, 39 strangled
-- by citizens) happened in its hospital zone, x95-101 y40-48 z167, where 124 wounded lay
-- on the floor and the burrow kept the unhappiest dwarves (patients never join it)
local REC_ZONES = {MeetingHall = true, DiningHall = true, Bedroom = true}

local function rec_state()
    local ok, d = pcall(dfhack.persistent.getSiteData, RECREATION_KEY, {members = {}})
    d = ok and type(d) == 'table' and d or {members = {}}
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}      -- let out (id -> when): not back for `days`
    return d
end

local function zone_tiles(b, burrow)
    local n = 0
    for y = b.y1, b.y2 do
        for x = b.x1, b.x2 do
            local okc, inside = pcall(dfhack.buildings.containsTile, b, x, y)
            if not okc or inside then
                if dfhack.burrows.setAssignedTile(burrow, xyz2pos(x, y, b.z), true) then n = n + 1 end
            end
        end
    end
    return n
end

-- The burrow's tiles: every zone of the fort's locations (tavern, temple,
-- library...), the meeting, dining, bedroom and hospital zones, and the
-- stockpiles that take food or drink.
function fill_recreation(burrow)
    dfhack.burrows.clearTiles(burrow)
    local n, loc_zone, hosp_zone = 0, {}, {}
    pcall(function()
        for _, b in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                local hosp = df.abstract_building_type[b:getType()] == 'HOSPITAL'
                for _, bid in ipairs(b:getContents().building_ids) do
                    if hosp then hosp_zone[bid] = true else loc_zone[bid] = true end
                end
            end)
        end
    end)
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        if t == df.building_type.Civzone then
            local kind = df.civzone_type[b.type] or ''
            if not hosp_zone[b.id] and kind ~= 'Hospital' and (loc_zone[b.id] or REC_ZONES[kind]) then
                n = n + zone_tiles(b, burrow)
            end
        elseif t == df.building_type.Stockpile then
            local okf, food = pcall(function() return b.settings.flags.food end)
            if okf and food then n = n + zone_tiles(b, burrow) end
        end
    end
    return n
end

-- (0.104.168) never a noble: the burrow covers no office, and a noble's
-- duties wait there (the mayor meets the citizens who come to complain, DF's
-- MEET_WORKERS; the manager takes up the work orders). Teacheroar, 1 Nov: 24
-- citizens "unable to complain" while the mayor was always in meetings.
local function rec_noble(u)
    local ok, list = pcall(dfhack.units.getNoblePositions, u)
    return ok and list ~= nil and #list > 0
end

local function rec_base(u)
    if not dfhack.units.isAdult(u) or u.military.squad_id ~= -1 then return false end
    if rec_noble(u) then return false end
    -- (0.104.169) never one in a tantrum, by the friends' places either: the
    -- recreation burrow is the taverns and halls, where the others are
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    if okm and (m == 'Tantrum' or m == 'Enraged') then return false end
    local okh, sick = pcall(function() return u.health and u.health.flags.needs_healthcare end)
    return not (okh and sick)
end

-- (0.104.80) BeWithFriends badly unmet: its focus level (lower is worse), else nil
function badly_wants_friends(u)
    local ok, f = pcall(function()
        for _, nd in ipairs(u.status.current_soul.personality.needs) do
            if df.need_type[nd.id] == 'BeWithFriends' and nd.focus_level <= -10000 then return nd.focus_level end
        end
    end)
    return ok and f or nil
end

local function rec_eligible(u)
    if not rec_base(u) then return false end
    -- (0.104.139) never one in a tantrum or a rage: they start the fights
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    if okm and (m == 'Tantrum' or m == 'Enraged') then return false end
    local okc, cat = pcall(dfhack.units.getStressCategory, u)
    return okc and type(cat) == 'number' and cat <= 1
end

-- Who is in the burrow now, for the report.
function recreation_status()
    local d = rec_state()
    local out = {members = 0, burrow = nil}
    local b = find_burrow(RECREATION_NAME)
    if b then out.burrow = b.id end
    for _ in pairs(d.members) do out.members = out.members + 1 end
    for _ in pairs(d.friends or {}) do out.for_friends = (out.for_friends or 0) + 1 end   -- (0.104.80)
    return out
end

function recreation_tick(max, days, dry_run, txt, friends, friend_days)
    max, days = max or 8, days or 28
    friends, friend_days = friends or 0, friend_days or 7
    local d = rec_state()
    d.friends = d.friends or {}
    local now = df.global.cur_year * 403200 + df.global.cur_year_tick
    local b = find_burrow(RECREATION_NAME)
    if not b and dry_run then
        return {ok = true, dry_run = true, note = 'the burrow would be made'}
    end
    local made = false
    if not b then b = new_burrow(RECREATION_NAME); made = true end
    local tiles
    if made or not d.filled or now - d.filled >= 7 * 1200 then
        if not dry_run then tiles = fill_recreation(b); d.filled = now end
    end
    local released, added = {}, {}
    -- back to work: recovered, gone, drafted, or in long enough
    for id, since in pairs(d.members) do
        local u = df.unit.find(tonumber(id))
        local keep = u and dfhack.units.isCitizen(u) and u.military.squad_id == -1
        if keep and rec_noble(u) then keep = false end     -- (0.104.168) a noble since moved in: out
        local okc, cat = false, nil
        if keep then okc, cat = pcall(dfhack.units.getStressCategory, u) end
        if keep and d.friends[id] then
            -- (0.104.80) in for friends: out after `friend_days`, or once the need is met
            if now - (tonumber(since) or now) >= friend_days * 1200 or not badly_wants_friends(u) then keep = false end
        elseif keep and ((okc and cat >= 3) or now - (tonumber(since) or now) >= days * 1200) then keep = false end
        if not keep then
            if not dry_run and u then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            d.members[id] = nil
            d.friends[id] = nil
            d.out[id] = now
            table.insert(released, u and (txt or tostring)(dfhack.units.getReadableName(u)) or id)
        end
    end
    local count, fcount = 0, 0
    for id in pairs(d.members) do
        if d.friends[id] then fcount = fcount + 1 else count = count + 1 end
    end
    -- the most stressed eligible first
    local cands = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local was = tonumber(d.out[tostring(u.id)])
        if was and now - was >= days * 1200 then d.out[tostring(u.id)] = nil; was = nil end
        if not d.members[tostring(u.id)] and not was and rec_eligible(u) then
            local okc, cat = pcall(dfhack.units.getStressCategory, u)
            table.insert(cands, {u = u, cat = okc and cat or 9})
        end
    end
    table.sort(cands, function(a, c) if a.cat ~= c.cat then return a.cat < c.cat end return a.u.id < c.u.id end)
    for _, c in ipairs(cands) do
        if count >= max then break end
        if not dry_run then dfhack.burrows.setAssignedUnit(b, c.u, true) end
        d.members[tostring(c.u.id)] = now
        count = count + 1
        table.insert(added, (txt or tostring)(dfhack.units.getReadableName(c.u)))
    end
    -- (0.104.80) a few places for civilians who badly want friends: a week
    -- where the others are (Enxah, autumn y76: 42 badly, 21 of them with no
    -- close friend, 11 of 14 idle dwarves in no meeting zone)
    if friends > 0 and fcount < friends then
        local fc = {}
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local key = tostring(u.id)
            if not d.members[key] and not d.out[key] and rec_base(u) then
                local f = badly_wants_friends(u)
                if f then table.insert(fc, {u = u, f = f}) end
            end
        end
        table.sort(fc, function(a, c) if a.f ~= c.f then return a.f < c.f end return a.u.id < c.u.id end)
        for _, c in ipairs(fc) do
            if fcount >= friends then break end
            if not dry_run then dfhack.burrows.setAssignedUnit(b, c.u, true) end
            d.members[tostring(c.u.id)] = now
            d.friends[tostring(c.u.id)] = true
            fcount = fcount + 1
            table.insert(added, (txt or tostring)(dfhack.units.getReadableName(c.u)) .. ' (for friends)')
        end
    end
    if not dry_run then pcall(dfhack.persistent.saveSiteData, RECREATION_KEY, d) end
    if #added == 0 and #released == 0 and not tiles then
        -- (0.104.79) nothing to change is no refusal: the rule waits its cooldown
        -- (asked every cycle and refused before, 17:45)
        return {ok = true, unchanged = true, members = count + fcount}
    end
    return {ok = true, burrow_id = b.id, tiles = tiles, added = added, released = released, members = count + fcount,
            dry_run = dry_run or nil}
end

-- --- (0.104.167) the hospital burrow -------------------------------------------
--
-- Teacheroar, 1 Nov 15:16-15:42: seven citizens killed by citizens, five of
-- them patients waiting for care, walking the corridors and halls (82 with
-- infected wounds walked the fort), strangled or struck down by dwarves in
-- tantrums. The player's word: keep the wounded inside the hospitals. The
-- opposite of the recreation burrow (which never covers a hospital since
-- 0.104.127): a burrow over every hospital location's zones, its members
-- the citizens DF asks a treatment for.
--
-- Drink (the design): a dwarf restricted to a burrow takes no drink or food
-- from outside it, and this fort has lost dwarves to thirst. Restricting only
-- the patients already lying in a hospital bed (fed and watered by the
-- doctors, labour FEED_WATER_CIVILIANS) would be safe for drink but would
-- leave out exactly those who were killed: the ones walking about. So the
-- burrow also covers, besides the hospitals' zones, the nearest stockpile
-- that holds drink now (in its barrels, neither forbidden), the nearest that
-- holds food, and the nearest well that gives water (built, its shaft open,
-- unfrozen water under it), each only when a dwarf can walk there from a
-- hospital zone (DF's walkability groups). With no drink reachable, nobody is
-- moved in and every member is let out, and the call says why.
-- Food: with no food pile reachable, only patients lying in a hospital bed
-- are moved in (the doctors feed them), and a member who is up and about is
-- let out after HOSP_NOFOOD_DAYS. Hunger takes far longer than that to harm.
-- Nobody is kept more than `days` (28): an untreated patient goes back to
-- the fort, and is not moved in again for HOSP_OUT_DAYS.
-- (review) The members are re-checked at every report, not only when the
-- brain asks (hospital_burrow_status): no hospital zone or no drink, and they
-- are let out right there; the burrow refilled when its sources change; the
-- burrow's own units compared with the saved list (assigned but not listed:
-- let out; listed but not assigned: dropped). The burrow is found by its
-- saved id (a renamed one is still ours; a removed one took its members).
-- Never a soldier, the hospital's own staff, a baby, the insane, one in a
-- tantrum, or one in a player's burrow; one in the AI's recreation burrow is
-- taken out of it first. Each is let out once DF asks no treatment for them.
-- At most `max` members, `per` new a call.
HOSPITAL_BURROW_NAME = 'AI hospital'
HOSPITAL_BURROW_KEY = 'ai-overseer/hospital-burrow'
HOSP_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
           'rq_setting', 'rq_traction', 'rq_crutch'}
HOSP_DAYS = 28              -- the longest stay (the brain may send its own)
HOSP_OUT_DAYS = 7           -- one let out after the longest stay: not moved in again for this long
HOSP_NOFOOD_DAYS = 3        -- no food reachable: one up and about is let out after this
HOSP_WELL_DEPTH = 2         -- a well's water: at least this deep (of 7)
local HOSP_FOOD = {FOOD = true, MEAT = true, FISH = true, CHEESE = true, EGG = true, PLANT = true, PLANT_GROWTH = true}
local HOSP_SCAN_MAX = 2000           -- items looked at in one pile

local function hb_state()
    local ok, d = pcall(dfhack.persistent.getSiteData, HOSPITAL_BURROW_KEY, {members = {}})
    d = ok and type(d) == 'table' and d or {members = {}}
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}
    return d
end

local function hb_save(d)
    pcall(dfhack.persistent.saveSiteData, HOSPITAL_BURROW_KEY, d)
end

local function hb_now()
    return df.global.cur_year * 403200 + df.global.cur_year_tick
end

-- The hospital locations' zones (as the bridge's hospital_survey finds them)
-- and the units holding a post at any of them.
function hospital_zones()
    local ids, staff, zones = {}, {}, {}
    pcall(function()
        for _, loc in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                if df.abstract_building_type[loc:getType()] ~= 'HOSPITAL' then return end
                for _, bid in ipairs(loc:getContents().building_ids) do ids[bid] = true end
                for _, o in ipairs(loc.occupations or {}) do
                    if o.unit_id ~= -1 then staff[o.unit_id] = true end
                end
            end)
        end
    end)
    for _, b in ipairs(df.global.world.buildings.all) do
        if ids[b.id] and b:getType() == df.building_type.Civzone then table.insert(zones, b) end
    end
    table.sort(zones, function(a, c) return a.id < c.id end)
    return zones, staff
end

local function walk_group(p)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, p)
    return ok and type(g) == 'number' and g or 0
end

-- A tile of the building a dwarf can stand on: its middle, else the first
-- walkable one of its tiles.
local function stand_pos(b)
    local mid = xyz2pos(math.floor((b.x1 + b.x2) / 2), math.floor((b.y1 + b.y2) / 2), b.z)
    if walk_group(mid) ~= 0 then return mid end
    local n = 0
    for y = b.y1, b.y2 do
        for x = b.x1, b.x2 do
            local p = xyz2pos(x, y, b.z)
            if walk_group(p) ~= 0 then return p end
            n = n + 1
            if n > 400 then return nil end
        end
    end
    return nil
end

local function can_walk(a, c)
    local ok, yes = pcall(dfhack.maps.canWalkBetween, a, c)
    if ok and type(yes) == 'boolean' then return yes end
    local ga = walk_group(a)
    return ga ~= 0 and ga == walk_group(c)
end

local function in_zones(pos, zones)
    if not pos then return false end
    for _, z in ipairs(zones) do
        if pos.z == z.z and pos.x >= z.x1 and pos.x <= z.x2 and pos.y >= z.y1 and pos.y <= z.y2 then
            local okc, inside = pcall(dfhack.buildings.containsTile, z, pos.x, pos.y)
            if not okc or inside then return true end
        end
    end
    return false
end

-- What a pile holds now: drink, food (in barrels and pots too; never a
-- forbidden item, nor what lies in a forbidden barrel).
local function pile_holds(b)
    local drink, food, seen = false, false, 0
    local function forbidden(it)
        local okf, f = pcall(function() return it.flags.forbid end)
        return okf and f and true or false
    end
    local function look(it)
        local okt, t = pcall(function() return df.item_type[it:getType()] end)
        if not okt then return end
        if t == 'DRINK' then drink = true elseif HOSP_FOOD[t] then food = true end
    end
    local ok, items = pcall(dfhack.buildings.getStockpileContents, b)
    if not ok or type(items) ~= 'table' and type(items) ~= 'userdata' then return false, false end
    for _, it in ipairs(items) do
        seen = seen + 1
        if seen > HOSP_SCAN_MAX or (drink and food) then break end
        if not forbidden(it) then
            look(it)
            pcall(function()
                for _, c in ipairs(dfhack.items.getContainedItems(it)) do
                    if not forbidden(c) then look(c) end
                end
            end)
        end
    end
    return drink, food
end

-- A well that gives water: fully built, and down its shaft no shut hatch
-- (the AI's cavern shaft gate, lua/ai-builder.lua shaft_gate_state 'closed',
-- or anyone's), no ice, but water HOSP_WELL_DEPTH deep (never magma) before
-- the shaft meets solid ground.
function well_gives_water(b)
    local okb, built = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    if not (okb and built) then return false end
    local x, y = b.centerx or b.x1, b.centery or b.y1
    for z = b.z - 1, math.max(0, b.z - 100), -1 do
        local p = xyz2pos(x, y, z)
        local okh, h = pcall(dfhack.buildings.findAtTile, p)
        if okh and h and df.building_type.Hatch ~= nil and h:getType() == df.building_type.Hatch then
            local okc, closed = pcall(function() return h.door_flags.closed end)
            if not okc or closed then return false end
        end
        local okt, tt = pcall(dfhack.maps.getTileType, p)
        if not okt or not tt then return false end
        local oka, shape, mat = pcall(function()
            local at = df.tiletype.attrs[tt]
            return df.tiletype_shape[at.shape], df.tiletype_material[at.material]
        end)
        if not oka then return false end
        if mat == 'FROZEN_LIQUID' then return false end
        local okf, des = pcall(dfhack.maps.getTileFlags, p)
        if not okf or not des then return false end
        if (des.flow_size or 0) > 0 then
            if des.liquid_type == true or des.liquid_type == 1 then return false end      -- magma
            return des.flow_size >= HOSP_WELL_DEPTH
        end
        if shape ~= 'EMPTY' and shape ~= 'RAMP_TOP' then return false end              -- the shaft ends dry
    end
    return false
end

-- The nearest drink pile, food pile and well a dwarf can walk to from a
-- hospital zone: {drink = b, food = b, well = b, dist = {...}}.
local function hospital_sources(zones)
    local from = {}
    for _, z in ipairs(zones) do
        local p = stand_pos(z)
        if p then table.insert(from, p) end
    end
    local out = {dist = {}}
    if #from == 0 then return out end
    local function reach(p)
        local best
        for _, f in ipairs(from) do
            local dd = math.abs(p.x - f.x) + math.abs(p.y - f.y) + 3 * math.abs(p.z - f.z)
            if (not best or dd < best) and can_walk(f, p) then best = dd end
        end
        return best
    end
    local function offer(kind, b, dd)
        if dd and (not out.dist[kind] or dd < out.dist[kind]) then out[kind], out.dist[kind] = b, dd end
    end
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        if t == df.building_type.Stockpile then
            local okf, food = pcall(function() return b.settings.flags.food end)
            if okf and food then
                local has_drink, has_food = pile_holds(b)
                if has_drink or has_food then
                    local p = stand_pos(b)
                    local dd = p and reach(p)
                    if has_drink then offer('drink', b, dd) end
                    if has_food then offer('food', b, dd) end
                end
            end
        elseif df.building_type.Well ~= nil and t == df.building_type.Well and well_gives_water(b) then
            -- a dwarf draws water standing beside the well
            local x, y = b.centerx or b.x1, b.centery or b.y1
            for dy = -1, 1 do
                for dx = -1, 1 do
                    if dx ~= 0 or dy ~= 0 then
                        local p = xyz2pos(x + dx, y + dy, b.z)
                        if walk_group(p) ~= 0 then offer('well', b, reach(p)) end
                    end
                end
            end
        end
    end
    return out
end

local function hb_sig(zones, src)
    local parts = {}
    for _, z in ipairs(zones) do table.insert(parts, tostring(z.id)) end
    for _, k in ipairs({'drink', 'food', 'well'}) do
        table.insert(parts, k .. '=' .. tostring(src[k] and src[k].id or '-'))
    end
    return table.concat(parts, ',')
end

local function fill_hospital_burrow(burrow, zones, src)
    dfhack.burrows.clearTiles(burrow)
    local n = 0
    for _, z in ipairs(zones) do n = n + zone_tiles(z, burrow) end
    if src.drink then n = n + zone_tiles(src.drink, burrow) end
    if src.food and src.food ~= src.drink then n = n + zone_tiles(src.food, burrow) end
    if src.well then
        local w = src.well
        local x, y = w.centerx or w.x1, w.centery or w.y1
        for dy = -1, 1 do
            for dx = -1, 1 do
                if dfhack.burrows.setAssignedTile(burrow, xyz2pos(x + dx, y + dy, w.z), true) then n = n + 1 end
            end
        end
    end
    return n
end

-- The burrow by its saved id (a renamed one is still ours). Gone (the player
-- removed it): its members went with it, the list is cleared. An older save
-- with no id: the one by our name.
local function hb_burrow(d)
    if d.burrow_id ~= nil then
        for _, b in ipairs(df.global.plotinfo.burrows.list) do
            if b.id == d.burrow_id then return b end
        end
        d.members, d.burrow_id, d.sig, d.filled, d.tiles = {}, nil, nil, nil, nil
        return nil
    end
    local b = find_burrow(HOSPITAL_BURROW_NAME)
    if b then d.burrow_id = b.id end
    return b
end

-- The units the burrow holds now (unit id -> true), or nil when unreadable.
local function burrow_unit_ids(b)
    local ids = {}
    local ok = pcall(function()
        for _, u in ipairs(dfhack.burrows.listUnits(b)) do ids[u.id] = true end
    end)
    if not ok then
        ids = {}
        ok = pcall(function() for _, id in ipairs(b.units) do ids[id] = true end end)
    end
    return ok and ids or nil
end

-- The burrow's own units against the saved list: assigned but not listed
-- (a throw mid-call, a player's hand): let out; listed but no longer
-- assigned (the player took them out): dropped from the list.
local function hb_reconcile(d, b, dry_run, released, name)
    local ids = burrow_unit_ids(b)
    if not ids then return end
    for id in pairs(ids) do
        if not d.members[tostring(id)] then
            local u = df.unit.find(id)
            if not dry_run and u then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            table.insert(released, u and name(u) or tostring(id))
        end
    end
    for id in pairs(d.members) do
        if not ids[tonumber(id)] then d.members[id] = nil end
    end
end

-- A treatment asked by DF (its rq_ flags; needs_healthcare alone is set for
-- every infected dwarf walking about: 0.104.150).
function is_patient(u)
    local ok, yes = pcall(function()
        if not (u.health and u.health.flags.needs_healthcare) then return false end
        for _, f in ipairs(HOSP_RQ) do
            if u.health.flags[f] then return true end
        end
        return false
    end)
    return ok and yes or false
end

local function in_tantrum(u)
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    return okm and (m == 'Tantrum' or m == 'Enraged')
end

-- (review) the same citizen test for moving in and for keeping: a citizen
-- and sane (getCitizens(true) lists the insane too)
local function hb_citizen(u)
    local okc, cit = pcall(dfhack.units.isCitizen, u)
    if not (okc and cit) then return false end
    local oks, sane = pcall(dfhack.units.isSane, u)
    return not (oks and sane == false)
end

-- Whether in a burrow other than ours and the recreation one, and whether
-- in the recreation one.
local function burrows_of(u, own_id, rec_id)
    local other, rec = false, false
    local ok = pcall(function()
        for _, bid in ipairs(u.burrows or {}) do
            if bid == rec_id then rec = true elseif bid ~= own_id then other = true end
        end
    end)
    if not ok then return true, false end
    return other, rec
end

local function in_hospital_bed(u, zones)
    local ok, yes = pcall(function()
        local j = u.job.current_job
        if not (j and j.job_type == df.job_type.Rest) then return false end
        local bed = dfhack.buildings.findAtTile(u.pos)
        return bed ~= nil and bed:getType() == df.building_type.Bed and in_zones(u.pos, zones)
    end)
    return ok and yes or false
end

-- eligible, and whether in the recreation burrow now
local function hb_eligible(u, staff, own_id, rec_id)
    local okb, baby = pcall(dfhack.units.isBaby, u)
    if okb and baby then return false end
    if not hb_citizen(u) or u.military.squad_id ~= -1 or staff[u.id] or in_tantrum(u) then return false end
    if not is_patient(u) then return false end
    local other, rec = burrows_of(u, own_id, rec_id)
    if other then return false end
    return true, rec
end

-- The members' checks (the burrow already reconciled). With no hospital
-- zone or no drink reachable, everyone out: returns why. Else the tiles
-- refilled when the sources changed (returns nil, tiles), and each member
-- let out who is healed, gone, drafted, staff, raging, in a player's burrow,
-- or in too long.
-- (0.105.22) a member thirsty or hungry this far is let out to drink and eat
-- where they can (B, 3 Nov: 36 of a night's 71 who died of thirst were in
-- the hospital burrow, its "drink they can reach" one pile; the bedridden get
-- water only from a well) and not taken back in until they've drunk
HOSP_THIRST = 25000          -- DFHack's "thirsty"
HOSP_HUNGER = 50000          -- DF's "hungry"

local function hb_dry(u)
    local ok, yes = pcall(function()
        return u.counters2.thirst_timer >= HOSP_THIRST or u.counters2.hunger_timer >= HOSP_HUNGER
    end)
    return ok and yes == true
end

local function hb_maintain(d, b, zones, staff, src, now, dry_run, name, released)
    local function let_out(id, u, timed)
        if not dry_run and u and b then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
        d.members[id] = nil
        if timed then d.out[id] = now end
        table.insert(released, u and name(u) or id)
    end
    local why
    if #zones == 0 then
        why = 'no hospital zone: make a zone a hospital location first'
    elseif not src.drink and not src.well then
        why = 'no drink reachable from the hospital (no stockpile holding drink and no well giving water that a '
              .. 'dwarf can walk to): nobody is kept in the hospital without it'
    end
    if why then
        for id in pairs(d.members) do let_out(id, df.unit.find(tonumber(id))) end
        d.why = why
        return why
    end
    d.why = nil
    d.drink = src.drink and 'stockpile' or 'well'
    d.food = src.food ~= nil
    local tiles
    local sig = hb_sig(zones, src)
    if b and not dry_run and (sig ~= d.sig or not d.filled or now - d.filled >= 7 * 1200) then
        tiles = fill_hospital_burrow(b, zones, src)
        d.filled, d.sig, d.tiles = now, sig, tiles
    end
    local days = tonumber(d.days) or HOSP_DAYS
    local rec_b = find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    for id, since in pairs(d.members) do
        local u = df.unit.find(tonumber(id))
        since = tonumber(since) or now
        local keep = u and hb_citizen(u) and u.military.squad_id == -1 and not staff[u.id] and is_patient(u)
                     and not in_tantrum(u) and not (burrows_of(u, b and b.id or -1, rec_id)) and true or false
        if keep and hb_dry(u) then
            let_out(id, u, true)                 -- (0.105.22) to drink and eat
        elseif keep and now - since >= days * 1200 then
            let_out(id, u, true)
        elseif keep and not src.food and now - since >= HOSP_NOFOOD_DAYS * 1200 and not in_hospital_bed(u, zones) then
            let_out(id, u, true)
        elseif not keep then
            let_out(id, u)
        end
    end
    return nil, tiles
end

-- For the report: the burrow, its members and tiles, the hospital zones, and
-- the patients who could join walking outside the hospitals. (review) Also
-- the bridge's own guard, at every report: the members re-checked and let
-- out here (no hospital, no drink, healed...), with no brain needed.
function hospital_burrow_status(txt)
    local function name(u) return (txt or tostring)(dfhack.units.getReadableName(u)) end
    local d = hb_state()
    local now = hb_now()
    local zones, staff = hospital_zones()
    local had_id = d.burrow_id
    local b = hb_burrow(d)
    local released = {}
    local before = 0
    for _ in pairs(d.members) do before = before + 1 end
    if b then hb_reconcile(d, b, false, released, name) end
    local tiles
    if next(d.members) ~= nil then
        local src = #zones > 0 and hospital_sources(zones) or {dist = {}}
        local _
        _, tiles = hb_maintain(d, b, zones, staff, src, now, false, name, released)
    end
    local after = 0
    for _ in pairs(d.members) do after = after + 1 end
    if #released > 0 or tiles or after ~= before or had_id ~= d.burrow_id then hb_save(d) end
    local rec_b = find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    local out = {burrow = b and b.id or nil, members = after, tiles = d.tiles, hospital_zones = #zones,
                 drink = d.drink, food = d.food, why = d.why, outside = 0, patients = 0,
                 released_now = #released > 0 and released or nil}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if is_patient(u) then
            out.patients = out.patients + 1
            if not d.members[tostring(u.id)] and hb_eligible(u, staff, b and b.id or -1, rec_id)
                    and not in_zones(u.pos, zones) then
                out.outside = out.outside + 1
            end
        end
    end
    return out
end

-- `release`: the brain's word that the burrow is to be emptied (the rule
-- switched off, the hospital gone, its status unreadable).
function hospital_burrow_tick(max, per, dry_run, txt, days, release)
    max, per, days = max or 30, per or 10, days or HOSP_DAYS
    local function name(u) return (txt or tostring)(dfhack.units.getReadableName(u)) end
    local d = hb_state()
    local now = hb_now()
    local zones, staff = hospital_zones()
    local b = hb_burrow(d)
    local released, added = {}, {}
    if b then hb_reconcile(d, b, dry_run, released, name) end
    if release then
        for id in pairs(d.members) do
            local u = df.unit.find(tonumber(id))
            if not dry_run and u and b then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            d.members[id] = nil
            table.insert(released, u and name(u) or id)
        end
        if not dry_run then hb_save(d) end
        if #released == 0 then return {ok = true, unchanged = true, members = 0} end
        return {ok = true, released = released, added = {}, members = 0, dry_run = dry_run or nil}
    end
    d.days = days
    local src = #zones > 0 and hospital_sources(zones) or {dist = {}}
    local why, tiles = hb_maintain(d, b, zones, staff, src, now, dry_run, name, released)
    if why then
        if not dry_run then hb_save(d) end
        if #released > 0 then
            return {ok = true, released = released, added = {}, members = 0, note = why, dry_run = dry_run or nil}
        end
        return {ok = false, rejected = true, error = why}
    end
    if not b and dry_run then
        return {ok = true, dry_run = true, note = 'the burrow would be made', drink = d.drink}
    end
    if not b then
        b = new_burrow(HOSPITAL_BURROW_NAME)
        d.burrow_id, d.members = b.id, {}
        tiles = fill_hospital_burrow(b, zones, src)
        d.filled, d.sig, d.tiles = now, hb_sig(zones, src), tiles
        hb_save(d)
    end
    local count = 0
    for _ in pairs(d.members) do count = count + 1 end
    -- the patients walking outside the hospitals first; with no food in
    -- reach only those lying in a hospital bed (the doctors feed them)
    local rec_b = find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    local cands = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local key = tostring(u.id)
        local was = tonumber(d.out[key])
        if was and now - was >= HOSP_OUT_DAYS * 1200 then d.out[key] = nil; was = nil end
        if not d.members[key] and not was then
            local ok, in_rec = hb_eligible(u, staff, b.id, rec_id)
            -- (0.105.22) never one already thirsty or hungry; a bedridden one
            -- (in a hospital bed) only with a well giving water
            local bed = in_hospital_bed(u, zones)
            if ok and not hb_dry(u) and ((src.food and not bed) or (bed and src.well)) then
                table.insert(cands, {u = u, inside = in_zones(u.pos, zones) and 1 or 0, rec = in_rec})
            end
        end
    end
    table.sort(cands, function(a, c) if a.inside ~= c.inside then return a.inside < c.inside end return a.u.id < c.u.id end)
    local rec
    for _, c in ipairs(cands) do
        if count >= max or #added >= per then break end
        local key = tostring(c.u.id)
        if dry_run then
            count = count + 1
            table.insert(added, name(c.u))
        else
            if c.rec and rec_b then
                -- out of the AI's own recreation burrow first (patients never join it: 0.104.78)
                rec = rec or rec_state()
                pcall(dfhack.burrows.setAssignedUnit, rec_b, c.u, false)
                rec.members[key] = nil
                if type(rec.friends) == 'table' then rec.friends[key] = nil end
                rec.out[key] = now
                pcall(dfhack.persistent.saveSiteData, RECREATION_KEY, rec)
            end
            -- (review) each one listed and saved as moved in: a throw can't leave one assigned unlisted
            local oka = pcall(dfhack.burrows.setAssignedUnit, b, c.u, true)
            if oka then
                d.members[key] = now
                hb_save(d)
                count = count + 1
                table.insert(added, name(c.u) .. (c.rec and ' (from the recreation burrow)' or ''))
            end
        end
    end
    if not dry_run then hb_save(d) end
    if #added == 0 and #released == 0 and not tiles then
        return {ok = true, unchanged = true, members = count}     -- nothing to change is no refusal
    end
    return {ok = true, burrow_id = b.id, tiles = tiles, added = added, released = released, members = count,
            drink = d.drink, food = src.food ~= nil, dry_run = dry_run or nil}
end

-- --- (0.104.169) the calm-down burrows ---------------------------------------
--
-- Teacheroar, 1 Nov 18:38-18:53: five citizens killed by citizens, three of
-- them patients waiting for care, the killers in a tantrum (a planter killed
-- two in five minutes); and the tantrum-throwers die too (a butcher in a
-- tantrum at 17:01, strangled by the miner he went for at 17:03). The
-- player's word: keep a dwarf in a tantrum away from the patients and the
-- others until they calm down.
--
-- What DF allows (0.104.169 research): a citizen assigned to a burrow looks
-- for work and wanders only inside it, and won't eat or drink outside it
-- until starving or dehydrating (wiki, Burrow; the insane too comply). That a
-- tantrum's own acts (the fist fights, the thrown items, the toppled
-- furniture) keep to the burrow is NOT known: the wiki says nothing, and DF's
-- tantrum code is not public. So the lever is a nudge, measured: each report
-- counts whether each member stands inside its burrow (`seen_in`,
-- `seen_out`), so the game itself tells whether it works.
--
-- The lever: each citizen in a tantrum (soldier_mood Tantrum or Enraged) is
-- restricted, one to a burrow ("AI calm 1".."AI calm 6"), to a free bedroom
-- (a bedroom zone nobody owns, with a bed, nobody standing in it) at least
-- CALM_HOSP_DIST tiles from every hospital zone, the nearest one they can
-- walk to (never a location's room: a tavern's guest rooms); and drink they
-- can walk to from it (review: a quiet well first, then a quiet pile, then a
-- busy one, the hospital burrow's own last; of a pile only a few of the
-- tiles holding drink, nearest the room, never the whole dining-hall pile).
-- With no such room or no drink, nobody is moved, and the call says why.
-- Never a door locked, a dwarf chained or jailed, nor a hospital closed:
-- nobody is shut in or out. Not checked (no cheap path query in DFHack):
-- whether the walk from where the dwarf stands to the room passes through a
-- hospital zone; the room is only the nearest one far from them.
-- Let out: at the first report or call after the tantrum ends (calm), after
-- `days` (CALM_DAYS, 3) whatever (then not again for CALM_OUT_DAYS), thirsty
-- or hungry (CALM_THIRST/CALM_HUNGER: far from harm; DFHack calls 25000
-- thirsty, 50000 dehydrated, and three days add 3600), drafted, insane, gone,
-- the room taken (by another: their own claim is no taking) or gone, the
-- drink gone, hurt (needs care), or put in a player's burrow. Never a baby,
-- a soldier, the insane, one already thirsty or hungry, (review) a patient,
-- one resting or unable to walk, one in the hospital burrow, or one in a
-- player's burrow; one in the AI's recreation burrow is taken out of it
-- first (the taverns and halls, where the others are). Every report re-checks the
-- members itself (calm_burrow_status), with no brain needed.
CALM_PREFIX = 'AI calm '
CALM_KEY = 'ai-overseer/calm-burrow'
CALM_MAX = 6                -- burrows (and so members) at most
CALM_DAYS = 3               -- the longest stay (the brain may send its own, 1-7)
CALM_OUT_DAYS = 1           -- one let out after the longest stay: not moved in again for this long
CALM_HOSP_DIST = 15         -- the room at least this far from every hospital zone (x + y + 3z)
CALM_WALK_TICKS = 300       -- a quarter day to walk there before "outside" is counted
CALM_THIRST = 20000         -- thirst_timer at or past this: drink first (never moved in; let out)
CALM_HUNGER = 40000         -- hunger_timer likewise (DF: hungry at 50000)
-- (0.104.169, review) the drink: a quiet source first (a well, or a pile at
-- least CALM_HOSP_DIST from the hospitals, CALM_BUSY_DIST from any dining
-- hall, meeting hall or location zone, and fewer than CALM_CROWD citizens
-- within CALM_CROWD_DIST); of a pile only the tiles holding drink nearest the
-- room: CALM_PILE_TILES of a quiet one, CALM_BUSY_TILES of a busy one
CALM_BUSY_DIST = 3
CALM_CROWD = 5
CALM_CROWD_DIST = 6
CALM_PILE_TILES = 6
CALM_BUSY_TILES = 2

-- (0.104.169, review) never one who needs care: a patient (any treatment
-- asked, or DF's needs_healthcare: the infected), one resting (a Rest job:
-- bedridden, fed and watered by the doctors where they lie), one lying on the
-- ground (flags1.on_ground) or unconscious. Kept 15+ tiles from every
-- hospital they would get no treatment, and in a bed far off no water.
local function needs_care(u)
    if is_patient(u) then return 'patient' end
    local ok, why = pcall(function()
        if u.health and u.health.flags.needs_healthcare then return 'patient' end
        local j = u.job and u.job.current_job
        if j and j.job_type == df.job_type.Rest then return 'resting' end
        if u.flags1 and u.flags1.on_ground then return 'cannot walk' end
        if u.counters and (tonumber(u.counters.unconscious) or 0) > 0 then return 'cannot walk' end
        return nil
    end)
    return ok and why or nil
end

local function calm_state()
    local ok, d = pcall(dfhack.persistent.getSiteData, CALM_KEY, {members = {}})
    d = ok and type(d) == 'table' and d or {members = {}}
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}
    d.stats = type(d.stats) == 'table' and d.stats or {}
    return d
end

local function calm_save(d) pcall(dfhack.persistent.saveSiteData, CALM_KEY, d) end

local function calm_count(d, k, n) d.stats[k] = (tonumber(d.stats[k]) or 0) + (n or 1) end

local function burrow_by_id(id)
    if id == nil then return nil end
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if b.id == id then return b end
    end
    return nil
end

-- The AI's calm burrows by name (id -> burrow), and the next free name.
local function calm_burrows()
    local by = {}
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        local nm = tostring(b.name)
        if nm:sub(1, #CALM_PREFIX) == CALM_PREFIX then by[b.id] = b end
    end
    return by
end

local function thirsty(u)
    local ok, yes = pcall(function()
        return u.counters2.thirst_timer >= CALM_THIRST or u.counters2.hunger_timer >= CALM_HUNGER
    end)
    return ok and yes or false
end

-- The burrows a unit is in: whether one is a player's (not the recreation,
-- hospital or a calm one), and which of the AI's.
local function calm_burrows_of(u, ids)
    local other, which = false, {}
    local ok = pcall(function()
        for _, bid in ipairs(u.burrows or {}) do
            if ids[bid] then which[ids[bid]] = bid else other = true end
        end
    end)
    if not ok then return true, which end
    return other, which
end

local function calm_ai_ids(calm_by)
    local ids = {}
    local rec_b = find_burrow(RECREATION_NAME)
    if rec_b then ids[rec_b.id] = 'rec' end
    local hb = hb_state()
    if hb.burrow_id ~= nil then ids[hb.burrow_id] = 'hosp' end
    for id in pairs(calm_by) do ids[id] = 'calm' end
    return ids
end

local function dist(a, c)
    return math.abs(a.x - c.x) + math.abs(a.y - c.y) + 3 * math.abs(a.z - c.z)
end

local function zone_dist(p, zones)
    local best
    for _, z in ipairs(zones) do
        local dx = p.x < z.x1 and z.x1 - p.x or (p.x > z.x2 and p.x - z.x2 or 0)
        local dy = p.y < z.y1 and z.y1 - p.y or (p.y > z.y2 and p.y - z.y2 or 0)
        local dd = dx + dy + 3 * math.abs(p.z - z.z)
        if not best or dd < best then best = dd end
    end
    return best
end

local function bed_of(z)
    local pos
    pcall(function()
        for _, b in ipairs(z.contained_buildings) do
            if b:getType() == df.building_type.Bed then
                pos = xyz2pos(b.centerx or b.x1, b.centery or b.y1, b.z)
                return
            end
        end
    end)
    return pos
end

local function bedroom_list()
    local ok, list = pcall(function() return df.global.world.buildings.other.ZONE_BEDROOM end)
    if ok and list then return list end
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone and df.civzone_type[b.type] == 'Bedroom' then table.insert(out, b) end
    end
    return out
end

-- (0.104.169, review) The zones of the fort's locations (tavern, temple,
-- library, hospital...: id -> true), and the busy zones (those, and every
-- dining and meeting hall): where the others gather.
local function calm_busy_zones()
    local loc, busy = {}, {}
    pcall(function()
        for _, l in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                for _, bid in ipairs(l:getContents().building_ids) do loc[bid] = true end
            end)
        end
    end)
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone then
            local kind = df.civzone_type[b.type] or ''
            if loc[b.id] or kind == 'DiningHall' or kind == 'MeetingHall' or kind == 'Hospital' then
                table.insert(busy, b)
            end
        end
    end
    return loc, busy
end

-- The free bedrooms far enough from every hospital zone: {z, pos, hd};
-- (review) never one of a location (a tavern's guest rooms).
local function calm_rooms(hzones, taken, people, loc)
    local out = {}
    for _, z in ipairs(bedroom_list()) do
        local okf, free = pcall(function() return z.assigned_unit_id == -1 end)
        if okf and free and not taken[z.id] and not (loc and loc[z.id]) then
            local pos = bed_of(z)
            local hd = pos and (#hzones == 0 and 999 or zone_dist(pos, hzones))
            if pos and hd >= CALM_HOSP_DIST and walk_group(pos) ~= 0 then
                local busy = false
                for _, p in ipairs(people) do
                    if in_zones(p, {z}) then busy = true break end
                end
                if not busy then table.insert(out, {z = z, pos = pos, hd = hd}) end
            end
        end
    end
    return out
end

-- Every drink a dwarf could take: {b, kind, pos} (a stockpile holding drink
-- now, a well giving water: each tile beside it a dwarf can stand on).
local function drink_list()
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        if t == df.building_type.Stockpile then
            local okf, food = pcall(function() return b.settings.flags.food end)
            if okf and food then
                local has_drink = pile_holds(b)
                local p = has_drink and stand_pos(b)
                if p then table.insert(out, {b = b, kind = 'stockpile', pos = p}) end
            end
        elseif df.building_type.Well ~= nil and t == df.building_type.Well and well_gives_water(b) then
            local x, y = b.centerx or b.x1, b.centery or b.y1
            for dy = -1, 1 do
                for dx = -1, 1 do
                    local p = xyz2pos(x + dx, y + dy, b.z)
                    if (dx ~= 0 or dy ~= 0) and walk_group(p) ~= 0 then
                        table.insert(out, {b = b, kind = 'well', pos = p})
                    end
                end
            end
        end
    end
    return out
end

-- (0.104.169, review) Each drink marked quiet or busy: busy when within
-- CALM_HOSP_DIST of a hospital zone, CALM_BUSY_DIST of a hall or location
-- zone, or with CALM_CROWD citizens within CALM_CROWD_DIST.
local function calm_mark_drinks(drinks, hzones, busy, people)
    for _, s in ipairs(drinks) do
        local b = (#hzones > 0 and zone_dist(s.pos, hzones) < CALM_HOSP_DIST)
                  or (#busy > 0 and zone_dist(s.pos, busy) <= CALM_BUSY_DIST)
        if not b then
            local n = 0
            for _, p in ipairs(people) do
                if dist(p, s.pos) <= CALM_CROWD_DIST then n = n + 1 end
            end
            b = n >= CALM_CROWD
        end
        s.busy = b and true or false
    end
end

-- The drink a dwarf can walk to from `pos`, by preference: a quiet well, a
-- quiet pile, a busy one (only a few of its tiles, see fill_calm), and the
-- hospital burrow's own (`avoid`) last; the nearest in each. Returns the
-- entry and whether it is the hospital's.
local function calm_drink(pos, drinks, avoid)
    local function pass_of(s)
        if avoid[s.b.id] then return 4 end
        if s.busy then return 3 end
        return s.kind == 'well' and 1 or 2
    end
    local best, bd, bp
    for _, s in ipairs(drinks) do
        local p = pass_of(s)
        local dd = dist(pos, s.pos)
        if (not bp or p < bp or (p == bp and dd < bd)) and can_walk(pos, s.pos) then best, bd, bp = s, dd, p end
    end
    return best, bp == 4
end

-- (0.104.169, review) A pile's tiles that hold drink now (its barrels' and
-- loose drinks' tiles, never forbidden), the nearest `k` to `pos`.
local function pile_drink_tiles(b, pos, k)
    local seen, list, n = {}, {}, 0
    local function is_drink(it)
        local okt, t = pcall(function() return df.item_type[it:getType()] end)
        return okt and t == 'DRINK'
    end
    local ok, items = pcall(dfhack.buildings.getStockpileContents, b)
    if not ok or not items then return list end
    for _, it in ipairs(items) do
        n = n + 1
        if n > HOSP_SCAN_MAX then break end
        local okf, forbid = pcall(function() return it.flags.forbid end)
        if not (okf and forbid) then
            local has = is_drink(it)
            if not has then
                pcall(function()
                    for _, c in ipairs(dfhack.items.getContainedItems(it)) do
                        if is_drink(c) and not c.flags.forbid then has = true break end
                    end
                end)
            end
            local okp, p = pcall(function() return it.pos end)
            if has and okp and p and p.x ~= nil then
                local key = p.x .. ',' .. p.y .. ',' .. p.z
                if not seen[key] then
                    seen[key] = true
                    table.insert(list, xyz2pos(p.x, p.y, p.z))
                end
            end
        end
    end
    table.sort(list, function(a, c) return dist(a, pos) < dist(c, pos) end)
    while #list > k do table.remove(list) end
    return list
end

-- The hospital burrow's drink and food piles and well (its saved signature).
local function hospital_drink_ids()
    local ids = {}
    local sig = hb_state().sig
    if type(sig) == 'string' then
        for id in sig:gmatch('=(%d+)') do ids[tonumber(id)] = true end
    end
    return ids
end

local function fill_calm(b, room, src, pos)
    dfhack.burrows.clearTiles(b)
    local n = zone_tiles(room, b)
    if src.kind == 'stockpile' then
        -- (review) never the whole pile: the tiles holding drink nearest the room
        local tiles = pile_drink_tiles(src.b, pos, src.busy and CALM_BUSY_TILES or CALM_PILE_TILES)
        if #tiles == 0 then
            if src.busy then tiles = {src.pos} else return n + zone_tiles(src.b, b) end
        end
        for _, p in ipairs(tiles) do
            if dfhack.burrows.setAssignedTile(b, p, true) then n = n + 1 end
        end
    else
        local w = src.b
        local x, y = w.centerx or w.x1, w.centery or w.y1
        for dy = -1, 1 do
            for dx = -1, 1 do
                if dfhack.burrows.setAssignedTile(b, xyz2pos(x + dx, y + dy, w.z), true) then n = n + 1 end
            end
        end
    end
    return n
end

local function building_by_id(id)
    if id == nil then return nil end
    local ok, b = pcall(df.building.find, id)
    if ok and b then return b end
    for _, x in ipairs(df.global.world.buildings.all) do
        if x.id == id then return x end
    end
    return nil
end

-- The drink still there: the pile holds drink, the well gives water.
local function drink_still(m)
    local b = building_by_id(m.src)
    if not b then return false end
    if m.kind == 'well' then return well_gives_water(b) end
    return (pile_holds(b))
end

-- One member let out: off the burrow, its tiles cleared, the reason counted.
local function calm_let_out(d, id, u, why, now, dry_run, name, released)
    local m = d.members[id]
    local b = type(m) == 'table' and burrow_by_id(m.burrow)
    if not dry_run then
        if b and u then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
        if b then pcall(dfhack.burrows.clearTiles, b) end
    end
    d.members[id] = nil
    if why == 'limit' then d.out[id] = now end
    calm_count(d, 'out_' .. why:gsub(' ', '_'))
    table.insert(released, (u and name(u) or id) .. ' (' .. why .. ')')
end

-- The members' checks: each let out who is calm, in too long, thirsty,
-- drafted, insane, gone, in a player's burrow, whose room or drink is gone;
-- each other unit found in a calm burrow let out; and, for those kept, the
-- count of whether they stand inside their burrow.
local function calm_maintain(d, now, dry_run, name, released)
    local days = tonumber(d.days) or CALM_DAYS
    local calm_by = calm_burrows()
    local ids = calm_ai_ids(calm_by)
    local owner = {}
    for id, m in pairs(d.members) do
        local u = df.unit.find(tonumber(id))
        local b = type(m) == 'table' and burrow_by_id(m.burrow)
        local room = type(m) == 'table' and building_by_id(m.room)
        local why
        if not (u and b and room) then why = 'gone'
        elseif not hb_citizen(u) or u.military.squad_id ~= -1 then why = 'gone'
        elseif not in_tantrum(u) then why = 'calm'
        elseif now - (tonumber(m.since) or now) >= days * 1200 then why = 'limit'
        elseif thirsty(u) then why = 'thirst'
        elseif needs_care(u) then why = 'needs care'          -- (review) hurt while kept: to the doctors
        elseif (calm_burrows_of(u, ids)) then why = 'player burrow'
        else
            -- (review) the member's own claim is no taking (DF 50: a homeless
            -- dwarf claims a free bedroom by sleeping in it)
            local okr, free = pcall(function() return room.assigned_unit_id == -1 or room.assigned_unit_id == u.id end)
            if not (okr and free) then why = 'room taken'
            elseif not drink_still(m) then why = 'no drink' end
        end
        if why then
            calm_let_out(d, id, u, why, now, dry_run, name, released)
        else
            owner[m.burrow] = u.id
            if not dry_run and now - (tonumber(m.since) or now) >= CALM_WALK_TICKS then
                local oki, inside = pcall(dfhack.burrows.isAssignedTile, b, u.pos)
                if oki then
                    local k = inside and 'seen_in' or 'seen_out'
                    m[k] = (tonumber(m[k]) or 0) + 1
                    calm_count(d, k)
                    d.seen_dirty = true                    -- (review) saved by the status call
                end
            end
        end
    end
    -- the calm burrows' own units: only their one member (a throw mid-call, a player's hand)
    for bid, b in pairs(calm_by) do
        local have = burrow_unit_ids(b)
        for uid in pairs(have or {}) do
            if owner[bid] ~= uid then
                local u = df.unit.find(uid)
                if not dry_run and u then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
                table.insert(released, (u and name(u) or tostring(uid)) .. ' (not listed)')
            end
        end
        if not owner[bid] and not dry_run then pcall(dfhack.burrows.clearTiles, b) end
    end
end

-- For the report, and the bridge's own guard at every report: the members
-- re-checked and let out here; the citizens in a tantrum now, and how many
-- could be moved (`free`: in no burrow of a player, not thirsty).
function calm_burrow_status(txt)
    local function name(u) return (txt or tostring)(dfhack.units.getReadableName(u)) end
    local d = calm_state()
    local now = hb_now()
    local released = {}
    local before = 0
    for _ in pairs(d.members) do before = before + 1 end
    if before > 0 or next(calm_burrows()) ~= nil then calm_maintain(d, now, false, name, released) end
    local ids = calm_ai_ids(calm_burrows())
    local out = {members = 0, tantrums = 0, free = 0, held = {}, list = {}, why = d.why,
                 released_now = #released > 0 and released or nil}
    for k, v in pairs(d.stats) do out[k] = v end
    for id, m in pairs(d.members) do
        out.members = out.members + 1
        local u = df.unit.find(tonumber(id))
        if u and #out.list < CALM_MAX then
            local okc, cat = pcall(dfhack.units.getStressCategory, u)
            table.insert(out.list, {id = u.id, name = name(u), days = (now - (tonumber(m.since) or now)) // 1200,
                                    seen_in = tonumber(m.seen_in) or 0, seen_out = tonumber(m.seen_out) or 0,
                                    stress0 = m.cat0, stress = okc and cat or nil})
        end
    end
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if in_tantrum(u) then
            out.tantrums = out.tantrums + 1
            if not d.members[tostring(u.id)] then
                local okb, baby = pcall(dfhack.units.isBaby, u)
                local why
                if okb and baby then why = 'baby'
                elseif not hb_citizen(u) then why = 'insane'
                elseif u.military.squad_id ~= -1 then why = 'soldier'
                elseif thirsty(u) then why = 'thirsty'
                elseif needs_care(u) then why = needs_care(u)     -- (review) patient, resting, cannot walk
                elseif (calm_burrows_of(u, ids)) then why = 'player burrow'
                elseif select(2, calm_burrows_of(u, ids)).hosp then why = 'hospital burrow'
                elseif d.out[tostring(u.id)] and now - tonumber(d.out[tostring(u.id)]) < CALM_OUT_DAYS * 1200 then
                    why = 'resting'
                end
                if why then out.held[why] = (out.held[why] or 0) + 1 else out.free = out.free + 1 end
            end
        end
    end
    -- (review) the sightings saved too, or the measurement is lost between calls
    if #released > 0 or out.members ~= before or d.seen_dirty then
        d.seen_dirty = nil
        calm_save(d)
    end
    return out
end

-- `release`: the brain's word that every calm burrow is to be emptied (the
-- rule switched off, its status unreadable).
function calm_burrow_tick(max, days, dry_run, txt, release)
    max, days = math.min(max or CALM_MAX, CALM_MAX), days or CALM_DAYS
    local function name(u) return (txt or tostring)(dfhack.units.getReadableName(u)) end
    local d = calm_state()
    local now = hb_now()
    local released, added = {}, {}
    if release then
        for id in pairs(d.members) do
            calm_let_out(d, id, df.unit.find(tonumber(id)), 'released', now, dry_run, name, released)
        end
        if not dry_run then
            for _, b in pairs(calm_burrows()) do
                for uid in pairs(burrow_unit_ids(b) or {}) do
                    local u = df.unit.find(uid)
                    if u then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
                end
                pcall(dfhack.burrows.clearTiles, b)
            end
            calm_save(d)
        end
        if #released == 0 then return {ok = true, unchanged = true, members = 0} end
        return {ok = true, released = released, added = {}, members = 0, dry_run = dry_run or nil}
    end
    d.days = days
    calm_maintain(d, now, dry_run, name, released)
    local count = 0
    for _ in pairs(d.members) do count = count + 1 end
    -- who: each citizen in a tantrum, not a member, eligible
    local calm_by = calm_burrows()
    local ids = calm_ai_ids(calm_by)
    local cands, people = {}, {}
    local hzones = hospital_zones()
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local key = tostring(u.id)
        local was = tonumber(d.out[key])
        if was and now - was >= CALM_OUT_DAYS * 1200 then d.out[key] = nil; was = nil end
        local okb, baby = pcall(dfhack.units.isBaby, u)
        if in_tantrum(u) and not d.members[key] and not was and not (okb and baby) and hb_citizen(u)
                and u.military.squad_id == -1 and not thirsty(u) and not needs_care(u) then
            local other, which = calm_burrows_of(u, ids)
            -- (review) never one in the hospital burrow: they stay with the doctors
            if not other and not which.hosp then
                table.insert(cands, {u = u, which = which, hd = #hzones > 0 and zone_dist(u.pos, hzones) or 999})
            end
        end
        table.insert(people, u.pos)
    end
    -- the nearest to a hospital first
    table.sort(cands, function(a, c) if a.hd ~= c.hd then return a.hd < c.hd end return a.u.id < c.u.id end)
    local why
    if #cands > 0 and count < max then
        local taken = {}
        for _, m in pairs(d.members) do if type(m) == 'table' and m.room then taken[m.room] = true end end
        local loc, busy = calm_busy_zones()
        local rooms = calm_rooms(hzones, taken, people, loc)
        local drinks = drink_list()
        calm_mark_drinks(drinks, hzones, busy, people)
        local avoid = hospital_drink_ids()
        local used = {}
        for _, m in pairs(d.members) do if type(m) == 'table' and m.burrow then used[m.burrow] = true end end
        for _, c in ipairs(cands) do
            if count >= max then break end
            -- the nearest free room this dwarf can walk to, with drink they can walk to from it
            local best, bd, src, shared
            for _, r in ipairs(rooms) do
                if not taken[r.z.id] then
                    local dd = dist(c.u.pos, r.pos)
                    if (not bd or dd < bd) and can_walk(c.u.pos, r.pos) then
                        local s, sh = calm_drink(r.pos, drinks, avoid)
                        if s then best, bd, src, shared = r, dd, s, sh end
                    end
                end
            end
            if not best then
                why = #rooms == 0 and ('no free bedroom at least ' .. CALM_HOSP_DIST .. ' tiles from the hospitals')
                      or 'no free bedroom the dwarf can walk to with drink in reach'
            elseif dry_run then
                taken[best.z.id] = true
                count = count + 1
                table.insert(added, name(c.u))
            else
                -- a burrow of our own: a free calm one, else a new one
                local b
                for i = 1, CALM_MAX do
                    local nm = CALM_PREFIX .. i
                    local x = find_burrow(nm)
                    if x and not used[x.id] then b = x break end
                    if not x then b = new_burrow(nm) break end
                end
                if not b then why = 'every calm burrow in use' break end
                used[b.id] = true
                -- out of the AI's recreation burrow first (the taverns and halls,
                -- where the others are); (review) never out of the hospital burrow
                local key = tostring(c.u.id)
                local rb = c.which.rec and burrow_by_id(c.which.rec)
                if rb then
                    pcall(dfhack.burrows.setAssignedUnit, rb, c.u, false)
                    local rec = rec_state()
                    rec.members[key] = nil
                    if type(rec.friends) == 'table' then rec.friends[key] = nil end
                    rec.out[key] = now
                    pcall(dfhack.persistent.saveSiteData, RECREATION_KEY, rec)
                end
                local tiles = fill_calm(b, best.z, src, best.pos)
                local oka = pcall(dfhack.burrows.setAssignedUnit, b, c.u, true)
                if oka then
                    local okc, cat = pcall(dfhack.units.getStressCategory, c.u)
                    d.members[key] = {since = now, burrow = b.id, room = best.z.id, src = src.b.id, kind = src.kind,
                                      cat0 = okc and cat or nil, tiles = tiles}
                    taken[best.z.id] = true
                    calm_count(d, 'moved')
                    if shared then calm_count(d, 'shared_drink') end
                    calm_save(d)
                    count = count + 1
                    table.insert(added, name(c.u) .. ' (room ' .. best.z.id .. ', ' .. bd .. ' tiles away, drink: '
                                 .. src.kind .. (src.busy and ', busy: a few tiles' or '')
                                 .. (shared and ', the hospital\'s' or '') .. ')')
                else
                    pcall(dfhack.burrows.clearTiles, b)
                end
            end
        end
    end
    d.why = why
    if not dry_run then calm_save(d) end
    if #added == 0 and #released == 0 then
        if why and #cands > 0 then return {ok = false, rejected = true, error = why} end
        return {ok = true, unchanged = true, members = count}       -- nothing to change is no refusal
    end
    return {ok = true, added = added, released = released, members = count, note = why, dry_run = dry_run or nil}
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
