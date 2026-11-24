-- probe-beds-who: every bed in the fort's hospital zones and what holds it
-- (units on the tile, jobs aimed at it, the bed's users, the other zones over
-- it), and each infected citizen's health flags and wounds, as JSON
-- (0.105.94 investigation, B: all 10 hospital beds taken, 7 infected never
-- diagnosed). READ ONLY: it changes nothing.
local json = require('json')
local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
local function is(f, u) local ok, r = pcall(f, u) return ok and r or false end
local function uname(u) return txt(dfhack.units.getReadableName(u)) end
local out = {beds = {}, infected = {}}

-- the hospitals' zones (ai-health hospitals())
local zones = {}
pcall(function()
    local site = dfhack.world.getCurrentSite()
    for _, loc in ipairs(site and site.buildings or {}) do
        if df.abstract_building_type[loc:getType()] == 'HOSPITAL' then
            local c = loc:getContents()
            for _, bid in ipairs(c and c.building_ids or {}) do
                local z = df.building.find(bid)
                if z then zones[z.id] = z end
            end
        end
    end
end)

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
local on_tile, job_at = {}, {}
for _, u in ipairs(df.global.world.units.active) do
    if not is(dfhack.units.isDead, u) then
        local k = key(u.pos.x, u.pos.y, u.pos.z)
        on_tile[k] = on_tile[k] or {}
        local row = {id = u.id, name = uname(u), citizen = is(dfhack.units.isCitizen, u)}
        pcall(function() row.job = u.job.current_job and tostring(df.job_type[u.job.current_job.job_type]) or nil end)
        pcall(function() row.on_ground = u.flags1.on_ground or nil end)
        pcall(function() row.unconscious = u.counters.unconscious > 0 or nil end)
        pcall(function() row.needs_healthcare = u.health and u.health.flags.needs_healthcare or nil end)
        table.insert(on_tile[k], row)
    end
end
pcall(function()
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j then
            pcall(function()
                local k = key(j.pos.x, j.pos.y, j.pos.z)
                job_at[k] = job_at[k] or {}
                local w = dfhack.job.getWorker(j)
                table.insert(job_at[k], {type = tostring(df.job_type[j.job_type]), id = j.id,
                                         special = j.flags.special or nil,
                                         worker = w and {id = w.id, name = uname(w)} or nil})
            end)
        end
        link = link.next
    end
end)

for zid, z in pairs(zones) do
    pcall(function()
        for _, b in ipairs(z.contained_buildings) do
            if df.building_type[b:getType()] == 'Bed' then
                local k = key(b.centerx, b.centery, b.z)
                local row = {bed = b.id, zone = zid, x = b.centerx, y = b.centery, z = b.z,
                             on_tile = on_tile[k], jobs = job_at[k], users = {}, zones_over = {}}
                pcall(function() row.built = b:getBuildStage() >= b:getMaxBuildStage() end)
                pcall(function()
                    for _, uid in ipairs(b.users.unit) do
                        local u = df.unit.find(uid)
                        table.insert(row.users, {id = uid, name = u and uname(u) or '?'})
                    end
                end)
                pcall(function()
                    for _, cz in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(b.centerx, b.centery, b.z)) or {}) do
                        local r = {id = cz.id, type = tostring(df.civzone_type[cz.type])}
                        pcall(function() r.owner = cz.assigned_unit_id end)
                        table.insert(row.zones_over, r)
                    end
                end)
                table.insert(out.beds, row)
            end
        end
    end)
end

-- the infected: flags, wounds
for _, u in ipairs(df.global.world.units.active) do
    if is(dfhack.units.isCitizen, u) and not is(dfhack.units.isDead, u) then
        local inf = false
        pcall(function() for _, w in ipairs(u.body.wounds) do if w.flags.infection then inf = true end end end)
        if inf then
            local row = {id = u.id, name = uname(u), flags = {}, wounds = {}}
            pcall(function() row.load = u.body.infection_level end)
            pcall(function() row.job = u.job.current_job and tostring(df.job_type[u.job.current_job.job_type]) or nil end)
            pcall(function()
                if u.health then
                    for k, v in pairs(u.health.flags) do if v == true then table.insert(row.flags, tostring(k)) end end
                else row.health = 'nil' end
            end)
            pcall(function()
                for _, w in ipairs(u.body.wounds) do
                    local wr = {id = w.id, age = w.age, flags = {}, parts = #w.parts}
                    for k, v in pairs(w.flags) do if v == true then table.insert(wr.flags, tostring(k)) end end
                    pcall(function()
                        local p = w.parts[0]
                        if p then
                            wr.part = p.body_part_id
                            wr.part_flags = {}
                            for k, v in pairs(p.flags1) do if v == true then table.insert(wr.part_flags, tostring(k)) end end
                            for k, v in pairs(p.flags2) do if v == true then table.insert(wr.part_flags, tostring(k)) end end
                        end
                    end)
                    table.insert(row.wounds, wr)
                end
            end)
            table.insert(out.infected, row)
        end
    end
end
print(json.encode(out))
