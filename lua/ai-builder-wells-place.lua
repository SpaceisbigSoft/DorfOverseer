-- ai-builder-wells-place: a cavern well taken up again or undone, the shaft dug from the
-- bottom up, the winter cistern (a filled well), place_well, a well's dig checked and renewed.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.
-- (r8) Cut from ai-builder-wells.lua, which had grown to 133 KB; loaded right
-- after it and its parts before this one, in the old file's order.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-wells-place'] = '0.105.79'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

-- (0.105.24) A cavern well given up over a dug shaft (the game wouldn't place
-- the well: C's #110, F's #114, 3 Nov) taken up again, once: its shaft still
-- open all the way down, nothing built on its top, a floor beside the top
-- (or a landing to dig, as place_well digs one). The project goes back to
-- digging (the landing), then to furnish as before. nil when there is none
-- (or none that can be taken up: then `why` is kept for the next look).
OPEN_SHAPE = function(t) return t ~= nil and t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP' end

function revive_cavern_well(data, pri, dry_run)
    for _, p in ipairs(data.list) do
        if p.kind == 'well' and p.phase == 'cancelled' and type(p.shaft) == 'table' and #p.shaft > 0
                and type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] and not p.revived and not p.unreached
                and not p.held then
            local a = anchor_of(p)
            local top = tile_info(a.x, a.y, p.z)
            local open = top ~= nil and (top.shape == 'EMPTY' or top.shape == 'RAMP_TOP') and not top.building
            for _, zk in ipairs(p.shaft) do
                if not OPEN_SHAPE(tile_info(a.x, a.y, zk)) then open = false end
            end
            if open then
                local st = p.shaft_stairs[1]
                local floors = {}
                for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do floors[g.x .. ',' .. g.y] = true end
                local landing, lwhy
                if not well_floor_beside(a.x, a.y, p.z, floors, st) then
                    landing, lwhy = well_landing(a.x, a.y, p.z, st, floors)
                    if not landing then
                        p.revive_why = lwhy
                        if not dry_run then save_projects(data) end
                        return nil
                    end
                end
                local out = {ok = true, project_id = p.id, revived = true, cavern = true, x = a.x, y = a.y,
                             elevation = ez(p.z), landing = landing and {x = landing.x, y = landing.y} or nil,
                             dry_run = dry_run or nil}
                if dry_run then return out end
                if landing then
                    local s = quickfort_apply('dig', {{x = 0, y = 0, text = 'd' .. (pri or '')}}, p.z, landing.x, landing.y)
                    if stat(s, 'dig_designated') ~= 1 then
                        return {ok = false, error = ('the game would not dig a floor beside the old well shaft at x%d y%d elevation %d')
                            :format(landing.x, landing.y, ez(p.z))}
                    end
                    p.gallery = type(p.gallery) == 'table' and p.gallery or {}
                    table.insert(p.gallery, {x = landing.x, y = landing.y})
                    p.landing = {x = landing.x, y = landing.y}
                end
                p.phase, p.revived = 'dig', true
                p.well_refusals, p.well_retry_at = nil, nil
                if not save_projects(data) then return {ok = false, error = 'could not save the project with the fort'} end
                return out
            end
        end
    end
    return nil
end

-- (0.105.33 L5) A cavern well's other designations taken back: the shaft's
-- levels, the stair column beside it and the gallery (the top channel is
-- cells.dig, undone by the caller). Tiles already dug stay dug.
function undo_well_cells(p)
    local a = anchor_of(p)
    local pri = type(p.params) == 'table' and p.params.pri or ''
    for _, zk in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'h' .. pri}}, zk, a.x, a.y, 'undo')
    end
    for _, c in ipairs(type(p.shaft_stairs) == 'table' and p.shaft_stairs or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'undo')
    end
    for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. pri}}, p.z, g.x, g.y, 'undo')
    end
    for _, c in ipairs(type(p.chamber) == 'table' and p.chamber or {}) do     -- (r2 h2)
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. pri}}, c.z, c.x, c.y, 'undo')
    end
end

-- --- (0.105.47) cavern wells made safe (lua/ai-well-safety.lua) ------------------
--
-- I7d (14 Nov): the AI's cavern wells killed 11 dwarves in the run (falls
-- down a fresh shaft, drownings in the lake under it, the stranded later
-- killed by a beast). The checks live in ai-well-safety; these are the
-- shaft's own steps and the hook to them.
WELL_DIG_UP = true      -- a new cavern shaft dug from the bottom up (false: from the top, as before)

