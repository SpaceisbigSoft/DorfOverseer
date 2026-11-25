-- ai-society-burrows-weather: evil weather: the civilians kept inside the AI shelter's burrow
-- without the alarm, and the AI's burrows emptied when the AI is halted or away.
--
-- (r9) A part of ai-society-burrows, not a script of its own: ai-society-burrows.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-society-burrows').name and the names defined there and in the
-- parts before it are in reach.

if not BURROWS_PART_LOCALS then qerror('ai-society-burrows-weather is a part of ai-society-burrows; run ai-society-burrows') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-burrows-weather'] = '0.105.116'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, S, rec_state, rec_dry, hb_state, hb_now, calm_state = BURROWS_PART_LOCALS.U, BURROWS_PART_LOCALS.report_citizens, BURROWS_PART_LOCALS.S, BURROWS_PART_LOCALS.rec_state, BURROWS_PART_LOCALS.rec_dry, BURROWS_PART_LOCALS.hb_state, BURROWS_PART_LOCALS.hb_now, BURROWS_PART_LOCALS.calm_state   -- (r9) the hub's and earlier parts' locals

-- --- (item4) evil weather: the civilians kept inside without the alarm ---------
--
-- The alarm locked the whole fort down for a cloud drifting over the surface
-- (and stopped everything that waits on it); each spell sounded it again. Now
-- the civilians are put into the AI shelter's burrow (the inside of the fort,
-- drawn for the alarm) as members: outdoor work (wood cutting, gathering,
-- hauling outside) stops, the work inside goes on, the alarm stays for
-- enemies. Not a soldier (they may have to fight), not one in another burrow
-- (the hospital, a calm-down room, the recreation burrow, a player's). The
-- members are kept in the save; `on = false` lets out exactly those.
WEATHER_KEEP_KEY = 'ai-overseer/weather-keep-in'

local function wk_state()
    local d = U.site_get(WEATHER_KEEP_KEY, {members = {}})
    if type(d) ~= 'table' or type(d.members) ~= 'table' then d = {members = {}} end
    if type(d.out) ~= 'table' then d.out = {} end
    return d
end

-- (r9, A7 2) the keep-in's own guard at every report (weather_keep_in_status),
-- as the other AI burrows have: a member thirsty or hungry let out (and not
-- taken back for WK_OUT_TICKS), and everyone let out when no keep-in call came
-- for WK_STALE_TICKS (the brain sends one every 100 ticks while the weather
-- lasts; a brain that lost its memory of the spell never let them out)
WK_STALE_TICKS = 1200
WK_OUT_TICKS = 1200

local function wk_soldier(u)
    local ok, sq = pcall(function() return u.military.squad_id end)
    return ok and type(sq) == 'number' and sq >= 0
end

-- in burrow `bid` now; in another burrow
local function wk_burrows(u, bid)
    local mine, other = false, false
    local ok = pcall(function()
        for _, id in ipairs(u.burrows or {}) do
            if id == bid then mine = true else other = true end
        end
    end)
    if not ok then return false, true end
    return mine, other
end

function weather_keep_in(on, dry_run, txt)
    local d = wk_state()
    local b = S.find_burrow(S.SHELTER_NAME)
    if not on then
        local n = 0
        for id in pairs(d.members) do
            local u = df.unit.find(tonumber(id) or -1)
            if u and b and not dry_run then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            n = n + 1
        end
        if not dry_run then U.site_put(WEATHER_KEEP_KEY, {members = {}, out = {}}) end
        return {ok = true, on = false, released = n, dry_run = dry_run or nil}
    end
    if not b then
        return {ok = false, rejected = true, error = 'no AI shelter burrow yet (the alarm rule sets one up)'}
    end
    local okb, blocks = pcall(function() return #dfhack.burrows.listBlocks(b) end)
    if okb and blocks == 0 then
        return {ok = false, rejected = true, error = 'the AI shelter burrow covers no tiles'}
    end
    -- (0.105.48, K3) the shelter as it is now, with drink: drawn again at a
    -- spell's first keep-in and when last drawn over SHELTER_REDRAW_TICKS ago
    -- (the alarm's may be days old, narrowed to a few levels, short of drink)
    local sh
    if not dry_run then
        local okr, r = pcall(S.shelter_for_keep_in, d.spell == nil)
        if not okr then
            return {ok = false, rejected = true, error = 'could not check the AI shelter: ' .. tostring(r):sub(1, 120)}
        end
        sh = r or {}
        local why
        if (tonumber(sh.tiles) or 0) == 0 then why = 'the AI shelter covers no tiles'
        elseif sh.no_water then why = 'the AI shelter holds no drink and no well' end
        if why then
            -- nobody kept where they can't drink: those in let out
            local out = 0
            for id in pairs(d.members) do
                local u = df.unit.find(tonumber(id) or -1)
                if u then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
                out = out + 1
            end
            U.site_put(WEATHER_KEEP_KEY, {members = {}})
            return {ok = false, rejected = true, error = why .. ': nobody kept in it', released = out}
        end
        if d.spell == nil then pcall(function() d.spell = U.abs_tick() end) end
        d.spell = d.spell or 0
        pcall(function() d.last = U.abs_tick() end)      -- (r9) the stale guard's clock
    end
    local now_t = tonumber(d.last)
    local added, skipped, gone = 0, 0, 0
    local live = {}
    for _, u in ipairs(report_citizens(true)) do
        local id = tostring(u.id)
        live[id] = true
        local out_t = tonumber(d.out[id])
        if out_t and now_t and now_t >= out_t and now_t - out_t < WK_OUT_TICKS and not d.members[id] then
            skipped = skipped + 1            -- (r9) let out thirsty or hungry lately: not taken back yet
        elseif not d.members[id] then
            if out_t then d.out[id] = nil end
            local mine, other = wk_burrows(u, b.id)
            -- (0.105.97) and never a held killer: a second burrow lets them out of their cell
            if mine or other or wk_soldier(u) or killer_held(u) then
                skipped = skipped + 1        -- the player's own member, another burrow's, a soldier
            elseif dry_run then
                added = added + 1
            elseif pcall(dfhack.burrows.setAssignedUnit, b, u, true) then
                d.members[id] = true
                added = added + 1
            end
        end
    end
    for id in pairs(d.members) do
        if not live[id] then
            -- dead, gone, no longer a citizen: let out and forgotten
            local u = df.unit.find(tonumber(id) or -1)
            if u and not dry_run then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            d.members[id] = nil
            gone = gone + 1
        end
    end
    local n = 0
    for _ in pairs(d.members) do n = n + 1 end
    if not dry_run then U.site_put(WEATHER_KEEP_KEY, d) end
    return {ok = true, on = true, added = added, members = n, skipped = skipped, gone = gone,
            dry_run = dry_run or nil, shelter_tiles = sh and sh.tiles, shelter_redrawn = sh and sh.redrawn,
            drink_short = sh and sh.drink_short}
end

-- The keep-in's members for the report, and (r9) its guard: each member
-- thirsty or hungry let out; everyone let out when no keep-in call came for
-- WK_STALE_TICKS (or the shelter burrow is gone). Never raises.
function weather_keep_in_status(txt)
    local d = wk_state()
    local n = 0
    for _ in pairs(d.members) do n = n + 1 end
    if n == 0 then return {members = 0} end
    local okn, now = pcall(hb_now)
    if not okn or type(now) ~= 'number' then return {members = n} end
    local b = S.find_burrow(S.SHELTER_NAME)
    local last = tonumber(d.last) or tonumber(d.spell)
    if not last then
        d.last = now                -- a save from before the guard: counted from now
        U.site_put(WEATHER_KEEP_KEY, d)
        return {members = n}
    end
    if not b or now < last or now - last >= WK_STALE_TICKS then
        local ok, r = pcall(weather_keep_in, false, false)
        return {members = 0, released_stale = ok and r and r.released or n,
                why = not b and 'the AI shelter burrow is gone' or 'no keep-in call for a day'}
    end
    local released = {}
    for id in pairs(d.members) do
        local u = df.unit.find(tonumber(id) or -1)
        if u and rec_dry(u) then
            pcall(dfhack.burrows.setAssignedUnit, b, u, false)
            d.members[id] = nil
            d.out[id] = now
            n = n - 1
            local okt, nm = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
            table.insert(released, okt and nm or id)
        end
    end
    if #released > 0 then U.site_put(WEATHER_KEEP_KEY, d) end
    return {members = n, released_now = #released > 0 and released or nil}
end

-- --- (0.105.48, K3) the AI's burrows emptied: the AI halted or away ----------
--
-- The recreation, hospital, calm-down and weather keep-in burrows let their
-- members out only when the brain calls (or at a report): a brain stopped or
-- halted left dwarves in them (a calm room with a few drinks, the shelter
-- under evil weather) for good. ai-status's away watcher calls this (through
-- reqscript('ai-society').stand_down) while the AI is halted or no status
-- call came for AWAY_TICKS. Only the AI's own members, as each burrow's save
-- lists them (the player's members, the player's burrows: untouched); each
-- burrow's release only when it holds any (a cheap look otherwise).
-- Returns {recreation = n, hospital = n, calm = n, weather = n} (those let
-- out; 0s left out), never raises.
function release_ai_burrows(dry_run)
    local out = {}
    local function count(t)
        local n = 0
        for _ in pairs(type(t) == 'table' and t or {}) do n = n + 1 end
        return n
    end
    local function released(r)
        if type(r) ~= 'table' then return 0 end
        if type(r.released) == 'table' then return #r.released end
        return tonumber(r.released) or 0
    end
    local steps = {
        {'recreation', function() return count(rec_state().members) end,
         function() return recreation_tick(nil, nil, dry_run, nil, nil, nil, true) end},
        {'hospital', function() return count(hb_state().members) end,
         function() return hospital_burrow_tick(nil, nil, dry_run, nil, nil, true) end},
        {'calm', function() return count(calm_state().members) end,
         function() return calm_burrow_tick(nil, nil, dry_run, nil, true) end},
        {'weather', function() return count(wk_state().members) end,
         function() return weather_keep_in(false, dry_run) end},
    }
    for _, s in ipairs(steps) do
        local okn, n = pcall(s[2])
        if okn and n > 0 then
            local ok, r = pcall(s[3])
            if ok and released(r) > 0 then out[s[1]] = released(r)
            elseif not ok then out[s[1] .. '_error'] = tostring(r):sub(1, 120) end
        end
    end
    return out
end
