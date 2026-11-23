-- ai-military-gear-kit: every armour slot: why each empty entry stays empty, the kit report, the
-- armour handed out (kit_report, assign_kit), and army_gear (the why, the
-- shields, the kit, the quivers, flasks and bolts for gear_report).
--
-- (r8) A part of ai-military-gear, not a script of its own: ai-military-gear.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-military-gear').name (and ai-military's, through its forwarders)
-- and a name swapped there reaches this file.

if not GEAR_PART_LOCALS then qerror('ai-military-gear-kit is a part of ai-military-gear; run ai-military-gear') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-gear-kit'] = '0.105.89'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, fort_squads, eq_ids, gear_items, claimed_items, free_gear, vec_remove, vec_add, item_fits = GEAR_PART_LOCALS.U, GEAR_PART_LOCALS.fort_squads, GEAR_PART_LOCALS.eq_ids, GEAR_PART_LOCALS.gear_items, GEAR_PART_LOCALS.claimed_items, GEAR_PART_LOCALS.free_gear, GEAR_PART_LOCALS.vec_remove, GEAR_PART_LOCALS.vec_add, GEAR_PART_LOCALS.item_fits   -- (r8) handed on by the files before

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
                    local una = eq and eq_ids(eq, 'items_unassigned', 'GLOVES') or {}
                    pcall(function()
                        for _, it in ipairs(gear_items('GLOVES')) do
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
    local claimed, work = claimed_items(), eq_ids(eq, 'work_weapons')
    local done, out, by = 0, {}, {}
    for _, slot in ipairs(KIT_GIVE) do
        local cat_name, list_name, flag, need = slot[1], slot[2], slot[3], slot[4]
        local cat = df.uniform_category[cat_name]
        local una = eq_ids(eq, 'items_unassigned', list_name)
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
    local okb, nb = pcall(bolts_free_count)      -- (r2h4) the bolts assign_bolts can hand out
    if okb and type(nb) == 'number' then out.bolts_free = nb end
end
