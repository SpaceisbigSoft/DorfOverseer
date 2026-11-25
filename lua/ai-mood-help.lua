-- (0.105.47) What the strange moods need from the rest of the fort: the
-- section `mood_help` and the action `mood_shelter`.
--
-- Why (I7a, the 11-14 Nov run, forts A-F): 54 moods failed. 49 timed out,
-- 36 of them waiting on cloth (silk 20, plant 10, yarn 6); 5 were cancelled
-- "Forbidden area" by the AI's own civilian alarm while the dwarf fetched
-- outside the shelter burrow. The AI waited on orders DF kept cancelling
-- ("Weave yarn into cloth: Needs 1 unused collected yarn thread" more than
-- 1,000 times in F, "Shear animal: No creature" 250 times, "Collect sand:
-- Need valid, active sand collection zone" 31 times), and silk had no route
-- at all while remove_webs took 20,000-36,000 webs a fort off the map.
--
-- What it reads (each part behind pcall):
--   * cancels: DF's job-cancel reports of the last CANCEL_WINDOW ticks
--     (ai-threats cancel_rows / parse_cancel, the 0.105.44 reader), tallied
--     by job and reason: {job, n, why, tick}; the brain counts an order
--     whose jobs DF keeps cancelling as a failed route (planner_mood_help);
--   * webs: the loose webs (where the spiders spun them, not forbidden, no
--     job on them) and how many a Loom's weaver can walk to (sampled;
--     read once a game day): the silk route (DF's CollectWebs job at a Loom);
--   * shelter: while a crafting mood gathers and the AI shelter burrow
--     exists, how many of the tiles it needs (its workshop, where the items
--     it lacks lie: ai-moods mood_tiles) lie outside it.
--
--   report()                     the section
--   add_mood_spots(b, dry_run)   those tiles put in burrow b (the AI shelter):
--                                ai-society's fill_shelter calls it each time
--                                it draws the shelter; the action calls it
--                                while the alarm (or the evil weather's
--                                keep-in) is up
--   act_mood_shelter(a)          the `mood_shelter` action
--   act_hospital_release(a)      the `hospital_release` action: the hospital's
--                                thread or cloth for a waiting strange mood,
--                                and the hospital's quotas lowered meanwhile
--                                (restore = true puts them back)
--   act_hospital_cap(a)          (0.105.112) the `hospital_cap` action: the
--                                hospital's standing thread and cloth quotas
--                                (what its patients need), the surplus set out
--@ module = true

local U = reqscript('ai-util')

CANCEL_WINDOW = 3 * 1200        -- job cancellations this recent are read
CANCEL_TICKS = 100              -- read again at most this often
CANCEL_ROWS = 30                -- jobs kept in the section
WEBS_TICKS = 1200               -- the webs counted once a game day
WEB_REACH_CHECKS = 20000        -- webs looked at a count at most (a walk group read each: cheap)
WEB_REACH_ENOUGH = 200          -- ...or until this many are known within reach
CRAFT_MOODS = {Fey = true, Secretive = true, Possessed = true, Macabre = true, Fell = true}

MEMO = MEMO or {}
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-mood-help'] = function(sc)
        if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then MEMO = {} end
    end
end

local function now_tick() return U.now_tick(0) end            -- (r6) ai-util's: 0 when it can't be read

-- {job, n, why, tick} by job and reason, the most cancelled first
function job_cancels(window)
    local out = {}
    local ok, T = pcall(reqscript, 'ai-threats')
    if not ok or not T or not T.cancel_rows or not T.parse_cancel then return out end
    local okr, rows = pcall(T.cancel_rows, window or CANCEL_WINDOW)
    if not okr or type(rows) ~= 'table' then return out end
    local by = {}
    for _, r in ipairs(rows) do               -- newest first
        local who, job, why = T.parse_cancel(r.text)
        if who and type(job) == 'string' and not job:find('^Drink') and not job:find('^Eat')
                and not job:find('^Sleep') then
            local k = job:lower() .. '|' .. tostring(why):lower()     -- each reason its own row
            local e = by[k]
            if not e then
                e = {job = job:sub(1, 60), n = 0, why = tostring(why):sub(1, 80), tick = r.tick}
                by[k] = e
                table.insert(out, e)
            end
            e.n = e.n + (tonumber(r.n) or 1)
        end
    end
    table.sort(out, function(a, b) return a.n > b.n end)
    while #out > CANCEL_ROWS do table.remove(out) end
    return out
end

local function cancels_memo()
    local now = now_tick()
    local m = MEMO.cancels
    if m and now - m.at >= 0 and now - m.at < CANCEL_TICKS then return m.list end
    local list = job_cancels()
    MEMO.cancels = {at = now, list = list}
    return list
end

-- (0.105.51) the walk groups a Loom's weaver stands in: every walkable tile
-- of each Loom's footprint (R3: "reach 0" in all six forts with 4,000-11,000
-- loose webs, the walk asked from the Loom's centre tile only and from the
-- first 400 webs of the list; a tile under the loom's frame has no walk group)
function loom_groups()
    local out, n = {}, 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.Workshop and b.type == df.workshop_type.Loom then
                n = n + 1
                for x = b.x1, b.x2 do
                    for y = b.y1, b.y2 do
                        local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, b.z))
                        if ok and type(g) == 'number' and g ~= 0 then out[g] = true end
                    end
                end
            end
        end
    end)
    return out, n
