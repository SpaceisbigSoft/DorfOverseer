-- (0.105.47, I7d 2a) Surface work kept near the gates while a great danger
-- the squads can't beat is about.
--
-- C (y258-259): a savanna titan and a hill titan came in at the map's edge;
-- the alarm went up within 50 ticks, and still the fisherdwarves 60 to 200
-- tiles out died within 500-1000 ticks: they couldn't walk home in time. B
-- lost a fishery worker the same way, A an outpost liaison on the surface.
-- The alarm can't save a dwarf that far out; keeping them near the way in can.
--
-- The brain (brain/planner_near_gates.py) decides when (a titan, megabeast or
-- other great danger on the surface or at the map's edge that the matchup
-- says the squads can't beat, and a few days after it left); this module
-- does it with a burrow, the "AI near gates":
--   * its tiles: the fort's inside (ai-society fill_shelter, the same scan
--     as the AI shelter: every level the dwarves live, store or draw water
--     on) and, round each surface way in of the gate scan, the tiles within
--     `radius` across and NEAR_Z levels up and down (so fishing, gathering,
--     felling, herding and hunting go on there, and nowhere farther);
--   * its members: every citizen who is no soldier, no patient (the hospital
--     burrow takes them) and in no other burrow (the player's, the hospital,
--     a calm-down room, the recreation burrow, the weather keep-in), kept in
--     the save; a member who becomes a patient or joins another burrow is let
--     out. `on = false` lets out exactly those.
-- The alarm (civ alert) still sends everyone into the shelter when the
-- danger comes near; from 25 tiles out that is a short walk.
--
--   status(txt)                    the `near_gates` section: {on, radius,
--                                  members, gates, outside, far = [{id,
--                                  name, d}] (citizens outside farther than
--                                  radius from every surface way in), far_total}
--   set(on, radius, dry_run, txt)  the `near_gates` action
--@module = true

local U = reqscript('ai-util')

BURROW_NAME = 'AI near gates'
STATE_KEY = 'ai-overseer/near-gates'
RADIUS = 25              -- default tiles across from a surface way in
RADIUS_MIN, RADIUS_MAX = 5, 60
NEAR_Z = 3               -- levels up and down round a way in
FAR_MAX = 12             -- far-out citizens listed by name at most

local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end

-- --- pure parts ---------------------------------------------------------------------

-- The surface ways in of the gate scan's entrance list: {x, y, z} each.
function gate_list(entrances)
    local out = {}
    for _, e in ipairs(type(entrances) == 'table' and entrances or {}) do
        if type(e) == 'table' and e.kind == 'surface' and type(e.x) == 'number' and type(e.y) == 'number'
                and type(e.z) == 'number' then
            table.insert(out, {x = e.x, y = e.y, z = e.z})
        end
    end
    return out
end

-- The distance (x/y tiles, a level counting 3) from p to the nearest way in,
-- and whether p is inside one's box (radius across, NEAR_Z levels).
function reach(p, gates, radius)
    local best, inside = nil, false
    for _, g in ipairs(gates) do
        local dxy = math.max(math.abs(p.x - g.x), math.abs(p.y - g.y))
        local dz = math.abs(p.z - g.z)
        if dxy <= radius and dz <= NEAR_Z then inside = true end
        local d = dxy + 3 * dz
        if not best or d < best then best = d end
    end
    return best, inside
end

-- A citizen's verdict for the burrow: 'add', 'keep', 'out' (let out) or
-- 'skip'. f: {member (ours, in the save), in_ours, other (in another
-- burrow), soldier, patient}.
function member_verdict(f)
    if f.member then
        if f.soldier or f.patient or f.other then return 'out' end
        return 'keep'
    end
    if f.in_ours or f.other or f.soldier or f.patient then return 'skip' end
    return 'add'
end

-- --- the game -----------------------------------------------------------------------

local function load_state()
    local d = U.site_get(STATE_KEY, {})
    if type(d) ~= 'table' then d = {} end
    d.members = type(d.members) == 'table' and d.members or {}
    return d
end

local function society()
    local ok, S = pcall(reqscript, 'ai-society')
    return ok and S or nil
end

local function gates_now()
    local ok, G = pcall(function() return reqscript('ai-gates').GATES end)
    if not ok or type(G) ~= 'table' or not G.scanned then return nil end
    return gate_list(G.entrances)
end

local function find_burrow()
    local S = society()
    if S and S.find_burrow then return S.find_burrow(BURROW_NAME) end
    return nil
end

local function soldier(u)
    local ok, sq = pcall(function() return u.military.squad_id end)
    return ok and type(sq) == 'number' and sq >= 0
end

local function patient(u)
    local S = society()
    local f = S and S.is_patient
    if not f then
        local ok, B = pcall(reqscript, 'ai-society-burrows')
        f = ok and B and B.is_patient or nil
    end
    if not f then return false end
    local ok, v = pcall(f, u)
    return ok and v == true
end

-- in our burrow now; in another one
local function burrows_of(u, bid)
    local mine, other = false, false
    local ok = pcall(function()
        for _, id in ipairs(u.burrows or {}) do
            if id == bid then mine = true else other = true end
        end
    end)
    if not ok then return false, true end
    return mine, other
end

local function name_of(u, txt)
    local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
    n = ok and n or ('unit ' .. tostring(u.id))
    return txt and txt(n) or n
end

local function outside_at(p)
    local ok, des = pcall(dfhack.maps.getTileFlags, xyz2pos(p.x, p.y, p.z))
    return ok and des and des.outside and true or false
end

