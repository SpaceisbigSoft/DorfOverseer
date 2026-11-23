-- The fort's soldiers' gear (13c: split out of lua/ai-military.lua, which
-- keeps every name here reachable as reqscript('ai-military').<name>): the
-- gear report (who carries a weapon, wears armour and a helm; spare metal
-- gear; weapon-grade bars), gear DF keeps assigned to no one put back,
-- weapons, shields, quivers, bolts and armour given to the soldiers' empty
-- entries, why an entry stays empty, and the kit report.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules
local M = reqscript('ai-military')  -- the squads: fort_squad, ai_uniforms, routine_names...

-- Gear: how many soldiers carry a weapon, wear body armour and a helm; how
-- many squads have a uniform (without one, armour made isn't handed out);
-- spare metal gear; and weapon-grade metal bars by kind.
GEAR_METALS = {'STEEL', 'IRON', 'BRONZE', 'BISMUTH_BRONZE', 'COPPER'}   -- best first
-- (0.105.40 M7) the alloys and their parts, whose values the gear report gives
ALLOY_METALS = {'COPPER', 'TIN', 'BISMUTH', 'ZINC', 'SILVER', 'GOLD', 'BRONZE', 'BISMUTH_BRONZE', 'BRASS',
                'ELECTRUM', 'BILLON', 'BLACK_BRONZE', 'ROSE_GOLD', 'STERLING_SILVER'}
local GEAR_LISTS = {weapons = 'WEAPON', body = 'ARMOR', helms = 'HELM', pants = 'PANTS',
                    gloves = 'GLOVES', boots = 'SHOES', shields = 'SHIELD'}

local function metal_token_of(item)
    local mi = dfhack.matinfo.decode(item)
    if not mi or not mi.inorganic or not mi.material.flags.IS_METAL then return nil end
    return mi.inorganic.id
end

-- (0.105.40 E3) inside gear_report (CLAIM_MEMO) an item's metal is decoded
-- once: the report asked it of the same item up to a dozen times (the stray,
-- spare, bar and gap counts, and each kind of empty entry)
function metal_token(item)
    local m = CLAIM_MEMO
    if not m then return metal_token_of(item) end
    local okid, id = pcall(function() return item.id end)
    if not okid or id == nil then return metal_token_of(item) end
    local mt = m.metal
    if not mt then mt = {}; m.metal = mt end
    local v = mt[id]
    if v == nil then
        v = metal_token_of(item)
        if v == nil then mt[id] = false else mt[id] = v end
        return v
    end
    if v == false then return nil end
    return v
end

-- How an item is carried: the enum moved between DF versions
-- (df.inv_item_role_type in v50+, unit_inventory_item.T_mode before).
function inv_mode_name(mode)
    local okn, enum = pcall(function() return df.inv_item_role_type end)
    if not okn then enum = nil end
    if not enum then
        local ok, old = pcall(function() return df.unit_inventory_item.T_mode end)
        enum = ok and old or nil
    end
    return enum and enum[mode] or tostring(mode)
end

-- (0.104.58) Gear DF will never hand out again: on the fort's "assigned"
-- list though no soldier's place claims it (a dead or released soldier's), or
-- on no list at all. Enxah, summer y74: a copper battle axe lying free on the
-- assigned list with no claim, another on no list, 52 helms on the unassigned
-- list of 115 counted spare, while 19 soldiers went without an axe. DF's
-- lists are plotinfo.equipment.items_assigned / items_unassigned, by kind.
STRAY_KINDS = {'WEAPON', 'ARMOR', 'HELM', 'PANTS', 'GLOVES', 'SHOES', 'SHIELD'}

function id_set(v)
    local s = {}
    pcall(function() for _, id in ipairs(v) do s[id] = true end end)
    return s
end

-- (0.105.33 review) The fort's own squads: only they can claim the fort's
-- items. world.squads.all is every squad of every entity in the world (a
-- big world: thousands), walked several times a pulse. Falls back to it
-- only when the fort's entity can't be read.
local fort_squads_walk
local function fort_squads()
    -- (0.105.40 E3) inside gear_report, read once (a fresh list each caller)
    local m = CLAIM_MEMO
    if not m then return fort_squads_walk() end
    if not m.fort_squads then m.fort_squads = fort_squads_walk() end
    local out = {}
    for i, sq in ipairs(m.fort_squads) do out[i] = sq end
    return out
