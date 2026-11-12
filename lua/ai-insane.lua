-- (0.105.40b) The fort's insane: who, what kind, where, and what deadly
-- ground lies near them; the AI's own doors locked between a melancholy or
-- stark raving dwarf and that ground while they are near; and the citizens
-- whose stress is heading that way.
--
-- What DF does with the insane (DF wiki, Insane, v50; df-structures
-- mood_type): insanity is permanent; the insane don't sleep, eat, drink,
-- follow orders or work, and every kind ends in death.
--   Melancholy   (mood Melancholy) moves slowly and seeks death: jumps off a
--                cliff, drowns in water or burns in magma; with none to
--                hand, starves or dies of thirst.
--   Raving       (mood Raving, "stark raving mad") strips, drops what they
--                carry, wanders and babbles; doesn't seek death but ignores
--                hazards; dies of thirst or hunger. Attacks no one.
--   Berserk      (mood Berserk) attacks friend and foe: the military rules
--                and the hazards section see to it (not this module).
--   Catatonic    (mood Traumatized, DF's CATATONIC) stares into space until
--                they starve. Nothing to be done.
-- A locked door (or hatch) is passed by no creature but a building
-- destroyer, sane or not: the one lever the AI has. It locks only its own
-- doors (inside the levels it dug: the builder's project areas, the wells'
-- excepted, whose hatches their own rules run), never a gate piece (the
-- entrances' watcher's), one on a lever, one already locked (the player's or
-- another rule's), and frees each lock as soon as no guarded dwarf is near,
-- or after LOCK_MAX_TICKS (then rests it REST_TICKS: anyone shut in on the
-- far side gets out), never locks again for a week a door someone else
-- opened, and never holds more than MAX_LOCKS.
--
--   report()         the `insane` section: {list = [{id, name, kind, mood,
--                    x, y, z, place, hazards = {water, magma, drop} (the
--                    nearest of each, in tiles), doors (the AI's doors
--                    between them and it the guard would lock now),
--                    locked (held for them)}],
--                    locks (held in all), at_risk = [{id, name, longterm,
--                    stress, bedroom, squad, leader}], at_risk_total}
--   guard(o, dry)    lock and free the doors (o.units: the guarded ids; nil
--                    = every melancholy and raving one). {ok, locked,
--                    released, held, doors}
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/insane-locks'
KINDS = {Melancholy = 'melancholy', Raving = 'raving', Berserk = 'berserk', Traumatized = 'catatonic'}
GUARDED = {melancholy = true, raving = true}   -- the kinds kept from deadly ground
SCAN_XY = 12          -- deadly ground looked for this far round an insane dwarf...
SCAN_DOWN = 2         -- ...on their level and this many below (liquids; drops on their own level)
DEEP = 4              -- water this deep drowns a dwarf (the hazards section's `wet`)
DOOR_NEAR = 10        -- a door is locked while a guarded dwarf is this near (tiles, |dz| <= 1)...
DOOR_HAZARD = 6       -- ...with deadly ground this near the door, nearer the door than the dwarf
RELEASE_NEAR = 14     -- a held lock freed once no guarded dwarf is this near
LOCK_MAX_TICKS = 2400 -- a lock held two days at most...
REST_TICKS = 600      -- ...then left open half a day (anyone shut in on the far side gets out)
LEFT_TICKS = 7 * 1200 -- a lock someone else opened: not locked again for a week
MAX_LOCKS = 12
MAX_ROWS = 10         -- insane dwarves listed (and scanned) at most
RISK_LONGTERM = 25000 -- (DF wiki, Stress) long-term stress "stressed" and up: listed for the brain...
RISK_CATEGORY = 2     -- ...while unhappy or worse (getStressCategory 0-2)
RISK_MAX = 12
STRESS_LABELS = {[0] = 'miserable', [1] = 'very_unhappy', [2] = 'unhappy', [3] = 'fine',
                 [4] = 'content', [5] = 'happy', [6] = 'ecstatic'}

-- --- helpers ---------------------------------------------------------------

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function txt(s)
    if s == nil then return nil end
    local ok, v = pcall(dfhack.df2utf, s)
    return ok and v or s
end

local function name_of(u)
    local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
    return ok and txt(n) or ('unit ' .. tostring(u.id))
end

local function pos_of(u)
    local ok, x, y, z = pcall(dfhack.units.getPosition, u)
    if ok and type(x) == 'number' then return x, y, z end
    return nil
end

-- tiles apart: the larger step across, a level counted as 3
local function dist(ax, ay, az, bx, by, bz)
    return math.max(math.abs(ax - bx), math.abs(ay - by)) + 3 * math.abs(az - bz)
end

local function kind_of(u)
    local ok, k = pcall(function() return u.mood >= 0 and df.mood_type[u.mood] or nil end)
    return ok and k and KINDS[k] or nil, ok and k or nil
end

-- one of the fort's own (DFHack's citizen list leaves the insane out)
local function own(u)
    local ok, o = pcall(function() return dfhack.units.isOwnGroup(u) end)
    if ok and o then return true end
    ok, o = pcall(function() return u.civ_id == df.global.plotinfo.civ_id end)
    return ok and o == true
end

-- the fort's insane, alive: {u, kind, mood}
function insane_units()
    local out = {}
    local okl, active = pcall(U.units_active)
    for _, u in ipairs(okl and active or {}) do
        local kind, mood = kind_of(u)
        if kind then
            local okd, dead = pcall(dfhack.units.isDead, u)
            if not (okd and dead) and own(u) then
                table.insert(out, {u = u, kind = kind, mood = mood})
                if #out >= MAX_ROWS then break end
            end
        end
    end
    return out
end

-- --- deadly ground ---------------------------------------------------------

local function shape_at(x, y, z)
    local ok, s = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        if tt == nil then return nil end
        return df.tiletype_shape[df.tiletype.attrs[tt].shape]
    end)
    return ok and s or nil
end

-- what kind of deadly ground (x, y, z) is: 'water', 'magma', 'drop' (open
-- space with open space below: a fall of two levels or more), or nil.
-- Tiles no dwarf has seen are none.
function hazard_at(x, y, z, drops)
    local ok, des = pcall(dfhack.maps.getTileFlags, x, y, z)
    if not ok or not des then return nil end
    if des.hidden then return nil end
    local fs = des.flow_size or 0
    if fs > 0 then
        local magma = des.liquid_type == true or des.liquid_type == 1
        if magma then return 'magma' end
        if fs >= DEEP then return 'water' end
        return nil
    end
    if drops and shape_at(x, y, z) == 'EMPTY' and shape_at(x, y, z - 1) == 'EMPTY' then
        local okb, below = pcall(dfhack.maps.getTileFlags, x, y, z - 1)
        if okb and below and (below.flow_size or 0) == 0 then return 'drop' end
    end
    return nil
end

-- the deadly ground round (x, y, z): nearest = {water = d, magma = d, drop = d}
-- and the tiles found {x, y, z, kind, d}, the nearest first
function hazards_near(x, y, z)
    local nearest, tiles = {}, {}
    for dz = -SCAN_DOWN, 0 do
        for dx = -SCAN_XY, SCAN_XY do
            for dy = -SCAN_XY, SCAN_XY do
                local hx, hy, hz = x + dx, y + dy, z + dz
                local k = hazard_at(hx, hy, hz, dz == 0)
                if k then
                    local d = dist(x, y, z, hx, hy, hz)
                    if not nearest[k] or d < nearest[k] then nearest[k] = d end
                    table.insert(tiles, {x = hx, y = hy, z = hz, kind = k, d = d})
                end
            end
        end
    end
    table.sort(tiles, function(a, b) return a.d < b.d end)
    while #tiles > 200 do table.remove(tiles) end
    return nearest, tiles
end

-- --- the AI's own doors ----------------------------------------------------

-- the boxes of the levels the AI dug (open and closed projects, the dropped
-- ones' outlines), the wells' left out
function ai_boxes()
    local boxes = {}
    pcall(function()
        local B = reqscript('ai-builder')
        local data = B.load_projects()
        for _, p in ipairs(data.list or {}) do
            if p.kind ~= 'well' then
                local okA, areas = pcall(B.project_areas, p)
                for _, a in ipairs(okA and areas or {}) do table.insert(boxes, a) end
            end
        end
        for _, a in ipairs(data.old_areas or {}) do table.insert(boxes, a) end
    end)
    return boxes
end

local function in_boxes(boxes, x, y, z)
    for _, a in ipairs(boxes) do
        if a.z == z and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 then return true end
    end
    return false
end

-- the entrances' gate pieces (the watcher's own, saved or live)
function gate_ids()
    local ids = {}
    pcall(function()
        for _, g in ipairs(U.site_get('ai-overseer/gates', {}).gates or {}) do ids[g.id] = true end
    end)
    pcall(function()
        local G = reqscript('ai-gates').GATES or {}
        for _, e in ipairs(G.entrances or {}) do
            for _, g in ipairs(e.equipment or {}) do ids[g.id] = true end
            for _, g in ipairs(e.outer or {}) do ids[g.id] = true end
        end
    end)
    return ids
end

local function door_list()
    local out = {}
    local ok = pcall(function()
        for _, k in ipairs({'DOOR', 'HATCH'}) do
            for _, b in ipairs(df.global.world.buildings.other[k]) do table.insert(out, b) end
        end
    end)
    if ok then return out end
    out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            local t = df.building_type[b:getType()]
            if t == 'Door' or t == 'Hatch' then table.insert(out, b) end
        end
    end)
    return out
