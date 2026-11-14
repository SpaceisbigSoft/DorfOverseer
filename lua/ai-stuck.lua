-- (0.105.45) The sweep for things stuck "in progress": the AI's own works
-- that entered a state and never left it.
--
-- Why (Phase 11 (d)): over many runs forts lost dwarves or stalled because
-- something the AI started stayed "in progress" for good: a gate the game
-- held shut (0.105.32), a cistern step, a well dig, a level kept "digging"
-- with nothing dug, a squad's kill order on a target long gone, a work order
-- neither done nor cancelled, a lever pull job never done (the cavern
-- well's 49 tries, 0.104.164). Each of those had (or got) a rule of its own;
-- this one pass lists them all with the game tick they entered their state
-- and the evidence that they move (or don't), so the brain
-- (brain/planner_stuck.py) can nudge, then retire, what no rule moves.
--
-- What it lists (each in its own pcall; the AI's own only):
--   project    an open level (dig / furnish / decorate), since its phase began
--              (the record's own start), the brain joins its dig counts from
--              the projects section;
--   cistern    the cistern in a stage before `done` (its relinks, leaks and
--              depth while filling as progress);
--   waterwork  a moat, pump, irrigation, magma or power work in a stage
--              before `done` (`held` is the waterworks rule's own), since
--              its stage began (the work's own `since`);
--   lever      a PullLever job on one of the AI's levers ("AI ..." names but
--              the player's own "AI gate", the cistern's, the wells' shaft
--              levers, the waterworks'), whether a dwarf has taken it;
--   squad      an AI kill order (titled "AI overseer") whose targets are all
--              dead, gone from the map or caged;
--   order      a one-time manager order the AI placed, its amount left as
--              progress;
--   gate       an entrance closing on gate pieces the AI planned, their jobs
--              and workers, since the scan first read it closing.
--
-- The tick each thing entered its state, and the tick its progress last
-- changed, are kept in the save (`ai-overseer/stuck`, written only when
-- something changed): a thing first seen gets "now" for both, unless its own
-- record knows when its state began. The list is capped (LIST_MAX), oldest
-- first.
--
--   report()                the `stuck` section: {list = [{kind, id, key,
--                           state, since, moved, age_days, still_days,
--                           progress, job, worker, suspended, what, ...}],
--                           total, tick, errors}
--   reset(a, dry)           the `stuck_reset` action: {kind = 'lever', id,
--                           mode = 'reissue' | 'drop'}: the lever's waiting
--                           pull jobs taken off; 'reissue' queues the same
--                           pull afresh (an odd count of pulls: one; an even
--                           count undid itself: none). Only the AI's levers.
--@ module = true

local U = reqscript('ai-util')

SEEN_KEY = 'ai-overseer/stuck'
LIST_MAX = 40
DAY = 1200
YEAR = 403200
-- the stages a waterwork is still under way in (done, running, retired: over;
-- held: the waterworks rule retires those itself)
WORK_OPEN = {planned = true, digging = true, building = true, linking = true, filling = true, drying = true,
             finishing = true}
CISTERN_KEY = 'ai-overseer/cistern'
ORDERS_KEY = 'ai-overseer/orders'
PLAYER_LEVER = 'ai gate'      -- the player's own lever named for the AI to work: never touched here

-- --- pure helpers (tests/test_stuck.py runs these in lupa) -------------------

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

-- A {year, tick} date as ticks, or nil.
function tick_of(d)
    if type(d) ~= 'table' then return nil end
    local y, t = tonumber(d.year), tonumber(d.tick)
    if not y then return nil end
    return math.tointeger(y * YEAR + (t or 0))
end

function row_key(r)
    if type(r.key) == 'string' then return r.key end
    return tostring(r.kind) .. ':' .. tostring(r.id)
end

-- Each row's `since` (the tick it entered its state) and `moved` (its
-- progress last changed) from what was kept, the record's own start, or now.
-- Returns the new kept table (only the rows seen now) and whether it changed.
function track(seen, rows, now)
    seen = type(seen) == 'table' and seen or {}
    local out, changed = {}, false
    for _, r in ipairs(rows) do
        local k = row_key(r)
        r.key = k
        local prev = type(seen[k]) == 'table' and seen[k] or nil
        local st = tostring(r.state or '')
        local pg = r.progress ~= nil and tostring(r.progress) or ''
        local own = math.tointeger(r.since)
        local rec
        if not prev or prev.s ~= st then
            -- a new thing or a new state: its own start if the record knows it,
            -- else now; progress counted from now (nothing is known before)
            rec = {s = st, p = pg, since = own or now, moved = now}
            changed = true
        elseif prev.p ~= pg then
            rec = {s = st, p = pg, since = math.tointeger(prev.since) or own or now, moved = now}
            changed = true
        else
            rec = {s = st, p = pg, since = math.tointeger(prev.since) or own or now,
                   moved = math.tointeger(prev.moved) or now}
        end
        out[k] = rec
        r.since = rec.since
        r.moved = math.max(rec.moved, rec.since)
        r.age_days = math.max(0, (now - r.since) // DAY)
        r.still_days = math.max(0, (now - r.moved) // DAY)
    end
    for k in pairs(seen) do
        if out[k] == nil then changed = true end
    end
    return out, changed
end

-- Oldest first (then by key), at most `max`; and how many there were.
function rank(rows, max)
    table.sort(rows, function(a, b)
        if a.since ~= b.since then return (a.since or 0) < (b.since or 0) end
        return tostring(a.key) < tostring(b.key)
    end)
    local out = {}
    for i = 1, math.min(#rows, max or LIST_MAX) do out[i] = rows[i] end
    return out, #rows
end

-- Is this lever name one the AI gave? ("AI gate lever", "AI moat", "AI pump",
-- the scan's "AI gate <n> lever"...), not the player's own "AI gate".
function ai_lever_name(name)
    local n = tostring(name or ''):lower()
    return n:find('^ai ') ~= nil and n ~= PLAYER_LEVER
end

-- How a kill order's targets stand: {live, dead, gone, caged}.
-- `look(id)` gives 'live', 'dead', 'gone' or 'caged'.
function targets_state(ids, look)
    local c = {live = 0, dead = 0, gone = 0, caged = 0}
    for _, id in ipairs(ids) do
        local s = look(id)
        c[s] = (c[s] or 0) + 1
    end
    return c
end

-- --- reads of the game (each behind pcall) ------------------------------------

local function unit_state(id)
    local ok, s = pcall(function()
        local u = df.unit.find(id)
        if not u then return 'gone' end
        if dfhack.units.isDead(u) then return 'dead' end
        if u.flags1.caged then return 'caged' end
        local oka, active = pcall(dfhack.units.isActive, u)
        if oka and active == false then return 'gone' end
        return 'live'
    end)
    return ok and s or 'live'      -- unread: counted as alive (never cleared on a guess)
end

local function pull_jobs(b)
    local out = {}
    for _, j in ipairs(b and b.jobs or {}) do
        if j.job_type == df.job_type.PullLever then table.insert(out, j) end
    end
    return out
end

-- The AI's own lever ids: named by the AI, the cistern's, the wells' shaft
-- levers, the waterworks'.
function ai_lever_ids()
    local ids = {}
    pcall(function()
        local d = U.site_get(CISTERN_KEY, {})
        if math.tointeger(d.lever_id) then ids[d.lever_id] = true end
    end)
    pcall(function()
        for _, p in ipairs(reqscript('ai-builder').load_projects().list or {}) do
            local sg = type(p.shaft_gate) == 'table' and p.shaft_gate or nil
            if sg and math.tointeger(sg.lever_id) then ids[sg.lever_id] = true end
        end
    end)
    pcall(function()
        for _, wk in pairs(reqscript('ai-waterworks').load_state().works or {}) do
            if type(wk) == 'table' and math.tointeger(wk.lever_id) then ids[wk.lever_id] = true end
        end
    end)
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and ai_lever_name(b.name) then ids[b.id] = true end
        end
    end)
    return ids
end

local function lever_of(id)
    local ok, b = pcall(df.building.find, id)
    if not ok or not b then return nil end
    local okl, lever = pcall(function() return b.trap_type == df.trap_type.Lever end)
    if not okl or not lever then return nil end
    return b
end

local function ai_lever(b)
    if not b then return false end
    if tostring(b.name or ''):lower() == PLAYER_LEVER then return false end
    return ai_lever_ids()[b.id] == true
end

-- --- the collectors ----------------------------------------------------------

local function projects(rows)
    local B = reqscript('ai-builder')
    for _, p in ipairs(B.load_projects().list or {}) do
        if p.phase == 'dig' or p.phase == 'furnish' or p.phase == 'decorate' then
            local since = p.phase == 'dig' and tick_of(p.started)
                or p.phase == 'furnish' and (tick_of(p.furnish_started) or tick_of(p.started))
                or tick_of(p.decorate_started)
            table.insert(rows, {kind = 'project', id = p.id, state = p.phase, since = since, what = p.kind,
                                cavern = type(p.summary) == 'table' and p.summary.cavern and true or nil})
        end
    end
end

local function cistern(rows)
    local d = U.site_get(CISTERN_KEY, {})
    if not d.stage or d.stage == 'done' then return end
    local depth = ''
    if d.stage == 'filling' and type(d.plan) == 'table' and type(d.plan.well) == 'table' then
        pcall(function()
            local t = reqscript('ai-builder').tile_info(d.plan.well.x, d.plan.well.y, d.plan.cistern.z)
            depth = t and t.liquid and t.depth or 0
        end)
    end
    table.insert(rows, {kind = 'cistern', id = 'cistern', state = d.stage, what = 'cistern',
                        progress = ('%s/%s/%s/%s'):format(tostring(d.relinks or 0), tostring(d.leaks or 0),
                                                          tostring(d.unsealed_refusals or 0), tostring(depth))})
end

local function waterworks(rows)
    for id, wk in pairs(reqscript('ai-waterworks').load_state().works or {}) do
        if type(wk) == 'table' and WORK_OPEN[wk.stage] then
            local plan = type(wk.plan) == 'table' and wk.plan or {}
            local placed = 0
            for _ in pairs(type(wk.placed) == 'table' and wk.placed or {}) do placed = placed + 1 end
            -- progress: a long dig's segment, its floodgate's floor, the pieces
            -- placed, the links asked, the depth and the wet tiles
            table.insert(rows, {kind = 'waterwork', id = tostring(id), state = wk.stage, what = wk.kind,
                                shop = plan.shop, since = math.tointeger(wk.since),
                                progress = ('%s/%s/%d/%s/%s/%s'):format(tostring(wk.seg or ''), tostring(wk.dig2 or ''),
                                                                    placed, tostring(wk.relinks or ''),
                                                                    tostring(wk.depth or ''), tostring(wk.wet or ''))})
        end
    end
end

local function levers(rows)
    local ids = ai_lever_ids()
    for id in pairs(ids) do
        local b = lever_of(id)
        if b and tostring(b.name or ''):lower() ~= PLAYER_LEVER then
            local jobs = pull_jobs(b)
            if #jobs > 0 then
                local worker, suspended = false, false
                for _, j in ipairs(jobs) do
                    pcall(function() if dfhack.job.getWorker(j) then worker = true end end)
                    pcall(function() if j.flags.suspend then suspended = true end end)
                end
                -- its state is the first job's id: a new pull is a new state
                -- a dwarf taking it (or dropping it) is progress
                table.insert(rows, {kind = 'lever', id = b.id, state = 'pull:' .. tostring(jobs[1].id),
                                    progress = worker and 1 or 0, job = true, worker = worker, suspended = suspended or nil, pulls = #jobs,
                                    what = tostring(b.name or ''), x = b.centerx, y = b.centery, z = b.z})
            end
        end
    end
end

local function squads(rows)
    local fort = U.fort_entity()
    if not fort then return end
    local title = 'AI overseer'
    pcall(function() title = reqscript('ai-military').AI_ORDER_TITLE or title end)
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq then
            for _, o in ipairs(sq.orders) do
                local ok, row = pcall(function()
                    if o.title ~= title or not df.squad_order_kill_listst:is_instance(o) then return nil end
                    local ids = {}
                    for _, id in ipairs(o.units) do table.insert(ids, id) end
                    if #ids == 0 then return nil end
                    local c = targets_state(ids, unit_state)
                    local since
                    pcall(function()
                        if o.year ~= nil and o.year >= 0 then since = U.abs_tick(o.year, o.year_tick) end
                    end)
                    return {kind = 'squad', id = sid, state = c.live == 0 and 'kill_done' or 'kill',
                            since = math.tointeger(since), progress = c.live, targets = #ids, live = c.live,
                            dead = c.dead, gone = c.gone, caged = c.caged,
                            what = (function()
                                local okn, n = pcall(function() return dfhack.df2utf(dfhack.military.getSquadName(sid)) end)
                                return okn and n or ('squad ' .. sid)
                            end)()}
                end)
                if ok and row then table.insert(rows, row) break end
            end
        end
    end
end

local function orders(rows)
    local ids = U.site_get(ORDERS_KEY, {ids = {}}).ids
    if type(ids) ~= 'table' then return end
    for _, o in ipairs(df.global.world.manager_orders.all) do
        if ids[tostring(o.id)] == true then
            local once = true
            pcall(function() once = df.workquota_frequency_type[o.frequency] == 'OneTime' end)
            if once then
                local okv, validated = pcall(function() return o.status.validated == true end)
                table.insert(rows, {kind = 'order', id = o.id, state = 'open', progress = o.amount_left,
                                    left = o.amount_left, total = o.amount_total,
                                    what = df.job_type[o.job_type] or tostring(o.job_type),
                                    validated = okv and validated or nil})
            end
        end
    end
end

local function gate_key(x, y, z) return (z * 4096 + y) * 4096 + x end

local function gates(rows)
    local G = reqscript('ai-gates')
    local GS = G.GATES or {}
    for _, e in ipairs(GS.entrances or {}) do
        if e.closing and not e.sealed and type(e.pending_ids) == 'table' and #e.pending_ids > 0 then
            local pieces, jobs, worker, suspended = 0, 0, false, false
            for _, bid in ipairs(e.pending_ids) do
                local okb, b = pcall(df.building.find, bid)
                if okb and b then
                    local okm, mine = pcall(G.ai_planned_building, b)
                    if okm and mine then
                        pieces = pieces + 1
                        for _, j in ipairs(b.jobs or {}) do
                            jobs = jobs + 1
                            pcall(function() if dfhack.job.getWorker(j) then worker = true end end)
                            pcall(function() if j.flags.suspend then suspended = true end end)
                        end
                    end
                end
            end
            if pieces > 0 then
                local since = GS.closing_since and GS.closing_since[gate_key(e.x, e.y, e.z)]
                table.insert(rows, {kind = 'gate', id = e.id, key = ('gate:%d,%d,%d'):format(e.x, e.y, e.z),
                                    state = 'closing', since = math.tointeger(since), progress = pieces,
                                    pieces = pieces, job = jobs > 0, worker = worker, suspended = suspended or nil,
                                    what = tostring(e.kind or 'entrance'), x = e.x, y = e.y, z = e.z})
            end
        end
    end
end

COLLECTORS = {{'project', projects}, {'cistern', cistern}, {'waterwork', waterworks}, {'lever', levers},
              {'squad', squads}, {'order', orders}, {'gate', gates}}

function report()
    local now = now_tick()
    local rows, errors = {}, nil
    for _, c in ipairs(COLLECTORS) do
        local ok, err = pcall(c[2], rows)
        if not ok then
            errors = errors or {}
            errors[c[1]] = tostring(err):sub(1, 120)
        end
    end
    local kept = U.site_get(SEEN_KEY, {})
    local items, changed = track(type(kept.items) == 'table' and kept.items or {}, rows, now)
    -- (a collector that failed keeps its old rows: its things are not "new" next time)
    if errors then
        for k, v in pairs(type(kept.items) == 'table' and kept.items or {}) do
            local kind = tostring(k):match('^([%a_]+):')
            if items[k] == nil and kind and errors[kind] then items[k] = v; end
        end
    end
    if changed then U.site_put(SEEN_KEY, {items = items}) end
    local list, total = rank(rows, LIST_MAX)
    return {list = list, total = total, tick = now, errors = errors}
end

-- --- the action ---------------------------------------------------------------

local function reject(why) return {ok = false, rejected = true, error = why} end

function reset(a, dry_run)
    if type(a) ~= 'table' or a.kind ~= 'lever' then return reject('stuck_reset: kind is lever') end
    local id = math.tointeger(tonumber(a.id))
    if not id then return reject('stuck_reset: id is the lever\'s building id') end
    local mode = a.mode or 'reissue'
    if mode ~= 'reissue' and mode ~= 'drop' then return reject('stuck_reset: mode is reissue or drop') end
    local b = lever_of(id)
    if not b then return reject(('stuck_reset: no lever %d'):format(id)) end
    if not ai_lever(b) then
        return reject(('stuck_reset: lever %d is not one of the AI\'s (the player\'s levers are left alone)'):format(id))
    end
    local jobs = pull_jobs(b)
    if #jobs == 0 then return reject(('stuck_reset: no pull job waits on lever %d'):format(id)) end
    local again = (mode == 'reissue' and #jobs % 2 == 1) and 1 or 0
    if dry_run then return {ok = true, dry_run = true, jobs = #jobs, queued = again} end
    local removed = 0
    for _, j in ipairs(jobs) do
        if pcall(dfhack.job.removeJob, j) then removed = removed + 1 end
    end
    if removed < #jobs then
        return {ok = false, error = ('stuck_reset: %d of %d pull job(s) on lever %d could not be taken off')
                                        :format(#jobs - removed, #jobs, id), removed = removed}
    end
    local queued = 0
    if again == 1 then
        local okr, out, rv = pcall(dfhack.run_command_silent, 'lever', 'pull', '--id', tostring(id))
        if not okr or rv ~= CR_OK then
            return {ok = false, removed = removed,
                    error = ('stuck_reset: the old pull job(s) on lever %d taken off, the new pull refused (%s)')
                                :format(id, tostring(okr and out or rv):sub(1, 80))}
        end
        queued = 1
    end
    return {ok = true, removed = removed, queued = queued}
end
