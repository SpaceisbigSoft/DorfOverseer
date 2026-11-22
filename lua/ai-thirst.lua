-- (0.105.46, I2) The thirst watch: each thirsty citizen, why they don't
-- drink, and every death of thirst with the last reason known.
--
-- Why (the 8-13 Nov run): 186 died of thirst over the six forts (A 29, B 97,
-- C 10, D 10, E 26, F 14); B's 66 died beside 845 drinks. Access, not
-- supply. The causes were found one at a time (a gate DF held shut, a
-- wounded visitor in the way of every Drink job, jailed office holders with
-- no water, cavern wells shut, the stranded, a shelter with no drink, the
-- insane); this reads all of them for each dwarf at once, so the brain knows
-- which remedy fits (brain/planner_thirst.py).
--
-- What it reads (each behind pcall):
--   * every citizen (the insane too) with counters2.thirst_timer at or past
--     THIRSTY (DFHack's "thirsty", 25000; DEHYDRATED 50000 as the society
--     section's `parched`): id, name, timer, place, walk group;
--   * the drink: one pass over items.other.DRINK (DRINK_SCAN at most): per
--     walk group the drink not forbidden (the item, its barrel, not carried)
--     and the drink forbidden; the wells that give water and the water
--     source zones, by the walk group beside them;
--   * the burrows each dwarf is assigned to (whether any holds drink or a
--     well), the civilian alert and its burrows; jailed (DF's punishments),
--     chained, the AI's killer cells (ai-killers); insane or in a strange
--     mood; stranded outside (ai-gates stranded_citizens); a patient;
--   * the last cancelled Drink job of each, from DF's own job-cancel reports
--     (ai-threats cancel_rows / parse_cancel, the 0.105.44 reader);
--   * one `reason` each (classify, below).
-- The last snapshot of each thirsty dwarf is kept in the save, so a death of
-- thirst (DF's incident: death_cause THIRST) is told with its place and the
-- last reason known; the last RECENT_DEATHS deaths are kept for the brain.
--
--   report()            the `thirst` section (in the pulse: thirst kills in days)
--   classify(f)         the reason for a facts table (pure; the tests call it)
--   unforbid_drink(uid, dry, max)   the drink forbidden in that dwarf's walk
--                       group let go (the nearest first; never in a siege nor
--                       near a danger)
--   open_way(uid, dry, max_dig)     (R1 g2) no_path: the AI's own walls and
--                       locked doors on the way taken down or unlocked, else
--                       the shortest dig through natural rock (see below);
--                       (X1) never out of a cell, the jail or chains, never in
--                       a siege or by a danger, only plain walls, safe tiles,
--                       and never a way that joins the fort to the outside
--                       past its gates (the flood check)
--   patient_help(uid, dry)          (R1 g2) a patient out of the hospital
--                       burrow; the water carrying counted
--   probe(uid, dry)                 (R1 g2) "unknown" looked into
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/thirst'
DAY = 1200
THIRSTY = 25000           -- DFHack's "thirsty" (ai-society-burrows REC_THIRST, ai-military SHELTER_THIRST)
DEHYDRATED = 50000        -- DFHack's "dehydrated" (the society section's `parched`)
MAX_ROWS = 40             -- dwarves listed at most (the thirstiest first)
DRINK_SCAN = 6000         -- drink items read at most
NEAREST_SPOTS = 60        -- drink tiles kept a walk group for the nearest one
CANCEL_WINDOW = 3 * DAY   -- job cancellations this recent are read
RECENT_DEATHS = 20        -- deaths kept in the save
SAVE_EVERY = 300          -- the snapshot written at least this often while it changes only in its numbers
UNFORBID_MAX = 10         -- drinks let go a call at most
UNFORBID_DANGER = 15      -- never one this near (walked across) a danger
BURROW_TILE_CHECKS = 400  -- burrow tile tests a report at most
-- strange moods (not insanity): the dwarf works on the artifact and may not drink till done
STRANGE_MOODS = {Fey = true, Secretive = true, Possessed = true, Macabre = true, Fell = true}
INSANE_MOODS = {Melancholy = 'melancholy', Raving = 'raving', Berserk = 'berserk', Traumatized = 'catatonic'}
HEALTH_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
             'rq_setting', 'rq_traction', 'rq_crutch'}

-- --- helpers ---------------------------------------------------------------

local function now_tick() return U.now_tick(0) end            -- (r6) ai-util's: 0 when it can't be read

local function txt(s)
    if s == nil then return nil end
    local ok, v = pcall(dfhack.df2utf, s)
    return ok and v or s
end

local function name_of(u) return U.name_of_conv(u, txt) end   -- (r6) ai-util's

local function is(fn, u)
    if type(fn) ~= 'function' then return false end
    local ok, v = pcall(fn, u)
    return ok and v == true
end

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

local function group_at(x, y, z)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    if ok and type(g) == 'number' then return g end
    return nil
end

-- tiles apart: the larger step across, a level counted as 3 (as ai-insane)
local function dist(a, b)
    return math.max(math.abs(a.x - b.x), math.abs(a.y - b.y)) + 3 * math.abs(a.z - b.z)
end

-- "Urist McName 'Nick', Miner" -> "urist mcname" (quoted nicknames out, lower case)
function norm_name(s)
    if type(s) ~= 'string' then return nil end
    s = s:gsub(',.*$', '')
    s = s:gsub('\226\128\156[^\226]*\226\128\157', ''):gsub('"[^"]*"', ''):gsub("`[^']*'", '')
    s = s:lower():gsub('%s+', ' '):gsub('^ ', ''):gsub(' $', '')
    if s == '' then return nil end
    return s
end

-- the names DF's reports may give the unit by, normalised
local function name_keys(u)
    local out = {}
    local function add(s) local k = norm_name(s); if k then out[k] = true end end
    pcall(function() add(txt(dfhack.translation.translateName(u.name))) end)
    pcall(function() add(txt(dfhack.TranslateName(u.name))) end)
    pcall(function() add(txt(dfhack.units.getReadableName(u))) end)
    return out
end

local function mood_of(u)
    local ok, m = pcall(function() return u.mood >= 0 and df.mood_type[u.mood] or nil end)
    return ok and m or nil
end

local function job_name(u)
    local ok, n = pcall(function()
        local j = u.job.current_job
        return j and df.job_type[j.job_type] or nil
    end)
    return ok and n or nil
end

local function patient(u)
    local ok, yes = pcall(function()
        if not (u.health and u.health.flags.needs_healthcare) then return false end
        for _, k in ipairs(HEALTH_RQ) do
            local okf, v = pcall(function() return u.health.flags[k] end)
            if okf and v then return true end
        end
        return false
    end)
    return ok and yes or false
end

-- --- the reason ------------------------------------------------------------

-- f: {insane, mood, chained, jailed, cell, stranded, drinking, timer,
-- cancel = {why, by}, alert, alert_drink, burrows = n, burrow_drink,
-- burrow_ai, drink_group, wells_group, water_group, forbidden_group,
-- drink_elsewhere, wells_elsewhere, patient}. The first that holds:
--   insane       melancholy, raving, berserk or catatonic: they don't drink
--   mood         a strange mood: at the workshop till the artifact is done
--   chained      in chains (the jail's water only, carried)
--   jailed       serving time in the jail
--   cell         in the AI's killer cell (ai-killers lets them out at 20000)
--   stranded     outside with no way in (ai-gates stranded_citizens)
--   drinking     on a Drink job now (not yet dehydrated)
--   interrupted  their last Drink job dropped: "Interrupted by" someone
--   alert        the civilian alert keeps them in its burrows, none with drink or a well
--   burrow       their own burrows hold no drink nor well
--   forbidden    the drink in their walk group is all forbidden
--   no_path      drink or a well elsewhere, none in their walk group
--   no_drink     no drink nor well anywhere
--   injured      a patient, or "too injured" (water brought from a well);
--                (R1 g2) also one last seen as a patient while still thirsty
--                (was_patient) or resting in bed (resting)
--   cancelled    their Drink job dropped for another reason (in `cancel`)
--   unknown      drink in reach, nothing seen in the way (on the way to it)
function classify(f)
    f = f or {}
    local function n(v) return tonumber(v) or 0 end
    if f.insane then return 'insane' end
    if f.mood then return 'mood' end
    if f.chained then return 'chained' end
    if f.jailed then return 'jailed' end
    if f.cell then return 'cell' end
    if f.stranded then return 'stranded' end
    if f.drinking and n(f.timer) < DEHYDRATED then return 'drinking' end
    local c = type(f.cancel) == 'table' and f.cancel or {}
    if c.by then return 'interrupted' end
    -- (K48-K4b) not when the burrow look ran out of budget before it knew (the
    -- reason was "burrow" for a burrow never looked at)
    if f.alert and not f.alert_drink and not f.alert_unread then return 'alert' end
    if n(f.burrows) > 0 and not f.burrow_drink and not f.burrow_unread and n(f.timer) < DEHYDRATED then return 'burrow' end
    local here = n(f.drink_group) + n(f.wells_group) + n(f.water_group)
    if here == 0 then
        if n(f.forbidden_group) > 0 then return 'forbidden' end
        if n(f.drink_elsewhere) + n(f.wells_elsewhere) > 0 then return 'no_path' end
        return 'no_drink'
    end
    local why = type(c.why) == 'string' and c.why:lower() or ''
    -- (R1 g2) a patient stays a patient once dehydrated: DF's treatment flags
    -- may read clear by then (B 16 Nov: "a patient" at 25-32k, then "unknown"
    -- at 50k and dead in the hospital bed), so a dwarf last seen as one (the
    -- save's snapshot) or lying in bed resting still is one
    if f.patient or f.was_patient or f.resting or why:find('injur', 1, true) then return 'injured' end
    if why:find('path', 1, true) or why:find('reach', 1, true) then return 'no_path' end
    if why ~= '' then return 'cancelled' end
    return 'unknown'
end

-- --- the drink on the map ---------------------------------------------------

-- {groups = {g = {n, forbidden, spots = {{x,y,z,n}}, fspots}}, total, forbidden, scanned}
local function drink_map()
    local gm = {}
    local out = {groups = {}, total = 0, forbidden = 0, scanned = 0}
    local function gof(x, y, z)
        local k = key(x, y, z)
        local g = gm[k]
        if g == nil then g = group_at(x, y, z) or false; gm[k] = g end
        return g or nil
    end
    local okl, list = pcall(function() return df.global.world.items.other.DRINK end)
    if not okl or not list then return out end
    for _, it in ipairs(list) do
        out.scanned = out.scanned + 1
        if out.scanned > DRINK_SCAN then out.more = true break end
        local ok, row = pcall(function()
            local fl = it.flags
            if fl.garbage_collect or fl.rotten then return nil end
            if fl.trader then return nil end        -- (K48-K4b, A4 22) a caravan's goods at the depot are not the fort's
            -- what a unit carries is no store (in_inventory alone: a barrel's content too)
            if fl.in_inventory then
                local okh, h = pcall(dfhack.items.getHolderUnit, it)
                if okh and h ~= nil then return nil end
            end
            local forbid = fl.forbid and true or false
            local c = dfhack.items.getContainer and dfhack.items.getContainer(it)
            if c then
                if c.flags.trader then return nil end
                if c.flags.forbid then forbid = true end
                local okh, h = pcall(dfhack.items.getHolderUnit, c)
                if okh and h ~= nil then return nil end
            end
            local x, y, z = U.item_pos(it)
            if not x then return nil end
            local st = 1
            if type(it.stack_size) == 'number' and it.stack_size > 0 then st = it.stack_size end
            return {x = x, y = y, z = z, n = st, forbid = forbid}
        end)
        if ok and row then
            local g = gof(row.x, row.y, row.z)
            if g and g ~= 0 then
                local e = out.groups[g]
                if not e then e = {n = 0, forbidden = 0, spots = {}, fspots = {}}; out.groups[g] = e end
                if row.forbid then
                    e.forbidden = e.forbidden + row.n
                    out.forbidden = out.forbidden + row.n
                    if #e.fspots < NEAREST_SPOTS then table.insert(e.fspots, row) end
                else
                    e.n = e.n + row.n
                    out.total = out.total + row.n
                    if #e.spots < NEAREST_SPOTS then table.insert(e.spots, row) end
                end
            end
        end
    end
    return out
end

local NEIGH = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}

-- the walk groups beside a spot (a well stands on its hole)
local function groups_beside(x, y, z, into)
    for _, d in ipairs(NEIGH) do
        local g = group_at(x + d[1], y + d[2], z)
        if g and g ~= 0 then into[g] = true end
    end
end

-- {by_group = {g = n}, list = {{x,y,z,groups}}}: the wells that give water
local function wells()
    local out = {by_group = {}, list = {}}
    pcall(function()
        local okb, B = pcall(reqscript, 'ai-society-burrows')
        for _, b in ipairs(df.global.world.buildings.other.WELL) do
            local ok, good = pcall(function()
                if b:getBuildStage() < b:getMaxBuildStage() then return false end
                if okb and B and B.well_gives_water then return B.well_gives_water(b) ~= false end
                return true
            end)
            if not ok or good then
                local gs = {}
                groups_beside(b.centerx, b.centery, b.z, gs)
                for g in pairs(gs) do out.by_group[g] = (out.by_group[g] or 0) + 1 end
                table.insert(out.list, {x = b.centerx, y = b.centery, z = b.z, groups = gs})
            end
        end
    end)
    return out
end

-- {by_group = {g = n}, n}: the water source zones, by the walk groups on and beside them
local function water_zones()
    local out = {by_group = {}, n = 0, list = {}}
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_WATER_SOURCE) do
            out.n = out.n + 1
            local gs = {}
            local cx, cy = (z.x1 + z.x2) // 2, (z.y1 + z.y2) // 2
            local g = group_at(cx, cy, z.z)
            if g and g ~= 0 then gs[g] = true end
            groups_beside(cx, cy, z.z, gs)
            for gg in pairs(gs) do out.by_group[gg] = (out.by_group[gg] or 0) + 1 end
            table.insert(out.list, {x = cx, y = cy, z = z.z, groups = gs})
        end
    end)
    return out
end

-- --- who is held where -------------------------------------------------------

local function burrow_by_id(id)
    local ok, b = pcall(function()
        for _, b in ipairs(df.global.plotinfo.burrows.list) do if b.id == id then return b end end
    end)
    return ok and b or nil
end

local function jailed_ids()
    local out = {}
    pcall(function()
        for _, pu in ipairs(df.global.plotinfo.punishments) do
            if (pu.prison_counter or 0) > 0 then
                local c = pu.criminal
                local id = type(c) == 'number' and c or (c and c.id)
                if id and id >= 0 then out[id] = pu.prison_counter end
            end
        end
    end)
    return out
end

-- (X1, V5) every AI holding cell: ai-killers' killer cells (not let out)
-- and ai-threats' werebeast moon cells (a record kept only while held):
-- {uid = 'killer' | 'moon'}. A dwarf in one is held on purpose, never
-- 'no_path' (a way would be dug or opened out of the cell).
local function cell_ids()
    local out = {}
    pcall(function()
        local K = reqscript('ai-killers')
        for uid, c in pairs(K.state().cells or {}) do
            if type(c) == 'table' and not c.out then out[tonumber(uid) or uid] = 'killer' end
        end
    end)
    pcall(function()
        local T = reqscript('ai-threats')
        local read = type(T.load_state) == 'function' and T.load_state or T.state
        for uid, c in pairs(read().cells or {}) do
            local id = tonumber(uid) or uid
            if type(c) == 'table' and not c.out and not c.released and not out[id] then out[id] = 'moon' end
        end
    end)
    return out
end

-- (X1, V5) the AI's holding burrows by name: a killer cell, a moon cell, a
-- tantrum's calm-down room (ai-society-burrows CALM_PREFIX). Their kind, or nil.
HELD_BURROWS = {{'AI killer cell ', 'killer'}, {'AI moon cell ', 'moon'}, {'AI calm ', 'calm'}}
function held_burrow_kind(name)
    if type(name) ~= 'string' then return nil end
    for _, h in ipairs(HELD_BURROWS) do
        if name:sub(1, #h[1]) == h[1] then return h[2] end
    end
    return nil
end

-- (X1, V5) is this unit held by the AI or DF on purpose (a cell, the
-- calm-down room, the jail, chains)? Its kind, or nil. open_way never opens
-- a way out for one.
local function held_kind(u, cells, jail)
    cells = cells or cell_ids()
    if cells[u.id] then return cells[u.id] end
    jail = jail or jailed_ids()
    if jail[u.id] then return 'jail' end
    local chained = false
    pcall(function() chained = u.flags1.chained == true end)
    if chained then return 'chained' end
    local kind = nil
    pcall(function()
        for _, bid in ipairs(u.burrows) do
            local b = burrow_by_id(bid)
            kind = kind or (b and held_burrow_kind(txt(tostring(b.name)))) or nil
        end
    end)
    return kind
end

local function stranded_rows()
    local out = {}
    pcall(function()
        local st = reqscript('ai-gates').stranded_citizens()
        for _, r in ipairs(st and st.list or {}) do out[r.id] = r end
    end)
    return out
end

-- {on, burrows = {id = true}}: the civilian alert and the burrows it keeps citizens in
local function civ_alert()
    local out = {on = false, burrows = {}}
    pcall(function()
        local a = df.global.plotinfo.alerts
        out.on = a.civ_alert_idx ~= 0
        if out.on then
            for _, al in ipairs(a.list) do
                if al.id == a.civ_alert_idx then
                    for _, id in ipairs(al.burrows) do out.burrows[id] = true end
                end
            end
            if next(out.burrows) == nil then
                local al = a.list[a.civ_alert_idx]
                for _, id in ipairs(al and al.burrows or {}) do out.burrows[id] = true end
            end
        end
    end)
    return out
end


-- does the burrow hold one of these spots ({x,y,z})? (budget: a shared counter)
local function burrow_holds(b, spots, budget)
    for _, p in ipairs(spots or {}) do
        if budget.n <= 0 then return nil end
        budget.n = budget.n - 1
        local ok, yes = pcall(dfhack.burrows.isAssignedTile, b, xyz2pos(p.x, p.y, p.z))
        if ok and yes then return true end
    end
    return false
end

-- --- the last cancelled Drink job of each dwarf -------------------------------

-- {normalised name = {why, by, n, tick, x, y, z}}: the newest Drink cancellation each
local function drink_cancels()
    local out = {}
    local ok, T = pcall(reqscript, 'ai-threats')
    if not ok or not T or not T.cancel_rows or not T.parse_cancel then return out end
    local okr, rows = pcall(T.cancel_rows, CANCEL_WINDOW)
    if not okr or type(rows) ~= 'table' then return out end
    for _, r in ipairs(rows) do        -- newest first
        local who, job, why = T.parse_cancel(r.text)
        if who and type(job) == 'string' and job:find('^Drink') then
            local k = norm_name(who)
            if k then
                local c = out[k]
                if not c then
                    local by
                    if T.interrupter_of then
                        local okb, b = pcall(T.interrupter_of, why)
                        by = okb and b or nil
                    end
                    c = {why = tostring(why):sub(1, 80), by = by, n = 0, tick = r.tick, x = r.x, y = r.y, z = r.z}
                    out[k] = c
                end
                c.n = c.n + (tonumber(r.n) or 1)
            end
        end
    end
    return out
end

-- --- the save's record ---------------------------------------------------------

-- {snap = {uid = {tick, timer, reason, x, y, z, name, cancel}}, deaths = [...], told = {uid = tick}, saved}
function state()
    local d = U.site_get(SITE_KEY, {})
    d.snap = type(d.snap) == 'table' and d.snap or {}
    d.deaths = type(d.deaths) == 'table' and d.deaths or {}
    d.told = type(d.told) == 'table' and d.told or {}
    return d
end

local function save(d) pcall(U.site_put, SITE_KEY, d) end

local function death_cause(u)
    local ok, c = pcall(function()
        local inc = df.incident.find(u.counters.death_id)
        return inc and df.death_type[inc.death_cause] or nil
    end)
    return ok and c or nil
end

-- the snapshot's dwarves now dead of thirst, told once each (in the save)
local function find_deaths(d, now, alive)
    local new = {}
    for sid, sn in pairs(d.snap) do
        local uid = tonumber(sid) or sid
        if not alive[uid] then
            local u = df.unit.find(uid)
            if not u then
                d.snap[sid] = nil
            elseif is(dfhack.units.isDead, u) then
                local cause = death_cause(u)
                if cause == 'THIRST' and not d.told[tostring(uid)] then
                    local row = {id = uid, name = sn.name or name_of(u), tick = now, reason = sn.reason,
                                 timer = sn.timer, cancel = sn.cancel, x = sn.x, y = sn.y, z = sn.z,
                                 seen_tick = sn.tick}
                    pcall(function()
                        if u.pos.x >= 0 then row.x, row.y, row.z = u.pos.x, u.pos.y, u.pos.z end
                    end)
                    table.insert(d.deaths, row)
                    d.told[tostring(uid)] = now
                    table.insert(new, row)
                end
                d.snap[sid] = nil
            end
        end
    end
    while #d.deaths > RECENT_DEATHS do table.remove(d.deaths, 1) end
    -- the told marks kept a year
    for k, t in pairs(d.told) do
        if type(t) ~= 'number' or now - t > 403200 then d.told[k] = nil end
    end
    return new
end

-- --- the report -------------------------------------------------------------------

local function nearest(spots, p)
    local best, bd = nil, math.huge
    for _, s in ipairs(spots or {}) do
        local dd = dist(s, p)
        if dd < bd then best, bd = s, dd end
    end
    return best and {x = best.x, y = best.y, z = best.z, d = bd} or nil
end

function report()
    local now = now_tick()
    local d = state()
    local thirsty = {}
    local okc, cits = pcall(U.citizens, false, true)
    for _, u in ipairs(okc and cits or {}) do
        local ok, th = pcall(function() return u.counters2.thirst_timer end)
        if ok and type(th) == 'number' and th >= THIRSTY and not is(dfhack.units.isDead, u) then
            table.insert(thirsty, {u = u, timer = th})
        end
    end
    table.sort(thirsty, function(a, b) return a.timer > b.timer end)
    local out = {thirsty = #thirsty, dehydrated = 0, list = {}, thresholds = {thirsty = THIRSTY, dehydrated = DEHYDRATED}}
    local alive = {}
    if #thirsty > 0 then
        local dm = drink_map()
        local wl, wz = wells(), water_zones()
        local jail, cells, strand = jailed_ids(), cell_ids(), stranded_rows()
        local alert = civ_alert()
        local cancels = drink_cancels()
        local budget = {n = BURROW_TILE_CHECKS}
        out.drink_total, out.drink_forbidden, out.wells, out.water_zones = dm.total, dm.forbidden, #wl.list, wz.n
        out.alert = alert.on or nil
        local wells_all, zones_all = #wl.list, wz.n
        for _, t in ipairs(thirsty) do
            local u = t.u
            alive[u.id] = true
            if t.timer >= DEHYDRATED then out.dehydrated = out.dehydrated + 1 end
            if #out.list < MAX_ROWS then
                local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                local g = group_at(p.x, p.y, p.z)
                local e = g and dm.groups[g] or nil
                local f = {timer = t.timer}
                local row = {id = u.id, name = name_of(u), timer = t.timer, x = p.x, y = p.y, z = p.z, group = g,
                             level = t.timer >= DEHYDRATED and 'dehydrated' or 'thirsty'}
                local m = mood_of(u)
                if m and INSANE_MOODS[m] then f.insane, row.insane = true, INSANE_MOODS[m]
                elseif m and STRANGE_MOODS[m] then f.mood, row.mood = true, m end
                pcall(function() if u.flags1.chained then f.chained, row.chained = true, true end end)
                if jail[u.id] then f.jailed, row.jailed = true, jail[u.id] end
                if cells[u.id] then f.cell, row.cell = true, cells[u.id] end
                local sr = strand[u.id]
                if sr then
                    f.stranded = true
                    row.stranded = {cause = sr.cause, out_days = sr.out_days, stuck_gate = sr.stuck_gate,
                                    entrance_id = sr.entrance and sr.entrance.id or nil, by_ai = sr.by_ai}
                end
                local jn = job_name(u)
                if jn and jn:find('^Drink') then f.drinking, row.drinking = true, true end
                row.job = jn
                for k in pairs(name_keys(u)) do
                    if cancels[k] then row.cancel = cancels[k]; break end
                end
                f.cancel = row.cancel
                f.patient = patient(u) or nil
                row.patient = f.patient
                -- (R1 g2) a patient once, still thirsty since: still a patient
                local prev = d.snap[tostring(u.id)]
                if not f.patient and type(prev) == 'table' and (prev.patient or prev.reason == 'injured') then
                    f.was_patient, row.was_patient = true, true
                end
                if jn == 'Rest' then f.resting, row.resting = true, true end
                -- in reach: the walk group's drink, wells, water zones
                f.drink_group = e and e.n or 0
                f.forbidden_group = e and e.forbidden or 0
                f.wells_group = g and wl.by_group[g] or 0
                f.water_group = g and wz.by_group[g] or 0
                f.drink_elsewhere = dm.total - f.drink_group
                f.wells_elsewhere = wells_all + zones_all - f.wells_group - f.water_group
                row.drink_group, row.forbidden_group = f.drink_group, f.forbidden_group
                row.wells_group, row.water_group = f.wells_group, f.water_group
                row.drink_elsewhere, row.wells_elsewhere = f.drink_elsewhere, f.wells_elsewhere
                row.nearest_drink = e and nearest(e.spots, p) or nil
                if f.drink_group == 0 and e and e.forbidden > 0 then row.nearest_forbidden = nearest(e.fspots, p) end
                -- the burrows that hold them: their own, and the alert's
                local spots = {}
                for _, s in ipairs(e and e.spots or {}) do table.insert(spots, s) end
                for _, w in ipairs(wl.list) do if g and w.groups[g] then table.insert(spots, w) end end
                for _, w in ipairs(wz.list) do if g and w.groups[g] then table.insert(spots, w) end end
                local mine, bdrink, ai_only = {}, false, true
                local unread = false        -- (K48-K4b, A4 22) the look's budget ran out: not known
                local soldier = false
                pcall(function() soldier = u.military.squad_id ~= -1 end)
                local in_alert = {}
                pcall(function()
                    for _, bid in ipairs(u.burrows) do
                        local b = burrow_by_id(bid)
                        local nm = b and txt(tostring(b.name)) or tostring(bid)
                        local ai = nm:sub(1, 3) == 'AI '
                        if not ai then ai_only = false end
                        -- (X1, V5) a cell's burrow or the calm-down room: held there on purpose
                        local hk = held_burrow_kind(nm)
                        if hk and not f.cell then f.cell, row.cell = true, hk end
                        local holds = b and burrow_holds(b, spots, budget)
                        if holds then bdrink = true end
                        if b and holds == nil then unread = true end
                        table.insert(mine, {id = bid, name = nm, ai = ai or nil, drink = holds})
                    end
                end)
                if #mine > 0 then
                    row.burrows = mine
                    f.burrows, f.burrow_drink = #mine, bdrink
                    if unread and not bdrink then f.burrow_unread = true end
                    row.burrow_ai = ai_only or nil
                end
                if alert.on and not soldier then
                    local adrink, any, aunread = false, false, false
                    for bid in pairs(alert.burrows) do
                        any = true
                        local b = burrow_by_id(bid)
                        local holds = b and burrow_holds(b, spots, budget)
                        if holds then adrink = true break end
                        if b and holds == nil then aunread = true end
                    end
                    if any then
                        f.alert, f.alert_drink = true, adrink
                        if aunread and not adrink then f.alert_unread = true end
                        row.alert = {drink = adrink}
                    end
                end
                row.reason = classify(f)
                table.insert(out.list, row)
                -- the snapshot (a death explained by it)
                d.snap[tostring(u.id)] = {tick = now, timer = t.timer, reason = row.reason, x = p.x, y = p.y, z = p.z,
                                          name = row.name, cancel = row.cancel and row.cancel.why or nil,
                                          patient = (f.patient or f.was_patient or f.resting) and true or nil}
            else
                local sn = d.snap[tostring(u.id)]
                if sn then sn.timer, sn.tick = t.timer, now end
            end
        end
    end
    -- a dwarf who drank leaves the snapshot; the dead are told
    local okc2, all = pcall(U.citizens, false, true)
    local living = {}
    for _, u in ipairs(okc2 and all or {}) do living[u.id] = true end
    for sid in pairs(d.snap) do
        local uid = tonumber(sid) or sid
        if living[uid] and not alive[uid] then d.snap[sid] = nil end
    end
    local new = find_deaths(d, now, alive)
    out.new_deaths = #new
    out.deaths = d.deaths
    -- written when who or why changed, a death came, or SAVE_EVERY passed
    local sig = {}
    for sid, sn in pairs(d.snap) do table.insert(sig, sid .. ':' .. tostring(sn.reason)) end
    table.sort(sig)
    sig = table.concat(sig, ';')
    if #new > 0 or sig ~= d.sig or now - (tonumber(d.saved) or -SAVE_EVERY) >= SAVE_EVERY then
        d.sig, d.saved = sig, now
        save(d)
    end
    return out
end

-- --- the action: drink forbidden in a dwarf's reach let go ----------------------

function unforbid_drink(uid, dry_run, max)
    max = math.max(1, math.min(tonumber(max) or UNFORBID_MAX, 50))
    local u = df.unit.find(uid)
    if not u or is(dfhack.units.isDead, u) then
        return {ok = false, rejected = true, error = 'no such living unit'}
    end
    local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
    local g = group_at(p.x, p.y, p.z)
    if not g or g == 0 then return {ok = false, rejected = true, error = 'the dwarf stands on no walkable tile'} end
    local siege = false
    pcall(function() siege = reqscript('ai-gates').GATES.armed == true end)
    if siege then
        return {ok = false, rejected = true, error = 'the gates are shut against enemies: nothing is let go now'}
    end
    local dangers = U.danger_spots()
    local cand, near_danger = {}, 0
    local okl, list = pcall(function() return df.global.world.items.other.DRINK end)
    local n = 0
    for _, it in ipairs(okl and list or {}) do
        n = n + 1
        if n > DRINK_SCAN then break end
        local ok, row = pcall(function()
            local fl = it.flags
            if fl.garbage_collect or fl.rotten then return nil end
            if fl.trader then return nil end        -- (K48-K4b, A4 22) a caravan's goods at the depot are not the fort's
            local c = dfhack.items.getContainer and dfhack.items.getContainer(it)
            if c and c.flags.trader then return nil end
            local cf = c and c.flags.forbid
            if not fl.forbid and not cf then return nil end
            if fl.in_inventory then
                local okh, h = pcall(dfhack.items.getHolderUnit, it)
                if okh and h ~= nil then return nil end
            end
            local x, y, z = U.item_pos(it)
            if not x or group_at(x, y, z) ~= g then return nil end
            return {it = it, c = cf and c or nil, x = x, y = y, z = z}
        end)
        if ok and row then
            if U.near_danger(dangers, row.x, row.y, row.z, UNFORBID_DANGER) then
                near_danger = near_danger + 1
            else
                row.d = dist(row, p)
                table.insert(cand, row)
            end
        end
    end
    table.sort(cand, function(a, b) return a.d < b.d end)
    local done, containers, seen = 0, 0, {}
    for _, r in ipairs(cand) do
        if done >= max then break end
        if not dry_run then
            pcall(function() r.it.flags.forbid = false end)
            if r.c and not seen[r.c] then
                seen[r.c] = true
                pcall(function() r.c.flags.forbid = false end)
                containers = containers + 1
            end
        elseif r.c and not seen[r.c] then
            seen[r.c] = true
            containers = containers + 1
        end
        done = done + 1
    end
    local res = {ok = done > 0, dry_run = dry_run or nil, unforbidden = done, containers = containers,
                 near_danger = near_danger, group = g, candidates = #cand}
    if done == 0 then
        res.rejected = true
        res.error = near_danger > 0 and 'the forbidden drink in their reach lies near a danger'
            or 'no forbidden drink in their reach'
    end
    return res
end

-- (r9) this file's locals the later parts use (each takes back the ones it
-- uses as locals of its own): all functions and fixed values, set once here
PART_LOCALS = {U = U, now_tick = now_tick, txt = txt, is = is, key = key, group_at = group_at, mood_of = mood_of, job_name = job_name, patient = patient, drink_map = drink_map, NEIGH = NEIGH, wells = wells, water_zones = water_zones, burrow_by_id = burrow_by_id, held_kind = held_kind, civ_alert = civ_alert, burrow_holds = burrow_holds}

---------------------------------------------------------------------------
-- (r9) The rest of the thirst watch lives in a part beside this file
-- (ai-thirst-<part>.lua): remedies (the real remedies: open_way and the
-- search for a way to the drink with its safety checks, patient_help,
-- probe). It runs in this module's own environment, so its names stay
-- reqscript('ai-thirst').name for the bridge and the other modules, and a
-- test's swap (T.open_way = ...) reaches it. DFHack reloads a module when
-- its own file changes: a change to a part alone is picked up once
-- ai-thirst.lua is touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'remedies'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-thirst'] = '0.105.64'}   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local name = 'ai-thirst-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-thirst: ' .. name .. '.lua is missing (it goes beside ai-thirst.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
