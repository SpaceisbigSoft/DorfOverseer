-- ai-trade-screen: the trade screen's buttons pressed (calibrated, judged by
-- what the screen says after), the caravans done, the screen opened.
--
-- (r9) A part of ai-trade, not a script of its own: ai-trade.lua loads it
-- into its own environment, so every name here is reqscript('ai-trade').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-trade-screen is a part of ai-trade; run ai-trade') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-trade-screen'] = '0.105.120'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_units, depot, GOOD_TYPE, is_artifact, goods, trade_screen, perceived, ready, clear = PART_LOCALS.U, PART_LOCALS.report_units, PART_LOCALS.depot, PART_LOCALS.GOOD_TYPE, PART_LOCALS.is_artifact, PART_LOCALS.goods, PART_LOCALS.trade_screen, PART_LOCALS.perceived, PART_LOCALS.ready, PART_LOCALS.clear   -- (r9) the hub's locals

-- --- pressing the screen's buttons --------------------------------------------------

-- (0.105.47) the save's, else this PC's (shown in any save here), else the
-- AI's own guess (lua/ai-screen-buttons.lua): the 11 Nov forts had none
-- shown, so no trade screen was ever opened in the 8-13 Nov run
function buttons()
    local ok, d = pcall(function() return reqscript('ai-screen-buttons').get(BUTTONS_KEY) end)
    if ok and type(d) == 'table' then return d end
    return U.site_get(BUTTONS_KEY, {})
end

