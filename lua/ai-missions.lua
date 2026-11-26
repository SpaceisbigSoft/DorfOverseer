-- The fort's world-map missions (phase 13b, the read side): the armies the
-- fort has sent out (raids, rescues, requests...), its squads and who of
-- them is away, the mission and spoils reports that came back, the foreign
-- sites nearest the fort and how the fort's civ stands with their owners,
-- and, only while the World screen is already open, which missions the game
-- would allow there. The planner decides from this later; this module
-- changes nothing in the game and never opens or changes a screen.
--
-- The field names come from df-structures master and were NOT checked
-- against DF 53.16 / DFHack 53.16-r3. So every read is inside pcall: a field
-- that can't be read gives nil (or 'unknown') and its name goes once into
-- the report's `unknown` list, so a wrong guess shows in the report instead
-- of breaking it.
--
--   report()      the small table for the daily JSON report (lists capped)
--   targets(R, civ, group, fort_site[, screen])  (0.105.39) where a mission
--                 could go: rescue, recover_artifact, explore, raid...
--   away_units()  set {unit_id = true} of citizens away on a mission
--@ module = true

MAX_CONTROLLERS = 10
MAX_SQUADS = 12
MAX_SITES = 8
MAX_UNKNOWN = 16
MAX_TEXT = 48

-- ---------------------------------------------------------------------------
-- reading helpers

-- A reader that remembers what it couldn't read. rd(label, fn) returns fn()
-- or nil; an error (a field the game doesn't have) adds label to unknown.
local function new_reader()
    local seen, list = {}, {}
    local R = {list = list}
    function R.note(label)
        if label and not seen[label] and #list < MAX_UNKNOWN then
            seen[label] = true
            table.insert(list, label)
        end
    end
    function R.rd(label, fn)
        local ok, v = pcall(fn)
        if ok then return v end
        R.note(label)
        return nil
    end
    return R
end

local function short(s, max)
    if type(s) ~= 'string' then return nil end
    s = s:gsub('[%c]', ' ')
    if s == '' then return nil end
    return s:sub(1, max or MAX_TEXT)
end

-- an enum value's name (df.X[v]), or the number when the enum has no name
-- (r6) kept here: this module takes no ai-util at load (its tests run it
-- without one); enum_name and name_of (a translated name, not a unit's) are
-- its own: ai-util's enum_name_num is the same rule.
local function enum_name(enum, v)
    if v == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return tonumber(v) and tostring(v) or nil
end

-- A DF name in words (dfhack.TranslateName was renamed in DFHack 50.15).
local function name_of(name)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, true) end)
    if ok and type(s) == 'string' and s ~= '' then return short(s) end
    ok, s = pcall(function() return dfhack.TranslateName(name, true) end)
    if ok and type(s) == 'string' and s ~= '' then return short(s) end
    return nil
end

