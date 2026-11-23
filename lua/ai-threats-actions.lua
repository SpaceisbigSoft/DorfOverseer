-- ai-threats-actions: what the fort does: fire_guard, the prisoners' room, the moon cell,
-- seal_cavern, the creatures that breathe fire.
--
-- (r8) A part of ai-threats, not a script of its own: ai-threats.lua loads it
-- into its own environment, so every name here is reqscript('ai-threats').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-threats-actions is a part of ai-threats; run ai-threats') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-threats-actions'] = '0.105.70'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, now_tick, name_of, save_state, unkey, is, citizens, fire_points, each_job, changed, okey, watcher_held, lure_open_ids = PART_LOCALS.U, PART_LOCALS.report_citizens, PART_LOCALS.now_tick, PART_LOCALS.name_of, PART_LOCALS.save_state, PART_LOCALS.unkey, PART_LOCALS.is, PART_LOCALS.citizens, PART_LOCALS.fire_points, PART_LOCALS.each_job, PART_LOCALS.changed, PART_LOCALS.okey, PART_LOCALS.watcher_held, PART_LOCALS.lure_open_ids   -- (r8) the hub's and earlier parts' locals

-- --- actions ---------------------------------------------------------------------

-- Fire: restricted traffic round each fire (only tiles at Normal, kept in
-- the save) and the jobs beside it taken off (at most max_jobs: DF gives
-- back a designation's job, so it's done again while the fire burns);
-- lift: those tiles back to Normal.
-- (0.105.41) A tile the AI painted High or Low (lua/ai-traffic.lua) is
-- restricted as a Normal one is, and lifted back to what the AI painted.
local function traffic_painted(x, y, z, memo)
    local ok, v = pcall(function() return reqscript('ai-traffic').ai_value(x, y, z, memo) end)
    return ok and v or nil
end

function fire_guard(radius, max_jobs, lift, dry_run)
    local d = load_state()
    local memo = {}
    if lift then
        local n = 0
        for _, k in ipairs(d.fire.tiles) do
            local x, y, z = unkey(k)
            pcall(function()
                local des = dfhack.maps.getTileFlags(x, y, z)
                if des and des.traffic == df.tile_traffic.Restricted then
                    if not dry_run then des.traffic = traffic_painted(x, y, z, memo) or df.tile_traffic.Normal end
                    n = n + 1
                end
            end)
        end
        if not dry_run then
            d.fire.tiles = {}
            save_state(d)
        end
        return {ok = true, lifted = n, dry_run = dry_run or nil}
    end
    local pts = fire_points()
    if #pts == 0 then return {ok = false, rejected = true, nothing_to_do = true, error = 'no fire burns now'} end
    local have = {}
    for _, k in ipairs(d.fire.tiles) do have[k] = true end
    local marked = 0
    for _, k in ipairs(fire_tiles(pts, radius, FIRE_MAX_TILES)) do
        if not have[k] then
            local x, y, z = unkey(k)
            pcall(function()
                local des = dfhack.maps.getTileFlags(x, y, z)
                if des and (des.traffic == df.tile_traffic.Normal
                            or (des.traffic ~= df.tile_traffic.Restricted
                                and des.traffic == traffic_painted(x, y, z, memo))) then
                    if not dry_run then
                        des.traffic = df.tile_traffic.Restricted
                        table.insert(d.fire.tiles, k)
                        have[k] = true
                    end
                    marked = marked + 1
                end
            end)
        end
    end
    local found = {}
    pcall(function()
        each_job(function(j)
            local okp, p = pcall(function() return j.pos end)
            local okt, jt = pcall(function() return df.job_type[j.job_type] end)
            if okp and p and p.x >= 0 and okt and fire_job_ok(jt) and near_any(p.x, p.y, p.z, pts, radius) then
                table.insert(found, j)
                if #found >= max_jobs then return false end
            end
        end)
    end)
    local removed = 0
    if not dry_run then
        for _, j in ipairs(found) do
            if pcall(dfhack.job.removeJob, j) then removed = removed + 1 end
        end
        save_state(d)
    end
    return {ok = true, fires = #pts, restricted = marked, jobs_removed = dry_run and #found or removed,
            dry_run = dry_run or nil}
