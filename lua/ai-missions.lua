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
local function member_away(R, hfid)
    local hf = R.rd('historical_figure.find', function() return df.historical_figure.find(hfid) end)
    if not hf then return false, nil end
    local died = R.rd('historical_figure.died_year', function() return hf.died_year end)
    if died and died ~= -1 then return false, nil end
    local unit_id = int(R.rd('historical_figure.unit_id', function() return hf.unit_id end))
    local army = R.rd('hf.info.whereabouts.army_id', function() return hf.info.whereabouts.army_id end)
    if army and army >= 0 then return true, unit_id end
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
            local s = {id = int(sid), members = 0, away = 0, away_units = {}}
            local alias = R.rd('squad.alias', function() return sq.alias end)
            s.name = short(alias) or R.rd('squad.name', function() return name_of(sq.name) end)
            local ctl = R.rd('squad.assigned_army_controller_id', function() return sq.assigned_army_controller_id end)
            if ctl and ctl >= 0 then s.controller = int(ctl) end
            local positions = R.rd('squad.positions', function() return sq.positions end)
            for _, p in ipairs(each(positions)) do
                local occ = R.rd('squad_position.occupant', function() return p.occupant end)
                if occ and occ ~= -1 then
                    s.members = s.members + 1
                    local away, uid = member_away(R, occ)
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
            table.insert(out, e)
        end
    end
    return out
end

-- members of the armies the fort's controllers lead: {controller id = n}
-- and their units (hf -> unit) for away_units
local function army_members(R, ctl_ids)
    local counts, units = {}, {}
    local all = R.rd('world.armies.all', function() return df.global.world.armies.all end)
    for _, a in ipairs(each(all)) do
        local cid = R.rd('army.controller_id', function() return a.controller_id end)
        if cid and ctl_ids[cid] then
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
    return counts, units
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

