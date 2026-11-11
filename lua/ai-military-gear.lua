-- The fort's soldiers' gear (13c: split out of lua/ai-military.lua, which
-- keeps every name here reachable as reqscript('ai-military').<name>): the
-- gear report (who carries a weapon, wears armour and a helm; spare metal
-- gear; weapon-grade bars), gear DF keeps assigned to no one put back,
-- weapons, shields, quivers, bolts and armour given to the soldiers' empty
-- entries, why an entry stays empty, and the kit report.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules
local M = reqscript('ai-military')  -- the squads: fort_squad, ai_uniforms, routine_names...
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-gear'] = '0.105.33'   -- (0.105.26) bumped with BRIDGE_VERSION

-- Gear: how many soldiers carry a weapon, wear body armour and a helm; how
-- many squads have a uniform (without one, armour made isn't handed out);
-- spare metal gear; and weapon-grade metal bars by kind.
GEAR_METALS = {'STEEL', 'IRON', 'BRONZE', 'BISMUTH_BRONZE', 'COPPER'}   -- best first
local GEAR_LISTS = {weapons = 'WEAPON', body = 'ARMOR', helms = 'HELM', pants = 'PANTS',
                    gloves = 'GLOVES', boots = 'SHOES', shields = 'SHIELD'}

function metal_token(item)
    local mi = dfhack.matinfo.decode(item)
    if not mi or not mi.inorganic or not mi.material.flags.IS_METAL then return nil end
    return mi.inorganic.id
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
local function fort_squads()
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
    local claimed, work = claimed_items(), id_set(eq.work_weapons)
    local out = {orphan = {}, unlisted = {}, n = 0, unassigned = {}, work = work}
    for _, kind in ipairs(STRAY_KINDS) do
        local asg, una = id_set(eq.items_assigned[kind]), id_set(eq.items_unassigned[kind])
        out.unassigned[kind] = una
        -- (0.104.59) new items wait on the "unmanifested" list before DF files
        -- them: listed, not stray (a new axe from the forge counted as lost)
        local okm, unm = pcall(function() return id_set(eq.items_unmanifested[kind]) end)
        unm = okm and unm or {}
        local o, u = 0, 0
        for _, it in ipairs(df.global.world.items.other[kind]) do
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
    local claimed, work = claimed_items(), id_set(eq.work_weapons)
    local una = id_set(eq.items_unassigned.WEAPON)
    -- free weapons DF could hand out: on its unassigned list, not forbidden,
    -- not on a job, nobody's tool or claim
    local pool = {}
    for _, it in ipairs(df.global.world.items.other.WEAPON) do
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
                 spare_crossbows = 0, bolts = 0,
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
    for _, it in ipairs(other.WEAPON) do
        local f = it.flags
        local okc, id = pcall(function() return it.subtype.id end)
        if okc and id == 'ITEM_WEAPON_CROSSBOW' and not f.in_inventory and U.item_free(it, CROSSBOW_OK) then
            out.spare_crossbows = out.spare_crossbows + 1
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
    local ctx = {entry = entry, place = place, work = id_set(eq.work_weapons), una = id_set(eq.items_unassigned[list_name])}
    local items = df.global.world.items.other[list_name]
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
    local una = eq and id_set(eq.items_unassigned.QUIVER) or {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.QUIVER) do
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
    local una = eq and id_set(eq.items_unassigned.FLASK) or {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.FLASK) do
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

-- A crossbow squad's bolts: its ammunition entries, the bolts wanted and
-- those DF has assigned. nil for a squad that doesn't shoot.
function squad_ammo(sq)
    local shoots = false
    for _, pos in ipairs(sq.positions) do
        if ranged_place(pos) then shoots = true break end
    end
    if not shoots then return nil end
    local out = {specs = 0, wanted = 0, assigned = 0, items = 0}
    pcall(function()
        for _, a in ipairs(sq.ammo.ammunition) do
            out.specs = out.specs + 1
            out.wanted = out.wanted + (a.amount or 0)
            out.assigned = out.assigned + #a.assigned
        end
        out.items = #sq.ammo.ammo_items
    end)
    return out
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

-- (0.105.8) Every armour slot, as for weapons and shields: why each empty
-- entry stays empty, and how a pair is kept on an entry. E (2 Nov): 10 spare
-- metal gauntlets and boots, 1 soldier gloved; "untangle the uniforms" twice
-- changed nothing, and nothing else looked at armour. Read only; built at
-- most once a game day (the military section is the report's slowest).
KIT_SLOTS = {{'body', 'body', 'ARMOR'}, {'helms', 'head', 'HELM'}, {'pants', 'pants', 'PANTS'},
             {'gloves', 'gloves', 'GLOVES'}, {'boots', 'shoes', 'SHOES'}}
KIT_CACHE = KIT_CACHE or {}

local function glove_side(it)
    local r, l
    pcall(function() r, l = it.handedness[0], it.handedness[1] end)
    if r == nil and l == nil then return '?' end
    local rv = (r == true or (type(r) == 'number' and r ~= 0))
    local lv = (l == true or (type(l) == 'number' and l ~= 0))
    return (rv and lv) and 'both' or rv and 'right' or lv and 'left' or 'none'
end

function kit_report()
    local now = df.global.cur_year_tick or 0
    local year = df.global.cur_year or 0
    if KIT_CACHE.out and KIT_CACHE.year == year and now - (KIT_CACHE.tick or -1e9) >= 0
            and now - KIT_CACHE.tick < 1200 then
        return KIT_CACHE.out
    end
    local out = {}
    for _, slot in ipairs(KIT_SLOTS) do
        local key, cat, list = slot[1], slot[2], slot[3]
        local ok, g = pcall(gaps_why, cat, list)
        if ok and g then
            local r = {entries = g.entries, given = g.given, no_entry = g.no_entry,
                       why = next(g.why) and g.why or nil}
            if #g.detail > 0 then r.detail = {table.unpack(g.detail, 1, math.min(3, #g.detail))} end
            -- how many items a given entry holds (a pair: 1 or 2?), and the
            -- sides of free gloves
            if key == 'gloves' or key == 'boots' then
                local hist = {}
                pcall(function()
                    local c = df.uniform_category[cat]
                    for _, sq in ipairs(fort_squads()) do
                        for _, pos in ipairs(sq.positions) do
                            if pos.occupant ~= -1 then
                                for _, spec in ipairs(pos.equipment.uniform[c]) do
                                    local n = tostring(#spec.assigned)
                                    hist[n] = (hist[n] or 0) + 1
                                end
                            end
                        end
                    end
                end)
                r.per_entry = next(hist) and hist or nil
                if key == 'gloves' then
                    local sides, worn = {}, {}
                    local eq = equipment_lists()
                    local una = eq and id_set(eq.items_unassigned.GLOVES) or {}
                    pcall(function()
                        for _, it in ipairs(df.global.world.items.other.GLOVES) do
                            if metal_token(it) then
                                local sd = glove_side(it)
                                if una[it.id] and not it.flags.in_inventory then
                                    sides[sd] = (sides[sd] or 0) + 1
                                elseif it.flags.in_inventory then
                                    worn[sd] = (worn[sd] or 0) + 1
                                end
                            end
                        end
                    end)
                    r.free_sides = next(sides) and sides or nil
                    r.carried_sides = next(worn) and worn or nil
                end
            end
            out[key] = r
        else
            out[key] = {error = tostring(g):sub(1, 120)}
        end
    end
    local okd, dr = pcall(assign_kit, true, 50)
    out.fillable = okd and type(dr) == 'table' and (dr.would_assign or 0) or nil
    KIT_CACHE = {out = out, tick = now, year = year}
    return out
end

-- (0.105.8) The armour DF won't hand out, put on the soldiers' entries as
-- assign_weapons does for weapons: each empty body, helm, greaves, shield,
-- gloves or boots entry of a soldier on the map gets the nearest free item
-- that fits it (its kind and material, on DF's unassigned list, nobody's,
-- not forbidden, in a job or to melt, reachable). A pair entry takes two, as
-- DF fills one (the six forts: every given gloves or boots entry holds 2):
-- gloves one left and one right; nothing is given until the pair is found.
-- E (2 Nov): 7 of 9 gloves entries empty, 5 left and 5 right free.
KIT_GIVE = {{'body', 'ARMOR', 'armor', 1}, {'head', 'HELM', 'helm', 1}, {'pants', 'PANTS', 'pants', 1},
            {'shield', 'SHIELD', 'shield', 1}, {'gloves', 'GLOVES', 'gloves', 2}, {'shoes', 'SHOES', 'shoes', 2}}

function assign_kit(dry_run, limit)
    local eq = equipment_lists()
    if not eq then return {ok = false, rejected = true, error = "this DF keeps its equipment lists elsewhere"} end
    local fort = U.fort_entity()
    if not fort then return {ok = false, rejected = true, error = 'no fort'} end
    limit = limit or 10
    local claimed, work = claimed_items(), id_set(eq.work_weapons)
    local done, out, by = 0, {}, {}
    for _, slot in ipairs(KIT_GIVE) do
        local cat_name, list_name, flag, need = slot[1], slot[2], slot[3], slot[4]
        local cat = df.uniform_category[cat_name]
        local una = id_set(eq.items_unassigned[list_name])
        local pool = {}
        for _, it in ipairs(df.global.world.items.other[list_name] or {}) do
            local f = it.flags
            if una[it.id] and not claimed[it.id] and free_gear(it, work) and not f.forbid and not f.in_job
                    and not f.dump and not f.melt then
                local x, y, z = dfhack.items.getPosition(it)
                if x then table.insert(pool, {it = it, pos = xyz2pos(x, y, z),
                                              side = list_name == 'GLOVES' and glove_side(it) or nil}) end
            end
        end
        local given = 0
        for _, sid in ipairs(fort.squads) do
            local sq = df.squad.find(sid)
            for _, pos in ipairs(sq and sq.positions or {}) do
                if done >= limit or #pool < need then break end
                if pos.occupant ~= -1 then
                    local hf = df.historical_figure.find(pos.occupant)
                    local u = hf and df.unit.find(hf.unit_id)
                    local ux, uy, uz
                    if u then ux, uy, uz = dfhack.units.getPosition(u) end
                    local specs = {}
                    pcall(function() for _, sp in ipairs(pos.equipment.uniform[cat]) do table.insert(specs, sp) end end)
                    for _, spec in ipairs(ux and specs or {}) do
                        if done >= limit or #pool < need then break end
                        if #spec.assigned == 0 then
                            local upos = xyz2pos(ux, uy, uz)
                            -- the nearest fitting items, one per side for gloves
                            local picks, took = {}, {}
                            for k = 1, need do
                                local best, bd
                                for i, c in ipairs(pool) do
                                    local side_ok = true
                                    if c.side and need == 2 and c.side ~= '?' then
                                        for _, j in ipairs(picks) do
                                            if pool[j].side == c.side then side_ok = false end
                                        end
                                    end
                                    if not took[i] and side_ok and item_fits(spec, c.it, false) then
                                        local d = math.abs(c.pos.x - ux) + math.abs(c.pos.y - uy) + 3 * math.abs(c.pos.z - uz)
                                        if (not bd or d < bd) and dfhack.maps.canWalkBetween(upos, c.pos) then
                                            best, bd = i, d
                                        end
                                    end
                                end
                                if not best then break end
                                took[best] = true
                                table.insert(picks, best)
                            end
                            if #picks == need then
                                table.sort(picks, function(a, b) return a > b end)
                                for _, i in ipairs(picks) do
                                    local c = table.remove(pool, i)
                                    if not dry_run then
                                        spec.assigned:insert('#', c.it.id)
                                        vec_add(pos.equipment.assigned_items, c.it.id)
                                        vec_remove(eq.items_unassigned[list_name], c.it.id)
                                        vec_add(eq.items_assigned[list_name], c.it.id)
                                    end
                                end
                                done, given = done + 1, given + 1
                                table.insert(out, ('squad %d: %s'):format(sid, flag))
                            end
                        end
                    end
                end
            end
        end
        if given > 0 then
            by[flag] = given
            if not dry_run then pcall(function() df.global.plotinfo.equipment.update[flag] = true end) end
        end
    end
    if not dry_run and done > 0 then KIT_CACHE = {} end
    if dry_run then return {ok = true, dry_run = true, would_assign = done, by = by} end
    if done == 0 then
        return {ok = false, rejected = true, error = 'no free armour fits the empty armour places'}
    end
    return {ok = true, assigned = done, by = by, items = out}
end

-- For gear_report: the why of the gaps, the shields, the quivers.
function army_gear(out)
    local okw, w = pcall(gaps_why, 'weapon', 'WEAPON')
    if okw and w then
        if next(w.why) then
            out.weapon_gaps_why, out.weapon_gaps_detail = w.why, w.detail
            out.weapon_gaps_ranged = w.ranged
            if next(w.wanted) then out.weapon_gaps_wanted = w.wanted end
        end
    else
        out.weapon_gaps_why = {error = tostring(w):sub(1, 120)}
    end
    local oks, sh = pcall(gaps_why, 'shield', 'SHIELD')
    if oks and sh then
        out.shields = {places = sh.places, no_entry = sh.no_entry, entries = sh.entries, given = sh.given,
                       no_entry_squads = next(sh.no_entry_squads) and sh.no_entry_squads or nil,   -- (0.105.0 review)
                       why = next(sh.why) and sh.why or nil, detail = #sh.detail > 0 and sh.detail or nil}
    end
    local okk, kit = pcall(kit_report)
    out.kit = okk and kit or {error = tostring(kit):sub(1, 120)}
    local okq, q = pcall(quiver_report)
    if okq and q then
        for k, v in pairs(q) do out[k] = v end
    end
    local okf, fl = pcall(flask_report)          -- (0.105.26)
    if okf and fl then
        for k, v in pairs(fl) do out[k] = v end
    end
end
