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
-- here for citizens: an idle one with an infected wound and no treatment
-- asked is put to rest in a free hospital bed (the worst infections first).
-- Whether DF keeps a walking dwarf resting there is watched (`stayed`,
-- `asked`) and said, so the planner stops when it doesn't work.
--@module = true

local INFECTION_BLEEDS = 300            -- df-structures: ">=300 causes bleeding"
local RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
            'rq_setting', 'rq_traction', 'rq_crutch'}
local SENT_DAYS = 7

-- dwarves the AI put to rest: unit id (number) -> game tick (survives calls;
-- a reloaded script forgets, which only restarts the count)
SENT = SENT or {}

local function now_tick()
    return df.global.cur_year * 403200 + df.global.cur_year_tick
end

-- Pure: the candidates to send, best first. Each: {id, load, infected,
-- asked, in_hospital, idle, soldier, child, mood, sent}. Only an idle grown
-- citizen with an infected wound, no treatment asked, outside the hospitals,
-- not a soldier, not in a mood, not sent lately; bleeding (load >= 300)
-- first, then the heavier infection, ties to the lower id.
function pick_patients(cands, max)
    local list = {}
    for _, c in ipairs(cands) do
        if c.infected and not c.asked and not c.in_hospital and c.idle and not c.soldier
                and not c.child and not c.mood and not c.sent then
            table.insert(list, c)
        end
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

-- --- the game -----------------------------------------------------------------

local function hospital_zones()
    local zones = {}
    local site = dfhack.world.getCurrentSite()
    for _, loc in ipairs(site and site.buildings or {}) do
        if df.abstract_building_type[loc:getType()] == 'HOSPITAL' then
            local c = loc:getContents()
            for _, bid in ipairs(c and c.building_ids or {}) do
                local z = df.building.find(bid)
                if z then zones[z.id] = z end
            end
        end
    end
    return zones
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

local function resting(u)
    local ok, r = pcall(function()
        local j = u.job.current_job
        return j ~= nil and j.job_type == df.job_type.Rest
    end)
    return ok and r
end

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

-- The hospital zones' finished beds nobody lies in or is on the way to.
local function free_beds(zones, citizens)
    local taken = {}
    for _, u in ipairs(citizens) do
        pcall(function() taken[key(u.pos.x, u.pos.y, u.pos.z)] = true end)
        pcall(function()
            local j = u.job.current_job
            if j and j.job_type == df.job_type.Rest then taken[key(j.pos.x, j.pos.y, j.pos.z)] = true end
        end)
    end
    local beds, total = {}, 0
    for _, z in pairs(zones) do
        pcall(function()
            for _, b in ipairs(z.contained_buildings) do
                if df.building_type[b:getType()] == 'Bed' then
                    local done = true
                    pcall(function() done = b:getBuildStage() >= b:getMaxBuildStage() end)
                    if done then
                        total = total + 1
                        if not taken[key(b.centerx, b.centery, b.z)] then
                            table.insert(beds, {x = b.centerx, y = b.centery, z = b.z})
                        end
                    end
                end
            end
        end)
    end
    return beds, total
end

local function candidate(u, zones)
    local c = {id = u.id, unit = u, infected = infected(u), asked = asked(u), load = load_of(u)}
    if not c.infected then return c end
    c.in_hospital = in_hospital(u, zones)
    pcall(function() c.idle = u.job.current_job == nil end)
    c.soldier = u.military.squad_id ~= -1
    pcall(function() c.child = not dfhack.units.isAdult(u) end)
    pcall(function() c.mood = u.mood ~= nil and u.mood ~= -1 end)
    c.sent = SENT[u.id] ~= nil
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

-- Read only: the fort's infected, the hospital beds free, and how those the
-- AI put to rest are doing.
function survey(txt)
    local zones = hospital_zones()
    local citizens = dfhack.units.getCitizens(true)
    local out = {infected = 0, untreated = 0, bleeding = 0, in_hospital = 0, idle_untreated = 0, max_load = 0,
                 worst = {}, sent = 0, stayed = 0, asked = 0}
    local worst = {}
    for _, u in ipairs(citizens) do
        local c = candidate(u, zones)
        if c.infected then
            out.infected = out.infected + 1
            if c.load >= INFECTION_BLEEDS then out.bleeding = out.bleeding + 1 end
            if c.load > out.max_load then out.max_load = c.load end
            if c.in_hospital then out.in_hospital = out.in_hospital + 1 end
            if not c.asked then
                out.untreated = out.untreated + 1
                if #pick_patients({c}, 1) == 1 then out.idle_untreated = out.idle_untreated + 1 end
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
    local beds, total = free_beds(zones, citizens)
    out.beds, out.free_beds = total, #beds
    local n = 0
    for _ in pairs(zones) do n = n + 1 end
    out.hospital_zones = n
    -- cleaning patients is the CLEAN labour; diagnosis DIAGNOSE (civilians only)
    out.cleaners = labor_count(citizens, 'CLEAN')
    out.diagnosers = labor_count(citizens, 'DIAGNOSE')
    -- those the AI put to rest: still resting (in the bed or on the way), or
    -- asked a treatment since
    local t = now_tick()
    for id, when in pairs(SENT) do
        local u = df.unit.find(id)
        local oka, alive = pcall(function() return dfhack.units.isAlive(u) end)
        if not u or t - when > SENT_DAYS * 1200 or t < when or (oka and not alive) then
            SENT[id] = nil
        else
            out.sent = out.sent + 1
            if asked(u) then out.asked = out.asked + 1
            elseif resting(u) then out.stayed = out.stayed + 1 end
        end
    end
    return out
end

-- Put up to `max` idle infected citizens (no treatment asked) to rest in a
-- free hospital bed they can walk to, the worst first; as dwarfvet does.
function rest_infected(max, dry_run, txt)
    local zones = hospital_zones()
    if next(zones) == nil then return {ok = false, rejected = true, error = 'the fort has no hospital zone'} end
    local citizens = dfhack.units.getCitizens(true)
    local beds = free_beds(zones, citizens)
    if #beds == 0 then return {ok = false, rejected = true, error = 'no free hospital bed'} end
    local cands = {}
    for _, u in ipairs(citizens) do
        local c = candidate(u, zones)
        if c.infected then table.insert(cands, c) end
    end
    local picks = pick_patients(cands, #cands)
    if #picks == 0 then
        return {ok = false, rejected = true, error = 'no idle infected dwarf outside the hospital waits for care'}
    end
    local sent, used = {}, {}
    for _, c in ipairs(picks) do
        if #sent >= max then break end
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
            local done = dry_run
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
                end)
                if done then SENT[u.id] = now_tick() end
            end
            if done then
                used[bed] = true
                table.insert(sent, {unit_id = u.id, name = name, load = c.load})
            end
        end
    end
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
