-- Turns the game's announcements into events the overseer understands
-- (strange moods, tantrums, ghosts, crimes, petitions...). Many things that
-- matter in a fort reach the game only as announcements, never as an event
-- DFHack's event watcher can see.
--
-- Matching is on the announcement type's name (any part of it) and on words
-- in the text, so a renamed type or a reworded message in a new DF version
-- still has a second chance to be caught. Order matters: the first topic
-- that matches wins.
--@module = true

TOPICS = {
    -- a dwarf's mind breaking (after a failed mood, or stress)
    {topic = 'insanity', types = {'BERSERK', 'INSANE', 'MELANCHOLY', 'CRAZED'},
     texts = {'stark raving mad', 'gone berserk', 'melancholy', 'babbling'}},
    -- strange moods, step by step
    {topic = 'artifact_made', types = {'MADE_ARTIFACT', 'NAMED_ARTIFACT'},
     texts = {'has created'}},
    {topic = 'mood_working', types = {'ARTIFACT_BEGUN'},
     texts = {'mysterious construction'}},
    {topic = 'mood_claimed', types = {'MOOD_BUILDING_CLAIMED'},
     texts = {'has claimed a'}},
    {topic = 'mood', types = {'STRANGE_MOOD', 'FEY_MOOD', 'SECRETIVE_MOOD', 'POSSESSED_MOOD',
                              'MACABRE_MOOD', 'FELL_MOOD'},
     texts = {'withdraws from society', 'fey mood', 'secretive mood', 'has been possessed',
              'fell and terrible', 'stalk and brood'}},
    -- stress
    {topic = 'tantrum', types = {'TANTRUM'}, texts = {'tantrum'}},
    {topic = 'stress', types = {'STRESS'}, texts = {'unable to cope', 'is overwhelmed'}},
    -- the dead
    {topic = 'ghost', types = {'GHOST'}, texts = {'ghost', 'haunt', 'has risen'}},
    -- outsiders
    {topic = 'thief', types = {'THIEF', 'SNATCHER', 'KIDNAP'}, texts = {'thief', 'snatcher', 'kidnap', 'sneaking around'}},
    {topic = 'siege', types = {'SIEGE', 'AMBUSH'}, texts = {'siege', 'ambush', 'vile force of darkness'}},
    {topic = 'curse', types = {'VAMPIRE', 'WEREBEAST', 'NECROMANCER', 'UNDEAD'},
     texts = {'vampire', 'necromancer', 'undead', '%f[%a]were%a+', 'has transformed'}},
    -- law and society
    {topic = 'crime', types = {'CRIME', 'JUSTICE'}, texts = {'crime', 'vandal', 'theft', 'has been murdered'}},
    {topic = 'petition', types = {'PETITION'}, texts = {'petition'}},
    {topic = 'birth', types = {'BIRTH_CITIZEN'}, texts = {}},
    {topic = 'migrants', types = {'MIGRANT'}, texts = {'migrants have arrived'}},
    {topic = 'caravan', types = {'CARAVAN'}, texts = {'merchants from', 'a caravan'}},
    -- the map itself
    {topic = 'cave_in', types = {'COLLAPSE', 'CAVE_IN'}, texts = {'cave-in', 'collapse'}},
    {topic = 'flood', types = {'FLOOD'}, texts = {'flood'}},
    {topic = 'dig_cancelled', types = {'DIG_CANCEL'}, texts = {'damp stone', 'warm stone'}},
}

-- Types that are never of interest here (combat play-by-play, animal births).
local SKIP_TYPES = {'COMBAT', 'ANIMAL', 'HUNTING', 'SPARRING', 'MASTERPIECE'}
local SKIP_TEXTS = {'masterpiece'}

local function contains_any(hay, needles, plain)
    for _, n in ipairs(needles) do
        if hay:find(n, 1, plain) then return true end
    end
    return false
end

