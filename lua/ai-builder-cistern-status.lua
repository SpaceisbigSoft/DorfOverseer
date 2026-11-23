-- ai-builder-cistern-status: the cistern as built: its saved record, status, levers, retiring, gaps.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment right after ai-builder-cistern, so every name here is
-- reqscript('ai-builder').name and the helpers defined there are in reach.
-- (r8) Split off ai-builder-cistern.lua by theme; the top-level locals the
-- ai-builder-cistern files share with this one come from CISTERN_PART_LOCALS.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-cistern-status'] = '0.105.87'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez
local DIR8 = CISTERN_PART_LOCALS.DIR8

-- --- building the cistern: one step a call ------------------------------------------
--
--   dig       stairs down from the well spot into the cistern's middle, the
--             room and the tunnel dug (all but the plug)
--   build     the floodgate (first tunnel tile) and the lever placed
--   link      the lever linked to the floodgate
--   open      the floodgate opened (a pull) so the water can come through
--   plug      the plug dug: the water comes in (the miner goes back out
--             through the open floodgate and up the stairs)
--   fill      waiting for 6/7 in the cistern, then the floodgate shut
--   hole      the down stair over the cistern channelled into the well's hole
--   well      the well built over it
--   done      kept: the AI opens the floodgate when the cistern falls under
--             3/7 and shuts it at 6/7 (cistern_status reports it)
-- State in site data 'ai-overseer/cistern'.
CISTERN_KEY = 'ai-overseer/cistern'
CISTERN_FULL, CISTERN_LOW = 6, 3

function cistern_data()
    local d = site_get(CISTERN_KEY)
    return d.stage and d or nil
end

local function save_cistern(d) site_put(CISTERN_KEY, d) end

-- The game's own clock (not now_tick: the tests swap that one for the projects').
local function game_tick()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and t or 0
end

local function room_tiles(c)
    local out = {}
    for y = c.y1, c.y2 do
        for x = c.x1, c.x2 do table.insert(out, {x = x, y = y}) end
    end
    return out
end

-- {id, built, closed} of the building of `kind` at a tile, or nil.
local function building_info(x, y, z, kind)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b then return nil end
    local okt, t = pcall(function() return df.building_type[b:getType()] end)
    if kind and (not okt or t ~= kind) then return nil end
    local closed
    pcall(function() closed = b.gate_flags.closed end)
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage(), closed = closed}
end

-- (0.100, review) a pull already waiting for a dwarf: a second one queued
-- now would undo it (two pulls shut the floodgate and open it again)
function lever_pull_pending(lever_id)
    local ok, yes = pcall(function()
        local b = df.building.find(lever_id)
        for _, j in ipairs(b and b.jobs or {}) do
            if j.job_type == df.job_type.PullLever then return true end
        end
        return false
    end)
    return ok and yes
end

-- (0.105.33 L5) Every PullLever job queued on the lever taken away (a dwarf
-- on the way would toggle the gate back after an instant pull). The count.
function cancel_lever_pulls(lever_id)
    local n = 0
    pcall(function()
        local b = df.building.find(lever_id)
        local jobs = {}
        for _, j in ipairs(b and b.jobs or {}) do
            if j.job_type == df.job_type.PullLever then table.insert(jobs, j) end
        end
        for _, j in ipairs(jobs) do
            if pcall(dfhack.job.removeJob, j) then n = n + 1 end
        end
    end)
    return n
end

