-- (0.105.47) The herd: what the Husbandry slider keeps, breeds, tames and
-- takes from the fort's animals.
--
-- Why (the 14 Nov scorecard): the Garden fort (Husbandry +80) won no
-- Husbandry line. Tame animals A 58 (War-hold), B 19, C 45, D 12, E 14,
-- F 30 (Garden); pastures A 9, C 8, F 7. Husbandry did only three things:
-- nestboxes on at 0 or more, DFHack's autobutcher on at 0 or less once the
-- herd was big, and bigger new pastures. Nothing kept a breeding pair, tamed
-- a caught animal, or sheared and milked by what the animals had grown, and
-- war training ran in every fort alike (DFHack's autobutcher spares war and
-- hunting animals, so the forts that trained most kept most).
--
-- What this module does (each behind pcall: fields this DF may name otherwise):
--   report()                 the herd by kind: adults by sex, young, the
--                            AI's breeders, the protected (pets, war and
--                            hunting animals, named), the marked for
--                            slaughter, the caged; grazers' grass need (the
--                            AI's pastures and the loose); wool grown now
--                            (a shearable layer's bp_modifiers at its
--                            shear length), milk ready now (no MilkCounter);
--                            caged wild animals that can be tamed; trainers;
--                            the autobutcher targets the AI set
--   keep_breeders(f)         per kind of grazer or egg layer with a pair:
--                            one adult male and up to f adult females kept
--                            from the butcher on the AI's kept list
--                            (KEPT_KEY; (0.105.51) once a nickname, which
--                            crashed DF 53.17: upkeep() unmarks them for
--                            autobutcher, slaughter_one skips them); f = 0
--                            lets every breeder go
--   tame(max)                caged wild animals given a training assignment
--                            (any trainer, no war or hunting flag): DF's
--                            animal trainers tame them at the cage
--   train_hunt(max)          tame adults of a TRAINABLE_HUNTING kind given
--                            hunting training (the war kind is ai-society's)
--   set_targets(t)           DFHack's autobutcher targets (kids and adults
--                            of each sex a kind keeps) for every kind and
--                            new ones: `autobutcher target fk mk fa ma all`
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/herd'
BREEDER_NICK = 'Breeder'          -- (0.105.51) the old nickname: only cleared now (clear_ai_nicknames)
AI_PASTURE_NAME = 'AI pasture'
MAX_KINDS = 16
MAX_TAMEABLE = 12

local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

local function yes(f, ...)
    local ok, v = pcall(f, ...)
    return ok and v and true or false
end

local function caste_of(u)
    local ok, c = pcall(function() return df.creature_raw.find(u.race).caste[u.caste] end)
    return ok and c or nil
end

local function race_name(u)
    local ok, n = pcall(function() return df.creature_raw.find(u.race).creature_id end)
    return ok and n or tostring(u.race)
end

local function flag(c, name)
    if not c then return false end
    return yes(function() return c.flags[name] end)
end

local function nickname(u)
    local ok, n = pcall(function() return u.name.nickname end)
    return ok and n or ''
end

local function society()
    local ok, m = pcall(reqscript, 'ai-society')
    return ok and m or nil
end

-- an animal that came with a caravan, a visitor or a diplomat: never the fort's (ai-society)
local function visiting(u)
    local soc = society()
    if soc and soc.visiting_animal then return yes(soc.visiting_animal, u) end
    return yes(function() return u.flags1.merchant end)
end

local function grazer_tiles(u)
    local soc = society()
    if soc and soc.grazer_tiles then
        local ok, n = pcall(soc.grazer_tiles, u)
        if ok and type(n) == 'number' then return n end
    end
    return 10
end

-- The fort's own animal: alive, an animal, the fort's (fort-controlled, or
-- tame and of its civ), no citizen, not a visitor's.
function fort_animal(u)
    if not yes(dfhack.units.isAlive, u) or not yes(dfhack.units.isAnimal, u) then return false end
    if yes(dfhack.units.isCitizen, u) then return false end
    if not (yes(dfhack.units.isFortControlled, u)
            or (yes(dfhack.units.isTame, u) and yes(dfhack.units.isOwnCiv, u))) then
        return false
    end
    return not visiting(u)
end

local function is_pet(u)
    if yes(dfhack.units.isPet, u) then return true end
    local ok, id = pcall(function() return u.relationship_ids.PetOwner end)
    return ok and type(id) == 'number' and id ~= -1
