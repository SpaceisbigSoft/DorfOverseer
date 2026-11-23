-- probe-citizen-armies.lua: which citizens' figures are tied to a world army?
-- READ-ONLY: reads the citizens, their figures' whereabouts and those armies'
-- controllers; prints one JSON object. (22 Nov: the messenger posts of A, C and
-- F are held by figures who left with an outside group's CAMP army: are the
-- citizens still on the map tied to their arrival armies too?)
local json = require('json')
local function try(f) local ok, v = pcall(f) if ok then return v end return nil end
local out = {probe = 'citizen-armies', read_only = true, group_id = try(function() return df.global.plotinfo.group_id end),
             civ_id = try(function() return df.global.plotinfo.civ_id end)}
local n, tied, by = 0, 0, {}
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    n = n + 1
    local hf = u.hist_figure_id >= 0 and df.historical_figure.find(u.hist_figure_id)
    local aid = hf and try(function() return hf.info.whereabouts.army_id end)
    if aid and aid >= 0 then
        tied = tied + 1
        local army = try(function() return df.army.find(aid) end)
        local cid = army and try(function() return army.controller_id end)
        local ctl = cid and cid >= 0 and try(function() return df.army_controller.find(cid) end)
        local key = ctl and (tostring(try(function() return df.army_controller_goal_type[ctl.goal] end)) .. ' entity ' .. tostring(ctl.entity_id) .. ' y' .. tostring(ctl.year)) or ('army ' .. tostring(aid) .. (army and '' or ' (gone)'))
        by[key] = (by[key] or 0) + 1
    end
end
out.citizens, out.tied_to_an_army, out.by_army = n, tied, by
-- the entities in play
for _, id in ipairs({out.group_id, out.civ_id, 3160}) do
    local e = id and try(function() return df.historical_entity.find(id) end)
    if e then out['entity_' .. id] = {type = try(function() return df.historical_entity_type[e.type] end),
        name = try(function() return dfhack.df2utf(dfhack.translation.translateName(e.name, true)) end)} end
end
print(json.encode(out))
