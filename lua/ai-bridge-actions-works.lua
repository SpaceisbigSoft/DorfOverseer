-- ai-bridge-actions-works: the action handlers for uniforms and gear, burrows, threats
-- answered, the builder's surface works, slaughter, instruments, work
-- details, old remains, offices, squads, trade, water, the cistern and
-- the water works, locations, petitions and alerts.
--
-- A part of ai-bridge.lua (r6, split out of ai-bridge-actions.lua when it was 204 KB),
-- loaded by it after ai-bridge-actions into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-actions files share with this one come from ACTIONS_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-actions-works is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-actions-works'] = '0.105.66'   -- bumped with BRIDGE_VERSION

-- (0.99.7) Soldiers who don't pick up their uniforms: DFHack's
-- uniform-unstick frees items assigned to one soldier but held by another
-- (or in a container) so their owners can claim them. Its report goes back.
function act_unstick_uniforms(a)
    local okr, changed = pcall(function() return reqscript('ai-military').replace_clothing(a.dry_run == true) end)
    if a.dry_run then return {ok = true, dry_run = true, replace_clothing = okr and changed or nil} end
    -- (0.99.9) the AI's uniforms replace clothes, and what blocks a uniform
    -- item is dropped (uniform-unstick's report named everyday gloves and shoes)
    local output, rv = dfhack.run_command_silent('uniform-unstick', '--all', '--free', '--drop')
    output = tostring(output or ''):gsub('%s+$', '')
    if rv ~= CR_OK then return {ok = false, error = 'uniform-unstick failed: ' .. output:sub(1, 200)} end
    local lines = 0
    for _ in output:gmatch('[^\n]+') do lines = lines + 1 end
    return {ok = true, lines = lines, report = output:sub(1, 400),
            replace_clothing = okr and changed or tostring(changed):sub(1, 120)}
end

-- (0.104.58) Gear DF keeps assigned to no one, or on no list, put back where
-- DF hands it out (lua/ai-military.lua free_stray_gear).
function act_free_stray_gear(a)
    local n = int_in(a.limit or 100, 1, 500)
    if not n then return reject('free_stray_gear: limit 1-500') end
    return reqscript('ai-military').free_stray_gear(a.dry_run == true, n)
end

-- (0.105.8) Armour put on the soldiers' places as assign_weapons does weapons
-- (lua/ai-military.lua assign_kit).
function act_assign_kit(a)
    local n = int_in(a.limit or 10, 1, 50)
    if not n then return reject('assign_kit: limit 1-50') end
    return reqscript('ai-military').assign_kit(a.dry_run == true, n)
end

-- (0.104.60) Weapons put on the soldiers' places when DF leaves the entry
-- empty with free weapons about (lua/ai-military.lua assign_weapons).
function act_assign_weapons(a)
    local n = int_in(a.limit or 10, 1, 50)
    if not n then return reject('assign_weapons: limit 1-50') end
    return reqscript('ai-military').assign_weapons(a.dry_run == true, n)
end

-- (0.104.77) A chair beside each lone chair in a tavern zone (lua/ai-builder.lua pair_chairs).
-- (0.104.78) `zones`: several tried in turn until one gets chairs (Enxah's
-- proper tavern answered "every chair has one beside it")
function act_pair_chairs(a)
    local n = int_in(a.max or 5, 1, 20)
    if not n then return reject('pair_chairs: max 1-20') end
    local ids = {}
    if type(a.zones) == 'table' then
        for _, z in ipairs(a.zones) do local id = whole_number(z); if id then table.insert(ids, id) end end
    elseif a.zone_id ~= nil then
        local id = whole_number(a.zone_id); if id then table.insert(ids, id) end
    end
    if #ids == 0 then return reject('pair_chairs needs zone_id or zones') end
    local B, said, all_paired = reqscript('ai-builder'), {}, true
    for _, id in ipairs(ids) do
        local r = B.pair_chairs(id, a.dry_run == true, n)
        if r.ok then return r end
        table.insert(said, tostring(r.error))
        local e = tostring(r.error)
        if not e:find('has one beside it', 1, true) then all_paired = false end   -- (no chairs yet: not done)
    end
    -- (0.104.138) every chair already has a neighbour: nothing to do (asked 33 times)
    return {ok = false, rejected = true, nothing_to_do = all_paired or nil, error = table.concat(said, '; ')}
end

-- (0.104.78) The recreation burrow: the low-mood moved in, the recovered let
-- out (lua/ai-society.lua recreation_tick).
function act_recreation(a)
    local n = int_in(a.max or 8, 1, 30)
    local days = int_in(a.days or 28, 3, 112)
    if not n or not days then return reject('recreation: max 1-30, days 3-112') end
    -- (0.104.80) places for those who badly want friends, a short stay each
    local f, fd = int_in(a.friends or 0, 0, 10), int_in(a.friend_days or 7, 3, 28)
    if not f or not fd then return reject('recreation: friends 0-10, friend_days 3-28') end
    if a.release_only and a.release ~= true then      -- (0.105.48, K3) halted: only let out
        return {ok = false, rejected = true, halted = true, error = 'the AI is halted in the game: the burrow only emptied'}
    end
    -- (0.105.51) unhappy: the plain unhappy moved in too (a fort unhappy past the brain's share)
    if a.unhappy ~= nil and type(a.unhappy) ~= 'boolean' then return reject('recreation: unhappy is true or false') end
    return reqscript('ai-society').recreation_tick(n, days, a.dry_run == true, txt, f, fd, a.release == true,
                                                   a.unhappy == true)
end

-- (0.104.168) The loose cups no finished goods pile takes: the pile with the
-- most room set to take them; forbidden cups in a hall unforbidden
-- (lua/ai-society.lua accept_cups).
function act_accept_cups(a)
    return reqscript('ai-society').accept_cups(a.dry_run == true)
end

-- (0.104.168) A few cats (vermin hunters) kept from the butcher
-- (lua/ai-society.lua keep_mousers): (0.105.51) on the AI's kept list, no
-- longer nicknamed (named animals crashed DF 53.17).
function act_keep_mousers(a)
    local n = int_in(a.count or 6, 1, 20)
    if not n then return reject('keep_mousers: count 1-20') end
    return reqscript('ai-society').keep_mousers(n, a.dry_run == true, txt)
end

-- (0.104.167) The hospital burrow: the patients kept inside the hospitals
-- (with the nearest drink and food they can reach), the healed let out
-- (lua/ai-society.lua hospital_burrow_tick).
function act_hospital_burrow(a)
    local n = int_in(a.max or 30, 1, 60)
    local per = int_in(a.per or 10, 1, 30)
    local days = int_in(a.days or 28, 3, 112)       -- (review) the longest stay
    if not n or not per or not days then return reject('hospital_burrow: max 1-60, per 1-30, days 3-112') end
    -- (review) release: everyone let out (the rule switched off, the hospital gone, the status unreadable)
    if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('hospital_burrow: release is true or false') end
    if a.release_only and a.release ~= true then      -- (0.105.48, K3) halted: only let out
        return {ok = false, rejected = true, halted = true, error = 'the AI is halted in the game: the burrow only emptied'}
    end
    return reqscript('ai-society').hospital_burrow_tick(n, per, a.dry_run == true, txt, days, a.release == true)
end

-- (0.104.169) The calm-down burrows: each citizen in a tantrum kept in a
-- free bedroom away from the hospitals (with the nearest drink), let out
-- once calm or after `days` (lua/ai-society.lua calm_burrow_tick).
function act_calm_burrow(a)
    local n = int_in(a.max or 6, 1, 6)
    local days = int_in(a.days or 3, 1, 7)          -- the longest stay
    if not n or not days then return reject('calm_burrow: max 1-6, days 1-7') end
    if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('calm_burrow: release is true or false') end
    if a.release_only and a.release ~= true then      -- (0.105.48, K3) halted: only let out
        return {ok = false, rejected = true, halted = true, error = 'the AI is halted in the game: the burrows only emptied'}
    end
    return reqscript('ai-society').calm_burrow_tick(n, days, a.dry_run == true, txt, a.release == true)
end

-- (0.105.0) Round 3, threats answered (lua/ai-threats.lua). Fire: the
-- tiles round a fire get restricted traffic and the jobs beside it are taken
-- off; lift puts back the tiles the AI changed.
function act_fire_guard(a)
    local r = int_in(a.radius or 6, 1, 15)
    local jobs = int_in(a.max_jobs or 40, 0, 200)
    if not r or not jobs then return reject('fire_guard: radius 1-15, max_jobs 0-200') end
    if a.lift ~= nil and type(a.lift) ~= 'boolean' then return reject('fire_guard: lift is true or false') end
    return reqscript('ai-threats').fire_guard(r, jobs, a.lift == true, a.dry_run == true)
end

-- (0.105.0) A cage room for prisoners: an animal stockpile inside the fort.
function act_prisoner_room(a)
    return reqscript('ai-threats').prisoner_room(a.dry_run == true)
end

-- (0.105.0) Werebeast citizens in cells for the full moon (ids), or let out (release).
function act_moon_cell(a)
    local ids = {}
    if a.ids ~= nil and type(a.ids) ~= 'table' then return reject('moon_cell: ids is a list of unit ids') end
    for _, v in ipairs(a.ids or {}) do
        local id = whole_number(v)
        if not id then return reject('moon_cell: ids must be whole numbers') end
        table.insert(ids, id)
    end
    if #ids > 10 then return reject('moon_cell: at most 10 ids') end
    if a.release ~= nil and type(a.release) ~= 'boolean' then return reject('moon_cell: release is true or false') end
    return reqscript('ai-threats').moon_cell(ids, a.release == true, a.dry_run == true, txt)
end

-- (0.105.0) The way down to a cavern locked (its doors and hatches), or unlocked (open).
function act_seal_cavern(a)
    if type(a.layer) ~= 'string' or #a.layer == 0 then return reject('seal_cavern needs layer') end
    if a.open ~= nil and type(a.open) ~= 'boolean' then return reject('seal_cavern: open is true or false') end
    if a.openings ~= nil and type(a.openings) ~= 'boolean' then return reject('seal_cavern: openings is true or false') end
    local tiles = {}
    if not a.open then
        -- (0.105.26) openings: every cavern opening on record too (tiles may then be none)
        if a.openings == true and a.tiles == nil then a.tiles = {} end
        if type(a.tiles) ~= 'table' then return reject('seal_cavern needs tiles {x, y, z}') end
        for _, p in ipairs(a.tiles) do
            if type(p) ~= 'table' or not whole_number(p.x) or not whole_number(p.y) or not whole_number(p.z) then
                return reject('seal_cavern: each tile is {x, y, z}')
            end
            table.insert(tiles, {x = whole_number(p.x), y = whole_number(p.y), z = whole_number(p.z)})
        end
        if (#tiles == 0 and a.openings ~= true) or #tiles > 20 then return reject('seal_cavern: 1-20 tiles') end
    end
    -- (0.105.0 review) the cavern's levels, so no dwarf is sealed out on the far side
    if (a.z1 ~= nil and not whole_number(a.z1)) or (a.z2 ~= nil and not whole_number(a.z2)) then
        return reject('seal_cavern: z1 and z2 are whole numbers')
    end
    return reqscript('ai-threats').seal_cavern(a.layer, tiles, a.open == true, a.dry_run == true,
                                               a.z1 and whole_number(a.z1), a.z2 and whole_number(a.z2),
                                               a.openings == true)
end

-- (0.104.168) Infected dwarves DF asks no treatment for, put to rest in a
-- free hospital bed (as DFHack's dwarfvet does for animals), the worst
-- first; and a second doctor's post at a hospital (lua/ai-health.lua).
function act_rest_infected(a)
    local n = int_in(a.max or 3, 1, 10)
    -- (review) at most `cap` of the AI's sleepers at once, `keep_free` beds left for DF's patients
    local cap, keep = int_in(a.cap or 3, 1, 20), int_in(a.keep_free or 2, 0, 20)
    if not n or not cap or not keep then return reject('rest_infected: max 1-10, cap 1-20, keep_free 0-20') end
    return reqscript('ai-health').rest_infected(n, a.dry_run == true, txt, cap, keep)
end

-- (0.105.24) A patient needing traction got up from an ordinary bed while a
-- traction bench in a hospital stands free, so DF lays him on it.
function act_traction_rest(a)
    local n = int_in(a.max or 1, 1, 3)
    if not n then return reject('traction_rest: max 1-3') end
    return reqscript('ai-health').traction_rest(n, a.dry_run == true, txt)
end

-- (0.105.24) A dwarf in a strange mood: the materials it can use that lie
-- forbidden or marked for the dump within its walk are freed (lua/ai-moods.lua).
function act_mood_free_items(a)
    local id = math.tointeger(tonumber(a.unit_id))   -- (tests/test_moods.py runs this body alone)
    local n = int_in(a.max or 10, 1, 10)
    if not id or not n then return reject('mood_free_items needs unit_id and max 1-10') end
    return reqscript('ai-moods').free_items(id, a.dry_run == true, n, txt)
end

function act_add_doctor_post(a)
    local id = tonumber(a.location_id)
    if not id then return reject('add_doctor_post needs location_id') end
    return reqscript('ai-health').add_doctor_post(id, a.dry_run == true)
end

function act_gather_plants(a)
    local n = int_in(a.count or 100, 1, 150)
    if not n then return reject('gather_plants needs count 1-150') end
    return reqscript('ai-labor').gather_plants(n, a.dry_run == true)
end

-- Outside things: a refuse pile, a trade depot (lua/ai-builder.lua).
function act_place_surface(a)
    if a.kind ~= 'refuse' and a.kind ~= 'depot' and a.kind ~= 'dump' and a.kind ~= 'cages' then
        return reject('place_surface needs kind refuse|depot|dump|cages')
    end
    return reqscript('ai-builder').place_surface(a.kind, a.dry_run == true)
end

-- (0.101) A bridge across water on the surface (lua/ai-builder.lua crossings).
function act_build_crossing(a)
    local x, y, z = whole_number(a.x), whole_number(a.y), whole_number(a.z)
    local len, width = int_in(a.len, 1, 9), int_in(a.width or 1, 1, 3)
    if not (x and y and z and len and width) or not ({n = 1, s = 1, e = 1, w = 1})[a.dir] then
        return reject('build_crossing needs x, y, z, dir n|s|e|w, len 1-9 and width 1-3')
    end
    if a.kind ~= nil and a.kind ~= 'cheap' and a.kind ~= 'refined' then
        return reject('kind must be cheap or refined')
    end
    local now = abs_tick()
    return reqscript('ai-builder').build_crossing(x, y, z, a.dir, len, width, a.kind or 'cheap', now, a.dry_run == true)
end

function act_remove_crossing(a)
    local i = int_in(a.index, 1, 50)
    if not i then return reject('remove_crossing needs index 1-50 (one of the AI\'s own bridges)') end
    return reqscript('ai-builder').remove_crossing(i, a.dry_run == true)
end

-- The keep: walls round the way in, then a roof (lua/ai-builder.lua), a step at a time.
function act_place_keep(a)
    return reqscript('ai-builder').place_keep(a.dry_run == true)
end

-- (0.105.30) construction. A builder or gates file without the function
-- (one left behind at delivery) refuses cleanly instead of erroring.
local function construct_call(mod, fn, what)
    local ok, M = pcall(reqscript, mod)
    local f = ok and type(M) == 'table' and M[fn] or nil
    if type(f) ~= 'function' then
        return nil, reject(('%s: %s.%s is not loaded (an older %s.lua?)'):format(what, mod, fn, mod))
    end
    return f
end

HALL_KINDS = {field_hall = true, market_hall = true}

HALL_OPTS = {'windows', 'floor', 'statue'}

-- One stage of a surface hall (lua/ai-builder-halls.lua place_hall):
-- {type = 'place_hall', kind = 'field_hall'|'market_hall', windows, floor,
-- statue, dry_run}. The three options are the brain's (by the sliders):
-- true or false, or left out (false); anything else is refused.
function act_place_hall(a)
    if not HALL_KINDS[a.kind] then return reject('place_hall needs kind field_hall|market_hall') end
    local opts = {}
    for _, k in ipairs(HALL_OPTS) do
        local v = a[k]
        if v ~= nil and type(v) ~= 'boolean' then
            return reject(('place_hall: %s must be true or false'):format(k))
        end
        opts[k] = v == true
    end
    local f, r = construct_call('ai-builder', 'place_hall', 'place_hall')
    if not f then return r end
    return f(a.kind, a.dry_run == true, opts)
end

-- The two wall arms out from a standing gatehouse (lua/ai-gates.lua
-- build_wings): {type = 'build_wings', entrance_id, dry_run}
function act_build_wings(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('build_wings needs entrance_id') end
    local f, r = construct_call('ai-gates', 'build_wings', 'build_wings')
    if not f then return r end
    return f(id, a.dry_run == true)
end

-- Block floors over the soil of a finished project (lua/ai-builder-rooms.lua
-- floor_soil_rooms): {type = 'floor_rooms', project_id, dry_run}
function act_floor_rooms(a)
    local id = whole_number(a.project_id)
    if not id then return reject('floor_rooms needs project_id') end
    local f, r = construct_call('ai-builder', 'floor_soil_rooms', 'floor_rooms')
    if not f then return r end
    return f(id, a.dry_run == true)
end

-- (0.105.23, 14.1 step 4c) The Deep mine's trade depot underground: a 3-wide
-- ramp road for the wagons and a hall, dug, then the depot (lua/ai-builder.lua).
function act_deep_depot(a)
    return reqscript('ai-builder').place_deep_depot(a.dry_run == true)
end

-- (0.104.7) One spare tame animal to the butcher: fat for tallow, tallow for
-- soap, soap for wounds (Enxah: 7 infected wounds, no soap, no fat, 42 tame
-- animals). Never a pet, a war or hunting animal, a caged or wild one, a
-- child, or the last two of a kind; from the most numerous kind, a male while
-- the kind has more than one. The game's butcher does the rest.
-- (0.105.30) `oldest`: for a strange mood (a life at stake), the oldest of
-- the chosen kind and sex (`born`: smaller is older).
function slaughter_pick(animals, oldest)
    local by_race = {}
    for _, a in ipairs(animals) do
        local r = by_race[a.race] or {n = 0, males = 0, list = {}}
        r.n = r.n + 1
        if a.male then r.males = r.males + 1 end
        table.insert(r.list, a)
        by_race[a.race] = r
    end
    local best_race, best
    for race, r in pairs(by_race) do
        if r.n >= 3 and (not best or r.n > best.n or (r.n == best.n and race < best_race)) then
            best_race, best = race, r
        end
    end
    if not best then return nil end
    -- a male while the kind has two or more; else a female (the one male breeds)
    local want_male = best.males > 1
    table.sort(best.list, function(x, y)
        local xw, yw = (x.male == want_male), (y.male == want_male)
        if xw ~= yw then return xw end
        if oldest and (x.born or 0) ~= (y.born or 0) then return (x.born or 0) < (y.born or 0) end
        return x.id < y.id
    end)
    return best.list[1], best_race, best.n
end

-- (R1 g6) For a strange mood waiting on bone or leather (a life at stake),
-- any spare tame animal will do: R-AD/R-CE, 15-16 Nov, the "three of a kind,
-- adult" rule refused 93 times in D and 200+ in C and E while five moods died
-- for one bone. Still never a pet, a war or hunting animal, a named one, a
-- caged one (act_slaughter_one leaves those out), nor one of the last
-- breeding pair of its kind. The AI's kept breeders and mousers only when
-- nothing else will do; adults before young (more bone and a hide), the most
-- numerous kind, the oldest. animals: {id, race, male, female, born, adult,
-- kept} (female: nil means "not male"; false with male false: neither sex).
-- (X2, V4) The pair counts every age: a calf grows up to breed (R-AD's herd
-- of one adult bull and four heifer calves lost the bull: no calf was born
-- again). Never the only male of a kind while it has a female, adult or not,
-- nor the only female while it has a male. Among the rest, a pick that
-- leaves the kind an adult pair (breeding now) when it had one comes before
-- one that leaves it a pair only once the young grow up. mates (optional):
-- the kind's other animals that breed but are never taken (pets, war and
-- hunting animals, named ones): {race, male, female, adult}; they count for
-- the pairs only. Returns the pick, its race and kind size.
function slaughter_pick_mood(animals, mates)
    local function sex_of(a)
        if a.male then return 'm' end
        if a.female == false then return nil end
        return 'f'
    end
    local by_race = {}
    local function row(race)
        local r = by_race[race] or {n = 0, m = 0, f = 0, am = 0, af = 0, list = {}}
        by_race[race] = r
        return r
    end
    local function count(r, a)
        local s = sex_of(a)
        if s == 'm' then
            r.m = r.m + 1
            if a.adult then r.am = r.am + 1 end
        elseif s == 'f' then
            r.f = r.f + 1
            if a.adult then r.af = r.af + 1 end
        end
    end
    for _, a in ipairs(animals) do
        local r = row(a.race)
        r.n = r.n + 1
        count(r, a)
        table.insert(r.list, a)
    end
    for _, a in ipairs(mates or {}) do
        if a.race ~= nil and by_race[a.race] then count(by_race[a.race], a) end
    end
    local function b(v) return v and true or false end
    local best, best_race, best_r, best_pair
    for race, r in pairs(by_race) do
        for _, a in ipairs(r.list) do
            local s = sex_of(a)
            -- the kind's last male (or female) while it has the other sex: never
            local last = (s == 'm' and r.m == 1 and r.f >= 1) or (s == 'f' and r.f == 1 and r.m >= 1)
            if not last then
                -- an adult pair left (when the kind had one), or no adult pair to break
                local am, af = r.am, r.af
                if a.adult and s == 'm' then am = am - 1 elseif a.adult and s == 'f' then af = af - 1 end
                local pair = not (r.am >= 1 and r.af >= 1) or (am >= 1 and af >= 1)
                local better = best == nil
                if not better then
                    if b(a.kept) ~= b(best.kept) then better = not a.kept
                    elseif pair ~= best_pair then better = pair
                    elseif b(a.adult) ~= b(best.adult) then better = a.adult == true
                    elseif r.n ~= best_r.n then better = r.n > best_r.n
                    elseif (a.born or 0) ~= (best.born or 0) then better = (a.born or 0) < (best.born or 0)
                    else better = a.id < best.id end
                end
                if better then best, best_race, best_r, best_pair = a, race, r, pair end
            end
        end
    end
    if not best then return nil end
    return best, best_race, best_r.n
end

-- (X2, V4) an animal that breeds but is never taken for a mood (a pet, a war
-- or hunting animal, a named one): {race, male, female, adult}, for the pairs
local function mate_row(u)
    local r = df.creature_raw.find(u.race)
    local m, f, ad = false, nil, false
    pcall(function() m = dfhack.units.isMale(u) == true end)
    if not m then pcall(function() f = dfhack.units.isFemale(u) == true end) end
    pcall(function() ad = dfhack.units.isAdult(u) == true end)
    return {race = r and r.creature_id or tostring(u.race), male = m, female = f, adult = ad}
end

function act_slaughter_one(a)
    local cands, marked = {}, 0
    -- (R1 g6) for a strange mood (mood_unit, or mood = true): any spare tame
    -- animal (slaughter_pick_mood), young and the AI's kept ones included
    local for_mood = a.mood_unit ~= nil or a.mood == true
    -- (0.105.51) the cats and breeders the AI keeps: a list of ids now, no nickname (lua/ai-herd.lua)
    local okk, kept = pcall(function() return reqscript('ai-herd').kept_all() end)
    kept = okk and type(kept) == 'table' and kept or {}
    for _, u in ipairs(df.global.world.units.active) do
        local ok, fit, is_kept = pcall(function()
            if not dfhack.units.isAnimal(u) or not dfhack.units.isFortControlled(u) or dfhack.units.isDead(u) then return false end
            if u.flags2.slaughter then marked = marked + 1 return false end
            if dfhack.units.isPet(u) or dfhack.units.isWar(u) or dfhack.units.isHunter(u) then return false end
            if u.flags1.caged then return false end
            if (u.name.nickname or '') == 'Mouser' then return false end      -- (0.104.168) a cat the AI keeps
            local ai_kept = kept[u.id] == true or (u.name.nickname or '') == 'Breeder'
            if for_mood then
                -- (R1 g6) a named animal is the player's: never, not even for a mood
                local named = false
                pcall(function() named = u.name.has_name == true end)
                if named or ((u.name.nickname or '') ~= '' and not ai_kept) then return false end
                return true, ai_kept
            end
            if kept[u.id] then return false end                                -- (0.105.51) kept by the AI
            if (u.name.nickname or '') == 'Breeder' then return false end     -- (0.105.47) a breeder (lua/ai-herd.lua)
            if not dfhack.units.isAdult(u) then return false end
            return true
        end)
        if ok and fit then
            local race = df.creature_raw.find(u.race)
            local born = 0
            pcall(function() born = u.birth_year * 403200 + u.birth_time end)
            local adult = true
            local female
            if for_mood then
                local oka, ad = pcall(dfhack.units.isAdult, u)
                adult = oka and ad == true
                -- (X2, V4) neither sex (female false, male false) is no one's mate
                if not dfhack.units.isMale(u) then
                    local okf, fe = pcall(dfhack.units.isFemale, u)
                    if okf and type(fe) == 'boolean' then female = fe end
                end
            end
            table.insert(cands, {id = u.id, unit = u, race = race and race.creature_id or tostring(u.race),
                                 male = dfhack.units.isMale(u), female = female, born = born, adult = adult,
                                 kept = is_kept == true})
        end
    end
    if marked > 0 then return {ok = false, rejected = true, waiting = true, error = ('%d animal(s) already wait for the butcher'):format(marked)} end
    local pick, race, n
    if for_mood then
        -- (X2, V4) the animals never taken that still breed (pets, war and
        -- hunting animals, named ones; not caged) count for the pairs
        local mates, is_cand = {}, {}
        for _, c in ipairs(cands) do is_cand[c.id] = true end
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function()
                if is_cand[u.id] or u.flags1.caged or not dfhack.units.isAnimal(u)
                        or not dfhack.units.isFortControlled(u) or dfhack.units.isDead(u) then return end
                table.insert(mates, mate_row(u))
            end)
        end
        pick, race, n = slaughter_pick_mood(cands, mates)
        if not pick then
            return {ok = false, rejected = true, error = 'no tame animal to spare even for a strange mood (only pets, war or ' ..
                    'hunting animals, named or caged ones, or a kind\'s last breeding pair)'}
        end
    else
        pick, race, n = slaughter_pick(cands, a.oldest == true)
    end
    if not pick then return {ok = false, rejected = true, error = 'no spare tame animal (three or more of a kind, adult, no pet or war animal)'} end
    local out = {ok = true, race = race, of = n, unit_id = pick.id, dry_run = a.dry_run or nil,
                 oldest = a.oldest == true or nil, mood_unit = a.mood_unit,
                 young = (for_mood and not pick.adult) or nil, kept = (for_mood and pick.kept) or nil}
    if a.dry_run then return out end
    pick.unit.flags2.slaughter = true
    return out
end

-- (0.104.8) Instruments for the tavern and temples (DF 50 builds most from
-- parts made at several workshops, then assembled): DFHack's `instruments`
-- tool lists what the fort can make and orders an instrument with all its
-- parts. A hand-held one (they're kept in the location's chest), the fewest
-- parts first. Pure pick, then the action.
function instrument_pick(listed, defs)
    local best
    for _, d in ipairs(defs) do
        local placed = false
        for _, f in ipairs(d.flags or {}) do if f == 'PLACED_AS_BUILDING' then placed = true end end
        if not placed and listed[(d.name or ''):lower()] then
            if not best or (d.pieces or 0) < (best.pieces or 0)
                    or ((d.pieces or 0) == (best.pieces or 0) and d.name < best.name) then
                best = d
            end
        end
    end
    return best
end

function act_order_instrument(a)
    local n = int_in(a.amount or 2, 1, 10)
    if not n then return reject('order_instrument needs amount 1-10') end
    if not dfhack.findScript('instruments') then
        return {ok = false, error = 'DFHack has no instruments script in this version'}
    end
    local out, rv = dfhack.run_command_silent('instruments', 'list')
    if rv ~= CR_OK then return {ok = false, error = 'instruments list failed: ' .. tostring(out):sub(1, 120)} end
    local text = tostring(out):lower()
    -- the raws' own names (the tool lists and orders by them; accents and all)
    local defs = {}
    pcall(function()
        for _, d in ipairs(df.global.world.raws.itemdefs.instruments) do
            local e = {name = d.name, pieces = 0, flags = {}}
            pcall(function() e.pieces = #d.pieces end)
            pcall(function() if d.flags.PLACED_AS_BUILDING then e.flags = {'PLACED_AS_BUILDING'} end end)
            table.insert(defs, e)
        end
    end)
    local listed = {}
    for _, d in ipairs(defs) do
        local nm = (d.name or ''):lower()
        if nm ~= '' and text:find(nm, 1, true) then listed[nm] = true end
    end
    local pick = instrument_pick(listed, defs)
    if not pick then return {ok = false, rejected = true, error = 'no hand-held instrument the fort can make'} end
    local res = {ok = true, instrument = txt(pick.name), pieces = pick.pieces, amount = n, dry_run = a.dry_run or nil}
    if a.dry_run then return res end
    -- (0.104.68) what the tool made: 105 orders on Enxah left no order in the
    -- report; the tool's own words and the work orders before and after
    local before = #df.global.world.manager_orders.all
    local had = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do had[o.id] = true end
    local o2, rv2 = dfhack.run_command_silent('instruments', 'order', pick.name, tostring(n))
    if rv2 ~= CR_OK then return {ok = false, error = 'instruments order failed: ' .. tostring(o2):sub(1, 160)} end
    res.orders_made = #df.global.world.manager_orders.all - before
    -- (0.104.69) the tool's orders are the AI's: counted as queued, cancelled
    -- if stuck (Enxah: 31 instrument orders piled up, none counted)
    pcall(function()
        local data = ai_orders()
        for _, o in ipairs(df.global.world.manager_orders.all) do
            if not had[o.id] then data.ids[tostring(o.id)] = true end
        end
        save_ai_orders(data)
    end)
    res.report = txt(tostring(o2 or ''):gsub('%s+$', ''):sub(1, 300))
    if res.orders_made <= 0 then
        res.ok, res.rejected = false, true
        res.error = 'the instruments tool made no work order for ' .. txt(pick.name) .. ': ' .. res.report:sub(1, 120)
    end
    return res
end

-- (0.104.69) Instrument orders piled up (one a month asked, none counted as
-- queued): those the instruments tool made for the AI (a custom reaction
-- MAKE_<entity> IN..., recorded by act_order_instrument), not yet begun,
-- beyond `keep`, are cancelled. (0.105.33) Only the AI's own: an instrument
-- the player orders at DF's work-order screen has the same reaction and is
-- neither adopted nor cancelled.
function act_trim_instrument_orders(a)
    local keep = int_in(a.keep or 1, 0, 10)
    if not keep then return reject('trim_instrument_orders: keep 0-10') end
    local all = df.global.world.manager_orders.all
    local ours = ai_orders().ids
    local mine, cancelled = {}, 0
    for _, o in ipairs(all) do
        local okr, r = pcall(function() return o.reaction_name end)
        if okr and type(r) == 'string' and r:match('^MAKE_ENT%d+ IN') and ours[tostring(o.id)] then
            table.insert(mine, o)
        end
    end
    -- begun ones (some made) first: they are kept
    table.sort(mine, function(x, y)
        local bx, by = x.amount_left < x.amount_total, y.amount_left < y.amount_total
        if bx ~= by then return bx end
        return x.id < y.id
    end)
    for i, o in ipairs(mine) do
        if i > keep and o.amount_left == o.amount_total then
            if not a.dry_run then
                local r = act_cancel_work_order({order_id = o.id})
                if r and r.ok then cancelled = cancelled + 1 end
            else
                cancelled = cancelled + 1
            end
        end
    end
    return {ok = true, found = #mine, cancelled = cancelled, kept = #mine - cancelled, dry_run = a.dry_run or nil}
end

-- (0.104.10) free time: an "everybody" work detail narrowed to a crew, or back (lua/ai-labor.lua)
function act_narrow_detail(a)
    if a.job ~= 'farming' and a.job ~= 'gathering' then return reject('narrow_detail: job must be farming or gathering') end
    if a.widen == true then return reqscript('ai-labor').widen(a.job, a.dry_run == true) end
    local n = int_in(a.keep or 5, 1, 30)
    if not n then return reject('narrow_detail needs keep 1-30') end
    return reqscript('ai-labor').narrow(a.job, n, a.dry_run == true, txt)
end

-- (0.104.166) a detail cut back to the few the job needs (lua/ai-labor.lua trim)
function act_trim_labor(a)
    if a.job ~= 'fishing' then return reject('trim_labor: job must be fishing') end
    local n = int_in(a.keep == nil and 2 or a.keep, 0, 30)
    if not n then return reject('trim_labor needs keep 0-30') end
    return reqscript('ai-labor').trim(a.job, n, a.dry_run == true, txt)
end

-- (0.104.139, phase 11) Fights among the fort's own: DF's conflicts drag
-- friends and kin in and turn lethal (Teacheroar: 460 citizens killed by
-- citizens in five days, 356 strangled, 87% within a minute of another
-- death, none of it a crime). DFHack's fix/loyaltycascade (51.11+) takes the
-- citizens out of their conflicts and clears their enemy marks.
function act_break_fights(a)
    if not dfhack.findScript('fix/loyaltycascade') then
        return {ok = false, rejected = true, error = 'this DFHack has no fix/loyaltycascade'}
    end
    if a.dry_run then return {ok = true, dry_run = true} end
    local output, rv = dfhack.run_command_silent('fix/loyaltycascade')
    output = tostring(output or ''):gsub('%s+$', '')
    if rv ~= CR_OK then return {ok = false, error = 'fix/loyaltycascade failed: ' .. output:sub(1, 200)} end
    local n = 0
    for _ in output:gmatch('[^\n]+') do n = n + 1 end
    return {ok = true, lines = n, report = output:sub(1, 400)}
end

-- (0.104.0) Old remains rot away when the game runs slowly from too many
-- items: DFHack's deteriorate for non-entombed corpses and body parts nobody
-- can craft with (its defaults). Usable parts (bones, hair, wool) and food are
-- left alone; entombed dead are never touched. Stays on in this save.
-- (0.105.33 fix) The fort's dead still lying unburied, whatever their race:
-- a corpse (not in a coffin or tomb, not removed) whose unit is of the
-- fort's civilisation, or of the fort's race when its unit can't be found.
-- get_dead's `unburied` counts the fort's race only (a goblin or elf citizen
-- waiting for burial didn't stop the one pass). nil when unreadable.
-- (0.105.36) animals and visitors of the civ are left out: a dead cat on the
-- refuse pile stopped the corpse pass for good.
function unburied_citizens()
    local ok, n = pcall(function()
        local race, civ = df.global.plotinfo.race_id, df.global.plotinfo.civ_id
        local c = 0
        for _, it in ipairs(df.global.world.items.other.CORPSE) do
            if not it.flags.in_building and not it.flags.removed then
                local oku, du = pcall(df.unit.find, it.unit_id)
                local ours
                if oku and du then
                    -- (0.105.36, D6) the fort's people only: not its dead pets and
                    -- livestock, nor a dead merchant, guard, envoy or visitor of its civ
                    local function is(f)
                        local okf, r = pcall(f, du)
                        return okf and r == true
                    end
                    local U = dfhack.units
                    ours = du.civ_id == civ and not is(U.isAnimal) and not is(U.isMerchant)
                        and not is(U.isDiplomat) and not is(U.isVisitor)
                else ours = it.race == race end
                if ours then c = c + 1 end
            end
        end
        return c
    end)
    return ok and n or nil
end

function act_prune_remains(a)
    if not dfhack.findScript('deteriorate') then
        return {ok = false, error = 'DFHack has no deteriorate script in this version'}
    end
    -- (0.104.115) and, asked for by name: worn clothes thrown on the floor
    -- ('clothes': only on the ground and worn, never armour) and usable parts
    -- ('usable-parts': Teacheroar held 7,227 butchered bones and shells on the
    -- ground, 6,627 dead creatures still on the map's books)
    -- (0.105.33) corpses are never left on a timer: deteriorate's corpses
    -- category takes the fort's own dead too ("this includes former members
    -- of your fort"), and once on it stayed on, so a citizen waiting for a
    -- coffin rotted away unburied (a ghost). Corpses go in one pass now, and
    -- only while no citizen lies unburied; the timer keeps the parts and
    -- clothes only (deteriorate's own default has corpses on: turned off).
    -- (0.105.33 fix) keep = {'usable-parts'}: only take the bones and shells off
    -- the timer (an earlier prune put them on, and it stays on in the save: a
    -- strange mood's bone or the fort's bone reserve would rot away)
    if type(a.keep) == 'table' then
        local keep = {}
        for _, c in ipairs(a.keep) do
            if c == 'usable-parts' or c == 'clothes' then table.insert(keep, c) end
        end
        if #keep == 0 then return {ok = false, error = 'prune_remains keep: nothing to keep'} end
        if a.dry_run then return {ok = true, dry_run = true, kept = keep} end
        local out, rv = dfhack.run_command_silent('deteriorate', 'disable', table.concat(keep, ','))
        if rv ~= CR_OK then
            return {ok = false, error = 'deteriorate failed: ' .. tostring(out):sub(1, 160)}
        end
        return {ok = true, kept = keep}
    end
    local cats = {'unusable-parts'}
    for _, c in ipairs(type(a.extra) == 'table' and a.extra or {}) do
        if c == 'clothes' or c == 'usable-parts' then table.insert(cats, c) end
    end
    -- (0.105.33 fix) every citizen's corpse counted, not the fort's race only
    local unburied = unburied_citizens()
    local corpses_now = unburied == 0
    if a.dry_run then
        return {ok = true, dry_run = true, categories = cats, corpses_now = corpses_now,
                unburied = unburied}
    end
    local out, rv = dfhack.run_command_silent('deteriorate', 'disable', 'corpses')
    if rv ~= CR_OK then
        return {ok = false, error = 'deteriorate failed: ' .. tostring(out):sub(1, 160)}
    end
    out, rv = dfhack.run_command_silent('deteriorate', 'enable', table.concat(cats, ','))
    if rv ~= CR_OK then
        return {ok = false, error = 'deteriorate failed: ' .. tostring(out):sub(1, 160)}
    end
    out, rv = dfhack.run_command_silent('enable', 'deteriorate')
    if rv ~= CR_OK then
        return {ok = false, error = 'enable deteriorate failed: ' .. tostring(out):sub(1, 160)}
    end
    local res = {ok = true, categories = cats, said = tostring(out):sub(1, 200)}
    if corpses_now then
        local o2, rv2 = dfhack.run_command_silent('deteriorate', 'now', 'corpses')
        res.corpses = rv2 == CR_OK and tostring(o2):gsub('%s+$', ''):sub(1, 120)
            or ('the one pass failed: ' .. tostring(o2):sub(1, 120))
    else
        res.corpses = unburied and ('left: %d citizen(s) wait for burial'):format(unburied)
            or 'left: the dead could not be counted'
    end
    return res
end

-- An office filled by the AI (lua/ai-nobles.lua): manager, bookkeeper,
-- broker, chief medical dwarf; read back through DFHack, undone if unseen.
function act_appoint(a)
    if type(a.office) ~= 'string' then return reject('appoint needs office') end
    return reqscript('ai-nobles').appoint(a.office, a.dry_run == true, txt)
end

-- A new squad, led by an appointed militia commander or captain (lua/ai-military.lua).
function act_make_squad(a)
    return reqscript('ai-military').make_squad(a.dry_run == true, txt)
end

-- A vein of the metal the fort needs marked for digging (lua/ai-industry.lua).
function act_mine_ore(a)
    if type(a.metal) ~= 'string' or not a.metal:match('^[A-Z_]+$') then return reject('mine_ore needs metal') end
    local n = int_in(a.count or 40, 1, 80)       -- (0.105.9) 80: Mining's top (E asked 80, refused 30 times)
    if not n then return reject('mine_ore needs count 1-80') end
    return reqscript('ai-industry').mine(a.metal, n, a.dry_run == true)
end

-- Take down a gate the AI built at an entrance that wasn't one (lua/ai-gates.lua).
function act_clear_gate(a)
    local x, y, z = whole_number(a.x), whole_number(a.y), whole_number(a.z)
    if not (x and y and z) then return reject('clear_gate needs x, y, z') end
    local pieces = type(a.pieces) == 'table' and a.pieces or nil
    return reqscript('ai-gates').clear_gate(x, y, z, pieces, a.dry_run == true)
end

-- Goods to the depot for a caravan (lua/ai-trade.lua); the trade is yours.
function act_bring_goods(a)
    -- (0.104.78) up to 120 at a time: the finished-goods piles full of crafts
    local n = int_in(a.count or 40, 1, 120)
    if not n then return reject('bring_goods needs count 1-120') end
    return reqscript('ai-trade').bring(n, a.dry_run == true, txt, a.keep_treasures == true, a.keep_trinkets == true)
end

-- (0.103.8) The fort's goods left in the depot after the caravans: back out.
function act_unload_depot(a)
    local n = int_in(a.max or 50, 1, 200)
    if not n then return reject('unload_depot needs max 1-200') end
    return reqscript('ai-trade').unload(n, a.dry_run == true, txt)
end

-- A deal ticked on the open trade screen, and the Trade button pressed if
-- asked and calibrated (lua/ai-trade.lua). wants: {{key, count}} in order.
function act_trade_deal(a)
    local wants = {}
    for _, w in ipairs(type(a.wants) == 'table' and a.wants or {}) do
        local n = int_in(w.count, 1, 500)
        if type(w.key) ~= 'string' or not n then return reject('trade_deal wants {key, count 1-500}') end
        table.insert(wants, {key = w.key, count = n})
    end
    if #wants == 0 then return reject('trade_deal needs wants') end
    -- (r2 h5) what any fort can use, bought only when none of the wants is on sale
    local extra = {}
    for _, w in ipairs(type(a.extra) == 'table' and a.extra or {}) do
        local n = int_in(w.count, 1, 500)
        if type(w.key) ~= 'string' or not n then return reject('trade_deal extra {key, count 1-500}') end
        table.insert(extra, {key = w.key, count = n})
    end
    local margin = tonumber(a.margin) or 1.2
    if margin < 1.0 or margin > 3 then return reject('trade_deal margin must be 1.0-3') end
    local T = reqscript('ai-trade')
    -- (0.100, security pass) a trade screen the player opened is the
    -- player's: the AI neither ticks goods there nor presses Trade
    if not a.dry_run and a.force ~= true and not T.opened_by_ai() then
        return reject('the player opened this trade screen: the AI leaves the deal to them')
    end
    local r = T.deal(wants, margin, a.dry_run == true, txt, #extra > 0 and extra or nil)
    -- nothing to buy (or turned down before): the screen closed, if asked
    if r.rejected and a.close == true and not a.dry_run and T.opened_by_ai() then
        local c = T.close_screen()
        r.closed = c.closed
    end
    -- (r2 h5) pressed too where no place is known: press() looks for the
    -- Trade label by its word (every fort's guess was retired)
    if r.ok and not r.waiting and not a.dry_run and a.press == true and (r.calibrated or r.can_search) then
        local p = T.press('Trade', txt)
        r.press = p
        r.answer, r.traded, r.counter, r.closed = p.answer, p.traded, p.counter, p.closed
        -- not pressed at all (no Trade button found): the AI's screen closed
        -- (time stands still while it is open), this caravan left to the player
        if p.rejected and not p.pressed and not p.closed and a.close == true and T.opened_by_ai() then
            local c = T.close_screen()
            r.closed = c.closed
        end
    end
    return r
end

-- Recreational crafting turned on at a Craftsdwarf's workshop (lua/ai-society.lua).
function act_idle_crafting(a)
    return reqscript('ai-society').idle_crafting(a.dry_run == true)
end

-- (0.105.38) the map's width (at least 80): a far source's reach at most
-- (the old fixed caps were 80 and 100 tiles)
function map_width()
    local ok, w = pcall(function() return (dfhack.maps.getTileSize()) end)
    return math.max(80, ok and math.tointeger(w) or 80)
end

-- (0.105.38) the brain's water_far_reach for the cistern's and the shore well's far sources
-- (none or below 0: the map's width; (review) 0: far sources off)
function far_reach_of(a)
    local r = whole_number(a.far_reach)
    if whole_number(a.job_max) == 0 then r = 0 end    -- (0.105.38 review) water_job_max 0: no far work either
    pcall(function()
        local B = reqscript('ai-builder')
        B.CISTERN_FAR_REACH = r
        B.SHORE_FAR_REACH = r
    end)
end

-- Survey the water near the fort (lua/ai-water.lua): kept in the save. In
-- slices: each call scans for at most ~0.15 s and says "done = false" until
-- the survey is finished; then the cistern plan, one fort level a call
-- (the lag pass: the whole survey froze the game ~1.4 s, the plan up to 3 s).
WATER_PLAN = WATER_PLAN or nil
function act_survey_water(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    local W = reqscript('ai-water')
    local now = abs_tick()
    if not WATER_PLAN then
        -- (r2h1) the brain's slice length while scanning (capped in ai-water)
        local r = W.scan_step(now, W.slice_seconds and W.slice_seconds(a.seconds) or nil)
        if not r.ok then return r end
        if not r.done then return {ok = true, done = false, scanning = true, left = r.left} end
        WATER_PLAN = {i = 1}
        return {ok = true, done = false, planning = true}
    end
    local B = reqscript('ai-builder')
    far_reach_of(a)
    local i = WATER_PLAN.i
    -- (0.105.3) Hammerstirred (2 Nov): the brain's cistern_tunnel_max (the pool 53-66 tiles off)
    local tun = whole_number(a.tunnel)
    -- (r2h1) after the busiest levels, one call for the next CISTERN_RIVER_LEVELS
    -- fort levels when the survey found a river: its shaft way needs a cistern
    -- 1-8 levels under it (region4's at z160, the dwarves' busiest higher up)
    local nlev = B.CISTERN_LEVELS or 6
    local last_i = i
    if i > nlev then last_i = nlev + (B.CISTERN_RIVER_LEVELS or 10) end
    local okp, plan, why = pcall(B.plan_cistern, i, last_i, {tunnel = tun and math.max(2, math.min(tun, map_width())) or nil})
    if okp and plan and (not WATER_PLAN.best or plan.score < WATER_PLAN.best.score) then WATER_PLAN.best = plan end
    if okp and not plan and why then WATER_PLAN.why = WATER_PLAN.why or why end
    if not okp then WATER_PLAN.why = tostring(plan):sub(1, 160) end
    local river_pass = false
    if i == nlev and B.cistern_rivers then
        local okr, rv = pcall(B.cistern_rivers)
        river_pass = okr and rv ~= nil
    end
    if i < nlev or river_pass then
        WATER_PLAN.i = i + 1
        return {ok = true, done = false, planning = true, level = i}
    end
    local r = W.last() or {ok = true}
    r.cistern = WATER_PLAN.best or {none = true, why = WATER_PLAN.why or 'no still, fresh water on the level under a fort level'}
    WATER_PLAN = nil
    pcall(dfhack.persistent.saveSiteData, 'ai-overseer/water', r)
    local kinds = {}
    for _, bd in ipairs(r.bodies or {}) do table.insert(kinds, ('%s %d'):format(bd.kind, bd.tiles)) end
    return {ok = true, done = true, bodies = kinds, aquifer = r.aquifer, magma = r.magma, cistern = r.cistern}
end

-- The cistern (lua/ai-builder.lua): one step of building it, or keeping it filled.
function act_cistern_step(a)
    if a.shut == true then return reqscript('ai-builder').cistern_shut(a.dry_run == true) end
    -- (0.105.35) retired by the AI (leaked twice, a gap it can't close, a lever that won't link), or relinked
    if a.retire == true then
        return reqscript('ai-builder').cistern_retire(a.dry_run == true, type(a.why) == 'string' and a.why:sub(1, 120) or nil)
    end
    if a.relink == true then return reqscript('ai-builder').cistern_relink(a.dry_run == true) end
    -- (0.104.145) what the brain knows that weighs the source: the climate
    -- freezes, a danger in the caverns
    local prefs = type(a.prefs) == 'table' and {freezes = a.prefs.freezes == true,
                                               cavern_danger = a.prefs.cavern_danger == true} or nil
    -- (0.105.3) the tunnel's reach, as the survey planned it (Hammerstirred's pool 53-66 tiles off)
    local tun = whole_number(a.tunnel)
    far_reach_of(a)
    return reqscript('ai-builder').cistern_step(a.dry_run == true, prefs, tun and math.max(2, math.min(tun, map_width())) or nil)
end

-- (0.105.0) Water works and magma (lua/ai-waterworks.lua): one step of the
-- moat, the pump stack, the muddied farm level or a magma workshop, or its
-- floodgate shut at once (shut) or the work retired.
function act_water_work(a)
    local kinds = reqscript('ai-waterworks').KINDS
    if not kinds[a.kind] then return reject('water_work: kind is moat, pump, irrigation, magma or power') end
    if a.shop ~= nil and not reqscript('ai-waterworks').MAGMA_SHOPS[a.shop] then
        return reject('water_work: shop is MagmaForge, MagmaSmelter or MagmaGlassFurnace')
    end
    -- (0.105.37 E3) the power's source: a water wheel or a windmill (nil: a wheel if it can)
    if a.source ~= nil and a.source ~= 'wheel' and a.source ~= 'windmill' then
        return reject('water_work: source is wheel or windmill')
    end
    return reqscript('ai-waterworks').step(a.kind, {dry_run = a.dry_run == true, shut = a.shut == true,
        retire = a.retire == true, shop = a.shop, plain = a.plain == true, reopen = a.reopen == true,
        source = a.source,
        -- (0.105.38) far sources: the brain's reach (tiles; none or below 0: the
        -- map's width; 0: far sources off), the job's size at most (0: no far
        -- work), a long dig's segment; and the cavern switch's answer for magma
        -- whose way opens a cavern
        far_reach = whole_number(a.far_reach), job_max = whole_number(a.job_max), segment = whole_number(a.segment),
        open_caverns = a.open_caverns == true,
        -- (r9, A4 19) the leak watch's recheck passed on by its own flag (it
        -- worked only because the brain's why starts "recheck")
        recheck = a.recheck == true,
        why = type(a.why) == 'string' and a.why:sub(1, 120) or nil})
end

-- (0.84) a vacant post at a location (hospital staff, scribes, the tavern keeper)
function act_staff_location(a)
    local id = whole_number(a.location_id)
    if not id or type(a.post) ~= 'string' then return reject('staff_location needs location_id and post') end
    return reqscript('ai-society').staff_location(id, a.post, a.dry_run == true, txt)
end

-- (0.92) give a hall still being dug to another petition: project_id and
-- one of profession, deity_hf, religion
function act_retarget_hall(a)
    local id = whole_number(a.project_id)
    if not id then return reject('retarget_hall needs project_id') end
    local t = {}
    if a.profession ~= nil then
        if type(a.profession) ~= 'string' or df.profession[a.profession] == nil then return reject('unknown profession') end
        t.profession = a.profession
    elseif a.deity_hf ~= nil then
        t.deity_hf = whole_number(a.deity_hf)
        if not t.deity_hf or not df.historical_figure.find(t.deity_hf) then return reject('no such deity') end
    elseif a.religion ~= nil then
        t.religion = whole_number(a.religion)
        if not t.religion or not df.historical_entity.find(t.religion) then return reject('no such religion') end
    else
        return reject('retarget_hall needs profession, deity_hf or religion')
    end
    return reqscript('ai-builder').retarget_hall(id, t, a.dry_run == true)
end

-- (0.89) answer a temple or guildhall petition: id, accept (true/false)
function act_answer_petition(a)
    if type(a.accept) ~= 'boolean' then return reject('answer_petition needs id (or ids) and accept true|false') end
    -- (0.105.9) ids: up to 25 at once (old residency petitions by the hundred)
    if type(a.ids) == 'table' then
        local ids = {}
        for _, v in ipairs(a.ids) do
            local n = whole_number(v)
            if not n then return reject('answer_petition: ids are whole numbers') end
            table.insert(ids, n)
        end
        if #ids == 0 or #ids > 25 then return reject('answer_petition needs 1-25 ids') end
        local out = {ok = true, answered = 0, refused = {}, accepted = a.accept or nil, dry_run = a.dry_run or nil}
        for _, n in ipairs(ids) do
            local r = answer_petition(n, a.accept, a.dry_run == true)
            if r.ok then out.answered = out.answered + 1
            else table.insert(out.refused, {id = n, error = r.error}) end
        end
        if #out.refused == 0 then out.refused = nil end
        out.ok = out.answered > 0
        if not out.ok then out.error = 'no petition answered'; out.rejected = true end
        return out
    end
    local id = whole_number(a.id)
    if not id then return reject('answer_petition needs id (or ids) and accept true|false') end
    return answer_petition(id, a.accept, a.dry_run == true)
end

-- (0.88) alerts: {TYPE = ticks | false, default = ticks}; max 1-100
function act_dismiss_alerts(a)
    local n = whole_number(a.max)
    if not n or n < 1 or n > 100 then return reject('dismiss_alerts needs max 1-100') end
    if type(a.ages) ~= 'table' then return reject('dismiss_alerts needs ages {TYPE = ticks, default = ticks}') end
    local ages = {}
    for k, v in pairs(a.ages) do
        if type(k) ~= 'string' or not (k == 'default' or df.announcement_alert_type[k] ~= nil) then
            return reject('unknown alert type: ' .. tostring(k))
        end
        local t = whole_number(v)
        if v == false then ages[k] = false
        elseif t and t >= 0 then ages[k] = t
        else return reject('alert ages are whole ticks or false') end
    end
    return reqscript('ai-reports').dismiss_alerts(ages, n, a.dry_run == true)
end
