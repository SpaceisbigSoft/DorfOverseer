-- ai-bridge-report-supplies: the report's citizen anchor and walk groups, workshops, brewables,
-- the hospital's store, the supplies (the tombs and the dead: ai-bridge-report-dead).
--
-- A part of ai-bridge.lua (r6, split out of ai-bridge-report.lua when it was 194 KB),
-- loaded by it after ai-bridge-report into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-report files share with this one come from REPORT_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-report-supplies is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report-supplies'] = '0.105.116'   -- bumped with BRIDGE_VERSION

local inc, usable = REPORT_PART_LOCALS.inc, REPORT_PART_LOCALS.usable

-- (13c) Where the first citizen with a place on the map stands: what the
-- report and the actions judge "can the dwarves walk there" from (the dead,
-- tombs, workshops, slabs). nil when nobody has one. (Was written out four
-- times.)
function citizen_anchor()
    local from
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then from = xyz2pos(x, y, z) break end
        end
    end)
    return from
end

-- (0.105.48, A2-1) The walk groups the citizens stand in ({[group] = true},
-- group 0 left out), or nil when none can be read. A place any citizen can
-- walk to is in one of them: one dwarf cut off (on a ledge, outside the
-- gates, swimming) no longer decides for the fort.
function citizen_walk_groups()
    local set
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then
                local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
                if okg and type(g) == 'number' and g ~= 0 then
                    set = set or {}
                    set[g] = true
                end
            end
        end
    end)
    return set
end

local function is_empty(item)
    local ok, inside = pcall(dfhack.items.getContainedItems, item)
    return ok and #inside == 0
end

-- A workshop's name in the report: DF's workshop type, and for the custom
-- ones (the soap maker's, the screw press) the AI's name or the raws' code.
CUSTOM_SHOP_NAMES = {SOAP_MAKER = 'SoapMaker', SOAP_MAKERS = 'SoapMaker', SCREW_PRESS = 'ScrewPress'}
function workshop_name(b)
    local name = df.workshop_type[b.type] or tostring(b.type)
    if name == 'Custom' then
        local ok, code = pcall(function() return df.building_def.find(b.custom_type).code end)
        if ok and code then name = CUSTOM_SHOP_NAMES[code] or ('Custom:' .. code) end
    end
    return name
end

-- (0.99.5) Can a still brew this item? Its material names a drink among its
-- reaction products (the raws' MATERIAL_REACTION_PRODUCT:DRINK_MAT).
function brewable(item)
    local ok, yes = pcall(function()
        local mi = dfhack.matinfo.decode(item)
        if not mi or not mi.material then return false end
        for _, id in ipairs(mi.material.reaction_product.id) do
            local v = type(id) == 'string' and id or id.value
            if v == 'DRINK_MAT' then return true end
        end
        return false
    end)
    return ok and yes or false
end

local function mat_flags(item)
    local mi = dfhack.matinfo.decode(item)
    return mi and mi.material and mi.material.flags, mi
end

GOOD_MEAL_VALUE = 20
THREAD_WHOLE = 15000            -- (0.105.47, J1) a whole spun thread's dimension

-- Supplies that stall a fort without anyone noticing: empty containers
-- (brewing and cooking stop without them) and what a hospital and wells use.
-- Items already in a job don't count as free.
-- (0.105.33) A test: is this item kept in a chest (or other container
-- building) inside a hospital's zone? The hospital zones are found once, each
-- container's answer kept for the call.
function hospital_store_test()
    local zones = {}
    pcall(function()
        for _, b in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                if df.abstract_building_type[b:getType()] == 'HOSPITAL' then
                    for _, bid in ipairs(b:getContents().building_ids) do zones[bid] = true end
                end
            end)
        end
    end)
    if next(zones) == nil then return function() return false end end
    local seen = {}
    return function(it)
        local ok, r = pcall(function()
            local c = dfhack.items.getContainer(it)
            if not c then
                -- (R1 g6) on the hospital zone's floor: the hospital's too (R-AD:
                -- A's cloth at x109 y174 z163 in zone 582 counted as mood stock)
                if it.flags.in_inventory or it.flags.in_building then return false end
                local x, y, z = dfhack.items.getPosition(it)
                if not x then return false end
                for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(x, y, z)) or {}) do
                    if zones[zn.id] then return true end
                end
                return false
            end
            if seen[c.id] ~= nil then return seen[c.id] end
            local ans = false
            -- (0.105.36, D6) thread in a bag in the chest: the bag has no holder
            -- building, so walk up the containers (a few levels) to the one that has
            local bld, up = nil, c
            for _ = 1, 4 do
                bld = dfhack.items.getHolderBuilding(up)
                if bld then break end
                up = dfhack.items.getContainer(up)
                if not up then break end
            end
            if bld then
                for _, z in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(bld.centerx, bld.centery, bld.z)) or {}) do
                    if zones[z.id] then ans = true break end
                end
            end
            seen[c.id] = ans
            return ans
        end)
        return ok and r == true
    end