end

local function built(b)
    local ok, done = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    return ok and done
end

local function flag(b, k)
    local ok, v = pcall(function() return b.door_flags[k] end)
    return ok and v == true
end

-- (x, y, z) of a building: its own tile (a door or hatch is one tile)
local function bpos(b)
    local ok, x, y, z = pcall(function() return b.centerx, b.centery, b.z end)
    if ok and type(x) == 'number' then return x, y, z end
    ok, x, y, z = pcall(function() return b.x1, b.y1, b.z end)
    if ok and type(x) == 'number' then return x, y, z end
    return nil
end

-- The AI's doors between a dwarf at (x, y, z) and the deadly ground
-- `tiles`: {b, x, y, z, hazard}. ctx: {boxes, gates} (read once a call).
function doors_between(ctx, x, y, z, tiles)
    local out = {}
    if #tiles == 0 then return out end
    for _, b in ipairs(ctx.doors) do
        local bx, by, bz = bpos(b)
        if bx and math.abs(bz - z) <= 1 and dist(x, y, z, bx, by, bz) <= DOOR_NEAR
                and not ctx.gates[b.id] and not flag(b, 'operated_by_mechanisms') and built(b)
                and in_boxes(ctx.boxes, bx, by, bz) then
            local dd = dist(x, y, z, bx, by, bz)
            for _, h in ipairs(tiles) do
                local dh = dist(bx, by, bz, h.x, h.y, h.z)
                -- the door nearer the ground than the dwarf is: in the way
                if dh <= DOOR_HAZARD and h.d > dh and h.d >= dd then
                    table.insert(out, {b = b, x = bx, y = by, z = bz, hazard = h.kind})
                    break
                end
            end
        end
    end
    return out
