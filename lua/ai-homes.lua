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
--
-- (E4, the Design track's personal rooms) citizens_taste(): the report's
-- `citizens_taste` section, each grown-up's personality, dreams and likes
-- (taste_of) summed for the fort's design language (brain/design_rules.py);
-- house(..., place): rooms chosen by their place too (an artist by their
-- craft's workshop, family near the families, rulers and warriors near the
-- great halls, nature lovers near the fields, the quiet away from the busy
-- halls, the gregarious near the tavern), no one moved out of a room they
-- like; furnish_liked(n): a piece in a dwarf's own room from the stock, in
-- a material or showing a creature they like.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

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

-- (0.105.33, L6) The zones of the fort's locations (a tavern's guest rooms,
-- a temple's): id -> true. Never a citizen's home, never counted free (the
-- calm burrows leave them out too).
local function location_zone_ids()
    local ids = {}
    pcall(function()
        for _, l in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                for _, bid in ipairs(l:getContents().building_ids) do ids[bid] = true end
            end)
        end
    end)
    return ids
end

-- (E4) the statues the AI put up in a dwarf's own bedroom (furnish_liked):
-- building id -> true. Not a noble suite's statue: such a room stays a
-- bedroom. Read at the start of each call that looks at rooms.
-- (0.105.37 fix, documented) The room measure (the census, the scorecard's
-- rooms) reads these ids from the save whatever the Design setting: a fort
-- that ran Guided and is set back to Scripts measures its rooms exactly as it
-- did at Guided (a bedroom the AI gave a liked statue stays a bedroom, never
-- a suite). Only against main's code does it differ: main had no such ids and
-- counted the statue. A save that never ran Guided has none, so Scripts there
-- is main's byte for byte.
LIKED_STATUES_KEY = 'ai-overseer/liked-statues'
local liked_statues = {}
local function load_liked_statues()
    liked_statues = {}
    local d = U.site_get(LIKED_STATUES_KEY, {})
    for _, id in ipairs(type(d.ids) == 'table' and d.ids or {}) do
        if tonumber(id) then liked_statues[tonumber(id)] = true end
    end
    return d
end

