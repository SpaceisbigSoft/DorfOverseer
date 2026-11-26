-- ai-bridge-orders-jobs: the actions on the orders and jobs the AI has
-- queued: approve, unsuspend, the bootstrap chair, the bench jobs, the
-- orphaned jobs, the order slots, cancel an order, and the DFHack tools'
-- switch (act_tool).
--
-- A part of ai-bridge.lua (0.105.119, split out of ai-bridge-orders.lua when
-- it reached the size limit), loaded by it right after ai-bridge-orders into
-- its own environment, as every part: what is global here is the bridge's
-- (reachable as reqscript('ai-bridge').<name>), and the bridge's shared
-- helpers are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-orders-jobs is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-orders-jobs'] = '0.105.128'   -- bumped with BRIDGE_VERSION

-- True if DF's own screens might be holding this order right now. Deleting an
-- order that a screen points at would crash DF, so we refuse in that case.
local function order_in_use_by_ui(order)
    local ok, busy = pcall(function()
        local mi = df.global.game.main_interface
        local wo = mi.info.work_orders
        if mi.info.open and mi.info.current_mode == df.info_interface_mode_type.WORK_ORDERS then
            return true
        end
        if mi.job_details.open then return true end
        return wo.conditions.wq == order or wo.entering_wq == order
            or wo.b_entering_wq == order or mi.job_details.wq == order
            or mi.image_creator.ics.wq == order
    end)
    return (not ok) or busy -- if we can't tell, assume it's in use
end

-- Free an order the same way DFHack's `orders clear` does.
local function free_order(order)
    for _, c in ipairs(order.item_conditions) do c:delete() end
    for _, c in ipairs(order.order_conditions) do c:delete() end
    if order.items then
        for _, e in ipairs(order.items.elements) do e:delete() end
        order.items:delete()
    end
    order:delete()
end

-- (0.101.2) The manager approves ("validates") work orders in an office with
-- a chair; a new fort's office waits for a chair that needs an approved
-- order (a deadlock: two test forts never brewed, cooked or made a bed).
-- The AI's own orders that have waited are approved here, as the manager
-- would; never the player's. A working manager goes on approving the rest.
function act_approve_orders(a)
    local ids = ai_orders().ids
    local n = 0
    for _, o in ipairs(df.global.world.manager_orders.all) do
        if ids[tostring(o.id)] and not o.status.validated then
            if not a.dry_run then o.status.validated = true end
            n = n + 1
        end
    end
    if n == 0 then return reject('no unapproved orders of the AI\'s') end
    return {ok = true, approved = n, dry_run = a.dry_run or nil}
end

