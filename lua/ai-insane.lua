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
-- A locked door is passed by no creature but a building destroyer, sane or
-- not: the one lever the AI has. It locks only its own doors (inside the
-- levels it dug: the builder's project areas, the wells' excepted, a dropped
-- well's outline too, whose doors their own rules run), never a hatch (one
-- over stairs or a shaft is a way between levels the walk below can't
-- judge), never a gate piece (the entrances' watcher's), one the threats
-- rules hold or could need (a werebeast cell's, the cavern seal's, one on a
-- way down to the caverns on record, one the gate watcher holds: ai-threats
-- claimed_doors), one on a lever, one already locked (the player's or another
-- rule's), and only a door that truly stands between: a walk from the dwarf
-- (through no door it would lock, nor a locked one, in a box round them, the
-- door and the ground) never reaches the deadly ground, and a walk from that
-- ground never reaches the dwarf, the door touching both; never one with a
-- sane citizen on the deadly side (it would shut them in). It frees each lock
-- as soon as no guarded dwarf is near, or after LOCK_MAX_TICKS (then rests it
-- REST_TICKS: anyone shut in on the far side gets out), never locks again for
-- a week a door someone else opened, and never holds more than MAX_LOCKS. A
-- lock another rule has claimed since (a cell or the seal took the door over)
-- is dropped from the record and left locked. The report frees the stale
-- locks itself (held too long, or nobody guarded near), so they never
-- outlast the guard (the AI halted, the brain stopped). Each lock records the
-- door's state just before (`before`: unlocked, as the guard locks no other);
-- a door the player locks again after the AI's lock can't be told apart from
-- the AI's, and is opened with it: accepted (the player can lock it again).
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
FILL_MARGIN = 4       -- the walks between the dwarf and the ground keep to a box this much round them
-- (0.105.40b fix 3) a walk is capped at the box's own volume (it can't pass it: the box bounds it)
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
-- ones' outlines), the wells' left out ((0.105.40b fix) a dropped well's
-- outline too: marked `well` by the builder since; an older save's can't be
-- told apart)
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
        for _, a in ipairs(data.old_areas or {}) do
            if type(a) == 'table' and not a.well then table.insert(boxes, a) end
        end
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

-- (0.105.40b fix) the doors and hatches the threats rules hold or could need
-- (ai-threats claimed_doors), and the gate pieces
function claimed_ids(gates)
    local ids = {}
    for id in pairs(gates or gate_ids()) do ids[id] = true end
    pcall(function()
        for id in pairs(reqscript('ai-threats').claimed_doors() or {}) do ids[tonumber(id) or id] = true end
    end)
    return ids
end

-- (0.105.40b fix 2) the doors the threats rules have taken over (a cell's
-- locked doors, the seal's: ai-threats adopted_doors): a lock of the AI's on
-- one is dropped unopened; one they only could need is freed as usual
function adopted_ids()
    local ids = {}
    local ok = pcall(function()
        for id in pairs(reqscript('ai-threats').adopted_doors() or {}) do ids[tonumber(id) or id] = true end
    end)
    -- (lead) the gate pieces too: a door that became an AI gate piece after
    -- it was locked here is the gate watcher's now, left as it is
    pcall(function() for id in pairs(gate_ids()) do ids[id] = true end end)
    -- (lead) the threats rules unreadable: nothing freed this time (a cell's
    -- or the seal's door could be among the locks), read again next cycle
    if not ok then ids.__unknown = true end
    return ids
end

-- the doors (never a hatch: (0.105.40b fix) one over stairs or a shaft is a
-- way between levels, not a door in a wall)
local function door_list()
    local out = {}
    local ok = pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.DOOR) do table.insert(out, b) end
    end)
    if ok then return out end
    out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if df.building_type[b:getType()] == 'Door' then table.insert(out, b) end
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

-- --- the walk: does a door stand between? ------------------------------------

local function tkey(x, y, z) return x .. ',' .. y .. ',' .. z end

local BLOCKS = {WALL = true, FORTIFICATION = true}
local UP = {STAIR_UP = true, STAIR_UPDOWN = true}
local DOWN = {STAIR_DOWN = true, STAIR_UPDOWN = true}

