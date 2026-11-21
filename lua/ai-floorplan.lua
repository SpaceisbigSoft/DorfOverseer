-- The floor plans of the hallway-first layout (layout B), as data: pure
-- functions, no game access.
--
-- A floor is one z-level of the fort with its 3-wide main hall running out
-- from the central stair. This module owns the saved record of the floors
-- (site data key 'ai-overseer/floors', read and written by ai-builder only):
-- its migration, the clamps of the floor grammar, writing a finished placement
-- into the record (commit), taking a cancelled project out (release), marking
-- a floor full, the tiles a floor claims, and the rows of the report. It never
-- reads the map and never decides where anything goes (ai-floorplace does).
--
-- All geometry is in stair-relative tiles: (0, 0) is the central stair on
-- that level, +x east, +y south (the frame ai-layouts uses).
--   run   {id, parent, ox, oy, dx, dy, len, walked, tag, node, neck, closed}
--         one straight stretch of hall. Run coordinates (u, v) are the tile
--         x = ox + u*dx + v*px, y = oy + u*dy + v*py with p = (-dy, dx).
--         The node is u, v in [-1, 1] (node = 5: [-2, 2]); the hall is
--         u in [u0, u0 + len - 1], v in [-1, 1], u0 = 2 (3 for a 5x5 node);
--         a neck's first column u0 is only v = 0.
--   slot  {run, side, u, w, d, pid, kind, tag, group, role, flag, dead}
--         columns u .. u + w - 1; the wall row is v = 2*side, the room is
--         v = 3*side .. (2 + d)*side.
-- Beside the contract's keys this module keeps, for release: on a run
-- `pid` (the project that made it), `grew` ({[tostring(pid)] = len before
-- that project lengthened it}) and `low` (the shortest length a released
-- project would have rolled it back to); on an axial slot `axial = true`
-- and `rect` (its box as placed).
--
-- The store is saved as JSON: only string keys or dense lists in it.
-- Tested with tests/test_b1_floorplan.py.
--@ module = true

VERSION = 1
FLOORS_MAX = 60       -- floors in the store
SLOTS_MAX = 160       -- slots a floor (dead ones too)
RUNS_MAX = 24         -- runs a floor

local DAY = 1200
local COMPASS = {'east', 'south', 'west', 'north'}
local IS_COMPASS = {east = true, south = true, west = true, north = true}

-- G's numbers: key -> {lowest, highest, default}
local NUMBERS = {
    gap = {1, 4, 1}, kind_gap = {0, 6, 1}, lead = {0, 8, 2}, ahead = {0, 3, 1},
    run_max = {12, 80, 30}, run_min = {4, 30, 10}, arms_max = {1, 4, 2},
    stagger = {0, 6, 0}, tries = {4, 60, 24}, full_retry_days = {1, 336, 28},
    -- read by the builder beside the grammar
    pile_w = {3, 11, 5}, piles_new = {0, 3, 1},
}
local WORDS = {
    sides = {both = true, one = true, alternate = true, default = 'both'},
    turns = {left = true, right = true, alternate = true, both = true, default = 'alternate'},
}
local BOOLS = {'balance', 'axial', 'neck'}
local SHOP_COLS, PILE_COLS = 5, 5   -- a workshop's room and the smallest pile room, in columns along the hall
local PASSED = {'elevs', 'tag', 'group', 'zone', 'spine'}

-- ---------------------------------------------------------------- helpers

local function is_num(n)
    return type(n) == 'number' and n == n and n ~= math.huge and n ~= -math.huge
end

local function whole(n)
    return math.floor(n + 0.5)
end

local function clamp(n, lo, hi, default)
    if not is_num(n) then return default end
    n = whole(n)
    if n < lo then return lo end
    if n > hi then return hi end
    return n
end

local function list_of(t)
    return type(t) == 'table' and t or {}
end

local function u0_of(run)
    return (run.node == 5) and 3 or 2
end

local function half_of(run)
    return (run.node == 5) and 2 or 1
end

local function is_hub_run(run)
    return run.parent == nil or run.parent == 0
end

local function same_pid(a, b)
    return a ~= nil and b ~= nil and tostring(a) == tostring(b)
end

local function compass(dx, dy)
    if dx == 1 and dy == 0 then return 'east' end
    if dx == -1 and dy == 0 then return 'west' end
    if dx == 0 and dy == 1 then return 'south' end
    if dx == 0 and dy == -1 then return 'north' end
    return nil
end

local function find_run(floor, id)
    for _, r in ipairs(list_of(floor.runs)) do
        if type(r) == 'table' and r.id == id then return r end
    end
    return nil
end

local function index_of(store, floor)
    for i, f in ipairs(store.floors) do
        if f == floor then return i end
    end
    return nil
end

local function max_id(store)
    local top = 0
    for _, f in ipairs(store.floors) do
        if type(f) == 'table' and is_num(f.id) and f.id > top then top = f.id end
    end
    return top