-- f(...) of ai-well-safety, its first result; nil when it fails or is missing
-- (a guard that can't be read lets the old behaviour stand, said in its report)
function well_safety_call(name, ...)
    local args = table.pack(...)
    local ok, r = pcall(function()
        local WS = reqscript('ai-well-safety')
        return WS[name](table.unpack(args, 1, args.n))
    end)
    if ok then return r end
    return nil
end

-- (0.105.47) Does tile (x, y, z) of a bottom-up shaft wait undesignated (a
-- level over the one being dug, or the top channel)? p.up = {zs = {z...}}:
-- the levels still to designate, lowest first.
function well_up_waits(p, x, y, z)
    local up = type(p) == 'table' and p.up or nil
    if type(up) ~= 'table' or type(up.zs) ~= 'table' then return false end
    local a = anchor_of(p)
    if not a or x ~= a.x or y ~= a.y then return false end
    for _, zz in ipairs(up.zs) do if zz == z then return true end end
    return false
end

-- (0.105.47) The next level of a bottom-up shaft designated: the lowest one
-- left, once the level under it is open (dug) and the break into the cavern
-- was let go (p.held gone), and nobody stands in the shaft's column
-- (`busy`: who, or nil). Returns the stage ('designated', 'held', 'below',
-- 'busy', 'next' (dry run), 'refused', 'done') and the level. The caller saves.
function well_up_advance(p, dry_run, busy)
    local up = type(p) == 'table' and p.up or nil
    if type(up) ~= 'table' or type(up.zs) ~= 'table' then return nil end
    if #up.zs == 0 then return 'done' end
    if type(p.held) == 'table' then return 'held' end
    local a = anchor_of(p)
    local z = up.zs[1]
    if up.top_first and z == p.z then
        -- (K48-K4) the top over a rock level (the one under it last): all under that open
        if not OPEN_SHAPE(tile_info(a.x, a.y, z - 2)) then return 'below', z end
    elseif up.top_first and z == p.z - 1 then
        -- the ramp the top's channel left: only once the top is dug, and all under it open
        if not OPEN_SHAPE(tile_info(a.x, a.y, z - 1)) or not OPEN_SHAPE(tile_info(a.x, a.y, p.z)) then
            return 'below', z
        end
    elseif not OPEN_SHAPE(tile_info(a.x, a.y, z - 1)) then
        return 'below', z
    end
    if busy then return 'busy', z end
    if dry_run then return 'next', z end
    local pri = type(p.params) == 'table' and p.params.pri or ''
    local ok, st = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'h' .. (pri or '')}}, z, a.x, a.y)
    if not ok or stat(st, 'dig_designated') ~= 1 then
        up.refused = (tonumber(up.refused) or 0) + 1
        return 'refused', z
    end
    table.remove(up.zs, 1)
    up.refused = nil
    return 'designated', z
end

