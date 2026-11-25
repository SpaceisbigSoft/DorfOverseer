-- (item7) The EngraveSlab work orders that never end, and the walking ghosts'
-- orders put first.
--
-- Why (B, 24 Nov): the AI's own memorial orders (ai-welfare slab_order) were
-- made with df.manager_order:new(), whose frequency is NONE (-1), not
-- OneTime; DF never counts such an order down, so each stayed at "1 left"
-- and engraved its dead's slab again whenever a blank one was made. 14 such
-- orders stood, one dwarf's slab was engraved 71 times and put up 67 times
-- (136 Slab buildings), and the walking ghost's own order (Inod "Oarzeal")
-- waited behind 8 others' jobs for a blank slab that never reached it, while
-- place_slabs put up "1 engraved memorial slab, none of them a walking
-- ghost's" 34 times in 2 hours.
--
--   order_scan()         {stale, endless, ghost_waiting, open}: the EngraveSlab
--                        orders whose dead has a memorial slab already (stale),
--                        those still needed that never end (frequency not
--                        OneTime), the walking ghosts with an open order and
--                        no slab yet
--   prune_orders(dry)    the stale orders taken off (with their jobs nobody
--                        works), the needed ones made OneTime, and the walking
--                        ghosts' orders moved to the front of the list
--
-- An order whose job a mason works now is left until the next time. Every DF
-- read is in a pcall; the dry run changes nothing.
--@ module = true

local function memorial_hfs()
    local out = {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.SLAB) do
            pcall(function()
                if it.engraving_type == df.slab_engraving_type.Memorial then out[it.topic] = true end
            end)
        end
    end)
    return out
end

local function order_hf(o)
    local ok, hf = pcall(function() return o.specdata.hist_figure_id end)
    if ok and type(hf) == 'number' then return hf end
    return -1
end

local function ghost_hfs()
    local ok, g = pcall(function() return reqscript('ai-builder').ghost_hfs() end)
    return ok and type(g) == 'table' and g or {}
end

-- order id -> {jobs, worked}: the jobs each order made, and whether a dwarf works one
local function order_jobs()
    local out = {}
    pcall(function()
        local link = df.global.world.jobs.list.next
        while link do
            local j = link.item
            if j then
                pcall(function()
                    local oid = j.order_id
                    if oid and oid ~= -1 then
                        local r = out[oid] or {jobs = {}, worked = false}
                        table.insert(r.jobs, j)
                        if dfhack.job.getWorker(j) then r.worked = true end
                        out[oid] = r
                    end
                end)
            end
            link = link.next
        end
    end)
    return out
end

local function once(o)
    local ok, yes = pcall(function() return o.frequency == df.workquota_frequency_type.OneTime end)
    return ok and yes
end

function order_scan()
    local out = {stale = 0, endless = 0, ghost_waiting = 0, open = 0}
    local slabs, ghosts = memorial_hfs(), ghost_hfs()
    pcall(function()
        for _, o in ipairs(df.global.world.manager_orders.all) do
            pcall(function()
                if o.job_type ~= df.job_type.EngraveSlab then return end
                local hf = order_hf(o)
                if hf < 0 then return end
                out.open = out.open + 1
                if slabs[hf] then
                    out.stale = out.stale + 1
                else
                    if not once(o) then out.endless = out.endless + 1 end
                    if ghosts[hf] then out.ghost_waiting = out.ghost_waiting + 1 end
                end
            end)
        end
    end)
    return out
end

-- DF's work orders screen (or a job's details) may hold an order: none is
-- taken off while one is open (ai-bridge-orders' order_in_use_by_ui)
local function screen_open()
    local ok, busy = pcall(function()
        local mi = df.global.game.main_interface
        if mi.info.open and mi.info.current_mode == df.info_interface_mode_type.WORK_ORDERS then return true end
        return mi.job_details.open and true or false
    end)
    return (not ok) or busy
end

local function free_order(o)
    for _, c in ipairs(o.item_conditions) do c:delete() end
    for _, c in ipairs(o.order_conditions) do c:delete() end
    if o.items then
        for _, e in ipairs(o.items.elements) do e:delete() end
        o.items:delete()
    end
    o:delete()
end

function prune_orders(dry_run)
    local scan = order_scan()
    if scan.stale == 0 and scan.endless == 0 then
        return {ok = false, rejected = true, nothing_to_do = true,
                error = 'no memorial order for a dead with a slab already, and none that never ends'}
    end
    if dry_run then
        return {ok = true, dry_run = true, stale = scan.stale, endless = scan.endless,
                ghost_waiting = scan.ghost_waiting}
    end
    if screen_open() then
        return {ok = false, rejected = true, error = 'the work orders screen is open; try again when it is closed'}
    end
    local slabs, ghosts = memorial_hfs(), ghost_hfs()
    local jobs = order_jobs()
    local all = df.global.world.manager_orders.all
    local removed, jobs_removed, kept_worked, made_once = 0, 0, 0, 0
    for i = #all - 1, 0, -1 do
        local o = all[i]
        local okt, slab_job = pcall(function() return o.job_type == df.job_type.EngraveSlab end)
        local hf = order_hf(o)
        if okt and slab_job and hf >= 0 then
            if slabs[hf] then
                local js = jobs[o.id]
                if js and js.worked then
                    kept_worked = kept_worked + 1
                else
                    -- no other order waits on it ("after order X"): those conditions go
                    for _, other in ipairs(all) do
                        pcall(function()
                            local conds = other.order_conditions
                            for k = #conds - 1, 0, -1 do
                                if conds[k].order_id == o.id then
                                    local c = conds[k]
                                    conds:erase(k)
                                    c:delete()
                                end
                            end
                        end)
                    end
                    for _, j in ipairs(js and js.jobs or {}) do
                        if pcall(dfhack.job.removeJob, j) then jobs_removed = jobs_removed + 1 end
                    end
                    all:erase(i)
                    pcall(free_order, o)
                    removed = removed + 1
                end
            elseif not once(o) then
                if pcall(function() o.frequency = df.workquota_frequency_type.OneTime end) then
                    made_once = made_once + 1
                end
            end
        end
    end
    -- the walking ghosts' orders first: the manager hands out jobs in list order
    local front = {}
    for i = #all - 1, 0, -1 do
        local o = all[i]
        local okt, slab_job = pcall(function() return o.job_type == df.job_type.EngraveSlab end)
        local hf = order_hf(o)
        if okt and slab_job and hf >= 0 and ghosts[hf] and not slabs[hf] then
            all:erase(i)
            table.insert(front, 1, o)
        end
    end
    for k = #front, 1, -1 do all:insert(0, front[k]) end
    return {ok = true, removed = removed, jobs_removed = jobs_removed > 0 and jobs_removed or nil,
            kept_worked = kept_worked > 0 and kept_worked or nil, made_once = made_once > 0 and made_once or nil,
            ghosts_first = #front > 0 and #front or nil}
end
