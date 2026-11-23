-- probe-messenger-compare.lua: every messenger's appointment and figure, field by field
-- READ-ONLY: reads the fort's messenger slots, each holder's figure (its
-- entity links, whereabouts) and unit, and prints one JSON object.
-- (22 Nov: Kib Shorastevud was made messenger by the AI and left with a
-- nomadic camp at once; Catten Mozirsibrek was made messenger by hand on the
-- Nobles screen: compare what DF holds for each.)
local json = require('json')
local function try(f) local ok, v = pcall(f) if ok then return v end return nil end
local function scalar(v)
    local t = type(v)
    if t == 'number' or t == 'boolean' or t == 'string' then return v end
    if t == 'userdata' then
        local ok, s = pcall(function() return tostring(v) end)
        return ok and s or '?'
    end
    return nil
end
local function dump(obj, depth)
    depth = depth or 0
    local out = {}
    local ok = pcall(function()
        for k, v in pairs(obj) do
            local s = scalar(v)
            if type(v) == 'userdata' and depth < 1 then
                local sub = try(function() return dump(v, depth + 1) end)
                out[tostring(k)] = (sub and next(sub)) and sub or s
            else
                out[tostring(k)] = s
            end
        end
    end)
    if not ok then return {err = 'not iterable'} end
    return out
end
local function flagset(f)
    local o = {}
    pcall(function() for k, v in pairs(f) do if v == true then table.insert(o, tostring(k)) end end end)
    return o
end

local out = {probe = 'messenger-compare', read_only = true,
             year = try(function() return df.global.cur_year end), tick = try(function() return df.global.cur_year_tick end)}
local ent = try(function() return df.historical_entity.find(df.global.plotinfo.group_id) end)
local holders = {}
for _, p in ipairs(ent.positions.own) do
    if p.code == 'MESSENGER' then
        out.position = {id = p.id, flags = flagset(p.flags), number = p.number}
        for _, a in ipairs(ent.positions.assignments) do
            if a.position_id == p.id then
                local h = {assignment = dump(a)}
                local hf = a.histfig ~= -1 and df.historical_figure.find(a.histfig)
                if hf then
                    h.name = try(function() return dfhack.df2utf(dfhack.translation.translateName(hf.name, false)) end)
                    h.hf = {id = hf.id, unit_id = hf.unit_id, civ_id = hf.civ_id, population_id = try(function() return hf.population_id end),
                            flags = flagset(hf.flags), profession = try(function() return df.profession[hf.profession] end)}
                    local links = {}
                    for _, l in ipairs(hf.entity_links) do
                        local row = {type = try(function() return df.histfig_entity_link_type[l:getType()] end),
                                     class = try(function() return l._type and tostring(l._type) end),
                                     fields = dump(l)}
                        table.insert(links, row)
                    end
                    h.entity_links = links
                    h.site_links = try(function()
                        local o = {}
                        for _, l in ipairs(hf.site_links) do table.insert(o, {type = try(function() return df.histfig_site_link_type[l:getType()] end), fields = dump(l)}) end
                        return o end)
                    h.whereabouts = try(function() return dump(hf.info.whereabouts) end)
                    local u
                    for _, x in ipairs(df.global.world.units.all) do if x.hist_figure_id == hf.id then u = x; break end end
                    if u then
                        h.unit = {id = u.id, pos = {u.pos.x, u.pos.y, u.pos.z},
                                  citizen = try(function() return dfhack.units.isCitizen(u) end),
                                  in_active = try(function() for _, y in ipairs(df.global.world.units.active) do if y.id == u.id then return true end end return false end),
                                  flags1 = flagset(u.flags1), flags2 = flagset(u.flags2), flags3 = flagset(u.flags3), flags4 = try(function() return flagset(u.flags4) end),
                                  job = try(function() return u.job.current_job and df.job_type[u.job.current_job.job_type] end),
                                  army_controller_id = try(function() return u.enemy.army_controller_id end),
                                  following = try(function() return u.following and u.following.id end)}
                    end
                end
                table.insert(holders, h)
            end
        end
    end
end
out.holders = holders
print(json.encode(out))
