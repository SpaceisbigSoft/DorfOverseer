-- ai-waterworks-steps: one step of a work (step) and the report.
--
-- (r8) A part of ai-waterworks, not a script of its own: ai-waterworks.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-waterworks').name and the hooks and helpers defined there
-- (T, building, designate, load_state, ...) are in reach.

if not WATERWORKS_PART_LOCALS then qerror('ai-waterworks-steps is a part of ai-waterworks; run ai-waterworks') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-waterworks-steps'] = '0.105.88'   -- (0.105.26) bumped with BRIDGE_VERSION

-- (r8) the hub's and earlier parts' locals used here
local seg_cells, dug, designate_all, undug, left_to_dig, leak, depth_at = WATERWORKS_PART_LOCALS.seg_cells, WATERWORKS_PART_LOCALS.dug, WATERWORKS_PART_LOCALS.designate_all, WATERWORKS_PART_LOCALS.undug, WATERWORKS_PART_LOCALS.left_to_dig, WATERWORKS_PART_LOCALS.leak, WATERWORKS_PART_LOCALS.depth_at

-- One step of the work of `kind`. opts: {dry_run, shut, retire, shop, plain}
function step(kind, opts)
    opts = opts or {}
    FAR = {reach = opts.far_reach, job_max = opts.job_max, segment = opts.segment}      -- (0.105.38)
    if not KINDS[kind] then return {ok = false, rejected = true, error = 'water_work: unknown kind ' .. tostring(kind)} end
    if kind == 'power' then return power_step(opts) end      -- (0.105.37 E3) its own steps (no floodgate of its own)
    local st = load_state()
    local id = kind == 'magma' and ('magma:' .. (MAGMA_SHOPS[opts.shop] and opts.shop or 'MagmaForge')) or kind
    local wk = st.works[id]
    local dry = opts.dry_run == true
    local function save() if not dry then st.works[id] = wk; save_state(st) end end
    local function wait(why) return {ok = false, rejected = true, waiting = true, stage = wk.stage, error = why} end
    local function advance(stage, extra)
        if not dry then wk.stage = stage; wk.since = now(); save() end
        local out = {ok = true, kind = kind, stage = stage, dry_run = dry or nil}
        for k, v in pairs(extra or {}) do out[k] = v end
        return out
    end
    local function gate_of(p) return building(p.gate.x, p.gate.y, p.gate.z, 'Floodgate') end
    local function lever_of(p) return building(p.lever.x, p.lever.y, p.lever.z, 'Trap') end
    -- (0.105.36) the pump stack's screw pumps set to be worked by hand while
    -- it fills (DF's "Start pump manually"), unset when it stops; how many
    local function pumps_manual(on)
        if dry or not wk or type(wk.plan) ~= 'table' or wk.plan.kind ~= 'pump' then return 0 end
        local n = 0
        for _, b in ipairs(wk.plan.builds or {}) do
            if b.kind == 'ScrewPump' then
                local bb = building(b.x, b.y, b.z, 'ScrewPump')
                if bb and bb.built and set_pump_manual(bb.id, on) then n = n + 1 end
            end
        end
        if on and n > 0 then
            wk.manual = n
            wk.manual_since = wk.manual_since or now()
        elseif not on then
            wk.manual, wk.manual_since = nil, nil
        end
        return n
    end
    local function hold(why)
        pumps_manual(false)        -- (0.105.36) a held stack isn't worked
        if not dry then wk.stage = 'held'; wk.why = why; save() end
        return {ok = false, rejected = true, stage = 'held', error = why}
    end
    -- (0.105.33) the floodgate shut at once, any pull on its way called off;
    -- true: it was open (and so pulled)
    local function shut_now(g)
        if dry or not wk.lever_id then return false end
        cancel_pulls(wk.lever_id)
        if g and g.built and not g.closed then pull(wk.lever_id, true) return true end
        return false
    end
    -- (0.105.33) filling that never ends: the floodgate shut, held, with why
    local function stalled(g, why)
        shut_now(g)
        pumps_manual(false)
        return hold(why)
    end
    -- (0.105.36) a citizen in deep water near the work's own tiles (a flood
    -- shut counts toward SHUTS_MAX only then: the report's "dwarves in deep
    -- water" is anywhere on the map). Unknown (no citizens): counted.
    local function flood_near()
        local okc, cs = pcall(citizens)
        local tiles = type(wk.plan) == 'table' and (wk.plan.tiles or wk.plan.wet) or nil
        if not okc or type(cs) ~= 'table' or type(tiles) ~= 'table' or next(tiles) == nil then return true end
        for _, c in ipairs(cs) do
            if type(c) == 'table' and c.x and depth_at(c) >= 4 then
                for _, t in ipairs(tiles) do
                    if math.abs(c.z - t.z) <= 3 and math.max(math.abs(c.x - t.x), math.abs(c.y - t.y)) <= FLOOD_NEAR then
                        return true
                    end
                end
            end
        end
        return false
    end

    -- the emergency stop, and retiring
    if opts.shut or opts.retire then
        if not wk then return {ok = false, rejected = true, error = 'no ' .. kind .. ' work to shut'} end
        -- (v35 fix) a hold that watches for water still getting in (or whose
        -- floodgate is gone) is never retired: the watch would stop
        if opts.retire and wk.stage == 'held' and type(wk.why) == 'string'
                and (wk.why:find('water is still getting in', 1, true) or wk.why:find('the floodgate is gone', 1, true)) then
            return {ok = false, rejected = true, stage = 'held', leak_watch = true,
                    error = 'held while water may still get in (' .. wk.why:sub(1, 80) .. '): not retired, kept watched'}
        end
        local g = gate_of(wk.plan)
        if dry then return {ok = true, dry_run = true, stage = wk.stage} end
        local was_open = shut_now(g)
        pumps_manual(false)
        if opts.retire then
            -- (0.105.38 review) a long dig retired half-done: what is designated
            -- and not dug yet is called off (the tunnel goes no nearer its
            -- source), and the half-dug tunnel is recorded and logged
            local p = wk.plan
            if type(p) == 'table' and p.stages and (wk.stage == 'digging' or (wk.stage == 'held' and wk.seg)) then
                local seg = math.min(#p.stages, math.tointeger(wk.seg) or 1)
                local upto = p.stages[seg][2]
                local designated, open = {}, nil
                for k = 1, upto do table.insert(designated, p.dig[k]) end
                local left = undug(designated)
                -- (review) the floodgate's floor too, once designated
                local cancel = {}
                for _, c in ipairs(left) do table.insert(cancel, c) end
                if wk.dig2 then for _, c in ipairs(undug(p.dig2)) do table.insert(cancel, c) end end
                local n_off = #cancel > 0 and undesignate(cancel) or 0
                local n_jobs = #cancel > 0 and cancel_dig_jobs(cancel) or 0
                if not (seg == #p.stages and #left == 0) then     -- (review) all dug: no half-dug tunnel
                    for k = upto, 1, -1 do
                        local c = p.dig[k]
                        if dug(T(c.x, c.y, c.z), c.text) then open = {x = c.x, y = c.y, z = c.z} break end
                    end
                    wk.half_dug = {dug = #designated - #left, of = #p.dig, segment = seg, segments = #p.stages,
                                   called_off = n_off, jobs_removed = n_jobs, last = open}
                    log_line(('%s retired half-dug: %d of %d tiles dug (segment %d of %d), %d designation(s) and %d dig job(s) called off%s')
                        :format(id, wk.half_dug.dug, #p.dig, seg, #p.stages, n_off, n_jobs,
                                open and (', its end at x%d y%d elevation %d'):format(open.x, open.y, ez(open.z)) or ''))
                end
            end
            wk.stage = 'retired'; wk.why = opts.why or 'retired'
            wk.shut, wk.shut_open = nil, nil
            -- (0.105.35) retired by the AI (a held work): not begun again for a
            -- while (the brain's retry wait), and never after RETIRE_MAX times
            st.retired_n = type(st.retired_n) == 'table' and st.retired_n or {}
            st.retired_n[id] = (math.tointeger(st.retired_n[id]) or 0) + 1
            st.refused[id] = {tick = now(), why = 'retired: ' .. wk.why, retired = st.retired_n[id]}
        else
            -- (0.105.33) kept shut: the steps wait (and pull nothing) until the
            -- brain asks for it to be opened again (reopen)
            wk.shut = opts.why or 'shut'
            wk.shut_at = now()
            wk.shut_open = wk.shut_open or was_open or nil
            -- (0.105.36) only the shuts of the last SHUTS_WINDOW_DAYS count,
            -- and only with a citizen in deep water near the work (floods
            -- elsewhere, years apart, never hold a work)
            local recent = {}
            for _, t in ipairs(type(wk.shut_ticks) == 'table' and wk.shut_ticks or {}) do
                if math.tointeger(t) and now() - t < SHUTS_WINDOW_DAYS * DAY then table.insert(recent, t) end
            end
            if flood_near() then table.insert(recent, now()) end
            wk.shut_ticks = recent
            wk.shuts = #recent
            if wk.shuts >= SHUTS_MAX and wk.stage ~= 'held' then
                wk.stage = 'held'
                wk.why = ('the floodgate was shut %d times in %d days (%s), with dwarves in deep water near it: '
                          .. 'the AI retires it, its floodgate shut for good'):format(wk.shuts, SHUTS_WINDOW_DAYS, wk.shut)
            end
        end
        save()
        return {ok = true, stage = wk.stage, shut = true}
    end

    if not wk or wk.stage == 'retired' then
        local n_ret = type(st.retired_n) == 'table' and math.tointeger(st.retired_n[id]) or 0
        if n_ret >= RETIRE_MAX then
            -- (0.105.36) the refusal stamped (with `retired`, so the brain
            -- skips this work and goes on to the next kind)
            local why0 = ('retired %d times already: not begun again'):format(n_ret)
            if not dry then
                local old = type(st.refused[id]) == 'table' and st.refused[id] or {}
                st.refused[id] = {tick = now(), why = old.why or why0, retired = n_ret}
                save_state(st)
            end
            return {ok = false, rejected = true, retired = n_ret, error = why0}
        end
        local plan, why, later
        if kind == 'moat' then plan, why = plan_moat({plain = opts.plain})
        elseif kind == 'magma' then plan, why = plan_magma(opts.shop, {open_caverns = opts.open_caverns == true})
        else plan, why, later = PLANNERS[kind]() end
        if not plan then
            if not dry then st.refused[id] = {tick = now(), why = why, later = later or nil}; save_state(st) end
            return {ok = false, rejected = true, error = why, later = later or nil}
        end
        local path = path_check(plan)
        if not path.ok then
            local why2 = ('dry run: %s at x%d y%d, elevation %d'):format(path.why, path.at.x, path.at.y, path.at.e)
            if not dry then st.refused[id] = {tick = now(), why = why2}; save_state(st) end
            return {ok = false, rejected = true, error = why2, path = path}
        end
        if dry then return {ok = true, dry_run = true, stage = 'planned', plan = plan, path = path} end
        st.refused[id] = nil
        wk = {kind = kind, plan = plan, path = path}
        return advance('planned', {path = path})
    end
    local p = wk.plan
    if wk.stage == 'held' and wk.plug_guard then
        -- (fix41-ff) a plug the dig guard refused: read again each step (not
        -- counted again); filling goes on once the guard lets it be dug
        local gwhy = dig_guard_why(p.plug.x, p.plug.y, p.plug.z, nil)
        if gwhy and gwhy ~= guard_err() then return {ok = false, rejected = true, stage = 'held', error = wk.why} end
        if dry then return {ok = true, dry_run = true, stage = 'held', recheck = true} end
        wk.plug_guard, wk.why = nil, nil
        return advance('filling')
    end
    if wk.stage == 'held' then
        -- (0.105.36) a leak-watch hold looked at again (the brain asks for a
        -- `recheck`, or a why starting "recheck"): the floodgate rebuilt if it
        -- is gone, the farm room's wet tiles counted again; un-held when dry
        local again = opts.recheck == true or (type(opts.why) == 'string' and opts.why:match('^recheck') ~= nil)
        local why0 = type(wk.why) == 'string' and wk.why or ''
        local gone_hold = why0:find('the floodgate is gone', 1, true) ~= nil
        local wet_hold = why0:find('water is still getting in', 1, true) ~= nil
        if not (again and (gone_hold or wet_hold)) then
            return {ok = false, rejected = true, stage = 'held', error = wk.why}
        end
        if dry then return {ok = true, dry_run = true, stage = 'held', recheck = true} end
        local function watching(why) save() return {ok = false, rejected = true, waiting = true, stage = 'held', error = why} end
        local g, l = gate_of(p), lever_of(p)
        if not g or not l then
            -- gone (a building destroyer): a new one placed where it stood
            -- (magma: magma-safe, the building stage checks it)
            if not gone_hold then wk.why = 'the floodgate is gone (destroyed while held): a new one is placed' end
            local cells = {}
            if not g then table.insert(cells, {x = p.gate.x, y = p.gate.y, z = p.gate.z, text = 'x'}) end
            if not l then table.insert(cells, {x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}) end
            local filtered = p.kind == 'magma' and magma_filter(true) or nil
            local ok = designate_all(cells, 'build')
            if filtered then magma_filter(filtered) end
            if not ok then
                return watching(('the floodgate or its lever is gone and the game would not place a new one at x%d y%d, '
                                 .. 'elevation %d: kept watched, tried again in a few days'):format(p.gate.x, p.gate.y, ez(p.gate.z)))
            end
            return watching('the floodgate or its lever is gone: a new one is placed where it stood')
        end
        if gone_hold then
            -- a floodgate stands there again: built, linked and opened as before
            wk.why, wk.opened_once, wk.open_from, wk.opened_at, wk.relinks = nil, nil, nil, nil, nil
            wk.rise_at, wk.test_from = nil, nil
            return advance('building')
        end
        if g.built and not g.closed then shut_now(g) end
        if p.room then
            local r = p.room
            local wet = 0
            for x = r.x1, r.x2 do for y = r.y1, r.y2 do if depth_at({x = x, y = y, z = r.z}) > 0 then wet = wet + 1 end end end
            wk.wet = wet
            if wet == 0 then
                wk.why, wk.slow = nil, nil
                return advance('drying', {wet = 0})       -- dry now: the next step finishes it
            end
            return watching(('the farm room is still wet (%d tile(s)): kept watched, its floodgate shut'):format(wet))
        end
        wk.why = nil
        return advance('filling')
    end

    -- (0.105.33) shut by the emergency stop: nothing pulled until the brain
    -- asks for it again (reopen; the bridge passes `why`, so a why starting
    -- "reopen" asks too), and then no sooner than REOPEN_AFTER_DAYS
    if wk.shut then
        local again = opts.reopen == true or (type(opts.why) == 'string' and opts.why:match('^reopen') ~= nil)
        if not again then return wait(('the floodgate is shut (%s): waiting to be opened again'):format(wk.shut)) end
        local since = now() - (wk.shut_at or 0)
        if since < REOPEN_AFTER_DAYS * DAY then
            return wait(('the floodgate was shut (%s) under %d days ago: not opened yet'):format(wk.shut, REOPEN_AFTER_DAYS))
        end
        if dry then return {ok = true, dry_run = true, stage = wk.stage, reopen = true} end
        local g = gate_of(p)
        local opened = false
        if wk.shut_open and g and g.built and g.closed and wk.lever_id
                and (wk.stage == 'filling' or wk.stage == 'done') then
            pull(wk.lever_id, false)
            opened = true
            if wk.stage == 'filling' then wk.opened_at = now() end
        end
        if wk.stage == 'filling' then
            -- (0.105.36) the stall clocks start again: the days shut don't
            -- count, and a pull not made yet is waited on (and asked again)
            -- as at the first opening
            if opened then wk.opened_once, wk.open_from = nil, now() end
            wk.rise_at, wk.test_from, wk.stalled = nil, now(), nil
        end
        wk.shut, wk.shut_at, wk.shut_open = nil, nil, nil
        save()
        return {ok = true, stage = wk.stage, reopened = true, opening = opened or nil}
    end

    if wk.stage == 'planned' then
        if dry then return {ok = true, dry_run = true, stage = 'digging'} end
        -- (0.105.38) a long dig a segment at a time (the first one now)
        local ok, z = designate_all(seg_cells(p, 1), 'dig')
        if not ok then return {ok = false, error = ('the game would not designate the dig (elevation %d)'):format(ez(z))} end
        if p.stages then wk.seg = 1 end
        return advance('digging', p.stages and {segment = 1, segments = #p.stages} or nil)
    end
    if wk.stage == 'digging' and p.stages and (wk.seg or 1) < #p.stages then
        -- (0.105.38) the segment dug: the dry run walked again over the whole
        -- plan (something may have opened beside it meanwhile), then the next
        local i = wk.seg or 1
        local n = left_to_dig(seg_cells(p, i))
        if n > 0 then return wait(('%d tile(s) left to dig (segment %d of %d)'):format(n, i, #p.stages)) end
        local chk = path_check(p)
        if not chk.ok then
            return hold(('dry run before segment %d of %d: %s at x%d y%d, elevation %d'):format(
                i + 1, #p.stages, chk.why, chk.at.x, chk.at.y, chk.at.e))
        end
        -- (0.105.38 review) the next segment's own tiles still solid rock (no
        -- aquifer, no cavern unless the plan was let open one, nothing wet
        -- beside or over them)
        local bad = next_segment_bad(p, seg_cells(p, i + 1))
        if bad then return hold(('before segment %d of %d: %s'):format(i + 1, #p.stages, bad)) end
        if dry then return {ok = true, dry_run = true, stage = 'digging', segment = i + 1} end
        local ok, z = designate_all(seg_cells(p, i + 1), 'dig')
        if not ok then return {ok = false, error = ('the game would not designate the dig (elevation %d)'):format(ez(z))} end
        wk.seg = i + 1
        save()
        return wait(('segment %d of %d designated'):format(i + 1, #p.stages))
    end
    if wk.stage == 'digging' then
        local n = left_to_dig(p.dig)
        if n > 0 then return wait(('%d tile(s) left to dig'):format(n)) end
        if p.dig2 and not wk.dig2 then
            if dry then return {ok = true, dry_run = true, stage = 'digging'} end
            local ok = designate_all(p.dig2, 'dig')
            if not ok then return {ok = false, error = 'the game would not designate the floodgate\'s floor'} end
            wk.dig2 = true
            save()
            return wait('the floodgate\'s floor is being dug')
        end
        if p.dig2 and left_to_dig(p.dig2) > 0 then return wait('the floodgate\'s floor is being dug') end
        -- (0.105.0 review) magma: only with magma-safe parts at hand (a wooden
        -- or iron floodgate would melt or burn, and the magma flood the fort);
        -- buildingplan's magma filter on while they are placed
        local filtered = nil
        if p.kind == 'magma' then
            local have = magma_parts()
            local want = {floodgates = 1, hatches = 1, mechanisms = 3}
            local short = {}
            for _, k in ipairs({'floodgates', 'hatches', 'mechanisms'}) do
                if (have[k] or 0) < want[k] then
                    table.insert(short, ('%d magma-safe %s (has %d)'):format(want[k], k, have[k] or 0))
                end
            end
            if #short > 0 then
                return wait('magma works need magma-safe parts (e.g. of green glass, or of a metal like steel): '
                            .. table.concat(short, ', '))
            end
        end
        if dry then return {ok = true, dry_run = true, stage = 'building'} end
        if p.kind == 'magma' then filtered = magma_filter(true) end
        local cells = {{x = p.gate.x, y = p.gate.y, z = p.gate.z, text = 'x'},
                       {x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}}
        for _, b in ipairs(p.builds or {}) do table.insert(cells, b) end
        local ok = designate_all(cells, 'build')
        if filtered then magma_filter(filtered) end
        if not ok then return {ok = false, error = 'the game would not place the floodgate, lever or the work\'s buildings'} end
        return advance('building')
    end
    if wk.stage == 'building' then
        local g, l = gate_of(p), lever_of(p)
        if not g or not l then return {ok = false, error = 'the floodgate or the lever is gone'} end
        local left = {}
        if not g.built then table.insert(left, 'the floodgate') end
        if not l.built then table.insert(left, 'the lever') end
        for _, b in ipairs(p.builds or {}) do
            local bb = building(b.x, b.y, b.z, b.kind)
            if not bb or not bb.built then table.insert(left, b.kind:lower()) end
        end
        if #left > 0 then return wait('being built: ' .. table.concat(left, ', ')) end
        -- (0.105.0 review) magma: what was built must be magma-safe (nothing flows yet)
        if p.kind == 'magma' then
            local bad = {}
            if building_magma_safe(g.id) == false then table.insert(bad, 'the floodgate') end
            for _, b in ipairs(p.builds or {}) do
                local bb = building(b.x, b.y, b.z, b.kind)
                if bb and building_magma_safe(bb.id) == false then table.insert(bad, b.kind:lower()) end
            end
            if #bad > 0 then
                return hold(table.concat(bad, ' and ') .. ' was built of a material that is not magma-safe: '
                            .. 'take it down and build it of a magma-safe one')
            end
        end
        if dry then return {ok = true, dry_run = true, stage = 'linking'} end
        set_name(l.id, p.lever.name)
        for _, b in ipairs(p.builds or {}) do
            local bb = building(b.x, b.y, b.z, b.kind)
            if b.lock then lock_hatch(bb.id) end
            if b.kind == 'Bridge' then wk.bridge_id = bb.id end
        end
        local r = link(l.id, g.id)
        if not r.ok then return r end
        wk.lever_id, wk.gate_id = l.id, g.id
        return advance('linking')
    end
    if wk.stage == 'linking' then
        if not is_linked(wk.lever_id, wk.gate_id) then
            if link_pending(wk.lever_id) or dry then return wait('the lever is being linked to the floodgate') end
            wk.relinks = (wk.relinks or 0) + 1
            if wk.relinks > 3 then return hold('the lever\'s link to the floodgate was lost 3 times: the AI retires it') end
            local r = link(wk.lever_id, wk.gate_id)
            save()
            if not r.ok then return r end
            return wait('the link was lost: asked for again')
        end
        -- (moat) the drawbridge is not on the moat's lever (one pull would
        -- work both): the gate scan finds it unworked and the gate rules give
        -- it its own "AI gate lever", which the gate watcher pulls
        if p.kind == 'moat' and p.bridge and p.bridge.drawbridge and not dry and not wk.gates_rescanned then
            pcall(function() reqscript('ai-gates').scan(now()) end)
            wk.gates_rescanned = true
            save()
        end
        if dry then return {ok = true, dry_run = true, stage = 'filling'} end
        return advance('filling', {})
    end
    if wk.stage == 'filling' then
        local g = gate_of(p)
        if not g then return hold('the floodgate is gone') end
        local lk = leak(p)
        if lk then
            shut_now(g)
            return hold(('liquid got out at x%d y%d, elevation %d: the floodgate was shut'):format(lk.x, lk.y, ez(lk.z)))
        end
        -- the plug: dug with the gate shut, after the path is walked again
        if not dug(T(p.plug.x, p.plug.y, p.plug.z), p.plug.text) then
            local path = path_check(p)
            if not path.ok then
                wk.path = path
                return wait(('the plug waits: %s at x%d y%d, elevation %d'):format(path.why, path.at.x, path.at.y, path.at.e))
            end
            -- (0.105.40b fix) a plug the dig guard refuses: the work held with its
            -- reason (not 'dig-now did not dig it' for ever), counted once
            local gwhy = dig_guard_why(p.plug.x, p.plug.y, p.plug.z, (not dry) and 'waterworks_plug' or nil)
            if gwhy and gwhy == guard_err() then
                -- (fix41-ff) the guard couldn't read the tile: no lasting hold on
                -- a read error, the plug waits and is read again next step
                return wait(('the plug at x%d y%d, elevation %d waits: %s (read again next time)'):format(
                    p.plug.x, p.plug.y, ez(p.plug.z), gwhy))
            end
            if gwhy then
                -- (fix41-ff) held, and looked at again each step (wk.plug_guard)
                if not dry then wk.plug_guard = true end
                return hold(('the plug at x%d y%d, elevation %d is left alone (%s): it guards the underworld'):format(
                    p.plug.x, p.plug.y, ez(p.plug.z), gwhy))
            end
            if dry then return {ok = true, dry_run = true, stage = 'filling', plug = true} end
            if not g.closed then pull(wk.lever_id, true) return wait('the floodgate is shut before the plug is dug') end
            designate({{x = p.plug.x, y = p.plug.y, text = p.plug.text}}, p.plug.z, 'dig')
            dig_now(p.plug.x, p.plug.y, p.plug.z)
            if not dug(T(p.plug.x, p.plug.y, p.plug.z), p.plug.text) then
                return wait('the plug is being dug (DFHack dig-now did not dig it)')
            end
            wk.opened_at = now()
            pull(wk.lever_id, false)
            save()
            return {ok = true, stage = 'filling', plug_dug = true, opening = true}
        end
        if g.closed and not wk.opened_once then
            -- (0.105.33) not waited on for ever: held when nobody opened it
            if not dry and not wk.open_from then wk.open_from = wk.opened_at or now() save() end
            if now() - (wk.open_from or now()) > FILL_STALL_DAYS * DAY then
                return hold(('the floodgate was not opened in %d days: can a dwarf reach its lever?'):format(FILL_STALL_DAYS))
            end
            -- (0.105.36) no pull yet (a floodgate placed again after it was gone): one now
            if (not wk.opened_at or now() - wk.opened_at > 2 * DAY) and not dry then pull(wk.lever_id, false) wk.opened_at = now() save() end
            return wait('a dwarf is on the way to open the floodgate')
        end
        if not dry and not wk.opened_once then wk.opened_once = true; wk.test_from = now(); save() end
        local t = p.test
        -- (0.105.33) the last rise, for the stall test (a frozen or dry source, a blocked way)
        local function rose(d)
            if not dry and (wk.best == nil or d > wk.best) then
                wk.best = d; wk.rise_at = now()
                wk.stalled = nil             -- (0.105.36) rising again: no more pump labour asked
            end
            return now() - (wk.rise_at or wk.test_from or now()) > FILL_STALL_DAYS * DAY
        end
        if t.mode == 'deep' then
            local d = depth_at(t)
            wk.depth = d
            if d < t.want then
                if rose(d) then
                    return stalled(g, ('%s has not risen in %d days (%d/7): the source may be frozen or dry, or its way '
                                       .. 'blocked; the floodgate was shut'):format(kind == 'moat' and 'the moat' or 'the magma pit',
                                                                                    FILL_STALL_DAYS, d))
                end
                save()
                return wait(('filling: %d/7 (wants %d/7)'):format(d, t.want))
            end
            return advance('finishing', {depth = d})
        elseif t.mode == 'rise' then
            -- (0.105.36) the pumps worked by hand (set again each step: cheap)
            local manual = pumps_manual(true)
            local d = depth_at(t)
            if wk.start_depth == nil and not dry then wk.start_depth = d end
            wk.depth = d
            if d >= t.want then
                pumps_manual(false)
                return advance('done', {depth = d, rose = d - (wk.start_depth or 0)})
            end
            -- (said in the stall text; the stall wait still runs, so it never waits for ever)
            if not dry then wk.manual_failed = manual == 0 or nil end
            if rose(d) then
                return stalled(g, ('the reservoir has not risen in %d days (%d/7): the pumps are not worked, or the '
                                   .. 'water is gone; the floodgate was shut'):format(FILL_STALL_DAYS, d))
            end
            if now() - (wk.rise_at or wk.test_from or now()) > PUMP_TEST_DAYS * DAY then
                wk.stalled = true
                save()
                return wait(('the reservoir has not risen in %d days (%d/7): is a dwarf working the pumps (the pump operator labour)?%s')
                    :format(PUMP_TEST_DAYS, d, wk.manual_failed and ' (the pumps could not be set to "Start pump manually")' or ''))
            end
            save()
            return wait(('pumping: the reservoir %d/7 (from %d/7)'):format(d, wk.start_depth or 0))
        elseif t.mode == 'wet' then
            local r = p.room
            local wet = 0
            for x = r.x1, r.x2 do for y = r.y1, r.y2 do if depth_at({x = x, y = y, z = r.z}) > 0 then wet = wet + 1 end end end
            if wet == 0 then
                if now() - (wk.test_from or now()) > FILL_STALL_DAYS * DAY then
                    return stalled(g, ('no water reached the farm room in %d days: the source may be frozen or dry, '
                                       .. 'or the tunnel blocked; the floodgate was shut'):format(FILL_STALL_DAYS))
                end
                return wait('the water is on its way into the farm room')
            end
            if dry then return {ok = true, dry_run = true, stage = 'drying'} end
            -- enough: a little water muddies the floor. (0.105.33) Shut, not
            -- toggled: the lever pulled only while the floodgate is open
            shut_now(g)
            return advance('drying', {wet = wet})
        end
    end
    if wk.stage == 'drying' then
        local r = p.room
        local wet = 0
        for x = r.x1, r.x2 do for y = r.y1, r.y2 do if depth_at({x = x, y = y, z = r.z}) > 0 then wet = wet + 1 end end end
        wk.wet = wet
        if wet > 0 then
            -- (0.105.0 review) not waited on for ever: held, with why
            if now() - (wk.since or now()) > IRR_DRY_DAYS * DAY then
                wk.slow = true
                shut_now(gate_of(p))
                return hold(('the farm room is still wet after %d days (%d tile(s)): water is still getting in '
                             .. '(the floodgate leaks, or a second way in); the AI keeps it watched, its floodgate shut, '
                             .. 'and looks again every few days'):format(IRR_DRY_DAYS, wet))
            end
            save()
            return wait(('the farm room is drying: %d tile(s) still wet'):format(wet))
        end
        return advance('finishing')
    end
    if wk.stage == 'finishing' then
        if p.kind == 'irrigation' then
            local r = p.room
            local cells, muddy = {}, 0
            for x = r.x1, r.x2 do for y = r.y1, r.y2 do
                if not (x == r.x1 and y == r.y1) and mud(x, y, r.z) then
                    muddy = muddy + 1
                    table.insert(cells, {x = x, y = y, z = r.z, text = 'p'})
                end
            end end
            if muddy == 0 then return hold('the floor dried without mud: the AI retires it') end
            if dry then return {ok = true, dry_run = true, stage = 'done', muddy = muddy} end
            if not designate_all(cells, 'build') then return {ok = false, error = 'the game would not place the farm plots'} end
            return advance('done', {muddy = muddy})
        end
        if p.kind == 'magma' then
            local f = p.finish[1]
            local b = building(f.x, f.y, f.z, f.kind)
            if b and b.built then return advance('done') end
            if b then return wait('the ' .. p.shop .. ' is being built') end
            if dry then return {ok = true, dry_run = true, stage = 'finishing'} end
            if not designate_all(p.finish, 'build') then return {ok = false, error = 'the game would not place the ' .. p.shop} end
            save()
            return wait('the ' .. p.shop .. ' is placed over the magma')
        end
        return advance('done')
    end
    if wk.stage == 'done' then
        local lk = leak(p)
        local g = gate_of(p)
        if lk and g and not g.closed then
            shut_now(g)
            return hold(('liquid got out at x%d y%d, elevation %d: the floodgate was shut'):format(lk.x, lk.y, ez(lk.z)))
        end
        -- (0.105.0 review) waiting: the planner looks again in a few days (the leak check)
        return {ok = false, rejected = true, waiting = true, stage = 'done', error = 'the ' .. kind .. ' is done (no leak)'}
    end
    return {ok = false, rejected = true, error = 'unknown stage ' .. tostring(wk.stage)}
end

-- The report: each work's stage and what it waits for, and the refusals.
function report()
    local st = load_state()
    local out = {works = {}, refused = {}}
    local parts          -- (13c) the parts in store, counted once a report (not once a work)
    local links          -- (0.105.33) the levers' links, fetched once a report (not once a work)
    for id, wk in pairs(st.works) do
        if wk.lever_id and not links then links = lever_links() or {} end
        local p = wk.plan or {}
        local g = p.gate and building(p.gate.x, p.gate.y, p.gate.z, 'Floodgate')
        local row = {kind = wk.kind, stage = wk.stage, why = wk.why, depth = wk.depth, wet = wk.wet,
                     stalled = wk.stalled or nil, slow = wk.slow or nil, shut = wk.shut,
                     manual = wk.manual, manual_since = wk.manual_since,
                     gate = g and (g.built and (g.closed and 'shut' or 'open') or 'planned') or nil,
                     linked = wk.lever_id and is_linked(wk.lever_id, wk.gate_id, links) or nil,
                     path_tiles = wk.path and wk.path.tiles, lift = p.lift, power = p.power, wheel = p.wheel,
                     shop = p.shop, bridge = p.bridge and (p.bridge.drawbridge and 'drawbridge' or 'bridge') or nil,
                     lever_at = p.lever and {x = p.lever.x, y = p.lever.y, e = ez(p.lever.z)} or nil,
                     gate_at = p.gate and {x = p.gate.x, y = p.gate.y, e = ez(p.gate.z)} or nil}
        if wk.kind == 'power' then
            -- (0.105.37 E3) the power: its source, the power check, on or off
            row.source, row.need, row.have, row.wheels = p.source, p.need, p.have, p.wheels
            row.engaged = wk.stage == 'running' and wk.engaged ~= false or nil
            row.power, row.power_need = wk.power, wk.power_need
            row.still = wk.still_from and true or nil
            row.paused = wk.stage == 'running' and wk.paused or nil      -- (0.105.37 fix) a still wheel: why
        end
        pcall(function()
            if wk.stage == 'linking' or wk.stage == 'building' then
                if not parts then
                    local B = reqscript('ai-builder')
                    parts = {floodgates = B.count_items('FLOODGATE'), mechanisms = B.count_items('TRAPPARTS'),
                             pipes = B.count_items('PIPE_SECTION')}
                end
                row.floodgates_free, row.mechanisms_free, row.pipes_free = parts.floodgates, parts.mechanisms, parts.pipes
            end
        end)
        out.works[id] = row
    end
    for id, r in pairs(st.refused) do out.refused[id] = r end
    return out
end