end
fort_squads_walk = function()
    local out = {}
    local okf, fort = pcall(U.fort_entity)
    if okf and fort then
        pcall(function()
            for _, sid in ipairs(fort.squads) do
                local sq = df.squad.find(sid)
                if sq then table.insert(out, sq) end
            end
        end)
        return out
    end
    pcall(function() for _, sq in ipairs(df.global.world.squads.all) do table.insert(out, sq) end end)
    return out
end

-- (0.105.33 review) gear_report builds the claim sets once (it only reads):
-- set for the length of one report, nil otherwise (actions build their own)
CLAIM_MEMO = nil
local function memo(key, build)
    local m = CLAIM_MEMO
    if not m then return build() end
    if m[key] == nil then m[key] = table.pack(build()) end
    return table.unpack(m[key], 1, m[key].n)
end

-- (0.105.40 E3) inside gear_report, one id set for each of DF's equipment
-- lists (`field`, and `kind` for the by-kind ones), not one each time a
-- count asks: the unassigned weapons were turned into a set 4 times a report.
-- A list that can't be read throws, as id_set's caller did before.
local function eq_ids(eq, field, kind)
    local m = CLAIM_MEMO
    local function build()
        if kind ~= nil then return id_set(eq[field][kind]) end
        return id_set(eq[field])
    end
    if not m then return build() end
    local key = 'ids:' .. field .. ':' .. tostring(kind)
    local v = m[key]
    if v == nil then v = build(); m[key] = v end
    return v
end

