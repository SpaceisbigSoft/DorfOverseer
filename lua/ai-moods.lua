-- (0.105.24) Strange moods: what each of a mood's requests still lacks, and
-- whether the fort holds something that would do: free to take and within
-- the dwarf's walk, forbidden, dumped, claimed by another job, or none at all.
-- And the one thing the AI can do in place: unforbid (and un-dump) items the
-- mood can use.
--
-- Why (the overnight run, 2-5 Nov, six forts): 231 strange moods, 128 made
-- their artifact, 103 failed (38 melancholy, 35 stark raving, 30 berserk);
-- most of the fort's "in a melancholy/raving mood" deaths of thirst are these
-- dwarves. The AI's notes listed the whole unmet list (the items the dwarf
-- had not fetched yet among them), so "still lacks" said nothing about what
-- the fort had. A mood gathers its requests in order (Kib, C 3 Nov 20:22-20:24:
-- the list shrank from the front, day by day), so the first unmet request is
-- the one the dwarf is looking for now; the last list before a mood failed
-- began with cloth 43 times of 103 (yarn 19, silk 14, plant 10), bone 13,
-- a metal bar 10, a rough gem 12 (4 of green glass), leather 8.
--
-- (0.105.24) DF counts a mood's cloth by its dimension (10000 a whole cloth):
-- the report said "needs 9999 cloths (silk)" for a request the dwarf had
-- already met (one cloth fetched, counted 1), and "30000 cloths" for three.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

CLOTH_DIM = 10000            -- a whole cloth, in DF's units
SCAN_CAP = 30000             -- items looked at a request at most
FREE_MAX = 10                -- items unforbidden a call at most

-- requests with no item type (item NONE): bones, shells and the like are
-- corpse pieces in DF 50; anything else is looked for among all items
local BODY_FLAGS = {bone = true, shell = true, horn = true, pearl = true, ivory = true, tooth = true,
                    hair_wool = true, leather = true}

local function flag_names(ji)
    local out = {}
    for _, fl in ipairs({ji.flags1, ji.flags2, ji.flags3}) do
        pcall(function()
            for name, on in pairs(fl) do
                if on == true and type(name) == 'string' then table.insert(out, name) end
            end
        end)
    end
    table.sort(out)
    return out
end

local function job_requests(job)
    local reqs = job.job_items
    pcall(function() if reqs.elements then reqs = reqs.elements end end)   -- (a job_reqst in 53: its vector is .elements)
    return reqs
end

