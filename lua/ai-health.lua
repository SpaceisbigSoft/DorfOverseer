-- (0.104.168) Infected wounds: who walks about with one, and getting them
-- into a hospital bed so DF's doctors see them.
--
-- Teacheroar, 1 Nov: 77 of 142 citizens with an infected wound, two of them
-- with a treatment asked; the rest up and working, never diagnosed, and
-- dwarves dying of infection months after the fight. What the game does (read
-- from DFHack and df-structures, 53.16):
--   * a dwarf with a wound has the patient flag needs_healthcare
--     (NEEDS_URGENT_CARE); a treatment is asked only through the rq_ flags
--     (GO_IN_FOR_DIAGNOSIS, NEEDS_CLEANING, NEEDS_SURGERY...), and DF's wiki:
--     a diagnosis comes before any treatment;
--   * u.body.infection_level (overall_infection_load) of 300 or more makes
--     the dwarf bleed (df-structures' note): the infection deaths;
--   * cleaning a patient (job CleanPatient) is the CLEAN labour, not a
--     doctor's (df-structures job_type attrs); soap is the only thing that
--     sterilizes a wound (wiki), surgery mends infected or rotten ones.
-- DFHack's own dwarfvet does what a player's doctor can't ask for: an
-- injured animal with needs_healthcare and no job is given a special Rest job
-- on a free tile of a hospital zone, and DF's doctors treat it there. The same
-- here for citizens: an idle one with an infected wound, needs_healthcare
-- and no treatment asked is put to rest in a free hospital bed (the worst
-- infections first).
--
-- (0.104.168, review) Never a bed taken for good: a sleeper DF hasn't asked
-- a treatment for within REST_DAYS is got up (the Rest job removed) and not
-- sent again for COOLDOWN_DAYS; at most `cap` of the AI's undiagnosed
-- sleepers lie in the beds at once, always `keep_free` beds left for DF's own
-- patients. Who was sent, got up and helped is kept in the save (site data),
-- so a reload forgets nobody. The tending is done at each report (survey),
-- as the hospital burrow re-checks its members there, so the sleepers are got
-- up even while the planner asks nothing.
--@module = true

local INFECTION_BLEEDS = 300            -- df-structures: ">=300 causes bleeding"
local RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
            'rq_setting', 'rq_traction', 'rq_crutch'}
REST_DAYS = 3                -- a sleeper with no treatment asked after this many days is got up
COOLDOWN_DAYS = 28           -- ...and not sent again for this many
STATE_KEY = 'ai-overseer/infected-rest'
local DAY = 1200

local function now_tick()
    return df.global.cur_year * 403200 + df.global.cur_year_tick
end

-- the save's record: sent = {id = {tick, job}}, cooldown = {id = tick} (got
-- up with nothing asked), helped = {id = tick} (DF asked a treatment)
local function load_state()
    local ok, d = pcall(dfhack.persistent.getSiteData, STATE_KEY, {})
    d = ok and type(d) == 'table' and d or {}
    for _, k in ipairs({'sent', 'cooldown', 'helped'}) do
        d[k] = type(d[k]) == 'table' and d[k] or {}
    end
    return d
end

local function save_state(d)
    pcall(dfhack.persistent.saveSiteData, STATE_KEY, d)
end

-- Pure: the candidates to send, best first. Each: {id, load, infected,
-- care (needs_healthcare), asked, in_hospital, idle, soldier, child, mood,
-- sent, cooldown, unhappy, tantrum, insane, burrow, staff, restrained,
-- noble}. Only an idle grown citizen with an infected wound DF says needs
-- care, no treatment asked, outside the hospitals; never a soldier, one in a
-- mood, a tantrum or mad, the unhappy, one in any burrow, the hospitals' own
-- staff, the caged or chained, an office holder, nor one sent or got up
-- lately. Bleeding (load >= 300) first, then the heavier infection, ties to
-- the lower id.
local BARS = {'asked', 'in_hospital', 'soldier', 'child', 'mood', 'sent', 'cooldown', 'unhappy', 'tantrum',
              'insane', 'burrow', 'staff', 'restrained', 'noble'}

