-- ai-siege: the fort's answer to a siege beyond the gates, and the squads
-- sent out for the fort's people in the open (item5).
--
--   report()              the `siege` section (daily, cached a day): each
--                         gated surface entrance's fortifications and the
--                         posts behind them, the natural walls beside it that
--                         could take fortifications (smooth, carve, or a dig
--                         to thin a 2-thick wall), a spot for a ballista; the
--                         siege engines (the AI's named "AI ballista"), their
--                         parts and arrows, the siege operators and engineers
--   fortify_post(...)     fortifications carved into the thin natural walls
--                         beside an entrance (smoothed first; a 2-thick wall
--                         thinned by digging its inner tile, from inside)
--   archer_post(...)      the "AI archer post" burrow over the floor behind
--                         an entrance's fortifications, the crossbow squads
--                         ordered to hold it (ai-military defend: the order
--                         is the AI's, recalled like the gate guard's)
--   place_engine(...)     a ballista (or catapult) on free roofed floor
--                         behind the fortifications, facing out, named
--   place_shop(...)       a siege workshop (5x5) on free roofed floor near
--                         a gated entrance, when the fort has none
--   field_watch()         the `field_watch` section (each pulse): hostiles
--                         near a caravan's merchants, and hostile wild
--                         animals (large predators, agitated ones) near the
--                         dwarves at work outside
--
-- Nothing here touches the player's own: a siege engine counts as the AI's
-- only when it carries the AI's name, the post burrow is the AI's by name,
-- and squads on the player's orders are refused (ai-military defend).
-- Reads walk small boxes round at most ENTRANCES_MAX entrances (each tile
-- read once a survey); the units are walked once a pulse.
--@ module = true

local U = reqscript('ai-util')

POST_RADIUS = 7            -- tiles round an entrance looked at for fortifications and posts
ENTRANCES_MAX = 4          -- entrances surveyed at most
FORTIFY_MAX = 8            -- tiles designated in one fortify_post at most
ENGINE_NAME = 'AI ballista'
CATAPULT_NAME = 'AI catapult'
POST_BURROW = 'AI archer post'
CARAVAN_NEAR = 25          -- hostiles this near a merchant are listed (the brain decides from its own number)
WILD_NEAR = 40             -- hostile wild animals this near a dwarf are listed
ROWS_MAX = 12
ENGINE_KEYS = {ballista = 'ib', catapult = 'ic'}     -- quickfort's siege engine keys (centred, 3x3)
-- (fix3) no SOIL: soil can't be smoothed nor fortifications carved in it
NATURAL = {STONE = true, MINERAL = true, LAVA_STONE = true, FEATURE = true}
ENGINES_KEY = 'ai-overseer/siege-engines'            -- the AI's engines' building ids (site data)

local ORTHO = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

-- engine_spot's facing (the way out, screen directions) as the engine's
-- df.siegeengine_orientation name (+y is south)
ENGINE_ORIENTATION = {Up = 'North', Down = 'South', Left = 'West', Right = 'East'}

local report_citizens = U.report_citizens      -- (r6) ai-util's, the copy that was here
local report_units = U.report_units            -- (r6) ai-util's, the copy that was here

-- The modules this one leans on, through functions the tests replace.
function gates() return reqscript('ai-gates') end
function builder() return reqscript('ai-builder') end
function military() return reqscript('ai-military') end
function society() return reqscript('ai-society') end

local function gkey(x, y, z) return (z * 4096 + y) * 4096 + x end      -- ai-gates' key (GATES.inside)

---------------------------------------------------------------------------
-- The map
---------------------------------------------------------------------------

-- {shape, material, smooth, walk, outside, hidden, liquid, occupied,
-- designated, aquifer} or nil off the map.
function tile(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    local des, occ = dfhack.maps.getTileFlags(x, y, z)
    if not des then return nil end
    local a = df.tiletype.attrs[tt]
    local out = {
        shape = df.tiletype_shape[a.shape],
        material = df.tiletype_material[a.material],
        smooth = df.tiletype_special[a.special] == 'SMOOTH',
        walk = df.tiletype_shape.attrs[a.shape].walkable == true,
        outside = des.outside == true,
        hidden = des.hidden == true,
        liquid = (des.flow_size or 0) > 0,
        occupied = occ ~= nil and occ.building ~= df.tile_building_occ.None,
        designated = des.dig ~= df.tile_dig_designation.No,
    }
    pcall(function() if des.smooth ~= 0 then out.designated = true end end)
    pcall(function() out.aquifer = des.water_table == true end)
    return out
end

-- One survey's reads: each tile read once.
local function reader()
    local memo = {}
    return function(x, y, z)
        local k = gkey(x, y, z)
        local v = memo[k]
        if v == nil then
            v = tile(x, y, z) or false
            memo[k] = v
        end
        return v or nil
    end
end

local function dist(a, b)
    return math.abs(a.x - b.x) + math.abs(a.y - b.y) + 3 * math.abs(a.z - b.z)
end

---------------------------------------------------------------------------
-- The posts beside an entrance
---------------------------------------------------------------------------

-- Pure-ish (reads through `T`, the inside map `inside`): what stands round
-- entrance `e` at its level. Floor "in" is the fort's inside, walkable,
-- roofed, dry and free; "out" is walkable, dry floor that is not the fort's
-- inside. A thin wall is a natural wall with "in" on one side and "out"
-- straight across; a thick one has a second natural wall between.
function survey(e, inside, T, engines)
    local R = POST_RADIUS
    local z = e.z
    local function is_in(x, y)
        local t = T(x, y, z)
        return t and inside[gkey(x, y, z)] == true and t.walk and not t.outside and not t.liquid or false
    end
    local function is_free_in(x, y)
        local t = T(x, y, z)
        return is_in(x, y) and not t.occupied and not t.designated
    end
    local function is_out(x, y)
        local t = T(x, y, z)
        return t and inside[gkey(x, y, z)] ~= true and t.walk and not t.liquid or false
    end
    -- (fix3) never an aquifer's wall: a fortification carved in it, or the
    -- inner tile of a thick one dug out, lets the water in
    local function natural_wall(x, y)
        local t = T(x, y, z)
        return t and t.shape == 'WALL' and NATURAL[t.material] == true and not t.hidden and not t.aquifer or false
    end
    local opening = {}
    for _, k in ipairs(e.inside_list or {}) do opening[k] = true end
    local row = {id = e.id, x = e.x, y = e.y, z = z, kind = e.kind, sealed = e.sealed == true,
                 fortifications = 0, posts = 0, carve = 0, smooth = 0, dig = 0, engines_near = 0}
    local posts, seen_post = {}, {}
    local fort_tiles, carve, smooth, dig = {}, {}, {}, {}
    local seen_dig = {}
    for y = e.y - R, e.y + R do
        for x = e.x - R, e.x + R do
            local t = T(x, y, z)
            if t and t.shape == 'FORTIFICATION' then
                row.fortifications = row.fortifications + 1
                table.insert(fort_tiles, {x = x, y = y, z = z})
                for _, d in ipairs(ORTHO) do
                    local px, py = x + d[1], y + d[2]
                    local pk = gkey(px, py, z)
                    if is_in(px, py) and not seen_post[pk] then
                        seen_post[pk] = true
                        table.insert(posts, {x = px, y = py, z = z})
                    end
                end
            elseif natural_wall(x, y) and not t.designated then
                for _, d in ipairs(ORTHO) do
                    local dx, dy = d[1], d[2]
                    if is_in(x - dx, y - dy) then
                        if is_out(x + dx, y + dy) then
                            local c = {x = x, y = y, z = z, face = {dx, dy}}
                            if t.smooth then table.insert(carve, c) else table.insert(smooth, c) end
                            break
                        elseif natural_wall(x + dx, y + dy) and is_out(x + 2 * dx, y + 2 * dy)
                                and not seen_dig[gkey(x, y, z)] then
                            -- a 2-thick wall: its inner tile dug from inside, the outer one carved later
                            seen_dig[gkey(x, y, z)] = true
                            table.insert(dig, {x = x, y = y, z = z, face = {dx, dy}})
                            break
                        end
                    end
                end
            end
        end
    end
    row.posts, row.carve, row.smooth, row.dig = #posts, #carve, #smooth, #dig
    -- the AI's engines and anyone's near it
    for _, g in ipairs(engines or {}) do
        if g.z == z and math.abs(g.x - e.x) <= R + 3 and math.abs(g.y - e.y) <= R + 3 then
            row.engines_near = row.engines_near + 1
        end
    end
    -- a ballista's spot: a 3x3 of free inside floor with a free ring round it
    -- (it never closes a corridor), none of it the opening, 2-6 tiles behind a
    -- fortification standing, facing it
    if #fort_tiles > 0 then
        local best, best_d
        for cy = e.y - R + 2, e.y + R - 2 do
            for cx = e.x - R + 2, e.x + R - 2 do
                local near, nf
                for _, f in ipairs(fort_tiles) do
                    local d = math.max(math.abs(f.x - cx), math.abs(f.y - cy))
                    if not near or d < near then near, nf = d, f end
                end
                if near and near >= 2 and near <= 6 and (not best_d or near < best_d) then
                    local ok = true
                    for dy = -2, 2 do
                        for dx = -2, 2 do
                            if ok and (opening[gkey(cx + dx, cy + dy, z)] or not is_free_in(cx + dx, cy + dy)) then
                                ok = false
                            end
                        end
                    end
                    if ok then
                        local fx, fy = nf.x - cx, nf.y - cy
                        local facing
                        if math.abs(fx) >= math.abs(fy) then facing = fx > 0 and 'Right' or 'Left'
                        else facing = fy > 0 and 'Down' or 'Up' end
                        best, best_d = {x = cx, y = cy, z = z, facing = facing}, near
                    end
                end
            end
        end
        row.engine_spot = best
    end
    return row, {posts = posts, carve = carve, smooth = smooth, dig = dig}
end

---------------------------------------------------------------------------
-- Siege engines, their parts and arrows, operators
---------------------------------------------------------------------------

local function ai_engine_ids()
    local ids = {}
    for _, id in ipairs(U.site_get(ENGINES_KEY, {}) or {}) do
        if tonumber(id) then ids[tonumber(id)] = true end
    end
    return ids
end

local function note_engine(id)
    local list = U.site_get(ENGINES_KEY, {}) or {}
    table.insert(list, id)
    while #list > 20 do table.remove(list, 1) end
    U.site_put(ENGINES_KEY, list)
end

-- Every siege engine on the map: {id, kind, x, y, z, built, ai, facing}.
function engines()
    local out = {}
    local mine = ai_engine_ids()
    -- (0.105.48) buildings.other has no SIEGEENGINE vector in DF 53.17: the
    -- whole list, filtered by type below
    local list = df.global.world.buildings.all
    for _, b in ipairs(list) do
        local okt, is_engine = pcall(function() return b:getType() == df.building_type.SiegeEngine end)
        if okt and is_engine then
            local row = {id = b.id, x = b.centerx, y = b.centery, z = b.z}
            pcall(function() row.kind = tostring(df.siegeengine_type[b.type]):lower() end)
            pcall(function() row.built = b:getBuildStage() >= b:getMaxBuildStage() end)
            pcall(function() row.facing = df.siegeengine_orientation[b.facing] end)
            local okn, name = pcall(function() return b.name end)
            row.ai = mine[b.id] == true or (okn and (name == ENGINE_NAME or name == CATAPULT_NAME)) or false
            table.insert(out, row)
        end
    end
    return out
end

local function count_items(kind)
    local n = 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other[kind]) do
            if U.item_free == nil or U.item_free(it, {in_job = true}) then n = n + 1 end
        end
    end)
    return n