-- how much of each request the dwarf has fetched (a cloth request counted by
-- the cloth's dimension when DF asks in those units)
local function fetched(job, reqs)
    local got, dim = {}, {}
    for idx, ji in ipairs(reqs) do
        dim[idx] = ji.item_type == df.item_type.CLOTH and ji.quantity >= 1000
    end
    for _, ref in ipairs(job.items) do
        local idx = ref.job_item_idx
        if idx and idx >= 0 then
            local n = ref.item:getStackSize()
            if dim[idx] then
                local ok, d = pcall(function() return ref.item:getTotalDimension() end)
                n = (ok and type(d) == 'number' and d > 0) and d or n * CLOTH_DIM
            end
            got[idx] = (got[idx] or 0) + n
        end
    end
    return got, dim
end

-- The requests not yet met: {index, item, material, flags, quantity}, in
-- the mood's own order (the first is what the dwarf is fetching now).
function requests_missing(job, txt)
    txt = txt or tostring
    local reqs = job_requests(job)
    local got, dim = fetched(job, reqs)
    local out = {}
    for idx, ji in ipairs(reqs) do
        local left = ji.quantity - (got[idx] or 0)
        if left > 0 then
            local mat
            if ji.mat_type >= 0 then
                local mi = dfhack.matinfo.decode(ji.mat_type, ji.mat_index)
                -- (0.105.24) mat_type 0 with no index is "any stone, gem or
                -- metal": the report said "rough gem of rock"
                if mi and not (ji.mat_type == 0 and ji.mat_index < 0) then mat = txt(mi:toString()) end
            end
            table.insert(out, {index = idx, item = df.item_type[ji.item_type] or tostring(ji.item_type), material = mat,
                               flags = flag_names(ji),
                               quantity = dim[idx] and math.ceil(left / CLOTH_DIM) or left})
        end
    end
    return out
end

-- which item lists hold what a request asks for
function search_lists(item_name, flags)
    if item_name and item_name ~= 'NONE' and df.items_other_id[item_name] ~= nil then return {item_name} end
    for _, f in ipairs(flags or {}) do
        if BODY_FLAGS[f] then return {'CORPSEPIECE'} end
    end
    return {'IN_PLAY'}
end

-- an item's standing for a mood: 'free', 'forbidden', 'dump', 'job' (another
-- job holds it) or 'other' (a building, a construction, a trader's, owned...)
-- (lua/ai-util.lua's list; what a unit carries isn't looked up: this runs in
-- every pulse report)
local STANDING = {in_job = 'job', forbid = 'forbidden', dump = 'dump'}
local HELD_OK = {held = true}

-- (0.105.33) The hospital's stock: the chests standing in a hospital
-- location's zones (chest building id -> true), read again every
-- HOSPITAL_TICKS. What lies in them is the hospital's thread and cloth, not
-- the mood's (C, 8 Nov: "5 yarn thread" counted for a mood, unchanged for 9
-- seasons, were the hospital's; the mood waited on them and went melancholy).
HOSPITAL_TICKS = 1200
HOSPITAL_CACHE = HOSPITAL_CACHE or nil
function hospital_boxes()
    local now = U.abs_tick()
    local c = HOSPITAL_CACHE
    if c and now - c.at >= 0 and now - c.at < HOSPITAL_TICKS then return c.set, c.rects or {} end
    local set, zones = {}, {}
    pcall(function()
        local site = dfhack.world.getCurrentSite()
        for _, loc in ipairs(site and site.buildings or {}) do
            if df.abstract_building_type[loc:getType()] == 'HOSPITAL' then
                local ct = loc:getContents()
                for _, bid in ipairs(ct and ct.building_ids or {}) do
                    local z = df.building.find(bid)
                    if z then
                        -- (R1 g6) the zone's floor too; (X2, V6) only plain data is kept for the
                        -- day: a zone removed meanwhile is freed DF memory. It is found again by id.
                        pcall(function()
                            table.insert(zones, {id = z.id, z = z.z, x1 = z.x1, y1 = z.y1,
                                                 x2 = z.x2, y2 = z.y2})
                        end)
                        pcall(function()
                            for _, b in ipairs(z.contained_buildings) do
                                if df.building_type[b:getType()] == 'Box' then set[b.id] = true end
                            end
                        end)
                    end
                end
            end
        end
    end)
    HOSPITAL_CACHE = {at = now, set = set, rects = zones}   -- (X2, V6) plain data only
    return set, zones
end

-- (R1 g6) true for an item lying anywhere inside a hospital zone (on its
-- floor as much as in its chests): R-AD, A's "pig tail cloth" and "alpaca
-- wool cloth" at x109 y174 z163, inside hospital zone 582 (x104-112
-- y166-174 z163), were counted "free, in walk" for four moods; no dwarf ever
-- fetched them, and Udib and Melbil died after 40 days waiting. Counted
-- 'other', the mood's cloth is made at once.
function hospital_ground(it)
    local _, zones = hospital_boxes()
    if not zones or #zones == 0 then return false end
    local ok, yes = pcall(function()
        local x, y, z = dfhack.items.getPosition(it)
        if not x then return false end
        for _, zn in ipairs(zones) do
            local okz, inside = pcall(function()
                if zn.z ~= z then return false end
                if zn.x1 and (x < zn.x1 or x > zn.x2 or y < zn.y1 or y > zn.y2) then return false end
                local b = df.building.find(zn.id)        -- (X2, V6) fresh: nil once removed
                if not b or b.z ~= z then return false end
                return dfhack.buildings.containsTile(b, x, y)
            end)
            if okz and inside == true then return true end
        end
        return false
    end)
    return ok and yes == true
end
-- (0.105.36, D5) another fort's chest ids are not this one's
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-moods-hospital'] = function(sc)
        if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then HOSPITAL_CACHE = nil end
    end
end

