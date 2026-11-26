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
PART_VERSIONS = {['ai-society-burrows'] = '0.105.127'}   -- (0.105.26) bumped with BRIDGE_VERSION

-- --- (0.104.78) the recreation burrow ----------------------------------------
--
-- Players' cure for dwarves too busy to meet their needs (Steam forum, 2024):
-- a burrow over the taverns, temples and library, the low-mood moved in, so
-- they take no work and spend their time where the friends, the drink and the
-- gods are. Enxah: 42 badly wanting friends, 18 miserable, hardly anyone idle.
-- (item6) One tavern and one temple, so its members meet one another there.
-- (0.105.115 item22) Only the tavern and the temple now (never the hospital:
-- 0.104.127): no dining hall, bedroom or stockpile, where the members took
-- jobs (StoreItemInBarrel, FillPond) or idled alone. The thirsty, hungry and
-- drowsy are let out to drink, eat and sleep (rec_dry, rec_tired).
-- At most `max` dwarves at a time: very unhappy or worse, not a soldier, not
-- a child, not a patient; each goes back to work when no longer unhappy, or
-- after `days` days. Its members are kept in the save.
RECREATION_NAME = 'AI recreation'
RECREATION_KEY = 'ai-overseer/recreation'
-- (0.104.127) never the hospital: Teacheroar's massacre (31 Oct, ~45 dead, 39 strangled
-- by citizens) happened in its hospital zone, x95-101 y40-48 z167, where 124 wounded lay
-- on the floor and the burrow kept the unhappiest dwarves (patients never join it)
-- (0.105.115 item22) the meeting halls only, and only in a fort with no tavern
-- (the dining halls and bedrooms are gone: 25 Nov, 07:23, of 19 members in
-- four forts one was praying, the rest hauling or idle in bedrooms)
local REC_ZONES = {MeetingHall = true}

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
REC_SLEEPY = 57600           -- (0.105.115 item22) DFHack's "drowsy": the burrow has no bed
-- (0.105.115 item22) a member's least stay (half a day): the recovered or the
-- need met wait this long before going back to work; an emergency (thirst,
-- hunger, sleep, a tantrum, care, a mood, a threat) never waits
REC_MIN_STAY = 600

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

-- (0.105.115 item22) drowsy: out to sleep in a bed (none in the burrow)
local function rec_tired(u)
    local ok, yes = pcall(function() return u.counters2.sleepiness_timer >= REC_SLEEPY end)
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

-- The burrow's tiles: the zones of one tavern and one temple (item6:
-- rec_gathering; every location's and every meeting hall when the fort has
-- no tavern), never a hospital's. (0.105.115 item22) The stockpiles that take
-- food or drink only when neither drink in those zones nor a well is found.
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

-- (item6) The burrow's gathering place: one tavern and one temple, not every
-- location and meeting hall. B "Monastery", 24 Nov: 15 locations for 36
-- dwarves (3 taverns, 5 temples, 2 guildhalls, a library, 4 hospitals); the
-- burrow's 7 members idled in 7 different ones (DF's idle area is a location),
-- 30 of 36 badly missed friends while only 2 missed company at all (they
-- talked, seldom to a friend), and a performance (MakeMerry, TakeItEasy)
-- wants an audience. Pure: from {id, kind, keeper, goblets, instruments,
-- value, any_deity} (kind DF's abstract building type) the ids of the tavern
-- kept (a keeper, goblets and instruments first, then the most valuable,
-- then the lowest id) and of the temple (to all gods first, then the most
-- valuable); nil for either when the fort has none.
-- (0.105.113 item9) a tavern's or temple's rank (the higher the better),
-- shared with social_keep so the burrow's place is the first one kept
function gather_key(l)
    local id, v = tonumber(l.id) or 0, tonumber(l.value) or 0
    if l.kind == 'INN_TAVERN' then
        local s = (l.keeper and 4 or 0) + ((tonumber(l.goblets) or 0) > 0 and 2 or 0)
                  + ((tonumber(l.instruments) or 0) > 0 and 2 or 0)
        return {s, v, -id}
    end
    return {l.any_deity and 1 or 0, v, -id}
end

local function key_above(k, best_k)
    if not best_k then return true end
    for i = 1, #k do
        if k[i] ~= best_k[i] then return k[i] > best_k[i] end
    end
    return false
end

function rec_gathering(locs)
    local tav, tav_k, tem, tem_k
    for _, l in ipairs(locs or {}) do
        local id = tonumber(l.id)
        -- (0.105.113 item9) one whose zones are all inactive (retired) gathers nobody
        if l.inactive then id = nil end
        if id and l.kind == 'INN_TAVERN' then
            local k = gather_key(l)
            if key_above(k, tav_k) then tav, tav_k = id, k end
        elseif id and l.kind == 'TEMPLE' then
            local k = gather_key(l)
            if key_above(k, tem_k) then tem, tem_k = id, k end
        end
    end
    return tav, tem
end

-- (item6) bumped when the burrow's layout rule changes: a burrow filled by
-- an older rule is filled again at the next tick, not at its weekly refill
REC_FILL_V = 3      -- (0.105.115 item22) 3: the tavern and temple only

-- (0.105.113 item9) a civzone's active flag (DF's zone screen), or nil unread
local function zone_on(bid)
    local ok, v = pcall(function() return df.building.find(bid).spec_sub_flag.active end)
    if ok and type(v) == 'boolean' then return v end
    return nil