-- (0.105.47 review) A guessed button is pressed only where the screen reads
-- "Trade" at the guessed tile, never where it reads Seize or Offer (a seize
-- turns the caravan's civilisation hostile for good). Forbidden word, or text
-- that can't be read (TrueType): the guess retired at once, so the Needs you
-- comes back; readable without the word: a miss. Returns true to press, or
-- false and why.
-- (0.105.48, K9) A shown place (this save's or the PC's, a guess that worked
-- included) gets the forbidden-word check too whenever the text can be read:
-- Seize or Offer there, not pressed (a window resized, a place shared from
-- another save); missing or unreadable text doesn't stop a shown place.
function guess_word_ok(name, b, x, y)
    if not b then return true end
    local ok, v, w = pcall(function() return reqscript('ai-screen-buttons').check_word(x, y, 'Trade') end)
    if not ok then v = 'unreadable' end
    if v == 'ok' then return true end
    if not b.default then
        if v == 'forbidden' then
            return false, 'the ' .. name .. ' button\'s place reads "' .. tostring(w) .. '" there now: not pressed ' ..
                          '(show it again: probe_trade.py --here' .. (name == 'Depot' and '-depot' or '') .. ')', v
        end
        return true
    end
    local why = v == 'forbidden' and ('the guessed ' .. name .. ' button reads "' .. tostring(w) .. '" there: not pressed')
        or v == 'missing' and ('the guessed ' .. name .. ' button doesn\'t read "Trade" there: not pressed')
        or ('the screen\'s text by the guessed ' .. name .. ' button can\'t be read: not pressed blind')
    pcall(function()
        reqscript('ai-screen-buttons').miss(BUTTONS_KEY, name, why, v ~= 'missing')
    end)
    return false, why, v
end

-- (0.105.48, K9) the merchants' lines that answer a trade proposal
-- (df.talk_line_type): only the Trade button brings one
TRADE_REPLIES = {Trade = true, Haggle = true, CounterOffer = true, CouldNotFindCounterOffer1 = true,
                 CouldNotFindCounterOffer2 = true, ICannotAfford = true, YouCannotAfford = true,
                 NoMoreTradeHaggleFailure = true}
-- the lines of the other buttons beside it (a gift, a seize)
WRONG_REPLIES = {Offer = true, Seize = true, OfferJoke = true, SeizeJoke = true}
-- (0.105.113 item10) "we can't carry that": the merchants' animals and
-- wagons are full (C and F, 7 deals 22-24 Nov, each caravan then left with
-- nothing traded). Not a refusal of the price: the deal ticked again lighter
-- and pressed again (press_lighter), the caravan not marked done for it
WEIGHT_REPLIES = {Weight1 = true, Weight2 = true}
TRADE_REPLIES.Weight1, TRADE_REPLIES.Weight2 = true, true    -- the Trade button's answer all the same
WEIGHT_RETRIES = 3
WEIGHT_HAGGLE_MAX = 2      -- the caravan's haggle_fail_count at which no try more is made
WEIGHT_CUT = {Weight1 = 0.6, Weight2 = 0.4}

-- Pure: what a press did, from the talk line before and after, whether the
-- goods moved and whether a counter-offer came up: 'worked' (a trade
-- answer), 'wrong' (a gift's or a seize's line, or goods gone without a
-- trade answer), 'none' (nothing changed).
function after_verdict(before, after, traded, countered)
    if WRONG_REPLIES[after] then return 'wrong' end
    if TRADE_REPLIES[after] or countered then return 'worked' end
    if traded then return 'wrong' end
    return 'none'
end

-- (0.105.47) a guess's check: kept for every save when it worked, counted
-- (retired after two, or at once with `now`) when it didn't
local function guess_result(name, b, worked, why, now)
    if not (b and b.default) then return end
    pcall(function()
        local B = reqscript('ai-screen-buttons')
        if worked then B.share(BUTTONS_KEY, name, b) else B.miss(BUTTONS_KEY, name, why, now) end
    end)
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
    local d = U.site_get(BUTTONS_KEY, {})   -- (0.105.47) the save's own, not the merged guesses
    d[name] = {dx = x - gps.dimx // 2, dy = gps.dimy - y, rx = gps.dimx - x, ty = y,
               anchor = name == 'Depot' and 'right-top' or 'centre-bottom',
               x = x, y = y, w = gps.dimx, h = gps.dimy}
    dfhack.persistent.saveSiteData(BUTTONS_KEY, d)
    -- (0.105.47) and for every save on this PC
    pcall(function() reqscript('ai-screen-buttons').share(BUTTONS_KEY, name, d[name]) end)
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

-- (item9) the ticked goods of one side with their owner flag (flags.trader:
-- the merchants'), read before a press; nil where the game gives no flags
function ticked_owners(trade, side)
    local list = {}
    for i = 0, #trade.goodflag[side] - 1 do
        if trade.goodflag[side][i].selected then
            local it = trade.good[side][i]
            local ok, tr = pcall(function() return it.flags.trader end)
            if ok and type(tr) == 'boolean' then table.insert(list, {it = it, trader = tr}) end
        end
    end
    return list
end

-- (item9) how many of those goods changed hands since: theirs now the fort's
-- (bought), the fort's now theirs (sold)
function owner_changes(mer, fort)
    local bought, sold = 0, 0
    for _, e in ipairs(mer) do
        local ok, tr = pcall(function() return e.it.flags.trader end)
        if ok and e.trader and tr == false then bought = bought + 1 end
    end
    for _, e in ipairs(fort) do
        local ok, tr = pcall(function() return e.it.flags.trader end)
        if ok and not e.trader and tr == true then sold = sold + 1 end
    end
    return bought, sold
end

-- (item9) Pure: whether a press made a deal. The goods leaving the lists
-- (moved), the ticked goods changing owner, or the merchants' "Trade" line
-- (their yes: in all six forts, 23-24 Nov, 117 presses were answered
-- "Trade" with both lists and every tick unchanged, and the fort had the
-- goods bought afterwards: foreign cloth, leather and fruit matching the
-- deals' lists). Before, only `moved` counted, so every deal was logged "NOT
-- traded" (the audit's "no deal in ~40 fort-years"). A gift's or a seize's
-- line is never a deal.
function deal_made(talk_before, talk, moved, bought, sold)
    if WRONG_REPLIES[talk] then return false, nil end
    if moved then return true, 'goods' end
    if (bought or 0) > 0 or (sold or 0) > 0 then return true, 'owners' end
    if talk == 'Trade' and talk_before ~= 'Trade' then return true, 'answer' end
    return false, nil
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

-- (r2 h5) the trade screen's Trade label, by its word on the bottom rows,
-- nearest the October place (2 left of the centre, 2 above the bottom); never
-- one by a Seize or Offer
function find_trade_button()
    local ok, B = pcall(reqscript, 'ai-screen-buttons')
    if not (ok and type(B) == 'table' and B.find_label) then return nil, 'unavailable' end
    local gps = df.global.gps
    local okf, hits, how = pcall(B.find_label, 'Trade', {0, gps.dimy - 8, gps.dimx - 1, gps.dimy - 1},
                                 {gps.dimx // 2 - 2, gps.dimy - 2}, {forbid = true})
    if not okf then return nil, 'error' end
    return hits[1], how
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
    local x, y, how, refused, refused_why
    if b then x, y = button_at(b); how = b.default and 'guess' or 'shown' end
    if b and b.default and not (x >= 0 and y >= 0 and x < gps.dimx and y < gps.dimy) then
        b = nil      -- (r2 h5) off this screen: looked for by its word instead
    end
    -- (0.105.47 review) a guess pressed only where the screen reads "Trade";
    -- refused: nothing pressed, the ticks taken off and the screen closed
    -- (this caravan not tried again this visit)
    if b then
        local word_ok, why, verdict = guess_word_ok(name, b, x, y)
        if not word_ok and not ((verdict == 'missing' or verdict == 'unreadable') and name == 'Trade') then
            clear(trade)
            local c = close_screen()
            return {ok = false, rejected = true, guess_refused = verdict, error = why, closed = c.closed}
        end
        -- (r2 h5) no Trade at the guess (or only blanks there): looked for by its word
        if not word_ok then b, refused, refused_why = nil, verdict, why end
    end
    -- (r2 h5) no place known (or the guess retired, as in all six forts): the
    -- Trade label found on the screen's bottom rows, only where no Seize or
    -- Offer stands by it (judge); unreadable text: nothing pressed
    if not b then
        local spot, found = find_trade_button()
        if not spot then
            if found == 'unreadable' then UNREADABLE = true end
            return {ok = false, rejected = true, search = found, guess_refused = refused,
                    error = (refused_why and (refused_why .. '; ') or '') ..
                            'the AI doesn\'t know where the ' .. name .. ' button is yet (calibrate: probe_trade.py --here)' ..
                            (found == 'unreadable' and '; the screen\'s text can\'t be read to find it' or
                             found == 'none' and '; no Trade button found on the screen\'s bottom rows' or '')}
        end
        x, y, how = spot.x, spot.y, 'found'
    end
    -- DFHack's confirm tool asks "Are you sure you want to trade the selected
    -- goods?" on a click there (seen in game, 0.56.0): turned off for this one
    -- click only (in memory, its settings file untouched), then back on
    local fort_before = ticked_set(trade, FORT)
    local mer_owners, fort_owners = ticked_owners(trade, MERCHANT), ticked_owners(trade, FORT)
    local talk_before = df.talk_line_type[trade.talkline] or tostring(trade.talkline)
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
    local moved = after[3] < before[3] or after[4] < before[4]
    -- (item9) a counter-offer's extra goods weren't ticked before: only the
    -- first ticks are followed, which is enough to see goods change hands
    local bought_n, sold_n = owner_changes(mer_owners, fort_owners)
    local traded, traded_by = deal_made(talk_before, talk, moved, bought_n, sold_n)
    -- (0.105.47) a guessed button checked: only the Trade button makes the
    -- merchants answer (their talk line; in October they answered "Trade"
    -- with both lists unchanged). Goods gone with no answer is some other
    -- button (a seize or a gift): the guess retired at once. No answer and
    -- nothing moved: a miss (retired after two).
    -- (0.105.48, K9) the screen opens on Greet, so "any line but NONE" proved
    -- nothing (a seize answered too): worked only when the merchants answered
    -- a trade (TRADE_REPLIES) or a counter-offer came up; a gift's or a
    -- seize's line (or goods gone with no trade answer) retires the place at once
    local verdict = after_verdict(talk_before, talk, moved, counter ~= nil or trade.counter_offer == true)
    if how == 'guess' then
        if verdict == 'worked' then
            guess_result(name, b, true)
        elseif verdict == 'wrong' then
            guess_result(name, b, false, 'the merchants answered "' .. tostring(talk) .. '" (or goods moved with no ' ..
                         'trade answer): not the Trade button', true)
        else
            guess_result(name, b, false, 'pressed and the merchants said nothing')
        end
    end
    -- done: close the screen (the game goes on; nothing is ticked, so
    -- DFHack's "leave the screen?" question wouldn't come up anyway)
    local closed
    local heavy = WEIGHT_REPLIES[talk] == true and not traded
    if (traded or moved or talk ~= 'NONE') and not heavy then
        without_confirm('trade-cancel', function()
            require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
        end)
        closed = not trade.open
    end
    -- one try a caravan: haggling again and again ends the trading for good
    -- (a click that got no answer at all, e.g. a dialog in the way, isn't a refusal)
    -- (0.105.48, K9) the screen closed after the press: this caravan done for the
    -- visit (before, a miss on Greet closed it unmarked: open, press, close each cycle)
    if not heavy and (traded or moved or (talk ~= 'NONE' and talk ~= 'Greet' and talk ~= 'HarshGreet') or closed) then
        mark_done(trade.mer)
    end
    local wrong_line = WRONG_REPLIES[talk] == true
    return {ok = not wrong_line, pressed = name, at = {x, y}, answer = talk, answer_before = talk_before,
            traded = traded, traded_by = traded_by, moved = moved, too_heavy = heavy or nil,
            bought_now = bought_n, sold_now = sold_n, screen_now = focus, guessed = (how == 'guess') or nil, how = how, verdict = verdict,
            error = wrong_line and ('the merchants answered "' .. tostring(talk) .. '": not a trade') or nil,
            counter = counter, closed = closed,
            counter_offer = trade.counter_offer or nil,
            before = before, after = after}
end

-- (0.105.113 item10) after a Weight1/Weight2 answer (r: the deal's ticks,
-- p: the press): the deal ticked again with the fort's goods outweighing the
-- bought ones by at most WEIGHT_CUT of the last try (the goods most valuable
-- for their weight first), pressed again, up to WEIGHT_RETRIES times; still
-- too heavy, or nothing lighter to give: the screen closed, the caravan done.
-- Returns the last deal and press, with the tries.
function press_lighter(r, p, wants, margin, txt, extra)
    local tries = {}
    while p and p.too_heavy and #tries < WEIGHT_RETRIES do
        local net = (r.give_weight or 0) - (r.buy_weight or 0)
        local okh, fails = pcall(function() return trade_screen().mer.haggle_fail_count end)
        fails = okh and tonumber(fails) or 0
        table.insert(tries, {answer = p.answer, give_value = r.give_value, given = r.given,
                             give_weight = r.give_weight, buy_weight = r.buy_weight, haggle_fails = fails})
        -- nothing heavier on the fort's side, or the merchants' patience wearing thin
        if net <= 0 or fails >= WEIGHT_HAGGLE_MAX then break end
        clear(trade_screen())
        local r2 = deal(wants, margin, false, txt, extra, net * (WEIGHT_CUT[p.answer] or 0.5))
        if not r2.ok or r2.rejected or r2.waiting then
            tries[#tries].next_error = r2.error
            break
        end
        r = r2
        p = press('Trade', txt)
    end
    if p and p.too_heavy then
        local c = close_screen()          -- marks the caravan done
        p.closed = c.closed
    end
    if #tries > 0 then r.weight_tries = tries end
    return r, p
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

-- (r9, audit A8 #24) kept in the save too (the newest DONE_KEEP): DONE alone
-- lived in memory, so after a DFHack restart the AI haggled again with the
-- caravan it had already traded with (or been turned down by)
DONE_KEY, DONE_KEEP = 'ai-overseer/trade-done', 8
function mark_done(c)
    local k = caravan_key(c)
    if not k then return end
    DONE[k] = true
    pcall(function()
        local list = {}
        for _, x in ipairs(U.site_get(DONE_KEY, {})) do
            if type(x) == 'string' and x ~= k then table.insert(list, x) end
        end
        table.insert(list, k)
        while #list > DONE_KEEP do table.remove(list, 1) end
        U.site_put(DONE_KEY, list)
    end)
end
function is_done(c)
    local k = caravan_key(c)
    if k == nil then return false end
    if DONE[k] == true then return true end
    local ok, list = pcall(U.site_get, DONE_KEY, {})
    for _, x in ipairs(ok and type(list) == 'table' and list or {}) do
        if x == k then DONE[k] = true; return true end
    end
    return false
end

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
GUESS_CHECK_FRAMES = 30     -- (0.105.47) a guessed Depot button judged this many frames after its click
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

-- (r2 h5) The depot sheet's Trade button found by its word where no place is
-- known or the guess misses (DF 53.17's sheet: the October place opened no
-- trade screen in the 14-15 Nov run, and one retired guess shut trading off
-- for every later caravan in that DF folder). A few tries a caravan visit,
-- half a day apart; text that can't be read stops the search (nothing is
-- clicked blind) and the Needs you comes back.
OPEN_TRIES_PER_VISIT = 3
OPEN_RETRY_TICKS = 600
SEARCH_NOT_BEFORE = {depot = true, goods = true, agreement = true, agreements = true}
TRIES = TRIES or {}
UNREADABLE = UNREADABLE or nil

local function screen_buttons()
    local ok, B = pcall(reqscript, 'ai-screen-buttons')
    return ok and type(B) == 'table' and B.find_label and B or nil
end

-- the caravan at the depot the AI hasn't traded with this visit, or nil
local function fresh_caravan()
    for _, c in ipairs(df.global.plotinfo.caravans) do
        if c.trade_state == df.caravan_state.T_trade_state.AtDepot and not is_done(c) then return c end
    end
end

-- Pure: may the AI still try to open the screen for this visit (a place
-- known, or the search not used up and the text readable)?
function may_open(has_place, tries, unreadable)
    if has_place then return true end
    return not unreadable and (tries or 0) < OPEN_TRIES_PER_VISIT
end

function can_open_now()
    local c = fresh_caravan()
    local k = c and caravan_key(c)
    return may_open(buttons().Depot ~= nil, k and TRIES[k] or 0, UNREADABLE == true)
end

-- the depot sheet's Trade label, nearest the October place: {x, y} or nil, and how
function find_depot_trade()
    local B = screen_buttons()
    if not B then return nil, 'unavailable' end
    local gps = df.global.gps
    local ok, hits, how, rows = pcall(B.find_label, 'Trade',
                                      {math.max(gps.dimx // 3, gps.dimx - 110), 1, gps.dimx - 1, gps.dimy - 2},
                                      {gps.dimx - 76, 15}, {not_before = SEARCH_NOT_BEFORE})
    if not ok then return nil, 'error' end
    return hits[1], how, rows, #hits
end

-- a failed try this visit: counted, the next one half a day on
local function failed_try(key, why)
    if key then TRIES[key] = (TRIES[key] or 0) + 1 end
    OPEN_AFTER = trade_now() + OPEN_RETRY_TICKS
    if LAST_OPEN then LAST_OPEN.tries = key and TRIES[key] or nil end
end

local function close_sheet()
    pcall(function()
        local vs = df.global.game.main_interface.view_sheets
        vs.open = false
        vs.active_sheet = df.view_sheet_type.NONE
        vs.active_id = -1
    end)
end

-- a few rows of the sheet's text where the button should be (for the report)
local function sheet_sample(rows)
    if type(rows) ~= 'table' then return nil end
    local out = {}
    for i = 1, math.min(#rows, 24) do
        local r = rows[i]:gsub('%s+$', '')
        if r:find('%S') then table.insert(out, r:sub(-70)) end      -- the sheet sits on the right
        if #out >= 12 then break end
    end
    return out
end

function open_screen(dry_run, txt)
    local trade = trade_screen()
    if trade.open then return {ok = true, open = true, note = 'already open'} end
    local fc = fresh_caravan()
    if not fc then return {ok = true, waiting = true, error = 'the AI has already traded with the caravan(s) at the depot'} end
    local key = caravan_key(fc)
    local dep = depot()
    if not dep then return {ok = false, rejected = true, error = 'no trade depot built yet'} end
    local job = trade_job(dep)
    local w = job and dfhack.job.getWorker(job)
    if not at_depot(w, dep) then return {ok = true, waiting = true, error = 'nobody is at the depot to trade yet'} end
    if OPEN_AFTER and trade_now() < OPEN_AFTER then
        return {ok = true, waiting = true, error = 'the screen was opened while the merchants unloaded, or the last try missed: waiting a while'}
    end
    local still, why = unloading(dep)
    if still then return {ok = true, waiting = true, error = why} end
    local b = buttons().Depot
    if b and b.default then
        -- (0.105.47) a guess only where it lands on this screen
        local gps = df.global.gps
        local gx, gy = button_at(b)
        if not (gx >= 0 and gy >= 0 and gx < gps.dimx and gy < gps.dimy) then b = nil end
    end
    -- (r2 h5) no place known: the button looked for by its word on the sheet,
    -- a few tries a visit (before: refused, a Needs you, every caravan)
    if not b and not may_open(false, TRIES[key], UNREADABLE == true) then
        return {ok = false, rejected = true, tries = TRIES[key], last = LAST_OPEN,
                error = 'the AI doesn\'t know where the depot\'s Trade button is yet' ..
                        (UNREADABLE and ' and can\'t read the screen\'s text to find it' or
                         ' and didn\'t find it on the depot\'s sheet') .. ' (probe_trade.py --here-depot)'}
    end
    local okf, plain = pcall(function()
        return dfhack.gui.matchFocusString('dwarfmode/Default') or dfhack.gui.matchFocusString('dwarfmode/ViewSheets')
    end)
    if okf and not plain then return {ok = true, waiting = true, error = 'the player has a menu open'} end
    local vs = df.global.game.main_interface.view_sheets
    -- (r9, audit A8 #17) a sheet the player is reading (a dwarf's, another
    -- building's) is never taken over for the depot's: only the plain map,
    -- or the depot's own sheet already up
    local oks, reading = pcall(function()
        return dfhack.gui.matchFocusString('dwarfmode/ViewSheets') and vs.open
            and not (vs.active_sheet == df.view_sheet_type.BUILDING and vs.active_id == dep.id)
    end)
    if oks and reading then return {ok = true, waiting = true, error = 'the player is reading a sheet'} end
    if dry_run then return {ok = true, dry_run = true, at = b and {button_at(b)} or nil, search = not b or nil} end
    vs.open = true
    pcall(function() vs.context = df.view_sheets_context_type.REGULAR_PLAY end)
    vs.active_sheet = df.view_sheet_type.BUILDING
    vs.active_id = dep.id
    vs.viewing_bldid = dep.id
    pcall(function() vs.active_sub_tab = 0 end)
    -- the game lays the sheet out when it draws it: the click a few frames
    -- later (dfhack.timeout counts frames even while paused); the result is
    -- seen on the next cycle (the trade report's screen.open)
    local x, y
    if b then x, y = button_at(b) end
    OPEN_CLICKED_AT, OPENED_FOR = os.time(), nil
    dfhack.timeout(3, 'frames', function()
        -- (0.105.47 review) a guess clicked only where the sheet reads "Trade"
        -- (0.105.48, K3) the AI halted since the sheet opened: no click, the sheet shut
        local okh, halted = pcall(function() return reqscript('ai-status').is_halted() end)
        if okh and halted == true then
            close_sheet()
            LAST_OPEN = {clicked = false, halted = true, error = 'the AI was halted in the game'}
            return
        end
        -- (r9, A8 #17) the focus looked at again before the click: a menu the
        -- player opened meanwhile, or another sheet over the depot's: no click
        local okf2, still_ok = pcall(function()
            local mi = df.global.game.main_interface.view_sheets
            return (dfhack.gui.matchFocusString('dwarfmode/Default') or dfhack.gui.matchFocusString('dwarfmode/ViewSheets'))
                and mi.active_id == dep.id
        end)
        if okf2 and not still_ok then
            LAST_OPEN = {clicked = false, error = 'the screen changed before the click (the player): not clicked'}
            return
        end
        local how = b and (b.default and 'guess' or 'shown') or nil
        local refused
        if b then
            local word_ok, wwhy, verdict = guess_word_ok('Depot', b, x, y)
            if not word_ok then
                if verdict == 'missing' or verdict == 'unreadable' then
                    -- (r2 h5) the sheet reads no Trade at the guess (or only blanks
                    -- there): looked for by its word instead (the search itself
                    -- clicks nothing where the text can't be read)
                    b, how, refused = nil, nil, verdict
                else
                    close_sheet()
                    LAST_OPEN = {clicked = false, guessed = b.default or nil, guess_refused = verdict, error = wwhy}
                    return
                end
            end
        end
        local sample
        if not b then
            local spot, found, rows, n = find_depot_trade()
            sample = sheet_sample(rows)
            if not spot then
                close_sheet()
                if found == 'unreadable' then UNREADABLE = true end
                LAST_OPEN = {clicked = false, search = found, sheet = sample, guess_refused = refused,
                             error = found == 'unreadable' and 'the depot sheet\'s text can\'t be read: not clicked blind'
                                     or found == 'blank' and 'the depot\'s sheet showed no text yet'
                                     or 'no Trade button found on the depot\'s sheet'}
                failed_try(key)
                return
            end
            x, y, how = spot.x, spot.y, 'found'
            if n and n > 1 then how = 'found (nearest of ' .. n .. ')' end
        end
        local okc, err = pcall(click, x, y)
        LAST_OPEN = {clicked = okc, error = not okc and tostring(err) or nil, opened = trade.open,
                     guessed = (how == 'guess') or nil, how = how, at = {x, y}, sheet = sample}
        if trade.open then
            OPENED_FOR = caravan_key(trade.mer)
            close_sheet()
            if how == 'guess' then guess_result('Depot', b, true) end
        else
            -- the screen may come up a slow frame later (opened_by_ai's 0.100
            -- note), so it is judged GUESS_CHECK_FRAMES on. Missed: whatever it
            -- opened instead is left (the depot's goods screen), the sheet
            -- closed, a guess counted, a found place's try counted for the visit.
            dfhack.timeout(GUESS_CHECK_FRAMES, 'frames', function()
                if trade.open then
                    if how == 'guess' then guess_result('Depot', b, true) end
                    if LAST_OPEN then LAST_OPEN.opened = true end
                    return
                end
                pcall(function()
                    if df.global.game.main_interface.assign_trade.open then
                        require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
                    end
                end)
                close_sheet()
                if how == 'guess' then guess_result('Depot', b, false, 'clicked and the trade screen did not open') end
                -- (r9, A8 #17) a shown place that missed waits half a day too
                -- (OPEN_AFTER), not counted against the visit's tries: before,
                -- open, tick, press, close came round every cycle
                if how ~= 'shown' then failed_try(key) else failed_try(nil) end
                if LAST_OPEN then LAST_OPEN.guess_missed = (how == 'guess') or nil; LAST_OPEN.missed = true end
            end)
        end
    end)
    return {ok = true, clicking = true, at = b and {x, y} or nil, guessed = (b and b.default) or nil,
            search = not b or nil}
end

