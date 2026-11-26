-- ai-builder-projects-founding: founding (a fresh embark's first staircase) and cancelling a project
-- (its dig undone, a stair column nobody reaches dropped).
--
-- (r8) A part of ai-builder, not a script of its own: cut from ai-builder-projects.lua
-- (which had grown to 164 KB) at a section boundary, the code as it stood. ai-builder.lua
-- loads it into its own environment right after the part before it (PARTS), so every
-- name here is reqscript('ai-builder').name and the hub's helpers are in reach.
-- The top-level locals the ai-builder-projects files share come through
-- PROJECTS_PART_LOCALS (the same functions).

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-projects-founding'] = '0.105.129'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez
local find = PROJECTS_PART_LOCALS.find

---------------------------------------------------------------------------
-- Founding (a fresh embark): the fort's first staircase. Every level the AI
-- digs grows from a staircase where the dwarves live, and a new embark has
-- none, so the first step is a stair shaft from a surface tile near the
-- wagon down into the ground: a down stair on the surface, up/down stairs
-- through the soil, an up stair on the first level of rock (or 3 levels down
-- when there's no rock near). Never into an aquifer, water, a cavern or warm
-- stone: the whole column is checked before anything is designated. After
-- that, the usual rules dig every level from it.
---------------------------------------------------------------------------

FOUND_RADIUS = 10        -- tiles from the wagon (or the dwarves) to look for the shaft (the builder
                         -- finds stairs within 10 of where the dwarves are)
FOUND_MAX_DEPTH = 8      -- levels the shaft may go down to reach rock
FOUND_WIDE_RADIUS = 20   -- (0.105.35) found_fort{wide}: looked for this far out when nothing near fits
FOUND_SURFACE = {FLOOR = true, PEBBLES = true, SHRUB = true, BOULDER = false}

-- Where the dwarves' wagon stands (a fresh embark), else the middle of the
-- citizens on their busiest level. {x, y, z, what}
function found_center()
    local ok, w = pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.Wagon then
                return {x = b.centerx, y = b.centery, z = b.z, what = 'the wagon'}
            end
        end
    end)
    if ok and w then return w end
    local pos = citizen_positions()
    if #pos == 0 then return nil end
    local by_z = {}
    for _, p in ipairs(pos) do by_z[p.z] = (by_z[p.z] or 0) + 1 end
    local bz, bn = nil, -1
    for z, n in pairs(by_z) do if n > bn then bz, bn = z, n end end
    local xs, ys = {}, {}
    for _, p in ipairs(pos) do if p.z == bz then table.insert(xs, p.x); table.insert(ys, p.y) end end
    table.sort(xs); table.sort(ys)
    return {x = xs[(#xs + 1) // 2], y = ys[(#ys + 1) // 2], z = bz, what = 'the dwarves'}
end

-- The column under a surface tile: {depth to the first rock level, or nil}
-- or nil, why (aquifer, water, cavern, warm stone, open space, not natural).
function found_column(x, y, z)
    local rock
    for d = 1, FOUND_MAX_DEPTH do
        local t = tile_info(x, y, z - d)
        if not t then return nil, 'the map ends' end
        if t.aquifer then return nil, ('an aquifer %d level(s) down'):format(d) end
        if t.liquid then return nil, ('water or magma %d level(s) down'):format(d) end
        if t.feature then return nil, ('a cavern %d level(s) down'):format(d) end
        if t.warm then return nil, ('warm stone %d level(s) down'):format(d) end
        if t.shape ~= 'WALL' then return nil, ('open space %d level(s) down'):format(d) end
        if not NATURAL[t.material] then return nil, ('%s %d level(s) down'):format(tostring(t.material), d) end
        -- and around it: digging the stair opens its sides to anything beside
        for _, n in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
            local nt = tile_info(x + n[1], y + n[2], z - d)
            if nt and nt.aquifer then return nil, ('an aquifer beside it %d level(s) down'):format(d) end
            if nt and nt.liquid then return nil, ('water or magma beside it %d level(s) down'):format(d) end
            if nt and nt.feature then return nil, ('a cavern beside it %d level(s) down'):format(d) end
            -- (0.100, review) open space beside the shaft (a ravine, a river's
            -- channel): the shaft would open into it
            if nt and nt.shape ~= 'WALL' then return nil, ('open space beside it %d level(s) down'):format(d) end
        end
        if t.material ~= 'SOIL' and not rock then rock = d end
        if rock and d >= rock then break end
    end
    return {rock = rock}
end

function found_site(radius)
    radius = radius or FOUND_RADIUS
    local c = found_center()
    if not c then return nil, 'no citizens and no wagon' end
    local best, best_score, why_not = nil, nil, {}
    local w, h = map_size()
    local t0 = os.clock()
    for r = 2, radius do
        -- (0.105.35) a wide search stops short of the bridge's answer time (tried again soon)
        if radius > FOUND_RADIUS and not best and os.clock() - t0 > SEARCH_SECONDS then
            return nil, ('the search stopped at %d tiles from %s (out of time)'):format(r - 1, c.what), true
        end
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = c.x + dx, c.y + dy
                    local t = (x > 1 and y > 1 and x < w - 2 and y < h - 2) and tile_info(x, y, c.z) or nil
                    if t and FOUND_SURFACE[t.shape] and not t.liquid and not t.building and not t.designated then
                        local col, why = found_column(x, y, c.z)
                        if col then
                            -- near the wagon, and rock not far down
                            local score = r + (col.rock and col.rock * 2 or 20)
                            if not best_score or score < best_score then
                                best, best_score = {x = x, y = y, z = c.z, rock = col.rock}, score
                            end
                        elseif why then
                            why_not[why:gsub('%d+ level%(s%) down', 'below')] = true
                        end
                    end
                end
            end
        end
        if best and r >= 6 then break end          -- (looked far enough for a good one)
    end
    if not best then
        local list = {}
        for k in pairs(why_not) do table.insert(list, k) end
        table.sort(list)
        return nil, ('no tile within %d of %s with solid, dry ground under it%s'):format(
            radius, c.what, #list > 0 and (' (found: ' .. table.concat(list, ', ') .. ')') or '')
    end
    best.near = c.what
    return best
end

-- A down stair on the founding level near the wagon or the dwarves (one the
-- AI dug, or yours), even if the dwarves have wandered from it.
function stair_near_center()
    local c = found_center()
    if not c then return nil end
    for dx = -FOUND_RADIUS, FOUND_RADIUS do
        for dy = -FOUND_RADIUS, FOUND_RADIUS do
            local sh = stair_shape(c.x + dx, c.y + dy, c.z)
            if sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN' then return {x = c.x + dx, y = c.y + dy, z = c.z} end
        end
    end
    return nil
end

FOUNDED_KEY = 'ai-overseer/founded'     -- where the AI laid out the first staircase (in the save)

local function founded_site()
    local ok, f = pcall(dfhack.persistent.getSiteData, FOUNDED_KEY, nil)
    return ok and type(f) == 'table' and tonumber(f.x) and f or nil
end

function has_staircase()
    if find_stairs(1) ~= nil or stair_near_center() ~= nil then return true end
    -- the AI's own first shaft, wherever the dwarves have gone since
    local f = founded_site()
    if f then
        local sh = stair_shape(f.x, f.y, f.z)
        return sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN'
    end
    return false
end

function found_fort(dry_run, wide)
    if has_staircase() then return {ok = false, rejected = true, error = 'the fort already has a staircase'} end
    -- a shaft already designated (by the AI earlier, or by you) that the miners
    -- haven't dug yet: wait for it rather than start a second
    local f = founded_site()
    if f then
        local t = tile_info(f.x, f.y, f.z)
        if t and (t.designated or (t.shape or ''):find('^STAIR')) then
            return {ok = false, rejected = true, waiting = true,
                    error = ('the first staircase at x%d y%d is being dug; waiting for the miners'):format(f.x, f.y)}
        end
    end
    local c = found_center()
    if c then
        for dx = -FOUND_RADIUS, FOUND_RADIUS do
            for dy = -FOUND_RADIUS, FOUND_RADIUS do
                local t = tile_info(c.x + dx, c.y + dy, c.z)
                local below = t and t.designated and tile_info(c.x + dx, c.y + dy, c.z - 1)
                if below and below.designated then
                    return {ok = false, rejected = true, waiting = true,
                            error = ('a staircase is designated at x%d y%d; waiting for the miners to dig it'):format(
                                c.x + dx, c.y + dy)}
                end
            end
        end
    end
    -- (0.105.35) wide: nothing near the wagon fits, so further out (FOUND_WIDE_RADIUS)
    local site, why, timed_out = found_site(wide and FOUND_WIDE_RADIUS or nil)
    if not site then return {ok = false, error = why, timed_out = timed_out or nil} end
    local depth = site.rock or 3
    local cells = {{z = site.z, text = 'j'}}
    for d = 1, depth - 1 do table.insert(cells, {z = site.z - d, text = 'i'}) end
    table.insert(cells, {z = site.z - depth, text = 'u'})
    local out = {ok = true, x = site.x, y = site.y, z = site.z, elevation = ez(site.z), levels = depth,
                 rock = site.rock ~= nil, near = site.near}
    if dry_run then out.dry_run = true return out end
    local done, err = pcall(function()
        for _, c in ipairs(cells) do
            local st = quickfort_apply('dig', {{x = 0, y = 0, text = c.text}}, c.z, site.x, site.y)
            if stat(st, 'dig_designated') ~= 1 then error(('could not designate the stair on z%d'):format(ez(c.z))) end
        end
    end)
    if not done then
        for _, c in ipairs(cells) do
            pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.text}}, c.z, site.x, site.y, 'undo')
        end
        return {ok = false, error = 'designating the first stair failed and was undone: ' .. tostring(err)}
    end
    site_put(FOUNDED_KEY, {x = site.x, y = site.y, z = site.z})
    return out
end

-- (0.105.22) `unreached`: given up because no dwarf got to dig it (B, 3-5
-- Nov: a tomb level placed 11 times on the same stair column nobody could
-- reach, given up after 336 days each time): its area is kept off-limits to
-- new levels for UNREACHED_YEARS
UNREACHED_YEARS = 5

-- (0.105.26) The staircases less those in `banned` (x * 100000 + y: the stair
-- of a level given up as out of reach) that no citizen can walk to: none of
-- the column's tiles is in a walk group a citizen stands in. When the walk
-- groups can't be read, a banned stair counts as not reached.
function unreached_stairs_dropped(stairs, banned)
    local groups
    local okp, pos = pcall(citizen_positions)
    if okp and type(pos) == 'table' then
        groups = {}
        for _, cp in ipairs(pos) do
            local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(cp.x, cp.y, cp.z))
            if not okg then groups = nil break end
            if g and g ~= 0 then groups[g] = true end
        end
    end
    local function reached(st)
        if not groups then return false end
        local zb, zt = math.tointeger(st.z_bottom) or st.z, math.tointeger(st.z_top) or st.z
        if not zb or not zt then return false end
        for z = zb, zt do
            local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(st.x, st.y, z))
            if okg and g and g ~= 0 and groups[g] then return true end
        end
        return false
    end
    local kept = {}
    for _, st in ipairs(stairs) do
        if not (banned[st.x * 100000 + st.y] and not reached(st)) then table.insert(kept, st) end
    end
    return kept
