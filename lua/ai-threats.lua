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
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

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

local function now_tick() return U.abs_tick() end             -- (r6) not protected: an error goes to the caller

local function name_of(u, txt) return U.name_of(u, txt) end   -- (r6) ai-util's

-- --- (r1 g7) visitors turned killers -------------------------------------------
-- B (16 Nov): lone heroes came in as guests for the fort's artifacts. Len
-- Karaura killed 19 citizens in 65 seconds and Itvid 5; F lost its last 4 to
-- two visiting humans. DF counted them neither a danger nor an invader for a
-- while, so no row, no kill order (kill_target_ok said no). A non-citizen who
-- kills one of the fort's own (not a berserk one), or who is spotted sneaking
-- after an artifact (DF's AMBUSH_HERO report), is marked here (kept in the
-- save, TURNED_DAYS): others_on_map lists them as a threat and the squads may
-- be sent at them (ai-military kill_target_ok).
TURNED_DAYS = 28
TURNED_NEAR = 3          -- tiles from the report's place a spotted hero is looked for
TURNED = TURNED or nil   -- unit id (string) -> tick marked; read from the save on first use
TURNED_SITE = TURNED_SITE or nil   -- the site TURNED was read for (another fort loaded: read afresh)

local function turned_set()
    local oks, site = pcall(function() return df.global.plotinfo.site_id end)
    site = oks and site or nil
    if type(TURNED) ~= 'table' or TURNED_SITE ~= site then
        TURNED_SITE = site
        local set = {}
        pcall(function()
            local d = U.site_get(STATE_KEY, {})
            if type(d.turned) == 'table' then
                for k, v in pairs(d.turned) do
                    if type(v) == 'number' then set[tostring(k)] = v end
                end
            end
        end)
        TURNED = set
    end
    return TURNED
end

-- Mark unit `id` a turned visitor at tick t; the old marks dropped; saved.
function mark_turned(id, t)
    if type(id) ~= 'number' or id < 0 then return false end
    local set = turned_set()
    t = t or now_tick()
    set[tostring(id)] = t
    for k, v in pairs(set) do
        if type(v) ~= 'number' or t - v > TURNED_DAYS * DAY then set[k] = nil end
    end
    pcall(function()
        local d = U.site_get(STATE_KEY, {})
        d.turned = set
        U.site_put(STATE_KEY, d)
    end)
    return true
end

-- Is u a marked visitor (alive, not a citizen, marked within TURNED_DAYS)?
function is_turned(u)
    if not u or type(u.id) ~= 'number' then return false end
    local t = turned_set()[tostring(u.id)]
    if type(t) ~= 'number' then return false end
    local okn, now = pcall(now_tick)
    if okn and type(now) == 'number' and now - t > TURNED_DAYS * DAY then return false end
    local okc, cit = pcall(dfhack.units.isCitizen, u)
    if okc and cit then return false end
    local okd, dead = pcall(dfhack.units.isDead, u)
    return not (okd and dead)
end

-- A death event (ai-bridge-report death_details): its killer marked when an
-- outsider (no citizen, ghost, beast or animal), alive, killed one of the
-- fort's own who wasn't berserk. Returns true when marked.
function note_death(ev)
    if type(ev) ~= 'table' or ev.again or ev.animal or not ev.own_civ then return false end
    if ev.killer_kind ~= 'outsider' or ev.killer_dead or type(ev.killer_id) ~= 'number' then return false end
    if tostring(ev.mood or ''):lower() == 'berserk' then return false end
    return mark_turned(ev.killer_id)
end

