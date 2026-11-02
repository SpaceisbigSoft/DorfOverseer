-- (0.105.0) Threats that were only noted before: what the fort does about
-- them, read and acted on here (the planner's half is brain/planner_threats.py).
--
--   * fire: where it burns; the tiles round it get the game's "restricted"
--     traffic (paths go round) and the jobs beside it are taken off, put
--     back exactly once it is out (only tiles the AI changed);
--   * prisoners: invaders caught in cages, where their cages are, and
--     whether a cage room (an animal stockpile inside the fort) exists. DF
--     has no safe way in DFHack to release a prisoner outside or kill one
--     (a pit needs a pit zone and a drop): they are kept, and said so;
--   * thieves and snatchers: by their profession (THIEF, MASTER_THIEF,
--     SNATCHER) or what they are after (unit.path.goal SeekKidnapVictim,
--     ThiefTarget), remembered in the save so the gates get cage traps;
--   * the undead, evil clouds and a reanimating land: the walking dead on
--     the map, clouds that trail across the surface (a flow with a guide),
--     the fort's region (world_region.evil / .reanimating), bodies lying
--     outside there;
--   * werebeast citizens: each change seen is kept with the moon's phase
--     (world_data.moon_phase, a probe: the first change in game tells us
--     the full-moon value), and a cell: a burrow on a jail zone or a free
--     bedroom, its doors locked once the dwarf is inside, unlocked after;
--   * the caverns sealed against a great beast: the doors and hatches on
--     the way down locked (forbidden), unlocked when it has gone;
--   * great dangers on the surface near dwarves out there;
--   * the wounded fetched after a fight: who has DF's Recover wounded
--     labour (unit_labor RECOVER_WOUNDED, job RecoverWounded) and who lies
--     wounded with no job.
-- Fields this module isn't sure of are read inside pcall and reported as
-- found (probe style).
--@module = true

STATE_KEY = 'ai-overseer/threats'
FIRE_RADIUS = 6              -- tiles round a fire restricted, jobs taken off
FIRE_MAX_TILES = 3000        -- tiles restricted at most (a forest fire)
CELL_PREFIX = 'AI moon cell '
local DAY = 1200
local THIEF_PROFS = {THIEF = 'thief', MASTER_THIEF = 'thief', SNATCHER = 'snatcher'}
local THIEF_GOALS = {SeekKidnapVictim = 'snatcher', ThiefTarget = 'thief'}
local FIRE_FLOWS = {Fire = true, Dragonfire = true}
local CLOUD_FLOWS = {MaterialDust = true, MaterialGas = true, MaterialVapor = true}
local GREAT = {'isForgottenBeast', 'isTitan', 'isMegabeast', 'isDemon'}

local function now_tick()
    return df.global.cur_year * 403200 + df.global.cur_year_tick
end

local function name_of(u, txt)
    local ok, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
    return ok and n or ('unit ' .. tostring(u.id))
end

-- the save's record: fire = {tiles = {"x,y,z", ...}}, thieves = {seen = {id
-- = tick}, last, total}, moon = {changes = {{tick, phase}}}, cells = {uid =
-- {burrow, zone, doors = {ids}, tick, locked}}, sealed = {layer = {ids, tick}}
function load_state()
    local ok, d = pcall(dfhack.persistent.getSiteData, STATE_KEY, {})
    d = ok and type(d) == 'table' and d or {}
    for _, k in ipairs({'fire', 'thieves', 'moon', 'cells', 'sealed'}) do
        d[k] = type(d[k]) == 'table' and d[k] or {}
    end
    d.fire.tiles = type(d.fire.tiles) == 'table' and d.fire.tiles or {}
    d.thieves.seen = type(d.thieves.seen) == 'table' and d.thieves.seen or {}
    d.moon.changes = type(d.moon.changes) == 'table' and d.moon.changes or {}
    return d
end

local function save_state(d)
    pcall(dfhack.persistent.saveSiteData, STATE_KEY, d)
end

-- --- pure helpers (tested) -------------------------------------------------------

