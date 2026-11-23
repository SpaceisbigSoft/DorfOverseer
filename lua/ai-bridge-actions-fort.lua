-- ai-bridge-actions-fort: the action handlers for work-order libraries, webs, the census,
-- gates, the game left unattended, the shelter, prisoners, pastures, the
-- army, stairwells, labour, farms and the kitchen.
--
-- A part of ai-bridge.lua (r6, split out of ai-bridge-actions.lua when it was 204 KB),
-- loaded by it after ai-bridge-actions into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-actions files share with this one come from ACTIONS_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-actions-fort is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-actions-fort'] = '0.105.82'   -- bumped with BRIDGE_VERSION

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
    -- (r9) the cleanup report's dead counts made true now (lua/ai-cleanup.lua
    -- recount_dead): its last pass still counted the dead scrubbed here, and
    -- cleanup_dead_units was asked for them and refused 5 times in 5
    pcall(function() reqscript('ai-cleanup').recount_dead() end)
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

-- (0.105.30) wagon: the underground depot's road, a 3-wide drawbridge; sealed: a cavern opening walled for good (the Hermit)
local GATE_STYLES = {plain = true, narrow = true, fortified = true, gatehouse = true, grand = true, drawbridge = true,
                     wagon = true, sealed = true}

function act_fortify_entrance(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('fortify_entrance needs entrance_id') end
    if not GATE_STYLES[a.style] then return reject('fortify_entrance needs style plain|narrow|fortified|gatehouse|grand|drawbridge|wagon|sealed') end
    return reqscript('ai-gates').fortify(id, a.style)
end

-- A fresh embark: the fort's first staircase (lua/ai-builder.lua found_fort).
function act_found_fort(a)
    return reqscript('ai-builder').found_fort(a.dry_run == true, a.wide == true)   -- (0.105.35) wide: further out
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

-- (0.105.32) A gate that reads open but DF's walk map treats as shut (E: 64
-- dead at the founding stair's hatch): one step a call (lua/ai-gates.lua unstick_gate).
function act_unstick_gate(a)
    local id, step = whole_number(a.id), int_in(a.step, 1, 3)
    if not id or not step then return reject('unstick_gate needs id and step 1-3') end
    return reqscript('ai-gates').unstick_gate(id, step, a.dry_run == true, a.cavern_ok == true)
end

function act_arm_gates(a) return reqscript('ai-gates').arm() end
function act_open_gates(a) return reqscript('ai-gates').open_all() end

-- (0.105.34) One entrance opened for its stranded during a siege elsewhere.
function act_open_entrance(a)
    local id = tonumber(a.id)
    if not id then return reject('open_entrance needs the entrance id') end
    return reqscript('ai-gates').open_entrance(id, a.dry_run == true, a.cavern_ok == true)
end

-- (0.105.35) The gate watcher failing: the entrances an enemy is close to shut now.
function act_close_threatened_gates(a)
    return reqscript('ai-gates').close_threatened_gates(a.dry_run == true)
end

-- (0.105.35) A gate planned at an entrance, waiting with parts free: its building jobs unsuspended.
function act_free_gate_jobs(a)
    local id = tonumber(a.entrance_id)
    if not id then return reject('free_gate_jobs needs the entrance_id') end
    return reqscript('ai-gates').free_gate_jobs(id, a.dry_run == true, a.ai_plan == true)   -- (0.105.36)
end

-- (item4) Evil weather: the civilians kept inside the AI shelter's burrow
-- without the alarm (lua/ai-society-burrows.lua weather_keep_in); on = false
-- lets out those it put there.
function act_weather_burrow(a)
    if type(a.on) ~= 'boolean' then return reject('weather_burrow: on must be true or false') end
    if a.release_only and a.on then      -- (0.105.48, K3) halted: only let out
        return {ok = false, rejected = true, halted = true, error = 'the AI is halted in the game: the keep-in only let out'}
    end
    return reqscript('ai-society').weather_keep_in(a.on, a.dry_run == true, txt)
end

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
    if r.ok == nil then r.ok = true end      -- (r9) a redraw that found nothing: ok = false, the old tiles back
    return r
end

function act_set_population_cap(a)
    local cap = int_in(a.cap, 7, 1000)
    if not cap then return reject('set_population_cap needs cap 7-1000') end
    local strict = int_in(a.strict or (cap + 20), cap, 1100)
    if not strict then return reject('strict must be at least the cap') end
    -- (item5) DF's baby caps, raised (never lowered) for a fort under its floor
    local babies, pct
    if a.baby_cap ~= nil then
        babies = int_in(a.baby_cap, 1, 1000)
        if not babies then return reject('baby_cap must be 1-1000') end
    end
    if a.baby_pct ~= nil then
        pct = int_in(a.baby_pct, 1, 1000)
        if not pct then return reject('baby_pct must be 1-1000') end
    end
    return reqscript('ai-society').set_popcap(cap, strict, babies, pct)
end

-- (item5) Prisoners let go when the fort has no water for them: a citizen in
-- the jail drinks only what is carried from a well or a water zone, never
-- booze (Hammerstirred, the Hermit hold with no well: 9 office holders died
-- of thirst in their chains, one after another, y263-269). The sentence is
-- cut short to its last day; DF itself unchains them when it runs out.
-- ids: the prisoners (unit ids) to let go; none: every one serving time.
function act_release_prisoners(a)
    local want
    if a.ids ~= nil then
        if type(a.ids) ~= 'table' then return reject('ids must be a list of unit ids') end
        want = {}
        for _, v in ipairs(a.ids) do
            local id = whole_number(v)
            if not id then return reject('ids must be whole numbers') end
            want[id] = true
        end
    end
    local released, names = 0, {}
    local okp, err = pcall(function()
        for _, pu in ipairs(df.global.plotinfo.punishments) do
            if (pu.prison_counter or 0) > 1 then
                local u = punished_unit(pu)
                if u and (not want or want[u.id]) and dfhack.units.isCitizen(u) and not dfhack.units.isDead(u) then
                    pu.prison_counter = 1
                    released = released + 1
                    if #names < 5 then table.insert(names, txt(dfhack.units.getReadableName(u))) end
                end
            end
        end
    end)
    if not okp then return {ok = false, error = 'the punishments could not be read: ' .. tostring(err):sub(1, 120)} end
    if released == 0 then return reject('no citizen is serving time in the jail') end
    return {ok = true, released = released, names = names}
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

-- (r2h4) the free bolts onto the crossbow squads' ammunition entries
function act_assign_bolts(a)
    local n = int_in(a.limit or 20, 1, 50)
    if not n then return reject('assign_bolts: limit 1-50') end
    return reqscript('ai-military').assign_bolts(a.dry_run == true, n)
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
    -- (0.105.45) station: {x, y, z}: the squads stand there (between the
    -- threat and the civilians' shelter), not in the shelter
    local st = type(a.station) == 'table' and a.station or nil
    local sx, sy, sz
    if st then
        sx, sy, sz = int_in(st.x, 0, 1000), int_in(st.y, 0, 1000), int_in(st.z, 0, 1000)
        if not sx or not sy or not sz then return reject('shelter_squads: station needs x, y, z') end
    end
    for _, v in ipairs(a.squads) do
        local id = whole_number(v)
        if not id then return reject('shelter_squads: squads must be squad ids') end
        local r
        if st then
            r = M.station(id, sx, sy, sz, a.dry_run == true)
            out[tostring(id)] = r.ok and ('at x%d y%d z%d'):format(sx, sy, sz) or r.error
        else
            r = M.shelter(id, a.dry_run == true)
            out[tostring(id)] = r.ok and 'in the shelter' or r.error
        end
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

-- (0.105.32) An emergency way in for citizens stranded outside with no gate
-- to blame (lua/ai-builder-projects.lua dig_way_in): x, y, z of where they stand.
function act_dig_way_in(a)
    -- (0.105.33) second = true: a second way to the surface by design (no stranded spot)
    if a.second == true then
        -- (0.105.47) near {x, y}: the second way's top as near there as it may go (the Garden fort's fields)
        local near
        if a.near ~= nil then
            local nx = type(a.near) == 'table' and int_in(a.near.x, 0, 1000) or nil
            local ny = type(a.near) == 'table' and int_in(a.near.y, 0, 1000) or nil
            if not nx or not ny then return reject('dig_way_in: near is {x, y} on the map') end
            near = {x = nx, y = ny}
        end
        return reqscript('ai-builder').dig_way_in({second = true, near = near}, get_date(), a.dry_run == true)
    end
    local x, y, z = int_in(a.x, 0, 1000), int_in(a.y, 0, 1000), int_in(a.z, 0, 1000)
    if not x or not y or not z then return reject('dig_way_in needs x, y, z (where the stranded stand)') end
    return reqscript('ai-builder').dig_way_in({x = x, y = y, z = z}, get_date(), a.dry_run == true)
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

-- (0.105.33) the kitchen bans both rules share: `keys` excluded from cooking
-- (ban) and recorded under `key`, or the recorded ones lifted (only the AI's
-- own; false from addExclusion means the player's or ours is there already)
-- (r2h6) one kitchen exclusion (Cook) added (on) or removed: the one place
-- the AI touches DF's kitchen list (the bans below and the seed reserve)
local function kitchen_exclude(k, on)
    if on then return dfhack.kitchen.addExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) end
    return dfhack.kitchen.removeExclusion({Cook = true}, k.t, k.s, k.mt, k.mi)
end

-- (Y1, W2) One shared record of the AI's kitchen exclusions (site data
-- KITCHEN_HOLDS_KEY), one entry per exclusion (job, item type, subtype,
-- material) naming every AI reason that holds it: 'brewables', 'fat',
-- 'seed:<PLANT_ID>'. An exclusion is added when the first reason asks and
-- removed only when the last reason lets go; one that was there before the
-- AI asked (ai = false: the player's) is never removed. Before, each rule
-- kept its own list, and the seed reserve's plump helmet ban (its plant
-- already excluded by the brewables ban) was lifted with the brewables ban.
-- The three old per-rule records are taken over once (migrated).
KITCHEN_HOLDS_KEY = 'ai-overseer/kitchen-holds'
local KITCHEN_HOLDS_VERSION = 1