-- true for an item in one of the hospital's chests
function hospital_stock(it)
    local set = hospital_boxes()
    if next(set) == nil then return false end
    local ok, yes = pcall(function()
        local cont = dfhack.items.getContainer(it)
        if not cont then return false end
        local b = dfhack.items.getHolderBuilding(cont)
        return b ~= nil and set[b.id] == true
    end)
    return ok and yes == true
end

function item_standing(it)
    local why = U.item_unfree(it, HELD_OK)
    if why == nil then
        if hospital_stock(it) then return 'other' end       -- (0.105.33) the hospital's, not the mood's
        if hospital_ground(it) then return 'other' end      -- (R1 g6) on the hospital's floor too
        return 'free'
    end
    return STANDING[why] or 'other'
end

-- (0.105.33) A request that names a material takes only that material:
-- DFHack's isSuitableMaterial reads the request's flags, not its mat_type
-- (C, E, F, 8 Nov: three glassmakers' "rough green glass" was counted from
-- plain rough gems, "2 free, 2 in walk", in forts with no glass and no sand;
-- the AI waited on items that were never there). mat_type 0 with no index is
-- "any stone, gem or metal": any inorganic.
local function material_ok(ji, it)
    local mt = tonumber(ji.mat_type) or -1
    if mt < 0 then return true end
    if it:getMaterial() ~= mt then return false end
    local mi = tonumber(ji.mat_index) or -1
    return mi < 0 or it:getMaterialIndex() == mi
end

-- (0.105.47) Cloth and thread by the kind of fibre: an item's material
-- flags (SILK, YARN, THREAD_PLANT), 'silk' / 'yarn' / 'plant', or nil when
-- the material says none of them (or can't be read). One test for the
-- moods and the bridge's cloth and thread counts (supplies cloth_kinds,
-- thread_kinds), so the reserves see what a mood can use.
function cloth_kind(it)
    local ok, k = pcall(function()
        local mi = dfhack.matinfo.decode(it)
        local f = mi and mi.material and mi.material.flags
        if not f then return nil end
        return f.SILK and 'silk' or f.YARN and 'yarn' or f.THREAD_PLANT and 'plant' or nil
    end)
    return ok and k or nil
end

-- (0.105.47) the material flags could be read at all (an item from a test
-- or an odd material: then DFHack's own test is asked, as before)
local function mat_flags_read(it)
    local ok, f = pcall(function()
        local mi = dfhack.matinfo.decode(it)
        return mi and mi.material and mi.material.flags
    end)
    return ok and f ~= nil
end

local CLOTH_TYPES = {CLOTH = true, THREAD = true}
local KIND_FLAGS = {'silk', 'yarn', 'plant'}

-- (0.105.47) a cloth or thread request matched by the fibre the request
-- names (job_item flags2 silk / yarn / plant; none named: any cloth): I7a,
-- 11-14 Nov, more than 2,000 mood records of a cloth request read `avail {}`
-- (nothing counted, not even forbidden) in every fort, B holding 96-133
-- plant cloth: DFHack's isSuitableItem/isSuitableMaterial rejected what DF
-- itself fetched (F's Cerol took the fort's silk), so every cloth line said
-- "can't supply". 36 of the run's 54 failed moods waited on cloth.
-- nil: not a cloth or thread request (the caller asks DFHack).
function cloth_suits(ji, it)
    local tname = df.item_type[ji.item_type]
    if not CLOTH_TYPES[tname] then return nil end
    if it:getType() ~= ji.item_type then return false end
    if not mat_flags_read(it) then return nil end
    -- a web lying where the spider spun it is no collected thread
    local okw, web = pcall(function() return it.flags.spider_web end)
    if okw and web == true then return false end
    local want = {}
    for _, k in ipairs(KIND_FLAGS) do
        local okf, on = pcall(function() return ji.flags2[k] end)
        if okf and on == true then want[k] = true end
    end
    local kind = cloth_kind(it)
    if next(want) == nil then return true end      -- any cloth (any fibre)
    return kind ~= nil and want[kind] == true
end

-- (0.105.51) A body-part request (bone, shell, horn, pearl, ivory, wool...)
-- matched by the corpse piece's own flags (item_body_component corpse_flags:
-- what it counts as), not DFHack's isSuitableMaterial: R3, E's Tobul waited
-- 40 days on "1 bone" counted "free, in walk" from a stack of shorn alpaca
-- wool on a stockpile, and the AI asked no animal for its bones. nil: not a
-- body-part request, or the item has no corpse flags (DFHack is asked).
local BODY_MATCH = {bone = 'bone', shell = 'shell', horn = 'horn', pearl = 'pearl', ivory_tooth = 'tooth',
                    hair_wool = 'hair_wool', yarn = 'yarn', silk = 'silk', leather = 'leather', totemable = 'skull'}
