-- ai-builder-wagonroad: the deep depot's built road, checked for the wagons and mended;
-- the depot's steps and status.
--
-- A part of ai-builder, not a script of its own (r8, split out of
-- ai-builder-surface.lua when it was 126 KB): ai-builder.lua loads it into its
-- own environment right after ai-builder-deepdepot, so every name here is
-- reqscript('ai-builder').name and the helpers defined there (info,
-- quickfort_apply, ...) are in reach. The local helpers it shares
-- with ai-builder-deepdepot come from DEPOT_PART_LOCALS.

if not PARTS then qerror('ai-builder-wagonroad is a part of ai-builder; run ai-builder') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-wagonroad'] = '0.105.134'   -- bumped with BRIDGE_VERSION

local info, ez = info, ez
local save_deep_depot, deep_now, wagon_ground, building_blocks = DEPOT_PART_LOCALS.save_deep_depot, DEPOT_PART_LOCALS.deep_now, DEPOT_PART_LOCALS.wagon_ground, DEPOT_PART_LOCALS.building_blocks
local wagon_look, deep_dir, deep_depot_building = DEPOT_PART_LOCALS.wagon_look, DEPOT_PART_LOCALS.deep_dir, DEPOT_PART_LOCALS.deep_depot_building
local any_depot, depot_built, deep_dig_left = DEPOT_PART_LOCALS.any_depot, DEPOT_PART_LOCALS.depot_built, DEPOT_PART_LOCALS.deep_dig_left

