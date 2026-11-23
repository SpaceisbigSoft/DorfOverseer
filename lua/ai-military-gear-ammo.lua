-- ai-military-gear-ammo: quivers, flasks and waterskins, the squads' ammunition and the bolts handed
-- out (quiver_report, flask_report, assign_quivers, squad_ammo, free_bolts,
-- bolts_free_count, assign_bolts, squad_bolts).
--
-- (r8) A part of ai-military-gear, not a script of its own: ai-military-gear.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-military-gear').name (and ai-military's, through its forwarders)
-- and a name swapped there reaches this file.

if not GEAR_PART_LOCALS then qerror('ai-military-gear-ammo is a part of ai-military-gear; run ai-military-gear') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-gear-ammo'] = '0.105.75'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, M, fort_squads, memo, eq_ids, gear_items, vec_remove, vec_add, is_ranged_spec = GEAR_PART_LOCALS.U, GEAR_PART_LOCALS.M, GEAR_PART_LOCALS.fort_squads, GEAR_PART_LOCALS.memo, GEAR_PART_LOCALS.eq_ids, GEAR_PART_LOCALS.gear_items, GEAR_PART_LOCALS.vec_remove, GEAR_PART_LOCALS.vec_add, GEAR_PART_LOCALS.is_ranged_spec   -- (r8) handed on by the files before

-- Quivers: each place with a ranged weapon entry and its quiver (the place's
-- own `quiver` field, df-structures squad_position_equipmentst), and the
-- free ones. {ranged_places, quivers_assigned, quivers_carried, quivers_free}
local function ranged_place(pos)
    local r = false
    pcall(function()
        for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
            if is_ranged_spec(spec, true) then r = true end
        end
    end)
    return r
end

local function quiver_claims()
    return memo('quivers', function()
    local c = {}
    for _, sq in ipairs(fort_squads()) do
        for _, pos in ipairs(sq.positions) do
            pcall(function() if pos.equipment.quiver ~= -1 then c[pos.equipment.quiver] = true end end)
        end
    end
    return c
    end)
end

local function free_quivers(claimed)
    local out = {}
    -- (0.105.0 review) only quivers on DF's unassigned list (as for weapons),
    -- never one built in or an artifact
    local eq = equipment_lists()
    local una = eq and eq_ids(eq, 'items_unassigned', 'QUIVER') or {}
    pcall(function()
        for _, it in ipairs(gear_items('QUIVER')) do
            local f = it.flags
            if una[it.id] and not (claimed[it.id] or f.forbid or f.owned or f.trader or f.removed or f.garbage_collect
                    or f.dump or f.hostile or f.in_job or f.construction or f.in_inventory
                    or f.in_building or f.artifact) then
                table.insert(out, it)
            end
        end
    end)
    return out
end

function quiver_report()
    local out = {ranged_places = 0, quivers_assigned = 0, quivers_carried = 0, quivers_free = 0}
    local fort = U.fort_entity()
    if not fort then return out end
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for _, pos in ipairs(sq and sq.positions or {}) do
            if pos.occupant ~= -1 and ranged_place(pos) then
                out.ranged_places = out.ranged_places + 1
                local okq, qid = pcall(function() return pos.equipment.quiver end)
                if okq and qid ~= nil and qid ~= -1 then
                    out.quivers_assigned = out.quivers_assigned + 1
                    pcall(function()
                        local it = df.item.find(qid)
                        local u = it and dfhack.items.getHolderUnit(it)
                        local hf = df.historical_figure.find(pos.occupant)
                        if u and hf and u.id == hf.unit_id then out.quivers_carried = out.quivers_carried + 1 end
                    end)
                end
            end
        end
    end
    out.quivers_free = #free_quivers(quiver_claims())
    return out
end

-- (0.105.26) Flasks and waterskins: a squad set to carry water (carry_water,
-- ai-military) fills nothing without one. Each soldier's place and its
-- `flask` (df-structures squad_position_equipmentst), and the free ones
-- (DF hands those out itself). {flask_places, flasks_assigned, flasks_free}
function flask_report()
    local out = {flask_places = 0, flasks_assigned = 0, flasks_free = 0}
    local fort = U.fort_entity()
    if not fort then return out end
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for _, pos in ipairs(sq and sq.positions or {}) do
            if pos.occupant ~= -1 then
                out.flask_places = out.flask_places + 1
                local okf, fid = pcall(function() return pos.equipment.flask end)
                if okf and fid ~= nil and fid ~= -1 then out.flasks_assigned = out.flasks_assigned + 1 end
            end
        end
    end
    local eq = equipment_lists()
    local una = eq and eq_ids(eq, 'items_unassigned', 'FLASK') or {}
    pcall(function()
        for _, it in ipairs(gear_items('FLASK')) do
            local f = it.flags
            if una[it.id] and not (f.forbid or f.owned or f.trader or f.removed or f.garbage_collect or f.dump
                    or f.hostile or f.in_job or f.construction or f.in_inventory or f.in_building or f.artifact) then
                out.flasks_free = out.flasks_free + 1
            end
        end
    end)
    return out
