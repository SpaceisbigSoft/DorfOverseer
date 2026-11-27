-- ai-threats-actions: what the fort does: fire_guard, the prisoners' room, the moon cell
-- (0.105.119: seal_cavern and the creatures that breathe fire in ai-threats-seal).
--
-- (r8) A part of ai-threats, not a script of its own: ai-threats.lua loads it
-- into its own environment, so every name here is reqscript('ai-threats').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-threats-actions is a part of ai-threats; run ai-threats') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-threats-actions'] = '0.105.135'   -- (0.105.26) bumped with BRIDGE_VERSION

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

-- (0.105.115 item24) the werebeast cells behind drawbridges (lua/ai-werecells.lua)
local function W() return reqscript('ai-werecells') end
local function were_zone(key)
    local ok, z = pcall(function()
        local c = W().find(key)
        return c and W().zone_of(c)
    end)
    return ok and z or nil
end

local function zone_by_id(id)
    -- (0.105.119 item31) a side cell dug for a cursed dwarf: its key
    if type(id) == 'string' and id:sub(1, 4) == 'dig:' then
        local rec = load_state().digs[id]
        return type(rec) == 'table' and rec.ready and W().side_zone(id, rec) or nil
    end
    if type(id) == 'string' then return were_zone(id) end   -- (item24) a were cell's key
    for _, b in ipairs(df.global.world.buildings.all) do
        if b.id == id then return b end
    end
end

