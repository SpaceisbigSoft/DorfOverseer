-- The fort's offices: who holds them, and appointing the best-suited dwarf
-- to a vacant one (manager, bookkeeper, broker, chief medical dwarf, sheriff,
-- captain of the guard).
--
-- A fort needs these without anyone at the keyboard: from 20 citizens DF
-- does a work order only once the manager has validated it, and almost
-- everything the AI makes is a work order. DFHack has no call that appoints,
-- so this writes the same two records DF's nobles screen does (as DFHack's
-- own make-monarch script does for a monarch):
--   * the office's assignment names the dwarf's historical figure as holder;
--   * the figure gets a position link to the fort's government (the entity),
--     pointing at that assignment.
-- Then it reads the appointment back through DFHack's own getNoblePositions;
-- if DFHack doesn't see it, both writes are undone and it says so. A history
-- event is added as the game does (so legends show it); if that fails the
-- appointment stands.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

-- A DF name in words (dfhack.TranslateName was renamed in DFHack 50.15).
local function translate(name, english)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, english) end)
    if ok and s then return s end
    ok, s = pcall(function() return dfhack.TranslateName(name, english) end)
    return ok and s or '?'
end

-- office -> the skills that make a good holder (the first counts most)
OFFICES = {
    MANAGER = {'ORGANIZATION', 'RECORD_KEEPING'},
    BOOKKEEPER = {'RECORD_KEEPING', 'ORGANIZATION'},
    BROKER = {'APPRAISAL', 'NEGOTIATION', 'PERSUASION', 'JUDGING_INTENT'},
    CHIEF_MEDICAL_DWARF = {'DIAGNOSE'},
    -- justice: crimes are reported to the sheriff (a fort without one leaves
    -- them unpunished); a dwarf who reads people and can fight
    SHERIFF = {'JUDGING_INTENT', 'OBSERVATION', 'MELEE_COMBAT', 'DISCIPLINE'},
    -- the post a growing fort adds over the sheriff's: leads the fort guard
    CAPTAIN_OF_THE_GUARD = {'JUDGING_INTENT', 'MELEE_COMBAT', 'LEADERSHIP', 'DISCIPLINE'},
}
OFFICE_ORDER = {'MANAGER', 'BOOKKEEPER', 'CHIEF_MEDICAL_DWARF', 'BROKER', 'SHERIFF', 'CAPTAIN_OF_THE_GUARD'}

-- (0.104.168) the military offices, refilled when their holder dies
-- (Teacheroar's spirals killed squad leaders with the rest): the commander
-- (appointed by the expedition leader or mayor) and a captain whose slot
-- leads a squad (appointed by the commander). A vacant captain's slot that
-- leads no squad is the one DF keeps for the next squad (make_squad's). The
-- new holder takes the squad's leader seat (lua/ai-military.lua seat_leader).
-- Never a soldier of a squad already, a mother of a baby (it is carried into
-- every fight), a child; the miserable only when nobody else will do.
OFFICES.MILITIA_COMMANDER = {'MILITARY_TACTICS', 'LEADERSHIP', 'MELEE_COMBAT', 'DISCIPLINE'}
OFFICES.MILITIA_CAPTAIN = {'LEADERSHIP', 'MELEE_COMBAT', 'MILITARY_TACTICS', 'DISCIPLINE'}
MILITARY_OFFICES = {MILITIA_COMMANDER = true, MILITIA_CAPTAIN = true}
table.insert(OFFICE_ORDER, 'MILITIA_COMMANDER')
table.insert(OFFICE_ORDER, 'MILITIA_CAPTAIN')

-- (0.105.0, 13b) the messenger (Nobles and Administration), who carries the
-- fort's word on a Diplomacy mission ("Make contact"): only when the fort has
-- the post, and never a soldier, a mother of a baby, a hospital's or any
-- location's staff, a patient, nor a dwarf holding another office (they'd be
-- away for seasons): the best talker of the rest. (0.105.24) Nor one wounded.
-- (r11 n1) When nobody else is suitable, an office holder with `interim`
-- (pick_interim), swapped out later (lua/ai-nobles-swap.lua).
OFFICES.MESSENGER = {'PERSUASION', 'NEGOTIATION', 'CONVERSATION', 'JUDGING_INTENT'}
CIVILIAN_AWAY_OFFICES = {MESSENGER = true}
table.insert(OFFICE_ORDER, 'MESSENGER')

-- Pure: the best candidate. Each: {id, skills = {level, level...} in the
-- office's order, offices = offices already held, soldier = bool, child =
-- bool}. Dwarves without an office before any with one (one job each), then
-- the skilled (the first skill counts double), never a child, soldiers last; ties to the
-- lower id. (0.104.168) `miserable` (very unhappy or worse): only when nobody
-- else will do; with `military` (a military office) never a mother of a baby.
function pick_holder(cands, military)
    local best, best_score
    for _, c in ipairs(cands) do
        -- (0.104.168, review) a squad's leader is never a mother of a baby, a
        -- patient, one of the hospitals' (or any location's) staff, nor the
        -- unhappy; one who wants to fight first
        if not c.child and not (military and (c.mother or c.patient or c.staff or c.miserable or c.unhappy))
                and not (c.away_post and (c.mother or c.patient or c.staff or c.hurt or (c.offices or 0) > 0)) then   -- (0.105.0; hurt 0.105.24)
            local score = 0
            for i, lvl in ipairs(c.skills or {}) do score = score + (i == 1 and 2 or 1) * (lvl or 0) end
            -- a dwarf already holding an office only when nobody else will do
            score = score * 10 - 1000 * (c.offices or 0) - (c.soldier and 15 or 0)
            if c.miserable then score = score - 5000 end      -- (0.104.168)
            if military and c.wants_fight then score = score + 300 end
            if best_score == nil or score > best_score or (score == best_score and c.id < best.id) then
                best, best_score = c, score
            end
        end
    end
    return best