end

-- Give each crossbow soldier without one a free quiver: the place's quiver
-- field, and DF told to look at quivers again (its own update flags).
function assign_quivers(dry_run, limit)
    local fort = U.fort_entity()
    if not fort then return {ok = false, rejected = true, error = 'no fort'} end
    limit = limit or 10
    local pool = free_quivers(quiver_claims())
    local eq = equipment_lists()
    local n, squads, err = 0, {}, nil
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for _, pos in ipairs(sq and sq.positions or {}) do
            if n >= limit or #pool == 0 or err then break end
            local okq, qid = pcall(function() return pos.equipment.quiver end)
            if pos.occupant ~= -1 and okq and qid == -1 and ranged_place(pos) then
                local it = table.remove(pool, 1)
                if not dry_run then
                    -- (0.105.0 review) the field's name is read from df-structures, not
                    -- seen in 53.16: a wrong one is reported, not raised; the quiver
                    -- moves to the assigned list as assign_weapons moves a weapon
                    local okw, werr = pcall(function()
                        pos.equipment.quiver = it.id
                        if eq then
                            vec_remove(eq.items_unassigned.QUIVER, it.id)
                            vec_add(eq.items_assigned.QUIVER, it.id)
                        end
                    end)
                    if okw then squads[sid] = true
                    else err = tostring(werr):sub(1, 160) end
                end
                if not err then n = n + 1 end
            end
        end
    end
    if err and n == 0 then
        return {ok = false, error = "this DF's squad places take no quiver this way: " .. err}
    end
    if n == 0 then
        return {ok = false, rejected = true, error = #pool == 0 and 'no free quiver' or 'every crossbow soldier has a quiver'}
    end
    if dry_run then return {ok = true, dry_run = true, would_assign = n} end
    for sid in pairs(squads) do
        pcall(function() df.squad.find(sid).ammo.update.quiver = true end)      -- (0.105.0 review: in a pcall)
    end
    pcall(function() df.global.plotinfo.equipment.update.quiver = true end)
    return {ok = true, assigned = n, left = #pool, error = err}
end

-- (r2h4) the bolts a list of item ids holds (stack sizes summed; an id
-- that is gone counts nothing)
local function stack_units(ids)
    local n = 0
    for _, id in ipairs(ids) do
        pcall(function()
            local it = df.item.find(id)
            if it then n = n + (it:getStackSize() or 1) end
        end)
    end
    return n
end

-- A crossbow squad's bolts: its ammunition entries, the bolts wanted and
-- those DF has assigned. nil for a squad that doesn't shoot.
-- (r2h4) `units`: the bolts on the entries' assigned lists (`assigned` counts
-- stacks: 25 bolts are one item), so wanted and units compare
function squad_ammo(sq)
    local shoots = false
    for _, pos in ipairs(sq.positions) do
        if ranged_place(pos) then shoots = true break end
    end
    if not shoots then return nil end
    local out = {specs = 0, wanted = 0, assigned = 0, items = 0, units = 0}
    pcall(function()
        for _, a in ipairs(sq.ammo.ammunition) do
            out.specs = out.specs + 1
            out.wanted = out.wanted + (a.amount or 0)
            out.assigned = out.assigned + #a.assigned
            out.units = out.units + stack_units(a.assigned)
        end
        out.items = #sq.ammo.ammo_items
    end)
    return out
end

-- (r2h4) Bolts DF never hands out. The 15-16 Nov run (0.105.55): every
-- crossbow squad had its bolts entry (set_bolts, 500 wanted) and none
-- assigned (A with 500 bolts in stock, C 508, D 304, E 449: `ammo.assigned`
-- 0), so no soldier ever had a bolt in his quiver (`power.ranged` 0 in all
-- 14 squads). DF fills an entry only when its equipment update runs (the
-- update flags), and the entry was set before the bolts were made: B's
-- squad, set while 11 stacks lay free, got those 11 and no more. Weapons
-- had the same lazy hand-out (assign_weapons, 0.104.60). Here the free bolts
-- go onto the entries as DF's own assignment puts them: the entry's
-- `assigned` list, from DF's unassigned list to its assigned one; then the
-- update flags, so DF has the soldiers fetch them into their quivers.
BOLTS_ID = 'ITEM_AMMO_BOLTS'

local function is_bolts(it)
    local ok, id = pcall(function() return it.subtype.id end)
    return ok and id == BOLTS_ID
end

-- every bolt stack an ammunition entry claims (any squad's, the hunters')
local function ammo_claims()
    local c = {}
    for _, sq in ipairs(fort_squads()) do
        pcall(function()
            for _, a in ipairs(sq.ammo.ammunition) do
                for _, id in ipairs(a.assigned) do c[id] = true end
            end
        end)
    end
    pcall(function()
        for _, a in ipairs(df.global.plotinfo.equipment.hunter_ammunition) do
            for _, id in ipairs(a.assigned) do c[id] = true end
        end
    end)
    return c
end

-- The free bolt stacks no entry claims: {it, units, listed} (listed: on
-- DF's unassigned list; else on no list at all, as a new stack DF has not
-- filed). Never one forbidden, for the dump or to melt, in a job, carried,
-- a trader's or an enemy's, or one waiting on the "unmanifested" list.
local BOLT_OK = {}
function free_bolts()
    local out = {}
    local eq = equipment_lists()
    local una, asg, unm = {}, {}, {}
    if eq then
        pcall(function() una = id_set(eq.items_unassigned.AMMO) end)
        pcall(function() asg = id_set(eq.items_assigned.AMMO) end)
        pcall(function() unm = id_set(eq.items_unmanifested.AMMO) end)
    end
    local claimed = ammo_claims()
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.AMMO) do
            local f = it.flags
            if is_bolts(it) and not claimed[it.id] and not unm[it.id] and not f.melt
                    and U.item_free(it, BOLT_OK) and (una[it.id] or not asg[it.id]) then
                table.insert(out, {it = it, units = it:getStackSize() or 1, listed = una[it.id] and true or false})
            end
        end
    end)
    return out
