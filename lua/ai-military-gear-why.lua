-- ai-military-gear-why: why a soldier's weapon or shield entry stays
-- empty (gaps_why: each empty entry judged against every item of its kind,
-- the furthest stage the best one reached).
--
-- (r8) A part of ai-military-gear, not a script of its own: ai-military-gear.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-military-gear').name (and ai-military's, through its forwarders)
-- and a name swapped there reaches this file.

if not GEAR_PART_LOCALS then qerror('ai-military-gear-why is a part of ai-military-gear; run ai-military-gear') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-gear-why'] = '0.105.75'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, fort_squads, memo, eq_ids, gear_items, free_gear = GEAR_PART_LOCALS.U, GEAR_PART_LOCALS.fort_squads, GEAR_PART_LOCALS.memo, GEAR_PART_LOCALS.eq_ids, GEAR_PART_LOCALS.gear_items, GEAR_PART_LOCALS.free_gear   -- (r8) handed on by the files before

-- ===========================================================================
-- (0.105.0) Round 2, an army that can fight: why a soldier's weapon (or
-- shield) entry stays empty, the fixes, quivers, bolts, and the shelter.
--
-- Teacheroar, 1 Nov: 39 soldiers, 23 armed, 16 weapon places empty and "0
-- fillable" while 8 battle axes lay spare; nobody had a shield with 4 spare;
-- the crossbow squad had no quivers. Each empty entry is now judged against
-- every item of its kind, and the reason the best one fails is reported
-- (weapon_gaps_why), so the cause is seen, not guessed.
-- ===========================================================================

-- the stages an item passes on its way to an empty entry, in order; a gap's
-- reason is the furthest stage any item reached
GAP_STAGES = {'none of its kind', 'wrong material', 'held, owned or a tool', "another soldier's",
              "stale on a soldier's list", 'not on the free list', 'forbidden, dumped or to melt', 'in a job',
              'unreachable', 'fillable'}

-- an entry of any other kind (a shield): its kind and material
local function item_fits(spec, it, is_weapon)
    if is_weapon then return weapon_fits(spec, it) end
    if spec.item_subtype ~= -1 and it:getSubtype() ~= spec.item_subtype then return false, 'kind' end
    local okm, mt, mi = pcall(function() return spec.mattype, spec.matindex end)
    if okm and mt ~= nil and mt ~= -1 then
        if it:getMaterial() ~= mt or (mi ~= -1 and it:getMaterialIndex() ~= mi) then return false, 'material' end
    end
    local okk, cls = pcall(function() return df.entity_material_category[spec.material_class] end)
    if okk and cls == 'Armor' and metal_token(it) == nil then return false, 'material' end
    return true
end

-- who claims what: an entry's own assigned list, or only a place's list
local function claim_map()
    return memo('claim_map', function()
    local entry, place = {}, {}
    for _, sq in ipairs(fort_squads()) do
        for _, pos in ipairs(sq.positions) do
            local mine = {}
            pcall(function()
                for cat = 0, df.uniform_category._last_item do
                    for _, spec in ipairs(pos.equipment.uniform[cat]) do
                        for _, iid in ipairs(spec.assigned) do entry[iid] = true; mine[iid] = true end
                    end
                end
            end)
            pcall(function()
                for _, iid in ipairs(pos.equipment.assigned_items) do
                    if not mine[iid] then place[iid] = true end
                end
            end)
        end
    end
    return entry, place
    end)
end

local function spec_text(spec)
    local what = '?'
    pcall(function()
        if spec.item_subtype == -1 then
            local c = spec.indiv_choice
            what = (c and c.ranged and not c.melee) and 'any ranged' or (c and c.melee) and 'any melee' or 'any'
        else
            local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
            what = def and def.id or tostring(spec.item_subtype)
        end
    end)
    pcall(function()
        local cls = df.entity_material_category[spec.material_class]
        if cls and cls ~= 'None' then what = what .. ' ' .. cls end
        if spec.mattype ~= -1 then what = what .. ' mat ' .. spec.mattype .. ':' .. spec.matindex end
    end)
    return what
end

local function is_ranged_spec(spec, is_weapon)
    if not is_weapon then return false end
    local r = false
    pcall(function()
        if spec.item_subtype ~= -1 then
            local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
            r = def ~= nil and weapon_is_ranged(def)
        else
            r = spec.indiv_choice.ranged and not spec.indiv_choice.melee
        end
    end)
    return r == true
end

