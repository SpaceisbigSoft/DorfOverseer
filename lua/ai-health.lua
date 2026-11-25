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

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

local INFECTION_BLEEDS = 300            -- df-structures: ">=300 causes bleeding"
local RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
            'rq_setting', 'rq_traction', 'rq_crutch'}
REST_DAYS = 3                -- a sleeper with no treatment asked after this many days is got up
COOLDOWN_DAYS = 28           -- ...and not sent again for this many
STATE_KEY = 'ai-overseer/infected-rest'
local DAY = 1200

local function now_tick() return U.abs_tick() end             -- (r6) not protected: an error goes to the caller

-- the save's record: sent = {id = {tick, job}}, cooldown = {id = tick} (got
-- up with nothing asked), helped = {id = tick} (DF asked a treatment)
local function load_state()
    local d = U.site_get(STATE_KEY, {})
    for _, k in ipairs({'sent', 'cooldown', 'helped'}) do
        d[k] = type(d[k]) == 'table' and d[k] or {}
    end
    return d
end

local function save_state(d)
    U.site_put(STATE_KEY, d)
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

-- (0.105.94) A heavy infection (load HEAVY_LOAD or more) is sent busy or
-- unhappy too: its job given up first (rest_infected). Live 23 Nov, B: 7
-- infected, all at work or unhappy, none ever sent (idle_untreated 0, 6 beds
-- free) while tantrums strangled the weakened (Kubuk, load 118, by a child).
HEAVY_LOAD = 60
local HEAVY_PASS = {unhappy = true}

function eligible(c)
    if not (c.infected and c.care) then return false end
    local heavy = (c.load or 0) >= HEAVY_LOAD
    if not (c.idle or heavy) then return false end
    for _, k in ipairs(BARS) do
        if c[k] and not (heavy and HEAVY_PASS[k]) then return false end
    end
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

-- (0.105.94) every infected wound already diagnosed: DF counts it treated.
-- Live 23 Nov, B (probe-beds-who): all 7 infected had their infected wound
-- flagged diagnosed (most sutured too, some years old), no treatment asked,
-- needs_healthcare false: no doctor sees them and the bed rule (it wants
-- needs_healthcare) can't send them; free beds were not what held them.
local function diagnosed_only(u)
    local ok, r = pcall(function()
        local any = false
        for _, w in ipairs(u.body.wounds) do
            if w.flags.infection then
                any = true
                if not w.flags.diagnosed then return false end
            end
        end
        return any
    end)
    return ok and r or false
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
        for _, u in ipairs(report_units()) do
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
    c.diagnosed = diagnosed_only(u)                      -- (0.105.94)
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

-- (0.105.33) tend() only ever drops entries (and notes a dropped sleeper in
-- cooldown/helped), so the counts tell whether it changed anything
local function state_sig(d)
    return count(d.sent or {}) .. '/' .. count(d.cooldown or {}) .. '/' .. count(d.helped or {})
end

