-- ai-gates-wings: the War-hold's wing walls, gate_parts and summary(); citizens on ledges and
-- the vertical cut.
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-wings'] = '0.105.38'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, key, unkey, T, TK, moves_k, moves, treetop, inside_or_courtyard, seals, WALL_GROUND, open_ground, citizen_starts, place, entrance = U, key, unkey, T, TK, moves_k, moves, treetop, inside_or_courtyard, seals, WALL_GROUND, open_ground, citizen_starts, place, entrance   -- (13e) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- (0.105.30, construction spec 3.2) The War-hold's wing walls: once a
-- gatehouse stands, two straight arms of wall run from its front corners
-- (beside the drawbridge), across the corridor's line, WING_LEN tiles each,
-- a barbican's funnel on the surface. Seen from above, the corridor going
-- north (B the bridge, W the gatehouse walls, A the arms):
--     A A A A A W B W A A A A A
--               W T W
--               W H W
-- Each arm tile: ground a wall stands on (not open space, not a ramp top),
-- the open surface (open_ground: nothing built, no water, not a courtyard),
-- in no zone, with no farm plot, pasture or depot within WING_KEEP_OFF and
-- no water within WING_WATER. An arm stops at its first bad tile and is
-- dropped when shorter than WING_MIN. The arms must close no courtyard:
-- with them and the gatehouse's walls standing, every open tile beside an
-- arm, and the tile in front of the bridge, still reaches the map's edge;
-- an arm that would close one is dropped. The pieces go on the gate's record.
---------------------------------------------------------------------------
WING_LEN, WING_MIN = 5, 3
WING_KEEP_OFF, WING_WATER = 3, 2

-- (0.105.30, construction seams) The wing tiles placed, kept with the save
-- by the entrance's spot: {["x,y,z" of the way in] = {"x,y,z", ...}}. A scan
-- puts them back on the entrance (e.wing_pieces); ai-constructions counts
-- them as ai.wings (not as gate pieces), and the summary says wings = 'standing'.
WINGS_KEY = 'ai-overseer/wings'
WINGS_MAX = 40                 -- tiles kept a way in (two arms of WING_LEN, built again a few times)

function wing_records()
    local d = U.site_get(WINGS_KEY, {})
    return type(d) == 'table' and d or {}
end

local function spot_of(e) return ('%d,%d,%d'):format(e.x, e.y, e.z) end

-- The wing tiles recorded for this way in (nil: none).
function wing_pieces_of(e)
    local list = wing_records()[spot_of(e)]
    return (type(list) == 'table' and #list > 0) and list or nil
end

local function note_wings(e, pieces)
    if #pieces == 0 then return end
    local d = wing_records()
    local list, seen = {}, {}
    for _, k in ipairs(type(d[spot_of(e)]) == 'table' and d[spot_of(e)] or {}) do
        if not seen[k] then seen[k] = true; table.insert(list, k) end
    end
    for _, k in ipairs(pieces) do
        if not seen[k] and #list < WINGS_MAX then seen[k] = true; table.insert(list, k) end
    end
    d[spot_of(e)] = list
    U.site_put(WINGS_KEY, d)
    e.wing_pieces = list
end

-- Zones, farm plots and depots on level z: {{x1, y1, x2, y2, kind}} with kind
-- 'zone', 'pasture', 'farm' or 'depot' (tests replace this).
function wing_keepouts(z)
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b.z == z then
                local t = df.building_type[b:getType()]
                local kind
                if t == 'Civzone' then
                    kind = (df.civzone_type[b.type] == 'Pen') and 'pasture' or 'zone'
                elseif t == 'FarmPlot' then kind = 'farm'
                elseif t == 'TradeDepot' then kind = 'depot' end
                if kind then table.insert(out, {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, kind = kind}) end
            end
        end
    end)
    return out
end

-- An outside tile walks to the map's edge with `blocked` standing (no cache).
local function edge_without(k, blocked)
    local W, H = map_size()
    local seen, queue, head = {[k] = true}, {k}, 1
    while head <= #queue do
        local ck = queue[head]
        head = head + 1
        local x, y, z = unkey(ck)
        if x <= 0 or y <= 0 or x >= W - 1 or y >= H - 1 then return true end
        if #queue > COURTYARD_LIMIT then return true end
        moves(x, y, z, T(x, y, z), function(nx, ny, nz)
            local nk = key(nx, ny, nz)
            if seen[nk] or blocked[nk] then return end
            local nt = T(nx, ny, nz)
            if nt and nt.walk and nt.outside and not nt.hidden then
                seen[nk] = true
                table.insert(queue, nk)
            end
        end)
    end
    return false
