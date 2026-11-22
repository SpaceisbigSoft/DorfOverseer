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