end

local function usable(store)
    return type(store) == 'table' and type(store.floors) == 'table'
end

-- The store's own record of `floor`: the same table, or the one with its z and
-- stair (a floor handed in twice is one floor).
local function own_record(store, floor)
    if index_of(store, floor) then return floor end
    if type(floor.stair) == 'table' then
        return find_floor(store, floor.z, floor.stair.x, floor.stair.y)
    end
    return nil
end

-- Put a floor that is not in the store into it. Its id is kept unless another
-- floor has it; store.next moves past it.
local function insert_floor(store, floor)
    local taken = not is_num(floor.id)
    for _, f in ipairs(store.floors) do
        if type(f) == 'table' and f.id == floor.id then taken = true end
    end
    if taken then
        floor.id = math.max(is_num(store.next) and store.next or 1, max_id(store) + 1)
    end
    if type(floor.runs) ~= 'table' then floor.runs = {} end
    if type(floor.slots) ~= 'table' then floor.slots = {} end
    if type(floor.full) ~= 'table' then floor.full = {} end
    if floor.hub ~= 'dug' then floor.hub = 'found' end
    table.insert(store.floors, floor)
    if not is_num(store.next) or store.next <= floor.id then store.next = floor.id + 1 end
    return floor
end

-- ---------------------------------------------------------------- the store

function new_store()
    return {v = VERSION, next = 1, fallbacks = 0, floors = {}}
end

-- A number, from a number or a numeric string ("12"), or nil.
local function num_of(v)
    if is_num(v) then return v end
    if type(v) == 'string' then
        local n = tonumber(v)
        if is_num(n) then return n end
    end
    return nil
end

local RUN_NUMS = {'parent', 'ox', 'oy', 'len', 'walked', 'node', 'low'}
local SLOT_NUMS = {'u', 'w', 'd'}
local RECT_NUMS = {'x1', 'y1', 'x2', 'y2'}

-- (F2) The fields of a table that should be numbers: a numeric string becomes
-- its number (changed), anything else is left to `junk` (true when one of
-- `required` is not a number, so the caller drops the row). `optional` fields
-- that are not numbers are cleared.
local function mend_nums(t, required, optional)
    local changed, junk = false, false
    for _, k in ipairs(required) do
        local v = t[k]
        local n = num_of(v)
        if n == nil then junk = true
        elseif n ~= v then t[k] = n; changed = true end
    end
    for _, k in ipairs(optional or {}) do
        local v = t[k]
        if v ~= nil then
            local n = num_of(v)
            if n ~= v then t[k] = n; changed = true end
        end
    end
    return changed, junk
end

-- A list (dense, 1..n) from whatever was saved: a list is kept as it is; an
-- object with string keys (or a list with holes) gives its table values, in
-- the order of their numeric keys and then their ids. Returns list, changed.
local function dense(t)
    local n, count = #t, 0
    for _ in pairs(t) do count = count + 1 end
    if count == n then return t, false end
    local rows = {}
    for k, v in pairs(t) do table.insert(rows, {k = k, v = v}) end
    table.sort(rows, function(a, b)
        local ka, kb = num_of(a.k), num_of(b.k)
        if ka and kb then return ka < kb end
        if ka or kb then return ka ~= nil end
        return tostring(a.k) < tostring(b.k)
    end)
    local out = {}
    for _, r in ipairs(rows) do table.insert(out, r.v) end
    return out, true
end

