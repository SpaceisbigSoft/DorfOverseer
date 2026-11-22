-- (r11 n1, the player 22 Nov 01:43) A held civilian office given to a better
-- holder: the interim messenger (an office holder doubling as messenger in a
-- tiny fort, lua/ai-nobles.lua pick_interim) replaced as soon as a suitable
-- free citizen exists, and a civilian office the AI fills (manager,
-- bookkeeper, broker, chief medical dwarf, messenger; not the sheriff or the
-- captain of the guard, whose posts lead a squad) given to a free citizen
-- vastly better at its skills.
--
-- The planner decides when (brain/planner_office_swap.py: the margin, the
-- cooldowns, threats); this re-checks everything against the game and swaps
-- all-or-nothing: the old holder taken off as DFHack's own code takes an
-- officer off (Military.cpp remove_officer_entity_link; scripts'
-- internal/emigration unit-link-utils: the slot's holder cleared, the
-- position link erased), the new one written as the nobles screen does
-- (write_appointment, read back through getNoblePositions); if that fails
-- the old holder is put back as they were. Only after both stand is the
-- old holder's former-position link and the history event added (as
-- DFHack's code does). DF has no "lost an office" thought (df-structures'
-- unit_thought_type: Elected, Reelected; MilitaryRemoved is squads only).
--@module = true

local N = reqscript('ai-nobles')

PART_VERSIONS = {['ai-nobles-swap'] = '0.105.66'}   -- (r11 n1 fixes) bumped with BRIDGE_VERSION

-- the civilian offices the AI may give to a better holder. (r11 n1 fixes)
-- Not the sheriff nor the captain of the guard: their posts lead the fortress
-- guard (DF's raws give the captain [SQUAD:10:...]; the slot's squad_id), and
-- moving the office would leave the squad with the old holder. Any other
-- slot that leads a squad, or a soldier holder or candidate, is never swapped.
SWAP_OFFICES = {'MANAGER', 'BOOKKEEPER', 'BROKER', 'CHIEF_MEDICAL_DWARF', 'MESSENGER'}
-- the margin when the planner gives none (brain/planner_config_rounds.py n1_swap_*)
MARGIN_ADD, MARGIN_FACTOR = 10, 2.0

-- the jobs an office's holder does for it: not taken off mid-job
OFFICE_JOBS = {
    MANAGER = {'ManageWorkOrders'},
    BOOKKEEPER = {'UpdateStockpileRecords'},
    BROKER = {'TradeAtDepot', 'BringItemToDepot'},
    CHIEF_MEDICAL_DWARF = {'DiagnosePatient', 'Surgery', 'SetBone', 'Suture', 'DressWound', 'CleanPatient',
                           'ApplyCast', 'PlaceInTraction'},
    SHERIFF = {'InterrogateSubject', 'ExecuteCriminal'},
    CAPTAIN_OF_THE_GUARD = {'InterrogateSubject', 'ExecuteCriminal'},
}

local function name_of(u, txt)
    return u and (txt or tostring)(dfhack.units.getReadableName(u)) or nil
end

local function position_of(ent, id)
    for _, p in ipairs(ent.positions.own) do
        if p.id == id then return p end
    end
end

-- Pure: the score a candidate must reach to replace a holder of score `held`.
function needed(held, add, factor)
    held = tonumber(held) or 0
    return math.max(held + (tonumber(add) or MARGIN_ADD), math.ceil(held * (tonumber(factor) or MARGIN_FACTOR)))
end