-- instant: the lever acts now, no dwarf needed (DFHack's lever --instant),
-- for a flood in the fort, when the lever may stand in the water
function pull(lever_id, instant)
    if not instant and lever_pull_pending(lever_id) then
        return true, 'a dwarf is already on the way to pull it', true
    end
    local args = {'lever', 'pull', '--id', tostring(lever_id)}
    if instant then table.insert(args, '--instant') end
    local out, rv = dfhack.run_command_silent(table.unpack(args))
    return rv == CR_OK, tostring(out or '')
end

-- Items of a kind the fort has: free (no building, job or trader holds them,
-- not forbidden) and reserved (a job holds them: a construction waiting is
-- getting its part).
function count_items(tname)
    local free, reserved = 0, 0
    pcall(function()
        for _, item in ipairs(df.global.world.items.other[tname]) do
            -- (0.105.36 D3) a part carried to its job is reserved, not uncounted
            if not item_held(item, item.flags.in_job and {held = true} or nil) then
                if item.flags.in_job then reserved = reserved + 1 else free = free + 1 end
            end
        end
    end)
    return free, reserved
end

-- (0.104.94) What lies on the water's way in: each tunnel tile, the plug and
-- the source (shape and depth, or ice): Teacheroar's cistern sat at 0/7 for
-- hours with nothing to say why.
function cistern_path(p)
    local z = p.intake_z or p.cistern.z
    local function desc(pt)
        local t = pt and tile_info(pt.x, pt.y, z)
        if not t then return '?' end
        if t.material == 'FROZEN_LIQUID' then return 'ice' end
        local sh = tostring(t.shape):lower()
        if sh == 'wall' then sh = 'wall (' .. tostring(t.material):lower() .. (t.designated and ', marked' or '') .. ')' end
        return t.liquid and (sh .. ' ' .. t.depth .. '/7') or sh
    end
    local tunnel = {}
    for i = 1, #(p.tunnel_path or {}) - 1 do table.insert(tunnel, desc(p.tunnel_path[i])) end
    return {tunnel = tunnel, plug = desc(p.plug), source = desc(p.water)}
end

local function path_words(path)
    return ('tunnel %s; plug %s; source %s'):format(#path.tunnel > 0 and table.concat(path.tunnel, ', ') or 'none',
                                                    path.plug, path.source)
end

-- How it stands: stage, depth in the cistern's middle, the floodgate's state.
function cistern_status()
    local d = cistern_data()
    if not d then return nil end
    local p = d.plan
    local t = tile_info(p.well.x, p.well.y, p.cistern.z)
    local gate = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
    local out = {stage = d.stage, depth = t and t.liquid and t.depth or 0, source = p.source,
            gate = gate and (gate.built and (gate.closed and 'shut' or 'open') or 'planned') or nil,
            elevation = ez(p.cistern.z), x = p.well.x, y = p.well.y,
            -- (0.104.145) the design, where the water comes from, a leak seen
            v = p.v or 1, intake_elevation = p.intake_z and ez(p.intake_z) or nil, shaft = p.shaft and true or nil,
            source_why = p.source_why, leak = d.leak, unsealed = d.unsealed,
            -- (0.105.35) the leaks seen, the game's refusals to close a gap, the relink rounds asked
            leaks = math.tointeger(d.leaks) or nil, unsealed_refusals = math.tointeger(d.unsealed_refusals) or nil,
            relink_rounds = math.tointeger(d.relink_rounds) or nil,
            -- (0.104.168) why the AI can't close a gap itself (the player's then),
            -- and how many walls/floors it placed to close them
            unsealed_why = d.unsealed and d.unsealed_why or nil, sealing = nil}
    if d.unsealed and type(d.sealing) == 'table' then
        local n = 0
        for _ in pairs(d.sealing) do n = n + 1 end
        out.sealing = n > 0 and n or nil
    end
    if d.stage == 'filling' or d.stage == 'plug' then
        local okp, path = pcall(cistern_path, p)
        out.path = okp and path or nil
    end
    -- (0.104.145, review) every report while water can come in: still closed?
    -- (a dig beside the shaft or tunnel later floods that level)
    if gate and gate.built and not gate.closed then
        local oks, sealed, where = pcall(cistern_sealed, p, d.stage)
        if oks then
            out.sealed_now = sealed == true
            out.unsealed = (sealed ~= true) and where or d.unsealed
        end
    end
    -- (0.92.1) while its parts wait: the lever's state, and the floodgates and
    -- mechanisms there are (free, or taken by a job): the floodgate waited two
    -- years in region2 for a floodgate nobody made, the lever for a mechanism
    if d.stage == 'building' or d.stage == 'linking' then
        local lever = p.lever and building_info(p.lever.x, p.lever.y, p.well.z, 'Trap')
        out.lever = lever and (lever.built and 'built' or 'planned') or nil
        -- (0.104.141) the relinks asked for, whether linked, where the lever and
        -- the gate are, and why DF dropped the last link job (when it said)
        if d.stage == 'linking' then
            out.relinks = math.tointeger(d.relinks) or 0
            pcall(function()
                local lv = df.building.find(d.lever_id)
                for _, j in ipairs(lv and lv.jobs or {}) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then
                        out.link_pending = true
                        -- (0.104.143) whether a dwarf has taken it, or it is suspended
                        out.link_worker = dfhack.job.getWorker(j) ~= nil
                        out.link_suspended = j.flags.suspend or nil
                    end
                end
            end)
            -- (0.104.143) can the dwarves get beside the lever and the floodgate
            -- (a linker carries the mechanisms to both)?
            local function reach(x, y, z)
                local groups = {}
                pcall(function()
                    for _, u in ipairs(dfhack.units.getCitizens(true)) do
                        local g = dfhack.maps.getWalkableGroup(xyz2pos(dfhack.units.getPosition(u)))
                        if g and g ~= 0 then groups[g] = true end
                    end
                end)
                local seen = false
                for dy = -1, 1 do
                    for dx = -1, 1 do
                        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x + dx, y + dy, z))
                        if okg and g and g ~= 0 then
                            if groups[g] then return 'reachable' end
                            seen = true
                        end
                    end
                end
                return seen and 'cut off from the dwarves' or 'no open ground beside it'
            end
            pcall(function()
                if p.lever then out.lever_reach = reach(p.lever.x, p.lever.y, p.well.z) end
                out.gate_reach = reach(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z)
            end)
            out.link_why = d.link_why
            -- (0.104.143) with the elevation the game's screen shows (e)
            out.lever_at = p.lever and {x = p.lever.x, y = p.lever.y, z = p.well.z, e = ez(p.well.z)} or nil
            out.gate_at = {x = p.floodgate.x, y = p.floodgate.y, z = p.intake_z or p.cistern.z, e = ez(p.intake_z or p.cistern.z)}
            pcall(function()
                for _, lid in ipairs(reqscript('ai-gates').lever_links()[d.gate_id] or {}) do
                    if lid == d.lever_id then out.linked = true end
                end
            end)
        end
        out.floodgates_free, out.floodgates_reserved = count_items('FLOODGATE')
        -- (0.94.1) counted as the lever's link takes them (ai-gates), with
        -- what holds the ones it can't use
        local okg, mc = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
        if okg and mc then
            out.mechanisms_free, out.mechanisms_reserved = mc.usable, mc.reserved
            if next(mc.why) then out.mechanisms_held = mc.why end
        else
            out.mechanisms_free, out.mechanisms_reserved = count_items('TRAPPARTS')
        end
    end
    return out