local function in_zone(z, x, y, zz)
    if zz ~= z.z or x < z.x1 or x > z.x2 or y < z.y1 or y > z.y2 then return false end
    -- (item24) a were cell's or (item31) a side cell's box: a plain table. (0.105.119
    -- item31) A DF zone is userdata and `z.were` on it threw ("Cannot read field
    -- building_civzonest.were"), so since 0.105.115 cell_room saw no jail or bedroom
    -- at all: A, 25 Nov 16:33-16:44, 39 calls "no jail zone or free bedroom" with 2 jails
    if type(z) == 'table' then return true end
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
-- (0.105.76, verifier) only a room with a door to lock (a doorless room was
-- "locked" with no door: the beast held by its burrow alone); the werebeast's
-- own bedroom too (a fort without a jail or a free bedroom had no cell)
-- a floor tile of the cell a dwarf can stand on (no building but the zone
-- and its bed, chest or cabinet), the zone's own walk group: nil if none
local CELL_FURNITURE = {Bed = true, Box = true, Cabinet = true, Chair = true, Table = true}
local function cell_spot(z)
    local best
    for y = z.y1, z.y2 do
        for x = z.x1, z.x2 do
            if not best and in_zone(z, x, y, z.z) then pcall(function()
                local tt = dfhack.maps.getTileType(x, y, z.z)
                local a = tt and df.tiletype.attrs[tt]
                if not a or df.tiletype_shape[a.shape] ~= 'FLOOR' then return end
                local p = xyz2pos(x, y, z.z)
                if dfhack.maps.getWalkableGroup(p) == 0 then return end
                local b = dfhack.buildings.findAtTile(p)
                if b and b:getType() ~= df.building_type.Civzone
                        and not CELL_FURNITURE[df.building_type[b:getType()]] then return end
                best = p
            end) end
        end
    end
    return best
end

local SPARE_KINDS = {Office = true, Tomb = true, Bedroom = true}
SPARE_MAX_TILES = 36
local function cell_room(pos, taken, uid, d)
    local best, bd, bkind
    local function try(z, were, kind, alone)
        pcall(function()
            if taken[z.id] then return end
            local dd = math.abs(z.x1 - pos.x) + math.abs(z.y1 - pos.y) + 3 * math.abs(z.z - pos.z)
            if bd and dd >= bd then return end
            if not were and next(zone_doors(z)) == nil then return end
            if alone and other_in_zone(z, uid) then return end
            best, bd, bkind = z, dd, kind
        end)
    end
    local function each(list, fn) pcall(function() for _, z in ipairs(list) do fn(z) end end) end
    local other = df.global.world.buildings.other
    -- (0.105.115 item24) a were cell first: built, its lever linked, its bridge
    -- down, nobody inside (a changed werebeast breaks doors; a raised bridge holds)
    pcall(function()
        local links = W().lever_links()
        for _, c in ipairs(W().cells()) do
            local z = W().zone_of(c)
            if not taken[z.id] and W().ready(c, links) then try(z, true, 'were', true) end
        end
    end)
    if best then return best, bkind end
    each(other.ZONE_DUNGEON, function(z) try(z, false, 'jail') end)
    if best then return best, bkind end
    each(other.ZONE_BEDROOM, function(z)
        if z.assigned_unit_id == -1 or (uid and z.assigned_unit_id == uid) then try(z, false, 'bedroom') end
    end)
    if best then return best, bkind end
    -- (0.105.119 item31) any other room with a door to lock: an office, a tomb,
    -- another's bedroom (nobody inside: never locked in with them), or a side
    -- cell dug for this before; small rooms only (no hall)
    each(other.ANY_ZONE, function(z)
        local okk, k = pcall(function() return df.civzone_type[z.type] end)
        if okk and SPARE_KINDS[k] and (z.x2 - z.x1 + 1) * (z.y2 - z.y1 + 1) <= SPARE_MAX_TILES then
            try(z, false, 'room', true)
        end
    end)
    for key, rec in pairs(d and d.digs or {}) do
        if type(rec) == 'table' and rec.ready then try(W().side_zone(key, rec), false, 'side', true) end
    end
    if best then return best, bkind end
    -- (item31) a were cell dug but not lockable yet (its lever unlinked, its
    -- bridge not built): its burrow holds them, and it is locked once linked
    pcall(function()
        for _, c in ipairs(W().cells()) do
            local z = W().zone_of(c)
            if not taken[z.id] and cell_spot(z) then try(z, true, 'were_open', true) end
        end
    end)
    return best, bkind
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
    -- (0.105.115 item24) the were cells' bridges and levers: never opened by another rule
    pcall(function() for id in pairs(W().piece_ids()) do out[id] = true end end)
    return out
end

-- (0.105.103) a cell's doors still locked in the game: every door on its
-- record there and forbidden. E, 24 Nov 14:00: three cells on record as
-- locked had their doors unlocked (the cells' record is a file outside the
-- save; a game reopened from an earlier save, or anything else unlocking
-- them, left the record saying locked), and the brain sends no moon_cell
-- for a cell it reads locked. A cell whose doors aren't held counts as not
-- locked, and is locked again.
function cell_doors_held(c)
    -- (0.105.115 item24) a were cell is held by its raised bridge
    if type(c) == 'table' and c.kind == 'were' then
        local ok, up = pcall(function()
            local wc = W().find(c.zone)
            return wc and W().cell_state(wc).raised
        end)
        return (ok and up) and true or false
    end
    if type(c) ~= 'table' or type(c.doors) ~= 'table' or #c.doors == 0 then return false end
    for _, id in ipairs(c.doors) do
        local b = df.building.find(tonumber(id) or id)
        local ok, f = pcall(function() return b.door_flags.forbidden end)
        if not (b and ok and f) then return false end
    end
    return true
end

-- (0.105.103) who else stands in a werebeast's locked cell: names (at most
-- 3). E, 24 Nov 08:31: Urvad's cell was locked at 08:28 with him alone, yet
-- he changed with Dakost and Momuz inside and killed them, then Deler and
-- Inod; no rule had unlocked the door. The report says it each cycle, so
-- the next full moon shows how they get in.
function cell_others(c, uid, txt)
    if type(c) ~= 'table' or not c.zone then return nil end
    local z = type(c.zone) == 'string' and zone_by_id(c.zone) or df.building.find(c.zone)
    if not z then return nil end
    local out = {}
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            if tostring(u.id) ~= tostring(uid) and in_zone(z, u.pos.x, u.pos.y, u.pos.z) and #out < 3 then
                table.insert(out, name_of(u, txt))
            end
        end
    end)
    return #out > 0 and out or nil
end

-- (0.105.115 item18) the doors of every locked cell, handed to ai-util's
-- door guard: no other rule unlocks them (lock_door refuses its unlock)
function hold_cell_doors(d)
    local ids = {}
    for _, c in pairs((d or load_state()).cells or {}) do
        if type(c) == 'table' and c.locked then
            for _, id in ipairs(type(c.doors) == 'table' and c.doors or {}) do
                local n = tonumber(id)
                if n then ids[n] = true end
            end
        end
    end
    pcall(function() U.hold_cell_doors(ids) end)
    return ids
