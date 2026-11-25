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
--   ready(c)             a cell moon_cell may use: built, linked, lowered, still
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

function ready(c, links)
    local st = cell_state(c, links)
    return st.built and st.linked and not st.raised and not st.moving, st
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
        local st = cell_state(c, links)
        local ok = st.built and st.linked and not st.raised and not st.moving
        out.built = out.built + (st.built and 1 or 0)
        out.linked = out.linked + (st.linked and 1 or 0)
        out.raised = out.raised + (st.raised and 1 or 0)
        out.ready = out.ready + (ok and 1 or 0)
        out.free = out.free + ((ok and not used[c.key]) and 1 or 0)
        if st.built and not st.linked and not st.link_job then out.unlinked = out.unlinked + 1 end
        if #out.rows < REPORT_ROWS then
            table.insert(out.rows, {key = c.key, built = st.built or nil, linked = st.linked or nil,
                                    raised = st.raised or nil, link_job = st.link_job or nil,
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
