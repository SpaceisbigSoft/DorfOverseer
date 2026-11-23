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

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
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

-- (r2h4) `ranged`: places in a crossbow squad: among the keen alike (and the
-- rest alike), a dwarf with crossbow or bow skill (`rskill`) first, the most
-- skilled first (A, C, D, E's crossbow squads were filled by melee skill)
function pick_soldiers(cands, n, avoid, ranged)
    local list = {}
    for _, c in ipairs(cands) do
        if not (avoid and avoid[c.id]) then table.insert(list, c) end
    end
    local function keen(c) return c.fight_focus ~= nil and c.fight_focus <= KEEN_FOCUS end
    table.sort(list, function(a, b)
        if keen(a) ~= keen(b) then return keen(a) end
        if keen(a) and a.fight_focus ~= b.fight_focus then return a.fight_focus < b.fight_focus end
        if ranged and (a.rskill or 0) ~= (b.rskill or 0) then return (a.rskill or 0) > (b.rskill or 0) end
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

-- (item5) the archer post behind an entrance's fortifications (lua/ai-siege.lua):
-- a defend order on it is the AI's too, held like the gate guard's
ARCHER_POST_NAME = 'AI archer post'
local function archer_post_id()
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if b.name == ARCHER_POST_NAME then return b.id end
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
        if #o.burrows ~= 1 then return false end
        local gid = guard_burrow_id()
        if gid ~= nil and o.burrows[0] == gid then return true end
        local pid = archer_post_id()           -- (item5) the archer post
        return pid ~= nil and o.burrows[0] == pid
    end)
    return okd and mine == true
end

local function is_ai_order(o, squad_id)
    local ok, title = pcall(function() return o.title end)
    if ok and title == AI_ORDER_TITLE then return true end
    if squad_id ~= nil and is_shelter_order(o, squad_id) then return true end   -- (0.105.0; review: marked only)
    -- (0.105.48 K1b) a station (move) order has no title in DF 53.17
    -- (squad_order_movest: pos and point_id only): the AI's is known by the
    -- site mark and the same position (station_of, below; looked up on call)
    if squad_id ~= nil then
        local oks, st = pcall(station_of, o, squad_id)
        if oks and st then return true end
    end
    return is_guard_order(o)
end

-- (0.105.45) is_ai_order for other modules (lua/ai-hunt.lua: a squad on the
-- player's own orders is not sent hunting)
function ai_order(o, squad_id) return is_ai_order(o, squad_id) end

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
        elseif df.squad_order_movest and df.squad_order_movest:is_instance(o) then
            -- (0.105.48 K1b) a station order: its tile
            return ('move:%d,%d,%d'):format(o.pos.x, o.pos.y, o.pos.z)
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

-- (0.104.118) A squad's fighting strength, for fight or hide.
-- (0.105.45, Phase 11 (a)) Each soldier's facts and the formula (the brain
-- weighs melee against ranged by the threat: brain/planner_matchup.py):
--   base   = 1 + (best skill, at most 20) / 3      (melee or ranged skill)
--   armour = 1 + 0.5 x coverage, coverage the share of body 0.4, helm 0.15,
--            legs 0.15, feet 0.05, hands 0.05, shield 0.2 worn (real armour:
--            armour level above 0; a full set 1.5, the old "armoured" x1.5)
--   well   = x0.5 wounded (DF's hospital flag), x0.85 tired (exhaustion 2000+)
--   melee  = base x armour x well x the weapon's class (adamantine 1.4,
--            steel 1.25, iron 1.1, bronze 1.05, other metal 0.95, copper 0.85,
--            bone 0.7, stone 0.6, wood 0.55; not known 1.0), x0.4 unarmed
--   ranged = a soldier with a ranged weapon: base (ranged skill) x armour x
--            well, x0.15 with no ammunition in the quiver; and 0.3 of his
--            melee base to melee (he bashes with it)
-- power = melee_power + ranged_power (the total the old callers read).
-- {power, melee_power, ranged_power, armored, armed, skill (average best),
--  ranged (soldiers shooting with ammo), coverage (average), weapons
--  {class = n}, wounded, tired}.
local FIGHT_SKILLS = {'AXE', 'SWORD', 'MACE', 'HAMMER', 'SPEAR', 'PIKE', 'WHIP', 'DAGGER', 'CROSSBOW', 'BOW',
                      'BLOWGUN', 'WRESTLING'}
RANGED_SKILLS = {CROSSBOW = true, BOW = true, BLOWGUN = true}
-- the "worn" inventory mode's number (its enum moved between DFHack versions)
WORN_MODE = (function()
    for _, get in ipairs({function() return df.inv_item_role_type.Worn end,
                          function() return df.unit_inventory_item.T_mode.Worn end}) do
        local ok, v = pcall(get)
        if ok and v ~= nil then return v end
    end
    return 2
end)()
ARMOR_SLOTS = {HELM = 'helm', ARMOR = 'body', PANTS = 'legs', SHOES = 'feet', GLOVES = 'hands', SHIELD = 'shield'}
COVER_WEIGHT = {body = 0.4, helm = 0.15, legs = 0.15, feet = 0.05, hands = 0.05, shield = 0.2}
WEAPON_CLASS_MULT = {adamantine = 1.4, steel = 1.25, iron = 1.1, bronze = 1.05, metal = 0.95, copper = 0.85,
                     bone = 0.7, stone = 0.6, wood = 0.55, unknown = 1.0}
TIRED_EXHAUSTION = 2000

-- (0.105.45) a weapon's class from its material: mode ('inorganic',
-- 'creature', 'plant'), the material's id (STEEL, BONE, WOOD) and whether
-- it's a metal
function weapon_class(mode, id, metal)
    id = tostring(id or ''):upper()
    if mode == 'inorganic' then
        if id == 'ADAMANTINE' then return 'adamantine' end
        if id == 'STEEL' then return 'steel' end
        if id == 'IRON' or id == 'PIG_IRON' or id == 'WROUGHT_IRON' then return 'iron' end
        if id:find('BRONZE') then return 'bronze' end
        if id == 'COPPER' then return 'copper' end
        return metal and 'metal' or 'stone'
    end
    if mode == 'creature' then return (id:find('WOOD') and 'wood') or 'bone' end
    if mode == 'plant' then return 'wood' end
    return 'unknown'
