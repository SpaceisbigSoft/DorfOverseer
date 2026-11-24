-- ai-util-helpers: (r6 c1) the helpers each module had its own copy of
-- (report_citizens, report_units, now_tick, name_of, enum_name) and their
-- variants.
--
-- (r9) A part of ai-util, not a script of its own: ai-util.lua loads it into
-- its own environment, so every name here is reqscript('ai-util').name and
-- the helpers defined there and in the parts before it are in reach.

if not PARTS then qerror('ai-util-helpers is a part of ai-util; run ai-util') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-util-helpers'] = '0.105.101'   -- (0.105.26) bumped with BRIDGE_VERSION

-- ===========================================================================
-- (r6 c1, code health) The five helpers each module had its own copy of:
-- report_citizens, report_units, now_tick, name_of, enum_name. The copies had
-- drifted into variants; each variant is kept here as an option or its own
-- name, and each module calls the one it had (same results, same errors).
-- ===========================================================================

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (REPORT_CTX: the same units, same order); outside one, afresh
function report_citizens(...)
    if REPORT_CTX and citizens then return citizens(...) end
    return dfhack.units.getCitizens(...)
end
function report_units()
    if REPORT_CTX and units_active then return units_active() end
    return df.global.world.units.active
end

-- The game's moment (abs_tick), protected: `fallback` (0 or nil, as the
-- caller had it) when it can't be read. number_only: a non-number is the
-- fallback too (ai-killzone); integer: math.tointeger of it (ai-traffic).
function now_tick(fallback, number_only, integer)
    local ok, t = pcall(abs_tick)
    if number_only then return ok and type(t) == 'number' and t or fallback end
    if integer then return ok and math.tointeger(t) or fallback end
    return ok and t or fallback
end

-- A unit's readable name, protected: conv (default tostring) on the name
-- inside the pcall; on failure `fallback` - a string, a function of the unit,
-- or (nil) 'unit <id>'.
function name_of(u, conv, fallback)
    local ok, n = pcall(function() return (conv or tostring)(dfhack.units.getReadableName(u)) end)
    if ok and n then return n end
    if fallback == nil then return 'unit ' .. tostring(u.id) end
    if type(fallback) == 'function' then return fallback(u) end
    return fallback
end
-- Not protected: an error goes to the caller (ai-hauling, ai-labor).
function name_of_raw(u, conv)
    return (conv or tostring)(dfhack.units.getReadableName(u))
end
-- The name protected ('unit <id>' on failure), then conv on it, not
-- protected, the name itself when conv gives nothing (ai-hunt, ai-near-gates).
function name_of_then(u, conv)
    local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
    n = ok and n or ('unit ' .. tostring(u.id))
    return conv and conv(n) or n
end
-- The name protected, conv on it (not protected) only when read; 'unit <id>'
-- when it can't be read or conv gives nothing (ai-insane, ai-killers, ai-thirst).
function name_of_conv(u, conv)
    local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
    return ok and conv(n) or ('unit ' .. tostring(u.id))
end

-- An enum's name for v, protected: the name when it is a string, else nil
-- (nil for v nil or no enum).
function enum_name(enum, v)
    if v == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return nil
end
-- As enum_name, but a number with no name comes back as its text (also with
-- no enum: ai-diplomacy, ai-missions).
function enum_name_num(enum, v)
    if v == nil then return nil end
    local ok, n = pcall(function() return enum[v] end)
    if ok and type(n) == 'string' then return n end
    return tonumber(v) and tostring(v) or nil
end
-- enum[v] as it is, protected (nil on error or a false value: ai-homes).
function enum_value(enum, v)
    local ok, n = pcall(function() return enum[v] end)
    return ok and n or nil
end
-- enum[v] as text, else v as text (ai-killers).
function enum_text(enum, v)
    local ok, n = pcall(function() return enum[v] end)
    if ok and n ~= nil then return tostring(n) end
    return tostring(v)
end

-- (0.105.101) DF's standing orders are one block of bytes. In DFHack
-- 53.17-r1 on Windows, 16 of DFHack's names for them (gather_refuse_outside,
-- gather_vermin_remains, every dump_*, forbid_own_dead, forbid_own_dead_items,
-- forbid_other_nohunt, zoneonly_drink/fish, auto_loom, use_dyed_cloth)
-- resolve about 9 MB away from the rest (B, 24 Nov: auto_loom read 2 there;
-- the AI's "gather refuse from outside" went into some other byte of the
-- game, read back as set, and the game wrote over it: nothing reached the
-- dump). An order counts only when its address lies within STANDING_NEAR
-- bytes of STANDING_ANCHOR (bound on every platform); where DFHack's address
-- is outside and DF's own name (standingorder_<name>, as symbols.xml's win64
-- tables name the petition orders) lies inside on a byte no other order
-- holds, DFHack's name is bound to it (dfhack.internal.setAddress, as
-- petition_orders_bind does). Otherwise the order is missing: never read,
-- never written. Without dfhack.internal (the tests' fakes) every order counts.
STANDING_ANCHOR = 'standing_orders_mix_food'
STANDING_NEAR = 128
STANDING_CHECKED = STANDING_CHECKED or {}     -- {short = true | false}, once a session

local function standing_addr(I, full)
    local ok, a = pcall(I.getAddress, full)
    return (ok and type(a) == 'number') and a or nil
end

local function standing_taken(I, anchor, a, except)
    local taken = false
    pcall(function()
        for k in pairs(df.global) do
            if type(k) == 'string' and k:match('^standing_orders_') and k ~= except then
                if standing_addr(I, k) == a then taken = true end
            end
        end
    end)
    return taken or a == anchor
end

-- the full global name of standing order `short` ('gather_refuse_outside'),
-- or nil and why when it can't be trusted in this DF
function standing_order(short)
    short = tostring(short):gsub('^standing_orders_', '')
    local full = 'standing_orders_' .. short
    local I = dfhack.internal
    if type(I) ~= 'table' or type(I.getAddress) ~= 'function' then return full end
    if STANDING_CHECKED[short] ~= nil then
        return STANDING_CHECKED[short] and full or nil, STANDING_CHECKED[short] == false and 'not by the other standing orders' or nil
    end
    local anchor = standing_addr(I, STANDING_ANCHOR)
    if not anchor then STANDING_CHECKED[short] = true; return full end
    local a = standing_addr(I, full)
    local near = function(x) return x ~= nil and math.abs(x - anchor) <= STANDING_NEAR end
    if near(a) then STANDING_CHECKED[short] = true; return full end
    local d = standing_addr(I, 'standingorder_' .. short)
    if near(d) and type(I.setAddress) == 'function' and not standing_taken(I, anchor, d, full) then
        local okv, v = pcall(function() return df.reinterpret_cast('uint8_t', d).value end)
        if okv and (v == 0 or v == 1) and pcall(I.setAddress, full, d) and standing_addr(I, full) == d then
            STANDING_CHECKED[short] = true
            return full
        end
    end
    STANDING_CHECKED[short] = false
    return nil, 'not by the other standing orders'
end
