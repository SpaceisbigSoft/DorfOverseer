-- (item10) Wood that lasts: cavern trees logged when safe, and a grove kept.
--
-- The coverage audit's "should" list: "when a cavern is known and safe
-- (sealed or watched), woodcutters fell cavern trees (tower-caps etc.) when
-- surface wood is short or the elves' tree quota is near ... never into a
-- cavern with hostiles in sight"; and "tree farming: saplings/trees kept (a
-- grove zone left alone by autochop) so wood lasts years, where DF allows it".
--
-- What DF allows (DF wiki, Tree and Elf): trees can't be planted; saplings
-- sprout by themselves on open soil and grow to trees over years if nothing
-- lies or is built on them and they aren't trampled. Underground trees
-- (tower-caps, fungiwood...) grow in the caverns, and on bare soil inside the
-- fort once a cavern is open. The elves' quota counts every tree felled
-- (plotinfo.trees_removed): the wiki says cutting fungus "trees" counts too,
-- so cavern logging is no way round the quota; the brain stops it there.
--
--   report()      the `forestry` section: the revealed trees and saplings by
--                 where they stand (surface: outside; cavern: on a cavern
--                 tile; inside: the fort's own underground soil), the cavern
--                 and inside trees the dwarves can reach, those marked for
--                 felling (and by the AI), the cavern layers (z bands) with
--                 their trees and the dangers on cavern tiles near them, and
--                 the grove. The tree census is rebuilt once a game day (the
--                 plant list walked once); the dangers are read every report.
--   cavern_logging(limit, dry_run, stop, inside_only, unsafe_only)
--                 up to `limit` reachable cavern (and inside) trees marked for
--                 felling, the nearest to the fort first; none in a layer with
--                 a danger on a cavern tile near it, none within DANGER_TILES
--                 of one. Remembered (site data FOREST_KEY). stop: every tree
--                 the AI marked and still standing unmarked (the caverns
--                 unwatched, the switch off). unsafe_only (with stop): only the
--                 AI's marks a new call would not make now (in a layer with a
--                 danger near it, or within DANGER_TILES of a danger) lifted;
--                 the safe layers' marks stand (the report's ai_marked_unsafe).
--                 inside_only: the fort's own underground trees only.
--   keep_grove(dry_run, guard)
--                 the grove: a patch of surface soil near the fort with the
--                 most saplings and young trees (GROVE_W x GROVE_H), chosen
--                 once and remembered; its tiles of normal traffic set to
--                 restricted (fewer feet on the saplings). Each call (guard:
--                 only this) unmarks the felling designations on the trees in
--                 it, autochop's or anyone's: the grove is the AI's own zone,
--                 and sets its tiles back at normal traffic to restricted again.
--                 The guard reads only the grove's tiles, fresh (no census),
--                 and the report counts the grove from its tiles every report,
--                 so the brain can guard it within hours of autochop's marks.
--                 (DFHack's autochop has no burrow or area to leave alone: its
--                 burrow settings only limit felling TO burrows, which would
--                 take over the player's autochop; so the AI unmarks instead.)
--@ module = true

local U = reqscript('ai-util')

FOREST_KEY = 'ai-overseer/forestry'     -- {marked = {["x,y,z"] = tick}, grove = {x1, y1, x2, y2, z, made}}
CENSUS_TICKS = 1200                     -- the tree census rebuilt once a game day
LAYER_GAP = 3                           -- cavern trees more than this many levels apart: another layer
LAYER_DANGER_DZ = 3                     -- a danger this many levels round a layer makes it unsafe
DANGER_TILES = 25                       -- no tree marked this near a danger
MARK_MAX = 30                           -- a call's cap
GROVE_W, GROVE_H = 9, 9
GROVE_RADIUS = 45                       -- the grove within this many tiles of a way in
GROVE_MIN_D = 6                         -- ...and no nearer than this (the way in stays clear)
GROVE_TRIES = 25

CENSUS = CENSUS

local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end

local function key(x, y, z) return ('%d,%d,%d'):format(x, y, z) end

local function load_state()
    local d = U.site_get(FOREST_KEY, {})
    if type(d) ~= 'table' then d = {} end
    if type(d.marked) ~= 'table' then d.marked = {} end
    return d
end

local function save_state(d) return U.site_put(FOREST_KEY, d) end

local function now()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function site_id()
    local ok, id = pcall(function() return df.global.plotinfo.site_id end)
    return ok and id or nil
end

-- What stands on a tile: 'tree' (a trunk at its base), 'sapling', or nil;
-- where: 'surface', 'cavern' or 'inside'; and whether it is marked for felling.
function tile_class(x, y, z)
    local ok, kind, where, marked = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        if not tt then return nil end
        local a = df.tiletype.attrs[tt]
        local shape, mat = df.tiletype_shape[a.shape], df.tiletype_material[a.material]
        local k
        if mat == 'TREE' and (shape == 'WALL' or shape == 'TRUNK_BRANCH') then k = 'tree'
        elseif shape == 'SAPLING' then k = 'sapling' end
        if not k then return nil end
        local des = dfhack.maps.getTileFlags(x, y, z)
        if not des or des.hidden then return nil end
        local w = (des.feature_global or des.feature_local) and 'cavern' or (des.outside and 'surface' or 'inside')
        return k, w, des.dig ~= df.tile_dig_designation.No
    end)
    if not ok then return nil end
    return kind, where, marked
