-- (0.105.41, item 8) Export bans: the goods the nobles (the mountainhome's
-- monarch, a baron's own) forbid the fort to export, kept off the caravan
-- trade. DF keeps them as mandates: df.global.world.mandates.all, mode
-- Export (df.mandate_type), item_type / item_subtype / mat_type /
-- mat_index (-1: any), in force while timeout_counter < timeout_limit; this
-- is how DFHack's own caravan screen (internal/caravan/common
-- get_banned_items) reads them, and the bridge's `mandates` section reads
-- the same list. Breaking one gets the noble's punishment (a beating, jail).
--
-- lua/ai-trade.lua asks checker() whether an item (or a bin's contents) is
-- banned: never taken to the depot, never offered on the trade screen. Our
-- own match is kept beside DFHack's (its scan_banned, and its "risky" list)
-- so a DFHack without that internal script still keeps the bans.
--@ module = true

MAX_BANS = 20

local function enum_name(enum, v)
    if v == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return nil
end

local function num(v, default)
    v = tonumber(v)
    if v == nil then return default end
    return v
end

-- Pure: is a mandate an export ban in force? m: {mode (number or name),
-- timeout_counter, timeout_limit}; export: the Export mode's number.
function in_force(m, export)
    if m == nil then return false end
    if m.mode ~= export and m.mode ~= 'Export' then return false end
    local lim, cnt = tonumber(m.timeout_limit), tonumber(m.timeout_counter)
    if lim and cnt then return cnt < lim end
    return true                        -- the timer unreadable: kept as in force (the safe side)
end

-- Pure: does a ban cover an item? Both plain tables {item_type,
-- item_subtype, mat_type, mat_index}; -1 (or nil) in the ban is any.
function matches(ban, it)
    if ban == nil or it == nil then return false end
    local bt = num(ban.item_type, -1)
    if bt >= 0 and bt ~= num(it.item_type, -2) then return false end
    local bs = num(ban.item_subtype, -1)
    if bs >= 0 and bs ~= num(it.item_subtype, -2) then return false end
    local bm = num(ban.mat_type, -1)
    if bm >= 0 then
        if bm ~= num(it.mat_type, -2) then return false end
        local bi = num(ban.mat_index, -1)
        if bi >= 0 and bi ~= num(it.mat_index, -2) then return false end
    end
    return true
end

-- Pure: the first ban that covers the item, or nil.
function banned_by(bans, it)
    for _, b in ipairs(bans or {}) do
        if matches(b, it) then return b end
    end
    return nil
end

-- The export bans in force now: {{item_type, item_subtype, mat_type,
-- mat_index, item, material, by, days_left}}. Every read is guarded: a
-- field that can't be read leaves that ban out.
function read(txt)
    txt = txt or tostring
    local out = {}
    local export = nil
    pcall(function() export = df.mandate_type.Export end)
    local okl, list = pcall(function() return df.global.world.mandates.all end)
    if not okl or list == nil then return out end
    pcall(function()
        for _, m in ipairs(list) do
            if #out >= MAX_BANS then break end
            local ok, b = pcall(function()
                if not in_force({mode = m.mode, timeout_counter = m.timeout_counter,
                                 timeout_limit = m.timeout_limit}, export) then return nil end
                return {item_type = m.item_type, item_subtype = m.item_subtype,
                        mat_type = m.mat_type, mat_index = m.mat_index}
            end)
            if ok and b then
                b.item = enum_name(df.item_type, b.item_type) or tostring(b.item_type)
                pcall(function()
                    if b.mat_type >= 0 then
                        local mi = dfhack.matinfo.decode(b.mat_type, b.mat_index)
                        if mi then b.material = txt(mi:toString()) end
                    end
                end)
                pcall(function() if m.unit then b.by = txt(dfhack.units.getReadableName(m.unit)) end end)
                pcall(function()
                    b.days_left = math.max(0, (m.timeout_limit - m.timeout_counter) * 10 // 1200)
                end)
                table.insert(out, b)
            end
        end
    end)
    return out
end

-- An item as matches() wants it.
function item_key(item)
    local ok, k = pcall(function()
        return {item_type = item:getType(), item_subtype = item:getSubtype(),
                mat_type = item:getMaterial(), mat_index = item:getMaterialIndex()}
    end)
    return ok and k or nil
end

-- DFHack's own ban check (internal/caravan/common), or nil without it.
local function dfhack_check()
    local ok, common = pcall(reqscript, 'internal/caravan/common')
    if not ok or type(common) ~= 'table' then return nil end
    local okr, risky = pcall(function() return common.get_risky_items(common.get_banned_items()) end)
    if not okr then return nil end
    return function(item)
        local okb, banned, isrisky = pcall(common.scan_banned, item, risky)
        return okb and (banned or isrisky) or false
    end
end

-- A function(item) -> true when the item, or anything in it, is banned
-- from export. No ban in force: always false (DFHack's scan isn't run).
-- bans: a list from read() (read now when nil).
function checker(bans)
    bans = bans or read()
    if #bans == 0 then return function() return false end, bans end
    local theirs = dfhack_check()
    local function one(item)
        if banned_by(bans, item_key(item)) then return true end
        return theirs ~= nil and theirs(item) == true
    end
    return function(item)
        if one(item) then return true end
        local okc, inside = pcall(dfhack.items.getContainedItems, item)
        if okc and inside then
            for _, it in ipairs(inside) do if one(it) then return true end end
        end
        return false
    end, bans
end

-- For the report (lua/ai-trade.lua survey): the bans in force, in words.
function summary(bans)
    local out = {}
    for _, b in ipairs(bans or {}) do
        table.insert(out, {item = b.item, material = b.material, by = b.by, days_left = b.days_left})
    end
    return out
end
