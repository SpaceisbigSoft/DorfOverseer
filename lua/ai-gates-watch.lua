-- ai-gates-watch: the watcher: who is outside, closing and opening an entrance's pieces,
-- the lever links, check(), arm(), open_all(); planned gate buildings; doors.
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-watch'] = '0.105.44'   -- (0.105.26) bumped with BRIDGE_VERSION

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

-- (0.105.23) A door or hatch on a lever, set by its lever: true if it was
-- pulled. Without a lever of this entrance's own to pull, it's only locked
-- (as before 0.105.23). `pulled` keeps one pull per lever per call.
local function set_lever_door(g, b, close, pulled)
    if not g.drive_lever then
        if b.door_flags.forbidden ~= close then b.door_flags.forbidden = close; return true end
        return false
    end
    if not close and b.door_flags.forbidden then b.door_flags.forbidden = false end   -- (a lock left from before the link)
    local shut = door_shut(b)
    if shut == nil or shut == close or pulled[g.drive_lever] then return false end
    pulled[g.drive_lever] = true
    local ok = pull_instant(g.drive_lever)
    -- (0.105.32) E: an instant pull opened the hatch, and DF's walk map stayed split at it
    if ok and not close then pcall(note_split_after_open, g, b) end
    return ok
end

local function set_bridge(g, b, close)
    local ok, c = pcall(function() return b.gate_flags.raised end)   -- (13c) not `closed`
    -- (0.105.33) nor while it moves (a pull now would send it back)
    local okm, moving = pcall(function() return b.gate_flags.raising or b.gate_flags.lowering end)
    -- lowering (opening) waits while anyone stands where it comes down;
    -- raising goes ahead (a threat is why it's raised)
    return ok and c ~= close and not (okm and moving) and g.lever_id and #b.jobs == 0
        and (close or not bridge_occupied(b)) and pull(g.lever_id) or false
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
            local b = df.building.find(g.id)
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
                    pcall(function()
                        local lv = df.building.find(g.lever_id)
                        local jobs = {}
                        for _, j in ipairs(lv and lv.jobs or {}) do
                            if j.job_type == df.job_type.PullLever then table.insert(jobs, j) end
                        end
                        for _, j in ipairs(jobs) do
                            if pcall(dfhack.job.removeJob, j) then n = n + 1 end
                        end
                    end)
                end
            end
        end
    end
    if n > 0 then GATES.pulls_cancelled = (GATES.pulls_cancelled or 0) + n end
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
                if shut == false or (booked and ai_piece(e, g)) or GATES.mine[g.id] then
                    ours[g.id] = true
                end
            end
        end
        for id in pairs(ours) do GATES.mine[id] = true end
    else
        for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
            for _, g in ipairs(list) do if ai_piece(e, g) then ours[g.id] = true end end
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
            elseif b and set_bridge(g, b, close) then done = done + 1 end
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
                if set_bridge(g, b, close) then done = done + 1 end
            elseif g.lever_driven then
                if set_lever_door(g, b, close, pulled) then done = done + 1 end
            else
                if b.door_flags.forbidden ~= close then
                    b.door_flags.forbidden = close
                    done = done + 1
                end
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
                        return f.raised or f.lowering
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
function visible_dangers()
    local out = {}
    for _, u in ipairs(df.global.world.units.active) do
        local ok, yes = pcall(function()
            return dfhack.units.isAlive(u) and not u.flags1.caged and not u.flags1.chained
                and not dfhack.units.isCitizen(u) and not dfhack.units.isHidden(u)
                and (dfhack.units.isDanger(u) or dfhack.units.isInvader(u))
        end)
        if ok and yes then
            local oki, inv = pcall(dfhack.units.isInvader, u)
            local okg, great = pcall(dfhack.units.isGreatDanger, u)      -- (0.105.4 review)
            table.insert(out, {pos = u.pos, invader = oki and inv or false, great = okg and great or false})
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

-- One look by the watcher: close what needs closing.
function check()
    if not GATES.armed or not GATES.entrances then return end
    local vis = visible_dangers()
    local ds, invaders, great = {}, 0, 0
    for _, d in ipairs(vis) do
        table.insert(ds, d.pos)
        if d.invader then invaders = invaders + 1 end
        if d.great then great = great + 1 end
    end
    if type(GATES.peak) == 'number' then GATES.peak = math.max(GATES.peak, #vis) end
    local outside = citizens_outside()
    GATES.clear_looks = GATES.clear_looks or {}
    GATES.opening = GATES.opening or {}
    local lure = lure_holds()                 -- (0.105.45)
    for _, e in ipairs(GATES.entrances) do
        if next(lure) then
            for id in pairs(entrance_gate_ids(e)) do
                if lure[id] then goto continue end
            end
        end
        if not GATES.closed[e.id] then GATES.opening[e.id] = nil end
        if GATES.opening[e.id] and #e.equipment > 0 then
            -- (0.105.33) being opened (a dwarf on the way to the lever): its
            -- bridge still up, or down already, isn't a lost close. Danger
            -- comes: closed again; else the opening tried again (pulls only
            -- what is still up and still), and done once every gate is open
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            GATES.clear_looks[e.id] = nil
            if should_close(nearest, outside) then
                GATES.opening[e.id] = nil
                set_entrance(e, true, true)        -- (0.105.36 fix) its queued opening pull taken away
                pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s closed again while opening (danger %s tiles away)')
                    :format(gate_name(e), nearest == math.huge and '?' or tostring(nearest)), COLOR_YELLOW, true)
            else
                set_entrance(e, false)
            end
        elseif GATES.closed[e.id] and #e.equipment > 0 then
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            if may_reopen(nearest, invaders, great, GATES.peak) then
                GATES.clear_looks[e.id] = (GATES.clear_looks[e.id] or 0) + 1
                -- (0.105.26 seal fix) not while the cavern seal holds any of
                -- its gates (a hidden forgotten beast is out of sight, not
                -- gone): kept shut, and opened at the first look after the seal
                if GATES.clear_looks[e.id] >= REOPEN_CHECKS and sealed_entrance(e) then
                    GATES.seal_kept = (GATES.seal_kept or 0) + 1
                elseif GATES.clear_looks[e.id] >= REOPEN_CHECKS then
                    GATES.clear_looks[e.id] = nil
                    set_entrance(e, false)
                    GATES.reopened = (GATES.reopened or 0) + 1
                    pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s opened again (no danger in sight, %d citizens outside)')
                        :format(gate_name(e), outside), COLOR_GREEN, true)
                    goto continue
                end
            else
                GATES.clear_looks[e.id] = nil
            end
        end
        local watched = {}                    -- (0.105.23) the gatehouse's bridge watched too
        for _, g in ipairs(e.equipment) do table.insert(watched, g) end
        for _, g in ipairs(e.outer or {}) do table.insert(watched, g) end
        local repulled, drift_open = {}, false
        for _, g in ipairs(watched) do
            local b = df.building.find(g.id)
            GATES.gone_ids = GATES.gone_ids or {}
            GATES.repulled = GATES.repulled or {}
            if not b then
                -- (0.104.139) a gate gone (Teacheroar's hatch 278, toppled in a
                -- tantrum) left the entrance open until the weekly scan: scan
                -- again (once for each one gone)
                if not GATES.gone_ids[g.id] then
                    GATES.gone_ids[g.id] = true
                    GATES.scanned = false
                    GATES.gone = (GATES.gone or 0) + 1
                end
            elseif GATES.opening[e.id] then
                -- (0.105.33) being opened: none of its gates is pulled back shut
            elseif not ai_piece(e, g) then
                -- (0.105.36 fix) the player's piece: never pulled by the watcher
            elseif GATES.closed[e.id] and g.kind == 'bridge' and g.lever_id then
                -- (0.104.139) closed, but the pull's job was lost: the bridge is
                -- still down, not moving. Pulled again, not within 10 checks of
                -- the last (a pull is a dwarf's job: a second undoes the first)
                local ok, still = pcall(function()
                    local f = b.gate_flags
                    return not f.raised and not f.raising and not f.lowering
                end)
                local now = df.global.cur_year_tick or 0
                local last = GATES.repulled[g.id]
                if ok and still and #b.jobs == 0 and (not last or now < last or now - last > 10 * CHECK_TICKS) then
                    GATES.repulled[g.id] = now
                    pcall(pull, g.lever_id)
                end
            elseif GATES.closed[e.id] and g.kind ~= 'bridge' and g.lever_driven and g.drive_lever
                    and door_shut(b) == false then
                -- (0.105.26 seal fix) a lever's hatch the watcher holds shut
                -- reads open (the seal opened it, the player pulled it, a pull
                -- went astray): its lever pulled again, at once. Still open
                -- after: the watcher's view corrected (not closed), so its
                -- next look decides again
                if not repulled[g.drive_lever] then
                    repulled[g.drive_lever] = true
                    local okp, done = pcall(pull_instant, g.drive_lever)
                    GATES.hatch_repulled = (GATES.hatch_repulled or 0) + 1
                    if not (okp and done) then drift_open = true end
                end
                if door_shut(b) == false then drift_open = true end
            end
        end
        if drift_open then GATES.closed[e.id] = nil end
        if not GATES.closed[e.id] and #e.equipment > 0 then
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            if should_close(nearest, outside) then
                set_entrance(e, true)
                -- (0.105.36 fix) said only when the AI shut something (gates the
                -- player shut already stay theirs: not booked, not said)
                if GATES.closed[e.id] then
                    pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s closed (danger %s tiles away, %d citizens outside)')
                        :format(gate_name(e), nearest == math.huge and '?' or tostring(nearest), outside), COLOR_YELLOW, true)
                end
            else
                -- (0.105.23) open while the watcher doesn't shut it: a lever's
                -- hatch its link shut is opened (citizens outside get back in)
                pcall(open_lever_hatches, e)
            end
        end
        ::continue::
    end