end

local function anchor()
    local from
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then from = xyz2pos(x, y, z) break end
        end
    end)
    return from
end

-- Can a dwarf at `from` stand beside the trunk?
local function reachable(from, x, y, z)
    if not from then return false end
    local ok, yes = pcall(function()
        for dy = -1, 1 do for dx = -1, 1 do
            if (dx ~= 0 or dy ~= 0) and dfhack.maps.canWalkBetween(from, xyz2pos(x + dx, y + dy, z)) then return true end
        end end
        return false
    end)
    return ok and yes
end

-- The plant list walked once: {trees = {{x, y, z, where, marked, reach}...},
-- saplings = {{x, y, z, where}...}, tick}.
local function build_census()
    local c = {trees = {}, saplings = {}, tick = now(), site = site_id()}
    local from = anchor()
    local seen = {}
    pcall(function()
        for _, p in ipairs(df.global.world.plants.all) do
            local x, y, z = p.pos.x, p.pos.y, p.pos.z
            local k = key(x, y, z)
            if not seen[k] then
                seen[k] = true
                local kind, where, marked = tile_class(x, y, z)
                if kind == 'tree' then
                    table.insert(c.trees, {x = x, y = y, z = z, where = where, marked = marked or nil,
                                           reach = where ~= 'surface' and reachable(from, x, y, z) or nil})
                elseif kind == 'sapling' then
                    table.insert(c.saplings, {x = x, y = y, z = z, where = where})
                end
            end
        end
    end)
    return c
end

function census(fresh)
    local t = now()
    if fresh or not CENSUS or t - (CENSUS.tick or -1e9) >= CENSUS_TICKS or t < (CENSUS.tick or 0)
            or CENSUS.site ~= site_id() then
        CENSUS = build_census()
    end
    return CENSUS
end

-- The dangers on cavern tiles: {{x, y, z}...}; and every danger.
local function dangers()
    local all = {}
    pcall(function() all = U.danger_spots() or {} end)
    local cave = {}
    for _, d in ipairs(all) do
        local ok, yes = pcall(function()
            local des = dfhack.maps.getTileFlags(d.x, d.y, d.z)
            return des and (des.feature_global or des.feature_local)
        end)
        if ok and yes then table.insert(cave, d) end
    end
    return cave, all
end