-- (0.105.40 E3) inside gear_report, items.other[name] read once into a list
-- (the same items, same order): the weapons were walked 4-6 times a report
local function gear_items(name)
    local m = CLAIM_MEMO
    local vec = df.global.world.items.other[name]
    if not m or vec == nil then return vec end
    local key = 'items:' .. tostring(name)
    local v = m[key]
    if v == nil then
        v = {}
        for _, it in ipairs(vec) do v[#v + 1] = it end
        m[key] = v
    end
    return v
end

-- every item any squad place claims (its own list or a uniform entry's)
local function claimed_items()
    return memo('claimed', function()
    local c = {}
    for _, sq in ipairs(fort_squads()) do
        for _, pos in ipairs(sq.positions) do
            pcall(function() for _, iid in ipairs(pos.equipment.assigned_items) do c[iid] = true end end)
            pcall(function()
                for cat = 0, df.uniform_category._last_item do
                    for _, spec in ipairs(pos.equipment.uniform[cat]) do
                        for _, iid in ipairs(spec.assigned) do c[iid] = true end
                    end
                end
            end)
        end
    end
    return c
    end)
end

-- An item DF could hand to a soldier: none a unit holds, a trader's, an
-- enemy's, built in, an artifact, owned, or a worker's tool.
-- (lua/ai-util.lua's list; forbidden, for the dump or in a job is still the
-- fort's to hand out: the callers unforbid, or skip a job's, themselves)
local GEAR_OK = {forbid = true, dump = true, in_job = true}
local function free_gear(it, work)
    return not work[it.id] and U.item_free(it, GEAR_OK)
end

-- The fort's equipment lists, or nil where this DF keeps them elsewhere.
function equipment_lists()
    local ok, eq = pcall(function() return df.global.plotinfo.equipment end)
    if not ok or not eq then return nil end
    local okv = pcall(function() return #eq.items_assigned.WEAPON + #eq.items_unassigned.WEAPON end)
    if not okv then return nil end
    return eq
end

-- Counts by kind: `orphan` on the assigned list with no claim, `unlisted` on
-- neither list (both free items only); `unassigned` the ids DF may hand out.
function stray_report()
    local eq = equipment_lists()
    if not eq then return nil end
    local claimed, work = claimed_items(), eq_ids(eq, 'work_weapons')
    local out = {orphan = {}, unlisted = {}, n = 0, unassigned = {}, work = work}
    for _, kind in ipairs(STRAY_KINDS) do
        local asg, una = eq_ids(eq, 'items_assigned', kind), eq_ids(eq, 'items_unassigned', kind)
        out.unassigned[kind] = una
        -- (0.104.59) new items wait on the "unmanifested" list before DF files
        -- them: listed, not stray (a new axe from the forge counted as lost)
        local okm, unm = pcall(function() return eq_ids(eq, 'items_unmanifested', kind) end)
        unm = okm and unm or {}
        local o, u = 0, 0
        for _, it in ipairs(gear_items(kind)) do
            if free_gear(it, work) and not claimed[it.id] and not unm[it.id] then
                if asg[it.id] and not una[it.id] then o = o + 1
                elseif not asg[it.id] and not una[it.id] then u = u + 1 end
            end
        end
        if o > 0 then out.orphan[kind] = o end
        if u > 0 then out.unlisted[kind] = u end
        out.n = out.n + o + u
    end
    return out
end

local function vec_remove(v, id)
    for i = #v - 1, 0, -1 do
        if v[i] == id then v:erase(i) return true end
    end
    return false
end

local function vec_add(v, id)
    -- DF keeps these lists in id order; insert in order (append if it isn't)
    local n = #v
    local sorted = true
    for i = 1, n - 1 do
        if v[i - 1] > v[i] then sorted = false break end
    end
    if sorted then
        local pos = n
        for i = 0, n - 1 do
            if v[i] == id then return false end
            if v[i] > id then pos = i break end
        end
        v:insert(pos, id)
    else
        for i = 0, n - 1 do if v[i] == id then return false end end
        v:insert('#', id)
    end
    return true
end

-- Put stray gear back on the unassigned list so DF hands it out again (at
-- most `limit` items), and ask DF to redo its assignments: every kind
-- assigned to no one; on no list, weapons only.
function free_stray_gear(dry_run, limit)
    local eq = equipment_lists()
    if not eq then return {ok = false, rejected = true, error = "this DF keeps its equipment lists elsewhere"} end
    limit = limit or 100
    local claimed, work = claimed_items(), id_set(eq.work_weapons)
    local moved, by_kind = 0, {}
    for _, kind in ipairs(STRAY_KINDS) do
        local asgv, unav = eq.items_assigned[kind], eq.items_unassigned[kind]
        local asg, una = id_set(asgv), id_set(unav)
        local okm, unm = pcall(function() return id_set(eq.items_unmanifested[kind]) end)
        unm = okm and unm or {}
        for _, it in ipairs(df.global.world.items.other[kind]) do
            if moved >= limit then break end
            -- on no list: weapons only (armour may be left off for its size:
            -- reported, not moved, until a probe shows why)
            if free_gear(it, work) and not claimed[it.id] and not una[it.id] and not unm[it.id]
                    and (asg[it.id] or kind == 'WEAPON') then
                if not dry_run then
                    if asg[it.id] then vec_remove(asgv, it.id) end
                    vec_add(unav, it.id)
                end
                moved = moved + 1
                by_kind[kind] = (by_kind[kind] or 0) + 1
            end
        end
    end
    if dry_run then return {ok = true, dry_run = true, would_free = moved, by_kind = by_kind} end
    if moved > 0 then
        for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'pants'}) do
            pcall(function() df.global.plotinfo.equipment.update[f] = true end)
        end
    end
    return {ok = true, freed = moved, by_kind = by_kind}
end

-- (0.104.60) Weapons handed out by the AI when DF won't: Enxah, autumn y74,
-- every melee uniform entry asked for a battle axe ("given 0" on all 19
-- melee places) while 19 free axes lay on DF's unassigned list; the armour
-- of the same uniforms was handed out (helmed 6 -> 20 in a month). The
-- item goes on the soldier's place as DF's own assignments do (the entry's
-- `assigned`, the place's `assigned_items`, from the unassigned to the
-- assigned list); the soldier then fetches it (PickupEquipment).
local function weapon_specs_empty(pos)
    local out = {}
    pcall(function()
        for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
            if spec.item_type == df.item_type.WEAPON and #spec.assigned == 0 then table.insert(out, spec) end
        end
    end)
    return out
end

-- occupied places whose weapon entry has nothing; and how many melee
-- entries have a weapon given (fetched or not: the arms rule counts them)
function weapon_gaps()
    local fort, n, given = U.fort_entity(), 0, 0
    if not fort then return 0, 0 end
    local xbow
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.weapons) do
            if def.id == 'ITEM_WEAPON_CROSSBOW' then xbow = def.subtype ~= nil and def.subtype or i end
        end
    end)
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq then
            for _, pos in ipairs(sq.positions) do
                if pos.occupant ~= -1 then
                    n = n + #weapon_specs_empty(pos)
                    pcall(function()
                        for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                            if spec.item_type == df.item_type.WEAPON and #spec.assigned > 0
                                    and spec.item_subtype ~= xbow then
                                given = given + 1
                            end
                        end
                    end)
                end
            end
        end
    end
    return n, given
end

-- (0.104.80) Where the handed-out weapons go: Enxah, 25 Oct 17:52-17:57,
-- assign_weapons gave 9-10 axes a call to squads 26 and 46 (both off duty)
-- and the next call found the same places empty again (one melee entry of
-- 25 still given). Each weapon given is booked here (the module stays
-- loaded between calls); the next call says what became of each: still on
-- the entry, off the entry but on the place, off the place, back on DF's
-- unassigned list, the soldier gone from the place, the item gone; and the
-- squad's routine then and now.
AW_LEDGER = AW_LEDGER or {}