end

-- (0.105.115 item18) A cursed dwarf confined to the cell: the cell's burrow
-- is their only one (taken out of every other burrow, the burrows kept on
-- the cell's record to give back at the release). E, 25 Nov: Dodók and the
-- child Uzol "waited" for their cells 14+ days, worked outside them and
-- turned there. DF's civilian alarm sends every civilian to its burrows
-- whatever they belong to, so the move below (CELL_MOVE_TICKS) is what
-- gets them in at last.
CELL_MOVE_TICKS = 1200        -- a day placed and still outside: moved in
local function confine(u, c)
    local own = CELL_PREFIX .. tostring(u.id)
    c.burrows_left = type(c.burrows_left) == 'table' and c.burrows_left or {}
    local n = 0
    pcall(function()
        for _, b in ipairs(df.global.plotinfo.burrows.list) do
            if tostring(b.name) ~= own then
                local okm, member = pcall(dfhack.burrows.isAssignedUnit, b, u)
                if okm and member then
                    if pcall(dfhack.burrows.setAssignedUnit, b, u, false) then
                        table.insert(c.burrows_left, b.id)
                        n = n + 1
                    end
                end
            end
        end
    end)
    return n
end

-- the burrows a released dwarf was taken out of, given back (those still there)
local function unconfine(u, c)
    if not u or type(c.burrows_left) ~= 'table' then return end
    for _, bid in ipairs(c.burrows_left) do
        pcall(function()
            for _, b in ipairs(df.global.plotinfo.burrows.list) do
                if b.id == tonumber(bid) then dfhack.burrows.setAssignedUnit(b, u, true) end
            end
        end)
    end
end

-- (0.105.115 item18) Moved into the cell at once (DFHack's units.teleport: a
-- direct move, not a walk; the same call the caravans' 'edge' step uses):
-- a cursed dwarf placed CELL_MOVE_TICKS ago and still outside, or any once
-- the brain says the change is close (move_in). Never one in beast form, in
-- a fight, caged or chained; never with anyone else in the cell. Their job is
-- dropped first (DF's removeWorker) so they don't walk off to it.
-- Returns true when moved, or nil and why not.
-- (R30b) E, 25 Nov 22:04 and 22:18: the cursed moved in, the bridge raised,
-- and found outside 30 s later, levels away. DFHack's units.teleport sets the
-- position and leaves the unit's path (unit.path) as it was: DF walks the unit
-- on along the old path's next steps from wherever it stands, out through the
-- wall. The old path and its goal dropped (DF finds a new one, inside).
function drop_path(u)
    local ok = pcall(function()
        local pp = u.path.path
        pp.x:resize(0); pp.y:resize(0); pp.z:resize(0)
        u.path.dest.x, u.path.dest.y, u.path.dest.z = -30000, -30000, -30000
        pcall(function() u.path.goal = df.unit_path_goal.None end)
    end)
    return ok
end

local function move_in(u, z, uid)
    if changed(u) then return nil, 'in beast form' end
    local okf, fight = pcall(function() return u.opponent.unit_id ~= -1 end)
    if okf and fight then return nil, 'in a fight' end
    local okc, held = pcall(function() return u.flags1.caged or u.flags1.chained end)
    if okc and held then return nil, 'caged' end
    if other_in_zone(z, uid) then return nil, 'someone else in the cell' end
    local p = cell_spot(z)
    if not p then return nil, 'no floor in the cell to stand on' end
    pcall(function() if u.job.current_job then dfhack.job.removeWorker(u.job.current_job, 0) end end)
    local ok, done = pcall(dfhack.units.teleport, u, p)
    if not ok or done == false then return nil, 'the move was refused: ' .. tostring(done):sub(1, 60) end
    drop_path(u)
    return true
end

-- (0.105.119 item34/31) is the cell's dwarf inside it? true, false, or nil (can't tell)
function cell_has(c, u)
    if type(c) ~= 'table' or not c.zone or not u then return nil end
    local ok, yes = pcall(function()
        local z = zone_by_id(c.zone)
        if not z then return nil end
        return in_zone(z, u.pos.x, u.pos.y, u.pos.z)
    end)
    if ok then return yes end
    return nil
end

-- (R30b) Is the cell's werebeast held by stone and a raised bridge now? A
-- were cell on record as locked, its bridge raised and still, its shell
-- sealed (ai-werecells sealed: wall all round, roof above), DF's walk map
-- parting the cell from the lever's tile in front of it (joined false, not
-- unread), and the dwarf inside it. A, 25 Nov 19:21-22:24: 105 squad
-- orders at Zuglar in beast form while he stood locked in such a cell, six
-- squads every moon: the threats report says `sealed` and no squad is sent.
function cell_sealed(c, u)
    if type(c) ~= 'table' or c.kind ~= 'were' or not c.locked or c.reserved or not u then return false end
    local ok, yes = pcall(function()
        local wc = W().find(c.zone)
        if not wc then return false end
        local st = W().cell_state(wc)
        if not st.raised or st.moving or st.joined then return false end
        if W().sealed(wc) ~= true then return false end
        if W().joined(wc) ~= false then return false end
        return cell_has(c, u) == true
    end)
    return ok and yes == true
end

-- (r33a) A were cell (kind 'were') whose drawbridge can't hold anyone now:
-- no bridge on its doorway (never built, or gone), no lever, not built, or
-- the cell itself gone from the AI's levels. The reason, or nil (worked as a
-- were cell). B, 26 Nov 14:23+: the dead weresheep Bomrek's cell was on
-- record behind a drawbridge that was not there; free() refused "stays up"
-- every call and the record never cleared. Can't tell (no ai-werecells,
-- an error): nil, as before.
function were_unworkable(c)
    if type(c) ~= 'table' or c.kind ~= 'were' then return nil end
    local ok, why = pcall(function()
        local wc = W().find(c.zone)
        if not wc then return 'the cell is gone' end
        local st = W().cell_state(wc)
        if type(st) ~= 'table' or st.built then return nil end     -- built: both stand there
        if not st.bridge_id then return 'no drawbridge on the cell\'s doorway' end
        if not st.lever_id then return 'no lever in front of the cell' end
        return 'the cell\'s bridge or lever is not built'
    end)
    return ok and why or nil