end

-- Pure: an office's skill score (the first skill counts double), as pick_holder weighs it.
function skill_score(skills)
    local score = 0
    for i, lvl in ipairs(skills or {}) do score = score + (i == 1 and 2 or 1) * (tonumber(lvl) or 0) end
    return score
end

-- (r11 n1, the player 22 Nov 01:43) A tiny fort's interim messenger: when no
-- free citizen is suitable, an office holder carries the fort's word too. The
-- office that matters least at home first (a lower rank); never a holder of
-- any office not ranked here (the expedition leader, mayor, militia...), a
-- soldier, a child, a patient, staff, the wounded, a mother of a baby (one in
-- a mood never reaches the candidates). Among them the best talker.
INTERIM_RANK = {BOOKKEEPER = 1, BROKER = 2, SHERIFF = 3, CAPTAIN_OF_THE_GUARD = 4, CHIEF_MEDICAL_DWARF = 5,
                MANAGER = 6}

-- Pure: the interim messenger of the candidates (each with `codes`, the
-- offices held), and the office that ranks them; nil when none fits.
function pick_interim(cands)
    local best, best_tier, best_score, best_code
    for _, c in ipairs(cands) do
        if not (c.child or c.soldier or c.mother or c.patient or c.staff or c.hurt) and (c.offices or 0) > 0
                and type(c.codes) == 'table' and #c.codes > 0 then
            local tier, code = 0, nil
            for _, k in ipairs(c.codes) do
                local r = INTERIM_RANK[k]
                if not r then tier = nil; break end
                if r > tier then tier, code = r, k end
            end
            if tier then
                local score = skill_score(c.skills) - (c.miserable and 5000 or 0)
                if best == nil or tier < best_tier or (tier == best_tier and (score > best_score
                        or (score == best_score and c.id < best.id))) then
                    best, best_tier, best_score, best_code = c, tier, score, code
                end
            end
        end
    end
    return best, best_code
end

-- --- the game -----------------------------------------------------------------


local function position_of(ent, id)
    for _, p in ipairs(ent.positions.own) do
        if p.id == id then return p end
    end
end

local function skill(u, name)
    local id = df.job_skill[name]
    local soul = u.status.current_soul
    if not soul or not id then return 0 end
    for _, s in ipairs(soul.skills) do
        if s.id == id then return s.rating end
    end
    return 0
end

-- (r11 n1) the codes of the offices a dwarf holds
local function codes_held(u)
    local out = {}
    pcall(function()
        for _, p in ipairs(dfhack.units.getNoblePositions(u) or {}) do table.insert(out, p.position.code) end
    end)
    return out
end

-- (r11 n1) a dwarf's levels in an office's skills, in its order
function office_skills(u, code)
    local out = {}
    for i, name in ipairs(OFFICES[code] or {}) do out[i] = skill(u, name) end
    return out
end

-- (r11 n1) Why a figure (an office holder) is away, or nil: on an army's roll
-- (a mission), no unit on the map, an inactive or departed unit; for the
-- messenger also a mission being sent right now (lua/ai-mission-send.lua RUN:
-- a Make contact run picks the messenger on the World screen).
function holder_away(hf, messenger)
    if not hf then return 'not found' end
    local oka, army = pcall(function() return hf.info.whereabouts.army_id end)
    if oka and type(army) == 'number' and army >= 0 then return 'away with an army (a mission)' end
    local u = df.unit.find(hf.unit_id)
    if not u then return 'not on the map' end
    local oki, inactive = pcall(function() return u.flags1.inactive end)
    local okl, left = pcall(function() return u.flags1.left end)
    if (oki and inactive) or (okl and left) then return 'off the map' end
    if messenger then
        local okr, run = pcall(function() return reqscript('ai-mission-send').RUN end)
        if okr and run then return 'a mission is being sent (' .. tostring(run.goal or '?') .. ')' end
    end
    return nil
end

local function holds(u, code)
    local list = dfhack.units.getNoblePositions(u)
    for _, p in ipairs(list or {}) do
        if p.position.code == code then return true end
    end
    return false
end

-- (0.101.6) DF keeps, besides the assignments, a list per duty of the posts
-- held (assignments_by_type: MANAGE_PRODUCTION, TRADE, HEALTH_MANAGEMENT...),
-- and the game finds its manager, broker, doctor there. Appointments written
-- before 0.101.6 left it empty: the Enxah fort's manager was never seen, so no
-- work order ever started. Returns the held posts missing from it, and the
-- listed posts no longer held; with fix, puts that right.
function sync_held(ent, fix)
    local missing, stale = 0, 0
    for _, a in ipairs(ent.positions.assignments) do
        local p = a.histfig ~= -1 and position_of(ent, a.position_id)
        if p then
            for i, on in ipairs(p.responsibilities) do
                if on then
                    local lst, found = ent.assignments_by_type[i], false
                    for _, b in ipairs(lst) do if b == a then found = true break end end
                    if not found then
                        missing = missing + 1
                        if fix then lst:insert('#', a) end
                    end
                end
            end
        end
    end
    for i, lst in ipairs(ent.assignments_by_type) do
        for k = #lst - 1, 0, -1 do
            if lst[k].histfig == -1 then
                stale = stale + 1
                if fix then lst:erase(k) end
            end
        end
    end
    return missing, stale
