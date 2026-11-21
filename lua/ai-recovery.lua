-- (0.105.46, I4) A fallen fort and its migrants.
--
-- Why: D (the Hermit hold) sat at 15 dwarves for ten years, then 8: DF sent
-- it no migrants. After the first two waves DF sends migrants by the wealth
-- the fort created, as the outgoing dwarven caravan reports it, and only
-- under the population cap (the AI's cap rule, ai-society get_popcap). When
-- the brain (brain/planner_recovery.py) finds a fallen fort with its cap
-- open and nobody coming for half a year, it calls a wave with DFHack's own
-- `force Migrants` (the script queues DF's own Migrants event for the fort's
-- civilisation; DF makes the wave).
--
--   report()            the `migration` section: {force = 'force' | nil (the
--                       script that can call a wave), queued (Migrants events
--                       waiting in DF's timed events), civ (the fort's
--                       civilisation found), hermit_tool (DFHack's own
--                       `hermit` is on: it turns migrants away; nil unknown)}
--   call_migrants(dry)  the `call_migrants` action: refused while a wave is
--                       already queued; a dry run says what it would run
--
-- Every read is behind pcall (fields this DF may name otherwise).
--@module = true

CARAVAN_UNITS_MAX = 60     -- (r2 h9) merchants (and their animals) told to leave in one go at most

-- The DFHack script that calls a migrant wave, or nil.
local function force_script()
    local ok, path = pcall(function() return dfhack.findScript('force') end)
    if ok and path then return 'force' end
    return nil
end

-- DF's Migrants events already queued (a called wave not yet arrived).
local function queued()
    local n = 0
    local ok = pcall(function()
        local want = df.timed_event_type.Migrants
        for _, ev in ipairs(df.global.timed_events) do
            if ev.type == want then n = n + 1 end
        end
    end)
    return ok and n or nil
end

-- DFHack's own hermit tool (it blocks caravans, migrants and diplomats): on,
-- off, or nil when this DFHack can't say.
local function hermit_on()
    local ok, on = pcall(function()
        if not dfhack.findScript('hermit') then return false end
        local h = reqscript('hermit')
        if type(h.isEnabled) == 'function' then return h.isEnabled() == true end
        return nil
    end)
    if ok then return on end
    return nil
end

-- --- (r2 h9) the caravans and their merchants --------------------------------------
--
-- B (15 Nov run): the y251 caravan said "will be leaving soon" and never
-- embarked; its two merchants were still on the map in y261, the fort's 325
-- goods stayed locked in the depot, and for ten years no caravan and no
-- migrant came (12 waves called by force Migrants brought nobody). DF's own
-- bug 12624 has caravans stuck "Leaving" for years with the same signs. The
-- trade module (ai-trade.lua) sees only caravans coming or at the depot; this
-- reads them all (DF's plotinfo.caravans) with the merchants still on the
-- map, whether each can walk off it (ai-way-out's edge groups), for the
-- brain's migrant drought (brain/planner_outside.py).
--
--   caravans()          {{entity, own (the fort's civ), state (DF's trade
--                       state's name), days_left, tribute, merchants (on the
--                       map, alive), can_leave (of those, how many stand in a
--                       walk group that reaches the map's edge; nil unknown)}}
--   free_caravan(e, d)  the `free_caravan` action: the merchants of a caravan
--                       that is Leaving (or out of time) told to walk off the
--                       map as DFHack's own emigration does (flags1.forest,
--                       the leave countdown); only those who can reach the
--                       edge; refused for a caravan coming or trading

local function trade_state_name(c)
    local ok, n = pcall(function() return df.caravan_state.T_trade_state[c.trade_state] end)
    if ok and n then return tostring(n) end
    local okr, v = pcall(function() return c.trade_state end)
    return okr and tostring(v) or '?'
end

-- the merchants (and their pack animals: DF flags them merchants too) on the
-- map, alive, by their civilisation
local function merchants_by_civ()
    local by = {}
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function()
                if u.flags1.merchant and not u.flags1.left and not u.flags1.inactive
                        and not (dfhack.units.isDead and dfhack.units.isDead(u)) then
                    local list = by[u.civ_id] or {}
                    table.insert(list, u)
                    by[u.civ_id] = list
                end
            end)
        end
    end)
    return by
end

-- the map's edge groups (ai-way-out), or nil
local function edges()
    local ok, g = pcall(function() return reqscript('ai-way-out').edge_groups() end)
    if ok and type(g) == 'table' then return g end
    return nil
end

local function can_leave(u, eg)
    if not eg then return nil end
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(u.pos) end)
    if not ok or type(g) ~= 'number' or g == 0 then return false end
    return eg[g] == true
end

-- is this caravan done trading (DF's Leaving, or out of time and not coming)?
local function leaving(c, state)
    if state == 'Leaving' then return true end
    local ok, t = pcall(function() return c.time_remaining end)
    return ok and type(t) == 'number' and t <= 0 and state ~= 'Approaching'
end

function caravans()
    local out = {}
    local by = merchants_by_civ()
    local eg = nil
    local okc, civ = pcall(function() return df.global.plotinfo.civ_id end)
    pcall(function()
        for _, c in ipairs(df.global.plotinfo.caravans) do
            local state = trade_state_name(c)
            local e = {entity = c.entity, own = okc and c.entity == civ or nil, state = state}
            pcall(function() e.days_left = math.floor(c.time_remaining / 1200) end)
            pcall(function() e.tribute = c.flags.tribute or nil end)
            local list = by[c.entity] or {}
            e.merchants = #list
            if #list > 0 and leaving(c, state) then
                eg = eg or edges()
                local n, known = 0, eg ~= nil
                for _, u in ipairs(list) do if can_leave(u, eg) then n = n + 1 end end
                e.can_leave = known and n or nil
                e.leaving = true
            elseif leaving(c, state) then
                e.leaving = true
            end
            table.insert(out, e)
        end
    end)
    return out
end

function free_caravan(entity, dry)
    local c, state
    pcall(function()
        for _, x in ipairs(df.global.plotinfo.caravans) do
            if x.entity == entity then c = x end
        end
    end)
    if not c then return {ok = false, rejected = true, error = 'no caravan of entity ' .. tostring(entity)} end
    state = trade_state_name(c)
    if not leaving(c, state) then
        return {ok = false, rejected = true, error = 'that caravan is ' .. tostring(state) .. ', not leaving: left to trade'}
    end
    local list = merchants_by_civ()[entity] or {}
    if #list == 0 then return {ok = false, rejected = true, error = 'none of its merchants is on the map'} end
    local eg = edges()
    local told, shut = 0, 0
    for _, u in ipairs(list) do
        if told >= CARAVAN_UNITS_MAX then break end
        local can = can_leave(u, eg)
        if can == false then
            shut = shut + 1
        else
            if not dry then
                pcall(function() u.flags1.forest = true end)
                pcall(function() u.animal.leave_countdown = 2 end)
            end
            told = told + 1
        end
    end
    if told == 0 then
        return {ok = false, rejected = true, shut = shut,
                error = shut .. ' merchant(s) on the map, none with a way to the map edge'}
    end
    return {ok = true, dry_run = dry or nil, told = told, shut = shut > 0 and shut or nil, state = state}
end

function report()
    local out = {force = force_script(), queued = queued(), hermit_tool = hermit_on()}
    pcall(function()
        out.civ = df.historical_entity.find(df.global.plotinfo.civ_id) ~= nil
    end)
    -- (r2 h9) every caravan DF holds, with its merchants still on the map
    local okc, cs = pcall(caravans)
    if okc and type(cs) == 'table' and #cs > 0 then out.caravans = cs end
    return out
end

function call_migrants(dry)
    local name = force_script()
    if not name then
        return {ok = false, error = 'this DFHack has no force script to call a migrant wave'}
    end
    local before = queued()
    if before and before > 0 then
        return {ok = false, rejected = true, error = 'a migrant wave is already on its way', queued = before}
    end
    if dry then return {ok = true, dry_run = true, script = name, queued = before} end
    local out, rv = dfhack.run_command_silent(name, 'Migrants')
    if rv ~= (CR_OK or 0) then
        return {ok = false, error = name .. ' Migrants failed: ' .. tostring(out):sub(1, 160)}
    end
    local after = queued()
    if after ~= nil and after <= (before or 0) then
        return {ok = false, error = name .. ' Migrants queued no wave: ' .. tostring(out):sub(1, 160)}
    end
    return {ok = true, script = name, queued = after}
end
