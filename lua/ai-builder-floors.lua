-- ai-builder-floors: (layout B) hallway-first floors: the site on a floor. A new level's place
-- along the 3-wide main hall that runs out from the central stair on a floor (z-level), as an
-- ordinary site and an ordinary layout start_project can dig; or nil and why, and the level is
-- placed the classic way (choose_site).
--
-- A part of ai-builder, not a script of its own: ai-builder.lua loads it into its own
-- environment, so every name here is reqscript('ai-builder').name and the helpers defined there
-- (info, check_site, ...) are in reach.
--
-- This part is the only code that looks at the map for the floors. Where things go is decided by
-- the pure modules (ai-floorunits cuts a level into room units and composes the result,
-- ai-floorplan owns the floor records and the grammar, ai-floorplace picks the slots); they see
-- the map only through the `env` built here, which wraps the builder's own safety checks
-- (check_site, natural_wall, room_tiles, the saved projects' boxes). Nothing here designates or
-- saves anything: floor_commit (ai-builder-floorstore) writes the record once the project is saved.
--
-- No reqscript while this part loads (the modules are fetched inside floor_site, behind pcall);
-- the sibling parts' functions (load_floors, floor_pile_units) are asked for by type() first.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-floors'] = '0.105.89'   -- (0.105.26) bumped with BRIDGE_VERSION

FLOOR_SECONDS = 1.5          -- the floor search's share of a start_project (the classic search keeps its own 4 s)
FLOORS_TRY = 3               -- floors `place` is really tried on, for one level
FLOOR_LEVELS_SCAN = 8        -- levels looked at in all (a level with no free direction costs only its survey)
FLOOR_STAIRS = 3             -- stairs tried: the hint's first, then the most used
FLOOR_KINDS = {bedrooms = true, suites = true, jail = true, dining = true, storage = true, workshops = true,
               temple = true, memorial = true, garden = true, hospital = true, barracks = true, archery = true,
               tombs = true, tavern = true, library = true}       -- never farms (they follow the soil)
