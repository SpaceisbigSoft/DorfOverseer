-- The AI's hands on the military: reading the fort's squads, filling them
-- with suitable dwarves, setting their schedule, sending them at threats,
-- and pulling the gate lever. Squads themselves are created by the player
-- in the military screen (DFHack can't appoint a squad's captain).
--
-- Everything here can be undone: soldiers can be removed again, orders the
-- AI gives are marked as its own and only those are ever cleared.
--@module = true

AI_ORDER_TITLE = 'AI overseer'
GATE_NAME = 'ai gate'          -- a lever named like this (any case) is the gate

local COMBAT_SKILLS = {'AXE', 'SWORD', 'MACE', 'HAMMER', 'SPEAR', 'DAGGER', 'CROSSBOW', 'BOW',
                       'MELEE_COMBAT', 'RANGED_COMBAT', 'WRESTLING', 'DODGING', 'SHIELD',
                       'ARMOR', 'FIGHTER'}

-- Pure: pick the n best candidates. Each: {id, combat = skill levels summed,
-- best_craft = highest non-combat skill level}. Fighters first; among equals,
-- dwarves whose best trade skill is lowest (keep the legendary crafters home).
FIGHT_BONUS = 30
FIGHT_NEEDS = {Fight = true, MartialTraining = true}

local function wants_fight(u)
    local ok, yes = pcall(function()
        for _, nd in ipairs(u.status.current_soul.personality.needs) do
            if FIGHT_NEEDS[df.need_type[nd.id]] and nd.focus_level <= -1000 then return true end
        end
        return false
    end)
    return ok and yes
end