-- (F2, S3) One floor's runs, slots, marks and free run mended in place: a
-- numeric string becomes its number; a run with no id or no direction, a
-- second run with the same id, a slot with no run, no side or no place (and
-- every slot of a dropped run) is dropped. Returns changed.
local function mend_floor(f)
    local changed = false
    local function set(k, v) f[k] = v; changed = true end
    if type(f.stair) ~= 'table' then set('stair', {})
    else
        local c = mend_nums(f.stair, {}, {'x', 'y'})
        changed = changed or c
    end
    if type(f.runs) ~= 'table' then set('runs', {}) end
    if type(f.slots) ~= 'table' then set('slots', {}) end
    if type(f.full) ~= 'table' then set('full', {}) end
    local runs, c1 = dense(f.runs)
    local slots, c2 = dense(f.slots)
    changed = changed or c1 or c2

    local kept_runs, ids = {}, {}
    for _, r in ipairs(runs) do
        local ok = false
        if type(r) == 'table' then
            local c, junk = mend_nums(r, {'id', 'dx', 'dy'}, RUN_NUMS)
            changed = changed or c
            if not junk and compass(r.dx, r.dy) and not ids[r.id] then
                ok = true
                if r.len == nil then r.len = 0; changed = true end
                if r.walked == nil then r.walked = 0; changed = true end
                if r.grew ~= nil then
                    if type(r.grew) ~= 'table' then r.grew = nil; changed = true
                    else
                        for k, v in pairs(r.grew) do
                            local n = num_of(v)
                            if n ~= v then r.grew[k] = n; changed = true end
                        end
                        if next(r.grew) == nil then r.grew = nil; changed = true end
                    end
                end
                if r.tag ~= nil and type(r.tag) ~= 'string' then r.tag = nil; changed = true end
                if r.closed ~= nil and type(r.closed) ~= 'string' then r.closed = nil; changed = true end
                if r.neck ~= nil and type(r.neck) ~= 'boolean' then r.neck = (r.neck == true); changed = true end
            end
        end
        if ok then
            ids[r.id] = true
            table.insert(kept_runs, r)
        else
            changed = true
        end
    end

    local kept_slots = {}
    for _, s in ipairs(slots) do
        local ok = false
        if type(s) == 'table' then
            local c, junk = mend_nums(s, {'run', 'side'}, SLOT_NUMS)
            changed = changed or c
            local placed = is_num(s.u) and is_num(s.w) and is_num(s.d)
            local side_ok = s.side == 1 or s.side == -1 or (s.axial == true and s.side == 0)
            if not junk and ids[s.run] and placed and side_ok then
                ok = true
                if s.rect ~= nil then
                    local bad = type(s.rect) ~= 'table'
                    if not bad then
                        local cr, jr = mend_nums(s.rect, RECT_NUMS)
                        changed = changed or cr
                        bad = jr
                    end
                    if bad then s.rect = nil; changed = true end
                end
                for _, k in ipairs({'kind', 'tag', 'role', 'flag'}) do
                    if s[k] ~= nil and type(s[k]) ~= 'string' then s[k] = nil; changed = true end
                end
                -- a saved `false` stays false; anything else that is set means dead
                if s.dead ~= nil and type(s.dead) ~= 'boolean' then s.dead = true; changed = true end
            end
        end
        if ok then table.insert(kept_slots, s) else changed = true end
    end
    if #kept_runs ~= #runs or c1 then f.runs = kept_runs end
    if #kept_slots ~= #slots or c2 then f.slots = kept_slots end

    for tag, tick in pairs(f.full) do
        local n = num_of(tick)
        if type(tag) ~= 'string' or n == nil then f.full[tag] = nil; changed = true
        elseif n ~= tick then f.full[tag] = n; changed = true end
    end
    if f.free ~= nil then
        if type(f.free) ~= 'table' then set('free', nil)
        else
            local c = mend_nums(f.free, {}, {'tick', 'east', 'south', 'west', 'north'})
            changed = changed or c
        end
    end
    if f.hub ~= nil and f.hub ~= 'dug' and f.hub ~= 'found' then set('hub', 'found') end
    return changed
end

-- nil / {} / junk / no whole v -> a new store (changed = true). A newer store
-- comes back untouched with changed = false, why = 'newer': callers then only
-- read it. A v1 store that lost a part or holds junk (hand-edited,
-- half-written, a number saved as a string) is mended in place (changed =
-- true, why = 'repaired'; see mend_floor). Never throws.
function migrate(store)
    if type(store) ~= 'table' then
        return new_store(), true, (store == nil) and 'new' or 'junk'
    end
    local v = rawget(store, 'v')
    if not is_num(v) or v < 1 or v ~= math.floor(v) then
        return new_store(), true, (next(store) == nil) and 'new' or 'junk'
    end
    if v > VERSION then return store, false, 'newer' end
    local changed = false
    if type(store.floors) ~= 'table' then store.floors = {}; changed = true end
    local rows, holey = dense(store.floors)
    local kept, dropped, ids = {}, holey, {}
    for _, f in ipairs(rows) do
        local ok = false
        if type(f) == 'table' then
            local c, junk = mend_nums(f, {'id', 'z'}, {'made'})
            changed = changed or c
            if not junk then
                ok = true
                if mend_floor(f) then changed = true end
            end
        end
        if ok then table.insert(kept, f) else dropped = true end
    end
    -- (F2) a second floor with the same id gets a new one
    local top = 0
    for _, f in ipairs(kept) do if f.id > top then top = f.id end end
    for _, f in ipairs(kept) do
        if ids[f.id] then
            top = top + 1
            f.id = top
            changed = true
        end
        ids[f.id] = true
    end
    if dropped or #kept ~= #store.floors then
        -- a list with a hole or a junk row: rebuilt dense
        for k in pairs(store.floors) do store.floors[k] = nil end
        for i, f in ipairs(kept) do store.floors[i] = f end
        changed = true
    end
    local nx = num_of(store.next)
    if nx ~= store.next then store.next = nx; changed = true end
    top = max_id(store)
    if not is_num(store.next) or store.next <= top then store.next = top + 1; changed = true end
    local fb = num_of(store.fallbacks)
    if fb ~= store.fallbacks then store.fallbacks = fb; changed = true end
    if not is_num(store.fallbacks) then store.fallbacks = 0; changed = true end
    if changed then return store, true, 'repaired' end
    return store, false, nil
