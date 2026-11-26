-- ai-werecells: the werebeast cells behind drawbridges (0.105.115 item24).
--
-- A werebeast changed at the full moon is a building destroyer (level 2,
-- the DF wiki): it breaks doors, hatches and furniture, so a cell held by
-- a locked door holds it only until it reaches the door. Walls hold, and a
-- raised drawbridge is a wall no building destroyer can break. The
-- were_cells level (ai-layouts-kinds were_cells) digs 2x2 cells off a
-- corridor, each with a 1-tile drawbridge on its doorway, a lever on the
-- corridor tile in front of it and a bed; its saved cells (cells.were) name
-- each cell's box, bridge and lever (wereN(2x2), werebridgeN, wereleverN).
--
--   cells(data)          every cell of those levels: {key, project, i, x1..y2, z, bridge, lever}
--   cell_state(c)        its bridge and lever now: built, linked, raised, moving, link_job
--   ready(c)             a cell moon_cell may use: built, linked, lowered, still, and
--                        (R29 W8) sealed: no way out but its bridge (sealed(c));
--                        cell_state's joined: raised, yet DF's walk map joins it to the lever
--   find(key) / zone_of(c)  a cell by its key; the cell as a box for moon_cell's zone code
--   set_raised(c, up, dry_run)  the lever pulled (ai-gates pull_instant: DFHack's
--                        `lever pull --instant`, no dwarf) until the bridge stands as
--                        asked; never while anyone is on the bridge tile (raising
--                        flings them, lowering destroys what lies under it)
--   link(dry_run)        the action were_cells: each built lever not yet linked is
--                        linked to its bridge (ai-gates link_lever: a mechanic's job)
--   report(held)         the threats section's were.were_cells
--   piece_ids()          the bridges and levers, for ai-threats' claimed_doors
--
-- Tests replace building_at, occupied, pull, lever_links and projects.
--@ module = true

LEVER_NAME = 'AI were cell lever'
BRIDGE_NAME = 'AI were cell'
REPORT_ROWS = 12

-- (0.105.48 r2) constructBuilding is in library/lua/dfhack/buildings.lua, added to
-- dfhack.buildings only by this require (without it, only after buildingplan loaded it)
pcall(function() require('dfhack.buildings') end)

local function gates() return reqscript('ai-gates') end

-- the AI's levels (read only)
function projects()
    return reqscript('ai-builder').projects_read_only()
end

local function parse(text)
    local i, w, h = text:match('^were(%d+)%((%d+)x(%d+)%)$')
    if i then return 'room', tonumber(i), tonumber(w), tonumber(h) end
    i = text:match('^werebridge(%d+)$')
    if i then return 'bridge', tonumber(i) end
    i = text:match('^werelever(%d+)$')
    if i then return 'lever', tonumber(i) end
    return nil
end

function cells(data)
    local out = {}
    pcall(function()
        data = data or projects()
        for _, p in ipairs(type(data) == 'table' and type(data.list) == 'table' and data.list or {}) do
            local a = type(p) == 'table' and (p.anchor or p.stair) or nil
            if a and p.kind == 'were_cells' and p.phase ~= 'cancelled' and type(p.cells) == 'table'
                    and type(p.cells.were) == 'table' then
                local ax, ay, z = tonumber(a.x), tonumber(a.y), tonumber(p.z)
                local by = {}
                for _, c in ipairs(ax and ay and z and p.cells.were or {}) do
                    local what, i, w, h = parse(tostring(c.text))
                    if what and tonumber(c.x) and tonumber(c.y) then
                        local r = by[i] or {project = p.id, i = i, z = z, phase = p.phase}
                        by[i] = r
                        local x, y = ax + c.x, ay + c.y
                        if what == 'room' then
                            r.x1, r.y1, r.x2, r.y2 = x, y, x + w - 1, y + h - 1
                        else
                            r[what] = {x = x, y = y, z = z}
                        end
                    end
                end
                for i, r in pairs(by) do
                    if r.x1 and r.bridge and r.lever then
                        r.key = ('were:%s:%d'):format(tostring(p.id), i)
                        table.insert(out, r)
                    end
                end
            end
        end
    end)
    table.sort(out, function(a, b) return a.key < b.key end)
    return out
end

function find(key, list)
    for _, c in ipairs(list or cells()) do
        if c.key == key then return c end
    end
    return nil
end

-- the cell as a box moon_cell's zone code reads (in_zone, burrow tiles, cell_spot)
function zone_of(c)
    return {id = c.key, x1 = c.x1, y1 = c.y1, x2 = c.x2, y2 = c.y2, z = c.z, were = true}
end

-- the bridge or lever standing on a tile, or nil
function building_at(pos, kind)
    local out
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(pos.x, pos.y, pos.z))
        if not b then return end
        local t = b:getType()
        if kind == 'bridge' and t == df.building_type.Bridge then out = b end
        if kind == 'lever' and t == df.building_type.Trap and b.trap_type == df.trap_type.Lever then out = b end
    end)
    return out
