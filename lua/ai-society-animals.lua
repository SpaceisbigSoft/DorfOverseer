-- ai-society-animals: pastures and the grass a grazer needs, nest boxes for the hens, war training,
-- the gate guard's burrow and the war dogs at the gate, the pastures' report.
--
-- (r8) A part of ai-society, not a script of its own: ai-society.lua loads it
-- into its own environment, so every name here is reqscript('ai-society').name
-- and the names defined there and in the parts before it are in reach.

if not SOCIETY_PART_LOCALS then qerror('ai-society-animals is a part of ai-society; run ai-society') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-animals'] = '0.105.108'   -- (0.105.26) bumped with BRIDGE_VERSION

local report_citizens, report_units, utils = SOCIETY_PART_LOCALS.report_citizens, SOCIETY_PART_LOCALS.report_units, SOCIETY_PART_LOCALS.utils   -- (r8) the hub's locals

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

-- (0.105.33, L6) An animal that came with a caravan, a visitor or a
-- diplomat (a dwarven caravan's pack animals are own-civ and tame), or one
-- following such a unit: never pastured, never trained (DFHack's old zone
-- tool skipped flags1.merchant too). Pinned to a pasture, it can hold up the
-- caravan.
function visiting_animal(u)
    local function yes(f)
        local ok, v = pcall(f)
        return ok and v and true or false
    end
    local function outsider(x)
        return yes(function() return x.flags1.merchant end)
            or yes(function() return dfhack.units.isMerchant(x) end)
            or yes(function() return dfhack.units.isVisitor(x) end)
            or yes(function() return dfhack.units.isDiplomat(x) end)
            or yes(function() return x.flags1.diplomat end)
    end
    if outsider(u) then return true end
    local okf, lead = pcall(function()
        local id = u.following and u.following.id
        if id == nil or id < 0 then id = u.relationship_ids and u.relationship_ids.PetOwner end
        if id ~= nil and id >= 0 then return df.unit.find(id) end
        return nil
    end)
    if okf and lead and outsider(lead) then return true end
    return false
end

-- (0.105.51) A pet: DF moves it with its owner, so the AI never pens it
-- (fort C crashed on a soldier's pet doe rabbit the AI had pastured).
function pet_animal(u)
    local ok, p = pcall(dfhack.units.isPet, u)
    if ok and p then return true end
    local okr, id = pcall(function() return u.relationship_ids.PetOwner end)
    return okr and type(id) == 'number' and id ~= -1
end

function unpastured_grazers()
    local out = {}
    for _, u in ipairs(report_units()) do
        if dfhack.units.isAlive(u) and dfhack.units.isTame(u) and dfhack.units.isOwnCiv(u)
                and not u.flags1.caged and dfhack.units.isGrazer(u) and not visiting_animal(u)
                and not pet_animal(u)
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
            and dfhack.units.isAdult(u) and dfhack.units.isFemale(u)) or u.flags1.caged or visiting_animal(u) then
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
    for _, u in ipairs(report_units()) do
        if egg_layer(u) then
            hens = hens + 1
            local ref = dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED)
            if ref then by_zone[ref.building_id] = (by_zone[ref.building_id] or 0) + 1
            elseif not pet_animal(u) then table.insert(loose, u) end     -- (0.105.51) a pet goes with its owner
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
            and dfhack.units.isAdult(u)) or dfhack.units.isCitizen(u) or visiting_animal(u) then
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
    for _, u in ipairs(report_units()) do
        local okp, prof = pcall(function() return df.profession[u.profession] end)
        if okp and prof == 'TRAINED_WAR' and dfhack.units.isAlive(u) and dfhack.units.isOwnCiv(u) then
            out.war_trained = out.war_trained + 1
        elseif not assigned[u.id] and war_trainable(u) then
            out.war_candidates = out.war_candidates + 1
        end
    end
    local labor = df.unit_labor.ANIMALTRAIN
    for _, u in ipairs(report_citizens(true)) do
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
    for _, u in ipairs(report_units()) do
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
    for _, u in ipairs(report_units()) do
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
    local n, tiles, spare, dogs = 0, 0, 0, 0
    for _, p in ipairs(list) do
        -- (0.105.47) the gate dogs' pen is a guard post, no pasture (the
        -- scorecard counted it: the War-hold's 9 pastures)
        if tostring(p.zone.name or '') == GATE_DOGS_NAME then dogs = dogs + 1 end
        if tostring(p.zone.name or '') == AI_PASTURE_NAME then
            n = n + 1
            tiles = tiles + p.area
            spare = spare + math.max(0, p.spare)
        end
    end
    return {grazers = #waiting, count = #list - dogs,
            needs = {need = need, smallest = smallest or 0, spare = #list > 0 and math.max(0, list[1].spare) or 0},
            ai = {count = n, tiles = tiles, spare = spare}}
end