end

-- (0.105.0 review) the jobs the fire guard may take off: digging, building
-- (constructions and buildings) and hauling. Never eating, drinking,
-- sleeping, fetching the wounded or any care.
-- (ConstructX jobs other than ConstructBuilding are workshop crafts: kept)
local FIRE_JOB_PREFIX = {'Dig', 'Carve', 'Store', 'Haul', 'Bring', 'Remove', 'Dump'}
local FIRE_JOB_EXACT = {ConstructBuilding = true, DetailWall = true, DetailFloor = true, SmoothWall = true,
                        SmoothFloor = true, DestroyBuilding = true, StoreItemInHospital = false}
local FIRE_JOB_NEVER = {Eat = true, Drink = true, Drink2 = true, Sleep = true, RecoverWounded = true,
                        DiagnosePatient = true, ImmobilizeBreak = true, DressWound = true, CleanPatient = true,
                        Surgery = true, Suture = true, SetBone = true, PlaceInTraction = true,
                        BringCrutch = true, ApplyCast = true, GiveFood = true, GiveWater = true,
                        BringItemToPatient = true, Rest = true, SeekInfant = true}
function fire_job_ok(jt)
    if type(jt) ~= 'string' or FIRE_JOB_NEVER[jt] then return false end
    if FIRE_JOB_EXACT[jt] ~= nil then return FIRE_JOB_EXACT[jt] end
    for _, p in ipairs(FIRE_JOB_PREFIX) do
        if jt:sub(1, #p) == p then return true end
    end
    return false
end

local function interior_floor(x, y, z)
    local ok, yes = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        if not tt then return false end
        local a = df.tiletype.attrs[tt]
        if df.tiletype_shape[a.shape] ~= 'FLOOR' then return false end
        local des = dfhack.maps.getTileFlags(x, y, z)
        if not des or des.outside or des.hidden or des.flow_size > 0 then return false end
        if des.feature_global or des.feature_local then return false end      -- not in a cavern
        if dfhack.buildings.findAtTile(xyz2pos(x, y, z)) then return false end
        return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) ~= 0
    end)
    return ok and yes or false
end

-- A cage room: an animal stockpile (where full cages go) on free floor
-- inside the fort, near where most citizens are, 3x3.
function prisoner_room(dry_run)
    local cit = citizens()
    if #cit == 0 then return {ok = false, error = 'no citizens'} end
    local byz = {}
    for _, p in ipairs(cit) do
        if not p.outside then byz[p.z] = byz[p.z] or {} table.insert(byz[p.z], p) end
    end
    local z, best = nil, 0
    for zz, l in pairs(byz) do if #l > best then z, best = zz, #l end end
    if not z then return {ok = false, error = 'no citizen is inside the fort'} end
    local xs, ys = {}, {}
    for _, p in ipairs(byz[z]) do table.insert(xs, p.x) table.insert(ys, p.y) end
    table.sort(xs) table.sort(ys)
    local cx, cy = xs[(#xs + 1) // 2], ys[(#ys + 1) // 2]
    local spot = find_rect(function(x, y) return interior_floor(x, y, z) end, cx, cy, 30, 3, 3)
    if not spot then return {ok = false, error = 'no free 3x3 floor inside the fort near the dwarves'} end
    local out = {ok = true, x = spot.x, y = spot.y, z = z, dry_run = dry_run or nil}
    local qf = reqscript('quickfort')
    local function put(dry)
        local ok, stats = pcall(qf.apply_blueprint, {mode = 'place', data = {[z] = {[spot.y] = {[spot.x] = 'a(3x3)'}}},
                                                     pos = {x = 0, y = 0, z = 0}, command = 'run', dry_run = dry})
        return ok and stats and stats.place_designated and stats.place_designated.value > 0
    end
    if not put(true) then return {ok = false, error = ('the game would not take a stockpile at x%d y%d'):format(spot.x, spot.y)} end
    if dry_run then return out end
    if not put(false) then return {ok = false, error = 'the game refused the cage stockpile'} end
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(spot.x, spot.y, z))
        if b and b:getType() == df.building_type.Stockpile then b.name = 'AI prisoners' end
    end)
    return out