end

local function built(b)
    local ok, yes = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    return ok and yes or false
end

function lever_links()
    local ok, l = pcall(function() return gates().lever_links() end)
    return ok and type(l) == 'table' and l or {}
end

function cell_state(c, links)
    local st = {key = c.key, built = false, linked = false, raised = false, moving = false}
    local br, lv = building_at(c.bridge, 'bridge'), building_at(c.lever, 'lever')
    st.bridge_id, st.lever_id = br and br.id or nil, lv and lv.id or nil
    st.built = (br and lv and built(br) and built(lv)) and true or false
    if br then
        pcall(function()
            local f = br.gate_flags
            st.raised = ((f.raised and not f.lowering) or f.raising) and true or false
            st.moving = (f.raising or f.lowering) and true or false
        end)
    end
    if st.raised and not st.moving then
        local okj, j = pcall(joined, c)
        if okj and j then st.joined = true end      -- (R29 W8) raised, yet DF walks out
    end
    if br and lv then
        for _, l in ipairs((links or lever_links())[br.id] or {}) do
            if l == lv.id then st.linked = true end
        end
        pcall(function()
            for _, j in ipairs(lv.jobs) do
                if j.job_type == df.job_type.LinkBuildingToTrigger then st.link_job = true end
            end
        end)
    end
    return st
end

-- (R29 W8) F, 25 Nov 17:21-17:27: Besmar locked behind a raised bridge,
-- found turned nine levels down. Is the cell shut on every side but its
-- bridge? Every tile round its box on its level (diagonals too: DF walks
-- diagonally) a wall; its own tiles floor (no stair, ramp or hole); above
-- each of them and above the bridge a roof (no open space, ramp top or
-- down stair: a climber or a stair goes up). (A weremole digs nothing: no
-- creature of DF tunnels; a changed were breaks buildings, not walls, and
-- a raised bridge is a wall it cannot break.) true, false and why, or nil
-- when the tiles can't be read. Tests replace shape_at.
local OPEN_ABOVE = {EMPTY = true, RAMP_TOP = true, STAIR_DOWN = true, STAIR_UPDOWN = true}
function sealed(c)
    if type(c) ~= 'table' or not (c.x1 and c.y1 and c.x2 and c.y2 and c.z) then return nil end
    local z = c.z
    local br = c.bridge or {}
    local function inside(x, y) return x >= c.x1 and x <= c.x2 and y >= c.y1 and y <= c.y2 end
    for y = c.y1 - 1, c.y2 + 1 do
        for x = c.x1 - 1, c.x2 + 1 do
            local s = shape_at(x, y, z)
            if s == nil then return nil end
            if inside(x, y) then
                if s ~= 'FLOOR' then return false, ('the cell\'s own tile %d,%d,%d is %s, not floor'):format(x, y, z, s) end
                local up = shape_at(x, y, z + 1)
                if up == nil then return nil end
                if OPEN_ABOVE[up] then return false, ('open above the cell at %d,%d,%d (%s)'):format(x, y, z + 1, up) end
            elseif not (x == br.x and y == br.y) and s ~= 'WALL' then
                return false, ('the cell\'s side %d,%d,%d is %s, not wall'):format(x, y, z, s)
            end
        end
    end
    if br.x and br.y then
        local up = shape_at(br.x, br.y, z + 1)
        if up and OPEN_ABOVE[up] then return false, ('open above the bridge at %d,%d,%d (%s)'):format(br.x, br.y, z + 1, up) end
    end
    return true
