-- One-off read-only probe (25 Oct): why DF leaves some armour off its
-- equipment lists. Writes DF-AI\logs\probe-gear.txt. Changes nothing.
local out = {}
local function p(...) local t = {} for i = 1, select('#', ...) do t[#t+1] = tostring(select(i, ...)) end out[#out+1] = table.concat(t, ' ') end
local eq = df.global.plotinfo.equipment
local function id_set(v) local s = {} for _, id in ipairs(v) do s[id] = true end return s end
local fort_race = df.global.plotinfo.race_id
p('fort race', fort_race, df.creature_raw.find(fort_race).creature_id)
local FL = {'forbid', 'in_inventory', 'on_ground', 'in_job', 'owned', 'trader', 'dump', 'in_building', 'garbage_collect',
            'removed', 'hostile', 'artifact', 'container', 'melt', 'foreign', 'construction', 'rotten', 'spider_web', 'encased'}
local function desc(it)
    local f, fl = it.flags, {}
    for _, k in ipairs(FL) do pcall(function() if f[k] then fl[#fl+1] = k end end) end
    local mr = -1
    pcall(function() mr = it:getMakerRace() end)
    local mrn = '?'
    pcall(function() mrn = df.creature_raw.find(mr).creature_id end)
    local x, y, z = dfhack.items.getPosition(it)
    local cont = dfhack.items.getContainer(it)
    local holder = dfhack.items.getHolderUnit(it)
    local mi = dfhack.matinfo.decode(it)
    local wear = -1
    pcall(function() wear = it.wear end)
    local gen = '?'
    pcall(function() gen = tostring(it:getEffectiveArmorLevel()) end)
    return ('#%d %s maker_race %s(%s) mat %s q%d wear %d armorlevel %s at %s,%s,%s [%s]%s%s'):format(it.id,
        dfhack.df2console(dfhack.items.getDescription(it, 0, true)), tostring(mr), mrn, mi and mi:getToken() or '?',
        it:getQuality(), wear, gen, tostring(x), tostring(y), tostring(z), table.concat(fl, ' '),
        cont and (' in ' .. dfhack.df2console(dfhack.items.getDescription(cont, 0, true))) or '',
        holder and (' held by ' .. dfhack.df2console(dfhack.units.getReadableName(holder))) or '')
end
for _, kind in ipairs({'ARMOR', 'GLOVES', 'PANTS', 'SHOES', 'HELM'}) do
    local asg, una, unm = id_set(eq.items_assigned[kind]), id_set(eq.items_unassigned[kind]), id_set(eq.items_unmanifested[kind])
    local tally = {listed = {}, unlisted = {}}
    local samples = {}
    for _, it in ipairs(df.global.world.items.other[kind]) do
        local listed = asg[it.id] or una[it.id] or unm[it.id]
        local key = listed and 'listed' or 'unlisted'
        local mr = -1
        pcall(function() mr = it:getMakerRace() end)
        local f = it.flags
        local tags = {}
        tags[#tags+1] = (mr == fort_race) and 'ours' or ('race' .. tostring(mr))
        local mi = dfhack.matinfo.decode(it)
        tags[#tags+1] = (mi and mi.material.flags.IS_METAL) and 'metal' or 'nonmetal'
        if f.in_inventory and dfhack.items.getHolderUnit(it) then tags[#tags+1] = 'held' end
        if f.owned then tags[#tags+1] = 'owned' end
        if f.forbid then tags[#tags+1] = 'forbid' end
        if f.trader then tags[#tags+1] = 'trader' end
        if f.foreign then tags[#tags+1] = 'foreign' end
        if f.in_building then tags[#tags+1] = 'in_building' end
        if f.melt then tags[#tags+1] = 'melt' end
        local t = table.concat(tags, ' ')
        tally[key][t] = (tally[key][t] or 0) + 1
        if not listed and not (f.in_inventory and dfhack.items.getHolderUnit(it)) and not f.owned and #samples < 6 then
            samples[#samples+1] = desc(it)
        end
    end
    p('=== ' .. kind)
    for k, tt in pairs(tally) do
        for t, n in pairs(tt) do p('  ', k, t, n) end
    end
    for _, s in ipairs(samples) do p('   sample', s) end
end
local fh = io.open('C:/Users/skulr/Documents/DF-AI/logs/probe-gear.txt', 'w')
if fh then fh:write(table.concat(out, '\n')) fh:close() print('probe-gear: written, ' .. #out .. ' lines') else print('probe-gear: could not write') end
