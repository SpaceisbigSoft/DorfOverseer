-- ai-fights: the fight watcher. A fight among the fort's own citizens capped
-- at a brawl and broken up inside the game, every FIGHT_WATCH_TICKS, not once
-- a game day.
--
-- Why (B, 24 Nov): seven citizens strangled (SUFFOCATE) by citizens in three
-- hours, a tantrum-thrower and the bystanders drawn in. The brain's
-- break_fights (DFHack fix/loyaltycascade) ran once a cycle, about a game day:
-- at tick 163785 it took 11 units out of their conflicts, and ~600 ticks later
-- two died in the same fight. A fight kills in tens to hundreds of ticks, and
-- a tantrum-thrower re-engages at once; this watcher looks every 10.
--
-- Each pass (DF's world.activities.all; nothing to do when no Conflict
-- activity exists):
--   * a Conflict whose every participant (all sides' unit_ids) is a living
--     citizen (dfhack.units.isCitizen, none an invader, undead, crazed or
--     transformed werebeast, none a danger) is the fort's own fight; anything
--     else (invaders, wildlife, a unit we can't read) is left alone, and its
--     units too: they are never taken out of their conflicts here;
--   * levels below Brawl (Encounter, Horseplay, Training) are only logged;
--   * cap: any side's enemies[i].conflict_level above Brawl (Nonlethal,
--     Lethal, NoQuarter) is set to Brawl (a plain field write);
--   * separate: once it has lasted FIGHT_SEPARATE_TICKS since first seen, or
--     a level above Brawl was seen in it, or a participant died in it, or one
--     of its units was separated less than REENGAGE_TICKS ago (counted as a
--     re-engagement), every living citizen in it is taken out of its conflicts
--     with DFHack's own makeown.remove_from_conflict (what fix/loyaltycascade
--     does for every citizen). Each pass again while they keep fighting.
--
-- Every conflict of the fort's own is logged (first sighting, each change of
-- levels or participants, each cap and separation: activity id, the
-- participants with names and tantrum/berserk, the side levels before and
-- after, DF's three timers, the tick) to a ring in memory (the `fights`
-- section) and appended to dfhack-config/ai-overseer/fights.jsonl (kept to
-- the last LOG_FILE_KEEP lines).
--
-- The loop lives while the game runs: its state is kept in one global table
-- (survives a reload of this file, so arming twice never makes two loops; a
-- newer load takes the loop over and the older one stops at its next beat),
-- cleared when the map or world unloads. The brain's fight_watch rule arms it
-- whenever the `fights` section says it is off.
--
-- (item3, the player 24 Nov 16:50) A tantrum that attacks a citizen is ended
-- at once: B's and E's tantrum-throwers strangled citizens with no Conflict
-- activity DF opened for the watcher to see. Each pass also looks at the
-- living citizens in a Tantrum or Enraged soldier mood; one whose Attack
-- action targets a living citizen (or whose opponent is one, or who is in a
-- Conflict with one) has its soldier_mood_countdown set to 1 (DF ends the
-- mood itself next tick; soldier_mood is never written). Counted
-- (tantrums_ended), logged (kind 'tantrum_ended', once a unit a
-- TANTRUM_LOG_TICKS). The Rules switch end_tantrums (on by default) turns
-- the ending off (then only logged). A calm citizen's Attack on a citizen
-- is only logged (kind 'attack', once a pair a ATTACK_LOG_TICKS), sparring
-- left out.
--
-- (item3, B 24 Nov) Sparring: B logged 199 'attack's in ~2 h, nearly all
-- mutual pairs of wrestlers (each attacking the other in the same ticks, no
-- deaths, no tantrum): DF's sparring/combat training opens no Horseplay or
-- Training conflict. A calm citizen's attack on a citizen is sparring when
-- the guards hold (the target in no tantrum or berserk, neither of the two in
-- a conflict above Training, neither badly hurt: suffocating, unconscious or
-- under 3/4 of its blood) and one of:
--   'conflict'  the attacker in a Horseplay/Training conflict (as before);
--   'activity'  the attacker in a training activity (an entry or event named
--               in TRAINING_ACTIVITY: its u.social_activities/u.activities,
--               or listed among a training event's participants);
--   'squad'     the attacker on duty in a squad told to train (a TRAIN order
--               in its routine's schedule this month, or a routine named
--               '...train...') with no order of the squad's own;
--   'mutual'    the target attacked the attacker too within MUTUAL_TICKS.
-- Counted (counts.spars, once a pair a ATTACK_LOG_TICKS), never in the log:
-- the last SPAR_RECENT_KEEP are the section's spars_recent. A tantrum is
-- still ended (the tantrum branch is looked at first, mutual or not).
--
--   act(a)        the fight_watch action {on, ticks?, separate_ticks?, end_tantrums?, dry_run?}
--   report()      the `fights` section
--   pass(now)     one pass (the timer's; tests call it)
--@ module = true

FIGHT_WATCH_TICKS = 10       -- ticks between passes
FIGHT_SEPARATE_TICKS = 50    -- a brawl this old (since first seen) is broken up
REENGAGE_TICKS = 600         -- a separated unit fighting again this soon: separated again at once
BRAWL = 3                    -- df.conflict_level.Brawl (-1 None, 0 Encounter, 1 Horseplay, 2 Training,
                             -- 3 Brawl, 4 Nonlethal, 5 Lethal, 6 NoQuarter)
LOG_KEEP = 60                -- log entries kept in memory
REPORT_LOG = 10              -- ...of which the section shows the last
LOG_FILE_KEEP = 500          -- lines kept in fights.jsonl
LOG_FILE_SLACK = 100         -- ...rewritten once it holds this many more
TANTRUM_LOG_TICKS = 100      -- (item3) a tantrum ended is logged once a unit in this many ticks
ATTACK_LOG_TICKS = 600       -- (item3) a calm citizen's attack on a citizen: once a pair in this many
SPARRING_MAX = 2             -- (item3) a conflict no higher than Training is sparring
MUTUAL_TICKS = 100           -- (item3) A attacks B and B attacks A within this many ticks: sparring
SPAR_RECENT_KEEP = 5         -- (item3) the last spars the section shows (spars_recent)
TRAINING_ACTIVITY = {Sparring = true, CombatTraining = true, IndividualSkillDrill = true, SkillDemonstration = true,
                     Training = true, TrainingSession = true, RangedPractice = true}   -- (item3) DF's names
MONTH = 33600                -- ticks in a game month (the squad schedule's index)
STATE_KEY = 'ai_overseer_fight_watch'
YEAR = 403200

local CODE = {}              -- this load of the file (a newer load takes the loop over)

local function game_tick()   -- (U.abs_tick's reading, here so the timer needs no other module)
    local ok, t = pcall(function() return df.global.cur_year * YEAR + df.global.cur_year_tick end)
    return ok and t or 0
end

local function fresh_state()
    return {on = false, ticks = FIGHT_WATCH_TICKS, separate_ticks = FIGHT_SEPARATE_TICKS, end_tantrums = true,
            counts = {seen = 0, capped = 0, separated = 0, reengaged = 0, passes = 0, errors = 0, died = 0,
                      tantrums_ended = 0, tantrum_attacks = 0, attacks = 0, spars = 0},
            seen = {}, recent = {}, log = {}, file_lines = nil, tantrum_logged = {}, attack_logged = {},
            attack_seen = {}, spar_logged = {}, spars_recent = {}}
end

-- the one state table, global so a reload of this file finds it
function state()
    local G = _G
    local S = rawget(G, STATE_KEY)
    if type(S) ~= 'table' then
        S = fresh_state()
        rawset(G, STATE_KEY, S)
    end
    return S
end

function reset()
    rawset(_G, STATE_KEY, fresh_state())
    return state()
end

if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-fights'] = function(sc)
        if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then
            pcall(reset)                 -- DFHack drops the tick timers itself
        end
    end
end

-- --- small helpers ----------------------------------------------------------

local function is(f, ...)
    if type(f) ~= 'function' then return nil end
    local ok, r = pcall(f, ...)
    if not ok then return nil end
    return r == true
end

local function unit_name(u)   -- (U.name_of's reading; the timer needs no other module)
    local ok, nm = pcall(dfhack.units.getReadableName, u)
    if not ok or type(nm) ~= 'string' then return 'unit ' .. tostring(u and u.id) end
    if dfhack.df2utf then
        local okc, c = pcall(dfhack.df2utf, nm)
        if okc and type(c) == 'string' then nm = c end
    end
    return nm
end

local function in_tantrum(u)
    local ok, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    return ok and (m == 'Tantrum' or m == 'Enraged') or false
end

local function berserk(u)
    local ok, m = pcall(function() return u.mood ~= nil and u.mood >= 0 and df.mood_type[u.mood] or nil end)
    return ok and m == 'Berserk' or false
end

local function vec_list(v)
    local out = {}
    if v == nil then return out end
    local ok = pcall(function() for _, x in ipairs(v) do table.insert(out, x) end end)
    return ok and out or {}
end

local function field(o, k)
    local ok, v = pcall(function() return o[k] end)
    return ok and v or nil
end

-- the unit's judgement: 'citizen' (a living citizen of the fort), 'dead' (a
-- dead citizen), or nil and why (anything else: the conflict is left alone)
function unit_kind(u)
    local U = dfhack.units
    if not u then return nil, 'unit not found' end
    if is(U.isDead, u) or (U.isAlive and is(U.isAlive, u) == false) then
        local civ = field(df.global.plotinfo, 'civ_id')
        if field(u, 'civ_id') == civ and civ ~= nil and not is(U.isAnimal, u) then return 'dead' end
        return nil, 'dead, not a citizen'
    end
    if is(U.isInvader, u) then return nil, 'invader' end
    if is(U.isUndead, u) then return nil, 'undead' end
    if is(U.isCrazed, u) then return nil, 'crazed' end
    if is(U.isDanger, u) then return nil, 'a danger' end
    local okw, changed = pcall(function()
        local nr = u.enemy.normal_race
        return nr ~= nil and nr >= 0 and nr ~= u.race
    end)
    if okw and changed then return nil, 'transformed' end
    if is(U.isMerchant, u) or is(U.isDiplomat, u) or is(U.isVisitor, u) or is(U.isAnimal, u) then
        return nil, 'not a citizen'
    end
    local okc, cit = pcall(U.isCitizen, u, true)
    if okc and cit then return 'citizen' end
    return nil, 'not a citizen'
end

local function find_unit(id)
    local ok, u = pcall(df.unit.find, id)
    return ok and u or nil
end

-- the Conflict events now: {act = activity id, ev = event}
function conflicts()
    local out = {}
    local ok = pcall(function()
        local all = df.global.world.activities.all
        if #all == 0 then return end
        local CT, ET = df.activity_entry_type.Conflict, df.activity_event_type.Conflict
        for _, a in ipairs(all) do
            if a.type == CT then
                for _, ev in ipairs(a.events) do
                    local okt, ty = pcall(function() return ev:getType() end)
                    if okt and ty == ET then table.insert(out, {act = a.id, ev = ev}) end
                end
            end
        end
    end)
    return ok and out or {}
end

local function timers_of(ev)
    return {inactivity = field(ev, 'inactivity_timer'), attack_inactivity = field(ev, 'attack_inactivity_timer'),
            stop_fort_fights = field(ev, 'stop_fort_fights_timer')}
end

-- the sides' levels: {{side = id, enemy = id, level = n}, ...} and the highest
function levels_of(ev)
    local out, max = {}, nil
    for _, side in ipairs(vec_list(field(ev, 'sides'))) do
        for _, e in ipairs(vec_list(field(side, 'enemies'))) do
            local lv = field(e, 'conflict_level')
            if type(lv) == 'number' then
                table.insert(out, {side = field(side, 'id'), enemy = field(e, 'id'), level = lv})
                if max == nil or lv > max then max = lv end
            end
        end
    end
    return out, max
end

-- One conflict read: {ours = bool, why, ids, units = {{id, u, kind, name, tantrum, berserk}}, died}
function judge(ev)
    local j = {ours = true, ids = {}, units = {}, died = false}
    local seen = {}
    for _, side in ipairs(vec_list(field(ev, 'sides'))) do
        for _, id in ipairs(vec_list(field(side, 'unit_ids'))) do
            if not seen[id] then
                seen[id] = true
                table.insert(j.ids, id)
                local u = find_unit(id)
                local kind, why = unit_kind(u)
                if not kind then
                    j.ours, j.why = false, why
                    j.why_id = j.why_id or id   -- (0.105.106) the unit that made it not the fort's own
                else
                    if kind == 'dead' then j.died = true end
                    table.insert(j.units, {id = id, u = u, kind = kind})
                end
            end
        end
    end
    if #j.ids < 2 then j.ours, j.why = false, j.why or 'fewer than two units' end
    return j
end

-- --- the log ----------------------------------------------------------------

local function esc(s)
    return (s:gsub('[%c"\\]', function(c)
        if c == '"' then return '\\"' elseif c == '\\' then return '\\\\'
        elseif c == '\n' then return '\\n' end
        return string.format('\\u%04x', c:byte())
    end))
end

-- a small JSON encoder (a list is a table with [1]; an empty table is [])
function encode(v)
    local t = type(v)
    if t == 'nil' then return 'null' end
    if t == 'boolean' then return tostring(v) end
    if t == 'number' then
        if v ~= v or v == math.huge or v == -math.huge then return 'null' end
        if math.type and math.type(v) == 'integer' then return tostring(v) end
        if v == math.floor(v) and math.abs(v) < 1e15 then return string.format('%d', v) end
        return tostring(v)
    end
    if t == 'string' then return '"' .. esc(v) .. '"' end
    if t == 'table' then
        local parts = {}
        if v[1] ~= nil or next(v) == nil then
            for _, x in ipairs(v) do table.insert(parts, encode(x)) end
            return '[' .. table.concat(parts, ',') .. ']'
        end
        local keys = {}
        for k in pairs(v) do table.insert(keys, tostring(k)) end
        table.sort(keys)
        for _, k in ipairs(keys) do table.insert(parts, '"' .. esc(k) .. '":' .. encode(v[k])) end
        return '{' .. table.concat(parts, ',') .. '}'
    end
    return 'null'
end

function log_path()
    local ok, p = pcall(function() return dfhack.getDFPath() .. '/dfhack-config/ai-overseer/fights.jsonl' end)
    return ok and p or nil
end

local function count_lines(p)
    local n = 0
    local f = io.open(p, 'r')
    if not f then return 0 end
    for _ in f:lines() do n = n + 1 end
    f:close()
    return n
end

local function trim_file(p)
    local lines = {}
    local f = io.open(p, 'r')
    if not f then return 0 end
    for l in f:lines() do table.insert(lines, l) end
    f:close()
    local from = math.max(1, #lines - LOG_FILE_KEEP + 1)
    local w = io.open(p, 'w')
    if not w then return #lines end
    for i = from, #lines do w:write(lines[i], '\n') end
    w:close()
    return #lines - from + 1
end

local function append_file(S, entry)
    local p = log_path()
    if not p then return end
    pcall(function()
        if S.file_lines == nil then
            pcall(function() dfhack.filesystem.mkdir_recursive(dfhack.getDFPath() .. '/dfhack-config/ai-overseer') end)
            S.file_lines = count_lines(p)
        end
        local f = io.open(p, 'a')
        if not f then return end
        f:write(encode(entry), '\n')
        f:close()
        S.file_lines = S.file_lines + 1
        if S.file_lines > LOG_FILE_KEEP + LOG_FILE_SLACK then S.file_lines = trim_file(p) end
    end)
end

local function log(S, entry)
    table.insert(S.log, entry)
    while #S.log > LOG_KEEP do table.remove(S.log, 1) end
    append_file(S, entry)
end

local function unit_rows(j)
    local out = {}
    for _, r in ipairs(j.units) do
        table.insert(out, {id = r.id, name = unit_name(r.u), dead = r.kind == 'dead' or nil,
                           tantrum = (r.kind == 'citizen' and in_tantrum(r.u)) or nil,
                           berserk = (r.kind == 'citizen' and berserk(r.u)) or nil})
    end
    return out
end

local function sig_of(ids, lv)
    local a = {}
    for _, id in ipairs(ids) do table.insert(a, tostring(id)) end
    table.sort(a)
    local b = {}
    for _, l in ipairs(lv) do table.insert(b, tostring(l.side) .. '>' .. tostring(l.enemy) .. '=' .. tostring(l.level)) end
    table.sort(b)
    return table.concat(a, ',') .. '|' .. table.concat(b, ',')
end

-- --- makeown ------------------------------------------------------------------

local makeown_mod = nil
local function makeown()
    if makeown_mod then return makeown_mod end
    local ok, m = pcall(reqscript, 'makeown')
    if ok and type(m) == 'table' and type(m.remove_from_conflict) == 'function' then
        makeown_mod = m
        return m
    end
    return nil
end

local status_mod = nil
local function halted()
    if status_mod == nil then
        local ok, m = pcall(reqscript, 'ai-status')
        status_mod = (ok and type(m) == 'table') and m or false
    end
    if not status_mod or type(status_mod.is_halted) ~= 'function' then return false end
    local ok, h = pcall(status_mod.is_halted)
    return ok and h == true
end

-- --- (item3) tantrums that attack citizens -------------------------------------

local function bump(S, k, n)
    S.counts[k] = (S.counts[k] or 0) + (n or 1)
end

-- the unit's Attack actions: {{target = id, attack = data.attack}, ...}
local function attacks_of(u)
    local out = {}
    pcall(function()
        local acts = u.actions
        if acts == nil or #acts == 0 then return end
        local AT = df.unit_action_type.Attack
        for _, a in ipairs(acts) do
            if a.type == AT then
                local at = a.data.attack
                local tid = at.target_unit_id
                if type(tid) == 'number' and tid >= 0 then table.insert(out, {target = tid, attack = at}) end
            end
        end
    end)
    return out
end

local function living_citizen(id)
    if type(id) ~= 'number' or id < 0 then return nil end
    local t = find_unit(id)
    if t and unit_kind(t) == 'citizen' then return t end
    return nil
end

-- the conflicts by unit: {[id] = {{ev, max}, ...}} (from the pass's list)
local function conflicts_by_unit(list)
    local by = {}
    for _, c in ipairs(list) do
        local _, max = levels_of(c.ev)
        for _, side in ipairs(vec_list(field(c.ev, 'sides'))) do
            for _, id in ipairs(vec_list(field(side, 'unit_ids'))) do
                by[id] = by[id] or {}
                table.insert(by[id], {ev = c.ev, act = c.act, max = max})
            end
        end
    end
    return by
end

-- a living citizen on another side of one of the unit's conflicts: unit, activity id
local function conflict_citizen(by, id)
    for _, c in ipairs(by[id] or {}) do
        for _, side in ipairs(vec_list(field(c.ev, 'sides'))) do
            local ids = vec_list(field(side, 'unit_ids'))
            local mine = false
            for _, x in ipairs(ids) do if x == id then mine = true end end
            if not mine then
                for _, x in ipairs(ids) do
                    local t = living_citizen(x)
                    if t then return t, c.act end
                end
            end
        end
    end
    return nil
end

local function sparring(by, id)
    for _, c in ipairs(by[id] or {}) do
        if c.max ~= nil and c.max >= 1 and c.max <= SPARRING_MAX then return true end
    end
    return false
end

-- --- (item3) sparring that opens no conflict -----------------------------------

-- in a conflict above Training (a brawl or worse: never sparring)
local function above_training(by, id)
    for _, c in ipairs(by[id] or {}) do
        if c.max ~= nil and c.max > SPARRING_MAX then return true end
    end
    return false
end

-- badly hurt: suffocating (a strangling, what killed B's seven), unconscious,
-- or under 3/4 of its blood. nil when not (or unreadable).
local function hurt(u)
    local c = field(u, 'counters')
    local suff, unc = field(c, 'suffocation'), field(c, 'unconscious')
    if type(suff) == 'number' and suff > 0 then return 'suffocating' end
    if type(unc) == 'number' and unc > 0 then return 'unconscious' end
    local b = field(u, 'body')
    local bc, bm = field(b, 'blood_count'), field(b, 'blood_max')
    if type(bc) == 'number' and type(bm) == 'number' and bm > 0 and bc * 4 < bm * 3 then return 'bleeding' end
    return nil
end

-- the DF name of a training activity entry or event type (nil when it is none)
local function training_name(enum, ty)
    local ok, nm = pcall(function() return enum[ty] end)
    if ok and type(nm) == 'string' and TRAINING_ACTIVITY[nm] then return nm end
    return nil
end

-- the training activities now: {acts = {[activity id] = name}, units = {[unit id] = name}}
-- (an entry is training when its own type or one of its events' is; the units
-- are the training events' participants.units, where DF lists them)
function training_index()
    local idx = {acts = {}, units = {}}
    pcall(function()
        local all = df.global.world.activities.all
        if #all == 0 then return end
        for _, a in ipairs(all) do
            local nm = training_name(df.activity_entry_type, field(a, 'type'))
            local evs = vec_list(field(a, 'events'))
            for _, ev in ipairs(evs) do
                local okt, ty = pcall(function() return ev:getType() end)
                local en = (okt and training_name(df.activity_event_type, ty)) or nil
                if en then nm = nm or en end
            end
            if nm then
                local id = field(a, 'id')
                if id ~= nil then idx.acts[id] = nm end
                for _, ev in ipairs(evs) do
                    for _, uid in ipairs(vec_list(field(field(ev, 'participants'), 'units'))) do
                        if idx.units[uid] == nil then idx.units[uid] = nm end
                    end
                end
            end
        end
    end)
    return idx
end

-- the training activity the unit is in (its name), or nil
local function training_of(u, idx)
    local id = field(u, 'id')
    if id ~= nil and idx.units[id] then return idx.units[id] end
    for _, k in ipairs({'social_activities', 'activities'}) do
        for _, aid in ipairs(vec_list(field(u, k))) do
            if type(aid) ~= 'number' then aid = field(aid, 'id') end   -- (a pointer, should DF hold one)
            if aid ~= nil and idx.acts[aid] then return idx.acts[aid] end
        end
    end
    return nil
end

-- on duty in a squad told to train: 'order' (a TRAIN order in the squad's
-- routine this month, the unit's position not left out of it), 'routine' (the
-- schedule unreadable, the routine named '...train...'), or nil. A squad with
-- an order of its own (kill, station...) is not training.
local function squad_training(u)
    local ok, why = pcall(function()
        local sid = u.military.squad_id
        if type(sid) ~= 'number' or sid < 0 then return nil end
        local sq = df.squad.find(sid)
        if not sq then return nil end
        local okn, n = pcall(function() return #sq.orders end)
        if okn and n > 0 then return nil end
        local idx = field(sq, 'cur_routine_idx')
        if type(idx) ~= 'number' or idx < 0 then return nil end
        local found, read = nil, false
        pcall(function()
            local month = math.floor(df.global.cur_year_tick / MONTH)
            local TRAIN = df.squad_order_type.TRAIN
            local pos = u.military.squad_position
            for _, so in ipairs(sq.schedule[idx][month].orders) do
                local okt, ty = pcall(function() return so.order:getType() end)
                if okt and ty == TRAIN then
                    local okp, mine = pcall(function() return so.positions[pos] end)
                    if not okp or mine ~= false then found = 'order' end
                end
            end
            read = true
        end)
        if found or read then return found end
        local okr, nm = pcall(function() return tostring(df.global.plotinfo.alerts.routines[idx].name) end)
        if okr and type(nm) == 'string' and nm:lower():find('train', 1, true) then return 'routine' end
        return nil
    end)
    return ok and why or nil
end

-- why a calm citizen's attack on citizen `t` is sparring ('conflict',
-- 'activity', 'squad', 'mutual'; and the activity's name), or nil: a real
-- attack. The guards first: a target in a tantrum or berserk, either in a
-- conflict above Training, or either badly hurt is never sparring.
function spar_reason(S, by, u, t, now, tidx)
    if in_tantrum(t) or berserk(t) or berserk(u) then return nil end
    if above_training(by, u.id) or above_training(by, t.id) then return nil end
    if hurt(u) or hurt(t) then return nil end
    if sparring(by, u.id) then return 'conflict' end
    local nm = training_of(u, tidx)
    if nm then return 'activity', nm end
    local sq = squad_training(u)
    if sq then return 'squad', sq end
    local back = (S.attack_seen or {})[tostring(t.id) .. '>' .. tostring(u.id)]
    if back and now - back >= 0 and now - back <= MUTUAL_TICKS then return 'mutual' end
    return nil
end

-- a few plain fields of the attack's wrestle info (nil when unreadable)
local function wrestle_of(at)
    local ok, out = pcall(function()
        local wi = at.wrestle_info
        if wi == nil then return nil end
        local o, n = {}, 0
        for k, v in pairs(wi) do
            if (type(v) == 'number' or type(v) == 'boolean') and n < 8 then
                o[tostring(k)] = v
                n = n + 1
            end
        end
        return n > 0 and o or nil
    end)
    return ok and out or nil
end

local function job_of(u)
    local ok, j = pcall(function()
        local cj = u.job.current_job
        if cj == nil then return nil end
        return df.job_type[cj.job_type] or cj.job_type
    end)
    return ok and j or nil
end

local function attack_row(at)
    if at == nil then return nil end
    return {wrestle = wrestle_of(at), body_part = field(at, 'attack_body_part_id'),
            timer1 = field(at, 'timer1'), timer2 = field(at, 'timer2')}
end

-- one look at the living citizens: a tantrum that attacks a citizen ended,
-- a calm citizen's attack on a citizen logged, or counted as sparring
-- (item3: spar_reason). Returns the tantrums ended.
function scan_units(S, now, dry, list)
    local units = {}
    local ok = pcall(function() units = df.global.world.units.active end)
    if not ok or units == nil then return 0 end
    S.tantrum_logged = S.tantrum_logged or {}
    S.attack_logged = S.attack_logged or {}
    S.attack_seen = S.attack_seen or {}              -- (item3) a state from an older load of this file
    S.spar_logged = S.spar_logged or {}
    S.spars_recent = S.spars_recent or {}
    S.counts.spars = S.counts.spars or 0
    local calm = {}
    local on = S.end_tantrums ~= false
    local by = nil
    local ended = 0
    for _, u in ipairs(units) do
        local tantrum = in_tantrum(u)
        local hits = attacks_of(u)
        if (tantrum or #hits > 0) and unit_kind(u) == 'citizen' then
            by = by or conflicts_by_unit(list)
            if tantrum then
                local target, how, at, act_id = nil, nil, nil, nil
                for _, h in ipairs(hits) do
                    target = living_citizen(h.target)
                    if target then how, at = 'attack', h.attack; break end
                end
                if not target then
                    target = living_citizen(field(field(u, 'opponent'), 'unit_id'))
                    if target then how = 'opponent' end
                end
                if not target then
                    target, act_id = conflict_citizen(by, u.id)
                    if target then how = 'conflict' end
                end
                if target then
                    local before = field(u.counters, 'soldier_mood_countdown')
                    local done = false
                    if on and not dry and type(before) == 'number' and before > 1 then
                        done = pcall(function() u.counters.soldier_mood_countdown = 1 end)
                        if done then
                            ended = ended + 1
                            bump(S, 'tantrums_ended')
                        end
                    end
                    local last = S.tantrum_logged[u.id]
                    if not (last and now - last >= 0 and now - last < TANTRUM_LOG_TICKS) then
                        S.tantrum_logged[u.id] = now
                        bump(S, 'tantrum_attacks')
                        local mood = nil
                        pcall(function() mood = df.soldier_mood_type[u.counters.soldier_mood] end)
                        log(S, {kind = 'tantrum_ended', tick = now, id = u.id, name = unit_name(u),
                                mood = mood, target = target.id, target_name = unit_name(target), how = how,
                                countdown = before, ended = done, off = (not on) or nil, dry = dry or nil,
                                suffocation = field(field(target, 'counters'), 'suffocation'),
                                activity_id = act_id, opponent_timer = field(field(u, 'opponent'), 'timer'),
                                attack = attack_row(at)})
                    end
                end
            else
                -- (item3) a calm citizen's attacks: all of this pass's seen first (a
                -- mutual pair is both ways in the same ticks), judged below
                for _, h in ipairs(hits) do
                    local target = living_citizen(h.target)
                    if target then
                        S.attack_seen[tostring(u.id) .. '>' .. tostring(target.id)] = now
                        table.insert(calm, {u = u, target = target, h = h})
                    end
                end
            end
        end
    end
    local tidx = nil
    for _, c in ipairs(calm) do
        local u, target, h = c.u, c.target, c.h
        tidx = tidx or training_index()
        local why, what = spar_reason(S, by, u, target, now, tidx)
        if why then
            -- (item3) sparring: counted once a pair a ATTACK_LOG_TICKS, kept out of the log
            local lo, hi = math.min(u.id, target.id), math.max(u.id, target.id)
            local key = tostring(lo) .. '~' .. tostring(hi)
            local last = S.spar_logged[key]
            if not (last and now - last >= 0 and now - last < ATTACK_LOG_TICKS) then
                S.spar_logged[key] = now
                bump(S, 'spars')
                table.insert(S.spars_recent, {tick = now, id = u.id, name = unit_name(u), target = target.id,
                                              target_name = unit_name(target), why = why, what = what})
                while #S.spars_recent > SPAR_RECENT_KEEP do table.remove(S.spars_recent, 1) end
            end
        else
            local key = tostring(u.id) .. '>' .. tostring(target.id)
            local last = S.attack_logged[key]
            if not (last and now - last >= 0 and now - last < ATTACK_LOG_TICKS) then
                S.attack_logged[key] = now
                bump(S, 'attacks')
                log(S, {kind = 'attack', tick = now, id = u.id, name = unit_name(u), target = target.id,
                        target_name = unit_name(target), job = job_of(u),
                        suffocation = field(field(target, 'counters'), 'suffocation'),
                        attack = attack_row(h.attack)})
            end
        end
    end
    for id, t in pairs(S.tantrum_logged) do if now - t >= TANTRUM_LOG_TICKS or now < t then S.tantrum_logged[id] = nil end end
    for k, t in pairs(S.attack_logged) do if now - t >= ATTACK_LOG_TICKS or now < t then S.attack_logged[k] = nil end end
    for k, t in pairs(S.attack_seen) do if now - t > MUTUAL_TICKS or now < t then S.attack_seen[k] = nil end end
    for k, t in pairs(S.spar_logged) do if now - t >= ATTACK_LOG_TICKS or now < t then S.spar_logged[k] = nil end end
    return ended
end

-- --- one pass ---------------------------------------------------------------

-- opts: {dry = true: read and log, change nothing}. Returns what it did.
function pass(now, opts)
    local S = state()
    opts = opts or {}
    now = now or game_tick()
    local dry = opts.dry == true or S.dry == true
    local done = {conflicts = 0, ours = 0, capped = 0, separated = 0, tantrums_ended = 0}
    local list = conflicts()
    S.counts.passes = S.counts.passes + 1
    -- (item3) the tantrums that attack citizens, before the conflicts (and when there are none)
    local okt, n = pcall(scan_units, S, now, dry, list)
    if okt then
        done.tantrums_ended = n or 0
    else
        S.error = 'tantrums: ' .. tostring(n):sub(1, 160)
        S.counts.errors = S.counts.errors + 1
    end
    if #list == 0 then
        S.seen = {}
        return done
    end
    -- judge every conflict first: a unit in one that is not ours is never separated
    local judged, foreign = {}, {}
    for _, c in ipairs(list) do
        local j = judge(c.ev)
        j.act, j.ev = c.act, c.ev
        table.insert(judged, j)
        if not j.ours then
            -- (0.105.106) why each unit is kept: the other conflict, its reason and the unit behind it
            local who = j.why_id and find_unit(j.why_id) or nil
            local note = {act = c.act, why = j.why, who = j.why_id, who_name = who and unit_name(who) or nil}
            for _, id in ipairs(j.ids) do foreign[id] = foreign[id] or note end
        end
    end
    local live = {}
    local mo = nil
    for _, j in ipairs(judged) do
        done.conflicts = done.conflicts + 1
        if j.ours then
            done.ours = done.ours + 1
            local key = tostring(j.act) .. ':' .. tostring(field(j.ev, 'event_id'))
            live[key] = true
            local lv, max = levels_of(j.ev)
            local rec = S.seen[key]
            local entry = nil
            if not rec then
                rec = {first = now, act = j.act}
                S.seen[key] = rec
                S.counts.seen = S.counts.seen + 1
                entry = {kind = 'seen'}
            end
            local sig = sig_of(j.ids, lv)
            if rec.sig ~= sig and not entry then entry = {kind = 'change'} end
            rec.sig, rec.last = sig, now
            if j.died and not rec.died then
                rec.died = true
                S.counts.died = S.counts.died + 1
                entry = entry or {kind = 'change'}
                entry.died = true
            end
            if max and max > BRAWL then rec.lethal = true end
            local fighting = max ~= nil and max >= BRAWL
            local capped = 0
            if fighting and max > BRAWL then
                for _, side in ipairs(vec_list(field(j.ev, 'sides'))) do
                    for _, e in ipairs(vec_list(field(side, 'enemies'))) do
                        local l = field(e, 'conflict_level')
                        if type(l) == 'number' and l > BRAWL then
                            if not dry then
                                local okw = pcall(function() e.conflict_level = BRAWL end)
                                if okw then capped = capped + 1 end
                            else
                                capped = capped + 1
                            end
                        end
                    end
                end
            end
            local reeng = false
            for _, r in ipairs(j.units) do
                local t = S.recent[r.id]
                if t and now - t >= 0 and now - t <= REENGAGE_TICKS then
                    reeng = true
                end
            end
            local separate = fighting and (rec.lethal or rec.died or reeng
                or (now - rec.first) > (S.separate_ticks or FIGHT_SEPARATE_TICKS))
            local removed, kept = {}, {}
            if separate then
                if not dry then mo = mo or makeown() end
                for _, r in ipairs(j.units) do
                    if r.kind == 'citizen' then
                        if foreign[r.id] then
                            table.insert(kept, r.id)
                        elseif dry then
                            table.insert(removed, r.id)
                        elseif mo then
                            local ok, res = pcall(mo.remove_from_conflict, r.u)
                            if ok then
                                table.insert(removed, r.id)
                                S.recent[r.id] = now
                            else
                                S.error = 'remove_from_conflict: ' .. tostring(res):sub(1, 120)
                            end
                        end
                    end
                end
                if not dry and not mo then S.error = 'no makeown.remove_from_conflict in this DFHack' end
            end
            if capped > 0 or #removed > 0 then entry = entry or {kind = 'change'} end
            if entry then
                entry.tick, entry.activity_id, entry.event_id = now, j.act, field(j.ev, 'event_id')
                entry.units = unit_rows(j)
                entry.levels = lv
                entry.max = max
                entry.timers = timers_of(j.ev)
                entry.age = now - rec.first
                if capped > 0 then
                    entry.capped = capped
                    entry.levels_after = (levels_of(j.ev))
                end
                if #removed > 0 then entry.separated = removed end
                if #kept > 0 then
                    entry.kept = kept
                    local why = {}
                    for _, id in ipairs(kept) do
                        local f = foreign[id]
                        if type(f) == 'table' then
                            table.insert(why, {id = id, act = f.act, why = f.why, who = f.who, who_name = f.who_name})
                        end
                    end
                    if #why > 0 then entry.kept_why = why end
                end
                if reeng then entry.reengaged = true end
                if dry then entry.dry = true end
                log(S, entry)
            end
            if not dry then
                S.counts.capped = S.counts.capped + capped
                if #removed > 0 then
                    S.counts.separated = S.counts.separated + #removed
                    if reeng then S.counts.reengaged = S.counts.reengaged + 1 end
                    rec.sep_at = now
                    rec.separations = (rec.separations or 0) + 1
                end
            end
            done.capped = done.capped + capped
            done.separated = done.separated + #removed
        end
    end
    for k in pairs(S.seen) do if not live[k] then S.seen[k] = nil end end
    for id, t in pairs(S.recent) do if now - t > REENGAGE_TICKS or now < t then S.recent[id] = nil end end
    return done
end

-- --- the loop -----------------------------------------------------------------

function alive()
    local S = state()
    if not (S.on and S.timer) then return false end
    if type(dfhack.timeout_active) ~= 'function' then return true end
    local ok, active = pcall(dfhack.timeout_active, S.timer)
    return (ok and active) and true or false
end

-- each arming makes its own beat, keyed by a fresh token: a beat whose token
-- is no longer the state's (disarmed, armed again, a newer load) ends there
local function make_beat(token)
    local beat
    beat = function()
        local S = state()
        if S.token ~= token then return end
        S.timer = nil
        if not S.on then return end
        if not halted() then
            local ok, err = pcall(pass)
            if not ok then
                S.error = tostring(err):sub(1, 200)
                S.counts.errors = S.counts.errors + 1
            end
        end
        local okt, id = pcall(dfhack.timeout, S.ticks or FIGHT_WATCH_TICKS, 'ticks', beat)
        S.timer = okt and id or nil
    end
    return beat
end

local function arm(S)
    if alive() and S.code == CODE then return false end
    S.code, S.token = CODE, {}
    S.on = true
    local okt, id = pcall(dfhack.timeout, S.ticks or FIGHT_WATCH_TICKS, 'ticks', make_beat(S.token))
    S.timer = okt and id or nil
    if not okt then S.error = 'dfhack.timeout: ' .. tostring(id):sub(1, 120) end
    return S.timer ~= nil
end

local function whole(v, lo, hi)
    if type(v) ~= 'number' or v ~= math.floor(v) or v < lo or v > hi then return nil end
    return math.floor(v)
end

local function brief(S)
    return {ok = true, armed = alive(), on = S.on or false, ticks = S.ticks, separate_ticks = S.separate_ticks,
            end_tantrums = S.end_tantrums ~= false, counts = S.counts}
end

-- the fight_watch action
function act(a)
    a = a or {}
    if type(a.on) ~= 'boolean' then return {ok = false, rejected = true, error = 'fight_watch needs on = true or false'} end
    local ticks, sep = FIGHT_WATCH_TICKS, FIGHT_SEPARATE_TICKS
    if a.ticks ~= nil then
        ticks = whole(a.ticks, 1, 1200)
        if not ticks then return {ok = false, rejected = true, error = 'fight_watch: ticks is 1-1200'} end
    end
    if a.separate_ticks ~= nil then
        sep = whole(a.separate_ticks, 0, 12000)
        if not sep then return {ok = false, rejected = true, error = 'fight_watch: separate_ticks is 0-12000'} end
    end
    if a.end_tantrums ~= nil and type(a.end_tantrums) ~= 'boolean' then
        return {ok = false, rejected = true, error = 'fight_watch: end_tantrums is true or false'}
    end
    local S = state()
    if a.dry_run == true then
        local r = brief(S)
        r.dry_run, r.would = true, a.on and (alive() and 'update' or 'arm') or (S.on and 'disarm' or 'nothing')
        return r
    end
    if a.ticks ~= nil or S.ticks == nil then S.ticks = ticks end
    if a.separate_ticks ~= nil or S.separate_ticks == nil then S.separate_ticks = sep end
    if a.on then
        S.end_tantrums = a.end_tantrums ~= false       -- (item3) on unless the action says false
        local was = alive()
        local started = arm(S)
        local r = brief(S)
        r.started = started or nil
        r.already = (was and not started) or nil
        return r
    end
    S.on, S.token = false, nil                     -- the pending beat ends the loop
    S.timer = nil
    S.seen, S.recent = {}, {}
    return brief(S)
end

-- the `fights` section
function report()
    local S = state()
    local out = {armed = alive(), on = S.on or false, ticks = S.ticks, separate_ticks = S.separate_ticks,
                 end_tantrums = S.end_tantrums ~= false, counts = S.counts, error = S.error, log = {}, now = {},
                 spars_recent = S.spars_recent or {}}     -- (item3) the last sparring pairs (never in the log)
    for i = math.max(1, #S.log - REPORT_LOG + 1), #S.log do table.insert(out.log, S.log[i]) end
    local now = game_tick()
    for _, c in ipairs(conflicts()) do
        local j = judge(c.ev)
        if j.ours then
            local lv, max = levels_of(c.ev)
            local key = tostring(c.act) .. ':' .. tostring(field(c.ev, 'event_id'))
            local rec = S.seen[key]
            table.insert(out.now, {activity_id = c.act, units = unit_rows(j), levels = lv, max = max,
                                   timers = timers_of(c.ev), age = rec and (now - rec.first) or nil,
                                   separations = rec and rec.separations or nil})
        end
    end
    return out
end
