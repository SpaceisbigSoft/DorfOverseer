-- ai-util-dig: the dig guard (raw adamantine, the spire it stands in and the
-- underworld are never dug into: dig_forbidden, the deep map, the quickfort
-- dig check, the refusals kept for the report) and the report's deep_hazard
-- walk (sliced).
--
-- (r9) A part of ai-util, not a script of its own: ai-util.lua loads it into
-- its own environment, so every name here is reqscript('ai-util').name and
-- the helpers defined there and in the parts before it are in reach.

if not PARTS then qerror('ai-util-dig is a part of ai-util; run ai-util') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-util-dig'] = '0.105.69'   -- (0.105.26) bumped with BRIDGE_VERSION

-- --- the dig guard (0.105.40b) ----------------------------------------------------
--
-- Raw adamantine, the spire it stands in and the underworld under it end a
-- fort when dug into: the spire's hollow and the underworld's open floor
-- bring out what lives down there. No dig the AI marks may take such a tile,
-- one beside it (the 8 around on its level) or the one over or under it.
-- Every path that marks digging asks dig_forbidden first: quickfort's dig
-- blueprints (lua/ai-builder.lua quickfort_apply, so every level, hall, well,
-- cistern, way in, landmark, site check and gallery), the joins and widenings
-- (ai-joins.lua), the ore veins, drifts and quarries (ai-industry.lua), and
-- DFHack's dig-now (the cistern's and the water works' plugs).
--
-- dig_forbidden reads the tile itself, hidden or not (a guard, not a survey):
--   * a mineral vein whose stone is flagged DEEP_SPECIAL in the raws (raw
--     adamantine);
--   * a tile of a deep special feature: designation.feature_local in a block
--     whose local feature is a deep_special_tube or deep_surface_portal;
--   * a tile of the underworld: designation.feature_global in a block whose
--     global feature is underworld_from_layer;
--   * map special stone (tiletype material FEATURE) of such a feature, and
--     the underworld's own HFS tiles.
-- Each block and tile is read once per game tick (the memo); the raws once.
-- The Rules switch `mine_adamantine` is kept for a sealed breach plan that
-- isn't built yet: on or off, these tiles are refused.