function body_suits(ji, it)
    local okb, body = pcall(function() return ji.flags2.body_part end)
    if not (okb and body == true) then return nil end
    local okc, cf = pcall(function() return it.corpse_flags end)
    if not okc or cf == nil then return nil end
    local want, any = false, false
    for jf, cfn in pairs(BODY_MATCH) do
        local okf, on = pcall(function() return ji.flags2[jf] end)
        if okf and on == true then
            want = true
            local okh, has = pcall(function() return cf[cfn] end)
            if okh and has == true then any = true end
        end
    end
    if not want then return nil end
    local oku, unb = pcall(function() return cf.unbutchered end)
    if oku and unb == true then return false end        -- a carcass still to butcher
    return any
end

local function suits(ji, it)
    local ok, yes = pcall(function()
        local c = cloth_suits(ji, it)
        if c ~= nil then return c and material_ok(ji, it) end
        local bs = body_suits(ji, it)
        if bs == false then return false end
        return dfhack.job.isSuitableItem(ji, it:getType(), it:getSubtype())
            and dfhack.job.isSuitableMaterial(ji, it:getMaterial(), it:getMaterialIndex(), it:getType())
            and material_ok(ji, it)
    end)
    return ok and yes == true
end

local function reach(from, it)
    if not from then return nil end
    local ok, yes = pcall(function()
        local x, y, z = dfhack.items.getPosition(it)
        if not x then return false end
        return dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z))
    end)
    return ok and yes == true
end

-- Walks the items that suit one request, calling fn(item, standing, reachable)
-- (reachability only asked for the free, forbidden and dumped).
local function own_items(unit)
    local ids = {}
    pcall(function()
        for _, ref in ipairs(unit.job.current_job.items) do ids[ref.item.id] = true end
    end)
    return ids
end

-- (0.105.30) returns true when the search was cut short: the scan cap, or
-- an error part way (E, 8 Nov: "no loose stone" from a search that may not
-- have looked)
local function each_suitable(ji, entry, from, fn, own)
    own = own or {}
    local scanned, failed = 0, false
    for _, list in ipairs(search_lists(entry.item, entry.flags)) do
        local ok = pcall(function()
            for _, it in ipairs(df.global.world.items.other[df.items_other_id[list]]) do
                scanned = scanned + 1
                if scanned > SCAN_CAP then return end
                if not own[it.id] and suits(ji, it) then        -- (not what the mood has fetched)
                    local st = item_standing(it)
                    local r = (st == 'free' or st == 'forbidden' or st == 'dump') and reach(from, it) or nil
                    if fn(it, st, r) == false then return end
                end
            end
        end)
        if not ok then failed = true end
        if not ok or scanned > SCAN_CAP then break end
    end
    return scanned > SCAN_CAP or failed
end

-- (0.105.30) the unit carrying an item, if any
local function holder_of(it)
    local ok, u = pcall(dfhack.items.getHolderUnit, it)
    return ok and u or nil
end

