-- ai-military-uniforms: does a place have a uniform (found by field name), the
-- uniform probe, uniforms from the fort's templates (pick, apply, clear), the
-- bolts a squad may use, worn clothing replaced, a uniform set, its weapon
-- changed, the player's uniform adopted, and the names of those the AI set.
--
-- (r8) A part of ai-military, not a script of its own: ai-military.lua loads
-- it into its own environment, so every name here is
-- reqscript('ai-military').name and a name swapped there reaches this file.

if not MILITARY_PART_LOCALS then qerror('ai-military-uniforms is a part of ai-military; run ai-military') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-uniforms'] = '0.105.63'   -- (0.105.26) bumped with BRIDGE_VERSION

local U = MILITARY_PART_LOCALS.U   -- (r8) the hub's locals

-- Does a squad position have a uniform? Found by field name, since where DF
-- keeps it has moved between versions (pos.uniform, pos.equipment.uniform...):
-- any field whose name contains "uniform" holding a non-empty list.
local function entries(v)
    local ok, n = pcall(function() return #v end)
    if not ok or type(n) ~= 'number' or n == 0 then return 0 end
    local total = 0
    for i = 0, n - 1 do
        local okx, x = pcall(function() return v[i] end)
        if okx and type(x) == 'userdata' then
            local okn, m = pcall(function() return #x end)
            total = total + ((okn and type(m) == 'number') and m or 1)
        elseif okx and x ~= nil then
            total = total + 1
        end
    end
    return total
end

local function has_uniform(obj, depth)
    local ok, found = pcall(function()
        for k, v in pairs(obj) do
            if type(k) == 'string' and k:lower():find('uniform') and entries(v) > 0 then return true end
            if depth > 0 and type(k) == 'string' and type(v) == 'userdata'
                    and (k == 'equipment' or k:lower():find('equip')) and has_uniform(v, depth - 1) then
                return true
            end
        end
        return false
    end)
    return ok and found
end

local function position_has_uniform(pos)
    -- DF 50+: pos.equipment.uniform[category] (squad_position_equipmentst)
    local ok, found = pcall(function()
        for cat = 0, df.uniform_category._last_item do
            if #pos.equipment.uniform[cat] > 0 then return true end
        end
        return false
    end)
    if ok then return found end
    return has_uniform(pos, 2)
end
uniform_set = position_has_uniform       -- (for make_squad and the report, defined above this)

-- For brain/selftest.py: the field names of a squad and one of its
-- positions, to see where this DF version keeps uniforms.
function probe()
    local fort = U.fort_entity()
    if not fort or #fort.squads == 0 then return {note = 'no squads'} end
    local sq = df.squad.find(fort.squads[0])
    local function fields(obj, depth)
        local out = {}
        local ok = pcall(function()
            for k, v in pairs(obj) do
                local t = type(v)
                local n = entries(v)
                local e = tostring(k) .. ':' .. t .. (n > 0 and ('[' .. n .. ']') or '')
                if depth > 0 and t == 'userdata' and n == 0 then
                    local sub = fields(v, depth - 1)
                    if #sub > 0 then e = e .. '{' .. table.concat(sub, ',') .. '}' end
                end
                table.insert(out, e)
            end
        end)
        if not ok then table.insert(out, '?') end
        return out
    end
    local pos = #sq.positions > 1 and sq.positions[1] or sq.positions[0]
    return {squad = table.concat(fields(sq, 0), ' '), position = table.concat(fields(pos, 1), ' ')}
end

-- --- uniforms from the fort's templates ----------------------------------------

-- A squad without a uniform fights in its clothes and the armour the fort
-- makes is never handed out. The fort has uniform templates (DF's military
-- screen: "Melee, leather armor", "Melee, metal armor", ...); the AI gives
-- such a squad one of them, as the screen's "apply uniform" does: each
-- template entry becomes a uniform entry on every place in the squad. A
-- squad the AI gave a uniform to may later be moved to a better one (leather
-- to metal); a uniform you set yourself is never touched.
-- (UNIFORMS_KEY and ai_uniforms() are defined above make_squad)

-- (0.105.33 review) Pure: a template's name says crossbows. One test for
-- pick_template and set_uniform (a fort with only a "Ranged" template was
-- picked it, then refused it: "no crossbow uniform template").
function ranged_template_name(name)
    local l = tostring(name):lower()
    return l:find('crossbow', 1, true) ~= nil or l:find('archer', 1, true) ~= nil or l:find('ranged', 1, true) ~= nil
end

-- Pure: the template to use from their names. kind 'metal' or 'leather';
-- melee before crossbows; else the first one.
function pick_template(names, kind, ranged)
    local best, best_score
    for i, n in ipairs(names) do
        local l = tostring(n):lower()
        local score = 0
        if l:find(kind or 'leather', 1, true) then score = score + 2 end
        if ranged then
            if ranged_template_name(l) then
                score = score + 4
            end
        elseif l:find('melee', 1, true) then score = score + 1 end
        if not best_score or score > best_score then best, best_score = i, score end
    end
    return best
end

local function clear_uniform(pos)
    for cat = 0, df.uniform_category._last_item do
        local v = pos.equipment.uniform[cat]
        for i = #v - 1, 0, -1 do
            local spec = v[i]
            v:erase(i)
            pcall(function() spec:delete() end)
        end
    end
end

local function apply_template(uf, sq)
    local n, rc_err = 0, nil
    for p = 0, #sq.positions - 1 do
        local pos = sq.positions[p]
        clear_uniform(pos)
        for cat = 0, df.uniform_category._last_item do
            local types, subs, infos = uf.uniform_item_types[cat], uf.uniform_item_subtypes[cat], uf.uniform_item_info[cat]
            for i = 0, #types - 1 do
                local info = infos[i]
                local spec = df.squad_uniform_spec:new()
                spec.item = -1
                spec.item_type = types[i]
                spec.item_subtype = subs[i]
                if info then
                    spec.material_class = info.material_class
                    spec.mattype = info.mattype
                    spec.matindex = info.matindex
                    pcall(function() spec.color = info.item_color end)
                    pcall(function() spec.indiv_choice.whole = info.indiv_choice.whole end)
                end
                pos.equipment.uniform[cat]:insert('#', spec)
                n = n + 1
            end
        end
        pcall(function() pos.equipment.flags.whole = uf.flags.whole end)
        -- (0.99.9) the kit replaces clothes: worn over them, a wool glove or
        -- a pig tail shoe keeps the steel one off (region2: 30 on duty, none
        -- armed or helmed; uniform-unstick: "... blocking a missing uniform item")
        -- (13c) a DF without the flag: said in the result (it was silently skipped)
        local okr, err = pcall(function() pos.equipment.flags.replace_clothing = true end)
        if not okr then rc_err = tostring(err):sub(1, 120) end
        pcall(function() pos.equipment.nickname = uf.name end)
    end
    for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'ammo', 'pants'}) do
        pcall(function()
            sq.ammo.update[f] = true
            df.global.plotinfo.equipment.update[f] = true
        end)
    end
    return n, rc_err
