-- (0.104.168) The citizens' homes: who sleeps where, and a bedroom for each
-- household.
--
-- What the game does (DF wiki, Bedroom and Spouse; DFHack Buildings.cpp
-- setOwner): a dwarf with no bedroom claims an unowned one by sleeping in
-- it; married couples share one bedroom and one bed ("any bedroom claimed by
-- or assigned to one spouse will automatically be assigned to both": the
-- zone keeps one owner, assigned_unit_id, and DFHack's setOwner puts it in
-- the spouse's owned_buildings too); babies sleep in their mother's room.
-- Where children sleep the wiki doesn't say: here a child counts as housed
-- with a bedroom of their own or one of a parent's (an assumption).
--
-- census(): the households, read once a game day (the report's `homes`
-- section): adults and children with and without a bedroom, couples in one
-- room, in two (each spouse kept the one they had before the wedding) or in
-- none, free bedrooms, and the citizens who slept rough lately (the game's
-- SleptGrass / SleptFloor ... and LackBedroom thoughts) with or without a
-- room of their own.
--
-- house(n_house, n_upgrade): the AI's hand (the house_dwarves action):
--   * a couple in two rooms keeps the better one (for both of them) and
--     frees the other; a single dwarf owning two or more keeps the best;
--   * a dwarf or couple with no bedroom gets the best free one they can walk
--     to (a child too, when neither parent has one);
--   * (n_upgrade) the most stressed move to a free room much better FOR
--     THEM: an item's value counts once more for each of its owner's likes
--     it matches, its material and its kind (DF wiki, Preference: "Each
--     match multiplies the item's total value for that dwarf"), so a bed of
--     the wood a dwarf likes makes a better room for that dwarf.
-- A room's value here is its furniture's (the items' value, by the likes of
-- whoever sleeps there); the walls' smoothing and engraving aren't read (the
-- rooms of one level share them). Rooms with a statue are a noble suite's
-- bedroom (lua/ai-layouts.lua suites): never given or taken here.
--@module = true

ROUGH_THOUGHTS = {SleptFloor = true, SleptMud = true, SleptGrass = true, SleptRoughFloor = true,
                  SleptRocks = true, SleptIce = true, SleptDirt = true, SleptDriftwood = true}
ROUGH_DAYS = 28
UPGRADE_RATIO = 1.5      -- a move only for a room this much better for them...
UPGRADE_MIN_GAIN = 20    -- ...and by at least this much value
SAMPLES = 6

local function zone_kind(b)
    local ok, k = pcall(function() return df.civzone_type[b.type] end)
    return ok and k or nil
end

local function is_bedroom(b)
    local ok, r = pcall(function()
        return b:getType() == df.building_type.Civzone and zone_kind(b) == 'Bedroom'
    end)
    return ok and r or false
end

local function rel(u, key)
    local ok, v = pcall(function() return u.relationship_ids[key] end)
    v = ok and tonumber(v) or -1
    return v >= 0 and v or nil
end

local function bedroom_zones()
    local ok, list = pcall(function() return df.global.world.buildings.other.ZONE_BEDROOM end)
    if ok and list then return list end
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if is_bedroom(b) then table.insert(out, b) end
    end
    return out
end

-- {bed = bool, statue = bool, bed_pos, items = {{v, mt, mi, it, st}}} of a
-- bedroom zone's furniture (with `items`, the values too: the action only)
local function furnish(z, items)
    local r = {bed = false, statue = false, items = items and {} or nil}
    pcall(function()
        for _, b in ipairs(z.contained_buildings) do
            local t = b:getType()
            if t == df.building_type.Bed then
                r.bed = true
                r.bed_pos = r.bed_pos or {x = b.centerx, y = b.centery, z = b.z}
            elseif t == df.building_type.Statue then
                r.statue = true
            end
            if items then
                pcall(function()
                    for _, ci in ipairs(b.contained_items) do
                        local it = ci.item
                        table.insert(r.items, {v = math.max(0, dfhack.items.getValue(it) or 0),
                                               mt = it:getMaterial(), mi = it:getMaterialIndex(),
                                               it = it:getType(), st = it:getSubtype()})
                    end
                end)
            end
        end
    end)
    return r
end

local function stress_cat(u)
    local ok, c = pcall(dfhack.units.getStressCategory, u)
    return ok and c or 3
end

local function needs_bedroom(u)
    local ok, r = pcall(function()
        for _, np in ipairs(dfhack.units.getNoblePositions(u) or {}) do
            if (np.position.required_bedroom or 0) > 0 then return true end
        end
        return false
    end)
    return ok and r or false
end

-- The citizens by id: {u, id, child, own = {zones assigned to them},
-- shared = {bedroom zones they use: their own and a spouse's}, spouse,
-- mother, father (ids of citizens), cat (stress category)}.
local function people(units)
    local by, order = {}, {}
    for _, u in ipairs(units or dfhack.units.getCitizens()) do
        local okc, child = pcall(function() return dfhack.units.isChild(u) or dfhack.units.isBaby(u) end)
        local p = {u = u, id = u.id, child = okc and child or false, own = {}, shared = {},
                   spouse = rel(u, 'Spouse'), mother = rel(u, 'Mother'), father = rel(u, 'Father')}
        pcall(function()
            for _, b in ipairs(u.owned_buildings) do
                if is_bedroom(b) then
                    table.insert(p.shared, b)
                    if b.assigned_unit_id == u.id then table.insert(p.own, b) end
                end
            end
        end)
        by[u.id] = p
        table.insert(order, p)
    end
    for _, p in ipairs(order) do
        if p.spouse and not by[p.spouse] then p.spouse = nil end      -- dead, away or not a citizen
        if p.mother and not by[p.mother] then p.mother = nil end
        if p.father and not by[p.father] then p.father = nil end
    end
    return by, order
end

local function has(list, z)
    for _, b in ipairs(list) do if b.id == z.id then return true end end
    return false
end

-- (a couple whose room is in only one spouse's list: married after it was
-- assigned, or the list lost it)
local function unlinked(p, q)
    return (#p.own > 0 and not has(q.shared, p.own[1])) or (#q.own > 0 and not has(p.shared, q.own[1]))
end

-- (0.104.168, review) is one of the household a noble whose office asks for
-- a bedroom? Their room is never moved, freed or downgraded here.
local function noble(p)
    if p.noble == nil then p.noble = needs_bedroom(p.u) end
    return p.noble
end

local function nobles_in(by, p)
    local q = p.spouse and by[p.spouse]
    return (noble(p) and 1 or 0) + ((q and noble(q)) and 1 or 0)
end

-- (0.104.168, review) what step 1 of house() will do for this dwarf, so the
-- census counts only that: 'apart' (a couple in two rooms, at most one of
-- them a noble: the noble's kept), 'unlinked', 'hoard' (a single non-noble
-- owning two or more), or nil
local function merge_kind(by, p)
    local q = p.spouse and by[p.spouse]
    if q then
        if #p.own > 0 and #q.own > 0 then return nobles_in(by, p) < 2 and 'apart' or nil end
        return unlinked(p, q) and 'unlinked' or nil
    end
    if #p.own > 1 and not noble(p) then return 'hoard' end
    return nil
end


local function housed(by, p)
    if #p.shared > 0 then return true end
    local q = p.spouse and by[p.spouse]
    if q and #q.own > 0 then return true end      -- (the spouse's room is theirs too)
    if p.child then
        for _, k in ipairs({'mother', 'father'}) do
            local q = p[k] and by[p[k]]
            if q and #q.shared > 0 then return true end
        end
    end
    return false
end

local function rough_sleeper(u, since)
    local rough, lack = false, false
    pcall(function()
        for _, em in ipairs(u.status.current_soul.personality.emotions) do
            local okt, when = pcall(function() return em.year * 403200 + em.year_tick end)
            if not okt or when >= since then
                local name = df.unit_thought_type[em.thought]
                if ROUGH_THOUGHTS[name] then rough = true end
                if name == 'LackBedroom' then lack = true end
            end
        end
    end)
    return rough, lack
end

local function can_walk(u, pos)
    if not pos then return true end
    local ok, r = pcall(function() return dfhack.maps.canWalkBetween(u.pos, pos) end)
    return not ok or r ~= false
end

-- The report's `homes` section (cheap: each citizen's own buildings and
-- relations, the bedroom zones' contents, and the thoughts of the last 28
-- days; no item values).
function census(units, txt)
    txt = txt or tostring
    local by, order = people(units)
    local now = df.global.cur_year * 403200 + df.global.cur_year_tick
    local since = now - ROUGH_DAYS * 1200
    local c = {citizens = #order, adults = 0, children = 0, adults_roomless = 0, children_roomless = 0,
               couples = 0, couples_shared = 0, couples_apart = 0, couples_none = 0, couples_unlinked = 0, hoarders = 0,
               rough = 0, rough_housed = 0, rough_children = 0, rough_unreachable = 0, lack_room = 0,
               free_bedrooms = 0, free_suites = 0, free_bedless = 0, rooms_wanted = 0,
               rooms_reachable = 0, samples = {}}
    local function sample(line) if #c.samples < SAMPLES then table.insert(c.samples, line) end end
    local function name(p) return txt(dfhack.units.getReadableName(p.u)) end
    local roomless = {}      -- one per household with no bedroom
    for _, p in ipairs(order) do
        local home = housed(by, p)
        if p.child then
            c.children = c.children + 1
            if not home then
                c.children_roomless = c.children_roomless + 1
                -- (one with a parent here rides on the parent's room, once they have one)
                if not p.mother and not p.father then
                    c.rooms_wanted = c.rooms_wanted + 1
                    table.insert(roomless, p)
                end
            end
        else
            c.adults = c.adults + 1
            if not home then
                c.adults_roomless = c.adults_roomless + 1
                if not p.spouse then
                    c.rooms_wanted = c.rooms_wanted + 1
                    table.insert(roomless, p)
                    sample('no room: ' .. name(p))
                end
            end
        end
        local q = p.spouse and by[p.spouse]
        local mk = merge_kind(by, p)
        if q and p.id < q.id then
            c.couples = c.couples + 1
            if mk == 'apart' then
                c.couples_apart = c.couples_apart + 1
                sample('two rooms: ' .. name(p) .. ' and ' .. name(q))
            elseif #p.own > 0 and #q.own > 0 then
                c.couples_nobles = (c.couples_nobles or 0) + 1   -- two nobles: each keeps theirs
            elseif #p.shared == 0 and #q.shared == 0 then
                c.couples_none = c.couples_none + 1
                c.rooms_wanted = c.rooms_wanted + 1
                table.insert(roomless, p)
                sample('no room: ' .. name(p) .. ' and ' .. name(q))
            elseif mk == 'unlinked' then
                c.couples_unlinked = c.couples_unlinked + 1
                sample('room not shared: ' .. name(p) .. ' and ' .. name(q))
            else
                c.couples_shared = c.couples_shared + 1
            end
        elseif mk == 'hoard' then
            c.hoarders = c.hoarders + 1
        end
        local rough, lack = rough_sleeper(p.u, since)
        if lack then c.lack_room = c.lack_room + 1 end
        if rough then
            c.rough = c.rough + 1
            if p.child then c.rough_children = c.rough_children + 1 end
            if home then
                c.rough_housed = c.rough_housed + 1
                local z = p.shared[1]
                if z and not can_walk(p.u, furnish(z).bed_pos) then c.rough_unreachable = c.rough_unreachable + 1 end
            end
        end
    end
    local free_beds = {}
    for _, z in ipairs(bedroom_zones()) do
        if z.assigned_unit_id == -1 then
            local f = furnish(z)
            if not f.bed then c.free_bedless = c.free_bedless + 1
            elseif f.statue then c.free_suites = c.free_suites + 1
            else
                c.free_bedrooms = c.free_bedrooms + 1
                table.insert(free_beds, f.bed_pos)
            end
        end
    end
    -- (0.104.168, review) the roomless households that can walk to a free
    -- bedroom (the action gives only those): by walkability group, so one
    -- lookup a bed and one a household
    local groups, any_group = {}, false
    for _, pos in ipairs(free_beds) do
        local ok, g = pcall(dfhack.maps.getWalkableGroup, pos)
        if ok and g and g ~= 0 then groups[g], any_group = true, true end
    end
    for _, p in ipairs(roomless) do
        local ok, g = pcall(dfhack.maps.getWalkableGroup, p.u.pos)
        if not ok or not g then
            -- (no group to read: one path check a bed, as the action does)
            for _, pos in ipairs(free_beds) do
                if can_walk(p.u, pos) then c.rooms_reachable = c.rooms_reachable + 1 break end
            end
        elseif groups[g] then
            c.rooms_reachable = c.rooms_reachable + 1
        end
    end
    c.rooms_unreachable = #roomless - c.rooms_reachable
    return c
end

-- --- the action -------------------------------------------------------------

-- A dwarf's likes for furniture: {mat = {'mt:mi' = true}, item = {'it:st' = true, 'it:-1' = true}}.
local function likes_of(p)
    if p.likes then return p.likes end
    local l = {mat = {}, item = {}}
    pcall(function()
        for _, pr in ipairs(p.u.status.current_soul.preferences) do
            local okn, n = pcall(function() return df.unitpref_type[pr.type] end)
            if okn and n == 'LikeMaterial' then
                l.mat[pr.mattype .. ':' .. pr.matindex] = true
            elseif okn and n == 'LikeItem' then
                l.item[pr.item_type .. ':' .. pr.item_subtype] = true
            end
        end
    end)
    p.likes = l
    return l
end

-- The room's value for the dwarves in `ps` (a couple: both): each item's
-- value, once more per like of theirs it matches.
function room_value(room, ps)
    local total = 0
    for _, p in ipairs(ps) do
        local l = likes_of(p)
        for _, it in ipairs(room.items or {}) do
            local m = 1
            if l.mat[it.mt .. ':' .. it.mi] then m = m + 1 end
            if l.item[it.it .. ':' .. it.st] or l.item[it.it .. ':-1'] then m = m + 1 end
            total = total + it.v * m
        end
    end
    return total
end

local function household(by, p)
    local q = p.spouse and by[p.spouse]
    return q and {p, q} or {p}
end

-- The best free room for the household in `ps` that the first of them can
-- walk to: index into `pool`, its value.
local function best_free(pool, ps)
    local bi, bv = nil, -1
    for i, room in ipairs(pool) do
        local v = room_value(room, ps)
        if v > bv and can_walk(ps[1].u, room.bed_pos) then bi, bv = i, v end
    end
    return bi, bv
end

local function room_of(z)
    local r = furnish(z, true)
    r.z, r.id = z, z.id
    return r
end

local function set_owner(z, u)
    local ok, r = pcall(dfhack.buildings.setOwner, z, u)
    return ok and r ~= false
end

function house(n_house, n_upgrade, dry_run, txt, units)
    txt = txt or tostring
    n_house, n_upgrade = n_house or 0, n_upgrade or 0
    local by, order = people(units)
    local function name(p) return txt(dfhack.units.getReadableName(p.u)) end
    local pool = {}
    -- (0.104.169) never a room an AI calm burrow holds now (a dwarf in a
    -- tantrum kept there: lua/ai-society.lua, the calm-down burrows)
    local calm = {}
    pcall(function()
        local d = dfhack.persistent.getSiteData('ai-overseer/calm-burrow', {})
        for _, m in pairs(type(d) == 'table' and type(d.members) == 'table' and d.members or {}) do
            if type(m) == 'table' and m.room then calm[tonumber(m.room)] = true end
        end
    end)
    for _, z in ipairs(bedroom_zones()) do
        if z.assigned_unit_id == -1 and not calm[z.id] then
            local r = room_of(z)
            if r.bed and not r.statue then table.insert(pool, r) end
        end
    end
    local out = {merged = 0, freed = 0, housed = 0, upgraded = 0, lines = {}, free_before = #pool}
    local function line(s) if #out.lines < 8 then table.insert(out.lines, s) end end
    local done = 0
    local seen = {}
    -- 1. one room per household: a couple in two keeps the better (a noble's
    -- own room if one of them needs a bedroom), a single dwarf keeps the best
    for _, p in ipairs(order) do
        if done >= n_house then break end
        local q = p.spouse and by[p.spouse]
        local mk = not seen[p.id] and merge_kind(by, p) or nil
        if mk == 'apart' or mk == 'hoard' then
            seen[p.id] = true
            if q then seen[q.id] = true end
            local ps = household(by, p)
            local rooms = {}
            for _, x in ipairs(ps) do
                for _, z in ipairs(x.own) do table.insert(rooms, {r = room_of(z), owner = x}) end
            end
            local keep, kv = nil, -1
            for _, e in ipairs(rooms) do
                local v = room_value(e.r, ps) + (noble(e.owner) and 1e9 or 0)
                if v > kv then keep, kv = e, v end
            end
            local freed = 0
            for _, e in ipairs(rooms) do
                -- (0.104.168, review) not handed out again in this call: the
                -- old owner's things are still in its cabinet and chest
                if e ~= keep and (dry_run or set_owner(e.r.z, nil)) then freed = freed + 1 end
            end
            if q and not dry_run then
                -- (the room kept goes to the spouse's list again: freeing the other took it out)
                set_owner(keep.r.z, nil)
                set_owner(keep.r.z, keep.owner.u)
            end
            if freed > 0 then
                done = done + 1
                out.merged, out.freed = out.merged + 1, out.freed + freed
                line((q and (name(p) .. ' and ' .. name(q) .. ' share one room') or (name(p) .. ' keeps one room'))
                     .. (' (%d freed)'):format(freed))
            end
        elseif mk == 'unlinked' then
            -- a couple whose one room is in only one spouse's list: given
            -- again, so that setOwner puts it in both
            seen[p.id], seen[q.id] = true, true
            local owner = #p.own > 0 and p or q
            local z = owner.own[1]
            if dry_run or (set_owner(z, nil) and set_owner(z, owner.u)) then
                done = done + 1
                out.merged = out.merged + 1
                line(name(p) .. ' and ' .. name(q) .. ' share one room')
            end
        end
    end
    -- 2. a bedroom for each household with none: the most stressed first,
    -- the grown-ups before the children
    local roomless = {}
    for _, p in ipairs(order) do
        local q = p.spouse and by[p.spouse]
        if not housed(by, p) and not (q and housed(by, q)) and not (q and seen[q.id]) then
            seen[p.id] = true
            table.insert(roomless, p)
        end
    end
    table.sort(roomless, function(a, b)
        if a.child ~= b.child then return not a.child end
        local ca, cb = stress_cat(a.u), stress_cat(b.u)
        if ca ~= cb then return ca < cb end
        return a.id < b.id
    end)
    for _, p in ipairs(roomless) do
        if done >= n_house or #pool == 0 then break end
        -- (a child whose parent was just given a room sleeps there)
        local i = not housed(by, p) and best_free(pool, household(by, p)) or nil
        if i then
            local room = table.remove(pool, i)
            if dry_run or (set_owner(room.z, p.u) and room.z.assigned_unit_id == p.u.id) then
                done = done + 1
                out.housed = out.housed + 1
                local q = p.spouse and by[p.spouse]
                table.insert(p.shared, room.z)
                if q then table.insert(q.shared, room.z) end
                line((q and (name(p) .. ' and ' .. name(q)) or name(p)) .. ' get a bedroom')
            end
        end
    end
    -- 3. the most stressed to a free room much better for them
    if n_upgrade > 0 and #pool > 0 then
        local cands = {}
        for _, p in ipairs(order) do
            local cat = stress_cat(p.u)
            local q = p.spouse and by[p.spouse]
            if cat <= 2 and not p.child and #p.own == 1 and not seen[p.id] and not (q and #q.own > 0)
                    and nobles_in(by, p) == 0 then      -- (review: nor a noble spouse's room)
                table.insert(cands, {p = p, cat = cat})
            end
        end
        table.sort(cands, function(a, b) if a.cat ~= b.cat then return a.cat < b.cat end return a.p.id < b.p.id end)
        local moved = 0
        for _, c in ipairs(cands) do
            if moved >= n_upgrade or #pool == 0 then break end
            local p, ps = c.p, household(by, c.p)
            local cur = room_of(p.own[1])
            if not cur.statue then
                local have = room_value(cur, ps)
                local i, v = best_free(pool, ps)
                if i and v >= have * UPGRADE_RATIO and v - have >= UPGRADE_MIN_GAIN then
                    local room = table.remove(pool, i)
                    local ok = dry_run or (set_owner(room.z, p.u) and room.z.assigned_unit_id == p.u.id
                                           and set_owner(cur.z, nil))
                    if ok then
                        moved = moved + 1
                        out.upgraded = out.upgraded + 1      -- (the old room not given again this call)
                        line(('%s moves to a better room for them (%d -> %d)'):format(name(p), have, v))
                    end
                end
            end
        end
    end
    local n = out.merged + out.housed + out.upgraded
    out.ok = n > 0
    out.dry_run = dry_run or nil
    out.free_after = #pool
    if n == 0 then
        out.rejected = true
        out.error = 'every household has one room, and no free room is much better for the stressed'
    end
    return out
end