end

local function burrow_named(name, make)
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if tostring(b.name) == name then return b end
    end
    if not make then return nil end
    local b = df.burrow:new()
    b.id = df.global.plotinfo.burrows.next_id
    df.global.plotinfo.burrows.next_id = b.id + 1
    b.name = name
    df.global.plotinfo.burrows.list:insert('#', b)
    return b
end

local function zone_by_id(id)
    for _, b in ipairs(df.global.world.buildings.all) do
        if b.id == id then return b end
    end
end

local function in_zone(z, x, y, zz)
    if zz ~= z.z or x < z.x1 or x > z.x2 or y < z.y1 or y > z.y2 then return false end
    local ok, yes = pcall(dfhack.buildings.containsTile, z, x, y)
    return not ok or yes
end

-- (0.105.0 review) a tile on the zone or beside one of its own tiles (not
-- just in the ring round its bounding box: a bedroom need not be square)
function touches_zone(inz, x, y)
    for dy = -1, 1 do
        for dx = -1, 1 do
            if inz(x + dx, y + dy) then return true end
        end
    end
    return false
end

-- The doors and hatches on a zone's edge (its tiles and the tiles touching them).
local function zone_doors(z)
    local out = {}
    local function inz(x, y) return in_zone(z, x, y, z.z) end
    for y = z.y1 - 1, z.y2 + 1 do
        for x = z.x1 - 1, z.x2 + 1 do
            if touches_zone(inz, x, y) then pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z.z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    out[b.id] = b
                end
            end) end
        end
    end
    return out
end

-- (0.105.0 review) another citizen in the zone (never locked in with a werebeast)
local function other_in_zone(z, uid)
    local ok, yes = pcall(function()
        for _, c in ipairs(report_citizens(true)) do
            if c.id ~= uid and in_zone(z, c.pos.x, c.pos.y, c.pos.z) then return true end
        end
        return false
    end)
    return not ok or yes
end

-- A room for a cell: a jail zone, else a free bedroom; the nearest to pos,
-- never one another cell holds.
local function cell_room(pos, taken)
    local best, bd
    local function try(z)
        if taken[z.id] then return end
        local dd = math.abs(z.x1 - pos.x) + math.abs(z.y1 - pos.y) + 3 * math.abs(z.z - pos.z)
        if not bd or dd < bd then best, bd = z, dd end
    end
    pcall(function() for _, z in ipairs(df.global.world.buildings.other.ZONE_DUNGEON) do try(z) end end)
    if best then return best, 'jail' end
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_BEDROOM) do
            if z.assigned_unit_id == -1 then try(z) end
        end
    end)
    return best, best and 'bedroom' or nil
end

-- (0.105.40b fix) The doors ai-insane holds locked for the insane: {id = true}.
local function insane_held()
    local ok, ids = pcall(function() return reqscript('ai-insane').held_ids() end)
    return ok and type(ids) == 'table' and ids or {}
end

-- (0.105.40b fix 2) The doors the threats rules have taken over and will
-- open themselves: the werebeast cells' locked doors (c.doors) and the
-- cavern seal's (locked, or shut by their lever). ai-insane drops its lock
-- on one of these without opening it; a door the rules only could need
-- (claimed_doors) it frees as usual, or it would stay locked for good.
function adopted_doors()
    local d = load_state()
    local out = {}
    for _, c in pairs(d.cells) do
        if type(c) == 'table' then
            for _, id in ipairs(type(c.doors) == 'table' and c.doors or {}) do out[tonumber(id) or id] = true end
        end
    end
    for id in pairs(seal_holds(d).ids) do out[id] = true end
    return out
