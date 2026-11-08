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
function item_standing(it)
    local why = U.item_unfree(it, HELD_OK)
    if why == nil then return 'free' end
    return STANDING[why] or 'other'
end

local function suits(ji, it)
    local ok, yes = pcall(function()
        return dfhack.job.isSuitableItem(ji, it:getType(), it:getSubtype())
            and dfhack.job.isSuitableMaterial(ji, it:getMaterial(), it:getMaterialIndex(), it:getType())
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

local function each_suitable(ji, entry, from, fn, own)
    own = own or {}
    local scanned = 0
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
        if not ok or scanned > SCAN_CAP then break end
    end
    return scanned > SCAN_CAP
end

-- {free, reach, forbidden, forbidden_reach, dump, job, other, capped,
-- enough}: the walk stops once enough lies free within reach (`enough`:
-- the other counts are then partial); a stone or a log is found at once.
function request_avail(ji, entry, unit)
    local a = {free = 0, reach = 0, forbidden = 0, forbidden_reach = 0, dump = 0, job = 0, other = 0}
    local from = unit and unit.pos or nil
    local want = math.max(1, tonumber(entry.quantity) or 1)
    local capped = each_suitable(ji, entry, from, function(it, st, r)
        local n = 1
        pcall(function() n = it:getStackSize() end)
        a[st] = a[st] + n
        if st == 'free' and r then a.reach = a.reach + n end
        if (st == 'forbidden' or st == 'dump') and r then a.forbidden_reach = a.forbidden_reach + n end
        if a.reach >= want then a.enough = true return false end
    end, unit and own_items(unit) or nil)
    if capped then a.capped = true end
    return a
end

-- (0.105.24) the moods are in every pulse report: a request's count is kept
-- for half a day (keyed by the dwarf, the request and what it still lacks)
AVAIL_TICKS = 600
AVAIL_CACHE = AVAIL_CACHE or {}

local function now_tick()
    return U.abs_tick()
end

local function cached_avail(ji, entry, unit)
    local key = tostring(unit and unit.id) .. ':' .. tostring(entry.index) .. ':' .. tostring(entry.quantity)
    local now = now_tick()
    local c = AVAIL_CACHE[key]
    if c and now - c.at >= 0 and now - c.at < AVAIL_TICKS then return c.avail end
    local a = request_avail(ji, entry, unit)
    local n = 0
    for _ in pairs(AVAIL_CACHE) do n = n + 1 end
    if n >= 200 then AVAIL_CACHE = {} end           -- moods long over
    AVAIL_CACHE[key] = {at = now, avail = a}
    return a
end

-- (0.105.24) the mood's requests, each with what the fort holds for it
function mood_report(job, unit, txt)
    local missing = requests_missing(job, txt)
    local reqs = job_requests(job)
    for _, e in ipairs(missing) do
        local ji = reqs[e.index]
        if ji then
            local ok, a = pcall(cached_avail, ji, e, unit)
            if ok then e.avail = a end
        end
    end
    return missing
end

local function mood_job(u)
    if not u or u.mood == nil or u.mood < 0 then return nil end
    local ok, job = pcall(function() return u.job.current_job end)
    return ok and job or nil
end

-- (0.105.24) For a dwarf in a strange mood: items the mood can use that lie
-- forbidden (or marked for the dump) within the dwarf's walk are freed, for
-- each request nothing free within reach would meet, as much as it lacks
-- (at most `max` items a call). Nothing else is touched: never an item
-- another job holds, a building, a construction, an owned or a trader's item.
function free_items(unit_id, dry_run, max, txt)
    txt = txt or tostring
    max = math.min(FREE_MAX, math.max(1, tonumber(max) or FREE_MAX))
    local u = df.unit.find(unit_id)
    if not u then return {ok = false, rejected = true, error = 'no such unit'} end
    local job = mood_job(u)
    if not job then return {ok = false, rejected = true, error = 'that dwarf is not in a mood with a job'} end
    local reqs = job_requests(job)
    local freed, names = 0, {}
    for _, e in ipairs(requests_missing(job, txt)) do
        local ji = reqs[e.index]
        if ji and freed < max then
            local a = request_avail(ji, e, u)
            local want = math.max(0, e.quantity - a.reach)
            if want > 0 then
                each_suitable(ji, e, u.pos, function(it, st, r)
                    if (st == 'forbidden' or st == 'dump') and r then
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
    if freed == 0 then
        return {ok = false, rejected = true, error = 'nothing forbidden or dumped within the dwarf\'s walk that the mood can use'}
    end
    return {ok = true, freed = freed, items = names, dry_run = dry_run or nil}
end
