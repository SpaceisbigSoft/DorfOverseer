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
-- (0.105.48 r2) constructBuilding is in library/lua/dfhack/buildings.lua, added to
-- dfhack.buildings only by this require (without it, only after buildingplan loaded it)
pcall(function() require('dfhack.buildings') end)

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

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
    for _, u in ipairs(units or report_citizens()) do
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
-- owning two or more), or nil. (r9, audit A7 #24) 'hoard' only when one of
-- the rooms is in a level the AI dug (`areas`, a function giving ai_areas()
-- once): a second room the player gave (an office-bedroom) is theirs to keep
local function zone_in_ai_areas(z, areas)
    local ok, yes = pcall(function()
        local pos = {x = (z.x1 + z.x2) // 2, y = (z.y1 + z.y2) // 2, z = z.z}
        for _, a in ipairs(areas) do
            if type(a) == 'table' and a.z == pos.z and tonumber(a.x1) and pos.x >= a.x1 and pos.x <= a.x2
                    and pos.y >= a.y1 and pos.y <= a.y2 then
                return true
            end
        end
        return false
    end)
    return ok and yes or false
end

local function memo_areas()
    local got
    return function()
        if got == nil then
            local ok, a = pcall(function() return ai_areas() end)
            got = ok and type(a) == 'table' and a or {}
        end
        return got
    end
end

local function hoard_rooms(p, areas)
    local ai, other = {}, {}
    for _, z in ipairs(p.own) do
        if zone_in_ai_areas(z, areas()) then table.insert(ai, z) else table.insert(other, z) end
    end
    return ai, other
end

local function merge_kind(by, p, areas)
    local q = p.spouse and by[p.spouse]
    if q then
        if #p.own > 0 and #q.own > 0 then return nobles_in(by, p) < 2 and 'apart' or nil end
        return unlinked(p, q) and 'unlinked' or nil
    end
    if #p.own > 1 and not noble(p) then
        if not areas then return 'hoard' end
        local ai = hoard_rooms(p, areas)
        return #ai > 0 and 'hoard' or nil
    end
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
    local areas = memo_areas()          -- (r9) the AI's levels, read once if a hoarder is seen
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
        local mk = merge_kind(by, p, areas)
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
    -- (0.105.48, A7) the levels of free bedrooms no roomless household's
    -- walk group reaches (up to 5): the brain names them (cut off from the fort)
    if #roomless > 0 and any_group then
        local mine, known = {}, true
        for _, p in ipairs(roomless) do
            local ok, g = pcall(dfhack.maps.getWalkableGroup, p.u.pos)
            if ok and g then mine[g] = true else known = false end
        end
        if known then
            local zs, seen = {}, {}
            for _, pos in ipairs(free_beds) do
                local ok, g = pcall(dfhack.maps.getWalkableGroup, pos)
                if ok and g and not mine[g] and not seen[pos.z] and #zs < 5 then
                    seen[pos.z] = true
                    table.insert(zs, pos.z)
                end
            end
            if #zs > 0 then table.sort(zs); c.free_cut_z = zs end
        end
    end
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

local function enum_name(enum, v) return U.enum_value(enum, v) end   -- (r6) ai-util's

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
    local areas = memo_areas()
    -- 1. one room per household: a couple in two keeps the better (a noble's
    -- own room if one of them needs a bedroom), a single dwarf keeps the best
    for _, p in ipairs(order) do
        if done >= n_house then break end
        local q = p.spouse and by[p.spouse]
        local mk = not seen[p.id] and merge_kind(by, p, areas) or nil
        if mk == 'apart' or mk == 'hoard' then
            seen[p.id] = true
            if q then seen[q.id] = true end
            local ps = household(by, p)
            local rooms = {}
            local mine = nil
            if mk == 'hoard' then
                -- (r9, audit A7 #24) only the rooms in the AI's levels are freed;
                -- with a room of the player's, the dwarf keeps that one (and it)
                local ai, other = hoard_rooms(p, areas)
                mine = #other > 0 and other[1] or nil
                for _, z in ipairs(ai) do table.insert(rooms, {r = room_of(z), owner = p}) end
            else
                for _, x in ipairs(ps) do
                    for _, z in ipairs(x.own) do table.insert(rooms, {r = room_of(z), owner = x}) end
                end
            end
            local keep, kv = nil, -1
            for _, e in ipairs(rooms) do
                local v = room_value(e.r, ps) + (noble(e.owner) and 1e9 or 0)
                if v > kv then keep, kv = e, v end
            end
            if mine then keep = {r = room_of(mine), owner = p} end
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

-- (r9) this file's locals the later parts use (each takes back the ones it
-- uses as locals of its own): all functions and fixed values, set once here
PART_LOCALS = {U = U, location_zone_ids = location_zone_ids, load_liked_statues = load_liked_statues, furnish = furnish, stress_cat = stress_cat, people = people, can_walk = can_walk, enum_name = enum_name}

---------------------------------------------------------------------------
-- (r9) The rest of the homes lives in a part beside this file
-- (ai-homes-furnish.lua): the rooms furnished in what the dwarf likes
-- (furnish_plan, furnish_liked) and the report's citizens_taste section.
-- It runs in this module's own environment, so its names stay
-- reqscript('ai-homes').name for the bridge and the other modules, and a
-- test's swap (H.house = ...) reaches it. DFHack reloads a module when its
-- own file changes: a change to the part alone is picked up once
-- ai-homes.lua is touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'furnish'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-homes'] = '0.105.69'}   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local name = 'ai-homes-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-homes: ' .. name .. '.lua is missing (it goes beside ai-homes.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