-- Points {x, y, z} gathered into cells of `cell` tiles on a level: {x, y, z,
-- n}, the biggest first, at most `max`.
function cluster(points, cell, max)
    local by, list = {}, {}
    for _, p in ipairs(points) do
        local k = p.z * 1000000 + (p.x // cell) * 1000 + (p.y // cell)
        local c = by[k]
        if not c then
            c = {x = p.x, y = p.y, z = p.z, n = 0}
            by[k] = c
            table.insert(list, c)
        end
        c.n = c.n + 1
    end
    table.sort(list, function(a, b) return a.n > b.n or (a.n == b.n and (a.z * 1e6 + a.x * 1e3 + a.y) < (b.z * 1e6 + b.x * 1e3 + b.y)) end)
    while max and #list > max do table.remove(list) end
    return list
end

-- Is (x, y, z) within r tiles (on the same level) of one of the points?
function near_any(x, y, z, points, r)
    for _, p in ipairs(points) do
        if p.z == z and math.abs(p.x - x) <= r and math.abs(p.y - y) <= r then return true end
    end
    return false
end

-- A thief or snatcher by its profession's or path goal's name: 'thief',
-- 'snatcher' or nil.
function thief_kind(prof, goal)
    return THIEF_PROFS[prof or ''] or THIEF_GOALS[goal or '']
end

-- The tiles round the fire points: "x,y,z" keys within r on each level, at most max.
function fire_tiles(points, r, max)
    local seen, out = {}, {}
    for _, p in ipairs(points) do
        for y = p.y - r, p.y + r do
            for x = p.x - r, p.x + r do
                local k = ('%d,%d,%d'):format(x, y, p.z)
                if x >= 0 and y >= 0 and not seen[k] then
                    seen[k] = true
                    table.insert(out, k)
                    if #out >= max then return out end
                end
            end
        end
    end
    return out
end

-- The first w x h rectangle of tiles that pass ok(x, y), searched outward
-- from (cx, cy) within r: {x, y} (its top-left corner) or nil.
function find_rect(ok, cx, cy, r, w, h)
    for d = 0, r do
        for y = cy - d, cy + d do
            for x = cx - d, cx + d do
                if math.max(math.abs(x - cx), math.abs(y - cy)) == d then
                    local fits = true
                    for dy = 0, h - 1 do
                        for dx = 0, w - 1 do
                            if not ok(x + dx, y + dy) then fits = false break end
                        end
                        if not fits then break end
                    end
                    if fits then return {x = x, y = y} end
                end
            end
        end
    end
    return nil
end

local function unkey(k)
    local x, y, z = tostring(k):match('^(-?%d+),(-?%d+),(-?%d+)$')
    return tonumber(x), tonumber(y), tonumber(z)
end

-- --- the game -------------------------------------------------------------------

local function is(fn, u)
    local ok, v = pcall(fn, u)
    return ok and v or false
end

local function outside_at(x, y, z)
    local ok, des = pcall(dfhack.maps.getTileFlags, x, y, z)
    return ok and des and des.outside and true or false
end

local function citizens()
    local list, groups = {}, {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z, id = u.id, unit = u}
        p.outside = outside_at(p.x, p.y, p.z)
        table.insert(list, p)
        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(p.x, p.y, p.z))
        if okg and g and g ~= 0 then groups[g] = true end
    end
    return list, groups
end

local function dist_to(pos, list, only_outside)
    local best
    for _, p in ipairs(list) do
        if not only_outside or p.outside then
            local d = math.max(math.abs(p.x - pos.x), math.abs(p.y - pos.y)) + 3 * math.abs(p.z - pos.z)
            if not best or d < best then best = d end
        end
    end
    return best
end

local function reaches(pos, groups)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(pos.x, pos.y, pos.z))
    if not ok or not g or g == 0 then return nil end
    return groups[g] == true
end

local function loose(u)
    return dfhack.units.isActive(u) and not dfhack.units.isDead(u)
        and not u.flags1.caged and not u.flags1.chained and not is(dfhack.units.isHidden, u)
end

local function fire_points()
    local pts = {}
    pcall(function()
        for _, f in ipairs(df.global.flows) do
            if f.density > 0 and FIRE_FLOWS[df.flow_type[f.type]] then
                table.insert(pts, {x = f.pos.x, y = f.pos.y, z = f.pos.z})
            end
        end
    end)
    return pts
end

local function each_job(fn)
    local link = df.global.world.jobs.list.next
    local n = 0
    while link and n < 20000 do
        n = n + 1
        if link.item and fn(link.item) == false then return end
        link = link.next
    end
end

-- fire: where it burns, and the AI's guard round it
local function fire_report(d, cit)
    local out = {fires = 0, spots = {}, guarded_tiles = 0, jobs_near = 0}
    local pts = fire_points()
    out.fires = #pts
    for _, c in ipairs(cluster(pts, 8, 8)) do
        c.near = dist_to(c, cit)
        c.outside = outside_at(c.x, c.y, c.z) or nil
        table.insert(out.spots, c)
    end
    out.guarded_tiles = #d.fire.tiles
    if #pts > 0 then
        pcall(function()
            each_job(function(j)
                local okp, p = pcall(function() return j.pos end)
                if okp and p and p.x >= 0 and near_any(p.x, p.y, p.z, pts, FIRE_RADIUS) then
                    out.jobs_near = out.jobs_near + 1
                end
            end)
        end)
    end
    return out
end