end

-- Shut the cistern's floodgate now (a flood in the fort), whatever the stage.
-- (0.105.35) nothing waits for the player. The brain retires a cistern that
-- leaked twice, whose gap the game won't let the AI close, or whose lever
-- won't stay linked: its floodgate shut at once (when a lever is linked), the
-- cistern put with the retired ones (its tiles' items stay forbidden) and
-- the next one planned afresh (its dug room no longer counts as solid rock).
-- At most CISTERN_RETIRE_MAX retired so; a dry run changes nothing.
CISTERN_RETIRE_MAX = 3
function cistern_retire(dry_run, why)
    local d = cistern_data()
    if not d then return {ok = false, rejected = true, error = 'no cistern to retire'} end
    local old = site_get(CISTERN_KEY .. '/retired', {})
    local by_ai = 0
    for _, r in ipairs(old) do if r.by_ai then by_ai = by_ai + 1 end end
    local p = d.plan
    local gate = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
    if by_ai >= CISTERN_RETIRE_MAX then
        -- (v35 nit) its floodgate shut, as said (not on a dry run)
        local shut = gate and gate.built and gate.closed
        if not dry_run and gate and gate.built and not gate.closed and d.lever_id then
            if lever_pull_pending(d.lever_id) then cancel_lever_pulls(d.lever_id) end
            shut = pull(d.lever_id, true) and true or false
        end
        return {ok = false, rejected = true,
                error = ('the AI has retired %d cisterns already: this one is left as it is, its floodgate %s')
                        :format(by_ai, shut and 'shut' or 'not shut (no lever linked to it)')}
    end
    -- (0.105.36 D3) retired only with its floodgate shut (as the first-design
    -- retire): nothing watches that floodgate once it is retired
    if gate and gate.built and not gate.closed and not d.lever_id then
        return {ok = false, rejected = true, needs_player = true,
                error = 'the cistern\'s floodgate is open and no lever is linked to it: the AI can\'t shut it, so it '
                        .. 'is not retired (it keeps watching it); shut it by hand'}
    end
    if dry_run then return {ok = true, dry_run = true, retire = true} end
    if gate and gate.built and not gate.closed then
        if lever_pull_pending(d.lever_id) then cancel_lever_pulls(d.lever_id) end
        local okp, out = pull(d.lever_id, true)
        local g2 = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
        if not okp and not (g2 and g2.closed) then
            return {ok = false, error = 'the cistern\'s floodgate would not shut (lever pull failed: '
                        .. tostring(out) .. '): it is not retired until it is shut'}
        end
    end
    table.insert(old, {cistern = p.cistern, source = p.source, tunnel_path = p.tunnel_path, intake_z = p.intake_z,
                       shaft = p.shaft, why = type(why) == 'string' and why:sub(1, 120) or 'retired by the AI',
                       by_ai = true, at = game_tick()})
    site_put(CISTERN_KEY .. '/retired', old)
    site_put(CISTERN_KEY, {})
    return {ok = true, stage = 'retired', retired = true,
            error = 'the cistern retired (' .. (why or 'by the AI') .. '), its floodgate shut: another is planned next'}
end

-- (0.105.35) the lever's link lost 3 times: asked for afresh (another 3
-- tries), CISTERN_RELINK_MAX rounds at most; a dry run changes nothing
CISTERN_RELINK_MAX = 2
function cistern_relink(dry_run)
    local d = cistern_data()
    if not d or d.stage ~= 'linking' then return {ok = false, rejected = true, error = 'no cistern lever being linked'} end
    local rounds = math.tointeger(d.relink_rounds) or 0
    if rounds >= CISTERN_RELINK_MAX then
        return {ok = false, rejected = true, error = 'the lever link was asked afresh ' .. rounds .. ' times already'}
    end
    if dry_run then return {ok = true, dry_run = true, relink = true} end
    d.relinks, d.relink_rounds = 0, rounds + 1
    save_cistern(d)
    return {ok = true, stage = d.stage, relink = true,
            error = ('the lever link asked for afresh (round %d of %d)'):format(rounds + 1, CISTERN_RELINK_MAX)}
