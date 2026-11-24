-- ai-military-draft: who may be a soldier (nursing mothers, dwarves near a
-- breakdown, the fort's last farmers and brewers kept out), a squad filled,
-- trimmed and a soldier let go, the squad leader's seat, and a new squad made
-- with a captain's post and a leader (make_squad).
--
-- (r8) A part of ai-military, not a script of its own: ai-military.lua loads
-- it into its own environment, so every name here is
-- reqscript('ai-military').name and a name swapped there reaches this file.

if not MILITARY_PART_LOCALS then qerror('ai-military-draft is a part of ai-military; run ai-military') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-military-draft'] = '0.105.99'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, COMBAT_SKILLS, wants_fight, fight_focus = MILITARY_PART_LOCALS.U, MILITARY_PART_LOCALS.report_citizens, MILITARY_PART_LOCALS.COMBAT_SKILLS, MILITARY_PART_LOCALS.wants_fight, MILITARY_PART_LOCALS.fight_focus   -- (r8) the hub's locals

-- Candidates: adult, sane citizens not in a squad, without a noble office,
-- not hurt badly enough to be in hospital care.
-- Mothers of babies (a baby is carried everywhere, into battle too): never
-- made soldiers. unit id -> true.
function nursing_mothers()
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

-- (0.103.8) A dwarf very unhappy or worse isn't drafted: the stress care
-- took Enxah's miserable lye maker out of his squad, and the next cycle's
-- fill put him straight back in, a dozen times an hour. (0.103.9) Unless soldiering is
-- what the dwarf longs for (the Fight / MartialTraining needs).
-- (0.104.168) `strict` (the fort in crisis): never one very unhappy or
-- worse, whatever they long for (armed mid-spiral in a tantrum spiral)
local function breaking_down(u, strict)
    local ok, cat = pcall(dfhack.units.getStressCategory, u)
    if not (ok and type(cat) == 'number' and cat <= 1) then return false end
    -- (0.105.21) strict == 'keen': a crisis's keen-only fill, where the very
    -- unhappy (1) who long to train may go, the miserable (0) never
    if strict == 'keen' then return cat == 0 or not wants_fight(u) end
    return strict == true or not wants_fight(u)
end

-- (0.104.168) the fill's test, shared with the needs report's count of the
-- keen who can be drafted (`keen_draftable`): adult, in no squad, no nursing
-- mother, not breaking down, no noble post, no hospital care asked
-- (R1 g6) and never a dwarf in a strange mood or gone insane (u.mood set:
-- R-AD, Melbil, Zas and Fikod were put into squads mid-mood by soldier_swap,
-- and all three died)
function draftable(u, mothers, strict)
    -- (0.105.96) never a werebeast-cursed dwarf: the moon cell takes them out
    -- of the squad, and a fill drafted them straight back (B, 23 Nov)
    local okw, cursed = pcall(function() return reqscript('ai-threats').were_cursed(u) end)
    if okw and cursed then return false end
    -- (0.105.97) never a killer the killer rule holds (a cell, or a strong or
    -- certain suspect): B, 23 Nov, soldier_swap's fill drafted the celled
    -- Fath Shemnish (2 kills) into squad 182; the cell takes them out
    local okk, held = pcall(function() return reqscript('ai-killers').is_held(u) end)
    if okk and held then return false end
    local ok, yes = pcall(function()
        local m = tonumber(u.mood)
        if m ~= nil and m >= 0 then return false end
        return dfhack.units.isAdult(u) and u.military.squad_id == -1 and not mothers[u.id]
            and not breaking_down(u, strict)
            and #(dfhack.units.getNoblePositions(u) or {}) == 0
            and not (u.health and u.health.flags.needs_healthcare)
    end)
    return ok and yes == true
end

-- (0.105.99) Never drafted into the fort's squads (the training squad apart:
-- no uniform, no weapons, it is where the stress-prone who long to train
-- go): a dwarf in a breakdown now (soldier_mood Tantrum, Enraged, Depressed
-- or Oblivious), the miserable whatever they long for, and one with a
-- tantrum in the last 28 days or 3+ in a year (ai-tantrums' ledger, the bar
-- a post has). E, 23 Nov 00:07:57: the defence floor's fill drafted Medtob
-- Sefollòr (miserable, stress 83,000, a tantrum 78 days before, slipping
-- into depression that very report) into squad 191; at 00:15:13 he threw a
-- tantrum among his squad and struck down Goden Besmardodók, and the calm
-- burrow never takes a soldier. The reason, or nil.
DRAFT_BREAKDOWN = {Tantrum = true, Enraged = true, Depressed = true, Oblivious = true}
local LEDGER_MEMO = {at = nil, d = nil}
function draft_bar(u)
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    if okm and DRAFT_BREAKDOWN[m] then return 'in a breakdown (' .. tostring(m) .. ')' end
    local okc, cat = pcall(dfhack.units.getStressCategory, u)
    if okc and cat == 0 then return 'miserable' end
    local okt, why = pcall(function()
        local T = reqscript('ai-tantrums')
        local now = U.abs_tick()
        if LEDGER_MEMO.at ~= now or LEDGER_MEMO.d == nil then LEDGER_MEMO.at, LEDGER_MEMO.d = now, T.load() end
        local d = LEDGER_MEMO.d
        if T.count(d, u.id, T.STAFF_DAYS, now) > 0 then return 'a tantrum in the last ' .. T.STAFF_DAYS .. ' days' end
        if T.count(d, u.id, T.YEAR // T.DAY, now) >= T.CHRONIC then return T.CHRONIC .. '+ tantrums this year' end
        return nil
    end)
    return okt and why or nil
end

local function candidates(strict)
    local out = {}
    local mothers = nursing_mothers()
    for _, u in ipairs(report_citizens(true)) do
        if draftable(u, mothers, strict) then
            local combat, best, rskill = 0, 0, 0
            local soul = u.status.current_soul
            if soul then
                for _, sk in ipairs(soul.skills) do
                    local name = df.job_skill[sk.id] or ''
                    local is_combat = false
                    for _, c in ipairs(COMBAT_SKILLS) do
                        if name == c then is_combat = true break end
                    end
                    if is_combat then combat = combat + sk.rating
                    elseif sk.rating > best then best = sk.rating end
                    -- (r2h4) the crossbow squad's own skills
                    if (name == 'CROSSBOW' or name == 'BOW') and sk.rating > rskill then rskill = sk.rating end
                end
            end
            table.insert(out, {id = u.id, combat = combat, best_craft = best, unit = u, wants_fight = wants_fight(u),
                               fight_focus = fight_focus(u), rskill = rskill})
        end
    end
    return out
end

-- The leader's seat (place 0): DFHack's addToSquad won't fill it, so it's
-- written as addToSquad writes the others (the place's occupant, the unit's
-- squad and place, the figure's squad link, an equipment update).
function seat_leader(u, sq)
    -- (0.105.96, verifier) a werebeast-cursed leader is never seated again (moon_cell took them out)
    local okw, cursed = pcall(function() return reqscript('ai-threats').were_cursed(u) end)
    if okw and cursed then return false end
    -- (0.105.97) nor a held killer (B, 23 Nov: Fath Shemnish made captain of squad 214)
    local okk, held = pcall(function() return reqscript('ai-killers').is_held(u) end)
    if okk and held then return false end
    local hf = df.historical_figure.find(u.hist_figure_id)
    if not hf or u.military.squad_id ~= -1 or #sq.positions == 0 or sq.positions[0].occupant ~= -1 then
        return false
    end
    sq.positions[0].occupant = hf.id
    u.military.squad_id = sq.id
    u.military.squad_position = 0
    hf.entity_links:insert('#', {new = df.histfig_entity_link_squadst, squad_id = sq.id, squad_position = 0,
                                 entity_id = sq.entity_id, start_year = df.global.cur_year, link_strength = 100})
    for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'ammo', 'pants', 'backpack',
                        'quiver', 'flask'}) do
        pcall(function()
            sq.ammo.update[f] = true
            df.global.plotinfo.equipment.update[f] = true
        end)
    end
    return true