-- A walker over the tiles in `box`, with the tiles in `shut` closed: a
-- cache of what each tile is. step(x, y, z, f) calls f on each tile one step
-- on (on the level, up or down stairs, onto a ramp's top and down it, a fall
-- through open space).
local function walker(box, shut)
    local cache = {}
    local function info(x, y, z)
        local k = tkey(x, y, z)
        local c = cache[k]
        if c == nil then
            local shape = shape_at(x, y, z)
            local okf, des = pcall(dfhack.maps.getTileFlags, x, y, z)
            local seen = okf and des and not des.hidden
            c = {shape = shape, open = shape ~= nil and not BLOCKS[shape] and seen and true or false}
            cache[k] = c
        end
        return c
    end
    local function inside(x, y, z)
        return x >= box.x1 and x <= box.x2 and y >= box.y1 and y <= box.y2 and z >= box.z1 and z <= box.z2
    end
    local function ok(x, y, z)
        return inside(x, y, z) and not shut[tkey(x, y, z)] and info(x, y, z).open
    end
    local function step(x, y, z, f)
        local here = info(x, y, z).shape
        for dx = -1, 1 do
            for dy = -1, 1 do
                if (dx ~= 0 or dy ~= 0) and ok(x + dx, y + dy, z) then f(x + dx, y + dy, z) end
                if here == 'RAMP' and ok(x + dx, y + dy, z + 1) then f(x + dx, y + dy, z + 1) end
            end
        end
        if UP[here] and ok(x, y, z + 1) and DOWN[info(x, y, z + 1).shape] then f(x, y, z + 1) end
        if (DOWN[here] and ok(x, y, z - 1) and UP[info(x, y, z - 1).shape])
                or ((here == 'RAMP_TOP' or here == 'EMPTY') and ok(x, y, z - 1)) then
            f(x, y, z - 1)
        end
    end
    return step, inside
end

