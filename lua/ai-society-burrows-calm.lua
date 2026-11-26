-- ai-society-burrows-calm: the calm-down burrows: a dwarf in a tantrum moved to a quiet free
-- bedroom far from the hospitals, with a drink, and let out once calm.
--
-- (r9) A part of ai-society-burrows, not a script of its own: ai-society-burrows.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-society-burrows').name and the names defined there and in the
-- parts before it are in reach.

if not BURROWS_PART_LOCALS then qerror('ai-society-burrows-calm is a part of ai-society-burrows; run ai-society-burrows') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-burrows-calm'] = '0.105.126'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, S, rec_state, zone_tiles, HOSP_SCAN_MAX, hb_state, hb_now, walk_group, stand_pos, can_walk, in_zones, pile_holds, burrow_unit_ids, in_tantrum, hb_citizen, shelter_id, wk_take_out = BURROWS_PART_LOCALS.U, BURROWS_PART_LOCALS.report_citizens, BURROWS_PART_LOCALS.S, BURROWS_PART_LOCALS.rec_state, BURROWS_PART_LOCALS.zone_tiles, BURROWS_PART_LOCALS.HOSP_SCAN_MAX, BURROWS_PART_LOCALS.hb_state, BURROWS_PART_LOCALS.hb_now, BURROWS_PART_LOCALS.walk_group, BURROWS_PART_LOCALS.stand_pos, BURROWS_PART_LOCALS.can_walk, BURROWS_PART_LOCALS.in_zones, BURROWS_PART_LOCALS.pile_holds, BURROWS_PART_LOCALS.burrow_unit_ids, BURROWS_PART_LOCALS.in_tantrum, BURROWS_PART_LOCALS.hb_citizen, BURROWS_PART_LOCALS.shelter_id, BURROWS_PART_LOCALS.wk_take_out   -- (r9) the hub's and earlier parts' locals

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
    -- (r9, audit A7 #21) the AI shelter's: the weather keep-in's members, no player's burrow
    local sid = shelter_id()
    if sid >= 0 and not ids[sid] then ids[sid] = 'wk' end
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
        elseif killer_held(u) then why = 'held killer'           -- (0.105.97) their cell, not a calm room
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
                elseif killer_held(u) then why = 'killer'                 -- (0.105.97) kept in their cell
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
                and not in_mood(u)   -- (0.105.51 merge) a mood claims its workshop outside the burrow
                and not killer_held(u)   -- (0.105.97) a held killer stays in their cell (B, 23 Nov)
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
                if c.which.wk then wk_take_out(c.u, c.which.wk) end   -- (r9) out of the weather keep-in
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

-- (r9) this part's locals the parts after it use, handed on
BURROWS_PART_LOCALS.calm_state = calm_state
