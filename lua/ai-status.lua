-- What the AI overseer is doing, for the on-screen panel (lua/ai-overlay.lua),
-- plus the in-game controls: the halt switch and your answers to the
-- co-pilot's questions.
--
-- STATUS and DECISIONS live in memory only (they are rebuilt every in-game
-- day by the overseer). The halt switch is saved with the fort, so a halted
-- AI stays halted after a reload.
--@ module = true

HALT_KEY = 'ai-overseer/halt'
MAX_LINES = 5
MAX_PENDING = 3

STATUS = STATUS                 -- last report from the overseer (nil until the first)
DECISIONS = DECISIONS or {}     -- pending id -> 'yes' | 'no'
LAST_SEEN = LAST_SEEN           -- os.time() the overseer last checked in (every ~2 s)
SEEN_TICK = SEEN_TICK           -- (0.105.48, K3) the game tick of that check-in
AWAY = AWAY or {}               -- (0.105.48, K3) the away watcher: {first, last, timer, result, why}

-- A different fort: forget the last one's report and answers.
dfhack.onStateChange['ai-status'] = function(sc)
    if sc == SC_MAP_UNLOADED then
        STATUS, DECISIONS, LAST_SEEN = nil, {}, nil
        SEEN_TICK, AWAY = nil, {}
        local D = rawget(_G, 'ai_status_deadman_state')
        if type(D) == 'table' then D.hold_until, D.fired_for, D.last_gap_s = nil, nil, nil end
    end
end

local function game_tick()
    local ok, t = pcall(function()
        return df.global.cur_year * 403200 + df.global.cur_year_tick
    end)
    return ok and type(t) == 'number' and t or nil
end

function mark_seen()
    local now = os.time()
    pcall(deadman_seen, now, LAST_SEEN)
    LAST_SEEN = now
    SEEN_TICK = game_tick() or SEEN_TICK
    pcall(away_watch_start)
    pcall(deadman_start)
end

-- Plain printable text only, capped (it comes from outside the game).
local function clean(v, max)
    if type(v) ~= 'string' then return nil end
    v = v:gsub('[%c]', ' ')
    return v:sub(1, max or 120)
end

local function clean_list(v, max_items, max_len)
    local out = {}
    for _, s in ipairs(type(v) == 'table' and v or {}) do
        local t = clean(s, max_len)
        if t and #out < max_items then table.insert(out, t) end
    end
    return out
end

function is_halted()
    if not dfhack.isMapLoaded() then return false end
    local d = dfhack.persistent.getSiteData(HALT_KEY, {halted = false})
    return type(d) == 'table' and d.halted == true
end

function set_halted(on)
    dfhack.persistent.saveSiteData(HALT_KEY, {halted = on == true})
    local msg = on and 'AI Overseer HALTED: it will not change anything until you resume (Ctrl-Shift-H).'
        or 'AI Overseer resumed.'
    pcall(dfhack.gui.showAnnouncement, msg, on and COLOR_LIGHTRED or COLOR_LIGHTGREEN, true)
    -- (0.105.48, K3) halting stands the AI down at once (even paused): its
    -- own alarm lowered, its burrows let out; the gate watcher only opens now
    if on then pcall(away_check, true) end
    return on == true
end