-- (numbers read back from the save may be floats: 53.0 is key 53)
local function knum(v) return math.tointeger(v) or v end

local function kitchen_key_id(k)
    return (k.j or 'cook') .. ':' .. tostring(knum(k.t)) .. ':' .. tostring(knum(k.s)) .. ':'
        .. tostring(knum(k.mt)) .. ':' .. tostring(knum(k.mi))
end

local function valid_kitchen_key(k)
    return type(k) == 'table' and type(k.t) == 'number' and type(k.s) == 'number'
        and type(k.mt) == 'number' and type(k.mi) == 'number'
end

local function old_bans(key)
    local ok, d = pcall(dfhack.persistent.getSiteData, key, {bans = {}})
    return ok and type(d) == 'table' and type(d.bans) == 'table' and d.bans or {}
end

-- holds[id] = {j, t, s, mt, mi, ai = true/false, reasons = {reason = true}}
local function migrate_kitchen_holds(holds, live)
    local function take(k, reason, ai)
        if not valid_kitchen_key(k) then return end
        local id = kitchen_key_id(k)
        local h = holds[id]
        if not h then
            local n = 0
            for _, o in pairs(holds) do if type(o.n) == 'number' and o.n > n then n = o.n end end
            h = {j = k.j or 'cook', t = k.t, s = k.s, mt = k.mt, mi = k.mi, ai = ai, reasons = {}, n = n + 1}
            holds[id] = h
        elseif ai then
            h.ai = true
        end
        h.reasons[reason] = true
    end
    for _, k in ipairs(old_bans(KITCHEN_KEY)) do take(k, 'brewables', true) end
    for _, k in ipairs(old_bans(KITCHEN_FAT_KEY)) do take(k, 'fat', true) end
    local seeds = old_bans(KITCHEN_SEED_KEY)
    local ids = {}
    for id, added in pairs(seeds) do
        id = tostring(id)
        table.insert(ids, id)
        for _, k in ipairs(type(added) == 'table' and added or {}) do take(k, 'seed:' .. id, true) end
        -- the plant's keys the old reserve found excluded already (not recorded
        -- then): held for it now too, as someone else's unless a reason above is the AI's
        local okp, keys = pcall(function()
            for _, p in ipairs(df.global.world.raws.plants.all) do
                if p.id == id then return plant_seed_keys(p) end
            end
            return {}
        end)
        for _, k in ipairs(okp and type(keys) == 'table' and keys or {}) do
            if valid_kitchen_key(k) and not holds[kitchen_key_id(k)] then
                -- (not on a dry run: it changes nothing)
                local oka, yes = false, false
                if live then oka, yes = pcall(kitchen_exclude, k, true) end
                take(k, 'seed:' .. id, oka and yes == true)
            elseif valid_kitchen_key(k) then
                take(k, 'seed:' .. id, false)
            end
        end
    end
    return ids