function status(txt)
    local d = load_state()
    local radius = math.tointeger(d.radius) or RADIUS
    local gates = gates_now()
    local n = 0
    for _ in pairs(d.members) do n = n + 1 end
    local out = {on = d.on == true, radius = radius, members = n, gates = gates and #gates or nil,
                 drawn_tiles = d.tiles, since = d.since, outside = 0, far = {}, far_total = 0}
    for _, u in ipairs(report_citizens(true)) do
        local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
        if outside_at(p) then
            out.outside = out.outside + 1
            if gates and #gates > 0 then
                local dist, inside = reach(p, gates, radius)
                if not inside then
                    out.far_total = out.far_total + 1
                    if #out.far < FAR_MAX then
                        table.insert(out.far, {id = u.id, name = name_of(u, txt), d = dist,
                                               member = d.members[tostring(u.id)] and true or nil})
                    end
                end
            end
        end
    end
    return out
end

-- the burrow's tiles: the inside (fill_shelter) and the boxes round the ways in
local function draw(b, gates, radius)
    local S = society()
    pcall(dfhack.burrows.clearTiles, b)
    local n = 0
    if S and S.fill_shelter then
        local ok, m = pcall(S.fill_shelter, b)
        if ok and type(m) == 'number' then n = m end
    end
    local sx, sy, sz = dfhack.maps.getTileSize()
    for _, g in ipairs(gates) do
        for z = math.max(0, g.z - NEAR_Z), math.min(sz - 1, g.z + NEAR_Z) do
            for y = math.max(0, g.y - radius), math.min(sy - 1, g.y + radius) do
                for x = math.max(0, g.x - radius), math.min(sx - 1, g.x + radius) do
                    if pcall(dfhack.burrows.setAssignedTile, b, xyz2pos(x, y, z), true) then n = n + 1 end
                end
            end
        end
    end
    return n
end

local function sig_of(gates, radius)
    local parts = {tostring(radius)}
    for _, g in ipairs(gates) do table.insert(parts, g.x .. ',' .. g.y .. ',' .. g.z) end
    table.sort(parts)
    return table.concat(parts, ';')
end

local function let_out(d, b, dry_run)
    local n = 0
    for id in pairs(d.members) do
        local u = df.unit.find(tonumber(id) or -1)
        if u and b and not dry_run then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
        n = n + 1
    end
    return n
end

function set(on, radius, dry_run, txt)
    local d = load_state()
    local b = find_burrow()
    if not on then
        if not d.on and next(d.members) == nil then
            return {ok = false, rejected = true, nothing_to_do = true, error = 'the near-gates burrow is not in use'}
        end
        local n = let_out(d, b, dry_run)
        if not dry_run then
            pcall(dfhack.burrows.clearTiles, b)     -- (no tiles: nothing reads it as a place)
            U.site_put(STATE_KEY, {on = false, members = {}})
        end
        return {ok = true, on = false, released = n, dry_run = dry_run or nil}
    end
    radius = math.tointeger(radius) or RADIUS
    if radius < RADIUS_MIN or radius > RADIUS_MAX then
        return {ok = false, rejected = true, error = ('radius %d-%d'):format(RADIUS_MIN, RADIUS_MAX)}
    end
    local gates = gates_now()
    if not gates or #gates == 0 then
        return {ok = false, rejected = true, error = 'no surface way in known yet (the gate scan)'}
    end
    local S = society()
    if not (S and S.new_burrow and S.find_burrow) then
        return {ok = false, error = 'ai-society could not be loaded'}
    end
    local sig = sig_of(gates, radius)
    local drawn = false
    if dry_run then
        drawn = not b or d.sig ~= sig
    else
        local fresh = false
        if not b then b, fresh = S.new_burrow(BURROW_NAME), true end   -- (gone: drawn again)
        if fresh or d.sig ~= sig or not d.on then
            d.tiles = draw(b, gates, radius)
            d.sig, drawn = sig, true
            if (d.tiles or 0) == 0 then
                return {ok = false, error = 'the near-gates burrow came out with no tiles'}
            end
        end
    end
    local bid = b and b.id or -1
    local added, out_, skipped, gone = 0, 0, 0, 0
    local live = {}
    for _, u in ipairs(report_citizens(true)) do
        local id = tostring(u.id)
        live[id] = true
        local mine, other = burrows_of(u, bid)
        local v = member_verdict({member = d.members[id] == true, in_ours = mine, other = other,
                                  soldier = soldier(u), patient = patient(u)})
        if v == 'add' then
            if dry_run then
                added = added + 1
            elseif pcall(dfhack.burrows.setAssignedUnit, b, u, true) then
                d.members[id] = true
                added = added + 1
            end
        elseif v == 'out' then
            if not dry_run then pcall(dfhack.burrows.setAssignedUnit, b, u, false); d.members[id] = nil end
            out_ = out_ + 1
        elseif v == 'skip' then
            skipped = skipped + 1
        end
    end
    for id in pairs(d.members) do
        if not live[id] then
            local u = df.unit.find(tonumber(id) or -1)
            if u and b and not dry_run then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            if not dry_run then d.members[id] = nil end
            gone = gone + 1
        end
    end
    local n = 0
    for _ in pairs(d.members) do n = n + 1 end
    if not dry_run then
        if not d.on then
            local okt, t = pcall(U.abs_tick)
            d.since = okt and t or nil
        end
        d.on, d.radius = true, radius
        U.site_put(STATE_KEY, d)
    end
    return {ok = true, on = true, radius = radius, gates = #gates, drawn = drawn or nil, tiles = d.tiles,
            added = added, let_out = out_, members = n, skipped = skipped, gone = gone, dry_run = dry_run or nil}
end