end

-- Werebeasts in cells for the full moon: each id given gets a burrow on its
-- room (a jail, else a free bedroom); once the dwarf is inside, the room's
-- doors are locked. release: unlocked (only the doors the AI locked), the
-- dwarf out of the burrow, every cell not in `ids` let out too.
function moon_cell(ids, release, dry_run, txt, opts, raw)
    opts = type(opts) == 'table' and opts or {}
    -- (r33a) the bridge's action, for its dead_only and all (booleans, checked there)
    if type(raw) == 'table' then
        if raw.dead_only == true then opts.dead_only = true end
        if raw.all == true then opts.all = true end
    end
    local d = load_state()
    local t = now_tick()
    local want = {}
    for _, id in ipairs(ids or {}) do want[tostring(id)] = true end
    local out = {ok = true, placed = {}, locked = {}, released = {}, waiting = {}, dry_run = dry_run or nil}
    local function dead_or_gone(u) return (not u) or dfhack.units.isDead(u) end
    -- (0.105.114) a release waits while any living werebeast is in its beast
    -- form or a cursed one is fighting (E, 25 Nov: cells let out between
    -- moons while bitten dwarves were still in fights)
    -- (r33a) dead_only: a release of the dead (or gone) werebeasts' cells only
    -- (B, 26 Nov: "the cells of dead werebeasts" freed Asob's cell, reserved
    -- the call before, and the two calls flipped it every 20-40 s). A release
    -- keeps a living cursed dwarf's reserved cell unless `all` (the Rules
    -- switch off): nobody is in it, and the reserve would only take it again.
    local dead_only = release and opts.dead_only == true
    if release and not dry_run and not dead_only then
        for uid, c in pairs(d.cells) do
            local u = df.unit.find(tonumber(uid))
            if type(c) == 'table' and not dead_or_gone(u) then
                local okc, fight = pcall(function() return u.opponent.unit_id ~= -1 end)
                if changed(u) or (okc and fight) then
                    return {ok = false, rejected = true, wait = true,
                            error = name_of(u, txt) .. (changed(u) and ' is in its beast form' or ' is in a fight')
                                .. ': no werebeast let out yet'}
                end
            end
        end
    end
    local function free(uid, c)
        local u = df.unit.find(tonumber(uid))
        local living = u and not dead_or_gone(u)
        -- (r33a) a release of the dead's cells: a living dwarf's cell untouched (said
        -- as kept only when cursed: a cell for the living isn't this call's)
        if dead_only and living then
            return
        end
        if release and living and c.reserved and not c.locked and opts.all ~= true then
            out.kept = out.kept or {}
            table.insert(out.kept, name_of(u, txt) .. ' (reserved)')
            return
        end
        -- (0.105.0 review) never a cell whose werebeast has changed now (raging):
        -- a call listing only another werebeast, or a release, let it out.
        -- (0.105.114) a dead one's cell is freed: E kept 40 cells of the dead
        if u and changed(u) and not dfhack.units.isDead(u) then
            out.kept = out.kept or {}
            table.insert(out.kept, name_of(u, txt))
            return
        end
        -- (0.105.114) a living cursed dwarf's cell is kept unless this is a
        -- release: a call that didn't name them (a list cut short) let them out
        if not release and u and not dead_or_gone(u) and type(were_cursed) == 'function' then
            local okw, cursed = pcall(were_cursed, u)
            if okw and cursed then
                out.kept = out.kept or {}
                table.insert(out.kept, name_of(u, txt))
                return
            end
        end
        -- (0.105.115 item24) a were cell: its bridge lowered first; not lowered
        -- (someone on the tile, the lever unlinked), the cell is kept as it is
        -- (r33a) a were cell whose bridge isn't there (or the cell gone): freed as a
        -- plain room (its doors unlocked, the record dropped), said in notes
        local gone = c.kind == 'were' and were_unworkable(c)
        if gone then
            out.notes = out.notes or {}
            table.insert(out.notes, ('the cell of %s was on record behind a drawbridge (%s): freed as a plain room')
                :format(u and name_of(u, txt) or ('unit ' .. tostring(uid)), gone))
        end
        if c.kind == 'were' and not gone then
            local okr, down, why = pcall(function()
                local wc = W().find(c.zone)
                if not wc then return true end
                return W().set_raised(wc, false, dry_run)
            end)
            -- (r33a) a dead one's cell whose bridge stands down already (its lever
            -- unlinked: set_raised refuses before it looks): nothing to lower
            if not (okr and down) and dead_or_gone(u) then
                local okd, isdown = pcall(function()
                    local st = W().cell_state(W().find(c.zone))
                    return not st.raised and not st.moving
                end)
                if okd and isdown then okr, down = true, true end
            end
            if not (okr and down) then
                out.errors = out.errors or {}
                table.insert(out.errors, 'the drawbridge of ' .. (u and name_of(u, txt) or ('unit ' .. tostring(uid))) .. '\'s cell stays up: '
                    .. tostring(okr and why or down):sub(1, 100))
                return
            end
        end
        local pre = {}
        for _, id in ipairs(type(c.pre) == 'table' and c.pre or {}) do pre[tostring(id)] = true end
        if not dry_run then
            -- (13c) a door left locked, or a burrow not cleared, is said (it was
            -- silently dropped with the cell's record)
            local function failed(what, err)
                out.errors = out.errors or {}
                table.insert(out.errors, what .. ': ' .. tostring(err):sub(1, 100))
            end
            for _, bid in ipairs(c.doors or {}) do
                local okd, err = pcall(function()
                    if pre[tostring(bid)] then return end     -- (0.105.114) locked before the cell: left so
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
                if u and not dead_or_gone(u) then unconfine(u, c) end   -- (0.105.115 item18) their burrows back
            end)
            if not okb then failed('cell burrow ' .. tostring(uid), err) end
            d.cells[uid] = nil
        end
        if dead_or_gone(u) then
            out.dead = (out.dead or 0) + 1
        else
            table.insert(out.released, name_of(u, txt))
        end
    end
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' and (release or not want[uid]) then free(uid, c) end
    end
    -- (r33a) a dead-only release with nothing dead left to free: as a nothing-to-do
    if dead_only and (out.dead or 0) == 0 and not out.errors then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'no dead werebeast\'s cell on record'}
    end
    -- (0.105.115 item18) a cursed dwarf outside the cell moved in (said either way)
    local function try_move(u, z)
        if dry_run then
            out.would_move = out.would_move or {}
            table.insert(out.would_move, name_of(u, txt))
            return
        end
        local moved, why = move_in(u, z, u.id)
        if moved then
            out.moved = out.moved or {}
            table.insert(out.moved, name_of(u, txt))
        else
            out.not_moved = out.not_moved or {}
            table.insert(out.not_moved, name_of(u, txt) .. ': ' .. tostring(why))
        end
    end
    if not release then
        local taken = {}
        for _, c in pairs(d.cells) do if type(c) == 'table' and c.zone then taken[c.zone] = true end end
        -- (0.105.119 item31) the side cells being dug: their door placed once dug, ready once built
        for key, rec in pairs(d.digs) do
            if type(rec) == 'table' and rec.door and not rec.ready then
                local okst, st = pcall(W().side_step, rec, dry_run, t)
                if okst and st == 'ready' and not dry_run then rec.ready = true end
                out.side = out.side or {}
                table.insert(out.side, key .. ': ' .. tostring(okst and st or 'unreadable'))
            end
            if type(rec) == 'table' and not rec.ready then taken[key] = true end
        end
        for uid in pairs(want) do
            local u = df.unit.find(tonumber(uid))
            -- (0.105.96) a soldier out of the squad first: on duty (training,
            -- stationed) a squad's orders take them past the cell's burrow. Live
            -- 23 Nov, B: the captain of the guard Mafol and the wrestler Ineth
            -- waited for their cells 4 cycles each, changed outside them and
            -- killed (a bone doctor) before the militia shot them
            local oksq, in_squad = pcall(function() return u.military.squad_id ~= -1 end)
            if u and not opts.reserve and not dfhack.units.isDead(u) and not changed(u) and oksq and in_squad then
                local name = name_of(u, txt)
                if dry_run then
                    out.unsquad = out.unsquad or {}
                    table.insert(out.unsquad, name)
                else
                    local oks, done = pcall(function() return dfhack.military.removeFromSquad(u.id) end)
                    out.unsquad = out.unsquad or {}
                    table.insert(out.unsquad, name .. ((oks and done) and '' or ' (the game kept them in the squad)'))
                end
            end
            if u and not dfhack.units.isDead(u) then
                local c = d.cells[uid]
                -- (0.105.103) on record as locked, its doors not held in the game: lock again
                -- (0.105.114) its doors kept on record (they were wiped, and a door
                -- still locked was then left off it: E's cells read "doors 0",
                -- never held, and were relocked every cycle)
                if c and c.locked and not cell_doors_held(c) then
                    out.relock = out.relock or {}
                    table.insert(out.relock, name_of(u, txt))
                    if not dry_run then c.locked = nil end
                end
                -- (0.105.119 item34/31) locked in, yet not inside (F, 25 Nov: Besmar locked
                -- 17:21:40 behind a raised bridge, turned 17:27:32 nine levels down and
                -- killed Tosid): not locked, moved in again now
                if c and c.locked and not c.reserved and cell_has(c, u) == false then
                    out.escaped = out.escaped or {}
                    table.insert(out.escaped, ('%s (at %d,%d,%d)'):format(name_of(u, txt), u.pos.x, u.pos.y, u.pos.z))
                    if not dry_run then c.locked = nil end
                    opts.move_in = true
                end
                -- (item31) a were cell taken while its lever was unlinked: a were cell once linked
                if c and c.kind == 'were_open' then
                    pcall(function()
                        local wc = W().find(c.zone)
                        local st = wc and W().cell_state(wc)
                        if st and st.built and st.linked and not dry_run then c.kind = 'were' end
                    end)
                end
                -- (r33a) a were cell whose drawbridge isn't there (never built, gone):
                -- nothing holds them in it. Not locked (or its record says locked and
                -- nothing holds it): the record dropped, another room taken (a jail,
                -- a bedroom, a room with a door, else one dug); said
                if c and c.kind == 'were' and not (c.locked and cell_doors_held(c)) then
                    local why = were_unworkable(c)
                    if why then
                        out.rekind = out.rekind or {}
                        table.insert(out.rekind, name_of(u, txt) .. ': ' .. why .. ': another room')
                        if not dry_run then d.cells[uid] = nil end
                        if c.zone then taken[c.zone] = true end      -- not this one again this call
                        c = nil
                    end
                end
                local z = c and c.zone and zone_by_id(c.zone)
                -- (item31) a cell made ready before the moon (reserved): still free for them?
                if c and c.reserved and not opts.reserve then
                    local okz, other = pcall(function()
                        return c.kind ~= 'were' and c.kind ~= 'were_open' and z and z.assigned_unit_id ~= -1
                            and z.assigned_unit_id ~= u.id and c.kind == 'bedroom'
                    end)
                    if not z or (okz and other) or other_in_zone(z, u.id) and not in_zone(z, u.pos.x, u.pos.y, u.pos.z) then
                        if not dry_run then d.cells[uid] = nil end
                        taken[c.zone] = nil
                        c, z = nil, nil
                    end
                end
                if opts.reserve and c then
                    -- (item31) a reserve call touches no cell already made
                elseif not z or (c and c.reserved and not opts.reserve) then
                    local kind = c and c.kind
                    if not z then z, kind = cell_room(u.pos, taken, u.id, d) end
                    if not z then
                        -- (0.105.119 item31) no room at all: a side cell dug off the nearest
                        -- corridor (A, 25 Nov: 39 calls refused, 25 dead), never a refusal
                        local okw, site = pcall(function() return W().side_site(u.pos, taken) end)
                        site = okw and site or nil
                        out.digging = out.digging or {}
                        if site then
                            local key = W().side_key(site)
                            local okd, n = pcall(function() return W().side_dig(site, dry_run) end)
                            n = okd and tonumber(n) or 0
                            if not dry_run then
                                site.tick, site.dug, site.for_uid = t, t, tonumber(uid)
                                d.digs[key] = site
                            end
                            taken[key] = true
                            table.insert(out.digging, ('%s: a side cell at %d,%d,%d (%d tiles designated)'):format(
                                name_of(u, txt), site.x, site.y, site.z, n))
                        else
                            out.error = 'no jail, bedroom, office, tomb or were cell for a cell, and no rock beside a corridor near '
                                .. name_of(u, txt) .. ' to dig one in'
                            out.ok = #out.placed + #out.locked > 0
                        end
                    elseif opts.reserve then
                        if not dry_run then
                            d.cells[uid] = {zone = z.id, kind = kind, tick = t, doors = {}, reserved = true}
                        end
                        taken[z.id] = true
                        out.reserved = out.reserved or {}
                        table.insert(out.reserved, name_of(u, txt) .. ' (' .. tostring(kind) .. ')')
                        z = nil
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
                            local n = confine(u, c)
                            if n > 0 then out.unburrowed = (out.unburrowed or 0) + n end
                        else
                            out.error = 'the cell\'s burrow could not be made: ' .. tostring(eb)
                            out.ok = #out.placed + #out.locked > 0
                            z = nil
                        end
                    end
                    if z then table.insert(out.placed, name_of(u, txt)) end
                    -- (0.105.115 item18) the change close: the new cell's dwarf moved in at once
                    -- (locked by the next call, once they are seen inside and alone)
                    if z and c and opts.move_in and not in_zone(z, u.pos.x, u.pos.y, u.pos.z) then try_move(u, z) end
                elseif not c.locked then
                    -- (0.105.115 item18) outside their cell: out of every other burrow
                    -- (one given since), and moved in once they've waited CELL_MOVE_TICKS
                    -- or the brain says the change is close
                    if not in_zone(z, u.pos.x, u.pos.y, u.pos.z) then
                        if not dry_run then
                            local n = confine(u, c)
                            if n > 0 then out.unburrowed = (out.unburrowed or 0) + n end
                        end
                        if t - (tonumber(c.tick) or t) >= CELL_MOVE_TICKS or opts.move_in then try_move(u, z) end
                    end
                    if in_zone(z, u.pos.x, u.pos.y, u.pos.z) and other_in_zone(z, u.id) then
                        table.insert(out.waiting, name_of(u, txt))       -- (0.105.0 review) someone else inside
                    elseif in_zone(z, u.pos.x, u.pos.y, u.pos.z) and c.kind == 'were' then
                        -- (0.105.115 item24) alone inside a were cell: its bridge raised (a wall)
                        local okr, up, why = pcall(function()
                            local wc = W().find(c.zone)
                            if not wc then return false, 'the cell is gone' end
                            return W().set_raised(wc, true, dry_run)
                        end)
                        -- (R30b) raised, yet DF's walk map still joins the cell to the corridor:
                        -- not locked (said; the next call looks again)
                        local okj, open = false, nil
                        -- (R32 a) still rising (DF moves it over the next ticks): not a wall yet,
                        -- the walk map not yet cut; neither locked nor "not sealed" (the next call looks)
                        local rising = okr and up and why == 'raising'
                        if rising then
                            table.insert(out.waiting, name_of(u, txt))
                            out.raising = out.raising or {}
                            table.insert(out.raising, name_of(u, txt))
                        elseif okr and up and not dry_run then
                            okj, open = pcall(function()
                                local wc = W().find(c.zone)
                                return wc and W().joined(wc)
                            end)
                        end
                        if rising then
                            -- said above
                        elseif okr and up and okj and open == true then
                            table.insert(out.waiting, name_of(u, txt))
                            out.not_sealed = out.not_sealed or {}
                            table.insert(out.not_sealed, name_of(u, txt) .. ': the bridge is up, yet DF walks out of the cell')
                        elseif okr and up then
                            if not dry_run then c.locked = true end
                            table.insert(out.locked, name_of(u, txt))
                        else
                            table.insert(out.waiting, name_of(u, txt))
                            out.not_raised = out.not_raised or {}
                            table.insert(out.not_raised, name_of(u, txt) .. ': ' .. tostring(okr and why or up):sub(1, 100))
                        end
                    elseif in_zone(z, u.pos.x, u.pos.y, u.pos.z) and c.kind == 'were_open' then
                        -- (item31) inside a were cell whose lever isn't linked yet: held by the burrow
                        -- alone, the bridge raised once the lever is linked
                        table.insert(out.waiting, name_of(u, txt))
                        out.open_cell = out.open_cell or {}
                        table.insert(out.open_cell, name_of(u, txt))
                    elseif in_zone(z, u.pos.x, u.pos.y, u.pos.z) then
                        local insane = insane_held()
                        c.doors = type(c.doors) == 'table' and c.doors or {}
                        local mine = {}
                        for _, id in ipairs(c.doors) do mine[tostring(id)] = true end
                        for id, b in pairs(zone_doors(z)) do
                            local okf, f = pcall(function() return b.door_flags.forbidden end)
                            if okf and not f then
                                if not dry_run then
                                    U.lock_door(b, true, 'cell') -- (0.105.47) ai-util: the walk map redone
                                    if not mine[tostring(id)] then table.insert(c.doors, id) end
                                end
                            elseif okf and not dry_run and not mine[tostring(id)] then
                                -- (0.105.40b fix) locked by ai-insane already: the cell's now
                                -- (ai-insane drops it without opening it). (0.105.114) any door
                                -- locked already goes on the record too (held is checked by
                                -- it), but one not ai-insane's is left locked at the release
                                table.insert(c.doors, id)
                                if not insane[id] then
                                    c.pre = type(c.pre) == 'table' and c.pre or {}
                                    table.insert(c.pre, id)
                                end
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
    if not dry_run then
        save_state(d)
        hold_cell_doors(d)       -- (0.105.115 item18) the locked cells' doors: no other rule unlocks them
    end
    if #out.placed + #out.locked + #out.released + #out.waiting + #(out.unsquad or {}) + #(out.relock or {}) + (out.dead or 0) + #(out.moved or {})
            + #(out.reserved or {}) + #(out.digging or {}) + #(out.escaped or {}) + #(out.side or {}) + #(out.rekind or {}) == 0 and not out.error and not out.errors then   -- (item31)   -- (0.105.96, verifier) a squad left counts
        return {ok = false, rejected = true, nothing_to_do = true, error = 'every cell is as it should be'}
    end
    return out
end

-- (0.105.119) seal_cavern and the fire breathers: in ai-threats-seal.lua (loaded
-- next), which takes this part's insane_held back
PART_LOCALS.insane_held = insane_held