-- The tiles reached from (x, y, z): {key = true}, and whether `cap` tiles
-- were passed (not judged; the box's volume, so only a safety net). `stop`: a set of keys whose reaching ends the walk
-- (returns true as the third value).
local function walk(step, x, y, z, stop, cap)
    local seen, queue, head, n = {[tkey(x, y, z)] = true}, {{x, y, z}}, 1, 1
    if stop and stop[tkey(x, y, z)] then return seen, false, true end
    while queue[head] do
        local p = queue[head]
        head = head + 1
        local hit = false
        step(p[1], p[2], p[3], function(a, b, c)
            local k = tkey(a, b, c)
            if not seen[k] and not hit then
                seen[k] = true
                n = n + 1
                if stop and stop[k] then hit = true end
                table.insert(queue, {a, b, c})
            end
        end)
        if hit then return seen, false, true end
        if n > cap then return seen, true, false end
    end
    return seen, false, false
end

-- a tile of `set` one step from the door at (x, y, z), on its level
local function touches(set, x, y, z)
    for dx = -1, 1 do
        for dy = -1, 1 do
            if (dx ~= 0 or dy ~= 0) and set[tkey(x + dx, y + dy, z)] then return true end
        end
    end
    return false
end

-- The AI's doors between a dwarf at (x, y, z) and the deadly ground
-- `tiles`: {b, x, y, z, hazard}. ctx: {boxes, gates, claimed, doors, shut,
-- sane} (read once a call). (0.105.40b fix) A door near both (the old
-- distance test) is only a candidate: with every candidate and every locked
-- door shut, the walk from the dwarf must not reach the deadly ground, the
-- walk from that ground must not reach the dwarf's side nor find a sane
-- citizen, and the door must touch both sides.
function doors_between(ctx, x, y, z, tiles)
    local out = {}
    if #tiles == 0 then return out end
    local cands = {}
    for _, b in ipairs(ctx.doors) do
        local bx, by, bz = bpos(b)
        if bx and math.abs(bz - z) <= 1 and dist(x, y, z, bx, by, bz) <= DOOR_NEAR
                and not ctx.gates[b.id] and not ctx.claimed[b.id] and not flag(b, 'operated_by_mechanisms')
                and built(b) and in_boxes(ctx.boxes, bx, by, bz) then
            local dd = dist(x, y, z, bx, by, bz)
            local hz = {}
            for _, h in ipairs(tiles) do
                local dh = dist(bx, by, bz, h.x, h.y, h.z)
                -- the door nearer the ground than the dwarf is: perhaps in the way
                if dh <= DOOR_HAZARD and h.d > dh and h.d >= dd then table.insert(hz, h) end
            end
            if #hz > 0 then table.insert(cands, {b = b, x = bx, y = by, z = bz, hz = hz}) end
        end
    end
    if #cands == 0 then return out end
    -- the box the walks keep to, and the tiles shut in them
    local box = {x1 = x, x2 = x, y1 = y, y2 = y, z1 = z, z2 = z}
    local function grow(px, py, pz)
        box.x1, box.x2 = math.min(box.x1, px), math.max(box.x2, px)
        box.y1, box.y2 = math.min(box.y1, py), math.max(box.y2, py)
        box.z1, box.z2 = math.min(box.z1, pz), math.max(box.z2, pz)
    end
    local shut, hzset = {}, {}
    for k in pairs(ctx.shut) do shut[k] = true end
    for _, c in ipairs(cands) do
        grow(c.x, c.y, c.z)
        shut[tkey(c.x, c.y, c.z)] = true
        for _, h in ipairs(c.hz) do grow(h.x, h.y, h.z); hzset[tkey(h.x, h.y, h.z)] = true end
    end
    box.x1, box.x2 = box.x1 - FILL_MARGIN, box.x2 + FILL_MARGIN
    box.y1, box.y2 = box.y1 - FILL_MARGIN, box.y2 + FILL_MARGIN
    box.z1, box.z2 = box.z1 - 1, box.z2 + 1               -- a way round by a level above or below
    local step = walker(box, shut)
    -- the dwarf's side: reaching the ground (a door no lock helps) or too big: nothing locked
    local cap = (box.x2 - box.x1 + 1) * (box.y2 - box.y1 + 1) * (box.z2 - box.z1 + 1)
    local mine, big, hit = walk(step, x, y, z, hzset, cap)
    if big or hit then return out end
    -- the ground's sides, each walked once
    local side_of, sides = {}, {}
    local function side(h)
        local k = tkey(h.x, h.y, h.z)
        if side_of[k] then return sides[side_of[k]] end
        -- (0.105.40b fix 3) judged by reaching the dwarf's side or a sane citizen only
        local set, _, hit2 = walk(step, h.x, h.y, h.z, mine, cap)
        local sd = {set = set, bad = hit2}
        if not sd.bad then
            for sk in pairs(ctx.sane) do
                if set[sk] then sd.bad = true break end
            end
        end
        table.insert(sides, sd)
        for sk in pairs(set) do
            if hzset[sk] and not side_of[sk] then side_of[sk] = #sides end
        end
        side_of[k] = #sides
        return sd
    end
    for _, c in ipairs(cands) do
        if touches(mine, c.x, c.y, c.z) then
            for _, h in ipairs(c.hz) do
                local sd = side(h)
                if not sd.bad and touches(sd.set, c.x, c.y, c.z) then
                    table.insert(out, {b = c.b, x = c.x, y = c.y, z = c.z, hazard = h.kind})
                    break
                end
            end
        end
    end
    return out
end

-- the sane citizens' tiles (the insane are left out of DFHack's citizens)
local function sane_tiles()
    local out = {}
    local okc, cits = pcall(U.citizens)
    for _, u in ipairs(okc and cits or {}) do
        local kind = kind_of(u)
        if not kind then
            local x, y, z = pos_of(u)
            if x then out[tkey(x, y, z)] = true end
        end
    end
    return out
end

local function context()
    local gates = gate_ids()
    local doors = door_list()
    local shut = {}
    for _, b in ipairs(doors) do
        if flag(b, 'forbidden') then
            local bx, by, bz = bpos(b)
            if bx then shut[tkey(bx, by, bz)] = true end
        end
    end
    return {boxes = ai_boxes(), gates = gates, claimed = claimed_ids(gates), doors = doors, shut = shut,
            sane = sane_tiles()}
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

