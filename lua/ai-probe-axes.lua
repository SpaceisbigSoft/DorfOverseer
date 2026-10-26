-- One-off read-only probe (25 Oct): why no soldier is given a battle axe.
-- Writes DF-AI\logs\probe-axes.txt. Changes nothing in the game.
local out = {}
local function p(...) local t = {} for i = 1, select('#', ...) do t[#t+1] = tostring(select(i, ...)) end out[#out+1] = table.concat(t, ' ') end
local eq = df.global.plotinfo.equipment
p('equipment fields:')
pcall(function() for k, v in pairs(eq) do
    local n = ''
    pcall(function() n = ' (#' .. #v .. ')' end)
    p('  ', k, tostring(v):sub(1, 60) .. n)
end end)
local function list_ids(v)
    local s = {}
    pcall(function() for _, id in ipairs(v) do s[id] = true end end)
    return s
end
local function sub_lists(name)
    local res = {}
    pcall(function()
        local c = eq[name]
        for k, v in pairs(c) do
            local ok, n = pcall(function() return #v end)
            if ok and n > 0 then res[k] = list_ids(v); p('  ', name, k, n) end
        end
    end)
    return res
end
local unas = sub_lists('items_unassigned')
local asg = sub_lists('items_assigned')
local unman = sub_lists('items_unmanifested')
local work = {}
pcall(function() work = list_ids(eq.work_weapons); p('work_weapons', #eq.work_weapons) end)
pcall(function() p('work_units', #eq.work_units) end)
local function in_any(lists, id)
    local r = {}
    for k, s in pairs(lists) do if s[id] then r[#r+1] = tostring(k) end end
    return table.concat(r, ',')
end
-- who claims each item: squad positions
local claim = {}
for _, sq in ipairs(df.global.world.squads.all) do
    for pi, pos in ipairs(sq.positions) do
        pcall(function()
            for _, iid in ipairs(pos.equipment.assigned_items) do
                claim[iid] = ('squad %d place %d occupant %d'):format(sq.id, pi, pos.occupant)
            end
        end)
    end
end
p('--- weapons (axes, picks) ---')
for _, it in ipairs(df.global.world.items.other.WEAPON) do
    local ok, id = pcall(function() return it.subtype.id end)
    if ok and (id == 'ITEM_WEAPON_AXE_BATTLE' or id == 'ITEM_WEAPON_PICK') then
        local f, fl = it.flags, {}
        for _, k in ipairs({'forbid', 'in_inventory', 'on_ground', 'in_job', 'owned', 'trader', 'dump', 'in_building', 'garbage_collect', 'removed', 'hostile', 'artifact'}) do
            if f[k] then fl[#fl+1] = k end
        end
        local holder = dfhack.items.getHolderUnit(it)
        local x, y, z = dfhack.items.getPosition(it)
        p(('#%d %s %s q%d at %s,%s,%s [%s] unassigned:%s assigned:%s unmanifested:%s work:%s claim:%s holder:%s'):format(
            it.id, id, dfhack.matinfo.decode(it) and dfhack.matinfo.decode(it):getToken() or '?', it:getQuality(),
            tostring(x), tostring(y), tostring(z), table.concat(fl, ' '),
            in_any(unas, it.id), in_any(asg, it.id), in_any(unman, it.id), tostring(work[it.id] or false),
            tostring(claim[it.id]), holder and dfhack.df2console(dfhack.units.getReadableName(holder)) or '-'))
    end
end
-- woodcutters and miners by labour
local wc, mn = 0, 0
for _, u in ipairs(dfhack.units.getCitizens(true)) do
    if u.status.labors.CUTWOOD then wc = wc + 1 end
    if u.status.labors.MINE then mn = mn + 1 end
end
p('citizens with CUTWOOD', wc, 'with MINE', mn)
-- each weapon uniform spec's assigned list
for _, sq in ipairs(df.global.world.squads.all) do
    pcall(function()
        if sq.entity_id ~= df.global.plotinfo.group_id then return end
        for pi, pos in ipairs(sq.positions) do
            for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                p(('squad %d place %d occ %d weapon spec: type %d sub %d matclass %d mat %d:%d item %d choice %s assigned %d'):format(
                    sq.id, pi, pos.occupant, spec.item_type, spec.item_subtype, spec.material_class, spec.mattype,
                    spec.matindex, spec.item, tostring(spec.indiv_choice.whole), #spec.assigned))
            end
        end
    end)
end
local path = dfhack.getDFPath() .. '/../../../../Users/skulr/Documents/DF-AI/logs/probe-axes.txt'
local fh = io.open('C:/Users/skulr/Documents/DF-AI/logs/probe-axes.txt', 'w')
if fh then fh:write(table.concat(out, '\n')) fh:close() print('probe-axes: written, ' .. #out .. ' lines') else print('probe-axes: could not write') end