end

-- true when a location has zones and every one is inactive
function loc_inactive(zones)
    if #zones == 0 then return false end
    for _, bid in ipairs(zones) do
        if zone_on(bid) ~= false then return false end
    end
    return true
end

-- The fort's locations as rec_gathering reads them (never a hospital: it is
-- left out of the burrow anyway), and each one's zones.
local function rec_locations()
    local out = {}
    pcall(function()
        for _, b in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                local gone = false
                pcall(function() gone = b.flags.DOES_NOT_EXIST end)
                if gone then return end
                local c = b:getContents()
                local e = {id = b.id, kind = df.abstract_building_type[b:getType()], zones = {}}
                pcall(function()
                    e.value, e.goblets, e.instruments = c.location_value, c.count_goblets, c.count_instruments
                end)
                for _, bid in ipairs(c.building_ids) do table.insert(e.zones, bid) end
                e.inactive = loc_inactive(e.zones)            -- (0.105.113 item9)
                pcall(function()
                    for _, o in ipairs(b.occupations) do
                        if df.occupation_type[o.type] == 'TAVERN_KEEPER' and o.histfig_id ~= -1 then e.keeper = true end
                    end
                end)
                if e.kind == 'TEMPLE' then
                    pcall(function()
                        local dt = df.religious_practice_type[b.deity_type]
                        e.any_deity = dt ~= 'WORSHIP_HFID' and dt ~= 'RELIGION_ENID'
                    end)
                end
                table.insert(out, e)
            end)
        end
    end)
    return out
end

function fill_recreation(burrow)
    dfhack.burrows.clearTiles(burrow)
    local n, loc_zone, hosp_zone = 0, {}, {}
    local cx = {x = 0, y = 0, z = 0, n = 0}
    local locs = rec_locations()
    -- (item6) one tavern and one temple when the fort has a tavern; else (as
    -- before) every location's zones and every meeting hall
    local tav, tem = rec_gathering(locs)
    for _, e in ipairs(locs) do
        local zs = e.kind == 'HOSPITAL' and hosp_zone or loc_zone
        if e.kind == 'HOSPITAL' or not tav or e.id == tav or e.id == tem then
            for _, bid in ipairs(e.zones) do zs[bid] = true end
        end
    end
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        if t == df.building_type.Civzone then
            local kind = df.civzone_type[b.type] or ''
            local plain = REC_ZONES[kind] and (kind ~= 'MeetingHall' or not tav)
            if not hosp_zone[b.id] and kind ~= 'Hospital' and (loc_zone[b.id] or plain) then
                n = n + zone_tiles(b, burrow)
                cx.x, cx.y, cx.z, cx.n = cx.x + (b.x1 + b.x2) / 2, cx.y + (b.y1 + b.y2) / 2, cx.z + b.z, cx.n + 1
            end
        end
    end
    local water = rec_water(burrow, cx)
    if water == nil then
        -- (0.105.115 item22) no drink nor well: the food and drink piles, as before
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.Stockpile then
                local okf, food = pcall(function() return b.settings.flags.food end)
                -- (0.105.97) never a killer cell's own pile (ai-killers LARDER_PREFIX): the way
                -- to it leads into the killer's cell (B, 23 Nov)
                local okc, larder = pcall(function() return tostring(b.name):find('AI cell larder ', 1, true) == 1 end)
                if okf and food and not (okc and larder) then n = n + zone_tiles(b, burrow) end
            end
        end
        water = rec_water(burrow, cx)
        if water == 'drink' then water = 'piles' end
    end
    return n, water, tav and {tavern = tav, temple = tem} or nil
