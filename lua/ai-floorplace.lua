-- Where things go on one floor (layout B, hallway-first floors): pure
-- functions, no game access.
--
-- A floor is one z-level with a 3-wide main hall running out from the central
-- stair. Given the floor's record (ai-floorplan's shape: runs, slots, hub), a
-- request (some {w, d} boxes), the grammar G (already clamped) and `env` (the
-- caller's eyes on the map), `place` decides which way the hall can run,
-- which slot each box gets, and when the hall is lengthened, turned or given
-- another arm. It changes nothing: it answers a placement, or nil and why.
-- ai-floorplan.commit writes a placement into the record; ai-floorunits turns
-- it into dig cells.
--
-- Everything is in stair-relative tiles: (0, 0) the stair, +x east, +y south.
--   run    {id, parent, ox, oy, dx, dy, len, tag, node, neck, closed, walked}
--          (u, v) -> (ox + u*dx + v*px, oy + u*dy + v*py), p = (-dy, dx);
--          the hall is u = u0 .. u0 + len - 1, v = -1 .. 1 (u0 = 2; 3 after a
--          5x5 node); the node is the 3x3 round the origin
--   slot   {run, side, u, w, d}: columns u .. u + w - 1, the wall row
--          v = 2*side, the room v = 3*side .. (2 + d)*side. An axial slot
--          (side = 0) closes a run's end: wall row u = E + 1, rooms beyond
--
-- What is kept apart (the bookkeeping, before the map is asked):
--   a slot keeps one tile of rock from everything of the floor except its own
--   run's hall and the 3x3 node that hall starts from; new hall keeps one
--   tile from every slot that is not its own run's, and from other halls
--   except round its own node.
--
-- Tested with tests/test_b2_floorplace.py.
--@ module = true

SURVEY_MAX = 60

local SLOTS_MAX = 160          -- ai-floorplan's limits a floor
local RUNS_MAX = 24
local TURN_REACH = 7           -- columns a run may be lengthened by to make room for a turn's node
local PLANS_MAX = 200          -- plans tried in one call (each failed one has spent a probe)

local DIRS = {east = {1, 0}, south = {0, 1}, west = {-1, 0}, north = {0, -1}}
local DIR_ORDER = {'east', 'south', 'west', 'north'}
local SAY_ORDER = {'north', 'east', 'south', 'west'}

local function dir_name(dx, dy)
    for _, n in ipairs(DIR_ORDER) do
        if DIRS[n][1] == dx and DIRS[n][2] == dy then return n end
    end
    return '?'
end

-- ---------------------------------------------------------------- geometry

local function tile(run, u, v)
    return run.ox + u * run.dx + v * run.px, run.oy + u * run.dy + v * run.py
end

-- the tile box of the run-frame box u1..u2, v1..v2
local function box_uv(run, u1, v1, u2, v2)
    local xa, ya = tile(run, u1, v1)
    local xb, yb = tile(run, u2, v2)
    if xa > xb then xa, xb = xb, xa end
    if ya > yb then ya, yb = yb, ya end
    return xa, ya, xb, yb
end

local function run_end(run) return run.u0 + run.len - 1 end

local function in_bounds(env, x1, y1, x2, y2)
    local b = env.bounds
    if type(b) ~= 'table' then return true end
    return x1 >= b.x1 and y1 >= b.y1 and x2 <= b.x2 and y2 <= b.y2
end

-- a hall column's three tiles: 'rock' (all to dig), 'open' (all the fort's
-- own floor), 'mixed' (some of each), or nil when one is 'bad'
local function column_state(env, run, u)
    local rock, open = 0, 0
    for v = -1, 1 do
        local x, y = tile(run, u, v)
        local s = env.open(x, y)
        if s == 'rock' then rock = rock + 1 elseif s == 'open' then open = open + 1 else return nil end
    end
    if open == 0 then return 'rock' elseif rock == 0 then return 'open' end
    return 'mixed'
end

-- ---------------------------------------------------------------- survey

local function survey_dir(env, dx, dy)
    local run = {ox = 0, oy = 0, dx = dx, dy = dy, px = -dy, py = dx}
    local n = 0
    for u = 2, 1 + SURVEY_MAX do
        local x1, y1, x2, y2 = box_uv(run, u, -1, u, 1)
        if not in_bounds(env, x1, y1, x2, y2) then break end
        if not column_state(env, run, u) then break end
        if env.blocked(x1, y1, x2, y2) then break end
        n = n + 1
    end
    return n
end

-- The free run each way from the stair's hub: the hall columns (u = 2 on)
-- whose three tiles are each 'rock' or 'open' and whose 3-wide column is not
-- env.blocked (nor outside env.bounds), to the first that fails.
function survey(floor, G, env)
    local free = {}
    for _, n in ipairs(DIR_ORDER) do free[n] = survey_dir(env, DIRS[n][1], DIRS[n][2]) end
    return free
end

-- ---------------------------------------------------------------- the shadow floor
-- A working copy of the floor's runs and slots that a plan adds to; the
-- floor's own tables are only read.

local function bump(S) S.ver = S.ver + 1 end

local function set_hall(run)
    local h = run.hall
    if run.len <= 0 then
        h.off = true
    else
        h.off = false
        h.x1, h.y1, h.x2, h.y2 = box_uv(run, run.u0, -1, run_end(run), 1)
    end
end

local function add_run(S, r)
    r.px, r.py = -r.dy, r.dx
    r.u0 = (r.node == 5) and 3 or 2
    r.ss = {[-1] = {}, [1] = {}}
    r.kids = {}
    r.nkids = 0
    r.core = {}
    r.core.x1, r.core.y1, r.core.x2, r.core.y2 = r.ox - 1, r.oy - 1, r.ox + 1, r.oy + 1
    r.hall = {t = 'hall', run = r.id}
    set_hall(r)
    table.insert(S.fixed, r.hall)
    if r.node == 5 then
        r.nodeob = {t = 'node', run = r.id, x1 = r.ox - 2, y1 = r.oy - 2, x2 = r.ox + 2, y2 = r.oy + 2}
        table.insert(S.fixed, r.nodeob)
    end
    -- the slots that can matter to this run: those within its band (kept as slots are added)
    local far = r.u0 + math.max(r.len, S.run_max) + TURN_REACH + S.dmax + 6
    local wide = S.dmax + 5
    local b = {}
    b.x1, b.y1, b.x2, b.y2 = box_uv(r, -5, -wide, far, wide)
    r.band = b
    r.near = {}
    for _, o in ipairs(S.slots) do
        if o.x1 <= b.x2 and o.x2 >= b.x1 and o.y1 <= b.y2 and o.y2 >= b.y1 then table.insert(r.near, o) end
    end
    table.insert(S.runs, r)
    S.byid[r.id] = r
    if r.id >= S.next_id then S.next_id = r.id + 1 end
    if r.orphan then
        r.depth = math.abs(r.ox) + math.abs(r.oy)
    elseif r.parent == 0 then
        S.hub_runs = S.hub_runs + 1
        S.dir_used[dir_name(r.dx, r.dy)] = true
        r.depth = 0
    else
        local p = S.byid[r.parent]
        if p then
            local side = (r.dx == p.px and r.dy == p.py) and 1 or -1
            if not p.kids[side] then p.kids[side] = r; p.nkids = p.nkids + 1 end
            r.pside = side
            r.depth = p.depth + math.abs((r.ox - p.ox) * p.dx + (r.oy - p.oy) * p.dy)
        else
            r.depth = math.abs(r.ox) + math.abs(r.oy)
        end
    end
    bump(S)
    return r