end

function cistern_shut(dry_run)
    local d = cistern_data()
    if not d or not d.lever_id then return {ok = false, rejected = true, error = 'no cistern lever linked yet'} end
    local p = d.plan
    local gate = building_info(p.floodgate.x, p.floodgate.y, p.intake_z or p.cistern.z, 'Floodgate')
    -- (0.105.33 L5) a refill or shut pull queued for a dwarf is taken away
    -- first: walked to after the instant shut, it would open the gate again
    local pending = lever_pull_pending(d.lever_id)
    if gate and gate.closed and pending then
        if dry_run then return {ok = true, dry_run = true, cancel_pull = true} end
        local n = cancel_lever_pulls(d.lever_id)
        return {ok = n > 0, shut = true, cancelled_pulls = n,
                error = n == 0 and 'the pull queued on the lever could not be taken away' or nil}
    end
    if not gate or gate.closed then return {ok = false, rejected = true, error = 'the floodgate is already shut'} end
    if dry_run then return {ok = true, dry_run = true} end
    if pending then cancel_lever_pulls(d.lever_id) end
    -- (0.100, review) at once: a queued pull waits for a dwarf to wade to
    -- the lever, and the planner asks again every cycle while dwarves are wet
    local ok, out = pull(d.lever_id, true)
    return {ok = ok, shut = ok, instant = true, error = not ok and out or nil}
end

