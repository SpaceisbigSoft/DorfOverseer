-- The fort's water: what there is on the map, where, and of what kind,
-- the base for everything the AI does with water (wells, cisterns,
-- channels, moats, pumps and floodgates: see handoff.md, "Water
-- engineering") and with magma.
--
-- (0.105.38) The survey reads the whole map (the player, 12 Nov: "the
-- water survey should use the entire map"): every x and y, from the surface
-- (the highest level with ground on it) down to the magma sea's top (or the
-- map's floor), a slice of blocks a call (scan_step), so the game never
-- stalls. Two results come of the one pass:
--
-- * `waters`: every body on the map, each one a connected run of map blocks
--   holding the same kind of liquid, by kind:
--     river, brook       flowing surface water (flow = 'flowing')
--     lake, pond, pool   still water (flow = 'stagnant'; `underground` when
--                        under a roof outside the caverns: a dug or natural pool)
--     sea                salt water under the sky
--     cavern             water in a cavern layer (`cavern`: which one)
--     aquifer            wall tiles that seep water
--     magma              by `magma`: pipe (a magma pipe's column), volcano (a
--                        pipe open to the sky), cavern (a pool in a cavern:
--                        `cavern`), sea (the magma sea), surface, pool
--   with its tiles, volume (sum of depths, 7 = a full tile), levels, salt /
--   stagnant / seen shares, the tile nearest the fort (`nearest`, `d`: the
--   tiles across plus twice the levels), its highest tile (`top`), and a
--   reach estimate: `reach`, the length of a dig from the fort's middle
--   (a shaft, then an L-shaped tunnel) through safe rock to it, or nil;
--   `opens_cavern` (the cavern such a dig crosses: reaching it opens it),
--   `aquifer` (it crosses one) and `reach_through` (its length all the same)
--   say why not. The list is capped (WATERS_MAX: every flowing body up to
--   FLOWING_MAX, every kind of magma, then the nearest and the biggest),
--   nearest first; `waters_found` counts them all.
-- * `bodies`, `aquifer`, `magma` (as before 0.105.38): the water within
--   RADIUS tiles of the fort's middle, from SURFACE_ABOVE levels over the
--   highest dwarf down to DEPTH levels under the lowest, summed by kind
--   (river, surface, cavern, pool): what the water works chose from before,
--   so a fort whose water is near makes the same choices as before.
--
-- (0.105.38 review) The near box is scanned first, its blocks as before
-- 0.105.38, and its result saved at once (`waters_pending`: the whole map's
-- list is the survey before's until this one's is done); the whole map's
-- slices skip its blocks. Magma is read by its deep feature's type
-- (getGlobalInitFeature): only the sea's sets the sea's top; unknown, a
-- cavern's pool. Ice under the sky is a body of its own (`ice`); a river
-- seen before and now ice is `frozen_river`.
--
-- Kept in the save (site data 'ai-overseer/water') and reported from there:
-- the scan runs once a season (the survey_water action), the report costs
-- nothing.
--@ module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end
local function report_units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end

WATER_KEY = 'ai-overseer/water'
RADIUS = 72
SURFACE_ABOVE = 12
DEPTH = 80
MAX_SECONDS = 4
-- (0.105.38) the whole-map survey
WATERS_MAX = 16          -- bodies in the report at most
FLOWING_MAX = 6          -- rivers and brooks always among them (the nearest first)
MAGMA_MAX = 6            -- bodies of magma among them at most (one of each kind first)
LAKE_TILES = 400         -- still surface water this big: a lake
POND_TILES = 20          -- this big: a pond (smaller: a pool)
RIVER_BLOCKS_MAX = 1500  -- (0.105.38 review) a river's blocks kept at most (ice there later: a frozen river)
SEA_BELOW = 2            -- the scan goes this many levels under the magma sea's top, no further

local function fort_middle()
    local xs, ys, zs, n = 0, 0, {}, 0
    for _, u in ipairs(report_citizens(true)) do
        local x, y, z = dfhack.units.getPosition(u)
        if x then
            xs, ys, n = xs + x, ys + y, n + 1
            table.insert(zs, z)
        end
    end
    if n == 0 then return nil end
    table.sort(zs)
    return {x = xs // n, y = ys // n, z_low = zs[1], z_high = zs[#zs], z_mid = zs[(#zs + 1) // 2]}
end

local function new_body(kind)
    return {kind = kind, tiles = 0, volume = 0, z1 = math.huge, z2 = -math.huge, salt = 0, stagnant = 0,
            seen = 0, deep = 0, nearest = nil}
end

local RIVER_MATS = {RIVER = true, BROOK = true}

-- (0.105.38) The deep layers by the block's global feature index:
-- {[gid] = {name = 'Cavern1'|'MagmaSea'|'Underworld', found = bool}}. A
-- global function, so the tests can swap it.
function layer_names()
    local out = {}
    pcall(function()
        local feats = df.global.world.features
        for i, f in ipairs(feats.map_features) do
            if df.feature_init_subterranean_from_layerst:is_instance(f)
                    or df.feature_init_magma_core_from_layerst:is_instance(f)
                    or df.feature_init_underworld_from_layerst:is_instance(f) then
                out[feats.feature_global_idx[i]] = {name = tostring(df.layer_type[f.start_depth] or ('Layer' .. tostring(f.start_depth))),
                                                    found = f.flags.Discovered and true or false}
            end
        end
    end)
    return out
end

-- (0.105.38 review) The kind of a global feature (a block's
-- global_feature): 'sea' (the magma sea), 'underworld', 'cavern', or nil
-- when unknown. DFHack's getGlobalInitFeature first (its type, not the layer
-- names, which may fail), then the layer names. Unknown magma is read as a
-- cavern's pool: only magma known to be the sea's sets the sea's top (and
-- stops the scan under it). A global function, so the tests can swap it.
function feature_kind(gid, names)
    if gid == nil or gid < 0 then return nil end
    local ok, k = pcall(function()
        local f = dfhack.maps.getGlobalInitFeature(gid)
        if not f then return nil end
        local t = f:getType()
        local ft = df.feature_type
        if t == ft.magma_core_from_layer then return 'sea' end
        if t == ft.underworld_from_layer then return 'underworld' end
        if t == ft.subterranean_from_layer then return 'cavern' end
        return nil
    end)
    if ok and k then return k end
    local layer = names and names[gid]
    local n = layer and tostring(layer.name) or ''
    if n:find('Cavern') then return 'cavern' end
    if n:find('MagmaSea') then return 'sea' end
    if n:find('Underworld') then return 'underworld' end
    return nil
end

-- the job's feature kinds, cached by global feature index (false: unknown)
local function fkind(job, gid)
    if gid == nil then return nil end
    local c = job.fkinds[gid]
    if c == nil then
        c = feature_kind(gid, job.names) or false
        job.fkinds[gid] = c
    end
    return c or nil
end

local function open_tiletype()
    local ok, v = pcall(function() return df.tiletype.OpenSpace end)
    return ok and v or nil
end

-- the tiletype's shape and material names (nil when unknown), cached by
-- tiletype (they never change)
TT_CACHE = TT_CACHE or {}
local function tt_names(tt)
    local c = tt ~= nil and TT_CACHE[tt]
    if c then return c[1], c[2] end
    local ok, shape, mat = pcall(function()
        local a = df.tiletype.attrs[tt]
        return a.shape ~= nil and df.tiletype_shape[a.shape] or nil, df.tiletype_material[a.material]
    end)
    if not ok then shape, mat = nil, nil end
    if tt ~= nil then TT_CACHE[tt] = {shape, mat} end
    return shape, mat
end

-- the classes a body's blocks are joined by (cells of one class touching)
local CLASSES = {'f', 's', 'l', 'u', 'c', 'a', 'mp', 'mc', 'ms', 'mo', 'mu', 'i'}   -- (i: ice, a frozen river or lake)
local CLASS_ID = {}
for i, c in ipairs(CLASSES) do CLASS_ID[c] = i end

-- A survey in slices (the lag pass: the whole scan froze the game ~1.4 s):
-- start_survey() sets it up, survey_step(job, seconds) scans a block after
-- another (the levels above the start up to the surface first, then down)
-- until the time is up and says whether it's done, then joins the blocks
-- into bodies and estimates each one's reach (in slices too);
-- finish_survey() sums it up. survey() does it all at once (the tests).
function start_survey()
    local mid = fort_middle()
    if not mid then return nil, 'no citizens' end
    local W, H, Z = dfhack.maps.getTileSize()
    local z2 = math.min(Z - 1, mid.z_high + SURFACE_ABOVE)
    local job = {mid = mid, W = W, H = H, Z = Z, nbx = (W + 15) // 16, nby = (H + 15) // 16,
                 x1 = math.max(0, mid.x - RADIUS), x2 = math.min(W - 1, mid.x + RADIUS),
                 y1 = math.max(0, mid.y - RADIUS), y2 = math.min(H - 1, mid.y + RADIUS),
                 z1 = math.max(0, mid.z_low - DEPTH), z2 = z2,
                 bodies = {river = new_body('river'), surface = new_body('surface'), cavern = new_body('cavern'),
                           pool = new_body('pool')},
                 aquifer = {}, magma = {}, frozen = {},
                 -- (0.105.38 review) the near box first (its blocks, as before
                 -- 0.105.38), its result saved at once; then the whole map
                 phase = 'near', z = z2, bi = 0, ground = false, ztop = z2,
                 cells = {}, list = {}, names = layer_names(), fkinds = {}, open = open_tiletype()}
    job.bx1, job.bx2, job.by1, job.by2 = job.x1 // 16, job.x2 // 16, job.y1 // 16, job.y2 // 16
    return job
end

local function add_cell(job, cls, bx, by, bz, x, y, d, extra)
    local k = ((CLASS_ID[cls] * job.Z + bz) * job.nby + by) * job.nbx + bx
    local c = job.cells[k]
    if not c then
        c = {k = k, cls = cls, bx = bx, by = by, z = bz, tiles = 0, volume = 0, deep = 0, salt = 0, stagnant = 0,
             seen = 0, river = 0, brook = 0, outside = 0}
        job.cells[k] = c
        table.insert(job.list, c)
    end
    c.tiles = c.tiles + 1
    local fs = d.flow_size or 0
    c.volume = c.volume + fs
    if fs >= 4 then c.deep = c.deep + 1 end
    if d.water_salt then c.salt = c.salt + 1 end
    if d.water_stagnant then c.stagnant = c.stagnant + 1 end
    if not d.hidden then c.seen = c.seen + 1 end
    if d.outside then c.outside = c.outside + 1 end
    if extra == 'RIVER' then c.river = c.river + 1 elseif extra == 'BROOK' then c.brook = c.brook + 1 end
    local mid = job.mid
    local dist = math.max(math.abs(x - mid.x), math.abs(y - mid.y)) + 2 * math.abs(bz - mid.z_mid)
    local man = math.abs(x - mid.x) + math.abs(y - mid.y)        -- (ties: the straighter way)
    if not c.nd or dist < c.nd or (dist == c.nd and man < c.nm) then
        c.nx, c.ny, c.nd, c.nm, c.ndepth = x, y, dist, man, fs
    end
    local flat = math.max(math.abs(x - mid.x), math.abs(y - mid.y))
    if not c.td or flat < c.td then c.tx, c.ty, c.td, c.tout = x, y, flat, d.outside and true or nil end
end

-- one map block: the near box's sums as before (`near`: the block is one of
-- the near box's, every tile of it counted, as before 0.105.38), and the
-- whole map's cells. true when it holds ground (anything but open space:
-- the up phase's test)
local FROZEN = 'FROZEN_LIQUID'
local function scan_block(job, bx, by, bz, want_ground, near)
    local block = dfhack.maps.getBlock(bx, by, bz)
    if not block then return false end
    local mid, bodies, aquifer, magma = job.mid, job.bodies, job.aquifer, job.magma
    local gk = fkind(job, block.global_feature)
    local layer = job.names[block.global_feature]
    local lname = gk == 'cavern' and (layer and layer.name or 'a cavern') or nil
    local ground = false
    local open = job.open
    for lx = 0, 15 do
        local col = block.designation[lx]
        local x = bx * 16 + lx
        for ly = 0, 15 do
            local d = col[ly]
            local y = by * 16 + ly
            if want_ground and not ground then
                local tt = block.tiletype[lx][ly]
                if open == nil or tt ~= open then ground = true end
            end
            local fs = d.flow_size
            -- (0.105.38 review) ice under the sky (a frozen river or lake: its
            -- tiletype's material FROZEN_LIQUID), only outside tiles looked at
            local frozen = false
            if d.outside then
                local _, mat = tt_names(block.tiletype[lx][ly])
                if mat == FROZEN then
                    frozen = true
                    if near then job.frozen[bz] = (job.frozen[bz] or 0) + 1 end
                    add_cell(job, 'i', bx, by, bz, x, y, d)
                end
            end
            if fs > 0 then
                local is_magma = d.liquid_type == true or d.liquid_type == 1
                local feat = d.feature_local or d.feature_global
                if is_magma then
                    if near then
                        magma[bz] = (magma[bz] or 0) + 1
                        -- (0.105.0) the highest magma outside the caverns, nearest
                        -- the fort's middle: what a magma workshop is dug to
                        if not feat then
                            local dist = math.max(math.abs(x - mid.x), math.abs(y - mid.y))
                            local t = job.magma_top
                            if not t or bz > t.z or (bz == t.z and dist < t.d) then
                                job.magma_top = {x = x, y = y, z = bz, d = dist}
                            end
                        end
                    end
                    -- (0.105.38) the magma's kind: the magma sea (or the
                    -- underworld) and the caverns are global features, the
                    -- pipes local ones. (review) By the feature's type: only
                    -- magma known to be the sea's is the sea; unknown, a
                    -- cavern's pool (the scan goes on under it)
                    local cls
                    if d.feature_global then
                        cls = (gk == 'sea' or gk == 'underworld') and 'ms' or 'mc'
                    elseif d.feature_local then cls = 'mp'
                    elseif d.outside then cls = 'mo'
                    else cls = 'mu' end
                    if cls == 'ms' and gk == 'sea' and (not job.sea_top or bz > job.sea_top) then job.sea_top = bz end
                    add_cell(job, cls, bx, by, bz, x, y, d)
                else
                    local tt = block.tiletype[lx][ly]
                    local _, mat = tt_names(tt)
                    if near then
                        local kind = feat and 'cavern' or RIVER_MATS[mat] and 'river'
                            or d.outside and 'surface' or 'pool'
                        local b = bodies[kind]
                        b.tiles = b.tiles + 1
                        b.volume = b.volume + fs
                        if fs >= 4 then b.deep = b.deep + 1 end
                        if bz < b.z1 then b.z1 = bz end
                        if bz > b.z2 then b.z2 = bz end
                        if d.water_salt then b.salt = b.salt + 1 end
                        if d.water_stagnant then b.stagnant = b.stagnant + 1 end
                        if not d.hidden then b.seen = b.seen + 1 end
                        local dist = math.max(math.abs(x - mid.x), math.abs(y - mid.y))
                            + 2 * math.abs(bz - mid.z_mid)
                        if not b.nearest or dist < b.nearest.d then
                            b.nearest = {x = x, y = y, z = bz, d = dist, depth = fs}
                        end
                    end
                    local cls = feat and 'c' or RIVER_MATS[mat] and 'f'
                        or (d.outside and d.water_salt) and 's' or d.outside and 'l' or 'u'
                    if not frozen then add_cell(job, cls, bx, by, bz, x, y, d, mat) end
                end
            elseif d.water_table then
                if near then aquifer[bz] = (aquifer[bz] or 0) + 1 end
                add_cell(job, 'a', bx, by, bz, x, y, d)
            end
        end
    end
    if lname then
        -- (the cells of this block learn their cavern's name)
        for _, cls in ipairs({'c', 'mc'}) do
            local c = job.cells[((CLASS_ID[cls] * job.Z + bz) * job.nby + by) * job.nbx + bx]
            if c then c.cavern = lname; c.cavern_found = layer and layer.found or false end
        end
    end
    return ground
end

-- (0.105.38 review) a block of the near box (scanned in the near phase:
-- the whole-map phases skip it)
local function in_near(job, bx, by, bz)
    return bz >= job.z1 and bz <= job.z2 and bx >= job.bx1 and bx <= job.bx2 and by >= job.by1 and by <= job.by2
end

-- the scan's lowest level: the map's floor, or a little under the magma
-- sea's top once it is found (nothing under it matters), never above the
-- near box's floor
local function z_floor(job)
    if job.sea_top then return math.max(0, math.min(job.z1, job.sea_top - SEA_BELOW)) end
    return 0
end

-- Union-find over the cells: one body a connected run of one class.
local function find(c)
    local r = c
    while r.up ~= r do r = r.up end
    while c.up ~= r do local nx = c.up; c.up = r; c = nx end
    return r
end

local function union(a, b)
    local ra, rb = find(a), find(b)
    if ra ~= rb then rb.up = ra end
end

-- Pure-ish: the tile at (x, y, z) for the reach walk: designation, shape,
-- the block's layer name (nil when the block is missing)
local function tile_at(job, x, y, z)
    if x < 0 or y < 0 or z < 0 or x >= job.W or y >= job.H or z >= job.Z then return nil end
    local block = dfhack.maps.getBlock(x // 16, y // 16, z)
    if not block then return nil end
    local d = block.designation[x % 16][y % 16]
    local shape = tt_names(block.tiletype[x % 16][y % 16])
    local gid = block.global_feature
    local layer = job.names[gid]
    return d, shape, {name = layer and layer.name or nil, kind = fkind(job, gid)}
end

-- (0.105.38 review) the 8 tiles round (x, y, z) and the one above it: an
-- aquifer's ('aquifer'), or liquid other than the body's own near its end
-- ('magma' / 'water'), or nil. A dug tile beside either seeps or floods.
local NB = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {1, 1, 0}, {1, -1, 0}, {-1, 1, 0}, {-1, -1, 0}, {0, 0, 1}}
local function wet_beside(job, x, y, z, n, magma)
    local aq
    for _, o in ipairs(NB) do
        local nx, ny, nz = x + o[1], y + o[2], z + o[3]
        local d = tile_at(job, nx, ny, nz)
        if d then
            if (d.flow_size or 0) > 0 then
                local is_magma = d.liquid_type == true or d.liquid_type == 1
                local own = is_magma == magma and (nz == n.z or nz == n.z + 1)
                    and math.max(math.abs(nx - n.x), math.abs(ny - n.y)) <= 16
                if not own then return is_magma and 'magma' or 'water' end
            elseif d.water_table then aq = 'aquifer' end
        end
    end
    return aq
end

-- (0.105.38) The reach estimate of one body: a shaft at the fort's middle
-- from the fort's levels to the body's level, then an L-shaped tunnel to its
-- nearest tile (either way round), each tile safe: no other liquid, no
-- aquifer, no cavern, no magma pipe, no open sky. {reach} or {reach_through,
-- opens_cavern, aquifer, blocked}.
local function reach_of(job, b)
    local n = b.nearest
    if not n then return {} end
    local mid = job.mid
    local magma = b.kind == 'magma'
    local sea_body = magma and b.magma == 'sea'
    local zf = math.max(mid.z_low, math.min(mid.z_high, n.z))
    local best
    for _, xfirst in ipairs({true, false}) do
        local steps, issue = 0, {}
        local done = false
        local function visit(x, y, z)
            if done then return end
            steps = steps + 1
            local d, shape, layer = tile_at(job, x, y, z)
            if not d then issue.blocked = issue.blocked or 'off the known map' return end
            if (d.flow_size or 0) > 0 then
                local is_magma = d.liquid_type == true or d.liquid_type == 1
                if (x == n.x and y == n.y and z == n.z) or (is_magma == magma and z == n.z
                        and math.max(math.abs(x - n.x), math.abs(y - n.y)) <= 16) then
                    done = true                          -- the body (its own tiles near the end)
                    return
                end
                issue.blocked = issue.blocked or (is_magma and 'magma' or 'other water') .. ' on the way'
                return
            end
            if d.water_table then issue.aquifer = true end
            -- (0.105.38 review) a global feature by its type: the sea or the
            -- underworld block the way; a cavern (or one of unknown kind) is
            -- opened by it
            local deep = layer.kind == 'sea' or layer.kind == 'underworld'
            if d.feature_global and not deep then
                issue.opens_cavern = issue.opens_cavern or layer.name or 'a cavern'
            elseif d.feature_global and sea_body and layer.kind == 'sea' then
                -- (0.105.38 review) the sea's own layer, on the way to the sea itself
            elseif d.feature_local or d.feature_global then
                issue.blocked = issue.blocked or 'a deep feature (a pipe or the sea) on the way'
            end
            -- (0.105.38 review) a dug tile with an aquifer or other liquid beside or above it
            local wb = wet_beside(job, x, y, z, n, magma)
            if wb == 'aquifer' then issue.aquifer = true
            elseif wb then issue.blocked = issue.blocked or (wb == 'magma' and 'magma' or 'other water') .. ' beside the way' end
            if shape == 'EMPTY' and d.outside then issue.blocked = issue.blocked or 'open sky on the way' end
        end
        local step_z = n.z >= zf and 1 or -1
        for z = zf, n.z, step_z do
            if z ~= zf then visit(mid.x, mid.y, z) end
        end
        local x, y = mid.x, mid.y
        local function walk(tx, ty)
            while (x ~= tx or y ~= ty) and not done do
                if x ~= tx then x = x + (tx > x and 1 or -1) else y = y + (ty > y and 1 or -1) end
                visit(x, y, n.z)
            end
        end
        if xfirst then walk(n.x, mid.y); walk(n.x, n.y) else walk(mid.x, n.y); walk(n.x, n.y) end
        local safe = not issue.blocked and not issue.aquifer and not issue.opens_cavern
        local r = safe and {reach = steps} or {reach_through = not issue.blocked and steps or nil,
                                                opens_cavern = issue.opens_cavern, aquifer = issue.aquifer,
                                                blocked = issue.blocked}
        local rank = safe and 0 or (issue.blocked and 2 or 1)
        if not best or rank < best.rank or (rank == best.rank and steps < best.steps) then
            best = {rank = rank, steps = steps, r = r}
        end
    end
    local r = best.r
    -- a body in a cavern: reaching it opens that cavern
    if b.cavern and (b.kind == 'cavern' or b.magma == 'cavern') then
        r.opens_cavern = r.opens_cavern or b.cavern
        if r.reach then r.reach_through, r.reach = r.reach, nil end
    end
    return r
end

-- the cells joined into bodies, summed and named
local function gather(job)
    local roots, out = {}, {}
    for _, c in ipairs(job.list) do
        local r = find(c)
        local b = roots[r]
        if not b then
            b = {cls = c.cls, tiles = 0, volume = 0, deep = 0, salt = 0, stagnant = 0, seen = 0, river = 0, brook = 0,
                 outside = 0, z1 = c.z, z2 = c.z}
            roots[r] = b
            table.insert(out, b)
        end
        for _, f in ipairs({'tiles', 'volume', 'deep', 'salt', 'stagnant', 'seen', 'river', 'brook', 'outside'}) do
            b[f] = b[f] + c[f]
        end
        if c.z < b.z1 then b.z1 = c.z end
        if c.z > b.z2 then b.z2 = c.z; b.top = nil end
        if c.z == b.z2 and (not b.top or c.td < b.top.td) then
            b.top = {x = c.tx, y = c.ty, z = c.z, td = c.td, outside = c.tout}
        end
        if not b.nearest or c.nd < b.nearest.d or (c.nd == b.nearest.d and c.nm < b.nearest.m) then
            b.nearest = {x = c.nx, y = c.ny, z = c.z, d = c.nd, depth = c.ndepth, m = c.nm}
        end
        if c.cavern then b.cavern, b.cavern_found = c.cavern, c.cavern_found end
    end
    for _, b in ipairs(out) do
        local cls = b.cls
        if cls == 'f' then b.kind = b.brook > b.river and 'brook' or 'river'; b.flow = 'flowing'
        elseif cls == 's' then b.kind = 'sea'
        elseif cls == 'l' then
            b.kind = b.tiles >= LAKE_TILES and 'lake' or b.tiles >= POND_TILES and 'pond' or 'pool'
            b.flow = 'stagnant'
        elseif cls == 'u' then b.kind = 'pool'; b.flow = 'stagnant'; b.underground = true
        elseif cls == 'c' then b.kind = 'cavern'
        elseif cls == 'a' then b.kind = 'aquifer'
        elseif cls == 'i' then b.kind = 'ice'; b.flow = 'frozen'    -- (0.105.38 review)
        else
            b.kind = 'magma'
            b.magma = cls == 'mp' and ((b.top and b.top.outside) and 'volcano' or 'pipe')
                or cls == 'mc' and 'cavern' or cls == 'ms' and 'sea' or cls == 'mo' and 'surface' or 'pool'
        end
        local t = math.max(1, b.tiles)
        b.salt_share = math.floor(100 * b.salt / t + 0.5)
        b.stagnant_share = math.floor(100 * b.stagnant / t + 0.5)
        b.seen_share = math.floor(100 * b.seen / t + 0.5)
        b.d = b.nearest and b.nearest.d or nil
        if b.nearest then b.nearest.m = nil end
        if b.top then b.top.td, b.top.outside = nil, nil end
        if b.kind == 'aquifer' or b.kind == 'cavern' or b.kind == 'ice' then b.top = nil end
        b.salt, b.stagnant, b.seen, b.river, b.brook, b.outside, b.cls = nil, nil, nil, nil, nil, nil, nil
        if b.kind ~= 'magma' and b.kind ~= 'aquifer' and b.kind ~= 'ice' and b.volume == 0 then b.volume = nil end
    end
    return out
end

-- the report's list: every flowing body (to FLOWING_MAX), one magma body of
-- each kind then the nearest ones (to MAGMA_MAX), the nearest of every other
-- kind, then the nearest and the biggest by turns; nearest first
local function pick(all)
    local by_d = {}
    for _, b in ipairs(all) do table.insert(by_d, b) end
    table.sort(by_d, function(a, b) return (a.d or math.huge) < (b.d or math.huge) end)
    local by_size = {}
    for _, b in ipairs(all) do table.insert(by_size, b) end
    table.sort(by_size, function(a, b) return a.tiles > b.tiles end)
    local chosen, n = {}, 0
    local function take(b)
        if not chosen[b] and n < WATERS_MAX then chosen[b] = true; n = n + 1 end
    end
    local flowing, magma, kinds, mkinds = 0, 0, {}, {}
    for _, b in ipairs(by_d) do
        if b.flow == 'flowing' and flowing < FLOWING_MAX then take(b); flowing = flowing + 1 end
    end
    for _, b in ipairs(by_d) do
        if b.kind == 'magma' and not mkinds[b.magma] and magma < MAGMA_MAX then
            mkinds[b.magma] = true; take(b); magma = magma + 1
        end
    end
    for _, b in ipairs(by_d) do
        if b.kind == 'magma' and magma < MAGMA_MAX and not chosen[b] then take(b); magma = magma + 1 end
    end
    for _, b in ipairs(by_d) do
        if b.kind ~= 'magma' and not kinds[b.kind] then kinds[b.kind] = true; take(b) end
    end
    local i, j = 1, 1
    while n < WATERS_MAX and (i <= #by_d or j <= #by_size) do
        while i <= #by_d and (chosen[by_d[i]] or by_d[i].kind == 'magma') do i = i + 1 end
        if i <= #by_d then take(by_d[i]) end
        while j <= #by_size and (chosen[by_size[j]] or by_size[j].kind == 'magma') do j = j + 1 end
        if j <= #by_size then take(by_size[j]) end
    end
    local out = {}
    for _, b in ipairs(by_d) do if chosen[b] then table.insert(out, b) end end
    return out
end

SLICE_MARGIN = 0.01     -- (0.105.38) a slice stops this much short of its time (a block's work and the reply fit in it)
function survey_step(job, seconds)
    local deadline = os.clock() + math.max(0, seconds - math.min(SLICE_MARGIN, seconds / 10))
    local first = true
    local function time_up()
        if first then first = false return false end    -- (at least one block a call)
        return os.clock() > deadline
    end
    local per_level = job.nbx * job.nby
    -- (0.105.38 review) the near box first, its blocks level by level from
    -- the top down (as before 0.105.38): its result is saved before the
    -- whole map goes on (scan_step), so near water never waits for it
    if job.phase == 'near' then
        local nw = job.bx2 - job.bx1 + 1
        local per_near = nw * (job.by2 - job.by1 + 1)
        while job.z >= job.z1 do
            if time_up() then return false end
            scan_block(job, job.bx1 + job.bi % nw, job.by1 + job.bi // nw, job.z, false, true)
            job.bi = job.bi + 1
            if job.bi >= per_near then job.bi, job.z = 0, job.z - 1 end
        end
        job.near_ready = true
        job.bi, job.z, job.ground = 0, job.z2 + 1, false
        job.phase = 'up'
        if job.z > job.Z - 1 then job.phase, job.z = 'down', job.z2 end
    end
    -- the levels over the start, up to the last one with ground on it
    while job.phase == 'up' do
        if time_up() then return false end
        local bx, by = job.bi % job.nbx, job.bi // job.nbx
        if scan_block(job, bx, by, job.z, not job.ground, false) then job.ground = true end
        job.bi = job.bi + 1
        if job.bi >= per_level then
            job.bi = 0
            if not job.ground or job.z >= job.Z - 1 then
                if job.ground then job.ztop = job.z end
                job.phase, job.z = 'down', job.z2
            else
                job.ztop = job.z
                job.z, job.ground = job.z + 1, false
            end
        end
    end
    -- then down, the whole map, to the magma sea's top
    while job.phase == 'down' do
        if job.z < z_floor(job) then job.phase, job.ci = 'join', 1 break end
        local bx, by = job.bi % job.nbx, job.bi // job.nbx
        -- (0.105.38 review) the near box's blocks were scanned first
        if not in_near(job, bx, by, job.z) then
            if time_up() then return false end
            scan_block(job, bx, by, job.z, false, false)
        end
        job.bi = job.bi + 1
        if job.bi >= per_level then job.bi, job.z = 0, job.z - 1 end
    end
    -- the cells joined (each with its neighbours of the same class)
    if job.phase == 'join' then
        if job.ci == 1 then for _, c in ipairs(job.list) do c.up = c end end
        local cells, nbx, nby, Z = job.cells, job.nbx, job.nby, job.Z
        while job.ci <= #job.list do
            if job.ci % 64 == 0 and time_up() then return false end
            local c = job.list[job.ci]
            local cid = CLASS_ID[c.cls]
            for dz = -1, 1 do
                local z = c.z + dz
                if z >= 0 and z < Z then
                    for dy = -1, 1 do
                        local y = c.by + dy
                        if y >= 0 and y < nby then
                            for dx = -1, 1 do
                                local x = c.bx + dx
                                if x >= 0 and x < nbx then
                                    local o = cells[((cid * Z + z) * nby + y) * nbx + x]
                                    if o and o ~= c then union(c, o) end
                                end
                            end
                        end
                    end
                end
            end
            job.ci = job.ci + 1
        end
        local all = gather(job)
        job.found = #all
        job.waters = pick(all)
        job.phase, job.ri = 'reach', 1
        -- (0.105.38 review) the blocks a river runs through (kept in the save,
        -- RIVER_BLOCKS_MAX at most) and the ice's: ice where a river was seen
        -- is a frozen river, other ice (a glacier, a frozen lake) is not
        job.river_blocks, job.ice_blocks = {}, {}
        for _, c in ipairs(job.list) do
            local k = c.bx .. ',' .. c.by .. ',' .. c.z
            if c.cls == 'f' and #job.river_blocks < RIVER_BLOCKS_MAX then table.insert(job.river_blocks, k)
            elseif c.cls == 'i' then job.ice_blocks[k] = true end
        end
        job.cells, job.list = nil, nil
    end
    -- each body's reach, a body a slice at least
    while job.phase == 'reach' do
        local b = job.waters[job.ri]
        if not b then job.phase = 'done' break end
        if time_up() then return false end
        if b.kind ~= 'aquifer' and b.kind ~= 'ice' then
            for k, v in pairs(reach_of(job, b)) do b[k] = v end
        end
        job.ri = job.ri + 1
    end
    return true
end

local function levels(t)
    local lo, hi, n = math.huge, -math.huge, 0
    for z, c in pairs(t) do
        n = n + c
        if z < lo then lo = z end
        if z > hi then hi = z end
    end
    if n == 0 then return nil end
    return {z1 = lo, z2 = hi, tiles = n}
end

-- (0.105.38 review) The near box's result (the fields of the survey before
-- 0.105.38), from the near phase alone: saved as soon as that phase is done
-- (the whole map goes on after it). The job's sums are copied, not changed.
function finish_near(job)
    local bodies = job.bodies
    local out = {ok = true, middle = job.mid, box = {x1 = job.x1, x2 = job.x2, y1 = job.y1, y2 = job.y2,
                                                     z1 = job.z1, z2 = job.z2},
                 bodies = {}, aquifer = nil, magma = nil}
    for _, kind in ipairs({'river', 'surface', 'cavern', 'pool'}) do
        local b = bodies[kind]
        if b.tiles > 0 then
            local c = {}
            for k, v in pairs(b) do c[k] = v end
            c.salt_share = math.floor(100 * b.salt / b.tiles + 0.5)
            c.stagnant_share = math.floor(100 * b.stagnant / b.tiles + 0.5)
            -- (seen_share: hidden tiles are counted all the same, the
            -- review's decision; the share says how much of it is known)
            c.seen_share = math.floor(100 * b.seen / b.tiles + 0.5)
            c.salt, c.stagnant, c.seen = nil, nil, nil
            if b.nearest then c.nearest = {} for k, v in pairs(b.nearest) do c.nearest[k] = v end end
            table.insert(out.bodies, c)
        end
    end
    out.aquifer = levels(job.aquifer)
    out.magma = levels(job.magma)
    if out.magma and job.magma_top then   -- (0.105.0)
        local t = job.magma_top
        out.magma.top_nearest = {x = t.x, y = t.y, z = t.z, d = t.d}
    end
    out.ice = levels(job.frozen)          -- (0.105.38 review) ice under the sky near the fort
    return out
end

-- The whole survey: the near box's result and the whole map's. `prev`: the
-- survey before (a river it saw, now ice: a frozen river).
function finish_survey(job, prev)
    local out = finish_near(job)
    -- (0.105.38) the whole map
    out.map = {w = job.W, h = job.H, z = job.Z}
    out.map_box = {x1 = 0, x2 = job.W - 1, y1 = 0, y2 = job.H - 1, z1 = z_floor(job), z2 = job.ztop}
    out.waters, out.waters_found = job.waters or {}, job.found or 0
    -- (0.105.38) the nearest flowing water, and the nearest magma, in short
    local ice = out.ice ~= nil
    for _, b in ipairs(out.waters) do
        if b.flow == 'flowing' and not out.nearest_flowing then
            out.nearest_flowing = {kind = b.kind, d = b.d, reach = b.reach, x = b.nearest.x, y = b.nearest.y,
                                   z = b.nearest.z}
        end
        if b.kind == 'ice' then ice = true end
    end
    if job.sea_top then out.magma_sea_top = job.sea_top end
    -- (0.105.38 review) a river seen by this survey or one before it, and
    -- now ice (a winter survey): a frozen river, still a river for the
    -- choice of a water wheel over a windmill
    local river_now = out.nearest_flowing ~= nil
    for _, b in ipairs(out.bodies) do if b.kind == 'river' then river_now = true end end
    -- (review) only ice in a block the river ran through before counts
    local before = type(prev) == 'table' and type(prev.river_blocks) == 'table' and prev.river_blocks or {}
    local on_river = false
    if ice and not river_now then
        for _, k in ipairs(before) do if (job.ice_blocks or {})[k] then on_river = true break end end
        -- (third review) a save from before river_blocks (river_seen, no
        -- blocks): any ice counts, as it did then
        if not on_river and type(prev) == 'table' and prev.river_seen == true and type(prev.river_blocks) ~= 'table' then
            on_river = true
        end
    end
    if on_river then out.frozen_river = true end
    out.river_seen = river_now or out.frozen_river == true or nil
    if river_now then out.river_blocks = job.river_blocks
    elseif on_river and type(prev.river_blocks) == 'table' then out.river_blocks = before end
    return out
end

-- (test-only) the whole survey at once: the game uses scan_step (in slices)
function survey()
    local job, why = start_survey()
    if not job then return {ok = false, error = why} end
    survey_step(job, 1e9)
    return finish_survey(job, last())
end

-- (test-only) the whole survey at once, kept in the save with the tick it
-- was made (the game uses scan_step)
function scan(now_tick)
    local r = survey()
    if r.ok then
        r.tick = now_tick
        U.site_put(WATER_KEY, r)
    end
    return r
end

-- One slice of a survey (`seconds` of scanning at most): {done = false,
-- level} while it goes on (the next call carries on), or the finished
-- survey (kept in the save) when done.
SLICE_SECONDS = 0.15
JOB = JOB or nil

-- (0.105.33) the fort a sliced survey belongs to (the world's save and the
-- site): a survey begun in one fort is never finished into another's save
local function fort_id()
    local ok, v = pcall(function()
        return tostring(df.global.world.cur_savegame.save_dir) .. ':' .. tostring(df.global.plotinfo.site_id)
    end)
    return ok and v or nil
end

-- (0.105.33) the half-done survey belongs to the fort unloaded
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-water'] = function(sc)
        if sc == SC_MAP_UNLOADED then JOB = nil end
    end
end

-- how much is left, in levels (roughly: the levels still to scan, 1 while
-- the bodies are joined and reached)
local function left_of(job)
    if job.phase == 'near' then return (job.z - job.z1 + 1) + (job.Z - job.z2) + (job.z2 - z_floor(job) + 1) end
    if job.phase == 'up' then return (job.Z - job.z) + (job.z2 - z_floor(job) + 1) end
    if job.phase == 'down' then return math.max(1, job.z - z_floor(job) + 1) end
    return 1
end

-- (0.105.38 review) the near box's result into the save, the whole map's
-- fields (and the cistern's plan) of the survey before kept until this one's
-- whole map is done
local KEEP = {'map', 'map_box', 'waters', 'waters_found', 'nearest_flowing', 'magma_sea_top', 'cistern',
              'river_seen', 'frozen_river', 'river_blocks'}
function save_near(job, now_tick)
    local r = finish_near(job)
    local prev = last()
    if prev then for _, k in ipairs(KEEP) do if r[k] == nil then r[k] = prev[k] end end end
    r.waters_pending = true
    -- (0.105.38 review) the survey's tick stays the last whole survey's (none
    -- before: none), so a whole-map pass cut off (a save, a quit, the map
    -- unloaded) is begun again at once, not a season on; near_tick: this one's
    r.tick = prev and prev.tick or nil
    r.near_tick = now_tick
    U.site_put(WATER_KEY, r)
    return r
end

function scan_step(now_tick, seconds)
    if JOB and JOB.fort ~= fort_id() then JOB = nil end
    if JOB and (not JOB.phase or not JOB.fkinds) then JOB = nil end   -- (0.105.38) a half-done survey of an older kind
    if not JOB then
        local why
        JOB, why = start_survey()
        if not JOB then return {ok = false, error = why} end
        JOB.started = now_tick
        JOB.fort = fort_id()
    end
    if not survey_step(JOB, seconds or SLICE_SECONDS) then
        -- (0.105.38 review) the near box done: its result saved at once (the
        -- whole-map list of the survey before kept, `waters_pending` until
        -- the whole map is done)
        if JOB.near_ready and not JOB.near_saved then
            JOB.near_saved = true
            save_near(JOB, now_tick)
        end
        return {ok = true, done = false, level = JOB.z, phase = JOB.phase, left = left_of(JOB),
                near_done = JOB.near_saved or nil}
    end
    local r = finish_survey(JOB, last())
    JOB = nil
    r.tick = now_tick
    r.done = true
    U.site_put(WATER_KEY, r)
    return r
end

function scanning() return JOB ~= nil end

-- (0.105.38 third review) The report's copy of the last scan ({none} when
-- none): the save's fields but the river's blocks (kept in the save only)
REPORT_SKIP = {river_blocks = true}
function report_copy()
    local w = {}
    for k, v in pairs(last() or {none = true}) do
        if not REPORT_SKIP[k] then w[k] = v end
    end
    return w
end

-- The last scan (or nil): what the fort report shows.
function last()
    local d = U.site_get(WATER_KEY, nil)
    return type(d) == 'table' and d.ok and d or nil
end
