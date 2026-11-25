-- ai-bridge-sections: the fort report's SECTIONS (each section's reader, run
-- through `safe`: one that fails leaves its error in its place), fort_key,
-- the deep hazard section, PULSE_SECTIONS and TIERS, and the section cache
-- (SECTION_CACHE_DAYS, SECTION_MAX_DAYS, CACHE_INVALIDATES, SECTION_CACHE).
--
-- A part of ai-bridge.lua (r8, when the 132 KB hub was split), run by it in
-- its own environment where these lines stood in it: after the version and
-- modules commands, before build_state and the other commands. What is
-- global here is the bridge's (reachable as reqscript('ai-bridge').<name>).
-- Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-sections is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-sections'] = '0.105.114'   -- (0.105.26) bumped with BRIDGE_VERSION

-- Run one section of the report; if it fails, keep the rest of the report
-- and put the error where that section would have been.
local function safe(fn, ...)
    local ok, result = pcall(fn, ...)
    if ok then return result end
    return {error = tostring(result)}
end

-- (0.105.33) which fort a per-site memory belongs to, so a save of the same
-- site id (another world) loaded in the same DF session is not taken for the
-- fort seen before. (r1g9) The world and the site (ai-util fort_id), not the
-- save folder: DF's seasonal autosave renames it (autosave 1, 2, 3), and every
-- cached section was rebuilt each season; another copy of the same world is
-- told apart by SC_MAP_UNLOADED (the caches are emptied then)
function fort_key()
    local ok, v = pcall(function() return reqscript('ai-util').fort_id() end)
    if ok and type(v) == 'string' then return v end
    local okd, dir = pcall(function() return df.global.world.cur_savegame.save_dir end)
    return tostring(okd and dir or '?') .. '#' .. tostring(df.global.plotinfo.site_id)
end