end

function get_supplies()
    local out = {empty_barrels = 0, empty_pots = 0, empty_bags = 0, buckets = 0, slabs = 0, fuel = 0, wheelbarrows = 0,
                 splints = 0, crutches = 0, soap = 0, ash = 0, lye = 0, tallow = 0, fat = 0, errors = {}}
    local other = df.global.world.items.other
    local function each(list_name, fn)
        local ok, err = pcall(function()
            for _, it in ipairs(other[df.items_other_id[list_name]]) do
                if usable(it) and not it.flags.in_job then fn(it) end
            end
        end)
        if not ok then out.errors[list_name] = tostring(err):sub(1, 120) end
    end
    each('BARREL', function(it) if is_empty(it) then out.empty_barrels = out.empty_barrels + 1 end end)
    -- (0.99.5) what a still can brew: a plant or growth whose material makes
    -- a drink (DRINK_MAT). region2's 325 "fruit" were leaves and the like:
    -- "Brew drink from fruit: Needs unrotten fermentable leaf or fruit"
    out.brewable_plants, out.brewable_growths = 0, 0
    -- (0.104.11) plants that give thread (Enxah had none: 59 thread orders stood still)
    -- (0.104.138) one pass for both, ai-builder looked up once and each plant
    -- kind's answer kept (the supplies section ran ~255 ms every report)
    out.thread_plants = 0
    -- (0.105.31 reserve fixes) the thread plants a still could brew too: the
    -- mood reserve's processing for thread leaves the drink's plants alone
    out.thread_brewable_plants = 0
    local okB, B = pcall(reqscript, 'ai-builder')
    local thread_of = {}
    each('PLANT', function(it)
        local n = it:getStackSize()
        local brews = brewable(it)
        if brews then out.brewable_plants = out.brewable_plants + n end
        local okp, yes = pcall(function()
            local okk, key = pcall(function() return it:getActualMaterialIndex() end)
            if okk and key ~= nil and thread_of[key] ~= nil then return thread_of[key] end
            local mi = dfhack.matinfo.decode(it)
            local yes_ = (okB and mi and mi.plant and B.plant_thread(mi.plant)) and true or false
            if okk and key ~= nil then thread_of[key] = yes_ end
            return yes_
        end)
        if okp and yes then
            out.thread_plants = out.thread_plants + n
            if brews then out.thread_brewable_plants = out.thread_brewable_plants + n end
        end
    end)
    each('PLANT_GROWTH', function(it)
        if brewable(it) then out.brewable_growths = out.brewable_growths + it:getStackSize() end
    end)
    -- (0.105.24) drink by kind (its material): dwarves who drink the same
    -- booze day after day are upset by it (SameBooze: B and E's worst stress)
    out.drink_kinds = 0
    pcall(function()
        local kinds = {}
        each('DRINK', function(it)
            local _, mi = mat_flags(it)
            local tok = mi and mi:getToken()
            if tok then kinds[tok] = (kinds[tok] or 0) + it:getStackSize() end
        end)
        local list = {}
        for tok, n in pairs(kinds) do table.insert(list, {tok, n}) end
        table.sort(list, function(a, b) return a[2] > b[2] end)
        out.drink_kinds = #list
        out.drink_by_kind = {}
        for i = 1, math.min(5, #list) do out.drink_by_kind[list[i][1]] = list[i][2] end
    end)
    -- (0.104.28) the wool route: tame animals that can be shorn (their caste
    -- has a shearable layer: sheep, llamas, alpacas, goats...). Enxah had no
    -- fibre crop and waited for caravans while patients went without sutures.
    out.shearable = 0
    pcall(function()
        for _, u in ipairs(report_units()) do
            if dfhack.units.isTame(u) and dfhack.units.isAlive(u) and not dfhack.units.isCitizen(u) then
                local okc, n = pcall(function()
                    return #df.creature_raw.find(u.race).caste[u.caste].shearable_tissue_layer
                end)
                if okc and n and n > 0 then
                    out.shearable = out.shearable + 1
                    -- (0.105.47, J1) and with wool grown long enough to shear now: a
                    -- shearable layer whose length modifier has reached the raws'
                    -- length (I7a: "Shear animal: No creature" 250 times in F while
                    -- the count above said yes). Unread: not counted as ready.
                    local okr, ready = pcall(function()
                        local c = df.creature_raw.find(u.race).caste[u.caste]
                        for _, l in ipairs(c.shearable_tissue_layer) do
                            for _, idx in ipairs(l.bp_modifiers_idx) do
                                if u.appearance.bp_modifiers[idx] >= l.length then return true end
                            end
                        end
                        return false
                    end)
                    if okr then
                        out.shearable_ready = (out.shearable_ready or 0) + (ready and 1 or 0)
                    else
                        out.shearable_unread = (out.shearable_unread or 0) + 1
                    end
                end
                -- (0.104.79) and those that can be milked (cows, goats, llamas...)
                local okm, m = pcall(function()
                    local c = df.creature_raw.find(u.race).caste[u.caste]
                    return c.flags.MILKABLE or (c.misc.milkable or 0) > 0
                end)
                if okm and m and dfhack.units.isAdult(u) and dfhack.units.isFemale(u) then
                    out.milkable = (out.milkable or 0) + 1
                end
                -- (0.104.80) and the hens that lay (chickens, ducks, geese...):
                -- they lay only in a nest box they can reach
                local oke, e = pcall(function()
                    return df.creature_raw.find(u.race).caste[u.caste].flags.LAYS_EGGS
                end)
                if oke and e and dfhack.units.isAdult(u) and dfhack.units.isFemale(u) and not u.flags1.caged then
                    out.egg_layers = (out.egg_layers or 0) + 1
                    if dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED) then
                        out.egg_layers_penned = (out.egg_layers_penned or 0) + 1
                    end
                end
            end
        end
    end)
    -- (0.100) raw food stacks: a cooking job takes 2-4 whole stacks, so the
    -- planner limits meal jobs by stacks, not by items
    out.food_stacks = 0
    for _, kind in ipairs({'MEAT', 'FISH', 'PLANT', 'PLANT_GROWTH', 'CHEESE', 'EGG'}) do
        local okw, w = pcall(stock_walk, kind)      -- (13c) the stocks section's walk
        if okw then out.food_stacks = out.food_stacks + w.free_items
        else out.errors[kind] = tostring(w):sub(1, 120) end
    end
    -- (0.104.80) nest boxes: built ones, and free ones to build
    out.nest_boxes, out.nest_box_items = 0, 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.NestBox then out.nest_boxes = out.nest_boxes + 1 end
        end
    end)
    -- (13c) the tools, once: nest boxes, empty large pots, wheelbarrows and
    -- blank quires (no writing on them)
    out.blank_quires = 0
    each('TOOL', function(it)
        local id = it.subtype and it.subtype.id
        if id == 'ITEM_TOOL_NEST_BOX' then out.nest_box_items = out.nest_box_items + 1
        elseif id == 'ITEM_TOOL_LARGE_POT' then
            if is_empty(it) then out.empty_pots = out.empty_pots + 1 end
        elseif id == 'ITEM_TOOL_WHEELBARROW' then out.wheelbarrows = out.wheelbarrows + 1
        elseif id == 'ITEM_TOOL_QUIRE' then
            local written = false
            pcall(function()
                for _, imp in ipairs(it.improvements) do
                    if imp:getType() == df.improvement_type.WRITING then written = true end
                end
            end)
            if not written then out.blank_quires = out.blank_quires + 1 end
        end
    end)
    -- (0.88.2) bags are their own item type, BAG (live 0.88.1: 92 boxes, all
    -- stone and wood chests; 838 seed stacks in BAG items). The old count
    -- looked for cloth "boxes", so it read 0 empty bags since it was written,
    -- and the kiln never got its order.
    -- (13c) counted in the one walk of the bags below
    -- (0.88) where the bags go: every bag by what it holds, and the seeds
    -- still loose. DF stores seeds in bags whenever it can (DF wiki, Bag),
    -- one bag per kind of seed, so each kind lying loose takes the next new bag.
    local ok_b, err_b = pcall(function()
        local use = {empty = 0, empty_in_job = 0, held = {}, bags = 0, seed_containers = {}}
        for _, it in ipairs(other.BAG) do
            if not it.flags.garbage_collect and not it.flags.removed then
                use.bags = use.bags + 1
                local inside = dfhack.items.getContainedItems(it)
                if #inside == 0 then
                    if it.flags.in_job then use.empty_in_job = use.empty_in_job + 1
                    else
                        use.empty = use.empty + 1
                        if usable(it) then out.empty_bags = out.empty_bags + 1 end
                    end
                else
                    local k = df.item_type[inside[1]:getType()] or '?'
                    use.held[k] = (use.held[k] or 0) + 1
                end
            end
        end
        local loose, bagged = {}, {}
        local n_loose = 0
        for _, it in ipairs(other.SEEDS) do
            if usable(it) and not it.flags.in_job then
                local key = it:getMaterial() .. ':' .. it:getMaterialIndex()
                local c = dfhack.items.getContainer(it)
                if c == nil then
                    loose[key] = true
                    n_loose = n_loose + it:getStackSize()
                else
                    bagged[key] = true
                    local ct = df.item_type[c:getType()] or '?'
                    use.seed_containers[ct] = (use.seed_containers[ct] or 0) + 1
                end
            end
        end
        local function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end
        -- a loose kind that already has a bag somewhere still wants one of its
        -- own only if that bag is full; counted apart so the planner can tell
        local loose_new = 0
        for k in pairs(loose) do if not bagged[k] then loose_new = loose_new + 1 end end
        use.seed_kinds_loose, use.seed_kinds_loose_unbagged = count(loose), loose_new
        use.seed_kinds_bagged, use.seeds_loose = count(bagged), n_loose
        out.bag_use = use
    end)
    if not ok_b then out.errors.bag_use = tostring(err_b):sub(1, 120) end
    -- empty ones only: lye is kept in buckets (the soap chain), and a full one
    -- isn't one the hospital can use (Oct 23: 97 bucket orders while lye sat in them)
    each('BUCKET', function(it) if is_empty(it) then out.buckets = out.buckets + 1 end end)
    -- (0.100) quivers: free ones (soldiers pick a spare up themselves) and worn ones
    out.quivers, out.quivers_worn = 0, 0
    each('QUIVER', function(it)
        if it.flags.in_inventory then out.quivers_worn = out.quivers_worn + 1 else out.quivers = out.quivers + 1 end
    end)
    -- (0.105.94) blank slabs only (engraving_type Slab, -1): the engraved are
    -- no use to a memorial. Live 23 Nov, F: a "Secrets" slab counted as the
    -- one blank, so slabs (1) < ghosts (1) never held and no blank was made;
    -- Urvad's EngraveSlab job waited 11 hours with no slab to take
    local BLANK = -1
    pcall(function() if df.slab_engraving_type.Slab ~= nil then BLANK = df.slab_engraving_type.Slab end end)
    each('SLAB', function(it)
        local okb, blank = pcall(function() return it.engraving_type == BLANK end)
        if okb and blank then out.slabs = (out.slabs or 0) + 1 end
    end)
    -- (0.103.16) engraved memorial slabs nobody has put up yet
    -- (item4) + spares (dead has one up)
    pcall(function()
        local m, sp, dup = reqscript('ai-builder').memorial_slabs()
        out.memorial_slabs, out.memorial_spare, out.dup_memorials = #m, sp, dup
    end)
    -- (r1g8) of them the walking ghosts' own; and the ghosts with no memorial
    -- slab at all and no open order of the AI's for one (engrave_memorials ghosts)
    pcall(function()
        local w, none = reqscript('ai-builder').ghost_slab_counts()
        out.ghost_slabs = w
        out.ghosts_unslabbed = none      -- (item7) no memorial slab at all, ordered or not
    end)
    pcall(function() out.ghosts_no_slab = #reqscript('ai-welfare').ghost_scan() end)
    -- (item7) EngraveSlab orders for a dead with a slab already, or that never end (lua/ai-memorials.lua)
    pcall(function()
        local m = reqscript('ai-memorials').order_scan()
        out.memorial_orders_stale, out.memorial_orders_endless = m.stale, m.endless
    end)
    -- (0.83) good meals: EatGoodMeal is met by a preferred food or a meal
    -- worth over 20 (DF wiki, Needs): servings of prepared meals and those
    -- worth more than GOOD_MEAL_VALUE each
    out.meal_servings, out.good_meals = 0, 0
    each('FOOD', function(it)
        local n = it:getStackSize()
        out.meal_servings = out.meal_servings + n
        local okv, v = pcall(dfhack.items.getValue, it)
        if okv and v and n > 0 and v / n > GOOD_MEAL_VALUE then out.good_meals = out.good_meals + n end
    end)
    -- (0.103.14) the fort's cooks (a lavish meal's worth grows with the cook's
    -- skill) and the lowest skill its kitchens let cook
    pcall(function()
        -- (0.105.8) best and skilled count only the cooks who can cook now:
        -- adults, sane, in no squad, with the cooking labour. Counting every
        -- citizen kept the six forts' kitchens at 3+ or 6+ for cooks who were
        -- soldiers (A: 27 of 37 in squads), and the lavish meals stuck at the
        -- kitchen for weeks; best_any keeps the old count
        local best, skilled, best_any, able = 0, 0, 0, {}
        for _, u in ipairs(report_citizens(true)) do
            local r = dfhack.units.getNominalSkill(u, df.job_skill.COOK, true) or 0
            if r > best_any then best_any = r end
            local ok_c, can = pcall(function()
                return dfhack.units.isAdult(u) and dfhack.units.isSane(u)
                    and (u.military.squad_id or -1) < 0
                    and u.status.labors[df.unit_labor.COOK] == true
            end)
            if ok_c and can then
                table.insert(able, r)
                if r > best then best = r end
                if r >= 5 then skilled = skilled + 1 end
            end
        end
        table.sort(able, function(x, y) return x > y end)
        local top = {}
        for i = 1, math.min(5, #able) do top[i] = able[i] end
        local kmin = nil
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            if b.type == df.workshop_type.Kitchen then
                local m = b.profile.min_level
                if kmin == nil or m < kmin then kmin = m end
            end
        end
        out.cooks = {best = best, skilled = skilled, kitchen_min = kmin, best_any = best_any,
                     able = #able, able_skills = top}
    end)
    -- (0.105.113 item13) the logs a citizen can walk to (D: 19 logs, all on the surface out of every
    -- dwarf's walk: the charcoal a bar mood's smelting needed never burnt); nil when no walk group is read
    pcall(function()
        local groups = citizen_walk_groups()
        if not groups then return end
        local n = 0
        each('WOOD', function(it)
            local x, y, z = dfhack.items.getPosition(it)
            if not x then return end
            local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
            if okg and groups[g] then n = n + it:getStackSize() end
        end)
        out.wood_reach = n
    end)
    each('SPLINT', function(it) out.splints = out.splints + it:getStackSize() end)
    each('CRUTCH', function(it) out.crutches = out.crutches + it:getStackSize() end)
    each('BAR', function(it)
        local _, mi = mat_flags(it)
        local token = mi and mi:getToken() or ''
        if token:find('SOAP') then out.soap = out.soap + it:getStackSize() end
        if token == 'ASH' then out.ash = out.ash + it:getStackSize() end
        if token:find('^COAL') then out.fuel = (out.fuel or 0) + it:getStackSize() end   -- charcoal, coke
    end)
    -- (0.104.95) glass: bags of sand (sand powder, in a bag), the sand zones,
    -- and the sand in the fort's geology (a sand zone needs some)
    -- (0.105.51) raw green glass (a glassmaker's mood asks 3; R3: two died
    -- waiting for it, none in the fort): the mood reserve's count
    out.green_glass = 0
    each('ROUGH', function(it)
        local _, mi = mat_flags(it)
        if mi and mi:getToken() == 'GLASS_GREEN' then out.green_glass = out.green_glass + it:getStackSize() end
    end)
    out.sand_bags = 0
    each('POWDER_MISC', function(it)
        local _, mi = mat_flags(it)
        if mi and mi.inorganic and mi.inorganic.flags.SOIL_SAND then out.sand_bags = out.sand_bags + 1 end
    end)
    pcall(function()
        local n = 0
        for _, z in ipairs(df.global.world.buildings.other.ZONE_SAND_COLLECTION or {}) do n = n + 1 end
        out.sand_zones = n
    end)
    if out.sand_zones == nil then
        pcall(function()
            local n = 0
            for _, b in ipairs(df.global.world.buildings.other.ACTIVITY_ZONE) do
                if b.type == df.civzone_type.SandCollection then n = n + 1 end
            end
            out.sand_zones = n
        end)
    end
    pcall(function()
        local names, seen = {}, {}
        local p = reqscript('ai-builder').citizen_positions()[1]
        if not p then return end
        local rx, ry = dfhack.maps.getTileBiomeRgn(p.x, p.y, p.z)
        if type(rx) == 'table' or type(rx) == 'userdata' then rx, ry = rx.x, rx.y end
        local okr, region = pcall(dfhack.maps.getRegionBiome, rx, ry)
        if not okr or not region then region = dfhack.maps.getRegionBiome(xy2pos(rx, ry)) end
        local biome = df.world_geo_biome.find(region.geo_index)
        for _, layer in ipairs(biome.layers) do
            local inorg = df.global.world.raws.inorganics.all[layer.mat_index]
            if inorg and inorg.flags.SOIL_SAND and not seen[inorg.id] then
                seen[inorg.id] = true
                table.insert(names, (inorg.id:lower():gsub('_', ' ')))   -- (gsub's count dropped)
            end
        end
        out.sand_layers = names
    end)
    -- the soap chain: lye (in buckets), tallow and fat (globs)
    local function each_any(list_name, fn)
        local ok, err = pcall(function()
            for _, it in ipairs(other[df.items_other_id[list_name]]) do
                local f = it.flags
                if not (f.forbid or f.garbage_collect or f.rotten or f.trader or f.removed or f.in_job) then fn(it) end
            end
        end)
        if not ok then out.errors[list_name] = tostring(err):sub(1, 120) end
    end
    -- the liquids, once (13c): lye; milk of lime (the kiln and paper chains);
    -- (0.104.79) milk to make cheese of (a liquid of a milk material, not
    -- milk of lime), which only has to be neither forbidden nor rotten
    out.milk, out.milk_of_lime = 0, 0
    local ok_l, err_l = pcall(function()
        for _, it in ipairs(other.LIQUID_MISC) do
            local f = it.flags
            local _, mi = mat_flags(it)
            local tok = mi and mi:getToken() or ''
            if tok:find('MILK') and not tok:find('MILK_OF_LIME') and not f.forbid and not f.rotten then
                out.milk = out.milk + 1
            end
            if not (f.forbid or f.garbage_collect or f.rotten or f.trader or f.removed or f.in_job) then
                if tok == 'LYE' then out.lye = out.lye + 1
                elseif tok:find('MILK_OF_LIME') then out.milk_of_lime = out.milk_of_lime + 1 end
            end
        end
    end)
    if not ok_l then out.errors.LIQUID_MISC = tostring(err_l):sub(1, 120) end
    each_any('GLOB', function(it)
        local _, mi = mat_flags(it)
        local token = mi and mi:getToken() or ''
        if token:find(':TALLOW$') then out.tallow = out.tallow + it:getStackSize()
        elseif token:find(':FAT$') then out.fat = out.fat + it:getStackSize() end
    end)
    -- (0.86) the kiln and paper chains (DF's reaction_other raws): quicklime
    -- and plaster powder (in bags), milk of lime (in buckets), sheets, blank
    -- quires (no writing on them), fresh hides that make parchment, and the
    -- boulders the kiln takes (calcium carbonate, gypsum); cloth by kind
    -- (a plant-cloth bag order can't use silk or yarn cloth)
    out.quicklime, out.plaster, out.sheets, out.hides = 0, 0, 0, 0
    out.calcium_carbonate, out.gypsum = 0, 0
    out.cloth_kinds = {plant = 0, silk = 0, yarn = 0}
    out.anvils = 0
    each('ANVIL', function(it) out.anvils = out.anvils + 1 end)
    -- (0.88) free traction benches (a hospital wants one), tables and ropes for one
    out.traction_benches, out.tables, out.ropes = 0, 0, 0
    each('TRACTION_BENCH', function(it) out.traction_benches = out.traction_benches + 1 end)
    -- (0.90) free statues, to lift a location's value to its tier
    out.statues = 0
    each('STATUE', function(it) out.statues = out.statues + 1 end)
    each('TABLE', function(it) out.tables = out.tables + 1 end)
    -- (0.105.51) free doors, cabinets and chairs: the idle-hands rule's stock
    -- furniture (made while the blocks are at their cap) stops at a count
    out.doors, out.cabinets, out.chairs = 0, 0, 0
    each('DOOR', function(it) out.doors = out.doors + 1 end)
    each('CABINET', function(it) out.cabinets = out.cabinets + 1 end)
    each('CHAIR', function(it) out.chairs = out.chairs + 1 end)
    each('CHAIN', function(it) out.ropes = out.ropes + 1 end)
    each_any('POWDER_MISC', function(it)
        local _, mi = mat_flags(it)
        local token = mi and mi:getToken() or ''
        if token:find('QUICKLIME') then out.quicklime = out.quicklime + 1
        elseif token:find('PLASTER') then out.plaster = out.plaster + 1 end
    end)
    each('SHEET', function(it) out.sheets = out.sheets + it:getStackSize() end)
    local function has_product(mat, id)
        local found = false
        pcall(function()
            for _, p in ipairs(mat.reaction_product.id) do if p.value == id then found = true end end
        end)
        return found
    end
    each_any('CORPSEPIECE', function(it)
        local _, mi = mat_flags(it)
        if mi and mi.material and has_product(mi.material, 'PARCHMENT_MAT') then out.hides = out.hides + 1 end
    end)
    -- (13c) from the one walk of the boulders a report
    local okb, census = pcall(boulder_census)
    if okb then
        for key, n in pairs(census.by_mat) do
            local c = ''
            local mt, mx = key:match('^(-?%d+):(-?%d+)$')
            local mi = mt and dfhack.matinfo.decode(tonumber(mt), tonumber(mx))
            pcall(function()
                for _, rc in ipairs(mi.material.reaction_class) do
                    if rc.value == 'CALCIUM_CARBONATE' or rc.value == 'GYPSUM' then c = rc.value end
                end
            end)
            if c == 'CALCIUM_CARBONATE' then out.calcium_carbonate = out.calcium_carbonate + n
            elseif c == 'GYPSUM' then out.gypsum = out.gypsum + n end
        end
    else
        out.errors.BOULDER = tostring(census):sub(1, 120)
    end
    -- (0.105.33) the hospital's stock (thread and cloth kept in its chests
    -- for sutures and dressings) is not the fort's: counted apart, so a mood
    -- or a reserve doesn't read it as weaving stock (C's yarn reserve
    -- re-ordered six times from it; F's silk/yarn looked met by it)
    out.hospital = {thread = 0, cloth = 0}
    local in_hospital = hospital_store_test()
    -- (0.105.47, J1) the kind by ai-moods' own test (cloth_kind), as the moods count it
    local okmk, MK = pcall(reqscript, 'ai-moods')
    local function kind_of(it)
        if okmk and MK and MK.cloth_kind then return MK.cloth_kind(it) end
        local f = mat_flags(it)
        return f and (f.SILK and 'silk' or f.YARN and 'yarn' or f.THREAD_PLANT and 'plant') or nil
    end
    -- (item2) and by fibre: a mood's cloth or thread may be all the hospital's (B's 15 thread);
    -- the brain releases the mood's kind (lua/ai-mood-help.lua hospital_release)
    out.hospital.cloth_kinds = {plant = 0, silk = 0, yarn = 0}
    out.hospital.thread_kinds = {plant = 0, silk = 0, yarn = 0}
    -- (0.105.113 item13) and the hospital's part-used thread (a suture's leftover, under
    -- THREAD_WHOLE) by kind: the loom weaves only whole thread (B: its thread 97% of a whole one)
    out.hospital.thread_short = {plant = 0, silk = 0, yarn = 0}
    local function hosp_kind(what, it)
        local k = kind_of(it)
        if k then out.hospital[what][k] = out.hospital[what][k] + it:getStackSize() end
        if k and what == 'thread_kinds' then
            local okd, d = pcall(function() return it:getTotalDimension() end)
            if okd and type(d) == 'number' and d > 0 and d < THREAD_WHOLE then
                out.hospital.thread_short[k] = out.hospital.thread_short[k] + it:getStackSize()
            end
        end
    end
    each('CLOTH', function(it)
        if in_hospital(it) then out.hospital.cloth = out.hospital.cloth + it:getStackSize(); hosp_kind('cloth_kinds', it) return end
        local k = kind_of(it)
        if k then out.cloth_kinds[k] = out.cloth_kinds[k] + it:getStackSize() end
    end)
    -- (0.104.140) thread by kind, as cloth: a stuck plant-cloth weave can turn
    -- to silk or yarn thread at hand (webs collected, wool spun)
    out.thread_kinds = {plant = 0, silk = 0, yarn = 0}
    -- (0.105.47, J1) thread shorter than a whole spun thread (dimension under
    -- THREAD_WHOLE, a suture's leftover) counted apart too (needs an in-game
    -- look: F's 6 yarn thread "unused collected" DF wouldn't weave)
    out.thread_short = {plant = 0, silk = 0, yarn = 0}
    each('THREAD', function(it)
        if in_hospital(it) then out.hospital.thread = out.hospital.thread + it:getStackSize(); hosp_kind('thread_kinds', it) return end
        local k = kind_of(it)
        if k then
            out.thread_kinds[k] = out.thread_kinds[k] + it:getStackSize()
            local okd, d = pcall(function() return it:getTotalDimension() end)
            if okd and type(d) == 'number' and d > 0 and d < THREAD_WHOLE then
                out.thread_short[k] = out.thread_short[k] + it:getStackSize()
            end
        end
    end)
    if next(out.errors) == nil then out.errors = nil end
    return out
end

-- (0.105.113) the tombs and the dead (get_dead): in ai-bridge-report-dead.lua