end

-- ---------------------------------------------------------------- prune

local function has_any(t)
    if type(t) ~= 'table' then return false end
    return next(t) ~= nil
end

-- (F2, V2) A floor that is only a mark: no run, no slot, no hub dug. Only such
-- a floor is ever taken out of the record.
local function empty_floor(f)
    return type(f) == 'table' and not has_any(f.runs) and not has_any(f.slots) and f.hub ~= 'dug'
end

-- (r3 g1) A floor with no hall left: it has a run or a slot, but no slot is
-- live and every run is released or has no length (its levels were all
-- cancelled: D's floor 3, `hall 0`, `closed: released`, hub `dug`). The
-- report's row says `dead`; marked '*' (its hub refused) it is a no_hall row,
-- so the brain no longer offers its level while the mark is fresh.
function dead_floor(f)
    if type(f) ~= 'table' or not (has_any(f.runs) or has_any(f.slots)) then return false end
    for _, s in ipairs(list_of(f.slots)) do
        if type(s) == 'table' and not s.dead then return false end
    end
    for _, r in ipairs(list_of(f.runs)) do
        if type(r) == 'table' and r.closed ~= 'released' and is_num(r.len) and r.len > 0 then return false end
    end
    return true
end

-- The tick of a floor's newest mark (nil: none that is a number).
local function newest_mark(f)
    local top
    for _, t in pairs(type(f.full) == 'table' and f.full or {}) do
        if is_num(t) and (top == nil or t > top) then top = t end
    end
    return top
end

-- Can the record take one more floor? It can while it holds fewer than
-- FLOORS_MAX, or when one of its floors is only a mark (make_room drops it).
-- Reads only.
function room_for(store)
    if not usable(store) then return false end
    if #store.floors < FLOORS_MAX then return true end
    for _, f in ipairs(store.floors) do
        if empty_floor(f) then return true end
    end
    return false
end

-- (F2, V2) Take out of the record every floor that is only a mark (no run,
-- no slot, no hub dug) whose marks are all older than retry_days (default
-- 28) as of `now`. A floor with a run or a slot is never taken out. With
-- `room` true, and the record still at FLOORS_MAX, the floor-only-a-mark
-- whose newest mark is oldest goes too (a mark only saves a search). store.next
-- never goes back, so an id is never given twice. Returns how many went.
function prune(store, now, retry_days, room)
    if not usable(store) then return 0 end
    local span = (is_num(retry_days) and retry_days > 0 and retry_days or NUMBERS.full_retry_days[3]) * DAY
    local kept, n = {}, 0
    for _, f in ipairs(store.floors) do
        local gone = false
        if empty_floor(f) and is_num(now) then
            local t = newest_mark(f)
            gone = t == nil or now - t >= span
        end
        if gone then n = n + 1 else table.insert(kept, f) end
    end
    if room and #kept >= FLOORS_MAX then
        local oldest, at
        for i, f in ipairs(kept) do
            if empty_floor(f) then
                local t = newest_mark(f) or -math.huge
                if oldest == nil or t < oldest then oldest, at = t, i end
            end
        end
        if at then table.remove(kept, at); n = n + 1 end
    end
    if n > 0 then
        for k in pairs(store.floors) do store.floors[k] = nil end
        for i, f in ipairs(kept) do store.floors[i] = f end
    end
    return n
end

-- The floor on level z that hangs on the stair at (sx, sy). With no stair
-- given: the first floor on that level.
function find_floor(store, z, sx, sy)
    if not usable(store) then return nil end
    for _, f in ipairs(store.floors) do
        if type(f) == 'table' and f.z == z then
            local st = type(f.stair) == 'table' and f.stair or {}
            if (sx == nil and sy == nil) or (st.x == sx and st.y == sy) then return f end
        end
    end
    return nil
end

-- A floor's empty record. NOT inserted and store.next not moved: commit (or
-- mark_full) does both, so a placement that fails leaves no trace.
function new_floor(store, z, sx, sy, tick)
    local id = (type(store) == 'table' and is_num(store.next)) and store.next or 1
    return {id = id, z = z, stair = {x = sx, y = sy}, made = tick, hub = 'found',
            runs = {}, slots = {}, full = {}}
end

-- ---------------------------------------------------------------- the grammar

local function word_list(v, ok, default)
    local out, seen = {}, {}
    if type(v) == 'table' then
        for _, w in ipairs(v) do
            if type(w) == 'string' and ok[w] and not seen[w] then
                seen[w] = true
                table.insert(out, w)
            end
        end
    end
    if #out == 0 then
        for _, w in ipairs(default) do table.insert(out, w) end
    end
    return out
end

