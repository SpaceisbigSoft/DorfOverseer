-- ai-waterworks-power: the steps' helpers, and W7: power for the pump stack (its plan, its step).
--
-- (r8) A part of ai-waterworks, not a script of its own: ai-waterworks.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-waterworks').name and the hooks and helpers defined there
-- (T, building, designate, load_state, ...) are in reach.

if not WATERWORKS_PART_LOCALS then qerror('ai-waterworks-power is a part of ai-waterworks; run ai-waterworks') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-waterworks-power'] = '0.105.116'   -- (0.105.26) bumped with BRIDGE_VERSION

-- (r8) the hub's and earlier parts' locals used here
local key, rock, ground, l_path, N4, N8 = WATERWORKS_PART_LOCALS.key, WATERWORKS_PART_LOCALS.rock, WATERWORKS_PART_LOCALS.ground, WATERWORKS_PART_LOCALS.l_path, WATERWORKS_PART_LOCALS.N4, WATERWORKS_PART_LOCALS.N8

---------------------------------------------------------------------------
-- The steps
---------------------------------------------------------------------------

local function dug(t, text)
    if not t then return false end
    if text == 'h' then return t.shape == 'EMPTY' or t.shape == 'RAMP_TOP' end
    if text == 'j' then return t.shape == 'STAIR_DOWN' or t.shape == 'STAIR_UPDOWN' end
    if text == 'u' then return t.shape == 'STAIR_UP' or t.shape == 'STAIR_UPDOWN' end
    if text == 'i' then return t.shape == 'STAIR_UPDOWN' end
    if text == 'z' then return t.shape == 'FLOOR' end
    return t.shape ~= 'WALL'
end

local function by_z(cells)
    local out, zs = {}, {}
    for _, c in ipairs(cells) do
        if not out[c.z] then out[c.z] = {}; table.insert(zs, c.z) end
        table.insert(out[c.z], {x = c.x, y = c.y, text = c.text})
    end
    table.sort(zs, function(a, b) return a > b end)
    return out, zs
end

local function designate_all(cells, mode)
    local g, zs = by_z(cells)
    for _, z in ipairs(zs) do
        if not designate(g[z], z, mode) then return false, z end
    end
    return true
end

-- (0.105.37 fix) the cells not dug yet (a power planned again over its own
-- old shaft designates only what is left)
local function undug(cells)
    local out = {}
    for _, c in ipairs(cells or {}) do if not dug(T(c.x, c.y, c.z), c.text) then table.insert(out, c) end end
    return out
end

local function left_to_dig(cells)
    local n = 0
    for _, c in ipairs(cells or {}) do if not dug(T(c.x, c.y, c.z), c.text) then n = n + 1 end end
    return n
end

-- liquid seen outside the work's tiles, beside its wet tiles (a leak)
local function leak(p)
    local planned = {}
    for _, c in ipairs(p.tiles) do planned[key(c.x, c.y, c.z)] = true end
    local src = p.plug
    for _, c in ipairs(p.wet) do
        for _, d in ipairs(N8) do
            local x, y = c.x + d[1], c.y + d[2]
            if not planned[key(x, y, c.z)] and math.max(math.abs(x - src.x), math.abs(y - src.y)) > 1 then
                local t = T(x, y, c.z)
                if t and t.liquid and not (p.kind == 'moat' and t.outside) then return {x = x, y = y, z = c.z} end
            end
        end
    end
    return nil
end

local function depth_at(c)
    local t = T(c.x, c.y, c.z)
    return t and t.liquid and (t.depth or 0) or 0, t
end

