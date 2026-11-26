-- ai-siege-invite: the Rules' "Invite a siege (test)" (R29 W2; 0.105.123:
-- the civ by reach, the army watched for, the next civ tried, a re-invite).
--
-- (0.105.123) A part of ai-siege (split off when it neared the size limit),
-- not a script of its own: ai-siege.lua loads it into its own environment,
-- so every name here is reqscript('ai-siege').name (invite_siege for the
-- bridge, invited for field_watch).
--
-- DF 53 has no CivAttack timed event: its siege is EvaluateAttackAndSendImmediateArmy
-- (a probe of A, 25 Nov 21:36). DFHack's force takes any df.timed_event_type by name
-- but sets the event's entity only for Caravan and Diplomat, so the army event it
-- queues has none: the AI sets it to the civ it picked (and reads it back, before DF
-- takes the event, to say whether it held). Without force, the same event is queued
-- here.
--
-- What 0.105.122 showed live (A, 25 Nov 22:06): DF took the event for civ 314 (the
-- most sites) and sent nobody. Both civs at war with A have their nearest site and
-- army ~51-53 world tiles off (a 129x129 world); none of their 1583 armies' controllers
-- had A's site. So the civ is chosen by reach (its nearest site or army to the fort's
-- site, TotalWar before Skirmishing before any other hostile), the invitation waits
-- WAIT_DAYS for an army whose controller targets the fort's site (or invaders on the
-- map), and with none the next civ of the ranking is tried, CIVS_MAX at most; then
-- DF sent no army ("tried X, Y, Z") and (the player's fallback, 25 Nov) the AI places
-- the top-ranked civ's war party (SPAWN_COUNT of its race, armed, invaders of that
-- civ) at the map-edge surface tile the fort's entrance can be walked to from, the
-- farthest from it, by ai-spawn (DFHack's modtools/create-unit, else DF 53's own
-- dfhack.units.create), once a fort (SPAWN_KEY): the invitation then counts as one that
-- brought an army. With neither or no tile, it ends 'no_army' and says why.
--
-- The record (site data, INVITE_KEY): {tick, year, invitation (1, 2...), state
-- ('waiting', 'came', 'no_army'), civ_id/civ_name/race/relation/how/event (the civ
-- tried now), tries = {{civ_id, civ_name, race, relation, reach, tick, how,
-- entity_set, entity_read, outcome ('army', 'no_army')}}, ranking = {{id, name,
-- race, relation, reach, site_d, army_d, armies, sites}}, previous (the invitation
-- before: its state and the civs tried)}. An invitation that brought an army is
-- the fort's one ('once'); one that ended with no army allows one new invitation,
-- started by the switch turned on again.

if not PART_LOCALS then qerror('ai-siege-invite is a part of ai-siege; run ai-siege') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-siege-invite'] = '0.105.133'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, is, entrances_of = PART_LOCALS.U, PART_LOCALS.is, PART_LOCALS.entrances_of   -- the hub's locals

