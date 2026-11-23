-- ai-thirst-remedies: the real remedies for one thirsty dwarf: open_way (the
-- cheapest way to the drink, the AI's walls and locked doors on it and the
-- rock dug, with the safety checks: the AI's protected pieces, unsafe tiles,
-- the siege and the flood check), patient_help and probe.
--
-- (r9) A part of ai-thirst, not a script of its own: ai-thirst.lua loads it
-- into its own environment, so every name here is reqscript('ai-thirst').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-thirst-remedies is a part of ai-thirst; run ai-thirst') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-thirst-remedies'] = '0.105.74'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, now_tick, txt, is, key, group_at, mood_of, job_name, patient, drink_map, NEIGH, wells, water_zones, burrow_by_id, held_kind, civ_alert, burrow_holds = PART_LOCALS.U, PART_LOCALS.now_tick, PART_LOCALS.txt, PART_LOCALS.is, PART_LOCALS.key, PART_LOCALS.group_at, PART_LOCALS.mood_of, PART_LOCALS.job_name, PART_LOCALS.patient, PART_LOCALS.drink_map, PART_LOCALS.NEIGH, PART_LOCALS.wells, PART_LOCALS.water_zones, PART_LOCALS.burrow_by_id, PART_LOCALS.held_kind, PART_LOCALS.civ_alert, PART_LOCALS.burrow_holds   -- (r9) the hub's locals

-- --- (R1 g2) real remedies: a way to the drink, water to a patient, a look at "unknown" ----------
--
-- Why (the 15-16 Nov run): F's fortify walled its own hallway (x110 y148-150
-- z170) and four founders behind it died of thirst `no_path` while the brain
-- asked join_levels 37 times, each "dead_ends: 0" (nothing joined); 12
-- patients died of thirst in the AI's hospital burrow (F), every winter's
-- patients died with no water carried (B), and E's four "unknown" deaths had
-- no action at all. Each function here is one bounded step the brain takes
-- for one dwarf (brain/planner_thirst.py: a few tries each, then Needs you).
--
--   open_way(uid, dry, max_dig)  no_path: the cheapest way from the dwarf to
--        a walk group holding drink or a well, on their level, within
--        WAY_RADIUS: through the AI's own built walls (taken down), the AI's
--        own locked gate doors (unlocked), or natural rock (an ordinary dig
--        designation through the dig guard). Never a player's wall or
--        locked door, never in a siege or near a danger.
--   patient_help(uid, dry)       a patient: lifted out of the AI hospital
--        burrow (when held there), and what water carrying needs, counted:
--        dwarves with the labour, free buckets, a well or water zone in reach.
--   probe(uid, dry)              "unknown": their burrows (an AI one with no
--        drink left), the alarm's burrow, the AI's locked doors near them,
--        the drink in reach forbidden or claimed by jobs: each finding said,
--        the AI's own ones undone.

WAY_RADIUS = 40           -- tiles from the dwarf searched, on their level
WAY_TILES = 4000          -- tiles looked at most
WAY_SECONDS = 0.5         -- the search's time cap (then: no way found, said so)
WAY_DIG_MAX = 30          -- rock tiles dug a call at most
WAY_CHANGE_MAX = 12       -- the AI's walls taken down and doors unlocked a call at most
WAY_COST = {walk = 1, door = 2, wall = 3, rock = 5}
WAY_DANGER = 15           -- nothing taken down or unlocked this near (walked across) a danger
WAY_KEY = 'ai-overseer/thirst-ways'
WAY_KEEP = 200            -- tiles kept in the save's record
PROBE_DOOR_REACH = 12     -- the AI's locked doors looked for this near a dwarf (2 levels up or down)
PATIENT_CARRIERS = 3      -- dwarves with the water-carrying labour a patient needs at least

local ORTHO4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

-- A small binary heap of {cost, x, y}.
local function heap_push(h, c, x, y)
    local n = #h + 1
    h[n] = {c, x, y}
    while n > 1 do
        local p = n // 2
        if h[p][1] <= h[n][1] then break end
        h[p], h[n] = h[n], h[p]
        n = p
    end
end
local function heap_pop(h)
    local top = h[1]
    if not top then return nil end
    local last = table.remove(h)
    if #h > 0 then
        h[1] = last
        local n = 1
        while true do
            local l, r, m = 2 * n, 2 * n + 1, n
            if h[l] and h[l][1] < h[m][1] then m = l end
            if h[r] and h[r][1] < h[m][1] then m = r end
            if m == n then break end
            h[m], h[n] = h[n], h[m]
            n = m
        end
    end
    return top
end