function eligible(c)
    if not (c.infected and c.care and c.idle) then return false end
    for _, k in ipairs(BARS) do if c[k] then return false end end
    return true
end

function pick_patients(cands, max)
    local list = {}
    for _, c in ipairs(cands) do
        if eligible(c) then table.insert(list, c) end
    end
    table.sort(list, function(a, b)
        local ba, bb = (a.load or 0) >= INFECTION_BLEEDS, (b.load or 0) >= INFECTION_BLEEDS
        if ba ~= bb then return ba end
        if (a.load or 0) ~= (b.load or 0) then return (a.load or 0) > (b.load or 0) end
        return a.id < b.id
    end)
    local out = {}
    for i = 1, math.min(max or #list, #list) do out[i] = list[i] end
    return out
end

-- Pure: how many may be sent now: at most `max`, `cap` sleepers in all,
-- `keep_free` beds left free.
function room(max, cap, keep_free, sleeping, free)
    return math.max(0, math.min(max, cap - sleeping, free - keep_free))
end

-- --- the game -----------------------------------------------------------------

local function hospitals()
    local zones, staff = {}, {}
    local site = dfhack.world.getCurrentSite()
    for _, loc in ipairs(site and site.buildings or {}) do
        if df.abstract_building_type[loc:getType()] == 'HOSPITAL' then
            local c = loc:getContents()
            for _, bid in ipairs(c and c.building_ids or {}) do
                local z = df.building.find(bid)
                if z then zones[z.id] = z end
            end
            pcall(function()
                for _, o in ipairs(loc.occupations) do
                    if o.unit_id ~= -1 then staff[o.unit_id] = true end
                end
            end)
        end
    end
    return zones, staff
end

local function in_hospital(u, zones)
    local ok, inside = pcall(function()
        for _, z in ipairs(dfhack.buildings.findCivzonesAt(u.pos) or {}) do
            if zones[z.id] then return true end
        end
        return false
    end)
    return ok and inside
end

local function infected(u)
    local ok, r = pcall(function()
        for _, w in ipairs(u.body.wounds) do
            if w.flags.infection then return true end
        end
        return false
    end)
    return ok and r
end

local function asked(u)
    local ok, r = pcall(function()
        local f = u.health and u.health.flags
        if not f then return false end
        for _, k in ipairs(RQ) do if f[k] then return true end end
        return false
    end)
    return ok and r
end

local function load_of(u)
    local ok, n = pcall(function() return u.body.infection_level end)
    return ok and tonumber(n) or 0
end

local function rest_job(u)
    local ok, j = pcall(function()
        local j = u.job.current_job
        return j ~= nil and j.job_type == df.job_type.Rest and j or nil
    end)
    return ok and j or nil
end

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

-- every job in the world: (0.104.168, review) a bed is held by any job
-- aimed at it, not only by a citizen's Rest job
local function each_job(fn)
    pcall(function()
        local link = df.global.world.jobs.list.next
        while link do
            if link.item then fn(link.item) end
            link = link.next
        end
    end)
end

-- The hospital zones' finished beds (or, with `kind`, traction benches:
-- 0.105.24) nobody lies in, is on the way to, or uses (its users list).
local function free_beds(zones, kind)
    kind = kind or 'Bed'
    local taken = {}
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function() taken[key(u.pos.x, u.pos.y, u.pos.z)] = true end)
            pcall(function()
                local j = u.job.current_job
                if j then taken[key(j.pos.x, j.pos.y, j.pos.z)] = true end
            end)
        end
    end)
    each_job(function(j) pcall(function() taken[key(j.pos.x, j.pos.y, j.pos.z)] = true end) end)
    local beds, total = {}, 0
    for _, z in pairs(zones) do
        pcall(function()
            for _, b in ipairs(z.contained_buildings) do
                if df.building_type[b:getType()] == kind then
                    local done = true
                    pcall(function() done = b:getBuildStage() >= b:getMaxBuildStage() end)
                    if done then
                        total = total + 1
                        local used = false
                        pcall(function() used = #b.users.unit > 0 end)
                        if not used and not taken[key(b.centerx, b.centery, b.z)] then
                            table.insert(beds, {x = b.centerx, y = b.centery, z = b.z, id = b.id})
                        end
                    end
                end
            end
        end)
    end
    return beds, total
end

local function in_tantrum(u)
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    return okm and (m == 'Tantrum' or m == 'Enraged')
end

local function candidate(u, zones, staff, d)
    local c = {id = u.id, unit = u, infected = infected(u), asked = asked(u), load = load_of(u)}
    if not c.infected then return c end
    pcall(function() c.care = u.health ~= nil and u.health.flags.needs_healthcare == true end)
    c.in_hospital = in_hospital(u, zones)
    pcall(function() c.idle = u.job.current_job == nil end)
    c.soldier = u.military.squad_id ~= -1
    pcall(function() c.child = not dfhack.units.isAdult(u) end)
    pcall(function() c.mood = u.mood ~= nil and u.mood ~= -1 end)
    c.sent = d.sent[tostring(u.id)] ~= nil
    c.cooldown = d.cooldown[tostring(u.id)] ~= nil
    -- (review) unhappy or worse (stress category 2 and below), raging, mad
    pcall(function() local cat = dfhack.units.getStressCategory(u); c.unhappy = type(cat) == 'number' and cat <= 2 end)
    c.tantrum = in_tantrum(u)
    pcall(function() c.insane = dfhack.units.isSane(u) == false end)
    -- any burrow: the AI's recreation or hospital burrow, or a player's
    pcall(function() c.burrow = #u.burrows > 0 end)
    c.staff = staff[u.id] == true
    pcall(function() c.restrained = u.flags1.caged or u.flags1.chained end)
    pcall(function() local l = dfhack.units.getNoblePositions(u); c.noble = l ~= nil and #l > 0 end)
    return c
end

local function labor_count(citizens, name)
    local id, n = df.unit_labor[name], 0
    if id == nil then return nil end
    for _, u in ipairs(citizens) do
        pcall(function()
            if u.military.squad_id == -1 and dfhack.units.isAdult(u) and u.status.labors[id] then n = n + 1 end
        end)
    end
    return n
end

-- The AI's sleepers tended: DF asked a treatment (helped: DF's patient now),
-- DF ended the rest, or REST_DAYS passed with nothing asked (the Rest job
-- removed: got up, cooldown); old cooldowns and helps forgotten. Returns the
-- counts; `dry_run` changes nothing.
local function tend(d, t, dry_run)
    local out = {sleeping = 0, got_up = 0, ended = 0}
    for sid, e in pairs(d.sent) do
        local u = df.unit.find(tonumber(sid))
        local oka, alive = pcall(function() return dfhack.units.isAlive(u) end)
        local when = type(e) == 'table' and tonumber(e.tick) or tonumber(e) or t
        if not u or (oka and not alive) or t < when then
            if not dry_run then d.sent[sid] = nil end
        elseif asked(u) then
            if not dry_run then d.sent[sid], d.helped[sid] = nil, t end
        else
            local j = rest_job(u)
            -- (0.104.168, review) only the AI's own Rest job: DF may have ended it
            -- and given the dwarf a Rest of its own for a new wound since
            local mine = type(e) == 'table' and tonumber(e.job) or nil
            if j and mine and j.id ~= mine then j = nil end
            if not j then
                out.ended = out.ended + 1                 -- DF ended the rest itself
                if not dry_run then d.sent[sid], d.cooldown[sid] = nil, t end
            elseif t - when >= REST_DAYS * DAY then
                out.got_up = out.got_up + 1
                if not dry_run then
                    pcall(dfhack.job.removeJob, j)
                    d.sent[sid], d.cooldown[sid] = nil, t
                end
            else
                out.sleeping = out.sleeping + 1
            end
        end
    end
    if not dry_run then
        for sid, w in pairs(d.cooldown) do
            if t < (tonumber(w) or 0) or t - (tonumber(w) or 0) >= COOLDOWN_DAYS * DAY then d.cooldown[sid] = nil end
        end
        for sid, w in pairs(d.helped) do
            if t < (tonumber(w) or 0) or t - (tonumber(w) or 0) >= COOLDOWN_DAYS * DAY then d.helped[sid] = nil end
        end
    end
    return out
end

local function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end

-- The fort's infected, the hospital beds free, and the AI's sleepers (tended
-- here: see the top).
function survey(txt)
    local d = load_state()
    local t = now_tick()
    local tended = tend(d, t, false)
    save_state(d)
    local zones, staff = hospitals()
    local citizens = dfhack.units.getCitizens(true)
    local out = {infected = 0, untreated = 0, bleeding = 0, in_hospital = 0, idle_untreated = 0, max_load = 0,
                 worst = {}}
    local worst = {}
    for _, u in ipairs(citizens) do
        local c = candidate(u, zones, staff, d)
        if c.infected then
            out.infected = out.infected + 1
            if c.load >= INFECTION_BLEEDS then out.bleeding = out.bleeding + 1 end
            if c.load > out.max_load then out.max_load = c.load end
            if c.in_hospital then out.in_hospital = out.in_hospital + 1 end
            if not c.asked then
                out.untreated = out.untreated + 1
                if eligible(c) then out.idle_untreated = out.idle_untreated + 1 end
            end
            table.insert(worst, c)
        end
    end
    table.sort(worst, function(a, b) return a.load > b.load or (a.load == b.load and a.id < b.id) end)
    for i = 1, math.min(5, #worst) do
        local c = worst[i]
        table.insert(out.worst, {id = c.id, name = (txt or tostring)(dfhack.units.getReadableName(c.unit)),
                                 load = c.load, asked = c.asked or nil, in_hospital = c.in_hospital or nil})
    end
    local beds, total = free_beds(zones)
    out.beds, out.free_beds = total, #beds
    out.hospital_zones = count(zones)
    -- cleaning patients is the CLEAN labour; diagnosis DIAGNOSE (civilians only)
    out.cleaners = labor_count(citizens, 'CLEAN')
    out.diagnosers = labor_count(citizens, 'DIAGNOSE')
    -- the AI's sleepers: lying in now (undiagnosed), got up for nothing asked
    -- (in the last COOLDOWN_DAYS), and helped (DF asked a treatment)
    out.sleeping = tended.sleeping
    out.got_up_now = tended.got_up + tended.ended
    out.failed = count(d.cooldown)
    out.helped = count(d.helped)
    out.rest_days = REST_DAYS
    pcall(function() out.traction = traction_survey(zones) end)     -- (0.105.24)
    return out
end

-- Put idle infected citizens DF asks no treatment for to rest in a free
-- hospital bed they can walk to, the worst first; as dwarfvet does. At
-- most `max` now, `cap` of the AI's sleepers at once, `keep_free` beds left.
function rest_infected(max, dry_run, txt, cap, keep_free)
    cap, keep_free = cap or 3, keep_free or 2
    local d = load_state()
    local t = now_tick()
    local tended = tend(d, t, dry_run)
    local zones, staff = hospitals()
    if next(zones) == nil then return {ok = false, rejected = true, error = 'the fort has no hospital zone'} end
    local beds = free_beds(zones)
    local n = room(max, cap, keep_free, tended.sleeping, #beds)
    if n == 0 then
        if not dry_run then save_state(d) end
        return {ok = false, rejected = true, error = ('no room: %d of the AI\'s sleepers in bed (at most %d), %d bed(s) '
                .. 'free (%d kept for the doctors\' own patients)'):format(tended.sleeping, cap, #beds, keep_free)}
    end
    local cands = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local c = candidate(u, zones, staff, d)
        if c.infected then table.insert(cands, c) end
    end
    local picks = pick_patients(cands, #cands)
    if #picks == 0 then
        if not dry_run then save_state(d) end
        return {ok = false, rejected = true, error = 'no idle infected dwarf outside the hospital waits for care'}
    end
    local sent, used = {}, {}
    for _, c in ipairs(picks) do
        if #sent >= n then break end
        local u = c.unit
        local bed
        for i, b in ipairs(beds) do
            if not used[i] then
                local ok, walk = pcall(dfhack.maps.canWalkBetween, u.pos, xyz2pos(b.x, b.y, b.z))
                if ok and walk then bed = i break end
            end
        end
        if bed then
            local b = beds[bed]
            local name = (txt or tostring)(dfhack.units.getReadableName(u))
            local done, job_id = dry_run, nil
            if not dry_run then
                done = pcall(function()
                    local job = df.job:new()
                    dfhack.job.linkIntoWorld(job, true)
                    job.pos.x, job.pos.y, job.pos.z = b.x, b.y, b.z
                    job.flags.special = true
                    job.job_type = df.job_type.Rest
                    local gref = df.new(df.general_ref_unit_workerst)
                    gref.unit_id = u.id
                    job.general_refs:insert('#', gref)
                    u.job.current_job = job
                    job_id = job.id
                end)
                if done then d.sent[tostring(u.id)] = {tick = t, job = job_id} end
            end
            if done then
                used[bed] = true
                table.insert(sent, {unit_id = u.id, name = name, load = c.load})
            end
        end
    end
    if not dry_run then save_state(d) end
    if #sent == 0 then
        return {ok = false, rejected = true, error = 'no free hospital bed the infected can walk to'}
    end
    return {ok = true, dry_run = dry_run or nil, sent = sent}
end

-- A second doctor's post at a hospital (one doctor does every treatment):
-- made as lua/ai-society.lua add_posts makes the first (DF's own record), at
-- most two doctors a hospital. The staffing rule then fills it.
function add_doctor_post(loc_id, dry_run)
    local site = dfhack.world.getCurrentSite()
    local loc
    for _, b in ipairs(site and site.buildings or {}) do
        if b.id == loc_id then loc = b end
    end
    if not site or not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    if df.abstract_building_type[loc:getType()] ~= 'HOSPITAL' then
        return {ok = false, rejected = true, error = 'not a hospital'}
    end
    local n = 0
    for _, o in ipairs(loc.occupations) do
        if df.occupation_type[o.type] == 'DOCTOR' then n = n + 1 end
    end
    if n >= 2 then return {ok = false, rejected = true, error = 'the hospital has two doctors\' posts already'} end
    if dry_run then return {ok = true, dry_run = true, posts = n + 1} end
    local o = df.occupation:new()
    o.id = df.global.occupation_next_id
    o.type = df.occupation_type.DOCTOR
    o.histfig_id, o.unit_id = -1, -1
    o.location_id = loc.id
    o.site_id = site.id
    o.group_id = -1
    df.global.occupation_next_id = o.id + 1
    df.global.world.occupations.all:insert('#', o)
    loc.occupations:insert('#', o)
    return {ok = true, posts = n + 1}
end

-- --- (0.105.24) traction --------------------------------------------------------
--
-- Teacheroar (31 Oct - 1 Nov): a farmer waited 759-828 days "for immobilize,
-- traction" with a traction bench standing in the hospital and splints in
-- store; others waited 500+ days for immobilize alone. DF lays a patient who
-- needs traction on a traction bench when it picks where the patient rests;
-- one already lying in an ordinary bed (put there before the bench stood, or
-- when it was taken) keeps that bed, and the doctors never set the bone. So
-- such a patient is got up (the Rest job removed, as `tend` does), one at a
-- time while a finished bench in a hospital zone stands free, and DF picks
-- his resting place again. Not the same dwarf again for TRACTION_UP_DAYS.
TRACTION_UP_DAYS = 28
TRACTION_KEY = 'ai-overseer/traction-up'

local function needs_traction(u)
    local ok, r = pcall(function() return u.health ~= nil and u.health.flags.rq_traction == true end)
    return ok and r
end

-- the building at the dwarf's tile, by type name (Bed, TractionBench), or nil
local function lying_on(u)
    local ok, t = pcall(function()
        local b = dfhack.buildings.findAtTile(u.pos)
        return b and df.building_type[b:getType()] or nil
    end)
    return ok and t or nil
end

-- Pure: who to get up, lowest id first: needing traction, resting, on a
-- bed (not a bench), not got up lately; at most `max`.
function traction_picks(cands, max)
    local list = {}
    for _, c in ipairs(cands) do
        if c.traction and c.resting and c.on == 'Bed' and not c.up then table.insert(list, c) end
    end
    table.sort(list, function(a, b) return a.id < b.id end)
    local out = {}
    for i = 1, math.min(max or #list, #list) do out[i] = list[i] end
    return out
end

local function traction_state(t, dry_run)
    local ok, d = pcall(dfhack.persistent.getSiteData, TRACTION_KEY, {})
    d = ok and type(d) == 'table' and d or {}
    d.up = type(d.up) == 'table' and d.up or {}
    if not dry_run then
        for k, w in pairs(d.up) do
            if t < (tonumber(w) or 0) or t - (tonumber(w) or 0) >= TRACTION_UP_DAYS * DAY then d.up[k] = nil end
        end
    end
    return d
end

local function traction_cands(d)
    local out = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if needs_traction(u) then
            table.insert(out, {id = u.id, unit = u, traction = true, resting = rest_job(u) ~= nil,
                               on = lying_on(u), up = d.up[tostring(u.id)] ~= nil})
        end
    end
    return out
end

-- The report: patients who need traction, how many rest on a bed and on a
-- bench, and the free finished benches in the hospitals.
function traction_survey(zones)
    local d = traction_state(now_tick(), true)
    local out = {waiting = 0, in_bed = 0, on_bench = 0, got_up = 0}
    for _, c in ipairs(traction_cands(d)) do
        out.waiting = out.waiting + 1
        if c.resting and c.on == 'Bed' then out.in_bed = out.in_bed + 1 end
        if c.on == 'TractionBench' then out.on_bench = out.on_bench + 1 end
        if c.up then out.got_up = out.got_up + 1 end
    end
    local benches, total = free_beds(zones, 'TractionBench')
    out.benches, out.benches_free = total, #benches
    return out
end

-- Get up to `max` patients needing traction out of an ordinary bed while
-- a finished traction bench in a hospital zone stands free.
function traction_rest(max, dry_run, txt)
    local t = now_tick()
    local d = traction_state(t, dry_run)
    local zones = hospitals()
    if next(zones) == nil then return {ok = false, rejected = true, error = 'the fort has no hospital zone'} end
    local benches = free_beds(zones, 'TractionBench')
    if #benches == 0 then
        return {ok = false, rejected = true, error = 'no free, finished traction bench in a hospital zone'}
    end
    local picks = traction_picks(traction_cands(d), math.min(max or 1, #benches))
    if #picks == 0 then
        return {ok = false, rejected = true,
                error = 'no patient needing traction lies in an ordinary bed (or each was got up lately)'}
    end
    local up = {}
    for _, c in ipairs(picks) do
        local name = (txt or tostring)(dfhack.units.getReadableName(c.unit))
        local done = dry_run
        if not dry_run then
            local j = rest_job(c.unit)
            done = j ~= nil and pcall(dfhack.job.removeJob, j)
            if done then d.up[tostring(c.id)] = t end
        end
        if done then table.insert(up, {unit_id = c.id, name = name}) end
    end
    if not dry_run then pcall(dfhack.persistent.saveSiteData, TRACTION_KEY, d) end
    if #up == 0 then return {ok = false, error = 'the game kept them in bed (the Rest job could not be removed)'} end
    return {ok = true, dry_run = dry_run or nil, got_up = up, benches_free = #benches}
end
