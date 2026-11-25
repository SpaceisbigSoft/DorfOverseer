-- ai-blueprints-stages: (E2) the build order of a surface drawing, with
-- scaffolding (build_stages).
--
-- (r9) A part of ai-blueprints, not a script of its own: ai-blueprints.lua loads it
-- into its own environment, so every name here is reqscript('ai-blueprints').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-blueprints-stages is a part of ai-blueprints; run ai-blueprints') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-blueprints-stages'] = '0.105.118'   -- (0.105.26) bumped with BRIDGE_VERSION

local needs_floor, int, where, grids_of, cell, N8, mark = PART_LOCALS.needs_floor, PART_LOCALS.int, PART_LOCALS.where, PART_LOCALS.grids_of, PART_LOCALS.cell, PART_LOCALS.N8, PART_LOCALS.mark   -- (r9) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- (E2) The build order of a surface drawing, with scaffolding
---------------------------------------------------------------------------
-- A surface landmark goes up level by level from the bottom. A tile is
-- built by a dwarf standing on a walkable tile beside it (8 ways, the same
-- level) that a dwarf can walk to from '@'; a stair is also built from the
-- up stair under it (a stair column grows from below) [verify]. Where the
-- next tiles can't be reached so, a temporary stair column (scaffolding:
-- 'Cu' on the ground, 'Cx' above) is planned first, on ground left walkable
-- ('.') with open air ('_') over it on every level it climbs (outside the
-- finished shape), and taken down (top first) once the part it serves is
-- built. Never walls a dwarf in: no step leaves a tile that was reachable
-- walkable but cut off from '@' (the walls that would close a space wait,
-- inside-out, until the space has another way out), and a removal waits
-- while anyone stands where it would strand them (its `cut` tiles).
--
-- build_stages(bp, q) -> {list = {step...}, scaffold = {columns, tiles}},
-- or nil and reasons ({code = 'ORDER', level, x, y, words}, on the
-- drawing's own grid). A step: {kind = 'build' | 'scaffold' | 'remove',
-- level, dz, cells = {{x, y, text, gx, gy}}, cut = {{x, y, dz}} (remove)},
-- x, y in to_layouts' frame (level 1's '@' at 0, 0, after q quarter turns);
-- text a construction key ('Cw' 'Cf' 'Cr' 'Cu' 'Cd' 'Cx' 'CF'), 'd' a door,
-- or the scaffold's key (a 'remove' step's tiles are taken down). The
-- furniture, stockpiles and zone come after the last step, as before.
-- A rock drawing has no steps. Pure: the drawing only, no map.
SCAFFOLD_MAX = {columns = 4, tiles = 24}

local SOLID_KEY = {Cw = true, CF = true}
local STAIR_KEY = {Cu = true, Cd = true, Cx = true}
local KEY_SYM = {Cw = 'W', CF = 'O', Cf = 'F', Cr = 'R', Cu = 'U', Cd = 'D', Cx = 'I', d = 'd'}

local function stage_plan(bp)
    local g = grids_of(bp)
    local n, h, w = #g, #g[1], #g[1][1]
    local jx, jy
    for r = 0, h - 1 do
        local c = g[1][r + 1]:find('@', 1, true)
        if c then jx, jy = c - 1, r end
    end
    local function K(i, x, y) return (i * 64 + y) * 64 + x end
    local jobs, job_at = {}, {}
    for i = 1, n do
        for y = 0, h - 1 do
            for x = 0, w - 1 do
                local ch = cell(g, i, x, y)
                local below = i > 1 and cell(g, i - 1, x, y) or nil
                local key = CONSTRUCT[ch] or (needs_floor(i, ch, below) and 'Cf') or nil
                if key then
                    local j = {i = i, x = x, y = y, text = key, solid = SOLID_KEY[key] or false}
                    table.insert(jobs, j)
                    job_at[K(i, x, y)] = j
                end
                if ch == '+' then
                    local j = {i = i, x = x, y = y, text = 'd', door = true, solid = false}
                    table.insert(jobs, j)
                    job_at[-K(i, x, y)] = j      -- the door's own key (its floor may share the tile)
                end
            end
        end
    end
    return {g = g, n = n, h = h, w = w, jx = jx, jy = jy, K = K, jobs = jobs, job_at = job_at}
