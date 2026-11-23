-- probe-stress: what weighs on the fort's most stressed citizens. For each
-- living citizen at or past the given stress (default 50000: miserable), the
-- emotions DF keeps (their thought, its strength and severity); tallied over
-- them by thought, negative feelings only, the heaviest first; with how many
-- are children and soldiers. READ ONLY.
--
--     probe-stress [stress]
local json = require('json')
local LINE = tonumber(({...})[1]) or 50000
local out = {line = LINE, citizens = 0, stressed = 0, children = 0, soldiers = 0, by_thought = {}, worst = {}}
local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
-- every feeling is tallied with its name (DF's emotion_type); the reader
-- tells good from bad. POS: the plainly good ones, left out
local POS = {}
for _, k in ipairs({'ACCEPTANCE','ADORATION','AFFECTION','AMUSEMENT','BLISS','CALM','CONTENTMENT','DELIGHT',
                    'ECSTASY','ELATION','ENJOYMENT','ENTHUSIASM','EUPHORIA','EXCITEMENT','EXHILARATION','FONDNESS',
                    'FREEDOM','GAIETY','GLADNESS','GLEE','GRATITUDE','HAPPINESS','HOPE','JOY','JUBILATION','LOVE',
                    'PLEASURE','PRIDE','RELIEF','SATISFACTION','SERENITY','TENDERNESS','THRILL','TRIUMPH','WONDER',
                    'ZEAL','ZEST','INTEREST','CURIOSITY','RAPTURE','APPRECIATION','RESPECT','SYMPATHY','HUMOR'}) do
    POS[k] = true
end
for _, u in ipairs(df.global.world.units.active) do
    local okc, cit = pcall(dfhack.units.isCitizen, u)
    local okd, dead = pcall(dfhack.units.isDead, u)
    if okc and cit and not (okd and dead) then
        out.citizens = out.citizens + 1
        local soul = u.status.current_soul
        local stress = soul and soul.personality.stress or 0
        if stress >= LINE then
            out.stressed = out.stressed + 1
            local child = false
            pcall(function() child = dfhack.units.isChild(u) or dfhack.units.isBaby(u) end)
            if child then out.children = out.children + 1 end
            if u.military.squad_id >= 0 then out.soldiers = out.soldiers + 1 end
            local mine = {}
            pcall(function()
                for _, e in ipairs(soul.personality.emotions) do
                    local en = tostring(df.emotion_type[e.type] or e.type)
                    if not POS[en:upper()] then
                        local th = tostring(df.unit_thought_type[e.thought] or e.thought) .. ' (' .. en .. ')'
                        local w = (e.strength or 0) * math.max(1, e.severity or 1)
                        local t = out.by_thought[th] or {n = 0, weight = 0}
                        t.n, t.weight = t.n + 1, t.weight + w
                        out.by_thought[th] = t
                        mine[th] = (mine[th] or 0) + w
                    end
                end
            end)
            if #out.worst < 12 then
                local top, tw = nil, -1
                for k, w in pairs(mine) do if w > tw then top, tw = k, w end end
                table.insert(out.worst, {name = txt(dfhack.units.getReadableName(u)), stress = stress, child = child,
                                         soldier = u.military.squad_id >= 0, top = top})
            end
        end
    end
end
local list = {}
for k, v in pairs(out.by_thought) do table.insert(list, {thought = k, n = v.n, weight = v.weight}) end
table.sort(list, function(a, b) return a.weight > b.weight end)
out.by_thought = {}
for i = 1, math.min(20, #list) do out.by_thought[i] = list[i] end
print(json.encode(out))
