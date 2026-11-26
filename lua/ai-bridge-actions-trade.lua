-- ai-bridge-actions-trade: the action handlers for trade (goods to the
-- depot, unload, the deal), recreational crafting, water (the survey, the
-- cistern, the water works), locations, petitions and alerts.
--
-- A part of ai-bridge.lua (0.105.119, split out of ai-bridge-actions-works.lua
-- when it reached the size limit), loaded by it right after
-- ai-bridge-actions-works into its own environment, as every part: what is
-- global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-actions-trade is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-actions-trade'] = '0.105.124'   -- bumped with BRIDGE_VERSION

-- Goods to the depot for a caravan (lua/ai-trade.lua); the trade is yours.
function act_bring_goods(a)
    -- (0.104.78) up to 120 at a time: the finished-goods piles full of crafts
    local n = int_in(a.count or 40, 1, 120)
    if not n then return reject('bring_goods needs count 1-120') end
    return reqscript('ai-trade').bring(n, a.dry_run == true, txt, a.keep_treasures == true, a.keep_trinkets == true)
end

-- (0.103.8) The fort's goods left in the depot after the caravans: back out.
function act_unload_depot(a)
    local n = int_in(a.max or 50, 1, 200)
    if not n then return reject('unload_depot needs max 1-200') end
    return reqscript('ai-trade').unload(n, a.dry_run == true, txt)
end

