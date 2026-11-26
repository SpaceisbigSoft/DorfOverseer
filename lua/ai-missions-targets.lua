-- ai-missions-targets: the World screen (only when already open), the landmasses, how the
-- fort's civ stands with a site's owner, and targets(): where a mission could go.
--
-- (r9) A part of ai-missions, not a script of its own: ai-missions.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-missions').name and the readers defined there (new_reader,
-- short, int, ...) are in reach.

if not MISSIONS_PART_LOCALS then qerror('ai-missions-targets is a part of ai-missions; run ai-missions') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-missions-targets'] = '0.105.132'   -- (0.105.26) bumped with BRIDGE_VERSION

-- (r9) the hub's and earlier parts' locals used here
local new_reader, short, enum_name, name_of, each, int, fort_ids, hostile = MISSIONS_PART_LOCALS.new_reader, MISSIONS_PART_LOCALS.short, MISSIONS_PART_LOCALS.enum_name, MISSIONS_PART_LOCALS.name_of, MISSIONS_PART_LOCALS.each, MISSIONS_PART_LOCALS.int, MISSIONS_PART_LOCALS.fort_ids, MISSIONS_PART_LOCALS.hostile

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

ALLOWED_MODES = {NEW_MISSION = true, MISSION_DETAILS = true}

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
    -- (0.105.47) new_mission holds DF's verdicts only once a site's New
    -- mission was opened (recorded 14 Nov: garbage numbers on world/NORMAL,
    -- the right words on NEW_MISSION and MISSION_DETAILS): read only there
    if not ALLOWED_MODES[out.view_mode or ''] then nm = nil end
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
-- each part of the walk (rescue, artifacts, sites: (r9) a budget each) stops
-- after TARGET_BUDGET seconds (dfhack.getTickCount, os.clock without it) and
-- says partial.

-- (0.105.47) Can the fort's people get there at all? Recorded 14 Nov: a
-- goblin site on an island read INACCESSIBLE for Attack, Request workers
-- and Diplomacy on New mission. A site on another landmass than the fort
-- (world_data.region_map[x][y].landmass_id, the world tiles of site.pos)
-- is taken for the same and never named as a target; a landmass that
-- can't be read says nothing (the World screen's own verdict stops a run
-- there, and the planner remembers the site).
function landmass_at(x, y)
    if type(x) ~= 'number' or type(y) ~= 'number' then return nil end
    local ok, id = pcall(function()
        local col = df.global.world.world_data.region_map[x]
        local okd, e = pcall(function() return col:_displace(y) end)
        if not okd or e == nil then e = col[y] end
        return e.landmass_id
    end)
    if ok and type(id) == 'number' and id >= 0 then return math.tointeger(id) or id end
    return nil
end

function site_landmass(s)
    local ok, x, y = pcall(function() return s.pos.x, s.pos.y end)
    if not ok then return nil end
    return landmass_at(x, y)
end

-- Pure: true when both landmasses are known and differ
function other_landmass(a, b)
    return a ~= nil and b ~= nil and a ~= b
end

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
    -- (r9, A8 #19) the holder and its civilisation, not the maker (site_owner)
    local who, c = site_owner(s)
    local ours = who ~= nil and (who == civ or who == group or c == civ)
    local r = resolver(R, civ, group)(c, who)      -- (r2 h9) both ways
    return {hostile = hostile(r) and not ours, at_war = type(r) == 'string' and r:find('War') ~= nil and not ours,
            relation = r or 'unknown', owner = who and int(who) or nil, ours = ours or nil,
            civ = c and int(c) or nil}      -- (0.105.41, item 8) the owner's civilisation
end

local function link_type(R, enum, label, l)
    local t = R.rd(label, function() return l:getType() end)
    return enum_name(enum, t)
end

function targets(R, civ, group, fort_site, sc)
    R = R or new_reader()
    DROPPED_INACCESSIBLE = 0      -- (0.105.47) targets on another landmass, this walk
    -- (r9, audit A8 #8) a budget per part (the rescue walk, the artifacts, the
    -- sites), not one for all: in a big fort (War-hold) the rescue walk over
    -- every figure of the group spent the whole 0.05 s and the artifacts and
    -- sites were never looked at ("targets": [], partial). `partial` says any
    -- part ran out; each part starts its own clock with phase().
    local t0 = clock()
    local partial, phase_over = false, false
    local function over()
        if phase_over then return true end
        local t = t0 and clock()
        if t and t - t0 > TARGET_BUDGET then partial, phase_over = true, true end
        return phase_over
    end
    local function phase()
        t0, phase_over = clock(), false
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
    local rel_of = resolver(R, civ, group)           -- (r2 h9) both ways
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
        -- (r9, A8 #19) the holder's civilisation (or the holder), not the maker
        local who, c = site_owner(s)
        local r = rel_of(c, who)
        return c or who, who, r
    end
    -- one target at a site; nil when the site is ours or unknown
    local fort_land = fs and site_landmass(fs)
    local function add(goal, site_id, fields, rank)
        if not site_id or site_id < 0 or site_id == fort_site then return false end
        local s = site_of(site_id)
        if not s then return false end
        -- (0.105.47) another landmass: DF's "Inaccessible" (an island)
        if other_landmass(fort_land, site_landmass(s)) then
            DROPPED_INACCESSIBLE = (DROPPED_INACCESSIBLE or 0) + 1
            return false
        end
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
    phase()
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
    phase()
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
            -- (0.105.48, K9) the site's type goes with each offensive target: the
            -- brain attacks only sites people live in (planner_raids LIVED_IN),
            -- never a monument, a lair or a cave
            local st = enum_name(df.world_site_type, R.rd('world_site.type', function() return s.type end))
            add('raid', id, {why = 'hostile: ' .. r, type = st})
            add('pillage', id, {why = 'hostile: ' .. r, type = st})
            local d = dist_to(s)
            -- (0.105.48) 0 living there is not known to be "smaller" (resident_count may be 0 for a site never loaded)
            local weaker = okp and type(pop) == 'number' and pop > 0 and n_members and pop < n_members
            if weaker and d and d <= TRIBUTE_DIST then
                add('tribute', id, {why = 'hostile, smaller (' .. int(pop) .. ' living there), near', type = st})
            end
            if weaker and d and d <= CONQUER_DIST and r:find('War') then
                add('conquer', id, {why = 'at war, smaller (' .. int(pop) .. ' living there), near', type = st})
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

-- (r9) this file's locals handed on to ai-missions-report
MISSIONS_PART_LOCALS.world_screen, MISSIONS_PART_LOCALS.screen, MISSIONS_PART_LOCALS.walk, MISSIONS_PART_LOCALS.link_type = world_screen, screen, walk, link_type
