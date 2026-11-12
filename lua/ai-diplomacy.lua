-- (0.105.0, phases 12b and 13b) The world outside the fort: the civilisations
-- it knows, at war or at peace, who has besieged it, the tribute asked or
-- offered, what the caravans' trade agreements ask the fort to make, and the
-- meetings with diplomats and the outpost liaison answered so an unattended
-- run never stalls on one.
--
-- What is known (df-structures master and DFHack's own scripts, 53.16):
--   * DF's meeting screen is game.main_interface.diplomacy (DFHack's focus
--     string dwarfmode/Diplomacy/Default, /Requests while the fort picks what
--     the liaison's people should bring, /ElevateLandHolder for a barony);
--     its dipev is the meeting (civ, topics, the requests);
--   * on the Requests screen DFHack's own tradeagreement overlay ticks a
--     wish by setting dipev.sell_requests.priority[category][i] (0 none, 4
--     the most); DF keeps the choice only after its "Done" button;
--   * a caravan's trade agreement is caravan.buy_prices (items.item_type,
--     items.item_subtype, price; 128 = the usual price), as DFHack's trade
--     screen reads it for "requested items";
--   * the fort's civ's diplomacy states (relation: Peace, TotalWar,
--     NoContact, AcceptingTribute, OfferingTribute, Skirmishing) and the
--     sieges (plotinfo.invasions.list: civ_id, flags.siege, created_year).
-- NOT known without seeing it in game: where the meeting screen's answer
-- buttons are, which topic is being asked right now, and how much a tribute
-- is. So the screen is answered only through buttons the player showed the
-- AI once (meeting_here Yes|No|Done, as the trade screen's Trade button),
-- every read is inside pcall, and each open meeting screen is written to
-- dfhack-config/ai-overseer/meeting-probe.json for the next round. When an
-- answer can't be given, nothing is pressed: today's Needs-you note stands
-- and the overseer leaves the screen after 10 minutes, as before.
--@ module = true

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

PROBE_FILE = dfhack.getDFPath() .. '/dfhack-config/ai-overseer/meeting-probe.json'
PROBE_KEEP = 12                       -- the last samples kept in the probe file
BUTTONS_KEY = 'ai-overseer/meeting-buttons'
BUTTON_NAMES = {Yes = true, No = true, Done = true}
MAX_CIVS, MAX_WANTED, MAX_UNKNOWN = 24, 12, 16
HOSTILE = {TotalWar = true, Skirmishing = true}

-- (0.105.0) What the AI answers to each topic of a meeting, by DF's own topic
-- names (df.meeting_topic). 'yes', 'no', 'requests' (the Requests screen:
-- tick the fort's wishes, then Done), 'tribute' (the Rules choice), nil:
-- left to the player (a barony's holder is the player's to choose).
TOPIC_ANSWERS = {
    DiscussCurrent = 'yes', PleasantPlace = 'yes', WorldStatus = 'yes',
    TreeQuota = 'yes',                      -- agree to the elves' quota (the planner keeps it)
    RequestPeace = 'yes', InducePeace = 'yes', SeekAlliance = 'yes',
    OpenTrade = 'yes', ImproveTrade = 'yes',
    ExportAgreement = 'requests', ImportAgreement = 'requests',
    TributeAgreement = 'tribute',
    DemandSurrender = 'no', DeclareWar = 'no', InduceWar = 'no',
    BecomeLandHolder = nil, PromoteLandHolder = nil,
}

-- (0.105.0) The fort's wishes on the Requests screen when the planner gives
-- none: what a fort runs short of and seldom makes (DF's entity_sell_category).
DEFAULT_WISHES = {'MetalBars', 'Leather', 'ClothPlant', 'ThreadPlant', 'Wood', 'Seeds', 'Anvils', 'Meat',
                  'Cheese', 'Drinks'}
WISH_PRIORITY = 2                     -- of DF's 0-4 (DFHack's overlay uses 4 for "all")

local function translate(name, english)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, english) end)
    if ok and s then return s end
    ok, s = pcall(function() return dfhack.TranslateName(name, english) end)
    return ok and s or '?'
end

-- A reader that remembers the fields it couldn't read (ai-missions' pattern).
local function new_reader()
    local seen, list = {}, {}
    local R = {list = list}
    function R.note(label)
        if label and not seen[label] and #list < MAX_UNKNOWN then
            seen[label] = true
            table.insert(list, label)
        end
    end
    function R.rd(label, fn)
        local ok, v = pcall(fn)
        if ok then return v end
        R.note(label)
        return nil
    end
    return R