end

-- (0.104.81, 13c) a watcher that errors closes nothing: its error is kept
-- for the report (the brain says it) instead of vanishing in the pcall
local function watched_check()
    local ok, err = pcall(check)
    if ok then
        GATES.watch_error = nil
    else
        local w = GATES.watch_error or {n = 0}
        w.n, w.error, w.tick = w.n + 1, tostring(err):sub(1, 200), df.global.cur_year_tick
        GATES.watch_error = w
    end
end

local function tick()
    if not GATES.armed then return end
    watched_check()
    GATES.timer = dfhack.timeout(CHECK_TICKS, 'ticks', tick)
end

-- (0.105.33) from_save (gates_restore): {closed = {entrance id = true}, peak =
-- number or nil}: what the save says the watcher held is in place before its
-- first look (that look would open a saved-shut lever hatch), and the peak
-- comes back (unknown, nil, keeps a restored lockdown shut)
function arm(from_save)
    if not GATES.scanned then return {ok = false, rejected = true, error = 'entrances not scanned yet'} end
    if not GATES.armed then
        -- (0.100, review) gates still waiting to open: forgotten; the watcher
        -- closes what needs closing from the bridges as they stand.
        -- (0.105.36, D2) except an entrance still being opened (a bridge up
        -- with someone on it, a pull on its way): kept closed and opening, so
        -- it stays the AI's and the watcher's look goes on opening it (or
        -- shuts it again if danger comes); forgotten, it read as the player's
        if GATES.reopen_timer then pcall(dfhack.timeout_active, GATES.reopen_timer, nil) end
        local kept = {}
        for id, v in pairs(GATES.opening or {}) do
            if v and GATES.closed and GATES.closed[id] then kept[id] = true end
        end
        GATES.reopen_timer, GATES.closed, GATES.opening = nil, {}, {}
        for id in pairs(kept) do GATES.closed[id], GATES.opening[id] = true, true end
        GATES.peak, GATES.clear_looks = 0, {}       -- (0.105.4 review) dangers seen at once since armed
        if type(from_save) == 'table' then
            for id, v in pairs(from_save.closed or {}) do if v then GATES.closed[id] = true end end
            for id, v in pairs(from_save.opening or {}) do
                if v and GATES.closed[id] then GATES.opening[id] = true end
            end
            GATES.peak = type(from_save.peak) == 'number' and from_save.peak or nil
        end
        GATES.armed = true
        GATES.timer = dfhack.timeout(CHECK_TICKS, 'ticks', tick)
        watched_check()
    end
    return {ok = true, armed = true}