local function list_has(v, id)
    for _, x in ipairs(v or {}) do if x == id then return true end end
    return false
end

local function routine_of(sq, names)
    local ok, idx = pcall(function() return sq.cur_routine_idx end)
    if not ok or type(idx) ~= 'number' then return '?' end
    return tostring(names[idx + 1] or idx)
end

local function safe_routines()
    local ok, n = pcall(M.routine_names)
    return ok and n or {}
end

local function check_ledger(eq)
    local names = safe_routines()
    local out = {booked = 0, kept = 0, why = {}, samples = {}}
    local now = df.global.cur_year_tick or 0
    for id, b in pairs(AW_LEDGER) do
        out.booked = out.booked + 1
        local sq = df.squad.find(b.sid)
        local pos = sq and sq.positions[b.pi]
        local it
        if not pcall(function() it = df.item.find(id) end) then it = {flags = {}} end
        local on_spec, on_pos = false, false
        if pos then
            on_pos = list_has(pos.equipment.assigned_items, id)
            pcall(function()
                for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                    if list_has(spec.assigned, id) then on_spec = true end
                end
            end)
        end
        local why
        if not it then why = 'item gone'
        elseif not pos then why = 'place gone'
        elseif pos.occupant ~= b.hf then why = 'soldier left the place'
        elseif on_spec and on_pos then why = nil
        elseif on_pos then why = 'off the entry, still on the place'
        elseif on_spec then why = 'on the entry, off the place'
        else why = 'off the entry and the place' end
        if why then
            local where = it and ((it.flags.in_inventory and 'carried') or (it.flags.on_ground and 'on the ground')
                or 'stored') or '-'
            local lists = (list_has(eq.items_unassigned.WEAPON, id) and 'unassigned')
                or (list_has(eq.items_assigned.WEAPON, id) and 'assigned') or 'no list'
            local key = why .. '; ' .. lists .. '; routine then ' .. b.routine .. ', now '
                .. (sq and routine_of(sq, names) or '-')
            out.why[key] = (out.why[key] or 0) + 1
            if #out.samples < 4 then
                table.insert(out.samples, ('#%d squad %d place %d: %s (%s, %d ticks)'):format(
                    id, b.sid, b.pi, why, where, (now - b.tick) % 403200))
            end
            AW_LEDGER[id] = nil
        else
            out.kept = out.kept + 1
            if (now - b.tick) % 403200 > 28 * 1200 then AW_LEDGER[id] = nil end   -- a month kept: stop watching
        end
    end
    return out
end