end

-- (0.105.40b fix) The doors and hatches the threats rules hold or could
-- need: the werebeast cells' (those they locked, and every door of a cell's
-- room), the cavern seal's (locked, or shut by their lever), the openings on
-- record (the ways down to the caverns the seal locks), and the entrances'
-- the gate watcher holds shut now. ai-insane never locks one of these (only
-- 'don't lock'; what it drops unopened is adopted_doors).
function claimed_doors()
    local d = load_state()
    local out = {}
    for _, c in pairs(d.cells) do
        if type(c) == 'table' then
            for _, id in ipairs(type(c.doors) == 'table' and c.doors or {}) do out[tonumber(id) or id] = true end
            pcall(function()
                local z = c.zone and zone_by_id(c.zone)
                if z then for id in pairs(zone_doors(z)) do out[id] = true end end
            end)
        end
    end
    for id in pairs(seal_holds(d).ids) do out[id] = true end
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.x and o.y and o.z then
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(o.x, o.y, o.z))
                if b then out[b.id] = true end
            end)
        end
    end
    for id in pairs(watcher_held()) do out[id] = true end
    return out
end

-- Werebeasts in cells for the full moon: each id given gets a burrow on its
-- room (a jail, else a free bedroom); once the dwarf is inside, the room's
-- doors are locked. release: unlocked (only the doors the AI locked), the
-- dwarf out of the burrow, every cell not in `ids` let out too.
function moon_cell(ids, release, dry_run, txt)
    local d = load_state()
    local t = now_tick()
    local want = {}
    for _, id in ipairs(ids or {}) do want[tostring(id)] = true end
    local out = {ok = true, placed = {}, locked = {}, released = {}, waiting = {}, dry_run = dry_run or nil}
    local function free(uid, c)
        local u = df.unit.find(tonumber(uid))
        -- (0.105.0 review) never a cell whose werebeast has changed now (raging):
        -- a call listing only another werebeast, or a release, let it out
        if u and changed(u) then
            out.kept = out.kept or {}
            table.insert(out.kept, name_of(u, txt))
            return
        end
        if not dry_run then
            -- (13c) a door left locked, or a burrow not cleared, is said (it was
            -- silently dropped with the cell's record)
            local function failed(what, err)
                out.errors = out.errors or {}
                table.insert(out.errors, what .. ': ' .. tostring(err):sub(1, 100))
            end
            for _, bid in ipairs(c.doors or {}) do
                local okd, err = pcall(function()
                    local b = df.building.find(bid)
                    if b and not select(2, U.lock_door(b, false, 'cell')) then error('the lock could not be written') end -- (0.105.47) ai-util: the walk map redone
                end)
                if not okd then failed('door ' .. tostring(bid), err) end
            end
            local okb, err = pcall(function()
                local b = burrow_named(CELL_PREFIX .. uid, false)
                if b then
                    if u then dfhack.burrows.setAssignedUnit(b, u, false) end
                    dfhack.burrows.clearTiles(b)
                end
            end)
            if not okb then failed('cell burrow ' .. tostring(uid), err) end
            d.cells[uid] = nil
        end
        table.insert(out.released, u and name_of(u, txt) or uid)
    end
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' and (release or not want[uid]) then free(uid, c) end
    end
    if not release then
        local taken = {}
        for _, c in pairs(d.cells) do if type(c) == 'table' and c.zone then taken[c.zone] = true end end
        for uid in pairs(want) do
            local u = df.unit.find(tonumber(uid))
            if u and not dfhack.units.isDead(u) then
                local c = d.cells[uid]
                local z = c and c.zone and zone_by_id(c.zone)
                if not z then
                    local kind
                    z, kind = cell_room(u.pos, taken)
                    if not z then
                        out.ok = #out.placed + #out.locked > 0
                        out.error = 'no jail zone or free bedroom for a cell'
                    elseif not dry_run then
                        -- (0.105.0 review) the burrow made inside pcall: a failure is said,
                        -- and the cells already done this call are still saved below
                        local okb, eb = pcall(function()
                            local b = burrow_named(CELL_PREFIX .. uid, true)
                            dfhack.burrows.clearTiles(b)
                            for y = z.y1, z.y2 do
                                for x = z.x1, z.x2 do
                                    if in_zone(z, x, y, z.z) then dfhack.burrows.setAssignedTile(b, xyz2pos(x, y, z.z), true) end
                                end
                            end
                            dfhack.burrows.setAssignedUnit(b, u, true)
                        end)
                        if okb then
                            c = {zone = z.id, kind = kind, tick = t, doors = {}}
                            d.cells[uid] = c
                            taken[z.id] = true
                        else
                            out.error = 'the cell\'s burrow could not be made: ' .. tostring(eb)
                            out.ok = #out.placed + #out.locked > 0
                            z = nil
                        end
                    end
                    if z then table.insert(out.placed, name_of(u, txt)) end
                elseif not c.locked then
                    if in_zone(z, u.pos.x, u.pos.y, u.pos.z) and other_in_zone(z, u.id) then
                        table.insert(out.waiting, name_of(u, txt))       -- (0.105.0 review) someone else inside
                    elseif in_zone(z, u.pos.x, u.pos.y, u.pos.z) then
                        local insane = insane_held()
                        for id, b in pairs(zone_doors(z)) do
                            local okf, f = pcall(function() return b.door_flags.forbidden end)
                            if okf and not f then
                                if not dry_run then
                                    U.lock_door(b, true, 'cell') -- (0.105.47) ai-util: the walk map redone
                                    table.insert(c.doors, id)
                                end
                            elseif okf and insane[id] and not dry_run then
                                -- (0.105.40b fix) locked by ai-insane already: the cell's now
                                -- (ai-insane drops it without opening it)
                                table.insert(c.doors, id)
                            end
                        end
                        if not dry_run then c.locked = true end
                        table.insert(out.locked, name_of(u, txt))
                    else
                        table.insert(out.waiting, name_of(u, txt))
                    end
                end
            end
        end
    end
    if not dry_run then save_state(d) end
    if #out.placed + #out.locked + #out.released + #out.waiting == 0 and not out.error then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'every cell is as it should be'}
    end
    return out
end

-- (0.105.0 review) a citizen down in the cavern (on a cavern tile between
-- its levels, z1..z2): the seal would shut them out on the far side
local function citizen_in_cavern(z1, z2)
    if not z1 or not z2 then return nil end
    local lo, hi = math.min(z1, z2), math.max(z1, z2)
    local gids = cavern_gids()          -- (0.105.51) a cavern layer's tile, not the surface river's
    local ok, who = pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local p = u.pos
            if p.z >= lo and p.z <= hi then
                if on_cavern_tile(p.x, p.y, p.z, gids) then return u end
            end
        end
    end)
    return ok and who or nil