-- (0.105.47) where an item lies, in a word or two: in a container (its
-- kind), in a building (its kind), on a stockpile, carried, or on the ground
-- (I7a: four moods waited 40 days on bone or leather counted "free, in walk"
-- and never fetched; the logs couldn't say where it lay)
function item_place(it)
    local where = 'ground'
    pcall(function()
        local c = dfhack.items.getContainer and dfhack.items.getContainer(it)
        if c then
            where = 'in a ' .. tostring(df.item_type[c:getType()] or 'container'):lower()
            return
        end
        if it.flags.in_building then
            local b = dfhack.items.getHolderBuilding and dfhack.items.getHolderBuilding(it)
            where = 'in a building' .. (b and (' (' .. tostring(df.building_type[b:getType()]) .. ')') or '')
            return
        end
        if it.flags.in_inventory then where = 'carried' return end
        local x, y, z = dfhack.items.getPosition(it)
        local b = x and dfhack.buildings.findAtTile and dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if b and df.building_type[b:getType()] == 'Stockpile' then where = 'on a stockpile' end
    end)
    return where
end

SPOTS_MAX = 3

local function spot_of(it, st, r)
    local ok, sp = pcall(function()
        local x, y, z = dfhack.items.getPosition(it)
        if not x then return nil end
        local okd, d = pcall(dfhack.items.getReadableDescription, it)
        return {x = x, y = y, z = z, standing = st, reach = r == true, at = item_place(it),
                what = okd and type(d) == 'string' and d:sub(1, 60) or nil}
    end)
    return ok and sp or nil
end

-- {free, reach, forbidden, forbidden_reach, dump, job, other, capped,
-- enough}: the walk stops once enough lies free within reach (`enough`:
-- the other counts are then partial); a stone or a log is found at once.
-- (0.105.30) `held`: what the dwarf itself carries that suits (counted only
-- there; it is on its way to the workshop)
-- (0.105.47) `taken`: items an earlier request of the same mood has counted
-- for itself (item id -> true), passed by; the items this request counts
-- toward what it lacks (free or forbidden within reach, up to the quantity)
-- are added to it, so one rough gem doesn't meet four requests (F's Asen,
-- y264: four rough-gem requests all "on hand" from one gem). `spots`: where
-- the first few free or forbidden items lie (I7a 7).
-- (0.105.79) a cloth request (DF asks in dimension units) counts only whole
-- cloths: a partial piece (E, 22 Nov: Nish's Secretive mood stalled 41 days
-- "on hand" with a 60% silk and a 20% wool cloth free, then went mad and
-- died of thirst) is tallied in `partial`, never toward what the mood lacks.
local function partial_cloth(ji, it)
    local okq, dimq = pcall(function() return ji.item_type == df.item_type.CLOTH and ji.quantity >= 1000 end)
    if not (okq and dimq) then return false end
    local ok, d = pcall(function() return it:getTotalDimension() end)
    return ok and type(d) == 'number' and d > 0 and d < CLOTH_DIM
end

function request_avail(ji, entry, unit, taken)
    local a = {free = 0, reach = 0, forbidden = 0, forbidden_reach = 0, dump = 0, job = 0, other = 0, held = 0}
    local from = unit and unit.pos or nil
    local want = math.max(1, tonumber(entry.quantity) or 1)
    local skip = unit and own_items(unit) or {}
    for id in pairs(taken or {}) do skip[id] = true end
    local spots = {}
    local capped = each_suitable(ji, entry, from, function(it, st, r)
        if partial_cloth(ji, it) then
            a.partial = (a.partial or 0) + 1
            return
        end
        local n = 1
        pcall(function() n = it:getStackSize() end)
        local h = unit and holder_of(it)
        if h and h.id == unit.id then
            a.held = a.held + n
        else
            local claim = false
            if st == 'free' and r and a.reach + a.held < want then claim = true end
            if (st == 'forbidden' or st == 'dump') and r and a.reach + a.forbidden_reach < want then claim = true end
            a[st] = a[st] + n
            if st == 'free' and r then a.reach = a.reach + n end
            if (st == 'forbidden' or st == 'dump') and r then a.forbidden_reach = a.forbidden_reach + n end
            if claim and taken then taken[it.id] = true end
            if (st == 'free' or st == 'forbidden' or st == 'dump') and #spots < SPOTS_MAX then
                local sp = spot_of(it, st, r)
                if sp then table.insert(spots, sp) end
            end
        end
        if a.reach + a.held >= want then a.enough = true return false end
    end, skip)
    if capped then a.capped = true end
    if #spots > 0 then a.spots = spots end
    return a
end

-- (0.105.24) the moods are in every pulse report: a request's count is kept
-- for half a day (keyed by the dwarf, the request and what it still lacks)
AVAIL_TICKS = 600
AVAIL_CACHE = AVAIL_CACHE or {}