local function match(type_name, low)
    for _, rule in ipairs(TOPICS) do
        if contains_any(type_name, rule.types, true) then return rule.topic end
    end
    for _, rule in ipairs(TOPICS) do
        -- text patterns may be Lua patterns (e.g. the werebeast one)
        for _, pat in ipairs(rule.texts) do
            if low:find(pat) then return rule.topic end
        end
    end
    return nil
end

-- classify('STRANGE_MOOD', 'Urist withdraws from society...') -> 'mood'
function classify(type_name, text)
    type_name = tostring(type_name or ''):upper()
    if contains_any(type_name, SKIP_TYPES, true) then return nil end
    local low = tostring(text or ''):lower()
    if contains_any(low, SKIP_TEXTS, true) then return nil end
    -- (0.104.38) the professions aren't a siege ("Urist has become a Siege
    -- Operator": 12 false sieges in Enxah's night)
    low = low:gsub('siege operator', 'operator'):gsub('siege engineer', 'engineer')
    local topic = match(type_name, low)
    -- (0.105.15) "X was spotted sneaking around!" is a thief or snatcher
    -- (DF files it with the ambushes), not a siege
    if topic == 'siege' and low:find('sneaking around', 1, true) then topic = 'thief' end
    -- "Urist cancels Clean: Throwing tantrum." repeats for every job the
    -- dwarf drops; only the digging ones (damp or warm stone) are news.
    if topic and topic ~= 'dig_cancelled' and low:find(' cancels ', 1, true) then return nil end
    return topic
end


-- Where an announcement happened: x, y, z, or nil (DF uses -30000 for
-- "nowhere", and not every record has a pos).
local function pos_of(r)
    local ok, x, y, z = pcall(function() return r.pos.x, r.pos.y, r.pos.z end)
    if ok and type(x) == 'number' and x >= 0 and type(y) == 'number' and type(z) == 'number' then
        return x, y, z
    end
end

