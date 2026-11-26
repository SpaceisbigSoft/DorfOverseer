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
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-actions'] = '0.105.131'   -- (0.105.26) bumped with BRIDGE_VERSION

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
    -- (0.105.99) never a body by a live danger, nor one the AI forbade on its
    -- cistern's tiles (ai-util near_danger, cistern_tiles): those forbids stand
    local spots, cistern = {}, {}
    pcall(function()
        local U = reqscript('ai-util')
        spots, cistern = U.danger_spots(), U.cistern_tiles()
    end)
    local kept = 0
    for _, it in ipairs(df.global.world.items.other.CORPSE) do
        if n >= max then break end
        local ok, r = pcall(function() return it.race end)
        if ok and r == race and it.flags.forbid and not it.flags.in_building and not it.flags.removed
                and not it.flags.in_job then
            local x, y, z = dfhack.items.getPosition(it)
            local okk, keep = pcall(function()
                return x ~= nil and (cistern[x .. ',' .. y .. ',' .. z]
                    or reqscript('ai-util').near_danger(spots, x, y, z)) and true or false
            end)
            if okk and keep then
                kept = kept + 1
            elseif x and from and dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z)) then
                if not a.dry_run then it.flags.forbid = false end
                n = n + 1
            end
        end
    end
    if n == 0 then
        return reject(kept > 0 and ('the %d forbidden bodies left lie by a live danger or on the cistern\'s tiles: '
            .. 'left forbidden'):format(kept) or 'no forbidden body of the fort\'s the dwarves can reach')
    end
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
        if p.kind == 'tombs' and type(p.area) == 'table' then
            -- (F4, S2) a floor tomb level: its own rooms only (ar.own), never a neighbour's in its box
            local oko, own = pcall(function() return reqscript('ai-builder').own_areas(p) end)
            if oko and type(own) == 'table' then
                for _, ar in ipairs(own) do table.insert(areas, ar) end
            else
                table.insert(areas, p.area)
            end
        end
    end
    -- (0.105.47) and the coffins the AI put on its other levels (lua/ai-welfare.lua)
    pcall(function()
        for _, ar in ipairs(reqscript('ai-welfare').corner_areas()) do table.insert(areas, ar) end
    end)
    if #areas == 0 then return reject('no tomb level of the AI\'s') end
    local n = 0
    for _, z in ipairs(df.global.world.buildings.all) do
        if z:getType() == df.building_type.Civzone and z.type == df.civzone_type.Tomb then
            local mine = false
            for _, ar in ipairs(areas) do
                if z.z == ar.z and z.x1 >= ar.x1 and z.x2 <= ar.x2 and z.y1 >= ar.y1 and z.y2 <= ar.y2
                        and (type(ar.own) ~= 'function' or ar.own(z)) then mine = true end
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
    -- (0.105.48, K3) halted: only lowered (run_action's release_only)
    if a.release_only and a.on then
        return {ok = false, rejected = true, halted = true, error = 'the AI is halted in the game: the alarm only lowered'}
    end
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
        -- (item4) not drawn again when drawn within the last day (a.refresh: always)
        local okr, rr = pcall(function() return reqscript('ai-society').refresh_shelter_due(a.refresh == true) end)
        -- (r9) never sounded into an AI shelter that covers nothing (a redraw
        -- that found no tiles and had none to put back, or one that failed):
        -- every civilian would be sent to an empty burrow
        local oke, empty = pcall(function() return reqscript('ai-society').shelter_empty() end)
        if oke and empty then
            return {ok = false, rejected = true, error = 'the AI shelter covers no tiles: the alarm not sounded',
                    shelter = okr and rr or nil, shelter_error = (not okr) and tostring(rr):sub(1, 120) or nil}
        end
        civ.sound_alarm()
        -- (0.105.48, K3) the alarm the AI's: booked with the fort, so the game
        -- itself lowers it when the AI is halted or away (ai-status's watcher)
        if df.global.plotinfo.alerts.civ_alert_idx ~= 0 then
            pcall(function() reqscript('ai-society').note_ai_alarm(true) end)
        end
        return {ok = true, on = df.global.plotinfo.alerts.civ_alert_idx ~= 0,
                shelter = okr and rr or nil, shelter_error = (not okr) and tostring(rr):sub(1, 120) or nil}
    else
        civ.clear_alarm()
        pcall(function() reqscript('ai-society').note_ai_alarm(false) end)   -- (0.105.48, K3)
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
    -- (D0 G4) the hall shapes are the layouts' own list (ai-layouts.HALLS), as the customs are
    local okh, halls = pcall(function() return reqscript('ai-layouts').HALLS end)
    if not (okh and type(halls) == 'table') then
        halls = {plain = true, rounded = true, pillared = true,
                 octagonal = true, round = true, cruciform = true, nave = true}
    end
    local hall = st.hall or 'plain'
    if type(hall) ~= 'string' or not halls[hall] then
        local names = {}
        for k in pairs(halls) do table.insert(names, k) end
        table.sort(names)
        return nil, 'style.hall must be one of: ' .. table.concat(names, ', ')
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
    -- (D0 G4, the Design track; d0-spec 1.4) optional, each sent only when not its default
    local scale, aspect, arms, motif, grand
    if st.scale ~= nil then
        scale = int_in(st.scale, 80, 150)
        if not scale then return nil, 'style.scale must be 80-150 (per cent)' end
    end
    if st.aspect ~= nil then
        if st.aspect ~= 'square' and st.aspect ~= 'long' and st.aspect ~= 'wide' then
            return nil, 'style.aspect must be square, long or wide'
        end
        aspect = st.aspect
    end
    if st.arms ~= nil then
        if st.arms ~= 'corridor' and st.arms ~= 'cross' and st.arms ~= 'ring' then
            return nil, 'style.arms must be corridor, cross or ring'
        end
        arms = st.arms
    end
    if st.motif ~= nil then
        local forms = {rows = true, ring = true, cross = true, spiral = true, star = true, wave = true}
        if type(st.motif) ~= 'string' or not forms[st.motif] then
            return nil, 'style.motif must be one of: cross, ring, rows, spiral, star, wave (a form, not a symbol)'
        end
        motif = st.motif
    end
    if st.grand ~= nil then
        if type(st.grand) ~= 'boolean' then return nil, 'style.grand must be true or false' end
        grand = st.grand
    end
    local customs        -- (0.105.29) fort customs the layouts read; unknown names dropped
    for _, c in ipairs(type(st.customs) == 'table' and st.customs or {}) do
        -- (0.105.33) the layouts' own list (ai-layouts.LAYOUT_CUSTOMS), so a new custom isn't dropped here
        local okl, known = pcall(function() return reqscript('ai-layouts').LAYOUT_CUSTOMS end)
        if type(c) == 'string' and (okl and type(known) == 'table' and known[c]
                or not (okl and type(known) == 'table') and (c == 'cloister' or c == 'armoury' or c == 'ore_piles')) then
            customs = customs or {}; table.insert(customs, c)
        end
    end
    return {hall = hall, smooth = smooth, statues = statues, entry_door = st.entry_door == true,
            spacing = spacing, orient = orient, rhythm = rhythm, customs = customs,
            scale = scale, aspect = aspect, arms = arms, motif = motif, grand = grand}
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

-- (layout B) The overseer's hint for the hallway-first floors (the `floor`
-- key of start_project, beside `plan`, which stays the classic search's
-- hint). Returns hint, error: nil when none was given (the builder makes its
-- own plain hint), false for "place this one the classic way", else a cleaned
-- table: unknown keys dropped, a known key of a wrong type or range refused
-- with its name. The ranges are ai-floorplan's grammar (G).
local FLOOR_INTS = {     -- key = {lo, hi}
    gap = {1, 4}, kind_gap = {0, 6}, lead = {0, 8}, ahead = {0, 3}, run_max = {12, 80}, run_min = {4, 30},
    arms_max = {1, 4}, stagger = {0, 6}, tries = {4, 60}, full_retry_days = {1, 336},
    pile_w = {3, 11}, piles_new = {0, 3},
}
local FLOOR_WORDS = {    -- key = {the words, in the order the error names them}
    zone = {'near', 'mid', 'far', 'any'},
    sides = {'both', 'one', 'alternate'},
    turns = {'left', 'right', 'alternate', 'both'},
}
local FLOOR_LISTS = {    -- key = {the words, the most of them}: a list of distinct words
    dirs = {{'north', 'south', 'east', 'west'}, 4},
    grow = {{'arm', 'turn'}, 2},
}
local FLOOR_BOOLS = {'balance', 'axial', 'neck', 'spill'}   -- (r3 g2) spill: false keeps a full floor to its arms_max
local FLOOR_NAMES = {'tag', 'group'}

local function floor_has(words, v)
    if type(v) ~= 'string' then return false end
    for _, w in ipairs(words) do if w == v then return true end end
    return false
end

function parse_floor(v)
    if v == nil then return nil end
    if v == false then return false end
    if type(v) ~= 'table' then return nil, 'floor must be an object or false' end
    local out = {}
    if v.elevs ~= nil then
        if type(v.elevs) ~= 'table' then return nil, 'floor.elevs must be a list of 1-6 whole numbers, -400 to 400' end
        local list, n = {}, 0
        for _ in pairs(v.elevs) do n = n + 1 end
        for _, e in ipairs(v.elevs) do
            -- (a number only: int_in alone would take the string '12')
            local z = type(e) == 'number' and int_in(e, -400, 400) or nil
            if not z then return nil, 'floor.elevs must be a list of 1-6 whole numbers, -400 to 400' end
            table.insert(list, z)
        end
        if #list < 1 or #list > 6 or n ~= #list then
            return nil, 'floor.elevs must be a list of 1-6 whole numbers, -400 to 400'
        end
        out.elevs = list
    end
    for _, k in ipairs(FLOOR_NAMES) do
        if v[k] ~= nil then
            if type(v[k]) ~= 'string' or not v[k]:match('^[a-z_]+$') or #v[k] > 24 then
                return nil, ('floor.%s must be 1-24 of the letters a-z and _'):format(k)
            end
            out[k] = v[k]
        end
    end
    if v.spine ~= nil then
        local sp = type(v.spine) == 'table' and v.spine or {}
        local x = type(sp.x) == 'number' and int_in(sp.x, 0, 999) or nil
        local y = type(sp.y) == 'number' and int_in(sp.y, 0, 999) or nil
        if not x or not y then return nil, 'floor.spine must be x and y, 0-999' end
        out.spine = {x = x, y = y}
    end
    for _, k in ipairs(sorted_keys(FLOOR_LISTS)) do
        if v[k] ~= nil then
            local words, most = FLOOR_LISTS[k][1], FLOOR_LISTS[k][2]
            local msg = ('floor.%s must be a list of 1-%d distinct names from %s'):format(k, most, table.concat(words, ', '))
            if type(v[k]) ~= 'table' then return nil, msg end
            local list, seen, n = {}, {}, 0
            for _ in pairs(v[k]) do n = n + 1 end
            for _, w in ipairs(v[k]) do
                if not floor_has(words, w) or seen[w] then return nil, msg end
                seen[w] = true
                table.insert(list, w)
            end
            if #list < 1 or #list > most or n ~= #list then return nil, msg end
            out[k] = list
        end
    end
    for _, k in ipairs(sorted_keys(FLOOR_WORDS)) do
        if v[k] ~= nil then
            if not floor_has(FLOOR_WORDS[k], v[k]) then
                return nil, ('floor.%s must be one of: %s'):format(k, table.concat(FLOOR_WORDS[k], ', '))
            end
            out[k] = v[k]
        end
    end
    for _, k in ipairs(sorted_keys(FLOOR_INTS)) do
        if v[k] ~= nil then
            local lo, hi = FLOOR_INTS[k][1], FLOOR_INTS[k][2]
            local n = type(v[k]) == 'number' and int_in(v[k], lo, hi) or nil
            if not n then return nil, ('floor.%s must be a whole number, %d-%d'):format(k, lo, hi) end
            out[k] = n
        end
    end
    if v.bay ~= nil then        -- 0: no rhythm; else every 3-6 slots
        local n = type(v.bay) == 'number' and int_in(v.bay, 0, 6) or nil
        if not n or n == 1 or n == 2 then return nil, 'floor.bay must be 0 or 3-6' end
        out.bay = n
    end
    if v.node ~= nil then
        local n = type(v.node) == 'number' and int_in(v.node, 3, 5) or nil
        if not n or n == 4 then return nil, 'floor.node must be 3 or 5' end
        out.node = n
    end
    for _, k in ipairs(FLOOR_BOOLS) do
        if v[k] ~= nil then
            if type(v[k]) ~= 'boolean' then return nil, ('floor.%s must be true or false'):format(k) end
            out[k] = v[k]
        end
    end
    -- (r3 g1) the floors tried on each stair after the first, and the other stairs a floor may hang on
    if v.stair_tries ~= nil then
        local n = type(v.stair_tries) == 'number' and int_in(v.stair_tries, 0, 3) or nil
        if not n then return nil, 'floor.stair_tries must be a whole number, 0-3' end
        out.stair_tries = n
    end
    if v.stairs ~= nil then
        local msg = 'floor.stairs must be a list of 1-6 stairs, each x and y 0-999'
        if type(v.stairs) ~= 'table' then return nil, msg end
        local list, n = {}, 0
        for _ in pairs(v.stairs) do n = n + 1 end
        for _, st in ipairs(v.stairs) do
            local x = type(st) == 'table' and type(st.x) == 'number' and int_in(st.x, 0, 999) or nil
            local y = type(st) == 'table' and type(st.y) == 'number' and int_in(st.y, 0, 999) or nil
            if not x or not y then return nil, msg end
            table.insert(list, {x = x, y = y})
        end
        if #list < 1 or #list > 6 or n ~= #list then return nil, msg end
        out.stairs = list
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
    elseif a.kind == 'were_cells' then       -- (0.105.115 item24) werebeast cells behind drawbridges
        p.cells = int_in(a.cells, 1, 8)
        if not p.cells then return reject('were_cells needs cells 1-8') end
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
        -- (0.105.54) a new level's free rooms (spare, the shops they are planned
        -- for: spare_for) and whether a standing level may take the shops (join)
        if a.spare ~= nil then
            p.spare = int_in(a.spare, 0, 8)
            if not p.spare then return reject('spare must be 0-8') end
        end
        if a.spare_for ~= nil then
            if type(a.spare_for) == 'table' and next(a.spare_for) == nil then
                p.spare_for = {}
            else
                p.spare_for = string_list(a.spare_for, layouts.WORKSHOPS, 8)
                if not p.spare_for then return reject('spare_for must list up to 8 workshops') end
            end
        end
        if a.join ~= nil then
            if a.join ~= false and a.join ~= true and a.join ~= 'band' then
                return reject('join must be true, false or "band"')
            end
            p.join = a.join
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
    local floor, ferr = parse_floor(a.floor)        -- (layout B) the floor hint; false: the classic placement
    if ferr then return reject(ferr) end
    p.floor = floor
    p.urgent = a.urgent == true or nil       -- a well's or a mood's workshop: one slot more
    p.mood = (a.mood == true and a.kind == 'workshops') or nil   -- (R1 g6) a waiting mood's shop: no slot taken
    -- (r2h4) the crossbow squad's Bowyer's workshop alone: no slot taken (B and E: refused by
    -- "already N unfinished building projects" while their crossbow squads had no crossbow)
    p.crossbows = (a.crossbows == true and a.kind == 'workshops' and type(p.shops) == 'table' and #p.shops == 1
                   and p.shops[1] == 'Bowyers') or nil
    -- (R2 h3) a small need (paper, mood, well, drink, meals): the needs' own pool of slots
    if a.need ~= nil then
        local kinds = reqscript('ai-builder').NEED_KINDS or {}
        if type(a.need) ~= 'string' or not kinds[a.need] then
            return reject('need must be one of: paper, mood, well, drink, meals')
        end
        p.need = a.need
    end
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
    local cooldown, tries = whole_number(a.cooldown_days), whole_number(a.site_tries)
    -- (0.105.38) a far bank: up to the brain's water_far_reach, else the map's width
    far_reach_of(a)
    local map_w = math.max(100, map_width())
    local half = whole_number(a.half)
    return reqscript('ai-builder').place_well({inside_only = a.inside_only == true, cavern = a.cavern == true,
                                               urgent = a.urgent == true,
                                               -- (r2 h2) the winter cistern: a chamber filled by bucket
                                               filled = a.filled == true and a.cavern ~= true or nil,
                                               half = half and math.max(1, math.min(half, 2)) or nil,
                                               -- (0.105.4 review) a cavern nobody has found: the Rules tab's say
                                               open_caverns = a.open_caverns == true,
                                               gallery = gallery and math.max(0, math.min(gallery, 80)) or nil,
                                               toward = toward,
                                               shore_reach = reach and math.max(0, math.min(reach, map_w)) or nil,
                                               -- (K48-K4b, A4 18) the brain's cooldown and site cap (ai-well-safety place_gate)
                                               cooldown_days = cooldown and math.max(0, math.min(cooldown, 3360)) or nil,
                                               site_tries = tries and math.max(1, math.min(tries, 20)) or nil},
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
    -- (0.105.47, R2 item 3) unit_id: only that culprit's cases (a chronic
    -- tantrum dwarf, the last resort: brain/planner_tantrums.py)
    local only
    if a.unit_id ~= nil then
        only = whole_number(a.unit_id)
        if not only then return reject('convict: unit_id is a unit id') end
    end
    -- (r9) disorderly: only disorderly-behaviour cases (the tantrum's own);
    -- the last resort took the culprit's first solved case of any kind (a
    -- production-order violation's sentence can be a beating or the hammer)
    local disorderly = a.disorderly == true
    local function kind_ok(c)
        if not disorderly then return true end
        local ok, k = pcall(function() return df.crime_type[c.mode] end)
        return ok and k == 'DisorderlyBehavior'
    end
    local site = df.global.plotinfo.site_id
    local list = df.global.world.crimes.all
    local busy = convict_busy(list)
    local picked = {}
    for i = 0, #list - 1 do
        if #picked >= max then break end
        local c = list[i]
        if convictable(c, site) and not busy[c.criminal] and (only == nil or c.criminal == only)
                and kind_ok(c) then
            table.insert(picked, c)
            busy[c.criminal] = true
        end
    end
    if #picked == 0 then
        return {ok = false, rejected = true, error = (only and 'no solved case of that culprit waits for a trial'
                                                         or 'no solved case waits for a trial')
                                                        .. (disorderly and ' (disorderly behaviour only)' or '')}
    end
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

-- (0.105.35) an AI level's marker-only (blueprint) dig tiles made real designations
function act_unmark_project_dig(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').unmark_project_dig(id, a.dry_run == true)
end

-- (0.105.31) a well level's channel nobody digs: its job renewed
function act_renew_well_dig(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').renew_well_dig(id, a.priority, a.dry_run == true)
end

-- (0.104.151) the cavern wells' stair columns closed: a hatch on each, locked
function act_seal_well_stairs(a)
    return reqscript('ai-builder').seal_well_stairs(a.dry_run == true)
end

-- (0.104.152) the cavern wells' shaft hatch: placed, linked to its lever, opened;
-- shut (at once) while a danger is in the caverns
function act_well_shaft(a)
    -- (group 2) dry: the brain says the fort is short of water (nil: unchanged)
    local dry = nil
    if a.dry ~= nil then dry = a.dry == true end
    -- (item2) keep_shut: the gates the brain keeps shut for a great beast in the
    -- cavern layer they open into (shut now if open; the watcher doesn't open them)
    local keep = nil
    if a.keep_shut ~= nil then
        if type(a.keep_shut) ~= 'table' then return reject('keep_shut must be a list of project ids') end
        keep = {}
        for _, v in ipairs(a.keep_shut) do
            local id = math.tointeger(v)
            if id then keep[id] = true end
        end
    end
    return reqscript('ai-builder').well_shaft_step(a.close == true, a.dry_run == true, dry, keep)
end

function act_finish_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    -- (R2 h3) drop: the building kinds a given-up level may lose besides its workshops
    local drop
    if a.drop ~= nil then
        if type(a.drop) ~= 'table' then return reject('drop must be a list of building kinds') end
        drop = {}
        for i, k in ipairs(a.drop) do
            if i > 12 then break end
            if type(k) ~= 'string' or not k:match('^%a+$') then return reject('drop must be a list of building kinds') end
            table.insert(drop, k)
        end
    end
    return reqscript('ai-builder').finish_project(id, a.decor_only == true, a.stalled == true,
                                                 a.give_up == true, drop,   -- (0.105.51; R2 h3)
                                                 a.leave_planned == true)   -- (r2h7)
end

-- (R2 h3) a level waiting on the same pieces for weeks parked: no building slot held
function act_park_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    if a.sig ~= nil and type(a.sig) ~= 'string' then return reject('sig must be text') end
    return reqscript('ai-builder').park_project(id, a.sig, a.dry_run == true)
end

-- The fort's culture, written by the overseer so the panel's Culture page can
-- show it (and so it travels with the save). Display only: nothing in the
-- game reads it.
CULTURE_KEY = 'ai-overseer/culture'
local CULTURE_ENUMS = {
    hall = {plain = true, rounded = true, pillared = true,
            octagonal = true, round = true, cruciform = true, nave = true},   -- (D0) the Design track's halls
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
    fort_run = true,   -- (0.105.48, K8) the run id (brain/fort_run.py): a fresh embark has none
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
    -- (D0) the design language in words (brain/design.py lines), for the panel
    local design = {}
    for _, x in ipairs(type(c.design) == 'table' and c.design or {}) do
        local t = says(x, 160)
        if t and #design < 6 then table.insert(design, t) end
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
        design = #design > 0 and design or nil,     -- (D0)
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

-- (r6) The local helper ai-bridge-actions-civic (loaded after this file) uses
-- too: the same function, handed on.
ACTIONS_PART_LOCALS = {string_list = string_list}