-- --- (0.105.30) the built road, checked for the wagons ---------------------------
--
-- deep_wagon_check(d): the AI's best guess at what stops the wagons, along
-- its own road in the order a wagon drives it: the two rows of ground in
-- front of the mouth, the channel's open tops, the ramps, the road's floor,
-- the hall; then the way over the surface from the mouth to the map's edge.
-- {state = 'clear'|'blocked'|'unknown', block = {x, y, z, what, text, fix,
-- key, id, pending, tiles}, opens = {x, y, z}}. fix: 'fell' (a tree),
-- 'smooth' (a boulder), 'redig' (key: h channel, r ramp, d floor), 'remove'
-- (a door, hatch, trap... on the AI's own road), or nil (a Needs you).
-- opens: where the hall or road opens into the fort (it shouldn't: then a
-- door there guards the fort, and is not the AI's to take away).
local DEEP_WANT = {h = 'the ramp\'s open top', ramp = 'a ramp', d = 'dug floor'}
DEEP_REMOVING = DEEP_REMOVING or {}      -- building id -> true: its removal was ordered
DEEP_CHECK = DEEP_CHECK or {}            -- {tick, at, res}: the report's last check

-- (tests replace this) take a building down: DFHack's own call
function remove_building(id)
    local ok, r = pcall(function()
        local b = df.building.find(id)
        if not b then return false end
        dfhack.buildings.deconstruct(b)
        return true
    end)
    return ok and r == true
end

local function shape_words(t)
    if not t then return 'off the map' end
    if is_tree(t) then return 'a tree' end
    local s = tostring(t.shape)
    if s == 'WALL' then return t.material == 'CONSTRUCTION' and 'a built wall' or 'solid rock' end
    if s == 'EMPTY' then return 'open space' end
    if s == 'RAMP_TOP' then return 'a ramp\'s open top' end
    return s:lower():gsub('_', ' ')
end

function deep_wagon_check(d)
    local cache = {}
    local function info(x, y, z)
        local k = (z * 4096 + y) * 4096 + x
        local v = cache[k]
        if v == nil then v = tile_info(x, y, z) or false; cache[k] = v end
        return v or nil
    end
    local look = wagon_look(info)
    local dir = d and deep_dir(d)
    if not (dir and d.start and d.tiles and d.depot) then
        return {state = 'unknown', why = 'the road\'s plan is not in the save'}
    end
    local function k3(x, y, z) return (z * 4096 + y) * 4096 + x end
    local px, py = -dir[2], dir[1]
    local sx, sy, sz = d.start.x, d.start.y, d.start.z
    local plan = {}
    for _, p in ipairs(d.tiles) do plan[k3(p.x, p.y, p.z)] = p.r end
    -- where the hall or road opens into anything walkable that isn't its own
    local opens
    for _, p in ipairs(d.tiles) do
        if p.z < sz and not opens then
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local x, y = p.x + dx, p.y + dy
                    if not opens and (dx ~= 0 or dy ~= 0) and not plan[k3(x, y, p.z)] and look.group(x, y, p.z) ~= 0 then
                        local t = info(x, y, p.z)
                        -- (the rock round the ramps' foot is walked over from the surface: not an opening)
                        if t and t.shape ~= 'WALL' then opens = {x = x, y = y, z = p.z} end
                    end
                end
            end
        end
    end
    -- (0.105.30 fixes) and up or down from it: a stair (or a ramp, or a
    -- channel) out of the hall or road to a level that isn't the road's own
    -- (a stair down from the hall's floor into the fort)
    local UP = {STAIR_UP = true, STAIR_UPDOWN = true}
    local DOWN = {STAIR_DOWN = true, STAIR_UPDOWN = true}
    local function walk_tile(x, y, z)
        if plan[k3(x, y, z)] then return nil end
        local t = info(x, y, z)
        if not t or t.shape == 'WALL' or t.shape == 'EMPTY' then return nil end
        return t
    end
    for _, p in ipairs(d.tiles) do
        if opens then break end
        if p.z < sz then
            local t = info(p.x, p.y, p.z)
            local shape = t and t.shape
            if shape and DOWN[shape] then
                local dn = walk_tile(p.x, p.y, p.z - 1)
                if dn and UP[dn.shape] then opens = {x = p.x, y = p.y, z = p.z - 1} end
            end
            if not opens and shape and UP[shape] and p.z + 1 < sz then
                local up = walk_tile(p.x, p.y, p.z + 1)
                if up and DOWN[up.shape] then opens = {x = p.x, y = p.y, z = p.z + 1} end
            end
            if not opens and (shape == 'RAMP_TOP' or shape == 'EMPTY') and p.r ~= 'h' then
                -- the hall's floor channelled or holed: what is under it
                if walk_tile(p.x, p.y, p.z - 1) then opens = {x = p.x, y = p.y, z = p.z - 1} end
            end
            if not opens and shape == 'RAMP' and p.z + 1 < sz then
                -- a ramp of the road leads up beside it: to a level of the fort?
                for dx = -1, 1 do
                    for dy = -1, 1 do
                        if not opens and (dx ~= 0 or dy ~= 0) then
                            local up = walk_tile(p.x + dx, p.y + dy, p.z + 1)
                            if up and not up.outside and up.shape ~= 'RAMP_TOP' then
                                opens = {x = p.x + dx, y = p.y + dy, z = p.z + 1}
                            end
                        end
                    end
                end
            end
        end
    end
    local function block(x, y, z, what, fix, extra)
        local b = {x = x, y = y, z = z, elevation = ez(z), what = what, fix = fix}
        for k, v in pairs(extra or {}) do b[k] = v end
        b.text = b.text or ('%s at x%d y%d elevation %d on the depot road'):format(what, x, y, ez(z))
        local t = info(x, y, z)
        if fix == 'fell' or fix == 'redig' then
            b.pending = t ~= nil and t.designated == true
        elseif fix == 'smooth' then
            b.pending = t ~= nil and (t.smoothing == true or t.designated == true)
        elseif fix == 'remove' then
            b.pending = b.id ~= nil and DEEP_REMOVING[b.id] == true
        end
        return {state = 'blocked', block = b, opens = opens}
    end
    -- what a building on the AI's road does: removed only when the hall and
    -- road are found sealed from the fort on every level (no `opens`, above:
    -- the same level, stairs, ramps and holes). Opening into the fort,
    -- anything there may be closing the fort's passage (a door, hatch,
    -- floodgate, grate, bars, a bridge...): never the AI's to take away,
    -- a Needs you. (0.105.30 fixes) A bridge never: the wagon drawbridge
    -- the gates put on the road is raised at an alarm, and a raised one is
    -- the gate doing its work.
    local function building_fix(b)
        if opens or not b or not b.id then return nil end
        if b.kind == 'Bridge' then return nil end
        return 'remove'
    end
    -- 1. the ground in front of the mouth (u = -1, 0)
    for u = -1, 0 do
        for v = -1, 1 do
            local x, y = sx + u * dir[1] + v * px, sy + u * dir[2] + v * py
            local t = info(x, y, sz)
            local b = look.building(x, y, sz)
            local bb = building_blocks(b, t)
            if bb and bb ~= 'floored' then
                return block(x, y, sz, bb, nil, {id = b.id,
                    text = ('%s at x%d y%d elevation %d, in front of the depot road\'s mouth'):format(bb, x, y, ez(sz))})
            end
            local why = t and wagon_ground(t) or (not t and 'off the map') or nil
            if not why and t and (t.shape == 'WALL' or is_tree(t)) then why = shape_words(t) end
            if why then
                local fix = (t and is_tree(t)) and 'fell' or (t and t.shape == 'BOULDER') and 'smooth' or nil
                return block(x, y, sz, why, fix,
                    {text = ('%s at x%d y%d elevation %d, in front of the depot road\'s mouth'):format(why, x, y, ez(sz))})
            end
        end
    end
    -- 2. the road and the hall, as dug (the plan's own order: down the road)
    for _, p in ipairs(d.tiles) do
        local t = info(p.x, p.y, p.z)
        local b = look.building(p.x, p.y, p.z)
        local bb = building_blocks(b, t)
        if bb and bb ~= 'floored' then
            return block(p.x, p.y, p.z, bb, building_fix(b), {id = b.id, kind = b.kind})
        end
        local shape = t and t.shape
        if p.r == 'h' then
            if shape == 'EMPTY' then
                local dn = info(p.x, p.y, p.z - 1)
                return block(p.x, p.y, p.z, 'open space where a ramp\'s top should be (no ramp under it)',
                    (dn and dn.shape == 'WALL') and 'redig' or nil, {key = 'r', at = {x = p.x, y = p.y, z = p.z - 1}})
            elseif shape ~= 'RAMP_TOP' then
                return block(p.x, p.y, p.z, ('%s where %s should be'):format(shape_words(t), DEEP_WANT.h),
                    (shape == 'WALL' or GROUND[shape or '']) and 'redig' or nil, {key = 'h'})
            end
        elseif p.r == 'ramp' then
            if shape ~= 'RAMP' then
                local good = 0
                for _, q in ipairs(d.tiles) do
                    if q.r == 'ramp' and q.z == p.z then
                        local qt = info(q.x, q.y, q.z)
                        if qt and qt.shape == 'RAMP' then good = good + 1 end
                    end
                end
                return block(p.x, p.y, p.z, ('%s where a ramp should be'):format(shape_words(t)),
                    shape == 'WALL' and 'redig' or nil, {key = 'r',
                    text = ('the ramp at x%d y%d elevation %d is %s, so the ramp row is %d wide (a wagon needs 3)')
                        :format(p.x, p.y, ez(p.z), shape_words(t), good)})
            end
        else
            if shape == 'WALL' then
                return block(p.x, p.y, p.z, 'solid rock where the road\'s floor should be', 'redig', {key = 'd'})
            end
            local why = t and wagon_ground(t) or (not t and 'off the map') or nil
            if why then
                return block(p.x, p.y, p.z, why, shape == 'BOULDER' and 'smooth' or nil)
            end
        end
    end
    -- 3. from the mouth over the surface to the map's edge
    local g = look.group(sx, sy, sz)
    if g == 0 then
        return block(sx, sy, sz, ('%s at the road\'s start'):format(shape_words(info(sx, sy, sz))), nil)
    end
    local seeds, skip = {}, {}
    for v = -1, 1 do table.insert(seeds, {x = sx + v * px, y = sy + v * py, z = sz}) end
    for _, p in ipairs(d.tiles) do skip[k3(p.x, p.y, p.z)] = true end
    local res = wagon_reaches_edge(look, seeds, g, skip)
    if res.reached then return {state = 'clear', opens = opens} end
    if res.cut then return {state = 'unknown', opens = opens, why = 'the way to the map\'s edge is too long to check'} end
    local first = res.blocks and res.blocks[1]
    if not first then
        return block(sx, sy, sz, 'no room to turn', nil, {text = ('no 3-wide way for wagons from the depot road\'s '
            .. 'mouth at x%d y%d elevation %d to the map\'s edge'):format(sx, sy, ez(sz))})
    end
    local tiles = {}
    for _, b in ipairs(res.blocks) do
        if b.fix == first.fix and first.fix and #tiles < DEEP_FIX_MAX then
            table.insert(tiles, {x = b.x, y = b.y, z = b.z})
        end
    end
    return block(first.x, first.y, first.z, first.what, first.fix, {id = first.b and first.b.id,
        tiles = #tiles > 0 and tiles or nil,
        text = ('%s at x%d y%d elevation %d, on the wagons\' way from the depot road\'s mouth (x%d y%d) to the '
                .. 'map\'s edge (no 3-wide way past it)'):format(first.what, first.x, first.y, ez(first.z), sx, sy)})
end

-- The block for the report: {x, y, elevation, what, text, fix, pending}.
local function block_report(b)
    if not b then return nil end
    return {x = b.x, y = b.y, elevation = b.elevation, what = b.what, text = b.text, fix = b.fix,
            pending = b.pending or nil}
end

-- Clear a block: the number of tiles marked (or buildings taken down).
local function deep_fix(b)
    local n = 0
    if b.fix == 'fell' then
        for _, p in ipairs(b.tiles or {b}) do
            local t = tile_info(p.x, p.y, p.z)
            if t and is_tree(t) and not t.designated and fell_tree(p.x, p.y, p.z) then n = n + 1 end
        end
    elseif b.fix == 'smooth' then
        for _, p in ipairs(b.tiles or {b}) do
            local ok = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 's'}}, p.z, p.x, p.y)
            if ok then n = n + 1 end
        end
    elseif b.fix == 'redig' then
        local at = b.at or b
        local ok = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = b.key or 'd'}}, at.z, at.x, at.y)
        if ok then n = 1 end
    elseif b.fix == 'remove' and b.id then
        if remove_building(b.id) then DEEP_REMOVING[b.id] = true; n = 1 end
    end
    return n
