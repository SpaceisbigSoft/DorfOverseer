-- ai-bridge-report-supplies: the report's citizen anchor and walk groups, workshops, brewables,
-- the hospital's store, the supplies, the tombs and the dead.
--
-- A part of ai-bridge.lua (r6, split out of ai-bridge-report.lua when it was 194 KB),
-- loaded by it after ai-bridge-report into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-report files share with this one come from REPORT_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-report-supplies is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report-supplies'] = '0.105.69'   -- bumped with BRIDGE_VERSION

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
    each('SLAB', function(it) out.slabs = (out.slabs or 0) + 1 end)
    -- (0.103.16) engraved memorial slabs nobody has put up yet
    pcall(function() out.memorial_slabs = #reqscript('ai-builder').memorial_slabs() end)
    -- (r1g8) of them the walking ghosts' own; and the ghosts with no memorial
    -- slab at all and no open order of the AI's for one (engrave_memorials ghosts)
    pcall(function()
        local w = reqscript('ai-builder').ghost_slab_counts()
        out.ghost_slabs = w
    end)
    pcall(function() out.ghosts_no_slab = #reqscript('ai-welfare').ghost_scan() end)
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
    each('CLOTH', function(it)
        if in_hospital(it) then out.hospital.cloth = out.hospital.cloth + it:getStackSize() return end
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
        if in_hospital(it) then out.hospital.thread = out.hospital.thread + it:getStackSize() return end
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

-- The dead: ghosts of the fort's own, citizens' bodies not yet in a coffin,
-- and coffins in a tomb zone that are still free for a burial.
local CORPSE_TYPES = {CORPSE = true, CORPSEPIECE = true, REMAINS = true}

local function coffin_is_free(b)
    for _, ci in ipairs(b.contained_items) do
        if ci.use_mode == 0 and CORPSE_TYPES[df.item_type[ci.item:getType()]] then
            return false
        end
    end
    return true
end

local function in_tomb_zone(b)
    local ok, zones = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(b.centerx, b.centery, b.z))
    if not ok or not zones then return false, nil end
    for _, z in ipairs(zones) do
        if z.type == df.civzone_type.Tomb then
            -- a tomb set aside for one dwarf (a noble's) isn't free for others
            local okid, owner = pcall(function() return z.assigned_unit_id end)
            return true, okid and owner or -1, z
        end
    end
    return false, nil
end

-- (0.104.16) a free tomb zone's own state: whether the game would bury a
-- citizen there (zone active, citizens not turned away)
local function tomb_state(z)
    local st = {}
    pcall(function() if z.is_active == 0 or z.is_active == false then st.inactive = true end end)
    pcall(function() if z.zone_settings.tomb.flags.no_citizens then st.no_citizens = true end end)
    pcall(function() if z.zone_settings.tomb.flags.no_pets == false then st.pets = true end end)
    return st
end

-- (0.104.21) The AI's tomb levels' areas (cached for one report).
AI_TOMBS = nil
function in_ai_tombs(x, y, z)
    if not AI_TOMBS then
        AI_TOMBS = {}
        pcall(function()
            local B = reqscript('ai-builder')
            for _, p in ipairs(B.load_projects().list) do
                if p.kind == 'tombs' and type(p.area) == 'table' then
                    -- (F4, S2) a floor tomb level: its own rooms only (a.own)
                    local oko, own = pcall(function() return B.own_areas(p) end)
                    for _, a in ipairs(oko and type(own) == 'table' and own or {p.area}) do
                        table.insert(AI_TOMBS, a)
                    end
                end
            end
        end)
        -- (0.105.47) and the coffins the AI put on its other levels (lua/ai-welfare.lua)
        pcall(function()
            for _, a in ipairs(reqscript('ai-welfare').corner_areas()) do table.insert(AI_TOMBS, a) end
        end)
    end
    for _, a in ipairs(AI_TOMBS) do
        if z == a.z and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2
                and (type(a.own) ~= 'function' or a.own({x1 = x, y1 = y, x2 = x, y2 = y})) then return true end
    end
    return false
end

-- (0.105.27) the game's standing orders on the dead, refuse and dumping
-- (uint8_t globals, df.global.standing_orders_*): {name = 0/1} for each
-- that exists in this DF, the name without the prefix
STANDING_DEAD_ORDERS = {
    'forbid_used_ammo', 'forbid_own_dead', 'forbid_own_dead_items', 'forbid_other_nohunt',
    'forbid_other_dead_items', 'gather_refuse', 'gather_refuse_outside',
    'dump_corpses', 'dump_skulls', 'dump_bones', 'dump_shells', 'dump_skins', 'dump_hair', 'dump_other',
}

local function standing_kept(name)
    return name:match('^forbid_') or name:match('^gather_refuse') or name:match('^dump_')
end

function standing_orders_dead()
    local out = {}
    local function read(name)
        local ok, v = pcall(function() return df.global['standing_orders_' .. name] end)
        if not ok or v == nil then return end
        if type(v) == 'boolean' then out[name] = v and 1 or 0
        elseif type(v) == 'number' then out[name] = v ~= 0 and 1 or 0 end
    end
    for _, name in ipairs(STANDING_DEAD_ORDERS) do read(name) end
    -- any other of the kind this DF has (the globals listed, where the game lets them be)
    pcall(function()
        for k in pairs(df.global) do
            local name = type(k) == 'string' and k:match('^standing_orders_(.+)$')
            if name and out[name] == nil and standing_kept(name) then read(name) end
        end
    end)
    return out
end

function get_dead()
    AI_TOMBS = nil
    local out = {ghosts = 0, ghost_names = {}, unburied = 0, tomb_coffins = 0, free_tombs = 0,
                 loose_coffins = 0}
    local race, civ = df.global.plotinfo.race_id, df.global.plotinfo.civ_id
    local from0 = citizen_anchor()
    -- (13c) the memorial slabs by whom they remember, read once (each ghost
    -- walked every slab)
    local memorials
    local function memorials_of(hf)
        if not memorials then
            memorials = {}
            for _, it in ipairs(df.global.world.items.other.SLAB) do
                if it.engraving_type == df.slab_engraving_type.Memorial then
                    memorials[it.topic] = memorials[it.topic] or {}
                    table.insert(memorials[it.topic], it)
                end
            end
        end
        return memorials[hf] or {}
    end
    -- and the bodies by whose they are (the last one listed, as before)
    local bodies
    local function body_of(id)
        if not bodies then
            bodies = {}
            for _, c in ipairs(df.global.world.items.other.CORPSE) do bodies[c.unit_id] = c end
        end
        return bodies[id]
    end
    for _, u in ipairs(report_units()) do
        if dfhack.units.isGhost(u) and u.race == race and u.civ_id == civ then
            out.ghosts = out.ghosts + 1
            if #out.ghost_names < 5 then
                table.insert(out.ghost_names, txt(dfhack.units.getReadableName(u)))
            end
            -- (0.104.39) each ghost: its kind (a violent one scares dwarves to
            -- death: 24 of Enxah's 34 deaths in a year were fright) and what
            -- memorial slab there is for it
            pcall(function()
                out.ghost_list = out.ghost_list or {}
                if #out.ghost_list < 20 then
                    local g = {id = u.id, hf = u.hist_figure_id, name = txt(dfhack.units.getReadableName(u))}
                    pcall(function() g.kind = df.ghost_type[u.ghost_info.type] end)
                    pcall(function()
                        for _, it in ipairs(memorials_of(u.hist_figure_id)) do
                            local st = it.flags.in_building and 'built' or it.flags.in_job and 'job'
                                or it.flags.construction and 'built' or 'loose'
                            g.slab = (g.slab == 'built') and 'built' or st
                            -- (0.104.41) where it is and what holds it
                            local x, y, z = dfhack.items.getPosition(it)
                            g.slab_at = {x = x, y = y, z = z, forbid = it.flags.forbid or nil,
                                         dump = it.flags.dump or nil, trader = it.flags.trader or nil,
                                         owned = it.flags.owned or nil}
                            pcall(function()
                                for _, ref in ipairs(it.specific_refs) do
                                    if ref.type == df.specific_ref_type.JOB then
                                        local j = ref.data.job
                                        g.slab_job = {type = df.job_type[j.job_type], suspended = j.flags.suspend or nil,
                                                      worker = dfhack.job.getWorker(j) and true or nil}
                                        local h = dfhack.job.getHolder(j)
                                        if h then g.slab_job.building = df.building_type[h:getType()]; g.slab_job.stage = h:getBuildStage() end
                                        -- (0.104.46) why it's suspended, by DFHack's suspendmanager
                                        pcall(function()
                                            local sm = require('plugins.suspendmanager')
                                            local keys = {}
                                            for k, v in pairs(sm) do if type(v) == 'function' then table.insert(keys, k) end end
                                            table.sort(keys)
                                            out.sm_api = keys
                                            for _, fn in ipairs({'suspendmanager_suspensionDescription', 'suspensionDescription',
                                                                 'getSuspensionDescription', 'suspendmanager_getDescription'}) do
                                                if sm[fn] then g.slab_job.why = tostring(sm[fn](j)) break end
                                            end
                                            if sm.isKeptSuspended then g.slab_job.kept = sm.isKeptSuspended(j) end
                                        end)
                                        pcall(function()
                                            local pos = xyz2pos(h.centerx, h.centery, h.z)
                                            local n = 0
                                            for _, it2 in ipairs(dfhack.maps.getTileBlock(pos).items) do
                                                local i2 = df.item.find(it2)
                                                if i2 and i2.pos.x == pos.x and i2.pos.y == pos.y and i2.pos.z == pos.z then n = n + 1 end
                                            end
                                            g.slab_job.items_on_tile = n
                                            g.slab_job.at = {x = pos.x, y = pos.y, z = pos.z}
                                        end)
                                    end
                                end
                            end)
                            pcall(function()
                                if from0 and x then g.slab_at.reach = dfhack.maps.canWalkBetween(from0, xyz2pos(x, y, z)) end
                            end)
                            -- (0.104.48) out of reach: the tiles round it, to see why
                            pcall(function()
                                if g.slab_at.reach == false and x then
                                    local rows = {}
                                    for yy = y - 3, y + 3 do
                                        local row = {}
                                        for xx = x - 3, x + 3 do
                                            local ch = '?'
                                            local tt = dfhack.maps.getTileType(xx, yy, z)
                                            local d, occ = dfhack.maps.getTileFlags(xx, yy, z)
                                            if tt then
                                                local sh = df.tiletype_shape[df.tiletype.attrs[tt].shape]
                                                ch = (sh == 'WALL' and '#') or (sh == 'FLOOR' and '.') or (sh == 'RAMP' and '^')
                                                    or (sh and sh:find('STAIR') and 'X') or (sh == 'EMPTY' and ' ') or ','
                                                if occ and occ.building ~= df.tile_building_occ.None then ch = 'B' end
                                                if d and d.flow_size > 0 then ch = d.flow_size >= 4 and 'W' or 'w' end
                                                if xx == x and yy == y then ch = '@' end
                                            end
                                            table.insert(row, ch)
                                        end
                                        table.insert(rows, table.concat(row))
                                    end
                                    g.slab_at.around = rows
                                    local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
                                    if b then g.slab_at.building = df.building_type[b:getType()] end
                                end
                            end)
                        end
                    end)
                    pcall(function()
                        local c = body_of(u.id)
                        g.body = c and (c.flags.in_building and 'entombed' or 'lying') or 'none'
                    end)
                    table.insert(out.ghost_list, g)
                end
            end)
        end
    end
    -- (0.104.15) why the unburied aren't buried: Enxah had 104 bodies and
    -- 7 free tombs for a whole season. Forbidden (DF's "forbid your dead"
    -- standing order, or by hand), marked for dumping, out of the dwarves'
    -- reach, or already on someone's job.
    local why = {forbidden = 0, dump = 0, in_job = 0, unreachable = 0, outside = 0, carried = 0,
                 not_ours = 0, free = 0}
    local samples = {}
    local side_ctx
    pcall(function()
        local U = reqscript('ai-util')
        if type(U.corpse_side) == 'function' and type(U.fort_race_civ) == 'function' then
            local r, c, g = U.fort_race_civ()
            side_ctx = {U = U, race = r, civ = c, group = g}
        end
    end)
    local from = from0      -- where the first citizen stands (13c: found once, above)
    for _, it in ipairs(df.global.world.items.other.CORPSE) do
        local ok, r = pcall(function() return it.race end)
        if ok and r == race and not it.flags.in_building and not it.flags.removed then
            out.unburied = out.unburied + 1
            pcall(function()
                local f = it.flags
                if f.forbid then why.forbidden = why.forbidden + 1 end
                if f.dump then why.dump = why.dump + 1 end
                if f.in_job then why.in_job = why.in_job + 1 end
                if f.in_inventory then why.carried = why.carried + 1 end
                local x, y, z = dfhack.items.getPosition(it)
                local reach = true
                if x and from then
                    reach = dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z))
                    if not reach then why.unreachable = why.unreachable + 1 end
                    local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
                    if d and d.outside then why.outside = why.outside + 1 end
                end
                -- (0.104.16) whose body: the fort's own dead, or a visitor's,
                -- a merchant's, a migrant's who never joined (DF buries only
                -- its own in the fort's tombs)
                -- (0.105.51) the shared classifier (ai-util corpse_side: the
                -- dead one's record, a visitor or merchant of any civ is not
                -- ours), else the civ alone as before
                local okc, own = pcall(function()
                    if side_ctx then return side_ctx.U.corpse_side(it, 'CORPSE', side_ctx) == 'own' end
                    local du = df.unit.find(it.unit_id)
                    return du ~= nil and du.civ_id == civ
                end)
                if okc and not own then
                    why.not_ours = why.not_ours + 1
                    -- (0.105.51) of those, the ones neither marked for the dump
                    -- nor lying in a garbage dump zone: the brain's burial_others
                    -- asks for these alone (a dumped body stays counted above)
                    local loose = not f.dump
                    if loose and x then
                        pcall(function()
                            for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(x, y, z)) or {}) do
                                if zn.type == df.civzone_type.Dump then loose = false end
                            end
                        end)
                    end
                    if loose then why.not_ours_loose = (why.not_ours_loose or 0) + 1 end
                end
                if reach and not f.forbid and not f.dump and not f.in_job and not f.in_inventory
                        and (not okc or own) then
                    why.free = why.free + 1          -- nothing in the way that the AI can see
                end
                if #samples < 5 and (f.forbid or not reach) and x then
                    local smp = {x = x, y = y, z = z, forbidden = f.forbid or nil, reach = reach}
                    -- (0.104.39) what the spot is: water over it, open space,
                    -- and how this one died (Enxah: 29 bodies out of reach)
                    pcall(function()
                        local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
                        if d and d.flow_size > 0 then
                            smp.water = d.flow_size
                            if d.liquid_type then smp.magma = true end
                        end
                        local tt = dfhack.maps.getTileType(xyz2pos(x, y, z))
                        if tt then smp.shape = df.tiletype_shape[df.tiletype.attrs[tt].shape] end
                    end)
                    pcall(function()
                        local du = df.unit.find(it.unit_id)
                        local inc = du and df.incident.find(du.counters.death_id)
                        if inc then smp.cause = df.death_type[inc.death_cause] end
                    end)
                    table.insert(samples, smp)
                end
            end)
        end
    end
    if out.unburied > 0 then
        out.why = why
        if #samples > 0 then out.samples = samples end
    end
    -- (0.104.39) how the fort's own died this year and last (DF's death
    -- incidents): Enxah lost dwarves overnight with none of it said
    pcall(function()
        local by, n, killers, by_citizen = {}, 0, {}, {}
        local y0 = df.global.cur_year - 1
        for _, inc in ipairs(df.global.world.incidents.all) do
            pcall(function()
                if inc.type == df.incident_type.Death and inc.event_year >= y0 then
                    local du = df.unit.find(inc.victim)
                    if du and du.civ_id == civ and du.race == race then
                        local c = df.death_type[inc.death_cause] or tostring(inc.death_cause)
                        by[c] = (by[c] or 0) + 1
                        n = n + 1
                        -- (0.104.50) who struck them down: a citizen (a fight, a
                        -- berserk, the guard), a ghost, a beast, an outsider
                        pcall(function()
                            local k = inc.criminal ~= -1 and df.unit.find(inc.criminal)
                            if k then
                                local who = (dfhack.units.isGhost(k) or dfhack.units.isDead(k)) and 'ghost'
                                    or (dfhack.units.isCitizen(k) or k.civ_id == civ) and 'citizen'
                                    or (dfhack.units.isAnimal and dfhack.units.isAnimal(k)) and 'animal'
                                    or 'outsider'
                                killers[who] = (killers[who] or 0) + 1
                                if who == 'citizen' and #by_citizen < 8 then
                                    table.insert(by_citizen, {cause = c, killer = txt(dfhack.units.getReadableName(k)),
                                                              victim = txt(dfhack.units.getReadableName(du))})
                                end
                            end
                        end)
                    end
                end
            end)
        end
        out.deaths = {since_year = y0, n = n, by_cause = by, killers = killers,
                      by_citizen = #by_citizen > 0 and by_citizen or nil}
    end)
    -- (0.104.16) who may bury them (the Burial labour, HAUL_BODY) and whether
    -- the free tombs can be walked to
    pcall(function()
        local n, lab = 0, df.unit_labor.HAUL_BODY
        for _, u in ipairs(report_citizens(true)) do
            if u.status.labors[lab] then n = n + 1 end
        end
        out.burial_labor = n
    end)
    out._from = from
    -- the game's standing orders on the dead (the Orders screen)
    -- (0.105.27) they are uint8_t 0/1, never true: `== true` read them false always
    out.standing = standing_orders_dead()
    out.forbid_own_dead = (out.standing.forbid_own_dead or 0) ~= 0
    out.forbid_own_dead_items = (out.standing.forbid_own_dead_items or 0) ~= 0
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Coffin and b:getBuildStage() >= b:getMaxBuildStage() then
            local tomb, owner, zone = in_tomb_zone(b)
            if not tomb then
                out.loose_coffins = out.loose_coffins + 1
            else
                out.tomb_coffins = out.tomb_coffins + 1
                local st = zone and tomb_state(zone) or {}
                -- (0.104.21) a tomb closed to citizens outside the AI's tomb
                -- levels (a noble's, or one you set up) isn't free for the dead:
                -- not counted, so the tomb rules see the real room
                local reserved = st.no_citizens and not in_ai_tombs(b.centerx, b.centery, b.z)
                if reserved and coffin_is_free(b) and (owner == nil or owner < 0) then
                    out.reserved_tombs = (out.reserved_tombs or 0) + 1
                elseif coffin_is_free(b) and (owner == nil or owner < 0) then
                    out.free_tombs = out.free_tombs + 1
                    if zone then
                        if st.inactive then out.free_tombs_inactive = (out.free_tombs_inactive or 0) + 1 end
                        if st.no_citizens then
                            out.free_tombs_no_citizens = (out.free_tombs_no_citizens or 0) + 1
                            -- (0.104.19) where: a noble's tomb, or a tomb of the AI's levels
                            out.closed_tombs = out.closed_tombs or {}
                            if #out.closed_tombs < 8 then
                                table.insert(out.closed_tombs, {x = b.centerx, y = b.centery, z = b.z, zone = zone.id})
                            end
                        end
                    end
                    pcall(function()
                        if out._from and not dfhack.maps.canWalkBetween(out._from, xyz2pos(b.centerx, b.centery, b.z)) then
                            out.free_tombs_unreachable = (out.free_tombs_unreachable or 0) + 1
                        end
                    end)
                end
            end
        end
    end
    out._from = nil
    -- (0.105.47, I7b) the fort's dead whose bodies can't be reached (out of the
    -- dwarves' walk, or gone: drowned, in ice, in the caverns) and how many of
    -- them have no memorial slab nor an order for one (lua/ai-welfare.lua)
    pcall(function()
        local sc = reqscript('ai-welfare').dead_scan()
        out.unreachable_dead = sc.total
        out.unreachable_bodies = sc.unreachable
        out.gone_bodies = sc.gone
        out.unreachable_no_slab = sc.without_slab
        out.memorials_wanted = sc.wanting
        out.memorial_orders = sc.ordered
    end)
    return out
end
