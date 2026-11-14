-- (0.105.47, R2) The training squad: a small squad that only trains, for the
-- civilians who badly want to fight or train, in a fort whose Militarism
-- keeps them out of the army (the player, 14 Nov 14:11: high Welfare allows
-- it even at low Militarism; the Monastery at Militarism -60, Welfare 80
-- had MartialTraining unmet for 60-83 dwarves, and every stressed dwarf at
-- the end of the run wanted to fight).
--
-- The squads the AI made for this are kept in the save (TRAINING_KEY); the
-- military report marks them (`training = true`), the brain never counts
-- them as the fort's soldiers nor sends them to fight (brain/planner_training.py),
-- and the trim never takes their members (ai-military trim).
--
--   marks()                          squad id (text) -> true
--   make(dry_run, txt)               a new squad, led by a volunteer, under a
--                                    vacant captain's office; no uniform
--   fill(sid, count, dry, txt, avoid, unit_id)   volunteers into its open
--                                    places (unit_id: that dwarf first, if he
--                                    can be drafted)
--   forget(sid, dry)                 no longer the training squad (Welfare fell)
--@ module = true

local U = reqscript('ai-util')

TRAINING_KEY = 'ai-overseer/training-squads'

function marks()
    return U.site_get(TRAINING_KEY, {})
end

local function put(m)
    return U.site_put(TRAINING_KEY, m)
end

-- the marks of squads that are gone dropped
local function prune(m)
    local out, changed = {}, false
    for k, v in pairs(m) do
        local sq = tonumber(k) and df.squad.find(tonumber(k))
        if sq then out[k] = v else changed = true end
    end
    if changed then put(out) end
    return out
end

function make(dry_run, txt)
    local M = reqscript('ai-military')
    local r = M.make_squad(dry_run, txt, {training = true})
    if r.ok and not dry_run and r.squad_id then
        local m = prune(marks())
        m[tostring(r.squad_id)] = true
        put(m)
        r.training = true
    end
    return r
end

local function free_places(sq)
    local places = {}
    for i, pos in ipairs(sq.positions) do
        if i > 0 and i < 10 and pos.occupant == -1 then table.insert(places, i) end
    end
    return places
end

function fill(squad_id, count, dry_run, txt, avoid, unit_id)
    local m = marks()
    if not m[tostring(squad_id)] then
        return {ok = false, rejected = true, error = 'not the training squad'}
    end
    local M = reqscript('ai-military')
    local sq = M.fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local places = free_places(sq)
    if #places == 0 then return {ok = false, rejected = true, error = 'the training squad has no open places'} end
    if unit_id then
        -- one named dwarf (stress care: one breaking down who longs to train)
        local u = df.unit.find(unit_id)
        if not u or not dfhack.units.isCitizen(u) then return {ok = false, rejected = true, error = 'no such citizen'} end
        local okm, mothers = pcall(M.nursing_mothers)
        if not (okm and M.draftable(u, mothers, false)) then
            return {ok = false, rejected = true, error = 'that dwarf cannot be drafted (in a squad, a noble, a nursing mother or a patient)'}
        end
        local name = (txt or tostring)(dfhack.units.getReadableName(u))
        if dry_run then return {ok = true, dry_run = true, name = name} end
        if not dfhack.military.addToSquad(u.id, squad_id, places[1]) then
            return {ok = false, error = 'the game kept ' .. name .. ' out of the squad'}
        end
        return {ok = true, added = {{unit_id = u.id, name = name}}, squad_id = squad_id}
    end
    if dry_run then return {ok = true, dry_run = true, open = #places} end
    -- volunteers only: those who badly want to fight or train (keen_only)
    return M.fill(squad_id, math.min(count, #places), txt, avoid, false, true)
end

function forget(squad_id, dry_run)
    local m = marks()
    if not m[tostring(squad_id)] then return {ok = false, rejected = true, error = 'not the training squad'} end
    if dry_run then return {ok = true, dry_run = true} end
    m[tostring(squad_id)] = nil
    put(m)
    return {ok = true, forgotten = squad_id}
end