-- The report's sections: name -> function(ctx) returning that section.
-- ctx.dwarves / ctx.units come from one get_dwarves call shared by both.
-- (0.105.40b) the deep section's deep_hazard: around the citizens' middle,
-- with the Rules switch mine_adamantine (reserved: still refused)
function deep_hazard_section()
    local near
    pcall(function()
        local cs = dfhack.units.getCitizens()
        if #cs > 0 then
            local sx, sy, sz = 0, 0, 0
            for _, u in ipairs(cs) do sx, sy, sz = sx + u.pos.x, sy + u.pos.y, sz + u.pos.z end
            near = {x = sx // #cs, y = sy // #cs, z = sz // #cs}
        end
    end)
    local okm, mine = pcall(function() return reqscript('ai-overseer-settings').load_settings().mine_adamantine end)
    -- (0.105.40b fix) once per loaded map: the AI's own digs on refused tiles taken back
    pcall(function() reqscript('ai-builder').dig_guard_sweep() end)
    return reqscript('ai-util').deep_hazard(near, okm and mine == true)
end

SECTIONS = {   -- (0.100) a module field: the tests swap in their own
    bridge_version = function() return BRIDGE_VERSION end,
    -- (0.105.33) the plain reads are wrapped too: one throw used to lose the whole report
    paused = function() return safe(function() return df.global.pause_state end) end,
    fort = function()
        return safe(function()
            local okw, world = pcall(function() return txt(translate_name(df.global.world.world_data.name)) end)
            local okn, name = pcall(function()
                return txt(translate_name(df.world_site.find(df.global.plotinfo.site_id).name, true))
            end)
            return {save_dir = df.global.world.cur_savegame.save_dir,
                    site_id = df.global.plotinfo.site_id,
                    world = okw and world or nil,
                    name = okn and name or nil,
                    run_id = run_mark()}       -- (0.105.0) a scenario copy's mark, or nil
        end)
    end,
    date = function() return safe(get_date) end,
    wealth = function() return safe(function() return df.global.plotinfo.tasks.wealth.total end) end,
    dwarves = function(ctx) return ctx.dwarves end,
    units = function(ctx) return ctx.units end,
    stocks = function() return safe(get_stocks) end,
    supplies = function() return safe(get_supplies) end,
    dead = function() return safe(get_dead) end,
    -- (0.104.20) rooms whose walls were dug open
    room_gaps = function() return safe(function() return reqscript('ai-builder').room_gaps_report() end) end,
    planned = function() return safe(function() return reqscript('ai-builder').planned_report() end) end,   -- (0.104.154)
    justice = function() return safe(get_justice) end,
    society = function() return safe(get_society) end,
    entrances = function() return safe(function() return reqscript('ai-gates').summary() end) end,
    military = function() return safe(function() return reqscript('ai-military').report(txt) end) end,
    moods = function() return safe(get_moods) end,
    buildings = function() return safe(get_buildings) end,
    jobs = function() return safe(get_jobs) end,
    -- (0.105.40b) the threats that breathe fire marked (lua/ai-threats.lua, by their raws)
    others_on_map = function() return safe(function()
        local o = get_others_on_map()
        local okf, nf = pcall(function() return reqscript('ai-threats').mark_fire_breathers(o) end)
        -- (fix41-ff) with a fire breather about: which of them stand at the
        -- fort's walls (the crossbows' only targets; brain/planner_firebreath.py)
        if okf and type(nf) == 'number' and nf > 0 then
            pcall(function()
                local ids = {}
                for _, t in ipairs(o.threats) do if t.fire_breather then ids[#ids + 1] = t.id end end
                o.intruders_at_walls = reqscript('ai-gates').intruders_at_walls(ids)
            end)
        end
        return o
    end) end,
    -- (0.105.40b) with `deep_hazard`: raw adamantine uncovered and the dig
    -- guard's refusals (lua/ai-util.lua deep_hazard; brain/planner_deep.py)
    deep = function() return safe(function()
        local d = get_deep()
        if type(d) == 'table' then
            pcall(function() d.deep_hazard = deep_hazard_section() end)
        end
        return d
    end) end,
    -- (0.104.95, 13b) the fort's world-map missions, read only (lua/ai-missions.lua)
    -- (0.105.24) with `send`: the World-screen sender's run under way and its last outcome
    missions = function() return safe(function()
        local r = reqscript('ai-missions').report()
        local oks, send = pcall(function() return reqscript('ai-mission-send').status() end)
        if oks then r.send = send end
        return r
    end) end,
    needs = function() return safe(get_needs) end,
    hazards = function() return safe(get_hazards) end,
    -- (0.105.0) round 3: fire places, prisoners, thieves, undead, werebeasts, the wounded (lua/ai-threats.lua)
    threats = function() return safe(function() return reqscript('ai-threats').survey(txt) end) end,
    health = function() return safe(get_health) end,
    -- (0.104.168) the infected: untreated, bleeding, beds free (lua/ai-health.lua)
    infection = function() return safe(function() return reqscript('ai-health').survey(txt) end) end,
    -- the last water survey (lua/ai-water.lua), from the save: no scan here
    water = function()
        return safe(function()
            -- (0.105.38 third review) a copy without the river's blocks (kept
            -- in the save for a frozen river later, not sent to the brain)
            local w = reqscript('ai-water').report_copy()
            -- a survey under way (in slices): the planner asks for the next slice
            if reqscript('ai-water').scanning() or WATER_PLAN then w.scanning = true end
            local okc, st = pcall(function() return reqscript('ai-builder').cistern_status() end)
            w.cistern_status = okc and st or nil
            return w
        end)
    end,
    -- (0.105.0) the water works and magma workshops: each one's stage, and the refusals
    waterworks = function() return safe(function() return reqscript('ai-waterworks').report() end) end,
    -- (13c) a feeder or storage survey that failed is not kept for 3 days
    -- (the second value: don't cache), only the next report tries it again
    logistics = function()
        local r = safe(function()
            local B = reqscript('ai-builder')
            local okf, feeders = pcall(B.feeder_survey)
            local oks, storage = pcall(B.storage_survey)
            local counts = {}
            pcall(function()
                counts.items = #df.global.world.items.all
                counts.units = #df.global.world.units.active
                local n, link = 0, df.global.world.jobs.list.next
                while link do n = n + 1; link = link.next end
                counts.jobs = n
            end)
            return {feeders = okf and feeders or {error = tostring(feeders):sub(1, 160)},
                    storage = oks and storage or {error = tostring(storage):sub(1, 160)},
                    counts = counts}
        end)
        return r, r.error == nil and (type(r.feeders) == 'table' and r.feeders.error ~= nil
                                      or type(r.storage) == 'table' and r.storage.error ~= nil)
    end,
    map = function()
        local okh, size, off = pcall(function()
            -- add to a z-level to get the elevation the game shows on screen
            return {dfhack.maps.getTileSize()}, df.global.world.map.region_z - 100
        end)
        return {
            size = okh and size or nil,
            elevation_offset = okh and off or nil,
            error = (not okh) and tostring(size) or nil,   -- (0.105.33) the header failed: said
            layers = safe(layers_summary),
            dwarves = safe(get_dwarf_levels),
        }
    end,
    nobles = function() return safe(get_nobles) end,
    mandates = function() return safe(get_mandates) end,
    civ_alert = function() return safe(function() return df.global.plotinfo.alerts.civ_alert_idx ~= 0 end) end,
    -- Read directly: gui/civ-alert's can_sound_alarm() creates alert
    -- entries when they're missing, and a report must not change the game.
    civ_alert_ready = function()
        return safe(function()
            local l = df.global.plotinfo.alerts.list
            return (#l >= 2 and #l[1].burrows > 0)
                or df.global.plotinfo.alerts.civ_alert_idx ~= 0
        end)
    end,
    -- (0.105.36 fix) whose burrow the civilian alert sends citizens to: 'ai'
    -- (the AI shelter only), 'player' (a burrow of the player's), 'none'.
    -- Read directly, as civ_alert_ready (nothing created)
    civ_alert_shelter = function()
        return safe(function()
            local l = df.global.plotinfo.alerts.list
            if #l < 2 or #l[1].burrows == 0 then return 'none' end
            local names = {}
            for _, b in ipairs(df.global.plotinfo.burrows.list) do names[b.id] = tostring(b.name):lower() end
            for _, id in ipairs(l[1].burrows) do
                if names[id] ~= 'ai shelter' then return 'player' end
            end
            return 'ai'
        end)
    end,
    orders = function() return safe(get_orders) end,
    -- (0.101.6) why orders don't start (get_order_desk)
    order_desk = function() return safe(get_order_desk) end,
    stone_types = function() return safe(get_stone_types) end,
    -- stone the masons may use, and the economic stone lying about
    stone_use = function() return safe(get_stone_use) end,
    locations = function() return safe(get_locations) end,
    petitions = function() return safe(get_petitions) end,
    diplomacy = function() return safe(get_diplomacy) end,
    meetings = function() return safe(get_meetings) end,
    -- (0.105.0, 12b) the world outside: civs at war or peace, sieges, tribute,
    -- the caravans' trade agreements, the meeting screen (lua/ai-diplomacy.lua)
    world = function() return safe(function() return reqscript('ai-diplomacy').world_report(txt) end) end,
    -- (0.88) the alert icons down the left of the screen, by type (lua/ai-reports.lua)
    alerts = function() return safe(function() return reqscript('ai-reports').alerts_report() end) end,
    projects = function() return safe(function() return reqscript('ai-builder').projects_report() end) end,
    -- every AI project on record, with where it is (small: ids and boxes)
    registry = function() return safe(function() return reqscript('ai-builder').registry_report() end) end,
    -- (D0) the Design track's landmarks: name, purpose, status, stage, levels (ai-bridge-design.lua)
    landmarks = function() return safe(get_landmarks) end,
    farms = function() return safe(function() return reqscript('ai-builder').farms_report() end) end,
    -- (0.101) water on the surface and the crossings over it (weekly: slow, changes slowly)
    crossings = function() return safe(function() return reqscript('ai-builder').crossings_report() end) end,
    -- a fresh embark: has the fort a staircase yet (lua/ai-builder.lua found_fort)?
    founding = function()
        return safe(function()
            -- (0.100) a fort with its staircase keeps it: the scan (up to 12
            -- levels across the fort, ~12 ms a report) runs until it's found,
            -- then not again this session for that site
            -- (0.105.33) keyed by save and site, and forgotten when the map
            -- unloads: a fresh copy of a site seen earlier is scanned again
            local site = fort_key()
            if FOUNDED_SITE == site then return {stairs = true, near = FOUNDED_NEAR} end
            local B = reqscript('ai-builder')
            local c = B.found_center()
            local stairs = B.has_staircase()
            if stairs then FOUNDED_SITE, FOUNDED_NEAR = site, c and c.what or nil end
            return {stairs = stairs, near = c and c.what or nil}
        end)
    end,
    -- who digs: miners, picks, digging waiting (lua/ai-labor.lua)
    labor = function() return safe(function() return reqscript('ai-labor').survey() end) end,
    -- caravans, the depot and goods for it (lua/ai-trade.lua)
    trade = function() return safe(function() return reqscript('ai-trade').survey(txt) end) end,
    -- uncovered ore near the fort, by metal (lua/ai-industry.lua)
    -- (0.105.46, I6) while its sliced vein walk is under way the copy isn't kept (true)
    industry = function()
        local ok, v, nocache = pcall(function() return reqscript('ai-industry').survey() end)
        if not ok then return {error = tostring(v)} end
        return v, nocache
    end,
    -- the fort's offices: holders, vacancies (lua/ai-nobles.lua)
    offices = function() return safe(function() return reqscript('ai-nobles').survey(txt) end) end,
    -- the rooms the nobles' offices ask for and don't have (lua/ai-nobles.lua)
    noble_rooms = function() return safe(function() return reqscript('ai-nobles').rooms_survey(txt) end) end,
    -- (0.105.41) each noble's title and the value each room must reach against its own (lua/ai-noble-demands.lua)
    noble_demands = function() return safe(function() return reqscript('ai-noble-demands').survey(txt) end) end,
    -- (0.104.168) the households: who has a bedroom, couples in one room or two, who slept rough (lua/ai-homes.lua)
    homes = function() return safe(function() return reqscript('ai-homes').census(nil, txt) end) end,
    -- (E4) the citizens' personalities, dreams and likes, summed (lua/ai-homes.lua citizens_taste)
    citizens_taste = function() return safe(function() return reqscript('ai-homes').citizens_taste(nil, txt) end) end,
    tools = function() return safe(get_tools) end,
    -- the player's settings from the control panel (gui/ai-overseer)
    settings = function()
        return safe(function()
            local S = reqscript('ai-overseer-settings')
            local out = S.for_ai(S.load_settings())
            out.preset = S.current_preset()     -- (0.105.4) the preset last applied (window or keeper)
            return out
        end)
    end,
    events_waiting = function() return #EVENT_QUEUE end,
    -- (0.104.0) the AI's ledger, as saved with this game
    ledger = function() return safe(ledger_data) end,
    recent_announcements = function() return safe(get_recent_announcements, 15) end,
    -- (0.105.27) the dump zones, the melt and dump marks, the smelters, the
    -- seal and the siege (lua/ai-disposal.lua); cached a day, cleared by the
    -- disposal actions
    disposal = function() return safe(function() return reqscript('ai-disposal').report() end) end,
    -- (0.105.40, 13e) world cleanup: items by state, the unreachable ones and
    -- creatures and for how long, spatter, the dead units (lua/ai-cleanup.lua).
    -- Not in SECTION_CACHE_DAYS: the module walks in slices of its own budget
    -- (a pass spans many reports; a new one starts a game day after the last
    -- started at the soonest) and sends its last finished pass between
    cleanup = function() return safe(function() return reqscript('ai-cleanup').report() end) end,
    -- (0.105.40b) the fort's insane (melancholy, raving, berserk, catatonic):
    -- where, the deadly ground near them, the AI's doors locked for them; the
    -- citizens whose stress heads that way (lua/ai-insane.lua; in the pulse)
    insane = function() return safe(function() return reqscript('ai-insane').report() end) end,
    -- (item3) a killer among the fort's own: cursed citizens and residents
    -- (vampires, werebeasts), the living who killed the fort's people (DF's
    -- incidents and crimes), with a confidence each; the AI's cells (lua/ai-killers.lua)
    killers = function() return safe(function() return reqscript('ai-killers').report() end) end,
    -- (0.105.45) the AI's own things stuck "in progress": projects, the cistern,
    -- waterworks, its levers' pull jobs, kill orders on targets gone, its work
    -- orders, gates planned; each with the tick it entered its state and its
    -- progress (lua/ai-stuck.lua; the daily report)
    stuck = function() return safe(function() return reqscript('ai-stuck').report() end) end,
    -- (0.105.45) the lure pockets behind the AI's cavern doors: each one's
    -- pieces, its beast and its phase; the openings a pocket fits behind
    -- (planned once a game day); the great dangers and whether traps catch them (lua/ai-lure.lua)
    lures = function() return safe(function() return reqscript('ai-lure').report() end) end,
    -- (0.105.41) traffic zones: the AI's finished levels waiting for their
    -- traffic, the one in progress, the next recheck (lua/ai-traffic.lua; the
    -- project records only, no tile read)
    traffic = function() return safe(function() return reqscript('ai-traffic').report() end) end,
    -- (item6) caged prisoners one by one and the AI's pit; a necromancer siege's facts (lua/ai-captives.lua)
    captives = function() return safe(function() return reqscript('ai-captives').report(txt) end) end,
    necro = function() return safe(function() return reqscript('ai-captives').necro(txt) end) end,
    -- (fix41) evil weather on its own (it was in threats, read once a day): in the pulse too
    weather = function() return safe(function() return reqscript('ai-threats').weather_section() end) end,
    -- (0.105.41, item 7) spilt magma, cave-ins, frost and heat (lua/ai-hazards.lua; in the pulse too:
    -- the magma read each time, the rest every few hours)
    env_hazards = function() return safe(function() return reqscript('ai-hazards').report() end) end,
    -- (0.105.40 M5) hauling: the haul jobs waiting and how long, the haulers,
    -- the key specialists who haul, the details carrying it (lua/ai-hauling.lua)
    hauling = function() return safe(function() return reqscript('ai-hauling').report(txt) end) end,
    -- (0.105.40b, M6) the food store: the piles that take food (barrels, size,
    -- fullness, the AI's own), the kitchens and stills, the food lying out of
    -- piles and barrels and the rotten (lua/ai-food-store.lua; cached a day)
    food_store = function() return safe(function() return reqscript('ai-food-store').report() end) end,
    -- (0.105.41, item 2) the wheelbarrows (owned, held by piles, wanted), the
    -- AI's stone piles and its feeder piles' links (lua/ai-pile-links.lua; cached a day)
    pile_links = function() return safe(function() return reqscript('ai-pile-links').report() end) end,
    -- (0.105.41, item 4) provisions from the land: game and hunters, butchery and
    -- tanning, fruit trees and their zones, meals by kind, cavern farms (lua/ai-provisions.lua)
    provisions = function() return safe(function() return reqscript('ai-provisions').report() end) end,
    -- (item5) siege works: each entrance's fortifications and posts, the siege engines,
    -- their parts and arrows, the operators (lua/ai-siege.lua; cached a day)
    siege = function() return safe(function() return reqscript('ai-siege').report() end) end,
    -- (item5) hostiles near a caravan's merchants, hostile wild animals near the
    -- dwarves outside (lua/ai-siege.lua; in the pulse)
    field_watch = function() return safe(function() return reqscript('ai-siege').field_watch(txt) end) end,
    -- (0.105.45) kill zones: per entrance the 1-wide stretch inside, the AI's traps there (built,
    -- full cages), its drawbridge, the fortifications; the enemies and whether DF's traps work
    -- on them (TRAPAVOID); mechanisms, trap weapons (lua/ai-killzone.lua; cached a day)
    killzones = function() return safe(function() return reqscript('ai-killzone').report(txt) end) end,
    -- (0.105.46, I4) whether a migrant wave can be called to a fallen fort: the force
    -- script, waves queued, DFHack's own hermit tool (lua/ai-recovery.lua)
    migration = function() return safe(function() return reqscript('ai-recovery').report() end) end,
    -- (item9) paper from plants, scrolls and codices for the library (lua/ai-paper.lua)
    -- (fix6) not cached while a paper step's order is open: the report after
    -- it is done reads afresh what it used (a day-old copy ordered it again)
    paper = function()
        local v = safe(function() return reqscript('ai-paper').report() end)
        local oko, open = pcall(function() return reqscript('ai-paper').orders_open() end)
        return v, (oko and open) or nil
    end,
    -- (item10) the trees by where they stand, cavern layers and their dangers, the grove (lua/ai-forestry.lua;
    -- its tree census rebuilt once a game day, the dangers read each report)
    forestry = function() return safe(function() return reqscript('ai-forestry').report() end) end,
    -- (item10) the AI's workshops of a kind, their skill caps, the labour's skills (lua/ai-benches.lua)
    benches = function() return safe(function() return reqscript('ai-benches').report() end) end,
    -- (item10) the soldiers' empty leather uniform entries and the free leather gear (lua/ai-leather-gear.lua)
    leather_gear = function() return safe(function() return reqscript('ai-leather-gear').report() end) end,
    -- (0.105.41, item 11) the citizens' syndromes (names, routes, deadly effects, sources),
    -- the carriers of a contact syndrome, the fort's floors walked in slices for
    -- syndrome spatter, the quarantine (lua/ai-syndromes.lua)
    syndromes = function() return safe(function() return reqscript('ai-syndromes').report() end) end,
    -- (0.105.41, item 11) miasma: the flows indoors and near the living, what rots
    -- near the worst, the dump zones under the sky (lua/ai-syndromes.lua)
    miasma = function() return safe(function() return reqscript('ai-syndromes').miasma_report() end) end,
    -- (item 12) the artifacts on the map (displayed, loose, claimed by other
    -- civs), the display furniture, the AI's rooms that could hold one
    -- (lua/ai-artifacts.lua; cached a day)
    artifacts = function() return safe(function()
        local r = reqscript('ai-artifacts').report()
        -- (0.105.95) the secrets of life and death: slabs, books, necromancers (lua/ai-secrets.lua)
        local oks, sec = pcall(function() return reqscript('ai-secrets').report() end)
        if oks then r.secrets = sec end
        return r
    end) end,
    -- (0.105.45) hunting: the loose hostiles and beasts a squad could go after
    -- (the way there, workers near), the squads' strength, the AI's hunts and
    -- their history (lua/ai-hunt.lua)
    hunt = function()
        return safe(function()
            local okl, layers = pcall(get_layers)
            return reqscript('ai-hunt').report(txt, {layers = okl and layers or nil})
        end)
    end,
    -- (0.105.45) the shelter away from the threat: the dangers' ways in, the
    -- fort's levels as shelters with the threat's and the civilians' walk to
    -- each, the chokes between, the barracks, the AI's pick now (lua/ai-shelter-plan.lua;
    -- in the pulse: only a units scan with no danger on the map)
    -- (0.105.48, A1) walked in slices: the pulse gives it a small budget (ctx.tier)
    shelter_plan = function(ctx) return safe(function() return reqscript('ai-shelter-plan').report(txt, ctx and ctx.tier) end) end,
    -- (0.105.46, I2) the thirst watch: each thirsty citizen with why they don't
    -- drink (no path, drink forbidden, a burrow or the alert, jailed, insane,
    -- stranded, the last cancelled Drink job), and the deaths of thirst with
    -- the last reason known (lua/ai-thirst.lua; in the pulse)
    thirst = function() return safe(function() return reqscript('ai-thirst').report() end) end,
    -- (0.105.47, J1) what the strange moods need from the rest of the fort: DF's job
    -- cancels by job (a dead order is a failed route), the webs a weaver can reach
    -- (silk), the moods' tiles outside the shelter (lua/ai-mood-help.lua; in the pulse)
    mood_help = function() return safe(function() return reqscript('ai-mood-help').report() end) end,
    -- (0.105.47, R2 item 3) tantrums one dwarf at a time: the ledger (28 days, a
    -- year), each thrower's posts, labours and unmet needs, the hospitals, the
    -- squads (calm or not) and the AI's hospital guards (lua/ai-tantrums.lua; in the pulse)
    tantrums = function() return safe(function() return reqscript('ai-tantrums').report(txt) end) end,
    -- (item1) the in-game fight watcher: armed, its counts since the game loaded, its
    -- last log entries, the citizens' conflicts now (lua/ai-fights.lua; in the pulse)
    fights = function() return safe(function() return reqscript('ai-fights').report() end) end,
    -- (0.105.47, I7b) the coffins on the AI's other levels (placed, built, free),
    -- free coffins in store, the trainee cook (lua/ai-welfare.lua)
    welfare = function() return safe(function() return reqscript('ai-welfare').report() end) end,
    -- (0.105.47) the cavern wells' safety: each shaft dug from the bottom up,
    -- who is in its column or the cavern under it, its door, the watcher's log
    -- (beside an open shaft, turned up under a well), the one-at-a-time book
    -- (lua/ai-well-safety.lua; in the pulse: the stranded wait on it)
    well_safety = function() return safe(function() return reqscript('ai-well-safety').report() end) end,
    -- (0.105.47, I7d) the near-gates burrow: on, members, the citizens outside
    -- far from every surface way in (lua/ai-near-gates.lua; in the pulse)
    near_gates = function() return safe(function() return reqscript('ai-near-gates').status(txt) end) end,
    -- (0.105.47) the herd by kind (adults by sex, young, breeders, protected,
    -- marked, caged), grass the AI's grazers need, wool grown and milk ready
    -- now, caged wild animals to tame, trainers, autobutcher targets (lua/ai-herd.lua)
    -- (0.105.51) first its upkeep: the AI's old 'Mouser'/'Breeder' nicknames
    -- cleared once, autobutcher's mark taken off the animals the AI keeps
    herd = function() return safe(function()
        local h = reqscript('ai-herd')
        pcall(h.upkeep)
        return h.report()
    end) end,
    -- (0.105.47) the Garden fort's garden court above ground: its stage, the
    -- walls, beds, statues and seats built or waiting (lua/ai-builder-court.lua; nil: none)
    garden_court = function() return safe(function() return reqscript('ai-builder').garden_court_status() end) end,
    -- (0.105.30) what the fort has built: finished constructions by shape and
    -- material, above or below ground, roofed surface tiles, the waiting ones
    -- and the AI's own (lua/ai-constructions.lua; one pass, every 3 days)
    -- (0.105.33) after an action cleared it, the module's own day-long survey
    -- cache is passed by too (else the "read again" copy was up to a day old)
    constructions = function()
        local fresh = CONSTRUCTIONS_FRESH == true
        local r = safe(function() return reqscript('ai-constructions').survey(fresh) end)
        if fresh and not (type(r) == 'table' and r.error) then CONSTRUCTIONS_FRESH = nil end
        -- (r9, audit A3 18) a walk not through yet (its round goes on next
        -- report) is sent but not kept for the section's 3 days
        if type(r) == 'table' and (r.partial or r.refreshing) then return r, true end
        return r
    end,
    -- (0.105.47) the deep plan's crossing of the first cavern: none, ready,
    -- working, built or blocked (why), its depth, a danger in the layer
    -- (lua/ai-descent.lua; nine tiles a level of one column)
    descent = function() return safe(function() return reqscript('ai-descent').report(get_layers()) end) end,
    -- (0.105.47, J16) can the citizens walk off the map: their walk group
    -- against the map's edge groups, the surface gates shut on the way, the
    -- dangers in sight (lua/ai-way-out.lua; in the pulse too)
    way_out = function() return safe(function() return reqscript('ai-way-out').report() end) end,
    -- (layout B) the hallway-first floors: the saved floor plans, their halls and rooms,
    -- the fallbacks (lua/ai-builder-floors.lua; reads the saved record only, no map tile)
    floors = function() return safe(function() return reqscript('ai-builder').floors_report() end) end,
}

-- The pulse: a small report for the frequent check between full ones.
PULSE_SECTIONS = {
    'hunt',   -- (0.105.45, merge) a hunt going badly is called back within hours, not a day
    'bridge_version', 'paused', 'fort', 'date', 'wealth', 'dwarves', 'stocks',
    'others_on_map', 'civ_alert', 'civ_alert_ready', 'civ_alert_shelter', 'orders', 'projects', 'entrances',
    'moods', 'military', 'settings', 'events_waiting', 'hazards', 'ledger',
    'insane',   -- (0.105.40b) a melancholy dwarf walks to the water: read each cycle
    'weather',  -- (fix41) an evil cloud crosses from the map's edge in hours: read each cycle
    'field_watch',   -- (item5) a caravan attacked, a bear by the woodcutters: read each cycle
    'env_hazards',   -- (0.105.41, item 7) spilt magma spreads in minutes: read each cycle
    'shelter_plan',  -- (0.105.45) a titan inside walks to the shelter in minutes: read each cycle
    'lures',         -- (0.105.45) a lure is opened and shut on what the beast does: read each cycle
    'thirst',        -- (0.105.46, I2) thirst kills in days: read each cycle
    'mood_help',     -- (0.105.47, J1) an alarm sounded while a mood gathers: read each cycle
    'tantrums',      -- (0.105.47) a tantrum is loose for hours: read each cycle
    'fights',        -- (item1) the fight watcher re-armed on the next cycle after a reload
    'well_safety',   -- (0.105.47) a dwarf under a well, a shaft's next level: read each cycle
    'near_gates',    -- (0.105.47, I7d) a titan reaches the far-out workers in 500 ticks: read each cycle
    'way_out',       -- (0.105.47, J16) a fort sealed in: read each cycle (the edge groups cached)
}
TIERS = {pulse = true, daily = true, survey = true}
-- report sections rebuilt only every so many game days (the lag pass, Oct 23:
-- each full report froze the game ~0.5 s; these walk every item or stockpile)
SECTION_CACHE_DAYS = {logistics = 3, industry = 7,   -- industry: 300-450 ms live (veins and every boulder)
    -- (0.100) slow and slow-changing, read only for slow decisions: rebuilt
    -- in rotation (SECTION_REBUILDS a report, the stalest first), so no one
    -- report pays for all of them (region2: a full report froze ~250 ms)
    -- (supplies isn't cached: "have + queued" rules read it against live
    -- orders, and a stale count made them order twice; review 24 Oct)
    room_gaps = 3, planned = 1, needs = 1, registry = 3, noble_rooms = 3, locations = 2, petitions = 2, diplomacy = 7, crossings = 7,
    missions = 1,   -- (0.104.95) every world site walked
    homes = 1,      -- (0.104.168) each citizen's thoughts and every bedroom zone read
    citizens_taste = 3,   -- (E4) each citizen's soul and the free furniture read
    disposal = 1}   -- (0.105.27) every item in play walked once for the marks
SECTION_CACHE_DAYS.constructions = 3   -- (0.105.30) every built tile walked once
SECTION_CACHE_DAYS.food_store = 1      -- (0.105.40b, M6) every food item walked once
SECTION_CACHE_DAYS.noble_demands = 1   -- (0.105.41) the engravings walked once
SECTION_CACHE_DAYS.pile_links = 1      -- (0.105.41, item 2) every tool and the AI's piles walked once
SECTION_CACHE_DAYS.siege = 1           -- (item5) small boxes round the entrances, the engines
SECTION_CACHE_DAYS.paper = 1           -- (item9) the plants and tools walked once
SECTION_CACHE_DAYS.artifacts = 1       -- (item 12) the artifacts and display furniture walked once
SECTION_CACHE_DAYS.killzones = 1       -- (0.105.45) a walk in from each entrance, the units once
-- (0.105.51) R3 (15 Nov): 110-196 ms median a full report, rebuilt each one:
-- the AI's project areas (the registry decoded and copied) and every
-- citizen's skills for each kind; read only for the slow training-bench rule
SECTION_CACHE_DAYS.benches = 2
SECTION_REBUILDS = 2       -- expired cached sections rebuilt in one report (a missing one always is)
-- (0.105.48, K7c) the most game days a cached copy is ever sent: past it the
-- section is rebuilt whatever the rotation (A1: two rebuilds a report against
-- ~14 due a day left every cached section 11-12 days old). Set by how fast
-- each changes and how fast the rules that read it must answer; a section
-- not listed is only rotated. The age of each copy sent is in perf.cache_age.
SECTION_MAX_DAYS = {
    needs = 2, homes = 2, disposal = 2, food_store = 2, planned = 2,   -- the people and the food: within a day or two
    siege = 2, killzones = 2,                                         -- the defences
    missions = 3, noble_demands = 3, pile_links = 3, paper = 3, artifacts = 3, petitions = 3,
    locations = 4, benches = 4,
    logistics = 6, room_gaps = 6, registry = 6, noble_rooms = 6, constructions = 6, citizens_taste = 7,
    industry = 12, diplomacy = 12, crossings = 12,
}
-- (0.100) the cached sections each action changes (cleared when it succeeds)
CACHE_INVALIDATES = {
    place_in_zone = {'justice'}, convict = {'justice'},
    give_room = {'noble_rooms'}, appoint = {'noble_rooms'}, quick_location = {'locations'},
    send_mission = {'missions'},   -- (0.105.24) the sender's status read again
    add_posts = {'locations'}, staff_location = {'locations'}, vacate_post = {'locations', 'health'}, retarget_hall = {'locations', 'registry'},
    answer_petition = {'petitions', 'locations'}, petition_orders = {'petitions'},
    give_trinkets = {'needs'}, idle_crafting = {'needs'}, unload_depot = {'needs'},
    keep_mousers = {'needs'},     -- (0.104.168) the cats kept: read again
    -- (review) furnishing makes the temple, hospital, offices and rooms: the
    -- rules that read locations and noble_rooms would start a second level
    start_project = {'registry'}, furnish_project = {'registry', 'locations', 'noble_rooms'},
    finish_project = {'registry', 'locations', 'noble_rooms'},
    cancel_project = {'registry', 'locations', 'noble_rooms'}, engrave_project = {'registry'},
    build_crossing = {'crossings'}, remove_crossing = {'crossings'},
    unforbid_dead = {'dead'}, allow_burial = {'dead'}, repair_rooms = {'room_gaps'},
    -- (0.104.141) a pile placed: the cached logistics section said "none" for
    -- 3 days and the rule asked again each cycle (17 refusals in 1.5 h)
    feeder_pile = {'logistics'},
    add_doctor_post = {'locations'},   -- (0.104.168)
    house_dwarves = {'homes', 'noble_rooms'},   -- (0.104.168)
    furnish_liked = {'homes', 'citizens_taste'},   -- (E4)
}
CACHE_INVALIDATES.set_farm_crops = {'farms'}   -- (0.105.5) the plots' crops read again
CACHE_INVALIDATES.accept_cups = {'needs'}       -- (0.104.168) the cups census shows what it changed
CACHE_INVALIDATES.mood_free_items = {'moods'}  -- (0.105.24) what the mood can reach now
CACHE_INVALIDATES.hospital_release = {'moods', 'locations'}  -- (item2) the moods' counts, the hospital's quotas
CACHE_INVALIDATES.hospital_cap = {'moods', 'locations'}  -- (0.105.112) likewise
CACHE_INVALIDATES.location_access = {'locations'}  -- (0.105.26) shut places read shut, not "opened by you"
-- (0.105.27) the disposal section read again after each disposal action
for _, name in ipairs({'unforbid_items', 'mark_melt', 'mark_dump', 'empty_dump', 'place_dump'}) do
    CACHE_INVALIDATES[name] = {'disposal'}
end
CACHE_INVALIDATES.set_standing_orders = {'disposal', 'dead'}
-- (0.105.47) the dead and the coffins read again after the burial actions
CACHE_INVALIDATES.coffins_anywhere = {'dead', 'welfare'}
CACHE_INVALIDATES.engrave_memorials = {'dead'}
CACHE_INVALIDATES.prune_memorial_orders = {'dead'}   -- (item7) memorial_orders counted again
CACHE_INVALIDATES.entomb_dead = {'dead'}   -- (item8) the free tombs counted again
CACHE_INVALIDATES.train_cook = {'welfare'}
-- (0.105.40 review) world cleanup: items deleted (the disposal marks and dump
-- counts, industry's boulders and stocks), creatures vaporized (disposal's
-- invaders), dead units off the active list; the spatter is in no cached section
CACHE_INVALIDATES.cleanup_items = {'disposal', 'industry'}
CACHE_INVALIDATES.cleanup_units = {'disposal'}
CACHE_INVALIDATES.cleanup_dead_units = {'disposal', 'dead'}
CACHE_INVALIDATES.food_pile = {'food_store', 'logistics'}   -- (0.105.40b, M6) the new pile read again
CACHE_INVALIDATES.food_barrels = {'food_store'}
CACHE_INVALIDATES.pile_barrows = {'pile_links'}   -- (0.105.41, item 2)
CACHE_INVALIDATES.feeder_link = {'pile_links'}
-- (item5) the siege section read again after its own actions
CACHE_INVALIDATES.fortify_post = {'siege'}
CACHE_INVALIDATES.archer_post = {'siege'}
CACHE_INVALIDATES.place_siege_engine = {'siege'}
CACHE_INVALIDATES.place_siege_shop = {'siege'}
CACHE_INVALIDATES.build_killzone = {'killzones', 'siege'}   -- (0.105.45) the zone read again after each step
CACHE_INVALIDATES.clear_miasma = {'disposal'}   -- (0.105.41, item 11) items marked for the dump
CACHE_INVALIDATES.place_display = {'artifacts'}      -- (item 12)
CACHE_INVALIDATES.display_artifact = {'artifacts'}
CACHE_INVALIDATES.forbid_secrets = {'artifacts'}     -- (0.105.95)
-- (fix41) a kitchen's or still's feeder pile is a food pile, and a storage
-- level's furnish step lays its food piles: the food store read again
CACHE_INVALIDATES.feeder_pile = {'logistics', 'food_store', 'pile_links'}
CACHE_INVALIDATES.furnish_project = {'registry', 'locations', 'noble_rooms', 'food_store'}
CACHE_INVALIDATES.polish_room = {'noble_demands'}   -- (0.105.41)
CACHE_INVALIDATES.bench_caps = {'benches'}          -- (0.105.51) the cap set or lifted read again
for _, name in ipairs({'give_room', 'place_in_zone', 'furnish_project', 'house_dwarves'}) do
    table.insert(CACHE_INVALIDATES[name], 'noble_demands')     -- (0.105.41) a noble's room changed
end
CACHE_INVALIDATES.renew_well_dig = {'registry'}   -- (0.105.31) as start_project
CACHE_INVALIDATES.build_blueprint = {'registry'}   -- (D0) a landmark's levels are projects
CACHE_INVALIDATES.landmark_step = {'registry'}
-- (0.105.30) construction placed: the waiting count read again
for _, name in ipairs({'place_hall', 'build_wings', 'floor_rooms', 'place_keep'}) do
    CACHE_INVALIDATES[name] = {'constructions'}
end
CACHE_INVALIDATES.place_garden_court = {'constructions'}   -- (0.105.47)
CACHE_INVALIDATES.redig_projects = {'registry'}
SECTION_CACHE = SECTION_CACHE or {}
-- (0.104.8) a new bridge starts with an empty cache: DFHack keeps a script's
-- globals across runs, so a section cached by older code (0.104.7's
-- instruments with raw names) outlived the fix for 28 days
if SECTION_CACHE_VERSION ~= BRIDGE_VERSION then
    SECTION_CACHE = {}
    SECTION_CACHE_VERSION = BRIDGE_VERSION
end
