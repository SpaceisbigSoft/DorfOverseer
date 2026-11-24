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
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local S = reqscript('ai-society')   -- find_burrow, new_burrow
-- (r9) the hub's and its parts' version marks; started afresh at each load, so a part
-- that failed to load shows as unmarked (as ai-gates does)
PART_VERSIONS = {['ai-society-burrows'] = '0.105.107'}   -- (0.105.26) bumped with BRIDGE_VERSION

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

-- (0.105.97) a killer the killer rule holds (lua/ai-killers.lua is_held: a
-- cell, or a strong or certain suspect): never into the recreation, hospital,
-- calm-down or weather burrows, and let out of them. A dwarf in several
-- burrows may go to any (B, 23 Nov: the celled Degel and Fath Shemnish were
-- moved into the recreation burrow; Degel killed again in a hospital).
-- Shared with the parts (they run in this module's environment).
function killer_held(u)
    local ok, yes = pcall(function() return reqscript('ai-killers').is_held(u) end)
    return ok and yes == true
end

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
            -- (0.105.97) never a killer cell's own pile (ai-killers LARDER_PREFIX): the way
            -- to it leads into the killer's cell (B, 23 Nov)
            local okc, larder = pcall(function() return tostring(b.name):find('AI cell larder ', 1, true) == 1 end)
            if okf and food and not (okc and larder) then n = n + zone_tiles(b, burrow) end
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

-- (0.105.51) a dwarf in a mood (a strange mood, or one gone insane): DF lets
-- a moody dwarf claim a workshop and fetch materials only inside the burrows
-- it is assigned to (wiki, Strange mood). R3 (15 Nov): the recreation burrow
-- (taverns, halls, food piles: no workshop) took five dwarves in strange
-- moods "for friends" or the low mood; all five went insane and died of thirst
-- (A's Ber, a tanner, never claimed a workshop; E's Tobul, Avuz and Ilral, C's
-- Mestthos stalled 40 days gathering).
function in_mood(u)
    local ok, m = pcall(function() return u.mood end)
    return ok and type(m) == 'number' and m >= 0
end

local function rec_base(u)
    if not dfhack.units.isAdult(u) or u.military.squad_id ~= -1 then return false end
    if in_mood(u) then return false end              -- (0.105.51) a mood claims its workshop outside
    if rec_noble(u) then return false end
    if killer_held(u) then return false end          -- (0.105.97) a held killer, never among the others
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

-- --- (0.105.97) off-duty soldiers short of friends, drink or prayer ---------
--
-- B "Monastery", 23 Nov: 30 of 32 dwarves badly missing drink were soldiers,
-- 37 soldiers among the 76 of 88 badly wanting friends; the burrow took
-- civilians only. A soldier whose squad is off duty (and under no order) now
-- gets a few days in the burrow, where the taverns and temples are; out at
-- once when the squad goes back on duty (act_squad_routine lets the squad
-- out: recreation_release_squad), takes an order, the soldier leaves the
-- squad, the need is met, or after `soldier_days`.
REC_SOLDIER_NEEDS = {BeWithFriends = true, DrinkAlcohol = true, PrayOrMeditate = true}

-- the worst focus among those needs when one is badly unmet (else nil), and
-- whether drink or prayer is among them (the brain counts friends apart)
function soldier_leisure_want(u)
    local worst, np = nil, false
    pcall(function()
        for _, nd in ipairs(u.status.current_soul.personality.needs) do
            local name = df.need_type[nd.id]
            if REC_SOLDIER_NEEDS[name] and nd.focus_level <= -10000 then
                worst = math.min(worst or nd.focus_level, nd.focus_level)
                if name ~= 'BeWithFriends' then np = true end
            end
        end
    end)
    return worst, np
end

-- is squad `sid` off duty now (its routine named so) and under no order?
local function squad_free(sid)
    local ok, yes = pcall(function()
        local sq = df.squad.find(sid)
        if not sq or #sq.orders > 0 then return false end
        local r = df.global.plotinfo.alerts.routines[sq.cur_routine_idx]
        return r ~= nil and tostring(r.name):lower():find('off duty', 1, true) ~= nil
    end)
    return ok and yes == true
end

local function rec_soldier_base(u)
    if not dfhack.units.isAdult(u) or u.military.squad_id == -1 then return false end
    if not squad_free(u.military.squad_id) then return false end
    if killer_held(u) then return false end          -- (0.105.97, merge) a held killer, never among the others
    if in_mood(u) or rec_noble(u) or rec_tantrum(u) or rec_dry(u) then return false end
    return not rec_sick(u)
end

-- a soldier member (marked with the squad's id): kept while still in that
-- squad, the squad off duty under no order, the need badly unmet, and
-- within `soldier_days`
local function rec_keep_soldier(sid, id, since, now, soldier_days)
    local u = df.unit.find(tonumber(id))
    if not (u and dfhack.units.isCitizen(u)) or u.military.squad_id ~= tonumber(sid) then
        return false, 'gone or out of the squad', u
    end
    if not squad_free(u.military.squad_id) then return false, 'back on duty', u end
    if killer_held(u) then return false, 'a held killer', u end   -- (0.105.97, merge)
    if in_mood(u) then return false, 'a mood', u end
    if rec_dry(u) then return false, 'thirsty or hungry', u end
    if rec_tantrum(u) then return false, 'a tantrum', u end
    if rec_sick(u) then return false, 'needs care', u end
    since = tonumber(since) or now
    if now - since >= (soldier_days or 5) * 1200 or not soldier_leisure_want(u) then return false, 'time', u end
    return true, nil, u
end

-- (0.105.51) `worst_cat`: the highest stress category moved in (1, very
-- unhappy, by default; 2, the plain unhappy too, when the brain says the
-- fort's unhappy share is high: E's bulk sat at 2, out of reach)
local function rec_eligible(u, worst_cat)
    -- (0.104.139) never one in a tantrum or a rage: they start the fights (rec_base)
    if not rec_base(u) then return false end
    local okc, cat = pcall(dfhack.units.getStressCategory, u)
    return okc and type(cat) == 'number' and cat <= (worst_cat or 1)
end

-- Is member `id` (in since `since`) kept? false and why when not.
local function rec_keep(d, id, since, now, days, friend_days)
    if d.soldiers and d.soldiers[id] then          -- (0.105.97) in for a few days off duty
        return rec_keep_soldier(d.soldiers[id], id, since, now, tonumber(d.soldier_days) or 5)
    end
    local u = df.unit.find(tonumber(id))
    if not (u and dfhack.units.isCitizen(u) and u.military.squad_id == -1) then return false, 'gone or drafted', u end
    if rec_noble(u) then return false, 'a noble', u end      -- (0.104.168) a noble since moved in: out
    if killer_held(u) then return false, 'a held killer', u end   -- (0.105.97) out at once (B, 23 Nov)
    if in_mood(u) then return false, 'a mood', u end         -- (0.105.51) out at once: its workshop is outside
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
    if d.soldiers then d.soldiers[id] = nil end     -- (0.105.97)
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
    for _ in pairs(d.soldiers or {}) do out.for_soldiers = (out.for_soldiers or 0) + 1 end   -- (0.105.97)
    -- (0.105.97) each squad's members and how many badly miss friends, drink
    -- or prayer (short), drink or prayer alone (short_np): the brain keeps a
    -- squad most of whom are short off duty a turn more (planner_leisure)
    pcall(function()
        local sq = {}
        for _, u in ipairs(report_citizens()) do
            local sid = u.military.squad_id
            if sid ~= -1 then
                local r = sq[tostring(sid)] or {n = 0, short = 0, short_np = 0}
                sq[tostring(sid)] = r
                r.n = r.n + 1
                local w, np = soldier_leisure_want(u)
                if w then r.short = r.short + 1 end
                if np then r.short_np = r.short_np + 1 end
            end
        end
        if next(sq) ~= nil then out.squads = sq end
    end)
    if d.water ~= nil then out.water = d.water end
    return out
end

-- `release` (0.105.33): the brain's word that the burrow is to be emptied
-- (a threat, the fort shrunk, the status unreadable): everyone out, nobody in.
-- `unhappy` (0.105.51): the plain unhappy moved in too (rec_eligible).
-- `soldiers`, `soldier_days` (0.105.97): places for off-duty soldiers badly
-- missing friends, drink or prayer, a few days each.
function recreation_tick(max, days, dry_run, txt, friends, friend_days, release, unhappy, soldiers, soldier_days)
    max, days = max or 8, days or 28
    friends, friend_days = friends or 0, friend_days or 7
    soldiers, soldier_days = soldiers or 0, soldier_days or 5
    local d = rec_state()
    d.friends = d.friends or {}
    d.soldiers = type(d.soldiers) == 'table' and d.soldiers or {}
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
    if not dry_run then d.ticked, d.days, d.friend_days, d.soldier_days = now, days, friend_days, soldier_days end
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
    local count, fcount, scount = 0, 0, 0
    for id in pairs(d.members) do
        if d.soldiers[id] then scount = scount + 1
        elseif d.friends[id] then fcount = fcount + 1 else count = count + 1 end
    end
    -- the most stressed eligible first
    local cands = {}
    for _, u in ipairs(report_citizens(true)) do
        local was = tonumber(d.out[tostring(u.id)])
        if was and now - was >= days * 1200 then d.out[tostring(u.id)] = nil; was = nil end
        if not d.members[tostring(u.id)] and not was and rec_eligible(u, unhappy and 2 or 1) then
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
    -- (0.105.97) a few places for off-duty soldiers badly missing friends,
    -- drink or prayer (B, 23 Nov: the soldiers were almost all of those
    -- missing drink), the worst first
    if soldiers > 0 and scount < soldiers then
        local sc = {}
        for _, u in ipairs(report_citizens(true)) do
            local key = tostring(u.id)
            if not d.members[key] and not d.out[key] and rec_soldier_base(u) then
                local w = soldier_leisure_want(u)
                if w then table.insert(sc, {u = u, f = w}) end
            end
        end
        table.sort(sc, function(a, c) if a.f ~= c.f then return a.f < c.f end return a.u.id < c.u.id end)
        for _, c in ipairs(sc) do
            if scount >= soldiers then break end
            if not dry_run then dfhack.burrows.setAssignedUnit(b, c.u, true) end
            d.members[tostring(c.u.id)] = now
            d.soldiers[tostring(c.u.id)] = c.u.military.squad_id
            scount = scount + 1
            table.insert(added, (txt or tostring)(dfhack.units.getReadableName(c.u)) .. ' (soldier off duty)')
        end
    end
    if not dry_run then U.site_put(RECREATION_KEY, d) end
    if #added == 0 and #released == 0 and not tiles then
        -- (0.104.79) nothing to change is no refusal: the rule waits its cooldown
        -- (asked every cycle and refused before, 17:45)
        return {ok = true, unchanged = true, members = count + fcount + scount}
    end
    return {ok = true, burrow_id = b.id, tiles = tiles, added = added, released = released,
            members = count + fcount + scount, dry_run = dry_run or nil}
end

-- (0.105.97) squad `sid` back on duty (act_squad_routine): its soldiers in
-- the recreation burrow let out now, not at the next report, so the burrow
-- and the training don't pull on them both
function recreation_release_squad(sid, txt)
    local d = rec_state()
    if type(d.soldiers) ~= 'table' or next(d.soldiers) == nil then return {} end
    local b = S.find_burrow(RECREATION_NAME)
    local now, released = U.abs_tick(), {}
    for id, q in pairs(d.soldiers) do
        if tonumber(q) == tonumber(sid) then rec_let_out(d, b, id, df.unit.find(tonumber(id)), now, false, txt, released) end
    end
    if #released > 0 then U.site_put(RECREATION_KEY, d) end
    return released
end

-- (r9) this file's locals the later parts use, handed on (each takes them
-- back as locals of its own; a part adds its own the parts after it use)
BURROWS_PART_LOCALS = {U = U, report_citizens = report_citizens, S = S, rec_state = rec_state, rec_dry = rec_dry, zone_tiles = zone_tiles}

---------------------------------------------------------------------------
-- (r9) The rest of the burrows lives in parts beside this file
-- (ai-society-burrows-<part>.lua): hospital (the hospital burrow, the
-- hospital zones, a well that gives water, who is a patient), calm (the
-- calm-down burrows for a dwarf in a tantrum) and weather (the evil weather
-- keep-in, and the AI's burrows emptied: release_ai_burrows). Each runs in
-- this module's own environment, so its names stay
-- reqscript('ai-society-burrows').name (and ai-society's forwarders reach
-- them as before), and a test's swap (B.fn = ...) reaches every part. They
-- load in this order, the old file's. DFHack reloads a module when its own
-- file changes: a change to a part alone is picked up once
-- ai-society-burrows.lua is touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'hospital', 'calm', 'weather'}

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
    local name = 'ai-society-burrows-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-society-burrows: ' .. name .. '.lua is missing (it goes beside ai-society-burrows.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
