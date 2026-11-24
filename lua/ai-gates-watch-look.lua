-- ai-gates-watch-look: the watcher's look (a lockdown that outlives its cause, the brain away),
-- check(), arm(), open_all(), the restored lockdown; planned gate buildings; doors.
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-watch-look'] = '0.105.98'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, gate_name, lever_pull_pending, pull, set_entrance = U, gate_name, lever_pull_pending, pull, set_entrance   -- (r9) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- (0.105.47, J16) A lockdown that outlives its cause. Live 14 Nov 17:33
-- (War-hold): the keepers stopped 13 Nov, yet the watcher's timer went on in
-- DF holding a lockdown (its peak unknown after a restore, so may_reopen
-- never passed); the player pulled the three AI gate levers open and within
-- seconds its "lost close" re-pulls shut them again. A messenger and a squad
-- could never leave. So:
--   * the peak alone no longer keeps an entrance shut for ever: with no
--     invader, no great danger and nothing within WIDE, it opens after
--     LIFT_CHECKS clear looks (a day; half a day, REOPEN_CHECKS, with the
--     brain away);
--   * the brain away (no report for UNATTENDED_TICKS: GATES.brain_tick, set by
--     each `entrances` report): the watcher shuts only for a danger within
--     IMMINENT and opens what it holds once none is within 2 * IMMINENT for
--     UNATTENDED_CLEAR looks (the cavern seal still keeps what it holds);
--   * a gate it holds found open again (the player's pull, a lost job) with
--     no danger within WIDE is left open and the entrance unbooked: never
--     pulled back shut against the player.
---------------------------------------------------------------------------
LIFT_CHECKS = 2 * REOPEN_CHECKS
-- (0.105.48, K2) a slow unattended fort reports only every 2400 ticks (1200
-- x perf_slow_cycle_factor) and one failed cycle leaves more: two days read a
-- live brain as away. Away now needs both: no `entrances` report for
-- UNATTENDED_TICKS (five game days) and no status poll from the overseer (its
-- 2 s heartbeat, brain_ping) for UNATTENDED_REAL_S real seconds (never pinged:
-- the game ticks alone decide)
UNATTENDED_TICKS = U.BRAIN_AWAY_TICKS or 6000     -- (round 2) ai-util's, one value for both away watchers
UNATTENDED_REAL_S = U.BRAIN_AWAY_REAL_S or 180
UNATTENDED_CLEAR = 2
BRAIN_PING = BRAIN_PING or {}     -- {t = os.time() of the overseer's last status poll}: kept across a rescan

local function now_abs()
    local ok, t = pcall(U.abs_tick)
    return ok and t or nil
end

local function real_now()
    local ok, t = pcall(os.time)
    return ok and type(t) == 'number' and t or nil
end

-- The brain away? (no `entrances` report for UNATTENDED_TICKS, and no status
-- poll for UNATTENDED_REAL_S real seconds.) real: the real time now (tests)
-- (0.105.48 round 2) the rule itself is ai-util's brain_away, shared with
-- ai-status's away watcher
function brain_away(now, real)
    now = now or now_abs()
    return U.brain_away(now, GATES.brain_tick, real or real_now(), BRAIN_PING.t,
                        UNATTENDED_TICKS, UNATTENDED_REAL_S)
end

-- (0.105.48, K2) Called by the bridge's `status` (the overseer's 2 s poll)
function brain_ping()
    BRAIN_PING.t = real_now() or BRAIN_PING.t
    return BRAIN_PING.t
end

-- (0.105.48, K3) The AI halted in the game (ai-status; false when it can't
-- be read). While halted the watcher's looks only release: nothing is shut
-- or pulled back shut, and what it holds opens by the brain-away rule
-- (nothing within 2 * IMMINENT for UNATTENDED_CLEAR looks), so a halted fort
-- ends open, never flung open into a fight. The link watch and its levers wait.
function ai_halted()
    local ok, yes = pcall(function() return reqscript('ai-status').is_halted() end)
    return ok and yes == true
end

-- Called by each `entrances` report (ai-gates-stuck summary)
function brain_seen()
    GATES.brain_tick = now_abs() or GATES.brain_tick
end

-- (0.105.47, J16) Pure: may a held entrance open on this look? (looks: clear
-- looks so far, this one counted.) 'reopen' (the old rule), 'lift' (only the
-- peak held it), 'away' (the brain away, nothing within 2 * IMMINENT), or nil.
function lift_reason(nearest, invaders, great, peak, looks, away)
    if away then
        if nearest > 2 * IMMINENT and looks >= UNATTENDED_CLEAR then return 'away' end
        return nil
    end
    if may_reopen(nearest, invaders, great, peak) then
        return looks >= REOPEN_CHECKS and 'reopen' or nil
    end
    if invaders == 0 and (great or 0) == 0 and nearest > WIDE and looks >= LIFT_CHECKS then return 'lift' end
    return nil
end

-- Does this look count as clear for a held entrance?
local function clear_look(nearest, invaders, great, away)
    if away then return nearest > 2 * IMMINENT end
    return invaders == 0 and (great or 0) == 0 and nearest > WIDE
end

-- One look by the watcher: close what needs closing.
function check()
    if not GATES.armed or not GATES.entrances then return end
    local vis = visible_dangers()
    local ds, invaders, great = {}, 0, 0
    for _, d in ipairs(vis) do
        table.insert(ds, d.pos)
        if d.invader then invaders = invaders + 1 end
        if d.great then great = great + 1 end
    end
    if type(GATES.peak) == 'number' then GATES.peak = math.max(GATES.peak, #vis) end
    local outside = citizens_outside()
    GATES.clear_looks = GATES.clear_looks or {}
    GATES.opening = GATES.opening or {}
    local lure = lure_holds()                 -- (0.105.45)
    local away = brain_away()                 -- (0.105.47, J16) the brain away: real dangers only
    local halted = ai_halted()                -- (0.105.48, K3) halted: release only
    if halted then away = true end
    GATES.away = away or nil
    GATES.halted = halted or nil
    -- (0.105.47, J16) with the brain away, an entrance shuts only for a danger within IMMINENT
    local function close_for(nearest)
        if halted then return false end
        if away then return nearest <= IMMINENT end
        return should_close(nearest, outside)
    end
    for _, e in ipairs(GATES.entrances) do
        if next(lure) then
            for id in pairs(entrance_gate_ids(e)) do
                if lure[id] then goto continue end
            end
        end
        if not GATES.closed[e.id] then GATES.opening[e.id] = nil end
        if GATES.opening[e.id] and #e.equipment > 0 then
            -- (0.105.33) being opened (a dwarf on the way to the lever): its
            -- bridge still up, or down already, isn't a lost close. Danger
            -- comes: closed again; else the opening tried again (pulls only
            -- what is still up and still), and done once every gate is open
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            GATES.clear_looks[e.id] = nil
            -- (0.105.47) held open for a mission's travellers: only an enemy
            -- within IMMINENT shuts it again while it opens
            local okh0, held0 = pcall(function() return reqscript('ai-mission-way').mission_held(e.id) end)
            local close_now = close_for(nearest)
            if okh0 and held0 == true then close_now = nearest <= IMMINENT and not halted end
            if close_now then
                GATES.opening[e.id] = nil
                set_entrance(e, true, true)        -- (0.105.36 fix) its queued opening pull taken away
                pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s closed again while opening (danger %s tiles away)')
                    :format(gate_name(e), nearest == math.huge and '?' or tostring(nearest)), COLOR_YELLOW, true)
            else
                set_entrance(e, false)
            end
        elseif GATES.closed[e.id] and #e.equipment > 0 then
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            -- (0.105.47, J16) lift_reason: the old reopen, or the peak's cap, or the brain away
            if clear_look(nearest, invaders, great, away) then
                GATES.clear_looks[e.id] = (GATES.clear_looks[e.id] or 0) + 1
                local why = lift_reason(nearest, invaders, great, GATES.peak, GATES.clear_looks[e.id], away)
                -- (0.105.26 seal fix) not while the cavern seal holds any of
                -- its gates (a hidden forgotten beast is out of sight, not
                -- gone): kept shut, and opened at the first look after the seal
                if why and sealed_entrance(e) then
                    GATES.seal_kept = (GATES.seal_kept or 0) + 1
                elseif why then
                    GATES.clear_looks[e.id] = nil
                    set_entrance(e, false)
                    GATES.reopened = (GATES.reopened or 0) + 1
                    if why ~= 'reopen' then
                        GATES.lifted = GATES.lifted or {}
                        GATES.lifted[why] = (GATES.lifted[why] or 0) + 1
                    end
                    pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s opened again (no danger in sight, %d citizens outside%s)')
                        :format(gate_name(e), outside, why == 'away' and '; the overseer is away' or ''), COLOR_GREEN, true)
                    goto continue
                end
            else
                GATES.clear_looks[e.id] = nil
            end
        end
        local watched = {}                    -- (0.105.23) the gatehouse's bridge watched too
        for _, g in ipairs(e.equipment) do table.insert(watched, g) end
        for _, g in ipairs(e.outer or {}) do table.insert(watched, g) end
        local repulled, drift_open, drift_let = {}, false, false
        -- (0.105.47, J16) found open with no danger within WIDE (the player
        -- pulled its lever, a job was lost): left open, never pulled back shut
        local near_e = math.huge
        for _, p in ipairs(ds) do near_e = math.min(near_e, distance_to(e, p)) end
        local let_open = near_e > WIDE or (away and near_e > IMMINENT) or halted
        local held_by_seal = nil
        for _, g in ipairs(watched) do
            local b = df.building.find(g.id)
            GATES.gone_ids = GATES.gone_ids or {}
            GATES.repulled = GATES.repulled or {}
            if not b then
                -- (0.104.139) a gate gone (Teacheroar's hatch 278, toppled in a
                -- tantrum) left the entrance open until the weekly scan: scan
                -- again (once for each one gone)
                if not GATES.gone_ids[g.id] then
                    GATES.gone_ids[g.id] = true
                    GATES.scanned = false
                    GATES.gone = (GATES.gone or 0) + 1
                end
            elseif GATES.opening[e.id] then
                -- (0.105.33) being opened: none of its gates is pulled back shut
            elseif not ai_piece(e, g) then
                -- (0.105.36 fix) the player's piece: never pulled by the watcher
            elseif GATES.closed[e.id] and g.kind == 'bridge' and g.lever_id then
                -- (0.104.139) closed, but the pull's job was lost: the bridge is
                -- still down, not moving. Pulled again, not within 10 checks of
                -- the last (a pull is a dwarf's job: a second undoes the first)
                local ok, still = pcall(function()
                    local f = b.gate_flags
                    return not f.raised and not f.raising and not f.lowering
                end)
                local now = df.global.cur_year_tick or 0
                local last = GATES.repulled[g.id]
                held_by_seal = held_by_seal or seal_holds()
                -- (0.105.48, K2) the watcher's own close pull still on its way (queued
                -- at the lever, or pulled within the last 10 looks): not "found open"
                local own_pull = lever_pull_pending(g.lever_id)
                local cp = GATES.close_pulled and GATES.close_pulled[g.id]
                local tnow = now_tick_abs()
                if not own_pull and cp and tnow and tnow >= cp and tnow - cp <= 10 * CHECK_TICKS then own_pull = true end
                if ok and still and let_open and not seal_has(held_by_seal, g) then
                    if not own_pull then
                        drift_open, drift_let = true, true
                        GATES.let_open = (GATES.let_open or 0) + 1
                    end                 -- (else: the own pull on its way, no danger near: waited for)
                elseif ok and still and #b.jobs == 0 and (not last or now < last or now - last > 10 * CHECK_TICKS) then
                    GATES.repulled[g.id] = now
                    pcall(pull, g.lever_id)
                end
            elseif GATES.closed[e.id] and g.kind ~= 'bridge' and g.lever_driven and g.drive_lever
                    and door_shut(b) == false then
                -- (0.105.26 seal fix) a lever's hatch the watcher holds shut
                -- reads open (the seal opened it, the player pulled it, a pull
                -- went astray): its lever pulled again, at once. Still open
                -- after: the watcher's view corrected (not closed), so its
                -- next look decides again
                held_by_seal = held_by_seal or seal_holds()
                if let_open and not seal_has(held_by_seal, g) then
                    GATES.let_open = (GATES.let_open or 0) + 1
                    drift_let = true
                elseif not repulled[g.drive_lever] then
                    repulled[g.drive_lever] = true
                    local okp, done = pcall(pull_instant, g.drive_lever)
                    GATES.hatch_repulled = (GATES.hatch_repulled or 0) + 1
                    if not (okp and done) then drift_open = true end
                end
                if door_shut(b) == false then drift_open = true end
            end
        end
        if drift_open then
            -- (0.105.48, K2) found open with no danger near (drift_let): the
            -- entrance's other pieces the AI shut are opened too (left shut and
            -- forgotten, the AI called its own lock the player's); a queued
            -- close pull is taken away. Kept booked only while a piece is still
            -- on its way down or the cavern seal holds one (set_entrance says)
            if drift_let then
                pcall(set_entrance, e, false)
            else
                GATES.closed[e.id] = nil
            end
            -- the pieces open now aren't the AI's shut ones; those still shut stay its own
            if type(GATES.mine) == 'table' then
                for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
                    for _, g in ipairs(list) do
                        local b = df.building.find(g.id)
                        if not b or piece_shut(g, b) == false then GATES.mine[g.id] = nil end
                    end
                end
            end
            GATES.clear_looks[e.id] = nil
        end
        if not GATES.closed[e.id] and #e.equipment > 0 then
            local nearest = math.huge
            for _, p in ipairs(ds) do nearest = math.min(nearest, distance_to(e, p)) end
            -- (0.105.47) a way opened for a mission's travellers (the
            -- messenger, a squad walking off the map) isn't shut on the
            -- "danger coming, nobody outside" look while its hold lasts
            -- (lua/ai-mission-way.lua); an enemy within IMMINENT still shuts it
            local okh, held = pcall(function() return reqscript('ai-mission-way').mission_held(e.id) end)
            if okh and held == true and nearest > IMMINENT then
                GATES.mission_held_skips = (GATES.mission_held_skips or 0) + 1
            elseif close_for(nearest) then
                set_entrance(e, true)
                -- (0.105.36 fix) said only when the AI shut something (gates the
                -- player shut already stay theirs: not booked, not said)
                if GATES.closed[e.id] then
                    pcall(dfhack.gui.showAnnouncement, ('AI Overseer: %s closed (danger %s tiles away, %d citizens outside)')
                        :format(gate_name(e), nearest == math.huge and '?' or tostring(nearest), outside), COLOR_YELLOW, true)
                end
            else
                -- (0.105.23) open while the watcher doesn't shut it: a lever's
                -- hatch its link shut is opened (citizens outside get back in)
                pcall(open_lever_hatches, e)
            end
        end
        ::continue::
    end
