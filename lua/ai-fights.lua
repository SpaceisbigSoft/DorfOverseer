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
--   act(a)        the fight_watch action {on, ticks?, separate_ticks?, dry_run?}
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
STATE_KEY = 'ai_overseer_fight_watch'
YEAR = 403200

local CODE = {}              -- this load of the file (a newer load takes the loop over)

local function game_tick()   -- (U.abs_tick's reading, here so the timer needs no other module)
    local ok, t = pcall(function() return df.global.cur_year * YEAR + df.global.cur_year_tick end)
    return ok and t or 0
end

local function fresh_state()
    return {on = false, ticks = FIGHT_WATCH_TICKS, separate_ticks = FIGHT_SEPARATE_TICKS,
            counts = {seen = 0, capped = 0, separated = 0, reengaged = 0, passes = 0, errors = 0, died = 0},
            seen = {}, recent = {}, log = {}, file_lines = nil}
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

-- --- one pass ---------------------------------------------------------------

-- opts: {dry = true: read and log, change nothing}. Returns what it did.
function pass(now, opts)
    local S = state()
    opts = opts or {}
    now = now or game_tick()
    local dry = opts.dry == true or S.dry == true
    local done = {conflicts = 0, ours = 0, capped = 0, separated = 0}
    local list = conflicts()
    S.counts.passes = S.counts.passes + 1
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
        if not j.ours then for _, id in ipairs(j.ids) do foreign[id] = true end end
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
                if #kept > 0 then entry.kept = kept end
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
            counts = S.counts}
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
    local S = state()
    if a.dry_run == true then
        local r = brief(S)
        r.dry_run, r.would = true, a.on and (alive() and 'update' or 'arm') or (S.on and 'disarm' or 'nothing')
        return r
    end
    if a.ticks ~= nil or S.ticks == nil then S.ticks = ticks end
    if a.separate_ticks ~= nil or S.separate_ticks == nil then S.separate_ticks = sep end
    if a.on then
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
                 counts = S.counts, error = S.error, log = {}, now = {}}
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