-- The fort's infected, the hospital beds free, and the AI's sleepers (tended
-- here: see the top).
function survey(txt)
    local d = load_state()
    local t = now_tick()
    local before = state_sig(d)
    local tended = tend(d, t, false)
    if state_sig(d) ~= before then save_state(d) end      -- (0.105.33) only on a change
    local zones, staff = hospitals()
    local citizens = report_citizens(true)
    local out = {infected = 0, untreated = 0, bleeding = 0, in_hospital = 0, idle_untreated = 0, max_load = 0,
                 not_patients = 0, chronic = 0, worst = {}}
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
                -- (0.105.94) not DF's patient: the bed rule can't send them;
                -- chronic: every infected wound already diagnosed
                if not c.care then
                    out.not_patients = out.not_patients + 1
                    if c.diagnosed then out.chronic = out.chronic + 1 end
                end
            end
            table.insert(worst, c)
        end
    end
    table.sort(worst, function(a, b) return a.load > b.load or (a.load == b.load and a.id < b.id) end)
    for i = 1, math.min(5, #worst) do
        local c = worst[i]
        table.insert(out.worst, {id = c.id, name = (txt or tostring)(dfhack.units.getReadableName(c.unit)),
                                 load = c.load, asked = c.asked or nil, in_hospital = c.in_hospital or nil,
                                 patient = c.care or nil, diagnosed = c.diagnosed or nil})
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
    -- (item5) the wounded up and working: who waits for bed rest and why
    local okb, bed = pcall(bed_survey, zones, staff, citizens, txt)
    out.bed = okb and bed or {error = tostring(bed)}
    return out
end

-- The special Rest job DFHack's dwarfvet gives an injured animal, on bed
-- `b` ({x, y, z}): DF's doctors come to a patient resting in a hospital bed.
-- Returns whether it was made, and the job's id.
local function give_rest(u, b)
    local job_id
    local done = pcall(function()
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
    return done, job_id
end

-- Put idle infected citizens DF asks no treatment for to rest in a free
-- hospital bed they can walk to, the worst first; as dwarfvet does. At
-- most `max` now, `cap` of the AI's sleepers at once, `keep_free` beds left.
REST_THIRST = 20000          -- (0.105.33) as the calm burrow: drink first
REST_HUNGER = 40000
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
    for _, u in ipairs(report_citizens(true)) do
        local c = candidate(u, zones, staff, d)
        if c.infected then table.insert(cands, c) end
    end
    local picks = pick_patients(cands, #cands)
    if #picks == 0 then
        if not dry_run then save_state(d) end
        return {ok = false, rejected = true, error = 'no idle infected dwarf (nor a badly infected one at work) outside the hospital waits for care'}
    end
    local sent, used = {}, {}
    for _, c in ipairs(picks) do
        if #sent >= n then break end
        local u = c.unit
        -- (0.105.33) never one already thirsty or hungry into a 3-day rest
        local okd, dry = pcall(function()
            return u.counters2.thirst_timer >= REST_THIRST or u.counters2.hunger_timer >= REST_HUNGER
        end)
        if okd and dry then goto next_pick end
        -- (0.105.94) a heavy infection at work: its job given up first (as
        -- DF's own interruptions do), else it is passed over
        if u.job.current_job and not dry_run then
            pcall(function() dfhack.job.removeWorker(u.job.current_job, 0) end)
            if u.job.current_job then goto next_pick end
        end
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
                done, job_id = give_rest(u, b)
                if done then d.sent[tostring(u.id)] = {tick = t, job = job_id} end
            end
            if done then
                used[bed] = true
                table.insert(sent, {unit_id = u.id, name = name, load = c.load})
            end
        end
        ::next_pick::
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
    local d = U.site_get(TRACTION_KEY, {})
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
    for _, u in ipairs(report_citizens(true)) do
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
    if not dry_run then U.site_put(TRACTION_KEY, d) end
    if #up == 0 then return {ok = false, error = 'the game kept them in bed (the Rest job could not be removed)'} end
    return {ok = true, dry_run = dry_run or nil, got_up = up, benches_free = #benches}
end

-- (0.105.94) DESIGN ONLY, never called by the planner (no bridge action):
-- what a re-diagnosis of a chronic heavy infection would change. DF asks a
-- treatment (rq_cleaning, rq_surgery...) only at a diagnosis, and a wound
-- flagged diagnosed is not diagnosed again; the idea is to clear the
-- infected wounds' diagnosed flags (the wound's and its parts') and set the
-- patient's rq_diagnosis and needs_healthcare, as a new wound does. Unproven:
-- run a live trial on one dwarf (a save first) before any use. With
-- dry_run (the default, anything but false) it only reports. (item5) The
-- live trial, bounded and undone when it fails, is bed_rest's 'rediag'.
function rediagnose(ids, dry_run, min_load)
    dry_run = dry_run ~= false
    min_load = min_load or HEAVY_LOAD
    local out = {ok = true, dry_run = dry_run or nil, units = {}}
    for _, id in ipairs(ids or {}) do
        local u = df.unit.find(id)
        local row = {id = id}
        if not u then
            row.skip = 'no such unit'
        elseif load_of(u) < min_load then
            row.skip = 'load ' .. load_of(u) .. ' under ' .. min_load
        elseif asked(u) then
            row.skip = 'a treatment is asked already'
        elseif not u.health then
            row.skip = 'no health record (DF keeps one only for a unit hurt once)'
        else
            row.wounds = {}
            for _, w in ipairs(u.body.wounds) do
                if w.flags.infection and w.flags.diagnosed then
                    table.insert(row.wounds, w.id)
                    if not dry_run then
                        w.flags.diagnosed = false
                        for _, p in ipairs(w.parts) do
                            pcall(function() p.flags1.diagnosed = false end)   -- whichever set holds it
                            pcall(function() p.flags2.diagnosed = false end)
                        end
                    end
                end
            end
            row.would_set = {'rq_diagnosis', 'needs_healthcare'}
            if not dry_run and #row.wounds > 0 then
                u.health.flags.rq_diagnosis = true
                u.health.flags.needs_healthcare = true
            end
        end
        table.insert(out.units, row)
    end
    return out
end

-- --- (item5) bed rest for the wounded who are up and working --------------------
--
-- B, 24 Nov: Zutthan waited 126 days "for immobilize, dressing, surgery",
-- walking about and working, and died; the chief medical dwarf, two surgeons,
-- a doctor and the militia captain all walk about with infected wounds (live,
-- probe i5-health-flags: every infected wound and its parts flagged diagnosed
-- years ago, sutured, no rq_ flag, needs_healthcare false: DF counts them
-- treated; loads 1-105). DF's doctors treat a patient resting in a bed; one up
-- and working is passed by. What DF/DFHack offer, and why this way:
--   * a special Rest job on a free hospital bed, as DFHack's dwarfvet gives an
--     injured animal so DF's doctors treat it (the job rest_infected makes):
--     DF's own job, undone by dfhack.job.removeJob, nothing else written. Chosen.
--   * the hospital burrow only keeps a walking patient inside the zones (he
--     works on there); needs_healthcare alone asks nothing of a dwarf already
--     diagnosed (DF's doctors go by the rq_ flags, asked at a diagnosis, and a
--     wound flagged diagnosed is not diagnosed again).
-- So (a) 'treat': a citizen DF asked a treatment for (any rq_ flag) who isn't
-- resting gets that Rest job; kept in bed while treatments go on, got up after
-- TREAT_DAYS with none given, or once none is left. (b) 'rediag', a trial (one
-- dwarf at a time): a heavy chronic infection (every infected wound diagnosed,
-- nothing asked, load REDIAG_LOAD or more) has its infected wounds' diagnosed
-- flags cleared and rq_diagnosis + needs_healthcare set, as a fresh wound has
-- them, then the Rest job; if DF asks no treatment within REDIAG_DAYS, every
-- flag is put back as it was and he is got up (the planner stops trying after
-- a few such failures). Never sent: the thirsty or hungry (and a sleeper is got
-- up once thirst or hunger pass BED_THIRST_UP / BED_HUNGER_UP: B's patients
-- died of thirst in bed), a soldier, one in a mood, a tantrum, mad or caged,
-- nor the last dwarf able to diagnose. When no dwarf with the DIAGNOSE labour
-- is both able and healthy, the able citizen best at it is given the labour
-- (through the work details, ai-labor give_labor).
BED_KEY = 'ai-overseer/bed-rest'
TREAT_DAYS = 14              -- in bed this long with no treatment given: got up
REDIAG_DAYS = 3              -- a trial with nothing asked after this long: undone
REDIAG_LOAD = HEAVY_LOAD
BED_COOLDOWN_DAYS = 28       -- not sent again for this long after a failure
BED_SHORT_DAYS = 3           -- ...after getting up to drink, or DF ending the rest
BED_THIRST_UP = 30000        -- a sleeper this thirsty (or hungry) is got up to drink and eat
BED_HUNGER_UP = 50000

local function rq_list(u)
    local out = {}
    pcall(function()
        local f = u.health and u.health.flags
        if not f then return end
        for _, k in ipairs(RQ) do if f[k] then table.insert(out, k) end end
    end)
    return out
end

local function bed_state()
    local d = U.site_get(BED_KEY, {})
    for _, k in ipairs({'sent', 'cooldown', 'stats'}) do
        d[k] = type(d[k]) == 'table' and d[k] or {}
    end
    return d
end

local function bump(d, k) d.stats[k] = (tonumber(d.stats[k]) or 0) + 1 end

local function bed_sig(d)
    local n, kinds = 0, ''
    for sid, e in pairs(d.sent) do n = n + 1; kinds = kinds .. sid .. (type(e) == 'table' and tostring(e.kind) .. tostring(e.sig) or '') end
    local s = 0
    for _, v in pairs(d.stats) do s = s + (tonumber(v) or 0) end
    return n .. '/' .. count(d.cooldown) .. '/' .. s .. '/' .. kinds
end

-- the trial's flags: each infected, diagnosed wound (and its diagnosed parts)
-- made undiagnosed, rq_diagnosis and needs_healthcare set; the record says
-- what to put back
local function trial_start(u, rec)
    for _, w in ipairs(u.body.wounds) do
        if w.flags.infection and w.flags.diagnosed then
            local r = {id = w.id, parts = {}}
            table.insert(rec, r)                  -- recorded first: a failure part-way is undone too
            for i, p in ipairs(w.parts) do
                local ok, v = pcall(function() return p.flags1.diagnosed end)
                if ok and v then
                    table.insert(r.parts, i)
                    p.flags1.diagnosed = false
                end
            end
            w.flags.diagnosed = false
        end
    end
    u.health.flags.rq_diagnosis = true
    u.health.flags.needs_healthcare = true
end

local function trial_undo(u, rec)
    pcall(function()
        local by = {}
        for _, r in ipairs(rec or {}) do if type(r) == 'table' then by[tonumber(r.id)] = r end end
        for _, w in ipairs(u.body.wounds) do
            local r = by[w.id]
            if r then
                local parts = {}
                for _, i in ipairs(r.parts or {}) do parts[tonumber(i)] = true end
                for i, p in ipairs(w.parts) do
                    if parts[i] then pcall(function() p.flags1.diagnosed = true end) end
                end
                w.flags.diagnosed = true
            end
        end
        u.health.flags.rq_diagnosis = false
        u.health.flags.needs_healthcare = false
    end)
end

local function too_dry(u, thirst, hunger)
    local ok, dry = pcall(function()
        return u.counters2.thirst_timer >= thirst or u.counters2.hunger_timer >= hunger
    end)
    return ok and dry
end

-- The AI's bed-rest sleepers tended (see the top). Returns the counts;
-- `dry_run` changes nothing.
local function bed_tend(d, t, dry_run)
    local out = {sleeping = 0, trials = 0}
    for sid, e in pairs(d.sent) do
        e = type(e) == 'table' and e or {}
        local u = df.unit.find(tonumber(sid))
        local oka, alive = pcall(function() return dfhack.units.isAlive(u) end)
        local when = tonumber(e.tick) or t
        local function drop(days, stat)
            if dry_run then return end
            d.sent[sid] = nil
            if days then d.cooldown[sid] = t + days * DAY end
            if stat then bump(d, stat) end
        end
        if not u or (oka and not alive) or t < when then
            drop()
        else
            local rq = rq_list(u)
            local j = rest_job(u)
            local mine = tonumber(e.job)
            local own = j ~= nil and mine ~= nil and j.id == mine
            local function get_up() if own and not dry_run then pcall(dfhack.job.removeJob, j) end end
            local sig = table.concat(rq, ',')
            if e.kind == 'rediag' and sig ~= '' and sig ~= 'rq_diagnosis' then
                -- DF diagnosed him and asked a treatment: a patient now
                if not dry_run then
                    bump(d, 'rediag_helped')
                    e.kind, e.sig, e.last, e.wounds = 'treat', sig, t, nil
                end
                out.sleeping = out.sleeping + 1
            elseif e.kind == 'rediag' and sig == '' then
                -- diagnosed again, nothing asked: the old flags put back as they were
                if not dry_run then trial_undo(u, e.wounds) end
                get_up()
                drop(BED_COOLDOWN_DAYS, 'rediag_failed')
            elseif e.kind == 'rediag' and (not j or t - when >= REDIAG_DAYS * DAY
                                           or too_dry(u, BED_THIRST_UP, BED_HUNGER_UP)) then
                -- never diagnosed (or up to drink, or DF ended the rest): undone
                if not dry_run then trial_undo(u, e.wounds) end
                get_up()
                local failed = t - when >= REDIAG_DAYS * DAY
                drop(failed and BED_COOLDOWN_DAYS or BED_SHORT_DAYS, failed and 'rediag_failed' or 'trial_cut')
            elseif e.kind == 'rediag' then
                out.sleeping, out.trials = out.sleeping + 1, out.trials + 1
            elseif sig == '' then
                get_up()                              -- every treatment given
                drop(nil, 'treated')
            elseif j and not own then
                drop()                                -- DF rests him itself now
            elseif not j then
                drop(BED_SHORT_DAYS, 'ended')         -- DF ended the rest
            elseif too_dry(u, BED_THIRST_UP, BED_HUNGER_UP) then
                get_up()
                drop(BED_SHORT_DAYS, 'drink_up')
            else
                if sig ~= e.sig and not dry_run then e.sig, e.last = sig, t end   -- a treatment given
                if t - (tonumber(e.last) or when) >= TREAT_DAYS * DAY and sig == e.sig then
                    get_up()
                    drop(BED_COOLDOWN_DAYS, 'stalled')
                else
                    out.sleeping = out.sleeping + 1
                end
            end
        end
    end
    if not dry_run then
        for sid, w in pairs(d.cooldown) do
            if t >= (tonumber(w) or 0) or (tonumber(w) or 0) - t > BED_COOLDOWN_DAYS * DAY then d.cooldown[sid] = nil end
        end
    end
    return out
end

local function bed_cand(u, zones, staff, d, t)
    local c = {id = u.id, unit = u, rq = rq_list(u), load = load_of(u), infected = infected(u)}
    pcall(function() c.care = u.health ~= nil and u.health.flags.needs_healthcare == true end)
    c.chronic = c.infected and #c.rq == 0 and not c.care and diagnosed_only(u)
    c.resting = rest_job(u) ~= nil
    pcall(function() c.job = u.job.current_job and tostring(df.job_type[u.job.current_job.job_type]) or nil end)
    c.soldier = false
    pcall(function() c.soldier = u.military.squad_id ~= -1 end)
    pcall(function() c.child = not dfhack.units.isAdult(u) end)
    pcall(function() c.mood = u.mood ~= nil and u.mood ~= -1 end)
    c.tantrum = in_tantrum(u)
    pcall(function() c.insane = dfhack.units.isSane(u) == false end)
    pcall(function() c.restrained = u.flags1.caged or u.flags1.chained end)
    pcall(function() c.down = u.flags1.on_ground == true end)    -- where he fell: DF's rescuers carry him
    pcall(function() local cat = dfhack.units.getStressCategory(u); c.miserable = type(cat) == 'number' and cat <= 1 end)
    c.thirsty = too_dry(u, REST_THIRST, REST_HUNGER)
    c.sent = d.sent[tostring(u.id)] ~= nil
    local cd = tonumber(d.cooldown[tostring(u.id)])
    c.cooldown = cd ~= nil and t < cd
    pcall(function() c.diagnoser = u.status.labors[df.unit_labor.DIAGNOSE] == true end)
    pcall(function() c.skill = dfhack.units.getNominalSkill(u, df.job_skill.DIAGNOSE, true) end)
    c.staff = staff[u.id] == true
    return c
end

-- Pure: the kind of bed rest a citizen waits for ('treat', 'rediag') or nil;
-- with a kind, the bar that keeps him from it (nil if none).
BED_BARS = {'resting', 'sent', 'down', 'soldier', 'mood', 'tantrum', 'insane', 'restrained', 'thirsty', 'cooldown'}
function bed_kind(c, rediag)
    local kind
    if #(c.rq or {}) > 0 then kind = 'treat'
    elseif rediag and c.chronic and (c.load or 0) >= REDIAG_LOAD then kind = 'rediag'
    else return nil end
    for _, k in ipairs(BED_BARS) do if c[k] then return kind, k end end
    return kind, nil
end

-- Pure: one who can do a diagnosis now (the labour, up, sane, no soldier)
function able_diagnoser(c)
    return c.diagnoser == true and not (c.soldier or c.child or c.resting or c.sent or c.insane or c.tantrum
                                        or c.mood or c.restrained or c.down)
end

function healthy_diagnoser(c)
    return able_diagnoser(c) and #(c.rq or {}) == 0 and (c.load or 0) < REDIAG_LOAD
end

-- Pure: who goes to bed, at most `max`: those DF asked a treatment for
-- first, then the trials (one at a time, `trials` already in bed); among
-- them the healers first, the healthiest of them first (soonest back at
-- work), the others by the heavier infection and the more treatments. The
-- last dwarf able to diagnose stays up (returned as kept).
function bed_picks(cands, max, rediag, trials)
    local able = 0
    for _, c in ipairs(cands) do if able_diagnoser(c) then able = able + 1 end end
    local list = {}
    for _, c in ipairs(cands) do
        local kind, bar = bed_kind(c, rediag)
        if kind and not bar then c.kind = kind; table.insert(list, c) end
    end
    local function healer(c) return (c.diagnoser or c.staff) and true or false end
    table.sort(list, function(a, b)
        if (a.kind == 'treat') ~= (b.kind == 'treat') then return a.kind == 'treat' end
        local ha, hb = healer(a), healer(b)
        if ha ~= hb then return ha end
        local la, lb, na, nb = a.load or 0, b.load or 0, #(a.rq or {}), #(b.rq or {})
        if ha then
            if na ~= nb then return na < nb end
            if la ~= lb then return la < lb end
        else
            if la ~= lb then return la > lb end
            if na ~= nb then return na > nb end
        end
        return a.id < b.id
    end)
    local out, kept = {}, {}
    trials = trials or 0
    for _, c in ipairs(list) do
        if #out >= (max or 0) then break end
        if able_diagnoser(c) and able <= 1 then
            table.insert(kept, c)
        elseif c.kind == 'rediag' and trials >= 1 then
            -- one trial at a time
        else
            if able_diagnoser(c) then able = able - 1 end
            if c.kind == 'rediag' then trials = trials + 1 end
            table.insert(out, c)
        end
    end
    return out, kept
end

-- Pure: the citizen given the DIAGNOSE labour when no able dwarf with it is
-- healthy: up, grown, sane, no soldier, not miserable, no treatment asked,
-- no heavy infection; the best at diagnosing, ties to the lower id. nil if a
-- healthy diagnoser stands or nobody fits.
function healer_pick(cands)
    for _, c in ipairs(cands) do if healthy_diagnoser(c) then return nil end end
    local best
    for _, c in ipairs(cands) do
        local fit = not (c.diagnoser or c.child or c.soldier or c.insane or c.tantrum or c.mood or c.restrained
                         or c.resting or c.sent or c.miserable or c.down) and #(c.rq or {}) == 0 and (c.load or 0) < REDIAG_LOAD
        if fit and (not best or (c.skill or 0) > (best.skill or 0)
                    or ((c.skill or 0) == (best.skill or 0) and c.id < best.id)) then
            best = c
        end
    end
    return best
end

local BAR_WORDS = {resting = 'resting already', sent = 'put to bed by the AI', soldier = 'a soldier',
                   down = 'lying where he fell (for DF\'s rescuers)',
                   mood = 'in a strange mood', tantrum = 'in a tantrum', insane = 'mad', restrained = 'caged or chained',
                   thirsty = 'thirsty or hungry (drink first)', cooldown = 'got up lately (waits a while)'}

-- The report's part: who waits for bed rest and why, the healers, the
-- AI's sleepers (tended here, as survey tends rest_infected's).
function bed_survey(zones, staff, citizens, txt)
    local d = bed_state()
    local t = now_tick()
    local before = bed_sig(d)
    local tended = bed_tend(d, t, false)
    if bed_sig(d) ~= before then save_state_bed(d) end
    local out = {treat_waiting = 0, rediag_waiting = 0, ready_treat = 0, ready_rediag = 0, able_diagnosers = 0,
                 healthy_diagnosers = 0, sleeping = tended.sleeping, trials = tended.trials, who = {},
                 stats = d.stats, treat_days = TREAT_DAYS, rediag_days = REDIAG_DAYS, rediag_load = REDIAG_LOAD}
    local cands, rows = {}, {}
    for _, u in ipairs(citizens) do
        local c = bed_cand(u, zones, staff, d, t)
        table.insert(cands, c)
        if able_diagnoser(c) then out.able_diagnosers = out.able_diagnosers + 1 end
        if healthy_diagnoser(c) then out.healthy_diagnosers = out.healthy_diagnosers + 1 end
        local kind, bar = bed_kind(c, true)
        if kind and bar ~= 'resting' and bar ~= 'sent' then
            out[kind .. '_waiting'] = out[kind .. '_waiting'] + 1
            if not bar then out['ready_' .. kind] = out['ready_' .. kind] + 1 end
            table.insert(rows, {c = c, kind = kind, bar = bar})
        end
    end
    table.sort(rows, function(a, b)
        if (a.kind == 'treat') ~= (b.kind == 'treat') then return a.kind == 'treat' end
        if (a.c.load or 0) ~= (b.c.load or 0) then return (a.c.load or 0) > (b.c.load or 0) end
        return a.c.id < b.c.id
    end)
    for i = 1, math.min(6, #rows) do
        local r = rows[i]
        local needs = {}
        for _, k in ipairs(r.c.rq) do table.insert(needs, (k:gsub('^rq_', ''))) end
        table.insert(out.who, {id = r.c.id, name = (txt or tostring)(dfhack.units.getReadableName(r.c.unit)),
                               kind = r.kind, load = r.c.load, needs = needs, healer = (r.c.diagnoser or r.c.staff) or nil,
                               why = r.bar and BAR_WORDS[r.bar] or (r.c.job and ('up, at work (' .. r.c.job .. ')')
                                                                   or 'up, idle')})
    end
    local h = healer_pick(cands)
    if h then out.healer_candidate = {id = h.id, skill = h.skill or 0} end
    return out
end

function save_state_bed(d) U.site_put(BED_KEY, d) end

-- Put up to `max` of the wounded up and working to bed (see the top): at most
-- `cap` of the AI's sleepers (this and rest_infected's) at once, `keep_free`
-- beds left; `rediag` allows the trial. First, when no healthy dwarf able to
-- diagnose stands, one is given the labour.
function bed_rest(max, dry_run, txt, cap, keep_free, rediag)
    cap, keep_free = cap or 3, keep_free or 2
    local d = bed_state()
    local t = now_tick()
    local tended = bed_tend(d, t, dry_run)
    local zones, staff = hospitals()
    if next(zones) == nil then
        if not dry_run then save_state_bed(d) end
        return {ok = false, rejected = true, error = 'the fort has no hospital zone'}
    end
    local cands = {}
    for _, u in ipairs(report_citizens(true)) do table.insert(cands, bed_cand(u, zones, staff, d, t)) end
    local out = {ok = true, dry_run = dry_run or nil, sent = {}, kept = {}}
    local h = healer_pick(cands)
    if h then
        local given = dry_run
        if not dry_run then
            local ok, r = pcall(function() return reqscript('ai-labor').give_labor(h.unit, 'DIAGNOSE') end)
            given = ok and r == true
        end
        if given then
            h.diagnoser = true
            out.healer = {unit_id = h.id, name = (txt or tostring)(dfhack.units.getReadableName(h.unit)), skill = h.skill or 0}
        end
    end
    local beds = free_beds(zones)
    local others = count(load_state().sent)              -- rest_infected's sleepers share the cap
    local n = room(max, cap, keep_free, tended.sleeping + others, #beds)
    local picks, kept = bed_picks(cands, n, rediag, tended.trials)
    for _, c in ipairs(kept) do
        table.insert(out.kept, {unit_id = c.id, name = (txt or tostring)(dfhack.units.getReadableName(c.unit))})
    end
    local used = {}
    for _, c in ipairs(picks) do
        local u = c.unit
        if u.job.current_job and not dry_run then
            pcall(function() dfhack.job.removeWorker(u.job.current_job, 0) end)
            if u.job.current_job then goto next_pick end
        end
        do
            local bed
            for i, b in ipairs(beds) do
                if not used[i] then
                    local ok, walk = pcall(dfhack.maps.canWalkBetween, u.pos, xyz2pos(b.x, b.y, b.z))
                    if ok and walk then bed = i break end
                end
            end
            if bed then
                local done, job_id, rec = dry_run, nil, nil
                if not dry_run then
                    if c.kind == 'rediag' then
                        rec = {}
                        done = pcall(trial_start, u, rec)
                        if not done then trial_undo(u, rec) end
                    else
                        done = true
                    end
                    if done then
                        done, job_id = give_rest(u, beds[bed])
                        if not done and rec then trial_undo(u, rec) end
                    end
                    if done then
                        d.sent[tostring(u.id)] = {tick = t, job = job_id, kind = c.kind, sig = table.concat(c.rq, ','),
                                                  last = t, wounds = rec}
                        if c.kind == 'rediag' then bump(d, 'rediag_tried') end
                    end
                end
                if done then
                    used[bed] = true
                    local needs = {}
                    for _, k in ipairs(c.rq) do table.insert(needs, (k:gsub('^rq_', ''))) end
                    table.insert(out.sent, {unit_id = u.id, name = (txt or tostring)(dfhack.units.getReadableName(u)),
                                            kind = c.kind, load = c.load, needs = needs})
                end
            end
        end
        ::next_pick::
    end
    if not dry_run then save_state_bed(d) end
    if #out.sent == 0 and not out.healer then
        local why
        if n == 0 then
            why = ('no room: %d of the AI\'s sleepers in bed (at most %d), %d bed(s) free (%d kept for the doctors\' '
                   .. 'own patients)'):format(tended.sleeping + others, cap, #beds, keep_free)
        elseif #picks == 0 then
            why = #kept > 0 and 'the only one waiting is the last dwarf able to diagnose: kept up'
                  or 'nobody up and working waits for a treatment (or each is barred: thirsty, a soldier, raging...)'
        else
            why = 'no free hospital bed they can walk to'
        end
        return {ok = false, rejected = true, error = why, kept = out.kept}
    end
    return out
end