local function sites(R, civ, group, fort_site)
    local out = {n_hostile = 0, n_neutral = 0, n_unknown = 0, nearest = {}, ruins = {}}
    -- the fort civ's diplomacy: entity id -> relation name
    local rel = {}
    local civ_ent = civ and R.rd('historical_entity.find', function() return df.historical_entity.find(civ) end)
    local states = civ_ent and R.rd('entity.relations.diplomacy.state',
        function() return civ_ent.relations.diplomacy.state end)
    for _, st in ipairs(each(states)) do
        local gid = R.rd('diplomacy_state.group_id', function() return st.group_id end)
        local r = R.rd('diplomacy_state.relation', function() return st.relation end)
        if gid then rel[gid] = enum_name(df.diplomacy_state_type, r) end
    end
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
            local civ_id = s.civ_id
            local okc, cur = pcall(function() return s.cur_owner_id end)   -- newer saves only
            if not okc then cur = nil end
            local who = (cur and cur >= 0 and cur) or (civ_id and civ_id >= 0 and civ_id) or nil
            if not who then return nil end                                 -- empty or ruined
            if civ_id == civ or who == civ or who == group then return nil end   -- our own
            local r = rel[civ_id] or rel[who]
            local x, y = s.pos.x, s.pos.y
            return {id = int(id), owner_civ = int(civ_id ~= -1 and civ_id or who), relation = r or 'unknown',
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
    for i = 1, math.min(MAX_SITES, #cands) do
        local e = cands[i]
        local s = e.site
        table.insert(out.nearest, {
            id = e.id, owner_civ = e.owner_civ, relation = e.relation, dist = int(e.dist),
            name = R.rd('world_site.name', function() return name_of(s.name) end),
            type = enum_name(df.world_site_type, R.rd('world_site.type', function() return s.type end)),
        })
    end
    return out
end

-- ---------------------------------------------------------------------------
-- the World screen, only when the player (or DF) already has it open

local function world_screen()
    if not df.viewscreen_worldst then return nil end
    local ok, scr = pcall(function() return dfhack.gui.getViewscreenByType(df.viewscreen_worldst, 0) end)
    if ok and scr then return scr end
    -- walk the screen stack ourselves (an older getViewscreenByType)
    local okw, found = pcall(function()
        local s = df.global.gview.view.child
        local n = 0
        while s and n < 50 do
            if df.viewscreen_worldst:is_instance(s) then return s end
            s, n = s.child, n + 1
        end
    end)
    return okw and found or nil
end

local function screen(R)
    local scr = world_screen()
    if not scr then return nil end
    local out = {allowed = {}}
    out.view_mode = enum_name(df.world_view_mode_type, R.rd('viewscreen_worldst.view_mode', function() return scr.view_mode end))
    local fs = R.rd('viewscreen_worldst.focus_site', function() return scr.focus_site end)
    if type(fs) == 'number' then
        out.focus_site = fs >= 0 and int(fs) or nil
    elseif fs ~= nil then
        local okid, id = pcall(function() return fs.id end)
        out.focus_site = okid and int(id) or nil
    end
    local nm = R.rd('viewscreen_worldst.new_mission', function() return scr.new_mission end)
    if nm ~= nil then
        local E = df.army_controller_goal_type
        local first = math.max(0, tonumber(E and E._first_item) or 0)
        local last = tonumber(E and E._last_item) or 15
        for g = first, last do
            local okv, v = pcall(function() return nm[g] end)   -- past the array's end: an error, skipped
            local name = enum_name(E, g)
            if okv and v ~= nil and name then
                out.allowed[name] = enum_name(df.world_new_mission_type, v) or 'unknown'
            end
        end
    end
    return out
end

-- ---------------------------------------------------------------------------
-- (0.105.39) targets: where a mission could go and why, best first.
--
--   rescue            a citizen (a historical figure of the fort's group)
--                     held elsewhere: a PRISONER/SLAVE link to another
--                     entity, a PRISON_* site link, or an abduction event
--                     (newest events only) and not back home
--   recover_artifact  an artifact the fort's group (or civ) claims, last
--                     known at another site
--   explore           a ruin (RUINED, or no owner and nobody living there)
--   raid / pillage    a site of a civ the fort's civ is hostile to
--   tribute / conquer only a hostile site smaller than the fort (its
--                     resident_count below the group's member count) and
--                     near; at war for conquer. Unknown sizes: no entry.
--
-- `ready` is the open World screen's verdict for the goal, only when the
-- screen's focus site is the target's site. Everything is read through R.rd;
-- the walk stops after TARGET_BUDGET seconds (dfhack.getTickCount, os.clock
-- without it) and says partial.

MAX_TARGETS = 12
TARGET_NAME = 40
TARGET_BUDGET = 0.05
MAX_EVENTS = 4000          -- the newest history events looked at for abductions
TRIBUTE_DIST = 20
CONQUER_DIST = 10
GOAL_ORDER = {'rescue', 'recover_artifact', 'explore', 'raid', 'pillage', 'tribute', 'conquer'}
EXPLORE_NOT = {Cave = true, LairShrine = true}   -- ruined, but no ruin to explore
GOAL_CAP = {rescue = 4, recover_artifact = 3, explore = 2, raid = 2, pillage = 1, tribute = 1, conquer = 1}
-- the army_controller_goal_type the World screen's new_mission[] holds for each goal
DF_GOAL = {rescue = 'RESCUE_HF', recover_artifact = 'RECOVER_ARTIFACT', explore = 'SITE_INVASION',
           raid = 'SITE_INVASION', pillage = 'SITE_INVASION', tribute = 'SITE_INVASION',
           conquer = 'SITE_INVASION'}

-- the items of a vector, visited until fn returns true; newest first with
-- rev, at most max of them
local function walk(v, fn, rev, max)
    if v == nil then return end
    local ok, n = pcall(function() return #v end)
    if not ok or type(n) ~= 'number' or n <= 0 then return end
    local ok0, first = pcall(function() return v[0] end)
    local base = (ok0 and first ~= nil) and 0 or 1
    local lo, hi = base, base + n - 1
    if max and n > max then
        if rev then lo = hi - max + 1 else hi = lo + max - 1 end
    end
    local a, b, step = lo, hi, 1
    if rev then a, b, step = hi, lo, -1 end
    for i = a, b, step do
        local okv, x = pcall(function() return v[i] end)
        if okv and x ~= nil and fn(x) then return end
    end
end

-- seconds: DFHack's millisecond clock (wall time) when there is one, else
-- os.clock (CPU time: the tests)
local function clock()
    local okd, ms = pcall(function() return dfhack.getTickCount() end)
    if okd and type(ms) == 'number' then return ms / 1000 end
    local ok, t = pcall(function() return os.clock() end)
    return ok and tonumber(t) or nil
end

-- the fort civ's diplomacy: entity id -> relation name
local function relations(R, civ)
    local rel = {}
    local civ_ent = civ and R.rd('historical_entity.find', function() return df.historical_entity.find(civ) end)
    local states = civ_ent and R.rd('entity.relations.diplomacy.state',
        function() return civ_ent.relations.diplomacy.state end)
    for _, st in ipairs(each(states)) do
        local gid = R.rd('diplomacy_state.group_id', function() return st.group_id end)
        local r = R.rd('diplomacy_state.relation', function() return st.relation end)
        if gid then rel[gid] = enum_name(df.diplomacy_state_type, r) end
    end
    return rel
end

-- (0.105.39 review) Is a site's owner hostile to the fort's civ (at war or
-- skirmishing, as hostile() says)? For the bridge's send_mission, which
-- refuses raids and the like against anyone else. Returns
-- {hostile, at_war, relation, owner, ours} or nil and why.
function site_hostile(site_id)
    local R = new_reader()
    local civ, group = fort_ids(R)
    local s = R.rd('world_site.find', function() return df.world_site.find(site_id) end)
    if not s then return nil, 'no site ' .. tostring(site_id) end
    local c = R.rd('world_site.civ_id', function() return s.civ_id end)
    local okc, cur = pcall(function() return s.cur_owner_id end)
    if not okc then cur = nil end
    local who = (cur and cur >= 0 and cur) or (c and c >= 0 and c) or nil
    local ours = who ~= nil and (who == civ or who == group or c == civ)
    local rel = relations(R, civ)
    local r = (c and rel[c]) or (cur and rel[cur]) or nil
    return {hostile = hostile(r) and not ours, at_war = type(r) == 'string' and r:find('War') ~= nil and not ours,
            relation = r or 'unknown', owner = who and int(who) or nil, ours = ours or nil,
            civ = (c and c >= 0) and int(c) or nil}      -- (0.105.41, item 8) the owner's civilisation
end

local function link_type(R, enum, label, l)
    local t = R.rd(label, function() return l:getType() end)
    return enum_name(enum, t)
end

function targets(R, civ, group, fort_site, sc)
    R = R or new_reader()
    local t0 = clock()
    local partial = false
    local function over()
        if partial then return true end
        local t = t0 and clock()
        if t and t - t0 > TARGET_BUDGET then partial = true end
        return partial
    end
    local found = {}
    for _, g in ipairs(GOAL_ORDER) do found[g] = {} end

    -- the world's sites by id, and the fort's position
    local by_id, list = {}, {}
    local all = R.rd('world.world_data.sites', function() return df.global.world.world_data.sites end)
    walk(all, function(s)
        local ok, id = pcall(function() return s.id end)
        if ok and id then by_id[id] = s; table.insert(list, s) end
    end)
    local function site_of(id)
        if not id or id < 0 then return nil end
        return by_id[id] or R.rd('world_site.find', function() return df.world_site.find(id) end)
    end
    local fs = site_of(fort_site)
    local fx = fs and R.rd('world_site.pos', function() return fs.pos.x end)
    local fy = fs and R.rd('world_site.pos', function() return fs.pos.y end)
    local function dist_to(s)
        if not (s and fx and fy) then return nil end
        local ok, x, y = pcall(function() return s.pos.x, s.pos.y end)
        if not ok then R.note('world_site.pos'); return nil end
        return int(math.max(math.abs(x - fx), math.abs(y - fy)))
    end
    local rel = relations(R, civ)
    local ent_names = {}
    local function ent_name(id)
        if not id or id < 0 then return nil end
        if ent_names[id] == nil then
            local e = R.rd('historical_entity.find', function() return df.historical_entity.find(id) end)
            ent_names[id] = (e and short(R.rd('entity.name', function() return name_of(e.name) end), TARGET_NAME)) or false
        end
        return ent_names[id] or nil
    end
    local function owner_of(s)
        local c = R.rd('world_site.civ_id', function() return s.civ_id end)
        local okc, cur = pcall(function() return s.cur_owner_id end)   -- newer saves only
        if not okc then cur = nil end
        local r = (c and rel[c]) or (cur and rel[cur])
        return (c and c >= 0 and c) or (cur and cur >= 0 and cur) or nil, cur, r
    end
    -- one target at a site; nil when the site is ours or unknown
    local function add(goal, site_id, fields, rank)
        if not site_id or site_id < 0 or site_id == fort_site then return false end
        local s = site_of(site_id)
        if not s then return false end
        local who, _, r = owner_of(s)
        local e = {goal = goal, site_id = int(site_id),
                   site = short(R.rd('world_site.name', function() return name_of(s.name) end), TARGET_NAME),
                   dist = dist_to(s), civ_id = who and int(who) or nil, civ = ent_name(who),
                   hostile = hostile(r), at_war = type(r) == 'string' and r:find('War') ~= nil,
                   _rank = rank or 0}
        for k, v in pairs(fields) do e[k] = v end
        table.insert(found[goal], e)
        return true
    end

    -- rescue -----------------------------------------------------------------
    local ours = {}        -- hf ids of the fort's group
    local ent = group and R.rd('historical_entity.find', function() return df.historical_entity.find(group) end)
    local members = ent and R.rd('entity.histfig_ids', function() return ent.histfig_ids end)
    local n_members = 0
    walk(members, function(id) ours[id] = true; n_members = n_members + 1 end)
    if ent and members == nil then n_members = nil end
    local seen_hf = {}
    local function hf_home(hf)
        local uid = R.rd('historical_figure.unit_id', function() return hf.unit_id end)
        if not uid or uid < 0 then return false end
        local u = R.rd('unit.find', function() return df.unit.find(uid) end)
        if not u then return false end
        local inactive = R.rd('unit.flags1.inactive', function() return u.flags1.inactive end)
        return inactive == false
    end
    -- where a figure is held, and why we think so; nil when not held
    local function held(hf, abducted)
        local okd, died = pcall(function() return hf.died_year end)
        if okd and died and died ~= -1 then return nil end
        local where, why
        walk(R.rd('historical_figure.site_links', function() return hf.site_links end), function(l)
            local t = link_type(R, df.histfig_site_link_type, 'histfig_site_link.getType', l)
            if t == 'PRISON_ABSTRACT_BUILDING' or t == 'PRISON_SITE_BUILDING_PROFILE' then
                where = R.rd('histfig_site_link.site', function() return l.site end)
                why = 'held in a prison'
                return true
            end
        end)
        if not why then
            walk(R.rd('historical_figure.entity_links', function() return hf.entity_links end), function(l)
                local t = link_type(R, df.histfig_entity_link_type, 'histfig_entity_link.getType', l)
                local eid = R.rd('histfig_entity_link.entity_id', function() return l.entity_id end)
                if (t == 'PRISONER' or t == 'SLAVE') and eid ~= civ and eid ~= group then
                    why = (t == 'SLAVE') and 'enslaved' or 'a prisoner'
                    return true
                end
            end)
        end
        if not why and abducted then why = 'abducted' end
        if not why then return nil end
        local wh = R.rd('hf.info.whereabouts', function() return hf.info.whereabouts end)
        local wsite = wh and R.rd('hf.info.whereabouts.site_id', function() return wh.site_id end)
        if wsite == fort_site and hf_home(hf) then return nil end
        if not where or where < 0 then where = wsite end
        if not where or where < 0 or where == fort_site then return nil end
        return where, why
    end
    local function try_hf(id, abducted, where_hint)
        if seen_hf[id] == 'found' or (seen_hf[id] and not where_hint) then return end
        seen_hf[id] = 'tried'
        local hf = R.rd('historical_figure.find', function() return df.historical_figure.find(id) end)
        if not hf then return end
        local where, why = held(hf, abducted)
        if not where and where_hint then where, why = where_hint, 'held where the World screen shows' end
        if where then
            seen_hf[id] = 'found'
            add('rescue', where, {hf_id = int(id), why = why,
                hf = short(R.rd('historical_figure.name', function() return name_of(hf.name) end), TARGET_NAME)})
        end
    end
    walk(members, function(id) try_hf(id, false); return over() end)
    -- abductions, newest first: of a figure of ours or at the fort
    if not over() then
        local evs = R.rd('world.history.events', function() return df.global.world.history.events end)
        walk(evs, function(ev)
            if over() then return true end
            local t = link_type(R, df.history_event_type, 'history_event.getType', ev)
            if t == 'HIST_FIGURE_ABDUCTED' then
                local tgt = R.rd('history_event_hist_figure_abductedst.target', function() return ev.target end)
                local at = R.rd('history_event_hist_figure_abductedst.site', function() return ev.site end)
                if tgt and tgt >= 0 and (ours[tgt] or at == fort_site) then try_hf(tgt, true) end
            end
        end, true, MAX_EVENTS)
    end
    -- the open World screen's prisoners at its focus site
    local scr = sc and sc.focus_site and world_screen()
    if scr and not over() then
        walk(R.rd('viewscreen_worldst.focus_site_prisoner', function() return scr.focus_site_prisoner end), function(hf)
            local okid, id = pcall(function() return hf.id end)
            if okid and id and ours[id] then try_hf(id, false, sc.focus_site) end
        end)
    end

    -- recover_artifact -------------------------------------------------------
    if not over() then
        local arts = R.rd('world.artifacts.all', function() return df.global.world.artifacts.all end)
        walk(arts, function(a)
            if over() then return true end
            local claims = R.rd('artifact_record.entity_claims', function() return a.entity_claims end)
            local tier
            walk(claims, function(eid)
                if group and eid == group then tier = 0; return true end
                if civ and eid == civ then tier = 1 end
            end)
            if not tier then return end
            local where = R.rd('artifact_record.storage_site', function() return a.storage_site end)
            if not where or where < 0 then where = R.rd('artifact_record.site', function() return a.site end) end
            if not where or where < 0 then
                local h = R.rd('artifact_record.holder_hf', function() return a.holder_hf end)
                local hf = h and h >= 0 and R.rd('historical_figure.find', function() return df.historical_figure.find(h) end)
                where = hf and R.rd('hf.info.whereabouts.site_id', function() return hf.info.whereabouts.site_id end)
            end
            if not where or where < 0 or where == fort_site then return end
            -- (0.105.39 review) kept at a site of the fort's own civ or group: not stolen from us
            local ws = site_of(where)
            if ws then
                local who, cur = owner_of(ws)
                if who == civ or who == group or (cur and (cur == civ or cur == group)) then return end
            end
            add('recover_artifact', where, {
                artifact_id = int(R.rd('artifact_record.id', function() return a.id end)),
                artifact = short(R.rd('artifact_record.name', function() return name_of(a.name) end), TARGET_NAME),
                why = tier == 0 and 'claimed by the fort' or "claimed by the fort's civ"}, tier)
        end)
    end

    -- explore and the offensive goals: one walk over the sites ---------------
    for _, s in ipairs(list) do
        if over() then break end
        local okw = pcall(function()
            local id = s.id
            if id == fort_site then return end
            local okh, hidden = pcall(function() return s.flag.HIDDEN end)
            if okh and hidden then return end
            local okf, ruined = pcall(function() return s.flag.RUINED end)
            local who, cur, r = owner_of(s)
            local okp, pop = pcall(function() return s.resident_count end)
            -- (0.105.39 review) explore: a RUINED site only (not a lair, a cave or
            -- an empty unowned site: nothing there a mission can explore)
            if okf and ruined then
                local tn = enum_name(df.world_site_type, R.rd('world_site.type', function() return s.type end))
                -- (review 2) a type that can't be read: not explored (a cave or a lair can't be told apart)
                if tn and not tonumber(tn) and not EXPLORE_NOT[tn] then add('explore', id, {why = 'a ruin'}) end
                return
            end
            if not who or who == civ or who == group or cur == civ or cur == group then return end
            if not hostile(r) then return end
            add('raid', id, {why = 'hostile: ' .. r})
            add('pillage', id, {why = 'hostile: ' .. r})
            local d = dist_to(s)
            local weaker = okp and type(pop) == 'number' and pop >= 0 and n_members and pop < n_members
            if weaker and d and d <= TRIBUTE_DIST then
                add('tribute', id, {why = 'hostile, smaller (' .. int(pop) .. ' living there), near'})
            end
            if weaker and d and d <= CONQUER_DIST and r:find('War') then
                add('conquer', id, {why = 'at war, smaller (' .. int(pop) .. ' living there), near'})
            end
        end)
        if not okw then R.note('world_site fields') end
    end

    -- best first: goal order, then the rank inside a goal, then nearest
    local out = {}
    for _, g in ipairs(GOAL_ORDER) do
        local l = found[g]
        table.sort(l, function(a, b)
            if a._rank ~= b._rank then return a._rank < b._rank end
            local da, db = a.dist or math.huge, b.dist or math.huge
            if da ~= db then return da < db end
            return (a.hf_id or a.artifact_id or a.site_id) < (b.hf_id or b.artifact_id or b.site_id)
        end)
        for i = 1, math.min(GOAL_CAP[g] or 1, #l) do
            if #out >= MAX_TARGETS then break end
            local e = l[i]
            e._rank = nil
            if sc and sc.focus_site and sc.focus_site == e.site_id and sc.allowed then
                e.ready = sc.allowed[DF_GOAL[g]]
            end
            table.insert(out, e)
        end
    end
    return out, partial
end

-- ---------------------------------------------------------------------------
-- (0.105.39 review) where the citizen and the artifact the last missions went
-- for are now, so the brain counts a rescue or a recovery only when it is
-- true: status_of = {hf = {["<id>"] = 'home'|'dead'|'held'|'unknown'},
-- artifact = {["<id>"] = 'fort'|'away'|'unknown'}} (string keys: JSON)

MAX_STATUS = 8

local function hf_state(R, id, civ, group, fort_site)
    local hf = R.rd('historical_figure.find', function() return df.historical_figure.find(id) end)
    if not hf then return 'unknown' end
    local okd, died = pcall(function() return hf.died_year end)
    if okd and died and died ~= -1 then return 'dead' end
    local uid = R.rd('historical_figure.unit_id', function() return hf.unit_id end)
    local u = uid and uid >= 0 and R.rd('unit.find', function() return df.unit.find(uid) end) or nil
    if u then
        local okk, killed = pcall(function() return u.flags2.killed end)
        if okk and killed then return 'dead' end
        local inactive = R.rd('unit.flags1.inactive', function() return u.flags1.inactive end)
        if inactive == false then return 'home' end
    end
    local held = false
    walk(R.rd('historical_figure.entity_links', function() return hf.entity_links end), function(l)
        local t = link_type(R, df.histfig_entity_link_type, 'histfig_entity_link.getType', l)
        local eid = R.rd('histfig_entity_link.entity_id', function() return l.entity_id end)
        if (t == 'PRISONER' or t == 'SLAVE') and eid ~= civ and eid ~= group then held = true; return true end
    end)
    if not held then
        walk(R.rd('historical_figure.site_links', function() return hf.site_links end), function(l)
            local t = link_type(R, df.histfig_site_link_type, 'histfig_site_link.getType', l)
            if t == 'PRISON_ABSTRACT_BUILDING' or t == 'PRISON_SITE_BUILDING_PROFILE' then held = true; return true end
        end)
    end
    return held and 'held' or 'unknown'
end

local function artifact_state(R, id, fort_site)
    local a = R.rd('artifact_record.find', function() return df.artifact_record.find(id) end)
    if not a then
        walk(R.rd('world.artifacts.all', function() return df.global.world.artifacts.all end), function(x)
            local ok, xid = pcall(function() return x.id end)
            if ok and xid == id then a = x; return true end
        end)
    end
    if not a then return 'unknown' end
    -- on the fort's map: the item has a place here
    local okp, onmap = pcall(function()
        local x = dfhack.items.getPosition(a.item)
        return x ~= nil and x >= 0
    end)
    if okp and onmap then return 'fort' end
    local site = R.rd('artifact_record.site', function() return a.site end)
    if site and site == fort_site then return 'fort' end
    if site and site >= 0 then return 'away' end
    return 'unknown'
end

-- ids: {hf = {id, ...}, artifact = {id, ...}}
function status_of(R, civ, group, fort_site, ids)
    R = R or new_reader()
    local out = {hf = {}, artifact = {}}
    local n = 0
    for _, id in ipairs(ids and ids.hf or {}) do
        if n >= MAX_STATUS then break end
        out.hf[tostring(id)] = hf_state(R, id, civ, group, fort_site)
        n = n + 1
    end
    for _, id in ipairs(ids and ids.artifact or {}) do
        if n >= MAX_STATUS then break end
        out.artifact[tostring(id)] = artifact_state(R, id, fort_site)
        n = n + 1
    end
    return out
end

-- the citizen and artifact ids of the sender's last run of each goal
-- (lua/ai-mission-send.lua last_by_goal)
local function sent_ids()
    local ids = {hf = {}, artifact = {}}
    local ok, by = pcall(function() return reqscript('ai-mission-send').last_by_goal() end)
    if not ok or type(by) ~= 'table' then return ids end
    for _, o in pairs(by) do
        if type(o) == 'table' then
            local h, a = int(o.hf_id), int(o.artifact_id)
            if type(h) == 'number' and h >= 0 then table.insert(ids.hf, h) end
            if type(a) == 'number' and a >= 0 then table.insert(ids.artifact, a) end
        end
    end
    table.sort(ids.hf)
    table.sort(ids.artifact)
    return ids
end

local function squad_ctl_set(squads)
    local set = {}
    for _, s in ipairs(squads) do if s.controller then set[s.controller] = true end end
    return set
end

function report()
    local R = new_reader()
    local civ, group, fort_site = fort_ids(R)
    local squads = fort_squads(R, group)
    local ctl = controllers(R, civ, group, squad_ctl_set(squads))
    local ids = {}
    for _, c in ipairs(ctl) do ids[c.id] = true end
    local counts = army_members(R, ids)
    -- a controller's squads: its own list, and squads that point at it
    for _, c in ipairs(ctl) do
        local have = {}
        for _, s in ipairs(c.squads) do have[s] = true end
        for _, s in ipairs(squads) do
            if s.controller == c.id and not have[s.id] then
                have[s.id] = true
                table.insert(c.squads, s.id)
            end
        end
        for _, s in ipairs(squads) do
            if have[s.id] then c.away = c.away + s.away end
        end
        c.army_members = counts[c.id]
    end
    -- the site names of the missions' targets
    for _, c in ipairs(ctl) do
        if c.site_id then
            local s = R.rd('world_site.find', function() return df.world_site.find(c.site_id) end)
            c.site = s and R.rd('world_site.name', function() return name_of(s.name) end) or nil
        end
    end
    -- (0.105.39 review) the fort's own first (holding its squads, or of its
    -- group), then the civ's, before the cap: a busy civ's armies never push
    -- the fort's own mission out of the report
    local fort_sq = {}
    for _, s in ipairs(squads) do fort_sq[s.id] = true end
    local order = {}
    for i, c in ipairs(ctl) do
        local own = (group ~= nil and c.entity_id == group)
        for _, sid in ipairs(c.squads) do if fort_sq[sid] then own = true end end
        order[c] = {own and 0 or 1, i}
    end
    table.sort(ctl, function(a, b)
        local oa, ob = order[a], order[b]
        if oa[1] ~= ob[1] then return oa[1] < ob[1] end
        return oa[2] < ob[2]
    end)
    local out_ctl = {}
    for i = 1, math.min(MAX_CONTROLLERS, #ctl) do table.insert(out_ctl, ctl[i]) end
    local out_sq = {}
    for i = 1, math.min(MAX_SQUADS, #squads) do
        local s = squads[i]
        table.insert(out_sq, {id = s.id, name = s.name, members = s.members, away = s.away, controller = s.controller})
    end
    local okst, st = pcall(sites, R, civ, group, fort_site)
    if not okst then R.note('sites'); st = nil end
    local oksc, sc = pcall(screen, R)
    if not oksc then R.note('world screen'); sc = nil end
    -- (0.105.39) where a mission could go, best first
    local okt, tl, partial = pcall(targets, R, civ, group, fort_site, sc)
    if not okt then R.note('targets'); tl, partial = {}, nil end
    local oks2, so = pcall(status_of, R, civ, group, fort_site, sent_ids())
    if not oks2 then R.note('status_of'); so = nil end
    return {
        targets = tl,
        targets_partial = partial or nil,
        status_of = so,
        controllers = out_ctl,
        squads = out_sq,
        reports = reports(R),
        spoils = spoils(R),
        sites = st,
        screen = sc,
        unknown = R.list,
    }
end

-- Citizens away on a mission: {unit_id = true}. Squad members away (see
-- member_away) and the units of the fort's armies' members.
function away_units()
    local R = new_reader()
    local civ, group = fort_ids(R)
    local squads = fort_squads(R, group)
    local set = {}
    for _, s in ipairs(squads) do
        for _, uid in ipairs(s.away_units) do set[uid] = true end
    end
    local ids = {}
    for _, c in ipairs(controllers(R, civ, group, squad_ctl_set(squads))) do ids[c.id] = true end
    local _, units = army_members(R, ids)
    for uid in pairs(units) do set[uid] = true end
    return set
end


-- (0.104.97, 13b) A probe, read only: everything the World screen holds right
-- now, one level deep (numbers, strings, booleans and enum names as they
-- are; vectors as their size and first few values), with the focus string,
-- the mouse and the fort's mission counts. brain/probe_missions.py samples it
-- every second while the player sends one mission by hand, so the AI can
-- learn the screen's steps (as probe_trade did for the Trade button).
local function plain(v)
    local t = type(v)
    if t == 'number' or t == 'string' or t == 'boolean' then return v end
    if t == 'userdata' then
        local okn, n = pcall(function() return #v end)
        if okn and type(n) == 'number' then
            local first = {}
            for i = 0, math.min(n, 4) - 1 do
                local oke, e = pcall(function() return v[i] end)
                local te = oke and type(e)
                if te == 'number' or te == 'string' or te == 'boolean' then table.insert(first, e) end
            end
            return {n = n, first = (#first > 0) and first or nil}
        end
        local oks, str = pcall(tostring, v)
        return oks and short(str, 60) or '?'
    end
    return nil
end

function probe_screen()
    local out = {}
    pcall(function() out.focus = dfhack.gui.getCurFocus(true) end)
    pcall(function() out.mouse = {x = df.global.gps.mouse_x, y = df.global.gps.mouse_y} end)
    pcall(function() out.controllers = #df.global.world.army_controllers.all end)
    pcall(function() out.reports = #df.global.world.status.mission_reports end)
    -- (0.104.99) the newest army controllers in the world, with their owners,
    -- and the fort's own ids: which entity a mission sent from here belongs to
    pcall(function()
        out.fort = {civ = df.global.plotinfo.civ_id, group = df.global.plotinfo.group_id,
                    site = df.global.plotinfo.site_id}
        local all, newest = df.global.world.army_controllers.all, {}
        for i = #all - 1, math.max(0, #all - 4), -1 do
            local c = all[i]
            local e = {id = c.id}
            pcall(function() e.entity = c.entity_id end)
            pcall(function() e.site = c.site_id end)
            pcall(function() e.goal = df.army_controller_goal_type[c.goal] end)
            pcall(function() e.master = c.master_id end)
            pcall(function() e.commander = c.commander_hf end)
            pcall(function() e.squads = #c.assigned_squads end)
            pcall(function() e.origin = c.origin_site_id end)
            table.insert(newest, e)
        end
        out.newest_controllers = newest
    end)
    local scr = world_screen()
    if not scr then
        out.screen = false
        return out
    end
    local fields, n = {}, 0
    local ok = pcall(function()
        for k, v in pairs(scr) do
            if n >= 120 then break end
            local okv, pv = pcall(plain, v)
            if okv and pv ~= nil then fields[tostring(k)] = pv; n = n + 1 end
        end
    end)
    out.screen = true
    out.fields = fields
    out.fields_ok = ok
    pcall(function() out.view_mode = df.world_view_mode_type[scr.view_mode] end)
    pcall(function()
        local allowed = {}
        for i = 0, #scr.new_mission - 1 do
            allowed[df.army_controller_goal_type[i] or tostring(i)] = df.world_new_mission_type[scr.new_mission[i]]
                or scr.new_mission[i]
        end
        out.allowed = allowed
    end)
    return out
end