-- (0.105.40b fix) the map's deep floor and deep levels (DEEP_MAP), once per
-- loaded map: the floor is the top level of the lowest cavern (else the
-- magma sea's top, else the spire's top); a deep level holds a block of a
-- tube or portal, the underworld, a DEEP_SPECIAL vein, a layer of unknown
-- kind or one that could not be read. dig_forbidden answers at once (nil)
-- for a tile above the floor whose levels z-1..z+1 hold nothing deep; and
-- where the guard cannot read a tile at or below the floor or beside a deep
-- level it refuses it (GUARD_ERR) instead of letting it be dug. With no
-- floor known (a test's map) both stay as before: every tile read, an
-- error let by.
-- (0.105.40b fix) 'F' (carve a fortification) cuts the tile too; a key the
-- guard does not know is refused at a deep level (DIG_KEYS_SAFE: the keys
-- that never dig).
DIG_KEYS = {d = true, h = true, u = true, j = true, i = true, r = true, F = true}   -- quickfort keys that dig
DIG_KEYS_SAFE = {x = true, s = true, e = true, T = true, v = true, M = true, t = true, p = true,
                 z = true, o = true, c = true, a = true, b = true, m = true}
GUARD_ERR = 'the dig guard could not read the tile'
-- refusals since the map loaded, each tile counted once (tiles: the set)
DIG_GUARD = DIG_GUARD or {refused = 0, by = {}, last = {}, tiles = {}}
DIG_GUARD_LAST_MAX = 5
DIG_GUARD_TILES_MAX = 20000  -- tiles remembered for the once-per-tile count (past it: counted again)

local DEEP_INORG = {}        -- inorganic index -> DEEP_SPECIAL (the raws never change while the game runs)
local GMEMO = nil            -- {tick, map, blocks, tiles, errs}
DEEP_MAP = nil               -- {key, ok, floor, levels = {[z] = true}, at}

local function deep_inorganic(idx)
    if idx == nil then return false end
    local v = DEEP_INORG[idx]
    if v ~= nil then return v end
    local ok, inorg = pcall(function() return df.global.world.raws.inorganics.all[idx] end)
    if not (ok and inorg) then ok, inorg = pcall(function() return df.global.world.raws.inorganics[idx] end) end
    v = false
    if ok and inorg then
        local okf, f = pcall(function() return inorg.flags.DEEP_SPECIAL end)
        v = okf and f == true
    end
    DEEP_INORG[idx] = v
    return v
end
is_deep_inorganic = deep_inorganic

-- A feature init's kind: 'tube', 'under', 'cavern', 'magma' or 'other'; nil unread
local function feature_kind(f)
    if not f then return nil end
    local okt, t = pcall(function() return f:getType() end)
    if okt and t ~= nil then
        local FT = df.feature_type
        if t == FT.deep_special_tube or t == FT.deep_surface_portal then return 'tube' end
        if t == FT.underworld_from_layer then return 'under' end
        if t == FT.subterranean_from_layer then return 'cavern' end
        if t == FT.magma_core_from_layer then return 'magma' end
        return 'other'
    end
    local function is(name)
        local ok, v = pcall(function() return df[name]:is_instance(f) end)
        return ok and v == true
    end
    if is('feature_init_deep_special_tubest') or is('feature_init_deep_surface_portalst') then return 'tube' end
    if is('feature_init_underworld_from_layerst') then return 'under' end
    if is('feature_init_subterranean_from_layerst') then return 'cavern' end
    if is('feature_init_magma_core_from_layerst') then return 'magma' end
    return nil
end

-- The map's features (the fallback when DFHack's init lookups are missing):
-- local ones keyed by (region x, region y, index) where the map lists their
-- region (an index alone names a different feature in each region tile),
-- and by index alone (any_tube: a tube anywhere under that index); global
-- ones by index ({[gid] = kind}). err: the list could not be read.
local function deep_features()
    local out = {tube = {}, tube_at = {}, under = {}, global = {}, gkind = {}}
    local ok = pcall(function()
        local F = df.global.world.features
        for i, f in ipairs(F.map_features) do
            local gid = F.feature_global_idx[i]
            local lid = F.feature_local_idx[i]
            local kind = feature_kind(f)
            if gid ~= nil and gid >= 0 then
                out.global[gid] = true
                out.gkind[gid] = kind
                if kind == 'under' then out.under[gid] = true end
            end
            if lid ~= nil and lid >= 0 then
                local tube = kind == 'tube'
                if tube then out.tube[lid] = true end
                local okp, fx, fy = pcall(function() return F.feature_x[i], F.feature_y[i] end)
                if okp and fx ~= nil and fy ~= nil then
                    local k = fx .. ',' .. fy .. ',' .. lid
                    out.tube_at[k] = out.tube_at[k] or tube
                end
            end
        end
    end)
    if not ok then out.err = true end
    return out
end

-- Kinds read by index, shared for a map (a cache: {ltube = {}, gkind = {}, F})
local function new_kinds() return {ltube = {}, gkind = {}} end

-- Is the block's local feature a tube or portal? true / false; nil when it has
-- none; 'err' when it could not be read.
local function block_tube(block, K)
    local lf = block.local_feature
    if lf == nil or lf < 0 then return nil end
    local rp = block.region_pos
    local okr, rx, ry = pcall(function() return rp.x, rp.y end)
    local k = (okr and rx or '?') .. ',' .. (okr and ry or '?') .. ',' .. lf
    local v = K.ltube[k]
    if v ~= nil then return v end
    local kind
    local okl = pcall(function() kind = feature_kind(dfhack.maps.getLocalInitFeature(rp, lf)) end)
    if okl and kind then
        v = kind == 'tube'
    else
        K.F = K.F or deep_features()
        local F = K.F
        if F.tube_at[k] ~= nil then v = F.tube_at[k]
        elseif F.err then v = 'err'
        else v = F.tube[lf] == true end         -- by index alone: a tube anywhere under it counts
    end
    K.ltube[k] = v
    return v
end

