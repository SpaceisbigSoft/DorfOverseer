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

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end
local function report_units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end

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
    return U.abs_tick()
end

local function name_of(u, txt)
    local ok, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
    return ok and n or ('unit ' .. tostring(u.id))
end

-- the save's record: fire = {tiles = {"x,y,z", ...}}, thieves = {seen = {id
-- = tick}, last, total}, moon = {changes = {{tick, phase}}}, cells = {uid =
-- {burrow, zone, doors = {ids}, tick, locked}}, sealed = {layer = {ids, tick,
-- pulled?}}, (0.105.26) openings = {"x,y,z" = {x, y, z, kind, source, tick}}
function load_state()
    local d = U.site_get(STATE_KEY, {})
    for _, k in ipairs({'fire', 'thieves', 'moon', 'cells', 'sealed', 'openings'}) do
        d[k] = type(d[k]) == 'table' and d[k] or {}
    end
    d.fire.tiles = type(d.fire.tiles) == 'table' and d.fire.tiles or {}
    d.thieves.seen = type(d.thieves.seen) == 'table' and d.thieves.seen or {}
    d.moon.changes = type(d.moon.changes) == 'table' and d.moon.changes or {}
    return d
end

local function save_state(d)
    U.site_put(STATE_KEY, d)
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
    for _, u in ipairs(report_citizens(true)) do
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
    for _, u in ipairs(report_units()) do
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

-- (0.105.40 E3) every entity of the world was walked each report (a big
-- world: thousands); the world's civilisations and their raws are made at
-- world creation, so the answer is kept for the world loaded (its save
-- folder and the entity count: a new entity of any kind reads it again)
local function evil_civ()
    local okk, key = pcall(function()
        return tostring(df.global.world.cur_savegame.save_dir) .. '#' .. #df.global.world.entities.all
    end)
    local m = EVIL_CIV_MEMO
    if okk and m and m.key == key then return m.yes end
    local ok, yes = pcall(function()
        for _, e in ipairs(df.global.world.entities.all) do
            if e.type == df.historical_entity_type.Civilization and e.entity_raw.code == 'EVIL' then return true end
        end
        return false
    end)
    local v = ok and yes or false
    if okk and ok then EVIL_CIV_MEMO = {key = key, yes = v} end
    return v
end

-- thieves and snatchers on the map, and the ones seen before (the save)
local function thieves_report(d, t, cit, groups, txt)
    local out = {list = {}, now = 0}
    local mil
    pcall(function() mil = reqscript('ai-military') end)
    for _, u in ipairs(report_units()) do
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
    for _, u in ipairs(report_units()) do
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

