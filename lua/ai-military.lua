-- The AI's hands on the military: the fort's squads (made by the AI with a
-- captain's post when there are none: make_squad), filling them with
-- suitable dwarves and letting them go again, their routines, kill and
-- shelter orders, uniforms from the fort's templates, and the gear: stray
-- and stale gear handed back, weapons, quivers, bolts and kit given out, and
-- the reports on what each soldier still lacks.
--
-- Everything here can be undone: soldiers can be removed again, orders the
-- AI gives are marked as its own and only those are ever cleared, and only
-- a uniform the AI set is ever changed.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules
-- (13c) the gear half: lua/ai-military-gear.lua (see the end of this file)
-- (0.105.26) kept after the first lookup: reqscript finds the file again on
-- every call (5-7 file checks on Windows), and the forwarders below call it
-- for every name. One check of the file's time a call instead; when the file
-- changed, reqscript again, which reloads it. DFHack reloads a module into the
-- table it already has (its script environment is kept), so the one kept here
-- is the live module before and after a reload.
local GEAR, GEAR_PATH, GEAR_MTIME
local function gear()
    if GEAR then
        local ok, t = pcall(function() return dfhack.filesystem.mtime(GEAR_PATH) end)
        if ok and t ~= nil and t == GEAR_MTIME then return GEAR end
    end
    local m = reqscript('ai-military-gear')
    local okp, p = pcall(function() return dfhack.findScript('ai-military-gear') end)
    local okt, t = pcall(function() return dfhack.filesystem.mtime(p) end)
    GEAR, GEAR_PATH, GEAR_MTIME = m, okp and p or nil, okt and t or nil
    return m
end

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

-- (0.104.138) a dwarf who BADLY wants to fight or train (as `keen_civilians`
-- counts them) before one who merely wants it: an Axe Lord sent home slips
-- just past the wanting line in weeks and was drafted straight back over the
-- 70-200 keen ones (Teacheroar: 2,070 swaps, the same 20 dwarves 15-22 times)
KEEN_FOCUS = -10000

local function fight_focus(u)
    local ok, low = pcall(function()
        local lo
        for _, nd in ipairs(u.status.current_soul.personality.needs) do
            if FIGHT_NEEDS[df.need_type[nd.id]] and (lo == nil or nd.focus_level < lo) then lo = nd.focus_level end
        end
        return lo
    end)
    return ok and low or nil
end

function pick_soldiers(cands, n, avoid)
    local list = {}
    for _, c in ipairs(cands) do
        if not (avoid and avoid[c.id]) then table.insert(list, c) end
    end
    local function keen(c) return c.fight_focus ~= nil and c.fight_focus <= KEEN_FOCUS end
    table.sort(list, function(a, b)
        if keen(a) ~= keen(b) then return keen(a) end
        if keen(a) and a.fight_focus ~= b.fight_focus then return a.fight_focus < b.fight_focus end
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


function routine_names()
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

-- (0.105.0) The shelter: when the AI hides from a great danger the squads
-- hold the civilian alert's burrow with the civilians (shelter(), at the end
-- of this file). The burrows are read, never made (DFHack's civ-alert script
-- makes the alert entries when it is missing them).
function shelter_burrow_ids()
    local out = {}
    pcall(function()
        local l = df.global.plotinfo.alerts.list
        if #l >= 2 then
            for _, id in ipairs(l[1].burrows) do out[id] = true end
        end
    end)
    return out
end

-- (0.105.0 review) The AI's own shelter orders, marked when shelter() gives
-- them: squad id (text) -> the order's year_tick (true when unreadable),
-- kept in the site data. A defend order naming only the shelter burrows is
-- the AI's only when marked: a player's own shelter station counted as the
-- AI's and was recalled every quiet cycle (and replaced by kill orders).
SHELTER_KEY = 'ai-overseer/shelter'

function shelter_marks()
    return U.site_get(SHELTER_KEY, {})
end

local function save_shelter_marks(m)
    return U.site_put(SHELTER_KEY, m)
end

local function order_tick(o)
    local ok, t = pcall(function() return o.year_tick end)
    return (ok and type(t) == 'number') and t or true
end

-- a defend order on the shelter burrows only, given by shelter() to this
-- squad (squad_id nil: the burrows alone, for callers without the squad)
function is_shelter_order(o, squad_id, marks)
    local ok, yes = pcall(function()
        if not df.squad_order_defend_burrowsst:is_instance(o) or #o.burrows == 0 then return false end
        local sh = shelter_burrow_ids()
        for _, id in ipairs(o.burrows) do if not sh[id] then return false end end
        return true
    end)
    if not (ok and yes == true) then return false end
    if squad_id == nil then return true end
    local mark = (marks or shelter_marks())[tostring(squad_id)]       -- (0.105.0 review)
    if mark == nil then return false end
    return mark == true or mark == order_tick(o)
end

-- (0.105.0 review) marks whose squad no longer has its shelter order are dropped
function prune_shelter_marks()
    local m = shelter_marks()
    local changed = false
    for k in pairs(m) do
        local sq = df.squad.find(tonumber(k) or -1)
        local still = false
        for _, o in ipairs(sq and sq.orders or {}) do
            if is_shelter_order(o, k, m) then still = true end
        end
        if not still then m[k] = nil; changed = true end
    end
    if changed then save_shelter_marks(m) end
    return changed
end

-- (0.104.83) a defend order has no title: the AI's names only the gate guard burrow
local function is_guard_order(o)
    local okd, mine = pcall(function()
        if not df.squad_order_defend_burrowsst:is_instance(o) then return false end
        local gid = guard_burrow_id()
        return gid ~= nil and #o.burrows == 1 and o.burrows[0] == gid
    end)
    return okd and mine == true
end

local function is_ai_order(o, squad_id)
    local ok, title = pcall(function() return o.title end)
    if ok and title == AI_ORDER_TITLE then return true end
    if squad_id ~= nil and is_shelter_order(o, squad_id) then return true end   -- (0.105.0; review: marked only)
    return is_guard_order(o)
end

-- (0.105.24) Clearing an order the whole way. B (4 Nov): 7 squads recalled
-- from the shelter ("cleared": 1 each) and 28 soldiers still died of thirst
-- on one tile (x109 y153 z165) 20 minutes later. The recall took the order
-- off the squad's list and deleted it, but a squad's soldiers also carry
-- orders of their own (each squad_position.orders: the individual orders DF
-- hands out), which the recall never looked at: a copy there keeps a soldier
-- on it, and the very order pointed to there was left dangling once deleted.
-- Now, as DF's own "cancel orders" does, an order taken off the squad is taken
-- off every position too (the same object, or a copy: the same kind naming
-- the same burrows or targets) before it is deleted, each step in a pcall.
local function same_obj(a, b)
    if rawequal(a, b) then return true end
    local ok, eq = pcall(function() return a == b end)
    if ok and eq == true then return true end
    local oka, _, pa = pcall(df.sizeof, a)
    local okb, _, pb = pcall(df.sizeof, b)
    return oka and okb and pa ~= nil and pa == pb
end

-- the kind of an order and what it names, e.g. 'defend:5,9' or 'kill:1203'
-- (nil when it can't be read)
function order_sig(o)
    local ok, s = pcall(function()
        local list, kind
        if df.squad_order_defend_burrowsst:is_instance(o) then kind, list = 'defend', o.burrows
        elseif df.squad_order_kill_listst and df.squad_order_kill_listst:is_instance(o) then kind, list = 'kill', o.units
        else return nil end
        local ids = {}
        for _, id in ipairs(list) do table.insert(ids, id) end
        table.sort(ids)
        return kind .. ':' .. table.concat(ids, ',')
    end)
    return ok and s or nil
end

-- the positions' own orders that are `removed` (objects) or copies of them
-- (their sigs) taken off; deleted unless they were one of `removed` (those
-- the caller deletes once). Returns how many.
local function clear_position_orders(sq, removed, sigs)
    local n = 0
    pcall(function()
        for _, pos in ipairs(sq.positions) do
            local po = pos.orders
            if po ~= nil then
                for j = #po - 1, 0, -1 do
                    local o = po[j]
                    local mine = false
                    for _, r in ipairs(removed) do if same_obj(o, r) then mine = 'same' end end
                    if not mine then
                        local s = order_sig(o)
                        if s and sigs[s] then mine = 'copy' end
                    end
                    if mine then
                        local oke = pcall(function() po:erase(j) end)
                        if oke then
                            n = n + 1
                            if mine == 'copy' then pcall(function() o:delete() end) end
                        end
                    end
                end
            end
        end
    end)
    return n
end

-- Takes the squad's orders that `pick(o)` says off it, off its soldiers'
-- own lists too, then deletes them. Returns removed, members' orders cleared.
function drop_orders(sq, pick)
    local removed, sigs = {}, {}
    for i = #sq.orders - 1, 0, -1 do
        local o = sq.orders[i]
        if pick(o) then
            sq.orders:erase(i)
            table.insert(removed, o)
            local s = order_sig(o)
            if s then sigs[s] = true end
        end
    end
    local member = #removed > 0 and clear_position_orders(sq, removed, sigs) or 0
    for _, o in ipairs(removed) do pcall(function() o:delete() end) end
    return #removed, member
end

-- (0.105.24) The squad's soldiers: how many, how many are thirsty or hungry
-- (the hospital burrow's marks, ai-society HOSP_THIRST/HOSP_HUNGER), and how
-- many orders of their own they still hold. {n, parched?, own_orders?}
SHELTER_THIRST = 25000       -- DFHack's "thirsty"
SHELTER_HUNGER = 50000       -- DF's "hungry"

function members_state(sq)
    local n, parched, own = 0, 0, 0
    for _, pos in ipairs(sq.positions) do
        if pos.occupant ~= -1 then
            n = n + 1
            pcall(function() own = own + #pos.orders end)
            pcall(function()
                local hf = df.historical_figure.find(pos.occupant)
                local u = hf and df.unit.find(hf.unit_id)
                local c = u and u.counters2
                if c and (c.thirst_timer >= SHELTER_THIRST or c.hunger_timer >= SHELTER_HUNGER) then
                    parched = parched + 1
                end
            end)
        end
    end
    return {n = n, parched = parched > 0 and parched or nil, own_orders = own > 0 and own or nil}
end

function fort_squad(squad_id)
    local fort = U.fort_entity()
    if not fort then return nil end
    for _, sid in ipairs(fort.squads) do
        if sid == squad_id then return df.squad.find(sid) end
    end
    return nil
end

-- (0.105.36) Is what a lever works shut now? true/false from the linked
-- buildings themselves (a bridge raised, a door, hatch, floodgate or bars
-- closed), nil when one can't be read or they disagree. The brain no longer
-- has to guess the shut state from the lever's position the first time it
-- sees it (a gate the player had shut was learnt as "open", and opened).
local function lever_shut(b)
    local shut
    for _, mech in ipairs(b.linked_mechanisms) do
        local tid
        for _, ref in ipairs(mech.general_refs or {}) do
            local t = ref:getType()
            if t == df.general_ref_type.BUILDING_HOLDER or t == df.general_ref_type.BUILDING_TRIGGERTARGET then
                if ref.building_id ~= b.id then tid = ref.building_id break end
            end
        end
        local t = tid and df.building.find(tid)
        if not t then return nil end
        local c
        if df.building_bridgest:is_instance(t) then
            local ok, v = pcall(function() return t.gate_flags.raised end)
            if ok then c = v end
        else
            local ok, v = pcall(function() return t.door_flags.closed end)
            if not ok then ok, v = pcall(function() return t.gate_flags.closed end) end
            if ok then c = v end
        end
        if type(c) ~= 'boolean' then return nil end
        if shut ~= nil and shut ~= c then return nil end
        shut = c
    end
    return shut
end

function gate_levers()
    local out = {}
    for _, b in ipairs(df.global.world.buildings.other.TRAP) do
        if b.trap_type == df.trap_type.Lever and tostring(b.name or ''):lower() == GATE_NAME then
            local ok, shut = pcall(lever_shut, b)
            if not ok then shut = nil end
            table.insert(out, {id = b.id, state = b.state, linked = #b.linked_mechanisms,
                               pending = #b.jobs > 0, x = b.centerx, y = b.centery, z = b.z,
                               shut = shut})
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
    local power, armored, skill_sum, n, armed = 0, 0, 0, 0, 0
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
            -- (0.105.2) armed: a weapon in hand or one given on a weapon entry
            -- (an entry's weapon may still lie elsewhere: armed means "has
            -- one coming", which the gear fix makes true)
            -- (B's squads went at a thief with none: four sent, the thief lived)
            local has_weapon = false
            pcall(function()
                for _, inv in ipairs(u.inventory) do
                    if inv.item:getType() == df.item_type.WEAPON then
                        local def = weapon_def(inv.item)
                        local id = def and def.id or ''
                        if id ~= 'ITEM_WEAPON_PICK' and not id:find('_TRAINING', 1, true) then has_weapon = true end
                    end
                end
            end)
            if not has_weapon then
                pcall(function()
                    for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                        if #spec.assigned > 0 then has_weapon = true end
                    end
                end)
            end
            pcall(function()
                for _, inv in ipairs(u.inventory) do
                    -- (0.104.139) real armour only: shirts, coats and cloaks are
                    -- ARMOR items too, so every clothed dwarf counted as armoured
                    if inv.mode == WORN_MODE and inv.item:getType() == df.item_type.ARMOR then
                        local okl, lvl = pcall(function() return inv.item.subtype.armorlevel end)
                        if okl and (lvl or 0) > 0 then arm = true end
                    end
                end
            end)
            -- (0.104.139) DF's own hospital flag: the wound list holds old scars too
            local okw, wounded = pcall(function() return u.health ~= nil and u.health.flags.needs_healthcare end)
            local p = (1 + math.min(best, 20) / 3) * (arm and 1.5 or 1) * ((okw and wounded) and 0.5 or 1)
                      * (has_weapon and 1 or 0.4)
            power, n, skill_sum = power + p, n + 1, skill_sum + best
            if arm then armored = armored + 1 end
            if has_weapon then armed = armed + 1 end
        end
    end
    return {power = math.floor(power * 10 + 0.5) / 10, armored = armored, armed = armed,
            skill = n > 0 and math.floor(skill_sum / n * 10 + 0.5) / 10 or 0}
end

function report(txt)
    local routines = routine_names()
    local out = {squads = {}, soldiers = 0, routines = routines, gates = {}}
    pcall(prune_shelter_marks)          -- (0.105.0 review) the shelter orders gone: unmarked
    local fort = U.fort_entity()
    local ai_names = ai_uniform_names(txt)      -- (13c) read once, not once a squad
    if fort then
        for _, sid in ipairs(fort.squads) do
            local sq = df.squad.find(sid)
            if sq then
                local members = 0
                for _, pos in ipairs(sq.positions) do
                    if pos.occupant ~= -1 then members = members + 1 end
                end
                local ai_orders, guarding = 0, false
                local kill_ids, sheltering = nil, nil
                for _, o in ipairs(sq.orders) do
                    if is_ai_order(o, sid) then
                        ai_orders = ai_orders + 1
                        -- (0.104.140) who the AI's kill order names: a second wave
                        -- gets an order of its own (the first one's list was kept)
                        pcall(function()
                            if df.squad_order_kill_listst:is_instance(o) then
                                kill_ids = kill_ids or {}
                                for _, id in ipairs(o.units) do table.insert(kill_ids, id) end
                            end
                        end)
                        -- (0.104.83) holding the gate rather than out to kill
                        -- (0.105.0 review: the gate guard burrow only, not the shelter)
                        if is_guard_order(o) then guarding = true end
                        -- (0.105.0) in the shelter with the civilians (the AI hides)
                        if is_shelter_order(o, sid) then sheltering = true end
                    end
                end
                local ok, idx = pcall(function() return sq.cur_routine_idx end)
                -- (0.105.24) soldiers thirsty or hungry (a sheltered squad is let out)
                local okm, ms = pcall(members_state, sq)
                table.insert(out.squads, {
                    parched = okm and ms and ms.parched or nil,
                    id = sid, name = txt(dfhack.military.getSquadName(sid)),
                    members = members, size = #sq.positions,
                    leader = #sq.positions > 0 and sq.positions[0].occupant ~= -1,
                    routine = ok and routines[idx + 1] or nil,
                    orders = #sq.orders, ai_orders = ai_orders, guarding = guarding or nil, kill_ids = kill_ids,
                    sheltering = sheltering,         -- (0.105.0)
                    -- (0.105.0) a crossbow squad's bolts: entries, wanted, assigned
                    ammo = (function() local oka, a = pcall(squad_ammo, sq) return oka and a or nil end)(),
                    uniform = #sq.positions > 0 and uniform_set(sq.positions[0]) or false,
                    ai_uniform = ai_names[tostring(sid)],
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
    -- (0.105.26) the alarm is on and an entrance shut when the AI's shelter
    -- was made is open now (its gate broken, or a building destroyer at it):
    -- the planner has the shelter made again (refresh_shelter)
    pcall(function()
        local n = reqscript('ai-society').shelter_stale()
        if type(n) == 'number' and n > 0 then out.shelter_stale = n end
    end)
    -- (0.104.159) soldiers with a baby (drafted before it came): {id, name, leader}
    pcall(function()
        local mothers = nursing_mothers()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            if mothers[u.id] and u.military.squad_id ~= -1 then
                out.soldier_mothers = out.soldier_mothers or {}
                table.insert(out.soldier_mothers, {id = u.id, name = (txt or tostring)(dfhack.units.getReadableName(u)),
                                                   leader = u.military.squad_position == 0 or nil})
            end
        end
    end)
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
function draftable(u, mothers, strict)
    local ok, yes = pcall(function()
        return dfhack.units.isAdult(u) and u.military.squad_id == -1 and not mothers[u.id]
            and not breaking_down(u, strict)
            and #(dfhack.units.getNoblePositions(u) or {}) == 0
            and not (u.health and u.health.flags.needs_healthcare)
    end)
    return ok and yes == true
end

local function candidates(strict)
    local out = {}
    local mothers = nursing_mothers()
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if draftable(u, mothers, strict) then
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
            table.insert(out, {id = u.id, combat = combat, best_craft = best, unit = u, wants_fight = wants_fight(u),
                               fight_focus = fight_focus(u)})
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
    local fort = U.fort_entity()
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
    local added = {}
    local tried, k = 0, 1
    for _, c in ipairs(pick_soldiers(cands, count, avoid)) do
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
    local fort = U.fort_entity()
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
-- `mother`: (0.104.159) a soldier with a baby goes home whatever she longs
-- for (the baby is carried into every fight); only a squad leader stays.
function release(unit_id, dry_run, txt, mother)
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
    if wants_fight(u) and not mother then return {ok = false, rejected = true, error = 'longs to fight or train: the squad is what meets that'} end
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

function make_squad(dry_run, txt)
    local fort = U.fort_entity()
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
            U.site_put(UNIFORMS_KEY, mine)
        end
    end
    return {ok = true, squad_id = sq.id, office = office, leader = name, appointed = appointed or nil, seated = seated,
            new_post = new_post and true or nil,
            uniform = uniform, uniform_from = from and txt and txt(dfhack.military.getSquadName(from.id)) or nil}
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
uniform_set = position_has_uniform       -- (for make_squad and the report, defined above this)

-- For brain/selftest.py: the field names of a squad and one of its
-- positions, to see where this DF version keeps uniforms.
function probe()
    local fort = U.fort_entity()
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

-- --- uniforms from the fort's templates ----------------------------------------

-- A squad without a uniform fights in its clothes and the armour the fort
-- makes is never handed out. The fort has uniform templates (DF's military
-- screen: "Melee, leather armor", "Melee, metal armor", ...); the AI gives
-- such a squad one of them, as the screen's "apply uniform" does: each
-- template entry becomes a uniform entry on every place in the squad. A
-- squad the AI gave a uniform to may later be moved to a better one (leather
-- to metal); a uniform you set yourself is never touched.
-- (UNIFORMS_KEY and ai_uniforms() are defined above make_squad)

-- (0.105.33 review) Pure: a template's name says crossbows. One test for
-- pick_template and set_uniform (a fort with only a "Ranged" template was
-- picked it, then refused it: "no crossbow uniform template").
function ranged_template_name(name)
    local l = tostring(name):lower()
    return l:find('crossbow', 1, true) ~= nil or l:find('archer', 1, true) ~= nil or l:find('ranged', 1, true) ~= nil
end

-- Pure: the template to use from their names. kind 'metal' or 'leather';
-- melee before crossbows; else the first one.
function pick_template(names, kind, ranged)
    local best, best_score
    for i, n in ipairs(names) do
        local l = tostring(n):lower()
        local score = 0
        if l:find(kind or 'leather', 1, true) then score = score + 2 end
        if ranged then
            if ranged_template_name(l) then
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
    local n, rc_err = 0, nil
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
        -- (13c) a DF without the flag: said in the result (it was silently skipped)
        local okr, err = pcall(function() pos.equipment.flags.replace_clothing = true end)
        if not okr then rc_err = tostring(err):sub(1, 120) end
        pcall(function() pos.equipment.nickname = uf.name end)
    end
    for _, f in ipairs({'weapon', 'armor', 'shoes', 'shield', 'helm', 'gloves', 'ammo', 'pants'}) do
        pcall(function()
            sq.ammo.update[f] = true
            df.global.plotinfo.equipment.update[f] = true
        end)
    end
    return n, rc_err
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
                -- (13c) read and set directly: a DF without the flag raises an
                -- error the unstick action reports (the pcalls here hid it, and
                -- the count said 0)
                if not pos.equipment.flags.replace_clothing then
                    if not dry_run then pos.equipment.flags.replace_clothing = true end
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
    local fort = U.fort_entity()
    if not fort or #fort.uniforms == 0 then
        return {ok = false, rejected = true, error = 'the fort has no uniform templates (make one in the military screen)'}
    end
    local names = {}
    for i, uf in ipairs(fort.uniforms) do names[i + 1] = uf.name end
    local idx = pick_template(names, kind, ranged)
    local uf = fort.uniforms[idx - 1]
    if ranged and not ranged_template_name(uf.name) then
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
    local n, rc_err = apply_template(uf, sq)
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
    U.site_put(UNIFORMS_KEY, mine)
    local bolts
    if ranged then
        bolts = BOLTS_PER_SOLDIER * math.max(1, #sq.positions)
        local okb, err = set_bolts(sq, bolts)
        if not okb then bolts = 'not set: ' .. tostring(err) end
    end
    return {ok = true, template = name, items = n, replaced = had or nil, bolts = bolts, bolts_cleared = cleared,
            replace_clothing_error = rc_err}
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
    U.site_put(UNIFORMS_KEY, mine)
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
    local fort = U.fort_entity()
    local names = {}
    for i, uf in ipairs(fort and fort.uniforms or {}) do names[i + 1] = uf.name end
    if #names == 0 then return {ok = false, rejected = true, error = 'the fort has no uniform templates'} end
    local name = names[pick_template(names, metal and 'metal' or 'leather', ranged)]
    local entry = name .. (weapon and (' |weapon:' .. weapon) or '')
    if dry_run then return {ok = true, dry_run = true, uniform = entry} end
    mine[key] = entry
    U.site_put(UNIFORMS_KEY, mine)
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
    -- (0.104.140) a citizen changed into a beast (a werebeast) for now
    local okc, changed = pcall(function()
        return u.enemy.normal_race ~= -1 and u.enemy.normal_race ~= u.race
            and (u.enemy.were_race == nil or u.enemy.were_race == -1 or u.race == u.enemy.were_race)
    end)
    if okc and changed then return true end
    if is(U.isMerchant) or is(U.isDiplomat) or is(U.isTame) then return false end
    if is(U.isCitizen) then return false end
    return is(U.isDanger) or is(U.isInvader)
end

-- Kill orders against the given units (only ones actually on the map), or
-- clear the orders the AI gave before. The player's own orders are kept.
function orders(squad_id, kill, clear)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    -- (0.105.24) off the soldiers' own order lists too (drop_orders)
    local function drop()
        local removed, member = drop_orders(sq, function(o) return is_ai_order(o, squad_id) end)
        if removed > 0 then pcall(prune_shelter_marks) end      -- (0.105.0 review)
        return removed, member
    end
    if clear then
        local removed, member = drop()
        local out = {ok = true, cleared = removed, member_orders = member > 0 and member or nil}
        -- (0.105.24) what the soldiers are left doing, for the next live look
        local okm, m = pcall(members_state, sq)
        if okm and m then out.members = m end
        return out
    end
    -- (0.105.33 review) the targets are checked BEFORE the AI's orders come
    -- off: a refused kill list leaves the shelter / gate order standing.
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
    local removed = drop()
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
        if not is_ai_order(o, squad_id) then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
    end
    for _, o in ipairs(sq.orders) do
        -- (0.105.33 review) a shelter order is a defend order too: only the
        -- gate guard order means the squad already holds the gate
        if is_ai_order(o, squad_id) and is_guard_order(o) then
            return {ok = false, rejected = true, error = 'the squad already holds the gate'}
        end
    end
    -- (0.105.24) off the soldiers' own order lists too (drop_orders)
    local removed = drop_orders(sq, function(o) return is_ai_order(o, squad_id) end)
    local o = df.squad_order_defend_burrowsst:new()
    o.burrows:insert('#', burrow_id)
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    return {ok = true, burrow_id = burrow_id, replaced = removed}
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
    local fort = U.fort_entity()
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
                                gear().inv_mode_name(inv.mode) or tostring(inv.mode)))
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
        local eq = gear().equipment_lists()
        if not eq then return end
        local fort_race = df.global.plotinfo.race_id
        local res = {}
        for _, kind in ipairs({'ARMOR', 'HELM', 'PANTS', 'GLOVES', 'SHOES', 'SHIELD'}) do
            local asg, una = gear().id_set(eq.items_assigned[kind]), gear().id_set(eq.items_unassigned[kind])
            local okm, unm = pcall(function() return gear().id_set(eq.items_unmanifested[kind]) end)
            unm = okm and unm or {}
            local r = {listed = {}, unlisted = {}, sample = {}}
            for _, it in ipairs(df.global.world.items.other[kind]) do
                local listed = asg[it.id] or una[it.id] or unm[it.id]
                local f, tags = it.flags, {}
                local okr, mr = pcall(function() return it:getMakerRace() end)
                tags[#tags + 1] = (okr and mr == fort_race) and 'ours' or ('race' .. tostring(okr and mr or '?'))
                tags[#tags + 1] = gear().metal_token(it) and 'metal' or 'other'
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

-- The shelter: the squad holds the civilian alert's burrow(s), the AI's
-- orders on it replaced (a squad on the player's orders: refused).
function shelter(squad_id, dry_run)
    local sq = fort_squad(squad_id)
    if not sq then return {ok = false, rejected = true, error = 'no such squad in this fort'} end
    local ids = {}
    for id in pairs(shelter_burrow_ids()) do table.insert(ids, id) end
    table.sort(ids)
    if #ids == 0 then return {ok = false, rejected = true, error = 'no civilian-alert burrow to shelter in'} end
    for _, o in ipairs(sq.orders) do
        if not is_ai_order(o, squad_id) then return {ok = false, rejected = true, error = 'the squad is on your orders'} end
        if is_shelter_order(o, squad_id) then return {ok = false, rejected = true, error = 'the squad is in the shelter already'} end
    end
    -- (0.105.24) thirsty or hungry soldiers are not shut in (as the hospital
    -- burrow, 0.105.22): they drink and eat first
    local okm, m = pcall(members_state, sq)
    if okm and m and (m.parched or 0) > 0 then
        return {ok = false, rejected = true, parched = m.parched,
                error = ('%d of its soldiers are thirsty or hungry: they eat and drink first'):format(m.parched)}
    end
    if dry_run then return {ok = true, dry_run = true, burrows = #ids} end
    -- (0.105.24) off the soldiers' own order lists too (drop_orders)
    local removed = drop_orders(sq, function() return true end)
    -- (0.105.24) the squad's supplies: soldiers on the shelter order carry
    -- food and water (DFHack's makeSquad gives a squad carry_food 2 and
    -- carry_water 1; a squad set to carry none is set so), so a long hold
    -- doesn't keep them from drink
    local supplies
    pcall(function()
        if sq.carry_water == 0 then sq.carry_water = 1; supplies = 'water' end
    end)
    pcall(function()
        if sq.carry_food == 0 then sq.carry_food = 2; supplies = supplies and (supplies .. ', food') or 'food' end
    end)
    local o = df.squad_order_defend_burrowsst:new()
    for _, id in ipairs(ids) do o.burrows:insert('#', id) end
    pcall(function() o.year = df.global.cur_year; o.year_tick = df.global.cur_year_tick end)
    sq.orders:insert('#', o)
    -- (0.105.0 review) marked as the AI's, with the site data
    local marks = shelter_marks()
    marks[tostring(squad_id)] = order_tick(o)
    save_shelter_marks(marks)
    return {ok = true, burrows = #ids, replaced = removed, supplies = supplies}
end

-- --- the gear (lua/ai-military-gear.lua) ------------------------------------------
--
-- (13c) The gear half of this file moved there; every name it exports is
-- still reachable here (the bridge, ai-society and ai-threats call them as
-- reqscript('ai-military').<name>). Looked up on call: that module loads
-- this one, so this one must not load it while loading (gear(), at the top).
for _, name in ipairs({'stray_report', 'free_stray_gear', 'weapon_gaps', 'fix_weapon_colours', 'weapon_def',
                       'weapon_is_ranged', 'weapon_fits', 'assign_weapons', 'gear_report', 'gaps_why',
                       'quiver_report', 'assign_quivers', 'squad_ammo', 'squad_bolts', 'unforbid_spares',
                       'fix_gear_gaps', 'kit_report', 'assign_kit', 'army_gear', 'flask_report'}) do
    _ENV[name] = function(...) return gear()[name](...) end
end
