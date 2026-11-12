-- (0.105.41, item 7) Environment hazards: spilt magma, cave-ins, frost and
-- heat. The `env_hazards` section (in the pulse too) and three actions.
--
--   magma   magma where it shouldn't be: a magma tile that is no part of
--           the map's own magma (a pipe's or the sea's: DF's feature flags),
--           of the AI's own magma works (lua/ai-waterworks.lua, their tiles
--           and one round them) or under a magma workshop. Looked for in
--           the map blocks round the citizens (and z-1), round the AI's
--           magma works and where it was seen before; a block is read whole
--           once a game day, otherwise only when DF marks its liquid as
--           moving (block.flags.update_liquid). Kept in the save tile by
--           tile (first and last seen, whether a citizen was near), so the
--           brain sees it spread (`grew_ago`), stand, and cool (`settled`:
--           tiles with no magma now, how long dry, how many are walls now:
--           obsidian). Dwarves standing in it (`burning`).
--   cave_ins  the game's cave-in announcements of the last CAVE_IN_DAYS
--           (lua/ai-reports.lua classify: the event feed's own matching),
--           with the citizens near each: the hurt (wounds), the trapped (in
--           another walking area than the fort's), where.
--   frost   the surface's temperature (outside citizens' tiles, else the
--           AI's outside water), freezing or not; each well's water (water,
--           ice, dry; under the sky or not); the AI's water zones' water;
--           the AI's moat frozen; citizens standing on ice.
--   heat    each magma workshop: what lies within HEAT_RADIUS that burns or
--           melts at magma's heat (item counts), what burns now; the AI's
--           magma works whose floodgate is not magma-safe; citizens near
--           magma or a magma workshop burning (a body part on fire) or hot.
--   channel_guard  the channels refused since the map loaded (a floor they
--           would leave hanging over nothing: a cave-in), and the last one.
--
-- Actions: magma_guard (traffic restricted round loose magma, the jobs
-- beside it taken off; lift), magma_reclaim (after it cooled: those tiles'
-- traffic back to normal and, dig = true, the walls the magma left (obsidian)
-- designated for digging, never one beside liquid), and the channel check
-- (channel_check, called by ai-builder's quickfort_apply on every dig
-- blueprint with channels).
--
-- All map access goes through the hooks at the top, so the tests can swap
-- them. State in site data 'ai-overseer/hazards'.
--@module = true

local U = reqscript('ai-util')

STATE_KEY = 'ai-overseer/hazards'
DAY = 1200
MAGMA_NEAR = 6            -- a citizen this close (same level, or one up or down) to a loose tile: "near"
MAGMA_BLOCKS_MAX = 160    -- map blocks read at most in one report
MAGMA_TILES_MAX = 600     -- loose tiles kept in the save at most
MAGMA_CELLS_MAX = 8       -- loose spots (8x8 cells) reported at most
MAGMA_WORK_NEAR = 20      -- an AI magma work this close to a loose spot is named
SETTLED_MAX = 8           -- cooled spots reported at most
CAVE_IN_DAYS = 3          -- cave-ins this recent reported
CAVE_IN_RADIUS = 10       -- citizens this close (two levels up or down) to a cave-in are checked
CAVE_IN_MAX = 6
FREEZE = 10000            -- water freezes at 10000 (DF's Urist degrees)
HOT = 10150               -- (a guess: needs an in-game look) a body part this hot is overheating
HEAT_RADIUS = 3           -- around a magma workshop: what burns or melts
HEAT_UNIT_NEAR = 10       -- citizens this close to magma or a magma workshop: their heat read
MAGMA_TEMP = 12000
ISLAND_MAX = 400          -- a floor area this big (or more) beside a channel is taken as held up
LIGHT_TICKS = 300         -- cave-ins, frost and heat read again after this long (the pulse reads magma only)

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
local function unkey(k)
    local x, y, z = tostring(k):match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
    return math.tointeger(tonumber(x)), math.tointeger(tonumber(y)), math.tointeger(tonumber(z))
end

---------------------------------------------------------------------------
-- Hooks (the game; the tests swap these)
---------------------------------------------------------------------------

function now()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function txt(s)
    local ok, v = pcall(dfhack.df2utf, s)
    return ok and v or tostring(s)
end

-- the citizens: {id, name, x, y, z, u}
function citizens()
    local out = {}
    local ok, cits = pcall(function()
        if U.REPORT_CTX and type(U.citizens) == 'function' then return U.citizens(true) end
        return dfhack.units.getCitizens(true)
    end)
    for _, u in ipairs(ok and cits or {}) do
        local okp, x, y, z = pcall(dfhack.units.getPosition, u)
        if okp and x then
            local okn, name = pcall(function() return txt(dfhack.units.getReadableName(u)) end)
            table.insert(out, {id = u.id, name = okn and name or ('unit ' .. tostring(u.id)), x = x, y = y, z = z, u = u})
        end
    end
    return out
end

-- a tile: ai-builder's tile_info (shape, material, magma, depth, feature, outside, hidden...)
local BUILDER
function tile(x, y, z)
    BUILDER = BUILDER or reqscript('ai-builder')
    local ok, t = pcall(BUILDER.tile_info, x, y, z)
    return ok and t or nil
end

-- the magma tiles of the 16x16 block (bx, by) on level z: list of {x, y, z,
-- depth, feature}; and whether DF marks the block's liquid as moving (true
-- when that can't be read). nil when the block isn't there. Not `must` and
-- still: not read ({}, false).
function block_magma(bx, by, z, must)
    local block = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
    if not block then return nil end
    local moving = true
    pcall(function() moving = block.flags.update_liquid == true end)
    if not must and not moving then return {}, false end
    local out = {}
    for lx = 0, 15 do
        for ly = 0, 15 do
            local d = block.designation[lx][ly]
            if d.flow_size > 0 and (d.liquid_type == true or d.liquid_type == 1) then
                local feat = false
                pcall(function() feat = d.feature_local or d.feature_global end)
                table.insert(out, {x = bx * 16 + lx, y = by * 16 + ly, z = z, depth = d.flow_size, feature = feat})
            end
        end
    end
    return out, moving
end

-- the map's size in blocks (nil: unknown)
function map_blocks()
    local ok, x, y, z = pcall(dfhack.maps.getTileSize)
    if ok and x then return (x + 15) // 16, (y + 15) // 16, z end
end

-- the AI's magma works (lua/ai-waterworks.lua): {id, shop, stage, gate_id,
-- tiles = {{x, y, z}}, gate = {x, y, z}}; its moat: {tiles}
local function waterworks_state()
    local ok, st = pcall(function() return reqscript('ai-waterworks').load_state() end)
    return ok and type(st) == 'table' and type(st.works) == 'table' and st or {works = {}}
end

local function plan_tiles(p)
    local out = {}
    if type(p) ~= 'table' then return out end
    for _, list in ipairs({p.wet, p.upstream, p.dig}) do
        if type(list) == 'table' then
            for _, c in ipairs(list) do
                if type(c) == 'table' and c.x then table.insert(out, {x = c.x, y = c.y, z = c.z}) end
            end
        end
    end
    for _, n in ipairs({'gate', 'pit', 'plug'}) do
        if type(p[n]) == 'table' and p[n].x then table.insert(out, {x = p[n].x, y = p[n].y, z = p[n].z}) end
    end
    return out
end

function magma_works()
    local out = {}
    for id, wk in pairs(waterworks_state().works) do
        if type(wk) == 'table' and wk.kind == 'magma' then
            local p = type(wk.plan) == 'table' and wk.plan or {}
            table.insert(out, {id = id, shop = p.shop, stage = wk.stage, gate_id = wk.gate_id,
                               gate = type(p.gate) == 'table' and {x = p.gate.x, y = p.gate.y, z = p.gate.z} or nil,
                               tiles = plan_tiles(p)})
        end
    end
    table.sort(out, function(a, b) return tostring(a.id) < tostring(b.id) end)
    return out
end

function moat_tiles()
    local wk = waterworks_state().works.moat
    if type(wk) ~= 'table' or wk.stage ~= 'done' and wk.stage ~= 'filling' then return {} end
    local p = type(wk.plan) == 'table' and wk.plan or {}
    local out = {}
    for _, c in ipairs(type(p.wet) == 'table' and p.wet or {}) do
        if type(c) == 'table' and c.x then table.insert(out, {x = c.x, y = c.y, z = c.z}) end
    end
    return out
end

-- a built floodgate's material magma-safe? (nil: unknown)
function gate_magma_safe(id)
    if not id then return nil end
    local ok, v = pcall(function() return reqscript('ai-waterworks').building_magma_safe(id) end)
    if ok then return v end
end

-- the magma workshops: {id, kind, x1, y1, x2, y2, z, x, y}
local MAGMA_SHOP_NAMES = {MagmaForge = true, MagmaSmelter = true, MagmaGlassFurnace = true, MagmaKiln = true}
function magma_shops()
    local out = {}
    for _, name in ipairs({'WORKSHOP_ANY', 'FURNACE_ANY'}) do
        pcall(function()
            for _, b in ipairs(df.global.world.buildings.other[name]) do
                local okn, n = pcall(function()
                    local t = b:getType()
                    if t == df.building_type.Workshop then return df.workshop_type[b:getSubtype()] end
                    return df.furnace_type[b:getSubtype()]
                end)
                if okn and MAGMA_SHOP_NAMES[n] then
                    table.insert(out, {id = b.id, kind = n, x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
                                       x = b.centerx, y = b.centery})
                end
            end
        end)
    end
    return out
end

-- how a material fares at magma's heat: 'burns', 'melts' or nil (safe).
-- h: {mat_fixed_temp, melting_point, boiling_point, ignite_point, heatdam_point}; 60001 = none
function heat_risk(h)
    if type(h) ~= 'table' then return nil end
    local fixed = tonumber(h.mat_fixed_temp)
    if fixed and fixed ~= 60001 then return nil end
    local ign = tonumber(h.ignite_point)
    if ign and ign ~= 60001 and ign <= MAGMA_TEMP then return 'burns' end
    for _, k in ipairs({'melting_point', 'boiling_point', 'heatdam_point'}) do
        local v = tonumber(h[k])
        if v and v ~= 60001 and v <= MAGMA_TEMP then return 'melts' end
    end
    return nil
end

-- the loose items within r of (x, y) on level z: {burns, melts, on_fire}
function items_near(x, y, z, r)
    local out = {burns = 0, melts = 0, on_fire = 0}
    local seen = {}
    for bx = (x - r) // 16, (x + r) // 16 do
        for by = (y - r) // 16, (y + r) // 16 do
            pcall(function()
                local block = dfhack.maps.getTileBlock(bx * 16, by * 16, z)
                if not block then return end
                for _, iid in ipairs(block.items) do
                    if not seen[iid] then
                        seen[iid] = true
                        local it = df.item.find(iid)
                        if it and it.flags.on_ground and not it.flags.in_building
                                and math.abs(it.pos.x - x) <= r and math.abs(it.pos.y - y) <= r and it.pos.z == z then
                            if it.flags.on_fire then out.on_fire = out.on_fire + 1 end
                            local okh, risk = pcall(function()
                                local h = dfhack.matinfo.decode(it).material.heat
                                return heat_risk({mat_fixed_temp = h.mat_fixed_temp, melting_point = h.melting_point,
                                                  boiling_point = h.boiling_point, ignite_point = h.ignite_point,
                                                  heatdam_point = h.heatdam_point})
                            end)
                            if okh and risk then out[risk] = out[risk] + 1 end
                        end
                    end
                end
            end)
        end
    end
    return out
end

-- a unit's heat: {on_fire = bool, temp = the hottest body part (nil: unknown)}
-- (body_part_status.on_fire and status2.body_part_temperature: needs an in-game look)
function unit_heat(u)
    local out = {on_fire = false}
    pcall(function()
        for _, st in ipairs(u.body.components.body_part_status) do
            if st.on_fire then out.on_fire = true break end
        end
    end)
    pcall(function()
        local hot
        for _, t in ipairs(u.status2.body_part_temperature) do
            local v = tonumber(t.whole)
            if v and (not hot or v > hot) then hot = v end
        end
        out.temp = hot
    end)
    return out
end

-- is the unit hurt? DF's own hospital flag (u.body.wounds holds old scars too)
function unit_hurt(u)
    local ok, v = pcall(function() return u.health ~= nil and u.health.flags.needs_healthcare end)
    return ok and v == true
end

-- the walking area a tile belongs to (0: none)
function walk_group(x, y, z)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    return ok and g or 0
end

-- a tile's temperature (nil: unknown)
function temp_at(x, y, z)
    local ok, t = pcall(function()
        local block = dfhack.maps.getTileBlock(x, y, z)
        return block.temperature_1[x & 15][y & 15]
    end)
    return ok and tonumber(t) or nil
end

-- the wells: {id, x, y, z}
function wells()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.WELL) do
            table.insert(out, {id = b.id, x = b.centerx, y = b.centery, z = b.z})
        end
    end)
    return out