end

-- the old records cleared once the shared one is saved (the seed list kept
-- as the set of held plant ids)
local function clear_old_kitchen_records(ids)
    pcall(dfhack.persistent.saveSiteData, KITCHEN_KEY, {bans = {}})
    pcall(dfhack.persistent.saveSiteData, KITCHEN_FAT_KEY, {bans = {}})
    local set = {}
    for _, id in ipairs(ids) do set[id] = true end
    pcall(dfhack.persistent.saveSiteData, KITCHEN_SEED_KEY, {bans = set})
end

-- The shared record (migrated from the old ones the first time; on a dry
-- run the migration is only read, nothing written or excluded).
function kitchen_holds_load(dry_run)
    local ok, d = pcall(dfhack.persistent.getSiteData, KITCHEN_HOLDS_KEY, {})
    d = ok and type(d) == 'table' and d or {}
    local holds = type(d.holds) == 'table' and d.holds or {}
    local migrated
    if d.v ~= KITCHEN_HOLDS_VERSION then
        local okm, ids = pcall(migrate_kitchen_holds, holds, not dry_run)
        migrated = okm and ids or nil        -- (failed: the old records kept, tried again next time)
    end
    -- malformed entries dropped, the rest keyed afresh (whole numbers)
    local out = {}
    for _, h in pairs(holds) do
        if valid_kitchen_key(h) and type(h.reasons) == 'table' and next(h.reasons) ~= nil then
            h.t, h.s, h.mt, h.mi, h.n = knum(h.t), knum(h.s), knum(h.mt), knum(h.mi), knum(h.n)
            h.ai = h.ai == true
            local r = {}
            for reason, on in pairs(h.reasons) do if on then r[tostring(reason)] = true end end
            h.reasons = r
            if next(r) ~= nil then out[kitchen_key_id(h)] = h end
        end
    end
    if migrated and not dry_run then
        kitchen_holds_save(out)
        clear_old_kitchen_records(migrated)
    end
    return out
