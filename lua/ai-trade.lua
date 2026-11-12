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
local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end
local function report_units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end

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

-- A good the AI may sell, loose (not in a bin): stone, metal, gems or glass.
local function sellable(item)
    return not unsellable(item) and trade_material(item)
        and not (KEEP_TREASURES and treasure(item))
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

-- What to take: {items (loose goods and whole bins), value, count of goods}.
local function goods(dep, limit)
    local out, value, count, bins = {}, 0, 0, {}
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

-- The report's "trade" section.
function survey(txt)
    local dep = depot()
    local out = {depot = dep ~= nil, caravans = caravans(txt)}
    if dep then
        local ok, list, value, count = pcall(goods, dep, 500)
        if ok then out.goods, out.goods_value, out.loads = count, value, #list end
        local at = 0
        for _, ci in ipairs(dep.contained_items) do
            if ci.use_mode == df.building_item_role_type.TEMP then at = at + 1 end
        end
        out.at_depot = at
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
        return {ok = true, items = n, loads = marked, value = value, caravan = cs[1].civ}
    end
    return {ok = true, dry_run = true, items = n, loads = #list, value = value, caravan = cs[1].civ}
end

-- (0.103.9) The fort's goods left in the depot once the caravans have gone:
-- set down on the depot's tile, so the haulers store them again and dwarves
-- can own them (DF leaves them there until the next caravan: Enxah, 163).
function unload(limit, dry_run, txt)
    local busy_n = 0
    local dep = depot()
    if not dep then return {ok = false, rejected = true, error = 'no trade depot built yet'} end
    if #caravans(txt) > 0 then return {ok = false, rejected = true, error = 'a caravan is coming or at the depot'} end
    local items = {}
    for _, ci in ipairs(dep.contained_items) do
        if ci.use_mode == df.building_item_role_type.TEMP and ci.item then
            -- (0.104.138) one a hauler is already carrying out is left to him
            local busy = false
            pcall(function() busy = ci.item.flags.in_job end)
            if busy then busy_n = busy_n + 1 else table.insert(items, ci.item) end
        end
    end
    if #items == 0 and busy_n > 0 then
        return {ok = false, rejected = true, waiting = true, error = busy_n .. ' item(s) are being hauled out of the depot'}
    end
    if #items == 0 then return {ok = false, rejected = true, error = 'nothing of the fort\'s is in the depot'} end
    local n = math.min(#items, limit or 50)
    if dry_run then return {ok = true, dry_run = true, items = n, at_depot = #items} end
    local pos, moved, failed = xyz2pos(dep.centerx, dep.centery, dep.z), 0, nil
    for i = 1, n do
        local item = items[i]
        local ok, r = pcall(dfhack.items.moveToGround, item, pos)
        if ok and r ~= false and not item.flags.in_building then
            moved = moved + 1
        else
            failed = ok and 'the game kept it in the depot' or tostring(r):sub(1, 120)
        end
    end
    if moved == 0 then return {ok = false, error = 'none moved out of the depot: ' .. tostring(failed)} end
    return {ok = true, items = moved, left = #items - moved, error = failed}
end

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
-- SEEDS, ANVIL, DRINK, FOOD, SOAP, TALLOW, ROUGH and SMALLGEM (gems); nil for anything else.
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
    if SIMPLE[tname] then return tname end
    return nil
end

local function stack(item)
    local ok, n = pcall(function() return item:getStackSize() end)
    return ok and n or 1
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
function pick_buys(cands, wants, budget)
    local picks, spent, used = {}, 0, {}
    for _, w in ipairs(wants) do
        local list = {}
        for _, c in ipairs(cands) do
            if c.cat == w.key and not used[c.idx] and c.value > 0 then table.insert(list, c) end
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
function pick_offers(offers, target)
    local list, total = {}, 0
    for _, o in ipairs(offers) do if o.value > 0 then table.insert(list, o); total = total + o.value end end
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
                local n = 0
                for _, c in ipairs(inside) do
                    local cc = category(c)
                    if cat == nil then cat = cc elseif cc ~= cat then cat = false end
                    n = n + stack(c)
                end
                if cat then table.insert(cands, {idx = i, cat = cat, n = n, value = perceived(item, mer),
                                                  name = (txt or tostring)(dfhack.items.getDescription(item, 0, true))}) end
            elseif not is_container(item) then
                cat = category(item)
                if cat then table.insert(cands, {idx = i, cat = cat, n = stack(item), value = perceived(item, mer),
                                                  name = (txt or tostring)(dfhack.items.getDescription(item, 0, true))}) end
            end
        elseif parent_ok then
            local cat = category(item)
            if cat then table.insert(cands, {idx = i, cat = cat, n = stack(item), value = perceived(item, mer),
                                              name = (txt or tostring)(dfhack.items.getDescription(item, 0, true))}) end
        end
    end
    -- the fort: crafts of stone, metal or gems (never wood or animal goods,
    -- which some caravans refuse), loose or one by one out of their bins;
    -- never anything the nobles ban
    for i, item in ipairs(trade.good[FORT]) do
        if GOOD_TYPE[item:getType()] and trade_material(item) and not is_container(item)
                and not banned(item) and not is_artifact(item) then
            table.insert(offers, {idx = i, value = perceived(item, mer),
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
-- need. Returns what was ticked; dry_run ticks nothing.
function deal(wants, margin, dry_run, txt)
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
    if have == 0 then return {ok = false, rejected = true, error = 'none of the fort\'s crafts are at the depot to pay with'} end
    local buys, spent = pick_buys(cands, wants or {}, math.floor(have / margin))
    if #buys == 0 then
        return {ok = false, rejected = true, error = 'the merchants have nothing the fort wants that its goods can pay for',
                offer_value = have, merchant_goods = #cands}
    end
    local pays, paid = pick_offers(offers, math.ceil(spent * margin))
    local bought, given = {}, {}
    for _, b in ipairs(buys) do table.insert(bought, ('%s (%s x%d, %d)'):format(b.name, b.cat, b.n, b.value)) end
    for _, o in ipairs(pays) do table.insert(given, o.name) end
    if not dry_run then
        clear(trade)
        for _, b in ipairs(buys) do trade.goodflag[MERCHANT][b.idx].selected = true end
        for _, o in ipairs(pays) do trade.goodflag[FORT][o.idx].selected = true end
    end
    return {ok = true, dry_run = dry_run or nil, buy_value = spent, give_value = paid, bought = bought, margin = margin,
            given = #given, given_sample = {table.unpack(given, 1, math.min(8, #given))},
            calibrated = buttons().Trade ~= nil}
end

-- --- pressing the screen's buttons --------------------------------------------------

function buttons()
    return U.site_get(BUTTONS_KEY, {})
end

-- Remember where a button is: the mouse is on it now (the player put it
-- there). Kept from the screen's centre and bottom, so a resized window
-- still finds it.
-- Buttons: Trade (the trade screen's, kept from the centre and bottom) and
-- Depot (the Trade button on the depot's sheet, which sits on the right:
-- kept from the right edge and the top).
function calibrate(name)
    local gps = df.global.gps
    local x, y = gps.mouse_x, gps.mouse_y
    if x < 0 or y < 0 then return {ok = false, error = 'the game doesn\'t know where the mouse is: put it on the button in DF'} end
    if name == 'Depot' then
        local vs = df.global.game.main_interface.view_sheets
        local b = vs.open and vs.active_sheet == df.view_sheet_type.BUILDING and df.building.find(vs.active_id)
        if not (b and df.building_tradedepotst:is_instance(b)) then
            return {ok = false, error = 'open the trade depot\'s sheet first (click the depot), then put the mouse on its Trade button'}
        end
    end
    local d = buttons()
    d[name] = {dx = x - gps.dimx // 2, dy = gps.dimy - y, rx = gps.dimx - x, ty = y,
               anchor = name == 'Depot' and 'right-top' or 'centre-bottom',
               x = x, y = y, w = gps.dimx, h = gps.dimy}
    dfhack.persistent.saveSiteData(BUTTONS_KEY, d)
    return {ok = true, button = name, x = x, y = y, screen = {gps.dimx, gps.dimy}}
end

function button_at(b)
    local gps = df.global.gps
    if b.anchor == 'right-top' then return gps.dimx - b.rx, b.ty end
    return gps.dimx // 2 + b.dx, gps.dimy - b.dy
end

local function click(x, y)
    local gps = df.global.gps
    local ox, oy = gps.mouse_x, gps.mouse_y
    gps.mouse_x, gps.mouse_y = x, y
    pcall(function()
        gps.precise_mouse_x = x * gps.tile_pixel_x + gps.tile_pixel_x // 2
        gps.precise_mouse_y = y * gps.tile_pixel_y + gps.tile_pixel_y // 2
    end)
    local gui = require('gui')
    gui.simulateInput(dfhack.gui.getDFViewscreen(true), '_MOUSE_L')
    gps.mouse_x, gps.mouse_y = ox, oy
end

-- DFHack's confirm tool asks before trading or leaving the screen (seen in
-- game, 0.56.0): its question turned off for one call only (in memory, the
-- settings file untouched), then back on.
function without_confirm(id, fn, ...)
    local okc, conf = pcall(function() return reqscript('internal/confirm/specs').config.data[id] end)
    local was_on = okc and conf ~= nil and conf.enabled
    if was_on then conf.enabled = false end
    local res = table.pack(pcall(fn, ...))
    if was_on then conf.enabled = true end
    return table.unpack(res, 1, res.n)
end

function ticked_set(trade, side)
    local set = {}
    for i = 0, #trade.goodflag[side] - 1 do if trade.goodflag[side][i].selected then set[i] = true end end
    return set
end

function ticked_value(trade, side)
    local v = 0
    for i = 0, #trade.goodflag[side] - 1 do
        if trade.goodflag[side][i].selected then v = v + perceived(trade.good[side][i], trade.mer) end
    end
    return v
end

MARGIN_KEY = 'ai-overseer/trade-margin'

function learned_margin()
    return tonumber(U.site_get(MARGIN_KEY, {}).margin) or 0
end

function save_margin(m)
    m = math.min(3, math.max(learned_margin(), m))
    U.site_put(MARGIN_KEY, {margin = m})
end

-- Press the Trade button on the open screen (where calibrate put it). It
-- refuses unless something is ticked on both sides; afterwards it reads the
-- merchants' answer (DF's talk line) and whether the ticked goods left.
function press(name, txt)
    name = name or 'Trade'
    local trade = trade_screen()
    if not trade.open then return {ok = false, rejected = true, error = 'the trade screen is not open'} end
    if not ready(trade) then return {ok = false, rejected = true, error = 'the merchants are not ready'} end
    local b = buttons()[name]
    if not b then return {ok = false, rejected = true, error = 'the AI doesn\'t know where the ' .. name .. ' button is yet (calibrate)'} end
    local function ticked(side)
        local n = 0
        for i = 0, #trade.goodflag[side] - 1 do if trade.goodflag[side][i].selected then n = n + 1 end end
        return n
    end
    local before = {ticked(MERCHANT), ticked(FORT), #trade.good[MERCHANT], #trade.good[FORT]}
    if before[1] == 0 or before[2] == 0 then
        return {ok = false, rejected = true, error = 'nothing ticked on one side: no trade to press for'}
    end
    local gps = df.global.gps
    local x, y = button_at(b)
    -- DFHack's confirm tool asks "Are you sure you want to trade the selected
    -- goods?" on a click there (seen in game, 0.56.0): turned off for this one
    -- click only (in memory, its settings file untouched), then back on
    local fort_before = ticked_set(trade, FORT)
    local okk, err = without_confirm('trade-confirm-trade', click, x, y)
    if not okk then return {ok = false, error = 'the click failed: ' .. tostring(err):sub(1, 200)} end
    local talk = df.talk_line_type[trade.talkline] or tostring(trade.talkline)
    -- a counter-offer: the merchants tick more of the fort's goods (in game,
    -- 0.56.1: 15 ticked became 20). Taken if they're only crafts and not
    -- dearer than half the deal (+30), and pressed again; the margin learned for
    -- next time. Else unticked and left to the player.
    local counter
    if talk == 'CounterOffer' or trade.counter_offer then
        local mer, extra, value, only_crafts = trade.mer, {}, 0, true
        for i = 0, #trade.goodflag[FORT] - 1 do
            if trade.goodflag[FORT][i].selected and not fort_before[i] then
                local it = trade.good[FORT][i]
                table.insert(extra, i)
                value = value + perceived(it, mer)
                if not (GOOD_TYPE[it:getType()] and trade_material(it)) or is_artifact(it) then
                    only_crafts = false     -- (0.100) an artifact asked for: the counter-offer isn't taken
                end
            end
        end
        local buy, give = ticked_value(trade, MERCHANT), ticked_value(trade, FORT) - value
        counter = {items = #extra, value = value, only_crafts = only_crafts, buy = buy, give = give}
        if #extra > 0 and only_crafts and value <= buy / 2 + 30 then
            if buy > 0 then save_margin((give + value) / buy * 1.05) end
            pcall(function() trade.counter_offer = false end)
            without_confirm('trade-confirm-trade', click, x, y)
            talk = df.talk_line_type[trade.talkline] or tostring(trade.talkline)
            counter.accepted = true
        else
            for _, i in ipairs(extra) do trade.goodflag[FORT][i].selected = false end
            pcall(function() trade.counter_offer = false end)
            counter.accepted = false
        end
    end
    local focus
    pcall(function() focus = table.concat(dfhack.gui.getFocusStrings(dfhack.gui.getCurViewscreen(true)), ' ') end)
    local after = {ticked(MERCHANT), ticked(FORT), #trade.good[MERCHANT], #trade.good[FORT]}
    local traded = after[3] < before[3] or after[4] < before[4]
    -- done: close the screen (the game goes on; nothing is ticked, so
    -- DFHack's "leave the screen?" question wouldn't come up anyway)
    local closed
    if traded or talk ~= 'NONE' then
        without_confirm('trade-cancel', function()
            require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
        end)
        closed = not trade.open
    end
    -- one try a caravan: haggling again and again ends the trading for good
    -- (a click that got no answer at all, e.g. a dialog in the way, isn't a refusal)
    if traded or (talk ~= 'NONE' and talk ~= 'Greet' and talk ~= 'HarshGreet') then mark_done(trade.mer) end
    return {ok = true, pressed = name, at = {x, y}, answer = talk, traded = traded, screen_now = focus,
            counter = counter, closed = closed,
            counter_offer = trade.counter_offer or nil,
            before = before, after = after}
end

-- A caravan the AI has traded with (or been turned down by, or found
-- nothing to buy from) this visit: the screen isn't opened for it again.
-- Kept by the caravan's civ and the value it came with (fixed for a visit).
DONE = DONE or {}

function caravan_key(c)
    local ok, k = pcall(function() return tostring(c.entity) .. ':' .. tostring(c.import_value) end)
    return ok and k or nil
end

function opened_by_ai()
    local ok, t = pcall(trade_screen)
    if not (ok and t.open) then return false end
    -- (0.100, review) the screen came up after the click's check, 3 frames
    -- on (a slow frame): it's the AI's if it opened within 2 minutes of the
    -- AI's click and nobody else's yet
    if OPENED_FOR == nil and OPEN_CLICKED_AT and os.time() - OPEN_CLICKED_AT <= 120 then
        OPENED_FOR = caravan_key(t.mer)
    end
    return OPENED_FOR ~= nil and OPENED_FOR == caravan_key(t.mer) or false
end

function mark_done(c) local k = caravan_key(c); if k then DONE[k] = true end end
function is_done(c) local k = caravan_key(c); return k ~= nil and DONE[k] == true end

-- Close the trade screen (nothing to buy, or the deal refused), without
-- DFHack's "leave the screen?" question.
function close_screen(unloading)
    local trade = trade_screen()
    if not trade.open then return {ok = true, closed = true} end
    if unloading then
        -- opened too early: the merchants can't unload while the screen holds
        -- time still. Closed, not counted as traded; opened again later.
        OPEN_AFTER = trade_now() + UNLOAD_RETRY_TICKS
    else
        mark_done(trade.mer)
    end
    clear(trade)
    without_confirm('trade-cancel', function()
        require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
    end)
    return {ok = not trade.open, closed = not trade.open,
            error = trade.open and 'the trade screen did not close' or nil}
end

-- --- opening the trade screen ---------------------------------------------------------
--
-- What the player does: the depot's sheet (view_sheets set to the
-- building, as DFHack's own tests open a unit's sheet), then its Trade
-- button (where the player showed it once: calibrate 'Depot'). Only from
-- the plain map or a sheet, so a menu the player has open isn't disturbed.
UNLOAD_QUIET_TICKS = 300     -- the merchants' goods in the depot unchanged this long: unloaded
UNLOAD_RETRY_TICKS = 600     -- after closing a screen opened too early, wait this long
LOAD_WATCH = LOAD_WATCH or {}

function trade_now()
    return U.abs_tick()
end

-- Are the merchants still carrying their goods into the depot? (The trade
-- screen opened then only says "unloading", and holds time still, so they
-- never finish.) Their goods in the depot must hold still for
-- UNLOAD_QUIET_TICKS. If the screen still opens too early, the planner
-- closes it again (close_screen(true)) and it is opened later.
function unloading(dep)
    local n = 0
    pcall(function()
        for _, ref in ipairs(dep.contained_items) do
            if ref.item.flags.trader then n = n + 1 end
        end
    end)
    local busy = 0
    pcall(function()
        for _, u in ipairs(report_units()) do
            if u.flags1.merchant and not u.flags1.inactive and dfhack.units.isActive(u) and u.job.current_job then
                busy = busy + 1
            end
        end
    end)
    local now = trade_now()
    -- (merchants with a job are only reported: one may well have a job for
    -- some other reason, and that mustn't keep the screen shut all visit)
    if LOAD_WATCH.n ~= n or LOAD_WATCH.dep ~= dep.id or not LOAD_WATCH.since or now < LOAD_WATCH.since then
        LOAD_WATCH = {n = n, dep = dep.id, since = now}
    end
    local quiet = now - LOAD_WATCH.since
    if quiet < UNLOAD_QUIET_TICKS then
        return true, ('the merchants are still unloading (%d of their goods in the depot, %d busy, steady %d ticks)')
            :format(n, busy, quiet)
    end
    return false
end

function open_screen(dry_run, txt)
    local trade = trade_screen()
    if trade.open then return {ok = true, open = true, note = 'already open'} end
    local fresh = false
    for _, c in ipairs(df.global.plotinfo.caravans) do
        if c.trade_state == df.caravan_state.T_trade_state.AtDepot and not is_done(c) then fresh = true end
    end
    if not fresh then return {ok = true, waiting = true, error = 'the AI has already traded with the caravan(s) at the depot'} end
    local dep = depot()
    if not dep then return {ok = false, rejected = true, error = 'no trade depot built yet'} end
    local job = trade_job(dep)
    local w = job and dfhack.job.getWorker(job)
    if not at_depot(w, dep) then return {ok = true, waiting = true, error = 'nobody is at the depot to trade yet'} end
    if OPEN_AFTER and trade_now() < OPEN_AFTER then
        return {ok = true, waiting = true, error = 'the screen was opened while the merchants unloaded: waiting a while'}
    end
    local still, why = unloading(dep)
    if still then return {ok = true, waiting = true, error = why} end
    local b = buttons().Depot
    if not b then
        return {ok = false, rejected = true,
                error = 'the AI doesn\'t know where the depot\'s Trade button is yet (probe_trade.py --here-depot)'}
    end
    local okf, plain = pcall(function()
        return dfhack.gui.matchFocusString('dwarfmode/Default') or dfhack.gui.matchFocusString('dwarfmode/ViewSheets')
    end)
    if okf and not plain then return {ok = true, waiting = true, error = 'the player has a menu open'} end
    local vs = df.global.game.main_interface.view_sheets
    if dry_run then return {ok = true, dry_run = true, at = {button_at(b)}} end
    vs.open = true
    pcall(function() vs.context = df.view_sheets_context_type.REGULAR_PLAY end)
    vs.active_sheet = df.view_sheet_type.BUILDING
    vs.active_id = dep.id
    vs.viewing_bldid = dep.id
    pcall(function() vs.active_sub_tab = 0 end)
    -- the game lays the sheet out when it draws it: the click a few frames
    -- later (dfhack.timeout counts frames even while paused); the result is
    -- seen on the next cycle (the trade report's screen.open)
    local x, y = button_at(b)
    OPEN_CLICKED_AT, OPENED_FOR = os.time(), nil
    dfhack.timeout(3, 'frames', function()
        local okc, err = pcall(click, x, y)
        LAST_OPEN = {clicked = okc, error = not okc and tostring(err) or nil, opened = trade.open}
        if trade.open then
            OPENED_FOR = caravan_key(trade.mer)
            vs.open = false
            vs.active_sheet = df.view_sheet_type.NONE
            vs.active_id = -1
        end
    end)
    return {ok = true, clicking = true, at = {x, y}}
end

-- --- someone to the depot ---------------------------------------------------------
--
-- The depot's "request trader" (trade_flags.trader_requested, and the
-- TradeAtDepot job it brings, as DFHack's caravan tool clears them) while a
-- caravan is coming or there; when nobody has come after `wait` ticks,
-- "anyone may trade" (trade_flags.anyone_can_trade), turned back off when
-- the caravans are gone if the AI turned it on.
CALL_KEY = 'ai-overseer/trade-call'

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
        if st.anyone_by_ai and not dry_run then dep.trade_flags.anyone_can_trade = false end
        if next(st) and not dry_run then U.site_put(CALL_KEY, {}) end
        return {ok = true, waiting = true, error = 'no caravan is coming or at the depot'}
    end
    local job = trade_job(dep)
    local worker = job and dfhack.job.getWorker(job)
    if worker and at_depot(worker, dep) then
        return {ok = true, at_depot = true, trader = (txt or tostring)(dfhack.units.getReadableName(worker))}
    end
    if dry_run then return {ok = true, dry_run = true, requested = dep.trade_flags.trader_requested} end
    local out = {ok = true}
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
    if not dep.trade_flags.anyone_can_trade and st.since and now - st.since >= wait then
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