end

-- The caverns sealed: the doors and hatches on the given tiles (the way
-- down to the cavern: where the fort's ground meets it, the stair column)
-- locked; open: unlocked (only those the AI locked). (0.105.0 review) only
-- on those very tiles (no longer every door within a tile of them), and
-- refused while a citizen is down in the cavern (z1..z2: its levels).
-- (0.105.26) openings: every opening on record too (state.openings), but
-- never a cavern well's shaft hatch (its lever and the shaft watcher work
-- it, and the bucket needs it open whenever no great beast is about); a
-- door or hatch on a lever is shut by that lever (a lock does nothing to
-- it) when the lever works nothing else, and opened by it again after. The
-- doors and hatches found are put on record as openings. Said in the game.
local function announce(text, color)
    pcall(function() dfhack.gui.showAnnouncement('AI Overseer: ' .. text, color or COLOR_YELLOW, true) end)
end

-- a lever that works this building and nothing else, or nil
local function own_lever(bid)
    local ok, lid = pcall(function()
        local G = reqscript('ai-gates')
        local links = G.lever_links()
        for _, l in ipairs(links[bid] or {}) do
            local targets = G.lever_targets(links, l)
            if #targets == 1 and targets[1] == bid then return l end
        end
    end)
    return ok and lid or nil