end

-- Give a squad one of the fort's uniform templates ('leather' or 'metal').
-- A squad that has a uniform is left alone, unless the AI set it (then it
-- may change to another template).
-- Bolts for a crossbow squad: one ammunition entry (bolts of any material,
-- for combat and training), `amount` in all, as the squad's ammo screen sets.
BOLTS_PER_SOLDIER = 50
function set_bolts(sq, amount)
    local sub
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.ammo) do
            if def.id == 'ITEM_AMMO_BOLTS' then sub = def.subtype ~= nil and def.subtype or i end
        end
    end)
    if sub == nil then return false, 'no bolts in this game' end
    local v = sq.ammo.ammunition
    for i = #v - 1, 0, -1 do
        local a = v[i]
        v:erase(i)
        pcall(function() a:delete() end)
    end
    local spec = df.squad_ammo_spec:new()
    spec.item_type = df.item_type.AMMO
    spec.item_subtype = sub
    pcall(function() spec.material_class = -1 end)
    spec.mattype, spec.matindex = -1, -1
    spec.amount = amount
    spec.flags.use_combat = true
    spec.flags.use_training = true
    v:insert('#', spec)
    pcall(function()
        sq.ammo.update.ammo = true
        df.global.plotinfo.equipment.update.ammo = true
    end)
    return true
end

