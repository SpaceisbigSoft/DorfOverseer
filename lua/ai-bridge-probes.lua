-- ai-bridge-probes: the read-only probes (squads, defence, trade, meetings,
-- missions, justice, announcements, assumptions) and the screen-recording
-- commands (trade_here, meeting_here, mission_here, trade_press, test_threat).
--
-- A part of ai-bridge.lua (13c, when the 409 KB file was split), loaded by it
-- into its own environment: what is global here is the bridge's (reachable as
-- reqscript('ai-bridge').<name>), and the bridge's shared helpers (txt,
-- reject, int_in, whole_number, sorted_keys, abs_tick, translate_name,
-- in_fort, NOT_IN_FORT, OUT_DIR) are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-probes is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-probes'] = '0.105.31'   -- (0.105.26) bumped with BRIDGE_VERSION

local utils = require('utils')

-- ai-bridge probe: where this DF version keeps squad data (diagnostics).
function cmd_probe()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-military').probe() end)
    return {ok = true, probe = ok and r or tostring(r)}
end

-- The building ids that the given items (mechanisms) point to with a
-- reference of the given type (BUILDING_TRIGGER or BUILDING_TRIGGERTARGET).
local function probe_link_ids(items, ref_name)
    local ids = {}
    for _, it in ipairs(items or {}) do
        for _, ref in ipairs(it.general_refs or {}) do
            if df.general_ref_type[ref:getType()] == ref_name then table.insert(ids, ref.building_id) end
        end
    end
    return ids
end

-- DF's trade screen, read only (for automatic trading).
function cmd_probe_trade()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-trade').probe_screen(txt) end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    r.ok = true
    return r
end

-- (0.105.0, 12b) ai-bridge probe_meeting: the meeting screen, read only (also
-- written to meeting-probe.json); meeting_here Yes|No|Done: the mouse is on
-- that button of the open meeting screen, remember where.
function cmd_probe_meeting()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function()
        local D = reqscript('ai-diplomacy')
        local p = D.probe(txt)
        if p.state then D.save_probe(p) end
        return p
    end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    r.ok = true
    return r
end

function cmd_meeting_here(args)
    if not in_fort() then return NOT_IN_FORT end
    return reqscript('ai-diplomacy').calibrate((args or {})[1] or 'Yes')
end

-- (0.104.97, 13b) ai-bridge probe_missions: the World screen, read only
function cmd_probe_missions()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-missions').probe_screen() end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    r.ok = true
    return r
end