end

-- a web lying where it was spun, free for a weaver to collect
function web_loose(it)
    local ok, yes = pcall(function()
        local f = it.flags
        return f.spider_web == true and f.on_ground and not (f.forbid or f.in_job or f.removed or f.garbage_collect
            or f.in_building or f.construction or f.encased or f.trader or f.owned)
    end)
    return ok and yes == true
end

-- {total, loose, reach, looms, sampled}: a web within reach when its tile's
-- walk group is a Loom's (DF's own canWalkBetween test, read once a Loom)
function webs_near()
    local out = {total = 0, loose = 0, reach = 0}
    local groups, nl = loom_groups()
    out.looms = nl
    local checks = 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.ANY_WEBS) do
            out.total = out.total + 1
            if web_loose(it) then
                out.loose = out.loose + 1
                if next(groups) ~= nil and checks < WEB_REACH_CHECKS and out.reach < WEB_REACH_ENOUGH then
                    checks = checks + 1
                    local okp, pos = pcall(function() return it.pos end)
                    local okg, g = false, nil
                    if okp then okg, g = pcall(dfhack.maps.getWalkableGroup, pos) end
                    if okg and type(g) == 'number' and g ~= 0 and groups[g] then out.reach = out.reach + 1 end
                end
            end
        end
    end)
    if checks >= WEB_REACH_CHECKS then out.sampled = true end
    return out
end

local function webs_memo()
    local now = now_tick()
    local m = MEMO.webs
    if m and now - m.at >= 0 and now - m.at < WEBS_TICKS then return m.v end
    local v = webs_near()
    MEMO.webs = {at = now, v = v}
    return v
end

-- the citizens in a crafting mood with its job (gathering or at work)
function gathering_moods()
    local out = {}
    local okc, list = pcall(U.citizens, false, true)
    if not okc then return out end
    for _, u in ipairs(list) do
        local ok, yes = pcall(function()
            return u.mood >= 0 and CRAFT_MOODS[df.mood_type[u.mood]] == true and u.job.current_job ~= nil
        end)
        if ok and yes then table.insert(out, u) end
    end
    return out
end

function shelter_burrow()
    local ok, b = pcall(function()
        local S = reqscript('ai-society')
        return S.find_burrow(S.SHELTER_NAME)
    end)
    return ok and b or nil
end

-- the tiles the gathering moods need, each once: {x, y, z}
local function mood_spots(units)
    local out, seen = {}, {}
    local okm, M = pcall(reqscript, 'ai-moods')
    if not (okm and M and M.mood_tiles) then return out end
    for _, u in ipairs(units) do
        local ok, tiles = pcall(M.mood_tiles, u)
        if ok and type(tiles) == 'table' then
            for _, t in ipairs(tiles) do
                local k = t.x .. ',' .. t.y .. ',' .. t.z
                if not seen[k] then
                    seen[k] = true
                    table.insert(out, t)
                end
            end
        end
    end
    return out
