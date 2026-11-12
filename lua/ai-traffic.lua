-- (0.105.41) Traffic zones on the AI's own levels, for the dwarves' paths and
-- the game's speed. DF's path finder weighs each tile by its traffic
-- designation (df.tile_traffic: Normal, Low, High, Restricted; the names are
-- used, never the numbers): a path keeps to High tiles and keeps off Low
-- ones, so the dwarves walk the corridors and stairs instead of cutting
-- through bedrooms, farms, tombs and the hospital, and the path search
-- settles sooner on the main ways.
--
-- What is painted, and only on tiles the AI dug itself (its project
-- records; never the player's rooms, never a tile outside them):
--   High  the stair tile of each finished level and the stair levels the
--         project dug (the spine where the AI's levels meet it), the
--         corridor and avenue from the stair to the level (p.links, kept
--         by start_project from 0.105.41; an older project's straight
--         corridor is found along the line from its stair to its anchor),
--         every tile of a way in (shaft stairs and gallery), and the deep
--         depot's road and hall once dug;
--   Low   every other dug tile of a bedrooms, suites, tombs, hospital or
--         farms level (dead ends: Low only keeps the through traffic out).
-- A level is painted when it is finished (phase done or decorate), once;
-- wells are never painted (a cavern well's shaft is no road). Restricted is
-- left to the guards that have a reason for it (the fire guard, the water
-- over ice).
--
-- Never the player's: only a tile at Normal is changed. A tile the player
-- (or a guard) set to anything else is left and counted. A recheck (audit)
-- counts a painted level's tiles again: when a quarter of them were set to
-- something else since (Restricted not counted: the fire and ice guards
-- set it for a while), or half were put back to Normal, the level is the
-- player's from then on (hands_off: never painted again); otherwise the few
-- back at Normal (a fire guard lifted) are painted again.
--
-- Cheap for the game: report() reads only the project records (no tile);
-- paint() goes in slices (o.max tiles and o.budget_ms a call, resumed by
-- a cursor in the save), so no call walks more than a slice, and nothing
-- here ever walks the map.
--
--   report()                    the `traffic` report section
--   paint(o, dry_run)           paint (or audit, o.audit) one level a slice
--   ai_value(x, y, z)           the value the AI painted on a tile, or nil
--                               (the fire guard restores it when it lifts)
--   tiles_of(p, dig_set)        a project's tiles and classes (pure)
--@module = true

local U = reqscript('ai-util')

TRAFFIC_KEY = 'ai-overseer/traffic'    -- {done = {[key] = rec}, hands_off = {[key] = tick}, cursor = {...}}
LOW_KINDS = {bedrooms = true, suites = true, tombs = true, hospital = true, farms = true}
HIGH_KINDS = {way_in = true}
SKIP_KINDS = {well = true}
FINISHED = {done = true, decorate = true}
SLICE_MAX = 5000              -- tiles a call at most (the brain sends less)
BUDGET_MS_MAX = 200
HANDS_OFF_OTHER = 0.25        -- this share set to another value since: the player's
HANDS_OFF_NORMAL = 0.5        -- this share back at Normal: the player wiped it
HANDS_OFF_MIN = 4             -- ...and never for fewer tiles than this (a fire guard lifted)
PENDING_LIST = 10
DEEP_KEY = 'deep'

local function now_tick()
    local ok, t = pcall(function() return U.abs_tick() end)
    return ok and math.tointeger(t) or 0
end

local function int(v) return math.tointeger(tonumber(v)) end

function load_state()
    local d = U.site_get(TRAFFIC_KEY, {})
    d.done = type(d.done) == 'table' and d.done or {}
    d.hands_off = type(d.hands_off) == 'table' and d.hands_off or {}
    if type(d.cursor) ~= 'table' then d.cursor = nil end
    return d
end

local function save_state(d) return U.site_put(TRAFFIC_KEY, d) end

function enabled()
    local ok, s = pcall(function() return reqscript('ai-overseer-settings').load_settings() end)
    if ok and type(s) == 'table' then return s.traffic ~= false end
    return true
end

local function builder() return reqscript('ai-builder') end

local function projects()
    local ok, data = pcall(function() return builder().load_projects() end)
    if ok and type(data) == 'table' and type(data.list) == 'table' then return data.list end
    return {}
end

local function deep_depot()
    local ok, d = pcall(function() return builder().deep_depot_data() end)
    if ok and type(d) == 'table' and type(d.tiles) == 'table' and #d.tiles > 0
            and d.stage ~= 'digging' and d.stage ~= 'no_road' then
        return d
    end
    return nil
end

local function pkey(p) return 'p' .. tostring(p.id) end

-- A project the AI may paint: finished, of a kind that's painted, with a level.
function paintable(p)
    return type(p) == 'table' and int(p.id) ~= nil and FINISHED[p.phase] == true
        and not SKIP_KINDS[p.kind] and int(p.z) ~= nil
        and type(p.anchor or p.stair) == 'table'
end

-- The dig cells' tiles, anchor-relative: set[x][y] = true ('d', 'd5' and
-- 'd(WxH)' cells, as ai-layouts tiles_from_dig; every other code one tile).
function dig_set(cells)
    local t = {}
    for _, c in ipairs(type(cells) == 'table' and cells or {}) do
        local x, y = type(c) == 'table' and int(c.x), type(c) == 'table' and int(c.y)
        if x and y then
            local w, h = 1, 1
            local ew, eh = tostring(c.text):match('^d%((%d+)x(%d+)%)$')
            if ew then w, h = tonumber(ew), tonumber(eh) end
            for dx = 0, w - 1 do
                for dy = 0, h - 1 do
                    t[x + dx] = t[x + dx] or {}
                    t[x + dx][y + dy] = true
                end
            end
        end
    end
    return t
end

local function has(set, x, y) return set[x] ~= nil and set[x][y] == true end

-- An older project's corridor (no p.links): from its stair toward its
-- anchor, along the longer axis, the first `n` of its own dug tiles
-- (n: the new corridor's length; the walked tiles were dug before and are
-- not the project's). Relative to the anchor. A dog-leg is only found to
-- its jog: what's past it stays Normal.
function fallback_links(p, set)
    local a, s = p.anchor, p.stair
    if type(a) ~= 'table' or type(s) ~= 'table' then return {} end
    local ax, ay, sx, sy = int(a.x), int(a.y), int(s.x), int(s.y)
    local n = int(p.new_corridor) or int(p.corridor) or 0
    if not (ax and ay and sx and sy) or n <= 0 then return {} end
    local dx, dy = ax - sx, ay - sy
    local ux, uy = 0, 0
    if math.abs(dx) >= math.abs(dy) then ux = dx > 0 and 1 or -1 else uy = dy > 0 and 1 or -1 end
    if dx == 0 and dy == 0 then return {} end
    local out, found = {}, 0
    for i = 1, n + (int(p.corridor) or n) + 2 do
        local rx, ry = sx + ux * i - ax, sy + uy * i - ay
        if has(set, rx, ry) then
            table.insert(out, {x = rx, y = ry})
            found = found + 1
            if found >= n then break end
        elseif found > 0 then
            break
        end
    end
    return out
end

-- A project's tiles in the order they're painted (High first), each
-- {x, y, z, v = 'high' | 'low'}, map coordinates, every tile once.
function tiles_of(p)
    local out, seen = {}, {}
    local function add(x, y, z, v)
        x, y, z = int(x), int(y), int(z)
        if not (x and y and z) then return end
        local k = x .. ',' .. y .. ',' .. z
        if seen[k] then return end
        seen[k] = true
        table.insert(out, {x = x, y = y, z = z, v = v})
    end
    local z = int(p.z)
    local a = p.anchor or p.stair
    local ax, ay = int(a.x) or 0, int(a.y) or 0
    local cells = type(p.cells) == 'table' and p.cells or {}
    local set = dig_set(cells.dig)
    if HIGH_KINDS[p.kind] then
        for _, c in ipairs(type(p.shaft_stairs) == 'table' and p.shaft_stairs or {}) do
            if type(c) == 'table' then add(c.x, c.y, c.z, 'high') end
        end
        for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do
            if type(g) == 'table' then add(g.x, g.y, g.z or z, 'high') end
        end
        for x, col in pairs(set) do
            for y in pairs(col) do add(ax + x, ay + y, z, 'high') end
        end
        return out
    end
    -- the stair: on this level, and the stair levels this project dug
    local s = type(p.stair) == 'table' and p.stair or nil
    if s then
        add(s.x, s.y, z, 'high')
        for _, c in ipairs(type(p.stairs) == 'table' and p.stairs or {}) do
            if type(c) == 'table' then add(s.x, s.y, c.z, 'high') end
        end
    end
    -- the corridor and avenue to the level
    local links = type(p.links) == 'table' and p.links or fallback_links(p, set)
    for _, l in ipairs(links) do
        if type(l) == 'table' and int(l.x) and int(l.y) then add(ax + l.x, ay + l.y, z, 'high') end
    end
    -- the rooms of a dead-end level
    if LOW_KINDS[p.kind] then
        local xs = {}
        for x in pairs(set) do table.insert(xs, x) end
        table.sort(xs)
        for _, x in ipairs(xs) do
            local ys = {}
            for y in pairs(set[x]) do table.insert(ys, y) end
            table.sort(ys)
            for _, y in ipairs(ys) do add(ax + x, ay + y, z, 'low') end
        end
    end
    return out
end

local function deep_tiles(d)
    local out, seen = {}, {}
    for _, t in ipairs(d.tiles) do
        if type(t) == 'table' and int(t.x) and int(t.y) and int(t.z) then
            local k = t.x .. ',' .. t.y .. ',' .. t.z
            if not seen[k] then
                seen[k] = true
                table.insert(out, {x = int(t.x), y = int(t.y), z = int(t.z), v = 'high'})
            end
        end
    end
    return out
end

-- Every unit the AI may paint: {key, kind, p | deep}, in project order.
local function units()
    local out = {}
    for _, p in ipairs(projects()) do
        if paintable(p) then table.insert(out, {key = pkey(p), kind = p.kind, id = p.id, p = p}) end
    end
    local d = deep_depot()
    if d then table.insert(out, {key = DEEP_KEY, kind = 'deep_depot', deep = d}) end
    return out
end

local function unit_tiles(u)
    if u.deep then return deep_tiles(u.deep) end
    return tiles_of(u.p)
end

local function find_unit(key)
    for _, u in ipairs(units()) do
        if u.key == key then return u end
    end
    return nil
end

local function want_of(v)
    return v == 'high' and df.tile_traffic.High or df.tile_traffic.Low
end

-- The report section: no tile read, only the records.
function report()
    local st = load_state()
    local pending, n_pending, painted, hands_off = {}, 0, 0, 0
    local audit
    local now = now_tick()
    for _, u in ipairs(units()) do
        local rec = st.done[u.key]
        if st.hands_off[u.key] then
            hands_off = hands_off + 1
        elseif type(rec) == 'table' then
            painted = painted + 1
            local last = int(rec.checked) or int(rec.t) or 0
            if not audit or last < audit.last then
                audit = {key = u.key, kind = u.kind, last = last}
            end
        else
            n_pending = n_pending + 1
            if #pending < PENDING_LIST then table.insert(pending, {key = u.key, kind = u.kind}) end
        end
    end
    local cur = st.cursor
    local out = {enabled = enabled(), pending = pending, pending_total = n_pending, painted = painted,
                 hands_off = hands_off,
                 tiles = int(st.tiles) or 0,
                 cursor = cur and {key = cur.key, at = int(cur.at) or 0} or nil}
    if audit then
        out.audit_next = {key = audit.key, kind = audit.kind, days = math.max(0, (now - audit.last) // 1200)}
    end
    return out
end

local function reject(why, extra)
    local r = {ok = false, rejected = true, error = why}
    for k, v in pairs(extra or {}) do r[k] = v end
    return r
end

-- One call: paint one level a slice (o.key, or none given the one in
-- progress, else the first waiting), o.max tiles and o.budget_ms at most,
-- resumed next call where it stopped; or (o.audit) recheck a painted level.
function paint(o, dry_run)
    o = type(o) == 'table' and o or {}
    if not enabled() then return reject('traffic zones are off on the Rules tab') end
    local max = math.max(1, math.min(SLICE_MAX, int(o.max) or 1500))
    local budget = math.max(5, math.min(BUDGET_MS_MAX, int(o.budget_ms) or 40)) / 1000
    local st = load_state()
    local key = type(o.key) == 'string' and o.key or nil
    if o.audit == true then
        if not key then return reject('a recheck needs the level (key)') end
        return audit(st, key, max, budget, dry_run)
    end
    if not key and st.cursor then key = st.cursor.key end
    if not key then
        local r = report()
        if r.pending[1] then key = r.pending[1].key end
    end
    if not key then return reject('every finished level already has its traffic', {nothing_to_do = true}) end
    local function drop_cursor()
        if st.cursor and st.cursor.key == key and not dry_run then st.cursor = nil; save_state(st) end
    end
    if st.hands_off[key] then
        drop_cursor()
        return reject(key .. ' is the player\'s now (changed by hand)', {nothing_to_do = true})
    end
    if type(st.done[key]) == 'table' then
        drop_cursor()
        return reject(key .. ' already painted', {nothing_to_do = true})
    end
    local u = find_unit(key)
    if not u then
        -- (0.105.41 review) the saved cursor's level stopped being paintable:
        -- nothing to do (the cursor dropped, the next call takes the next
        -- level), not a refusal that would hold all painting back
        local was_cursor = st.cursor and st.cursor.key == key
        drop_cursor()
        return reject('no finished AI level ' .. key, was_cursor and {nothing_to_do = true} or nil)
    end
    local tiles = unit_tiles(u)
    local cur = (st.cursor and st.cursor.key == key) and st.cursor
        or {key = key, at = 0, painted = 0, kept = 0, other = 0, high = 0, low = 0}
    local Normal = df.tile_traffic.Normal
    local t0 = os.clock()
    local i, n = int(cur.at) or 0, 0
    while i < #tiles and n < max do
        i, n = i + 1, n + 1
        local t = tiles[i]
        local want = want_of(t.v)
        local ok, des = pcall(dfhack.maps.getTileFlags, t.x, t.y, t.z)
        if ok and des then
            if des.traffic == want then
                cur.kept = cur.kept + 1
            elseif des.traffic == Normal then
                if not dry_run then des.traffic = want end
                cur.painted = cur.painted + 1
                cur[t.v] = (int(cur[t.v]) or 0) + 1
            else
                cur.other = cur.other + 1      -- the player's (or a guard's): left
            end
        end
        if os.clock() - t0 > budget then break end
    end
    local finished = i >= #tiles
    if not dry_run then
        if finished then
            st.done[key] = {t = now_tick(), painted = cur.painted, kept = cur.kept, other = cur.other,
                            high = cur.high, low = cur.low, n = #tiles}
            st.cursor = nil
            st.tiles = (int(st.tiles) or 0) + cur.painted
        else
            cur.at = i
            st.cursor = cur
        end
        save_state(st)
    end
    return {ok = true, key = key, kind = u.kind, tiles = #tiles, at = i, finished = finished,
            painted = cur.painted, kept = cur.kept, other = cur.other, high = cur.high, low = cur.low,
            dry_run = dry_run or nil, ms = math.floor((os.clock() - t0) * 1000 + 0.5)}
end

-- A painted level counted again (its first `max` tiles: a sample of a bigger
-- one). Much changed since: the player's from now on. Otherwise the tiles
-- back at Normal (a guard lifted) are painted again.
function audit(st, key, max, budget, dry_run)
    local rec = st.done[key]
    if st.hands_off[key] then return reject(key .. ' is the player\'s now', {nothing_to_do = true}) end
    if type(rec) ~= 'table' then return reject(key .. ' was never painted: nothing to recheck') end
    local u = find_unit(key)
    if not u then return reject('no finished AI level ' .. key) end
    local tiles = unit_tiles(u)
    local Normal = df.tile_traffic.Normal
    local t0 = os.clock()
    local kept, other, guarded, back = 0, 0, 0, {}
    local n = 0
    for i = 1, math.min(#tiles, max) do
        local t = tiles[i]
        local want = want_of(t.v)
        local ok, des = pcall(dfhack.maps.getTileFlags, t.x, t.y, t.z)
        if ok and des then
            n = n + 1
            if des.traffic == want then kept = kept + 1
            elseif des.traffic == Normal then table.insert(back, {des = des, want = want})
            elseif des.traffic == df.tile_traffic.Restricted then guarded = guarded + 1   -- a guard's (fire, ice): not counted
            else other = other + 1 end
        end
        if os.clock() - t0 > budget then break end
    end
    local total = math.max(1, int(rec.n) or #tiles)
    -- what was the player's already when it was painted, and what the AI set, in this sample
    local other_then = (int(rec.other) or 0) * n // total
    local mine = math.max(1, (int(rec.painted) or 0) * n // total)
    local out = {ok = true, key = key, kind = u.kind, audit = true, checked = n, tiles = #tiles,
                 kept = kept, normal = #back, other = other, restricted = guarded, dry_run = dry_run or nil}
    if n > 0 and (other - other_then >= math.max(HANDS_OFF_MIN, HANDS_OFF_OTHER * n)
            or #back >= math.max(HANDS_OFF_MIN, HANDS_OFF_NORMAL * mine)) then
        out.hands_off = true
        if not dry_run then
            st.hands_off[key] = now_tick()
            save_state(st)
        end
    else
        if not dry_run then
            for _, b in ipairs(back) do b.des.traffic = b.want end
            rec.checked = now_tick()
            rec.repainted = (int(rec.repainted) or 0) + #back
            st.tiles = (int(st.tiles) or 0) + #back
            save_state(st)
        end
        out.repainted = #back
    end
    out.ms = math.floor((os.clock() - t0) * 1000 + 0.5)
    return out
end

-- The value the AI painted on (x, y, z), or nil (not one of its painted
-- tiles, or a level that's the player's now). Builds the set once a call
-- of `memo` (pass the same table to reuse it).
function ai_value(x, y, z, memo)
    memo = type(memo) == 'table' and memo or {}
    if not memo.map then
        local st = load_state()
        local m = {}
        for _, u in ipairs(units()) do
            if type(st.done[u.key]) == 'table' and not st.hands_off[u.key] then
                for _, t in ipairs(unit_tiles(u)) do m[t.x .. ',' .. t.y .. ',' .. t.z] = want_of(t.v) end
            end
        end
        memo.map = m
    end
    return memo.map[x .. ',' .. y .. ',' .. z]
end
