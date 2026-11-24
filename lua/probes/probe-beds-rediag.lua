-- probe-beds-rediag: a dry run of ai-health's rediagnose design (0.105.94)
-- for every infected citizen with load 60 or more: which infected wounds
-- are flagged diagnosed, whether a treatment is asked, and the flags a live
-- re-diagnosis would change. Self-contained (runs on a bridge without
-- rediagnose). READ ONLY: it changes nothing.
local json = require('json')
local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
local RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
            'rq_setting', 'rq_traction', 'rq_crutch'}
local MIN = 60
local out = {units = {}}
for _, u in ipairs(df.global.world.units.active) do
    local okc, cit = pcall(dfhack.units.isCitizen, u)
    if okc and cit and not dfhack.units.isDead(u) then
        local load = 0
        pcall(function() load = u.body.infection_level end)
        if load >= MIN then
            local row = {id = u.id, name = txt(dfhack.units.getReadableName(u)), load = load, wounds = {}}
            row.health = u.health ~= nil
            if u.health then
                row.asked = {}
                for _, k in ipairs(RQ) do if u.health.flags[k] then table.insert(row.asked, k) end end
                row.needs_healthcare = u.health.flags.needs_healthcare
            end
            for _, w in ipairs(u.body.wounds) do
                if w.flags.infection then
                    local wr = {id = w.id, diagnosed = w.flags.diagnosed, parts = {}}
                    for _, p in ipairs(w.parts) do
                        local pr = {part = p.body_part_id}
                        pcall(function() pr.f1 = p.flags1.diagnosed end)
                        pcall(function() pr.f2 = p.flags2.diagnosed end)
                        table.insert(wr.parts, pr)
                    end
                    table.insert(row.wounds, wr)
                end
            end
            table.insert(out.units, row)
        end
    end
end
print(json.encode(out))
