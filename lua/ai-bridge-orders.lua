-- ai-bridge-orders: work orders (the recipes the AI may queue, its own orders
-- kept in the save), the DFHack tools it may switch, and their actions.
--
-- A part of ai-bridge.lua (13c, when the 409 KB file was split), loaded by it
-- into its own environment: what is global here is the bridge's (reachable as
-- reqscript('ai-bridge').<name>), and the bridge's shared helpers (txt,
-- reject, int_in, whole_number, sorted_keys, abs_tick, translate_name,
-- in_fort, NOT_IN_FORT, OUT_DIR) are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-orders is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-orders'] = '0.105.39'   -- (0.105.26) bumped with BRIDGE_VERSION


---------------------------------------------------------------------------
-- Actions: the only ways the AI can change the game. Version 1 is limited to
-- changes that are easy to see and to undo.
---------------------------------------------------------------------------

-- DFHack automation tools the AI may switch on or off. autolabor is left out
-- on purpose: turning it on rewrites every dwarf's labor assignments.
TOOL_ALLOWLIST = {
    autobutcher = true, autochop = true, autofarm = true, seedwatch = true,
    nestboxes = true, tailor = true, autoclothing = true, suspendmanager = true,
    -- needed by building projects: planned furniture waits for materials
    -- instead of vanishing
    buildingplan = true,
    -- engraves memorial slabs for ghosts (needs blank slabs in stock)
    autoslab = true,
    -- cuts rough gems at a jeweller's (the AI sells cut gems)
    autogems = true,
}
local MAX_ORDER_AMOUNT = 500
local AI_ORDERS_KEY = 'ai-overseer/orders'

