-- ai-bridge-catalog: the bridge's ACTIONS table (every action's name and its
-- handler), DRY_OK (what a dry run may still do), DISPLAY_ONLY (what works
-- while the AI is halted) and RELEASE_WHILE_HALTED (the undoing steps that
-- still run while halted).
--
-- A part of ai-bridge.lua (r8, when the 132 KB hub was split), run by it in
-- its own environment where these lines stood in it: after the other parts
-- (BRIDGE_PARTS, whose act_* handlers the table names), before the commands.
-- What is global here is the bridge's (reachable as
-- reqscript('ai-bridge').<name>). Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-catalog is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-catalog'] = '0.105.102'   -- (0.105.26) bumped with BRIDGE_VERSION

ACTIONS = {
    join_levels = act_join_levels,
    set_rules = act_set_rules,           -- (0.105.20) logs/rules-request.json
    apply_preset = act_apply_preset,     -- (0.105.4) keeper.py --preset
    census = act_census,
    clear_webs = act_clear_webs,
    remove_webs = act_remove_webs,       -- (0.105.3)
    scrub_dead_units = act_scrub_dead_units,
    scan_entrances = act_scan_entrances,
    build_gate_doors = act_build_gate_doors,
    fortify_entrance = act_fortify_entrance,
    arm_gates = act_arm_gates,
    link_lever = act_link_lever,
    place_traps = act_place_traps,
    place_gate_lever = act_place_gate_lever,          -- (0.105.12)
    build_gatehouse = act_build_gatehouse,            -- (0.105.23)
    unstick_gate = act_unstick_gate,                  -- (0.105.32)
    location_access = act_location_access,            -- (0.105.12)
    -- (0.105.48 round 2) never while halted, by whatever path it is called
    unpause = function(a)
        if reqscript('ai-status').is_halted() then
            return {ok = false, rejected = true, halted = true,
                    error = 'the AI is halted in the game (Ctrl-Shift-H to resume)'}
        end
        return act_unpause(a)
    end,
    found_fort = act_found_fort,
    quiet_announcements = act_quiet_announcements,
    save_game = act_save_game,
    open_gates = act_open_gates,
    open_entrance = act_open_entrance,     -- (0.105.34)
    close_threatened_gates = act_close_threatened_gates,   -- (0.105.35) the watcher failing
    free_gate_jobs = act_free_gate_jobs,                   -- (0.105.35) a planned gate's suspended jobs
    setup_shelter = act_setup_shelter,
    refresh_shelter = act_refresh_shelter,       -- (0.105.26)
    set_population_cap = act_set_population_cap,
    expel_dwarf = act_expel_dwarf,
    release_prisoners = act_release_prisoners,   -- (item5) no water for the jail
    pasture = act_pasture,
    nest_boxes = act_nest_boxes,             -- (0.104.80)
    train_war = act_train_war,               -- (0.104.81)
    dig_stairwell = act_dig_stairwell,       -- (0.104.82)
    dig_way_in = act_dig_way_in,             -- (0.105.32) an emergency way in for the stranded
    guard_gate = act_guard_gate,             -- (0.104.83)
    -- (0.105.0, round 2) an army that can fight
    fix_gear_gaps = act_fix_gear_gaps, assign_quivers = act_assign_quivers, squad_bolts = act_squad_bolts,
    assign_bolts = act_assign_bolts,   -- (r2h4)
    shelter_squads = act_shelter_squads, cut_entrance = act_cut_entrance,
    gate_dogs = act_gate_dogs,               -- (0.104.83)
    make_pasture = act_make_pasture,
    import_orders = act_import_orders,
    squad_fill = act_squad_fill,
    squad_swap = act_squad_swap,          -- (0.104.65)
    pair_chairs = act_pair_chairs,        -- (0.104.77)
    recreation = act_recreation,          -- (0.104.78)
    hospital_burrow = act_hospital_burrow,   -- (0.104.167)
    calm_burrow = act_calm_burrow,           -- (0.104.169)
    -- (0.105.0) round 3: threats answered (lua/ai-threats.lua)
    fire_guard = act_fire_guard,
    prisoner_room = act_prisoner_room,
    moon_cell = act_moon_cell,
    seal_cavern = act_seal_cavern,
    accept_cups = act_accept_cups,           -- (0.104.168)
    rest_infected = act_rest_infected,       -- (0.104.168)
    traction_rest = act_traction_rest,       -- (0.105.24)
    mood_free_items = act_mood_free_items,   -- (0.105.24) a mood's forbidden or dumped materials freed
    add_doctor_post = act_add_doctor_post,   -- (0.104.168)
    squad_trim = act_squad_trim,
    squad_release = act_squad_release,
    quick_location = function(a)
        if a.kind ~= 'temple' and a.kind ~= 'tavern' then return reject('quick_location needs kind temple or tavern') end
        return reqscript('ai-builder').quick_location(a.kind, a.dry_run == true)
    end,
    assign_labor = act_assign_labor,
    appoint = act_appoint,
    place_surface = act_place_surface,
    build_crossing = act_build_crossing,
    remove_crossing = act_remove_crossing,
    place_keep = act_place_keep,
    -- (0.105.30) construction: a surface hall, the gatehouse's wing walls, soil floors finished
    place_hall = act_place_hall,
    build_wings = act_build_wings,
    floor_rooms = act_floor_rooms,
    deep_depot = act_deep_depot,                 -- (0.105.23)
    narrow_detail = act_narrow_detail,
    trim_labor = act_trim_labor,
    order_instrument = act_order_instrument,
    trim_instrument_orders = act_trim_instrument_orders,   -- (0.104.69)
    slaughter_one = act_slaughter_one,
    prune_remains = act_prune_remains,
    ledger_set = act_ledger_set,
    mark_run = act_mark_run,      -- (0.105.0) a scenario copy's run id
    make_squad = act_make_squad,
    mine_ore = act_mine_ore,
    clear_gate = act_clear_gate,
    bring_goods = act_bring_goods,
    unload_depot = act_unload_depot,
    kitchen_skill = act_kitchen_skill,
    place_slabs = act_place_slabs,
    free_slabs = act_free_slabs,
    restrict_water = act_restrict_water,
    trade_deal = act_trade_deal,
    squad_barracks = act_squad_barracks,
    call_trader = act_call_trader,
    feeder_pile = act_feeder_pile,
    idle_crafting = act_idle_crafting,
    give_trinkets = act_give_trinkets,
    house_dwarves = act_house_dwarves,   -- (0.104.168)
    furnish_liked = act_furnish_liked,   -- (E4) a piece a dwarf likes in their own room
    staff_location = act_staff_location,
    add_posts = act_add_posts,
    staff_labors = act_staff_labors,
    vacate_post = act_vacate_post,
    dismiss_alerts = act_dismiss_alerts,
    answer_petition = act_answer_petition,
    retarget_hall = act_retarget_hall,
    place_in_zone = act_place_in_zone,
    survey_water = act_survey_water,
    cistern_step = act_cistern_step,
    water_work = act_water_work,          -- (0.105.0) moat, pumps, irrigation, magma workshops
    remove_workshops = act_remove_workshops,
    open_trade = act_open_trade,
    close_trade = act_close_trade,
    close_meeting = act_close_meeting,
    answer_meeting = act_answer_meeting,  -- (0.105.0)
    send_mission = act_send_mission,      -- (0.105.24) Make contact by the World screen (lua/ai-mission-send.lua)
    keep_mousers = act_keep_mousers,      -- (0.104.168)
    water_zone = act_water_zone,
    sand_zone = act_sand_zone,
    give_room = act_give_room,
    gather_plants = act_gather_plants,
    farm_thresholds = act_farm_thresholds,
    set_farm_crops = act_set_farm_crops,   -- (0.105.5) each plot's crop set by the AI (Hammerstirred: fallow plots)
    kitchen_brewables = act_kitchen_brewables,   -- (0.100) cooking keeps brewables while drink is short
    unstick_uniforms = act_unstick_uniforms,
    break_fights = act_break_fights,
    free_stray_gear = act_free_stray_gear,   -- (0.104.58)
    assign_weapons = act_assign_weapons,     -- (0.104.60)
    assign_kit = act_assign_kit,             -- (0.105.8)
    trim_gathering = act_trim_gathering,
    squad_routine = act_squad_routine,
    set_uniform = act_set_uniform,
    petition_orders = act_petition_orders,
    adopt_uniform = act_adopt_uniform,
    set_uniform_weapon = act_set_uniform_weapon,
    allow_stone = act_allow_stone,
    quarry = act_quarry,
    polish = act_polish,
    squad_orders = act_squad_orders,
    pull_gate = act_pull_gate,
    work_order = act_work_order,
    cancel_work_order = act_cancel_work_order,
    approve_orders = act_approve_orders,
    unsuspend_orders = act_unsuspend_orders,
    unforbid_dead = act_unforbid_dead,
    allow_burial = act_allow_burial,
    bench_jobs = act_bench_jobs,
    clear_orphan_jobs = act_clear_orphan_jobs,
    order_slots = act_order_slots,
    kitchen_fat = act_kitchen_fat,
    seed_reserve = act_seed_reserve,   -- (r2h6) low seeds kept from the cooks
    convict = act_convict,
    repair_rooms = function(a) return reqscript('ai-builder').repair_rooms(a.dry_run == true) end,
    bootstrap_chair = act_bootstrap_chair,
    sync_offices = function(a) return reqscript('ai-nobles').sync_offices(a.dry_run == true) end,
    -- (0.105.41) a noble's room under its office's value: smoothed, then engraved (lua/ai-noble-demands.lua)
    polish_room = function(a)
        local id = math.tointeger(tonumber(a.zone_id))
        if not id then return {ok = false, rejected = true, error = 'polish_room needs zone_id'} end
        return reqscript('ai-noble-demands').polish_room(id, a.dry_run == true)
    end,
    tool = act_tool,
    civ_alert = act_civ_alert,
    weather_burrow = act_weather_burrow,     -- (item4) evil weather: kept in without the alarm
    start_project = act_start_project,
    farm_plots = act_farm_plots,
    place_well = act_place_well,
    furnish_project = act_furnish_project,
    free_dig_jobs = act_free_dig_jobs,
    prioritize_dig = act_prioritize_dig,
    renew_well_dig = act_renew_well_dig,      -- (0.105.31)
    -- (0.105.48, K7c) the open projects' lost shaft, stair and gallery tiles
    -- designated again (was done inside the projects report, halted or not)
    redig_projects = function(a) return reqscript('ai-builder').redig_projects(a.dry_run == true) end,
    unmark_project_dig = act_unmark_project_dig,   -- (0.105.35) a level's marker-only dig tiles made real
    seal_well_stairs = act_seal_well_stairs,
    well_shaft = act_well_shaft,
    finish_project = act_finish_project,
    park_project = act_park_project,          -- (R2 h3) a level waiting on the same pieces holds no slot
    engrave_project = act_engrave_project,
    set_culture = act_set_culture,
    set_learned = act_set_learned,
    report_status = act_report_status,
    save_memory = act_save_memory,
    cancel_project = act_cancel_project,
    -- (0.105.27) disposal: the forbidden things lying about (lua/ai-disposal.lua)
    unforbid_items = act_unforbid_items,
    mark_melt = act_mark_melt,
    mark_dump = act_mark_dump,
    empty_dump = act_empty_dump,
    set_standing_orders = act_set_standing_orders,
    place_dump = act_place_dump,
    -- (0.105.40, 13e) world cleanup: what no dwarf can clean up (lua/ai-cleanup.lua)
    cleanup_items = act_cleanup_items,
    cleanup_units = act_cleanup_units,
    cleanup_spatter = act_cleanup_spatter,
    cleanup_dead_units = act_cleanup_dead_units,
    -- (0.105.40b) the AI's own doors locked between the insane and deadly ground (lua/ai-insane.lua)
    insane_guard = function(a)
        if a.units ~= nil and type(a.units) ~= 'table' then return reject('insane_guard: units is a list of unit ids') end
        local ids
        if a.units ~= nil then
            ids = {}
            for _, id in ipairs(a.units) do
                local n = type(id) == 'number' and math.tointeger(id) or nil
                if not n then return reject('insane_guard: units is a list of unit ids') end
                table.insert(ids, n)
            end
        end
        -- (0.105.40b fix) release_only: the held locks freed, none made (run_action sets it while halted)
        return reqscript('ai-insane').guard({units = ids, release_only = a.release_only == true}, a.dry_run == true)
    end,
    -- (item3) a killer among the fort's own locked away in a cell (lua/ai-killers.lua)
    killer_cell = function(a)
        if type(a.units) ~= 'table' then return reject('killer_cell: units is a list of unit ids') end
        local ids = {}
        for _, id in ipairs(a.units) do
            local n = type(id) == 'number' and math.tointeger(id) or nil
            if not n then return reject('killer_cell: units is a list of unit ids') end
            table.insert(ids, n)
        end
        -- release_only: the thirsty and hungry let out, nobody locked in (run_action sets it while halted)
        return reqscript('ai-killers').cell({units = ids, release_only = a.release_only == true}, a.dry_run == true)
    end,
    -- (0.105.46, I2) the drink forbidden in a parched dwarf's walk group let
    -- go, the nearest first (lua/ai-thirst.lua; never with the gates shut
    -- against enemies, never near a danger)
    -- (0.105.47) one stage of the Garden fort's garden court above ground
    -- (lua/ai-builder-court.lua): {name, paths, statues, dry_run}
    place_garden_court = function(a)
        if a.name ~= nil and (type(a.name) ~= 'string' or not a.name:match("^[A-Za-z' ]+$") or #a.name > 40) then
            return reject('place_garden_court: name is a plain name (letters, spaces, apostrophes; up to 40)')
        end
        if a.paths ~= nil and type(a.paths) ~= 'boolean' then return reject('place_garden_court: paths is true or false') end
        local n = 0
        if a.statues ~= nil then
            n = type(a.statues) == 'number' and math.tointeger(a.statues) or nil
            if not n or n < 0 or n > 4 then return reject('place_garden_court: statues is 0-4') end
        end
        return reqscript('ai-builder').place_garden_court(a.dry_run == true,
            {name = a.name, paths = a.paths == true, statues = n})
    end,
    -- (r9 c1) the garden court's meeting area off while danger is about
    -- (its door locked: lock), on again once it has gone: {on, lock, dry_run}
    garden_court_meeting = function(a)
        if type(a.on) ~= 'boolean' then return reject('garden_court_meeting: on is true or false') end
        if a.lock ~= nil and type(a.lock) ~= 'boolean' then return reject('garden_court_meeting: lock is true or false') end
        return reqscript('ai-builder').garden_court_meeting(a.dry_run == true, {on = a.on, lock = a.lock == true})
    end,
    -- (0.105.95) a secrets book or scroll forbidden (on) or let go: nobody reads it (lua/ai-secrets.lua)
    forbid_secrets = function(a)
        if type(a.ids) ~= 'table' or #a.ids == 0 or #a.ids > 20 then return reject('forbid_secrets needs ids: 1-20 item ids') end
        if type(a.on) ~= 'boolean' then return reject('forbid_secrets: on is true or false') end
        return reqscript('ai-secrets').forbid(a.ids, a.on, a.dry_run == true)
    end,
    thirst_unforbid = function(a)
        local id = type(a.unit_id) == 'number' and math.tointeger(a.unit_id) or nil
        if not id then return reject('thirst_unforbid needs unit_id') end
        local max = a.max ~= nil and math.tointeger(a.max) or nil
        if a.max ~= nil and (not max or max < 1 or max > 50) then return reject('thirst_unforbid: max is 1-50') end
        return reqscript('ai-thirst').unforbid_drink(id, a.dry_run == true, max)
    end,
    -- (R1 g2) a parched dwarf's way to drink opened (the AI's walls and doors,
    -- else a dig), a patient lifted out of the hospital burrow and the water
    -- carrying counted, an "unknown" looked into (lua/ai-thirst.lua)
    thirst_way = function(a)
        local id = type(a.unit_id) == 'number' and math.tointeger(a.unit_id) or nil
        if not id then return reject('thirst_way needs unit_id') end
        local dig = a.max_dig ~= nil and math.tointeger(a.max_dig) or nil
        if a.max_dig ~= nil and (not dig or dig < 1 or dig > 60) then return reject('thirst_way: max_dig is 1-60') end
        return reqscript('ai-thirst').open_way(id, a.dry_run == true, dig)
    end,
    thirst_patient = function(a)
        local id = type(a.unit_id) == 'number' and math.tointeger(a.unit_id) or nil
        if not id then return reject('thirst_patient needs unit_id') end
        return reqscript('ai-thirst').patient_help(id, a.dry_run == true)
    end,
    thirst_probe = function(a)
        local id = type(a.unit_id) == 'number' and math.tointeger(a.unit_id) or nil
        if not id then return reject('thirst_probe needs unit_id') end
        return reqscript('ai-thirst').probe(id, a.dry_run == true)
    end,
    -- (0.105.47, R2) the training squad: made, filled with volunteers, or
    -- forgotten (lua/ai-training-squad.lua; never counted as soldiers)
    training_squad = function(a)
        local TS = reqscript('ai-training-squad')
        local dry = a.dry_run == true
        if a.mode == 'make' then return TS.make(dry, txt) end
        local sid = type(a.squad_id) == 'number' and math.tointeger(a.squad_id) or nil
        if not sid then return reject('training_squad needs squad_id (or mode make)') end
        if a.mode == 'forget' then return TS.forget(sid, dry) end
        if a.mode ~= 'fill' then return reject('training_squad: mode is make, fill or forget') end
        local n = type(a.count) == 'number' and math.tointeger(a.count) or 1
        if not n or n < 1 or n > 10 then return reject('training_squad: count is 1-10') end
        local uid = a.unit_id ~= nil and (type(a.unit_id) == 'number' and math.tointeger(a.unit_id) or false) or nil
        if uid == false then return reject('training_squad: unit_id is a unit id') end
        local avoid = {}
        for _, v in ipairs(type(a.avoid) == 'table' and a.avoid or {}) do
            local u = type(v) == 'number' and math.tointeger(v) or nil
            if u then avoid[u] = true end
        end
        return TS.fill(sid, n, dry, txt, avoid, uid)
    end,
    -- (0.105.45) a great beast sealed in a cavern lured into a pocket behind
    -- one of the AI's cavern doors and caught or shut in (lua/ai-lure.lua)
    build_lure = function(a)
        if type(a.opening) ~= 'string' then return reject('build_lure needs opening ("x,y,z")') end
        local beast = a.beast ~= nil and math.tointeger(a.beast) or nil
        if a.beast ~= nil and not beast then return reject('build_lure: beast is a unit id') end
        return reqscript('ai-lure').build_lure(a.opening, beast, a.dry_run == true)
    end,
    lure_open = function(a)
        if type(a.opening) ~= 'string' then return reject('lure_open needs opening ("x,y,z")') end
        return reqscript('ai-lure').lure_open(a.opening, a.dry_run == true)
    end,
    lure_shut = function(a)
        if type(a.opening) ~= 'string' then return reject('lure_shut needs opening ("x,y,z")') end
        return reqscript('ai-lure').lure_shut(a.opening, a.dry_run == true)
    end,
    -- (0.105.40 M5) hauling balanced: haulers added, key specialists relieved (lua/ai-hauling.lua)
    add_haulers = act_add_haulers,
    relieve_haulers = act_relieve_haulers,
    -- (0.105.40b, M6) the food store: a food pile near the kitchen and still, its barrels (lua/ai-food-store.lua)
    food_pile = act_food_pile,
    food_barrels = act_food_barrels,
    -- (0.105.41, item 2) wheelbarrows for the AI's stone piles, its feeders linked to their workshops (lua/ai-pile-links.lua)
    pile_barrows = act_pile_barrows,
    feeder_link = act_feeder_link,
    -- (0.105.41, item 4) provisions from the land: hunters, butchering and tanning orders, fruit zone, cavern farms
    hunters = act_hunters,
    food_standing = act_food_standing,
    fruit_zone = act_fruit_zone,
    cavern_farm = act_cavern_farm,
    -- (item5) siege works and the field guard (lua/ai-siege.lua): fortifications carved
    -- beside an entrance, the crossbows posted behind them, a ballista placed there
    fortify_post = function(a)
        local id = math.tointeger(tonumber(a.entrance_id))
        if not id then return reject('fortify_post needs entrance_id') end
        local n = a.max ~= nil and int_in(a.max, 1, 8) or 4
        if not n then return reject('fortify_post: max is 1-8') end
        return reqscript('ai-siege').fortify_post(id, n, a.dry_run == true)
    end,
    archer_post = function(a)
        local id = math.tointeger(tonumber(a.entrance_id))
        if not id or type(a.squads) ~= 'table' then return reject('archer_post needs entrance_id and squads') end
        local ids = {}
        for _, v in ipairs(a.squads) do
            local n = math.tointeger(tonumber(v))
            if not n then return reject('archer_post: squads is a list of squad ids') end
            table.insert(ids, n)
        end
        if #ids == 0 or #ids > 6 then return reject('archer_post: 1-6 squads') end
        return reqscript('ai-siege').archer_post(id, ids, a.dry_run == true)
    end,
    place_siege_engine = function(a)
        local id = math.tointeger(tonumber(a.entrance_id))
        if not id then return reject('place_siege_engine needs entrance_id') end
        if a.kind ~= nil and a.kind ~= 'ballista' and a.kind ~= 'catapult' then
            return reject('place_siege_engine: kind is ballista or catapult')
        end
        return reqscript('ai-siege').place_engine(id, a.kind or 'ballista', a.dry_run == true)
    end,
    place_siege_shop = function(a)
        local id = math.tointeger(tonumber(a.entrance_id))
        if not id then return reject('place_siege_shop needs entrance_id') end
        return reqscript('ai-siege').place_shop(id, a.dry_run == true)
    end,
    -- (0.105.41, item 11) syndromes and miasma (lua/ai-syndromes.lua): the syndrome-carrying
    -- spatter cleaned off the citizens and the fort's floors, the carriers kept in the
    -- hospital burrow, what rots near miasma marked for the dump under the sky
    clean_contaminants = function(a)
        for _, k in ipairs({'units', 'tiles'}) do
            if a[k] ~= nil and type(a[k]) ~= 'boolean' then return reject('clean_contaminants: ' .. k .. ' is true or false') end
        end
        local ms = a.budget_ms ~= nil and int_in(a.budget_ms, 10, 500) or nil
        if a.budget_ms ~= nil and not ms then return reject('clean_contaminants: budget_ms is 10-500') end
        return reqscript('ai-syndromes').clean({units = a.units, tiles = a.tiles, budget_ms = ms}, a.dry_run == true)
    end,
    quarantine_syndromes = function(a)
        if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('quarantine_syndromes: release is true or false') end
        local days = a.days ~= nil and int_in(a.days, 1, 56) or nil
        local max = a.max ~= nil and int_in(a.max, 1, 60) or nil
        if (a.days ~= nil and not days) or (a.max ~= nil and not max) then
            return reject('quarantine_syndromes: days 1-56, max 1-60')
        end
        return reqscript('ai-syndromes').quarantine({days = days, max = max, release = a.release == true}, a.dry_run == true)
    end,
    clear_miasma = function(a)
        local max = a.max ~= nil and int_in(a.max, 1, 200) or nil
        if a.max ~= nil and not max then return reject('clear_miasma: max is 1-200') end
        return reqscript('ai-syndromes').clear_miasma({max = max}, a.dry_run == true)
    end,
    -- (item 12) the artifacts shown: display furniture in the AI's rooms, an artifact put on it (lua/ai-artifacts.lua)
    place_display = act_place_display,
    display_artifact = act_display_artifact,
    -- (D0) the Design track: a landmark's sites, its drawing built, its next stage (ai-bridge-design.lua)
    blueprint_sites = act_blueprint_sites,
    build_blueprint = act_build_blueprint,
    landmark_step = act_landmark_step,
    -- (0.105.41) traffic zones on the AI's own finished levels, a slice a call (lua/ai-traffic.lua)
    paint_traffic = function(a)
        if a.key ~= nil and (type(a.key) ~= 'string' or #a.key > 40) then return reject('paint_traffic: key is a level key') end
        for _, k in ipairs({'max', 'budget_ms'}) do
            if a[k] ~= nil and not math.tointeger(a[k]) then return reject('paint_traffic: ' .. k .. ' is a whole number') end
        end
        return reqscript('ai-traffic').paint({key = a.key, max = a.max, budget_ms = a.budget_ms, audit = a.audit == true},
                                             a.dry_run == true)
    end,
    -- (item6) prisoners' outcomes: the AI's pit over a drop already there, caged prisoners into it (lua/ai-captives.lua)
    make_pit = function(a)
        if a.min_drop ~= nil and type(a.min_drop) ~= 'number' then return reject('make_pit: min_drop is a number') end
        return reqscript('ai-captives').make_pit({min_drop = a.min_drop}, a.dry_run == true)
    end,
    pit_prisoners = function(a)
        if type(a.ids) ~= 'table' then return reject('pit_prisoners: ids is a list of unit ids') end
        local ids = {}
        for _, id in ipairs(a.ids) do
            local n = type(id) == 'number' and math.tointeger(id) or nil
            if not n then return reject('pit_prisoners: ids is a list of unit ids') end
            table.insert(ids, n)
        end
        if #ids == 0 then return reject('pit_prisoners: no ids') end
        return reqscript('ai-captives').pit_prisoners({ids = ids, max = a.max, min_drop = a.min_drop}, a.dry_run == true)
    end,
    -- (0.105.41, item 7) spilt magma: paths round it restricted, then reclaimed once cooled (lua/ai-hazards.lua)
    magma_guard = function(a)
        local r = int_in(a.radius or 3, 1, 10)
        local jobs = int_in(a.max_jobs or 40, 0, 200)
        if not r or not jobs then return reject('magma_guard: radius 1-10, max_jobs 0-200') end
        if a.lift ~= nil and type(a.lift) ~= 'boolean' then return reject('magma_guard: lift is true or false') end
        return reqscript('ai-hazards').magma_guard(r, jobs, a.lift == true, a.dry_run == true)
    end,
    magma_reclaim = function(a)
        local cool = int_in(a.cool_ticks or 3600, 0, 403200)
        if not cool then return reject('magma_reclaim: cool_ticks 0-403200') end
        if a.dig ~= nil and type(a.dig) ~= 'boolean' then return reject('magma_reclaim: dig is true or false') end
        return reqscript('ai-hazards').magma_reclaim(cool, a.dig == true, a.dry_run == true)
    end,
    -- (item10) cavern trees felled when safe (stop: the AI's marks lifted); the grove kept (lua/ai-forestry.lua)
    cavern_logging = function(a)
        return reqscript('ai-forestry').cavern_logging(a.limit, a.dry_run == true, a.stop == true,
                                                      a.inside_only == true, a.unsafe_only == true)
    end,
    keep_grove = function(a) return reqscript('ai-forestry').keep_grove(a.dry_run == true, a.guard == true) end,
    -- (item10) a skill cap on the AI's second workshop of a kind (release: lifted) (lua/ai-benches.lua)
    bench_caps = function(a)
        if type(a.kind) ~= 'string' then return reject('bench_caps needs kind (Carpenters, Masons, ...)') end
        local B = reqscript('ai-benches')
        if a.release == true then return B.release_bench(a.kind, a.dry_run == true) end
        return B.cap_bench(a.kind, a.level, a.dry_run == true)
    end,
    -- (0.105.47, I7d) surface work kept near the gates while a great danger is about (lua/ai-near-gates.lua)
    near_gates = function(a)
        if type(a.on) ~= 'boolean' then return reject('near_gates needs on (true or false)') end
        local r = a.radius ~= nil and whole_number(a.radius) or nil
        if a.radius ~= nil and not r then return reject('near_gates: radius is a whole number of tiles') end
        return reqscript('ai-near-gates').set(a.on, r, a.dry_run == true, txt)
    end,
    -- (0.105.47, I7d) the AI's water zones on surface water taken down before the ice (lua/ai-ice.lua)
    retire_water_zones = function(a)
        return reqscript('ai-ice').retire(a.outside_only ~= false, a.dry_run == true)
    end,
    -- (0.105.45) hunting: squads sent at a beast or an enemy, and called back (lua/ai-hunt.lua)
    hunt_send = function(a)
        local tid = whole_number(a.target_id)
        if not tid then return reject('hunt_send needs target_id') end
        if type(a.squad_ids) ~= 'table' or #a.squad_ids == 0 or #a.squad_ids > 10 then
            return reject('hunt_send needs squad_ids: a list of 1-10 squad ids')
        end
        local ids = {}
        for _, v in ipairs(a.squad_ids) do
            local n = whole_number(v)
            if not n then return reject('hunt_send: squad_ids is a list of squad ids') end
            table.insert(ids, n)
        end
        return reqscript('ai-hunt').send({squad_ids = ids, target_id = tid}, a.dry_run == true)
    end,
    hunt_recall = function(a)
        local o = {reason = type(a.reason) == 'string' and a.reason or nil}
        if a.squad_ids ~= nil then
            if type(a.squad_ids) ~= 'table' or #a.squad_ids > 10 then
                return reject('hunt_recall: squad_ids is a list of 1-10 squad ids')
            end
            o.squad_ids = {}
            for _, v in ipairs(a.squad_ids) do
                local n = whole_number(v)
                if not n then return reject('hunt_recall: squad_ids is a list of squad ids') end
                table.insert(o.squad_ids, n)
            end
        end
        if a.target_id ~= nil then
            o.target_id = whole_number(a.target_id)
            if not o.target_id then return reject('hunt_recall: target_id is a unit id') end
        end
        if not (o.squad_ids and #o.squad_ids > 0) and not o.target_id then
            return reject('hunt_recall needs squad_ids or target_id')
        end
        return reqscript('ai-hunt').recall(o, a.dry_run == true)
    end,
    -- (0.105.45) the shelter away from the threat's way in: the AI shelter drawn
    -- over the levels the brain picked (clear: the whole fort again), and a
    -- squad stationed between the threat and it (lua/ai-shelter-plan.lua, ai-military station)
    shelter_pick = function(a)
        local levels
        if a.clear ~= true then
            if type(a.levels) ~= 'table' then return reject('shelter_pick needs levels (a list of z) or clear') end
            levels = {}
            for _, z in ipairs(a.levels) do
                local n = int_in(z, 0, 1000)
                if not n then return reject('shelter_pick: levels are z levels') end
                table.insert(levels, n)
            end
        end
        return reqscript('ai-shelter-plan').pick(levels, {clear = a.clear == true, why = a.why,
                                                          way_in = type(a.way_in) == 'table' and a.way_in or nil},
                                                 a.dry_run == true)
    end,
    squad_station = function(a)
        local id = whole_number(a.squad_id)
        local x, y, z = int_in(a.x, 0, 1000), int_in(a.y, 0, 1000), int_in(a.z, 0, 1000)
        if not id or not x or not y or not z then return reject('squad_station needs squad_id, x, y, z') end
        return reqscript('ai-military').station(id, x, y, z, a.dry_run == true)
    end,
    -- (0.105.45) the sweep for things stuck "in progress": an AI lever's pull
    -- job nobody does, taken off and asked afresh, or dropped (lua/ai-stuck.lua)
    stuck_reset = function(a)
        if a.kind ~= 'lever' then return reject('stuck_reset: kind is lever') end
        if a.mode ~= nil and a.mode ~= 'reissue' and a.mode ~= 'drop' then
            return reject('stuck_reset: mode is reissue or drop')
        end
        return reqscript('ai-stuck').reset({kind = a.kind, id = a.id, mode = a.mode}, a.dry_run == true)
    end,
    -- (0.105.45) kill zones at the gates and cavern openings (lua/ai-killzone.lua): traps in
    -- the 1-wide stretch inside, a drawbridge (over a channel where allowed); full cage traps
    build_killzone = function(a)
        local id = math.tointeger(tonumber(a.entrance_id))
        if not id then return reject('build_killzone needs entrance_id') end
        local n = 4
        if a.traps ~= nil then
            n = int_in(a.traps, 0, 6)
            if not n then return reject('build_killzone: traps is 0-6') end
        end
        local kind = a.kind or 'cage'
        if kind ~= 'cage' and kind ~= 'weapon' and kind ~= 'stonefall' and kind ~= 'mixed' then
            return reject('build_killzone: kind is cage, weapon, stonefall or mixed')
        end
        if a.drawbridge ~= nil and type(a.drawbridge) ~= 'boolean' then
            return reject('build_killzone: drawbridge is true or false')
        end
        return reqscript('ai-killzone').build_killzone(id, n, kind, a.drawbridge == true, a.dry_run == true)
    end,
    reset_cage_traps = function(a)
        local id = math.tointeger(tonumber(a.entrance_id))
        if not id then return reject('reset_cage_traps needs entrance_id') end
        return reqscript('ai-killzone').reset_cage_traps(id, a.dry_run == true)
    end,
    -- (0.105.46, I4) a migrant wave called to a fallen fort DF sends none to
    -- (DFHack's force Migrants; lua/ai-recovery.lua, brain/planner_recovery.py)
    call_migrants = function(a)
        return reqscript('ai-recovery').call_migrants(a.dry_run == true)
    end,
    -- (r2 h9) the merchants of a caravan stuck leaving told to walk off the map
    -- (lua/ai-recovery.lua free_caravan, brain/planner_outside.py); (0.105.97)
    -- step: walk (the default), edge (teleported to the map's edge), dismiss
    -- (DFHack's fix/stuck-merchants and caravan leave, its merchants gone)
    free_caravan = function(a)
        local id = math.tointeger(tonumber(a.entity))
        if not id then return reject('free_caravan needs entity (the caravan\'s civilisation id)') end
        return reqscript('ai-recovery').free_caravan(id, a.dry_run == true, a.step)
    end,
    -- (0.105.47, J1) a gathering strange mood's workshop and materials put in the AI
    -- shelter while the alarm is up (lua/ai-mood-help.lua; I7a: 5 moods cancelled "Forbidden area")
    mood_shelter = function(a) return reqscript('ai-mood-help').act_mood_shelter({dry_run = a.dry_run == true}) end,
    -- (0.105.47) a meeting that waits behind DF's diplomacy light opened by
    -- clicking it (lua/ai-meeting-open.lua); sent by the overseer only unattended
    open_meeting = function(a)
        return reqscript('ai-meeting-open').open(a.dry_run == true)
    end,
    -- (0.105.48, K9) DF's World screen left (lua/ai-mission-send.lua leave_world):
    -- sent by the overseer only unattended, after WORLD_CLOSE_S with the screen open
    close_world = function(a)
        return reqscript('ai-mission-send').leave_world(a.dry_run == true)
    end,
    -- (0.105.47, R2 item 3) tantrums: a calm squad stationed at a hospital zone
    -- while a tantrum is loose, or taken off again (release); a tantrum-thrower
    -- off every post they hold, the hospital labours too (lua/ai-tantrums.lua)
    hospital_guard = function(a)
        local id = whole_number(a.squad_id)
        if not id then return reject('hospital_guard needs squad_id') end
        if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('hospital_guard: release is true or false') end
        if a.release == true then return reqscript('ai-tantrums').unguard(id, a.dry_run == true) end
        local zone = whole_number(a.zone_id)
        if not zone then return reject('hospital_guard needs zone_id (or release)') end
        return reqscript('ai-tantrums').guard(id, zone, a.dry_run == true)
    end,
    tantrum_step_down = function(a)
        local id = whole_number(a.unit_id)
        if not id then return reject('tantrum_step_down needs unit_id') end
        if a.medical ~= nil and type(a.medical) ~= 'boolean' then return reject('tantrum_step_down: medical is true or false') end
        return reqscript('ai-tantrums').step_down(id, a.medical == true, a.dry_run == true, txt)
    end,
    -- (0.105.47, I7b) the dead and a cook (lua/ai-welfare.lua): coffins with a
    -- tomb each on the AI's finished levels when no tomb level comes; memorial
    -- slab orders for the dead nobody can reach; one cook kept at the kitchens
    coffins_anywhere = function(a)
        local n = int_in(a.max or 5, 1, 10)
        if not n then return reject('coffins_anywhere: max is 1-10') end
        return reqscript('ai-welfare').place_corner_coffins(n, a.dry_run == true)
    end,
    engrave_memorials = function(a)
        local n = int_in(a.max or 5, 1, 10)
        if not n then return reject('engrave_memorials: max is 1-10') end
        return reqscript('ai-welfare').engrave_memorials(n, a.dry_run == true, a.ghosts == true)   -- (r1g8) ghosts by name
    end,
    train_cook = function(a)
        if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('train_cook: release is true or false') end
        return reqscript('ai-welfare').train_cook(a.dry_run == true, a.release == true)
    end,
    -- (0.105.47) cavern wells made safe (lua/ai-well-safety.lua): the watcher,
    -- the shaft's column restricted, the door at the gallery's fort end, the
    -- next level of a shaft dug from the bottom up; a dwarf stranded under a well let out
    well_safety = function(a)
        return reqscript('ai-well-safety').step(a.dry_run == true)
    end,
    well_rescue = function(a)
        local x, y, z = math.tointeger(tonumber(a.x)), math.tointeger(tonumber(a.y)), math.tointeger(tonumber(a.z))
        if not x or not y or not z then return reject('well_rescue needs x, y, z (where the stranded stand)') end
        local pid = a.project_id ~= nil and math.tointeger(tonumber(a.project_id)) or nil
        if a.project_id ~= nil and not pid then return reject('well_rescue: project_id is a number') end
        return reqscript('ai-well-safety').rescue(x, y, z, pid, a.dry_run == true)
    end,
    -- (0.105.47) the deep plan's stair taken past the first cavern, a step at a
    -- time: a walled shaft through the cavern (lua/ai-descent.lua, brain/planner_descent.py)
    cross_cavern = function(a)
        local x, y, e = math.tointeger(tonumber(a.x)), math.tointeger(tonumber(a.y)), math.tointeger(tonumber(a.elev))
        if not x or not y or not e then return reject('cross_cavern needs x, y and elev') end
        if type(a.layer) ~= 'string' or not a.layer:match('^Cavern%d$') then
            return reject('cross_cavern: layer is Cavern1, Cavern2 or Cavern3')
        end
        return reqscript('ai-descent').cross_cavern({x = x, y = y, elev = e, layer = a.layer}, a.dry_run == true,
                                                    get_layers())
    end,
    -- (0.105.47) the herd by Husbandry (lua/ai-herd.lua, brain/planner_husbandry.py):
    -- breeders kept from the butcher, caged wild animals tamed, hunting
    -- training, DFHack's autobutcher targets
    herd_breeders = function(a)
        local f = int_in(a.females, 0, 12)
        if not f then return reject('herd_breeders needs females 0-12') end
        return reqscript('ai-herd').keep_breeders(f, a.dry_run == true, txt)
    end,
    tame_wild = function(a)
        local n = int_in(a.max, 1, 10)
        if not n then return reject('tame_wild needs max 1-10') end
        return reqscript('ai-herd').tame(n, a.dry_run == true, txt, a.predators == true)   -- (r9) large predators too
    end,
    train_hunt = function(a)
        local n = int_in(a.max, 1, 6)
        if not n then return reject('train_hunt needs max 1-6') end
        return reqscript('ai-herd').train_hunt(n, a.dry_run == true, txt)
    end,
    herd_targets = function(a)
        local t = {}
        for _, k in ipairs({'fk', 'mk', 'fa', 'ma'}) do
            t[k] = int_in(a[k], 0, 50)
            if not t[k] then return reject('herd_targets needs fk, mk, fa, ma 0-50') end
        end
        return reqscript('ai-herd').set_targets(t, a.dry_run == true)
    end,
    -- (0.105.47) one way off the map opened for a mission's travellers (the
    -- AI's own shut gate, by ai-gates open_entrance and its refusals), held
    -- open a day against the watcher's pre-emptive shut (lua/ai-mission-way.lua)
    mission_way = function(a)
        local id = int_in(a.id, 0, 100000000)
        if not id then return reject('mission_way needs the entrance id') end
        local key = type(a.mission) == 'string' and a.mission:sub(1, 40) or 'mission'
        return reqscript('ai-mission-way').open_way(id, key, a.dry_run == true)
    end,
    -- (0.105.47, J16) the way out: one surface entrance opened by the AI's own
    -- levers and locks (the player's gates never), and the fort left open when
    -- the AI stops with no enemy in reach (lua/ai-way-out.lua)
    way_out_open = function(a)
        local id = int_in(a.id, 0, 100000000)
        if not id then return reject('way_out_open needs the entrance id') end
        return reqscript('ai-way-out').open_way(id, {dry_run = a.dry_run == true, instant = a.instant == true})
    end,
    way_out_leave = function(a)
        return reqscript('ai-way-out').leave(a.dry_run == true)
    end,
    -- (0.105.47, J17) a raid party's pets: let out of the AI's own zone for the
    -- trip (op release, pet_ids), put back once home (op restore) (lua/ai-raids.lua)
    mission_pets = function(a)
        local R = reqscript('ai-raids')
        if a.op == 'restore' then return R.restore_pets(a.dry_run == true) end
        if a.op ~= 'release' then return reject('mission_pets: op is release or restore') end
        if type(a.pet_ids) ~= 'table' then return reject('mission_pets release needs pet_ids') end
        local ids = {}
        for i = 1, 13 do
            local v = a.pet_ids[i]
            if v == nil then break end
            if i > 12 then return reject('mission_pets: at most 12 pets') end
            local n = int_in(v, 0, 100000000)
            if not n then return reject('mission_pets: pet_ids is a list of unit ids') end
            table.insert(ids, n)
        end
        if #ids == 0 then return reject('mission_pets release needs pet_ids') end
        return R.release_pets(ids, a.dry_run == true)
    end,
}

-- (13c) The actions whose dry run changes nothing in the fort, all the way
-- down: their dry runs get through while the AI is halted (cmd_act). A new
-- action whose dry run is read-only goes here too. (Was a chain of names kept
-- by hand in cmd_act; farm_thresholds, unstick_uniforms and set_rules were
-- missing.) (0.105.26) Only these take a dry run at all: cmd_act refuses
-- dry_run for any other action, as their handlers ignored it and acted for
-- real. The second list was checked handler by handler (each one's dry run
-- returns before it changes anything); unpause, pull_gate and narrow_detail
-- (its widen writes before its dry-run return) are not on it.
DRY_OK = {}
for _, name in ipairs({
    'start_project', 'farm_plots', 'place_well', 'make_pasture', 'link_lever', 'save_game',
    'quiet_announcements', 'found_fort', 'assign_labor', 'gather_plants', 'trim_gathering', 'appoint',
    'place_surface', 'place_keep', 'deep_depot', 'make_squad', 'mine_ore', 'clear_gate', 'bring_goods',
    'unload_depot', 'kitchen_skill', 'place_slabs', 'give_room', 'set_uniform', 'adopt_uniform',
    'petition_orders', 'set_uniform_weapon', 'allow_stone', 'prioritize_dig', 'renew_well_dig', 'redig_projects', 'convict', 'quarry', 'polish',
    'trade_deal', 'call_trader', 'open_trade', 'close_trade', 'squad_barracks', 'feeder_pile',
    'idle_crafting', 'give_trinkets', 'staff_location', 'vacate_post', 'add_posts', 'staff_labors',
    'dismiss_alerts', 'place_in_zone', 'answer_petition', 'retarget_hall', 'remove_workshops',
    'survey_water', 'cistern_step', 'water_zone', 'sand_zone', 'water_work', 'set_farm_crops',
    'kitchen_brewables', 'farm_thresholds', 'unstick_uniforms', 'set_rules',
    -- (0.105.26) honoured all the way down, not listed before
    'accept_cups', 'add_doctor_post', 'allow_burial', 'answer_meeting', 'apply_preset', 'approve_orders',
    'assign_kit', 'assign_quivers', 'assign_weapons', 'bench_jobs', 'bootstrap_chair', 'break_fights',
    'build_crossing', 'build_gatehouse', 'calm_burrow', 'clear_orphan_jobs', 'clear_webs', 'close_meeting',
    'cut_entrance', 'dig_stairwell', 'fire_guard', 'fix_gear_gaps', 'free_slabs', 'free_stray_gear',
    'gate_dogs', 'guard_gate', 'hospital_burrow', 'house_dwarves', 'furnish_liked', 'join_levels', 'keep_mousers',
    'kitchen_fat', 'seed_reserve', 'ledger_set', 'location_access', 'mark_run', 'mood_free_items', 'moon_cell', 'nest_boxes',
    'order_instrument', 'order_slots', 'pair_chairs', 'place_gate_lever', 'prisoner_room', 'prune_remains',
    'quick_location', 'recreation', 'remove_crossing', 'remove_webs', 'repair_rooms', 'rest_infected',
    'restrict_water', 'scrub_dead_units', 'seal_cavern', 'seal_well_stairs', 'send_mission', 'shelter_squads',
    'slaughter_one', 'squad_bolts', 'assign_bolts', 'squad_release', 'squad_swap', 'squad_trim', 'sync_offices',
    'traction_rest', 'train_war', 'trim_instrument_orders', 'trim_labor', 'unforbid_dead',
    'unsuspend_orders', 'well_shaft',
    'refresh_shelter',   -- (0.105.26)
    'weather_burrow',    -- (item4) its dry run counts who would be kept in
    'polish_room',       -- (0.105.41) a noble's room smoothed or engraved
    -- (0.105.27) disposal: each dry run returns before it changes anything
    'unforbid_items', 'mark_melt', 'mark_dump', 'empty_dump', 'set_standing_orders', 'place_dump',
    -- (0.105.30) construction: each plans and returns before it places anything
    'place_hall', 'build_wings', 'floor_rooms',
    'open_entrance',     -- (0.105.34) its dry run checks the distance and changes nothing
    'close_threatened_gates', 'free_gate_jobs',   -- (0.105.35) each dry run only counts
    'unstick_gate',      -- (0.105.32) its dry run says what it would do, and changes nothing
    -- (0.105.32) the way in: planned (and quickfort's dry run) before anything is designated
    'dig_way_in',
    'unmark_project_dig',   -- (0.105.35) its dry run counts the marked tiles and changes nothing
    -- (D0) each checks the drawing (and quickfort's dry run) before it designates or places anything
    'build_blueprint', 'landmark_step',
    -- (0.105.40) world cleanup: each dry run counts and returns before it removes anything
    'cleanup_items', 'cleanup_units', 'cleanup_spatter', 'cleanup_dead_units',
    'insane_guard',   -- (0.105.40b) its dry run counts the doors and changes nothing
    'killer_cell',    -- (item3) its dry run finds the rooms and changes nothing
    'shelter_pick', 'squad_station',   -- (0.105.45) each dry run checks and changes nothing
    'stuck_reset',    -- (0.105.45) its dry run counts the lever's pull jobs and changes nothing
    'build_lure', 'lure_open', 'lure_shut',   -- (0.105.45) each dry run plans or checks and changes nothing
    'add_haulers', 'relieve_haulers',   -- (0.105.40 M5) each dry run names the dwarves and changes nothing
    -- (0.105.40b, M6) the food store: each dry run finds the spot (quickfort's dry run) and changes nothing
    'food_pile', 'food_barrels',
    'pile_barrows', 'feeder_link',   -- (0.105.41, item 2) each dry run checks the pile and changes nothing
    'paint_traffic',   -- (0.105.41) its dry run counts the tiles and paints none
    -- (0.105.41, item 4) provisions: each dry run names or finds (quickfort's dry run) and changes nothing
    'hunters', 'food_standing', 'fruit_zone', 'cavern_farm',
    -- (item5) each dry run surveys (and quickfort's dry run) and changes nothing
    'fortify_post', 'archer_post', 'place_siege_engine', 'place_siege_shop',
    'make_pit', 'pit_prisoners',   -- (item6) each dry run finds and checks, and changes nothing
    'magma_guard', 'magma_reclaim',   -- (0.105.41, item 7) each dry run counts and changes nothing
    'cavern_logging', 'keep_grove', 'bench_caps',   -- (item10) each dry run counts and changes nothing
    -- (0.105.41, item 11) each dry run counts (and names) and changes nothing
    'clean_contaminants', 'quarantine_syndromes', 'clear_miasma',
    'place_display', 'display_artifact',   -- (item 12) each dry run checks and returns before it builds or makes a job
    'hunt_send', 'hunt_recall',   -- (0.105.45) each dry run checks the target and squads, and gives no order
    'build_killzone', 'reset_cage_traps',   -- (0.105.45) each dry run plans (or counts) and places nothing
    'thirst_unforbid',   -- (0.105.46, I2) its dry run counts the drinks and lets none go
    'forbid_secrets',    -- (0.105.95) its dry run changes no flag
    'thirst_way', 'thirst_patient', 'thirst_probe',   -- (R1 g2) each dry run plans or counts and changes nothing
    'call_migrants',   -- (0.105.46, I4) its dry run names the script and queues nothing
    'free_caravan',    -- (r2 h9) its dry run counts the merchants and tells none to leave; (0.105.97) moves none,
                       -- runs only fix/stuck-merchants -n
    'mood_shelter',    -- (0.105.47, J1) its dry run counts the tiles and adds none
    'open_meeting',    -- (0.105.47) its dry run finds the diplomacy light and clicks nothing
    'close_world',     -- (0.105.48, K9) its dry run says whether the World screen would be left, and presses nothing
    'hospital_guard', 'tantrum_step_down',   -- (0.105.47) each dry run checks and changes nothing
    'training_squad',   -- (0.105.47) its dry run names the leader or counts the places and changes nothing
    'coffins_anywhere', 'engrave_memorials', 'train_cook',   -- (0.105.47) each dry run finds and names, and changes nothing
    'well_safety', 'well_rescue',   -- (0.105.47) each dry run plans and checks, and changes nothing
    'near_gates', 'retire_water_zones',   -- (0.105.47, I7d) each dry run counts and changes nothing
    'cross_cavern',    -- (0.105.47) its dry run plans the step (quickfort's dry run) and marks nothing
    -- (0.105.47) the herd: each dry run counts (and names) and changes nothing
    'herd_breeders', 'tame_wild', 'train_hunt', 'herd_targets',
    'place_garden_court',   -- (0.105.47) its dry run finds the site (quickfort's dry run) and places nothing
    'garden_court_meeting',   -- (r9 c1) its dry run reads the zone and the door and switches nothing
    'mission_way',   -- (0.105.47) its dry run is open_entrance's (checks the distance) and holds nothing
    'mission_pets',  -- (0.105.47, J17) its dry run names the pets and moves none
    'way_out_open', 'way_out_leave',   -- (0.105.47, J16) each dry run says what it would pull or unlock and changes nothing
    'park_project',   -- (y2) its dry run checks the level and its sig and saves nothing
}) do DRY_OK[name] = true end

-- These only change what's displayed, so they still work while halted, dry
-- run or not. (save_memory, ledger_set and (0.105.0) mark_run are the AI's own
-- bookkeeping, not a change to the fort; (0.105.4) apply_preset sets the
-- player's settings (keeper --preset), not the fort.)
DISPLAY_ONLY = {report_status = true, set_culture = true, set_learned = true, save_memory = true,
                ledger_set = true, mark_run = true, apply_preset = true,
                -- (D0) changes no tile: the sites it finds are kept in the AI's own site data
                blueprint_sites = true}

-- (0.105.40b fix) Actions that, while halted, still run their undoing step
-- alone (the field set true): the insane guard frees the doors it locked (a
-- lock left on while the AI is halted could shut a dwarf in), and locks none.
-- (item3) the killer cells let the thirsty and hungry out, and lock nobody in.
RELEASE_WHILE_HALTED = {insane_guard = 'release_only', killer_cell = 'release_only',
                        lure_shut = 'while_halted',   -- (0.105.45, merge) shutting a lure pocket is always safe
                        -- (0.105.48, K3) the AI's alarm and burrows: only lowered and
                        -- emptied (the handlers refuse the raising and the moving in);
                        -- the way out's leave only opens, lowers and lets out
                        civ_alert = 'release_only', weather_burrow = 'release_only',
                        recreation = 'release_only', hospital_burrow = 'release_only',
                        calm_burrow = 'release_only', way_out_leave = 'release_only'}