end

local function add_slot(S, run, s)
    if s.axial then
        local c0 = s.c0
        local va, vb = -(s.w - 1), s.w - 1          -- a recorded one: its opening's column is not kept
        if c0 then va, vb = -c0, s.w - 1 - c0 end
        s.x1, s.y1, s.x2, s.y2 = box_uv(run, s.u, va, s.u + s.d, vb)
        run.axial = s
    else
        s.e = s.u + s.w - 1
        s.x1, s.y1, s.x2, s.y2 = box_uv(run, s.u, 2 * s.side, s.e, (2 + s.d) * s.side)
        table.insert(run.ss[s.side], s)
        run.last_side = s.side
    end
    s.t = 'slot'
    s.runid = run.id
    table.insert(S.slots, s)
    for _, r in ipairs(S.runs) do
        local b = r.band
        if s.x1 <= b.x2 and s.x2 >= b.x1 and s.y1 <= b.y2 and s.y2 >= b.y1 then table.insert(r.near, s) end
    end
    bump(S)
    return s
end

local function shadow(floor, run_max, dmax)
    local S = {runs = {}, byid = {}, slots = {}, fixed = {}, ver = 0, hub_runs = 0, dir_used = {}, next_id = 1,
               run_max = run_max, dmax = dmax}
    table.insert(S.fixed, {t = 'hub', x1 = -1, y1 = -1, x2 = 1, y2 = 1})
    local runs = type(floor.runs) == 'table' and floor.runs or {}
    local slots = type(floor.slots) == 'table' and floor.slots or {}
    -- parents before children, whatever the record's order
    local todo, left = {}, 0
    for _, r in ipairs(runs) do
        if type(r) == 'table' and r.id then table.insert(todo, r); left = left + 1 end
    end
    local moved = true
    while left > 0 and moved do
        moved = false
        for i, r in ipairs(todo) do
            if r and ((r.parent or 0) == 0 or S.byid[r.parent]) then
                local turning = (r.parent or 0) ~= 0
                -- (B16) a run ai-floorplan.release closed ('released': its project was cancelled, nothing
                -- live on it) is open again: its direction (and its place on the parent) is not lost for
                -- good; its dead slots stay where they are, and new slots go past them
                local closed = r.closed
                if closed == 'released' then closed = nil end
                add_run(S, {id = r.id, key = tostring(r.id), parent = r.parent or 0, ox = r.ox or 0, oy = r.oy or 0,
                            dx = r.dx or 1, dy = r.dy or 0, len = r.len or 0, len0 = r.len or 0, new = false,
                            tag = r.tag, node = (turning and r.node == 5) and 5 or 3,
                            neck = r.neck and true or false, closed = closed, closed0 = closed,
                            walked = r.walked or 0})
                todo[i] = false
                left = left - 1
                moved = true
            end
        end
    end
    for _, r in ipairs(todo) do            -- a run whose parent is gone: still solid ground
        if r then
            add_run(S, {id = r.id, key = tostring(r.id), parent = 0, ox = r.ox or 0, oy = r.oy or 0,
                        dx = r.dx or 1, dy = r.dy or 0, len = r.len or 0, len0 = r.len or 0, new = false,
                        tag = r.tag, node = 3, neck = r.neck and true or false, closed = r.closed or 'orphan',
                        closed0 = r.closed, walked = r.walked or 0, orphan = true})
        end
    end
    for _, s in ipairs(slots) do
        local run = type(s) == 'table' and S.byid[s.run]
        if run and s.u and s.w and s.d then
            local axial = s.axial == true or s.side == 0
            add_slot(S, run, {side = axial and 0 or ((s.side == 1) and 1 or -1), u = s.u, w = s.w, d = s.d,
                              kind = s.kind, group = s.group, axial = axial, c0 = s.c0, old = true})
        end
    end
    return S
end

-- ---------------------------------------------------------------- clearance

-- May a slot's box (wall row and rooms) stand here? One tile of rock from
-- everything but the run's own hall and the 3x3 node it starts from.
local function slot_clear(S, run, x1, y1, x2, y2)
    local ex1, ey1, ex2, ey2 = x1 - 1, y1 - 1, x2 + 1, y2 + 1
    local c = run.core
    local own = run.hall
    for _, o in ipairs(run.near) do
        if o.x1 <= ex2 and o.x2 >= ex1 and o.y1 <= ey2 and o.y2 >= ey1 then return false end
    end
    for _, o in ipairs(S.fixed) do
        if o ~= own and not o.off and o.x1 <= ex2 and o.x2 >= ex1 and o.y1 <= ey2 and o.y2 >= ey1 then
            -- what of it lies within a tile of the box: all inside the own node?
            local ix1 = o.x1 > ex1 and o.x1 or ex1
            local iy1 = o.y1 > ey1 and o.y1 or ey1
            local ix2 = o.x2 < ex2 and o.x2 or ex2
            local iy2 = o.y2 < ey2 and o.y2 or ey2
            if not (ix1 >= c.x1 and iy1 >= c.y1 and ix2 <= c.x2 and iy2 <= c.y2) then return false end
        end
    end
    return true
end