-- The floor grammar from the brain's hint: every key optional, unknown keys
-- dropped, a wrong type gives the default, numbers are rounded and clamped.
-- (V3) A short run keeps room for a workshop and one pile room on a side:
-- lead, ahead and gap give way, pile_w is capped (brain/floor_grammar.py
-- does the same). Takes nil and any junk.
function grammar(hint)
    if type(hint) ~= 'table' then hint = {} end
    local G = {}
    for key, r in pairs(NUMBERS) do
        G[key] = clamp(hint[key], r[1], r[2], r[3])
    end
    -- a run can never be opened when it must be longer than a run may be
    if G.run_min > G.run_max then G.run_min = G.run_max end
    -- bay: 0 (no rhythm) or 3-6
    local bay = hint.bay
    if not is_num(bay) then
        G.bay = 0
    else
        bay = whole(bay)
        G.bay = (bay <= 0) and 0 or math.max(3, math.min(6, bay))
    end
    -- node: 3 or 5
    G.node = (is_num(hint.node) and whole(hint.node) >= 5) and 5 or 3
    for key, ok in pairs(WORDS) do
        local w = hint[key]
        G[key] = (type(w) == 'string' and ok[w] and w ~= 'default') and w or ok.default
    end
    for _, key in ipairs(BOOLS) do
        G[key] = (hint[key] == true)
    end
    -- (V3) one side of a full run holds a workshop (5 columns) and one pile room (pile_w, 5 at
    -- least) with the gap between: the lead gives way first, then what is kept ahead, then the gap;
    -- the pile room is no wider than what is left beside the shop
    local function room() return G.run_max - G.lead - G.ahead - (G.neck and 1 or 0) end
    while room() < SHOP_COLS + G.gap + PILE_COLS do
        if G.lead > 0 then G.lead = G.lead - 1
        elseif G.ahead > 0 then G.ahead = G.ahead - 1
        elseif G.gap > 1 then G.gap = G.gap - 1
        else break end
    end
    local wide = room() - SHOP_COLS - G.gap
    if G.pile_w > wide then G.pile_w = math.max(NUMBERS.pile_w[1], wide) end
    G.dirs = word_list(hint.dirs, IS_COMPASS, COMPASS)
    G.grow = word_list(hint.grow, {turn = true, arm = true}, {'arm', 'turn'})
    for _, key in ipairs(PASSED) do
        G[key] = hint[key]
    end
    return G
end

-- ---------------------------------------------------------------- commit

local RUN_KEYS = {'id', 'parent', 'ox', 'oy', 'dx', 'dy', 'len', 'walked', 'tag', 'node', 'neck', 'closed'}