-- The core, without the game: T(x, y) -> nil (off the map) or {kind =
-- 'walk' (group), 'wall' (the AI's built wall), 'door' (the AI's locked
-- door), 'rock' (natural rock safe to dig), 'blocked' (why)}. From (sx, sy)
-- to the nearest walk tile whose group is in `targets`: the steps that are
-- not walking ({x, y, kind}), the cost, or nil and the walls met on the way
-- ({why = n}).
function plan_way(T, sx, sy, targets, opts)
    opts = opts or {}
    local radius, cap = opts.radius or WAY_RADIUS, opts.tiles or WAY_TILES
    local cost = opts.cost or WAY_COST
    local function k(x, y) return y * 4096 + x end
    local best, from, cache = {}, {}, {}
    local function read(x, y)
        local kk = k(x, y)
        local v = cache[kk]
        if v == nil then v = T(x, y) or false; cache[kk] = v end
        return v or nil
    end
    local blocked, seen = {}, 0
    local h = {}
    best[k(sx, sy)] = 0
    heap_push(h, 0, sx, sy)
    while true do
        local top = heap_pop(h)
        if not top then break end
        local c, x, y = top[1], top[2], top[3]
        if c == best[k(x, y)] then
            local t = read(x, y)
            if t and t.kind == 'walk' and targets[t.group] and not (x == sx and y == sy) then
                local steps, path, n = {}, {}, k(x, y)
                while from[n] do
                    local s = from[n]
                    if s.kind ~= 'walk' then table.insert(steps, 1, {x = s.x, y = s.y, kind = s.kind}) end
                    table.insert(path, 1, {x = s.x, y = s.y, kind = s.kind})
                    n = s.prev
                end
                -- (X1, V8) path: every tile of the way, walked ones too (the start's not)
                return {steps = steps, path = path, cost = c, to = {x = x, y = y, group = t.group}}
            end
            seen = seen + 1
            if seen > cap or (opts.deadline and seen % 64 == 0 and os.clock() > opts.deadline) then
                seen = cap + 1
                break
            end
            for _, d in ipairs(ORTHO4) do
                local nx, ny = x + d[1], y + d[2]
                if math.abs(nx - sx) <= radius and math.abs(ny - sy) <= radius then
                    local nt = read(nx, ny)
                    if nt then
                        local step = cost[nt.kind]
                        if step then
                            local nc, nk = c + step, k(nx, ny)
                            if best[nk] == nil or nc < best[nk] then
                                best[nk] = nc
                                from[nk] = {prev = k(x, y), x = nx, y = ny, kind = nt.kind}
                                heap_push(h, nc, nx, ny)
                            end
                        elseif nt.kind == 'blocked' then
                            local w = nt.why or 'in the way'
                            blocked[w] = (blocked[w] or 0) + 1
                        end
                    end
                end
            end
        end
    end
    return nil, blocked, seen > cap
end

-- the walk groups holding drink (not forbidden), a well that gives water or a water zone
local function drink_groups()
    local out = {}
    local dm, wl, wz = drink_map(), wells(), water_zones()
    for g, e in pairs(dm.groups) do if (e.n or 0) > 0 then out[g] = true end end
    for g in pairs(wl.by_group) do out[g] = true end
    for g in pairs(wz.by_group) do out[g] = true end
    return out, dm, wl, wz
end

local function shape_name(x, y, z)
    local ok, sh = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        return df.tiletype_shape[df.tiletype.attrs[tt].shape]
    end)
    return ok and sh or nil
end