end

function seal_cavern(layer, tiles, open, dry_run, z1, z2, openings)
    local d = load_state()
    local t = now_tick()
    local rec = type(d.sealed[layer]) == 'table' and d.sealed[layer] or nil
    if open then
        if not rec then return {ok = false, rejected = true, nothing_to_do = true, error = 'the AI sealed nothing there'} end
        -- (0.105.26 seal fix) an entrance the gate watcher holds shut (an
        -- ordinary danger at it) is left shut: the watcher opens it later
        local watched = watcher_held()
        local n, kept = 0, 0
        for _, bid in ipairs(rec.ids or {}) do
            pcall(function()
                local b = df.building.find(bid)
                if b and watched[b.id] then
                    kept = kept + 1
                elseif b then
                    if not dry_run then U.lock_door(b, false, 'seal') end -- (0.105.47) ai-util: the walk map redone
                    n = n + 1
                end
            end)
        end
        for sid, lever in pairs(type(rec.pulled) == 'table' and rec.pulled or {}) do
            pcall(function()
                local b = df.building.find(tonumber(sid))
                if b and watched[b.id] then
                    kept = kept + 1
                elseif b and b.door_flags.closed then
                    if not dry_run then reqscript('ai-gates').pull_instant(lever) end
                    n = n + 1
                end
            end)
        end
        if not dry_run then
            d.sealed[layer] = nil
            save_state(d)
            announce(('the ways into the caverns opened again (%s): no great beast left'):format(tostring(layer)),
                     COLOR_GREEN)
        end
        return {ok = true, unlocked = n, layer = layer, watcher_kept = kept > 0 and kept or nil, dry_run = dry_run or nil}
    end
    local inside = citizen_in_cavern(z1, z2)
    if inside then
        return {ok = false, rejected = true, waiting = true,
                error = name_of(inside) .. ' is down in ' .. tostring(layer) .. ': not sealed while a dwarf is on the far side'}
    end
    local skip, list, given = {}, {}, {}
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.kind == 'well' and o.x then skip[okey(o.x, o.y, o.z)] = true end
    end
    for _, p in ipairs(tiles or {}) do
        local x, y, z = tonumber(p.x), tonumber(p.y), tonumber(p.z)
        if x and y and z then
            table.insert(list, {x = x, y = y, z = z})
            given[okey(x, y, z)] = true
        end
    end
    local well_kept, well_why, well_dwarf = 0, nil, 0
    if openings then
        for _, o in pairs(d.openings) do
            if type(o) == 'table' and o.x and o.kind ~= 'well' then
                -- (0.105.47, K48-K4) a cavern well's door with a dwarf beyond it, or
                -- whose shaft gate keeps the cavern out: left open. (r2h7) by
                -- seal_lockable, the test the openings report gives the brain
                local okl, can, why, blocked, code = pcall(seal_lockable, o)
                if okl and not can and (code == 'blocked' or code == 'skip') then
                    well_kept = well_kept + 1
                    if blocked then
                        well_dwarf = well_dwarf + 1
                        well_why = tostring(why)
                    else
                        well_why = well_why or tostring(why)
                    end
                elseif not okl or can then
                    table.insert(list, {x = o.x, y = o.y, z = o.z})
                end
                -- (not lockable for want of a door: nothing to add; the walk below finds nothing there either)
            end
        end
    end
    local found, at = {}, {}
    for _, p in ipairs(list) do
        if not skip[okey(p.x, p.y, p.z)] then
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(p.x, p.y, p.z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    found[b.id] = b
                    at[b.id] = p
                end
            end)
        end
    end
    rec = rec or {ids = {}, tick = t}
    rec.pulled = type(rec.pulled) == 'table' and rec.pulled or {}
    local have, n, already, adopted, pull_failed = {}, 0, 0, 0, 0
    for _, id in ipairs(rec.ids) do have[id] = true end
    -- (0.105.26 seal fix) one the gate watcher already holds shut goes on
    -- the record too, so the watcher doesn't open it while the beast is about
    local watched = watcher_held()
    local insane = insane_held()      -- (0.105.40b fix) ai-insane's locks: the seal's now
    local lure = lure_open_ids()      -- (0.105.45) a lure's open door is left to the lure
    for id in pairs(lure) do found[id] = nil end
    for id, b in pairs(found) do
        local lever = own_lever(id)
        if lever then
            local okc, c = pcall(function() return b.door_flags.closed end)
            if okc and not c then
                -- (0.105.33 review) counted only when the pull worked (a failed
                -- pull said "locked" and the opening still read unsealed)
                if not dry_run then
                    local okp, pulled = pcall(function() return reqscript('ai-gates').pull_instant(lever) end)
                    if okp and pulled then
                        rec.pulled[tostring(id)] = lever
                        n = n + 1
                    else
                        pull_failed = pull_failed + 1
                    end
                else
                    n = n + 1
                end
            elseif okc then
                already = already + 1
                if watched[id] and rec.pulled[tostring(id)] == nil then
                    if not dry_run then rec.pulled[tostring(id)] = lever end
                    adopted = adopted + 1
                end
            end
        else
            local okf, f = pcall(function() return b.door_flags.forbidden end)
            if okf and not f then
                if not dry_run then
                    U.lock_door(b, true, 'seal') -- (0.105.47) ai-util: the walk map redone
                    if not have[id] then table.insert(rec.ids, id); have[id] = true end
                end
                n = n + 1
            elseif okf then
                already = already + 1
                if (watched[id] or insane[id]) and not have[id] then
                    if not dry_run then table.insert(rec.ids, id); have[id] = true end
                    adopted = adopted + 1
                end
            end
        end
        local p = at[id]
        if p and given[okey(p.x, p.y, p.z)] and not dry_run then
            note_opening(d, p.x, p.y, p.z, 'way_down', tostring(layer), t)
        end
    end
    if n == 0 and adopted > 0 then
        -- everything locked already, some by the gate watcher: on the seal's record now
        if not dry_run then
            d.sealed[layer] = rec
            save_state(d)
        end
        return {ok = true, locked = 0, adopted = adopted, layer = layer, dry_run = dry_run or nil}
    end
    if n == 0 and well_kept > 0 and already == 0 and pull_failed == 0 then
        -- (0.105.51) the only ways down on record are cavern wells' doors, left
        -- open (their shaft gate keeps the cavern out, or a dwarf is beyond):
        -- said as such, not "no door or hatch" (the planner leaves them out too)
        if not dry_run then save_state(d) end
        return {ok = false, rejected = true, well_kept = well_kept, nothing_lockable = true,   -- (r2h7)
                nothing_to_do = well_dwarf == 0 or nil, waiting = well_dwarf > 0 or nil,
                error = 'only cavern well doors on the way down, left open: ' .. tostring(well_why):sub(1, 100)}
    end
    if n == 0 then
        if not dry_run then save_state(d) end          -- (the openings found are kept)
        return {ok = false, rejected = true, nothing_to_do = already > 0 and pull_failed == 0,
                pull_failed = pull_failed > 0 and pull_failed or nil,
                nothing_lockable = (already == 0 and pull_failed == 0) or nil,   -- (r2h7) the brain stops asking
                error = pull_failed > 0 and (pull_failed .. ' lever(s) on the way down would not pull: the doors stay open')
                    or already > 0 and 'every door and hatch on the way down is locked already'
                    or 'no door or hatch on the way down to lock'}
    end
    if not dry_run then
        d.sealed[layer] = rec
        save_state(d)
        announce(('%d way(s) into the caverns locked against a great beast (%s)'):format(n, tostring(layer)))
    end
    return {ok = true, locked = n, adopted = adopted > 0 and adopted or nil, layer = layer, dry_run = dry_run or nil,
            pull_failed = pull_failed > 0 and pull_failed or nil,
            well_kept = well_kept > 0 and well_kept or nil}   -- (0.105.47) a well's door left: a dwarf beyond it
