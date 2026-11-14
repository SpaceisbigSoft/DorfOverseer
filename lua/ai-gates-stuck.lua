-- ai-gates-stuck: a gate the game treats as shut (unstick_gate, open_entrance,
-- close_threatened_gates, free_gate_jobs) and the save-aware arm/open_all/check/summary.
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-stuck'] = '0.105.43'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, key, STAIR_UP, ref_ids, set_entrance, wgroup, on_cavern_tile = U, key, STAIR_UP, ref_ids, set_entrance, wgroup, on_cavern_tile   -- (13e) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- (0.105.32) A gate the game treats as shut. E (8 Nov): the founding
-- stair's hatch, on its lever, was shut and opened again by instant pulls
-- in a brief alarm; from then on it read open (`closed` false) but DF's walk
-- map was split at it (the hatch and the surface one group, the stair under
-- it and the fort another). Every citizen who went out, and every migrant
-- wave, was stranded there and reported as "no path"; 64 died of thirst
-- with 470+ drinks in store. Why DF held it is not known (a flag the report
-- didn't read, the walk map not redone after the instant pull, the half-done
-- link), so the fix doesn't need to know it:
--   gate_splits()   each entrance's doors and hatches that read open (not
--                   closed, not locked) with their two sides in different
--                   walk groups: the entrance's `split`, with everything
--                   about the piece (flags, tiles, link). A few walk-group
--                   reads a piece, at each report.
--   unstick_gate()  one step a call: 1 unlock and open it, and ask DF to
--                   redo its walk map; 2 its own lever pulled twice (shut,
--                   open); 3 the piece taken down (the AI's only), and the
--                   spot remembered (GATES.stuck_removed, kept with the
--                   save): no lever drives a new piece there for a year.
-- After each instant pull that opens a gate, its sides are read again; a
-- split is noted (GATES.split_seen: id -> tick) so the report shows since
-- when (a split the report then finds joined is dropped).
---------------------------------------------------------------------------

STUCK_ENEMY_NEAR = 12           -- tiles: no unsticking with an enemy in sight this close to the gate
local DOOR_FLAG_NAMES = {'forbidden', 'internal', 'taken_by_invaders', 'used_by_intruder', 'closed',
                         'operated_by_mechanisms', 'pet_passable', 'accept_pets'}   -- read when pairs can't
local BUILDING_FIELDS = {'close_timer'}        -- other fields a door or hatch may be held by

local function stuck_key(x, y, z) return ('%d:%d:%d'):format(x, y, z) end

function copy_stuck(t)
    local out = {}
    for k, v in pairs(t or {}) do
        if type(k) == 'string' and type(v) == 'number' then out[k] = v end
    end
    return out
end

-- The stuck gates taken down less than a year ago ("x:y:z" -> tick), the
-- older ones dropped.
function stuck_removed_live()
    local okn, now = pcall(U.abs_tick)
    local out = {}
    for k, v in pairs(copy_stuck(GATES.stuck_removed)) do
        if not okn or now - v < U.TICKS_PER_YEAR then out[k] = v end
    end
    GATES.stuck_removed = next(out) and out or nil
    return out
end

-- When a stuck gate at this spot was taken down (tick), if less than a year ago.
function stuck_spot(x, y, z)
    if type(GATES.stuck_removed) ~= 'table' or x == nil then return nil end
    return stuck_removed_live()[stuck_key(x, y, z)]
end

local function piece_pos(g)
    return g.x or g.x1, g.y or g.y1, g.z
end

local function shape_at(x, y, z)
    local ok, t = pcall(tile, x, y, z)
    return ok and t and t.shape or nil
end

-- The two tiles a piece joins: a hatch, its own tile and the stair under
-- it; a door, its two walkable neighbours along the way through. nil when
-- it joins nothing (a hatch over no stair).
function piece_sides(kind, x, y, z)
    if kind == 'hatch' then
        local s = shape_at(x, y, z - 1)
        if not (s and STAIR_UP[s]) then return nil end
        return {x = x, y = y, z = z}, {x = x, y = y, z = z - 1}
    elseif kind == 'door' then
        for _, d in ipairs({{1, 0}, {0, 1}}) do
            local a, c = {x = x + d[1], y = y + d[2], z = z}, {x = x - d[1], y = y - d[2], z = z}
            if wgroup(a.x, a.y, a.z) ~= 0 and wgroup(c.x, c.y, c.z) ~= 0 then return a, c end
        end
    end
    return nil
end

-- Reads open: not shut by DF's flag and not locked.
local function reads_open(b)
    local okc, c = pcall(function() return b.door_flags.closed end)
    local okf, f = pcall(function() return b.door_flags.forbidden end)
    return okc and okf and not c and not f
end

-- Every door flag (by pairs, else by name), and the building's other
-- fields that may hold it: what the report can show of why DF holds it.
function piece_flags(b)
    local out = {}
    pcall(function()
        for k, v in pairs(b.door_flags) do
            if type(k) == 'string' and (type(v) == 'boolean' or type(v) == 'number') then out[k] = v end
        end
    end)
    if next(out) == nil then
        for _, n in ipairs(DOOR_FLAG_NAMES) do
            local ok, v = pcall(function() return b.door_flags[n] end)
            if ok and (type(v) == 'boolean' or type(v) == 'number') then out[n] = v end
        end
    end
    for _, f in ipairs(BUILDING_FIELDS) do
        local ok, v = pcall(function() return b[f] end)
        if ok and (type(v) == 'boolean' or type(v) == 'number') then out[f] = v end
    end
    pcall(function()        -- the building's own flags, the ones set
        for k, v in pairs(b.flags) do
            if type(k) == 'string' and v == true then out['building_' .. k] = true end
        end
    end)
    pcall(function() out.jobs = #b.jobs end)
    return out
end

local function tile_name(x, y, z)
    local ok, n = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        return tt and df.tiletype[tt] or nil
    end)
    return ok and n or nil
end

-- The driving lever, its links, the mechanisms the piece holds.
function piece_link(g, b)
    local out = {status = 'none'}
    local lid = g.drive_lever or g.lever_id
    if lid then
        out.lever_id = lid
        out.status = 'linked'
        pcall(function()
            local lv = df.building.find(lid)
            out.lever_name = tostring(lv.name or '')
            out.linked_mechanisms = #lv.linked_mechanisms
            for _, j in ipairs(lv.jobs or {}) do
                if j.job_type == df.job_type.LinkBuildingToTrigger then out.status = 'linking' end
                if j.job_type == df.job_type.PullLever then out.pull_waiting = true end
            end
        end)
    end
    if g.levers and #g.levers > 1 then
        out.levers = {}
        for _, l in ipairs(g.levers) do table.insert(out.levers, l.id) end
    end
    pcall(function()
        local n, trig = 0, 0
        for _, ci in ipairs(b.contained_items or {}) do
            local it = ci.item
            if it:getType() == df.item_type.TRAPPARTS then n = n + 1 end
            if #ref_ids(it, df.general_ref_type.BUILDING_TRIGGER) > 0 then trig = trig + 1 end
        end
        out.mechanisms, out.trigger_refs = n, trig
    end)
    return out
end

-- Which side is out: the one not in the fort's interior group, else the
-- one off the map of the inside, else (a hatch) the one above it, under it
-- for a cavern's.
local function side_roles(e, kind, a, c, ga, gc, interior_group)
    if interior_group == ga then return gc, ga end
    if interior_group == gc then return ga, gc end
    local ins = GATES.inside or {}
    local ia, ic = ins[key(a.x, a.y, a.z)] == true, ins[key(c.x, c.y, c.z)] == true
    if ia and not ic then return gc, ga end
    if ic and not ia then return ga, gc end
    if kind == 'hatch' and e and e.kind == 'cavern' then return gc, ga end
    return ga, gc
end

-- One piece's walk groups now: split (true/false), and the two groups;
-- nil when it can't be told.
local function sides_now(kind, x, y, z)
    local a, c = piece_sides(kind, x, y, z)
    if not a then return nil end
    local ga, gc = wgroup(a.x, a.y, a.z), wgroup(c.x, c.y, c.z)
    if ga == 0 or gc == 0 then return nil end
    return ga ~= gc, a, c, ga, gc
end

-- The split record of a gate piece, or nil (not split, not open, unread).
function piece_split(e, g, interior_group)
    if g.kind ~= 'door' and g.kind ~= 'hatch' then return nil end
    local okb, b = pcall(df.building.find, g.id)
    if not okb or not b or not reads_open(b) then return nil end
    local x, y, z = piece_pos(g)
    local split, a, c, ga, gc = sides_now(g.kind, x, y, z)
    if not split then return nil end
    local og, ig = side_roles(e, g.kind, a, c, ga, gc, interior_group)
    return {id = g.id, kind = g.kind, x = x, y = y, z = z, outside_group = og, inside_group = ig,
            flags = piece_flags(b),
            tiles = {above = tile_name(x, y, z + 1), at = tile_name(x, y, z), below = tile_name(x, y, z - 1)},
            link = piece_link(g, b)}
end

-- Every entrance's split pieces (e.split, nil when none); split_seen kept
-- for the ones still split. Returns how many.
function gate_splits()
    local okn, now = pcall(U.abs_tick)
    now = okn and now or 0
    local oki, interior = pcall(fort_interior)
    local ig = oki and interior and interior.group or nil
    local seen_old, seen, n = GATES.split_seen or {}, {}, 0
    for _, e in ipairs(GATES.entrances or {}) do
        local list = {}
        for _, g in ipairs(e.equipment or {}) do
            local ok, p = pcall(piece_split, e, g, ig)
            if ok and p then
                seen[p.id] = seen_old[p.id] or now
                p.since = seen[p.id]
                table.insert(list, p)
            end
        end
        e.split = #list > 0 and list or nil
        n = n + #list
    end
    GATES.split_seen = next(seen) and seen or nil
    GATES.splits_at = now
    return n
end

-- After an instant pull meant to open a gate: its sides read again; split
-- ones noted (the report then reads them itself).
function note_split_after_open(g, b)
    local kind = g.kind
    if kind ~= 'door' and kind ~= 'hatch' then return false end
    if not reads_open(b) then return false end
    local split = sides_now(kind, b.x1, b.y1, b.z)
    if not split then return false end
    local okn, now = pcall(U.abs_tick)
    GATES.split_seen = GATES.split_seen or {}
    GATES.split_seen[b.id] = GATES.split_seen[b.id] or (okn and now or 0)
    return true
end

local function find_piece(id)
    for _, e in ipairs(GATES.entrances or {}) do
        for _, g in ipairs(e.equipment or {}) do
            if g.id == id then return e, g end
        end
    end
    return nil
end

local function enemy_near(x, y, z)
    local ok, vis = pcall(visible_dangers)
    local best
    for _, d in ipairs(ok and vis or {}) do
        local dd = math.max(math.abs(d.pos.x - x), math.abs(d.pos.y - y)) + 3 * math.abs(d.pos.z - z)
        if not best or dd < best then best = dd end
    end
    return best
end

-- DF asked to redo its walk map, where the field exists. true if set.
function reindex_paths()
    return pcall(function()
        if df.global.world.reindex_pathfinding == nil then error('no such field') end
        df.global.world.reindex_pathfinding = true
    end) == true
end

-- The AI's own piece: worked by an "AI gate..." lever, or a hatch of a cut
-- the AI made. A player's own gate is never taken down.
local function ai_piece(e, g)
    if g.drive_ai then return true end
    for _, l in ipairs(g.levers or {}) do
        if ai_lever_name(l.name) then return true end
    end
    return e.cut == true and g.kind == 'hatch'
end

local function where(x, y, z) return ('x%d y%d z%d'):format(x, y, z) end

-- One step (1-3) at a gate piece that reads open but DF holds shut.
-- {ok, step, done, split_after, flags_before, flags_after, dry_run?}.
-- (0.105.35) cavern_ok: the brain read the caverns and found no great
-- danger there: a cavern's way gets step 2 too (the AI's own piece
-- only, as anywhere), for citizens cut off on its far side; (v35 fix) never
-- step 3 (taken down) on a cavern's way.
function unstick_gate(id, step, dry_run, cavern_ok)
    pcall(gates_restore)        -- (the save's record read back before this one is added)
    if not GATES.scanned then return {ok = false, rejected = true, error = 'map the entrances first'} end
    if step ~= 1 and step ~= 2 and step ~= 3 then
        return {ok = false, rejected = true, error = 'unstick_gate needs step 1, 2 or 3'}
    end
    local e, g = find_piece(id)
    if not g then
        return {ok = false, rejected = true, error = ('no gate %s at a mapped entrance (scan first)'):format(tostring(id))}
    end
    if g.kind ~= 'door' and g.kind ~= 'hatch' then
        return {ok = false, rejected = true, error = 'only a door or hatch is unstuck (a drawbridge is its lever\'s)'}
    end
    local okb, b = pcall(df.building.find, id)
    if not okb or not b then return {ok = false, rejected = true, error = 'that gate is gone'} end
    local x, y, z = piece_pos(g)
    if seal_has(seal_holds(), g) then
        return {ok = false, rejected = true, step = step,
                error = 'the cavern seal holds this gate shut (a great beast in the caverns): it stays until the seal lifts'}
    end
    local near = enemy_near(x, y, z)
    if near and near <= STUCK_ENEMY_NEAR then
        return {ok = false, rejected = true, step = step, enemy_near = near,
                error = ('an enemy is in sight %d tiles from the gate: it is left as it is until they are gone'):format(near)}
    end
    -- (merge32 review) the split read again now, not trusted from the scan:
    -- a piece whose two sides walk together is left alone (no pull, no
    -- taking down)
    local split_now, sa, sc, sga, sgc = sides_now(g.kind, x, y, z)
    if split_now ~= true then
        return {ok = false, rejected = true, step = step, split_after = split_now,
                error = split_now == false and 'it is not stuck now (both sides are one walk group again): left as it is'
                    or 'its two sides can\'t be read now: left as it is'}
    end
    -- (merge32 review) a cavern's way: never pulled open and shut or taken
    -- down (a hatch the AI put on a cavern's way keeps what's down there out)
    local oki, interior = pcall(fort_interior)
    local og = side_roles(e, g.kind, sa, sc, sga, sgc, oki and interior and interior.group or nil)
    local out_tile = og == sga and sa or sc
    local cavern = e.kind == 'cavern' or on_cavern_tile(out_tile)
    if cavern and step >= 2 and cavern_ok ~= true then
        return {ok = false, rejected = true, step = step, cavern = true,
                error = 'this gate is on a cavern\'s way: the AI does not pull it open and shut or take it down; '
                    .. 'see to it by hand'}
    end
    -- (v35 fix) never taken down on a cavern's way, even with the caverns read
    -- safe now: that way into the caverns would stay open until a door is rebuilt
    if cavern and step == 3 then
        return {ok = false, rejected = true, step = step, cavern = true,
                error = 'this gate is on a cavern\'s way: the AI does not take it down (the way into the caverns '
                    .. 'would stay open)'}
    end
    -- (merge32 review) the gate watcher's: an entrance it holds shut isn't
    -- opened by a pull; nothing is taken down while it is armed or an invader
    -- is in sight
    local held = GATES.closed and GATES.closed[e.id] and true or false
    local okf, locked = pcall(function() return b.door_flags.forbidden end)
    if held and (step == 2 or (step == 1 and (door_shut(b) or (okf and locked)))) then
        return {ok = false, rejected = true, step = step, watcher = true,
                error = 'the gate watcher holds this entrance shut (danger near): it is not pulled until the watcher opens it'}
    end
    if step == 1 and GATES.armed and door_shut(b) then
        return {ok = false, rejected = true, step = step, watcher = true,
                error = 'the gate watcher is armed and this gate reads shut: it is not opened until the alarm is over'}
    end
    if step == 3 then
        local okv, vis = pcall(visible_dangers)
        local invader = false
        for _, d in ipairs(okv and vis or {}) do if d.invader then invader = true end end
        if GATES.armed or invader then
            return {ok = false, rejected = true, step = step, watcher = true,
                    error = GATES.armed and 'the gate watcher is armed: no gate is taken down until the alarm is over'
                        or 'an invader is in sight on the map: no gate is taken down until they are gone'}
        end
    end
    local before = piece_flags(b)
    local out = {ok = true, step = step, id = id, flags_before = before, dry_run = dry_run or nil}
    local lever = g.drive_lever
    local did = {}
    local function finish_step()
        if dry_run then
            table.insert(did, 'would ask DF to redo its walk map')
        else
            out.reindexed = reindex_paths()
            table.insert(did, out.reindexed and 'asked DF to redo its walk map'
                or 'DF\'s walk map could not be asked to redo (no such field here)')
            local split = sides_now(g.kind, x, y, z)
            out.split_after = split
            out.shut_after = door_shut(b)
        end
    end
    if step == 1 then
        local shut = door_shut(b)
        if before.forbidden then table.insert(did, (dry_run and 'would unlock it' or 'unlocked it')) end
        if shut then
            if lever then
                table.insert(did, ('%s its lever %d (it read shut)'):format(dry_run and 'would open it by' or 'opened it by', lever))
            else
                table.insert(did, dry_run and 'would set it open (it read shut, no lever of its own)'
                    or 'set it open (it read shut, no lever of its own)')
            end
        end
        if not dry_run then
            pcall(function() b.door_flags.forbidden = false end)
            if shut and lever then
                out.pulled = pull_instant(lever)
                if not out.pulled then table.insert(did, 'the lever pull was refused') end
            elseif shut then
                pcall(function() b.door_flags.closed = false end)
            end
        end
        finish_step()
    elseif step == 2 then
        if not lever then
            -- (merge32 review) nothing to pull: the step done as nothing, so
            -- the brain goes on to step 3 (a refusal was asked again for ever)
            out.done = 'no lever: skipped'
            out.split_after = split_now
            out.skipped = true
            if not dry_run then out.split_after = sides_now(g.kind, x, y, z); out.flags_after = before end
            return out
        end
        if dry_run then
            table.insert(did, ('would pull its lever %d twice at once (shut, then open)'):format(lever))
        else
            local n = 0
            for _ = 1, 2 do if pull_instant(lever) then n = n + 1 end end
            out.pulls = n
            table.insert(did, ('pulled its lever %d %d time(s) at once (shut, then open)'):format(lever, n))
            if n < 2 then out.ok = false; out.error = 'the lever would not be pulled twice' end
        end
        finish_step()
    else
        if not ai_piece(e, g) then
            return {ok = false, rejected = true, step = step, flags_before = before,
                    error = 'this gate is the player\'s own (no "AI gate" lever works it): the AI does not take it down; '
                        .. 'take it down by hand, or name its lever "AI gate"'}
        end
        local okj, going = pcall(function()
            for _, j in ipairs(b.jobs or {}) do
                if j.job_type == df.job_type.DestroyBuilding then return true end
            end
            return false
        end)
        if okj and going then
            return {ok = false, rejected = true, step = step, flags_before = before,
                    error = 'it is already being taken down'}
        end
        local what = ('the %s at %s'):format(g.kind, where(x, y, z))
        if dry_run then
            table.insert(did, ('would take down %s%s; no lever-driven piece goes back there for a year'):format(
                what, lever and (' (its link to lever ' .. lever .. ' goes with it)') or ''))
        else
            -- DFHack has no call to undo a link: the link goes with the piece
            local okd, gone = pcall(dfhack.buildings.deconstruct, b)
            if not okd then
                return {ok = false, step = step, flags_before = before,
                        error = 'the game would not take it down: ' .. tostring(gone):sub(1, 120)}
            end
            out.removed_now = gone == true
            table.insert(did, ('%s %s%s'):format(gone == true and 'took down' or 'marked for taking down', what,
                lever and (' (its link to lever ' .. lever .. ' goes with it)') or ''))
            local okn, now = pcall(U.abs_tick)
            local s = stuck_removed_live()
            s[stuck_key(x, y, z)] = okn and now or 0
            GATES.stuck_removed = s
            if GATES.split_seen then GATES.split_seen[id] = nil end
            pcall(gates_persist)
            table.insert(did, 'no lever-driven piece goes back there for a year')
            out.split_after = sides_now(g.kind, x, y, z)
        end
    end
    out.done = table.concat(did, '; ')
    if not dry_run then
        local okf, b2 = pcall(df.building.find, id)
        out.flags_after = okf and b2 and piece_flags(b2) or nil
    end
    return out
end

-- (0.105.35 merge) The player's own levers (not named "AI gate...") that
-- opening this entrance would pull (a drawbridge's lever_id, a door's or
-- hatch's drive_lever) and that also work something besides this
-- entrance's gates, read live from the links: {{lever = id, others = n}}.
-- Such a lever is never pulled for the entrance (the pull would work the
-- player's other things too). levers: lever_links()'s map, if already read.
function players_shared_levers(e, levers)
    if not levers then
        local okl, l = pcall(lever_links)
        levers = okl and l or {}
    end
    local mine = entrance_gate_ids(e)
    local out, seen = {}, {}
    for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
        for _, g in ipairs(list) do
            local lid = g.kind == 'bridge' and g.lever_id or (g.lever_driven and g.drive_lever) or nil
            if lid and not seen[lid] then
                seen[lid] = true
                local okb, lv = pcall(df.building.find, lid)
                local name = okb and lv and tostring(lv.name or '') or ''
                if not ai_lever_name(name) then
                    local others = 0
                    for _, tid in ipairs(lever_targets(levers, lid)) do
                        if not mine[tid] then others = others + 1 end
                    end
                    if others > 0 then table.insert(out, {lever = lid, others = others}) end
                end
            end
        end
    end
    return out
end

-- (0.105.34) One entrance opened for citizens the AI's gates shut out, while
-- a siege is held off elsewhere (the player: nothing waits for them). Only
-- the gates of this entrance; the watcher stays armed and shuts it again if
-- danger comes within IMMINENT. Refused while a visible danger (or any great
-- danger in sight) is within IMMINENT of it, or the cavern seal holds it.
-- (0.105.35) cavern_ok: the brain read the caverns and found no great danger
-- there (its cavern_great, deep_read): a cavern entrance opens too, for
-- citizens shut out on its far side (the seal and a great danger in sight
-- still refuse it). (v35 fix) Only an entrance the AI shut (GATES.closed).
function open_entrance(id, dry_run, cavern_ok)
    local e
    for _, x in ipairs(GATES.entrances or {}) do if x.id == id then e = x end end
    if not e then return {ok = false, rejected = true, error = 'no entrance ' .. tostring(id)} end
    if e.kind == 'cavern' and cavern_ok ~= true then
        return {ok = false, rejected = true, error = 'a cavern entrance stays as the cavern rules keep it'}
    end
    -- (0.105.36, D2) the seal and a great danger in sight pass (a siege's titan
    -- held off at another gate): waiting, so the brain looks again soon
    -- instead of backing off for days while the shut-out go thirsty
    if sealed_entrance(e) then
        return {ok = false, rejected = true, waiting = true, error = 'the cavern seal holds this entrance'}
    end
    local okv, vis = pcall(visible_dangers)
    local nearest = math.huge
    for _, d in ipairs(okv and vis or {}) do
        if d.great then return {ok = false, rejected = true, waiting = true, error = 'a great danger is in sight'} end
        local okd, dd = pcall(distance_to, e, d.pos)
        if okd and dd < nearest then nearest = dd end
    end
    if nearest <= IMMINENT then
        return {ok = false, rejected = true, waiting = true, nearest = nearest,
                error = ('an enemy is %d tiles from this entrance'):format(nearest)}
    end
    -- (v35 fix) a gate the AI didn't shut is the player's: never opened by
    -- the AI (no lever of the player's pulled, no door the player locked
    -- unlocked); the brain digs the shut-out a way in instead
    if not (GATES.closed and GATES.closed[e.id]) then
        local okp, shared = pcall(players_shared_levers, e)
        local sh = okp and shared and shared[1] or nil
        return {ok = false, rejected = true, not_ai = true,
                shared_lever = sh and sh.lever or nil, works_other = sh and sh.others or nil,
                error = 'its gate was not shut by the AI: the AI does not open the player\'s gate'
                    .. (sh and (' (the player\'s lever %d works %d other thing(s))'):format(sh.lever, sh.others) or '')}
    end
    if dry_run then return {ok = true, dry_run = true, entrance = id, nearest = nearest < math.huge and nearest or nil} end
    local done = set_entrance(e, false)
    pcall(gates_persist)
    return {ok = true, entrance = id, opened = done, still_shut = GATES.closed[e.id] and true or nil,
            nearest = nearest < math.huge and nearest or nil}
end

-- (0.105.35) The gate watcher failing (the player: nothing waits for them):
-- every entrance with a visible danger within IMMINENT of it shut now, as
-- the watcher's own look would. Refused (waiting) when none is that close.
function close_threatened_gates(dry_run)
    if not GATES.scanned or not GATES.entrances then
        return {ok = false, rejected = true, error = 'map the entrances first'}
    end
    local okv, vis = pcall(visible_dangers)
    if not okv then return {ok = false, error = 'the dangers could not be read: ' .. tostring(vis):sub(1, 120)} end
    local ids, done = {}, 0
    GATES.closed = GATES.closed or {}
    for _, e in ipairs(GATES.entrances) do
        -- (0.105.36, X1) not `e.sealed`: the scan sets it on every entrance whose
        -- gates seal it, so no gate was ever shut here (the cavern seal is
        -- sealed_entrance(e), and a seal-held gate is shut already)
        -- (0.105.36) one being opened (a bridge still up, a pull on its way) is
        -- shut again too, as the watcher's look would
        local opening = GATES.opening and GATES.opening[e.id]
        -- (0.105.36 fix) and only with a gate open to shut: one the player
        -- shut already is theirs, never booked as the AI's
        if #(e.equipment or {}) > 0 and (not GATES.closed[e.id] or opening)
                and (opening or open_pieces(e) > 0) then
            local nearest = math.huge
            for _, d in ipairs(vis or {}) do
                local okd, dd = pcall(distance_to, e, d.pos)
                if okd and dd < nearest then nearest = dd end
            end
            if nearest <= IMMINENT then
                table.insert(ids, e.id)
                if not dry_run then
                    if GATES.opening then GATES.opening[e.id] = nil end
                    local okc, n = pcall(set_entrance, e, true, opening)   -- (0.105.36 fix) its queued opening pull taken away
                    if okc then done = done + (n or 0) end
                end
            end
        end
    end
    if #ids == 0 then
        return {ok = false, rejected = true, waiting = true,
                error = ('no enemy within %d tiles of an open gate'):format(IMMINENT)}
    end
    if not dry_run then pcall(gates_persist) end
    return {ok = true, entrances = ids, closed = done, dry_run = dry_run or nil}
end

-- (0.105.35) A gate planned at an entrance waits a week with parts free:
-- the building jobs of what is planned there unsuspended (a suspended job
-- is the usual cause). Refused when none is suspended. (v35 fix) Only the
-- pieces the AI planned (gate_planned_records).
-- (0.105.36, D2) ai_plan: the brain's memory says the AI fortified this
-- entrance (memory.gates_fortified): a piece planned there with no record
-- (planned before v35 kept them) is the AI's too; a record of another
-- building on its tile still says it isn't. (0.105.36 fix) Only one whose
-- id is older than the records (gate_planned_since): one the player planned
-- since, unrecorded, is theirs. Records of what is gone or
-- built are forgotten first.
function free_gate_jobs(id, dry_run, ai_plan)
    local e
    for _, x in ipairs(GATES.entrances or {}) do if x.id == id then e = x end end
    if not e then return {ok = false, rejected = true, error = 'no entrance ' .. tostring(id)} end
    if not dry_run then
        pcall(function()
            local _, list = gate_planned_records()
            local kept = prune_gate_planned(list)
            if #kept ~= #list then U.site_put(GATE_PLANNED_KEY, {tiles = kept}) end
        end)
    end
    local okr, recs = pcall(gate_planned_records)
    recs = okr and recs or {}
    -- (0.105.36 fix) ai_plan: only a piece older than the AI's records (planned
    -- before it kept them); a later one with no record is the player's
    local oks, since = pcall(gate_planned_since, not dry_run)
    since = oks and since or nil
    local function unrecorded(b)
        if b.x1 == nil or b.z == nil then return false end
        if not since or not math.tointeger(b.id) or b.id >= since then return false end
        for x = b.x1, b.x2 or b.x1 do
            for y = b.y1, b.y2 or b.y1 do
                if recs[('%d,%d,%d'):format(x, y, b.z)] ~= nil then return false end
            end
        end
        return true
    end
    local n, seen, theirs = 0, 0, 0
    for _, bid in ipairs(e.pending_ids or {}) do
        local okb, b = pcall(df.building.find, bid)
        if okb and b then
            seen = seen + 1
            -- (v35 fix) only what the AI planned: the player's suspended job stays theirs
            local mine = ai_planned_building(b) or (ai_plan == true and unrecorded(b))
            for _, j in ipairs(b.jobs or {}) do
                if j.flags and j.flags.suspend then
                    if mine then
                        n = n + 1
                        if not dry_run then j.flags.suspend = false end
                    else
                        theirs = theirs + 1
                    end
                end
            end
        end
    end
    if n == 0 then
        return {ok = false, rejected = true, players = theirs > 0 or nil,
                error = theirs > 0 and ('the %d suspended job(s) there are on what the player planned: the AI '
                                        .. 'leaves them'):format(theirs)
                    or ('no suspended job at the %d piece(s) planned there'):format(seen)}
    end
    return {ok = true, unsuspended = n, dry_run = dry_run or nil}
end

-- (the file's own functions, as just defined above: a reload of the script takes the new ones)
GATES_ORIG = {arm = arm, open_all = open_all, check = check, summary = summary}

function arm()
    pcall(gates_restore)
    local r = GATES_ORIG.arm()
    pcall(gates_persist)
    return r
end

function open_all()
    pcall(gates_restore)
    local saved = GATES_SAVE.saved
    local r = GATES_ORIG.open_all()
    if saved and not GATES.scanned then
        -- no map of the entrances yet: the saved gates opened by their ids;
        -- the saved state is kept (unarmed) until they are all down
        local ok, opened, waiting = pcall(open_saved_gates, saved)
        if ok then
            r.opened = (r.opened or 0) + opened
            if waiting > 0 then r.waiting = (r.waiting or 0) + waiting end
            saved.armed = false
            if waiting == 0 then GATES_SAVE.saved = {armed = false, gates = {}, stuck_removed = stuck_removed_live()} end
            U.site_put(GATES_SAVE_KEY, GATES_SAVE.saved)
            GATES_SAVE.persisted = GATES_SAVE.saved
        end
        return r
    end
    pcall(gates_persist)
    return r
end

function check()
    GATES_ORIG.check()
    pcall(gates_persist)
end

function summary()
    pcall(gates_restore)
    -- (0.105.23) a link made while no watch ran (a reload): taken up, and a
    -- hatch it shut opened, at the next report at the latest
    if GATES.scanned then
        pcall(attach_links)
        if not GATES.armed then pcall(open_lever_hatches) end
        if link_jobs_pending() then pcall(link_watch_start) end
        pcall(gate_splits)        -- (0.105.32) each entrance's gates that read open but DF holds shut
    end
    local out = GATES_ORIG.summary()
    -- (0.105.26) citizens outside who can't walk back in (nil without a map of the inside)
    local oks, st = pcall(stranded_citizens)
    if oks and st then
        out.stranded, out.stranded_total = st.list, st.total
        out.interior = st.interior
    elseif not oks then
        out.stranded_error = tostring(st):sub(1, 160)
    end
    pcall(gates_persist)
    -- what came back from the save after a load (the brain says it once)
    out.restored = GATES_SAVE.restored_from_save
    if GATES_SAVE.saved and next(GATES_SAVE.saved.gates or {}) ~= nil then
        -- gates the save says are closed, not yet matched to a scan: the
        -- planner may open them (open_gates) before the scan
        out.saved_closed = #GATES_SAVE.saved.gates
        if GATES_SAVE.saved.armed then out.armed = true end
    end
    return out
end

if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-gates-save'] = function(sc)
        if sc == SC_MAP_UNLOADED then GATES_SAVE = {} end
    end
end