-- The kind of the block's global feature ('under', 'cavern', 'magma', 'other'),
-- nil when it has none or its layer is unknown; 'err' when it could not be read
local function block_global(block, K)
    local gf = block.global_feature
    if gf == nil or gf < 0 then return nil end
    local v = K.gkind[gf]
    if v ~= nil then return v or nil end
    local kind
    local okg = pcall(function() kind = feature_kind(dfhack.maps.getGlobalInitFeature(gf)) end)
    if okg and kind then
        v = kind
    else
        K.F = K.F or deep_features()
        local F = K.F
        if F.gkind[gf] then v = F.gkind[gf]
        elseif F.global[gf] then v = 'other'
        elseif F.err then v = 'err'
        else v = false end                      -- a layer the map doesn't list: unknown
    end
    K.gkind[gf] = v
    return v or nil
end

-- Does the block hold a DEEP_SPECIAL vein? {[lx * 16 + ly] = true} or nil
local function block_deep_veins(block)
    local deep
    for _, ev in ipairs(block.block_events) do
        if df.block_square_event_mineralst:is_instance(ev) and deep_inorganic(ev.inorganic_mat) then
            deep = deep or {}
            for lx = 0, 15 do
                for ly = 0, 15 do
                    if dfhack.maps.getTileAssignment(ev.tile_bitmask, lx, ly) then deep[lx * 16 + ly] = true end
                end
            end
        end
    end
    return deep
end

-- Which map is loaded (its region and size): the deep map is kept for it
function dig_guard_map_key()
    local ok, k = pcall(function()
        local m = df.global.world.map
        return ('%s,%s,%s:%s,%s,%s'):format(tostring(m.region_x), tostring(m.region_y), tostring(m.region_z),
                                           tostring(m.x_count), tostring(m.y_count), tostring(m.z_count))
    end)
    return ok and k or 'map'
end