end

function kitchen_holds_save(holds)
    pcall(dfhack.persistent.saveSiteData, KITCHEN_HOLDS_KEY, {v = KITCHEN_HOLDS_VERSION, holds = holds})
end

-- `reason` holds exclusion k: true when the AI added it to DF's list now
function kitchen_hold(holds, k, reason)
    if not valid_kitchen_key(k) then return false end
    local id = kitchen_key_id(k)
    local h = holds[id]
    if h then
        h.reasons[reason] = true
        if not h.ai then
            -- the player's: if they have taken it off since, it is the AI's now
            local oka, yes = pcall(kitchen_exclude, h, true)
            if oka and yes == true then h.ai = true; return true end
        end
        return false
    end
    local oka, yes = pcall(kitchen_exclude, k, true)
    local added = oka and yes == true
    local n = 0
    for _, o in pairs(holds) do if type(o.n) == 'number' and o.n > n then n = o.n end end
    holds[id] = {j = k.j or 'cook', t = k.t, s = k.s, mt = k.mt, mi = k.mi, ai = added, reasons = {[reason] = true},
                 n = n + 1}
    return added
end

-- `reason` lets go of every exclusion it holds (or of k only): the ones no
-- reason holds any more are removed from DF's list if the AI added them.
-- Returns the number removed.
function kitchen_release(holds, reason, k)
    local removed = 0
    local ids = {}
    for id in pairs(holds) do table.insert(ids, id) end
    -- in the order they were held (the same order every time)
    table.sort(ids, function(x, y)
        local a, b = tonumber(holds[x].n) or 0, tonumber(holds[y].n) or 0
        if a ~= b then return a < b end
        return x < y
    end)
    for _, id in ipairs(ids) do
        local h = holds[id]
        if h.reasons[reason] and (k == nil or id == kitchen_key_id(k)) then
            h.reasons[reason] = nil
            if next(h.reasons) == nil then
                if h.ai then
                    local oka, yes = pcall(kitchen_exclude, h, false)
                    if oka and yes == true then removed = removed + 1 end
                end
                holds[id] = nil
            end
        end
    end
    return removed
