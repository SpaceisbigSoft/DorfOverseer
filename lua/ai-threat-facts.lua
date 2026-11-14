-- (0.105.45, Phase 11 (a)) What a threat brings to a fight, read from its
-- caste's raws and its body, for the brain's matchup against the squads
-- (brain/planner_matchup.py). The report's others_on_map threats get these
-- fields (add_facts, called from lua/ai-bridge-report.lua under pcall):
--
--   facts          1: this module read the threat (the brain uses the new
--                  formula only then; an older bridge's rows are judged as
--                  before)
--   attacks        {count, best = 'edged'/'bite'/'blunt'/'grab', syndrome,
--                  deadly}: its natural attacks (caste.body_info.attacks);
--                  syndrome when one injects an extract or does an
--                  interaction (venom, a forgotten beast's poisoned bite),
--                  deadly when that extract's syndrome kills or cripples
--   syndrome_attack  true when an attack carries a syndrome
--   breath         a list of kinds: 'dragonfire', 'fire', 'web',
--                  'poison_gas', 'dust', 'spit', 'rock', 'other', and
--                  'deadly' when the breathed material carries a syndrome
--                  that kills or cripples (body_info.interactions: each
--                  ability's CDI:FLOW, interaction.material_breath, or its
--                  interaction's material target)
--   webs           spins webs (WEBBER / THICKWEB, or a web spray)
--   no_pain, no_exert, no_stun, trap_avoid, immune_fire   caste flags (and
--                  an undead's curse tags for the first three)
--   regenerates    an active syndrome that regrows parts or heals tissue
--   armor          0-3, armor_kind: a rough natural armour hint (scales,
--                  shell or chitin 1; plates, a stone body or tissue of
--                  strength like bone 2; a metal body or tissue as strong as
--                  iron 3)
--   undead_raiser  an ability that animates the dead (ANIMATE effect)
--   speed          its movement against a dwarf's (2 = twice as fast), from
--                  dfhack.units.computeMovementSpeed; move: the raw number
--   wounds, blood_lost   its wound count and the share of blood it has lost
--
-- The raw half is kept per race and caste for the session (one world: a
-- generated beast's race number means another beast in another save); the
-- body half is read each report. Pure helpers (breath_kinds, attack_kind,
-- attack_summary, armor_of, flag_facts) take plain tables: tested with
-- lupa on stubs (tests/test_r45_matchup.py).
--
-- Field names from df-structures (53.x): caste_raw.body_info.attacks
-- (caste_attack: name, flags.edge/latch, specialattack_type,
-- specialattack_mat_type/index, skill), caste_raw.body_info.interactions
-- (body_actionst.interaction: interaction_informationst material_breath,
-- type_id, material_str0-2), interaction.targets (breath_attack_type,
-- mat_type, mat_index), interaction.effects[i]:getType(), creature_raw.tissue
-- (id, mat_type, mat_index), material.strength.yield[SHEAR],
-- material.syndrome.syndrome[i].ce[j]:getType(), unit.syndromes.active[i].type,
-- unit.body.wounds, unit.body.blood_count/blood_max, unit.curse.add_tags1.
--@ module = true

DWARF_MOVE = 900            -- a dwarf's computeMovementSpeed, about (speed 1.0)
FACTS_CACHE = FACTS_CACHE or {}

-- breath_attack_type names -> the kind the brain weighs
BREATH_KIND = {
    DRAGONFIRE = 'dragonfire', FIREJET = 'fire', FIREBALL = 'fire',
    WEB_SPRAY = 'web',
    TRAILING_GAS_FLOW = 'poison_gas', UNDIRECTED_GAS = 'poison_gas',
    TRAILING_VAPOR_FLOW = 'poison_gas', UNDIRECTED_VAPOR = 'poison_gas',
    WEATHER_CREEPING_GAS = 'poison_gas', WEATHER_CREEPING_VAPOR = 'poison_gas',
    TRAILING_DUST_FLOW = 'dust', UNDIRECTED_DUST = 'dust', WEATHER_CREEPING_DUST = 'dust',
    SPATTER_POWDER = 'dust', UNDIRECTED_ITEM_CLOUD = 'dust',
    SOLID_GLOB = 'spit', LIQUID_GLOB = 'spit', SPATTER_LIQUID = 'spit',
    SHARP_ROCK = 'rock', TRAILING_ITEM_FLOW = 'rock', WEATHER_FALLING_MATERIAL = 'other',
}
-- the syndrome effects that kill or cripple (as lua/ai-syndromes.lua DEADLY)
DEADLY = {NECROSIS = true, BLEEDING = true, PARALYSIS = true, UNCONSCIOUSNESS = true, COUGH_BLOOD = true,
          VOMIT_BLOOD = true, IMPAIR_FUNCTION = true}
REGEN = {REGROW_PARTS = true, HEAL_TISSUES = true, CLOSE_OPEN_WOUNDS = true, HEAL_NERVES = true}
-- attack kinds, the most dangerous to an armoured dwarf first
ATTACK_RANK = {edged = 4, bite = 3, blunt = 2, grab = 1}
-- tissue tokens that armour a body
ARMOR_TISSUE = {SCALE = 'scales', SHELL = 'shell', CHITIN = 'chitin', PLATE = 'plates'}
SHEAR_BONE = 100000         -- a tissue at least this strong in shear (bone ~130000): 2
SHEAR_IRON = 200000         -- iron-like (iron 310000, steel 430000): 3

-- --- pure helpers (plain tables in, plain tables out) ---------------------

-- The kinds of one breath: its flow's name, and whether its material carries
-- a deadly syndrome. Returns a list (may be empty for NONE).
function breath_kinds(name, deadly)
    local out = {}
    if name == nil or name == 'NONE' or name == 'MAXNUM' then
        if deadly then out[1] = 'deadly' end
        return out
    end
    out[1] = BREATH_KIND[tostring(name)] or 'other'
    if deadly then out[2] = 'deadly' end
    return out
end

-- One attack's kind from {name, verb, edge, latch, skill (job_skill name)}.
function attack_kind(a)
    local name = tostring(a.name or ''):upper()
    local skill = tostring(a.skill or ''):upper()
    if name:find('BITE') or skill == 'BITE' then return 'bite' end
    if a.edge then return 'edged' end
    if a.latch or name:find('GRAB') or name:find('SQUEEZE') or name:find('GRASP') or skill == 'GRASP_STRIKE' then
        return 'grab'
    end
    return 'blunt'
end

-- A caste's attacks summed up: {count, best, syndrome, deadly} from a list
-- of {name, edge, latch, skill, special = {'INJECT_EXTRACT', ...}, deadly}.
function attack_summary(list)
    local out = {count = 0}
    local best = 0
    for _, a in ipairs(list or {}) do
        out.count = out.count + 1
        local k = attack_kind(a)
        if (ATTACK_RANK[k] or 0) > best then best, out.best = ATTACK_RANK[k], k end
        for _, sp in ipairs(a.special or {}) do
            if sp == 'INJECT_EXTRACT' or sp == 'INTERACTION' then out.syndrome = true end
        end
        if a.deadly then out.syndrome, out.deadly = true, true end
    end
    return out
end

-- A rough natural armour hint from the body's tissues: a list of {id,
-- inorganic (a stone or metal body), metal, shear (yield)}. Returns level
-- 0-3 and its kind (nil at 0).
function armor_of(tissues)
    local level, kind = 0, nil
    local function up(l, k) if l > level then level, kind = l, k end end
    for _, t in ipairs(tissues or {}) do
        local id = tostring(t.id or ''):upper()
        local bony = id:find('BONE') or id:find('TOOTH') or id:find('TUSK') or id:find('IVORY')
                     or id:find('HORN') or id:find('HOOF') or id:find('NAIL') or id:find('CLAW')
                     or id:find('BEAK') or id:find('TALON')
        for tok, k in pairs(ARMOR_TISSUE) do
            if id:find(tok) then up(tok == 'PLATE' and 2 or 1, k) end
        end
        if t.metal then up(3, 'metal')
        elseif t.inorganic then up(2, 'stone') end
        -- the body's own strength: bones and teeth don't armour it
        local sh = tonumber(t.shear)
        if sh and not bony then
            if sh >= SHEAR_IRON then up(3, kind or 'hard')
            elseif sh >= SHEAR_BONE then up(2, kind or 'hard') end
        end
    end
    return level, kind
end

-- The caste's flags (a table name -> bool) as facts.
function flag_facts(f)
    f = f or {}
    local out = {}
    if f.NOPAIN then out.no_pain = true end
    if f.NOEXERT then out.no_exert = true end
    if f.NOSTUN then out.no_stun = true end
    if f.TRAPAVOID then out.trap_avoid = true end
    if f.FIREIMMUNE or f.FIREIMMUNE_SUPER then out.immune_fire = true end
    if f.WEBBER or f.THICKWEB then out.webs = true end
    if f.FLIER then out.flier = true end
    return out
end

-- --- reading DF (all behind pcall) ----------------------------------------

local function enum_name(enum, v)
    if v == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return nil
end

local function vec(v)
    local out = {}
    if v == nil then return out end
    pcall(function() for _, x in ipairs(v) do out[#out + 1] = x end end)
    return out
end

-- Does a material (type, index) carry a deadly syndrome? (and any at all)
local function mat_deadly(mt, mi)
    if mt == nil or mt < 0 then return false, false end
    local any, deadly = false, false
    pcall(function()
        local info = dfhack.matinfo.decode(mt, mi)
        for _, sd in ipairs(info.material.syndrome.syndrome) do
            any = true
            for _, ce in ipairs(sd.ce) do
                local n = enum_name(df.creature_interaction_effect_type, ce:getType())
                if n and DEADLY[n] then deadly = true end
            end
        end
    end)
    return deadly, any
end

local function material_deadly(mat)
    local deadly = false
    pcall(function()
        for _, sd in ipairs(mat.syndrome.syndrome) do
            for _, ce in ipairs(sd.ce) do
                local n = enum_name(df.creature_interaction_effect_type, ce:getType())
                if n and DEADLY[n] then deadly = true end
            end
        end
    end)
    return deadly
end

-- The material a creature ability names (CDI:MATERIAL tokens), deadly?
local function info_deadly(cr, info)
    local s0, s1, s2 = '', '', ''
    pcall(function() s0, s1, s2 = info.material_str0 or '', info.material_str1 or '', info.material_str2 or '' end)
    if s0 == 'LOCAL_CREATURE_MAT' then
        local d = false
        pcall(function()
            for _, m in ipairs(cr.material) do
                if m.id == s1 then d = material_deadly(m) end
            end
        end)
        return d
    end
    local token = (s0 == 'CREATURE_MAT' and ('CREATURE:' .. s1 .. ':' .. s2))
                  or (s0 == 'INORGANIC' and ('INORGANIC:' .. s1)) or nil
    if not token then return false end
    local d = false
    pcall(function()
        local mi = dfhack.matinfo.find(token)
        if mi then d = material_deadly(mi.material) end
    end)
    return d
end

local function add_kinds(set, list)
    for _, k in ipairs(list) do set[k] = true end
end

-- The raw half: one table per race and caste.
function raw_facts(race, caste)
    local okw, world = pcall(function() return df.global.world.cur_savegame.save_dir end)
    world = tostring(okw and world or '?')
    if FACTS_WORLD ~= world then FACTS_CACHE, FACTS_WORLD = {}, world end
    local key = tostring(race) .. ':' .. tostring(caste)
    local v = FACTS_CACHE[key]
    if v ~= nil then return v end
    v = {}
    local okc, cr, c = pcall(function()
        local r = df.creature_raw.find(race)
        return r, r.caste[caste]
    end)
    if not (okc and cr and c) then
        FACTS_CACHE[key] = v
        return v
    end
    -- attacks
    local list = {}
    for _, a in ipairs(vec(c.body_info.attacks)) do
        local row = {special = {}}
        pcall(function() row.name = a.name end)
        pcall(function() row.edge = a.flags.edge and true or false end)
        pcall(function() row.latch = a.flags.latch and true or false end)
        pcall(function() row.skill = enum_name(df.job_skill, a.skill) end)
        pcall(function()
            local mts, mis = vec(a.specialattack_mat_type), vec(a.specialattack_mat_index)
            for j, sp in ipairs(vec(a.specialattack_type)) do
                local n = enum_name(df.specialattack_type, sp) or tostring(sp)
                table.insert(row.special, n)
                if n == 'INJECT_EXTRACT' and mat_deadly(mts[j], mis[j]) then row.deadly = true end
            end
        end)
        list[#list + 1] = row
    end
    if #list > 0 then
        v.attacks = attack_summary(list)
        if v.attacks.syndrome then v.syndrome_attack = true end
    end
    -- abilities: breaths, webs, raising the dead
    local kinds = {}
    for _, act in ipairs(vec(c.body_info.interactions)) do
        pcall(function()
            local info = act.interaction
            local deadly = info_deadly(cr, info)
            local b = enum_name(df.breath_attack_type, info.material_breath)
            if b and b ~= 'NONE' and b ~= 'MAXNUM' then add_kinds(kinds, breath_kinds(b, deadly)) end
            local it = df.interaction.find(info.type_id)
            if it then
                for _, t in ipairs(vec(it.targets)) do
                    local okb, bt = pcall(function() return t.breath_attack_type end)
                    local n = okb and enum_name(df.breath_attack_type, bt) or nil
                    if n and n ~= 'NONE' and n ~= 'MAXNUM' then
                        local okm, mt, mi = pcall(function() return t.mat_type, t.mat_index end)
                        local d2 = okm and mat_deadly(mt, mi) or false
                        add_kinds(kinds, breath_kinds(n, deadly or d2))
                    end
                end
                for _, e in ipairs(vec(it.effects)) do
                    local oke, et = pcall(function() return e:getType() end)
                    if oke and enum_name(df.interaction_effect_type, et) == 'ANIMATE' then v.undead_raiser = true end
                end
            end
        end)
    end
    local blist = {}
    for _, k in ipairs({'dragonfire', 'fire', 'poison_gas', 'dust', 'web', 'spit', 'rock', 'other', 'deadly'}) do
        if kinds[k] then blist[#blist + 1] = k end
    end
    if #blist > 0 then v.breath = blist end
    -- flags
    local fl = {}
    for _, n in ipairs({'NOPAIN', 'NOEXERT', 'NOSTUN', 'TRAPAVOID', 'FIREIMMUNE', 'FIREIMMUNE_SUPER',
                        'WEBBER', 'THICKWEB', 'FLIER'}) do
        local okf, on = pcall(function() return c.flags[n] end)
        if okf and on then fl[n] = true end
    end
    for k, x in pairs(flag_facts(fl)) do v[k] = x end
    if kinds.web then v.webs = true end
    -- natural armour from the tissues
    local tissues = {}
    for _, t in ipairs(vec(cr.tissue)) do
        local row = {}
        pcall(function() row.id = t.id end)
        pcall(function()
            local mi = dfhack.matinfo.decode(t.mat_type, t.mat_index)
            if mi then
                if mi.inorganic then
                    row.inorganic = true
                    row.metal = mi.material.flags.IS_METAL and true or false
                end
                row.shear = mi.material.strength.yield[df.strain_type.SHEAR]
            end
        end)
        tissues[#tissues + 1] = row
    end
    local lvl, kind = armor_of(tissues)
    if lvl > 0 then v.armor, v.armor_kind = lvl, kind end
    FACTS_CACHE[key] = v
    return v
end

-- The body half: wounds, blood, curse tags, regeneration, speed.
function body_facts(u)
    local out = {}
    pcall(function() out.wounds = #u.body.wounds end)
    pcall(function()
        local mx, cur = u.body.blood_max or 0, u.body.blood_count or 0
        if mx > 0 and cur < mx then out.blood_lost = math.floor((1 - cur / mx) * 100 + 0.5) / 100 end
    end)
    pcall(function()
        local t = u.curse.add_tags1
        if t.NOPAIN then out.no_pain = true end
        if t.NOEXERT then out.no_exert = true end
        if t.NOSTUN then out.no_stun = true end
    end)
    pcall(function()
        for _, s in ipairs(u.syndromes.active) do
            local sd = df.syndrome.find(s.type)
            for _, ce in ipairs(sd and vec(sd.ce) or {}) do
                local n = enum_name(df.creature_interaction_effect_type, ce:getType())
                if n and REGEN[n] then out.regenerates = true end
            end
        end
    end)
    pcall(function()
        local m = dfhack.units.computeMovementSpeed(u)
        if type(m) == 'number' and m > 0 then
            out.move = m
            out.speed = math.floor(DWARF_MOVE / m * 100 + 0.5) / 100
        end
    end)
    return out
end

-- The report's threat row t gets the facts of unit u. Fields already on the
-- row (flier, abilities, destroyer, size) are left as they are.
function add_facts(t, u)
    if type(t) ~= 'table' or not u then return t end
    local okr, raw = pcall(raw_facts, u.race, u.caste)
    if okr and type(raw) == 'table' then
        for k, x in pairs(raw) do
            if k ~= 'flier' and t[k] == nil then t[k] = x end
        end
    end
    local okb, body = pcall(body_facts, u)
    if okb and type(body) == 'table' then
        for k, x in pairs(body) do if t[k] == nil then t[k] = x end end
    end
    t.facts = 1
    return t
end