-- One entry per announcement, with continuation lines joined on.
-- `list` is anything indexable from 0 with {id, type, text, flags, year, time}
-- (and optionally pos).
function merge(list, n, type_name_of, to_text)
    local merged = {}
    for i = 0, n - 1 do
        local r = list[i]
        if r.flags.continuation and #merged > 0 then
            merged[#merged].text = merged[#merged].text .. ' ' .. to_text(r.text)
        else
            local x, y, z = pos_of(r)
            table.insert(merged, {id = r.id, type = type_name_of(r.type), text = to_text(r.text),
                                  year = r.year, tick = r.time, x = x, y = y, z = z})
        end
    end
    return merged
end

-- New announcements since `last_id`, as events. The first call (last_id nil)
-- reports only the last in-game day's, not the whole backlog.
-- Returns events, the newest id seen.
function new_events(merged, last_id, now_year, now_tick)
    local out, newest = {}, last_id or -1
    for _, a in ipairs(merged) do
        if a.id > newest then newest = a.id end
        local fresh
        if last_id then
            fresh = a.id > last_id
        else
            fresh = a.year == now_year and now_tick - (a.tick or 0) <= 1200
        end
        if fresh then
            local topic = classify(a.type, a.text)
            if topic then
                table.insert(out, {kind = 'report', topic = topic, text = a.text, type = a.type,
                                   report_id = a.id, year = a.year, tick = a.tick,
                                   x = a.x, y = a.y, z = a.z})
            end
        end
    end
    return out, newest
end

-- In the game: scan df.global.world.status.announcements.
function scan(last_id, txt)
    local list = df.global.world.status.announcements
    local merged = merge(list, #list,
        function(t) return df.announcement_type[t] or tostring(t) end, txt)
    return new_events(merged, last_id, df.global.cur_year, df.global.cur_year_tick)
end

-- --- the alert icons down the left of the screen (0.88) -----------------------------
--
-- DF gathers announcements into alerts (world.status.announcement_alert, one
-- per alert type: mining, weather, death, combat, nobles...), shown as icons
-- that pile up until someone right-clicks them away. The AI reads every
-- announcement itself, so most icons only clutter the player's screen. An
-- alert is dismissed by taking its entry out of the list (not freed, see
-- dismiss_alerts). Never while the alert window is open, or for the alert
-- under the mouse or being viewed (the game holds pointers to those).

TICKS_PER_YEAR = 403200

local function status() return df.global.world.status end

local function now_ticks() return df.global.cur_year * TICKS_PER_YEAR + df.global.cur_year_tick end

-- Ticks since the newest report the alert holds (nil if none has a date).
local function alert_age(a, now)
    local newest
    for _, rid in ipairs(a.announcement_id) do
        local r = df.report.find(rid)
        if r then
            local t = r.year * TICKS_PER_YEAR + r.time
            if not newest or t > newest then newest = t end
        end
    end
    return newest and math.max(0, now - newest) or nil
end

-- The alerts the game is pointing at right now (never freed under it).
local function held_alerts()
    local held, open = {}, false
    local ok = pcall(function()
        local mi = df.global.game.main_interface
        open = mi.announcement_alert.open == true
        -- (a NULL pointer reads as nil: no ipairs over these, it would stop at the first)
        local ps = {mi.announcement_alert.viewing_alert, mi.current_hover_alert, mi.hover_announcement_alert}
        for i = 1, 3 do
            if ps[i] then table.insert(held, ps[i]) end
        end
    end)
    -- unreadable (a newer DF?): treated as open, so nothing is freed blind
    if not ok then open = true end
    return held, open
end

local function is_held(a, held)
    for _, p in ipairs(held) do if p == a then return true end end
    return false
end

-- {total, by_type = {TYPE = {n, reports, units, age}}, open}
function alerts_report()
    local out = {total = 0, by_type = {}}
    local now = now_ticks()
    local _, open = held_alerts()
    out.open = open or nil
    for _, a in ipairs(status().announcement_alert) do
        local t = df.announcement_alert_type[a.type] or tostring(a.type)
        local e = out.by_type[t] or {n = 0, reports = 0, units = 0}
        e.n = e.n + 1
        e.reports = e.reports + #a.announcement_id
        e.units = e.units + #a.report_unid
        local age = alert_age(a, now)
        if age and (not e.age or age < e.age) then e.age = age end
        out.by_type[t] = e
        out.total = out.total + 1
    end
    return out
end

-- ages: {TYPE = ticks, default = ticks}: an alert goes once its newest
-- report is at least that old; a type given false (or missing with no
-- default) is kept. max: at most this many in one call.
function dismiss_alerts(ages, max, dry_run)
    local held, open = held_alerts()
    if open then return {ok = false, rejected = true, waiting = true, error = 'the alert window is open'} end
    local list = status().announcement_alert
    local now = now_ticks()
    local gone, kept, by_type = 0, 0, {}
    for i = #list - 1, 0, -1 do
        if gone >= max then break end
        local a = list[i]
        local t = df.announcement_alert_type[a.type] or tostring(a.type)
        local need = ages[t]
        if need == nil then need = ages.default end
        local age = alert_age(a, now) or math.huge
        if need ~= nil and need ~= false and age >= need and not is_held(a, held) then
            -- taken out of the list, not freed: a pointer the game still holds
            -- somewhere would then point at freed memory (a crash); a few
            -- bytes left behind are the safer cost
            if not dry_run then list:erase(i) end
            gone = gone + 1
            by_type[t] = (by_type[t] or 0) + 1
        else
            kept = kept + 1
        end
    end
    if gone == 0 then
        return {ok = false, rejected = true, error = 'no alert is old enough to clear', kept = kept}
    end
    return {ok = true, dismissed = gone, by_type = by_type, left = #list, dry_run = dry_run or nil}
end