end

-- (0.100, review) gates left closed when the rest opened (someone stood on
-- a bridge): tried again every CHECK_TICKS until they're open, or the
-- watcher is armed again
local function reopen_tick()
    GATES.reopen_timer = nil
    if GATES.armed or not GATES.closed or next(GATES.closed) == nil then return end
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed[e.id] then pcall(set_entrance, e, false) end
    end
    if next(GATES.closed) ~= nil then
        GATES.reopen_timer = dfhack.timeout(CHECK_TICKS, 'ticks', reopen_tick)
    end
end

function open_all()
    GATES.armed = false
    if GATES.timer then dfhack.timeout_active(GATES.timer, nil) end
    GATES.timer = nil
    local opened = 0
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed and GATES.closed[e.id] then
            set_entrance(e, false)
            if not GATES.closed[e.id] then opened = opened + 1 end
        end
    end
    GATES.closed = GATES.closed or {}
    pcall(open_lever_hatches)            -- (0.105.23) a lever's hatch its link shut
    local waiting = 0
    for _ in pairs(GATES.closed) do waiting = waiting + 1 end
    if waiting > 0 and not (GATES.reopen_timer and dfhack.timeout_active(GATES.reopen_timer)) then
        GATES.reopen_timer = dfhack.timeout(CHECK_TICKS, 'ticks', reopen_tick)
    end
    return {ok = true, opened = opened, waiting = waiting > 0 and waiting or nil}