-- The walk: every block once. ok false when the blocks could not be walked.
local function build_deep_map(key)
    local dm = {key = key, ok = false, levels = {}}
    local K = new_kinds()
    local caverns, magma_top, tube_top = {}, nil, nil
    local hz = {}
    local ok = pcall(function()
        for _, block in ipairs(df.global.world.map.map_blocks) do
            local z = block.map_pos.z
            local deep = false
            local okb = pcall(function()
                local t = block_tube(block, K)
                if t == true or t == 'err' then deep = true end
                if t == true and (not tube_top or z > tube_top) then tube_top = z end
                local g = block_global(block, K)
                if g == 'under' then
                    deep = true
                elseif g == 'cavern' then
                    local c = caverns[block.global_feature]
                    if not c then c = {lo = z, hi = z}; caverns[block.global_feature] = c end
                    if z < c.lo then c.lo = z end
                    if z > c.hi then c.hi = z end
                elseif g == 'magma' then
                    if not magma_top or z > magma_top then magma_top = z end
                elseif g == 'err' or (g == nil and block.global_feature ~= nil and block.global_feature >= 0) then
                    deep = true                 -- a layer of unknown kind
                end
                local veins = block_deep_veins(block)
                if veins then deep = true end
                -- (0.105.46, I6) the blocks deep_hazard reads: a deep vein, the
                -- spire's tube, the underworld (under: nothing else in it)
                if veins or t == true or g == 'under' then
                    local p = block.map_pos
                    hz[#hz + 1] = {p.x, p.y, z, under = (g == 'under' and not veins and t ~= true) or nil}
                end
            end)
            if not okb then
                deep = true
                local okp, p = pcall(function() return block.map_pos end)
                if okp and p then hz[#hz + 1] = {p.x, p.y, z} end       -- (I6) read again by the hazard walk
            end
            if deep then dm.levels[z] = true end
        end
    end)
    if not ok then return dm end
    dm.hz = hz
    local lowest
    for _, c in pairs(caverns) do
        if not lowest or c.lo < lowest.lo then lowest = c end
    end
    dm.floor = (lowest and lowest.hi) or magma_top or tube_top
    dm.ok = true
    dm.kinds = K
    return dm
end

-- The loaded map's deep floor and levels (built once per map; again a day
-- later when the walk failed)
function deep_map()
    local key = dig_guard_map_key()
    local dm = DEEP_MAP
    if dm and dm.key == key then
        if dm.ok then return dm end
        local okt, now = pcall(abs_tick)
        if not (okt and dm.at and now - dm.at >= TICKS_PER_DAY) then return dm end
    end
    dm = build_deep_map(key)
    local okt, now = pcall(abs_tick)
    dm.at = okt and now or nil
    DEEP_MAP = dm
    return dm
end

-- Is level z one the guard refuses on a read error: at or below the deep
-- floor, or within 1 level of a deep level (false with no deep floor known)
local function fail_closed(dm, z)
    if not (dm and dm.ok and dm.floor) then return false end
    if z <= dm.floor then return true end
    local L = dm.levels
    return L[z - 1] == true or L[z] == true or L[z + 1] == true
end
function dig_guard_fail_closed(z)
    local ok, v = pcall(function() return fail_closed(deep_map(), z) end)
    return ok and v == true
end

local function memo()
    local ok, t = pcall(abs_tick)
    t = ok and t or false
    if not GMEMO or GMEMO.tick ~= t then
        local okm, dm = pcall(deep_map)
        GMEMO = {tick = t, blocks = {}, tiles = {}, errs = {}, map = okm and dm or nil,
                 kinds = okm and dm and dm.kinds or new_kinds()}
    end
    return GMEMO
end

-- The memo dropped (a test, or a caller that just changed the map); the deep map with it.
function dig_guard_reset() GMEMO = nil; DEEP_MAP = nil end

-- (0.105.40b fix) everything the guard keeps, dropped when the map or world
-- unloads (the next map has its own raws, features and refusals)
function dig_guard_unload()
    DEEP_INORG = {}
    GMEMO = nil
    DEEP_MAP = nil
    DEEP_HAZARD_CACHE = nil
    UNDER_SEEN = {}          -- (0.105.46)
    DIG_GUARD = {refused = 0, by = {}, last = {}, tiles = {}}
end
if dfhack and dfhack.onStateChange then   -- (in the game a userdata-wrapped event, not a table)
    pcall(function()
        dfhack.onStateChange['ai-util-dig-guard'] = function(sc)
            if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then dig_guard_unload() end
        end
    end)
end

-- What a block holds of the deep: {tube, under, deep = {[lx * 16 + ly] = true}, err}, or false
local function block_info(m, x, y, z)
    local key = (x // 16) .. ',' .. (y // 16) .. ',' .. z
    local b = m.blocks[key]
    if b ~= nil then return b end
    b = false
    local okb, block = pcall(function() return dfhack.maps.getTileBlock(x, y, z) end)
    if not okb then
        b = {err = true}
    elseif block then
        b = {}
        local K = m.kinds
        local okt = pcall(function()
            local t = block_tube(block, K)
            if t == 'err' then b.err = true          -- unknown: its special stone still counts (deep_tile)
            elseif t ~= nil then b.tube = t end
        end)
        if not okt then b.err = true end
        local okg = pcall(function()
            local g = block_global(block, K)
            if g == 'err' then b.err = true
            elseif g ~= nil then b.under = (g == 'under') end
        end)
        if not okg then b.err = true end
        local okv = pcall(function() b.deep = block_deep_veins(block) end)
        if not okv then b.err = true end
    end
    m.blocks[key] = b
    return b
end

-- The tile's material name; nil and true when it could not be read
local function tile_material(x, y, z)
    local ok, name = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        local a = tt and df.tiletype.attrs[tt]
        return a and df.tiletype_material[a.material]
    end)
    if not ok then return nil, true end
    return name
end

-- Why this one tile is the deep's ('raw adamantine', 'the adamantine spire',
-- 'the underworld'), or nil; second: true when part of it could not be read
function deep_tile(x, y, z, m)
    m = m or memo()
    local k = x .. ',' .. y .. ',' .. z
    local t = m.tiles[k]
    if t ~= nil then return t or nil, m.errs[k] end
    t = false
    local err = false
    local b = block_info(m, x, y, z)
    if b then
        err = b.err == true
        local okd, d = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
        if not okd then err = true end
        if not (okd and d) then d = nil end
        local fl = d and d.feature_local
        local fg = d and d.feature_global
        if b.deep and b.deep[(x & 15) * 16 + (y & 15)] then t = 'raw adamantine'
        elseif b.tube and fl then t = 'the adamantine spire'
        elseif b.under and fg then t = 'the underworld'
        else
            local mat, merr = tile_material(x, y, z)
            if merr then err = true end
            if mat == 'HFS' then t = 'the underworld'
            -- local special stone: the tube's (not a block's whose local feature is known not to be one)
            elseif mat == 'FEATURE' and fl and b.tube ~= false then t = 'the adamantine spire'
            elseif mat == 'FEATURE' and fg and b.under ~= false then t = 'the underworld'
            end
        end
    end
    m.tiles[k] = t
    if err then m.errs[k] = true end
    return t or nil, err or nil
