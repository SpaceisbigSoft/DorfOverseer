-- ai-waterworks-plans: the works' plans (the moat, the pump stack, the muddied farm level, magma).
--
-- (r8) A part of ai-waterworks, not a script of its own: ai-waterworks.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-waterworks').name and the hooks and helpers defined there
-- (T, building, designate, load_state, ...) are in reach.

if not WATERWORKS_PART_LOCALS then qerror('ai-waterworks-plans is a part of ai-waterworks; run ai-waterworks') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-waterworks-plans'] = '0.105.99'   -- (0.105.26) bumped with BRIDGE_VERSION

-- (r8) the hub's and earlier parts' locals used here
local OPEN, key, rock, cavern_tile, ground, still_water, l_path, N4, wet_beside = WATERWORKS_PART_LOCALS.OPEN, WATERWORKS_PART_LOCALS.key, WATERWORKS_PART_LOCALS.rock, WATERWORKS_PART_LOCALS.cavern_tile, WATERWORKS_PART_LOCALS.ground, WATERWORKS_PART_LOCALS.still_water, WATERWORKS_PART_LOCALS.l_path, WATERWORKS_PART_LOCALS.N4, WATERWORKS_PART_LOCALS.wet_beside

---------------------------------------------------------------------------
-- Plans. Each: {kind, dig = {{x,y,z,text}}, dig2, gate = {x,y,z}, plug =
-- {x,y,z,text}, lever = {x,y,z,name}, builds = {{x,y,z,text,kind}},
-- finish = {...}, wet = tiles the liquid fills, tiles = every tile it may
-- reach, test = {mode, x,y,z | tiles}}
---------------------------------------------------------------------------