-- {bed = bool, statue = bool, bed_pos, items = {{v, mt, mi, it, st}}} of a
-- bedroom zone's furniture (with `items`, the values too: the action only)
-- (E4) and `kinds`: the building types it holds (by name)
local function furnish(z, items)
    local r = {bed = false, statue = false, items = items and {} or nil, kinds = {}}
    pcall(function()
        for _, b in ipairs(z.contained_buildings) do
            local t = b:getType()
            pcall(function() r.kinds[df.building_type[t] or t] = true end)
            if t == df.building_type.Bed then
                r.bed = true
                r.bed_pos = r.bed_pos or {x = b.centerx, y = b.centery, z = b.z}
            elseif t == df.building_type.Statue and not liked_statues[b.id] then
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
            local okt, when = pcall(function() return U.abs_tick(em.year, em.year_tick) end)
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
    load_liked_statues()
    local by, order = people(units)
    local now = U.abs_tick()
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
    local loc = location_zone_ids()
    for _, z in ipairs(bedroom_zones()) do
        if z.assigned_unit_id == -1 and not loc[z.id] then
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

-- --- (E4) the citizens' taste: personality, dreams and likes ----------------
--
-- What DF keeps (df-structures 53.17, df.soul.xml / df.personality.xml):
-- unit.status.current_soul is a unit_soul; its `preferences` (unit_preference:
-- type = unitpref_type LikeMaterial / LikeCreature / LikeItem / LikeColor /
-- LikeShape / LikePlant / LikeTree ..., with mattype+matindex, creature_id,
-- item_type+item_subtype, color_id, shape_id, plant_id) are the likes, and
-- `personality` (unit_personality) holds `values` (personality_valuest: type
-- = value_type, strength -50..50), `dreams` (personality_goalst: type =
-- goal_type, flags.accomplished) and `traits` (int16 0-100 by
-- personality_facet_type). Every read is under pcall: a field missing in
-- another DF reads as nothing.
--
-- A dwarf's leanings: nature, craft, art, martial, rule, family, social,
-- quiet, knowledge, commerce, peace; each a small score from their values
-- (DF's levels: 11-25 values it, 26-40 strongly, 41+ above all: 1, 2, 3),
-- their dream (3), their traits (a loner or a gregarious dwarf, the anxious,
-- the private, the artistic) and their likes of plants and trees. The
-- strongest of the placing leanings (2 or more) says where their room
-- should be: an artist (art, craft) by the workshop of their best craft;
-- family by the families; imposing (rule, martial) near the dining hall or
-- the barracks; nature near the farms and gathering grounds; social near the
-- tavern (else the dining or meeting hall); quiet away from all of those.

TASTE_HOLD = 2              -- a leaning this strong counts as the dwarf's own
TASTE_TRAIT_HI, TASTE_TRAIT_LO = 76, 24     -- DF's facet bands: 76+ strong, 24- strong the other way
TASTE_DREAM = 3
TASTE_TOP = 5               -- likes listed in the report, of each kind
VALUE_LEAN = {NATURE = 'nature', CRAFTSMANSHIP = 'craft', SKILL = 'craft', HARD_WORK = 'craft',
              ARTWORK = 'art', MARTIAL_PROWESS = 'martial', POWER = 'rule', LAW = 'rule',
              FAMILY = 'family', ROMANCE = 'family', FRIENDSHIP = 'social', MERRIMENT = 'social',
              TRANQUILITY = 'quiet', INTROSPECTION = 'quiet', KNOWLEDGE = 'knowledge',
              COMMERCE = 'commerce', PEACE = 'peace', HARMONY = 'peace'}
DREAM_LEAN = {START_A_FAMILY = 'family', FALL_IN_LOVE = 'family', RULE_THE_WORLD = 'rule',
              ATTAIN_RANK_IN_SOCIETY = 'rule', BECOME_A_LEGENDARY_WARRIOR = 'martial',
              CREATE_A_GREAT_WORK_OF_ART = 'art', CRAFT_A_MASTERWORK = 'craft', MASTER_A_SKILL = 'craft',
              SEE_THE_GREAT_NATURAL_SITES = 'nature', MAKE_A_GREAT_DISCOVERY = 'knowledge',
              BRING_PEACE_TO_THE_WORLD = 'peace'}
PLACE_OF = {art = 'artist', craft = 'artist', family = 'family', rule = 'imposing', martial = 'imposing',
            nature = 'nature', quiet = 'quiet', social = 'social'}
PLACE_ORDER = {'artist', 'family', 'imposing', 'nature', 'quiet', 'social'}
-- a craft skill -> the workshop list (df.global.world.buildings.other) an artist's room is near
CRAFT_SHOP = {CARPENTRY = 'WORKSHOP_CARPENTER', MASONRY = 'WORKSHOP_MASON', STONECRAFT = 'WORKSHOP_CRAFTSDWARF',
              WOODCRAFT = 'WORKSHOP_CRAFTSDWARF', BONECARVE = 'WORKSHOP_CRAFTSDWARF',
              CUTGEM = 'WORKSHOP_JEWELER', ENCRUSTGEM = 'WORKSHOP_JEWELER', FORGE_WEAPON = 'WORKSHOP_FORGE_ANY',
              FORGE_ARMOR = 'WORKSHOP_FORGE_ANY', FORGE_FURNITURE = 'WORKSHOP_FORGE_ANY',
              METALCRAFT = 'WORKSHOP_FORGE_ANY', BOWYER = 'WORKSHOP_BOWYER', MECHANICS = 'WORKSHOP_MECHANIC',
              LEATHERWORK = 'WORKSHOP_LEATHER', CLOTHESMAKING = 'WORKSHOP_CLOTHIER', WEAVING = 'WORKSHOP_LOOM',
              GLASSMAKER = 'FURNACE_GLASS_ANY', SIEGECRAFT = 'WORKSHOP_SIEGE'}
PLACE_SPAN = 40             -- tiles: a room this far (or farther) from what suits it gains nothing
PLACE_Z = 5                 -- a level up or down counts as this many tiles
PLACE_FLOOR = 20            -- a bare room in the right place is worth this much more, at most

local function enum_name(enum, v)
    local ok, n = pcall(function() return enum[v] end)
    return ok and n or nil
end

local function strength_points(s)
    return s >= 41 and 3 or (s >= 26 and 2 or 1)
end

-- The dwarf's taste (cached on p): {lean = {name = score}, values = {NAME =
-- strength}, dreams = {NAME}, mat = {'mt:mi' = {mt, mi}}, item = {'it:st' =
-- true}, creature = {id = true}, color, shape, plant = {id = true}, craft
-- (their best craft skill's name), place (artist, family, ... or nil)}
function taste_of(p)
    if p.taste then return p.taste end
    local t = {lean = {}, values = {}, dreams = {}, mat = {}, item = {}, creature = {}, color = {}, shape = {},
               plant = {}}
    local function add(k, n) if k then t.lean[k] = (t.lean[k] or 0) + n end end
    local ok, soul = pcall(function() return p.u.status.current_soul end)
    if not ok or not soul then p.taste = t return t end
    pcall(function()
        for _, v in ipairs(soul.personality.values) do
            local name, s = enum_name(df.value_type, v.type), tonumber(v.strength) or 0
            if name and s >= 11 then
                t.values[name] = s
                add(VALUE_LEAN[name], strength_points(s))
            end
        end
    end)
    pcall(function()
        for _, d in ipairs(soul.personality.dreams) do
            local okf, done = pcall(function() return d.flags.accomplished end)
            local name = enum_name(df.goal_type, d.type)
            if name and not (okf and done) then
                table.insert(t.dreams, name)
                add(DREAM_LEAN[name], TASTE_DREAM)
            end
        end
    end)
    pcall(function()
        local tr = soul.personality.traits
        local function facet(n)
            local okv, v = pcall(function() return tr[df.personality_facet_type[n]] end)
            return okv and tonumber(v) or 50
        end
        local g = facet('GREGARIOUSNESS')
        if g >= TASTE_TRAIT_HI then add('social', 2) elseif g <= TASTE_TRAIT_LO then add('quiet', 2) end
        if facet('ANXIETY_PROPENSITY') >= TASTE_TRAIT_HI then add('quiet', 1) end
        if facet('PRIVACY') >= TASTE_TRAIT_HI then add('quiet', 1) end
        if facet('ART_INCLINED') >= TASTE_TRAIT_HI then add('art', 1) end
    end)
    local greens = 0
    pcall(function()
        for _, pr in ipairs(soul.preferences) do
            local n = enum_name(df.unitpref_type, pr.type)
            pcall(function()
                if n == 'LikeMaterial' then t.mat[pr.mattype .. ':' .. pr.matindex] = {pr.mattype, pr.matindex}
                elseif n == 'LikeItem' then t.item[pr.item_type .. ':' .. pr.item_subtype] = true
                elseif n == 'LikeCreature' then t.creature[pr.creature_id] = true
                elseif n == 'LikeColor' then t.color[pr.color_id] = true
                elseif n == 'LikeShape' then t.shape[pr.shape_id] = true
                elseif n == 'LikePlant' or n == 'LikeTree' then
                    t.plant[pr.plant_id] = true
                    if greens < 2 then greens = greens + 1; add('nature', 1) end
                end
            end)
        end
    end)
    pcall(function()
        local best = -1
        for _, sk in ipairs(soul.skills) do
            local name = enum_name(df.job_skill, sk.id)
            local r = tonumber(sk.rating) or 0
            if name and CRAFT_SHOP[name] and r > best then t.craft, best = name, r end
        end
    end)
    -- where the room should be: the strongest placing leaning, 2 or more
    local sums = {}
    for k, v in pairs(t.lean) do
        local pk = PLACE_OF[k]
        if pk then sums[pk] = (sums[pk] or 0) + v end
    end
    local best = TASTE_HOLD - 1
    for _, pk in ipairs(PLACE_ORDER) do
        if (sums[pk] or 0) > best then t.place, best = pk, sums[pk] end
    end
    p.taste = t
    return t
end

-- --- (E4) where things are, for placement ----------------------------------

local function pos_of(b)
    local ok, r = pcall(function()
        if b.centerx and b.centerx >= 0 then return {x = b.centerx, y = b.centery, z = b.z} end
        return {x = (b.x1 + b.x2) // 2, y = (b.y1 + b.y2) // 2, z = b.z}
    end)
    return ok and r or nil
end

local function list_pos(name, out)
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other[name]) do
            local p = pos_of(b)
            if p then table.insert(out, p) end
        end
    end)
    return out
end

-- The places that suit a leaning: {shops = {LIST = {pos}}, any_shop, dining,
-- meeting, barracks, tavern, garden}. A module field: the tests swap it.
function place_targets()
    local t = {shops = {}, any_shop = {}, dining = {}, meeting = {}, barracks = {}, tavern = {}, garden = {}}
    local seen = {}
    for _, name in pairs(CRAFT_SHOP) do
        if not seen[name] then
            seen[name] = true
            t.shops[name] = list_pos(name, {})
        end
    end
    list_pos('WORKSHOP_ANY', t.any_shop)
    list_pos('ZONE_DINING_HALL', t.dining)
    list_pos('ZONE_MEETING_HALL', t.meeting)
    list_pos('ZONE_BARRACKS', t.barracks)
    list_pos('FARM_PLOT', t.garden)
    list_pos('ZONE_PLANT_GATHERING', t.garden)
    pcall(function()
        for _, l in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                if df.abstract_building_type[l:getType()] == 'INN_TAVERN' then
                    for _, bid in ipairs(l:getContents().building_ids) do
                        local b = df.building.find(bid)
                        local p = b and pos_of(b)
                        if p then table.insert(t.tavern, p) end
                    end
                end
            end)
        end
    end)
    return t