end

function sync_offices(dry_run)
    local ent = U.fort_entity()
    if not ent then return {ok = false, error = 'no fort government (entity) found'} end
    local missing, stale = sync_held(ent, not dry_run)
    if missing + stale == 0 then return {ok = false, rejected = true, error = 'the duty lists are right already'} end
    return {ok = true, added = missing, removed = stale, dry_run = dry_run or nil}
end

-- The fort's offices (read-only): code -> {held_by, vacant assignments,
-- appointable}, plus what the AI may fill.
function survey(txt)
    local ent = U.fort_entity()
    if not ent then return {error = 'no fort government (entity) found'} end
    local out = {entity = ent.id, offices = {}}
    pcall(function()   -- (0.101.6) held posts the game can't see
        local missing, stale = sync_held(ent, false)
        if missing + stale > 0 then out.unlisted, out.stale_listed = missing, stale end
    end)
    for idx, a in ipairs(ent.positions.assignments) do
        local p = position_of(ent, a.position_id)
        if p then
            local o = out.offices[p.code] or {vacant = 0, held = {}, appointed_by = #p.appointed_by,
                                                ai = OFFICES[p.code] ~= nil}
            if o.appointable == nil then          -- (0.104.168) the fort's to fill, or DF's
                local okp, can, why = pcall(appointable, ent, p)
                if okp then o.appointable, o.not_why = can, why end
            end
            if a.histfig == -1 then
                o.vacant = o.vacant + 1
                -- (0.104.168) a vacant slot that leads a squad (a dead leader's)
                if (tonumber(a.squad_id) or -1) ~= -1 then o.vacant_squad = (o.vacant_squad or 0) + 1 end
            else
                local hf = df.historical_figure.find(a.histfig)
                table.insert(o.held, hf and (txt or tostring)(translate(hf.name)) or tostring(a.histfig))
            end
            out.offices[p.code] = o
        end
    end
    -- (r2 h9) the messenger: DF's raws make it [NUMBER:AS_NEEDED], and DF adds a
    -- slot only when the player fills one on the nobles screen, so no fort had
    -- a MESSENGER in this list (A5 finding 2: offices of A-F) and Make contact
    -- could never run. The position itself is read here (the civilisation's
    -- own list); the appoint action adds the slot as the screen does.
    pcall(function()
        local okp, p = pcall(position_by_code, ent, 'MESSENGER')
        p = okp and p or nil
        out.messenger = {position = p ~= nil}
        if not p then return end
        -- (r10 p2) a post found by its duty under another code: read as MESSENGER
        if p.code ~= 'MESSENGER' and out.offices[p.code] and not out.offices.MESSENGER then
            out.offices.MESSENGER = out.offices[p.code]
        end
        local slots = 0
        for _, a in ipairs(ent.positions.assignments) do
            if a.position_id == p.id then slots = slots + 1 end
        end
        out.messenger.slots = slots
        pcall(function() out.messenger.number = tonumber(p.number) end)
        if slots == 0 and not out.offices.MESSENGER then
            local okc, can, why = pcall(appointable, ent, p)
            out.offices.MESSENGER = {vacant = 0, held = {}, slots = 0, appointed_by = #p.appointed_by, ai = true,
                                     appointable = okc and can or false, not_why = okc and why or nil,
                                     no_slot = true}
        end
    end)
    -- (r10 p2) where the post is and why nobody carries the fort's word (missions.messenger.why too)
    pcall(function()
        local st = messenger_status(txt, ent)
        out.messenger = out.messenger or {position = false}
        for _, k in ipairs({'post', 'code', 'why', 'requires_population', 'population', 'pop_met', 'interim',
                            'interim_possible', 'interim_unit', 'interim_name', 'interim_office', 'holder_unit',
                            'free_unit', 'free_name', 'away'}) do
            out.messenger[k] = st[k]
        end
        local o = out.offices.MESSENGER
        local gate = st.post == 'fort' and not st.held_by
                     and pop_gate(st.requires_population, st.population, st.pop_met)
        if o and gate then o.appointable, o.not_why = false, gate end
    end)
    -- (r11 n1) each civilian office's holder against the best free candidate
    -- (lua/ai-nobles-swap.lua): the planner's swaps
    pcall(function() out.swap = reqscript('ai-nobles-swap').swap_survey(ent, txt) end)
    return out
end

-- (r2 h9) the fort government's position of this code, and its index
function position_by_code(ent, code)
    for idx, p in ipairs(ent.positions.own) do
        if p.code == code then return p, idx end
    end
    -- (r10 p2) the messenger by its duty too (DELIVER_MESSAGES), whatever its code
    if code == 'MESSENGER' then
        for idx, p in ipairs(ent.positions.own) do
            if delivers_messages(p) then return p, idx end
        end
    end
end

-- --- (r10 p2, 13b) the messenger's post ----------------------------------------
-- What df-structures shows (docs/dfhack-notes.md "The messenger (r10)"):
-- the duty is entity_position_responsibility DELIVER_MESSAGES; a civilisation
-- keeps its site posts' templates in positions.site (site_position_template)
-- and a site government its own posts in positions.own; a post has
-- requires_population and the flag HAS_MET_POP_REQ. Nothing in DFHack copies
-- a template into a fort's own list, and no evidence says how DF does it, so
-- the AI never writes a post: it appoints once DF has given the fort the post
-- (the existing slot + appointment writes), and otherwise says why not.

-- the post carries messages (its duty), protected
function delivers_messages(p)
    local ok, on = pcall(function()
        return p.responsibilities[df.entity_position_responsibility.DELIVER_MESSAGES]
    end)
    return ok and on == true
end

function is_messenger(p)
    if p == nil then return false end
    local okc, code = pcall(function() return p.code end)
    return (okc and code == 'MESSENGER') or delivers_messages(p)
end

local function first_messenger(list)
    local found
    pcall(function()
        for _, p in ipairs(list) do
            if is_messenger(p) then found = p; break end
        end
    end)
    return found
end

local function pop_flag(p)
    local ok, v = pcall(function() return p.flags.HAS_MET_POP_REQ end)
    if ok and type(v) == 'boolean' then return v end
    return nil
end

-- Pure: why a post of the fort (or a civilisation template) isn't open yet
-- for its population: req and pop numbers, met = the post's HAS_MET_POP_REQ
-- (nil unread). DF's wiki: a post needing 7 or fewer is open from embark;
-- above that it opens only when DF evaluates its posts. Returns a why or nil.
function pop_gate(req, pop, met)
    req = tonumber(req) or 0
    if req <= 0 or met == true then return nil end
    if pop and pop < req then
        return 'no post until population ' .. req .. ' (now ' .. pop .. ')'
    end
    if met == false then
        return 'post listed but not open yet: population ' .. req .. ' reached (now ' .. tostring(pop)
               .. ') and DF has not opened it (it re-checks its posts only at some events)'
    end
    if pop == nil and met == nil then           -- (r10 v12) nothing known: wait, don't guess
        return 'post needs population ' .. req .. ' and neither the count nor DF\'s flag could be read'
    end
    return nil
end


-- (r2 h9) a vacant slot for an AS_NEEDED position (the messenger), added as
-- DF's nobles screen does: a new assignment with the next id, nobody in it
-- (DF's duty lists take it once it is held: sync_held). Returns it and its
-- index, or nil and why.
function add_slot(ent, code)
    local p, pidx = position_by_code(ent, code)
    if not p then return nil, 'this civilisation gives the fort no ' .. code .. ' position' end
    local n = 0
    for _, a in ipairs(ent.positions.assignments) do
        if a.position_id == p.id then n = n + 1 end
    end
    local number = tonumber(p.number) or 1
    if number >= 0 and n >= number then return nil, 'all ' .. number .. ' ' .. code .. ' slots are in use' end
    local can, why = appointable(ent, p)
    if not can then return nil, code:lower() .. " is not the fort's to fill (" .. tostring(why) .. ')' end
    local a = df.entity_position_assignment:new()
    a.id = ent.positions.next_assignment_id
    a.histfig = -1
    pcall(function() a.histfig2 = -1 end)
    a.position_id = p.id
    pcall(function() a.position_vector_idx = pidx end)
    a.squad_id = -1
    -- the flags of another slot of the fort's government (DF's 'active')
    local like
    pcall(function() like = #ent.positions.assignments > 0 and ent.positions.assignments[0] or nil end)
    if like then pcall(function() a.flags.active = like.flags.active end) end
    ent.positions.next_assignment_id = a.id + 1
    ent.positions.assignments:insert('#', a)
    return a, #ent.positions.assignments - 1, p
end

-- (r2 h9) take back a slot add_slot made (nobody could be appointed)
function drop_slot(ent, a)
    for i = #ent.positions.assignments - 1, 0, -1 do
        local v = ent.positions.assignments[i]
        if v == a or (v and v.id == a.id) then ent.positions.assignments:erase(i) end
    end
    if ent.positions.next_assignment_id == a.id + 1 then ent.positions.next_assignment_id = a.id end
    pcall(function() a:delete() end)
end

-- (0.104.168) mothers of babies: unit id -> true
local function mothers()
    local out = {}
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            if dfhack.units.isBaby(u) then
                local m = u.relationship_ids.Mother
                if m and m ~= -1 then out[m] = true end
            end
        end
    end)
    return out
end

local function candidates(code)
    local wants = OFFICES[code]
    local military = MILITARY_OFFICES[code]
    local moms = (military or CIVILIAN_AWAY_OFFICES[code]) and mothers() or {}   -- (0.105.33 review) once, not per candidate
    local out = {}
    for _, u in ipairs(report_citizens(true)) do
        -- (0.104.168) a military office's holder takes a squad's leader seat:
        -- never a soldier of a squad already
        -- (0.105.0) the messenger is away for seasons: never a soldier either
        local away = CIVILIAN_AWAY_OFFICES[code]
        -- (0.105.51) never one in a mood: a strange mood (R3: A's Urdim, possessed
        -- and gathering, made militia captain on day 20; insane on day 42) or
        -- one gone insane
        local okmd, md = pcall(function() return u.mood end)
        local moody = okmd and type(md) == 'number' and md >= 0
        if u.hist_figure_id >= 0 and not moody and not ((military or away) and u.military.squad_id >= 0) then
            local skills = {}
            for i, name in ipairs(wants) do skills[i] = skill(u, name) end
            local okm, cat = pcall(function() return dfhack.units.getStressCategory(u) end)
            local codes = codes_held(u)
            local c = {id = u.id, skills = skills, offices = #codes, codes = codes,
                       soldier = u.military.squad_id >= 0,
                       child = dfhack.units.isChild(u) or dfhack.units.isBaby(u),
                       mother = moms[u.id] or nil,
                       miserable = (okm and type(cat) == 'number' and cat <= 1) or nil}
            if away then          -- (0.105.0) no key worker: staff, patients, mothers, office holders out
                pcall(function() c.patient = (u.health and u.health.flags.needs_healthcare) or nil end)
                pcall(function() c.staff = #u.occupations > 0 or nil end)
                c.mother = moms[u.id] or nil
                -- (0.105.24) healthy: never one with an open wound (seasons on the road)
                pcall(function() c.hurt = (#u.body.wounds > 0) or nil end)
                c.away_post = true
            end
            if military then      -- (0.104.168, review)
                c.unhappy = (okm and type(cat) == 'number' and cat <= 2) or nil
                pcall(function() c.patient = (u.health and u.health.flags.needs_healthcare) or nil end)
                pcall(function() c.staff = #u.occupations > 0 or nil end)
                pcall(function()
                    for _, nd in ipairs(u.status.current_soul.personality.needs) do
                        local t = df.need_type[nd.id]
                        if (t == 'Fight' or t == 'MartialTraining') and nd.focus_level <= -1000 then c.wants_fight = true end
                    end
                end)
            end
            table.insert(out, c)
        end
    end
    return out
end

-- (r11 n1) for lua/ai-nobles-swap.lua
function office_candidates(code) return candidates(code) end
function holds_office(u, code) return holds(u, code) end
function translate_name(n, english) return translate(n, english) end

-- (0.104.168) May the fort fill this office itself? Only one appointed by
-- an office of the fort's own government that someone holds (the mayor,
-- the expedition leader, the militia commander); never an elected one
-- (the mayor), one passed to an heir (a baron...), one replaced (the
-- sheriff by the captain of the guard), or one a monarch elsewhere
-- appoints: those are left to DF. Returns can, why-not.
function appointable(ent, pos)
    local why
    pcall(function()
        if pos.flags.ELECTED then why = 'elected' end
        if pos.flags.SUCCESSION_BY_HEIR then why = 'inherited' end
        if pos.flags.HAS_BEEN_REPLACED then why = 'replaced' end
    end)
    if why then return false, why end
    local by = pos.appointed_by
    if not by or #by == 0 then return false, 'nobody appoints it' end
    local civs = nil
    pcall(function() civs = pos.appointed_by_civ end)
    for i = 0, #by - 1 do
        local civ = civs and civs[i]
        if civ == nil or civ == -1 or civ == ent.id then
            for _, a in ipairs(ent.positions.assignments) do
                if a.position_id == by[i] and a.histfig ~= -1 then return true end
            end
        end
    end
    return false, 'its appointer is not in the fort'
end

local function add_event(ent, hf, pos)
    pcall(function()
        local id = df.global.hist_event_next_id
        df.global.hist_event_next_id = id + 1
        df.global.world.history.events:insert('#', {
            new = df.history_event_add_hf_entity_linkst,
            year = df.global.cur_year, seconds = df.global.cur_year_tick, id = id,
            civ = ent.id, histfig = hf.id, link_type = df.histfig_entity_link_type.POSITION,
            position_id = pos.id, appointer_hfid = -1, promise_to_hfid = -1,
        })
    end)
end

-- (r10 p2) The messenger's post read: where it is, what it needs, who holds
-- it, and `why` nobody carries the fort's word yet (nil once it is held).
-- post: 'fort' (the fort's own post), 'civ_site' (only its civilisation's
-- template for its sites), 'civ' (a post of the civilisation itself), 'raw'
-- (only in its raws, entity_raw.positions), 'none'.
-- Read only. `pop` given by a test; else the citizens counted.
function messenger_status(txt, ent, pop)
    ent = ent or U.fort_entity()
    if not ent then return {post = 'unknown', why = 'no fort government (entity) found'} end
    if pop == nil then
        local okp, list = pcall(report_citizens, true)
        pop = okp and type(list) == 'table' and #list or nil
    end
    local out = {post = 'none', population = pop}
    local p = position_by_code(ent, 'MESSENGER')
    if p then
        out.post, out.code, out.position_id = 'fort', p.code, p.id
        pcall(function() out.requires_population = tonumber(p.requires_population) end)
        out.pop_met = pop_flag(p)
        pcall(function() out.number = tonumber(p.number) end)
        local by = {}
        pcall(function()
            for i = 0, #p.appointed_by - 1 do
                local ap = position_of(ent, p.appointed_by[i])
                table.insert(by, ap and ap.code or tostring(p.appointed_by[i]))
            end
        end)
        out.appointed_by = by
        local slots, vacant = 0, 0
        for _, a in ipairs(ent.positions.assignments) do
            if a.position_id == p.id then
                slots = slots + 1
                if a.histfig == -1 then
                    vacant = vacant + 1
                elseif not out.held_by then
                    local hf = df.historical_figure.find(a.histfig)
                    out.holder_hf = a.histfig
                    out.held_by = hf and (txt or tostring)(translate(hf.name)) or tostring(a.histfig)
                end
            end
        end
        out.slots, out.vacant = slots, vacant
        if out.held_by then
            -- (r11 n1) an interim messenger (one holding another office too):
            -- the free suitable citizen who'd take over, and whether they're away
            pcall(function()
                local hf = df.historical_figure.find(out.holder_hf)
                local u = hf and df.unit.find(hf.unit_id)
                out.holder_unit = u and u.id or nil
                out.away = holder_away(hf, true)
                local codes = u and codes_held(u) or {}
                if #codes > 1 then
                    out.interim = true
                    local c = pick_holder(candidates('MESSENGER'), false)
                    if c and c.id ~= out.holder_unit and (c.offices or 0) == 0 then
                        local cu = df.unit.find(c.id)
                        out.free_unit = c.id
                        out.free_name = cu and (txt or tostring)(dfhack.units.getReadableName(cu)) or nil
                    end
                end
            end)
            return out
        end
        local gate = pop_gate(out.requires_population, pop, out.pop_met)
        if gate then out.why, out.appointable = gate, false; return out end
        local okc, can, nwhy = pcall(appointable, ent, p)
        out.appointable = okc and can or false
        if not out.appointable then
            out.why = "post exists, but it is not the fort's to fill (" .. tostring(okc and nwhy or can) .. ')'
            return out
        end
        local okk, c = pcall(function() return pick_holder(candidates('MESSENGER'), false) end)
        if okk and c == nil then
            out.why = 'post exists, nobody suitable to appoint (soldiers, office holders, staff, patients, '
                      .. 'the wounded, mothers of babies and children stay home)'
            -- (r11 n1) an office holder who may double as messenger meanwhile
            pcall(function()
                local ic, icode = pick_interim(candidates('MESSENGER'))
                out.interim_possible = ic ~= nil
                if ic then
                    local iu = df.unit.find(ic.id)
                    out.interim_unit, out.interim_office = ic.id, icode
                    out.interim_name = iu and (txt or tostring)(dfhack.units.getReadableName(iu)) or nil
                end
            end)
        else
            out.why = 'post exists, nobody appointed'
        end
        return out
    end
    -- not the fort's: its civilisation's lists
    local civ
    pcall(function() civ = df.historical_entity.find(df.global.plotinfo.civ_id) end)
    if not civ then out.why = "no post: the fort's civilisation could not be read"; return out end
    local t = first_messenger(civ.positions.site)
    if t then
        out.post, out.code = 'civ_site', t.code
        pcall(function() out.requires_population = tonumber(t.requires_population) end)
        out.why = pop_gate(out.requires_population, pop, nil)
                  or ("no post yet: the civilisation's sites have a messenger post"
                      .. ((out.requires_population or 0) > 0 and (' (from population ' .. out.requires_population .. ')') or '')
                      .. ' but DF has not given it to this fort (the AI does not write posts)')
        return out
    end
    local c = first_messenger(civ.positions.own)
    if c then
        out.post, out.code = 'civ', c.code
        out.why = "no post: the messenger is the civilisation's post, not this fort's to fill"
        return out
    end
    -- the civilisation's raws ([POSITION:...] in entity_raw.positions): a SITE messenger there
    local raw
    pcall(function()
        for _, r in ipairs(civ.entity_raw.positions) do
            local duty = false
            pcall(function() duty = r.responsibilities[df.entity_position_responsibility.DELIVER_MESSAGES] == true end)
            if r.code == 'MESSENGER' or duty then raw = r; break end
        end
    end)
    if raw then
        out.post, out.code = 'raw', raw.code
        pcall(function() out.requires_population = tonumber(raw.requires_population) end)
        out.why = pop_gate(out.requires_population, pop, nil)
                  or "no post yet: the civilisation's raws have a messenger post but DF has not given it to this fort"
        return out
    end
    out.why = 'no post: this civilisation has no messenger position'
    return out
end

-- (r11 n1) The holder for `code`: the best suitable citizen; for the
-- messenger with `interim`, when none is free, an office holder (pick_interim).
-- Returns the candidate, and the office it keeps when it is an interim.
local function choose(code, interim)
    local cands = candidates(code)
    local c = pick_holder(cands, MILITARY_OFFICES[code])
    if c or not (interim and code == 'MESSENGER') then return c end
    return pick_interim(cands)
end

-- Appoint the best-suited citizen to a vacant `code` office. (r11 n1) opts:
-- `interim` (the messenger: an office holder when nobody free is suitable);
-- `replace` (a held civilian office's holder replaced: lua/ai-nobles-swap.lua).
function appoint(code, dry_run, txt, opts)
    opts = type(opts) == 'table' and opts or {}
    if not OFFICES[code] then
        return {ok = false, rejected = true, error = 'the AI only appoints ' .. table.concat(OFFICE_ORDER, ', ')}
    end
    if opts.replace then return reqscript('ai-nobles-swap').replace(code, dry_run, txt, opts) end
    local interim = opts.interim == true
    local ent = U.fort_entity()
    if not ent then return {ok = false, error = 'no fort government (entity) found'} end
    local assignment, a_idx, pos
    local added_slot = false                    -- (r2 h9) a messenger's slot made for this appointment
    local msg_pos_id                            -- (r10 v12) the post messenger_status judged
    if code == 'MESSENGER' then                 -- (r10 p2) only into a post DF has given and opened
        local okst, st = pcall(messenger_status, txt, ent)
        if not okst or type(st) ~= 'table' then
            return {ok = false, rejected = true, error = 'the messenger post could not be read: ' .. tostring(st)}
        end
        if st.post ~= 'fort' then
            return {ok = false, rejected = true, why = st.why,
                    error = 'the fort has no MESSENGER office yet: ' .. tostring(st.why)}
        end
        local gate = (not st.held_by) and pop_gate(st.requires_population, st.population, st.pop_met)
        if gate then return {ok = false, rejected = true, error = gate, why = gate} end
        if st.appointable == false then        -- (r10 v12) elected, inherited, appointer away...
            return {ok = false, rejected = true, why = st.why,
                    error = "the messenger is not the fort's to fill (" .. tostring(st.why) .. ')'}
        end
        msg_pos_id = st.position_id
    end
    if MILITARY_OFFICES[code] then              -- (0.104.168)
        local r = military_slot(ent, code)
        if not r.ok then return r end
        assignment, a_idx, pos = r.assignment, r.idx, r.pos
    else
        for idx, a in ipairs(ent.positions.assignments) do
            local p = position_of(ent, a.position_id)
            -- (r10 p2) the messenger's post found by its duty too
            -- (r10 v12) the messenger: only the very post messenger_status judged
            local match = p and ((code == 'MESSENGER' and msg_pos_id ~= nil and p.id == msg_pos_id)
                or (code == 'MESSENGER' and msg_pos_id == nil and is_messenger(p))
                or (code ~= 'MESSENGER' and p.code == code))
            if match then
                if a.histfig ~= -1 then
                    return {ok = false, rejected = true, error = code .. ' is already held'}
                end
                assignment, a_idx, pos = a, idx, p
                break
            end
        end
        if not assignment and CIVILIAN_AWAY_OFFICES[code] then
            -- (r2 h9) an AS_NEEDED post with no slot yet: one added, as the nobles screen does
            local p0 = position_by_code(ent, code)
            if not p0 then
                return {ok = false, rejected = true, error = 'the fort has no ' .. code .. ' office yet: its civilisation gives it no such position'}
            end
            local can, why = appointable(ent, p0)
            if not can then
                return {ok = false, rejected = true, error = code:lower() .. " is not the fort's to fill (" .. tostring(why) .. ')'}
            end
            local c0, keeps0 = choose(code, interim)
            if c0 == nil then
                return {ok = false, rejected = true, error = 'no grown citizen to appoint'
                        .. (code == 'MESSENGER' and (interim and ' (nor an office holder who may double as messenger)'
                            or ' (an office holder may double as messenger: interim)') or '')}
            end
            if dry_run then
                local u0 = df.unit.find(c0.id)
                return {ok = true, dry_run = true, office = code, slot_added = true, unit_id = c0.id,
                        interim = keeps0 and true or nil, keeps = keeps0,
                        name = u0 and (txt or tostring)(dfhack.units.getReadableName(u0)) or nil}
            end
            local why2
            assignment, a_idx, why2 = add_slot(ent, code)
            if not assignment then return {ok = false, rejected = true, error = tostring(a_idx)} end
            pos = why2
            added_slot = true
        end
        if not assignment then
            return {ok = false, rejected = true, error = 'the fort has no ' .. code .. ' office yet'}
        end
    end
    local c, keeps = choose(code, interim)
    if not c and added_slot then drop_slot(ent, assignment) end
    if not c then
        if MILITARY_OFFICES[code] then          -- (0.104.168, review) left empty, said
            return {ok = false, rejected = true, nobody_fits = true,
                    error = 'nobody fits to lead a squad (a content, healthy civilian outside the squads, no '
                            .. 'mother of a baby, holding no post): the ' .. code:lower():gsub('_', ' ')
                            .. ' stays vacant'}
        end
        return {ok = false, rejected = true, error = 'no grown citizen to appoint'}
    end
    local u = df.unit.find(c.id)
    local hf = u and df.historical_figure.find(u.hist_figure_id)
    if not hf then
        if added_slot then drop_slot(ent, assignment) end
        return {ok = false, error = 'the chosen dwarf has no historical figure'}
    end
    local name = (txt or tostring)(dfhack.units.getReadableName(u))
    local out = {ok = true, office = code, name = name, unit_id = u.id, skills = c.skills, dry_run = dry_run or nil,
                 slot_added = added_slot or nil, interim = keeps and true or nil, keeps = keeps}
    if dry_run then return out end
    local ok = write_appointment(ent, assignment, a_idx, pos, u)
    if not ok and added_slot then drop_slot(ent, assignment) end
    if not ok then
        return {ok = false, office = code, error = 'DFHack did not see the appointment, so it was undone: '
                .. 'appoint the ' .. code:lower():gsub('_', ' ') .. ' in the nobles screen'}
    end
    -- (0.104.168) the squad the office leads: its leader's seat taken
    if MILITARY_OFFICES[code] and (tonumber(assignment.squad_id) or -1) ~= -1 then
        local oks, seated = pcall(function()
            local sq = df.squad.find(assignment.squad_id)
            return sq and reqscript('ai-military').seat_leader(u, sq) or false
        end)
        out.squad_id, out.seated = assignment.squad_id, (oks and seated) or false
    end
    return out
end

-- (0.104.168) The vacant slot of a military office to fill: the commander's
-- (one), or a captain's that leads a squad (a dead captain's), and only when
-- the fort may fill it (appointable: the commander appoints the captains).
function military_slot(ent, code)
    local held, seen, best = false, false, nil
    for idx, a in ipairs(ent.positions.assignments) do
        local p = position_of(ent, a.position_id)
        if p and p.code == code then
            seen = true
            local squad = (tonumber(a.squad_id) or -1) ~= -1
            if a.histfig ~= -1 then
                held = true
            elseif (code == 'MILITIA_COMMANDER' or squad) and (not best or (squad and not best.squad)) then
                best = {a = a, idx = idx, p = p, squad = squad}
            end
        end
    end
    if not seen then return {ok = false, rejected = true, error = 'the fort has no ' .. code .. ' office yet'} end
    if code == 'MILITIA_COMMANDER' and held then
        return {ok = false, rejected = true, error = code .. ' is already held'}
    end
    if not best then
        return {ok = false, rejected = true, error = code == 'MILITIA_CAPTAIN'
                and "no squad has lost its captain (a vacant captain's slot without a squad is for the next squad)"
                or code .. ' is already held'}
    end
    local can, why = appointable(ent, best.p)
    if not can then
        return {ok = false, rejected = true,
                error = code:lower():gsub('_', ' ') .. " is not the fort's to fill (" .. tostring(why) .. ')'}
    end
    return {ok = true, assignment = best.a, idx = best.idx, pos = best.p}
end

-- Undo an appointment written here.
function undo_appointment(assignment, hf)
    assignment.histfig = -1
    for i = #hf.entity_links - 1, 0, -1 do
        local l = hf.entity_links[i]
        if df.histfig_entity_link_positionst:is_instance(l) and l.assignment_id == assignment.id then
            hf.entity_links:erase(i)
            pcall(function() l:delete() end)
        end
    end
end

-- The two records DF's nobles screen writes, read back through DFHack (and
-- undone if it doesn't see them); then the history event. Returns true/false.
function write_appointment(ent, assignment, a_idx, pos, u)
    local hf = df.historical_figure.find(u.hist_figure_id)
    if not hf then return false end
    assignment.histfig = hf.id
    hf.entity_links:insert('#', {new = df.histfig_entity_link_positionst, entity_id = ent.id,
                                 link_strength = 100, assignment_id = assignment.id,
                                 assignment_vector_idx = a_idx, start_year = df.global.cur_year})
    if not holds(u, pos.code) then
        undo_appointment(assignment, hf)
        return false
    end
    pcall(function() assignment.histfig2 = hf.id end)   -- DF's "last holder"
    pcall(sync_held, ent, true)                          -- (0.101.6) the game's duty lists
    add_event(ent, hf, pos)
    return true
end

-- --- rooms the nobles want ------------------------------------------------------

-- A noble's office may ask for rooms of its own (DF's position raws:
-- required office, bedroom, dining room, tomb). Without one the noble is
-- unhappy and makes demands. The AI gives each such noble a free room of
-- the kind (an office or bedroom of a suites level it built, a tomb), and
-- builds a suites level when there is none free.
ROOM_ZONES = {office = 'Office', bedroom = 'Bedroom', dining = 'DiningHall', tomb = 'Tomb'}
local REQUIRED = {office = 'required_office', bedroom = 'required_bedroom', dining = 'required_dining',
                  tomb = 'required_tomb'}

local function owns(u, zone_type)
    for _, z in ipairs(u.owned_buildings) do
        local ok, t = pcall(function() return df.civzone_type[z.type] end)
        if ok and t == zone_type then return true end
    end
    return false
end

-- (0.100.1, review) a dining hall given to a noble is theirs alone: the
-- fort's shared one is never given (one unowned hall is always kept, and of
-- the others the smallest goes)
local function free_zones(zone_type)
    local list = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone and df.civzone_type[b.type] == zone_type
                and b.assigned_unit_id == -1 then
            table.insert(list, b)
        end
    end
    return list
end

local function area(b)
    local ok, a = pcall(function() return (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1) end)
    return ok and a or math.huge
end

local function free_zone(zone_type)
    local list = free_zones(zone_type)
    if zone_type == 'DiningHall' then
        if #list < 2 then return nil end
        table.sort(list, function(a, b) return area(a) < area(b) end)
    end
    return list[1]
end

-- {{unit_id, name, office, needs = {'office', 'bedroom'...}}, ...} and the
-- free zones of each kind.
function rooms_survey(txt)
    local out, free = {}, {}
    for kind, zt in pairs(ROOM_ZONES) do
        local n = #free_zones(zt)
        if zt == 'DiningHall' then n = math.max(0, n - 1) end     -- the shared hall isn't given
        free[kind] = n
    end
    for _, u in ipairs(report_citizens(true)) do
        local list = dfhack.units.getNoblePositions(u)
        if list then
            local needs, office = {}, nil
            for _, np in ipairs(list) do
                for kind, field in pairs(REQUIRED) do
                    local ok, v = pcall(function() return np.position[field] end)
                    if ok and v and v > 0 and not owns(u, ROOM_ZONES[kind]) then
                        needs[kind] = true
                        office = office or np.position.code
                    end
                end
            end
            local kinds = {}
            for k in pairs(needs) do table.insert(kinds, k) end
            table.sort(kinds)
            if #kinds > 0 then
                table.insert(out, {unit_id = u.id, name = (txt or tostring)(dfhack.units.getReadableName(u)),
                                   office = office, needs = kinds})
            end
        end
    end
    return {nobles = out, free = free}
end

-- Give the noble a free room of the kind.
function give_room(unit_id, kind, dry_run, txt)
    local zt = ROOM_ZONES[kind]
    if not zt then return {ok = false, rejected = true, error = 'unknown room kind: ' .. tostring(kind)} end
    local u = df.unit.find(unit_id)
    if not u then return {ok = false, rejected = true, error = 'no such dwarf'} end
    if owns(u, zt) then return {ok = false, rejected = true, error = 'already has one'} end
    local z = free_zone(zt)
    if not z then return {ok = false, rejected = true, error = 'no free ' .. kind .. ' to give'} end
    local name = (txt or tostring)(dfhack.units.getReadableName(u))
    if dry_run then return {ok = true, dry_run = true, name = name, kind = kind, zone = z.id} end
    if not dfhack.buildings.setOwner(z, u) or not owns(u, zt) then
        return {ok = false, error = 'the game did not give ' .. name .. ' the ' .. kind}
    end
    return {ok = true, name = name, kind = kind, zone = z.id}
end
