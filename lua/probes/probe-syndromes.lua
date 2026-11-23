-- probe-syndromes: syndrome 367 (or the id given) and every active syndrome
-- class among the living citizens, as JSON. READ ONLY: it changes nothing.
--
--     probe-syndromes [id]
local json = require('json')
local id = tonumber(({...})[1]) or 367
local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
local function classes(sd)
    local out = {}
    pcall(function()
        for _, c in ipairs(sd.syn_class) do
            local v = c
            if type(c) ~= 'string' then pcall(function() v = c.value end) end
            table.insert(out, tostring(v))
        end
    end)
    return out
end
local out = {id = id, by_syndrome = {}, holders = {}}
pcall(function()
    local sd = df.syndrome.find(id)
    if sd then
        out.name = txt(sd.syn_name)
        out.classes = classes(sd)
        out.effects = {}
        for _, ce in ipairs(sd.ce) do table.insert(out.effects, tostring(ce._type)) end
    else
        out.name = 'not found'
    end
end)
for _, u in ipairs(df.global.world.units.active) do
    local okc, cit = pcall(dfhack.units.isCitizen, u)
    local okd, dead = pcall(dfhack.units.isDead, u)
    if okc and cit and not (okd and dead) then
        pcall(function()
            for _, a in ipairs(u.syndromes.active) do
                local sd = df.syndrome.find(a.type)
                local k = tostring(a.type) .. ' ' .. (sd and txt(sd.syn_name) or '?') .. ' [' .. table.concat(sd and classes(sd) or {}, ',') .. ']'
                out.by_syndrome[k] = (out.by_syndrome[k] or 0) + 1
                if a.type == id then table.insert(out.holders, {id = u.id, name = txt(dfhack.units.getReadableName(u))}) end
            end
        end)
        pcall(function()
            local nc = dfhack.units.isNightCreature(u)
            if nc then out.night = (out.night or 0) + 1 end
        end)
    end
end
print(json.encode(out))