-- (0.105.40b fix) the doors held locked for the insane now: {id = true}
-- (ai-threats' cells and seal take them over: adopted_doors)
function held_ids()
    local out = {}
    for _, l in pairs(state().locks) do
        if type(l) == 'table' and l.id ~= nil then out[l.id] = true end
    end
    return out
end

-- The held locks: freed when no guarded dwarf (`guarded`: {x, y, z}) is
-- near, or held too long; forgotten when the door is gone or was unlocked by
-- someone else; (0.105.40b fix) dropped, left locked, when another rule has
-- taken the door over since (`claimed`: ai-threats adopted_doors, a cell's
-- or the seal's; a door they only could need is freed as usual). Returns how many were freed, and
-- whether the record changed.
function release_locks(st, guarded, now, dry, claimed)
    local released, changed = 0, false
    for key, l in pairs(st.locks) do
        local b = type(l) == 'table' and find_building(l.id) or nil
        local free, forget = false, false
        if not b or not flag(b, 'forbidden') then
            forget = true
        elseif claimed and claimed.__unknown and now - (l.since or now) < 2 * LOCK_MAX_TICKS then
            -- (lead) whose doors are whose can't be read: kept locked for now
            -- (at most twice the usual hold; then freed as usual below)
        elseif claimed and claimed[l.id] then
            forget = true          -- a cell's or the seal's now: theirs to open
        else
            local near = false
            for _, g in ipairs(guarded) do
                if math.abs(g.z - l.z) <= 1 and dist(g.x, g.y, g.z, l.x, l.y, l.z) <= RELEASE_NEAR then near = true end
            end
            if not near then free = true
            elseif now - (l.since or now) >= LOCK_MAX_TICKS then
                free = true
                if not dry then st.rest[key] = now end
            end
        end
        if forget and b and not dry and not (claimed and claimed[l.id]) then
            -- unlocked by someone else (the player): not locked again for LEFT_TICKS
            st.rest[key] = now + LEFT_TICKS - REST_TICKS
        end
        if free or forget then
            -- unlocked only when it was unlocked before the AI's lock (always,
            -- as the guard locks no locked door; a `before` from an odd record kept)
            if free and not dry and l.before ~= true then
                pcall(function() b.door_flags.forbidden = false end)
            end
            if free then released = released + 1 end
            if not dry then
                st.locks[key] = nil
                changed = true
            end
        end
    end
    return released, changed
end

-- the melancholy and raving dwarves with their places: {u, x, y, z}
local function guarded_units(want)
    local out = {}
    for _, e in ipairs(insane_units()) do
        if GUARDED[e.kind] and (want == nil or want[e.u.id]) then
            local x, y, z = pos_of(e.u)
            if x then table.insert(out, {u = e.u, x = x, y = y, z = z}) end
        end
    end
    return out
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
    -- (0.105.40b fix) the stale locks freed here too (held too long, nobody
    -- guarded near, claimed since): never left on while the guard can't run
    if next(st.locks) ~= nil then
        local _, changed = release_locks(st, guarded_units(nil), now_tick(), false, adopted_ids())
        if changed then save(st) end
    end
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
    local guarded = guarded_units(want)
    local locked, doors = 0, {}
    -- 1. the held locks: freed when the door is gone or was unlocked by
    -- someone else (forgotten), claimed by another rule since (dropped, left
    -- locked), no guarded dwarf is near, or held too long
    local released = release_locks(st, guarded, now, dry, adopted_ids())
    for key, t in pairs(st.rest) do
        if type(t) ~= 'number' or now - t >= REST_TICKS then st.rest[key] = nil end
    end
    -- 2. the doors between each guarded dwarf and the deadly ground near them
    -- ((0.105.40b fix) none while halted: o.release_only)
    if #guarded > 0 and not o.release_only then
        local ctx = context()
        local held = count(st.locks)
        for _, g in ipairs(guarded) do
            local _, tiles = hazards_near(g.x, g.y, g.z)
            for _, d in ipairs(doors_between(ctx, g.x, g.y, g.z, tiles)) do
                local key = tostring(d.b.id)
                if not st.locks[key] and not st.rest[key] and not flag(d.b, 'forbidden')
                        and held + locked < MAX_LOCKS then
                    if not dry then
                        local before = flag(d.b, 'forbidden')      -- (0.105.40b fix) as it was just before
                        pcall(function() d.b.door_flags.forbidden = true end)
                        st.locks[key] = {id = d.b.id, unit = g.u.id, since = now, x = d.x, y = d.y, z = d.z,
                                         hazard = d.hazard, before = before}
                    end
                    locked = locked + 1
                    table.insert(doors, {id = d.b.id, unit = g.u.id, hazard = d.hazard})
                end
            end
        end
    end
    if not dry then save(st) end
    return {ok = true, locked = locked, released = released, held = count(st.locks), doors = doors,
            guarded = #guarded, dry_run = dry or nil, release_only = o.release_only or nil}
end