-- Pure: the cavern trees' layers, by z bands: {{z1, z2, trees, reachable, marked}...}.
function layers_of(trees)
    local zs, by = {}, {}
    for _, t in ipairs(trees) do
        if t.where == 'cavern' then
            if not by[t.z] then by[t.z] = {n = 0, reach = 0, marked = 0}; table.insert(zs, t.z) end
            local b = by[t.z]
            b.n = b.n + 1
            if t.reach then b.reach = b.reach + 1 end
            if t.marked then b.marked = b.marked + 1 end
        end
    end
    table.sort(zs)
    local out, cur = {}, nil
    for _, z in ipairs(zs) do
        if cur and z - cur.z2 <= LAYER_GAP then
            cur.z2 = z
        else
            cur = {z1 = z, z2 = z, trees = 0, reachable = 0, marked = 0}
            table.insert(out, cur)
        end
        cur.trees = cur.trees + by[z].n
        cur.reachable = cur.reachable + by[z].reach
        cur.marked = cur.marked + by[z].marked
    end
    return out
end

-- Pure: is a layer near a danger?
function layer_unsafe(layer, cave_dangers)
    for _, d in ipairs(cave_dangers) do
        if d.z >= layer.z1 - LAYER_DANGER_DZ and d.z <= layer.z2 + LAYER_DANGER_DZ then return true end
    end
    return false
end

-- The z levels of the cavern layers near a cavern danger: {[z] = true}.
function unsafe_zs(trees, cave_dangers)
    local unsafe = {}
    for _, l in ipairs(layers_of(trees)) do
        if layer_unsafe(l, cave_dangers) then
            for z = l.z1, l.z2 do unsafe[z] = true end
        end
    end
    return unsafe
end

-- Would cavern_logging refuse to mark this tree now? (a cavern tree in a layer
-- near a danger, or any tree within DANGER_TILES of one)
function mark_unsafe(t, unsafe, all_d)
    if t.where == 'cavern' and unsafe[t.z] then return true end
    return U.near_danger(all_d, t.x, t.y, t.z, DANGER_TILES) == true
end

local function in_rect(g, x, y, z)
    return type(g) == 'table' and g.z == z and x >= g.x1 and x <= g.x2 and y >= g.y1 and y <= g.y2
end

