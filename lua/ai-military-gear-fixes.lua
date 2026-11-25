-- ai-military-gear-fixes: the fixes for what the why report finds: stale ids off the places, weapon
-- materials loosened, spare gear unforbidden away from danger, shield
-- entries added (unforbid_spares, fix_gear_gaps).
--
-- (r8) A part of ai-military-gear, not a script of its own: ai-military-gear.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-military-gear').name (and ai-military's, through its forwarders)
-- and a name swapped there reaches this file.

if not GEAR_PART_LOCALS then qerror('ai-military-gear-fixes is a part of ai-military-gear; run ai-military-gear') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-gear-fixes'] = '0.105.115'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, M, fort_squads, free_gear, vec_remove, vec_add, claim_map, item_stage = GEAR_PART_LOCALS.U, GEAR_PART_LOCALS.M, GEAR_PART_LOCALS.fort_squads, GEAR_PART_LOCALS.free_gear, GEAR_PART_LOCALS.vec_remove, GEAR_PART_LOCALS.vec_add, GEAR_PART_LOCALS.claim_map, GEAR_PART_LOCALS.item_stage   -- (r8) handed on by the files before

-- Fixes for what the why report finds:
--  * a soldier's place still listing an item that is back on the free list
--    (DF took it off the entry: "off the entry, still on the place" in the
--    0.104.80 ledger): the stale id is taken off the place;
--  * a weapon entry of a uniform the AI set asking for a material no free
--    weapon of its kind has: loosened to any material;
--  * a metal melee uniform the AI set with no shield entry, while shields
--    lie spare: a shield entry (any shield) on each place;
-- then the weapons are handed out (assign_weapons).
local function stale_places(dry_run)
    local eq = equipment_lists()
    if not eq then return 0 end
    local una, asg = {}, {}
    for _, k in ipairs({'WEAPON', 'SHIELD'}) do
        for id in pairs(id_set(eq.items_unassigned[k])) do una[id] = true end
        for id in pairs(id_set(eq.items_assigned[k])) do asg[id] = k end
    end
    -- (0.105.2) a place's stale id DF also keeps on its ASSIGNED list (no
    -- entry anywhere claims it, nobody holds it): DF never hands it out
    -- again. B (2 Nov): 7, then 24 places "stale on a soldier's list" and
    -- the fix refused 17 times, as it took only ids on the free list. Such
    -- an id comes off the place and goes back on the free list.
    local entry = claim_map()
    local work = id_set(eq.work_weapons)
    local moved = {}
    local function free_again(id)
        if una[id] or not asg[id] or entry[id] then return false end
        local okf, ok = pcall(function()
            local it = df.item.find(id)
            if not it then return false end
            -- (0.105.2 review) only what DF could hand out, and not mid-pickup
            if it.flags.in_job then return false end
            return free_gear(it, work)
        end)
        return okf and ok
    end
    local n = 0
    for _, sq in ipairs(fort_squads()) do
        for _, pos in ipairs(sq.positions) do
            pcall(function()
                local mine = {}
                for cat = 0, df.uniform_category._last_item do
                    for _, spec in ipairs(pos.equipment.uniform[cat]) do
                        for _, iid in ipairs(spec.assigned) do mine[iid] = true end
                    end
                end
                -- (0.105.0 review) an item the place's own soldier holds is not stale
                local hf = pos.occupant ~= -1 and df.historical_figure.find(pos.occupant)
                local uid = hf and hf.unit_id or nil
                local function held_by_occupant(id)
                    if not uid or uid == -1 then return false end
                    local okh, u = pcall(function()
                        local it = df.item.find(id)
                        return it and dfhack.items.getHolderUnit(it)
                    end)
                    return okh and u ~= nil and u.id == uid
                end
                local v = pos.equipment.assigned_items
                for i = #v - 1, 0, -1 do
                    local id = v[i]
                    if una[id] and not mine[id] and not held_by_occupant(id) then
                        if not dry_run then v:erase(i) end
                        n = n + 1
                    elseif not mine[id] and not held_by_occupant(id) and free_again(id) then
                        if not dry_run then
                            v:erase(i)
                            if not moved[id] then
                                vec_remove(eq.items_assigned[asg[id]], id)
                                vec_add(eq.items_unassigned[asg[id]], id)
                                AW_LEDGER[id] = nil
                            end
                        end
                        moved[id] = true
                        n = n + 1
                    end
                end
            end)
        end
    end
    return n