end

local function enum_name(enum, v)
    if v == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return tonumber(v) and tostring(v) or nil
end

local function each(v)
    local out = {}
    if v == nil then return out end
    local ok = pcall(function() for _, x in ipairs(v) do table.insert(out, x) end end)
    if not ok then out = {} end
    return out
end

-- ---------------------------------------------------------------------------
-- Pure parts (tested without the game)

-- Pure: the topic being asked now, a guess: the first of the meeting's topics
-- not yet concluded (dipev.agreement_topic lists the concluded ones).
function current_topic(topics, concluded)
    local done = {}
    for _, t in ipairs(concluded or {}) do done[t] = (done[t] or 0) + 1 end
    for _, t in ipairs(topics or {}) do
        if (done[t] or 0) > 0 then done[t] = done[t] - 1 else return t end
    end
    return nil
end

-- (0.105.0 review) Pure: the topics not yet concluded, in order.
function pending_topics(topics, concluded)
    local done, out = {}, {}
    for _, t in ipairs(concluded or {}) do done[t] = (done[t] or 0) + 1 end
    for _, t in ipairs(topics or {}) do
        if (done[t] or 0) > 0 then done[t] = done[t] - 1 else table.insert(out, t) end
    end
    return out
end

-- (0.105.0 review) Pure: why the AI must not press anything (nil: it may).
-- The screen may show any unconcluded topic, so only when exactly one is
-- left is the topic known; and never on war or surrender, whatever the
-- guess. (0.105.33 review) Tribute is pressed when the Rules say pay or
-- refuse (No is always safe), or 'small' with the amount asked known
-- (tribute_known); before, only 'pay' ever got past here, so decide()'s
-- refuse and small answers never ran and the meeting waited for a person.
NEVER_PRESSED = {DemandSurrender = true, DeclareWar = true, InduceWar = true}
function press_guard(pending, policy, tribute_known)
    for _, t in ipairs(pending or {}) do
        if NEVER_PRESSED[t] then return t .. ' is on the table: left to you' end
        if t == 'TributeAgreement' and not (policy == 'pay' or policy == 'refuse'
                or (policy == 'small' and tribute_known)) then
            return policy == 'small' and 'a tribute is on the table and how much is asked is not known: left to you'
                or 'a tribute is on the table: left to you'
        end
    end
    local n = #(pending or {})
    if n ~= 1 then
        return n == 0 and 'which topic is asked is not known: left to you'
            or (('%d topics are open and the screen may show any of them: left to you'):format(n))
    end
    return nil
end

-- Pure: the answer to a topic. policy: the Rules choice for tribute ('small':
-- pay a small one, refuse a large one; 'pay'; 'refuse'). ctx: {amount =
-- the tribute asked if known, wealth = the fort's created wealth,
-- small_share = the share of the wealth still "small"}. Returns answer, why
-- (answer nil: left to the player).
function decide(topic, policy, ctx)
    ctx = ctx or {}
    if topic == nil then return nil, 'no topic is known' end
    local a = TOPIC_ANSWERS[topic]
    if a == 'tribute' then
        if policy == 'pay' then return 'yes', 'the Rules: pay tribute' end
        if policy == 'refuse' then return 'no', 'the Rules: refuse tribute' end
        local amount, wealth = tonumber(ctx.amount), tonumber(ctx.wealth)
        if not amount or not wealth or amount < 0 then
            return nil, 'how much tribute is asked is not known: left to you'
        end
        local limit = math.floor(wealth * (tonumber(ctx.small_share) or 0.05))
        if amount <= limit then return 'yes', ('a small tribute (%d of the fort\'s %d): pay'):format(amount, wealth) end
        return 'no', ('a large tribute (%d, over %d): refuse'):format(amount, limit)
    end
    if a == nil then return nil, (topic .. ' is left to you') end
    return a, (topic .. ': ' .. a)
end