-- The grove's trees and saplings read from its own tiles, now (GROVE_W x
-- GROVE_H tiles: cheap enough for every report and every guard): {{x, y, z,
-- kind, marked}...}, a tree once (at its plant's own tile when DF says which).
local function grove_plants(g)
    local out = {}
    for y = g.y1, g.y2 do
        for x = g.x1, g.x2 do
            local kind, _, marked = tile_class(x, y, g.z)
            if kind then
                local base = true
                pcall(function()
                    local p = dfhack.maps.getPlantAtTile(x, y, g.z)
                    if p and p.pos and (p.pos.x ~= x or p.pos.y ~= y or p.pos.z ~= g.z) then base = false end
                end)
                if base then table.insert(out, {x = x, y = y, z = g.z, kind = kind, marked = marked or nil}) end
            end
        end
    end
    return out
end

local function grove_counts(g)
    local out = {x1 = g.x1, y1 = g.y1, x2 = g.x2, y2 = g.y2, z = g.z, made = g.made, trees = 0, saplings = 0, marked = 0}
    for _, p in ipairs(grove_plants(g)) do
        if p.kind == 'tree' then
            out.trees = out.trees + 1
            if p.marked then out.marked = out.marked + 1 end
        else
            out.saplings = out.saplings + 1
        end
    end
    return out
end

function report()
    local c = census()
    local d = load_state()
    local cave_d, all_d = dangers()
    local out = {surface = {trees = 0, saplings = 0, marked = 0}, cavern = {trees = 0, reachable = 0, marked = 0},
                 inside = {trees = 0, reachable = 0, marked = 0}, ai_marked = 0, ai_marked_unsafe = 0,
                 cavern_dangers = #cave_d}
    local standing = {}
    for _, t in ipairs(c.trees) do
        local b = out[t.where]
        b.trees = b.trees + 1
        if t.marked then b.marked = b.marked + 1 end
        if t.reach then b.reachable = (b.reachable or 0) + 1 end
        standing[key(t.x, t.y, t.z)] = t
    end
    for _, s in ipairs(c.saplings) do
        local b = out[s.where]
        b.saplings = (b.saplings or 0) + 1
    end
    -- the AI's marks: still standing (and in which layer), or felled since
    local felled, changed = 0, false
    local unsafe = unsafe_zs(c.trees, cave_d)
    for k in pairs(d.marked) do
        local t = standing[k]
        if t then
            out.ai_marked = out.ai_marked + 1
            if mark_unsafe(t, unsafe, all_d) then out.ai_marked_unsafe = out.ai_marked_unsafe + 1 end
        else
            felled = felled + 1
            d.marked[k] = nil
            changed = true
        end
    end
    if felled > 0 then
        d.felled = (tonumber(d.felled) or 0) + felled
    end
    out.ai_felled = tonumber(d.felled) or nil
    out.layers = layers_of(c.trees)
    for _, l in ipairs(out.layers) do
        if layer_unsafe(l, cave_d) then l.danger = true end
    end
    if #out.layers == 0 then out.layers = nil end
    if type(d.grove) == 'table' and d.grove.x1 then out.grove = grove_counts(d.grove) end
    if changed then save_state(d) end
    out.census_age = now() - (c.tick or 0)
    return out
end

function cavern_logging(limit, dry_run, stop, inside_only, unsafe_only)
    local d = load_state()
    if stop then
        local n, kept = 0, 0
        local lift
        if unsafe_only then
            -- only the marks a new call would not make now; the safe layers' stand
            local c = census()
            local cave_d, all_d = dangers()
            local unsafe = unsafe_zs(c.trees, cave_d)
            local standing = {}
            for _, t in ipairs(c.trees) do standing[key(t.x, t.y, t.z)] = t end
            lift = function(k)
                local t = standing[k]
                return not t or mark_unsafe(t, unsafe, all_d)
            end
        end
        for k in pairs(d.marked) do
            local x, y, z = k:match('^(-?%d+),(-?%d+),(-?%d+)$')
            x, y, z = tonumber(x), tonumber(y), tonumber(z)
            local keep = lift ~= nil and x ~= nil and not lift(k)
            if keep then kept = kept + 1 end
            if x and not keep and not dry_run then
                pcall(function()
                    local plant = dfhack.maps.getPlantAtTile(x, y, z)
                    if plant then dfhack.designations.unmarkPlant(plant) end
                end)
                pcall(function()
                    local des = dfhack.maps.getTileFlags(x, y, z)
                    if des then des.dig = df.tile_dig_designation.No end
                end)
            end
            if x and not keep then n = n + 1 end
            if not dry_run and not keep then d.marked[k] = nil end
        end
        if not dry_run then save_state(d) end
        return {ok = true, unmarked = n, kept = unsafe_only and kept or nil, dry_run = dry_run or nil}
    end
    limit = math.floor(tonumber(limit) or 0)
    if limit < 1 then return {ok = false, rejected = true, error = 'cavern_logging needs limit 1+'} end
    limit = math.min(limit, MARK_MAX)
    local c = census(true)
    local cave_d, all_d = dangers()
    local unsafe = unsafe_zs(c.trees, cave_d)
    local from = anchor()
    local picks = {}
    for _, t in ipairs(c.trees) do
        if t.where ~= 'surface' and t.reach and not t.marked and not (t.where == 'cavern' and (unsafe[t.z] or inside_only))
                and not U.near_danger(all_d, t.x, t.y, t.z, DANGER_TILES) then
            local dist = from and (math.abs(t.x - from.x) + math.abs(t.y - from.y) + 3 * math.abs(t.z - from.z)) or 0
            table.insert(picks, {t = t, d = dist})
        end
    end
    if #picks == 0 then
        return {ok = false, rejected = true,
                error = 'no cavern or underground tree the dwarves can reach safely (or every one is marked)'}
    end
    table.sort(picks, function(a, b) return a.d < b.d end)
    local n, t0 = 0, now()
    for i = 1, math.min(limit, #picks) do
        local t = picks[i].t
        if dry_run then
            n = n + 1
        else
            local marked = false
            pcall(function()
                local plant = dfhack.maps.getPlantAtTile(t.x, t.y, t.z)
                if plant then marked = dfhack.designations.markPlant(plant) ~= false end
            end)
            if marked then
                n = n + 1
                t.marked = true
                d.marked[key(t.x, t.y, t.z)] = t0
            end
        end
    end
    if not dry_run then save_state(d) end
    return {ok = n > 0, marked = n, candidates = #picks, dry_run = dry_run or nil,
            error = n == 0 and 'no tree could be marked' or nil}
end

-- The AI's areas and the surface ways in (swapped by the tests).
function grove_context()
    local ctx = {reserved = {}, anchors = {}}
    pcall(function()
        local B = reqscript('ai-builder')
        for _, p in ipairs(B.registry_report() or {}) do
            if type(p) == 'table' and type(p.bounds) == 'table' and p.bounds.x1 then table.insert(ctx.reserved, p.bounds) end
        end
        for _, c in pairs(B.clearing_spots() or {}) do
            if type(c) == 'table' and c.x and c.w then
                table.insert(ctx.reserved, {x1 = c.x, y1 = c.y, x2 = c.x + c.w - 1, y2 = c.y + c.h - 1, z = c.z})
            end
        end
        ctx.anchors = B.surface_anchors() or {}
    end)
    return ctx
end

local function overlaps(r, g, pad)
    return math.abs((r.z or g.z) - g.z) <= 1 and r.x1 - pad <= g.x2 and g.x1 <= r.x2 + pad
        and r.y1 - pad <= g.y2 and g.y1 <= r.y2 + pad
end

-- Every tile of the rectangle open soil or a sapling or tree, no building, no water.
local function rect_ok(g)
    for y = g.y1, g.y2 do
        for x = g.x1, g.x2 do
            local ok, good = pcall(function()
                local tt = dfhack.maps.getTileType(x, y, g.z)
                if not tt then return false end
                local des, occ = dfhack.maps.getTileFlags(x, y, g.z)
                if not des or des.hidden or not des.outside or des.flow_size > 0 then return false end
                if occ and occ.building ~= df.tile_building_occ.None then return false end
                local a = df.tiletype.attrs[tt]
                local shape = df.tiletype_shape[a.shape]
                return shape == 'FLOOR' or shape == 'SAPLING' or shape == 'SHRUB' or shape == 'TWIG'
                    or df.tiletype_material[a.material] == 'TREE'
            end)
            if not (ok and good) then return false end
        end
    end
    return true
end

-- Pure-ish: the best grove rectangle from the census and the context, or nil and why.
function pick_grove(c, ctx, w, h)
    w, h = w or GROVE_W, h or GROVE_H
    if #(ctx.anchors or {}) == 0 then return nil, 'no surface way in to start from' end
    local pts = {}
    local function add(p, v)
        local k = key(p.x, p.y, p.z)
        pts[k] = (pts[k] or 0) + v
    end
    local cands = {}
    for _, s in ipairs(c.saplings) do
        if s.where == 'surface' then add(s, 2); table.insert(cands, s) end
    end
    for _, t in ipairs(c.trees) do if t.where == 'surface' then add(t, 1) end end
    local scored = {}
    for _, s in ipairs(cands) do
        local near = false
        for _, a in ipairs(ctx.anchors) do
            local dd = math.max(math.abs(a.x - s.x), math.abs(a.y - s.y))
            if math.abs(a.z - s.z) <= 2 and dd <= GROVE_RADIUS then near = true end
        end
        if near then
            local g = {x1 = s.x - w // 2, y1 = s.y - h // 2, z = s.z}
            g.x2, g.y2 = g.x1 + w - 1, g.y1 + h - 1
            local score = 0
            for y = g.y1, g.y2 do for x = g.x1, g.x2 do score = score + (pts[key(x, y, g.z)] or 0) end end
            table.insert(scored, {g = g, score = score})
        end
    end
    if #scored == 0 then return nil, 'no sapling on the surface near the fort' end
    table.sort(scored, function(a, b) return a.score > b.score end)
    for i = 1, math.min(#scored, GROVE_TRIES) do
        local g = scored[i].g
        local clear = true
        for _, r in ipairs(ctx.reserved or {}) do
            if overlaps(r, g, 2) then clear = false break end
        end
        for _, a in ipairs(ctx.anchors) do
            if math.abs(a.z - g.z) <= 1 and a.x > g.x1 - GROVE_MIN_D and a.x < g.x2 + GROVE_MIN_D
                    and a.y > g.y1 - GROVE_MIN_D and a.y < g.y2 + GROVE_MIN_D then
                clear = false
            end
        end
        if clear and rect_ok(g) then return g, nil, scored[i].score end
    end
    return nil, 'no clear patch of soil round the saplings near the fort'
end

-- The grove's marked trees unmarked, read from its tiles now.
local function unmark_in(g, dry_run)
    local n = 0
    for _, t in ipairs(grove_plants(g)) do
        if t.kind == 'tree' and t.marked then
            n = n + 1
            if not dry_run then
                pcall(function()
                    local plant = dfhack.maps.getPlantAtTile(t.x, t.y, t.z)
                    if plant then dfhack.designations.unmarkPlant(plant) end
                end)
                pcall(function()
                    local des = dfhack.maps.getTileFlags(t.x, t.y, t.z)
                    if des then des.dig = df.tile_dig_designation.No end
                end)
                t.marked = nil
            end
        end
    end
    return n
end

-- The grove's tiles at normal traffic set to restricted (only those: a tile
-- set high or low is someone's choice and kept). How many.
local function restrict(g, dry_run)
    local restricted = 0
    for y = g.y1, g.y2 do
        for x = g.x1, g.x2 do
            pcall(function()
                local des = dfhack.maps.getTileFlags(x, y, g.z)
                if des and des.traffic == df.tile_traffic.Normal then
                    if not dry_run then des.traffic = df.tile_traffic.Restricted end
                    restricted = restricted + 1
                end
            end)
        end
    end
    return restricted
end

function keep_grove(dry_run, guard)
    local d = load_state()
    local g = type(d.grove) == 'table' and d.grove.x1 and d.grove or nil
    if not g then
        if guard then return {ok = false, rejected = true, error = 'the AI keeps no grove yet'} end
        local why, score
        g, why, score = pick_grove(census(true), grove_context())
        if not g then return {ok = false, error = why} end
        local restricted = restrict(g, dry_run)
        if dry_run then
            return {ok = true, dry_run = true, grove = {x1 = g.x1, y1 = g.y1, x2 = g.x2, y2 = g.y2, z = g.z},
                    score = score, restricted = restricted}
        end
        g.made = now()
        d.grove = g
        save_state(d)
        local un = unmark_in(g, false)
        return {ok = true, made = true, grove = {x1 = g.x1, y1 = g.y1, x2 = g.x2, y2 = g.y2, z = g.z},
                restricted = restricted, unmarked = un}
    end
    local un = unmark_in(g, dry_run)
    local restricted = restrict(g, dry_run)
    return {ok = true, unmarked = un, restricted = restricted, dry_run = dry_run or nil}
end
