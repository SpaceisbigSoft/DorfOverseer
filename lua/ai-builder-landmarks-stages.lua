-- ai-builder-landmarks-stages: a landmark under way: the surface stages
-- (clearing, walls, floor, furnish, zone), the scaffolding taken down, the
-- openings in the rock cut in waves and railed, one step a call
-- (landmark_step), and the landmarks' report.
--
-- (r9) A part of ai-builder, not a script of its own: cut from ai-builder-landmarks.lua
-- (which had grown to 84 KB) at a section boundary, the code as it stood. ai-builder.lua
-- loads it into its own environment right after the part before it (PARTS), so every
-- name here is reqscript('ai-builder').name and the hub's helpers are in reach.
-- The top-level locals the ai-builder-landmarks files share come through
-- LANDMARKS_PART_LOCALS (the same functions).

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-landmarks-stages'] = '0.105.99'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, add = info, add
local save_landmarks, find_landmark = LANDMARKS_PART_LOCALS.save_landmarks, LANDMARKS_PART_LOCALS.find_landmark
local now_date = LANDMARKS_PART_LOCALS.now_date

---------------------------------------------------------------------------
-- The surface stages (landmark_step), on the pattern of place_hall
---------------------------------------------------------------------------

local BUILT_AS = {Cw = 'WALL', CF = 'FORTIFICATION', Cf = 'FLOOR', Cr = 'RAMP', Cu = 'STAIR_UP', Cd = 'STAIR_DOWN',
                  Cx = 'STAIR_UPDOWN'}

-- Cells still waiting to be built (planned): a construction waiting is a
-- building on its tile; a building waits while buildingplan finds its materials.
local function waiting(cells, z)
    local n = 0
    for _, c in ipairs(cells) do
        local t = tile_info(c.x, c.y, z)
        if BUILT_AS[c.text] then
            if t and t.building then n = n + 1 end
        elseif hall_planned_at(c.x, c.y, z) then
            n = n + 1
        end
    end
    return n
end

local function trees_standing(rec)
    local n = 0
    for _, t in ipairs(rec.trees or {}) do if is_tree(tile_info(t.x, t.y, t.z)) then n = n + 1 end end
    return n
end

-- (E2) Scaffolding: taking a tile down (a construction marked for removal)
-- and who stands where. Tests swap both.
function remove_construction(x, y, z, dry_run)
    if dry_run then return true end
    local ok, r = pcall(function() return dfhack.constructions.designateRemove(xyz2pos(x, y, z)) end)
    return ok and r and true or false
end

-- How many living units stand on these tiles ({x, y, z} each). (0.105.37
-- fix) Fails closed: nil when the units can't be read (the caller waits).
function units_on(tiles)
    local want = {}
    for _, t in ipairs(tiles) do want[(t.z * 4096 + t.y) * 4096 + t.x] = true end
    local ok, n = pcall(function()
        local c = 0
        for _, u in ipairs(df.global.world.units.active) do
            if not dfhack.units.isDead(u) then
                local x, y, z = dfhack.units.getPosition(u)
                if x and want[(z * 4096 + y) * 4096 + x] then c = c + 1 end
            end
        end
        return c
    end)
    if not ok or type(n) ~= 'number' then return nil end
    return n
end

