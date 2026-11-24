-- ai-society-posts: the locations' posts (staffed, given back, made), the vermin hunters kept from
-- the butcher, the burrows' forwarders (lua/ai-society-burrows.lua), the AI's own alarm and standing down.
--
-- (r8) A part of ai-society, not a script of its own: ai-society.lua loads it
-- into its own environment, so every name here is reqscript('ai-society').name
-- and the names defined there and in the parts before it are in reach.

if not SOCIETY_PART_LOCALS then qerror('ai-society-posts is a part of ai-society; run ai-society') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-posts'] = '0.105.91'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, report_units = SOCIETY_PART_LOCALS.U, SOCIETY_PART_LOCALS.report_citizens, SOCIETY_PART_LOCALS.report_units   -- (r8) the hub's locals

-- A location's occupations (DF's location screen: a hospital's doctor,
-- diagnostician, surgeon and bone doctor, a library's scribes, a tavern's
-- keeper) are records the game makes vacant; the player gives each to a
-- citizen. DFHack's own notifications count a hospital as working only with
-- someone in its posts (internal/notify: DOCTOR or DIAGNOSTICIAN, BONE_DOCTOR,
-- SURGEON), and region2's patients waited 130 days for a diagnosis. The AI
-- fills a vacant post with the citizen best at its trade: never a child, a
-- soldier, an office holder, one already holding a post, or one in a mood.
-- The record gets the dwarf's figure and unit, the dwarf's occupations list
-- the record (as the screen does); read back, undone if not seen.
STAFF_SKILLS = {DOCTOR = {'DRESS_WOUNDS', 'DIAGNOSE', 'SURGERY', 'SET_BONE', 'SUTURE'}, DIAGNOSTICIAN = {'DIAGNOSE'},
                SURGEON = {'SURGERY'}, BONE_DOCTOR = {'SET_BONE'}, SCRIBE = {'WRITING'},
                TAVERN_KEEPER = {}}

local function find_location(loc_id)
    local site = dfhack.world.getCurrentSite()
    for _, b in ipairs(site and site.buildings or {}) do
        if b.id == loc_id then return b end
    end
end

local function skill_of(u, names)
    local n = 0
    for _, name in ipairs(names) do
        pcall(function() n = n + dfhack.units.getNominalSkill(u, df.job_skill[name], true) end)
    end
    return n
end

STAFF_HURT_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
                 'rq_setting', 'rq_traction', 'rq_crutch'}

-- (0.105.47, R2 item 3) the tantrum ledger (lua/ai-tantrums.lua), or nil
local function tantrums()
    local ok, T = pcall(reqscript, 'ai-tantrums')
    return ok and type(T) == 'table' and T or nil
end

