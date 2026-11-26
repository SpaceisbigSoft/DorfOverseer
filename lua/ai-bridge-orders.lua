-- ai-bridge-orders: work orders (the recipes the AI may queue, its own orders
-- kept in the save), the DFHack tools it may switch, and their actions.
--
-- A part of ai-bridge.lua (13c, when the 409 KB file was split), loaded by it
-- into its own environment: what is global here is the bridge's (reachable as
-- reqscript('ai-bridge').<name>), and the bridge's shared helpers (txt,
-- reject, int_in, whole_number, sorted_keys, abs_tick, translate_name,
-- in_fort, NOT_IN_FORT, OUT_DIR) are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-orders is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-orders'] = '0.105.130'   -- (0.105.26) bumped with BRIDGE_VERSION


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
    -- (item9) paper from plants, scrolls and codices: the reaction looked up
    -- in the game's raws by kind (lua/ai-paper.lua reaction; the vanilla codes
    -- are remembered, not read, so a reaction of the right shape stands in)
    make_slurry = {job = 'CustomReaction', paper = 'slurry'},
    press_paper = {job = 'CustomReaction', paper = 'press'},
    make_papyrus = {job = 'CustomReaction', paper = 'papyrus'},
    make_scroll = {job = 'CustomReaction', paper = 'scroll'},
    bind_codex = {job = 'CustomReaction', paper = 'codex'},
    wooden_scroll_rollers = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_SCROLL_ROLLERS', material_category = {'wood'}},
    wooden_book_binding = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_BOOK_BINDING', material_category = {'wood'}},
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
    -- (0.105.40 M7) alloys at the smelter from bars (vanilla reaction_smelter.txt,
    -- the "(use bars)" reactions; each takes a fuel unless at a magma smelter).
    -- `alloy`: when the code isn't in this game's raws, the smelter reaction
    -- whose reagents are all bars and whose product is a bar of that metal.
    alloy_bronze = {job = 'CustomReaction', reaction = 'BRONZE_MAKING2', alloy = 'BRONZE'},
    alloy_bismuth_bronze = {job = 'CustomReaction', reaction = 'BISMUTH_BRONZE_MAKING', alloy = 'BISMUTH_BRONZE'},
    alloy_brass = {job = 'CustomReaction', reaction = 'BRASS_MAKING2', alloy = 'BRASS'},
    alloy_electrum = {job = 'CustomReaction', reaction = 'ELECTRUM_MAKING2', alloy = 'ELECTRUM'},
    alloy_billon = {job = 'CustomReaction', reaction = 'BILLON_MAKING2', alloy = 'BILLON'},
    alloy_black_bronze = {job = 'CustomReaction', reaction = 'BLACK_BRONZE_MAKING', alloy = 'BLACK_BRONZE'},
    alloy_rose_gold = {job = 'CustomReaction', reaction = 'ROSE_GOLD_MAKING', alloy = 'ROSE_GOLD'},
    alloy_sterling_silver = {job = 'CustomReaction', reaction = 'STERLING_SILVER_MAKING', alloy = 'STERLING_SILVER'},
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
    -- (item10) a leather uniform's armour, while metal is short (brain/planner_leather.py)
    leather_armor = {job = 'MakeArmor', item_subtype = 'ITEM_ARMOR_LEATHER', material_category = {'leather'}},
    leather_cap = {job = 'MakeHelm', item_subtype = 'ITEM_HELM_CAP', material_category = {'leather'}},
    leather_leggings = {job = 'MakePants', item_subtype = 'ITEM_PANTS_LEGGINGS', material_category = {'leather'}},
    leather_gloves = {job = 'MakeGloves', item_subtype = 'ITEM_GLOVES_GLOVES', material_category = {'leather'}},
    leather_high_boots = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_BOOTS', material_category = {'leather'}},
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
    -- (0.105.51) the piece a Quern or a Millstone workshop is built from, at
    -- the mason's (df.job_type ConstructQuern / ConstructMillstone, rock)
    stone_quern = {job = 'ConstructQuern', kind = 'stone'},
    stone_millstone = {job = 'ConstructMillstone', kind = 'stone'},
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
    -- (r2h4) crossbows forged of metal (no bowyer's needed), bolts carved of bone at the craftsdwarf's
    metal_crossbow = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_CROSSBOW', kind = 'metal'},
    bone_bolts = {job = 'MakeAmmo', item_subtype = 'ITEM_AMMO_BOLTS', material_category = {'bone'}},
    -- (item5) siege engines (lua/ai-siege.lua): parts and arrows at the siege workshop,
    -- the ballista's arrowheads at the forge
    ballista_parts = {job = 'ConstructBallistaParts', material_category = {'wood'}},
    catapult_parts = {job = 'ConstructCatapultParts', material_category = {'wood'}},
    ballista_arrowheads = {job = 'MakeBallistaArrowHead', kind = 'metal'},
    ballista_arrows = {job = 'AssembleSiegeAmmo', item_subtype = 'ITEM_SIEGEAMMO_BALLISTA', material_category = {'wood'}},
    metal_spear = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_SPEAR', kind = 'metal'},
    metal_mace = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_MACE', kind = 'metal'},
    metal_mail_shirt = {job = 'MakeArmor', item_subtype = 'ITEM_ARMOR_MAIL_SHIRT', kind = 'metal'},
    metal_breastplate = {job = 'MakeArmor', item_subtype = 'ITEM_ARMOR_BREASTPLATE', kind = 'metal'},
    metal_helm = {job = 'MakeHelm', item_subtype = 'ITEM_HELM_HELM', kind = 'metal'},
    metal_greaves = {job = 'MakePants', item_subtype = 'ITEM_PANTS_GREAVES', kind = 'metal'},
    metal_gauntlets = {job = 'MakeGloves', item_subtype = 'ITEM_GLOVES_GAUNTLETS', kind = 'metal'},
    metal_high_boots = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_BOOTS', kind = 'metal'},
    metal_shield = {job = 'MakeShield', item_subtype = 'ITEM_SHIELD_SHIELD', kind = 'metal'},
    -- (item5) a noble's mandate for shields or bucklers (Hammerstirred's queen asked
    -- for bucklers year after year; unmet, her office holders were jailed): wood, at the carpenter's
    wooden_shield = {job = 'MakeShield', item_subtype = 'ITEM_SHIELD_SHIELD', material_category = {'wood'}},
    wooden_buckler = {job = 'MakeShield', item_subtype = 'ITEM_SHIELD_BUCKLER', material_category = {'wood'}},
}
-- (0.105.45) giant axe blades at the forge for the kill zones' weapon traps (lua/ai-killzone.lua;
-- vanilla's trap component token: needs an in-game look that DF takes the order)
ORDER_RECIPES.metal_trap_blades = {job = 'MakeTrapComponent', item_subtype = 'ITEM_TRAPCOMP_GIANTAXEBLADE', kind = 'metal'}
-- (0.105.47, J1) webs collected for silk thread at a Loom (DF's CollectWebs job; a
-- strange mood's silk or the silk reserve: I7a, 20 moods died waiting on silk, no route)
ORDER_RECIPES.collect_webs = {job = 'CollectWebs'}

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
-- (r4 k4, audit A7 B6) `by`: order id -> who in the AI made it, when it is
-- not the planner ('strategist': the token-using review's own orders). Only
-- those are shown to the strategist as its own, and only those it may cancel.
function ai_orders()
    local data = dfhack.persistent.getSiteData(AI_ORDERS_KEY, {ids = {}})
    data.ids = type(data.ids) == 'table' and data.ids or {}
    data.by = type(data.by) == 'table' and data.by or {}
    return data
end

-- (r4 k4) An order the AI made, recorded: `by` 'strategist' marks the
-- strategist's own (any other value: the planner's, unmarked)
function record_ai_order(data, id, by)
    data.ids[tostring(id)] = true
    if by == 'strategist' then data.by[tostring(id)] = 'strategist' end
end

function save_ai_orders(data)
    -- Forget orders DF has already finished and removed.
    local live = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do live[tostring(o.id)] = true end
    for id in pairs(data.ids) do
        if not live[id] then data.ids[id] = nil end
    end
    for id in pairs(data.by or {}) do
        if not live[id] or not data.ids[id] then data.by[id] = nil end
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
        local reaction = (r.alloy and alloy_reaction(r)) or r.reaction
            or (r.reaction_find and coke_reaction(r.reaction_find)) or ''
        if r.paper and r.job == job then reaction = paper_reaction(r.paper) or '' end   -- (item9)
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
-- (0.105.46, I3) how many grown citizens outside the squads hold a labour
-- (df.unit_labor number): an order's job waiting for a worker nobody can be
-- is stuck for want of the labour, not of materials. Counted once a labour a
-- report (`memo`), nil when the citizens can't be read.
local function labour_holders(lab, memo)
    if memo[lab] ~= nil then return memo[lab] or nil end
    local ok, n = pcall(function()
        local c = 0
        for _, u in ipairs(dfhack.units.getCitizens(true) or {}) do
            local grown = true
            pcall(function() grown = dfhack.units.isAdult(u) end)
            if grown and u.military.squad_id == -1 and u.status.labors[lab] then c = c + 1 end
        end
        return c
    end)
    memo[lab] = ok and n or false
    return ok and n or nil
end

function order_jobs(ids)
    local by = {}
    local memo = {}            -- (0.105.46, I3) labour -> holders, once a call
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
                        -- (0.105.48, A2-5) DFHack 53.17 has no job.getSpecificLabor:
                        -- ai-labor's job_labor (the job type's labour, a reaction's
                        -- by its skill, a skill-less job's by its workshop)
                        local okl, lab = pcall(function() return reqscript('ai-labor').job_labor(j) end)
                        if okl and lab and lab ~= -1 then
                            e.labor = df.unit_labor[lab]
                            -- (0.105.46, I3) and whether anyone may take it: DF says
                            -- nothing more of a job that waits (its items are looked
                            -- for only when a worker takes it)
                            e.holders = labour_holders(lab, memo)
                            if e.holders == 0 then e.why = 'no citizen has the labour ' .. tostring(e.labor) end
                        end
                        -- (0.105.48 r2) nor job.getSkill: ai-labor's job_skill (the
                        -- job type's skill, a reaction's its own)
                        local okk, sk = pcall(function() return reqscript('ai-labor').job_skill(j) end)
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
    local ai_data = ai_orders()
    local ai_ids, ai_by = ai_data.ids, ai_data.by
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
            -- (r4 k4, B6) the strategist's own (a marker apart from the planner's)
            by_strategist = (ai_ids[tostring(o.id)] == true and ai_by[tostring(o.id)] == 'strategist') or nil,
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
        -- (0.105.46, I3) the order's material (INORGANIC:IRON...): two helm
        -- orders in two metals are two orders, one may lack its bars
        -- (0.105.48, A2-3) not a meal's: PrepareMeal keeps its ingredient
        -- count there, which decodes as a glass
        pcall(function()
            if o.mat_type ~= -1 and df.job_type[o.job_type] ~= 'PrepareMeal' then
                local mi = dfhack.matinfo.decode(o.mat_type, o.mat_index)
                if mi then e.material = mi:getToken() end
            end
        end)
        -- (0.105.99) what kind of material an order takes by category (cloth,
        -- silk, yarn, leather): a waiting mood's cloth went into clothing orders
        pcall(function()
            local mc, cats = o.material_category, {}
            for _, k in ipairs({'cloth', 'silk', 'yarn', 'leather'}) do
                if mc[k] == true then table.insert(cats, k) end
            end
            if #cats > 0 then e.mat_cats = cats end
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

-- (item9) A paper recipe's reaction code (lua/ai-paper.lua), or nil.
function paper_reaction(kind)
    local ok, code = pcall(function() return reqscript('ai-paper').reaction(kind) end)
    return ok and code or nil
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

-- (0.105.40 M7) An alloy recipe's reaction code: its own when the game has it,
-- else a smelter reaction whose reagents are all bars and which makes a bar of
-- the recipe's metal (a mod that renamed it). Nil when there is neither.
-- (fix41) the cache is one world's raws: emptied when the world or map is
-- unloaded, and keyed by the save's folder too (a world loaded without the
-- unload seen, or a bridge reloaded, never reads another world's codes)
ALLOY_CACHE = ALLOY_CACHE or {}
-- (r1g9) the world by its name (ai-util world_name), not the save folder
-- DF's seasonal autosave renames
function alloy_world()
    local okw, world = pcall(function() return reqscript('ai-util').world_name() end)
    if not okw or type(world) ~= 'string' then
        okw, world = pcall(function() return df.global.world.cur_savegame.save_dir end)
    end
    return okw and world ~= nil and tostring(world) or ''
end
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-bridge-alloys'] = function(sc)
        if sc == SC_WORLD_UNLOADED or sc == SC_MAP_UNLOADED then ALLOY_CACHE = {} end
    end
end
function alloy_reaction(r)
    local key = alloy_world() .. '|' .. tostring(r.reaction) .. '/' .. tostring(r.alloy)
    if ALLOY_CACHE[key] ~= nil then return ALLOY_CACHE[key] or nil end
    local code = nil
    -- (lead) the named code only when its reagents are all bars: vanilla's
    -- BRONZE_MAKING, BRASS_MAKING, ELECTRUM_MAKING and BILLON_MAKING take ORE
    -- (the bar versions end in 2); a mod may differ
    local named_ok = false
    if r.reaction and reaction_exists(r.reaction) then
        named_ok = pcall(function()
            for _, rx in ipairs(df.global.world.raws.reactions.reactions) do
                if rx.code == r.reaction then
                    if #rx.reagents == 0 then error('no reagents') end
                    for _, rg in ipairs(rx.reagents) do
                        if rg.item_type ~= df.item_type.BAR then error('not bars') end
                    end
                    return
                end
            end
        end)
    end
    if named_ok then
        code = r.reaction
    else
        local ok, found = pcall(function()
            for _, rx in ipairs(df.global.world.raws.reactions.reactions) do
                local bars_only = #rx.reagents > 0
                for _, rg in ipairs(rx.reagents) do
                    local okb, it = pcall(function() return rg.item_type end)
                    if not okb or it ~= df.item_type.BAR then bars_only = false end
                end
                if bars_only then
                    for _, pr in ipairs(rx.products) do
                        local okp, id = pcall(function()
                            if pr.item_type ~= df.item_type.BAR then return nil end
                            local mi = dfhack.matinfo.decode(pr.mat_type, pr.mat_index)
                            return mi and mi.inorganic and mi.inorganic.id
                        end)
                        if okp and id == r.alloy then return rx.code end
                    end
                end
            end
        end)
        code = ok and found or nil
    end
    ALLOY_CACHE[key] = code or false
    return code
end

function act_work_order(a)
    local recipe = ORDER_RECIPES[a.recipe]
    if recipe and recipe.alloy then
        local code = alloy_reaction(recipe)
        if not code then
            return reject(('the game has no reaction making %s bars from bars (recipe %s)'):format(
                recipe.alloy, a.recipe))
        end
        local copy = {}
        for k, v in pairs(recipe) do if k ~= 'alloy' then copy[k] = v end end
        copy.reaction = code
        recipe = copy
    end
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
    if recipe and recipe.paper then         -- (item9) paper, scrolls, codices
        local code = paper_reaction(recipe.paper)
        if not code then
            return reject(('the game has no %s reaction (recipe %s)'):format(recipe.paper, a.recipe))
        end
        local copy = {}
        for k, v in pairs(recipe) do if k ~= 'paper' then copy[k] = v end end
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
    record_ai_order(data, new_id, a.by)
    local saved = save_ai_orders(data)
    -- (0.105.46, I3) approved as it is placed, when the brain says the manager
    -- doesn't get to the AI's orders (it approved them itself before: 674
    -- approve_orders in a day's run, 30 a game year, each after a 3-day wait)
    local approved = nil
    if a.approve == true then
        approved = pcall(function() all[#all - 1].status.validated = true end) or nil
    end
    -- (fix6) a paper step ordered: the cached paper section (its inputs and
    -- tools) is read again, not served a day old to order the step twice
    local base = ORDER_RECIPES[a.recipe]
    local paper_step = base and (base.paper or base.item_subtype == 'ITEM_TOOL_SCROLL_ROLLERS'
        or base.item_subtype == 'ITEM_TOOL_BOOK_BINDING')
    return {ok = true, order_id = new_id, recipe = a.recipe, amount = amount,
            material = spec.material, stale = paper_step and {'paper'} or nil, approved = approved,
            warning = (not saved) and 'order created but not recorded; the AI cannot cancel it later' or nil}
end

-- (0.105.119) approve, unsuspend, the bootstrap chair, the bench jobs, the
-- orphaned jobs, the order slots, cancel an order and act_tool: in
-- ai-bridge-orders-jobs.lua (loaded right after this file)