-- (0.104.13) The AI's own orders' jobs a workshop suspended are taken up
-- again (the player's "resume" in the workshop). Only jobs made by the AI's
-- orders: never a construction (suspendmanager's) or a player's job.
function act_unsuspend_orders(a)
    local ids = ai_orders().ids
    local want = whole_number(a.order_id)
    local n, kinds = 0, {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j and j.flags.suspend then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and ids[tostring(oid)] and (not want or want == oid) then
                if not a.dry_run then j.flags.suspend = false end
                n = n + 1
                local k = df.job_type[j.job_type] or tostring(j.job_type)
                kinds[k] = (kinds[k] or 0) + 1
            end
        end
        link = link.next
    end
    if n == 0 then return reject('no suspended job of the AI\'s orders') end
    return {ok = true, unsuspended = n, kinds = kinds, dry_run = a.dry_run or nil}
end

-- (0.105.33) one job on a workshop's bench, of one wood or one hard boulder
-- (the chair and the coffin/slab jobs share it)
local function bench_job(b, jt, wood)
    local job = dfhack.job.createLinked()
    job.job_type = jt
    job.mat_type = -1
    local ji = df.job_item:new()
    ji.mat_type = -1
    ji.mat_index = -1
    ji.quantity = 1
    if wood then
        job.material_category.wood = true
        ji.item_type = df.item_type.WOOD
        ji.vector_id = df.job_item_vector_id.WOOD
    else
        ji.item_type = df.item_type.BOULDER
        ji.vector_id = df.job_item_vector_id.BOULDER
        ji.flags3.hard = true
    end
    job.job_items.elements:insert('#', ji)
    dfhack.job.assignToWorkshop(job, b)
    return job
end

-- (0.101.4) Below 20 citizens orders need no approval, but the manager hands
-- them out only from an office with a chair; with no chair in the fort every
-- order waits forever (the Enxah fort never ran one in 3 years). One chair is
-- made the old way: a job put straight on a carpenter's (wood) or mason's
-- (stone) bench, the way a player clicks "add job" in the workshop.
function act_bootstrap_chair(a)
    local benches = {}
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        if (b.type == df.workshop_type.Carpenters or b.type == df.workshop_type.Masons)
                and b:getBuildStage() >= b:getMaxBuildStage() then
            for _, j in ipairs(b.jobs) do
                if j.job_type == df.job_type.ConstructThrone then
                    return reject('a chair job is already waiting at a workshop')
                end
            end
            table.insert(benches, b)
        end
    end
    table.sort(benches, function(x, y)   -- wood first: a carpenter's chair
        return (x.type == df.workshop_type.Carpenters and 0 or 1) < (y.type == df.workshop_type.Carpenters and 0 or 1)
    end)
    local b = benches[1]
    if not b then return reject('no finished carpenter\'s or mason\'s workshop') end
    if not (dfhack.job.createLinked and dfhack.job.assignToWorkshop) then
        return reject('this DFHack has no workshop job API')
    end
    local wood = b.type == df.workshop_type.Carpenters
    if a.dry_run then return {ok = true, dry_run = true, workshop = b.id, wood = wood} end
    local job = bench_job(b, df.job_type.ConstructThrone, wood)
    return {ok = true, workshop = b.id, job_id = job.id, material = wood and 'wood' or 'stone'}
end

-- (0.104.21) Jobs put straight on a workshop's bench when the AI's order for
-- them makes none (Enxah: a 29-coffin order took no job at the masons in
-- two game months while a tomb level waited and 106 dead lay unburied).
-- Only coffins so far: stone at a mason's, or wood at a carpenter's.
-- (0.104.32) and blank slabs: autoslab's engrave jobs waiting for one filled
-- the masons' job list (10 jobs: 7 of them "needs unengraved slab"), so no
-- slab and too few coffins could ever reach the bench (13 ghosts, 90 dead)
BENCH_JOBS = {
    coffin = {job = 'ConstructCoffin', shops = {Masons = 'stone', Carpenters = 'wood'}},
    slab = {job = 'ConstructSlab', shops = {Masons = 'stone'}},
}
-- jobs that may be lifted off a full bench to make room (make_room): only
-- unworked ones of orders that are not the AI's, waiting on what the bench
-- jobs make; the order makes them again later
BENCH_LIFT = {EngraveSlab = true}
BENCH_MAX = 5

-- (0.104.34) Jobs at a workshop whose work order no longer exists: the AI
-- cancels an order it finds stuck, and DF leaves the order's jobs on the
-- bench, unworked for good (Enxah: 14 jewellery and craft jobs on three
-- craftsdwarf's benches, 2 engrave jobs on the masons'). Only unworked jobs
-- with an order id that is gone; never a player's job (no order) or a
-- construction. count_only: just count them.
-- (0.105.33) only_id: just the jobs of that (cancelled) order
function orphan_jobs(count_only, max, only_id)
    local live = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do live[o.id] = true end
    local found, kinds = {}, {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and not live[oid] and (only_id == nil or oid == only_id)
                    and not dfhack.job.getWorker(j)
                    and dfhack.job.getHolder and dfhack.job.getHolder(j) then
                table.insert(found, j)
                local k = df.job_type[j.job_type] or tostring(j.job_type)
                kinds[k] = (kinds[k] or 0) + 1
            end
        end
        link = link.next
    end
    if count_only then return #found end
    local n = 0
    for i = 1, math.min(#found, max or 30) do
        if pcall(dfhack.job.removeJob, found[i]) then n = n + 1 end
    end
    return n, kinds, #found
end

function act_clear_orphan_jobs(a)
    if a.dry_run then
        local n = orphan_jobs(true)
        if n == 0 then return reject('no job without its order') end
        return {ok = true, dry_run = true, orphans = n}
    end
    local n, kinds, found = orphan_jobs(false, whole_number(a.max) or 30)
    if found == 0 then return reject('no job without its order') end
    if n == 0 then return {ok = false, error = 'the game would not remove the jobs'} end
    return {ok = true, removed = n, found = found, kinds = kinds}
end

-- (0.104.23) A workshop's limit of jobs taken from work orders ("max general
-- orders"), raised when its slots are all held by jobs that can't go on
-- (Enxah's masons: 5 engrave-memorial jobs of autoslab's, "needs unengraved
-- slab", held all 5 for 250 days, so the AI's slab, coffin and block orders
-- never reached the bench: the slabs those jobs wait for included).
function act_order_slots(a)
    local id = whole_number(a.workshop_id)
    local n = whole_number(a.max)
    if not id or not n or n < 1 or n > 15 then return reject('workshop_id and max 1-15 needed') end
    local b = df.building.find(id)
    if not b or not df.building_workshopst:is_instance(b) then return reject('no such workshop') end
    local old = b.profile.max_general_orders
    if n <= old then return reject(('the workshop already takes %d'):format(old)) end
    if not a.dry_run then b.profile.max_general_orders = n end
    return {ok = true, workshop = id, before = old, max = n, dry_run = a.dry_run or nil}
end

function act_bench_jobs(a)
    local spec = BENCH_JOBS[tostring(a.kind)]
    if not spec then return reject('kind must be one of: coffin, slab') end
    local n = whole_number(a.count) or 1
    if n < 1 or n > BENCH_MAX then return reject(('count must be 1-%d'):format(BENCH_MAX)) end
    if not (dfhack.job.createLinked and dfhack.job.assignToWorkshop) then
        return reject('this DFHack has no workshop job API')
    end
    local want = a.material == 'wood' and 'wood' or a.material == 'stone' and 'stone' or nil
    local jt = df.job_type[spec.job]
    local bench, have = nil, 0
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        local mat = spec.shops[df.workshop_type[b.type]]
        if mat and (not want or want == mat) and b:getBuildStage() >= b:getMaxBuildStage() then
            local waiting = 0
            for _, j in ipairs(b.jobs) do if j.job_type == jt then waiting = waiting + 1 end end
            have = have + waiting
            if not bench or (#b.jobs < #bench.jobs) then bench = b end
        end
    end
    if not bench then return reject('no finished workshop for ' .. tostring(a.kind)) end
    if have >= BENCH_MAX then return reject(('%d such jobs already wait at the benches'):format(have)) end
    n = math.min(n, BENCH_MAX - have)
    local lifted = 0
    if 10 - #bench.jobs < n and a.make_room then
        local mine = ai_orders().ids
        local lift = {}
        for _, j in ipairs(bench.jobs) do
            if BENCH_LIFT[df.job_type[j.job_type]] and not dfhack.job.getWorker(j)
                    -- (0.105.33) only jobs of orders that are not the AI's: a
                    -- job with no order (the player's, added at the bench) stays
                    and j.order_id ~= -1 and not mine[tostring(j.order_id)] then
                table.insert(lift, j)
            end
        end
        local want_free = n - (10 - #bench.jobs)
        if not a.dry_run then
            for i = 1, math.min(want_free, #lift) do
                if pcall(dfhack.job.removeJob, lift[i]) then lifted = lifted + 1 end
            end
        else
            lifted = math.min(want_free, #lift)
        end
    end
    n = math.min(n, 10 - #bench.jobs + (a.dry_run and lifted or 0))
    if n < 1 then return reject('the workshop\'s job list is full') end
    local wood = spec.shops[df.workshop_type[bench.type]] == 'wood'
    if a.dry_run then return {ok = true, dry_run = true, workshop = bench.id, count = n, lifted = lifted, material = wood and 'wood' or 'stone'} end
    for _ = 1, n do bench_job(bench, jt, wood) end
    return {ok = true, workshop = bench.id, count = n, lifted = lifted > 0 and lifted or nil,
            material = wood and 'wood' or 'stone'}
end

function act_cancel_work_order(a)
    local id = whole_number(a.order_id)
    if not id then return reject('order_id must be a whole number') end
    local data = ai_orders()
    if not data.ids[tostring(id)] then
        return reject(('order %d was not created by the AI (or has finished); the AI only cancels its own orders'):format(id))
    end
    -- (r4 k4, B6) the strategist cancels only the orders it made itself
    if a.by == 'strategist' and data.by[tostring(id)] ~= 'strategist' then
        return reject(('order %d is the planner\'s, not the strategist\'s; the strategist only cancels its own orders'):format(id))
    end
    local all = df.global.world.manager_orders.all
    for i = #all - 1, 0, -1 do
        local order = all[i]
        if order.id == id then
            if order_in_use_by_ui(order) then
                return reject('the work orders screen is open; try again when it is closed')
            end
            -- Remove "after order X completes" conditions pointing at it.
            for _, other in ipairs(all) do
                local conds = other.order_conditions
                for j = #conds - 1, 0, -1 do
                    if conds[j].order_id == id then
                        local c = conds[j]
                        conds:erase(j)
                        c:delete()
                    end
                end
            end
            all:erase(i)
            free_order(order)
            data.ids[tostring(id)] = nil
            data.by[tostring(id)] = nil
            save_ai_orders(data)
            -- (0.104.34) its jobs that nobody works go with it (DF leaves them)
            local gone = 0
            -- (0.105.33) only this order's: the fort-wide sweep is clear_orphan_jobs' own rule
            pcall(function() gone = orphan_jobs(false, 30, id) end)
            return {ok = true, order_id = id, cancelled = true, jobs_removed = gone > 0 and gone or nil}
        end
    end
    data.ids[tostring(id)] = nil
    data.by[tostring(id)] = nil
    save_ai_orders(data)
    return {ok = true, order_id = id, cancelled = false,
            note = 'order was already finished or removed'}
end

function act_tool(a)
    if not TOOL_ALLOWLIST[a.name] then
        return reject(('tool not allowed: %s (allowed: %s)'):format(
            tostring(a.name), table.concat(sorted_keys(TOOL_ALLOWLIST), ', ')))
    end
    if type(a.enabled) ~= 'boolean' then
        return reject('enabled must be true or false')
    end
    local output, rv = dfhack.run_command_silent(a.enabled and 'enable' or 'disable', a.name)
    if rv ~= CR_OK then
        return {ok = false, error = ('%s %s failed: %s'):format(
            a.enabled and 'enable' or 'disable', a.name, (output or ''):gsub('%s+$', ''))}
    end
    return {ok = true, name = a.name, enabled = plugin_enabled(a.name)}
end
