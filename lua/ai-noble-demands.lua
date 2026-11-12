-- (0.105.41, item 1) What the nobles demand of their rooms, and how near
-- their rooms come to it: the monarch (a fort the monarch lives in is the
-- capital), the land holders (baron, count, duke) and every other office.
--
-- DF's position raws (df-structures entity_position: required_office,
-- required_bedroom, required_dining, required_tomb; required_boxes,
-- required_cabinets, required_racks, required_stands) give each office the
-- VALUE its rooms must reach; ai-nobles.lua already gives a noble a free
-- room of each kind (give_room). This module reads, for each noble, the
-- value each room must have and the value it has, and raises a room that
-- falls short: a statue put in (ai-builder place_in_zone, as the petition
-- halls are lifted to their tier since 0.90), and in a room the AI dug
-- itself, its natural rock smoothed and then engraved (polish_room). A
-- room the player dug is never smoothed or engraved (statues only, as in
-- the halls).
--
-- A room's value is worked out here (DFHack has no call for DF's own room
-- value): the furniture's items (dfhack.items.getValue) and the engravings
-- on the room's floor and the walls round it. It is an estimate: DF's own
-- figure may differ (needs an in-game look against the room's screen).
--@module = true

local U = reqscript('ai-util')

KINDS = {'office', 'bedroom', 'dining', 'tomb'}
ZONE_OF = {office = 'Office', bedroom = 'Bedroom', dining = 'DiningHall', tomb = 'Tomb'}
FIELD = {office = 'required_office', bedroom = 'required_bedroom', dining = 'required_dining',
         tomb = 'required_tomb'}
STORAGE = {boxes = 'required_boxes', cabinets = 'required_cabinets', racks = 'required_racks',
           stands = 'required_stands'}
-- vanilla dwarves: LAND_HOLDER:1 baron, 2 count, 3 duke
LAND_TITLES = {'baron', 'count', 'duke'}
-- an engraving's worth, by quality (ordinary .. masterful): an estimate,
-- DF's item quality multipliers on a base of 10 (needs an in-game look)
ENGRAVING_BASE = 10
QUALITY_MULT = {[0] = 1, 2, 3, 4, 5, 10}
-- rock that can be smoothed and engraved
SMOOTHABLE = {STONE = true, MINERAL = true, LAVA_STONE = true}
ROOMS_MAX = 40            -- noble rooms read in one report (a guard; a fort has a handful)

local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end

-- A DF name in words.
local function readable(u, txt)
    local ok, s = pcall(dfhack.units.getReadableName, u)
    return (txt or tostring)(ok and s or ('unit ' .. tostring(u.id)))
end

-- --- pure ----------------------------------------------------------------------

-- The rooms an office asks for, in value: positions = {{required = {office
-- = n, ...}, storage = {boxes = n, ...}}, ...} -> {office = max, ...},
-- {boxes = max, ...} (a noble holding two offices needs the more of each).
function demands_of(positions)
    local need, store = {}, {}
    for _, p in ipairs(positions or {}) do
        for _, k in ipairs(KINDS) do
            local v = tonumber((p.required or {})[k]) or 0
            if v > 0 and v > (need[k] or 0) then need[k] = v end
        end
        for k in pairs(STORAGE) do
            local v = tonumber((p.storage or {})[k]) or 0
            if v > 0 and v > (store[k] or 0) then store[k] = v end
        end
    end
    return need, store
end

-- The highest title among a noble's positions: 'monarch', 'duke', 'count',
-- 'baron' or nil. positions: {{monarch = bool, land_holder = n}, ...}
function title_of(positions)
    local best
    for _, p in ipairs(positions or {}) do
        if p.monarch then return 'monarch' end
        local lh = tonumber(p.land_holder) or 0
        if lh > 0 and (not best or lh > best) then best = lh end
    end
    return best and (LAND_TITLES[math.min(best, #LAND_TITLES)]) or nil
end

-- An engraving's worth (an estimate).
function engraving_value(quality)
    return ENGRAVING_BASE * (QUALITY_MULT[tonumber(quality) or 0] or 1)
end

-- What polishing a room still wants: tiles = {{x, y, z, shape, material,
-- smoothed, smoothing, hidden, designated, building, warm}} (ai-builder
-- tile_info plus x, y, z; ring: round the zone, where only walls count),
-- engraved = {'x,y,z' = {q, floor}} -> smooth, engrave (lists of tiles),
-- pending (a count). Natural rock floors and walls only; a tile with a job
-- on it, hidden, warm or under a building is left. pending: the tiles
-- already designated to be smoothed or engraved, or with that job on them
-- (t.smoothing, t.polish_job): until they are done the room is not read as
-- having nothing left to polish.
function polish_split(tiles, engraved)
    local smooth, engrave, pending = {}, {}, 0
    for _, t in ipairs(tiles or {}) do
        local fits = (t.shape == 'WALL' or (t.shape == 'FLOOR' and not t.ring)) and SMOOTHABLE[t.material]
                and not t.hidden
        if fits and (t.smoothing or t.polish_job) then
            pending = pending + 1
        elseif fits and not t.designated and not t.warm
                and not (t.shape == 'FLOOR' and t.building) then
            if not t.smoothed then
                table.insert(smooth, t)
            elseif not (engraved or {})[t.x .. ',' .. t.y .. ',' .. t.z] then
                table.insert(engrave, t)
            end
        end
    end
    return smooth, engrave, pending
end

-- Is the box (x1..x2, y1..y2, z) inside one of the AI's own levels?
-- areas: {{x1, y1, x2, y2, z}, ...}
function inside_areas(box, areas)
    local cx, cy = (box.x1 + box.x2) // 2, (box.y1 + box.y2) // 2
    for _, a in ipairs(areas or {}) do
        if type(a) == 'table' and a.z == box.z and cx >= a.x1 and cx <= a.x2 and cy >= a.y1 and cy <= a.y2 then
            return true
        end
    end
    return false
end

-- --- the game (each swapped by the tests) -------------------------------------

-- ai-builder's tile_info plus where.
function read_tile(x, y, z)
    local ok, t = pcall(function() return reqscript('ai-builder').tile_info(x, y, z) end)
    if not ok or not t then return nil end
    t.x, t.y, t.z = x, y, z
    return t
end

-- Every level the AI has dug (ai-builder level_areas), or {}.
function ai_areas()
    local ok, a = pcall(function() return reqscript('ai-builder').level_areas() end)
    return ok and type(a) == 'table' and a or {}
end

-- The map's engravings (df-structures: world.engravings; guarded, the
-- vector's place may differ in 53.x: needs an in-game look).
function engravings_list()
    local ok, l = pcall(function() return df.global.world.engravings end)
    if ok and l then return l end
    ok, l = pcall(function() return df.global.world.event.engravings end)
    return ok and l or {}
end

-- The engravings on the given levels: {'x,y,z' = {q = quality, floor =
-- bool}}. One walk.
function engravings_on(levels)
    local out = {}
    if not next(levels) then return out end
    pcall(function()
        for _, e in ipairs(engravings_list()) do
            local p = e.pos
            if p and levels[p.z] then
                local floor = false
                pcall(function() floor = e.flags.floor == true end)
                out[p.x .. ',' .. p.y .. ',' .. p.z] = {q = tonumber(e.quality) or 0, floor = floor}
            end
        end
    end)
    return out
end

local function zone_has(z, x, y)
    local ok, yes = pcall(dfhack.buildings.containsTile, z, x, y)
    return not ok or yes
end

-- The zone's tiles and the ring round it: {{x, y, ring}, ...} (no tile
-- twice; ring: outside the zone, where only a wall counts).
function zone_tiles(z)
    local out, seen = {}, {}
    local function add(x, y, ring)
        local k = x .. ',' .. y
        if not seen[k] then seen[k] = true; table.insert(out, {x = x, y = y, ring = ring or nil}) end
    end
    for y = z.y1, z.y2 do
        for x = z.x1, z.x2 do
            if zone_has(z, x, y) then
                add(x, y)
                for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
                    local nx, ny = x + d[1], y + d[2]
                    if nx < z.x1 or nx > z.x2 or ny < z.y1 or ny > z.y2 or not zone_has(z, nx, ny) then add(nx, ny, true) end
                end
            end
        end
    end
    return out
end

-- The room's worth (furniture items and engravings), its statues (built or
-- not), and those of them not built yet (a construction site whose statue a
-- dwarf has still to bring: the report's free statues count that one until
-- the job is taken, so the brain waits for it rather than placing another).
function zone_worth(z, engraved)
    local value, statues, pending = 0, 0, 0
    pcall(function()
        for _, b in ipairs(z.contained_buildings) do
            pcall(function()
                if b:getType() == df.building_type.Statue then
                    statues = statues + 1
                    local okb, unbuilt = pcall(function() return b:getBuildStage() < b:getMaxBuildStage() end)
                    if okb and unbuilt then pending = pending + 1 end
                end
            end)
            pcall(function()
                for _, ci in ipairs(b.contained_items) do
                    value = value + math.max(0, dfhack.items.getValue(ci.item) or 0)
                end
            end)
        end
    end)
    for _, t in ipairs(zone_tiles(z)) do
        local e = engraved[t.x .. ',' .. t.y .. ',' .. z.z]
        -- inside: every engraving; round it: the walls' (not a corridor's floor)
        if e and not (t.ring and e.floor) then value = value + engraving_value(e.q) end
    end
    return math.floor(value), statues, pending
end

-- The smoothing and engraving jobs: {'x,y,z' = true} (ai-builder's job
-- tiles, one walk of the job list a tick, shared; swapped by the tests).
local POLISH_JOBS = {SmoothWall = true, SmoothFloor = true, DetailWall = true, DetailFloor = true}
function polish_jobs()
    local out = {}
    pcall(function()
        for k, j in pairs(reqscript('ai-builder').job_tiles()) do
            local ok, name = pcall(function() return df.job_type[j.job_type] end)
            if ok and POLISH_JOBS[name] then out[k] = true end
        end
    end)
    return out
end

-- What polishing the room still wants: smooth, engrave (tiles), pending (a count).
function zone_polish(z, engraved, jobs)
    jobs = jobs or polish_jobs()
    local tiles = {}
    for _, t in ipairs(zone_tiles(z)) do
        local ti = read_tile(t.x, t.y, z.z)
        if ti then
            ti.ring = t.ring
            if jobs[t.x .. ',' .. t.y .. ',' .. z.z] then ti.polish_job = true end
            table.insert(tiles, ti)
        end
    end
    return polish_split(tiles, engraved)
end

-- The zones of a kind a unit owns (the most valuable later).
local function owned(u, zone_type)
    local out = {}
    pcall(function()
        for _, z in ipairs(u.owned_buildings) do
            local ok, t = pcall(function() return df.civzone_type[z.type] end)
            if ok and t == zone_type then table.insert(out, z) end
        end
    end)
    return out
end

-- One noble position read: {code, name, entity_id, monarch, land_holder,
-- required = {office = n...}, storage = {boxes = n...}}
function position_info(np, txt)
    local pos = np.position
    local p = {code = pos.code, required = {}, storage = {}}
    pcall(function() p.name = (txt or tostring)(pos.name[0]) end)
    pcall(function() p.entity_id = np.entity.id end)
    for k, f in pairs(FIELD) do
        pcall(function() local v = pos[f]; if v and v > 0 then p.required[k] = v end end)
    end
    for k, f in pairs(STORAGE) do
        pcall(function() local v = pos[f]; if v and v > 0 then p.storage[k] = v end end)
    end
    pcall(function() local lh = pos.land_holder; if lh and lh > 0 then p.land_holder = lh end end)
    -- the monarch: the civilisation's law-maker (vanilla MONARCH)
    local civ = false
    pcall(function() civ = np.entity.type == df.historical_entity_type.Civilization end)
    local laws = false
    pcall(function() laws = pos.responsibilities[df.entity_position_responsibility.LAW_MAKING] == true end)
    if p.code == 'MONARCH' or (civ and laws and not p.land_holder) then p.monarch = true end
    return p
end

-- --- the report ----------------------------------------------------------------

-- {nobles = [{unit_id, name, title, positions = {codes}, monarch, land_holder,
--   mandates (count), storage = {boxes...}, rooms = [{kind, need, zone_id, value, statues,
--   statues_pending, ai_built, smooth_left, engrave_left, polish_pending}]}], monarch, capital,
--   land_holders}
-- A room kind the noble has none of is listed with no zone_id.
function survey(txt)
    local out = {nobles = {}, land_holders = {}}
    local found = {}
    for _, u in ipairs(report_citizens(true)) do
        local okp, list = pcall(dfhack.units.getNoblePositions, u)
        if okp and list and #list > 0 then
            local ps = {}
            for _, np in ipairs(list) do
                local okq, p = pcall(position_info, np, txt)
                if okq and p then table.insert(ps, p) end
            end
            local need, store = demands_of(ps)
            local title = title_of(ps)
            if next(need) or title then
                local n = {unit_id = u.id, name = readable(u, txt), title = title, positions = {}, rooms = {},
                           storage = next(store) and store or nil}
                for _, p in ipairs(ps) do
                    table.insert(n.positions, p.code)
                    if p.monarch then n.monarch = true end
                    if p.land_holder and p.land_holder > (n.land_holder or 0) then n.land_holder = p.land_holder end
                end
                table.insert(found, {n = n, u = u, need = need})
                table.insert(out.nobles, n)
                if n.monarch then out.monarch, out.capital = n.name, true end
                if n.land_holder then table.insert(out.land_holders, {name = n.name, title = title}) end
            end
        end
    end
    -- (mandates) each noble's mandates now in force
    pcall(function()
        local by = {}
        for _, f in ipairs(found) do by[f.u.id] = f.n end
        for _, m in ipairs(df.global.world.mandates.all) do
            local n = m.unit and by[m.unit.id]
            if n then n.mandates = (n.mandates or 0) + 1 end
        end
    end)
    -- the rooms: their levels' engravings walked once
    local rooms, levels = {}, {}
    for _, f in ipairs(found) do
        for _, k in ipairs(KINDS) do
            local v = f.need[k]
            if v then
                local zs = owned(f.u, ZONE_OF[k])
                for _, z in ipairs(zs) do levels[z.z] = true end
                table.insert(rooms, {n = f.n, kind = k, need = v, zones = zs})
            end
        end
    end
    local engraved = engravings_on(levels)
    local areas = (#rooms > 0) and ai_areas() or {}
    local read, jobs = 0, nil
    for _, r in ipairs(rooms) do
        local e = {kind = r.kind, need = r.need}
        local best
        for _, z in ipairs(r.zones) do
            if read < ROOMS_MAX then
                read = read + 1
                local v, st, sp = zone_worth(z, engraved)
                if not best or v > best.value then best = {z = z, value = v, statues = st, pending = sp} end
            end
        end
        if best then
            local z = best.z
            e.zone_id, e.value, e.statues = z.id, best.value, best.statues
            e.statues_pending = (best.pending or 0) > 0 and best.pending or nil
            e.ai_built = inside_areas({x1 = z.x1, y1 = z.y1, x2 = z.x2, y2 = z.y2, z = z.z}, areas) or nil
            if e.value < e.need and e.ai_built then
                jobs = jobs or polish_jobs()
                local oks, sm, en, pend = pcall(zone_polish, z, engraved, jobs)
                if oks then
                    e.smooth_left, e.engrave_left = #sm, #en
                    e.polish_pending = (pend or 0) > 0 and pend or nil
                end
            end
        end
        table.insert(r.n.rooms, e)
    end
    out.capital = out.capital or false
    return out
end

-- --- the action ----------------------------------------------------------------

-- Smooth a noble's room (an AI-dug one), or once smooth, engrave it: the
-- natural rock floor and walls round the zone. dry_run: what would be done.
function polish_room(zone_id, dry_run)
    local z = zone_id and df.building.find(zone_id)
    if not z then return {ok = false, rejected = true, error = 'no zone ' .. tostring(zone_id)} end
    local okz = pcall(function() assert(z:getType() == df.building_type.Civzone) end)
    if not okz then return {ok = false, rejected = true, error = 'building ' .. tostring(zone_id) .. ' is not a zone'} end
    if not inside_areas({x1 = z.x1, y1 = z.y1, x2 = z.x2, y2 = z.y2, z = z.z}, ai_areas()) then
        return {ok = false, rejected = true, error = 'zone ' .. zone_id .. " is not in a level the AI dug: the player's rooms are left as they are"}
    end
    local smooth, engrave = zone_polish(z, engravings_on({[z.z] = true}))
    local step, tiles, key = 'smooth', smooth, 's'
    if #smooth == 0 then step, tiles, key = 'engrave', engrave, 'e' end
    if #tiles == 0 then
        return {ok = false, rejected = true, error = 'nothing left to smooth or engrave in zone ' .. zone_id}
    end
    local out = {ok = true, zone_id = zone_id, step = step, tiles = #tiles, dry_run = dry_run or nil}
    if dry_run then return out end
    local cells = {}
    for _, t in ipairs(tiles) do table.insert(cells, {x = t.x - z.x1, y = t.y - z.y1, text = key}) end
    local ok, s = pcall(function()
        return reqscript('ai-builder').quickfort_apply('dig', cells, z.z, z.x1, z.y1)
    end)
    if not ok then return {ok = false, error = 'quickfort failed: ' .. tostring(s)} end
    local n = 0
    pcall(function() n = s.dig_designated.value end)
    out.designated = n
    if n == 0 then out.ok, out.rejected, out.error = false, true, 'quickfort designated nothing in zone ' .. zone_id end
    return out
end
