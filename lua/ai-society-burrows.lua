-- The burrows that hold dwarves for a while (13c: split out of
-- lua/ai-society.lua, which keeps every name here reachable as
-- reqscript('ai-society').<name>): the recreation burrow (the low-mood off
-- work, where the friends, the drink and the gods are), the hospital burrow
-- (the wounded kept by their beds, with water and food), and the calm-down
-- burrows (a dwarf in a tantrum in a quiet room with a drink). Each keeps its
-- members in the save.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end
local function report_units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end
local S = reqscript('ai-society')   -- find_burrow, new_burrow
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-burrows'] = '0.105.40'   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local d = U.site_get(RECREATION_KEY, {members = {}})
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}      -- let out (id -> when): not back for `days`
    return d
end

-- (0.105.33, L6) the members' checks, at every tick and every report: out
-- when thirsty or hungry (the burrow need not hold drink), in a tantrum, in
-- need of care (the burrow never covers a hospital), gone, drafted, a noble,
-- recovered, or in too long. And when no tick came for REC_STALE_DAYS (the
-- brain stopped asking: a siege, the fort shrunk, a section unreadable),
-- everyone out.
REC_THIRST = 25000           -- DFHack's "thirsty"
REC_HUNGER = 50000           -- DF's "hungry"
REC_STALE_DAYS = 9           -- the rule's cooldown (7 days) and two more

local function rec_tantrum(u)
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    return okm and (m == 'Tantrum' or m == 'Enraged') or false
end

local function rec_sick(u)
    local okh, sick = pcall(function() return u.health and u.health.flags.needs_healthcare end)
    return okh and sick and true or false
end

local function rec_dry(u)
    local ok, yes = pcall(function()
        return u.counters2.thirst_timer >= REC_THIRST or u.counters2.hunger_timer >= REC_HUNGER
    end)
    return ok and yes == true
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
-- (0.105.33, L6) Drink in the burrow: 'drink' when (not forbidden) drink
-- lies on one of its tiles; else the 3x3 of the working well nearest the
-- burrow's zones (`cx`: their centres) added, 'well'; else nil (nobody is
-- then kept in it). REC_DRINK_SCAN drinks looked at at most.
REC_DRINK_SCAN = 4000
local function rec_water(burrow, cx)
    local found = false
    pcall(function()
        local seen = 0
        for _, it in ipairs(df.global.world.items.other.DRINK) do
            seen = seen + 1
            if seen > REC_DRINK_SCAN then break end
            local ok, yes = pcall(function()
                if it.flags.forbid or it.flags.garbage_collect then return false end
                -- (0.105.33 fix) DF sets in_inventory on drink in a barrel
                -- too: only drink a unit carries is skipped, and drink in a
                -- forbidden or carried barrel
                if it.flags.in_inventory then
                    local okh, u = pcall(dfhack.items.getHolderUnit, it)
                    if okh and u ~= nil then return false end
                end
                local okc, c = pcall(dfhack.items.getContainer, it)
                if okc and c then
                    if c.flags.forbid then return false end
                    local okh, u = pcall(dfhack.items.getHolderUnit, c)
                    if c.flags.in_inventory and okh and u ~= nil then return false end
                end
                local x, y, z = dfhack.items.getPosition(it)
                if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
                if not x or x < 0 then return false end
                return dfhack.burrows.isAssignedTile(burrow, xyz2pos(x, y, z))
            end)
            if ok and yes then found = true; break end
        end
    end)
    if found then return 'drink' end
    local best, bd
    pcall(function()
        for _, w in ipairs(df.global.world.buildings.other.WELL) do
            local okw, good = pcall(well_gives_water, w)
            if okw and good then
                local x, y = w.centerx or w.x1, w.centery or w.y1
                local dd = 0
                if cx and cx.n > 0 then
                    dd = math.abs(x - cx.x / cx.n) + math.abs(y - cx.y / cx.n) + 3 * math.abs(w.z - cx.z / cx.n)
                end
                if not bd or dd < bd then best, bd = w, dd end
            end
        end
    end)
    if not best then return nil end
    local x, y = best.centerx or best.x1, best.centery or best.y1
    for dy = -1, 1 do
        for dx = -1, 1 do pcall(dfhack.burrows.setAssignedTile, burrow, xyz2pos(x + dx, y + dy, best.z), true) end
    end
    return 'well'
end

