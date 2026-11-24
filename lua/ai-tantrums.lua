-- (0.105.47, R2 item 3, 12i) Tantrums one dwarf at a time: who threw them and
-- how often (a ledger kept in the save), what posts and hospital labours the
-- tantrum-throwers hold, what they miss, and a calm squad on guard at each
-- hospital while a tantrum is loose.
--
-- Why (I7c, the 11-14 Nov run): E lost 14 citizens to citizens. Five chronic
-- tantrum dwarves (miserable for years) held the posts the AI gave them
-- (doctor, tavern keeper, surgeon, bone doctor, two with skill 0) and beat
-- patients to death in their beds; 8 of E's 11 "suffocated" died inside a
-- hospital zone, a ninth at its door two tiles from the central stair. The
-- calm burrow never held one (members outside 54 of 60 times), and the crisis
-- trigger (10 tantrums in 28 days) never fired in a fort of 23-45: the 44
-- tantrums came from 4-5 dwarves, one or two at a time.
--
-- What it keeps and reads (each behind pcall):
--   * the ledger (site data LEDGER_KEY): each citizen's tantrum starts (their
--     soldier_mood turning Tantrum or Enraged, as the calm burrow reads it),
--     a year of them at most; a tantrum seen over several reports counts once;
--   * per tantrum-thrower: tantrums in 28 days and in the year, in one now,
--     stress, the posts held (u.occupations: location and kind), the hospital
--     labours on, their worst unmet needs, an own bedroom, a squad, hurt;
--   * while a tantrum is loose or a guard stands (else `quiet`): the hospital
--     zones (ai-society-burrows hospital_zones) with a tile to stand on, the fort's squads (calm: no member very unhappy or worse, in a
--     tantrum or berserk; wounded; thirsty or hungry; orders), and the AI's
--     hospital guards (GUARD_KEY), each checked against the squad's orders.
--
--   report(txt)           the `tantrums` section (in the pulse: a tantrum is
--                         loose for hours, not days)
--   staff_refusal(u, d)   why u may not take a post now (nil: may): very
--                         unhappy or worse, in a tantrum, one in the last 28
--                         days, or 3+ in a year (ai-society can_staff)
--   kill_kind(k)          'tantrum', 'berserk' or 'possessed' for a killer
--                         (the death event's conflict, ai-bridge-report)
--   fight_of(victim)      (0.105.99) 'brawl' and the tantrum-thrower loose
--                         then, for a victim drawn into a fight
--   guard(squad, zone, dry)   a squad stationed at a hospital zone (ai-military station)
--   unguard(squad, dry)       its station order taken off, the marks cleared
--   step_down(unit, medical, dry, txt)   every post the dwarf holds vacated
--                         (ai-society vacate_post), the hospital labours off
--@ module = true

local U = reqscript('ai-util')

LEDGER_KEY = 'ai-overseer/tantrums'
GUARD_KEY = 'ai-overseer/hospital-guard'
DAY = 1200
YEAR = 403200
STAFF_DAYS = 28           -- a tantrum this recent bars a post (can_staff)
CHRONIC = 3               -- tantrums in a year that make a chronic case
KILL_DAYS = 2             -- a killer with a tantrum this recent killed in one
SEEN_STEP = 100           -- (0.105.99) a tantrum's "last seen on" written this often at most
EPISODE_GAP = 300         -- a tantrum seen again this soon after one began is the same one
MAX_TICKS = 12            -- tantrum starts kept a dwarf
MAX_ROWS = 12             -- tantrum-throwers listed at most (in one now first, then the most)
STRESS_LABELS = {[0] = 'miserable', [1] = 'very_unhappy', [2] = 'unhappy', [3] = 'fine',
                 [4] = 'content', [5] = 'happy', [6] = 'ecstatic'}
-- the hospital labours (ai-society POST_LABORS, every post's)
MED_LABORS = {'DIAGNOSE', 'SURGERY', 'BONE_SETTING', 'SUTURING', 'DRESSING_WOUNDS'}
DISTRACTED = -1000        -- a need this low is unmet (ai-bridge-report get_needs)
HURT_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
           'rq_setting', 'rq_traction', 'rq_crutch'}

-- --- helpers ---------------------------------------------------------------

local function citizens()
    if U.REPORT_CTX and U.citizens then return U.citizens(true) end
    return dfhack.units.getCitizens(true)
end

function in_tantrum(u)
    local ok, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    return ok and (m == 'Tantrum' or m == 'Enraged') or false
end

local function mood_of(u)
    local ok, m = pcall(function() return u.mood ~= nil and u.mood >= 0 and df.mood_type[u.mood] or nil end)
    return ok and m or nil
end

local function stress_of(u)
    local ok, c = pcall(dfhack.units.getStressCategory, u)
    return ok and type(c) == 'number' and c or nil
end

local function hurt(u)
    local ok, yes = pcall(function()
        if (u.body.blood_count or 0) < (u.body.blood_max or 0) then return true end
        local f = u.health and u.health.flags
        if not f then return false end
        for _, k in ipairs(HURT_RQ) do if f[k] then return true end end
        return false
    end)
    return ok and yes or false
end

local function name_of(u, txt) return U.name_of(u, txt) end   -- (r6) ai-util's

-- --- the ledger ----------------------------------------------------------------

function load()
    local d = U.site_get(LEDGER_KEY, {units = {}})
    if type(d.units) ~= 'table' then d.units = {} end
    return d
end

-- Tantrums begun within `days` of now by unit `id` (from the ledger `d`).
function count(d, id, days, now)
    local r = d and d.units and d.units[tostring(id)]
    if type(r) ~= 'table' or type(r.t) ~= 'table' then return 0 end
    local n = 0
    for _, t in ipairs(r.t) do
        if type(t) == 'number' and now - t >= 0 and now - t < days * DAY then n = n + 1 end
    end
    return n
end

-- Every citizen read once: a tantrum that began since the last look is
-- written down (a start, not each report it lasts); a year kept a dwarf;
-- ticks after now (an older save loaded) dropped. Returns the ledger.
function note(now)
    now = now or U.abs_tick()
    local d = load()
    local changed = false
    for _, u in ipairs(citizens()) do
        local key = tostring(u.id)
        local r = d.units[key]
        if in_tantrum(u) then
            if type(r) ~= 'table' then r = {t = {}}; d.units[key] = r end
            if type(r.t) ~= 'table' then r.t = {} end
            if not r.on then
                local last = r.t[#r.t]
                if type(last) ~= 'number' or now - last >= EPISODE_GAP or now < last then table.insert(r.t, now) end
                r.on = true
                changed = true
            end
            -- (0.105.99) when it was last seen on (kill_kind, fight_of), written
            -- every SEEN_STEP ticks at most
            local seen = tonumber(r.seen)
            if seen == nil or now - seen >= SEEN_STEP or now < seen then
                r.seen = now
                changed = true
            end
        elseif type(r) == 'table' and r.on then
            r.on = nil
            r.ended = now        -- (0.105.99) when it ended: kill_kind counts from there
            changed = true
        end
    end
    for key, r in pairs(d.units) do
        if type(r) ~= 'table' then
            d.units[key] = nil
            changed = true
        else
            local keep, old = {}, type(r.t) == 'table' and r.t or {}
            for _, t in ipairs(old) do
                if type(t) == 'number' and t <= now and now - t < YEAR then table.insert(keep, t) end
            end
            while #keep > MAX_TICKS do table.remove(keep, 1) end
            if #keep ~= #old then changed = true end
            r.t = keep
            if #keep == 0 and not r.on then d.units[key] = nil; changed = true end
        end
    end
    if changed then U.site_put(LEDGER_KEY, d) end
    return d
end

-- Why `u` may not take a post now, or nil. (I7c fix 1) Miserable chronic
-- tantrum dwarves were made doctor, surgeon, bone doctor and tavern keeper
-- (twice with skill 0) and beat patients in their beds.
function staff_refusal(u, d, now)
    local cat = stress_of(u)
    if cat and cat <= 1 then return ((STRESS_LABELS[cat] or 'very_unhappy'):gsub('_', ' ')) end
    if in_tantrum(u) then return 'in a tantrum' end
    d = d or load()
    now = now or U.abs_tick()
    if count(d, u.id, STAFF_DAYS, now) > 0 then return 'a tantrum in the last 28 days' end
    if count(d, u.id, YEAR // DAY, now) >= CHRONIC then return CHRONIC .. '+ tantrums this year' end
    return nil
end

-- What a killer was in when they killed: 'tantrum' (in one now, or one in
-- the last KILL_DAYS), 'berserk', 'possessed'; nil otherwise.
-- (0.105.99) "one in the last KILL_DAYS" from the tantrum's END too (the
-- ledger's `ended`, or `seen`: last seen on by a report), not only its start.
-- E, 23 Nov 23:55:43: Meng Inoddesor's tantrum began at tick 183635 and ran
-- past 186154 (five blows at the stonecrafter Urist); Urist suffocated at
-- 186584, 2949 ticks after the start, with Meng calm by then: told as a
-- killing "without a tantrum" (conflict None).
function kill_kind(k, now)
    if not k then return nil end
    local m = mood_of(k)
    if m == 'Berserk' then return 'berserk' end
    if m == 'Possessed' then return 'possessed' end
    if in_tantrum(k) then return 'tantrum' end
    now = now or U.abs_tick()
    local ok, n = pcall(function()
        local d = load()
        if count(d, k.id, KILL_DAYS, now) > 0 then return 1 end
        local r = d.units[tostring(k.id)]
        if type(r) ~= 'table' then return 0 end
        for _, e in ipairs({tonumber(r.ended) or false, tonumber(r.seen) or false}) do
            if e and now - e >= 0 and now - e < KILL_DAYS * DAY then return 1 end
        end
        return 0
    end)
    if ok and n > 0 then return 'tantrum' end
    return nil
end

-- (0.105.99) A death in a fight the victim was drawn into: 'brawl' when the
-- victim's own thoughts of the last KILL_DAYS hold a Conflict or JoinConflict
-- (DF's "got into a fight" and "joined a fight"), and the citizen whose
-- tantrum was loose then (the ledger's latest: on, ended or begun within
-- KILL_DAYS), or nil. E, 23 Nov 23:47: Medtob Sefollòr's tantrum (tick
-- 141621) struck the butcher Tobul at 142379; the peasant Endok joined the
-- fight at 142434 (JoinConflict), both had "major injuries" by 142900 and
-- were carried to the hospital (Rescued), and both suffocated there at
-- 143695 and 144129, the kills credited to the miner Zon Avuzfikod and the
-- axedwarf Dodók Tithlethzas, calm dwarves who had joined in (no weapon in
-- DF's record of either death). Read: brawl, round Medtob's tantrum.
BRAWL_THOUGHTS = {Conflict = true, JoinConflict = true}
function fight_of(v, now)
    if not v then return nil end
    now = now or U.abs_tick()
    local seen = false
    pcall(function()
        for _, e in ipairs(v.status.current_soul.personality.emotions) do
            local okt, th = pcall(function() return df.unit_thought_type[e.thought] end)
            if okt and BRAWL_THOUGHTS[th] then
                local t = U.abs_tick(e.year, e.year_tick)
                if now - t >= 0 and now - t < KILL_DAYS * DAY then
                    seen = true
                    break
                end
            end
        end
    end)
    if not seen then return nil end
    local best, bt = nil, nil
    pcall(function()
        for key, r in pairs(load().units) do
            if type(r) == 'table' then
                local t = math.max(tonumber(r.seen) or -1, tonumber(r.ended) or -1,
                                   type(r.t) == 'table' and tonumber(r.t[#r.t]) or -1)
                if t >= 0 and now - t >= 0 and now - t < KILL_DAYS * DAY and (bt == nil or t > bt) then
                    best, bt = tonumber(key), t
                end
            end
        end
    end)
    return 'brawl', best
end

-- --- one dwarf's row -------------------------------------------------------------

local function posts_of(u)
    local out = {}
    pcall(function()
        for _, o in ipairs(u.occupations) do
            table.insert(out, {location_id = o.location_id, post = df.occupation_type[o.type] or tostring(o.type)})
        end
    end)
    return out
end

local function medical_on(u)
    local on = {}
    for _, l in ipairs(MED_LABORS) do
        pcall(function() if u.status.labors[df.unit_labor[l]] then table.insert(on, l) end end)
    end
    return on
end

local function unmet_of(u)
    local worst = {}
    pcall(function()
        for _, nd in ipairs(u.status.current_soul.personality.needs) do
            if nd.focus_level <= DISTRACTED then
                table.insert(worst, {name = df.need_type[nd.id] or tostring(nd.id), focus = nd.focus_level})
            end
        end
    end)
    table.sort(worst, function(a, b) return a.focus < b.focus end)
    local out = {}
    for i = 1, math.min(4, #worst) do out[i] = worst[i].name end
    return out
end

local function bedroom_of(u)
    local ok, yes = pcall(function()
        for _, b in ipairs(u.owned_buildings) do
            if df.building_civzonest:is_instance(b) and df.civzone_type[b.type] == 'Bedroom' then return true end
        end
        return false
    end)
    if ok then return yes end
    return nil
end

local function row_of(u, r, now, txt)
    local cat = stress_of(u)
    local ticks = {}
    for _, t in ipairs(type(r) == 'table' and type(r.t) == 'table' and r.t or {}) do table.insert(ticks, t) end
    local med = medical_on(u)
    local squad = false
    pcall(function() squad = u.military.squad_id ~= -1 end)
    return {id = u.id, name = name_of(u, txt), now = in_tantrum(u) or nil,
            n28 = count({units = {[tostring(u.id)] = r}}, u.id, 28, now),
            year = #ticks, ticks = ticks, last = ticks[#ticks],
            stress = cat and STRESS_LABELS[cat] or nil, posts = posts_of(u),
            medical = #med > 0 and med or nil, unmet = unmet_of(u), bedroom = bedroom_of(u),
            squad = squad or nil, hurt = hurt(u) or nil, mood = mood_of(u)}
end

-- --- hospitals and squads ---------------------------------------------------------

local function walk_group(p)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, p)
    return ok and type(g) == 'number' and g or 0
end

-- a tile of the zone a soldier can stand on: its middle, else the first walkable one
function stand_pos(b)
    local mid = {x = math.floor((b.x1 + b.x2) / 2), y = math.floor((b.y1 + b.y2) / 2), z = b.z}
    if walk_group(mid) ~= 0 then return mid end
    local n = 0
    for y = b.y1, b.y2 do
        for x = b.x1, b.x2 do
            local p = {x = x, y = y, z = b.z}
            if walk_group(p) ~= 0 then return p end
            n = n + 1
            if n > 400 then return nil end
        end
    end
    return nil
end

function hospital_zones()
    local ok, zones = pcall(function() return (reqscript('ai-society-burrows').hospital_zones()) end)
    return ok and type(zones) == 'table' and zones or {}
end

local function member_units(sq)
    local out = {}
    for _, pos in ipairs(sq.positions) do
        if pos.occupant ~= -1 then
            pcall(function()
                local hf = df.historical_figure.find(pos.occupant)
                local u = hf and df.unit.find(hf.unit_id)
                if u then table.insert(out, u) end
            end)
        end
    end
    return out
end

function load_marks()
    local m = U.site_get(GUARD_KEY, {})
    return type(m) == 'table' and m or {}
end

local function squad_rows(M, marks)
    local out, guards, changed = {}, {}, false
    local fort = U.fort_entity()
    local here = {}
    for _, sid in ipairs(fort and fort.squads or {}) do
        local sq = df.squad.find(sid)
        if sq then
            here[tostring(sid)] = true
            local units = member_units(sq)
            local calm, wounded, worst = true, 0, nil
            for _, u in ipairs(units) do
                local cat = stress_of(u)
                if cat and (not worst or cat < worst) then worst = cat end
                if (cat and cat <= 1) or in_tantrum(u) or mood_of(u) then calm = false end
                if hurt(u) then wounded = wounded + 1 end
            end
            local ai, player = 0, 0
            for _, o in ipairs(sq.orders) do
                local oka, mine = pcall(M.ai_order, o, sid)
                if oka and mine then ai = ai + 1 else player = player + 1 end
            end
            local okm, ms = pcall(M.members_state, sq)
            local mark = marks[tostring(sid)]
            local guarding = nil
            if type(mark) == 'table' then
                for _, o in ipairs(sq.orders) do
                    local oks, st = pcall(M.station_of, o, sid)
                    if oks and st and st.x == mark.x and st.y == mark.y and st.z == mark.z then guarding = mark.zone_id end
                end
                if guarding == nil then marks[tostring(sid)] = nil; changed = true
                else table.insert(guards, {squad_id = sid, zone_id = mark.zone_id, x = mark.x, y = mark.y, z = mark.z,
                                           since = mark.tick}) end
            end
            table.insert(out, {id = sid, members = #units, calm = (#units > 0 and calm) or nil,
                               worst = worst and STRESS_LABELS[worst] or nil, wounded = wounded > 0 and wounded or nil,
                               parched = okm and ms and ms.parched or nil, ai_orders = ai, player_orders = player,
                               guarding = guarding})
        end
    end
    for k in pairs(marks) do
        if not here[k] then marks[k] = nil; changed = true end
    end
    if changed then U.site_put(GUARD_KEY, marks) end
    return out, guards
end

-- --- the section -------------------------------------------------------------------

function report(txt)
    local now = U.abs_tick()
    local d = note(now)
    local out = {loose = 0, berserk = 0, possessed = 0, dwarves = {}, chronic = 0, hospitals = {}, squads = {},
                 guards = {}, staff_days = STAFF_DAYS, chronic_at = CHRONIC}
    local by = {}
    for _, u in ipairs(citizens()) do
        by[tostring(u.id)] = u
        if in_tantrum(u) then out.loose = out.loose + 1 end
        local m = mood_of(u)
        if m == 'Berserk' then out.berserk = out.berserk + 1 end
        if m == 'Possessed' then out.possessed = out.possessed + 1 end
    end
    local rows = {}
    for key, r in pairs(d.units) do
        local u = by[key]
        if u then
            local row = row_of(u, r, now, txt)
            if row.year >= CHRONIC then out.chronic = out.chronic + 1 end
            table.insert(rows, row)
        end
    end
    table.sort(rows, function(a, b)
        if (a.now or false) ~= (b.now or false) then return a.now == true end
        if a.year ~= b.year then return a.year > b.year end
        return (a.last or 0) > (b.last or 0)
    end)
    for i = 1, math.min(MAX_ROWS, #rows) do out.dwarves[i] = rows[i] end
    out.listed_all = #rows <= MAX_ROWS or nil
    -- the hospitals and squads only while they matter (a tantrum loose, or a
    -- guard to check): the section is in the pulse, and the zones walk every building
    local marks = load_marks()
    if out.loose == 0 and next(marks) == nil then
        out.quiet = true
        return out
    end
    for _, z in ipairs(hospital_zones()) do
        local okp, p = pcall(stand_pos, z)
        table.insert(out.hospitals, {zone_id = z.id, x = okp and p and p.x or nil, y = okp and p and p.y or nil,
                                     z = okp and p and p.z or nil})
    end
    local okM, M = pcall(reqscript, 'ai-military')
    if okM and M then
        local oks, sq, gd = pcall(squad_rows, M, marks)
        if oks then out.squads, out.guards = sq, gd else out.squads_error = tostring(sq):sub(1, 120) end
    end
    return out
end

-- --- actions --------------------------------------------------------------------------

local function reject(msg) return {ok = false, rejected = true, error = msg} end

function guard(squad_id, zone_id, dry_run)
    local zone
    for _, z in ipairs(hospital_zones()) do if z.id == zone_id then zone = z end end
    if not zone then return reject('no hospital zone ' .. tostring(zone_id)) end
    local p = stand_pos(zone)
    if not p then return reject('no tile to stand on in the hospital zone') end
    local M = reqscript('ai-military')
    local r = M.station(squad_id, p.x, p.y, p.z, dry_run)
    if type(r) ~= 'table' then return {ok = false, error = 'the station gave no answer'} end
    r.zone_id = zone_id
    if r.ok and not dry_run then
        local marks = load_marks()
        marks[tostring(squad_id)] = {zone_id = zone_id, x = p.x, y = p.y, z = p.z, tick = U.abs_tick()}
        U.site_put(GUARD_KEY, marks)
    end
    return r
end

function unguard(squad_id, dry_run)
    local marks = load_marks()
    local key = tostring(squad_id)
    if type(marks[key]) ~= 'table' then return reject('the squad guards no hospital for the AI') end
    local M = reqscript('ai-military')
    local sq = M.fort_squad(squad_id)
    if dry_run then return {ok = true, dry_run = true, zone_id = marks[key].zone_id} end
    local removed = 0
    if sq then
        removed = M.drop_orders(sq, function(o)
            local ok, st = pcall(M.station_of, o, squad_id)
            return ok and st ~= nil
        end)
    end
    local zone_id = marks[key].zone_id
    marks[key] = nil
    U.site_put(GUARD_KEY, marks)
    pcall(function()
        local sm = M.station_marks()
        if sm[key] ~= nil then sm[key] = nil; U.site_put(M.STATION_KEY, sm) end
    end)
    return {ok = true, removed = removed, zone_id = zone_id}
end

function step_down(unit_id, medical, dry_run, txt)
    local u = df.unit.find(unit_id)
    if not u then return reject('no such unit') end
    local posts = posts_of(u)
    local med = medical and medical_on(u) or {}
    if #posts == 0 and #med == 0 then return reject('holds no post and no hospital labour') end
    local out = {ok = true, name = name_of(u, txt), posts = {}, labors = {}, dry_run = dry_run or nil}
    local S = reqscript('ai-society')
    for _, p in ipairs(posts) do
        local r = S.vacate_post(p.location_id, unit_id, dry_run, txt)
        if r and r.ok then table.insert(out.posts, r.post or p.post) end
    end
    -- (r9, audit A7 #22) off through the work details (ai-labor), not the
    -- flag alone: a detail holding the dwarf set it back at its next recompute
    local okl, L = pcall(reqscript, 'ai-labor')
    if dry_run then
        for _, l in ipairs(med) do table.insert(out.labors, l) end
    elseif #med > 0 and okl and type(L) == 'table' and L.take_labors then
        local okt, off = pcall(L.take_labors, u, med)
        if okt and type(off) == 'table' then
            for _, l in ipairs(off) do table.insert(out.labors, l) end
        end
    else
        for _, l in ipairs(med) do
            local ok = pcall(function() u.status.labors[df.unit_labor[l]] = false end)
            if ok then table.insert(out.labors, l) end
        end
    end
    if #out.posts == 0 and #out.labors == 0 then return {ok = false, error = 'no post or labour was let go'} end
    return out
end