-- the default district tag of each kind (the brain's hint names its own)
FLOOR_TAGS = {bedrooms = 'homes', suites = 'homes', dining = 'homes', tavern = 'homes', hospital = 'homes',
              temple = 'halls', library = 'halls', memorial = 'halls', garden = 'halls', tombs = 'halls',
              jail = 'defence', barracks = 'defence', archery = 'defence',
              storage = 'storage', workshops = 'industry'}
FLOOR_WHY_MAX = 300          -- the reasons a level did not go onto a floor, in characters
-- (F4, S4) a floor that answered "refused: ..." for a request is not searched again for the same
-- request (kind, tag, units, floor and its record's size) for this many days: the reason is given
-- again and the next floor (or the classic search) is tried, as before. In memory only, never saved;
-- forgotten when the clock goes back or the projects record is another fort's (next_id below the top seen).
FLOOR_REFUSED_DAYS = 3
-- (r3 g2) switches: a full floor opens another arm out of the hub (hint spill = false: not);
-- a level too big for any run of its grammar goes the classic way at once (no other floor tried);
-- a "no room" mark keeps off only levels as big as the one refused; classic levels keep clear of
-- the floors' hubs and planned halls (FLOOR_KEEP_ARM columns out each free way from a live hub)
FLOOR_SPILL = true
FLOOR_BIG_STOP = true
FLOOR_FULL_BY_SIZE = true
FLOOR_KEEP_CLEAR = true
FLOOR_KEEP_ARM = 12
FLOOR_REFUSED_MAX = 200      -- notes kept at most (all dropped past it)
FLOOR_REFUSED = FLOOR_REFUSED or {notes = {}, n = 0, top = 0}
-- (r3 g1) floors that keep opening. Each a switch (false or 0: as before).
FLOOR_STAIR_TRIES = 1        -- floors tried on each stair after the first, beyond FLOORS_TRY (the hint's
                             -- stair_tries says it for the brain): the first stair's no-rooms no longer
                             -- use up the search before another stair is looked at
FLOOR_STAIRS_MORE = 4        -- stairs tried at most when the hint names other stairs (`stairs`)
FLOOR_STAIRS_APART = true    -- a stair within STAIRWELL_APART of one already taken (a 2x2 stair, the
                             -- shaft's side stair) is the same stairwell: not tried again
FLOOR_HUB_MARK = true        -- "refused: the stair's hub" marks the level '*' (no hall can start here,
                             -- full_retry_days) like "no hall", at the cost of its survey only: a floor
                             -- whose levels were all cancelled and whose hub the fort then used (D's
                             -- floor 3, refused x39) is skipped, reported no_hall/dead, and looked at
                             -- again only after full_retry_days

local has, add = has, add

---------------------------------------------------------------------------
-- Small helpers
---------------------------------------------------------------------------

local function compass(dx, dy)
    if dx > 0 then return 'east' end
    if dx < 0 then return 'west' end
    if dy > 0 then return 'south' end
    return 'north'
end

-- Tiles given as a list ({x=, y=} or {x, y}) or as a set ({[x] = {[y] = true}}), as a set.
-- Returns the set and its box (nil when empty).
local function tile_set(tiles)
    local set, box = {}, nil
    local function put(x, y)
        x, y = math.tointeger(x), math.tointeger(y)
        if not x or not y or has(set, x, y) then return end
        add(set, x, y)
        if not box then
            box = {x1 = x, y1 = y, x2 = x, y2 = y}
        else
            box.x1, box.x2 = math.min(box.x1, x), math.max(box.x2, x)
            box.y1, box.y2 = math.min(box.y1, y), math.max(box.y2, y)
        end
    end
    for k, v in pairs(type(tiles) == 'table' and tiles or {}) do
        if type(v) == 'table' then
            if type(v.x) == 'number' and type(v.y) == 'number' then
                put(v.x, v.y)
            elseif type(v[1]) == 'number' and type(v[2]) == 'number' then
                put(v[1], v[2])
            else
                for y, on in pairs(v) do if on == true then put(k, y) end end
            end
        end
    end
    return set, box
end

-- A saved box (x1, y1, x2, y2 as whole numbers), or nil.
local function whole_box(a)
    if type(a) ~= 'table' then return nil end
    local x1, y1, x2, y2 = math.tointeger(a.x1), math.tointeger(a.y1), math.tointeger(a.x2), math.tointeger(a.y2)
    if not (x1 and y1 and x2 and y2) or x1 > x2 or y1 > y2 then return nil end
    return {x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = math.tointeger(a.z)}
end

-- A box without its 1-tile border (as it is when the border is all there is).
local function shrunk(b)
    if b.x2 - b.x1 < 2 or b.y2 - b.y1 < 2 then return b end
    return {x1 = b.x1 + 1, y1 = b.y1 + 1, x2 = b.x2 - 1, y2 = b.y2 - 1, z = b.z}
end

-- Is the saved project `p` one of the floor's own (on its level, hanging on its stair)?
local function floor_project(p, floor, sx, sy, z)
    if type(p) ~= 'table' or type(p.floor) ~= 'table' or p.floor.id == nil or p.floor.id ~= floor.id then
        return false
    end
    if math.tointeger(p.z) ~= z then return false end
    -- (the record of the floors lost and begun again would hand an old id out twice: the stair says whose)
    local st = type(p.stair) == 'table' and p.stair or anchor_of(p)
    return type(st) == 'table' and math.tointeger(st.x) == sx and math.tointeger(st.y) == sy
end

-- The node and hall tiles of a run as the contract draws them (stair-relative), into `set`.
local function run_tiles(set, r)
    local ox, oy = math.tointeger(r.ox), math.tointeger(r.oy)
    local dx, dy = math.tointeger(r.dx), math.tointeger(r.dy)
    local len = math.tointeger(r.len) or 0
    if not (ox and oy and dx and dy) then return end
    local px, py = -dy, dx
    local n = (math.tointeger(r.node) == 5) and 2 or 1
    for u = -n, n do
        for v = -n, n do add(set, ox + u * dx + v * px, oy + u * dy + v * py) end
    end
    for u = n + 1, n + len do
        for v = -1, 1 do add(set, ox + u * dx + v * px, oy + u * dy + v * py) end
    end
end

---------------------------------------------------------------------------
-- env: the placement module's eyes on one level
---------------------------------------------------------------------------

-- The env ai-floorplace reads a level through (all coordinates stair-relative).
--   floor     the floor's record (its id and slot count; its own projects are told by floor.id)
--   stair     the stair column the floor hangs on ({x, y}); z: the level
--   data      load_projects()'s record; reserved: the open projects' areas (start_project's list)
--   claims    the floor's own tiles ({[x] = {[y] = true}}, ai-floorplan.claims), or nil
--   deadline  os.clock() the call must end by, or nil
-- Reads only. env.probe_own (the floor's others' areas) and env.exempt_for serve floor_site's last check.
function floor_env(floor, stair, z, data, reserved, claims, deadline)
    local sx, sy = stair.x, stair.y
    claims = type(claims) == 'table' and claims or {}
    if type(data) ~= 'table' then
        local ok, d = pcall(load_projects)
        data = ok and d or {}
    end
    local list = type(data.list) == 'table' and data.list or {}
    local group = walk_group(sx, sy, z)
    local rooms = room_tiles(z, data)

    -- the tiles of the others on this level (map coordinates), and the open projects' areas that are the floor's own
    local boxes, own_area = {}, {}
    local function area_key(a)
        return ('%s,%s,%s,%s,%s'):format(tostring(a.x1), tostring(a.y1), tostring(a.x2), tostring(a.y2), tostring(a.z))
    end
    for _, p in ipairs(list) do
        if type(p) == 'table' then
            if floor_project(p, floor, sx, sy, z) then
                for _, a in ipairs(project_areas(p)) do own_area[a] = true; own_area[area_key(a)] = true end
            else
                local pz = math.tointeger(p.z)
                local a = whole_box(p.area)
                if a and (a.z or pz) == z then table.insert(boxes, shrunk(a)) end
                for _, more in ipairs(type(p.areas) == 'table' and p.areas or {}) do
                    local b = whole_box(more)
                    if b and (b.z or pz) == z then table.insert(boxes, b) end
                end
            end
        end
    end
    -- a dropped level's outline: another's, unless it is the floor's own (a box round its rooms or
    -- its hall: without its border, each of its four edges holds a tile the floor claims)
    local function own_old(b)
        local s = shrunk(b)
        local function row(y)
            for x = s.x1, s.x2 do if has(claims, x - sx, y - sy) then return true end end
            return false
        end
        local function col(x)
            for y = s.y1, s.y2 do if has(claims, x - sx, y - sy) then return true end end
            return false
        end
        return row(s.y1) and row(s.y2) and col(s.x1) and col(s.x2)
    end
    for _, a in ipairs(type(data.old_areas) == 'table' and data.old_areas or {}) do
        local b = whole_box(a)
        if b and b.z == z and not own_old(b) then table.insert(boxes, b) end
    end
    local others = {}
    for _, r in ipairs(type(reserved) == 'table' and reserved or {}) do
        if type(r) == 'table' and not own_area[r] and not own_area[area_key(r)] then table.insert(others, r) end
    end

    local env = {}
    local open_memo = {}

    -- 'rock': untouched natural rock; 'open': the fort's own dry floor the stair's dwarves walk,
    -- with no room, building or zone on it; 'bad': anything else
    function env.open(x, y)
        x, y = math.tointeger(x), math.tointeger(y)
        if not x or not y then return 'bad' end
        local k = (y + 8192) * 16384 + (x + 8192)
        local v = open_memo[k]
        if v then return v end
        local X, Y = sx + x, sy + y
        local t = info(X, Y, z)
        if natural_wall(t) then
            v = 'rock'
        elseif t and t.shape ~= 'WALL' and not t.liquid and not t.aquifer and not t.feature and not t.outside
                and group ~= 0 and walk_group(X, Y, z) == group
                and not has(rooms, X, Y) and not tile_taken(X, Y, z) then
            v = 'open'
        else
            v = 'bad'
        end
        open_memo[k] = v
        return v
    end

    -- does the box meet another project's tiles (or a dropped level's outline)?
    function env.blocked(x1, y1, x2, y2)
        if type(x1) == 'table' then
            local b = x1
            x1, y1, x2, y2 = b.x1 or b[1], b.y1 or b[2], b.x2 or b[3], b.y2 or b[4]
        end
        if not (x1 and y1 and x2 and y2) then return true end
        if x1 > x2 then x1, x2 = x2, x1 end
        if y1 > y2 then y1, y2 = y2, y1 end
        local X1, Y1, X2, Y2 = sx + x1, sy + y1, sx + x2, sy + y2
        for _, b in ipairs(boxes) do
            if X1 <= b.x2 and b.x1 <= X2 and Y1 <= b.y2 and b.y1 <= Y2 then return true end
        end
        return false
    end

    -- may all `tiles` be dug? check_site on a pseudo-layout of them (every rule of a new level:
    -- natural rock, no aquifer, water or magma on or above, no feature, not under the sky, not
    -- warm, the dig guard, the map's edge, the open projects' areas, no corner-only gap).
    -- A border tile may be open where it is the floor's own (`known`), the stair, or (role
    -- 'hall' only) the fort's open floor.
    function env.probe(tiles, known, role)
        local set, box = tile_set(tiles)
        if not box then return true end
        local own = tile_set(known)
        local pseudo = {tiles = set, bounds = box}
        local ok, why = check_site(pseudo, {}, sx, sy, z, others, {x = 0, y = 0}, function(X, Y)
            local x, y = X - sx, Y - sy
            if (x == 0 and y == 0) or has(own, x, y) then return true end
            return role == 'hall' and env.open(x, y) == 'open'
        end)
        if ok then return true end
        return false, why
    end

    function env.late()
        return deadline ~= nil and os.clock() > deadline
    end

    local w, h = map_size()
    env.bounds = {x1 = 2 - sx, y1 = 2 - sy, x2 = w - 3 - sx, y2 = h - 3 - sy}
    env.seed = (math.tointeger(floor.id) or 0) * 31 + (type(floor.slots) == 'table' and #floor.slots or 0)
    env.others = others            -- (for floor_site's last check; ai-floorplace reads none of the two)
    env.claims = claims
    return env
end

---------------------------------------------------------------------------
-- Which stairs, which levels
---------------------------------------------------------------------------

-- The hint's levels as a band for spine_first (where to look for the spine's stair), or the plan's.
local function hint_band(hint, plan)
    local lo, hi, first
    for _, e in ipairs(type(hint.elevs) == 'table' and hint.elevs or {}) do
        local z = math.tointeger(e)
        if z then
            z = z - OFFSET
            first = first or z
            lo, hi = math.min(lo or z, z), math.max(hi or z, z)
        end
    end
    if first then return {lo = lo, hi = hi, target = first} end
    return plan_band(plan)
end

-- (r3 g1) The number of floors tried on each stair after the first (0: the old search, FLOORS_TRY
-- in all): the hint's stair_tries, else FLOOR_STAIR_TRIES.
local function stair_tries(hint)
    local n = math.tointeger(hint.stair_tries)
    if n == nil then n = math.tointeger(FLOOR_STAIR_TRIES) or 0 end
    return math.max(0, math.min(3, n))
end

-- (r3 g1) The stair list with `st` ({x, y}, a stair the brain knows: a district's stairwell, the
-- survey's) in it, right after the first (the spine): spine_first finds it where the dwarves walk.
-- Returns the list and whether it was put in.
local function with_stair(list, st, band, at)
    local sx, sy = math.tointeger(type(st) == 'table' and st.x), math.tointeger(type(st) == 'table' and st.y)
    if not (sx and sy) then return list, false end
    for i, s in ipairs(list) do
        if s.x == sx and s.y == sy then
            if i <= at then return list, false end
            local out = {}
            for j = 1, at - 1 do out[#out + 1] = list[j] end
            out[#out + 1] = s
            for j = at, #list do if j ~= i then out[#out + 1] = list[j] end end
            return out, true
        end
    end
    local ok, l2 = pcall(spine_first, list, {spine = {x = sx, y = sy}}, band)
    if not (ok and type(l2) == 'table' and #l2 > #list and l2[1].x == sx and l2[1].y == sy) then return list, false end
    local out = {}
    for j = 1, at - 1 do out[#out + 1] = list[j] end
    out[#out + 1] = l2[1]
    for j = at, #list do out[#out + 1] = list[j] end
    return out, true
end

-- The stairs a floor may hang on, FLOOR_STAIRS at most: the hint's spine when it is a stair the
-- dwarves use, then the others in their own order. (r3 g1) With stair_tries on: the stairs the
-- hint names (`stairs`) right after the spine, and FLOOR_STAIRS_MORE at most when it names any;
-- one stair a stairwell (FLOOR_STAIRS_APART).
local function floor_stairs(stairs, hint, plan)
    local list = stairs
    if type(hint.spine) == 'table' then
        local ok, l2 = pcall(spine_first, stairs, {spine = hint.spine}, hint_band(hint, plan))
        if ok and type(l2) == 'table' and #l2 > 0 then list = l2 end
    end
    local more = stair_tries(hint) > 0
    local named = 0
    if more and type(hint.stairs) == 'table' and #list > 0 then
        local band = hint_band(hint, plan)
        for i, st in ipairs(hint.stairs) do
            if i > 6 then break end
            local put
            list, put = with_stair(list, st, band, 2 + named)
            if put then named = named + 1 end
        end
    end
    local cap = FLOOR_STAIRS
    if named > 0 then cap = math.max(cap, math.min(math.tointeger(FLOOR_STAIRS_MORE) or cap, 1 + named)) end
    local apart = more and FLOOR_STAIRS_APART and (math.tointeger(STAIRWELL_APART) or 6) or 0
    local out = {}
    for _, s in ipairs(list) do
        if #out >= cap then break end
        local alone = true
        for _, k in ipairs(out) do
            if math.max(math.abs(k.x - s.x), math.abs(k.y - s.y)) < apart then alone = false break end
        end
        if alone then out[#out + 1] = s end
    end
    return out
end

-- One stair's levels to try, in order: {z, extend}. The hint's elevations in its order; else the
-- plan's band, nearest its target; else the stair's levels nearest the dwarves. A level under the
-- stair's bottom comes after every level the stair reaches, and only within the plan's reach.
local function floor_levels(stair, hint, band, ceil_z)
    local reach = (band and band.extend) or PLAN_EXTEND
    local through, below, seen = {}, {}, {}
    local function take(z, extend)
        if seen[z] or (ceil_z and z > ceil_z) or z < 1 then return end
        seen[z] = true
        if not extend and z >= stair.z_bottom and z <= stair.z_top then
            table.insert(through, {z = z, extend = false})
        elseif z < stair.z_bottom and z >= stair.z_bottom - reach then
            table.insert(below, {z = z, extend = true})
        end
    end
    local elevs = {}
    for _, e in ipairs(type(hint.elevs) == 'table' and hint.elevs or {}) do
        local z = math.tointeger(e)
        if z then table.insert(elevs, z - OFFSET) end
    end
    if #elevs > 0 then
        for _, z in ipairs(elevs) do take(z, false) end
    elseif band then
        for _, lv in ipairs(stair_levels(stair, band, true, 'near')) do take(lv.z, lv.extend) end
    else
        for _, lv in ipairs(stair_levels(stair, nil, false)) do take(lv.z, lv.extend) end
    end
    for _, lv in ipairs(below) do table.insert(through, lv) end
    return through
end

---------------------------------------------------------------------------
-- The request
---------------------------------------------------------------------------

-- The hint as the brain sent it (params.floor), or the builder's own plain one; the kind's
-- default tag, zone and workshop group where the hint names none.
local function floor_hint(params)
    local kind = params.kind
    local hint = {}
    for k, v in pairs(type(params.floor) == 'table' and params.floor or {}) do hint[k] = v end
    if type(hint.tag) ~= 'string' or hint.tag == '' then hint.tag = FLOOR_TAGS[kind] end
    if type(hint.zone) ~= 'string' then hint.zone = (kind == 'hospital') and 'far' or 'any' end
    if hint.group == nil and kind == 'workshops' and type(params.shops) == 'table' then
        hint.group = WORKSHOP_GROUPS[params.shops[1] or '']
    end
    return hint
end

-- One unit as the request names it.
local function req_unit(u, role, flag)
    return {w = u.w, d = u.d, open = u.open, role = role, flag = flag}
end

---------------------------------------------------------------------------
-- floor_site
---------------------------------------------------------------------------

-- The three pure modules and the saved record's reader, or nil when any is missing.
local function floor_modules()
    if type(load_floors) ~= 'function' then return nil end
    local M = {}
    for key, name in pairs({units = 'ai-floorunits', plan = 'ai-floorplan', place = 'ai-floorplace'}) do
        local ok, m = pcall(reqscript, name)
        if not (ok and type(m) == 'table') then return nil end
        M[key] = m
    end
    return M
end

-- (V3) The columns one side of a full-length run holds for rooms: the run less its lead,
-- what is kept ahead and a neck's column (the stagger is the other side's only). A workshop
-- and its pile rooms must fit in it.
local function shop_room(G)
    local n = (tonumber(G.run_max) or 30) - (tonumber(G.lead) or 0) - (tonumber(G.ahead) or 0)
    if G.neck then n = n - 1 end
    return n
end

-- The level on one floor: site, L2; or nil, why, mark ('*', the tag, or nil), free.
-- c.looked / c.tried count what it cost.
local function on_floor(c, stair, z, extend, floor, is_new)
    local M, params, G, hint = c.M, c.params, c.G, c.hint
    local sx, sy = stair.x, stair.y
    c.looked = c.looked + 1
    if extend then
        local ok, why = check_extension(sx, sy, stair.z_bottom, z)
        if not ok then return nil, why end
    end
    local okc, claims = pcall(M.plan.claims, floor)
    if not okc or type(claims) ~= 'table' then claims = {} end
    local env = floor_env(floor, stair, z, c.data, c.reserved, claims, c.deadline)

    -- the request: a workshops level's pile rooms first, then the level's own units
    local units, req_units, pile_meta, extra_units = {}, {}, {}, {}
    -- (V3) a workshops level is placed as clusters, each shop beside its own pile rooms: the
    -- columns each shop's cluster has taken so far, and the pile rooms that go with it
    local shop_of, cl_cols, cl_piles = {}, {}, {}
    local room = shop_room(G)
    if c.kind == 'workshops' then
        for i, u in ipairs(c.units) do
            local name = type(u.tag) == 'string' and u.tag:match('^shop:(.+)$') or nil
            if name and not shop_of[name] then shop_of[name] = i end
            cl_cols[i], cl_piles[i] = u.w, {}
        end
    end
    -- the cluster a pile room joins: its shop's (the level's first shop when its shop is not
    -- there), and only while the cluster still fits one run; nil: the room is left out
    local function join_cluster(shop, w)
        local i = shop and shop_of[shop] or nil
        if not i then
            for j, u in ipairs(c.units) do
                if type(u.tag) == 'string' and u.tag:match('^shop:') then i = j break end
            end
        end
        i = i or 1
        if not cl_cols[i] or cl_cols[i] + G.gap + w > room then return nil end
        cl_cols[i] = cl_cols[i] + G.gap + w
        return i
    end
    -- the level's own pile room (the ore_piles custom): beside the first shop it can feed
    local own_pile_at = {}
    if c.kind == 'workshops' then
        for i, u in ipairs(c.units) do
            if u.tag == 'pile' then
                local to
                for name, j in pairs(shop_of) do
                    local f = type(FEEDERS) == 'table' and FEEDERS[name] or nil
                    if type(f) == 'table' and f.flag == 'stone' and (not to or j < to) then to = j end
                end
                if to and cl_cols[to] + G.gap + u.w <= room then
                    cl_cols[to] = cl_cols[to] + G.gap + u.w
                    own_pile_at[i] = to
                end
            end
        end
    end
    if c.kind == 'workshops' and type(floor_pile_units) == 'function' then
        local phint = {}
        for k, v in pairs(hint) do phint[k] = v end
        phint.pile_w, phint.piles_new = G.pile_w or hint.pile_w, G.piles_new or hint.piles_new
        local function has_flag(flag)
            if c.own_piles[flag] then return true end      -- (the level brings that pile itself: ore_piles)
            for _, s in ipairs(type(floor.slots) == 'table' and floor.slots or {}) do
                if type(s) == 'table' and s.role == 'pile' and s.flag == flag and not s.dead
                        and (s.tag == nil or s.tag == hint.tag) then
                    return true
                end
            end
            return false
        end
        local list = floor_pile_units(params, phint, has_flag)
        for _, pu in ipairs(type(list) == 'table' and list or {}) do
            if type(pu) == 'table' and type(pu.flag) == 'string' then
                local size = math.tointeger(pu.room_size) or 5
                local key = pu.flag .. ':' .. size
                local unit = c.pile_cache[key]
                if unit == nil then
                    unit = false
                    local pp = M.units.unit_params({kind = 'storage', piles = {pu.flag}, room_size = size,
                                                    style = params.style})
                    local Lp = layouts.make('storage', pp)
                    if Lp then
                        local us = M.units.cut(Lp, pp)
                        if type(us) == 'table' and us[1] then unit = us[1] end
                    end
                    c.pile_cache[key] = unit
                end
                local at = unit and join_cluster(pu.shop, unit.w) or nil
                if unit and at then
                    table.insert(cl_piles[at], #units + 1)
                    table.insert(units, unit)
                    table.insert(extra_units, unit)
                    table.insert(req_units, req_unit(unit, 'pile', pu.flag))
                    pile_meta[#units] = {flag = pu.flag, shop = pu.shop}
                end
            end
        end
    end
    local npiles = #units
    for i, u in ipairs(c.units) do
        table.insert(units, u)
        table.insert(req_units, c.req_units[i])
    end
    local clusters
    if c.kind == 'workshops' then
        -- each of the level's units in order, its pile rooms (and the custom's own) before it
        clusters = {}
        for i in ipairs(c.units) do
            if not own_pile_at[i] then
                local cl = {}
                for _, k in ipairs(cl_piles[i] or {}) do table.insert(cl, k) end
                for j, to in pairs(own_pile_at) do
                    if to == i then table.insert(cl, npiles + j) end
                end
                table.sort(cl)
                table.insert(cl, npiles + i)
                table.insert(clusters, cl)
            end
        end
    end
    local req = {kind = c.kind, tag = hint.tag, group = hint.group, zone = hint.zone, units = req_units,
                 together = c.kind == 'workshops', clusters = clusters, axial = c.axial, min_u = nil}
    if c.kind == 'hospital' then
        req.min_u, req.zone = HOSPITAL_STAIR_GAP + 1, 'far'
    end

    local free = {}
    for k, v in pairs(M.place.survey(floor, G, env) or {}) do free[k] = v end
    free.tick = now_tick()
    c.tried = c.tried + 1
    local placement, why = M.place.place(floor, req, G, env)
    if type(placement) ~= 'table' then
        why = tostring(why or 'no place')
        if why:sub(1, 7) == 'no hall' then
            c.tried = c.tried - 1          -- (it cost only its survey)
            return nil, why, '*', free
        end
        -- (r3 g1) a hub the fort used for something else: no hall can start here either (marked, so
        -- the level is not offered again for full_retry_days; B's z38/z42, D's floor 3 x39)
        if FLOOR_HUB_MARK and why:sub(1, 24) == "refused: the stair's hub" then
            c.tried = c.tried - 1
            return nil, why, '*', free
        end
        if why:sub(1, 7) == 'no room' then
            -- (V3) full only when the request could have gone onto an empty run of this grammar;
            -- a request too big for any run leaves the floor unmarked
            if type(M.place.fits_empty) == 'function' then
                local okf, fits = pcall(M.place.fits_empty, req, G)
                if okf and fits == false then
                    -- (r3 g2) told apart from a full floor: the run it would need (nil: none can
                    -- take it), in the answer (floor_big) for the brain, and no other floor tried
                    local need
                    if type(M.place.need_run) == 'function' then
                        local okn, n = pcall(M.place.need_run, req, G, function(rm)
                            local h2 = {}
                            for k, v in pairs(hint) do h2[k] = v end
                            h2.run_max = rm
                            return M.plan.grammar(h2)
                        end)
                        if okn then need = math.tointeger(n) end
                    end
                    c.big = {need = need, run_max = math.tointeger(G.run_max), kind = c.kind}
                    return nil, 'too big for a run' .. (need
                        and (' (needs a run of %d, this one is %d)'):format(need, math.tointeger(G.run_max) or 0)
                        or ' (no run can take it)')
                end
            end
            return nil, why, hint.tag, free
        end
        return nil, why
    end
    local puts = type(placement.puts) == 'table' and placement.puts or {}
    if #puts == 0 then return nil, 'refused: the placement holds no room' end

    -- the level as it will be dug, and one last check over all of it
    -- (puts[i].unit counts the pile rooms, extra_units, first, then the level's own units: as req.units)
    local L2 = M.units.compose(c.units, c.uinfo, placement,
                               {hall_pri = params.urgent == true and 1 or 3, extra_units = extra_units,
                                statues = math.tointeger(type(c.uinfo.style) == 'table' and c.uinfo.style.statues) or 0})
    if type(L2) ~= 'table' or type(L2.tiles) ~= 'table' or next(L2.tiles) == nil then
        return nil, 'refused: the level could not be composed'
    end
    if has(L2.tiles, 0, 0) then return nil, 'refused: the stair tile is in the dig' end
    if type(L2.bounds) ~= 'table' then
        local _, box = tile_set(L2.tiles)
        L2.bounds = box
    end
    local hall = tile_set(placement.hall)
    local known = {}
    for x, col in pairs(claims) do
        for y, on in pairs(col) do if on == true then add(known, x, y) end end
    end
    for _, r in ipairs(type(placement.runs) == 'table' and placement.runs or {}) do
        if type(r) == 'table' then run_tiles(known, r) end
    end
    local function new_room(x, y) return has(L2.tiles, x, y) and not has(hall, x, y) end
    local ok, why2 = check_site(L2, {}, sx, sy, z, env.others, {x = 0, y = 0}, function(X, Y)
        local x, y = X - sx, Y - sy
        if (x == 0 and y == 0) or has(known, x, y) then return true end
        if env.open(x, y) ~= 'open' then return false end
        -- the fort's open floor may border the new hall, never a new room
        for dx = -1, 1 do
            for dy = -1, 1 do
                if new_room(x + dx, y + dy) then return false end
            end
        end
        return true
    end)
    if not ok then return nil, 'refused: ' .. tostring(why2) end
    if c.kind == 'hospital' then
        L2.stair_gap = HOSPITAL_STAIR_GAP
        L2.main_stair = c.stairs[1]
        -- its rooms and their doors keep the gap (the main hall is the way to it: the hub and
        -- the hall's first columns, when this level digs them, lie at the stair by their nature)
        local rooms = {}
        for x, col in pairs(L2.tiles) do
            for y in pairs(col) do if new_room(x, y) then add(rooms, x, y) end end
        end
        local okg, whyg = stair_gap_ok({stair_gap = L2.stair_gap, tiles = rooms}, sx, sy, {stair, c.stairs[1]})
        if not okg then return nil, 'refused: ' .. tostring(whyg) end
    end

    -- the site
    local area
    for _, p in ipairs(puts) do
        local r = type(p) == 'table' and p.rect or nil
        if type(r) == 'table' and r.x1 and r.y1 and r.x2 and r.y2 then
            area = area or {x1 = r.x1, y1 = r.y1, x2 = r.x2, y2 = r.y2}
            area.x1, area.y1 = math.min(area.x1, r.x1, r.x2), math.min(area.y1, r.y1, r.y2)
            area.x2, area.y2 = math.max(area.x2, r.x1, r.x2), math.max(area.y2, r.y1, r.y2)
        end
    end
    if not area then return nil, 'refused: the placement names no room box' end
    area = {x1 = sx + area.x1 - 1, y1 = sy + area.y1 - 1, x2 = sx + area.x2 + 1, y2 = sy + area.y2 + 1, z = z}
    local links, hbox = {}, nil
    for x, col in pairs(hall) do
        for y in pairs(col) do
            table.insert(links, {x = x, y = y})
            hbox = hbox or {x1 = x, y1 = y, x2 = x, y2 = y}
            hbox.x1, hbox.y1 = math.min(hbox.x1, x), math.min(hbox.y1, y)
            hbox.x2, hbox.y2 = math.max(hbox.x2, x), math.max(hbox.y2, y)
        end
    end
    table.sort(links, function(a, b) return a.x < b.x or (a.x == b.x and a.y < b.y) end)
    local areas = hbox and {{x1 = sx + hbox.x1 - 1, y1 = sy + hbox.y1 - 1, x2 = sx + hbox.x2 + 1,
                             y2 = sy + hbox.y2 + 1, z = z}} or nil
    -- the pile rooms added: where each stockpile lies, its kind and its shop
    local piles, pile_flags = {}, {}
    for _, p in ipairs(puts) do
        local meta = type(p) == 'table' and pile_meta[math.tointeger(p.unit) or 0] or nil
        if meta then
            local x, y
            local cell = type(units[p.unit].place) == 'table' and units[p.unit].place[1] or nil
            if cell and type(p.T) == 'table' then
                local okx, c2 = pcall(M.units.xf_cell, p.T, cell)
                if okx and type(c2) == 'table' then x, y = math.tointeger(c2.x), math.tointeger(c2.y) end
            end
            if not (x and y) and type(p.rect) == 'table' then       -- (no cell to follow: the box's middle)
                x, y = (p.rect.x1 + p.rect.x2) // 2, (p.rect.y1 + p.rect.y2) // 2
            end
            if x and y then
                table.insert(piles, {x = x, y = y, flag = meta.flag, shop = meta.shop})
                table.insert(pile_flags, meta.flag)
            end
        end
    end
    -- the hub run the first room hangs on (directly or through turns), and its side
    local runs = {}
    for _, r in ipairs(type(floor.runs) == 'table' and floor.runs or {}) do
        if type(r) == 'table' and r.id ~= nil then runs[r.id] = r end
    end
    for _, r in ipairs(type(placement.runs) == 'table' and placement.runs or {}) do
        if type(r) == 'table' and r.id ~= nil then runs[r.id] = r end
    end
    local first = puts[1]
    local run = runs[first.run]
    local arm, side
    if run then
        local s = math.tointeger(first.side) or 0
        if first.axial or s == 0 then
            side = compass(run.dx, run.dy)             -- (it closes the run's end)
        else
            side = compass(-run.dy * s, run.dx * s)
        end
        local hub, hops = run, 0
        while hub.parent and hub.parent ~= 0 and runs[hub.parent] and hops < 64 do
            hub, hops = runs[hub.parent], hops + 1
        end
        arm = compass(hub.dx, hub.dy)
    end
    local hall_new = math.tointeger(placement.hall_new) or #links
    local band = c.band
    local marks = {}
    for i, m in ipairs(c.marks) do marks[i] = m end
    local site = {
        z = z, extend = extend and true or false, anchor = {x = sx, y = sy}, extra = {},
        area = area, areas = areas, stair = stair, corridor = 0, new_corridor = 0,
        links = links,
        floor = {id = floor.id, slots = #puts, hall = hall_new, piles = #piles > 0 and piles or nil},
        floor_result = {id = floor.id, elevation = ez(z), stair = {x = sx, y = sy}, arm = arm, side = side,
                        u = first.u, hall_new = hall_new, new_floor = is_new and true or false,
                        piles = #pile_flags > 0 and pile_flags or nil, units = #puts,
                        gap = G.gap, lead = G.lead, run_max = G.run_max},
        _commit = {store = c.store, floor = floor, placement = placement, free = free, marks = marks},
    }
    if band then site.in_district = z >= band.lo and z <= band.hi end
    if type(placement.neck) == 'table' and placement.neck.x and placement.neck.y then
        site.join = {x = placement.neck.x, y = placement.neck.y}
        site.doors = 'fortified'
    end
    return site, L2
end

local function floor_search(params, stairs, reserved, data, ceil_z)
    local M = floor_modules()
    if not M then return nil, 'the floor modules are not loaded' end
    if type(params) ~= 'table' or params.floor == false then return nil, 'this level keeps its own place' end
    local kind = params.kind
    if type(stairs) ~= 'table' or #stairs == 0 then return nil, 'no staircase' end

    -- 1. the level cut into its units
    -- (the level's params go to cut too: it reads params.style.entry_door, which ai-layouts' style drops)
    local uparams = M.units.unit_params(params)
    local L, lerr = layouts.make(kind, uparams)
    if not L then return nil, tostring(lerr or 'no layout') end
    local units, uinfo = M.units.cut(L, uparams)
    if type(units) ~= 'table' or #units == 0 then return nil, tostring(uinfo or 'not cuttable') end
    uinfo = type(uinfo) == 'table' and uinfo or {}

    local hint = floor_hint(params)
    local G = M.plan.grammar(hint)
    if type(G) ~= 'table' then return nil, 'no floor grammar' end
    -- (r3 g2) a floor full by its grammar opens another arm out of the hub before 'no room'
    -- (ai-floorplace spill), unless the brain's hint says spill = false or FLOOR_SPILL is off
    G.spill = FLOOR_SPILL ~= false and hint.spill ~= false
    local store, writable = load_floors()
    if type(store) ~= 'table' then return nil, 'the floor record could not be read' end
    if writable == false then return nil, 'the floor record is from a newer version' end

    local req_units, own_piles = {}, {}
    for i, u in ipairs(units) do
        if kind == 'workshops' then
            if u.tag == 'pile' then
                req_units[i] = req_unit(u, 'pile', 'stone')       -- (the ore_piles custom's own room)
                own_piles.stone = true
            else
                req_units[i] = req_unit(u, 'shop')
            end
        else
            req_units[i] = req_unit(u, u.mode == 'hall' and 'hall' or 'room')
        end
    end
    local plan = type(params.plan) == 'table' and params.plan or nil
    -- (r3 g2) the level's size for the "no room" marks: its widest and deepest unit, its count
    local size = {w = 0, d = 0, n = #units}
    for _, u in ipairs(units) do
        size.w = math.max(size.w, math.tointeger(u.w) or 0)
        size.d = math.max(size.d, math.tointeger(u.d) or 0)
    end
    local c = {M = M, params = params, kind = kind, hint = hint, G = G, store = store, size = size,
               units = units, uinfo = uinfo, req_units = req_units, own_piles = own_piles, pile_cache = {},
               axial = type(uinfo.style) == 'table' and uinfo.style.grand == true
                   and #units == 1 and units[1].mode == 'hall',
               stairs = stairs, reserved = reserved, data = data, band = plan_band(plan),
               deadline = os.clock() + FLOOR_SECONDS, marks = {}, looked = 0, tried = 0}
    if type(c.data) ~= 'table' then c.data = load_projects() end

    local notes, late = {}, false
    local retry = (tonumber(G.full_retry_days) or 28) * 1200
    local now = now_tick()
    local seen = {}
    -- (F4, S4) the notes of floors that refused lately
    local R = type(FLOOR_REFUSED) == 'table' and FLOOR_REFUSED or {}
    FLOOR_REFUSED = R
    if type(R.notes) ~= 'table' then R.notes, R.n, R.top = {}, 0, 0 end
    local next_id = math.tointeger(type(c.data) == 'table' and c.data.next_id) or 0
    if next_id < (R.top or 0) or (R.n or 0) > FLOOR_REFUSED_MAX then R.notes, R.n, R.top = {}, 0, 0 end
    R.top = math.max(R.top or 0, next_id)
    local function refused_key(floor, stair, z)
        return table.concat({tostring(kind), tostring(hint.tag), #units, stair.x, stair.y, z,
                             tostring(floor.id), #(type(floor.slots) == 'table' and floor.slots or {}),
                             #(type(floor.runs) == 'table' and floor.runs or {})}, '|')
    end
    -- (r3 g1) each stair after the first has stair_tries floors of its own (and twice as many
    -- levels looked at), so the first stair's full floors leave the others a try
    local more = stair_tries(hint)
    local list = floor_stairs(stairs, hint, plan)
    local try_cap, look_cap = FLOORS_TRY, FLOOR_LEVELS_SCAN
    for si, stair in ipairs(list) do
        try_cap, look_cap = FLOORS_TRY + (si - 1) * more, FLOOR_LEVELS_SCAN + (si - 1) * more * 2
        for _, lv in ipairs(floor_levels(stair, hint, c.band, ceil_z)) do
            if os.clock() > c.deadline then late = true break end
            if c.looked >= look_cap or c.tried >= try_cap then break end
            local z = lv.z
            local key = stair.x .. ',' .. stair.y .. ',' .. z
            if not seen[key] then
                seen[key] = true
                local floor = M.plan.find_floor(store, z, stair.x, stair.y)
                local is_new = floor == nil
                if is_new then floor = M.plan.new_floor(store, z, stair.x, stair.y, now) end
                local label = is_new and ('z%d'):format(ez(z)) or ('floor %s'):format(tostring(floor.id))
                -- a floor found full lately is left alone for a while
                local full = type(floor.full) == 'table' and floor.full or {}
                local skip
                -- (r3 g2) a "no room" mark kept with the size of the level refused: a smaller level
                -- (fewer, narrower or shallower units) is tried on the floor all the same
                local sized = FLOOR_FULL_BY_SIZE ~= false and type(floor.full_size) == 'table' and floor.full_size or {}
                local function smaller(tag)
                    local fs = tag ~= '*' and sized[tag] or nil
                    if type(fs) ~= 'table' then return false end
                    return size.w < (tonumber(fs.w) or 0) or size.d < (tonumber(fs.d) or 0)
                        or size.n < (tonumber(fs.n) or 0)
                end
                for _, tag in ipairs({'*', hint.tag}) do
                    local t = tag ~= nil and tonumber(full[tag]) or nil
                    if t and now - t < retry and not smaller(tag) then
                        skip = tag == '*' and 'no hall can start here' or ('full for ' .. tostring(tag))
                        break
                    end
                end
                -- (F2, V2) a new floor the record cannot hold is never dug: commit
                -- (after the level is designated) would refuse it
                if not skip and is_new and type(M.plan.room_for) == 'function'
                        and not M.plan.room_for(store) then
                    skip = ('the floor record is full (%s floors)'):format(tostring(M.plan.FLOORS_MAX or #store.floors))
                end
                local rkey = refused_key(floor, stair, z)
                local note = R.notes[rkey]
                if type(note) == 'table' and not (now > note.tick and now - note.tick < FLOOR_REFUSED_DAYS * 1200) then
                    R.notes[rkey], note = nil, nil
                end
                if skip then
                    table.insert(notes, label .. ': ' .. skip)
                elseif note then
                    -- (F4, S4) refused lately: its answer again, counted as a floor tried (as the search was)
                    c.looked, c.tried = c.looked + 1, c.tried + 1
                    table.insert(notes, label .. ': ' .. note.why)
                else
                    local tried0 = c.tried
                    local ok, site, L2, mark, free = pcall(on_floor, c, stair, z, lv.extend, floor, is_new)
                    if not ok then
                        -- (a module that threw: this floor is given up, the next is tried)
                        c.tried = math.max(c.tried, tried0 + 1)
                        table.insert(notes, label .. ': failed: ' .. tostring(site):sub(1, 120))
                    elseif site then
                        return site, L2
                    else
                        table.insert(notes, label .. ': ' .. tostring(L2))
                        if mark then
                            table.insert(c.marks, {z = z, sx = stair.x, sy = stair.y, tag = mark, free = free,
                                                   size = mark ~= '*' and size or nil})
                        elseif tostring(L2):sub(1, 8) == 'refused:' then
                            if R.notes[rkey] == nil then R.n = (R.n or 0) + 1 end
                            R.notes[rkey] = {tick = now, why = tostring(L2)}
                        end
                    end
                end
            end
            -- (r3 g2) too big for any run of this grammar: so on every floor; the classic way at once
            if c.big and FLOOR_BIG_STOP ~= false then break end
        end
        if c.big and FLOOR_BIG_STOP ~= false then break end
        if late or os.clock() > c.deadline then late = true break end
        local last_cap = FLOORS_TRY + (#list - 1) * more
        if c.looked >= FLOOR_LEVELS_SCAN + (#list - 1) * more * 2 or c.tried >= last_cap then break end
    end
    if late then table.insert(notes, 'out of time') end
    if #notes == 0 then table.insert(notes, 'no level of the stairs to try') end
    return nil, table.concat(notes, '; '):sub(1, FLOOR_WHY_MAX), c.marks, c.big
end

-- (r3 g2) What a classic level (choose_site) keeps out of while the floors are on: map boxes
-- {x1, y1, x2, y2, z, why} for check_site's reserved list. For every floor with a hall (or its
-- hub dug): its hub's 3x3, each run's hall and room rows out to the length it may still grow to
-- (run_max, from this level's grammar; a run with a turn or closed: its own), and FLOOR_KEEP_ARM
-- columns out each way no arm has taken yet; and the hub of each elevation this level's hint
-- offers, on the stair its floors hang on (unless no hall can start there). The floor's own
-- search never reads these. Never raises: {} on any error.
FLOOR_KEEP_SIDE = 4          -- rows each side of a planned hall kept (the wall row and the rooms)
local KEEP_DIRS = {east = {1, 0}, south = {0, 1}, west = {-1, 0}, north = {0, -1}}

function floor_keep_boxes(params, stairs)
    local out = {}
    if FLOOR_KEEP_CLEAR == false or type(params) ~= 'table' then return out end
    local ok = pcall(function()
        local M = floor_modules()
        if not M then return end
        local okl, store = pcall(load_floors)
        if not okl or type(store) ~= 'table' or type(store.floors) ~= 'table' then store = {floors = {}} end
        local hint = floor_hint(params)
        local G = M.plan.grammar(hint)
        local run_max = type(G) == 'table' and math.tointeger(G.run_max) or 30
        local side = math.tointeger(FLOOR_KEEP_SIDE) or 4
        local arm = math.tointeger(FLOOR_KEEP_ARM) or 12
        local function put(sx, sy, z, ax, ay, bx, by, why)
            table.insert(out, {x1 = sx + math.min(ax, bx), y1 = sy + math.min(ay, by),
                               x2 = sx + math.max(ax, bx), y2 = sy + math.max(ay, by), z = z, why = why})
        end
        -- run-frame box u1..u2, v1..v2 of a run at (ox, oy) going (dx, dy)
        local function run_box(sx, sy, z, ox, oy, dx, dy, u1, u2, v1, v2, why)
            local px, py = -dy, dx
            put(sx, sy, z, ox + u1 * dx + v1 * px, oy + u1 * dy + v1 * py,
                ox + u2 * dx + v2 * px, oy + u2 * dy + v2 * py, why)
        end
        local done = {}
        for _, f in ipairs(store.floors) do
            local st = type(f) == 'table' and type(f.stair) == 'table' and f.stair or nil
            local sx, sy, z = st and math.tointeger(st.x), st and math.tointeger(st.y), math.tointeger(f.z)
            if sx and sy and z then
                local runs = type(f.runs) == 'table' and f.runs or {}
                local live = f.hub == 'dug'
                for _, r in ipairs(runs) do
                    if type(r) == 'table' and (math.tointeger(r.len) or 0) > 0 then live = true end
                end
                -- (r3 V3) a dead floor (every level gone, its runs released) or one marked
                -- "no hall can start here" ('*') keeps nothing: it will never use that ground
                local dead = (type(f.full) == 'table' and f.full['*'] ~= nil)
                if not dead and M.plan and type(M.plan.dead_floor) == 'function' then
                    local okf, isd = pcall(M.plan.dead_floor, f)
                    dead = okf and isd == true
                end
                if dead then live = false end
                if live then
                    local why = ('kept for the main hall of floor %s (elevation %d)'):format(tostring(f.id), ez(z))
                    done[sx .. ',' .. sy .. ',' .. z] = true
                    put(sx, sy, z, -1, -1, 1, 1, why)
                    local kids, used = {}, {}
                    for _, r in ipairs(runs) do
                        if type(r) == 'table' and r.parent ~= nil and r.parent ~= 0 then kids[r.parent] = true end
                    end
                    for _, r in ipairs(runs) do
                        local dx, dy = type(r) == 'table' and math.tointeger(r.dx), type(r) == 'table' and math.tointeger(r.dy)
                        if dx and dy and (dx ~= 0 or dy ~= 0) then
                            local hub_run = r.parent == nil or r.parent == 0
                            if hub_run then used[compass(dx, dy)] = true end
                            local u0 = (math.tointeger(r.node) == 5 and not hub_run) and 3 or 2
                            local len = math.tointeger(r.len) or 0
                            if not kids[r.id] and r.closed ~= 'terminus' then len = math.max(len, run_max) end
                            if len > 0 then
                                run_box(sx, sy, z, math.tointeger(r.ox) or 0, math.tointeger(r.oy) or 0, dx, dy,
                                        u0, u0 + len, -1 - side, 1 + side, why)
                            end
                        end
                    end
                    for name, d in pairs(KEEP_DIRS) do
                        if not used[name] and arm > 0 then
                            run_box(sx, sy, z, 0, 0, d[1], d[2], 2, 1 + arm, -1, 1, why)
                        end
                    end
                end
            end
        end
        -- the hubs of the elevations this level's hint offers, on its floors' stair
        local elevs = type(params.floor) == 'table' and type(hint.elevs) == 'table' and hint.elevs or {}
        local st = (#elevs > 0 and type(stairs) == 'table' and #stairs > 0)
            and floor_stairs(stairs, hint, type(params.plan) == 'table' and params.plan or nil)[1] or nil
        if st then
            for _, e in ipairs(elevs) do
                local z = math.tointeger(e) and (math.tointeger(e) - OFFSET) or nil
                if z and not done[st.x .. ',' .. st.y .. ',' .. z] and z >= (st.z_bottom or z) and z <= (st.z_top or z) then
                    local f = M.plan.find_floor(store, z, st.x, st.y)
                    local no_hall = f and type(f.full) == 'table' and f.full['*'] ~= nil
                    if not no_hall then
                        put(st.x, st.y, z, -1, -1, 1, 1, ('kept for a floor\'s hub (elevation %d)'):format(ez(z)))
                    end
                end
            end
        end
    end)
    if not ok then return {} end
    return out
end

-- The site for a new level on a floor; or nil, why, marks, big (the caller then places it the classic way;
-- big: (r3 g2) {need, run_max, kind} when the level is too big for any run of its grammar, need nil: no run).
-- Reads only: nothing is designated and nothing saved.
--   params   start_project's (kind, the kind's own numbers, style, plan, floor = the brain's hint or nil, urgent)
--   stairs   find_stairs()'s list (already without the banned ones); reserved: the open projects' areas
--   data     load_projects()'s record (the other projects' boxes, old_areas)
--   ceil_z   no level above it, or nil
--   marks    { {z, sx, sy, tag, free} ... }: floors found full for the tag ('*': no hall can start), for floor_fallback
-- site: an ordinary site (z, extend, anchor = the stair, extra = {}, area, areas, stair, corridor = 0,
-- new_corridor = 0, in_district, join, doors, links) plus floor (saved on the project), floor_result
-- (for the action's answer) and _commit (what floor_commit needs). L2: ai-floorunits.compose's layout.
function floor_site(params, stairs, reserved, data, ceil_z)
    CACHE = {}
    local ok, site, L2, marks, big = pcall(floor_search, params, stairs, reserved, data, ceil_z)
    CACHE = nil
    if not ok then error(site, 0) end
    if site then return site, L2 end
    return nil, L2, marks, big
end
