-- (0.105.47, J17) The raid policy's facts (read here) and the pets a raid
-- party can't leave without (released here, and put back).
--
-- The player, 14 Nov 17:47: "War-holds [should] potentially attack any
-- others, but still allow for some allies. Other fort types should still
-- allow for the option of raiding, but be less hostile and more
-- reactionary, or if some other hostile towns are setting up nearby be able
-- to deal with that." The brain decides (brain/planner_raids.py); this
-- module gives it what the targets list (ai-missions, hostile sites only)
-- doesn't:
--
--   raid_sites()    every reachable site of another owner near the fort (a
--                   civ at peace too, a bandit camp, a lair with an owner):
--                   its owner and civ, how the fort's civ stands with it,
--                   its type, how many live there, the distance; the nearest
--                   RAID_PER_OWNER of each owner, RAID_MAX in all, within
--                   RAID_MAX_DIST world tiles, the fort's landmass only
--   pets_report(squads)  the pets of the soldiers at home that are held: in
--                   a pasture or another zone (the AI's own: named "AI ..."),
--                   a cage, a chain; and the book of pets the AI let out for
--                   a mission, each with `ready` (back home: put it back)
--   release_pets(ids, dry_run)  pets taken out of the AI's own zone for the
--                   trip (booked in the save); never a cage, a chain or the
--                   player's zone
--   restore_pets(dry_run)  the booked pets put back in their zone once the
--                   pet and its owner are home again
--
-- Live 14 Nov 17:38: a raid squad waited at the map edge (x0 y131) because
-- two members' pets couldn't come (a sheep kept in an AI pasture, a
-- peafowl): a pet held in a zone holds its owner back.
--@ module = true

RAID_MAX_DIST = 40         -- world tiles: farther sites are no raid's business
RAID_PER_OWNER = 3         -- the nearest sites of each owner
RAID_MAX = 30
RAID_NAME = 40
-- (0.105.48, K9) the site types people live in (df.world_site_type names; the
-- rest, Monument, LairShrine, Cave, ImportantLocation, PlayerFortress, are
-- never a raid's target: the audit's world had 1210 monuments of unknown
-- civs and the aggressive rule picked them first, being "weakest")
RAID_LIVED_IN = {Town = true, Hamlet = true, Fortress = true, DarkFortress = true, MountainHalls = true,
                 ForestRetreat = true, Camp = true, Tower = true}

AI_ZONE_PREFIX = 'AI '     -- the AI's own zones' names ('AI pasture', 'AI gate dogs', ...)
PET_BOOK_KEY = 'ai-overseer/raid_pets'
PET_BOOK_MAX = 24
PETS_MAX = 20

local function int(v)
    v = tonumber(v)
    return v and math.tointeger(v) or v
end

local function short(s, max)
    if type(s) ~= 'string' then return nil end
    s = s:gsub('[%c]', ' ')
    if s == '' then return nil end
    return s:sub(1, max or RAID_NAME)
end

local function enum_name(enum, v)
    if v == nil or enum == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return tonumber(v) and tostring(v) or nil
end

local function name_of(name)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, true) end)
    if ok and type(s) == 'string' and s ~= '' then return short(s) end
    ok, s = pcall(function() return dfhack.TranslateName(name, true) end)
    if ok and type(s) == 'string' and s ~= '' then return short(s) end
    return nil
end