end

local function trained(u)
    local okp, prof = pcall(function() return df.profession[u.profession] end)
    if okp and (prof == 'TRAINED_WAR' or prof == 'TRAINED_HUNTER') then return prof end
    if yes(dfhack.units.isWar, u) then return 'TRAINED_WAR' end
    if yes(dfhack.units.isHunter, u) then return 'TRAINED_HUNTER' end
    return nil
end

local function caged(u)
    return yes(function() return u.flags1.caged end)
end

local function born(u)
    local ok, b = pcall(function() return u.birth_year * 403200 + u.birth_time end)
    return ok and b or 0
end

-- Wool on it now: one of its caste's shearable layers grown to the shear
-- length (df-structures: shearable when u.appearance.bp_modifiers[
-- layer.bp_modifiers_idx[i]] >= layer.length). Shearing one with none
-- grown is DF's "Shear animal: No creature" (I7a: more than 250 a run).
function wool_now(u, c)
    c = c or caste_of(u)
    local ok, grown = pcall(function()
        for _, layer in ipairs(c.shearable_tissue_layer) do
            for _, idx in ipairs(layer.bp_modifiers_idx) do
                local v = u.appearance.bp_modifiers[idx]
                if type(v) == 'number' and v >= layer.length then return true end
            end
        end
        return false
    end)
    return ok and grown or false
end

local function shearable(c)
    local ok, n = pcall(function() return #c.shearable_tissue_layer end)
    return ok and type(n) == 'number' and n > 0
end

local function milkable(c)
    return flag(c, 'MILKABLE') or yes(function() return (c.misc.milkable or 0) > 0 end)
end

-- Milk ready now: an adult female of a milkable kind with no MilkCounter
-- running (DF counts down from the last milking).
function milk_now(u, c)
    c = c or caste_of(u)
    if not milkable(c) or not yes(dfhack.units.isAdult, u) or not yes(dfhack.units.isFemale, u) then return false end
    local ok, waiting = pcall(function()
        local want = df.misc_trait_type.MilkCounter
        for _, t in ipairs(u.status.misc_traits) do
            if t.id == want and (t.value or 0) > 0 then return true end
        end
        return false
    end)
    return ok and not waiting
end

-- A kind worth breeding: a grazer (meat, milk, wool) or an egg layer.
local function breeding_kind(u, c)
    return yes(dfhack.units.isGrazer, u) or flag(c, 'LAYS_EGGS')
end

-- A caged wild animal DF's trainers can tame: not tame, not intelligent
-- (those are prisoners: ai-captives), no great danger (a forgotten beast
-- stays caged), a pet or trainable kind (DF's PET, PET_EXOTIC,
-- TRAINABLE_WAR, TRAINABLE_HUNTING). (r9, audit A7 #26) Never an invader's
-- beast (a caged goblin's mount: invader, or another civ's), and a large
-- predator only with `predators` (Husbandry at its top: a half-trained one
-- turns wild again among the dwarves). Returns the second value 'predator'
-- for one left out only for being a large predator.
local function tameable(u, predators)
    if not caged(u) or not yes(dfhack.units.isAlive, u) or not yes(dfhack.units.isAnimal, u) then return false end
    if yes(dfhack.units.isTame, u) or yes(dfhack.units.isCitizen, u) or yes(dfhack.units.isGreatDanger, u) then
        return false
    end
    if yes(dfhack.units.isInvader, u) then return false end
    local okc, civ = pcall(function() return u.civ_id end)
    if okc and type(civ) == 'number' and civ >= 0 and not yes(dfhack.units.isOwnCiv, u) then return false end
    local c = caste_of(u)
    if not c or flag(c, 'CAN_LEARN') or flag(c, 'CAN_SPEAK') then return false end
    if not (flag(c, 'PET') or flag(c, 'PET_EXOTIC') or flag(c, 'TRAINABLE_WAR') or flag(c, 'TRAINABLE_HUNTING')) then
        return false
    end
    if not predators and flag(c, 'LARGE_PREDATOR') then return false, 'predator' end
    return true
end

local function training_list()
    local ok, v = pcall(function() return df.global.plotinfo.training.training_assignments end)
    if ok and v then return v end
    ok, v = pcall(function() return df.global.plotinfo.equipment.training_assignments end)
    if ok and v then return v end
    error('no animal training list in this DF')
end

-- (kept sorted by animal_id, as DF keeps the list)
local function utils_insert(list, a)
    local ok = pcall(function() require('utils').insert_sorted(list, a, 'animal_id') end)
    if not ok then list:insert('#', a) end
end

local function assigned_ids()
    local out, n = {}, 0
    local ok = pcall(function()
        for _, a in ipairs(training_list()) do out[a.animal_id] = a; n = n + 1 end
    end)
    return out, n, ok
end

local function pasture_of(u)
    local ok, z = pcall(function()
        local ref = dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED)
        if not ref then return false end
        return df.building.find(ref.building_id) or false
    end)
    if not ok then return nil end
    return z
end

local function state()
    local d = U.site_get(SITE_KEY, {})
    return type(d) == 'table' and d or {}
end

-- --- (0.105.51) the animals the AI keeps from the butcher, by id -------------
--
-- Fort C, 15 Nov: DF 53.17 crashed five times overnight in its render path,
-- each crash log naming a named female tame animal, three of them stray cats
-- the AI had nicknamed 'Mouser'. DFHack's setNickname gives an unnamed animal
-- a whole new name record (has_name, language 0, no first name, no words)
-- to hold the nickname: the likely crash. So the AI renames no animal now.
-- Its mousers (ai-society keep_mousers) and breeders (keep_breeders) are kept
-- in a list of unit ids in the save's site data instead. autobutcher has no
-- per-unit protection but a name (plugins/autobutcher.cpp isProtectedUnit),
-- so upkeep() takes the butcher's mark off a kept animal each report (not
-- while the AI is halted), the bridge's slaughter_one skips them, and once a
-- fort the nicknames the AI gave ('Mouser', 'Breeder', exactly) are cleared,
-- their animals put on the list.
KEPT_KEY = 'ai-overseer/kept-animals'
KEPT_KINDS = {'mousers', 'breeders'}
AI_NICKS = {Mouser = 'mousers', Breeder = 'breeders'}