INVITE_KEY = 'ai-overseer/siege-invite'
INVITE_EVENTS = {'EvaluateAttackAndSendImmediateArmy', 'CivAttack', 'Siege'}
INVITE_RELATIONS = {TotalWar = 2, Skirmishing = 1}   -- the tiers; any other name with War/Hostil in it: 0
INVITE_WAIT_DAYS = 7          -- a civ's army looked for this long before the next civ is tried
INVITE_CIVS_MAX = 3           -- civs tried at most in one invitation
INVITE_RANK_KEEP = 5          -- the ranking's rows kept in the record
INVITE_DAY = 1200
-- (0.105.123, the player's fallback of 25 Nov) an invitation DF sent no army for
-- ends with a war party placed at the map edge by the AI itself, once a fort
SPAWN_KEY = 'ai-overseer/siege-spawned'
SPAWN_COUNT = 16              -- goblins (the civ's race) placed
SPAWN_COUNT_NEXT = 30         -- (0.105.127) a later war party, bigger: the gates and kill zones brought into play
SPAWN_SPREAD_MAX = 12         -- (0.105.127) the spread grows by 3 to this until the tiles hold the party (A 26 Nov: 9 of 16 at 3)
SPAWN_SPREAD = 3              -- tiles round the edge tile they are spread over
SPAWN_EQUIP = {'ITEM_WEAPON_SPEAR:INORGANIC:IRON', 'ITEM_ARMOR_MAIL_SHIRT:INORGANIC:IRON',
               'ITEM_HELM_HELM:INORGANIC:IRON', 'ITEM_SHIELD_BUCKLER:INORGANIC:IRON'}
SPAWN_FLAGS = {'active_invader', 'invader_origin'}
SPAWN_WHY = 600               -- chars of the spawner's reason kept (200 lost the diagnosis, A 26 Nov 00:35)
EDGE_STEP = 4                 -- every 4th tile of the map's edges looked at (A: 283 found in 16 ms)
ARMY_SCALE = 48               -- an army's pos over this: world tiles (site.pos)

local function try(f, ...)
    local ok, v = pcall(f, ...)
    if ok then return v end
    return nil
end

local function now_tick() return U.now_tick(0) end            -- (r6) ai-util's: 0 when it can't be read

-- the tier of a relation's name (nil: not hostile)
function relation_tier(rel)
    local w = INVITE_RELATIONS[rel]
    if w then return w end
    if type(rel) == 'string' and (rel:find('War') or rel:find('Hostil')) then return 0 end
    return nil
end

-- Pure: the hostile civs from {id, kind, relation, name, race, sites, site_d,
-- army_d, armies, alive} rows, best first: a Civilization, hostile, with
-- living members or armies and some site or army; its tier (TotalWar, then
-- Skirmishing, then any other at war), then its reach (the nearer of its
-- nearest site and army, world tiles; unknown last), then its id. A civ in
-- `tried_before` ({[id] = true}: tried by an invitation before that brought
-- no army) goes after the others.
function rank_civs(rows, tried_before)
    local out = {}
    for _, r in ipairs(rows or {}) do
        local tier = relation_tier(r.relation)
        local armies, sites = tonumber(r.armies) or 0, tonumber(r.sites) or 0
        local alive = r.alive ~= false or armies > 0
        if tier and r.kind == 'Civilization' and alive and (sites > 0 or armies > 0 or (r.site_d == nil and r.army_d == nil)) then
            local reach = r.site_d
            if r.army_d and (not reach or r.army_d < reach) then reach = r.army_d end
            local row = {}
            for k, v in pairs(r) do row[k] = v end
            row.tier, row.reach = tier, reach
            table.insert(out, row)
        end
    end
    local before = tried_before or {}
    table.sort(out, function(a, b)
        local ta, tb = before[a.id] and 1 or 0, before[b.id] and 1 or 0
        if ta ~= tb then return ta < tb end
        if a.tier ~= b.tier then return a.tier > b.tier end
        local ra, rb = a.reach or 1e9, b.reach or 1e9
        if ra ~= rb then return ra < rb end
        return a.id < b.id
    end)
    return out
end

-- (0.105.122's name) the civ ranked first
function pick_civ(rows)
    return rank_civs(rows)[1]
end

local function invite_event_type()
    for _, n in ipairs(INVITE_EVENTS) do
        local ok, v = pcall(function() return df.timed_event_type[n] end)
        if ok and v ~= nil then return n, v end
    end
    return nil
end

local function fort_site()
    return try(function() return dfhack.world.getCurrentSite() end)
end

-- an entity's civilisation (a site government's or a group's parent), memoised in `memo`
local function civ_of(eid, memo)
    if eid == nil or eid < 0 then return nil end
    if memo[eid] ~= nil then return memo[eid] end
    local r = eid
    pcall(function()
        local e = df.historical_entity.find(eid)
        if e and df.historical_entity_type[e.type] ~= 'Civilization' then
            local parent = df.entity_entity_link_type and df.entity_entity_link_type.PARENT
            for _, l in ipairs(e.entity_links) do
                if l.type == parent then r = l.target break end
            end
        end
    end)
    memo[eid] = r
    return r
end

local function has_living(ent)
    local alive = false
    pcall(function()
        for _, id in ipairs(ent.histfig_ids) do
            local hf = df.historical_figure.find(id)
            if hf and hf.died_year == -1 then alive = true return end
        end
    end)
    return alive
end

-- the fort's civ's hostile relations, each with its sites and armies' reach (live)
function reach_rows()
    local rows, by_id, memo = {}, {}, {}
    pcall(function()
        local civ = df.historical_entity.find(df.global.plotinfo.civ_id)
        for _, st in ipairs(civ.relations.diplomacy.state) do
            local rel = df.diplomacy_state_type[st.relation] or tostring(st.relation)
            local ent = relation_tier(rel) and df.historical_entity.find(st.group_id)
            if ent then
                local cr = try(function() return df.creature_raw.find(ent.race) end)
                local row = {id = ent.id, kind = df.historical_entity_type[ent.type], relation = rel,
                             race = cr and cr.creature_id or '?', sites = 0, armies = 0,
                             name = try(dfhack.translation.translateName, ent.name, true),
                             alive = has_living(ent)}
                table.insert(rows, row)
                by_id[ent.id] = row
            end
        end
    end)
    local site = fort_site()
    if not site or #rows == 0 then return rows end
    local sx, sy = site.pos.x, site.pos.y
    local function d(x, y) return math.max(math.abs(x - sx), math.abs(y - sy)) end
    pcall(function()
        for _, s in ipairs(df.global.world.world_data.sites) do
            local row = by_id[s.civ_id] or by_id[civ_of(s.cur_owner_id, memo)] or by_id[s.cur_owner_id]
            if row and s.id ~= site.id then
                row.sites = row.sites + 1
                local dd = d(s.pos.x, s.pos.y)
                if not row.site_d or dd < row.site_d then
                    row.site_d, row.site_id = dd, s.id
                    row.group_id = (s.cur_owner_id and s.cur_owner_id >= 0 and s.cur_owner_id ~= row.id) and s.cur_owner_id or nil
                end
            end
        end
    end)
    pcall(function()
        for _, a in ipairs(df.global.world.armies.all) do
            local ctl = a.controller
            local eid = ctl and ctl.entity_id or -1
            local row = by_id[civ_of(eid, memo)] or by_id[eid]   -- a group's army counts for its civ
            if row then
                row.armies = row.armies + 1
                local dd = d(math.floor(a.pos.x / ARMY_SCALE), math.floor(a.pos.y / ARMY_SCALE))
                if not row.army_d or dd < row.army_d then row.army_d = dd end
            end
        end
    end)
    return rows
end

-- the armies (and army controllers) of a hostile entity whose target is the
-- fort's site, and the invaders on the map: {armies, controllers, invaders, civs}
function army_watch()
    local out = {armies = 0, controllers = 0, invaders = 0, civs = {}}
    local site = fort_site()
    local memo = {}
    local foes = {}            -- the civs at war with the fort's (a caravan or a diplomat travels as an army too)
    pcall(function()
        local civ = df.historical_entity.find(df.global.plotinfo.civ_id)
        for _, st in ipairs(civ.relations.diplomacy.state) do
            if relation_tier(df.diplomacy_state_type[st.relation] or tostring(st.relation)) then foes[st.group_id] = true end
        end
    end)
    local function hostile(eid)
        local c = civ_of(eid, memo)
        return c ~= nil and (foes[c] or foes[eid]) == true
    end
    if site then
        pcall(function()
            for _, a in ipairs(df.global.world.armies.all) do
                local ctl = a.controller
                if ctl and ctl.site_id == site.id and hostile(ctl.entity_id) then
                    out.armies = out.armies + 1
                    out.civs[civ_of(ctl.entity_id, memo)] = true
                end
            end
        end)
        pcall(function()
            for _, ctl in ipairs(df.global.world.army_controllers.all) do
                if ctl.site_id == site.id and hostile(ctl.entity_id) then
                    out.controllers = out.controllers + 1
                    out.civs[civ_of(ctl.entity_id, memo)] = true
                end
            end
        end)
    end
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if is(dfhack.units.isInvader, u) and not is(dfhack.units.isDead, u) then out.invaders = out.invaders + 1 end
        end
    end)
    return out
end

local function queued_of(v)
    local n, last = 0, nil
    for _, ev in ipairs(df.global.timed_events) do
        if ev.type == v then n, last = n + 1, ev end
    end
    return n, last
end

local function switch_on()
    local on = false
    pcall(function() on = reqscript('ai-overseer-settings').load_settings().invite_siege == true end)
    return on
end

local function switch_off()
    pcall(function()
        local S = reqscript('ai-overseer-settings')
        local s = S.load_settings()
        if s.invite_siege then s.invite_siege = false; S.save_settings(s) end
    end)
end

-- the record, read; a 0.105.122 record (no state, no tries) as an invitation
-- waiting on its one civ
function invited()
    local ok, r = pcall(dfhack.persistent.getSiteData, INVITE_KEY, nil)
    if not (ok and type(r) == 'table' and r.tick ~= nil) then return nil end
    if r.state == nil then r.state = 'waiting' end
    if type(r.tries) ~= 'table' or #r.tries == 0 then
        r.tries = {{civ_id = r.civ_id, civ_name = r.civ_name, race = r.race, relation = r.relation,
                    tick = r.tick, how = r.how}}
    end
    r.invitation = r.invitation or 1
    return r
end

local function save(rec)
    pcall(dfhack.persistent.saveSiteData, INVITE_KEY, rec)
end

local function names_of(tries)
    local t = {}
    for _, tr in ipairs(tries or {}) do table.insert(t, tr.civ_name or (tr.civ_id and ('civ ' .. tostring(tr.civ_id))) or 'no civ named') end
    return t
end

-- the army event queued for `civ` (a ranking row, or nil: DF picks); the
-- event's entity read back before DF takes it
local function queue(name, v, civ)
    local ent = civ and df.historical_entity.find(civ.id)
    local out = {}
    local before = queued_of(v)
    local okf, script = pcall(dfhack.findScript, 'force')
    if okf and script then
        local text = dfhack.run_command_silent('force', name)
        local after, last = queued_of(v)
        if after > before and last then
            out.how = 'force'
            if ent then pcall(function() last.entity = ent end) end
            out.entity_read = try(function() return last.entity and last.entity.id end)
        else
            out.force_said = tostring(text):sub(1, 120)
        end
    end
    if not out.how then
        local ok, err = pcall(function()
            df.global.timed_events:insert('#', {new = true, type = v, season = df.global.cur_season,
                                                season_ticks = df.global.cur_season_tick, entity = ent, feature_ind = -1})
        end)
        if not ok then
            out.error = 'the army event could not be queued: ' .. tostring(err):sub(1, 120)
            return out
        end
        out.how = 'timed_event'
        local _, last = queued_of(v)
        out.entity_read = try(function() return last and last.entity and last.entity.id end)
    end
    out.entity_set = civ ~= nil and out.entity_read == civ.id or false
    out.queued = queued_of(v)
    return out
end

local function short_rank(ranking)
    local t = {}
    for i, r in ipairs(ranking) do
        if i > INVITE_RANK_KEEP then break end
        table.insert(t, {id = r.id, name = r.name, race = r.race, relation = r.relation, reach = r.reach,
                         site_d = r.site_d, army_d = r.army_d, armies = r.armies, sites = r.sites,
                         site_id = r.site_id, group_id = r.group_id})
    end
    return t
end

-- one try: civ (a ranking row or nil) queued, the try added to rec
local function try_civ(rec, name, v, civ)
    local q = queue(name, v, civ)
    if q.error then return nil, q end
    local tr = {civ_id = civ and civ.id, civ_name = civ and civ.name, race = civ and civ.race,
                relation = civ and civ.relation, reach = civ and civ.reach, tick = now_tick(),
                how = q.how, entity_set = q.entity_set, entity_read = q.entity_read}
    rec.tries = rec.tries or {}
    table.insert(rec.tries, tr)
    rec.civ_id, rec.civ_name, rec.race, rec.relation, rec.how, rec.event = tr.civ_id, tr.civ_name, tr.race, tr.relation, tr.how, name
    rec.state = 'waiting'
    return tr, q
end

local function answer(rec, extra)
    local out = {ok = true, state = rec.state, invitation = rec.invitation, tick = rec.tick, year = rec.year,
                 civ_id = rec.civ_id, civ_name = rec.civ_name, race = rec.race, relation = rec.relation,
                 how = rec.how, event = rec.event, tried = names_of(rec.tries), ranking = rec.ranking}
    for k, v in pairs(extra or {}) do out[k] = v end
    return out
end

-- --- (0.105.123) the fallback: a war party placed at the map edge ---------------

local function shape_attrs(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    return df.tiletype_shape.attrs[df.tiletype.attrs[tt].shape]
end

-- the surface floor of column x, y (the first non-open tile from the top:
-- walkable, outside, no water or magma), or nil
local function surface_z(x, y, zmax)
    for z = zmax - 1, 1, -1 do
        local ok, a = pcall(shape_attrs, x, y, z)
        if not ok or not a then return nil end
        if a.basic_shape ~= df.tiletype_shape_basic.Open then
            if a.walkable then
                local okd, des = pcall(dfhack.maps.getTileFlags, xyz2pos(x, y, z))
                if okd and des and des.outside and (des.flow_size or 0) == 0 then return z end
            end
            return nil
        end
    end
    return nil
end

-- the walkable groups of the fort's surface entrances (or, with none, of its
-- citizens), and the first entrance's spot
local function fort_groups()
    local groups, spot = {}, nil
    pcall(function()
        for _, e in ipairs(entrances_of(gates())) do
            for _, d in ipairs({{0, 0}, {1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {-1, -1}, {1, -1}, {-1, 1}}) do
                local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(e.x + d[1], e.y + d[2], e.z))
                if okg and g and g ~= 0 then
                    groups[g] = true
                    spot = spot or {x = e.x, y = e.y, z = e.z}
                    break
                end
            end
        end
    end)
    if next(groups) == nil then
        pcall(function()
            for _, u in ipairs(U.report_citizens(true)) do
                local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(u.pos.x, u.pos.y, u.pos.z))
                if okg and g and g ~= 0 then
                    groups[g] = true
                    spot = spot or {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                end
            end
        end)
    end
    return groups, spot
end

-- the map-edge surface tile the fort's entrance can be walked to from,
-- the farthest from it (the far side: time for the alarm), or nil
function edge_spot()
    local groups, spot = fort_groups()
    if next(groups) == nil or not spot then return nil end
    local w, h, zc = dfhack.maps.getTileSize()
    local best, bd
    local function look(x, y)
        local z = surface_z(x, y, zc)
        if not z then return end
        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
        if okg and g and groups[g] then
            local d = (x - spot.x) ^ 2 + (y - spot.y) ^ 2
            if not bd or d > bd then
                best, bd = {x = x, y = y, z = z, distance = math.max(math.abs(x - spot.x), math.abs(y - spot.y))}, d
            end
        end
    end
    for x = 1, w - 2, EDGE_STEP do look(x, 0); look(x, h - 1) end
    for y = 1, h - 2, EDGE_STEP do look(0, y); look(w - 1, y) end
    return best
end

function spawned()
    local ok, r = pcall(dfhack.persistent.getSiteData, SPAWN_KEY, nil)
    return (ok and type(r) == 'table' and r.tick ~= nil) and r or nil
end

-- the war party of `civ` ({id, name, race, group_id}) placed at the map edge by
-- ai-spawn's spawn_units (DFHack's modtools/create-unit, armed by its -equip;
-- without it when that fails; create-unit stale for DF 53: dfhack.units.create,
-- armed by dfhack.items, ai-spawn.lua), marked invaders of the civ. Returns the
-- record, or nil, the reason (up to SPAWN_WHY chars) and the spawner's info
-- (route, each route's error, counts: ai-spawn brief).
-- (0.105.127) a war party placed before and still alive on the map (any of its ids)
function party_alive(rec)
    rec = rec or spawned()
    if not rec or type(rec.ids) ~= 'table' then return false end
    for _, id in ipairs(rec.ids) do
        local ok, alive = pcall(function()
            local u = df.unit.find(id)
            return u ~= nil and not dfhack.units.isDead(u) and dfhack.units.isActive(u)
        end)
        if not ok or alive then return true end   -- can't tell: counted alive (no second party on a guess)
    end
    return false
end

-- (0.105.127) the player's switch is the yes for each test: a war party again once the
-- last one is dead (was once a fort); a later one is SPAWN_COUNT_NEXT strong
function spawn_party(civ, count)
    local before = spawned()
    if before and party_alive(before) then return nil, 'the last war party (' .. tostring(before.count) .. ') is still on the map' end
    count = count or (before and SPAWN_COUNT_NEXT or SPAWN_COUNT)
    if not civ or not civ.id or not civ.race or civ.race == '?' then return nil, 'no civ at war to send it' end
    local okm, SP = pcall(reqscript, 'ai-spawn')
    if not okm or type(SP) ~= 'table' or not SP.spawn_units then
        return nil, 'no ai-spawn (create-unit or dfhack.units.create): ' .. tostring(SP):sub(1, 200)
    end
    local at = edge_spot()
    if not at then return nil, 'no map-edge surface tile the fort can be walked to from' end
    local group = nil          -- a government of the civ (create-unit refuses a civilisation as the group)
    pcall(function()
        local g = civ.group_id and df.historical_entity.find(civ.group_id)
        if g and df.historical_entity_type[g.type] ~= 'Civilization' then group = civ.group_id end
    end)
    local spread = SPAWN_SPREAD
    if SP.spawn_tiles then
        while spread < SPAWN_SPREAD_MAX do
            local okt, tiles = pcall(SP.spawn_tiles, {x = at.x, y = at.y, z = at.z}, spread)
            if not okt or type(tiles) ~= 'table' or #tiles >= count then break end   -- unreadable: as it was
            spread = spread + 3
        end
        spread = math.min(spread, SPAWN_SPREAD_MAX)
    end
    local ids, why, info = SP.spawn_units{race = civ.race, count = count, pos = {x = at.x, y = at.y, z = at.z},
                                          spread = spread, civ_id = civ.id, group_id = group,
                                          flags = SPAWN_FLAGS, equip = SPAWN_EQUIP}
    info = type(info) == 'table' and info or {}
    local brief = SP.brief and SP.brief(info) or {route = info.route}
    if not ids or #ids == 0 then
        return nil, ('no war party placed: ' .. tostring(why or 'no unit')):sub(1, SPAWN_WHY), brief
    end
    local rec = {tick = now_tick(), year = df.global.cur_year, count = #ids, asked = count, spread = spread,
                 parties = ((before and before.parties) or (before and 1) or 0) + 1, civ_id = civ.id, civ_name = civ.name,
                 race = civ.race, group_id = group, x = at.x, y = at.y, z = at.z, distance = at.distance,
                 equipped = info.equipped == true, equip_error = info.equip_error, route = info.route, ids = ids,
                 spawn_info = brief}
    pcall(dfhack.persistent.saveSiteData, SPAWN_KEY, rec)
    return rec
end

-- an invitation waiting: the army looked for; WAIT_DAYS with none: the next civ
local function step(rec, dry, came)
    local tr = rec.tries[#rec.tries]
    local seen = army_watch()
    if came then seen.invaders = math.max(seen.invaders, 1); seen.seen_by_brain = true end
    if seen.armies + seen.controllers + seen.invaders > 0 then
        tr.outcome = 'army'
        rec.state, rec.came = 'came', now_tick()
        if not dry then save(rec) end
        return answer(rec, {came = true, armies = seen.armies, controllers = seen.controllers, invaders = seen.invaders})
    end
    local days = (now_tick() - (tonumber(tr.tick) or now_tick())) / INVITE_DAY
    if days < INVITE_WAIT_DAYS then
        return answer(rec, {waiting = true, days = math.floor(days * 10) / 10, quiet = true})
    end
    if dry then return answer(rec, {waiting = true, days = days, dry_run = true}) end
    tr.outcome = 'no_army'
    local no_army = tr.civ_name or (tr.civ_id and ('civ ' .. tostring(tr.civ_id))) or 'no civ named'
    local tried = {}
    for _, t in ipairs(rec.tries) do if t.civ_id then tried[t.civ_id] = true end end
    local nxt
    if #rec.tries < INVITE_CIVS_MAX then
        for _, r in ipairs(rec.ranking or {}) do
            if not tried[r.id] and df.historical_entity.find(r.id) then nxt = r break end
        end
    end
    local name, v = invite_event_type()
    if nxt and name then
        local t2, q = try_civ(rec, name, v, nxt)
        if t2 then
            save(rec)
            return answer(rec, {retried = true, no_army = no_army, entity_set = t2.entity_set,
                                entity_read = t2.entity_read, queued = q.queued})
        end
    end
    rec.state, rec.ended = 'no_army', now_tick()
    -- (0.105.123) the fallback: the top-ranked civ's war party at the map edge, once a fort
    local top = (rec.ranking or {})[1]
    if not top and rec.tries[1] and rec.tries[1].civ_id then
        local t1 = rec.tries[1]
        top = {id = t1.civ_id, name = t1.civ_name, race = t1.race}
    end
    local sp, why, sinfo = spawn_party(top)
    if sp then
        rec.state, rec.came = 'came', now_tick()
        rec.spawned = {count = sp.count, civ_id = sp.civ_id, civ_name = sp.civ_name, race = sp.race, x = sp.x,
                       y = sp.y, z = sp.z, tick = sp.tick, equipped = sp.equipped, route = sp.route,
                       spawn_info = sp.spawn_info}
        rec.civ_id, rec.civ_name, rec.race = sp.civ_id, sp.civ_name, sp.race   -- the siege watch's civ
    else
        rec.spawn_error = why and tostring(why):sub(1, SPAWN_WHY) or nil
        rec.spawn_info = sinfo
    end
    save(rec)
    return answer(rec, {gave_up = true, no_army = no_army, spawned = rec.spawned, spawn_error = rec.spawn_error,
                        spawn_info = rec.spawn_info, equip_error = sp and sp.equip_error or nil})
end

-- dry: read and rank, change nothing. Called by the switch (a new invitation)
-- and by the brain each day while an invitation waits (its army looked for);
-- opts.came: the brain's siege watch saw invaders since the invitation (a
-- siege that came and went while this waited is no "no army").
function invite_siege(dry, opts)
    local rec = invited()
    if rec and rec.state == 'waiting' then
        if not dry then switch_off() end
        return step(rec, dry, type(opts) == 'table' and opts.came == true)
    end
    -- (0.105.127) after a siege that came: again once it is over (no invader alive on the map);
    -- the switch is the player's yes each time (was never again)
    if rec and rec.state ~= 'no_army' then
        local busy = army_watch()
        if busy.invaders > 0 or party_alive() then
            if not dry then switch_off() end
            return {ok = false, rejected = true, done = rec, state = rec.state,
                    error = 'the last siege (year ' .. tostring(rec.year) .. ', ' .. tostring(rec.civ_name or 'no civ named')
                            .. ') is not over: invaders on the map; the switch is off'}
        end
    end
    if rec and not dry and not switch_on() then
        return {ok = false, rejected = true, done = rec, state = rec.state,
                error = 'the invitation ended with no army (tried ' .. table.concat(names_of(rec.tries), ', ')
                        .. '): the switch turned on again starts a new one'}
    end
    local name, v = invite_event_type()
    if not name then return {ok = false, error = 'this DF has no army event (timed_event_type) to queue'} end
    local before = {}
    if rec then for _, t in ipairs(rec.tries or {}) do if t.civ_id then before[t.civ_id] = true end end end
    -- (0.105.127) every civ an earlier invitation waited on sent no army: those are tried again,
    -- and when all the ranked ones are among them, the war party at once (no 7-day waits)
    local quiet = {}
    if rec then
        for _, c in ipairs(rec.no_army_civs or {}) do quiet[c] = true end
        for _, t in ipairs(rec.tries or {}) do if t.civ_id and t.outcome == 'no_army' then quiet[t.civ_id] = true end end
    end
    local ranking = short_rank(rank_civs(reach_rows(), rec and rec.state == 'no_army' and before or {}))
    local civ = ranking[1]
    -- only a repeat test after a war party (state 'came' with `spawned`): a plain no-army
    -- invitation gives DF's armies another try (the civs tried before go last)
    local direct = rec ~= nil and rec.state == 'came' and rec.spawned ~= nil and #ranking > 0
    for _, r in ipairs(ranking) do if not quiet[r.id] then direct = false end end
    local quiet_list = {}
    for c in pairs(quiet) do table.insert(quiet_list, c) end
    table.sort(quiet_list)
    local new = {tick = now_tick(), year = df.global.cur_year, invitation = rec and (rec.invitation or 1) + 1 or 1,
                 ranking = ranking, tries = {}, no_army_civs = quiet_list}
    if rec then new.previous = {state = rec.state, tick = rec.tick, year = rec.year, tried = names_of(rec.tries)} end
    if dry then
        return {ok = true, dry_run = true, event = name, civ_id = civ and civ.id, civ_name = civ and civ.name,
                race = civ and civ.race, relation = civ and civ.relation, ranking = ranking,
                invitation = new.invitation, reinvite = rec ~= nil or nil, direct = direct or nil}
    end
    if direct then
        new.state, new.ended, new.direct = 'no_army', now_tick(), true
        local sp, why, sinfo = spawn_party(civ)
        if sp then
            new.state, new.came = 'came', now_tick()
            new.spawned = {count = sp.count, asked = sp.asked, spread = sp.spread, civ_id = sp.civ_id, civ_name = sp.civ_name,
                           race = sp.race, x = sp.x, y = sp.y, z = sp.z, tick = sp.tick, equipped = sp.equipped,
                           route = sp.route, spawn_info = sp.spawn_info}
            new.civ_id, new.civ_name, new.race = sp.civ_id, sp.civ_name, sp.race
        else
            new.spawn_error = why and tostring(why):sub(1, SPAWN_WHY) or nil
            new.spawn_info = sinfo
        end
        save(new)
        switch_off()
        return answer(new, {gave_up = true, direct = true, no_army = 'every ranked civ sent none before',
                            spawned = new.spawned, spawn_error = new.spawn_error, spawn_info = new.spawn_info,
                            reinvite = true, previous = new.previous})
    end
    local tr, q = try_civ(new, name, v, civ)
    if not tr then return {ok = false, error = q.error, force_said = q.force_said} end
    save(new)
    switch_off()
    return answer(new, {invited = true, entity_set = tr.entity_set, entity_read = tr.entity_read,
                        queued = q.queued, force_said = q.force_said, reinvite = rec ~= nil or nil,
                        previous = new.previous})
end
