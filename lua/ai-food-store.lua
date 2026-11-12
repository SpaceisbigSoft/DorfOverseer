-- (0.105.40b, M6) The fort's food store: where its food and drink are kept,
-- and what is lost to rot. The coverage audit (12 Nov): "the AI never makes
-- sure food is stored properly: a food stockpile (prepared meals, plants,
-- drinks) set to use barrels, near the kitchen and still, inside (out of
-- vermin/sun), sized to the food; spoilage/vermin losses aren't watched."
--
-- DF keeps food best in a stockpile, in barrels or pots: food lying outside
-- a pile rots; food in a pile but not in a container is what vermin eat
-- (DF wiki, Vermin; Food). A pile takes barrels up to its max_barrels
-- (barrel_seek_num), its own setting.
--
--   report()          the `food_store` section: every stockpile that takes
--                     food (its box, tiles and tiles used, max barrels and
--                     bins, tiles open to the sky, whether it is the AI's own,
--                     its distance to the nearest kitchen or still), the
--                     kitchens and stills (each one's nearest food pile, and
--                     whether a pile would fit beside it), and the food items:
--                     lying outside a pile, in a pile out of any container,
--                     in barrels and pots, rotten.
--   food_pile(o, dry)  a food pile on free, roofed floor near a kitchen or
--                     still (on its level, within o.reach), about o.tiles
--                     tiles, its max barrels set to o.barrels; remembered as
--                     the AI's own. Refused while a food pile is near already
--                     (unless o.more: the near ones are full).
--   food_barrels(o, dry)  an AI food pile's max barrels set to o.barrels.
--
-- The AI's own piles: the ones this module placed (and the kitchen's and
-- still's feeder piles, place_feeder), and those its levels placed (a
-- project's `place` cells). Every other pile is the player's and is never
-- changed; the AI places its own beside it instead.
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/food-piles'
FOOD_SHOPS = {Kitchen = true, Still = true}
-- the item types that are food or drink (seeds go to bags, not barrels)
FOOD_TYPES = {'MEAT', 'FISH', 'FISH_RAW', 'PLANT', 'PLANT_GROWTH', 'CHEESE', 'EGG', 'DRINK', 'FOOD'}
CONTAINERS = {BARREL = true, TOOL = true}   -- a barrel, a large pot (a TOOL)
REACH = 20          -- a kitchen's or still's food pile is near within this (the room check's reach too)
REACH_MAX = 30      -- the action's reach at most
DZ_COST = 3         -- a z-level counts as this many tiles of walk (the stairs)
SIDE_MIN, SIDE_MAX = 3, 8
TILES_MAX = 64
BARRELS_MAX = 100
PILES_MAX = 40      -- piles listed in the report at most (nearest a kitchen or still first)
ITEMS_MAX = 60000   -- food items looked at a report at most
REMEMBER_MAX = 200

-- the builder (tile_info, qf_try, tile_taken, load_projects); swapped by the tests
function builder() return reqscript('ai-builder') end

local function offset()
    local ok, v = pcall(function() return df.global.world.map.region_z - 100 end)
    return ok and math.tointeger(v) or 0
end

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

-- --- the AI's own piles ----------------------------------------------------

function registry()
    local d = U.site_get(SITE_KEY, {})
    if type(d) ~= 'table' then d = {} end
    if type(d.piles) ~= 'table' then d.piles = {} end
    return d
end

-- A pile the AI placed, by its top-left corner (a building id is not kept:
-- quickfort hands back none, and the corner is the project cells' key too).
function remember(x, y, z)
    local d = registry()
    local k = key(x, y, z)
    for _, v in ipairs(d.piles) do if v == k then return true end end
    table.insert(d.piles, k)
    while #d.piles > REMEMBER_MAX do table.remove(d.piles, 1) end
    return U.site_put(SITE_KEY, d)
end

-- The corners ("x,y,z") of the piles that are the AI's own.
function own_corners()
    local out = {}
    for _, k in ipairs(registry().piles) do out[tostring(k)] = true end
    local ok, data = pcall(function() return builder().load_projects() end)
    if ok and type(data) == 'table' and type(data.list) == 'table' then
        for _, p in ipairs(data.list) do
            local a = type(p) == 'table' and (p.anchor or p.stair)
            local cells = type(p) == 'table' and type(p.cells) == 'table' and p.cells.place
            if type(a) == 'table' and type(p.z) == 'number' and type(cells) == 'table' then
                for _, c in ipairs(cells) do
                    if type(c) == 'table' and type(c.x) == 'number' and type(c.y) == 'number' then
                        out[key(a.x + c.x, a.y + c.y, p.z)] = true
                    end
                end
            end
        end
    end
    return out
end

-- --- stockpiles --------------------------------------------------------------

local function takes_food(sp)
    local ok, on = pcall(function() return sp.settings.flags.food end)
    return ok and on == true
end

function max_barrels(sp)
    local ok, v = pcall(function() return sp.storage.max_barrels end)
    if ok and type(v) == 'number' then return math.tointeger(v) or v end
    ok, v = pcall(function() return sp.max_barrels end)
    if ok and type(v) == 'number' then return math.tointeger(v) or v end
    return nil
end

local function max_bins(sp)
    local ok, v = pcall(function() return sp.storage.max_bins end)
    if ok and type(v) == 'number' then return v end
    ok, v = pcall(function() return sp.max_bins end)
    if ok and type(v) == 'number' then return v end
    return nil
end

local function set_max_barrels(sp, n)
    if pcall(function() sp.storage.max_barrels = n end) then return true end
    return pcall(function() sp.max_barrels = n end)
end

-- The tiles of a pile's box that are pile, those holding an item, and those
-- open to the sky.
local function pile_tiles(sp)
    local tiles, used, outside = 0, 0, 0
    for y = sp.y1, sp.y2 do
        for x = sp.x1, sp.x2 do
            local des, occ = dfhack.maps.getTileFlags(x, y, sp.z)
            if des and des.pile then
                tiles = tiles + 1
                if occ and occ.item then used = used + 1 end
                if des.outside then outside = outside + 1 end
            end
        end
    end
    return tiles, used, outside
end

-- The walk from one box to another, roughly: the gap across, and each
-- z-level between as DZ_COST tiles of stairs.
function box_dist(a, b)
    local gx = math.max(a.x1 - b.x2, b.x1 - a.x2, 0)
    local gy = math.max(a.y1 - b.y2, b.y1 - a.y2, 0)
    return math.max(gx, gy) + DZ_COST * math.abs(a.z - b.z)
end

local function box_of(b)
    return {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z}
end

-- The kitchens and stills, built.
function food_shops()
    local out = {}
    local ok, list = pcall(function() return df.global.world.buildings.other.WORKSHOP_ANY end)
    if not ok or not list then return out end
    for _, b in ipairs(list) do
        local okk, kind = pcall(function() return df.workshop_type[b.type] end)
        local built = true
        pcall(function() built = b:getBuildStage() >= b:getMaxBuildStage() end)
        if okk and FOOD_SHOPS[kind] and built then
            table.insert(out, {b = b, kind = kind})
        end
    end
    return out
end

function food_piles()
    local out = {}
    local ok, list = pcall(function() return df.global.world.buildings.other.STOCKPILE end)
    if not ok or not list then return out end
    for _, sp in ipairs(list) do
        if takes_food(sp) then table.insert(out, sp) end
    end
    return out
end

-- The nearest food pile to a box: the pile and its distance, or nil.
local function nearest_pile(piles, box)
    local best, bd = nil, nil
    for _, sp in ipairs(piles) do
        local d = box_dist(box_of(sp), box)
        if not bd or d < bd then best, bd = sp, d end
    end
    return best, bd
end

-- --- where a new pile goes ------------------------------------------------------

-- Free, roofed floor: no building, zone, pile, dig, liquid; seen; not open to the sky.
local function free_inside(B, x, y, z)
    local t = B.tile_info(x, y, z)
    if not t or t.hidden or t.liquid or t.building or t.designated or t.marked or t.outside then return false end
    if t.shape ~= 'FLOOR' then return false end
    local okp, pile = pcall(function()
        local des = dfhack.maps.getTileFlags(x, y, z)
        return des.pile
    end)
    return not (okp and pile)
end

-- The nearest w x h of free roofed floor 2..reach tiles from the box (never
-- touching it), on its level, whose tiles hold no zone either.
function inside_rect(box, w, h, reach)
    local B = builder()
    local z = box.z
    for d = 2, reach do
        for ry = box.y1 - d - h + 1, box.y2 + d do
            for rx = box.x1 - d - w + 1, box.x2 + d do
                local gx = math.max(box.x1 - (rx + w - 1), rx - box.x2, 0)
                local gy = math.max(box.y1 - (ry + h - 1), ry - box.y2, 0)
                if math.max(gx, gy) == d then
                    local ok = true
                    for yy = ry, ry + h - 1 do
                        for xx = rx, rx + w - 1 do
                            if not free_inside(B, xx, yy, z) then ok = false break end
                        end
                        if not ok then break end
                    end
                    if ok and B.tile_taken then
                        for yy = ry, ry + h - 1 do
                            for xx = rx, rx + w - 1 do
                                local okt, taken = pcall(B.tile_taken, xx, yy, z)
                                if okt and taken then ok = false break end
                            end
                            if not ok then break end
                        end
                    end
                    if ok then return {x = rx, y = ry, z = z, w = w, h = h} end
                end
            end
        end
    end
    return nil
end

-- The sides tried for about `tiles` tiles: the square that holds them, then smaller.
local function sides_for(tiles)
    local side = math.max(SIDE_MIN, math.min(SIDE_MAX, math.ceil(math.sqrt(tiles))))
    local out = {}
    for s = side, SIDE_MIN, -1 do
        table.insert(out, {s, s})
        if s > SIDE_MIN then table.insert(out, {s, s - 1}) end
    end
    return out
end

-- --- the report ----------------------------------------------------------------------

local function container_kind(it)
    local ok, c = pcall(dfhack.items.getContainer, it)
    if not ok or not c then return nil end
    return U.item_kind(c)
end

function item_counts()
    local out = {loose = 0, exposed = 0, in_containers = 0, rotten = 0, total = 0}
    local seen = 0
    local other = df.global.world.items.other
    for _, tname in ipairs(FOOD_TYPES) do
        local okl, list = pcall(function() return other[tname] end)
        if okl and list then
            for _, it in ipairs(list) do
                seen = seen + 1
                if seen > ITEMS_MAX then out.capped = true break end
                local f = it.flags
                if not (f.removed or f.garbage_collect) then
                    out.total = out.total + 1
                    if f.rotten then out.rotten = out.rotten + 1 end
                    if f.in_inventory then
                        if CONTAINERS[container_kind(it) or ''] then out.in_containers = out.in_containers + 1 end
                    elseif f.on_ground and not f.in_building and not f.in_job and not f.forbid then
                        local x, y, z = U.item_pos(it)
                        local des = x and dfhack.maps.getTileFlags(x, y, z)
                        if des and des.pile then out.exposed = out.exposed + 1
                        elseif des then out.loose = out.loose + 1 end
                    end
                end
            end
        end
        if out.capped then break end
    end
    return out
end

function report()
    local off = offset()
    local own = own_corners()
    local piles, shops = food_piles(), food_shops()
    local rows = {}
    for _, sp in ipairs(piles) do
        local tiles, used, outside = pile_tiles(sp)
        local best, bd = nil, nil
        for _, s in ipairs(shops) do
            local d = box_dist(box_of(sp), box_of(s.b))
            if not bd or d < bd then best, bd = s, d end
        end
        table.insert(rows, {id = sp.id, x1 = sp.x1, y1 = sp.y1, x2 = sp.x2, y2 = sp.y2, z = sp.z,
                            elevation = sp.z + off, tiles = tiles, used = used, outside = outside,
                            barrels = max_barrels(sp), bins = max_bins(sp),
                            ai = own[key(sp.x1, sp.y1, sp.z)] == true,
                            dist = bd, shop = best and best.kind or nil, shop_id = best and best.b.id or nil})
    end
    table.sort(rows, function(a, b)
        local da, db = a.dist or 1e9, b.dist or 1e9
        if da ~= db then return da < db end
        return a.id < b.id
    end)
    while #rows > PILES_MAX do table.remove(rows) end
    local srows = {}
    for _, s in ipairs(shops) do
        local b = s.b
        local p, d = nearest_pile(piles, box_of(b))
        local row = {id = b.id, kind = s.kind, x = b.centerx, y = b.centery, z = b.z, elevation = b.z + off,
                     x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, pile = p and p.id or nil, dist = d}
        if not d or d > REACH then
            local okr, r = pcall(inside_rect, box_of(b), SIDE_MIN, SIDE_MIN, REACH)
            row.room = (okr and r ~= nil) and true or false
        end
        table.insert(srows, row)
    end
    return {piles = rows, shops = srows, items = item_counts(), reach = REACH, piles_total = #piles}
end

-- --- the actions -------------------------------------------------------------------

local function clamp(v, lo, hi, default)
    local n = math.tointeger(tonumber(v))
    if not n then return default end
    return math.max(lo, math.min(hi, n))
end

local function shop_of(id)
    local b = df.building.find(id)
    if not b then return nil end
    for _, s in ipairs(food_shops()) do
        if s.b.id == b.id then return s end
    end
    return nil
end

local function pile_at(x, y, z)
    for _, sp in ipairs(food_piles()) do
        if sp.z == z and sp.x1 == x and sp.y1 == y then return sp end
    end
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if ok and b and takes_food(b) then return b end
    return nil
end

function food_pile(o, dry_run)
    local s = shop_of(o.building_id)
    if not s then return {ok = false, rejected = true, error = 'not a kitchen or still'} end
    local box = box_of(s.b)
    local reach = clamp(o.reach, 4, REACH_MAX, REACH)
    local tiles = clamp(o.tiles, SIDE_MIN * SIDE_MIN, TILES_MAX, 9)
    local p, d = nearest_pile(food_piles(), box)
    if p and d <= reach and not o.more then
        return {ok = false, rejected = true, stale = {'food_store'},
                error = ('the %s already has a food pile %d tiles away'):format(s.kind, d)}
    end
    local r
    for _, wh in ipairs(sides_for(tiles)) do
        r = inside_rect(box, wh[1], wh[2], reach)
        if r then break end
    end
    if not r then
        return {ok = false, room = false,
                error = ('no free roofed floor within %d tiles of the %s for a food pile'):format(reach, s.kind)}
    end
    local B = builder()
    local cell = {{x = 0, y = 0, text = ('f(%dx%d)'):format(r.w, r.h)}}
    local good, failed = B.qf_try('place', cell, r.z, r.x, r.y, dry_run)
    if failed == 'dry' then
        return {ok = false, error = ('the game would not place a stockpile at x%d y%d'):format(r.x, r.y)}
    elseif not good then
        return {ok = false, error = ('the game refused the stockpile at x%d y%d'):format(r.x, r.y)}
    end
    local barrels = clamp(o.barrels, 0, math.min(BARRELS_MAX, r.w * r.h), r.w * r.h)
    local out = {ok = true, kind = s.kind, x = r.x, y = r.y, elevation = r.z + offset(), w = r.w, h = r.h,
                 tiles = r.w * r.h, barrels = barrels, more = o.more and true or nil, dry_run = dry_run or nil}
    if dry_run then return out end
    remember(r.x, r.y, r.z)
    local sp = pile_at(r.x, r.y, r.z)
    if sp then
        out.pile_id = sp.id
        if not set_max_barrels(sp, barrels) then out.warning = 'the max barrels could not be set' end
    else
        out.warning = 'the new pile was not found to set its barrels (the next look does)'
    end
    return out
end

function food_barrels(o, dry_run)
    local id = math.tointeger(tonumber(o.pile_id))
    local sp = id and df.building.find(id)
    if not sp or not takes_food(sp) then
        return {ok = false, rejected = true, stale = {'food_store'}, error = 'no food stockpile with that id'}
    end
    if not own_corners()[key(sp.x1, sp.y1, sp.z)] then
        return {ok = false, rejected = true, error = 'that food pile is the player\'s: the AI leaves it as it is'}
    end
    local tiles = pile_tiles(sp)
    local n = clamp(o.barrels, 0, math.min(BARRELS_MAX, math.max(tiles, 1)), tiles)
    local had = max_barrels(sp)
    if had == n then
        return {ok = false, rejected = true, stale = {'food_store'}, error = ('it takes %d barrels already'):format(n)}
    end
    local out = {ok = true, pile_id = sp.id, barrels = n, had = had, dry_run = dry_run or nil}
    if dry_run then return out end
    if not set_max_barrels(sp, n) then return {ok = false, error = 'the game would not take the max barrels'} end
    return out
end
