-- ai-trade-depot: someone called to the depot to trade (the broker first),
-- and the probe of the trade screen (read only).
--
-- (r9) A part of ai-trade, not a script of its own: ai-trade.lua loads it
-- into its own environment, so every name here is reqscript('ai-trade').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-trade-depot is a part of ai-trade; run ai-trade') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-trade-depot'] = '0.105.86'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, depot, caravans, goods, trade_screen, sides = PART_LOCALS.U, PART_LOCALS.depot, PART_LOCALS.caravans, PART_LOCALS.goods, PART_LOCALS.trade_screen, PART_LOCALS.sides   -- (r9) the hub's locals

-- --- someone to the depot ---------------------------------------------------------
--
-- The depot's "request trader" (trade_flags.trader_requested, and the
-- TradeAtDepot job it brings, as DFHack's caravan tool clears them) while a
-- caravan is coming or there; when nobody has come after `wait` ticks,
-- "anyone may trade" (trade_flags.anyone_can_trade), turned back off when
-- the caravans are gone if the AI turned it on.
CALL_KEY = 'ai-overseer/trade-call'
WORKER_STALL_DAYS = 4        -- (r2 h5) a trader on the way this long while the caravan waits: let go
BROKER_WAIT_FACTOR = 3       -- (r2 h5) the broker on his way: anyone may trade only after this many waits

-- (r2 h5) the fort's broker (DFHack's own office list)
function is_broker(u)
    local ok, yes = pcall(function()
        for _, p in ipairs(dfhack.units.getNoblePositions(u) or {}) do
            if p.position.code == 'BROKER' then return true end
        end
        return false
    end)
    return ok and yes == true
end

local function call_state()
    return U.site_get(CALL_KEY, {})
end

function trade_job(dep)
    for _, j in ipairs(dep.jobs) do
        if j.job_type == df.job_type.TradeAtDepot then return j end
    end
end

function at_depot(unit, dep)
    if not unit then return false end
    local x, y, z = dfhack.units.getPosition(unit)
    return z == dep.z and x >= dep.x1 and x <= dep.x2 and y >= dep.y1 and y <= dep.y2
end

function call_trader(now, wait, dry_run, txt)
    local dep = depot()
    if not dep then return {ok = false, rejected = true, error = 'no trade depot built yet'} end
    local st = call_state()
    local cs = caravans(txt)
    if #cs == 0 then
        local out = {ok = true, waiting = true, error = 'no caravan is coming or at the depot'}
        if st.anyone_by_ai and not dry_run then dep.trade_flags.anyone_can_trade = false end
        if next(st) and not dry_run then U.site_put(CALL_KEY, {}) end
        -- (r2 h5) the broker's call ended too: E's last state had a dwarf
        -- standing at the depot on a TradeAtDepot job with no caravan
        -- (requested, job, at_depot all true, caravans none); the AI asks again
        -- when the next caravan comes
        if not dry_run then
            if dep.trade_flags.trader_requested then
                dep.trade_flags.trader_requested = false
                out.unrequested = true
            end
            local j = trade_job(dep)
            if j and pcall(dfhack.job.removeJob, j) then out.job_removed = true end
            if out.unrequested or out.job_removed then out.waiting, out.error = nil, nil end
        end
        return out
    end
    local job = trade_job(dep)
    local worker = job and dfhack.job.getWorker(job)
    if worker and at_depot(worker, dep) then
        return {ok = true, at_depot = true, trader = (txt or tostring)(dfhack.units.getReadableName(worker))}
    end
    if dry_run then return {ok = true, dry_run = true, requested = dep.trade_flags.trader_requested} end
    local out = {ok = true}
    -- (r2 h5) who is on the way, and since when. A child who took the job
    -- ("anyone may trade": B's only trader coming in 22,554 ticks was a
    -- Dwarven Child), or one on the way for WORKER_STALL_DAYS with the caravan
    -- waiting (C y253: a carpenter "coming" from 5,323 to 31,750 ticks), is
    -- let go, so another takes the job
    local wid = worker and worker.id or nil
    if wid ~= st.worker_id then st.worker_id, st.worker_since = wid, wid and now or nil end
    if worker and job then
        local name = (txt or tostring)(dfhack.units.getReadableName(worker))
        local okc, child = pcall(function() return dfhack.units.isChild(worker) or dfhack.units.isBaby(worker) end)
        local stalled = st.since and st.worker_since and now - st.worker_since >= WORKER_STALL_DAYS * 1200
        if (okc and child) or stalled then
            if pcall(dfhack.job.removeWorker, job, 0) then
                out.let_go = name .. ((okc and child) and ' (a child)' or (' (on the way ' .. (now - st.worker_since) .. ' ticks)'))
                worker, st.worker_id, st.worker_since = nil, nil, nil
            end
        end
    end
    if dep.trade_flags.trader_requested then st.flagged = st.flagged or now end
    if not dep.trade_flags.trader_requested then
        -- the flag, as the depot's button sets it; the game makes the job
        dep.trade_flags.trader_requested = true
        st.flagged = st.flagged or now
        out.requested = true
    elseif not job and st.flagged and now - st.flagged >= 200 then
        -- flagged a while and still no job: made as the game would
        if dfhack.job.linkIntoWorld then
            local j = df.job:new()
            j.job_type = df.job_type.TradeAtDepot
            j.pos = xyz2pos(dep.centerx, dep.centery, dep.z)
            dfhack.job.addGeneralRef(j, df.general_ref_type.BUILDING_HOLDER, dep.id)
            dfhack.job.linkIntoWorld(j, true)
            dep.jobs:insert('#', j)
            out.job_made = true
        end
    end
    -- the wait counts from the caravan's arrival at the depot
    for _, c in ipairs(cs) do if c.state == 'AtDepot' then st.since = st.since or now end end
    -- (r2 h5) not while the broker himself is on the way (C y250: Sibrek,
    -- broker, coming, and anyone let in at 1,344 ticks): up to BROKER_WAIT_FACTOR waits
    local broker_coming = worker ~= nil and is_broker(worker)
    if broker_coming then out.broker_coming = true end
    if not dep.trade_flags.anyone_can_trade and st.since and now - st.since >= wait
            and not (broker_coming and now - st.since < BROKER_WAIT_FACTOR * wait) then
        dep.trade_flags.anyone_can_trade = true
        st.anyone_by_ai = true
        out.anyone = true
    end
    U.site_put(CALL_KEY, st)
    out.waiting_ticks = st.since and now - st.since or 0
    out.coming = worker and (txt or tostring)(dfhack.units.getReadableName(worker)) or nil
    return out
