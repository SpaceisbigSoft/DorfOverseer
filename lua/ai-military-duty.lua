-- ai-military-duty: what the squads are told to do: the routine, kill orders
-- (and whom one may name), the defend order, barracks and ranges, the defence
-- test's invaders and gate pull, the self-test's probe of each soldier's
-- gear, and the squads sent to the shelter or stationed at a choke point.
--
-- (r8) A part of ai-military, not a script of its own: ai-military.lua loads
-- it into its own environment, so every name here is
-- reqscript('ai-military').name and a name swapped there reaches this file.

if not MILITARY_PART_LOCALS then qerror('ai-military-duty is a part of ai-military; run ai-military') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-duty'] = '0.105.100'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, report_units, gear, save_shelter_marks, order_tick, is_guard_order, is_ai_order = MILITARY_PART_LOCALS.U, MILITARY_PART_LOCALS.report_citizens, MILITARY_PART_LOCALS.report_units, MILITARY_PART_LOCALS.gear, MILITARY_PART_LOCALS.save_shelter_marks, MILITARY_PART_LOCALS.order_tick, MILITARY_PART_LOCALS.is_guard_order, MILITARY_PART_LOCALS.is_ai_order   -- (r8) the hub's locals

-- Switch a squad to the named schedule ("Staggered training", "Off duty"...).
function set_routine(squad_id, name)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    for i, r in ipairs(df.global.plotinfo.alerts.routines) do
        if r.name == name then
            sq.cur_routine_idx = i
            return {ok = true, routine = name}
        end
    end
    return {ok = false, rejected = true, error = 'no schedule named ' .. tostring(name)}
end

