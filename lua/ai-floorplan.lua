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

-- nil / {} / junk / no whole v -> a new store (changed = true). A newer store
-- comes back untouched with changed = false, why = 'newer': callers then only
-- read it. A v1 store that lost a part (hand-edited, half-written) is mended
-- in place (changed = true, why = 'repaired'). Never throws.
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
    local kept, dropped = {}, false
    for _, f in ipairs(store.floors) do
        if type(f) == 'table' and is_num(f.id) and is_num(f.z) then
            if type(f.stair) ~= 'table' then f.stair = {}; changed = true end
            if type(f.runs) ~= 'table' then f.runs = {}; changed = true end
            if type(f.slots) ~= 'table' then f.slots = {}; changed = true end
            if type(f.full) ~= 'table' then f.full = {}; changed = true end
            table.insert(kept, f)
        else
            dropped = true
        end
    end
    if dropped or #kept ~= #store.floors then
        -- a list with a hole or a junk row: rebuilt dense
        for k in pairs(store.floors) do store.floors[k] = nil end
        for i, f in ipairs(kept) do store.floors[i] = f end
        changed = true
    end
    local top = max_id(store)
    if not is_num(store.next) or store.next <= top then store.next = top + 1; changed = true end
    if not is_num(store.fallbacks) then store.fallbacks = 0; changed = true end
    if changed then return store, true, 'repaired' end
    return store, false, nil
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
-- Takes nil and any junk.
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
    if not rec and #store.floors >= FLOORS_MAX then return nil, 'floor record full' end
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
function mark_full(store, floor, tag, tick, free)
    if not usable(store) then return nil, 'no floor store' end
    if type(floor) ~= 'table' then return nil, 'no floor' end
    local rec = own_record(store, floor)
    if not rec then
        if #store.floors >= FLOORS_MAX then return nil, 'floor record full' end
        if not is_num(floor.made) then floor.made = tick end
        rec = insert_floor(store, floor)
    end
    if type(rec.full) ~= 'table' then rec.full = {} end
    if type(tag) ~= 'string' or tag == '' then tag = '*' end
    rec.full[tag] = tick
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
            row.no_hall = (n_runs == 0 and fresh(full_marks['*'])) and true or false

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