-- (0.104.80) Every field of a weapon entry, one level deep (vectors by
-- length): DF fills the crossbow entries and takes the AI's axes back, so a
-- melee entry is set beside a ranged one to find what DF reads differently.
local function dump_fields(obj, depth)
    local out = {}
    local ok = pcall(function()
        for k, v in pairs(obj) do
            local tv = type(v)
            if tv == 'userdata' then
                local okl, n = pcall(function() return #v end)
                if okl and type(n) == 'number' and (depth or 0) >= 1 then out[tostring(k)] = '#' .. n
                elseif (depth or 0) < 1 then out[tostring(k)] = dump_fields(v, (depth or 0) + 1)
                else out[tostring(k)] = tostring(v) end
            else
                out[tostring(k)] = tostring(v)
            end
        end
    end)
    if not ok then out._error = 'not readable' end
    return out
end

local function spec_dump()
    local fort = U.fort_entity()
    if not fort then return nil end
    local xbow
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.weapons) do
            if def.id == 'ITEM_WEAPON_CROSSBOW' then xbow = def.subtype ~= nil and def.subtype or i end
        end
    end)
    local out = {}
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for pi, pos in ipairs(sq and sq.positions or {}) do
            pcall(function()
                for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                    local kind = spec.item_subtype == xbow and 'ranged' or 'melee'
                    if not out[kind] then
                        out[kind] = {squad = sid, place = pi, assigned = #spec.assigned, spec = dump_fields(spec)}
                    end
                end
            end)
            if out.melee and out.ranged then return out end
        end
    end
    return out
end

-- (0.104.80) Weapon entries asking for a colour: set by set_uniform_weapon
-- before 0.104.80 (colour 0, a dye colour, not "any": Enxah, every melee
-- entry; the crossbow entries, from DF's own templates, had -1 and were
-- filled). Put to any colour; DF then hands out the weapons itself.
function fix_weapon_colours(dry_run)
    local fort = U.fort_entity()
    if not fort then return 0 end
    local n = 0
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for _, pos in ipairs(sq and sq.positions or {}) do
            pcall(function()
                for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                    if spec.item_type == df.item_type.WEAPON and spec.color ~= -1 then
                        if not dry_run then spec.color = -1 end
                        n = n + 1
                    end
                end
            end)
        end
    end
    if n > 0 and not dry_run then
        pcall(function() df.global.plotinfo.equipment.update.weapon = true end)
    end
    return n
end

-- (0.105.0) Does a weapon fit a uniform's weapon entry? ok, or false and why
-- ('kind', 'melee', 'ranged', 'pick', 'material'). "Any weapon" (subtype -1)
-- reads the entry's individual choice: melee or ranged (a crossbow has ranged
-- ammo in its definition); a miner's pick only when the entry names picks.
-- The material: a named one (mattype/matindex), or a class: the metal classes
-- want metal, Wood wants wood. Unread fields pass (the game then decides).
-- (WeaponRanged is "metal.ranged": a crossbow entry asking for it takes no
-- wooden crossbow; DF's own crossbow templates ask for any material, -1)
local METAL_CLASSES = {WeaponMelee = true, WeaponRanged = true, Pick = true, Armor = true}
function weapon_def(it)
    local ok, def = pcall(function() return it.subtype end)
    if ok and def then return def end
    local ok2, d2 = pcall(function() return dfhack.items.getSubtypeDef(df.item_type.WEAPON, it:getSubtype()) end)
    return ok2 and d2 or nil
end

function weapon_is_ranged(def)
    local ok, ammo = pcall(function() return def.ranged_ammo end)
    return ok and type(ammo) == 'string' and ammo ~= ''
end

function weapon_fits(spec, it)
    local sub = it:getSubtype()
    if spec.item_subtype ~= -1 then
        if sub ~= spec.item_subtype then return false, 'kind' end
    else
        local def = weapon_def(it)
        local id = def and def.id
        if id == 'ITEM_WEAPON_PICK' then return false, 'pick' end
        -- (0.105.0 review) a training weapon is never "any"
        if type(id) == 'string' and id:find('_TRAINING', 1, true) then return false, 'kind' end
        local okc, choice = pcall(function() return spec.indiv_choice end)
        if okc and choice and def then
            local r = weapon_is_ranged(def)
            if choice.ranged and not choice.melee and not r then return false, 'ranged' end
            if choice.melee and not choice.ranged and r then return false, 'melee' end
        end
    end
    local okm, mt, mi = pcall(function() return spec.mattype, spec.matindex end)
    if okm and mt ~= nil and mt ~= -1 then
        if it:getMaterial() ~= mt or (mi ~= -1 and it:getMaterialIndex() ~= mi) then return false, 'material' end
    end
    local okk, cls = pcall(function() return df.entity_material_category[spec.material_class] end)
    if okk and cls then
        if METAL_CLASSES[cls] and metal_token(it) == nil then return false, 'material' end
        if cls == 'Wood' then
            local okw, wood = pcall(function()
                local m = dfhack.matinfo.decode(it)
                return m and m.material and m.material.flags.WOOD
            end)
            if okw and wood == false then return false, 'material' end
        end
    end
    return true
end

function assign_weapons(dry_run, limit)
    local eq = equipment_lists()
    if not eq then return {ok = false, rejected = true, error = "this DF keeps its equipment lists elsewhere"} end
    local fort = U.fort_entity()
    if not fort then return {ok = false, rejected = true, error = 'no fort'} end
    limit = limit or 10
    local claimed, work = claimed_items(), eq_ids(eq, 'work_weapons')
    local una = eq_ids(eq, 'items_unassigned', 'WEAPON')
    -- free weapons DF could hand out: on its unassigned list, not forbidden,
    -- not on a job, nobody's tool or claim
    local pool = {}
    for _, it in ipairs(gear_items('WEAPON')) do
        local f = it.flags
        if una[it.id] and not claimed[it.id] and free_gear(it, work) and not f.forbid and not f.in_job
                and not f.dump and not f.melt then
            local x, y, z = dfhack.items.getPosition(it)
            if x then table.insert(pool, {it = it, sub = it:getSubtype(), pos = xyz2pos(x, y, z)}) end
        end
    end
    local ledger = (not dry_run) and check_ledger(eq) or nil
    local colours = fix_weapon_colours(dry_run)
    local names = safe_routines()
    local done, out = 0, {}
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for pi, pos in ipairs(sq and sq.positions or {}) do
            if done >= limit then break end
            if pos.occupant ~= -1 then
                local hf = df.historical_figure.find(pos.occupant)
                local u = hf and df.unit.find(hf.unit_id)
                local ux, uy, uz
                if u then ux, uy, uz = dfhack.units.getPosition(u) end
                for _, spec in ipairs(u and ux and weapon_specs_empty(pos) or {}) do
                    if done >= limit then break end
                    local upos, best, bd = xyz2pos(ux, uy, uz), nil, nil
                    for i, c in ipairs(pool) do
                        -- (0.105.0) the entry's own ask: its kind, melee or ranged
                        -- for "any", never a miner's pick for "any", its material
                        if weapon_fits(spec, c.it) then
                            local d = math.abs(c.pos.x - ux) + math.abs(c.pos.y - uy) + 3 * math.abs(c.pos.z - uz)
                            if (not bd or d < bd) and dfhack.maps.canWalkBetween(upos, c.pos) then best, bd = i, d end
                        end
                    end
                    if best then
                        local c = table.remove(pool, best)
                        if not dry_run then
                            spec.assigned:insert('#', c.it.id)
                            vec_add(pos.equipment.assigned_items, c.it.id)
                            vec_remove(eq.items_unassigned.WEAPON, c.it.id)
                            vec_add(eq.items_assigned.WEAPON, c.it.id)
                            AW_LEDGER[c.it.id] = {sid = sid, pi = pi, hf = pos.occupant,
                                                  tick = df.global.cur_year_tick or 0, routine = routine_of(sq, names)}
                        end
                        done = done + 1
                        local okd, d = pcall(function()
                            return (dfhack.df2utf or tostring)(dfhack.items.getDescription(c.it, 0, true))
                        end)
                        table.insert(out, ('squad %d: %s'):format(sid, okd and d or ('#' .. c.it.id)))
                    end
                end
            end
        end
    end
    if dry_run then return {ok = true, dry_run = true, would_assign = done, items = out} end
    local specs
    if ledger and ledger.booked > ledger.kept then specs = spec_dump() end
    if done == 0 and colours == 0 then
        -- (0.104.80) nothing to hand out is a refusal: the brain backs off
        -- (asked every cycle after DF took over the arming, 18:24)
        return {ok = false, rejected = true, left = #pool, ledger = ledger, specs = specs,
                error = 'no free weapon fits the empty weapon places'}
    end
    return {ok = true, assigned = done, items = out, left = #pool, ledger = ledger, specs = specs,
            colours_fixed = colours > 0 and colours or nil}
end

-- (lua/ai-util.lua's list) spare gear may be on its way somewhere in a job,
-- and gear in a bin counts (who holds it is looked at here); a crossbow in a
-- rack or a job counts as spare too; bars in a bin count
local SPARE_OK = {in_job = true, held = true}
local CROSSBOW_OK = {in_job = true, in_building = true, held = true}
local HELD_OK = {held = true}

local gear_report_body
function gear_report()
    -- (0.105.33 review) the claim sets built once for the whole report
    local outer = CLAIM_MEMO == nil
    if outer then CLAIM_MEMO = {} end
    local ok, out = pcall(gear_report_body)
    if outer then CLAIM_MEMO = nil end
    if not ok then error(out, 0) end
    return out
end

gear_report_body = function()        -- (the local declared above gear_report)
    -- armed/armored/helmed count only soldiers ON DUTY: off duty they put
    -- their weapons (and sometimes armour) away, which isn't a shortage
    local out = {soldiers = 0, on_duty = 0, armed = 0, armored = 0, helmed = 0, squads_with_uniform = 0,
                 legged = 0, gloved = 0, booted = 0, shielded = 0, ranged_armed = 0,
                 spare_crossbows = 0, bolts = 0, crossbows_total = 0,   -- (0.105.46, I3) crossbows_total
                 squads = 0, spare = {}, bars = {}, forges = 0}
    local routines = M.routine_names()
    local fort = U.fort_entity()
    if fort then
        for _, sid in ipairs(fort.squads) do
            local sq = df.squad.find(sid)
            if sq then
                out.squads = out.squads + 1
                local okr, idx = pcall(function() return sq.cur_routine_idx end)
                local routine = okr and routines[idx + 1] or ''
                local on_duty = not tostring(routine):lower():find('off duty', 1, true)
                local uniform = false
                for _, pos in ipairs(sq.positions) do
                    if M.uniform_set(pos) then uniform = true end
                    if pos.occupant ~= -1 then
                        local hf = df.historical_figure.find(pos.occupant)
                        local u = hf and df.unit.find(hf.unit_id)
                        if u then
                            out.soldiers = out.soldiers + 1
                        end
                        if u and on_duty then
                            out.on_duty = out.on_duty + 1
                            local w, a, h, p, g, b, sh = false, false, false, false, false, false, false
                            for _, inv in ipairs(u.inventory) do
                                local t, how = inv.item:getType(), inv_mode_name(inv.mode)
                                if t == df.item_type.WEAPON and how == 'Weapon' then w = true end
                                if t == df.item_type.ARMOR and how == 'Worn' then a = true end
                                if t == df.item_type.HELM and how == 'Worn' then h = true end
                                -- the rest of a kit, metal only (cloth and leather are clothes)
                                local metal = metal_token(inv.item) ~= nil
                                if metal and how == 'Worn' then
                                    if t == df.item_type.PANTS then p = true end
                                    if t == df.item_type.GLOVES then g = true end
                                    if t == df.item_type.SHOES then b = true end
                                end
                                if t == df.item_type.SHIELD and how ~= 'Hauled' then sh = true end
                            end
                            for _, inv in ipairs(u.inventory) do
                                if inv.item:getType() == df.item_type.WEAPON and inv_mode_name(inv.mode) == 'Weapon' then
                                    local okc, id = pcall(function() return inv.item.subtype.id end)
                                    if okc and id == 'ITEM_WEAPON_CROSSBOW' then out.ranged_armed = out.ranged_armed + 1 end
                                end
                            end
                            if w then out.armed = out.armed + 1 end
                            if a then out.armored = out.armored + 1 end
                            if h then out.helmed = out.helmed + 1 end
                            if p then out.legged = out.legged + 1 end
                            if g then out.gloved = out.gloved + 1 end
                            if b then out.booted = out.booted + 1 end
                            if sh then out.shielded = out.shielded + 1 end
                        end
                    end
                end
                if uniform then out.squads_with_uniform = out.squads_with_uniform + 1 end
            end
        end
    end
    local other = df.global.world.items.other
    local grade = {}
    for _, m in ipairs(GEAR_METALS) do grade[m] = true end
    -- (0.104.58) spare is what DF can hand out: on its unassigned list, no
    -- worker's tool; stray gear (off both lists, or assigned to no one) is
    -- counted apart for free_stray_gear
    local okst, st = pcall(stray_report)
    st = okst and st or nil
    if st then out.stray = {n = st.n, orphan = st.orphan, unlisted = st.unlisted} end
    -- (0.104.60) soldiers' places whose weapon entry DF left empty
    pcall(function() out.weapon_gaps, out.melee_given = weapon_gaps() end)
    for key, list_name in pairs(GEAR_LISTS) do
        local n = 0
        local una = st and st.unassigned[list_name]
        for _, it in ipairs(other[df.items_other_id[list_name]]) do
            local f = it.flags
            local listed = (not st) or (una[it.id] and not st.work[it.id])
            -- (0.104.55) in a bin counts: only a unit's inventory doesn't (Enxah:
            -- 120 helms in bins counted as none spare, so 114 gauntlet and 96
            -- boot orders went in while 3 of 26 soldiers were armed)
            local held = false
            if f.in_inventory then
                local okh, u = pcall(dfhack.items.getHolderUnit, it)
                held = (not okh) or u ~= nil
                if not held then
                    local okc, c = pcall(dfhack.items.getContainer, it)
                    held = (not okc) or c == nil
                end
            end
            if listed and not held and U.item_free(it, SPARE_OK) then
                local m = metal_token(it)
                if m and grade[m] then
                    n = n + 1
                    if key == 'weapons' then
                        -- by kind (a uniform asking for battle axes takes only those)
                        local okd, id = pcall(function() return it.subtype.id end)
                        if okd and id then
                            out.spare_weapons = out.spare_weapons or {}
                            out.spare_weapons[id] = (out.spare_weapons[id] or 0) + 1
                        end
                    end
                end
            end
        end
        out.spare[key] = n
    end
    -- crossbows of any material lying free, and bolts anywhere but a trader's
    for _, it in ipairs(gear_items('WEAPON')) do
        local f = it.flags
        local okc, id = pcall(function() return it.subtype.id end)
        if okc and id == 'ITEM_WEAPON_CROSSBOW' and not f.in_inventory and U.item_free(it, CROSSBOW_OK) then
            out.spare_crossbows = out.spare_crossbows + 1
        end
        -- (0.105.46, I3) every crossbow the fort has: in a bin, in a soldier's
        -- hands or put away off duty (370 crossbow orders in a day's run: the
        -- spare count skips bins and owned ones, and ranged_armed counts the
        -- squads on duty only, so a squad off duty read as unarmed)
        if okc and id == 'ITEM_WEAPON_CROSSBOW' then
            pcall(function()
                if f.trader or f.hostile or f.removed or f.garbage_collect or f.forbid or f.dump then return end
                if f.in_inventory then
                    local u = dfhack.items.getHolderUnit(it)
                    if u and not dfhack.units.isCitizen(u) then return end
                end
                out.crossbows_total = (out.crossbows_total or 0) + 1
            end)
        end
    end
    pcall(function()
        for _, it in ipairs(other.AMMO) do
            local f = it.flags
            local okc, id = pcall(function() return it.subtype.id end)
            if okc and id == 'ITEM_AMMO_BOLTS' and not (f.forbid or f.garbage_collect or f.trader or f.removed
                    or f.dump or f.hostile) then
                out.bolts = out.bolts + it:getStackSize()
            end
        end
    end)
    for _, it in ipairs(other.BAR) do
        if U.item_free(it, HELD_OK) then
            local m = metal_token(it)
            if m and grade[m] then out.bars[m] = (out.bars[m] or 0) + it:getStackSize() end
            -- every metal (furniture can be made of silver, gold...)
            if m then
                out.all_bars = out.all_bars or {}
                out.all_bars[m] = (out.all_bars[m] or 0) + it:getStackSize()
            end
            -- pig iron: the step between iron and steel (not gear itself)
            if m == 'PIG_IRON' then out.pig_iron = (out.pig_iron or 0) + it:getStackSize() end
        end
    end
    -- (0.105.40 M7) each metal's value in this game's raws, the bars held and
    -- the alloys (the brain alloys precious metals only where the alloy is worth more)
    pcall(function()
        local want = {}
        for m in pairs(out.all_bars or {}) do want[m] = true end
        for _, m in ipairs(ALLOY_METALS) do want[m] = true end
        for m in pairs(want) do
            local mi = dfhack.matinfo.find('INORGANIC:' .. m)
            if mi and mi.material then
                out.bar_values = out.bar_values or {}
                out.bar_values[m] = mi.material.material_value
            end
        end
    end)
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Workshop and (b.type == df.workshop_type.MetalsmithsForge
                or b.type == df.workshop_type.MagmaForge) then
            out.forges = out.forges + 1
        end
    end
    -- (0.104.138) how many empty weapon places the hand-out could really fill
    -- (its own dry run): the brain counted 354 spare weapons of every kind
    -- while each empty place asked for a battle axe and none was free
    -- (assign_weapons refused 71 times a day)
    if (out.weapon_gaps or 0) > 0 then
        pcall(function()
            local r = assign_weapons(true, 50)
            out.weapon_gaps_fillable = (r and r.would_assign) or 0
        end)
    end
    -- (0.105.0) why each empty entry stays empty, the shields, the quivers
    pcall(army_gear, out)
    return out
end

-- (r8) The rest of the gear lives in parts beside this file
--
-- ai-military-gear-why    why a weapon or shield entry stays empty (gaps_why)
-- ai-military-gear-ammo   quivers, flasks, the squads' ammunition, the bolts
-- ai-military-gear-fixes  the fixes for what the why report finds, spares
--                         unforbidden, shield entries (fix_gear_gaps)
-- ai-military-gear-kit    every armour slot (kit_report, assign_kit), army_gear
--
-- Each is loaded into THIS environment (as ai-gates loads its parts), so
-- every name stays reqscript('ai-military-gear').<name> (and ai-military's,
-- through its forwarders) and a test's swap (G.fn = ...) reaches every part.
-- This file's locals the parts use go to them in GEAR_PART_LOCALS (each takes
-- them back as locals of its own): the same functions and tables, none
-- reassigned after this line. DFHack reloads a module when its own file
-- changes: a change to a part alone is picked up once ai-military-gear.lua is
-- touched too, or the game restarts.
GEAR_PART_LOCALS = {U = U, M = M, fort_squads = fort_squads, memo = memo, eq_ids = eq_ids, gear_items = gear_items, claimed_items = claimed_items, free_gear = free_gear, vec_remove = vec_remove, vec_add = vec_add}

PARTS = {'why', 'ammo', 'fixes', 'kit'}
-- each part marks the version it came with (the bridge's `version` lists one
-- that differs from BRIDGE_VERSION); started afresh at each load, so a part
-- that failed to load shows as unmarked
PART_VERSIONS = {['ai-military-gear'] = '0.105.82'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-military-gear-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-military-gear: ' .. name .. '.lua is missing (it goes beside ai-military-gear.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