-- (0.104.0) The cistern's room and its tunnel (all but the plug), the tiles
-- the water fills first.
function cistern_inside(p, z)
    local out = room_tiles(p.cistern)
    for i = 1, #p.tunnel_path - 1 do table.insert(out, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y}) end
    return out
end

-- (0.104.145) The tunnel's tiles (all but the plug), on the source's level.
function cistern_way(p)
    local out = {}
    for i = 1, #(p.tunnel_path or {}) - 1 do table.insert(out, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y}) end
    return out
end

-- How many living creatures stand on these tiles of level z.
function units_on_tiles(tiles, z)
    local set = {}
    for _, t in ipairs(tiles) do set[t.x .. ',' .. t.y] = true end
    local n = 0
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if u.pos.z == z and set[u.pos.x .. ',' .. u.pos.y] and not dfhack.units.isDead(u) then n = n + 1 end
        end
    end)
    return n
end

-- Items lying on these tiles of level z forbidden (nobody fetches them); how many.
function forbid_items_on(tiles, z)
    local n = 0
    for _, t in ipairs(tiles) do
        pcall(function()
            local block = dfhack.maps.getTileBlock(xyz2pos(t.x, t.y, z))
            if not block then return end
            for _, id in ipairs(block.items) do
                local it = df.item.find(id)
                if it and it.pos.x == t.x and it.pos.y == t.y and it.pos.z == z and it.flags.on_ground then
                    if not it.flags.forbid then it.flags.forbid = true; n = n + 1 end
                end
            end
        end)
    end
    return n
end

-- (0.104.168) THE PLAYER'S RULE: what the AI can set up in the game it does
-- itself. Teacheroar's cistern waited 20+ steps on "the cistern's shaft is
-- open at x105 y128" for the player to wall it. Now the AI builds the wall
-- (or, over the room, the tunnel and the shaft's top, a floor) at each open
-- spot itself, but never:
--   - in water, on a building, or on a stair or a ramp (a way up or down the
--     dwarves may walk: the player decides those);
--   - where the wall would cut a way: the open tile's walkable neighbours
--     (the cistern's own tiles left out) must still meet round it without it;
--   - with anyone on the tile, or in a hollow the wall would close off (a
--     pocket with no way off its level but through the gap).
-- Any open tile beside the shaft, the tunnel or the room lets the water out
-- (the shaft and tunnel are under pressure), so every gap is one to close.
CISTERN_GAP_WALL_ON = {FLOOR = true, EMPTY = true, PEBBLES = true, BOULDER = true, SHRUB = true, SAPLING = true}
CISTERN_GAP_POCKET_MAX = 400       -- tiles looked at beyond a gap
-- (0.104.168, review) ground a dwarf can stand on (open air and deep water are not)
CISTERN_STANDABLE = {FLOOR = true, PEBBLES = true, BOULDER = true, SHRUB = true, SAPLING = true, TWIG = true,
                     STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true, RAMP_TOP = true,
                     BROOK_BED = true}
-- ...and of those, the ways off the level
CISTERN_WAY_OFF = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true, RAMP_TOP = true}
local function standable(t)
    return t ~= nil and CISTERN_STANDABLE[tostring(t.shape)] == true and not (t.liquid and (t.depth or 0) >= 4)
end

-- Is a construction (a wall or floor being built, by the AI or the player) on this tile?
function construction_at(x, y, z)
    local ok, yes = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        return b ~= nil and b:getType() == df.building_type.Construction
    end)
    return ok and yes == true
end

