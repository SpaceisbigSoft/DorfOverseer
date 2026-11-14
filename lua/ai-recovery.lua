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

function report()
    local out = {force = force_script(), queued = queued(), hermit_tool = hermit_on()}
    pcall(function()
        out.civ = df.historical_entity.find(df.global.plotinfo.civ_id) ~= nil
    end)
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
