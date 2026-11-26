-- (0.105.47) The deep plan's descent: the fort's main stair taken down past
-- the first cavern in a sealed crossing, so a deep fort (high Verticality,
-- the Deep mine) can put its levels below the cavern as it grows.
--
-- Why: the 14 Nov scorecard. The Deep mine (E) was the SHALLOWEST fort
-- (deepest level 8 under the surface; A 19, B 29); the master plan stops
-- every district CAVERN_MARGIN levels over the first cavern (brain/
-- masterplan.py _range) and the builder's stair extension refuses any tile
-- of a cavern (ai-builder-sites check_extension: natural_wall), so nothing
-- could ever go deeper. 0.105.44 G6 left it as "deeper needs a stair past
-- Cavern1 (open item)".
--
-- The crossing, at the spine's own column (x, y), from the stair's bottom down:
--   * the rock above the cavern: an up/down stair dug ('i'), each tile and
--     its 8 neighbours untouched natural rock (as check_extension asks);
--   * each level of the cavern's layer (z_top .. z_bottom): the shaft's tile
--     dug where it is rock, a constructed up/down stair ('Cx') where it is
--     open; every open neighbour (open space, cavern floor, pebbles) walled
--     ('Cw'); rock neighbours left as they are. So the stair runs through
--     the cavern inside a walled shaft: nothing in the cavern can walk in.
--   * BELOW_ROCK levels of solid rock under the layer, dug ('i', the last
--     'u'): the builder's ordinary extension takes the stair on from there.
-- Refused, before anything is marked, when any tile of the 3x3 column on
-- any level holds water or magma, an aquifer, warm stone, open sky, a tree,
-- a ramp, a boulder or a building of someone else's; when the dig guard
-- (ai-util dig_forbidden: adamantine, the spire, the underworld) refuses a
-- tile it would dig; when the layer is the lowest cavern (the deep floor
-- lies under it); when there is no solid rock under the layer; or when the
-- column would run more than MAX_LEVELS.
-- A step at a time (the brain's `cross_cavern` each cycle): the rock above
-- first (its last level held back), then one cavern level at a time from
-- the top (the stair, then its walls, are built from the stair above), then
-- the rock below. A step waits while the last one's tiles are marked or
-- being built, while a hostile creature is in the layer near the column,
-- and while the AI has the caverns sealed against a great beast.
--
--   plan_crossing(read, forbid, x, y, zb, layer, opts)   pure (the tests call it)
--   progress(read, plan)                                  pure: each step's state
--   cross_cavern(a, dry_run)                              the bridge action
--   report()                                              the `descent` section
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/descent'
BELOW_ROCK = 2           -- solid rock levels under the cavern's layer the stair reaches
MAX_LEVELS = 60          -- the column runs at most this many levels down
DANGER_RADIUS = 25       -- a hostile creature in the layer this near the column: wait
local NB = {{-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1}}
-- open tiles a wall can be built on (anything else open in the way refuses).
-- (item6, R32 e) a shrub or a sapling on the cavern floor too: DF builds a
-- construction over one (quickfort's own check takes them, as the gates' and
-- the cistern's walls do) and the plant goes. E's crossing was refused 13
-- times for "a shrub where the stair goes" and nothing cleared it.
BUILD_ON = {EMPTY = true, FLOOR = true, PEBBLES = true, SHRUB = true, SAPLING = true}
local NATURAL = {STONE = true, MINERAL = true, SOIL = true, LAVA_STONE = true}
local STAIRS = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true}

local function B() return reqscript('ai-builder') end

-- why a tile anywhere in the column refuses the crossing, or nil
local function hazard(t)
    if not t then return 'off the map' end
    if t.liquid then return t.magma and 'magma' or 'water' end
    if t.magma then return 'magma' end
    if t.aquifer then return 'an aquifer' end
    if t.warm then return 'warm stone (magma nearby)' end
    if t.outside then return 'open to the sky' end
    return nil
end

local function rock(t)
    return t.shape == 'WALL' and NATURAL[t.material] == true and not t.designated and not t.building
end

local function where(x, y, z, ez)
    return ('x%d y%d z%d'):format(x, y, ez and ez(z) or z)
end

-- The crossing's cells, level by level, from the map as it is (tiles the
-- crossing already dug, built or marked count as its own).
--   read(x, y, z)   tile info (ai-builder tile_info's fields) or nil
--   forbid(x, y, z) the dig guard's why, or nil
--   zb              the stair's bottom z now (where the column starts)
--   layer           {name, z_top, z_bottom} of the cavern to cross
--   opts            {floor = the deep floor z (refused at or above it: the
--                   lowest cavern), ez = z -> elevation for the words,
--                   bottom_shape = the stair's bottom shape at zb}
-- Returns {levels = {{z, part = 'above'|'cavern'|'below', cells = {{x, y, z,
-- mode = 'dig'|'build', text}}}}, z_end}, or nil and why.
function plan_crossing(read, forbid, x, y, zb, layer, opts)
    opts = opts or {}
    local ez = opts.ez
    local top, bot = tonumber(layer and layer.z_top), tonumber(layer and layer.z_bottom)
    if not top or not bot or top < bot then return nil, 'the cavern layer is not known' end
    if zb <= top then return nil, 'the stair already reaches the cavern' end
    if opts.floor and bot <= opts.floor then
        return nil, ('%s is the lowest cavern: only the deep lies under it'):format(tostring(layer.name))
    end
    local z_end = bot - BELOW_ROCK
    if zb - z_end > MAX_LEVELS then
        return nil, ('the cavern lies %d levels under the stair (at most %d)'):format(zb - top, MAX_LEVELS)
    end
    local levels = {}
    -- the stair's bottom step made an up/down stair (as stair_cells does)
    if opts.bottom_shape == 'STAIR_UP' then
        table.insert(levels, {z = zb, part = 'above', cells = {{x = x, y = y, z = zb, mode = 'dig', text = 'i'}}})
    end
    for z = zb - 1, z_end, -1 do
        local part = z > top and 'above' or z >= bot and 'cavern' or 'below'
        local text = z == z_end and 'u' or 'i'
        local cells = {}
        -- every tile of the 3x3 (and the shaft's tile under the last level)
        local tiles = {}
        for _, d in ipairs({{0, 0}, table.unpack(NB)}) do
            local t = read(x + d[1], y + d[2], z)
            local why = hazard(t)
            if why then return nil, ('%s at %s'):format(why, where(x + d[1], y + d[2], z, ez)) end
            if t.feature_local then
                return nil, ('a pool or magma pipe at %s'):format(where(x + d[1], y + d[2], z, ez))
            end
            tiles[#tiles + 1] = t
        end
        local shaft = tiles[1]
        if part ~= 'cavern' then
            -- solid rock all round; the shaft's tile rock, or the crossing's own stair
            for i = 2, 9 do
                local t = tiles[i]
                if not rock(t) or t.feature then
                    return nil, ('%s: not solid rock beside the stair at %s'):format(
                        part == 'below' and 'no solid rock under the cavern' or 'the way down',
                        where(x + NB[i - 1][1], y + NB[i - 1][2], z, ez))
                end
            end
            if not (STAIRS[shaft.shape] or (shaft.designated and shaft.shape == 'WALL') or rock(shaft))
                    or (shaft.feature and not STAIRS[shaft.shape]) then
                return nil, ('not solid rock under the stair at %s'):format(where(x, y, z, ez))
            end
            cells[#cells + 1] = {x = x, y = y, z = z, mode = 'dig', text = text}
        else
            if shaft.shape == 'WALL' then
                if shaft.building or not NATURAL[shaft.material] then
                    return nil, ('a built wall or building where the stair goes at %s'):format(where(x, y, z, ez))
                end
                cells[#cells + 1] = {x = x, y = y, z = z, mode = 'dig', text = 'i'}
            elseif STAIRS[shaft.shape] then
                -- the crossing's own stair: built ('Cx') or dug ('i') before
                local built = shaft.material == 'CONSTRUCTION'
                cells[#cells + 1] = {x = x, y = y, z = z, mode = built and 'build' or 'dig', text = built and 'Cx' or 'i'}
            elseif BUILD_ON[shaft.shape] then
                -- (r9, audit A3 10) "ours" covers only a construction being
                -- built (the crossing's own): a trap, a door of the cavern
                -- seal, the player's building refuses (construction == false)
                if shaft.building and (not opts.ours or shaft.construction == false) then
                    return nil, ('something is built at %s'):format(where(x, y, z, ez))
                end
                cells[#cells + 1] = {x = x, y = y, z = z, mode = 'build', text = 'Cx'}
            else
                return nil, ('a %s where the stair goes at %s'):format(tostring(shaft.shape):lower(), where(x, y, z, ez))
            end
            for i = 2, 9 do
                local t = tiles[i]
                local nx, ny = x + NB[i - 1][1], y + NB[i - 1][2]
                if t.shape == 'WALL' then
                    -- rock or a wall already built: the shaft's side as it is
                elseif BUILD_ON[t.shape] then
                    if t.building and (not opts.ours or t.construction == false) then   -- (r9)
                        return nil, ('something is built beside the stair at %s'):format(where(nx, ny, z, ez))
                    end
                    cells[#cells + 1] = {x = nx, y = ny, z = z, mode = 'build', text = 'Cw'}
                else
                    return nil, ('a %s beside the stair at %s'):format(tostring(t.shape):lower(), where(nx, ny, z, ez))
                end
            end
        end
        for _, c in ipairs(cells) do
            if c.mode == 'dig' and forbid then
                local why = forbid(c.x, c.y, c.z)
                if why then return nil, ('the dig guard refuses %s: %s'):format(where(c.x, c.y, c.z, ez), tostring(why)) end
            end
        end
        table.insert(levels, {z = z, part = part, cells = cells})
    end
    return {levels = levels, z_end = z_end, z_start = zb}
end

-- A cell's state on the map: 'done', 'marked' (dug or built when the
-- dwarves get to it) or 'open' (nothing yet)
function cell_state(read, c)
    local t = read(c.x, c.y, c.z)
    if not t then return 'open' end
    if c.text == 'Cw' then
        if t.shape == 'WALL' then return 'done' end
        return t.building and 'marked' or 'open'
    end
    if c.text == 'u' then
        if t.shape == 'STAIR_UP' or t.shape == 'STAIR_UPDOWN' then return 'done' end
    elseif t.shape == 'STAIR_UPDOWN' then
        return 'done'
    end
    if c.mode == 'dig' then return t.designated and 'marked' or 'open' end
    return t.building and 'marked' or 'open'
end

-- The steps (each a list of levels placed together): the rock above but its
-- last level; each cavern level with the level over it held back; the rock
-- below. Returns {steps = {{levels, state = 'done'|'marked'|'open'}}, next}
-- where next is the first step not done (nil when the crossing is built).
function progress(read, plan)
    local steps, cur = {}, nil
    local lv = plan.levels
    for i, l in ipairs(lv) do
        local nxt = lv[i + 1]
        if l.part == 'above' then
            -- the last rock level over the cavern goes with the first cavern level
            if nxt and nxt.part == 'above' then
                cur = cur or {levels = {}}
                table.insert(cur.levels, l)
            else
                if cur then table.insert(steps, cur) end
                cur = {levels = {l}}
            end
        elseif l.part == 'cavern' then
            cur = cur or {levels = {}}
            table.insert(cur.levels, l)
            table.insert(steps, cur)
            cur = nil
        else
            cur = cur or {levels = {}}
            table.insert(cur.levels, l)
        end
    end
    if cur then table.insert(steps, cur) end
    local nxt
    for i, st in ipairs(steps) do
        local any_open, any_marked = false, false
        for _, l in ipairs(st.levels) do
            for _, c in ipairs(l.cells) do
                local s = cell_state(read, c)
                if s == 'open' then any_open = true elseif s == 'marked' then any_marked = true end
            end
        end
        st.state = any_open and 'open' or any_marked and 'marked' or 'done'
        if st.state ~= 'done' and not nxt then nxt = i end
    end
    return {steps = steps, next = nxt}
end

---------------------------------------------------------------------------
-- The game side
---------------------------------------------------------------------------

local function load() local d = U.site_get(SITE_KEY, {}); return type(d) == 'table' and d or {} end
local function save(d) U.site_put(SITE_KEY, d) end

local function offset()
    local ok, v = pcall(function() return B().elevation_offset() end)
    return ok and tonumber(v) or 0
end

-- the layer by name ({name, z_top, z_bottom}) and the deep floor
local function layer_named(name, layers)
    local out, floor
    pcall(function()
        for _, l in ipairs(layers.list) do
            if l.name == name and l.z_top then out = {name = l.name, z_top = l.z_top, z_bottom = l.z_bottom} end
        end
    end)
    pcall(function()
        local dm = U.deep_map()
        if dm and dm.ok then floor = dm.floor end
    end)
    return out, floor
end

local function forbid(x, y, z)
    local ok, why = pcall(function() return U.dig_forbidden(x, y, z) end)
    return ok and why or nil
end

-- (r9, audit A3 10) a building on the tile: true when it is a construction
-- (a wall or stair being built), false when it is anything else, nil when
-- it can't be told
function construction_at(x, y, z)
    local ok, is = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if not b then return nil end
        return b:getType() == df.building_type.Construction
    end)
    if ok then return is end
    return nil
end

local function read(x, y, z)
    local ok, t = pcall(function() return B().tile_info(x, y, z) end)
    if ok and t and t.building then t.construction = construction_at(x, y, z) end
    return ok and t or nil
end

-- hostile creatures in the layer (z_top+1 .. z_bottom) within DANGER_RADIUS of the column
function danger_near(x, y, layer)
    local n = 0
    pcall(function()
        local Bm = B()
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function()
                if dfhack.units.isDead(u) or dfhack.units.isCitizen(u) then return end
                local p = u.pos
                if p.z > layer.z_top + 1 or p.z < layer.z_bottom then return end
                if math.max(math.abs(p.x - x), math.abs(p.y - y)) > DANGER_RADIUS then return end
                local bad = false
                pcall(function() bad = dfhack.units.isDanger(u) end)
                if not bad and Bm.hostile_wild then pcall(function() bad = Bm.hostile_wild(u) end) end
                if bad then n = n + 1 end
            end)
        end
    end)
    return n
end

-- the caverns sealed by the AI against a great beast (ai-threats' record)
local function sealed()
    local ok, v = pcall(function()
        local d = reqscript('ai-threats').load_state()
        return next(d.sealed or {}) ~= nil
    end)
    return ok and v == true
end

-- the crossing planned from the record ({x, y, z_start, layer}); nil, why
local function current(d, layers)
    local layer, floor = layer_named(d.layer, layers or {list = {}})
    if not layer then return nil, 'the cavern layer ' .. tostring(d.layer) .. ' is not on this map' end
    local off = offset()
    local plan, why = plan_crossing(read, forbid, d.x, d.y, d.z_start, layer,
                                    {floor = floor, ez = function(z) return z + off end, ours = true,
                                     bottom_shape = d.bottom_shape})
    return plan, why, layer, off
end

-- The `descent` section: none | ready | working | built | blocked, the
-- crossing's place and depth, its steps, the danger in the layer.
function report(layers)
    local d = load()
    if not d.x then return {state = 'none'} end
    local plan, why, layer, off = current(d, layers)
    off = off or offset()
    local out = {x = d.x, y = d.y, layer = d.layer, elevation_start = d.z_start + off,
                 started = d.started}
    if not plan then
        out.state, out.why = 'blocked', why
        return out
    end
    local pr = progress(read, plan)
    out.elevation_bottom = plan.z_end + off
    out.steps, out.steps_done = #pr.steps, (pr.next or (#pr.steps + 1)) - 1
    if not pr.next then
        out.state = 'built'
    else
        out.state = pr.steps[pr.next].state == 'marked' and 'working' or 'ready'
        out.danger = layer and danger_near(d.x, d.y, layer) or nil
        if out.danger == 0 then out.danger = nil end
        out.sealed = sealed() or nil
    end
    return out
end

-- The bridge action: the next step of the crossing marked (dug or built).
-- a = {x, y, elev (any level of the spine stair), layer}
function cross_cavern(a, dry_run, layers)
    local Bm = B()
    local d = load()
    local off = offset()
    if not d.x or d.x ~= a.x or d.y ~= a.y or d.layer ~= a.layer then
        -- a new crossing: the spine stair's run at (x, y)
        local z0 = a.elev - off
        local zt, zb, shape
        for z = z0, z0 - 30, -1 do
            local ok, s = pcall(Bm.stair_shape, a.x, a.y, z)
            if ok and s then
                zt, zb = Bm.stair_run(a.x, a.y, z)
                shape = Bm.stair_shape(a.x, a.y, zb)
                break
            end
        end
        if not zb then
            return {ok = false, rejected = true, error = ('no stair at x%d y%d near elevation %d'):format(a.x, a.y, a.elev)}
        end
        d = {x = a.x, y = a.y, layer = a.layer, z_start = zb, bottom_shape = shape, started = (function() local ok, t = pcall(U.abs_tick); return ok and t or nil end)()}
    end
    local plan, why, layer = current(d, layers)
    if not plan then return {ok = false, rejected = true, error = 'no crossing: ' .. tostring(why)} end
    local pr = progress(read, plan)
    if not pr.next then
        if not dry_run then save(d) end
        return {ok = false, rejected = true, nothing_to_do = true, built = true,
                error = 'the crossing is built: the stair reaches elevation ' .. (plan.z_end + off)}
    end
    if not dry_run then save(d) end      -- the crossing on record (the report follows it) from its first try
    local step = pr.steps[pr.next]
    if step.state == 'marked' then
        return {ok = false, rejected = true, nothing_to_do = true, waiting = true,
                error = 'the last step is still being dug or built'}
    end
    local touches = false
    for _, l in ipairs(step.levels) do if l.part == 'cavern' then touches = true end end
    if touches and sealed() then
        return {ok = false, rejected = true, waiting = true, error = 'the caverns are sealed against a great beast'}
    end
    local n_danger = touches and danger_near(d.x, d.y, layer) or 0
    if n_danger > 0 then
        return {ok = false, rejected = true, waiting = true,
                error = n_danger .. ' hostile creature(s) in ' .. tostring(d.layer) .. ' near the stair'}
    end
    -- each level's open cells, dug then built, through quickfort (the dig guard on every dig)
    local placed, failed = 0, nil
    for _, l in ipairs(step.levels) do
        local dig, build = {}, {}
        for _, c in ipairs(l.cells) do
            if cell_state(read, c) == 'open' then
                table.insert(c.mode == 'dig' and dig or build, {x = c.x - d.x, y = c.y - d.y, text = c.text})
            end
        end
        for _, part in ipairs({{'dig', dig}, {'build', build}}) do
            if #part[2] > 0 and not failed then
                local ok = Bm.qf_try(part[1], part[2], l.z, d.x, d.y, dry_run, #part[2], false)
                if ok then placed = placed + #part[2]
                else failed = ('%s at elevation %d: quickfort would not place it'):format(part[1], l.z + off) end
            end
        end
        if failed then break end
    end
    if failed then return {ok = false, error = failed, placed = placed} end
    if not dry_run then save(d) end
    return {ok = true, dry_run = dry_run or nil, placed = placed, step = pr.next, steps = #pr.steps,
            layer = d.layer, elevation_bottom = plan.z_end + off,
            levels = #step.levels, cavern = touches or nil}
end
