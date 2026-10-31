-- What fills the map (0.104.113): a fort of 300 dwarves after 38 years
-- saved for minutes and ran at 18 FPS with 6,500 creatures and 42,000 items
-- on the map. Read only: creatures by kind and race, items by type and state.
--@ module = true

local function race_name(u)
    local ok, n = pcall(function() return df.creature_raw.find(u.race).creature_id end)
    return ok and n or tostring(u.race)
end

local function top(counts, n)
    local list = {}
    for k, v in pairs(counts) do table.insert(list, {k, v}) end
    table.sort(list, function(a, b) return a[2] > b[2] or (a[2] == b[2] and a[1] < b[1]) end)
    local out = {}
    for i = 1, math.min(n, #list) do out[i] = {name = list[i][1], n = list[i][2]} end
    return out
end

function units()
    local by = {total = 0, citizens = 0, dead = 0, tame = 0, wild = 0, hostile = 0, visitors = 0, caged = 0,
                offsite = 0, other = 0}
    local races, dead_races, tame_races, wild_races = {}, {}, {}, {}
    for _, u in ipairs(df.global.world.units.active) do
        by.total = by.total + 1
        local r = race_name(u)
        local function is(f) local ok, v = pcall(f, u) return ok and v end
        if is(dfhack.units.isDead) or u.flags2.killed then
            by.dead = by.dead + 1
            dead_races[r] = (dead_races[r] or 0) + 1
        elseif not is(dfhack.units.isActive) then
            by.offsite = by.offsite + 1
        elseif is(dfhack.units.isCitizen) then
            by.citizens = by.citizens + 1
        elseif u.flags1.caged then
            by.caged = by.caged + 1
        elseif is(dfhack.units.isTame) or is(dfhack.units.isDomesticated) then
            by.tame = by.tame + 1
            tame_races[r] = (tame_races[r] or 0) + 1
        elseif is(dfhack.units.isDanger) then
            by.hostile = by.hostile + 1
        elseif is(dfhack.units.isVisitor) or is(dfhack.units.isMerchant) or is(dfhack.units.isDiplomat) then
            by.visitors = by.visitors + 1
        elseif is(dfhack.units.isAnimal) or u.flags2.roaming_wilderness_population_source then
            by.wild = by.wild + 1
            wild_races[r] = (wild_races[r] or 0) + 1
        else
            by.other = by.other + 1
        end
        races[r] = (races[r] or 0) + 1
    end
    return {counts = by, races = top(races, 12), dead = top(dead_races, 8), tame = top(tame_races, 8),
            wild = top(wild_races, 8)}
end

function items()
    local by = {total = 0, forbidden = 0, dump = 0, rotten = 0, worn = 0, in_buildings = 0, in_containers = 0,
                on_ground = 0, owned = 0, artifacts = 0}
    local types, worn_types, ground_types = {}, {}, {}
    for _, it in ipairs(df.global.world.items.all) do
        local f = it.flags
        if not (f.garbage_collect or f.removed) then
            by.total = by.total + 1
            local t = df.item_type[it:getType()] or '?'
            types[t] = (types[t] or 0) + 1
            if f.forbid then by.forbidden = by.forbidden + 1 end
            if f.dump then by.dump = by.dump + 1 end
            if f.rotten then by.rotten = by.rotten + 1 end
            if f.owned then by.owned = by.owned + 1 end
            if f.artifact then by.artifacts = by.artifacts + 1 end
            if f.in_building or f.construction then by.in_buildings = by.in_buildings + 1
            elseif f.in_inventory or f.container or f.in_job then by.in_containers = by.in_containers + 1
            elseif f.on_ground then
                by.on_ground = by.on_ground + 1
                ground_types[t] = (ground_types[t] or 0) + 1
            end
            local okw, wear = pcall(function() return it.wear end)
            if okw and type(wear) == 'number' and wear >= 2 then
                by.worn = by.worn + 1
                worn_types[t] = (worn_types[t] or 0) + 1
            end
        end
    end
    return {counts = by, types = top(types, 15), worn = top(worn_types, 6), on_ground = top(ground_types, 10)}
end

function census()
    local t0 = os.clock()
    local oku, u = pcall(units)
    local oki, i = pcall(items)
    return {ok = true, units = oku and u or {error = tostring(u)}, items = oki and i or {error = tostring(i)},
            jobs = (function() local n, l = 0, df.global.world.jobs.list.next
                       while l do n = n + 1; l = l.next end return n end)(),
            ms = math.floor((os.clock() - t0) * 1000)}
end