end

-- the AI's water source zones (ai-builder-farms: the water tile each was made for)
function water_zones()
    local ok, list = pcall(function() return U.site_get('ai-overseer/water_zones', {}) end)
    return ok and type(list) == 'table' and list or {}
end

-- the game's announcements since tick `since`, newest first: {type, text, x, y, z, tick}
function announcements(since)
    local out = {}
    pcall(function()
        local list = df.global.world.status.announcements
        for i = #list - 1, 0, -1 do
            local r = list[i]
            local t = U.abs_tick(r.year, r.time)
            if t < since then break end
            if not r.flags.continuation then
                local x, y, z
                pcall(function()
                    if r.pos.x >= 0 then x, y, z = r.pos.x, r.pos.y, r.pos.z end
                end)
                table.insert(out, {type = df.announcement_type[r.type] or tostring(r.type), text = txt(r.text),
                                   x = x, y = y, z = z, tick = t})
            end
        end
    end)
    return out
end

function classify(type_name, text)
    local ok, topic = pcall(function() return reqscript('ai-reports').classify(type_name, text) end)
    return ok and topic or nil
end

-- the jobs: each job's {pos, type name, job}
function each_job(fn)
    pcall(function()
        local l = df.global.world.jobs.list.next
        local n = 0
        while l and n < 20000 do
            n = n + 1
            local j = l.item
            if j then
                local okp, p = pcall(function() return j.pos end)
                local okt, jt = pcall(function() return df.job_type[j.job_type] end)
                if okp and p and p.x >= 0 and okt and fn(p, jt, j) == false then return end
            end
            l = l.next
        end
    end)