local function can_staff(u, T, ledger)
    if not dfhack.units.isAdult(u) or u.military.squad_id ~= -1 then return false end
    -- (0.105.47, R2 item 3, I7c) never a dwarf very unhappy or worse, in a
    -- tantrum, with one in the last 28 days or 3+ this year: E made miserable
    -- chronic tantrum dwarves doctor, surgeon, bone doctor and tavern keeper
    -- (twice with skill 0), and they beat patients to death in their beds.
    -- The stress read here too, so a ledger that fails to load still bars it
    local okc, cat = pcall(dfhack.units.getStressCategory, u)
    if okc and type(cat) == 'number' and cat <= 1 then return false end
    if T then
        local okr, why = pcall(T.staff_refusal, u, ledger)
        if okr and why then return false end
    end
    local okm, mood = pcall(function() return u.mood end)
    if okm and mood ~= nil and mood ~= -1 then return false end
    local okn, list = pcall(dfhack.units.getNoblePositions, u)
    if okn and list and #list > 0 then return false end
    -- (0.104.111) never a wounded dwarf: Teacheroar's surgeon and bone
    -- doctor were patients themselves while five waited up to 820 days
    -- (0.104.150) wounded = bleeding or waiting for a treatment (DF's rq_
    -- flags): the wound list keeps old scars, so after Teacheroar's massacre
    -- nobody was "free" and a tavern stood without a keeper for days
    local okw, wounded = pcall(function()
        if (u.body.blood_count or 0) < (u.body.blood_max or 0) then return true end
        local f = u.health and u.health.flags
        if not f then return false end
        for _, k in ipairs(STAFF_HURT_RQ) do if f[k] then return true end end
        return false
    end)
    if okw and wounded then return false end
    local oko, n = pcall(function() return #u.occupations end)
    return oko and n == 0
end

-- (0.104.111) A post given back: its holder (a doctor who is a patient
-- himself) leaves it, so the staffing rule fills it with someone who can
-- work. {ok, post, name}.
function vacate_post(loc_id, unit_id, dry_run, txt)
    local loc = find_location(loc_id)
    if not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local post
    for _, o in ipairs(loc.occupations) do
        if o.unit_id == unit_id then post = o; break end
    end
    if not post then return {ok = false, rejected = true, error = 'that dwarf holds no post there'} end
    local u = df.unit.find(unit_id)
    local name = u and (txt or tostring)(dfhack.units.getReadableName(u)) or tostring(unit_id)
    local job = tostring(df.occupation_type[post.type] or 'post'):lower():gsub('_', ' ')
    if dry_run then return {ok = true, dry_run = true, post = job, name = name} end
    post.histfig_id, post.unit_id = -1, -1
    if u then
        for i = #u.occupations - 1, 0, -1 do
            if u.occupations[i] == post or u.occupations[i].id == post.id then u.occupations:erase(i) end
        end
    end
    return {ok = true, post = job, name = name}
end

function staff_location(loc_id, occ_type, dry_run, txt)
    local loc = find_location(loc_id)
    if not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local want = STAFF_SKILLS[occ_type]
    if not want then return {ok = false, rejected = true, error = 'the AI does not fill ' .. tostring(occ_type) .. ' posts'} end
    local post
    for _, o in ipairs(loc.occupations) do
        if df.occupation_type[o.type] == occ_type and o.histfig_id == -1 and o.unit_id == -1 then post = o; break end
    end
    if not post then return {ok = false, rejected = true, error = 'no vacant ' .. occ_type:lower() .. ' post there'} end
    local best, best_n
    local T = tantrums()                                        -- (0.105.47)
    local ledger = T and select(2, pcall(T.load)) or nil
    if type(ledger) ~= 'table' then ledger = nil end
    for _, u in ipairs(report_citizens(true)) do
        if can_staff(u, T, ledger) and u.hist_figure_id ~= -1 then
            local n = skill_of(u, want)
            if not best or n > best_n then best, best_n = u, n end
        end
    end
    if not best then
        return {ok = false, rejected = true,
                error = 'nobody free to take the post (no child, soldier, office holder, post holder, patient, '
                        .. 'or dwarf very unhappy or with a tantrum lately)'}
    end
    local name = (txt or tostring)(dfhack.units.getReadableName(best))
    local job = occ_type:lower():gsub('_', ' ')
    if dry_run then return {ok = true, dry_run = true, post = job, unit_id = best.id, name = name, skill = best_n} end
    post.histfig_id = best.hist_figure_id
    post.unit_id = best.id
    best.occupations:insert('#', post)
    -- read back: the post names the dwarf, and the dwarf lists the post
    local seen = false
    for _, o in ipairs(best.occupations) do
        if o == post or o.id == post.id then seen = true end
    end
    if post.unit_id ~= best.id or not seen then
        post.histfig_id, post.unit_id = -1, -1
        for i = #best.occupations - 1, 0, -1 do
            if best.occupations[i] == post then best.occupations:erase(i) end
        end
        return {ok = false, error = 'the post did not take ' .. name .. ', so it was undone'}
    end
    local okl, labors = pcall(function() return give_post_labors(best, occ_type) end)
    return {ok = true, post = job, unit_id = best.id, name = name, skill = best_n,
            labors = okl and #labors > 0 and labors or nil}
end

-- (0.84) Read only: what the game writes for an occupation, so the AI can
-- one day create a post itself (the fort's locations have no post records
-- until the player assigns one: region2, spring y62). Every occupation the
-- world has (up to 12, this site's first), its fields, and its holder's
-- figure links that point at it; the fort's locations with their post counts.
local function fields_of(o, names)
    local out = {}
    for _, k in ipairs(names) do
        local ok, v = pcall(function() return o[k] end)
        if ok and (type(v) == 'number' or type(v) == 'string' or type(v) == 'boolean') then out[k] = v end
    end
    return out
end

function probe_occupations(txt)
    local site = dfhack.world.getCurrentSite()
    local out = {next_id = nil, total = 0, here = {}, elsewhere = {}, locations = {}}
    pcall(function() out.next_id = df.global.occupation_next_id end)
    local all = df.global.world.occupations.all
    out.total = #all
    for _, o in ipairs(all) do
        local here = site and o.site_id == site.id
        local list = here and out.here or out.elsewhere
        if #out.here + #out.elsewhere < 12 and (here or #out.elsewhere < 4) then
            local e = fields_of(o, {'id', 'histfig_id', 'unit_id', 'location_id', 'site_id', 'group_id',
                                    'next_service_order_id'})
            e.type = df.occupation_type[o.type] or tostring(o.type)
            local hf = o.histfig_id ~= -1 and df.historical_figure.find(o.histfig_id)
            if hf then
                e.links = {}
                for _, l in ipairs(hf.entity_links) do
                    local okid, oid = pcall(function() return l.occupation_id end)
                    if okid and oid == o.id then
                        table.insert(e.links, {kind = tostring(l._type), fields = fields_of(l, {'entity_id',
                            'link_strength', 'occupation_id', 'start_year', 'end_year'})})
                    end
                end
                for _, l in ipairs(hf.site_links) do
                    local okid, oid = pcall(function() return l.occupation_id end)
                    if okid and oid == o.id then
                        table.insert(e.links, {kind = tostring(l._type), fields = fields_of(l, {'site', 'sub_id',
                            'entity', 'occupation_id', 'link_strength'})})
                    end
                end
                pcall(function() e.hf_occupation = hf:getOccupation() end)
            end
            local u = o.unit_id ~= -1 and df.unit.find(o.unit_id)
            if u then
                e.unit_lists_it = false
                for _, uo in ipairs(u.occupations) do if uo.id == o.id then e.unit_lists_it = true end end
                e.name = (txt or tostring)(dfhack.units.getReadableName(u))
            end
            table.insert(list, e)
        end
    end
    for _, b in ipairs(site and site.buildings or {}) do
        local okp, n = pcall(function() return #b.occupations end)
        if okp then
            table.insert(out.locations, {id = b.id, type = df.abstract_building_type[b:getType()], posts = n})
        end
    end
    return out
end

-- (0.85) A post the game hasn't made yet, made as DF makes it. Read from the
-- game (region2, spring y62, logs/probe-occupations.json): opening the
-- hospital's posts screen made one vacant record of each kind (doctor,
-- diagnostician, surgeon, bone doctor): its id from occupation_next_id, its
-- type, location_id = the location's id, site_id = the fort's site, holder
-- -1 (figure and unit), group_id -1; in world.occupations.all and the
-- location's occupations; a fort's post has no figure links (a filled one
-- only names the figure and unit, and the dwarf lists it). Only kinds the
-- AI staffs (POST_KINDS), one record a kind, never one that exists.
POST_KINDS = {HOSPITAL = {'DOCTOR', 'DIAGNOSTICIAN', 'SURGEON', 'BONE_DOCTOR'}, INN_TAVERN = {'TAVERN_KEEPER'},
              LIBRARY = {'SCRIBE'}}

function add_posts(loc_id, kinds, dry_run)
    local site = dfhack.world.getCurrentSite()
    local loc = find_location(loc_id)
    if not site or not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local ltype = df.abstract_building_type[loc:getType()]
    local allowed = {}
    for _, k in ipairs(POST_KINDS[ltype] or {}) do allowed[k] = true end
    local have = {}
    for _, o in ipairs(loc.occupations) do have[df.occupation_type[o.type] or ''] = true end
    local add = {}
    for _, k in ipairs(kinds or POST_KINDS[ltype] or {}) do
        if allowed[k] and not have[k] and df.occupation_type[k] ~= nil then table.insert(add, k) end
    end
    if #add == 0 then return {ok = false, rejected = true, error = 'no post to add there'} end
    if dry_run then return {ok = true, dry_run = true, posts = add} end
    local made = {}
    for _, k in ipairs(add) do
        local o = df.occupation:new()
        o.id = df.global.occupation_next_id
        o.type = df.occupation_type[k]
        o.histfig_id, o.unit_id = -1, -1
        o.location_id = loc.id
        o.site_id = site.id
        o.group_id = -1
        df.global.occupation_next_id = o.id + 1
        df.global.world.occupations.all:insert('#', o)
        loc.occupations:insert('#', o)
        table.insert(made, k)
    end
    return {ok = true, posts = made}
end

-- (0.87.3) A post's labours. Read from the game (region2, 6 Timber y62): the
-- diagnostician you gave by hand had DIAGNOSE, but the surgeon, bone doctor
-- and doctor the AI seated had none of SURGERY, BONE_SETTING or DIAGNOSE, so
-- a dwarf needing a bone set lay in a hospital bed 355 days with no job ever
-- made. The game's screen evidently turns a post's labours on; the AI does
-- the same: each holder of a post gets its labours (the unit's own labour
-- flags), read back.
POST_LABORS = {DOCTOR = {'DIAGNOSE', 'SURGERY', 'BONE_SETTING', 'SUTURING', 'DRESSING_WOUNDS'},
               DIAGNOSTICIAN = {'DIAGNOSE'}, SURGEON = {'SURGERY', 'SUTURING'},
               BONE_DOCTOR = {'BONE_SETTING'}}

function give_post_labors(u, post)
    local added = {}
    for _, l in ipairs(POST_LABORS[post] or {}) do
        local id = df.unit_labor[l]
        if id ~= nil and not u.status.labors[id] then
            u.status.labors[id] = true
            if u.status.labors[id] then table.insert(added, l) end
        end
    end
    return added
end

function staff_labors(loc_id, dry_run, txt)
    local loc = find_location(loc_id)
    if not loc then return {ok = false, rejected = true, error = 'no such location in this fort'} end
    local out = {}
    for _, o in ipairs(loc.occupations) do
        local post = df.occupation_type[o.type]
        local u = o.unit_id ~= -1 and df.unit.find(o.unit_id)
        if u and POST_LABORS[post] then
            local missing = {}
            for _, l in ipairs(POST_LABORS[post]) do
                local id = df.unit_labor[l]
                if id ~= nil and not u.status.labors[id] then table.insert(missing, l) end
            end
            if #missing > 0 then
                local added = dry_run and missing or give_post_labors(u, post)
                table.insert(out, {name = (txt or tostring)(dfhack.units.getReadableName(u)), post = post:lower():gsub('_', ' '),
                                   labors = added})
            end
        end
    end
    if #out == 0 then return {ok = false, rejected = true, error = 'every post holder has the labours of the post'} end
    return {ok = true, dry_run = dry_run or nil, given = out}
end

-- --- (0.104.168) vermin hunters ----------------------------------------------
--
-- Teacheroar, 1 Nov: 15-16 citizens a month upset at being "accosted by"
-- vermin they hate (NEAR_HATED_VERMIN, stress 25-50 each). The fort's
-- answer in DF is a vermin hunter (a creature whose caste has HUNTS_VERMIN:
-- the cat), loose in the fort, catching the vermin in the halls and food
-- stores. DFHack's autobutcher (on in this fort, for a herd of 1,077) culls
-- every kind down to 2/4/2/4 and spares only the named or nicknamed, pets,
-- war and hunting animals, the pregnant and those up for adoption
-- (plugins/autobutcher.cpp, isProtectedUnit): the cats went with the ducks.
-- The AI kept a few by giving them a nickname (MOUSER_NICK), which
-- autobutcher respects. (0.105.51) No more: fort C's DF crashed five times
-- in its render path on named animals, three of them the AI's 'Mouser'
-- cats. The kept cats are a list of unit ids now (lua/ai-herd.lua KEPT_KEY:
-- its upkeep() takes autobutcher's mark off them each report, slaughter_one
-- skips them); the old nickname is only cleared (ai-herd clear_ai_nicknames).
MOUSER_NICK = 'Mouser'

local function herd()
    local ok, m = pcall(reqscript, 'ai-herd')
    return ok and m or nil
end

-- The ids of the cats the AI keeps (a set; empty when unreadable).
local function kept_mouser_ids()
    local h = herd()
    if not (h and h.kept_ids) then return {} end
    local ok, ids = pcall(h.kept_ids, 'mousers')
    return ok and type(ids) == 'table' and ids or {}
end

local function hunts_vermin(u)
    local ok, yes = pcall(function()
        local cr = df.creature_raw.find(u.race)
        return cr ~= nil and cr.caste[u.caste].flags.HUNTS_VERMIN
    end)
    return ok and yes == true
end

local function fort_animal(u)
    local ok, yes = pcall(function()
        if dfhack.units.isDead(u) or not dfhack.units.isAnimal(u) then return false end
        return dfhack.units.isFortControlled(u) or (dfhack.units.isTame(u) and dfhack.units.isOwnCiv(u))
    end)
    return ok and yes == true
end

local function kept_hunter(u, kept_ids)
    if kept_ids and kept_ids[u.id] then return true end
    local ok, yes = pcall(function()
        return dfhack.units.isPet(u) or u.name.has_name or (u.name.nickname or '') ~= ''
            or dfhack.units.isAvailableForAdoption(u)
    end)
    return ok and yes == true
end

-- The fort's vermin hunters: {n, loose, caged, marked (for slaughter),
-- kept (loose and safe from autobutcher: pets, named, up for adoption, the
-- AI's), mousers (kept by the AI: its list), races = {CAT = n}}.
function vermin_hunters(units)
    local out = {n = 0, loose = 0, caged = 0, marked = 0, kept = 0, mousers = 0, races = {}}
    local mine = kept_mouser_ids()
    for _, u in ipairs(units or report_units()) do
        if fort_animal(u) and hunts_vermin(u) then
            out.n = out.n + 1
            local okr, r = pcall(function() return df.creature_raw.find(u.race).creature_id end)
            r = okr and r or tostring(u.race)
            out.races[r] = (out.races[r] or 0) + 1
            local okc, caged = pcall(function() return u.flags1.caged end)
            local in_cage = okc and caged
            if in_cage then out.caged = out.caged + 1 else out.loose = out.loose + 1 end
            local okm, marked = pcall(function() return u.flags2.slaughter end)
            if okm and marked then out.marked = out.marked + 1 end
            if kept_hunter(u, mine) and not in_cage then out.kept = out.kept + 1 end     -- loose and safe
            if mine[u.id] then out.mousers = out.mousers + 1 end
        end
    end
    return out
end

-- Keep `want` vermin hunters safe from the butcher: those already safe
-- count; then loose ones, adults first, the marked unmarked, each put on
-- the AI's kept list ((0.105.51) no nickname: lua/ai-herd.lua KEPT_KEY).
-- Never a caged one (it hunts nothing).
function keep_mousers(want, dry_run, txt, units)
    want = math.max(1, math.min(tonumber(want) or 6, 20))
    local h = herd()
    if not (h and h.kept_ids and h.kept_save) then
        return {ok = false, error = 'the kept-animals list (ai-herd) is not loaded'}
    end
    if not dry_run then pcall(h.clear_ai_nicknames) end
    local mine = kept_mouser_ids()
    local kept, cands = 0, {}
    for _, u in ipairs(units or report_units()) do
        if fort_animal(u) and hunts_vermin(u) then
            local okc, caged = pcall(function() return u.flags1.caged end)
            if kept_hunter(u, mine) then
                if not (okc and caged) then kept = kept + 1 end
            elseif not (okc and caged) then
                local oka, adult = pcall(dfhack.units.isAdult, u)
                table.insert(cands, {u = u, adult = oka and adult or false})
            end
        end
    end
    if kept >= want then return {ok = true, unchanged = true, kept = kept} end
    if #cands == 0 then
        return {ok = false, rejected = true, kept = kept,
                error = kept > 0 and 'no other loose vermin hunter to keep' or 'no loose cat or other vermin hunter in the fort'}
    end
    table.sort(cands, function(a, b)
        if a.adult ~= b.adult then return a.adult end
        return a.u.id < b.u.id
    end)
    local named, unmarked = {}, 0
    for _, c in ipairs(cands) do
        if kept >= want then break end
        if not dry_run then
            local okm, marked = pcall(function() return c.u.flags2.slaughter end)
            if okm and marked then c.u.flags2.slaughter = false; unmarked = unmarked + 1 end
            mine[c.u.id] = true
        end
        kept = kept + 1
        local okn, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(c.u)) end)
        table.insert(named, okn and n or tostring(c.u.id))
    end
    if not dry_run then
        local oks, err = h.kept_save('mousers', mine)
        if not oks then
            return {ok = false, kept = kept, named = named, unmarked = unmarked,
                    error = 'the kept-animals list was not saved: ' .. tostring(err)}
        end
    end
    return {ok = true, kept = kept, named = named, unmarked = unmarked, dry_run = dry_run or nil}
end

-- --- the burrows that hold dwarves (lua/ai-society-burrows.lua) ---------------------
--
-- (13c) The recreation, hospital and calm-down burrows moved there; every
-- name they export is still reachable here (the bridge calls them as
-- reqscript('ai-society').<name>). Looked up on call: that module loads this
-- one, so this one must not load it while loading.
-- (0.105.26) kept after the first lookup: reqscript finds the file again on
-- every call (5-7 file checks on Windows), and the forwarders below call it
-- for every name. One check of the file's time a call instead; when the file
-- changed, reqscript again, which reloads it. DFHack reloads a module into the
-- table it already has (its script environment is kept), so the one kept here
-- is the live module before and after a reload.
local BURROWS, BURROWS_PATH, BURROWS_MTIME
local function burrows()
    if BURROWS then
        local ok, t = pcall(function() return dfhack.filesystem.mtime(BURROWS_PATH) end)
        if ok and t ~= nil and t == BURROWS_MTIME then return BURROWS end
    end
    local m = reqscript('ai-society-burrows')
    local okp, p = pcall(function() return dfhack.findScript('ai-society-burrows') end)
    local okt, t = pcall(function() return dfhack.filesystem.mtime(p) end)
    BURROWS, BURROWS_PATH, BURROWS_MTIME = m, okp and p or nil, okt and t or nil
    return m
end
for _, name in ipairs({'fill_recreation', 'badly_wants_friends', 'recreation_status', 'recreation_tick', 'hospital_zones',
                       'well_gives_water', 'is_patient', 'in_quarantine', 'hospital_burrow_status', 'hospital_burrow_tick', 'calm_burrow_status',
                       'calm_burrow_tick', 'weather_keep_in', 'weather_keep_in_status',
                       'release_ai_burrows', 'in_mood'}) do   -- (0.105.48, K3); (0.105.51) in_mood
    _ENV[name] = function(...) return burrows()[name](...) end
end

-- --- (0.105.48, K3) the AI's own alarm, and the AI standing down -------------
--
-- Nothing lowered the AI's alarm when the AI stopped: the brain alone knew it
-- had raised it (memory.ai_alert_raised), and a fort left with it on kept its
-- citizens in the shelter (0.105.8: 31 dead of thirst). The game now keeps
-- the ownership too: act_civ_alert books it (note_ai_alarm), the alert found
-- off forgets it (the player or anyone lowered it), and a stand-down lowers
-- only an alarm the AI raised (never the player's).
AI_ALARM_KEY = 'ai-overseer/ai-alarm'
-- the brain away this long with an enemy still in sight: the AI's alarm
-- lowered anyway (a shelter is not drink and food for ever; the player's
-- own alarm is the player's to keep)
AWAY_ALARM_MAX_TICKS = 3 * 1200

-- The civilian alert on (true / false), or nil when unreadable.
function alarm_on()
    local ok, on = pcall(function() return df.global.plotinfo.alerts.civ_alert_idx ~= 0 end)
    if ok then return on end
    return nil
end

-- The AI raised the alarm (on) or lowered it (not on): booked with the fort.
function note_ai_alarm(on)
    local okt, t = pcall(U.abs_tick)
    pcall(U.site_put, AI_ALARM_KEY, on and {mine = true, tick = okt and t or nil} or {mine = false})
end

-- Is the alarm on now the AI's? (the booking, the alert read on). The
-- alert read off: the booking forgotten (whoever lowered it).
function ai_alarm_mine()
    local okd, d = pcall(U.site_get, AI_ALARM_KEY, {})
    if not okd or type(d) ~= 'table' or d.mine ~= true then return false end
    local on = alarm_on()
    if on == false then
        note_ai_alarm(false)
        return false
    end
    return on == true
end

-- Visible invaders and great dangers on the map (the gate watcher's own
-- look; nil when it can't be read).
local function enemies_in_sight()
    local ok, vis = pcall(function() return reqscript('ai-gates').visible_dangers() end)
    if not ok or type(vis) ~= 'table' then return nil end
    local n = 0
    for _, d in ipairs(vis) do
        if d.invader or d.great then n = n + 1 end
    end
    return n
end

-- The AI's alarm lowered: o.force (halted: always), else only with no
-- invader nor great danger in sight, or once o.away_ticks (how long the
-- brain is away) passes AWAY_ALARM_MAX_TICKS. Returns 'lowered', 'kept'
-- (an enemy in sight), or nil (no alarm of the AI's).
function lower_ai_alarm(o)
    o = o or {}
    if not ai_alarm_mine() then return nil end
    if not o.force then
        local n = enemies_in_sight()
        local long = type(o.away_ticks) == 'number' and o.away_ticks >= AWAY_ALARM_MAX_TICKS
        if (n == nil or n > 0) and not long then return 'kept' end
    end
    if o.dry_run then return 'lowered' end
    local ok = pcall(function() reqscript('gui/civ-alert').clear_alarm() end)
    if not ok then pcall(function() df.global.plotinfo.alerts.civ_alert_idx = 0 end) end
    if alarm_on() == false then
        note_ai_alarm(false)
        pcall(dfhack.gui.showAnnouncement, 'AI Overseer: its civilian alert lowered (' ..
              (o.why or 'the AI stood down') .. ')', COLOR_GREEN, false)
        return 'lowered'
    end
    return 'kept'
end

-- (0.105.48, K3) The AI standing down: halted by the player (o.halted), its
-- brain away (o.away_ticks) or stopping (o.stopping, the way out's leave).
-- Its own alarm lowered (lower_ai_alarm: at once when halted) and every
-- member of its own burrows let out (release_ai_burrows). Never raises.
function stand_down(o)
    o = o or {}
    local why = o.halted and 'the AI is halted' or o.stopping and 'the AI stopped'
        or 'the overseer is away'
    local out = {}
    local oka, a = pcall(lower_ai_alarm, {force = o.halted == true, away_ticks = o.away_ticks,
                                          dry_run = o.dry_run, why = why})
    if oka then out.alarm = a else out.alarm_error = tostring(a):sub(1, 120) end
    local okb, b = pcall(release_ai_burrows, o.dry_run == true)
    if okb and type(b) == 'table' then
        if next(b) ~= nil then out.burrows = b end
    elseif not okb then
        out.burrows_error = tostring(b):sub(1, 120)
    end
    return out
end