-- prisoners: caught invaders and dangers in cages, and the cage rooms
local function prisoners_report(txt)
    local out = {caged = 0, in_traps = 0, inside = 0, outside = 0, list = {}, cage_rooms = 0, outside_piles = 0,
                 pit_zones = 0, release_supported = false, kill_supported = false}
    for _, u in ipairs(df.global.world.units.active) do
        if u.flags1.caged and dfhack.units.isActive(u) and not dfhack.units.isDead(u)
                and not is(dfhack.units.isCitizen, u)
                and (is(dfhack.units.isInvader, u) or is(dfhack.units.isDanger, u)) then
            out.caged = out.caged + 1
            local row = {id = u.id, name = name_of(u, txt)}
            pcall(function() row.race = df.creature_raw.find(u.race).creature_id end)
            pcall(function()
                local cage = dfhack.units.getContainer and dfhack.units.getContainer(u)
                if not cage then return end
                if cage.flags.in_building then
                    row.trap = true
                    out.in_traps = out.in_traps + 1
                end
                local x, y, z = dfhack.items.getPosition(cage)
                if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
                if x then
                    row.outside = outside_at(x, y, z) or nil
                    if row.outside then out.outside = out.outside + 1 else out.inside = out.inside + 1 end
                end
            end)
            if #out.list < 10 then table.insert(out.list, row) end
        end
    end
    pcall(function()
        for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
            if sp.settings.flags.animals then
                if outside_at(sp.x1, sp.y1, sp.z) then out.outside_piles = out.outside_piles + 1
                else out.cage_rooms = out.cage_rooms + 1 end
            end
        end
    end)
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_PIT_POND) do
            out.pit_zones = out.pit_zones + 1
        end
    end)
    return out
end

local function evil_civ()
    local ok, yes = pcall(function()
        for _, e in ipairs(df.global.world.entities.all) do
            if e.type == df.historical_entity_type.Civilization and e.entity_raw.code == 'EVIL' then return true end
        end
        return false
    end)
    return ok and yes or false
end

-- thieves and snatchers on the map, and the ones seen before (the save)
local function thieves_report(d, t, cit, groups, txt)
    local out = {list = {}, now = 0}
    local mil
    pcall(function() mil = reqscript('ai-military') end)
    for _, u in ipairs(df.global.world.units.active) do
        if loose(u) and not is(dfhack.units.isCitizen, u) then
            local prof, goal
            pcall(function() prof = df.profession[u.profession] end)
            pcall(function() goal = df.unit_path_goal[u.path.goal] end)
            local kind = thief_kind(prof, goal)
            if kind then
                out.now = out.now + 1
                local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                if not d.thieves.seen[tostring(u.id)] then
                    d.thieves.total = (tonumber(d.thieves.total) or 0) + 1
                end
                d.thieves.seen[tostring(u.id)] = t
                d.thieves.last = t
                d.thieves.kinds = type(d.thieves.kinds) == 'table' and d.thieves.kinds or {}
                d.thieves.kinds[kind] = true
                local row = {id = u.id, name = name_of(u, txt), kind = kind, profession = prof, goal = goal,
                             can_reach_dwarves = reaches(pos, groups), inside = not outside_at(pos.x, pos.y, pos.z),
                             distance = dist_to(pos, cit), pos = pos,
                             invader = is(dfhack.units.isInvader, u) or nil}
                if mil and mil.kill_target_ok then
                    local okk, yes = pcall(mil.kill_target_ok, u)
                    row.kill_ok = okk and yes or false
                end
                if #out.list < 10 then table.insert(out.list, row) end
            end
        end
    end
    -- a month's sightings kept (ids), the count and the last for good
    for k, v in pairs(d.thieves.seen) do
        if type(v) ~= 'number' or t - v > 28 * DAY then d.thieves.seen[k] = nil end
    end
    out.seen_total = tonumber(d.thieves.total) or 0
    out.last_seen_days = d.thieves.last and (t - d.thieves.last) // DAY or nil
    out.kinds_seen = d.thieves.kinds
    out.evil_civ = evil_civ()
    return out
end

-- the fort's region: evil, reanimating (world_region, by the site's tiles)
local function region_of(p)
    local out = {}
    pcall(function()
        local rx, ry = dfhack.maps.getTileBiomeRgn(p.x, p.y, p.z)
        local okr, entry = pcall(dfhack.maps.getRegionBiome, rx, ry)
        if not okr or not entry then entry = dfhack.maps.getRegionBiome(xy2pos(rx, ry)) end
        out.evilness = entry.evilness
        local reg = df.world_region.find(entry.region_id)
        if reg then
            out.evil = reg.evil and true or nil
            out.reanimating = reg.reanimating and true or nil
        end
    end)
    return out
end