-- A deal ticked on the open trade screen, and the Trade button pressed if
-- asked and calibrated (lua/ai-trade.lua). wants: {{key, count}} in order.
function act_trade_deal(a)
    local wants = {}
    for _, w in ipairs(type(a.wants) == 'table' and a.wants or {}) do
        local n = int_in(w.count, 1, 500)
        if type(w.key) ~= 'string' or not n then return reject('trade_deal wants {key, count 1-500}') end
        table.insert(wants, {key = w.key, count = n})
    end
    if #wants == 0 then return reject('trade_deal needs wants') end
    -- (r2 h5) what any fort can use, bought only when none of the wants is on sale
    local extra = {}
    for _, w in ipairs(type(a.extra) == 'table' and a.extra or {}) do
        local n = int_in(w.count, 1, 500)
        if type(w.key) ~= 'string' or not n then return reject('trade_deal extra {key, count 1-500}') end
        table.insert(extra, {key = w.key, count = n})
    end
    local margin = tonumber(a.margin) or 1.2
    if margin < 1.0 or margin > 3 then return reject('trade_deal margin must be 1.0-3') end
    local T = reqscript('ai-trade')
    -- (0.100, security pass) a trade screen the player opened is the
    -- player's: the AI neither ticks goods there nor presses Trade
    if not a.dry_run and a.force ~= true and not T.opened_by_ai() then
        return reject('the player opened this trade screen: the AI leaves the deal to them')
    end
    local r = T.deal(wants, margin, a.dry_run == true, txt, #extra > 0 and extra or nil)
    -- nothing to buy (or turned down before): the screen closed, if asked
    if r.rejected and a.close == true and not a.dry_run and T.opened_by_ai() then
        local c = T.close_screen()
        r.closed = c.closed
    end
    -- (r2 h5) pressed too where no place is known: press() looks for the
    -- Trade label by its word (every fort's guess was retired)
    if r.ok and not r.waiting and not a.dry_run and a.press == true and (r.calibrated or r.can_search) then
        local p = T.press('Trade', txt)
        -- (0.105.113 item10) "we can't carry that": ticked again lighter, pressed again
        if p.too_heavy then r, p = T.press_lighter(r, p, wants, margin, txt, #extra > 0 and extra or nil) end
        r.press = p
        r.answer, r.traded, r.counter, r.closed = p.answer, p.traded, p.counter, p.closed
        -- not pressed at all (no Trade button found): the AI's screen closed
        -- (time stands still while it is open), this caravan left to the player
        if p.rejected and not p.pressed and not p.closed and a.close == true and T.opened_by_ai() then
            local c = T.close_screen()
            r.closed = c.closed
        end
    end
    return r
end

-- Recreational crafting turned on at a Craftsdwarf's workshop (lua/ai-society.lua).
function act_idle_crafting(a)
    return reqscript('ai-society').idle_crafting(a.dry_run == true)
end

-- (0.105.38) the map's width (at least 80): a far source's reach at most
-- (the old fixed caps were 80 and 100 tiles)
function map_width()
    local ok, w = pcall(function() return (dfhack.maps.getTileSize()) end)
    return math.max(80, ok and math.tointeger(w) or 80)
end

-- (0.105.38) the brain's water_far_reach for the cistern's and the shore well's far sources
-- (none or below 0: the map's width; (review) 0: far sources off)
function far_reach_of(a)
    local r = whole_number(a.far_reach)
    if whole_number(a.job_max) == 0 then r = 0 end    -- (0.105.38 review) water_job_max 0: no far work either
    pcall(function()
        local B = reqscript('ai-builder')
        B.CISTERN_FAR_REACH = r
        B.SHORE_FAR_REACH = r
    end)
end

-- Survey the water near the fort (lua/ai-water.lua): kept in the save. In
-- slices: each call scans for at most ~0.15 s and says "done = false" until
-- the survey is finished; then the cistern plan, one fort level a call
-- (the lag pass: the whole survey froze the game ~1.4 s, the plan up to 3 s).
WATER_PLAN = WATER_PLAN or nil
function act_survey_water(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    local W = reqscript('ai-water')
    local now = abs_tick()
    if not WATER_PLAN then
        -- (r2h1) the brain's slice length while scanning (capped in ai-water)
        local r = W.scan_step(now, W.slice_seconds and W.slice_seconds(a.seconds) or nil)
        if not r.ok then return r end
        if not r.done then return {ok = true, done = false, scanning = true, left = r.left} end
        WATER_PLAN = {i = 1}
        return {ok = true, done = false, planning = true}
    end
    local B = reqscript('ai-builder')
    far_reach_of(a)
    local i = WATER_PLAN.i
    -- (0.105.3) Hammerstirred (2 Nov): the brain's cistern_tunnel_max (the pool 53-66 tiles off)
    local tun = whole_number(a.tunnel)
    -- (r2h1) after the busiest levels, one call for the next CISTERN_RIVER_LEVELS
    -- fort levels when the survey found a river: its shaft way needs a cistern
    -- 1-8 levels under it (region4's at z160, the dwarves' busiest higher up)
    local nlev = B.CISTERN_LEVELS or 6
    local last_i = i
    if i > nlev then last_i = nlev + (B.CISTERN_RIVER_LEVELS or 10) end
    local okp, plan, why = pcall(B.plan_cistern, i, last_i, {tunnel = tun and math.max(2, math.min(tun, map_width())) or nil})
    if okp and plan and (not WATER_PLAN.best or plan.score < WATER_PLAN.best.score) then WATER_PLAN.best = plan end
    if okp and not plan and why then WATER_PLAN.why = WATER_PLAN.why or why end
    if not okp then WATER_PLAN.why = tostring(plan):sub(1, 160) end
    local river_pass = false
    if i == nlev and B.cistern_rivers then
        local okr, rv = pcall(B.cistern_rivers)
        river_pass = okr and rv ~= nil
    end
    if i < nlev or river_pass then
        WATER_PLAN.i = i + 1
        return {ok = true, done = false, planning = true, level = i}
    end
    local r = W.last() or {ok = true}
    r.cistern = WATER_PLAN.best or {none = true, why = WATER_PLAN.why or 'no still, fresh water on the level under a fort level'}
    WATER_PLAN = nil
    pcall(dfhack.persistent.saveSiteData, 'ai-overseer/water', r)
    local kinds = {}
    for _, bd in ipairs(r.bodies or {}) do table.insert(kinds, ('%s %d'):format(bd.kind, bd.tiles)) end
    return {ok = true, done = true, bodies = kinds, aquifer = r.aquifer, magma = r.magma, cistern = r.cistern}
end

-- The cistern (lua/ai-builder.lua): one step of building it, or keeping it filled.
function act_cistern_step(a)
    if a.shut == true then return reqscript('ai-builder').cistern_shut(a.dry_run == true) end
    -- (0.105.35) retired by the AI (leaked twice, a gap it can't close, a lever that won't link), or relinked
    if a.retire == true then
        return reqscript('ai-builder').cistern_retire(a.dry_run == true, type(a.why) == 'string' and a.why:sub(1, 120) or nil)
    end
    if a.relink == true then return reqscript('ai-builder').cistern_relink(a.dry_run == true) end
    -- (0.104.145) what the brain knows that weighs the source: the climate
    -- freezes, a danger in the caverns
    local prefs = type(a.prefs) == 'table' and {freezes = a.prefs.freezes == true,
                                               cavern_danger = a.prefs.cavern_danger == true} or nil
    -- (0.105.3) the tunnel's reach, as the survey planned it (Hammerstirred's pool 53-66 tiles off)
    local tun = whole_number(a.tunnel)
    far_reach_of(a)
    return reqscript('ai-builder').cistern_step(a.dry_run == true, prefs, tun and math.max(2, math.min(tun, map_width())) or nil)
end

-- (0.105.0) Water works and magma (lua/ai-waterworks.lua): one step of the
-- moat, the pump stack, the muddied farm level or a magma workshop, or its
-- floodgate shut at once (shut) or the work retired.
function act_water_work(a)
    local kinds = reqscript('ai-waterworks').KINDS
    if not kinds[a.kind] then return reject('water_work: kind is moat, pump, irrigation, magma or power') end
    if a.shop ~= nil and not reqscript('ai-waterworks').MAGMA_SHOPS[a.shop] then
        return reject('water_work: shop is MagmaForge, MagmaSmelter or MagmaGlassFurnace')
    end
    -- (0.105.37 E3) the power's source: a water wheel or a windmill (nil: a wheel if it can)
    if a.source ~= nil and a.source ~= 'wheel' and a.source ~= 'windmill' then
        return reject('water_work: source is wheel or windmill')
    end
    return reqscript('ai-waterworks').step(a.kind, {dry_run = a.dry_run == true, shut = a.shut == true,
        retire = a.retire == true, shop = a.shop, plain = a.plain == true, reopen = a.reopen == true,
        source = a.source,
        -- (0.105.38) far sources: the brain's reach (tiles; none or below 0: the
        -- map's width; 0: far sources off), the job's size at most (0: no far
        -- work), a long dig's segment; and the cavern switch's answer for magma
        -- whose way opens a cavern
        far_reach = whole_number(a.far_reach), job_max = whole_number(a.job_max), segment = whole_number(a.segment),
        open_caverns = a.open_caverns == true,
        -- (r9, A4 19) the leak watch's recheck passed on by its own flag (it
        -- worked only because the brain's why starts "recheck")
        recheck = a.recheck == true,
        why = type(a.why) == 'string' and a.why:sub(1, 120) or nil})
end

-- (0.84) a vacant post at a location (hospital staff, scribes, the tavern keeper)
function act_staff_location(a)
    local id = whole_number(a.location_id)
    if not id or type(a.post) ~= 'string' then return reject('staff_location needs location_id and post') end
    return reqscript('ai-society').staff_location(id, a.post, a.dry_run == true, txt)
end

-- (0.92) give a hall still being dug to another petition: project_id and
-- one of profession, deity_hf, religion
function act_retarget_hall(a)
    local id = whole_number(a.project_id)
    if not id then return reject('retarget_hall needs project_id') end
    local t = {}
    if a.profession ~= nil then
        if type(a.profession) ~= 'string' or df.profession[a.profession] == nil then return reject('unknown profession') end
        t.profession = a.profession
    elseif a.deity_hf ~= nil then
        t.deity_hf = whole_number(a.deity_hf)
        if not t.deity_hf or not df.historical_figure.find(t.deity_hf) then return reject('no such deity') end
    elseif a.religion ~= nil then
        t.religion = whole_number(a.religion)
        if not t.religion or not df.historical_entity.find(t.religion) then return reject('no such religion') end
    else
        return reject('retarget_hall needs profession, deity_hf or religion')
    end
    return reqscript('ai-builder').retarget_hall(id, t, a.dry_run == true)
end

-- (0.89) answer a temple or guildhall petition: id, accept (true/false)
function act_answer_petition(a)
    if type(a.accept) ~= 'boolean' then return reject('answer_petition needs id (or ids) and accept true|false') end
    -- (0.105.9) ids: up to 25 at once (old residency petitions by the hundred)
    if type(a.ids) == 'table' then
        local ids = {}
        for _, v in ipairs(a.ids) do
            local n = whole_number(v)
            if not n then return reject('answer_petition: ids are whole numbers') end
            table.insert(ids, n)
        end
        if #ids == 0 or #ids > 25 then return reject('answer_petition needs 1-25 ids') end
        local out = {ok = true, answered = 0, refused = {}, accepted = a.accept or nil, dry_run = a.dry_run or nil}
        for _, n in ipairs(ids) do
            local r = answer_petition(n, a.accept, a.dry_run == true)
            if r.ok then out.answered = out.answered + 1
            else table.insert(out.refused, {id = n, error = r.error}) end
        end
        if #out.refused == 0 then out.refused = nil end
        out.ok = out.answered > 0
        if not out.ok then out.error = 'no petition answered'; out.rejected = true end
        return out
    end
    local id = whole_number(a.id)
    if not id then return reject('answer_petition needs id (or ids) and accept true|false') end
    return answer_petition(id, a.accept, a.dry_run == true)
end

-- (0.88) alerts: {TYPE = ticks | false, default = ticks}; max 1-100
function act_dismiss_alerts(a)
    local n = whole_number(a.max)
    if not n or n < 1 or n > 100 then return reject('dismiss_alerts needs max 1-100') end
    if type(a.ages) ~= 'table' then return reject('dismiss_alerts needs ages {TYPE = ticks, default = ticks}') end
    local ages = {}
    for k, v in pairs(a.ages) do
        if type(k) ~= 'string' or not (k == 'default' or df.announcement_alert_type[k] ~= nil) then
            return reject('unknown alert type: ' .. tostring(k))
        end
        local t = whole_number(v)
        if v == false then ages[k] = false
        elseif t and t >= 0 then ages[k] = t
        else return reject('alert ages are whole ticks or false') end
    end
    return reqscript('ai-reports').dismiss_alerts(ages, n, a.dry_run == true)
end