function fill_recreation(burrow)
    dfhack.burrows.clearTiles(burrow)
    local n, loc_zone, hosp_zone = 0, {}, {}
    local cx = {x = 0, y = 0, z = 0, n = 0}
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
                cx.x, cx.y, cx.z, cx.n = cx.x + (b.x1 + b.x2) / 2, cx.y + (b.y1 + b.y2) / 2, cx.z + b.z, cx.n + 1
            end
        elseif t == df.building_type.Stockpile then
            local okf, food = pcall(function() return b.settings.flags.food end)
            if okf and food then n = n + zone_tiles(b, burrow) end
        end
    end
    return n, rec_water(burrow, cx)
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
    if rec_tantrum(u) then return false end
    if rec_dry(u) then return false end              -- (0.105.33) drink and eat first
    return not rec_sick(u)
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
    -- (0.104.139) never one in a tantrum or a rage: they start the fights (rec_base)
    if not rec_base(u) then return false end
    local okc, cat = pcall(dfhack.units.getStressCategory, u)
    return okc and type(cat) == 'number' and cat <= 1
end

-- Is member `id` (in since `since`) kept? false and why when not.
local function rec_keep(d, id, since, now, days, friend_days)
    local u = df.unit.find(tonumber(id))
    if not (u and dfhack.units.isCitizen(u) and u.military.squad_id == -1) then return false, 'gone or drafted', u end
    if rec_noble(u) then return false, 'a noble', u end      -- (0.104.168) a noble since moved in: out
    if rec_dry(u) then return false, 'thirsty or hungry', u end
    if rec_tantrum(u) then return false, 'a tantrum', u end
    if rec_sick(u) then return false, 'needs care', u end
    since = tonumber(since) or now
    if d.friends and d.friends[id] then
        -- (0.104.80) in for friends: out after `friend_days`, or once the need is met
        if now - since >= friend_days * 1200 or not badly_wants_friends(u) then return false, 'time', u end
        return true, nil, u
    end
    local okc, cat = pcall(dfhack.units.getStressCategory, u)
    if (okc and type(cat) == 'number' and cat >= 3) or now - since >= days * 1200 then return false, 'time', u end
    return true, nil, u
end

local function rec_let_out(d, b, id, u, now, dry_run, txt, released)
    if not dry_run and u and b then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
    d.members[id] = nil
    if d.friends then d.friends[id] = nil end
    d.out[id] = now
    table.insert(released, u and (txt or tostring)(dfhack.units.getReadableName(u)) or id)
end

-- Who is in the burrow now, for the report. (0.105.33, L6) Also the
-- bridge's own guard, at every report, as the hospital burrow's: each member
-- checked (rec_keep) and let out here, and everyone when no tick came for
-- REC_STALE_DAYS or the burrow has no drink nor well.
function recreation_status(txt)
    local d = rec_state()
    local out = {members = 0, burrow = nil}
    local b = S.find_burrow(RECREATION_NAME)
    if b then out.burrow = b.id end
    if next(d.members) ~= nil then
        local now = U.abs_tick()
        local released = {}
        -- (0.105.36, D5) a save from before 0.105.33 has no `ticked`: its
        -- clock starts now, the stale guard skipped this once (`filled` can
        -- be two weeks old with the ticks running)
        local last = tonumber(d.ticked)
        if not last then d.ticked = now; U.site_put(RECREATION_KEY, d) end
        local why_all
        if not b then why_all = 'the burrow is gone'
        elseif last and now - last >= REC_STALE_DAYS * 1200 then why_all = 'no tick for ' .. REC_STALE_DAYS .. ' days'
        elseif d.water == false then why_all = 'no drink nor well in the burrow' end
        local days, fdays = tonumber(d.days) or 28, tonumber(d.friend_days) or 7
        for id, since in pairs(d.members) do
            local keep, _, u = rec_keep(d, id, since, now, days, fdays)
            if why_all or not keep then
                if not u then u = df.unit.find(tonumber(id)) end
                rec_let_out(d, b, id, u, now, false, txt, released)
            end
        end
        if #released > 0 then
            U.site_put(RECREATION_KEY, d)
            out.released_now = released
            out.why = why_all
        end
    end
    for _ in pairs(d.members) do out.members = out.members + 1 end
    for _ in pairs(d.friends or {}) do out.for_friends = (out.for_friends or 0) + 1 end   -- (0.104.80)
    if d.water ~= nil then out.water = d.water end
    return out
end