-- The gate pieces the AI shut itself (ai-gates' GATES.mine, by building id),
-- and whether the gates are shut against enemies now.
local function gates_facts()
    local mine, armed = {}, false
    pcall(function()
        local G = reqscript('ai-gates').GATES
        armed = G.armed == true
        if type(G.mine) == 'table' then for id in pairs(G.mine) do mine[tonumber(id) or id] = true end end
    end)
    return mine, armed
end

local function door_kind(b)
    local ok, t = pcall(function() return df.building_type[b:getType()] end)
    return ok and (t == 'Door' or t == 'Hatch') and t or nil
end

-- (X1, V2/S1) "x,y,z", {x, y, z} or ai-gates' number key -> x, y, z (or nil)
local function any_xyz(v)
    if type(v) == 'string' then
        local x, y, z = v:match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
        return tonumber(x), tonumber(y), tonumber(z)
    elseif type(v) == 'table' then
        local x, y, z = v.x or v[1], v.y or v[2], v.z or v[3]
        if type(x) == 'number' and type(y) == 'number' and type(z) == 'number' then return x, y, z end
    elseif math.type(v) == 'integer' and v >= 0 then
        return v % 4096, (v // 4096) % 4096, v // (4096 * 4096)
    end
end

-- (X1, V2/S1) The AI's pieces thirst_way never takes down nor unlocks, by
-- their records (not only by what lies beside them): {tiles = {"x,y,z" =
-- what}, ids = {building id = what}}. The cistern (its rooms, tunnel, shaft
-- and sealing walls), every entrance's recorded pieces (a cavern's and its
-- seal's, the wings; a surface gate's pieces are judged by the flood check,
-- see open_way), the wings' record, ai-threats' claimed doors (the moon
-- cells', the cavern seal's, the openings to the caverns, the entrances the
-- watcher holds shut now), the killer cells' doors, the lures' pieces and
-- pockets, the kill zones' traps and bridges, the cavern wells' shafts,
-- stairs, doors and hatches. Tests replace WAY_PROTECTED.
WAY_PROTECTED = nil
function protected_pieces()
    if WAY_PROTECTED then return WAY_PROTECTED() end
    local out = {tiles = {}, ids = {}}
    local function tile(v, what)
        local x, y, z = any_xyz(v)
        if x then out.tiles[key(x, y, z)] = out.tiles[key(x, y, z)] or what end
    end
    local function ids(set, what)
        for id, on in pairs(type(set) == 'table' and set or {}) do
            if on then out.ids[tonumber(id) or id] = out.ids[tonumber(id) or id] or what end
        end
    end
    local function each(list, fn) if type(list) == 'table' then for _, v in pairs(list) do pcall(fn, v) end end end
    pcall(function() for k in pairs(U.cistern_tiles()) do tile(k, 'the cistern') end end)
    pcall(function()
        local d = U.site_get('ai-overseer/cistern', {})
        for k in pairs(type(d) == 'table' and type(d.sealing) == 'table' and d.sealing or {}) do tile(k, 'the cistern') end
    end)
    pcall(function()
        local G = reqscript('ai-gates').GATES
        each(type(G) == 'table' and G.entrances, function(e)
            local cavern = e.kind == 'cavern'
            each(e.seal_pieces, function(v) tile(v, 'the cavern seal') end)
            each(e.wings, function(v) tile(v, 'a gate\'s wing') end)
            each(e.wing_pieces, function(v) tile(v, 'a gate\'s wing') end)
            if cavern then
                each(e.pieces, function(v) tile(v, 'the cavern seal') end)
                each(e.equipment, function(b) if b.id ~= nil then out.ids[b.id] = 'the cavern seal' end end)
            end
        end)
    end)
    pcall(function()
        local d = U.site_get('ai-overseer/wings', {})
        for _, list in pairs(type(d) == 'table' and d or {}) do each(list, function(v) tile(v, 'a gate\'s wing') end) end
    end)
    pcall(function() ids(reqscript('ai-threats').claimed_doors(), 'a door the threats rules hold (a cell, the seal)') end)
    pcall(function()
        for _, c in pairs(reqscript('ai-killers').state().cells or {}) do
            if type(c) == 'table' then
                each(c.doors, function(id) out.ids[tonumber(id) or id] = 'a killer cell\'s door' end)
            end
        end
    end)
    pcall(function()
        local L = reqscript('ai-lure')
        ids(L.held_ids(), 'a lure\'s piece')
        ids(L.held_open(), 'a lure\'s piece')
        for _, rec in pairs(L.load_state().lures or {}) do
            if type(rec) == 'table' then
                tile(rec, 'a lure\'s piece')
                each(rec.tiles, function(v) tile(v, 'a lure\'s pocket') end)
                each(rec.traps, function(v) tile(v, 'a lure\'s trap') end)
                tile(rec.inner, 'a lure\'s gate')
                tile(rec.mouth, 'a lure\'s gate')
            end
        end
    end)
    pcall(function()
        for _, rec in pairs(reqscript('ai-killzone').records()) do
            if type(rec) == 'table' then
                each(rec.traps, function(v) tile(v, 'a kill zone\'s trap') end)
                tile(rec.bridge, 'a kill zone\'s bridge')
            end
        end
    end)
    pcall(function()
        local B = reqscript('ai-builder')
        local data = B.load_projects()
        each(type(data) == 'table' and data.list, function(p)
            if type(p) ~= 'table' or p.kind ~= 'well' then return end
            local a = B.anchor_of(p)
            for _, z in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
                if a and a.x then tile({a.x, a.y, z}, 'a well\'s shaft') end
            end
            each(p.shaft_stairs, function(v) tile(v, 'a well\'s shaft stair') end)
            tile(p.fort_door, 'a well\'s door')
            if type(p.rescue) == 'table' then tile(p.rescue.hatch, 'a well\'s hatch') end
        end)
    end)
    return out
end

-- (X1, V1/V2) tile_info's tiles a dig or a wall's removal must never open:
-- water, magma, a cavern (or any deep feature), the sky, an aquifer, open
-- space, warm (magma-heated) stone, or a tile that can't be read
local function unsafe(t)
    return t == nil or t.liquid or t.magma or t.aquifer or t.feature or t.outside or t.warm or t.shape == 'EMPTY'
end

-- (X1, V1) why (x, y, z) may not be opened, or nil: one of its 8 neighbours
-- on its level, or the tile over or under it, is unsafe (DF's water and
-- magma spread to all 8, and units walk diagonally between two walls)
function beside_unsafe(info, x, y, z)
    for _, d in ipairs(NEIGH) do
        local ok, nt = pcall(info, x + d[1], y + d[2], z)
        if not ok or unsafe(nt) then return 'water, magma, a cavern, the sky or an aquifer beside it' end
    end
    for _, dz in ipairs({1, -1}) do
        local ok, nt = pcall(info, x, y, z + dz)
        if not ok or unsafe(nt) then
            return ('water, magma, a cavern, the sky or an aquifer %s it'):format(dz > 0 and 'over' or 'under')
        end
    end
    return nil
end

-- (X1, V2) the AI's wall categories (ai-constructions ai_claim) that only
-- part the fort's own rooms and halls: the only ones thirst_way takes down
-- (gate_pieces: a surface gate's line inside the fort, and only when the
-- flood check finds the fort still shut from the outside; never the keep,
-- the cistern, the cavern seal or the wings)
WAY_WALL_CATS = {room_walls = true, halls = true, gate_pieces = true}

-- The game's tile reader on level z (tests replace WAY_READER).
WAY_READER = nil
function game_way_reader(z)
    if WAY_READER then return WAY_READER(z) end
    local B = reqscript('ai-builder')
    local okc, C = pcall(reqscript, 'ai-constructions')
    local R = nil
    if okc and C and C.ai_regions then
        local okr, r = pcall(C.ai_regions)
        R = okr and r or nil
    end
    local mine = gates_facts()
    local okp, prot = pcall(protected_pieces)
    prot = okp and type(prot) == 'table' and prot or {tiles = {}, ids = {}}
    return function(x, y)
        local pos = xyz2pos(x, y, z)
        local okb, b = pcall(dfhack.buildings.findAtTile, pos)
        if okb and b and door_kind(b) then
            local okf, locked = pcall(function() return b.door_flags.forbidden end)
            if okf and locked then
                local held = prot.ids[b.id] or prot.tiles[key(x, y, z)]
                if held then return {kind = 'blocked', why = 'a locked door the AI holds: ' .. tostring(held)} end
                if mine[b.id] then return {kind = 'door', b = b} end
                return {kind = 'blocked', why = 'a locked door not the AI\'s'}
            end
        end
        local g = group_at(x, y, z)
        if g and g ~= 0 then return {kind = 'walk', group = g} end
        local okt, t = pcall(B.tile_info, x, y, z)
        if not okt or not t then return nil end
        local okk, built = pcall(dfhack.constructions.findAtTile, pos)
        if okk and built and (t.shape == 'WALL' or t.shape == 'FORTIFICATION') then
            local cat = R and C.ai_claim(R, x, y, z, t.shape == 'WALL' and 'wall' or 'fortification',
                                          t.subterranean == false)
            if not cat then return {kind = 'blocked', why = 'a wall the AI did not build'} end
            -- (X1, V2) only a plain wall of the fort's own rooms, halls or a gate's inner line
            local held = prot.tiles[key(x, y, z)]
            if held then return {kind = 'blocked', why = 'the AI\'s wall of ' .. tostring(held)} end
            if not WAY_WALL_CATS[cat] then
                return {kind = 'blocked', why = 'the AI\'s ' .. tostring(cat) .. ' wall (never taken down)'}
            end
            if t.aquifer or t.liquid then return {kind = 'blocked', why = 'water at the AI\'s wall'} end
            local why = beside_unsafe(B.tile_info, x, y, z)
            if why then return {kind = 'blocked', why = 'the AI\'s wall: ' .. why} end
            return {kind = 'wall', cat = cat}
        end
        -- rock already marked for digging (the AI's last call, or anyone's
        -- plain dig) is still rock on the way: it will be dug
        local t2 = t
        if t.designated and t.dig == 'Default' then t2 = setmetatable({designated = false}, {__index = t}) end
        local okn, nat = pcall(B.natural_wall, t2)
        if okn and nat and not t.smoothed then
            -- (X1, V1) all 8 neighbours on the level and the tiles over and under it
            if beside_unsafe(B.tile_info, x, y, z) then
                return {kind = 'blocked', why = 'water, magma, a cavern or the sky beside the rock'}
            end
            if prot.tiles[key(x, y, z)] then return {kind = 'blocked', why = 'the AI\'s ' .. prot.tiles[key(x, y, z)]} end
            if U.dig_forbidden(x, y, z) then return {kind = 'blocked', why = 'the dig guard'} end
            return {kind = 'rock'}
        end
        return {kind = 'blocked', why = 'not natural rock to dig'}
    end
end

-- What the actions do in the game (tests replace these).
WAY_DO = {
    remove = function(x, y, z)
        local ok, r = pcall(dfhack.constructions.designateRemove, xyz2pos(x, y, z))
        return ok and r and true or false
    end,
    unlock = function(b) local changed = U.lock_door(b, false, 'thirst') return changed end,
    dig = function(x, y, z)
        local d = dfhack.maps.getTileFlags(x, y, z)
        if not d then return false end
        if d.dig ~= df.tile_dig_designation.No then return 'pending' end
        if U.dig_forbidden(x, y, z) then return false end
        d.dig = df.tile_dig_designation.Default
        local block = dfhack.maps.getTileBlock(x, y, z)
        if block then block.flags.designated = true end
        return true
    end,
}

local function way_record(tiles, z, now)
    local d = U.site_get(WAY_KEY, {})
    local list = type(d.tiles) == 'table' and d.tiles or {}
    for _, p in ipairs(tiles) do table.insert(list, {x = p.x, y = p.y, z = z, kind = p.kind, tick = now}) end
    while #list > WAY_KEEP do table.remove(list, 1) end
    U.site_put(WAY_KEY, {tiles = list})
end

-- (X1, V8) Why no way may be opened now, or nil: the gates shut against
-- enemies, or the civilian alarm up while a danger can reach the dwarves
-- (one standing in a citizen's walk group). dangers: U.danger_spots().
local function siege_why(dangers)
    local _, armed = gates_facts()
    if armed then return 'the gates are shut against enemies: nothing is dug, taken down or unlocked' end
    if #dangers == 0 then return nil end
    local alert = civ_alert()
    if not alert.on then return nil end
    local groups = {}
    local okc, cits = pcall(U.citizens, false, true)
    for _, c in ipairs(okc and cits or {}) do
        pcall(function()
            local g = group_at(c.pos.x, c.pos.y, c.pos.z)
            if g and g ~= 0 then groups[g] = true end
        end)
    end
    for _, d in ipairs(dangers) do
        local g = group_at(d.x, d.y, d.z)
        if g and g ~= 0 and groups[g] then
            return ('the alarm is up for an enemy that can reach the dwarves (x%d y%d z%d): nothing is dug, taken '
                .. 'down or unlocked'):format(d.x, d.y, d.z)
        end
    end
    return nil
end

-- (X1, V8) The flood check on a reader (tests: WAY_READER): from seed over
-- the walk tiles of its level (8 ways), a gate piece (t.gate) never crossed.
-- Exposed: the map's edge (a tile off the map beside a walked one), a tile
-- under the sky (t.outside, but t.way_out: the fort's own ungated way out),
-- or a danger on or beside a walked tile. -> why or nil, capped.
local function reader_exposure(seed, T, dangers)
    local function k(x, y) return y * 4096 + x end
    local seen, q, h = {[k(seed.x, seed.y)] = true}, {{seed.x, seed.y}}, 1
    local cap = WAY_TILES * 4
    while h <= #q do
        if #q > cap then return 'too big to check', true end
        local x, y = q[h][1], q[h][2]
        h = h + 1
        local t = T(x, y)
        if t and t.outside and not t.way_out then return ('the outside at x%d y%d z%d'):format(x, y, seed.z) end
        for _, d in ipairs(dangers) do
            if d.z == seed.z and math.abs(d.x - x) <= 1 and math.abs(d.y - y) <= 1 then
                return ('a danger at x%d y%d z%d'):format(d.x, d.y, d.z)
            end
        end
        for _, d in ipairs(NEIGH) do
            local nx, ny = x + d[1], y + d[2]
            if not seen[k(nx, ny)] then
                seen[k(nx, ny)] = true
                local nt = T(nx, ny)
                if nt == nil then return ('the map\'s edge at x%d y%d z%d'):format(nx, ny, seed.z) end
                if nt.kind == 'walk' and not nt.gate then table.insert(q, {nx, ny}) end
            end
        end
    end
    return nil
end

-- (X1, V8) The flood check in the game: ai-gates' own flood of the fort
-- (explore: every level, stairs and ramps) from seed, every gate piece of
-- every entrance shut (their equipment and outer gates) and the pieces the
-- AI holds (the seal's, the cells', the lures'). Exposed: the seed itself
-- outside the fort, an opening reached that is not an entrance with no gate
-- at all (the fort's own ungated way out: the fort is open there anyway),
-- or a danger standing on a tile reached. -> why or nil, capped.
function game_exposure(seed, dangers, prot)
    local G = reqscript('ai-gates')
    local GT = type(G.GATES) == 'table' and G.GATES or {}
    local function nk(x, y, z) return (z * 4096 + y) * 4096 + x end
    local function unk(k) return k % 4096, (k // 4096) % 4096, k // (4096 * 4096) end
    local shut = {}
    local function add_b(b)
        pcall(function()
            for x = b.x1, b.x2 do for y = b.y1, b.y2 do shut[nk(x, y, b.z)] = true end end
        end)
    end
    local function add_id(id)
        pcall(function() local b = df.building.find(id); if b then add_b(b) end end)
    end
    local ents = type(GT.entrances) == 'table' and GT.entrances or {}
    for _, e in ipairs(ents) do
        for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
            for _, g in ipairs(list) do
                if type(g) == 'table' then
                    if g.x1 and g.x2 and g.y1 and g.y2 and g.z then add_b(g) elseif g.id ~= nil then add_id(g.id) end
                end
            end
        end
    end
    for id in pairs(prot and prot.ids or {}) do add_id(id) end
    local oc, oe = G.cache, G.edge_cache
    G.cache, G.edge_cache = {}, {}
    local ok, seen, n, openings = pcall(G.explore, {{x = seed.x, y = seed.y, z = seed.z}}, shut)
    G.cache, G.edge_cache = oc, oe
    if not ok or type(seen) ~= 'table' then return 'the flood check failed: ' .. tostring(seen):sub(1, 80) end
    if (tonumber(n) or 0) >= (tonumber(G.MAX_TILES) or 250000) then return 'too big to check', true end
    if not seen[nk(seed.x, seed.y, seed.z)] then
        return ('the far end x%d y%d z%d is outside the fort'):format(seed.x, seed.y, seed.z)
    end
    for _, o in ipairs(type(openings) == 'table' and openings or {}) do
        local own = nil
        for _, e in ipairs(ents) do
            local hit = type(e.outs) == 'table' and e.outs[o.out]
            if not hit then
                for _, ik in ipairs(e.inside_list or {}) do if ik == o.inside then hit = true break end end
            end
            if hit then own = e break end
        end
        local gated = own and (#(own.equipment or {}) > 0 or own.kind == 'cavern')
        if not own or gated then
            local x, y, z = unk(o.out)
            return ('%s at x%d y%d z%d past the gates'):format(o.kind == 'cavern' and 'a cavern' or 'the outside',
                x, y, z)
        end
    end
    for _, d in ipairs(dangers) do
        if seen[nk(d.x, d.y, d.z)] then return ('a danger at x%d y%d z%d'):format(d.x, d.y, d.z) end
    end
    return nil
end

WAY_EXPOSURE = nil        -- tests: function(seed {x, y, z}, T, dangers) -> why or nil, capped
local function exposure(seed, T, dangers, prot)
    if WAY_EXPOSURE then return WAY_EXPOSURE(seed, T, dangers) end
    if WAY_READER then return reader_exposure(seed, T, dangers) end
    return game_exposure(seed, dangers, prot)
end

function open_way(uid, dry_run, max_dig)
    max_dig = math.max(1, math.min(tonumber(max_dig) or WAY_DIG_MAX, 60))
    local u = df.unit.find(uid)
    if not u or is(dfhack.units.isDead, u) then return {ok = false, rejected = true, error = 'no such living unit'} end
    local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
    -- (X1, V5) never a way out of a cell, the calm-down room, the jail or chains
    local held = held_kind(u)
    if held then
        return {ok = false, rejected = true, held = held,
                error = ('held on purpose (%s): no way is opened out of it'):format(held)}
    end
    local g = group_at(p.x, p.y, p.z)
    if not g or g == 0 then return {ok = false, rejected = true, error = 'the dwarf stands on no walkable tile'} end
    local targets = drink_groups()
    if targets[g] then
        return {ok = true, nothing = true, group = g, note = 'drink or water is already in their walk group'}
    end
    if next(targets) == nil then
        return {ok = false, rejected = true, error = 'no drink nor water anywhere a dwarf can walk to'}
    end
    -- (X1, V8) a siege: nothing dug, taken down or unlocked (not only walls and doors)
    local okd, dangers = pcall(U.danger_spots)
    dangers = okd and type(dangers) == 'table' and dangers or {}
    local siege = siege_why(dangers)
    if siege then return {ok = false, rejected = true, siege = true, error = siege} end
    local okp, prot = pcall(protected_pieces)
    prot = okp and type(prot) == 'table' and prot or {tiles = {}, ids = {}}
    local T0 = game_way_reader(p.z)
    -- (X1, V2) whatever the reader says, only a plain wall of the fort's rooms
    -- and halls (or a gate's inner line) and none on the AI's records
    local function T(x, y)
        local t = T0(x, y)
        if t and t.kind == 'wall' then
            if not WAY_WALL_CATS[t.cat] then
                return {kind = 'blocked', why = 'the AI\'s ' .. tostring(t.cat) .. ' wall (never taken down)'}
            end
            local what = prot.tiles[key(x, y, p.z)]
            if what then return {kind = 'blocked', why = 'the AI\'s wall of ' .. tostring(what)} end
        elseif t and t.kind == 'door' then
            local what = (t.b and prot.ids[t.b.id]) or prot.tiles[key(x, y, p.z)]
            if what then return {kind = 'blocked', why = 'a locked door the AI holds: ' .. tostring(what)} end
        elseif t and t.kind == 'rock' then
            local what = prot.tiles[key(x, y, p.z)]
            if what then return {kind = 'blocked', why = 'the AI\'s ' .. tostring(what)} end
        end
        return t
    end
    local r, blocked, capped = plan_way(T, p.x, p.y, targets, {deadline = os.clock() + WAY_SECONDS})
    if not r then
        local bits = {}
        for w, n in pairs(blocked or {}) do table.insert(bits, ('%s x%d'):format(w, n)) end
        table.sort(bits)
        return {ok = false, rejected = true, blocked = blocked, capped = capped or nil,
                error = ('no way to drink found on their level within %d tiles%s'):format(WAY_RADIUS,
                    #bits > 0 and (': ' .. table.concat(bits, ', ')) or '')}
    end
    local walls, doors, rock = {}, {}, {}
    for _, s in ipairs(r.steps) do
        if s.kind == 'wall' then table.insert(walls, s)
        elseif s.kind == 'door' then table.insert(doors, s)
        elseif s.kind == 'rock' then table.insert(rock, s) end
    end
    local out = {ok = true, z = p.z, from = p, to = r.to, cost = r.cost, walls = #walls, doors = #doors,
                 rock = #rock, dry_run = dry_run or nil}
    if #r.steps == 0 then
        out.nothing, out.note = true, 'a walkable way reads open already (DF\'s walk map may lag)'
        return out
    end
    if #rock > max_dig then
        return {ok = false, rejected = true, rock = #rock, walls = #walls,
                error = ('the way to drink needs %d tiles dug (at most %d)'):format(#rock, max_dig)}
    end
    if #walls + #doors > WAY_CHANGE_MAX then
        return {ok = false, rejected = true, walls = #walls, doors = #doors,
                error = ('the way to drink crosses %d of the AI\'s walls and doors (at most %d)'):format(
                    #walls + #doors, WAY_CHANGE_MAX)}
    end
    -- (X1, V8) no danger near ANY tile of the way (dug, taken down, unlocked
    -- or walked) nor its far end
    local way = {}
    for _, s in ipairs(r.path or r.steps) do table.insert(way, s) end
    table.insert(way, {x = r.to.x, y = r.to.y})
    for _, s in ipairs(way) do
        if U.near_danger(dangers, s.x, s.y, p.z, WAY_DANGER) then
            return {ok = false, rejected = true, error = ('a danger is near x%d y%d z%d'):format(s.x, s.y, p.z)}
        end
    end
    -- (X1, V8) the flood check: from the way's far end, every gate shut, the
    -- fort must not reach the outside past a gate, a cavern or a danger,
    -- unless the dwarf's own side already does (then nothing new is opened)
    local far = {x = r.to.x, y = r.to.y, z = p.z}
    local exposed, ecap = exposure(far, T, dangers, prot)
    if exposed then
        local own, ocap = exposure(p, T, dangers, prot)
        if ecap or not own or ocap then
            return {ok = false, rejected = true, exposed = exposed,
                    error = ('opened, the way would join the fort to %s'):format(exposed)}
        end
        out.exposed_already = own
    end
    local steps = {}
    for i, s in ipairs(r.steps) do
        if i <= 8 then table.insert(steps, ('%s x%d y%d'):format(s.kind, s.x, s.y)) end
    end
    out.steps = steps
    if dry_run then return out end
    local removed, unlocked, dug, pending = 0, 0, 0, 0
    for _, s in ipairs(walls) do
        if WAY_DO.remove(s.x, s.y, p.z) then removed = removed + 1 end
    end
    for _, s in ipairs(doors) do
        local t = T(s.x, s.y)
        if t and t.b and WAY_DO.unlock(t.b) then unlocked = unlocked + 1 end
    end
    for _, s in ipairs(rock) do
        local d = WAY_DO.dig(s.x, s.y, p.z)
        if d == 'pending' then pending = pending + 1 elseif d then dug = dug + 1 end
    end
    out.removed, out.unlocked, out.dug, out.pending = removed, unlocked, dug, pending
    pcall(way_record, r.steps, p.z, now_tick())
    if removed + unlocked + dug + pending == 0 then
        out.ok, out.rejected, out.error = false, true, 'the way was found but nothing on it could be changed'
    end
    return out
end

-- The AI hospital burrow's record and burrow (ai-society-burrows), or nil.
local function hospital_burrow()
    local okS, S = pcall(reqscript, 'ai-society-burrows')
    if not okS or type(S) ~= 'table' or not S.HOSPITAL_BURROW_KEY then return nil end
    local d = U.site_get(S.HOSPITAL_BURROW_KEY, {})
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}
    local b = d.burrow_id ~= nil and burrow_by_id(d.burrow_id) or nil
    return {S = S, d = d, b = b}
end

local function in_burrow(u, bid)
    local ok, yes = pcall(function()
        for _, id in ipairs(u.burrows) do if id == bid then return true end end
        return false
    end)
    return ok and yes or false
end

-- Lift one dwarf out of the AI hospital burrow (not let back in for its
-- HOSP_OUT_DAYS): true if they were held there.
local function lift_hospital(u, dry_run, now)
    local h = hospital_burrow()
    if not h then return false end
    local key = tostring(u.id)
    local held = h.d.members[key] ~= nil or (h.b ~= nil and in_burrow(u, h.b.id))
    if not held or dry_run then return held end
    if h.b then pcall(dfhack.burrows.setAssignedUnit, h.b, u, false) end
    h.d.members[key] = nil
    h.d.out[key] = now
    U.site_put(h.S.HOSPITAL_BURROW_KEY, h.d)
    return true
end

local function has_labor(u, name)
    local ok, yes = pcall(function() return u.status.labors[df.unit_labor[name]] == true end)
    return ok and yes or false
end

local function buckets()
    local n, free = 0, 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.BUCKET) do
            local fl = it.flags
            if not (fl.garbage_collect or fl.trader or fl.dump or fl.removed) then
                n = n + 1
                if not (fl.forbid or fl.in_job) then free = free + 1 end
            end
        end
    end)
    return n, free
end

function patient_help(uid, dry_run)
    local u = df.unit.find(uid)
    if not u or is(dfhack.units.isDead, u) then return {ok = false, rejected = true, error = 'no such living unit'} end
    local now = now_tick()
    local out = {ok = true, unit_id = uid, dry_run = dry_run or nil, missing = {}}
    out.lifted = lift_hospital(u, dry_run, now) or nil
    -- who carries water: citizens with the labour, not soldiers, not patients, sane
    local carriers = 0
    local okc, cits = pcall(U.citizens, false, true)
    for _, c in ipairs(okc and cits or {}) do
        if c.id ~= uid and not is(dfhack.units.isDead, c) and has_labor(c, 'FEED_WATER_CIVILIANS') then
            local soldier = false
            pcall(function() soldier = c.military.squad_id ~= -1 end)
            local m = mood_of(c)
            if not soldier and not patient(c) and not (m and INSANE_MOODS[m]) then carriers = carriers + 1 end
        end
    end
    out.carriers = carriers
    out.buckets, out.buckets_free = buckets()
    local g = group_at(u.pos.x, u.pos.y, u.pos.z)
    local wl, wz = wells(), water_zones()
    out.group = g
    out.wells_here = g and wl.by_group[g] or 0
    out.water_zones_here = g and wz.by_group[g] or 0
    out.wells = #wl.list
    out.water_zones = wz.n
    if carriers < PATIENT_CARRIERS then table.insert(out.missing, 'carriers') end
    if out.buckets_free == 0 then table.insert(out.missing, 'buckets') end
    if out.wells_here + out.water_zones_here == 0 then table.insert(out.missing, 'water') end
    if #out.missing == 0 then out.missing = nil end
    return out
end

function probe(uid, dry_run)
    local u = df.unit.find(uid)
    if not u or is(dfhack.units.isDead, u) then return {ok = false, rejected = true, error = 'no such living unit'} end
    local now = now_tick()
    local out = {ok = true, unit_id = uid, findings = {}, acted = 0, dry_run = dry_run or nil}
    local function say(s) if #out.findings < 12 then table.insert(out.findings, s) end end
    local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
    local g = group_at(p.x, p.y, p.z)
    local dm, wl, wz = drink_map(), wells(), water_zones()
    local e = g and dm.groups[g] or nil
    local spots = {}
    for _, s in ipairs(e and e.spots or {}) do table.insert(spots, s) end
    for _, w in ipairs(wl.list) do if g and w.groups[g] then table.insert(spots, w) end end
    for _, w in ipairs(wz.list) do if g and w.groups[g] then table.insert(spots, w) end end
    -- the drink in reach: free, forbidden, claimed by a job
    local claimed = 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.DRINK) do
            if it.flags.in_job then
                local x, y, z = U.item_pos(it)
                if x and group_at(x, y, z) == g then claimed = claimed + (it.stack_size or 1) end
            end
        end
    end)
    out.drink_here = e and e.n or 0
    out.forbidden_here = e and e.forbidden or 0
    out.claimed_here = claimed
    out.wells_here = g and wl.by_group[g] or 0
    if out.drink_here > 0 and claimed >= out.drink_here and out.wells_here == 0 then
        say(('all %d drink in reach is claimed by jobs'):format(out.drink_here))
    end
    if out.drink_here == 0 and out.forbidden_here > 0 then
        say(('the drink in reach is forbidden (%d)'):format(out.forbidden_here))
        if not dry_run then
            local r = unforbid_drink(uid, false)
            if r and (r.unforbidden or 0) > 0 then out.acted = out.acted + 1; say(('%d let go'):format(r.unforbidden)) end
        end
    end
    -- their burrows: the AI's with no drink left (the hospital's: the patient's lift)
    local budget = {n = BURROW_TILE_CHECKS}
    local h = hospital_burrow()
    pcall(function()
        local ids = {}
        for _, bid in ipairs(u.burrows) do table.insert(ids, bid) end
        for _, bid in ipairs(ids) do
            local b = burrow_by_id(bid)
            local nm = b and txt(tostring(b.name)) or tostring(bid)
            local ai = nm:sub(1, 3) == 'AI '
            local holds = b and burrow_holds(b, spots, budget)
            local hk = held_burrow_kind(nm)
            if hk then
                -- (X1, V5) a cell's burrow or the calm-down room: never lifted here
                say(('held in %s (the AI\'s %s): left alone'):format(nm, hk == 'calm' and 'calm-down room' or 'cell'))
            elseif holds == false then
                if ai and h and h.b and h.b.id == bid then
                    say(('held in %s, which holds no drink they reach'):format(nm))
                    if lift_hospital(u, dry_run, now) and not dry_run then out.acted = out.acted + 1; say('let out of it') end
                elseif ai then
                    say(('held in %s, which holds no drink they reach'):format(nm))
                    if not dry_run and b then
                        local ok = pcall(dfhack.burrows.setAssignedUnit, b, u, false)
                        if ok then out.acted = out.acted + 1; say('taken out of it') end
                    end
                else
                    say(('in the player\'s burrow %s, which holds no drink they reach (left alone)'):format(nm))
                end
            end
        end
    end)
    -- the alarm's burrow
    local alert = civ_alert()
    if alert.on then
        local any, dry = false, true
        for bid in pairs(alert.burrows) do
            any = true
            local b = burrow_by_id(bid)
            if b and burrow_holds(b, spots, budget) ~= false then dry = false end
        end
        if any and dry then say('the alarm keeps them in burrows with no drink they reach') end
    end
    -- the AI's locked doors near them
    local mine, armed = gates_facts()
    local dangers = nil
    -- (X1, S1) never the seal's, a lure's, a kill zone's, a cell's, a well's door
    local okp, prot = pcall(protected_pieces)
    prot = okp and type(prot) == 'table' and prot or {tiles = {}, ids = {}}
    for _, list in ipairs({'DOOR', 'HATCH'}) do
        pcall(function()
            for _, b in ipairs(df.global.world.buildings.other[list]) do
                if math.abs(b.z - p.z) <= 2 and math.abs(b.centerx - p.x) <= PROBE_DOOR_REACH
                        and math.abs(b.centery - p.y) <= PROBE_DOOR_REACH and b.door_flags.forbidden then
                    local held = prot.ids[b.id] or prot.tiles[key(b.centerx, b.centery, b.z)]
                    if mine[b.id] and held then
                        say(('the AI\'s locked door at x%d y%d z%d stays locked: %s'):format(b.centerx, b.centery, b.z, tostring(held)))
                    elseif mine[b.id] and not armed then
                        dangers = dangers or U.danger_spots()
                        local siege = siege_why(dangers)      -- (X1, V8) the alarm up for an enemy in reach
                        if siege then
                            say(('the AI\'s locked door at x%d y%d z%d stays locked: %s'):format(b.centerx, b.centery, b.z,
                                siege:gsub(':.*$', '')))
                        elseif U.near_danger(dangers, b.centerx, b.centery, b.z, WAY_DANGER) then
                            say(('the AI\'s locked door at x%d y%d z%d stays locked: a danger is near'):format(b.centerx, b.centery, b.z))
                        else
                            say(('the AI\'s locked door at x%d y%d z%d'):format(b.centerx, b.centery, b.z))
                            if not dry_run and WAY_DO.unlock(b) then out.acted = out.acted + 1; say('unlocked') end
                        end
                    elseif mine[b.id] then
                        say(('the AI\'s locked door at x%d y%d z%d stays locked: the gates are shut against enemies'):format(b.centerx, b.centery, b.z))
                    else
                        say(('a locked door not the AI\'s at x%d y%d z%d (left alone)'):format(b.centerx, b.centery, b.z))
                    end
                end
            end
        end)
    end
    local jn = job_name(u)
    out.job = jn
    if jn == 'Rest' then say('resting in bed: only water carried from a well reaches them') end
    if #out.findings == 0 then say('nothing found in the way') end
    return out
end