---------------------------------------------------------------------------
-- (0.105.48, K3) The away watcher. The AI's alarm and burrows were let go
-- only by the brain: halted, or with the overseer stopped, they stayed (the
-- gate watcher alone had a brain-away rule). Every AWAY_LOOK_TICKS (a game
-- timer, started by the panel's update and by each status call, so it runs
-- after a reload with no overseer too): halted, or no status call for
-- AWAY_TICKS (and AWAY_REAL_S real seconds: ai-util brain_away), the AI stands down (ai-society stand_down: its own alarm
-- lowered, at once when halted, else once no enemy is in sight or after
-- AWAY_ALARM_MAX_TICKS; every member of its own burrows let out). Only the
-- AI's own: the player's alarm and burrows are never touched.
---------------------------------------------------------------------------
-- (0.105.48 round 2) One rule with the gate watcher's (ai-util brain_away):
-- away only with no status call for AWAY_TICKS game ticks (five days) AND
-- none for AWAY_REAL_S real seconds, so a slow live brain (one cycle taking
-- minutes, a slow fort's 2400-tick reports) is never read as away.
AWAY_TICKS = nil                -- ai-util's BRAIN_AWAY_TICKS (set below; nil: ai-util unread)
AWAY_REAL_S = nil               -- ai-util's BRAIN_AWAY_REAL_S
AWAY_LOOK_TICKS = 100

local function util()
    local ok, U = pcall(reqscript, 'ai-util')
    if ok and type(U) == 'table' and type(U.brain_away) == 'function' then return U end
    return nil
end
do
    local U = util()
    if U then AWAY_TICKS, AWAY_REAL_S = U.BRAIN_AWAY_TICKS, U.BRAIN_AWAY_REAL_S end
end

-- 'halted', 'away' or nil, and how long the overseer has been away (ticks).
-- real: the real time now (os.time(); tests)
function away_state(now, real)
    if is_halted() then return 'halted', 0 end
    now = now or game_tick()
    if type(now) ~= 'number' then return nil, 0 end
    AWAY.first = AWAY.first or now
    local seen = SEEN_TICK or AWAY.first
    if now < seen then                          -- an older save loaded: counted from now
        SEEN_TICK, AWAY.first, seen = nil, now, now
    end
    local U = util()
    if not U then return nil, now - seen end    -- the rule unread: never away by time
    if real == nil then
        local okr, r = pcall(os.time)
        real = okr and r or nil
    end
    if U.brain_away(now, seen, real, LAST_SEEN, AWAY_TICKS, AWAY_REAL_S) then return 'away', now - seen end
    return nil, now - seen
end

-- One look (force: whatever the time since the last). Returns the stand-down's
-- result when the AI stood down, else nil.
function away_check(force)
    if not dfhack.isMapLoaded() then return nil end
    local now = game_tick()
    if not force and AWAY.last and now and now >= AWAY.last and now - AWAY.last < AWAY_LOOK_TICKS then
        return nil
    end
    AWAY.last = now
    local why, ticks = away_state(now)
    AWAY.why = why
    local okm, S = pcall(reqscript, 'ai-society')
    if not okm or type(S) ~= 'table' then return nil end
    if not why then
        pcall(S.ai_alarm_mine)                  -- the alarm found off: its booking forgotten
        return nil
    end
    local ok, r = pcall(S.stand_down, {halted = why == 'halted', away_ticks = ticks})
    AWAY.result = ok and r or {error = tostring(r):sub(1, 160)}
    AWAY.tick = now
    return AWAY.result
end

local function away_tick()
    AWAY.timer = nil
    pcall(away_check)
    if dfhack.isMapLoaded() then
        AWAY.timer = dfhack.timeout(AWAY_LOOK_TICKS, 'ticks', away_tick)
    end
end

-- The watcher's timer started (once; DFHack drops 'ticks' timers at unload)
function away_watch_start()
    if not dfhack.isMapLoaded() or type(dfhack.timeout) ~= 'function' then return false end
    if AWAY.timer and type(dfhack.timeout_active) == 'function' then
        local ok, active = pcall(dfhack.timeout_active, AWAY.timer)
        if ok and active then return false end
    end
    AWAY.timer = dfhack.timeout(AWAY_LOOK_TICKS, 'ticks', away_tick)
    return true
end

---------------------------------------------------------------------------
-- (F5a) The dead-man pause. The keeper stopped or dead, the game ran on
-- unpaused with nobody at the wheel (DF's own announcement pauses are off).
-- Every DEADMAN_LOOK_TICKS (a 'ticks' timer: it only runs while the game
-- runs) the watcher looks at the overseer's last check-in (LAST_SEEN, real
-- time): older than DEADMAN_S real seconds, the game is paused, ONCE for that
-- check-in (a player who unpauses is not fought: it pauses again only after
-- a fresh check-in has gone stale too). Never before the first check-in on
-- this map (a fort loaded by hand, or by the keeper's revive before its
-- overseer is up: LAST_SEEN is forgotten when the map unloads), never while
-- the AI is halted (the game is the player's), never while the keeper holds
-- it (deadman_hold: its planned close, the save being written).
-- The loop keeps ai-fights' token + CODE pattern: a reloaded file takes the
-- loop over and the old load's pending beat ends there.
---------------------------------------------------------------------------
DEADMAN_S = 600                 -- the check-in this old (real seconds): the game paused (0: off)
DEADMAN_LOOK_TICKS = 100
DEADMAN_HOLD_MAX_S = 7200       -- a keeper's hold at most this long
local DEADMAN_KEY = 'ai_status_deadman_state'
local CODE = {}                 -- this load of the file (a newer load takes the loop over)

function deadman()
    local S = rawget(_G, DEADMAN_KEY)
    if type(S) ~= 'table' then
        S = {}
        rawset(_G, DEADMAN_KEY, S)
    end
    return S
end

local function real_now()
    local ok, t = pcall(os.time)
    return ok and type(t) == 'number' and t or nil
end

-- a check-in: the gap since the one before kept (the status reply's age is
-- otherwise always 0, the reply being itself a check-in); any hold ends (the
-- overseer is back: the planned close was put off)
function deadman_seen(now, before)
    local S = deadman()
    S.last_gap_s = (type(now) == 'number' and type(before) == 'number') and math.max(0, now - before) or nil
    S.hold_until = nil
end

-- the keeper's planned close: no pause for `seconds` (capped) from now; 0 ends it
function deadman_hold(seconds)
    local S = deadman()
    local s = tonumber(seconds)
    local now = real_now()
    if not s or s <= 0 or not now then
        S.hold_until = nil
        return false
    end
    S.hold_until = now + math.floor(math.min(s, DEADMAN_HOLD_MAX_S))
    return true
end

-- One look. now: the real time (os.time(); tests). Returns 'paused' when it
-- paused the game, else nil and why not.
function deadman_check(now)
    local S = deadman()
    if not dfhack.isMapLoaded() then return nil, 'no map' end
    if type(DEADMAN_S) ~= 'number' or DEADMAN_S <= 0 then return nil, 'off' end
    if type(LAST_SEEN) ~= 'number' then return nil, 'no check-in yet' end
    now = now or real_now()
    if type(now) ~= 'number' then return nil, 'no clock' end
    if S.hold_until and now < S.hold_until then return nil, 'held' end
    local age = now - LAST_SEEN
    if age < DEADMAN_S then return nil, 'fresh' end
    if S.fired_for == LAST_SEEN then return nil, 'done' end
    if is_halted() then return nil, 'halted' end
    S.fired_for = LAST_SEEN
    local okp, already = pcall(function() return df.global.pause_state end)
    if okp and already == true then
        S.found_paused_at = now
        return nil, 'already paused'
    end
    local ok, err = pcall(function() df.global.pause_state = true end)
    if not ok then
        S.error = tostring(err):sub(1, 160)
        return nil, 'error'
    end
    S.paused_at, S.paused_age_s = now, age
    local msg = ('AI Overseer: no check-in for %d min, game paused'):format(math.floor(age / 60))
    pcall(print, msg)
    pcall(dfhack.gui.showAnnouncement, msg, COLOR_LIGHTRED, true)
    return 'paused'
end

function deadman_alive()
    local S = deadman()
    if not S.timer then return false end
    if type(dfhack.timeout_active) ~= 'function' then return true end
    local ok, active = pcall(dfhack.timeout_active, S.timer)
    return (ok and active) and true or false
end

-- each arming makes its own beat, keyed by a fresh token: a beat whose token
-- is no longer the state's (armed again, a newer load) ends there
local function make_beat(token)
    local beat
    beat = function()
        local S = deadman()
        if S.token ~= token then return end
        S.timer = nil
        local ok, err = pcall(deadman_check)
        if not ok then S.error = tostring(err):sub(1, 160) end
        if dfhack.isMapLoaded() then
            local okt, id = pcall(dfhack.timeout, DEADMAN_LOOK_TICKS, 'ticks', beat)
            S.timer = okt and id or nil
        end
    end
    return beat
end

-- The watcher's timer started (by each check-in; DFHack drops 'ticks' timers
-- at unload, and a reloaded file takes the loop over). True when armed now.
function deadman_start()
    if not dfhack.isMapLoaded() or type(dfhack.timeout) ~= 'function' then return false end
    local S = deadman()
    if deadman_alive() and S.code == CODE then return false end
    S.code, S.token = CODE, {}
    local okt, id = pcall(dfhack.timeout, DEADMAN_LOOK_TICKS, 'ticks', make_beat(S.token))
    S.timer = okt and id or nil
    if not okt then S.error = 'dfhack.timeout: ' .. tostring(id):sub(1, 120) end
    return S.timer ~= nil
end

-- For the status reply (the brain sees it): armed (a check-in seen, the
-- watcher's timer live), the gap before this check-in, the last pause.
function deadman_state(now)
    local S = deadman()
    now = now or real_now()
    local function ago(t) return (type(t) == 'number' and type(now) == 'number') and now - t or nil end
    return {
        armed = type(DEADMAN_S) == 'number' and DEADMAN_S > 0 and type(LAST_SEEN) == 'number' and deadman_alive(),
        after_s = DEADMAN_S,
        last_checkin_age_s = S.last_gap_s,
        paused_at = S.paused_at,
        paused_ago_s = ago(S.paused_at),
        found_paused_at = S.found_paused_at,
        held_s = (S.hold_until and type(now) == 'number' and S.hold_until > now) and S.hold_until - now or nil,
        error = S.error,
    }
end

-- The overseer's report. Returns the decisions it hasn't seen yet and
-- forgets the ones it says it has acted on.
function set_status(t)
    if type(t) ~= 'table' then return nil, 'status must be an object' end
    local pending = {}
    for _, p in ipairs(type(t.pending) == 'table' and t.pending or {}) do
        if type(p) == 'table' and #pending < MAX_PENDING then
            local id, text = clean(p.id, 16), clean(p.text, 100)
            if id and id:match('^[%w]+$') and text then
                table.insert(pending, {id = id, text = text})
            end
        end
    end
    for _, id in ipairs(type(t.ack) == 'table' and t.ack or {}) do
        if type(id) == 'string' then DECISIONS[id] = nil end
    end
    -- (F5a) the dead-man pause's limit, when the overseer sends one (0: off)
    local dm = tonumber(t.deadman_s)
    if dm and dm == math.floor(dm) and (dm == 0 or (dm >= 60 and dm <= 86400)) then DEADMAN_S = dm end
    STATUS = {
        mode = clean(t.mode, 20) or '?',
        acting = clean(t.acting, 40) or '?',
        date = clean(t.date, 40),
        last = clean_list(t.last, MAX_LINES, 90),
        notes = clean_list(t.notes, 2, 90),
        -- things only the player can do (set up a burrow, link a lever...)
        todo = clean_list(t.todo, 10, 160),
        building = clean_list(t.building, 2, 90),
        ai = clean(t.ai, 90),
        tokens = type(t.tokens) == 'table' and {
            saved = math.tointeger(tonumber(t.tokens.saved)) or 0,
            today = math.tointeger(tonumber(t.tokens.today)) or 0,
            total = math.tointeger(tonumber(t.tokens.total)) or 0,
        } or nil,
        pending = pending,
        unattended = t.unattended == true,      -- (0.104.88) the camera director runs only then
        received = os.time(),
    }
    return true
end

function decide(id, yes)
    if type(id) == 'string' and id:match('^[%w]+$') then
        DECISIONS[id] = yes and 'yes' or 'no'
    end
end

function decisions()
    local out = {}
    for id, v in pairs(DECISIONS) do out[id] = v end
    return out
end