end

-- The state: built[k] = the symbol built there ('W' 'O' 'F' 'R' 'U' 'D' 'I',
-- 'd' a door), scaffolding in sc[k] ('U' or 'I').
local function sim(P)
    local S = {built = {}, sc = {}}
    local g, n, h, w, K = P.g, P.n, P.h, P.w, P.K
    local function eff(i, x, y)
        local k = K(i, x, y)
        return S.sc[k] or S.built[k]
    end
    S.eff = eff
    local function solid(b) return b == 'W' or b == 'O' end
    -- extra: {k = sym} taken as built on top of the state (a stage's walls)
    local function walk(i, x, y, extra)
        if i < 1 or i > n or x < 0 or y < 0 or x >= w or y >= h then return false end
        local k = K(i, x, y)
        local b = (extra and extra[k]) or eff(i, x, y)
        if b == '-' then b = nil end
        if solid(b) then return false end
        if b then return true end
        if i == 1 then return cell(g, 1, x, y) ~= '_' end
        local bk = K(i - 1, x, y)
        local under = (extra and extra[bk]) or eff(i - 1, x, y)
        return under == 'W'
    end
    S.walk = walk
    local function sym_at(i, x, y, extra)
        local k = K(i, x, y)
        local b = (extra and extra[k]) or eff(i, x, y)
        if b == '-' then return nil end
        return b
    end
    -- Every tile reached from '@': seen[k] = true. grow: floor jobs taken as
    -- they come within reach (built on the way); returns seen, taken.
    function S.reach(extra, grow)
        extra = extra or {}
        local taken = {}
        local seen
        local again = true
        while again do
            again = false
            seen = {}
            local queue, head = {}, 1
            local function go(i, x, y)
                local k = K(i, x, y)
                if not seen[k] and walk(i, x, y, extra) then
                    queue[#queue + 1] = {i, x, y}
                    seen[k] = #queue
                end
            end
            local function take(j)
                if grow and grow[j] and not taken[j] then
                    taken[j] = true
                    extra[K(j.i, j.x, j.y)] = j.door and (extra[K(j.i, j.x, j.y)] or 'd') or KEY_SYM[j.text]
                    again = true
                end
            end
            go(1, P.jx, P.jy)
            while head <= #queue do
                local i, x, y = table.unpack(queue[head])
                head = head + 1
                local b = sym_at(i, x, y, extra)
                if grow then
                    for _, d in ipairs(N8) do
                        local nx, ny = x + d[1], y + d[2]
                        take(P.job_at[K(i, nx, ny)])
                        if walk(i, nx, ny, extra) and not seen[K(i, nx, ny)] then go(i, nx, ny) end
                    end
                    if (b == 'U' or b == 'I') and i < n then
                        local j = P.job_at[K(i + 1, x, y)]
                        if j and STAIR_KEY[j.text] then take(j) end
                    end
                    b = sym_at(i, x, y, extra)
                end
                for _, d in ipairs(N8) do go(i, x + d[1], y + d[2]) end
                if (b == 'U' or b == 'I') and i < n then
                    local up = sym_at(i + 1, x, y, extra)
                    if up == 'D' or up == 'I' then go(i + 1, x, y) end
                end
                if (b == 'D' or b == 'I') and i > 1 then
                    local dn = sym_at(i - 1, x, y, extra)
                    if dn == 'U' or dn == 'I' then go(i - 1, x, y) end
                end
                if b == 'R' and i < n then
                    for _, d in ipairs(N8) do go(i + 1, x + d[1], y + d[2]) end
                end
                if i > 1 then
                    for _, d in ipairs(N8) do
                        if sym_at(i - 1, x + d[1], y + d[2], extra) == 'R' then go(i - 1, x + d[1], y + d[2]) end
                    end
                end
            end
            if not grow then break end
        end
        return seen, taken
    end
    -- Can a dwarf in `seen` build (or take down) the tile at i, x, y?
    -- Beside it on its level, or (a stair) on the up stair under it.
    function S.stand(seen, i, x, y, stair)
        for _, d in ipairs(N8) do
            if seen[K(i, x + d[1], y + d[2])] then return true end
        end
        if stair and i > 1 and seen[K(i - 1, x, y)] then
            local b = eff(i - 1, x, y)
            if b == 'U' or b == 'I' then return true end
        end
        return false
    end
    -- Tiles in `before` still walkable (with extra) but not in `after`.
    function S.cut(before, after, extra)
        local out = {}
        for k in pairs(before) do
            if not after[k] then
                local x = k % 64
                local y = (k // 64) % 64
                local i = k // 4096
                if walk(i, x, y, extra) then out[#out + 1] = {i = i, x = x, y = y} end
            end
        end
        table.sort(out, function(a, b) return K(a.i, a.x, a.y) < K(b.i, b.x, b.y) end)
        return out
    end
    return S
end

local function turn_xy_bp(x, y, q)
    for _ = 1, q % 4 do x, y = -y, x end
    return x, y
end

local function order_reason(level, x, y, words)
    return {code = 'ORDER', level = level, x = x, y = y, words = where(level, x, y) .. words}
end

-- The ring of 8 round a tile, in order, and whether the reachable ones of
-- them are one group joined round it (so walling the tile cuts nothing off).
local RING = {{-1, -1}, {0, -1}, {1, -1}, {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}}
local function simple_point(seen, K, j)
    local on, any = {}, 0
    for r, d in ipairs(RING) do
        if seen[K(j.i, j.x + d[1], j.y + d[2])] then on[r] = true any = any + 1 end
    end
    if any == 0 then return true end
    -- groups along the ring: a corner (odd r) joins its two sides; a side
    -- (even r) joins the next side across the corner between them too
    local group, g = {}, 0
    local function mark(r0)
        local stack = {r0}
        group[r0] = g
        while #stack > 0 do
            local r = table.remove(stack)
            local nb = {r % 8 + 1, (r - 2) % 8 + 1}
            if r % 2 == 0 then nb[3] = (r + 1) % 8 + 1; nb[4] = (r - 3) % 8 + 1 end
            for _, o in ipairs(nb) do
                if on[o] and not group[o] then group[o] = g stack[#stack + 1] = o end
            end
        end
    end
    for r = 1, 8 do
        if on[r] and not group[r] then g = g + 1 mark(r) end
    end
    return g <= 1
end

function build_stages(bp, q)
    if type(bp) ~= 'table' or bp.ground ~= 'surface' then
        return {list = {}, scaffold = {columns = 0, tiles = 0}}
    end
    local ok, reasons = check_format(bp)
    if not ok then return nil, reasons end
    q = (int(q) or 0) % 4
    local P = stage_plan(bp)
    local S = sim(P)
    local K, n = P.K, P.n
    local function simple(seen, j) return simple_point(seen, K, j) end
    local done = {}
    local steps = {}
    local columns = {}           -- {x, y, top, used}
    local sc_tiles = 0
    local function pending_dep(j)
        if j.i > 1 then
            local below = P.job_at[K(j.i - 1, j.x, j.y)]
            if below and not done[below] then return true end
        end
        if j.door then
            local floor = P.job_at[K(j.i, j.x, j.y)]
            if floor and not done[floor] then return true end
        end
        return false
    end
    local function commit(kind, level, list, extra)
        for _, j in ipairs(list) do
            done[j] = true
            local k = K(j.i, j.x, j.y)
            if j.door then
                S.built[k] = S.built[k] or 'd'
            else
                S.built[k] = KEY_SYM[j.text]
            end
        end
        table.sort(list, function(a, b)
            if a.y ~= b.y then return a.y < b.y end
            if a.x ~= b.x then return a.x < b.x end
            return (a.door and 1 or 0) < (b.door and 1 or 0)
        end)
        table.insert(steps, {kind = kind, level = level, jobs = list})
    end
    -- The columns a step leans on (it can't be done without them), on the
    -- state before it: floors (grown) or walls and doors (beside a dwarf).
    local function leans(list, grown)
        local need = {}
        for _, c in ipairs(columns) do
            local saved = {}
            for i = 1, c.top do local k = K(i, c.x, c.y); saved[k] = S.sc[k]; S.sc[k] = nil end
            local miss = false
            if grown then
                local g2 = {}
                for _, j in ipairs(list) do g2[j] = true end
                local _, t2 = S.reach({}, g2)
                for _, j in ipairs(list) do if not t2[j] then miss = true break end end
            else
                local extra = {}
                for _, j in ipairs(list) do if j.solid then extra[K(j.i, j.x, j.y)] = KEY_SYM[j.text] end end
                local seen = S.reach(extra)
                for _, j in ipairs(list) do
                    if not S.stand(seen, j.i, j.x, j.y, false) then miss = true break end
                end
            end
            for k, v in pairs(saved) do S.sc[k] = v end
            if miss then need[#need + 1] = c end
        end
        return need
    end
    local guard = 0
    while true do
        guard = guard + 1
        if guard > 4000 then return nil, {order_reason(nil, nil, nil, 'the build order did not settle')} end
        local left = false
        for _, j in ipairs(P.jobs) do if not done[j] then left = true break end end
        if not left then break end
        local R0 = S.reach()
        local progressed = false
        for L = 1, n do
            -- floors, stairs and ramps first (they only open ways), taken
            -- as they come within reach (the dwarves build them outward)
            local grow, any = {}, false
            for _, j in ipairs(P.jobs) do
                if not done[j] and j.i == L and not j.solid and not j.door and not pending_dep(j) then
                    grow[j] = true
                    any = true
                end
            end
            if any then
                local _, taken = S.reach({}, grow)
                local list = {}
                for _, j in ipairs(P.jobs) do if taken[j] then list[#list + 1] = j end end
                if #list > 0 then
                    local need = leans(list, true)
                    commit('build', L, list)
                    for _, c in ipairs(need) do c.used = #steps end
                    progressed = true
                    break
                end
            end
            -- then the walls and fortifications (and the doors), inside-out
            local cand = {}
            for _, j in ipairs(P.jobs) do
                if not done[j] and j.i == L and (j.solid or j.door) and not pending_dep(j)
                        and S.stand(R0, j.i, j.x, j.y, false) then
                    cand[#cand + 1] = j
                end
            end
            -- inside-out: the farthest from '@' first; a wall joins the step
            -- only while every tile of it keeps a dwarf's place beside it,
            -- whatever order they go up in, and no reachable tile is cut off
            local function far(j)
                local v = R0[K(j.i, j.x, j.y)]
                if v then return v end
                v = 0
                for _, d in ipairs(N8) do
                    local o = R0[K(j.i, j.x + d[1], j.y + d[2])]
                    if o and o > v then v = o end
                end
                return v
            end
            for _, j in ipairs(cand) do j.far = far(j) end
            table.sort(cand, function(a, b)
                if a.far ~= b.far then return a.far > b.far end
                return K(a.i, a.x, a.y) < K(b.i, b.x, b.y)
            end)
            local take, extra = {}, {}
            local R1 = {}
            for k, v in pairs(R0) do R1[k] = v end
            for _, j in ipairs(cand) do
                local k = K(j.i, j.x, j.y)
                local trial, local_only = R1, false
                if j.solid and R1[k] then
                    extra[k] = KEY_SYM[j.text]
                    if j.i == 1 and simple(R1, j) then
                        -- (a tile whose reachable neighbours stay joined round
                        -- it: walling it cuts nothing off, no search needed)
                        R1[k] = nil
                        local_only = true
                    else
                        trial = S.reach(extra)
                    end
                end
                local good = S.stand(trial, j.i, j.x, j.y, false)
                if good then
                    for _, t in ipairs(take) do
                        if not S.stand(trial, t.i, t.x, t.y, false) then good = false break end
                    end
                end
                if good and trial ~= R1 and #S.cut(R0, trial, extra) > 0 then good = false end
                if good then
                    take[#take + 1] = j
                    R1 = trial
                else
                    if local_only then R1[k] = R0[k] end
                    if j.solid then extra[k] = nil end
                end
            end
            cand = take
            if #cand > 0 then
                local need = leans(cand, false)
                commit('build', L, cand)
                for _, c in ipairs(need) do c.used = #steps end
                progressed = true
                break
            end
        end
        if not progressed then
            -- stuck: the lowest level with tiles ready but out of reach
            local L, stuck
            for lv = 1, n do
                stuck = {}
                for _, j in ipairs(P.jobs) do
                    if not done[j] and j.i == lv and not pending_dep(j)
                            and not S.stand(R0, j.i, j.x, j.y, STAIR_KEY[j.text]) then
                        stuck[#stuck + 1] = j
                    end
                end
                if #stuck > 0 then L = lv break end
            end
            if not L then
                local j
                for _, jj in ipairs(P.jobs) do if not done[jj] then j = jj break end end
                return nil, {order_reason(j.i, j.x, j.y, 'no build order that keeps a way out: these walls would close '
                    .. 'a space before it has another way out')}
            end
            local j1 = stuck[1]
            if L == 1 then
                return nil, {order_reason(j1.i, j1.x, j1.y, 'no dwarf can reach this tile from a walkable one to build it')}
            end
            -- a scaffold stair: a new column, or an old one climbing higher
            local best
            for y = 0, P.h - 1 do
                for x = 0, P.w - 1 do
                    local old
                    for _, c in ipairs(columns) do if c.x == x and c.y == y and not c.down then old = c end end
                    local from = old and (old.top + 1) or 1
                    local good = from <= L
                    if good and not old then
                        good = cell(P.g, 1, x, y) == '.' and not S.eff(1, x, y) and R0[K(1, x, y)] ~= nil
                    end
                    for i = math.max(from, 2), L do
                        if good and (cell(P.g, i, x, y) ~= '_' or S.eff(i, x, y)) then good = false end
                    end
                    if good then
                        for _, c in ipairs(columns) do
                            if not c.down and c ~= old and math.abs(c.x - x) + math.abs(c.y - y) == 0 then good = false end
                        end
                    end
                    if good then
                        local saved = {}
                        for i = from, L do
                            local k = K(i, x, y)
                            saved[k] = S.sc[k]
                            S.sc[k] = (i == 1) and 'U' or 'I'
                        end
                        local seen = S.reach()
                        local gain = 0
                        for _, j in ipairs(stuck) do
                            if S.stand(seen, j.i, j.x, j.y, STAIR_KEY[j.text]) then gain = gain + 1 end
                        end
                        for k, v in pairs(saved) do S.sc[k] = v end
                        if gain > 0 then
                            local over = 0          -- the finished shape above it (later levels)
                            for i = L + 1, n do if cell(P.g, i, x, y) ~= '_' then over = over + 1 end end
                            local dist = math.max(math.abs(x - P.jx), math.abs(y - P.jy))
                            local score = {-gain, over, L - from + 1, dist, y, x}
                            local better = not best
                            if best then
                                for t = 1, #score do
                                    if score[t] ~= best.score[t] then better = score[t] < best.score[t] break end
                                end
                            end
                            if better then best = {x = x, y = y, from = from, old = old, score = score} end
                        end
                    end
                end
            end
            if not best then
                return nil, {order_reason(j1.i, j1.x, j1.y, 'no dwarf can reach this tile, and there is no open ground '
                    .. "('.' with open air above) beside the shape for a scaffold stair")}
            end
            local add = L - best.from + 1
            if (not best.old and #columns >= SCAFFOLD_MAX.columns) or sc_tiles + add > SCAFFOLD_MAX.tiles then
                return nil, {order_reason(j1.i, j1.x, j1.y, ('it would take more scaffolding than allowed '
                    .. '(%d stair columns, %d tiles)'):format(SCAFFOLD_MAX.columns, SCAFFOLD_MAX.tiles))}
            end
            local c = best.old or {x = best.x, y = best.y, top = 0}
            if not best.old then table.insert(columns, c) end
            for i = best.from, L do
                local key = (i == 1) and 'Cu' or 'Cx'
                S.sc[K(i, c.x, c.y)] = (i == 1) and 'U' or 'I'
                table.insert(steps, {kind = 'scaffold', level = i, column = c,
                                     jobs = {{i = i, x = c.x, y = c.y, text = key}}})
                sc_tiles = sc_tiles + 1
            end
            c.top = L
            c.used = #steps
        end
    end
    -- the scaffolding comes down (top first) after the last step that
    -- leans on it; the whole order is then replayed and checked (else every
    -- column comes down at the end)
    local function with_removals(at_end)
        local out = {}
        local after = {}
        for _, c in ipairs(columns) do
            local at = at_end and #steps or math.max(c.used or #steps, 1)
            after[at] = after[at] or {}
            table.insert(after[at], c)
        end
        for s, st in ipairs(steps) do
            table.insert(out, st)
            for _, c in ipairs(after[s] or {}) do
                for i = c.top, 1, -1 do
                    table.insert(out, {kind = 'remove', level = i, column = c,
                                       jobs = {{i = i, x = c.x, y = c.y, text = (i == 1) and 'Cu' or 'Cx'}}})
                end
            end
        end
        return out
    end
    local function replay(list)
        local R = sim(P)
        local fin = {}
        local cuts = {}
        for s, st in ipairs(list) do
            local before = R.reach()
            if st.kind == 'remove' then
                local j = st.jobs[1]
                local k = K(j.i, j.x, j.y)
                if not R.sc[k] or (j.i < n and R.sc[K(j.i + 1, j.x, j.y)]) then return false end
                local sv = R.sc[k]
                R.sc[k] = nil
                local by_side = R.stand(before, j.i, j.x, j.y, false)
                R.sc[k] = sv
                local below = j.i > 1 and before[K(j.i - 1, j.x, j.y)] and R.sc[K(j.i - 1, j.x, j.y)]
                if not (by_side or below) then return false end
                R.sc[k] = nil
                local after = R.reach()
                cuts[s] = R.cut(before, after)
                -- (0.105.37 fix) a removal that leaves a tile cut off (one the
                -- remover or a builder could be standing on) is refused: this
                -- order fails, and with none left the drawing is refused
                if #cuts[s] > 0 then return false end
            else
                local extra = {}
                for _, j in ipairs(st.jobs) do
                    if st.kind == 'build' and j.solid then extra[K(j.i, j.x, j.y)] = KEY_SYM[j.text] end
                end
                local R1 = R.reach(extra)
                if #R.cut(before, R1, extra) > 0 then return false end
                local grow = {}
                for _, j in ipairs(st.jobs) do
                    if j.i > 1 then
                        local bj = P.job_at[K(j.i - 1, j.x, j.y)]
                        if bj and not fin[bj] then return false end
                    end
                    if j.door then
                        local fj = P.job_at[K(j.i, j.x, j.y)]
                        if fj and not fin[fj] then return false end
                    end
                    if st.kind == 'build' and not j.solid and not j.door then grow[j] = true end
                end
                local _, taken = R.reach({}, grow)
                for _, j in ipairs(st.jobs) do
                    local can
                    if grow[j] then can = taken[j]
                    else can = R.stand(R1, j.i, j.x, j.y, st.kind == 'scaffold' or STAIR_KEY[j.text]) end
                    if not can then return false end
                end
                for _, j in ipairs(st.jobs) do
                    local k = K(j.i, j.x, j.y)
                    if st.kind == 'scaffold' then R.sc[k] = (j.i == 1) and 'U' or 'I'
                    elseif j.door then R.built[k] = R.built[k] or 'd'
                    else R.built[k] = KEY_SYM[j.text] end
                    fin[j] = true
                end
            end
        end
        for _ in pairs(R.sc) do return false end
        return true, cuts
    end
    local list = with_removals(false)
    local good, cuts = replay(list)
    if not good then
        list = with_removals(true)
        good, cuts = replay(list)
    end
    if not good then
        return nil, {order_reason(nil, nil, nil, 'no safe order to put up and take down its scaffolding')}
    end
    -- in to_layouts' frame
    local function frame(x, y) return turn_xy_bp(x - P.jx, y - P.jy, q) end
    local out = {list = {}, scaffold = {columns = #columns, tiles = sc_tiles}}
    for s, st in ipairs(list) do
        local step = {kind = st.kind, level = st.level, dz = st.level - 1, cells = {}}
        for _, j in ipairs(st.jobs) do
            local x, y = frame(j.x, j.y)
            table.insert(step.cells, {x = x, y = y, text = j.text, gx = j.x, gy = j.y})
        end
        if st.kind == 'remove' then
            step.cut = {}
            for _, c in ipairs(cuts[s] or {}) do
                local x, y = frame(c.x, c.y)
                table.insert(step.cut, {x = x, y = y, dz = c.i - 1})
            end
        end
        table.insert(out.list, step)
    end
    return out
end
