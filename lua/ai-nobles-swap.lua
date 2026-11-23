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
local U = reqscript('ai-util')      -- (r11) the shared helpers

PART_VERSIONS = {['ai-nobles-swap'] = '0.105.72'}   -- (r11 n1 fixes) bumped with BRIDGE_VERSION

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

local function name_of(u, txt) return u and U.name_of(u, txt) or nil end   -- (r11) ai-util's, protected

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
    local ent = U.fort_entity()
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

-- --- (r14 m1) a holder who left the fort --------------------------------------
-- Live (22 Nov 20:58, probe-messenger-where): in A, C and F the messenger's
-- one slot named a figure with no unit anywhere in world.units.all, whose
-- whereabouts was an army of a nomadic group of the fort's own civilisation
-- (goal CAMP, "The Torments of Tattooing"), with no mission of the fort's out.
-- Every Make contact was refused "the messenger is away" and the post could
-- never be refilled. A holder is STALE when their figure has no living unit
-- on the map (none in world.units.all, or dead) and they are not away on one
-- of this fort's own missions (an army whose controller is the fort's
-- government's or civilisation's, with a mission goal; another entity's, a
-- CAMP, or no army at all: stale). Never judged while a Make contact run is
-- under way (the sender holds the messenger then). Elected and inherited
-- posts, the expedition leader, the mayor and the militia are never freed.

-- the army controller goals of a mission the fort sends (lua/ai-mission-send.lua GOALS)
MISSION_GOALS = {DIPLOMACY = true, SITE_INVASION = true, RECOVER_ARTIFACT = true, RESCUE_HF = true,
                 MAKE_REQUEST = true}
NEVER_FREED = {EXPEDITION_LEADER = true, MAYOR = true}

local function rd(f) local ok, v = pcall(f); if ok then return v end end

local function enum_word(enum, v)
    local s = rd(function() return enum[v] end)
    if s ~= nil then return tostring(s) end
    return v ~= nil and tostring(v) or nil
end

-- the figure's unit in world.units.all (by unit_id first, then by figure), or nil
local function unit_of(hf)
    local u = rd(function() return df.unit.find(hf.unit_id) end)
    if u and rd(function() return u.hist_figure_id end) == hf.id then return u end
    local found
    pcall(function()
        for _, x in ipairs(df.global.world.units.all) do
            if x.hist_figure_id == hf.id then found = x; break end
        end
    end)
    return found
end

local function dead_unit(u)
    return rd(function() return u.flags2.killed end) == true or rd(function() return dfhack.units.isDead(u) end) == true
end