end

-- --- the probe (read only) -------------------------------------------------------

-- Look for a word on the screen (button labels). TrueType text can't be
-- read (readTile gives nil there): reported, so the mouse calibration is used.
local function find_word(word)
    local gps, hits, truetype = df.global.gps, {}, 0
    for y = 0, gps.dimy - 1 do
        for x = 0, gps.dimx - #word do
            local t = dfhack.screen.readTile(x, y)
            if t == nil then truetype = truetype + 1
            elseif t.ch == word:byte(1) then
                local m = true
                for k = 2, #word do
                    local tk = dfhack.screen.readTile(x + k - 1, y)
                    if not tk or tk.ch ~= word:byte(k) then m = false; break end
                end
                if m then table.insert(hits, {x, y}) end
            end
        end
    end
    return hits, truetype
end

-- What DF's trade screen holds while it is open: both sides' goods (a few,
-- with values), what's selected, whether the merchants are ready, the
-- mouse, the screen size, the buttons' labels if readable.
function probe_screen(txt)
    local out = {open = false}
    local ok, err = pcall(function()
        local trade = trade_screen()
        out.open = trade.open == true
        pcall(function() out.havetalker = trade.havetalker end)
        pcall(function() out.stillunloading = trade.stillunloading end)
        pcall(function() out.talkline = df.talk_line_type[trade.talkline] end)
        pcall(function() out.counter_offer = trade.counter_offer end)
        out.sides = {}
        for side = 0, 1 do
            local s = {who = side == MERCHANT and 'merchants' or 'fort', count = 0, selected = 0,
                       value_selected = 0, sample = {}}
            pcall(function()
                for i, item in ipairs(trade.good[side]) do
                    s.count = s.count + 1
                    local sel = false
                    pcall(function() sel = trade.goodflag[side][i].selected end)
                    local v = dfhack.items.getValue(item, trade.mer)
                    if sel then s.selected, s.value_selected = s.selected + 1, s.value_selected + v end
                    if #s.sample < 6 then
                        table.insert(s.sample, ((txt or tostring)(dfhack.items.getDescription(item, 0, true)))
                                     .. ' ' .. v .. (sel and ' *' or ''))
                    end
                end
            end)
            pcall(function() s.amounts = #trade.good_amount[side] end)
            out.sides[side + 1] = s
        end
        if out.open then
            local okc, cands, offers = pcall(sides, trade, txt)
            if okc then
                local cats = {}
                for _, c in ipairs(cands) do cats[c.cat] = (cats[c.cat] or 0) + c.n end
                local ov = 0
                for _, o in ipairs(offers) do ov = ov + o.value end
                out.merchants_have = cats
                out.fort_can_give = {goods = #offers, value = ov}
            else
                out.deal_error = tostring(cands):sub(1, 200)
            end
        end
    end)
    if not ok then out.error = tostring(err):sub(1, 200) end
    pcall(function()
        local gps = df.global.gps
        out.mouse, out.screen = {gps.mouse_x, gps.mouse_y}, {gps.dimx, gps.dimy}
        local okw, hits, tt = pcall(find_word, 'Trade')
        if okw then out.trade_label, out.truetype_tiles = hits, tt end
    end)
    out.buttons = buttons()
    out.last_open = LAST_OPEN
    return out
end