end

local function context()
    return {boxes = ai_boxes(), gates = gate_ids(), doors = door_list()}
end

-- --- the record ------------------------------------------------------------

function state()
    local st = U.site_get(SITE_KEY, {})
    st.locks = type(st.locks) == 'table' and st.locks or {}
    st.rest = type(st.rest) == 'table' and st.rest or {}
    return st
end

local function save(st)
    pcall(U.site_put, SITE_KEY, st)
end

local function count(t)
    local n = 0
    for _ in pairs(t) do n = n + 1 end
    return n
end

local function find_building(id)
    local ok, b = pcall(df.building.find, id)
    return ok and b or nil
end

-- --- the citizens heading for a breakdown ----------------------------------

local function bedroom_of(u)
    local has = false
    pcall(function()
        for _, b in ipairs(u.owned_buildings) do
            if df.building_civzonest:is_instance(b) and df.civzone_type[b.type] == 'Bedroom' then has = true end
        end
    end)
    return has
end

-- (DF wiki, Stress) a breakdown, and insanity, come when both the
-- long-term and the short-term stress are high: the citizens with long-term
-- stress RISK_LONGTERM and up while unhappy or worse, the most first.
-- Read once a game day (the soul's numbers move slowly).
AT_RISK_CACHE = AT_RISK_CACHE or nil
function at_risk()
    local day = now_tick() // 1200
    if AT_RISK_CACHE and AT_RISK_CACHE.day == day then return AT_RISK_CACHE.rows, AT_RISK_CACHE.total end
    local rows = {}
    local okc, cits = pcall(U.citizens)
    for _, u in ipairs(okc and cits or {}) do
        local ok, lt = pcall(function() return u.status.current_soul.personality.longterm_stress end)
        if ok and type(lt) == 'number' and lt >= RISK_LONGTERM then
            local okc2, cat = pcall(dfhack.units.getStressCategory, u)
            if okc2 and type(cat) == 'number' and cat <= RISK_CATEGORY then
                local squad = false
                local leader = false
                pcall(function() squad = u.military.squad_id ~= -1; leader = squad and u.military.squad_position == 0 end)
                table.insert(rows, {id = u.id, name = name_of(u), longterm = lt, stress = STRESS_LABELS[cat],
                                    bedroom = bedroom_of(u), squad = squad or nil, leader = leader or nil})
            end
        end
    end
    table.sort(rows, function(a, b)
        if a.longterm ~= b.longterm then return a.longterm > b.longterm end
        return a.id < b.id
    end)
    local total = #rows
    while #rows > RISK_MAX do table.remove(rows) end
    AT_RISK_CACHE = {day = day, rows = rows, total = total}
    return rows, total
end

-- --- the report ------------------------------------------------------------

local function place_at(x, y, z)
    local out
    pcall(function()
        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(x, y, z)) or {}) do
            out = out or df.civzone_type[zn.type]
        end
    end)
    return out