-- the undead, evil clouds and a reanimating land
local function undead_report(cit, groups, txt)
    local out = {undead = 0, list = {}, clouds = 0, cloud_near = nil, cloud_outside_near = nil, surface_corpses = 0}
    for _, u in ipairs(df.global.world.units.active) do
        if loose(u) and not is(dfhack.units.isCitizen, u) and is(dfhack.units.isUndead, u) then
            out.undead = out.undead + 1
            local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            if #out.list < 10 then
                table.insert(out.list, {id = u.id, name = name_of(u, txt), distance = dist_to(pos, cit),
                                        outside = outside_at(pos.x, pos.y, pos.z) or nil,
                                        can_reach_dwarves = reaches(pos, groups),
                                        invader = is(dfhack.units.isInvader, u) or nil,
                                        great = is(dfhack.units.isGreatDanger, u) or nil})   -- (0.105.0 review)
            end
        end
    end
    pcall(function()
        for _, f in ipairs(df.global.flows) do
            if f.density > 0 and CLOUD_FLOWS[df.flow_type[f.type]] then
                -- (probe) an evil cloud drifts with a guide (flow_guide, trailing);
                -- a dust or gas from a beast or a reaction has none
                local okg, gid = pcall(function() return f.guide_id end)
                if okg and gid and gid ~= -1 and outside_at(f.pos.x, f.pos.y, f.pos.z) then
                    out.clouds = out.clouds + 1
                    local dd = dist_to(f.pos, cit)
                    local od = dist_to(f.pos, cit, true)
                    if dd and (not out.cloud_near or dd < out.cloud_near) then out.cloud_near = dd end
                    if od and (not out.cloud_outside_near or od < out.cloud_outside_near) then out.cloud_outside_near = od end
                    if not out.cloud_material then
                        pcall(function() out.cloud_material = dfhack.matinfo.decode(f.mat_type, f.mat_index):toString() end)
                    end
                end
            end
        end
    end)
    local where = cit[1]
    for _, p in ipairs(cit) do if p.outside then where = p break end end
    if where then
        local r = region_of(where)
        out.evil, out.reanimating, out.evilness = r.evil, r.reanimating, r.evilness
    end
    if out.reanimating then
        pcall(function()
            for _, kind in ipairs({'CORPSE', 'CORPSEPIECE'}) do
                local n = 0
                for _, it in ipairs(df.global.world.items.other[kind]) do
                    n = n + 1
                    if n > 3000 then break end
                    local okp, x, y, z = pcall(dfhack.items.getPosition, it)
                    if okp and x then
                        if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
                        if outside_at(x, y, z) then out.surface_corpses = out.surface_corpses + 1 end
                    end
                end
            end
        end)
    end
    return out
end

local function changed(u)
    local ok, yes = pcall(function()
        return u.enemy.normal_race ~= -1 and u.enemy.normal_race ~= u.race
    end)
    return ok and yes or false
end