function pick_soldiers(cands, n)
    local list = {}
    for _, c in ipairs(cands) do table.insert(list, c) end
    table.sort(list, function(a, b)
        -- dwarves who long to fight or train (the Fight / MartialTraining
        -- needs) come first: soldiering meets those needs. (0.104.64) always
        -- first, before any veteran: a soldier the AI let go to meet his other
        -- needs was drafted straight back over the keen
        if (a.wants_fight and true or false) ~= (b.wants_fight and true or false) then return a.wants_fight and true or false end
        local sa = (a.combat or 0) * 3 - (a.best_craft or 0) + (a.wants_fight and FIGHT_BONUS or 0)
        local sb = (b.combat or 0) * 3 - (b.best_craft or 0) + (b.wants_fight and FIGHT_BONUS or 0)
        if sa ~= sb then return sa > sb end
        return a.id < b.id
    end)
    local out = {}
    for i = 1, math.min(n, #list) do table.insert(out, list[i]) end
    return out
end

local function fort_entity()
    return df.historical_entity.find(df.global.plotinfo.group_id)
end

local function routine_names()
    local out = {}
    for i, r in ipairs(df.global.plotinfo.alerts.routines) do out[i + 1] = r.name end
    return out
end

GUARD_BURROW_NAME = 'AI gate guard'      -- (0.104.83) the burrow the squads hold at the gate

local function guard_burrow_id()
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if b.name == GUARD_BURROW_NAME then return b.id end
    end
    return nil
end

local function is_ai_order(o)
    local ok, title = pcall(function() return o.title end)
    if ok and title == AI_ORDER_TITLE then return true end
    -- (0.104.83) a defend order has no title: the AI's names only the gate guard burrow
    local okd, mine = pcall(function()
        if not df.squad_order_defend_burrowsst:is_instance(o) then return false end
        local gid = guard_burrow_id()
        return gid ~= nil and #o.burrows == 1 and o.burrows[0] == gid
    end)
    return okd and mine == true
end

function fort_squad(squad_id)
    local fort = fort_entity()
    if not fort then return nil end
    for _, sid in ipairs(fort.squads) do
        if sid == squad_id then return df.squad.find(sid) end
    end
    return nil
end

function gate_levers()
    local out = {}
    for _, b in ipairs(df.global.world.buildings.other.TRAP) do
        if b.trap_type == df.trap_type.Lever and tostring(b.name or ''):lower() == GATE_NAME then
            table.insert(out, {id = b.id, state = b.state, linked = #b.linked_mechanisms,
                               pending = #b.jobs > 0, x = b.centerx, y = b.centery, z = b.z})
        end
    end
    return out
end

-- (0.104.118) A squad's fighting strength, for fight or hide: each soldier
-- counts 1 + (best weapon skill)/3, half again in body armour, half when
-- wounded. {power, armored, skill (average)}.
local FIGHT_SKILLS = {'AXE', 'SWORD', 'MACE', 'HAMMER', 'SPEAR', 'PIKE', 'WHIP', 'DAGGER', 'CROSSBOW', 'BOW',
                      'BLOWGUN', 'WRESTLING'}
-- the "worn" inventory mode's number (its enum moved between DFHack versions)
WORN_MODE = (function()
    for _, get in ipairs({function() return df.inv_item_role_type.Worn end,
                          function() return df.unit_inventory_item.T_mode.Worn end}) do
        local ok, v = pcall(get)
        if ok and v ~= nil then return v end
    end
    return 2
end)()

function squad_power(sq)
    local power, armored, skill_sum, n = 0, 0, 0, 0
    for _, pos in ipairs(sq.positions) do
        local hf = pos.occupant ~= -1 and df.historical_figure.find(pos.occupant)
        local u = hf and hf.unit_id ~= -1 and df.unit.find(hf.unit_id)
        if u and not dfhack.units.isDead(u) then
            local best = 0
            for _, k in ipairs(FIGHT_SKILLS) do
                local ok, v = pcall(dfhack.units.getNominalSkill, u, df.job_skill[k], true)
                if ok and v and v > best then best = v end
            end
            local arm = false
            pcall(function()
                for _, inv in ipairs(u.inventory) do
                    if inv.mode == WORN_MODE and inv.item:getType() == df.item_type.ARMOR then arm = true end
                end
            end)
            local okw, wounded = pcall(function() return #u.body.wounds > 0 end)
            local p = (1 + math.min(best, 20) / 3) * (arm and 1.5 or 1) * ((okw and wounded) and 0.5 or 1)
            power, n, skill_sum = power + p, n + 1, skill_sum + best
            if arm then armored = armored + 1 end
        end
    end
    return {power = math.floor(power * 10 + 0.5) / 10, armored = armored,
            skill = n > 0 and math.floor(skill_sum / n * 10 + 0.5) / 10 or 0}
end

function report(txt)
    local routines = routine_names()
    local out = {squads = {}, soldiers = 0, routines = routines, gates = {}}
    local fort = fort_entity()
    if fort then
        for _, sid in ipairs(fort.squads) do
            local sq = df.squad.find(sid)
            if sq then
                local members = 0
                for _, pos in ipairs(sq.positions) do
                    if pos.occupant ~= -1 then members = members + 1 end
                end
                local ai_orders, guarding = 0, false
                for _, o in ipairs(sq.orders) do
                    if is_ai_order(o) then
                        ai_orders = ai_orders + 1
                        -- (0.104.83) holding the gate (a defend order) rather than out to kill
                        local okg, g = pcall(function() return df.squad_order_defend_burrowsst:is_instance(o) end)
                        if okg and g then guarding = true end
                    end
                end
                local ok, idx = pcall(function() return sq.cur_routine_idx end)
                table.insert(out.squads, {
                    id = sid, name = txt(dfhack.military.getSquadName(sid)),
                    members = members, size = #sq.positions,
                    leader = #sq.positions > 0 and sq.positions[0].occupant ~= -1,
                    routine = ok and routines[idx + 1] or nil,
                    orders = #sq.orders, ai_orders = ai_orders, guarding = guarding or nil,
                    uniform = #sq.positions > 0 and uniform_set(sq.positions[0]) or false,
                    ai_uniform = ai_uniform_names(txt)[tostring(sid)],
                    power = (function() local okp, p = pcall(squad_power, sq) return okp and p or nil end)(),
                })
                out.soldiers = out.soldiers + members
            end
        end
    end
    -- the fort's uniform templates (for a later squad uniform without one to copy)
    pcall(function()
        out.uniform_templates = {}
        for _, uf in ipairs(fort.uniforms) do table.insert(out.uniform_templates, txt(uf.name)) end
    end)
    local ok, gates = pcall(gate_levers)
    out.gates = ok and gates or {}
    local okg, gear = pcall(gear_report)
    out.gear = okg and gear or {error = tostring(gear):sub(1, 200)}
    local okb, bar = pcall(barracks_report)
    out.barracks = okb and bar or {}
    local okr, rng = pcall(ranges_report)
    out.ranges = okr and rng or {}
    return out
end

-- Candidates: adult, sane citizens not in a squad, without a noble office,
-- not hurt badly enough to be in hospital care.
-- Mothers of babies (a baby is carried everywhere, into battle too): never
-- made soldiers. unit id -> true.
function nursing_mothers()
    local out = {}
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
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
local function breaking_down(u)
    local ok, cat = pcall(dfhack.units.getStressCategory, u)
    return ok and type(cat) == 'number' and cat <= 1 and not wants_fight(u)
end

local function candidates()
    local out = {}
    local mothers = nursing_mothers()
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if dfhack.units.isAdult(u) and u.military.squad_id == -1 and not mothers[u.id]
                and not breaking_down(u)
                and #(dfhack.units.getNoblePositions(u) or {}) == 0
                and not (u.health and u.health.flags.needs_healthcare) then
            local combat, best = 0, 0
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
                end
            end
            table.insert(out, {id = u.id, combat = combat, best_craft = best, unit = u, wants_fight = wants_fight(u)})
        end
    end
    return out
end

-- The leader's seat (place 0): DFHack's addToSquad won't fill it, so it's
-- written as addToSquad writes the others (the place's occupant, the unit's
-- squad and place, the figure's squad link, an equipment update).
function seat_leader(u, sq)
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
    local fort = fort_entity()
    for _, a in ipairs(fort and fort.positions.assignments or {}) do
        if a.id == sq.leader_assignment and a.histfig ~= -1 then
            for _, u in ipairs(dfhack.units.getCitizens(true)) do
                if u.hist_figure_id == a.histfig then return seat_leader(u, sq) end
            end
        end
    end
    return false
end

-- Fill up to `count` open positions of a squad (never the captain's seat).
function fill(squad_id, count, txt)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local seated = seat_holder(sq)
    -- (0.104.5) a squad whose leader's office stands empty (Enxah: no militia
    -- commander or captain, both squads leaderless): the best fighter outside
    -- the squads is appointed to it and takes the seat, as make_squad does
    local appointed_leader
    if not seated and #sq.positions > 0 and sq.positions[0].occupant == -1 then
        pcall(function()
            local fort = fort_entity()
            for idx, a in ipairs(fort and fort.positions.assignments or {}) do
                if a.id == sq.leader_assignment and a.histfig == -1 then
                    local pos
                    for _, p in ipairs(fort.positions.own) do if p.id == a.position_id then pos = p end end
                    local pick = pos and pick_soldiers(candidates(), 1)[1]
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
    local okc, cands = pcall(candidates)
    if not okc then return {ok = false, error = 'could not list dwarves: ' .. tostring(cands)} end
    local added = {}
    local tried, k = 0, 1
    for _, c in ipairs(pick_soldiers(cands, count)) do
        tried = tried + 1
        local place = places[k]
        if place and dfhack.military.addToSquad(c.id, squad_id, place) then
            table.insert(added, {unit_id = c.id, name = txt(dfhack.units.getReadableName(c.unit))})
            k = k + 1
        end
    end
    if #added == 0 then
        return seated and {ok = true, added = {}, leader_seated = true, leader_appointed = appointed_leader}
            or {ok = false, error = ('no suitable dwarves could be added (%d candidate(s), %d tried, %d open place(s)%s)'):format(
                #cands, tried, open, sq.positions[0] and sq.positions[0].occupant == -1 and ', the leader\'s seat empty' or '')}
    end
    return {ok = true, added = added, leader_seated = seated or nil, leader_appointed = appointed_leader}
end

-- (0.102) An army bigger than the fort wants (Militarism lowered, or the
-- fort shrank) is trimmed: up to `count` soldiers back to work, those least
-- suited first (fewest combat skills, best at a trade), never a squad's
-- leader, a dwarf who longs to fight, or a squad out on orders.
function trim(count, dry_run, txt)
    if not (dfhack.military and type(dfhack.military.removeFromSquad) == 'function') then
        return {ok = false, rejected = true, error = 'this DFHack cannot take a dwarf out of a squad'}
    end
    local fort = fort_entity()
    if not fort then return {ok = false, error = 'no fort government (entity) found'} end
    local list = {}
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq and #sq.orders == 0 then
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
                        table.insert(list, {u = u, squad = sid, score = combat * 3 - best})
                    end
                end
            end
        end
    end
    table.sort(list, function(a, b)
        if a.score ~= b.score then return a.score < b.score end
        return a.u.id < b.u.id
    end)
    local out = {}
    for i = 1, math.min(count, #list) do
        local c = list[i]
        local name = (txt or tostring)(dfhack.units.getReadableName(c.u))
        if dry_run or dfhack.military.removeFromSquad(c.u.id) then
            table.insert(out, {unit_id = c.u.id, squad_id = c.squad, name = name})
        end
    end
    if #out == 0 then return {ok = false, rejected = true, error = 'no soldier who could go back to work'} end
    return {ok = true, removed = out, dry_run = dry_run or nil}
end

-- (0.102.4) One stressed soldier back to civilian life (DF wiki: the
-- stress-prone are "not suitable for the military"): never a squad's
-- leader, nor while the squad is out on orders.
function release(unit_id, dry_run, txt)
    if not (dfhack.military and type(dfhack.military.removeFromSquad) == 'function') then
        return {ok = false, rejected = true, error = 'this DFHack cannot take a dwarf out of a squad'}
    end
    local u = df.unit.find(unit_id)
    if not u or not dfhack.units.isCitizen(u) then return {ok = false, rejected = true, error = 'no such citizen'} end
    if u.military.squad_id == -1 then return {ok = false, rejected = true, error = 'not in a squad'} end
    if u.military.squad_position == 0 then return {ok = false, rejected = true, error = 'a squad leader stays'} end
    -- (0.103.10) one who longs to fight or train stays: the squad is what
    -- meets that (and the fill would draft them straight back)
    if wants_fight(u) then return {ok = false, rejected = true, error = 'longs to fight or train: the squad is what meets that'} end
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
    local ok, d = pcall(dfhack.persistent.getSiteData, UNIFORMS_KEY, {})
    return ok and type(d) == 'table' and d or {}
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
            if on then fort.positions.assignments_by_type[r]:insert('#', a) end
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
        for r = 0, #fort.positions.assignments_by_type - 1 do erase(fort.positions.assignments_by_type[r]) end
    end)
    pcall(function() a:delete() end)
end

function make_squad(dry_run, txt)
    local fort = fort_entity()
    if not fort then return {ok = false, error = 'no fort government (entity) found'} end
    local best, best_rank, best_idx, best_pos
    for idx, a in ipairs(fort.positions.assignments) do
        if a.squad_id == -1 then
            for _, p in ipairs(fort.positions.own) do
                local rank = LEAD_OFFICES[p.code]
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
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            if u.hist_figure_id == best.histfig then leader = u end
        end
    else
        local okc, cands = pcall(candidates)
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
    local from = squad_with_uniform(fort, sq.id)
    local oku, uniform = true, false
    if from then oku, uniform = pcall(copy_uniform, from, sq) end
    uniform = oku and uniform or false
    if uniform then
        -- a copy of the AI's uniform is the AI's too (it may change it later)
        local mine = ai_uniforms()
        if mine[tostring(from.id)] then
            mine[tostring(sq.id)] = mine[tostring(from.id)]
            pcall(dfhack.persistent.saveSiteData, UNIFORMS_KEY, mine)
        end
    end
    return {ok = true, squad_id = sq.id, office = office, leader = name, appointed = appointed or nil, seated = seated,
            new_post = new_post and true or nil,
            uniform = uniform, uniform_from = from and txt and txt(dfhack.military.getSquadName(from.id)) or nil}
end

-- --- uniforms from the fort's templates ----------------------------------------

-- A squad without a uniform fights in its clothes and the armour the fort
-- makes is never handed out. The fort has uniform templates (DF's military
-- screen: "Melee, leather armor", "Melee, metal armor", ...); the AI gives
-- such a squad one of them, as the screen's "apply uniform" does: each
-- template entry becomes a uniform entry on every place in the squad. A
-- squad the AI gave a uniform to may later be moved to a better one (leather
-- to metal); a uniform you set yourself is never touched.
-- (UNIFORMS_KEY and ai_uniforms() are defined above make_squad)

-- Pure: the template to use from their names. kind 'metal' or 'leather';
-- melee before crossbows; else the first one.
function pick_template(names, kind, ranged)
    local best, best_score
    for i, n in ipairs(names) do
        local l = tostring(n):lower()
        local score = 0
        if l:find(kind or 'leather', 1, true) then score = score + 2 end
        if ranged then
            if l:find('crossbow', 1, true) or l:find('archer', 1, true) or l:find('ranged', 1, true) then
                score = score + 4
            end
        elseif l:find('melee', 1, true) then score = score + 1 end
        if not best_score or score > best_score then best, best_score = i, score end
    end
    return best
end

local function clear_uniform(pos)
    for cat = 0, df.uniform_category._last_item do
        local v = pos.equipment.uniform[cat]
        for i = #v - 1, 0, -1 do
            local spec = v[i]
            v:erase(i)
            pcall(function() spec:delete() end)
        end
    end
end

local function apply_template(uf, sq)
    local n = 0
    for p = 0, #sq.positions - 1 do
        local pos = sq.positions[p]
        clear_uniform(pos)
        for cat = 0, df.uniform_category._last_item do
            local types, subs, infos = uf.uniform_item_types[cat], uf.uniform_item_subtypes[cat], uf.uniform_item_info[cat]
            for i = 0, #types - 1 do
                local info = infos[i]
                local spec = df.squad_uniform_spec:new()
                spec.item = -1
                spec.item_type = types[i]
                spec.item_subtype = subs[i]
                if info then
                    spec.material_class = info.material_class
                    spec.mattype = info.mattype
                    spec.matindex = info.matindex
                    pcall(function() spec.color = info.item_color end)
                    pcall(function() spec.indiv_choice.whole = info.indiv_choice.whole end)
                end
                pos.equipment.uniform[cat]:insert('#', spec)
                n = n + 1
            end
        end
        pcall(function() pos.equipment.flags.whole = uf.flags.whole end)
        -- (0.99.9) the kit replaces clothes: worn over them, a wool glove or
        -- a pig tail shoe keeps the steel one off (region2: 30 on duty, none
        -- armed or helmed; uniform-unstick: "... blocking a missing uniform item")
        pcall(function() pos.equipment.flags.replace_clothing = true end)
        pcall(function() pos.equipment.nickname = uf.name end)
    end
    for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'ammo', 'pants'}) do
        pcall(function()
            sq.ammo.update[f] = true
            df.global.plotinfo.equipment.update[f] = true
        end)
    end
    return n
end

-- Give a squad one of the fort's uniform templates ('leather' or 'metal').
-- A squad that has a uniform is left alone, unless the AI set it (then it
-- may change to another template).
-- Bolts for a crossbow squad: one ammunition entry (bolts of any material,
-- for combat and training), `amount` in all, as the squad's ammo screen sets.
BOLTS_PER_SOLDIER = 50
function set_bolts(sq, amount)
    local sub
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.ammo) do
            if def.id == 'ITEM_AMMO_BOLTS' then sub = def.subtype ~= nil and def.subtype or i end
        end
    end)
    if sub == nil then return false, 'no bolts in this game' end
    local v = sq.ammo.ammunition
    for i = #v - 1, 0, -1 do
        local a = v[i]
        v:erase(i)
        pcall(function() a:delete() end)
    end
    local spec = df.squad_ammo_spec:new()
    spec.item_type = df.item_type.AMMO
    spec.item_subtype = sub
    pcall(function() spec.material_class = -1 end)
    spec.mattype, spec.matindex = -1, -1
    spec.amount = amount
    spec.flags.use_combat = true
    spec.flags.use_training = true
    v:insert('#', spec)
    pcall(function()
        sq.ammo.update.ammo = true
        df.global.plotinfo.equipment.update.ammo = true
    end)
    return true
end

-- (0.99.9) The uniforms the AI set replace clothes instead of going over
-- them (DF's own uniform option). Squads someone else dressed are left alone.
-- Returns how many positions changed.
function replace_clothing(dry_run)
    local mine, n = ai_uniforms(), 0
    for key in pairs(mine) do
        local sq = fort_squad(tonumber(key))
        if sq then
            for p = 0, #sq.positions - 1 do
                local pos = sq.positions[p]
                local ok, was = pcall(function() return pos.equipment.flags.replace_clothing end)
                if ok and not was then
                    if not dry_run then pcall(function() pos.equipment.flags.replace_clothing = true end) end
                    n = n + 1
                end
            end
        end
    end
    if n > 0 and not dry_run then
        for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'pants'}) do
            pcall(function() df.global.plotinfo.equipment.update[f] = true end)
        end
    end
    return n
end

function set_uniform(squad_id, kind, dry_run, txt, ranged)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local fort = fort_entity()
    if not fort or #fort.uniforms == 0 then
        return {ok = false, rejected = true, error = 'the fort has no uniform templates (make one in the military screen)'}
    end
    local names = {}
    for i, uf in ipairs(fort.uniforms) do names[i + 1] = uf.name end
    local idx = pick_template(names, kind, ranged)
    local uf = fort.uniforms[idx - 1]
    if ranged and not tostring(uf.name):lower():find('crossbow', 1, true) then
        return {ok = false, rejected = true, error = 'the fort has no crossbow uniform template'}
    end
    local mine = ai_uniforms()
    local had = #sq.positions > 0 and uniform_set(sq.positions[0])
    local key = tostring(squad_id)
    if had and not mine[key] then
        return {ok = false, rejected = true, error = 'the squad has a uniform someone set: left alone'}
    end
    if had and tostring(mine[key]):gsub(' |weapon:.*$', '') == uf.name then
        return {ok = false, rejected = true, error = 'the squad already wears ' .. uf.name}
    end
    local name = (txt or tostring)(uf.name)
    if dry_run then return {ok = true, dry_run = true, template = name, replaces = mine[key]} end
    local was_ranged = had and tostring(mine[key] or ''):lower():find('crossbow', 1, true)
    local n = apply_template(uf, sq)
    if n == 0 then return {ok = false, error = 'the template ' .. name .. ' has nothing in it'} end
    local cleared
    if was_ranged and not ranged then
        -- back to close combat: the bolts the AI asked for go too
        pcall(function()
            local v = sq.ammo.ammunition
            for i = #v - 1, 0, -1 do
                local a = v[i]
                v:erase(i)
                pcall(function() a:delete() end)
            end
            sq.ammo.update.ammo = true
            df.global.plotinfo.equipment.update.ammo = true
            cleared = true
        end)
    end
    mine[key] = uf.name
    pcall(dfhack.persistent.saveSiteData, UNIFORMS_KEY, mine)
    local bolts
    if ranged then
        bolts = BOLTS_PER_SOLDIER * math.max(1, #sq.positions)
        local okb, err = set_bolts(sq, bolts)
        if not okb then bolts = 'not set: ' .. tostring(err) end
    end
    return {ok = true, template = name, items = n, replaced = had or nil, bolts = bolts, bolts_cleared = cleared}
end

-- The weapon in a squad's uniform made one kind (e.g. ITEM_WEAPON_AXE_BATTLE)
-- instead of "any melee weapon", which lets a soldier take a miner's pick
-- (a pick is a weapon). Only on a uniform the AI set.
-- (0.100) Is this a squad of shooters? Its stored entry says crossbow, or
-- its uniform's weapon is a crossbow or "any ranged weapon".
function squad_is_ranged(sq, entry)
    if tostring(entry or ''):lower():find('crossbow', 1, true) then return true end
    local ranged = false
    pcall(function()
        for _, spec in ipairs(sq.positions[0].equipment.uniform[df.uniform_category.weapon]) do
            if spec.indiv_choice.ranged then ranged = true end
            if spec.item_subtype ~= -1 then
                local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
                if def and def.id == 'ITEM_WEAPON_CROSSBOW' then ranged = true end
            end
        end
    end)
    return ranged
end

function set_uniform_weapon(squad_id, weapon_id, dry_run)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local mine = ai_uniforms()
    local key = tostring(squad_id)
    if not mine[key] then return {ok = false, rejected = true, error = 'not a uniform the AI set: left alone'} end
    -- (0.100) a crossbow squad keeps its crossbows, whatever is asked (region2's
    -- squad 56 was given battle axes)
    if weapon_id ~= 'ITEM_WEAPON_CROSSBOW' and squad_is_ranged(sq, mine[key]) then
        return {ok = false, rejected = true, error = 'a crossbow squad: its weapon stays the crossbow'}
    end
    -- the weapon's subtype: its place among the game's weapon definitions
    -- (0.51 asked dfhack.items.findSubtype, which didn't give it)
    local sub
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.weapons) do
            if def.id == weapon_id then sub = def.subtype ~= nil and def.subtype or i end
        end
    end)
    if sub == nil then
        return {ok = false, rejected = true, error = 'no such weapon: ' .. tostring(weapon_id)}
    end
    if dry_run then return {ok = true, dry_run = true, weapon = weapon_id} end
    local cat = df.uniform_category.weapon
    for p = 0, #sq.positions - 1 do
        local v = sq.positions[p].equipment.uniform[cat]
        for i = #v - 1, 0, -1 do
            local spec = v[i]
            v:erase(i)
            pcall(function() spec:delete() end)
        end
        local spec = df.squad_uniform_spec:new()
        spec.item = -1
        spec.item_type = df.item_type.WEAPON
        spec.item_subtype = sub
        spec.material_class = -1
        spec.mattype = -1
        spec.matindex = -1
        -- (0.104.80) any colour: a new entry's colour is 0, a dye colour, so DF
        -- gave no weapon to it and took back every one the AI gave (Enxah)
        pcall(function() spec.color = -1 end)
        v:insert('#', spec)
    end
    for _, f in ipairs({'weapon'}) do
        pcall(function()
            sq.ammo.update[f] = true
            df.global.plotinfo.equipment.update[f] = true
        end)
    end
    local base = tostring(mine[key]):gsub(' |weapon:.*$', '')
    mine[key] = base .. ' |weapon:' .. weapon_id
    pcall(dfhack.persistent.saveSiteData, UNIFORMS_KEY, mine)
    return {ok = true, weapon = weapon_id, places = #sq.positions}
end

-- A squad the AI made whose uniform it copied before 0.82 (when copies
-- weren't recorded): the uniform is marked as the AI's, named after the
-- fort's template it matches (crossbow or melee, metal or leather; the
-- weapon kind if one is asked for), so the AI may change it later. Only a
-- squad with a uniform and not already marked; the planner asks only for
-- squads it made itself (memory.squads_made).
function adopt_uniform(squad_id, dry_run, txt)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local mine = ai_uniforms()
    local key = tostring(squad_id)
    if mine[key] then return {ok = false, rejected = true, error = 'already the AI\'s: ' .. tostring(mine[key])} end
    if #sq.positions == 0 or not uniform_set(sq.positions[0]) then
        return {ok = false, rejected = true, error = 'the squad has no uniform'}
    end
    local ranged, metal, weapon = false, false, nil
    local pos = sq.positions[0]
    for cat = 0, df.uniform_category._last_item do
        for _, spec in ipairs(pos.equipment.uniform[cat]) do
            if spec.material_class == df.entity_material_category.Armor then metal = true end
            -- (0.100) "any ranged weapon" is a crossbow squad too (it was adopted as melee)
            if spec.item_type == df.item_type.WEAPON then
                pcall(function() if spec.indiv_choice.ranged then ranged = true end end)
            end
            if spec.item_type == df.item_type.WEAPON and spec.item_subtype ~= -1 then
                pcall(function()
                    local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
                    weapon = def and def.id or weapon
                end)
            end
        end
    end
    if weapon == 'ITEM_WEAPON_CROSSBOW' then ranged, weapon = true, nil end
    if ranged then weapon = nil end
    local fort = fort_entity()
    local names = {}
    for i, uf in ipairs(fort and fort.uniforms or {}) do names[i + 1] = uf.name end
    if #names == 0 then return {ok = false, rejected = true, error = 'the fort has no uniform templates'} end
    local name = names[pick_template(names, metal and 'metal' or 'leather', ranged)]
    local entry = name .. (weapon and (' |weapon:' .. weapon) or '')
    if dry_run then return {ok = true, dry_run = true, uniform = entry} end
    mine[key] = entry
    pcall(dfhack.persistent.saveSiteData, UNIFORMS_KEY, mine)
    return {ok = true, uniform = (txt or tostring)(entry)}
end

-- Squads whose uniform the AI set: squad id -> template name.
function ai_uniform_names(txt)
    local out = {}
    for k, v in pairs(ai_uniforms()) do out[k] = (txt or tostring)(v) end
    return out
end

-- Switch a squad to the named schedule ("Staggered training", "Off duty"...).
function set_routine(squad_id, name)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    for i, r in ipairs(df.global.plotinfo.alerts.routines) do
        if r.name == name then
            sq.cur_routine_idx = i
            return {ok = true, routine = name}
        end
    end
    return {ok = false, rejected = true, error = 'no schedule named ' .. tostring(name)}
end

-- (0.100, security pass) whom a kill order may name: what the report calls a
-- threat (DFHack's isDanger, or an invader) or a dwarf gone berserk, never a
-- merchant, a diplomat, a tame animal or a sane citizen. The rules only send
-- these; this keeps a bad id from turning a squad on the fort.
function kill_target_ok(u)
    local U = dfhack.units
    local function is(f) local ok, v = pcall(f, u); return ok and v end
    if u.mood == df.mood_type.Berserk then return true end
    if is(U.isMerchant) or is(U.isDiplomat) or is(U.isTame) then return false end
    if is(U.isCitizen) then return false end
    return is(U.isDanger) or is(U.isInvader)
end

-- Kill orders against the given units (only ones actually on the map), or
-- clear the orders the AI gave before. The player's own orders are kept.
function orders(squad_id, kill, clear)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local removed = 0
    for i = #sq.orders - 1, 0, -1 do
        if is_ai_order(sq.orders[i]) then
            local o = sq.orders[i]
            sq.orders:erase(i)
            o:delete()
            removed = removed + 1
        end
    end
    if clear then return {ok = true, cleared = removed} end
    local o = df.squad_order_kill_listst:new()
    local n, refused = 0, 0
    for _, id in ipairs(kill or {}) do
        local u = df.unit.find(id)
        if u and not dfhack.units.isDead(u) then
            if kill_target_ok(u) then
                o.units:insert('#', id)
                n = n + 1
            else
                refused = refused + 1
            end
        end
    end
    if n == 0 then
        o:delete()
        return {ok = false, rejected = true, refused = refused,
                error = refused > 0 and 'none of those units is a threat (a dangerous creature, an invader or a berserk dwarf)'
                    or 'none of those units is on the map and alive'}
    end
    o.title = AI_ORDER_TITLE
    -- stamped with today's date where the order has one (DF ages orders)
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    return {ok = true, targets = n, replaced = removed}
end

-- (0.104.83) Hold the gate: the AI's orders on the squad replaced by one
-- order to defend the gate guard burrow (the soldiers wait there and fight
-- what comes in). The player's own orders are kept.
function defend(squad_id, burrow_id)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    for _, o in ipairs(sq.orders) do
        if not is_ai_order(o) then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
    end
    local removed = 0
    for i = #sq.orders - 1, 0, -1 do
        local o = sq.orders[i]
        if is_ai_order(o) then
            if df.squad_order_defend_burrowsst:is_instance(o) then
                return {ok = false, rejected = true, error = 'the squad already holds the gate'}
            end
            sq.orders:erase(i)
            o:delete()
            removed = removed + 1
        end
    end
    local o = df.squad_order_defend_burrowsst:new()
    o.burrows:insert('#', burrow_id)
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    return {ok = true, burrow_id = burrow_id, replaced = removed}
end

-- Gear: how many soldiers carry a weapon, wear body armour and a helm; how
-- many squads have a uniform (without one, armour made isn't handed out);
-- spare metal gear; and weapon-grade metal bars by kind.
GEAR_METALS = {'STEEL', 'IRON', 'BRONZE', 'BISMUTH_BRONZE', 'COPPER'}   -- best first
local GEAR_LISTS = {weapons = 'WEAPON', body = 'ARMOR', helms = 'HELM', pants = 'PANTS',
                    gloves = 'GLOVES', boots = 'SHOES', shields = 'SHIELD'}

local function metal_token(item)
    local mi = dfhack.matinfo.decode(item)
    if not mi or not mi.inorganic or not mi.material.flags.IS_METAL then return nil end
    return mi.inorganic.id
end

-- Does a squad position have a uniform? Found by field name, since where DF
-- keeps it has moved between versions (pos.uniform, pos.equipment.uniform...):
-- any field whose name contains "uniform" holding a non-empty list.
local function entries(v)
    local ok, n = pcall(function() return #v end)
    if not ok or type(n) ~= 'number' or n == 0 then return 0 end
    local total = 0
    for i = 0, n - 1 do
        local okx, x = pcall(function() return v[i] end)
        if okx and type(x) == 'userdata' then
            local okn, m = pcall(function() return #x end)
            total = total + ((okn and type(m) == 'number') and m or 1)
        elseif okx and x ~= nil then
            total = total + 1
        end
    end
    return total
end

local function has_uniform(obj, depth)
    local ok, found = pcall(function()
        for k, v in pairs(obj) do
            if type(k) == 'string' and k:lower():find('uniform') and entries(v) > 0 then return true end
            if depth > 0 and type(k) == 'string' and type(v) == 'userdata'
                    and (k == 'equipment' or k:lower():find('equip')) and has_uniform(v, depth - 1) then
                return true
            end
        end
        return false
    end)
    return ok and found
end

local function position_has_uniform(pos)
    -- DF 50+: pos.equipment.uniform[category] (squad_position_equipmentst)
    local ok, found = pcall(function()
        for cat = 0, df.uniform_category._last_item do
            if #pos.equipment.uniform[cat] > 0 then return true end
        end
        return false
    end)
    if ok then return found end
    return has_uniform(pos, 2)
end
uniform_set = position_has_uniform       -- (for make_squad, defined above this)

-- For brain/selftest.py: the field names of a squad and one of its
-- positions, to see where this DF version keeps uniforms.
function probe()
    local fort = fort_entity()
    if not fort or #fort.squads == 0 then return {note = 'no squads'} end
    local sq = df.squad.find(fort.squads[0])
    local function fields(obj, depth)
        local out = {}
        local ok = pcall(function()
            for k, v in pairs(obj) do
                local t = type(v)
                local n = entries(v)
                local e = tostring(k) .. ':' .. t .. (n > 0 and ('[' .. n .. ']') or '')
                if depth > 0 and t == 'userdata' and n == 0 then
                    local sub = fields(v, depth - 1)
                    if #sub > 0 then e = e .. '{' .. table.concat(sub, ',') .. '}' end
                end
                table.insert(out, e)
            end
        end)
        if not ok then table.insert(out, '?') end
        return out
    end
    local pos = #sq.positions > 1 and sq.positions[1] or sq.positions[0]
    return {squad = table.concat(fields(sq, 0), ' '), position = table.concat(fields(pos, 1), ' ')}
end

-- How an item is carried: the enum moved between DF versions
-- (df.inv_item_role_type in v50+, unit_inventory_item.T_mode before).
local function inv_mode_name(mode)
    local okn, enum = pcall(function() return df.inv_item_role_type end)
    if not okn then enum = nil end
    if not enum then
        local ok, old = pcall(function() return df.unit_inventory_item.T_mode end)
        enum = ok and old or nil
    end
    return enum and enum[mode] or tostring(mode)
end

-- (0.104.58) Gear DF will never hand out again: on the fort's "assigned"
-- list though no soldier's place claims it (a dead or released soldier's), or
-- on no list at all. Enxah, summer y74: a copper battle axe lying free on the
-- assigned list with no claim, another on no list, 52 helms on the unassigned
-- list of 115 counted spare, while 19 soldiers went without an axe. DF's
-- lists are plotinfo.equipment.items_assigned / items_unassigned, by kind.
STRAY_KINDS = {'WEAPON', 'ARMOR', 'HELM', 'PANTS', 'GLOVES', 'SHOES', 'SHIELD'}

local function id_set(v)
    local s = {}
    pcall(function() for _, id in ipairs(v) do s[id] = true end end)
    return s
end

-- every item any squad place claims (its own list or a uniform entry's)
local function claimed_items()
    local c = {}
    for _, sq in ipairs(df.global.world.squads.all) do
        for _, pos in ipairs(sq.positions) do
            pcall(function() for _, iid in ipairs(pos.equipment.assigned_items) do c[iid] = true end end)
            pcall(function()
                for cat = 0, df.uniform_category._last_item do
                    for _, spec in ipairs(pos.equipment.uniform[cat]) do
                        for _, iid in ipairs(spec.assigned) do c[iid] = true end
                    end
                end
            end)
        end
    end
    return c
end

-- An item DF could hand to a soldier: none a unit holds, a trader's, an
-- enemy's, built in, an artifact, owned, or a worker's tool.
local function free_gear(it, work)
    local f = it.flags
    if f.owned or f.trader or f.hostile or f.removed or f.garbage_collect or f.construction
            or f.in_building or f.artifact or work[it.id] then
        return false
    end
    if f.in_inventory then
        local okh, u = pcall(dfhack.items.getHolderUnit, it)
        if (not okh) or u ~= nil then return false end
    end
    return true
end

-- The fort's equipment lists, or nil where this DF keeps them elsewhere.
local function equipment_lists()
    local ok, eq = pcall(function() return df.global.plotinfo.equipment end)
    if not ok or not eq then return nil end
    local okv = pcall(function() return #eq.items_assigned.WEAPON + #eq.items_unassigned.WEAPON end)
    if not okv then return nil end
    return eq
end

-- Counts by kind: `orphan` on the assigned list with no claim, `unlisted` on
-- neither list (both free items only); `unassigned` the ids DF may hand out.
function stray_report()
    local eq = equipment_lists()
    if not eq then return nil end
    local claimed, work = claimed_items(), id_set(eq.work_weapons)
    local out = {orphan = {}, unlisted = {}, n = 0, unassigned = {}, work = work}
    for _, kind in ipairs(STRAY_KINDS) do
        local asg, una = id_set(eq.items_assigned[kind]), id_set(eq.items_unassigned[kind])
        out.unassigned[kind] = una
        -- (0.104.59) new items wait on the "unmanifested" list before DF files
        -- them: listed, not stray (a new axe from the forge counted as lost)
        local okm, unm = pcall(function() return id_set(eq.items_unmanifested[kind]) end)
        unm = okm and unm or {}
        local o, u = 0, 0
        for _, it in ipairs(df.global.world.items.other[kind]) do
            if free_gear(it, work) and not claimed[it.id] and not unm[it.id] then
                if asg[it.id] and not una[it.id] then o = o + 1
                elseif not asg[it.id] and not una[it.id] then u = u + 1 end
            end
        end
        if o > 0 then out.orphan[kind] = o end
        if u > 0 then out.unlisted[kind] = u end
        out.n = out.n + o + u
    end
    return out
end

local function vec_remove(v, id)
    for i = #v - 1, 0, -1 do
        if v[i] == id then v:erase(i) return true end
    end
    return false
end

local function vec_add(v, id)
    -- DF keeps these lists in id order; insert in order (append if it isn't)
    local n = #v
    local sorted = true
    for i = 1, n - 1 do
        if v[i - 1] > v[i] then sorted = false break end
    end
    if sorted then
        local pos = n
        for i = 0, n - 1 do
            if v[i] == id then return false end
            if v[i] > id then pos = i break end
        end
        v:insert(pos, id)
    else
        for i = 0, n - 1 do if v[i] == id then return false end end
        v:insert('#', id)
    end
    return true
end

-- Put stray gear back on the unassigned list so DF hands it out again (at
-- most `limit` items), and ask DF to redo its assignments: every kind
-- assigned to no one; on no list, weapons only.
function free_stray_gear(dry_run, limit)
    local eq = equipment_lists()
    if not eq then return {ok = false, rejected = true, error = "this DF keeps its equipment lists elsewhere"} end
    limit = limit or 100
    local claimed, work = claimed_items(), id_set(eq.work_weapons)
    local moved, by_kind = 0, {}
    for _, kind in ipairs(STRAY_KINDS) do
        local asgv, unav = eq.items_assigned[kind], eq.items_unassigned[kind]
        local asg, una = id_set(asgv), id_set(unav)
        local okm, unm = pcall(function() return id_set(eq.items_unmanifested[kind]) end)
        unm = okm and unm or {}
        for _, it in ipairs(df.global.world.items.other[kind]) do
            if moved >= limit then break end
            -- on no list: weapons only (armour may be left off for its size:
            -- reported, not moved, until a probe shows why)
            if free_gear(it, work) and not claimed[it.id] and not una[it.id] and not unm[it.id]
                    and (asg[it.id] or kind == 'WEAPON') then
                if not dry_run then
                    if asg[it.id] then vec_remove(asgv, it.id) end
                    vec_add(unav, it.id)
                end
                moved = moved + 1
                by_kind[kind] = (by_kind[kind] or 0) + 1
            end
        end
    end
    if dry_run then return {ok = true, dry_run = true, would_free = moved, by_kind = by_kind} end
    if moved > 0 then
        for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'pants'}) do
            pcall(function() df.global.plotinfo.equipment.update[f] = true end)
        end
    end
    return {ok = true, freed = moved, by_kind = by_kind}
end

-- (0.104.60) Weapons handed out by the AI when DF won't: Enxah, autumn y74,
-- every melee uniform entry asked for a battle axe ("given 0" on all 19
-- melee places) while 19 free axes lay on DF's unassigned list; the armour
-- of the same uniforms was handed out (helmed 6 -> 20 in a month). The
-- item goes on the soldier's place as DF's own assignments do (the entry's
-- `assigned`, the place's `assigned_items`, from the unassigned to the
-- assigned list); the soldier then fetches it (PickupEquipment).
local function weapon_specs_empty(pos)
    local out = {}
    pcall(function()
        for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
            if spec.item_type == df.item_type.WEAPON and #spec.assigned == 0 then table.insert(out, spec) end
        end
    end)
    return out
end

-- occupied places whose weapon entry has nothing; and how many melee
-- entries have a weapon given (fetched or not: the arms rule counts them)
function weapon_gaps()
    local fort, n, given = fort_entity(), 0, 0
    if not fort then return 0, 0 end
    local xbow
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.weapons) do
            if def.id == 'ITEM_WEAPON_CROSSBOW' then xbow = def.subtype ~= nil and def.subtype or i end
        end
    end)
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq then
            for _, pos in ipairs(sq.positions) do
                if pos.occupant ~= -1 then
                    n = n + #weapon_specs_empty(pos)
                    pcall(function()
                        for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                            if spec.item_type == df.item_type.WEAPON and #spec.assigned > 0
                                    and spec.item_subtype ~= xbow then
                                given = given + 1
                            end
                        end
                    end)
                end
            end
        end
    end
    return n, given
end

-- (0.104.80) Where the handed-out weapons go: Enxah, 25 Oct 17:52-17:57,
-- assign_weapons gave 9-10 axes a call to squads 26 and 46 (both off duty)
-- and the next call found the same places empty again (one melee entry of
-- 25 still given). Each weapon given is booked here (the module stays
-- loaded between calls); the next call says what became of each: still on
-- the entry, off the entry but on the place, off the place, back on DF's
-- unassigned list, the soldier gone from the place, the item gone; and the
-- squad's routine then and now.
AW_LEDGER = AW_LEDGER or {}

local function list_has(v, id)
    for _, x in ipairs(v or {}) do if x == id then return true end end
    return false
end

local function routine_of(sq, names)
    local ok, idx = pcall(function() return sq.cur_routine_idx end)
    if not ok or type(idx) ~= 'number' then return '?' end
    return tostring(names[idx + 1] or idx)
end

local function safe_routines()
    local ok, n = pcall(routine_names)
    return ok and n or {}
end

local function check_ledger(eq)
    local names = safe_routines()
    local out = {booked = 0, kept = 0, why = {}, samples = {}}
    local now = df.global.cur_year_tick or 0
    for id, b in pairs(AW_LEDGER) do
        out.booked = out.booked + 1
        local sq = df.squad.find(b.sid)
        local pos = sq and sq.positions[b.pi]
        local it
        if not pcall(function() it = df.item.find(id) end) then it = {flags = {}} end
        local on_spec, on_pos = false, false
        if pos then
            on_pos = list_has(pos.equipment.assigned_items, id)
            pcall(function()
                for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                    if list_has(spec.assigned, id) then on_spec = true end
                end
            end)
        end
        local why
        if not it then why = 'item gone'
        elseif not pos then why = 'place gone'
        elseif pos.occupant ~= b.hf then why = 'soldier left the place'
        elseif on_spec and on_pos then why = nil
        elseif on_pos then why = 'off the entry, still on the place'
        elseif on_spec then why = 'on the entry, off the place'
        else why = 'off the entry and the place' end
        if why then
            local where = it and ((it.flags.in_inventory and 'carried') or (it.flags.on_ground and 'on the ground')
                or 'stored') or '-'
            local lists = (list_has(eq.items_unassigned.WEAPON, id) and 'unassigned')
                or (list_has(eq.items_assigned.WEAPON, id) and 'assigned') or 'no list'
            local key = why .. '; ' .. lists .. '; routine then ' .. b.routine .. ', now '
                .. (sq and routine_of(sq, names) or '-')
            out.why[key] = (out.why[key] or 0) + 1
            if #out.samples < 4 then
                table.insert(out.samples, ('#%d squad %d place %d: %s (%s, %d ticks)'):format(
                    id, b.sid, b.pi, why, where, (now - b.tick) % 403200))
            end
            AW_LEDGER[id] = nil
        else
            out.kept = out.kept + 1
            if (now - b.tick) % 403200 > 28 * 1200 then AW_LEDGER[id] = nil end   -- a month kept: stop watching
        end
    end
    return out
end

-- (0.104.80) Every field of a weapon entry, one level deep (vectors by
-- length): DF fills the crossbow entries and takes the AI's axes back, so a
-- melee entry is set beside a ranged one to find what DF reads differently.
local function dump_fields(obj, depth)
    local out = {}
    local ok = pcall(function()
        for k, v in pairs(obj) do
            local tv = type(v)
            if tv == 'userdata' then
                local okl, n = pcall(function() return #v end)
                if okl and type(n) == 'number' and (depth or 0) >= 1 then out[tostring(k)] = '#' .. n
                elseif (depth or 0) < 1 then out[tostring(k)] = dump_fields(v, (depth or 0) + 1)
                else out[tostring(k)] = tostring(v) end
            else
                out[tostring(k)] = tostring(v)
            end
        end
    end)
    if not ok then out._error = 'not readable' end
    return out
end

local function spec_dump()
    local fort = fort_entity()
    if not fort then return nil end
    local xbow
    pcall(function()
        for i, def in ipairs(df.global.world.raws.itemdefs.weapons) do
            if def.id == 'ITEM_WEAPON_CROSSBOW' then xbow = def.subtype ~= nil and def.subtype or i end
        end
    end)
    local out = {}
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for pi, pos in ipairs(sq and sq.positions or {}) do
            pcall(function()
                for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                    local kind = spec.item_subtype == xbow and 'ranged' or 'melee'
                    if not out[kind] then
                        out[kind] = {squad = sid, place = pi, assigned = #spec.assigned, spec = dump_fields(spec)}
                    end
                end
            end)
            if out.melee and out.ranged then return out end
        end
    end
    return out
end

-- (0.104.80) Weapon entries asking for a colour: set by set_uniform_weapon
-- before 0.104.80 (colour 0, a dye colour, not "any": Enxah, every melee
-- entry; the crossbow entries, from DF's own templates, had -1 and were
-- filled). Put to any colour; DF then hands out the weapons itself.
function fix_weapon_colours(dry_run)
    local fort = fort_entity()
    if not fort then return 0 end
    local n = 0
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for _, pos in ipairs(sq and sq.positions or {}) do
            pcall(function()
                for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                    if spec.item_type == df.item_type.WEAPON and spec.color ~= -1 then
                        if not dry_run then spec.color = -1 end
                        n = n + 1
                    end
                end
            end)
        end
    end
    if n > 0 and not dry_run then
        pcall(function() df.global.plotinfo.equipment.update.weapon = true end)
    end
    return n
end

function assign_weapons(dry_run, limit)
    local eq = equipment_lists()
    if not eq then return {ok = false, rejected = true, error = "this DF keeps its equipment lists elsewhere"} end
    local fort = fort_entity()
    if not fort then return {ok = false, rejected = true, error = 'no fort'} end
    limit = limit or 10
    local claimed, work = claimed_items(), id_set(eq.work_weapons)
    local una = id_set(eq.items_unassigned.WEAPON)
    -- free weapons DF could hand out: on its unassigned list, not forbidden,
    -- not on a job, nobody's tool or claim
    local pool = {}
    for _, it in ipairs(df.global.world.items.other.WEAPON) do
        local f = it.flags
        if una[it.id] and not claimed[it.id] and free_gear(it, work) and not f.forbid and not f.in_job
                and not f.dump and not f.melt then
            local x, y, z = dfhack.items.getPosition(it)
            if x then table.insert(pool, {it = it, sub = it:getSubtype(), pos = xyz2pos(x, y, z)}) end
        end
    end
    local ledger = (not dry_run) and check_ledger(eq) or nil
    local colours = fix_weapon_colours(dry_run)
    local names = safe_routines()
    local done, out = 0, {}
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        for pi, pos in ipairs(sq and sq.positions or {}) do
            if done >= limit then break end
            if pos.occupant ~= -1 then
                local hf = df.historical_figure.find(pos.occupant)
                local u = hf and df.unit.find(hf.unit_id)
                local ux, uy, uz
                if u then ux, uy, uz = dfhack.units.getPosition(u) end
                for _, spec in ipairs(u and ux and weapon_specs_empty(pos) or {}) do
                    if done >= limit then break end
                    local upos, best, bd = xyz2pos(ux, uy, uz), nil, nil
                    for i, c in ipairs(pool) do
                        if (spec.item_subtype == -1 or c.sub == spec.item_subtype) then
                            local d = math.abs(c.pos.x - ux) + math.abs(c.pos.y - uy) + 3 * math.abs(c.pos.z - uz)
                            if (not bd or d < bd) and dfhack.maps.canWalkBetween(upos, c.pos) then best, bd = i, d end
                        end
                    end
                    if best then
                        local c = table.remove(pool, best)
                        if not dry_run then
                            spec.assigned:insert('#', c.it.id)
                            vec_add(pos.equipment.assigned_items, c.it.id)
                            vec_remove(eq.items_unassigned.WEAPON, c.it.id)
                            vec_add(eq.items_assigned.WEAPON, c.it.id)
                            AW_LEDGER[c.it.id] = {sid = sid, pi = pi, hf = pos.occupant,
                                                  tick = df.global.cur_year_tick or 0, routine = routine_of(sq, names)}
                        end
                        done = done + 1
                        local okd, d = pcall(function()
                            return (dfhack.df2utf or tostring)(dfhack.items.getDescription(c.it, 0, true))
                        end)
                        table.insert(out, ('squad %d: %s'):format(sid, okd and d or ('#' .. c.it.id)))
                    end
                end
            end
        end
    end
    if dry_run then return {ok = true, dry_run = true, would_assign = done, items = out} end
    local specs
    if ledger and ledger.booked > ledger.kept then specs = spec_dump() end
    if done == 0 and colours == 0 then
        -- (0.104.80) nothing to hand out is a refusal: the brain backs off
        -- (asked every cycle after DF took over the arming, 18:24)
        return {ok = false, rejected = true, left = #pool, ledger = ledger, specs = specs,
                error = 'no free weapon fits the empty weapon places'}
    end
    return {ok = true, assigned = done, items = out, left = #pool, ledger = ledger, specs = specs,
            colours_fixed = colours > 0 and colours or nil}
end

function gear_report()
    -- armed/armored/helmed count only soldiers ON DUTY: off duty they put
    -- their weapons (and sometimes armour) away, which isn't a shortage
    local out = {soldiers = 0, on_duty = 0, armed = 0, armored = 0, helmed = 0, squads_with_uniform = 0,
                 legged = 0, gloved = 0, booted = 0, shielded = 0, ranged_armed = 0,
                 spare_crossbows = 0, bolts = 0,
                 squads = 0, spare = {}, bars = {}, forges = 0}
    local routines = routine_names()
    local fort = fort_entity()
    if fort then
        for _, sid in ipairs(fort.squads) do
            local sq = df.squad.find(sid)
            if sq then
                out.squads = out.squads + 1
                local okr, idx = pcall(function() return sq.cur_routine_idx end)
                local routine = okr and routines[idx + 1] or ''
                local on_duty = not tostring(routine):lower():find('off duty', 1, true)
                local uniform = false
                for _, pos in ipairs(sq.positions) do
                    if position_has_uniform(pos) then uniform = true end
                    if pos.occupant ~= -1 then
                        local hf = df.historical_figure.find(pos.occupant)
                        local u = hf and df.unit.find(hf.unit_id)
                        if u then
                            out.soldiers = out.soldiers + 1
                        end
                        if u and on_duty then
                            out.on_duty = out.on_duty + 1
                            local w, a, h, p, g, b, sh = false, false, false, false, false, false, false
                            for _, inv in ipairs(u.inventory) do
                                local t, how = inv.item:getType(), inv_mode_name(inv.mode)
                                if t == df.item_type.WEAPON and how == 'Weapon' then w = true end
                                if t == df.item_type.ARMOR and how == 'Worn' then a = true end
                                if t == df.item_type.HELM and how == 'Worn' then h = true end
                                -- the rest of a kit, metal only (cloth and leather are clothes)
                                local metal = metal_token(inv.item) ~= nil
                                if metal and how == 'Worn' then
                                    if t == df.item_type.PANTS then p = true end
                                    if t == df.item_type.GLOVES then g = true end
                                    if t == df.item_type.SHOES then b = true end
                                end
                                if t == df.item_type.SHIELD and how ~= 'Hauled' then sh = true end
                            end
                            for _, inv in ipairs(u.inventory) do
                                if inv.item:getType() == df.item_type.WEAPON and inv_mode_name(inv.mode) == 'Weapon' then
                                    local okc, id = pcall(function() return inv.item.subtype.id end)
                                    if okc and id == 'ITEM_WEAPON_CROSSBOW' then out.ranged_armed = out.ranged_armed + 1 end
                                end
                            end
                            if w then out.armed = out.armed + 1 end
                            if a then out.armored = out.armored + 1 end
                            if h then out.helmed = out.helmed + 1 end
                            if p then out.legged = out.legged + 1 end
                            if g then out.gloved = out.gloved + 1 end
                            if b then out.booted = out.booted + 1 end
                            if sh then out.shielded = out.shielded + 1 end
                        end
                    end
                end
                if uniform then out.squads_with_uniform = out.squads_with_uniform + 1 end
            end
        end
    end
    local other = df.global.world.items.other
    local grade = {}
    for _, m in ipairs(GEAR_METALS) do grade[m] = true end
    -- (0.104.58) spare is what DF can hand out: on its unassigned list, no
    -- worker's tool; stray gear (off both lists, or assigned to no one) is
    -- counted apart for free_stray_gear
    local okst, st = pcall(stray_report)
    st = okst and st or nil
    if st then out.stray = {n = st.n, orphan = st.orphan, unlisted = st.unlisted} end
    -- (0.104.60) soldiers' places whose weapon entry DF left empty
    pcall(function() out.weapon_gaps, out.melee_given = weapon_gaps() end)
    for key, list_name in pairs(GEAR_LISTS) do
        local n = 0
        local una = st and st.unassigned[list_name]
        for _, it in ipairs(other[df.items_other_id[list_name]]) do
            local f = it.flags
            local listed = (not st) or (una[it.id] and not st.work[it.id])
            -- (0.104.55) in a bin counts: only a unit's inventory doesn't (Enxah:
            -- 120 helms in bins counted as none spare, so 114 gauntlet and 96
            -- boot orders went in while 3 of 26 soldiers were armed)
            local held = false
            if f.in_inventory then
                local okh, u = pcall(dfhack.items.getHolderUnit, it)
                held = (not okh) or u ~= nil
                if not held then
                    local okc, c = pcall(dfhack.items.getContainer, it)
                    held = (not okc) or c == nil
                end
            end
            if listed and not (f.forbid or f.garbage_collect or f.rotten or f.trader or f.removed or f.dump
                    or f.owned or held or f.in_building or f.construction or f.hostile) then
                local m = metal_token(it)
                if m and grade[m] then
                    n = n + 1
                    if key == 'weapons' then
                        -- by kind (a uniform asking for battle axes takes only those)
                        local okd, id = pcall(function() return it.subtype.id end)
                        if okd and id then
                            out.spare_weapons = out.spare_weapons or {}
                            out.spare_weapons[id] = (out.spare_weapons[id] or 0) + 1
                        end
                    end
                end
            end
        end
        out.spare[key] = n
    end
    -- crossbows of any material lying free, and bolts anywhere but a trader's
    for _, it in ipairs(other.WEAPON) do
        local f = it.flags
        local okc, id = pcall(function() return it.subtype.id end)
        if okc and id == 'ITEM_WEAPON_CROSSBOW' and not (f.forbid or f.garbage_collect or f.trader or f.removed
                or f.dump or f.owned or f.in_inventory or f.construction or f.hostile) then
            out.spare_crossbows = out.spare_crossbows + 1
        end
    end
    pcall(function()
        for _, it in ipairs(other.AMMO) do
            local f = it.flags
            local okc, id = pcall(function() return it.subtype.id end)
            if okc and id == 'ITEM_AMMO_BOLTS' and not (f.forbid or f.garbage_collect or f.trader or f.removed
                    or f.dump or f.hostile) then
                out.bolts = out.bolts + it:getStackSize()
            end
        end
    end)
    for _, it in ipairs(other.BAR) do
        local f = it.flags
        if not (f.forbid or f.garbage_collect or f.trader or f.removed or f.dump or f.in_job
                or f.construction or f.hostile) then
            local m = metal_token(it)
            if m and grade[m] then out.bars[m] = (out.bars[m] or 0) + it:getStackSize() end
            -- every metal (furniture can be made of silver, gold...)
            if m then
                out.all_bars = out.all_bars or {}
                out.all_bars[m] = (out.all_bars[m] or 0) + it:getStackSize()
            end
            -- pig iron: the step between iron and steel (not gear itself)
            if m == 'PIG_IRON' then out.pig_iron = (out.pig_iron or 0) + it:getStackSize() end
        end
    end
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Workshop and (b.type == df.workshop_type.MetalsmithsForge
                or b.type == df.workshop_type.MagmaForge) then
            out.forges = out.forges + 1
        end
    end
    return out
end

-- --- barracks -------------------------------------------------------------------
--
-- Barracks zones and the squads using them (zone.squad_room_info); a squad
-- given one to train in and keep its gear at (DFHack's
-- dfhack.military.updateRoomAssignments, as the zone's squad screen does).
-- Not to sleep in: soldiers keep their bedrooms.
BARRACKS_FLAGS = 2 + 4 + 8        -- squad_use_flags: train, indiv_eq, squad_eq

function barracks_report()
    local out = {}
    local okl, list = pcall(function() return df.global.world.buildings.other.ZONE_BARRACKS end)
    for _, b in ipairs(okl and list or {}) do
        local squads = {}
        pcall(function()
            for _, info in ipairs(b.squad_room_info) do table.insert(squads, info.squad_id) end
        end)
        table.insert(out, {id = b.id, squads = squads})
    end
    if #out == 0 then
        -- (older DFHack: no ZONE_BARRACKS list) any civzone of the barracks type
        pcall(function()
            for _, b in ipairs(df.global.world.buildings.other.ACTIVITY_ZONE) do
                if b.type == df.civzone_type.Barracks then
                    local squads = {}
                    for _, info in ipairs(b.squad_room_info) do table.insert(squads, info.squad_id) end
                    table.insert(out, {id = b.id, squads = squads})
                end
            end
        end)
    end
    return out
end

-- Archery ranges and the squads training there.
function ranges_report()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.ACTIVITY_ZONE) do
            if b.type == df.civzone_type.ArcheryRange then
                local squads = {}
                for _, info in ipairs(b.squad_room_info) do table.insert(squads, info.squad_id) end
                table.insert(out, {id = b.id, squads = squads})
            end
        end
    end)
    return out
end

function assign_barracks(squad_id, zone_id, dry_run)
    local sq = df.squad.find(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad'} end
    local zone = df.building.find(zone_id)
    local okz, ztype = pcall(function() return zone.type end)
    local range = okz and ztype == df.civzone_type.ArcheryRange
    if not zone or not okz or not (ztype == df.civzone_type.Barracks or range) then
        return {ok = false, rejected = true, error = 'that is not a barracks zone'}
    end
    for _, info in ipairs(zone.squad_room_info) do
        if info.squad_id == squad_id then return {ok = false, rejected = true, error = 'the squad already uses it'} end
    end
    if not (dfhack.military and dfhack.military.updateRoomAssignments) then
        return {ok = false, rejected = true, error = 'this DFHack has no updateRoomAssignments'}
    end
    if dry_run then return {ok = true, dry_run = true} end
    -- an archery range: to train there only
    local flags = range and 2 or BARRACKS_FLAGS
    local ok, err = pcall(dfhack.military.updateRoomAssignments, squad_id, zone_id, flags)
    if not ok then
        ok, err = pcall(dfhack.military.updateRoomAssignments, squad_id, zone_id,
                        range and {train = true} or {train = true, indiv_eq = true, squad_eq = true})
    end
    if not ok then return {ok = false, error = 'the game refused: ' .. tostring(err):sub(1, 160)} end
    for _, info in ipairs(zone.squad_room_info) do
        if info.squad_id == squad_id then return {ok = true, squad_id = squad_id, zone_id = zone_id} end
    end
    return {ok = false, error = 'the squad was not added to the barracks'}
end

-- --- the defence test (brain/defence_test.py, a test save only) ------------------------
--
-- A few hostile invaders set down outside, where they can walk to the fort:
-- on the trade depot's level, 15-30 tiles from it, on open ground outside
-- that has a path to the depot. Made by DFHack's modtools/create-unit, in an
-- enemy civilisation (a goblin one, else none) and flagged as invaders, so
-- the game and the AI treat them as an attack. Never during a real threat.

local function test_spot()
    local dep
    for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do dep = b break end
    local cx, cy, cz
    if dep then cx, cy, cz = dep.centerx, dep.centery, dep.z
    else
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            local okf, f = pcall(dfhack.maps.getTileFlags, x, y, z)
            if okf and f and f.outside then cx, cy, cz = x, y, z break end
        end
    end
    if not cx then return nil, 'no trade depot and no citizen outside to aim at' end
    local target = xyz2pos(cx, cy, cz)
    for r = 15, 30 do
        for _, d in ipairs({{r, 0}, {-r, 0}, {0, r}, {0, -r}, {r, r}, {-r, r}, {r, -r}, {-r, -r}}) do
            local x, y = cx + d[1], cy + d[2]
            local okf, f = pcall(dfhack.maps.getTileFlags, x, y, cz)
            if okf and f and f.outside and not f.hidden and f.flow_size == 0
                    and dfhack.maps.canWalkBetween(xyz2pos(x, y, cz), target) then
                return {x = x, y = y, z = cz}
            end
        end
    end
    return nil, 'no open ground 15-30 tiles from the depot with a path to it'
end

local function enemy_civ()
    for _, e in ipairs(df.global.world.entities.all) do
        local ok, code = pcall(function() return e.entity_raw.code end)
        if ok and code == 'EVIL' and e.type == df.historical_entity_type.Civilization then return e.id end
    end
    return nil
end

function spawn_test_threat(count, race, dry_run)
    count = math.max(1, math.min(10, count or 3))
    race = race or 'GOBLIN'
    for _, u in ipairs(df.global.world.units.active) do
        if dfhack.units.isActive(u) and not dfhack.units.isDead(u) and dfhack.units.isDanger(u)
                and not dfhack.units.isHidden(u) then
            return {ok = false, rejected = true, error = 'there is already a threat on the map: no test now'}
        end
    end
    local spot, why = test_spot()
    if not spot then return {ok = false, rejected = true, error = why} end
    local civ = enemy_civ()
    if dry_run then return {ok = true, dry_run = true, spot = spot, race = race, count = count, civ = civ} end
    local okm, cu = pcall(reqscript, 'modtools/create-unit')
    if not okm then return {ok = false, error = 'DFHack has no modtools/create-unit: ' .. tostring(cu):sub(1, 120)} end
    local before = {}
    for _, u in ipairs(df.global.world.units.active) do before[u.id] = true end
    local ok, err = pcall(cu.createUnit, race, nil, spot, {offset_x = 2, offset_y = 2, offset_z = 0}, 'Walkable',
                          nil, false, civ or -1, nil, nil, nil, nil, count, nil, nil, nil, nil,
                          {'marauder', 'active_invader', 'invader_origin'}, nil)
    if not ok then return {ok = false, error = 'create-unit failed: ' .. tostring(err):sub(1, 200)} end
    local made = {}
    for _, u in ipairs(df.global.world.units.active) do
        if not before[u.id] then table.insert(made, u.id) end
    end
    return {ok = true, spot = spot, race = race, count = #made, units = made, civ = civ}
end

-- Pull the lever named "AI gate" (a dwarf goes and pulls it).
function pull_gate(lever_id)
    for _, g in ipairs(gate_levers()) do
        if g.id == lever_id then
            if g.pending then return {ok = false, rejected = true, error = 'a pull is already on its way'} end
            local out, rv = dfhack.run_command_silent('lever', 'pull', '--id', tostring(lever_id))
            if rv ~= CR_OK then
                return {ok = false, error = 'lever pull failed: ' .. tostring(out):gsub('%s+$', '')}
            end
            return {ok = true, lever_id = lever_id}
        end
    end
    return {ok = false, rejected = true, error = 'no lever named "AI gate" with that id'}
end

-- For the self-test: what each soldier's uniform asks for, what the game
-- has assigned them, and what they carry (soldiers stayed unarmed with
-- axes and helms lying spare, y52: this shows where it breaks).
function probe_squads(txt)
    local out = {}
    local fort = fort_entity()
    if not fort then return out end
    for _, sid in ipairs(fort.squads) do
        local sq = df.squad.find(sid)
        if sq then
            for p, pos in ipairs(sq.positions) do
                local e = {squad = sid, place = p, uniform = {}, assigned = 0, carries = {}}
                pcall(function()
                    for cat = 0, df.uniform_category._last_item do
                        for _, spec in ipairs(pos.equipment.uniform[cat]) do
                            local sub = '?'
                            pcall(function()
                                local def = dfhack.items.getSubtypeDef(spec.item_type, spec.item_subtype)
                                sub = def and def.id or tostring(spec.item_subtype)
                            end)
                            local given = 0
                            pcall(function() given = #spec.assigned end)
                            table.insert(e.uniform, ('%s:%s mat%s/%s:%s%s given %d'):format(
                                df.item_type[spec.item_type] or '?', sub, tostring(spec.material_class),
                                tostring(spec.mattype), tostring(spec.matindex),
                                spec.indiv_choice.whole ~= 0 and ' choice' or '', given))
                        end
                    end
                end)
                pcall(function() e.assigned = #pos.equipment.assigned_items end)
                -- what the game assigned, and where it is (why it isn't picked up)
                -- (0.104.56) can the soldier walk to each, and what is the soldier doing
                local upos
                pcall(function()
                    local hf0 = df.historical_figure.find(pos.occupant)
                    local u0 = hf0 and df.unit.find(hf0.unit_id)
                    if u0 then
                        local ux, uy, uz = dfhack.units.getPosition(u0)
                        if ux then upos = xyz2pos(ux, uy, uz) end
                        if u0.job.current_job then e.job = df.job_type[u0.job.current_job.job_type] end
                        pcall(function() e.pickup = u0.military.pickup_flags.whole end)
                    end
                end)
                pcall(function()
                    e.assigned_items = {}
                    for _, iid in ipairs(pos.equipment.assigned_items) do
                        local it = df.item.find(iid)
                        if it then
                            local f, where = it.flags, {}
                            for _, k in ipairs({'forbid', 'in_inventory', 'in_building', 'container', 'trader',
                                                'dump', 'on_ground', 'in_job', 'owned', 'hostile'}) do
                                if f[k] then table.insert(where, k) end
                            end
                            local holder = dfhack.items.getHolderUnit(it)
                            local cont = dfhack.items.getContainer(it)
                            local x, y, z = dfhack.items.getPosition(it)
                            pcall(function()
                                if upos and x then
                                    table.insert(where, dfhack.maps.canWalkBetween(upos, xyz2pos(x, y, z)) and 'reach' or 'NO-REACH')
                                end
                            end)
                            table.insert(e.assigned_items, ('%s %s at %s,%s,%s [%s]%s%s'):format(
                                df.item_type[it:getType()] or '?',
                                (txt or tostring)(dfhack.items.getDescription(it, 0, true)),
                                tostring(x), tostring(y), tostring(z), table.concat(where, ' '),
                                holder and (' held by ' .. (txt or tostring)(dfhack.units.getReadableName(holder))) or '',
                                cont and (' in ' .. (txt or tostring)(dfhack.items.getDescription(cont, 0, true))) or ''))
                        else
                            table.insert(e.assigned_items, 'item ' .. tostring(iid) .. ' (gone)')
                        end
                    end
                end)
                pcall(function() e.flags = pos.equipment.flags.whole end)
                if pos.occupant ~= -1 then
                    local hf = df.historical_figure.find(pos.occupant)
                    local u = hf and df.unit.find(hf.unit_id)
                    if u then
                        e.name = (txt or tostring)(dfhack.units.getReadableName(u))
                        for _, inv in ipairs(u.inventory) do
                            table.insert(e.carries, ('%s(%s)'):format(df.item_type[inv.item:getType()] or '?',
                                inv_mode_name(inv.mode) or tostring(inv.mode)))
                        end
                    end
                end
                if e.name then table.insert(out, e) end
            end
        end
    end
    -- (0.81) a few spare weapons and helms, and why they might not be taken
    pcall(function()
        local spares = {}
        for _, kind in ipairs({'WEAPON', 'HELM'}) do
            local n = 0
            for _, it in ipairs(df.global.world.items.other[kind]) do
                if n >= 4 then break end
                if not it.flags.in_inventory and not it.flags.trader then
                    local f, where = it.flags, {}
                    for _, k in ipairs({'forbid', 'in_building', 'container', 'dump', 'on_ground', 'in_job',
                                        'owned', 'garbage_collect', 'construction'}) do
                        if f[k] then table.insert(where, k) end
                    end
                    local cont = dfhack.items.getContainer(it)
                    local x, y, z = dfhack.items.getPosition(it)
                    table.insert(spares, ('%s %s sub%s mat%s:%s at %s,%s,%s [%s]%s'):format(kind,
                        (txt or tostring)(dfhack.items.getDescription(it, 0, true)), tostring(it:getSubtype()),
                        tostring(it:getMaterial()), tostring(it:getMaterialIndex()), tostring(x), tostring(y),
                        tostring(z), table.concat(where, ' '),
                        cont and (' in ' .. (txt or tostring)(dfhack.items.getDescription(cont, 0, true))) or ''))
                    n = n + 1
                end
            end
        end
        if #out > 0 then out[1].spares = spares else table.insert(out, {spares = spares}) end
    end)
    -- (0.99.11) every battle axe and helm by its flags, and what holds it:
    -- no soldier was given an axe with 14 counted spare (region2, y68)
    pcall(function()
        local census = {}
        local function add(kind, it)
            local c = census[kind] or {n = 0, by_flags = {}, by_where = {}, by_mat = {}, sample = {}}
            census[kind] = c
            c.n = c.n + 1
            local f, set = it.flags, {}
            for _, k in ipairs({'forbid', 'in_inventory', 'in_building', 'container', 'trader', 'dump', 'on_ground',
                                'in_job', 'owned', 'garbage_collect', 'construction', 'artifact', 'melt',
                                'hidden', 'encased', 'removed', 'spider_web', 'hostile'}) do
                if f[k] then table.insert(set, k) end
            end
            local key = #set > 0 and table.concat(set, ' ') or '-'
            c.by_flags[key] = (c.by_flags[key] or 0) + 1
            local where = 'loose'
            local holder = dfhack.items.getHolderUnit(it)
            local cont = dfhack.items.getContainer(it)
            local bld = dfhack.items.getHolderBuilding(it)
            if holder then
                where = 'held by ' .. (dfhack.units.isCitizen(holder) and 'a citizen' or 'a non-citizen')
            elseif bld then
                where = 'in a ' .. tostring(df.building_type[bld:getType()])
            elseif cont then
                where = 'in a ' .. tostring(df.item_type[cont:getType()])
            end
            c.by_where[where] = (c.by_where[where] or 0) + 1
            local mi = dfhack.matinfo.decode(it)
            local m = mi and mi:getToken() or '?'
            c.by_mat[m] = (c.by_mat[m] or 0) + 1
            local ok_q, q = pcall(function() return it:getQuality() end)
            if #c.sample < 3 and not holder then
                local x, y, z = dfhack.items.getPosition(it)
                table.insert(c.sample, ('#%d %s q%s at %s,%s,%s [%s] %s'):format(it.id,
                    (txt or tostring)(dfhack.items.getDescription(it, 0, true)), ok_q and tostring(q) or '?',
                    tostring(x), tostring(y), tostring(z), key, where))
            end
        end
        for _, it in ipairs(df.global.world.items.other.WEAPON) do
            local ok, id = pcall(function() return it.subtype.id end)
            if ok and id == 'ITEM_WEAPON_AXE_BATTLE' then add('battle_axe', it) end
        end
        for _, it in ipairs(df.global.world.items.other.HELM) do add('helm', it) end
        if #out > 0 then out[1].census = census else table.insert(out, {census = census}) end
    end)
    -- (0.104.60) gear DF keeps on none of its equipment lists, against the
    -- gear it lists, by maker race, metal and flags, with a few samples: why
    -- 222 armour pieces were left off in Enxah (y74)
    pcall(function()
        local eq = equipment_lists()
        if not eq then return end
        local fort_race = df.global.plotinfo.race_id
        local res = {}
        for _, kind in ipairs({'ARMOR', 'HELM', 'PANTS', 'GLOVES', 'SHOES', 'SHIELD'}) do
            local asg, una = id_set(eq.items_assigned[kind]), id_set(eq.items_unassigned[kind])
            local okm, unm = pcall(function() return id_set(eq.items_unmanifested[kind]) end)
            unm = okm and unm or {}
            local r = {listed = {}, unlisted = {}, sample = {}}
            for _, it in ipairs(df.global.world.items.other[kind]) do
                local listed = asg[it.id] or una[it.id] or unm[it.id]
                local f, tags = it.flags, {}
                local okr, mr = pcall(function() return it:getMakerRace() end)
                tags[#tags + 1] = (okr and mr == fort_race) and 'ours' or ('race' .. tostring(okr and mr or '?'))
                tags[#tags + 1] = metal_token(it) and 'metal' or 'other'
                local held = false
                if f.in_inventory then
                    local okh, u = pcall(dfhack.items.getHolderUnit, it)
                    held = okh and u ~= nil
                end
                if held then tags[#tags + 1] = 'held' end
                for _, k in ipairs({'owned', 'forbid', 'trader', 'foreign', 'in_building', 'melt', 'dump',
                                    'garbage_collect', 'hostile', 'removed', 'container'}) do
                    local okf, v = pcall(function() return f[k] end)
                    if okf and v then tags[#tags + 1] = k end
                end
                local key = table.concat(tags, ' ')
                local side = listed and r.listed or r.unlisted
                side[key] = (side[key] or 0) + 1
                if not listed and not held and #r.sample < 4 then
                    local x, y, z = dfhack.items.getPosition(it)
                    local cont = dfhack.items.getContainer(it)
                    local okw, wear = pcall(function() return it.wear end)
                    table.insert(r.sample, ('#%d %s q%s wear %s at %s,%s,%s [%s]%s'):format(it.id,
                        (txt or tostring)(dfhack.items.getDescription(it, 0, true)), tostring(it:getQuality()),
                        okw and tostring(wear) or '?', tostring(x), tostring(y), tostring(z), key,
                        cont and (' in ' .. (txt or tostring)(dfhack.items.getDescription(cont, 0, true))) or ''))
                end
            end
            res[kind] = r
        end
        if #out > 0 then out[1].lists = res else table.insert(out, {lists = res}) end
    end)
    return out
end