local function now_tick() return U.abs_tick() end             -- (r6) not protected: an error goes to the caller

-- (0.105.31) the sizes of the item lists a request is looked for in: a
-- count kept while nothing within reach would do is taken again at once when
-- a list grows (F, 8 Nov: the supplies counted 2 plant cloth, woven after
-- the weaver's request was counted 0, and the AI said "can't supply" for
-- half a day)
-- (0.105.31 reserve fixes) only a list of the requested kind (CLOTH, BONES...)
-- is taken again at once when it grows; the catch-all lists (IN_PLAY, body
-- parts) grow and shrink nearly every tick: at most once a game hour for them
AVAIL_RECOUNT_TICKS = 50
local CATCH_ALL = {IN_PLAY = true, CORPSEPIECE = true}
local function list_sizes(entry)
    local out = {}
    for _, list in ipairs(search_lists(entry.item, entry.flags)) do
        local ok, n = pcall(function() return #df.global.world.items.other[df.items_other_id[list]] end)
        out[list] = ok and tonumber(n) or nil
    end
    return out
end

-- a new item that may suit: a list of the requested kind longer than at the
-- count, or a catch-all list longer and the count an hour old
local function grew(old, sizes, age)
    for list, n in pairs(sizes) do
        local was = type(old) == 'table' and old[list] or nil
        if was == nil or n > was then
            if not CATCH_ALL[list] or age >= AVAIL_RECOUNT_TICKS then return true end
        end
    end
    return false
end

-- (0.105.47) `taken` as request_avail's; `fresh`: an earlier request of the
-- mood was counted again, so this one is too (what it may claim changed).
-- Returns the count and whether it was counted afresh.
local function cached_avail(ji, entry, unit, taken, fresh)
    local key = tostring(unit and unit.id) .. ':' .. tostring(entry.index) .. ':' .. tostring(entry.quantity)
    local now = now_tick()
    local c = AVAIL_CACHE[key]
    local sizes = list_sizes(entry)
    if not fresh and c and now - c.at >= 0 and now - c.at < AVAIL_TICKS
            and (c.avail.enough or not grew(c.sizes, sizes, now - c.at)) then
        for id in pairs(c.claimed or {}) do taken[id] = true end
        return c.avail, false
    end
    local before = {}
    for id in pairs(taken) do before[id] = true end
    local a = request_avail(ji, entry, unit, taken)
    local claimed = {}
    for id in pairs(taken) do if not before[id] then claimed[id] = true end end
    local n = 0
    for _ in pairs(AVAIL_CACHE) do n = n + 1 end
    if n >= 200 then AVAIL_CACHE = {} end           -- moods long over
    AVAIL_CACHE[key] = {at = now, avail = a, sizes = sizes, claimed = claimed}
    return a, true
end

-- (0.105.24) the mood's requests, each with what the fort holds for it
-- (0.105.47) each item counted for one request only, in the mood's order
function mood_report(job, unit, txt)
    local missing = requests_missing(job, txt)
    local reqs = job_requests(job)
    local taken, fresh = {}, false
    for _, e in ipairs(missing) do
        local ji = reqs[e.index]
        if ji then
            local ok, a, again = pcall(cached_avail, ji, e, unit, taken, fresh)
            if ok then
                e.avail = a
                if again then fresh = true end
            end
        end
    end
    return missing
end

local function mood_job(u)
    if not u or u.mood == nil or u.mood < 0 then return nil end
    local ok, job = pcall(function() return u.job.current_job end)
    return ok and job or nil
end

-- (0.105.47) the tiles a gathering mood needs: its workshop's and where the
-- items it still lacks lie (free or forbidden, a few a request), as
-- {x, y, z} (lua/ai-mood-help.lua puts them in the shelter burrow while the
-- alarm is up: I7a, five moods cancelled "Forbidden area" by the AI's alarm)
function mood_tiles(unit)
    local out = {}
    local job = mood_job(unit)
    if not job then return out end
    pcall(function()
        local b = dfhack.job.getHolder(job)
        if b then
            for x = b.x1, b.x2 do
                for y = b.y1, b.y2 do table.insert(out, {x = x, y = y, z = b.z}) end
            end
        end
    end)
    local reqs = job_requests(job)
    local okm, missing = pcall(requests_missing, job)
    if not okm then return out end
    local taken = {}
    for _, e in ipairs(missing) do
        local ji = reqs[e.index]
        if ji then
            local ok, a = pcall(request_avail, ji, e, unit, taken)
            if ok and a.spots then
                for _, sp in ipairs(a.spots) do table.insert(out, {x = sp.x, y = sp.y, z = sp.z}) end
            end
        end
    end
    return out
end

-- (0.105.24) For a dwarf in a strange mood: items the mood can use that lie
-- forbidden (or marked for the dump) within the dwarf's walk are freed, for
-- each request nothing free within reach would meet, as much as it lacks
-- (at most `max` items a call). Nothing else is touched: never an item
-- another job holds, a building, a construction, an owned or a trader's item.
--
-- (0.105.33) and never an item the disposal actions would leave alone
-- (ai-disposal's blocked(): on the cistern's tiles the AI forbade before the
-- flood, near a live danger, on a cavern tile while the seal holds, an
-- artifact, owned): a moody dwarf isn't sent into a cistern about to flood
-- or onto a battlefield. When those can't be read, nothing is freed.
local function unforbid_guard()
    local okd, D = pcall(reqscript, 'ai-disposal')
    if not (okd and type(D) == 'table' and D.context and D.blocked) then return nil end
    local okc, ctx = pcall(D.context)
    if not (okc and type(ctx) == 'table') then return nil end
    return function(it)
        local ok, why = pcall(function()
            local x, y, z = dfhack.items.getPosition(it)
            return D.blocked(it, x, y, z, 'mood', ctx)
        end)
        if not ok then return 'error' end
        return why
    end
end

function free_items(unit_id, dry_run, max, txt)
    txt = txt or tostring
    max = math.min(FREE_MAX, math.max(1, tonumber(max) or FREE_MAX))
    local u = df.unit.find(unit_id)
    if not u then return {ok = false, rejected = true, error = 'no such unit'} end
    local job = mood_job(u)
    if not job then return {ok = false, rejected = true, error = 'that dwarf is not in a mood with a job'} end
    local reqs = job_requests(job)
    local freed, names = 0, {}
    local guard, held = nil, {}
    local function kept(it)
        if guard == nil then
            guard = unforbid_guard() or false
        end
        if guard == false then return 'unread' end
        return guard(it)
    end
    for _, e in ipairs(requests_missing(job, txt)) do
        local ji = reqs[e.index]
        if ji and freed < max then
            local a = request_avail(ji, e, u)
            local want = math.max(0, e.quantity - a.reach)
            if want > 0 then
                each_suitable(ji, e, u.pos, function(it, st, r)
                    local why = (st == 'forbidden' or st == 'dump') and r and kept(it) or nil
                    if why then
                        held[why] = (held[why] or 0) + 1
                    elseif (st == 'forbidden' or st == 'dump') and r then
                        if not dry_run then
                            it.flags.forbid = false
                            it.flags.dump = false
                        end
                        freed = freed + 1
                        want = want - 1
                        if #names < 5 then
                            local okd, d = pcall(dfhack.items.getReadableDescription, it)
                            table.insert(names, okd and txt(d) or tostring(e.item))
                        end
                    end
                    if want <= 0 or freed >= max then return false end
                end, own_items(u))
            end
        end
    end
    local kept_n, kept_why = 0, {}
    for why, n in pairs(held) do
        kept_n = kept_n + n
        table.insert(kept_why, n .. ' ' .. why)
    end
    table.sort(kept_why)
    if freed == 0 then
        if kept_n > 0 then
            return {ok = false, rejected = true, kept = kept_n,
                    error = 'the forbidden items the mood can use are left alone (' .. table.concat(kept_why, ', ')
                        .. '): a cistern about to flood, a danger, a sealed cavern, or the dangers unread'}
        end
        return {ok = false, rejected = true, error = 'nothing forbidden or dumped within the dwarf\'s walk that the mood can use'}
    end
    return {ok = true, freed = freed, items = names, dry_run = dry_run or nil, kept = kept_n > 0 and kept_n or nil}
end