end

local function concat(...)
    local out = {}
    for _, l in ipairs({...}) do for _, x in ipairs(l or {}) do table.insert(out, x) end end
    return out
end

-- The placement context of one call: the targets, the families' rooms.
function place_ctx(by, order)
    local ok, t = pcall(place_targets)
    t = ok and type(t) == 'table' and t or {}
    t.traffic = concat(t.dining, t.meeting, t.tavern, t.barracks)
    t.imposing = concat(t.dining, t.barracks)
    t.social = (#(t.tavern or {}) > 0) and t.tavern or concat(t.dining, t.meeting)
    -- the families: the rooms of parents with a child here (else of couples)
    local fam, couples = {}, {}
    local parent = {}
    for _, p in ipairs(order) do
        if p.child then
            if p.mother then parent[p.mother] = true end
            if p.father then parent[p.father] = true end
        end
    end
    for _, p in ipairs(order) do
        local z = p.own[1]
        local f = z and furnish(z)
        if f and f.bed_pos then
            local rec = {x = f.bed_pos.x, y = f.bed_pos.y, z = f.bed_pos.z, hh = p.id, sp = p.spouse}
            if parent[p.id] or (p.spouse and parent[p.spouse]) then table.insert(fam, rec)
            elseif p.spouse then table.insert(couples, rec) end
        end
    end
    t.family = #fam > 0 and fam or couples
    return t
end

local function dist(a, b)
    return math.abs(a.x - b.x) + math.abs(a.y - b.y) + PLACE_Z * math.abs(a.z - b.z)
end

local function nearest(list, pos, skip)
    local best
    for _, q in ipairs(list or {}) do
        if not (skip and skip[q.hh]) then
            local d = dist(pos, q)
            if not best or d < best then best = d end
        end
    end
    return best
end

local PLACE_WORDS = {artist = 'by their craft\'s workshop', family = 'near the families',
                     imposing = 'near the great halls', nature = 'near the gardens and fields',
                     quiet = 'away from the busy halls', social = 'near the tavern'}

-- How well the room's place suits this dwarf: 0..1 (0 when nothing to go by)
function place_fit(p, pos, ctx)
    if not pos or not ctx then return 0 end
    local t = taste_of(p)
    local k = t.place
    if not k then return 0 end
    local d
    if k == 'artist' then
        local l = t.craft and ctx.shops and ctx.shops[CRAFT_SHOP[t.craft]]
        d = nearest((l and #l > 0) and l or ctx.any_shop, pos)
    elseif k == 'family' then
        d = nearest(ctx.family, pos, {[p.id] = true, [p.spouse or -1] = true})
    elseif k == 'imposing' then
        d = nearest(ctx.imposing, pos)
    elseif k == 'nature' then
        d = nearest(ctx.garden, pos)
    elseif k == 'social' then
        d = nearest(ctx.social, pos)
    elseif k == 'quiet' then
        d = nearest(ctx.traffic, pos)
        return d and math.min(1, d / PLACE_SPAN) or 0
    end
    return d and math.max(0, 1 - d / PLACE_SPAN) or 0
end

local function household_fit(room, ps, ctx)
    local f = 0
    for _, p in ipairs(ps) do f = f + place_fit(p, room.bed_pos, ctx) end
    return f / math.max(1, #ps)
end

-- (E4) A room's worth to the household with placement: its value raised by
-- how well its place suits them (a bare room in the right place gains
-- PLACE_FLOOR), a whole number.
function room_score(room, ps, ctx)
    local v = room_value(room, ps)
    return math.floor(v + (v + PLACE_FLOOR) * household_fit(room, ps, ctx) + 0.5)
end

-- ' (near the tavern)' when the room's place suits the first of them well
function place_words(room, ps, ctx)
    local p = ps[1]
    local k = p and taste_of(p).place
    if k and place_fit(p, room.bed_pos, ctx) >= 0.5 then return ' (' .. PLACE_WORDS[k] .. ')' end
    return ''
end

-- Does one of the household like the room they have? A good thought about
-- their bedroom in the last 28 days (BedroomQuality with a good emotion:
-- df.emotion_type's divider below 0), or an item in it of a kind or
-- material they like.
LIKED_ROOM_DAYS = 28
function likes_room(ps, room)
    local since = U.abs_tick() - LIKED_ROOM_DAYS * 1200
    for _, p in ipairs(ps) do
        local l = likes_of(p)
        for _, it in ipairs(room.items or {}) do
            if l.mat[it.mt .. ':' .. it.mi] or l.item[it.it .. ':' .. it.st] or l.item[it.it .. ':-1'] then
                return true
            end
        end
        local liked = false
        pcall(function()
            for _, em in ipairs(p.u.status.current_soul.personality.emotions) do
                local okt, when = pcall(function() return U.abs_tick(em.year, em.year_tick) end)
                if (not okt or when >= since) and df.unit_thought_type[em.thought] == 'BedroomQuality' then
                    local okd, div = pcall(function() return df.emotion_type.attrs[em.type].divider end)
                    if okd and tonumber(div) and tonumber(div) < 0 then liked = true end
                end
            end
        end)
        if liked then return true end
    end
    return false
end

-- The best free room for the household in `ps` that the first of them can
-- walk to: index into `pool`, its value.
-- (E4) with `ctx` (placement by taste), its worth to them: the value raised
-- by how well the room's place suits them (room_score)
local function best_free(pool, ps, ctx)
    local bi, bv = nil, -1
    for i, room in ipairs(pool) do
        local v = ctx and room_score(room, ps, ctx) or room_value(room, ps)
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

-- (E4) `place` (true): each room given or moved to is chosen by its worth to
-- the household AND by its place (placement by dream and personality:
-- room_score), and no one is moved out of a room they like (likes_room).
-- Without it, everything is as before.
function house(n_house, n_upgrade, dry_run, txt, units, place)
    txt = txt or tostring
    n_house, n_upgrade = n_house or 0, n_upgrade or 0
    load_liked_statues()
    local by, order = people(units)
    local function name(p) return txt(dfhack.units.getReadableName(p.u)) end
    local ctx = place and place_ctx(by, order) or nil
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
    local loc = location_zone_ids()
    for _, z in ipairs(bedroom_zones()) do
        if z.assigned_unit_id == -1 and not calm[z.id] and not loc[z.id] then
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
        local i = not housed(by, p) and best_free(pool, household(by, p), ctx) or nil
        if i then
            local room = table.remove(pool, i)
            if dry_run or (set_owner(room.z, p.u) and room.z.assigned_unit_id == p.u.id) then
                done = done + 1
                out.housed = out.housed + 1
                local q = p.spouse and by[p.spouse]
                table.insert(p.shared, room.z)
                if q then table.insert(q.shared, room.z) end
                line((q and (name(p) .. ' and ' .. name(q)) or name(p)) .. ' get a bedroom'
                     .. (ctx and place_words(room, household(by, p), ctx) or ''))
                if ctx and place_words(room, household(by, p), ctx) ~= '' then out.placed = (out.placed or 0) + 1 end
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
            -- (E4) never out of a room they like
            if not cur.statue and not (ctx and likes_room(ps, cur)) then
                local have = ctx and room_score(cur, ps, ctx) or room_value(cur, ps)
                local i, v = best_free(pool, ps, ctx)
                if i and v >= have * UPGRADE_RATIO and v - have >= UPGRADE_MIN_GAIN then
                    local room = table.remove(pool, i)
                    local ok = dry_run or (set_owner(room.z, p.u) and room.z.assigned_unit_id == p.u.id
                                           and set_owner(cur.z, nil))
                    if ok then
                        moved = moved + 1
                        out.upgraded = out.upgraded + 1      -- (the old room not given again this call)
                        line(('%s moves to a better room for them (%d -> %d)'):format(name(p), have, v)
                             .. (ctx and place_words(room, ps, ctx) or ''))
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

-- --- (E4) rooms furnished in what the dwarf likes --------------------------
--
-- furnish_liked(n): for up to n citizens whose own bedroom the AI dug (inside
-- one of its projects' outlines, the old ones too: a player's room is never
-- furnished), one piece of furniture from the fort's stock put up in it: a
-- statue whose image shows a creature or an item they like (DF's art image:
-- the statue's image elements), or one of a material they like; else a
-- cabinet, a chest, a table or a chair of a liked material or kind. Only a
-- kind the room doesn't have; only an item free for a new job (ai-util's
-- one list: never in a job, owned, forbidden, an artifact...), lying on the
-- ground, that the room's bed can be walked to from; never while a strange
-- mood gathers (the moody take what they please); a statue (it blocks the
-- way) only on a floor tile whose neighbours stay joined without it. The
-- statues it puts up are kept in the save (LIKED_STATUES_KEY), so the room
-- still counts as a bedroom, not a noble's suite.

FURNISH_KINDS = {
    {kind = 'Statue', list = 'STATUE', blocking = true},
    {kind = 'Cabinet', list = 'CABINET'},
    {kind = 'Box', list = 'BOX'},
    {kind = 'Table', list = 'TABLE'},
    {kind = 'Chair', list = 'CHAIR'},
}
FURNISH_MAX = 10
STRANGE_MOODS = {Fey = true, Secretive = true, Possessed = true, Macabre = true, Fell = true}
-- building types a dwarf can't walk through
BLOCKING = {Statue = true, Support = true, GrateWall = true, BarsVertical = true, Window = true}

-- a material's kind: stone, metal, gem, glass, wood or other
local function mat_kind(mt, mi)
    local ok, k = pcall(function()
        local info = dfhack.matinfo.decode(mt, mi)
        local f = info.material.flags
        if f.IS_GEM then return 'gem' end
        if f.IS_METAL then return 'metal' end
        if f.IS_GLASS then return 'glass' end
        if f.IS_STONE then return 'stone' end
        if f.WOOD or f.STRUCTURAL_PLANT_MAT then return 'wood' end
        return 'other'
    end)
    return ok and k or 'other'
end

-- The tile hooks (the tests swap them): ai-builder's tile reading.
function TILE(x, y, z) return reqscript('ai-builder').tile_info(x, y, z) end
function BLOCKED_AT(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, x, y, z)
    if not ok or not b then return false end
    return BLOCKING[df.building_type[b:getType()]] == true
end
function DOOR_AT(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, x, y, z)
    if not ok or not b then return false end
    local t = df.building_type[b:getType()]
    return t == 'Door' or t == 'Hatch'
end
-- The outlines of every level the AI dug (its projects' and the old ones'):
-- {{x1, y1, x2, y2, z}}. A module field: the tests swap it.
function ai_areas()
    local out = {}
    pcall(function()
        local B = reqscript('ai-builder')
        local data = B.load_projects()
        for _, p in ipairs(data.list) do
            if p.kind ~= 'way_in' then
                for _, a in ipairs(B.project_areas(p)) do table.insert(out, a) end
            end
        end
        for _, a in ipairs(type(data.old_areas) == 'table' and data.old_areas or {}) do table.insert(out, a) end
    end)
    return out
end

local function in_areas(areas, pos)
    if not pos then return false end
    for _, a in ipairs(areas) do
        if type(a) == 'table' and a.z == pos.z and tonumber(a.x1) and pos.x >= a.x1 and pos.x <= a.x2
                and pos.y >= a.y1 and pos.y <= a.y2 then
            return true
        end
    end
    return false
end

local function shape_ok(t)
    local s = t and tostring(t.shape) or ''
    return s == 'FLOOR' or s == 'RAMP' or s:find('STAIR') ~= nil
end

local function passable(x, y, z)
    local t = TILE(x, y, z)
    if not shape_ok(t) then return false end
    return not (t.building and BLOCKED_AT(x, y, z))
end

-- the eight around a tile, in turn (each next to the one before)
local RING = {{0, -1}, {1, -1}, {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}}
local ORTHO4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

-- Would a building that blocks the way on (x, y) leave its walkable
-- neighbours joined? (Counted round the ring through orthogonal steps only:
-- stricter than DF, which also steps diagonally.)
function keeps_way(x, y, z)
    local open = {}
    for i, d in ipairs(RING) do open[i] = passable(x + d[1], y + d[2], z) end
    local runs, any = 0, false
    for i = 1, 8 do
        if open[i] then
            any = true
            if not open[(i - 2) % 8 + 1] then runs = runs + 1 end
        end
    end
    if any and runs == 0 then runs = 1 end      -- all eight open
    return any and runs <= 1
end

-- The free floor tiles inside a bedroom zone for one more piece: beside a
-- wall (or in the open with room all round), not in front of a door; for a
-- blocking piece, only where the way round stays (keeps_way). Beside a
-- wall first, then reading order.
function room_spots(z, blocking)
    local spots = {}
    pcall(function()
        for y = z.y1, z.y2 do
            for x = z.x1, z.x2 do
                local okc, inside = pcall(dfhack.buildings.containsTile, z, x, y)
                local t = (not okc or inside) and TILE(x, y, z.z)
                if t and tostring(t.shape) == 'FLOOR' and not t.building and not t.items and not t.liquid then
                    local walls, door, open = 0, false, 0
                    for _, d in ipairs(ORTHO4) do
                        local n = TILE(x + d[1], y + d[2], z.z)
                        if n and tostring(n.shape) == 'WALL' then walls = walls + 1
                        elseif n and n.building and DOOR_AT(x + d[1], y + d[2], z.z) then door = true
                        elseif shape_ok(n) then open = open + 1 end
                    end
                    if not door and ((walls >= 1 and open >= 1) or (walls == 0 and open >= 4))
                            and (not blocking or keeps_way(x, y, z.z)) then
                        table.insert(spots, {x = x, y = y, z = z.z, walls = walls})
                    end
                end
            end
        end
    end)
    table.sort(spots, function(a, b)
        if (a.walls == 0) ~= (b.walls == 0) then return b.walls == 0 end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    return spots
end

-- What a statue's image shows: {creatures = {race = true}, items = {'it' = true}}
local function image_of(it)
    local out = {creatures = {}, items = {}}
    pcall(function()
        local chunk = df.art_image_chunk.find(it.image.id)
        local img = chunk.images[it.image.subid].art_image
        for _, e in ipairs(img.elements) do
            local okr, race = pcall(function() return e.race end)
            if okr and tonumber(race) and race >= 0 then out.creatures[race] = true end
            local oki, ity = pcall(function() return e.item_type end)
            if oki and tonumber(ity) and ity >= 0 then out.items[tostring(ity)] = true end
        end
    end)
    return out
end

-- The free furniture in stock: {kind = {{it, mt, mi, ity, ist, pos, img}}}
function stock_furniture()
    local out = {}
    for _, k in ipairs(FURNISH_KINDS) do
        local list = {}
        pcall(function()
            for _, it in ipairs(df.global.world.items.other[k.list]) do
                local okf, free = pcall(function() return it.flags.on_ground and U.item_free(it) end)
                if okf and free then
                    local r = {it = it, mt = it:getMaterial(), mi = it:getMaterialIndex(), ity = it:getType(),
                               ist = it:getSubtype()}
                    local okp, x, y, z = pcall(dfhack.items.getPosition, it)
                    r.pos = okp and x and {x = x, y = y, z = z} or nil
                    -- (a chest, not a bag: a bag is cloth or leather)
                    local mk = k.kind == 'Box' and mat_kind(r.mt, r.mi) or nil
                    if r.pos and (k.kind ~= 'Box' or mk == 'stone' or mk == 'metal' or mk == 'wood'
                                  or mk == 'glass' or mk == 'gem') then
                        if k.kind == 'Statue' then r.img = image_of(it) end
                        table.insert(list, r)
                    end
                end
            end
        end)
        out[k.kind] = list
    end
    return out
end

-- How much the household would like the item: 3 for a statue showing a
-- creature or an item they like, 2 for a material they like, 1 for a kind
-- of item they like; 0: not at all.
local function like_score(r, ps)
    local s = 0
    for _, p in ipairs(ps) do
        local t = taste_of(p)
        local n = 0
        if r.img then
            for race in pairs(r.img.creatures) do if t.creature[race] then n = n + 3 break end end
            for ity in pairs(r.img.items) do
                if t.item[ity .. ':-1'] then n = n + 3 break end
                local hit = false
                for key in pairs(t.item) do if key:match('^' .. ity .. ':') then hit = true break end end
                if hit then n = n + 3 break end
            end
        end
        if t.mat[r.mt .. ':' .. r.mi] then n = n + 2 end
        if t.item[r.ity .. ':' .. r.ist] or t.item[r.ity .. ':-1'] then n = n + 1 end
        s = s + n
    end
    return s
end

local function strange_mood_now(order)
    for _, p in ipairs(order) do
        local ok, m = pcall(function() return df.mood_type[p.u.mood] end)
        if ok and STRANGE_MOODS[m] then return true end
    end
    return false
end

-- The plan: up to `max` {p, ps, room, z, kind, item, spot, score, why}
-- (one piece a household), most stressed first.
function furnish_plan(by, order, max)
    local plan = {}
    if strange_mood_now(order) then return plan, 'a strange mood is gathering what it wants' end
    local areas = ai_areas()
    if #areas == 0 then return plan, 'no room the AI dug' end
    local loc = location_zone_ids()
    local stock = stock_furniture()
    local any = false
    for _, l in pairs(stock) do if #l > 0 then any = true end end
    if not any then return plan, 'no free furniture in stock' end
    local cands = {}
    for _, p in ipairs(order) do
        local q = p.spouse and by[p.spouse]
        -- the room's owner, once a household (a couple's: the one whose name it's in)
        if not p.child and #p.own == 1 and not (q and #q.own > 0 and q.id < p.id) then
            table.insert(cands, {p = p, cat = stress_cat(p.u)})
        end
    end
    table.sort(cands, function(a, b) if a.cat ~= b.cat then return a.cat < b.cat end return a.p.id < b.p.id end)
    local taken = {}
    for _, c in ipairs(cands) do
        if #plan >= max then break end
        local p = c.p
        local z = p.own[1]
        local room = furnish(z)
        if room.bed_pos and not loc[z.id] and in_areas(areas, room.bed_pos) then
            local q = p.spouse and by[p.spouse]
            local ps = q and {p, q} or {p}
            local best
            for _, k in ipairs(FURNISH_KINDS) do
                if not room.kinds[k.kind] and not (k.kind == 'Statue' and room.statue) then
                    for _, r in ipairs(stock[k.kind] or {}) do
                        if not taken[r] then
                            local s = like_score(r, ps)
                            if s > 0 and (not best or s > best.score) then
                                best = {kind = k, item = r, score = s}
                            end
                        end
                    end
                end
            end
            if best and can_walk(p.u, best.item.pos) then
                local okw, walk = pcall(function() return dfhack.maps.canWalkBetween(best.item.pos, room.bed_pos) end)
                local spot = (not okw or walk ~= false) and room_spots(z, best.kind.blocking)[1] or nil
                if spot then
                    taken[best.item] = true
                    table.insert(plan, {p = p, ps = ps, z = z, kind = best.kind.kind, item = best.item, spot = spot,
                                        score = best.score})
                end
            end
        end
    end
    return plan, #plan == 0 and 'no citizen\'s room lacks a piece they would like that the stock has' or nil
end

local function liked_words(e, txt)
    local r = e.item
    local what = e.score >= 3 and (r.img and 'showing something they like' or 'they like') or
                 (e.score >= 2 and 'of a material they like' or 'of a kind they like')
    local mat = ''
    pcall(function() mat = ' of ' .. txt(dfhack.matinfo.decode(r.mt, r.mi):toString()) end)
    return ('a %s%s, %s'):format(e.kind:lower() == 'box' and 'chest' or e.kind:lower(), mat, what)
end

function furnish_liked(n, dry_run, txt, units)
    txt = txt or tostring
    n = math.max(1, math.min(FURNISH_MAX, tonumber(n) or 1))
    local store = load_liked_statues()
    local by, order = people(units)
    local plan, why = furnish_plan(by, order, n)
    local out = {placed = 0, lines = {}, dry_run = dry_run or nil}
    local function name(p) return txt(dfhack.units.getReadableName(p.u)) end
    local new_statues = {}
    for _, e in ipairs(plan) do
        local ok = dry_run
        if not dry_run then
            local pos = xyz2pos and xyz2pos(e.spot.x, e.spot.y, e.spot.z) or {x = e.spot.x, y = e.spot.y, z = e.spot.z}
            local okc, b = pcall(dfhack.buildings.constructBuilding,
                                 {type = df.building_type[e.kind], pos = pos, items = {e.item.it}})
            ok = okc and b ~= nil
            if ok and e.kind == 'Statue' then table.insert(new_statues, b.id) end
        end
        if ok then
            out.placed = out.placed + 1
            if #out.lines < 8 then
                table.insert(out.lines, name(e.p) .. "'s room: " .. liked_words(e, txt))
            end
        end
    end
    if #new_statues > 0 then
        local ids = type(store.ids) == 'table' and store.ids or {}
        for _, id in ipairs(new_statues) do table.insert(ids, id) end
        while #ids > 400 do table.remove(ids, 1) end
        U.site_put(LIKED_STATUES_KEY, {ids = ids})
    end
    out.ok = out.placed > 0
    if not out.ok then
        out.rejected = true
        out.error = why or 'the game took none of the pieces'
    end
    return out
end

-- --- (E4) the report's citizens_taste section -------------------------------

-- (for the tests and a look in the console) each citizen's taste by id:
-- {id = {place, craft, lean, dreams}}
function citizen_tastes(units)
    local _, order = people(units)
    local out = {}
    for _, p in ipairs(order) do
        local t = taste_of(p)
        out[p.id] = {place = t.place, craft = t.craft, lean = t.lean, dreams = t.dreams, plant = t.plant}
    end
    return out
end

local function top(counts, n, describe)
    local list = {}
    for k, c in pairs(counts) do table.insert(list, {k = k, n = c}) end
    table.sort(list, function(a, b) if a.n ~= b.n then return a.n > b.n end return tostring(a.k) < tostring(b.k) end)
    local out = {}
    for i = 1, math.min(n, #list) do
        local e = describe(list[i].k)
        e.n = list[i].n
        table.insert(out, e)
    end
    return out
end

-- The citizens' taste, summed over the grown-ups (once in 3 days: each
-- citizen's soul and the free furniture read): how many hold each leaning,
-- where their rooms would go, their values and dreams, the most liked
-- materials, creatures, items, colours, shapes and plants (token, name, n),
-- and how many rooms furnish_liked could furnish now.
function citizens_taste(units, txt)
    txt = txt or tostring
    load_liked_statues()
    local by, order = people(units)
    local out = {citizens = #order, adults = 0, leanings = {}, place = {}, values = {}, dreams = {}}
    local mats, creatures, items, colors, shapes, plants = {}, {}, {}, {}, {}, {}
    local matkey = {}
    local function bump(t, k) t[k] = (t[k] or 0) + 1 end
    for _, p in ipairs(order) do
        if not p.child then
            out.adults = out.adults + 1
            local t = taste_of(p)
            for k, v in pairs(t.lean) do if v >= TASTE_HOLD then bump(out.leanings, k) end end
            if t.place then bump(out.place, t.place) end
            for k in pairs(t.values) do bump(out.values, k) end
            for _, d in ipairs(t.dreams) do bump(out.dreams, d) end
            for k, m in pairs(t.mat) do bump(mats, k); matkey[k] = m end
            for k in pairs(t.creature) do bump(creatures, k) end
            for k in pairs(t.item) do bump(items, k) end
            for k in pairs(t.color) do bump(colors, k) end
            for k in pairs(t.shape) do bump(shapes, k) end
            for k in pairs(t.plant) do bump(plants, k) end
        end
    end
    -- (creature_raw: creature_id and name[0]; colours, shapes, plants: id and name)
    local function raw_name(kind, id)
        local e = {}
        pcall(function()
            if kind == 'creature' then
                local r = df.creature_raw.find(id)
                e.token = tostring(r.creature_id)
                e.name = txt(r.name[0])
            else
                local r = df[kind].find(id)
                e.token = tostring(r.id)
                e.name = txt(r.name)
            end
        end)
        e.token = e.token or tostring(id)
        return e
    end
    out.likes = {
        materials = top(mats, TASTE_TOP, function(k)
            local m = matkey[k]
            local e = {kind = mat_kind(m[1], m[2])}
            pcall(function()
                local info = dfhack.matinfo.decode(m[1], m[2])
                e.token = info:getToken()
                e.name = txt(info:toString())
            end)
            e.token = e.token or k
            return e
        end),
        creatures = top(creatures, TASTE_TOP, function(k) return raw_name('creature', k) end),
        items = top(items, TASTE_TOP, function(k)
            local it = tonumber(k:match('^(-?%d+)'))
            return {token = tostring(enum_name(df.item_type, it) or k)}
        end),
        colors = top(colors, 3, function(k) return raw_name('descriptor_color', k) end),
        shapes = top(shapes, 3, function(k) return raw_name('descriptor_shape', k) end),
        plants = top(plants, 3, function(k) return raw_name('plant_raw', k) end),
    }
    -- a few dwarves and where their rooms would go (taste_of's place)
    out.samples = {}
    for _, p in ipairs(order) do
        if #out.samples >= SAMPLES then break end
        local t = p.taste
        if t and t.place then
            table.insert(out.samples, txt(dfhack.units.getReadableName(p.u)) .. ': ' .. t.place
                         .. (#t.dreams > 0 and (' (dreams: ' .. t.dreams[1]:lower():gsub('_', ' ') .. ')') or ''))
        end
    end
    local okp, plan, why = pcall(furnish_plan, by, order, FURNISH_MAX)
    out.furnish_ready = okp and #plan or 0
    if okp and #plan == 0 and why then out.furnish_why = why end
    out.strange_mood = strange_mood_now(order) or nil
    return out
end