local function fort_box()
    local cs = citizens() or {}
    if #cs == 0 then return nil end
    local xs, ys, zs = 0, 0, {}
    local per = {}
    for _, c in ipairs(cs) do
        xs, ys = xs + c.x, ys + c.y
        table.insert(zs, c.z)
        per[c.z] = (per[c.z] or 0) + 1
    end
    table.sort(zs)
    local busy, bn = zs[1], 0
    for z, n in pairs(per) do if n > bn or (n == bn and z < busy) then busy, bn = z, n end end
    return {x = xs // #cs, y = ys // #cs, z_low = zs[1], z_high = zs[#zs], z_busy = busy}
end

-- A free floor inside the fort on level z near (x, y) for a lever.
function lever_spot(x, y, z, avoid)
    for r = 0, 20 do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local tx, ty = x + dx, y + dy
                    local t = T(tx, ty, z)
                    if t and t.shape == 'FLOOR' and not t.outside and not t.liquid and not t.building
                            and not t.designated and not (avoid and avoid[key(tx, ty, z)]) then
                        return {x = tx, y = ty, z = z}
                    end
                end
            end
        end
    end
    return nil
end

local function add_tiles(p, list)
    for _, c in ipairs(list) do table.insert(p.tiles, {x = c.x, y = c.y, z = c.z}) end
end

-- W3: a trench across the approach to a surface gate, fed from the river
-- through a floodgate, crossed by a drawbridge (a plain bridge: no lever).
-- (0.105.38) one river's moat: the river's nearest tile, its highest level,
-- the feed's length at most. (0.105.38 review) Only the near river (as
-- before 0.105.38): a far river never feeds a moat.
local function moat_for(river, river_z2, feed_max, opts, es)
    local why
    for _, e in ipairs(es) do
        -- the side the outside lies on
        local dir
        for _, d in ipairs(N4) do
            local t = T(e.x + d[1], e.y + d[2], e.z)
            if t and t.outside and OPEN[t.shape] and not t.liquid then dir = d break end
        end
        if not dir then why = why or 'the gate has no open ground outside it' goto next end
        do
            local z = e.z
            if river.z ~= z - 1 then
                why = why or ('the river\'s water is not one level under the ground at the gate (river at elevation %d, '
                              .. 'ground %d): a moat there would overflow or stay dry'):format(ez(river.z), ez(z))
                goto next
            end
            local px, py = -dir[2], dir[1]                  -- along the trench
            local cx, cy = e.x + dir[1] * (MOAT_GAP + 1), e.y + dir[2] * (MOAT_GAP + 1)
            local trench = {}
            for i = -MOAT_HALF, MOAT_HALF do
                local x, y = cx + px * i, cy + py * i
                if not ground(x, y, z) then why = why or ('the ground across the approach is not diggable at x%d y%d'):format(x, y) goto next end
                table.insert(trench, {x = x, y = y, z = z, i = i})
            end
            -- the trench end nearer the river, then the feed to the river's edge
            local a, b = trench[1], trench[#trench]
            local function dist(t) return math.max(math.abs(t.x - river.x), math.abs(t.y - river.y)) end
            local from = dist(a) <= dist(b) and a or b
            local start = {x = from.x + (from == a and -px or px), y = from.y + (from == a and -py or py)}
            -- (0.105.33) the feed stops at the tile beside the river (the plug);
            -- its corner never at the floodgate: the tile before the gate would
            -- touch the plug diagonally and the water go round the gate
            local feed, cornered
            for _, xfirst in ipairs({true, false}) do
                local f = l_path(start, river, function(x, y) return ground(x, y, z) end, xfirst)
                while f and #f > 0 do
                    local l = f[#f]
                    local nb = T(l.x, l.y, z)
                    if math.max(math.abs(l.x - river.x), math.abs(l.y - river.y)) <= 1 then break end
                    if nb and nb.liquid then table.remove(f) else break end
                end
                if f and #f >= 3 and math.max(math.abs(f[#f - 2].x - f[#f].x), math.abs(f[#f - 2].y - f[#f].y)) <= 1 then
                    cornered, f = true, nil
                end
                if f then feed = f break end
            end
            if not feed then
                why = why or (cornered and 'the feed channel would turn its corner at the floodgate (the water would go round it)'
                              or 'no diggable ground for a channel from the river to the trench')
                goto next
            end
            if #feed < 3 then why = why or 'the river is too close to the trench for a floodgate between' goto next end
            if #feed > feed_max then why = why or ('the river is %d tiles from the trench (%d at most)'):format(#feed, feed_max) goto next end
            local plug = feed[#feed]
            local gate = feed[#feed - 1]
            local cs = citizens() or {}
            local lever = lever_spot(e.x - dir[1] * 3, e.y - dir[2] * 3, z)
                or (cs[1] and lever_spot(cs[1].x, cs[1].y, cs[1].z))
            if not lever then why = why or 'no free floor inside for the moat\'s lever' goto next end
            lever.name = 'AI moat'
            local p = {kind = 'moat', entrance = e.id, dig = {}, dig2 = {}, builds = {}, tiles = {}, wet = {},
                       gate = {x = gate.x, y = gate.y, z = z - 1}, lever = lever,
                       plug = {x = plug.x, y = plug.y, z = z, text = 'h'}, river = river,
                       test = {mode = 'deep', x = cx, y = cy, z = z - 1, want = 3}}
            for _, t in ipairs(trench) do
                table.insert(p.dig, {x = t.x, y = t.y, z = z, text = 'h'})
                table.insert(p.wet, {x = t.x, y = t.y, z = z - 1})
            end
            for i = 1, #feed - 1 do
                table.insert(p.dig, {x = feed[i].x, y = feed[i].y, z = z, text = 'h'})
                table.insert(p.wet, {x = feed[i].x, y = feed[i].y, z = z - 1})
            end
            table.insert(p.wet, {x = plug.x, y = plug.y, z = z - 1})
            -- (0.105.33) river water can be under pressure (from the river's
            -- higher reaches): the dry run lets it climb to one level under the
            -- river's highest water the survey saw, up through the channels dug
            p.pressure = true
            p.pressure_top = math.max(tonumber(river_z2) or river.z, river.z) - 1
            p.channels = {}
            for _, c in ipairs(p.dig) do p.channels[key(c.x, c.y, c.z)] = true end
            p.channels[key(plug.x, plug.y, z)] = true
            -- the floodgate stands on a floor: the ramp a channel leaves under it removed
            table.insert(p.dig2, {x = gate.x, y = gate.y, z = z - 1, text = 'z'})
            add_tiles(p, p.wet)
            -- the crossing: three trench tiles on the gate's line
            local bx1, by1 = cx + px * -1, cy + py * -1
            local bw, bh = (px ~= 0) and 3 or 1, (py ~= 0) and 3 or 1
            local bdir = dir[2] == 1 and 'gx' or dir[2] == -1 and 'gw' or dir[1] == 1 and 'gd' or 'ga'
            local bx, by = math.min(bx1, cx + px), math.min(by1, cy + py)
            p.bridge = {x = bx, y = by, z = z, w = bw, h = bh, drawbridge = opts.plain ~= true}
            table.insert(p.builds, {x = bx, y = by, z = z, text = ('%s(%dx%d)'):format(bdir, bw, bh), kind = 'Bridge'})
            local by = bypass(p)             -- (0.105.33) the water never round the floodgate
            if by then why = why or by.why goto next end
            return p
        end
        ::next::
    end
    return nil, why or 'no gate fit for a moat'
end

function plan_moat(opts)
    opts = opts or {}
    local w = water_survey()
    if not w then return nil, 'no water survey yet' end
    local river, river_z2
    for _, b in ipairs(w.bodies or {}) do if b.kind == 'river' then river, river_z2 = b.nearest, b.z2 end end
    -- (0.105.38 review) the near river only, as before: a far river's long
    -- channel is no moat (the brain's moat_wanted asks for a near one too)
    if not river then return nil, 'no river or brook near the fort' end
    local es = entrances()
    if #es == 0 then return nil, 'no surface entrance found (scan the entrances first)' end
    return moat_for(river, river_z2, MOAT_FEED_MAX, opts, es)
end

-- W4: screw pumps lifting still water from a level below to a 3x3
-- reservoir under the fort's lowest level (a well goes over it later).
-- Worked by a dwarf (the pump operator labour).
local function pump_at(src, fb, w, far)
    local why_b
    local groups = far and citizen_groups() or nil     -- (0.105.38 review) a far stack: its top where the dwarves walk
    local zt = fb.z_low - 1                         -- the reservoir, under the lowest fort level
    local zs = src.z
    local lift = zt - zs
    if lift < 1 then return nil, 'the water is not below the reservoir level' end
    if lift > PUMP_MAX_LIFT then return nil, ('the water is %d levels under the fort (%d at most)'):format(lift, PUMP_MAX_LIFT) end
    local s = T(src.x, src.y, zs)
    if not still_water(s) then return nil, 'the water under the fort is not still and fresh' end
    for _, d in ipairs(N4) do
        -- water W, plug P, gate G, sump A, then B beside A and the stair C
        local P = {x = src.x + d[1], y = src.y + d[2]}
        local G = {x = P.x + d[1], y = P.y + d[2]}
        local A = {x = G.x + d[1], y = G.y + d[2]}
        local B = {x = A.x + d[1], y = A.y + d[2]}
        local C = {x = A.x - d[2], y = A.y + d[1]}           -- beside A, off the line
        local ok = rock(T(P.x, P.y, zs)) and rock(T(G.x, G.y, zs)) and rock(T(A.x, A.y, zs)) and rock(T(C.x, C.y, zs))
        for z = zs + 1, zt do
            for _, q in ipairs({A, B, C}) do if not rock(T(q.x, q.y, z)) then ok = false end end
        end
        -- the reservoir beyond B on the top level
        local R = {}
        local rx, ry = B.x + d[1] * 2, B.y + d[2] * 2
        for dx = -1, 1 do for dy = -1, 1 do
            local x, y = rx + dx, ry + dy
            if not rock(T(x, y, zt)) then ok = false end
            table.insert(R, {x = x, y = y, z = zt})
        end end
        local top = T(rx, ry, zt + 1)
        local ctop = T(C.x, C.y, zt + 1)
        if not (top and top.shape == 'FLOOR' and not top.outside and not top.building) then ok = false end
        if not (ctop and ctop.shape == 'FLOOR' and not ctop.outside and not ctop.building) then ok = false end
        if ok and far and not (groups[walk_group(rx, ry, zt + 1)] == true and groups[walk_group(C.x, C.y, zt + 1)] == true) then
            ok = false
            why_b = why_b or ('the far reservoir\'s site at x%d y%d is not where the dwarves can walk'):format(rx, ry)
        end
        if ok then
            local p = {kind = 'pump', dig = {}, builds = {}, tiles = {}, wet = {}, down = {},
                       gate = {x = G.x, y = G.y, z = zs}, plug = {x = P.x, y = P.y, z = zs, text = 'd'},
                       lift = lift, power = 'dwarf', source = {x = src.x, y = src.y, z = zs},
                       src = {x = src.x, y = src.y, z = zs},
                       reservoir = {x = rx, y = ry, z = zt},
                       test = {mode = 'rise', x = rx, y = ry, z = zt, want = 4}}
            table.insert(p.dig, {x = G.x, y = G.y, z = zs, text = 'd'})
            table.insert(p.dig, {x = A.x, y = A.y, z = zs, text = 'd'})
            table.insert(p.dig, {x = C.x, y = C.y, z = zs, text = 'u'})
            for _, q in ipairs({P, G, A, C}) do table.insert(p.wet, {x = q.x, y = q.y, z = zs}) end
            for z = zs + 1, zt do
                local k = z - zs
                local intake, out = (k % 2 == 1) and A or B, (k % 2 == 1) and B or A
                table.insert(p.dig, {x = intake.x, y = intake.y, z = z, text = 'h'})
                table.insert(p.dig, {x = out.x, y = out.y, z = z, text = 'd'})
                table.insert(p.dig, {x = C.x, y = C.y, z = z, text = 'i'})
                -- the pump: 1x2 over the intake, pumping from the intake's side
                -- (quickfort Ms + u/k/m/h = from north/east/south/west: a guess)
                local fx, fy = intake.x - out.x, intake.y - out.y
                local from = fy == -1 and 'u' or fx == 1 and 'k' or fy == 1 and 'm' or 'h'
                local w_, h_ = (fx ~= 0) and 2 or 1, (fy ~= 0) and 2 or 1
                table.insert(p.builds, {x = math.min(intake.x, out.x), y = math.min(intake.y, out.y), z = z,
                                        text = ('Ms%s(%dx%d)'):format(from, w_, h_), kind = 'ScrewPump'})
                for _, q in ipairs({A, B, C}) do table.insert(p.tiles, {x = q.x, y = q.y, z = z}) end
                p.down[key(intake.x, intake.y, z)] = true
            end
            for _, r in ipairs(R) do
                if not (r.x == rx and r.y == ry) then table.insert(p.dig, {x = r.x, y = r.y, z = zt, text = 'd'}) end
            end
            table.insert(p.dig, {x = rx, y = ry, z = zt, text = 'd'})
            table.insert(p.dig, {x = C.x, y = C.y, z = zt + 1, text = 'j'})
            -- the stair into the stack covered by a locked hatch on the fort
            -- floor: pumped water is under pressure and would climb it
            table.insert(p.builds, {x = C.x, y = C.y, z = zt + 1, text = 'H', kind = 'Hatch', lock = true})
            p.stops = {[key(C.x, C.y, zt + 1)] = true}
            p.pressure = true
            -- (the top pump's output joins the reservoir: B or A on zt to it)
            local link_tiles = l_path({x = ((lift % 2 == 1) and B or A).x, y = ((lift % 2 == 1) and B or A).y},
                                      {x = rx, y = ry}, function(x, y)
                                          return rock(T(x, y, zt)) or (x == A.x and y == A.y) or (x == B.x and y == B.y) end)
            for _, l in ipairs(link_tiles or {}) do
                if not ((l.x == A.x and l.y == A.y) or (l.x == B.x and l.y == B.y)) then
                    table.insert(p.dig, {x = l.x, y = l.y, z = zt, text = 'd'})
                    table.insert(p.tiles, {x = l.x, y = l.y, z = zt})
                end
            end
            add_tiles(p, R)
            add_tiles(p, p.wet)
            p.wet = p.tiles          -- pumped water may stand anywhere in the stack
            local lv = lever_spot(C.x, C.y, zt + 1, {[key(rx, ry, zt + 1)] = true, [key(C.x, C.y, zt + 1)] = true})
            if not lv then return nil, 'no free floor for the pump\'s lever' end
            lv.name = 'AI pump'
            p.lever = lv
            -- the pump's water wheel: only beside a river (said, not built yet)
            for _, b in ipairs(w.bodies or {}) do if b.kind == 'river' then p.wheel = 'possible on the river' end end
            local by = bypass(p)         -- (0.105.33) the water never round the floodgate
            if not by and far then
                -- (0.105.38 review) a far stack: its dig checked on the map
                -- (no aquifer or other water beside it), the job cap, staged
                local bad = far_route_check(p, false) or stage_plan(p)
                if bad then by = {why = bad} end
            end
            if not by then return p end
            why_b = why_b or by.why
        end
    end
    return nil, why_b or 'no solid rock beside the water for a sump, pumps and a reservoir'
end

function plan_pump(opts)
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local w = water_survey()
    if not w then return nil, 'no water survey yet' end
    local src
    for _, b in ipairs(w.bodies or {}) do
        if b.kind == 'pool' and b.nearest and b.nearest.z < fb.z_low then src = b.nearest end
    end
    -- (0.105.38) the whole map's other underground pools under the fort, the
    -- cheapest first (the stack stands beside its water, under a fort floor)
    local far = far_sources(w, function(b)
        return b.underground == true and b.nearest.z < fb.z_low and (tonumber(b.salt_share) or 0) == 0 end, src)
    if not src and #far == 0 then
        return nil, 'no still water under the fort outside the caverns (cavern water is not tunnelled to)'
    end
    local why
    if src then
        local p, w1 = pump_at(src, fb, w)
        if p then return p end
        why = w1
    end
    for _, b in ipairs(far) do
        local p, w2 = pump_at(b.nearest, fb, w, true)
        if p then p.far = {d = tonumber(b.d) or 0, kind = 'pool'} return p end
        why = why or w2
    end
    return nil, why
end

-- W5: a 5x5 room in stone under a fort level, muddied by a little water
-- let in through a floodgate, dried, then farm plots on the mud.
IRR_FAR_SECONDS = 0.25   -- (0.105.38 review) the far farm room's search this long at most (then: tried again later)
-- (r2h1) A river-fed cistern, built and holding water (ai-builder-cistern,
-- its plan `river`: filled through its diagonal step, so its water is still
-- and under no pressure), as the farm room's source: the room on the
-- cistern's level under the well's fort floor, its tunnel and floodgate cut
-- through the cistern's wall. nil, or {zf, z, edge = water tiles of the
-- room's edge (not the well's), cistern = {x1, y1, z}, own = {["x,y,z"]: the
-- cistern's water tiles: the room, its tunnel and shaft}, stops}.
function cistern_feed()
    local ok, d = pcall(function() return reqscript('ai-builder').cistern_data() end)
    if not ok or type(d) ~= 'table' or d.stage ~= 'done' or type(d.plan) ~= 'table' then return nil end
    local p = d.plan
    if not p.river or type(p.cistern) ~= 'table' or type(p.well) ~= 'table' then return nil end
    local c, z = p.cistern, p.cistern.z
    local zi = p.intake_z or z
    local out = {zf = p.well.z, z = z, edge = {}, cistern = {x1 = c.x1, y1 = c.y1, z = z}, own = {}}
    for x = c.x1, c.x2 do for y = c.y1, c.y2 do
        out.own[key(x, y, z)] = true
        if (x == c.x1 or x == c.x2 or y == c.y1 or y == c.y2) and not (x == p.well.x and y == p.well.y)
                and still_water(T(x, y, z)) then
            table.insert(out.edge, {x = x, y = y, d = 0})
        end
    end end
    for _, q in ipairs(p.tunnel_path or {}) do out.own[key(q.x, q.y, zi)] = true end
    if p.plug then out.own[key(p.plug.x, p.plug.y, zi)] = true end
    if type(p.shaft) == 'table' then
        for zz = z, zi do out.own[key(p.shaft.x, p.shaft.y, zz)] = true end
    end
    if #out.edge == 0 then return nil end
    return out
end

-- (r2h1) a cistern-fed plan's dug tiles kept off the cistern: none of them
-- (but the plug, through the room's wall) beside any of the cistern's water
-- tiles (its room, tunnel, shaft), so the cistern stays closed all round
local function off_cistern(p, cf)
    for _, list in ipairs({p.dig or {}, p.wet or {}}) do
        for _, q in ipairs(list) do
            if not (q.x == p.plug.x and q.y == p.plug.y and q.z == p.plug.z) then
                for dx = -1, 1 do for dy = -1, 1 do
                    if cf.own[key(q.x + dx, q.y + dy, q.z)] then
                        return ('the dug tile at x%d y%d would open the cistern\'s wall'):format(q.x, q.y)
                    end
                end end
            end
        end
    end
    return nil
end

function plan_irrigation()
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local why
    local far_deadline, far_out
    local tries = {}
    for zf = fb.z_high, math.max(fb.z_low, fb.z_high - 3), -1 do table.insert(tries, {zf = zf}) end
    -- (r2h1) the river-fed cistern last: the fort's own still water first
    local okc, cf = pcall(cistern_feed)
    if okc and cf then table.insert(tries, {zf = cf.zf, cf = cf}) end
    for _, try in ipairs(tries) do
        local zf, cf = try.zf, try.cf
        local z = zf - 1
        -- still water on the room's level near the fort (the nearest 12 tiles)
        local waters = {}
        if cf then waters = cf.edge end
        for dx = -30, 30 do for dy = -30, 30 do
            if cf then break end
            local t = T(fb.x + dx, fb.y + dy, z)
            if still_water(t) then table.insert(waters, {x = fb.x + dx, y = fb.y + dy, d = math.max(math.abs(dx), math.abs(dy))}) end
        end end
        table.sort(waters, function(a, b) return a.d < b.d end)
        while #waters > 12 do table.remove(waters) end
        -- (0.105.38) none near on this level: the survey's still water
        -- further off, the cheapest first, reached by a long tunnel (staged)
        if #waters == 0 and not far_out and not cf then
            local w = water_survey()
            for _, b in ipairs(far_sources(w, function(b)
                    return b.flow == 'stagnant' and b.nearest.z == z and (tonumber(b.salt_share) or 0) == 0 end)) do
                local n = b.nearest
                if still_water(T(n.x, n.y, z)) then
                    local dd = math.max(math.abs(n.x - fb.x), math.abs(n.y - fb.y))
                    table.insert(waters, {x = n.x, y = n.y, d = dd, far = math.min(far_cap(w), dd + 2 * IRR_REACH)})
                end
            end
        end
        for _, wt in ipairs(waters) do
            for _, d in ipairs(N4) do
                if wt.far and far_out then break end
                for gap = 3, wt.far or IRR_REACH do
                    -- (0.105.38 review) a far source's long line within IRR_FAR_SECONDS in all
                    -- (third review) out of time: no more far sources this call,
                    -- the near water of the other levels still tried
                    if wt.far then
                        far_deadline = far_deadline or (os.clock() + IRR_FAR_SECONDS)
                        if os.clock() > far_deadline then far_out = true end
                    end
                    if wt.far and far_out then break end
                    local cx, cy = wt.x + d[1] * (gap + 2), wt.y + d[2] * (gap + 2)
                    local above = T(cx - 2, cy - 2, zf)
                    local ok = true
                    -- (0.105.38) the fort floor over it first (a far source's long line is cheap to try)
                    if wt.far and not (above and above.shape == 'FLOOR' and not above.outside) then ok = false end
                    for x = cx - 2, cx + 2 do for y = cy - 2, cy + 2 do
                        if ok and not rock(T(x, y, z)) then ok = false end
                    end end
                    if ok and above and above.shape == 'FLOOR' and not above.outside and not above.building then
                        -- the tunnel from the room's side to the water
                        local edge = {x = cx - d[1] * 3, y = cy - d[2] * 3}
                        local path = l_path(edge, wt, function(x, y) return rock(T(x, y, z)) end)
                        if path and #path >= 2 then
                            local p = {kind = 'irrigation', dig = {}, builds = {}, tiles = {}, wet = {},
                                       gate = {x = path[1].x, y = path[1].y, z = z},
                                       plug = {x = path[#path].x, y = path[#path].y, z = z, text = 'd'},
                                       room = {x1 = cx - 2, y1 = cy - 2, x2 = cx + 2, y2 = cy + 2, z = z},
                                       src = {x = wt.x, y = wt.y, z = z},
                                       test = {mode = 'wet', z = z}}
                            if cf then
                                -- (r2h1) fed from the river's cistern: its tiles stop the dry
                                -- run's walk (they are the source), and it names the cistern
                                p.cistern_fed, p.stops = cf.cistern, {}
                                for k in pairs(cf.own) do p.stops[k] = true end
                                p.fed_from = 'the river-fed cistern'
                            end
                            for x = cx - 2, cx + 2 do for y = cy - 2, cy + 2 do
                                local stair = x == cx - 2 and y == cy - 2
                                table.insert(p.dig, {x = x, y = y, z = z, text = stair and 'u' or 'd'})
                                table.insert(p.wet, {x = x, y = y, z = z})
                            end end
                            table.insert(p.dig, {x = cx - 2, y = cy - 2, z = zf, text = 'j'})
                            p.upstream = {}     -- (0.105.33) the tunnel between the gate and the plug
                            for i = 1, #path - 1 do
                                table.insert(p.dig, {x = path[i].x, y = path[i].y, z = z, text = 'd'})
                                table.insert(p.wet, {x = path[i].x, y = path[i].y, z = z})
                                if i >= 2 then table.insert(p.upstream, {x = path[i].x, y = path[i].y, z = z}) end
                            end
                            table.insert(p.wet, {x = p.plug.x, y = p.plug.y, z = z})
                            add_tiles(p, p.wet)
                            local lv = lever_spot(cx, cy, zf, {[key(cx - 2, cy - 2, zf)] = true})
                            if not lv then why = why or 'no free floor for the lever' goto skip end
                            lv.name = 'AI irrigation'
                            p.lever = lv
                            if cf then
                                local off = off_cistern(p, cf)
                                if off then why = why or off goto skip end
                            end
                            local by = bypass(p)     -- (0.105.33) the water never round the floodgate
                            if not by and wt.far then
                                p.far = {d = #path, kind = 'tunnel'}
                                -- (0.105.38 review) the long tunnel checked on the map: no
                                -- aquifer or other water beside or over a dug tile
                                local big = far_route_check(p, false) or stage_plan(p)
                                if big then why = why or big goto skip end
                            end
                            if not by then return p end
                            why = why or by.why
                        end
                    end
                    ::skip::
                end
            end
        end
    end
    if far_out then
        return nil, (why and (why .. '; ') or '') .. 'the search for a far farm room ran out of time: tried again later', true
    end
    return nil, why or 'no still, fresh water beside solid rock under a fort level within reach'
end

-- Magma: a 5x5 room on the level over the magma, a stair down to it from the
-- fort, a pit under the workshop's middle, a tunnel from the pit to the
-- magma with a (magma-safe) floodgate; the service stair to the tunnel's
-- level covered by a locked hatch. Never through a cavern.
-- (0.105.38) A tunnel on the fort's lowest level from (x, y) toward the
-- fort's middle, through solid rock until it meets the fort: its tiles (the
-- first one excluded), or nil, why. (0.105.38 review) The fort met only at
-- an open floor that is no cavern's, seen, and in a citizen's walk group
-- (any other open tile refuses it); a cavern's tile refuses it unless
-- `allow_cavern` (the cavern switch; then a cavern's wall is dug and its
-- open floor crossed); a tile to dig with an aquifer or liquid beside or
-- over it refuses it.
local function fort_tunnel(x, y, fb, allow_cavern)
    local z = fb.z_low
    local groups = citizen_groups()
    local why
    for _, xfirst in ipairs({true, false}) do
        local out, cx, cy, ok, met = {}, x, y, true, false
        local function walk(tx, ty)
            while ok and not met and (cx ~= tx or cy ~= ty) do
                if cx ~= tx and (xfirst or cy == ty) then cx = cx + (tx > cx and 1 or -1) else cy = cy + (ty > cy and 1 or -1) end
                local t = T(cx, cy, z)
                local open = t and OPEN[t.shape] and t.shape ~= 'EMPTY' and not t.outside and not t.liquid
                if open and not t.feature and not t.hidden and groups[walk_group(cx, cy, z)] == true then met = true
                elseif cavern_tile(t) then
                    if not allow_cavern then
                        ok = false
                        why = why or ('the tunnel to the fort would open a cavern at x%d y%d (the cavern switch does not allow it)')
                            :format(cx, cy)
                    elseif rock(t, true) or (t.shape == 'WALL' and not t.liquid and not t.aquifer and not t.outside) then
                        local wb = wet_beside(cx, cy, z)
                        if wb then ok = false; why = why or ('the tunnel to the fort: ' .. wb)
                        else table.insert(out, {x = cx, y = cy, z = z}) end
                    elseif not open then
                        ok = false
                        why = why or ('the tunnel to the fort would cross a cavern\'s water or open space at x%d y%d'):format(cx, cy)
                    end
                elseif not rock(t, true) then
                    ok = false
                    why = why or ('the tunnel to the fort would cross something other than solid rock at x%d y%d'):format(cx, cy)
                else
                    local wb = wet_beside(cx, cy, z)
                    if wb then
                        ok = false
                        why = why or ('the tunnel to the fort: ' .. wb)
                    else table.insert(out, {x = cx, y = cy, z = z}) end
                end
            end
        end
        if xfirst then walk(fb.x, y); walk(fb.x, fb.y) else walk(x, fb.y); walk(fb.x, fb.y) end
        if ok and met then return out end
        why = why or 'the tunnel to the fort met no fort floor the dwarves walk on'
    end
    return nil, why
end

local function magma_at(m, shop, fb, allow_cavern)
    local why_b
    local zm, zw = m.z, m.z + 1
    if fb.z_low - zw > MAGMA_STAIR_MAX then return nil, 'the magma is too deep for a stair' end
    if zw >= fb.z_low then return nil, 'the magma is not below the fort' end
    for _, d in ipairs(N4) do
        for gap = 3, MAGMA_REACH do
            local P = {x = m.x + d[1] * gap, y = m.y + d[2] * gap}
            local path = l_path(P, m, function(x, y) return rock(T(x, y, zm), true) end)
            local ok = path ~= nil and #path >= 3
            -- the room on zw around P, all rock
            for x = P.x - 2, P.x + 2 do for y = P.y - 2, P.y + 2 do
                if not rock(T(x, y, zw), true) then ok = false end
            end end
            local S1 = {x = P.x - 2, y = P.y - 2}            -- the stair up to the fort
            local S2 = {x = P.x + 2, y = P.y + 2}            -- the service stair to the tunnel
            local S2t = T(S2.x, S2.y, zm)
            if ok and not rock(S2t, true) then ok = false end
            -- the service stair's foot must touch the tunnel on the pit's side
            -- of the floodgate (0.105.33: it joined the gate's own tile, and the
            -- tile beside the gate touched the tunnel on the magma's side too)
            local touches = path ~= nil and math.abs(path[1].x - S2.x) <= 1 and math.abs(path[1].y - S2.y) <= 1
            local why_s
            if ok then
                for z = zw + 1, fb.z_low do
                    local t = T(S1.x, S1.y, z)
                    if not t then ok = false break end
                    if t.feature then why_s = 'the way down crosses a cavern' ok = false break end
                    if z < fb.z_low and not rock(t, true) then ok = false break end
                end
            end
            if why_s then return nil, why_s end
            if ok then
                local p = {kind = 'magma', shop = shop, dig = {}, builds = {}, finish = {}, tiles = {}, wet = {}, down = {},
                           gate = {x = path[2].x, y = path[2].y, z = zm},
                           plug = {x = path[#path].x, y = path[#path].y, z = zm, text = 'd'},
                           pit = {x = P.x, y = P.y, z = zm}, room = {x = P.x, y = P.y, z = zw},
                           src = {x = m.x, y = m.y, z = zm, magma = true},
                           test = {mode = 'deep', x = P.x, y = P.y, z = zm, want = 4}}
                for x = P.x - 2, P.x + 2 do for y = P.y - 2, P.y + 2 do
                    local text = (x == S1.x and y == S1.y) and 'u' or (x == S2.x and y == S2.y) and 'j'
                        or (x == P.x and y == P.y) and 'h' or 'd'
                    table.insert(p.dig, {x = x, y = y, z = zw, text = text})
                end end
                for z = zw + 1, fb.z_low do
                    table.insert(p.dig, {x = S1.x, y = S1.y, z = z, text = z == fb.z_low and 'j' or 'i'})
                end
                -- (0.105.38) a stair far from the fort: a tunnel joins its top to the fort
                if math.max(math.abs(S1.x - fb.x), math.abs(S1.y - fb.y)) > MAGMA_NEAR then
                    local tun, twhy = fort_tunnel(S1.x, S1.y, fb, allow_cavern)
                    if not tun then return nil, twhy end
                    for _, c in ipairs(tun) do table.insert(p.dig, {x = c.x, y = c.y, z = c.z, text = 'd'}) end
                    p.access = #tun
                end
                table.insert(p.dig, {x = S2.x, y = S2.y, z = zm, text = 'u'})
                if not touches then
                    local con = l_path({x = S2.x, y = S2.y}, path[1], function(x, y) return rock(T(x, y, zm), true) or (x == S2.x and y == S2.y) end)
                    for i = 2, #(con or {}) do
                        table.insert(p.dig, {x = con[i].x, y = con[i].y, z = zm, text = 'd'})
                        table.insert(p.wet, {x = con[i].x, y = con[i].y, z = zm})
                    end
                end
                p.upstream = {}                 -- (0.105.33) the tunnel between the gate and the plug
                for i = 1, #path - 1 do
                    table.insert(p.dig, {x = path[i].x, y = path[i].y, z = zm, text = 'd'})
                    table.insert(p.wet, {x = path[i].x, y = path[i].y, z = zm})
                    if i >= 3 then table.insert(p.upstream, {x = path[i].x, y = path[i].y, z = zm}) end
                end
                table.insert(p.wet, {x = S2.x, y = S2.y, z = zm})
                table.insert(p.wet, {x = p.plug.x, y = p.plug.y, z = zm})
                add_tiles(p, p.wet)
                -- the room's floor over the magma's level is not in its way
                p.builds = {{x = S2.x, y = S2.y, z = zw, text = 'H', kind = 'Hatch', lock = true}}
                p.finish = {{x = P.x, y = P.y, z = zw, text = MAGMA_SHOPS[shop], kind = shop == 'MagmaForge' and 'Workshop' or 'Furnace'}}
                local lv = lever_spot(P.x, P.y, zw, {[key(S1.x, S1.y, zw)] = true, [key(S2.x, S2.y, zw)] = true,
                                                     [key(P.x, P.y, zw)] = true})
                -- (the room is still rock when planned: the lever goes in its corner)
                lv = lv or {x = P.x + 2, y = P.y - 2, z = zw}
                lv.name = 'AI magma'
                p.lever = lv
                local by = bypass(p)             -- (0.105.33) the magma never round the floodgate
                if not by then return p end
                why_b = why_b or by.why
            end
        end
    end
    return nil, why_b or 'no solid rock between the magma and a workshop site within reach'
end

-- (0.105.38) the magma's kinds in the order a workshop takes them (cost
-- comes after): a pipe or anything else outside the deep layers, the sea last
MAGMA_RANK = {pipe = 0, volcano = 0, pool = 0, surface = 1, cavern = 2, sea = 3}

-- The magma workshop's magma: the near box's highest magma first (as
-- before 0.105.38), then the whole map's magma bodies by kind and cost (a
-- pipe before the sea); one whose dig opens a cavern only when the cavern
-- switch allows it (opts.open_caverns: the brain's Rules choice, Never /
-- Always / AI decides), never by this rule alone. (0.105.38 review) The
-- survey's estimate (a shaft from the fort's middle) only sorts them: a
-- body it found blocked (other liquid, a deep feature, off the map) is left
-- out, one deeper than MAGMA_STAIR_MAX too; the planned dig itself is
-- walked for a cavern, an aquifer or other liquid beside it
-- (far_route_check), and the plan's `source.opens_cavern` says what it found.
function plan_magma(shop, opts)
    shop = MAGMA_SHOPS[shop] and shop or 'MagmaForge'
    opts = type(opts) == 'table' and opts or {}
    local allow = opts.open_caverns == true
    local fb = fort_box()
    if not fb then return nil, 'no citizens' end
    local w = water_survey()
    local m = w and w.magma and w.magma.top_nearest
    local cands, why, held = {}, nil, nil
    if m then table.insert(cands, {m = m}) end
    for _, b in ipairs(far_sources(w, function(b) return b.kind == 'magma' end, nil, function(b)
            return 10000 * (MAGMA_RANK[b.magma] or 2) end, 8)) do
        local t = b.top or b.nearest
        if b.blocked then
            why = why or ('the %s magma: %s'):format(tostring(b.magma), tostring(b.blocked))
        elseif fb.z_low - (t.z + 1) > MAGMA_STAIR_MAX then
            held = held or ('the %s magma is too deep for a stair (%d levels, %d at most)')
                :format(tostring(b.magma), fb.z_low - (t.z + 1), MAGMA_STAIR_MAX)
        elseif b.magma == 'cavern' and not allow then
            -- a pool in a cavern: reaching it opens the cavern, whatever the way
            held = held or ('the %s magma %d tiles off: reaching it opens %s (the cavern switch does not allow it)')
                :format(tostring(b.magma), tonumber(b.d) or 0, tostring(b.opens_cavern or b.cavern or 'a cavern'))
        elseif not (m and t.x == m.x and t.y == m.y and t.z == m.z) then
            table.insert(cands, {m = {x = t.x, y = t.y, z = t.z}, b = b})
        end
    end
    if #cands == 0 then
        return nil, why or held or 'no magma found near the fort (or the survey is older than 0.105.0)'
    end
    for _, c in ipairs(cands) do
        local p, w1 = magma_at(c.m, shop, fb, c.b and allow)
        if p and c.b then
            local deep = c.b.magma == 'sea' or c.b.magma == 'underworld'
            local zw = c.m.z + 1
            if deep then p.deep_z = zw end      -- (review) the sea's own layer: next_segment_bad's too
            local bad = far_route_check(p, allow)
            if not bad then
                -- a cavern on the planned dig (allowed by the switch), or the body's own
                local crossed
                for _, d in ipairs(p.dig) do
                    local t = T(d.x, d.y, d.z)
                    if cavern_tile(t) and not (deep and d.z <= zw) then crossed = true break end
                end
                p.source = {magma = c.b.magma, d = c.b.d,
                            opens_cavern = (crossed or c.b.magma == 'cavern') and (c.b.opens_cavern or c.b.cavern or 'a cavern') or nil}
                bad = stage_plan(p)
            end
            if bad then p, w1 = nil, bad end
        end
        if p then return p end
        why = why or (c.b and (('the %s magma: '):format(tostring(c.b.magma)) .. tostring(w1)) or w1)
    end
    return nil, why or held
end

PLANNERS = {moat = plan_moat, pump = plan_pump, irrigation = plan_irrigation, magma = plan_magma}