---------------------------------------------------------------------------
-- (0.105.37 E3) W7: power for the pump stack
---------------------------------------------------------------------------
-- The pump stack (W4) is worked by hand. Its power: a water wheel on the
-- river (flowing water under it) or a windmill (the map's wind), joined to
-- the stack by a shaft of vertical axles straight down over the top pump's
-- output tile (DF: a screw pump "accepts and transfers power using either
-- tile of the pump, in all orthogonal directions, including above and
-- below"; the pumps pass power on to each other), and on the surface by
-- horizontal axles and gear assemblies. Begun only when the stack is done
-- (its floodgate, the water's stop, built and tested).
--
-- (0.105.37 fix) The power never joins the fort to the outside or the sky.
-- Gears and axles block nothing, and floors block power between levels (the
-- wiki's Axle page), so every link between levels is an open tile; the seals
-- are machines nothing passes: a screw pump's output tile ("blocks liquid
-- flow and creature movement") and a standing windmill's centre ("does not
-- permit passage"). The shaft and its access stair are a pocket in solid
-- rock from zt + 2 to the ground's level less one: every tile beside them on
-- their levels is rock. At its foot (zt + 1, the fort's level over the top
-- pump) a screw pump's output fills the shaft's column over the top pump's
-- output, so the shaft opens onto two outputs and nothing else; that pump's
-- intake is a nook of the fort (dug and built from the fort's side), over
-- solid rock with nothing to pump. The pocket's floor at zt + 2 stays a rock
-- plug until that pump stands. Its top is roofed by the rock: the switch
-- gear at ztop - 1 under the ground; the windmill's centre over its gear;
-- for a wheel, a second screw pump under the ground (the top seal) whose
-- output lies under the ground's gear D, the power's one opening to the sky.
-- The stair's hatch is built last and locked. Pumped water rises at most to
-- the pump's own level (the water rules, design-notes W1), so none climbs
-- into the shaft; any water seen in it stops the power, shuts the stack's
-- floodgate and holds the work. The shaft's top and stair are kept 2 tiles
-- from any water (dry_near).
--
-- The power's stop: a gear assembly on a lever ("AI pump power") that bears
-- nothing (a wheel or an axle resting on a disengaged gear falls), pulled
-- at once on a flood, water in the shaft or the stack held, and pulled to
-- keep the reservoir between POWER_LOW and POWER_HIGH. A wheel that stops
-- (its river frozen or low) is paused: the power off, the pumps worked by
-- hand, on again when it turns; retired only when it stood still through
-- WHEEL_RETIRE_DAYS of unfrozen river (a full thawed season). Held when the
-- wind is too weak or the power falls short.
--
-- The power check, DF's numbers (the wiki's Power page): a screw pump needs
-- 10 (the two seals too), a gear assembly 5, an axle 1 a tile; a water wheel
-- gives 100 in flowing water (10 of it turning itself), a windmill 40 (20,
-- or 0, in poor wind; the same all the map's life).
POWER_PUMP = 10
POWER_GEAR = 5
POWER_AXLE = 1
POWER_WHEEL = 100
POWER_WHEEL_OWN = 10
POWER_WINDMILL = 40
POWER_SHAFT_MAX = 30    -- levels from the top pump to the surface at most
POWER_RUN_MAX = 30      -- tiles of axle on the surface at most
AXLE_SEG = 10           -- a horizontal axle this long at most (several in a row)
WHEELS_MAX = 3          -- side by side over the river, each on the last's centre
POWER_LOW = 3           -- the reservoir this low: the power on
POWER_HIGH = 5          -- this high: off
WHEEL_DRY_DAYS = 14     -- (unused since 0.105.37 fix: a still wheel is paused, see WHEEL_RETIRE_DAYS)
WHEEL_RETIRE_DAYS = 84  -- (0.105.37 fix) a still wheel over unfrozen water this long (a season): held, retired
WIND_DAYS = 14          -- the windmill still this long: held
WHEEL_FAR_CENTRES = 12  -- (0.105.38 review) a far river's wheel: its centres nearest the shaft tried at most
WHEEL_FAR_SECONDS = 0.25 -- (0.105.38 review) the far wheel's search this long at most (then: tried again later)
POWER_SHORT_DAYS = 14   -- less power than the machine needs this long: held
POWER_PULL_DAYS = 2     -- a pull to switch the power on asked again no sooner

local OWN = {}           -- (0.105.37 fix) the plan being made: the older plan's tiles (own_tiles)

-- open space over flowing river water: a water wheel's tile; the water's depth, or nil
local function wheel_tile(x, y, z)
    local t, b = T(x, y, z), T(x, y, z - 1)
    if not (t and t.shape == 'EMPTY' and not t.liquid and (not t.building or OWN[key(x, y, z)])) then return nil end
    if not (b and b.liquid and not b.magma and (b.material == 'RIVER' or b.material == 'BROOK')) then return nil end
    return b.depth or 0
end

-- no water within r tiles, on the level and the one under it
local function dry_near(x, y, z, r)
    for dz = -1, 0 do
        for dx = -r, r do for dy = -r, r do
            local t = T(x + dx, y + dy, z + dz)
            if t and t.liquid then return false end
        end end
    end
    return true
end

-- the pump stack's top screw pump: its intake tile {x, y, z} and its
-- output tile {x, y} (the plan's `down` marks the intakes)
local function top_pump(pp)
    local best
    for _, b in ipairs(pp.builds or {}) do
        if b.kind == 'ScrewPump' and (not best or b.z > best.z) then best = b end
    end
    if not best or type(pp.down) ~= 'table' then return nil end
    local w, h = tostring(best.text or ''):match('%((%d+)x(%d+)%)')
    w, h = tonumber(w) or 1, tonumber(h) or 1
    local a, b = {x = best.x, y = best.y}, {x = best.x + w - 1, y = best.y + h - 1}
    if pp.down[key(a.x, a.y, best.z)] then return {x = a.x, y = a.y, z = best.z}, b end
    if pp.down[key(b.x, b.y, best.z)] then return {x = b.x, y = b.y, z = best.z}, a end
    return nil
end

-- A screw pump with its intake on tile a and its output on b (orthogonal
-- neighbours): its quickfort key ("pumps from" the intake's side) and its
-- top-left corner.
local function pump_text(a, b)
    if b.x == a.x + 1 then return 'Msh(2x1)', a.x, a.y end
    if b.x == a.x - 1 then return 'Msk(2x1)', b.x, b.y end
    if b.y == a.y + 1 then return 'Msu(1x2)', a.x, a.y end
    return 'Msm(1x2)', b.x, b.y
end

-- (0.105.37 fix) The power's own tiles from an older plan (planned again
-- after a retire): dug, channelled or built by it. Seen as its own, never as
-- "not solid rock": the planner reuses its old shaft and machines.
local function own_tiles(old)
    local own = {}
    if type(old) ~= 'table' then return own end
    for _, list in ipairs({old.dig or {}, old.dig2 or {}, old.dig3 or {}, old.pocket or {}}) do
        for _, c in ipairs(list) do own[key(c.x, c.y, c.z)] = true end
    end
    for _, b in ipairs(old.builds or {}) do
        local w, h = tostring(b.text or ''):match('%((%d+)x(%d+)%)')
        w, h = tonumber(w) or 1, tonumber(h) or 1
        for x = b.x, b.x + w - 1 do for y = b.y, b.y + h - 1 do own[key(x, y, b.z)] = true end end
    end
    if type(old.hatch) == 'table' then own[key(old.hatch.x, old.hatch.y, old.hatch.z)] = true end
    return own
end

local function rock_or_own(x, y, z) return OWN[key(x, y, z)] or rock(T(x, y, z)) end
local function ground_or_own(x, y, z)
    if OWN[key(x, y, z)] or ground(x, y, z) then return true end
    -- (open ground over the old plan's own dug tile: its shaft's roof)
    local t = T(x, y, z)
    return OWN[key(x, y, z - 1)] == true and t ~= nil and t.outside == true and not t.liquid
        and (t.shape == 'FLOOR' or t.shape == 'SHRUB' or t.shape == 'SAPLING' or t.shape == 'PEBBLES')
end

-- The shaft and its access stair: the shaft C (over the top pump's output)
-- and the stair S = C + d, from zt + 2 to ztop - 1, with `extra` tiles: all
-- solid rock, and every tile beside them on their level rock or their own.
-- The pocket joins nothing: not the fort, not the pump stack, not the river.
-- Its floor at zt + 2 is the rock plug over the foot (cut only once the
-- foot's pump stands). {S, list} or nil, why
local function power_pocket(C, zt, ztop, d, extra)
    local S = {x = C.x + d[1], y = C.y + d[2]}
    local list, set = {}, {}
    local function add(x, y, z) table.insert(list, {x = x, y = y, z = z}); set[key(x, y, z)] = true end
    for z = zt + 2, ztop - 1 do add(C.x, C.y, z) end      -- (the shaft first: its reasons said first)
    for z = zt + 2, ztop - 1 do add(S.x, S.y, z) end
    for _, c in ipairs(extra or {}) do add(c.x, c.y, c.z) end
    for _, c in ipairs(list) do
        if not rock_or_own(c.x, c.y, c.z) then
            return nil, ('the shaft\'s stair would cross something other than solid rock at x%d y%d, elevation %d')
                :format(c.x, c.y, ez(c.z))
        end
    end
    for _, c in ipairs(list) do
        for _, n in ipairs(N8) do
            local x, y = c.x + n[1], c.y + n[2]
            if not set[key(x, y, c.z)] and not rock_or_own(x, y, c.z) then
                return nil, ('the shaft would touch something other than solid rock at x%d y%d, elevation %d '
                             .. '(it must join nothing of the fort)'):format(x, y, ez(c.z))
            end
        end
    end
    if not ground_or_own(S.x, S.y, ztop) then
        return nil, ('no dry open ground for the shaft\'s stair at x%d y%d, elevation %d'):format(S.x, S.y, ez(ztop))
    end
    return {S = S, list = list}
end

local WALK_SHAPES = {FLOOR = true, STAIR_UP = true, STAIR_DOWN = true, STAIR_UPDOWN = true, RAMP = true}

-- The foot: a screw pump on the level over the top pump (zt + 1), its
-- output tile C over the top pump's output (both impassable: DF's screw
-- pump output "blocks liquid flow and creature movement"), its intake I0
-- beside it on dug floor over solid rock (nothing under it to pump). It
-- takes the shaft's power down into the stack through the channel at C and
-- seals the shaft from the fort's level and from the stack: nothing walks,
-- flies or flows between them. Dug and built from the fort's side (a fort
-- tile beside I0). {I0, text, x, y} or nil, why
local function power_foot(pp, C, zt)
    local z = zt + 1
    if not rock_or_own(C.x, C.y, z) then
        return nil, ('the foot of the shaft over the top pump is not solid rock at x%d y%d, elevation %d')
            :format(C.x, C.y, ez(z))
    end
    local stack = {}
    for _, c in ipairs(pp.dig or {}) do stack[key(c.x, c.y, c.z)] = true end
    local why
    for _, f in ipairs(N4) do
        local I = {x = C.x + f[1], y = C.y + f[2]}
        local ok = not stack[key(I.x, I.y, z)] and rock_or_own(I.x, I.y, z) and rock(T(I.x, I.y, z - 1))
        if not ok then
            why = why or 'no solid rock beside the shaft\'s foot for its pump (with rock under its intake)'
        else
            -- nothing beside the foot open to the sky or holding water; a fort
            -- tile beside the intake to dig and build it from
            local reach = false
            for _, c in ipairs({C, I}) do
                for _, n in ipairs(N8) do
                    local x, y = c.x + n[1], c.y + n[2]
                    local t = T(x, y, z)
                    if t and (t.liquid or t.outside or t.feature or t.aquifer) then
                        ok = false
                        why = why or ('the shaft\'s foot would be beside water or open air at x%d y%d, elevation %d')
                            :format(x, y, ez(z))
                    end
                    if c == I and not (x == C.x and y == C.y) and t and WALK_SHAPES[t.shape] and not t.outside
                            and not t.liquid then
                        reach = true
                    end
                end
            end
            if ok and not reach then
                ok = false
                why = why or 'no fort floor beside the shaft\'s foot to dig and build its pump from'
            end
            if ok then
                local text, x, y = pump_text(I, C)
                return {I = I, text = text, x = x, y = y}
            end
        end
    end
    return nil, why
end

-- the digs every power plan shares: the stair and the shaft dug from the
-- surface down to zt + 2 (the plug: its floor kept), the foot dug from the
-- fort's side (its pump's intake floor, the channel over the top pump's
-- output); then the shaft's floors channelled down to zt + 3 (dig2); the
-- plug cut (dig3) only once the foot's pump stands
local function power_digs(p, C, S, zt, ztop, foot, chan_top)
    for z = zt + 2, ztop - 1 do
        table.insert(p.dig, {x = S.x, y = S.y, z = z, text = z == zt + 2 and 'u' or 'i'})
        table.insert(p.dig, {x = C.x, y = C.y, z = z, text = 'd'})
    end
    table.insert(p.dig, {x = S.x, y = S.y, z = ztop, text = 'j'})
    table.insert(p.dig, {x = foot.I.x, y = foot.I.y, z = zt + 1, text = 'd'})
    table.insert(p.dig, {x = C.x, y = C.y, z = zt + 1, text = 'h'})
    for z = zt + 3, chan_top do table.insert(p.dig2, {x = C.x, y = C.y, z = z, text = 'h'}) end
    p.dig3 = {{x = C.x, y = C.y, z = zt + 2, text = 'h'}}
    -- the foot's tiles (watched for water with the pocket)
    table.insert(p.pocket, {x = C.x, y = C.y, z = zt + 1})
    table.insert(p.pocket, {x = foot.I.x, y = foot.I.y, z = zt + 1})
end

local function power_need(pumps, gears, axles)
    return pumps * POWER_PUMP + gears * POWER_GEAR + axles * POWER_AXLE
end

-- the horizontal axles between two gears on one line (a and b excluded), in
-- pieces of AXLE_SEG at most
local function axle_run(a, b, z, out)
    local dx, dy = (b.x > a.x and 1 or b.x < a.x and -1 or 0), (b.y > a.y and 1 or b.y < a.y and -1 or 0)
    local tiles = {}
    local x, y = a.x + dx, a.y + dy
    while not (x == b.x and y == b.y) do table.insert(tiles, {x = x, y = y}); x, y = x + dx, y + dy end
    local i = 1
    while i <= #tiles do
        local j = math.min(#tiles, i + AXLE_SEG - 1)
        local n = j - i + 1
        local x1, y1 = math.min(tiles[i].x, tiles[j].x), math.min(tiles[i].y, tiles[j].y)
        table.insert(out, {x = x1, y = y1, z = z, kind = 'AxleHorizontal',
                           text = dx ~= 0 and ('Mh(%dx1)'):format(n) or ('Mhs(1x%d)'):format(n)})
        i = j + 1
    end
    return #tiles
end

local function power_lever(pp, old)
    -- (planned again) the old lever where it stands
    if type(old) == 'table' and type(old.lever) == 'table' and building(old.lever.x, old.lever.y, old.lever.z, 'Trap') then
        return {x = old.lever.x, y = old.lever.y, z = old.lever.z, name = 'AI pump power'}
    end
    if type(pp.lever) ~= 'table' then return nil end
    local lv = lever_spot(pp.lever.x, pp.lever.y, pp.lever.z, {[key(pp.lever.x, pp.lever.y, pp.lever.z)] = true})
    if lv then lv.name = 'AI pump power' end
    return lv
end

-- the foot's pump, the shaft's axles and its switch (a gear at ztop - 1,
-- under the ground: the shaft stays roofed); the switch's index
local function shaft_builds(p, add, C, zt, ztop, foot)
    local prev = add({x = foot.x, y = foot.y, z = zt + 1, text = foot.text, kind = 'ScrewPump', seal = 'foot'})
    p.foot = prev
    local plug = true
    for z = zt + 2, ztop - 2 do
        prev = add({x = C.x, y = C.y, z = z, text = 'Mv', kind = 'AxleVertical', after = prev, plug = plug or nil})
        plug = false
    end
    p.switch = add({x = C.x, y = C.y, z = ztop - 1, text = 'Mg', kind = 'GearAssembly', after = prev,
                    plug = plug or nil})
    return p.switch
end

-- A water wheel (or two or three side by side) over the river one level
-- under the shaft's ground, a gear on the bank beside its centre, gears and
-- axles along the ground to a gear D over the top seal: a screw pump under
-- the ground (its output under D, its intake beside the switch) that takes
-- the power down and is the shaft's roof where D's channel opens (nothing
-- walks, flies or flows through a pump's output). The axles and gears on the
-- ground stay outside; the shaft is roofed by rock everywhere else.
local function power_wheel(pp, C, zt, ztop, pumps, w, foot)
    local river
    for _, b in ipairs(w and w.bodies or {}) do
        if b.kind == 'river' and (tonumber(b.tiles) or 0) > 0 then river = b end
    end
    -- (0.105.38) and the far ones (tried when none near is within reach)
    local far = far_sources(w, function(b) return b.flow == 'flowing' end)
    if not river and #far == 0 then return nil, 'no river near the fort for a water wheel' end
    local best, why
    local deadline, late          -- (0.105.38 review) the far search's time budget
    for _, e in ipairs(N4) do
        for _, d in ipairs(N4) do
            if d[1] * e[1] + d[2] * e[2] == 0 then
                local I1 = {x = C.x + e[1], y = C.y + e[2]}
                local U = {x = C.x + 2 * e[1], y = C.y + 2 * e[2]}
                local pk, pwhy = power_pocket(C, zt, ztop, d, {{x = I1.x, y = I1.y, z = ztop - 1}, {x = U.x, y = U.y, z = ztop - 1}})
                if not pk then why = why or pwhy goto nexte end
                if not (rock(T(I1.x, I1.y, ztop - 2)) and rock(T(U.x, U.y, ztop - 2))) then
                    why = why or 'no solid rock under the shaft\'s top seal'
                    goto nexte
                end
                if not ground_or_own(U.x, U.y, ztop) then
                    why = why or ('no dry open ground over the shaft\'s top seal at x%d y%d'):format(U.x, U.y)
                    goto nexte
                end
                do
                    local S = pk.S
                    if not (dry_near(S.x, S.y, ztop, 2) and dry_near(U.x, U.y, ztop, 2) and dry_near(C.x, C.y, ztop, 2)) then
                        why = why or 'the shaft\'s top would be within 2 tiles of water'
                        goto nexte
                    end
                    local function walk(x, y)
                        return ground_or_own(x, y, ztop) and not (x == S.x and y == S.y)
                    end
                    local D = U
                    -- (0.105.38) one wheel's centre tried: the axle's run to it this long at most
                    local function try_c(c, runmax, far)
                        if wheel_tile(c.x, c.y, ztop) then
                            for _, u in ipairs({{1, 0}, {0, 1}}) do
                                local v = {u[2], u[1]}
                                for _, s in ipairs({1, -1}) do
                                    local G0 = {x = c.x + v[1] * s, y = c.y + v[2] * s}
                                    if walk(G0.x, G0.y) and not (G0.x == D.x and G0.y == D.y) then
                                        local path = l_path(D, G0, walk, nil, runmax)   -- (review: given up past runmax)
                                        if path and #path <= runmax then
                                            table.insert(path, G0)
                                            -- the gears: D, the corner, the bank
                                            local gears = {1}
                                            for i = 2, #path - 1 do
                                                local a, b2, n = path[i - 1], path[i], path[i + 1]
                                                if (b2.x - a.x) ~= (n.x - b2.x) or (b2.y - a.y) ~= (n.y - b2.y) then
                                                    table.insert(gears, i)
                                                end
                                            end
                                            table.insert(gears, #path)
                                            local axles = {}
                                            local h = 0
                                            for i = 2, #gears do h = h + axle_run(path[gears[i - 1]], path[gears[i]], ztop, axles) end
                                            local vert = ztop - zt - 3
                                            -- the stack's pumps and the two seals; the switch and the ground's gears
                                            local need = power_need(pumps + 2, #gears + 1, vert + h)
                                            local n = (need + POWER_WHEEL - POWER_WHEEL_OWN - 1) // (POWER_WHEEL - POWER_WHEEL_OWN)
                                            n = math.max(1, n)
                                            local ok = n <= WHEELS_MAX
                                            local wheels = {}
                                            for k = 0, (ok and n or 0) - 1 do
                                                local ck = {x = c.x - v[1] * s * k, y = c.y - v[2] * s * k}
                                                local deep = false
                                                for j = -1, 1 do
                                                    local dd = wheel_tile(ck.x + u[1] * j, ck.y + u[2] * j, ztop)
                                                    if not dd then ok = false end
                                                    if dd and dd >= 4 then deep = true end
                                                end
                                                if not deep then ok = false end
                                                table.insert(wheels, ck)
                                            end
                                            if not ok and n > WHEELS_MAX then
                                                why = why or ('the pumps need %d power, more than %d water wheels give (%d each)')
                                                    :format(need, WHEELS_MAX, POWER_WHEEL - POWER_WHEEL_OWN)
                                            end
                                            local score = n * 1000 + #path
                                            if ok and (not best or score < best.score) then
                                                best = {score = score, S = S, pocket = pk.list, path = path, gears = gears,
                                                        axles = axles, wheels = wheels, u = u, need = need + n * POWER_WHEEL_OWN,
                                                        have = n * POWER_WHEEL, n = n, vert = vert, h = h, I1 = I1, U = U,
                                                        far = far}
                                            end
                                        end
                                    end
                                end
                            end
                        end
                    end
                    for dx = -POWER_RUN_MAX, POWER_RUN_MAX do for dy = -POWER_RUN_MAX, POWER_RUN_MAX do
                        try_c({x = D.x + dx, y = D.y + dy}, POWER_RUN_MAX)
                    end end
                    -- (0.105.38) no river within reach of the shaft's top: the far
                    -- ones the survey found, the cheapest first (a long run of axles)
                    -- (0.105.38 review) the WHEEL_FAR_CENTRES wheel tiles nearest the
                    -- shaft's top tried at most, within WHEEL_FAR_SECONDS in all
                    if not best and not late then
                        local cs = {}
                        for _, fr in ipairs(far) do
                            local fn = fr.nearest
                            if fn.z == ztop - 1 then
                                for dx = -6, 6 do for dy = -6, 6 do
                                    local c = {x = fn.x + dx, y = fn.y + dy}
                                    if wheel_tile(c.x, c.y, ztop) then
                                        c.d = math.abs(c.x - D.x) + math.abs(c.y - D.y)
                                        table.insert(cs, c)
                                    end
                                end end
                            end
                        end
                        table.sort(cs, function(a, b) return a.d < b.d end)
                        deadline = deadline or (os.clock() + WHEEL_FAR_SECONDS)
                        for i = 1, math.min(#cs, WHEEL_FAR_CENTRES) do
                            if os.clock() > deadline then late = true break end
                            try_c(cs[i], far_cap(w), true)
                        end
                    end
                end
            end
            ::nexte::
        end
    end
    if not best and late then
        return nil, 'the search for a far river\'s water wheel ran out of time: tried again later', true
    end
    if not best then
        return nil, why or ('no flowing river water (4/7 deep) under open space within %d tiles of the shaft\'s top, '
                            .. 'with dry ground to join them'):format(POWER_RUN_MAX)
    end
    local p = {kind = 'power', v = 2, source = 'wheel', dig = {}, dig2 = {}, builds = {}, pocket = best.pocket,
               far = best.far and {d = #best.path, kind = 'axles'} or nil,
               shaft = {x = C.x, y = C.y, z1 = zt + 1, z2 = ztop - 1}, need = best.need, have = best.have,
               pumps = pumps, wheels = best.n, sources = {}, reservoir = pp.reservoir, test = pp.test}
    power_digs(p, C, best.S, zt, ztop, foot, ztop - 1)
    table.insert(p.dig, {x = best.I1.x, y = best.I1.y, z = ztop - 1, text = 'd'})
    table.insert(p.dig, {x = best.U.x, y = best.U.y, z = ztop - 1, text = 'd'})
    table.insert(p.dig2, {x = best.U.x, y = best.U.y, z = ztop, text = 'h'})       -- D: over the top seal
    local function add(b) table.insert(p.builds, b) return #p.builds end
    shaft_builds(p, add, C, zt, ztop, foot)
    local st, sx, sy = pump_text(best.I1, best.U)
    local seal = add({x = sx, y = sy, z = ztop - 1, text = st, kind = 'ScrewPump', seal = 'top'})
    p.top = seal
    local dgear = add({x = best.U.x, y = best.U.y, z = ztop, text = 'Mg', kind = 'GearAssembly', after = seal})
    for i = 2, #best.gears do
        local g = best.path[best.gears[i]]
        add({x = g.x, y = g.y, z = ztop, text = 'Mg', kind = 'GearAssembly'})
    end
    local bank = #p.builds
    if #best.gears < 2 then bank = dgear end
    for _, a in ipairs(best.axles) do add(a) end
    local prev = bank
    for _, ck in ipairs(best.wheels) do
        local ew = best.u[1] ~= 0
        prev = add({x = ew and ck.x - 1 or ck.x, y = ew and ck.y or ck.y - 1, z = ztop, cx = ck.x, cy = ck.y,
                    text = ew and 'Mws(3x1)' or 'Mw(1x3)', kind = 'WaterWheel', after = prev})
        table.insert(p.sources, prev)
    end
    p.hatch = {x = best.S.x, y = best.S.y, z = ztop, text = 'H', kind = 'Hatch', lock = true}
    p.lever = power_lever(pp, pp.old_)
    if not p.lever then return nil, 'no free floor for the power\'s lever' end
    if p.far then
        local big = job_too_big(p)             -- (0.105.38) a far wheel's run within the job cap
        if big then return nil, big end
    end
    return p
end

-- A windmill on open ground beside the shaft: its centre over a gear under
-- the ground, an axle to the shaft's top gear (the switch, under the ground:
-- the shaft stays roofed; the windmill's centre is its roof over the gear,
-- DF: "this does not permit passage as long as the windmill stands").
local function power_windmill(pp, C, zt, ztop, pumps, foot)
    local why
    for _, d in ipairs(N4) do
        for _, e in ipairs(N4) do
            if d[1] * e[1] + d[2] * e[2] == 0 then
                local E = {x = C.x + e[1], y = C.y + e[2]}
                local M = {x = C.x + 2 * e[1], y = C.y + 2 * e[2]}
                local pk, pwhy = power_pocket(C, zt, ztop, d, {{x = E.x, y = E.y, z = ztop - 1}, {x = M.x, y = M.y, z = ztop - 1}})
                local ok = pk ~= nil
                if not ok then why = why or pwhy end
                if ok then
                    for dx = -1, 1 do for dy = -1, 1 do
                        if not ground_or_own(M.x + dx, M.y + dy, ztop) then ok = false end
                    end end
                    if not ok then why = why or ('no 3x3 of open ground under the sky for the windmill at x%d y%d'):format(M.x, M.y) end
                end
                if ok and not (dry_near(pk.S.x, pk.S.y, ztop, 2) and dry_near(M.x, M.y, ztop, 2)) then
                    ok = false
                    why = why or 'the windmill or the shaft\'s stair would be within 2 tiles of water'
                end
                if ok then
                    local vert = ztop - zt - 3
                    -- the stack's pumps and the foot's; the switch and the windmill's gear
                    local need = power_need(pumps + 1, 2, vert + 1)
                    if need > POWER_WINDMILL then
                        return nil, ('the pumps need %d power, more than a windmill gives (%d at most)'):format(need, POWER_WINDMILL)
                    end
                    local p = {kind = 'power', v = 2, source = 'windmill', dig = {}, dig2 = {}, builds = {}, pocket = pk.list,
                               shaft = {x = C.x, y = C.y, z1 = zt + 1, z2 = ztop - 1}, need = need, have = POWER_WINDMILL,
                               pumps = pumps, sources = {}, reservoir = pp.reservoir, test = pp.test}
                    power_digs(p, C, pk.S, zt, ztop, foot, ztop - 1)
                    table.insert(p.dig, {x = E.x, y = E.y, z = ztop - 1, text = 'd'})
                    table.insert(p.dig, {x = M.x, y = M.y, z = ztop - 1, text = 'd'})
                    table.insert(p.dig2, {x = M.x, y = M.y, z = ztop, text = 'h'})     -- the windmill's centre
                    local function add(b) table.insert(p.builds, b) return #p.builds end
                    shaft_builds(p, add, C, zt, ztop, foot)
                    add({x = E.x, y = E.y, z = ztop - 1, text = e[1] ~= 0 and 'Mh(1x1)' or 'Mhs(1x1)', kind = 'AxleHorizontal'})
                    local wm = add({x = M.x, y = M.y, z = ztop - 1, text = 'Mg', kind = 'GearAssembly'})
                    table.insert(p.sources, add({x = M.x, y = M.y, z = ztop, text = 'windmill', kind = 'Windmill', after = wm}))
                    p.hatch = {x = pk.S.x, y = pk.S.y, z = ztop, text = 'H', kind = 'Hatch', lock = true}
                    p.lever = power_lever(pp, pp.old_)
                    if not p.lever then return nil, 'no free floor for the power\'s lever' end
                    return p
                end
            end
        end
    end
    return nil, why or 'no site for a windmill over the shaft'
end

-- The power for a done pump stack (pw, its work). src: 'wheel', 'windmill'
-- or nil (a wheel if it can, else a windmill). old: the power's earlier plan
-- (planned again after a retire: its shaft and machines are its own, reused
-- where they stand; its own source tried first). The plan, or nil, why.
--
-- (0.105.37 fix) The shaft never joins the fort to the outside or the sky:
-- it runs over the top pump's output and is sealed at both ends by screw
-- pumps' outputs (impassable to creatures and water) or the windmill's
-- centre: the foot's pump on the fort's lowest level, the top seal under the
-- wheel's gear on the ground. Every tile beside the pocket on its levels is
-- rock; its floor at zt + 2 stays a rock plug until the foot's pump stands.
-- Gears and axles block nothing, so nothing of the power opens a way.
function plan_power(pw, src, old)
    local pp = type(pw) == 'table' and pw.plan
    if type(pp) ~= 'table' or pp.kind ~= 'pump' then return nil, 'no pump stack to power' end
    local top, out = top_pump(pp)
    if not top then return nil, 'the pump stack\'s top screw pump is not in its plan' end
    local C, zt = {x = out.x, y = out.y}, top.z
    local pumps = 0
    for _, b in ipairs(pp.builds or {}) do if b.kind == 'ScrewPump' then pumps = pumps + 1 end end
    old = (type(old) == 'table' and old.v == 2) and old or nil
    OWN = own_tiles(old)
    local function done(...) OWN = {} return ... end
    -- the shaft: solid rock straight up from over the top pump's output to the surface
    local ztop
    for z = zt + 1, zt + POWER_SHAFT_MAX + 1 do
        if not rock_or_own(C.x, C.y, z) then
            if ground_or_own(C.x, C.y, z) then ztop = z break end
            return done(nil, ('the shaft over the top pump would cross something other than solid rock at x%d y%d, '
                              .. 'elevation %d (a room, water, a cavern, the aquifer)'):format(C.x, C.y, ez(z)))
        end
    end
    if not ztop then return done(nil, ('the surface is more than %d levels over the top pump'):format(POWER_SHAFT_MAX)) end
    if ztop < zt + 3 then return done(nil, 'too little rock over the top pump for the shaft\'s seals and gears') end
    local foot, fwhy = power_foot(pp, C, zt)
    if not foot then return done(nil, fwhy) end
    pp = setmetatable({old_ = old}, {__index = pp})
    local kinds = (src == 'wheel' or src == 'windmill') and {src} or {'wheel', 'windmill'}
    if not src and old and old.source == 'windmill' then kinds = {'windmill', 'wheel'} end
    local why
    for _, k in ipairs(kinds) do
        local p, w2, later
        if k == 'wheel' then p, w2, later = power_wheel(pp, C, zt, ztop, pumps, water_survey(), foot)
        else p, w2 = power_windmill(pp, C, zt, ztop, pumps, foot) end
        if p then return done(p) end
        -- (0.105.38 review) out of time: no windmill instead, tried again later
        if later then return done(nil, w2, true) end
        why = why and (why .. '; ' .. w2) or w2
    end
    return done(nil, why)
end

-- One step of the pump stack's power. opts: {dry_run, shut, retire, reopen, why, source}
function power_step(opts)
    opts = opts or {}
    local st = load_state()
    local id = 'power'
    local wk = st.works[id]
    local dry = opts.dry_run == true
    local function save() if not dry then st.works[id] = wk; save_state(st) end end
    local function wait(why) return {ok = false, rejected = true, waiting = true, stage = wk.stage, error = why} end
    local function advance(stage, extra)
        if not dry then wk.stage = stage; wk.since = now(); save() end
        local out = {ok = true, kind = 'power', stage = stage, dry_run = dry or nil}
        for k, v in pairs(extra or {}) do out[k] = v end
        return out
    end
    local function hold(why)
        if not dry then wk.stage = 'held'; wk.why = why; save() end
        return {ok = false, rejected = true, stage = 'held', error = why}
    end
    local function bld(b) return building(b.cx or b.x, b.cy or b.y, b.z, b.kind) end
    local function switch_of()
        local p = wk and wk.plan
        local b = p and p.switch and p.builds[p.switch]
        return b and bld(b) or nil
    end
    local function engaged(g)
        local e = g and gear_engaged(g.id)
        if e == nil then return wk.engaged ~= false end
        return e
    end
    -- the power off at once (a pull on its way called off); true: it was on
    local function stop_power()
        if dry or not wk or not wk.lever_id then return false end
        local g = switch_of()
        if not g or not g.built or not engaged(g) then return false end
        cancel_pulls(wk.lever_id)
        pull(wk.lever_id, true)
        wk.engaged = false
        return true
    end
    local function shaft_wet(p)
        for _, c in ipairs(p.pocket or {}) do
            local d = depth_at(c)
            if d > 0 then return c, d end
        end
        return nil
    end
    local function pump_shut(why)
        if dry then return end
        pcall(step, 'pump', {shut = true, why = why})
        st = load_state()        -- (the pump's step saved its own work)
    end

    if opts.shut or opts.retire then
        if not wk then return {ok = false, rejected = true, error = 'no power work to shut'} end
        if dry then return {ok = true, dry_run = true, stage = wk.stage} end
        stop_power()
        if opts.retire then
            wk.stage = 'retired'; wk.why = opts.why or 'retired'
            wk.shut, wk.shut_at = nil, nil
            st.retired_n = type(st.retired_n) == 'table' and st.retired_n or {}
            st.retired_n[id] = (math.tointeger(st.retired_n[id]) or 0) + 1
            st.refused[id] = {tick = now(), why = 'retired: ' .. wk.why, retired = st.retired_n[id]}
        else
            wk.shut = opts.why or 'shut'
            wk.shut_at = now()
        end
        save()
        return {ok = true, stage = wk.stage, shut = true}
    end

    if not wk or wk.stage == 'retired' then
        local n_ret = type(st.retired_n) == 'table' and math.tointeger(st.retired_n[id]) or 0
        if n_ret >= RETIRE_MAX then
            local why0 = ('retired %d times already: not begun again'):format(n_ret)
            if not dry then
                local old = type(st.refused[id]) == 'table' and st.refused[id] or {}
                st.refused[id] = {tick = now(), why = old.why or why0, retired = n_ret}
                save_state(st)
            end
            return {ok = false, rejected = true, retired = n_ret, error = why0}
        end
        local pw = st.works.pump
        local plan, why, later
        if type(pw) ~= 'table' or pw.stage ~= 'done' then
            why = 'the pump stack is not done yet (its floodgate built and its reservoir filled once): no power for it'
        elseif pw.shut then
            why = 'the pump stack\'s floodgate is shut: no power for it now'
        else
            -- (0.105.37 fix) planned again after a retire: its own old shaft and machines reused
            plan, why, later = plan_power(pw, opts.source, wk and wk.plan)
        end
        if not plan then
            if not dry then st.refused[id] = {tick = now(), why = why, later = later or nil}; save_state(st) end
            return {ok = false, rejected = true, error = why, later = later or nil}
        end
        if dry then return {ok = true, dry_run = true, stage = 'planned', plan = plan} end
        st.refused[id] = nil
        wk = {kind = 'power', plan = plan}
        return advance('planned', {source = plan.source, need = plan.need, have = plan.have})
    end
    local p = wk.plan
    if wk.stage == 'held' then return {ok = false, rejected = true, stage = 'held', error = wk.why} end
    if type(p) ~= 'table' or p.v ~= 2 then
        -- (0.105.37 fix) an older plan's shaft could open onto the fort: stopped and held (retired, planned afresh)
        if dry then return {ok = true, dry_run = true, stage = 'held'} end
        stop_power()
        return hold('planned before the shaft was sealed at both ends: the power stopped, the AI plans it again')
    end

    if wk.shut then
        local again = opts.reopen == true or (type(opts.why) == 'string' and opts.why:match('^reopen') ~= nil)
        if not again then return wait(('the power is off (%s): waiting to be switched on again'):format(wk.shut)) end
        if now() - (wk.shut_at or 0) < REOPEN_AFTER_DAYS * DAY then
            return wait(('the power was switched off (%s) under %d days ago: not on yet'):format(wk.shut, REOPEN_AFTER_DAYS))
        end
        if dry then return {ok = true, dry_run = true, stage = wk.stage, reopen = true} end
        wk.shut, wk.shut_at = nil, nil      -- (switched on by the running step when the reservoir is low)
        save()
        return {ok = true, stage = wk.stage, reopened = true}
    end

    -- water in the shaft or its stair: stopped, the stack's floodgate shut, held
    local wc, wd = shaft_wet(p)
    if wc and wk.stage ~= 'planned' then
        if dry then return {ok = true, dry_run = true, stage = 'held'} end
        stop_power()
        pump_shut('water in the power shaft')
        return hold(('water (%d/7) in the power shaft at x%d y%d, elevation %d: the power stopped and the pump '
                     .. 'stack\'s floodgate shut'):format(wd, wc.x, wc.y, ez(wc.z)))
    end

    if wk.stage == 'planned' then
        if dry then return {ok = true, dry_run = true, stage = 'digging'} end
        local ok, z = designate_all(undug(p.dig), 'dig')
        if not ok then return {ok = false, error = ('the game would not designate the shaft (elevation %d)'):format(ez(z))} end
        return advance('digging')
    end
    if wk.stage == 'digging' then
        local n = left_to_dig(p.dig)
        if n > 0 then return wait(('%d tile(s) of the shaft and its stair left to dig'):format(n)) end
        if not wk.dig2 and #undug(p.dig2) > 0 then
            if dry then return {ok = true, dry_run = true, stage = 'digging'} end
            if not designate_all(undug(p.dig2), 'dig') then return {ok = false, error = 'the game would not designate the shaft\'s channels'} end
            wk.dig2 = true
            save()
            return wait('the shaft\'s floors are being channelled')
        end
        if not dry then wk.dig2 = true end
        n = left_to_dig(p.dig2)
        if n > 0 then return wait(('%d of the shaft\'s floors left to channel'):format(n)) end
        -- (0.105.37 fix) the plug over the foot (dig3) waits for the foot's pump: cut in the building stage
        if dry then return {ok = true, dry_run = true, stage = 'building'} end
        if not building(p.lever.x, p.lever.y, p.lever.z, 'Trap') and not designate_all({{x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}}, 'build') then
            return {ok = false, error = 'the game would not place the power\'s lever'}
        end
        wk.placed = {}
        return advance('building')
    end
    if wk.stage == 'building' then
        -- placed a wave at a time: a piece over open space only once what bears it is built
        local placed = type(wk.placed) == 'table' and wk.placed or {}
        local left, put = {}, 0
        -- (0.105.37 fix) the rock plug over the foot cut once the foot's pump
        -- stands (the shaft then opens onto its output, nothing else)
        local foot = p.foot and p.builds[p.foot]
        local fb = foot and bld(foot)
        if not wk.dig3 and fb and fb.built and not dry then
            if not designate_all(undug(p.dig3), 'dig') then return {ok = false, error = 'the game would not designate the plug over the shaft\'s foot'} end
            wk.dig3 = true
        end
        local plug_cut = wk.dig3 and left_to_dig(p.dig3) == 0
        for i, b in ipairs(p.builds) do
            local have = bld(b)
            if not (have and have.built) then table.insert(left, b.kind) end
            local pk = tostring(i)
            local again = placed[pk] and not have and now() - (tonumber(placed[pk]) or 0) > 2 * DAY
            if not have and (not placed[pk] or again) then
                local under = b.after and p.builds[b.after]
                local bears = not under or (function() local u = bld(under) return u ~= nil and u.built end)()
                if b.plug and not plug_cut then bears = false end
                if bears and not dry then
                    local ok
                    if b.kind == 'Windmill' then ok = place_windmill(b.x, b.y, b.z)
                    else ok = designate({{x = b.x, y = b.y, text = b.text}}, b.z, 'build') end
                    if ok then placed[pk] = now(); put = put + 1 end
                end
            end
        end
        wk.placed = placed
        if #left > 0 then
            save()
            return wait(('being built: %d piece(s) (%s)'):format(#left, table.concat(left, ', ', 1, math.min(#left, 4))))
        end
        local l = building(p.lever.x, p.lever.y, p.lever.z, 'Trap')
        if not l then
            if not dry then designate_all({{x = p.lever.x, y = p.lever.y, z = p.lever.z, text = 'Tl'}}, 'build') end
            return wait('the power\'s lever is placed again')
        end
        if not l.built then return wait('being built: the power\'s lever') end
        -- the stair's hatch last (the dwarves came down it), then locked
        local h = building(p.hatch.x, p.hatch.y, p.hatch.z, 'Hatch')
        if not h then
            if dry then return {ok = true, dry_run = true, stage = 'building'} end
            designate_all({p.hatch}, 'build')
            save()
            return wait('the hatch over the shaft\'s stair is placed')
        end
        if not h.built then return wait('being built: the hatch over the shaft\'s stair') end
        if dry then return {ok = true, dry_run = true, stage = 'linking'} end
        lock_hatch(h.id)
        set_name(l.id, p.lever.name)
        local g = switch_of()
        local r = link(l.id, g.id)
        if not r.ok then return r end
        wk.lever_id, wk.gate_id = l.id, g.id
        return advance('linking')
    end
    if wk.stage == 'linking' then
        if not is_linked(wk.lever_id, wk.gate_id) then
            if link_pending(wk.lever_id) or dry then return wait('the lever is being linked to the power\'s gear') end
            wk.relinks = (wk.relinks or 0) + 1
            if wk.relinks > 3 then return hold('the lever\'s link to the power\'s gear was lost 3 times: the AI retires it') end
            local r = link(wk.lever_id, wk.gate_id)
            save()
            if not r.ok then return r end
            return wait('the link was lost: asked for again')
        end
        if dry then return {ok = true, dry_run = true, stage = 'running'} end
        wk.engaged = true
        return advance('running')
    end
    if wk.stage == 'running' then
        local pw = st.works.pump
        if type(pw) ~= 'table' or pw.stage == 'retired' or pw.stage == 'held' then
            if dry then return {ok = true, dry_run = true, stage = 'held'} end
            stop_power()
            return hold(('the pump stack is %s: its power stopped'):format(type(pw) == 'table' and pw.stage or 'gone'))
        end
        local g = switch_of()
        if not g then
            if dry then return {ok = true, dry_run = true, stage = 'held'} end
            return hold('the power\'s gear is gone: the AI retires it')
        end
        if pw.shut then
            if stop_power() then save() end
            return wait(('the pump stack\'s floodgate is shut (%s): its power off meanwhile'):format(pw.shut))
        end
        -- the source turning
        local turning, known = false, false
        for _, i in ipairs(p.sources or {}) do
            local b = bld(p.builds[i])
            local t
            if b then
                if p.source == 'wheel' then t = wheel_turning(b.id) else t = windmill_turning(b.id) end
            end
            if t ~= nil then known = true end
            if t then turning = true end
        end
        local function stack_manual(on)
            if dry then return end
            for _, b in ipairs(pw.plan and pw.plan.builds or {}) do
                if b.kind == 'ScrewPump' then
                    local bb = building(b.x, b.y, b.z, 'ScrewPump')
                    if bb and bb.built then set_pump_manual(bb.id, on) end
                end
            end
        end
        if known and not turning and p.source == 'wheel' then
            -- (0.105.37 fix) a still wheel (its river frozen or low) is paused, not
            -- retired: the power off, the stack's pumps worked by hand meanwhile, on
            -- again when it turns. Retired only after WHEEL_RETIRE_DAYS still over
            -- unfrozen water (a full thawed season); frozen days don't count.
            local frozen, low = false, false
            for _, i in ipairs(p.sources or {}) do
                local b = p.builds[i]
                local t = T(b.cx or b.x, b.cy or b.y, b.z - 1)
                if t and (t.material == 'FROZEN_LIQUID' or t.frozen) then frozen = true
                elseif not (t and t.liquid) or (t.depth or 0) < 4 then low = true end
            end
            if not dry then
                wk.still_from = wk.still_from or now()
                local last = tonumber(wk.still_seen) or now()
                if not frozen then wk.dry_thawed = (tonumber(wk.dry_thawed) or 0) + math.max(0, now() - last) end
                wk.still_seen = now()
            end
            if (tonumber(wk.dry_thawed) or 0) > WHEEL_RETIRE_DAYS * DAY then
                if dry then return {ok = true, dry_run = true, stage = 'held'} end
                stop_power()
                stack_manual(true)
                return hold(('the water wheel has stood still through %d days of unfrozen river (the river dry or '
                             .. 'still under it): the power stopped, the pumps worked by hand, the AI retires it')
                            :format(WHEEL_RETIRE_DAYS))
            end
            local why = frozen and 'its river frozen' or low and 'its river too low' or 'the river still under it'
            if not dry then
                if stop_power() then wk.pull_at = nil end
                stack_manual(true)
                wk.paused = why
                save()
            end
            return wait(('paused: the water wheel stands still (%s): the power off, the pumps worked by hand until it '
                         .. 'turns again'):format(why))
        elseif known and not turning then
            if not dry and not wk.still_from then wk.still_from = now() end
            if now() - (wk.still_from or now()) > WIND_DAYS * DAY then
                if dry then return {ok = true, dry_run = true, stage = 'held'} end
                stop_power()
                return hold(('the windmill has not turned in %d days (no wind on this map): the power stopped, '
                             .. 'the AI retires it'):format(WIND_DAYS))
            end
        elseif not dry then
            wk.still_from, wk.still_seen, wk.dry_thawed = nil, nil, nil
            if wk.paused then wk.paused, wk.resumed = nil, now() end    -- (turning again: the reservoir rule below)
        end
        -- the power check: the machine's power against what it needs
        local on = engaged(g)
        local mp = machine_power(g.id)
        if mp and not dry then wk.power, wk.power_need = mp.cur, mp.need end
        if on and mp and mp.cur < mp.need then
            if not dry and not wk.short_from then wk.short_from = now() end
            if now() - (wk.short_from or now()) > POWER_SHORT_DAYS * DAY then
                if dry then return {ok = true, dry_run = true, stage = 'held'} end
                stop_power()
                return hold(('the machine has %d power for the %d it needs, for %d days: the power stopped, the AI '
                             .. 'retires it'):format(mp.cur, mp.need, POWER_SHORT_DAYS))
            end
        elseif not dry then
            wk.short_from = nil
        end
        -- the reservoir kept between POWER_LOW and POWER_HIGH
        local d = depth_at(p.test or p.reservoir or {x = 0, y = 0, z = 0})
        if not dry then wk.depth = d end
        local did
        if on and d >= POWER_HIGH then
            if not dry then stop_power() end
            did, on = 'switched off', false
        elseif not on and d <= POWER_LOW and now() - (wk.pull_at or -math.huge) > POWER_PULL_DAYS * DAY then
            if not dry then
                pull(wk.lever_id, false)
                wk.pull_at = now()
                wk.engaged = true
            end
            did, on = 'switched on', true
        end
        -- (no dwarf needed at a powered pump)
        stack_manual(false)
        save()
        return wait(('running: the reservoir %d/7, the power %s%s%s'):format(d, on and 'on' or 'off',
            mp and (' (%d for %d needed)'):format(mp.cur, mp.need) or '', did and (': ' .. did) or ''))
    end
    return {ok = false, rejected = true, error = 'unknown stage ' .. tostring(wk.stage)}
end

-- (r8) the steps' helpers (the top of this file) handed on to ai-waterworks-steps
WATERWORKS_PART_LOCALS.dug, WATERWORKS_PART_LOCALS.designate_all, WATERWORKS_PART_LOCALS.undug, WATERWORKS_PART_LOCALS.left_to_dig, WATERWORKS_PART_LOCALS.leak, WATERWORKS_PART_LOCALS.depth_at = dug, designate_all, undug, left_to_dig, leak, depth_at
