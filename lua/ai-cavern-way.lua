-- (item3, 25 Nov 22:38, the player's yes) The guarded cavern way: ONE way of
-- the AI's from the fort down onto the first cavern's floor, so the silk webs,
-- the cavern hunts, a lure pocket and the cavern trees can be reached.
--
-- Why: no fort reached real cavern floor (only the wells' hatches over the
-- caverns): 3,300-13,200 webs a fort out of reach, lures with no pocket spot
-- (planner_lure: "no walking way in"), cavern hunts no_path or seal.
--
-- The way (plan_way, pure: the tests call it):
--   top     a free natural floor tile on one of the fort's own levels (the
--           deepest the fort's character allows: a cautious fort never
--           under its homes), dug a down stair; the GATE is a hatch over it
--           on a lever beside it ('AI cavern way gate' / 'lever');
--   column  an up/down stair straight down through solid rock (each level's
--           3x3 natural rock, no water, magma, aquifer, warm stone or
--           cavern), its bottom an up stair on a level of the cavern's layer;
--   tunnel  a straight 1-wide tunnel of TUNNEL_MIN..TUNNEL_MAX tiles from
--           the stair's bottom through solid rock (rock all round it, over
--           and under it: one way in, a lure pocket fits in it), its last
--           tile beside real cavern floor: that tile takes the DOOR (a plain
--           door, never on a lever: the seal locks it, a lure opens it).
-- Built a step at a time (build_step, the brain's `cavern_way` step=build):
-- the column and the tunnel but its last tile dug; the lever; the hatch;
-- the link (2 mechanisms); then, the hatch linked, no danger near the far
-- side and a door in store, the last tile dug (the breach) and the door
-- built on it; the hatch shut. The way stays SHUT: set_gate opens it for a
-- job the brain names (silk, hunt, lure, logging, stranded) and shuts it.
-- The watcher (every WATCH_TICKS while the gate is open) shuts it at once
-- for a danger within CLOSE_TILES of the door, or within WATCH_NEAR with
-- nobody beyond it ("gates close late": a dwarf out there gets time back).
-- The door goes on ai-threats' openings record (gather_openings reads
-- door_opening()): the seal locks it against a great beast, a lure can
-- build its pocket in the tunnel. The gates' scan leaves the hatch to this
-- module (own_keys(), read with the wells' shaft hatches).
--   plan_way(read, forbid, starts, layer, opts)   pure
--   build_step(a, dry_run, layers)                the bridge action (step=build)
--   set_gate(open, why, dry_run, release_only)    the bridge action (step=open/shut)
--   report(layers)                                the `cavern_way` section
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/cavern-way'
TUNNEL_MIN = 8            -- tiles of tunnel (the door's tile counted): a lure pocket and its gate fit
TUNNEL_MAX = 24
COLUMN_MAX = 45           -- levels the stair runs down at most
STARTS_MAX = 48           -- floor tiles tried as the stair's top, a search
LEVELS_TRIED = 3          -- the fort's deepest levels tried
SEARCH_SECONDS = 1.5
REFUSED_RETRY = 28 * 1200 -- a search that found nothing: tried again after (ticks)
REPORT_RADIUS = 40        -- dangers reported within this of the door
CLOSE_TILES = 12          -- a danger this near the door: shut, whoever is out
WATCH_NEAR = 20           -- ...this near with nobody beyond: shut
WATCH_TICKS = 100
BREACH_CLEAR = 25         -- no danger this near the far side before the breach
WEB_CHECKS = 20000
WEBS_ENOUGH = 5000
LEVER_NAME = 'AI cavern way lever'
GATE_NAME = 'AI cavern way gate'
DOOR_NAME = 'AI cavern way door'
local DAY = 1200
local NB = {{-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1}}
local DIRS = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
local NATURAL = {STONE = true, MINERAL = true, SOIL = true, LAVA_STONE = true}
local STAIRS = {STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true}
local CAVE_FLOOR = {FLOOR = true, PEBBLES = true, SHRUB = true, SAPLING = true, BOULDER = true, TWIG = true}
-- the levels a cautious fort never puts the way under
local HOME_KINDS = {bedrooms = true, suites = true, hospital = true, dining = true, tavern = true, temple = true,
                    meeting = true, nobles = true, noble_rooms = true}

CW_WATCH = CW_WATCH or {on = false}
WEB_MEMO = WEB_MEMO or nil

if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-cavern-way'] = function(sc)
        if sc == SC_MAP_UNLOADED then CW_WATCH = {on = false}; WEB_MEMO = nil end
    end
end

local function B() return reqscript('ai-builder') end
local function okey(x, y, z) return ('%d,%d,%d'):format(x, y, z) end

---------------------------------------------------------------------------
-- The plan (pure: reads tiles through read only)
---------------------------------------------------------------------------

-- why a tile refuses the way, or nil
local function hazard(t)
    if not t then return 'off the map' end
    if t.liquid then return t.magma and 'magma' or 'water' end
    if t.magma then return 'magma' end
    if t.aquifer then return 'an aquifer' end
    if t.warm then return 'warm stone' end
    if t.outside then return 'open to the sky' end
    return nil
end

-- a natural wall, untouched (a cavern's own wall may carry the cavern's flag)
local function wall(t)
    return t ~= nil and t.shape == 'WALL' and NATURAL[t.material] == true and not t.designated and not t.building
        and hazard(t) == nil
end

-- rock the way itself is dug through: a wall that is no part of a cavern
local function rock(t)
    return wall(t) and not t.feature
end

-- natural rock, or a tile this way already dug (a step taken before)
local function rock_or_ours(t, ours)
    if rock(t) then return true end
    return ours and t ~= nil and hazard(t) == nil and not t.feature and t.shape ~= 'WALL'
end

-- a wall beside the way (any natural wall), or a tile this way already dug
local function wall_or_ours(t, ours)
    return wall(t) or rock_or_ours(t, ours)
end

local function cave_floor(t)
    return t ~= nil and t.feature and CAVE_FLOOR[t.shape] == true and not t.liquid and not t.building
end

-- The cells of a plan, in digging order: {x, y, z, text, part = 'top'|'column'|'bottom'|'tunnel'|'door'}
function plan_cells(plan)
    local out = {}
    local t = plan.top
    table.insert(out, {x = t.x, y = t.y, z = t.z, text = 'j', part = 'top'})
    for z = t.z - 1, plan.bottom_z, -1 do
        table.insert(out, {x = t.x, y = t.y, z = z, text = z == plan.bottom_z and 'u' or 'i',
                           part = z == plan.bottom_z and 'bottom' or 'column'})
    end
    for i, p in ipairs(plan.tunnel) do
        table.insert(out, {x = p.x, y = p.y, z = p.z, text = 'd', part = i == #plan.tunnel and 'door' or 'tunnel'})
    end
    return out
end

-- The straight tunnel from (x, y, z) in direction d, or nil: its tiles (the
-- last beside the cavern floor `out`) when every tile but the last has rock
-- all round it (but the tunnel's own), over and under it.
local function tunnel_from(read, x, y, z, d, ours)
    local tiles = {}
    for i = 1, TUNNEL_MAX do
        local tx, ty = x + d[1] * i, y + d[2] * i
        local t = read(tx, ty, z)
        local nt = read(tx + d[1], ty + d[2], z)
        local last = cave_floor(nt)
        -- the door's tile may be the cavern's own wall; the rest is rock outside the cavern
        if not t or not (rock_or_ours(t, ours and ours[okey(tx, ty, z)]) or (last and wall(t))) then return nil end
        table.insert(tiles, {x = tx, y = ty, z = z})
        if last then
            if i < TUNNEL_MIN then return nil end
            -- every tile but the door's: rock all round (the tunnel's own and the stair aside)
            local line = {[okey(x, y, z)] = true}
            for _, p in ipairs(tiles) do line[okey(p.x, p.y, p.z)] = true end
            for j = 1, #tiles - 1 do
                local p = tiles[j]
                for _, n in ipairs(NB) do
                    local k = okey(p.x + n[1], p.y + n[2], z)
                    if not line[k] then
                        local s = read(p.x + n[1], p.y + n[2], z)
                        if not wall_or_ours(s, ours and ours[k]) then return nil end
                    end
                end
                for _, dz in ipairs({-1, 1}) do
                    if not wall(read(p.x, p.y, z + dz)) then return nil end
                end
            end
            return tiles, {x = tx + d[1], y = ty + d[2], z = z}
        end
    end
    return nil
end

-- read(x, y, z) -> tile (ai-builder tile_info's fields) or nil; forbid(x,
-- y, z) -> the dig guard's why or nil; starts: {{x, y, z}} the fort's floor
-- tiles (already free and in the citizens' walk area), the best first;
-- layer {name, z_top, z_bottom}; opts {ours = {"x,y,z" = true} (a plan's
-- own dug tiles), deadline = os.clock() limit, from = the first start
-- tried (a search spread over calls), best = the best plan so far}. Returns
-- the plan {top = {x,y,z}, bottom_z, tunnel = {{x,y,z}}, door, out, dir,
-- depth, length, layer} (the shortest found), or nil and why; and, when the
-- deadline stopped it, the index of the next start to try.
function plan_way(read, forbid, starts, layer, opts)
    opts = opts or {}
    local ours = opts.ours
    local top_z, bot_z = tonumber(layer and layer.z_top), tonumber(layer and layer.z_bottom)
    if not top_z or not bot_z then return nil, 'the cavern layer is not known' end
    local best, why = opts.best, nil
    local tried = 0
    local list = starts or {}
    for i = tonumber(opts.from) or 1, #list do
        local s = list[i]
        if opts.deadline and os.clock() > opts.deadline and i > (tonumber(opts.from) or 1) then
            return best, 'the search goes on', i
        end
        tried = tried + 1
        local st = read(s.x, s.y, s.z)
        if s.z <= top_z then
            why = why or 'the fort\'s levels are not above the cavern'
        elseif not st or hazard(st) or st.feature or not (st.shape == 'FLOOR' or (ours and ours[okey(s.x, s.y, s.z)]))
                or (st.building and not (ours and ours[okey(s.x, s.y, s.z)])) then
            why = why or 'no free natural floor for the stair\'s top'
        else
            for z = s.z - 1, math.max(bot_z, s.z - COLUMN_MAX), -1 do
                -- the column's tile and its 3x3: solid rock (or this way's own stair)
                local ok = true
                local c = read(s.x, s.y, z)
                if not rock_or_ours(c, ours and ours[okey(s.x, s.y, z)]) then
                    ok = false
                    why = why or ('not solid rock under the stair at z %d'):format(z)
                end
                if ok then
                    for _, n in ipairs(NB) do
                        local k = okey(s.x + n[1], s.y + n[2], z)
                        if not wall_or_ours(read(s.x + n[1], s.y + n[2], z), ours and ours[k]) then
                            ok = false
                            why = why or ('not solid rock beside the stair at z %d'):format(z)
                            break
                        end
                    end
                end
                if ok and forbid then
                    local f = forbid(s.x, s.y, z)
                    if f then ok = false; why = ('the dig guard refuses z %d: %s'):format(z, tostring(f)) end
                end
                if not ok then break end      -- this start goes no deeper
                if z <= top_z then
                    for _, d in ipairs(DIRS) do
                        local tiles, out = tunnel_from(read, s.x, s.y, z, d, ours)
                        if tiles then
                            local bad
                            if forbid then
                                for _, p in ipairs(tiles) do
                                    local f = forbid(p.x, p.y, p.z)
                                    if f then bad = f; break end
                                end
                            end
                            if bad then
                                why = why or ('the dig guard refuses the tunnel: ' .. tostring(bad))
                            else
                                local cost = (s.z - z) + #tiles
                                if not best or cost < best.cost then
                                    best = {top = {x = s.x, y = s.y, z = s.z}, bottom_z = z, tunnel = tiles,
                                            door = tiles[#tiles], out = out, dir = {d[1], d[2]},
                                            depth = s.z - z, length = #tiles, layer = layer.name, cost = cost}
                                end
                            end
                        end
                    end
                end
            end
        end
        if best and opts.first then break end
    end
    if best then return best end
    if tried == 0 and not opts.from then return nil, 'no free floor on the fort\'s deepest levels' end
    return nil, why or ('no straight way from the fort\'s deepest levels to %s\'s floor through solid rock'):format(
        tostring(layer.name))
end

-- A cell's state on the map: 'done', 'marked' or 'open'
function cell_state(read, c)
    local t = read(c.x, c.y, c.z)
    if not t then return 'open' end
    if c.text == 'j' then
        if t.shape == 'STAIR_DOWN' or t.shape == 'STAIR_UPDOWN' then return 'done' end
    elseif c.text == 'u' then
        if t.shape == 'STAIR_UP' or t.shape == 'STAIR_UPDOWN' then return 'done' end
    elseif c.text == 'i' then
        if t.shape == 'STAIR_UPDOWN' then return 'done' end
    elseif t.shape ~= 'WALL' then
        return 'done'
    end
    return t.designated and 'marked' or 'open'
end

---------------------------------------------------------------------------
-- The game side
---------------------------------------------------------------------------

local function load() local d = U.site_get(SITE_KEY, {}); return type(d) == 'table' and d or {} end
local function save(d) U.site_put(SITE_KEY, d) end
local function now() local ok, t = pcall(U.abs_tick); return ok and t or 0 end

local function offset()
    local ok, v = pcall(function() return B().elevation_offset() end)
    return ok and tonumber(v) or 0
end

local function read(x, y, z)
    local ok, t = pcall(function() return B().tile_info(x, y, z) end)
    return ok and t or nil
end

local function forbid(x, y, z)
    local ok, why = pcall(function() return U.dig_forbidden(x, y, z) end)
    return ok and why or nil
end

local function walk(x, y, z)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    return ok and tonumber(g) or 0
end

local function at(p, kind)
    if not p then return nil end
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(p.x, p.y, p.z))
    if not ok or not b then return nil end
    local okt, ty = pcall(function() return df.building_type[b:getType()] end)
    if not okt or ty ~= kind then return nil end
    if kind == 'Trap' then
        local okl, lever = pcall(function() return b.trap_type == df.trap_type.Lever end)
        if not (okl and lever) then return nil end
    end
    local built = false
    pcall(function() built = b:getBuildStage() >= b:getMaxBuildStage() end)
    return {id = b.id, b = b, built = built}
end

local function door_flags(b)
    local out = {}
    pcall(function() out.closed = b.door_flags.closed == true end)
    pcall(function() out.locked = b.door_flags.forbidden == true end)
    return out
end

local function name_it(b, name)
    pcall(function() if b and tostring(b.name or '') == '' then b.name = name end end)
end

local function gates() local ok, G = pcall(reqscript, 'ai-gates'); return ok and G or nil end

local function linked(G, lever_id, target_id)
    local ok, links = pcall(G.lever_links)
    if not ok or type(links) ~= 'table' then return false end
    for _, l in ipairs(links[target_id] or {}) do if l == lever_id then return true end end
    return false
end

local function job_on(id, jt)
    local ok, yes = pcall(function()
        local b = df.building.find(id)
        for _, j in ipairs(b and b.jobs or {}) do if j.job_type == jt then return true end end
        return false
    end)
    return ok and yes
end

local function sealed()
    local ok, v = pcall(function() return next(reqscript('ai-threats').load_state().sealed or {}) ~= nil end)
    return ok and v == true
end

local function halted()
    local ok, yes = pcall(function() return reqscript('ai-status').is_halted() end)
    return ok and yes == true
end

-- the layer by name, or the first cavern ({name, z_top, z_bottom, discovered})
local function layer_of(layers, name)
    local out
    pcall(function()
        for _, l in ipairs(layers.list) do
            if l.z_top and ((name and l.name == name) or (not name and l.name == 'Cavern1')) then
                out = {name = l.name, z_top = l.z_top, z_bottom = l.z_bottom, discovered = l.discovered}
            end
        end
    end)
    return out
end

-- Every tile of the way below its top (the column and the tunnel): "x,y,z" -> true
local function way_tiles(plan)
    local out = {}
    if type(plan) ~= 'table' then return out end
    for _, c in ipairs(plan_cells(plan)) do
        if c.part ~= 'top' then out[okey(c.x, c.y, c.z)] = true end
    end
    return out
end

-- the citizens' main walk group (where most of them stand)
local function main_group()
    local count, best, bn = {}, 0, 0
    pcall(function()
        for _, u in ipairs(U.citizens(true)) do
            local g = walk(u.pos.x, u.pos.y, u.pos.z)
            if g ~= 0 then
                count[g] = (count[g] or 0) + 1
                if count[g] > bn then best, bn = g, count[g] end
            end
        end
    end)
    return best
end

-- The stair's top tried: free natural floor tiles of the fort's deepest
-- levels (the AI's own projects' bounds), in the citizens' walk group.
-- opts.caution >= 50: never a level of homes (the fort keeps the caverns
-- away from its beds); the deepest levels first.
function start_tiles(opts)
    opts = opts or {}
    local out = {}
    local Bm = B()
    local ok, list = pcall(Bm.registry_report)
    if not ok or type(list) ~= 'table' then return out end
    local by_z, homes = {}, {}
    for _, p in ipairs(list) do
        if type(p) == 'table' and tonumber(p.z) and type(p.bounds) == 'table' and p.phase ~= 'cancelled' then
            local z = tonumber(p.z)
            by_z[z] = by_z[z] or {}
            table.insert(by_z[z], p.bounds)
            if HOME_KINDS[p.kind] then homes[z] = true end
        end
    end
    local zs = {}
    for z in pairs(by_z) do
        if not (opts.layer_top and z <= opts.layer_top) then table.insert(zs, z) end
    end
    table.sort(zs)
    local cautious = tonumber(opts.caution) and tonumber(opts.caution) >= 50
    local g = main_group()
    local levels = 0
    for _, z in ipairs(zs) do
        if levels >= LEVELS_TRIED or #out >= STARTS_MAX then break end
        if not (cautious and homes[z]) then
            levels = levels + 1
            for _, bd in ipairs(by_z[z]) do
                local x1, y1 = tonumber(bd.x1 or bd[1]), tonumber(bd.y1 or bd[2])
                local x2, y2 = tonumber(bd.x2 or bd[3]), tonumber(bd.y2 or bd[4])
                if x1 and y1 and x2 and y2 then
                    -- every other tile of the level's bounds
                    for y = y1, y2, 2 do
                        for x = x1, x2, 2 do
                            if #out >= STARTS_MAX then break end
                            local t = read(x, y, z)
                            if t and t.shape == 'FLOOR' and NATURAL[t.material] and not t.building and not t.designated
                                    and not t.feature and not t.liquid and (g == 0 or walk(x, y, z) == g) then
                                table.insert(out, {x = x, y = y, z = z})
                            end
                        end
                    end
                end
            end
        end
    end
    return out
end

-- a free floor tile for the lever: 2-3 tiles from the top, in its walk group
local function lever_spot(top)
    local g = walk(top.x, top.y, top.z)
    for _, r in ipairs({2, 3}) do
        for dy = -r, r do
            for dx = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = top.x + dx, top.y + dy
                    local t = read(x, y, top.z)
                    if t and t.shape == 'FLOOR' and not t.building and not t.designated and not t.liquid
                            and walk(x, y, top.z) ~= 0 and (g == 0 or walk(x, y, top.z) == g) then
                        return {x = x, y = y, z = top.z}
                    end
                end
            end
        end
    end
end

local function hostile(u)
    local Bm = B()
    if dfhack.units.isDead(u) or not dfhack.units.isActive(u) or dfhack.units.isCitizen(u, true) then return false end
    if u.flags1.caged or u.flags1.chained then return false end
    local okf, fort = pcall(dfhack.units.isFortControlled, u)
    if okf and fort then return false end
    local okt, tame = pcall(dfhack.units.isTame, u)
    if okt and tame then return false end
    local okd, d = pcall(dfhack.units.isDanger, u)
    if okd and d then return true end
    local okw, w = pcall(Bm.hostile_wild, u)
    return okw and w == true
end

-- The dangers near the door (and in the way's own tiles): {{id, name, d,
-- great, flier}} nearest first, within radius (levels counted too)
function dangers_near(p, radius, tiles)
    local out = {}
    if not p then return out end
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function()
                local q = u.pos
                local d = math.max(math.abs(q.x - p.x), math.abs(q.y - p.y), math.abs(q.z - p.z))
                local inway = tiles and tiles[okey(q.x, q.y, q.z)]
                if (d <= radius or inway) and hostile(u) then
                    local okg, great = pcall(dfhack.units.isGreatDanger, u)
                    local okn, nm = pcall(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end)
                    local okfl, fl = pcall(function() return u.enemy.caste_flags.FLIER end)
                    table.insert(out, {id = u.id, name = okn and nm or ('unit ' .. u.id), d = inway and 0 or d,
                                       great = (okg and great) or nil, flier = (okfl and fl) or nil, in_way = inway or nil})
                end
            end)
        end
    end)
    table.sort(out, function(a, b) return a.d < b.d end)
    return out
end

-- The citizens beyond the gate: {n, first}. Shut: those in the cavern
-- side's walk group (cut off by it). Open: those on the way's tiles below
-- its top, or on a cavern tile of its layer within BEYOND_TILES of its door
-- (not a dwarf at another cavern opening of the fort's, far off).
BEYOND_TILES = 60
function beyond(d, shut)
    local n, first = 0, nil
    local plan = d.plan
    if type(plan) ~= 'table' then return {n = 0} end
    local tiles = way_tiles(plan)
    local lo, hi = tonumber(d.z_bottom) or plan.bottom_z, tonumber(d.z_top) or plan.bottom_z
    local g = shut and walk(plan.out.x, plan.out.y, plan.out.z) or 0
    -- the cavern side the fort's own walk area (the caverns open elsewhere): nobody is cut off by this gate
    if shut and (g == 0 or g == main_group()) then return {n = 0, joined = g ~= 0 or nil} end
    local door = plan.door
    pcall(function()
        for _, u in ipairs(U.citizens(true)) do
            local q = u.pos
            local out
            if shut then
                out = g ~= 0 and walk(q.x, q.y, q.z) == g
            else
                out = tiles[okey(q.x, q.y, q.z)]
                if not out and q.z >= lo and q.z <= hi
                        and math.max(math.abs(q.x - door.x), math.abs(q.y - door.y)) <= BEYOND_TILES then
                    local des = dfhack.maps.getTileFlags(q.x, q.y, q.z)
                    out = des and des.feature_global
                end
            end
            if out then
                n = n + 1
                if not first then
                    local ok, nm = pcall(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end)
                    first = ok and nm or ('unit ' .. u.id)
                end
            end
        end
    end)
    return {n = n, first = first}
end

-- loose webs on the cavern side (the far tile's walk group), once a game day,
-- read while the gate is shut (open, the walk areas are one: the last count
-- stands); none when the cavern side is the fort's own walk area already
local function webs_beyond(out_tile, shut)
    if not out_tile then return nil end
    if not shut then return WEB_MEMO and WEB_MEMO.n or nil end
    local t = now()
    if WEB_MEMO and WEB_MEMO.key == okey(out_tile.x, out_tile.y, out_tile.z) and t - WEB_MEMO.at >= 0
            and t - WEB_MEMO.at < DAY then
        return WEB_MEMO.n
    end
    local g = walk(out_tile.x, out_tile.y, out_tile.z)
    if g == 0 then return nil end
    if g == main_group() then
        WEB_MEMO = {key = okey(out_tile.x, out_tile.y, out_tile.z), at = t, n = 0}
        return 0
    end
    local n, checks = 0, 0
    local okm, M = pcall(reqscript, 'ai-mood-help')
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.ANY_WEBS) do
            if checks >= WEB_CHECKS or n >= WEBS_ENOUGH then break end
            if okm and M.web_loose(it) then
                checks = checks + 1
                local okg, wg = pcall(function() return dfhack.maps.getWalkableGroup(it.pos) end)
                if okg and wg == g then n = n + 1 end
            end
        end
    end)
    WEB_MEMO = {key = okey(out_tile.x, out_tile.y, out_tile.z), at = t, n = n}
    return n
end

-- What stands of the way: {state, lever, hatch, door, linked, gate} from the map.
-- state: none | dig | digging | lever | lever_building | hatch | hatch_building |
-- link | linking | breach | breaching | door | door_building | ready
function status(d)
    local plan = d.plan
    if type(plan) ~= 'table' then return {state = 'none'} end
    local out = {}
    local cells = plan_cells(plan)
    local marked = false
    for _, c in ipairs(cells) do
        if c.part ~= 'door' then
            local s = cell_state(read, c)
            if s == 'open' then out.state = 'dig'; return out end
            if s == 'marked' then marked = true end
        end
    end
    if marked then out.state = 'digging'; return out end
    local lv = d.lever and at(d.lever, 'Trap') or nil
    out.lever = lv
    if not lv then out.state = 'lever'; return out end
    if not lv.built then out.state = 'lever_building'; return out end
    local h = at(plan.top, 'Hatch')
    out.hatch = h
    if not h then out.state = 'hatch'; return out end
    if not h.built then out.state = 'hatch_building'; return out end
    out.closed = door_flags(h.b).closed == true
    out.gate = out.closed and 'closed' or 'open'
    local G = gates()
    out.linked = G and linked(G, lv.id, h.id) or false
    if not out.linked then
        out.state = job_on(lv.id, df.job_type.LinkBuildingToTrigger) and 'linking' or 'link'
        return out
    end
    if job_on(lv.id, df.job_type.PullLever) then out.gate = 'pulling' end
    local dc = cells[#cells]
    local ds = cell_state(read, dc)
    if ds ~= 'done' then out.state = ds == 'marked' and 'breaching' or 'breach'; return out end
    local door = at(plan.door, 'Door')
    out.door = door
    if not door then out.state = 'door'; return out end
    if not door.built then out.state = 'door_building'; return out end
    out.state = 'ready'
    return out
end

local function free_doors()
    local n = 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.DOOR) do
            local okf, free = pcall(U.item_free, it)
            if okf and free then n = n + 1 end
        end
    end)
    return n
end

local function mechanisms()
    local G = gates()
    local ok, n = pcall(function() return G.free_mechanism_count(30) end)
    return ok and tonumber(n) or 0
end

local function place(mode, text, p)
    local ok, st = pcall(B().quickfort_apply, mode, {{x = 0, y = 0, text = text}}, p.z, p.x, p.y)
    return ok and B().stat(st, mode .. '_designated') >= 1
end

local function pull(lever_id)
    local G = gates()
    local ok, done = pcall(G.pull_instant, lever_id)
    return ok and done == true
end

---------------------------------------------------------------------------
-- The watcher: an open gate shut at once for a danger
---------------------------------------------------------------------------

local function watch_alive()
    if not (CW_WATCH.on and CW_WATCH.timer) then return false end
    if type(dfhack.timeout_active) ~= 'function' then return true end
    local ok, active = pcall(dfhack.timeout_active, CW_WATCH.timer)
    return (ok and active) and true or false
end

-- Pure: shut for these dangers? (nearest first) and who is out (n)
function watch_verdict(dangers, out_n)
    local dz = dangers and dangers[1]
    if not dz then return nil end
    if dz.d <= CLOSE_TILES then return dz end
    if dz.d <= WATCH_NEAR and (out_n or 0) == 0 then return dz end
    return nil
end

local function watch_tick()
    CW_WATCH.timer = nil
    if not CW_WATCH.on then return end
    local ok, err = pcall(function()
        if halted() then return end
        local d = load()
        if not d.plan or not d.lever_id or not d.hatch_id then CW_WATCH.on = false; return end
        local h = df.building.find(d.hatch_id)
        if not h or door_flags(h).closed then CW_WATCH.on = false; return end
        local hit = watch_verdict(dangers_near(d.plan.door, WATCH_NEAR, way_tiles(d.plan)), beyond(d, false).n)
        if hit and not job_on(d.lever_id, df.job_type.PullLever) then
            if pull(d.lever_id) then
                d.open_for, d.shut_tick, d.shut_why = nil, now(), 'danger: ' .. tostring(hit.name)
                save(d)
                CW_WATCH.last = {tick = now(), unit = hit.id}
                pcall(function()
                    dfhack.gui.showAnnouncement(('AI Overseer: the cavern way shut (%s near its door)'):format(
                        tostring(hit.name)), COLOR_YELLOW, true)
                end)
                CW_WATCH.on = false
            end
        end
    end)
    CW_WATCH.error = (not ok) and tostring(err):sub(1, 160) or nil
    if CW_WATCH.on then CW_WATCH.timer = dfhack.timeout(WATCH_TICKS, 'ticks', watch_tick) end
end

function watch_start()
    if watch_alive() then return false end
    CW_WATCH.on = true
    CW_WATCH.timer = dfhack.timeout(WATCH_TICKS, 'ticks', watch_tick)
    return true
end

---------------------------------------------------------------------------
-- The actions
---------------------------------------------------------------------------

local function wait(why, extra)
    local r = {ok = false, rejected = true, waiting = true, nothing_to_do = true, error = why}
    for k, v in pairs(extra or {}) do r[k] = v end
    return r
end

-- (the way finished: its pieces' ids on record, so the seal and the lure know its door)
local function adopt(d, st)
    if st.state ~= 'ready' then return false end
    if d.door_id == st.door.id and d.lever_id == st.lever.id and d.hatch_id == st.hatch.id and d.built then
        return false
    end
    d.door_id, d.lever_id, d.hatch_id = st.door.id, st.lever.id, st.hatch.id
    d.built = d.built or now()
    name_it(st.door.b, DOOR_NAME)
    save(d)
    return true
end

-- The next step of the way. a = {caution, unfound_ok}
function build_step(a, dry_run, layers)
    a = a or {}
    local d = load()
    local t = now()
    if type(d.plan) ~= 'table' then
        if d.refused and t - (tonumber(d.refused.tick) or 0) < REFUSED_RETRY then
            return {ok = false, rejected = true, error = 'no way found: ' .. tostring(d.refused.why), refused = true}
        end
        local layer = layer_of(layers or {list = {}})
        if not layer then return {ok = false, rejected = true, error = 'no first cavern on this map'} end
        if not layer.discovered and a.unfound_ok ~= true then
            return wait('the first cavern is not found yet (and the AI may not open it)')
        end
        if sealed() then return wait('the caverns are sealed against a great beast') end
        local starts = start_tiles({caution = a.caution, layer_top = layer.z_top})
        -- (a search takes several calls on a real map: ~0.1 s a start) the place it reached kept
        local sr = type(d.search) == 'table' and d.search.n == #starts and d.search or nil
        local cache = {}
        local function cread(x, y, z)
            local k = okey(x, y, z)
            local v = cache[k]
            if v == nil then v = read(x, y, z) or false; cache[k] = v end
            return v or nil
        end
        local plan, why, nxt = plan_way(cread, forbid, starts, layer,
                                        {deadline = os.clock() + SEARCH_SECONDS, from = sr and sr.next or nil,
                                         best = sr and sr.best or nil})
        if nxt then
            if not dry_run then d.search = {n = #starts, next = nxt, best = plan}; save(d) end
            return {ok = true, dry_run = dry_run or nil, stage = 'search', tried = nxt - 1, starts = #starts,
                    found = plan ~= nil or nil}
        end
        d.search = nil
        if not plan then
            if not dry_run then d.refused = {why = why, tick = t}; save(d) end
            return {ok = false, rejected = true, error = 'no way found: ' .. tostring(why), refused = true}
        end
        if dry_run then
            return {ok = true, dry_run = true, top = plan.top, door = plan.door, depth = plan.depth, length = plan.length}
        end
        d = {plan = plan, layer = layer.name, z_top = layer.z_top, z_bottom = layer.z_bottom, started = t}
        save(d)
    end
    local plan = d.plan
    local st = status(d)
    local off = offset()
    local where = ('x%d y%d elevation %d'):format(plan.top.x, plan.top.y, plan.top.z + off)
    if st.state == 'dig' then
        -- every cell but the door's, by level (the dig guard on each)
        local by_z = {}
        for _, c in ipairs(plan_cells(plan)) do
            if c.part ~= 'door' and cell_state(read, c) == 'open' then
                by_z[c.z] = by_z[c.z] or {}
                table.insert(by_z[c.z], {x = c.x - plan.top.x, y = c.y - plan.top.y, text = c.text})
            end
        end
        local n = 0
        for z, cells in pairs(by_z) do
            local ok = B().qf_try('dig', cells, z, plan.top.x, plan.top.y, dry_run, #cells, false)
            if not ok then
                return {ok = false, error = ('the dig at elevation %d: quickfort would not mark it'):format(z + off)}
            end
            n = n + #cells
        end
        return {ok = true, dry_run = dry_run or nil, stage = 'dig', marked = n, top = where}
    elseif st.state == 'digging' then
        return wait('the way is being dug')
    elseif st.state == 'lever' then
        local lv = (d.lever and read(d.lever.x, d.lever.y, d.lever.z) and d.lever) or lever_spot(plan.top)
        if not lv then return {ok = false, rejected = true, error = 'no free floor near the stair for the lever'} end
        if dry_run then return {ok = true, dry_run = true, stage = 'lever'} end
        if not place('build', 'Tl', lv) then return {ok = false, error = 'the game would not place the lever'} end
        d.lever = lv
        save(d)
        return {ok = true, stage = 'lever_placed'}
    elseif st.state == 'hatch' then
        if dry_run then return {ok = true, dry_run = true, stage = 'hatch'} end
        if not place('build', 'H', plan.top) then return {ok = false, error = 'the game would not place the hatch'} end
        return {ok = true, stage = 'hatch_placed'}
    elseif st.state == 'link' then
        if mechanisms() < 2 then return wait('2 free mechanisms are needed for the link (the brain has them made meanwhile)', {mechanisms = mechanisms()}) end
        name_it(st.lever.b, LEVER_NAME)
        name_it(st.hatch.b, GATE_NAME)
        if dry_run then return {ok = true, dry_run = true, stage = 'link'} end
        local res = gates().link_lever(st.lever.id, st.hatch.id, false)
        if not res.ok then return {ok = false, error = res.error} end
        d.lever_id, d.hatch_id = st.lever.id, st.hatch.id
        save(d)
        return {ok = true, stage = 'linking'}
    elseif st.state == 'breach' then
        if sealed() then return wait('the caverns are sealed against a great beast') end
        local near = dangers_near(plan.out, BREACH_CLEAR)
        if #near > 0 then return wait(('%s is near the cavern side'):format(near[1].name)) end
        if free_doors() < 1 then return wait('a door is needed in store before the cavern is opened (the brain has one made meanwhile)', {doors_free = 0}) end
        if st.closed then
            -- the diggers go down through it
            if dry_run then return {ok = true, dry_run = true, stage = 'open_for_breach'} end
            if not pull(st.lever.id) then return {ok = false, error = 'the gate would not open for the diggers'} end
        end
        if dry_run then return {ok = true, dry_run = true, stage = 'breach'} end
        local ok = B().qf_try('dig', {{x = 0, y = 0, text = 'd'}}, plan.door.z, plan.door.x, plan.door.y, false, 1, false)
        if not ok then return {ok = false, error = 'the game would not dig the last tile into the cavern'} end
        d.lever_id, d.hatch_id = st.lever.id, st.hatch.id
        d.open_for, d.opened_tick = 'build', t
        save(d)
        watch_start()
        return {ok = true, stage = 'breach'}
    elseif st.state == 'door' then
        if dry_run then return {ok = true, dry_run = true, stage = 'door'} end
        if not place('build', 'd', plan.door) then return {ok = false, error = 'the game would not place the door'} end
        return {ok = true, stage = 'door_placed'}
    elseif st.state == 'ready' then
        local changed = false
        if d.door_id ~= st.door.id or d.lever_id ~= st.lever.id or d.hatch_id ~= st.hatch.id then
            d.door_id, d.lever_id, d.hatch_id, changed = st.door.id, st.lever.id, st.hatch.id, true
            name_it(st.door.b, DOOR_NAME)
        end
        if not d.built then d.built, changed = t, true end
        if d.open_for == 'build' and not st.closed then
            -- finished: shut (unless a dwarf is still out there: then the brain shuts it)
            if beyond(d, false).n == 0 and not dry_run and pull(st.lever.id) then
                d.open_for, d.shut_tick, d.shut_why, changed = nil, t, 'built', true
            end
        end
        if changed and not dry_run then save(d) end
        if changed then
            pcall(function()
                dfhack.gui.showAnnouncement(('AI Overseer: the cavern way stands (%s, its gate shut)'):format(where),
                                            COLOR_GREEN, true)
            end)
            return {ok = true, stage = 'finished', dry_run = dry_run or nil}
        end
        return {ok = false, rejected = true, nothing_to_do = true, error = 'the cavern way is built'}
    end
    return wait('the way\'s ' .. st.state:gsub('_', ' ') .. ' is under way')
end

-- The gate opened for a job (why) or shut. release_only (the AI halted): shut only.
function set_gate(open, why, dry_run, release_only)
    if open and release_only then return {ok = false, rejected = true, halted = true, error = 'the AI is halted'} end
    local d = load()
    if type(d.plan) ~= 'table' then return {ok = false, rejected = true, error = 'no cavern way'} end
    local st = status(d)
    if not st.lever or not st.hatch or not st.linked then
        return {ok = false, rejected = true, error = 'the way\'s gate is not linked yet (' .. st.state .. ')'}
    end
    if open and st.state ~= 'ready' then
        return {ok = false, rejected = true, error = 'the cavern way is not finished (' .. st.state .. ')'}
    end
    pcall(adopt, d, st)
    local want = open and 'open' or 'closed'
    if open then
        local near = dangers_near(d.plan.door, CLOSE_TILES * 2, way_tiles(d.plan))
        if why ~= 'lure' and #near > 0 then
            return {ok = false, rejected = true, waiting = true, error = ('%s is near its door'):format(near[1].name)}
        end
        local dr = st.door and door_flags(st.door.b) or {}
        if why == 'lure' and not dr.locked then
            return {ok = false, rejected = true, error = 'for the lure the door must be locked first (the seal locks it)'}
        end
        if why ~= 'lure' and dr.locked then
            return {ok = false, rejected = true, error = 'the way\'s door is locked (the seal or a lure holds it)'}
        end
        local okl, held = pcall(function() return reqscript('ai-lure').held_open() end)
        if okl and type(held) == 'table' and st.door and held[st.door.id] then
            return {ok = false, rejected = true, error = 'a lure holds the way\'s door open: the gate stays shut'}
        end
    end
    if (st.closed and 'closed' or 'open') == want then
        if open then watch_start() end
        if not dry_run and d.open_for ~= (open and why or nil) and open then d.open_for = why; save(d) end
        return {ok = false, rejected = true, nothing_to_do = true, error = 'the gate is ' .. want .. ' already'}
    end
    if dry_run then return {ok = true, dry_run = true, gate = want} end
    if not pull(st.lever.id) then return {ok = false, error = 'the lever pull failed'} end
    local t = now()
    if open then
        d.open_for, d.opened_tick = why or 'job', t
        watch_start()
    else
        d.open_for, d.shut_tick, d.shut_why = nil, t, why or 'job done'
    end
    save(d)
    return {ok = true, gate = want, why = why}
end

---------------------------------------------------------------------------
-- What other modules read
---------------------------------------------------------------------------

-- The door's tile on ai-threats' openings record, once built: {x, y, z} or nil
function door_opening()
    local d = load()
    if type(d.plan) ~= 'table' or not d.door_id then return nil end
    return {x = d.plan.door.x, y = d.plan.door.y, z = d.plan.door.z, door_id = d.door_id}
end

-- The way's gate (its hatch) as ai-gates keys: the gate watcher leaves it to this module
function own_keys()
    local d = load()
    if type(d.plan) ~= 'table' then return {} end
    local t = d.plan.top
    return {[(t.z * 4096 + t.y) * 4096 + t.x] = true}
end

function is_way_door(id)
    local d = load()
    return id ~= nil and d.door_id ~= nil and d.door_id == id
end

-- The `cavern_way` section.
function report(layers)
    local d = load()
    local off = offset()
    if type(d.plan) ~= 'table' then
        local out = {state = 'none'}
        if d.refused then
            out.state, out.why = 'refused', d.refused.why
            out.retry_ticks = math.max(0, REFUSED_RETRY - (now() - (tonumber(d.refused.tick) or 0)))
        end
        return out
    end
    local plan = d.plan
    local st = status(d)
    pcall(adopt, d, st)
    local function el(p) return p and {x = p.x, y = p.y, z = p.z, elevation = p.z + off} or nil end
    local out = {state = st.state, layer = d.layer, top = el(plan.top), door = el(plan.door), out = el(plan.out),
                 depth = plan.depth, length = plan.length, gate = st.gate, linked = st.linked or nil,
                 lever_id = st.lever and st.lever.id or nil, hatch_id = st.hatch and st.hatch.id or nil,
                 door_id = st.door and st.door.id or nil, open_for = d.open_for, opened_tick = d.opened_tick,
                 shut_tick = d.shut_tick, shut_why = d.shut_why, built = d.built}
    if st.door then
        local f = door_flags(st.door.b)
        out.door_locked = f.locked or nil
    end
    local list = dangers_near(plan.door, REPORT_RADIUS, way_tiles(plan))
    out.dangers = {}
    for i = 1, math.min(5, #list) do table.insert(out.dangers, list[i]) end
    local by = beyond(d, st.closed == true)
    out.beyond, out.beyond_first = by.n, by.first
    if st.state == 'ready' or st.state == 'door' or st.state == 'door_building' then out.webs = webs_beyond(plan.out, st.closed == true) end
    -- (item6, R32 e) the parts a waiting step wants, so the brain orders them
    -- rather than asking for the step every cycle (D: "2 free mechanisms are
    -- needed for the link" 69 times; C waited for a door in store)
    if st.state == 'link' then out.mechanisms = mechanisms() end
    if st.state == 'breach' or st.state == 'breaching' or st.state == 'door' or st.state == 'door_building' then
        out.doors_free = free_doors()
    end
    out.watch = watch_alive() or nil
    out.watch_error = CW_WATCH.error
    -- an open gate (a reload, the brain's open): the watcher on
    if st.gate == 'open' and (st.state == 'ready' or st.state == 'breaching' or st.state == 'door'
            or st.state == 'door_building') and not out.watch then
        pcall(watch_start)
        out.watch = watch_alive() or nil
    end
    return out
end