end

-- The squad's leader post's holder, seated if the seat is empty (squads made
-- by bridge 0.42 left it empty, so no one else could be added).
local function seat_holder(sq)
    if #sq.positions == 0 or sq.positions[0].occupant ~= -1 then return false end
    local fort = U.fort_entity()
    for _, a in ipairs(fort and fort.positions.assignments or {}) do
        if a.id == sq.leader_assignment and a.histfig ~= -1 then
            for _, u in ipairs(report_citizens(true)) do
                if u.hist_figure_id == a.histfig then return seat_leader(u, sq) end
            end
        end
    end
    return false
end

-- (0.105.54) Labours the fort needs to live: the last adult outside the
-- squads who does one is never drafted. {n = {labour = holders}, of = {unit
-- id = {labours}}}.
KEEP_LABORS = {'PLANT', 'BREWER'}
function last_hands()
    local out = {n = {}, of = {}}
    for _, u in ipairs(report_citizens(true)) do
        if dfhack.units.isAdult(u) and u.military.squad_id == -1 then
            for _, tok in ipairs(KEEP_LABORS) do
                local l = df.unit_labor[tok]
                if l and u.status.labors[l] then
                    out.n[tok] = (out.n[tok] or 0) + 1
                    out.of[u.id] = out.of[u.id] or {}
                    table.insert(out.of[u.id], tok)
                end
            end
        end
    end
    return out