-- The name a readable name starts with ('Len Karaura "Heatdied", Human
-- Axeman' -> 'Len Karaura'), for matching the report's text.
function first_name_of(readable)
    local s = tostring(readable or '')
    s = s:match('^([^",]+)') or s
    return (s:gsub('^%s+', ''):gsub('%s+$', ''))
end

-- A report event (ai-reports): "The Human Axeman Len Karaura was spotted
-- sneaking around! "You will not stand between me and Nettlewalk!"" marks
-- the unit it names (or the one non-citizen person by the report's place).
-- Returns the unit id marked, or nil.
function note_report(ev, txt)
    if type(ev) ~= 'table' or ev.kind ~= 'report' then return nil end
    local text = tostring(ev.text or '')
    if ev.type ~= 'AMBUSH_HERO' and not text:find('spotted sneaking around', 1, true) then return nil end
    local named, near, n_near = nil, nil, 0
    for _, u in ipairs(df.global.world.units.active) do
        local ok, cand = pcall(function()
            return not dfhack.units.isDead(u) and not dfhack.units.isCitizen(u) and not dfhack.units.isAnimal(u)
        end)
        if ok and cand then
            -- by name only for a named unit (an unnamed one reads as its profession)
            local okh, hn = pcall(function() return u.name.has_name end)
            local nm = (okh and hn == false) and '' or first_name_of(name_of(u, txt))
            if #nm >= 3 and nm:find(' ', 1, true) and text:find(nm, 1, true) then named = u; break end
            if type(ev.x) == 'number' and u.pos.z == ev.z and math.abs(u.pos.x - ev.x) <= TURNED_NEAR
                    and math.abs(u.pos.y - ev.y) <= TURNED_NEAR then
                near, n_near = u, n_near + 1
            end
        end
    end
    local u = named or (n_near == 1 and near) or nil
    if u and mark_turned(u.id) then return u.id end
    return nil
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

-- (0.105.51) A unit's thief kind ('thief', 'snatcher' or nil), by its
-- profession and path goal (thief_kind); for the others_on_map threat rows,
-- which the pulse carries (the threats section is in the full report only)
function unit_thief_kind(u)
    local prof, goal
    pcall(function() prof = df.profession[u.profession] end)
    pcall(function() goal = df.unit_path_goal[u.path.goal] end)
    return thief_kind(prof, goal)
end

-- Count the points {x, y, z} within r tiles of p on its level.
function count_near(p, points, r)
    local n = 0
    for _, q in ipairs(points) do
        if q.z == p.z and math.abs(q.x - p.x) <= r and math.abs(q.y - p.y) <= r then n = n + 1 end
    end
    return n
end

CROWD_RADIUS = 5
-- (0.105.51) The crowd round a thief: the people (no animal, no danger,
-- not the thief) within CROWD_RADIUS tiles on its level, and the type of
-- the location (tavern, temple, library, guildhall) whose zone it stands
-- in. E (15 Nov): a thief come as a guest was attacked in the tavern three
-- times and the fight spread to ~26 bards, dancers and poets.
-- Returns crowd (a number), location type (a string or nil).
function crowd_of(u, units)
    local pts = {}
    for _, o in ipairs(units or {}) do
        local ok, yes = pcall(function()
            return o.id ~= u.id and dfhack.units.isActive(o) and not dfhack.units.isDead(o)
                and not dfhack.units.isAnimal(o) and not dfhack.units.isDanger(o)
                and o.pos.z == u.pos.z
        end)
        if ok and yes then table.insert(pts, {x = o.pos.x, y = o.pos.y, z = o.pos.z}) end
    end
    local n = count_near({x = u.pos.x, y = u.pos.y, z = u.pos.z}, pts, CROWD_RADIUS)
    local loc
    pcall(function()
        local site = dfhack.world.getCurrentSite()
        local zs = dfhack.buildings.findCivzonesAt(xyz2pos(u.pos.x, u.pos.y, u.pos.z)) or {}
        for _, zn in ipairs(zs) do
            local lid = zn.location_id
            if site and lid and lid ~= -1 then
                for _, b in ipairs(site.buildings) do
                    if b.id == lid then
                        loc = df.abstract_building_type[b:getType()]
                        return
                    end
                end
            end
        end
    end)
    return n, loc
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

-- (0.105.46, I6) only the flows of the types wanted (U.flows_where: one walk a report)
local function flows_typed(set)
    if U.flows_where then
        local ok, l = pcall(U.flows_where, function(t) return set[df.flow_type[t]] end)
        if ok and l then return l end
    end
    return df.global.flows
end

local function fire_points()
    local pts = {}
    pcall(function()
        for _, f in ipairs(flows_typed(FIRE_FLOWS)) do
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
        -- (0.105.48) the vector is ZONE_POND in DF 53.17 (was ZONE_PIT_POND, none such)
        local other = df.global.world.buildings.other
        local ok, v = pcall(function() return other.ZONE_POND end)
        if not ok or not v then v = other.ZONE_PIT_POND end
        for _, z in ipairs(v) do
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
    -- (r1g9) the world by its name (ai-util world_name), not the save folder
    local okk, key = pcall(function()
        local okn, w = pcall(function() return U.world_name() end)
        if not okn or type(w) ~= 'string' then w = df.global.world.cur_savegame.save_dir end
        return tostring(w) .. '#' .. #df.global.world.entities.all
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
                -- (0.105.51) the crowd round them: no squad sent into a tavern full of guests
                pcall(function() row.crowd, row.location = crowd_of(u, report_units()) end)
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
        for _, f in ipairs(flows_typed(CLOUD_FLOWS)) do
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

-- (0.105.76) A citizen bitten by a werebeast carries DF's curse as a syndrome
-- of class WERECURSE (data/vanilla interaction_werebeast.txt: [SYN_CLASS:
-- WERECURSE]) from the bite on, weeks before the first change; DFHack's
-- isNightCreature doesn't say so meanwhile. Live 22 Nov, E: the were list
-- stayed empty while bitten citizens turned at four full moons (20 dead in an
-- hour), each found only once changed, too late for the moon cells.
function were_cursed(u)
    local ok, yes = pcall(function()
        for _, a in ipairs(u.syndromes.active) do
            local sd = df.syndrome.find(a.type)
            if sd then
                for _, c in ipairs(sd.syn_class) do
                    local v = c
                    if type(c) ~= 'string' then pcall(function() v = c.value end) end
                    if tostring(v) == 'WERECURSE' then return true end
                end
            end
        end
        return false
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
            local cursed = own and not now_changed and were_cursed(u)
            if own and (now_changed or cursed
                        or (is(dfhack.units.isNightCreature, u) and not is(dfhack.units.isBloodsucker, u))) then
                local row = {id = u.id, name = name_of(u, txt), changed = now_changed or nil,
                             by_syndrome = cursed or nil}
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

-- (r8) this file's locals the later parts use (each takes back the ones it
-- uses as locals of its own): all functions and fixed values, set once here
PART_LOCALS = {U = U, report_citizens = report_citizens, report_units = report_units, DAY = DAY, now_tick = now_tick, name_of = name_of, save_state = save_state, unkey = unkey, is = is, outside_at = outside_at, citizens = citizens, dist_to = dist_to, reaches = reaches, fire_points = fire_points, each_job = each_job, fire_report = fire_report, prisoners_report = prisoners_report, thieves_report = thieves_report, undead_report = undead_report, changed = changed, were_report = were_report, surface_report = surface_report, rescue_report = rescue_report}

---------------------------------------------------------------------------
-- (r8) The rest of the threats lives in parts beside this file
-- (ai-threats-<part>.lua): survey (the cavern openings and their seal's
-- state, who keeps the dwarves from drink and food, survey() itself) and
-- actions (fire_guard, the prisoners' room, the moon cell, seal_cavern, the
-- fire breathers). Each runs in this module's own environment, so its names
-- stay reqscript('ai-threats').name for the bridge and the other modules, and
-- a test's swap (T.survey = ...) reaches every part. They load in this
-- order. DFHack reloads a module when its own file changes: a change to a
-- part alone is picked up once ai-threats.lua is touched too, or the game
-- restarts.
---------------------------------------------------------------------------

PARTS = {'survey', 'actions'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-threats'] = '0.105.76'}   -- (0.105.26) bumped with BRIDGE_VERSION

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
    local name = 'ai-threats-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-threats: ' .. name .. '.lua is missing (it goes beside ai-threats.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
