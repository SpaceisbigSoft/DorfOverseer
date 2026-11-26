-- ai-gates-watch: the watcher's helpers: who is outside, closing and opening an entrance's
-- pieces, the lever links, the danger at a gate (the watcher's look, check(), arm(),
-- open_all(), planned gate buildings and doors are in ai-gates-watch-look).
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-watch'] = '0.105.128'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, key, unkey, gate_name = U, key, unkey, gate_name   -- (13e) the hub's and earlier parts' locals

-- (0.105.0 review) a cut entrance's porch (the open area above its hatches)
-- reads as inside on the map, but a dwarf there is shut out when the hatches
-- lock: counted as outside
function citizens_outside()
    if not GATES.inside then return 0 end
    local porches = {}
    for _, e in ipairs(GATES.entrances or {}) do
        if e.porch then table.insert(porches, e.porch) end
    end
    local n = 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local k = key(u.pos.x, u.pos.y, u.pos.z)
        local out = not GATES.inside[k]
        for _, p in ipairs(porches) do if p[k] then out = true end end
        if out then n = n + 1 end
    end
    return n
end

-- (0.105.3) B (2 Nov): one thief left inside after a siege kept the only
-- hatch shut for 2.5 real hours (1-3 FPS, 6 citizens and 51 visitors shut
-- out). DF's walk groups ignore locked doors and hatches, so "can reach the
-- dwarves" can't tell an enemy inside from one queued at a shut door; the
-- map of the inside can. Inside: on that map, not on a cut entrance's porch,
-- and more than INTRUDER_GATE_MARGIN tiles from every opening (the bit of
-- tunnel in front of a gate reads as inside). nil: no map yet (a reload).
INTRUDER_GATE_MARGIN = 10
function inside_fort(pos)
    if not GATES.scanned or not GATES.inside then return nil end
    local k = key(pos.x, pos.y, pos.z)
    if not GATES.inside[k] then return false end
    for _, e in ipairs(GATES.entrances or {}) do
        if e.porch and e.porch[k] then return false end
        for _, ik in ipairs(e.inside_list or {}) do
            local x, y, z = unkey(ik)
            if math.abs(z - pos.z) <= 2 and math.abs(x - pos.x) <= INTRUDER_GATE_MARGIN
                    and math.abs(y - pos.y) <= INTRUDER_GATE_MARGIN then
                return false
            end
        end
    end
    return true
end

