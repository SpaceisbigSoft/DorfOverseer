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

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-landmarks'] = '0.105.82'   -- (0.105.26) bumped with BRIDGE_VERSION

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
-- (r9, audit A3 16) one with no tile built and no stage gone on for
-- LANDMARK_SLOT_DAYS (its pieces' items never come) holds its slot no
-- longer: it stays open and goes on when they come (progress_tick: the last
-- change landmark_step saw; an older record without it counts as before)
LANDMARK_SLOT_DAYS = 60
function landmarks_open_surface()
    local n, now = 0, now_tick()
    for _, l in ipairs(landmarks_data().list) do
        if l.ground == 'surface' and l.status == 'building' then
            local t = tonumber(l.progress_tick)
            if not (t and now - t >= LANDMARK_SLOT_DAYS * 1200) then n = n + 1 end
        end
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

-- (r9) The file goes on in ai-builder-landmarks-place.lua (the map checks a drawing
-- must pass, and its start on a site) and ai-builder-landmarks-stages.lua (the surface
-- stages, the openings, one step a call, the report), loaded right after this one.
-- The top-level locals they use, handed on (functions, never assigned again):
LANDMARKS_PART_LOCALS = {save_landmarks = save_landmarks, find_landmark = find_landmark, grid_xy = grid_xy,
                         reason = reason, reserved_boxes = reserved_boxes, extension_cells = extension_cells}
