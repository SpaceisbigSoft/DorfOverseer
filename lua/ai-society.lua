-- Things the AI sets up so the player doesn't have to:
--   * a civilian-alert shelter: a burrow named "AI shelter" covering the
--     inside of the fort (not caverns, not outside), registered as the
--     civilian alert's burrow
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
local function fort_levels()
    local lo, hi
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local z = u.pos.z
        if z >= 0 then
            lo = lo and math.min(lo, z) or z
            hi = hi and math.max(hi, z) or z
        end
    end
    return lo and (lo - 2) or nil, hi and (hi + 2) or nil
end

function fill_shelter(b)
    local lo, hi = fort_levels()
    if not lo then return 0 end
    local n = 0
    for _, block in ipairs(df.global.world.map.map_blocks) do
        local z = block.map_pos.z
        if z >= lo and z <= hi then
            for x = 0, 15 do
                for y = 0, 15 do
                    local d = block.designation[x][y]
                    if not d.hidden and not d.outside and not d.feature_local and not d.feature_global
                            and d.flow_size == 0 then
                        local tt = block.tiletype[x][y]
                        local shape = df.tiletype_shape[df.tiletype.attrs[tt].shape]
                        if OPEN[shape] then
                            dfhack.burrows.setAssignedBlockTile(b, block, x, y, true)
                            n = n + 1
                        end
                    end
                end
            end
        end
    end
    return n
end

-- Make (or refresh) the "AI shelter" burrow and make it the civilian alert's.
function setup_shelter()
    if alert_has_burrow() then
        return {ok = false, rejected = true, error = 'the civilian alert already has a burrow'}
    end
    local b = find_burrow(SHELTER_NAME) or new_burrow(SHELTER_NAME)
    dfhack.burrows.clearTiles(b)
    local n = fill_shelter(b)
    if n == 0 then
        return {ok = false, error = 'found no inside tiles to shelter in'}
    end
    require('utils').insert_sorted(civ_alert().burrows, b.id)
    return {ok = true, burrow_id = b.id, tiles = n}
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
                    if not seen[name] then seen[name], e.citizens = true, e.citizens + 1 end
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

local function rec_base(u)
    if not dfhack.units.isAdult(u) or u.military.squad_id ~= -1 then return false end
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
