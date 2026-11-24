-- ai-builder-wells-shaft: a cavern well's shaft: its designations, the gate at its
-- bottom and the stair lid, well_shaft_step.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.
-- (r8) Cut from ai-builder-wells.lua, which had grown to 133 KB; loaded right
-- after it and its parts before this one, in the old file's order.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-wells-shaft'] = '0.105.94'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

-- Every cell designated in the dry run, then for real (cells in map coordinates).
function designate(cells, z, mode)
    return (qf_try(mode, cells, z, 0, 0, false, #cells, true))
end

-- (0.104.151-152) A cavern well's two ways in from the cavern, closed.
-- The well is a hole (the wiki: no obstruction; swimmers path in through
-- wells), and its shaft is dug from a stair column beside it (0.104.13) that
-- runs down beside the shaft at every level. The one tile that opens into the
-- cavern is the shaft's lowest (its floor channelled away over the cavern's
-- air; the column's bottom step is an up stair, a floor under it). So:
--   the shaft gate: a hatch on that lowest shaft tile, on a lever beside the
--     well. A shut hatch stops the bucket, so it is opened once linked and
--     shut only while a danger is near (DFHack's lever --instant: no dwarf
--     runs to it), then opened again. Built from the column's bottom step.
--     The lever first; the hatch only once the lever stands and 2 mechanisms
--     are free for the link, so the well is never left blocked waiting.
--   the stair lid: only when the game won't build the gate, a hatch over the
--     column's top step, locked (DFHack forbids it); unlocked again while
--     dwarves must go down to build or relink a gate.
-- Kept in the project (`shaft_gate` = {lever = {x, y, z}, lever_id,
-- hatch_id, link_fails, impossible}). The review's points are marked "rv".
local STAIR_DOWN_SHAPE = {STAIR_DOWN = true, STAIR_UPDOWN = true}
SHAFT_LINK_FAILS_MAX = 3

local function shaft_bottom(p)
    local low
    for _, z in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
        if not low or z < low then low = z end
    end
    return low or (p.z - 1)
end

local function hatch_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b or b:getType() ~= df.building_type.Hatch then return nil end
    local closed = true
    pcall(function() closed = b.door_flags.closed end)
    local forbidden = false
    pcall(function() forbidden = b.door_flags.forbidden end)
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage(), closed = closed, forbidden = forbidden, b = b}
end

-- rv 14: a lever, not any trap
local function lever_at(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b or b:getType() ~= df.building_type.Trap then return nil end
    local okl, lever = pcall(function() return b.trap_type == df.trap_type.Lever end)
    if okl and not lever then return nil end
    return {id = b.id, built = b:getBuildStage() >= b:getMaxBuildStage()}
end

local function free_floor(x, y, z, group)
    local t = tile_info(x, y, z)
    local g = walk_group(x, y, z)
    return t and t.shape == 'FLOOR' and not t.building and not t.designated and not t.liquid
        and not building_at(x, y, z) and g ~= 0 and (group == nil or g == group)
end

-- rv 12: outside the well's 3x3 (its furnishing would wait for the lever)
local function shaft_lever_spot(p)
    local a = anchor_of(p)
    local top = type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] or nil
    for _, r in ipairs({2, 3}) do
        for dy = -r, r do
            for dx = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = a.x + dx, a.y + dy
                    -- rv2 5: reachable from the stairs (the same walk group as their top)
                    if not (top and x == top.x and y == top.y)
                            and free_floor(x, y, p.z, top and walk_group(top.x, top.y, top.z) or nil) then
                        return {x = x, y = y, z = p.z}
                    end
                end
            end
        end
    end
end

local function job_of(building_id, jt)
    local ok, j = pcall(function()
        local b = df.building.find(building_id)
        for _, job in ipairs(b and b.jobs or {}) do
            if job.job_type == jt then return job end
        end
    end)
    return ok and j or nil
end

function shaft_gate_state(p)
    local g = p.shaft_gate or {}
    local a = anchor_of(p)
    local h = hatch_at(a.x, a.y, shaft_bottom(p))
    local lv = g.lever and lever_at(g.lever.x, g.lever.y, g.lever.z or p.z) or nil
    if g.impossible then return {state = 'none_possible', hatch = h, lever = lv} end
    if not g.lever then return {state = h and 'stray' or 'none', hatch = h} end
    if not lv then return {state = 'no_lever', hatch = h} end
    if not lv.built then return {state = 'building', hatch = h, lever = lv} end
    if not h then return {state = 'no_hatch', lever = lv} end
    if not h.built then return {state = 'building', hatch = h, lever = lv} end
    local linked = false
    local okl, links = pcall(function() return reqscript('ai-gates').lever_links() end)
    for _, lid in ipairs(okl and links[h.id] or {}) do if lid == lv.id then linked = true end end
    if not linked then
        return {state = job_of(lv.id, df.job_type.LinkBuildingToTrigger) and 'linking' or 'unlinked', hatch = h, lever = lv}
    end
    if job_of(lv.id, df.job_type.PullLever) then return {state = 'pulling', hatch = h, lever = lv} end
    return {state = h.closed and 'closed' or 'open', hatch = h, lever = lv}
end

local function free_mechanism_count()
    -- (0.104.156) by the link's own test when there is one (none where no dwarf can walk)
    local okc, c = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
    if okc and type(c) == 'table' and type(c.usable) == 'number' then return c.usable end
    local ok, n = pcall(function() return (count_items('TRAPPARTS')) end)
    return ok and n or 0
end

-- (0.105.4 review) the shaft's lowest level dug open (the hatch can go on it)
function shaft_bottom_open(p)
    local a = anchor_of(p)
    local t = tile_info(a.x, a.y, shaft_bottom(p))
    return t ~= nil and t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP'
end

-- (0.105.4 review) hatch covers in store (free), for the hold on the shaft's last level
function shaft_hatch_covers()
    local ok, n = pcall(function() return (count_items('HATCH_COVER')) end)
    return ok and n or 0
end

-- (0.105.33 L5) A cavern well given up (the game refused the well, or it was
-- cancelled) over a shaft dug open into the cavern: its shaft still opens
-- the fort to the cavern, so its gate and lid are still kept (the gate
-- always shut: no bucket goes down it).
function shaft_left_open(p)
    return p.kind == 'well' and p.phase == 'cancelled' and not p.held
        and type(p.shaft) == 'table' and #p.shaft > 0
        and type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] ~= nil
        and shaft_bottom_open(p)