end

-- Fill up to `count` open positions of a squad (never the captain's seat).
-- (0.104.138) `avoid`: unit ids not to draft (those the AI sent home lately)
-- (0.104.168) `strict`: the fort in crisis (never the very unhappy);
-- `keen_only`: only those who badly want to fight or train (the places the
-- keen lift added are theirs alone: none of them filled by combat skill)
function fill(squad_id, count, txt, avoid, strict, keen_only)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local seated = seat_holder(sq)
    -- (0.104.5) a squad whose leader's office stands empty (Enxah: no militia
    -- commander or captain, both squads leaderless): the best fighter outside
    -- the squads is appointed to it and takes the seat, as make_squad does
    local appointed_leader
    if not seated and #sq.positions > 0 and sq.positions[0].occupant == -1 then
        pcall(function()
            local fort = U.fort_entity()
            for idx, a in ipairs(fort and fort.positions.assignments or {}) do
                if a.id == sq.leader_assignment and a.histfig == -1 then
                    local pos
                    for _, p in ipairs(fort.positions.own) do if p.id == a.position_id then pos = p end end
                    -- (0.105.99, verifier) the leader's seat kept from the breaking-down
                    -- and the tantrum-throwers too (draft_bar), the training squad's as well: a seat is an office
                    local pool = {}
                    if pos then
                        for _, c in ipairs(candidates()) do
                            if not draft_bar(c.unit) then table.insert(pool, c) end
                        end
                    end
                    local pick = pos and pick_soldiers(pool, 1)[1]
                    if pick and reqscript('ai-nobles').write_appointment(fort, a, idx, pos, pick.unit)
                            and seat_leader(pick.unit, sq) then
                        seated = true
                        appointed_leader = txt and txt(dfhack.units.getReadableName(pick.unit)) or tostring(pick.id)
                    end
                end
            end
        end)
    end
    -- (0.104.5) the open places by number: asked for "any place" (-1),
    -- DFHack takes the first free one, which is the leader's seat while it's
    -- empty, and refuses it (Enxah: every draft "no suitable dwarves" with
    -- both squads' leader seats empty, the soldiers' training need unmet)
    local places = {}
    for i, pos in ipairs(sq.positions) do
        if i > 0 and i < 10 and pos.occupant == -1 then table.insert(places, i) end
    end
    local open = #places
    count = math.min(count, open)
    if count < 1 then return {ok = false, rejected = true, error = 'the squad has no open places'} end
    -- (0.104.168) strict in a crisis; (0.105.21) eased for the keen: in C
    -- (3 Nov) every dwarf who badly wanted to train was unhappy for want of
    -- it, so the crisis's keen-only fill found 0 candidates 6 times while 33
    -- were distracted by MartialTraining (the squad is what meets that;
    -- stress_care never sends such a dwarf home). The miserable still never.
    local okc, cands = pcall(candidates, strict and (keen_only and 'keen' or true) or false)
    if not okc then return {ok = false, error = 'could not list dwarves: ' .. tostring(cands)} end
    if keen_only then
        local only = {}
        for _, c in ipairs(cands) do
            if c.fight_focus ~= nil and c.fight_focus <= KEEN_FOCUS then table.insert(only, c) end
        end
        cands = only
    end
    -- (0.105.99) the breaking-down and the tantrum-throwers kept out (draft_bar),
    -- but for the training squad
    local barred = 0
    local okts, TSQ = pcall(reqscript, 'ai-training-squad')
    local okm, tmarks = false, nil
    if okts and type(TSQ) == 'table' and type(TSQ.marks) == 'function' then okm, tmarks = pcall(TSQ.marks) end
    local training = okm and type(tmarks) == 'table' and tmarks[tostring(squad_id)] or false
    if not training then
        local kept_c = {}
        for _, c in ipairs(cands) do
            if draft_bar(c.unit) then barred = barred + 1 else table.insert(kept_c, c) end
        end
        cands = kept_c
    end
    local added = {}
    local tried, k = 0, 1
    local okh, hands = pcall(last_hands)          -- (0.105.54) never the last farmer or brewer
    if not okh then hands = nil end
    local kept = 0
    -- (r2h4) a crossbow squad's places go to those who shoot best
    local okr, shoots = pcall(function() return squad_is_ranged(sq, ai_uniforms()[tostring(squad_id)]) end)
    for _, c in ipairs(pick_soldiers(cands, count, avoid, okr and shoots or nil)) do
        tried = tried + 1
        local place = places[k]
        local mine = hands and hands.of[c.id]
        local last = false
        for _, tok in ipairs(mine or {}) do
            if (hands.n[tok] or 0) <= 1 then last = true end
        end
        if last then
            kept = kept + 1
        elseif place and dfhack.military.addToSquad(c.id, squad_id, place) then
            table.insert(added, {unit_id = c.id, name = txt(dfhack.units.getReadableName(c.unit))})
            k = k + 1
            for _, tok in ipairs(mine or {}) do hands.n[tok] = (hands.n[tok] or 0) - 1 end
        end
    end
    if #added == 0 then
        return seated and {ok = true, added = {}, leader_seated = true, leader_appointed = appointed_leader}
            or {ok = false, error = ('no suitable dwarves could be added (%d candidate(s), %d tried, %d open place(s)%s%s%s)'):format(
                #cands, tried, open, sq.positions[0] and sq.positions[0].occupant == -1 and ', the leader\'s seat empty' or '',
                kept > 0 and (', %d kept as the last farmer or brewer'):format(kept) or '',
                barred > 0 and (', %d kept out: breaking down or a recent tantrum'):format(barred) or '')}
    end
    return {ok = true, added = added, leader_seated = seated or nil, leader_appointed = appointed_leader,
            kept_last_hands = kept > 0 and kept or nil, kept_out = barred > 0 and barred or nil}
