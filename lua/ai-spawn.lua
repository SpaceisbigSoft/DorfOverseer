-- ai-spawn: units set down on the map by the AI's own tests (the siege test's
-- war party, ai-siege-invite spawn_party; the danger test's invaders,
-- ai-military-duty spawn_test_threat). One call, spawn_units{...}:
--
--   race      creature token ('GOBLIN') or race index
--   caste     caste token or index; nil: each unit a random caste
--   count     units (1..SPAWN_MAX)
--   pos       {x, y, z}: where they go
--   spread    tiles round pos they are spread over (same level)
--   civ_id    their civilisation (-1/nil: none); group_id: a government of it
--             (create-unit only: the native route makes no historical figures)
--   flags     unit flags1 names set on each ('active_invader', ...)
--   equip     a list of create-unit equipment strings
--             ('ITEM_WEAPON_SPEAR:INORGANIC:IRON'); true: none named, nothing
--             given; nil/false: unarmed
--   profession  a df.profession name set on each (nil: as made)
--
-- Returns the new units' ids and info {route ('create-unit' or 'native'),
-- equipped, armed, equip_error, cu_error, native_error, asked, made, placed,
-- place_error, capped}, or nil, a short reason and info. Never throws.
--
-- Two routes, in order:
--  1. DFHack's modtools/create-unit (in case a later DFHack fixes it). DFHack
--     53.17-r1's is stale for DF 53: "create-unit.lua:164: Cannot read field
--     world.arena_spawn: not found" (A, 25 Nov 23:21).
--  2. native: DFHack 53's dfhack.units.create(race, caste), the way DFHack's
--     own fix of create-unit does it (scripts PR #1530, activate_and_place_unit,
--     apply_equipment): each unit put in world.units.active, its pos set to a
--     tile round pos (spawn_tiles, one unit a tile) and the tile's occupancy
--     set by dfhack.units.teleport (else by hand), flags1.inactive and
--     hidden_in_ambush cleared, its body sizes left for DF to work out
--     (create-unit's induceBodyComputations); armed by dfhack.items.createItem
--     and dfhack.items.moveToInventory on the right body part (forceequip's
--     parts: GRASP, UPPERBODY, HEAD, LOWERBODY, STANCE). No historical
--     figure or nemesis: the siege watch counts dfhack.units.isInvader, and
--     53.17-r1's createNemesis sets nemesis_record fields DF 53 has not.
--     (The arena route of 0.105.124 is gone: DF 53 places no unit from a
--     simulated click, A 26 Nov 00:35.)
--
-- DF 53 names used are DFHack 53.17-r1's (tests/fixtures/df-names.json).
--@ module = true

SPAWN_MAX = 30
EQUIP_KINDS = {               -- create-unit's item tokens: the item type, the raws' list
    {'ITEM_WEAPON_', 'WEAPON', 'weapons'}, {'ITEM_ARMOR_', 'ARMOR', 'armor'}, {'ITEM_HELM_', 'HELM', 'helms'},
    {'ITEM_SHIELD_', 'SHIELD', 'shields'}, {'ITEM_PANTS_', 'PANTS', 'pants'}, {'ITEM_SHOES_', 'SHOES', 'shoes'},
    {'ITEM_GLOVES_', 'GLOVES', 'gloves'}, {'ITEM_AMMO_', 'AMMO', 'ammo'},
}
-- where each kind goes: the body part flag and the inventory role (forceequip's
-- parts; a shield strapped on the free hand)
WEAR = {WEAPON = {'GRASP', 'Weapon'}, SHIELD = {'GRASP', 'Strapped'}, ARMOR = {'UPPERBODY', 'Worn'},
        HELM = {'HEAD', 'Worn'}, PANTS = {'LOWERBODY', 'Worn'}, SHOES = {'STANCE', 'Worn'},
        GLOVES = {'GRASP', 'Worn'}}
-- a weapon the race's civ makes, when it makes not the one asked: these first
PREFER_WEAPONS = {'ITEM_WEAPON_SPEAR', 'ITEM_WEAPON_SWORD_SHORT', 'ITEM_WEAPON_AXE_BATTLE', 'ITEM_WEAPON_MACE',
                  'ITEM_WEAPON_HAMMER_WAR', 'ITEM_WEAPON_SCIMITAR'}

local function try(f, ...)
    local ok, v = pcall(f, ...)
    if ok then return v end
    return nil
end

-- an error's text without its "file:line: " head, cut short
local function short(e, n)
    local s = tostring(e):gsub('^[^\n]-%.lua:%d+: ', ''):gsub('^%[string "[^"]*"%]:%d+: ', '')
    return s:sub(1, n or 120)
end

local function vlen(v) return try(function() return #v end) or 0 end

-- the race's index and raw, and its castes' indices (the one named, or all)
function race_castes(race, caste)
    local creatures = df.global.world.raws.creatures.all
    local rid, cre
    if type(race) == 'number' then
        rid, cre = race, creatures[race]
    else
        for i, c in ipairs(creatures) do
            if c.creature_id == race then rid, cre = i, c break end
        end
    end
    if not cre then return nil, 'no creature ' .. tostring(race) end
    local castes = {}
    for i, c in ipairs(cre.caste) do
        if caste == nil or caste == i or c.caste_id == caste then table.insert(castes, i) end
    end
    if #castes == 0 then return nil, 'no caste ' .. tostring(caste) .. ' of ' .. tostring(race) end
    return rid, castes
end

-- a tile a unit can stand on: walkable, no water or magma, no building
-- (outside: and open to the sky, as pos is)
function standable(x, y, z, outside)
    local ok, good = pcall(function()
        if not dfhack.maps.isValidTilePos(x, y, z) then return false end
        local tt = dfhack.maps.getTileType(x, y, z)
        if not tt then return false end
        local a = df.tiletype_shape.attrs[df.tiletype.attrs[tt].shape]
        if not a or not a.walkable then return false end
        local f = dfhack.maps.getTileFlags(x, y, z)
        if not f or (f.flow_size or 0) > 0 then return false end
        if outside and not f.outside then return false end
        return dfhack.buildings.findAtTile(xyz2pos(x, y, z)) == nil
    end)
    return ok and good
end

-- the tiles round pos (pos first, then by distance) the units go to: standable,
-- on pos's walkable group (none inside the fort when pos is outside)
function spawn_tiles(pos, spread)
    local f = try(dfhack.maps.getTileFlags, pos.x, pos.y, pos.z)
    local outside = f and f.outside or false
    local grp = try(dfhack.maps.getWalkableGroup, xyz2pos(pos.x, pos.y, pos.z))
    local out = {}
    for dy = -spread, spread do
        for dx = -spread, spread do
            local x, y = pos.x + dx, pos.y + dy
            if standable(x, y, pos.z, outside) then
                local g = try(dfhack.maps.getWalkableGroup, xyz2pos(x, y, pos.z))
                if not grp or grp == 0 or g == grp then
                    table.insert(out, {x = x, y = y, z = pos.z, d = dx * dx + dy * dy})
                end
            end
        end
    end
    table.sort(out, function(a, b) return a.d < b.d end)
    return out
end

-- create-unit's equipment strings as {item_type, subtype, mat_type, mat_index}
function equip_rows(list)
    local rows = {}
    for _, s in ipairs(list) do
        local tok, mat = tostring(s):match('^([%w_]+):(.+)$')
        if not tok then error('bad equipment ' .. tostring(s)) end
        local kind
        for _, k in ipairs(EQUIP_KINDS) do
            if tok:sub(1, #k[1]) == k[1] then kind = k break end
        end
        if not kind then error('unknown item ' .. tok) end
        local sub
        for _, d in ipairs(df.global.world.raws.itemdefs[kind[3]]) do
            if d.id == tok then sub = d.subtype break end
        end
        if not sub then error('no item ' .. tok) end
        local mi = dfhack.matinfo.find(mat)
        if not mi then error('no material ' .. mat) end
        table.insert(rows, {df.item_type[kind[2]], sub, mi.type, mi.index, kind[2], tok})
    end
    return rows
end

-- the units made since: ids from `next0` (unit_next_id before), else (with
-- `before`) the active units not in it
local function made_since(next0, before)
    local out = {}
    local next1 = try(function() return df.global.unit_next_id end)
    if next0 and next1 and next1 > next0 then
        for id = next0, next1 - 1 do
            local u = try(df.unit.find, id)
            if u then table.insert(out, u) end
        end
        return out
    end
    if not before then return out end
    for _, u in ipairs(try(function() return df.global.world.units.active end) or {}) do
        if not before[u.id] then table.insert(out, u) end
    end
    return out
end

local function active_ids()
    local seen = {}
    for _, u in ipairs(try(function() return df.global.world.units.active end) or {}) do seen[u.id] = true end
    return seen
end

-- --- route 1: modtools/create-unit ---------------------------------------------------------

local function by_create_unit(o)
    local okm, CU = pcall(reqscript, 'modtools/create-unit')
    if not okm or type(CU) ~= 'table' or not CU.createUnit then return nil, 'DFHack has no modtools/create-unit' end
    local range = {offset_x = o.spread, offset_y = o.spread, offset_z = 0}
    local function make(eq)
        local next0 = try(function() return df.global.unit_next_id end)
        local before = active_ids()
        local units = CU.createUnit(o.race, o.caste, o.pos, range, 'Walkable', nil, false, o.civ_id, o.group_id,
                                    nil, nil, nil, o.count, eq, nil, nil, nil, o.flags, nil)
        if type(units) ~= 'table' or #units == 0 then units = made_since(next0, before) end
        if #units == 0 then error('no unit made') end
        return units
    end
    local eq = type(o.equip) == 'table' and #o.equip > 0 and o.equip or nil
    local ok, units = pcall(make, eq)
    local equip_error
    if not ok and eq then
        equip_error = short(units)
        eq = nil
        ok, units = pcall(make, nil)
    end
    if not ok then return nil, short(units, 160) end
    return units, nil, {equipped = eq ~= nil, equip_error = equip_error}
end

-- --- route 2: native, dfhack.units.create -------------------------------------------------

-- the weapon subtype to give: the one asked if the civ makes it (or there is
-- no civ, or its list is empty), else one of its own the race can wield in
-- melee (PREFER_WEAPONS first); none of its own fits: the one asked
function civ_weapon(civ_id, size, sub)
    local e = civ_id and civ_id >= 0 and try(df.historical_entity.find, civ_id)
    local list = e and try(function() return e.resources.weapon_type end)
    if not list or vlen(list) == 0 then return sub end
    local fits, by_id, first = {}, {}, nil
    for i = 0, vlen(list) - 1 do
        local st = list[i]
        local d = try(df.itemdef_weaponst.find, st)
        if d and (d.skill_ranged or -1) < 0 and (not size or size >= (d.minimum_size or 0)) then
            fits[st] = true
            by_id[d.id] = st
            first = first or st
        end
    end
    if fits[sub] then return sub end
    for _, id in ipairs(PREFER_WEAPONS) do
        if by_id[id] then return by_id[id] end
    end
    return first or sub
end

-- the equipment rows for the race and civ (the weapon swapped for one of the
-- civ's own), or nil and why
local function native_rows(o, rid)
    local ok, rows = pcall(equip_rows, o.equip)
    if not ok then return nil, short(rows) end
    local size = try(function() return df.global.world.raws.creatures.all[rid].caste[0].misc.adult_size end)
    local out = {}
    for _, r in ipairs(rows) do
        if r[5] == 'WEAPON' then
            table.insert(out, {r[1], civ_weapon(o.civ_id, size, r[2]), r[3], r[4], r[5]})
        else
            table.insert(out, r)
        end
    end
    return out
end

-- a body part of the unit with `flag`, not in `used` (and not lost)
local function free_part(u, flag, used)
    local parts = try(function() return u.body.body_plan.body_parts end)
    for i = 0, vlen(parts) - 1 do
        local bp = parts[i]
        if not used[i] and try(function() return bp.flags[flag] end)
                and not try(function() return u.body.components.body_part_status[i].missing end) then
            return i
        end
    end
    return nil
end

-- the rows' items made and put on the unit (apply_equipment of DFHack's fix,
-- each on its body part): the pieces put on, and the first errors
local function arm(u, rows)
    local put, errs = 0, {}
    local hands, worn = {}, {}
    for _, r in ipairs(rows) do
        local how = WEAR[r[5]]
        if not how then
            table.insert(errs, 'no place for ' .. tostring(r[5]))
        else
            local okc, items = pcall(dfhack.items.createItem, u, r[1], r[2], r[3], r[4], false)
            if not okc or type(items) ~= 'table' or #items == 0 then
                table.insert(errs, 'createItem ' .. tostring(r[5]) .. ': ' .. (okc and 'no item' or short(items, 80)))
            else
                for _, it in ipairs(items) do
                    local used = hands               -- a weapon and a shield: one hand each
                    if how[1] ~= 'GRASP' or r[5] == 'GLOVES' then
                        worn[r[5]] = worn[r[5]] or {}
                        used = worn[r[5]]
                    end
                    local bp = free_part(u, how[1], used)
                    local okm, moved = false, nil
                    if bp then
                        okm, moved = pcall(dfhack.items.moveToInventory, it, u, df.inv_item_role_type[how[2]], bp)
                    end
                    if okm and moved then
                        used[bp] = true
                        put = put + 1
                    else
                        pcall(dfhack.items.remove, it)
                        table.insert(errs, tostring(r[5]) .. (bp and (' not put on: ' .. (okm and 'refused' or short(moved, 80)))
                                                           or (' no free ' .. how[1] .. ' part')))
                    end
                end
            end
        end
    end
    pcall(function() u.military.uniform_drop:resize(0) end)    -- create-unit's setEquipmentOwnership: kept on
    pcall(function() u.flags2.calculated_inventory = false end)
    return put, errs
end

-- the unit on tile t: its pos, the tile's occupancy (teleport onto its own
-- tile sets it right; else by hand, as DFHack's fix does)
local function place(u, t)
    u.pos.x, u.pos.y, u.pos.z = t.x, t.y, t.z
    local okt, moved = pcall(dfhack.units.teleport, u, xyz2pos(t.x, t.y, t.z))
    if not (okt and moved) then
        local b = dfhack.maps.getTileBlock(t.x, t.y, t.z)
        b.occupancy[t.x % 16][t.y % 16].unit = true
    end
    u.flags1.inactive = false
    u.flags1.hidden_in_ambush = false
    -- create-unit's induceBodyComputations: DF works the sizes out again
    u.flags2.calculated_nerves = false
    u.flags2.calculated_bodyparts = false
    u.flags3.body_part_relsize_computed = false
    u.flags3.size_modifier_computed = false
    u.flags3.weight_computed = false
end

local function by_native(o)
    if not dfhack.isMapLoaded() then return nil, 'no map loaded' end
    if type(try(function() return dfhack.units.create end)) ~= 'function' then return nil, 'this DFHack has no dfhack.units.create' end
    local rid, castes = race_castes(o.race, o.caste)
    if not rid then return nil, castes end
    local tiles = spawn_tiles(o.pos, o.spread)
    if #tiles == 0 then return nil, 'no tile round the spot a unit can stand on' end
    local info = {asked = o.count, made = 0, placed = 0}
    local n = math.min(o.count, #tiles)          -- one unit a tile
    if n < o.count then info.capped = n end
    local rows
    if type(o.equip) == 'table' and #o.equip > 0 then
        rows, info.equip_error = native_rows(o, rid)
    end
    local active = df.global.world.units.active
    local units = {}
    for i = 1, n do
        local okc, u = pcall(dfhack.units.create, rid, castes[math.random(1, #castes)])
        if not okc or not u then
            info.create_error = okc and 'dfhack.units.create made no unit' or short(u, 160)
            break
        end
        info.made = info.made + 1
        local oki, e = pcall(function() active:insert('#', u) end)
        if not oki then
            info.create_error = 'not put in world.units.active: ' .. short(e, 120)   -- in units.all only, inactive
            break
        end
        local okp, pe = pcall(place, u, tiles[i])
        if okp then info.placed = info.placed + 1 else info.place_error = info.place_error or short(pe, 120) end
        table.insert(units, u)
    end
    if #units == 0 then return nil, info.create_error or 'no unit made', info end
    if o.profession and df.profession[o.profession] then
        for _, u in ipairs(units) do pcall(function() u.profession = df.profession[o.profession] end) end
    end
    info.rows = rows
    return units, nil, info
end

-- the native units armed (after civ and flags are set), info filled in
local function arm_all(units, info)
    local rows = info.rows
    info.rows = nil
    if not rows then info.equipped = false return end
    local armed, errs, seen = 0, {}, {}
    local function note(e)
        if not seen[e] and #errs < 4 then seen[e] = true table.insert(errs, e) end
    end
    for _, u in ipairs(units) do
        local okA, put, e = pcall(arm, u, rows)
        if okA and put > 0 then armed = armed + 1 end
        if not okA then note(short(put, 120)) else for _, x in ipairs(e) do note(x) end end
    end
    info.armed = armed
    info.equipped = armed > 0
    if #errs > 0 then info.equip_error = (info.equip_error and (info.equip_error .. '; ') or '') .. table.concat(errs, '; ') end
    if armed == 0 and not info.equip_error then info.equip_error = 'no piece put on' end
end

-- --- the call ------------------------------------------------------------------------------

local function finish(units, o, native)
    local ids = {}
    local flags = {}
    for _, f in ipairs(o.flags or {}) do flags[f] = true end
    -- no historical figure (as gui/sandbox's hostile units): marauder makes them attack
    if native and flags.active_invader then flags.marauder = true end
    for _, u in ipairs(units) do
        pcall(function()
            if o.civ_id and o.civ_id >= 0 then u.civ_id = o.civ_id end
            for f in pairs(flags) do u.flags1[f] = true end
        end)
        table.insert(ids, u.id)
    end
    return ids
end

local function spawn(o)
    if type(o) ~= 'table' or o.race == nil or type(o.pos) ~= 'table' then return nil, 'spawn_units: no race or pos', {} end
    o = {race = o.race, caste = o.caste, count = math.max(1, math.min(SPAWN_MAX, tonumber(o.count) or 1)),
         pos = {x = o.pos.x, y = o.pos.y, z = o.pos.z}, spread = math.max(0, tonumber(o.spread) or 0),
         civ_id = o.civ_id, group_id = o.group_id, flags = o.flags, equip = o.equip, profession = o.profession}
    local units, why, info = by_create_unit(o)
    if units then
        info.route = 'create-unit'
        return finish(units, o, false), nil, info
    end
    local cu_error = why
    local okN
    okN, units, why, info = pcall(by_native, o)
    if not okN then units, why, info = nil, short(units, 200), {} end
    info = info or {}
    info.cu_error = cu_error
    if not units then
        info.route = 'none'
        info.native_error = why
        info.rows = nil
        return nil, 'create-unit: ' .. tostring(cu_error) .. '; native: ' .. tostring(why), info
    end
    info.route = 'native'
    local ids = finish(units, o, true)
    arm_all(units, info)
    return ids, nil, info
end

function spawn_units(o)
    local ok, ids, why, info = pcall(spawn, o)
    if not ok then return nil, 'spawn_units: ' .. short(ids, 200), {route = 'none'} end
    return ids, why, info
end

-- info as a record keeps it: its numbers, booleans and strings (cut to 300)
function brief(info)
    local out = {}
    for k, v in pairs(type(info) == 'table' and info or {}) do
        if type(v) == 'string' then out[k] = v:sub(1, 300)
        elseif type(v) == 'number' or type(v) == 'boolean' then out[k] = v end
    end
    return out
end