-- (0.105.24, 13b) ai-bridge mission_here World|Diplomacy: the mouse is on
-- that button (the toolbar's World button; Diplomacy on New mission),
-- remember where (lua/ai-mission-send.lua)
function cmd_mission_here(args)
    if not in_fort() then return NOT_IN_FORT end
    return reqscript('ai-mission-send').calibrate((args or {})[1] or 'World')
end

local function probe_plain(v)
    local tv = type(v)
    if tv == 'number' or tv == 'string' or tv == 'boolean' then return v end
    if tv == 'userdata' then
        local okn, n = pcall(function() return #v end)
        if okn and type(n) == 'number' then
            local first = {}
            for i = 0, math.min(n, 4) - 1 do
                local oke, e = pcall(function() return v[i] end)
                local te = oke and type(e)
                if te == 'number' or te == 'string' or te == 'boolean' then table.insert(first, e) end
            end
            return {n = n, first = (#first > 0) and first or nil}
        end
        local oks, s = pcall(tostring, v)
        return oks and s:sub(1, 60) or '?'
    end
    return nil
end

local function probe_fields(obj, limit)
    local out, n = {}, 0
    pcall(function()
        for k, v in pairs(obj) do
            if n >= (limit or 120) then break end
            local okv, pv = pcall(probe_plain, v)
            if okv and pv ~= nil then out[tostring(k)] = pv; n = n + 1 end
        end
    end)
    return out
end

-- (0.104.129, 12i) ai-bridge probe_justice: DF's Justice screen and the
-- crimes, read only (Teacheroar: 1,571 crimes, 399 waiting for a trial, 1
-- ever sentenced; DF convicts only from that screen). The player convicts one
-- case by hand while brain/probe_justice.py --watch records it.
function cmd_probe_justice()
    if not in_fort() then return NOT_IN_FORT end
    local out = {ok = true}
    pcall(function() out.focus = dfhack.gui.getCurFocus(true) end)
    pcall(function() out.mouse = {x = df.global.gps.mouse_x, y = df.global.gps.mouse_y} end)
    pcall(function()
        local info = df.global.game.main_interface.info
        out.info = probe_fields(info, 60)
        out.justice = probe_fields(info.justice, 150)
    end)
    -- every crime (not the newest 600), and the ones whose flags or plain
    -- fields changed since the last call (what a conviction writes)
    pcall(function()
        local list = df.global.world.crimes.all
        out.crimes = #list
        local sentenced, newest_sentenced = 0, nil
        local now, changed = {}, {}
        for i = #list - 1, 0, -1 do
            local cr = list[i]
            local f = {}
            pcall(function() for k, v in pairs(cr.flags) do if v == true then table.insert(f, k) end end end)
            table.sort(f)
            local sig = table.concat(f, ',') .. '|' .. tostring(cr.accused) .. '|' .. tostring(cr.criminal)
            now[cr.id] = sig
            if PROBE_CRIMES and PROBE_CRIMES[cr.id] ~= nil and PROBE_CRIMES[cr.id] ~= sig and #changed < 10 then
                local e = probe_fields(cr, 60)
                e.flags_now, e.was = table.concat(f, ','), PROBE_CRIMES[cr.id]
                pcall(function() e.convict_data = probe_fields(cr.convict_data, 30) end)
                pcall(function() e.punishment = probe_fields(cr.punishment, 30) end)
                table.insert(changed, e)
            end
            if cr.flags.sentenced then
                sentenced = sentenced + 1
                if not newest_sentenced then newest_sentenced = probe_fields(cr, 60) end
            end
        end
        PROBE_CRIMES = now
        out.sentenced = sentenced
        out.newest_sentenced = newest_sentenced
        if #changed > 0 then out.crimes_changed = changed end
    end)
    pcall(function() out.punishments = #df.global.plotinfo.punishments end)
    return out
end

-- The defence test (brain/defence_test.py): hostile invaders set down
-- outside. args: count race [--dry]
function cmd_test_threat(args)
    if not in_fort() then return NOT_IN_FORT end
    -- (0.100, security pass) real invaders: never while the AI is halted
    if reqscript('ai-status').is_halted() then
        return {ok = false, rejected = true, error = 'the AI is halted (the switch in the game): no test invaders'}
    end
    local flags = utils.invert(args or {})
    local n = tonumber((args or {})[1]) or 3
    local race = (args or {})[2]
    if race and (race:sub(1, 2) == '--' or not race:match('^[A-Z_]+$')) then race = nil end
    local r = reqscript('ai-military').spawn_test_threat(n, race, flags['--dry'] ~= nil)
    if r.ok == false and r.rejected then r.ok = true; r.refused = r.error; r.error = nil end
    return r
end

-- The mouse is on one of the trade screen's buttons: remember where.
function cmd_trade_here(args)
    if not in_fort() then return NOT_IN_FORT end
    local name = (args or {})[1] or 'Trade'
    if name ~= 'Trade' and name ~= 'Depot' then return {ok = false, error = 'buttons: Trade, Depot'} end
    return reqscript('ai-trade').calibrate(name)
end

-- Press the Trade button on the open screen (what's ticked is traded).
function cmd_trade_press()
    if not in_fort() then return NOT_IN_FORT end
    if reqscript('ai-status').is_halted() then return {ok = false, error = 'the AI is halted in the game'} end
    local r = reqscript('ai-trade').press('Trade', txt)
    if r.ok == false and r.rejected then r.ok = true; r.refused = r.error; r.error = nil end
    return r
end

-- What soldiers' uniforms ask for, what's assigned to them, what they carry.
function cmd_probe_squads()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-military').probe_squads(txt) end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    return {ok = true, soldiers = r}
end

function cmd_probe_occupations()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-society').probe_occupations(txt) end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    r.ok = true
    return r
end

-- ai-bridge probe_defence [x y z ...]: read-only facts milestone 5 needs from
-- this DF version before anything is built: whether the game has the job and
-- reference types a lever link uses, the building types of drawbridges,
-- hatches and traps, the fort's levers and what they are linked to, and
-- what stands on the given tiles (the blocked entrances). Changes nothing.
function cmd_probe_defence(args)
    if not in_fort() then return NOT_IN_FORT end
    local out = {}
    local function has_enum(enum, name)
        local ok, v = pcall(function() return enum[name] end)
        return ok and v ~= nil
    end
    out.job_types = {}
    for _, n in ipairs({'LinkBuildingToTrigger', 'PullLever', 'ConstructHatchCover', 'ConstructMechanisms'}) do
        out.job_types[n] = has_enum(df.job_type, n)
    end
    out.ref_types = {}
    for _, n in ipairs({'BUILDING_TRIGGER', 'BUILDING_TRIGGERTARGET', 'BUILDING_HOLDER'}) do
        out.ref_types[n] = has_enum(df.general_ref_type, n)
    end
    out.job_roles = {}
    for _, n in ipairs({'job_role_type', 'job_item_ref.T_role'}) do
        local ok, v = pcall(function()
            local e = n == 'job_role_type' and df.job_role_type or df.job_item_ref.T_role
            return e ~= nil and e.LinkToTarget ~= nil and e.LinkToTrigger ~= nil
        end)
        out.job_roles[n] = ok and v or false
    end
    out.building_types = {}
    for _, n in ipairs({'Bridge', 'Hatch', 'Trap', 'Door', 'Floodgate', 'GrateFloor', 'BarsFloor'}) do
        out.building_types[n] = has_enum(df.building_type, n)
    end
    out.trap_types = {}
    for _, n in ipairs({'Lever', 'CageTrap', 'StoneFallTrap', 'WeaponTrap', 'TrackStop', 'PressurePlate'}) do
        out.trap_types[n] = has_enum(df.trap_type, n)
    end
    out.buildings_api = {}
    for _, n in ipairs({'constructBuilding', 'deconstruct', 'markedForRemoval', 'findAtTile', 'getSize'}) do
        out.buildings_api[n] = type(dfhack.buildings[n]) == 'function'
    end
    out.job_api = {}
    for _, n in ipairs({'linkIntoWorld', 'attachJobItem', 'addGeneralRef'}) do
        out.job_api[n] = type(dfhack.job[n]) == 'function'
    end
    local wanted = {}
    -- what stands on the given tiles
    out.tiles = {}
    for i = 1, #args - 2, 3 do
        local x, y, z = tonumber(args[i]), tonumber(args[i + 1]), tonumber(args[i + 2])
        if x and y and z then
            local t = {x = x, y = y, z = z}
            local ok_t, err_t = pcall(function()
                local b = dfhack.buildings.findAtTile(x, y, z)
                if b then
                    local bt = b:getType()
                    t.building = df.building_type[bt]
                    t.id = b.id
                    t.size = {b.x2 - b.x1 + 1, b.y2 - b.y1 + 1}
                    if bt == df.building_type.Bridge then t.direction = b.direction end
                    if bt == df.building_type.Trap then t.trap = df.trap_type[b.trap_type] end
                    local mechs = {}
                    for _, ci in ipairs(b.contained_items or {}) do table.insert(mechs, ci.item) end
                    t.levers = probe_link_ids(mechs, 'BUILDING_TRIGGER')
                    for _, lid in ipairs(t.levers) do wanted[lid] = true end
                    t.linked = #t.levers > 0
                end
                local tt = dfhack.maps.getTileType(x, y, z)
                t.shape = tt and df.tiletype_shape[df.tiletype.attrs[tt].shape] or nil
                local des = dfhack.maps.getTileFlags(x, y, z)
                if des and des.flow_size > 0 then
                    t.liquid = (des.liquid_type == true or des.liquid_type == 1) and 'magma' or 'water'
                    t.depth = des.flow_size
                end
            end)
            if not ok_t then t.error = tostring(err_t) end
            table.insert(out.tiles, t)
        end
    end
    -- the levers, and what each is linked to. A link lives on the
    -- mechanisms: the lever keeps its linked mechanisms, each with a
    -- BUILDING_TRIGGERTARGET reference to the bridge or door it works; the
    -- target holds a mechanism with a BUILDING_TRIGGER reference back to the
    -- lever (DF 53.16: the lever's linked mechanisms sit in the targets and
    -- carry a BUILDING_HOLDER reference to them). Levers named "AI gate" and
    -- levers working a probed tile come first, then the rest (at most 40).
    out.levers = {}
    out.levers_total = 0
    local ok_l, err_l = pcall(function()
        local named, working, others = {}, {}, {}
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever then
                out.levers_total = out.levers_total + 1
                local name = txt(b.name) or ''
                local targets = {}
                local tids = probe_link_ids(b.linked_mechanisms, 'BUILDING_HOLDER')
                if #tids == 0 then tids = probe_link_ids(b.linked_mechanisms, 'BUILDING_TRIGGERTARGET') end
                for _, tid in ipairs(tids) do
                    local tb = df.building.find(tid)
                    table.insert(targets, {id = tid, type = tb and df.building_type[tb:getType()] or '?'})
                end
                local e = {id = b.id, name = name, x = b.centerx, y = b.centery, z = b.z,
                           targets = targets, mechanisms = #b.linked_mechanisms,
                           pending = #b.jobs > 0}
                table.insert(name:lower() == 'ai gate' and named or wanted[b.id] and working or others, e)
            end
        end
        for _, e in ipairs(named) do table.insert(out.levers, e) end
        for _, e in ipairs(working) do table.insert(out.levers, e) end
        for _, e in ipairs(others) do
            if #out.levers >= 40 then break end
            table.insert(out.levers, e)
        end
    end)
    if not ok_l then out.levers_error = tostring(err_l) end
    return {ok = true, probe = out}
end

-- ai-bridge reports: how the latest announcements would be sorted, without
-- taking anything off the event feed (for brain/selftest.py).
function cmd_reports()
    if not in_fort() then return NOT_IN_FORT end
    local R = reqscript('ai-reports')
    local list = df.global.world.status.announcements
    local merged = R.merge(list, #list, function(t) return df.announcement_type[t] or tostring(t) end, txt)
    local out = {}
    for i = math.max(1, #merged - 39), #merged do
        local a = merged[i]
        table.insert(out, {type = a.type, topic = R.classify(a.type, a.text) or false,
                           text = (a.text or ''):sub(1, 100)})
    end
    return {ok = true, reports = out}
end

-- ai-bridge assumptions: every game name and DFHack call the AI relies on,
-- checked in this DF and DFHack (read-only). Each round of fixes so far
-- found a guess about DF 53 that was wrong (a work detail's field name, a
-- stock's name); this lists them before a run instead of during one.
ASSUMPTIONS = {
    -- enums and job types
    'df.job_type.LinkBuildingToTrigger', 'df.job_type.MakeChain', 'df.job_type.ConstructMechanisms',
    'df.unit_labor.MINE', 'df.unit_labor.CUTWOOD', 'df.unit_labor.HERBALIST', 'df.unit_labor.FISH',
    'df.unit_labor.PLANT', 'df.job_skill.MINING', 'df.job_skill.AXE', 'df.job_skill.HERBALISM',
    'df.work_detail_icon_type.MINERS', 'df.work_detail_icon_type.PLANT_GATHERERS',
    'df.work_detail_icon_type.FISHERMEN', 'df.work_detail_icon_type.PLANTERS',
    'df.work_detail_mode.OnlySelectedDoesThis', 'df.work_detail_mode.EverybodyDoesThis',
    'df.tiletype_shape.SHRUB', 'df.tiletype_shape.STAIR_UPDOWN', 'df.tiletype_material.TREE',
    'df.tiletype_material.GRASS_LIGHT', 'df.tile_dig_designation.Default', 'df.tile_dig_designation.Channel',
    'df.civzone_type.Pen', 'df.civzone_type.Tomb', 'df.building_type.Wagon', 'df.building_type.Hatch',
    'df.building_type.Well', 'df.building_type.FarmPlot', 'df.building_type.Bridge',
    'df.workshop_type.Fishery', 'df.workshop_type.Mechanics', 'df.workshop_type.Clothiers',
    'df.general_ref_type.BUILDING_HOLDER', 'df.general_ref_type.BUILDING_TRIGGER',
    'df.general_ref_type.BUILDING_CIVZONE_ASSIGNED',
    -- game state the AI reads or writes
    'df.global.plotinfo.labor_info.work_details', 'df.global.plotinfo.main.autosave_request',
    'df.global.world.status.popups', 'df.global.d_init.announcements.flags',
    'df.global.enabler.calculated_fps', 'df.global.plotinfo.alerts.list', 'df.global.plotinfo.burrows.list',
    'df.global.world.manager_orders.all', 'df.global.world.mandates.all',
    'df.global.world.items.other.TRAPPARTS', 'df.global.world.items.other.CHAIN',
    'df.global.world.items.other.PLANT_GROWTH', 'df.global.world.items.other.FISH_RAW',
    -- fields on real objects (checked on the first one the fort has)
    'DETAIL.flags.mode', 'DETAIL.icon', 'DETAIL.assigned_units', 'DETAIL.allowed_labors',
    'UNIT.status.labors', 'UNIT.military.squad_id', 'UNIT.job', 'UNIT.status.current_soul',
    'TILE.subterranean', 'TILE.outside', 'TILE.dig', 'TILE.flow_size', 'TILE.hidden',
    -- DFHack calls
    'dfhack.units.setAutomaticProfessions', 'dfhack.units.getNoblePositions', 'dfhack.units.getCitizens',
    'dfhack.military.makeSquad', 'dfhack.military.addToSquad', 'dfhack.items.getHolderUnit',
    'dfhack.buildings.findCivzonesAt', 'dfhack.maps.getTileFlags', 'dfhack.persistent.getSiteData',
    'UTILS.insert_sorted', 'QUICKFORT.apply_blueprint',
    -- appointing (lua/ai-nobles.lua)
    'df.histfig_entity_link_positionst', 'df.history_event_add_hf_entity_linkst',
    'df.histfig_entity_link_type.POSITION', 'df.global.hist_event_next_id', 'df.global.world.history.events',
    'df.global.plotinfo.group_id', 'ENTITY.positions.own', 'ENTITY.positions.assignments',
    'FIGURE.entity_links',
    -- squads (lua/ai-military.lua make_squad)
    'df.uniform_category._last_item', 'df.squad_uniform_spec', 'df.histfig_entity_link_squadst',
    'df.trap_type.Lever', 'UNIT.owned_buildings', 'dfhack.buildings.setOwner', 'dfhack.items.setOwner', 'dfhack.items.getOwner', 'dfhack.buildings.deconstruct', 'df.building_floodgatest', 'dfhack.maps.getBlock', 'df.viewscreen_titlest', 'df.need_type', 'df.building_def', 'dfhack.maps.getTileBiomeRgn', 'dfhack.maps.getRegionBiome', 'df.world_geo_biome', 'df.global.plotinfo.economic_stone', 'df.global.world.raws.itemdefs.weapons', 'df.uniform_category.weapon', 'dfhack.job.removeJob', 'df.general_ref_unit_workerst', 'ENTITY.uniforms', 'df.civzone_type.Office', '(dfhack.translation and dfhack.translation.translateName) or dfhack.TranslateName', 'df.global.squad_next_id', 'df.civzone_type.SandCollection', 'df.job_type.CollectSand', 'df.job_type.MakeWindow', 'df.furnace_type.GlassFurnace',
    -- captains' posts added by the AI (lua/ai-military.lua add_post, 0.81)
    'df.entity_position_assignment', 'ENTITY.positions.next_assignment_id', 'ENTITY.squads',
    'ENTITY.assignments_by_type',          -- (0.104.138) on the entity itself, not its positions
    -- staffing locations (lua/ai-society.lua staff_location, 0.84)
    'df.occupation_type.DOCTOR', 'df.occupation_type.SCRIBE', 'df.occupation_type.TAVERN_KEEPER', 'UNIT.occupations',
    'df.occupation', 'df.global.occupation_next_id', 'df.global.world.occupations.all',
    -- petitions (0.87)
    'df.global.plotinfo.petitions', 'df.agreement', 'df.agreement_details_type.Residency',
    -- (0.104.138) '~': optional, a warning when missing (DFHack 53.16-r3 knows these names but not their
    -- address in this DF; the petition orders are left to the player then)
    '~df.global.standing_orders_petition_citizenship', '~df.global.standing_orders_petition_resident_performer',
    'df.history_event_reason',
    -- the kiln and paper chains (0.86)
    'df.improvement_type.WRITING', 'df.global.world.items.other.SHEET', 'df.global.world.items.other.POWDER_MISC',
    'df.global.world.items.other.CORPSEPIECE', 'df.furnace_type.Kiln',
    'df.job_skill.DIAGNOSE', 'df.job_skill.SET_BONE', 'df.job_skill.WRITING', 'dfhack.units.getNominalSkill',
    -- ore (lua/ai-industry.lua)
    'df.block_square_event_mineralst', 'dfhack.maps.getTileAssignment', 'dfhack.maps.getWalkableGroup',
    'df.global.world.raws.inorganics', 'df.furnace_type.Smelter', 'df.furnace_type.WoodFurnace',
    'df.workshop_type.MetalsmithsForge',
    -- taking down a mistaken gate (lua/ai-gates.lua clear_gate)
    'dfhack.constructions.designateRemove', 'dfhack.constructions.findAtTile', 'dfhack.buildings.deconstruct',
    'dfhack.buildings.findAtTile', 'TILE.subterranean',
    -- trade (lua/ai-trade.lua)
    'df.global.plotinfo.caravans', 'df.caravan_state.T_trade_state.AtDepot', 'dfhack.items.markForTrade',
    'df.global.world.buildings.other.TRADE_DEPOT', 'df.building_item_role_type.TEMP', 'dfhack.maps.canWalkBetween',
    -- the logs folder of a copied save
    'df.global.world.world_data.name',
    -- (0.88) the alert icons, the bags, furniture into a zone
    'df.global.world.status.announcement_alert', 'df.announcement_alert_type.DEATH', 'df.report.find',
    -- (0.104.78) pointers: empty (nil) unless an alert is being looked at, so '?' = a nil value is fine,
    -- only an unknown field fails (they were reported missing every day)
    '?df.global.game.main_interface.announcement_alert.viewing_alert', '?df.global.game.main_interface.current_hover_alert',
    '?df.global.game.main_interface.hover_announcement_alert', 'df.global.world.items.other.SEEDS',
    'df.global.world.items.other.TRACTION_BENCH', 'dfhack.items.getContainer', 'dfhack.buildings.containsTile',
    'df.building_type.TractionBench', 'df.global.world.items.other.BAG',
    -- (0.89) location petitions, dedications
    'df.agreement.get_vector', 'df.agreement_details_type.Location', 'df.religious_practice_type.WORSHIP_HFID',
    'df.abstract_building_templest', 'df.abstract_building_guildhallst', 'df.global.plotinfo.site_id',
    'df.global.plotinfo.trees_removed', 'df.global.plotinfo.main.custom_difficulty.tree_fell_count',
    'df.global.world.items.other.STATUE', 'df.global.plotinfo.civ_id',
    'df.global.plotinfo.activities', 'df.global.plotinfo.dip_meeting_info', 'df.global.plotinfo.dipscript_popups', 'df.meeting_topic', 'df.diplomacy_state_type.Peace', 'df.historical_entity_type.Civilization',
    -- (0.104.168) why a complaint went unheard, the cats kept from the butcher
    'df.history_event_reason.vent_at_boss', 'df.caste_raw_flags.HUNTS_VERMIN', 'dfhack.units.setNickname',
    'dfhack.units.isAvailableForAdoption', 'dfhack.units.isFortControlled',
}

function cmd_assumptions()
    if not in_fort() then return NOT_IN_FORT end
    local env = {df = df, dfhack = dfhack}
    pcall(function() env.UTILS = require('utils') end)
    env.REACTION = function(code) return reaction_exists(code) or nil end
    env.COKE = function(stone) return coke_reaction(stone) end
    pcall(function() env.QUICKFORT = reqscript('quickfort') end)
    pcall(function() env.DETAIL = df.global.plotinfo.labor_info.work_details[0] end)
    pcall(function() env.UNIT = dfhack.units.getCitizens()[1] or dfhack.units.getCitizens()[0] end)
    pcall(function() env.ENTITY = df.historical_entity.find(df.global.plotinfo.group_id) end)
    pcall(function() env.FIGURE = df.historical_figure.find(env.UNIT.hist_figure_id) end)
    pcall(function()
        local u = env.UNIT
        env.TILE = dfhack.maps.getTileFlags(u.pos.x, u.pos.y, u.pos.z)
    end)
    -- every work order recipe's job type and every stock's item list
    local list = {}
    for _, a in ipairs(ASSUMPTIONS) do table.insert(list, a) end
    for name, r in pairs(ORDER_RECIPES) do
        if type(r) == 'table' and r.job then table.insert(list, 'df.job_type.' .. r.job .. ' (recipe ' .. name .. ')') end
        if type(r) == 'table' and r.reaction then
            table.insert(list, 'REACTION("' .. r.reaction .. '") (recipe ' .. name .. ')')
        end
        if type(r) == 'table' and r.reaction_find then
            table.insert(list, 'COKE("' .. r.reaction_find .. '") (recipe ' .. name .. ')')
        end
    end
    for _, cat in ipairs(STOCK_CATEGORIES) do table.insert(list, 'df.items_other_id.' .. cat[2]) end
    local failed, passed, optional = {}, 0, {}
    for _, a in ipairs(list) do
        local expr = a:gsub(' %(.*%)$', '')
        local opt = expr:sub(1, 1) == '~'
        if opt then expr = expr:sub(2) end
        local nil_ok = expr:sub(1, 1) == '?'
        if nil_ok then expr = expr:sub(2) end
        local holder = expr:match('^(%u+)%.')
        local ok, v = pcall(function()
            if holder and env[holder] == nil then error(holder:lower() .. ' not found in this fort') end
            local fn = load('return ' .. expr, a, 't', env)
            return fn()
        end)
        if ok and (v ~= nil or nil_ok) then passed = passed + 1
        else
            local why = a:gsub('^~', '') .. (ok and ': missing' or (': ' .. tostring(v):gsub('^.-:%d+: ', '')))
            table.insert(opt and optional or failed, why)
        end
    end
    table.sort(failed)
    -- (ok: the check ran; a failed list comes back as data, not an error)
    return {ok = true, all_found = #failed == 0, passed = passed, failed = failed,
            optional_missing = #optional > 0 and optional or nil}
end