end

-- (0.105.97) How badly a soldier is doing in the squad: the needs a soldier's
-- days leave unmet (friends, a drink, prayer) badly missed, one each, and
-- two more when unhappy or worse (stress category 2 and below). B, 23 Nov:
-- the defence floor kept 35-44 soldiers for years, almost all of them
-- badly missing a drink; those go home first when the floor falls.
TRIM_NEEDS = {BeWithFriends = true, DrinkAlcohol = true, PrayOrMeditate = true}
function trim_misery(u)
    local n = 0
    pcall(function()
        for _, nd in ipairs(u.status.current_soul.personality.needs) do
            if TRIM_NEEDS[df.need_type[nd.id]] and nd.focus_level <= KEEN_FOCUS then n = n + 1 end
        end
    end)
    local ok, cat = pcall(dfhack.units.getStressCategory, u)
    if ok and type(cat) == 'number' and cat <= 2 then n = n + 2 end
    return n
end

-- (0.102) An army bigger than the fort wants (Militarism lowered, or the
-- fort shrank) is trimmed: up to `count` soldiers back to work, those least
-- suited first (fewest combat skills, best at a trade), never a squad's
-- leader, a dwarf who longs to fight, or a squad out on orders.
-- (0.105.97) the unhappiest and those badly missing friends, a drink or
-- prayer go first (trim_misery), then the least suited as before.
function trim(count, dry_run, txt)
    if not (dfhack.military and type(dfhack.military.removeFromSquad) == 'function') then
        return {ok = false, rejected = true, error = 'this DFHack cannot take a dwarf out of a squad'}
    end
    local fort = U.fort_entity()
    if not fort then return {ok = false, error = 'no fort government (entity) found'} end
    local list = {}
    local okt, TS = pcall(reqscript, 'ai-training-squad')     -- (0.105.47) never the training squad's
    local tmarks = okt and TS.marks() or {}
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq and #sq.orders == 0 and not tmarks[tostring(sid)] then
            for i, pos in ipairs(sq.positions) do
                if i > 0 and pos.occupant ~= -1 then
                    local hf = df.historical_figure.find(pos.occupant)
                    local u = hf and df.unit.find(hf.unit_id)
                    if u and dfhack.units.isCitizen(u) and not wants_fight(u) then
                        local combat, best = 0, 0
                        for _, sk in ipairs(u.status.current_soul and u.status.current_soul.skills or {}) do
                            local name, is_combat = df.job_skill[sk.id] or '', false
                            for _, c in ipairs(COMBAT_SKILLS) do if name == c then is_combat = true break end end
                            if is_combat then combat = combat + sk.rating
                            elseif sk.rating > best then best = sk.rating end
                        end
                        table.insert(list, {u = u, squad = sid, score = combat * 3 - best, misery = trim_misery(u)})
                    end
                end
            end
        end
    end
    table.sort(list, function(a, b)
        if a.misery ~= b.misery then return a.misery > b.misery end   -- (0.105.97) the unhappiest first
        if a.score ~= b.score then return a.score < b.score end
        return a.u.id < b.u.id
    end)
    local out = {}
    for i = 1, math.min(count, #list) do
        local c = list[i]
        local name = (txt or tostring)(dfhack.units.getReadableName(c.u))
        if dry_run or dfhack.military.removeFromSquad(c.u.id) then
            table.insert(out, {unit_id = c.u.id, squad_id = c.squad, name = name, misery = c.misery > 0 and c.misery or nil})
        end
    end
    if #out == 0 then return {ok = false, rejected = true, error = 'no soldier who could go back to work'} end
    return {ok = true, removed = out, dry_run = dry_run or nil}
end

-- (0.102.4) One stressed soldier back to civilian life (DF wiki: the
-- stress-prone are "not suitable for the military"): never a squad's
-- leader, nor while the squad is out on orders.
-- `mother`: (0.104.159) a soldier with a baby goes home whatever she longs
-- for (the baby is carried into every fight); only a squad leader stays.
-- `tantrum`: (0.105.99) a soldier in a tantrum now goes home whatever he
-- longs for (the calm burrow never takes a soldier, and his squad stands
-- round him armed): E, 24 Nov 00:15, Medtob Sefollòr, a tantrum among squad
-- 191, struck down Goden; only a squad leader stays.
function release(unit_id, dry_run, txt, mother, tantrum)
    if not (dfhack.military and type(dfhack.military.removeFromSquad) == 'function') then
        return {ok = false, rejected = true, error = 'this DFHack cannot take a dwarf out of a squad'}
    end
    local u = df.unit.find(unit_id)
    if not u or not dfhack.units.isCitizen(u) then return {ok = false, rejected = true, error = 'no such citizen'} end
    if u.military.squad_id == -1 then return {ok = false, rejected = true, error = 'not in a squad'} end
    if u.military.squad_position == 0 then return {ok = false, rejected = true, error = 'a squad leader stays'} end
    -- (0.103.10) one who longs to fight or train stays: the squad is what
    -- meets that (and the fill would draft them straight back)
    if mother and not nursing_mothers()[u.id] then return {ok = false, rejected = true, error = 'no baby of hers'} end
    if tantrum then
        local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
        if not (okm and (m == 'Tantrum' or m == 'Enraged')) then
            return {ok = false, rejected = true, error = 'not in a tantrum now'}
        end
    end
    if wants_fight(u) and not mother and not tantrum then return {ok = false, rejected = true, error = 'longs to fight or train: the squad is what meets that'} end
    local sq = df.squad.find(u.military.squad_id)
    if sq and #sq.orders > 0 then return {ok = false, rejected = true, error = 'the squad is out on orders'} end
    local name = (txt or tostring)(dfhack.units.getReadableName(u))
    if dry_run then return {ok = true, dry_run = true, name = name} end
    if not dfhack.military.removeFromSquad(u.id) then return {ok = false, error = 'the game kept ' .. name .. ' in the squad'} end
    return {ok = true, name = name, squad_id = sq and sq.id or nil}
end

-- A new squad (bridge 0.41): DFHack's makeSquad on a military office that
-- leads no squad yet (the militia commander first, then a captain's post),
-- with a leader appointed to that office if it's vacant (the best fighter
-- outside the squads, written as lua/ai-nobles.lua writes appointments),
-- the leader put in the first place, and the uniform copied from a squad
-- that has one. Without a squad to copy from, the squad is made and Needs
-- you asks for its uniform.
LEAD_OFFICES = {MILITIA_COMMANDER = 1, MILITIA_CAPTAIN = 2}

-- squads whose uniform the AI set: squad id (text) -> template name (+ " |weapon:<id>")
UNIFORMS_KEY = 'ai-overseer/uniforms'

function ai_uniforms()
    return U.site_get(UNIFORMS_KEY, {})
end

local function copy_uniform(from_sq, to_sq)
    local src = from_sq.positions[0]
    if not src then return false end
    local copied = 0
    for i = 0, #to_sq.positions - 1 do
        local dst = to_sq.positions[i]
        for cat = 0, df.uniform_category._last_item do          -- (_first_item is NONE, -1)
            for _, spec in ipairs(src.equipment.uniform[cat]) do
                local new = df.squad_uniform_spec:new()
                new:assign(spec)
                new.item = -1                                -- a kind of item, not one particular item
                pcall(function() new.assigned:resize(0) end) -- (not the items given to the source dwarf)
                dst.equipment.uniform[cat]:insert('#', new)
                copied = copied + 1
            end
        end
        pcall(function() dst.equipment.flags:assign(src.equipment.flags) end)
    end
    return copied > 0
end

-- a squad to copy a uniform from: a melee one first (0.82: a new squad that
-- copied the crossbow squad's uniform made a second crossbow squad)
local function squad_with_uniform(fort, except)
    local mine, ranged = ai_uniforms(), nil
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq and sid ~= except and #sq.positions > 0 and uniform_set(sq.positions[0]) then
            if not tostring(mine[tostring(sid)] or ''):lower():find('crossbow', 1, true) then return sq end
            ranged = ranged or sq
        end
    end
    return ranged
end

-- A captain's post (bridge 0.81). DF's militia captain is [NUMBER:AS_NEEDED]:
-- the game adds a vacant captain's slot at the end of the nobles list each
-- time one is filled, so a fort can raise as many squads as it likes. Squads
-- the AI made never filled a captain's slot through the game's own screens,
-- so no vacant one appeared and make_squad found "no military office is free"
-- (Oct 23, region2: 1 squad for 98 dwarves, 78 distracted by MartialTraining
-- and Fight). The AI now adds the slot itself, as the game would: a new
-- entity_position_assignment for the captain's position, vacant, leading no
-- squad, with the next assignment id; it is taken away again if the squad
-- can't be made. Only for a position the raws mark AS_NEEDED (number < 0) or
-- with fewer slots than its number, only while a militia commander holds his
-- office (captains are his to appoint), and at most MAX_SQUADS squads.
MAX_SQUADS = 12

local function find_position(fort, code)
    for idx, p in ipairs(fort.positions.own) do
        if p.code == code then return p, idx end
    end
end

local function held(fort, code)
    local p = find_position(fort, code)
    if not p then return false end
    for _, a in ipairs(fort.positions.assignments) do
        if a.position_id == p.id and a.histfig ~= -1 then return true end
    end
    return false
end

-- (pos, pos_idx) when a new captain's slot may be added, else nil and why
function captain_post_room(fort)
    local p, pidx = find_position(fort, 'MILITIA_CAPTAIN')
    if not p or (p.squad_size or 0) < 1 then return nil, 'this civilisation has no militia captains' end
    if #fort.squads >= MAX_SQUADS then return nil, 'the fort has ' .. MAX_SQUADS .. ' squads already' end
    if not held(fort, 'MILITIA_COMMANDER') then return nil, 'no militia commander to appoint captains' end
    local n = 0
    for _, a in ipairs(fort.positions.assignments) do
        if a.position_id == p.id then n = n + 1 end
    end
    local number = tonumber(p.number) or 1
    if number >= 0 and n >= number then return nil, 'all ' .. number .. ' captains\' posts are in use' end
    return p, pidx
end

-- a new vacant slot for position p (index pidx in positions.own); returns it and its index
function add_post(fort, p, pidx)
    local a = df.entity_position_assignment:new()
    a.id = fort.positions.next_assignment_id
    a.histfig = -1
    pcall(function() a.histfig2 = -1 end)
    a.position_id = p.id
    pcall(function() a.position_vector_idx = pidx end)
    a.squad_id = -1
    -- (r15) the slot's army link at -1 as DF's own (a new record holds 0: DF
    -- reads it as an army assignment; ai-nobles clear_slot_links)
    pcall(function() reqscript('ai-nobles').clear_slot_links(a) end)
    pcall(function() if a.assigned_army_controller_id ~= -1 then a.assigned_army_controller_id = -1 end end)
    -- the flags of a slot of the same position (or of the commander's): 'active'
    local cmd = find_position(fort, 'MILITIA_COMMANDER')
    local like
    for _, o in ipairs(fort.positions.assignments) do
        if o.position_id == p.id then like = o; break end
        if cmd and o.position_id == cmd.id and not like then like = o end
    end
    if like then pcall(function() a.flags.active = like.flags.active end) end
    fort.positions.next_assignment_id = a.id + 1
    fort.positions.assignments:insert('#', a)
    pcall(function()
        for r, on in pairs(p.responsibilities) do
            -- (0.104.138) the per-duty lists hang on the entity itself (as
            -- ai-nobles reads them); `fort.positions.` failed silently
            if on then fort.assignments_by_type[r]:insert('#', a) end
        end
    end)
    return a, #fort.positions.assignments - 1
end

-- take back a slot add_post made (the squad couldn't be made)
function drop_post(fort, a)
    local function erase(v)
        for i = #v - 1, 0, -1 do
            if v[i] == a or (v[i] and v[i].id == a.id) then v:erase(i) end
        end
    end
    erase(fort.positions.assignments)
    pcall(function()
        for _, lst in ipairs(fort.assignments_by_type) do erase(lst) end
    end)
    pcall(function() a:delete() end)
end

-- (0.105.47) `opts.training`: the training squad (lua/ai-training-squad.lua):
-- only a vacant captain's office (the militia commander stays for the
-- fort's own guard), its leader a volunteer who badly wants to fight or
-- train, and no uniform copied (it trains as it is, never sent to fight)
function make_squad(dry_run, txt, opts)
    local training = type(opts) == 'table' and opts.training == true
    local fort = U.fort_entity()
    if not fort then return {ok = false, error = 'no fort government (entity) found'} end
    local best, best_rank, best_idx, best_pos
    for idx, a in ipairs(fort.positions.assignments) do
        if a.squad_id == -1 and not (training and a.histfig ~= -1) then
            for _, p in ipairs(fort.positions.own) do
                local rank = LEAD_OFFICES[p.code]
                if training and rank == 1 then rank = nil end
                if p.id == a.position_id and rank and p.squad_size > 0 and (not best_rank or rank < best_rank) then
                    best, best_rank, best_idx, best_pos = a, rank, idx, p
                end
            end
        end
    end
    local new_post, why
    if not best then
        local p, pidx_or_why = captain_post_room(fort)
        if not p then why = pidx_or_why
        elseif dry_run then
            new_post = true
            best, best_idx, best_pos = {id = -1, histfig = -1, squad_id = -1, position_id = p.id}, -1, p
        else
            best, best_idx = add_post(fort, p, pidx_or_why)
            best_pos, new_post = p, best
        end
    end
    if not best then
        return {ok = false, rejected = true, error = 'no military office is free to lead a new squad ('
                .. (why or 'DF adds captains\' posts as the fort grows') .. ')'}
    end
    local function fail(r)
        if new_post and new_post ~= true then drop_post(fort, new_post) end
        return r
    end
    -- the leader: the office's holder, or the best fighter outside the squads
    local leader, appointed
    if best.histfig ~= -1 then
        for _, u in ipairs(report_citizens(true)) do
            if u.hist_figure_id == best.histfig then leader = u end
        end
    else
        local okc, cands = pcall(candidates)
        if okc and training then           -- (0.105.47) a volunteer leads it
            local keen = {}
            for _, c in ipairs(cands) do
                if c.fight_focus ~= nil and c.fight_focus <= KEEN_FOCUS then table.insert(keen, c) end
            end
            cands = keen
        end
        local pick = okc and pick_soldiers(cands, 1)[1]
        leader = pick and pick.unit
        appointed = true
    end
    if not leader then return fail({ok = false, rejected = true, error = 'no dwarf fit to lead a squad'}) end
    local name = txt and txt(dfhack.units.getReadableName(leader)) or tostring(leader.id)
    local office = best_pos.code:lower():gsub('_', ' ')
    if dry_run then
        return {ok = true, dry_run = true, office = office, leader = name, appoint = appointed or nil,
                new_post = new_post and true or nil}
    end
    local N = reqscript('ai-nobles')
    if appointed and not N.write_appointment(fort, best, best_idx, best_pos, leader) then
        return fail({ok = false, error = 'DFHack did not see ' .. name .. ' appointed ' .. office .. ', so it was undone'})
    end
    local sq = dfhack.military.makeSquad(best.id)
    if not sq then
        if appointed then
            local hf = df.historical_figure.find(leader.hist_figure_id)
            if hf then N.undo_appointment(best, hf) end
        end
        return fail({ok = false, error = 'DFHack could not make a squad for the ' .. office})
    end
    local seated = seat_leader(leader, sq)
    local from = not training and squad_with_uniform(fort, sq.id) or nil
    local oku, uniform = true, false
    if from then oku, uniform = pcall(copy_uniform, from, sq) end
    uniform = oku and uniform or false
    if uniform then
        -- a copy of the AI's uniform is the AI's too (it may change it later)
        local mine = ai_uniforms()
        if mine[tostring(from.id)] then
            mine[tostring(sq.id)] = mine[tostring(from.id)]
            U.site_put(UNIFORMS_KEY, mine)
        end
    end
    return {ok = true, squad_id = sq.id, office = office, leader = name, appointed = appointed or nil, seated = seated,
            new_post = new_post and true or nil,
            uniform = uniform, uniform_from = from and txt and txt(dfhack.military.getSquadName(from.id)) or nil}
end