-- a caravan at or on its way to the depot (the broker's time)
local function caravan_here()
    local here = false
    pcall(function()
        local T = df.caravan_state.T_trade_state
        for _, c in ipairs(df.global.plotinfo.caravans) do
            local st = c.trade_state
            if st == T.Approaching or st == T.AtDepot or st == T.Stuck then here = true end
        end
    end)
    return here
end

-- Why the holder may not be taken off now, or nil: a strange mood, away,
-- at a job the office needs; the broker while a caravan is here.
function holder_busy(u, hf, code)
    local okm, md = pcall(function() return u.mood end)
    if okm and type(md) == 'number' and md >= 0 then return 'in a strange mood' end
    local away = N.holder_away(hf, code == 'MESSENGER')
    if away then return away end
    local jobs = OFFICE_JOBS[code]
    if jobs then
        local okj, jt = pcall(function() return u.job.current_job and df.job_type[u.job.current_job.job_type] end)
        if okj and jt then
            for _, j in ipairs(jobs) do
                if j == jt then return 'at a job of the office (' .. jt .. ')' end
            end
        end
    end
    if code == 'BROKER' and caravan_here() then return 'a caravan is here (the broker trades)' end
    return nil
end

-- the held slot of `code`: assignment, its index, the post
local function held_slot(ent, code)
    local mp = code == 'MESSENGER' and N.position_by_code(ent, 'MESSENGER') or nil
    for idx, a in ipairs(ent.positions.assignments) do
        local p = position_of(ent, a.position_id)
        if p and a.histfig ~= -1 and ((mp and p.id == mp.id) or (not mp and p.code == code)) then
            return a, idx, p
        end
    end
end

-- the best free citizen for `code` (lua/ai-nobles.lua free_pick: no office,
-- not the holder, not miserable, no soldier; messenger_status picks the same)
local function best_free(code, holder_id)
    return N.free_pick(code, holder_id)
end

-- why the slot may never be swapped (it leads a squad, a soldier holds it), or nil
local function squad_bound(a, u)
    if (tonumber(a.squad_id) or -1) ~= -1 then return 'leads a squad' end
    local oks, sq = pcall(function() return u and u.military.squad_id end)
    if oks and type(sq) == 'number' and sq >= 0 then return 'held by a soldier' end
    return nil
end

-- Each held civilian office, read only: {code = {holder, holder_unit,
-- holder_score, holder_offices, busy, cand, cand_unit, cand_score, fixed}}.
-- `fixed`: not the fort's to fill (elected, inherited, replaced...).
function swap_survey(ent, txt)
    local out = {}
    for _, code in ipairs(SWAP_OFFICES) do
        pcall(function()
            local a, _, p = held_slot(ent, code)
            if not a then return end
            local hf = df.historical_figure.find(a.histfig)
            local u = hf and df.unit.find(hf.unit_id)
            local o = {holder = hf and (txt or tostring)(N.translate_name(hf.name)) or tostring(a.histfig)}
            local can, why = N.appointable(ent, p)
            if not can then o.fixed = why or true end
            o.fixed = o.fixed or squad_bound(a, u)
            if u then
                o.holder_unit = u.id
                o.holder = name_of(u, txt) or o.holder
                o.holder_score = N.skill_score(N.office_skills(u, code))
                o.holder_offices = N.fort_offices(u, ent)
                o.busy = holder_busy(u, hf, code)
            else
                o.busy = 'not on the map'
            end
            local c = best_free(code, o.holder_unit)
            if c then
                o.cand_unit, o.cand_score = c.id, N.skill_score(c.skills)
                o.cand = name_of(df.unit.find(c.id), txt)
            end
            out[code] = o
        end)
    end
    return out
end

-- take the holder off the slot (what DFHack's own code does first): the
-- slot's holder cleared, the figure's position link to this entity for it
-- taken out (kept, with its index, for put_back). (r11 n1 fixes) Only this
-- entity's link: assignment ids are per entity.
local function take_off(ent, a, hf)
    local saved = {histfig = a.histfig, links = {}}
    pcall(function() saved.histfig2 = a.histfig2 end)
    a.histfig = -1
    for i = #hf.entity_links - 1, 0, -1 do
        local l = hf.entity_links[i]
        if df.histfig_entity_link_positionst:is_instance(l) and l.assignment_id == a.id and l.entity_id == ent.id then
            table.insert(saved.links, 1, {link = l, idx = i, start_year = l.start_year})
            hf.entity_links:erase(i)
        end
    end
    return saved
end

-- the old holder back as they were: the very link objects, at their places
local function put_back(a, hf, saved)
    a.histfig = saved.histfig
    if saved.histfig2 ~= nil then pcall(function() a.histfig2 = saved.histfig2 end) end
    for _, k in ipairs(saved.links) do
        hf.entity_links:insert(math.min(k.idx, #hf.entity_links), k.link)
    end
end

-- the new holder's link to this entity for the slot taken out (a write that raised)
local function drop_new(ent, a, hf)
    if not hf then return end
    for i = #hf.entity_links - 1, 0, -1 do
        local l = hf.entity_links[i]
        if df.histfig_entity_link_positionst:is_instance(l) and l.assignment_id == a.id and l.entity_id == ent.id then
            hf.entity_links:erase(i)
            pcall(function() l:delete() end)
        end
    end
end

-- after the swap stands: the old links freed, the old holder's former-position
-- link and the event (none when no live link existed, as DFHack does)
local function note_former(ent, hf, a, p, saved)
    if #saved.links == 0 then return end
    local start = saved.links[1].start_year or df.global.cur_year
    for _, k in ipairs(saved.links) do pcall(function() k.link:delete() end) end
    pcall(function()
        hf.entity_links:insert('#', {new = df.histfig_entity_link_former_positionst, assignment_id = a.id,
                                     entity_id = ent.id, start_year = start, end_year = df.global.cur_year,
                                     link_strength = 100})
    end)
    pcall(function()
        local id = df.global.hist_event_next_id
        df.global.hist_event_next_id = id + 1
        df.global.world.history.events:insert('#', {
            new = df.history_event_remove_hf_entity_linkst, year = df.global.cur_year,
            seconds = df.global.cur_year_tick, id = id, civ = ent.id, histfig = hf.id,
            link_type = df.histfig_entity_link_type.POSITION, position_id = p.id})
    end)
end

local function no(err, extra)
    local r = {ok = false, rejected = true, error = err}
    for k, v in pairs(extra or {}) do r[k] = v end
    return r
end

-- Replace the holder of a held civilian office. opts: interim_out (the
-- messenger's interim holder, one holding another office, replaced by any
-- suitable free citizen), else margin_add / margin_factor (the candidate's
-- skill score must reach needed()).
function replace(code, dry_run, txt, opts)
    opts = opts or {}
    local civil = false
    for _, c in ipairs(SWAP_OFFICES) do if c == code then civil = true end end
    if not civil then return no('the AI replaces only ' .. table.concat(SWAP_OFFICES, ', ')) end
    local ent = reqscript('ai-util').fort_entity()
    if not ent then return {ok = false, error = 'no fort government (entity) found'} end
    local a, a_idx, p = held_slot(ent, code)
    if not a then return no('nobody holds the ' .. code:lower():gsub('_', ' ') .. ' to replace') end
    local can, why = N.appointable(ent, p)
    if not can then return no(code:lower():gsub('_', ' ') .. " is not the fort's to fill (" .. tostring(why) .. ')') end
    local hf = df.historical_figure.find(a.histfig)
    local old = hf and df.unit.find(hf.unit_id)
    if not old then return no('the holder is not on the map') end
    local bound = squad_bound(a, old)
    if bound then return no('the ' .. code:lower():gsub('_', ' ') .. "'s post " .. bound .. ': never swapped') end
    local busy = holder_busy(old, hf, code)
    if busy then return no('the holder is ' .. busy .. ': not now', {busy = busy}) end
    if opts.interim_out and (code ~= 'MESSENGER' or N.fort_offices(old, ent) < 2) then
        return no('the messenger holds no other office: not an interim')
    end
    local c = best_free(code, old.id)
    if not c then return no('no free citizen suits the ' .. code:lower():gsub('_', ' ')) end
    local hs, cs = N.skill_score(N.office_skills(old, code)), N.skill_score(c.skills)
    local need = needed(hs, opts.margin_add, opts.margin_factor)
    if not opts.interim_out and cs < need then
        return no('not vastly better: skill ' .. hs .. ' -> ' .. cs .. ' (needs ' .. need .. ')',
                  {holder_score = hs, cand_score = cs})
    end
    local new = df.unit.find(c.id)
    local out = {ok = true, office = code, replaced = name_of(old, txt), replaced_unit = old.id,
                 name = name_of(new, txt), unit_id = c.id, holder_score = hs, cand_score = cs,
                 interim_out = opts.interim_out and true or nil, dry_run = dry_run or nil}
    if dry_run then return out end
    -- all or nothing: the old holder off, the new one on, else the old one back
    local saved = take_off(ent, a, hf)
    if N.holds_office(old, p.code) then
        put_back(a, hf, saved)
        return {ok = false, office = code, error = 'DFHack still saw ' .. tostring(out.replaced)
                .. ' in the office after taking them off: left as it was'}
    end
    -- (r11 n1 fixes) an error inside the write: the new link out, the old holder back
    local okw, wrote = pcall(N.write_appointment, ent, a, a_idx, p, new)
    if not okw then
        a.histfig = -1
        pcall(drop_new, ent, a, df.historical_figure.find(new.hist_figure_id))
        put_back(a, hf, saved)
        pcall(N.sync_held, ent, true)
        return {ok = false, office = code, restored = N.holds_office(old, p.code),
                error = 'the appointment failed (' .. tostring(wrote):sub(1, 120) .. '), so ' .. tostring(out.replaced)
                        .. ' was put back'}
    end
    if not wrote then
        put_back(a, hf, saved)
        pcall(N.sync_held, ent, true)
        return {ok = false, office = code, restored = N.holds_office(old, p.code),
                error = 'DFHack did not see ' .. tostring(out.name) .. ' appointed, so ' .. tostring(out.replaced)
                        .. ' was put back'}
    end
    note_former(ent, hf, a, p, saved)
    return out
end