end

-- Placing one building with quickfort; returns placed (bool) and, when it
-- isn't, what quickfort counted instead (e.g. build_unsuitable), so a refusal
-- can say why.
place_hook = nil       -- tests replace this
-- (v35 fix) The tiles where the AI planned a gate piece (a door, hatch,
-- wall, bridge), kept with the save ({"x,y,z", ...}): free_gate_jobs resumes
-- the suspended jobs of these only, never of what the player planned.
GATE_PLANNED_KEY = 'ai-overseer/gate_planned'
GATE_PLANNED_MAX = 400

-- (0.105.36, D2) a record is "x,y,z@building id" (the building the AI's
-- plan made there), or "x,y,z" (v35's, or the building unread): set maps
-- the tile to that id, or to true.
function gate_planned_records()
    local d = U.site_get(GATE_PLANNED_KEY, {})
    local list = type(d) == 'table' and type(d.tiles) == 'table' and d.tiles or {}
    local set = {}
    for _, k in ipairs(list) do
        local tile, id = tostring(k):match('^([%-%d]+,[%-%d]+,[%-%d]+)@(%d+)$')
        if tile then set[tile] = tonumber(id) else set[tostring(k)] = true end
    end
    return set, list
end

-- (0.105.36, D2) Is this planned building still unbuilt? nil if unread.
local function still_planned(b)
    local ok, yes = pcall(function() return b:getBuildStage() < b:getMaxBuildStage() end)
    if ok then return yes end
    return nil
end

-- (0.105.36, D2) Records whose building is gone or built forgotten (a
-- later building of the player's on that tile is theirs). One unread kept.
function prune_gate_planned(list)
    if not list then local _; _, list = gate_planned_records() end
    local out = {}
    for _, k in ipairs(list) do
        local tile, id = tostring(k):match('^([%-%d]+,[%-%d]+,[%-%d]+)@(%d+)$')
        local b, read = nil, false
        if tile then
            local okb, bb = pcall(df.building.find, tonumber(id))
            if okb then b, read = bb, true end
        else
            local x, y, z = tostring(k):match('^([%-%d]+),([%-%d]+),([%-%d]+)$')
            if x then
                local okb, bb = pcall(dfhack.buildings.findAtTile, xyz2pos(tonumber(x), tonumber(y), tonumber(z)))
                if okb then b, read = bb, true end
            end
        end
        if not read or (b and still_planned(b) ~= false) then table.insert(out, k) end
    end
    return out
end

-- (0.105.36 fix) Since when the AI keeps its records: the first building id
-- after it began (kept with the save). A gate piece planned with no record
-- and an id below it predates the records (the AI's own, at an entrance it
-- fortified); one at or above it, unrecorded, is the player's. Read (and,
-- with write, kept) on the first look: the lowest of the next building id
-- and the buildings already recorded. nil when none can be read.
GATE_PLANNED_SINCE_KEY = 'ai-overseer/gate_planned_since'
function gate_planned_since(write)
    local d = U.site_get(GATE_PLANNED_SINCE_KEY, {})
    if type(d) == 'table' and math.tointeger(d.id) then return math.tointeger(d.id) end
    local okn, nxt = pcall(function() return df.global.building_next_id end)
    local since = okn and math.tointeger(nxt) or nil
    local okr, set = pcall(gate_planned_records)
    for tile, v in pairs(okr and set or {}) do
        local id = math.tointeger(v)
        if not id then
            local x, y, z = tostring(tile):match('^([%-%d]+),([%-%d]+),([%-%d]+)$')
            if x then
                local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(tonumber(x), tonumber(y), tonumber(z)))
                id = okb and b and math.tointeger(b.id) or nil
            end
        end
        if id and (not since or id < since) then since = id end
    end
    if write and since then U.site_put(GATE_PLANNED_SINCE_KEY, {id = since}) end
    return since
end