end

function remove_job(j) return pcall(dfhack.job.removeJob, j) end

function job_ok(jt)
    local ok, v = pcall(function() return reqscript('ai-threats').fire_job_ok(jt) end)
    return ok and v == true
end

-- a tile's traffic: 'Normal', 'Restricted'...; set it
function traffic(x, y, z)
    local ok, v = pcall(function() return df.tile_traffic[dfhack.maps.getTileFlags(x, y, z).traffic] end)
    return ok and v or nil
end
function set_traffic(x, y, z, name)
    return pcall(function() dfhack.maps.getTileFlags(x, y, z).traffic = df.tile_traffic[name] end)
end

-- dig these tiles (ai-builder's quickfort_apply: the dig guard sees them)
function dig_tiles(cells, z)
    local ok, stats = pcall(function()
        return reqscript('ai-builder').quickfort_apply('dig', cells, z, 0, 0)
    end)
    if not ok or type(stats) ~= 'table' then return 0 end
    local okv, n = pcall(function()
        local v = stats.dig_designated
        return type(v) == 'table' and v.value or v
    end)
    return okv and tonumber(n) or 0
end

function log_line(msg) pcall(function() print('[ai-hazards] ' .. msg) end) end

---------------------------------------------------------------------------
-- State
---------------------------------------------------------------------------

function load_state()
    local d = U.site_get(STATE_KEY, {})
    d = type(d) == 'table' and d or {}
    d.magma = type(d.magma) == 'table' and d.magma or {}
    d.magma.tiles = type(d.magma.tiles) == 'table' and d.magma.tiles or {}
    d.magma.restricted = type(d.magma.restricted) == 'table' and d.magma.restricted or {}
    return d
end

function save_state(d) U.site_put(STATE_KEY, d) end

---------------------------------------------------------------------------
-- Pure helpers (tested)
---------------------------------------------------------------------------

-- the nearest of `pts` to (x, y, z): distance (levels count 3), or nil
function nearest(x, y, z, pts, dz_max)
    local best
    for _, p in ipairs(pts or {}) do
        local dz = math.abs((p.z or 0) - z)
        if not dz_max or dz <= dz_max then
            local d = math.max(math.abs(p.x - x), math.abs(p.y - y)) + 3 * dz
            if not best or d < best then best = d end
        end
    end
    return best
end

-- loose points gathered into 8x8 cells on a level, the biggest first
function cells_of(points, max)
    local by, list = {}, {}
    for _, p in ipairs(points) do
        local k = p.z * 1000000 + (p.x // 8) * 1000 + (p.y // 8)
        local c = by[k]
        if not c then
            c = {x = p.x, y = p.y, z = p.z, n = 0, pts = {}}
            by[k] = c
            table.insert(list, c)
        end
        c.n = c.n + 1
        table.insert(c.pts, p)
    end
    table.sort(list, function(a, b) return a.n > b.n or (a.n == b.n and (a.z * 1e6 + a.x * 1e3 + a.y) < (b.z * 1e6 + b.x * 1e3 + b.y)) end)
    while max and #list > max do table.remove(list) end
    return list
end

-- the tiles the AI's magma works and the magma workshops hold magma in by
-- design (each with one tile round it): {key = true}
function own_magma_tiles(works, shops)
    local out = {}
    local function add(x, y, z)
        for dx = -1, 1 do for dy = -1, 1 do out[key(x + dx, y + dy, z)] = true end end
    end
    for _, w in ipairs(works or {}) do
        for _, t in ipairs(w.tiles or {}) do add(t.x, t.y, t.z) end
    end
    for _, s in ipairs(shops or {}) do
        -- a magma workshop draws from the magma under it (the level below)
        for x = s.x1, s.x2 do for y = s.y1, s.y2 do add(x, y, s.z - 1) end end
    end
    return out
end

local SOLID = {WALL = true, FORTIFICATION = true}
local OPENISH = {EMPTY = true, RAMP_TOP = true, NONE = true}

-- (cave-ins) Would channelling `cells` (a list of {x, y} on level z) leave a
-- floor hanging over nothing? Every floor area beside the channels (the
-- tiles of level z, eight ways, the channels and the channels already
-- designated taken as open) needs a wall in it, a wall under one of its
-- tiles or a wall over one; an area of ISLAND_MAX tiles or more counts as
-- held. Returns the cells that would leave one ({key = why}), empty when none.
-- An area hanging is answered by refusing the first channel beside it; the
-- rest are checked again without it (an area it held is let by), so only as
-- many are refused as it takes (all left beside a hanging area after
-- ISLAND_ROUNDS rounds).
ISLAND_ROUNDS = 8
function channel_islands(cells, z, tile_fn)
    local bad = {}
    local left = cells
    for round = 1, ISLAND_ROUNDS do
        local b = channel_islands_once(left, z, tile_fn, round == ISLAND_ROUNDS)
        if next(b) == nil then break end
        local keep = {}
        for _, c in ipairs(left) do
            local k = key(c.x, c.y, z)
            if b[k] then bad[k] = b[k] else table.insert(keep, c) end
        end
        left = keep
        if #left == 0 then break end
    end
    return bad
end

-- one round: the first channel beside each hanging area (all: every one beside it)
function channel_islands_once(cells, z, tile_fn, all)
    tile_fn = tile_fn or tile
    local gone, bad = {}, {}
    for _, c in ipairs(cells) do gone[key(c.x, c.y, z)] = true end
    local memo = {}
    local function T(x, y, zz)
        local k = key(x, y, zz)
        local v = memo[k]
        if v == nil then v = tile_fn(x, y, zz) or false; memo[k] = v end
        return v or nil
    end
    local function open(x, y)
        if gone[key(x, y, z)] then return true end
        local t = T(x, y, z)
        if not t then return true end
        if t.dig == 'Channel' then return true end
        return OPENISH[t.shape] == true
    end
    local held_cache = {}
    for _, c in ipairs(cells) do
        for dx = -1, 1 do
            for dy = -1, 1 do
                local sx, sy = c.x + dx, c.y + dy
                if all and (dx ~= 0 or dy ~= 0) and held_cache[key(sx, sy, z)] == false then
                    bad[key(c.x, c.y, z)] = bad[key(c.x, c.y, z)] or 'a floor beside it would hang over nothing (a cave-in)'
                end
                if (dx ~= 0 or dy ~= 0) and not open(sx, sy) and held_cache[key(sx, sy, z)] == nil then
                    -- the area this tile belongs to
                    local area, queue, seen, held = {}, {{sx, sy}}, {[key(sx, sy, z)] = true}, false
                    while #queue > 0 and not held do
                        local p = table.remove(queue)
                        local x, y = p[1], p[2]
                        table.insert(area, key(x, y, z))
                        local t = T(x, y, z)
                        local below, above = T(x, y, z - 1), T(x, y, z + 1)
                        if (t and SOLID[t.shape]) or (below and SOLID[below.shape]) or (above and SOLID[above.shape])
                                or #area >= ISLAND_MAX then
                            held = true
                        else
                            for ex = -1, 1 do
                                for ey = -1, 1 do
                                    local k = key(x + ex, y + ey, z)
                                    if (ex ~= 0 or ey ~= 0) and not seen[k] and not open(x + ex, y + ey) then
                                        seen[k] = true
                                        table.insert(queue, {x + ex, y + ey})
                                    end
                                end
                            end
                        end
                    end
                    for _, k in ipairs(area) do held_cache[k] = held end
                    if not held then
                        bad[key(c.x, c.y, z)] = ('a floor of %d tile(s) at x%d y%d would hang over nothing (a cave-in)')
                            :format(#area, sx, sy)
                    end
                end
            end
        end
    end
    return bad
end

---------------------------------------------------------------------------
-- The channel guard (called from ai-builder's quickfort_apply)
---------------------------------------------------------------------------

CHANNEL_GUARD = CHANNEL_GUARD or {refused = 0}

-- Quickfort dig data ({[z] = {[y] = {[x] = text}}} at ox, oy, oz): the
-- channel cells (h, one tile each; a cell with extents is let by whole) that
-- would leave a floor hanging taken out. Returns the data (the same table
-- when nothing is refused), how many were refused, the first why.
-- `record`: kept for the report (false: a dry run).
function channel_check(data, ox, oy, oz, record)
    local refused, first = 0, nil
    local out, changed = {}, false
    for z, grid in pairs(data) do
        local cells, at = {}, {}
        for y, row in pairs(grid) do
            for x, text in pairs(row) do
                if type(text) == 'string' and text:match('^%s*h') and not text:find('%(') then
                    local c = {x = ox + x, y = oy + y}
                    table.insert(cells, c)
                    at[key(c.x, c.y, oz + z)] = {x = x, y = y}
                end
            end
        end
        local bad = #cells > 0 and channel_islands(cells, oz + z) or {}
        local og = {}
        out[z] = og
        for y, row in pairs(grid) do
            for x, text in pairs(row) do
                local k = key(ox + x, oy + y, oz + z)
                if bad[k] then
                    changed = true
                    refused = refused + 1
                    first = first or bad[k]
                    if record then
                        CHANNEL_GUARD.refused = CHANNEL_GUARD.refused + 1
                        CHANNEL_GUARD.last = {x = ox + x, y = oy + y, z = oz + z, why = bad[k], tick = now()}
                        log_line(('channel at x%d y%d z%d refused: %s'):format(ox + x, oy + y, oz + z, bad[k]))
                    end
                else
                    og[y] = og[y] or {}
                    og[y][x] = text
                end
            end
        end
    end
    if not changed then return data, 0, nil end
    return out, refused, first
end

---------------------------------------------------------------------------
-- The report
---------------------------------------------------------------------------

FULL_SCAN_AT = FULL_SCAN_AT or nil      -- the tick of the last whole read of the blocks
LIGHT = LIGHT or nil                    -- {tick, cave_ins, frost, heat}

local function magma_part(st, t, cits, works, shops)
    local m = st.magma
    local own = own_magma_tiles(works, shops)
    local full = FULL_SCAN_AT == nil or t - FULL_SCAN_AT >= DAY or t < FULL_SCAN_AT
    local nbx, nby, nz = map_blocks()
    -- the blocks to read: {key = {bx, by, z, must}} (must: read even if still)
    local blocks, nblocks = {}, 0
    local function want(x, y, z, must)
        local bx, by = x // 16, y // 16
        if bx < 0 or by < 0 or z < 0 or (nbx and (bx >= nbx or by >= nby or z >= nz)) then return end
        local k = key(bx, by, z)
        local b = blocks[k]
        if b then
            b.must = b.must or must
        elseif nblocks < MAGMA_BLOCKS_MAX or must then
            blocks[k] = {bx = bx, by = by, z = z, must = must}
            nblocks = nblocks + 1
        end
    end
    for k in pairs(m.tiles) do
        local x, y, z = unkey(k)
        if x then want(x, y, z, true) end
    end
    for _, w in ipairs(works) do
        if w.gate then
            for dx = -16, 16, 16 do for dy = -16, 16, 16 do want(w.gate.x + dx, w.gate.y + dy, w.gate.z, false) end end
        end
    end
    for _, c in ipairs(cits) do
        for _, dz in ipairs({0, -1}) do
            for dx = -16, 16, 16 do for dy = -16, 16, 16 do want(c.x + dx, c.y + dy, c.z + dz, false) end end
        end
    end
    local now_magma, loose, read, still = {}, {}, 0, 0
    for _, b in pairs(blocks) do
        local list, moving = block_magma(b.bx, b.by, b.z, full or b.must)
        if list then
            if full or b.must or moving then
                read = read + 1
                for _, p in ipairs(list) do
                    local k = key(p.x, p.y, p.z)
                    now_magma[k] = p
                    if not p.feature and not own[k] then table.insert(loose, p) end
                end
            else
                still = still + 1
                -- a still block not read: its recorded tiles keep their state
            end
        end
    end
    if full then FULL_SCAN_AT = t end
    -- the record: each loose tile's first and last sight, a citizen near
    local new = 0
    local burning = {}
    local cit_at = {}
    for _, c in ipairs(cits) do cit_at[key(c.x, c.y, c.z)] = c end
    for _, p in ipairs(loose) do
        local k = key(p.x, p.y, p.z)
        local near = nearest(p.x, p.y, p.z, cits, 1)
        local r = m.tiles[k]
        if not r then
            local n = 0
            for _ in pairs(m.tiles) do n = n + 1 end
            if n < MAGMA_TILES_MAX then
                r = {f = t}
                m.tiles[k] = r
                new = new + 1
            end
        end
        if r then
            r.l = t
            if near and near <= MAGMA_NEAR then r.near = true end
        end
        p.near = near
    end
    for k, c in pairs(cit_at) do
        if now_magma[k] then table.insert(burning, {id = c.id, name = c.name}) end
    end
    -- spreading: new loose tiles since the last read (not at the very first
    -- read: magma that was there before the AI watched isn't news)
    if new > 0 and (m.seen or 0) > 0 then m.grew = t end
    m.seen = (m.seen or 0) + 1
    m.scan = t
    -- the spots now
    local out = {loose = #loose, cells = {}, burning = burning, blocks_read = read, blocks_still = still,
                 full = full or nil, recorded = 0, restricted = #m.restricted}
    for _ in pairs(m.tiles) do out.recorded = out.recorded + 1 end
    if m.grew then out.grew_ago = math.max(0, t - m.grew) end
    for _, c in ipairs(cells_of(loose, MAGMA_CELLS_MAX)) do
        local near
        for _, p in ipairs(c.pts) do
            if p.near and (not near or p.near < near) then near = p.near end
        end
        local row = {x = c.x, y = c.y, z = c.z, n = c.n, near = near}
        local best
        for _, w in ipairs(works) do
            for _, wt in ipairs(w.tiles or {}) do
                local d = nearest(wt.x, wt.y, wt.z, c.pts, 1)
                if d and d <= MAGMA_WORK_NEAR and (not best or d < best.d) then best = {id = w.id, shop = w.shop, d = d} end
            end
        end
        if best then row.work, row.work_shop, row.work_d = best.id, best.shop, best.d end
        table.insert(out.cells, row)
    end
    -- cooled: recorded tiles with no magma now (their block read this time)
    local settled = {}
    for k, r in pairs(m.tiles) do
        local x, y, z = unkey(k)
        local bk = x and key(x // 16, y // 16, z)
        local readable = bk and blocks[bk] ~= nil
        if readable and not now_magma[k] and type(r.l) == 'number' then
            local tt = tile(x, y, z)
            table.insert(settled, {x = x, y = y, z = z, dry = t - r.l, wall = tt and tt.shape == 'WALL' or false,
                                   near = r.near == true})
        end
    end
    local sc = cells_of(settled, SETTLED_MAX)
    out.settled = {}
    for _, c in ipairs(sc) do
        local dry, walls, near
        for _, p in ipairs(c.pts) do
            if not dry or p.dry < dry then dry = p.dry end
            if p.wall then walls = (walls or 0) + 1 end
            near = near or p.near
        end
        table.insert(out.settled, {x = c.x, y = c.y, z = c.z, n = c.n, dry = dry, walls = walls or 0, near = near or nil})
    end
    out.works = {}
    for _, w in ipairs(works) do
        table.insert(out.works, {id = w.id, shop = w.shop, stage = w.stage})
    end
    return out
end

local function cave_part(t, cits)
    local out = {list = {}}
    local spots = {}
    for _, a in ipairs(announcements(t - CAVE_IN_DAYS * DAY)) do
        if classify(a.type, a.text) == 'cave_in' then
            local dup = false
            for _, s in ipairs(spots) do
                if a.x and s.x and s.z == a.z and math.abs(s.x - a.x) <= 3 and math.abs(s.y - a.y) <= 3 then
                    dup = true; s.n = s.n + 1
                end
            end
            if not dup and #spots < CAVE_IN_MAX then
                table.insert(spots, {x = a.x, y = a.y, z = a.z, ago = math.max(0, t - a.tick), n = 1,
                                     text = tostring(a.text):sub(1, 120)})
            end
        end
    end
    if #spots == 0 then return out end
    -- the fort's walking area: the one most citizens stand in
    local counts, main, best = {}, nil, 0
    for _, c in ipairs(cits) do
        c.group = c.group or walk_group(c.x, c.y, c.z)
        if c.group and c.group ~= 0 then
            counts[c.group] = (counts[c.group] or 0) + 1
            if counts[c.group] > best then main, best = c.group, counts[c.group] end
        end
    end
    for _, s in ipairs(spots) do
        s.hurt, s.trapped = {}, {}
        if s.x then
            for _, c in ipairs(cits) do
                if math.abs(c.z - s.z) <= 2 and math.abs(c.x - s.x) <= CAVE_IN_RADIUS and math.abs(c.y - s.y) <= CAVE_IN_RADIUS then
                    if unit_hurt(c.u) then table.insert(s.hurt, {id = c.id, name = c.name}) end
                    if main and c.group ~= main then
                        table.insert(s.trapped, {id = c.id, name = c.name, x = c.x, y = c.y, z = c.z})
                    end
                end
            end
        end
        table.insert(out.list, s)
    end
    return out
end

local FROZEN = 'FROZEN_LIQUID'

-- what a well draws from: 'water', 'ice', 'dry'; whether that is under the sky
function well_water(w, tile_fn)
    tile_fn = tile_fn or tile
    for z = w.z - 1, math.max(0, w.z - 80), -1 do
        local t = tile_fn(w.x, w.y, z)
        if not t then return 'dry', nil end
        if t.material == FROZEN then return 'ice', t.outside end
        if t.liquid and not t.magma then return 'water', t.outside end
        if t.shape ~= 'EMPTY' and t.shape ~= 'RAMP_TOP' then return 'dry', t.outside end
    end
    return 'dry', nil
end

local function frost_part(cits)
    local out = {wells = {}, zones = {}, on_ice = {}}
    local temps = {}
    for _, c in ipairs(cits) do
        if #temps >= 12 then break end
        local tt = tile(c.x, c.y, c.z)
        if tt and tt.outside then
            local v = temp_at(c.x, c.y, c.z)
            if v then table.insert(temps, v) end
        end
        if tt and tt.material == FROZEN then table.insert(out.on_ice, {id = c.id, name = c.name}) end
    end
    for _, w in ipairs(wells()) do
        local water, outside = well_water(w)
        table.insert(out.wells, {id = w.id, x = w.x, y = w.y, z = w.z, water = water, outside = outside or nil})
    end
    for _, zn in ipairs(water_zones()) do
        if type(zn) == 'table' and zn.x then
            local tt = tile(zn.x, zn.y, zn.z)
            local st = not tt and 'gone' or tt.material == FROZEN and 'ice' or (tt.liquid and not tt.magma) and 'water' or 'dry'
            table.insert(out.zones, {x = zn.x, y = zn.y, z = zn.z, water = st, outside = tt and tt.outside or nil})
            if #temps == 0 and tt and tt.outside then
                local v = temp_at(zn.x, zn.y, zn.z)
                if v then table.insert(temps, v) end
            end
        end
    end
    local moat = moat_tiles()
    if #moat > 0 then
        local ice, n = 0, 0
        for i = 1, #moat, math.max(1, #moat // 20) do
            local c = moat[i]
            local tt = tile(c.x, c.y, c.z)
            n = n + 1
            if tt and tt.material == FROZEN then ice = ice + 1 end
        end
        out.moat = {looked = n, ice = ice, frozen = ice * 2 >= n or nil}
    end
    if #temps > 0 then
        local lo = math.huge
        for _, v in ipairs(temps) do lo = math.min(lo, v) end
        out.surface_temp = lo
        out.freezing = lo <= FREEZE
    end
    return out
end

local function heat_part(cits, works, shops, magma_pts)
    local out = {shops = {}, works = {}, burning = {}, hot = {}}
    for _, s in ipairs(shops) do
        local it = items_near(s.x, s.y, s.z, HEAT_RADIUS)
        table.insert(out.shops, {id = s.id, kind = s.kind, x = s.x, y = s.y, z = s.z,
                                 burns = it.burns, melts = it.melts, on_fire = it.on_fire})
    end
    for _, w in ipairs(works) do
        local safe = gate_magma_safe(w.gate_id)
        if safe == false then table.insert(out.works, {id = w.id, shop = w.shop, gate_safe = false}) end
    end
    local pts = {}
    for _, s in ipairs(shops) do table.insert(pts, {x = s.x, y = s.y, z = s.z}) end
    for _, p in ipairs(magma_pts or {}) do table.insert(pts, p) end
    if #pts == 0 then return out end
    for _, c in ipairs(cits) do
        local d = nearest(c.x, c.y, c.z, pts, 1)
        if d and d <= HEAT_UNIT_NEAR then
            local h = unit_heat(c.u)
            if h.on_fire then table.insert(out.burning, {id = c.id, name = c.name})
            elseif h.temp and h.temp >= HOT then table.insert(out.hot, {id = c.id, name = c.name, temp = h.temp}) end
        end
    end
    return out
end

-- the env_hazards section
function report()
    local t = now()
    local st = load_state()
    local cits = citizens()
    local works = magma_works()
    local shops = magma_shops()
    local out = {}
    local okm, m = pcall(magma_part, st, t, cits, works, shops)
    out.magma = okm and m or {error = tostring(m)}
    if okm then save_state(st) end
    if not LIGHT or t - LIGHT.tick >= LIGHT_TICKS or t < LIGHT.tick then
        local magma_pts = {}
        if okm then for _, c in ipairs(m.cells) do table.insert(magma_pts, {x = c.x, y = c.y, z = c.z}) end end
        local okc, cv = pcall(cave_part, t, cits)
        local okf, fr = pcall(frost_part, cits)
        local okh, ht = pcall(heat_part, cits, works, shops, magma_pts)
        LIGHT = {tick = t, cave_ins = okc and cv or {error = tostring(cv)}, frost = okf and fr or {error = tostring(fr)},
                 heat = okh and ht or {error = tostring(ht)}}
    end
    out.cave_ins, out.frost, out.heat = LIGHT.cave_ins, LIGHT.frost, LIGHT.heat
    out.read_ago = t - LIGHT.tick
    out.channel_guard = {refused = CHANNEL_GUARD.refused, last = CHANNEL_GUARD.last}
    return out
end

---------------------------------------------------------------------------
-- Actions
---------------------------------------------------------------------------

-- the recorded tiles that held magma at the last report's read
local function live_tiles(m)
    local out = {}
    for k, r in pairs(m.tiles) do
        if m.scan ~= nil and r.l == m.scan then
            local x, y, z = unkey(k)
            if x then table.insert(out, {x = x, y = y, z = z, near = r.near}) end
        end
    end
    return out
end

-- Traffic restricted round the loose magma near the dwarves (only tiles at
-- Normal, kept in the save) and the jobs beside it taken off (digging,
-- hauling, building: ai-threats fire_job_ok); lift: those tiles back to Normal.
function magma_guard(radius, max_jobs, lift, dry_run)
    local d = load_state()
    local m = d.magma
    if lift then
        local n = 0
        for _, k in ipairs(m.restricted) do
            local x, y, z = unkey(k)
            if x and traffic(x, y, z) == 'Restricted' then
                if not dry_run then set_traffic(x, y, z, 'Normal') end
                n = n + 1
            end
        end
        if not dry_run then
            m.restricted = {}
            save_state(d)
        end
        return {ok = true, lifted = n, dry_run = dry_run or nil}
    end
    local pts = {}
    for _, p in ipairs(live_tiles(m)) do if p.near then table.insert(pts, p) end end
    if #pts == 0 then return {ok = false, rejected = true, nothing_to_do = true, error = 'no loose magma near the dwarves'} end
    local have = {}
    for _, k in ipairs(m.restricted) do have[k] = true end
    local marked = 0
    for _, p in ipairs(pts) do
        for y = p.y - radius, p.y + radius do
            for x = p.x - radius, p.x + radius do
                local k = key(x, y, p.z)
                if x >= 0 and y >= 0 and not have[k] and #m.restricted < 3000 and traffic(x, y, p.z) == 'Normal' then
                    have[k] = true
                    marked = marked + 1
                    if not dry_run then
                        set_traffic(x, y, p.z, 'Restricted')
                        table.insert(m.restricted, k)
                    end
                end
            end
        end
    end
    local found = {}
    each_job(function(pos, jt, j)
        if job_ok(jt) and nearest(pos.x, pos.y, pos.z, pts, 0) and nearest(pos.x, pos.y, pos.z, pts, 0) <= radius then
            table.insert(found, j)
            if #found >= max_jobs then return false end
        end
    end)
    local removed = 0
    if not dry_run then
        for _, j in ipairs(found) do if remove_job(j) then removed = removed + 1 end end
        save_state(d)
    end
    return {ok = true, spots = #pts, restricted = marked, jobs_removed = dry_run and #found or removed,
            dry_run = dry_run or nil}
end

local LIQUID_NEAR = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {1, 1, 0}, {1, -1, 0}, {-1, 1, 0}, {-1, -1, 0},
                     {0, 0, 1}, {0, 0, -1}}

-- After the magma cooled (no magma on a recorded tile for cool_ticks): the
-- restricted tiles no longer beside live magma back to Normal, those tiles
-- forgotten, and (dig) the walls it left where a citizen walked (obsidian)
-- designated for digging: never a constructed wall, a hidden tile, or one
-- with liquid beside it (a plug that holds magma or water back).
function magma_reclaim(cool_ticks, dig, dry_run)
    local d = load_state()
    local m = d.magma
    local t = now()
    local live = live_tiles(m)
    local cooled = {}
    for k, r in pairs(m.tiles) do
        if type(r.l) == 'number' and t - r.l >= cool_ticks then
            local x, y, z = unkey(k)
            local tt = x and tile(x, y, z)
            if tt and tt.magma then
                r.l = t                 -- magma back on it (not read since): not cooled
            elseif x then
                table.insert(cooled, {k = k, x = x, y = y, z = z, near = r.near, t = tt})
            end
        end
    end
    if #cooled == 0 and #m.restricted == 0 then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'no spilt magma has cooled'}
    end
    -- traffic back: every restricted tile further than 3 from live magma
    local lifted, keep = 0, {}
    for _, k in ipairs(m.restricted) do
        local x, y, z = unkey(k)
        local d0 = x and nearest(x, y, z, live, 0)
        if x and (not d0 or d0 > 3 or #live == 0) then
            if traffic(x, y, z) == 'Restricted' then
                if not dry_run then set_traffic(x, y, z, 'Normal') end
                lifted = lifted + 1
            end
        else
            table.insert(keep, k)
        end
    end
    -- the walls left, by level
    local by_z, walls, refused = {}, 0, 0
    if dig then
        for _, c in ipairs(cooled) do
            local tt = c.t
            if c.near and tt and tt.shape == 'WALL' and tt.material ~= 'CONSTRUCTION' and not tt.hidden and not tt.designated then
                local wet = false
                for _, o in ipairs(LIQUID_NEAR) do
                    local n = tile(c.x + o[1], c.y + o[2], c.z + o[3])
                    if n and (n.liquid or n.material == FROZEN) then wet = true break end
                end
                if wet then
                    refused = refused + 1
                else
                    by_z[c.z] = by_z[c.z] or {}
                    table.insert(by_z[c.z], {x = c.x, y = c.y, text = 'd'})
                    walls = walls + 1
                end
            end
        end
    end
    local designated = 0
    if not dry_run then
        for z, cells in pairs(by_z) do designated = designated + dig_tiles(cells, z) end
        for _, c in ipairs(cooled) do m.tiles[c.k] = nil end
        m.restricted = keep
        if next(m.tiles) == nil then m.grew = nil end
        save_state(d)
        log_line(('reclaimed %d cooled tile(s): %d restricted tile(s) back to normal, %d wall(s) designated for digging')
            :format(#cooled, lifted, designated))
    end
    return {ok = true, cooled = #cooled, lifted = lifted, walls = walls, designated = dry_run and walls or designated,
            beside_liquid = refused > 0 and refused or nil, dry_run = dry_run or nil}
end
