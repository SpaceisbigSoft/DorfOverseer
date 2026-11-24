-- ai-builder-cistern-step: building the cistern, one step a call (cistern_step).
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment right after ai-builder-cistern, so every name here is
-- reqscript('ai-builder').name and the helpers defined there are in reach.
-- (r8) Split off ai-builder-cistern.lua by theme; the top-level locals the
-- ai-builder-cistern files share with this one come from CISTERN_PART_LOCALS.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-cistern-step'] = '0.105.94'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez
local still_water, river_water = CISTERN_PART_LOCALS.still_water, CISTERN_PART_LOCALS.river_water
local save_cistern, game_tick, room_tiles = CISTERN_PART_LOCALS.save_cistern, CISTERN_PART_LOCALS.game_tick, CISTERN_PART_LOCALS.room_tiles
local building_info, path_words = CISTERN_PART_LOCALS.building_info, CISTERN_PART_LOCALS.path_words

-- (0.104.144) THE PLAYER, 31 Oct 20:51: the cistern as built doesn't work,
-- and working it would flood the fort. Until a new design: its floodgate is
-- never opened by the AI (it may still be shut), and no new cistern is begun.
CISTERN_HOLD = false          -- (0.104.145) the second design: released
CISTERN_HOLD_WHY = 'the cistern is on hold (the player: as built it would flood the fort): the floodgate stays shut'