end

local function guard_read(x, y, z, m)
    local why, err = deep_tile(x, y, z, m)
    if why then return why end
    local anyerr = err
    for dy = -1, 1 do
        for dx = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                why, err = deep_tile(x + dx, y + dy, z, m)
                if why then return 'next to ' .. why end
                anyerr = anyerr or err
            end
        end
    end
    why, err = deep_tile(x, y, z - 1, m)
    if why then return 'over ' .. why end
    anyerr = anyerr or err
    why, err = deep_tile(x, y, z + 1, m)
    if why then return 'under ' .. why end
    return nil, anyerr or err
end

-- Why digging (x, y, z) is refused, or nil: the tile itself is the deep's,
-- or one of the 8 beside it on its level, or the one over or under it.
-- (0.105.40b fix) nil at once above the deep floor where levels z-1..z+1
-- hold nothing deep; GUARD_ERR where the guard could not read a tile at or
-- below the floor or beside a deep level.
function dig_forbidden(x, y, z)
    x, y, z = math.tointeger(x), math.tointeger(y), math.tointeger(z)
    if not (x and y and z) then return nil end
    local okm, m = pcall(memo)
    local dm = okm and m and m.map or nil
    if dm and dm.ok and dm.floor and z - 1 > dm.floor then
        local L = dm.levels
        if not (L[z - 1] or L[z] or L[z + 1]) then return nil end
    end
    local ok, why, err = false, nil, nil
    if okm and m then ok, why, err = pcall(guard_read, x, y, z, m) end
    if ok and why then return why end
    if (not ok or err) and fail_closed(dm, z) then
        local g = DIG_GUARD
        local k = x .. ',' .. y .. ',' .. z
        g.unreadable_tiles = g.unreadable_tiles or {}
        g.nunreadable = g.nunreadable or 0
        if not g.unreadable_tiles[k] then
            -- (fix41-ff) remembered up to DIG_GUARD_TILES_MAX tiles, as the
            -- refusals are (past it each is counted again, nothing kept)
            if g.nunreadable < DIG_GUARD_TILES_MAX then
                g.unreadable_tiles[k] = true
                g.nunreadable = g.nunreadable + 1
            end
            g.unreadable = (g.unreadable or 0) + 1
        end
        return GUARD_ERR
    end
    return nil
end

-- A refusal kept for the report (by: the path that asked). (0.105.40b fix)
-- each tile counted once (a path asking for it again every day is one
-- refusal, not one a day); by[path]: the tiles that path was refused.
function dig_refused(by, x, y, z, why)
    local g = DIG_GUARD
    g.tiles = g.tiles or {}
    g.ntiles = g.ntiles or 0
    g.by = g.by or {}
    g.asked = (g.asked or 0) + 1
    local path = by or '?'
    local k = tostring(x) .. ',' .. tostring(y) .. ',' .. tostring(z)
    local seen = g.tiles[k]
    if seen and seen[path] then return false end
    if not seen and g.ntiles < DIG_GUARD_TILES_MAX then seen = {}; g.tiles[k] = seen; g.ntiles = g.ntiles + 1 end
    if seen then seen[path] = true end
    g.by[path] = (g.by[path] or 0) + 1
    if seen and next(seen, next(seen)) ~= nil then return true end   -- the tile counted already (another path)
    g.refused = (g.refused or 0) + 1
    g.last = g.last or {}
    table.insert(g.last, {by = by, x = x, y = y, z = z, why = why})
    while #g.last > DIG_GUARD_LAST_MAX do table.remove(g.last, 1) end
    return true