-- (0.100, security pass) whom a kill order may name: what the report calls a
-- threat (DFHack's isDanger, or an invader) or a dwarf gone berserk, never a
-- merchant, a diplomat, a tame animal or a sane citizen. The rules only send
-- these; this keeps a bad id from turning a squad on the fort.
function kill_target_ok(u)
    local U = dfhack.units
    local function is(f) local ok, v = pcall(f, u); return ok and v end
    if u.mood == df.mood_type.Berserk then return true end
    -- (0.104.140) a citizen changed into a beast (a werebeast) for now
    local okc, changed = pcall(function()
        return u.enemy.normal_race ~= -1 and u.enemy.normal_race ~= u.race
            and (u.enemy.were_race == nil or u.enemy.were_race == -1 or u.race == u.enemy.were_race)
    end)
    if okc and changed then return true end
    if is(U.isMerchant) or is(U.isDiplomat) or is(U.isTame) then return false end
    if is(U.isCitizen) then return false end
    if is(U.isDanger) or is(U.isInvader) then return true end
    -- (r1 g7) a visitor who killed one of the fort's own, or a hero spotted
    -- sneaking after an artifact (ai-threats TURNED): B's Len Karaura killed 19
    -- in 65 s while DF called him neither a danger nor an invader
    local okt, turned = pcall(function() return reqscript('ai-threats').is_turned(u) end)
    if okt and turned == true then return true end
    -- (item1, 14 Nov) a unit DF's own job cancellations show keeping the
    -- dwarves from drink, food or sleep ("cancels Drink: Interrupted by a
    -- human spearman"): B lost 66 to thirst beside 845 drinks while a beaten
    -- visitor neither isDanger nor an invader stood by the stores
    local oki, blocking = pcall(function() return reqscript('ai-threats').interrupting(u) end)
    if oki and blocking == true then return true end
    -- (item5) a wild animal that attacks (a large predator, or one DF has
    -- agitated: ai-builder hostile_wild): the wildlife and caravan guard rules
    -- send a squad at one near the dwarves or a caravan (lua/ai-siege.lua)
    local okw, wild = pcall(function() return reqscript('ai-builder').hostile_wild(u) end)
    if okw and wild == true then return true end
    -- (0.105.51) a wild animal at grips with a citizen (its last opponent):
    -- C's giant coyote, E's giant chipmunk are neither large predators nor
    -- agitated, and every wild_hunt order at them was refused ("none of those
    -- units is a threat") while they killed the dwarves outside
    local oka, att = pcall(function()
        if not U.isAnimal(u) or is(U.isFortControlled) then return false end
        local tid = u.opponent.unit_id
        if type(tid) ~= 'number' or tid < 0 then return false end
        local c = df.unit.find(tid)
        return c ~= nil and U.isCitizen(c) == true
    end)
    return oka and att == true
end

-- Kill orders against the given units (only ones actually on the map), or
-- clear the orders the AI gave before. The player's own orders are kept.
function orders(squad_id, kill, clear)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    -- (0.105.24) off the soldiers' own order lists too (drop_orders)
    local function drop()
        local removed, member = drop_orders(sq, function(o) return is_ai_order(o, squad_id) end)
        if removed > 0 then pcall(prune_shelter_marks) end      -- (0.105.0 review)
        if removed > 0 then pcall(prune_station_mark, sq, squad_id) end   -- (0.105.48 K1b)
        return removed, member
    end
    if clear then
        local removed, member = drop()
        local out = {ok = true, cleared = removed, member_orders = member > 0 and member or nil}
        -- (0.105.24) what the soldiers are left doing, for the next live look
        local okm, m = pcall(members_state, sq)
        if okm and m then out.members = m end
        return out
    end
    -- (0.105.33 review) the targets are checked BEFORE the AI's orders come
    -- off: a refused kill list leaves the shelter / gate order standing.
    local o = df.squad_order_kill_listst:new()
    local n, refused = 0, 0
    for _, id in ipairs(kill or {}) do
        local u = df.unit.find(id)
        if u and not dfhack.units.isDead(u) then
            if kill_target_ok(u) then
                o.units:insert('#', id)
                n = n + 1
            else
                refused = refused + 1
            end
        end
    end
    if n == 0 then
        o:delete()
        return {ok = false, rejected = true, refused = refused,
                error = refused > 0 and 'none of those units is a threat (a dangerous creature, an invader or a berserk dwarf)'
                    or 'none of those units is on the map and alive'}
    end
    local removed = drop()
    o.title = AI_ORDER_TITLE
    -- stamped with today's date where the order has one (DF ages orders)
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    return {ok = true, targets = n, replaced = removed}
end

-- (0.104.83) Hold the gate: the AI's orders on the squad replaced by one
-- order to defend the gate guard burrow (the soldiers wait there and fight
-- what comes in). The player's own orders are kept.
function defend(squad_id, burrow_id)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    for _, o in ipairs(sq.orders) do
        if not is_ai_order(o, squad_id) then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
    end
    for _, o in ipairs(sq.orders) do
        -- (0.105.33 review) a shelter order is a defend order too: only the
        -- gate guard order means the squad already holds the gate
        if is_ai_order(o, squad_id) and is_guard_order(o) then
            return {ok = false, rejected = true, error = 'the squad already holds the gate'}
        end
    end
    -- (0.105.24) off the soldiers' own order lists too (drop_orders)
    local removed = drop_orders(sq, function(o) return is_ai_order(o, squad_id) end)
    local o = df.squad_order_defend_burrowsst:new()
    o.burrows:insert('#', burrow_id)
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    return {ok = true, burrow_id = burrow_id, replaced = removed}
end

-- --- barracks -------------------------------------------------------------------
--
-- Barracks zones and the squads using them (zone.squad_room_info); a squad
-- given one to train in and keep its gear at (DFHack's
-- dfhack.military.updateRoomAssignments, as the zone's squad screen does).
-- Not to sleep in: soldiers keep their bedrooms.
BARRACKS_FLAGS = 2 + 4 + 8        -- squad_use_flags: train, indiv_eq, squad_eq

function barracks_report()
    local out = {}
    local okl, list = pcall(function() return df.global.world.buildings.other.ZONE_BARRACKS end)
    for _, b in ipairs(okl and list or {}) do
        local squads = {}
        pcall(function()
            for _, info in ipairs(b.squad_room_info) do table.insert(squads, info.squad_id) end
        end)
        table.insert(out, {id = b.id, squads = squads})
    end
    if #out == 0 then
        -- (older DFHack: no ZONE_BARRACKS list) any civzone of the barracks type
        pcall(function()
            for _, b in ipairs(df.global.world.buildings.other.ACTIVITY_ZONE) do
                if b.type == df.civzone_type.Barracks then
                    local squads = {}
                    for _, info in ipairs(b.squad_room_info) do table.insert(squads, info.squad_id) end
                    table.insert(out, {id = b.id, squads = squads})
                end
            end
        end)
    end
    return out
end

-- Archery ranges and the squads training there.
function ranges_report()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.ACTIVITY_ZONE) do
            if b.type == df.civzone_type.ArcheryRange then
                local squads = {}
                for _, info in ipairs(b.squad_room_info) do table.insert(squads, info.squad_id) end
                table.insert(out, {id = b.id, squads = squads})
            end
        end
    end)
    return out
end

function assign_barracks(squad_id, zone_id, dry_run)
    local sq = df.squad.find(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad'} end
    local zone = df.building.find(zone_id)
    local okz, ztype = pcall(function() return zone.type end)
    local range = okz and ztype == df.civzone_type.ArcheryRange
    if not zone or not okz or not (ztype == df.civzone_type.Barracks or range) then
        return {ok = false, rejected = true, error = 'that is not a barracks zone'}
    end
    for _, info in ipairs(zone.squad_room_info) do
        if info.squad_id == squad_id then return {ok = false, rejected = true, error = 'the squad already uses it'} end
    end
    if not (dfhack.military and dfhack.military.updateRoomAssignments) then
        return {ok = false, rejected = true, error = 'this DFHack has no updateRoomAssignments'}
    end
    if dry_run then return {ok = true, dry_run = true} end
    -- an archery range: to train there only
    local flags = range and 2 or BARRACKS_FLAGS
    local ok, err = pcall(dfhack.military.updateRoomAssignments, squad_id, zone_id, flags)
    if not ok then
        ok, err = pcall(dfhack.military.updateRoomAssignments, squad_id, zone_id,
                        range and {train = true} or {train = true, indiv_eq = true, squad_eq = true})
    end
    if not ok then return {ok = false, error = 'the game refused: ' .. tostring(err):sub(1, 160)} end
    for _, info in ipairs(zone.squad_room_info) do
        if info.squad_id == squad_id then return {ok = true, squad_id = squad_id, zone_id = zone_id} end
    end
    return {ok = false, error = 'the squad was not added to the barracks'}
end

-- --- the defence test (brain/defence_test.py, a test save only) ------------------------
--
-- A few hostile invaders set down outside, where they can walk to the fort:
-- on the trade depot's level, 15-30 tiles from it, on open ground outside
-- that has a path to the depot. Made by DFHack's modtools/create-unit, in an
-- enemy civilisation (a goblin one, else none) and flagged as invaders, so
-- the game and the AI treat them as an attack. Never during a real threat.

local function test_spot()
    local dep
    for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do dep = b break end
    local cx, cy, cz
    if dep then cx, cy, cz = dep.centerx, dep.centery, dep.z
    else
        for _, u in ipairs(report_citizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            local okf, f = pcall(dfhack.maps.getTileFlags, x, y, z)
            if okf and f and f.outside then cx, cy, cz = x, y, z break end
        end
    end
    if not cx then return nil, 'no trade depot and no citizen outside to aim at' end
    local target = xyz2pos(cx, cy, cz)
    for r = 15, 30 do
        for _, d in ipairs({{r, 0}, {-r, 0}, {0, r}, {0, -r}, {r, r}, {-r, r}, {r, -r}, {-r, -r}}) do
            local x, y = cx + d[1], cy + d[2]
            local okf, f = pcall(dfhack.maps.getTileFlags, x, y, cz)
            if okf and f and f.outside and not f.hidden and f.flow_size == 0
                    and dfhack.maps.canWalkBetween(xyz2pos(x, y, cz), target) then
                return {x = x, y = y, z = cz}
            end
        end
    end
    return nil, 'no open ground 15-30 tiles from the depot with a path to it'
end

local function enemy_civ()
    for _, e in ipairs(df.global.world.entities.all) do
        local ok, code = pcall(function() return e.entity_raw.code end)
        if ok and code == 'EVIL' and e.type == df.historical_entity_type.Civilization then return e.id end
    end
    return nil
end

function spawn_test_threat(count, race, dry_run)
    count = math.max(1, math.min(10, count or 3))
    race = race or 'GOBLIN'
    for _, u in ipairs(report_units()) do
        if dfhack.units.isActive(u) and not dfhack.units.isDead(u) and dfhack.units.isDanger(u)
                and not dfhack.units.isHidden(u) then
            return {ok = false, rejected = true, error = 'there is already a threat on the map: no test now'}
        end
    end
    local spot, why = test_spot()
    if not spot then return {ok = false, rejected = true, error = why} end
    local civ = enemy_civ()
    if dry_run then return {ok = true, dry_run = true, spot = spot, race = race, count = count, civ = civ} end
    local okm, cu = pcall(reqscript, 'modtools/create-unit')
    if not okm then return {ok = false, error = 'DFHack has no modtools/create-unit: ' .. tostring(cu):sub(1, 120)} end
    local before = {}
    for _, u in ipairs(report_units()) do before[u.id] = true end
    local ok, err = pcall(cu.createUnit, race, nil, spot, {offset_x = 2, offset_y = 2, offset_z = 0}, 'Walkable',
                          nil, false, civ or -1, nil, nil, nil, nil, count, nil, nil, nil, nil,
                          {'marauder', 'active_invader', 'invader_origin'}, nil)
    if not ok then return {ok = false, error = 'create-unit failed: ' .. tostring(err):sub(1, 200)} end
    local made = {}
    for _, u in ipairs(report_units()) do
        if not before[u.id] then table.insert(made, u.id) end
    end
    return {ok = true, spot = spot, race = race, count = #made, units = made, civ = civ}
end

-- Pull the lever named "AI gate" (a dwarf goes and pulls it).
function pull_gate(lever_id)
    for _, g in ipairs(gate_levers()) do
        if g.id == lever_id then
            if g.pending then return {ok = false, rejected = true, error = 'a pull is already on its way'} end
            local out, rv = dfhack.run_command_silent('lever', 'pull', '--id', tostring(lever_id))
            if rv ~= CR_OK then
                return {ok = false, error = 'lever pull failed: ' .. tostring(out):gsub('%s+$', '')}
            end
            return {ok = true, lever_id = lever_id}
        end
    end
    return {ok = false, rejected = true, error = 'no lever named "AI gate" with that id'}
end

-- For the self-test: what each soldier's uniform asks for, what the game
-- has assigned them, and what they carry (soldiers stayed unarmed with
-- axes and helms lying spare, y52: this shows where it breaks).
function probe_squads(txt)
    local out = {}
    local fort = U.fort_entity()
    if not fort then return out end
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq then
            for p, pos in ipairs(sq.positions) do
                local e = {squad = sid, place = p, uniform = {}, assigned = 0, carries = {}}
                pcall(function()
                    for cat = 0, df.uniform_category._last_item do
                        for _, spec in ipairs(pos.equipment.uniform[cat]) do
                            local sub = '?'
                            pcall(function()
                                local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
                                sub = def and def.id or tostring(spec.item_subtype)
                            end)
                            local given = 0
                            pcall(function() given = #spec.assigned end)
                            table.insert(e.uniform, ('%s:%s mat%s/%s:%s%s given %d'):format(
                                df.item_type[spec.item_type] or '?', sub, tostring(spec.material_class),
                                tostring(spec.mattype), tostring(spec.matindex),
                                spec.indiv_choice.whole ~= 0 and ' choice' or '', given))
                        end
                    end
                end)
                pcall(function() e.assigned = #pos.equipment.assigned_items end)
                -- what the game assigned, and where it is (why it isn't picked up)
                -- (0.104.56) can the soldier walk to each, and what is the soldier doing
                local upos
                pcall(function()
                    local hf0 = df.historical_figure.find(pos.occupant)
                    local u0 = hf0 and df.unit.find(hf0.unit_id)
                    if u0 then
                        local ux, uy, uz = dfhack.units.getPosition(u0)
                        if ux then upos = xyz2pos(ux, uy, uz) end
                        if u0.job.current_job then e.job = df.job_type[u0.job.current_job.job_type] end
                        pcall(function() e.pickup = u0.military.pickup_flags.whole end)
                    end
                end)
                pcall(function()
                    e.assigned_items = {}
                    for _, iid in ipairs(pos.equipment.assigned_items) do
                        local it = df.item.find(iid)
                        if it then
                            local f, where = it.flags, {}
                            for _, k in ipairs({'forbid', 'in_inventory', 'in_building', 'container', 'trader',
                                                'dump', 'on_ground', 'in_job', 'owned', 'hostile'}) do
                                if f[k] then table.insert(where, k) end
                            end
                            local holder = dfhack.items.getHolderUnit(it)
                            local cont = dfhack.items.getContainer(it)
                            local x, y, z = dfhack.items.getPosition(it)
                            pcall(function()
                                if upos and x then
                                    table.insert(where, dfhack.maps.canWalkBetween(upos, xyz2pos(x, y, z)) and 'reach' or 'NO-REACH')
                                end
                            end)
                            table.insert(e.assigned_items, ('%s %s at %s,%s,%s [%s]%s%s'):format(
                                df.item_type[it:getType()] or '?',
                                (txt or tostring)(dfhack.items.getDescription(it, 0, true)),
                                tostring(x), tostring(y), tostring(z), table.concat(where, ' '),
                                holder and (' held by ' .. (txt or tostring)(dfhack.units.getReadableName(holder))) or '',
                                cont and (' in ' .. (txt or tostring)(dfhack.items.getDescription(cont, 0, true))) or ''))
                        else
                            table.insert(e.assigned_items, 'item ' .. tostring(iid) .. ' (gone)')
                        end
                    end
                end)
                pcall(function() e.flags = pos.equipment.flags.whole end)
                if pos.occupant ~= -1 then
                    local hf = df.historical_figure.find(pos.occupant)
                    local u = hf and df.unit.find(hf.unit_id)
                    if u then
                        e.name = (txt or tostring)(dfhack.units.getReadableName(u))
                        for _, inv in ipairs(u.inventory) do
                            table.insert(e.carries, ('%s(%s)'):format(df.item_type[inv.item:getType()] or '?',
                                gear().inv_mode_name(inv.mode) or tostring(inv.mode)))
                        end
                    end
                end
                if e.name then table.insert(out, e) end
            end
        end
    end
    -- (0.81) a few spare weapons and helms, and why they might not be taken
    pcall(function()
        local spares = {}
        for _, kind in ipairs({'WEAPON', 'HELM'}) do
            local n = 0
            for _, it in ipairs(df.global.world.items.other[kind]) do
                if n >= 4 then break end
                if not it.flags.in_inventory and not it.flags.trader then
                    local f, where = it.flags, {}
                    for _, k in ipairs({'forbid', 'in_building', 'container', 'dump', 'on_ground', 'in_job',
                                        'owned', 'garbage_collect', 'construction'}) do
                        if f[k] then table.insert(where, k) end
                    end
                    local cont = dfhack.items.getContainer(it)
                    local x, y, z = dfhack.items.getPosition(it)
                    table.insert(spares, ('%s %s sub%s mat%s:%s at %s,%s,%s [%s]%s'):format(kind,
                        (txt or tostring)(dfhack.items.getDescription(it, 0, true)), tostring(it:getSubtype()),
                        tostring(it:getMaterial()), tostring(it:getMaterialIndex()), tostring(x), tostring(y),
                        tostring(z), table.concat(where, ' '),
                        cont and (' in ' .. (txt or tostring)(dfhack.items.getDescription(cont, 0, true))) or ''))
                    n = n + 1
                end
            end
        end
        if #out > 0 then out[1].spares = spares else table.insert(out, {spares = spares}) end
    end)
    -- (0.99.11) every battle axe and helm by its flags, and what holds it:
    -- no soldier was given an axe with 14 counted spare (region2, y68)
    pcall(function()
        local census = {}
        local function add(kind, it)
            local c = census[kind] or {n = 0, by_flags = {}, by_where = {}, by_mat = {}, sample = {}}
            census[kind] = c
            c.n = c.n + 1
            local f, set = it.flags, {}
            for _, k in ipairs({'forbid', 'in_inventory', 'in_building', 'container', 'trader', 'dump', 'on_ground',
                                'in_job', 'owned', 'garbage_collect', 'construction', 'artifact', 'melt',
                                'hidden', 'encased', 'removed', 'spider_web', 'hostile'}) do
                if f[k] then table.insert(set, k) end
            end
            local key = #set > 0 and table.concat(set, ' ') or '-'
            c.by_flags[key] = (c.by_flags[key] or 0) + 1
            local where = 'loose'
            local holder = dfhack.items.getHolderUnit(it)
            local cont = dfhack.items.getContainer(it)
            local bld = dfhack.items.getHolderBuilding(it)
            if holder then
                where = 'held by ' .. (dfhack.units.isCitizen(holder) and 'a citizen' or 'a non-citizen')
            elseif bld then
                where = 'in a ' .. tostring(df.building_type[bld:getType()])
            elseif cont then
                where = 'in a ' .. tostring(df.item_type[cont:getType()])
            end
            c.by_where[where] = (c.by_where[where] or 0) + 1
            local mi = dfhack.matinfo.decode(it)
            local m = mi and mi:getToken() or '?'
            c.by_mat[m] = (c.by_mat[m] or 0) + 1
            local ok_q, q = pcall(function() return it:getQuality() end)
            if #c.sample < 3 and not holder then
                local x, y, z = dfhack.items.getPosition(it)
                table.insert(c.sample, ('#%d %s q%s at %s,%s,%s [%s] %s'):format(it.id,
                    (txt or tostring)(dfhack.items.getDescription(it, 0, true)), ok_q and tostring(q) or '?',
                    tostring(x), tostring(y), tostring(z), key, where))
            end
        end
        for _, it in ipairs(df.global.world.items.other.WEAPON) do
            local ok, id = pcall(function() return it.subtype.id end)
            if ok and id == 'ITEM_WEAPON_AXE_BATTLE' then add('battle_axe', it) end
        end
        for _, it in ipairs(df.global.world.items.other.HELM) do add('helm', it) end
        if #out > 0 then out[1].census = census else table.insert(out, {census = census}) end
    end)
    -- (0.104.60) gear DF keeps on none of its equipment lists, against the
    -- gear it lists, by maker race, metal and flags, with a few samples: why
    -- 222 armour pieces were left off in Enxah (y74)
    pcall(function()
        local eq = gear().equipment_lists()
        if not eq then return end
        local fort_race = df.global.plotinfo.race_id
        local res = {}
        for _, kind in ipairs({'ARMOR', 'HELM', 'PANTS', 'GLOVES', 'SHOES', 'SHIELD'}) do
            local asg, una = gear().id_set(eq.items_assigned[kind]), gear().id_set(eq.items_unassigned[kind])
            local okm, unm = pcall(function() return gear().id_set(eq.items_unmanifested[kind]) end)
            unm = okm and unm or {}
            local r = {listed = {}, unlisted = {}, sample = {}}
            for _, it in ipairs(df.global.world.items.other[kind]) do
                local listed = asg[it.id] or una[it.id] or unm[it.id]
                local f, tags = it.flags, {}
                local okr, mr = pcall(function() return it:getMakerRace() end)
                tags[#tags + 1] = (okr and mr == fort_race) and 'ours' or ('race' .. tostring(okr and mr or '?'))
                tags[#tags + 1] = gear().metal_token(it) and 'metal' or 'other'
                local held = false
                if f.in_inventory then
                    local okh, u = pcall(dfhack.items.getHolderUnit, it)
                    held = okh and u ~= nil
                end
                if held then tags[#tags + 1] = 'held' end
                for _, k in ipairs({'owned', 'forbid', 'trader', 'foreign', 'in_building', 'melt', 'dump',
                                    'garbage_collect', 'hostile', 'removed', 'container'}) do
                    local okf, v = pcall(function() return f[k] end)
                    if okf and v then tags[#tags + 1] = k end
                end
                local key = table.concat(tags, ' ')
                local side = listed and r.listed or r.unlisted
                side[key] = (side[key] or 0) + 1
                if not listed and not held and #r.sample < 4 then
                    local x, y, z = dfhack.items.getPosition(it)
                    local cont = dfhack.items.getContainer(it)
                    local okw, wear = pcall(function() return it.wear end)
                    table.insert(r.sample, ('#%d %s q%s wear %s at %s,%s,%s [%s]%s'):format(it.id,
                        (txt or tostring)(dfhack.items.getDescription(it, 0, true)), tostring(it:getQuality()),
                        okw and tostring(wear) or '?', tostring(x), tostring(y), tostring(z), key,
                        cont and (' in ' .. (txt or tostring)(dfhack.items.getDescription(cont, 0, true))) or ''))
                end
            end
            res[kind] = r
        end
        if #out > 0 then out[1].lists = res else table.insert(out, {lists = res}) end
    end)
    return out
end

-- The shelter: the squad holds the civilian alert's burrow(s), the AI's
-- orders on it replaced (a squad on the player's orders: refused).
function shelter(squad_id, dry_run)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local ids = {}
    for id in pairs(shelter_burrow_ids()) do table.insert(ids, id) end
    table.sort(ids)
    if #ids == 0 then return {ok = false, rejected = true, error = 'no civilian-alert burrow to shelter in'} end
    for _, o in ipairs(sq.orders) do
        if not is_ai_order(o, squad_id) then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
        if is_shelter_order(o, squad_id) then return {ok = false, rejected = true, error = 'the squad is in the shelter already'} end
    end
    -- (0.105.24) thirsty or hungry soldiers are not shut in (as the hospital
    -- burrow, 0.105.22): they drink and eat first
    local okm, m = pcall(members_state, sq)
    if okm and m and (m.parched or 0) > 0 then
        return {ok = false, rejected = true, parched = m.parched,
                error = ('%d of its soldiers are thirsty or hungry: they eat and drink first'):format(m.parched)}
    end
    if dry_run then return {ok = true, dry_run = true, burrows = #ids} end
    -- (0.105.24) off the soldiers' own order lists too (drop_orders)
    local removed = drop_orders(sq, function() return true end)
    -- (0.105.24) the squad's supplies: soldiers on the shelter order carry
    -- food and water (DFHack's makeSquad gives a squad carry_food 2 and
    -- carry_water 1; a squad set to carry none is set so), so a long hold
    -- doesn't keep them from drink
    local supplies
    pcall(function()
        if sq.carry_water == 0 then sq.carry_water = 1; supplies = 'water' end
    end)
    pcall(function()
        if sq.carry_food == 0 then sq.carry_food = 2; supplies = supplies and (supplies .. ', food') or 'food' end
    end)
    local o = df.squad_order_defend_burrowsst:new()
    for _, id in ipairs(ids) do o.burrows:insert('#', id) end
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    -- (0.105.0 review) marked as the AI's, with the site data
    local marks = shelter_marks()
    marks[tostring(squad_id)] = order_tick(o)
    save_shelter_marks(marks)
    return {ok = true, burrows = #ids, replaced = removed, supplies = supplies}
end

-- (0.105.45) The squads between the threat and the civilians. F (27 Galena
-- y257): a hill titan killed 42 in the shelter, where the civilians and two
-- squads waited together. While the AI hides from a great danger the squads
-- now stand at a choke point on the threat's way to the shelter (a corridor
-- or stair just inside the gate it faces; brain/planner_shelter.py chooses
-- it from the shelter_plan section), or at the barracks: a station (move)
-- order, titled and marked as the AI's like the shelter's (the recall clears
-- it, `sheltering` stays true in the report so every hiding rule holds).
STATION_KEY = 'ai-overseer/station'

function station_marks() return U.site_get(STATION_KEY, {}) end

-- the AI's station order on this squad: {x, y, z}, or nil.
-- (0.105.48 K1b, audit A6 #1) DF 53.17's squad_order_movest has only `pos`
-- and `point_id` (df.squad.xml): no title. Reading or writing o.title threw,
-- so no station order was ever made or recognised. The AI's is now known by
-- the site mark (station_marks) naming this squad and the very same tile.
function station_of(o, squad_id)
    if not df.squad_order_movest:is_instance(o) then return nil end
    local mark = station_marks()[tostring(squad_id)]
    if type(mark) ~= 'table' then return nil end
    local okp, x, y, z = pcall(function() return o.pos.x, o.pos.y, o.pos.z end)
    if not okp then return nil end
    if x ~= mark.x or y ~= mark.y or z ~= mark.z then return nil end
    return {x = x, y = y, z = z}
end

-- (0.105.48 K1b) a station mark whose order is gone (recalled, replaced, or
-- cancelled in DF) is taken off, so a later move order of the player's to
-- the same tile is never read as the AI's
function prune_station_mark(sq, squad_id)
    local marks = station_marks()
    local key = tostring(squad_id)
    if marks[key] == nil then return end
    for _, o in ipairs(sq.orders) do
        local ok, st = pcall(station_of, o, squad_id)
        if ok and st then return end
    end
    marks[key] = nil
    U.site_put(STATION_KEY, marks)
end

function station(squad_id, x, y, z, dry_run)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local okw, walk = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        local shape = df.tiletype_shape[df.tiletype.attrs[tt].shape]
        return shape ~= 'WALL' and shape ~= 'EMPTY' and shape ~= 'NONE' and dfhack.maps.getWalkableGroup({x = x, y = y, z = z}) ~= 0
    end)
    if not (okw and walk) then return {ok = false, rejected = true, error = ('x%d y%d z%d is no place to stand'):format(x, y, z)} end
    for _, o in ipairs(sq.orders) do
        if not is_ai_order(o, squad_id) then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
        local st = station_of(o, squad_id)
        if st and st.x == x and st.y == y and st.z == z then
            return {ok = false, rejected = true, error = 'the squad stands there already'}
        end
    end
    local okm, m = pcall(members_state, sq)
    if okm and m and (m.parched or 0) > 0 then
        return {ok = false, rejected = true, parched = m.parched,
                error = ('%d of its soldiers are thirsty or hungry: they eat and drink first'):format(m.parched)}
    end
    if dry_run then return {ok = true, dry_run = true, x = x, y = y, z = z} end
    -- the order made first (a field this DF lacks: refused, nothing changed).
    -- (0.105.48 K1b) only DF 53.17's own fields: pos and point_id (-1: a
    -- tile, not a patrol point); the AI's mark is the site data below
    local made
    local okn, err = pcall(function()
        made = df.squad_order_movest:new()
        made.pos.x, made.pos.y, made.pos.z = x, y, z
        made.point_id = -1
    end)
    local o = made
    if not okn or not o then
        if o then pcall(function() o:delete() end) end
        return {ok = false, error = 'could not make a station order: ' .. tostring(err):sub(1, 120)}
    end
    local removed = drop_orders(sq, function() return true end)
    pcall(function()
        if sq.carry_water == 0 then sq.carry_water = 1 end
        if sq.carry_food == 0 then sq.carry_food = 2 end
    end)
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    local marks = station_marks()
    marks[tostring(squad_id)] = {x = x, y = y, z = z}
    U.site_put(STATION_KEY, marks)
    -- off the shelter's marks (it no longer holds the shelter)
    pcall(function()
        local sm = shelter_marks()
        if sm[tostring(squad_id)] ~= nil then sm[tostring(squad_id)] = nil; save_shelter_marks(sm) end
    end)
    return {ok = true, x = x, y = y, z = z, replaced = removed}
end