-- May these tiles become hall (or a node) of `run`? `pad`: how far round the
-- run's origin another hall may be met (the node and a tile round it).
local function hall_clear(S, run, x1, y1, x2, y2, pad, also)
    local ex1, ey1, ex2, ey2 = x1 - 1, y1 - 1, x2 + 1, y2 + 1
    local zx1, zy1, zx2, zy2 = run.ox - pad, run.oy - pad, run.ox + pad, run.oy + pad
    local own = run.hall
    local id = run.id
    for _, o in ipairs(run.near) do
        if (o.runid ~= id or o.axial) and o.x1 <= ex2 and o.x2 >= ex1 and o.y1 <= ey2 and o.y2 >= ey1 then
            return false
        end
    end
    local nodeob = run.nodeob
    for _, o in ipairs(S.fixed) do
        if o ~= own and o ~= also and o ~= nodeob and not o.off
                and o.x1 <= ex2 and o.x2 >= ex1 and o.y1 <= ey2 and o.y2 >= ey1 then
            local ix1 = o.x1 > ex1 and o.x1 or ex1
            local iy1 = o.y1 > ey1 and o.y1 or ey1
            local ix2 = o.x2 < ex2 and o.x2 or ex2
            local iy2 = o.y2 < ey2 and o.y2 or ey2
            if not (ix1 >= zx1 and iy1 >= zy1 and ix2 <= zx2 and iy2 <= zy2) then return false end
        end
    end
    return true
end

-- One more hall column of `run`, by the bookkeeping and the cheap callbacks.
local function col_ok(C, S, run, u)
    local lim = C.limit[run.key]
    if lim and u > lim then return false end
    local env = C.env
    local x1, y1, x2, y2 = box_uv(run, u, -1, u, 1)
    if not in_bounds(env, x1, y1, x2, y2) then return false end
    if not hall_clear(S, run, x1, y1, x2, y2, run.node == 5 and 3 or 2) then return false end
    if not column_state(env, run, u) then return false end
    if env.blocked(x1, y1, x2, y2) then return false end
    return true
end

local function cap_of(C, run)
    local e = run_end(run)
    if run.nkids > 0 or run.closed then return e end      -- a run something turns off, or a closed one, has its length
    local cap = run.u0 + C.G.run_max - 1
    if cap < e then cap = e end
    return cap
end

-- The farthest column the run's hall can be lengthened to.
local function reach(C, S, run)
    if run.reach_ver == S.ver then return run.reach end
    local cap = cap_of(C, run)
    local c = run_end(run)
    while c < cap and col_ok(C, S, run, c + 1) do c = c + 1 end
    run.reach, run.reach_ver = c, S.ver
    return c
end

-- ---------------------------------------------------------------- one item on one run
-- An item is the units placed in one go, side by side in one row: one unit,
-- one of a request's `clusters` (a workshop and its pile rooms), or a
-- `together` request's whole row when it names no clusters.

local function differs(C, s)
    local q = C.req
    if s.kind ~= q.kind then return true end
    return q.kind == 'workshops' and s.group ~= q.group
end

local function refused_key(run, side, u, item)
    return run.key .. '|' .. side .. '|' .. item.sig .. '|' .. u
end

-- every tile of the box and of the ring round it (but the row on the hall's
-- side) is untouched rock: a room touches nothing open but its own hall
local function rock_box(env, run, side, ua, ub, d)
    for u = ua - 1, ub + 1 do
        for r = 2, 3 + d do
            local x, y = tile(run, u, r * side)
            if env.open(x, y) ~= 'rock' then return false end
        end
    end
    return true
end

-- Does the item fit at column u on this side? -> positions | nil, next u to try
local function fits(C, S, run, side, u, item, cap)
    local G, env = C.G, C.env
    local list = run.ss[side]
    local before = 0
    for _, s in ipairs(list) do if s.u < u then before = before + 1 end end
    local function beat(k)          -- the k-th slot on the side (k from 1) starts a new bay
        return (G.bay > 0 and k > 1 and (k - 1) % G.bay == 0) and 1 or 0
    end
    -- where each unit stands
    local pos, at = {}, u
    for j, unit in ipairs(item.units) do
        if j > 1 then at = at + G.gap + beat(before + j) end
        pos[j] = at
        at = at + unit.w
    end
    local ue = at - 1
    if ue + G.ahead > cap then return nil, math.huge end
    -- its neighbours on the side
    local first_beat = beat(before + 1)
    for _, s in ipairs(list) do
        local g = G.gap + (differs(C, s) and G.kind_gap or 0)
        if s.u < u then
            if u < s.e + 1 + g + first_beat then return nil, s.e + 1 + g + first_beat end
        elseif ue > s.u - 1 - g then
            return nil, s.e + 1 + g
        end
    end
    if C.refused[refused_key(run, side, u, item)] then return nil end
    local min_u = C.req.min_u or 0
    for j, unit in ipairs(item.units) do
        local x1, y1, x2, y2 = box_uv(run, pos[j], 2 * side, pos[j] + unit.w - 1, (2 + unit.d) * side)
        if min_u > 0 then            -- no tile nearer the stair than this
            local nx = (x1 > 0 and x1) or (x2 < 0 and -x2) or 0
            local ny = (y1 > 0 and y1) or (y2 < 0 and -y2) or 0
            if (nx > ny and nx or ny) < min_u then return nil end
        end
        if not in_bounds(env, x1, y1, x2, y2) then return nil end
        if not slot_clear(S, run, x1, y1, x2, y2) then return nil end
    end
    if ue + G.ahead > reach(C, S, run) then return nil, math.huge end
    for j, unit in ipairs(item.units) do
        local x1, y1, x2, y2 = box_uv(run, pos[j], 2 * side, pos[j] + unit.w - 1, (2 + unit.d) * side)
        if env.blocked(x1 - 1, y1 - 1, x2 + 1, y2 + 1) then return nil end
        if not rock_box(env, run, side, pos[j], pos[j] + unit.w - 1, unit.d) then return nil end
    end
    return pos, ue
end

local function scan(C, S, run, side, start, item)
    if C.env.late() then C.late = true; return nil end
    local cap = cap_of(C, run)
    local u = start
    while u + item.wmin - 1 + C.G.ahead <= cap do
        local pos, nxt = fits(C, S, run, side, u, item, cap)
        if pos then return pos, nxt end
        if nxt == math.huge then return nil end
        u = (nxt and nxt > u) and nxt or (u + 1)
    end
    return nil
end

local function set_len(S, run, len)
    run.len = len
    set_hall(run)
    bump(S)
end

