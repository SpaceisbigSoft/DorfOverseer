-- ai-util-doors: doors, hatches and the walk map: every door or hatch flag the
-- AI writes goes through lock_door / shut_door here, and DF is asked to redo
-- its walk map (repath, door_changed); and module_flags_reset (a module
-- DFHack refused as "Cannot be used as a module" read again next time).
--
-- (r9) A part of ai-util, not a script of its own: ai-util.lua loads it into
-- its own environment, so every name here is reqscript('ai-util').name and
-- the helpers defined there and in the parts before it are in reach.

if not PARTS then qerror('ai-util-doors is a part of ai-util; run ai-util') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-util-doors'] = '0.105.111'   -- (0.105.26) bumped with BRIDGE_VERSION

-- --- doors, hatches and the walk map (0.105.47, J16) ------------------------------
--
-- Live 14 Nov (War-hold, the player: "the dwarves lock themselves in"): the
-- AI's two surface hatches were unlocked by a bare `door_flags.forbidden =
-- false` write and read open, yet the citizens' walk group (6712) still
-- reached no map-edge tile: DF doesn't redo its walk groups for a flag
-- written from Lua. world.reindex_pathfinding asks it to. So every place the
-- AI locks or unlocks a door or hatch, or sets one open or shut, does it
-- through lock_door / shut_door here, and anything else the AI changes
-- directly (a lever pulled at once) calls door_changed: DF is asked to redo
-- its walk map, once a game tick (one report or action is one tick: the
-- game stands still for a dfhack-run call). A pull by a dwarf's job goes
-- through DF and needs nothing. No other file writes these flags
-- (tests/test_r47_way_out.py greps for it).
REPATH = REPATH or {n = 0, writes = 0}

-- DF asked to redo its walk map (the field set, pcall'd), at most once a
-- tick. true if asked (now or already this tick). why: a word for the record.
function repath(why)
    local okt, t = pcall(abs_tick)
    t = okt and t or nil
    if t ~= nil and REPATH.tick == t and REPATH.ok then return true end
    local ok = pcall(function()
        if df.global.world.reindex_pathfinding == nil then error('no such field') end
        df.global.world.reindex_pathfinding = true
    end) == true
    REPATH.tick, REPATH.ok = t, ok
    if ok then
        REPATH.n = (REPATH.n or 0) + 1
        REPATH.last_tick, REPATH.why = t, why and tostring(why):sub(1, 40) or nil
    end
    return ok
end

-- A door, hatch, bridge or floodgate the AI changed directly: the walk map redone.
function door_changed(b, why)
    return repath(why)
end

local function set_door_flag(b, name, v, why)
    v = v == true
    local ok, changed = pcall(function()
        if b.door_flags[name] == v then return false end
        b.door_flags[name] = v
        return true
    end)
    if ok and changed then
        REPATH.writes = (REPATH.writes or 0) + 1
        repath(why)
    end
    return ok and changed or false, ok
end

-- Lock (true) or unlock (false) a door or hatch: (changed, ok). ok false:
-- the building or its flags couldn't be read or written (nothing changed).
function lock_door(b, locked, why) return set_door_flag(b, 'forbidden', locked, why) end

-- Set a door or hatch shut (true) or open (false) by its flag: (changed, ok).
function shut_door(b, closed, why) return set_door_flag(b, 'closed', closed, why) end

-- What the report shows (the `way_out` section's `repaths`)
function repath_summary()
    return {n = REPATH.n or 0, writes = REPATH.writes or 0, last_tick = REPATH.last_tick, why = REPATH.why}
end

-- (0.105.51) DFHack's reqscript refused a module it read no `--@ module = true`
-- line in: "<name>: Cannot be used as a module". R3 (F, 14 Nov 22:52, the
-- industry section): the scripts were copied over while the game ran
-- (0.105.48 to 0.105.49) and DFHack read ai-builder.lua half written; it
-- keeps the flags it read until the file's time changes (whole seconds), so
-- a write within the same second left them wrong. err: the error text. The
-- module's cached flags are dropped (dfhack.lua's Script: flags_mtime,
-- _flags), so the next reqscript reads the file again. Returns the module's
-- name when it did, else nil.
function module_flags_reset(err)
    local name = type(err) == 'string' and err:match('([%w_%-/]+): Cannot be used as a module') or nil
    if not name then return nil end
    local ok = pcall(function()
        local path = dfhack.findScript(name)
        local sc = path and dfhack.internal.scripts[path]
        if not sc then error('not loaded') end
        sc.flags_mtime = nil
        sc._flags = {}
    end)
    return ok and name or nil
end
