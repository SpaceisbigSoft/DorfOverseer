-- ai-builder-wells-watch: what may come up a cavern well's shaft (shaft_judge, shaft_threats),
-- the watcher that shuts and opens the gates, the wells' lids (well_lids, seal_well_stairs).
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.
-- (r8) Cut from ai-builder-wells.lua, which had grown to 133 KB; loaded right
-- after it and its parts before this one, in the old file's order.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-wells-watch'] = '0.105.64'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez
local STAIR_DOWN_SHAPE, shaft_bottom, hatch_at, job_of =
    WELLS_PART_LOCALS.STAIR_DOWN_SHAPE, WELLS_PART_LOCALS.shaft_bottom, WELLS_PART_LOCALS.hatch_at, WELLS_PART_LOCALS.job_of
local free_mechanism_count, shaft_kept, abs_now, gate_mem =
    WELLS_PART_LOCALS.free_mechanism_count, WELLS_PART_LOCALS.shaft_kept, WELLS_PART_LOCALS.abs_now, WELLS_PART_LOCALS.gate_mem

-- (0.104.153) A wild animal that attacks: a large predator, or one DF has
-- agitated. (Most of the caverns' thousands of creatures are neither.)
function hostile_wild(u)
    if not dfhack.units.isAnimal(u) or dfhack.units.isFortControlled(u) then return false end
    local okt, tame = pcall(dfhack.units.isTame, u)
    if okt and tame then return false end
    local oka, agit = pcall(function() return u.flags4.agitated_wilderness_creature end)
    if oka and agit then return true end
    local okp, pred = pcall(function() return df.creature_raw.find(u.race).caste[u.caste].flags.LARGE_PREDATOR end)
    return okp and pred or false
end

local function unit_flies(u)
    local ok, f = pcall(function() return u.enemy.caste_flags.FLIER end)
    return ok and f or false
end

-- (0.104.153) The shaft watcher: every SHAFT_WATCH_TICKS inside the game
-- (the brain reads the fort once a game day: a flier crosses 60 tiles
-- sooner), an open shaft gate is shut at once when a real danger comes near
-- below it, and (K48-K4) opened again once shaft_hold says the danger has
-- been away long enough (the brain's well_shaft does the same). Lives while the
-- game runs; `well_lids` says whether it is on, and the `well_shaft`
-- action starts it.
--
-- (group 2, 14 Nov) E and F: the shafts shut for Lizard Devil, Brine
-- Specter, Steam Monster (demons down in the underworld, z 0-2, 140 levels
-- under the shaft: the old "a great danger anywhere below, however far"),
-- and opened again whenever a citizen stepped into a cavern (that rule's
-- exception), well_shaft 49 and 32 times, 186 dead of thirst over the
-- forts. Now (shaft_judge, the brain reads the same verdict in well_lids):
--   * only a danger (isDanger: forgotten beasts, invaders, ...) or a hostile
--     wild animal (agitated, a large predator); never tame, caged, chained,
--     peaceful wildlife (vermin are no units);
--   * only in the shaft itself (its column, 2 tiles round) or in the very
--     cavern the shaft opens into (its map feature; another cavern layer, the
--     magma sea or the underworld is walled off by rock);
--   * by how it could come up: a flier within SHAFT_NEAR, a climber
--     (grasping parts) within SHAFT_CLIMB, one that only walks or swims
--     within SHAFT_CLOSE, great (a forgotten beast) or not;
--   * a shut gate counts it SHAFT_MARGIN tiles further (no flapping at the
--     edge), stays shut SHAFT_MIN_SHUT ticks at least and opens only once no
--     danger was seen for SHAFT_CLEAR ticks (not while short of water).
-- (K48-K4) War-hold and the Garden: every cavern well shut for the life of
-- one forgotten beast 80-95 tiles off (the great ranges were 80, 95 once
-- shut: most of a 192-tile layer). The watcher looks every 100 ticks, so the
-- ranges need only cover what a creature crosses in that time and more: the
-- great ranges are gone, and the watcher opens what it shut once the danger
-- is dead, caged or away (it no longer waits for the brain).
SHAFT_WATCH_TICKS = 100
SHAFT_CLOSE = 20        -- a walker or swimmer this near below (tiles, levels counted too)
SHAFT_CLIMB = 25        -- a climber (or one whose body can't be read) this near
SHAFT_NEAR = 40         -- a flier this near
SHAFT_FAR = SHAFT_NEAR  -- (kept for older callers: no longer a range of its own)
SHAFT_MARGIN = 10       -- a shut gate: counted this much further (hysteresis)
SHAFT_DRY_MARGIN = 5    -- ...a walker's, while the fort is short of water
SHAFT_LEVELS = 15       -- the cavern unknown (no map feature): only this many levels below
SHAFT_MIN_SHUT = 1200   -- ticks (a game day) a shut gate stays shut at least
SHAFT_CLEAR = 600       -- ticks no danger may be seen before it opens again
SHAFT_WATCH = SHAFT_WATCH or {on = false}

-- Pure: may this creature come up this shaft? c = {x, y, z, great, flier,
-- climber (nil: unknown, taken as yes), layer_match (true: the shaft's own
-- cavern, false: another, nil: unknown)}, w = {x, y, z (the well), hz (the
-- shaft's bottom)}, opts = {shut, dry}. The verdict {d, in_shaft, mobile,
-- great, reach} or nil.
function shaft_judge(c, w, opts)
    opts = opts or {}
    local dx = math.max(math.abs(c.x - w.x), math.abs(c.y - w.y))
    if c.z >= w.hz then
        if c.z < w.z and dx <= 2 then
            return {d = dx, in_shaft = true, mobile = true, great = c.great or nil, reach = 2}
        end
        return nil                       -- above the cavern, not in the shaft: the fort's own watch
    end
    if c.layer_match == false then return nil end
    local dz = w.hz - c.z
    if c.layer_match == nil and dz > SHAFT_LEVELS then return nil end
    local d = math.max(dx, dz)
    local mobile = (c.flier == true) or (c.climber ~= false)
    local reach
    if c.flier == true then
        reach = SHAFT_NEAR
    elseif mobile then
        reach = SHAFT_CLIMB
    else
        reach = SHAFT_CLOSE
    end
    if opts.shut then
        -- short of water a walker's margin is smaller (the brain's SHAFT_DRY_REACH: 20 + 5)
        reach = reach + ((opts.dry and not mobile) and SHAFT_DRY_MARGIN or SHAFT_MARGIN)
    end
    if d > reach then return nil end
    return {d = d, mobile = mobile, great = c.great or nil, reach = reach}
end

-- Ticks before a shut gate may be opened again (0: now).
function shaft_hold(pid, sg, now)
    if SHAFT_WATCH.dry then return 0 end
    now = now or abs_now()
    local g = (SHAFT_WATCH.gates or {})[pid] or {}
    local shut_at = g.shut_at or (type(sg) == 'table' and sg.shut_at) or nil
    if not shut_at or now < shut_at then return 0 end
    local seen = g.seen or shut_at
    if now < seen then seen = shut_at end
    return math.max(0, SHAFT_MIN_SHUT - (now - shut_at), SHAFT_CLEAR - (now - seen))
end

-- (0.105.33 L5) DFHack cancels every non-'frames' timer when the world
-- unloads, so a saved timer id can be dead: ask DFHack, not the id.
local function shaft_watch_alive()
    if not (SHAFT_WATCH.on and SHAFT_WATCH.timer) then return false end
    if type(dfhack.timeout_active) ~= 'function' then return true end   -- (no way to ask: the id taken at its word)
    local ok, active = pcall(dfhack.timeout_active, SHAFT_WATCH.timer)
    return (ok and active) and true or false
end

if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-builder-wells-watch'] = function(sc)
        if sc == SC_MAP_UNLOADED then SHAFT_WATCH = {on = false} end
    end
end

-- (group 2) climbing takes a grasping part (DF: no hands, no climbing).
-- nil when the raws can't be read (then taken as a climber).
local function unit_climbs(u)
    local ok, yes = pcall(function()
        for _, bp in ipairs(df.creature_raw.find(u.race).caste[u.caste].body_info.body_parts) do
            if bp.flags.GRASP then return true end
        end
        return false
    end)
    if ok then return yes end
    return nil
end

-- the map feature (a cavern layer) a tile's block belongs to; nil: none or unknown
local function feature_at(x, y, z)
    local ok, f = pcall(function()
        local b = dfhack.maps.getTileBlock(x, y, z)
        return b and b.global_feature
    end)
    if ok and type(f) == 'number' and f >= 0 then return f end
    return nil
end

-- The worst danger for each well: {[i] = {u, v}} (v: shaft_judge's verdict),
-- the nearest one, one in the shaft first. wells: {x, y, z, hz, shut}.
function shaft_threats(wells)
    local out = {}
    for _, w in ipairs(wells) do
        if w.cave == nil then w.cave = feature_at(w.x, w.y, w.hz - 1) or feature_at(w.x, w.y, w.hz) or false end
    end
    local dry = SHAFT_WATCH.dry == true
    for _, u in ipairs(df.global.world.units.active) do
        pcall(function()
            if not dfhack.units.isActive(u) or dfhack.units.isDead(u) or dfhack.units.isCitizen(u, true) then return end
            if u.flags1.caged or u.flags1.chained then return end
            local okf, fort = pcall(dfhack.units.isFortControlled, u)
            if okf and fort then return end
            local okt, tame = pcall(dfhack.units.isTame, u)
            if okt and tame then return end
            local danger = dfhack.units.isDanger(u)
            if not (danger or hostile_wild(u)) then return end
            local okg, great = pcall(dfhack.units.isGreatDanger, u)
            local c = {x = u.pos.x, y = u.pos.y, z = u.pos.z, great = (okg and great) or nil,
                       flier = unit_flies(u)}
            local uf, asked
            for i, w in ipairs(wells) do
                if c.z < w.hz then
                    if not asked and c.flier ~= true then c.climber, asked = unit_climbs(u), true end
                    if w.cave then
                        if uf == nil then uf = feature_at(c.x, c.y, c.z) or false end
                        c.layer_match = (uf == w.cave)
                    else
                        c.layer_match = nil
                    end
                end
                local v = shaft_judge(c, w, {shut = w.shut, dry = dry})
                if v then
                    v.flier = c.flier or nil
                    v.climber = (c.climber == true) or nil
                    local old = out[i]
                    if not old or (v.in_shaft and not old.v.in_shaft)
                            or (not old.v.in_shaft and v.d < old.v.d) then
                        out[i] = {u = u, v = v}
                    end
                end
            end
        end)
    end
    return out
end

-- (0.105.48, K3) the AI halted in the game: false when it can't be read
local function ai_halted()
    local ok, yes = pcall(function() return reqscript('ai-status').is_halted() end)
    return ok and yes == true
end

-- (K48-K4b, A4 17) The in-game timers (this watcher every 100 ticks, the
-- well-safety one every 50) decoded the whole project record on every beat.
-- A timer keeps its decoded copy in its own state table (emptied on map
-- unload) and decodes again only once save_projects has written since
-- (PROJECTS_GEN), or WATCH_RELOAD ticks have passed.
WATCH_RELOAD = 1200
function watch_projects(st)
    local gen, now = PROJECTS_GEN or 0, abs_now()
    if st.pdata and st.pgen == gen and now >= (st.ptick or 0) and now - (st.ptick or 0) < WATCH_RELOAD then
        return st.pdata
    end
    st.pdata, st.pgen, st.ptick = load_projects(), gen, now
    return st.pdata
end
function watch_projects_saved(st, data)
    st.pdata, st.pgen = data, PROJECTS_GEN or 0
end

local function shaft_watch_tick()
    SHAFT_WATCH.timer = nil
    if not SHAFT_WATCH.on then return end
    -- (0.105.48, K3) halted: no hatch shut; looked at again later
    if ai_halted() then
        SHAFT_WATCH.halted = true
        SHAFT_WATCH.timer = dfhack.timeout(SHAFT_WATCH_TICKS, 'ticks', shaft_watch_tick)
        return
    end
    SHAFT_WATCH.halted = nil
    local ok, err = pcall(function()
        local wells = {}
        local data = watch_projects(SHAFT_WATCH)      -- (K48-K4b, A4 17) not decoded every beat
        for _, p in ipairs(data.list) do
            -- a linked gate (its ids saved): only its hatch and lever read, not every
            -- building's links (this runs 12 times a game day)
            local sg = p.shaft_gate
            if p.kind == 'well' and sg and sg.lever_id and sg.hatch_id and not sg.impossible then
                local a = anchor_of(p)
                local h = hatch_at(a.x, a.y, shaft_bottom(p))
                if h and h.built and h.id == sg.hatch_id then
                    table.insert(wells, {x = a.x, y = a.y, z = p.z, hz = shaft_bottom(p), id = p.id, p = p,
                                         lever_id = sg.lever_id, shut = h.closed and true or false})
                end
            end
        end
        if #wells == 0 then return end
        local now, saved = abs_now(), false
        local hits = shaft_threats(wells)
        for i, hit in pairs(hits) do
            local w = wells[i]
            local g = gate_mem(w.id)
            g.seen = now
            if not w.shut then
                local pending = job_of(w.lever_id, df.job_type.PullLever)
                if pending then pcall(dfhack.job.removeJob, pending) end
                pull(w.lever_id, true)
                g.shut_at = now
                w.p.shaft_gate.shut_at = now
                w.p.shaft_gate.auto_shut = true       -- (K48-K4) shut for a danger: the watcher opens it again
                saved = true
                SHAFT_WATCH.last = {project_id = w.id, tick = df.global.cur_year_tick, year = df.global.cur_year,
                                    unit = hit.u and hit.u.id or nil}
            end
        end
        -- (K48-K4) the watcher opens what it (or well_shaft, for a danger)
        -- shut, once no danger is judged near and the hold has run out: with
        -- the brain stopped the wells no longer stay shut for good. Never a
        -- given-up shaft, one the brain shut for its own reason, or one with
        -- a citizen on its shut hatch.
        for i, w in ipairs(wells) do
            local sg = w.p.shaft_gate
            -- (K48-K4b) a gate shut with no mark at all (0.105.47's watcher shut
            -- without one, or a new gate built shut) and no danger near: adopted,
            -- opened by the same rules. Never one the brain shut for its own reason.
            if w.shut and not hits[i] and not sg.auto_shut and not sg.brain_shut and w.p.phase ~= 'cancelled' then
                sg.auto_shut, saved = true, true
            end
            if w.shut and not hits[i] and sg.auto_shut and w.p.phase ~= 'cancelled'
                    and shaft_hold(w.id, sg, now) == 0 and not job_of(w.lever_id, df.job_type.PullLever)
                    and not well_safety_call('gate_block', w.id, false, false) then
                local ok = pull(w.lever_id, true)
                if ok then
                    sg.auto_shut = nil
                    saved = true
                    SHAFT_WATCH.last_open = {project_id = w.id, tick = df.global.cur_year_tick, year = df.global.cur_year}
                end
            end
        end
        if saved and save_projects then
            pcall(save_projects, data)
            watch_projects_saved(SHAFT_WATCH, data)
        end
    end)
    SHAFT_WATCH.error = (not ok) and tostring(err):sub(1, 160) or nil
    SHAFT_WATCH.timer = dfhack.timeout(SHAFT_WATCH_TICKS, 'ticks', shaft_watch_tick)
end

function shaft_watch_start()
    if shaft_watch_alive() then return false end
    SHAFT_WATCH.on = true
    SHAFT_WATCH.timer = dfhack.timeout(SHAFT_WATCH_TICKS, 'ticks', shaft_watch_tick)
    return true
end

-- Each cavern well: {project_id, x, y, z, elevation (the column's top step),
-- state (the lid: none, planned, open, locked, blocked, gone), gate (the
-- shaft gate's state), gate_mechanisms?}.
function well_lids(probe, data)
    OFFSET = elevation_offset()
    local out = {}
    data = data or load_projects()      -- (13c) projects_report passes its own
    for _, p in ipairs(data.list) do
        local st = p.shaft_stairs
        if shaft_kept(p) then
            local top = st[1]
            local r = {project_id = p.id, x = top.x, y = top.y, z = top.z, elevation = ez(top.z)}
            if p.phase == 'cancelled' then r.cancelled = true end    -- (0.105.33 L5) given up, its shaft open
            -- (0.105.26) the shaft's opening into the cavern (where its gate's hatch goes)
            local an0 = anchor_of(p)
            r.shaft_hatch = {x = an0.x, y = an0.y, z = shaft_bottom(p)}
            -- (0.105.4 review) the shaft's last level held undug till the gate's parts are in store
            if p.held then r.held = true; r.hatch_covers = shaft_hatch_covers() end
            if p.released and p.phase == 'dig' then r.breaking = true end
            if p.phase == 'dig' then r.digging = true end       -- (K48-K4b) the miners use the stairs: no lid lock
            -- (K48-K4) the door at a gallery's fort end, locked (the cavern seal):
            -- the well beyond it is cut off from the fort, whatever its shaft gate
            local fd = type(p.fort_door) == 'table' and p.fort_door or nil
            if fd and fd.kind == 'door' and math.tointeger(fd.x) then
                local okd, db = pcall(dfhack.buildings.findAtTile, xyz2pos(fd.x, fd.y, fd.z))
                if okd and db then
                    local okf, f = pcall(function() return db.door_flags.forbidden end)
                    if okf and f then r.door_locked = true end
                end
            end
            local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(top.x, top.y, top.z))
            if okb and b then
                if b:getType() ~= df.building_type.Hatch then
                    r.state = 'blocked'
                elseif b:getBuildStage() < b:getMaxBuildStage() then
                    r.state = 'planned'
                else
                    local okf, f = pcall(function() return b.door_flags.forbidden end)
                    r.state = (okf and f) and 'locked' or 'open'
                    r.hatch_id = b.id
                end
            else
                local tl = tile_info(top.x, top.y, top.z)
                r.state = (tl and STAIR_DOWN_SHAPE[tl.shape]) and 'none' or 'gone'
            end
            local okg, g = pcall(shaft_gate_state, p)
            if okg and g then
                r.gate = g.state
                if g.state == 'no_hatch' or g.state == 'unlinked' then r.gate_mechanisms = free_mechanism_count() end
                -- (0.104.156) the ones the lever can reach (a link with others is cancelled)
                local sg = p.shaft_gate or {}
                if g.state == 'unlinked' and sg.lever then
                    local okm, m, far, far_at = pcall(reqscript('ai-gates').free_mechanisms, 2,
                                                      {x = sg.lever.x, y = sg.lever.y, z = sg.lever.z or p.z})
                    if okm and type(m) == 'table' then
                        r.gate_mechanisms_reachable = #m
                        if (far or 0) > 0 then r.gate_mechanisms_far = far end
                        if type(far_at) == 'table' and #far_at > 0 then
                            r.gate_mechanisms_far_at = table.concat(far_at, '; ')
                        end
                        local okg, lg = pcall(walk_group, sg.lever.x, sg.lever.y, sg.lever.z or p.z)
                        if okg then r.gate_lever_group = lg end
                    end
                end
                if sg.link_lost then r.gate_link_lost = sg.link_lost end
                if g.hatch then r.gate_hatch_built = g.hatch.built and true or false end
                r.gate_hatch_standing = g.hatch ~= nil or nil     -- rv2 1: a hatch still at the shaft's bottom
                if g.state == 'open' or g.state == 'closed' or g.state == 'pulling' then     -- (0.104.153)
                    r.watching = shaft_watch_alive()
                    r.watch_error = SHAFT_WATCH.error
                    if SHAFT_WATCH.last and SHAFT_WATCH.last.project_id == p.id then r.watch_last = SHAFT_WATCH.last end
                    -- (0.104.165) what the watcher would shut it for now, by its own test: the
                    -- report's wild list holds only animals in a "Cavern" layer, and the brain
                    -- reopened the gate under a predator the watcher saw (Teacheroar, unit
                    -- 6300), the watcher shutting it again at once. (group 2) The same
                    -- verdict the watcher and well_shaft act on (shaft_judge), and the hold
                    -- left before a shut gate may open (shaft_hold): the brain decides by them.
                    local an = anchor_of(p)
                    local shut = g.state ~= 'open'
                    r.watch_rule = 2
                    local okn, hits = pcall(shaft_threats, {{x = an.x, y = an.y, z = p.z, hz = shaft_bottom(p), shut = shut}})
                    local hit = okn and type(hits) == 'table' and hits[1] or nil
                    if hit and hit.u then
                        local u, v = hit.u, hit.v
                        local okr, nm = pcall(dfhack.units.getReadableName, u)
                        if okr and dfhack.df2utf then local okc, c = pcall(dfhack.df2utf, nm); if okc and c then nm = c end end
                        r.watch_near = {id = u.id, name = okr and nm or nil,
                                        pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z},
                                        d = v.d, reach = v.reach, great = v.great, flier = v.flier,
                                        climber = v.climber, mobile = v.mobile and true or false,
                                        in_shaft = v.in_shaft}
                    end
                    if shut then
                        local okh, hold = pcall(shaft_hold, p.id, p.shaft_gate)
                        r.shut_hold = okh and hold or 0
                    end
                    if SHAFT_WATCH.dry then r.watch_dry = true end
                end
            else
                r.gate_error = tostring(g):sub(1, 120)
            end
            table.insert(out, r)
        end
    end
    return out
end

-- The stair lid, only where the shaft gate can't be built: a hatch planned
-- where there is none (buildingplan waits for a hatch cover), a built one
-- locked. {ok, planned, locked, waiting}.
function seal_well_stairs(dry_run)
    local planned, locked, waiting = 0, 0, 0
    local below            -- (0.105.47) who is below a lid left unlocked
    local asked = {}
    local function lid_below(r)
        if asked[r.project_id] == nil then asked[r.project_id] = well_safety_call('lid_block', r.project_id) or false end
        return asked[r.project_id] or nil
    end
    for _, r in ipairs(well_lids(false)) do
        if r.gate ~= 'none_possible' then
            -- the gate seals the cavern: the lid stays unlocked (the way down to it)
        elseif r.gate_hatch_standing then
            -- rv2 1: a failed hatch still stands shut at the shaft's bottom: a
            -- dwarf must go down these stairs to take it away first
            waiting = waiting + 1
        elseif r.state == 'none' then
            if dry_run then
                planned = planned + 1
            else
                local okq, s = pcall(quickfort_apply, 'build', {{x = 0, y = 0, text = 'H'}}, r.z, r.x, r.y)
                if okq and stat(s, 'build_designated') == 1 then planned = planned + 1 else waiting = waiting + 1 end
            end
        elseif r.state == 'open' and r.digging then
            -- (K48-K4b, A4 12) the shaft still dug from the bottom up: the miners
            -- go down these stairs; the lid is locked once it is finished
            waiting = waiting + 1
        elseif r.state == 'open' and lid_below(r) then
            -- (0.105.47) a dwarf below the lid (the stair column, the shaft, the
            -- cavern under it): not locked on them; tried again next time
            -- (A's Nomal: the lid locked with no look below, ~1580)
            waiting = waiting + 1
            below = below or lid_below(r)
        elseif r.state == 'open' then
            if not dry_run then
                local b = df.building.find(r.hatch_id)
                if b then util_module().lock_door(b, true, 'well') end   -- (0.105.47) the walk map redone
            end
            locked = locked + 1
        elseif r.state == 'planned' then
            waiting = waiting + 1
        end
    end
    if planned + locked == 0 then
        return {ok = false, rejected = true, waiting = waiting, below = below,
                error = below and ('not locked: ' .. tostring(below) .. ' is below the stair lid (tried again later)')
                    or 'no cavern well stair to close'}
    end
    return {ok = true, planned = planned, locked = locked, waiting = waiting, below = below, dry_run = dry_run or nil}
end
