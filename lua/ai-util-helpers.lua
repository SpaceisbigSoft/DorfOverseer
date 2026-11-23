-- ai-util-helpers: (r6 c1) the helpers each module had its own copy of
-- (report_citizens, report_units, now_tick, name_of, enum_name) and their
-- variants.
--
-- (r9) A part of ai-util, not a script of its own: ai-util.lua loads it into
-- its own environment, so every name here is reqscript('ai-util').name and
-- the helpers defined there and in the parts before it are in reach.

if not PARTS then qerror('ai-util-helpers is a part of ai-util; run ai-util') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-util-helpers'] = '0.105.72'   -- (0.105.26) bumped with BRIDGE_VERSION

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