-- (0.105.37 fix) The tiles a removal must find empty: each tile taken down,
-- the one over it (a dwarf on the stair's top), and the tiles it cuts off.
local function removal_tiles(st)
    local tiles = {}
    for _, c in ipairs(st.cells) do
        table.insert(tiles, {x = c.x, y = c.y, z = st.z})
        table.insert(tiles, {x = c.x, y = c.y, z = st.z + 1})
    end
    for _, c in ipairs(st.cut or {}) do table.insert(tiles, c) end
    return tiles
end

-- nil when the removal may go ahead, else the words and whether it is a
-- wait (a removal that cuts tiles off is refused, not waited on: an old
-- record's; the planner no longer makes them)
local function removal_blocked(st, name)
    if #(st.cut or {}) > 0 then
        return ('%s: taking this scaffolding down would cut %d tile(s) off; it stays up'):format(name, #st.cut), false
    end
    local ok, who = pcall(units_on, removal_tiles(st))
    if not ok or type(who) ~= 'number' then
        return ('%s: who stands on the scaffolding can\'t be read; it comes down when it can'):format(name), true
    end
    if who > 0 then
        return ('%s: %d dwarf(s) on or above the scaffolding; it comes down when they leave'):format(name, who), true
    end
    return nil
end

local STAIR_SHAPES = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true}

-- What a step still waits for: its tiles to be built (planned buildings
-- left), or (a removal) its scaffold stairs to come down.
local function step_left(st)
    if not st then return 0 end
    if st.kind == 'remove' then
        local n = 0
        for _, c in ipairs(st.cells) do
            local t = tile_info(c.x, c.y, st.z)
            if t and STAIR_SHAPES[t.shape] then n = n + 1 end
        end
        return n
    end
    return waiting(st.cells, st.z)
end

-- The scaffolding's state for the report: {columns, tiles, up, next, ready}.
-- up: its tiles placed and not yet taken down; next: the next step's kind;
-- ready: the current step is done (the next can be placed).
local function scaffold_state(rec)
    if type(rec.steps) ~= 'table' then return nil end
    local sc = type(rec.scaffold) == 'table' and rec.scaffold or {}
    local up = 0
    local k = math.tointeger(rec.step) or 0
    for i = 1, math.min(k, #rec.steps) do
        local st = rec.steps[i]
        if st.kind == 'scaffold' then up = up + #st.cells elseif st.kind == 'remove' then up = up - #st.cells end
    end
    local cur = rec.steps[k]
    if cur and cur.kind == 'remove' then up = up + step_left(cur) end
    local nxt = rec.steps[k + 1]
    local ok, left = pcall(step_left, cur)
    return {columns = sc.columns or 0, tiles = sc.tiles or 0, up = math.max(up, 0),
            next = nxt and nxt.kind or (k >= #rec.steps and k > 0 and 'furnish' or nil),
            ready = (rec.stage ~= 'clearing' and ok and left == 0) or nil}
end

-- (E1) Openings in the rock: cut in waves, then railed.

-- The openings and rails of a placed drawing, per level that has any, in map
-- coordinates: {level, z, waves = {{cells 'h'}...} (the first cut first),
-- wave = 0 (the last designated), rails = {cells 'CF'}, railed, tries}.
function open_plan(plan, a)
    local out = {}
    for k, lv in ipairs(plan.levels) do
        local waves, rails = {}, {}
        for _, c in ipairs(lv.L.open or {}) do
            local w = math.tointeger(c.wave) or 1
            waves[w] = waves[w] or {}
            table.insert(waves[w], {x = a.x + c.x, y = a.y + c.y, text = c.text})
        end
        for _, c in ipairs(lv.L.construct or {}) do
            table.insert(rails, {x = a.x + c.x, y = a.y + c.y, text = c.text})
        end
        if #waves > 0 or #rails > 0 then
            table.insert(out, {level = k, z = lv.z, waves = waves, wave = 0, rails = rails, railed = false, tries = 0})
        end
    end
    return out
end

local function phase_of(data, pid)
    for _, p in ipairs(data.list) do if p.id == pid then return p.phase end end
end

-- Is a channel cut? (the floor gone: open space, or a ramp's top)
local function cut_done(t)
    return t ~= nil and t.shape ~= 'WALL' and t.shape ~= 'FLOOR'
end

-- One level's openings: what they wait on, and what to do next.
-- Returns state ('dig' | 'ready' | 'waiting' | 'done') and the action when
-- ready ('wave' | 'redo' | 'rails'), with the cells to redo.
local function open_state(rec, e, data)
    if e.done then return 'done' end
    if e.stalled then return 'stalled' end
    local ids = rec.project_ids or {}
    local function dug(pid)      -- (a level closed long ago is no longer listed: dug)
        return pid ~= nil and phase_of(data, pid) ~= 'dig'
    end
    -- this level dug (the openings and rails are dug floor first), and the
    -- level below, which the openings open onto
    if not dug(ids[e.level]) then return 'dig' end
    if #e.waves > 0 and not dug(ids[e.level + 1]) then return 'dig' end
    if e.wave > 0 and e.wave <= #e.waves then
        local jobs = job_tiles()
        local left, lost = 0, {}
        for _, c in ipairs(e.waves[e.wave]) do
            local t = tile_info(c.x, c.y, e.z)
            if not cut_done(t) then
                left = left + 1
                if t and not t.designated and not jobs[c.x .. ',' .. c.y .. ',' .. e.z] then table.insert(lost, c) end
            end
        end
        if left > 0 and e.gave_up ~= e.wave then
            if #lost == left and (math.tointeger(e.tries) or 0) < OPEN_REDIG_MAX then return 'ready', 'redo', lost end
            if #lost < left then return 'waiting', 'wave' end
            -- given up on the lost ones: the rails go up, the rest stays floor
        end
    end
    if e.wave < #e.waves then return 'ready', 'wave' end
    if not e.railed then return 'ready', 'rails' end
    if #e.rails > 0 and waiting(e.rails, e.z) > 0 then return 'waiting', 'rails' end
    return 'done'
end

-- (0.105.37 fix) The openings' wait limit: a level waiting OPEN_WAIT_DAYS on
-- the same wave or rails has them designated again (OPEN_REDIG_MAX times);
-- then the wave is given up (the tiles not cut stay floor; the rails go up)
-- or the rails are 'stalled' (reported: the brain frees the slot; the rails
-- stay designated, never taken off). Changed: the record wants saving.
local function open_watch(rec, data, dry_run)
    local changed = false
    local now = now_tick()
    for _, e in ipairs(rec.open or {}) do
        local st, what = open_state(rec, e, data)
        local mark = st == 'waiting' and (what .. ':' .. tostring(e.wave)) or nil
        if mark ~= e.wait_on then
            if not dry_run then e.wait_on, e.wait_since = mark, mark and now or nil end
            changed = true
        elseif mark and now - (tonumber(e.wait_since) or now) > OPEN_WAIT_DAYS * 1200 then
            local n = math.tointeger(e.wait_tries) or 0
            if dry_run then
            elseif n < OPEN_REDIG_MAX then
                local cells, mode = {}, 'dig'
                if what == 'wave' then
                    for _, c in ipairs(e.waves[e.wave]) do
                        if not cut_done(tile_info(c.x, c.y, e.z)) then table.insert(cells, c) end
                    end
                else
                    cells, mode = e.rails, 'build'
                end
                if #cells > 0 then pcall(qf_try, mode, cells, e.z, 0, 0, false) end
                e.wait_tries, e.wait_since = n + 1, now
                changed = true
            elseif what == 'wave' then
                e.gave_up, e.wait_tries, e.wait_on, e.wait_since = e.wave, 0, nil, nil
                changed = true
            else
                e.stalled = true
                e.stall_why = ('the rails of level %d waited %d days'):format(e.level, OPEN_WAIT_DAYS * (OPEN_REDIG_MAX + 1))
                changed = true
            end
        end
    end
    return changed
end

-- The openings of a rock landmark together: 'open' (something to do now),
-- 'opening' (cut or railed, waiting on the dwarves), 'dig' (waiting on the
-- digging), or nil (none left).
local function opening_stage(rec, data)
    if type(rec.open) ~= 'table' then return nil end
    local any_ready, any_wait, any_dig, any_stall = false, false, false, false
    for _, e in ipairs(rec.open) do
        local st = open_state(rec, e, data)
        if st == 'ready' then any_ready = true
        elseif st == 'waiting' then any_wait = true
        elseif st == 'stalled' then any_stall = true
        elseif st == 'dig' then any_dig = true end
    end
    if any_ready then return 'open' end
    if any_stall then return 'stalled' end
    if any_wait then return 'opening' end
    if any_dig then return 'dig' end
    return nil
end

-- One step of the openings: on every level that is ready, the next wave cut
-- (or its lost tiles again), or the rails built. Returns the step's answer
-- fields, or nil and why.
local function open_step(rec, data, dry_run)
    local cut, railed, levels = 0, 0, {}
    for _, e in ipairs(rec.open) do
        local st, act, lost = open_state(rec, e, data)
        if st == 'ready' then
            if act == 'wave' or act == 'redo' then
                local w = act == 'wave' and e.wave + 1 or e.wave
                local cells = act == 'wave' and e.waves[w] or lost
                local good, failed, res = qf_try('dig', cells, e.z, 0, 0, dry_run)
                if not good then
                    return nil, ('the game %s the openings of level %d'):format(failed == 'dry' and 'would not cut' or 'refused', e.level)
                end
                cut = cut + stat(res, 'dig_designated')
                if not dry_run then
                    if act == 'wave' then e.wave, e.tries = w, 0 else e.tries = (math.tointeger(e.tries) or 0) + 1 end
                end
                table.insert(levels, {level = e.level, wave = w, waves = #e.waves})
            else
                if #e.rails > 0 then
                    local good, failed, res = qf_try('build', e.rails, e.z, 0, 0, dry_run)
                    if not good then
                        return nil, ('the game %s the rails of level %d'):format(failed == 'dry' and 'would not place' or 'refused', e.level)
                    end
                    railed = railed + stat(res, 'build_designated')
                end
                if not dry_run then e.railed = true end
                table.insert(levels, {level = e.level, rails = #e.rails})
            end
        elseif st == 'done' and not dry_run then
            e.done = true
        end
    end
    return {cut = cut, railed = railed, levels = levels}
end

-- The status of a rock landmark from its levels: 'built' once every level is done.
local function rock_status(rec, data)
    local left = 0
    for _, pid in ipairs(rec.project_ids or {}) do
        for _, p in ipairs(data.list) do
            if p.id == pid then
                if p.phase == 'cancelled' then return 'dropped' end
                if p.phase ~= 'done' and p.phase ~= 'decorate' then left = left + 1 end
            end
        end
    end
    if left == 0 and opening_stage(rec, data) ~= nil then return 'building' end   -- (E1) openings left
    return left == 0 and 'built' or 'building'
end

-- One step of a landmark: a surface one's next stage (clearing -> walls ->
-- floor -> the next level's walls ... -> furnish -> zone -> done), each
-- waiting for the last one's tiles to be built. A rock landmark is built
-- by its levels' projects; its step only records it built once they are.
function landmark_step(id, dry_run)
    OFFSET = elevation_offset()
    local d = landmarks_data()
    local rec = find_landmark(d, id)
    if not rec then return {ok = false, rejected = true, error = 'no such landmark'} end
    local function out(t)
        t.ok = t.ok ~= false
        t.landmark_id = id
        t.dry_run = dry_run or nil
        return t
    end
    if rec.status ~= 'building' then
        return out({ok = false, rejected = true, stage = rec.stage, done = rec.status == 'built' or nil,
                    error = ('the landmark is %s'):format(tostring(rec.status))})
    end
    if rec.ground ~= 'surface' then
        local data = load_projects()
        -- (0.105.37 fix) the openings' wait limit looked at first
        if type(rec.open) == 'table' and opening_stage(rec, data) == 'opening' and rock_status(rec, data) == 'building'
                and open_watch(rec, data, dry_run) and not dry_run then
            save_landmarks(d)
        end
        -- (E1) the openings: the next wave cut, or the rails built
        if opening_stage(rec, data) == 'open' and rock_status(rec, data) ~= 'dropped' then
            local r, why = open_step(rec, data, dry_run)
            if not r then return out({ok = false, stage = 'open', error = why}) end
            if not dry_run then rec.stage = 'open' save_landmarks(d) end
            return out({stage = 'open', cut = r.cut, railed = r.railed, levels = r.levels})
        end
        local st = rock_status(rec, data)
        if st == 'building' and type(rec.open) == 'table' and opening_stage(rec, data) == 'opening' then
            return out({ok = false, rejected = true, waiting = true, stage = 'opening',
                        error = ('%s: the openings are being cut or railed'):format(rec.name or 'the landmark')})
        end
        if st == 'building' and type(rec.open) == 'table' and opening_stage(rec, data) == 'stalled' then
            local why
            for _, e in ipairs(rec.open) do why = why or e.stall_why end
            return out({ok = false, rejected = true, stage = 'stalled',
                        error = ('%s: %s'):format(rec.name or 'the landmark', why or 'the openings stalled')})
        end
        if st == 'building' then
            return out({ok = false, rejected = true, stage = 'levels',
                        error = 'a rock landmark is built through its levels\' projects'})
        end
        if not dry_run then rec.status, rec.stage, rec.done = st, st == 'built' and 'done' or rec.stage, now_date() save_landmarks(d) end
        return out({stage = 'done', done = st == 'built' or nil, ok = st == 'built',
                    error = st ~= 'built' and 'a level of the landmark was cancelled' or nil})
    end
    local k = math.tointeger(rec.level) or 1
    local lv = rec.surface and rec.surface[k]
    if not lv then return out({ok = false, error = 'the landmark\'s record has no level ' .. k}) end
    local function place(cells, z, what, mode)
        if #cells == 0 then return 0 end
        local good, failed, res = qf_try(mode or 'build', cells, z, 0, 0, dry_run)
        if not good then return nil, ('the game %s %s'):format(failed == 'dry' and 'would not place' or 'refused', what) end
        return stat(res, (mode or 'build') .. '_designated')
    end
    local function wait(stage, n, what)
        -- (r9) the last change seen (tiles left, the stage): its slot's clock
        if not dry_run and (rec.progress_left ~= n or rec.progress_stage ~= stage or not rec.progress_tick) then
            rec.progress_left, rec.progress_stage, rec.progress_tick = n, stage, now_tick()
            save_landmarks(d)
        end
        return out({ok = false, rejected = true, waiting = true, stage = stage, left = n,
                    error = ('%s: %d %s still to build'):format(rec.name or 'the landmark', n, what)})
    end
    local function advance(stage, extra)
        if not dry_run then
            rec.progress_tick, rec.progress_left, rec.progress_stage = now_tick(), nil, nil   -- (r9)
            rec.stage = stage
            for key, v in pairs(extra or {}) do rec[key] = v end
            save_landmarks(d)
        end
    end
    -- the furniture, stockpiles and zone, once the shape stands
    local function start_furnish()
        local placed = 0
        for _, l in ipairs(rec.surface) do
            local nb, why = place(l.furnish, l.z, 'the landmark\'s furniture')
            if not nb then return out({ok = false, error = why}) end
            local np, why2 = place(l.place, l.z, 'the landmark\'s stockpiles', 'place')
            if not np then return out({ok = false, error = why2}) end
            placed = placed + nb + np
        end
        advance('furnish')
        return out({stage = 'furnish', placed = placed})
    end
    -- (E2) a landmark planned in steps (ai-blueprints.build_stages): each
    -- step placed once the last one's tiles stand; scaffolding taken down
    -- only while no one stands where it would strand them
    if type(rec.steps) == 'table' and rec.stage ~= 'furnish' then
        local nsteps = #rec.steps
        local function next_step(i)
            local st = rec.steps[i]
            if not st then return start_furnish() end
            local n = 0
            if st.kind == 'remove' then
                local why, w8 = removal_blocked(st, rec.name or 'the landmark')
                if why then
                    return out({ok = false, rejected = true, waiting = w8 or nil, stage = 'remove', step = i, steps = nsteps,
                                error = why})
                end
                for _, c in ipairs(st.cells) do
                    if remove_construction(c.x, c.y, st.z, dry_run) then n = n + 1 end
                end
            else
                local placed, why = place(st.cells, st.z, st.kind == 'scaffold' and 'the scaffold stair'
                                                        or 'the landmark\'s next tiles')
                if not placed then return out({ok = false, error = why}) end
                n = placed
            end
            advance(st.kind, {step = i, level = st.level})
            return out({stage = st.kind, step = i, steps = nsteps, level = st.level, placed = n,
                        scaffold = st.kind ~= 'build' or nil})
        end
        if rec.stage == 'clearing' then
            local n = trees_standing(rec)
            if n > 0 then
                if not dry_run then for _, t in ipairs(rec.trees) do fell_tree(t.x, t.y, t.z) end end
                return out({ok = false, rejected = true, waiting = true, stage = 'clearing', trees = n,
                            error = ('the dwarves are still felling %d tree(s)'):format(n)})
            end
            return next_step(1)
        end
        local i = math.tointeger(rec.step) or 0
        local st = rec.steps[i]
        if not st then return next_step(i + 1) end
        local n = step_left(st)
        if n > 0 then
            if st.kind == 'remove' then
                -- (0.105.37 fix) asked again only while no one stands on or above it
                local why, w8 = removal_blocked(st, rec.name or 'the landmark')
                if why then
                    return out({ok = false, rejected = true, waiting = w8 or nil, stage = 'remove', step = i, steps = nsteps,
                                left = n, error = why})
                end
                if not dry_run then
                    for _, c in ipairs(st.cells) do remove_construction(c.x, c.y, st.z, false) end
                end
                return wait('remove', n, 'scaffold tile(s) to take down')
            end
            return wait(st.kind, n, st.kind == 'scaffold' and 'scaffold stair tile(s)' or 'tile(s)')
        end
        return next_step(i + 1)
    end
    if rec.stage == 'clearing' then
        local n = trees_standing(rec)
        if n > 0 then
            if not dry_run then for _, t in ipairs(rec.trees) do fell_tree(t.x, t.y, t.z) end end
            return out({ok = false, rejected = true, waiting = true, stage = 'clearing', trees = n,
                        error = ('the dwarves are still felling %d tree(s)'):format(n)})
        end
        local placed, why = place(lv.walls, lv.z, 'the landmark\'s walls')
        if not placed then return out({ok = false, error = why}) end
        advance('walls')
        return out({stage = 'walls', level = k, placed = placed})
    end
    if rec.stage == 'walls' then
        local n = waiting(lv.walls, lv.z)
        if n > 0 then return wait('walls', n, 'wall tile(s) or door(s)') end
        local placed, why = place(lv.floor, lv.z, 'the landmark\'s floor and stairs')
        if not placed then return out({ok = false, error = why}) end
        advance('floor')
        return out({stage = 'floor', level = k, placed = placed})
    end
    if rec.stage == 'floor' then
        local n = waiting(lv.floor, lv.z)
        if n > 0 then return wait('floor', n, 'floor, ramp or stair tile(s)') end
        if k < #rec.surface then
            local nxt = rec.surface[k + 1]
            local placed, why = place(nxt.walls, nxt.z, 'the next level\'s walls')
            if not placed then return out({ok = false, error = why}) end
            advance('walls', {level = k + 1})
            return out({stage = 'next level', level = k + 1, placed = placed})
        end
        local placed = 0
        for _, l in ipairs(rec.surface) do
            local nb, why = place(l.furnish, l.z, 'the landmark\'s furniture')
            if not nb then return out({ok = false, error = why}) end
            local np, why2 = place(l.place, l.z, 'the landmark\'s stockpiles', 'place')
            if not np then return out({ok = false, error = why2}) end
            placed = placed + nb + np
        end
        advance('furnish')
        return out({stage = 'furnish', placed = placed})
    end
    if rec.stage == 'furnish' then
        local n = 0
        for _, l in ipairs(rec.surface) do n = n + waiting(l.furnish, l.z) end
        if n > 0 then return wait('furnish', n, 'piece(s) of furniture') end
        local zoned, dedicated = 0, nil
        for _, l in ipairs(rec.surface) do
            if #l.zone > 0 then
                local nz, why = place(l.zone, l.z, 'the landmark\'s zone', 'zone')
                if not nz then return out({ok = false, error = why}) end
                zoned = zoned + nz
                if not dry_run and rec.zone == 'temple' and rec.deity_hf and nz > 0 then
                    local okd, ded = pcall(dedicate_temple, {anchor = {x = 0, y = 0}, z = l.z, cells = {zone = l.zone}},
                                           {deity_hf = rec.deity_hf})
                    dedicated = okd and ded or false
                end
            end
        end
        if not dry_run then rec.status, rec.stage, rec.done = 'built', 'done', now_date() save_landmarks(d) end
        return out({stage = 'zone', zoned = zoned, dedicated = dedicated, done = true})
    end
    return out({ok = false, rejected = true, stage = rec.stage, error = 'nothing left to do'})
end

---------------------------------------------------------------------------
-- The report
---------------------------------------------------------------------------

-- {list = {{id, name, purpose, status, stage, levels, project_ids, started}}}
-- (the status of a rock landmark read from its levels: nothing is saved)
function landmarks_report()
    local d = landmarks_data()
    local data
    local out = {}
    for _, l in ipairs(d.list) do
        local status, stage = l.status, l.stage
        if l.ground ~= 'surface' and status == 'building' then
            data = data or load_projects()
            local st = rock_status(l, data)
            if st ~= 'building' then status, stage = st, 'done' end
            -- (E1) the openings: 'open' when a step can be taken now
            if st == 'building' and type(l.open) == 'table' then
                local ok, os_ = pcall(opening_stage, l, data)
                if ok and os_ and os_ ~= 'dig' then stage = os_
                elseif ok and os_ == nil then
                    -- (r2 h8) no step to take now: it goes on through its levels'
                    -- projects (the saved stage stayed 'open' after the openings
                    -- were done, and the brain asked a step again and again)
                    stage = 'levels'
                end
            end
        end
        local why
        if stage == 'stalled' then
            for _, o in ipairs(l.open or {}) do why = why or o.stall_why end
        end
        local e = {id = l.landmark_id, name = l.name, purpose = l.purpose, status = status, stage = stage,
                   levels = l.levels, project_ids = l.project_ids, started = l.started, by = l.by,
                   ground = l.ground, why = why}
        -- (E2) a landmark built in steps: where it is, and its scaffolding
        if type(l.steps) == 'table' then
            e.step, e.steps = math.tointeger(l.step) or 0, #l.steps
            if status == 'building' then
                local ok, sc = pcall(scaffold_state, l)
                if ok then e.scaffold = sc end
            end
        end
        table.insert(out, e)
    end
    return {list = out}
end
