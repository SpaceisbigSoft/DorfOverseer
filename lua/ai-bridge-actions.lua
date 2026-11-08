-- ai-bridge-actions: the action handlers (act_*) behind the ACTIONS table in
-- ai-bridge.lua: projects, culture, ledger, memory, gates, labour, kitchen,
-- military, trade...
--
-- A part of ai-bridge.lua (13c, when the 409 KB file was split), loaded by it
-- into its own environment: what is global here is the bridge's (reachable as
-- reqscript('ai-bridge').<name>), and the bridge's shared helpers (txt,
-- reject, int_in, whole_number, sorted_keys, abs_tick, translate_name,
-- in_fort, NOT_IN_FORT, OUT_DIR) are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-actions is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-actions'] = '0.105.26'   -- (0.105.26) bumped with BRIDGE_VERSION

local json = require('json')
local utils = require('utils')

local MEMORY_TO_SAVE = OUT_DIR .. '/memory-to-save.json'

---------------------------------------------------------------------------
-- The dead and the civilian alert
---------------------------------------------------------------------------

-- (0.104.15) The fort's own dead, forbidden where they lie, unforbidden
-- so they can be carried to a free tomb (only bodies of the fort's race the
-- dwarves can walk to; never one a job holds).
function act_unforbid_dead(a)
    local race = df.global.plotinfo.race_id
    local max = whole_number(a.max) or 20
    local from = citizen_anchor()
    local n = 0
    for _, it in ipairs(df.global.world.items.other.CORPSE) do
        if n >= max then break end
        local ok, r = pcall(function() return it.race end)
        if ok and r == race and it.flags.forbid and not it.flags.in_building and not it.flags.removed
                and not it.flags.in_job then
            local x, y, z = dfhack.items.getPosition(it)
            if x and from and dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z)) then
                if not a.dry_run then it.flags.forbid = false end
                n = n + 1
            end
        end
    end
    if n == 0 then return reject('no forbidden body of the fort\'s the dwarves can reach') end
    return {ok = true, unforbidden = n, dry_run = a.dry_run or nil}
end

-- (0.104.17) Automatic burial of citizens switched back on in the AI's own
-- tomb levels (each coffin a 1x1 tomb zone): Enxah's 7 free tombs all had it
-- off ("no citizens") while 104 bodies lay unburied. Never a tomb outside an
-- AI tomb level, never one set aside for one dwarf.
function act_allow_burial(a)
    local okp, data = pcall(function() return reqscript('ai-builder').load_projects() end)
    local areas = {}
    for _, p in ipairs(okp and data and data.list or {}) do
        if p.kind == 'tombs' and type(p.area) == 'table' then table.insert(areas, p.area) end
    end
    if #areas == 0 then return reject('no tomb level of the AI\'s') end
    local n = 0
    for _, z in ipairs(df.global.world.buildings.all) do
        if z:getType() == df.building_type.Civzone and z.type == df.civzone_type.Tomb then
            local mine = false
            for _, ar in ipairs(areas) do
                if z.z == ar.z and z.x1 >= ar.x1 and z.x2 <= ar.x2 and z.y1 >= ar.y1 and z.y2 <= ar.y2 then mine = true end
            end
            local okf, off = pcall(function() return z.zone_settings.tomb.flags.no_citizens end)
            local oko, owner = pcall(function() return z.assigned_unit_id end)
            if mine and okf and off and (not oko or owner == nil or owner < 0) then
                if not a.dry_run then z.zone_settings.tomb.flags.no_citizens = false end
                n = n + 1
            end
        end
    end
    if n == 0 then return reject('every AI tomb already takes citizens') end
    return {ok = true, opened = n, dry_run = a.dry_run or nil}
end

-- The civilian alert sounded or cleared (DFHack's gui/civ-alert).
function act_civ_alert(a)
    if type(a.on) ~= 'boolean' then return reject('on must be true or false') end
    local civ = reqscript('gui/civ-alert')
    if a.on then
        if df.global.plotinfo.alerts.civ_alert_idx ~= 0 then
            -- already_on: the alert is someone else's (usually the player's)
            return {ok = true, on = true, already_on = true, note = 'civilian alert was already on'}
        end
        if not civ.can_sound_alarm() then
            return reject('no civilian alert burrow is set up yet; the player must choose one in the civ-alert settings first')
        end
        -- (0.105.8) the AI's shelter over the fort as it is now, first
        local okr, rr = pcall(function() return reqscript('ai-society').refresh_shelter() end)
        civ.sound_alarm()
        return {ok = true, on = df.global.plotinfo.alerts.civ_alert_idx ~= 0,
                shelter = okr and rr or nil, shelter_error = (not okr) and tostring(rr):sub(1, 120) or nil}
    else
        civ.clear_alarm()
    end
    return {ok = true, on = df.global.plotinfo.alerts.civ_alert_idx ~= 0}
end

---------------------------------------------------------------------------
-- Building projects (lua/ai-builder.lua). The AI names a level kind and a
-- size; the builder decides where and checks every tile. See docs/building.md.
---------------------------------------------------------------------------

local function string_list(v, allowed, max)
    if type(v) ~= 'table' then return nil end
    local out, seen = {}, {}
    for _, name in ipairs(v) do
        if type(name) ~= 'string' or not allowed[name] then return nil end
        if not seen[name] then table.insert(out, name); seen[name] = true end
    end
    if #out == 0 or #out > max then return nil end
    return out
end

-- The fort's building style (from its culture); every field is optional.
-- Returns style (or nil when none was given), error.
local function parse_style(st)
    if st == nil then return nil end
    if type(st) ~= 'table' then return nil, 'style must be an object' end
    local hall = st.hall or 'plain'
    if hall ~= 'plain' and hall ~= 'rounded' and hall ~= 'pillared' then
        return nil, 'style.hall must be plain, rounded or pillared'
    end
    local smooth, statues = int_in(st.smooth or 0, 0, 3), int_in(st.statues or 0, 0, 4)
    if not smooth or not statues then
        return nil, 'style.smooth must be 0-3 and style.statues 0-4'
    end
    if st.entry_door ~= nil and type(st.entry_door) ~= 'boolean' then
        return nil, 'style.entry_door must be true or false'
    end
    local spacing = int_in(st.spacing or 0, -200, 200)
    if not spacing then return nil, 'style.spacing must be -200 to 200' end
    -- optional: how the level is turned (0-3) and the pillar rhythm (3-6 tiles)
    local orient, rhythm
    if st.orient ~= nil then
        orient = int_in(st.orient, 0, 3)
        if not orient then return nil, 'style.orient must be 0-3' end
    end
    if st.rhythm ~= nil then
        rhythm = int_in(st.rhythm, 3, 6)
        if not rhythm then return nil, 'style.rhythm must be 3-6' end
    end
    return {hall = hall, smooth = smooth, statues = statues, entry_door = st.entry_door == true,
            spacing = spacing, orient = orient, rhythm = rhythm}
end

-- The overseer's master plan for a new level: a hint where to put it (the
-- builder tries it first, then searches as usual). Every field but the
-- elevation band is optional. Returns plan (or nil when none was given), error.
local PLAN_DIRS = {north = true, south = true, east = true, west = true}
function parse_plan(pl)
    if pl == nil then return nil end
    if type(pl) ~= 'table' then return nil, 'plan must be an object' end
    local out = {}
    if pl.spine ~= nil then
        local sp = type(pl.spine) == 'table' and pl.spine or {}
        local x, y = int_in(sp.x, 0, 999), int_in(sp.y, 0, 999)
        if not x or not y then return nil, 'plan.spine needs x and y, 0-999' end
        out.spine = {x = x, y = y}
    end
    local lo, hi = int_in(pl.elev_lo, -400, 400), int_in(pl.elev_hi, -400, 400)
    if not lo or not hi or lo > hi then
        return nil, 'plan needs elev_lo and elev_hi, -400 to 400, elev_lo <= elev_hi'
    end
    out.elev_lo, out.elev_hi = lo, hi
    if pl.elev_target ~= nil then
        out.elev_target = int_in(pl.elev_target, -400, 400)
        if not out.elev_target then return nil, 'plan.elev_target must be -400 to 400' end
    else
        out.elev_target = lo + (hi - lo) // 2       -- the middle of the band
    end
    if pl.extend ~= nil then                        -- (0.105.14) a deep fort's reach below the stair
        out.extend = int_in(pl.extend, 0, 30)
        if not out.extend then return nil, 'plan.extend must be 0 to 30' end
    end
    if pl.dirs ~= nil then
        if type(pl.dirs) ~= 'table' then return nil, 'plan.dirs must be a list' end
        local dirs, seen, n = {}, {}, 0
        for _ in pairs(pl.dirs) do n = n + 1 end
        for _, d in ipairs(pl.dirs) do
            if type(d) ~= 'string' or not PLAN_DIRS[d] or seen[d] then
                return nil, 'plan.dirs must be distinct names from north, south, east, west'
            end
            seen[d] = true
            table.insert(dirs, d)
        end
        if #dirs == 0 or #dirs > 4 or n ~= #dirs then
            return nil, 'plan.dirs needs 1-4 of north, south, east, west'
        end
        out.dirs = dirs
    end
    if pl.district ~= nil then
        local d = pl.district
        if type(d) ~= 'string' or #d > 40 or not d:match("^[A-Za-z0-9' %-]+$") then
            return nil, 'plan.district must be up to 40 letters, digits, spaces, apostrophes or hyphens'
        end
        out.district = d
    end
    -- corridor grammar (all optional): width, shape, doors
    if pl.avenue ~= nil then
        out.avenue = int_in(pl.avenue, 1, 3)
        if not out.avenue then return nil, 'plan.avenue must be 1-3' end
    end
    if pl.corridors ~= nil then
        if pl.corridors ~= 'straight' and pl.corridors ~= 'dog-leg' then
            return nil, 'plan.corridors must be "straight" or "dog-leg"'
        end
        out.corridors = pl.corridors
    end
    if pl.doors ~= nil then
        if pl.doors ~= 'open' and pl.doors ~= 'doored' and pl.doors ~= 'fortified' then
            return nil, 'plan.doors must be "open", "doored" or "fortified"'
        end
        out.doors = pl.doors
    end
    return out
end

function act_start_project(a)
    local layouts = reqscript('ai-layouts')
    local p = {kind = a.kind}
    if a.kind == 'bedrooms' then
        p.rooms = int_in(a.rooms, 1, 32)
        p.room_size = int_in(a.room_size or 3, 2, 4)
        if not p.rooms or not p.room_size then
            return reject('bedrooms needs rooms 1-32 and room_size 2-4')
        end
        -- (0.103.11) one hall of 4-20 beds and a dormitory zone (Communal)
        if a.dormitory == true then
            p.dormitory = true
            p.rooms = math.max(4, math.min(20, p.rooms))
        end
    elseif a.kind == 'suites' then
        p.suites = int_in(a.suites, 1, 8)
        if not p.suites then return reject('suites needs suites 1-8') end
    elseif a.kind == 'jail' then
        p.cells = int_in(a.cells, 1, 8)
        if not p.cells then return reject('jail needs cells 1-8') end
    elseif a.kind == 'dining' then
        p.tables = int_in(a.tables, 4, 90)
        if not p.tables then return reject('dining needs tables 4-90') end
    elseif a.kind == 'storage' then
        p.piles = string_list(a.piles, layouts.STOCKPILES, 12)
        p.room_size = int_in(a.room_size or 7, 5, 11)
        if not p.piles or not p.room_size then
            return reject('storage needs piles (1-12 of: ' ..
                table.concat(sorted_keys(layouts.STOCKPILES), ', ') .. ') and room_size 5-11')
        end
    elseif a.kind == 'temple' then
        if a.size ~= 'shrine' and a.size ~= 'grand' then
            return reject('temple needs size "shrine" or "grand"')
        end
        p.size = a.size
        -- (0.89) dedicated: to a deity (a figure) or a religion, or a guildhall
        if a.deity_hf ~= nil then
            p.deity_hf = whole_number(a.deity_hf)
            if not p.deity_hf or not df.historical_figure.find(p.deity_hf) then return reject('no such deity') end
        end
        if a.religion ~= nil then
            p.religion = whole_number(a.religion)
            if not p.religion or not df.historical_entity.find(p.religion) then return reject('no such religion') end
        end
        if a.profession ~= nil then
            if type(a.profession) ~= 'string' or df.profession[a.profession] == nil or not a.profession:match('^[%u_]+$') then
                return reject('profession must be one of DF\'s professions, e.g. MINER')
            end
            p.profession = a.profession
        end
    elseif a.kind == 'hospital' or a.kind == 'barracks' then
        p.beds = int_in(a.beds, 4, 20)
        if not p.beds then return reject(a.kind .. ' needs beds 4-20') end
    elseif a.kind == 'archery' then
        p.lanes = int_in(a.lanes or 2, 1, 3)
        p.length = int_in(a.length or 12, 8, 16)
        if not p.lanes or not p.length then return reject('archery needs lanes 1-3 and length 8-16') end
    elseif a.kind == 'tombs' then
        p.coffins = int_in(a.coffins, 4, 30)
        if not p.coffins then return reject('tombs needs coffins 4-30') end
    elseif a.kind == 'tavern' then
        p.tables = int_in(a.tables, 4, 20)
        if not p.tables then return reject('tavern needs tables 4-20') end
    elseif a.kind == 'library' then
        p.bookcases = int_in(a.bookcases, 4, 20)
        if not p.bookcases then return reject('library needs bookcases 4-20') end
    elseif a.kind == 'memorial' then
        if type(a.name) ~= 'string' or not a.name:match("^[A-Za-z' ]+$") or #a.name > 40 then
            return reject('memorial needs a name: letters, spaces and apostrophes, up to 40')
        end
        p.name = a.name
    elseif a.kind == 'garden' then
        if type(a.name) ~= 'string' or not a.name:match("^[A-Za-z' ]+$") or #a.name > 40 then
            return reject('garden needs a name: letters, spaces and apostrophes, up to 40')
        end
        p.name = a.name
    elseif a.kind == 'workshops' then
        p.shops = string_list(a.shops, layouts.WORKSHOPS, 12)
        if not p.shops then
            return reject('workshops needs shops (1-12 of: ' ..
                table.concat(sorted_keys(layouts.WORKSHOPS), ', ') .. ')')
        end
    else
        return reject(('unknown level kind: %s (known: %s)'):format(
            tostring(a.kind), table.concat(layouts.KINDS, ', ')))
    end
    local style, err = parse_style(a.style)
    if err then return reject(err) end
    p.style = style
    local plan, perr = parse_plan(a.plan)
    if perr then return reject(perr) end
    p.plan = plan
    p.urgent = a.urgent == true or nil       -- a well's or a mood's workshop: one slot more
    -- (0.105.23, 14.1 step 4c) the Deep mine: no level above this elevation (one under the surface)
    if a.max_elev ~= nil then
        p.max_elev = int_in(a.max_elev, -400, 400)
        if not p.max_elev then return reject('max_elev must be -400 to 400') end
    end
    return reqscript('ai-builder').start_project(p, get_date(), a.dry_run == true)
end