-- werebeast citizens, their cells, and the moon
local function were_report(d, t, txt)
    local out = {list = {}, cells = {}}
    pcall(function() out.moon_phase = df.global.world.world_data.moon_phase end)
    local any_changed = false
    for _, u in ipairs(df.global.world.units.active) do
        if dfhack.units.isActive(u) and not dfhack.units.isDead(u) then
            local own = is(dfhack.units.isCitizen, u)
            if not own then pcall(function() own = u.civ_id == df.global.plotinfo.civ_id and is(dfhack.units.isOwnGroup, u) end) end
            local now_changed = own and changed(u)
            if own and (now_changed or (is(dfhack.units.isNightCreature, u) and not is(dfhack.units.isBloodsucker, u))) then
                local row = {id = u.id, name = name_of(u, txt), changed = now_changed or nil}
                local c = d.cells[tostring(u.id)]
                if type(c) == 'table' then row.cell, row.locked = true, c.locked or nil end
                if #out.list < 10 then table.insert(out.list, row) end
                any_changed = any_changed or now_changed
            end
        end
    end
    local ch = d.moon.changes
    local last = ch[#ch]
    if any_changed and (not last or t - (tonumber(last.tick) or 0) > 3 * DAY) then
        table.insert(ch, {tick = t, phase = out.moon_phase})
        while #ch > 6 do table.remove(ch, 1) end
    end
    out.changes = ch
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' then
            table.insert(out.cells, {unit_id = tonumber(uid), locked = c.locked or nil, doors = #(c.doors or {}),
                                     days = c.tick and (t - c.tick) // DAY or nil})
        end
    end
    return out
end

-- great dangers on the surface (not invaders, not the undead) and how near
-- they are to the dwarves who are out there
local function surface_report(cit, txt)
    local out = {list = {}, outside_dwarves = 0}
    for _, p in ipairs(cit) do if p.outside then out.outside_dwarves = out.outside_dwarves + 1 end end
    for _, u in ipairs(df.global.world.units.active) do
        if loose(u) and not is(dfhack.units.isCitizen, u) and is(dfhack.units.isDanger, u)
                and not is(dfhack.units.isInvader, u) and not is(dfhack.units.isUndead, u)
                and not is(dfhack.units.isTame, u) and outside_at(u.pos.x, u.pos.y, u.pos.z) then
            local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            local row = {id = u.id, name = name_of(u, txt), distance_outside = dist_to(pos, cit, true),
                         distance = dist_to(pos, cit), great = is(dfhack.units.isGreatDanger, u) or nil}
            pcall(function() row.size = u.body.size_info.size_cur end)
            for _, f in ipairs(GREAT) do
                if is(dfhack.units[f], u) then row.kind = f:sub(3) break end
            end
            if #out.list < 10 then table.insert(out.list, row) end
        end
    end
    return out
end

-- the wounded fetched: DF's Recover wounded labour and who lies wounded
local function rescue_report()
    local out = {holders = 0, down = 0}
    local labor = df.unit_labor.RECOVER_WOUNDED
    if not labor then out.error = 'no RECOVER_WOUNDED labour in this DF' return out end
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local okl, has = pcall(function() return u.status.labors[labor] end)
        local soldier = u.military.squad_id >= 0
        if okl and has and not soldier then out.holders = out.holders + 1 end
        pcall(function()
            if u.health and u.health.flags.needs_healthcare and u.flags1.on_ground and not u.job.current_job then
                out.down = out.down + 1
            end
        end)
    end
    pcall(function()
        local wd, mode = reqscript('ai-labor').detail_for('RECOVER_WOUNDED')
        if wd then out.detail, out.mode, out.members = tostring(wd.name), mode, #wd.assigned_units end
    end)
    return out
end

function survey(txt)
    local d = load_state()
    local t = now_tick()
    local cit, groups = citizens()
    local out = {}
    local function part(name, fn, ...)
        local ok, v = pcall(fn, ...)
        out[name] = ok and v or {error = tostring(v):sub(1, 160)}
    end
    part('fire', fire_report, d, cit)
    part('prisoners', prisoners_report, txt)
    part('thieves', thieves_report, d, t, cit, groups, txt)
    part('undead', undead_report, cit, groups, txt)
    part('were', were_report, d, t, txt)
    part('surface', surface_report, cit, txt)
    part('rescue', rescue_report)
    out.sealed = {}
    for layer, s in pairs(d.sealed) do
        if type(s) == 'table' then
            out.sealed[layer] = {doors = #(s.ids or {}), days = s.tick and (t - s.tick) // DAY or nil}
        end
    end
    save_state(d)
    return out
end

-- --- actions ---------------------------------------------------------------------

-- Fire: restricted traffic round each fire (only tiles at Normal, kept in
-- the save) and the jobs beside it taken off (at most max_jobs: DF gives
-- back a designation's job, so it's done again while the fire burns);
-- lift: those tiles back to Normal.
function fire_guard(radius, max_jobs, lift, dry_run)
    local d = load_state()
    if lift then
        local n = 0
        for _, k in ipairs(d.fire.tiles) do
            local x, y, z = unkey(k)
            pcall(function()
                local des = dfhack.maps.getTileFlags(x, y, z)
                if des and des.traffic == df.tile_traffic.Restricted then
                    if not dry_run then des.traffic = df.tile_traffic.Normal end
                    n = n + 1
                end
            end)
        end
        if not dry_run then
            d.fire.tiles = {}
            save_state(d)
        end
        return {ok = true, lifted = n, dry_run = dry_run or nil}
    end
    local pts = fire_points()
    if #pts == 0 then return {ok = false, rejected = true, nothing_to_do = true, error = 'no fire burns now'} end
    local have = {}
    for _, k in ipairs(d.fire.tiles) do have[k] = true end
    local marked = 0
    for _, k in ipairs(fire_tiles(pts, radius, FIRE_MAX_TILES)) do
        if not have[k] then
            local x, y, z = unkey(k)
            pcall(function()
                local des = dfhack.maps.getTileFlags(x, y, z)
                if des and des.traffic == df.tile_traffic.Normal then
                    if not dry_run then
                        des.traffic = df.tile_traffic.Restricted
                        table.insert(d.fire.tiles, k)
                        have[k] = true
                    end
                    marked = marked + 1
                end
            end)
        end
    end
    local found = {}
    pcall(function()
        each_job(function(j)
            local okp, p = pcall(function() return j.pos end)
            local okt, jt = pcall(function() return df.job_type[j.job_type] end)
            if okp and p and p.x >= 0 and okt and fire_job_ok(jt) and near_any(p.x, p.y, p.z, pts, radius) then
                table.insert(found, j)
                if #found >= max_jobs then return false end
            end
        end)
    end)
    local removed = 0
    if not dry_run then
        for _, j in ipairs(found) do
            if pcall(dfhack.job.removeJob, j) then removed = removed + 1 end
        end
        save_state(d)
    end
    return {ok = true, fires = #pts, restricted = marked, jobs_removed = dry_run and #found or removed,
            dry_run = dry_run or nil}
end

-- (0.105.0 review) the jobs the fire guard may take off: digging, building
-- (constructions and buildings) and hauling. Never eating, drinking,
-- sleeping, fetching the wounded or any care.
-- (ConstructX jobs other than ConstructBuilding are workshop crafts: kept)
local FIRE_JOB_PREFIX = {'Dig', 'Carve', 'Store', 'Haul', 'Bring', 'Remove', 'Dump'}
local FIRE_JOB_EXACT = {ConstructBuilding = true, DetailWall = true, DetailFloor = true, SmoothWall = true,
                        SmoothFloor = true, DestroyBuilding = true, StoreItemInHospital = false}
local FIRE_JOB_NEVER = {Eat = true, Drink = true, Drink2 = true, Sleep = true, RecoverWounded = true,
                        DiagnosePatient = true, ImmobilizeBreak = true, DressWound = true, CleanPatient = true,
                        Surgery = true, Suture = true, SetBone = true, PlaceInTraction = true,
                        BringCrutch = true, ApplyCast = true, GiveFood = true, GiveWater = true,
                        BringItemToPatient = true, Rest = true, SeekInfant = true}
function fire_job_ok(jt)
    if type(jt) ~= 'string' or FIRE_JOB_NEVER[jt] then return false end
    if FIRE_JOB_EXACT[jt] ~= nil then return FIRE_JOB_EXACT[jt] end
    for _, p in ipairs(FIRE_JOB_PREFIX) do
        if jt:sub(1, #p) == p then return true end
    end
    return false
end

local function interior_floor(x, y, z)
    local ok, yes = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        if not tt then return false end
        local a = df.tiletype.attrs[tt]
        if df.tiletype_shape[a.shape] ~= 'FLOOR' then return false end
        local des = dfhack.maps.getTileFlags(x, y, z)
        if not des or des.outside or des.hidden or des.flow_size > 0 then return false end
        if des.feature_global or des.feature_local then return false end      -- not in a cavern
        if dfhack.buildings.findAtTile(xyz2pos(x, y, z)) then return false end
        return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) ~= 0
    end)
    return ok and yes or false
end

-- A cage room: an animal stockpile (where full cages go) on free floor
-- inside the fort, near where most citizens are, 3x3.
function prisoner_room(dry_run)
    local cit = citizens()
    if #cit == 0 then return {ok = false, error = 'no citizens'} end
    local byz = {}
    for _, p in ipairs(cit) do
        if not p.outside then byz[p.z] = byz[p.z] or {} table.insert(byz[p.z], p) end
    end
    local z, best = nil, 0
    for zz, l in pairs(byz) do if #l > best then z, best = zz, #l end end
    if not z then return {ok = false, error = 'no citizen is inside the fort'} end
    local xs, ys = {}, {}
    for _, p in ipairs(byz[z]) do table.insert(xs, p.x) table.insert(ys, p.y) end
    table.sort(xs) table.sort(ys)
    local cx, cy = xs[(#xs + 1) // 2], ys[(#ys + 1) // 2]
    local spot = find_rect(function(x, y) return interior_floor(x, y, z) end, cx, cy, 30, 3, 3)
    if not spot then return {ok = false, error = 'no free 3x3 floor inside the fort near the dwarves'} end
    local out = {ok = true, x = spot.x, y = spot.y, z = z, dry_run = dry_run or nil}
    local qf = reqscript('quickfort')
    local function put(dry)
        local ok, stats = pcall(qf.apply_blueprint, {mode = 'place', data = {[z] = {[spot.y] = {[spot.x] = 'a(3x3)'}}},
                                                     pos = {x = 0, y = 0, z = 0}, command = 'run', dry_run = dry})
        return ok and stats and stats.place_designated and stats.place_designated.value > 0
    end
    if not put(true) then return {ok = false, error = ('the game would not take a stockpile at x%d y%d'):format(spot.x, spot.y)} end
    if dry_run then return out end
    if not put(false) then return {ok = false, error = 'the game refused the cage stockpile'} end
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(spot.x, spot.y, z))
        if b and b:getType() == df.building_type.Stockpile then b.name = 'AI prisoners' end
    end)
    return out
end

local function burrow_named(name, make)
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if tostring(b.name) == name then return b end
    end
    if not make then return nil end
    local b = df.burrow:new()
    b.id = df.global.plotinfo.burrows.next_id
    df.global.plotinfo.burrows.next_id = b.id + 1
    b.name = name
    df.global.plotinfo.burrows.list:insert('#', b)
    return b
end

local function zone_by_id(id)
    for _, b in ipairs(df.global.world.buildings.all) do
        if b.id == id then return b end
    end
end

local function in_zone(z, x, y, zz)
    if zz ~= z.z or x < z.x1 or x > z.x2 or y < z.y1 or y > z.y2 then return false end
    local ok, yes = pcall(dfhack.buildings.containsTile, z, x, y)
    return not ok or yes
end

-- (0.105.0 review) a tile on the zone or beside one of its own tiles (not
-- just in the ring round its bounding box: a bedroom need not be square)
function touches_zone(inz, x, y)
    for dy = -1, 1 do
        for dx = -1, 1 do
            if inz(x + dx, y + dy) then return true end
        end
    end
    return false
end

-- The doors and hatches on a zone's edge (its tiles and the tiles touching them).
local function zone_doors(z)
    local out = {}
    local function inz(x, y) return in_zone(z, x, y, z.z) end
    for y = z.y1 - 1, z.y2 + 1 do
        for x = z.x1 - 1, z.x2 + 1 do
            if touches_zone(inz, x, y) then pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z.z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    out[b.id] = b
                end
            end) end
        end
    end
    return out
end

-- (0.105.0 review) another citizen in the zone (never locked in with a werebeast)
local function other_in_zone(z, uid)
    local ok, yes = pcall(function()
        for _, c in ipairs(dfhack.units.getCitizens(true)) do
            if c.id ~= uid and in_zone(z, c.pos.x, c.pos.y, c.pos.z) then return true end
        end
        return false
    end)
    return not ok or yes
end

-- A room for a cell: a jail zone, else a free bedroom; the nearest to pos,
-- never one another cell holds.
local function cell_room(pos, taken)
    local best, bd
    local function try(z)
        if taken[z.id] then return end
        local dd = math.abs(z.x1 - pos.x) + math.abs(z.y1 - pos.y) + 3 * math.abs(z.z - pos.z)
        if not bd or dd < bd then best, bd = z, dd end
    end
    pcall(function() for _, z in ipairs(df.global.world.buildings.other.ZONE_DUNGEON) do try(z) end end)
    if best then return best, 'jail' end
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_BEDROOM) do
            if z.assigned_unit_id == -1 then try(z) end
        end
    end)
    return best, best and 'bedroom' or nil