local function kept_state()
    local d = U.site_get(KEPT_KEY, {})
    if type(d) ~= 'table' then d = {} end
    for _, k in ipairs(KEPT_KINDS) do
        if type(d[k]) ~= 'table' then d[k] = {} end
    end
    return d
end

-- The ids kept as `kind` ('mousers' or 'breeders'): a set {[id] = true}.
function kept_ids(kind)
    local out = {}
    for _, id in ipairs(kept_state()[kind] or {}) do
        local n = tonumber(id)
        if n then out[n] = true end
    end
    return out
end

-- Every id the AI keeps, of either kind: a set.
function kept_all()
    local out = {}
    local d = kept_state()
    for _, k in ipairs(KEPT_KINDS) do
        for _, id in ipairs(d[k]) do
            local n = tonumber(id)
            if n then out[n] = true end
        end
    end
    return out
end

-- Saves the set `ids` as the `kind` kept.
function kept_save(kind, ids)
    local d = kept_state()
    local list = {}
    for id, on in pairs(ids or {}) do
        if on then table.insert(list, id) end
    end
    table.sort(list)
    d[kind] = list
    return U.site_put(KEPT_KEY, d)
end

-- One time a fort: the nicknames the AI gave ('Mouser', 'Breeder') cleared;
-- each such animal still alive and the fort's goes on the kept list instead.
-- Done once every one is cleared (a nickname the game would not clear is
-- tried again next time).
function clear_ai_nicknames(units)
    local d = kept_state()
    if d.nicks_cleared then return {ok = true, unchanged = true} end
    local sets = {}
    for _, k in ipairs(KEPT_KINDS) do sets[k] = kept_ids(k) end
    local cleared, failed = 0, 0
    local list = units
    if not list then
        local ok, all = pcall(function() return df.global.world.units.all end)
        list = ok and all or report_units()
    end
    for _, u in ipairs(list) do
        local kind = AI_NICKS[nickname(u)]
        if kind and yes(dfhack.units.isAnimal, u) then
            pcall(dfhack.units.setNickname, u, '')
            if nickname(u) == '' then
                cleared = cleared + 1
                if fort_animal(u) then sets[kind][u.id] = true end
            else
                failed = failed + 1
            end
        end
    end
    d = kept_state()
    for _, k in ipairs(KEPT_KINDS) do
        local l = {}
        for id in pairs(sets[k]) do table.insert(l, id) end
        table.sort(l)
        d[k] = l
    end
    if failed == 0 then d.nicks_cleared = true end
    U.site_put(KEPT_KEY, d)
    return {ok = failed == 0, cleared = cleared, failed = failed > 0 and failed or nil}