function note_gate_planned(pos)
    if not (pos and pos.x and pos.y and pos.z) then return end
    pcall(gate_planned_since, true)       -- (0.105.36 fix) before this record joins them
    local k = ('%d,%d,%d'):format(pos.x, pos.y, pos.z)
    -- (0.105.36, D2) with the id of the building planned there
    local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(pos.x, pos.y, pos.z))
    local id = okb and b and tonumber(b.id) or nil
    local set, list = gate_planned_records()
    if set[k] ~= nil and (set[k] == true or set[k] == id) then return end
    local okp, kept = pcall(prune_gate_planned, list)
    local out = {}
    for _, v in ipairs(okp and kept or list) do
        if tostring(v) ~= k and not tostring(v):match('^' .. k:gsub('%-', '%%-') .. '@') then table.insert(out, v) end
    end
    table.insert(out, id and (k .. '@' .. id) or k)
    while #out > GATE_PLANNED_MAX do table.remove(out, 1) end
    U.site_put(GATE_PLANNED_KEY, {tiles = out})
end

-- (v35 fix) Is any tile of this planned building one the AI planned?
-- (0.105.36, D2) a record with an id: only that building
function ai_planned_building(b)
    local okr, set = pcall(gate_planned_records)
    if not okr or not b or b.x1 == nil or b.z == nil then return false end
    for x = b.x1, b.x2 or b.x1 do
        for y = b.y1, b.y2 or b.y1 do
            local v = set[('%d,%d,%d'):format(x, y, b.z)]
            if v == true or (v ~= nil and v == b.id) then return true end
        end
    end
    return false
end

local function place_raw(key_text, pos)
    if place_hook then return place_hook(key_text, pos) end
    local qf = reqscript('quickfort')
    -- the same data shape ai-builder uses: {[z] = {[y] = {[x] = text}}}
    local data = {[pos.z] = {[pos.y] = {[pos.x] = key_text}}}
    local ok, stats = pcall(qf.apply_blueprint, {mode = 'build', data = data,
                                                 pos = {x = 0, y = 0, z = 0}, command = 'run'})
    if not ok then return false, tostring(stats):sub(1, 80) end
    if stats.build_designated and stats.build_designated.value > 0 then return true end
    local why = {}
    for name, v in pairs(stats) do
        if type(v) == 'table' and (v.value or 0) > 0 and name ~= 'build_designated' then
            table.insert(why, name)
        end
    end
    local seen = what_is_there(pos)
    return false, (#why > 0 and table.concat(why, ',') or 'not placed') .. (seen and (' ' .. seen) or '')
end

local function place(key_text, pos)
    local ok, why = place_raw(key_text, pos)
    if ok then pcall(note_gate_planned, pos) end       -- (v35 fix) the AI's own, recorded
    return ok, why
end

-- What's on a tile, in a few words, so a refusal says why ("SAPLING, a
-- building"). nil if it can't be read.
function what_is_there(pos)
    local ok, text = pcall(function()
        local tt = dfhack.maps.getTileType(pos.x, pos.y, pos.z)
        if not tt then return nil end
        local attrs = df.tiletype.attrs[tt]
        local bits = {df.tiletype_shape[attrs.shape] or '?', df.tiletype_material[attrs.material] or '?'}
        local des, occ = dfhack.maps.getTileFlags(pos.x, pos.y, pos.z)
        if des and des.flow_size > 0 then table.insert(bits, ('liquid %d/7'):format(des.flow_size)) end
        local b = dfhack.buildings.findAtTile(xyz2pos(pos.x, pos.y, pos.z))
        if b then
            local kind = df.building_type[b:getType()] or 'building'
            table.insert(bits, kind .. (b:getBuildStage() < b:getMaxBuildStage() and ' (planned)' or ''))
        end
        if des and des.dig ~= df.tile_dig_designation.No then table.insert(bits, 'designated to dig') end
        return ('at x%d y%d (%s)'):format(pos.x, pos.y, table.concat(bits, ', '))
    end)
    return ok and text or nil
end

local function entrance(id)
    for _, x in ipairs(GATES.entrances or {}) do if x.id == id then return x end end
    return nil
end

-- Doors on an open entrance's narrow opening (buildingplan waits for doors).
function build_doors(id)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if #e.door_spots == 0 then return {ok = false, rejected = true, error = 'no door spots for this entrance'} end
    local placed, why = 0, {}
    for _, sp in ipairs(e.door_spots) do
        local ok, reason = place('d', sp)
        if ok then placed = placed + 1 else table.insert(why, reason) end
    end
    if placed == 0 then
        return {ok = false, error = 'no door could be placed there (' .. table.concat(why, '; ') .. ')'}
    end
    return {ok = true, doors = placed}
end

-- (13e) this file's locals the later parts use, as module names (each takes
-- them back as locals of its own)
_ENV.pull, _ENV.set_entrance, _ENV.place, _ENV.entrance = pull, set_entrance, place, entrance