-- Pure: the Requests screen's wishes ticked. tabs: {category name, ...} in
-- the screen's order; prios: {[tab index] = {priority, ...}}; wishes: the
-- category names wanted. Sets WISH_PRIORITY on every item of a wanted tab
-- that has none yet; returns how many were set.
function tick_wishes(tabs, prios, wishes, prio)
    local want = {}
    for _, w in ipairs(wishes or {}) do want[w] = true end
    local n = 0
    for i, name in ipairs(tabs) do
        local list = prios[i]
        if want[name] and list then
            for k = 1, #list do
                if (list[k] or 0) == 0 then list[k] = prio or WISH_PRIORITY; n = n + 1 end
            end
        end
    end
    return n
end

-- Pure: a percent from DF's price (128 = the usual price).
function price_pct(price)
    local p = tonumber(price)
    if not p then return nil end
    return (p * 100) // 128
end

-- ---------------------------------------------------------------------------
-- The world: civs, war and peace, sieges, tribute, the caravans' agreements

local function civ_name(ent)
    if not ent then return '?' end
    return translate(ent.name, true)
end

local function race_of(ent)
    local ok, id = pcall(function()
        local cr = df.creature_raw.find(ent.race)
        return cr and cr.creature_id or nil
    end)
    return ok and id or nil
end

local function item_word(t, st)
    local tn = enum_name(df.item_type, t) or tostring(t)
    local ok, def = pcall(function() return dfhack.items.getSubtypeDef(t, st) end)
    if ok and def then
        local okn, n = pcall(function() return def.name end)
        if okn and n then return tn, n end
    end
    return tn, nil
end