end

-- (R29 W8) raised and still: does DF still walk from inside the cell to the
-- lever's tile in front of it? true (joined: the raise holds nothing), false,
-- nil (can't tell). Tests replace walk_group.
function walk_group(x, y, z)
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) end)
    g = ok and tonumber(g) or 0
    return g ~= 0 and g or nil
end
function joined(c)
    local out
    for y = c.y1, c.y2 do
        for x = c.x1, c.x2 do
            local g = walk_group(x, y, c.z)
            if g and out == nil then
                local gl = c.lever and walk_group(c.lever.x, c.lever.y, c.lever.z)
                if gl then out = (g == gl) end
            end
        end
    end
    return out
end

function ready(c, links)
    local st = cell_state(c, links)
    -- (R29 W8) a cell with a way out besides its bridge is never ready (can't tell: as before)
    local okq, shut, why = pcall(sealed, c)
    if okq and shut == false then st.open = why end
    return st.built and st.linked and not st.raised and not st.moving and not st.open and true or false, st
end

-- anyone (any living unit) on the tile; can't tell: yes
function occupied(pos)
    local ok, yes = pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if u.pos.x == pos.x and u.pos.y == pos.y and u.pos.z == pos.z and not dfhack.units.isDead(u) then
                return true
            end
        end
        return false
    end)
    return not ok or yes
end

function pull(lever_id)
    local ok, done = pcall(function() return gates().pull_instant(lever_id) end)
    return ok and done or false
end

-- The bridge raised (up) or lowered: true, or false and why. An instant
-- pull sets the bridge to the lever's new state, so a lever out of step
-- with its bridge needs a second pull (checked, and the tile looked at again).
function set_raised(c, up, dry_run)
    up = up and true or false
    local st = cell_state(c)
    if not st.bridge_id then return false, 'no drawbridge on the cell\'s doorway' end
    if not st.lever_id then return false, 'no lever in front of the cell' end
    if not st.built then return false, 'the cell\'s bridge or lever is not built yet' end
    if not st.linked then return false, 'the cell\'s lever is not linked to its bridge yet' end
    if st.raised == up then return true, 'already' end
    if st.moving then return false, 'the bridge is moving' end
    for try = 1, 2 do
        if occupied(c.bridge) then
            return false, 'someone is on the cell\'s bridge tile ('
                .. (up and 'raising would fling them' or 'lowering would crush them') .. ')'
        end
        if dry_run then return true, 'dry run' end
        if not pull(st.lever_id) then return false, 'the lever pull was refused' end
        if cell_state(c).raised == up then return true, (up and 'raised' or 'lowered') end
    end
    return false, 'the bridge did not move after two pulls'
end

