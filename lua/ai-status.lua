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

-- A different fort: forget the last one's report and answers.
dfhack.onStateChange['ai-status'] = function(sc)
    if sc == SC_MAP_UNLOADED then
        STATUS, DECISIONS, LAST_SEEN = nil, {}, nil
    end
end

function mark_seen()
    LAST_SEEN = os.time()
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
    return on == true
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
