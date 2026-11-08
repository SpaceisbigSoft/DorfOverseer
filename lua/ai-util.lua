-- Small helpers shared by the AI's Lua modules (13c): the fort's entity, the
-- game's absolute tick, the save's site data, and whether an item is free for
-- a new job. Each was copied into many modules, and the copies had drifted.
--
-- A module takes it with `local U = reqscript('ai-util')`; the tests load a
-- module through tests/lua_modules_util.py, which hands it this one.
--@module = true

TICKS_PER_DAY = 1200
TICKS_PER_MONTH = 28 * TICKS_PER_DAY
TICKS_PER_YEAR = 403200

-- The fort's own entity (the site government), or nil.
function fort_entity()
    return df.historical_entity.find(df.global.plotinfo.group_id)
end

-- Ticks since the world began, from a year and its tick (an event's
-- year/year_tick); with no arguments, now. Not protected: a caller that may
-- run with no world loaded wraps it in pcall.
function abs_tick(year, tick)
    if year == nil then year, tick = df.global.cur_year, df.global.cur_year_tick end
    return year * TICKS_PER_YEAR + tick
end

-- The save's site data under `key`, or `default` when there is none, it
-- can't be read, or (a table default) it isn't a table.
function site_get(key, default)
    local ok, d = pcall(function() return dfhack.persistent.getSiteData(key, default) end)
    if not ok or d == nil then return default end
    if type(default) == 'table' and type(d) ~= 'table' then return default end
    return d
end

-- Saves `value` as the site data under `key`. Returns true, or false and
-- the error (callers that only log it may ignore it; none should need to
-- guess why a value didn't stick).
function site_put(key, value)
    local ok, err = pcall(function() dfhack.persistent.saveSiteData(key, value) end)
    if ok then return true end
    return false, tostring(err)
end

-- --- is an item free for a new job? ------------------------------------------------
--
-- The one list (13c). Before it, about a dozen copies disagreed: some missed
-- rotten, encased, on fire, a spider web, owned, an artifact, evidence of a
-- murder or a dead dwarf's belongings, some missed the dump or a job, and
-- some counted an item in a dwarf's hands. In checking order: what the fort
-- can never use first, then what a job holds, then what the player (or the
-- AI) set aside, then what a unit carries. `in_inventory` alone is not a
-- reason: DF sets it for an item in a bin or barrel too.
UNFREE = {
    {'removed', 'gone'}, {'garbage_collect', 'gone'},
    {'construction', 'in a building'}, {'in_building', 'in a building'},
    {'encased', 'encased'},
    {'trader', 'a trader\'s'}, {'hostile', 'an enemy\'s'}, {'owned', 'owned by a dwarf'},
    {'artifact', 'an artifact'}, {'murder', 'evidence of a murder'}, {'dead_dwarf', 'a dead dwarf\'s'},
    {'rotten', 'rotten'}, {'on_fire', 'on fire'}, {'spider_web', 'a spider web'},
    {'in_job', 'taken by a job'}, {'forbid', 'forbidden'}, {'dump', 'marked for the dump'},
}

-- nil when the item is free, else the flag that stops it ('held' for an
-- item a unit carries) and why in words. `allow` (optional): a set of flag
-- names (and 'held') the caller doesn't mind, e.g. {in_job = true} to count
-- stock a job may be using, {held = true} to skip the holder look-up.
function item_unfree(it, allow)
    local f = it.flags
    for _, row in ipairs(UNFREE) do
        local name = row[1]
        if f[name] and not (allow and allow[name]) then return name, row[2] end
    end
    if f.in_inventory and not (allow and allow.held) then
        local ok, u = pcall(dfhack.items.getHolderUnit, it)
        if ok and u ~= nil then return 'held', 'carried' end
    end
    return nil
end

function item_free(it, allow)
    return item_unfree(it, allow) == nil
end