-- (0.105.40b) evil weather: the clouds on the map's surface (a flow with a
-- guide, or any cloud whose material carries a syndrome), DF's own list of
-- evil weather (world.world_data.region_weather: creeping clouds with their
-- in-game coordinates, falling material - blood or syndrome rain - with its
-- region tile, and DF's `announced` flag), the plain rain over the map
-- (current_weather) and, while any of it is about, the hostile units
-- standing out under the sky (the squads aren't sent out to them).
-- Bounded: a few names, at most WEATHER_MAX_FLOWS flows read, the
-- citizens' distances measured from at most WEATHER_MAX_NEAR_TILES cloud tiles.
-- (fix41) its own report section (weather_section), in the pulse too: a
-- cloud can cross from the map's edge in hours, the daily report was late.
WEATHER_MAX_FLOWS = 20000
-- a region cloud this close to the map's edge counts as near the fort (the
-- brain's planner_config weather_edge_near, 150: about a day's drift, so the
-- pulse and the event below see it while there is time to call everyone in)
WEATHER_EDGE_NEAR = 150
-- region clouds reported up to this far (the brain applies its own
-- weather_edge_near, which may be set wider than the default above)
WEATHER_EDGE_REPORT = 400
WEATHER_EVENT_NEAR = 120      -- a cloud this close (or DF's announcement) is an event: a cycle now
WEATHER_WATCH_TICKS = 50      -- the event watch reads DF's weather list at most once a game hour
WEATHER_MAX_NEAR_TILES = 300
WEATHER_MAX_IDS = 40
local WEATHER_FLOWS = {MaterialDust = true, MaterialGas = true, MaterialVapor = true, ItemCloud = true}
local BLOOD_IDS = {BLOOD = true, ICHOR = true, GOO = true, PUS = true}

-- a material's first syndrome, its effects (CE types, up to 6), whether it is blood
local SYN_MEMO = {}
local function material_facts(mt, mi)
    local key = tostring(mt) .. ':' .. tostring(mi)
    if SYN_MEMO[key] ~= nil then return SYN_MEMO[key] end
    local out = {}
    pcall(function()
        local info = dfhack.matinfo.decode(mt, mi)
        if not info then return end
        pcall(function() out.name = tostring(info:toString()):sub(1, 60) end)
        local m = info.material
        local id = m and tostring(m.id or '') or ''
        out.blood = BLOOD_IDS[id] or (out.name and out.name:lower():find('blood', 1, true)) and true or nil
        pcall(function()
            for _, syn in ipairs(m.syndrome.syndrome) do
                out.syndrome = out.syndrome or tostring(syn.syn_name or ''):sub(1, 60)
                out.effects = out.effects or {}
                for _, e in ipairs(syn.ce) do
                    if #out.effects >= 6 then break end
                    local okt, ty = pcall(function() return df.creature_interaction_effect_type[e:getType()] end)
                    if okt and ty then table.insert(out.effects, tostring(ty)) end
                end
                if out.syndrome == '' then out.syndrome = 'unnamed syndrome' end
            end
        end)
    end)
    SYN_MEMO[key] = out
    return out
end

-- (pure) DF's evil weather records against the fort's map: rows are
-- {kind = 'cloud'|'rain', gx, gy (clouds: global map tiles), rx, ry (rain:
-- its world tile, or region tile), announced, left, mx, my, mat = facts};
-- map = {rx, ry (the map's corner in region tiles, 48 map tiles each), w, h
-- (map tiles), ww, wh (the world's size in world tiles)}. Returns {clouds,
-- rains, cloud_edge (tiles from the map's edge, 0 on it: the nearest cloud
-- drifting this way within edge_near, else the nearest one), approaching,
-- rain_here, announced, left, cloud_mat, rain_mat}
function weather_rows_summary(rows, map, edge_near)
    local out = {clouds = 0, rains = 0}
    edge_near = edge_near or WEATHER_EDGE_NEAR
    local ox, oy = map.rx * 48, map.ry * 48
    local wx, wy = map.rx // 16, map.ry // 16
    local tiles_x, tiles_y = math.max(1, map.w // 48), math.max(1, map.h // 48)
    local best_appr
    for _, r in ipairs(rows) do
        if r.kind == 'cloud' and r.gx and r.gx > -30000 then
            local lx, ly = r.gx - ox, r.gy - oy
            local dx = math.max(0, -lx, lx - (map.w - 1))
            local dy = math.max(0, -ly, ly - (map.h - 1))
            local d = math.max(dx, dy)
            out.clouds = out.clouds + 1
            if d <= edge_near then
                local cx, cy = map.w // 2, map.h // 2
                local appr = d == 0 or ((r.mx or 0) ~= 0 and (r.mx > 0) == (lx < cx))
                    or ((r.my or 0) ~= 0 and (r.my > 0) == (ly < cy)) or false
                -- (fix41) a nearer cloud drifting away doesn't hide one coming
                local better = not out.cloud_edge or (appr and not best_appr)
                    or (appr == best_appr and d < out.cloud_edge)
                if better then
                    out.cloud_edge, out.cloud_mat, best_appr = d, r.mat, appr
                    out.approaching = appr or nil
                end
                if r.announced then out.announced = true end
                if r.left and (not out.left or r.left > out.left) then out.left = r.left end
            end
        elseif r.kind == 'rain' and r.rx then
            -- (probe) DF calls it the world tile. (fix41) Read as a region
            -- tile only when it can't be a world tile (past the world's
            -- width or height): a small world tile's number can be a region
            -- tile's number too, and rain on the wrong tile would be taken
            -- for the fort's
            local here = (r.rx == wx and r.ry == wy)
            if not here and map.ww and map.wh and (r.rx >= map.ww or r.ry >= map.wh) then
                here = r.rx >= map.rx and r.rx < map.rx + tiles_x and r.ry >= map.ry and r.ry < map.ry + tiles_y
            end
            if here then
                out.rains = out.rains + 1
                out.rain_here = true
                if not out.rain_mat or (r.mat and r.mat.syndrome and not out.rain_mat.syndrome) then out.rain_mat = r.mat end
                if r.announced then out.announced = true end
                if r.left and (not out.left or r.left > out.left) then out.left = r.left end
            end
        end
    end
    return out
end

-- the fort's map against the world: its corner in region tiles, its size,
-- the world's size in world tiles (nil when unreadable)
local function weather_map()
    local okm, map = pcall(function()
        local m = df.global.world.map
        return {rx = m.region_x, ry = m.region_y, w = m.x_count, h = m.y_count}
    end)
    if not (okm and map) then return nil end
    pcall(function()
        local wd = df.global.world.world_data
        map.ww, map.wh = wd.world_width, wd.world_height
    end)
    return map
end

local function weather_rows()
    local rows = {}
    pcall(function()
        for _, w in ipairs(df.global.world.world_data.region_weather) do
            if #rows >= 50 then break end
            local t = df.region_weather_type[w.type]
            local row = {announced = w.flags.announced and true or nil, left = w.remaining_duration,
                         mat = material_facts(w.mat_type, w.mat_index)}
            if t == 'FallingMaterial' then
                row.kind, row.rx, row.ry = 'rain', w.region_x, w.region_y
            elseif t == 'CreepingGas' or t == 'CreepingVapor' or t == 'CreepingDust' then
                row.kind, row.gx, row.gy = 'cloud', w.world_in_game_x, w.world_in_game_y
                row.mx, row.my = w.cloud_x_movement, w.cloud_y_movement
            end
            if row.kind then table.insert(rows, row) end
        end
    end)
    return rows
end

function weather_report(cit)
    SYN_MEMO = {}                 -- one report's lookups (another save has other materials)
    local out = {evil_cloud = 0}
    local flows_read = 0
    -- (fix41) the citizens' positions read once (all, and those outside),
    -- and measured from at most WEATHER_MAX_NEAR_TILES cloud tiles
    local all_p, out_p = {}, {}
    for _, p in ipairs(cit or {}) do
        local q = {p.x, p.y, p.z}
        all_p[#all_p + 1] = q
        if p.outside then out_p[#out_p + 1] = q end
    end
    local function nearest(pos, list, best)
        local x, y, z = pos.x, pos.y, pos.z
        for i = 1, #list do
            local q = list[i]
            local d = math.max(math.abs(q[1] - x), math.abs(q[2] - y)) + 3 * math.abs(q[3] - z)
            if not best or d < best then best = d end
        end
        return best
    end
    local measured = 0
    pcall(function()
        for _, f in ipairs(df.global.flows) do
            flows_read = flows_read + 1
            if flows_read > WEATHER_MAX_FLOWS then out.flows_capped = true break end
            if f.density > 0 and WEATHER_FLOWS[df.flow_type[f.type]] and outside_at(f.pos.x, f.pos.y, f.pos.z) then
                local okg, gid = pcall(function() return f.guide_id end)
                local facts = material_facts(f.mat_type, f.mat_index)
                if (okg and gid and gid ~= -1) or facts.syndrome then
                    out.evil_cloud = out.evil_cloud + 1
                    if measured < WEATHER_MAX_NEAR_TILES then
                        measured = measured + 1
                        out.cloud_near = nearest(f.pos, all_p, out.cloud_near)
                        out.cloud_outside_near = nearest(f.pos, out_p, out.cloud_outside_near)
                    else
                        out.near_capped = true
                    end
                    if not out.material or (facts.syndrome and not out.syndrome) then
                        out.material, out.syndrome, out.effects = facts.name, facts.syndrome, facts.effects
                    end
                end
            end
        end
    end)
    local map = weather_map()
    local region = {clouds = 0, rains = 0}
    if map then
        local oks, r = pcall(weather_rows_summary, weather_rows(), map, WEATHER_EDGE_REPORT)
        if oks and r then region = r end
    end
    out.region = {clouds = region.clouds, rains = region.rains, cloud_edge = region.cloud_edge,
                  approaching = region.approaching, announced = region.announced, left = region.left,
                  cloud_material = region.cloud_mat and region.cloud_mat.name or nil,
                  cloud_syndrome = region.cloud_mat and region.cloud_mat.syndrome or nil,
                  edge_near = WEATHER_EDGE_NEAR}
    if region.rain_here then
        local m = region.rain_mat or {}
        out.rain = m.blood and not m.syndrome and 'blood' or 'evil'
        out.rain_material, out.rain_syndrome = m.name, m.syndrome
        out.rain_effects = m.effects
        if not out.syndrome then out.syndrome, out.effects = m.syndrome, m.effects end
    end
    if not out.syndrome and region.cloud_mat then out.syndrome = region.cloud_mat.syndrome end
    pcall(function()
        for i = 0, 4 do
            for j = 0, 4 do
                if df.global.current_weather[i][j] == df.weather_type.Rain then out.raining = true end
            end
        end
    end)
    -- (fix41-ff) near: a region cloud within WEATHER_EDGE_NEAR (the brain's
    -- weather_edge_near), not every one reported out to WEATHER_EDGE_REPORT:
    -- the walk of the units below runs only then
    out.near_fort = out.evil_cloud > 0 or (region.cloud_edge ~= nil and region.cloud_edge <= WEATHER_EDGE_NEAR)
        or region.rain_here or false
    -- the hostile units out under the sky, while any of it is about
    if out.near_fort then
        out.enemies_outside = {}
        pcall(function()
            for _, u in ipairs(report_units()) do
                if #out.enemies_outside >= WEATHER_MAX_IDS then break end
                if loose(u) and not is(dfhack.units.isCitizen, u)
                        and (is(dfhack.units.isInvader, u) or is(dfhack.units.isUndead, u)
                             or is(dfhack.units.isGreatDanger, u) or is(dfhack.units.isDanger, u))
                        and outside_at(u.pos.x, u.pos.y, u.pos.z) then
                    table.insert(out.enemies_outside, u.id)
                end
            end
        end)
    end
    return out
end

-- (fix41) The report's own `weather` section (lua/ai-bridge.lua SECTIONS
-- and PULSE_SECTIONS): weather_report with the citizens read here
function weather_section()
    local cit = citizens()
    return weather_report(cit)
end

-- (fix41) The event watch (lua/ai-bridge.lua cmd_status, polled every few
-- seconds by the overseer): at most once a game hour DF's weather list is
-- read (no flows, no units: at most 50 rows), and an event is returned when
-- an evil cloud comes within WEATHER_EVENT_NEAR tiles of the map's edge
-- drifting this way (or is over the map), DF announces evil weather near
-- the fort, or evil rain falls on it - once each time it begins, so the
-- overseer runs a cycle (the pulse's weather section) now, not tomorrow.
-- now: the absolute tick; site: the save's key (another save starts afresh).
WEATHER_WATCH = WEATHER_WATCH or {}
function weather_watch(now, site)
    local w = WEATHER_WATCH
    if w.site ~= site or not w.tick or now < w.tick then
        WEATHER_WATCH = {site = site}
        w = WEATHER_WATCH
    elseif now - w.tick < WEATHER_WATCH_TICKS then
        return nil
    end
    w.tick = now
    local map = weather_map()
    if not map then return nil end
    local ok, r = pcall(weather_rows_summary, weather_rows(), map, WEATHER_EVENT_NEAR)
    if not ok or not r then return nil end
    local near = r.cloud_edge ~= nil and r.approaching == true
    local rain = r.rain_here == true
    local announced = r.announced == true
    local ev
    if (near and not w.near) or (rain and not w.rain) or (announced and not w.announced) then
        ev = {kind = 'weather', cloud_edge = near and r.cloud_edge or nil, rain = rain or nil,
              announced = announced or nil,
              material = (near and r.cloud_mat and r.cloud_mat.name) or (rain and r.rain_mat and r.rain_mat.name) or nil}
    end
    w.near, w.rain, w.announced = near, rain, announced
    return ev
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
    for _, u in ipairs(report_units()) do
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
    for _, u in ipairs(report_units()) do
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
    for _, u in ipairs(report_citizens(true)) do
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

-- --- (0.105.26) the cavern openings ------------------------------------------------
-- F lost 54 and C 12 to forgotten beasts that came in through caverns the AI
-- opened. Every opening onto a cavern the AI knows is kept in the save
-- (state.openings, by "x,y,z"): the gates scan's cavern entrances (their
-- doors and hatches, or the opening itself while it has none: the brain has
-- doors put on it), each cavern well's shaft hatch (the well's own lever
-- works it: the shaft watcher shuts it while a great beast is in the caverns),
-- and every door or hatch the seal found on the way down. The seal locks
-- them all while a forgotten beast or other great danger is about.
OPENINGS_MAX = 60

local function okey(x, y, z) return ('%d,%d,%d'):format(x, y, z) end

-- Pure-ish: one opening put on record (false when known, bad or the record is full).
function note_opening(d, x, y, z, kind, source, t)
    x, y, z = tonumber(x), tonumber(y), tonumber(z)
    if not (x and y and z) then return false end
    local k = okey(x, y, z)
    local o = d.openings[k]
    if o then
        if kind ~= 'open' and o.kind == 'open' then o.kind, o.source = kind, source end
        return false
    end
    local n = 0
    for _ in pairs(d.openings) do n = n + 1 end
    if n >= OPENINGS_MAX then return false end
    d.openings[k] = {x = x, y = y, z = z, kind = kind, source = source, tick = t}
    return true
end

function gather_openings(d, t)
    pcall(function()
        local G = reqscript('ai-gates')
        for _, e in ipairs(G.GATES and G.GATES.entrances or {}) do
            if e.kind == 'cavern' then
                local src = 'cavern entrance ' .. tostring(e.id)
                local doors = 0
                for _, b in ipairs(e.equipment or {}) do
                    if b.kind == 'door' or b.kind == 'hatch' then
                        note_opening(d, b.x1, b.y1, b.z, 'gate', src, t)
                        doors = doors + 1
                    end
                end
                if doors == 0 then note_opening(d, e.x, e.y, e.z, 'open', src, t) end
            end
        end
    end)
    pcall(function()
        for _, w in ipairs(reqscript('ai-builder').well_lids(false) or {}) do
            local h = w.shaft_hatch
            if type(h) == 'table' then
                note_opening(d, h.x, h.y, h.z, 'well', 'cavern well ' .. tostring(w.project_id), t)
            end
        end
    end)
end

-- What stands on one opening now: {building = 'Door'|'Hatch'|other, id,
-- built, locked, closed} (nothing: no building there).
local function opening_state(o)
    local row = {}
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(o.x, o.y, o.z))
        if not b then return end
        local ty = b:getType()
        if ty == df.building_type.Door or ty == df.building_type.Hatch then
            row.building = ty == df.building_type.Door and 'Door' or 'Hatch'
            row.id = b.id
            pcall(function() row.built = b:getBuildStage() >= b:getMaxBuildStage() end)
            pcall(function() row.locked = b.door_flags.forbidden == true end)
            pcall(function() row.closed = b.door_flags.closed == true end)
        else
            row.building = tostring(df.building_type[ty] or ty)
        end
    end)
    return row
end

-- (0.105.26 seal fix) What the seal holds, from its record: {ids = {building
-- id = true} (locked by it, or shut by their lever), locked = {id = true}
-- (the lock), pulled = {id = true} (shut by their lever), levers = {lever id
-- = true}}. The gate watcher (ai-gates) opens none of these while it stands.
function seal_holds(d)
    d = d or load_state()
    local out = {ids = {}, locked = {}, pulled = {}, levers = {}}
    for _, rec in pairs(d.sealed) do
        if type(rec) == 'table' then
            for _, id in ipairs(type(rec.ids) == 'table' and rec.ids or {}) do
                id = tonumber(id) or id
                out.ids[id], out.locked[id] = true, true
            end
            for sid, lever in pairs(type(rec.pulled) == 'table' and rec.pulled or {}) do
                local id = tonumber(sid) or sid
                out.ids[id], out.pulled[id] = true, true
                if lever ~= nil then out.levers[tonumber(lever) or lever] = true end
            end
        end
    end
    return out
end

-- (0.105.26 seal fix) The doors, hatches and bridges of the entrances the
-- gate watcher holds shut now: {building id = true}. The seal's open path
-- leaves these shut (the watcher opens them again when its danger is gone).
local function watcher_held()
    local out = {}
    pcall(function()
        local G = reqscript('ai-gates').GATES
        if type(G) ~= 'table' or type(G.closed) ~= 'table' then return end
        for _, e in ipairs(G.entrances or {}) do
            if G.closed[e.id] then
                for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
                    for _, g in ipairs(list) do if g.id ~= nil then out[g.id] = true end end
                end
            end
        end
    end)
    return out
end

-- {list = [{x, y, z, kind, source, building?, id?, built?, locked?, closed?,
-- sealed? (the seal locked it, or shut it by its lever, and (0.105.26 seal
-- fix) it is locked, or shut, now: one opened again since reads unsealed,
-- so the brain seals it again)}], n}
function openings_report(d, t, txt)
    gather_openings(d, t)
    local held = seal_holds(d)   -- the doors and hatches the seal locked or shut by their lever
    local list = {}
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.x and o.y and o.z then
            local row = opening_state(o)
            if row.id and ((held.locked[row.id] and row.locked) or (held.pulled[row.id] and row.closed)) then
                row.sealed = true
            end
            row.x, row.y, row.z, row.kind, row.source = o.x, o.y, o.z, o.kind, o.source
            table.insert(list, row)
        end
    end
    table.sort(list, function(a, b)
        if a.z ~= b.z then return a.z < b.z end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    return {list = list, n = #list}
end

-- (0.105.26) Citizens down in a cavern (on a cavern tile): the seal waits for them.
function cavern_citizens(txt)
    local out = {list = {}, n = 0}
    for _, u in ipairs(report_citizens(true)) do
        local ok, cave = pcall(function()
            local des = dfhack.maps.getTileFlags(u.pos.x, u.pos.y, u.pos.z)
            return des and (des.feature_global or des.feature_local) and true or false
        end)
        if ok and cave then
            out.n = out.n + 1
            if #out.list < 10 then
                table.insert(out.list, {id = u.id, name = name_of(u, txt), x = u.pos.x, y = u.pos.y, z = u.pos.z})
            end
        end
    end
    return out
end

-- --- who keeps the dwarves from drink and food ------------------------------------
--
-- (item1, 14 Nov) B, 13 Nov 17:05-17:45 (y259 Obsidian - y260 Slate): 66 of
-- 77 citizens died of thirst with 845 drinks in store. DF's gamelog: from the
-- squad's fight with a crossbow thief on, "X cancels Drink: Interrupted by a
-- human spearman." ~4900 times (Eat and Sleep too) for two game months. The
-- spearman (Om Konlihiñer, a visitor told of an artifact by a citizen,
-- beaten in that fight, "I must withdraw!") stayed inside the fort near the
-- stores; DF made every dwarf who saw him on the way to a drink drop it, but
-- he was no invader and not isDanger, so the AI counted no threat, lowered
-- the alarm, opened the gates and sent nobody. The report's job
-- cancellations name who interrupts; this reads them, finds that unit (its
-- race and profession, nearest the cancelling dwarves) and says so: the
-- planner sends a squad at it and kill_target_ok (ai-military) takes it as
-- a target. The other reasons for a cancelled Drink or Eat are counted too,
-- so a parched fort says why.

INTERRUPT_WINDOW = 2 * DAY   -- job cancellations this recent are read
INTERRUPT_MAX_REPORTS = 4000 -- newest reports walked at most
INTERRUPT_NEAR = 20          -- a cancelling dwarf this close (tiles; levels count 3) to the unit
INTERRUPT_MIN = 6            -- this many Drink/Eat/Sleep cancellations by it in the window...
INTERRUPT_MIN_DWARVES = 2    -- ...by this many dwarves, with it near...
INTERRUPT_MIN_NEAR = 3       -- ...at least this many of them: the unit blocks the dwarves
local NEEDS_JOBS = {Drink = 'drink', Eat = 'eat', Sleep = 'sleep'}

-- "Name, Profession cancels Drink: Interrupted by a human spearman." -> name, job, reason
function parse_cancel(text)
    if type(text) ~= 'string' then return nil end
    local who, job, why = text:match('^(.-) cancels ([^:]+): (.-)%.?%s*$')
    if not who or who == '' then return nil end
    return who, job, why
end

-- "Interrupted by a human spearman" -> "human spearman" (nil for other reasons)
function interrupter_of(why)
    if type(why) ~= 'string' then return nil end
    local who = why:match('^Interrupted by (.+)$')
    if not who then return nil end
    who = who:lower():gsub('^an? ', ''):gsub('^the ', ''):gsub('%s+$', '')
    if who == '' or who == 'combat' then return nil end
    return who
end

-- the phrases DF may call a unit by in "Interrupted by a ...": its profession,
-- its race and profession, its race (an animal), each lower case
function unit_phrases(race, prof)
    local out = {}
    race = type(race) == 'string' and race:lower() or nil
    prof = type(prof) == 'string' and prof:lower() or nil
    if prof and prof ~= '' then table.insert(out, prof) end
    if race and race ~= '' and prof and prof ~= '' then table.insert(out, race .. ' ' .. prof) end
    if race and race ~= '' then table.insert(out, race) end
    return out
end

-- rows {text, tick, x, y, z, n}: the cancellations within the window, by who
-- interrupted ({n, drink, eat, sleep, other, dwarves, spots}) and the reasons
-- for cancelled Drink and Eat jobs ({Drink = {reason = n}})
function tally_cancels(rows, now, window)
    local out = {by_who = {}, reasons = {Drink = {}, Eat = {}}, n = 0}
    for _, r in ipairs(rows or {}) do
        if type(r) == 'table' and (not now or not r.tick or now - r.tick <= window) then
            local name, job, why = parse_cancel(r.text)
            if name then
                local k = tonumber(r.n) or 1
                out.n = out.n + k
                if out.reasons[job] then
                    local short = tostring(why):sub(1, 60)
                    out.reasons[job][short] = (out.reasons[job][short] or 0) + k
                end
                local who = interrupter_of(why)
                if who then
                    local w = out.by_who[who]
                    if not w then
                        w = {n = 0, drink = 0, eat = 0, sleep = 0, other = 0, dwarves = 0, names = {}, spots = {}}
                        out.by_who[who] = w
                    end
                    w.n = w.n + k
                    local kind = NEEDS_JOBS[job] or 'other'
                    w[kind] = w[kind] + k
                    if not w.names[name] then w.names[name] = true; w.dwarves = w.dwarves + 1 end
                    if r.x and r.y and r.z and #w.spots < 200 then
                        table.insert(w.spots, {x = r.x, y = r.y, z = r.z, n = k, needs = NEEDS_JOBS[job] ~= nil})
                    end
                end
            end
        end
    end
    return out
end

-- the units that keep the dwarves from their needs: cands {id, phrases, x, y, z};
-- a phrase's units are ranked by the cancellations near them (several human
-- spearmen visit: only the one by the dwarves counts; with no places in the
-- reports, the one with most citizens `cit` {x, y, z} about it). Returns {id = row}
function blocking_units(tally, cands, cfg, cit)
    cfg = cfg or {}
    local near_r = cfg.near or INTERRUPT_NEAR
    local min_n, min_d = cfg.min or INTERRUPT_MIN, cfg.min_dwarves or INTERRUPT_MIN_DWARVES
    local min_near = cfg.min_near or INTERRUPT_MIN_NEAR
    local out = {}
    for who, w in pairs(tally and tally.by_who or {}) do
        local needs = (w.drink or 0) + (w.eat or 0) + (w.sleep or 0)
        if needs >= min_n and (w.dwarves or 0) >= min_d then
            local matched = {}
            for _, c in ipairs(cands or {}) do
                for _, p in ipairs(c.phrases or {}) do
                    if p == who then table.insert(matched, c) break end
                end
            end
            local function close(a, b)
                return math.max(math.abs(a.x - b.x), math.abs(a.y - b.y)) + 3 * math.abs(a.z - b.z) <= near_r
            end
            local placed = 0
            for _, sp in ipairs(w.spots or {}) do if sp.needs then placed = placed + 1 end end
            local best, best_n = nil, -1
            for _, c in ipairs(matched) do
                local near = 0
                if placed > 0 then
                    for _, sp in ipairs(w.spots) do
                        if sp.needs and close(sp, c) then near = near + (sp.n or 1) end
                    end
                else
                    -- no places in the reports: the citizens about it now
                    for _, p in ipairs(cit or {}) do if close(p, c) then near = near + 1 end end
                end
                if placed > 0 and near >= min_near then
                    out[c.id] = {id = c.id, who = who, near = near, cancels = needs, drink = w.drink, eat = w.eat,
                                 sleep = w.sleep, dwarves = w.dwarves}
                elseif placed == 0 and near > best_n then
                    best, best_n = c, near
                end
            end
            -- no places: one alone by that name, else the one with the most dwarves about it
            if best and (#matched == 1 or best_n >= min_near) then
                out[best.id] = {id = best.id, who = who, near = best_n, cancels = needs, drink = w.drink,
                                eat = w.eat, sleep = w.sleep, dwarves = w.dwarves}
            end
        end
    end
    return out
end

-- the game's job cancellations of the last window (world.status.reports, newest first)
local function read_cancels(now, window)
    local rows = {}
    pcall(function()
        local reps = df.global.world.status.reports
        local seen, tail = 0, nil
        for i = #reps - 1, 0, -1 do
            seen = seen + 1
            if seen > INTERRUPT_MAX_REPORTS then break end
            local r = reps[i]
            local okt, t = pcall(function() return U.abs_tick(r.year, r.time) end)
            if okt and t and now - t > window then break end
            local text = tostring(r.text)
            -- a long line goes on in the next report(s) (flags.continuation): read backwards, put together
            local cont = false
            pcall(function() cont = r.flags.continuation and true or false end)
            if cont then
                tail = tail and (text .. ' ' .. tail) or text
                text = nil
            elseif tail then
                text, tail = text .. ' ' .. tail, nil
            end
            if text and text:find(' cancels ', 1, true) then
                local row = {text = text, tick = okt and t or nil, n = 1}
                pcall(function() row.n = 1 + math.max(0, math.tointeger(r.repeat_count) or 0) end)
                pcall(function()
                    if r.pos.x >= 0 then row.x, row.y, row.z = r.pos.x, r.pos.y, r.pos.z end
                end)
                table.insert(rows, row)
            end
        end
    end)
    return rows
end

local function race_name(u)
    local ok, n = pcall(function() return df.global.world.raws.creatures.all[u.race].name[0] end)
    return ok and n or nil
end

local function prof_name(u)
    local ok, n = pcall(dfhack.units.getProfessionName, u)
    return ok and n or nil
end

INTERRUPT_MEMO = nil         -- {tick, blocking = {id = row}, tally}

-- the blocking units now ({id = row}) and the tally, read once a game tick
function interrupt_read()
    local now = now_tick()
    local m = INTERRUPT_MEMO
    if m and m.tick == now then return m end
    local tally = tally_cancels(read_cancels(now, INTERRUPT_WINDOW), now, INTERRUPT_WINDOW)
    local cands, cit = {}, {}
    if next(tally.by_who) then
        for _, u in ipairs(report_citizens(true)) do
            table.insert(cit, {x = u.pos.x, y = u.pos.y, z = u.pos.z})
        end
        for _, u in ipairs(report_units()) do
            if dfhack.units.isActive(u) and not dfhack.units.isDead(u) and not is(dfhack.units.isCitizen, u) then
                table.insert(cands, {id = u.id, x = u.pos.x, y = u.pos.y, z = u.pos.z,
                                     phrases = unit_phrases(race_name(u), prof_name(u))})
            end
        end
    end
    m = {tick = now, tally = tally, blocking = blocking_units(tally, cands, nil, cit)}
    INTERRUPT_MEMO = m
    return m
end

-- (item1) a unit DF's own reports show keeping the dwarves from drink, food or sleep
function interrupting(u)
    local ok, m = pcall(interrupt_read)
    return ok and m and u and m.blocking[u.id] ~= nil or false
end

-- the report's part: who blocks the dwarves (each unit with what DF says of
-- it), the top interrupters, and why Drink and Eat jobs were cancelled
function interrupters_report(cit, groups, txt)
    local m = interrupt_read()
    local out = {window_days = INTERRUPT_WINDOW // DAY, cancels = m.tally.n, list = {}, by_who = {}, reasons = {}}
    for who, w in pairs(m.tally.by_who) do
        table.insert(out.by_who, {who = who, n = w.n, drink = w.drink, eat = w.eat, sleep = w.sleep,
                                  dwarves = w.dwarves})
    end
    table.sort(out.by_who, function(a, b) return a.n > b.n end)
    while #out.by_who > 5 do table.remove(out.by_who) end
    for job, rs in pairs(m.tally.reasons) do
        local l = {}
        for why, n in pairs(rs) do table.insert(l, {why = why, n = n}) end
        table.sort(l, function(a, b) return a.n > b.n end)
        while #l > 3 do table.remove(l) end
        if #l > 0 then out.reasons[job:lower()] = l end
    end
    local mil
    pcall(function() mil = reqscript('ai-military') end)
    for id, row in pairs(m.blocking) do
        local u = df.unit.find(id)
        if u and not dfhack.units.isDead(u) and #out.list < 10 then
            local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            local r = {id = id, name = name_of(u, txt), who = row.who, cancels = row.cancels, drink = row.drink,
                       eat = row.eat, sleep = row.sleep, dwarves = row.dwarves, near = row.near, pos = pos,
                       inside = not outside_at(pos.x, pos.y, pos.z), can_reach_dwarves = reaches(pos, groups),
                       distance = dist_to(pos, cit),
                       caged = (u.flags1.caged or u.flags1.chained) or nil,
                       visitor = is(dfhack.units.isVisitor, u) or nil,
                       merchant = is(dfhack.units.isMerchant, u) or nil,
                       diplomat = is(dfhack.units.isDiplomat, u) or nil,
                       invader = is(dfhack.units.isInvader, u) or nil,
                       danger = is(dfhack.units.isDanger, u) or nil}
            if mil and mil.kill_target_ok then
                local okk, yes = pcall(mil.kill_target_ok, u)
                r.kill_ok = okk and yes or false
            end
            table.insert(out.list, r)
        end
    end
    table.sort(out.list, function(a, b) return (a.cancels or 0) > (b.cancels or 0) end)
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
    -- (fix41) the evil weather is its own section (weather_section), read in the pulse too
    part('were', were_report, d, t, txt)
    part('surface', surface_report, cit, txt)
    part('rescue', rescue_report)
    part('openings', openings_report, d, t, txt)          -- (0.105.26)
    part('cavern_citizens', cavern_citizens, txt)         -- (0.105.26)
    part('interrupters', interrupters_report, cit, groups, txt)   -- (item1) who keeps them from drink
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
-- (0.105.41) A tile the AI painted High or Low (lua/ai-traffic.lua) is
-- restricted as a Normal one is, and lifted back to what the AI painted.
local function traffic_painted(x, y, z, memo)
    local ok, v = pcall(function() return reqscript('ai-traffic').ai_value(x, y, z, memo) end)
    return ok and v or nil
end

function fire_guard(radius, max_jobs, lift, dry_run)
    local d = load_state()
    local memo = {}
    if lift then
        local n = 0
        for _, k in ipairs(d.fire.tiles) do
            local x, y, z = unkey(k)
            pcall(function()
                local des = dfhack.maps.getTileFlags(x, y, z)
                if des and des.traffic == df.tile_traffic.Restricted then
                    if not dry_run then des.traffic = traffic_painted(x, y, z, memo) or df.tile_traffic.Normal end
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
                if des and (des.traffic == df.tile_traffic.Normal
                            or (des.traffic ~= df.tile_traffic.Restricted
                                and des.traffic == traffic_painted(x, y, z, memo))) then
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
        for _, c in ipairs(report_citizens(true)) do
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

-- (0.105.40b fix) The doors ai-insane holds locked for the insane: {id = true}.
local function insane_held()
    local ok, ids = pcall(function() return reqscript('ai-insane').held_ids() end)
    return ok and type(ids) == 'table' and ids or {}
end

-- (0.105.40b fix 2) The doors the threats rules have taken over and will
-- open themselves: the werebeast cells' locked doors (c.doors) and the
-- cavern seal's (locked, or shut by their lever). ai-insane drops its lock
-- on one of these without opening it; a door the rules only could need
-- (claimed_doors) it frees as usual, or it would stay locked for good.
function adopted_doors()
    local d = load_state()
    local out = {}
    for _, c in pairs(d.cells) do
        if type(c) == 'table' then
            for _, id in ipairs(type(c.doors) == 'table' and c.doors or {}) do out[tonumber(id) or id] = true end
        end
    end
    for id in pairs(seal_holds(d).ids) do out[id] = true end
    return out
end

-- (0.105.40b fix) The doors and hatches the threats rules hold or could
-- need: the werebeast cells' (those they locked, and every door of a cell's
-- room), the cavern seal's (locked, or shut by their lever), the openings on
-- record (the ways down to the caverns the seal locks), and the entrances'
-- the gate watcher holds shut now. ai-insane never locks one of these (only
-- 'don't lock'; what it drops unopened is adopted_doors).
function claimed_doors()
    local d = load_state()
    local out = {}
    for _, c in pairs(d.cells) do
        if type(c) == 'table' then
            for _, id in ipairs(type(c.doors) == 'table' and c.doors or {}) do out[tonumber(id) or id] = true end
            pcall(function()
                local z = c.zone and zone_by_id(c.zone)
                if z then for id in pairs(zone_doors(z)) do out[id] = true end end
            end)
        end
    end
    for id in pairs(seal_holds(d).ids) do out[id] = true end
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.x and o.y and o.z then
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(o.x, o.y, o.z))
                if b then out[b.id] = true end
            end)
        end
    end
    for id in pairs(watcher_held()) do out[id] = true end
    return out
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
            -- (13c) a door left locked, or a burrow not cleared, is said (it was
            -- silently dropped with the cell's record)
            local function failed(what, err)
                out.errors = out.errors or {}
                table.insert(out.errors, what .. ': ' .. tostring(err):sub(1, 100))
            end
            for _, bid in ipairs(c.doors or {}) do
                local okd, err = pcall(function()
                    local b = df.building.find(bid)
                    if b then b.door_flags.forbidden = false end
                end)
                if not okd then failed('door ' .. tostring(bid), err) end
            end
            local okb, err = pcall(function()
                local b = burrow_named(CELL_PREFIX .. uid, false)
                if b then
                    if u then dfhack.burrows.setAssignedUnit(b, u, false) end
                    dfhack.burrows.clearTiles(b)
                end
            end)
            if not okb then failed('cell burrow ' .. tostring(uid), err) end
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
                        local insane = insane_held()
                        for id, b in pairs(zone_doors(z)) do
                            local okf, f = pcall(function() return b.door_flags.forbidden end)
                            if okf and not f then
                                if not dry_run then
                                    b.door_flags.forbidden = true
                                    table.insert(c.doors, id)
                                end
                            elseif okf and insane[id] and not dry_run then
                                -- (0.105.40b fix) locked by ai-insane already: the cell's now
                                -- (ai-insane drops it without opening it)
                                table.insert(c.doors, id)
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
        for _, u in ipairs(report_citizens(true)) do
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
-- (0.105.26) openings: every opening on record too (state.openings), but
-- never a cavern well's shaft hatch (its lever and the shaft watcher work
-- it, and the bucket needs it open whenever no great beast is about); a
-- door or hatch on a lever is shut by that lever (a lock does nothing to
-- it) when the lever works nothing else, and opened by it again after. The
-- doors and hatches found are put on record as openings. Said in the game.
local function announce(text, color)
    pcall(function() dfhack.gui.showAnnouncement('AI Overseer: ' .. text, color or COLOR_YELLOW, true) end)
end

-- a lever that works this building and nothing else, or nil
local function own_lever(bid)
    local ok, lid = pcall(function()
        local G = reqscript('ai-gates')
        local links = G.lever_links()
        for _, l in ipairs(links[bid] or {}) do
            local targets = G.lever_targets(links, l)
            if #targets == 1 and targets[1] == bid then return l end
        end
    end)
    return ok and lid or nil
end

function seal_cavern(layer, tiles, open, dry_run, z1, z2, openings)
    local d = load_state()
    local t = now_tick()
    local rec = type(d.sealed[layer]) == 'table' and d.sealed[layer] or nil
    if open then
        if not rec then return {ok = false, rejected = true, nothing_to_do = true, error = 'the AI sealed nothing there'} end
        -- (0.105.26 seal fix) an entrance the gate watcher holds shut (an
        -- ordinary danger at it) is left shut: the watcher opens it later
        local watched = watcher_held()
        local n, kept = 0, 0
        for _, bid in ipairs(rec.ids or {}) do
            pcall(function()
                local b = df.building.find(bid)
                if b and watched[b.id] then
                    kept = kept + 1
                elseif b then
                    if not dry_run then b.door_flags.forbidden = false end
                    n = n + 1
                end
            end)
        end
        for sid, lever in pairs(type(rec.pulled) == 'table' and rec.pulled or {}) do
            pcall(function()
                local b = df.building.find(tonumber(sid))
                if b and watched[b.id] then
                    kept = kept + 1
                elseif b and b.door_flags.closed then
                    if not dry_run then reqscript('ai-gates').pull_instant(lever) end
                    n = n + 1
                end
            end)
        end
        if not dry_run then
            d.sealed[layer] = nil
            save_state(d)
            announce(('the ways into the caverns opened again (%s): no great beast left'):format(tostring(layer)),
                     COLOR_GREEN)
        end
        return {ok = true, unlocked = n, layer = layer, watcher_kept = kept > 0 and kept or nil, dry_run = dry_run or nil}
    end
    local inside = citizen_in_cavern(z1, z2)
    if inside then
        return {ok = false, rejected = true, waiting = true,
                error = name_of(inside) .. ' is down in ' .. tostring(layer) .. ': not sealed while a dwarf is on the far side'}
    end
    local skip, list, given = {}, {}, {}
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.kind == 'well' and o.x then skip[okey(o.x, o.y, o.z)] = true end
    end
    for _, p in ipairs(tiles or {}) do
        local x, y, z = tonumber(p.x), tonumber(p.y), tonumber(p.z)
        if x and y and z then
            table.insert(list, {x = x, y = y, z = z})
            given[okey(x, y, z)] = true
        end
    end
    if openings then
        for _, o in pairs(d.openings) do
            if type(o) == 'table' and o.x and o.kind ~= 'well' then table.insert(list, {x = o.x, y = o.y, z = o.z}) end
        end
    end
    local found, at = {}, {}
    for _, p in ipairs(list) do
        if not skip[okey(p.x, p.y, p.z)] then
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(p.x, p.y, p.z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    found[b.id] = b
                    at[b.id] = p
                end
            end)
        end
    end
    rec = rec or {ids = {}, tick = t}
    rec.pulled = type(rec.pulled) == 'table' and rec.pulled or {}
    local have, n, already, adopted, pull_failed = {}, 0, 0, 0, 0
    for _, id in ipairs(rec.ids) do have[id] = true end
    -- (0.105.26 seal fix) one the gate watcher already holds shut goes on
    -- the record too, so the watcher doesn't open it while the beast is about
    local watched = watcher_held()
    local insane = insane_held()      -- (0.105.40b fix) ai-insane's locks: the seal's now
    for id, b in pairs(found) do
        local lever = own_lever(id)
        if lever then
            local okc, c = pcall(function() return b.door_flags.closed end)
            if okc and not c then
                -- (0.105.33 review) counted only when the pull worked (a failed
                -- pull said "locked" and the opening still read unsealed)
                if not dry_run then
                    local okp, pulled = pcall(function() return reqscript('ai-gates').pull_instant(lever) end)
                    if okp and pulled then
                        rec.pulled[tostring(id)] = lever
                        n = n + 1
                    else
                        pull_failed = pull_failed + 1
                    end
                else
                    n = n + 1
                end
            elseif okc then
                already = already + 1
                if watched[id] and rec.pulled[tostring(id)] == nil then
                    if not dry_run then rec.pulled[tostring(id)] = lever end
                    adopted = adopted + 1
                end
            end
        else
            local okf, f = pcall(function() return b.door_flags.forbidden end)
            if okf and not f then
                if not dry_run then
                    b.door_flags.forbidden = true
                    if not have[id] then table.insert(rec.ids, id); have[id] = true end
                end
                n = n + 1
            elseif okf then
                already = already + 1
                if (watched[id] or insane[id]) and not have[id] then
                    if not dry_run then table.insert(rec.ids, id); have[id] = true end
                    adopted = adopted + 1
                end
            end
        end
        local p = at[id]
        if p and given[okey(p.x, p.y, p.z)] and not dry_run then
            note_opening(d, p.x, p.y, p.z, 'way_down', tostring(layer), t)
        end
    end
    if n == 0 and adopted > 0 then
        -- everything locked already, some by the gate watcher: on the seal's record now
        if not dry_run then
            d.sealed[layer] = rec
            save_state(d)
        end
        return {ok = true, locked = 0, adopted = adopted, layer = layer, dry_run = dry_run or nil}
    end
    if n == 0 then
        if not dry_run then save_state(d) end          -- (the openings found are kept)
        return {ok = false, rejected = true, nothing_to_do = already > 0 and pull_failed == 0,
                pull_failed = pull_failed > 0 and pull_failed or nil,
                error = pull_failed > 0 and (pull_failed .. ' lever(s) on the way down would not pull: the doors stay open')
                    or already > 0 and 'every door and hatch on the way down is locked already'
                    or 'no door or hatch on the way down to lock'}
    end
    if not dry_run then
        d.sealed[layer] = rec
        save_state(d)
        announce(('%d way(s) into the caverns locked against a great beast (%s)'):format(n, tostring(layer)))
    end
    return {ok = true, locked = n, adopted = adopted > 0 and adopted or nil, layer = layer, dry_run = dry_run or nil,
            pull_failed = pull_failed > 0 and pull_failed or nil}
end

-- (0.105.40b) A creature that breathes, spits or hurls fire (a dragon, a fire
-- imp, a generated beast with a fire breath), or burns to the touch: no melee
-- squad goes at it (the fire takes a squad in its armour before it lands a
-- blow; brain/planner_firebreath.py). Read from its caste's raws: each natural
-- ability (caste.body_info.interactions, CAN_DO_INTERACTION) whose CDI:FLOW is
-- DRAGONFIRE, FIREJET or FIREBALL (interaction.material_breath), or whose
-- interaction's material target emits one of those (a generated beast's);
-- the caste flag IMMOLATE. One answer per race and caste, kept for the
-- session (raws don't change while a world is loaded).
-- Returns 'breath' / 'jet' / 'fireball' / 'burns', or false.
FIRE_BREATH_CACHE = FIRE_BREATH_CACHE or {}
local FIRE_FLOW_HOW = {DRAGONFIRE = 'breath', FIREJET = 'jet', FIREBALL = 'fireball'}

-- (fix41) the cache belongs to one world: another save loaded in the same
-- DFHack session has other races under the same numbers (generated beasts)
function fire_breath_of(race, caste)
    local okw, world = pcall(function() return df.global.world.cur_savegame.save_dir end)
    world = tostring(okw and world or '?')
    if FIRE_BREATH_WORLD ~= world then
        FIRE_BREATH_CACHE, FIRE_BREATH_WORLD = {}, world
    end
    local key = tostring(race) .. ':' .. tostring(caste)
    local v = FIRE_BREATH_CACHE[key]
    if v ~= nil then return v end
    v = false
    local fire = {}
    pcall(function()
        for name, how in pairs(FIRE_FLOW_HOW) do
            local e = df.breath_attack_type[name]
            if e ~= nil then fire[e] = how end
        end
    end)
    local okc, c = pcall(function() return df.creature_raw.find(race).caste[caste] end)
    if okc and c then
        pcall(function()
            for _, a in ipairs(c.body_info.interactions) do
                local info = a.interaction
                local how = fire[info.material_breath]
                if not how then
                    pcall(function()
                        local it = df.interaction.find(info.type_id)
                        for _, t in ipairs(it and it.targets or {}) do
                            local okb, b = pcall(function() return t.breath_attack_type end)
                            if okb and b ~= nil and fire[b] then how = fire[b]; break end
                        end
                    end)
                end
                if how then v = how; return end
            end
        end)
        if not v then
            local oki, imm = pcall(function() return c.flags.IMMOLATE end)
            if oki and imm then v = 'burns' end
        end
    end
    FIRE_BREATH_CACHE[key] = v
    return v
end

-- (0.105.40b) The others_on_map report's threats marked: fire_breather = true
-- and fire_how for each one that breathes fire (nothing added to the others,
-- so a report without one is as before). Returns how many were marked.
function mark_fire_breathers(o)
    local n = 0
    for _, t in ipairs(type(o) == 'table' and type(o.threats) == 'table' and o.threats or {}) do
        local u = type(t) == 'table' and t.id ~= nil and df.unit.find(t.id) or nil
        if u then
            local okf, how = pcall(fire_breath_of, u.race, u.caste)
            if okf and how then
                t.fire_breather, t.fire_how = true, how
                n = n + 1
            end
        end
    end
    return n
end