-- Can the AI close this gap, and how: 'build' (with the quickfort text),
-- 'building' (its construction already placed), 'wait' (someone is in the
-- way) or 'no' (the player's), with why. (0.104.168, review) `recheck`: the
-- AI's own wall is placed and waits for a builder: is it still safe to finish?
function cistern_gap_plan(p, g, inside_set, recheck)
    local t = tile_info(g.x, g.y, g.z)
    if not t then return 'no', 'off the map' end
    if t.liquid then return 'no', 'water stands there' end
    if t.building and not recheck then return 'building', 'a construction or building stands there' end
    if not g.fix then return 'no', 'only a stair or a dug way can be there' end
    local sh = tostring(t.shape)
    if g.fix == 'floor' and sh ~= 'EMPTY' then
        return 'no', ('it is %s (a way the dwarves walk, or nothing a floor can be built on)'):format(sh:lower())
    end
    if g.fix == 'wall' and not CISTERN_GAP_WALL_ON[sh] then
        return 'no', ('it is %s (a way up or down the dwarves may walk)'):format(sh:lower())
    end
    if units_on_tiles({{x = g.x, y = g.y}}, g.z) > 0 then return 'wait', 'a creature stands there' end
    if g.fix == 'wall' then
        -- the gap's open neighbours on its level, the cistern's own tiles left out
        local function key(x, y) return x .. ',' .. y end
        -- (0.104.168, review) only ground a dwarf can stand on: never through open air or deep water
        local function open_at(x, y)
            if x == g.x and y == g.y then return false end
            if inside_set[key(x, y) .. ',' .. g.z] then return false end
            return standable(tile_info(x, y, g.z))
        end
        local starts = {}
        for _, e in ipairs(DIR8) do
            if open_at(g.x + e[1], g.y + e[2]) then table.insert(starts, {x = g.x + e[1], y = g.y + e[2]}) end
        end
        if #starts > 0 then
            -- one walk from the first neighbour: it must meet every other one
            -- (else the wall cuts a way), and if it ends small with no way off
            -- the level it is a hollow: nobody may be in it
            local seen, queue, tiles, way_off, capped_ = {[key(starts[1].x, starts[1].y)] = true}, {starts[1]}, {}, false, false
            local i = 1
            while i <= #queue do
                local q = queue[i]; i = i + 1
                table.insert(tiles, q)
                if #tiles > CISTERN_GAP_POCKET_MAX then capped_ = true break end
                -- a way off the level: a stair or a ramp, or the surface's open ground
                -- (never a channel or open air: no dwarf walks off through it)
                local qt = tile_info(q.x, q.y, g.z)
                if qt and (CISTERN_WAY_OFF[tostring(qt.shape)] or qt.outside) then
                    way_off = true
                end
                for _, e in ipairs(DIR8) do
                    local nx, ny = q.x + e[1], q.y + e[2]
                    if not seen[key(nx, ny)] and open_at(nx, ny) then
                        seen[key(nx, ny)] = true
                        table.insert(queue, {x = nx, y = ny})
                    end
                end
            end
            for _, s0 in ipairs(starts) do
                if not seen[key(s0.x, s0.y)] then
                    return 'no', capped_ and 'a wall there could cut a way the dwarves walk'
                                         or 'a wall there would cut a way the dwarves walk'
                end
            end
            -- (0.104.168, review) past the tiles looked at, unsure: only safe with
            -- a way off the level found (then it is no hollow); else the player's
            if capped_ and not way_off then
                return 'no', 'too much ground beyond it to be sure the wall shuts nobody in'
            end
            if not way_off and units_on_tiles(tiles, g.z) > 0 then
                return 'wait', 'someone is in the hollow beyond it (the wall would shut them in)'
            end
        end
    end
    return 'build', g.fix == 'wall' and 'Cw' or 'Cf'
end

-- (0.104.168, review) Take back a wall the AI placed that isn't built yet.
function cancel_construction(x, y, z)
    local ok, done = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if not b or b:getType() ~= df.building_type.Construction then return false end
        if b:getBuildStage() >= b:getMaxBuildStage() then return false end
        return dfhack.buildings.deconstruct(b)
    end)
    return ok and done and true or false
end