-- Start a well: channel the spot now; the well itself is placed when the
-- hole is dug (furnish), like any other project.
-- --- (r2 h2) the winter cistern: a well filled by bucket ---------------------
--
-- B (R-B 1): the only water was a stagnant brook and pond on the surface that
-- froze every winter; no drop to water inside the fort, no cavern found (and
-- none to open without soldiers), no cistern site (no tunnel through solid
-- rock). Every bedridden dwarf of every winter died of thirst: a patient is
-- given only water, carried in a bucket from a well or a water source.
-- So: a small chamber dug in solid rock one level under a floor inside the
-- fort (under a roof, away from the sky, where water does not freeze), a well
-- over it, and a pond zone on the well's tile. The DF wiki (Well guide): "If
-- you designate your well as a pit/pond and have empty buckets, dwarves will
-- fill the well manually"; each bucket raises the water in the tile below by
-- 1/7 and the dwarves stop filling at 6/7, so the water never comes up out of
-- the chamber; a well needs 3/7. The dwarves fill it from the brook (its shore
-- well) while that is liquid; in winter the chamber's water is still there.
-- Sealed: every tile round the chamber, and under it, is solid natural rock
-- (no aquifer, no water, nothing dug or designated), the only way in the
-- well's own column; at most 6/7 of FILLED_WELL_SIDE^2 tiles of water, a
-- shallow puddle even if a later dig breached it. No floodgate, no lever, no
-- tunnel, nothing opened toward a cavern.
FILLED_WELL_HALF = 1                   -- the chamber's half side: 3x3 tiles (9 tiles, 54/7 of water at the most)
FILLED_WELL_HALF_MAX = 2               -- at most 5x5 (the brain's h2_winter_cistern_half)
FILLED_WELL_ZONE = 'AI winter cistern' -- the pond zone's name on the well's tile
FILLED_WELL_SECONDS = 2                -- the search's time

local function filled_rock(t)
    return solid_rock(t) and not t.designated and not t.outside and t.subterranean ~= false
end

-- Why (x, y, z) can't carry a winter cistern of half side h (nil: it can).
-- z: the well's floor; the chamber on z - 1.
function filled_well_why(x, y, z, h, reserved)
    for dy = -h - 1, h + 1 do
        for dx = -h - 1, h + 1 do
            local cx, cy = x + dx, y + dy
            local inner = math.abs(dx) <= h and math.abs(dy) <= h
            if inside_any(reserved, cx, cy, z - 1) or inside_any(reserved, cx, cy, z - 2) then
                return 'another project is dug there'
            end
            local t = tile_info(cx, cy, z - 1)
            if not filled_rock(t) then
                if t and (t.aquifer or t.liquid) then return 'water or an aquifer beside the chamber' end
                return inner and 'no solid rock for the chamber' or 'the chamber would not be closed all round'
            end
            if inner then
                if not filled_rock(tile_info(cx, cy, z - 2)) then return 'no solid rock under the chamber' end
                if dx ~= 0 or dy ~= 0 then
                    -- its roof: the floor (or rock) of the level above, never open
                    local r = tile_info(cx, cy, z)
                    if not r or r.outside or r.liquid or r.designated
                            or not (r.shape == 'FLOOR' or r.shape == 'WALL') then
                        return 'the chamber\'s roof is not whole'
                    end
                end
            end
        end
    end
    return nil
end

-- The best spot for a winter cistern: {x, y, z, half, zone}, or nil, why,
-- cut (the search ran out of time). A free natural floor inside the fort, on
-- a level the dwarves are on, with solid rock under it (see above), a floor
-- beside it for the well's builder; in a dining or meeting hall first, then
-- near the middle of the fort.
function find_filled_well_spot(reserved, half)
    local h = math.max(1, math.min(FILLED_WELL_HALF_MAX, math.floor(tonumber(half) or FILLED_WELL_HALF)))
    local area = fort_scan_area(WELL_SCAN_MARGIN)
    if not area then return nil, 'no citizens' end
    local best, best_score, cut
    local why_not = {}
    local deadline = os.clock() + FILLED_WELL_SECONDS
    for i = 1, math.min(FARM_SCAN_LEVELS, #area.levels) do
        local z = area.levels[i].z
        for y = area.y1, area.y2 do
            if os.clock() > deadline then cut = true break end
            for x = area.x1, area.x2 do
                local mat = floor_material(x, y, z)
                if mat and mat ~= 'CONSTRUCTION' then
                    local t = tile_info(x, y, z)
                    local under = tile_info(x, y, z - 1)
                    if t and not t.liquid and not t.feature and not t.outside and not t.building
                            and not t.designated and not inside_any(reserved, x, y, z)
                            and area.groups[walk_group(x, y, z)] and not building_at(x, y, z)
                            and under and under.shape == 'WALL' then
                        local zones, ok_zone, liked = zone_types(x, y, z), true, false
                        for _, k in ipairs(zones) do
                            if WELL_ZONES[k] then liked = true else ok_zone = false end
                        end
                        local score = (liked and 0 or 1000) + (i - 1) * 50
                            + math.abs(x - area.cx) + math.abs(y - area.cy)
                        if ok_zone and (not best_score or score < best_score)
                                and well_floor_beside(x, y, z) then
                            local why = filled_well_why(x, y, z, h, reserved)
                            if why then
                                why_not[why] = true
                            else
                                best, best_score = {x = x, y = y, z = z, half = h, zone = liked}, score
                            end
                        end
                    end
                end
            end
        end
    end
    if best then return best end
    local reasons = {}
    for w in pairs(why_not) do table.insert(reasons, w) end
    table.sort(reasons)
    return nil, (cut and 'search cut short: ' or '') .. ('no floor inside the fort over %dx%d tiles of solid rock '
        .. 'for a winter cistern'):format(2 * h + 1, 2 * h + 1)
        .. (#reasons > 0 and (' (' .. table.concat(reasons, '; ') .. ')') or ''), cut
end

-- The chamber's tiles (z - 1) but the one under the well (the channel makes it a ramp).
function filled_well_chamber(spot)
    local out = {}
    for dy = -spot.half, spot.half do
        for dx = -spot.half, spot.half do
            if dx ~= 0 or dy ~= 0 then table.insert(out, {x = spot.x + dx, y = spot.y + dy, z = spot.z - 1}) end
        end
    end
    return out
end

-- (r2 h2) the pond zone on a winter cistern's well, kept filling (quickfort's
-- `p` zone is a pond with keep_filled on; set again so it surely is)
function filled_well_keep_filling(p)
    local a = anchor_of(p)
    local n = 0
    pcall(function()
        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(a.x, a.y, p.z)) or {}) do
            if zn.type == df.civzone_type.Pond then
                pcall(function() zn.zone_settings.pond.flag.keep_filled = true end)
                n = n + 1
            end
        end
    end)
    return n
