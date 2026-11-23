-- probe-messenger-where.lua: where is the fort's messenger, really?
-- READ-ONLY. It changes nothing in the game or the save: it only reads the
-- messenger's slot, the historical figure, the units list and the army, and
-- prints one JSON object.
--
-- Why (22 Nov, 0.105.69 live): in A, C and F the AI reads the messenger as
-- "away with an army" (hf.info.whereabouts.army_id >= 0) and the sender as
-- "the messenger is away" (df.unit.find(hf.unit_id) is nil), while the fort
-- has no mission out (missions.controllers []). Is the dwarf on the map under
-- another unit id, or truly gone, and what is that army?
--
--     dfhack-run lua -f probe-messenger-where.lua

local json = require('json')
local out = {probe = 'messenger-where', read_only = true}

local function try(f, ...) local ok, v = pcall(f, ...) if ok then return v end return nil end
local function name_of(u) return try(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end) end

local ent = try(function() return df.historical_entity.find(df.global.plotinfo.group_id) end)
out.group_id = try(function() return df.global.plotinfo.group_id end)
out.tick = try(function() return df.global.cur_year_tick end)
out.year = try(function() return df.global.cur_year end)

local holders = {}
if ent then
    for _, p in ipairs(ent.positions.own) do
        if p.code == 'MESSENGER' then
            for _, a in ipairs(ent.positions.assignments) do
                if a.position_id == p.id then
                    table.insert(holders, {slot = a.id, histfig = a.histfig, squad_id = a.squad_id})
                end
            end
        end
    end
end

for _, h in ipairs(holders) do
    local hf = h.histfig ~= -1 and df.historical_figure.find(h.histfig) or nil
    if hf then
        h.hf_name = try(function() return dfhack.df2utf(dfhack.translation.translateName(hf.name, false)) end)
        h.hf_unit_id = hf.unit_id
        h.hf_died_year = hf.died_year
        h.hf_civ = hf.civ_id
        local w = try(function() return hf.info.whereabouts end)
        if w then
            h.whereabouts = {
                state = try(function() return df.whereabouts_type[w.state] or w.state end),
                army_id = try(function() return w.army_id end),
                site_id = try(function() return w.site_id end),
                region = try(function() return {w.pos_x, w.pos_y} end),
                abs = try(function() return {w.abs_smm_x, w.abs_smm_y} end),
            }
        end
        local u = df.unit.find(hf.unit_id)
        h.unit_by_id = u and {id = u.id, name = name_of(u)} or nil
        -- the same figure's unit anywhere in the units list
        local found = {}
        for _, x in ipairs(df.global.world.units.all) do
            if x.hist_figure_id == hf.id then
                table.insert(found, {
                    id = x.id, name = name_of(x),
                    active = try(function() return dfhack.units.isActive(x) end),
                    citizen = try(function() return dfhack.units.isCitizen(x) end),
                    inactive = x.flags1.inactive, left = try(function() return x.flags1.left end),
                    killed = x.flags2.killed, dead = try(function() return dfhack.units.isDead(x) end),
                    pos = {x.pos.x, x.pos.y, x.pos.z},
                    army_controller_id = try(function() return x.enemy.army_controller_id end),
                    in_active_list = try(function()
                        for _, y in ipairs(df.global.world.units.active) do if y.id == x.id then return true end end
                        return false end),
                })
            end
        end
        h.units_with_this_figure = found
        -- the army
        local aid = h.whereabouts and h.whereabouts.army_id
        if aid and aid >= 0 then
            local army = try(function() return df.army.find(aid) end)
            if army then
                h.army = {
                    id = army.id,
                    pos = try(function() return {army.pos.x, army.pos.y, army.pos.z} end),
                    controller_id = try(function() return army.controller_id end),
                    flags = try(function()
                        local f = {}
                        for k, v in pairs(army.flags) do if v == true then table.insert(f, tostring(k)) end end
                        return f end),
                    members = try(function()
                        local m = {}
                        for i, mem in ipairs(army.members) do
                            if i >= 12 then break end
                            local mhf = df.historical_figure.find(mem.nemesis_id) -- may be a nemesis id
                            table.insert(m, {nemesis_id = mem.nemesis_id})
                        end
                        return m end),
                    n_members = try(function() return #army.members end),
                }
                local cid = h.army.controller_id
                local ctl = cid and cid >= 0 and try(function() return df.army_controller.find(cid) end)
                if ctl then
                    h.army.controller = {
                        id = ctl.id,
                        goal = try(function() return df.army_controller_goal_type[ctl.goal] or ctl.goal end),
                        site_id = try(function() return ctl.site_id end),
                        entity_id = try(function() return ctl.entity_id end),
                        origin_site = try(function() return ctl.origin_site_id end),
                        year = try(function() return ctl.year end),
                    }
                end
            else
                h.army = {id = aid, missing = true}
            end
        end
    end
end
out.holders = holders

-- the fort's squads the AI reads as "away" (the same question)
local squads = {}
pcall(function()
    for _, sid in ipairs(ent.squads) do
        local sq = df.squad.find(sid)
        if sq then
            local away, members = 0, 0
            for _, pos in ipairs(sq.positions) do
                if pos.occupant ~= -1 then
                    members = members + 1
                    local hf = df.historical_figure.find(pos.occupant)
                    local a = hf and try(function() return hf.info.whereabouts.army_id end)
                    if a and a >= 0 then away = away + 1 end
                end
            end
            table.insert(squads, {id = sid, members = members, hf_in_army = away})
        end
    end
end)
out.squads = squads

print(json.encode(out))