-- Close what the AI can of the cistern's gaps (cistern_sealed's list).
-- Returns the step's answer: a wait while walls/floors are being built, or
-- needs_player (with why) for a gap the AI must leave to the player.
function cistern_close_gaps(d, p, gaps, dry_run, save)
    local c, z = p.cistern, p.cistern.z
    local zi = p.intake_z or z
    local inside_set = {}
    for yy = c.y1, c.y2 do for xx = c.x1, c.x2 do inside_set[xx .. ',' .. yy .. ',' .. z] = true end end
    for _, t in ipairs(p.tunnel_path or {}) do inside_set[t.x .. ',' .. t.y .. ',' .. zi] = true end
    if p.shaft then for zz = z, zi do inside_set[p.shaft.x .. ',' .. p.shaft.y .. ',' .. zz] = true end end
    local placed, building, waiting, refused = {}, 0, nil, nil
    local by_z = {}
    for _, g in ipairs(gaps or {}) do
        local how, what = cistern_gap_plan(p, g, inside_set)
        local mine = (d.sealing and d.sealing[g.x .. ',' .. g.y .. ',' .. g.z]) or construction_at(g.x, g.y, g.z)
        if how == 'building' and mine then
            -- (0.104.168, review) still safe to finish? Someone gone into the
            -- hollow behind it since: the wall is taken back
            -- (one only passing over the tile: DF waits for it to step off itself)
            local how2, what2 = cistern_gap_plan(p, g, inside_set, true)
            if how2 == 'wait' and tostring(what2):find('hollow') then
                if not dry_run and cancel_construction(g.x, g.y, g.z) then
                    if d.sealing then d.sealing[g.x .. ',' .. g.y .. ',' .. g.z] = nil end
                end
                waiting = waiting or (g.words .. ': ' .. what2 .. '; the wall placed there is taken back')
            else
                building = building + 1
            end
        elseif how == 'building' or how == 'no' then
            refused = refused or (g.words .. ': ' .. what)
        elseif how == 'wait' then
            waiting = waiting or (g.words .. ': ' .. what)
        else
            by_z[g.z] = by_z[g.z] or {}
            table.insert(by_z[g.z], {x = g.x, y = g.y, z = g.z, text = what, g = g})
        end
    end
    for zz, cells in pairs(by_z) do
        for _, cell in ipairs(cells) do
            if dry_run or designate({{x = cell.x, y = cell.y, text = cell.text}}, zz, 'build') then
                table.insert(placed, cell)
            else
                refused = refused or (cell.g.words .. ': the game would not place a '
                                      .. (cell.text == 'Cw' and 'wall' or 'floor') .. ' there')
            end
        end
    end
    if not dry_run then
        d.sealing = d.sealing or {}
        for _, cell in ipairs(placed) do d.sealing[cell.x .. ',' .. cell.y .. ',' .. cell.z] = cell.text end
        d.unsealed_why = refused
        d.unsealed_refusals = refused and ((math.tointeger(d.unsealed_refusals) or 0) + 1) or nil   -- (0.105.35)
        d.unsealed = gaps and gaps[1] and gaps[1].words or d.unsealed
        save(d)
    end
    local walls, floors = 0, 0
    for _, cell in ipairs(placed) do if cell.text == 'Cw' then walls = walls + 1 else floors = floors + 1 end end
    local words = {}
    if walls > 0 then table.insert(words, walls .. ' wall(s)') end
    if floors > 0 then table.insert(words, floors .. ' floor(s)') end
    local where = gaps and gaps[1] and gaps[1].words or '?'
    if refused then
        return {ok = false, rejected = true, needs_player = true, unsealed = where,
                unsealed_why = refused, walls = walls, floors = floors, dry_run = dry_run or nil,
                error = 'the cistern is not closed where the water goes (' .. refused .. '): the AI can\'t close that itself'}
    end
    if #placed > 0 then
        return {ok = true, stage = d.stage, sealing = true, walls = walls, floors = floors, dry_run = dry_run or nil,
                error = ('the cistern is not closed where the water goes (%s): the AI builds %s there first')
                        :format(where, table.concat(words, ' and '))}
    end
    return {ok = false, rejected = true, waiting = true, stage = d.stage, unsealed = where,
            error = 'the cistern is not closed where the water goes (' .. where .. '): '
                    .. (waiting or (building .. ' wall(s)/floor(s) the AI placed are being built'))}
end

-- (r8) The top-level locals ai-builder-cistern-step.lua uses, handed on:
CISTERN_PART_LOCALS.save_cistern, CISTERN_PART_LOCALS.game_tick, CISTERN_PART_LOCALS.room_tiles = save_cistern, game_tick, room_tiles
CISTERN_PART_LOCALS.building_info, CISTERN_PART_LOCALS.path_words = building_info, path_words