end

-- --- (0.105.113 item9) the taverns and temples drawn together --------------
--
-- B "Monastery", 24 Nov 23:40: 35 citizens (94 a season before) and every
-- place built for the 94 still open: 3 taverns, 5 temples, 2 guildhalls, a
-- library, 4 hospitals. DF's idle dwarves each go to one of them: 11 idle in
-- 6 of them and the barracks, never more than 3 in one; 26 of 35 badly
-- missed friends (21 of those have 3 or more close friends, never met). The
-- brain sends how many taverns (nt) and temples (ne) the fort needs by its
-- size; the others' zones are made inactive (DF's zone screen), so the idle
-- gather in the ones kept; one the AI retired is set going again, the best
-- first, when the fort grows. One the player makes active again (or made
-- inactive) is the player's: never touched again. Guildhalls, the library
-- and the hospitals are never touched (a guild's petition; the care).
SOCIAL_KEY = 'ai-overseer/social-retired'

local function social_state()
    local d = U.site_get(SOCIAL_KEY, {})
    d.zones = type(d.zones) == 'table' and d.zones or {}     -- zone id -> location id: the AI's retired zones
    d.player = type(d.player) == 'table' and d.player or {}  -- location id -> true: the player's (made active again)
    return d
end

-- Pure: the ids kept ({[id] = true}) of the taverns and temples in `locs`
-- (rec_locations' rows): the best by gather_key up to `nt` taverns and `ne`
-- temples (so the first is the recreation burrow's), and the player's
-- (`held`, {[tostring(id)] = true}) besides. Each kind keeps one at least.
function social_keep(locs, nt, ne, held)
    held = held or {}
    local rows = {INN_TAVERN = {}, TEMPLE = {}}
    for _, l in ipairs(locs or {}) do
        local id = tonumber(l.id)
        if id and rows[l.kind] then
            table.insert(rows[l.kind], {id = id, k = gather_key(l), held = held[tostring(id)] and 1 or 0})
        end
    end
    local keep = {}
    for kind, n in pairs({INN_TAVERN = math.max(1, tonumber(nt) or 1), TEMPLE = math.max(1, tonumber(ne) or 1)}) do
        local r = rows[kind]
        table.sort(r, function(a, b) return key_above(a.k, b.k) end)
        for i, e in ipairs(r) do
            if i <= n or e.held == 1 then keep[e.id] = true end
        end
    end
    return keep
end

-- the location ids the AI keeps retired (for the report)
function social_retired()
    local d, seen, out = social_state(), {}, {}
    for zid, lid in pairs(d.zones) do
        if zone_on(tonumber(zid)) == false and not seen[lid] then
            seen[lid] = true
            table.insert(out, tonumber(lid))
        end
    end
    table.sort(out)
    return out
end

function social_consolidate(nt, ne, dry_run)
    local d = social_state()
    -- a zone the AI retired that stands active again (or is gone): the player's
    for zid, lid in pairs(d.zones) do
        local on = zone_on(tonumber(zid))
        if on ~= false then
            d.zones[zid] = nil
            if on == true then d.player[tostring(lid)] = true end
        end
    end
    local ours = {}
    for _, lid in pairs(d.zones) do ours[tostring(lid)] = true end
    local cand = {}
    for _, e in ipairs(rec_locations()) do
        if (e.kind == 'INN_TAVERN' or e.kind == 'TEMPLE') and #e.zones > 0
                and (not e.inactive or ours[tostring(e.id)]) then
            table.insert(cand, e)
        end
    end
    local keep = social_keep(cand, nt, ne, d.player)
    local off, on = {}, {}
    for _, e in ipairs(cand) do
        for _, bid in ipairs(e.zones) do
            if keep[e.id] and d.zones[tostring(bid)] then
                table.insert(on, {zone = bid, loc = e.id, kind = e.kind})
            elseif not keep[e.id] and not d.player[tostring(e.id)] and zone_on(bid) == true then
                table.insert(off, {zone = bid, loc = e.id, kind = e.kind})
            end
        end
    end
    local out = {ok = true, retired = {}, restored = {}, dry_run = dry_run or nil}
    for id in pairs(keep) do out.kept = out.kept or {}; table.insert(out.kept, id) end
    if out.kept then table.sort(out.kept) end
    if #off == 0 and #on == 0 then
        if not dry_run then U.site_put(SOCIAL_KEY, d) end
        return {ok = false, rejected = true, kept = out.kept,
                error = 'the taverns and temples are already as asked (' .. tostring(nt) .. ' and ' .. tostring(ne) .. ')'}
    end
    local function names(list, into)
        local seen = {}
        for _, r in ipairs(list) do
            if not seen[r.loc] then seen[r.loc] = true; table.insert(into, (r.kind == 'TEMPLE' and 'temple #' or 'tavern #') .. r.loc) end
        end
    end
    if dry_run then names(off, out.retired); names(on, out.restored); return out end
    local done_off, done_on = {}, {}
    for _, r in ipairs(off) do
        pcall(function() df.building.find(r.zone).spec_sub_flag.active = false end)
        if zone_on(r.zone) == false then d.zones[tostring(r.zone)] = r.loc; table.insert(done_off, r) end
    end
    for _, r in ipairs(on) do
        pcall(function() df.building.find(r.zone).spec_sub_flag.active = true end)
        if zone_on(r.zone) == true then d.zones[tostring(r.zone)] = nil; table.insert(done_on, r) end
    end
    U.site_put(SOCIAL_KEY, d)
    names(done_off, out.retired); names(done_on, out.restored)
    if #done_off == 0 and #done_on == 0 then
        return {ok = false, error = 'the game would not change the zones of the taverns and temples'}
    end
    return out
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
    if rec_tired(u) then return false end            -- (0.105.115 item22) and sleep
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

-- (0.105.115 item22) a citizen's close friends among the citizens (DF's
-- relationship of love 50+, as the report's social.relations counts them):
-- a list of units, or nil when the relationships can't be read. `by_hf`:
-- hist_figure_id -> citizen.
REC_CLOSE_LOVE = 50
function close_friends(u, by_hf)
    local ok, list = pcall(function()
        local hf = df.historical_figure.find(u.hist_figure_id)
        local out = {}
        for _, r in ipairs(hf.info.relationships.hf_visual) do
            local x = by_hf[r.histfig_id]
            if x and x ~= u and r.core.love >= REC_CLOSE_LOVE then table.insert(out, x) end
        end
        return out
    end)
    return ok and list or nil
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
    if in_mood(u) or rec_noble(u) or rec_tantrum(u) or rec_dry(u) or rec_tired(u) then return false end
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
    if rec_tired(u) then return false, 'drowsy', u end           -- (0.105.115 item22)
    if rec_tantrum(u) then return false, 'a tantrum', u end
    if rec_sick(u) then return false, 'needs care', u end
    since = tonumber(since) or now
    if now - since < REC_MIN_STAY then return true, nil, u end   -- (0.105.115 item22) half a day at least
    if now - since >= (soldier_days or 5) * 1200 then return false, 'time', u end
    if not soldier_leisure_want(u) then return false, 'need met', u end
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
    if rec_tired(u) then return false, 'drowsy', u end           -- (0.105.115 item22) no bed inside
    if rec_tantrum(u) then return false, 'a tantrum', u end
    if rec_sick(u) then return false, 'needs care', u end
    since = tonumber(since) or now
    -- (0.105.115 item22) half a day at least: DF lets a dwarf socialise only
    -- when idle, and the member had to walk there first
    if now - since < REC_MIN_STAY then return true, nil, u end
    if d.pals and d.pals[id] then
        -- (0.105.115 item22) a close friend brought in with a lonely member:
        -- kept while that member is, within `friend_days`
        if now - since >= friend_days * 1200 then return false, 'time', u end
        if not d.members[tostring(d.pals[id])] then return false, 'friend gone out', u end
        return true, nil, u
    end
    if d.friends and d.friends[id] then
        -- (0.104.80) in for friends: out after `friend_days`, or once the need is met
        if now - since >= friend_days * 1200 then return false, 'time', u end
        if not badly_wants_friends(u) then return false, 'need met', u end
        return true, nil, u
    end
    local okc, cat = pcall(dfhack.units.getStressCategory, u)
    if okc and type(cat) == 'number' and cat >= 3 then return false, 'recovered', u end
    if now - since >= days * 1200 then return false, 'time', u end
    return true, nil, u
end

-- (0.105.115 item22) a member's labours off while in the burrow (25 Nov
-- 07:23: of 19 members one socialised, the rest hauling inside it: DF lets a
-- dwarf socialise only when idle). The ones it had are kept in the save
-- (d.labors[id], by name) and given back when it goes out. Looked at again
-- at every report: one the work details (or the AI's labour rules) gave back
-- is taken off again and added to the list.
function rec_labors_off(d, id, u)
    d.labors = type(d.labors) == 'table' and d.labors or {}
    local had = type(d.labors[id]) == 'table' and d.labors[id] or {}
    local seen = {}
    for _, n in ipairs(had) do seen[n] = true end
    local n = 0
    pcall(function()
        local last = df.unit_labor._last_item
        for i = 0, last do
            local okl, on = pcall(function() return u.status.labors[i] end)
            local name = df.unit_labor[i]
            if okl and on == true and name and pcall(function() u.status.labors[i] = false end) then
                n = n + 1
                if not seen[name] then table.insert(had, name); seen[name] = true end
            end
        end
    end)
    if #had > 0 then d.labors[id] = had end
    return n
end

function rec_labors_back(d, id, u)
    local had = type(d.labors) == 'table' and d.labors[id]
    if type(had) ~= 'table' then return 0 end
    local n = 0
    if u then
        for _, name in ipairs(had) do
            local ok = pcall(function()
                local l = df.unit_labor[name]
                if l ~= nil then u.status.labors[l] = true end
            end)
            if ok then n = n + 1 end
        end
    end
    d.labors[id] = nil
    return n
end

-- (0.105.115 item22) an emergency the labours are needed for: patients
-- wait for care and no citizen outside the burrow can diagnose: the members
-- who could (their labours kept in d.labors) are let out
-- `but`: a unit not counted (one about to move in)
local function rec_doctor_short(d, but)
    local short = false
    pcall(function()
        local sick, docs = 0, 0
        local l = df.unit_labor.DIAGNOSE
        for _, u in ipairs(report_citizens()) do
            if rec_sick(u) then sick = sick + 1 end
            if not d.members[tostring(u.id)] and u ~= but and u.military.squad_id == -1
                    and u.status.labors[l] then docs = docs + 1 end
        end
        short = sick > 0 and docs == 0
    end)
    return short
end

local function rec_could_diagnose(d, id)
    for _, n in ipairs(type(d.labors) == 'table' and type(d.labors[id]) == 'table' and d.labors[id] or {}) do
        if n == 'DIAGNOSE' then return true end
    end
    return false
end

local function rec_let_out(d, b, id, u, now, dry_run, txt, released, why)
    if not dry_run and u and b then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
    if not dry_run then rec_labors_back(d, id, u) end           -- (0.105.115 item22)
    if not dry_run and why then                                 -- (0.105.115 item22) why, for the tick's result
        d.out_why = type(d.out_why) == 'table' and d.out_why or {}
        d.out_why[why] = (tonumber(d.out_why[why]) or 0) + 1
    end
    d.members[id] = nil
    if d.pals then d.pals[id] = nil end
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
        local relabored = 0
        local doc = rec_doctor_short(d)
        for id, since in pairs(d.members) do
            local keep, why, u = rec_keep(d, id, since, now, days, fdays)
            if keep and doc and rec_could_diagnose(d, id) then keep, why = false, 'a doctor needed' end
            if why_all or not keep then
                if not u then u = df.unit.find(tonumber(id)) end
                rec_let_out(d, b, id, u, now, false, txt, released, why_all and 'all out' or why)
            elseif u then
                -- (0.105.115 item22) labours the details gave back: off again
                relabored = relabored + rec_labors_off(d, id, u)
            end
        end
        if relabored > 0 then out.labors_reset = relabored end
        if #released > 0 or relabored > 0 then
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
    for _ in pairs(d.pals or {}) do out.for_pals = (out.for_pals or 0) + 1 end   -- (0.105.115 item22)
    if type(d.out_why) == 'table' and next(d.out_why) ~= nil then out.out_why = d.out_why end
    -- (item6) the tavern (and temple) the burrow keeps its members in
    if type(d.gathering) == 'table' then out.gathering = d.gathering end
    -- (0.105.113 item9) the taverns and temples the AI retired
    pcall(function()
        local r = social_retired()
        if #r > 0 then out.retired = r end
        local held = {}
        for lid in pairs(social_state().player) do table.insert(held, tonumber(lid)) end
        if #held > 0 then table.sort(held); out.player_kept = held end   -- the player's: kept besides
    end)
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
        for id in pairs(d.members) do rec_let_out(d, b, id, df.unit.find(tonumber(id)), now, dry_run, txt, released, 'release') end
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
    -- (0.105.115 item22) and at once when the tavern or temple kept changed
    -- (social_consolidate retired the one the burrow held)
    local moved = false
    if type(d.gathering) == 'table' then
        local okg, gt, ge = pcall(function() return rec_gathering(rec_locations()) end)
        moved = okg and (gt ~= d.gathering.tavern or ge ~= d.gathering.temple)
    end
    if made or not d.filled or now - d.filled >= 7 * 1200 or moved
            or (d.water == false and now - d.filled >= 1200) or d.fill_v ~= REC_FILL_V then
        if not dry_run then
            local water, place
            tiles, water, place = fill_recreation(b)
            d.filled, d.water = now, water ~= nil and water or false
            d.fill_v, d.gathering = REC_FILL_V, place     -- (item6)
        end
    end
    if not dry_run then d.ticked, d.days, d.friend_days, d.soldier_days = now, days, friend_days, soldier_days end
    local released, added = {}, {}
    -- back to work: recovered, gone, drafted, thirsty, raging, sick, or in long enough
    local dry_burrow = d.water == false
    for id, since in pairs(d.members) do
        local keep, why, u = rec_keep(d, id, since, now, days, friend_days)
        if dry_burrow or not keep then
            if not u then u = df.unit.find(tonumber(id)) end
            rec_let_out(d, b, id, u, now, dry_run, txt, released, dry_burrow and 'no drink' or why)
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
    -- (0.105.115 item22) moved in: into the burrow, its labours off
    -- never the last diagnoser outside while patients wait (false: not moved in)
    local laboff = 0
    local function admit(u)
        local okd, diag = pcall(function() return u.status.labors[df.unit_labor.DIAGNOSE] == true end)
        if okd and diag and rec_doctor_short(d, u) then return false end
        if not dry_run then
            dfhack.burrows.setAssignedUnit(b, u, true)
            laboff = laboff + rec_labors_off(d, tostring(u.id), u)
        end
        d.members[tostring(u.id)] = now
        return true
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
        if admit(c.u) then
            count = count + 1
            table.insert(added, (txt or tostring)(dfhack.units.getReadableName(c.u)))
        end
    end
    -- (0.104.80) a few places for civilians who badly want friends: a week
    -- where the others are (Enxah, autumn y76: 42 badly, 21 of them with no
    -- close friend, 11 of 14 idle dwarves in no meeting zone)
    -- (0.105.115 item22) and where a close friend is: B, 25 Nov 10:50, none of
    -- the members' close friends was in the burrow or the tavern (they idled
    -- in other halls and the barracks), so the need could not be met there.
    -- First those with a close friend already in the burrow, then those with
    -- one who can come along (brought in with them, a pal: d.pals), then
    -- those whose friends can't be read or can't come; never one with no
    -- close friend in the fort at all (F: two at -200000 held places).
    local nofriend = 0
    if friends > 0 and fcount < friends then
        local cits = report_citizens(true)
        local by_hf = {}
        for _, u in ipairs(cits) do pcall(function() by_hf[u.hist_figure_id] = u end) end
        local fc = {}
        for _, u in ipairs(cits) do
            local key = tostring(u.id)
            if not d.members[key] and not d.out[key] and rec_base(u) then
                local f = badly_wants_friends(u)
                if f then
                    local close = close_friends(u, by_hf)
                    local tier, pal, palf = 2, nil, nil
                    if close and #close == 0 then tier = nil; nofriend = nofriend + 1 end
                    for _, x in ipairs(close or {}) do
                        local xk = tostring(x.id)
                        local inside = d.members[xk] ~= nil
                        if not inside and b then
                            pcall(function() inside = dfhack.burrows.isAssignedTile(b, x.pos) end)
                            inside = inside == true
                        end
                        if inside then tier = 0
                        elseif tier ~= 0 and not d.members[xk] and rec_base(x) then
                            -- the friend who misses friends most comes along
                            local xf = badly_wants_friends(x) or 0
                            if not pal or xf < palf then pal, palf, tier = x, xf, 1 end
                        end
                    end
                    if tier then table.insert(fc, {u = u, f = f, tier = tier, pal = tier == 1 and pal or nil}) end
                end
            end
        end
        table.sort(fc, function(a, c)
            if a.tier ~= c.tier then return a.tier < c.tier end
            if a.f ~= c.f then return a.f < c.f end
            return a.u.id < c.u.id
        end)
        for _, c in ipairs(fc) do
            if fcount >= friends then break end
            if not d.members[tostring(c.u.id)] and admit(c.u) then
                d.friends[tostring(c.u.id)] = true
                fcount = fcount + 1
                table.insert(added, (txt or tostring)(dfhack.units.getReadableName(c.u)) .. ' (for friends)')
                local p = c.pal
                if p and not d.members[tostring(p.id)] and fcount < friends and admit(p) then
                    d.friends[tostring(p.id)] = true
                    d.pals = type(d.pals) == 'table' and d.pals or {}
                    d.pals[tostring(p.id)] = c.u.id
                    fcount = fcount + 1
                    table.insert(added, (txt or tostring)(dfhack.units.getReadableName(p)) .. ' (a friend of '
                        .. (txt or tostring)(dfhack.units.getReadableName(c.u)) .. ')')
                end
            end
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
            if admit(c.u) then
                d.soldiers[tostring(c.u.id)] = c.u.military.squad_id
                scount = scount + 1
                table.insert(added, (txt or tostring)(dfhack.units.getReadableName(c.u)) .. ' (soldier off duty)')
            end
        end
    end
    -- (0.105.115 item22) why members went out since the last tick (the
    -- reports' too), into the tick's result (the journal), then cleared
    local out_why = type(d.out_why) == 'table' and next(d.out_why) ~= nil and d.out_why or nil
    if not dry_run then d.out_why = nil; U.site_put(RECREATION_KEY, d) end
    if #added == 0 and #released == 0 and not tiles and not out_why then
        -- (0.104.79) nothing to change is no refusal: the rule waits its cooldown
        -- (asked every cycle and refused before, 17:45)
        return {ok = true, unchanged = true, members = count + fcount + scount}
    end
    return {ok = true, burrow_id = b.id, tiles = tiles, added = added, released = released,
            members = count + fcount + scount, dry_run = dry_run or nil, out_why = out_why,
            labors_off = laboff > 0 and laboff or nil, no_close_friend = nofriend > 0 and nofriend or nil}
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