end

local function kitchen_held_by(holds, reason)
    local n = 0
    for _, h in pairs(holds) do if h.reasons[reason] then n = n + 1 end end
    return n
end

-- (0.105.33) the kitchen bans of the brewables and fat rules: `keys` held
-- for `reason` (ban) or every key it holds let go (Y1: the shared record)
local function kitchen_ban(reason, keys, ban, dry_run)
    local holds = kitchen_holds_load(dry_run)
    if ban then
        if dry_run then return {ok = true, dry_run = true, kinds = #keys} end
        local added = 0
        for _, k in ipairs(keys) do
            if kitchen_hold(holds, k, reason) then added = added + 1 end
        end
        kitchen_holds_save(holds)
        return {ok = true, banned = added, kinds = #keys, held = kitchen_held_by(holds, reason)}
    end
    if dry_run then return {ok = true, dry_run = true, held = kitchen_held_by(holds, reason)} end
    local lifted = kitchen_release(holds, reason)
    kitchen_holds_save(holds)
    return {ok = true, lifted = lifted}
end

function act_kitchen_brewables(a)
    if type(a.ban) ~= 'boolean' then return reject('kitchen_brewables needs ban = true or false') end
    local keys = {}
    if a.ban then
        local ok, k = pcall(brewable_cook_keys)
        if not ok then return {ok = false, error = 'kitchen_brewables: ' .. tostring(k):sub(1, 120)} end
        keys = k
    end
    return kitchen_ban('brewables', keys, a.ban, a.dry_run)
end

-- (0.104.30) Fat and tallow kept from the cooks while the hospital has no
-- soap (Enxah: 149 fat, then 13 tallow, cooked into meals before any soap
-- was made, wounds festering): a kitchen exclusion for each kind in stock,
-- lifted with ban = false. Only the AI's own exclusions are lifted.
KITCHEN_FAT_KEY = 'ai-overseer/kitchen-fat'

function act_kitchen_fat(a)
    if type(a.ban) ~= 'boolean' then return reject('kitchen_fat needs ban = true or false') end
    local keys = {}
    if a.ban then
        local seen = {}
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
    end
    local r = kitchen_ban('fat', keys, a.ban, a.dry_run)
    if a.ban and not a.dry_run and r.banned == 0 and #keys == 0 then return reject('no fat or tallow in the fort') end
    return r
end

-- (r2h6) The seed reserve: a farmable crop whose seeds run low keeps its
-- plant and its seed from the cooks (DF's kitchen exclusions, Cook), so the
-- plants are brewed or eaten raw and give their seed back (DF: cooking
-- never leaves a seed; the plump helmet's spawn is itself cookable). The
-- audit (A1, 14-15 Nov): plump helmet seed 0-7 in every fort, A with 1,082
-- plump helmets in store and 1 seed, the underground plots dead. {ban =
-- {plant ids}, lift = {plant ids}, target = n}: each banned plant's
-- exclusions are held for it ('seed:<id>') in the shared record
-- (KITCHEN_HOLDS_KEY, Y1), KITCHEN_SEED_KEY keeping the set of plant ids;
-- one removed only when no AI reason holds it any more, a player's own never. With DFHack's seedwatch on, its
-- target for the banned plants is set to `target` too (seedwatch lifts
-- every exclusion of a plant above its own target).
KITCHEN_SEED_KEY = 'ai-overseer/kitchen-seeds'
SEED_RESERVE_PLANTS_MAX = 40     -- plant ids an action names at most

local function plant_raw_by_id(id)
    for _, p in ipairs(df.global.world.raws.plants.all) do
        if p.id == id then return p end
    end
    return nil
end

-- The kitchen keys of a plant and of its seed (each {t, s, mt, mi}).
function plant_seed_keys(p)
    local out = {}
    for _, m in ipairs(p.material) do
        if m.id == 'STRUCTURAL' then
            local mi = dfhack.matinfo.find(p.id, m.id)
            if mi then table.insert(out, {t = df.item_type.PLANT, s = -1, mt = mi.type, mi = mi.index}) end
            break
        end
    end
    local okd, st, si = pcall(function() return p.material_defs.type.seed, p.material_defs.idx.seed end)
    if okd and type(st) == 'number' and st >= 0 and type(si) == 'number' then
        table.insert(out, {t = df.item_type.SEEDS, s = -1, mt = st, mi = si})
    end
    return out
end

-- The plant ids whose seed bans the AI holds (sorted).
function seed_bans_held()
    local ok, data = pcall(dfhack.persistent.getSiteData, KITCHEN_SEED_KEY, {bans = {}})
    local out = {}
    if ok and type(data) == 'table' and type(data.bans) == 'table' then
        for id in pairs(data.bans) do table.insert(out, tostring(id)) end
    end
    table.sort(out)
    return out
end

local function id_list(v)
    local out = {}
    if type(v) ~= 'table' then return out end
    for _, id in ipairs(v) do
        if type(id) == 'string' and id ~= '' and #out < SEED_RESERVE_PLANTS_MAX then table.insert(out, id) end
    end
    return out
end

function act_seed_reserve(a)
    local ban, lift = id_list(a.ban), id_list(a.lift)
    if #ban == 0 and #lift == 0 then return reject('seed_reserve needs ban or lift (plant ids)') end
    -- (Y1, W2) the exclusions live in the shared record (one entry per key,
    -- every AI reason named); KITCHEN_SEED_KEY keeps the set of plant ids held
    local holds = kitchen_holds_load(a.dry_run)      -- (first: it migrates the old seed record)
    local data = dfhack.persistent.getSiteData(KITCHEN_SEED_KEY, {bans = {}})
    local bans = type(data.bans) == 'table' and data.bans or {}
    local res = {ok = true, banned = {}, lifted = {}, unknown = {}, dry_run = a.dry_run == true or nil}
    for _, id in ipairs(ban) do
        local p = plant_raw_by_id(id)
        if not p then
            table.insert(res.unknown, id)
        elseif bans[id] == nil then
            local okk, keys = pcall(plant_seed_keys, p)
            if okk and not a.dry_run then
                -- a key already excluded (the brewables ban, the player) is held too
                for _, k in ipairs(keys) do kitchen_hold(holds, k, 'seed:' .. id) end
            end
            if not a.dry_run then bans[id] = true end
            table.insert(res.banned, id)
        end
    end
    for _, id in ipairs(lift) do
        if bans[id] ~= nil then
            if not a.dry_run then
                kitchen_release(holds, 'seed:' .. id)
                bans[id] = nil
            end
            table.insert(res.lifted, id)
        end
    end
    if a.dry_run then return res end
    kitchen_holds_save(holds)
    pcall(dfhack.persistent.saveSiteData, KITCHEN_SEED_KEY, {bans = bans})
    -- seedwatch, when on, keeps the same line (else it lifts the ban above its own target)
    local target = math.tointeger(tonumber(a.target))
    if target and target > 0 and #res.banned > 0 then
        local okp, on = pcall(plugin_enabled, 'seedwatch')
        if okp and on == true then
            res.seedwatch = 0
            for _, id in ipairs(res.banned) do
                local okc, _, rv = pcall(dfhack.run_command_silent, 'seedwatch', id, tostring(target))
                if okc and rv == CR_OK then res.seedwatch = res.seedwatch + 1 end
            end
        end
    end
    if #res.banned == 0 and #res.lifted == 0 then
        res.ok, res.rejected = false, true
        res.error = #res.unknown > 0 and ('no such plant: ' .. table.concat(res.unknown, ', '))
            or 'the seed bans asked are held already (or were never the AI\'s)'
    end
    res.held = 0
    for _ in pairs(bans) do res.held = res.held + 1 end
    if #res.unknown == 0 then res.unknown = nil end
    return res
end