end

-- Werebeasts in cells for the full moon: each id given gets a burrow on its
-- room (a jail, else a free bedroom); once the dwarf is inside, the room's
-- doors are locked. release: unlocked (only the doors the AI locked), the
-- dwarf out of the burrow, every cell not in `ids` let out too.
function moon_cell(ids, release, dry_run, txt)
    local d = load_state()
    local t = now_tick()
    local want = {}
    for _, id in ipairs(ids or {}) do want[tostring(id)] = true end
    local out = {ok = true, placed = {}, locked = {}, released = {}, waiting = {}, dry_run = dry_run or nil}
    local function free(uid, c)
        local u = df.unit.find(tonumber(uid))
        -- (0.105.0 review) never a cell whose werebeast has changed now (raging):
        -- a call listing only another werebeast, or a release, let it out
        if u and changed(u) then
            out.kept = out.kept or {}
            table.insert(out.kept, name_of(u, txt))
            return
        end
        if not dry_run then
            for _, bid in ipairs(c.doors or {}) do
                pcall(function()
                    local b = df.building.find(bid)
                    if b then b.door_flags.forbidden = false end
                end)
            end
            pcall(function()
                local b = burrow_named(CELL_PREFIX .. uid, false)
                if b then
                    if u then dfhack.burrows.setAssignedUnit(b, u, false) end
                    dfhack.burrows.clearTiles(b)
                end
            end)
            d.cells[uid] = nil
        end
        table.insert(out.released, u and name_of(u, txt) or uid)
    end
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' and (release or not want[uid]) then free(uid, c) end
    end
    if not release then
        local taken = {}
        for _, c in pairs(d.cells) do if type(c) == 'table' and c.zone then taken[c.zone] = true end end
        for uid in pairs(want) do
            local u = df.unit.find(tonumber(uid))
            if u and not dfhack.units.isDead(u) then
                local c = d.cells[uid]
                local z = c and c.zone and zone_by_id(c.zone)
                if not z then
                    local kind
                    z, kind = cell_room(u.pos, taken)
                    if not z then
                        out.ok = #out.placed + #out.locked > 0
                        out.error = 'no jail zone or free bedroom for a cell'
                    elseif not dry_run then
                        -- (0.105.0 review) the burrow made inside pcall: a failure is said,
                        -- and the cells already done this call are still saved below
                        local okb, eb = pcall(function()
                            local b = burrow_named(CELL_PREFIX .. uid, true)
                            dfhack.burrows.clearTiles(b)
                            for y = z.y1, z.y2 do
                                for x = z.x1, z.x2 do
                                    if in_zone(z, x, y, z.z) then dfhack.burrows.setAssignedTile(b, xyz2pos(x, y, z.z), true) end
                                end
                            end
                            dfhack.burrows.setAssignedUnit(b, u, true)
                        end)
                        if okb then
                            c = {zone = z.id, kind = kind, tick = t, doors = {}}
                            d.cells[uid] = c
                            taken[z.id] = true
                        else
                            out.error = 'the cell\'s burrow could not be made: ' .. tostring(eb)
                            out.ok = #out.placed + #out.locked > 0
                            z = nil
                        end
                    end
                    if z then table.insert(out.placed, name_of(u, txt)) end
                elseif not c.locked then
                    if in_zone(z, u.pos.x, u.pos.y, u.pos.z) and other_in_zone(z, u.id) then
                        table.insert(out.waiting, name_of(u, txt))       -- (0.105.0 review) someone else inside
                    elseif in_zone(z, u.pos.x, u.pos.y, u.pos.z) then
                        for id, b in pairs(zone_doors(z)) do
                            local okf, f = pcall(function() return b.door_flags.forbidden end)
                            if okf and not f then
                                if not dry_run then
                                    b.door_flags.forbidden = true
                                    table.insert(c.doors, id)
                                end
                            end
                        end
                        if not dry_run then c.locked = true end
                        table.insert(out.locked, name_of(u, txt))
                    else
                        table.insert(out.waiting, name_of(u, txt))
                    end
                end
            end
        end
    end
    if not dry_run then save_state(d) end
    if #out.placed + #out.locked + #out.released + #out.waiting == 0 and not out.error then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'every cell is as it should be'}
    end
    return out