-- the items of a DF vector (0-based, #v) or a plain Lua list (tests)
local function each(v)
    local out = {}
    if v == nil then return out end
    local ok, n = pcall(function() return #v end)
    if not ok or type(n) ~= 'number' then return out end
    local ok0, first = pcall(function() return v[0] end)
    local base = (ok0 and first ~= nil) and 0 or 1
    for i = base, base + n - 1 do
        local okv, x = pcall(function() return v[i] end)
        if okv and x ~= nil then table.insert(out, x) end
    end
    return out
end

local function int(v)
    v = tonumber(v)
    return v and math.tointeger(v) or v
end

-- ---------------------------------------------------------------------------
-- the fort, its squads and who is away

local function fort_ids(R)
    local civ = R.rd('plotinfo.civ_id', function() return df.global.plotinfo.civ_id end)
    local group = R.rd('plotinfo.group_id', function() return df.global.plotinfo.group_id end)
    local site = R.rd('plotinfo.site_id', function() return df.global.plotinfo.site_id end)
    return int(civ), int(group), int(site)
end

-- Is a squad member (a historical figure id) away from the fort? On an
-- army's roll (whereabouts.army_id), or with no unit on the map: no unit,
-- an inactive one, or one that has left. The dead are not away.
-- Returns away, unit id, on_army. (0.105.48, K9) Only on_army proves a
-- mission: a member merely gone from the map (left, sent away, a unit gone)
-- counts as away only in a squad with an army controller (fort_squads).
local function member_away(R, hfid)
    local hf = R.rd('historical_figure.find', function() return df.historical_figure.find(hfid) end)
    if not hf then return false, nil end
    local died = R.rd('historical_figure.died_year', function() return hf.died_year end)
    if died and died ~= -1 then return false, nil end
    local unit_id = int(R.rd('historical_figure.unit_id', function() return hf.unit_id end))
    local army = R.rd('hf.info.whereabouts.army_id', function() return hf.info.whereabouts.army_id end)
    if army and army >= 0 then return true, unit_id, true end
    if not unit_id or unit_id < 0 then return false, nil end   -- never had a unit: not ours to say
    local unit = R.rd('unit.find', function() return df.unit.find(unit_id) end)
    if not unit then return true, unit_id end
    local dead = R.rd('unit.flags2.killed', function() return unit.flags2.killed end)
    if dead then return false, unit_id end
    local inactive = R.rd('unit.flags1.inactive', function() return unit.flags1.inactive end)
    -- 'left' is an older name of the same idea; missing is not worth a note
    local okl, left = pcall(function() return unit.flags1.left end)
    if inactive or (okl and left) then return true, unit_id end
    return false, unit_id
end

-- the fort's squads: [{id, name, members, away, controller, away_units}]
local function fort_squads(R, group)
    local out = {}
    local ent = group and R.rd('historical_entity.find', function() return df.historical_entity.find(group) end)
    if not ent then return out end
    local ids = R.rd('entity.squads', function() return ent.squads end)
    for _, sid in ipairs(each(ids)) do
        local sq = R.rd('squad.find', function() return df.squad.find(sid) end)
        if sq then
            local s = {id = int(sid), members = 0, away = 0, away_units = {}, units = {}}
            local alias = R.rd('squad.alias', function() return sq.alias end)
            s.name = short(alias) or R.rd('squad.name', function() return name_of(sq.name) end)
            local ctl = R.rd('squad.assigned_army_controller_id', function() return sq.assigned_army_controller_id end)
            if ctl and ctl >= 0 then s.controller = int(ctl) end
            local positions = R.rd('squad.positions', function() return sq.positions end)
            for _, p in ipairs(each(positions)) do
                local occ = R.rd('squad_position.occupant', function() return p.occupant end)
                if occ and occ ~= -1 then
                    s.members = s.members + 1
                    local away, uid, on_army = member_away(R, occ)
                    -- (0.105.48, K9, the audit: squads 'away: 1' with nobody out
                    -- blocked every mission) gone from the map without an army's
                    -- roll and with no controller: not on a mission (counted as gone)
                    local gone = false
                    if away and not on_army and not s.controller then
                        away, gone = false, true
                        s.gone = (s.gone or 0) + 1
                    end
                    if not away and not gone and uid and uid >= 0 then table.insert(s.units, uid) end   -- (0.105.47) home: the way-out check
                    if away then
                        s.away = s.away + 1
                        if uid and uid >= 0 then table.insert(s.away_units, uid) end
                    end
                end
            end
            table.insert(out, s)
        end
    end
    return out
end

-- ---------------------------------------------------------------------------
-- the fort's army controllers (its missions)

local RETURN_FLAGS = {'RETURNING_HOME', 'RETURNING'}

-- the goal's own data (data.goal_<goal in lower case>) and its flags
local function returning(R, c, goal)
    if not goal or not goal:match('^[%u_]+$') then return nil end
    local key = 'goal_' .. goal:lower()
    local d = R.rd('army_controller.data.' .. key, function() return c.data[key] end)
    if d == nil then return nil end
    for _, f in ipairs(RETURN_FLAGS) do
        local ok, v = pcall(function() return d.flag[f] end)
        if ok and v ~= nil then return v == true end
    end
    return nil
end

local function controllers(R, civ, group, squad_ctl)
    local all = R.rd('world.army_controllers.all', function() return df.global.world.army_controllers.all end)
    local list = each(all)
    if all == nil then
        -- second way in: the fort's own entities' lists
        for _, eid in ipairs({group, civ}) do
            local e = eid and R.rd('historical_entity.find', function() return df.historical_entity.find(eid) end)
            local v = e and R.rd('entity.army_controllers', function() return e.army_controllers end)
            for _, c in ipairs(each(v)) do
                if type(c) == 'number' then
                    c = R.rd('army_controller.find', function() return df.army_controller.find(c) end)
                end
                if c then table.insert(list, c) end
            end
        end
    end
    local out, seen = {}, {}
    for _, c in ipairs(list) do
        local id = int(R.rd('army_controller.id', function() return c.id end))
        local eid = R.rd('army_controller.entity_id', function() return c.entity_id end)
        local ours = (eid ~= nil and (eid == civ or eid == group)) or (id ~= nil and squad_ctl[id])
        if ours and id and not seen[id] then
            seen[id] = true
            local goal = enum_name(df.army_controller_goal_type,
                R.rd('army_controller.goal', function() return c.goal end))
            local e = {id = id, goal = goal or 'unknown',
                       site_id = int(R.rd('army_controller.site_id', function() return c.site_id end)),
                       squads = {}, away = 0, entity_id = eid and int(eid) or nil}
            if e.site_id == -1 then e.site_id = nil end
            if goal == 'SITE_INVASION' then
                local inv = R.rd('army_controller.data.goal_site_invasion',
                    function() return c.data.goal_site_invasion end)
                if inv then
                    e.intent = enum_name(df.invasion_intent_type,
                        R.rd('goal_site_invasion.invasion_intent', function() return inv.invasion_intent end))
                    local st = R.rd('goal_site_invasion.invasion_stage', function() return inv.invasion_stage end)
                    e.stage = (df.invasion_stage_type and enum_name(df.invasion_stage_type, st)) or int(st)
                end
            end
            e.returning = returning(R, c, goal)
            local sq = R.rd('army_controller.assigned_squads', function() return c.assigned_squads end)
            for _, s in ipairs(each(sq)) do table.insert(e.squads, int(s)) end
            -- (0.105.47) when it was set up (start_year / start_season_cont)
            -- and its messengers, for the departure watch
            local oky, y, yt = pcall(function() return c.year, c.year_tick end)
            if oky and type(y) == 'number' and type(yt) == 'number' then e.since = {year = int(y), tick = int(yt)} end
            local oke, epp = pcall(function() return c.assigned_epp_epp_id end)
            if oke and epp ~= nil then
                e.epp = {}
                for _, x in ipairs(each(epp)) do table.insert(e.epp, int(x)) end
            end
            table.insert(out, e)
        end
    end
    return out
end

-- members of the armies the fort's controllers lead: {controller id = n}
-- and their units (hf -> unit) for away_units
local function army_members(R, ctl_ids)
    local counts, units, armies = {}, {}, {}
    local all = R.rd('world.armies.all', function() return df.global.world.armies.all end)
    if all == nil then armies = nil end
    for _, a in ipairs(each(all)) do
        local cid = R.rd('army.controller_id', function() return a.controller_id end)
        if cid and ctl_ids[cid] then
            armies[cid] = true           -- (0.105.47) the controller has an army: the mission set out
            local m = R.rd('army.members', function() return a.members end)
            for _, n in ipairs(each(m)) do
                counts[cid] = (counts[cid] or 0) + 1
                local nem = R.rd('nemesis_record.find', function() return df.nemesis_record.find(n.nemesis_id) end)
                local uid = nem and R.rd('nemesis.unit_id', function()
                    local oku, u = pcall(function() return nem.unit_id end)
                    if oku and u then return u end
                    return df.historical_figure.find(nem.figure_id).unit_id
                end)
                if uid and uid >= 0 then units[int(uid)] = true end
            end
        end
    end
    return counts, units, armies
end

-- (0.105.47) Who a mission waits on before it sets out, and what they are
-- doing (live 14 Nov 17:07: the messenger of a set-up Make contact on the
-- map, no job, path goal MarauderMill, 15 game-minutes on; no army yet).
-- Up to 3 {unit_id, path_goal, job}: the controller's squads' members and
-- its messengers (assigned_epp_epp_id, the fort group's position
-- assignments).
WAIT_PEOPLE = 3

local function unit_doing(R, uid)
    local u = uid and uid >= 0 and R.rd('unit.find', function() return df.unit.find(uid) end)
    if not u then return nil end
    local e = {unit_id = int(uid)}
    pcall(function() e.path_goal = df.unit_path_goal[u.path.goal] end)
    pcall(function()
        local j = u.job.current_job
        if j then e.job = df.job_type[j.job_type] end
    end)
    pcall(function() e.on_map = not u.flags1.inactive end)
    return e
end

local function waiting_people(R, c, group)
    local out = {}
    local function add_hf(hfid)
        if #out >= WAIT_PEOPLE or not hfid or hfid < 0 then return end
        local hf = R.rd('historical_figure.find', function() return df.historical_figure.find(hfid) end)
        local uid = hf and R.rd('historical_figure.unit_id', function() return hf.unit_id end)
        local e = unit_doing(R, uid)
        if e then table.insert(out, e) end
    end
    for _, sid in ipairs(c.squads or {}) do
        local sq = R.rd('squad.find', function() return df.squad.find(sid) end)
        for _, p in ipairs(each(sq and R.rd('squad.positions', function() return sq.positions end))) do
            add_hf(R.rd('squad_position.occupant', function() return p.occupant end))
        end
    end
    if c.epp and #c.epp > 0 then
        local ent = group and R.rd('historical_entity.find', function() return df.historical_entity.find(group) end)
        local asg = ent and R.rd('entity.positions.assignments', function() return ent.positions.assignments end)
        for _, a in ipairs(each(asg)) do
            local okid, id = pcall(function() return a.id end)
            for _, want in ipairs(c.epp) do
                if okid and id == want then add_hf(R.rd('entity_position_assignment.histfig', function() return a.histfig end)) end
            end
        end
    end
    -- (0.105.47, J17) a traveller's pet held in a zone, a cage or a chain:
    -- the soldier waits for it (live 17:38: a sheep in an AI pasture, a
    -- peafowl), so the watcher names it
    if #out > 0 and type(reqscript) == 'function' then
        local set = {}
        for _, e in ipairs(out) do set[e.unit_id] = true end
        local okp, held = pcall(function() return reqscript('ai-raids').held_pets(set) end)
        if okp and type(held) == 'table' then
            for _, e in ipairs(out) do
                local p = held[e.unit_id] and held[e.unit_id][1]
                if p then e.pet = {pet = p.pet, held = p.held, ai = p.ai} end
            end
        end
    end
    return out
end

-- ---------------------------------------------------------------------------
-- mission and spoils reports

local function reports(R)
    local out = {n = 0, unviewed = 0}
    local list = R.rd('world.status.mission_reports', function() return df.global.world.status.mission_reports end)
    local items = each(list)
    out.n = #items
    for _, r in ipairs(items) do
        local viewed = R.rd('mission_report.flags.viewed', function() return r.flags.viewed end)
        if viewed == false then out.unviewed = out.unviewed + 1 end
    end
    local last = items[#items]
    if last then
        out.last = {title = short(R.rd('mission_report.title', function() return last.title end), 60),
                    year = int(R.rd('mission_report.year', function() return last.year end))}
    end
    -- the "new report" lights in the game's status flags
    local new = {}
    for _, f in ipairs({'mission', 'spoils', 'tribute'}) do
        local v = R.rd('world.status.flags.' .. f, function() return df.global.world.status.flags[f] end)
        if v == true then table.insert(new, f) end
    end
    if #new > 0 then out.new = new end
    return out
end

-- how many items a spoils report lists: its counts summed, or its entries
local function spoils_items(R, r)
    for _, key in ipairs({'item_counts', 'item_count', 'counts'}) do
        local ok, v = pcall(function() return r[key] end)
        if ok and v ~= nil then
            local n = 0
            for _, x in ipairs(each(v)) do n = n + (tonumber(x) or 0) end
            return n
        end
    end
    local ok, v = pcall(function() return r.item_types end)
    if ok and v ~= nil then return #each(v) end
    R.note('spoils_report.item_counts')
    return nil
end

local function spoils(R)
    local out = {n = 0}
    local list = R.rd('world.status.spoils_reports', function() return df.global.world.status.spoils_reports end)
    local items = each(list)
    out.n = #items
    local last = items[#items]
    if last then
        local tribute = R.rd('spoils_report.flags.tribute', function() return last.flags.tribute end)
        out.last = {kind = tribute == true and 'tribute' or 'spoils', items = spoils_items(R, last)}
    end
    return out
end

-- ---------------------------------------------------------------------------
-- sites near the fort and how the fort's civ stands with their owners

-- (0.105.33 review) Skirmishing is hostile too, as in ai-diplomacy's HOSTILE
local function hostile(rel)
    return type(rel) == 'string' and (rel:find('War') ~= nil or rel == 'Skirmishing')
end

-- (r2 h9) How the fort stands with an entity, read both ways. A5 finding 2:
-- 1210 of 1429 site relations read "unknown" in every fort, because only the
-- fort civ's own diplomacy list was read, by the site's civ or owner id, and
-- DF lists there only the few civilisations it has met (B: 4 entries, three
-- goblin civs and one dwarven). Now: the fort civ's list and the fort's own
-- government's (plotinfo.group_id), for the site's civ and its owner (a site
-- government, a band); then the other side's lists for the fort civ or its
-- government (a tribute the other side accepts is one the fort offers); and
-- when both sides were read and neither lists the other, DF's NoContact
-- (never met). 'unknown' (nil here) stays only for what couldn't be read.
local SWAP = {AcceptingTribute = 'OfferingTribute', OfferingTribute = 'AcceptingTribute'}

local function rel_list(R, ent)
    if not ent then return nil end
    local states = R.rd('entity.relations.diplomacy.state', function() return ent.relations.diplomacy.state end)
    if states == nil then return nil end
    local out = {}
    for _, st in ipairs(each(states)) do
        local gid = R.rd('diplomacy_state.group_id', function() return st.group_id end)
        local r = R.rd('diplomacy_state.relation', function() return st.relation end)
        if gid and r ~= nil then out[gid] = enum_name(df.diplomacy_state_type, r) end
    end
    return out
end

function resolver(R, civ, group)
    R = R or {rd = function(_, fn) local ok, v = pcall(fn); if ok then return v end end, note = function() end}
    local function find(id)
        if not id or id < 0 then return nil end
        return R.rd('historical_entity.find', function() return df.historical_entity.find(id) end)
    end
    local mine = rel_list(R, find(civ))
    local gov = group and group ~= civ and rel_list(R, find(group)) or nil
    local theirs = {}
    local function other(id)
        if theirs[id] == nil then theirs[id] = rel_list(R, find(id)) or false end
        return theirs[id] or nil
    end
    return function(...)
        local ids = {...}
        for i = 1, select('#', ...) do
            local id = ids[i]
            if id and id >= 0 then
                if mine and mine[id] then return mine[id] end
                if gov and gov[id] then return gov[id] end
            end
        end
        local read_other = false
        for i = 1, select('#', ...) do
            local id = ids[i]
            if id and id >= 0 then
                local o = other(id)
                if o then
                    read_other = true
                    local r = (civ and o[civ]) or (group and o[group])
                    if r then return SWAP[r] or r end
                end
            end
        end
        if mine and read_other then return 'NoContact' end
        return nil
    end
end

-- (r9, audit A8 #19) Who holds a site now, and that holder's civilisation.
-- df-structures: world_site.civ_id is the MAKER (maker_civ_id) and
-- cur_owner_id the holder (specialization_enid, a site government or a band).
-- Read by the maker alone, a goblin-built site the fort's civ holds read
-- hostile and a dwarf-built one the goblins hold read ours. Now the holder
-- first; its civilisation is itself when it is one, else its PARENT link's
-- (entity_links, ID_IS_UMBRELLA_CIV) when that is a civilisation, else the
-- maker (nobody holds it, or the holder's civ can't be read). Returns owner, owner_civ, maker (ids or nil).
function site_owner(s)
    local okc, c = pcall(function() return s.civ_id end)
    if not okc or type(c) ~= 'number' or c < 0 then c = nil end
    local oko, cur = pcall(function() return s.cur_owner_id end)   -- newer saves only
    if not oko or type(cur) ~= 'number' or cur < 0 then cur = nil end
    if not cur then return c, c, c end
    -- the holders' civs cached a minute (a walk asks for every site's holder)
    local okt, t = pcall(function() return os.time() end)
    if not okt or type(t) ~= 'number' then t = 0 end
    if not OWNER_CIV or t - (OWNER_CIV_AT or 0) > 60 then OWNER_CIV, OWNER_CIV_AT = {}, t end
    local cached = OWNER_CIV[cur]
    if cached ~= nil then return cur, cached or c, c end
    local owner_civ
    pcall(function()
        local e = df.historical_entity.find(cur)
        if not e then return end
        if df.historical_entity_type[e.type] == 'Civilization' then owner_civ = cur return end
        for _, l in ipairs(each(e.entity_links)) do
            if df.entity_entity_link_type[l.type] == 'PARENT' then
                local p = df.historical_entity.find(l.target)
                if p and df.historical_entity_type[p.type] == 'Civilization' then owner_civ = l.target return end
            end
        end
    end)
    OWNER_CIV[cur] = owner_civ or false
    -- the holder's civilisation not found (no PARENT link read): the maker, as
    -- before (the safe side: a site built by the fort's civ is never attacked)
    return cur, owner_civ or c, c
end

local function sites(R, civ, group, fort_site)
    local out = {n_hostile = 0, n_neutral = 0, n_unknown = 0, nearest = {}, ruins = {}}
    -- the fort's diplomacy, both ways (r2 h9: resolver)
    local rel_of = resolver(R, civ, group)
    local all = R.rd('world.world_data.sites', function() return df.global.world.world_data.sites end)
    local list = each(all)
    local fx, fy
    for _, s in ipairs(list) do
        local okid, id = pcall(function() return s.id end)
        if okid and id == fort_site then
            fx = R.rd('world_site.pos', function() return s.pos.x end)
            fy = R.rd('world_site.pos', function() return s.pos.y end)
            break
        end
    end
    if not fx then R.note('fort site position') end
    -- (0.104.99) ruins: the sites a mission can Explore (DF's RUINED flag, or no
    -- owner and no people), nearest first, with the way to them from the fort
    local ruins = {}
    for _, s in ipairs(list) do
        pcall(function()
            if s.id == fort_site or not fx then return end
            local okf, ruined = pcall(function() return s.flag.RUINED end)
            if not okf then okf, ruined = pcall(function() return s.flag[df.site_flag_type.RUINED] end) end
            local okh, hidden = pcall(function() return s.flag.HIDDEN end)
            if not okh then okh, hidden = pcall(function() return s.flag[df.site_flag_type.HIDDEN] end) end
            out.flags_read = (out.flags_read or 0) + (okf and 1 or 0)
            if okf and ruined then out.n_ruined_all = (out.n_ruined_all or 0) + 1 end
            local okc, cur = pcall(function() return s.cur_owner_id end)
            local okp, pop = pcall(function() return s.resident_count end)
            local empty = (okc and cur ~= nil and cur < 0) and (s.civ_id == nil or s.civ_id < 0) and (okp and pop == 0)
            if not ((okf and ruined) or empty) or (okh and hidden) then return end
            local dx, dy = s.pos.x - fx, s.pos.y - fy
            local way = ((dy < 0 and 'north' or dy > 0 and 'south' or '') .. (dx > 0 and 'east' or dx < 0 and 'west' or ''))
            table.insert(ruins, {id = int(s.id), dist = math.max(math.abs(dx), math.abs(dy)), way = way ~= '' and way or 'here',
                                 site = s})
        end)
    end
    table.sort(ruins, function(a, b) return a.dist < b.dist or (a.dist == b.dist and a.id < b.id) end)
    for i = 1, math.min(6, #ruins) do
        local e = ruins[i]
        table.insert(out.ruins, {id = e.id, dist = int(e.dist), way = e.way,
            name = R.rd('world_site.name', function() return name_of(e.site.name) end),
            type = enum_name(df.world_site_type, R.rd('world_site.type', function() return e.site.type end))})
    end
    out.n_ruins = #ruins
    local cands = {}
    for _, s in ipairs(list) do
        local ok, e = pcall(function()
            local id = s.id
            if id == fort_site then return nil end
            -- (r9, A8 #19) the holder, not the maker (site_owner)
            local who, civ_id = site_owner(s)
            if not who then return nil end                                 -- empty or ruined
            if civ_id == civ or who == civ or who == group then return nil end   -- our own
            local r = rel_of(civ_id, who)
            local x, y = s.pos.x, s.pos.y
            return {id = int(id), owner_civ = int(civ_id or who), relation = r or 'unknown',
                    x = x, y = y, site = s}
        end)
        if not ok then R.note('world_site fields')
        elseif e then
            if hostile(e.relation) then out.n_hostile = out.n_hostile + 1
            elseif e.relation == 'unknown' then out.n_unknown = out.n_unknown + 1
            else out.n_neutral = out.n_neutral + 1 end
            if fx and e.x then
                -- world tiles: the larger of the two steps (diagonals count one)
                e.dist = math.max(math.abs(e.x - fx), math.abs(e.y - fy))
                table.insert(cands, e)
            end
        end
    end
    table.sort(cands, function(a, b) return a.dist < b.dist or (a.dist == b.dist and a.id < b.id) end)
    -- (0.105.47) the fort's landmass: a site on another is marked
    -- inaccessible (DF's verdict for an island), so Make contact skips it
    local fort_land
    for _, s in ipairs(list) do
        local okid, id = pcall(function() return s.id end)
        if okid and id == fort_site then fort_land = site_landmass(s) break end
    end
    for i = 1, math.min(MAX_SITES, #cands) do
        local e = cands[i]
        local s = e.site
        table.insert(out.nearest, {
            id = e.id, owner_civ = e.owner_civ, relation = e.relation, dist = int(e.dist),
            name = R.rd('world_site.name', function() return name_of(s.name) end),
            type = enum_name(df.world_site_type, R.rd('world_site.type', function() return s.type end)),
            inaccessible = other_landmass(fort_land, site_landmass(s)) and 'another landmass' or nil,
        })
    end
    return out
end

-- (r9) This file's locals the later parts use, handed on in one table (each
-- part takes back the ones it uses as locals of its own). All are functions
-- never assigned again, so every part holds the same ones.
MISSIONS_PART_LOCALS = {new_reader = new_reader, short = short, enum_name = enum_name, name_of = name_of, each = each, int = int, fort_ids = fort_ids, fort_squads = fort_squads, controllers = controllers, army_members = army_members, waiting_people = waiting_people, reports = reports, spoils = spoils, hostile = hostile, sites = sites}

---------------------------------------------------------------------------
-- (r9) The rest of the missions' read side lives in parts beside this file
-- (ai-missions-<part>.lua): targets (the World screen, the landmasses, the
-- relations and targets: where a mission could go) and report (status_of,
-- report, away_units, probe_screen). Each runs in this module's own
-- environment, so its names stay reqscript('ai-missions').name for the bridge
-- and the other modules, and a test's swap (M.fn = ...) reaches every part.
-- They load in this order, the old file's. DFHack reloads a module when its
-- own file changes: a change to a part alone is picked up once ai-missions.lua
-- is touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'targets', 'report'}
-- each part marks the version it came with (the bridge's `version` lists one
-- that differs from BRIDGE_VERSION); started afresh at each load, so a part
-- that failed to load shows as unmarked
PART_VERSIONS = {['ai-missions'] = '0.105.125'}   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local name = 'ai-missions-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-missions: ' .. name .. '.lua is missing (it goes beside ai-missions.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