-- Why `hf`, holding one of `ent`'s posts, is stale ({name, entity, entity_name,
-- entity_type, goal, year, state, army_id, dead}), or nil when they are home
-- or away on the fort's own mission. `during_run`: judged during a Make
-- contact run too (the sender's own check). (r14 m1 fixes) Stale only on
-- positive evidence: dead, or no living unit and the whereabouts army's
-- controller is another entity's (not the fort's government or civilisation)
-- or a CAMP. Everything else with no unit (army or controller missing, the
-- fort's own controller with another goal, no army at all) can't be told
-- from a messenger still on the fort's mission: nil, and the reading as the
-- second value (`unknown`, with `reason`), never freed. (DF's whereabouts
-- state army_died is its IN_ARMY: a messenger on the fort's own mission
-- reads the same, so the controller decides.)
function stale_holder(hf, ent, txt, during_run)
    if not hf then return nil end
    if not during_run then
        local run = rd(function() return reqscript('ai-mission-send').RUN end)
        if run then return nil end
    end
    local dead = (tonumber(rd(function() return hf.died_year end)) or -1) >= 0
    local u = unit_of(hf)
    if u and not dead and not dead_unit(u) then return nil end
    local out = {holder_hf = hf.id, dead = (dead or (u and dead_unit(u))) and true or nil,
                 name = (txt or tostring)(N.translate_name(hf.name)) or tostring(hf.id)}
    local w = rd(function() return hf.info.whereabouts end)
    if w then
        out.state = enum_word(df.whereabouts_type, rd(function() return w.state end))
        out.army_id = tonumber(rd(function() return w.army_id end))
    end
    if out.dead then return out end
    local function unknown(reason) out.reason = reason; out.unknown = true; return nil, out end
    if not (out.army_id and out.army_id >= 0) then
        return unknown('no unit on the map and on no army (whereabouts ' .. tostring(out.state or 'unread') .. ')')
    end
    local army = rd(function() return df.army.find(out.army_id) end)
    if not army then return unknown('no unit on the map; its army ' .. out.army_id .. ' is not found') end
    local ctl = rd(function() return df.army_controller.find(army.controller_id) end)
    if not ctl then return unknown('no unit on the map; its army has no controller') end
    out.entity = tonumber(rd(function() return ctl.entity_id end))
    out.goal = enum_word(df.army_controller_goal_type, rd(function() return ctl.goal end))
    out.year = tonumber(rd(function() return ctl.year end))
    local e = out.entity and rd(function() return df.historical_entity.find(out.entity) end)
    if e then
        out.entity_name = rd(function() return (txt or tostring)(N.translate_name(e.name, true)) end)
        out.entity_type = enum_word(df.historical_entity_type, rd(function() return e.type end))
    end
    local pi = df.global.plotinfo
    local ours = out.entity == ent.id or out.entity == rd(function() return pi.group_id end)
                 or out.entity == rd(function() return pi.civ_id end)
    if out.entity ~= nil and not ours then return out end      -- with another entity's army: gone
    if out.goal == 'CAMP' then return out end                   -- a camp: no mission
    if ours and MISSION_GOALS[out.goal or ''] then return nil end   -- away on the fort's own mission
    return unknown('no unit on the map; on an army of ' .. (out.entity and ('entity ' .. out.entity) or 'no entity')
                   .. ' (' .. tostring(out.goal or 'no goal') .. ')')
end

-- (r14 m1 fixes) a Diplomacy mission of the fort's or its civilisation's out
-- (world.army_controllers.all), or nil: no messenger is freed meanwhile
function diplomacy_out(ent)
    local found
    pcall(function()
        local pi = df.global.plotinfo
        for _, c in ipairs(df.global.world.army_controllers.all) do
            local eid = c.entity_id
            if (eid == ent.id or eid == pi.group_id or eid == pi.civ_id)
                    and enum_word(df.army_controller_goal_type, c.goal) == 'DIPLOMACY' then
                found = c.id; break
            end
        end
    end)
    return found
end

-- the words for a stale holder: "the messenger X left the fort with Y (CAMP): the post is free"
function stale_why(code, st)
    local word = 'the ' .. tostring(code):lower():gsub('_', ' ')
    if st.dead then return word .. ' ' .. tostring(st.name) .. ' is dead: the post is free' end
    if st.entity_name or st.entity then
        return word .. ' ' .. tostring(st.name) .. ' left the fort with ' .. tostring(st.entity_name or ('entity ' .. st.entity))
               .. ' (' .. tostring(st.goal or 'no goal') .. '): the post is free'
    end
    return word .. ' ' .. tostring(st.name) .. ' left the fort (no unit on the map, on no mission of the fort\'s): the post is free'
end

-- the code the AI fills a post under (MESSENGER by its duty too), or nil
local function ai_code(p)
    if N.is_messenger(p) then return 'MESSENGER' end
    if N.OFFICES[p.code] then return p.code end
end

-- each stale slot the AI may free: idx, assignment, post, figure, stale, code
local function stale_slots(ent, txt, want)
    local out = {}
    for idx, a in ipairs(ent.positions.assignments) do
        if a.histfig ~= -1 then
            local p = position_of(ent, a.position_id)
            local code = p and ai_code(p)
            if code and (want == nil or code == want) and not NEVER_FREED[code] and not N.MILITARY_OFFICES[code] then
                local hf = df.historical_figure.find(a.histfig)
                local st = hf and stale_holder(hf, ent, txt)
                if st then table.insert(out, {idx = idx, a = a, p = p, hf = hf, st = st, code = code}) end
            end
        end
    end
    return out
end

-- Read only: {code = stale} for each AI-filled office whose holder left the
-- fort (the first such slot each), with `why` and `fixed` (not the fort's to fill).
function stale_survey(ent, txt)
    local out = {}
    for _, s in ipairs(stale_slots(ent, txt)) do
        if not out[s.code] then
            local st = s.st
            st.why = stale_why(s.code, st)
            local can, why = N.appointable(ent, s.p)
            if not can then st.fixed = why or true end
            if (tonumber(s.a.squad_id) or -1) ~= -1 then st.fixed = 'leads a squad' end
            out[s.code] = st
        end
    end
    return out
end

-- (r14 m1) a figure's id and whereabouts, for an appointment's result (how
-- does a messenger end up with a nomadic camp?)
function figure_where(u)
    local hf = u and rd(function() return df.historical_figure.find(u.hist_figure_id) end)
    if not hf then return nil, nil end
    local w = rd(function() return hf.info.whereabouts end)
    return hf.id, w and {state = enum_word(df.whereabouts_type, rd(function() return w.state end)),
                         army_id = tonumber(rd(function() return w.army_id end))} or nil
end

-- Free a post whose holder left the fort and fill it at once (the best
-- suitable citizen; with opts.interim, an office holder when none is free),
-- all-or-nothing: the stale holder taken off as take_off does, the new one
-- written and read back; if that fails the old holder is put back. Only
-- after both stand: the former-position link and the history event.
function free_stale(code, dry_run, txt, opts)
    opts = opts or {}
    if N.MESSENGER_HOLD and code == 'MESSENGER' then     -- (r14 hold) see ai-nobles
        return {ok = false, rejected = true, error = N.MESSENGER_HOLD_WHY, why = N.MESSENGER_HOLD_WHY}
    end
    local word = tostring(code):lower():gsub('_', ' ')
    if NEVER_FREED[code] or N.MILITARY_OFFICES[code] or not N.OFFICES[code] then
        return no('the AI frees only the civilian offices it fills, not the ' .. word)
    end
    local ent = U.fort_entity()
    if not ent then return {ok = false, error = 'no fort government (entity) found'} end
    local s = stale_slots(ent, txt, code)[1]
    if not s then return no('no ' .. word .. ' has left the fort: nothing to free') end
    local a, a_idx, p, hf, st = s.a, s.idx, s.p, s.hf, s.st
    st.why = stale_why(code, st)
    local can, why = N.appointable(ent, p)
    if not can then return no(word .. " is not the fort's to fill (" .. tostring(why) .. ')', {stale = st}) end
    if (tonumber(a.squad_id) or -1) ~= -1 then return no('the ' .. word .. "'s post leads a squad: never freed") end
    if code == 'MESSENGER' then        -- (r14 m1 fixes) the Lua side too: not while a Diplomacy mission is out
        local dip = diplomacy_out(ent)
        if dip then return no('a Diplomacy mission (controller ' .. tostring(dip) .. ') is out: not now', {stale = st}) end
    end
    local c, keeps = N.choose_holder(code, opts.interim == true)
    if not c then
        return no('nobody suitable to take the ' .. word .. "'s post: left as it is", {stale = st})
    end
    local new = df.unit.find(c.id)
    local out = {ok = true, office = code, freed = st.name, freed_hf = hf.id, left_with = st.entity_name,
                 goal = st.goal, why = st.why, stale = st, name = name_of(new, txt), unit_id = c.id,
                 interim = keeps and true or nil, keeps = keeps, dry_run = dry_run or nil}
    out.figure, out.whereabouts = figure_where(new)
    if dry_run then return out end
    local saved = take_off(ent, a, hf)
    local okw, wrote = pcall(N.write_appointment, ent, a, a_idx, p, new)
    if not okw or not wrote then
        if not okw then
            a.histfig = -1
            pcall(drop_new, ent, a, df.historical_figure.find(new.hist_figure_id))
        end
        put_back(a, hf, saved)
        pcall(N.sync_held, ent, true)
        return {ok = false, office = code, restored = a.histfig == hf.id,
                error = (okw and ('DFHack did not see ' .. tostring(out.name) .. ' appointed')
                         or ('the appointment failed (' .. tostring(wrote):sub(1, 120) .. ')'))
                        .. ', so ' .. tostring(st.name) .. ' was put back'}
    end
    note_former(ent, hf, a, p, saved)
    return out
end