-- the items of a DF vector (0-based) or a plain Lua list (tests)
local function each(v)
    local out = {}
    if v == nil then return out end
    local ok, n = pcall(function() return #v end)
    if not ok or type(n) ~= 'number' then return out end
    local ok0, first = pcall(function() return v[0] end)
    local base = (ok0 and first ~= nil) and 0 or 1
    for i = base, base + n - 1 do
        local okv, x = pcall(function() return v[i] end)
        if okv and x ~= nil then table.insert(out, x) end
    end
    return out
end

local function hostile(rel)
    return type(rel) == 'string' and (rel:find('War') ~= nil or rel == 'Skirmishing')
end

local function abs_tick()
    local ok, t = pcall(function() return reqscript('ai-util').abs_tick() end)
    if ok and type(t) == 'number' then return t end
    local ok2, t2 = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok2 and t2 or 0
end

-- ---------------------------------------------------------------------------
-- the sites a raid could go to

-- the fort civ's diplomacy: entity id -> relation name
local function relations(civ)
    local rel = {}
    pcall(function()
        local e = df.historical_entity.find(civ)
        for _, st in ipairs(each(e.relations.diplomacy.state)) do
            local okg, gid = pcall(function() return st.group_id end)
            local okr, r = pcall(function() return st.relation end)
            if okg and gid and okr then rel[gid] = enum_name(df.diplomacy_state_type, r) end
        end
    end)
    return rel
end

local function landmass(s)
    local ok, M = pcall(function() return reqscript('ai-missions') end)
    if not ok or type(M) ~= 'table' or type(M.site_landmass) ~= 'function' then return nil end
    local okl, l = pcall(M.site_landmass, s)
    return okl and l or nil
end

-- Pure: the rows kept, nearest first: at most `per` of each owner, `max` in
-- all, none past `max_dist`
function pick_sites(rows, per, max, max_dist)
    table.sort(rows, function(a, b)
        if a.dist ~= b.dist then return a.dist < b.dist end
        return a.site_id < b.site_id
    end)
    local n_of, out = {}, {}
    for _, r in ipairs(rows) do
        if #out >= max then break end
        if r.dist <= max_dist then
            local key = r.civ_id and ('c' .. r.civ_id) or ('o' .. tostring(r.owner_id))
            if (n_of[key] or 0) < per then
                n_of[key] = (n_of[key] or 0) + 1
                table.insert(out, r)
            end
        end
    end
    return out
end

-- (0.105.48, K9) A site's people: resident_count (first_calc_total_pop, maybe 0
-- for a site never loaded), else its populace (the entity populations' counts
-- and the nemesis living there). Returns the count, or nil when none of it
-- can be read or all of it is 0 (unknown: the brain uses raid_unknown_pop).
function site_pop(s)
    local okn, pop = pcall(function() return s.resident_count end)
    if okn and type(pop) == 'number' and pop > 0 then return int(pop) end
    local n = 0
    pcall(function()
        for _, ip in ipairs(each(s.populace.inhabitants)) do
            local c = tonumber(ip.count)
            if c and c > 0 then n = n + c end
        end
    end)
    pcall(function() n = n + #s.populace.nemesis end)
    if n > 0 then return int(n) end
    return nil
end

function raid_sites()
    local okp, civ, group, fort_site = pcall(function()
        return df.global.plotinfo.civ_id, df.global.plotinfo.group_id, df.global.plotinfo.site_id
    end)
    if not okp then return {rows = {}, error = 'plotinfo'} end
    local list = {}
    pcall(function() list = each(df.global.world.world_data.sites) end)
    local fs
    for _, s in ipairs(list) do
        local ok, id = pcall(function() return s.id end)
        if ok and id == fort_site then fs = s break end
    end
    local okf, fx, fy = pcall(function() return fs.pos.x, fs.pos.y end)
    if not fs or not okf then return {rows = {}, error = 'the fort site'} end
    local fland = landmass(fs)
    local rel = relations(civ)
    local names, kinds = {}, {}
    local function ent_info(id)
        if not id or id < 0 then return nil, nil end
        if names[id] == nil then
            local e = nil
            pcall(function() e = df.historical_entity.find(id) end)
            names[id] = false
            pcall(function() names[id] = e and name_of(e.name) or false end)
            kinds[id] = false
            pcall(function() kinds[id] = df.historical_entity_type[e.type] or false end)
        end
        return names[id] or nil, kinds[id] or nil
    end
    local rows, unread, other_land = {}, 0, 0
    for _, s in ipairs(list) do
        local ok, row = pcall(function()
            if s.id == fort_site then return nil end
            local okh, hidden = pcall(function() return s.flag.HIDDEN end)
            if okh and hidden then return nil end
            local okr, ruined = pcall(function() return s.flag.RUINED end)
            if okr and ruined then return nil end
            local c = s.civ_id
            local okc, cur = pcall(function() return s.cur_owner_id end)
            if not okc then cur = nil end
            local who = (cur and cur >= 0 and cur) or (c and c >= 0 and c) or nil
            if not who then return nil end
            if c == civ or who == civ or who == group or cur == civ or cur == group then return nil end
            local dist = math.max(math.abs(s.pos.x - fx), math.abs(s.pos.y - fy))
            if dist > RAID_MAX_DIST then return nil end
            local l = landmass(s)
            if fland ~= nil and l ~= nil and l ~= fland then other_land = other_land + 1; return nil end
            local owner_name, owner_kind = ent_info(who)
            local civ_id = (c and c >= 0) and c or (owner_kind == 'Civilization' and who or nil)
            local civ_name = civ_id and ent_info(civ_id) or owner_name
            local r = (civ_id and rel[civ_id]) or rel[who]
            local stype = enum_name(df.world_site_type, s.type)
            if not RAID_LIVED_IN[stype] then return nil end
            local pop = site_pop(s)
            local e = {site_id = int(s.id), site = name_of(s.name), dist = int(dist),
                       type = stype,
                       civ_id = civ_id and int(civ_id) or nil, owner_id = int(who), civ = civ_name,
                       owner_kind = owner_kind, relation = r or 'unknown',
                       hostile = hostile(r) or nil, at_war = (type(r) == 'string' and r:find('War') ~= nil) or nil,
                       pop = pop}
            -- no civilisation behind it (bandits, a monster's band): nobody's friend
            if not civ_id then e.bandit = true end
            return e
        end)
        if not ok then unread = unread + 1 elseif row then table.insert(rows, row) end
    end
    local out = {rows = pick_sites(rows, RAID_PER_OWNER, RAID_MAX, RAID_MAX_DIST), known = #rows}
    if unread > 0 then out.unread = unread end
    if other_land > 0 then out.other_landmass = other_land end
    return out
end

-- ---------------------------------------------------------------------------
-- pets held

local function zone_of(u)
    local ok, z = pcall(function()
        local ref = dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED)
        if not ref then return false end
        return df.building.find(ref.building_id) or false
    end)
    if not ok then return nil end
    return z or nil
end

local function zone_name(z)
    local ok, n = pcall(function() return tostring(z.name or '') end)
    return ok and n or ''
end

local function ai_zone(z)
    return z ~= nil and zone_name(z):sub(1, #AI_ZONE_PREFIX) == AI_ZONE_PREFIX
end

local function is_pen(z)
    local ok, yes = pcall(function() return z.type == df.civzone_type.Pen end)
    return ok and yes
end

-- How a unit is held: 'cage', 'chain', 'pasture', 'zone' (with the zone), or nil
function held_of(u)
    local okc, caged = pcall(function() return u.flags1.caged end)
    if okc and caged then return 'cage' end
    local okh, chained = pcall(function() return u.flags1.chained end)
    if okh and chained then return 'chain' end
    local z = zone_of(u)
    if z then return is_pen(z) and 'pasture' or 'zone', z end
    return nil
end

local function alive(u)
    local ok, v = pcall(function() return dfhack.units.isAlive(u) end)
    if ok then return v and true or false end
    local okk, k = pcall(function() return u.flags2.killed end)
    return not (okk and k)
end

local function on_map(u)
    local ok, v = pcall(function() return u.flags1.inactive end)
    return not (ok and v)
end

local function race_word(u)
    local ok, n = pcall(function()
        local cr = df.creature_raw.find(u.race)
        return cr.caste[u.caste].caste_name[0]
    end)
    if ok and type(n) == 'string' and n ~= '' then return short(n, 24) end
    ok, n = pcall(function() return df.creature_raw.find(u.race).creature_id end)
    if ok and type(n) == 'string' then return short(n:lower(), 24) end
    return 'pet'
end

local function units()
    local ok, v = pcall(function() return df.global.world.units.active end)
    return ok and each(v) or {}
end

-- The held pets of the given owners (unit id set; nil: anyone's):
-- {[owner unit id] = {{pet_id, pet, held, zone_id, ai}, ...}}
function held_pets(owners)
    local out = {}
    for _, u in ipairs(units()) do
        pcall(function()
            local owner = u.relationship_ids.PetOwner
            if type(owner) ~= 'number' or owner < 0 then return end
            if owners and not owners[owner] then return end
            if not alive(u) then return end
            local held, z = held_of(u)
            if not held then return end
            local e = {pet_id = int(u.id), pet = race_word(u), held = held}
            if z then
                pcall(function() e.zone_id = int(z.id) end)
                e.ai = ai_zone(z) or nil
                e.zone = short(zone_name(z), 24)
            end
            out[owner] = out[owner] or {}
            table.insert(out[owner], e)
        end)
    end
    return out
end

local function book()
    local ok, U = pcall(function() return reqscript('ai-util') end)
    local b = ok and U.site_get(PET_BOOK_KEY, {}) or {}
    local out = {}
    for _, e in ipairs(type(b) == 'table' and b or {}) do
        if type(e) == 'table' and tonumber(e.pet_id) and tonumber(e.zone_id) then table.insert(out, e) end
    end
    return out
end

local function save_book(b)
    while #b > PET_BOOK_MAX do table.remove(b, 1) end
    local ok, U = pcall(function() return reqscript('ai-util') end)
    if ok then return U.site_put(PET_BOOK_KEY, b) end
    return false
end

local function find_unit(id)
    local ok, u = pcall(function() return df.unit.find(id) end)
    return ok and u or nil
end

local function find_zone(id)
    local ok, z = pcall(function() return df.building.find(id) end)
    return ok and z or nil
end

-- a booked pet: 'gone' (dead or no more), 'ready' (it and its owner home,
-- held nowhere, the zone still there) or 'away'
local function book_state(e)
    local u = find_unit(e.pet_id)
    if not u or not alive(u) then return 'gone' end
    local z = find_zone(e.zone_id)
    if not z then return 'gone' end
    if held_of(u) then return 'gone' end           -- held again (by the player or DF): not ours to move
    if not on_map(u) then return 'away' end
    local o = e.owner_id and find_unit(e.owner_id)
    if o and not on_map(o) then return 'away' end
    return 'ready'
end

function pets_report(squads)
    local owners, squad_of = {}, {}
    for _, s in ipairs(squads or {}) do
        for _, uid in ipairs(s.units or {}) do owners[uid] = true; squad_of[uid] = s.id end
    end
    local out = {held = {}, book = {}}
    for owner, list in pairs(held_pets(owners)) do
        for _, p in ipairs(list) do
            if #out.held < PETS_MAX then
                p.unit_id, p.squad_id = int(owner), squad_of[owner]
                table.insert(out.held, p)
            end
        end
    end
    table.sort(out.held, function(a, b) return a.pet_id < b.pet_id end)
    for _, e in ipairs(book()) do
        table.insert(out.book, {pet_id = int(e.pet_id), zone_id = int(e.zone_id), owner_id = int(e.owner_id),
                                tick = int(e.tick), state = book_state(e)})
    end
    return out
end

-- the zone link undone both ways (the zone's list, the unit's ref)
local function unassign(u, z)
    pcall(function()
        local v = z.assigned_units
        for i = #v - 1, 0, -1 do if v[i] == u.id then v:erase(i) end end
    end)
    pcall(function()
        local refs = u.general_refs
        for i = #refs - 1, 0, -1 do
            local r = refs[i]
            local okt, t = pcall(function() return r:getType() end)
            if okt and t == df.general_ref_type.BUILDING_CIVZONE_ASSIGNED and r.building_id == z.id then
                refs:erase(i)
                pcall(function() r:delete() end)
            end
        end
    end)
end

local function assign(u, z)
    local ok = pcall(function() require('utils').insert_sorted(z.assigned_units, u.id) end)
    if not ok then z.assigned_units:insert('#', u.id) end
    local ref = df.general_ref_building_civzone_assignedst:new()
    ref.building_id = z.id
    u.general_refs:insert('#', ref)
end

-- Pets let out of the AI's own zone for a mission (ids: pet unit ids)
function release_pets(ids, dry_run)
    local b = book()
    local done, refused = {}, {}
    for _, id in ipairs(ids or {}) do
        local u = find_unit(id)
        local held, z = nil, nil
        if u then held, z = held_of(u) end
        local owner = nil
        if u then pcall(function() owner = u.relationship_ids.PetOwner end) end
        if not u then
            table.insert(refused, {pet_id = id, why = 'no such unit'})
        elseif not held then
            table.insert(refused, {pet_id = id, why = 'held nowhere'})
        elseif not z or not ai_zone(z) then
            table.insert(refused, {pet_id = id, why = held == 'cage' and 'in a cage' or held == 'chain' and 'chained'
                                   or "in the player's zone"})
        else
            if not dry_run then
                unassign(u, z)
                table.insert(b, {pet_id = int(id), zone_id = int(z.id), owner_id = int(owner), tick = abs_tick()})
            end
            table.insert(done, {pet_id = int(id), zone_id = int(z.id), pet = race_word(u)})
        end
    end
    if #done == 0 then
        return {ok = false, rejected = true, error = 'no pet could be let out', refused = refused}
    end
    if not dry_run then save_book(b) end
    return {ok = true, released = done, refused = #refused > 0 and refused or nil, dry_run = dry_run or nil}
end

-- The booked pets put back where they were, once home
function restore_pets(dry_run)
    local keep, restored, dropped = {}, 0, 0
    for _, e in ipairs(book()) do
        local st = book_state(e)
        if st == 'ready' then
            if not dry_run then
                local okr = pcall(assign, find_unit(e.pet_id), find_zone(e.zone_id))
                if not okr then table.insert(keep, e) end
            end
            restored = restored + 1
        elseif st == 'gone' then
            dropped = dropped + 1
        else
            table.insert(keep, e)
        end
    end
    if restored == 0 and dropped == 0 then
        return {ok = false, rejected = true, error = 'no booked pet is home yet', kept = #keep}
    end
    if not dry_run then save_book(keep) end
    return {ok = true, restored = restored, dropped = dropped, kept = #keep, dry_run = dry_run or nil}
end