end

-- The first refused tile of a list of {x, y, z} (or {x, y} with `z`):
-- why, the tile; nil when every tile may be dug. `by`: kept as a refusal.
function dig_check_tiles(tiles, z, by)
    for _, t in ipairs(tiles or {}) do
        local tz = t.z or z
        local why = dig_forbidden(t.x, t.y, tz)
        if why then
            if by then dig_refused(by, t.x, t.y, tz, why) end
            return why, {x = t.x, y = t.y, z = tz}
        end
    end
    return nil
end

-- Does a quickfort dig cell's text dig (d, h, u, j, i, r, F with a priority,
-- options or extents)? Its key's first letter, its base text (no extents),
-- and its extents' width and height. Second form (unknown = true): a key
-- the guard knows neither as digging nor as safe.
local function cell_parts(text)
    local key = text:match('^%s*(%a)')
    local w, h = text:match('%((%-?%d+)%s*x%s*(%-?%d+)%)%s*$')
    local base = text:gsub('%(%-?%d+%s*x%s*%-?%d+%)%s*$', '')
    return key, base, math.tointeger(tonumber(w)) or 1, math.tointeger(tonumber(h)) or 1
end
function dig_cell(text)
    if type(text) ~= 'string' then return nil end
    local key, base, w, h = cell_parts(text)
    if not key or not DIG_KEYS[key] then return nil end
    return key, base, w, h
end
function dig_cell_unknown(text)
    if type(text) ~= 'string' then return false end
    local key = text:match('^%s*(%S)')
    if not key then return false end
    return not (DIG_KEYS[key] or DIG_KEYS_SAFE[key])
end

local function span(a, n)
    if n == 0 then n = 1 end
    if n > 0 then return a, a + n - 1 end
    return a + n + 1, a
end

-- Quickfort dig data ({[z] = {[y] = {[x] = text}}}, at pos ox, oy, oz) with
-- the refused tiles taken out (a cell with extents split into its allowed
-- tiles when part of it is refused). A channel (h) is refused over a
-- refused tile too (it digs the tile under it). Returns the data (the same
-- table when nothing is refused), how many tiles were refused and the first
-- one's reason. `by`: refusals kept for the report (nil: a dry run, not kept).
-- (0.105.40b fix) a key the guard doesn't know is refused at a deep level.
function dig_guard_data(data, ox, oy, oz, by)
    local refused, first = 0, nil
    local out, changed = {}, false
    for z, grid in pairs(data) do
        local og = {}
        out[z] = og
        local deep_z = nil
        for y, row in pairs(grid) do
            for x, text in pairs(row) do
                local key, base, w, h = dig_cell(text)
                local function put(px, py, t)
                    og[py] = og[py] or {}
                    if og[py][px] == nil then og[py][px] = t end
                end
                if not key then
                    local unknown = dig_cell_unknown(text)
                    if unknown then
                        if deep_z == nil then deep_z = dig_guard_fail_closed(oz + z) end
                    end
                    if unknown and deep_z then
                        local _, _, uw, uh = cell_parts(text)
                        local x1, x2 = span(x, uw)
                        local y1, y2 = span(y, uh)
                        local why = ('an unknown dig key (%s) at a deep level'):format(text:match('^%s*(%S)'))
                        for ty = y1, y2 do
                            for tx = x1, x2 do
                                refused = refused + 1
                                if by then dig_refused(by, ox + tx, oy + ty, oz + z, why) end
                            end
                        end
                        first = first or why
                        changed = true
                    else
                        put(x, y, text)
                    end
                else
                    local x1, x2 = span(x, w)
                    local y1, y2 = span(y, h)
                    local bad = {}
                    local nbad = 0
                    for ty = y1, y2 do
                        for tx = x1, x2 do
                            local mx, my, mz = ox + tx, oy + ty, oz + z
                            local why = dig_forbidden(mx, my, mz)
                            if not why and key == 'h' then
                                why = dig_forbidden(mx, my, mz - 1)
                                if why then why = 'a channel down to a tile ' .. why end
                            end
                            if why then
                                bad[ty * 100000 + tx] = true
                                nbad = nbad + 1
                                refused = refused + 1
                                first = first or why
                                if by then dig_refused(by, mx, my, mz, why) end
                            end
                        end
                    end
                    if nbad == 0 then
                        put(x, y, text)
                    else
                        changed = true
                        for ty = y1, y2 do
                            for tx = x1, x2 do
                                if not bad[ty * 100000 + tx] then put(tx, ty, base) end
                            end
                        end
                    end
                end
            end
        end
    end
    if not changed then return data, 0, nil end
    return out, refused, first
