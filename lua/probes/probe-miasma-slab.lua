-- probe-miasma-slab: why a memorial slab isn't engraved (F, Urvad), as JSON:
-- the slab orders, the EngraveSlab/ConstructSlab jobs, blank slabs, the
-- masons' workshops (jobs on the bench, profiles), the engravers. READ ONLY.
local json = require('json')
local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
local out = {orders = {}, jobs = {}, slabs = {blank = 0, engraved = 0, forbid = 0, in_job = 0, in_building = 0, rows = {}},
             shops = {}, engravers = 0, engravers_free = 0}
pcall(function()
    for _, o in ipairs(df.global.world.manager_orders.all) do
        local jt = tostring(df.job_type[o.job_type])
        if jt == 'EngraveSlab' or jt == 'ConstructSlab' then
            local r = {id = o.id, job = jt, left = o.amount_left, total = o.amount_total}
            pcall(function() r.hf = o.specdata.hist_figure_id end)
            pcall(function() r.validated = o.status.validated r.active = o.status.active end)
            pcall(function() r.workshop_id = o.workshop_id end)
            pcall(function() r.conditions = #o.item_conditions + #o.order_conditions end)
            pcall(function() r.frequency = tostring(df.workquota_frequency_type[o.frequency]) end)
            table.insert(out.orders, r)
        end
    end
end)
local link = df.global.world.jobs.list.next
while link do
    local j = link.item
    if j then
        local jt = tostring(df.job_type[j.job_type])
        if jt == 'EngraveSlab' or jt == 'ConstructSlab' then
            local r = {id = j.id, job = jt, suspended = j.flags.suspend or nil, repeat_ = j.flags['repeat'] or nil,
                       pos = {x = j.pos.x, y = j.pos.y, z = j.pos.z}}
            pcall(function() r.hf = j.hist_figure_id end)
            pcall(function()
                for _, g in ipairs(j.general_refs) do
                    local t = g:getType()
                    if t == df.general_ref_type.UNIT_WORKER then r.worker = g.unit_id end
                    if t == df.general_ref_type.BUILDING_HOLDER then r.building = g.building_id end
                end
            end)
            pcall(function() r.items = #j.items end)
            pcall(function() r.order_id = j.order_id end)
            table.insert(out.jobs, r)
        end
    end
    link = link.next
end
for _, it in ipairs(df.global.world.items.other.SLAB) do
    pcall(function()
        local eng = it.engraving_type ~= -1 and it.engraving_type ~= nil
        pcall(function() eng = it.engraving_type ~= df.slab_engraving_type.Slab end)
        if eng then out.slabs.engraved = out.slabs.engraved + 1 else out.slabs.blank = out.slabs.blank + 1 end
        if eng then
            local r = {id = it.id, engraved = true, in_building = it.flags.in_building or nil, forbid = it.flags.forbid or nil, in_job = it.flags.in_job or nil}
            pcall(function() r.engraving_type = tostring(df.slab_engraving_type[it.engraving_type]) end)
            pcall(function() r.topic = it.topic end)
            pcall(function() r.desc = txt(dfhack.items.getDescription(it, 0, true)) end)
            out.slabs.engraved_rows = out.slabs.engraved_rows or {}
            if #out.slabs.engraved_rows < 6 then table.insert(out.slabs.engraved_rows, r) end
        end
        if not eng then
            local r = {id = it.id, forbid = it.flags.forbid or nil, in_job = it.flags.in_job or nil,
                       in_building = it.flags.in_building or nil, dump = it.flags.dump or nil,
                       on_ground = it.flags.on_ground or nil, trader = it.flags.trader or nil,
                       mat = txt(dfhack.matinfo.getToken(it.mat_type, it.mat_index))}
            pcall(function() r.engraving_type = tostring(df.slab_engraving_type[it.engraving_type]) end)
            pcall(function() local p = xyz2pos(dfhack.items.getPosition(it)) r.pos = {x = p.x, y = p.y, z = p.z} end)
            if it.flags.forbid then out.slabs.forbid = out.slabs.forbid + 1 end
            if it.flags.in_job then out.slabs.in_job = out.slabs.in_job + 1 end
            if it.flags.in_building then out.slabs.in_building = out.slabs.in_building + 1 end
            if #out.slabs.rows < 12 then table.insert(out.slabs.rows, r) end
        end
    end)
end
pcall(function()
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_MASON) do
        local r = {id = b.id, jobs = #b.jobs, z = b.z, built = b:getBuildStage() >= b:getMaxBuildStage()}
        r.list = {}
        for _, j in ipairs(b.jobs) do table.insert(r.list, tostring(df.job_type[j.job_type]) .. (j.flags.suspend and '(s)' or '')) end
        pcall(function()
            local p = b.profile
            r.profile = {workers = #p.permitted_workers, min = p.min_level, max = p.max_level}
            pcall(function() r.profile.blocked = #p.blocked_labors end)
        end)
        table.insert(out.shops, r)
    end
end)
local lab = df.unit_labor.ENGRAVER
for _, u in ipairs(df.global.world.units.active) do
    pcall(function()
        if dfhack.units.isCitizen(u) and not dfhack.units.isDead(u) and u.status.labors[lab] then
            out.engravers = out.engravers + 1
            if not u.job.current_job then out.engravers_free = out.engravers_free + 1 end
        end
    end)
end
pcall(function()
    local okw, L = pcall(reqscript, 'ai-labor')
    if okw then local wd, mode = L.detail_for('ENGRAVER') if wd then out.detail = {name = tostring(wd.name), mode = mode, members = #wd.assigned_units} end end
end)
print(json.encode(out))
