-- Trade: caravans at the fort, and the goods the AI takes to the depot for
-- them. The trading itself (the barter screen) is DF's and stays the
-- player's: DFHack has no call that makes a trade. What the AI does is the
-- work before it: when a caravan is coming or at the depot, it marks the
-- fort's crafts for the depot (DFHack's dfhack.items.markForTrade, the same
-- call DFHack's own "move goods" screen uses), so the goods are there when
-- you open the trade screen.
--
-- Only goods of stone, metal or gems are taken: never wood or anything from
-- an animal (some caravans take offence at those).
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
-- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_citizens(...) return U.report_citizens(...) end
local function report_units(...) return U.report_units(...) end

-- A DF name in words (dfhack.TranslateName was renamed in DFHack 50.15).
local function translate(name, english)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, english) end)
    if ok and s then return s end
    ok, s = pcall(function() return dfhack.TranslateName(name, english) end)
    return ok and s or '?'
end

GOODS = {'FIGURINE', 'AMULET', 'BRACELET', 'EARRING', 'RING', 'CROWN', 'SCEPTER', 'GOBLET', 'TOY',
         'INSTRUMENT', 'TOTEM', 'SMALLGEM'}      -- (cut gems, from autogems at the jeweller's)
MAX_BRING = 120     -- (0.104.78) was 40: the goods piles full of crafts
-- (0.103.9) trinkets kept home while dwarves want something to own (Enxah:
-- 163 crafts left in the depot after the caravan, 0 free, 16 dwarves badly
-- wanting one)
TRINKET_TYPES = {FIGURINE = true, AMULET = true, BRACELET = true, EARRING = true, RING = true, CROWN = true,
                 SCEPTER = true}
NO_TRINKETS = false

local function depot()
    for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do
        if b:getBuildStage() >= b:getMaxBuildStage() then return b end
    end
end

-- Caravans coming or at the depot: {{civ, state}}.
local function caravans(txt)
    local out = {}
    for _, c in ipairs(df.global.plotinfo.caravans) do
        local ok, active = pcall(function()
            local T = df.caravan_state.T_trade_state
            return not c.flags.tribute and c.time_remaining > 0
                and (c.trade_state == T.Approaching or c.trade_state == T.AtDepot)
        end)
        if ok and active then
            local ent = df.historical_entity.find(c.entity)
            local name = ent and (txt or tostring)(translate(ent.name, true)) or '?'
            local _, state = pcall(function() return df.caravan_state.T_trade_state[c.trade_state] end)
            table.insert(out, {civ = name, state = state})
        end
    end
    return out
end

local GOOD_TYPE = {}
for _, name in ipairs(GOODS) do
    local ok, t = pcall(function() return df.item_type[name] end)
    if ok and t then GOOD_TYPE[t] = true end
end

-- Not free to sell (lua/ai-util.lua's list: a mood's artifact is never
-- traded away). Whether it sits loose or in a bin, goods() works out itself.
local HELD_OK = {held = true}
local function unsellable(item) return not U.item_free(item, HELD_OK) end

-- (0.100) a mood's artifact (or any item flagged one): never offered
local function is_artifact(item)
    local ok, v = pcall(function() return item.flags.artifact end)
    return ok and v == true
end

-- (r2 h5) a caravan's own good (in the depot it is the merchants', not the fort's)
function merchant_item(item)
    local ok, v = pcall(function() return item.flags.trader end)
    return ok and v == true
end

local function reachable(item, dep)
    return dfhack.maps.canWalkBetween(xyz2pos(dfhack.items.getPosition(item)),
                                      xyz2pos(dep.centerx, dep.centery, dep.z))
end

-- (0.96) Treasures a grasping fort (Greed +50) keeps home: cut gems and goods
-- of precious metal.
PRECIOUS = {GOLD = true, SILVER = true, PLATINUM = true, ELECTRUM = true, ROSE_GOLD = true, ALUMINUM = true}
KEEP_TREASURES = false

function treasure(item)
    local ok, yes = pcall(function()
        if df.item_type.SMALLGEM and item:getType() == df.item_type.SMALLGEM then return true end
        local mi = dfhack.matinfo.decode(item)
        local tok = mi and mi.inorganic and mi.inorganic.id
        return tok ~= nil and PRECIOUS[tok] == true
    end)
    return ok and yes == true
end

-- (0.104.95) Stone, metal, gems, and glass (built-in materials 3-5: green,
-- clear and crystal): never wood or animal goods, which some caravans refuse.
function trade_material(item)
    local ok, mt = pcall(function() return item:getMaterial() end)
    return ok and (mt == 0 or (mt >= 3 and mt <= 5))
end

-- (0.105.41, item 8) the nobles' export bans (lua/ai-bans.lua): set for one
-- walk of the goods by goods(); BANNED_KEPT counts the goods kept home for them
BANNED = nil
BANNED_KEPT = 0

local function banned_now(item)
    if BANNED == nil or not BANNED(item) then return false end
    BANNED_KEPT = BANNED_KEPT + 1
    return true
end

-- A good the AI may sell, loose (not in a bin): stone, metal, gems or glass,
-- and nothing the nobles ban from export.
local function sellable(item)
    return not unsellable(item) and trade_material(item)
        and not (KEEP_TREASURES and treasure(item)) and not banned_now(item)
end

-- A bin (or other container) holding only sellable goods, on the ground:
-- taken to the depot whole (0.46's bins hid every craft from the count:
-- an item in a bin is "in inventory", as one in a dwarf's hands).
local function sellable_bin(c)
    if unsellable(c) or c.flags.in_inventory or not c.flags.on_ground then return false end
    local contents = dfhack.items.getContainedItems(c)
    if #contents == 0 then return false end
    for _, it in ipairs(contents) do
        if not GOOD_TYPE[it:getType()] or not sellable(it) then return false end
        if NO_TRINKETS and TRINKET_TYPES[df.item_type[it:getType()] or ''] then return false end
    end
    return true, contents
end

-- the bans as a check, and the bans: ai-bans' (with DFHack's beside it), or
-- DFHack's alone when ai-bans can't load
local function ban_checker()
    local ok, B = pcall(reqscript, 'ai-bans')
    if ok and type(B) == 'table' and B.checker then
        local okc, fn, bans = pcall(B.checker)
        if okc and fn then return fn, bans, B end
    end
    return nil
end

-- What to take: {items (loose goods and whole bins), value, count of goods}.
local function goods(dep, limit)
    local out, value, count, bins = {}, 0, 0, {}
    BANNED, BANNED_KEPT = ban_checker(), 0
    for _, name in ipairs(GOODS) do
        local list = not (NO_TRINKETS and TRINKET_TYPES[name]) and df.global.world.items.other[name] or nil
        if list then
            for _, item in ipairs(list) do
                if count >= limit then return out, value, count end
                if not item.flags.in_inventory then
                    if sellable(item) and reachable(item, dep) then
                        table.insert(out, item)
                        value = value + dfhack.items.getValue(item)
                        count = count + 1
                    end
                else
                    local c = dfhack.items.getContainer(item)
                    if c and bins[c.id] == nil then
                        local ok, contents = sellable_bin(c)
                        bins[c.id] = ok and reachable(c, dep) or false
                        if bins[c.id] then
                            table.insert(out, c)
                            for _, it in ipairs(contents) do value = value + dfhack.items.getValue(it) end
                            count = count + #contents
                        end
                    end
                end
            end
        end
    end
    return out, value, count
end

-- (r2 h5) A caravan that stays past its leaving: B's y251 caravan said "will
-- be leaving soon" and never embarked; its merchants were still on the map
-- ten years later, its 325 goods in the depot, and no caravan (nor, likely,
-- migrants) came in those years. Each caravan past its time (no longer
-- Approaching or AtDepot, or its time run out) whose merchants are still on
-- the map is reported with what holds it: their goods still in the depot,
-- wagons with a depot they can't reach, merchants who can't walk to the
-- depot. `days` counts from the first report that saw it so.
OVERSTAY_KEY = 'ai-overseer/trade-overstay'

local function creature_id(u)
    local ok, id = pcall(function() return df.creature_raw.find(u.race).creature_id end)
    return ok and id or nil
end

-- Pure: the words for what holds a caravan, from its counts
function overstay_holds(o)
    local why = {}
    if (o.goods_in_depot or 0) > 0 then
        table.insert(why, ('%d of their goods still in the depot'):format(o.goods_in_depot))
    end
    if (o.wagons or 0) > 0 and o.depot_wagons == false then
        table.insert(why, ('%d wagon(s) and a depot the game marks out of the wagons\' reach'):format(o.wagons))
    end
    if o.merchants and o.reach_depot and o.reach_depot < o.merchants then
        table.insert(why, ('%d of %d merchants can\'t walk to the depot'):format(o.merchants - o.reach_depot, o.merchants))
    end
    if (o.in_depot or 0) > 0 then
        table.insert(why, ('%d merchant(s) still at the depot'):format(o.in_depot))
    end
    if #why == 0 then table.insert(why, 'nothing seen holding it (a way off the map shut?)') end
    return why
end

function overstays(txt, dep)
    local out = {}
    local now = trade_now()
    local seen = U.site_get(OVERSTAY_KEY, {})
    local keep, changed = {}, false
    for _, c in ipairs(df.global.plotinfo.caravans) do
        pcall(function()
            local state = df.caravan_state.T_trade_state[c.trade_state]
            local past = (state ~= 'Approaching' and state ~= 'AtDepot') or (tonumber(c.time_remaining) or 1) <= 0
            if not past or c.flags.tribute then return end
            local o = {state = tostring(state), time_remaining = c.time_remaining, merchants = 0, wagons = 0,
                       reach_depot = 0, in_depot = 0, at = {}, entity = c.entity}   -- (item3) entity: for clear_caravan_goods
            for _, u in ipairs(report_units()) do
                local okm, mine = pcall(function()
                    return u.flags1.merchant and u.civ_id == c.entity and not dfhack.units.isDead(u)
                        and not u.flags1.inactive
                end)
                if okm and mine then
                    if creature_id(u) == 'WAGON' then
                        o.wagons = o.wagons + 1
                    else
                        o.merchants = o.merchants + 1
                        local x, y, z = dfhack.units.getPosition(u)
                        if #o.at < 3 then table.insert(o.at, {x, y, z}) end
                        if dep then
                            if at_depot(u, dep) then o.in_depot = o.in_depot + 1 end
                            local okw, w = pcall(dfhack.maps.canWalkBetween, xyz2pos(x, y, z),
                                                 xyz2pos(dep.centerx, dep.centery, dep.z))
                            if okw and w then o.reach_depot = o.reach_depot + 1 end
                        end
                    end
                end
            end
            if o.merchants + o.wagons == 0 then return end
            if dep then
                local n = 0
                for _, ci in ipairs(dep.contained_items) do
                    if ci.use_mode == df.building_item_role_type.TEMP and merchant_item(ci.item) then n = n + 1 end
                end
                o.goods_in_depot = n
                pcall(function() o.depot_wagons = dep.accessible end)
            end
            local ent = df.historical_entity.find(c.entity)
            o.civ = ent and (txt or tostring)(translate(ent.name, true)) or '?'
            local k = caravan_key(c) or tostring(c.entity)
            local since = tonumber(seen[k]) or now
            if seen[k] == nil then changed = true end
            keep[k] = since
            o.days = math.max(0, (now - since) // 1200)
            o.holds = overstay_holds(o)
            table.insert(out, o)
        end)
    end
    for k in pairs(seen) do if keep[k] == nil then changed = true end end
    if changed then pcall(U.site_put, OVERSTAY_KEY, keep) end
    return out
end

-- (item4) The fort's items in the depot on a job, followed across looks:
-- {item id (string) = first tick seen busy}, kept in the save.
DEPOT_BUSY_KEY = 'ai-overseer/depot-busy'
DEPOT_STUCK_TICKS = 3 * 1200        -- a haul out of the depot takes far less than three days

-- Pure: the record after a look that saw `ids` busy at `now`: the ids no
-- longer busy forgotten, the new ones from now. Returns the new record, how
-- many were busy, how many longer than stuck_ticks, and whether it changed.
function busy_record(seen, ids, now, stuck_ticks)
    local keep, stuck, changed = {}, 0, false
    for _, id in ipairs(ids) do
        local k = tostring(id)
        local since = tonumber(seen[k])
        if since == nil or since > now then since = now; changed = true end   -- (a tick from the future: an older save)
        keep[k] = since
        if now - since >= stuck_ticks then stuck = stuck + 1 end
    end
    for k in pairs(seen) do if keep[k] == nil then changed = true end end
    return keep, #ids, stuck, changed
end

function depot_busy_seen(ids)
    local now = trade_now()
    local keep, busy, stuck, changed = busy_record(U.site_get(DEPOT_BUSY_KEY, {}), ids, now, DEPOT_STUCK_TICKS)
    if changed then pcall(U.site_put, DEPOT_BUSY_KEY, keep) end
    return busy, stuck
end

-- The report's "trade" section.
function survey(txt)
    local dep = depot()
    local out = {depot = dep ~= nil, caravans = caravans(txt)}
    -- (0.105.41, item 8) the nobles' export bans in force (lua/ai-bans.lua)
    pcall(function()
        local B = reqscript('ai-bans')
        local bans = B.summary(B.read(txt))
        if #bans > 0 then out.bans = bans end
    end)
    if dep then
        local ok, list, value, count = pcall(goods, dep, 500)
        if ok then out.goods, out.goods_value, out.loads = count, value, #list end
        if BANNED_KEPT > 0 then out.banned_kept = BANNED_KEPT end      -- (0.105.41, item 8)
        -- (r2 h5) the fort's goods only: the merchants' own (flags.trader) sat
        -- in the count, so a fort that never traded (D, Trade -100) and B,
        -- whose y251 caravan never left (325 "of the fort's goods"), asked to
        -- unload them 50 and 48 times ("the game kept it in the depot")
        local at, theirs = 0, 0
        local busy_ids = {}
        for _, ci in ipairs(dep.contained_items) do
            if ci.use_mode == df.building_item_role_type.TEMP then
                if merchant_item(ci.item) then theirs = theirs + 1 else
                    at = at + 1
                    local okb, b = pcall(function() return ci.item.flags.in_job end)
                    if okb and b then table.insert(busy_ids, ci.item.id) end
                end
            end
        end
        out.at_depot = at
        if theirs > 0 then out.merchant_goods = theirs end
        -- (item4) of those, the ones on a job (a hauler's, carrying them out):
        -- unload leaves them and answers "being hauled out". B (24 Nov): the
        -- same 4 stayed on a job for hours and unload_depot was asked 107
        -- times in 2 hours. Busy since a tick kept per item id; busy past
        -- DEPOT_STUCK_TICKS counts as stuck (the brain says it, asks no more)
        if at > 0 then
            local okr, busy, stuck = pcall(depot_busy_seen, busy_ids)
            if okr then
                out.at_depot_busy = busy
                if stuck > 0 then out.at_depot_stuck = stuck end
            end
        elseif next(U.site_get(DEPOT_BUSY_KEY, {})) ~= nil then
            pcall(U.site_put, DEPOT_BUSY_KEY, {})
        end
    end
    -- the commonest cut gem (to set into crafts at the jeweller's)
    pcall(function()
        local by = {}
        for _, it in ipairs(df.global.world.items.other.SMALLGEM) do
            if U.item_free(it, HELD_OK) then
                local tok = dfhack.matinfo.decode(it):getToken()
                by[tok] = (by[tok] or 0) + it:getStackSize()
            end
        end
        local best, n, total = nil, 0, 0
        for tok, c in pairs(by) do
            total = total + c
            if c > n then best, n = tok, c end
        end
        if best then out.cut_gem = {token = best, n = n, total = total} end
    end)
    -- (0.104.84) the commonest rough gem (cut at the jeweller's when DFHack
    -- has no autogems: Enxah, 293 rough and none ever cut)
    pcall(function()
        local by = {}
        for _, it in ipairs(df.global.world.items.other.ROUGH) do
            if U.item_free(it, HELD_OK) then
                local mi = dfhack.matinfo.decode(it)
                if mi and mi.material and mi.material.flags.IS_GEM then
                    local tok = mi:getToken()
                    by[tok] = (by[tok] or 0) + it:getStackSize()
                end
            end
        end
        local best, n, total = nil, 0, 0
        for tok, c in pairs(by) do
            total = total + c
            if c > n then best, n = tok, c end
        end
        if best then out.rough_gem = {token = best, n = n, total = total} end
    end)
    pcall(function()
        if dep then
            local j = trade_job(dep)
            local w = j and dfhack.job.getWorker(j)
            out.trader = {requested = dep.trade_flags.trader_requested, anyone = dep.trade_flags.anyone_can_trade,
                          job = j ~= nil, coming = w ~= nil, at_depot = at_depot(w, dep),
                          can_open = buttons().Depot ~= nil}
            -- (r2 h5) or the depot's Trade button looked for by its word (a few tries a visit)
            pcall(function() out.trader.can_open = can_open_now() end)
            pcall(function() out.trader.unloading = unloading(dep) or nil end)   -- (item39)
            if buttons().Depot == nil then
                out.trader.search = out.trader.can_open and 'by its word' or (UNREADABLE and 'unreadable' or 'used up')
            end
            -- (r2 h5) what the last try to open the screen did (no deal in six forts, and nothing said why)
            if LAST_OPEN then out.trader.last_open = LAST_OPEN end
            -- (0.105.47) where the depot's Trade button is known from: save, pc or guess
            pcall(function() out.trader.button = buttons().Depot.from end)
            -- whether the AI itself opened the depot to anyone (only then does it close it again)
            out.trader.anyone_by_ai = U.site_get(CALL_KEY, {}).anyone_by_ai == true
            -- a caravan at the depot the AI hasn't traded with yet this visit
            local fresh = false
            for _, c in ipairs(df.global.plotinfo.caravans) do
                if c.trade_state == df.caravan_state.T_trade_state.AtDepot and not is_done(c) then fresh = true end
            end
            out.trader.fresh = fresh
        end
    end)
    -- (r2 h5) a caravan past its leaving with its merchants still here
    pcall(function()
        local o = overstays(txt, dep)
        if #o > 0 then out.overstay = o end
    end)
    pcall(function()
        local t = df.global.game.main_interface.trade
        if t.open then
            out.screen = {open = true, ready = t.havetalker == 1 and t.stillunloading == 0 and not t.counter_offer,
                          unloading = t.stillunloading ~= 0,
                          calibrated = buttons().Trade ~= nil, by_ai = opened_by_ai()}
        end
    end)
    return out
end

-- Mark up to `count` goods for the depot while a caravan is coming or there.
function bring(count, dry_run, txt, keep_treasures, keep_trinkets)
    KEEP_TREASURES = keep_treasures == true
    NO_TRINKETS = keep_trinkets == true
    local dep = depot()
    if not dep then return {ok = false, rejected = true, error = 'no trade depot built yet'} end
    local cs = caravans(txt)
    if #cs == 0 then return {ok = false, rejected = true, error = 'no caravan is coming or at the depot'} end
    -- (13c) the goods walked once (it ran twice: once for the first `count`,
    -- once for all of them to put the requested ones first)
    local all = goods(dep, 500)
    local limit = math.min(count or MAX_BRING, MAX_BRING)
    local keyed = {}
    for i, it in ipairs(all) do
        local okc, inside = pcall(dfhack.items.getContainedItems, it)
        local items = (okc and #inside > 0) and inside or {it}
        table.insert(keyed, {it = it, i = i, items = items})
    end
    -- goods the caravans asked for go first (the game pays more for them:
    -- dfhack.items.isRequestedTradeGood); without that call, in list order
    pcall(function()
        for _, k in ipairs(keyed) do
            k.req = false
            for _, x in ipairs(k.items) do
                if dfhack.items.isRequestedTradeGood(x) then k.req = true break end
            end
        end
        table.sort(keyed, function(a, b)
            if a.req ~= b.req then return a.req end
            return a.i < b.i
        end)
    end)
    local list, value, n = {}, 0, 0
    for _, k in ipairs(keyed) do
        if n >= limit then break end
        table.insert(list, k.it)
        n = n + #k.items
        for _, x in ipairs(k.items) do value = value + dfhack.items.getValue(x) end
    end
    if #list == 0 then
        return {ok = false, rejected = true, error = 'no crafts of stone, metal or gems the dwarves can carry there'}
    end
    if not dry_run then
        local marked = 0
        for _, item in ipairs(list) do
            local okm, r = pcall(dfhack.items.markForTrade, item, dep)
            if okm and r ~= false then marked = marked + 1 end
        end
        if marked == 0 then return {ok = false, error = 'the game took none of the goods to the depot'} end
        return {ok = true, items = n, loads = marked, value = value, caravan = cs[1].civ,
                banned_kept = BANNED_KEPT > 0 and BANNED_KEPT or nil}
    end
    return {ok = true, dry_run = true, items = n, loads = #list, value = value, caravan = cs[1].civ,
            banned_kept = BANNED_KEPT > 0 and BANNED_KEPT or nil}
end

-- (0.105.119) unload() and clear_caravan_goods(): in ai-trade-unload.lua

-- --- the trade screen: automatic trading -------------------------------------------
--
-- DF's trade screen (df.global.game.main_interface.trade) lists the
-- merchants' goods in good[0] and the fort's in good[1] (in-game probe,
-- 0.55.2: gold bars and gems on side 0, the fort's bins of crafts on side 1);
-- goodflag[side][i].selected is the tick DFHack's own trade screen sets.
-- Values are as the merchants see them (dfhack.items.getValue with the
-- caravan), a container counted with what's in it, as DFHack's screen does.
-- The AI ticks what the fort needs from them and enough of its crafts to pay
-- with a margin; DF's Trade button has no key, so it is pressed with a
-- simulated mouse click where the player showed it once (calibrate).

MERCHANT, FORT = 0, 1
MARGIN = 1.2
BUTTONS_KEY = 'ai-overseer/trade-buttons'

local function trade_screen() return df.global.game.main_interface.trade end

local FOOD_TYPES = {MEAT = true, FISH = true, CHEESE = true, PLANT = true, PLANT_GROWTH = true,
                    FOOD = true, EGG = true}
local SIMPLE = {CLOTH = true, THREAD = true, SKIN_TANNED = true, WOOD = true, SEEDS = true,
                ANVIL = true, DRINK = true, BOULDER = true, BLOCKS = true,
                ROUGH = true, SMALLGEM = true}   -- (0.105.24) gems a strange mood waits for

-- What a merchant good is, in the words the planner asks with: BAR:IRON,
-- BAR:STEEL, BAR:COAL (fuel), CLOTH, THREAD, SKIN_TANNED (leather), WOOD,
-- SEEDS, ANVIL, DRINK, FOOD, SOAP, TALLOW, ROUGH, ROUGH:GLASS, SMALLGEM, the
-- smelter's stone (BOULDER:ORE_IRON, :FLUX, :COAL); nil for anything else.
function category(item)
    local tname = df.item_type[item:getType()]
    if tname == 'BAR' or tname == 'GLOB' then
        local ok, tok = pcall(function() return dfhack.matinfo.decode(item):getToken() end)
        if not ok or not tok then return nil end
        if tok:find('SOAP') then return 'SOAP' end
        if tname == 'GLOB' then return tok:find(':TALLOW$') and 'TALLOW' or nil end
        if tok:find('^INORGANIC:') then return 'BAR:' .. tok:sub(11) end
        if tok:find('^COAL') then return 'BAR:COAL' end
        return nil
    end
    if FOOD_TYPES[tname] then return 'FOOD' end
    if tname == 'BOULDER' then return boulder_kind(item) end
    if tname == 'ROUGH' then   -- (item41) raw glass apart: a glass mood's
        local ok, k = pcall(function() return dfhack.matinfo.decode(item):getToken() end)
        if ok and tostring(k):find('^GLASS') then return 'ROUGH:GLASS' end
    end
    if SIMPLE[tname] then return tname end
    return nil
end

-- (0.105.113 item10) a stone's use to the smelter: BOULDER:ORE_IRON (iron's
-- ores: hematite, limonite, magnetite), BOULDER:FLUX (steel's limestone,
-- dolomite, marble, chalk, calcite), BOULDER:COAL (coke), else BOULDER
local IRON_INDEX
function boulder_kind(item)
    local ok, kind = pcall(function()
        local mi = dfhack.matinfo.decode(item)
        if not (mi and mi.inorganic) then return nil end
        if IRON_INDEX == nil then
            local iron = dfhack.matinfo.find('INORGANIC:IRON')
            IRON_INDEX = iron and iron.index or false
        end
        if IRON_INDEX then
            for _, m in ipairs(mi.inorganic.metal_ore.mat_index) do
                if m == IRON_INDEX then return 'BOULDER:ORE_IRON' end
            end
        end
        for _, c in ipairs(mi.material.reaction_class) do
            if c.value == 'FLUX' then return 'BOULDER:FLUX' end
        end
        local tok = mi:getToken()
        if tok == 'INORGANIC:COAL_BITUMINOUS' or tok == 'INORGANIC:LIGNITE' then return 'BOULDER:COAL' end
        return nil
    end)
    return ok and kind or 'BOULDER'
end

local function stack(item)
    local ok, n = pcall(function() return item:getStackSize() end)
    return ok and n or 1
end

-- (0.105.113 item10) an item's weight in DF's units (Γ): volume x density /
-- 100000 a unit (a bauxite figurine 100 x 3100: 3.1, as DF's own count), with
-- what it holds; 0 where the game gives neither
function weight_of(item, depth)
    local ok, w = pcall(function()
        return item:getVolume() * item:getSolidDensity() * math.max(1, stack(item)) / 100000
    end)
    w = (ok and type(w) == 'number') and w or 0
    if (depth or 0) < 2 then
        local okc, inside = pcall(dfhack.items.getContainedItems, item)
        for _, c in ipairs(okc and inside or {}) do w = w + weight_of(c, (depth or 0) + 1) end
    end
    return w
end

local function perceived(item, mer)
    local v = dfhack.items.getValue(item, mer)
    for _, c in ipairs(dfhack.items.getContainedItems(item)) do
        v = v + dfhack.items.getValue(c, mer)
        for _, cc in ipairs(dfhack.items.getContainedItems(c)) do v = v + dfhack.items.getValue(cc, mer) end
    end
    return v
end

local function is_container(item)
    return #dfhack.items.getContainedItems(item) > 0
        or df.item_type[item:getType()] == 'BIN' or df.item_type[item:getType()] == 'BARREL'
        or df.item_type[item:getType()] == 'BOX' or df.item_type[item:getType()] == 'BAG'
end

-- Goods the nobles forbid trading (export bans, mandates), as DFHack's screen
-- finds them; nothing banned if that code isn't there.
local function ban_check()
    local mine = ban_checker()           -- (0.105.41, item 8) ai-bans: ours, and DFHack's with it
    if mine then return mine end
    local ok, common = pcall(reqscript, 'internal/caravan/common')
    if not ok then return function() return false end end
    local okr, risky = pcall(function() return common.get_risky_items(common.get_banned_items()) end)
    if not okr then return function() return false end end
    return function(item)
        local okb, banned, isrisky = pcall(common.scan_banned, item, risky)
        return okb and (banned or isrisky) or false
    end
end

-- Pure: the merchant goods to take. cands {{idx, cat, n, value}}; wants in
-- order {{key, count}}; budget in value. Per want the cheapest per unit
-- first, until the count is met or the budget spent. Returns picks, spent.
-- (R1 g6) a want of one fibre, CLOTH:SILK / THREAD:YARN..., takes only
-- goods of that fibre (a cand's `sub`, 'silk' / 'yarn' / 'plant'): a silk
-- mood was otherwise "met" by the merchants' cheapest (plant) cloth
function want_matches(key, c)
    if c.cat == key then return true end
    -- (0.105.113 item10) BOULDER: any stone, whatever its use
    if key == 'BOULDER' and tostring(c.cat):find('^BOULDER:') then return true end
    -- (item27) BAR:METAL: a mood's bar of no named metal takes any metal bar
    if key == 'BAR:METAL' then
        local m = tostring(c.cat):match('^BAR:(.+)$')
        return m ~= nil and m ~= 'COAL' and m ~= 'POTASH' and m ~= 'PEARLASH' and m ~= 'ASH'
    end
    local base, fibre = tostring(key):match('^([A-Z_]+):([A-Z]+)$')
    return base ~= nil and (base == 'CLOTH' or base == 'THREAD') and c.cat == base
        and type(c.sub) == 'string' and c.sub:upper() == fibre
end

function pick_buys(cands, wants, budget)
    local picks, spent, used = {}, 0, {}
    for _, w in ipairs(wants) do
        local list = {}
        for _, c in ipairs(cands) do
            if want_matches(w.key, c) and not used[c.idx] and c.value > 0 then table.insert(list, c) end
        end
        table.sort(list, function(a, b) return a.value / a.n < b.value / b.n end)
        local got = 0
        for _, c in ipairs(list) do
            if got >= w.count then break end
            if spent + c.value <= budget then
                table.insert(picks, c); used[c.idx] = true
                spent, got = spent + c.value, got + c.n
            end
        end
    end
    return picks, spent
end

-- Pure: the fort's goods to give for `target` value, overpaying as little
-- as possible (the smallest reachable sum at or over it; a greedy pick when
-- the goods are worth too much to search). offers {{idx, value}}.
-- (0.105.113 item10) the merchants answered Weight1/Weight2 (their animals
-- can't carry it: C and F, 7 deals of 22-24 Nov, 44-159 stone crafts worth
-- 20 each offered for 1-4 thousand): the goods most valuable for their weight
-- first, up to OFFER_SLACK times the target (never past max_weight, when
-- given), and the little-over pick made among those only
OFFER_SLACK = 1.5
function dense_first(offers, target, max_weight)
    local list = {}
    for _, o in ipairs(offers) do if o.value > 0 then table.insert(list, o) end end
    local function dens(o) return o.value / math.max(o.weight or 0, 0.01) end
    table.sort(list, function(a, b)
        local da, db = dens(a), dens(b)
        if da ~= db then return da > db end
        return a.value > b.value
    end)
    local out, sum, w = {}, 0, 0
    for _, o in ipairs(list) do
        if sum >= target * OFFER_SLACK then break end
        if not max_weight or w + (o.weight or 0) <= max_weight + 1e-6 then
            table.insert(out, o); sum, w = sum + o.value, w + (o.weight or 0)
        end
    end
    return out, sum
end

function pick_offers(offers, target, max_weight)
    local list, total = dense_first(offers, target, max_weight)
    if total < target then return list, total end
    if total <= 20000 and #list <= 400 then
        local reach = {[0] = {}}
        for i, o in ipairs(list) do
            for sum = total - o.value, 0, -1 do
                if reach[sum] and not reach[sum + o.value] then reach[sum + o.value] = {prev = sum, i = i} end
            end
        end
        local best = target
        while not reach[best] do best = best + 1 end
        local picks, sum = {}, best
        while sum > 0 do
            table.insert(picks, list[reach[sum].i]); sum = reach[sum].prev
        end
        return picks, best
    end
    table.sort(list, function(a, b) return a.value > b.value end)
    local picks, sum = {}, 0
    for _, o in ipairs(list) do
        if sum >= target then break end
        table.insert(picks, o); sum = sum + o.value
    end
    return picks, sum
end

-- Both sides' goods as the deal sees them.
-- (R1 g6) a cloth or thread's fibre ('silk', 'yarn', 'plant'), ai-moods' own test; nil otherwise
local FIBRE_TYPES = {CLOTH = true, THREAD = true}
local function fibre_of(item)
    local ok, k = pcall(function()
        if not FIBRE_TYPES[df.item_type[item:getType()]] then return nil end
        return reqscript('ai-moods').cloth_kind(item)
    end)
    return ok and k or nil
end

local function sides(trade, txt)
    local mer = trade.mer
    local banned = ban_check()
    local cands, offers = {}, {}
    -- merchants: loose goods, goods in a bin one by one, a barrel or bag whole
    local parent_ok = false
    for i, item in ipairs(trade.good[MERCHANT]) do
        local flag = trade.goodflag[MERCHANT][i]
        if not flag.contained then
            local tname = df.item_type[item:getType()]
            parent_ok = (tname == 'BIN')
            local cat
            if is_container(item) and tname ~= 'BIN' then
                local inside = dfhack.items.getContainedItems(item)
                local n, sub, first = 0, nil, true
                for _, c in ipairs(inside) do
                    local cc = category(c)
                    if cat == nil then cat = cc elseif cc ~= cat then cat = false end
                    local f = fibre_of(c)                    -- (R1 g6) one fibre throughout, or none
                    if first then sub, first = f, false elseif sub ~= f then sub = false end
                    n = n + stack(c)
                end
                if cat then table.insert(cands, {idx = i, cat = cat, n = n, value = perceived(item, mer),
                                                  sub = sub or nil, weight = weight_of(item),
                                                  name = (txt or tostring)(dfhack.items.getDescription(item, 0, true))}) end
            elseif not is_container(item) then
                cat = category(item)
                if cat then table.insert(cands, {idx = i, cat = cat, n = stack(item), value = perceived(item, mer), weight = weight_of(item),
                                                  sub = fibre_of(item),
                                                  name = (txt or tostring)(dfhack.items.getDescription(item, 0, true))}) end
            end
        elseif parent_ok then
            local cat = category(item)
            if cat then table.insert(cands, {idx = i, cat = cat, n = stack(item), value = perceived(item, mer), weight = weight_of(item),
                                              sub = fibre_of(item),
                                              name = (txt or tostring)(dfhack.items.getDescription(item, 0, true))}) end
        end
    end
    -- the fort: crafts of stone, metal or gems (never wood or animal goods,
    -- which some caravans refuse), loose or one by one out of their bins;
    -- never anything the nobles ban
    for i, item in ipairs(trade.good[FORT]) do
        if GOOD_TYPE[item:getType()] and trade_material(item) and not is_container(item)
                and not banned(item) and not is_artifact(item) then
            table.insert(offers, {idx = i, value = perceived(item, mer), weight = weight_of(item),
                                  name = (txt or tostring)(dfhack.items.getDescription(item, 0, true))})
        end
    end
    return cands, offers
end

local function ready(trade)
    return trade.open and trade.havetalker == 1 and trade.stillunloading == 0 and not trade.counter_offer
end

local function clear(trade)
    for side = 0, 1 do
        for i = 0, #trade.goodflag[side] - 1 do trade.goodflag[side][i].selected = false end
    end
end

-- Tick a deal on the open trade screen. wants {{key, count}} in order of
-- need. Returns what was ticked; dry_run ticks nothing. (0.105.113 item10)
-- max_weight: the most the fort's goods may outweigh the bought ones (after
-- a Weight1/Weight2 answer, press_lighter)
function deal(wants, margin, dry_run, txt, extra, max_weight)
    local trade = trade_screen()
    if not trade.open then return {ok = true, waiting = true, error = 'the trade screen is not open'} end
    if not ready(trade) then
        return {ok = true, waiting = true, error = 'the merchants are not ready (unloading, no broker, or a counter-offer up)'}
    end
    if is_done(trade.mer) and not dry_run then
        return {ok = false, rejected = true,
                error = 'the merchants turned down the AI\'s last offer: this caravan\'s trade is yours'}
    end
    margin = math.max(margin or MARGIN, learned_margin())
    local cands, offers = sides(trade, txt)
    local have = 0
    for _, o in ipairs(offers) do have = have + o.value end
    if max_weight and have > 0 then
        local _, light = dense_first(offers, math.huge, max_weight)
        have = light
    end
    if have == 0 then return {ok = false, rejected = true, error = 'none of the fort\'s crafts are at the depot to pay with'} end
    local buys, spent = pick_buys(cands, wants or {}, math.floor(have / margin))
    local fallback
    if #buys == 0 and type(extra) == 'table' and #extra > 0 then
        -- (r2 h5) none of what the fort needs is on sale: what any fort can use
        buys, spent = pick_buys(cands, extra, math.floor(have / margin))
        fallback = #buys > 0 or nil
    end
    if #buys == 0 then
        return {ok = false, rejected = true, error = 'the merchants have nothing the fort wants that its goods can pay for',
                offer_value = have, merchant_goods = #cands}
    end
    local buy_w = 0
    for _, b in ipairs(buys) do buy_w = buy_w + (b.weight or 0) end
    local pays, paid = pick_offers(offers, math.ceil(spent * margin), max_weight and (max_weight + buy_w) or nil)
    local give_w = 0
    for _, o in ipairs(pays) do give_w = give_w + (o.weight or 0) end
    local bought, given = {}, {}
    for _, b in ipairs(buys) do table.insert(bought, ('%s (%s x%d, %d)'):format(b.name, b.cat, b.n, b.value)) end
    for _, o in ipairs(pays) do table.insert(given, o.name) end
    if not dry_run then
        clear(trade)
        for _, b in ipairs(buys) do trade.goodflag[MERCHANT][b.idx].selected = true end
        for _, o in ipairs(pays) do trade.goodflag[FORT][o.idx].selected = true end
    end
    return {ok = true, dry_run = dry_run or nil, buy_value = spent, give_value = paid, bought = bought, margin = margin,
            fallback = fallback, max_weight = max_weight,
            give_weight = math.floor(give_w * 10 + 0.5) / 10, buy_weight = math.floor(buy_w * 10 + 0.5) / 10,
            given = #given, given_sample = {table.unpack(given, 1, math.min(8, #given))},
            calibrated = buttons().Trade ~= nil,
            can_search = UNREADABLE ~= true}      -- (r2 h5) the Trade button looked for by its word
end

-- (r9) this file's locals the later parts use (each takes back the ones it
-- uses as locals of its own): all functions and fixed values, set once here
PART_LOCALS = {U = U, translate = translate, report_units = report_units, depot = depot, caravans = caravans, GOOD_TYPE = GOOD_TYPE, is_artifact = is_artifact, goods = goods, trade_screen = trade_screen, perceived = perceived, sides = sides, ready = ready, clear = clear}

---------------------------------------------------------------------------
-- (r9) The rest of the trade lives in parts beside this file
-- (ai-trade-<part>.lua): unload (0.105.119: the fort's goods out of the
-- depot, a done caravan's goods cleared; first, where they stood), screen (pressing the trade screen's buttons, the
-- caravans done, opening the trade screen) and depot (someone called to
-- the depot to trade, the probe of the screen). Each runs in this module's
-- own environment, so its names stay reqscript('ai-trade').name for the
-- bridge and the other modules, and a test's swap (T.press = ...) reaches
-- every part. They load in this order. DFHack reloads a module when its own
-- file changes: a change to a part alone is picked up once ai-trade.lua is
-- touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'unload', 'screen', 'depot'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-trade'] = '0.105.121'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-trade-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-trade: ' .. name .. '.lua is missing (it goes beside ai-trade.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
