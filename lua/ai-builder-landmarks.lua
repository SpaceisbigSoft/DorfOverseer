-- ai-builder-landmarks: the Design track's landmarks (D0): candidate sites
-- for a blueprint's envelope, the map checks a drawing must pass, and its
-- building: one project a dug level (rock), or stage by stage (surface).
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers of the other parts (check_site, offset_sites, stair_levels,
-- find_surface_rect, keep_tile, surface_anchors, hall_depots, qf_try, ...) are
-- in reach.
--
-- The rule (design-track sections 5-6): the drawing says what the landmark
-- looks like; where it goes is decided here. A site is asked for by its
-- envelope (w, h, levels, ground) and comes back as an id (S1-S4) with words;
-- its coordinates stay in the save (site data BP_SITES_KEY) and never leave
-- the bridge. A drawing names a site; every tile is then checked on the real
-- map, and a refusal's reasons give positions on the drawing's own grid.
-- The format (alphabet, legend, limits) and the translation to Quickfort
-- cells are ai-blueprints' (check_format, cost, to_layouts); nothing here
-- reads a blueprint's text but its grids, for the positions in the words.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-landmarks'] = '0.105.45'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, has, add, ez = info, has, add, ez

LANDMARKS_KEY = 'ai-overseer/landmarks'
BP_SITES_KEY = 'ai-overseer/bp-sites'
BP_SITES_DAYS = 7                -- a site offered is good this long
LANDMARKS_KEEP = 12              -- landmark records kept (the newest; open ones always)
LANDMARK_REASONS_MAX = 8         -- reasons a refusal gives at most
LANDMARK_WAY_IN_CLEAR = 3        -- no surface landmark tile this near a way in or the depot road's mouth
LANDMARK_STOCK_SHARE = 0.6       -- built tiles at most this share of the boulders and blocks on hand
LANDMARK_MAX_TREES = 20          -- trees a surface landmark may fell
LANDMARK_SITE_TRIES = 12         -- surface rectangles looked at for n sites
WALK_SECONDS = 1.0               -- the walk test stops here
WALK_NODES = 400000              -- and after this many tiles
NEAR_REACH = 10                  -- tiles round a site looked at for its words (river, magma, cavern)
OPEN_REDIG_MAX = 3               -- (E1) times a wave's lost channel tiles are designated again
OPEN_WAIT_DAYS = 14              -- (0.105.37 fix) a wave or its rails waiting this long: designated again,
                                 -- OPEN_REDIG_MAX times; then a wave is given up (its rest stays floor) and
                                 -- rails are reported 'stalled' (the brain frees the landmark's slot)

-- the quarter turn that puts row 0 toward a corridor arriving in direction d
-- (q quarter turns clockwise: the drawing then reaches away from the stair)
local Q_OF_DIR = {['0,1'] = 0, ['-1,0'] = 1, ['0,-1'] = 2, ['1,0'] = 3}
local DIR_NAME = {['0,1'] = 'south', ['-1,0'] = 'west', ['0,-1'] = 'north', ['1,0'] = 'east'}

-- The blueprint module (ai-blueprints, pure: no game access). Tests swap it.
function blueprints()
    return reqscript('ai-blueprints')
end

---------------------------------------------------------------------------
-- Map reads only this part makes (swapped by the tests)
---------------------------------------------------------------------------

-- The stone a tile is (an inorganic token, e.g. 'GRANITE'), or nil. [verify]
-- a vein's mineral first, else the geology layer the tile is in.
function stone_at(x, y, z)
    local ok, tok = pcall(function()
        local b = dfhack.maps.getTileBlock(x, y, z)
        if not b then return nil end
        local lx, ly = x % 16, y % 16
        local inorg = df.global.world.raws.inorganics.all or df.global.world.raws.inorganics
        for _, ev in ipairs(b.block_events) do
            if df.block_square_event_mineralst:is_instance(ev) then
                local okg, on = pcall(function() return ev:getassignment(lx, ly) end)
                if okg and on and inorg[ev.inorganic_mat] then return inorg[ev.inorganic_mat].id end
            end
        end
        local d = b.designation[lx][ly]
        local rx, ry = dfhack.maps.getTileBiomeRgn(x, y, z)
        if type(rx) == 'table' or type(rx) == 'userdata' then rx, ry = rx.x, rx.y end
        local region = dfhack.maps.getRegionBiome(rx, ry)
        local biome = df.world_geo_biome.find(region.geo_index)
        local layer = biome.layers[d.geolayer_index]
        return layer and inorg[layer.mat_index] and inorg[layer.mat_index].id or nil
    end)
    return ok and tok or nil
end

-- Boulders and blocks free to build with (the stock cap's measure).
function landmark_stock()
    local b = select(1, count_items('BOULDER')) or 0
    local k = select(1, count_items('BLOCKS')) or 0
    return b + k
end

-- Is now a bad time for a landmark (an invasion on the map)? why, or nil.
function landmark_times()
    local ok, n = pcall(function()
        local c = 0
        for _, u in ipairs(df.global.world.units.active) do
            if dfhack.units.isInvader(u) and not dfhack.units.isDead(u) and dfhack.units.isActive(u) then
                c = c + 1
            end
        end
        return c
    end)
    if ok and n and n > 0 then return ('%d invader(s) on the map'):format(n) end
    return nil
end

---------------------------------------------------------------------------
-- Saved state
---------------------------------------------------------------------------

function landmarks_data()
    local d = site_get(LANDMARKS_KEY)
    d.next = math.tointeger(d.next) or 1
    d.list = type(d.list) == 'table' and d.list or {}
    return d
end

local OPEN_STATUS = {building = true}

local function save_landmarks(d)
    local n = 0
    for i = #d.list, 1, -1 do
        if not OPEN_STATUS[d.list[i].status] then
            n = n + 1
            if n > LANDMARKS_KEEP then table.remove(d.list, i) end
        end
    end
    while #d.list > LANDMARKS_KEEP do
        local dropped = false
        for i, l in ipairs(d.list) do
            if not OPEN_STATUS[l.status] then table.remove(d.list, i) dropped = true break end
        end
        if not dropped then break end
    end
    return site_put(LANDMARKS_KEY, d)
end

local function find_landmark(d, id)
    for _, l in ipairs(d.list) do if l.landmark_id == id then return l end end
end

-- Surface landmarks being built: each takes a building slot (slot_cap).
function landmarks_open_surface()
    local n = 0
    for _, l in ipairs(landmarks_data().list) do
        if l.ground == 'surface' and l.status == 'building' then n = n + 1 end
    end
    return n
end

---------------------------------------------------------------------------
-- Grids and turns
---------------------------------------------------------------------------

-- q quarter turns clockwise (DF's y grows southward): north goes east.
function turn_xy(x, y, q)
    for _ = 1, (q or 0) % 4 do x, y = -y, x end
    return x, y
end

-- and back (counter-clockwise)
function unturn_xy(x, y, q)
    for _ = 1, (q or 0) % 4 do x, y = y, -x end
    return x, y
end

local function rows_of(level)
    local g = type(level) == 'table' and level.grid or nil
    return type(g) == 'table' and g or {}
end

-- The '@' of level 1 on its grid (0-based column and row), or nil.
function join_of(bp)
    local lv = type(bp) == 'table' and type(bp.levels) == 'table' and bp.levels[1] or nil
    for r, row in ipairs(rows_of(lv)) do
        local c = tostring(row):find('@', 1, true)
        if c then return c - 1, r - 1 end
    end
end

-- Every tile of the drawing (not '_'), by level: {{gx, gy, lx, ly, sym}, ...},
-- lx, ly on the layout (the join at 0, 0, turned by q).
function grid_cells(bp, q)
    local jx, jy = join_of(bp)
    local out = {}
    for k, lv in ipairs(type(bp.levels) == 'table' and bp.levels or {}) do
        local cells = {}
        for r, row in ipairs(rows_of(lv)) do
            row = tostring(row)
            for c = 1, #row do
                local s = row:sub(c, c)
                if s ~= '_' then
                    local lx, ly = turn_xy(c - 1 - jx, r - 1 - jy, q)
                    table.insert(cells, {gx = c - 1, gy = r - 1, lx = lx, ly = ly, sym = s})
                end
            end
        end
        out[k] = cells
    end
    return out
end

-- A layout position back on the drawing's grid: gx, gy.
local function grid_xy(bp, q, lx, ly)
    local jx, jy = join_of(bp)
    local x, y = unturn_xy(lx, ly, q)
    return x + (jx or 0), y + (jy or 0)
end

-- A reason: {code, level, x, y, words}, positions on the drawing's grid.
local function reason(list, code, level, x, y, words)
    if #list >= LANDMARK_REASONS_MAX then return end
    local where = level and x and ('L%d x%d y%d: '):format(level, x, y) or (level and ('L%d: '):format(level) or '')
    table.insert(list, {code = code, level = level, x = x, y = y, words = where .. words})
end

---------------------------------------------------------------------------
-- Candidate sites
---------------------------------------------------------------------------

-- A full w x h envelope for one level, turned by q, the join at (0, 0) in
-- row 0's middle. with_join false: (0, 0) left out (offset_sites adds it).
function envelope(w, h, q, with_join)
    local a = (w - 1) // 2
    local L = {tiles = {}, halls = {}, dig = {}, kind = 'landmark'}
    for gy = 0, h - 1 do
        for gx = 0, w - 1 do
            local lx, ly = turn_xy(gx - a, gy, q)
            if with_join or not (lx == 0 and ly == 0) then add(L.tiles, lx, ly) end
        end
    end
    local x1, y1, x2, y2 = math.huge, math.huge, -math.huge, -math.huge
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            x1, x2, y1, y2 = math.min(x1, x), math.max(x2, x), math.min(y1, y), math.max(y2, y)
        end
    end
    if not with_join then x1, x2, y1, y2 = math.min(x1, 0), math.max(x2, 0), math.min(y1, 0), math.max(y2, 0) end
    L.bounds = {x1 = x1, y1 = y1, x2 = x2, y2 = y2}
    return L
end

-- The districts of the overseer's plan, as the AI's levels carried them
-- (newest first, one each), then none: the plans the rock search goes by.
function landmark_plans()
    local out, seen = {}, {}
    local list = load_projects().list
    for i = #list, 1, -1 do
        local pl = list[i].plan
        if type(pl) == 'table' and type(pl.district) == 'string' and not seen[pl.district] then
            seen[pl.district] = true
            table.insert(out, pl)
        end
    end
    table.insert(out, false)
    return out
end

-- The boxes no landmark may take: every open project's, and the levels given up lately.
local function reserved_boxes()
    local out = {}
    for _, p in ipairs(open_projects(load_projects())) do
        for _, a in ipairs(project_areas(p)) do table.insert(out, a) end
    end
    return out
end

-- What lies near a site: {'river', 'magma', 'cavern', 'aquifer'} (in that order).
function near_features(x1, y1, x2, y2, zlo, zhi)
    local found = {}
    for z = zlo, zhi do
        for y = y1 - NEAR_REACH, y2 + NEAR_REACH, 2 do
            for x = x1 - NEAR_REACH, x2 + NEAR_REACH, 2 do
                local t = info(x, y, z)
                if t then
                    if t.liquid and t.magma then found.magma = true
                    elseif t.liquid then found.river = true end
                    if t.feature and not t.liquid then found.cavern = true end
                    if t.aquifer then found.aquifer = true end
                end
            end
        end
    end
    local out = {}
    for _, k in ipairs({'river', 'magma', 'cavern', 'aquifer'}) do if found[k] then table.insert(out, k) end end
    return out
end

local NEAR_WORDS = {river = 'by water', magma = 'near magma', cavern = 'near a cavern', aquifer = 'near an aquifer'}

local function stone_words(tok)
    return tok and (tok:lower():gsub('_', ' ')) or nil
end

-- The extended stair's cells (as start_project's): 'i' on an up-only
-- bottom, 'i' between, 'u' on the new level.
local function extension_cells(stair, z)
    local cells = {}
    if stair.bottom_shape == 'STAIR_UP' then table.insert(cells, {z = stair.z_bottom, text = 'i'}) end
    for zz = stair.z_bottom - 1, z + 1, -1 do table.insert(cells, {z = zz, text = 'i'}) end
    table.insert(cells, {z = z, text = 'u'})
    return cells
end

-- On a level below the stair's bottom: the stair extended down to z, and a
-- straight corridor from it in direction d to the join. The site, or nil.
local function extend_site(L, stair, z, d, reserved, deadline, below)
    for corridor = 1, MAX_CORRIDOR do
        if os.clock() > deadline then return nil end
        local path = corridor_path(stair, d, 1, corridor, 0)
        local ax, ay = stair.x + d.x * (1 + corridor), stair.y + d.y * (1 + corridor)
        local extra = {}
        add(extra, 0, 0)
        for _, c in ipairs(path) do add(extra, c.x - ax, c.y - ay) end
        local ok, _, area = check_site(L, extra, ax, ay, z, reserved)
        if ok and check_extension(stair.x, stair.y, stair.z_bottom, z, true) then
            local s = below({z = z, extend = true, anchor = {x = ax, y = ay}, extra = extra, area = area,
                             corridor = corridor, new_corridor = corridor,
                             join = {x = stair.x + d.x - ax, y = stair.y + d.y - ay}})
            if s then return s end
        end
    end
end

-- The rock search: for each district of the plan (then none), each
-- direction (the plan's first), the stairs (the spine first) and their
-- levels (the band's first), the first site where the whole envelope fits:
-- level 1 beside the stair, joined by a corridor to the join (offset_sites,
-- or the stair extended down: extend_site), the levels below it checked as
-- they are. One site a (district, direction) at most.
local function rock_sites(env, n, deadline)
    local stairs, why = find_stairs(STAIRS_TO_TRY)
    if not stairs then return nil, why end
    local reserved = reserved_boxes()
    local found, used, tried = {}, {}, {}
    local last = 'no place in the rock for a ' .. env.w .. 'x' .. env.h .. 'x' .. env.levels .. ' landmark'
    local out_of_time = false
    for _, plan in ipairs(landmark_plans()) do
        local band = plan and plan_band(plan) or nil
        local dirs = plan_dirs(plan or nil)
        local list = plan and spine_first(stairs, plan, band) or stairs
        local district = plan and plan.district or nil
        for _, d in ipairs(dirs) do
            if #found >= n or out_of_time then break end
            local dk = d.x .. ',' .. d.y
            local key = tostring(district) .. '/' .. dk
            local q = Q_OF_DIR[dk]
            local L1 = envelope(env.w, env.h, q, false)
            local Ln = envelope(env.w, env.h, q, true)
            local site
            for _, stair in ipairs(list) do
                if site or out_of_time then break end
                for _, lv in ipairs(stair_levels(stair, band, false)) do
                    if os.clock() > deadline then out_of_time = true break end
                    local z = lv.z
                    local tk = ('%d,%d,%d,%s'):format(stair.x, stair.y, z, dk)
                    if not tried[tk] and z - env.levels + 1 >= 1 then
                        tried[tk] = true
                        -- the levels below level 1, each checked as it is (a
                        -- failure there tries the next corridor length)
                        local function below(cand)
                            local areas = {cand.area}
                            for k = 2, env.levels do
                                local okk, wk, ak = check_site(Ln, {}, cand.anchor.x, cand.anchor.y, z - k + 1, reserved)
                                if not okk then last = wk return nil end
                                table.insert(areas, ak)
                            end
                            cand.areas = areas
                            return cand
                        end
                        local s
                        if lv.extend then
                            s = extend_site(L1, stair, z, d, reserved, deadline, below)
                        else
                            s = offset_sites(L1, stair, z, reserved, function(good, reason_words, cand)
                                if good then return below(cand) end
                                last = reason_words or last
                            end, {d}, nil)
                        end
                        if s then
                            s.stair, s.q, s.dir = stair, q, DIR_NAME[dk]
                            s.district = district
                            s.in_district = band and (z >= band.lo and z <= band.hi) or nil
                            site = s
                            break
                        end
                    end
                end
            end
            if site and not used[key] then
                used[key] = true
                table.insert(found, site)
                for _, a in ipairs(site.areas) do table.insert(reserved, a) end
            end
        end
        if #found >= n or out_of_time then break end
    end
    if #found == 0 then
        return nil, (out_of_time and 'search cut short: ' or '') .. last
    end
    for _, s in ipairs(found) do
        local corr = {}
        for x, col in pairs(s.extra) do
            for y in pairs(col) do if not (x == 0 and y == 0) then table.insert(corr, {x = x, y = y}) end end
        end
        table.sort(corr, function(a, b) return a.x < b.x or (a.x == b.x and a.y < b.y) end)
        local a = s.anchor
        local from = s.join and {x = a.x + s.join.x, y = a.y + s.join.y} or {x = a.x, y = a.y}
        local b = envelope_box(env, s.q, a)
        s.record = {ground = 'rock', z = s.z, anchor = {x = a.x, y = a.y}, q = s.q, dir = s.dir,
                    stair = {x = s.stair.x, y = s.stair.y, z_top = s.stair.z_top, z_bottom = s.stair.z_bottom,
                             bottom_shape = s.stair.bottom_shape},
                    extend = s.extend or nil, corridor = corr, from = from, district = s.district,
                    in_district = s.in_district, depth = s.stair.z_top - s.z,
                    near = near_features(b.x1, b.y1, b.x2, b.y2, s.z - env.levels + 1, s.z),
                    stone = stone_at((b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2, s.z)}
    end
    return found
end

-- The map box of an envelope at anchor a: {x1, y1, x2, y2}.
function envelope_box(env, q, a)
    local b = envelope(env.w, env.h, q, true).bounds
    return {x1 = a.x + b.x1, y1 = a.y + b.y1, x2 = a.x + b.x2, y2 = a.y + b.y2}
end

-- What a surface landmark keeps away from (find_hall_site's): the keep, the
-- halls, the depots' wagon strips, the deep depot's mouth, planned channels,
-- the AI's open projects; each box on its level and the ones beside it.
local function surface_avoid()
    local boxes = {}
    local function box(x1, y1, x2, y2, z, m)
        m = m or 0
        for dz = -1, 1 do
            table.insert(boxes, {x1 = x1 - m, y1 = y1 - m, x2 = x2 + m, y2 = y2 + m, z = z + dz})
        end
    end
    pcall(function()
        local k = keep_data()
        if k and k.x then box(k.x - k.r, k.y - k.r, k.x + k.r, k.y + k.r, k.z, HALL_KEEP_CLEAR) end
    end)
    pcall(function()
        for _, h in ipairs(halls_data().list) do box(h.x1, h.y1, h.x2, h.y2, h.z, HALL_KEEP_CLEAR) end
    end)
    pcall(function()
        for _, dp in ipairs(hall_depots()) do
            box(dp.x1, dp.y1, dp.x2, dp.y2, dp.z, 1)
            local st = depot_strip(dp)
            box(st.x1, st.y1, st.x2, st.y2, st.z, 1)
        end
    end)
    pcall(function()
        for _, m in ipairs(deep_depot_mouth() or {}) do box(m.x, m.y, m.x, m.y, m.z, LANDMARK_WAY_IN_CLEAR) end
    end)
    pcall(function()
        for _, t in ipairs((deep_depot_data() or {}).tiles or {}) do
            if t.r == 'h' then box(t.x, t.y, t.x, t.y, t.z, HALL_CHANNEL_CLEAR) end
        end
    end)
    for _, a in ipairs(reserved_boxes()) do box(a.x1, a.y1, a.x2, a.y2, a.z, 0) end
    return boxes
end

-- Open air over a rectangle at z (the levels a surface landmark rises into).
local function open_air(x1, y1, x2, y2, z)
    for y = y1, y2 do
        for x = x1, x2 do
            local t = info(x, y, z)
            if not (t and t.shape == 'EMPTY' and t.outside and not t.building and not t.liquid) then return false end
        end
    end
    return true
end

-- The surface search: up to n rectangles of open ground near the ways in
-- (find_surface_rect, either way round), each with open air above for its
-- levels; row 0 turned toward the nearest way in.
local function surface_sites(env, n, deadline)
    local anchors = surface_anchors()
    if #anchors == 0 then return nil, 'no way in to build the landmark near' end
    local reserved = surface_avoid()
    local found, last = {}, nil
    for _ = 1, LANDMARK_SITE_TRIES do
        if #found >= n or os.clock() > deadline then break end
        local best, bw, bh
        for _, wh in ipairs(env.w == env.h and {{env.w, env.h}} or {{env.w, env.h}, {env.h, env.w}}) do
            local r, why = find_surface_rect(wh[1], wh[2], LANDMARK_WAY_IN_CLEAR + 1, reserved, GROUND, LANDMARK_MAX_TREES)
            if r and (not best) then best, bw, bh = r, wh[1], wh[2] end
            if not r then last = why or last end
        end
        if not best then break end
        local x1, y1, x2, y2, z = best.x, best.y, best.x + bw - 1, best.y + bh - 1, best.z
        for dz = -1, 1 do table.insert(reserved, {x1 = x1 - 1, y1 = y1 - 1, x2 = x2 + 1, y2 = y2 + 1, z = z + dz}) end
        local air = true
        for k = 2, env.levels do
            if not open_air(x1, y1, x2, y2, z + k - 1) then air = false break end
        end
        if not air then
            last = 'no open sky above the ground for its upper levels'
        else
            -- row 0 toward the nearest way in: north or south when the
            -- rectangle lies as drawn, east or west when it lies turned
            local na, nd = nil, math.huge
            local cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            for _, a in ipairs(anchors) do
                local d = math.max(math.abs(a.x - cx), math.abs(a.y - cy))
                if d < nd then na, nd = a, d end
            end
            local vx, vy = na.x - cx, na.y - cy
            local q
            if env.w == env.h and math.abs(vx) > math.abs(vy) then q = vx > 0 and 1 or 3
            elseif env.w == env.h or bw == env.w then q = vy > 0 and 2 or 0
            else q = vx > 0 and 1 or 3 end
            local b = envelope(env.w, env.h, q, true).bounds
            local a = {x = x1 - b.x1, y = y1 - b.y1}
            table.insert(found, {record = {ground = 'surface', z = z, anchor = a, q = q, trees = #best.trees,
                                           near = near_features(x1, y1, x2, y2, z, z),
                                           way_in = math.floor(nd)}})
        end
    end
    if #found == 0 then return nil, last or 'no open ground near the ways in' end
    return found
end

-- The words for a site (no coordinates: names, depths, stone, features).
local function site_words(r, env)
    local parts = {}
    if r.ground == 'rock' then
        table.insert(parts, r.district and ('in the %s district'):format(r.district) or 'by the main stair')
        table.insert(parts, ('%d level%s below the stair\'s top'):format(r.depth, r.depth == 1 and '' or 's'))
        if r.dir then table.insert(parts, ('%s of it'):format(r.dir)) end
        if r.extend then table.insert(parts, 'the stair dug on down to it') end
    else
        table.insert(parts, ('on open ground %d tiles from the way in'):format(r.way_in or 0))
        if r.trees and r.trees > 0 then table.insert(parts, ('%d tree%s to fell'):format(r.trees, r.trees == 1 and '' or 's')) end
    end
    if r.stone then table.insert(parts, stone_words(r.stone)) end
    for _, f in ipairs(r.near or {}) do table.insert(parts, NEAR_WORDS[f]) end
    return table.concat(parts, ', ')
end

-- Up to n candidate sites for a landmark of this envelope: {ok, asked, sites
-- = {{id, ground, w, h, levels, elevation, district, near, stone, words}}}
-- (no coordinates), the full records kept in BP_SITES_KEY for BP_SITES_DAYS.
-- env = {w, h, levels, ground}; purpose a landmark kind (only kept).
function landmark_sites(env, purpose, n)
    OFFSET = elevation_offset()
    n = math.max(1, math.min(4, math.tointeger(n) or 4))
    local now = now_tick()
    CACHE = {}
    local deadline = os.clock() + SEARCH_SECONDS
    local ok, found, why = pcall(env.ground == 'surface' and surface_sites or rock_sites, env, n, deadline)
    CACHE = nil
    if not ok then return {ok = false, error = 'the site search failed: ' .. tostring(found):sub(1, 160)} end
    if not found then return {ok = false, error = why or 'no site found'} end
    local kept, out = {}, {}
    for i, s in ipairs(found) do
        local r = s.record
        r.id = 'S' .. i
        r.w, r.h, r.levels = env.w, env.h, env.levels
        r.elevation = ez(r.z)
        r.words = site_words(r, env)
        table.insert(kept, r)
        table.insert(out, {id = r.id, ground = r.ground, w = r.w, h = r.h, levels = r.levels,
                           elevation = r.elevation, district = r.district, near = r.near,
                           stone = stone_words(r.stone), words = r.words})
    end
    site_put(BP_SITES_KEY, {asked = now, purpose = purpose, env = {w = env.w, h = env.h, levels = env.levels,
                            ground = env.ground}, list = kept})
    return {ok = true, asked = now, sites = out}
end

-- A site offered lately, by id: the record, or nil and why (SITE_GONE).
function offered_site(id)
    local d = site_get(BP_SITES_KEY)
    if type(d.list) ~= 'table' or not tonumber(d.asked) then return nil, 'no sites were offered lately' end
    if now_tick() - d.asked > BP_SITES_DAYS * 1200 then
        return nil, ('the sites offered are over %d days old'):format(BP_SITES_DAYS)
    end
    for _, r in ipairs(d.list) do if r.id == id then return r end end
    return nil, ('no site %s among those offered'):format(tostring(id))
end

---------------------------------------------------------------------------
-- The map checks
---------------------------------------------------------------------------

-- check_site's words (natural_wall's and its own) as a refusal code.
local function code_of(why)
    why = tostring(why or '')
    if why:find('map edge', 1, true) then return 'EDGE' end
    if why:find('another AI project', 1, true) then return 'OVERLAP' end
    if why:find('directly above', 1, true) or why:find('above', 1, true) and why:find('aquifer', 1, true) then return 'DAMP' end
    if why:find('aquifer', 1, true) then return 'AQUIFER' end
    if why:find('water or magma', 1, true) or why:find('warm stone', 1, true) then return 'LIQUID' end
    if why:find('cavern', 1, true) then return 'CAVERN' end
    if why:find('open to the sky', 1, true) then return 'SURFACE' end
    return 'ROCK'
end

local WHY_WORDS = {
    aquifer = 'an aquifer', ['water or magma'] = 'water or magma', ['cavern, magma sea or special vein'] = 'a cavern',
    ['open to the sky'] = 'open to the sky', ['warm stone (magma nearby)'] = 'warm stone (magma near)',
    ['not solid rock (already dug or open)'] = 'not solid rock (dug or open)',
    ['already designated for digging'] = 'designated for digging', ['a building is there'] = 'a building',
}

-- The checks of one rock level, tile by tile, every reason (check_site's
-- checks, positions on the drawing's grid). `extra` the corridor (level 1),
-- exempt(x, y, t) the border tiles where it opens on the fort.
local function rock_level_reasons(bp, q, k, L, extra, ax, ay, z, reserved, exempt, out)
    local w, h = map_size()
    local b = L.bounds
    local area = {x1 = ax + b.x1 - 1, y1 = ay + b.y1 - 1, x2 = ax + b.x2 + 1, y2 = ay + b.y2 + 1, z = z}
    if area.x1 < 1 or area.y1 < 1 or area.x2 > w - 2 or area.y2 > h - 2 then
        reason(out, 'EDGE', k, nil, nil, 'too close to the map\'s edge')
        return
    end
    for _, r in ipairs(reserved or {}) do
        if overlaps(area, r) then reason(out, 'OVERLAP', k, nil, nil, 'overlaps another of the AI\'s levels') return end
    end
    local function dug(x, y) return has(L.tiles, x, y) or has(extra, x, y) end
    local seen = {}
    local function look(x, y, beside)
        local t = info(ax + x, ay + y, z)
        local ok, why = natural_wall(t)
        if not ok and beside and exempt and exempt(ax + x, ay + y, t) then ok = true end
        if not ok then
            local gx, gy = grid_xy(bp, q, x, y)
            reason(out, code_of(why), k, gx, gy, (WHY_WORDS[why] or why) .. (beside and ' beside this tile' or ''))
        end
    end
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do
            look(x, y, false)
            local up = info(ax + x, ay + y, z + 1)
            if up and (up.aquifer or up.liquid) then
                local gx, gy = grid_xy(bp, q, x, y)
                reason(out, 'DAMP', k, gx, gy, (up.aquifer and 'an aquifer' or 'water') .. ' directly above')
            end
        end
    end
    for _, set in ipairs({L.tiles, extra}) do
        for x, col in pairs(set) do
            for y in pairs(col) do
                for dx = -1, 1 do
                    for dy = -1, 1 do
                        local nx, ny = x + dx, y + dy
                        if not dug(nx, ny) and not has(seen, nx, ny) then
                            add(seen, nx, ny)
                            look(nx, ny, true)
                        end
                    end
                end
            end
        end
    end
end

-- A surface tile in words, when it can't take the landmark (keep_tile's view).
local function surface_tile_reason(x, y, z, upper)
    local t = info(x, y, z)
    if upper then
        if t and t.shape == 'EMPTY' and t.outside and not t.building and not t.liquid then return nil end
        if t and t.liquid then return 'LIQUID', 'water in the air above the ground' end
        return 'SURFACE', 'no open air here'
    end
    local v = keep_tile(x, y, z)
    if v == 'ground' or v == 'tree' then return nil, nil, v end
    if t and t.liquid then return 'LIQUID', 'water' end
    if t and t.feature then return 'CAVERN', 'a cavern' end
    if v == 'wall' then return 'ROCK', 'rock or a wall' end
    if v == 'planned' then return 'ROCK', 'something being built' end
    return 'SURFACE', keep_tile_why(x, y, z)
end

-- (D0) The walk test: from each way in on the landmark's level, can the
-- dwarves still walk to the map's edge and to every depot, with the
-- planned walls (W, O) and statues standing? A target reached before but
-- not after is a cut. Returns true, or false and why.
local function walkable(t)
    return t ~= nil and not t.liquid and t.shape ~= 'WALL' and t.shape ~= 'EMPTY' and t.shape ~= 'NONE'
        and not is_tree(t)
end

function paths_kept(placed, z)
    local anchors = {}
    for _, a in ipairs(surface_anchors()) do if a.z == z then table.insert(anchors, a) end end
    if #anchors == 0 then return true end           -- no way in on this level: nothing to cut on it [verify]
    local mw, mh = map_size()
    local depots = {}
    for _, dp in ipairs(hall_depots()) do if dp.z == z then table.insert(depots, dp) end end
    local deadline = os.clock() + WALK_SECONDS
    local function flood(blocked)
        local seen, queue, head = {}, {}, 1
        local reached = {edge = false}
        local n = 0
        for _, a in ipairs(anchors) do
            local k = a.y * 4096 + a.x
            if not seen[k] then seen[k] = true; table.insert(queue, a) end
        end
        while head <= #queue do
            local p = queue[head]; head = head + 1
            n = n + 1
            if n > WALK_NODES or os.clock() > deadline then return nil end
            if p.x <= 1 or p.y <= 1 or p.x >= mw - 2 or p.y >= mh - 2 then reached.edge = true end
            for i, dp in ipairs(depots) do
                if p.x >= dp.x1 - 1 and p.x <= dp.x2 + 1 and p.y >= dp.y1 - 1 and p.y <= dp.y2 + 1 then reached[i] = true end
            end
            local done = reached.edge
            for i = 1, #depots do done = done and reached[i] == true end
            if done then return reached end
            for dx = -1, 1 do
                for dy = -1, 1 do
                    if dx ~= 0 or dy ~= 0 then
                        local x, y = p.x + dx, p.y + dy
                        local k = y * 4096 + x
                        if not seen[k] and x >= 0 and y >= 0 and x < mw and y < mh then
                            seen[k] = true
                            if not blocked[k] and walkable(info(x, y, z)) then table.insert(queue, {x = x, y = y}) end
                        end
                    end
                end
            end
        end
        return reached
    end
    local before = flood({})
    if not before then return false, 'the walk test ran out of time' end
    local blocked = {}
    for _, c in ipairs(placed) do blocked[c.y * 4096 + c.x] = true end
    local after = flood(blocked)
    if not after then return false, 'the walk test ran out of time' end
    if before.edge and not after.edge then return false, 'would cut the way in off from the map\'s edge' end
    for i = 1, #depots do
        if before[i] and not after[i] then return false, 'would cut the way in off from the trade depot' end
    end
    return true
end

-- (E1) An opening's drop: for each '*' (a layout's 'open' cell), the level it
-- lands on (the first below it with no opening there); when that is the
-- drawing's lowest level, the tile under the landing floor must hold it: no
-- water, magma, cavern, aquifer or open sky. Reasons go in `out`.
function open_drop_reasons(bp, plan, a, out)
    local n = #plan.levels
    local open_at = {}
    for k, lv in ipairs(plan.levels) do
        open_at[k] = {}
        for _, c in ipairs(lv.L.open or {}) do open_at[k][c.x .. ',' .. c.y] = true end
    end
    local told = {}
    for k, lv in ipairs(plan.levels) do
        for _, c in ipairs(lv.L.open or {}) do
            local j = k + 1
            while j <= n and open_at[j][c.x .. ',' .. c.y] do j = j + 1 end
            local key = c.x .. ',' .. c.y
            if j == n and not told[key] then
                told[key] = true
                local t = info(a.x + c.x, a.y + c.y, plan.levels[n].z - 1)
                local code, words
                if t and t.liquid then code, words = 'LIQUID', t.magma and 'magma' or 'water'
                elseif t and t.feature then code, words = 'CAVERN', 'a cavern'
                elseif t and t.aquifer then code, words = 'AQUIFER', 'an aquifer'
                elseif t and t.outside then code, words = 'SURFACE', 'open sky' end
                if code then
                    local gx, gy = grid_xy(bp, plan.q, c.x, c.y)
                    reason(out, code, k, gx, gy, words .. ' under the floor this opening drops to')
                end
            end
        end
    end
end

-- The placement of a drawing on a site: per level {k, z, L, cells, ...}.
local function placement(bp, site)
    local B = blueprints()
    local q = site.q
    local tl = B.to_layouts(bp, q)
    local cells = grid_cells(bp, q)
    local levels = {}
    for k, L in ipairs(tl.levels) do
        levels[k] = {k = k, L = L, z = site.z + (tl.dz and tl.dz[k] or (site.ground == 'surface' and (k - 1) or -(k - 1))),
                     cells = cells[k] or {}}
    end
    return {q = q, levels = levels}
end

local BLOCKS_WALK = {W = true, O = true}

-- Does the drawing pass on this site? ok, reasons (8 at most, each {code,
-- level, x, y, words}), and the placement (for start_landmark).
-- `site` an offered site's record; `cap` the most jobs it may cost.
function validate_landmark(bp, site, cap)
    local B = blueprints()
    local out = {}
    local okf, fr = B.check_format(bp)
    if not okf then
        for _, r in ipairs(fr or {}) do
            if #out < LANDMARK_REASONS_MAX then table.insert(out, r) end
        end
        if #out == 0 then reason(out, 'FORMAT', nil, nil, nil, 'the drawing is not in the format') end
        return false, out
    end
    if type(site) ~= 'table' then
        reason(out, 'SITE_GONE', nil, nil, nil, 'no such site')
        return false, out
    end
    local ground = bp.ground == 'surface' and 'surface' or 'rock'
    if ground ~= site.ground then
        reason(out, 'SITE_GONE', nil, nil, nil, ('the site is %s, the drawing is %s'):format(
            site.ground == 'surface' and 'on the surface' or 'in the rock', ground == 'surface' and 'for the surface' or 'for the rock'))
        return false, out
    end
    OFFSET = elevation_offset()
    CACHE = {}
    local okp, plan = pcall(placement, bp, site)
    if not okp then
        CACHE = nil
        reason(out, 'QUICKFORT', nil, nil, nil, 'the drawing could not be laid out: ' .. tostring(plan):sub(1, 120))
        return false, out
    end
    local a = site.anchor
    local reserved = reserved_boxes()
    local placed_walls = {}
    local ok_map, err = pcall(function()
        if ground == 'rock' then
            local extra = {}
            for _, c in ipairs(site.corridor or {}) do add(extra, c.x, c.y) end
            local group = walk_group(site.stair.x, site.stair.y, site.z)
            local from = site.from or a
            local exempt = function(x, y, t)
                return math.max(math.abs(x - from.x), math.abs(y - from.y)) <= 1 and t ~= nil and t.shape ~= 'WALL'
                    and not t.liquid and not t.aquifer and not t.feature and not t.outside
                    and group ~= 0 and walk_group(x, y, site.z) == group
            end
            for k, lv in ipairs(plan.levels) do
                local before = #out
                rock_level_reasons(bp, plan.q, k, lv.L, k == 1 and extra or {}, a.x, a.y, lv.z, reserved,
                                   k == 1 and exempt or nil, out)
                -- check_site, the levels' own test, has the last word
                if #out == before then
                    local okc, why = check_site(lv.L, k == 1 and extra or {}, a.x, a.y, lv.z, reserved, nil,
                                                k == 1 and exempt or nil)
                    if not okc then reason(out, code_of(why), k, nil, nil, (tostring(why):gsub(' at x%-?%d+ y%-?%d+ z%-?%d+', ''))) end
                end
                if #out >= LANDMARK_REASONS_MAX then break end
            end
            -- (E1) where an opening drops to: the floor it lands on, on the
            -- drawing's lowest level, stands on no water, magma, cavern,
            -- aquifer or open sky (the tiles on the way down are dug tiles,
            -- checked above with what is beside them)
            if #out == 0 then open_drop_reasons(bp, plan, a, out) end
            if site.extend and #out == 0 then
                local okx, why = check_extension(site.stair.x, site.stair.y, site.stair.z_bottom, site.z, true)
                if not okx then reason(out, code_of(why), 1, nil, nil, 'the stair down to it: '
                    .. (tostring(why):gsub(' at x%-?%d+ y%-?%d+ z%-?%d+', ''):gsub('z%-?%d+', 'its level'))) end
            end
        else
            local anchors = surface_anchors()
            local mouth = {}
            pcall(function() mouth = deep_depot_mouth() or {} end)
            local trees = 0
            for k, lv in ipairs(plan.levels) do
                for _, c in ipairs(lv.cells) do
                    local x, y = a.x + c.lx, a.y + c.ly
                    local code, words, v = surface_tile_reason(x, y, lv.z, k > 1)
                    if code then reason(out, code, k, c.gx, c.gy, words) end
                    if v == 'tree' then trees = trees + 1 end
                    if k == 1 then
                        local near
                        for _, an in ipairs(anchors) do
                            if math.abs(an.z - lv.z) <= 1 and math.max(math.abs(an.x - x), math.abs(an.y - y)) <= LANDMARK_WAY_IN_CLEAR then
                                near = 'too near a way in'
                            end
                        end
                        for _, m in ipairs(mouth) do
                            if math.abs(m.z - lv.z) <= 1 and math.max(math.abs(m.x - x), math.abs(m.y - y)) <= LANDMARK_WAY_IN_CLEAR then
                                near = 'too near the depot road\'s mouth'
                            end
                        end
                        if near then reason(out, 'WAY_IN', k, c.gx, c.gy, near) end
                        if BLOCKS_WALK[c.sym] or (c.sym:match('%l') and type(bp.legend) == 'table' and bp.legend[c.sym] == 'Statue') then
                            table.insert(placed_walls, {x = x, y = y})
                        end
                    end
                end
            end
            if trees > LANDMARK_MAX_TREES then
                reason(out, 'TREES', 1, nil, nil, ('%d trees to fell (%d at most)'):format(trees, LANDMARK_MAX_TREES))
            end
            -- (E2) the build order, and the scaffold stairs' tiles in the air
            if #out == 0 and B.build_stages then
                local stg, why = B.build_stages(bp, plan.q)
                if not stg then
                    for _, r in ipairs(why or {}) do
                        reason(out, r.code or 'ORDER', r.level, r.x, r.y, (tostring(r.words or 'no safe build order')
                            :gsub('^L%d+ x%d+ y%d+: ', ''):gsub('^L%d+: ', '')))
                    end
                else
                    plan.stages = stg
                    for _, st in ipairs(stg.list) do
                        if st.kind == 'scaffold' and st.dz > 0 then
                            for _, c in ipairs(st.cells) do
                                local code, words = surface_tile_reason(a.x + c.x, a.y + c.y, site.z + st.dz, true)
                                if code then reason(out, code, st.level, c.gx, c.gy, 'the scaffold stair: ' .. words) end
                            end
                        end
                    end
                end
            end
            if #out == 0 then
                local okw, why = paths_kept(placed_walls, plan.levels[1].z)
                if not okw then reason(out, 'PATH', 1, nil, nil, why) end
            end
        end
    end)
    if not ok_map then
        CACHE = nil
        reason(out, 'QUICKFORT', nil, nil, nil, 'the map check failed: ' .. tostring(err):sub(1, 120))
        return false, out, plan
    end
    -- cost and stock
    local c = B.cost(bp)
    plan.cost = c
    local limit = math.min(math.tointeger(cap) or B.BP_LIMITS.cost_max, B.BP_LIMITS.cost_max)
    if c.jobs > limit then reason(out, 'COST', nil, nil, nil, ('%d jobs, over the cap of %d'):format(c.jobs, limit)) end
    -- (E2) the scaffolding's tiles stand at the same time as the shape's
    local built = c.built + (plan.stages and plan.stages.scaffold and plan.stages.scaffold.tiles or 0)
    if built > 0 then
        local stock = landmark_stock()
        if built > LANDMARK_STOCK_SHARE * stock then
            reason(out, 'STOCK', nil, nil, nil, ('%d built tiles, over %d%% of the %d boulders and blocks on hand')
                :format(built, math.floor(LANDMARK_STOCK_SHARE * 100), stock))
        end
    end
    -- the slots and the times
    local open = open_projects(load_projects())
    if #open >= slot_cap(open) then
        reason(out, 'SLOTS', nil, nil, nil, ('no building slot free (%d projects open)'):format(#open))
    end
    local bad = landmark_times()
    if bad then reason(out, 'TIMES', nil, nil, nil, 'not now: ' .. bad) end
    -- Quickfort's dry run agrees on every tile it can test now: each rock
    -- level's digging (exactly), a surface landmark's first level of
    -- building (but the trees, felled first)
    if #out == 0 then
        for k, lv in ipairs(plan.levels) do
            if ground == 'rock' then
                local dig = landmark_dig_cells(lv, site, k)
                local want = count(layouts.tiles_from_dig(dig))
                local okq, dry = pcall(quickfort_apply, 'dig', dig, lv.z, a.x, a.y, 'run', true)
                if not okq or stat(dry, 'dig_designated') ~= want or stat(dry, 'dig_invalid_tiles') > 0
                        or stat(dry, 'out_of_bounds') > 0 or stat(dry, 'invalid_keys') > 0 then
                    reason(out, 'QUICKFORT', k, nil, nil, ('the game would dig %d of its %d tiles'):format(
                        okq and stat(dry, 'dig_designated') or 0, want)
                        .. (okq and dig_guard_note(dry) or ''))   -- (0.105.40b fix) the guard's why
                end
            elseif k == 1 then
                local cells = landmark_surface_cells(lv, 'walls', true, a)
                if #cells > 0 then
                    local good = qf_try('build', cells, lv.z, a.x, a.y, true)
                    if not good then reason(out, 'QUICKFORT', k, nil, nil, 'the game would not place its walls') end
                end
            end
        end
    end
    CACHE = nil
    return #out == 0, out, plan
end

---------------------------------------------------------------------------
-- Building it
---------------------------------------------------------------------------

-- A rock level's dig cells: the layout's, and on level 1 the corridor.
function landmark_dig_cells(lv, site, k)
    local cells = {}
    for _, c in ipairs(lv.L.dig or {}) do table.insert(cells, c) end
    if k == 1 then
        for _, c in ipairs(site.corridor or {}) do table.insert(cells, {x = c.x, y = c.y, text = 'd'}) end
    end
    return cells
end

local WALL_KEYS = {Cw = true, CF = true}
local FLOOR_KEYS = {Cf = true, Cr = true, Cu = true, Cd = true, Cx = true}

-- A surface level's cells for a stage ('walls': Cw, CF and the doors;
-- 'floor': Cf, Cr and the stairs; 'furnish': the rest of the buildings),
-- relative to the anchor. skip_trees: not on a tree (felled first).
function landmark_surface_cells(lv, stage, skip_trees, anchor)
    local out = {}
    local trees = {}
    if skip_trees and anchor then
        for _, c in ipairs(lv.cells) do
            if is_tree(info(anchor.x + c.lx, anchor.y + c.ly, lv.z)) then trees[c.lx .. ',' .. c.ly] = true end
        end
    end
    local function take(c) if not trees[c.x .. ',' .. c.y] then table.insert(out, {x = c.x, y = c.y, text = c.text}) end end
    if stage == 'walls' or stage == 'floor' then
        for _, c in ipairs(lv.L.construct or {}) do
            if (stage == 'walls' and WALL_KEYS[c.text]) or (stage == 'floor' and FLOOR_KEYS[c.text]) then take(c) end
        end
    end
    for _, c in ipairs(lv.L.build or {}) do
        local door = c.text == 'd'
        if (stage == 'walls' and door) or (stage == 'furnish' and not door) then take(c) end
    end
    return out
end

local function now_date(now)
    if type(now) == 'table' then return now end
    local t = now_tick()
    return {year = t // 403200, tick = t % 403200}
end

-- Start a drawing that passed validate_landmark: rock levels designated
-- level by level (all undone on any failure, as start_project does), one
-- project a level (kind 'landmark'); a surface landmark's trees marked and
-- its record left at 'clearing' for landmark_step. The record in LANDMARKS_KEY.
-- meta = {name, purpose, by, deity_hf}. now = {year, tick}.
function start_landmark(bp, site, meta, now, dry_run, plan)
    OFFSET = elevation_offset()
    local B = blueprints()
    if not plan then
        local ok, reasons, p = validate_landmark(bp, site, meta and meta.cap)
        if not ok then return {ok = false, rejected = true, error = reasons[1] and reasons[1].words or 'refused',
                               reasons = reasons} end
        plan = p
    end
    local lm = landmarks_data()
    local id = lm.next
    local cost = plan.cost or B.cost(bp)
    local zone = type(bp.zone) == 'table' and bp.zone.kind or nil
    local zone_level = type(bp.zone) == 'table' and math.tointeger(bp.zone.level) or 1
    local finish = type(bp.finish) == 'table' and bp.finish or {}
    local mats = type(bp.materials) == 'table' and bp.materials or {}
    local style = {smooth = math.tointeger(finish.smooth) or 0, engrave = finish.engrave,
                   palette = mats.palette, landmark = true}
    local out = {ok = true, landmark_id = id, project_ids = {}, levels = #plan.levels, quarter = plan.q,
                 cost = cost, ground = site.ground, dry_run = dry_run or nil}
    if dry_run then return out end
    local a = site.anchor
    local rec = {landmark_id = id, name = meta.name, purpose = meta.purpose, by = meta.by, ground = site.ground,
                 status = 'building', levels = #plan.levels, quarter = plan.q, cost = cost, started = now_date(now),
                 deity_hf = meta.deity_hf, zone = zone, words = site.words, project_ids = {}}
    if site.ground == 'rock' then
        local data = load_projects()
        local done = {}
        local stairs = site.extend and extension_cells(site.stair, site.z) or {}
        local okd, err = pcall(function()
            for k, lv in ipairs(plan.levels) do
                local dig = landmark_dig_cells(lv, site, k)
                local want = count(layouts.tiles_from_dig(dig))
                table.insert(done, {dig = dig, z = lv.z})
                local real = quickfort_apply('dig', dig, lv.z, a.x, a.y)
                if stat(real, 'dig_designated') ~= want then
                    error(('level %d: %d of %d tiles designated'):format(k, stat(real, 'dig_designated'), want))
                end
                if k == 1 then
                    for _, c in ipairs(stairs) do
                        local s = quickfort_apply('dig', {{x = 0, y = 0, text = c.text}}, c.z, site.stair.x, site.stair.y)
                        if stat(s, 'dig_designated') ~= 1 then error('could not designate the stair down to it') end
                    end
                end
            end
        end)
        local function undo_all()
            for i, dn in ipairs(done) do
                undo_dig(dn.dig, i == 1 and stairs or nil, dn.z, a, site.stair)
            end
        end
        if not okd then
            undo_all()
            return {ok = false, rejected = true, error = 'designating failed and was undone: ' .. tostring(err),
                    reasons = {{code = 'QUICKFORT', words = 'designating failed and was undone'}}}
        end
        local extra = {}
        for _, c in ipairs(site.corridor or {}) do add(extra, c.x, c.y) end
        add(extra, 0, 0)
        for k, lv in ipairs(plan.levels) do
            local L = lv.L
            local dig = done[k].dig
            local tiles = layouts.tiles_from_dig(dig)
            local x1, y1, x2, y2 = math.huge, math.huge, -math.huge, -math.huge
            for x, col in pairs(tiles) do
                for y in pairs(col) do
                    x1, x2, y1, y2 = math.min(x1, x), math.max(x2, x), math.min(y1, y), math.max(y2, y)
                end
            end
            local build = {}
            for _, c in ipairs(L.build or {}) do table.insert(build, c) end
            local decor = decoration_cells(L, {anchor = a, z = lv.z, extra = k == 1 and extra or {}}, build)
            local p = {
                id = data.next_id, kind = 'landmark', phase = 'dig',
                params = {landmark_id = id, level = k, name = meta.name, purpose = meta.purpose, style = style,
                          deity_hf = meta.deity_hf, zone = (zone_level == k) and zone or nil},
                stair = {x = site.stair.x, y = site.stair.y}, anchor = {x = a.x, y = a.y}, z = lv.z,
                area = {x1 = a.x + x1 - 1, y1 = a.y + y1 - 1, x2 = a.x + x2 + 1, y2 = a.y + y2 + 1, z = lv.z},
                corridor = k == 1 and #(site.corridor or {}) or 0, new_corridor = k == 1 and #(site.corridor or {}) or 0,
                stairs = k == 1 and stairs or {}, summary = L.summary, furniture = L.furniture,
                cells = {dig = dig, build = build, place = L.place or {}, zone = (zone_level == k) and (L.zone or {}) or {},
                         smooth = decor.smooth, engrave = decor.engrave},
                started = now, designated = count(tiles),
                plan = site.district and {district = site.district} or nil, in_district = site.in_district,
            }
            data.next_id = data.next_id + 1
            table.insert(data.list, p)
            table.insert(rec.project_ids, p.id)
        end
        if not save_projects(data) then
            undo_all()
            return {ok = false, error = 'could not save the landmark\'s levels with the fort, so they were undone'}
        end
        rec.stage = 'dig'
        -- (E1) the openings and rails, cut and built by landmark_step once dug
        local open = open_plan(plan, a)
        if #open > 0 then rec.open = open end
    else
        -- surface: the cells in map coordinates, by level, for the stages
        local lvls = {}
        local trees = {}
        for k, lv in ipairs(plan.levels) do
            local function abs(list)
                local o = {}
                for _, c in ipairs(list) do table.insert(o, {x = a.x + c.x, y = a.y + c.y, text = c.text}) end
                return o
            end
            lvls[k] = {z = lv.z, walls = abs(landmark_surface_cells(lv, 'walls')),
                       floor = abs(landmark_surface_cells(lv, 'floor')),
                       furnish = abs(landmark_surface_cells(lv, 'furnish')),
                       place = abs(lv.L.place or {}), zone = (zone_level == k) and abs(lv.L.zone or {}) or {}}
            if k == 1 then
                for _, c in ipairs(lv.cells) do
                    local x, y = a.x + c.lx, a.y + c.ly
                    if is_tree(tile_info(x, y, lv.z)) then table.insert(trees, {x = x, y = y, z = lv.z}) end
                end
            end
        end
        for _, t in ipairs(trees) do fell_tree(t.x, t.y, t.z) end
        rec.surface, rec.stage, rec.level = lvls, 'clearing', 1
        rec.trees = trees
        -- (E2) the build order: one step at a time, scaffolding included
        local stg = plan.stages
        if not stg and B.build_stages then stg = B.build_stages(bp, plan.q) end
        if stg then
            rec.steps, rec.step = {}, 0
            rec.scaffold = {columns = stg.scaffold.columns, tiles = stg.scaffold.tiles}
            for _, st in ipairs(stg.list) do
                local z = site.z + st.dz
                local cells, cut = {}, nil
                for _, c in ipairs(st.cells) do table.insert(cells, {x = a.x + c.x, y = a.y + c.y, text = c.text}) end
                if st.cut then
                    cut = {}
                    for _, c in ipairs(st.cut) do table.insert(cut, {x = a.x + c.x, y = a.y + c.y, z = site.z + c.dz}) end
                end
                table.insert(rec.steps, {kind = st.kind, level = st.level, z = z, cells = cells, cut = cut})
            end
            for _, l in ipairs(lvls) do l.walls, l.floor = {}, {} end    -- (the steps hold them)
        end
    end
    lm.next = id + 1
    table.insert(lm.list, rec)
    if not save_landmarks(lm) then
        out.warning = 'the landmark\'s record could not be saved'
    end
    out.project_ids = rec.project_ids
    return out
end

-- The bridge's entry: a drawing on an offered site. Refused with every
-- reason (8 at most), else started (dry_run: checked only).
function build_landmark(bp, site_id, meta, now, dry_run)
    local site, why = offered_site(site_id)
    if not site then
        return {ok = false, rejected = true, error = why,
                reasons = {{code = 'SITE_GONE', words = why}}}
    end
    local ok, reasons, plan = validate_landmark(bp, site, meta.cap)
    if not ok then
        return {ok = false, rejected = true, error = reasons[1] and reasons[1].words or 'refused', reasons = reasons}
    end
    local r = start_landmark(bp, site, meta, now, dry_run, plan)
    if r.ok and not dry_run then
        -- the site is taken: offered no more
        local d = site_get(BP_SITES_KEY)
        if type(d.list) == 'table' then
            for i, s in ipairs(d.list) do if s.id == site_id then table.remove(d.list, i) break end end
            site_put(BP_SITES_KEY, d)
        end
    end
    return r
end

---------------------------------------------------------------------------
-- The surface stages (landmark_step), on the pattern of place_hall
---------------------------------------------------------------------------

local BUILT_AS = {Cw = 'WALL', CF = 'FORTIFICATION', Cf = 'FLOOR', Cr = 'RAMP', Cu = 'STAIR_UP', Cd = 'STAIR_DOWN',
                  Cx = 'STAIR_UPDOWN'}

-- Cells still waiting to be built (planned): a construction waiting is a
-- building on its tile; a building waits while buildingplan finds its materials.
local function waiting(cells, z)
    local n = 0
    for _, c in ipairs(cells) do
        local t = tile_info(c.x, c.y, z)
        if BUILT_AS[c.text] then
            if t and t.building then n = n + 1 end
        elseif hall_planned_at(c.x, c.y, z) then
            n = n + 1
        end
    end
    return n
end

local function trees_standing(rec)
    local n = 0
    for _, t in ipairs(rec.trees or {}) do if is_tree(tile_info(t.x, t.y, t.z)) then n = n + 1 end end
    return n
end

-- (E2) Scaffolding: taking a tile down (a construction marked for removal)
-- and who stands where. Tests swap both.
function remove_construction(x, y, z, dry_run)
    if dry_run then return true end
    local ok, r = pcall(function() return dfhack.constructions.designateRemove(xyz2pos(x, y, z)) end)
    return ok and r and true or false
end

-- How many living units stand on these tiles ({x, y, z} each). (0.105.37
-- fix) Fails closed: nil when the units can't be read (the caller waits).
function units_on(tiles)
    local want = {}
    for _, t in ipairs(tiles) do want[(t.z * 4096 + t.y) * 4096 + t.x] = true end
    local ok, n = pcall(function()
        local c = 0
        for _, u in ipairs(df.global.world.units.active) do
            if not dfhack.units.isDead(u) then
                local x, y, z = dfhack.units.getPosition(u)
                if x and want[(z * 4096 + y) * 4096 + x] then c = c + 1 end
            end
        end
        return c
    end)
    if not ok or type(n) ~= 'number' then return nil end
    return n
end

-- (0.105.37 fix) The tiles a removal must find empty: each tile taken down,
-- the one over it (a dwarf on the stair's top), and the tiles it cuts off.
local function removal_tiles(st)
    local tiles = {}
    for _, c in ipairs(st.cells) do
        table.insert(tiles, {x = c.x, y = c.y, z = st.z})
        table.insert(tiles, {x = c.x, y = c.y, z = st.z + 1})
    end
    for _, c in ipairs(st.cut or {}) do table.insert(tiles, c) end
    return tiles
end

-- nil when the removal may go ahead, else the words and whether it is a
-- wait (a removal that cuts tiles off is refused, not waited on: an old
-- record's; the planner no longer makes them)
local function removal_blocked(st, name)
    if #(st.cut or {}) > 0 then
        return ('%s: taking this scaffolding down would cut %d tile(s) off; it stays up'):format(name, #st.cut), false
    end
    local ok, who = pcall(units_on, removal_tiles(st))
    if not ok or type(who) ~= 'number' then
        return ('%s: who stands on the scaffolding can\'t be read; it comes down when it can'):format(name), true
    end
    if who > 0 then
        return ('%s: %d dwarf(s) on or above the scaffolding; it comes down when they leave'):format(name, who), true
    end
    return nil
end

local STAIR_SHAPES = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true}

-- What a step still waits for: its tiles to be built (planned buildings
-- left), or (a removal) its scaffold stairs to come down.
local function step_left(st)
    if not st then return 0 end
    if st.kind == 'remove' then
        local n = 0
        for _, c in ipairs(st.cells) do
            local t = tile_info(c.x, c.y, st.z)
            if t and STAIR_SHAPES[t.shape] then n = n + 1 end
        end
        return n
    end
    return waiting(st.cells, st.z)
end

-- The scaffolding's state for the report: {columns, tiles, up, next, ready}.
-- up: its tiles placed and not yet taken down; next: the next step's kind;
-- ready: the current step is done (the next can be placed).
local function scaffold_state(rec)
    if type(rec.steps) ~= 'table' then return nil end
    local sc = type(rec.scaffold) == 'table' and rec.scaffold or {}
    local up = 0
    local k = math.tointeger(rec.step) or 0
    for i = 1, math.min(k, #rec.steps) do
        local st = rec.steps[i]
        if st.kind == 'scaffold' then up = up + #st.cells elseif st.kind == 'remove' then up = up - #st.cells end
    end
    local cur = rec.steps[k]
    if cur and cur.kind == 'remove' then up = up + step_left(cur) end
    local nxt = rec.steps[k + 1]
    local ok, left = pcall(step_left, cur)
    return {columns = sc.columns or 0, tiles = sc.tiles or 0, up = math.max(up, 0),
            next = nxt and nxt.kind or (k >= #rec.steps and k > 0 and 'furnish' or nil),
            ready = (rec.stage ~= 'clearing' and ok and left == 0) or nil}
end

-- (E1) Openings in the rock: cut in waves, then railed.

-- The openings and rails of a placed drawing, per level that has any, in map
-- coordinates: {level, z, waves = {{cells 'h'}...} (the first cut first),
-- wave = 0 (the last designated), rails = {cells 'CF'}, railed, tries}.
function open_plan(plan, a)
    local out = {}
    for k, lv in ipairs(plan.levels) do
        local waves, rails = {}, {}
        for _, c in ipairs(lv.L.open or {}) do
            local w = math.tointeger(c.wave) or 1
            waves[w] = waves[w] or {}
            table.insert(waves[w], {x = a.x + c.x, y = a.y + c.y, text = c.text})
        end
        for _, c in ipairs(lv.L.construct or {}) do
            table.insert(rails, {x = a.x + c.x, y = a.y + c.y, text = c.text})
        end
        if #waves > 0 or #rails > 0 then
            table.insert(out, {level = k, z = lv.z, waves = waves, wave = 0, rails = rails, railed = false, tries = 0})
        end
    end
    return out
end

local function phase_of(data, pid)
    for _, p in ipairs(data.list) do if p.id == pid then return p.phase end end
end

-- Is a channel cut? (the floor gone: open space, or a ramp's top)
local function cut_done(t)
    return t ~= nil and t.shape ~= 'WALL' and t.shape ~= 'FLOOR'
end

-- One level's openings: what they wait on, and what to do next.
-- Returns state ('dig' | 'ready' | 'waiting' | 'done') and the action when
-- ready ('wave' | 'redo' | 'rails'), with the cells to redo.
local function open_state(rec, e, data)
    if e.done then return 'done' end
    if e.stalled then return 'stalled' end
    local ids = rec.project_ids or {}
    local function dug(pid)      -- (a level closed long ago is no longer listed: dug)
        return pid ~= nil and phase_of(data, pid) ~= 'dig'
    end
    -- this level dug (the openings and rails are dug floor first), and the
    -- level below, which the openings open onto
    if not dug(ids[e.level]) then return 'dig' end
    if #e.waves > 0 and not dug(ids[e.level + 1]) then return 'dig' end
    if e.wave > 0 and e.wave <= #e.waves then
        local jobs = job_tiles()
        local left, lost = 0, {}
        for _, c in ipairs(e.waves[e.wave]) do
            local t = tile_info(c.x, c.y, e.z)
            if not cut_done(t) then
                left = left + 1
                if t and not t.designated and not jobs[c.x .. ',' .. c.y .. ',' .. e.z] then table.insert(lost, c) end
            end
        end
        if left > 0 and e.gave_up ~= e.wave then
            if #lost == left and (math.tointeger(e.tries) or 0) < OPEN_REDIG_MAX then return 'ready', 'redo', lost end
            if #lost < left then return 'waiting', 'wave' end
            -- given up on the lost ones: the rails go up, the rest stays floor
        end
    end
    if e.wave < #e.waves then return 'ready', 'wave' end
    if not e.railed then return 'ready', 'rails' end
    if #e.rails > 0 and waiting(e.rails, e.z) > 0 then return 'waiting', 'rails' end
    return 'done'
end

-- (0.105.37 fix) The openings' wait limit: a level waiting OPEN_WAIT_DAYS on
-- the same wave or rails has them designated again (OPEN_REDIG_MAX times);
-- then the wave is given up (the tiles not cut stay floor; the rails go up)
-- or the rails are 'stalled' (reported: the brain frees the slot; the rails
-- stay designated, never taken off). Changed: the record wants saving.
local function open_watch(rec, data, dry_run)
    local changed = false
    local now = now_tick()
    for _, e in ipairs(rec.open or {}) do
        local st, what = open_state(rec, e, data)
        local mark = st == 'waiting' and (what .. ':' .. tostring(e.wave)) or nil
        if mark ~= e.wait_on then
            if not dry_run then e.wait_on, e.wait_since = mark, mark and now or nil end
            changed = true
        elseif mark and now - (tonumber(e.wait_since) or now) > OPEN_WAIT_DAYS * 1200 then
            local n = math.tointeger(e.wait_tries) or 0
            if dry_run then
            elseif n < OPEN_REDIG_MAX then
                local cells, mode = {}, 'dig'
                if what == 'wave' then
                    for _, c in ipairs(e.waves[e.wave]) do
                        if not cut_done(tile_info(c.x, c.y, e.z)) then table.insert(cells, c) end
                    end
                else
                    cells, mode = e.rails, 'build'
                end
                if #cells > 0 then pcall(qf_try, mode, cells, e.z, 0, 0, false) end
                e.wait_tries, e.wait_since = n + 1, now
                changed = true
            elseif what == 'wave' then
                e.gave_up, e.wait_tries, e.wait_on, e.wait_since = e.wave, 0, nil, nil
                changed = true
            else
                e.stalled = true
                e.stall_why = ('the rails of level %d waited %d days'):format(e.level, OPEN_WAIT_DAYS * (OPEN_REDIG_MAX + 1))
                changed = true
            end
        end
    end
    return changed
end

-- The openings of a rock landmark together: 'open' (something to do now),
-- 'opening' (cut or railed, waiting on the dwarves), 'dig' (waiting on the
-- digging), or nil (none left).
local function opening_stage(rec, data)
    if type(rec.open) ~= 'table' then return nil end
    local any_ready, any_wait, any_dig, any_stall = false, false, false, false
    for _, e in ipairs(rec.open) do
        local st = open_state(rec, e, data)
        if st == 'ready' then any_ready = true
        elseif st == 'waiting' then any_wait = true
        elseif st == 'stalled' then any_stall = true
        elseif st == 'dig' then any_dig = true end
    end
    if any_ready then return 'open' end
    if any_stall then return 'stalled' end
    if any_wait then return 'opening' end
    if any_dig then return 'dig' end
    return nil
end

-- One step of the openings: on every level that is ready, the next wave cut
-- (or its lost tiles again), or the rails built. Returns the step's answer
-- fields, or nil and why.
local function open_step(rec, data, dry_run)
    local cut, railed, levels = 0, 0, {}
    for _, e in ipairs(rec.open) do
        local st, act, lost = open_state(rec, e, data)
        if st == 'ready' then
            if act == 'wave' or act == 'redo' then
                local w = act == 'wave' and e.wave + 1 or e.wave
                local cells = act == 'wave' and e.waves[w] or lost
                local good, failed, res = qf_try('dig', cells, e.z, 0, 0, dry_run)
                if not good then
                    return nil, ('the game %s the openings of level %d'):format(failed == 'dry' and 'would not cut' or 'refused', e.level)
                end
                cut = cut + stat(res, 'dig_designated')
                if not dry_run then
                    if act == 'wave' then e.wave, e.tries = w, 0 else e.tries = (math.tointeger(e.tries) or 0) + 1 end
                end
                table.insert(levels, {level = e.level, wave = w, waves = #e.waves})
            else
                if #e.rails > 0 then
                    local good, failed, res = qf_try('build', e.rails, e.z, 0, 0, dry_run)
                    if not good then
                        return nil, ('the game %s the rails of level %d'):format(failed == 'dry' and 'would not place' or 'refused', e.level)
                    end
                    railed = railed + stat(res, 'build_designated')
                end
                if not dry_run then e.railed = true end
                table.insert(levels, {level = e.level, rails = #e.rails})
            end
        elseif st == 'done' and not dry_run then
            e.done = true
        end
    end
    return {cut = cut, railed = railed, levels = levels}
end

-- The status of a rock landmark from its levels: 'built' once every level is done.
local function rock_status(rec, data)
    local left = 0
    for _, pid in ipairs(rec.project_ids or {}) do
        for _, p in ipairs(data.list) do
            if p.id == pid then
                if p.phase == 'cancelled' then return 'dropped' end
                if p.phase ~= 'done' and p.phase ~= 'decorate' then left = left + 1 end
            end
        end
    end
    if left == 0 and opening_stage(rec, data) ~= nil then return 'building' end   -- (E1) openings left
    return left == 0 and 'built' or 'building'
end

-- One step of a landmark: a surface one's next stage (clearing -> walls ->
-- floor -> the next level's walls ... -> furnish -> zone -> done), each
-- waiting for the last one's tiles to be built. A rock landmark is built
-- by its levels' projects; its step only records it built once they are.
function landmark_step(id, dry_run)
    OFFSET = elevation_offset()
    local d = landmarks_data()
    local rec = find_landmark(d, id)
    if not rec then return {ok = false, rejected = true, error = 'no such landmark'} end
    local function out(t)
        t.ok = t.ok ~= false
        t.landmark_id = id
        t.dry_run = dry_run or nil
        return t
    end
    if rec.status ~= 'building' then
        return out({ok = false, rejected = true, stage = rec.stage, done = rec.status == 'built' or nil,
                    error = ('the landmark is %s'):format(tostring(rec.status))})
    end
    if rec.ground ~= 'surface' then
        local data = load_projects()
        -- (0.105.37 fix) the openings' wait limit looked at first
        if type(rec.open) == 'table' and opening_stage(rec, data) == 'opening' and rock_status(rec, data) == 'building'
                and open_watch(rec, data, dry_run) and not dry_run then
            save_landmarks(d)
        end
        -- (E1) the openings: the next wave cut, or the rails built
        if opening_stage(rec, data) == 'open' and rock_status(rec, data) ~= 'dropped' then
            local r, why = open_step(rec, data, dry_run)
            if not r then return out({ok = false, stage = 'open', error = why}) end
            if not dry_run then rec.stage = 'open' save_landmarks(d) end
            return out({stage = 'open', cut = r.cut, railed = r.railed, levels = r.levels})
        end
        local st = rock_status(rec, data)
        if st == 'building' and type(rec.open) == 'table' and opening_stage(rec, data) == 'opening' then
            return out({ok = false, rejected = true, waiting = true, stage = 'opening',
                        error = ('%s: the openings are being cut or railed'):format(rec.name or 'the landmark')})
        end
        if st == 'building' and type(rec.open) == 'table' and opening_stage(rec, data) == 'stalled' then
            local why
            for _, e in ipairs(rec.open) do why = why or e.stall_why end
            return out({ok = false, rejected = true, stage = 'stalled',
                        error = ('%s: %s'):format(rec.name or 'the landmark', why or 'the openings stalled')})
        end
        if st == 'building' then
            return out({ok = false, rejected = true, stage = 'levels',
                        error = 'a rock landmark is built through its levels\' projects'})
        end
        if not dry_run then rec.status, rec.stage, rec.done = st, st == 'built' and 'done' or rec.stage, now_date() save_landmarks(d) end
        return out({stage = 'done', done = st == 'built' or nil, ok = st == 'built',
                    error = st ~= 'built' and 'a level of the landmark was cancelled' or nil})
    end
    local k = math.tointeger(rec.level) or 1
    local lv = rec.surface and rec.surface[k]
    if not lv then return out({ok = false, error = 'the landmark\'s record has no level ' .. k}) end
    local function place(cells, z, what, mode)
        if #cells == 0 then return 0 end
        local good, failed, res = qf_try(mode or 'build', cells, z, 0, 0, dry_run)
        if not good then return nil, ('the game %s %s'):format(failed == 'dry' and 'would not place' or 'refused', what) end
        return stat(res, (mode or 'build') .. '_designated')
    end
    local function wait(stage, n, what)
        return out({ok = false, rejected = true, waiting = true, stage = stage, left = n,
                    error = ('%s: %d %s still to build'):format(rec.name or 'the landmark', n, what)})
    end
    local function advance(stage, extra)
        if not dry_run then
            rec.stage = stage
            for key, v in pairs(extra or {}) do rec[key] = v end
            save_landmarks(d)
        end
    end
    -- the furniture, stockpiles and zone, once the shape stands
    local function start_furnish()
        local placed = 0
        for _, l in ipairs(rec.surface) do
            local nb, why = place(l.furnish, l.z, 'the landmark\'s furniture')
            if not nb then return out({ok = false, error = why}) end
            local np, why2 = place(l.place, l.z, 'the landmark\'s stockpiles', 'place')
            if not np then return out({ok = false, error = why2}) end
            placed = placed + nb + np
        end
        advance('furnish')
        return out({stage = 'furnish', placed = placed})
    end
    -- (E2) a landmark planned in steps (ai-blueprints.build_stages): each
    -- step placed once the last one's tiles stand; scaffolding taken down
    -- only while no one stands where it would strand them
    if type(rec.steps) == 'table' and rec.stage ~= 'furnish' then
        local nsteps = #rec.steps
        local function next_step(i)
            local st = rec.steps[i]
            if not st then return start_furnish() end
            local n = 0
            if st.kind == 'remove' then
                local why, w8 = removal_blocked(st, rec.name or 'the landmark')
                if why then
                    return out({ok = false, rejected = true, waiting = w8 or nil, stage = 'remove', step = i, steps = nsteps,
                                error = why})
                end
                for _, c in ipairs(st.cells) do
                    if remove_construction(c.x, c.y, st.z, dry_run) then n = n + 1 end
                end
            else
                local placed, why = place(st.cells, st.z, st.kind == 'scaffold' and 'the scaffold stair'
                                                        or 'the landmark\'s next tiles')
                if not placed then return out({ok = false, error = why}) end
                n = placed
            end
            advance(st.kind, {step = i, level = st.level})
            return out({stage = st.kind, step = i, steps = nsteps, level = st.level, placed = n,
                        scaffold = st.kind ~= 'build' or nil})
        end
        if rec.stage == 'clearing' then
            local n = trees_standing(rec)
            if n > 0 then
                if not dry_run then for _, t in ipairs(rec.trees) do fell_tree(t.x, t.y, t.z) end end
                return out({ok = false, rejected = true, waiting = true, stage = 'clearing', trees = n,
                            error = ('the dwarves are still felling %d tree(s)'):format(n)})
            end
            return next_step(1)
        end
        local i = math.tointeger(rec.step) or 0
        local st = rec.steps[i]
        if not st then return next_step(i + 1) end
        local n = step_left(st)
        if n > 0 then
            if st.kind == 'remove' then
                -- (0.105.37 fix) asked again only while no one stands on or above it
                local why, w8 = removal_blocked(st, rec.name or 'the landmark')
                if why then
                    return out({ok = false, rejected = true, waiting = w8 or nil, stage = 'remove', step = i, steps = nsteps,
                                left = n, error = why})
                end
                if not dry_run then
                    for _, c in ipairs(st.cells) do remove_construction(c.x, c.y, st.z, false) end
                end
                return wait('remove', n, 'scaffold tile(s) to take down')
            end
            return wait(st.kind, n, st.kind == 'scaffold' and 'scaffold stair tile(s)' or 'tile(s)')
        end
        return next_step(i + 1)
    end
    if rec.stage == 'clearing' then
        local n = trees_standing(rec)
        if n > 0 then
            if not dry_run then for _, t in ipairs(rec.trees) do fell_tree(t.x, t.y, t.z) end end
            return out({ok = false, rejected = true, waiting = true, stage = 'clearing', trees = n,
                        error = ('the dwarves are still felling %d tree(s)'):format(n)})
        end
        local placed, why = place(lv.walls, lv.z, 'the landmark\'s walls')
        if not placed then return out({ok = false, error = why}) end
        advance('walls')
        return out({stage = 'walls', level = k, placed = placed})
    end
    if rec.stage == 'walls' then
        local n = waiting(lv.walls, lv.z)
        if n > 0 then return wait('walls', n, 'wall tile(s) or door(s)') end
        local placed, why = place(lv.floor, lv.z, 'the landmark\'s floor and stairs')
        if not placed then return out({ok = false, error = why}) end
        advance('floor')
        return out({stage = 'floor', level = k, placed = placed})
    end
    if rec.stage == 'floor' then
        local n = waiting(lv.floor, lv.z)
        if n > 0 then return wait('floor', n, 'floor, ramp or stair tile(s)') end
        if k < #rec.surface then
            local nxt = rec.surface[k + 1]
            local placed, why = place(nxt.walls, nxt.z, 'the next level\'s walls')
            if not placed then return out({ok = false, error = why}) end
            advance('walls', {level = k + 1})
            return out({stage = 'next level', level = k + 1, placed = placed})
        end
        local placed = 0
        for _, l in ipairs(rec.surface) do
            local nb, why = place(l.furnish, l.z, 'the landmark\'s furniture')
            if not nb then return out({ok = false, error = why}) end
            local np, why2 = place(l.place, l.z, 'the landmark\'s stockpiles', 'place')
            if not np then return out({ok = false, error = why2}) end
            placed = placed + nb + np
        end
        advance('furnish')
        return out({stage = 'furnish', placed = placed})
    end
    if rec.stage == 'furnish' then
        local n = 0
        for _, l in ipairs(rec.surface) do n = n + waiting(l.furnish, l.z) end
        if n > 0 then return wait('furnish', n, 'piece(s) of furniture') end
        local zoned, dedicated = 0, nil
        for _, l in ipairs(rec.surface) do
            if #l.zone > 0 then
                local nz, why = place(l.zone, l.z, 'the landmark\'s zone', 'zone')
                if not nz then return out({ok = false, error = why}) end
                zoned = zoned + nz
                if not dry_run and rec.zone == 'temple' and rec.deity_hf and nz > 0 then
                    local okd, ded = pcall(dedicate_temple, {anchor = {x = 0, y = 0}, z = l.z, cells = {zone = l.zone}},
                                           {deity_hf = rec.deity_hf})
                    dedicated = okd and ded or false
                end
            end
        end
        if not dry_run then rec.status, rec.stage, rec.done = 'built', 'done', now_date() save_landmarks(d) end
        return out({stage = 'zone', zoned = zoned, dedicated = dedicated, done = true})
    end
    return out({ok = false, rejected = true, stage = rec.stage, error = 'nothing left to do'})
end

---------------------------------------------------------------------------
-- The report
---------------------------------------------------------------------------

-- {list = {{id, name, purpose, status, stage, levels, project_ids, started}}}
-- (the status of a rock landmark read from its levels: nothing is saved)
function landmarks_report()
    local d = landmarks_data()
    local data
    local out = {}
    for _, l in ipairs(d.list) do
        local status, stage = l.status, l.stage
        if l.ground ~= 'surface' and status == 'building' then
            data = data or load_projects()
            local st = rock_status(l, data)
            if st ~= 'building' then status, stage = st, 'done' end
            -- (E1) the openings: 'open' when a step can be taken now
            if st == 'building' and type(l.open) == 'table' then
                local ok, os_ = pcall(opening_stage, l, data)
                if ok and os_ and os_ ~= 'dig' then stage = os_ end
            end
        end
        local why
        if stage == 'stalled' then
            for _, o in ipairs(l.open or {}) do why = why or o.stall_why end
        end
        local e = {id = l.landmark_id, name = l.name, purpose = l.purpose, status = status, stage = stage,
                   levels = l.levels, project_ids = l.project_ids, started = l.started, by = l.by,
                   ground = l.ground, why = why}
        -- (E2) a landmark built in steps: where it is, and its scaffolding
        if type(l.steps) == 'table' then
            e.step, e.steps = math.tointeger(l.step) or 0, #l.steps
            if status == 'building' then
                local ok, sc = pcall(scaffold_state, l)
                if ok then e.scaffold = sc end
            end
        end
        table.insert(out, e)
    end
    return {list = out}
end
