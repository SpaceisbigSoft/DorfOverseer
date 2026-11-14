-- (0.105.46, I6) Walks spread over several reports.
--
-- Why: the run check of 12-13 Nov had two report sections the game waited
-- for: industry (563 ms median: the ore veins near the fort, tile by tile)
-- and deep (265 ms: every cavern block's tiles, the deep hazard's blocks).
-- What they read changes slowly (a vein is uncovered a few tiles a day, a
-- cavern seen a little at a time), so one pass over the whole list need not
-- happen inside one report: each report walks a slice (a time and a count
-- budget) and keeps its place here; the section sends the last finished
-- pass's result until the next one is whole.
--
-- run(name, spec) -> result, status, done, total
--   spec.key        what the walk is of (a map key...): another key starts afresh
--   spec.now        the game tick (for ttl)
--   spec.ttl        ticks a finished result is good for (nil: until invalidated;
--                   0: a new pass each time the caller asks with none under way)
--   spec.items()    the list to walk, made when a pass starts
--   spec.init()     a new pass's accumulator
--   spec.visit(acc, item)   one item (a throw counts as an error, the walk goes on)
--   spec.finish(acc, pass)  the result from a whole pass
--   spec.max_items, spec.max_ms   the slice's budget (at least one item a call)
--   spec.whole_first   with no result yet, the first pass is walked whole
--                      (the old cost once per map: a section never sends a
--                      half-walked answer)
-- status: 'cached' (the last result, still good), 'done' (a pass finished
-- now), 'partial' (a pass under way: result is the last finished one, or
-- nil when there is none yet).
--
-- State is kept in this script's globals (DFHack keeps them between runs),
-- dropped when the map unloads. Pure Lua: no game data is read here.
--@module = true

SLICES = SLICES or {}
SLICE_MS = 40            -- a slice's default time budget (os.clock ms)

function reset(name)
    if name == nil then SLICES = {} else SLICES[name] = nil end
end

-- What a walk read is stale (an action changed it): the pass under way is
-- dropped and the next call starts a new one; the last result is still sent
-- until then.
function invalidate(name)
    local s = SLICES[name]
    if s then
        s.stale = true
        s.pass = nil
    end
end

function status(name)
    local s = SLICES[name]
    if not s then return nil end
    return {key = s.key, passes = s.passes or 0, last_tick = s.last_tick, stale = s.stale or nil,
            under_way = s.pass and {done = s.pass.i - 1, total = #s.pass.list, slices = s.pass.slices} or nil}
end

function run(name, spec)
    local s = SLICES[name]
    if s and s.key ~= spec.key then s = nil end
    if not s then
        s = {key = spec.key}
        SLICES[name] = s
    end
    local now = spec.now
    if not s.pass then
        local ttl = spec.ttl
        local good = s.last ~= nil and not s.stale and ttl ~= 0
            and (ttl == nil or (type(now) == 'number' and type(s.last_tick) == 'number'
                                and now >= s.last_tick and now - s.last_tick < ttl))
        if good then return s.last, 'cached', 0, 0 end
        s.pass = {list = spec.items() or {}, i = 1, acc = spec.init(), started = now, slices = 0}
        s.stale = nil
    end
    local p = s.pass
    local whole = spec.whole_first and s.last == nil
    local max_n = spec.max_items or math.huge
    local max_ms = spec.max_ms or SLICE_MS
    local clock = os.clock
    local t0 = clock()
    local n = 0
    local list, visit, acc = p.list, spec.visit, p.acc
    p.slices = p.slices + 1
    while p.i <= #list do
        if not whole and n > 0 and (n >= max_n or (clock() - t0) * 1000 >= max_ms) then break end
        local ok, err = pcall(visit, acc, list[p.i])
        if not ok then
            p.errors = (p.errors or 0) + 1
            p.err = p.err or tostring(err)
        end
        p.i = p.i + 1
        n = n + 1
    end
    if p.i > #list then
        local r = spec.finish and spec.finish(acc, p) or acc
        s.last, s.last_tick, s.pass = r, now, nil
        s.passes = (s.passes or 0) + 1
        s.last_slices, s.last_errors = p.slices, p.errors
        return r, 'done', #list, #list
    end
    return s.last, 'partial', p.i - 1, #list
end

-- (a new map: every walk starts afresh)
if dfhack and dfhack.onStateChange then
    pcall(function()
        dfhack.onStateChange['ai-slices'] = function(sc)
            if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then SLICES = {} end
        end
    end)
end