-- A trade agreement (entity_buy_prices): {{item, subtype, name, pct}}, the
-- best-paid first.
local function agreement_items(R, bp)
    local out = {}
    if bp == nil then return out end
    local types = R.rd('buy_prices.items.item_type', function() return bp.items.item_type end)
    local subs = R.rd('buy_prices.items.item_subtype', function() return bp.items.item_subtype end)
    local prices = R.rd('buy_prices.price', function() return bp.price end)
    if not types or not prices then return out end
    local n = R.rd('buy_prices size', function() return #types end) or 0
    for i = 0, n - 1 do
        local t = R.rd('buy_prices.items.item_type[]', function() return types[i] end)
        local st = subs and R.rd('buy_prices.items.item_subtype[]', function() return subs[i] end) or -1
        local pr = R.rd('buy_prices.price[]', function() return prices[i] end)
        if t ~= nil then
            local tn, name = item_word(t, st)
            table.insert(out, {item = tn, name = name, pct = price_pct(pr)})
        end
    end
    table.sort(out, function(a, b) return (a.pct or 0) > (b.pct or 0) end)
    return out
end

function world_report(txt)
    txt = txt or tostring
    local R = new_reader()
    local out = {civs = {}, sieges = {}, caravans = {}, wanted = {}}
    local civ_id = R.rd('plotinfo.civ_id', function() return df.global.plotinfo.civ_id end)
    local civ = civ_id and R.rd('historical_entity.find', function() return df.historical_entity.find(civ_id) end)
    local rel = {}
    -- the civilisations the fort's civ knows, and how it stands with each
    local states = civ and R.rd('entity.relations.diplomacy.state', function() return civ.relations.diplomacy.state end)
    for _, st in ipairs(each(states)) do
        local gid = R.rd('diplomacy_state.group_id', function() return st.group_id end)
        local ent = gid and R.rd('historical_entity.find', function() return df.historical_entity.find(gid) end)
        local is_civ = ent and R.rd('historical_entity.type',
            function() return df.historical_entity_type[ent.type] == 'Civilization' end)
        if ent and is_civ and gid ~= civ_id then
            local r = enum_name(df.diplomacy_state_type, R.rd('diplomacy_state.relation', function() return st.relation end))
            rel[gid] = r
            if #out.civs < MAX_CIVS then
                local e = {id = gid, name = txt(civ_name(ent)), race = race_of(ent), relation = r or 'unknown',
                           hostile = HOSTILE[r] or nil}
                pcall(function() if st.flags.peace_offering_received then e.peace_offered = true end end)
                pcall(function() if st.flags.allies then e.allies = true end end)
                if r == 'AcceptingTribute' or r == 'OfferingTribute' then
                    e.tribute = r == 'AcceptingTribute' and 'they take' or 'they give'   -- a guess at the direction
                    pcall(function() e.tribute_season = enum_name(df.season, st.tribute_season) end)
                end
                table.insert(out.civs, e)
            end
        end
    end
    -- who has besieged the fort (DF keeps every invasion of this site)
    local per = {}
    local inv = R.rd('plotinfo.invasions.list', function() return df.global.plotinfo.invasions.list end)
    for _, v in ipairs(each(inv)) do
        local cid = R.rd('invasion.civ_id', function() return v.civ_id end)
        if cid and cid >= 0 then
            local e = per[cid] or {id = cid, n = 0}
            e.n = e.n + 1
            local y = R.rd('invasion.created_year', function() return v.created_year end)
            if y and (e.last_year == nil or y > e.last_year) then e.last_year = y end
            pcall(function() if v.flags.active then e.active = true end end)
            per[cid] = e
        end
    end
    for cid, e in pairs(per) do
        local ent = df.historical_entity.find(cid)
        e.name = ent and txt(civ_name(ent)) or nil
        e.race = ent and race_of(ent) or nil
        e.relation = rel[cid]
        table.insert(out.sieges, e)
    end
    table.sort(out.sieges, function(a, b) return a.n > b.n or (a.n == b.n and a.id < b.id) end)
    -- the caravans: whose, hostile or not, tribute, and their trade agreement
    local cars = R.rd('plotinfo.caravans', function() return df.global.plotinfo.caravans end)
    for _, c in ipairs(each(cars)) do
        local ok, e = pcall(function()
            if c.time_remaining <= 0 then return nil end
            local ent = df.historical_entity.find(c.entity)
            local r = rel[c.entity]
            return {civ_id = c.entity, civ = ent and txt(civ_name(ent)) or '?', race = ent and race_of(ent) or nil,
                    relation = r, hostile = HOSTILE[r] or nil,
                    state = enum_name(df.caravan_state.T_trade_state, c.trade_state),
                    tribute = c.flags.tribute or nil}
        end)
        if not ok then R.note('caravan fields')
        elseif e then
            local bp = R.rd('caravan.buy_prices', function() return c.buy_prices end)
            local wanted = agreement_items(R, bp)
            if #wanted > 0 then
                e.wanted = #wanted
                for i = 1, math.min(MAX_WANTED, #wanted) do
                    local w = wanted[i]
                    w.civ = e.civ
                    table.insert(out.wanted, w)
                end
            end
            table.insert(out.caravans, e)
        end
    end
    -- visitors on the map from a civ at war with the fort: left alone unless
    -- hostile on the map (ai-military's kill_target_ok decides)
    local hostile_civs = {}
    for id, r in pairs(rel) do if HOSTILE[r] then hostile_civs[id] = true end end
    if next(hostile_civs) then
        local n = 0
        pcall(function()
            for _, u in ipairs(report_units()) do
                local okv, v = pcall(function()
                    return hostile_civs[u.civ_id] and not dfhack.units.isDead(u)
                        and not dfhack.units.isDanger(u) and not dfhack.units.isInvader(u)
                end)
                if okv and v then n = n + 1 end
            end
        end)
        if n > 0 then out.visitors_from_hostile = n end
    end
    pcall(function() out.wealth = df.global.plotinfo.tasks.wealth.total end)
    out.meeting = meeting_state(R, txt)
    if #out.civs == 0 then out.civs = nil end
    if #out.sieges == 0 then out.sieges = nil end
    if #out.caravans == 0 then out.caravans = nil end
    if #out.wanted == 0 then out.wanted = nil end
    out.unknown = (#R.list > 0) and R.list or nil
    return out
end

-- ---------------------------------------------------------------------------
-- The meeting screen

local function ui()
    return df.global.game.main_interface.diplomacy
end

local function focus()
    local ok, f = pcall(function() return dfhack.gui.getCurFocus(true)[1] end)
    return ok and tostring(f or '') or ''
end

-- The meeting the screen shows (its dipev), or the first under way.
local function meeting_of(R, d)
    local ev = d and R.rd('diplomacy.dipev', function() return d.dipev end)
    if ev then return ev end
    return R.rd('plotinfo.dip_meeting_info', function() return df.global.plotinfo.dip_meeting_info[0] end)
end

local function topics_of(R, ev)
    local topics, concluded = {}, {}
    if not ev then return topics, concluded end
    for _, t in ipairs(each(R.rd('dipev.topic_list', function() return ev.topic_list end))) do
        table.insert(topics, enum_name(df.meeting_topic, t))
    end
    for _, t in ipairs(each(R.rd('dipev.agreement_topic', function() return ev.agreement_topic end))) do
        table.insert(concluded, enum_name(df.meeting_topic, t))
    end
    return topics, concluded
end

-- The tribute asked, a guess: the topic's parameter (dipev.topic_parms at the
-- tribute topic's place). Reported as a guess; nil when not a number.
local function tribute_amount(R, ev, topics)
    if not ev then return nil end
    for i, t in ipairs(topics) do
        if t == 'TributeAgreement' then
            local v = R.rd('dipev.topic_parms', function() return ev.topic_parms[i - 1] end)
            return tonumber(v)
        end
    end
    return nil
end

-- What the report says of the meeting screen (small): open, which part,
-- the civ, the topics, the one asked now (a guess).
function meeting_state(R, txt)
    R = R or new_reader()
    local okd, d = pcall(ui)
    local open = okd and R.rd('diplomacy.open', function() return d.open end) == true
    local f = focus()
    local low = f:lower()
    if not open and not low:find('diplomacy', 1, true) and not low:find('meeting', 1, true) then return nil end
    local out = {open = true, screen = f}
    if okd then
        out.requests = R.rd('diplomacy.taking_requests', function() return d.taking_requests end) or nil
        out.land_holder = R.rd('diplomacy.selecting_land_holder_position',
            function() return d.selecting_land_holder_position end) or nil
    end
    local ev = meeting_of(R, okd and d or nil)
    if ev then
        local cid = R.rd('dipev.civ_id', function() return ev.civ_id end)
        local ent = cid and df.historical_entity.find(cid)
        out.civ_id, out.civ, out.race = cid, ent and (txt or tostring)(civ_name(ent)) or nil, ent and race_of(ent) or nil
        local topics, concluded = topics_of(R, ev)
        out.topics, out.concluded = topics, (#concluded > 0) and concluded or nil
        out.topic = current_topic(topics, concluded)
        out.tribute_asked = tribute_amount(R, ev, topics)
        pcall(function() out.script = ev.dipscript.code end)
        pcall(function() out.done = (ev.flags.success or ev.flags.failure) or nil end)
    end
    out.buttons = {}
    for name in pairs(buttons()) do table.insert(out.buttons, name) end
    table.sort(out.buttons)
    if #out.buttons == 0 then out.buttons = nil end
    return out
end

-- A probe value, one level: numbers, strings, booleans as they are; vectors
-- as their size and first values; anything else its type.
local function plain(v)
    local t = type(v)
    if t == 'number' or t == 'string' or t == 'boolean' then return v end
    if t == 'userdata' then
        local okn, n = pcall(function() return #v end)
        if okn and type(n) == 'number' then
            local first = {}
            for i = 0, math.min(n, 6) - 1 do
                local oke, e = pcall(function() return v[i] end)
                local te = oke and type(e)
                if te == 'number' or te == 'string' or te == 'boolean' then table.insert(first, e) end
            end
            return {n = n, first = (#first > 0) and first or nil}
        end
        local oks, s = pcall(tostring, v)
        return oks and s:sub(1, 60) or '?'
    end
    return nil
end

local function fields_of(obj, max)
    local out, n = {}, 0
    if obj == nil then return nil end
    pcall(function()
        for k, v in pairs(obj) do
            if n >= (max or 80) then break end
            local okv, pv = pcall(plain, v)
            if okv and pv ~= nil then out[tostring(k)] = pv; n = n + 1 end
        end
    end)
    return out
end

-- (0.105.0) Everything the meeting screen holds now: the interface, its
-- meeting (dipev), the popup (mm), the text box, the requests' tabs, the
-- focus, the mouse. Read only.
function probe(txt)
    local R = new_reader()
    local out = {focus = focus()}
    pcall(function() out.date = {year = df.global.cur_year, tick = df.global.cur_year_tick} end)
    pcall(function() out.mouse = {x = df.global.gps.mouse_x, y = df.global.gps.mouse_y,
                                   w = df.global.gps.dimx, h = df.global.gps.dimy} end)
    local okd, d = pcall(ui)
    if okd and d then
        out.ui = fields_of(d, 80)
        out.dipev = fields_of(R.rd('diplomacy.dipev', function() return d.dipev end), 60)
        out.mm = fields_of(R.rd('diplomacy.mm', function() return d.mm end), 40)
        out.text = fields_of(R.rd('diplomacy.text', function() return d.text end), 40)
        out.environment = fields_of(R.rd('diplomacy.environment', function() return d.environment end), 20)
        pcall(function()
            local tabs = {}
            for _, c in ipairs(d.taking_requests_tablist) do
                local prios = d.environment.dipev.sell_requests.priority[c]
                table.insert(tabs, {cat = enum_name(df.entity_sell_category, c), items = #prios})
            end
            out.request_tabs = tabs
        end)
    end
    out.state = meeting_state(R, txt)
    pcall(function() out.popups = #df.global.plotinfo.dipscript_popups end)
    out.unknown = (#R.list > 0) and R.list or nil
    return out
end

-- The probe written to meeting-probe.json, the last PROBE_KEEP samples.
function save_probe(sample)
    pcall(function()
        local json = require('json')
        local data = {}
        local okr, old = pcall(json.decode_file, PROBE_FILE)
        if okr and type(old) == 'table' and type(old.samples) == 'table' then data = old.samples end
        table.insert(data, sample)
        while #data > PROBE_KEEP do table.remove(data, 1) end
        dfhack.filesystem.mkdir_recursive(dfhack.getDFPath() .. '/dfhack-config/ai-overseer')
        json.encode_file({samples = data}, PROBE_FILE)
    end)
end

-- ---------------------------------------------------------------------------
-- The answer buttons, shown to the AI once (as the trade screen's)

function buttons()
    return U.site_get(BUTTONS_KEY, {})
end

-- Remember where a button is: the mouse is on it now. Kept from the
-- screen's centre, so a resized window still finds a centred dialog's.
function calibrate(name)
    if not BUTTON_NAMES[name] then return {ok = false, error = 'buttons: Yes, No, Done'} end
    local gps = df.global.gps
    local x, y = gps.mouse_x, gps.mouse_y
    if x < 0 or y < 0 then return {ok = false, error = 'the game doesn\'t know where the mouse is: put it on the button in DF'} end
    if not meeting_state(nil) then
        return {ok = false, error = 'open a meeting first (a diplomat or the liaison), then put the mouse on its ' .. name .. ' button'}
    end
    local d = buttons()
    d[name] = {dx = x - gps.dimx // 2, dy = y - gps.dimy // 2, x = x, y = y, w = gps.dimx, h = gps.dimy}
    dfhack.persistent.saveSiteData(BUTTONS_KEY, d)
    save_probe({calibrated = name, at = {x = x, y = y}, sample = probe(dfhack.df2utf)})
    return {ok = true, button = name, x = x, y = y, screen = {gps.dimx, gps.dimy}}
end

local function click(b)
    local gps = df.global.gps
    local x, y = gps.dimx // 2 + b.dx, gps.dimy // 2 + b.dy
    local ox, oy = gps.mouse_x, gps.mouse_y
    gps.mouse_x, gps.mouse_y = x, y
    pcall(function()
        gps.precise_mouse_x = x * gps.tile_pixel_x + gps.tile_pixel_x // 2
        gps.precise_mouse_y = y * gps.tile_pixel_y + gps.tile_pixel_y // 2
    end)
    require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), '_MOUSE_L')
    gps.mouse_x, gps.mouse_y = ox, oy
    return x, y
end

-- A fingerprint of the screen: changes when an answer was taken.
local function fingerprint()
    local R = new_reader()
    local st = meeting_state(R) or {}
    local parts = {tostring(st.open), tostring(st.screen), tostring(st.requests), tostring(st.topic),
                   tostring(st.concluded and #st.concluded or 0), tostring(st.done)}
    pcall(function() table.insert(parts, tostring(ui().environment.dipev.cur_step)) end)
    pcall(function() table.insert(parts, tostring(#ui().text.word)) end)
    return table.concat(parts, '|')
end

-- ---------------------------------------------------------------------------
-- (0.105.0) Answer the meeting screen with the AI's defaults.
--   a.tribute: 'small' | 'pay' | 'refuse' (default: the Rules tab's)
--   a.wishes: entity_sell_category names to tick on the Requests screen
--   a.dry_run: decide and report, press nothing
-- Returns {ok, answer, why, topic, pressed, ...}; ok false with
-- needs_button when the button to press hasn't been shown to the AI.
function answer_meeting(a, txt)
    a = a or {}
    local R = new_reader()
    local st = meeting_state(R, txt)
    if not st then return {ok = false, rejected = true, error = 'no meeting screen is open'} end
    local sample = probe(txt)
    save_probe(sample)
    local policy = a.tribute
    if policy == nil then
        pcall(function() policy = reqscript('ai-overseer-settings').load_settings().tribute end)
    end
    if policy ~= 'pay' and policy ~= 'refuse' then policy = 'small' end
    local out = {topic = st.topic, topics = st.topics, civ = st.civ, screen = st.screen, policy = policy,
                 dry_run = a.dry_run or nil}
    local btn = buttons()
    -- the Requests screen: tick the fort's wishes, then Done
    if st.requests then
        out.answer = 'requests'
        local ok, n = pcall(function()
            local d = ui()
            local tabs, prios = {}, {}
            for _, c in ipairs(d.taking_requests_tablist) do
                table.insert(tabs, enum_name(df.entity_sell_category, c))
                local list, vec = {}, d.environment.dipev.sell_requests.priority[c]
                for k = 0, #vec - 1 do list[k + 1] = vec[k] end
                table.insert(prios, {list = list, vec = vec})
            end
            local plain_prios = {}
            for i, p in pairs(prios) do plain_prios[i] = p.list end
            local wishes = type(a.wishes) == 'table' and a.wishes or DEFAULT_WISHES
            if a.dry_run then
                local copy = {}
                for i, l in pairs(plain_prios) do copy[i] = {table.unpack(l)} end
                return tick_wishes(tabs, copy, wishes)
            end
            local set = tick_wishes(tabs, plain_prios, wishes)
            for i, p in pairs(prios) do
                for k = 1, #p.list do if p.vec[k - 1] ~= p.list[k] then p.vec[k - 1] = p.list[k] end end
            end
            return set
        end)
        out.wishes_ticked = ok and n or nil
        if not ok then out.error = 'the requests could not be read: ' .. tostring(n):sub(1, 120) end
        if a.dry_run then out.ok = ok; return out end
        if not btn.Done then
            out.ok, out.needs_button = false, 'Done'
            out.error = 'the AI doesn\'t know where the Done button is yet: python brain\\probe_meeting.py --here Done'
            return out
        end
        local before = fingerprint()
        click(btn.Done)
        out.pressed = 'Done'
        out.ok = fingerprint() ~= before
        if not out.ok then out.error = 'Done was pressed and nothing changed: the button may have moved (show it again)' end
        return out
    end
    if st.land_holder then
        return {ok = false, rejected = true, left_to_player = true, topic = st.topic,
                error = 'a barony\'s holder is the player\'s to choose: left to you'}
    end
    -- (0.105.0 review) pressed only when the topic is certain and safe
    local guard = press_guard(pending_topics(st.topics, st.concluded), policy,
                              tonumber(st.tribute_asked) ~= nil and tonumber(st.tribute_asked) >= 0)
    if guard then
        return {ok = false, rejected = true, left_to_player = true, topic = st.topic, topics = st.topics, error = guard}
    end
    local wealth = nil
    pcall(function() wealth = df.global.plotinfo.tasks.wealth.total end)
    local answer, why = decide(st.topic, policy, {amount = st.tribute_asked, wealth = wealth,
                                                  small_share = tonumber(a.small_share) or 0.05})
    out.answer, out.why = answer, why
    if answer == 'requests' then answer = 'yes' end          -- the topic opens the Requests screen
    if answer == nil then out.ok, out.left_to_player = false, true; out.error = why; return out end
    if a.dry_run then out.ok = true; return out end
    local name = answer == 'yes' and 'Yes' or 'No'
    if not btn[name] then
        out.ok, out.needs_button = false, name
        out.error = 'the AI doesn\'t know where the ' .. name .. ' button is yet: python brain\\probe_meeting.py --here ' .. name
        return out
    end
    local before = fingerprint()
    click(btn[name])
    out.pressed = name
    local after = fingerprint()
    out.ok = after ~= before
    if not out.ok then out.error = name .. ' was pressed and nothing changed: the button may have moved (show it again)' end
    -- the meeting over (DF set success or failure): the screen left, as Esc would
    local st2 = meeting_state(nil)
    if st2 and st2.done then
        pcall(function() require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN') end)
        out.closed = meeting_state(nil) == nil
    end
    save_probe({answered = out.answer, pressed = out.pressed, ok = out.ok, after = probe(txt)})
    return out
end