-- (0.99.9) The uniforms the AI set replace clothes instead of going over
-- them (DF's own uniform option). Squads someone else dressed are left alone.
-- Returns how many positions changed.
function replace_clothing(dry_run)
    local mine, n = ai_uniforms(), 0
    for key in pairs(mine) do
        local sq = fort_squad(tonumber(key))
        if sq then
            for p = 0, #sq.positions - 1 do
                local pos = sq.positions[p]
                -- (13c) read and set directly: a DF without the flag raises an
                -- error the unstick action reports (the pcalls here hid it, and
                -- the count said 0)
                if not pos.equipment.flags.replace_clothing then
                    if not dry_run then pos.equipment.flags.replace_clothing = true end
                    n = n + 1
                end
            end
        end
    end
    if n > 0 and not dry_run then
        for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'pants'}) do
            pcall(function() df.global.plotinfo.equipment.update[f] = true end)
        end
    end
    return n
end

function set_uniform(squad_id, kind, dry_run, txt, ranged)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local fort = U.fort_entity()
    if not fort or #fort.uniforms == 0 then
        return {ok = false, rejected = true, error = 'the fort has no uniform templates (make one in the military screen)'}
    end
    local names = {}
    for i, uf in ipairs(fort.uniforms) do names[i + 1] = uf.name end
    local idx = pick_template(names, kind, ranged)
    local uf = fort.uniforms[idx - 1]
    if ranged and not ranged_template_name(uf.name) then
        return {ok = false, rejected = true, error = 'the fort has no crossbow uniform template'}
    end
    local mine = ai_uniforms()
    local had = #sq.positions > 0 and uniform_set(sq.positions[0])
    local key = tostring(squad_id)
    if had and not mine[key] then
        return {ok = false, rejected = true, error = 'the squad has a uniform someone set: left alone'}
    end
    if had and tostring(mine[key]):gsub(' |weapon:.*$', '') == uf.name then
        return {ok = false, rejected = true, error = 'the squad already wears ' .. uf.name}
    end
    local name = (txt or tostring)(uf.name)
    if dry_run then return {ok = true, dry_run = true, template = name, replaces = mine[key]} end
    local was_ranged = had and tostring(mine[key] or ''):lower():find('crossbow', 1, true)
    local n, rc_err = apply_template(uf, sq)
    if n == 0 then return {ok = false, error = 'the template ' .. name .. ' has nothing in it'} end
    local cleared
    if was_ranged and not ranged then
        -- back to close combat: the bolts the AI asked for go too
        pcall(function()
            local v = sq.ammo.ammunition
            for i = #v - 1, 0, -1 do
                local a = v[i]
                v:erase(i)
                pcall(function() a:delete() end)
            end
            sq.ammo.update.ammo = true
            df.global.plotinfo.equipment.update.ammo = true
            cleared = true
        end)
    end
    mine[key] = uf.name
    U.site_put(UNIFORMS_KEY, mine)
    local bolts
    if ranged then
        bolts = BOLTS_PER_SOLDIER * math.max(1, #sq.positions)
        local okb, err = set_bolts(sq, bolts)
        if not okb then bolts = 'not set: ' .. tostring(err) end
    end
    return {ok = true, template = name, items = n, replaced = had or nil, bolts = bolts, bolts_cleared = cleared,
            replace_clothing_error = rc_err}
end

-- The weapon in a squad's uniform made one kind (e.g. ITEM_WEAPON_AXE_BATTLE)
-- instead of "any melee weapon", which lets a soldier take a miner's pick
-- (a pick is a weapon). Only on a uniform the AI set.
-- (0.100) Is this a squad of shooters? Its stored entry says crossbow, or
-- its uniform's weapon is a crossbow or "any ranged weapon".
function squad_is_ranged(sq, entry)
    if tostring(entry or ''):lower():find('crossbow', 1, true) then return true end
    local ranged = false
    pcall(function()
        for _, spec in ipairs(sq.positions[0].equipment.uniform[df.uniform_category.weapon]) do
            if spec.indiv_choice.ranged then ranged = true end
            if spec.item_subtype ~= -1 then
                local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
                if def and def.id == 'ITEM_WEAPON_CROSSBOW' then ranged = true end
            end
        end
    end)
    return ranged
end

function set_uniform_weapon(squad_id, weapon_id, dry_run)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local mine = ai_uniforms()
    local key = tostring(squad_id)
    if not mine[key] then return {ok = false, rejected = true, error = 'not a uniform the AI set: left alone'} end
    -- (0.100) a crossbow squad keeps its crossbows, whatever is asked (region2's
    -- squad 56 was given battle axes)
    if weapon_id ~= 'ITEM_WEAPON_CROSSBOW' and squad_is_ranged(sq, mine[key]) then
        return {ok = false, rejected = true, error = 'a crossbow squad: its weapon stays the crossbow'}
    end
    -- the weapon's subtype: its place among the game's weapon definitions
    -- (0.51 asked dfhack.items.findSubtype, which didn't give it)
    local sub
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.weapons) do
            if def.id == weapon_id then sub = def.subtype ~= nil and def.subtype or i end
        end
    end)
    if sub == nil then
        return {ok = false, rejected = true, error = 'no such weapon: ' .. tostring(weapon_id)}
    end
    if dry_run then return {ok = true, dry_run = true, weapon = weapon_id} end
    local cat = df.uniform_category.weapon
    for p = 0, #sq.positions - 1 do
        local v = sq.positions[p].equipment.uniform[cat]
        for i = #v - 1, 0, -1 do
            local spec = v[i]
            v:erase(i)
            pcall(function() spec:delete() end)
        end
        local spec = df.squad_uniform_spec:new()
        spec.item = -1
        spec.item_type = df.item_type.WEAPON
        spec.item_subtype = sub
        spec.material_class = -1
        spec.mattype = -1
        spec.matindex = -1
        -- (0.104.80) any colour: a new entry's colour is 0, a dye colour, so DF
        -- gave no weapon to it and took back every one the AI gave (Enxah)
        pcall(function() spec.color = -1 end)
        v:insert('#', spec)
    end
    for _, f in ipairs({'weapon'}) do
        pcall(function()
            sq.ammo.update[f] = true
            df.global.plotinfo.equipment.update[f] = true
        end)
    end
    local base = tostring(mine[key]):gsub(' |weapon:.*$', '')
    mine[key] = base .. ' |weapon:' .. weapon_id
    U.site_put(UNIFORMS_KEY, mine)
    return {ok = true, weapon = weapon_id, places = #sq.positions}
end

-- A squad the AI made whose uniform it copied before 0.82 (when copies
-- weren't recorded): the uniform is marked as the AI's, named after the
-- fort's template it matches (crossbow or melee, metal or leather; the
-- weapon kind if one is asked for), so the AI may change it later. Only a
-- squad with a uniform and not already marked; the planner asks only for
-- squads it made itself (memory.squads_made).
function adopt_uniform(squad_id, dry_run, txt)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local mine = ai_uniforms()
    local key = tostring(squad_id)
    if mine[key] then return {ok = false, rejected = true, error = 'already the AI\'s: ' .. tostring(mine[key])} end
    if #sq.positions == 0 or not uniform_set(sq.positions[0]) then
        return {ok = false, rejected = true, error = 'the squad has no uniform'}
    end
    local ranged, metal, weapon = false, false, nil
    local pos = sq.positions[0]
    for cat = 0, df.uniform_category._last_item do
        for _, spec in ipairs(pos.equipment.uniform[cat]) do
            if spec.material_class == df.entity_material_category.Armor then metal = true end
            -- (0.100) "any ranged weapon" is a crossbow squad too (it was adopted as melee)
            if spec.item_type == df.item_type.WEAPON then
                pcall(function() if spec.indiv_choice.ranged then ranged = true end end)
            end
            if spec.item_type == df.item_type.WEAPON and spec.item_subtype ~= -1 then
                pcall(function()
                    local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
                    weapon = def and def.id or weapon
                end)
            end
        end
    end
    if weapon == 'ITEM_WEAPON_CROSSBOW' then ranged, weapon = true, nil end
    if ranged then weapon = nil end
    local fort = U.fort_entity()
    local names = {}
    for i, uf in ipairs(fort and fort.uniforms or {}) do names[i + 1] = uf.name end
    if #names == 0 then return {ok = false, rejected = true, error = 'the fort has no uniform templates'} end
    local name = names[pick_template(names, metal and 'metal' or 'leather', ranged)]
    local entry = name .. (weapon and (' |weapon:' .. weapon) or '')
    if dry_run then return {ok = true, dry_run = true, uniform = entry} end
    mine[key] = entry
    U.site_put(UNIFORMS_KEY, mine)
    return {ok = true, uniform = (txt or tostring)(entry)}
end

-- Squads whose uniform the AI set: squad id -> template name.
function ai_uniform_names(txt)
    local out = {}
    for k, v in pairs(ai_uniforms()) do out[k] = (txt or tostring)(v) end
    return out
end