end

function report()
    local st = state()
    local rows = {}
    local insane = insane_units()
    local ctx
    for _, e in ipairs(insane) do
        local u = e.u
        local row = {id = u.id, name = name_of(u), kind = e.kind, mood = e.mood}
        local x, y, z = pos_of(u)
        if x then
            row.x, row.y, row.z = x, y, z
            row.place = place_at(x, y, z)
            if e.kind ~= 'catatonic' and e.kind ~= 'berserk' then
                local near, tiles = hazards_near(x, y, z)
                row.hazards = near
                if GUARDED[e.kind] then
                    -- the doors the guard would lock now (not locked already, not resting)
                    ctx = ctx or context()
                    local n = 0
                    for _, d in ipairs(doors_between(ctx, x, y, z, tiles)) do
                        if not flag(d.b, 'forbidden') and not st.rest[tostring(d.b.id)] then n = n + 1 end
                    end
                    row.doors = n
                end
            end
        end
        local held = 0
        for _, l in pairs(st.locks) do if l.unit == u.id then held = held + 1 end end
        row.locked = held
        table.insert(rows, row)
    end
    local risk, total = at_risk()
    return {list = rows, locks = count(st.locks), at_risk = risk, at_risk_total = total}
end

-- --- the guard -------------------------------------------------------------

-- o.units: the guarded dwarves' ids (each must be one of the fort's
-- melancholy or raving; nil: all of them). dry: count, change nothing.
function guard(o, dry)
    o = o or {}
    local now = now_tick()
    local st = state()
    local want
    if type(o.units) == 'table' then
        want = {}
        for _, id in ipairs(o.units) do want[id] = true end
    end
    local guarded = {}
    for _, e in ipairs(insane_units()) do
        if GUARDED[e.kind] and (want == nil or want[e.u.id]) then
            local x, y, z = pos_of(e.u)
            if x then table.insert(guarded, {u = e.u, x = x, y = y, z = z}) end
        end
    end
    local released, locked, doors = 0, 0, {}
    -- 1. the held locks: freed when the door is gone or was unlocked by
    -- someone else (forgotten), no guarded dwarf is near, or held too long
    for key, l in pairs(st.locks) do
        local b = find_building(l.id)
        local free, forget = false, false
        if not b or not flag(b, 'forbidden') then
            forget = true
        else
            local near = false
            for _, g in ipairs(guarded) do
                if math.abs(g.z - l.z) <= 1 and dist(g.x, g.y, g.z, l.x, l.y, l.z) <= RELEASE_NEAR then near = true end
            end
            if not near then free = true
            elseif now - (l.since or now) >= LOCK_MAX_TICKS then
                free = true
                st.rest[key] = now
            end
        end
        if forget and b and not dry then
            -- unlocked by someone else (the player): not locked again for LEFT_TICKS
            st.rest[key] = now + LEFT_TICKS - REST_TICKS
        end
        if free or forget then
            if free and not dry then pcall(function() b.door_flags.forbidden = false end) end
            if free then released = released + 1 end
            if not dry then st.locks[key] = nil end
        end
    end
    for key, t in pairs(st.rest) do
        if type(t) ~= 'number' or now - t >= REST_TICKS then st.rest[key] = nil end
    end
    -- 2. the doors between each guarded dwarf and the deadly ground near them
    if #guarded > 0 then
        local ctx = context()
        local held = count(st.locks)
        for _, g in ipairs(guarded) do
            local _, tiles = hazards_near(g.x, g.y, g.z)
            for _, d in ipairs(doors_between(ctx, g.x, g.y, g.z, tiles)) do
                local key = tostring(d.b.id)
                if not st.locks[key] and not st.rest[key] and not flag(d.b, 'forbidden')
                        and held + locked < MAX_LOCKS then
                    if not dry then
                        pcall(function() d.b.door_flags.forbidden = true end)
                        st.locks[key] = {id = d.b.id, unit = g.u.id, since = now, x = d.x, y = d.y, z = d.z,
                                         hazard = d.hazard}
                    end
                    locked = locked + 1
                    table.insert(doors, {id = d.b.id, unit = g.u.id, hazard = d.hazard})
                end
            end
        end
    end
    if not dry then save(st) end
    return {ok = true, locked = locked, released = released, held = count(st.locks), doors = doors,
            guarded = #guarded, dry_run = dry or nil}
end