end

-- Cancelling a project. Only while digging: removes dig designations on the
-- project's own tiles (dug tiles stay dug, stairs are never removed).
-- (r9, audit A3 20: this note stood above the founding code)
function cancel_project(id, unreached)
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then
        return {ok = false, rejected = true, error = 'only projects still being dug can be cancelled'}
    end
    -- (0.105.33, L4) and what dig_progress keeps designated: a well's shaft,
    -- the stairs it is dug from and its gallery, a way in's column and tunnel
    local pri = type(p.params) == 'table' and p.params.pri or ''
    local function undo_one(x, y, z, key)
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = key .. pri}}, z, x, y, 'undo')
    end
    local a = anchor_of(p)
    -- (0.105.33 merge) a well's own undo (ai-builder-wells.lua undo_well_cells),
    -- one place for what a well designates beyond cells.dig
    if p.kind == 'well' and type(undo_well_cells) == 'function' and type(a) == 'table'
            and pcall(undo_well_cells, p) then
        -- done
    else
        for _, zk in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
            if type(a) == 'table' then undo_one(a.x, a.y, zk, 'h') end
        end
        for _, c in ipairs(type(p.shaft_stairs) == 'table' and p.shaft_stairs or {}) do
            undo_one(c.x, c.y, c.z, c.key)
        end
        for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do undo_one(g.x, g.y, p.z, 'd') end
    end
    p.phase = 'cancelled'
    p.cancelled_tick = now_tick()   -- (0.105.47) a cavern well's cooldown counts from here (ai-well-safety)
    if unreached then
        p.unreached = true
        p.cancelled_year = df.global.cur_year
    end
    save_projects(data)
    -- (layout B) a floor level's slots and hall are taken out of its floor (ai-builder-floorstore.lua)
    if p.floor and type(floor_release) == 'function' then pcall(floor_release, p) end
    -- (F1, verify V1) the level's dig undone after its floor's record let it go: the hub, hall
    -- and stair tiles another live level of the floor still hangs on (only a floor's first
    -- level designates them) are left designated, only the rest undone (ai-builder-floorstore)
    local dig_undo, stairs_undo = cells_of(p, 'dig'), p.stairs
    if p.floor and type(floor_cancel_keep) == 'function' and type(floor_cells_without) == 'function' then
        local okk, keep, keep_stairs, more, more_stairs = pcall(floor_cancel_keep, p, data)
        if okk and type(keep) == 'table' then
            local okw, rest = pcall(floor_cells_without, dig_undo, keep)
            if okw and type(rest) == 'table' then dig_undo = rest end
            if keep_stairs then stairs_undo = nil end
        end
        -- what an earlier cancel on this floor left designated and no live level needs now
        if okk and type(more) == 'table' and #more > 0 then
            local all = {}
            for _, c in ipairs(dig_undo) do table.insert(all, c) end
            for _, c in ipairs(more) do table.insert(all, c) end
            dig_undo = all
        end
        if okk and type(more_stairs) == 'table' and #more_stairs > 0 then
            local all = {}
            for _, c in ipairs(type(stairs_undo) == 'table' and stairs_undo or {}) do table.insert(all, c) end
            for _, c in ipairs(more_stairs) do table.insert(all, c) end
            stairs_undo = all
        end
    end
    undo_dig(dig_undo, stairs_undo, p.z, anchor_of(p), p.stair)
    return {ok = true, project_id = id}
end

-- (r8) handed on to the ai-builder-projects files after this one (ai-builder-projects-wayin)
PROJECTS_PART_LOCALS.founded_site = founded_site
