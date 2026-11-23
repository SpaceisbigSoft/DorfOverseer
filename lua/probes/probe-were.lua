-- probe-were: werebeast-cursed citizens and the moon cells, as JSON
-- (0.105.76). READ ONLY: moon_cell is called with dry_run true (nothing is
-- zoned, locked or moved); it changes nothing in the game.
--
--     probe-were
--
-- What it prints: DF's moon phase; each citizen with an active syndrome of
-- class WERECURSE (DF's werebeast curse, from the bite on), whether they have
-- changed now, their syndrome's name and how long it has run; what the AI's
-- moon_cell would do for them (a dry run: the cells it would use, refusals).

local json = require('json')

local function txt(s)
    local ok, r = pcall(dfhack.df2utf, tostring(s or ''))
    return ok and r or tostring(s or '')
end

local out = {cursed = {}}
pcall(function() out.moon_phase = df.global.world.world_data.moon_phase end)
local ids = {}
for _, u in ipairs(df.global.world.units.active) do
    local okc, cit = pcall(dfhack.units.isCitizen, u)
    local okd, dead = pcall(dfhack.units.isDead, u)
    if okc and cit and not (okd and dead) then
        pcall(function()
            for _, a in ipairs(u.syndromes.active) do
                local sd = df.syndrome.find(a.type)
                local cls = {}
                if sd then
                    for _, c in ipairs(sd.syn_class) do
                        local v = c
                        if type(c) ~= 'string' then pcall(function() v = c.value end) end
                        table.insert(cls, tostring(v))
                    end
                end
                for _, c in ipairs(cls) do
                    if c == 'WERECURSE' then
                        local row = {id = u.id, name = txt(dfhack.units.getReadableName(u)),
                                     syndrome = sd and txt(sd.syn_name) or nil, syndrome_id = a.type}
                        pcall(function() row.ticks = a.ticks end)
                        pcall(function() row.changed = u.enemy.normal_race ~= -1 and u.enemy.normal_race ~= u.race end)
                        pcall(function() row.pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z} end)
                        table.insert(out.cursed, row)
                        table.insert(ids, u.id)
                        break
                    end
                end
            end
        end)
    end
end
out.count = #out.cursed
local okt, T = pcall(reqscript, 'ai-threats')
if okt and #ids > 0 then
    local some = {}
    for i = 1, math.min(#ids, 10) do some[i] = ids[i] end
    local ok, r = pcall(T.moon_cell, some, false, true)
    out.dry_run = ok and r or {error = tostring(r):sub(1, 200)}
end
print(json.encode(out))