-- The action: each built lever linked to its own bridge (one link job each,
-- at most `max`), named so the player sees what it works.
function link(dry_run, max)
    max = math.tointeger(max) or 8
    local out = {ok = true, linked = {}, waiting = {}, dry_run = dry_run or nil}
    local links = lever_links()
    local G = gates()
    for _, c in ipairs(cells()) do
        local st = cell_state(c, links)
        if st.built and not st.linked and not st.link_job and #out.linked < max then
            local ok, r = pcall(G.link_lever, st.lever_id, st.bridge_id, dry_run == true)
            if ok and type(r) == 'table' and r.ok then
                table.insert(out.linked, c.key)
                if not dry_run then
                    pcall(G.name_at, c.lever, LEVER_NAME)
                    pcall(G.name_at, c.bridge, BRIDGE_NAME)
                end
            else
                -- (0.105.119 item30) how many free mechanisms the link found, and the held ones apart
                if ok and type(r) == 'table' and r.free_mechanisms then
                    out.free_mechanisms = r.free_mechanisms
                    out.held_mechanisms = r.held_mechanisms
                    out.out_of_reach = r.out_of_reach
                    out.mechanisms_needed = (out.mechanisms_needed or 0) + (r.mechanisms_needed or 2)
                end
                out.errors = out.errors or {}
                table.insert(out.errors, c.key .. ': ' .. tostring(ok and type(r) == 'table' and r.error or r):sub(1, 120))
            end
        elseif st.link_job then
            table.insert(out.waiting, c.key)
        end
    end
    if #out.linked == 0 then
        out.ok, out.rejected = false, true
        out.error = out.errors and out.errors[1]
            or (#out.waiting > 0 and 'the link jobs are waiting for a mechanic' or 'no cell lever waits for its link')
        out.nothing_to_do = (not out.errors and #out.waiting == 0) or nil
    end
    return out
end

-- The report: how many cells, built, linked, ready (lowered, built, linked)
-- and free (ready and no moon cell holds them); unlinked: built levers with
-- no link and no link job (the brain sends were_cells). held: moon_cell's
-- record ({uid = {zone = key}}).
function report(held)
    local list = cells()
    if #list == 0 then return nil end
    local used = {}
    for uid, c in pairs(type(held) == 'table' and held or {}) do
        if type(c) == 'table' and type(c.zone) == 'string' then used[c.zone] = tonumber(uid) or uid end
    end
    local links = lever_links()
    local out = {n = #list, built = 0, linked = 0, ready = 0, free = 0, raised = 0, unlinked = 0, rows = {}}
    for _, c in ipairs(list) do
        local ok, st = ready(c, links)
        if st.open then out.open = (out.open or 0) + 1 end           -- (R29 W8) a way out besides the bridge
        if st.joined then out.joined = (out.joined or 0) + 1 end     -- (R29 W8) raised, yet DF walks out
        out.built = out.built + (st.built and 1 or 0)
        out.linked = out.linked + (st.linked and 1 or 0)
        out.raised = out.raised + (st.raised and 1 or 0)
        out.ready = out.ready + (ok and 1 or 0)
        out.free = out.free + ((ok and not used[c.key]) and 1 or 0)
        if st.built and not st.linked and not st.link_job then out.unlinked = out.unlinked + 1 end
        if #out.rows < REPORT_ROWS then
            table.insert(out.rows, {key = c.key, built = st.built or nil, linked = st.linked or nil,
                                    raised = st.raised or nil, link_job = st.link_job or nil,
                                    open = st.open, joined = st.joined,         -- (R29 W8)
                                    unit_id = used[c.key], x = c.x1, y = c.y1, z = c.z})
        end
    end
    return out
end

-- the bridges and levers of every cell: {building id = true}
function piece_ids()
    local out = {}
    for _, c in ipairs(cells()) do
        local br, lv = building_at(c.bridge, 'bridge'), building_at(c.lever, 'lever')
        if br then out[br.id] = true end
        if lv then out[lv.id] = true end
    end
    return out
end

-- (0.105.119 item31) Side cells: a 1-tile room dug off a corridor, with a
-- door on its doorway, for a cursed dwarf when the fort has no jail, free
-- bedroom, office or tomb to lock (A, 25 Nov 16:27-16:44: 39 moon_cell
-- calls found no cell while the were cells' levers waited for mechanisms).
-- The corridor floor F, the doorway D = F + d and the room R = F + 2d; every
-- neighbour of R but D (diagonals too: DF walks diagonally) and D's sides
-- are natural rock, so the door is the only way out. Dug through
-- ai-builder's quickfort_apply (the dig guard sees it); once both tiles
-- are dug a door is placed (any door the haulers bring); built, the cell
-- is a room like any other (side_zone: its box, the door on its edge).
--   side_site(pos, taken)  the nearest such place within SIDE_RADIUS on pos's level, or nil
--   side_dig(site, dry_run)  its two tiles designated: how many
--   side_step(rec, dry_run)  'digging', 'door' (placed or building), 'ready'
-- Tests replace shape_at, walk_at, door_at, dig and place_door.
SIDE_RADIUS = 12
SIDE_MAX = 8
local DIRS = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

function shape_at(x, y, z)
    local s, natural
    pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        local a = tt and df.tiletype.attrs[tt]
        if not a then return end
        s = df.tiletype_shape[a.shape]
        local m = df.tiletype_material[a.material]
        natural = m == 'STONE' or m == 'SOIL' or m == 'MINERAL' or m == 'LAVA_STONE'
    end)
    return s, natural
end

function walk_at(x, y, z)
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) end)
    return ok and (tonumber(g) or 0) ~= 0
end

local function rock(x, y, z)
    local s, n = shape_at(x, y, z)
    return s == 'WALL' and n and true or false
end

function side_key(r) return ('dig:%d,%d,%d'):format(r.x, r.y, r.z) end

function side_site(pos, taken)
    taken = taken or {}
    local best, bd
    local z = pos.z
    for dy = -SIDE_RADIUS, SIDE_RADIUS do
        for dx = -SIDE_RADIUS, SIDE_RADIUS do
            local fx, fy = pos.x + dx, pos.y + dy
            local dd = math.abs(dx) + math.abs(dy)
            if (not bd or dd < bd) and shape_at(fx, fy, z) == 'FLOOR' and walk_at(fx, fy, z) then
                for _, d in ipairs(DIRS) do
                    local px, py = d[2], d[1]
                    local Dx, Dy, Rx, Ry = fx + d[1], fy + d[2], fx + 2 * d[1], fy + 2 * d[2]
                    local ok = rock(Dx, Dy, z) and rock(Dx + px, Dy + py, z) and rock(Dx - px, Dy - py, z)
                    for oy = -1, 1 do
                        for ox = -1, 1 do
                            local x, y = Rx + ox, Ry + oy
                            if ok and not (x == Dx and y == Dy) then ok = rock(x, y, z) end
                        end
                    end
                    local r = {x = Rx, y = Ry, z = z}
                    if ok and not taken[side_key(r)] and (not bd or dd < bd) then
                        r.door = {x = Dx, y = Dy, z = z}
                        best, bd = r, dd
                    end
                end
            end
        end
    end
    return best
end

function dig(cells, z)
    local ok, stats = pcall(function() return reqscript('ai-builder').quickfort_apply('dig', cells, z, 0, 0) end)
    if not ok or type(stats) ~= 'table' then return 0 end
    local okv, n = pcall(function()
        local v = stats.dig_designated
        return type(v) == 'table' and v.value or v
    end)
    return okv and tonumber(n) or 0
end

function side_dig(site, dry_run)
    if dry_run then return 2 end
    return dig({{x = site.door.x, y = site.door.y, text = 'd'}, {x = site.x, y = site.y, text = 'd'}}, site.z)
end

function door_at(pos)
    local out
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(pos.x, pos.y, pos.z))
        if b and b:getType() == df.building_type.Door then out = b end
    end)
    return out
end

function place_door(pos)
    local ok, b = pcall(dfhack.buildings.constructBuilding,
                        {type = df.building_type.Door, pos = xyz2pos(pos.x, pos.y, pos.z)})
    return ok and b ~= nil
end

function side_step(rec, dry_run, now)
    local D = rec.door
    if shape_at(D.x, D.y, D.z) ~= 'FLOOR' or shape_at(rec.x, rec.y, rec.z) ~= 'FLOOR' then
        -- still rock: designated again a day on (a dig cancelled, or the guard's refusal lifted)
        if not dry_run and now and now - (tonumber(rec.dug) or 0) >= 1200 then
            rec.dug = now
            side_dig(rec, false)
        end
        return 'digging'
    end
    local b = door_at(D)
    if not b then
        if not dry_run then place_door(D) end
        return 'door'
    end
    return built(b) and 'ready' or 'door'
end

function side_zone(key, rec)
    return {id = key, x1 = rec.x, y1 = rec.y, x2 = rec.x, y2 = rec.y, z = rec.z, side = true}
end
