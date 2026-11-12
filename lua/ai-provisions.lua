-- (0.105.41, item 4) Provisions from the land: hunting, butchery and
-- tanning, fruit picked from trees, meals of more than one kind, and farms
-- on cavern soil. The coverage audit's "should" list (12 Nov): the AI never
-- sent a hunter out, left kills and hides to chance, never picked a tree,
-- cooked one kind of meal, and never farmed a cavern's soil.
--
--   report()           the `provisions` section:
--     hunting   game on the surface (wild animals that are no danger),
--               dangerous wild ones up there, the hunters (citizens outside
--               the squads with the labour), the AI's own, the detail
--     butchery  DF's standing orders on butchering, tanning and cooking (as
--               0/1), the unbutchered bodies a butcher could take (and those
--               forbidden), the raw hides a tanner could take, the citizens
--               with each labour, the orders the AI set itself
--     fruit     the fruit trees near the fort (a growth to eat or brew; weekly
--               scan), the fruit-gathering zones and the AI's own
--     meals     servings by kind (biscuits, stew, roast) and in all
--     cavern    the AI's farm plots on cavern soil (plots, tiles)
--   hunters(o, dry)    o.count: up to that many more hunters through the game's
--                      work detail (ai-labor assign), remembered as the AI's;
--                      o.stop: the AI's own hunters taken off it (danger)
--   food_standing(o, dry)  o.orders {name = 0|1}: DF's standing orders on
--                      butchering, tanning and cooking (only those), each one
--                      the AI set remembered; one it set that is off again
--                      (the player) is never set again
--   fruit_zone(o, dry) a fruit-gathering zone over the densest stand of fruit
--                      trees near the fort (quickfort 'g', dry run first)
--   cavern_farm(o, dry)  farm plots on soil floor in a known cavern, near
--                      o.at (where the dwarves' ground meets it), walkable
--                      from there, no danger near; quickfort 'p', dry run first
--
-- Never the player's own: only the AI's hunters are taken off, only the AI's
-- zones and plots counted as its own; the player's details set to everybody
-- or nobody are left as they are (ai-labor refuses them).
--@ module = true

local U = reqscript('ai-util')

HUNTERS_KEY = 'ai-overseer/hunters'          -- {ids = {unit ids the AI made hunters}}
STANDING_KEY = 'ai-overseer/food-standing'   -- {name = 1}: the standing orders the AI turned on
FRUIT_KEY = 'ai-overseer/fruit-zones'        -- {{x, y, z, w, h}}
CAVERN_KEY = 'ai-overseer/cavern-farms'      -- {{x, y, z, w, h}}

-- the standing orders this module may set (df.global.standing_orders_<name>)
FOOD_STANDING = {'auto_butcher', 'auto_tan', 'auto_kitchen', 'auto_fishery'}
-- and reads (the kills' fate: forbidden unless hunted)
FOOD_STANDING_READ = {'auto_butcher', 'auto_tan', 'auto_kitchen', 'auto_fishery', 'auto_slaughter',
                      'forbid_other_nohunt', 'forbid_other_dead_items'}
MEAL_KINDS = {ITEM_FOOD_BISCUITS = 'biscuits', ITEM_FOOD_STEW = 'stew', ITEM_FOOD_ROAST = 'roast'}

FRUIT_RADIUS = 45            -- trees this far (across) from the fort's centre
FRUIT_LEVELS = 8             -- and this many levels up or down
FRUIT_SCAN_TICKS = 7 * 1200  -- the trees counted once a game week
FRUIT_ZONE_SIDE = 21         -- a zone at most this wide
FRUIT_ZONE_MIN = 3
FRUIT_STAND = 8              -- trees this close (across) to the best one form its stand
FRUIT_PLANTS_MAX = 20000     -- plants looked at a scan at most
FRUIT_CACHE = FRUIT_CACHE    -- kept across reloads within a session

CAVERN_RADIUS = 25           -- soil this far (across) from where the fort meets the cavern
CAVERN_LEVELS = 2            -- and this many levels up or down
CAVERN_DANGER = 30           -- no plot with a danger this close
CAVERN_SIDE_MAX, CAVERN_SIDE_MIN = 6, 2
CAVERN_TILES_MAX = 60
FARM_GRASS = {SOIL = true, GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true, GRASS_DEAD = true}

-- the builder and the labour module; swapped by the tests
function builder() return reqscript('ai-builder') end
function labor() return reqscript('ai-labor') end

local function enum(e, k) if e == nil or k == nil then return nil end return e[k] end
local function now_tick() local ok, t = pcall(U.abs_tick); return ok and t or nil end
local function txt_of(txt) return txt or function(s) return s end end

local function units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end

local function citizens()
    if U.REPORT_CTX and U.citizens then return U.citizens(true) end
    return dfhack.units.getCitizens(true)
end

local function items_of(kind)
    local ok, l = pcall(function() return df.global.world.items.other[kind] end)
    return ok and l or {}
end

local function in_squad(u)
    local ok, v = pcall(function() return u.military.squad_id >= 0 end)
    return ok and v
end

local function grown(u)
    local ok, v = pcall(function() return not (dfhack.units.isChild(u) or dfhack.units.isBaby(u)) end)
    return not ok or v
end

local function has_labor(u, l)
    local ok, v = pcall(function() return u.status.labors[l] end)
    return ok and v == true
end

local function tile_outside(x, y, z)
    local d = dfhack.maps.getTileFlags(x, y, z)
    return d ~= nil and d.outside == true
end

-- --- the hunting -----------------------------------------------------------------------

-- A wild animal on the surface: 'game' (no danger), 'danger' (a danger), or nil.
function wild_kind(u)
    local ok, kind = pcall(function()
        local Un = dfhack.units
        if Un.isDead(u) or not Un.isActive(u) then return nil end
        if u.flags1.caged or u.flags1.chained then return nil end
        if not Un.isAnimal(u) or Un.isFortControlled(u) then return nil end
        local okt, tame = pcall(Un.isTame, u)
        if okt and tame then return nil end
        if not tile_outside(u.pos.x, u.pos.y, u.pos.z) then return nil end      -- not in a cavern
        if Un.isDanger(u) or (Un.isGreatDanger and Un.isGreatDanger(u)) then return 'danger' end
        return 'game'
    end)
    return ok and kind or nil
end

function ai_hunter_ids()
    local d = U.site_get(HUNTERS_KEY, {})
    return type(d.ids) == 'table' and d.ids or {}
end

local function hunting_report()
    local out = {game = 0, danger = 0, hunters = 0, ai_hunters = 0}
    for _, u in ipairs(units()) do
        local k = wild_kind(u)
        if k then out[k] = out[k] + 1 end
    end
    local HUNT = enum(df.unit_labor, 'HUNT')
    local mine = {}
    for _, id in ipairs(ai_hunter_ids()) do mine[id] = true end
    for _, u in ipairs(citizens()) do
        if HUNT and grown(u) and not in_squad(u) and has_labor(u, HUNT) then
            out.hunters = out.hunters + 1
            if mine[u.id] then out.ai_hunters = out.ai_hunters + 1 end
        end
    end
    pcall(function()
        local wd, mode = labor().detail_for('HUNT')
        out.detail = wd and tostring(wd.name) or nil
        out.mode = mode
    end)
    return out
end

local function recompute(u)
    if dfhack.units.setAutomaticProfessions then return pcall(dfhack.units.setAutomaticProfessions, u) end
    return false
end

-- More hunters (o.count), or the AI's own taken off (o.stop).
function hunters(o, dry_run, txt)
    o = o or {}
    local HUNT = enum(df.unit_labor, 'HUNT')
    if not HUNT then return {ok = false, error = 'no HUNT labour in this DF'} end
    if o.stop then return stop_hunting(dry_run, txt) end
    local n = math.tointeger(tonumber(o.count)) or 0
    if n < 1 or n > 5 then return {ok = false, rejected = true, error = 'hunters needs count 1-5 (or stop)'} end
    local before = {}
    for _, u in ipairs(citizens()) do if has_labor(u, HUNT) then before[u.id] = true end end
    local r = labor().assign('HUNT', n, dry_run, txt)
    if dry_run or type(r) ~= 'table' or not r.ok then return r end
    local d = U.site_get(HUNTERS_KEY, {})
    local ids = type(d.ids) == 'table' and d.ids or {}
    local seen = {}
    for _, id in ipairs(ids) do seen[id] = true end
    local added = {}
    for _, u in ipairs(citizens()) do
        if has_labor(u, HUNT) and not before[u.id] and not seen[u.id] then
            table.insert(ids, u.id)
            table.insert(added, u.id)
        end
    end
    U.site_put(HUNTERS_KEY, {ids = ids})
    r.ai_hunters = #ids
    r.added_ids = added
    return r
end

-- The AI's hunters off the hunting: out of the detail (an "only selected"
-- one; else the labour itself, when no detail carries it), their hunt
-- dropped. The player's hunters are never touched.
function stop_hunting(dry_run, txt)
    local HUNT = enum(df.unit_labor, 'HUNT')
    local ids = ai_hunter_ids()
    if #ids == 0 then return {ok = false, rejected = true, error = 'the AI has no hunters of its own'} end
    local wd, mode
    pcall(function() wd, mode = labor().detail_for('HUNT') end)
    if wd and mode ~= 'OnlySelectedDoesThis' then
        U.site_put(HUNTERS_KEY, {ids = {}})
        return {ok = false, rejected = true,
                error = ('the %s work detail is %s now (yours): its hunters left as they are'):format(tostring(wd.name), tostring(mode))}
    end
    local names, off = {}, 0
    local T = txt_of(txt)
    for _, id in ipairs(ids) do
        local u = df.unit.find(id)
        if u then
            table.insert(names, T(dfhack.units.getReadableName(u)))
            if not dry_run then
                if wd then
                    local vec = wd.assigned_units
                    for i = #vec - 1, 0, -1 do if vec[i] == id then vec:erase(i) end end
                    if not recompute(u) then u.status.labors[HUNT] = false end
                else
                    u.status.labors[HUNT] = false
                end
                -- (needs an in-game look) the hunt under way dropped
                pcall(function()
                    local j = u.job.current_job
                    if j and df.job_type[j.job_type] == 'Hunt' and dfhack.job.removeWorker then
                        dfhack.job.removeWorker(j, 0)
                    end
                end)
                off = off + 1
            end
        end
    end
    if dry_run then return {ok = true, dry_run = true, hunters = names} end
    U.site_put(HUNTERS_KEY, {ids = {}})
    return {ok = true, stopped = off, hunters = names}
end

-- --- butchery, tanning, cooking --------------------------------------------------------

local function read_standing(name)
    local ok, v = pcall(function() return df.global['standing_orders_' .. name] end)
    if not ok or v == nil then return nil end
    if type(v) == 'boolean' then return v and 1 or 0 end
    if type(v) == 'number' then return v ~= 0 and 1 or 0 end
    return nil
end

local function has_product(mat, id)
    local found = false
    pcall(function()
        for _, p in ipairs(mat.reaction_product.id) do
            local v = type(p) == 'string' and p or p.value
            if v == id then found = true end
        end
    end)
    return found
end

-- A creature that speaks (a sapient's body is never butchered).
local SAPIENT = {}
local function sapient(race)
    if race == nil then return true end
    if SAPIENT[race] == nil then
        local ok, v = pcall(function()
            local cr = df.creature_raw.find(race)
            for _, c in ipairs(cr.caste) do
                if c.flags.CAN_SPEAK or c.flags.CAN_LEARN then return true end
            end
            return false
        end)
        SAPIENT[race] = not ok or v == true
    end
    return SAPIENT[race]
end

local function butchery_report()
    local out = {standing = {}, corpses = 0, corpses_forbidden = 0, hides = 0, butchers = 0, tanners = 0,
                 ai_set = U.site_get(STANDING_KEY, {})}
    for _, name in ipairs(FOOD_STANDING_READ) do out.standing[name] = read_standing(name) end
    for _, it in ipairs(items_of('CORPSE')) do
        pcall(function()
            local f = it.flags
            if f.removed or f.garbage_collect or f.rotten or f.trader or f.in_job then return end
            if not it.corpse_flags.unbutchered then return end
            if sapient(it.race) then return end
            if f.forbid then out.corpses_forbidden = out.corpses_forbidden + 1
            else out.corpses = out.corpses + 1 end
        end)
    end
    for _, it in ipairs(items_of('CORPSEPIECE')) do
        pcall(function()
            local f = it.flags
            if f.removed or f.garbage_collect or f.rotten or f.forbid or f.trader or f.in_job or f.dump then return end
            local mi = dfhack.matinfo.decode(it)
            if mi and mi.material and has_product(mi.material, 'TAN_MAT') then out.hides = out.hides + 1 end
        end)
    end
    local B, T = enum(df.unit_labor, 'BUTCHER'), enum(df.unit_labor, 'TANNER')
    for _, u in ipairs(citizens()) do
        if grown(u) and not in_squad(u) then
            if B and has_labor(u, B) then out.butchers = out.butchers + 1 end
            if T and has_labor(u, T) then out.tanners = out.tanners + 1 end
        end
    end
    return out
end

-- DF's standing orders on butchering, tanning and cooking.
function food_standing(o, dry_run)
    local orders = type(o) == 'table' and (o.orders or o) or nil
    if type(orders) ~= 'table' then return {ok = false, rejected = true, error = 'food_standing needs orders {name = 0|1}'} end
    local allowed = {}
    for _, n in ipairs(FOOD_STANDING) do allowed[n] = true end
    local ai = U.site_get(STANDING_KEY, {})
    local changed, plan = {}, {}
    for name, v in pairs(orders) do
        name = tostring(name):gsub('^standing_orders_', '')
        if not allowed[name] then
            return {ok = false, rejected = true, error = 'food_standing: not a butchering, tanning or cooking order: ' .. name}
        end
        v = math.tointeger(tonumber(v))
        if v ~= 0 and v ~= 1 then return {ok = false, rejected = true, error = 'food_standing: ' .. name .. ' must be 0 or 1'} end
        local cur = read_standing(name)
        if cur == nil then return {ok = false, rejected = true, error = 'food_standing: the game has no order ' .. name} end
        if v == 1 and cur == 0 and ai[name] == 1 then
            return {ok = false, rejected = true,
                    error = ('food_standing: %s was turned on by the AI and off again since (yours): left off'):format(name)}
        end
        if cur ~= v then plan[name] = v end
    end
    if next(plan) == nil then return {ok = false, rejected = true, error = 'food_standing: already so'} end
    if dry_run then return {ok = true, dry_run = true, orders = plan} end
    for name, v in pairs(plan) do
        local ok = pcall(function()
            local old = df.global['standing_orders_' .. name]
            if type(old) == 'boolean' then df.global['standing_orders_' .. name] = v == 1
            else df.global['standing_orders_' .. name] = v end
        end)
        if ok then
            changed[name] = v
            ai[name] = v == 1 and 1 or nil
        end
    end
    U.site_put(STANDING_KEY, ai)
    if next(changed) == nil then return {ok = false, error = 'the game would not take the standing orders'} end
    return {ok = true, orders = changed}
end

local function meals_report()
    local out = {by_kind = {biscuits = 0, stew = 0, roast = 0}, servings = 0}
    for _, it in ipairs(items_of('FOOD')) do
        pcall(function()
            local f = it.flags
            if f.removed or f.garbage_collect or f.rotten or f.trader then return end
            local n = it:getStackSize()
            out.servings = out.servings + n
            local okk, id = pcall(function() return it.subtype.id end)
            local k = okk and MEAL_KINDS[id] or nil
            if k then out.by_kind[k] = out.by_kind[k] + n end
        end)
    end
    return out
end

-- --- fruit trees ------------------------------------------------------------------------

-- Does a plant raw bear a growth to eat or brew? true / false (nil: unread).
local FRUITFUL = {}
function fruitful(raw)
    local ok, v = pcall(function()
        if not raw.flags.TREE then return false end
        for _, g in ipairs(raw.growths) do
            local m = raw.material[g.mat_index]
            if m and (m.flags.EDIBLE_RAW or m.flags.EDIBLE_COOKED or has_product(m, 'DRINK_MAT')) then return true end
        end
        return false
    end)
    if not ok then return nil end
    return v
end

local function plant_raw(idx)
    local ok, r = pcall(function() return df.global.world.raws.plants.all[idx] end)
    return ok and r or nil
end

-- The fruit trees near the fort: {{x, y, z}...} (the trunk's base), at most `limit`.
function fruit_trees(c, limit)
    local out = {}
    if not c then return out end
    local ok, all = pcall(function() return df.global.world.plants.all end)
    if not ok or not all then return out end
    local seen = 0
    for _, p in ipairs(all) do
        seen = seen + 1
        if seen > FRUIT_PLANTS_MAX or #out >= (limit or 2000) then break end
        pcall(function()
            local pos = p.pos
            if math.abs(pos.x - c.x) > FRUIT_RADIUS or math.abs(pos.y - c.y) > FRUIT_RADIUS
                    or math.abs(pos.z - c.z) > FRUIT_LEVELS then return end
            local idx = p.material
            if FRUITFUL[idx] == nil then
                local raw = plant_raw(idx)
                FRUITFUL[idx] = raw and fruitful(raw) or false
            end
            if FRUITFUL[idx] and tile_outside(pos.x, pos.y, pos.z) then
                table.insert(out, {x = pos.x, y = pos.y, z = pos.z})
            end
        end)
    end
    return out
end

local function zone_list()
    local out = {}
    pcall(function()
        local CIV = df.building_type.Civzone
        for _, b in ipairs(df.global.world.buildings.all) do
            local okz, t = pcall(function()
                if b:getType() ~= CIV then return nil end
                return df.civzone_type[b.type]
            end)
            if okz and t == 'PlantGathering' then table.insert(out, b) end
        end
    end)
    return out
end

local function remembered(key)
    local l = U.site_get(key, {})
    return type(l) == 'table' and l or {}
end

-- The remembered places still standing: a zone (or plot) found at each corner.
local function standing(key, check)
    local out = {}
    for _, r in ipairs(remembered(key)) do
        if type(r) == 'table' and r.x and check(r) then
            table.insert(out, r)
        end
    end
    return out
end

local function zone_at(x, y, z)
    for _, b in ipairs(zone_list()) do
        local ok, inside = pcall(function()
            return b.z == z and x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2
        end)
        if ok and inside then return b end
    end
    return nil
end

local function centre()
    local ok, c = pcall(function() return builder().found_center() end)
    return ok and c or nil
end

local function fruit_report()
    local out = {zones = #zone_list()}
    out.ai_zones = #standing(FRUIT_KEY, function(r) return zone_at(r.x, r.y, r.z) ~= nil end)
    local c = centre()
    local now = now_tick()
    local where = c and ((c.x // 20) .. ',' .. (c.y // 20) .. ',' .. c.z) or '-'
    local fc = FRUIT_CACHE
    if fc and now and fc.where == where and now >= fc.at and now - fc.at < FRUIT_SCAN_TICKS then
        out.trees = fc.trees
    else
        out.trees = #fruit_trees(c, 2000)
        FRUIT_CACHE = now and {at = now, where = where, trees = out.trees} or nil
    end
    return out
end

-- Pure: the densest stand among `trees` ({x, y, z}): its box {x1, y1, x2,
-- y2, z} (no wider than `side`, at least `min_side`) and how many trees.
function best_stand(trees, reach, side, min_side)
    local best, bn = nil, 0
    for _, t in ipairs(trees) do
        local n = 0
        for _, o in ipairs(trees) do
            if o.z == t.z and math.abs(o.x - t.x) <= reach and math.abs(o.y - t.y) <= reach then n = n + 1 end
        end
        if n > bn or (n == bn and best and (t.x < best.x or (t.x == best.x and t.y < best.y))) then
            best, bn = t, n
        end
    end
    if not best then return nil, 0 end
    local x1, y1, x2, y2 = best.x, best.y, best.x, best.y
    for _, o in ipairs(trees) do
        if o.z == best.z and math.abs(o.x - best.x) <= reach and math.abs(o.y - best.y) <= reach then
            x1, y1 = math.min(x1, o.x), math.min(y1, o.y)
            x2, y2 = math.max(x2, o.x), math.max(y2, o.y)
        end
    end
    -- a tile round the trees, then clamped about the best tree
    x1, y1, x2, y2 = x1 - 1, y1 - 1, x2 + 1, y2 + 1
    local function fit(a, b, mid)
        if b - a + 1 > side then a = math.max(a, mid - side // 2); b = a + side - 1 end
        if b - a + 1 < min_side then b = a + min_side - 1 end
        return a, b
    end
    x1, x2 = fit(x1, x2, best.x)
    y1, y2 = fit(y1, y2, best.y)
    return {x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = best.z}, bn
end

function fruit_zone(o, dry_run)
    o = o or {}
    local c = centre()
    if not c then return {ok = false, error = 'no fort centre (no wagon and no citizens on the map)'} end
    local trees = fruit_trees(c, 2000)
    if #trees == 0 then
        return {ok = false, rejected = true, error = ('no fruit trees within %d tiles of %s'):format(FRUIT_RADIUS, c.what or 'the fort')}
    end
    -- trees already in a fruit zone (anyone's) don't count
    local free = {}
    for _, t in ipairs(trees) do if not zone_at(t.x, t.y, t.z) then table.insert(free, t) end end
    local box, n = best_stand(free, FRUIT_STAND, FRUIT_ZONE_SIDE, FRUIT_ZONE_MIN)
    local least = math.tointeger(tonumber(o.min_trees)) or 3
    if not box or n < least then
        return {ok = false, rejected = true,
                error = ('no stand of %d fruit trees outside a fruit zone (best %d of %d near)'):format(least, n, #trees)}
    end
    local w, h = box.x2 - box.x1 + 1, box.y2 - box.y1 + 1
    local cell = {{x = 0, y = 0, text = ('g(%dx%d)'):format(w, h)}}
    local good, failed = builder().qf_try('zone', cell, box.z, box.x1, box.y1, dry_run)
    if not good then
        return {ok = false, error = ('quickfort refused the fruit zone (%s run) at x%d y%d z%d'):format(
            tostring(failed), box.x1, box.y1, box.z), trees = n}
    end
    local out = {ok = true, dry_run = dry_run or nil, x = box.x1, y = box.y1, z = box.z, w = w, h = h, trees = n}
    if dry_run then return out end
    local l = remembered(FRUIT_KEY)
    table.insert(l, {x = box.x1, y = box.y1, z = box.z, w = w, h = h})
    while #l > 20 do table.remove(l, 1) end
    U.site_put(FRUIT_KEY, l)
    return out
end

-- --- cavern soil farms -----------------------------------------------------------------

local function plot_at(x, y, z)
    local ok, b = pcall(function() return dfhack.buildings.findAtTile(xyz2pos(x, y, z)) end)
    if not ok or not b then return false end
    local okt, t = pcall(function() return df.building_type[b:getType()] end)
    return okt and t == 'FarmPlot'
end

local function cavern_report()
    local list = standing(CAVERN_KEY, function(r) return plot_at(r.x, r.y, r.z) end)
    local tiles = 0
    for _, r in ipairs(list) do tiles = tiles + (r.w or 0) * (r.h or 0) end
    return {plots = #list, tiles = tiles}
end

-- A tile a cavern plot may take: soil (or cave moss) floor in a cavern, seen,
-- dry, free, in the walk group `g`.
local function cavern_soil(B, x, y, z, g)
    local t = B.tile_info(x, y, z)
    if not t or t.shape ~= 'FLOOR' or not FARM_GRASS[t.material or ''] then return false end
    if not t.feature_global or t.hidden or t.liquid or t.building or t.designated or t.outside then return false end
    if B.walk_group(x, y, z) ~= g then return false end
    return not B.tile_taken(x, y, z)
end

-- Pure-ish: rectangles of good tiles (good(x, y, z) -> bool) in the box
-- around `at`, nearest first, adding up to about `want` tiles.
function cavern_spots(good, at, want, radius, levels, side_max, side_min)
    local used = {}
    local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
    local function ok(x, y, z) return not used[key(x, y, z)] and good(x, y, z) end
    local starts = {}
    for z = at.z - levels, at.z + levels do
        for y = at.y - radius, at.y + radius do
            for x = at.x - radius, at.x + radius do
                table.insert(starts, {x = x, y = y, z = z,
                                      d = math.abs(x - at.x) + math.abs(y - at.y) + 3 * math.abs(z - at.z)})
            end
        end
    end
    table.sort(starts, function(a, b)
        if a.d ~= b.d then return a.d < b.d end
        if a.z ~= b.z then return a.z < b.z end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    local spots, total = {}, 0
    for _, s in ipairs(starts) do
        if total >= want then break end
        local x, y, z = s.x, s.y, s.z
        if ok(x, y, z) then
            local w = 1
            while w < side_max and ok(x + w, y, z) do w = w + 1 end
            local h = 1
            while h < side_max do
                local row = true
                for dx = 0, w - 1 do if not ok(x + dx, y + h, z) then row = false break end end
                if not row then break end
                h = h + 1
            end
            h = math.max(side_min, math.min(h, math.ceil((want - total) / w)))
            local fits = w >= side_min and h >= side_min
            for dy = 0, h - 1 do
                for dx = 0, w - 1 do if fits and not ok(x + dx, y + dy, z) then fits = false end end
            end
            if fits then
                for dy = 0, h - 1 do for dx = 0, w - 1 do used[key(x + dx, y + dy, z)] = true end end
                table.insert(spots, {x = x, y = y, z = z, w = w, h = h})
                total = total + w * h
            end
        end
    end
    return spots, total
end

function cavern_farm(o, dry_run)
    o = o or {}
    local at = type(o.at) == 'table' and o.at or nil
    local ax, ay, az = at and math.tointeger(tonumber(at.x)), at and math.tointeger(tonumber(at.y)),
                       at and math.tointeger(tonumber(at.z))
    if not (ax and ay and az) then return {ok = false, rejected = true, error = 'cavern_farm needs at {x, y, z}'} end
    local want = math.tointeger(tonumber(o.tiles)) or 0
    if want < 4 or want > CAVERN_TILES_MAX then
        return {ok = false, rejected = true, error = ('cavern_farm needs tiles 4-%d'):format(CAVERN_TILES_MAX)}
    end
    local B = builder()
    local t = B.tile_info(ax, ay, az)
    if not t or not t.feature_global then
        return {ok = false, rejected = true, error = ('x%d y%d z%d is not in a cavern'):format(ax, ay, az)}
    end
    local g = B.walk_group(ax, ay, az)
    if g == 0 then return {ok = false, rejected = true, error = 'the cavern there is not walkable'} end
    -- no danger near: the planner checks the cavern's beasts, this the ground itself
    local okd, spots_d = pcall(U.danger_spots)
    local dangers = okd and spots_d or {}
    pcall(function()
        for _, u in ipairs(units()) do
            local okh, h = pcall(function() return B.hostile_wild and B.hostile_wild(u) end)
            if okh and h and not (u.flags1.caged or u.flags1.chained) then
                table.insert(dangers, {x = u.pos.x, y = u.pos.y, z = u.pos.z})
            end
        end
    end)
    if U.near_danger(dangers, ax, ay, az, CAVERN_DANGER) then
        return {ok = false, rejected = true, error = ('a danger within %d tiles of the cavern\'s way in'):format(CAVERN_DANGER)}
    end
    local spots, total = cavern_spots(function(x, y, z) return cavern_soil(B, x, y, z, g) end,
                                      {x = ax, y = ay, z = az}, want, CAVERN_RADIUS, CAVERN_LEVELS,
                                      CAVERN_SIDE_MAX, CAVERN_SIDE_MIN)
    if #spots == 0 then
        return {ok = false, rejected = true,
                error = ('no free soil floor in the cavern within %d tiles of where the fort meets it'):format(CAVERN_RADIUS)}
    end
    local placed, tiles, refused = {}, 0, 0
    for _, sp in ipairs(spots) do
        local cell = {{x = 0, y = 0, text = ('p(%dx%d)'):format(sp.w, sp.h)}}
        if B.qf_try('build', cell, sp.z, sp.x, sp.y, dry_run) then
            table.insert(placed, sp)
            tiles = tiles + sp.w * sp.h
        else
            refused = refused + 1
        end
    end
    if #placed == 0 then
        return {ok = false, error = ('quickfort refused the cavern plots (%d spot(s))'):format(refused)}
    end
    local out = {ok = true, dry_run = dry_run or nil, plots = #placed, tiles = tiles, refused = refused > 0 and refused or nil,
                 placed = placed}
    if dry_run then return out end
    local l = remembered(CAVERN_KEY)
    for _, sp in ipairs(placed) do table.insert(l, {x = sp.x, y = sp.y, z = sp.z, w = sp.w, h = sp.h}) end
    while #l > 60 do table.remove(l, 1) end
    U.site_put(CAVERN_KEY, l)
    return out
end

-- --- the report ----------------------------------------------------------------------------

function report()
    local out = {}
    local function part(name, fn)
        local ok, v = pcall(fn)
        if ok then out[name] = v else out[name] = {error = tostring(v):sub(1, 160)} end
    end
    part('hunting', hunting_report)
    part('butchery', butchery_report)
    part('meals', meals_report)
    part('fruit', fruit_report)
    part('cavern', cavern_report)
    return out
end