-- Work orders the AI may queue. Each recipe is copied from the order sets that
-- ship with DFHack (hack/data/orders/*.json), so DF is known to accept it.
-- The AI picks a recipe name; it never supplies job types or other raw fields.
--   kind 'stone': the AI may name a specific stone (INORGANIC:<STONE>);
--                 otherwise any stone is used.
ORDER_RECIPES = {
    -- drink and food
    brew_drink = {job = 'CustomReaction', reaction = 'BREW_DRINK_FROM_PLANT'},
    brew_drink_from_fruit = {job = 'CustomReaction', reaction = 'BREW_DRINK_FROM_PLANT_GROWTH'},
    make_mead = {job = 'CustomReaction', reaction = 'MAKE_MEAD'},
    -- meal_ingredients = how many ingredients per meal (DF's easy / fine / lavish)
    prepare_easy_meal = {job = 'PrepareMeal', meal_ingredients = 2},
    prepare_fine_meal = {job = 'PrepareMeal', meal_ingredients = 3},
    prepare_lavish_meal = {job = 'PrepareMeal', meal_ingredients = 4},
    mill_plants = {job = 'MillPlants'},
    process_plants = {job = 'ProcessPlants'},
    process_plants_barrel = {job = 'ProcessPlantsBarrel'},
    press_honeycomb = {job = 'CustomReaction', reaction = 'PRESS_HONEYCOMB'},
    -- industry
    make_charcoal = {job = 'MakeCharcoal'},
    make_ash = {job = 'MakeAsh'},
    make_potash = {job = 'MakePotashFromAsh'},
    make_lye = {job = 'MakeLye'},
    make_soap_from_tallow = {job = 'CustomReaction', reaction = 'MAKE_SOAP_FROM_TALLOW'},
    render_fat = {job = 'CustomReaction', reaction = 'RENDER_FAT'},
    dye_cloth = {job = 'DyeCloth'},
    spin_thread = {job = 'SpinThread', material_category = {'strand'}},
    shear_creature = {job = 'ShearCreature'},                               -- (0.104.28) the wool route
    milk_creature = {job = 'MilkCreature'},                                 -- (0.104.79) the dairy
    make_cheese = {job = 'MakeCheese'},
    stone_nest_box = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_NEST_BOX', kind = 'stone'},   -- (0.104.80)
    weave_plant_cloth = {job = 'WeaveCloth', material_category = {'plant'}},
    weave_yarn_cloth = {job = 'WeaveCloth', material_category = {'yarn'}},
    weave_silk_cloth = {job = 'WeaveCloth', material_category = {'silk'}},
    -- (0.105.24) a strange mood's leather (F: 8 of 103 failed moods waited on
    -- it first) and green glass (4 glassmakers' moods: "rough gem of green glass")
    tan_hide = {job = 'CustomReaction', reaction = 'TAN_A_HIDE'},
    raw_green_glass = {job = 'MakeRawGlass', material = 'GLASS_GREEN'},
    cloth_bag = {job = 'ConstructBag', material_category = {'cloth'}},
    silk_bag = {job = 'ConstructBag', material_category = {'silk'}},         -- (0.86) bags of the cloth there is
    yarn_bag = {job = 'ConstructBag', material_category = {'yarn'}},
    make_quicklime = {job = 'CustomReaction', reaction = 'MAKE_QUICKLIME'},  -- the kiln and paper chains (0.86)
    make_plaster_powder = {job = 'CustomReaction', reaction = 'MAKE_PLASTER_POWDER'},
    make_milk_of_lime = {job = 'CustomReaction', reaction = 'MAKE_MILK_OF_LIME'},
    make_parchment = {job = 'CustomReaction', reaction = 'MAKE_PARCHMENT'},
    make_quire = {job = 'CustomReaction', reaction = 'MAKE_QUIRE'},
    cloth_rope = {job = 'MakeChain', material_category = {'cloth'}},      -- a rope (a well needs one)
    yarn_rope = {job = 'MakeChain', material_category = {'yarn'}},        -- (0.105.18) a rope of yarn cloth
    silk_rope = {job = 'MakeChain', material_category = {'silk'}},        -- (0.105.18) a rope of silk cloth
    metal_chain = {job = 'MakeChain', kind = 'metal'},                     -- a chain (a jail's restraint)
    metal_anvil = {job = 'ForgeAnvil', kind = 'metal'},
    traction_bench = {job = 'ConstructTractionBench'},                     -- (0.88) a table, a mechanism, a rope or chain                    -- (0.86) a new forge needs one
    -- ore to bars at the smelter, one ore stone (INORGANIC:<ORE>) a job, a
    -- charcoal or coke each (DFHack's smelting library waits for 100 coal)
    smelt_ore = {job = 'SmeltOre', kind = 'stone'},
    -- steel, in two steps at the smelter (each takes flux stone and a fuel):
    -- iron to pig iron, then pig iron and iron to two steel bars
    pig_iron = {job = 'CustomReaction', reaction = 'PIG_IRON_MAKING'},
    -- coke, the smelter's fuel, from coal (the game's own smelter reactions)
    -- (the reaction codes are looked up in the game's raws: a smelter
    -- reaction that makes coke from that stone; 0.53's guessed codes were wrong)
    coke_bituminous = {job = 'CustomReaction', reaction_find = 'COAL_BITUMINOUS'},
    coke_lignite = {job = 'CustomReaction', reaction_find = 'LIGNITE'},
    steel = {job = 'CustomReaction', reaction = 'STEEL_MAKING'},
    -- (0.105.27) the items marked for melting melted at a smelter (DF 50
    -- makes no melt job by itself: the DF wiki's Melt page); ai-disposal's mark_melt adds it
    melt_metal = {job = 'MeltMetalObject'},
    -- wood
    wooden_bed = {job = 'ConstructBed', material_category = {'wood'}},
    -- wooden furniture (the Materials choice "wood where it will do")
    wooden_table = {job = 'ConstructTable', material_category = {'wood'}},
    wooden_chair = {job = 'ConstructThrone', material_category = {'wood'}},
    wooden_door = {job = 'ConstructDoor', material_category = {'wood'}},
    wooden_cabinet = {job = 'ConstructCabinet', material_category = {'wood'}},
    wooden_chest = {job = 'ConstructChest', material_category = {'wood'}},
    wooden_coffin = {job = 'ConstructCoffin', material_category = {'wood'}},
    wooden_armor_stand = {job = 'ConstructArmorStand', material_category = {'wood'}},
    wooden_weapon_rack = {job = 'ConstructWeaponRack', material_category = {'wood'}},
    wooden_bookcase = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_BOOKCASE', material_category = {'wood'}},
    -- clothing shoes (not metal boots), for nobles' mandates
    leather_shoes = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_SHOES', material_category = {'leather'}},
    cloth_shoes = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_SHOES', material_category = {'cloth'}},
    cloth_socks = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_SOCKS', material_category = {'cloth'}},
    leather_low_boots = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_BOOTS_LOW', material_category = {'leather'}},
    -- (0.100) crossbow soldiers carry bolts in a quiver (DFHack's military.json order)
    leather_quiver = {job = 'MakeQuiver', material_category = {'leather'}},
    leather_waterskin = {job = 'MakeFlask', material_category = {'leather'}}, glass_vial = {job = 'MakeFlask', material = 'GLASS_GREEN'},  -- (0.105.26) a soldier's water
    wooden_bin = {job = 'ConstructBin', material_category = {'wood'}},
    wooden_bucket = {job = 'MakeBucket', material_category = {'wood'}},
    wooden_barrel = {job = 'MakeBarrel', material_category = {'wood'}},
    wooden_cage = {job = 'MakeCage', material_category = {'wood'}},
    wooden_splint = {job = 'ConstructSplint', material_category = {'wood'}},
    wooden_crutch = {job = 'ConstructCrutch', material_category = {'wood'}},
    wooden_jug = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_JUG', material_category = {'wood'}},
    wheelbarrow = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_WHEELBARROW', material_category = {'wood'}},
    -- stone (any stone, or a named one)
    stone_blocks = {job = 'ConstructBlocks', kind = 'stone'},
    stone_crafts = {job = 'MakeCrafts', kind = 'stone'},      -- trade goods (any rock crafts)
    -- (0.104.95) crafts of a precious metal at the forge (a craft's value is mostly its material)
    metal_crafts = {job = 'MakeCrafts', kind = 'metal'},
    -- (0.104.95) glass: bags of sand filled at a glass furnace (a hauler, from a
    -- sand zone), then green glass goods made from them there with fuel
    -- (DFHack's own data/orders/glassstock.json: the job and GLASS_GREEN)
    collect_sand = {job = 'CollectSand'},
    glass_crafts = {job = 'MakeCrafts', material = 'GLASS_GREEN'},
    glass_blocks = {job = 'ConstructBlocks', material = 'GLASS_GREEN'},
    glass_table = {job = 'ConstructTable', material = 'GLASS_GREEN'},
    glass_chair = {job = 'ConstructThrone', material = 'GLASS_GREEN'},
    glass_door = {job = 'ConstructDoor', material = 'GLASS_GREEN'},
    glass_cabinet = {job = 'ConstructCabinet', material = 'GLASS_GREEN'},
    glass_chest = {job = 'ConstructChest', material = 'GLASS_GREEN'},
    glass_statue = {job = 'ConstructStatue', material = 'GLASS_GREEN'},
    glass_window = {job = 'MakeWindow', material = 'GLASS_GREEN'},
    -- (0.103.10) jewellery a dwarf wears: Be extravagant is met by wearing an
    -- item with a quality modifier (DF wiki, Needs), and a worn one is owned
    stone_amulet = {job = 'MakeAmulet', kind = 'stone'},
    stone_bracelet = {job = 'MakeBracelet', kind = 'stone'},
    stone_ring = {job = 'MakeRing', kind = 'stone'},
    stone_earring = {job = 'MakeEarring', kind = 'stone'},
    -- (0.104.137) jewellery in metal at the forge, for finery while stone is short
    metal_amulet = {job = 'MakeAmulet', kind = 'metal'},
    metal_bracelet = {job = 'MakeBracelet', kind = 'metal'},
    metal_ring = {job = 'MakeRing', kind = 'metal'},
    metal_earring = {job = 'MakeEarring', kind = 'metal'},
    stone_mugs = {job = 'MakeGoblet', kind = 'stone'},        -- mugs for the tavern
    -- (0.104.4) wooden goblets ("cups", DF wiki) at the craftsdwarf's, when there's no stone
    wooden_cups = {job = 'MakeGoblet', material_category = {'wood'}},
    -- (0.104.122) wooden crafts (figurines, rings, amulets... the craftsdwarf's
    -- pick) for the dwarves who want something to own when stone is short
    wood_crafts = {job = 'MakeCrafts', material_category = {'wood'}},
    -- (0.104.141) bone crafts: the butchers' bones, free while stone goes to furniture
    bone_crafts = {job = 'MakeCrafts', material_category = {'bone'}},
    stone_table = {job = 'ConstructTable', kind = 'stone'},
    stone_chair = {job = 'ConstructThrone', kind = 'stone'},
    stone_door = {job = 'ConstructDoor', kind = 'stone'},
    stone_cabinet = {job = 'ConstructCabinet', kind = 'stone'},
    stone_chest = {job = 'ConstructChest', kind = 'stone'},
    stone_coffin = {job = 'ConstructCoffin', kind = 'stone'},
    stone_statue = {job = 'ConstructStatue', kind = 'stone'},
    stone_slab = {job = 'ConstructSlab', kind = 'stone'},
    stone_armor_stand = {job = 'ConstructArmorStand', kind = 'stone'},
    stone_weapon_rack = {job = 'ConstructWeaponRack', kind = 'stone'},
    -- furniture in metal, at the forge (silver, gold and other metals the
    -- soldiers' gear doesn't need: brain/planner.py picks the metal)
    metal_table = {job = 'ConstructTable', kind = 'metal'},
    metal_chair = {job = 'ConstructThrone', kind = 'metal'},
    metal_door = {job = 'ConstructDoor', kind = 'metal'},
    metal_cabinet = {job = 'ConstructCabinet', kind = 'metal'},
    metal_chest = {job = 'ConstructChest', kind = 'metal'},
    metal_coffin = {job = 'ConstructCoffin', kind = 'metal'},
    metal_armor_stand = {job = 'ConstructArmorStand', kind = 'metal'},
    metal_weapon_rack = {job = 'ConstructWeaponRack', kind = 'metal'},
    stone_altar = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_ALTAR', kind = 'stone'},
    stone_bookcase = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_BOOKCASE', kind = 'stone'},
    stone_pedestal = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_PEDESTAL', kind = 'stone'},
    -- a "rock pot": food and drink storage made by a craftsdwarf, no wood needed
    stone_large_pot = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_LARGE_POT', kind = 'stone'},
    mechanisms = {job = 'ConstructMechanisms', kind = 'stone'},
    -- (0.92.1) the cistern's floodgate, at the mason's
    stone_floodgate = {job = 'ConstructFloodgate', kind = 'stone'},
    stone_hatch_cover = {job = 'ConstructHatchCover', kind = 'stone'},      -- (0.104.105) a hatch over a stair needs one
    -- soldiers' gear, in a named weapon-grade metal (steel, iron, bronze...)
    metal_battle_axe = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_AXE_BATTLE', kind = 'metal'},
    metal_pick = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_PICK', kind = 'metal'},   -- (0.99.4) more miners
    -- crafts set with cut gems at the jeweller's (far more valuable to sell)
    encrust_goods = {job = 'EncrustWithGems', item_category = {'finished_goods'}, kind = 'gem'},
    cut_gems = {job = 'CutGems', kind = 'gem'},                    -- (0.104.84) when there is no autogems
    -- a crossbow squad: wooden crossbows and bolts at the bowyer's, metal bolts at the forge
    wooden_crossbow = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_CROSSBOW', material_category = {'wood'}},
    wooden_bolts = {job = 'MakeAmmo', item_subtype = 'ITEM_AMMO_BOLTS', material_category = {'wood'}},
    metal_bolts = {job = 'MakeAmmo', item_subtype = 'ITEM_AMMO_BOLTS', kind = 'metal'},
    metal_spear = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_SPEAR', kind = 'metal'},
    metal_mace = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_MACE', kind = 'metal'},
    metal_mail_shirt = {job = 'MakeArmor', item_subtype = 'ITEM_ARMOR_MAIL_SHIRT', kind = 'metal'},
    metal_breastplate = {job = 'MakeArmor', item_subtype = 'ITEM_ARMOR_BREASTPLATE', kind = 'metal'},
    metal_helm = {job = 'MakeHelm', item_subtype = 'ITEM_HELM_HELM', kind = 'metal'},
    metal_greaves = {job = 'MakePants', item_subtype = 'ITEM_PANTS_GREAVES', kind = 'metal'},
    metal_gauntlets = {job = 'MakeGloves', item_subtype = 'ITEM_GLOVES_GAUNTLETS', kind = 'metal'},
    metal_high_boots = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_BOOTS', kind = 'metal'},
    metal_shield = {job = 'MakeShield', item_subtype = 'ITEM_SHIELD_SHIELD', kind = 'metal'},
}

-- Which plugins are on, from DFHack's own `enable` listing (the same way the
-- DFHack control panel reads it). Works for plugins without a Lua module too.
local function enabled_map()
    local out = {}
    local text = dfhack.run_command_silent('enable') or ''
    for line in text:gmatch('[^\n]+') do
        local name, state = line:match('^%s*(%S+):%s+(%S+)')
        if name then out[name] = (state == 'on') end
    end
    return out
end

function plugin_enabled(name, map)
    map = map or enabled_map()
    if map[name] ~= nil then return map[name] end
    local ok, mod = pcall(require, 'plugins.' .. name)
    if ok and type(mod) == 'table' and mod.isEnabled then
        return mod.isEnabled()
    end
    return nil -- state unknown
end

-- Manager orders the AI created, stored in the fort's save, so the AI can
-- only ever cancel its own orders and never the player's.
function ai_orders()
    local data = dfhack.persistent.getSiteData(AI_ORDERS_KEY, {ids = {}})
    data.ids = type(data.ids) == 'table' and data.ids or {}
    return data
end

function save_ai_orders(data)
    -- Forget orders DF has already finished and removed.
    local live = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do live[tostring(o.id)] = true end
    for id in pairs(data.ids) do
        if not live[id] then data.ids[id] = nil end
    end
    return pcall(dfhack.persistent.saveSiteData, AI_ORDERS_KEY, data)
end

-- Which of our recipes an existing manager order corresponds to (best
-- effort), so the planner can count what's already queued.
-- (0.101.8) stone, gem and metal recipes share a job: tell them apart by the
-- order's material (a stone door was read back as metal_door: the AI's
-- report then said it had ordered metal furniture in a fort with no bars)
local function order_kind(order)
    if order.mat_type ~= 0 then return nil end
    if order.mat_index == -1 then return 'stone' end
    local ok, info = pcall(dfhack.matinfo.decode, order.mat_type, order.mat_index)
    if not ok or not info then return nil end
    local f = info.material.flags
    return f.IS_METAL and 'metal' or f.IS_GEM and 'gem' or f.IS_STONE and 'stone' or nil
end

-- (0.104.119) a recipe naming a material (green glass) is only its own
-- orders: rock crafts were read as glass_crafts (pairs() order decided)
local MAT_CACHE = {}
function material_matches(r, order)
    if not r.material then return true end
    local mi = MAT_CACHE[r.material]
    if mi == nil then
        local ok, m = pcall(dfhack.matinfo.find, r.material)
        mi = ok and m or false
        MAT_CACHE[r.material] = mi
    end
    if not mi then return false end
    return order.mat_type == mi.type and (mi.index == -1 or order.mat_index == mi.index)
end

local function recipe_of(order)
    local job = df.job_type[order.job_type]
    local kind = order_kind(order)
    local subtype_token = nil
    if order.item_subtype >= 0 then
        -- DF usually leaves item_type NONE on orders; the job type implies it.
        local it = order.item_type
        if it == df.item_type.NONE then it = df.job_type.attrs[order.job_type].item end
        local def = dfhack.items.getSubtypeDef(it, order.item_subtype)
        subtype_token = def and def.id or nil
    end
    for name, r in pairs(ORDER_RECIPES) do
        -- (a recipe whose reaction is looked up in the raws, like coke: 0.54
        -- couldn't recognise its own coke orders and placed one every 2 days)
        local reaction = r.reaction or (r.reaction_find and coke_reaction(r.reaction_find)) or ''
        if r.job == job
                and reaction == order.reaction_name
                and (not r.meal_ingredients or r.meal_ingredients == order.mat_type)
                and (not r.item_subtype or r.item_subtype == subtype_token)
                and (not (r.kind == 'stone' or r.kind == 'metal' or r.kind == 'gem') or r.kind == kind)
                and material_matches(r, order) then
            local cats_ok = true
            for _, cat in ipairs(r.material_category or {}) do
                if not order.material_category[cat] then cats_ok = false end
            end
            if cats_ok then return name end
        end
    end
    return nil
end

-- (0.104.13) The jobs each AI order has made, by the order's id: how many,
-- how many suspended, how many a dwarf is on. Enxah's bucket order sat 28
-- days at a time, cancelled as stuck 30 times, with the reason never seen;
-- a suspended job is one the order never gets back to by itself.
function order_jobs(ids)
    local by = {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and ids[tostring(oid)] then
                local e = by[oid] or {n = 0, suspended = 0, working = 0}
                e.n = e.n + 1
                if j.flags.suspend then e.suspended = e.suspended + 1 end
                if dfhack.job.getWorker(j) then e.working = e.working + 1 end
                -- (0.104.73) where an unworked job waits, and the labour and
                -- skill it calls for (Enxah: 4 instrument orders, each one
                -- job nobody took)
                if not e.at and not dfhack.job.getWorker(j) then
                    pcall(function()
                        local b = dfhack.job.getHolder(j)
                        if b then
                            local bt = df.building_type[b:getType()] or '?'
                            local okw, wt = pcall(function() return df.workshop_type[b.type] end)
                            e.at = (okw and wt) and (bt .. ':' .. wt) or bt
                            e.at_id = b.id
                            -- (0.104.125) the workshop's worker profile: Teacheroar's
                            -- rope and cloth jobs waited 41 days with 175 dwarves
                            -- holding the labour (who may work there?)
                            pcall(function()
                                local pr = b.profile
                                local n = #pr.permitted_workers
                                if n > 0 then e.permitted = n end
                                if (pr.min_level or 0) > 0 then e.min_skill = pr.min_level end
                                if pr.max_level and pr.max_level < 3000 then e.max_skill = pr.max_level end
                            end)
                        end
                        local okl, lab = pcall(dfhack.job.getSpecificLabor, j)
                        if okl and lab and lab ~= -1 then e.labor = df.unit_labor[lab] end
                        local okk, sk = pcall(dfhack.job.getSkill, j)
                        if okk and sk and sk ~= -1 then e.skill = df.job_skill[sk] end
                    end)
                end
                by[oid] = e
            end
        end
        link = link.next
    end
    return by
end

function get_orders()
    local ai_ids = ai_orders().ids
    local okj, jobs_of = pcall(order_jobs, ai_ids)
    if not okj then jobs_of = {} end
    local out = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do
        table.insert(out, {
            id = o.id,
            recipe = recipe_of(o),
            job = df.job_type[o.job_type] or tostring(o.job_type),
            reaction = o.reaction_name ~= '' and o.reaction_name or nil,
            amount_left = o.amount_left,
            amount_total = o.amount_total,
            repeats = df.workquota_frequency_type[o.frequency] ~= 'OneTime',
            by_ai = ai_ids[tostring(o.id)] == true,
            jobs = jobs_of[o.id],
        })
        -- (0.101.2) the game's own view of the order: approved by the manager,
        -- active, tied to one workshop, conditions (a fresh fort's orders never
        -- moved: this says why)
        local e = out[#out]
        pcall(function()
            e.validated = o.status.validated == true
            e.active = o.status.active or nil
            -- (0.101.4) when the game next checks the order, and the fort's
            -- order-check countdown (plotinfo.manager_timer)
            if o.finished_year ~= -1 then e.next_check = {o.finished_year, o.finished_year_tick} end
            e.check_timer = df.global.plotinfo.manager_timer
            if o.workshop_id ~= -1 then e.workshop_id = o.workshop_id end
            if o.max_workshops ~= 0 then e.max_workshops = o.max_workshops end
            if #o.item_conditions > 0 then e.item_conditions = #o.item_conditions end
            if #o.order_conditions > 0 then e.order_conditions = #o.order_conditions end
        end)
    end
    return out
end

function get_tools()
    local out = {}
    local map = enabled_map()
    for name in pairs(TOOL_ALLOWLIST) do
        -- true / false, or nil when the state can't be read
        out[name] = plugin_enabled(name, map)
    end
    return out
end

-- The game's reaction that turns a stone (e.g. COAL_BITUMINOUS) into coke:
-- one whose code or name says coke and whose reagent is that stone. Its code,
-- or nil.
COKE_CACHE = COKE_CACHE or {}
function coke_reaction(stone)
    if COKE_CACHE[stone] ~= nil then return COKE_CACHE[stone] or nil end
    local ok, code = pcall(function()
        for _, r in ipairs(df.global.world.raws.reactions.reactions) do
            local text = (tostring(r.code) .. ' ' .. tostring(r.name)):upper()
            if text:find('COKE', 1, true) then
                for _, rg in ipairs(r.reagents) do
                    local ok2, mat = pcall(function()
                        return dfhack.matinfo.decode(rg.mat_type, rg.mat_index)
                    end)
                    local id = ok2 and mat and mat.inorganic and mat.inorganic.id
                    if id == stone then return r.code end
                end
                if text:find(stone:gsub('COAL_', ''), 1, true) then return r.code end
            end
        end
    end)
    code = ok and code or nil
    COKE_CACHE[stone] = code or false
    return code
end

-- Is there a reaction with this code in the game's raws?
function reaction_exists(code)
    local ok, found = pcall(function()
        for _, r in ipairs(df.global.world.raws.reactions.reactions) do
            if r.code == code then return true end
        end
        return false
    end)
    return ok and found
end

function act_work_order(a)
    local recipe = ORDER_RECIPES[a.recipe]
    if recipe and recipe.reaction_find then
        local code = coke_reaction(recipe.reaction_find)
        if not code then
            return reject(('the game has no coke reaction for %s (recipe %s)'):format(recipe.reaction_find, a.recipe))
        end
        local copy = {}
        for k, v in pairs(recipe) do if k ~= 'reaction_find' then copy[k] = v end end
        copy.reaction = code
        recipe = copy
    end
    if recipe and recipe.reaction and not reaction_exists(recipe.reaction) then
        return reject(('the game has no reaction %s (recipe %s)'):format(recipe.reaction, a.recipe))
    end
    if not recipe then
        return reject(('unknown recipe: %s (known: %s)'):format(
            tostring(a.recipe), table.concat(sorted_keys(ORDER_RECIPES), ', ')))
    end
    local amount = whole_number(a.amount)
    if not amount or amount < 1 or amount > MAX_ORDER_AMOUNT then
        return reject(('amount must be a whole number from 1 to %d'):format(MAX_ORDER_AMOUNT))
    end

    -- Built field by field from the recipe and checked values. Never pass
    -- AI-written JSON to workorder: some of its fields are run as Lua code.
    local spec = {amount_total = amount}
    for k, v in pairs(recipe) do
        if k ~= 'kind' then spec[k] = v end
    end
    if recipe.kind == 'stone' then
        spec.material = 'INORGANIC' -- any stone
        if a.material ~= nil then
            local info = type(a.material) == 'string' and a.material:match('^INORGANIC:')
                and dfhack.matinfo.find(a.material)
            if not info or not info.material.flags.IS_STONE then
                return reject('material must be a stone, written INORGANIC:<STONE>, e.g. INORGANIC:GRANITE')
            end
            spec.material = a.material
        end
    elseif recipe.kind == 'gem' then
        local info = type(a.material) == 'string' and a.material:match('^INORGANIC:')
            and dfhack.matinfo.find(a.material)
        if not info or not info.material.flags.IS_GEM then
            return reject('this recipe needs a gem, written INORGANIC:<GEM>, e.g. INORGANIC:AMETHYST')
        end
        spec.material = a.material
    elseif recipe.kind == 'metal' then
        local info = type(a.material) == 'string' and a.material:match('^INORGANIC:')
            and dfhack.matinfo.find(a.material)
        if not info or not info.material.flags.IS_METAL then
            return reject('this recipe needs a metal, written INORGANIC:<METAL>, e.g. INORGANIC:IRON')
        end
        spec.material = a.material
    elseif a.material ~= nil then
        return reject(('recipe %s does not take a material'):format(a.recipe))
    end

    local wo = reqscript('workorder')
    local orders = wo.preprocess_orders({spec})
    wo.fillin_defaults(orders)
    local all = df.global.world.manager_orders.all
    local count_before = #all
    local new_id = df.global.world.manager_orders.manager_order_next_id
    wo.create_orders(orders, true)
    if #all ~= count_before + 1 or all[#all - 1].id ~= new_id then
        return {ok = false, error = 'the game did not accept the work order'}
    end
    local data = ai_orders()
    data.ids[tostring(new_id)] = true
    local saved = save_ai_orders(data)
    return {ok = true, order_id = new_id, recipe = a.recipe, amount = amount,
            material = spec.material,
            warning = (not saved) and 'order created but not recorded; the AI cannot cancel it later' or nil}
end

-- True if DF's own screens might be holding this order right now. Deleting an
-- order that a screen points at would crash DF, so we refuse in that case.
local function order_in_use_by_ui(order)
    local ok, busy = pcall(function()
        local mi = df.global.game.main_interface
        local wo = mi.info.work_orders
        if mi.info.open and mi.info.current_mode == df.info_interface_mode_type.WORK_ORDERS then
            return true
        end
        if mi.job_details.open then return true end
        return wo.conditions.wq == order or wo.entering_wq == order
            or wo.b_entering_wq == order or mi.job_details.wq == order
            or mi.image_creator.ics.wq == order
    end)
    return (not ok) or busy -- if we can't tell, assume it's in use
end

-- Free an order the same way DFHack's `orders clear` does.
local function free_order(order)
    for _, c in ipairs(order.item_conditions) do c:delete() end
    for _, c in ipairs(order.order_conditions) do c:delete() end
    if order.items then
        for _, e in ipairs(order.items.elements) do e:delete() end
        order.items:delete()
    end
    order:delete()
end

-- (0.101.2) The manager approves ("validates") work orders in an office with
-- a chair; a new fort's office waits for a chair that needs an approved
-- order (a deadlock: two test forts never brewed, cooked or made a bed).
-- The AI's own orders that have waited are approved here, as the manager
-- would; never the player's. A working manager goes on approving the rest.
function act_approve_orders(a)
    local ids = ai_orders().ids
    local n = 0
    for _, o in ipairs(df.global.world.manager_orders.all) do
        if ids[tostring(o.id)] and not o.status.validated then
            if not a.dry_run then o.status.validated = true end
            n = n + 1
        end
    end
    if n == 0 then return reject('no unapproved orders of the AI\'s') end
    return {ok = true, approved = n, dry_run = a.dry_run or nil}
end

-- (0.104.13) The AI's own orders' jobs a workshop suspended are taken up
-- again (the player's "resume" in the workshop). Only jobs made by the AI's
-- orders: never a construction (suspendmanager's) or a player's job.
function act_unsuspend_orders(a)
    local ids = ai_orders().ids
    local want = whole_number(a.order_id)
    local n, kinds = 0, {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j and j.flags.suspend then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and ids[tostring(oid)] and (not want or want == oid) then
                if not a.dry_run then j.flags.suspend = false end
                n = n + 1
                local k = df.job_type[j.job_type] or tostring(j.job_type)
                kinds[k] = (kinds[k] or 0) + 1
            end
        end
        link = link.next
    end
    if n == 0 then return reject('no suspended job of the AI\'s orders') end
    return {ok = true, unsuspended = n, kinds = kinds, dry_run = a.dry_run or nil}
end

-- (0.105.33) one job on a workshop's bench, of one wood or one hard boulder
-- (the chair and the coffin/slab jobs share it)
local function bench_job(b, jt, wood)
    local job = dfhack.job.createLinked()
    job.job_type = jt
    job.mat_type = -1
    local ji = df.job_item:new()
    ji.mat_type = -1
    ji.mat_index = -1
    ji.quantity = 1
    if wood then
        job.material_category.wood = true
        ji.item_type = df.item_type.WOOD
        ji.vector_id = df.job_item_vector_id.WOOD
    else
        ji.item_type = df.item_type.BOULDER
        ji.vector_id = df.job_item_vector_id.BOULDER
        ji.flags3.hard = true
    end
    job.job_items.elements:insert('#', ji)
    dfhack.job.assignToWorkshop(job, b)
    return job
end

-- (0.101.4) Below 20 citizens orders need no approval, but the manager hands
-- them out only from an office with a chair; with no chair in the fort every
-- order waits forever (the Enxah fort never ran one in 3 years). One chair is
-- made the old way: a job put straight on a carpenter's (wood) or mason's
-- (stone) bench, the way a player clicks "add job" in the workshop.
function act_bootstrap_chair(a)
    local benches = {}
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        if (b.type == df.workshop_type.Carpenters or b.type == df.workshop_type.Masons)
                and b:getBuildStage() >= b:getMaxBuildStage() then
            for _, j in ipairs(b.jobs) do
                if j.job_type == df.job_type.ConstructThrone then
                    return reject('a chair job is already waiting at a workshop')
                end
            end
            table.insert(benches, b)
        end
    end
    table.sort(benches, function(x, y)   -- wood first: a carpenter's chair
        return (x.type == df.workshop_type.Carpenters and 0 or 1) < (y.type == df.workshop_type.Carpenters and 0 or 1)
    end)
    local b = benches[1]
    if not b then return reject('no finished carpenter\'s or mason\'s workshop') end
    if not (dfhack.job.createLinked and dfhack.job.assignToWorkshop) then
        return reject('this DFHack has no workshop job API')
    end
    local wood = b.type == df.workshop_type.Carpenters
    if a.dry_run then return {ok = true, dry_run = true, workshop = b.id, wood = wood} end
    local job = bench_job(b, df.job_type.ConstructThrone, wood)
    return {ok = true, workshop = b.id, job_id = job.id, material = wood and 'wood' or 'stone'}
end

-- (0.104.21) Jobs put straight on a workshop's bench when the AI's order for
-- them makes none (Enxah: a 29-coffin order took no job at the masons in
-- two game months while a tomb level waited and 106 dead lay unburied).
-- Only coffins so far: stone at a mason's, or wood at a carpenter's.
-- (0.104.32) and blank slabs: autoslab's engrave jobs waiting for one filled
-- the masons' job list (10 jobs: 7 of them "needs unengraved slab"), so no
-- slab and too few coffins could ever reach the bench (13 ghosts, 90 dead)
BENCH_JOBS = {
    coffin = {job = 'ConstructCoffin', shops = {Masons = 'stone', Carpenters = 'wood'}},
    slab = {job = 'ConstructSlab', shops = {Masons = 'stone'}},
}
-- jobs that may be lifted off a full bench to make room (make_room): only
-- unworked ones of orders that are not the AI's, waiting on what the bench
-- jobs make; the order makes them again later
BENCH_LIFT = {EngraveSlab = true}
BENCH_MAX = 5

-- (0.104.34) Jobs at a workshop whose work order no longer exists: the AI
-- cancels an order it finds stuck, and DF leaves the order's jobs on the
-- bench, unworked for good (Enxah: 14 jewellery and craft jobs on three
-- craftsdwarf's benches, 2 engrave jobs on the masons'). Only unworked jobs
-- with an order id that is gone; never a player's job (no order) or a
-- construction. count_only: just count them.
-- (0.105.33) only_id: just the jobs of that (cancelled) order
function orphan_jobs(count_only, max, only_id)
    local live = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do live[o.id] = true end
    local found, kinds = {}, {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and not live[oid] and (only_id == nil or oid == only_id)
                    and not dfhack.job.getWorker(j)
                    and dfhack.job.getHolder and dfhack.job.getHolder(j) then
                table.insert(found, j)
                local k = df.job_type[j.job_type] or tostring(j.job_type)
                kinds[k] = (kinds[k] or 0) + 1
            end
        end
        link = link.next
    end
    if count_only then return #found end
    local n = 0
    for i = 1, math.min(#found, max or 30) do
        if pcall(dfhack.job.removeJob, found[i]) then n = n + 1 end
    end
    return n, kinds, #found
end

function act_clear_orphan_jobs(a)
    if a.dry_run then
        local n = orphan_jobs(true)
        if n == 0 then return reject('no job without its order') end
        return {ok = true, dry_run = true, orphans = n}
    end
    local n, kinds, found = orphan_jobs(false, whole_number(a.max) or 30)
    if found == 0 then return reject('no job without its order') end
    if n == 0 then return {ok = false, error = 'the game would not remove the jobs'} end
    return {ok = true, removed = n, found = found, kinds = kinds}
end

-- (0.104.23) A workshop's limit of jobs taken from work orders ("max general
-- orders"), raised when its slots are all held by jobs that can't go on
-- (Enxah's masons: 5 engrave-memorial jobs of autoslab's, "needs unengraved
-- slab", held all 5 for 250 days, so the AI's slab, coffin and block orders
-- never reached the bench: the slabs those jobs wait for included).
function act_order_slots(a)
    local id = whole_number(a.workshop_id)
    local n = whole_number(a.max)
    if not id or not n or n < 1 or n > 15 then return reject('workshop_id and max 1-15 needed') end
    local b = df.building.find(id)
    if not b or not df.building_workshopst:is_instance(b) then return reject('no such workshop') end
    local old = b.profile.max_general_orders
    if n <= old then return reject(('the workshop already takes %d'):format(old)) end
    if not a.dry_run then b.profile.max_general_orders = n end
    return {ok = true, workshop = id, before = old, max = n, dry_run = a.dry_run or nil}
end

function act_bench_jobs(a)
    local spec = BENCH_JOBS[tostring(a.kind)]
    if not spec then return reject('kind must be one of: coffin, slab') end
    local n = whole_number(a.count) or 1
    if n < 1 or n > BENCH_MAX then return reject(('count must be 1-%d'):format(BENCH_MAX)) end
    if not (dfhack.job.createLinked and dfhack.job.assignToWorkshop) then
        return reject('this DFHack has no workshop job API')
    end
    local want = a.material == 'wood' and 'wood' or a.material == 'stone' and 'stone' or nil
    local jt = df.job_type[spec.job]
    local bench, have = nil, 0
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        local mat = spec.shops[df.workshop_type[b.type]]
        if mat and (not want or want == mat) and b:getBuildStage() >= b:getMaxBuildStage() then
            local waiting = 0
            for _, j in ipairs(b.jobs) do if j.job_type == jt then waiting = waiting + 1 end end
            have = have + waiting
            if not bench or (#b.jobs < #bench.jobs) then bench = b end
        end
    end
    if not bench then return reject('no finished workshop for ' .. tostring(a.kind)) end
    if have >= BENCH_MAX then return reject(('%d such jobs already wait at the benches'):format(have)) end
    n = math.min(n, BENCH_MAX - have)
    local lifted = 0
    if 10 - #bench.jobs < n and a.make_room then
        local mine = ai_orders().ids
        local lift = {}
        for _, j in ipairs(bench.jobs) do
            if BENCH_LIFT[df.job_type[j.job_type]] and not dfhack.job.getWorker(j)
                    -- (0.105.33) only jobs of orders that are not the AI's: a
                    -- job with no order (the player's, added at the bench) stays
                    and j.order_id ~= -1 and not mine[tostring(j.order_id)] then
                table.insert(lift, j)
            end
        end
        local want_free = n - (10 - #bench.jobs)
        if not a.dry_run then
            for i = 1, math.min(want_free, #lift) do
                if pcall(dfhack.job.removeJob, lift[i]) then lifted = lifted + 1 end
            end
        else
            lifted = math.min(want_free, #lift)
        end
    end
    n = math.min(n, 10 - #bench.jobs + (a.dry_run and lifted or 0))
    if n < 1 then return reject('the workshop\'s job list is full') end
    local wood = spec.shops[df.workshop_type[bench.type]] == 'wood'
    if a.dry_run then return {ok = true, dry_run = true, workshop = bench.id, count = n, lifted = lifted, material = wood and 'wood' or 'stone'} end
    for _ = 1, n do bench_job(bench, jt, wood) end
    return {ok = true, workshop = bench.id, count = n, lifted = lifted > 0 and lifted or nil,
            material = wood and 'wood' or 'stone'}
end

function act_cancel_work_order(a)
    local id = whole_number(a.order_id)
    if not id then return reject('order_id must be a whole number') end
    local data = ai_orders()
    if not data.ids[tostring(id)] then
        return reject(('order %d was not created by the AI (or has finished); the AI only cancels its own orders'):format(id))
    end
    local all = df.global.world.manager_orders.all
    for i = #all - 1, 0, -1 do
        local order = all[i]
        if order.id == id then
            if order_in_use_by_ui(order) then
                return reject('the work orders screen is open; try again when it is closed')
            end
            -- Remove "after order X completes" conditions pointing at it.
            for _, other in ipairs(all) do
                local conds = other.order_conditions
                for j = #conds - 1, 0, -1 do
                    if conds[j].order_id == id then
                        local c = conds[j]
                        conds:erase(j)
                        c:delete()
                    end
                end
            end
            all:erase(i)
            free_order(order)
            data.ids[tostring(id)] = nil
            save_ai_orders(data)
            -- (0.104.34) its jobs that nobody works go with it (DF leaves them)
            local gone = 0
            -- (0.105.33) only this order's: the fort-wide sweep is clear_orphan_jobs' own rule
            pcall(function() gone = orphan_jobs(false, 30, id) end)
            return {ok = true, order_id = id, cancelled = true, jobs_removed = gone > 0 and gone or nil}
        end
    end
    data.ids[tostring(id)] = nil
    save_ai_orders(data)
    return {ok = true, order_id = id, cancelled = false,
            note = 'order was already finished or removed'}
end

function act_tool(a)
    if not TOOL_ALLOWLIST[a.name] then
        return reject(('tool not allowed: %s (allowed: %s)'):format(
            tostring(a.name), table.concat(sorted_keys(TOOL_ALLOWLIST), ', ')))
    end
    if type(a.enabled) ~= 'boolean' then
        return reject('enabled must be true or false')
    end
    local output, rv = dfhack.run_command_silent(a.enabled and 'enable' or 'disable', a.name)
    if rv ~= CR_OK then
        return {ok = false, error = ('%s %s failed: %s'):format(
            a.enabled and 'enable' or 'disable', a.name, (output or ''):gsub('%s+$', ''))}
    end
    return {ok = true, name = a.name, enabled = plugin_enabled(a.name)}
end