end

local function labour_holders(name)
    local labor = df.unit_labor[name]
    if labor == nil then return nil end
    local n = 0
    for _, u in ipairs(report_citizens(true)) do
        local ok, has = pcall(function() return u.status.labors[labor] end)
        if ok and has and u.military.squad_id < 0 then n = n + 1 end
    end
    return n
end

-- The burrow the AI posts its archers in (nil when none).
function post_burrow()
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if b.name == POST_BURROW then return b end
    end
    return nil
end

-- The surface entrances worth a post (gated first), at most ENTRANCES_MAX.
local function entrances_of(G)
    local list = {}
    for _, e in ipairs((G.GATES or {}).entrances or {}) do
        if e.kind ~= 'cavern' and e.x and e.y and e.z then table.insert(list, e) end
    end
    table.sort(list, function(a, b)
        if (a.sealed == true) ~= (b.sealed == true) then return a.sealed == true end
        return (a.id or 0) < (b.id or 0)
    end)
    while #list > ENTRANCES_MAX do table.remove(list) end
    return list
end

function report()
    local G = gates()
    local out = {entrances = {}, scanned = (G.GATES or {}).scanned == true}
    local eng = engines()
    out.engines = eng
    out.ai_engines, out.built, out.planned = 0, 0, 0
    for _, g in ipairs(eng) do
        if g.ai then
            out.ai_engines = out.ai_engines + 1
            if g.built then out.built = out.built + 1 else out.planned = out.planned + 1 end
        end
    end
    out.all_built = 0
    for _, g in ipairs(eng) do if g.built then out.all_built = out.all_built + 1 end end
    if out.scanned and (G.GATES or {}).inside then
        local T = reader()
        for _, e in ipairs(entrances_of(G)) do
            local ok, row = pcall(survey, e, G.GATES.inside, T, eng)
            if ok then table.insert(out.entrances, row)
            else table.insert(out.entrances, {id = e.id, error = tostring(row):sub(1, 160)}) end
        end
    end
    out.ammo = {siege_ammo = count_items('SIEGEAMMO'), ballista_parts = count_items('BALLISTAPARTS'),
                catapult_parts = count_items('CATAPULTPARTS'), arrowheads = count_items('BALLISTAARROWHEAD')}
    out.shops = shop_count()
    out.operators = labour_holders('SIEGEOPERATE')
    out.engineers = labour_holders('SIEGECRAFT')
    local b = post_burrow()
    if b then
        out.post_burrow = b.id
        pcall(function()
            local n = 0
            for _, sid in ipairs(U.fort_entity().squads) do
                local sq = df.squad.find(sid)
                for _, o in ipairs(sq and sq.orders or {}) do
                    if df.squad_order_defend_burrowsst:is_instance(o) and #o.burrows == 1 and o.burrows[0] == b.id then
                        n = n + 1
                    end
                end
            end
            out.posted = n
        end)
    end
    return out