-- write the item into the shadow floor
local function take(C, S, run, side, pos, ue, item)
    for j, unit in ipairs(item.units) do
        local s = add_slot(S, run, {side = side, u = pos[j], w = unit.w, d = unit.d, kind = C.req.kind,
                                    group = C.req.group, unit = unit, index = item.index[j],
                                    item = item, item_u = pos[1]})
        table.insert(C.puts, s)
        if C.clusters then C.prev = s end   -- (a cluster request's next item goes on from here first)
    end
    local need = ue + C.G.ahead
    if need > run_end(run) then set_len(S, run, need - run.u0 + 1) end
end

local function side_order(C, run)
    local sides = C.G.sides
    if sides == 'one' then return {-1} end
    if sides == 'alternate' then
        if run.last_side == -1 then return {1, -1} end
        return {-1, 1}
    end
    if #run.ss[1] < #run.ss[-1] then return {1, -1} end
    return {-1, 1}
end

local function first_col(C, run, side)
    local G = C.G
    local u = run.u0 + G.lead + (run.neck and 1 or 0)
    if side == 1 then u = u + G.stagger end
    return u
end

local function try_run_now(C, S, run, item)
    local G, q = C.G, C.req
    -- right after the request's own previous item: its row goes on where it can
    local prev = C.prev
    if prev and prev.runid == run.id and not prev.axial then
        local from = prev.e + 1 + G.gap
        local base = first_col(C, run, prev.side)
        local pos, ue = scan(C, S, run, prev.side, from > base and from or base, item)
        if pos then take(C, S, run, prev.side, pos, ue, item); return true end
        if C.late then return false end
    end
    -- right after the run's last slot of the request's group
    if q.group ~= nil then
        local last
        for _, s in ipairs(S.slots) do
            if s.runid == run.id and not s.axial and s.group == q.group and s.kind == q.kind then last = s end
        end
        if last then
            local from = last.e + 1 + G.gap
            local base = first_col(C, run, last.side)
            local pos, ue = scan(C, S, run, last.side, from > base and from or base, item)
            if pos then take(C, S, run, last.side, pos, ue, item); return true end
            if C.late then return false end
        end
    end
    local zone = q.zone
    local pref
    if zone == 'far' then
        pref = run_end(run) + 1 - G.ahead
    elseif zone == 'mid' then
        pref = run.u0 + G.run_max // 3
    end
    local order = side_order(C, run)
    for pass = 1, 2 do
        if pass == 1 and pref or pass == 2 then
            for _, side in ipairs(order) do
                local base = first_col(C, run, side)
                local start = base
                if pass == 1 and pref > base then start = pref end
                if not (pass == 2 and pref and pref <= base) then       -- the same scan twice
                    local pos, ue = scan(C, S, run, side, start, item)
                    if pos then take(C, S, run, side, pos, ue, item); return true end
                    if C.late then return false end
                end
            end
        end
    end
    return false
end

local function try_run(C, S, run, item)
    -- a run that had no place for such an item has none later in the plan: the floor only fills
    if run.full and run.full[item.sig] then return false end
    local ok = try_run_now(C, S, run, item)
    if not ok and not C.late then
        run.full = run.full or {}
        run.full[item.sig] = true
    end
    return ok
end

-- ---------------------------------------------------------------- growing

local function free_runs(C)
    if not C.free then C.free = survey(C.floor, C.G, C.env) end
    return C.free
end

-- the directions a hub arm may open in, in order
local function arm_dirs(C, S)
    local G, free = C.G, free_runs(C)
    local out, seen = {}, {}
    local function ok(n) return DIRS[n] and not seen[n] and not S.dir_used[n] and free[n] >= G.run_min end
    for _, n in ipairs(type(G.dirs) == 'table' and G.dirs or {}) do
        if ok(n) then seen[n] = true; table.insert(out, n) end
    end
    local rest = {}
    for i, n in ipairs(DIR_ORDER) do
        if ok(n) then table.insert(rest, {n = n, i = i}) end
    end
    table.sort(rest, function(a, b)
        if free[a.n] ~= free[b.n] then return free[a.n] > free[b.n] end
        return a.i < b.i
    end)
    for _, r in ipairs(rest) do table.insert(out, r.n) end
    return out
end

-- take the newest run (and what came with it) out of the shadow floor again
local function drop_run(S, run, nobs)
    table.remove(S.runs)
    S.byid[run.id] = nil
    S.next_id = run.id
    for i = #S.fixed, nobs + 1, -1 do S.fixed[i] = nil end
    if run.parent == 0 then
        S.hub_runs = S.hub_runs - 1
        S.dir_used[dir_name(run.dx, run.dy)] = nil
    else
        local p = S.byid[run.parent]
        if p and p.kids[run.pside] == run then p.kids[run.pside] = nil; p.nkids = p.nkids - 1 end
    end
    bump(S)
end

-- spill: (r3 g2) the floor is full by its grammar: an arm past arms_max (up to one each way out of
-- the hub), begun wherever the survey's free run holds the item (not only run_min columns)
local function grow_arm(C, S, item, spill)
    local G = C.G
    if spill then
        if S.hub_runs >= #DIR_ORDER then return false end
    elseif S.hub_runs >= G.arms_max and #S.runs > 0 then
        return false
    end
    if #S.runs >= RUNS_MAX then C.record_full = true; return false end
    local dirs = arm_dirs(C, S)
    if spill then
        -- every free way, the longest free run first (the grammar's own ways were tried already)
        local G1 = {}
        for k, v in pairs(G) do G1[k] = v end
        G1.run_min, G1.dirs = G.lead + item.wmin + G.ahead, {}
        local C1 = setmetatable({G = G1}, {__index = C})
        dirs = arm_dirs(C1, S)
    end
    for _, n in ipairs(dirs) do
        local nobs = #S.fixed
        local run = add_run(S, {id = S.next_id, key = 'arm:' .. n, parent = 0, ox = 0, oy = 0,
                                dx = DIRS[n][1], dy = DIRS[n][2], len = 0, len0 = 0, new = true,
                                tag = C.req.tag, node = 3, neck = false, walked = 0})
        if G.neck and not C.necked and column_state(C.env, run, run.u0) == 'rock' then run.neck = true end
        local ok = reach(C, S, run) >= run.u0 + (spill and 1 or G.run_min) - 1
        if ok then
            if run.neck then C.necked = true end
            ok = try_run(C, S, run, item)
            if not ok and run.neck then C.necked = false end
        end
        if ok then return true end
        drop_run(S, run, nobs)
        if C.late then return false end
    end
    return false
end

-- which way a run turning off `parent` goes: sides of the parent, in order
local function turn_sides(C, parent)
    local t = C.G.turns
    if t == 'left' then return {-1} end
    if t == 'right' then return {1} end
    if t == 'both' then return {-1, 1} end
    -- alternate: the other way than the parent itself turned
    if parent.pside == -1 then return {1, -1} end
    return {-1, 1}
end

local function grow_turn(C, S, item)
    local G, env = C.G, C.env
    if #S.runs == 0 then return false end
    if #S.runs >= RUNS_MAX then C.record_full = true; return false end
    -- off the tag's runs, the newest first (a fort that forks both ways: the
    -- oldest first, so each end forks before its branches do); off any run
    -- when the tag has none
    local a, b, step = #S.runs, 1, -1
    if G.turns == 'both' then a, b, step = 1, #S.runs, 1 end
    local parents = {}
    for i = a, b, step do
        local r = S.runs[i]
        if not r.closed and r.tag == C.req.tag and r.len > 0 then table.insert(parents, r) end
    end
    if #parents == 0 then
        for i = a, b, step do
            local r = S.runs[i]
            if not r.closed and r.len > 0 then table.insert(parents, r) end
        end
    end
    for _, p in ipairs(parents) do
        for _, side in ipairs(turn_sides(C, p)) do
            local can = not p.kids[side] and (G.turns == 'both' or p.nkids == 0) and p.len >= 3
            if can then
                local e0, len0 = run_end(p), p.len
                local kmax = (p.nkids > 0) and 0 or TURN_REACH
                for k = 0, kmax do
                    local e = e0 + k
                    if k > 0 then
                        if not col_ok(C, S, p, e) then break end
                        set_len(S, p, e - p.u0 + 1)
                    end
                    local ox, oy = tile(p, e - 1, 0)
                    local nobs = #S.fixed
                    local node = G.node == 5 and 5 or 3
                    local sib = p.kids[-side]
                    local run = add_run(S, {id = S.next_id, key = 'turn:' .. p.key .. ':' .. side .. ':' .. e,
                                            parent = p.id, ox = ox, oy = oy, dx = side * p.px, dy = side * p.py,
                                            len = 0, len0 = 0, new = true, tag = C.req.tag, node = node,
                                            neck = false, walked = 0})
                    local ok = true
                    if node == 5 then
                        if sib and sib.node == 5 then
                            run.node_shared = true            -- the square is its sibling's
                        else
                            -- the 5x5 square: clear of every slot and of other halls, on the map, diggable
                            local o = run.nodeob
                            ok = in_bounds(env, o.x1, o.y1, o.x2, o.y2)
                                and hall_clear(S, run, o.x1, o.y1, o.x2, o.y2, 0, p.hall)
                                and not env.blocked(o.x1, o.y1, o.x2, o.y2)
                            if ok then
                                for x = o.x1, o.x2 do
                                    for y = o.y1, o.y2 do
                                        local s = env.open(x, y)
                                        if s ~= 'rock' and s ~= 'open' then ok = false end
                                    end
                                end
                            end
                        end
                    end
                    if ok then ok = reach(C, S, run) >= run.u0 + G.run_min - 1 end
                    if ok then ok = try_run(C, S, run, item) end
                    if ok then return true end
                    drop_run(S, run, nobs)
                    if C.late then
                        if p.len ~= len0 then set_len(S, p, len0) end
                        return false
                    end
                end
                if p.len ~= len0 then set_len(S, p, len0) end
            end
        end
    end
    return false
end

-- ---------------------------------------------------------------- one plan

local function ordered_runs(C, S, mine)
    local G, q = C.G, C.req
    local list = {}
    for _, r in ipairs(S.runs) do
        if not r.closed and ((r.tag == q.tag) == mine) then table.insert(list, r) end
    end
    local zone = q.zone
    table.sort(list, function(a, b)
        if G.balance and a.len ~= b.len then return a.len < b.len end
        if zone == 'near' and a.depth ~= b.depth then return a.depth < b.depth end
        if zone == 'far' and a.depth ~= b.depth then return a.depth > b.depth end
        return a.id < b.id
    end)
    if q.group ~= nil then            -- the run of the group's last slot first
        local last
        for _, s in ipairs(S.slots) do
            if s.group == q.group and s.kind == q.kind and not s.axial then last = s.runid end
        end
        for i, r in ipairs(list) do
            if r.id == last then table.remove(list, i); table.insert(list, 1, r); break end
        end
    end
    if C.prev then                    -- the run of the request's own previous item before any
        for i, r in ipairs(list) do
            if r.id == C.prev.runid then table.remove(list, i); table.insert(list, 1, r); break end
        end
    end
    return list
end

local function place_item(C, S, item)
    for _, run in ipairs(ordered_runs(C, S, true)) do
        if try_run(C, S, run, item) then return true end
        if C.late then return false end
    end
    local grow = type(C.G.grow) == 'table' and C.G.grow or {}
    if #S.runs == 0 then             -- an empty floor needs its first hall, whatever the grammar grows by
        if grow_arm(C, S, item) then return true end
    else
        for _, how in ipairs(grow) do
            if C.late then return false end
            if how == 'arm' and grow_arm(C, S, item) then return true end
            if how == 'turn' and grow_turn(C, S, item) then return true end
        end
    end
    if C.late then return false end
    for _, run in ipairs(ordered_runs(C, S, false)) do
        if try_run(C, S, run, item) then return true end
        if C.late then return false end
    end
    -- (r3 g2) every run full and the grammar grows no more: another arm out of the hub (the far
    -- side, the free ways the survey found) before 'no room'. Only with G.spill = true
    -- (ai-builder-floors sets it unless the hint says spill = false).
    if C.G.spill == true and #S.runs > 0 and not C.late then
        if grow_arm(C, S, item, true) then return true end
    end
    return false
end

-- a hall unit closing the end of the tag's longest run
local function try_axial(C, S, unit)
    local G, env, q = C.G, C.env, C.req
    if C.no_axial then return false end
    local best
    for _, r in ipairs(S.runs) do
        if not r.closed and r.tag == q.tag and r.nkids == 0 and (not best or r.len > best.len) then best = r end
    end
    if not best or best.len * 2 < G.run_max then return false end
    local run = best
    local e = run_end(run)
    local open = unit.open
    local c0 = (open[1] + open[2]) // 2
    if open[1] - c0 < -1 or open[2] - c0 > 1 then return false end       -- the opening must face the hall
    local va, vb = -c0, unit.w - 1 - c0
    local x1, y1, x2, y2 = box_uv(run, e + 1, va, e + 1 + unit.d, vb)
    if not in_bounds(env, x1, y1, x2, y2) then return false end
    if not slot_clear(S, run, x1, y1, x2, y2) then return false end
    if env.blocked(x1 - 1, y1 - 1, x2 + 1, y2 + 1) then return false end
    for u = e + 1, e + 2 + unit.d do
        for v = va - 1, vb + 1 do
            local x, y = tile(run, u, v)
            if env.open(x, y) ~= 'rock' then return false end
        end
    end
    for v = va - 1, vb + 1 do           -- beside the hall's last column: rock too
        if v < -1 or v > 1 then
            local x, y = tile(run, e, v)
            if env.open(x, y) ~= 'rock' then return false end
        end
    end
    local s = add_slot(S, run, {side = 0, u = e + 1, w = unit.w, d = unit.d, kind = q.kind, group = q.group,
                                axial = true, c0 = c0, unit = unit, index = 1})
    table.insert(C.puts, s)
    run.closed = 'terminus'
    bump(S)
    return true
end

local function plan(C)
    local S = shadow(C.floor, C.G.run_max, C.dmax)
    C.puts = {}
    C.prev = nil
    C.necked = false
    C.record_full = false
    local units = C.units
    if C.req.axial and C.G.axial and #units == 1 and (units[1].role == nil or units[1].role == 'hall')
            and try_axial(C, S, units[1]) then
        return S
    end
    if C.clusters then
        -- (V3) each cluster (a workshop and its pile rooms) is one row of its own; the clusters
        -- follow each other along the hall, onto the other side or another run when one is full
        for _, list in ipairs(C.clusters) do
            local item = {units = {}, index = {}, wmin = 0}
            local sig = 'T'
            for j, i in ipairs(list) do
                local u = units[i]
                item.units[j] = u
                item.index[j] = i
                item.wmin = item.wmin + u.w + (j > 1 and C.G.gap or 0)
                sig = sig .. u.w .. 'x' .. u.d
            end
            item.sig = sig
            if not place_item(C, S, item) then return nil end
        end
    else
        for i, u in ipairs(units) do
            local item = {units = {u}, index = {i}, wmin = u.w, sig = u.w .. 'x' .. u.d}
            if not place_item(C, S, item) then return nil end
        end
    end
    return S
end

-- ---------------------------------------------------------------- the map's word (env.probe)

local function mark(set, x, y)
    local col = set[x]
    if not col then col = {}; set[x] = col end
    col[y] = true
end

-- the floor's own tiles as the plan has them: hub, nodes, halls, slots
local function known_tiles(S)
    local set = {}
    for _, list in ipairs({S.fixed, S.slots}) do
        for _, o in ipairs(list) do
            if not o.off then
                for x = o.x1, o.x2 do
                    for y = o.y1, o.y2 do mark(set, x, y) end
                end
            end
        end
    end
    return set
end

local function put_T(C, run, s)
    local unit = s.unit
    if s.axial then
        local e1 = s.u
        return {a = run.px, b = run.dx, c = run.py, d = run.dy,
                tx = run.ox + e1 * run.dx - s.c0 * run.px, ty = run.oy + e1 * run.dy - s.c0 * run.py}, false
    end
    local G = C.G
    local mirror = not (G.stagger == 0 and G.sides == 'both') and ((C.env.seed or 0) + s.index) % 2 == 1
    local side = s.side
    local tx = run.ox + s.u * run.dx + 2 * side * run.px
    local ty = run.oy + s.u * run.dy + 2 * side * run.py
    if mirror then
        return {a = -run.dx, b = side * run.px, c = -run.dy, d = side * run.py,
                tx = tx + (unit.w - 1) * run.dx, ty = ty + (unit.w - 1) * run.dy}, true
    end
    return {a = run.dx, b = side * run.px, c = run.dy, d = side * run.py, tx = tx, ty = ty}, false
end

-- a unit's tiles to dig, as far as this module knows them: the whole room
-- and the opening on the wall row
local function put_tiles(T, unit, out)
    out = out or {}
    for bx = unit.open[1], unit.open[2] do
        table.insert(out, {x = T.a * bx + T.tx, y = T.c * bx + T.ty})
    end
    for by = 1, unit.d do
        for bx = 0, unit.w - 1 do
            table.insert(out, {x = T.a * bx + T.b * by + T.tx, y = T.c * bx + T.d * by + T.ty})
        end
    end
    return out
end

-- the rock tiles of a run's new hall columns a .. b (a neck's column: its
-- middle tile only), and of a new 5x5 node
local function hall_tiles(C, run, a, b, out, seen)
    local env = C.env
    out = out or {}
    seen = seen or {}
    local function add(x, y)
        if x == 0 and y == 0 then return end
        if seen[x] and seen[x][y] then return end
        mark(seen, x, y)
        if env.open(x, y) == 'rock' then table.insert(out, {x = x, y = y}) end
    end
    if run.new and run.node == 5 and not run.node_shared then
        for r = 0, 2 do                         -- the square, from its middle outward
            for du = -r, r do
                for dv = -r, r do
                    if math.max(math.abs(du), math.abs(dv)) == r then add(run.ox + du, run.oy + dv) end
                end
            end
        end
    end
    for u = a, b do
        if run.neck and u == run.u0 then
            add(tile(run, u, 0))
        else
            add(tile(run, u, 0))
            add(tile(run, u, -1))
            add(tile(run, u, 1))
        end
    end
    return out
