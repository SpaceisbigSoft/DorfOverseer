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
    end
end

local function game_tick()
    local ok, t = pcall(function()
        return df.global.cur_year * 403200 + df.global.cur_year_tick
    end)
    return ok and type(t) == 'number' and t or nil
end

function mark_seen()
    LAST_SEEN = os.time()
    SEEN_TICK = game_tick() or SEEN_TICK
    pcall(away_watch_start)
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