end

-- (0.105.40b fix) the guard itself threw over a blueprint: its levels at or
-- below the deep floor (or beside a deep level) dropped whole, the rest let
-- by as before. Returns the data, how many cells were dropped, and why.
function dig_guard_drop_deep(data, ox, oy, oz, by)
    local out, dropped = {}, 0
    for z, grid in pairs(data) do
        if dig_guard_fail_closed(oz + z) then
            for y, row in pairs(grid) do
                for x, _ in pairs(row) do
                    dropped = dropped + 1
                    if by then pcall(dig_refused, by, ox + x, oy + y, oz + z, GUARD_ERR) end
                end
            end
        else
            out[z] = grid
        end
    end
    if dropped == 0 then return data, 0, nil end
    return out, dropped, GUARD_ERR
end

-- (0.105.40b) The report's `deep_hazard` (in the `deep` section): the raw
-- adamantine the dwarves have uncovered (tiles, the highest level it is on,
-- the nearest such tile to `near` {x, y, z}), whether the spire or the
-- underworld has been seen, and the guard's refusals since the map loaded.
-- Only uncovered tiles are counted: the AI doesn't look through rock (the
-- guard does: it refuses hidden ones too). Kept a game day.
-- (0.105.40b fix) the walk reads only the blocks that can hold any of it (a
-- local feature, a deep level, at or below the deep floor) when the deep
-- map is known; the spire by the block's own region and index (block_tube).
DEEP_HAZARD_CACHE = nil
-- (0.105.46, I6) the underworld once seen on this map (by the deep map's
-- key): its blocks aren't read again (a seen tile is never hidden again)
UNDER_SEEN = UNDER_SEEN or {}

-- One block of the hazard walk, counted into base; st.best_d: the nearest so far
local function hazard_block(block, base, K, near, st)
    local p = block.map_pos
    local evs = nil
    for _, ev in ipairs(block.block_events) do
        if df.block_square_event_mineralst:is_instance(ev) and deep_inorganic(ev.inorganic_mat) then
            evs = evs or {}
            table.insert(evs, ev)
        end
    end
    local tube = block_tube(block, K) == true
    if evs or tube then
        local des = block.designation
        for lx = 0, 15 do
            local row = des[lx]
            for ly = 0, 15 do
                local d = row[ly]
                if not d.hidden then
                    local hit = false
                    if tube and d.feature_local then hit = true; base.spire_seen = true end
                    if not hit and evs then
                        for _, ev in ipairs(evs) do
                            if dfhack.maps.getTileAssignment(ev.tile_bitmask, lx, ly) then hit = true; break end
                        end
                    end
                    if hit then
                        base.adamantine_seen = true
                        base.tiles = base.tiles + 1
                        local x, y, z = p.x + lx, p.y + ly, p.z
                        if not base.top_z or z > base.top_z then base.top_z = z end
                        if type(near) == 'table' and near.x and near.y and near.z then
                            local dd = math.abs(x - near.x) + math.abs(y - near.y) + 3 * math.abs(z - near.z)
                            if not st.best_d or dd < st.best_d then
                                st.best_d = dd
                                base.nearest = {x = x, y = y, z = z}
                            end
                        end
                    end
                end
            end
        end
    end
    if not base.underworld_seen and block_global(block, K) == 'under' then
        for lx = 0, 15, 5 do
            for ly = 0, 15, 5 do
                if not block.designation[lx][ly].hidden then base.underworld_seen = true end
            end
        end
    end