-- Write a finished placement (ai-floorplace.place's answer) into the record
-- for project `pid`: new runs appended, lengthened runs given their new len
-- (the len before is remembered for release), every put a slot, an axial put
-- closing its run. A floor not in the store yet is inserted. Returns the
-- store's floor record, or nil, why with nothing changed.
function commit(store, floor, placement, pid, tick)
    if not usable(store) then return nil, 'no floor store' end
    if type(floor) ~= 'table' then return nil, 'no floor' end
    if type(placement) ~= 'table' then return nil, 'no placement' end
    local rec = own_record(store, floor)
    local target = rec or floor
    local puts, prun = list_of(placement.puts), list_of(placement.runs)

    -- everything is checked before anything is written
    if not rec and not room_for(store) then return nil, 'floor record full' end
    local runs_now, added, known = list_of(target.runs), 0, {}
    for _, r in ipairs(runs_now) do
        if type(r) == 'table' then known[r.id] = true end
    end
    for _, r in ipairs(prun) do
        if type(r) ~= 'table' or not is_num(r.id) then return nil, 'bad placement: a run with no id' end
        if not known[r.id] then
            if not compass(r.dx, r.dy) then return nil, 'bad placement: a run with no direction' end
            known[r.id] = true
            added = added + 1
        end
    end
    if #runs_now + added > RUNS_MAX then return nil, 'floor record full' end
    for _, p in ipairs(puts) do
        if type(p) ~= 'table' or not known[p.run] then return nil, 'bad placement: a slot on no run' end
        -- (an axial put closes the run's end: ai-floorplace gives it side 0)
        if not (is_num(p.u) and is_num(p.w) and is_num(p.d))
            or (p.side ~= 1 and p.side ~= -1 and not (p.axial == true and p.side == 0)) then
            return nil, 'bad placement: a slot with no place'
        end
    end
    if #list_of(target.slots) + #puts > SLOTS_MAX then return nil, 'floor record full' end

    if not rec then
        -- (F2, V2) the floors that are only marks make way (room_for said one can)
        if #store.floors >= FLOORS_MAX then prune(store, tick, nil, true) end
        if not is_num(floor.made) then floor.made = tick end
        rec = insert_floor(store, floor)
    end
    if type(rec.runs) ~= 'table' then rec.runs = {} end
    if type(rec.slots) ~= 'table' then rec.slots = {} end
    if type(rec.full) ~= 'table' then rec.full = {} end

    local key = tostring(pid)
    for _, r in ipairs(prun) do
        local run = find_run(rec, r.id)
        local before
        if run then
            before = is_num(r.len_before) and r.len_before or (run.len or 0)
            if is_num(r.len) and r.len > (run.len or 0) then run.len = r.len end
            -- (B16) a released run (its project cancelled) that a new placement uses is open again
            if run.closed == 'released' and r.closed ~= 'released' then run.closed = r.closed end
        else
            run = {}
            for _, k in ipairs(RUN_KEYS) do run[k] = r[k] end
            run.parent = is_num(r.parent) and r.parent or 0
            run.ox, run.oy = is_num(r.ox) and r.ox or 0, is_num(r.oy) and r.oy or 0
            run.len = is_num(r.len) and r.len or 0
            run.walked = is_num(r.walked) and r.walked or 0
            run.node = (r.node == 5 and run.parent ~= 0) and 5 or 3
            run.neck = (r.neck == true)
            run.pid = pid
            before = is_num(r.len_before) and r.len_before or 0
            table.insert(rec.runs, run)
        end
        if before < (run.len or 0) then
            if type(run.grew) ~= 'table' then run.grew = {} end
            -- a project that lengthens a run twice goes back to its first length
            if not is_num(run.grew[key]) or before < run.grew[key] then run.grew[key] = before end
        end
    end

    local req = type(placement.req) == 'table' and placement.req or {}
    for _, p in ipairs(puts) do
        local slot = {run = p.run, side = p.side, u = p.u, w = p.w, d = p.d, pid = pid,
                      kind = req.kind, tag = req.tag, group = req.group, role = p.role, flag = p.flag}
        if p.axial == true then
            slot.axial = true
            if type(p.rect) == 'table' and is_num(p.rect.x1) and is_num(p.rect.y1)
                and is_num(p.rect.x2) and is_num(p.rect.y2) then
                slot.rect = {x1 = p.rect.x1, y1 = p.rect.y1, x2 = p.rect.x2, y2 = p.rect.y2}
            end
            find_run(rec, p.run).closed = 'terminus'
        end
        table.insert(rec.slots, slot)
    end

    for _, t in ipairs(list_of(placement.hall)) do
        if type(t) == 'table' and is_num(t.x) and is_num(t.y)
            and math.abs(t.x) <= 1 and math.abs(t.y) <= 1 then
            rec.hub = 'dug'
        end
    end
    if rec.hub ~= 'dug' then rec.hub = 'found' end
    if req.tag ~= nil then rec.full[req.tag] = nil end
    if type(rec.full_size) == 'table' then             -- (r3 g2) the size goes with its mark
        if req.tag ~= nil then rec.full_size[req.tag] = nil end
        if next(rec.full_size) == nil then rec.full_size = nil end
    end
    rec.full['*'] = nil       -- a hall did start here
    return rec
end

-- ---------------------------------------------------------------- release

-- The hall column of `run` that the run `child` turns off needs: the far edge
-- of the child's node.
local function child_column(run, child)
    local u = ((child.ox or 0) - (run.ox or 0)) * (run.dx or 0) + ((child.oy or 0) - (run.oy or 0)) * (run.dy or 0)
    return u + half_of(child)
end

-- A cancelled project: every slot of it is marked dead and stays (the place
-- is never dug again); each run it lengthened goes back to the length before,
-- but never below what a live slot of another project (with one column
-- ahead) or a run turning off it needs, nor below its walked columns; a run
-- it made that holds nothing live is closed ('released'). Returns the number
-- of slots marked.
function release(store, pid)
    if not usable(store) or pid == nil then return 0 end
    local key, n = tostring(pid), 0
    for _, floor in ipairs(store.floors) do
        if type(floor) == 'table' then
            local slots, runs = list_of(floor.slots), list_of(floor.runs)
            for _, s in ipairs(slots) do
                if type(s) == 'table' and same_pid(s.pid, pid) and not s.dead then
                    s.dead = true
                    n = n + 1
                end
            end
            -- children were appended after their parents: last first, so a
            -- run knows which of its turnings are still there
            for i = #runs, 1, -1 do
                local run = runs[i]
                local grew = type(run) == 'table' and type(run.grew) == 'table' and run.grew[key] or nil
                if type(run) == 'table' and (grew ~= nil or same_pid(run.pid, pid)) then
                    local u0 = u0_of(run)
                    local need, live = 0, false
                    for _, s in ipairs(slots) do
                        if type(s) == 'table' and s.run == run.id and not s.dead then
                            live = true
                            -- an axial slot's wall is the column after the hall's last
                            local col = s.axial and (s.u - 1) or (s.u + s.w - 1 + 1)
                            need = math.max(need, col - u0 + 1)
                        end
                    end
                    for _, c in ipairs(runs) do
                        if type(c) == 'table' and c.parent == run.id and c.closed ~= 'released' then
                            live = true
                            need = math.max(need, child_column(run, c) - u0 + 1)
                        end
                    end
                    local len = run.len or 0
                    local back = len
                    if is_num(grew) then
                        back = math.min(back, grew)
                        run.low = math.min(is_num(run.low) and run.low or grew, grew)
                        run.grew[key] = nil
                        if next(run.grew) == nil then run.grew = nil end
                    end
                    if is_num(run.low) then back = math.min(back, run.low) end
                    run.len = math.min(len, math.max(back, need, run.walked or 0))
                    if same_pid(run.pid, pid) and not live and run.closed ~= 'terminus' then
                        run.closed = 'released'
                    end
                end
            end
        end
    end
    return n
end

-- ---------------------------------------------------------------- mark_full

-- No room on this floor for `tag` ('*': no hall can start on this level at
-- all), as of `tick`. A floor not in the store yet gets its record (a level
-- with no hall still has one: '*', no runs). `free`, when given, is the free
-- run each way as just measured. Returns the store's record, or nil, why.
-- (r3 g2) `size` ({w, d, n}: the refused level's widest and deepest unit and
-- its count), when given, is kept in full_size[tag]: a smaller level is
-- still tried there; a mark with no size clears it (full for any level).
function mark_full(store, floor, tag, tick, free, size)
    if not usable(store) then return nil, 'no floor store' end
    if type(floor) ~= 'table' then return nil, 'no floor' end
    local rec = own_record(store, floor)
    if not rec then
        -- (F2, V2) a mark never pushes the record past FLOORS_MAX: the expired
        -- marks go first, and if it is still full this mark is dropped
        if #store.floors >= FLOORS_MAX then prune(store, tick) end
        if #store.floors >= FLOORS_MAX then return nil, 'floor record full' end
        if not is_num(floor.made) then floor.made = tick end
        rec = insert_floor(store, floor)
    end
    if type(rec.full) ~= 'table' then rec.full = {} end
    if type(tag) ~= 'string' or tag == '' then tag = '*' end
    rec.full[tag] = tick
    if type(size) == 'table' and tag ~= '*' then
        if type(rec.full_size) ~= 'table' then rec.full_size = {} end
        rec.full_size[tag] = {w = clamp(size.w, 0, 999, 0), d = clamp(size.d, 0, 999, 0), n = clamp(size.n, 0, 999, 0)}
    elseif type(rec.full_size) == 'table' then
        rec.full_size[tag] = nil
        if next(rec.full_size) == nil then rec.full_size = nil end
    end
    if type(free) == 'table' then
        local kept = {tick = tick}
        for _, dir in ipairs(COMPASS) do
            kept[dir] = is_num(free[dir]) and free[dir] or 0
        end
        rec.free = kept
    end
    return rec
end

-- ---------------------------------------------------------------- claims

-- Every tile the floor holds, stair-relative: tiles[x][y] = true. The hub
-- (the 8 tiles round the stair, never the stair), every run's node and hall,
-- every slot's wall row and rooms (the dead ones too).
function claims(floor)
    local tiles = {}
    if type(floor) ~= 'table' then return tiles end
    local function add(x, y)
        if x == 0 and y == 0 then return end
        if not tiles[x] then tiles[x] = {} end
        tiles[x][y] = true
    end
    for x = -1, 1 do
        for y = -1, 1 do add(x, y) end
    end
    local by_id = {}
    for _, run in ipairs(list_of(floor.runs)) do
        if type(run) == 'table' and compass(run.dx, run.dy) then
            by_id[run.id] = run
            local ox, oy, dx, dy = run.ox or 0, run.oy or 0, run.dx, run.dy
            local px, py = -dy, dx
            local h, u0 = half_of(run), u0_of(run)
            if is_hub_run(run) then h = 1 end
            for u = -h, h do
                for v = -h, h do add(ox + u * dx + v * px, oy + u * dy + v * py) end
            end
            for u = u0, u0 + (run.len or 0) - 1 do
                if run.neck and u == u0 then
                    add(ox + u * dx, oy + u * dy)
                else
                    for v = -1, 1 do add(ox + u * dx + v * px, oy + u * dy + v * py) end
                end
            end
        end
    end
    for _, s in ipairs(list_of(floor.slots)) do
        local run = type(s) == 'table' and by_id[s.run] or nil
        if run and is_num(s.u) and is_num(s.w) and is_num(s.d) then
            local ox, oy, dx, dy = run.ox or 0, run.oy or 0, run.dx, run.dy
            local px, py = -dy, dx
            if s.axial and type(s.rect) == 'table' then
                for x = s.rect.x1, s.rect.x2 do
                    for y = s.rect.y1, s.rect.y2 do add(x, y) end
                end
            elseif s.axial then
                -- across the hall's end: the wall at u, the rooms d deep
                -- behind it, w wide about v = 0
                local v0 = -math.floor(s.w / 2)
                for u = s.u, s.u + s.d do
                    for v = v0, v0 + s.w - 1 do add(ox + u * dx + v * px, oy + u * dy + v * py) end
                end
            else
                local side = (s.side == 1) and 1 or -1
                for u = s.u, s.u + s.w - 1 do
                    for k = 2, 2 + s.d do
                        local v = k * side
                        add(ox + u * dx + v * px, oy + u * dy + v * py)
                    end
                end
            end
        end
    end
    return tiles
end

-- ---------------------------------------------------------------- summary

local function sorted_keys(set)
    local out = {}
    for k in pairs(set) do table.insert(out, k) end
    table.sort(out)
    return out
end

-- The rows of the report's `list`, one a floor: every key but `others` and
-- `old_boxes` (the caller adds those from the project records).
--   ez          function(z) -> elevation
--   now         the game tick; a mark counts while it is younger than
--               retry_days (default 28) x 1200 ticks
function summary(store, ez, now, retry_days)
    local rows = {}
    if not usable(store) then return rows end
    local span = (is_num(retry_days) and retry_days > 0 and retry_days or 28) * DAY
    local function fresh(tick)
        if not is_num(tick) then return false end
        if not is_num(now) then return true end
        return now - tick < span
    end
    for _, floor in ipairs(store.floors) do
        if type(floor) == 'table' then
            local runs, slots = list_of(floor.runs), list_of(floor.slots)
            local full_marks = type(floor.full) == 'table' and floor.full or {}
            local elevation = nil
            if type(ez) == 'function' then
                local ok, e = pcall(ez, floor.z)
                if ok then elevation = e end
            end
            local stair = type(floor.stair) == 'table' and floor.stair or {}
            local row = {id = floor.id, elevation = elevation, z = floor.z,
                         stair = {x = stair.x, y = stair.y},
                         hub = (floor.hub == 'dug') and 'dug' or 'found',
                         width = 3, rooms = 0, hall = 0, kinds = {}, arms = {}}

            -- which hub run each run hangs on (itself for a hub run)
            local by_id, n_runs = {}, 0
            for _, r in ipairs(runs) do
                if type(r) == 'table' then
                    by_id[r.id] = r
                    n_runs = n_runs + 1
                end
            end
            local function root_of(run)
                local seen = 0
                while run and not is_hub_run(run) and seen <= RUNS_MAX do
                    run = by_id[run.parent]
                    seen = seen + 1
                end
                if run and is_hub_run(run) then return run end
                return nil
            end

            local tags, arm_of = {}, {}
            for _, r in ipairs(runs) do
                if type(r) == 'table' then
                    row.hall = row.hall + 3 * (is_num(r.len) and r.len or 0)
                    if type(r.tag) == 'string' and r.closed ~= 'released' then tags[r.tag] = true end
                    if is_hub_run(r) then
                        local arm = {dir = compass(r.dx, r.dy), len = 0, runs = 0, tag = r.tag,
                                     slots = 0, closed = r.closed}
                        arm_of[r.id] = arm
                        table.insert(row.arms, arm)
                    end
                end
            end
            for _, r in ipairs(runs) do
                local root = type(r) == 'table' and root_of(r) or nil
                local arm = root and arm_of[root.id] or nil
                if arm then
                    arm.len = arm.len + (is_num(r.len) and r.len or 0)
                    arm.runs = arm.runs + 1
                end
            end
            for _, s in ipairs(slots) do
                if type(s) == 'table' then
                    local root = by_id[s.run] and root_of(by_id[s.run]) or nil
                    local arm = root and arm_of[root.id] or nil
                    -- a dead slot is still a slot taken on its arm
                    if arm then arm.slots = arm.slots + 1 end
                    if not s.dead then
                        row.rooms = row.rooms + 1
                        local kind = (s.role == 'pile') and 'pile' or s.kind
                        if type(kind) == 'string' then row.kinds[kind] = (row.kinds[kind] or 0) + 1 end
                        if type(s.tag) == 'string' then tags[s.tag] = true end
                    end
                end
            end
            row.tags = sorted_keys(tags)

            local full = {}
            for tag, tick in pairs(full_marks) do
                if tag ~= '*' and type(tag) == 'string' and fresh(tick) then full[tag] = true end
            end
            row.full = sorted_keys(full)
            -- (r3 g1) a dead floor (no hall left) marked '*' is a level no hall can start on, too
            local dead = dead_floor(floor)
            row.no_hall = ((n_runs == 0 or dead) and fresh(full_marks['*'])) and true or false
            if dead then row.dead = true end

            if type(floor.free) == 'table' then
                row.free = {tick = floor.free.tick}
                for _, dir in ipairs(COMPASS) do
                    row.free[dir] = is_num(floor.free[dir]) and floor.free[dir] or 0
                end
            end
            table.insert(rows, row)
        end
    end
    return rows
end