end

-- (0.105.0 review) a citizen down in the cavern (on a cavern tile between
-- its levels, z1..z2): the seal would shut them out on the far side
local function citizen_in_cavern(z1, z2)
    if not z1 or not z2 then return nil end
    local lo, hi = math.min(z1, z2), math.max(z1, z2)
    local ok, who = pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local p = u.pos
            if p.z >= lo and p.z <= hi then
                local des = dfhack.maps.getTileFlags(p.x, p.y, p.z)
                if des and (des.feature_global or des.feature_local) then return u end
            end
        end
    end)
    return ok and who or nil
end

-- The caverns sealed: the doors and hatches on the given tiles (the way
-- down to the cavern: where the fort's ground meets it, the stair column)
-- locked; open: unlocked (only those the AI locked). (0.105.0 review) only
-- on those very tiles (no longer every door within a tile of them), and
-- refused while a citizen is down in the cavern (z1..z2: its levels).
function seal_cavern(layer, tiles, open, dry_run, z1, z2)
    local d = load_state()
    local t = now_tick()
    local rec = type(d.sealed[layer]) == 'table' and d.sealed[layer] or nil
    if open then
        if not rec then return {ok = false, rejected = true, nothing_to_do = true, error = 'the AI sealed nothing there'} end
        local n = 0
        for _, bid in ipairs(rec.ids or {}) do
            pcall(function()
                local b = df.building.find(bid)
                if b then
                    if not dry_run then b.door_flags.forbidden = false end
                    n = n + 1
                end
            end)
        end
        if not dry_run then
            d.sealed[layer] = nil
            save_state(d)
        end
        return {ok = true, unlocked = n, layer = layer, dry_run = dry_run or nil}
    end
    local inside = citizen_in_cavern(z1, z2)
    if inside then
        return {ok = false, rejected = true, waiting = true,
                error = name_of(inside) .. ' is down in ' .. tostring(layer) .. ': not sealed while a dwarf is on the far side'}
    end
    local found = {}
    for _, p in ipairs(tiles or {}) do
        local x, y, z = tonumber(p.x), tonumber(p.y), tonumber(p.z)
        if x and y and z then
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    found[b.id] = b
                end
            end)
        end
    end
    rec = rec or {ids = {}, tick = t}
    local have, n, already = {}, 0, 0
    for _, id in ipairs(rec.ids) do have[id] = true end
    for id, b in pairs(found) do
        local okf, f = pcall(function() return b.door_flags.forbidden end)
        if okf and not f then
            if not dry_run then
                b.door_flags.forbidden = true
                if not have[id] then table.insert(rec.ids, id) end
            end
            n = n + 1
        elseif okf then
            already = already + 1
        end
    end
    if n == 0 then
        return {ok = false, rejected = true, nothing_to_do = already > 0,
                error = already > 0 and 'every door and hatch on the way down is locked already'
                    or 'no door or hatch on the way down to lock'}
    end
    if not dry_run then
        d.sealed[layer] = rec
        save_state(d)
    end
    return {ok = true, locked = n, layer = layer, dry_run = dry_run or nil}
end