end

-- (0.104.81, 13c) a watcher that errors closes nothing: its error is kept
-- for the report (the brain says it) instead of vanishing in the pcall
local function watched_check()
    local ok, err = pcall(check)
    if ok then
        GATES.watch_error = nil
    else
        local w = GATES.watch_error or {n = 0}
        w.n, w.error, w.tick = w.n + 1, tostring(err):sub(1, 200), df.global.cur_year_tick
        GATES.watch_error = w
    end
end

local function tick()
    if not GATES.armed then return end
    watched_check()
    GATES.timer = dfhack.timeout(CHECK_TICKS, 'ticks', tick)
end

-- (0.105.33) from_save (gates_restore): {closed = {entrance id = true}, peak =
-- number or nil}: what the save says the watcher held is in place before its
-- first look (that look would open a saved-shut lever hatch), and the peak
-- comes back (unknown, nil, keeps a restored lockdown shut)
function arm(from_save)
    if not GATES.scanned then return {ok = false, rejected = true, error = 'entrances not scanned yet'} end
    if not GATES.armed then
        -- (0.100, review) gates still waiting to open: forgotten; the watcher
        -- closes what needs closing from the bridges as they stand.
        -- (0.105.36, D2) except an entrance still being opened (a bridge up
        -- with someone on it, a pull on its way): kept closed and opening, so
        -- it stays the AI's and the watcher's look goes on opening it (or
        -- shuts it again if danger comes); forgotten, it read as the player's
        if GATES.reopen_timer then pcall(dfhack.timeout_active, GATES.reopen_timer, nil) end
        local kept = {}
        for id, v in pairs(GATES.opening or {}) do
            if v and GATES.closed and GATES.closed[id] then kept[id] = true end
        end
        GATES.reopen_timer, GATES.closed, GATES.opening = nil, {}, {}
        for id in pairs(kept) do GATES.closed[id], GATES.opening[id] = true, true end
        GATES.peak, GATES.clear_looks = 0, {}       -- (0.105.4 review) dangers seen at once since armed
        if type(from_save) == 'table' then
            for id, v in pairs(from_save.closed or {}) do if v then GATES.closed[id] = true end end
            for id, v in pairs(from_save.opening or {}) do
                if v and GATES.closed[id] then GATES.opening[id] = true end
            end
            GATES.peak = type(from_save.peak) == 'number' and from_save.peak or nil
        end
        GATES.armed = true
        GATES.brain_tick = GATES.brain_tick or now_abs()     -- (0.105.47, J16) counted from the arming
        -- (0.105.47, J16) a lockdown restored from the save, re-validated now:
        -- an entrance with no invader, no great danger and nothing within WIDE
        -- in sight is opened at once (its cause is gone; a restore's peak is unknown)
        if type(from_save) == 'table' and next(GATES.closed) ~= nil then
            pcall(lift_restored)
        end
        GATES.timer = dfhack.timeout(CHECK_TICKS, 'ticks', tick)
        watched_check()
    end
    return {ok = true, armed = true}
end

-- (0.105.47, J16) The restored lockdown's entrances whose danger is gone
-- (no invader or great danger in sight, nothing within WIDE): opened now.
-- The cavern seal's and the lure's stay. Returns how many.
function lift_restored()
    local okv, vis = pcall(visible_dangers)
    if not okv then return 0 end
    local invaders, great = 0, 0
    for _, d in ipairs(vis) do
        if d.invader then invaders = invaders + 1 end
        if d.great then great = great + 1 end
    end
    if invaders > 0 or great > 0 then return 0 end
    local lure, n = lure_holds(), 0
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed[e.id] and not sealed_entrance(e) then
            local lured = false
            for id in pairs(entrance_gate_ids(e)) do if lure[id] then lured = true end end
            local nearest = math.huge
            for _, d in ipairs(vis) do nearest = math.min(nearest, distance_to(e, d.pos)) end
            if not lured and nearest > WIDE then
                set_entrance(e, false)
                GATES.lifted_now = GATES.lifted_now or {}
                GATES.lifted_now[e.id] = true       -- (gates_restore doesn't book it again)
                n = n + 1
            end
        end
    end
    if n > 0 then GATES.restored_lifted = (GATES.restored_lifted or 0) + n end
    return n
end

-- (0.100, review) gates left closed when the rest opened (someone stood on
-- a bridge): tried again every CHECK_TICKS until they're open, or the
-- watcher is armed again
local function reopen_tick()
    GATES.reopen_timer = nil
    if GATES.armed or not GATES.closed or next(GATES.closed) == nil then return end
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed[e.id] then pcall(set_entrance, e, false) end
    end
    if next(GATES.closed) ~= nil then
        GATES.reopen_timer = dfhack.timeout(CHECK_TICKS, 'ticks', reopen_tick)
    end
end

function open_all()
    GATES.armed = false
    if GATES.timer then dfhack.timeout_active(GATES.timer, nil) end
    GATES.timer = nil
    local opened = 0
    for _, e in ipairs(GATES.entrances or {}) do
        if GATES.closed and GATES.closed[e.id] then
            set_entrance(e, false)
            if not GATES.closed[e.id] then opened = opened + 1 end
        end
    end
    GATES.closed = GATES.closed or {}
    pcall(open_lever_hatches)            -- (0.105.23) a lever's hatch its link shut
    local waiting = 0
    for _ in pairs(GATES.closed) do waiting = waiting + 1 end
    if waiting > 0 and not (GATES.reopen_timer and dfhack.timeout_active(GATES.reopen_timer)) then
        GATES.reopen_timer = dfhack.timeout(CHECK_TICKS, 'ticks', reopen_tick)
    end
    return {ok = true, opened = opened, waiting = waiting > 0 and waiting or nil}
end

-- Placing one building with quickfort; returns placed (bool) and, when it
-- isn't, what quickfort counted instead (e.g. build_unsuitable), so a refusal
-- can say why.
place_hook = nil       -- tests replace this
-- (v35 fix) The tiles where the AI planned a gate piece (a door, hatch,
-- wall, bridge), kept with the save ({"x,y,z", ...}): free_gate_jobs resumes
-- the suspended jobs of these only, never of what the player planned.
GATE_PLANNED_KEY = 'ai-overseer/gate_planned'
GATE_PLANNED_MAX = 400

-- (0.105.36, D2) a record is "x,y,z@building id" (the building the AI's
-- plan made there), or "x,y,z" (v35's, or the building unread): set maps
-- the tile to that id, or to true.
function gate_planned_records()
    local d = U.site_get(GATE_PLANNED_KEY, {})
    local list = type(d) == 'table' and type(d.tiles) == 'table' and d.tiles or {}
    local set = {}
    for _, k in ipairs(list) do
        local tile, id = tostring(k):match('^([%-%d]+,[%-%d]+,[%-%d]+)@(%d+)$')
        if tile then set[tile] = tonumber(id) else set[tostring(k)] = true end
    end
    return set, list
end

-- (0.105.36, D2) Is this planned building still unbuilt? nil if unread.
local function still_planned(b)
    local ok, yes = pcall(function() return b:getBuildStage() < b:getMaxBuildStage() end)
    if ok then return yes end
    return nil
end

-- (0.105.36, D2) Records whose building is gone or built forgotten (a
-- later building of the player's on that tile is theirs). One unread kept.
function prune_gate_planned(list)
    if not list then local _; _, list = gate_planned_records() end
    local out = {}
    for _, k in ipairs(list) do
        local tile, id = tostring(k):match('^([%-%d]+,[%-%d]+,[%-%d]+)@(%d+)$')
        local b, read = nil, false
        if tile then
            local okb, bb = pcall(df.building.find, tonumber(id))
            if okb then b, read = bb, true end
        else
            local x, y, z = tostring(k):match('^([%-%d]+),([%-%d]+),([%-%d]+)$')
            if x then
                local okb, bb = pcall(dfhack.buildings.findAtTile, xyz2pos(tonumber(x), tonumber(y), tonumber(z)))
                if okb then b, read = bb, true end
            end
        end
        if not read or (b and still_planned(b) ~= false) then
            table.insert(out, k)
        elseif b then
            pcall(name_built_gate, b)
        end
    end
    return out
end

-- (0.105.48 round 2, A5 #15) The scan names only the AI's own gates "AI
-- gate...": a door, hatch or bridge the AI planned, built and its record
-- forgotten here, keeps the AI's mark by its name (renamed by the next scan).
NAME_KINDS = {Door = true, Hatch = true, Bridge = true}
function name_built_gate(b)
    local okt, kind = pcall(function() return df.building_type[b:getType()] end)
    if not (okt and NAME_KINDS[kind]) then return false end
    if tostring(b.name or '') ~= '' then return false end
    b.name = 'AI gate (built)'
    return true
end

-- (0.105.36 fix) Since when the AI keeps its records: the first building id
-- after it began (kept with the save). A gate piece planned with no record
-- and an id below it predates the records (the AI's own, at an entrance it
-- fortified); one at or above it, unrecorded, is the player's. Read (and,
-- with write, kept) on the first look: the lowest of the next building id
-- and the buildings already recorded. nil when none can be read.
GATE_PLANNED_SINCE_KEY = 'ai-overseer/gate_planned_since'
function gate_planned_since(write)
    local d = U.site_get(GATE_PLANNED_SINCE_KEY, {})
    if type(d) == 'table' and math.tointeger(d.id) then return math.tointeger(d.id) end
    local okn, nxt = pcall(function() return df.global.building_next_id end)
    local since = okn and math.tointeger(nxt) or nil
    local okr, set = pcall(gate_planned_records)
    for tile, v in pairs(okr and set or {}) do
        local id = math.tointeger(v)
        if not id then
            local x, y, z = tostring(tile):match('^([%-%d]+),([%-%d]+),([%-%d]+)$')
            if x then
                local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(tonumber(x), tonumber(y), tonumber(z)))
                id = okb and b and math.tointeger(b.id) or nil
            end
        end
        if id and (not since or id < since) then since = id end
    end
    if write and since then U.site_put(GATE_PLANNED_SINCE_KEY, {id = since}) end
    return since
end

function note_gate_planned(pos)
    if not (pos and pos.x and pos.y and pos.z) then return end
    pcall(gate_planned_since, true)       -- (0.105.36 fix) before this record joins them
    local k = ('%d,%d,%d'):format(pos.x, pos.y, pos.z)
    -- (0.105.36, D2) with the id of the building planned there
    local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(pos.x, pos.y, pos.z))
    local id = okb and b and tonumber(b.id) or nil
    local set, list = gate_planned_records()
    if set[k] ~= nil and (set[k] == true or set[k] == id) then return end
    local okp, kept = pcall(prune_gate_planned, list)
    local out = {}
    for _, v in ipairs(okp and kept or list) do
        if tostring(v) ~= k and not tostring(v):match('^' .. k:gsub('%-', '%%-') .. '@') then table.insert(out, v) end
    end
    table.insert(out, id and (k .. '@' .. id) or k)
    while #out > GATE_PLANNED_MAX do table.remove(out, 1) end
    U.site_put(GATE_PLANNED_KEY, {tiles = out})
end

-- (v35 fix) Is any tile of this planned building one the AI planned?
-- (0.105.36, D2) a record with an id: only that building
function ai_planned_building(b)
    local okr, set = pcall(gate_planned_records)
    if not okr or not b or b.x1 == nil or b.z == nil then return false end
    for x = b.x1, b.x2 or b.x1 do
        for y = b.y1, b.y2 or b.y1 do
            local v = set[('%d,%d,%d'):format(x, y, b.z)]
            if v == true or (v ~= nil and v == b.id) then return true end
        end
    end
    return false
end

local function place_raw(key_text, pos)
    if place_hook then return place_hook(key_text, pos) end
    local qf = reqscript('quickfort')
    -- the same data shape ai-builder uses: {[z] = {[y] = {[x] = text}}}
    local data = {[pos.z] = {[pos.y] = {[pos.x] = key_text}}}
    local ok, stats = pcall(qf.apply_blueprint, {mode = 'build', data = data,
                                                 pos = {x = 0, y = 0, z = 0}, command = 'run'})
    if not ok then return false, tostring(stats):sub(1, 80) end
    if stats.build_designated and stats.build_designated.value > 0 then return true end
    local why = {}
    for name, v in pairs(stats) do
        if type(v) == 'table' and (v.value or 0) > 0 and name ~= 'build_designated' then
            table.insert(why, name)
        end
    end
    local seen = what_is_there(pos)
    return false, (#why > 0 and table.concat(why, ',') or 'not placed') .. (seen and (' ' .. seen) or '')
end

local function place(key_text, pos)
    local ok, why = place_raw(key_text, pos)
    if ok then pcall(note_gate_planned, pos) end       -- (v35 fix) the AI's own, recorded
    return ok, why
end

-- What's on a tile, in a few words, so a refusal says why ("SAPLING, a
-- building"). nil if it can't be read.
function what_is_there(pos)
    local ok, text = pcall(function()
        local tt = dfhack.maps.getTileType(pos.x, pos.y, pos.z)
        if not tt then return nil end
        local attrs = df.tiletype.attrs[tt]
        local bits = {df.tiletype_shape[attrs.shape] or '?', df.tiletype_material[attrs.material] or '?'}
        local des, occ = dfhack.maps.getTileFlags(pos.x, pos.y, pos.z)
        if des and des.flow_size > 0 then table.insert(bits, ('liquid %d/7'):format(des.flow_size)) end
        local b = dfhack.buildings.findAtTile(xyz2pos(pos.x, pos.y, pos.z))
        if b then
            local kind = df.building_type[b:getType()] or 'building'
            table.insert(bits, kind .. (b:getBuildStage() < b:getMaxBuildStage() and ' (planned)' or ''))
        end
        if des and des.dig ~= df.tile_dig_designation.No then table.insert(bits, 'designated to dig') end
        return ('at x%d y%d (%s)'):format(pos.x, pos.y, table.concat(bits, ', '))
    end)
    return ok and text or nil
end

local function entrance(id)
    for _, x in ipairs(GATES.entrances or {}) do if x.id == id then return x end end
    return nil
end

-- Doors on an open entrance's narrow opening (buildingplan waits for doors).
function build_doors(id)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if #e.door_spots == 0 then return {ok = false, rejected = true, error = 'no door spots for this entrance'} end
    local placed, why = 0, {}
    for _, sp in ipairs(e.door_spots) do
        local ok, reason = place('d', sp)
        if ok then placed = placed + 1 else table.insert(why, reason) end
    end
    if placed == 0 then
        return {ok = false, error = 'no door could be placed there (' .. table.concat(why, '; ') .. ')'}
    end
    return {ok = true, doors = placed}
end

-- (13e) this file's locals the later parts use, as module names (each takes
-- them back as locals of its own)
_ENV.pull, _ENV.set_entrance, _ENV.place, _ENV.entrance = pull, set_entrance, place, entrance
_ENV.lever_pull_pending = lever_pull_pending   -- (0.105.47, J16) for ai-way-out