end

local function entrance_by_id(id)
    local G = gates()
    for _, e in ipairs((G.GATES or {}).entrances or {}) do
        if e.id == id then return e, G end
    end
    return nil, G
end

local function qf(mode, cells, z, dry_run)
    local B = builder()
    local ok, fail, stats = B.qf_try(mode, cells, z, 0, 0, dry_run, 1, false)
    return ok, fail, stats
end

-- Fortifications beside an entrance: carve the thin smooth walls, smooth the
-- rough ones (carved at a later call), and only where there are none of
-- those, dig the inner tile of a 2-thick wall (from inside: the outer wall
-- stays). At most `max` tiles (FORTIFY_MAX).
function fortify_post(entrance_id, max, dry_run)
    local e, G = entrance_by_id(entrance_id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if not (G.GATES or {}).inside then return {ok = false, rejected = true, error = 'the fort is not mapped yet'} end
    if e.kind == 'cavern' then return {ok = false, rejected = true, error = 'posts are for surface entrances'} end
    max = math.max(1, math.min(FORTIFY_MAX, math.floor(tonumber(max) or 4)))
    local row, lists = survey(e, G.GATES.inside, reader(), engines())
    local cells, what = {}, nil
    if #lists.carve > 0 then
        what = 'carve'
        for i = 1, math.min(max, #lists.carve) do
            local c = lists.carve[i]
            table.insert(cells, {x = c.x, y = c.y, text = 'F'})
        end
    elseif #lists.smooth > 0 then
        what = 'smooth'
        for i = 1, math.min(max, #lists.smooth) do
            local c = lists.smooth[i]
            table.insert(cells, {x = c.x, y = c.y, text = 's'})
        end
    elseif #lists.dig > 0 then
        what = 'dig'
        for i = 1, math.min(max, #lists.dig) do
            local c = lists.dig[i]
            table.insert(cells, {x = c.x, y = c.y, text = 'd'})
        end
    end
    if not what then
        return {ok = false, rejected = true, fortifications = row.fortifications,
                error = row.fortifications > 0 and 'no more natural wall beside it to fortify'
                    or 'no natural wall beside it thin enough to fortify (a wall between the fort and the outside)'}
    end
    local ok, fail, stats = qf('dig', cells, e.z, dry_run)
    if not ok then
        return {ok = false, error = ('quickfort would not %s there (%s run)'):format(what, tostring(fail)),
                tiles = #cells}
    end
    return {ok = true, dry_run = dry_run or nil, step = what, tiles = #cells, entrance_id = e.id,
            fortifications = row.fortifications,
            at = {x = cells[1].x, y = cells[1].y, z = e.z}}
end

-- The archers posted behind an entrance's fortifications: the post burrow
-- set over its post tiles (and the free inside floor next to them), each
-- squad given a defend order on it (ai-military defend: the player's orders
-- refuse it).
function archer_post(entrance_id, squad_ids, dry_run)
    local e, G = entrance_by_id(entrance_id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if not (G.GATES or {}).inside then return {ok = false, rejected = true, error = 'the fort is not mapped yet'} end
    local T = reader()
    local row, lists = survey(e, G.GATES.inside, T, {})
    if #lists.posts == 0 then
        return {ok = false, rejected = true, error = 'no fortification with roofed floor behind it at that entrance'}
    end
    local tiles, seen = {}, {}
    local function add(x, y, z)
        local k = gkey(x, y, z)
        if seen[k] then return end
        local t = T(x, y, z)
        if t and G.GATES.inside[k] and t.walk and not t.outside and not t.liquid then
            seen[k] = true
            table.insert(tiles, {x = x, y = y, z = z})
        end
    end
    for _, p in ipairs(lists.posts) do add(p.x, p.y, p.z) end
    for _, p in ipairs(lists.posts) do
        for _, d in ipairs(ORTHO) do add(p.x + d[1], p.y + d[2], p.z) end
    end
    if dry_run then
        return {ok = true, dry_run = true, tiles = #tiles, posts = #lists.posts, squads = #(squad_ids or {})}
    end
    local b = post_burrow()
    if not b then
        local okb, nb = pcall(function() return society().new_burrow(POST_BURROW) end)
        if not (okb and nb) then return {ok = false, error = 'the post burrow could not be made: ' .. tostring(nb):sub(1, 120)} end
        b = nb
    end
    pcall(dfhack.burrows.clearTiles, b)
    for _, p in ipairs(tiles) do dfhack.burrows.setAssignedTile(b, xyz2pos(p.x, p.y, p.z), true) end
    local M = military()
    local sent, refused = {}, {}
    for _, sid in ipairs(squad_ids or {}) do
        local r = M.defend(sid, b.id)
        if r and r.ok then table.insert(sent, sid)
        else table.insert(refused, tostring(sid) .. ': ' .. tostring(r and r.error)) end
    end
    if #sent == 0 then
        return {ok = false, rejected = true, burrow_id = b.id,
                error = 'no squad took the post (' .. table.concat(refused, '; ') .. ')'}
    end
    return {ok = true, burrow_id = b.id, tiles = #tiles, squads = sent, entrance_id = e.id,
            refused = #refused > 0 and refused or nil}
end

-- A ballista (or catapult) behind an entrance's fortifications, facing out;
-- buildingplan waits for its parts. Named, and its id kept, as the AI's.
function place_engine(entrance_id, kind, dry_run)
    kind = kind or 'ballista'
    local text = ENGINE_KEYS[kind]
    if not text then return {ok = false, rejected = true, error = 'kind is ballista or catapult'} end
    local e, G = entrance_by_id(entrance_id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if not (G.GATES or {}).inside then return {ok = false, rejected = true, error = 'the fort is not mapped yet'} end
    local eng = engines()
    local row = survey(e, G.GATES.inside, reader(), eng)
    if row.engines_near > 0 then
        return {ok = false, rejected = true, error = 'a siege engine stands at that entrance already'}
    end
    local sp = row.engine_spot
    if not sp then
        return {ok = false, rejected = true,
                error = row.fortifications == 0
                    and 'no fortification beside that entrance to shoot through yet'
                    or 'no free 5x5 of roofed floor behind the fortifications for it'}
    end
    local ok, fail = qf('build', {{x = sp.x, y = sp.y, text = text}}, sp.z, dry_run)
    if not ok then return {ok = false, error = ('quickfort would not place the %s (%s run)'):format(kind, tostring(fail))} end
    if dry_run then return {ok = true, dry_run = true, at = sp, kind = kind, facing = sp.facing} end
    local out = {ok = true, at = sp, kind = kind, facing = sp.facing, entrance_id = e.id}
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(sp.x, sp.y, sp.z))
        if b then
            out.building_id = b.id
            pcall(function() b.name = (kind == 'catapult') and CATAPULT_NAME or ENGINE_NAME end)
            -- (0.105.48 r2) facing is a df.siegeengine_orientation (North..
            -- Northwest), not a building_siegeenginest.T_facing (no such type,
            -- so it was never set); its resting one too, so it turns back out
            local o = ENGINE_ORIENTATION[sp.facing]
            local okf = o ~= nil and pcall(function()
                local v = df.siegeengine_orientation[o]
                assert(type(v) == 'number')
                b.facing = v
            end)
            if okf then pcall(function() b.resting_orientation = df.siegeengine_orientation[o] end) end
            out.facing_set = okf or nil
            note_engine(b.id)
        end
    end)
    return out
end

-- A siege workshop (5x5) near a gated entrance: free roofed inside floor with
-- a free ring round it (it never closes a way through), none of it the
-- opening, within SHOP_RADIUS of the entrance on its level. Not when one
-- stands (anyone's). Returns {ok, at} or why not.
SHOP_RADIUS = 15

function shop_count()
    local n = 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            if df.workshop_type[b.type] == 'Siege' then n = n + 1 end
        end
    end)
    return n
end

function shop_spot(e, inside, T, ctx)
    local z = e.z
    local opening = {}
    for _, k in ipairs(e.inside_list or {}) do opening[k] = true end
    local purpose = shop_purpose_test(ctx)      -- (Y1) never in a room with a purpose
    local function free(x, y)
        local t = T(x, y, z)
        return t and inside[gkey(x, y, z)] == true and t.walk and not t.outside and not t.liquid
            and not t.occupied and not t.designated and not opening[gkey(x, y, z)]
            and not purpose(x, y, z) or false
    end
    local best, best_d
    for cy = e.y - SHOP_RADIUS, e.y + SHOP_RADIUS do
        for cx = e.x - SHOP_RADIUS, e.x + SHOP_RADIUS do
            local d = math.abs(cx - e.x) + math.abs(cy - e.y)
            if (not best_d or d < best_d) and d >= 5 then
                local ok = true
                for dy = -3, 3 do
                    for dx = -3, 3 do
                        if ok and not free(cx + dx, cy + dy) then ok = false end
                    end
                end
                if ok then best, best_d = {x = cx, y = cy, z = z}, d end
            end
        end
    end
    return best
end

-- (r2h7) R3 and the 15-16 Nov run: "no free 7x7 of roofed floor within 15
-- tiles of that entrance" A 35+42, D 40, E 29+21 times, every time: a stair
-- entrance with a 3-wide gatehouse has no such floor beside it. A siege
-- workshop is 5x5 and need not stand by the gate (its parts are carried to
-- the engines). Anywhere on the fort's inside then, nearest the entrance
-- first: a 5x5 of free roofed floor (FLOOR tiles, none of it the opening)
-- whose ring is wall or free floor, the free ring tiles in one run round it
-- (so nothing it stands on was a way through: a corridor's two sides are two
-- runs) and at least one of them beside an edge (not only a corner). A
-- workshop level's empty 5x5 room, its 3-wide door onto the corridor, is
-- such a spot.
-- (Y1) Bounded: the AI's workshop levels are looked at first, then the
-- fort's inside outward from the entrance and the fort's stair (a walk
-- flood: nearest by walking first), at most SHOP_SLICE_TILES tiles and
-- SHOP_SLICE_MS a call; a search not done is taken up again by the next call
-- (kept per entrance and inside map) and given up after SHOP_SCAN_MAX tiles
-- in all (that answer kept SHOP_NONE_CALLS calls, or until the inside map is
-- made again). Never a hall's
-- middle (the whole ring open), never a room with a purpose: a zone (dining,
-- temple, tavern, bedroom, hospital...), a stockpile, a farm plot, or an AI
-- level of any kind but workshops.
SHOP_SCAN_MAX = 120000      -- tiles looked at in all, over every slice (was 250000 in one call)
SHOP_SLICE_TILES = 15000    -- tiles looked at in one call at most
SHOP_SLICE_MS = 40          -- milliseconds of one call at most
SHOP_NONE_CALLS = 30        -- a search that found nothing is not made again for this many calls
SHOP_FREE_KINDS = {workshops = true}   -- AI levels a siege workshop may stand in

local RING = {}
do
    for dx = -3, 3 do table.insert(RING, {dx, -3}) end
    for dy = -2, 3 do table.insert(RING, {3, dy}) end
    for dx = 2, -3, -1 do table.insert(RING, {dx, 3}) end
    for dy = 2, -2, -1 do table.insert(RING, {-3, dy}) end
end

local function in_box(b, x, y, z)
    return b.z == z and x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2
end

-- (Y1) What the search needs from the game, read once a call: `taken` boxes
-- (rooms with a purpose), `rooms` boxes (AI workshop levels, looked at
-- first) and `starts` (the fort's stair, its meeting hall). Tests replace it.
function shop_context()
    local taken, rooms, starts = {}, {}, {}
    pcall(function()
        local BT = df.building_type
        for _, b in ipairs(df.global.world.buildings.all) do
            local t = b:getType()
            if t == BT.Civzone or t == BT.Stockpile or t == BT.FarmPlot then
                table.insert(taken, {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z})
            end
        end
    end)
    pcall(function()
        local B = builder()
        local data = B.load_projects()
        for _, p in ipairs(data and data.list or {}) do
            local okA, areas = pcall(B.project_areas, p)
            for _, ar in ipairs(okA and areas or {}) do
                if type(ar) == 'table' and ar.x1 and ar.z then
                    table.insert(SHOP_FREE_KINDS[p.kind] and rooms or taken,
                                 {x1 = ar.x1, y1 = ar.y1, x2 = ar.x2, y2 = ar.y2, z = ar.z})
                end
            end
        end
    end)
    pcall(function()
        for _, p in ipairs(gates().fort_anchor_starts() or {}) do table.insert(starts, p) end
    end)
    return {taken = taken, rooms = rooms, starts = starts}
end

function shop_purpose_test(ctx)
    local taken = type(ctx) == 'table' and type(ctx.taken) == 'table' and ctx.taken or {}
    return function(x, y, z)
        for _, b in ipairs(taken) do
            if in_box(b, x, y, z) then return true end
        end
        return false
    end
end

local function shop_fits(e, inside, T, purpose)
    local opening = {}
    for _, k in ipairs(e.inside_list or {}) do opening[k] = true end
    local function core(x, y, z)
        local t = T(x, y, z)
        return t and inside[gkey(x, y, z)] == true and t.walk and t.shape == 'FLOOR' and not t.outside
            and not t.liquid and not t.occupied and not t.designated and not opening[gkey(x, y, z)]
            and not purpose(x, y, z) or false
    end
    return function(cx, cy, z)
        for dy = -2, 2 do
            for dx = -2, 2 do
                if not core(cx + dx, cy + dy, z) then return false end
            end
        end
        -- the ring: each tile wall (not walkable) or free floor; the free ones in one run
        local open, edge, n_open = {}, false, 0
        for i, d in ipairs(RING) do
            local x, y = cx + d[1], cy + d[2]
            local t = T(x, y, z)
            local walk = t and t.walk or false
            if walk then
                if t.occupied or t.liquid or opening[gkey(x, y, z)] then return false end
                open[i] = true
                n_open = n_open + 1
                if math.abs(d[1]) ~= 3 or math.abs(d[2]) ~= 3 then edge = true end
            end
        end
        if not edge then return false end
        if n_open == #RING then return false end      -- (Y1) a hall's middle: never
        local runs, n = 0, #RING
        for i = 1, n do
            local prev = i == 1 and n or i - 1
            if open[i] and not open[prev] then runs = runs + 1 end
        end
        return runs <= 1
    end
end

local STEPS = {{1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {1, 1, 0}, {1, -1, 0}, {-1, 1, 0}, {-1, -1, 0},
               {0, 0, 1}, {0, 0, -1}}
local function climb(t)
    local sh = t and t.shape or ''
    return sh:find('STAIR') ~= nil or sh:find('RAMP') ~= nil
end

local SHOP_SEARCH = {}      -- (Y1) the searches not done (and given up), by entrance

local function clock_ms()
    local ok, c = pcall(os.clock)
    return ok and type(c) == 'number' and c * 1000 or 0
end

-- Returns the spot, or nil (and SHOP_LAST says why: 'searching', taken up
-- again next call; 'none', nothing in the fort).
function shop_spot_anywhere(e, inside, T, ctx)
    SHOP_LAST = nil
    if ctx == nil then
        local okc, c = pcall(shop_context)
        ctx = okc and type(c) == 'table' and c or {}
    end
    local purpose = shop_purpose_test(ctx)
    local fits = shop_fits(e, inside, T, purpose)
    local sk = tostring(e.id)
    local st = SHOP_SEARCH[sk]
    if st and st.inside ~= inside then st = nil end
    if st and st.none then
        -- the fort-wide 'none' kept SHOP_NONE_CALLS calls (or until the inside map is made again)
        st.none_calls = (st.none_calls or 0) + 1
        if st.none_calls <= SHOP_NONE_CALLS then SHOP_LAST = 'none'; return nil end
        st = nil
    end
    if not st then
        st = {inside = inside, queue = {}, seen = {}, head = 1, looked = 0, rooms_done = false}
        local function seed(x, y, z)
            local k = gkey(x, y, z)
            if inside[k] == true and not st.seen[k] then st.seen[k] = true; table.insert(st.queue, k) end
        end
        for _, k in ipairs(e.inside_list or {}) do
            if inside[k] == true and not st.seen[k] then st.seen[k] = true; table.insert(st.queue, k) end
        end
        seed(e.x, e.y, e.z)
        for _, p in ipairs(type(ctx.starts) == 'table' and ctx.starts or {}) do
            if type(p) == 'table' and p.x and p.y and p.z then seed(p.x, p.y, p.z) end
        end
    end
    SHOP_SEARCH[sk] = st
    local t0, slice = clock_ms(), 0
    local function over()
        return slice >= SHOP_SLICE_TILES or st.looked >= SHOP_SCAN_MAX
            or (slice % 256 == 0 and clock_ms() - t0 > SHOP_SLICE_MS)
    end
    -- the AI's workshop levels first (their empty rooms)
    if not st.rooms_done then
        local best, best_d
        for _, r in ipairs(type(ctx.rooms) == 'table' and ctx.rooms or {}) do
            for y = r.y1 + 2, r.y2 - 2 do
                for x = r.x1 + 2, r.x2 - 2 do
                    slice, st.looked = slice + 1, st.looked + 1
                    if inside[gkey(x, y, r.z)] == true and fits(x, y, r.z) then
                        local d = math.abs(x - e.x) + math.abs(y - e.y) + 3 * math.abs(r.z - e.z)
                        if not best_d or d < best_d then best, best_d = {x = x, y = y, z = r.z}, d end
                    end
                end
            end
        end
        st.rooms_done = true
        if best then SHOP_SEARCH[sk] = nil; return best end
    end
    -- then outward over the inside, nearest by walking first
    local q, seen = st.queue, st.seen
    while st.head <= #q do
        if over() then
            if st.looked >= SHOP_SCAN_MAX then st.none = true; st.queue, st.seen = nil, nil; SHOP_LAST = 'none'; return nil end
            SHOP_LAST = 'searching'; return nil
        end
        local k = q[st.head]
        q[st.head] = false
        st.head = st.head + 1
        slice, st.looked = slice + 1, st.looked + 1
        local x, y, z = k % 4096, (k // 4096) % 4096, k // (4096 * 4096)
        if fits(x, y, z) then SHOP_SEARCH[sk] = nil; return {x = x, y = y, z = z} end
        local t = T(x, y, z)
        local climbs = climb(t)
        for _, d in ipairs(STEPS) do
            local nx, ny, nz = x + d[1], y + d[2], z + d[3]
            local nk = gkey(nx, ny, nz)
            if not seen[nk] and inside[nk] == true then
                local u = T(nx, ny, nz)
                -- up and down only by a stair or a ramp
                if u and u.walk and (d[3] == 0 or climbs or climb(u)) then
                    seen[nk] = true
                    q[#q + 1] = nk
                end
            end
        end
    end
    st.none = true
    st.queue, st.seen = nil, nil
    SHOP_LAST = 'none'; return nil
end

function place_shop(entrance_id, dry_run)
    if shop_count() > 0 then return {ok = false, rejected = true, error = 'a siege workshop stands already'} end
    local e, G = entrance_by_id(entrance_id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if not (G.GATES or {}).inside then return {ok = false, rejected = true, error = 'the fort is not mapped yet'} end
    local T = reader()
    local okc, ctx = pcall(shop_context)       -- (Y1) the rooms with a purpose, the AI's workshop levels
    ctx = okc and type(ctx) == 'table' and ctx or {}
    local sp, near = shop_spot(e, G.GATES.inside, T, ctx), true
    if not sp then
        local ok, s2 = pcall(shop_spot_anywhere, e, G.GATES.inside, T, ctx)     -- (r2h7)
        sp, near = ok and s2 or nil, false
        if not sp and ok and SHOP_LAST == 'searching' then
            return {ok = false, rejected = true, searching = true,
                    error = 'still looking for a free 5x5 room for a siege workshop (the search goes on next time)'}
        end
    end
    if not sp then
        return {ok = false, rejected = true, error = 'no free 5x5 of roofed floor in the fort for a siege workshop '
            .. '(none by the gate, no empty room or hall elsewhere)'}
    end
    local ok, fail = qf('build', {{x = sp.x, y = sp.y, text = 'ws'}}, sp.z, dry_run)
    if not ok then return {ok = false, error = ('quickfort would not place the siege workshop (%s run)'):format(tostring(fail))} end
    return {ok = true, dry_run = dry_run or nil, at = sp, entrance_id = e.id, by_gate = near or nil}
end

---------------------------------------------------------------------------
-- The field watch: hostiles near a caravan, hostile wildlife near the dwarves
---------------------------------------------------------------------------

local function is(f, u)
    local ok, v = pcall(f, u)
    return ok and v == true
end

local function unnamed(u) return '#' .. tostring(u.id) end
local function name_of(u, txt) return U.name_of(u, txt, unnamed) end   -- (r6) ai-util's, '#<id>' when unread

local function nearest(pos, list)
    local best
    for _, p in ipairs(list) do
        local d = dist(pos, p)
        if not best or d < best then best = d end
    end
    return best
end

-- (looked up once a watch: reqscript checks the file on every call)
local function wild_test()
    local okb, B = pcall(builder)
    local f = okb and B and B.hostile_wild
    return function(u)
        if not f then return false end
        local ok, v = pcall(f, u)
        return ok and v == true
    end
end

local function fire_test()
    local okt, TH = pcall(reqscript, 'ai-threats')
    local f = okt and TH and TH.fire_breath_of
    return function(u)
        if not f then return nil end
        local ok, how = pcall(f, u.race, u.caste)
        return ok and how or nil
    end
end

-- (0.105.47, I7d 2e) A wild animal at grips with a citizen: C's giant
-- coyote and E's giant chipmunks killed four fisherdwarves and planters with
-- no alarm and no squad. They are neither large predators nor "agitated", so
-- hostile_wild (and so the field watch and the hunt) never saw them. DF keeps
-- the unit a creature last went for in unit.opponent.unit_id: a wild animal
-- (not the fort's, not tame) whose last target is a citizen is listed as a
-- hostile wild one (`attacking`). Not when that citizen is out hunting it (a
-- deer turning on the hunter is the hunter's affair). `cits`: {[id] = unit}.
function wild_attacking(u, cits)
    if type(cits) ~= 'table' then return false end
    if not is(dfhack.units.isAnimal, u) or is(dfhack.units.isFortControlled, u) then return false end
    local okt, tid = pcall(function() return u.opponent.unit_id end)
    if not okt or type(tid) ~= 'number' or tid < 0 then return false end
    local c = cits[tid]
    if not c then return false end
    local okh, hunting = pcall(function()
        local j = c.job.current_job
        return j ~= nil and j.job_type == df.job_type.Hunt
    end)
    if okh and hunting then return false end
    return true
end

-- (0.105.48, K1) a wild animal DF calls a danger (agitated) that is no
-- invader, great danger, night creature or undead: wildlife, not an enemy
function wild_animal(u)
    if not is(dfhack.units.isAnimal, u) or is(dfhack.units.isFortControlled, u) then return false end
    if is(dfhack.units.isInvader, u) or is(dfhack.units.isGreatDanger, u) then return false end
    if is(dfhack.units.isNightCreature, u) or is(dfhack.units.isUndead, u) then return false end
    return true
end

function field_watch(txt)
    local out = {merchants = 0, caravan = {}, wild = {}, wild_total = 0}
    local cit_all, cit_out, groups = {}, {}, {}
    local cit_ids = {}           -- (0.105.47) for wild_attacking
    for _, u in ipairs(report_citizens(true)) do
        if not is(dfhack.units.isDead, u) then
            cit_ids[u.id] = u
            local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            table.insert(cit_all, p)
            local okd, des = pcall(dfhack.maps.getTileFlags, xyz2pos(p.x, p.y, p.z))
            if okd and des and des.outside then table.insert(cit_out, p) end
            local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(p.x, p.y, p.z))
            if okg and g and g ~= 0 then groups[g] = true end
        end
    end
    out.citizens_outside = #cit_out
    local merchants = {}
    local units = report_units()
    for _, u in ipairs(units) do
        if is(dfhack.units.isMerchant, u) and not is(dfhack.units.isDead, u) and is(dfhack.units.isActive, u) then
            table.insert(merchants, {x = u.pos.x, y = u.pos.y, z = u.pos.z})
        end
    end
    out.merchants = #merchants
    local hostile_wild, fire_of = wild_test(), fire_test()
    for _, u in ipairs(units) do
        -- (fix3) the cheap tests first: only what is near a caravan or out
        -- under the sky is looked at further (the caverns' thousands never
        -- pay the eight unit checks below)
        local pos, outside, dm
        if not (u.flags1.caged or u.flags1.chained) then
            pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            local okd, des = pcall(dfhack.maps.getTileFlags, xyz2pos(pos.x, pos.y, pos.z))
            outside = okd and des and des.outside == true or false
            dm = #merchants > 0 and nearest(pos, merchants) or nil
        end
        if pos and ((dm and dm <= CARAVAN_NEAR) or outside)
                and is(dfhack.units.isActive, u) and not is(dfhack.units.isDead, u) and not is(dfhack.units.isCitizen, u)
                and not is(dfhack.units.isMerchant, u) and not is(dfhack.units.isDiplomat, u)
                and not is(dfhack.units.isVisitor, u) and not is(dfhack.units.isTame, u) then
            do
                local danger = is(dfhack.units.isDanger, u)
                -- (0.105.48, K1) DF's isDanger is true of an agitated wild
                -- animal (War-hold's falcon), so it was never `wild` and the
                -- wildlife rule never saw it: an animal that is no invader and
                -- no great danger is wildlife here, whatever isDanger says
                if danger and wild_animal(u) then danger = false end
                local wild = not danger and hostile_wild(u)
                -- (0.105.47) or one that went for a citizen (a giant coyote);
                -- (0.105.51) a large predator at grips with one says so too
                -- (the brain's wild_pack: a lone one attacking, no squad: the alarm)
                local attacking = not danger and outside and wild_attacking(u, cit_ids)
                if attacking then wild = true end
                if danger or wild then
                    local row = {id = u.id, name = name_of(u, txt), wild = wild or nil, outside = outside,
                                 attacking = attacking or nil,
                                 invader = is(dfhack.units.isInvader, u) or nil,
                                 great = is(dfhack.units.isGreatDanger, u) or nil}
                    local how = fire_of(u)
                    if how then row.fire_breather, row.fire_how = true, how end
                    pcall(function() if u.enemy.caste_flags.FLIER then row.flier = true end end)
                    pcall(function() row.size = u.body.size_info.size_cur end)
                    local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(pos.x, pos.y, pos.z))
                    if okg and g and g ~= 0 then row.reach = groups[g] == true end
                    if dm and dm <= CARAVAN_NEAR and #out.caravan < ROWS_MAX then
                        local r = {}
                        for k, v in pairs(row) do r[k] = v end
                        r.distance = dm
                        table.insert(out.caravan, r)
                    end
                    if wild and outside then
                        local d_out, d_all = nearest(pos, cit_out), nearest(pos, cit_all)
                        if (d_out and d_out <= WILD_NEAR) or (d_all and d_all <= WILD_NEAR) then
                            out.wild_total = out.wild_total + 1
                            if #out.wild < ROWS_MAX then
                                row.distance_outside, row.distance = d_out, d_all
                                table.insert(out.wild, row)
                            end
                        end
                    end
                end
            end
        end
    end
    return out
end
