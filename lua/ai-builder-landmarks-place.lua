-- ai-builder-landmarks-place: a drawing on a site: the map checks it must pass
-- (validate_landmark: every tile on the real map, the walk test, the openings'
-- drops) and its start (start_landmark, build_landmark: rock levels as projects,
-- a surface one stage by stage).
--
-- (r9) A part of ai-builder, not a script of its own: cut from ai-builder-landmarks.lua
-- (which had grown to 84 KB) at a section boundary, the code as it stood. ai-builder.lua
-- loads it into its own environment right after the part before it (PARTS), so every
-- name here is reqscript('ai-builder').name and the hub's helpers are in reach.
-- The top-level locals the ai-builder-landmarks files share come through
-- LANDMARKS_PART_LOCALS (the same functions).

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-landmarks-place'] = '0.105.110'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, has, add = info, has, add
local grid_xy, reason = LANDMARKS_PART_LOCALS.grid_xy, LANDMARKS_PART_LOCALS.reason
local reserved_boxes, extension_cells = LANDMARKS_PART_LOCALS.reserved_boxes, LANDMARKS_PART_LOCALS.extension_cells
local save_landmarks = LANDMARKS_PART_LOCALS.save_landmarks

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

-- (r9) The file goes on in ai-builder-landmarks-stages.lua, loaded right after this
-- one; the top-level local it uses besides, handed on:
LANDMARKS_PART_LOCALS.now_date = now_date