end

-- The wings for an entrance whose gatehouse stands: {arms = {{keys}, ...},
-- walls = {keys}, dropped = {why...}, len, dir} or nil and why.
function plan_wings(e)
    if e.gatehouse ~= 'standing' then return nil, 'no gatehouse stands there' end
    local h = lid_hatch(e)
    local br = e.gatehouse_bridge
    if not h or type(br) ~= 'table' then return nil, 'the gatehouse\'s hatch or bridge could not be found' end
    local dx, dy = br.x - h.x, br.y - h.y
    if br.z ~= h.z or (dx ~= 0 and dy ~= 0) or (dx == 0 and dy == 0) then
        return nil, 'the gatehouse does not run straight from its hatch'
    end
    local d = {dx > 0 and 1 or (dx < 0 and -1 or 0), dy > 0 and 1 or (dy < 0 and -1 or 0)}
    local len = math.max(math.abs(dx), math.abs(dy)) - 1
    local z = h.z
    local px, py = math.abs(d[2]), math.abs(d[1])
    local function at(u, v) return h.x + d[1] * u + px * v, h.y + d[2] * u + py * v end
    -- the gatehouse's own walls, as they stand once built
    local house = {}
    local function wall(u, v) local x, y = at(u, v); house[key(x, y, z)] = true end
    wall(-1, 0)
    for u = -1, len + 1 do wall(u, -1); wall(u, 1) end
    local keepouts = wing_keepouts(z) or {}
    local function kept_off(x, y)
        for _, r in ipairs(keepouts) do
            local m = (r.kind == 'zone') and 0 or WING_KEEP_OFF
            if x >= r.x1 - m and x <= r.x2 + m and y >= r.y1 - m and y <= r.y2 + m then return r.kind end
        end
        return nil
    end
    local function wet(x, y)
        for ax = x - WING_WATER, x + WING_WATER do
            for ay = y - WING_WATER, y + WING_WATER do
                local t = T(ax, ay, z)
                if t and t.liquid then return true end
            end
        end
        return false
    end
    local arms, dropped, standing = {}, {}, 0
    for _, side in ipairs({-1, 1}) do
        local arm, stop = {}, nil
        for i = 1, WING_LEN do
            local x, y = at(len + 1, side * (1 + i))
            local t = T(x, y, z)
            if i == 1 and t and t.shape == 'WALL' and t.material == 'CONSTRUCTION' then standing = standing + 1 end
            local why
            if not t then why = 'off the map'
            elseif not WALL_GROUND[t.shape] or t.shape == 'EMPTY' or t.shape == 'RAMP_TOP' then
                why = tostring(t.shape):lower():gsub('_', ' ')
            elseif not open_ground(x, y, z) then why = 'not open ground'
            elseif wet(x, y) then why = 'water near'
            else
                local k = kept_off(x, y)
                if k then why = (k == 'zone') and 'a zone' or ('a ' .. k .. ' near') end
            end
            if why then stop = ('x%d y%d (%s)'):format(x, y, why) break end
            table.insert(arm, key(x, y, z))
        end
        if #arm >= WING_MIN then
            table.insert(arms, arm)
        else
            table.insert(dropped, ('the %s arm stops after %d tile%s at %s'):format(side < 0 and 'first' or 'second',
                #arm, #arm == 1 and '' or 's', tostring(stop)))
        end
    end
    if standing == 2 then return nil, 'the wings stand there already' end
    -- no courtyard: with the arms and the gatehouse standing, the tiles by
    -- each arm and in front of the bridge still reach the map's edge
    local fx, fy = at(len + 2, 0)
    local function closes(list)
        local blocked = {}
        for k in pairs(house) do blocked[k] = true end
        for _, arm in ipairs(list) do for _, k in ipairs(arm) do blocked[k] = true end end
        local check = {[key(fx, fy, z)] = true}
        for _, arm in ipairs(list) do
            for _, k in ipairs(arm) do
                local x, y = unkey(k)
                for ax = -1, 1 do
                    for ay = -1, 1 do
                        local nk = key(x + ax, y + ay, z)
                        local nt = T(x + ax, y + ay, z)
                        if not blocked[nk] and nt and nt.walk and nt.outside and not nt.hidden then check[nk] = true end
                    end
                end
            end
        end
        for k in pairs(check) do
            if not edge_without(k, blocked) then
                local x, y = unkey(k)
                return ('x%d y%d'):format(x, y)
            end
        end
        return nil
    end
    if #arms > 0 and closes(arms) then
        local kept = {}
        for _, arm in ipairs(arms) do
            local where = closes({arm})
            if where then
                table.insert(dropped, ('an arm would close a courtyard at %s'):format(where))
            else
                table.insert(kept, arm)
            end
        end
        if #kept == 2 and closes(kept) then kept = {kept[1]} end
        arms = kept
    end
    if #arms == 0 then
        return nil, 'no room for wing walls: ' .. (dropped[1] or 'no arm fits')
            .. (dropped[2] and ('; ' .. dropped[2]) or '')
    end
    local walls = {}
    for _, arm in ipairs(arms) do for _, k in ipairs(arm) do table.insert(walls, k) end end
    return {arms = arms, walls = walls, dropped = dropped, len = len, dir = d}
end

-- Build the wings (plan_wings): walls only, any material (buildingplan).
function build_wings(id, dry_run)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if e.gatehouse ~= 'standing' then return {ok = false, rejected = true, error = 'wings go on a gatehouse that stands'} end
    cache, edge_cache = {}, {}            -- the map may have changed since the scan
    local plan, why = plan_wings(e)
    if not plan then return {ok = false, rejected = true, error = why} end
    local arms = {}
    for _, arm in ipairs(plan.arms) do table.insert(arms, #arm) end
    local note = #plan.dropped > 0 and table.concat(plan.dropped, '; ') or nil
    if dry_run then
        return {ok = true, dry_run = true, walls = #plan.walls, arms = arms, blocks_needed = #plan.walls, note = note}
    end
    local out = {walls = 0, arms = arms, pieces = {}, blocks_needed = #plan.walls, note = note}
    local failed = {}
    for _, k in ipairs(plan.walls) do
        local x, y, z = unkey(k)
        local ok, w = place('Cw', {x = x, y = y, z = z})
        if ok then
            out.walls = out.walls + 1
            table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, 'Cw:' .. tostring(w))
        end
    end
    out.ok = out.walls > 0
    if #failed > 0 then out.failed = table.concat(failed, '; '):sub(1, 300) end
    if not out.ok then out.error = 'no wing wall could be placed (' .. (out.failed or '?') .. ')' end
    pcall(note_wings, e, out.pieces)      -- (0.105.30 seams) on the entrance's saved record
    return out
end

-- (0.104.105) Gate parts in stock: free, and held by a job (on their way to
-- one). A planned hatch or door is built only from one the fort has.
GATE_PARTS = {hatch_covers = 'HATCH_COVER', doors = 'DOOR'}
function gate_parts()
    local out = {}
    for name, tname in pairs(GATE_PARTS) do
        local free, held = 0, 0
        pcall(function()
            for _, item in ipairs(df.global.world.items.other[tname]) do
                local f = item.flags
                -- (0.104.139) nor an artifact, an owned or carried one, or one
                -- to melt: buildingplan won't take them (Teacheroar: an heirloom
                -- hatch cover counted free, the hatch at x109 y38 waited 90 days)
                if not (f.forbid or f.in_building or f.construction or f.removed or f.garbage_collect
                        or f.trader or f.dump or f.hostile or f.artifact or f.owned or f.in_inventory
                        or f.melt or f.on_fire) then
                    if f.in_job then held = held + 1 else free = free + 1 end
                end
            end
        end)
        out[name], out[name .. '_held'] = free, held
    end
    return out
end

local DAY_TICKS = 1200
function closing_days(e)
    local since = e.closing and GATES.closing_since and GATES.closing_since[key(e.x, e.y, e.z)]
    if not since or not GATES.scanned_tick then return nil end
    return math.floor((GATES.scanned_tick - since) / DAY_TICKS)
end

function summary()
    local list = {}
    for _, e in ipairs(GATES.entrances or {}) do
        local eq, e_lock_only = {}, nil
        for _, b in ipairs(e.equipment) do
            local ids = {}
            for _, l in ipairs(b.levers or {}) do table.insert(ids, l.id) end
            local shut
            if b.lever_driven then                     -- (0.105.23) live: a link may have shut it
                local okb, bb = pcall(df.building.find, b.id)
                if okb and bb then shut = door_shut(bb) end
            end
            -- (0.105.33) on a lever that also works another gate: the watcher
            -- has no lever of this entrance's own to pull and only locks it
            local lock_only = (b.kind ~= 'bridge' and b.lever_driven and not b.drive_lever) or nil
            if lock_only then e_lock_only = true end
            table.insert(eq, {id = b.id, kind = b.kind, lever_id = b.lever_id, levers = ids,
                              lever_away = b.lever_away == true,
                              lever_driven = b.lever_driven or nil, drive_lever = b.drive_lever,
                              lock_only = lock_only, shut = shut})
        end
        local outer = {}
        for _, b in ipairs(e.outer or {}) do
            table.insert(outer, {id = b.id, kind = b.kind, lever_id = b.lever_id})
        end
        table.insert(list, {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z, width = e.width,
                            sealed = e.sealed, closing = e.closing == true, equipment = eq,
                            bridges_unworked = e.bridges_unworked or {},
                            door_spots = #e.door_spots,
                            cut = e.cut,                    -- (0.105.0) closed by hatches on its stairs down
                            cut_hatches = e.cut_hatches, cut_why = e.cut_why,
                            waiting = e.waiting,
                            closing_days = closing_days(e),
                            -- (0.105.33) days its drawbridge waited for an unlinked lever, given up
                            lever_wait_days = e.lever_wait_over,
                            -- (0.105.33) a door or hatch on a shared lever: only locked when "closed"
                            lock_only = e_lock_only,
                            closed = GATES.closed and GATES.closed[e.id] or false,
                            -- (0.105.23) the founding stair's lid, a gatehouse in front of it
                            lid = e.lid, gatehouse = e.gatehouse, gatehouse_why = e.gatehouse_why,
                            wings = e.wing_pieces and 'standing' or nil,   -- (0.105.30 seams) recorded wing walls
                            deep_road = e.deep_road,        -- (0.105.30) the depot's wagon road: a drawbridge only
                            split = e.split,                -- (0.105.32) open gates DF's walk map treats as shut
                            outer = #outer > 0 and outer or nil})
    end
    local okf, fl = pcall(free_levers)
    -- (0.105.3) enemies inside the fort (nil without a map: the brain acts as before)
    local oki, intr = pcall(intruders_inside)
    return {intruders_inside = oki and intr or nil,
            scanned = GATES.scanned == true, scanned_tick = GATES.scanned_tick, inside_tiles = GATES.inside_tiles,
            -- (0.100, review) the map of the inside hit its size limit: entrances
            -- past it weren't seen (not gone), and walls aren't planned on it
            capped = (GATES.inside_tiles or 0) >= MAX_TILES or nil,
            free_levers = okf and fl or {}, free_mechanisms = GATES.scanned and free_mechanism_count(200) or nil,
            entrances = list, armed = GATES.armed == true, watch_error = GATES.watch_error,
            -- (0.105.23) a lever linked since the scan: map the entrances again
            rescan = GATES.rescan or nil, lever_opened = GATES.lever_opened,
            parts = GATES.scanned and gate_parts() or nil,
            citizens_outside = GATES.scanned and citizens_outside() or nil,
            -- (0.105.4 review) visitors outside the fort (a tavern's inside don't count)
            visitors_outside = GATES.scanned and (function()
                local okv, n = pcall(visitors_outside); return okv and n or nil end)() or nil}
end

---------------------------------------------------------------------------
-- (0.105.0) Citizens on ledges, and the vertical cut.
--
-- Ledges: the map of the inside starts from where the citizens stand. One
-- on a tree's branches, a cliff ledge or a small roofed pocket outside the
-- fort seeded a little "inside" of its own, and every edge of it became an
-- entrance (Teacheroar: "the way in at x30 y187 is a branch", refused six
-- times). fort_starts keeps the citizens who stand in the fort: a start on a
-- treetop never counts; one in a small pocket (under LEDGE_MAX tiles) only
-- when no citizen stands anywhere bigger and that pocket holds the most.
--
-- The cut: an opening wider than the AI walls (50 tiles: titans walked into
-- Teacheroar through one) or one refused for what stands in it. The open
-- area behind it (the "porch": everything reachable from the opening without
-- going below its level) leads down into the fort somewhere: each stair
-- going down from it gets a hatch, which the gate watcher locks like any
-- other gate. Checked first: the hatches must seal the opening off from the
-- dwarves, the porch must not be where the dwarves live, and a ramp down
-- (no hatch fits one) is refused with where it is.
---------------------------------------------------------------------------

LEDGE_MAX = 120          -- tiles: a pocket this small with a citizen in it is a ledge, not the fort
CUT_MAX_PORCH = 6000     -- tiles: an open area bigger than this is the fort itself, not a porch
CUT_MAX_HATCHES = 12
-- (0.105.0 review) the brain's fortify_max_width: a narrower opening is
-- walled, and the scan looks for a cut there only where the AI cut one
FORTIFY_MAX_WIDTH = 50
CUT_SPOTS_KEY = 'ai-overseer/cuts'

-- the entrances the AI cut (key(x, y, z) -> true), kept with the save
function cut_spots()
    if CUT_SPOTS == nil then
        CUT_SPOTS = {}
        for k, v in pairs(U.site_get(CUT_SPOTS_KEY, {})) do if v then CUT_SPOTS[tonumber(k) or k] = true end end
    end
    return CUT_SPOTS
end

-- (each tile of the opening: a rescan may anchor the entrance on another of them)
function was_cut(e)
    local spots = cut_spots()
    for _, k in ipairs(e.inside_list or {}) do if spots[k] then return true end end
    return spots[key(e.x, e.y, e.z)] == true
end

local function note_cut_spot(e)
    local spots = cut_spots()
    spots[key(e.x, e.y, e.z)] = true
    for _, k in ipairs(e.inside_list or {}) do spots[k] = true end
    local out = {}
    for k in pairs(spots) do out[tostring(k)] = true end
    U.site_put(CUT_SPOTS_KEY, out)
end

-- (0.105.30 fixes) The AI's own keep and surface hall ("x,y,z" -> true:
-- their boxes, the level above for the roof): a citizen standing there
-- seeds no "fort" of its own. A finished keep with its stair to the roof is
-- its court and its roof together, over LEDGE_MAX at any radius (r = 4:
-- 49 + 81 tiles), so a dwarf in a keep built away from the way in would
-- make its door a fort entrance at one scan and gone at the next. A keep
-- round the way in is still the fort's: reached from the fort's own starts
-- up the founding stair. Tests replace this.
function ai_surface_box_keys()
    local out = {}
    pcall(function()
        local B = reqscript('ai-builder')
        local function box(x1, y1, x2, y2, z)
            for zz = z, z + 1 do
                for x = x1, x2 do
                    for y = y1, y2 do out[key(x, y, zz)] = true end
                end
            end
        end
        local k = B.keep_data and B.keep_data()
        if type(k) == 'table' and k.x and k.y and k.z and k.r then box(k.x - k.r, k.y - k.r, k.x + k.r, k.y + k.r, k.z) end
        local d = B.halls_data and B.halls_data()
        for _, h in ipairs(type(d) == 'table' and type(d.list) == 'table' and d.list or {}) do
            if h.x1 and h.y1 and h.x2 and h.y2 and h.z then box(h.x1, h.y1, h.x2, h.y2, h.z) end
        end
    end)
    pcall(deep_hall_keys, out)              -- (0.105.31)
    return out
end

-- (0.105.31) The deep depot's hall and wagon road (their own level only:
-- the level above an underground hall is rock or the fort's own rooms),
-- added to `out`. A dwarf standing in the hall (a trader's helper, a hauler
-- at the depot) seeded a "fort" there at the gates' scan, and the road out
-- of it looked like a way in.
function deep_hall_keys(out)
    local B = reqscript('ai-builder')
    local d = B.deep_depot_data and B.deep_depot_data()
    if type(d) ~= 'table' or d.stage == 'no_road' then return out end
    local h = d.hall
    if type(h) == 'table' and h.x1 and h.y1 and h.x2 and h.y2 and h.z then
        for x = h.x1, h.x2 do
            for y = h.y1, h.y2 do out[key(x, y, h.z)] = true end
        end
    end
    for _, t in ipairs(type(d.tiles) == 'table' and d.tiles or {}) do
        if t.x and t.y and t.z then out[key(t.x, t.y, t.z)] = true end
    end
    return out
end

-- (0.105.31 reserve fixes) Where the fort's own inside is when no citizen
-- stands in it: the founding stair under its lid, else a meeting hall (as
-- fort_interior). Points {x, y, z}; tests replace this.
function fort_anchor_starts()
    local out = {}
    pcall(function()
        for _, e in ipairs(GATES.entrances or {}) do
            if e.lid then
                local okh, h = pcall(lid_hatch, e)
                if okh and h then table.insert(out, {x = h.x, y = h.y, z = h.z - 1}) end
            end
        end
    end)
    pcall(function()
        for _, zn in ipairs(df.global.world.buildings.other.ZONE_MEETING_HALL) do
            local okp, x, y, z = pcall(function() return zn.centerx, zn.centery, zn.z end)
            if okp and x then table.insert(out, {x = x, y = y, z = z}) end
        end
    end)
    return out
end

-- the starts that stand somewhere big (keep_big), and the small pockets'
-- (grouped, in order); `big` is shared between calls of one fort_starts
local function sort_starts(starts, big)
    local groups, order = {}, {}
    local keep_big, seen_tile = {}, {}
    for _, p in ipairs(starts or {}) do
        local k = key(p.x, p.y, p.z)
        local t = T(p.x, p.y, p.z)
        if t and not seen_tile[k] and not treetop(t) and inside_or_courtyard(t, k) then
            seen_tile[k] = true
            if big[k] then
                table.insert(keep_big, p)
            else
                -- a flood from it, stopped at LEDGE_MAX tiles
                local seen, queue, head = {[k] = true}, {k}, 1
                local small = true
                while head <= #queue do
                    if #queue > LEDGE_MAX then small = false break end
                    local ck = queue[head]
                    head = head + 1
                    local x, y, z = unkey(ck)
                    moves(x, y, z, T(x, y, z), function(nx, ny, nz)
                        local nk = key(nx, ny, nz)
                        if seen[nk] then return end
                        local nt = T(nx, ny, nz)
                        if nt and nt.walk and not nt.hidden and not nt.special and not treetop(nt)
                                and inside_or_courtyard(nt, nk) then
                            seen[nk] = true
                            table.insert(queue, nk)
                        end
                    end)
                end
                if small then
                    local id = math.huge
                    for sk in pairs(seen) do if sk < id then id = sk end end
                    if not groups[id] then groups[id] = {}; table.insert(order, id) end
                    table.insert(groups[id], p)
                else
                    for sk in pairs(seen) do big[sk] = true end
                    table.insert(keep_big, p)
                end
            end
        end
    end
    -- no citizen in a big place (a new fort's first room): the pocket(s) with the most
    local most = 0
    for _, id in ipairs(order) do most = math.max(most, #groups[id]) end
    local pockets = {}
    for _, id in ipairs(order) do
        if #groups[id] == most then for _, p in ipairs(groups[id]) do table.insert(pockets, p) end end
    end
    return keep_big, pockets
end

function fort_starts(starts)
    -- (read fresh: it runs before a scan or a cut; (13e) in a scan, the scan
    -- has just read it fresh: SCAN_MEMO in ai-gates-scan)
    if not SCAN_MEMO then cache, edge_cache = {}, {} end
    local big = {}
    -- (0.105.30 fixes) not from the AI's keep or hall, (0.105.31) or its deep depot hall,
    -- while anyone stands elsewhere
    local all, left_out = starts, false
    local okb, boxes = pcall(ai_surface_box_keys)
    if okb and type(boxes) == 'table' and next(boxes) then
        local rest = {}
        for _, p in ipairs(starts or {}) do
            if not boxes[key(p.x, p.y, p.z)] then table.insert(rest, p) end
        end
        left_out = #rest < #(starts or {})
        starts = rest
    end
    local keep_big, pockets = sort_starts(starts, big)
    if #keep_big > 0 then return keep_big end
    -- (0.105.31 reserve fixes) leaving the keep, hall or depot hall out left
    -- no start in the fort itself (only a pocket, or none: F's case, the one
    -- citizen of the main area in the depot hall): the founding stair or the
    -- meeting hall is the start instead, else the starts left out after all
-- (when they stand somewhere big)
    if left_out then
        local oka, anchors = pcall(fort_anchor_starts)
        if oka and type(anchors) == 'table' then
            local anchor_big = sort_starts(anchors, big)
            if #anchor_big > 0 then return anchor_big end
        end
        -- (a road taken for a way in is better than the fort's real ways in missed)
        local all_big, all_pockets = sort_starts(all, big)
        if #all_big > 0 then return all_big end
        if #pockets == 0 then return all_pockets end
    end
    return pockets
end

-- The porch and its ways down: {n = tiles, stairs = {key...}, ramps = {key...},
-- home = true when a dwarf stands on it, capped = true when too big}.
function porch_of(e, starts)
    cache = cache or {}
    edge_cache = edge_cache or {}
    -- (13e) in a scan, each entrance's porch is walked once (the result is
    -- only read; the map can't change while the scan runs)
    local memo = SCAN_MEMO and SCAN_MEMO.porch
    local m = memo and memo[e]
    if m and m.starts == starts then return m.out end
    local out = porch_walk(e, starts)
    if memo then memo[e] = {starts = starts, out = out} end
    return out
end

function porch_walk(e, starts)
    local home = {}
    for _, p in ipairs(starts or {}) do home[key(p.x, p.y, p.z)] = true end
    local z0 = e.z
    local seen, queue, head = {}, {}, 1
    for _, k in ipairs(e.inside_list) do
        local _, _, kz = unkey(k)
        z0 = math.min(z0, kz)                    -- (the opening may span two levels)
        if not seen[k] then seen[k] = true; table.insert(queue, k) end
    end
    local out = {n = 0, stairs = {}, ramps = {}}
    local stair_seen, ramp_seen = {}, {}
    local tail = #queue
    local outs = e.outs
    local k, x, y         -- (13e) the tile walked from
    local function visit(nk, nx, ny, nz)
        if seen[nk] or outs[nk] then return end
        local nt = TK(nk, nx, ny, nz)
        if not nt or not nt.walk or nt.hidden or nt.special or treetop(nt) or not inside_or_courtyard(nt, nk) then
            return
        end
        if nz < z0 then
            -- a way down below the opening's level: a stair (hatch on the
            -- stair it leaves from) or a ramp
            if nx == x and ny == y then
                if not stair_seen[k] then stair_seen[k] = true; table.insert(out.stairs, k) end
            elseif not ramp_seen[nk] then
                ramp_seen[nk] = true
                table.insert(out.ramps, nk)
            end
            return
        end
        seen[nk] = true
        tail = tail + 1
        queue[tail] = nk
    end
    while head <= tail do
        if tail > CUT_MAX_PORCH then out.capped = true break end
        k = queue[head]
        head = head + 1
        if home[k] then out.home = true end
        local z
        x, y, z = unkey(k)
        local t = TK(k, x, y, z)
        moves_k(k, x, y, z, t, visit)
    end
    out.n = tail
    out.tiles = seen             -- (0.105.0 review) the porch's tiles (citizens there are outside)
    table.sort(out.stairs)
    table.sort(out.ramps)
    return out
end

-- Does blocking these keys keep the outside from the dwarves, however big
-- the porch? (seals() with the pocket the porch's size)
local function cut_seals(starts, e, blocked, porch_n)
    local was = POCKET
    POCKET = math.max(POCKET, porch_n + 50)
    local ok, sealed = pcall(seals, starts, {outs = e.outs}, blocked)
    POCKET = was
    return ok and sealed
end

-- The cut for one entrance: {hatches = {key...}, porch = n} or nil, why.
-- (0.105.33) fort_ready: the starts are fort_starts already (the scan's survey)
function plan_cut(e, starts, fort_ready)
    cache = cache or {}
    edge_cache = edge_cache or {}
    if not fort_ready then starts = fort_starts(starts) end
    local p = porch_of(e, starts)
    if p.capped then
        return nil, ('the open area behind it runs on for more than %d tiles (it is the fort, not a porch)'):format(CUT_MAX_PORCH)
    end
    if p.home then return nil, 'dwarves live in the open area behind it: no cut that leaves them outside' end
    if #p.ramps > 0 then
        local x, y, z = unkey(p.ramps[1])
        return nil, ('a ramp leads down from the open area at x%d y%d (no hatch fits a ramp): wall it'):format(x, y)
    end
    if #p.stairs == 0 then return nil, 'nothing leads down from the open area behind it' end
    if #p.stairs > CUT_MAX_HATCHES then
        return nil, ('%d stairs lead down from the open area: too many to close with hatches'):format(#p.stairs)
    end
    for _, k in ipairs(p.stairs) do
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if not t or t.liquid then return nil, ('water on the stair at x%d y%d'):format(x, y) end
    end
    local blocked = {}
    for _, k in ipairs(p.stairs) do blocked[k] = true end
    if not cut_seals(starts, e, blocked, p.n) then
        return nil, 'hatches on its stairs would not seal it (another way leads in)'
    end
    return {hatches = p.stairs, porch = p.n}
end

-- In the scan: hatches (built or planned) on the porch's stairs close an
-- entrance the doors and walls can't. Fills e.equipment / e.sealed /
-- e.closing / e.waiting / e.cut; never changes an entrance it can't close.
function cut_equipment(e, buildings, starts, inside)
    if e.sealed or e.closing or e.kind ~= 'surface' or #e.door_spots > 0 then return end
    local hatch_at, pending_at, any = {}, {}, false
    for _, b in ipairs(buildings) do
        if b.x1 == b.x2 and b.y1 == b.y2 then
            if b.kind == 'hatch' then hatch_at[key(b.x1, b.y1, b.z)] = b; any = true
            elseif b.kind == 'pending' and b.what == 'hatch' then pending_at[key(b.x1, b.y1, b.z)] = b; any = true end
        end
    end
    if not any then return end
    local p = porch_of(e, starts)
    if p.capped or p.home or #p.ramps > 0 or #p.stairs == 0 then return end
    local built, waiting = {}, 0
    for _, k in ipairs(p.stairs) do
        if hatch_at[k] then table.insert(built, hatch_at[k])
        elseif pending_at[k] then waiting = waiting + 1
        else return end                          -- a stair with nothing: not the cut
    end
    if waiting > 0 then
        e.closing, e.cut = true, true
        e.waiting = e.waiting or {}
        e.waiting.hatch = math.max(e.waiting.hatch or 0, waiting)   -- (the scan may have counted them near)
        return
    end
    local blocked = {}
    for _, b in ipairs(built) do blocked[key(b.x1, b.y1, b.z)] = true end
    if cut_seals(starts, e, blocked, p.n) then
        for _, b in ipairs(built) do table.insert(e.equipment, b) end
        table.sort(e.equipment, function(a, b) return a.id < b.id end)
        e.sealed, e.cut = true, true
        -- (0.105.0 review) for the watcher: the porch (outside) and the hatches
        e.porch = p.tiles
        e.hatch_keys = {}
        for k in pairs(blocked) do table.insert(e.hatch_keys, k) end
    end
end

-- For the scan: which open surface entrances a cut would close
-- (e.cut_hatches) or why not (e.cut_why); the widest first, CUT_SURVEY_MAX
-- of them (each is a walk of its open area).
CUT_SURVEY_MAX = 6
function cut_survey(entrances, starts)
    local list = {}
    for _, e in ipairs(entrances) do
        if not e.sealed and not e.closing and e.kind == 'surface' and #e.door_spots == 0 then
            table.insert(list, e)
        end
    end
    table.sort(list, function(a, b) return a.width > b.width end)
    for i = 1, math.min(#list, CUT_SURVEY_MAX) do
        local e = list[i]
        local ok, plan, why = pcall(plan_cut, e, starts, true)     -- (0.105.33) the scan's fort starts
        if ok and plan then e.cut_hatches = #plan.hatches
        else e.cut_why = ok and why or ('error: ' .. tostring(plan):sub(1, 100)) end
    end
end

-- The action: hatches on the porch's stairs (buildingplan waits for hatch
-- covers; the masons are asked by the gate parts rule).
function cut_entrance(id, starts, dry_run)
    local e
    for _, x in ipairs(GATES.entrances or {}) do if x.id == id then e = x end end
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    cache, edge_cache = {}, {}
    local plan, why = plan_cut(e, starts or citizen_starts())
    if not plan then return {ok = false, error = why} end
    if dry_run then                    -- (0.105.0 review) the plan, nothing placed
        local spots = {}
        for _, k in ipairs(plan.hatches) do
            local x, y, z = unkey(k)
            table.insert(spots, ('%d,%d,%d'):format(x, y, z))
        end
        return {ok = true, dry_run = true, style = 'cut', hatches = #plan.hatches, pieces = spots, porch = plan.porch}
    end
    local placed, failed, pieces = 0, {}, {}
    for _, k in ipairs(plan.hatches) do
        local x, y, z = unkey(k)
        local ok, reason = place('H', {x = x, y = y, z = z})
        if ok then
            placed = placed + 1
            table.insert(pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, ('x%d y%d: %s'):format(x, y, tostring(reason)))
        end
    end
    if placed == 0 then
        return {ok = false, error = 'no hatch could be placed (' .. table.concat(failed, '; '):sub(1, 200) .. ')'}
    end
    note_cut_spot(e)                   -- (0.105.0 review) the scan looks for its hatches from now on
    return {ok = true, style = 'cut', hatches = placed, pieces = pieces, porch = plan.porch,
            failed = #failed > 0 and table.concat(failed, '; '):sub(1, 300) or nil}
end

-- A new fort: forget the old one's gates.
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-gates'] = function(sc)
        if sc == SC_MAP_UNLOADED then GATES = {scanned = false}; CUT_SPOTS = nil end   -- (0.105.0 review CUT_SPOTS)
    end
end

-- (13e) this file's locals the later parts use, as module names (each takes
-- them back as locals of its own)
_ENV.DAY_TICKS = DAY_TICKS
