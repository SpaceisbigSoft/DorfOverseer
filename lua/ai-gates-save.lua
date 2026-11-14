-- ai-gates-save: the watcher's state kept with the save, and citizens stranded outside.
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-save'] = '0.105.43'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, key, unkey, pull, DAY_TICKS = U, key, unkey, pull, DAY_TICKS   -- (13e) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- (0.105.0) The watcher's state kept with the save. GATES lives only in
-- Lua memory and is cleared when the map unloads: a drawbridge the watcher
-- raised before a reload (or a crash and the reviver's load) was never
-- lowered by open_all, which knew nothing of it. What the watcher holds
-- (armed, and each closed entrance's gates by building id: entrance ids are
-- list places and change) goes into the site data whenever it changes, and
-- comes back after a load: the watcher re-armed once the entrances are
-- scanned again, closed gates matched to their entrances; before the scan,
-- open_all opens the saved gates directly.
-- Kept in its own functions: wrappers round arm, open_all, check and summary.
---------------------------------------------------------------------------
GATES_SAVE_KEY = 'ai-overseer/gates'
-- (apart from GATES, which a scan rebuilds): read back yet, what was read, what was last written
GATES_SAVE = GATES_SAVE or {}

local function saved_read()
    return U.site_get(GATES_SAVE_KEY, {})
end

-- What the watcher holds now, by building id.
function gates_snapshot()
    local gates = {}
    for _, e in ipairs(GATES.entrances or {}) do
        -- (0.105.33 fix) one being opened (the dwarf's pull is on its way and
        -- survives the reload) is not saved as a plain close (it was raised
        -- again once lowered); (0.105.36, D2) it is saved with `opening`, so
        -- after a reload it is still the AI's and its opening goes on (left
        -- out, a bridge still up read as the player's gate: never lowered)
        if GATES.closed and GATES.closed[e.id] then
            local opening = (GATES.opening and GATES.opening[e.id]) and true or nil
            -- (0.105.36 fix) only the pieces the AI shut: the player's stay theirs after a reload
            for _, g in ipairs(e.equipment or {}) do
                if ai_piece(e, g) then table.insert(gates, {id = g.id, kind = g.kind, lever_id = g.lever_id,
                                     drive_lever = g.lever_driven and g.drive_lever or nil,     -- (0.105.23)
                                     opening = opening}) end
            end
            for _, g in ipairs(e.outer or {}) do         -- (0.105.23) the gatehouse's bridge
                if ai_piece(e, g) then
                    table.insert(gates, {id = g.id, kind = g.kind, lever_id = g.lever_id, opening = opening})
                end
            end
        end
    end
    -- (0.105.32) where a stuck gate was taken down (no lever-driven piece there for a year)
    -- (0.105.33) the most dangers seen at once since armed (a restored lockdown keeps its rule)
    return {armed = GATES.armed == true, gates = gates, stuck_removed = stuck_removed_live(),
            peak = GATES.armed and type(GATES.peak) == 'number' and GATES.peak or nil}
end

local function same_snapshot(a, b)
    if (a.armed == true) ~= (b.armed == true) then return false end
    if a.peak ~= b.peak then return false end         -- (0.105.33)
    local sa, sb = a.stuck_removed or {}, b.stuck_removed or {}
    for k, v in pairs(sa) do if sb[k] ~= v then return false end end
    for k, v in pairs(sb) do if sa[k] ~= v then return false end end
    local ga, gb = a.gates or {}, b.gates or {}
    if #ga ~= #gb then return false end
    for i = 1, #ga do
        if ga[i].id ~= gb[i].id or ga[i].lever_id ~= gb[i].lever_id then return false end
        if (ga[i].opening == true) ~= (gb[i].opening == true) then return false end   -- (0.105.36)
    end
    return true
end

-- Into the save when it changed. Not before the saved state was read back
-- (a fresh GATES after a reload must not write over what the save holds).
function gates_persist()
    -- (nor while the saved state waits for a scan to be matched up)
    if not GATES_SAVE.restored or GATES_SAVE.saved then return false end
    local snap = gates_snapshot()
    if GATES_SAVE.persisted and same_snapshot(snap, GATES_SAVE.persisted) then return false end
    local ok = U.site_put(GATES_SAVE_KEY, snap)
    if ok then GATES_SAVE.persisted = snap end
    return ok
end

-- Open the saved gates straight from their building ids (no scan needed).
-- Returns opened, still waiting.
function open_saved_gates(saved)
    local opened, waiting = 0, 0
    local held = seal_holds()            -- (0.105.26 seal fix) the cavern seal's stay shut
    for _, g in ipairs(saved.gates or {}) do
        local b = df.building.find(g.id)
        if b and seal_has(held, g) then
            waiting = waiting + 1
        elseif b then
            if g.kind == 'bridge' then
                local ok, raised = pcall(function() return b.gate_flags.raised end)
                if ok and raised then
                    if g.lever_id and #b.jobs == 0 and not bridge_occupied(b) and pull(g.lever_id) then
                        opened = opened + 1
                    end
                    waiting = waiting + 1
                end
            else
                local ok = pcall(function()
                    if b.door_flags.forbidden then b.door_flags.forbidden = false opened = opened + 1 end
                end)
                if not ok then waiting = waiting + 1 end
                -- (0.105.23) a hatch on a lever: its lever opens it (at once)
                if ok and g.drive_lever and door_shut(b) then
                    if pull_instant(g.drive_lever) then
                        opened = opened + 1
                        pcall(note_split_after_open, g, b)      -- (0.105.32)
                    else
                        waiting = waiting + 1
                    end
                end
            end
        end
    end
    return opened, waiting
end

-- After a load: the saved state read back once; once the entrances are
-- scanned, the watcher re-armed and the closed gates matched up.
function gates_restore()
    if not GATES_SAVE.restored then
        GATES_SAVE.restored = true
        local saved = saved_read()
        GATES_SAVE.persisted = saved
        -- (0.105.32) the stuck gates taken down, kept whatever else was saved
        GATES.stuck_removed = type(saved.stuck_removed) == 'table' and copy_stuck(saved.stuck_removed) or nil
        -- (nothing closed and not armed: nothing to bring back)
        if saved.armed or next(saved.gates or {}) ~= nil then GATES_SAVE.saved = saved end
    end
    local saved = GATES_SAVE.saved
    if not saved or not GATES.scanned or not GATES.entrances then return nil end
    GATES_SAVE.saved = nil
    local ids, op = {}, {}
    for _, g in ipairs(saved.gates or {}) do
        ids[g.id] = true
        if g.opening then op[g.id] = true end       -- (0.105.36, D2) being opened when saved
    end
    local closed, opening = {}, {}
    for _, e in ipairs(GATES.entrances) do
        for id in pairs(entrance_gate_ids(e)) do       -- (0.105.33) the outer drawbridge too
            if ids[id] then closed[e.id] = true end
            if op[id] then opening[e.id] = true end
        end
    end
    -- (0.105.36 fix) the saved gates are the pieces the AI shut (a save from
    -- before saved every piece of a closed entrance: all of them, as then)
    GATES.mine = type(GATES.mine) == 'table' and GATES.mine or {}
    for id in pairs(ids) do GATES.mine[id] = true end
    if saved.armed and not GATES.armed then
        -- (0.105.33) the closed entrances (and the peak) in place before the first look
        pcall(GATES_ORIG.arm, {closed = closed, opening = opening, peak = saved.peak})
    end
    GATES.closed = GATES.closed or {}
    GATES.opening = GATES.opening or {}
    for id in pairs(closed) do GATES.closed[id] = true end
    -- (0.105.36, D2) still the AI's, and opened (not pulled back shut as a lost close)
    for id in pairs(opening) do if GATES.closed[id] then GATES.opening[id] = true end end
    if not GATES.armed and next(GATES.closed) ~= nil then
        pcall(GATES_ORIG.open_all)     -- (waiting gates: its reopen timer tries again)
    end
    GATES_SAVE.restored_from_save = {armed = saved.armed == true, gates = #(saved.gates or {})}
    return GATES_SAVE.restored_from_save
end

---------------------------------------------------------------------------
-- (0.105.26) Citizens stranded outside. E (3-5 Nov): 8 citizens were shut
-- out after a surface fire and died there; nothing saw it. A citizen is
-- stranded when they stand outside the map of the inside (or on a cut
-- entrance's porch) and can't walk back in: their walk group isn't the
-- fort's interior (the founding stair under its lid, else a meeting hall,
-- else where most citizens inside stand), or every way in from where they
-- stand is shut. Why, when it can be told: a gate the watcher holds shut
-- ("lockdown"), another gate shut ("gate_shut": a raised bridge, a locked
-- door, a lever's hatch), or no way at all ("no_path": a collapse, a fire's
-- ruin, a channel). How long each has been out is counted from the first
-- report that saw them out (a reload starts the count again).
---------------------------------------------------------------------------

STRANDED_SINCE = STRANDED_SINCE or {}      -- unit id -> abs tick first seen outside
STRANDED_MAX = 20                          -- rows reported at most
STRANDED_OUTS = 40                         -- each entrance's outside tiles read for their walk groups

local function wgroup(x, y, z)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    return ok and type(g) == 'number' and g or 0
end

-- The fort's interior: {what, x, y, z, group}, or nil.
function fort_interior()
    for _, e in ipairs(GATES.entrances or {}) do
        if e.lid then
            local okh, h = pcall(lid_hatch, e)
            if okh and h then
                local g = wgroup(h.x, h.y, h.z - 1)
                if g ~= 0 then return {what = 'founding stair', x = h.x, y = h.y, z = h.z - 1, group = g} end
            end
        end
    end
    local okz, zones = pcall(function() return df.global.world.buildings.other.ZONE_MEETING_HALL end)
    for _, zn in ipairs(okz and zones or {}) do
        local okp, x, y, z = pcall(function() return zn.centerx, zn.centery, zn.z end)
        if okp and x then
            local g = wgroup(x, y, z)
            if g ~= 0 then return {what = 'meeting hall', x = x, y = y, z = z, group = g} end
        end
    end
    if GATES.inside then
        local count, best, bg = {}, 0, nil
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            if GATES.inside[key(u.pos.x, u.pos.y, u.pos.z)] then
                local g = wgroup(u.pos.x, u.pos.y, u.pos.z)
                if g ~= 0 then
                    count[g] = (count[g] or 0) + 1
                    if count[g] > best then best, bg = count[g], g end
                end
            end
        end
        if bg then return {what = 'citizens inside', group = bg} end
    end
end

-- Is one gate shut now? A lever's door or hatch by DF's `closed`, a bridge
-- raised, any other door or hatch locked.
local function gate_shut_now(g)
    local okb, b = pcall(df.building.find, g.id)
    if not okb or not b then return false end
    if g.kind == 'bridge' then
        local ok, r = pcall(function() return b.gate_flags.raised end)
        return ok and r or false
    end
    if g.lever_driven then return door_shut(b) == true end
    local ok, f = pcall(function() return b.door_flags.forbidden end)
    return ok and f or false
end

-- One entrance: shut (and by the AI's watcher?), and the walk groups of its
-- outside tiles (where a citizen stands who would come in by it).
local function entrance_ways(e)
    local groups, n = {}, 0
    for k in pairs(e.outs or {}) do
        local x, y, z = unkey(k)
        local g = wgroup(x, y, z)
        if g ~= 0 then groups[g] = true end
        n = n + 1
        if n >= STRANDED_OUTS then break end
    end
    local shut, by_ai = false, false
    if GATES.closed and GATES.closed[e.id] then
        shut, by_ai = true, true
    elseif #(e.equipment or {}) > 0 then
        -- shut when every gate it needs is shut (each one seals it alone? no:
        -- the scan keeps only the ones it needs, so any one open lets them in)
        shut = true
        for _, g in ipairs(e.equipment) do
            if not gate_shut_now(g) then shut = false end
        end
    end
    return {e = e, groups = groups, shut = shut, by_ai = by_ai}
end

local function readable(u)
    local ok, n = pcall(dfhack.units.getReadableName, u)
    if not ok then return 'unit ' .. tostring(u.id) end
    if dfhack.df2utf then
        local okc, c = pcall(dfhack.df2utf, n)
        if okc and c then n = c end
    end
    return n
end

local function on_cavern_tile(p)
    local ok, des = pcall(dfhack.maps.getTileFlags, p.x, p.y, p.z)
    return ok and des and (des.feature_global or des.feature_local) and true or false
end

-- Pure: why a citizen outside can't come in, from their walk group, the
-- interior's, and the ways in. nil: not stranded. Returns cause, way, and
-- (gate_stuck) the piece. (0.105.32) splits: {{e, piece}, ...}, the gates
-- that read open with DF's walk map split at them: a citizen in a split's
-- outside group is held out by that gate ("gate_stuck"), not by no path.
function stranded_cause(g, interior_group, ways, splits)
    if g ~= 0 and g ~= interior_group then
        for _, sp in ipairs(splits or {}) do
            if sp.piece.outside_group == g then return 'gate_stuck', {e = sp.e}, sp.piece end
        end
    end
    local mine, open_way = {}, false
    for _, w in ipairs(ways) do
        if g ~= 0 and w.groups[g] then
            table.insert(mine, w)
            if not w.shut then open_way = true end
        end
    end
    local cut_off = interior_group ~= nil and g ~= 0 and g ~= interior_group
    if #mine > 0 and not open_way then
        -- every way in from where they stand is shut
        local w = mine[1]
        for _, m in ipairs(mine) do if m.by_ai then w = m break end end
        return w.by_ai and (GATES.armed and 'lockdown' or 'gate_shut') or 'gate_shut', w
    end
    if cut_off then return 'no_path', nil end
    return nil
end

-- {interior, list = [{id, name, x, y, z, out_ticks, out_days, cause,
-- in_cavern?, entrance?, by_ai?, danger_near?, gate_danger?, stuck_gate?}],
-- total} or nil without a map of the inside.
function stranded_citizens()
    if not GATES.scanned or not GATES.inside then return nil end
    local now = U.abs_tick()
    -- (0.105.32) the split gates, read now unless the report just did
    if GATES.splits_at ~= now then pcall(gate_splits) end
    local splits = {}
    for _, e in ipairs(GATES.entrances or {}) do
        for _, piece in ipairs(e.split or {}) do table.insert(splits, {e = e, piece = piece}) end
    end
    local interior = fort_interior()
    local ways = {}
    for _, e in ipairs(GATES.entrances or {}) do
        local ok, w = pcall(entrance_ways, e)
        if ok and w then table.insert(ways, w) end
    end
    local porches = {}
    for _, e in ipairs(GATES.entrances or {}) do if e.porch then table.insert(porches, e.porch) end end
    local okv, vis = pcall(visible_dangers)
    vis = okv and vis or {}
    local shared_at, links = {}, nil     -- (0.105.35 merge) an entrance's shared player lever, once a call
    local function shared_of(e)
        if shared_at[e.id] == nil then
            if links == nil then
                local okl, l = pcall(lever_links)
                links = okl and l or {}
            end
            local okp, sh = pcall(players_shared_levers, e, links)
            shared_at[e.id] = okp and sh[1] or false
        end
        return shared_at[e.id] or nil
    end
    local seen, list, total = {}, {}, 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        seen[u.id] = true
        local p = u.pos
        local k = key(p.x, p.y, p.z)
        local out = not GATES.inside[k]
        for _, po in ipairs(porches) do if po[k] then out = true end end
        if not out then
            STRANDED_SINCE[u.id] = nil
        else
            STRANDED_SINCE[u.id] = STRANDED_SINCE[u.id] or now
            local g = wgroup(p.x, p.y, p.z)
            local cause, w, stuck = stranded_cause(g, interior and interior.group or nil, ways, splits)
            if cause then
                total = total + 1
                if #list < STRANDED_MAX then
                    local t = now - STRANDED_SINCE[u.id]
                    local row = {id = u.id, name = readable(u), x = p.x, y = p.y, z = p.z, cause = cause,
                                 out_ticks = t, out_days = t // DAY_TICKS, group = g}
                    if on_cavern_tile(p) then row.in_cavern = true end
                    if stuck then row.stuck_gate = stuck.id end           -- (0.105.32)
                    local near = math.huge
                    for _, d in ipairs(vis) do
                        near = math.min(near, math.max(math.abs(d.pos.x - p.x), math.abs(d.pos.y - p.y))
                                        + 3 * math.abs(d.pos.z - p.z))
                    end
                    if near < math.huge then row.danger_near = near end
                    if w then
                        row.entrance = {id = w.e.id, kind = w.e.kind, x = w.e.x, y = w.e.y, z = w.e.z}
                        row.by_ai = w.by_ai
                        if not w.by_ai then
                            -- (0.105.35 merge) shut on the player's lever that works other things too
                            local sh = shared_of(w.e)
                            if sh then row.entrance.shared_lever, row.entrance.works_other = sh.lever, sh.others end
                        end
                        local gd = math.huge
                        for _, d in ipairs(vis) do
                            local okd, dd = pcall(distance_to, w.e, d.pos)
                            if okd then gd = math.min(gd, dd) end
                        end
                        if gd < math.huge then row.gate_danger = gd end
                    end
                    table.insert(list, row)
                end
            end
        end
    end
    for id in pairs(STRANDED_SINCE) do if not seen[id] then STRANDED_SINCE[id] = nil end end
    return {interior = interior, list = list, total = total}
end

-- (13e) this file's locals the later parts use, as module names (each takes
-- them back as locals of its own)
_ENV.wgroup, _ENV.on_cavern_tile = wgroup, on_cavern_tile