-- How far one item gets toward the entry (a stage number, GAP_STAGES).
local function item_stage(spec, it, is_weapon, ctx, upos)
    local ok, why = item_fits(spec, it, is_weapon)
    if not ok then return why == 'material' and 2 or 1 end
    if not free_gear(it, ctx.work) then return 3 end
    if ctx.entry[it.id] then return 4 end
    if ctx.place[it.id] then return 5 end
    if not ctx.una[it.id] then return 6 end
    local f = it.flags
    if f.forbid or f.dump or f.melt then return 7 end
    if f.in_job then return 8 end
    if upos then
        local x, y, z = dfhack.items.getPosition(it)
        local okw, walk = pcall(function() return x ~= nil and dfhack.maps.canWalkBetween(upos, xyz2pos(x, y, z)) end)
        if okw and not walk then return 9 end
    end
    return 10
end

-- The reasons for one kind of entry ('weapon' or 'shield'): {why = {reason
-- = n}, detail = {...}, wanted = {item id = n}, ranged = n, entries = n,
-- given = n, places = n, no_entry = n}.
function gaps_why(cat_name, list_name)
    local out = {why = {}, detail = {}, wanted = {}, ranged = 0, entries = 0, given = 0, places = 0, no_entry = 0,
                 no_entry_squads = {}}     -- (0.105.0 review) by squad id (text)
    local fort = U.fort_entity()
    local eq = equipment_lists()
    if not fort or not eq then return out end
    local is_weapon = cat_name == 'weapon'
    local cat = df.uniform_category[cat_name]
    local entry, place = claim_map()
    local ctx = {entry = entry, place = place, work = eq_ids(eq, 'work_weapons'),
                 una = eq_ids(eq, 'items_unassigned', list_name)}
    local items = gear_items(list_name)
    -- (0.105.33 review) an entry's stage depends only on what it asks for and
    -- where its soldier can walk: worked out once per (entry kind, walk
    -- group), not entries x every item (16 empty entries x a post-siege
    -- pile of thousands of weapons, every pulse)
    local stage_memo = {}
    local function spec_key(spec)
        local ok, k = pcall(function()
            local c = spec.indiv_choice
            return table.concat({tostring(spec.item_subtype), tostring(spec.mattype), tostring(spec.matindex),
                tostring(spec.material_class), tostring(c and c.melee), tostring(c and c.ranged)}, ':')
        end)
        return ok and k or nil
    end
    local function walk_key(upos)
        local ok, g = pcall(dfhack.maps.getWalkableGroup, upos)
        if ok and type(g) == 'number' and g ~= 0 then return 'g' .. g end
        return ('p%s,%s,%s'):format(upos.x, upos.y, upos.z)
    end
    local function best_stage(spec, upos)
        local sk = spec_key(spec)
        local key = sk and (sk .. '@' .. walk_key(upos))
        if key and stage_memo[key] then return stage_memo[key] end
        local best = 0
        for _, it in ipairs(items) do
            local st = item_stage(spec, it, is_weapon, ctx, upos)
            if st > best then best = st end
            if best == #GAP_STAGES then break end
        end
        if key then stage_memo[key] = best end
        return best
    end
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for pi, pos in ipairs(sq and sq.positions or {}) do
            if pos.occupant ~= -1 then
                out.places = out.places + 1
                local specs = {}
                pcall(function() for _, s in ipairs(pos.equipment.uniform[cat]) do table.insert(specs, s) end end)
                if #specs == 0 then
                    out.no_entry = out.no_entry + 1
                    out.no_entry_squads[tostring(sid)] = (out.no_entry_squads[tostring(sid)] or 0) + 1
                end
                local hf = df.historical_figure.find(pos.occupant)
                local u = hf and df.unit.find(hf.unit_id)
                local upos
                if u then
                    local x, y, z = dfhack.units.getPosition(u)
                    if x then upos = xyz2pos(x, y, z) end
                end
                for _, spec in ipairs(specs) do
                    out.entries = out.entries + 1
                    if #spec.assigned > 0 then
                        out.given = out.given + 1
                    else
                        local best = 0
                        if upos then
                            best = math.max(best_stage(spec, upos), 1)
                        end
                        local why = best == 0 and 'no soldier on the map' or GAP_STAGES[best]
                        out.why[why] = (out.why[why] or 0) + 1
                        if is_ranged_spec(spec, is_weapon) then out.ranged = out.ranged + 1 end
                        if best == 1 and spec.item_subtype ~= -1 then
                            local okd, def = pcall(dfhack.items.getSubtypeDef, spec.item_type, spec.item_subtype)
                            local id = okd and def and def.id or tostring(spec.item_subtype)
                            out.wanted[id] = (out.wanted[id] or 0) + 1
                        end
                        if #out.detail < 6 then
                            table.insert(out.detail, ('squad %d place %d wants %s: %s'):format(sid, pi, spec_text(spec), why))
                        end
                    end
                end
            end
        end
    end
    return out
end

-- (r8) this part's helpers the later parts use, handed on to them
GEAR_PART_LOCALS.is_ranged_spec, GEAR_PART_LOCALS.claim_map, GEAR_PART_LOCALS.item_stage, GEAR_PART_LOCALS.item_fits = is_ranged_spec, claim_map, item_stage, item_fits