end

local function loosen_material(dry_run)
    local fort = U.fort_entity()
    local eq = equipment_lists()
    if not fort or not eq then return 0 end
    local mine = M.ai_uniforms()
    local entry, place = claim_map()
    local ctx = {entry = entry, place = place, work = id_set(eq.work_weapons), una = id_set(eq.items_unassigned.WEAPON)}
    local n = 0
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq and mine[tostring(sid)] then
            for _, pos in ipairs(sq.positions) do
                pcall(function()
                    for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                        -- (0.105.0 review) a named weapon kind only: "any" loosened took anything
                        if #spec.assigned == 0 and spec.item_subtype ~= -1
                                and (spec.material_class ~= -1 or spec.mattype ~= -1) then
                            -- only when some item of its kind fails on the material alone
                            local best = 0
                            for _, it in ipairs(df.global.world.items.other.WEAPON) do
                                local st = item_stage(spec, it, true, ctx, nil)
                                if st > best then best = st end
                            end
                            if best == 2 then
                                if not dry_run then
                                    spec.material_class, spec.mattype, spec.matindex = -1, -1, -1
                                end
                                n = n + 1
                            end
                        end
                    end
                end)
            end
        end
    end
    return n
end

-- (0.105.2) A forbidden or dumped weapon an empty weapon entry wants is let
-- go again: B (2 Nov) had 20-23 places "forbidden, dumped or to melt" after
-- the human siege (a dead dwarf's things are forbidden by DF's standing
-- order) and every soldier unarmed. Only the forbid and dump marks are
-- cleared (a weapon set to melt is the player's call: left, and counted),
-- one weapon per empty entry, the nearest the soldier can walk to, and none
-- lying within UNFORBID_DANGER_TILES of a live enemy (a field of the dead
-- under fire is no place to send a dwarf for a sword).
UNFORBID_DANGER_TILES = U.DANGER_TILES or 20

-- (0.105.27) danger_spots / near_danger moved to ai-util (the disposal
-- actions use them too); these forward to it.
local function danger_spots()
    return U.danger_spots()
end

local function near_danger(spots, x, y, z)
    return U.near_danger(spots, x, y, z, UNFORBID_DANGER_TILES)
end

function unforbid_spares(dry_run, limit)
    limit = limit or 10
    local fort = U.fort_entity()
    local eq = equipment_lists()
    if not fort or not eq then return {n = 0, melt = 0, danger = 0} end
    local entry, place = claim_map()
    local ctx = {entry = entry, place = place, work = id_set(eq.work_weapons), una = id_set(eq.items_unassigned.WEAPON)}
    local spots = danger_spots()
    local taken, out = {}, {n = 0, melt = 0, danger = 0, items = {}}
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for _, pos in ipairs(sq and sq.positions or {}) do
            if out.n >= limit then return out end
            local hf = pos.occupant ~= -1 and df.historical_figure.find(pos.occupant)
            local u = hf and df.unit.find(hf.unit_id)
            local ux, uy, uz
            if u then ux, uy, uz = dfhack.units.getPosition(u) end
            if ux then
                local upos = xyz2pos(ux, uy, uz)
                local specs = {}
                pcall(function()
                    for _, sp in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                        if #sp.assigned == 0 then table.insert(specs, sp) end
                    end
                end)
                for _, spec in ipairs(specs) do
                    if out.n >= limit then break end
                    local best, bd, melt_seen, danger_seen = nil, nil, false, false
                    for _, it in ipairs(df.global.world.items.other.WEAPON) do
                        if not taken[it.id] then
                            local f = it.flags
                            if (f.forbid or f.dump or f.melt) and not f.in_job then
                                local ok, st = pcall(item_stage, spec, it, true, ctx, upos)
                                -- stage 7 here: only the mark stands between it and the entry
                                if ok and st == 7 then
                                    local x, y, z = dfhack.items.getPosition(it)
                                    if f.melt then
                                        melt_seen = true
                                    elseif x and near_danger(spots, x, y, z) then
                                        danger_seen = true
                                    elseif x then
                                        local okw, walk = pcall(dfhack.maps.canWalkBetween, upos, xyz2pos(x, y, z))
                                        if okw and walk then
                                            local d = math.abs(x - ux) + math.abs(y - uy) + 3 * math.abs(z - uz)
                                            if not bd or d < bd then best, bd = it, d end
                                        end
                                    end
                                end
                            end
                        end
                    end
                    if best then
                        taken[best.id] = true
                        if not dry_run then
                            best.flags.forbid = false
                            best.flags.dump = false
                        end
                        out.n = out.n + 1
                        local okd, d = pcall(function()
                            return (dfhack.df2utf or tostring)(dfhack.items.getDescription(best, 0, true))
                        end)
                        if #out.items < 6 then table.insert(out.items, okd and d or ('#' .. best.id)) end
                    elseif melt_seen then
                        out.melt = out.melt + 1
                    elseif danger_seen then
                        out.danger = out.danger + 1
                    end
                end
            end
        end
    end
    return out
end

local function add_shields(dry_run)
    local fort = U.fort_entity()
    if not fort then return 0 end
    local mine = M.ai_uniforms()
    local n = 0
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        local name = mine[tostring(sid)]
        if sq and tostring(name or ''):lower():find('metal', 1, true) and not M.squad_is_ranged(sq, name) then
            for _, pos in ipairs(sq.positions) do
                pcall(function()
                    local v = pos.equipment.uniform[df.uniform_category.shield]
                    if #v == 0 then
                        if not dry_run then
                            local spec = df.squad_uniform_spec:new()
                            spec.item = -1
                            spec.item_type = df.item_type.SHIELD
                            spec.item_subtype = -1
                            spec.material_class, spec.mattype, spec.matindex = -1, -1, -1
                            pcall(function() spec.color = -1 end)
                            v:insert('#', spec)
                        end
                        n = n + 1
                    end
                end)
            end
        end
    end
    return n
end

function fix_gear_gaps(dry_run, shields)
    local out = {stale = stale_places(dry_run), loosened = loosen_material(dry_run),
                 shields_added = shields and add_shields(dry_run) or 0}
    -- (0.105.2) forbidden or dumped weapons the entries want, let go
    local oku, uf = pcall(unforbid_spares, dry_run, 10)
    uf = oku and type(uf) == 'table' and uf or {n = 0, melt = 0, danger = 0}
    out.unforbidden = uf.n
    if uf.items and #uf.items > 0 then out.unforbidden_items = uf.items end
    if uf.melt > 0 then out.left_to_melt = uf.melt end
    if uf.danger > 0 then out.left_near_enemies = uf.danger end
    if not dry_run and out.stale + out.loosened + out.shields_added > 0 then
        for _, f in ipairs({'weapon', 'shield'}) do
            pcall(function() df.global.plotinfo.equipment.update[f] = true end)
        end
    end
    local okw, w = pcall(assign_weapons, dry_run, 10)
    out.weapons = okw and type(w) == 'table' and (w.assigned or w.would_assign) or 0
    if out.stale + out.loosened + out.shields_added + out.weapons + out.unforbidden == 0 then
        local why = 'nothing to fix (see the report\'s weapon_gaps_why)'
        -- (0.105.2 review) enemies or melt marks: looked at again in 2 days,
        -- no back-off (a long siege's waits kept the dead's weapons forbidden
        -- after it, and later gaps waited too)
        local waiting = nil
        if (out.left_near_enemies or 0) > 0 then
            why, waiting = out.left_near_enemies .. ' wanted weapon(s) lie near enemies: left forbidden until they go', true
        elseif (out.left_to_melt or 0) > 0 then
            why, waiting = out.left_to_melt .. ' wanted weapon(s) are set to melt: left for the player', true
        end
        return {ok = false, rejected = true, waiting = waiting, error = why}
    end
    out.ok, out.dry_run = true, dry_run or nil
    return out
end