end

-- the bolts the fort's free stacks hold, for the gear report
function bolts_free_count()
    local n = 0
    for _, b in ipairs(free_bolts()) do n = n + b.units end
    return n
end

-- Hand free bolts to the crossbow squads' entries short of their amount (at
-- most `limit` stacks a call). {ok, stacks, bolts, squads} or a refusal.
function assign_bolts(dry_run, limit)
    local fort = U.fort_entity()
    if not fort then return {ok = false, rejected = true, error = 'no fort'} end
    limit = limit or 20
    local pool = free_bolts()
    local eq = equipment_lists()
    local stacks, units, squads, short = 0, 0, {}, 0
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        local okv, specs = pcall(function() return sq.ammo.ammunition end)
        for _, a in ipairs((sq and okv and specs) or {}) do
            local okt, fits = pcall(function()
                return a.item_type == df.item_type.AMMO
            end)
            local have = stack_units(a.assigned)
            local want = tonumber(a.amount) or 0
            if okt and fits and have < want then
                short = short + 1
                while have < want and stacks < limit and #pool > 0 do
                    local b = table.remove(pool, 1)
                    if not dry_run then
                        a.assigned:insert('#', b.it.id)
                        if eq then
                            pcall(function()
                                vec_remove(eq.items_unassigned.AMMO, b.it.id)
                                vec_add(eq.items_assigned.AMMO, b.it.id)
                            end)
                        end
                    end
                    have, stacks, units = have + b.units, stacks + 1, units + b.units
                    squads[sid] = (squads[sid] or 0) + b.units
                end
            end
        end
    end
    if stacks == 0 then
        return {ok = false, rejected = true,
                error = short == 0 and 'every crossbow squad has its bolts' or 'no free bolts in a stockpile'}
    end
    local by = {}
    for sid, n in pairs(squads) do by[tostring(sid)] = n end
    if dry_run then return {ok = true, dry_run = true, would_assign = units, stacks = stacks, squads = by} end
    for sid in pairs(squads) do
        pcall(function()
            local sq = df.squad.find(sid)
            sq.ammo.update.ammo = true
            sq.ammo.update.quiver = true
        end)
    end
    pcall(function()
        df.global.plotinfo.equipment.update.ammo = true
        df.global.plotinfo.equipment.update.quiver = true
    end)
    return {ok = true, stacks = stacks, bolts = units, squads = by, left = #pool}
end

-- Bolts for a crossbow squad with no ammunition entry (a uniform the player
-- or an older AI set): one entry, BOLTS_PER_SOLDIER each.
function squad_bolts(squad_id, dry_run)
    local sq = M.fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local a = squad_ammo(sq)
    if not a then return {ok = false, rejected = true, error = 'the squad has no crossbows'} end
    if a.specs > 0 then return {ok = false, rejected = true, error = 'the squad already has bolts set'} end
    local n = M.BOLTS_PER_SOLDIER * math.max(1, #sq.positions)
    if dry_run then return {ok = true, dry_run = true, bolts = n} end
    local ok, err = M.set_bolts(sq, n)
    if not ok then return {ok = false, error = tostring(err)} end
    return {ok = true, bolts = n}
end