CISTERN_TUNNEL_ASKED = nil       -- (0.105.3) the brain's cistern_tunnel_max, set by cistern_step's caller
function cistern_step(dry_run, prefs, tunnel)
    CISTERN_TUNNEL_ASKED = math.tointeger(tonumber(tunnel))
    OFFSET = elevation_offset()
    if prefs then cistern_prefs(prefs) end
    local d = cistern_data()
    -- (0.104.145) a cistern of the first design is retired: its floodgate
    -- shut (it could flood the fort) and the next one planned afresh
    if d and (d.plan.v or 1) < CISTERN_V then
        local p0 = d.plan
        local g = building_info(p0.floodgate.x, p0.floodgate.y, p0.cistern.z, 'Floodgate')
        if g and g.built and not g.closed and not d.lever_id then
            return {ok = false, rejected = true, needs_player = true,
                    error = 'the old cistern\'s floodgate is open and no lever is linked to it: shut it by hand'}
        end
        if g and g.built and not g.closed and d.lever_id then
            if dry_run then return {ok = true, dry_run = true, retire = true} end
            if not lever_pull_pending(d.lever_id) then pull(d.lever_id, true) end
            return {ok = true, stage = d.stage, shut = true,
                    error = 'the old cistern\'s floodgate is being shut before it is retired (its design could flood the fort)'}
        end
        if dry_run then return {ok = true, dry_run = true, retire = true} end
        local old = site_get(CISTERN_KEY .. '/retired')
        -- (0.105.27 fixes) its tunnel and shaft too: ai-util cistern_tiles keeps their items forbidden
        table.insert(old, {cistern = p0.cistern, source = p0.source, tunnel_path = p0.tunnel_path,
                           intake_z = p0.intake_z, shaft = p0.shaft, why = 'the first design (pressure could flood the fort)'})
        site_put(CISTERN_KEY .. '/retired', old)
        site_put(CISTERN_KEY, {})
        return {ok = true, stage = 'retired', retired = true,
                error = 'the old cistern (first design) retired, its floodgate shut: a new one is planned next'}
    end
    if not d and CISTERN_HOLD then
        return {ok = false, rejected = true, held = true, error = 'no new cistern while the design is on hold'}
    end
    if not d then
        -- (0.105.3) the same tunnel reach the survey planned it with
        local plan, why, cut = plan_cistern(nil, nil, {tunnel = CISTERN_TUNNEL_ASKED})
        if not plan and not cut then
            -- (r2h1) a river's shaft way on the fort levels past the busiest (as the survey looked)
            local okr, rv = pcall(cistern_rivers)
            if okr and rv then
                local p2, why2, cut2 = plan_cistern(CISTERN_LEVELS + 1, CISTERN_LEVELS + CISTERN_RIVER_LEVELS,
                                                    {tunnel = CISTERN_TUNNEL_ASKED})
                if p2 then plan = p2 else cut = cut2; why = why or why2 end
            end
        end
        if not plan then return {ok = false, error = why, timed_out = cut or nil} end
        if dry_run then return {ok = true, dry_run = true, stage = 'dig', plan = plan} end
        d = {stage = 'dig', plan = plan}
    end
    local p, z = d.plan, d.plan.cistern.z
    local zw, wx, wy = p.well.z, p.well.x, p.well.y
    local zi = p.intake_z or z                 -- (0.104.145) the source's level: the tunnel, floodgate and plug
    local function wait(why) return {ok = false, rejected = true, waiting = true, stage = d.stage, error = why} end
    local function advance(stage, extra)
        if not dry_run then d.stage = stage; save_cistern(d) end
        local out = {ok = true, stage = stage, dry_run = dry_run or nil}
        for k, v in pairs(extra or {}) do out[k] = v end
        return out
    end

    -- (0.104.144) on hold: past the link (opening, the plug, filling, the
    -- well) nothing more is done; an open floodgate is shut
    if CISTERN_HOLD and d.stage ~= 'dig' and d.stage ~= 'building' and d.stage ~= 'linking' then
        local g = building_info(p.floodgate.x, p.floodgate.y, zi, 'Floodgate')
        if not dry_run and g and g.built and not g.closed and d.lever_id and not lever_pull_pending(d.lever_id) then
            pull(d.lever_id)
            return {ok = true, held = true, shut = true, error = CISTERN_HOLD_WHY}
        end
        return {ok = false, rejected = true, held = true, error = CISTERN_HOLD_WHY}
    end
    if d.stage == 'dig' then
        if dry_run then return {ok = true, dry_run = true, stage = 'dig', plan = p} end
        local room = {}
        for _, c in ipairs(room_tiles(p.cistern)) do
            if not (c.x == wx and c.y == wy) then table.insert(room, {x = c.x, y = c.y, text = 'd'}) end
        end
        local tunnel = {}
        -- (0.105.38) a long tunnel a segment at a time (from the cistern out)
        local tn = #p.tunnel_path - 1
        local first_seg = tn > CISTERN_SEGMENT and CISTERN_SEGMENT or tn
        for i = 1, first_seg do
            table.insert(tunnel, {x = p.tunnel_path[i].x, y = p.tunnel_path[i].y, text = 'd'})
        end
        if tn > first_seg then d.tseg = first_seg end
        if not designate({{x = wx, y = wy, text = 'j'}}, zw, 'dig')
                or not designate({{x = wx, y = wy, text = 'u'}}, z, 'dig')
                or not designate(room, z, 'dig') or (#tunnel > 0 and not designate(tunnel, zi, 'dig')) then
            return {ok = false, error = 'the game would not designate the cistern\'s digging'}
        end
        -- (0.104.145) the shaft: a down stair on the source's level, up/down
        -- stairs through the rock, an up stair at the bottom (diagonal to the room)
        if p.shaft then
            for zz = z, zi do
                local ch = zz == zi and 'j' or (zz == z and 'u' or 'i')
                if not designate({{x = p.shaft.x, y = p.shaft.y, text = ch}}, zz, 'dig') then
                    return {ok = false, error = 'the game would not designate the cistern\'s shaft'}
                end
            end
        end
        return advance('digging', {x = wx, y = wy, elevation = ez(z), tunnel = p.tunnel})
    end
    if d.stage == 'digging' then
        local left = 0
        for _, c in ipairs(room_tiles(p.cistern)) do
            local t = tile_info(c.x, c.y, z)
            if t and t.shape == 'WALL' then left = left + 1 end
        end
        local tdone = d.tseg or (#p.tunnel_path - 1)       -- (0.105.38) the tunnel designated so far
        for i = 1, tdone do
            local t = tile_info(p.tunnel_path[i].x, p.tunnel_path[i].y, zi)
            if t and t.shape == 'WALL' then left = left + 1 end
        end
        if left == 0 and tdone < #p.tunnel_path - 1 then
            -- the segment dug: the next one, its rock checked again first
            -- (solid, no water, aquifer or cavern; the plug's tile stays)
            local nxt = math.min(#p.tunnel_path - 1, tdone + CISTERN_SEGMENT)
            local cells = {}
            for i = tdone + 1, nxt do
                local q = p.tunnel_path[i]
                local t = tile_info(q.x, q.y, zi)
                if not tunnel_stretch_ok(t) then
                    return wait(('the tunnel\'s next stretch is no longer solid rock at x%d y%d (water, an aquifer '
                                 .. 'or a cavern): not dug further'):format(q.x, q.y))
                end
                table.insert(cells, {x = q.x, y = q.y, text = 'd'})
            end
            if dry_run then return {ok = true, dry_run = true, stage = 'digging', tunnel_dug = tdone} end
            if not designate(cells, zi, 'dig') then
                return {ok = false, error = 'the game would not designate the cistern\'s tunnel'}
            end
            d.tseg = nxt < #p.tunnel_path - 1 and nxt or nil
            save_cistern(d)
            return wait(('the cistern\'s tunnel: %d of %d tile(s) designated'):format(nxt, #p.tunnel_path - 1))
        end
        if p.shaft then
            for zz = z, zi do
                local t = tile_info(p.shaft.x, p.shaft.y, zz)
                if t and t.shape == 'WALL' then left = left + 1 end
            end
        end
        local top = tile_info(wx, wy, zw)
        if not top or top.shape ~= 'STAIR_DOWN' and top.shape ~= 'STAIR_UPDOWN' then left = left + 1 end
        if left > 0 then return wait(('the cistern is being dug: %d tile(s) left'):format(left)) end
        if dry_run then return {ok = true, dry_run = true, stage = 'build'} end
        local fg, lv = p.floodgate, p.lever
        if not lv then
            -- (0.105.33 L5) looked for again (an old plan, or a floor dug since)
            lv = cistern_lever_spot(wx, wy, zw)
            if not lv then return wait('no free floor for the lever near the well (2-3 tiles from it)') end
            p.lever = lv
            save_cistern(d)
        end
        if not designate({{x = fg.x, y = fg.y, text = 'x'}}, zi, 'build')
                or not designate({{x = lv.x, y = lv.y, text = 'Tl'}}, zw, 'build') then
            return {ok = false, error = 'the game would not place the floodgate or the lever'}
        end
        return advance('building')
    end
    local gate = building_info(p.floodgate.x, p.floodgate.y, zi, 'Floodgate')
    local lever = p.lever and building_info(p.lever.x, p.lever.y, zw, 'Trap')
    if d.stage == 'building' then
        if not gate or not lever then return {ok = false, error = 'the floodgate or the lever is gone'} end
        if not gate.built or not lever.built then return wait('the floodgate and the lever are being built') end
        if dry_run then return {ok = true, dry_run = true, stage = 'link'} end
        local okg, G = pcall(reqscript, 'ai-gates')
        if not okg then return {ok = false, error = 'ai-gates missing'} end
        local r = G.link_lever(lever.id, gate.id, false)
        if not r.ok then return r end
        d.lever_id, d.gate_id = lever.id, gate.id
        return advance('linking')
    end
    if d.stage == 'linking' then
        -- (0.104.138) the lever (or the gate) itself gone (Teacheroar: "no
        -- lever with id 273", toppled in a tantrum?) used up the 3 relinks on
        -- a building that wasn't there: take the one standing on its spot, or
        -- place it again, and count afresh
        local function gone(id)
            local ok, b = pcall(function() return df.building.find(id) end)
            return ok and id ~= nil and b == nil
        end
        if gone(d.lever_id) or gone(d.gate_id) then
            if dry_run then return wait('the lever or floodgate is gone: placed again') end
            if lever and lever.built and gate and gate.built then
                d.lever_id, d.gate_id, d.relinks = lever.id, gate.id, 0
                save_cistern(d)
                local r = reqscript('ai-gates').link_lever(d.lever_id, d.gate_id, false)
                if not r.ok then return r end
                return wait('the lever or floodgate was replaced: linked again')
            end
            if (not lever and p.lever and not designate({{x = p.lever.x, y = p.lever.y, text = 'Tl'}}, zw, 'build'))
                    or (not gate and not designate({{x = p.floodgate.x, y = p.floodgate.y, text = 'x'}}, zi, 'build')) then
                return {ok = false, error = 'the lever or floodgate is gone and the game would not place it again'}
            end
            d.relinks = 0
            return advance('building')
        end
        local links = reqscript('ai-gates').lever_links()
        local linked = false
        for _, lid in ipairs(links[d.gate_id] or {}) do if lid == d.lever_id then linked = true end end
        if not linked then
            -- (0.104.110) the link job was lost (cancelled, its mechanisms
            -- taken): Teacheroar waited on it 3,259 steps. Asked for again,
            -- 3 times at most
            local pending = false
            pcall(function()
                local lv = df.building.find(d.lever_id)
                for _, j in ipairs(lv and lv.jobs or {}) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then pending = true end
                end
            end)
            if pending or dry_run then return wait('the lever is being linked to the floodgate') end
            if (math.tointeger(d.relinks) or 0) >= 3 then
                return {ok = false, rejected = true, needs_player = true,
                    error = 'the link from the lever to the floodgate was lost 3 times; '
                    .. 'link it by hand (the lever beside the well)'}
            end
            -- (0.104.141) why the last one was dropped: DF's newest "cancels
            -- Link a Building" announcement, kept for the Needs you line
            pcall(function()
                local reps = df.global.world.status.reports
                for i = #reps - 1, math.max(0, #reps - 400), -1 do
                    local txt = reps[i].text
                    if txt:find('cancels Link') then d.link_why = txt:gsub('^.-cancels ', ''):sub(1, 120) break end
                end
            end)
            local r = reqscript('ai-gates').link_lever(d.lever_id, d.gate_id, false)
            if not r.ok then return r end
            d.relinks = (math.tointeger(d.relinks) or 0) + 1     -- (0.104.138) only a link really asked for
            save_cistern(d)
            return wait(('the lever link was lost: asked for again (%d)'):format(d.relinks))
        end
        if CISTERN_HOLD then return {ok = false, rejected = true, held = true, error = CISTERN_HOLD_WHY} end
        -- (0.104.145) closed all round, and its source still there, before any water
        local sealed, where, gaps = cistern_sealed(p, d.stage)
        if not dry_run and d.unsealed ~= (where or nil) then d.unsealed = where; save_cistern(d) end
        if not sealed then
            -- (0.104.168) the AI walls it up itself where it safely can
            return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
        end
        if not dry_run and (d.sealing or d.unsealed_why) then d.sealing, d.unsealed_why = nil, nil; save_cistern(d) end
        if p.river then
            -- (r2h1) a river's water beside the plug (frozen, or low: the plug waits)
            local wt = tile_info(p.water.x, p.water.y, zi)
            if not river_water(wt) and not still_water(wt) then
                return wait(wt and wt.material == 'FROZEN_LIQUID' and 'the river beside the plug is frozen: the plug waits for the thaw'
                            or 'the river beside the plug is low or gone: the plug waits for its water')
            end
        elseif not still_water(tile_info(p.water.x, p.water.y, zi)) then
            return {ok = false, rejected = true, error = 'the cistern\'s source is gone (no still water beside the plug)'}
        end
        if dry_run then return {ok = true, dry_run = true, stage = 'open'} end
        -- (0.104.145, review) the gate stays shut: the plug is dug first with
        -- nobody inside (DFHack dig-now), then the gate opened at once. A miner
        -- digging it by hand had to flee back down a shaft filling faster than
        -- the room, through water a dwarf won't wade
        return advance('opening')
    end
    if d.stage == 'opening' then
        if gate and gate.closed and d.plug_by_hand then
            return wait('a dwarf is on the way to pull the lever (open the floodgate)')
        end
        -- (0.105.33 L5) the gate open before the plug is dug (the player opened
        -- it, or a late pull did): shut at once, the plug dug with it shut
        if not d.plug_by_hand and gate and gate.built and not gate.closed and d.lever_id then
            if dry_run then return {ok = true, dry_run = true, stage = 'shut'} end
            cancel_lever_pulls(d.lever_id)
            local ok, out = pull(d.lever_id, true)
            if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
            return wait('the floodgate stood open before the plug was dug: shut at once, the plug next')
        end
        -- (0.104.0, map safety) the water comes in when the plug is dug: no one
        -- else may be in the cistern or its tunnel then. The plug waits until
        -- both are empty, and what lies there is forbidden (no hauler goes in
        -- for it); only the miner who digs the plug goes in, and out through
        -- the open floodgate
        local inside = cistern_inside(p, z)
        local n = zi == z and units_on_tiles(inside, z)
            or (units_on_tiles(room_tiles(p.cistern), z) + units_on_tiles(cistern_way(p), zi))
        if p.shaft then
            for zz = z, zi do n = n + units_on_tiles({{x = p.shaft.x, y = p.shaft.y}}, zz) end
        end
        if n > 0 then
            return wait(('%d creature(s) in the cistern or its tunnel: the plug waits until it is empty'):format(n))
        end
        local sealed, where, gaps = cistern_sealed(p, d.stage)
        if not dry_run and d.unsealed ~= (where or nil) then d.unsealed = where; save_cistern(d) end
        if not sealed then
            -- (0.104.168) the AI walls it up itself where it safely can; the plug waits
            return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
        end
        if not dry_run and (d.sealing or d.unsealed_why) then d.sealing, d.unsealed_why = nil, nil; save_cistern(d) end
        if dry_run then return {ok = true, dry_run = true, stage = 'plug'} end
        if zi == z then
            forbid_items_on(inside, z)
        else
            forbid_items_on(room_tiles(p.cistern), z)
            forbid_items_on(cistern_way(p), zi)
        end
        -- dig-now: the plug gone at once, the gate still shut; then the gate opened
        -- (0.105.40b) the dig guard: a plug by raw adamantine, the spire or the underworld is never dug
        -- (0.105.40b fix) held with the guard's reason (kept: d.guard_held), the
        -- refusal counted once for the tile however often this step runs
        local deep = dig_check_tiles({{x = p.plug.x, y = p.plug.y}}, zi, (not dry_run) and 'cistern_plug' or nil)
        if deep then
            local why = ('the plug at x%d y%d, elevation %d is left alone (%s): it guards the underworld'):format(
                p.plug.x, p.plug.y, ez(zi), deep)
            local okE, gerr = pcall(function() return util_module().GUARD_ERR end)
            if okE and gerr and deep == gerr then     -- (fix41-ff) a read error: waits, read again next step
                why = ('the plug at x%d y%d, elevation %d waits: %s (read again next time)'):format(
                    p.plug.x, p.plug.y, ez(zi), deep)
            end
            if not dry_run and d.guard_held ~= why then d.guard_held = why; save_cistern(d) end
            return {ok = false, rejected = true, held = true, stage = d.stage, error = why}
        end
        if not dry_run and d.guard_held then d.guard_held = nil; save_cistern(d) end
        if not d.plug_by_hand and gate and gate.closed then
            designate({{x = p.plug.x, y = p.plug.y, text = 'd'}}, zi, 'dig')
            local pos = ('%d,%d,%d'):format(p.plug.x, p.plug.y, zi)
            pcall(dfhack.run_command_silent, 'dig-now', pos, pos)
            local pt = tile_info(p.plug.x, p.plug.y, zi)
            if pt and pt.shape ~= 'WALL' then
                local ok, out = pull(d.lever_id, true)
                if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
                return advance('filling', {plug = 'dug at once', opened = true})
            end
            -- no dig-now here: the old way (the gate opened, a miner digs it),
            -- never down a shaft (the miner would drown fleeing it)
            if p.shaft then
                return {ok = false, rejected = true, needs_player = true,
                        error = 'DFHack\'s dig-now didn\'t dig the plug, and a miner digging it would drown in the shaft'}
            end
            d.plug_by_hand = true
            save_cistern(d)
            local ok, out = pull(d.lever_id)
            if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
            return wait('dig-now isn\'t here: the gate opened, a miner digs the plug')
        end
        -- (0.105.33 L5) never by hand down a shaft (the miner would drown in it)
        if p.shaft then
            return {ok = false, rejected = true, needs_player = true,
                    error = 'the plug can\'t be dug by hand: a miner digging it would drown in the shaft'}
        end
        if not designate({{x = p.plug.x, y = p.plug.y, text = 'd'}}, zi, 'dig') then
            return {ok = false, error = 'the game would not designate the plug'}
        end
        return advance('plug')
    end
    local st = cistern_status()
    -- (0.104.145) the leak guard: water over the cistern (on the well's level
    -- over the room or round it) means it is getting out: the floodgate is
    -- shut at once and the player told
    if d.stage ~= 'dig' and d.stage ~= 'digging' and d.stage ~= 'building' and d.stage ~= 'linking' then
        local leak
        -- (review) the shaft's own column and the tunnel hold water by design
        local own = {}
        if p.shaft then own[p.shaft.x .. ',' .. p.shaft.y] = true end
        if zi == zw then for _, q in ipairs(p.tunnel_path or {}) do own[q.x .. ',' .. q.y] = true end end
        for yy = p.cistern.y1 - 1, p.cistern.y2 + 1 do
            for xx = p.cistern.x1 - 1, p.cistern.x2 + 1 do
                local tt = tile_info(xx, yy, zw)
                if tt and tt.liquid and not tt.magma and not own[xx .. ',' .. yy] then
                    leak = leak or ('x%d y%d elevation %d'):format(xx, yy, ez(zw))
                end
            end
        end
        if not leak and d.leak and gate and gate.closed then
            -- the water gone from over it and it is closed again: tried once
            -- more (a second leak keeps it shut for good)
            local ok_, where, gaps = cistern_sealed(p, d.stage)
            if ok_ == true and (d.leaks or 0) < 2 and not dry_run then
                d.leak = nil
                d.unsealed, d.sealing, d.unsealed_why = nil, nil, nil
                save_cistern(d)
            elseif ok_ ~= true and (d.leaks or 0) < 2 then
                -- (0.105.36 D3) a gap is why it leaked: walled up by the AI
                -- (the leak kept, so no water comes in until it is closed;
                -- a gap the game won't let it close retires it in the brain)
                if not dry_run then d.unsealed = where or d.unsealed; save_cistern(d) end
                local r = cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
                r.leak, r.leaks = d.leak, math.tointeger(d.leaks)
                return r
            end
        end
        if d.leak and not leak then
            -- (v35 fix) waiting (the brain asks again in 2 days), not a refusal
            return {ok = false, rejected = true, waiting = true, leak = d.leak, leaks = math.tointeger(d.leaks),
                    error = 'the cistern leaked at ' .. d.leak .. ': its floodgate stays shut until it is closed '
                        .. 'all round again'}
        end
        if leak then
            if gate and gate.built and not gate.closed and d.lever_id and not dry_run then pull(d.lever_id, true) end
            -- (v35 fix) one leak is counted once, not on every step while the water stands over it
            if not d.leak then d.leaks = (d.leaks or 0) + 1 end
            d.leak = leak
            if not dry_run then save_cistern(d) end
            return {ok = false, rejected = true, waiting = true, leak = leak, shut = true,
                    leaks = math.tointeger(d.leaks),
                    error = 'water over the cistern at ' .. leak .. ': its floodgate shut at once'}
        end
    end
    if d.stage == 'plug' then
        local t = tile_info(p.plug.x, p.plug.y, zi)
        if t and t.shape == 'WALL' then return wait('the plug is being dug (then the water comes in)') end
        return advance('filling')
    end
    if d.stage == 'filling' then
        if st.depth < CISTERN_FULL then
            local why = st.path and (' (gate %s; %s)'):format(st.gate or '?', path_words(st.path)) or ''
            if dry_run then return wait(('the cistern is filling: %d/7%s'):format(st.depth, why)) end
            -- (0.104.100) the gate shut (the flood rule, while dwarves stood in deep
            -- water): reopened after CISTERN_REOPEN_DAYS with nobody in deep water
            -- (Teacheroar sat at 5/7 behind a shut gate from 03:18 all night)
            if gate and gate.built and gate.closed and d.lever_id then
                local now_t = game_tick()
                local wet = citizens_in_deep_water()
                if wet > 0 or not d.shut_seen then
                    d.shut_seen = now_t
                    save_cistern(d)
                end
                if (d.reopens or 0) >= CISTERN_MAX_REOPENS then
                    return wait(('the cistern is filling: %d/7, its floodgate shut after %d floods: it stays shut '
                                 .. '(open it by its lever when the cause is found)'):format(st.depth, d.reopens))
                end
                local days = (now_t - d.shut_seen) // 1200
                if wet == 0 and days >= CISTERN_REOPEN_DAYS and not CISTERN_HOLD then
                    if lever_pull_pending(d.lever_id) then
                        return wait('a dwarf is on the way to pull the cistern\'s lever (reopening it)')
                    end
                    -- (0.104.168) never reopened while it isn't closed where the water
                    -- goes (the gate may have been shut for exactly that): closed first
                    local sealed, where, gaps = cistern_sealed(p, d.stage)
                    if not sealed then
                        if not dry_run then d.unsealed = where; save_cistern(d) end
                        return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
                    end
                    d.unsealed, d.sealing, d.unsealed_why = nil, nil, nil
                    local ok, out = pull(d.lever_id)
                    if not ok then return {ok = false, error = 'lever pull failed: ' .. tostring(out)} end
                    d.reopens, d.shut_seen = (d.reopens or 0) + 1, nil
                    save_cistern(d)
                    return {ok = true, stage = 'filling', reopened = true, depth = st.depth,
                            error = ('the floodgate was shut for a flood; nobody has stood in deep water for %d days: '
                                     .. 'reopened to finish filling (%d of %d)'):format(days, d.reopens, CISTERN_MAX_REOPENS)}
                end
                return wait(('the cistern is filling: %d/7, its floodgate shut (%s): it reopens after %d days with '
                             .. 'nobody in deep water'):format(st.depth, wet > 0 and (wet .. ' in deep water now')
                                                              or (days .. ' day(s) dry so far'), CISTERN_REOPEN_DAYS))
            end
            -- (0.104.94) the source dried up (a surface pool evaporates): after
            -- CISTERN_DRY_DAYS with no water there and none in the cistern, the
            -- floodgate is shut and the cistern retired; the next one is planned
            -- afresh (this room no longer counts as solid rock)
            local src = tile_info(p.water.x, p.water.y, zi)
            -- (r2h1) a river frozen in winter is not dried up: it flows again in spring
            local frozen = p.river and src and src.material == 'FROZEN_LIQUID'
            local dry = st.depth == 0 and not (src and src.liquid) and not frozen
            local now_t = game_tick()
            if frozen and st.depth == 0 then
                return wait(('the cistern is filling: 0/7; its source (%s) is frozen: it fills after the thaw%s')
                            :format(tostring(p.source), why))
            end
            if dry then
                d.dry_since = d.dry_since or now_t
                save_cistern(d)
                if now_t - d.dry_since >= CISTERN_DRY_DAYS * 1200 then
                    if gate and gate.built and not gate.closed and d.lever_id then pull(d.lever_id) end
                    local old = site_get(CISTERN_KEY .. '/retired')
                    table.insert(old, {cistern = p.cistern, source = p.source, why = 'the source dried up', at = now_t})
                    site_put(CISTERN_KEY .. '/retired', old)
                    site_put(CISTERN_KEY, {})
                    return {ok = true, stage = 'retired', retired = true,
                            error = ('the cistern\'s source (%s) dried up for %d days: its floodgate shut and the cistern '
                                     .. 'retired; the next one is planned afresh'):format(tostring(p.source), CISTERN_DRY_DAYS)}
                end
                return wait(('the cistern is filling: 0/7; its source (%s) is dry for %d day(s)%s')
                            :format(tostring(p.source), (now_t - d.dry_since) // 1200, why))
            elseif d.dry_since then
                d.dry_since = nil
                save_cistern(d)
            end
            -- (0.104.96) the tunnel cleared only while there is water to let in
            -- (it ran first and kept the dry check from ever counting)
            -- (0.104.94) a tree grown in the tunnel (a trunk is a wall), or rock
            -- left: felled or dug again
            local blocked = 0
            local way = {}
            for i = 1, #p.tunnel_path - 1 do table.insert(way, p.tunnel_path[i]) end
            table.insert(way, p.plug)
            for _, c in ipairs(way) do
                local t = tile_info(c.x, c.y, zi)
                if t and t.shape == 'WALL' and t.material ~= 'FROZEN_LIQUID' and not t.designated then
                    blocked = blocked + 1
                    if t.material == 'TREE' or t.material == 'ROOT' then
                        fell_tree(c.x, c.y, zi)
                    else
                        designate({{x = c.x, y = c.y, text = 'd'}}, zi, 'dig')
                    end
                end
            end
            if blocked > 0 then
                return wait(('the cistern is filling: %d/7; %d tile(s) on the water\'s way blocked: felled or dug again%s')
                            :format(st.depth, blocked, why))
            end
            -- (0.104.119) water stands no higher than its source: a cistern at
            -- 4/7 or more that hasn't risen for CISTERN_LEVEL_DAYS with its
            -- gate open is as full as it gets (it waited at 5/7 for good)
            local now_t = game_tick()
            if d.depth_seen ~= st.depth or st.gate == 'shut' then
                d.depth_seen, d.depth_tick = st.depth, now_t
                save_cistern(d)
            end
            local still = (now_t - (math.tointeger(d.depth_tick) or now_t)) // 1200
            if not (st.depth >= CISTERN_LEVEL_MIN and still >= CISTERN_LEVEL_DAYS) then
                return wait(('the cistern is filling: %d/7%s'):format(st.depth, why))
            end
        end
        if dry_run then return {ok = true, dry_run = true, stage = 'hole'} end
        if gate and not gate.closed then pull(d.lever_id) end
        if not designate({{x = wx, y = wy, text = 'h'}}, zw, 'dig') then
            return {ok = false, error = 'the game would not channel the well\'s hole'}
        end
        return advance('hole', {depth = st.depth})
    end
    if d.stage == 'hole' then
        local t = tile_info(wx, wy, zw)
        if t and t.shape ~= 'EMPTY' and t.shape ~= 'RAMP_TOP' then return wait('the well\'s hole is being dug') end
        if dry_run then return {ok = true, dry_run = true, stage = 'well'} end
        if not designate({{x = wx, y = wy, text = 'l'}}, zw, 'build') then
            return {ok = false, error = 'the game would not place the well'}
        end
        return advance('well')
    end
    if d.stage == 'well' then
        local w = building_info(wx, wy, zw, 'Well')
        if not w or not w.built then return wait('the well is being built') end
        return advance('done', {depth = st.depth})
    end
    -- done: keep it topped up
    if gate and gate.built and d.lever_id then
        if gate.closed and st.depth < CISTERN_LOW and not CISTERN_HOLD then
            local sealed, where, gaps = cistern_sealed(p, d.stage)
            if not sealed then
                if not dry_run then d.unsealed = where; save_cistern(d) end
                -- (0.104.168) the AI walls it up itself where it safely can; not refilled till then
                return cistern_close_gaps(d, p, gaps, dry_run, save_cistern)
            end
            if not dry_run and (d.unsealed or d.sealing or d.unsealed_why) then
                d.unsealed, d.sealing, d.unsealed_why = nil, nil, nil; save_cistern(d)
            end
            if dry_run then return {ok = true, dry_run = true, refill = true} end
            local ok, out, pending = pull(d.lever_id)
            return {ok = ok, stage = 'done', refill = true, depth = st.depth, pending = pending,
                    error = not ok and out or nil}
        elseif not gate.closed and st.depth >= CISTERN_FULL then
            if dry_run then return {ok = true, dry_run = true, shut = true} end
            local ok, out, pending = pull(d.lever_id)
            return {ok = ok, stage = 'done', shut = true, depth = st.depth, pending = pending,
                    error = not ok and out or nil}
        end
    end
    return {ok = false, rejected = true, done = true, stage = 'done', depth = st.depth,
            error = 'the cistern is built and full enough'}
end