-- Farm plots: on soil or muddy floor the fort already has, else (dig = true)
-- a new farm level dug in a soil layer. The AI says how many tiles; the
-- builder finds where. See docs/building.md.
function act_farm_plots(a)
    local tiles = int_in(a.tiles, 4, 400)
    if not tiles then return reject('farm_plots needs tiles 4-400') end
    if a.dig ~= nil and type(a.dig) ~= 'boolean' then return reject('dig must be true or false') end
    local style, err = parse_style(a.style)
    if err then return reject(err) end
    if a.outside ~= nil and type(a.outside) ~= 'boolean' then return reject('outside must be true or false') end
    -- (0.99.10) `outside` reaches the builder: it was dropped here, so the
    -- outdoor search never ran (region2's "no free soil" seven times over)
    local max_elev                           -- (0.105.23) a farm level's ceiling (the Deep mine)
    if a.max_elev ~= nil then
        max_elev = int_in(a.max_elev, -400, 400)
        if not max_elev then return reject('max_elev must be -400 to 400') end
    end
    return reqscript('ai-builder').farm_plots({tiles = tiles, dig = a.dig == true, outside = a.outside == true,
        underground = a.underground == true,   -- (0.105.5) for underground crops: subterranean floor only
                                               max_elev = max_elev,
                                               style = style}, get_date(), a.dry_run == true)
end

-- A well: the builder finds a free floor inside the fort with a straight
-- drop to clean water, channels it, and places the well once it's dug.
function act_place_well(a)
    -- (0.105.3) Hammerstirred (2 Nov): the brain's reach for a well beside far
    -- water: gallery (tiles of tunnel out to a column over the cavern lake; 0
    -- none), toward (points of cavern water, from the survey), shore_reach
    -- (tiles from the gate a pond may be for a well on its bank)
    local toward
    if type(a.toward) == 'table' then
        toward = {}
        for i, p in ipairs(a.toward) do
            if i > 6 then break end
            if type(p) == 'table' then
                local x, y, z = whole_number(p.x), whole_number(p.y), whole_number(p.z)
                if x and y and z then table.insert(toward, {x = x, y = y, z = z}) end
            end
        end
    end
    local gallery = whole_number(a.gallery)
    local reach = whole_number(a.shore_reach)
    return reqscript('ai-builder').place_well({inside_only = a.inside_only == true, cavern = a.cavern == true,
                                               urgent = a.urgent == true,
                                               -- (0.105.4 review) a cavern nobody has found: the Rules tab's say
                                               open_caverns = a.open_caverns == true,
                                               gallery = gallery and math.max(0, math.min(gallery, 80)) or nil,
                                               toward = toward,
                                               shore_reach = reach and math.max(0, math.min(reach, 100)) or nil},
                                              get_date(), a.dry_run == true)
end

local function project_id(a)
    return whole_number(a.project_id)
end

function act_furnish_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').furnish_project(id, plugin_enabled('buildingplan') == true, a.stalled == true)
end

-- (0.104.110) a stalled level's dig jobs let go of their workers
function act_free_dig_jobs(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').free_dig_jobs(id)
end

-- (0.104.131) solved cases convicted, the oldest first, as the Justice screen
-- does: the case's culprit named as the accused; DF passes the sentence
function act_convict(a)
    local max = math.tointeger(a.max) or 3
    if max < 1 or max > CONVICT_PER_CALL_MAX then return reject('max must be 1-' .. CONVICT_PER_CALL_MAX) end
    local site = df.global.plotinfo.site_id
    local list = df.global.world.crimes.all
    local busy = convict_busy(list)
    local picked = {}
    for i = 0, #list - 1 do
        if #picked >= max then break end
        local c = list[i]
        if convictable(c, site) and not busy[c.criminal] then
            table.insert(picked, c)
            busy[c.criminal] = true
        end
    end
    if #picked == 0 then return {ok = false, rejected = true, error = 'no solved case waits for a trial'} end
    local out = {ok = true, convicted = {}}
    for _, cr in ipairs(picked) do
        local who = '?'
        pcall(function() who = txt(dfhack.units.getReadableName(df.unit.find(cr.criminal))) end)
        local kind = df.crime_type and df.crime_type[cr.mode] or tostring(cr.mode)
        if a.dry_run then
            table.insert(out.convicted, {id = cr.id, kind = kind, who = who})
        else
            local done = pcall(function()
                cr.accused = cr.criminal
                pcall(function() cr.accused_hf:assign(cr.criminal_hf) end)
            end)
            if done then table.insert(out.convicted, {id = cr.id, kind = kind, who = who}) end
        end
    end
    if #out.convicted == 0 then return {ok = false, error = 'the game took none of the convictions'} end
    out.dry_run = a.dry_run == true or nil
    return out
end

-- (0.104.128) an open level's tiles left to dig raised to a higher priority
function act_prioritize_dig(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').prioritize_project(id, a.priority, a.dry_run == true)
end

-- (0.104.151) the cavern wells' stair columns closed: a hatch on each, locked
function act_seal_well_stairs(a)
    return reqscript('ai-builder').seal_well_stairs(a.dry_run == true)
end

-- (0.104.152) the cavern wells' shaft hatch: placed, linked to its lever, opened;
-- shut (at once) while a danger is in the caverns
function act_well_shaft(a)
    return reqscript('ai-builder').well_shaft_step(a.close == true, a.dry_run == true)
end

function act_finish_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').finish_project(id, a.decor_only == true, a.stalled == true)
end

-- The fort's culture, written by the overseer so the panel's Culture page can
-- show it (and so it travels with the save). Display only: nothing in the
-- game reads it.
CULTURE_KEY = 'ai-overseer/culture'
local CULTURE_ENUMS = {
    hall = {plain = true, rounded = true, pillared = true},
    palette = {any = true, dark = true, light = true, warm = true, cool = true, precious = true,
               purpose = true, wood = true},
    temple = {none = true, shrine = true, grand = true},
}

local function clean_text(v, max)
    if type(v) ~= 'string' then return nil end
    return (v:gsub('[^%w %.,;:\'%(%)!%?%-]', '')):sub(1, max)
end

-- (0.104.0) The AI's ledger: the few things it must remember that the game
-- can't tell it (it raised the alert, it closed the gate, it banned cooking
-- brewables, the memorials it built...). Written into the save the moment
-- they change, so a save always holds the ledger that goes with its game:
-- the memory the overseer writes only once a game week could be older than
-- the game it was saved with (a reload lost the stop-gap temple, 0.103.13).
LEDGER_KEY = 'ai-overseer/ledger'
LEDGER_FIELDS = {
    ai_alert_raised = true, gate_closed_by_ai = true, kitchen_ban = true, farm_steer = true, farm_crops_player = true,
    tree_year = true, libraries_imported = true, squads_trained = true, squads_rested = true,
    tools_seen_on = true, tools_player_disabled = true, stuck_cancelled = true, wishes_agreed = true,
    last_expel_tick = true, last_memorial_tick = true, last_garden_tick = true, gardens_built = true,
    memorials_built = true, quick_locations = true, at = true,
}
-- (0.105.0) the AI's own work orders' day counts, and its gate, door and trap
-- records: a reload restarted the first and lost the second
LEDGER_FIELDS.order_watch, LEDGER_FIELDS.gate_records = true, true
LEDGER_MAX_ITEMS = 3000       -- (0.105.0, was 600) room for 40 orders and 40 gate records besides

local function ledger_clean(v, depth, budget)
    if budget.n <= 0 then return nil end
    budget.n = budget.n - 1
    local t = type(v)
    if t == 'boolean' then return v end
    if t == 'number' then
        if v ~= v or v == math.huge or v == -math.huge then return nil end
        return math.tointeger(v) or v
    end
    if t == 'string' then return (v:gsub('%c', '')):sub(1, 120) end   -- (names may carry accents)
    if t ~= 'table' or depth >= 3 then return nil end
    local out = {}
    for k, x in pairs(v) do
        local key = type(k) == 'number' and math.tointeger(k) or (type(k) == 'string' and (k:gsub('%c', '')):sub(1, 120))
        if key ~= nil and key ~= false then
            local c = ledger_clean(x, depth + 1, budget)
            if c ~= nil then out[key] = c end
        end
    end
    return out
end

function ledger_data()
    local ok, d = pcall(dfhack.persistent.getSiteData, LEDGER_KEY, {})
    return ok and type(d) == 'table' and d or {}
end

-- (0.105.0) A scenario copy's mark: a run id in the save's site data. A test
-- copy shared its logs folder and log memory with the real fort (the key is
-- world and site, and DF's autosave renames the loaded save); with the mark
-- the fort section reports run_id and the brain logs the copy apart.
RUN_KEY = 'ai-overseer/run'
function run_mark()
    local ok, d = pcall(dfhack.persistent.getSiteData, RUN_KEY, {})
    return ok and type(d) == 'table' and type(d.id) == 'string' and d.id or nil
end

function act_mark_run(a)
    local id = type(a.run_id) == 'string' and a.run_id:gsub('[^%w%-_]', ''):sub(1, 40) or ''
    if id == '' then return reject('mark_run needs run_id (letters, digits, - and _)') end
    local had = run_mark()
    if had and had ~= id then return reject('this save is already marked as run ' .. had) end
    if a.dry_run then return {ok = true, dry_run = true} end
    if not pcall(dfhack.persistent.saveSiteData, RUN_KEY, {id = id}) then
        return {ok = false, error = 'the run id could not be kept with the fort'}
    end
    return {ok = true, run_id = id}
end

function act_ledger_set(a)
    if type(a.values) ~= 'table' then return reject('ledger_set needs values') end
    local out, budget = {}, {n = LEDGER_MAX_ITEMS}
    for k, v in pairs(a.values) do
        if type(k) ~= 'string' or not LEDGER_FIELDS[k] then
            return reject(('ledger_set: %s is not a ledger field'):format(tostring(k)))
        end
        local c = ledger_clean(v, 0, budget)
        if c ~= nil then out[k] = c end
    end
    if budget.n <= 0 then return reject('ledger_set: too much to keep') end
    if a.dry_run then return {ok = true, dry_run = true} end
    local ok = pcall(dfhack.persistent.saveSiteData, LEDGER_KEY, out)
    if not ok then return {ok = false, error = 'the ledger could not be saved with the fort'} end
    return {ok = true}
end

function act_set_culture(a)
    local c = type(a.culture) == 'table' and a.culture or nil
    if not c then return reject('set_culture needs a culture object') end
    local pr = type(c.profile) == 'table' and c.profile or {}
    local profile = {}
    for k, allowed in pairs(CULTURE_ENUMS) do
        if pr[k] ~= nil then
            if not allowed[pr[k]] then return reject(('culture.profile.%s is not allowed'):format(k)) end
            profile[k] = pr[k]
        end
    end
    profile.smooth = int_in(pr.smooth or 0, 0, 3)
    profile.statues = int_in(pr.statues or 0, 0, 4)
    if profile.smooth == nil or profile.statues == nil then return reject('culture.profile numbers out of range') end
    profile.entry_doors = pr.entry_doors == true
    local memorials = {}
    for _, m in ipairs(type(pr.memorials) == 'table' and pr.memorials or {}) do
        local t = clean_text(m, 40)
        if t and #memorials < 12 then table.insert(memorials, t) end
    end
    profile.memorials = memorials
    local eras = {}
    for _, e in ipairs(type(c.eras) == 'table' and c.eras or {}) do
        if type(e) == 'table' and #eras < 12 then
            table.insert(eras, {year = whole_number(e.year) or 0, title = clean_text(e.title, 60) or ''})
        end
    end
    -- the weights engine's choices and the fort's quirks (display only)
    local function says(v, max) return type(v) == 'string' and (v:gsub('[^%w %.,;:\'%(%)!%?%-%+]', '')):sub(1, max) or nil end
    local choices = {}
    for _, ch in ipairs(type(c.choices) == 'table' and c.choices or {}) do
        if type(ch) == 'table' and #choices < 16 then
            table.insert(choices, {name = says(ch.name, 30) or '?', choice = says(ch.choice, 50) or '?',
                                   why = says(ch.why, 160) or '', by_ai = ch.by_ai == true,
                                   later = says(ch.later, 100)})
        end
    end
    local quirks = {}
    for _, q in ipairs(type(c.quirks) == 'table' and c.quirks or {}) do
        if type(q) == 'table' and #quirks < 6 then
            table.insert(quirks, {name = says(q.name, 30) or '?', since = whole_number(q.since) or 0,
                                  why = says(q.why, 160) or '', does = says(q.does, 200) or '',
                                  fade = says(q.fade, 160) or ''})
        end
    end
    -- the master plan in words, and the fort's current phase (display only)
    local plan = {}
    for _, s in ipairs(type(c.plan) == 'table' and c.plan or {}) do
        local t = says(s, 160)
        if t and #plan < 8 then table.insert(plan, t) end
    end
    -- (0.94) what each slider does now (brain/temperament.py), for the panel
    local effects = {}
    for k, v in pairs(type(c.effects) == 'table' and c.effects or {}) do
        if type(k) == 'string' and k:match('^[%l_]+$') and #k <= 20 and type(v) == 'string' then
            effects[k] = (v:gsub("[^%w %.,;:'%(%)!%?%-%+%%/]", '')):sub(1, 140)
        end
    end
    -- (0.95) what leans each slider beyond your setting (brain/leanings.py)
    local leanings = {}
    for k, v in pairs(type(c.leanings) == 'table' and c.leanings or {}) do
        if type(k) == 'string' and k:match('^[%l_]+$') and #k <= 20 and type(v) == 'string' then
            leanings[k] = (v:gsub("[^%w %.,;:'%(%)!%?%-%+%%/]", '')):sub(1, 110)
        end
    end
    local data = {
        choices = choices, quirks = quirks, effects = effects, leanings = leanings,
        plan = plan, phase = says(c.phase, 120),
        guide = clean_text(c.guide, 400) or '',
        stone = clean_text(c.stone, 40),
        profile = profile, eras = eras,
        beasts_slain = whole_number(c.beasts_slain) or 0,
        sieges = whole_number(c.sieges) or 0,
        updated = get_date(),
    }
    local ok = pcall(dfhack.persistent.saveSiteData, CULTURE_KEY, data)
    return ok and {ok = true} or {ok = false, error = 'could not save the culture with the fort'}
end

-- What the AI has learned (your preferences and lessons, self-tuned targets,
-- the outcome log's verdicts), for the panel's Culture tab (Shift-V). Display
-- only: nothing in the game reads it.
LEARNED_KEY = 'ai-overseer/learned'

local function says(v, max)
    return type(v) == 'string' and (v:gsub('[^%w %.,;:\'"%(%)!%?%-%+%%/>]', '')):sub(1, max) or nil
end

local function says_list(v, n, max)
    local out = {}
    for _, s in ipairs(type(v) == 'table' and v or {}) do
        local t = says(s, max)
        if t and #out < n then table.insert(out, t) end
    end
    return out
end

function act_set_learned(a)
    local l = type(a.learned) == 'table' and a.learned or nil
    if not l then return reject('set_learned needs a learned object') end
    local prefs = {}
    for _, p in ipairs(type(l.prefs) == 'table' and l.prefs or {}) do
        if type(p) == 'table' and #prefs < 12 then
            table.insert(prefs, {text = says(p.text, 60) or '?', weight = tonumber(p.weight) or 0,
                                 lesson = p.lesson == true, inherited = p.inherited == true,
                                 how = says(p.how, 240) or '', effect = says(p.effect, 60) or ''})
        end
    end
    local tuned = {}
    for _, t in ipairs(type(l.tuned) == 'table' and l.tuned or {}) do
        if type(t) == 'table' and #tuned < 8 then
            table.insert(tuned, {name = says(t.name, 50) or '?', value = tonumber(t.value) or 0,
                                 default = tonumber(t.default) or 0, why = says(t.why, 160) or '',
                                 date = says(t.date, 30) or ''})
        end
    end
    local data = {
        prefs = prefs, tuned = tuned,
        verdicts = says_list(l.verdicts, 6, 200), waiting = says_list(l.waiting, 4, 200),
        lessons = says_list(l.lessons, 6, 120), log = says_list(l.log, 6, 200),
        trends = says_list(l.trends, 6, 160), places = says_list(l.places, 4, 160),
        story = says_list(l.story, 4, 160),
        updated = get_date(),
    }
    local ok = pcall(dfhack.persistent.saveSiteData, LEARNED_KEY, data)
    return ok and {ok = true} or {ok = false, error = 'could not save what the AI learned with the fort'}
end

function act_engrave_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').engrave_project(id)
end

-- Idle hands: the next finished level smoothed, then engraved (lua/ai-builder.lua).
function act_polish(a)
    return reqscript('ai-builder').polish_next(a.dry_run == true)
end

function act_cancel_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').cancel_project(id, a.unreached == true)   -- (0.105.22)
end

-- The overseer's memory (cooldowns, culture history, token bank...), kept in
-- the save so it matches whichever save is loaded. The file holds
-- {fort, kinds = {working = "<json text>", ...}, drop_legacy}: each kind is
-- stored as text, untouched, under its own key (only changed kinds are sent).
-- An older brain's {fort, memory} still goes to the old single key.
local function drop_legacy_memory()
    local del = dfhack.persistent.deleteSiteData
    if type(del) == 'function' and pcall(del, MEMORY_KEY) then return end
    -- no delete in this DFHack: leave a marker cmd_memory reads as absent
    pcall(dfhack.persistent.saveSiteData, MEMORY_KEY, {dropped = true})
end

function act_save_memory(a)
    local ok, data = pcall(json.decode_file, MEMORY_TO_SAVE)
    if not ok or type(data) ~= 'table' or type(data.fort) ~= 'string' then
        return reject('the memory file is missing or not valid')
    end
    if data.kinds == nil and data.memory ~= nil then
        local saved = pcall(dfhack.persistent.saveSiteData, MEMORY_KEY, data)
        return saved and {ok = true, saved = {'legacy'}}
            or {ok = false, error = 'could not store the memory with the fort'}
    end
    -- (0.104.44) the texts in files of their own, as they are (the Lua JSON
    -- decoder took ~5 s on 60 KB)
    if type(data.kinds_files) == 'table' then
        data.kinds = data.kinds or {}
        for kind, name in pairs(data.kinds_files) do
            if type(name) ~= 'string' or not name:match('^memory%-to%-save%.[%a_]+%.txt$') then
                return reject('bad memory file name')
            end
            local f = io.open(OUT_DIR .. '/' .. name, 'rb')
            if not f then return reject('the memory file for ' .. tostring(kind) .. ' is missing') end
            data.kinds[kind] = f:read('*a')
            f:close()
        end
    end
    if type(data.kinds) ~= 'table' then return reject('the memory file has no kinds') end
    local allowed = utils.invert(MEMORY_KINDS)
    local names = {}
    for kind, text in pairs(data.kinds) do
        if not allowed[kind] then return reject(('unknown memory kind: %s'):format(tostring(kind))) end
        if type(text) ~= 'string' then return reject(('memory kind %s must be text'):format(kind)) end
        table.insert(names, kind)
    end
    table.sort(names)
    local saved = {}
    for _, kind in ipairs(names) do
        local done = pcall(dfhack.persistent.saveSiteData, MEMORY_KIND_PREFIX .. kind,
                           {fort = data.fort, text = data.kinds[kind]})
        if not done then
            return {ok = false, saved = saved, error = ('could not store the %s memory with the fort'):format(kind)}
        end
        table.insert(saved, kind)
    end
    if data.drop_legacy == true then drop_legacy_memory() end
    return {ok = true, saved = saved}
end

-- The overseer's report for the on-screen panel (memory only, not the save).
function act_report_status(a)
    local ok, err = reqscript('ai-status').set_status(a.status)
    if not ok then return reject(err) end
    -- (0.104.88) the camera director starts (or keeps running) while an
    -- unattended keeper reports; it says what it shows
    local okc, cam = pcall(function()
        local C = reqscript('ai-camera')
        -- (0.104.90) the keeper's places: the plan's districts, its newest work's reasons
        if type(a.status) == 'table' and type(a.status.camera) == 'table' then C.set_brain(a.status.camera) end
        C.ensure()
        local st = C.status()
        return {mode = st.mode, showing = st.showing, kind = st.kind, held = st.held, queued = st.queued,
                tour_stops = st.tour_stops, shown = st.shown, error = st.error, pinned = st.pinned}
    end)
    return {ok = true, camera = okc and cam or {error = tostring(cam):sub(1, 120)}}
end

-- DFHack's own work-order libraries (conditioned orders, e.g. smelting
-- whenever bars run low). Only these ones.
local ORDER_LIBRARIES = {smelting = true, rockstock = true}

function act_import_orders(a)
    if not ORDER_LIBRARIES[a.library] then
        return reject('library must be one of: ' .. table.concat(sorted_keys(ORDER_LIBRARIES), ', '))
    end
    local before = #df.global.world.manager_orders.all
    local out, rv = dfhack.run_command_silent('orders', 'import', 'library/' .. a.library)
    if rv ~= CR_OK then
        return {ok = false, error = ('orders import failed: %s'):format((out or ''):gsub('%s+$', ''))}
    end
    return {ok = true, library = a.library, added = #df.global.world.manager_orders.all - before}
end

-- (0.104.116) Spider webs removed (DFHack's clear-webs, webs only): a
-- fort's caverns held 10,000 of them, a fifth of the items on the map.
function act_clear_webs(a)
    if not dfhack.findScript('clear-webs') then
        return {ok = false, error = 'DFHack has no clear-webs script in this version'}
    end
    local before = #df.global.world.items.other.ANY_WEBS
    if a.dry_run then return {ok = true, dry_run = true, webs = before} end
    local out, rv = dfhack.run_command_silent('clear-webs', '--websOnly')
    if rv ~= CR_OK then return {ok = false, error = 'clear-webs failed: ' .. tostring(out):sub(1, 160)} end
    return {ok = true, removed = before - #df.global.world.items.other.ANY_WEBS}
end

-- (0.105.3) B (2 Nov): 5,530 spider webs on the ground, a third of the
-- 17,471 items, the game at 1-3 FPS. Only the loose webs outside the fort's
-- areas go (no creature stuck in them, not forbidden, owned, carried or in
-- a building; lua/ai-census.lua remove_webs), up to `max` a call (default
-- 2,000), so one call stays quick. Webs near the fort stay for the weavers.
function act_remove_webs(a)
    local n = int_in(a.max or 2000, 1, 5000)
    if not n then return reject('remove_webs needs max 1-5000') end
    return reqscript('ai-census').remove_webs(n, a.dry_run == true)
end

-- (0.104.158) Dead units scrubbed from the active list by DFHack's own
-- fix/dead-units (slaughtered animals, nameless and foreign dead, kept a
-- month; never the fort's own race). Teacheroar, 1 Nov: 7,322 of 8,627 units
-- on the list dead (2,565 ducks, 950 geese, 680 dogs), the game at 17 FPS.
function act_scrub_dead_units(a)
    if not dfhack.findScript('fix/dead-units') then
        return {ok = false, error = 'DFHack has no fix/dead-units script in this version'}
    end
    local before = #df.global.world.units.active
    if a.dry_run then return {ok = true, dry_run = true, units = before} end
    local out, rv = dfhack.run_command_silent('fix/dead-units', '--active', '-q')
    if rv ~= CR_OK then return {ok = false, error = 'fix/dead-units failed: ' .. tostring(out):sub(1, 160)} end
    local removed = before - #df.global.world.units.active
    if removed <= 0 then return {ok = false, rejected = true, error = 'no dead unit old enough to scrub'} end
    return {ok = true, removed = removed, units = #df.global.world.units.active}
end

-- (0.104.113) What fills the map, read only (lua/ai-census.lua).
function act_census(a)
    return reqscript('ai-census').census()
end

-- (0.104.108) Areas on one level joined by a corridor (lua/ai-joins.lua).
function act_join_levels(a)
    return reqscript('ai-joins').join_levels(a.dry_run == true)
end

-- The fort's entrances and their gates (lua/ai-gates.lua).
function act_scan_entrances(a)
    local t0 = os.clock()
    local r = reqscript('ai-gates').scan(abs_tick())
    r.ok, r.ms = true, math.floor((os.clock() - t0) * 1000)
    return r
end

function act_build_gate_doors(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('build_gate_doors needs entrance_id') end
    return reqscript('ai-gates').build_doors(id)
end

local GATE_STYLES = {plain = true, narrow = true, fortified = true, gatehouse = true, grand = true, drawbridge = true}

function act_fortify_entrance(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('fortify_entrance needs entrance_id') end
    if not GATE_STYLES[a.style] then return reject('fortify_entrance needs style plain|narrow|fortified|gatehouse|grand|drawbridge') end
    return reqscript('ai-gates').fortify(id, a.style)
end

-- A fresh embark: the fort's first staircase (lua/ai-builder.lua found_fort).
function act_found_fort(a)
    return reqscript('ai-builder').found_fort(a.dry_run == true)
end

-- (unattended) Unpause the game: DF pauses itself for many announcements,
-- and a fort left alone would wait there for days. Refused while halted.
function saving_now()
    local ok, r = pcall(function() return df.global.plotinfo.main.autosave_request end)
    return ok and r == true
end

function act_unpause(a)
    if saving_now() then return {ok = false, rejected = true, error = 'the game is saving'} end
    local was = df.global.pause_state
    -- (a = {unstick = true}) time isn't moving though the game isn't paused:
    -- DF waits on a popup announcement. Those wait in world.status.popups;
    -- they're taken off (their text is in the reports anyway).
    local cleared = 0
    if a.unstick == true then
        pcall(function()
            local list = df.global.world.status.popups
            while #list > 0 do
                local p = list[#list - 1]
                list:erase(#list - 1)
                pcall(function() p:delete() end)
                cleared = cleared + 1
            end
        end)
    end
    df.global.pause_state = false
    return {ok = true, was_paused = was == true, popups_cleared = cleared}
end

-- (unattended) No announcement pauses the game or opens a popup box while
-- the fort is left to the AI: DF's per-announcement flags PAUSE and DO_MEGA
-- (the box) are cleared in memory only (DF's settings files are untouched:
-- restarting DF brings them back). dry_run counts without changing.
local function announcement_flags()
    for _, get in ipairs({function() return df.global.d_init.announcements.flags end,
                          function() return df.global.announcements.flags end}) do
        local ok, f = pcall(get)
        if ok and f ~= nil then
            local ok2 = pcall(function() return f[0].PAUSE end)
            if ok2 then return f end
        end
    end
    return nil
end

function act_quiet_announcements(a)
    local flags = announcement_flags()
    if not flags then return {ok = false, rejected = true, error = 'announcement settings not found in this DF'} end
    local pause, box, seen = 0, 0, 0
    -- (a DFHack enum is walked by its first and last item: pairs() gives nothing,
    -- which is why 0.36.1 found 0 kinds and quieted nothing)
    local t = df.announcement_type
    for i = t._first_item, t._last_item do
        pcall(function()
            local fl = flags[i]
            seen = seen + 1
            if fl.PAUSE then pause = pause + 1; if not a.dry_run then fl.PAUSE = false end end
            if fl.DO_MEGA then box = box + 1; if not a.dry_run then fl.DO_MEGA = false end end
        end)
    end
    if seen == 0 then return {ok = false, error = 'no announcement kinds could be read'} end
    return {ok = true, dry_run = a.dry_run == true or nil, pausing = pause, boxes = box, kinds = seen}
end

-- (unattended) Save the game now, in its own save folder (DFHack's quicksave).
function act_save_game(a)
    if not dfhack.findScript('quicksave') then
        return {ok = false, rejected = true, error = 'DFHack has no quicksave script here'}
    end
    if a.dry_run == true then return {ok = true, dry_run = true} end
    if saving_now() then return {ok = true, already = true, by = 'the game is saving itself now'} end
    -- DF's own seasonal autosave usually comes at the same moment: if any save
    -- was written in the last 15 minutes, another one is only lag
    local okm, newest = pcall(function()
        local root = dfhack.getDFPath() .. '/save'
        local best = 0
        for _, name in ipairs(dfhack.filesystem.listdir(root) or {}) do
            for _, p in ipairs({root .. '/' .. name, root .. '/' .. name .. '/world.sav'}) do
                local m = tonumber(dfhack.filesystem.mtime(p))
                -- (on Windows DFHack gives the file time in 100 ns steps since 1601,
                -- which read as seconds made "saved -2239490023674139 minutes ago")
                if m and m > 1e15 then m = m / 1e7 - 11644473600
                elseif m and m > 1e11 then m = m / 1000 end
                if m and m > best and m <= os.time() + 60 then best = m end
            end
        end
        return best
    end)
    if okm and newest and newest > 0 and os.time() - newest < 15 * 60 then
        return {ok = true, already = true,
                by = ('the game saved itself %d minute(s) ago'):format(math.floor((os.time() - newest) / 60))}
    end
    local out, rv = dfhack.run_command_silent('quicksave')
    if rv ~= CR_OK then return {ok = false, error = ('quicksave failed: %s'):format((out or ''):gsub('%s+$', ''))} end
    return {ok = true, requested = true}       -- (DF saves over the next frames)
end

-- Traps behind a gate, in the fort's trap style.
function act_place_traps(a)
    local id = whole_number(a.entrance_id)
    local n = int_in(a.count, 1, 8)
    if not id or not n then return reject('place_traps needs entrance_id and count 1-8') end
    if not (a.kind == 'cage' or a.kind == 'stonefall' or a.kind == 'weapon') then
        return reject('place_traps needs kind cage|stonefall|weapon')
    end
    return reqscript('ai-gates').place_traps(id, a.kind, n)
end

-- (0.105.12) A lever of the AI's own for a gate (lua/ai-gates.lua).
function act_place_gate_lever(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('place_gate_lever needs entrance_id') end
    return reqscript('ai-gates').place_gate_lever(id, a.dry_run == true)
end

-- (0.105.23, 14.1 step 4a) A gatehouse in front of the founding stair's hatch:
-- walls, a trap corridor and a drawbridge (lua/ai-gates.lua build_gatehouse).
function act_build_gatehouse(a)
    local id = whole_number(a.entrance_id)
    local n = int_in(a.count or 4, 0, 4)
    if not id or not n then return reject('build_gatehouse needs entrance_id (and count 0-4)') end
    if not (a.kind == nil or a.kind == 'cage' or a.kind == 'stonefall' or a.kind == 'weapon') then
        return reject('build_gatehouse needs kind cage|stonefall|weapon')
    end
    return reqscript('ai-gates').build_gatehouse(id, a.kind or 'cage', n, a.dry_run == true)
end

-- (0.105.12) Who may come into a location (DF's location screen): visitors
-- allowed or not, at the fort's own site only, never a hospital
function act_location_access(a)
    if type(a.visitors) ~= 'boolean' or type(a.ids) ~= 'table' then
        return reject('location_access needs ids and visitors true|false')
    end
    local want = {}
    for _, v in ipairs(a.ids) do
        local n = whole_number(v)
        if not n then return reject('location_access: ids are whole numbers') end
        want[n] = true
    end
    local site = dfhack.world.getCurrentSite()
    if not site then return {ok = false, error = 'no site'} end
    local out = {ok = true, changed = {}, visitors = a.visitors, dry_run = a.dry_run or nil}
    for _, b in ipairs(site.buildings) do
        if want[b.id] then
            local t = df.abstract_building_type[b:getType()]
            if t ~= 'HOSPITAL' then
                local okf, cur = pcall(function() return b.flags.VISITORS_ALLOWED end)
                if okf and cur ~= a.visitors then
                    if not a.dry_run then b.flags.VISITORS_ALLOWED = a.visitors end
                    table.insert(out.changed, b.id)
                end
            end
        end
    end
    if #out.changed == 0 then out.changed = nil; out.ok = false; out.rejected = true; out.error = 'nothing to change' end
    return out
end

-- Link a lever to a bridge, door or hatch (a mechanic does the job).
function act_link_lever(a)
    local lid, tid = whole_number(a.lever_id), whole_number(a.target_id)
    if not lid or not tid then return reject('link_lever needs lever_id and target_id') end
    -- (0.100, security pass) the action links the AI's own lever to a
    -- drawbridge, as the gate rule asks; never the player's levers, and never
    -- a floodgate (water or magma behind it). The cistern links its floodgate
    -- itself, inside the builder.
    local lever, target = df.building.find(lid), df.building.find(tid)
    if not (lever and tostring(lever.name or ''):lower():find('^ai gate')) then
        return reject('only a lever named "AI gate" is linked by the AI')
    end
    -- (0.105.12) or a hatch: the founding stair's hatch is every fort's gate
    if not (target and (target:getType() == df.building_type.Bridge or target:getType() == df.building_type.Hatch)) then
        return reject('the AI links its lever to a drawbridge or a hatch only')
    end
    return reqscript('ai-gates').link_lever(lid, tid, a.dry_run == true)
end

function act_arm_gates(a) return reqscript('ai-gates').arm() end
function act_open_gates(a) return reqscript('ai-gates').open_all() end

-- Set-ups the AI does itself (lua/ai-society.lua).
function act_setup_shelter(a)
    return reqscript('ai-society').setup_shelter()
end

-- (0.105.26) The AI's shelter made again over the fort as it is now (a gate
-- lost while the alarm is on: the report's military.shelter_stale).
function act_refresh_shelter(a)
    local S = reqscript('ai-society')
    if a.dry_run == true then return {ok = true, dry_run = true, stale = S.shelter_stale()} end
    local r = S.refresh_shelter()
    if not r then return reject('the civilian alert\'s burrow is not the AI shelter') end
    r.ok = true
    return r
end

function act_set_population_cap(a)
    local cap = int_in(a.cap, 7, 1000)
    if not cap then return reject('set_population_cap needs cap 7-1000') end
    local strict = int_in(a.strict or (cap + 20), cap, 1100)
    if not strict then return reject('strict must be at least the cap') end
    return reqscript('ai-society').set_popcap(cap, strict)
end

-- (0.100, security pass) at most one dwarf sent away a game week, whoever
-- asks (the planner waits 28 days already); kept in the save
EXPEL_KEY, EXPEL_GAP_TICKS = 'ai-overseer/expel', 7 * 1200
function act_expel_dwarf(a)
    local id = a.unit_id ~= nil and whole_number(a.unit_id) or nil
    local now = abs_tick()
    local okg, last = pcall(dfhack.persistent.getSiteData, EXPEL_KEY, {})
    local tick = okg and type(last) == 'table' and tonumber(last.tick) or nil
    if tick and now >= tick and now - tick < EXPEL_GAP_TICKS then
        return reject('a dwarf was sent away less than a week ago')
    end
    local r = reqscript('ai-society').expel_one(txt, id)
    if r and r.ok then pcall(dfhack.persistent.saveSiteData, EXPEL_KEY, {tick = now}) end
    return r
end

-- A new pasture on grass near the fort's surface entrances, sized for the
-- herd (the planner says how many tiles), then the waiting grazers go in.
function act_make_pasture(a)
    local tiles = int_in(a.tiles, 9, 600)
    if not tiles then return reject('make_pasture needs tiles 9-600') end
    local r = reqscript('ai-builder').make_pasture({tiles = tiles}, a.dry_run == true)
    if r.ok and not r.dry_run then
        local ok, p = pcall(reqscript('ai-society').pasture, 50)
        r.assigned = ok and type(p) == 'table' and p.assigned or 0
    end
    return r
end

-- (0.104.83) Squads hold the gate (lua/ai-society.lua guard_gate); war dogs posted there (gate_dogs).
function act_guard_gate(a)
    local x, y, z = int_in(a.x, 0, 1000), int_in(a.y, 0, 1000), int_in(a.z, 0, 1000)
    if not x or not y or not z or type(a.squads) ~= 'table' or #a.squads == 0 then
        return reject('guard_gate needs x, y, z and squads')
    end
    local ids = {}
    for _, s in ipairs(a.squads) do
        local id = int_in(s, 0, 1000000)
        if id then table.insert(ids, id) end
    end
    return reqscript('ai-society').guard_gate(ids, x, y, z, int_in(a.radius or 5, 2, 10), a.dry_run == true)
end

-- (0.105.0, round 2) An army that can fight (lua/ai-military.lua, lua/ai-gates.lua)
function act_fix_gear_gaps(a)
    if a.shields ~= nil and type(a.shields) ~= 'boolean' then return reject('fix_gear_gaps: shields must be true or false') end
    return reqscript('ai-military').fix_gear_gaps(a.dry_run == true, a.shields == true)
end

function act_assign_quivers(a)
    local n = int_in(a.limit or 10, 1, 50)
    if not n then return reject('assign_quivers: limit 1-50') end
    return reqscript('ai-military').assign_quivers(a.dry_run == true, n)
end

function act_squad_bolts(a)
    local id = whole_number(a.squad_id)
    if not id then return reject('squad_bolts needs squad_id') end
    return reqscript('ai-military').squad_bolts(id, a.dry_run == true)
end

function act_shelter_squads(a)
    if type(a.squads) ~= 'table' or #a.squads == 0 or #a.squads > 20 then
        return reject('shelter_squads needs squads: a list of 1-20 squad ids')
    end
    local M, out, n = reqscript('ai-military'), {}, 0
    for _, v in ipairs(a.squads) do
        local id = whole_number(v)
        if not id then return reject('shelter_squads: squads must be squad ids') end
        local r = M.shelter(id, a.dry_run == true)
        out[tostring(id)] = r.ok and 'in the shelter' or r.error
        if r.ok then n = n + 1 end
    end
    if n == 0 then return {ok = false, rejected = true, error = 'no squad could be sent', squads = out} end
    return {ok = true, sheltered = n, squads = out}
end

function act_cut_entrance(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('cut_entrance needs entrance_id') end
    return reqscript('ai-gates').cut_entrance(id, nil, a.dry_run == true)   -- (0.105.0 review: dry_run honoured)
end

function act_gate_dogs(a)
    local x, y, z = int_in(a.x, 0, 1000), int_in(a.y, 0, 1000), int_in(a.z, 0, 1000)
    if not x or not y or not z then return reject('gate_dogs needs x, y, z') end
    return reqscript('ai-society').gate_dogs(x, y, z, int_in(a.max or 4, 1, 12), a.dry_run == true)
end

-- (0.104.82) A new stairwell for a district (lua/ai-builder.lua dig_stairwell).
function act_dig_stairwell(a)
    local lo, hi = int_in(a.elev_lo, -500, 500), int_in(a.elev_hi or a.elev_lo, -500, 500)
    if type(a.dir) ~= 'string' or not lo or not hi then
        return reject('dig_stairwell needs dir and elev_lo (elev_hi)')
    end
    local spine
    if type(a.spine) == 'table' then spine = {x = int_in(a.spine.x, 0, 1000), y = int_in(a.spine.y, 0, 1000)} end
    return reqscript('ai-builder').dig_stairwell({dir = a.dir, elev_lo = lo, elev_hi = hi, spine = spine,
        min_dist = int_in(a.min_dist or 10, 4, 60), max_dist = int_in(a.max_dist or 40, 6, 80)}, a.dry_run == true)
end

-- (0.104.81) Tame animals put to war training (lua/ai-society.lua train_war).
function act_train_war(a)
    local n = int_in(a.max, 1, 10)
    if not n then return reject('train_war needs max 1-10') end
    return reqscript('ai-society').train_war(n, a.dry_run == true, txt)
end

-- (0.104.80) Nest boxes in the hens' pasture (lua/ai-society.lua nest_boxes).
function act_nest_boxes(a)
    local n = int_in(a.max, 1, 10)
    if not n then return reject('nest_boxes needs max 1-10') end
    return reqscript('ai-society').nest_boxes(n, a.dry_run == true)
end

function act_pasture(a)
    local n = int_in(a.count, 1, 50)
    if not n then return reject('pasture needs count 1-50') end
    return reqscript('ai-society').pasture(n)
end

-- Who does what (lua/ai-labor.lua): more dwarves on a job through the game's
-- own work details; never a soldier, never anyone taken off a job.
local LABOR_JOBS = {mining = true, woodcutting = true, gathering = true, fishing = true, farming = true}

function act_assign_labor(a)
    local n = int_in(a.count, 0, 10)
    local L = reqscript('ai-labor')
    if type(a.job) ~= 'string' or not n or not (LABOR_JOBS[a.job] or L.job_spec(a.job)) then
        return reject('assign_labor needs job (mining|woodcutting|gathering|fishing|farming, or a labour '
                      .. 'like BREWER) and count 0-10')
    end
    local min_skill = a.min_skill ~= nil and int_in(a.min_skill, 0, 20) or nil
    return L.assign(a.job, n, a.dry_run == true, txt, min_skill)
end

-- Shrubs near the fort marked for gathering (food and drink before farms).
-- Waiting plant-gathering jobs beyond `keep` cancelled (lua/ai-labor.lua).
function act_trim_gathering(a)
    local keep = int_in(a.keep, 0, 200)
    if not keep then return reject('trim_gathering needs keep 0-200') end
    return reqscript('ai-labor').trim_gathering(keep, a.dry_run == true)
end

-- (0.99.6) autofarm's thresholds by crop: {thresholds = {PLANT_ID = n}}.
-- autofarm plants a crop while its stock is under its threshold; the AI
-- raises the brewable crops' and lowers the rest while drink is short.
function act_farm_thresholds(a)
    if type(a.thresholds) ~= 'table' then return reject('farm_thresholds needs thresholds {PLANT_ID = n}') end
    local by_n, count = {}, 0
    for id, n in pairs(a.thresholds) do
        n = int_in(n, 0, 10000)
        if type(id) ~= 'string' or not id:match('^[%u%d_]+$') or not n then
            return reject('farm_thresholds: plant ids are raws ids (A-Z, 0-9, _), thresholds 0-10000')
        end
        local found = false
        -- (13c) autofarm takes only plants with seeds (SEED): any other id
        -- stops it part-way, the earlier ones set and the rest not
        for _, raw in ipairs(df.global.world.raws.plants.all) do
            if raw.id == id then found = raw.flags.SEED and true or 'noseed' break end
        end
        if not found then return reject('farm_thresholds: no plant ' .. id) end
        if found == 'noseed' then return reject('farm_thresholds: ' .. id .. ' has no seeds (autofarm takes only crops)') end
        by_n[n] = by_n[n] or {}
        table.insert(by_n[n], id)
        count = count + 1
    end
    if count == 0 then return reject('farm_thresholds: no crops given') end
    if a.dry_run then return {ok = true, dry_run = true, crops = count} end
    if not plugin_enabled('autofarm') then
        dfhack.run_command_silent('enable', 'autofarm')
    end
    for n, ids in pairs(by_n) do
        table.sort(ids)
        local args = {'threshold', tostring(n)}
        for _, id in ipairs(ids) do table.insert(args, id) end
        local output, rv = dfhack.run_command_silent('autofarm', table.unpack(args))
        if rv ~= CR_OK then
            return {ok = false, error = 'autofarm threshold failed: ' .. tostring(output):gsub('%s+$', '')}
        end
    end
    return {ok = true, crops = count}
end

-- (0.105.5) Hammerstirred (2 Nov): plots lay fallow all year while autofarm
-- was on and its thresholds set (fort B: 4 of 5 surface plots fallow, drink
-- 0-11 for 7 dwarves, 147 seeds). The AI sets each plot's crop itself, for
-- every season where a crop the fort has seeds of grows there (DF's own test:
-- underground crops underground, surface crops on the surface in their biome
-- and seasons; lua/ai-builder.lua set_farm_crops). {drink = true} puts the
-- brewable crops first, {thread = true} one thread crop a season. autofarm is
-- switched off when the AI sets crops: it rewrites every plot's current
-- season each cycle (to fallow when no crop is under its threshold), so the
-- two would fight; only filling the plots autofarm left empty would leave the
-- fallow it chose. A crop the player set that grows there is kept.
function act_set_farm_crops(a)
    if a.drink ~= nil and type(a.drink) ~= 'boolean' then return reject('set_farm_crops: drink is true or false') end
    if a.thread ~= nil and type(a.thread) ~= 'boolean' then return reject('set_farm_crops: thread is true or false') end
    if a.variety ~= nil and type(a.variety) ~= 'boolean' then return reject('set_farm_crops: variety is true or false') end
    local r = reqscript('ai-builder').set_farm_crops({drink = a.drink == true, thread = a.thread == true,
                                                      variety = a.variety == true},
                                                     a.dry_run == true)
    if r.ok and not a.dry_run and plugin_enabled('autofarm') then
        dfhack.run_command_silent('disable', 'autofarm')
        r.autofarm_off = true
    end
    return r
end

-- (0.100) Cooking eats brewable plants and fruit, and keeps no seed (brewing
-- does): while drink is short the AI bans cooking them in the kitchen
-- settings, the way DFHack's ban-cooking brew does, and lifts its own bans
-- once drink recovers. {ban = true/false}. Only the exclusions the AI added
-- are kept (in the save) and later removed: the player's own stay.
KITCHEN_KEY = 'ai-overseer/kitchen'

-- (0.100) Does this material make a drink (DRINK_MAT among its reaction products)?
local function mat_brews(m)
    for _, id in ipairs(m.reaction_product.id) do
        local v = type(id) == 'string' and id or id.value
        if v == 'DRINK_MAT' then return true end
    end
    return false
end

-- (0.100) The kitchen exclusions for every brewable cookable plant (its
-- STRUCTURAL material, item PLANT) and growth (item PLANT_GROWTH, subtype the
-- growth's index), as ban-cooking.lua's brew list makes them.
function brewable_cook_keys()
    local out = {}
    for _, p in ipairs(df.global.world.raws.plants.all) do
        if p.material_defs.type.drink ~= -1 and p.material_defs.idx.drink ~= -1 then
            for _, m in ipairs(p.material) do
                if m.id == 'STRUCTURAL' then
                    if m.flags.EDIBLE_COOKED and mat_brews(m) then
                        local mi = dfhack.matinfo.find(p.id, m.id)
                        if mi then table.insert(out, {t = df.item_type.PLANT, s = -1, mt = mi.type, mi = mi.index}) end
                    end
                    break
                end
            end
            for k, g in ipairs(p.growths) do
                local mi = dfhack.matinfo.decode(g)
                if mi and mi.material and mi.material.flags.EDIBLE_COOKED and mat_brews(mi.material) then
                    table.insert(out, {t = df.item_type.PLANT_GROWTH, s = k, mt = mi.type, mi = mi.index})
                end
            end
        end
    end
    return out
end

-- (0.103.14) Only cooks this skilled or better work the kitchens (DF's
-- workshop profile, as its Workers tab sets): good meals from a skilled cook
function act_kitchen_skill(a)
    -- (0.104.141) to 20 (Legendary+5): Teacheroar's best cook is 18, and 16+
    -- was refused 9 times in a row
    local n = int_in(a.min_level, 0, 20)
    if not n then return reject('kitchen_skill needs min_level 0-20') end
    local set = 0
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        if b.type == df.workshop_type.Kitchen then
            if not a.dry_run then b.profile.min_level = n end
            set = set + 1
        end
    end
    if set == 0 then return reject('the fort has no kitchen') end
    return {ok = true, kitchens = set, min_level = n, dry_run = a.dry_run == true or nil}
end

function act_kitchen_brewables(a)
    if type(a.ban) ~= 'boolean' then return reject('kitchen_brewables needs ban = true or false') end
    local data = dfhack.persistent.getSiteData(KITCHEN_KEY, {bans = {}})
    local had = type(data.bans) == 'table' and data.bans or {}
    if a.ban then
        local ok, keys = pcall(brewable_cook_keys)
        if not ok then return {ok = false, error = 'kitchen_brewables: ' .. tostring(keys):sub(1, 120)} end
        if a.dry_run then return {ok = true, dry_run = true, kinds = #keys} end
        local added = 0
        for _, k in ipairs(keys) do
            -- false when the exclusion is there already (the player's own, or ours)
            if dfhack.kitchen.addExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then
                table.insert(had, k)
                added = added + 1
            end
        end
        pcall(dfhack.persistent.saveSiteData, KITCHEN_KEY, {bans = had})
        return {ok = true, banned = added, kinds = #keys, held = #had}
    end
    if a.dry_run then return {ok = true, dry_run = true, held = #had} end
    local lifted = 0
    for _, k in ipairs(had) do
        if dfhack.kitchen.removeExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then lifted = lifted + 1 end
    end
    pcall(dfhack.persistent.saveSiteData, KITCHEN_KEY, {bans = {}})
    return {ok = true, lifted = lifted}
end

-- (0.104.30) Fat and tallow kept from the cooks while the hospital has no
-- soap (Enxah: 149 fat, then 13 tallow, cooked into meals before any soap
-- was made, wounds festering): a kitchen exclusion for each kind in stock,
-- lifted with ban = false. Only the AI's own exclusions are lifted.
KITCHEN_FAT_KEY = 'ai-overseer/kitchen-fat'

function act_kitchen_fat(a)
    if type(a.ban) ~= 'boolean' then return reject('kitchen_fat needs ban = true or false') end
    local data = dfhack.persistent.getSiteData(KITCHEN_FAT_KEY, {bans = {}})
    local had = type(data.bans) == 'table' and data.bans or {}
    if a.ban then
        local seen, keys = {}, {}
        for _, it in ipairs(df.global.world.items.other.GLOB) do
            local okm, mi = pcall(dfhack.matinfo.decode, it)
            local token = okm and mi and mi:getToken() or ''
            if token:find(':TALLOW$') or token:find(':FAT$') then
                local k = it.mat_type .. ':' .. it.mat_index
                if not seen[k] then
                    seen[k] = true
                    table.insert(keys, {t = df.item_type.GLOB, s = -1, mt = it.mat_type, mi = it.mat_index})
                end
            end
        end
        if a.dry_run then return {ok = true, dry_run = true, kinds = #keys} end
        local added = 0
        for _, k in ipairs(keys) do
            if dfhack.kitchen.addExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then
                table.insert(had, k)
                added = added + 1
            end
        end
        pcall(dfhack.persistent.saveSiteData, KITCHEN_FAT_KEY, {bans = had})
        if added == 0 and #keys == 0 then return reject('no fat or tallow in the fort') end
        return {ok = true, banned = added, kinds = #keys, held = #had}
    end
    if a.dry_run then return {ok = true, dry_run = true, held = #had} end
    local lifted = 0
    for _, k in ipairs(had) do
        if dfhack.kitchen.removeExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then lifted = lifted + 1 end
    end
    pcall(dfhack.persistent.saveSiteData, KITCHEN_FAT_KEY, {bans = {}})
    return {ok = true, lifted = lifted}
end

-- (0.99.7) Soldiers who don't pick up their uniforms: DFHack's
-- uniform-unstick frees items assigned to one soldier but held by another
-- (or in a container) so their owners can claim them. Its report goes back.
function act_unstick_uniforms(a)
    local okr, changed = pcall(function() return reqscript('ai-military').replace_clothing(a.dry_run == true) end)
    if a.dry_run then return {ok = true, dry_run = true, replace_clothing = okr and changed or nil} end
    -- (0.99.9) the AI's uniforms replace clothes, and what blocks a uniform
    -- item is dropped (uniform-unstick's report named everyday gloves and shoes)
    local output, rv = dfhack.run_command_silent('uniform-unstick', '--all', '--free', '--drop')
    output = tostring(output or ''):gsub('%s+$', '')
    if rv ~= CR_OK then return {ok = false, error = 'uniform-unstick failed: ' .. output:sub(1, 200)} end
    local lines = 0
    for _ in output:gmatch('[^\n]+') do lines = lines + 1 end
    return {ok = true, lines = lines, report = output:sub(1, 400),
            replace_clothing = okr and changed or tostring(changed):sub(1, 120)}
end

-- (0.104.58) Gear DF keeps assigned to no one, or on no list, put back where
-- DF hands it out (lua/ai-military.lua free_stray_gear).
function act_free_stray_gear(a)
    local n = int_in(a.limit or 100, 1, 500)
    if not n then return reject('free_stray_gear: limit 1-500') end
    return reqscript('ai-military').free_stray_gear(a.dry_run == true, n)
end

-- (0.105.8) Armour put on the soldiers' places as assign_weapons does weapons
-- (lua/ai-military.lua assign_kit).
function act_assign_kit(a)
    local n = int_in(a.limit or 10, 1, 50)
    if not n then return reject('assign_kit: limit 1-50') end
    return reqscript('ai-military').assign_kit(a.dry_run == true, n)
end

-- (0.104.60) Weapons put on the soldiers' places when DF leaves the entry
-- empty with free weapons about (lua/ai-military.lua assign_weapons).
function act_assign_weapons(a)
    local n = int_in(a.limit or 10, 1, 50)
    if not n then return reject('assign_weapons: limit 1-50') end
    return reqscript('ai-military').assign_weapons(a.dry_run == true, n)
end

-- (0.104.77) A chair beside each lone chair in a tavern zone (lua/ai-builder.lua pair_chairs).
-- (0.104.78) `zones`: several tried in turn until one gets chairs (Enxah's
-- proper tavern answered "every chair has one beside it")
function act_pair_chairs(a)
    local n = int_in(a.max or 5, 1, 20)
    if not n then return reject('pair_chairs: max 1-20') end
    local ids = {}
    if type(a.zones) == 'table' then
        for _, z in ipairs(a.zones) do local id = whole_number(z); if id then table.insert(ids, id) end end
    elseif a.zone_id ~= nil then
        local id = whole_number(a.zone_id); if id then table.insert(ids, id) end
    end
    if #ids == 0 then return reject('pair_chairs needs zone_id or zones') end
    local B, said, all_paired = reqscript('ai-builder'), {}, true
    for _, id in ipairs(ids) do
        local r = B.pair_chairs(id, a.dry_run == true, n)
        if r.ok then return r end
        table.insert(said, tostring(r.error))
        local e = tostring(r.error)
        if not e:find('has one beside it', 1, true) then all_paired = false end   -- (no chairs yet: not done)
    end
    -- (0.104.138) every chair already has a neighbour: nothing to do (asked 33 times)
    return {ok = false, rejected = true, nothing_to_do = all_paired or nil, error = table.concat(said, '; ')}
end

-- (0.104.78) The recreation burrow: the low-mood moved in, the recovered let
-- out (lua/ai-society.lua recreation_tick).
function act_recreation(a)
    local n = int_in(a.max or 8, 1, 30)
    local days = int_in(a.days or 28, 3, 112)
    if not n or not days then return reject('recreation: max 1-30, days 3-112') end
    -- (0.104.80) places for those who badly want friends, a short stay each
    local f, fd = int_in(a.friends or 0, 0, 10), int_in(a.friend_days or 7, 3, 28)
    if not f or not fd then return reject('recreation: friends 0-10, friend_days 3-28') end
    return reqscript('ai-society').recreation_tick(n, days, a.dry_run == true, txt, f, fd)
end

-- (0.104.168) The loose cups no finished goods pile takes: the pile with the
-- most room set to take them; forbidden cups in a hall unforbidden
-- (lua/ai-society.lua accept_cups).
function act_accept_cups(a)
    return reqscript('ai-society').accept_cups(a.dry_run == true)
end

-- (0.104.168) A few cats (vermin hunters) kept from the butcher: nicknamed,
-- which DFHack's autobutcher respects (lua/ai-society.lua keep_mousers).
function act_keep_mousers(a)
    local n = int_in(a.count or 6, 1, 20)
    if not n then return reject('keep_mousers: count 1-20') end
    return reqscript('ai-society').keep_mousers(n, a.dry_run == true, txt)
end

-- (0.104.167) The hospital burrow: the patients kept inside the hospitals
-- (with the nearest drink and food they can reach), the healed let out
-- (lua/ai-society.lua hospital_burrow_tick).
function act_hospital_burrow(a)
    local n = int_in(a.max or 30, 1, 60)
    local per = int_in(a.per or 10, 1, 30)
    local days = int_in(a.days or 28, 3, 112)       -- (review) the longest stay
    if not n or not per or not days then return reject('hospital_burrow: max 1-60, per 1-30, days 3-112') end
    -- (review) release: everyone let out (the rule switched off, the hospital gone, the status unreadable)
    if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('hospital_burrow: release is true or false') end
    return reqscript('ai-society').hospital_burrow_tick(n, per, a.dry_run == true, txt, days, a.release == true)
end

-- (0.104.169) The calm-down burrows: each citizen in a tantrum kept in a
-- free bedroom away from the hospitals (with the nearest drink), let out
-- once calm or after `days` (lua/ai-society.lua calm_burrow_tick).
function act_calm_burrow(a)
    local n = int_in(a.max or 6, 1, 6)
    local days = int_in(a.days or 3, 1, 7)          -- the longest stay
    if not n or not days then return reject('calm_burrow: max 1-6, days 1-7') end
    if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('calm_burrow: release is true or false') end
    return reqscript('ai-society').calm_burrow_tick(n, days, a.dry_run == true, txt, a.release == true)
end

-- (0.105.0) Round 3, threats answered (lua/ai-threats.lua). Fire: the
-- tiles round a fire get restricted traffic and the jobs beside it are taken
-- off; lift puts back the tiles the AI changed.
function act_fire_guard(a)
    local r = int_in(a.radius or 6, 1, 15)
    local jobs = int_in(a.max_jobs or 40, 0, 200)
    if not r or not jobs then return reject('fire_guard: radius 1-15, max_jobs 0-200') end
    if a.lift ~= nil and type(a.lift) ~= 'boolean' then return reject('fire_guard: lift is true or false') end
    return reqscript('ai-threats').fire_guard(r, jobs, a.lift == true, a.dry_run == true)
end

-- (0.105.0) A cage room for prisoners: an animal stockpile inside the fort.
function act_prisoner_room(a)
    return reqscript('ai-threats').prisoner_room(a.dry_run == true)
end

-- (0.105.0) Werebeast citizens in cells for the full moon (ids), or let out (release).
function act_moon_cell(a)
    local ids = {}
    if a.ids ~= nil and type(a.ids) ~= 'table' then return reject('moon_cell: ids is a list of unit ids') end
    for _, v in ipairs(a.ids or {}) do
        local id = whole_number(v)
        if not id then return reject('moon_cell: ids must be whole numbers') end
        table.insert(ids, id)
    end
    if #ids > 10 then return reject('moon_cell: at most 10 ids') end
    if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('moon_cell: release is true or false') end
    return reqscript('ai-threats').moon_cell(ids, a.release == true, a.dry_run == true, txt)
end

-- (0.105.0) The way down to a cavern locked (its doors and hatches), or unlocked (open).
function act_seal_cavern(a)
    if type(a.layer) ~= 'string' or #a.layer == 0 then return reject('seal_cavern needs layer') end
    if a.open ~= nil and type(a.open) ~= 'boolean' then return reject('seal_cavern: open is true or false') end
    if a.openings ~= nil and type(a.openings) ~= 'boolean' then return reject('seal_cavern: openings is true or false') end
    local tiles = {}
    if not a.open then
        -- (0.105.26) openings: every cavern opening on record too (tiles may then be none)
        if a.openings == true and a.tiles == nil then a.tiles = {} end
        if type(a.tiles) ~= 'table' then return reject('seal_cavern needs tiles {x, y, z}') end
        for _, p in ipairs(a.tiles) do
            if type(p) ~= 'table' or not whole_number(p.x) or not whole_number(p.y) or not whole_number(p.z) then
                return reject('seal_cavern: each tile is {x, y, z}')
            end
            table.insert(tiles, {x = whole_number(p.x), y = whole_number(p.y), z = whole_number(p.z)})
        end
        if (#tiles == 0 and a.openings ~= true) or #tiles > 20 then return reject('seal_cavern: 1-20 tiles') end
    end
    -- (0.105.0 review) the cavern's levels, so no dwarf is sealed out on the far side
    if (a.z1 ~= nil and not whole_number(a.z1)) or (a.z2 ~= nil and not whole_number(a.z2)) then
        return reject('seal_cavern: z1 and z2 are whole numbers')
    end
    return reqscript('ai-threats').seal_cavern(a.layer, tiles, a.open == true, a.dry_run == true,
                                               a.z1 and whole_number(a.z1), a.z2 and whole_number(a.z2),
                                               a.openings == true)
end

-- (0.104.168) Infected dwarves DF asks no treatment for, put to rest in a
-- free hospital bed (as DFHack's dwarfvet does for animals), the worst
-- first; and a second doctor's post at a hospital (lua/ai-health.lua).
function act_rest_infected(a)
    local n = int_in(a.max or 3, 1, 10)
    -- (review) at most `cap` of the AI's sleepers at once, `keep_free` beds left for DF's patients
    local cap, keep = int_in(a.cap or 3, 1, 20), int_in(a.keep_free or 2, 0, 20)
    if not n or not cap or not keep then return reject('rest_infected: max 1-10, cap 1-20, keep_free 0-20') end
    return reqscript('ai-health').rest_infected(n, a.dry_run == true, txt, cap, keep)
end

-- (0.105.24) A patient needing traction got up from an ordinary bed while a
-- traction bench in a hospital stands free, so DF lays him on it.
function act_traction_rest(a)
    local n = int_in(a.max or 1, 1, 3)
    if not n then return reject('traction_rest: max 1-3') end
    return reqscript('ai-health').traction_rest(n, a.dry_run == true, txt)
end

-- (0.105.24) A dwarf in a strange mood: the materials it can use that lie
-- forbidden or marked for the dump within its walk are freed (lua/ai-moods.lua).
function act_mood_free_items(a)
    local id = math.tointeger(tonumber(a.unit_id))   -- (tests/test_moods.py runs this body alone)
    local n = int_in(a.max or 10, 1, 10)
    if not id or not n then return reject('mood_free_items needs unit_id and max 1-10') end
    return reqscript('ai-moods').free_items(id, a.dry_run == true, n, txt)
end

function act_add_doctor_post(a)
    local id = tonumber(a.location_id)
    if not id then return reject('add_doctor_post needs location_id') end
    return reqscript('ai-health').add_doctor_post(id, a.dry_run == true)
end

function act_gather_plants(a)
    local n = int_in(a.count or 100, 1, 150)
    if not n then return reject('gather_plants needs count 1-150') end
    return reqscript('ai-labor').gather_plants(n, a.dry_run == true)
end

-- Outside things: a refuse pile, a trade depot (lua/ai-builder.lua).
function act_place_surface(a)
    if a.kind ~= 'refuse' and a.kind ~= 'depot' and a.kind ~= 'dump' and a.kind ~= 'cages' then
        return reject('place_surface needs kind refuse|depot|dump|cages')
    end
    return reqscript('ai-builder').place_surface(a.kind, a.dry_run == true)
end

-- (0.101) A bridge across water on the surface (lua/ai-builder.lua crossings).
function act_build_crossing(a)
    local x, y, z = whole_number(a.x), whole_number(a.y), whole_number(a.z)
    local len, width = int_in(a.len, 1, 9), int_in(a.width or 1, 1, 3)
    if not (x and y and z and len and width) or not ({n = 1, s = 1, e = 1, w = 1})[a.dir] then
        return reject('build_crossing needs x, y, z, dir n|s|e|w, len 1-9 and width 1-3')
    end
    if a.kind ~= nil and a.kind ~= 'cheap' and a.kind ~= 'refined' then
        return reject('kind must be cheap or refined')
    end
    local now = abs_tick()
    return reqscript('ai-builder').build_crossing(x, y, z, a.dir, len, width, a.kind or 'cheap', now, a.dry_run == true)
end

function act_remove_crossing(a)
    local i = int_in(a.index, 1, 50)
    if not i then return reject('remove_crossing needs index 1-50 (one of the AI\'s own bridges)') end
    return reqscript('ai-builder').remove_crossing(i, a.dry_run == true)
end

-- The keep: walls round the way in, then a roof (lua/ai-builder.lua), a step at a time.
function act_place_keep(a)
    return reqscript('ai-builder').place_keep(a.dry_run == true)
end

-- (0.105.23, 14.1 step 4c) The Deep mine's trade depot underground: a 3-wide
-- ramp road for the wagons and a hall, dug, then the depot (lua/ai-builder.lua).
function act_deep_depot(a)
    return reqscript('ai-builder').place_deep_depot(a.dry_run == true)
end

-- (0.104.7) One spare tame animal to the butcher: fat for tallow, tallow for
-- soap, soap for wounds (Enxah: 7 infected wounds, no soap, no fat, 42 tame
-- animals). Never a pet, a war or hunting animal, a caged or wild one, a
-- child, or the last two of a kind; from the most numerous kind, a male while
-- the kind has more than one. The game's butcher does the rest.
function slaughter_pick(animals)
    local by_race = {}
    for _, a in ipairs(animals) do
        local r = by_race[a.race] or {n = 0, males = 0, list = {}}
        r.n = r.n + 1
        if a.male then r.males = r.males + 1 end
        table.insert(r.list, a)
        by_race[a.race] = r
    end
    local best_race, best
    for race, r in pairs(by_race) do
        if r.n >= 3 and (not best or r.n > best.n or (r.n == best.n and race < best_race)) then
            best_race, best = race, r
        end
    end
    if not best then return nil end
    -- a male while the kind has two or more; else a female (the one male breeds)
    local want_male = best.males > 1
    table.sort(best.list, function(x, y)
        local xw, yw = (x.male == want_male), (y.male == want_male)
        if xw ~= yw then return xw end
        return x.id < y.id
    end)
    return best.list[1], best_race, best.n
end

function act_slaughter_one(a)
    local cands, marked = {}, 0
    for _, u in ipairs(df.global.world.units.active) do
        local ok, fit = pcall(function()
            if not dfhack.units.isAnimal(u) or not dfhack.units.isFortControlled(u) or dfhack.units.isDead(u) then return false end
            if u.flags2.slaughter then marked = marked + 1 return false end
            if dfhack.units.isPet(u) or dfhack.units.isWar(u) or dfhack.units.isHunter(u) then return false end
            if (u.name.nickname or '') == 'Mouser' then return false end      -- (0.104.168) a cat the AI keeps
            if not dfhack.units.isAdult(u) or u.flags1.caged then return false end
            return true
        end)
        if ok and fit then
            local race = df.creature_raw.find(u.race)
            table.insert(cands, {id = u.id, unit = u, race = race and race.creature_id or tostring(u.race),
                                 male = dfhack.units.isMale(u)})
        end
    end
    if marked > 0 then return {ok = false, rejected = true, waiting = true, error = ('%d animal(s) already wait for the butcher'):format(marked)} end
    local pick, race, n = slaughter_pick(cands)
    if not pick then return {ok = false, rejected = true, error = 'no spare tame animal (three or more of a kind, adult, no pet or war animal)'} end
    local out = {ok = true, race = race, of = n, unit_id = pick.id, dry_run = a.dry_run or nil}
    if a.dry_run then return out end
    pick.unit.flags2.slaughter = true
    return out
end

-- (0.104.8) Instruments for the tavern and temples (DF 50 builds most from
-- parts made at several workshops, then assembled): DFHack's `instruments`
-- tool lists what the fort can make and orders an instrument with all its
-- parts. A hand-held one (they're kept in the location's chest), the fewest
-- parts first. Pure pick, then the action.
function instrument_pick(listed, defs)
    local best
    for _, d in ipairs(defs) do
        local placed = false
        for _, f in ipairs(d.flags or {}) do if f == 'PLACED_AS_BUILDING' then placed = true end end
        if not placed and listed[(d.name or ''):lower()] then
            if not best or (d.pieces or 0) < (best.pieces or 0)
                    or ((d.pieces or 0) == (best.pieces or 0) and d.name < best.name) then
                best = d
            end
        end
    end
    return best
end

function act_order_instrument(a)
    local n = int_in(a.amount or 2, 1, 10)
    if not n then return reject('order_instrument needs amount 1-10') end
    if not dfhack.findScript('instruments') then
        return {ok = false, error = 'DFHack has no instruments script in this version'}
    end
    local out, rv = dfhack.run_command_silent('instruments', 'list')
    if rv ~= CR_OK then return {ok = false, error = 'instruments list failed: ' .. tostring(out):sub(1, 120)} end
    local text = tostring(out):lower()
    -- the raws' own names (the tool lists and orders by them; accents and all)
    local defs = {}
    pcall(function()
        for _, d in ipairs(df.global.world.raws.itemdefs.instruments) do
            local e = {name = d.name, pieces = 0, flags = {}}
            pcall(function() e.pieces = #d.pieces end)
            pcall(function() if d.flags.PLACED_AS_BUILDING then e.flags = {'PLACED_AS_BUILDING'} end end)
            table.insert(defs, e)
        end
    end)
    local listed = {}
    for _, d in ipairs(defs) do
        local nm = (d.name or ''):lower()
        if nm ~= '' and text:find(nm, 1, true) then listed[nm] = true end
    end
    local pick = instrument_pick(listed, defs)
    if not pick then return {ok = false, rejected = true, error = 'no hand-held instrument the fort can make'} end
    local res = {ok = true, instrument = txt(pick.name), pieces = pick.pieces, amount = n, dry_run = a.dry_run or nil}
    if a.dry_run then return res end
    -- (0.104.68) what the tool made: 105 orders on Enxah left no order in the
    -- report; the tool's own words and the work orders before and after
    local before = #df.global.world.manager_orders.all
    local had = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do had[o.id] = true end
    local o2, rv2 = dfhack.run_command_silent('instruments', 'order', pick.name, tostring(n))
    if rv2 ~= CR_OK then return {ok = false, error = 'instruments order failed: ' .. tostring(o2):sub(1, 160)} end
    res.orders_made = #df.global.world.manager_orders.all - before
    -- (0.104.69) the tool's orders are the AI's: counted as queued, cancelled
    -- if stuck (Enxah: 31 instrument orders piled up, none counted)
    pcall(function()
        local data = ai_orders()
        for _, o in ipairs(df.global.world.manager_orders.all) do
            if not had[o.id] then data.ids[tostring(o.id)] = true end
        end
        save_ai_orders(data)
    end)
    res.report = txt(tostring(o2 or ''):gsub('%s+$', ''):sub(1, 300))
    if res.orders_made <= 0 then
        res.ok, res.rejected = false, true
        res.error = 'the instruments tool made no work order for ' .. txt(pick.name) .. ': ' .. res.report:sub(1, 120)
    end
    return res
end

-- (0.104.69) Instrument orders piled up (one a month asked, none counted as
-- queued): those the instruments tool makes (a custom reaction MAKE_<entity>
-- IN...), not yet begun, beyond `keep`, are cancelled; the rest become the
-- AI's.
function act_trim_instrument_orders(a)
    local keep = int_in(a.keep or 1, 0, 10)
    if not keep then return reject('trim_instrument_orders: keep 0-10') end
    local all = df.global.world.manager_orders.all
    local mine, cancelled = {}, 0
    for _, o in ipairs(all) do
        local okr, r = pcall(function() return o.reaction_name end)
        if okr and type(r) == 'string' and r:match('^MAKE_ENT%d+ IN') then table.insert(mine, o) end
    end
    local data = ai_orders()
    -- begun ones (some made) first: they are kept
    table.sort(mine, function(x, y)
        local bx, by = x.amount_left < x.amount_total, y.amount_left < y.amount_total
        if bx ~= by then return bx end
        return x.id < y.id
    end)
    for i, o in ipairs(mine) do
        if i > keep and o.amount_left == o.amount_total then
            if not a.dry_run then
                data.ids[tostring(o.id)] = true
                save_ai_orders(data)
                local r = act_cancel_work_order({order_id = o.id})
                if r and r.ok then cancelled = cancelled + 1 end
                data = ai_orders()
            else
                cancelled = cancelled + 1
            end
        elseif not a.dry_run then
            data.ids[tostring(o.id)] = true
        end
    end
    if not a.dry_run then save_ai_orders(data) end
    return {ok = true, found = #mine, cancelled = cancelled, kept = #mine - cancelled, dry_run = a.dry_run or nil}
end

-- (0.104.10) free time: an "everybody" work detail narrowed to a crew, or back (lua/ai-labor.lua)
function act_narrow_detail(a)
    if a.job ~= 'farming' and a.job ~= 'gathering' then return reject('narrow_detail: job must be farming or gathering') end
    if a.widen == true then return reqscript('ai-labor').widen(a.job, a.dry_run == true) end
    local n = int_in(a.keep or 5, 1, 30)
    if not n then return reject('narrow_detail needs keep 1-30') end
    return reqscript('ai-labor').narrow(a.job, n, a.dry_run == true, txt)
end

-- (0.104.166) a detail cut back to the few the job needs (lua/ai-labor.lua trim)
function act_trim_labor(a)
    if a.job ~= 'fishing' then return reject('trim_labor: job must be fishing') end
    local n = int_in(a.keep == nil and 2 or a.keep, 0, 30)
    if not n then return reject('trim_labor needs keep 0-30') end
    return reqscript('ai-labor').trim(a.job, n, a.dry_run == true, txt)
end

-- (0.104.139, phase 11) Fights among the fort's own: DF's conflicts drag
-- friends and kin in and turn lethal (Teacheroar: 460 citizens killed by
-- citizens in five days, 356 strangled, 87% within a minute of another
-- death, none of it a crime). DFHack's fix/loyaltycascade (51.11+) takes the
-- citizens out of their conflicts and clears their enemy marks.
function act_break_fights(a)
    if not dfhack.findScript('fix/loyaltycascade') then
        return {ok = false, rejected = true, error = 'this DFHack has no fix/loyaltycascade'}
    end
    if a.dry_run then return {ok = true, dry_run = true} end
    local output, rv = dfhack.run_command_silent('fix/loyaltycascade')
    output = tostring(output or ''):gsub('%s+$', '')
    if rv ~= CR_OK then return {ok = false, error = 'fix/loyaltycascade failed: ' .. output:sub(1, 200)} end
    local n = 0
    for _ in output:gmatch('[^\n]+') do n = n + 1 end
    return {ok = true, lines = n, report = output:sub(1, 400)}
end

-- (0.104.0) Old remains rot away when the game runs slowly from too many
-- items: DFHack's deteriorate for non-entombed corpses and body parts nobody
-- can craft with (its defaults). Usable parts (bones, hair, wool) and food are
-- left alone; entombed dead are never touched. Stays on in this save.
function act_prune_remains(a)
    if not dfhack.findScript('deteriorate') then
        return {ok = false, error = 'DFHack has no deteriorate script in this version'}
    end
    -- (0.104.115) and, asked for by name: worn clothes thrown on the floor
    -- ('clothes': only on the ground and worn, never armour) and usable parts
    -- ('usable-parts': Teacheroar held 7,227 butchered bones and shells on the
    -- ground, 6,627 dead creatures still on the map's books)
    local cats = {'corpses', 'unusable-parts'}
    for _, c in ipairs(type(a.extra) == 'table' and a.extra or {}) do
        if c == 'clothes' or c == 'usable-parts' then table.insert(cats, c) end
    end
    if a.dry_run then return {ok = true, dry_run = true, categories = cats} end
    local out, rv = dfhack.run_command_silent('deteriorate', 'enable', table.concat(cats, ','))
    if rv ~= CR_OK then
        return {ok = false, error = 'deteriorate failed: ' .. tostring(out):sub(1, 160)}
    end
    out, rv = dfhack.run_command_silent('enable', 'deteriorate')
    if rv ~= CR_OK then
        return {ok = false, error = 'enable deteriorate failed: ' .. tostring(out):sub(1, 160)}
    end
    return {ok = true, categories = cats, said = tostring(out):sub(1, 200)}
end

-- An office filled by the AI (lua/ai-nobles.lua): manager, bookkeeper,
-- broker, chief medical dwarf; read back through DFHack, undone if unseen.
function act_appoint(a)
    if type(a.office) ~= 'string' then return reject('appoint needs office') end
    return reqscript('ai-nobles').appoint(a.office, a.dry_run == true, txt)
end

-- A new squad, led by an appointed militia commander or captain (lua/ai-military.lua).
function act_make_squad(a)
    return reqscript('ai-military').make_squad(a.dry_run == true, txt)
end

-- A vein of the metal the fort needs marked for digging (lua/ai-industry.lua).
function act_mine_ore(a)
    if type(a.metal) ~= 'string' or not a.metal:match('^[A-Z_]+$') then return reject('mine_ore needs metal') end
    local n = int_in(a.count or 40, 1, 80)       -- (0.105.9) 80: Mining's top (E asked 80, refused 30 times)
    if not n then return reject('mine_ore needs count 1-80') end
    return reqscript('ai-industry').mine(a.metal, n, a.dry_run == true)
end

-- Take down a gate the AI built at an entrance that wasn't one (lua/ai-gates.lua).
function act_clear_gate(a)
    local x, y, z = whole_number(a.x), whole_number(a.y), whole_number(a.z)
    if not (x and y and z) then return reject('clear_gate needs x, y, z') end
    local pieces = type(a.pieces) == 'table' and a.pieces or nil
    return reqscript('ai-gates').clear_gate(x, y, z, pieces, a.dry_run == true)
end

-- Goods to the depot for a caravan (lua/ai-trade.lua); the trade is yours.
function act_bring_goods(a)
    -- (0.104.78) up to 120 at a time: the finished-goods piles full of crafts
    local n = int_in(a.count or 40, 1, 120)
    if not n then return reject('bring_goods needs count 1-120') end
    return reqscript('ai-trade').bring(n, a.dry_run == true, txt, a.keep_treasures == true, a.keep_trinkets == true)
end

-- (0.103.8) The fort's goods left in the depot after the caravans: back out.
function act_unload_depot(a)
    local n = int_in(a.max or 50, 1, 200)
    if not n then return reject('unload_depot needs max 1-200') end
    return reqscript('ai-trade').unload(n, a.dry_run == true, txt)
end

-- A deal ticked on the open trade screen, and the Trade button pressed if
-- asked and calibrated (lua/ai-trade.lua). wants: {{key, count}} in order.
function act_trade_deal(a)
    local wants = {}
    for _, w in ipairs(type(a.wants) == 'table' and a.wants or {}) do
        local n = int_in(w.count, 1, 500)
        if type(w.key) ~= 'string' or not n then return reject('trade_deal wants {key, count 1-500}') end
        table.insert(wants, {key = w.key, count = n})
    end
    if #wants == 0 then return reject('trade_deal needs wants') end
    local margin = tonumber(a.margin) or 1.2
    if margin < 1.0 or margin > 3 then return reject('trade_deal margin must be 1.0-3') end
    local T = reqscript('ai-trade')
    -- (0.100, security pass) a trade screen the player opened is the
    -- player's: the AI neither ticks goods there nor presses Trade
    if not a.dry_run and a.force ~= true and not T.opened_by_ai() then
        return reject('the player opened this trade screen: the AI leaves the deal to them')
    end
    local r = T.deal(wants, margin, a.dry_run == true, txt)
    -- nothing to buy (or turned down before): the screen closed, if asked
    if r.rejected and a.close == true and not a.dry_run and T.opened_by_ai() then
        local c = T.close_screen()
        r.closed = c.closed
    end
    if r.ok and not r.waiting and not a.dry_run and a.press == true and r.calibrated then
        local p = T.press('Trade', txt)
        r.press = p
        r.answer, r.traded, r.counter, r.closed = p.answer, p.traded, p.counter, p.closed
    end
    return r
end

-- Recreational crafting turned on at a Craftsdwarf's workshop (lua/ai-society.lua).
function act_idle_crafting(a)
    return reqscript('ai-society').idle_crafting(a.dry_run == true)
end

-- Survey the water near the fort (lua/ai-water.lua): kept in the save. In
-- slices: each call scans for at most ~0.15 s and says "done = false" until
-- the survey is finished; then the cistern plan, one fort level a call
-- (the lag pass: the whole survey froze the game ~1.4 s, the plan up to 3 s).
WATER_PLAN = WATER_PLAN or nil
function act_survey_water(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    local W = reqscript('ai-water')
    local now = abs_tick()
    if not WATER_PLAN then
        local r = W.scan_step(now)
        if not r.ok then return r end
        if not r.done then return {ok = true, done = false, scanning = true, left = r.left} end
        WATER_PLAN = {i = 1}
        return {ok = true, done = false, planning = true}
    end
    local B = reqscript('ai-builder')
    local i = WATER_PLAN.i
    -- (0.105.3) Hammerstirred (2 Nov): the brain's cistern_tunnel_max (the pool 53-66 tiles off)
    local tun = whole_number(a.tunnel)
    local okp, plan, why = pcall(B.plan_cistern, i, i, {tunnel = tun and math.max(2, math.min(tun, 80)) or nil})
    if okp and plan and (not WATER_PLAN.best or plan.score < WATER_PLAN.best.score) then WATER_PLAN.best = plan end
    if okp and not plan and why then WATER_PLAN.why = WATER_PLAN.why or why end
    if not okp then WATER_PLAN.why = tostring(plan):sub(1, 160) end
    if i < (B.CISTERN_LEVELS or 6) then
        WATER_PLAN.i = i + 1
        return {ok = true, done = false, planning = true, level = i}
    end
    local r = W.last() or {ok = true}
    r.cistern = WATER_PLAN.best or {none = true, why = WATER_PLAN.why or 'no still, fresh water on the level under a fort level'}
    WATER_PLAN = nil
    pcall(dfhack.persistent.saveSiteData, 'ai-overseer/water', r)
    local kinds = {}
    for _, bd in ipairs(r.bodies or {}) do table.insert(kinds, ('%s %d'):format(bd.kind, bd.tiles)) end
    return {ok = true, done = true, bodies = kinds, aquifer = r.aquifer, magma = r.magma, cistern = r.cistern}
end

-- The cistern (lua/ai-builder.lua): one step of building it, or keeping it filled.
function act_cistern_step(a)
    if a.shut == true then return reqscript('ai-builder').cistern_shut(a.dry_run == true) end
    -- (0.104.145) what the brain knows that weighs the source: the climate
    -- freezes, a danger in the caverns
    local prefs = type(a.prefs) == 'table' and {freezes = a.prefs.freezes == true,
                                               cavern_danger = a.prefs.cavern_danger == true} or nil
    -- (0.105.3) the tunnel's reach, as the survey planned it (Hammerstirred's pool 53-66 tiles off)
    local tun = whole_number(a.tunnel)
    return reqscript('ai-builder').cistern_step(a.dry_run == true, prefs, tun and math.max(2, math.min(tun, 80)) or nil)
end

-- (0.105.0) Water works and magma (lua/ai-waterworks.lua): one step of the
-- moat, the pump stack, the muddied farm level or a magma workshop, or its
-- floodgate shut at once (shut) or the work retired.
function act_water_work(a)
    local kinds = reqscript('ai-waterworks').KINDS
    if not kinds[a.kind] then return reject('water_work: kind is moat, pump, irrigation or magma') end
    if a.shop ~= nil and not reqscript('ai-waterworks').MAGMA_SHOPS[a.shop] then
        return reject('water_work: shop is MagmaForge, MagmaSmelter or MagmaGlassFurnace')
    end
    return reqscript('ai-waterworks').step(a.kind, {dry_run = a.dry_run == true, shut = a.shut == true,
        retire = a.retire == true, shop = a.shop, plain = a.plain == true,
        why = type(a.why) == 'string' and a.why:sub(1, 120) or nil})
end

-- (0.84) a vacant post at a location (hospital staff, scribes, the tavern keeper)
function act_staff_location(a)
    local id = whole_number(a.location_id)
    if not id or type(a.post) ~= 'string' then return reject('staff_location needs location_id and post') end
    return reqscript('ai-society').staff_location(id, a.post, a.dry_run == true, txt)
end

-- (0.92) give a hall still being dug to another petition: project_id and
-- one of profession, deity_hf, religion
function act_retarget_hall(a)
    local id = whole_number(a.project_id)
    if not id then return reject('retarget_hall needs project_id') end
    local t = {}
    if a.profession ~= nil then
        if type(a.profession) ~= 'string' or df.profession[a.profession] == nil then return reject('unknown profession') end
        t.profession = a.profession
    elseif a.deity_hf ~= nil then
        t.deity_hf = whole_number(a.deity_hf)
        if not t.deity_hf or not df.historical_figure.find(t.deity_hf) then return reject('no such deity') end
    elseif a.religion ~= nil then
        t.religion = whole_number(a.religion)
        if not t.religion or not df.historical_entity.find(t.religion) then return reject('no such religion') end
    else
        return reject('retarget_hall needs profession, deity_hf or religion')
    end
    return reqscript('ai-builder').retarget_hall(id, t, a.dry_run == true)
end

-- (0.89) answer a temple or guildhall petition: id, accept (true/false)
function act_answer_petition(a)
    if type(a.accept) ~= 'boolean' then return reject('answer_petition needs id (or ids) and accept true|false') end
    -- (0.105.9) ids: up to 25 at once (old residency petitions by the hundred)
    if type(a.ids) == 'table' then
        local ids = {}
        for _, v in ipairs(a.ids) do
            local n = whole_number(v)
            if not n then return reject('answer_petition: ids are whole numbers') end
            table.insert(ids, n)
        end
        if #ids == 0 or #ids > 25 then return reject('answer_petition needs 1-25 ids') end
        local out = {ok = true, answered = 0, refused = {}, accepted = a.accept or nil, dry_run = a.dry_run or nil}
        for _, n in ipairs(ids) do
            local r = answer_petition(n, a.accept, a.dry_run == true)
            if r.ok then out.answered = out.answered + 1
            else table.insert(out.refused, {id = n, error = r.error}) end
        end
        if #out.refused == 0 then out.refused = nil end
        out.ok = out.answered > 0
        if not out.ok then out.error = 'no petition answered'; out.rejected = true end
        return out
    end
    local id = whole_number(a.id)
    if not id then return reject('answer_petition needs id (or ids) and accept true|false') end
    return answer_petition(id, a.accept, a.dry_run == true)
end

-- (0.88) alerts: {TYPE = ticks | false, default = ticks}; max 1-100
function act_dismiss_alerts(a)
    local n = whole_number(a.max)
    if not n or n < 1 or n > 100 then return reject('dismiss_alerts needs max 1-100') end
    if type(a.ages) ~= 'table' then return reject('dismiss_alerts needs ages {TYPE = ticks, default = ticks}') end
    local ages = {}
    for k, v in pairs(a.ages) do
        if type(k) ~= 'string' or not (k == 'default' or df.announcement_alert_type[k] ~= nil) then
            return reject('unknown alert type: ' .. tostring(k))
        end
        local t = whole_number(v)
        if v == false then ages[k] = false
        elseif t and t >= 0 then ages[k] = t
        else return reject('alert ages are whole ticks or false') end
    end
    return reqscript('ai-reports').dismiss_alerts(ages, n, a.dry_run == true)
end

-- (0.104.45) Water the dwarves walk over: a river or pond freezes in winter,
-- the dwarves cross the ice, and it thaws under them (Enxah: the drowned lie
-- in the river channel past the main stair; SUFFOCATE and DROWN 6 a year).
-- The tile above every water or ice tile on the given levels, within
-- `radius` of (cx, cy), gets the game's "restricted" traffic, so paths go
-- round it (a bridge or a way across stays usable: restricted only costs).
-- Never a tile the player marked high or low.
function act_restrict_water(a)
    local zs = type(a.levels) == 'table' and a.levels or {}
    local cx, cy = whole_number(a.x), whole_number(a.y)
    local r = whole_number(a.radius) or 60
    if #zs == 0 or #zs > 6 or not cx or not cy or r < 5 or r > 120 then
        return reject('levels (1-6), x, y and radius 5-120 needed')
    end
    local sx, sy, sz = dfhack.maps.getTileSize()
    local marked, seen = 0, 0
    for _, z0 in ipairs(zs) do
        local z = whole_number(z0)
        if z and z >= 0 and z + 1 < sz then
            for y = math.max(0, cy - r), math.min(sy - 1, cy + r) do
                for x = math.max(0, cx - r), math.min(sx - 1, cx + r) do
                    pcall(function()
                        local pos = xyz2pos(x, y, z)
                        local d = dfhack.maps.getTileFlags(pos)
                        local wet = d and d.flow_size > 0 and not d.liquid_type
                        if not wet then
                            local tt = dfhack.maps.getTileType(pos)
                            wet = tt and df.tiletype.attrs[tt].material == df.tiletype_material.FROZEN_LIQUID
                        end
                        if wet then
                            seen = seen + 1
                            local up = dfhack.maps.getTileFlags(xyz2pos(x, y, z + 1))
                            if up and up.traffic == df.tile_traffic.Normal then
                                if not a.dry_run then up.traffic = df.tile_traffic.Restricted end
                                marked = marked + 1
                            end
                        end
                    end)
                end
            end
        end
    end
    if seen == 0 then return reject('no water or ice on those levels near the fort') end
    if marked == 0 then
        -- (0.104.138) nothing left to do is not a failure: the brain rests it long
        return {ok = false, rejected = true, nothing_to_do = true,
                error = ('all %d tiles over the water are already restricted (or set by hand)'):format(seen)}
    end
    return {ok = true, marked = marked, water_tiles = seen, dry_run = a.dry_run or nil}
end

-- (0.104.42) Memorial slabs that never get put up: the construction of the
-- slab (a building the AI placed) suspended, or the engraved slab itself
-- forbidden (Enxah: 9 ghosts, 5 MurderousGhosts among them, each with its
-- slab made; 5 slab buildings suspended at stage 0, 4 slabs forbidden;
-- 25 of 36 deaths in a year from fright). The slabs unforbidden where the
-- dwarves can reach them, the slab buildings' jobs resumed.
function act_free_slabs(a)
    local from = citizen_anchor()
    local unforbid, resumed, cleared, moved = 0, 0, 0, 0
    for _, it in ipairs(df.global.world.items.other.SLAB) do
        pcall(function()
            if it.engraving_type == df.slab_engraving_type.Memorial and not it.flags.in_building then
                if not it.flags.in_job then
                    local x, y, z = dfhack.items.getPosition(it)
                    local reach = x and (not from or dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z)))
                    if x and not reach and from and not it.flags.in_inventory then
                        -- (0.104.49) shut in the rock (Enxah's oldest ghost's slab lay
                        -- inside a wall tile, a wall built over where it lay): brought
                        -- out to where a dwarf stands, the way it would have been carried
                        if not a.dry_run and dfhack.items.moveToGround(it, from) then
                            moved = moved + 1
                            it.flags.forbid = false
                        end
                    elseif it.flags.forbid and reach then
                        if not a.dry_run then it.flags.forbid = false end
                        unforbid = unforbid + 1
                    end
                end
                for _, ref in ipairs(it.specific_refs) do
                    if ref.type == df.specific_ref_type.JOB then
                        local j = ref.data.job
                        local h = dfhack.job.getHolder(j)
                        if j.flags.suspend and h and h:getType() == df.building_type.Slab then
                            -- (0.104.47) suspendmanager: "Blocked by an unmovable item":
                            -- what lies on the site is unforbidden, so the builder can
                            -- clear it (never the slab itself, an artifact, or an item
                            -- on someone's job)
                            pcall(function()
                                local own = {}
                                for _, ji in ipairs(j.items) do own[ji.item.id] = true end
                                local bx, by, bz = h.centerx, h.centery, h.z
                                for _, iid in ipairs(dfhack.maps.getTileBlock(bx, by, bz).items) do
                                    local o = df.item.find(iid)
                                    if o and not own[o.id] and o.pos.x == bx and o.pos.y == by and o.pos.z == bz
                                            and not o.flags.in_job and not o.flags.artifact then
                                        if not a.dry_run then o.flags.forbid = false end
                                        cleared = cleared + 1
                                    end
                                end
                            end)
                            if not a.dry_run then j.flags.suspend = false end
                            resumed = resumed + 1
                        end
                    end
                end
            end
        end)
    end
    if unforbid + resumed + moved == 0 then return reject('no memorial slab forbidden, shut in or held by a suspended job') end
    return {ok = true, unforbidden = unforbid, resumed = resumed, cleared = cleared, moved = moved, dry_run = a.dry_run or nil}
end

-- (0.103.16) Engraved memorial slabs built, so the ghosts rest.
function act_place_slabs(a)
    local n = int_in(a.max or 5, 1, 20)
    if not n then return reject('place_slabs needs max 1-20') end
    return reqscript('ai-builder').place_slabs(n, a.dry_run == true)
end

-- (0.88) one piece of furniture into a zone: zone_id, what (traction_bench)
function act_place_in_zone(a)
    local id = whole_number(a.zone_id)
    if not id then return reject('place_in_zone needs zone_id') end
    local B = reqscript('ai-builder')
    if not B.ZONE_FURNITURE[a.what] then
        return reject('place_in_zone: what must be one of ' .. table.concat(sorted_keys(B.ZONE_FURNITURE), ', '))
    end
    return B.place_in_zone(id, a.what, a.dry_run == true)
end

function act_vacate_post(a)    -- (0.104.111) a doctor who is a patient gives his post back
    local id, uid = whole_number(a.location_id), whole_number(a.unit_id)
    if not id or not uid then return reject('vacate_post needs location_id and unit_id') end
    return reqscript('ai-society').vacate_post(id, uid, a.dry_run == true, txt)
end

-- (0.87.3) a post's labours for its holders (the game's screen turns them on)
function act_staff_labors(a)
    local id = whole_number(a.location_id)
    if not id then return reject('staff_labors needs location_id') end
    return reqscript('ai-society').staff_labors(id, a.dry_run == true, txt)
end

-- (0.85) posts at a location the game hasn't made yet (as its screen does)
function act_add_posts(a)
    local id = whole_number(a.location_id)
    if not id then return reject('add_posts needs location_id') end
    local kinds = type(a.posts) == 'table' and a.posts or nil
    return reqscript('ai-society').add_posts(id, kinds, a.dry_run == true)
end

-- Trinkets for dwarves who want to own things (lua/ai-society.lua).
function act_give_trinkets(a)
    local n = whole_number(a.max) or 10
    if n < 1 or n > 50 then return reject('give_trinkets needs max 1-50') end
    return reqscript('ai-society').give_trinkets(n, a.dry_run == true)
end

-- (0.104.168) One bedroom per household (a couple in two keeps the better,
-- one with none gets the best free one), and up to `upgrade` of the most
-- stressed moved to a free room much better for them (their likes counted)
-- (lua/ai-homes.lua). {house = 0-30, upgrade = 0-20}
function act_house_dwarves(a)
    local h, u = int_in(a.house or 0, 0, 30), int_in(a.upgrade or 0, 0, 20)
    if not h or not u or h + u == 0 then return reject('house_dwarves needs house 0-30 and upgrade 0-20, not both 0') end
    return reqscript('ai-homes').house(h, u, a.dry_run == true, txt)
end

-- Workshops the fort has far too many of, taken down (lua/ai-builder.lua).
function act_remove_workshops(a)
    if a.kind ~= 'SoapMaker' and a.kind ~= 'ScrewPress' then
        return reject('remove_workshops needs kind SoapMaker|ScrewPress')
    end
    local keep, max = whole_number(a.keep) or 1, whole_number(a.max) or 20
    return reqscript('ai-builder').remove_workshops(a.kind, keep, math.min(max, 40), a.dry_run == true)
end

-- A feeder stockpile beside a workshop (or goods beside the depot) (lua/ai-builder.lua).
function act_feeder_pile(a)
    local id = whole_number(a.building_id)
    if not id then return reject('feeder_pile needs building_id') end
    return reqscript('ai-builder').place_feeder(id, a.dry_run == true)
end

-- The trade screen opened from the depot (lua/ai-trade.lua), or closed.
function act_open_trade(a)
    return reqscript('ai-trade').open_screen(a.dry_run == true, txt)
end

-- (0.104.0) DF's meeting screen (a diplomat or the liaison) holds the game
-- until someone answers; nobody is at the game in an unattended run, so after
-- a long wait the overseer leaves it, as the player would with Esc: the
-- meeting ends without an agreement. Only that screen is ever left.
function meeting_focus()
    local ok, f = pcall(function() return dfhack.gui.getCurFocus(true)[1] end)
    f = ok and tostring(f or '') or ''
    local low = f:lower()
    return (low:find('meeting', 1, true) or low:find('diplomacy', 1, true)) and f or nil
end

-- (0.104.95) a sand collection zone (for glass), placed by the builder
function act_sand_zone(a)
    return reqscript('ai-builder').sand_zone(a.dry_run == true)
end

-- (0.104.2) A Water Source zone for the injured while there is no well (lua/ai-builder.lua).
function act_water_zone(a)
    if type(a.points) ~= 'table' or #a.points == 0 or #a.points > 6 then
        return reject('water_zone needs points: 1-6 water tiles {x, y, z}')
    end
    local pts = {}
    for _, p in ipairs(a.points) do
        local x, y, z = int_in(p.x, 0, 1000), int_in(p.y, 0, 1000), int_in(p.z, 0, 1000)
        if not (x and y and z) then return reject('water_zone: a point needs whole x, y and z') end
        table.insert(pts, {x = x, y = y, z = z})
    end
    return reqscript('ai-builder').water_zone(pts, a.dry_run == true)
end

function act_close_meeting(a)
    local f = meeting_focus()
    if not f then return {ok = false, rejected = true, error = 'no meeting screen is open'} end
    if a.dry_run then return {ok = true, dry_run = true, screen = f} end
    pcall(function()
        require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
    end)
    local after = meeting_focus()
    return {ok = after == nil, screen = f, error = after and ('the meeting screen is still open (' .. after .. ')') or nil}
end

-- (0.105.0, 12b) The meeting screen answered with the AI's defaults (trade
-- and peace agreed, the elves' tree quota kept, tribute by the Rules choice,
-- the requests' wishes ticked), through the buttons the player showed the AI
-- once (lua/ai-diplomacy.lua). Each open screen is written to
-- meeting-probe.json. tribute: small | pay | refuse; wishes: DF's request
-- categories (entity_sell_category names), at most 20.
function act_answer_meeting(a)
    if a.tribute ~= nil and a.tribute ~= 'small' and a.tribute ~= 'pay' and a.tribute ~= 'refuse' then
        return reject('answer_meeting: tribute is small, pay or refuse')
    end
    if a.wishes ~= nil then
        if type(a.wishes) ~= 'table' or #a.wishes > 20 then return reject('answer_meeting: wishes is a list of up to 20') end
        for _, w in ipairs(a.wishes) do
            if type(w) ~= 'string' or not w:match('^%a+$') then return reject('answer_meeting: a wish is a category name') end
        end
    end
    return reqscript('ai-diplomacy').answer_meeting({tribute = a.tribute, wishes = a.wishes, dry_run = a.dry_run == true}, txt)
end

-- (0.105.24, 13b) The messenger sent on "Make contact" to a site, by driving
-- DF's World screen as the player does (lua/ai-mission-send.lua). Only with
-- the Rules switch send_messenger on; the steps run over the next frames and
-- stop (the screen shut) at the first one that differs from what was
-- recorded; the outcome shows in the `missions` report's `send`.
function act_send_mission(a)
    if a.goal ~= nil and a.goal ~= 'make_contact' then return reject('send_mission: goal is make_contact') end
    local site = int_in(a.site_id, 0, 1000000)
    if not site then return reject('send_mission needs site_id: a site\'s id') end
    return reqscript('ai-mission-send').start({goal = 'make_contact', site_id = site, dry_run = a.dry_run == true})
end

function act_close_trade(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    if not reqscript('ai-trade').opened_by_ai() and a.force ~= true then
        return reject('the player opened this trade screen: left open')
    end
    return reqscript('ai-trade').close_screen(a.unloading == true)
end

-- Someone to the depot for a caravan: the broker asked for, anyone after
-- `wait_ticks` (lua/ai-trade.lua).
function act_call_trader(a)
    local wait = int_in(a.wait_ticks or 1200, 0, 403200)
    if not wait then return reject('call_trader wait_ticks must be 0-403200') end
    return reqscript('ai-trade').call_trader(abs_tick(), wait,
                                             a.dry_run == true, txt)
end

-- A noble given a free room of the kind its office asks for (lua/ai-nobles.lua).
function act_give_room(a)
    local id = whole_number(a.unit_id)
    if not id or type(a.kind) ~= 'string' then return reject('give_room needs unit_id and kind') end
    return reqscript('ai-nobles').give_room(id, a.kind, a.dry_run == true, txt)
end

function act_squad_release(a)
    local id = whole_number(a.unit_id)
    if not id then return reject('squad_release needs unit_id') end
    return reqscript('ai-military').release(id, a.dry_run == true, txt, a.mother == true)
end

-- (0.104.65) A swap: a soldier trained enough goes back to work and the
-- place goes at once to the keenest outside (the fill puts those longing to
-- train first); a release alone left the squads short (34 soldiers, 31 wanted
-- after the release, so no fill came).
function act_squad_swap(a)
    local id = whole_number(a.unit_id)
    if not id then return reject('squad_swap needs unit_id') end
    local u = df.unit.find(id)
    local sid = u and u.military.squad_id or -1
    if sid == -1 then return reject('not in a squad') end
    local M = reqscript('ai-military')
    local r = M.release(id, a.dry_run == true, txt)
    if not r.ok or a.dry_run then return r end
    -- (0.104.138) never the one just sent home, nor those sent home lately
    local avoid = {[id] = true}
    for _, v in ipairs(type(a.avoid) == 'table' and a.avoid or {}) do
        local n = whole_number(v)
        if n then avoid[n] = true end
    end
    local okf, f = pcall(M.fill, sid, 1, txt, avoid, a.strict == true)   -- (0.104.168) strict in a crisis
    return {ok = true, released = r.name, squad_id = sid, filled = okf and f or tostring(f)}
end

function act_squad_trim(a)
    local n = int_in(a.count, 1, 5)
    if not n then return reject('squad_trim needs count 1-5') end
    return reqscript('ai-military').trim(n, a.dry_run == true, txt)
end

function act_squad_fill(a)
    local id, n = whole_number(a.squad_id), int_in(a.count, 1, 10)
    if not id or not n then return reject('squad_fill needs squad_id and count 1-10') end
    local avoid = {}                                  -- (0.104.138) those sent home lately
    for _, v in ipairs(type(a.avoid) == 'table' and a.avoid or {}) do
        local u = whole_number(v)
        if u then avoid[u] = true end
    end
    return reqscript('ai-military').fill(id, n, txt, avoid, a.strict == true, a.keen_only == true)   -- (0.104.168)
end

-- A squad given a barracks to train in (lua/ai-military.lua).
function act_squad_barracks(a)
    local sid, zid = whole_number(a.squad_id), whole_number(a.zone_id)
    if not sid or not zid then return reject('squad_barracks needs squad_id and zone_id') end
    return reqscript('ai-military').assign_barracks(sid, zid, a.dry_run == true)
end

-- (0.87) DF's standing orders that answer residency and citizenship
-- petitions: each 0 (ask) or 1 (accept); refused unless every one reads 0
-- or 1 now (anything else would mean the game uses these values otherwise)
function act_petition_orders(a)
    if type(a.orders) ~= 'table' then return reject('petition_orders needs orders {kind = 0|1}') end
    local cur, set = {}, {}
    for _, k in ipairs(PETITION_ORDERS) do
        local okv, v = pcall(function() return df.global[petition_order_name(k)] end)
        if not okv or (v ~= 0 and v ~= 1) then
            return {ok = false, rejected = true, error = 'standing order ' .. k .. ' reads ' .. tostring(v) .. ', not 0 or 1: left alone'}
        end
        cur[k] = v
    end
    for k, v in pairs(a.orders) do
        if cur[k] == nil or (v ~= 0 and v ~= 1) then return reject('petition_orders: unknown ' .. tostring(k) .. '=' .. tostring(v)) end
        if cur[k] ~= v then set[k] = v end
    end
    if a.dry_run then return {ok = true, dry_run = true, would_set = set, now = cur} end
    for k, v in pairs(set) do df.global[petition_order_name(k)] = v end
    for k, v in pairs(set) do
        if df.global[petition_order_name(k)] ~= v then return {ok = false, error = 'the game did not keep ' .. k} end
    end
    return {ok = true, set = next(set) and set or nil, was = cur}
end

-- A squad given one of the fort's uniform templates (lua/ai-military.lua).
function act_set_uniform(a)
    local id = whole_number(a.squad_id)
    if not id or (a.kind ~= 'leather' and a.kind ~= 'metal') then
        return reject('set_uniform needs squad_id and kind leather or metal')
    end
    return reqscript('ai-military').set_uniform(id, a.kind, a.dry_run == true, txt, a.ranged == true)
end

-- (0.82) mark the uniform of a squad the AI made (copied before 0.82) as the AI's
function act_adopt_uniform(a)
    local id = whole_number(a.squad_id)
    if not id then return reject('adopt_uniform needs squad_id') end
    return reqscript('ai-military').adopt_uniform(id, a.dry_run == true, txt)
end

-- Let the masons and crafters use one kind of economic stone (DF's stone
-- settings): never an ore.
function act_allow_stone(a)
    if type(a.stone) ~= 'string' or not a.stone:match('^[%u%d_]+$') then return reject('allow_stone needs stone (a token)') end
    local economic = df.global.plotinfo.economic_stone
    local raws = df.global.world.raws.inorganics.all or df.global.world.raws.inorganics
    for idx, inorg in ipairs(raws) do
        if inorg.id == a.stone then
            if a.keep == true then
                -- back to "economic": kept from ordinary jobs (coal for coke)
                if idx < #economic and economic[idx] and economic[idx] ~= 0 then
                    return {ok = false, rejected = true, error = a.stone .. ' is kept already'}
                end
                if a.dry_run == true then return {ok = true, dry_run = true, stone = a.stone, keep = true} end
                local ok = pcall(function() economic[idx] = true end)
                if not ok then pcall(function() economic[idx] = 1 end) end
                return {ok = true, stone = a.stone, keep = true}
            end
            -- (0.104.124) an ore only when the brain asks for it by name with ore = true
            -- (Teacheroar: 13 ghosts and 38 dead with no stone for slabs or coffins, 197 iron-ore boulders)
            if #inorg.metal_ore.mat_index > 0 and a.ore ~= true then return reject(a.stone .. ' is an ore: kept for the smelter') end
            if FUEL_STONES[a.stone] then return reject(a.stone .. ' is coal: kept for coke') end
            if not (idx < #economic and economic[idx] and economic[idx] ~= 0) then
                return {ok = false, rejected = true, error = a.stone .. ' may already be used'}
            end
            if a.dry_run == true then return {ok = true, dry_run = true, stone = a.stone} end
            local ok = pcall(function() economic[idx] = false end)
            if not ok then pcall(function() economic[idx] = 0 end) end
            local now_econ = economic[idx] and economic[idx] ~= 0
            if now_econ then return {ok = false, error = 'the game kept ' .. a.stone .. ' economic'} end
            return {ok = true, stone = a.stone}
        end
    end
    return reject('no such stone: ' .. a.stone)
end

-- A small chamber dug in ordinary stone, for boulders (lua/ai-industry.lua).
function act_quarry(a)
    local n = int_in(a.count or 30, 1, 30)
    if not n then return reject('quarry needs count 1-30') end
    return reqscript('ai-industry').quarry(n, a.dry_run == true)
end

-- A squad's uniform weapon made one kind (lua/ai-military.lua).
function act_set_uniform_weapon(a)
    local id = whole_number(a.squad_id)
    if not id or type(a.weapon) ~= 'string' or not a.weapon:match('^ITEM_WEAPON_[%u_]+$') then
        return reject('set_uniform_weapon needs squad_id and weapon (ITEM_WEAPON_...)')
    end
    return reqscript('ai-military').set_uniform_weapon(id, a.weapon, a.dry_run == true)
end

function act_squad_routine(a)
    local id = whole_number(a.squad_id)
    if not id or type(a.routine) ~= 'string' then return reject('squad_routine needs squad_id and routine') end
    return reqscript('ai-military').set_routine(id, a.routine)
end

function act_squad_orders(a)
    local id = whole_number(a.squad_id)
    if not id then return reject('squad_orders needs squad_id') end
    if a.clear == true then return reqscript('ai-military').orders(id, nil, true) end
    if type(a.kill) ~= 'table' or #a.kill == 0 or #a.kill > 50 then
        return reject('squad_orders needs kill: a list of 1-50 unit ids, or clear: true')
    end
    local ids = {}
    for _, v in ipairs(a.kill) do
        local n = whole_number(v)
        if not n then return reject('kill must list unit ids') end
        table.insert(ids, n)
    end
    return reqscript('ai-military').orders(id, ids, false)
end

function act_pull_gate(a)
    local id = whole_number(a.lever_id)
    if not id then return reject('pull_gate needs lever_id') end
    return reqscript('ai-military').pull_gate(id)
end

-- (0.105.4) apply_preset: a named preset (built-in or saved) applied to the
-- fort's settings exactly as the window's Load preset does (traits, Extreme,
-- the Rules it carries; ai-overseer-settings apply_preset), saved with its
-- name in the fort's site data. For keeper.py --preset: six runs from one
-- embark, one preset each. A dry run saves nothing. An unknown name is
-- refused, naming the known ones. Allowed while halted (DISPLAY_ONLY): it
-- changes the player's settings, as the window may, not the fort.
function act_apply_preset(a)
    if type(a.name) ~= 'string' or a.name == '' then return reject('apply_preset needs a preset name') end
    local S = reqscript('ai-overseer-settings')
    local before = S.current_preset()
    local merged, rules = S.apply_preset(a.name, nil, 'keeper', a.dry_run == true)
    if not merged then return reject(rules) end
    local ai = S.for_ai(merged)
    ai.preset = a.dry_run == true and before or a.name
    return {ok = true, preset = a.name, previous = before, dry_run = a.dry_run == true or nil,
            traits = ai.traits, extreme = ai.extreme, rules = rules, settings = ai}
end

-- (0.105.20) The Rules tab's on/off switches set from outside the window
-- (logs/rules-request.json, read by the overseer): only keys whose default is
-- true or false, each to true or false. Returns what changed.
function act_set_rules(a)
    if type(a.rules) ~= 'table' then return reject('set_rules needs rules: {name = true|false}') end
    local S = reqscript('ai-overseer-settings')
    local defs = S.defaults()
    local cur = S.load_settings()
    local changed, unknown = {}, {}
    -- (0.105.27) a cycle named in RULE_CHOICES (disposal) takes one of its choices
    local function choice_ok(k, v)
        local choices = type(k) == 'string' and type(S.RULE_CHOICES) == 'table' and S.RULE_CHOICES[k]
        if type(choices) ~= 'table' or type(v) ~= 'string' then return false end
        for _, c in ipairs(choices) do if c == v then return true end end
        return false
    end
    for k, v in pairs(a.rules) do
        if not choice_ok(k, v) and (type(k) ~= 'string' or type(defs[k]) ~= 'boolean' or type(v) ~= 'boolean') then
            table.insert(unknown, tostring(k))
        elseif cur[k] ~= v then
            changed[k] = {old = cur[k], new = v}
            cur[k] = v
        end
    end
    if #unknown > 0 then
        table.sort(unknown)
        return reject('set_rules: not an on/off switch (or a choice of disposal) of the Rules tab: '
                      .. table.concat(unknown, ', '))
    end
    if next(changed) and a.dry_run ~= true then S.save_settings(cur) end
    return {ok = true, changed = changed, dry_run = a.dry_run == true or nil}
end

---------------------------------------------------------------------------
-- (0.105.27) Disposal (lua/ai-disposal.lua): the forbidden things lying
-- about let go, melted, dumped, or (the dump's) removed; DF's standing
-- orders on refuse; a dump zone placed. Every item action leaves alone what
-- lies near danger, everything during a siege, the sealed caverns, the
-- cistern's tiles, artifacts, a living dwarf's things and (without
-- player_items) what no game reason explains.
---------------------------------------------------------------------------

local DISPOSAL_REASONS = {own_dead = true, used_ammo = true, other_dead = true, dumped = true, unknown = true}
local DUMP_REASONS = {own_dead = true, used_ammo = true, other_dead = true, free = true, unknown = true}

-- opts for the item actions: reasons (a list from `allowed`), max (1..500),
-- player_items (bool); or nil, error
local function disposal_opts(a, allowed, name)
    local o = {}
    if a.reasons ~= nil then
        o.reasons = string_list(a.reasons, allowed, 10)
        if not o.reasons then
            return nil, ('%s: reasons is a list of %s'):format(name, table.concat(sorted_keys(allowed), ', '))
        end
    end
    if a.max ~= nil then
        o.max = int_in(a.max, 1, 500)
        if not o.max then return nil, name .. ': max is 1-500' end
    end
    for _, k in ipairs({'player_items', 'keep_masterwork', 'keep_enemy_gear'}) do
        if a[k] ~= nil and type(a[k]) ~= 'boolean' then return nil, ('%s: %s is true or false'):format(name, k) end
        o[k] = a[k]
    end
    return o
end

function act_unforbid_items(a)
    local o, err = disposal_opts(a, DISPOSAL_REASONS, 'unforbid_items')
    if not o then return reject(err) end
    return reqscript('ai-disposal').unforbid_items(o, a.dry_run == true)
end

-- The marks set, then (not in a dry run) a smelter work order "melt a metal
-- object" when one is needed: DF 50 makes no melt job by itself (DF wiki,
-- Melt: "the job order will still need to be made at a smelter").
function act_mark_melt(a)
    local o, err = disposal_opts(a, {}, 'mark_melt')
    if not o then return reject(err) end
    local r = reqscript('ai-disposal').mark_melt(o, a.dry_run == true)
    if r.needs_order and a.dry_run ~= true then
        local want = math.max(1, math.min((r.n or 0) + (r.already or 0), 20))
        local ok, wo = pcall(act_work_order, {type = 'work_order', recipe = 'melt_metal', amount = want})
        if ok and type(wo) == 'table' and wo.ok then
            r.melt_order, r.order_added = wo.order_id, want
            r.ok, r.rejected, r.error = true, nil, nil
        else
            r.order_error = ok and type(wo) == 'table' and wo.error or tostring(wo)
        end
    end
    return r
end

function act_mark_dump(a)
    local o, err = disposal_opts(a, DUMP_REASONS, 'mark_dump')
    if not o then return reject(err) end
    return reqscript('ai-disposal').mark_dump(o, a.dry_run == true)
end

function act_empty_dump(a)
    local o, err = disposal_opts(a, {}, 'empty_dump')
    if not o then return reject(err) end
    return reqscript('ai-disposal').empty_dump(o, a.dry_run == true)
end

function act_set_standing_orders(a)
    if type(a.orders) ~= 'table' then return reject('set_standing_orders needs orders {name = 0|1}') end
    return reqscript('ai-disposal').set_standing_orders(a.orders, a.dry_run == true)
end

-- A garbage dump zone: on the surface, or (inside = true) in a dug room near
-- the entrance. The builder places it (ai-builder-surface place_dump_zone,
-- group settings'); refused while the fort has one of that kind already.
-- place_dump_zone(inside, dry_run) is expected to return a table as
-- place_surface does: {ok = true, kind = 'dump', x, y, z or elevation,
-- inside, dry_run} or {ok = false, rejected?, waiting?, error}.
function act_place_dump(a)
    if a.inside ~= nil and type(a.inside) ~= 'boolean' then return reject('place_dump: inside is true or false') end
    local inside = a.inside == true
    local okz, zones = pcall(function() return reqscript('ai-disposal').dump_zones() end)
    if okz then
        for _, zn in ipairs(zones) do
            if zn.inside == inside then
                return {ok = false, rejected = true, nothing_to_do = true, stale = {'disposal'}, zone_id = zn.id,
                        error = ('the fort has a garbage dump %s already (zone %d at x%d y%d)')
                            :format(inside and 'inside' or 'outside', zn.id, zn.x, zn.y)}
            end
        end
    end
    local okb, B = pcall(reqscript, 'ai-builder')
    if not okb or type(B) ~= 'table' or type(B.place_dump_zone) ~= 'function' then
        return {ok = false, error = 'the builder has no place_dump_zone (ai-builder-surface.lua is older than this bridge)'}
    end
    local ok, r = pcall(B.place_dump_zone, inside, a.dry_run == true)
    if not ok then return {ok = false, error = 'place_dump_zone failed: ' .. tostring(r):sub(1, 300)} end
    if type(r) ~= 'table' then return {ok = false, error = 'place_dump_zone returned ' .. type(r) .. ', not a table'} end
    if r.ok == nil then r.ok = false end
    r.inside = inside
    return r
end