end

local FIX_WORDS = {fell = 'tree(s) marked for felling', smooth = 'boulder(s) marked for smoothing',
                   redig = 'tile(s) marked for digging again', remove = 'building(s) taken down'}

-- The report's check, kept for an in-game day (the surface walk is not free).
local function deep_check_cached(d)
    local now = deep_now() or 0
    local at = d.depot and ('%s,%s,%s'):format(d.depot.x, d.depot.y, d.depot.z) or ''
    local c = DEEP_CHECK
    if c.res and c.at == at and c.tick and now >= c.tick and now - c.tick < DEEP_WAGON_CHECK_TICKS then return c.res end
    local ok, res = pcall(deep_wagon_check, d)
    res = ok and res or {state = 'unknown', why = tostring(res)}
    DEEP_CHECK = {tick = now, at = at, res = res}
    return res
end

-- The report's view, once begun: {stage, x, y, elevation, levels, road,
-- tiles_left, stalled, depot = none|building|built, wagon_access, why}.
-- (0.105.30) built and the wagons not known to get there: dfhack_wagon_access
-- (DFHack's own check), wagon_check (clear|blocked|unknown), wagon_block
-- ({x, y, elevation, what, text, fix, pending}), opens_fort ({x, y, elevation}).
function deep_depot_status()
    local d = deep_depot_data()
    if not d then return nil end
    if d.stage == 'no_road' then
        local now = deep_now()
        if now and d.tick and now - d.tick >= DEEP_DEPOT_RETRY_TICKS then return nil end
        return {stage = 'no_road', why = d.why}
    end
    local out = {stage = d.stage, levels = d.levels, road = d.road}
    if d.depot then out.x, out.y, out.elevation = d.depot.x, d.depot.y, ez(d.depot.z) end
    local left, stalled = deep_dig_left(d)
    out.tiles_left, out.stalled = left, #stalled
    if d.stage == 'placed' then
        local b = deep_depot_building(d)
        if not b then
            out.depot = 'none'
        else
            local built = depot_built(b)
            out.depot = built == false and 'building' or 'built'
            if built ~= false then out.wagon_access = depot_wagon_access(b) end
            if built ~= false and out.wagon_access ~= true then
                out.dfhack_wagon_access = dfhack_wagon_access()
                if out.dfhack_wagon_access ~= true then
                    local chk = deep_check_cached(d)
                    out.wagon_check = chk.state
                    out.wagon_block = block_report(chk.block)
                    if chk.opens then
                        out.opens_fort = {x = chk.opens.x, y = chk.opens.y, elevation = ez(chk.opens.z)}
                    end
                end
            end
        end
    end
    return out
end

-- One step of the underground depot (see above).
function place_deep_depot(dry_run)
    OFFSET = elevation_offset()
    local d = deep_depot_data()
    if d and d.stage == 'no_road' then
        local now = deep_now()
        if not (now and d.tick and now - d.tick >= DEEP_DEPOT_RETRY_TICKS) then
            return {ok = false, rejected = true, no_road = true,
                    error = 'no wagon road down was found (' .. tostring(d.why) .. '): the depot goes on the surface'}
        end
        d = nil
    end
    if not d then
        if any_depot() then
            return {ok = false, rejected = true, error = 'a trade depot already stands'}
        end
        local plan, why = find_deep_depot(level_areas())
        if not plan then
            if not dry_run then save_deep_depot({stage = 'no_road', why = why, tick = deep_now()}) end
            return {ok = false, rejected = true, no_road = true, error = why, dry_run = dry_run or nil}
        end
        local out = {ok = true, stage = 'digging', x = plan.depot.x, y = plan.depot.y,
                     elevation = ez(plan.depot.z), levels = plan.levels, road = plan.road,
                     tiles = #plan.tiles, start = {x = plan.start.x, y = plan.start.y, elevation = ez(plan.start.z)},
                     dry_run = dry_run or nil}
        if dry_run then return out end
        -- designated level by level, the surface first (the miners come down the road)
        local by_z, zs = {}, {}
        for _, p in ipairs(plan.tiles) do
            if p.r ~= 'ramp' then
                if not by_z[p.z] then by_z[p.z] = {}; table.insert(zs, p.z) end
                table.insert(by_z[p.z], {x = p.x, y = p.y, text = p.r})
            end
        end
        table.sort(zs, function(a, b) return a > b end)
        for _, z in ipairs(zs) do
            local okd, dry = pcall(quickfort_apply, 'dig', by_z[z], z, 0, 0, 'run', true)
            if not okd or stat(dry, 'dig_designated') < #by_z[z] then
                return {ok = false, error = ('the game would not designate the wagon road at elevation %d'):format(ez(z))}
            end
        end
        for _, z in ipairs(zs) do pcall(quickfort_apply, 'dig', by_z[z], z, 0, 0) end
        save_deep_depot({stage = 'digging', tiles = plan.tiles, depot = plan.depot, hall = plan.hall,
                         levels = plan.levels, road = plan.road, start = plan.start,
                         dir = {plan.dir[1], plan.dir[2]}})
        return out
    end
    if d.stage == 'digging' then
        local left, stalled = deep_dig_left(d)
        if left > 0 then
            if #stalled == 0 then
                return {ok = false, rejected = true, waiting = true, stage = 'digging', tiles_left = left,
                        error = ('the wagon road and depot hall are being dug: %d tile(s) left'):format(left)}
            end
            if dry_run then return {ok = true, stage = 'digging', redig = #stalled, dry_run = true} end
            local n = 0
            for i = 1, math.min(#stalled, DEEP_REDIG_MAX) do
                local s = stalled[i]
                local ok = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = s.key}}, s.z, s.x, s.y)
                if ok then n = n + 1 end
            end
            return {ok = n > 0, stage = 'digging', redig = n, tiles_left = left,
                    error = n == 0 and 'the game would not designate the road\'s lost tiles again' or nil}
        end
        d.stage = 'placed'          -- dug: the depot goes in (below)
    end
    -- placed: the depot in the hall's middle (again if it was taken down)
    local b = deep_depot_building(d)
    if b then
        local built, acc = depot_built(b), depot_wagon_access(b)
        local out = {ok = false, rejected = true, done = true, stage = 'placed',
                     depot = built == false and 'building' or 'built', wagon_access = acc,
                     error = 'the underground trade depot is placed'}
        -- (0.105.30) built, and the game doesn't say the wagons get there:
        -- the first thing in their way, cleared when the AI can
        if built == false or acc == true then return out end
        out.dfhack_wagon_access = dfhack_wagon_access()
        if out.dfhack_wagon_access == true then return out end
        local okc, chk = pcall(deep_wagon_check, d)
        if not okc then out.error = 'the wagons\' way could not be checked: ' .. tostring(chk) return out end
        DEEP_CHECK = {}                            -- the report looks again
        out.wagon_check = chk.state
        out.wagon_block = block_report(chk.block)
        if chk.state ~= 'blocked' then
            if chk.state == 'clear' then
                out.error = 'the underground trade depot is placed; the AI finds nothing in the wagons\' way'
            end
            return out
        end
        local blk = chk.block
        if blk.fix and not blk.pending then
            if dry_run then
                return {ok = true, stage = 'placed', fix = blk.fix, wagon_block = out.wagon_block, dry_run = true}
            end
            local n = deep_fix(blk)
            return {ok = n > 0, stage = 'placed', fixed = blk.fix, marked = n, wagon_block = out.wagon_block,
                    wagon_access = acc,
                    error = n == 0 and ('the game would not take the fix for ' .. blk.text) or nil,
                    note = n > 0 and ('%d %s: %s'):format(n, FIX_WORDS[blk.fix] or blk.fix, blk.text) or nil}
        elseif blk.fix then
            out.waiting = true
            out.error = 'the wagons\' way is being cleared: ' .. blk.text
        else
            out.needs_you = true
            out.error = 'the wagons can\'t reach the underground depot: ' .. blk.text .. ' (not the AI\'s to clear)'
        end
        return out
    end
    if any_depot() then return {ok = false, rejected = true, error = 'a trade depot already stands'} end
    local c = d.depot
    local good, failed = qf_try('build', {{x = 0, y = 0, text = 'D'}}, c.z, c.x, c.y, dry_run)
    if failed == 'dry' then
        return {ok = false, error = ('the game would not place the trade depot in the hall at x%d y%d elevation %d')
                    :format(c.x, c.y, ez(c.z))}
    elseif not good then
        return {ok = false, error = ('the game refused the trade depot at x%d y%d'):format(c.x, c.y)}
    end
    local out = {ok = true, stage = 'placed', x = c.x, y = c.y, elevation = ez(c.z), dry_run = dry_run or nil}
    if dry_run then return out end
    save_deep_depot(d)
    return out
end
