-- ai-missions-report: status_of (where the last missions' citizen and artifact are now),
-- report() for the daily JSON report, away_units() and probe_screen().
--
-- (r9) A part of ai-missions, not a script of its own: ai-missions.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-missions').name and the readers defined there (new_reader,
-- short, int, ...) are in reach.

if not MISSIONS_PART_LOCALS then qerror('ai-missions-report is a part of ai-missions; run ai-missions') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-missions-report'] = '0.105.113'   -- (0.105.26) bumped with BRIDGE_VERSION

-- (r9) the hub's and earlier parts' locals used here
local new_reader, short, name_of, int, fort_ids, fort_squads, controllers, army_members, waiting_people, reports, spoils, sites, world_screen, screen, walk, link_type = MISSIONS_PART_LOCALS.new_reader, MISSIONS_PART_LOCALS.short, MISSIONS_PART_LOCALS.name_of, MISSIONS_PART_LOCALS.int, MISSIONS_PART_LOCALS.fort_ids, MISSIONS_PART_LOCALS.fort_squads, MISSIONS_PART_LOCALS.controllers, MISSIONS_PART_LOCALS.army_members, MISSIONS_PART_LOCALS.waiting_people, MISSIONS_PART_LOCALS.reports, MISSIONS_PART_LOCALS.spoils, MISSIONS_PART_LOCALS.sites, MISSIONS_PART_LOCALS.world_screen, MISSIONS_PART_LOCALS.screen, MISSIONS_PART_LOCALS.walk, MISSIONS_PART_LOCALS.link_type

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
    local counts, _, armies = army_members(R, ids)
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
        -- (0.105.47) set out: an army in world.armies.all points at it
        -- (nil when the armies can't be read); not yet: who it waits on
        if armies then c.departed = armies[c.id] == true end
        if c.departed == false then
            local okw, w = pcall(waiting_people, R, c, group)
            if okw and #w > 0 then
                c.waiting = w
                -- (0.105.47) every traveller off the map (and no army read yet): gone, set out
                local all_off = true
                for _, x in ipairs(w) do if x.on_map ~= false then all_off = false end end
                if all_off then c.departed, c.departed_by = true, 'off the map' end
                -- (0.105.47, live 17:09) can they walk off the map at all?
                local ids = {}
                for _, x in ipairs(w) do table.insert(ids, x.unit_id) end
                local okb, wr = pcall(function() return reqscript('ai-mission-way').way(ids) end)   -- (no reqscript: the tests)
                if okb and type(wr) == 'table' and wr.known then c.way_blocked = #wr.blocked end
            end
        end
        c.epp = c.epp and #c.epp or nil
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
        table.insert(out_sq, {id = s.id, name = s.name, members = s.members, away = s.away, controller = s.controller,
                              gone = s.gone})   -- (0.105.48, K9) members gone from the map, not on a mission
    end
    local okst, st = pcall(sites, R, civ, group, fort_site)
    if not okst then R.note('sites'); st = nil end
    local oksc, sc = pcall(screen, R)
    if not oksc then R.note('world screen'); sc = nil end
    -- (0.105.39) where a mission could go, best first
    local okt, tl, partial = pcall(targets, R, civ, group, fort_site, sc)
    if not okt then R.note('targets'); tl, partial = {}, nil end
    -- (0.105.47) the travellers' way off the map (lua/ai-mission-way.lua)
    local okw, way_out = false, nil
    if type(reqscript) == 'function' then
        okw, way_out = pcall(function()
            local mid = reqscript('ai-mission-send').messenger_home()
            return reqscript('ai-mission-way').report(squads, mid)
        end)
        if not okw then R.note('way_out'); way_out = nil end
    end
    -- (0.105.47, J17) the raid policy's sites (any owner, not only the
    -- hostile) and the soldiers' pets held at home (lua/ai-raids.lua)
    local raid_sites, pets
    if type(reqscript) == 'function' then
        local okr, rs = pcall(function() return reqscript('ai-raids').raid_sites() end)
        if okr and type(rs) == 'table' then raid_sites = rs else R.note('raid_sites') end
        local okq, pr = pcall(function() return reqscript('ai-raids').pets_report(squads) end)
        if okq and type(pr) == 'table' then pets = pr else R.note('pets') end
    end
    local oks2, so = pcall(status_of, R, civ, group, fort_site, sent_ids())
    if not oks2 then R.note('status_of'); so = nil end
    -- (r10 p2) the messenger's post: where it is, who holds it, why nobody does (lua/ai-nobles.lua)
    local messenger
    if type(reqscript) == 'function' then
        local okm, m = pcall(function() return reqscript('ai-nobles').messenger_status(function(x) return short(x) end) end)
        if okm and type(m) == 'table' then messenger = m else R.note('messenger') end
    end
    return {
        messenger = messenger,                                                                    -- (r10 p2)
        targets = tl,
        targets_partial = partial or nil,
        targets_inaccessible = (DROPPED_INACCESSIBLE or 0) > 0 and DROPPED_INACCESSIBLE or nil,   -- (0.105.47)
        way_out = way_out,                                                                        -- (0.105.47)
        raid_sites = raid_sites,                                                                  -- (0.105.47, J17)
        pets = pets,                                                                              -- (0.105.47, J17)
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