-- `release` (0.105.33): the brain's word that the burrow is to be emptied
-- (a threat, the fort shrunk, the status unreadable): everyone out, nobody in.
function recreation_tick(max, days, dry_run, txt, friends, friend_days, release)
    max, days = max or 8, days or 28
    friends, friend_days = friends or 0, friend_days or 7
    local d = rec_state()
    d.friends = d.friends or {}
    local now = U.abs_tick()
    local b = S.find_burrow(RECREATION_NAME)
    if release then
        local released = {}
        for id in pairs(d.members) do rec_let_out(d, b, id, df.unit.find(tonumber(id)), now, dry_run, txt, released) end
        if not dry_run then d.ticked = now; U.site_put(RECREATION_KEY, d) end
        return {ok = true, released = released, members = 0, release = true, dry_run = dry_run or nil,
                unchanged = #released == 0 or nil}
    end
    if not b and dry_run then
        return {ok = true, dry_run = true, note = 'the burrow would be made'}
    end
    local made = false
    if not b then b = S.new_burrow(RECREATION_NAME); made = true end
    local tiles
    -- (0.105.36, D5) a dry burrow is looked at again each day: drink brought
    -- in is seen then, not at the weekly refill
    if made or not d.filled or now - d.filled >= 7 * 1200
            or (d.water == false and now - d.filled >= 1200) then
        if not dry_run then
            local water
            tiles, water = fill_recreation(b)
            d.filled, d.water = now, water ~= nil and water or false
        end
    end
    if not dry_run then d.ticked, d.days, d.friend_days = now, days, friend_days end
    local released, added = {}, {}
    -- back to work: recovered, gone, drafted, thirsty, raging, sick, or in long enough
    local dry_burrow = d.water == false
    for id, since in pairs(d.members) do
        local keep, _, u = rec_keep(d, id, since, now, days, friend_days)
        if dry_burrow or not keep then
            if not u then u = df.unit.find(tonumber(id)) end
            rec_let_out(d, b, id, u, now, dry_run, txt, released)
        end
    end
    if dry_burrow then
        -- (0.105.33) no drink nor well inside: nobody kept, nobody moved in
        -- (0.105.36, D5) waiting, not a refusal: no backoff on the shared
        -- refusal key, the burrow looked at again the next day
        if not dry_run then U.site_put(RECREATION_KEY, d) end
        return {ok = true, waiting = true, unchanged = not (#released > 0 or tiles ~= nil) or nil,
                note = 'the recreation burrow holds no drink and no well giving water: nobody is kept in it '
                       .. '(looked at again each day)',
                burrow_id = b.id, tiles = tiles, released = released, members = 0, dry_run = dry_run or nil}
    end
    local count, fcount = 0, 0
    for id in pairs(d.members) do
        if d.friends[id] then fcount = fcount + 1 else count = count + 1 end
    end
    -- the most stressed eligible first
    local cands = {}
    for _, u in ipairs(report_citizens(true)) do
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
        for _, u in ipairs(report_citizens(true)) do
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
    if not dry_run then U.site_put(RECREATION_KEY, d) end
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
    local d = U.site_get(HOSPITAL_BURROW_KEY, {members = {}})
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}
    return d
end

local function hb_save(d)
    U.site_put(HOSPITAL_BURROW_KEY, d)
end

local function hb_now()
    return U.abs_tick()
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
    local b = S.find_burrow(HOSPITAL_BURROW_NAME)
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
    if ok and yes then return true end
    return in_quarantine(u)
end

-- (0.105.41, item 11) a citizen the AI quarantined for carrying a contact
-- syndrome (lua/ai-syndromes.lua quarantine) is kept in the hospital burrow
-- as a patient is, with every guard of the burrow's own
function in_quarantine(u)
    local okm, Q = pcall(reqscript, 'ai-syndromes')
    if not okm or type(Q) ~= 'table' or not Q.quarantined then return false end
    local ok, yes = pcall(Q.quarantined, u.id)
    return ok and yes == true
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

-- (0.105.33, L6) The report's sources, cached: hospital_sources reads every
-- food pile's contents and walks from each hospital zone to each pile. Kept
-- HB_SRC_TTL ticks for the same zones, the chosen piles and well re-checked
-- at each report (still holding drink and food, the well still giving water).
HB_SRC_TTL = 600             -- half a day
-- (0.105.33 fix) the cache keeps the buildings' ids, never the objects: a
-- pile or well the player removed meanwhile is freed by DF (reading it, a
-- use-after-free no pcall catches). Each is found again by id at the next
-- report; one gone, the sources are worked out afresh. Cleared when the map
-- unloads (a reload within half a day keeps the same zone ids).
local HB_SRC = nil           -- {key, at, ids = {drink, food, well}, dist}
local function hb_find(id)
    if id == nil then return nil end
    local ok, b = pcall(function() return df.building.find(id) end)
    if ok and b then return b end
    local okl, found = pcall(function()
        for _, x in ipairs(df.global.world.buildings.all) do
            if x.id == id then return x end
        end
    end)
    return okl and found or nil
end
local function hb_src_key(zones)
    local parts = {}
    for _, z in ipairs(zones) do table.insert(parts, tostring(z.id)) end
    return table.concat(parts, ',')
end
-- (0.105.36, D5) only sources that found drink or a well are kept: a cached
-- "no drink" (nothing in it to re-check) let out, within half a day, the
-- patients the tick had just moved in on drink brought back
local function hb_src_store(key, now, src)
    if not (src.drink or src.well) then HB_SRC = nil; return end
    local ids = {}
    for _, k in ipairs({'drink', 'food', 'well'}) do
        if src[k] then ids[k] = src[k].id end
    end
    HB_SRC = {key = key, at = now, ids = ids, dist = src.dist}
end
local function hospital_sources_cached(zones, now)
    local key = hb_src_key(zones)
    local c = HB_SRC
    if c and c.key == key and now >= c.at and now - c.at < HB_SRC_TTL then
        local src, good = {dist = c.dist}, true
        for _, k in ipairs({'drink', 'food', 'well'}) do
            if c.ids[k] ~= nil then
                src[k] = hb_find(c.ids[k])
                if not src[k] then good = false end
            end
        end
        if good and src.drink then
            local okd, dr = pcall(pile_holds, src.drink)
            if not (okd and dr) then good = false end
        end
        if good and src.food and src.food ~= src.drink then
            local okf, _, fo = pcall(pile_holds, src.food)
            if not (okf and fo) then good = false end
        end
        if good and src.well then
            local okw, w = pcall(well_gives_water, src.well)
            if not (okw and w) then good = false end
        end
        if good then return src end
    end
    local src = hospital_sources(zones)
    hb_src_store(key, now, src)
    return src
end
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-society-burrows-hb'] = function(sc)
        if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then HB_SRC = nil end
    end
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
    local rec_b = S.find_burrow(RECREATION_NAME)
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
        local src = #zones > 0 and hospital_sources_cached(zones, now) or {dist = {}}
        local _
        _, tiles = hb_maintain(d, b, zones, staff, src, now, false, name, released)
    end
    local after = 0
    for _ in pairs(d.members) do after = after + 1 end
    if #released > 0 or tiles or after ~= before or had_id ~= d.burrow_id then hb_save(d) end
    local rec_b = S.find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    local out = {burrow = b and b.id or nil, members = after, tiles = d.tiles, hospital_zones = #zones,
                 drink = d.drink, food = d.food, why = d.why, outside = 0, patients = 0,
                 released_now = #released > 0 and released or nil}
    for _, u in ipairs(report_citizens(true)) do
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
    -- (0.105.36, D5) the report's cache takes the tick's fresh sources, so
    -- the two agree on the drink and on the tiles' signature
    if #zones > 0 then hb_src_store(hb_src_key(zones), now, src) end
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
        b = S.new_burrow(HOSPITAL_BURROW_NAME)
        d.burrow_id, d.members = b.id, {}
        tiles = fill_hospital_burrow(b, zones, src)
        d.filled, d.sig, d.tiles = now, hb_sig(zones, src), tiles
        hb_save(d)
    end
    local count = 0
    for _ in pairs(d.members) do count = count + 1 end
    -- the patients walking outside the hospitals first; with no food in
    -- reach only those lying in a hospital bed (the doctors feed them)
    local rec_b = S.find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    local cands = {}
    for _, u in ipairs(report_citizens(true)) do
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
                U.site_put(RECREATION_KEY, rec)
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
    local d = U.site_get(CALM_KEY, {members = {}})
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}
    d.stats = type(d.stats) == 'table' and d.stats or {}
    return d
end

local function calm_save(d) U.site_put(CALM_KEY, d) end

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
    local rec_b = S.find_burrow(RECREATION_NAME)
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
-- (0.105.33, L6) For a pile, drink on one of the calm burrow's own tiles: a
-- busy pile gives the burrow only its 2 nearest drink tiles, and those
-- barrels emptied or moved left the member with no drink inside.
CALM_DRINK_CHECK = 400       -- a pile's drink tiles looked at, at most
local function drink_still(m)
    local b = building_by_id(m.src)
    if not b then return false end
    if m.kind == 'well' then return well_gives_water(b) end
    local cb = burrow_by_id(m.burrow)
    if not cb then return (pile_holds(b)) end
    local pos = xyz2pos(b.x1 or 0, b.y1 or 0, b.z or 0)
    local list = pile_drink_tiles(b, pos, CALM_DRINK_CHECK)
    if #list == 0 then return (pile_holds(b)) end      -- (no drink's place readable: the pile as before)
    for _, p in ipairs(list) do
        local ok, yes = pcall(dfhack.burrows.isAssignedTile, cb, p)
        if not ok then return (pile_holds(b)) end      -- (no tile test: the pile as before)
        if yes then return true end
    end
    return false
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
    for _, u in ipairs(report_citizens(true)) do
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
    for _, u in ipairs(report_citizens(true)) do
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
                    local x = S.find_burrow(nm)
                    if x and not used[x.id] then b = x break end
                    if not x then b = S.new_burrow(nm) break end
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
                    U.site_put(RECREATION_KEY, rec)
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