-- (fix41) At the fort's walls: on the same level and within AT_GATE_REACH
-- tiles of one of an entrance's own tiles (its inside line, the tiles just
-- outside it, its porch): at a shut door, before a raised bridge, in the
-- tunnel in front of a gate. (fix41-ff) Measured against the entrances, not
-- every inside tile (an enemy outside a solid wall of the fort is not at a
-- gate), and the same z only (a flier over the roof isn't either). The
-- crossbows shoot at a fire breather only there (brain/planner_firebreath.py):
-- one that "can reach the dwarves" behind shut gates away from them has a
-- way in nobody mapped, and the marksdwarves would walk out along it.
AT_GATE_REACH = 2
function at_fort_walls(pos)
    if not GATES.scanned or not GATES.inside then return nil end
    local function near(k)
        local x, y, z = unkey(k)
        return z == pos.z and math.abs(x - pos.x) <= AT_GATE_REACH and math.abs(y - pos.y) <= AT_GATE_REACH
    end
    for _, e in ipairs(GATES.entrances or {}) do
        for _, k in ipairs(e.inside_list or {}) do if near(k) then return true end end
        for k in pairs(e.outs or {}) do if near(k) then return true end end
        for k in pairs(e.porch or {}) do if near(k) then return true end end
    end
    return false
end

-- The ids of live, loose enemies standing inside the fort (at most 50), or
-- nil without a map of the inside
function intruders_inside()
    if not GATES.scanned or not GATES.inside then return nil end
    local out = {}
    for _, u in ipairs(df.global.world.units.active) do
        local ok, yes = pcall(function()
            return dfhack.units.isAlive(u) and not u.flags1.caged and not u.flags1.chained
                and not dfhack.units.isCitizen(u) and (dfhack.units.isDanger(u) or dfhack.units.isInvader(u))
                and inside_fort(u.pos) == true
        end)
        if ok and yes then table.insert(out, u.id) end
        if #out >= 50 then break end
    end
    return out
end

-- (fix41) The ids of live, loose enemies at the fort's walls (not inside;
-- at most 50), or nil without a map of the inside. (fix41-ff) `ids`: only
-- these units looked at (the fire breathers: the only ones asked about).
function intruders_at_walls(ids)
    if not GATES.scanned or not GATES.inside then return nil end
    local out = {}
    local units = {}
    if type(ids) == 'table' then
        for _, id in ipairs(ids) do
            local u = df.unit.find(id)
            if u then units[#units + 1] = u end
        end
    else
        units = df.global.world.units.active
    end
    for _, u in ipairs(units) do
        local ok, yes = pcall(function()
            return dfhack.units.isAlive(u) and not u.flags1.caged and not u.flags1.chained
                and not dfhack.units.isCitizen(u) and (dfhack.units.isDanger(u) or dfhack.units.isInvader(u))
                and inside_fort(u.pos) ~= true and at_fort_walls(u.pos) == true
        end)
        if ok and yes then table.insert(out, u.id) end
        if #out >= 50 then break end
    end
    return out
end

-- (0.105.4 review) visitors outside the map of the inside (or on a cut
-- entrance's porch): the ones a shut gate keeps out. nil without a map
function visitors_outside()
    if not GATES.scanned or not GATES.inside then return nil end
    local n = 0
    for _, u in ipairs(df.global.world.units.active) do
        local ok, yes = pcall(function()
            if not (dfhack.units.isAlive(u) and dfhack.units.isVisitor(u) and not dfhack.units.isCitizen(u)) then
                return false
            end
            local k = key(u.pos.x, u.pos.y, u.pos.z)
            if not GATES.inside[k] then return true end
            for _, e in ipairs(GATES.entrances or {}) do
                if e.porch and e.porch[k] then return true end
            end
            return false
        end)
        if ok and yes then n = n + 1 end
    end
    return n
end

-- (0.105.48, K2) the absolute tick (nil if unread), for the watcher's own marks
function now_tick_abs()
    local ok, t = pcall(U.abs_tick)
    return ok and t or nil
end

-- (0.105.48, K2) The PullLever jobs waiting at a lever taken away: how many.
local function remove_pulls(lever_id)
    local n = 0
    pcall(function()
        local lv = df.building.find(lever_id)
        local jobs = {}
        for _, j in ipairs(lv and lv.jobs or {}) do
            if j.job_type == df.job_type.PullLever then table.insert(jobs, j) end
        end
        for _, j in ipairs(jobs) do
            if pcall(dfhack.job.removeJob, j) then n = n + 1 end
        end
    end)
    return n
end

-- A pull job waiting at this lever?
local function lever_pull_pending(lever_id)
    local okp, pending = pcall(function()
        local lv = df.building.find(lever_id)
        for _, j in ipairs(lv and lv.jobs or {}) do
            if j.job_type == df.job_type.PullLever then return true end
        end
        return false
    end)
    return okp and pending
end

local function pull(lever_id)
    -- (0.100, review) a pull already waiting at the lever: a second would undo it
    if lever_pull_pending(lever_id) then return false end
    local out, rv = dfhack.run_command_silent('lever', 'pull', '--id', tostring(lever_id))
    return rv == CR_OK
end

-- (0.100, review) a lowering drawbridge crushes whatever stands where it
-- comes down: it isn't lowered while a creature is on its tiles
function bridge_occupied(b)
    local ok, yes = pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if not dfhack.units.isDead(u) and u.pos.z == b.z and u.pos.x >= b.x1 and u.pos.x <= b.x2
                    and u.pos.y >= b.y1 and u.pos.y <= b.y2 then
                return true
            end
        end
        return false
    end)
    return not ok or yes       -- can't tell: treat it as occupied
end

-- (item2, E 26 Nov: a were-cell bridge killed 3 passers-by despite an exact-tile
-- check) u.pos changes only on arrival: a unit stepping onto the bridge, or
-- whose next steps cross it, reads as off it. bridge_watch(b): one pass over
-- units.active (bounding boxes first, each unit read on its own) giving
--   on      one of the fort's own (a citizen, a tame animal, a peaceful guest of
--           the fort's civ; not a danger) on the bridge's tiles (0.105.120's rule)
--   near    one of them beside the footprint (its z, or the ramp levels z-1/z+1
--           beside it, not under it), or whose path's next BRIDGE_PATH_STEPS
--           steps or destination are on it (on counts as near)
--   enemy   a live, loose danger or invader (not the fort's) within IMMINENT of
--           the bridge (|dz| <= 3): true / false, nil when the units can't be read
--   unknown a unit standing within NEAR_BOX (one level), not hostile, whose isCitizen can't be read
--           and whose civ isn't the fort's (fix3: never a danger or invader)
BRIDGE_PATH_STEPS = 3
local NEAR_BOX = BRIDGE_PATH_STEPS + 1     -- tiles: past this no step or ring tile can touch the bridge
function bridge_watch(b)
    local w = {on = false, near = false, enemy = false, unknown = false, blind = false}
    -- (fix2) the fort's civ unread: own by isCitizen alone; the units list
    -- unread: blind (nothing seen: bridge_hold doesn't hold, as before item2)
    local okc, civ = pcall(function() return df.global.plotinfo.civ_id end)
    if not okc then civ = nil end
    local oku, units = pcall(function() return df.global.world.units.active end)
    if not oku or not units then
        w.enemy, w.blind = nil, true
        return w
    end
    local x1, x2, y1, y2, z = b.x1, b.x2, b.y1, b.y2, b.z
    local reach = IMMINENT or 12
    local function on(x, y, zz)
        return zz == z and x >= x1 and x <= x2 and y >= y1 and y <= y2
    end
    -- (fix3) each of a unit's reads on its own: a danger or invader is never
    -- own and never can't-tell (an enemy whose isDead or isCitizen can't be
    -- read still counts as the enemy); can't-tell is only a unit read standing
    -- at the bridge, not hostile, whose isCitizen can't be read and whose civ
    -- isn't the fort's
    local okl = pcall(function()
        for _, u in ipairs(units) do
            local okp, d, dz = pcall(function()
                local p = u.pos
                return math.max(x1 - p.x, p.x - x2, y1 - p.y, p.y - y2, 0), math.abs(p.z - z)
            end)
            -- (fix2) a unit whose position can't be read is no evidence: not counted
            if okp and dz <= 3 and d <= reach then
                local okdead, dead = pcall(function() return dfhack.units.isDead(u) end)
                if not (okdead and dead) then
                    local okd, danger = pcall(function() return dfhack.units.isDanger(u) end)
                    local oki, invader = pcall(function() return dfhack.units.isInvader(u) end)
                    local hostile = (okd and danger == true) or (oki and invader == true)
                    local okc, citizen = pcall(function() return dfhack.units.isCitizen(u, true) end)
                    local okv, same_civ = pcall(function() return civ ~= nil and u.civ_id == civ end)
                    local own = (okc and citizen == true) or (okv and same_civ == true)
                    if hostile then
                        -- one of the fort's own turned dangerous (a were) is neither own nor the enemy, as before
                        if not own and not w.enemy then
                            local okf, loose = pcall(function() return not u.flags1.caged and not u.flags1.chained end)
                            if not okf or loose then w.enemy = true end
                        end
                    elseif own then
                        if dz == 0 and d == 0 then w.on = true end
                        if not w.near and dz <= 1 and d <= NEAR_BOX then
                            if d <= 1 and (dz == 0 or d == 1) then
                                w.near = true          -- on it or beside it (the ramp levels: beside only)
                            else
                                pcall(function()
                                    local path = u.path
                                    local dst = path.dest
                                    if dst and on(dst.x, dst.y, dst.z) then w.near = true; return end
                                    local px, py, pz = path.path.x, path.path.y, path.path.z
                                    for i = 0, math.min(#px, BRIDGE_PATH_STEPS) - 1 do
                                        if on(px[i], py[i], pz[i]) then w.near = true; return end
                                    end
                                end)
                            end
                        end
                    elseif not okc and dz <= 1 and d <= NEAR_BOX then
                        w.unknown = true               -- at the bridge, not hostile, who it is unread
                    end
                end
            end
            if w.on and w.enemy then break end
        end
    end)
    if not okl then w.enemy, w.blind = nil, true end
    return w
end

-- (0.105.120, B 25 Nov 19:42: a stoneworker killed by the surface gate's bridge as
-- it closed for a weresheep) one of the fort's own on the bridge's tiles. A raise
-- flings them, a lowering crushes them: the bridge waits for them either way.
-- true / false, nil when it can't be told.
function own_on_bridge(b)
    local w = bridge_watch(b)
    if w.on then return true end
    if w.unknown then return nil end
    return false
end

-- (item2) Does the AI's pull of this gate bridge wait (close: a raise, else a
-- lowering)? true and why, or false.
--   on the bridge's tiles: always waits (0.105.120)
--   the units list unreadable (blind): not held, raise or lowering (fix2: as
--     before item2; only positive evidence holds a gate)
--   close with an enemy within IMMINENT: the near and can't-tell rules don't
--     hold it (a siege gate must still close)
--   else one of the fort's own near, or a unit read standing at the bridge
--     whose other fields can't be read: waits
--   a lowering also waits while anyone at all is on its tiles (bridge_occupied)
function bridge_hold(b, close)
    local w = bridge_watch(b)
    if w.on then return true, 'own on it' end
    if not w.blind and not (close and w.enemy) then
        if w.near then return true, 'own near' end
        if w.unknown then return true, "can't tell" end
    end
    if not close and bridge_occupied(b) then return true, 'occupied' end
    return false
end

-- (0.105.23, 14.1 step 4a) A lever pulled at once (DFHack's `lever pull
-- --instant`: no dwarf runs to it), as ai-builder's shaft gate does. A pull
-- a dwarf is on the way to make is called off first: arriving late it would
-- toggle the gate back. Tests replace this.
function pull_instant(lever_id)
    pcall(function()
        local lv = df.building.find(lever_id)
        local jobs = {}
        for _, j in ipairs(lv and lv.jobs or {}) do
            if j.job_type == df.job_type.PullLever then table.insert(jobs, j) end
        end
        for _, j in ipairs(jobs) do dfhack.job.removeJob(j) end
    end)
    local ok, out, rv = pcall(dfhack.run_command_silent, 'lever', 'pull', '--id', tostring(lever_id), '--instant')
    -- (0.105.47, J16) an instant pull sets the gate from Lua, not by DF's
    -- own pull (E, 0.105.32: the walk map stayed split after one): redone
    if ok and rv == CR_OK then pcall(repath) end
    return ok and rv == CR_OK
end

-- (0.105.23) Is this door or hatch shut now (DF's `closed`)? nil if unread.
function door_shut(b)
    local ok, c = pcall(function() return b.door_flags.closed end)
    if ok then return c == true end
    return nil
end

-- (0.105.26 seal fix) What the cavern seal (ai-threats) holds: {ids =
-- {building id = true}, levers = {lever id = true}}. While it stands the
-- watcher opens none of them (F lost 54 and C 12 to forgotten beasts that
-- came up through the caverns): not by its reopen, open_all or a lever's
-- hatch. Empty when it can't be read. Tests replace this.
function seal_holds()
    local ok, r = pcall(function() return reqscript('ai-threats').seal_holds() end)
    if ok and type(r) == 'table' and type(r.ids) == 'table' then
        r.levers = type(r.levers) == 'table' and r.levers or {}
        return r
    end
    return {ids = {}, levers = {}}
end

-- (0.105.45) The pieces of the lure pockets (lua/ai-lure.lua: the cavern door
-- it opens, the pocket's gates): {building id = true}. An entrance with one
-- of these is the lure's: the watcher neither shuts nor opens it. Tests replace this.
function lure_holds()
    local ok, r = pcall(function() return reqscript('ai-lure').held_ids() end)
    return ok and type(r) == 'table' and r or {}
end

-- Is this gate held by the seal (h: seal_holds())?
function seal_has(h, g)
    if not h or not g then return false end
    return (h.ids[g.id] or (g.drive_lever ~= nil and h.levers[g.drive_lever])
        or (g.lever_id ~= nil and h.levers[g.lever_id])) and true or false
end

-- Does the seal hold any gate of this entrance?
function sealed_entrance(e, h)
    h = h or seal_holds()
    for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
        for _, g in ipairs(list) do
            if seal_has(h, g) then return true end
        end
    end
    return false
end

-- (0.105.47, live 14 Nov 17:23) A door or hatch locked or unlocked by a
-- bare door_flags.forbidden write: DF doesn't redo its walk groups for it
-- (the hatches read open, the messenger's walk group 6712 still apart from
-- the outside's 1), so DF is asked to redo its walk map
-- (world.reindex_pathfinding, ai-gates-stuck reindex_paths) after each one.
-- (0.105.47, J16) one helper for the whole AI: ai-util's repath (once a
-- tick); GATES.repaths counts the gates' own. lock_gate: a gate piece locked
-- or unlocked through ai-util's lock_door (which repaths), counted the same.
function repath()
    local ok, done = pcall(function() return reindex_paths() end)
    if ok and done then GATES.repaths = (GATES.repaths or 0) + 1 end
    return ok and done or false
end

function lock_gate(b, locked)
    local changed, ok = U.lock_door(b, locked, 'gate')
    if changed then GATES.repaths = (GATES.repaths or 0) + 1 end
    return changed, ok
end

-- (0.105.23) A door or hatch on a lever, set by its lever: true if it was
-- pulled. Without a lever of this entrance's own to pull, it's only locked
-- (as before 0.105.23). `pulled` keeps one pull per lever per call.
local function set_lever_door(g, b, close, pulled)
    if not g.drive_lever then
        return (lock_gate(b, close))
    end
    if not close then lock_gate(b, false) end   -- (a lock left from before the link)
    local shut = door_shut(b)
    if shut == nil or shut == close or pulled[g.drive_lever] then return false end
    pulled[g.drive_lever] = true
    local ok = pull_instant(g.drive_lever)
    -- (0.105.32) E: an instant pull opened the hatch, and DF's walk map stayed split at it
    if ok and not close then pcall(note_split_after_open, g, b) end
    return ok
end

-- (item2) one pull per lever per call (`pulled`, as set_lever_door): a lever
-- working two of the entrance's bridges would otherwise be pulled twice and
-- the second pull undo the first
local function set_bridge(g, b, close, pulled)
    pulled = pulled or {}
    local ok, c = pcall(function() return b.gate_flags.raised end)   -- (13c) not `closed`
    -- (0.105.33) nor while it moves (a pull now would send it back)
    local okm, moving = pcall(function() return b.gate_flags.raising or b.gate_flags.lowering end)
    -- lowering (opening) waits while anyone stands where it comes down;
    -- (0.105.120) raising waits while one of the fort's own stands on it (a
    -- hostile on it is raised under); (item2) both wait while one of the
    -- fort's own is beside it or about to step on it, or the units can't be
    -- read, unless it is a close with an enemy within IMMINENT (bridge_hold)
    if not (ok and c ~= close and not (okm and moving) and g.lever_id and #b.jobs == 0) then return false end
    if pulled[g.lever_id] then return false end
    local held = bridge_hold(b, close)
    if held then
        GATES.bridge_holds = (GATES.bridge_holds or 0) + 1
        return false
    end
    pulled[g.lever_id] = true
    local done = pull(g.lever_id) or false
    -- (0.105.48, K2) a close pull is a dwarf's job: the bridge reads down until
    -- it is done, which is not "found open" (the watcher's own pull on its way)
    if done and close then
        GATES.close_pulled = GATES.close_pulled or {}
        GATES.close_pulled[g.id] = now_tick_abs()
    end
    return done
end

-- (item2) A gate bridge's pull is a dwarf's PullLever job (pull(): the
-- watcher's K2 bookkeeping, close_pulled, the repull and the cancelled
-- opening pulls are all built on it), so the bridge moves when the dwarf gets
-- to the lever, maybe much later than the checks above. Each look, a pull
-- still queued at the lever of one of the AI's gate bridges is looked at
-- again by bridge_hold and taken away while it holds (the dwarf sent off; the
-- watcher's next look pulls again, checked again). A close pull's K2 mark is
-- dropped with it, so the next look repulls it rather than waiting 10 looks.
-- skip: building ids not looked at (the lure's). The count taken away.
function hold_queued_bridge_pulls(skip)
    local n = 0
    skip = skip or {}
    for _, e in ipairs(GATES.entrances or {}) do
        for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
            for _, g in ipairs(list) do
                local b = g.kind == 'bridge' and g.lever_id and not skip[g.id] and df.building.find(g.id)
                if b and ai_piece(e, g) and lever_pull_pending(g.lever_id) then
                    local ok, up, moving = pcall(function()
                        local f = b.gate_flags
                        return f.raised, f.raising or f.lowering
                    end)
                    if ok and not moving and bridge_hold(b, not up) then
                        local k = remove_pulls(g.lever_id)
                        if k > 0 then
                            n = n + k
                            if not up and GATES.close_pulled then GATES.close_pulled[g.id] = nil end
                            if GATES.repulled then GATES.repulled[g.id] = nil end
                        end
                    end
                end
            end
        end
    end
    if n > 0 then GATES.bridge_pulls_held = (GATES.bridge_pulls_held or 0) + n end
    return n
end

-- (0.105.36 fix) Is this gate piece shut now, as the AI shuts it (a bridge
-- raised or rising; a hatch or door on its lever shut; any other door
-- locked)? nil if unread.
function piece_shut(g, b)
    if g.kind == 'bridge' then
        local ok, up = pcall(function()
            local f = b.gate_flags
            return (f.raised and not f.lowering) or f.raising
        end)
        if ok then return up and true or false end
        return nil
    end
    if g.lever_driven and g.drive_lever then return door_shut(b) end
    local ok, f = pcall(function() return b.door_flags.forbidden end)
    if ok then return f == true end
    return nil
end

-- (0.105.36 fix) The pieces the AI itself shut (GATES.mine, by building id:
-- a rescan keeps them). A piece found already shut when the AI closes its
-- entrance is the player's: the AI never books, opens or re-pulls it. An
-- entrance booked closed with none of its pieces in the record (a save or a
-- test from before) counts all of them, as before.
function ai_piece(e, g)
    local mine = GATES.mine
    if type(mine) ~= 'table' then return true end
    if mine[g.id] then return true end
    for id in pairs(entrance_gate_ids(e)) do
        if mine[id] then return false end
    end
    return true
end

-- (0.105.36 fix) An entrance's pieces open now (to be shut by the AI), and
-- whether it has any: what close_threatened_gates acts on.
function open_pieces(e)
    local n = 0
    for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
        for _, g in ipairs(list) do
            local b = not g.well_shaft and df.building.find(g.id)      -- (r9, A4 26) the well's own
            if b and piece_shut(g, b) == false then n = n + 1 end
        end
    end
    return n
end

-- (0.105.36 fix) An entrance being opened shut again: a PullLever job still
-- queued on a raised bridge's lever (the opening's, a dwarf on the way) is
-- taken away, or it lowers the bridge with the danger at it. The count.
local function cancel_opening_pulls(e)
    local n = 0
    for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
        for _, g in ipairs(list) do
            local b = g.kind == 'bridge' and g.lever_id and df.building.find(g.id)
            if b and ai_piece(e, g) then
                local ok, up = pcall(function() return b.gate_flags.raised and not b.gate_flags.lowering end)
                if ok and up and lever_pull_pending(g.lever_id) then
                    n = n + remove_pulls(g.lever_id)
                end
            end
        end
    end
    if n > 0 then GATES.pulls_cancelled = (GATES.pulls_cancelled or 0) + n end
    return n
end

-- (0.105.48, K2) The reverse: an entrance opened or let go while the
-- watcher's close pull (a dwarf on the way) is still queued at a bridge that
-- reads down. Done late it would raise the bridge with no danger and nobody
-- left to lower it (the watcher works booked entrances only): taken away.
function cancel_closing_pulls(e)
    local n = 0
    for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
        for _, g in ipairs(list) do
            local b = g.kind == 'bridge' and g.lever_id and df.building.find(g.id)
            if b and ai_piece(e, g) then
                local ok, down = pcall(function()
                    local f = b.gate_flags
                    return not f.raised and not f.raising and not f.lowering
                end)
                if ok and down and lever_pull_pending(g.lever_id) then
                    n = n + remove_pulls(g.lever_id)
                end
                if ok and down and GATES.close_pulled then GATES.close_pulled[g.id] = nil end
            end
        end
    end
    if n > 0 then GATES.close_pulls_cancelled = (GATES.close_pulls_cancelled or 0) + n end
    return n
end

-- Close (or open) one entrance's gates. (0.105.23) A gatehouse's outer
-- drawbridge is raised before the hatch shuts, and lowered after it opens.
-- (0.105.36 fix) Closing books as the AI's only the pieces it found open (and
-- those it shut before); one already shut is the player's and stays so:
-- the entrance is booked closed only with a piece of the AI's. Opening
-- touches only the AI's pieces. was_opening: the entrance was being opened
-- (its queued pulls taken away first).
local function set_entrance(e, close, was_opening)
    local done, pulled = 0, {}
    GATES.mine = type(GATES.mine) == 'table' and GATES.mine or {}
    local ours = {}                 -- this entrance's pieces that are the AI's
    if close then
        if was_opening then cancel_opening_pulls(e) end
        local booked = GATES.closed and GATES.closed[e.id]
        for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
            for _, g in ipairs(list) do
                local b = df.building.find(g.id)
                local shut = b and piece_shut(g, b)
                if g.well_shaft then
                    -- (r9, A4 26) a cavern well's shaft hatch: its own watcher's, never the gate's
                elseif shut == false or (booked and ai_piece(e, g)) or GATES.mine[g.id] then
                    ours[g.id] = true
                end
            end
        end
        for id in pairs(ours) do GATES.mine[id] = true end
    else
        pcall(cancel_closing_pulls, e)       -- (0.105.48, K2) a close pull still queued: taken away
        for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
            for _, g in ipairs(list) do if ai_piece(e, g) and not g.well_shaft then ours[g.id] = true end end
        end
    end
    -- (0.105.26 seal fix) opening: what the cavern seal holds stays shut
    -- (and keeps the entrance closed: tried again once the seal is gone)
    local held, kept = not close and seal_holds() or nil, 0
    local function outer()
        for _, g in ipairs(e.outer or {}) do
            local b = df.building.find(g.id)
            if not ours[g.id] then
                -- (0.105.36 fix) the player's: left as it is
            elseif b and held and seal_has(held, g) then
                kept = kept + 1
            elseif b and set_bridge(g, b, close, pulled) then done = done + 1 end
        end
    end
    if close then outer() end
    for _, g in ipairs(e.equipment) do
        local b = df.building.find(g.id)
        if not ours[g.id] then
            -- (0.105.36 fix) the player's: left as it is
        elseif b and held and seal_has(held, g) then
            kept = kept + 1
        elseif b then
            if g.kind == 'bridge' then
                if set_bridge(g, b, close, pulled) then done = done + 1 end
            elseif g.lever_driven then
                if set_lever_door(g, b, close, pulled) then done = done + 1 end
            else
                if lock_gate(b, close) then done = done + 1 end
            end
        end
    end
    if not close then outer() end
    -- (0.100, review) a bridge left up (someone on it, a pull waiting) keeps
    -- the entrance closed, so opening tries it again; (0.105.23) so does a
    -- lever's hatch still shut, and the gatehouse's bridge
    local waiting, moving = kept, 0
    if not close then
        for _, list in ipairs({e.equipment, e.outer or {}}) do
            for _, g in ipairs(list) do
                local b = df.building.find(g.id)
                if not ours[g.id] then
                    -- (0.105.36 fix) the player's: never waited for
                elseif b and held and seal_has(held, g) then
                    -- (counted above)
                elseif b and g.kind == 'bridge' then
                    local ok, raised = pcall(function()
                        local f = b.gate_flags
                        return f.raised or f.lowering or f.raising      -- (0.105.48, K2) rising too
                    end)
                    if ok and raised then waiting, moving = waiting + 1, moving + 1 end
                elseif b and g.lever_driven and g.drive_lever and door_shut(b) then
                    waiting, moving = waiting + 1, moving + 1
                end
            end
        end
    end
    -- (0.105.36 fix) closing: booked only with a piece of the AI's (one it
    -- found open, or shut before); an entrance all of whose gates the player
    -- shut stays theirs, unbooked
    GATES.closed[e.id] = ((close and next(ours) ~= nil) or (not close and waiting > 0)) or nil   -- (a pull on its way still reads raised: retried harmlessly)
    if not close then
        -- the AI's pieces that are open again are no longer its shut ones
        for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
            for _, g in ipairs(list) do
                local b = ours[g.id] and df.building.find(g.id)
                if b and piece_shut(g, b) == false then GATES.mine[g.id] = nil end
            end
        end
        if not GATES.closed[e.id] then
            for id in pairs(ours) do
                local b = df.building.find(id)
                if not b then GATES.mine[id] = nil end
            end
        end
    end
    -- (0.105.33) opening, a gate not down yet (a dwarf's pull on its way, someone
    -- on the bridge): the entrance is being opened, not held shut. The watcher's
    -- look then neither re-pulls it as a lost close nor counts clear looks again;
    -- it tries the opening again (what the cavern seal keeps is the old wait)
    GATES.opening = GATES.opening or {}
    GATES.opening[e.id] = (not close and moving > 0) or nil
    return done
end

-- (0.105.23, 14.1 step 4a) A hatch (or door) its lever's link shut: DF
-- shuts a door or hatch when a lever is linked to it, and the founding
-- stair's hatch is every fort's way in, so it would stay shut with the
-- dwarves on either side of it. Opened at once by its lever wherever the
-- watcher doesn't hold the entrance shut. Only the surface's gates, and
-- only by an "AI gate..." lever that works nothing outside this entrance (a
-- cavern well's shaft hatch is its own rule's; the player's own levers are
-- theirs). only_e: that entrance alone. Returns how many were opened.
function open_lever_hatches(only_e)
    local opened = 0
    for _, e in ipairs(only_e and {only_e} or GATES.entrances or {}) do
        if e.kind == 'surface' and not (GATES.closed and GATES.closed[e.id]) then
            local pulled, held = {}, nil
            for _, g in ipairs(e.equipment or {}) do
                if g.lever_driven and g.drive_lever and g.drive_ai and not pulled[g.drive_lever] then
                    local b = df.building.find(g.id)
                    held = (b and door_shut(b)) and (held or seal_holds()) or held   -- (0.105.26 seal fix)
                    if b and door_shut(b) and not seal_has(held, g) then
                        pulled[g.drive_lever] = true
                        if pull_instant(g.drive_lever) then
                            opened = opened + 1
                            pcall(note_split_after_open, g, b)      -- (0.105.32)
                        end
                    end
                end
            end
        end
    end
    if opened > 0 then
        GATES.lever_opened = (GATES.lever_opened or 0) + opened
        pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %d gate(s) on a lever opened (no danger near)'):format(opened),
              COLOR_GREEN, false)
    end
    return opened
end

-- (0.105.23) A link the mechanic has just made: the gate takes the lever at
-- once (no wait for the weekly scan), so the watcher can work it and the
-- hatch the link shut is opened; a full rescan is asked for too (the
-- report's `rescan`). Returns how many gates took a lever.
function attach_links()
    local levers, pos = lever_links()
    local n = 0
    for _, e in ipairs(GATES.entrances or {}) do
        for _, g in ipairs(e.equipment or {}) do
            if g.kind ~= 'bridge' and levers[g.id] then
                local have = {}
                for _, l in ipairs(g.levers or {}) do have[l.id] = true end
                local new = false
                for _, lid in ipairs(levers[g.id]) do
                    if not have[lid] and pos[lid] then
                        g.levers = g.levers or {}
                        local p = pos[lid]
                        table.insert(g.levers, {id = lid, x = p.x, y = p.y, z = p.z, name = p.name,
                                                targets = lever_targets(levers, lid)})
                        new = true
                    end
                end
                if new then
                    g.lever_driven = true
                    g.lever_id = g.lever_id or g.levers[1].id
                    n = n + 1
                end
            end
        end
    end
    if n > 0 then
        drive_levers(GATES.entrances)
        GATES.rescan = true
    end
    return n
end

-- A link job waiting at an "AI gate..." lever?
function link_jobs_pending()
    local ok, yes = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and ai_lever_name(b.name) then
                for _, j in ipairs(b.jobs) do
                    if j.job_type == df.job_type.LinkBuildingToTrigger then return true end
                end
            end
        end
        return false
    end)
    return ok and yes
end

-- The link watch: while a link job waits at an AI lever, every CHECK_TICKS
-- the new links are taken up and a hatch they shut is opened.
LINK_WATCH = LINK_WATCH or {}
local function link_watch_tick()
    LINK_WATCH.timer = nil
    if ai_halted() then          -- (0.105.48, K3) halted: no link taken up, no lever pulled; looked at again later
        LINK_WATCH.timer = dfhack.timeout(CHECK_TICKS, 'ticks', link_watch_tick)
        return
    end
    pcall(attach_links)
    if not GATES.armed then pcall(open_lever_hatches) end
    if link_jobs_pending() then
        LINK_WATCH.timer = dfhack.timeout(CHECK_TICKS, 'ticks', link_watch_tick)
    end
end

function link_watch_start()
    local ok, active = pcall(function() return LINK_WATCH.timer and dfhack.timeout_active(LINK_WATCH.timer) end)
    if ok and active then return false end
    LINK_WATCH.timer = dfhack.timeout(CHECK_TICKS, 'ticks', link_watch_tick)
    return true
end

-- (0.105.3) A (2 Nov, 09:36): "The Human Swordsman was spotted sneaking
-- around!", the hatch shut with 9 citizens outside, then he hid again and
-- nothing visible was left, yet the hatch stayed shut (1 FPS). Only VISIBLE
-- dangers count now (a hidden one isn't seen by anyone; the brain's report
-- leaves them out too): {pos, invader}. Tests replace this.
-- (0.105.48, K1) Small wildlife is no reason to shut a gate: an agitated
-- animal (no invader, no great danger, no night creature or undead) under
-- WILD_GATE_SIZE (the brain's wildlife_alarm_size) is left to the hunting
-- squads (War-hold: a falcon kept the gates armed for 30 days).
WILD_GATE_SIZE = 2000000
function small_wildlife(u)
    local ok, yes = pcall(function()
        if not dfhack.units.isAnimal(u) or dfhack.units.isInvader(u) or dfhack.units.isGreatDanger(u)
                or dfhack.units.isNightCreature(u) or dfhack.units.isUndead(u) then
            return false
        end
        local size = u.body.size_info.size_cur
        return type(size) == 'number' and size < WILD_GATE_SIZE
    end)
    return ok and yes == true
end

-- (0.105.51) A pack is no small wildlife: C (R3, winter 251) lost 10 of 14
-- dwarves to 9 giant dingoes, large predators DF never calls a danger, and
-- no gate shut. The wild animals (agitated, or hostile: ai-builder
-- hostile_wild) of WILD_PACK_SIZE or more, free, seen, not the fort's and not
-- in a cavern (the cavern alarm is its own): WILD_PACK_MIN or more on the map
-- are all dangers here (the brain's wild_pack sounds the alarm for them).
-- {[id] = true}. `list`: the units (all active ones by default).
WILD_PACK_MIN = 3
WILD_PACK_SIZE = 10000
function wild_pack_ids(list)
    list = list or df.global.world.units.active
    local hw
    pcall(function() hw = reqscript('ai-builder').hostile_wild end)
    local members = {}
    for _, u in ipairs(list) do
        local ok, yes = pcall(function()
            local U = dfhack.units
            if not U.isAnimal(u) or u.flags1.caged or u.flags1.chained then return false end
            if not U.isAlive(u) or U.isHidden(u) or U.isCitizen(u) or U.isFortControlled(u) then return false end
            if U.isInvader(u) or U.isGreatDanger(u) or U.isNightCreature(u) or U.isUndead(u) then return false end
            local okt, tame = pcall(U.isTame, u)
            if okt and tame then return false end
            local size = u.body.size_info.size_cur
            if type(size) ~= 'number' or size < WILD_PACK_SIZE then return false end
            if not U.isDanger(u) and not (type(hw) == 'function' and hw(u) == true) then return false end
            local des = dfhack.maps.getTileFlags(u.pos.x, u.pos.y, u.pos.z)
            if not des or des.hidden or des.feature_local or des.feature_global then return false end
            return true
        end)
        if ok and yes then table.insert(members, u.id) end
    end
    local out = {}
    if #members >= WILD_PACK_MIN then
        for _, id in ipairs(members) do out[id] = true end
    end
    return out
end

function visible_dangers()
    local out = {}
    local okp, pack = pcall(wild_pack_ids)
    if not okp or type(pack) ~= 'table' then pack = {} end
    for _, u in ipairs(df.global.world.units.active) do
        local ok, yes = pcall(function()
            if pack[u.id] then return true end
            return dfhack.units.isAlive(u) and not u.flags1.caged and not u.flags1.chained
                and not dfhack.units.isCitizen(u) and not dfhack.units.isHidden(u)
                and (dfhack.units.isDanger(u) or dfhack.units.isInvader(u))
                and not small_wildlife(u)
        end)
        if ok and yes then
            local oki, inv = pcall(dfhack.units.isInvader, u)
            local okg, great = pcall(dfhack.units.isGreatDanger, u)      -- (0.105.4 review)
            -- (R32 d) id: the watcher's look reads each one's step since the last
            table.insert(out, {id = u.id, pos = u.pos, invader = oki and inv or false, great = okg and great or false})
        end
    end
    return out
end

-- (0.105.3) A gate the watcher shut opens again (the watcher stays armed and
-- shuts it again if danger comes) once, for REOPEN_CHECKS looks in a row
-- (half a day), no visible invader is on the map and no other visible
-- danger is within REOPEN_CLEAR tiles of it. A siege in sight keeps it shut.
-- (0.105.4 review) Not while a great danger (titan, forgotten beast) is in
-- sight, however far; not after more than REOPEN_PEAK_MAX dangers were seen
-- at once since the watcher was armed (a bigger ambush that hid again keeps
-- the brain's normal quiet wait; unknown after a reload: kept shut too); and
-- the clear distance is WIDE, the same the watcher shuts at, so no band
-- between them flips the gate every half day.
REOPEN_CHECKS = 6
REOPEN_PEAK_MAX = 2
function may_reopen(nearest, invaders, great, peak)
    return invaders == 0 and (great or 0) == 0 and type(peak) == 'number' and peak <= REOPEN_PEAK_MAX
        and nearest > WIDE
end

function distance_to(e, pos)
    local best = math.huge
    local function near(x, y, z)
        if math.abs(z - pos.z) <= 3 then
            local d = math.max(math.abs(x - pos.x), math.abs(y - pos.y))
            if d < best then best = d end
        end
    end
    for k in pairs(e.outs) do near(unkey(k)) end
    -- (0.105.0 review) a cut entrance: its hatches too (a beast deep in a big
    -- porch is far from the opening but close to the way down)
    for _, k in ipairs(e.hatch_keys or {}) do near(unkey(k)) end
    return best
end

-- Close an entrance now? Danger right at it, or danger coming and nobody
-- left outside.
function should_close(nearest, outside)
    return nearest <= IMMINENT or (nearest <= WIDE and outside == 0)
end

-- (r9) this file's locals ai-gates-watch-look uses, as module names (it takes
-- them back as locals of its own)
_ENV.lever_pull_pending, _ENV.pull, _ENV.set_entrance = lever_pull_pending, pull, set_entrance