end

-- The cavern wells whose shaft gate and lid the AI keeps.
local function shaft_kept(p)
    local st = p.shaft_stairs
    if p.kind ~= 'well' or type(st) ~= 'table' or not st[1] then return false end
    if p.phase == 'furnish' or p.phase == 'done' then return true end
    if p.phase == 'dig' and (p.held or p.released) then return true end   -- (0.105.4 review) the gate before the breach
    return shaft_left_open(p)
end

SHAFT_WATCH = SHAFT_WATCH or {on = false}

local function abs_now()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and t or 0
end

local function gate_mem(pid)
    SHAFT_WATCH.gates = SHAFT_WATCH.gates or {}
    local g = SHAFT_WATCH.gates[pid]
    if not g then g = {}; SHAFT_WATCH.gates[pid] = g end
    return g
end

-- One step for each cavern well's shaft gate toward `want_closed` (a given-up
-- shaft's always toward shut). {ok, wells = [{project_id, was, stage?, error?}]}
-- (group 2) Shutting shuts the gates the watcher's test (shaft_judge) finds
-- a danger for (every gate when it finds none: the brain's own reason);
-- opening opens only a gate with no danger near and its hold (shaft_hold)
-- run out: "held_shut" otherwise, with the danger and the ticks left.
-- `dry` (true/false; nil: unchanged): the brain says the fort is short of
-- water (a far walker doesn't keep the shaft shut, no hold).
function well_shaft_step(want_closed, dry_run, dry)
    local data = load_projects()
    local wells, changed = {}, false
    local all_closed = want_closed
    local dry_changed = false
    if dry ~= nil and (SHAFT_WATCH.dry == true) ~= (dry == true) then
        dry_changed = true
        if not dry_run then SHAFT_WATCH.dry = (dry == true) or nil end
    end
    -- the linked gates' dangers now, by the watcher's own test
    local judged, hits = {}, {}
    for _, p in ipairs(data.list) do
        local sg = p.shaft_gate
        if p.kind == 'well' and shaft_kept(p) and type(sg) == 'table' and sg.lever and not sg.impossible then
            local a = anchor_of(p)
            local h = hatch_at(a.x, a.y, shaft_bottom(p))
            if h and h.built then
                table.insert(judged, {x = a.x, y = a.y, z = p.z, hz = shaft_bottom(p), id = p.id,
                                      shut = h.closed and true or false})
            end
        end
    end
    if #judged > 0 then
        local okt, t = pcall(shaft_threats, judged)
        if okt and type(t) == 'table' then
            for i, hit in pairs(t) do hits[judged[i].id] = hit end
        end
    end
    local any_hit = next(hits) ~= nil
    local now = abs_now()
    -- (K48-K4b, A4 11) a danger near this well's own shaft, for the steps that
    -- send a dwarf down beside the opening (the break into the cavern, the
    -- hatch, its link): a call made for another well no longer breaks this
    -- one into the cavern with a beast below it. Judged as for a shut gate
    -- (the wider reach). nil: none (or it can't be read).
    local function own_hit(p)
        if hits[p.id] then return hits[p.id] end
        local a = anchor_of(p)
        local okt, t = pcall(shaft_threats, {{x = a.x, y = a.y, z = p.z, hz = shaft_bottom(p), id = p.id, shut = true}})
        return okt and type(t) == 'table' and t[1] or nil
    end
    local function danger_name(hit)
        local okr, nm = pcall(dfhack.units.getReadableName, hit.u)
        return okr and nm or ('unit ' .. tostring(hit.u and hit.u.id))
    end
    for _, p in ipairs(data.list) do
        local st = p.shaft_stairs
        if shaft_kept(p) then
            local hit = hits[p.id]
            local want_closed = (all_closed and (hit ~= nil or not any_hit)) or p.phase == 'cancelled'
            local leave = all_closed and not want_closed      -- another gate's danger: this one left as it is
            local a, hz = anchor_of(p), shaft_bottom(p)
            local g = shaft_gate_state(p)
            local r = {project_id = p.id, was = g.state, cancelled = p.phase == 'cancelled' or nil}
            local sg = p.shaft_gate
            -- (0.105.47) who keeps the gate as it is (a pull due: opened or shut)
            local gate_below = nil
            if (g.state == 'pulling' or g.state == 'open' or g.state == 'closed')
                    and (g.state == 'pulling' or (g.state == 'closed') ~= (want_closed == true)) then
                gate_below = well_safety_call('gate_block', p.id, want_closed == true, hit ~= nil)
            end
            -- rv 3: work below needs the stairs: a locked lid is unlocked
            -- (K48-K4b, A4 12) the lid of a shaft still being dug too, when the
            -- gate can't be built (the miners dig the levels from those stairs)
            if g.state ~= 'open' and g.state ~= 'closed'
                    and (g.state ~= 'none_possible' or p.phase == 'dig') and not dry_run then
                local top = st[1]
                local lid = hatch_at(top.x, top.y, top.z)
                if lid and lid.forbidden then util_module().lock_door(lid.b, false, 'well'); r.unlocked_lid = true end   -- (0.105.47) the walk map redone
            end
            if g.state == 'none' or g.state == 'stray' or g.state == 'no_lever' then
                -- rv 2, 8: the lever first (a stray hatch kept: linked when the lever stands)
                local lv = (sg and sg.lever and free_floor(sg.lever.x, sg.lever.y, sg.lever.z or p.z)) and sg.lever
                    or shaft_lever_spot(p)
                if not lv then
                    r.error = 'no free floor near the well for the lever'
                elseif dry_run then
                    r.stage = 'place_lever'
                elseif designate({{x = lv.x, y = lv.y, text = 'Tl'}}, lv.z or p.z, 'build') then
                    p.shaft_gate = {lever = lv, link_fails = sg and sg.link_fails or nil}
                    r.stage, changed = 'lever_placed', true
                else
                    r.error = 'the game would not place the lever near the well'
                end
            elseif g.state == 'no_hatch' and p.held then
                -- (0.105.4 review) the lever stands: the shaft breaks into the cavern
                -- only once a hatch cover and 2 mechanisms (its link) are in store,
                -- so the hatch goes in straight after, before anything comes up
                local mech, covers = free_mechanism_count(), shaft_hatch_covers()
                local busy = well_safety_call('column_block', p.id)     -- (0.105.47)
                local near = own_hit(p)                                 -- (K48-K4b)
                if mech < 2 or covers < 1 then
                    r.stage, r.mechanisms, r.hatch_covers = 'waiting_parts', mech, covers
                elseif near then
                    r.stage, r.danger = 'waiting_danger', danger_name(near)
                elseif busy then
                    -- (0.105.47) never opened into the cavern with a dwarf in the shaft's column
                    r.stage, r.below = 'waiting_below', busy
                elseif dry_run then
                    r.stage = 'break_through'
                else
                    local hd = p.held
                    local pri = type(p.params) == 'table' and p.params.pri or ''
                    local okh, hs = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'h' .. (pri or '')}}, hd.z, a.x, a.y)
                    -- (K48-K4b, A4 11) the channel really designated (quickfort not
                    -- throwing is not enough: the hold was let go over nothing dug)
                    okh = okh and stat(hs, 'dig_designated') >= 1
                    if okh then
                        for _, c in ipairs(st) do
                            if c.z == hd.z then
                                pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. (pri or '')}}, c.z, c.x, c.y)
                            end
                        end
                    end
                    if okh then
                        p.held, p.released, changed = nil, true, true
                        r.stage = 'break_started'
                    else
                        r.error = 'the game would not dig the shaft\'s last level'
                    end
                end
            elseif g.state == 'no_hatch' and p.phase == 'dig' and not shaft_bottom_open(p) then
                r.stage = 'breaking_through'      -- (0.105.4 review) the hatch once the last level is dug
            elseif g.state == 'no_hatch' then
                -- rv 6: only with the lever up and 2 mechanisms free for the link
                local mech = free_mechanism_count()
                local near = own_hit(p)                                 -- (K48-K4b)
                if mech < 2 then
                    r.stage, r.mechanisms = 'waiting_mechanisms', mech
                elseif near then
                    r.stage, r.danger = 'waiting_danger', danger_name(near)
                elseif dry_run then
                    r.stage = 'place_hatch'
                else
                    local okd, s = pcall(quickfort_apply, 'build', {{x = 0, y = 0, text = 'H'}}, hz, a.x, a.y, 'run', true)
                    if not okd or stat(s, 'build_designated') ~= 1 then
                        -- rv2 3: three refusals, not one, before the lid instead
                        sg.hatch_fails, changed = (sg.hatch_fails or 0) + 1, true
                        if sg.hatch_fails >= SHAFT_LINK_FAILS_MAX then sg.impossible = true end
                        r.error = 'the game would not build a hatch at the bottom of the shaft'
                            .. (sg.impossible and ' (3 times: the stair lid instead)' or '')
                    elseif designate({{x = a.x, y = a.y, text = 'H'}}, hz, 'build') then
                        r.stage = 'hatch_placed'
                    else
                        r.error = 'the game refused the hatch at the bottom of the shaft'
                    end
                end
            elseif g.state == 'unlinked' then
                -- (0.104.156) a link job asked for and gone with no link: DF
                -- cancelled it ("Item inaccessible", 25 times on 1 Nov). Lost 3
                -- times with the same mechanisms: no new job until others are free.
                local G = reqscript('ai-gates')
                if sg.link_asked and not dry_run then
                    sg.link_lost, sg.link_asked, changed = (sg.link_lost or 0) + 1, nil, true
                end
                local lp = sg.lever or {}
                local okf, cand = pcall(G.free_mechanisms, 2, {x = lp.x or a.x, y = lp.y or a.y, z = lp.z or p.z})
                local key = {}
                for _, m in ipairs(okf and type(cand) == 'table' and cand or {}) do table.insert(key, tostring(m.id)) end
                key = table.concat(key, ',')
                local lost = sg.link_lost or 0
                local near = own_hit(p)                                 -- (K48-K4b)
                if near then
                    r.stage, r.danger = 'waiting_danger', danger_name(near)
                elseif lost >= SHAFT_LINK_FAILS_MAX and key == (sg.link_mechs or '') then
                    r.error = ('the link job was lost %d times (DF cancels it; mechanisms %s): waits for others')
                        :format(lost, key ~= '' and key or 'none')
                    r.link_lost = lost
                else
                    if lost >= SHAFT_LINK_FAILS_MAX and not dry_run then
                        sg.link_lost, changed = 0, true          -- other mechanisms: a fresh try
                    end
                    local res = dry_run and {ok = true} or G.link_lever(g.lever.id, g.hatch.id, false)
                    if res.ok then
                        r.stage = dry_run and 'link' or 'linking'
                        if not dry_run then
                            sg.link_asked, sg.link_mechs, changed = true, key, true
                            r.link_lost = sg.link_lost
                        end
                    else
                        r.error, r.mechanisms = res.error, res.mechanisms
                        -- rv 6: a link that keeps failing for another reason: the hatch
                        -- comes down (it would block the bucket for good), the lid instead
                        if not dry_run and not tostring(res.error or ''):find('mechanism') then
                            sg.link_fails, changed = (sg.link_fails or 0) + 1, true
                            if sg.link_fails >= SHAFT_LINK_FAILS_MAX then
                                pcall(dfhack.buildings.deconstruct, g.hatch.b)
                                sg.impossible = true
                                r.error = r.error .. ' (3 times: the shaft hatch taken down, the stair lid instead)'
                            end
                        end
                    end
                end
            elseif leave and (g.state == 'pulling' or g.state == 'closed' or g.state == 'open') then
                r.stage = g.state
            elseif not want_closed and (g.state == 'pulling' or g.state == 'closed')
                    and (hit or shaft_hold(p.id, sg, now) > 0) then
                -- (group 2) a danger near, or not away long enough: kept shut
                r.stage = 'held_shut'
                r.wait = shaft_hold(p.id, sg, now)
                if hit then
                    local okr, nm = pcall(dfhack.units.getReadableName, hit.u)
                    r.danger = okr and nm or ('unit ' .. tostring(hit.u and hit.u.id))
                end
            elseif gate_below then
                -- (0.105.47) not opened under a dwarf standing on the shut hatch (it
                -- drops into the cavern lake), nor shut for no danger with a dwarf
                -- below it: kept as it is, tried again next time
                r.stage, r.below = 'waiting_below', gate_below
            elseif g.state == 'pulling' then
                -- rv 9: a dwarf on the way to pull it: called off (a late pull would
                -- toggle the gate the wrong way), and the gate set at once
                if not dry_run then
                    local j = job_of(g.lever.id, df.job_type.PullLever)
                    if j then pcall(dfhack.job.removeJob, j) end
                    if g.hatch.closed ~= (want_closed == true) then
                        local ok, out = pull(g.lever.id, true)
                        if not ok then r.error = 'lever pull failed: ' .. tostring(out):sub(1, 120) end
                    end
                    if want_closed and not r.error then
                        gate_mem(p.id).shut_at, gate_mem(p.id).seen = now, hit and now or gate_mem(p.id).seen
                        if sg then sg.shut_at, changed = now, true end
                    end
                    if sg and not r.error then
                        sg.auto_shut, changed = (want_closed and hit ~= nil) or nil, true   -- (K48-K4)
                        sg.brain_shut = (want_closed and hit == nil and p.phase ~= 'cancelled') or nil   -- (K48-K4b)
                    end
                end
                if not r.error then r.stage = want_closed and 'closed' or 'opened' end
            elseif g.state == 'open' or g.state == 'closed' then
                if sg.link_lost or sg.link_asked then sg.link_lost, sg.link_asked, changed = nil, nil, true end
                if sg.lever_id ~= g.lever.id or sg.hatch_id ~= g.hatch.id then
                    sg.lever_id, sg.hatch_id, changed = g.lever.id, g.hatch.id, true   -- rv 13
                end
                if (g.state == 'closed') ~= (want_closed == true) then
                    if dry_run then
                        r.stage = want_closed and 'close' or 'open'
                    else
                        -- (0.104.164) opened at once too: a dwarf's pull never came (Teacheroar,
                        -- 1 Nov: well 218 "open its shaft again" 49 times in 90 minutes, the
                        -- gate still shut), and the hatch only opens while no danger is near
                        local ok, out = pull(g.lever.id, true)
                        if ok then r.stage = want_closed and 'closed' or 'opened'
                        else r.error = 'lever pull failed: ' .. tostring(out):sub(1, 120) end
                        if ok and want_closed then
                            gate_mem(p.id).shut_at, gate_mem(p.id).seen = now, hit and now or gate_mem(p.id).seen
                            sg.shut_at, changed = now, true
                        end
                        if ok then
                            sg.auto_shut, changed = (want_closed and hit ~= nil) or nil, true   -- (K48-K4)
                            -- (K48-K4b) shut by the brain for its own reason (no danger the
                            -- watcher sees): the watcher never opens it; anything else shut
                            -- with no mark (an older watcher's) it adopts
                            sg.brain_shut = (want_closed and hit == nil and p.phase ~= 'cancelled') or nil
                        end
                    end
                else
                    r.stage = g.state
                end
            else
                r.stage = g.state            -- building, linking, none_possible: waits
            end
            table.insert(wells, r)
        end
    end
    if changed and not dry_run then save_projects(data) end
    if #wells == 0 then return {ok = false, rejected = true, error = 'no cavern well'} end
    local watch_started = false
    for _, r in ipairs(wells) do
        local linked = r.was == 'open' or r.was == 'closed' or r.was == 'pulling'
        if linked and not dry_run and shaft_watch_start() then watch_started = true end
    end
    local acted = watch_started or dry_changed
    for _, r in ipairs(wells) do
        if not r.error and r.stage and r.stage ~= r.was and r.stage ~= 'waiting_mechanisms'
                and r.stage ~= 'waiting_parts' and r.stage ~= 'breaking_through' and r.stage ~= 'held_shut'
                and r.stage ~= 'waiting_below' and r.stage ~= 'waiting_danger' then      -- (0.105.47, K48-K4b)
            acted = true
        end
    end
    local dry_now = SHAFT_WATCH.dry == true or nil
    if dry_run then return {ok = true, dry_run = true, wells = wells, dry = dry_now} end
    if acted then return {ok = true, wells = wells, dry = dry_now, dry_changed = dry_changed or nil} end
    local why = wells[1].error
    for _, r in ipairs(wells) do
        if not why and r.stage == 'waiting_below' then      -- (0.105.47)
            why = 'waiting: ' .. tostring(r.below) .. ' is in the shaft or below its gate'
        end
        if not why and r.stage == 'waiting_danger' then      -- (K48-K4b)
            why = 'waiting: ' .. tostring(r.danger) .. ' is near the shaft below (no dwarf sent down beside it)'
        end
        if not why and r.stage == 'held_shut' then
            why = 'kept shut: ' .. (r.danger and (tostring(r.danger) .. ' is near') or
                                    ('the danger has been away too short a while, ' .. tostring(r.wait) .. ' ticks to go'))
        end
    end
    return {ok = false, rejected = true, wells = wells,
            error = why or ('nothing to do: ' .. tostring(wells[1].stage or wells[1].was))}
end

-- (r8) the file-scope helpers ai-builder-wells-watch uses too, handed on (the same
-- functions and table; none is assigned again)
WELLS_PART_LOCALS = {STAIR_DOWN_SHAPE = STAIR_DOWN_SHAPE, shaft_bottom = shaft_bottom, hatch_at = hatch_at, job_of = job_of,
                     free_mechanism_count = free_mechanism_count, shaft_kept = shaft_kept, abs_now = abs_now, gate_mem = gate_mem}