end

function place_well(params, now, dry_run)
    OFFSET = elevation_offset()
    local data = load_projects()
    local open = open_projects(data)
    -- (0.104.13) a well the injured or the parched wait for takes an urgent
    -- slot, like soap and tombs (Enxah: "no well yet: waiting for a free
    -- building slot" while patients died of thirst)
    -- (R2 h3) a well is a small need: it takes the needs' pool (NEED_SLOTS) past the cap
    if #open >= slot_cap(open) + (params.urgent == true and URGENT_EXTRA or 0)
            and not (type(need_slot_free) == 'function' and need_slot_free(open, {need = 'well'}, 'well')) then
        return {ok = false, rejected = true,
                error = ('already %d unfinished building projects'):format(#open)}
    end
    -- (0.104.13) dug first while the injured wait (quickfort's priority digit:
    -- 1 is the highest; 4, the game's default, otherwise)
    local pri = params.urgent == true and '1' or ''
    local reserved = {}
    for _, p in ipairs(open) do table.insert(reserved, p.area) end
    -- (0.105.31) nor where a well was given up as out of reach lately: E's
    -- shore well went on the same tile (x67 y124) four times, a year each
    for _, a in ipairs(well_spots_unreached(data)) do table.insert(reserved, a) end
    local spot, why, cut      -- (13c) cut: a search ran out of time
    if params.cavern then
        -- (0.105.47) one cavern well at a time, none for a while after one was
        -- given up, and a site given up WELL_SITE_TRIES times kept free
        -- (ai-well-safety place_gate; E placed 13 in 6 hours, 11 dead)
        local gate = well_safety_call('place_gate', data, params, now, 'active')
        if type(gate) == 'table' and gate.reject then return gate.reject end
        -- (0.105.24) a cavern well given up because the game wouldn't place
        -- the well over its dug shaft (C, F) is taken up again first, with a
        -- floor dug beside the shaft's top: no second shaft into the cavern
        local okr, rv = pcall(revive_cavern_well, data, pri, dry_run)
        if okr and rv then return rv end
        gate = well_safety_call('place_gate', data, params, now)
        if type(gate) == 'table' and gate.reject then return gate.reject end
        for _, a in ipairs(type(gate) == 'table' and type(gate.reserved) == 'table' and gate.reserved or {}) do
            table.insert(reserved, a)
        end
        -- (0.105.4 review) a "no spot" kept since the last survey: not searched again
        -- (third review: the near box's save counts as a survey, near_tick)
        local okw, wl = pcall(function() return reqscript('ai-water').last() end)
        local stamp = ('%s/%s'):format(okw and type(wl) == 'table' and tostring(wl.near_tick or wl.tick) or '-', tostring(params.gallery))
        local today = type(now) == 'table' and ((tonumber(now.year) or 0) * 403200 + (tonumber(now.tick) or 0)) // 1200 or nil
        local c = CAVERN_NO_SPOT
        if c and c.stamp == stamp and today and c.day and today >= c.day and today - c.day < CAVERN_NO_SPOT_DAYS then
            return {ok = false, error = c.why, cached = true}
        end
        local started = os.clock()
        spot, why, cut = find_cavern_well_spot(reserved)
        -- (0.105.3) Hammerstirred (2 Nov): no fort floor over the cavern lake
        -- (it lies beside the fort, 80 tiles off by the survey): a gallery
        -- through solid rock out to a column over it, unless the brain says no
        if not spot and params.gallery ~= 0 then
            local left = math.max(0.1, CAVERN_TOTAL_SECONDS - (os.clock() - started))
            local g, gwhy, gcut = find_gallery_well_spot(reserved, {max = params.gallery, toward = params.toward, seconds = left})
            if g then spot = g else why, cut = why .. '; ' .. gwhy, cut or gcut end
        end
        if not spot then
            -- (a search cut short by its time is not kept: it may find one next time)
            if not cut then CAVERN_NO_SPOT = {stamp = stamp, day = today, why = why} end
            return {ok = false, error = why, timed_out = cut or nil}
        end
        CAVERN_NO_SPOT = nil
        -- (0.105.4 review) Hammerstirred's Cavern1 was undiscovered: the first
        -- breach changes the fort's dangers, so only when the player allows it
        if spot.hidden and params.open_caverns ~= true then
            return {ok = false, rejected = true, unfound = true,
                    error = 'the shaft would open a cavern no dwarf has seen yet: allowed only from the Rules tab '
                        .. '("Cavern well into an unfound cavern")'}
        end
    elseif params.filled then
        -- (r2 h2) the winter cistern: a chamber in solid rock filled by bucket
        spot, why, cut = find_filled_well_spot(reserved, params.half)
        if not spot then return {ok = false, filled = true, error = why, timed_out = cut or nil} end
        spot.filled = true
    else
        spot, why, cut = find_well_spot(reserved)
    end
    if not spot and params.inside_only then
        return {ok = false, timed_out = cut or nil, error = why .. '; and the water near the surface freezes in winter (a well over '
                .. 'it would be taken down), so the AI looks only inside the fort'}
    end
    if not spot then
        local shore, why2, cut2 = find_shore_well_spot(reserved, params.shore_reach)
        if not shore then return {ok = false, error = why .. '; ' .. why2, timed_out = (cut or cut2) or nil} end
        spot = shore
    end
    local dig = {{x = 0, y = 0, text = 'h' .. pri}}
    local dry = quickfort_apply('dig', dig, spot.z, spot.x, spot.y, 'run', true)
    if stat(dry, 'dig_designated') ~= 1 then
        return {ok = false, error = ('the game would not channel the well spot at x%d y%d z%d'):format(
            spot.x, spot.y, ez(spot.z)) .. dig_guard_note(dry)}   -- (0.105.40b fix) the guard's why
    end
    -- a cavern well's shaft: every rock level under the floor channelled too,
    -- each from the stair column beside it (0.104.13)
    local shaft = {}
    for k = 1, spot.cavern and spot.rock or 0 do
        local zk = spot.z - k
        local d = quickfort_apply('dig', dig, zk, spot.x, spot.y, 'run', true)
        if stat(d, 'dig_designated') ~= 1 then
            return {ok = false, error = ('the game would not channel the shaft at elevation %d'):format(ez(zk))
                    .. dig_guard_note(d)}   -- (0.105.40b fix) the guard's why
        end
        table.insert(shaft, zk)
    end
    -- (r2 h2) the winter cistern's chamber, dug from the ramp the channel leaves
    local chamber = {}
    if spot.filled then
        for _, c in ipairs(filled_well_chamber(spot)) do
            local d = quickfort_apply('dig', {{x = 0, y = 0, text = 'd' .. pri}}, c.z, c.x, c.y, 'run', true)
            if stat(d, 'dig_designated') ~= 1 then
                return {ok = false, filled = true, error = ('the game would not dig the winter cistern at x%d y%d elevation %d')
                        :format(c.x, c.y, ez(c.z)) .. dig_guard_note(d)}
            end
            table.insert(chamber, c)
        end
    end
    -- (0.105.24) the well needs a floor on one of its sides (quickfort's well
    -- test): the gallery's or the hall's; else a landing dug beside the shaft
    local galls = {}
    for _, g in ipairs(spot.gallery or {}) do galls[g.x .. ',' .. g.y] = true end
    local landing
    if spot.cavern then
        if not well_floor_beside(spot.x, spot.y, spot.z, galls, spot.side) then
            local lwhy
            landing, lwhy = well_landing(spot.x, spot.y, spot.z, spot.side, galls)
            if not landing then
                return {ok = false, error = ('no floor beside the well spot at x%d y%d elevation %d for its builder (%s)')
                    :format(spot.x, spot.y, ez(spot.z), lwhy)}
            end
            spot.gallery = spot.gallery or {}
            table.insert(spot.gallery, {x = landing.x, y = landing.y})
        end
    end
    -- (0.105.3) the gallery out to the shaft, dug as plain floor through the rock
    local gallery = {}
    for _, g in ipairs(spot.gallery or {}) do
        local d = quickfort_apply('dig', {{x = 0, y = 0, text = 'd' .. pri}}, spot.z, g.x, g.y, 'run', true)
        if stat(d, 'dig_designated') ~= 1 then
            return {ok = false, error = ('the game would not dig the gallery at x%d y%d elevation %d'):format(g.x, g.y, ez(spot.z))}
        end
        table.insert(gallery, {x = g.x, y = g.y})
    end
    -- (0.105.4 review) the review: the last channel opened the cavern while the
    -- project was still digging, and the gate's lever and hatch came only at
    -- furnish (links lost 3+ times on 1 Nov). That level and the stair step
    -- beside it are held undug until the lever stands and a hatch cover and 2
    -- mechanisms are in store (well_shaft_step lets them go)
    local held = spot.cavern and #shaft > 0 and {z = shaft[#shaft], stair = spot.side and {x = spot.side.x, y = spot.side.y}} or nil
    -- (0.105.47) the shaft dug from the bottom up (ai-well-safety): the last
    -- level into the cavern is opened first, from the stair step beside it
    -- (the levels over it still rock), then each level over an open one, the
    -- top channel in the fort's floor last. Dug from the top down, every
    -- channel turned the rock under it into a ramp, so the shaft's column was
    -- a walk of ramps down to the cavern's ceiling, and the dwarf standing on
    -- the last one fell in when it was channelled away (B, E: COLLISION in
    -- the shaft's very column; six drowned in the lake under fresh shafts).
    -- Now no tile of the column is ever a floor or a ramp to stand on.
    -- (K48-K4) But the top: in a hall (a floor to walk on, not the rock of a
    -- gallery's end) the last channel opened the floor a dwarf may be
    -- crossing over a shaft open all the way down (9-22 levels in War-hold).
    -- There the level under the top stays rock until the top is channelled
    -- (a dwarf on it drops one level, onto the ramp it leaves), and that ramp
    -- is channelled away last, from the stair beside it.
    local up = nil
    if held and WELL_DIG_UP ~= false then
        up = {zs = {}}
        local under = spot.z - 1
        local tt = tile_info(spot.x, spot.y, spot.z)
        local top_first = tt ~= nil and tt.shape ~= 'WALL' and held.z ~= under and shaft[1] == under
        for i = #shaft, 1, -1 do
            if shaft[i] ~= held.z and not (top_first and shaft[i] == under) then table.insert(up.zs, shaft[i]) end
        end
        table.insert(up.zs, spot.z)
        if top_first then
            table.insert(up.zs, under)
            up.top_first = true
        end
    end
    local stairs = {}
    if spot.cavern then
        if not spot.side then return {ok = false, error = 'no room beside the shaft for the stairs it is dug from'} end
        for _, c in ipairs(shaft_stair_cells(spot.side, spot.z, spot.rock)) do
            local d = quickfort_apply('dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'run', true)
            if stat(d, 'dig_designated') ~= 1 then
                return {ok = false, error = ('the game would not dig the shaft\'s stairs at elevation %d'):format(ez(c.z))}
            end
            table.insert(stairs, c)
        end
    end
    local where = {x = spot.x, y = spot.y, elevation = ez(spot.z), drop = spot.drop, in_hall = spot.zone,
                   shore = spot.shore, stagnant = spot.stagnant, cavern = spot.cavern, shaft = #shaft,
                   stairs = #stairs > 0 and #stairs or nil, urgent = params.urgent == true or nil,
                   gallery = #gallery > 0 and #gallery or nil, from = spot.from, from_gate = spot.from_gate,
                   held = held and 2 or nil, landing = landing and {x = landing.x, y = landing.y} or nil,   -- (0.105.24)
                   dug_up = up and true or nil,   -- (0.105.47)
                   filled = spot.filled or nil, chamber = #chamber > 0 and #chamber + 1 or nil}   -- (r2 h2)
    if dry_run then
        where.ok, where.dry_run = true, true
        return where
    end
    if not up then
        local real = quickfort_apply('dig', dig, spot.z, spot.x, spot.y)
        if stat(real, 'dig_designated') ~= 1 then
            pcall(quickfort_apply, 'dig', dig, spot.z, spot.x, spot.y, 'undo')
            return {ok = false, error = 'the game refused to channel the well spot'}
        end
        for _, zk in ipairs(shaft) do
            if not (held and zk == held.z) then pcall(quickfort_apply, 'dig', dig, zk, spot.x, spot.y) end
        end
    end
    for _, g in ipairs(gallery) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. pri}}, spot.z, g.x, g.y)
    end
    for _, c in ipairs(chamber) do      -- (r2 h2)
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. pri}}, c.z, c.x, c.y)
    end
    for _, c in ipairs(stairs) do
        if not (held and c.z == held.z) then
            pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y)
        end
    end
    local p = {
        id = data.next_id, kind = 'well', phase = 'dig', params = {pri = pri ~= '' and pri or nil},
        stair = {x = spot.x, y = spot.y}, anchor = {x = spot.x, y = spot.y}, z = spot.z,
        area = {x1 = spot.x - 1, y1 = spot.y - 1, x2 = spot.x + 1, y2 = spot.y + 1, z = spot.z},
        corridor = 0, stairs = {}, dig_done = 'open', shaft = #shaft > 0 and shaft or nil,
        shaft_stairs = #stairs > 0 and stairs or nil, urgent = params.urgent == true or nil,
        need = 'well',                                  -- (R2 h3) counted in the needs' pool, not the cap
        gallery = #gallery > 0 and gallery or nil,      -- (0.105.3)
        held = held,                                    -- (0.105.4 review)
        up = up,                                        -- (0.105.47) dug from the bottom up
        landing = landing,                              -- (0.105.24) the floor dug beside the shaft's top
        -- (0.105.47) shore: the brain gives up a shore well still being dug before the ice (planner_ice)
        summary = {well = 1, drop = spot.drop, cavern = spot.cavern, shore = spot.shore},
        furniture = {Well = 1},
        chamber = #chamber > 0 and chamber or nil,   -- (r2 h2) its tiles one level down
        -- (r2 h2) the winter cistern's pond zone on the well's tile: the dwarves fill it by bucket
        cells = {dig = dig, build = {{x = 0, y = 0, text = 'l'}}, place = {},
                 zone = spot.filled and {{x = 0, y = 0, text = ('p{name="%s"}'):format(FILLED_WELL_ZONE)}} or {},
                 smooth = {}, engrave = {}},
        started = now, designated = 1,
    }
    p.summary.filled = spot.filled         -- (r2 h2) the winter cistern
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    if not save_projects(data) then
        -- (0.105.33 L5) every cell designated taken back, not the top channel only
        pcall(quickfort_apply, 'dig', dig, spot.z, spot.x, spot.y, 'undo')
        undo_well_cells(p)
        return {ok = false, error = 'could not save the project with the fort, so it was undone'}
    end
    where.ok, where.project_id = true, p.id
    return where
end


-- --- (0.105.31) a well's channel nobody digs ---------------------------------
--
-- Shore wells in every fort sat at "0 of 1 tiles dug" for 14 to 80 days, a
-- year in E (x67 y124, four times): a DigChannel job DF made and no miner
-- took (free_dig_jobs freed nothing: it had no worker), and the dig_first
-- rule couldn't raise a channel (prioritize_project raises rock only). Now
-- the bridge says why (well_dig_check), the brain renews the channel
-- (renew_well_dig: the unworked job taken away, the tile designated a
-- channel again at a higher priority; DF makes a fresh job) and a spot given
-- up as out of reach isn't chosen again for UNREACHED_YEARS.

-- The areas of wells given up as out of reach, or (0.105.33 B4) whose well
-- the game refused to place, in the last UNREACHED_YEARS.
function well_spots_unreached(data)
    local out = {}
    local okc, year = pcall(function() return df.global.cur_year end)
    for _, p in ipairs(type(data) == 'table' and data.list or {}) do
        if p.kind == 'well' and (p.unreached or p.refused) and type(p.area) == 'table' then
            local y = tonumber(p.cancelled_year)
            if not (okc and y) or year - y < (UNREACHED_YEARS or 5) then table.insert(out, p.area) end
        end
    end
    return out
end

-- The citizens with the mining labour ({x, y, z} each), or nil when it
-- can't be read. Tests replace this.
function well_miners()
    local ok, out = pcall(function()
        local out = {}
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local okl, mine = pcall(function() return u.status.labors.MINE end)
            if okl and mine then
                local x, y, z = dfhack.units.getPosition(u)
                if x then table.insert(out, {x = x, y = y, z = z}) end
            end
        end
        return out
    end)
    return ok and out or nil
end

-- Why a well level's channel isn't dug: {cause, text, x, y, elevation} or
-- nil. cause: 'no_designation' (gone and no job), 'wrong_designation' (a
-- dig of another kind on the floor), 'marked' (marker only), 'no_miners',
-- 'no_ground' (nothing to stand on beside it), 'unreached' (no miner walks
-- to beside it), 'held' (a cavern shaft's last level waits for its gate),
-- 'unworked' (a job no miner takes), 'waiting' (designated, no job yet).
-- A miner channels from beside the tile, on its own level.
function well_dig_check(p, jobs)
    local a = anchor_of(p)
    local x, y, z = a.x, a.y, p.z
    local t = tile_info(x, y, z)
    if not t then return nil end
    local function out(cause, text)
        return {cause = cause, text = text, x = x, y = y, elevation = ez(z)}
    end
    jobs = jobs or job_tiles()
    local job = jobs[x .. ',' .. y .. ',' .. z]
    if not job and not t.designated and well_up_waits(p, x, y, z) then
        -- (0.105.47) dug from the bottom up: the top channel comes last
        return out('held', 'the shaft is dug from the bottom up: its top waits for the levels under it')
    end
    if not job and not t.designated then
        return out('no_designation', 'its channel designation is gone and no job is on it')
    end
    if t.marked then
        return out('marked', 'it is designated as a marker only, which no dwarf digs')
    end
    if not job and t.dig and t.dig ~= 'Channel' then
        return out('wrong_designation', ('it is designated "%s", not a channel'):format(tostring(t.dig)))
    end
    local miners = well_miners()
    if miners and #miners == 0 then
        return out('no_miners', 'no citizen has the mining labour')
    end
    if miners then
        local groups = {}
        for _, m in ipairs(miners) do
            local g = walk_group(m.x, m.y, m.z)
            if g ~= 0 then groups[g] = true end
        end
        local ground, reached = false, false
        for dy = -1, 1 do
            for dx = -1, 1 do
                if dx ~= 0 or dy ~= 0 then
                    local g = walk_group(x + dx, y + dy, z)
                    if g ~= 0 then
                        ground = true
                        if groups[g] then reached = true end
                    end
                end
            end
        end
        if not ground then return out('no_ground', 'no floor beside it for a miner to stand on') end
        if not reached then
            return out('unreached', ('none of the %d miners can walk to beside it'):format(#miners))
        end
    end
    if type(p.held) == 'table' and not job then
        return out('held', 'the shaft\'s last level waits for its gate (lever, hatch cover, mechanisms)')
    end
    if job then
        return out('unworked', 'DF made the channel job but no miner takes it (a stale job, other digging '
                               .. 'first, or a shut door, burrow or raised bridge on the way)')
    end
    return out('waiting', 'designated as a channel, waiting for a miner')
end

-- (0.105.31 reserve fixes) the jobs renew_well_dig may take away: the
-- channel (or a dig) on the well's tile, never another job standing there
-- (a construction, a haul, a building's)
WELL_RENEW_JOBS = {DigChannel = true, Dig = true}
function well_dig_job(j)
    local ok, name = pcall(function() return df.job_type[j.job_type] end)
    return ok and name ~= nil and WELL_RENEW_JOBS[name] == true
end

-- The well level's channel renewed: its unworked channel (or dig) job taken away
-- and the floor designated a channel again at priority `pri` (DF makes a
-- fresh job from it). Rock left under a cavern shaft is not touched here.
function renew_well_dig(id, pri, dry_run)
    pri = math.max(1, math.min(3, math.tointeger(pri) or 2))
    local data = load_projects()
    local p
    for _, q in ipairs(data.list or {}) do if q.id == id then p = q end end
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.kind ~= 'well' or p.dig_done ~= 'open' then
        return {ok = false, rejected = true, error = 'only a well level\'s channel is renewed'}
    end
    if p.phase ~= 'dig' then return {ok = false, rejected = true, error = 'project is not being dug'} end
    local a = anchor_of(p)
    if well_up_waits(p, a.x, a.y, p.z) then      -- (0.105.47)
        return {ok = false, rejected = true, error = 'the shaft is dug from the bottom up: its top waits for the levels under it'}
    end
    local t = tile_info(a.x, a.y, p.z)
    if not (t and t.shape == 'FLOOR') then
        return {ok = false, rejected = true, error = 'nothing left to channel'}
    end
    local okc, check = pcall(well_dig_check, p)
    if dry_run then
        return {ok = true, dry_run = true, priority = pri, cause = okc and check and check.cause or nil}
    end
    local gone = 0
    pcall(function()
        local link = df.global.world.jobs.list.next
        while link do
            local j, nxt = link.item, link.next
            if j and j.pos.x == a.x and j.pos.y == a.y and j.pos.z == p.z and well_dig_job(j) then
                local okw, w = pcall(dfhack.job.getWorker, j)
                if not (okw and w) and pcall(dfhack.job.removeJob, j) then gone = gone + 1 end
            end
            link = nxt
        end
    end)
    local s = quickfort_apply('dig', {{x = 0, y = 0, text = 'h' .. pri}}, p.z, a.x, a.y)
    if stat(s, 'dig_designated') ~= 1 then
        return {ok = false, error = ('the game would not channel the well spot at x%d y%d elevation %d again')
                    :format(a.x, a.y, ez(p.z)), renewed = gone}
    end
    p.dig_pri, p.renewed = pri, (tonumber(p.renewed) or 0) + 1
    save_projects(data)
    return {ok = true, priority = pri, renewed = gone, times = p.renewed,
            cause = okc and check and check.cause or nil}
end