end

-- (0.105.45) the share of the body covered: slots = {body = true, ...}
function coverage(slots)
    local c = 0
    for k, w in pairs(COVER_WEIGHT) do if slots and slots[k] then c = c + w end end
    return math.floor(math.min(1, c) * 100 + 0.5) / 100
end

-- (0.105.45) one soldier's (melee, ranged) power from his facts: {skill
-- (best melee), rskill (best ranged), has_weapon, ranged (holds a ranged
-- weapon), ammo (count), slots, wclass, wounded, tired}
function soldier_power(f)
    local arm = 1 + 0.5 * coverage(f.slots)
    local well = (f.wounded and 0.5 or 1) * (f.tired and 0.85 or 1)
    local mbase = 1 + math.min(f.skill or 0, 20) / 3
    if f.ranged then
        local r = (1 + math.min(f.rskill or 0, 20) / 3) * arm * well * (((f.ammo or 0) > 0) and 1 or 0.15)
        return 0.3 * mbase * arm * well, r
    end
    local wm = f.has_weapon and (WEAPON_CLASS_MULT[f.wclass or 'unknown'] or 1) or 0.4
    return mbase * arm * well * wm, 0
end

local function soldier_facts(u, pos)
    local f = {skill = 0, rskill = 0, slots = {}, ammo = 0}
    for _, k in ipairs(FIGHT_SKILLS) do
        local ok, v = pcall(dfhack.units.getNominalSkill, u, df.job_skill[k], true)
        if ok and v then
            if RANGED_SKILLS[k] then f.rskill = math.max(f.rskill, v) else f.skill = math.max(f.skill, v) end
        end
    end
    -- (0.105.2) armed: a weapon in hand or one given on a weapon entry
    -- (an entry's weapon may still lie elsewhere: armed means "has
    -- one coming", which the gear fix makes true)
    -- (B's squads went at a thief with none: four sent, the thief lived)
    pcall(function()
        for _, inv in ipairs(u.inventory) do
            local it = inv.item
            local ty = it:getType()
            if ty == df.item_type.WEAPON then
                local def = weapon_def(it)
                local id = def and def.id or ''
                if id ~= 'ITEM_WEAPON_PICK' and not id:find('_TRAINING', 1, true) then
                    f.has_weapon = true
                    if weapon_is_ranged(def) then f.ranged = true end
                    pcall(function()
                        local mi = dfhack.matinfo.decode(it)
                        local mode = mi.inorganic and 'inorganic' or mi.creature and 'creature' or mi.plant and 'plant'
                        local cls = weapon_class(mode, mi.inorganic and mi.inorganic.id or mi.material.id,
                                                 mi.material.flags.IS_METAL)
                        if not f.wclass or (WEAPON_CLASS_MULT[cls] or 1) > (WEAPON_CLASS_MULT[f.wclass] or 1) then
                            f.wclass = cls
                        end
                    end)
                end
            elseif ty == df.item_type.QUIVER then
                pcall(function()
                    for _, a in ipairs(dfhack.items.getContainedItems(it)) do
                        if a:getType() == df.item_type.AMMO then f.ammo = f.ammo + (a.stack_size or 1) end
                    end
                end)
            else
                local slot = ARMOR_SLOTS[df.item_type[ty] or '']
                if slot == 'shield' then
                    f.slots.shield = true
                elseif slot and inv.mode == WORN_MODE then
                    -- (0.104.139) real armour only: shirts, coats and cloaks are
                    -- ARMOR items too, so every clothed dwarf counted as armoured
                    local okl, lvl = pcall(function() return it.subtype.armorlevel end)
                    if okl and (lvl or 0) > 0 then f.slots[slot] = true end
                end
            end
        end
    end)
    if not f.has_weapon then
        pcall(function()
            for _, spec in ipairs(pos.equipment.uniform[df.uniform_category.weapon]) do
                if #spec.assigned > 0 then f.has_weapon = true end
            end
        end)
    end
    -- (0.104.139) DF's own hospital flag: the wound list holds old scars too
    local okw, wounded = pcall(function() return u.health ~= nil and u.health.flags.needs_healthcare end)
    f.wounded = (okw and wounded) and true or false
    local okt, ex = pcall(function() return u.counters2.exhaustion end)
    f.tired = (okt and type(ex) == 'number' and ex >= TIRED_EXHAUSTION) and true or false
    return f
end

local function r1(x) return math.floor(x * 10 + 0.5) / 10 end

function squad_power(sq)
    local melee, ranged, armored, skill_sum, n, armed = 0, 0, 0, 0, 0, 0
    local shooters, cover, weapons, wounded, tired = 0, 0, {}, 0, 0
    for _, pos in ipairs(sq.positions) do
        local hf = pos.occupant ~= -1 and df.historical_figure.find(pos.occupant)
        local u = hf and hf.unit_id ~= -1 and df.unit.find(hf.unit_id)
        if u and not dfhack.units.isDead(u) then
            local f = soldier_facts(u, pos)
            local m, r = soldier_power(f)
            melee, ranged, n = melee + m, ranged + r, n + 1
            skill_sum = skill_sum + math.max(f.skill, f.rskill)
            if f.slots.body then armored = armored + 1 end
            if f.has_weapon then armed = armed + 1 end
            if f.ranged and f.ammo > 0 then shooters = shooters + 1 end
            if f.wclass then weapons[f.wclass] = (weapons[f.wclass] or 0) + 1 end
            if f.wounded then wounded = wounded + 1 end
            if f.tired then tired = tired + 1 end
            cover = cover + coverage(f.slots)
        end
    end
    return {power = r1(melee + ranged), melee_power = r1(melee), ranged_power = r1(ranged),
            armored = armored, armed = armed,
            skill = n > 0 and r1(skill_sum / n) or 0,
            ranged = shooters, coverage = n > 0 and math.floor(cover / n * 100 + 0.5) / 100 or 0,
            weapons = next(weapons) and weapons or nil,
            wounded = wounded > 0 and wounded or nil, tired = tired > 0 and tired or nil}
end

function report(txt)
    local routines = routine_names()
    local out = {squads = {}, soldiers = 0, routines = routines, gates = {}}
    pcall(prune_shelter_marks)          -- (0.105.0 review) the shelter orders gone: unmarked
    local fort = U.fort_entity()
    local ai_names = ai_uniform_names(txt)      -- (13c) read once, not once a squad
    -- (0.105.47) the training squad's (lua/ai-training-squad.lua): never the fort's soldiers
    local okt, TS = pcall(reqscript, 'ai-training-squad')
    local tmarks = okt and TS.marks() or {}
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
                local stationed = nil                -- (0.105.45) {x, y, z} of the AI's station order
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
                        -- (0.105.45) or standing between the threat and the shelter: a
                        -- hiding order too (the brain's rules treat it as the shelter's)
                        local okst, st = pcall(station_of, o, sid)
                        if okst and st then sheltering = true; stationed = st end
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
                    stationed = stationed,           -- (0.105.45)
                    -- (0.105.0) a crossbow squad's bolts: entries, wanted, assigned
                    ammo = (function() local oka, a = pcall(squad_ammo, sq) return oka and a or nil end)(),
                    uniform = #sq.positions > 0 and uniform_set(sq.positions[0]) or false,
                    ai_uniform = ai_names[tostring(sid)],
                    training = tmarks[tostring(sid)] and true or nil,   -- (0.105.47)
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
        for _, u in ipairs(report_citizens(true)) do
            if mothers[u.id] and u.military.squad_id ~= -1 then
                out.soldier_mothers = out.soldier_mothers or {}
                table.insert(out.soldier_mothers, {id = u.id, name = (txt or tostring)(dfhack.units.getReadableName(u)),
                                                   leader = u.military.squad_position == 0 or nil})
            end
        end
    end)
    return out
end

-- (r8) The rest of the military lives in parts beside this file
--
-- ai-military-draft     who may be a soldier, fill/trim/release, make_squad
-- ai-military-uniforms  the uniform probe, templates, set/adopt a uniform
-- ai-military-duty      routines, kill/defend orders, barracks, the defence
--                       test, probe_squads, shelter and station
--
-- Each is loaded into THIS environment (as ai-gates loads its parts), so
-- every name stays reqscript('ai-military').<name> and a test's swap
-- (M.fn = ...) reaches every part. This file's locals the parts use go to
-- them in MILITARY_PART_LOCALS (each takes them back as locals of its own):
-- the same functions and tables, none reassigned after this line.
MILITARY_PART_LOCALS = {U = U, report_citizens = report_citizens, COMBAT_SKILLS = COMBAT_SKILLS, wants_fight = wants_fight, fight_focus = fight_focus, report_units = report_units, gear = gear, save_shelter_marks = save_shelter_marks, order_tick = order_tick, is_guard_order = is_guard_order, is_ai_order = is_ai_order}

PARTS = {'draft', 'uniforms', 'duty'}
-- each part marks the version it came with (started afresh at each load, so a
-- part that failed to load shows as unmarked)
PART_VERSIONS = {['ai-military'] = '0.105.70'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-military-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-military: ' .. name .. '.lua is missing (it goes beside ai-military.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
-- (r8) the parts end here; what follows stood at the end of the one file

-- --- the gear (lua/ai-military-gear.lua) ------------------------------------------
--
-- (13c) The gear half of this file moved there; every name it exports is
-- still reachable here (the bridge, ai-society and ai-threats call them as
-- reqscript('ai-military').<name>). Looked up on call: that module loads
-- this one, so this one must not load it while loading (gear(), at the top).
for _, name in ipairs({'stray_report', 'free_stray_gear', 'weapon_gaps', 'fix_weapon_colours', 'weapon_def',
                       'weapon_is_ranged', 'weapon_fits', 'assign_weapons', 'gear_report', 'gaps_why',
                       'quiver_report', 'assign_quivers', 'squad_ammo', 'squad_bolts', 'unforbid_spares',
                       'fix_gear_gaps', 'kit_report', 'assign_kit', 'army_gear', 'flask_report',
                       'free_bolts', 'bolts_free_count', 'assign_bolts'}) do   -- (r2h4) the bolts handed out
    _ENV[name] = function(...) return gear()[name](...) end
end