end

local function hub_tiles(C, out, seen)
    out = out or {}
    for y = -1, 1 do
        for x = -1, 1 do
            if not (x == 0 and y == 0) then
                if seen then mark(seen, x, y) end
                if C.env.open(x, y) == 'rock' then table.insert(out, {x = x, y = y}) end
            end
        end
    end
    return out
end

local function ask(C, tiles, known, role)
    if #tiles == 0 then return true end
    if C.env.late() or C.probes >= C.G.tries then C.late = true; return nil end
    C.probes = C.probes + 1
    local ok, why = C.env.probe(tiles, known, role)
    if not ok then C.why = tostring(why or 'refused') end
    return ok and true or false
end

-- Ask the map about a plan. True: every new tile may be dug. False: something
-- was refused and noted in C (the next plan goes round it), or time ran out.
local function verify(C, S)
    local known = known_tiles(S)
    if C.new_hub and not C.good.hub then
        local ok = ask(C, hub_tiles(C), known, 'hall')
        if ok == nil then return false end
        if not ok then C.fatal = "refused: the stair's hub (" .. C.why .. ')'; return false end
        C.good.hub = true
    end
    for _, run in ipairs(S.runs) do
        local a, b = run.u0 + run.len0, run_end(run)
        if run.new or b >= a then
            local function key(to) return 'h|' .. run.key .. '|' .. a .. '|' .. to end
            if not C.good[key(b)] then
                local ok = ask(C, hall_tiles(C, run, a, b), known, 'hall')
                if ok == nil then return false end
                if ok then
                    C.good[key(b)] = true
                else
                    C.refusals = C.refusals + 1
                    -- how far it may go: the longest stretch the map allows
                    local lo, hi = a - 1, b
                    while hi - lo > 1 do
                        local mid = (lo + hi) // 2
                        local ok2 = ask(C, hall_tiles(C, run, a, mid), known, 'hall')
                        if ok2 == nil then return false end
                        if ok2 then lo = mid; C.good[key(mid)] = true else hi = mid end
                    end
                    C.limit[run.key] = lo
                    return false
                end
            end
        end
    end
    local pending = {}
    for _, s in ipairs(C.puts) do
        local run = S.byid[s.runid]
        s.T, s.mirror = put_T(C, run, s)
        s.rkey = s.axial and ('x|' .. run.key) or ('r|' .. run.key .. '|' .. s.side .. '|' .. s.u .. '|' .. s.w .. 'x' .. s.d)
        if not C.good[s.rkey] then table.insert(pending, s) end
    end
    if #pending == 0 then return true end
    local all = {}
    for _, s in ipairs(pending) do put_tiles(s.T, s.unit, all) end
    local ok = ask(C, all, known, 'room')
    if ok == nil then return false end
    if ok then
        for _, s in ipairs(pending) do C.good[s.rkey] = true end
        return true
    end
    C.refusals = C.refusals + 1
    local first = pending[1]
    local run = S.byid[first.runid]
    if first.axial then
        C.no_axial = true
        return false
    end
    -- the pending puts by the item they belong to: a row of several units (a cluster, a
    -- together row) is refused as one, at its first column; a single unit over its first half
    local items, order = {}, {}
    for _, s in ipairs(pending) do
        local it = s.item
        if not items[it] then items[it] = {}; table.insert(order, it) end
        table.insert(items[it], s)
    end
    local function refuse(it)
        local s = items[it][1]
        local r = S.byid[s.runid]
        if #it.units > 1 then
            C.refused[refused_key(r, s.side, s.item_u, it)] = true
        else
            for u = s.u, s.u + math.max(1, s.w // 2) - 1 do
                C.refused[refused_key(r, s.side, u, it)] = true
            end
        end
    end
    if #order == 1 then
        refuse(order[1])
        return false
    end
    local bad = 0
    for _, it in ipairs(order) do
        local tiles = {}
        for _, s in ipairs(items[it]) do put_tiles(s.T, s.unit, tiles) end
        local ok1 = ask(C, tiles, known, 'room')
        if ok1 == nil then return false end
        if ok1 then
            for _, s in ipairs(items[it]) do C.good[s.rkey] = true end
        else
            bad = bad + 1
            refuse(it)
        end
    end
    -- each alone is fine: the caller checks the whole level once more anyway
    return bad == 0
end

-- ---------------------------------------------------------------- the answer

local function build(C, S)
    local req, env = C.req, C.env
    local P = {floor_id = C.floor.id, new_floor = C.new_floor,
               req = {kind = req.kind, tag = req.tag, group = req.group},
               puts = {}, hall = {}, hall_rects = {}, runs = {}, statues = {}}
    local seen = {}
    if C.new_hub then hub_tiles(C, P.hall, seen) end
    for _, run in ipairs(S.runs) do
        local a, b = run.u0 + run.len0, run_end(run)
        local touched = run.new or b >= a or run.closed ~= run.closed0
        if touched and not run.orphan then
            if run.new or b >= a then
                hall_tiles(C, run, a, b, P.hall, seen)
                if run.new and run.node == 5 and not run.node_shared then
                    table.insert(P.hall_rects, {x = run.ox - 2, y = run.oy - 2, w = 5, h = 5})
                    for _, c in ipairs({{-2, -2}, {2, -2}, {-2, 2}, {2, 2}}) do
                        table.insert(P.statues, {x = run.ox + c[1], y = run.oy + c[2]})
                    end
                end
                local from = a
                if run.neck and run.len0 == 0 then
                    from = a + 1
                    local nx, ny = tile(run, run.u0, 0)
                    P.neck = {x = nx, y = ny}
                end
                if b >= from then
                    local x1, y1, x2, y2 = box_uv(run, from, -1, b, 1)
                    table.insert(P.hall_rects, {x = x1, y = y1, w = x2 - x1 + 1, h = y2 - y1 + 1})
                end
            end
            local walked = run.walked
            if run.new then
                walked = 0
                for u = run.u0, b do
                    if column_state(env, run, u) ~= 'open' then break end
                    walked = walked + 1
                end
            end
            table.insert(P.runs, {id = run.id, new = run.new, parent = run.parent, ox = run.ox, oy = run.oy,
                                  dx = run.dx, dy = run.dy, len_before = run.len0, len = run.len, walked = walked,
                                  tag = run.tag, node = run.node, neck = run.neck, closed = run.closed})
        end
    end
    local room_tiles = 0
    table.sort(C.puts, function(p, q) return p.index < q.index end)
    for _, s in ipairs(C.puts) do
        local run = S.byid[s.runid]
        local unit = s.unit
        if not s.T then s.T, s.mirror = put_T(C, run, s) end
        table.insert(P.puts, {unit = s.index, run = run.id, side = s.side, u = s.u, w = s.w, d = s.d,
                              axial = s.axial and true or false, mirror = s.mirror and true or false,
                              role = unit.role, flag = unit.flag, T = s.T,
                              rect = {x1 = s.x1, y1 = s.y1, x2 = s.x2, y2 = s.y2}})
        room_tiles = room_tiles + unit.w * unit.d + (unit.open[2] - unit.open[1] + 1)
    end
    P.hall_new = #P.hall
    P.tiles = P.hall_new + room_tiles
    return P
end

local function no_hall_words(free)
    local parts = {}
    for _, n in ipairs(SAY_ORDER) do table.insert(parts, n .. ' ' .. tostring(free[n])) end
    return 'no hall: ' .. table.concat(parts, ', ')
end

-- req: {kind, tag, group, zone, units = { {w, d, open, role, flag} ...},
-- together, clusters, axial, min_u}. A `together` request's units stand side
-- by side in rows: its `clusters` (lists of unit indices, each unit in
-- exactly one; a workshop and its pile rooms) are each one row, following
-- each other along the hall, across it or onto another run; with no
-- clusters the whole request is one row.
-- Where the request goes on the floor: a placement (nothing is saved until
-- ai-floorplan.commit), or nil and why: 'no hall ...' (no hall can start on
-- this level), 'no room' (the floor is full), 'refused: ...' (the map said
-- no), 'out of time' (env.late() or G.tries), 'floor record full',
-- 'bad request'.
function place(floor, req, G, env)
    if type(floor) ~= 'table' or type(req) ~= 'table' or type(G) ~= 'table' or type(env) ~= 'table' then
        return nil, 'bad request'
    end
    if type(req.units) ~= 'table' or #req.units == 0 then return nil, 'bad request: no units' end
    -- the units, read once (the request itself is never written to)
    local units = {}
    for i, u in ipairs(req.units) do
        if type(u) ~= 'table' or type(u.w) ~= 'number' or type(u.d) ~= 'number' or u.w < 1 or u.d < 1 then
            return nil, 'bad request: unit ' .. i
        end
        local w, d = math.floor(u.w), math.floor(u.d)
        local x0, x1 = (w - 1) // 2, (w - 1) // 2
        if type(u.open) == 'table' then
            x0 = math.floor(tonumber(u.open.x0 or u.open[1]) or x0)
            x1 = math.floor(tonumber(u.open.x1 or u.open[2]) or x0)
        end
        if x0 < 0 then x0 = 0 end
        if x1 > w - 1 then x1 = w - 1 end
        if x1 < x0 then x1 = x0 end
        units[i] = {w = w, d = d, role = u.role, flag = u.flag, open = {x0, x1}}
    end
    local nruns = type(floor.runs) == 'table' and #floor.runs or 0
    local nslots = type(floor.slots) == 'table' and #floor.slots or 0
    if nslots + #units > SLOTS_MAX or nruns > RUNS_MAX then return nil, 'floor record full' end
    local dmax = 1
    for _, u in ipairs(units) do
        if u.w > dmax then dmax = u.w end
        if u.d > dmax then dmax = u.d end
    end
    -- the hub is looked at (and its rock dug) while the floor has no hall: a new floor, or one whose first
    -- project was cancelled and its runs rolled back to nothing
    local no_hall = true
    for i = 1, nruns do
        local r = floor.runs[i]
        if type(r) == 'table' and (r.len or 0) > 0 then no_hall = false end
    end
    local C = {floor = floor, req = req, G = G, env = env, units = units, dmax = dmax,
               refused = {}, limit = {}, good = {}, probes = 0, refusals = 0, late = false,
               new_hub = no_hall,
               new_floor = floor.hub == nil and nruns == 0 and nslots == 0}
    -- the items: a together request's clusters (each unit in exactly one), or its whole row as one
    if req.together then
        local list = {}
        if type(req.clusters) == 'table' and #req.clusters > 0 then
            local seen = {}
            for k, cl in ipairs(req.clusters) do
                if type(cl) ~= 'table' or #cl == 0 then return nil, 'bad request: cluster ' .. k end
                local one = {}
                for _, i in ipairs(cl) do
                    i = math.tointeger(i)
                    if not i or not units[i] or seen[i] then return nil, 'bad request: cluster ' .. k end
                    seen[i] = true
                    table.insert(one, i)
                end
                table.insert(list, one)
            end
            for i = 1, #units do
                if not seen[i] then return nil, 'bad request: unit ' .. i .. ' in no cluster' end
            end
        else
            list[1] = {}
            for i = 1, #units do list[1][i] = i end
        end
        C.clusters = list
    end
    if C.new_hub then
        for y = -1, 1 do
            for x = -1, 1 do
                if not (x == 0 and y == 0) then
                    local s = env.open(x, y)
                    if s ~= 'rock' and s ~= 'open' then return nil, "refused: the stair's hub" end
                end
            end
        end
    end
    if nruns == 0 then
        -- can a hall start at all?
        local free, any = free_runs(C), false
        for _, n in ipairs(DIR_ORDER) do if free[n] >= G.run_min then any = true end end
        if not any then return nil, no_hall_words(free) end
    end
    for _ = 1, PLANS_MAX do
        if env.late() then C.late = true end
        if C.late then break end
        local S = plan(C)
        if C.late then break end
        if not S then
            if C.record_full then return nil, 'floor record full' end
            if C.refusals > 0 then return nil, 'refused: ' .. tostring(C.why) end
            return nil, 'no room'
        end
        if verify(C, S) then return build(C, S) end
        if C.fatal then return nil, C.fatal end
    end
    return nil, 'out of time'
end

-- (V3) Could the request go onto ONE empty run of this grammar? `place` on a
-- floor with nothing on it, all rock round the stair, one arm and no turns:
-- true when it fits. A 'no room' for a request that could is a full floor;
-- for one that could not, the request is only too big for a run (the floor
-- is not marked full for it). Pure: no env of the caller's is asked.
function fits_empty(req, G)
    if type(req) ~= 'table' or type(G) ~= 'table' then return false end
    local G1 = {}
    for k, v in pairs(G) do G1[k] = v end
    G1.arms_max, G1.grow, G1.tries, G1.spill = 1, {}, 1000, false
    local env = {bounds = nil, seed = 0}
    function env.open() return 'rock' end
    function env.blocked() return false end
    function env.probe() return true end
    function env.late() return false end
    local P = place({id = 0, runs = {}, slots = {}}, req, G1, env)
    return type(P) == 'table'
end

local RUN_MAX_TOP = 80        -- ai-floorplan's highest run_max

-- (r3 g2) The shortest run_max (G's own up to RUN_MAX_TOP) at which the request fits onto one
-- empty run of this grammar (fits_empty), or nil when even the longest run cannot take it (it is
-- too deep or too wide for any hall: the classic way at once). Pure.
-- remake(n), when given: the grammar as it would be with run_max n (ai-floorplan.grammar gives a
-- short run's lead and gap back as the run grows); else G with only run_max changed.
function need_run(req, G, remake)
    if type(req) ~= 'table' or type(G) ~= 'table' then return nil end
    local lo = math.tointeger(G.run_max) or 30
    local function fits_at(n)
        local G1
        if type(remake) == 'function' then G1 = remake(n) end
        if type(G1) ~= 'table' then
            G1 = {}
            for k, v in pairs(G) do G1[k] = v end
            G1.run_max = n
        end
        if (tonumber(G1.run_min) or 0) > n then G1.run_min = n end
        return fits_empty(req, G1)
    end
    if fits_at(lo) then return lo end
    if lo >= RUN_MAX_TOP or not fits_at(RUN_MAX_TOP) then return nil end
    local a, b = lo, RUN_MAX_TOP           -- fits_at(a) false, fits_at(b) true
    while b - a > 1 do
        local m = (a + b) // 2
        if fits_at(m) then b = m else a = m end
    end
    return b
end