end

-- The kept animals guarded: those gone (dead, off the list of units, no
-- longer the fort's) dropped from the list, the butcher's mark taken off the
-- rest. Returns {kept, unmarked, dropped}.
function guard_kept(dry_run, units)
    local here = {}
    for _, u in ipairs(units or report_units()) do here[u.id] = u end
    local out = {kept = 0, unmarked = 0, dropped = 0}
    for _, kind in ipairs(KEPT_KINDS) do
        local ids, changed = kept_ids(kind), false
        for id in pairs(ids) do
            local u = here[id]
            if not u and not units then
                local ok, f = pcall(df.unit.find, id)
                u = ok and f or nil
            end
            if not u or not fort_animal(u) then
                if not dry_run then ids[id] = nil; changed = true end
                out.dropped = out.dropped + 1
            else
                out.kept = out.kept + 1
                if yes(function() return u.flags2.slaughter end) then
                    if not dry_run then pcall(function() u.flags2.slaughter = false end) end
                    out.unmarked = out.unmarked + 1
                end
            end
        end
        if changed then kept_save(kind, ids) end
    end
    return out
end

-- Each report (lua/ai-bridge.lua's herd section): the AI's old nicknames
-- cleared once (an undoing step: also while halted), the kept guarded (not
-- while halted: the game is the player's then).
function upkeep()
    local out = {}
    local okc, c = pcall(clear_ai_nicknames)
    out.nicknames = okc and c or {ok = false, error = tostring(c)}
    local halted = false
    pcall(function() halted = reqscript('ai-status').is_halted() == true end)
    if not halted then
        local okg, g = pcall(guard_kept, false)
        out.guard = okg and g or {ok = false, error = tostring(g)}
    end
    return out
end

-- (0.105.113 item13) The fort's butcher's shops, built ({pos}), and whether a
-- unit can walk to one. E, 24-25 Nov: a peafowl marked for slaughter stood in a
-- pasture with no path to any butcher's shop; DF made no job for it, and every
-- slaughter_one for a mood was refused "1 animal(s) already wait for the
-- butcher" (79 times). No shop read: true (nothing known against it).
function butcher_shops()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            if b.type == df.workshop_type.Butchers and b:getBuildStage() >= b:getMaxBuildStage() then
                table.insert(out, xyz2pos(b.centerx, b.centery, b.z))
            end
        end
    end)
    return out
end

function reaches_butcher(u, shops)
    if not shops or #shops == 0 then return true end
    local ok, x, y, z = pcall(dfhack.units.getPosition, u)
    if not ok or not x then return false end
    local from = xyz2pos(x, y, z)
    for _, p in ipairs(shops) do
        local okw, w = pcall(dfhack.maps.canWalkBetween, from, p)
        if okw and w then return true end
    end
    return false
end

local function trainers()
    local n = 0
    pcall(function()
        local labor = df.unit_labor.ANIMALTRAIN
        for _, u in ipairs(report_citizens(true)) do
            if labor and u.status.labors[labor] then n = n + 1 end
        end
    end)
    return n
end

function report()
    local kinds, order = {}, {}
    local shops                                -- (0.105.113 item13) read at the first marked animal
    local out = {tame = 0, caged_tame = 0, pets = 0, war = 0, hunters = 0, kids = 0, marked = 0, marked_waiting = 0,
                 breeders = 0,
                 named = 0, wool_now = 0, milk_now = 0, shearable = 0, milkable = 0, egg_layers = 0,
                 grazers = 0, grazing_need = 0, pairs = 0, breeding_pairs = 0, tameable = 0, hunt_candidates = 0}
    local assigned, n_assigned, ok_list = assigned_ids()
    out.in_training = ok_list and n_assigned or nil
    local bset = kept_ids('breeders')          -- (0.105.51) the AI's breeders: a list, no nickname
    local tame_races = {}
    for _, u in ipairs(report_units()) do
        if fort_animal(u) then
            local c = caste_of(u)
            local r = race_name(u)
            local k = kinds[r]
            if not k then
                k = {name = r, n = 0, f = 0, m = 0, kids = 0, breeders_f = 0, breeders_m = 0, protected = 0,
                     marked = 0, caged = 0, grazer = yes(dfhack.units.isGrazer, u) or nil,
                     layer = flag(c, 'LAYS_EGGS') or nil, milk = milkable(c) or nil, wool = shearable(c) or nil}
                kinds[r] = k
                table.insert(order, r)
            end
            k.n = k.n + 1
            out.tame = out.tame + 1
            local adult = yes(dfhack.units.isAdult, u)
            local female, male = yes(dfhack.units.isFemale, u), yes(dfhack.units.isMale, u)
            local nick = nickname(u)
            local pet, tr, in_cage = is_pet(u), trained(u), caged(u)
            local marked = yes(function() return u.flags2.slaughter end)
            if in_cage then k.caged = k.caged + 1; out.caged_tame = out.caged_tame + 1 end
            if pet then out.pets = out.pets + 1 end
            if tr == 'TRAINED_WAR' then out.war = out.war + 1 elseif tr == 'TRAINED_HUNTER' then out.hunters = out.hunters + 1 end
            if marked then
                k.marked = k.marked + 1; out.marked = out.marked + 1
                -- (0.105.113 item13) and of them those that can walk to a butcher's (a job comes)
                shops = shops or butcher_shops()
                if reaches_butcher(u, shops) then out.marked_waiting = out.marked_waiting + 1 end
            end
            if not adult then k.kids = k.kids + 1; out.kids = out.kids + 1 end
            local breeder = bset[u.id] == true
            if breeder then
                out.breeders = out.breeders + 1
                if female then k.breeders_f = k.breeders_f + 1 elseif male then k.breeders_m = k.breeders_m + 1 end
            elseif nick ~= '' or yes(function() return u.name.has_name end) then
                out.named = out.named + 1
            end
            if pet or tr or nick ~= '' or breeder then k.protected = k.protected + 1 end
            if adult and not in_cage then
                if female then k.f = k.f + 1 elseif male then k.m = k.m + 1 end
            end
            if not in_cage then
                if wool_now(u, c) then out.wool_now = out.wool_now + 1 end
                if shearable(c) then out.shearable = out.shearable + 1 end
                if milk_now(u, c) then out.milk_now = out.milk_now + 1 end
                if milkable(c) and adult and female then out.milkable = out.milkable + 1 end
                if flag(c, 'LAYS_EGGS') and adult and female then out.egg_layers = out.egg_layers + 1 end
                if yes(dfhack.units.isGrazer, u) then
                    out.grazers = out.grazers + 1
                    -- the grass the AI must find: its own pastures' animals and the loose
                    -- (the player's pastures are theirs to size)
                    local z = pasture_of(u)
                    if z == false or (z and tostring(z.name or '') == AI_PASTURE_NAME) then
                        out.grazing_need = out.grazing_need + grazer_tiles(u)
                    end
                end
            end
            -- hunting training: a tame adult of a hunting kind, nobody's pet,
            -- untrained, no breeder, no assignment yet
            if adult and not in_cage and not pet and not tr and not breeder and not assigned[u.id]
                    and flag(c, 'TRAINABLE_HUNTING') and yes(dfhack.units.isOwnCiv, u) then
                out.hunt_candidates = out.hunt_candidates + 1
            end
        elseif not assigned[u.id] then
            local ok_t, why_t = tameable(u)
            if ok_t then
                out.tameable = out.tameable + 1
                local r = race_name(u)
                tame_races[r] = (tame_races[r] or 0) + 1
            elseif why_t == 'predator' then
                out.tameable_predators = (out.tameable_predators or 0) + 1   -- (r9) only at Husbandry's top
            end
        end
    end
    table.sort(order, function(a, b)
        if kinds[a].n ~= kinds[b].n then return kinds[a].n > kinds[b].n end
        return a < b
    end)
    out.kinds = {}
    for _, r in ipairs(order) do
        local k = kinds[r]
        if k.f > 0 and k.m > 0 then
            out.pairs = out.pairs + 1
            if k.grazer or k.layer then out.breeding_pairs = out.breeding_pairs + 1 end
        end
        if #out.kinds < MAX_KINDS then table.insert(out.kinds, k) end
    end
    out.kinds_n = #order
    local tl = {}
    for r, n in pairs(tame_races) do table.insert(tl, {name = r, n = n}) end
    table.sort(tl, function(a, b) return a.n > b.n or (a.n == b.n and a.name < b.name) end)
    out.tameable_kinds = {}
    for i = 1, math.min(MAX_TAMEABLE, #tl) do out.tameable_kinds[i] = tl[i] end
    out.trainers = trainers()
    local d = state()
    out.targets = type(d.targets) == 'table' and d.targets or nil
    out.tamed = tonumber(d.tamed) or 0
    return out
end

-- Breeders: per kind worth breeding with an adult pair, the male and up to
-- `females` females kept (on the kept list, KEPT_KEY; (0.105.51) no longer a
-- nickname). Those already kept stay first; then the youngest adults (they
-- breed longest). Nobody's pet, no war or hunting animal, nothing caged, no
-- name of the player's. A breeder past the want (or every one, females = 0)
-- is let go.
function keep_breeders(females, dry_run, txt)
    females = math.max(0, math.min(tonumber(females) or 2, 12))
    if not dry_run then pcall(clear_ai_nicknames) end
    local bset = kept_ids('breeders')
    local before = 0
    for _ in pairs(bset) do before = before + 1 end
    local by = {}
    for _, u in ipairs(report_units()) do
        if fort_animal(u) and yes(dfhack.units.isAdult, u) then
            local nick = nickname(u)
            local c = caste_of(u)
            -- (r9, audit A7 #23) never a new one already marked for the butcher
            -- (the player's mark, or autobutcher's: left as it is; another is kept)
            local marked = not bset[u.id] and yes(function() return u.flags2.slaughter end)
            if bset[u.id] or (nick == '' and not caged(u) and not is_pet(u) and not trained(u) and not marked
                    and not yes(function() return u.name.has_name end) and breeding_kind(u, c)) then
                local r = race_name(u)
                by[r] = by[r] or {f = {}, m = {}}
                if yes(dfhack.units.isFemale, u) then table.insert(by[r].f, u)
                elseif yes(dfhack.units.isMale, u) then table.insert(by[r].m, u) end
            end
        end
    end
    local kept, released, unmarked, named = 0, 0, 0, {}
    local function order(list)
        table.sort(list, function(a, b)
            local ak, bk = bset[a.id] == true, bset[b.id] == true
            if ak ~= bk then return ak end
            if born(a) ~= born(b) then return born(a) > born(b) end
            return a.id < b.id
        end)
    end
    local keep_set = {}
    local function keep(u)
        keep_set[u.id] = true
        if bset[u.id] then kept = kept + 1; return true end
        kept = kept + 1
        local okn, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
        if #named < 12 then table.insert(named, okn and n or ('#' .. u.id)) end
        return true
    end
    local function let_go(u)
        if not bset[u.id] then return end
        released = released + 1
    end
    local races = {}
    for r in pairs(by) do table.insert(races, r) end
    table.sort(races)
    local kinds = 0
    for _, r in ipairs(races) do
        local g = by[r]
        order(g.f)
        order(g.m)
        local pair = females > 0 and #g.f > 0 and #g.m > 0
        if pair then kinds = kinds + 1 end
        for i, u in ipairs(g.m) do
            if pair and i == 1 then keep(u) else let_go(u) end
        end
        for i, u in ipairs(g.f) do
            if pair and i <= females then keep(u) else let_go(u) end
        end
    end
    if females > 0 and kinds == 0 and released == 0 then
        return {ok = false, rejected = true, error = 'no kind of grazer or egg layer here has an adult male and female'}
    end
    if not dry_run then
        -- the list is the kept now (a kept one no longer here, adult or the fort's, drops off too)
        local n = 0
        for _ in pairs(keep_set) do n = n + 1 end
        local same = n == before
        if same then for id in pairs(bset) do if not keep_set[id] then same = false; break end end end
        if not same then kept_save('breeders', keep_set) end
    end
    return {ok = true, kinds = kinds, kept = kept, named = #named > 0 and named or nil, released = released,
            unmarked = unmarked, dry_run = dry_run or nil}
end

-- Tame up to `max` caged wild animals: a training assignment with any
-- trainer and no war or hunting flag, as DF's own "tame" on a caged
-- creature makes; DF's animal trainers go to the cage and tame it.
function tame(max, dry_run, txt, predators)
    max = math.max(1, math.min(tonumber(max) or 2, 10))
    local list = training_list()
    local assigned = {}
    for _, a in ipairs(list) do assigned[a.animal_id] = true end
    local cands = {}
    for _, u in ipairs(report_units()) do
        if not assigned[u.id] and tameable(u, predators == true) then table.insert(cands, u) end
    end
    if #cands == 0 then return {ok = false, rejected = true, error = 'no caged wild animal here can be tamed'} end
    table.sort(cands, function(a, b) return a.id < b.id end)
    local names = {}
    for i = 1, math.min(max, #cands) do
        local u = cands[i]
        if not dry_run then
            local a = df.training_assignment:new()
            a.animal_id = u.id
            a.trainer_id = -1
            a.flags.any_trainer = true
            utils_insert(list, a)
        end
        local okn, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
        table.insert(names, okn and n or ('#' .. u.id))
    end
    if not dry_run then
        local d = state()
        d.tamed = (tonumber(d.tamed) or 0) + #names
        U.site_put(SITE_KEY, d)
    end
    return {ok = true, assigned = #names, animals = names, left = #cands - #names, dry_run = dry_run or nil}
end

-- Hunting training for up to `max` tame adults of a hunting kind (they go
-- out with the fort's hunters); breeders, pets and the trained left alone.
function train_hunt(max, dry_run, txt)
    max = math.max(1, math.min(tonumber(max) or 2, 6))
    local list = training_list()
    local assigned = {}
    for _, a in ipairs(list) do assigned[a.animal_id] = true end
    local cands = {}
    local bset = kept_ids('breeders')
    for _, u in ipairs(report_units()) do
        if fort_animal(u) and not assigned[u.id] and yes(dfhack.units.isAdult, u) and not caged(u)
                and not is_pet(u) and not trained(u) and not bset[u.id]
                and yes(dfhack.units.isOwnCiv, u) and flag(caste_of(u), 'TRAINABLE_HUNTING') then
            table.insert(cands, u)
        end
    end
    if #cands == 0 then return {ok = false, rejected = true, error = 'no tame animal here can be trained to hunt'} end
    table.sort(cands, function(a, b) return a.id < b.id end)
    local names = {}
    for i = 1, math.min(max, #cands) do
        local u = cands[i]
        if not dry_run then
            local a = df.training_assignment:new()
            a.animal_id = u.id
            a.trainer_id = -1
            a.flags.any_trainer = true
            a.flags.train_hunt = true
            utils_insert(list, a)
        end
        local okn, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
        table.insert(names, okn and n or ('#' .. u.id))
    end
    return {ok = true, assigned = #names, animals = names, left = #cands - #names, dry_run = dry_run or nil}
end

-- DFHack's autobutcher targets for every kind watched and every new one:
-- t = {fk, mk, fa, ma} (kids female and male, adults female and male).
function set_targets(t, dry_run)
    local v = {}
    for i, key in ipairs({'fk', 'mk', 'fa', 'ma'}) do
        local n = tonumber(type(t) == 'table' and (t[key] or t[i]) or nil)
        if not n or n < 0 or n > 50 or n ~= math.floor(n) then
            return {ok = false, rejected = true, error = 'herd_targets needs fk, mk, fa, ma: whole numbers 0-50'}
        end
        v[i] = math.floor(n)
    end
    local cmd = ('autobutcher target %d %d %d %d all'):format(v[1], v[2], v[3], v[4])
    if dry_run then return {ok = true, dry_run = true, command = cmd} end
    for _, which in ipairs({'all', 'new'}) do
        local out, rv = dfhack.run_command_silent('autobutcher', 'target', tostring(v[1]), tostring(v[2]),
                                                  tostring(v[3]), tostring(v[4]), which)
        if rv ~= 0 and rv ~= (CR_OK or 0) then
            return {ok = false, error = ('autobutcher target failed: %s'):format(tostring(out or ''):gsub('%s+$', ''))}
        end
    end
    local d = state()
    d.targets = {fk = v[1], mk = v[2], fa = v[3], ma = v[4]}
    U.site_put(SITE_KEY, d)
    return {ok = true, targets = d.targets, command = cmd}
end