end

-- (0.105.40b) A creature that breathes, spits or hurls fire (a dragon, a fire
-- imp, a generated beast with a fire breath), or burns to the touch: no melee
-- squad goes at it (the fire takes a squad in its armour before it lands a
-- blow; brain/planner_firebreath.py). Read from its caste's raws: each natural
-- ability (caste.body_info.interactions, CAN_DO_INTERACTION) whose CDI:FLOW is
-- DRAGONFIRE, FIREJET or FIREBALL (interaction.material_breath), or whose
-- interaction's material target emits one of those (a generated beast's);
-- the caste flag IMMOLATE. One answer per race and caste, kept for the
-- session (raws don't change while a world is loaded).
-- Returns 'breath' / 'jet' / 'fireball' / 'burns', or false.
FIRE_BREATH_CACHE = FIRE_BREATH_CACHE or {}
local FIRE_FLOW_HOW = {DRAGONFIRE = 'breath', FIREJET = 'jet', FIREBALL = 'fireball'}

-- (fix41) the cache belongs to one world: another save loaded in the same
-- DFHack session has other races under the same numbers (generated beasts)
function fire_breath_of(race, caste)
    -- (r1g9) the world by its name, not the save folder an autosave renames
    local okw, world = pcall(function() return U.world_name() end)
    if not okw or type(world) ~= 'string' then
        okw, world = pcall(function() return df.global.world.cur_savegame.save_dir end)
    end
    world = tostring(okw and world or '?')
    if FIRE_BREATH_WORLD ~= world then
        FIRE_BREATH_CACHE, FIRE_BREATH_WORLD = {}, world
    end
    local key = tostring(race) .. ':' .. tostring(caste)
    local v = FIRE_BREATH_CACHE[key]
    if v ~= nil then return v end
    v = false
    local fire = {}
    pcall(function()
        for name, how in pairs(FIRE_FLOW_HOW) do
            local e = df.breath_attack_type[name]
            if e ~= nil then fire[e] = how end
        end
    end)
    local okc, c = pcall(function() return df.creature_raw.find(race).caste[caste] end)
    if okc and c then
        pcall(function()
            for _, a in ipairs(c.body_info.interactions) do
                local info = a.interaction
                local how = fire[info.material_breath]
                if not how then
                    pcall(function()
                        local it = df.interaction.find(info.type_id)
                        for _, t in ipairs(it and it.targets or {}) do
                            local okb, b = pcall(function() return t.breath_attack_type end)
                            if okb and b ~= nil and fire[b] then how = fire[b]; break end
                        end
                    end)
                end
                if how then v = how; return end
            end
        end)
        if not v then
            local oki, imm = pcall(function() return c.flags.IMMOLATE end)
            if oki and imm then v = 'burns' end
        end
    end
    FIRE_BREATH_CACHE[key] = v
    return v
end

-- (0.105.40b) The others_on_map report's threats marked: fire_breather = true
-- and fire_how for each one that breathes fire (nothing added to the others,
-- so a report without one is as before). Returns how many were marked.
function mark_fire_breathers(o)
    local n = 0
    for _, t in ipairs(type(o) == 'table' and type(o.threats) == 'table' and o.threats or {}) do
        local u = type(t) == 'table' and t.id ~= nil and df.unit.find(t.id) or nil
        if u then
            local okf, how = pcall(fire_breath_of, u.race, u.caste)
            if okf and how then
                t.fire_breather, t.fire_how = true, how
                n = n + 1
            end
        end
    end
    return n
end