end

local function new_base()
    return {adamantine_seen = false, tiles = 0, spire_seen = false, underworld_seen = false}
end

local function hazard_slices()
    local ok, S = pcall(function() return reqscript('ai-slices') end)
    return ok and type(S) == 'table' and S.run and S or nil
end
HAZARD_SLICE_MS = 30     -- (0.105.46) a report's slice of the hazard walk
HAZARD_SLICE_ITEMS = nil -- (0.105.46) and its count of blocks (nil: time only; the tests set it)

function deep_hazard(near, mine_adamantine)
    local ok, now = pcall(abs_tick)
    local day = ok and (now // TICKS_PER_DAY) or nil
    local c = DEEP_HAZARD_CACHE
    local base
    if c and day and c.day == day then
        base = c.base
    else
        local okd, dm = pcall(deep_map)
        dm = okd and dm or nil
        local limit = dm and dm.ok and dm.floor and dm or nil
        local K = (dm and dm.kinds) or new_kinds()
        if limit and type(dm.hz) == 'table' then
            -- (0.105.46, I6) only the blocks that can hold any of it (listed by
            -- the deep map's walk, once per map), sliced over reports when
            -- lua/ai-slices.lua is there; the underworld's not again once seen
            local key = dm.key
            local function visit(acc, b)
                if b.under and (acc.base.underworld_seen or UNDER_SEEN[key]) then return end
                local block = dfhack.maps.getTileBlock(b[1], b[2], b[3])
                if not block then return end
                acc.walked = acc.walked + 1
                hazard_block(block, acc.base, K, near, acc)
            end
            local function init()
                local b = new_base()
                if UNDER_SEEN[key] then b.underworld_seen = true end
                return {base = b, walked = 0}
            end
            local function finish(acc)
                local b = acc.base
                if b.underworld_seen then UNDER_SEEN[key] = true end
                b.nearest_z = b.nearest and b.nearest.z or b.top_z
                b.deep_floor = dm.floor
                return {base = b, walked = acc.walked}
            end
            local S = hazard_slices()
            local r, st
            if S then
                r, st = S.run('deep_hazard', {key = key, now = ok and now or nil, ttl = TICKS_PER_DAY,
                                              whole_first = true, items = function() return dm.hz end,
                                              init = init, visit = visit, finish = finish,
                                              max_ms = HAZARD_SLICE_MS, max_items = HAZARD_SLICE_ITEMS})
            end
            if not r then
                local acc = init()
                for _, b in ipairs(dm.hz) do pcall(visit, acc, b) end
                r, st = finish(acc), 'done'
            end
            base = r.base
            -- a pass under way: the last whole one is sent, and the next report goes on
            DEEP_HAZARD_CACHE = {day = st ~= 'partial' and day or nil, base = base, walked = r.walked,
                                 status = st}
        else
            base = new_base()
            local st = {}
            local walked = 0
            pcall(function()
                for _, block in ipairs(df.global.world.map.map_blocks) do
                    local p = block.map_pos
                    local lf = block.local_feature
                    if not limit or (lf ~= nil and lf >= 0) or p.z <= limit.floor or limit.levels[p.z] then
                        walked = walked + 1
                        hazard_block(block, base, K, near, st)
                    end
                end
            end)
            base.nearest_z = base.nearest and base.nearest.z or base.top_z
            base.deep_floor = dm and dm.ok and dm.floor or nil
            DEEP_HAZARD_CACHE = {day = day, base = base, walked = walked}
        end
    end
    local out = {}
    for k, v in pairs(base) do out[k] = v end
    local g = DIG_GUARD
    out.refused = g.refused or 0
    if out.refused > 0 then
        out.refused_by = g.by
        out.refused_last = g.last[#g.last]
    end
    if (g.unreadable or 0) > 0 then out.unreadable = g.unreadable end
    if g.swept then out.swept = g.swept end
    if mine_adamantine == true then
        out.mine_adamantine = true
        out.note = 'mine_adamantine is on, but the sealed breach plan is not built yet: adamantine is still left alone'
    end
    return out
end
