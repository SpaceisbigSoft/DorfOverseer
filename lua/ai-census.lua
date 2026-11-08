-- What fills the map (0.104.113): a fort of 300 dwarves after 38 years
-- saved for minutes and ran at 18 FPS with 6,500 creatures and 42,000 items
-- on the map. Read only: creatures by kind and race, items by type and state.
-- (0.105.3) except remove_webs (the bridge's remove_webs action), which takes
-- loose spider webs outside the fort's areas off the map.
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
                offsite = 0, other = 0, marked = 0, dead_scrubbable = 0}
    local races, dead_races, tame_races, wild_races, herd = {}, {}, {}, {}, {}
    for _, u in ipairs(df.global.world.units.active) do
        by.total = by.total + 1
        local r = race_name(u)
        local function is(f) local ok, v = pcall(f, u) return ok and v end
        if is(dfhack.units.isDead) or u.flags2.killed then
            by.dead = by.dead + 1
            dead_races[r] = (dead_races[r] or 0) + 1
            -- (0.104.158) the ones DFHack's fix/dead-units would scrub from the
            -- active list (not the fort's own race; slaughtered, nameless or
            -- of another civ; it keeps the last month's): an upper bound
            if not is(dfhack.units.isOwnRace) and (is(dfhack.units.isMarkedForSlaughter) or u.hist_figure_id == -1
                    or not is(dfhack.units.isOwnCiv)) then
                by.dead_scrubbable = by.dead_scrubbable + 1
            end
        elseif not is(dfhack.units.isActive) then
            by.offsite = by.offsite + 1
        elseif is(dfhack.units.isCitizen) then
            by.citizens = by.citizens + 1
        elseif u.flags1.caged then
            by.caged = by.caged + 1
        elseif is(dfhack.units.isTame) or is(dfhack.units.isDomesticated) then
            by.tame = by.tame + 1
            tame_races[r] = (tame_races[r] or 0) + 1
            -- (0.104.158) what each kind of livestock is: autobutcher (on, autowatch
            -- on, 2/4/2/4 a race by default) spares the named, pets, war and
            -- hunting animals, the pregnant and the brooding (DFHack 53.16 docs)
            local h = herd[r] or {n = 0, marked = 0, pet = 0, named = 0, trained = 0, kids = 0, protected = 0}
            h.n = h.n + 1
            local named = is(function(x) return x.name.has_name or (x.name.nickname or '') ~= '' end)
            local pet, marked = is(dfhack.units.isPet), is(dfhack.units.isMarkedForSlaughter)
            local trained = is(dfhack.units.isWar) or is(dfhack.units.isHunter)
            if marked then h.marked = h.marked + 1; by.marked = by.marked + 1 end
            if pet then h.pet = h.pet + 1 end
            if named then h.named = h.named + 1 end
            if trained then h.trained = h.trained + 1 end
            if not is(dfhack.units.isAdult) then h.kids = h.kids + 1 end
            if pet or named or trained then h.protected = h.protected + 1 end
            herd[r] = h
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
    -- the herd's 12 biggest kinds, with what each is
    local herd_top = {}
    for _, e in ipairs(top(tame_races, 12)) do
        local h = herd[e.name]
        h.name = e.name
        table.insert(herd_top, h)
    end
    -- slaughter jobs waiting (the butcher's backlog)
    local okj, waits = pcall(function()
        local n = 0
        local l = df.global.world.jobs.list.next
        while l do
            if l.item and l.item.job_type == df.job_type.SlaughterAnimal then n = n + 1 end
            l = l.next
        end
        return n
    end)
    if okj then by.slaughter_jobs = waits end
    return {counts = by, races = top(races, 12), dead = top(dead_races, 8), tame = top(tame_races, 8),
            wild = top(wild_races, 8), herd = herd_top}
end

-- (0.105.3) B (2 Nov): the census counted 5,992 "artifacts" among 17,471
-- items. The game's item list holds every item loaded, the world's too:
-- artifacts kept at other sites (books and scrolls written over 250 years,
-- mostly) have no place on this map. They are counted apart now (off_map,
-- artifacts_off_map); `artifacts` is the ones on this map.
local function off_map(it)
    -- getPosition: x, y, z (through the holder), or nil off the map
    local okp, x = pcall(function() return dfhack.items.getPosition(it) end)
    if okp then return type(x) ~= 'number' or x < 0 end
    local okq, x = pcall(function() return it.pos.x end)
    return okq and type(x) == 'number' and x < 0
end

---------------------------------------------------------------------------
-- (0.105.27) Forbidden items (the lock symbol): the player found them lying
-- about everywhere and nothing disposing of them. Each forbidden item is put
-- down to a reason by the ONE classifier the disposal actions use too
-- (ai-util forbidden_reason: ai, dumped, own_dead, other_dead, used_ammo,
-- unknown), so what is counted here is what the actions act on.
-- Bodies and body parts are counted apart (corpses = {own, other}) and not
-- in by_reason: no disposal action touches them (the burial and refuse
-- rules see to them), so they must not ask for one. `total` counts them.
-- And where it lies: surface / inside / caverns (one of them), and besides
-- near_danger (FORBID_DANGER_TILES of a live enemy) and unreachable (no
-- citizen's walk group reaches its tile). Folded into items()' own walk.
---------------------------------------------------------------------------
FORBID_REASONS = {'own_dead', 'used_ammo', 'other_dead', 'dumped', 'ai', 'unknown'}
FORBID_WHERE = {'surface', 'inside', 'caverns', 'near_danger', 'unreachable'}
FORBID_TOP_TYPES = 12
FORBID_DANGER_TILES = 20
FORBID_REACH_SAMPLE = 400       -- canWalkBetween checks at most (only without walk groups)

-- the fallbacks, as ai-military-gear has them, if neither module exports them
local function danger_spots_here()
    local out = {}
    local okl, active = pcall(function() return df.global.world.units.active end)
    for _, u in ipairs(okl and active or {}) do
        local ok, bad = pcall(function()
            local U = dfhack.units
            local f1 = u.flags1
            if f1 and (f1.caged or f1.chained) then return false end
            return not U.isDead(u) and (U.isDanger(u) or U.isInvader(u))
        end)
        if ok and bad then
            local okp, x, y, z = pcall(dfhack.units.getPosition, u)
            if okp and x then table.insert(out, {x = x, y = y, z = z}) end
        end
    end
    return out
end

local function near_danger_here(spots, x, y, z)
    for _, d in ipairs(spots) do
        if math.abs(d.x - x) + math.abs(d.y - y) <= FORBID_DANGER_TILES and math.abs(d.z - z) <= 3 then
            return true
        end
    end
    return false
end

-- danger_spots / near_danger: from ai-util (where they are moving), else
-- ai-military-gear, else the copy above
function danger_helpers()
    for _, name in ipairs({'ai-util', 'ai-military-gear'}) do
        local ok, m = pcall(function() return reqscript(name) end)
        if ok and (type(m) == 'table' or type(m) == 'userdata') then
            local okf, ds, nd = pcall(function() return m.danger_spots, m.near_danger end)
            if okf and type(ds) == 'function' and type(nd) == 'function' then return ds, nd, name end
        end
    end
    return danger_spots_here, near_danger_here, 'census'
end

-- the garbage dump zones: {x1, y1, x2, y2, z, b}
local function dump_zones()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            pcall(function()
                if b:getType() ~= df.building_type.Civzone then return end
                local t = df.civzone_type[b.type]
                if t == 'Dump' or t == 'GarbageDump' then
                    table.insert(out, {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z, b = b})
                end
            end)
        end
    end)
    return out
end

local function in_dump(dumps, x, y, z)
    for _, d in ipairs(dumps) do
        if z == d.z and x >= d.x1 and x <= d.x2 and y >= d.y1 and y <= d.y2 then
            -- a zone painted in a shape: its extents say which tiles of the box are in it
            local ok, inside = pcall(function()
                local r = d.b.room
                if not r or not r.extents or (r.width or 0) <= 0 then return true end
                return r.extents[(y - r.y) * r.width + (x - r.x)] ~= 0
            end)
            if not ok or inside then return true end
        end
    end
    return false
end

-- the walk groups the citizens stand in (nil: the game can't say)
local function citizen_groups()
    local ok, set, from = pcall(function()
        local s, first, any = {}, nil, false
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            first = first or u.pos
            local okg, g = pcall(dfhack.maps.getWalkableGroup, u.pos)
            if okg and type(g) == 'number' then
                any = true
                if g ~= 0 then s[g] = true end
            end
        end
        return any and s or nil, first
    end)
    if ok then return set, from end
    return nil, nil
end

local function in_stockpile(x, y, z)
    local ok, b = pcall(function() return dfhack.buildings.findAtTile(xyz2pos(x, y, z)) end)
    if not ok or not b then return false end
    local okt, sp = pcall(function() return b:getType() == df.building_type.Stockpile end)
    return okt and sp
end

-- the context built once a census (only when a forbidden item turns up):
-- the shared classifier's (ai-util forbid_context) with this module's dump
-- and stockpile tests; without ai-util every reason reads unknown
local function forbid_context()
    local okU, U = pcall(function() return reqscript('ai-util') end)
    local ctx
    if okU and U and type(U.forbid_context) == 'function' and type(U.forbidden_reason) == 'function' then
        ctx = U.forbid_context()
        ctx.U = U
    else
        ctx = {}
    end
    ctx.dumps, ctx.reach_checks = dump_zones(), 0
    ctx.in_dump = function(x, y, z) return in_dump(ctx.dumps, x, y, z) end
    ctx.in_stockpile = in_stockpile
    local ds, nd = danger_helpers()
    local oks, spots = pcall(ds)
    ctx.spots = oks and type(spots) == 'table' and spots or {}
    ctx.near = function(x, y, z)
        if #ctx.spots == 0 then return false end
        local ok, v = pcall(nd, ctx.spots, x, y, z)
        return ok and v == true
    end
    ctx.groups, ctx.from = citizen_groups()
    return ctx
end

local function new_forbidden()
    local f = {total = 0, by_type = {}, by_reason = {}, by_where = {}, metal = 0, worn = 0, valuable = 0,
               corpses = {own = 0, other = 0}}
    for _, k in ipairs(FORBID_REASONS) do f.by_reason[k] = 0 end
    for _, k in ipairs(FORBID_WHERE) do f.by_where[k] = 0 end
    return f
end

local function item_xyz(it)
    local okp, x, y, z = pcall(function() return dfhack.items.getPosition(it) end)
    if okp and type(x) == 'number' and x >= 0 then return x, y, z end
    if okp and (type(x) == 'userdata' or type(x) == 'table') then
        local okc, cx, cy, cz = pcall(function() return x.x, x.y, x.z end)
        if okc and type(cx) == 'number' and cx >= 0 then return cx, cy, cz end
    end
    local okq, qx, qy, qz = pcall(function() return it.pos.x, it.pos.y, it.pos.z end)
    if okq and type(qx) == 'number' and qx >= 0 then return qx, qy, qz end
    return nil
end

local function reachable(ctx, x, y, z)
    if ctx.groups then
        local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
        if not ok or type(g) ~= 'number' then return nil end
        return g ~= 0 and ctx.groups[g] == true
    end
    if not ctx.from or ctx.reach_checks >= FORBID_REACH_SAMPLE then return nil end
    ctx.reach_checks = ctx.reach_checks + 1
    local ok, r = pcall(dfhack.maps.canWalkBetween, ctx.from, xyz2pos(x, y, z))
    if not ok then return nil end
    return r == true
end

-- one forbidden item, counted
local function count_forbidden(fb, ctx, it, t, wear)
    fb.total = fb.total + 1
    fb.by_type[t] = (fb.by_type[t] or 0) + 1
    local f = it.flags
    if type(wear) == 'number' and wear >= 2 then fb.worn = fb.worn + 1 end
    local okq, q = pcall(function() return it:getQuality() end)
    if f.artifact or (okq and type(q) == 'number' and q >= 5) then fb.valuable = fb.valuable + 1 end
    local okm, metal = pcall(function()
        local mi = dfhack.matinfo.decode(it)
        return mi and mi.material and mi.material.flags.IS_METAL and true or false
    end)
    if okm and metal then fb.metal = fb.metal + 1 end
    local x, y, z = item_xyz(it)
    if x then
        local okh, des = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
        if okh and des and (des.feature_global or des.feature_local) then fb.by_where.caverns = fb.by_where.caverns + 1
        elseif okh and des and des.outside then fb.by_where.surface = fb.by_where.surface + 1
        else fb.by_where.inside = fb.by_where.inside + 1 end
        if ctx.near(x, y, z) then fb.by_where.near_danger = fb.by_where.near_danger + 1 end
        if reachable(ctx, x, y, z) == false then fb.by_where.unreachable = fb.by_where.unreachable + 1 end
    end
    local reason, corpse = 'unknown', nil
    if ctx.U then
        local ok, r, c = pcall(ctx.U.forbidden_reason, it, ctx, t, x, y, z)
        if ok and type(r) == 'string' and fb.by_reason[r] ~= nil then reason, corpse = r, c end
    end
    if corpse == 'own' or corpse == 'other' then
        fb.corpses[corpse] = fb.corpses[corpse] + 1
    else
        fb.by_reason[reason] = fb.by_reason[reason] + 1
    end
end

local function top_map(counts, n)
    local out = {}
    for _, e in ipairs(top(counts, n)) do out[e.name] = e.n end
    return out
end

function items()
    local by = {total = 0, forbidden = 0, dump = 0, rotten = 0, worn = 0, in_buildings = 0, in_containers = 0,
                on_ground = 0, owned = 0, artifacts = 0, off_map = 0, artifacts_off_map = 0}
    local types, worn_types, ground_types = {}, {}, {}
    -- (0.105.27) the forbidden ones, by type, reason and where
    local fb, fctx = new_forbidden(), nil
    for _, it in ipairs(df.global.world.items.all) do
        local f = it.flags
        if not (f.garbage_collect or f.removed) then
            by.total = by.total + 1
            local t = df.item_type[it:getType()] or '?'
            types[t] = (types[t] or 0) + 1
            local away = off_map(it)
            if away then by.off_map = by.off_map + 1 end
            if f.forbid then by.forbidden = by.forbidden + 1 end
            if f.dump then by.dump = by.dump + 1 end
            if f.rotten then by.rotten = by.rotten + 1 end
            if f.owned then by.owned = by.owned + 1 end
            if f.artifact then
                if away then by.artifacts_off_map = by.artifacts_off_map + 1
                else by.artifacts = by.artifacts + 1 end
            end
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
            if f.forbid and not away then
                fctx = fctx or forbid_context()
                pcall(count_forbidden, fb, fctx, it, t, okw and wear or nil)
            end
        end
    end
    fb.by_type = top_map(fb.by_type, FORBID_TOP_TYPES)
    if fctx and not fctx.groups and fctx.reach_checks > 0 then fb.reach_sampled = fctx.reach_checks end
    -- (0.104.116) spider webs (cavern silk left where the spiders spun it)
    local okw, webs = pcall(function() return #df.global.world.items.other.ANY_WEBS end)
    by.webs = okw and webs or nil
    -- (0.105.3) B (2 Nov): 5,530 webs, the caverns not found yet: which of
    -- them remove_webs would take (outside the fort's areas, loose, nobody
    -- stuck in them, not forbidden), why the rest stay, and on which levels
    local okr, wr = pcall(webs_survey)
    local where = nil
    if okr then
        by.webs_removable = wr.removable
        where = {kept = wr.kept, levels = wr.levels, hidden = wr.hidden}
    end
    return {counts = by, types = top(types, 15), worn = top(worn_types, 6), on_ground = top(ground_types, 10),
            webs = where, forbidden = fb}
end

---------------------------------------------------------------------------
-- (0.105.3) Spider webs. B "Monastery" (2 Nov, census 07:38): 5,530 webs
-- lay on the ground, a third of the 17,471 items, the game at 1-3 FPS.
-- DFHack's clear-webs takes every web at once, even one a dwarf is about
-- to collect inside the fort. These take only the loose webs outside the
-- fort's own areas. Webs are silk and could be woven into cloth, but
-- thousands of them spread over caverns nobody has reached cost more (in
-- FPS, and dwarves walking far to fetch them) than the silk is worth; the
-- webs near the fort's buildings stay for the weavers.
---------------------------------------------------------------------------

-- (0.105.3) the fort's areas: per level, the box round its buildings
-- (rooms, workshops, stockpiles, zones), widened by `margin` tiles
local function fort_boxes(margin)
    local boxes = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        local ok, z, x1, y1, x2, y2 = pcall(function() return b.z, b.x1, b.y1, b.x2, b.y2 end)
        if ok and type(z) == 'number' and x1 >= 0 then
            local bx = boxes[z]
            if not bx then
                boxes[z] = {x1 = x1, y1 = y1, x2 = x2, y2 = y2}
            else
                bx.x1, bx.y1 = math.min(bx.x1, x1), math.min(bx.y1, y1)
                bx.x2, bx.y2 = math.max(bx.x2, x2), math.max(bx.y2, y2)
            end
        end
    end
    for _, bx in pairs(boxes) do
        bx.x1, bx.y1, bx.x2, bx.y2 = bx.x1 - margin, bx.y1 - margin, bx.x2 + margin, bx.y2 + margin
    end
    return boxes
end

-- (0.105.3) where a creature is stuck in a web (clear-webs' own test:
-- counters.webbed, alive): that web stays
local function webbed_spots()
    local spots = {}
    for _, u in ipairs(df.global.world.units.active) do
        local ok, w = pcall(function() return u.counters.webbed end)
        if ok and type(w) == 'number' and w > 0 and not u.flags2.killed then
            spots[u.pos.x .. ',' .. u.pos.y .. ',' .. u.pos.z] = true
        end
    end
    return spots
end

WEB_MARGIN = 10

-- (0.105.3) true if the web can go, else why it stays (a word)
local function web_verdict(it, boxes, stuck)
    local f = it.flags
    if f.removed or f.garbage_collect then return 'gone' end
    -- a web collected for thread loses its spider_web flag: not a web any more
    local okw, web = pcall(function() return f.spider_web end)
    if okw and web == false then return 'held' end
    -- loose on the ground: not in a building, a bin or a hand, nor about to be collected
    if not f.on_ground or f.in_building or f.construction or f.in_inventory or f.container or f.in_job
            or f.encased then return 'held' end
    if f.owned or f.trader or f.artifact then return 'owned' end
    -- forbidden: the player (or a standing order) said keep it
    if f.forbid then return 'forbidden' end
    local p = it.pos
    if stuck[p.x .. ',' .. p.y .. ',' .. p.z] then return 'stuck' end
    local okh, des = pcall(function() return dfhack.maps.getTileFlags(p.x, p.y, p.z) end)
    local hidden = okh and des and des.hidden
    if not hidden then
        local bx = boxes[p.z]
        if bx and p.x >= bx.x1 and p.x <= bx.x2 and p.y >= bx.y1 and p.y <= bx.y2 then return 'fort' end
    end
    return true, hidden
end

-- (0.105.3) every web looked at once: the ones that can go, and the rest by why
function webs_survey()
    local boxes, stuck = fort_boxes(WEB_MARGIN), webbed_spots()
    local out = {total = 0, removable = 0, hidden = 0, pick = {},
                 kept = {gone = 0, held = 0, owned = 0, forbidden = 0, stuck = 0, fort = 0}}
    local per_z = {}
    for _, it in ipairs(df.global.world.items.other.ANY_WEBS) do
        out.total = out.total + 1
        local v, hidden = web_verdict(it, boxes, stuck)
        if v == true then
            out.removable = out.removable + 1
            if hidden then out.hidden = out.hidden + 1 end
            table.insert(out.pick, it)
            local z = tostring(it.pos.z)
            per_z[z] = (per_z[z] or 0) + 1
        else
            out.kept[v] = out.kept[v] + 1
        end
    end
    out.levels = top(per_z, 5)
    return out
end

-- (0.105.3) up to `max` of those webs removed (dfhack.items.remove, each in
-- a pcall, as clear-webs does), so one call stays quick
function remove_webs(max, dry_run)
    local t0 = os.clock()
    local w = webs_survey()
    local res = {webs = w.total, removable = w.removable, hidden = w.hidden, kept = w.kept, levels = w.levels}
    if dry_run then res.ok, res.dry_run = true, true; return res end
    if w.removable == 0 then
        res.ok, res.rejected = false, true
        res.error = 'no loose web outside the fort\'s areas (' .. w.total .. ' webs, all kept)'
        return res
    end
    local removed, failed = 0, 0
    for i = 1, math.min(max, #w.pick) do
        local ok, r = pcall(function() return dfhack.items.remove(w.pick[i]) end)
        if ok and r ~= false then removed = removed + 1 else failed = failed + 1 end
    end
    res.ok, res.removed, res.failed = removed > 0, removed, failed
    if removed == 0 then res.error = 'the game removed none of the ' .. failed .. ' webs tried' end
    res.webs = w.total - removed
    res.removable_left = w.removable - removed
    res.more = res.removable_left > 0
    res.ms = math.floor((os.clock() - t0) * 1000)
    return res
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