end

local function in_burrow(b, t)
    local ok, yes = pcall(dfhack.burrows.isAssignedTile, b, xyz2pos(t.x, t.y, t.z))
    return ok and yes == true
end

-- {moods, tiles, added, already, dry_run}: the gathering moods' tiles put in
-- burrow b (the AI shelter; never another burrow)
function add_mood_spots(b, dry_run)
    local units = gathering_moods()
    local r = {moods = #units, tiles = 0, added = 0, already = 0, dry_run = dry_run or nil}
    if not b or #units == 0 then return r end
    local spots = mood_spots(units)
    r.tiles = #spots
    for _, t in ipairs(spots) do
        if in_burrow(b, t) then
            r.already = r.already + 1
        elseif dry_run then
            r.added = r.added + 1
        elseif pcall(dfhack.burrows.setAssignedTile, b, xyz2pos(t.x, t.y, t.z), true) then
            r.added = r.added + 1
        end
    end
    return r
end

-- the section
function report()
    local out = {}
    local okc, c = pcall(cancels_memo)
    out.cancels = okc and c or {}
    local okw, w = pcall(webs_memo)
    out.webs = okw and w or nil
    local units = gathering_moods()
    if #units > 0 then
        local b = shelter_burrow()
        if b then
            local spots = mood_spots(units)
            local n = 0
            for _, t in ipairs(spots) do if not in_burrow(b, t) then n = n + 1 end end
            out.shelter = {moods = #units, tiles = #spots, outside = n}
        end
    end
    local okh, hh = pcall(hold_report)
    if okh and hh then out.hospital_hold = hh end
    local okp, hc = pcall(cap_report)
    if okp and hc then out.hospital_cap = hc end
    return out
end

-- the action: the gathering moods' tiles put in the AI shelter
function act_mood_shelter(a)
    local b = shelter_burrow()
    if not b then return {ok = false, rejected = true, error = 'no AI shelter burrow yet'} end
    local r = add_mood_spots(b, a and a.dry_run == true)
    if r.moods == 0 then
        return {ok = false, rejected = true, error = 'no dwarf in a strange mood with a job'}
    end
    if r.added == 0 then
        r.ok, r.rejected = false, true
        r.error = 'the moods\' workshops and materials are inside the shelter already (' .. r.already .. ' tiles)'
        return r
    end
    r.ok = true
    return r
end

-- --- the hospital's thread and cloth for a strange mood (item2) -----------------------
--
-- B (24 Nov) and others: every thread in the fort lay in the hospital's
-- chests (the hospital location's supply quota), so a mood wanting cloth or
-- thread never had it: the loom wove nothing (no free thread), and a mood
-- takes nothing of the hospital's (ai-moods counts it 'hospital'). Edzul died
-- of thirst in his mood, Udib went raving. While a mood waits, the hospital's
-- desired thread (and cloth, for a cloth mood) is set to 0 so it pulls no more
-- back, the first values kept in the save's site data (HOSPITAL_HOLD_KEY), and
-- as much of the mood's kind as it lacks is set on the ground just outside the
-- hospital's zones (ai-moods counts an item on a hospital zone's floor as the
-- hospital's too), unforbidden. restore puts the quotas back (after a reload
-- too: read from the site data); the brain asks it once no mood waits.
HOSPITAL_HOLD_KEY = 'ai-overseer/hospital-hold'
RELEASE_MAX = 10                -- items released a call at most
RELEASE_RADIUS = 12             -- tiles searched round an item for one outside the hospital
THREAD_WHOLE = 15000            -- a whole spun thread (lua/ai-bridge-report-supplies.lua's)
CLOTH_WHOLE = 10000             -- a whole cloth (ai-moods CLOTH_DIM)
local FIBRES = {plant = true, silk = true, yarn = true, any = true}
local QUOTAS = {'thread', 'cloth'}

-- the site's hospital locations (DF's abstract buildings, type HOSPITAL), or the one of this id
function hospital_locations(id)
    local out = {}
    pcall(function()
        local site = dfhack.world.getCurrentSite()
        for _, loc in ipairs(site and site.buildings or {}) do
            local gone = false
            pcall(function() gone = loc.flags.DOES_NOT_EXIST == true end)
            local ok, yes = pcall(function() return df.abstract_building_type[loc:getType()] == 'HOSPITAL' end)
            if not gone and ok and yes and (id == nil or loc.id == id) then table.insert(out, loc) end
        end
    end)
    return out
end

-- the save's record: {locs = {{id, thread, cloth}...} (the first desired
-- values, DF's units), at = tick lowered, released = {fibre = tick}}
function hold_get()
    local d = U.site_get(HOSPITAL_HOLD_KEY, {})
    if type(d) ~= 'table' then d = {} end
    if type(d.locs) ~= 'table' then d.locs = {} end
    if type(d.released) ~= 'table' then d.released = {} end
    return d
end

-- the section's part: nil while nothing is held
function hold_report()
    local d = hold_get()
    if #d.locs == 0 and next(d.released) == nil then return nil end
    local list = {}
    for _, e in ipairs(d.locs) do
        table.insert(list, {id = tonumber(e.id), thread = tonumber(e.thread), cloth = tonumber(e.cloth)})
    end
    return {locations = #d.locs, at = tonumber(d.at), released = d.released, list = list}
end

local function hold_entry(d, id)
    for _, e in ipairs(d.locs) do
        if tonumber(e.id) == id then return e end
    end
    return nil
end

-- the location's desired thread (and cloth) set to 0, the value before kept
-- once (a value raised again while held, by DF or the player, is the one
-- kept). Returns how many quotas were lowered now.
local function lower(loc, d, what, dry_run)
    local c = loc:getContents()
    local e = hold_entry(d, loc.id)
    local fresh = e == nil
    e = e or {id = loc.id}
    local n = 0
    for _, k in ipairs(QUOTAS) do
        if what[k] then
            local cur = tonumber(c['desired_' .. k]) or 0
            if cur > 0 then
                e[k] = cur
                n = n + 1
                if not dry_run then
                    c['desired_' .. k] = 0
                    pcall(function() c.need_more[k] = false end)
                end
            end
        end
    end
    if fresh and (e.thread or e.cloth) and not dry_run then table.insert(d.locs, e) end
    return n
end

-- (0.105.112) the standing cap's record (hospital_cap): {caps = {{id,
-- thread, cloth}...} (DF's units, the quotas the AI last set), at, tried}
HOSPITAL_CAP_KEY = 'ai-overseer/hospital-cap'
function cap_get()
    local d = U.site_get(HOSPITAL_CAP_KEY, {})
    if type(d) ~= 'table' then d = {} end
    if type(d.caps) ~= 'table' then d.caps = {} end
    return d
end

local function cap_entry(d, id)
    for _, e in ipairs(d.caps) do
        if tonumber(e.id) == id then return e end
    end
    return nil
end

-- the capped quota of a location (DF's units), or nil when the AI set none
function cap_units(id, k)
    local e = cap_entry(cap_get(), id)
    return e and tonumber(e[k]) or nil
end

-- the quotas put back as they were (a quota the player set meanwhile, not 0,
-- is left as it is), (0.105.112) never above the standing cap; the record cleared
function restore_quotas(dry_run)
    local d = hold_get()
    local r = {locations = #d.locs, restored = 0, gone = 0, dry_run = dry_run or nil}
    for _, e in ipairs(d.locs) do
        local loc = hospital_locations(tonumber(e.id))[1]
        if not loc then
            r.gone = r.gone + 1
        else
            pcall(function()
                local c = loc:getContents()
                for _, k in ipairs(QUOTAS) do
                    local was = tonumber(e[k])
                    -- (0.105.112) never above the standing cap (hospital_cap)
                    local cap = cap_units(tonumber(e.id), k)
                    if was and cap and was > cap then was = cap end
                    if was and was > 0 and (tonumber(c['desired_' .. k]) or 0) == 0 then
                        if not dry_run then c['desired_' .. k] = was end
                        r.restored = r.restored + 1
                    end
                end
            end)
        end
    end
    if not dry_run and (#d.locs > 0 or next(d.released) ~= nil) then U.site_put(HOSPITAL_HOLD_KEY, {}) end
    return r
end

-- an item kept in one of the hospital's chests (in a bag in one too); false
-- for a container in a job (being hauled)
local function in_box(it, set)
    local up = dfhack.items.getContainer(it)
    for _ = 1, 4 do
        if not up then return false end
        if up.flags.in_job then return false end
        local b = dfhack.items.getHolderBuilding(up)
        if b then return set[b.id] == true end
        up = dfhack.items.getContainer(up)
    end
    return false
end

local function zone_ids(zones)
    local ids = {}
    for _, z in ipairs(zones or {}) do if z.id then ids[z.id] = true end end
    return ids
end

-- a tile the item can lie on outside every hospital zone, reached from
-- where it lies: walkable, the same walk group, no building on it but a
-- zone or a stockpile (an item on a workshop's or furniture's tile may be
-- taken for it)
local FLOOR_OK = {Civzone = true, Stockpile = true}
local function tile_ok(p, g0, ids)
    local okg, g = pcall(dfhack.maps.getWalkableGroup, p)
    if not okg or g ~= g0 then return false end
    local okb, b = pcall(dfhack.buildings.findAtTile, p)
    if not okb then return false end
    if b ~= nil then
        local okt, t = pcall(function() return df.building_type[b:getType()] end)
        if not (okt and FLOOR_OK[t]) then return false end
    end
    local okz, zs = pcall(dfhack.buildings.findCivzonesAt, p)
    if not okz then return false end
    for _, z in ipairs(zs or {}) do
        if ids[z.id] then return false end
    end
    return true
end

function outside_tile(x, y, z, ids)
    local okg, g0 = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    if not okg or type(g0) ~= 'number' or g0 == 0 then return nil end
    for r = 1, RELEASE_RADIUS do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local p = xyz2pos(x + dx, y + dy, z)
                    if tile_ok(p, g0, ids) then return p end
                end
            end
        end
    end
    return nil
end

local UNFREE_OK = {forbid = true, dump = true}

-- the hospital's items of a kind (THREAD or CLOTH) and fibre, whole, that no
-- job, owner or carrier holds: in its chests or on its zones' floor
local function hospital_items(M, tname, fibre, whole, want)
    local out = {}
    local set, zones = M.hospital_boxes()
    if next(set or {}) == nil and #(zones or {}) == 0 then return out end
    local okl, list = pcall(function() return df.global.world.items.other[tname] end)
    if not okl or not list then return out end
    for _, it in ipairs(list) do
        if #out >= want then break end
        local ok, take = pcall(function()
            if U.item_unfree(it, UNFREE_OK) then return false end
            if not (in_box(it, set or {}) or M.hospital_ground(it)) then return false end
            if fibre ~= 'any' and M.cloth_kind(it) ~= fibre then return false end
            local okd, d = pcall(function() return it:getTotalDimension() end)
            if okd and type(d) == 'number' and d > 0 and d < whole then return false end   -- a used piece
            return true
        end)
        if ok and take then table.insert(out, it) end
    end
    return out, zone_ids(zones)
end

-- the items set on the ground outside the hospital, unforbidden: (moved,
-- names, kinds released, how many found no tile)
local function release(M, tname, n, fibre, whole, dry_run, txt)
    local moved, names, kinds, stuck = 0, {}, {}, 0
    if n <= 0 then return moved, names, kinds, stuck end
    local items, ids = hospital_items(M, tname, fibre, whole, n)
    local spots = {}
    for _, it in ipairs(items) do
        local ok, done = pcall(function()
            local x, y, z = dfhack.items.getPosition(it)
            if not x then return false end
            local key = x .. ',' .. y .. ',' .. z
            if spots[key] == nil then spots[key] = outside_tile(x, y, z, ids or {}) or false end
            local p = spots[key]
            if not p then return false end
            if dry_run then return true end
            if dfhack.items.moveToGround(it, p) ~= true then return false end
            it.flags.forbid = false
            it.flags.dump = false
            return true
        end)
        if ok and done then
            moved = moved + 1
            local okk, k = pcall(M.cloth_kind, it)
            kinds[(okk and k) or fibre] = true
            if #names < 5 then
                local okd, d = pcall(dfhack.items.getReadableDescription, it)
                table.insert(names, okd and type(d) == 'string' and txt(d) or tname:lower())
            end
        else
            stuck = stuck + 1
        end
    end
    return moved, names, kinds, stuck
end

local function count(v)
    local n = math.tointeger(tonumber(v) or 0) or 0
    return math.max(0, math.min(RELEASE_MAX, n))
end

-- the action. a: {thread = n, cloth = n (each 0-10), kind = plant|silk|yarn|any,
-- location_id (one hospital; all of them when left out), restore, dry_run};
-- restore_only (set while the AI is halted): only the quotas put back
function act_hospital_release(a, txt)
    a = a or {}
    txt = txt or tostring
    local dry = a.dry_run == true
    if a.restore == true or a.restore_only == true then
        local r = restore_quotas(dry)
        if r.locations == 0 then
            return {ok = false, rejected = true, error = 'no hospital quota was lowered by the AI: nothing to put back'}
        end
        r.ok = true
        return r
    end
    local thread, cloth = count(a.thread), count(a.cloth)
    if thread == 0 and cloth == 0 then
        return {ok = false, rejected = true, error = 'hospital_release needs thread or cloth 1-10 (or restore)'}
    end
    local fibre = a.kind == nil and 'any' or tostring(a.kind)
    if not FIBRES[fibre] then
        return {ok = false, rejected = true, error = 'hospital_release kind is plant, silk, yarn or any'}
    end
    if #gathering_moods() == 0 then
        return {ok = false, rejected = true, error = 'no dwarf in a strange mood with a job: nothing released'}
    end
    local okm, M = pcall(reqscript, 'ai-moods')
    if not (okm and type(M) == 'table' and M.hospital_boxes and M.hospital_ground and M.cloth_kind) then
        return {ok = false, rejected = true, error = 'ai-moods could not be read'}
    end
    local id = math.tointeger(tonumber(a.location_id))
    local locs = hospital_locations(id)
    if #locs == 0 then
        return {ok = false, rejected = true, error = id and 'no such hospital' or 'the fort has no hospital'}
    end
    local d = hold_get()
    local lowered = 0
    for _, loc in ipairs(locs) do
        local ok, n = pcall(lower, loc, d, {thread = true, cloth = cloth > 0}, dry)
        if ok then lowered = lowered + n end
    end
    local mc, nc, kc, sc = release(M, 'CLOTH', cloth, fibre, CLOTH_WHOLE, dry, txt)
    -- (0.105.112 item3) a thread mood (a.part_ok) takes thread at 90% of whole (B's hospital
    -- thread was all 97-99%: none set out); the loom, for a cloth mood, a whole one
    local mt, nt, kt, st = release(M, 'THREAD', thread, fibre, a.part_ok == true and 13500 or THREAD_WHOLE, dry, txt)
    local names = nc
    for _, v in ipairs(nt) do if #names < 5 then table.insert(names, v) end end
    local now = U.now_tick(0)
    if not dry then
        for _, kinds in ipairs({kc, kt}) do
            for k in pairs(kinds) do d.released[k] = now end
        end
        if lowered > 0 and not d.at then d.at = now end
        if #d.locs > 0 or next(d.released) ~= nil then U.site_put(HOSPITAL_HOLD_KEY, d) end
        -- the moods' counts read again (an item moved is no new item: their cache keeps it 'hospital')
        if mc + mt > 0 then pcall(function() M.AVAIL_CACHE = {} end) end
    end
    local r = {cloth = mc, thread = mt, items = names, lowered = lowered, kind = fibre, dry_run = dry or nil}
    if sc + st > 0 then r.no_tile = sc + st end
    if mc + mt == 0 and lowered == 0 then
        r.ok, r.rejected = false, true
        r.error = 'nothing of that kind in the hospital that can be taken (whole, in no job, owned by nobody'
            .. (sc + st > 0 and ', with a tile outside the hospital in reach' or '') .. '), and its quotas are 0 already'
        return r
    end
    r.ok = true
    return r
end

-- --- (0.105.112) the hospital's standing thread and cloth cap -------------------------
--
-- B (24 Nov): four hospital locations, each wanting DF's 5 thread and 5 cloth
-- (desired_thread 75000, desired_cloth 50000): 17 of the fort's 19 plant
-- threads lay in their chests and no thread was free outside, so the moods
-- failed and the loom wove nothing. hospital_release lowered the quotas only
-- while a mood waited and put them back after. Now the brain
-- (brain/planner_hospital_stock.py) sets each hospital's thread and cloth
-- quota to what its patients plausibly need (whole items: a small base and
-- one more for each patient waiting for sutures or dressings, all on the
-- hospital with the most chests, 0 on the others), and the surplus items
-- (whole cloth, thread at least THREAD_SET_OUT_MIN) in the hospitals' chests
-- and on their floor are set out beside them (hospital_release's
-- release: unforbidden, for the haulers to take to a pile). A quota the
-- player set below the AI's last cap is never raised; while hospital_release
-- holds a quota at 0 the value kept for its restore is lowered to the cap
-- instead, and restore_quotas never puts back more than the cap.
CAP_MAX = 20                    -- whole items a location's quota at most
-- B's hospital thread was all 97-99% (dimension 14625-14940: a suture's
-- snip): none of it "whole". A thread this full is set out as surplus (a
-- thread mood takes it; the loom wants a whole one); cloth only whole (a
-- mood's cloth must be whole, ai-moods partial_cloth), the pieces stay for
-- the dressings
THREAD_SET_OUT_MIN = 13500

-- the section's part: nil before the AI ever capped
function cap_report()
    local d = cap_get()
    if #d.caps == 0 then return nil end
    local list = {}
    for _, e in ipairs(d.caps) do
        table.insert(list, {id = tonumber(e.id), thread = tonumber(e.thread), cloth = tonumber(e.cloth)})
    end
    local tried = nil
    if type(d.tried) == 'table' then
        tried = {thread = tonumber(d.tried.thread), cloth = tonumber(d.tried.cloth),
                 moved = tonumber(d.tried.moved), at = tonumber(d.tried.at)}
    end
    return {list = list, at = tonumber(d.at), tried = tried}
end

local function whole_count(v)
    local n = math.tointeger(tonumber(v) or -1)
    if not n or n < 0 then return nil end
    return math.min(CAP_MAX, n)
end

local UNITS = {thread = THREAD_WHOLE, cloth = CLOTH_WHOLE}

-- one location's quotas set to the cap (DF's units). Returns the changes:
-- {k = {from, to, held = true when the hold's kept value was lowered}}
local function cap_location(loc, caps, rec, hold, dry_run)
    local c = loc:getContents()
    local held = hold_entry(hold, loc.id)
    local prev = cap_entry(rec, loc.id)
    local out = {}
    for _, k in ipairs(QUOTAS) do
        local want = caps[k]
        if want then
            local units = want * UNITS[k]
            if held and tonumber(held[k]) then
                -- hospital_release holds it at 0: the value it keeps lowered instead
                local was = tonumber(held[k])
                if was > units then
                    out[k] = {from = was, to = units, held = true}
                    if not dry_run then held[k] = units end
                end
            else
                local cur = tonumber(c['desired_' .. k]) or 0
                local last = prev and tonumber(prev[k]) or nil
                -- lowered always; raised only from the AI's own last cap
                if cur > units or (cur < units and last ~= nil and cur == last) then
                    out[k] = {from = cur, to = units}
                    if not dry_run then
                        c['desired_' .. k] = units
                        if units < cur then pcall(function() c.need_more[k] = false end) end
                    end
                end
            end
        end
    end
    return out
end

-- the action. a: {caps = {{id, thread, cloth}...} (whole items, 0-20; a
-- hospital left out is not touched), set_out = {thread = n, cloth = n} (whole
-- items out of the hospitals' chests, 0-10 each), seen = {thread, cloth} (the
-- brain's counts, kept so it doesn't ask again for the same stock), dry_run}
function act_hospital_cap(a, txt)
    a = a or {}
    txt = txt or tostring
    local dry = a.dry_run == true
    if type(a.caps) ~= 'table' or #a.caps == 0 then
        return {ok = false, rejected = true, error = 'hospital_cap needs caps: {{id, thread, cloth}...}'}
    end
    local rec, hold = cap_get(), hold_get()
    local changed, names, missing = 0, {}, 0
    local hold_changed = false
    for _, e in ipairs(a.caps) do
        local id = math.tointeger(tonumber(type(e) == 'table' and e.id or nil))
        local loc = id and hospital_locations(id)[1]
        if not loc then
            missing = missing + 1
        else
            local caps = {thread = whole_count(e.thread), cloth = whole_count(e.cloth)}
            local ok, ch = pcall(cap_location, loc, caps, rec, hold, dry)
            if ok then
                for k, v in pairs(ch) do
                    changed = changed + 1
                    if v.held then hold_changed = true end
                    table.insert(names, ('hospital %d %s %d -> %d%s'):format(id, k, math.floor(v.from / UNITS[k]),
                        math.floor(v.to / UNITS[k]), v.held and ' (after the mood)' or ''))
                end
                if not dry then
                    local r = cap_entry(rec, id)
                    if not r then r = {id = id}; table.insert(rec.caps, r) end
                    for _, k in ipairs(QUOTAS) do
                        if caps[k] then r[k] = caps[k] * UNITS[k] end
                    end
                end
            end
        end
    end
    -- the surplus whole items set out beside the hospital
    local so = type(a.set_out) == 'table' and a.set_out or {}
    local nt, nc = count(so.thread), count(so.cloth)
    local mt, mc, stuck, moved_names = 0, 0, 0, {}
    if nt + nc > 0 then
        local okm, M = pcall(reqscript, 'ai-moods')
        if okm and type(M) == 'table' and M.hospital_boxes and M.hospital_ground and M.cloth_kind then
            local n1, s1, n2, s2, k1, k2
            mc, n1, k1, s1 = release(M, 'CLOTH', nc, 'any', CLOTH_WHOLE, dry, txt)
            mt, n2, k2, s2 = release(M, 'THREAD', nt, 'any', THREAD_SET_OUT_MIN, dry, txt)
            stuck = s1 + s2
            for _, v in ipairs(n1) do table.insert(moved_names, v) end
            for _, v in ipairs(n2) do if #moved_names < 5 then table.insert(moved_names, v) end end
            if not dry and mc + mt > 0 then pcall(function() M.AVAIL_CACHE = {} end) end
        end
    end
    if not dry then
        local now = U.now_tick(0)
        if changed > 0 then rec.at = now end
        if nt + nc > 0 then
            local seen = type(a.seen) == 'table' and a.seen or {}
            rec.tried = {thread = tonumber(seen.thread), cloth = tonumber(seen.cloth), moved = mt + mc, at = now}
        end
        U.site_put(HOSPITAL_CAP_KEY, rec)
        if hold_changed then U.site_put(HOSPITAL_HOLD_KEY, hold) end
    end
    local r = {changed = changed, quotas = names, thread_out = mt, cloth_out = mc, items = moved_names,
               dry_run = dry or nil}
    if missing > 0 then r.no_such_hospital = missing end
    if stuck > 0 then r.no_tile = stuck end
    if changed == 0 and mt + mc == 0 then
        r.ok, r.rejected = false, true
        r.error = 'the hospitals\' thread and cloth quotas are at the cap already'
            .. (nt + nc > 0 and ', and no whole thread or cloth in their chests could be set out (in a job, owned, used, or no tile in reach)' or '')
        return r
    end
    r.ok = true
    return r
end
