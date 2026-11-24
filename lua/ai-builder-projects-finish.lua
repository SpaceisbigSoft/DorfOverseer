-- ai-builder-projects-finish: a project's steps on order: dedicate, retarget, prioritize, unmark; furnish
-- (a well refused), finish (what waits is dropped or kept), engrave.
--
-- (r8) A part of ai-builder, not a script of its own: cut from ai-builder-projects.lua
-- (which had grown to 164 KB) at a section boundary, the code as it stood. ai-builder.lua
-- loads it into its own environment right after the part before it (PARTS), so every
-- name here is reqscript('ai-builder').name and the hub's helpers are in reach.
-- The top-level locals the ai-builder-projects files share come through
-- PROJECTS_PART_LOCALS (the same functions).

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-projects-finish'] = '0.105.106'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

local function find(data, id)
    for _, p in ipairs(data.list) do
        if p.id == id then return p end
    end
end

-- (0.89) The temple location quickfort just made for a project's zone,
-- dedicated to the deity (or religion) a petition asked for. Returns the
-- location id, or false if none was found. Swapped by the tests.
function dedicate_temple(p, pr)
    local site = dfhack.world.getCurrentSite()
    local a = anchor_of(p)
    for _, c in ipairs(cells_of(p, 'zone')) do
        local zones = dfhack.buildings.findCivzonesAt({x = a.x + c.x, y = a.y + c.y, z = p.z}) or {}
        for _, z in ipairs(zones) do
            if z.location_id and z.location_id >= 0 then
                for _, loc in ipairs(site.buildings) do
                    if loc.id == z.location_id and df.abstract_building_type[loc:getType()] == 'TEMPLE'
                            and df.religious_practice_type[loc.deity_type] ~= 'WORSHIP_HFID'
                            and df.religious_practice_type[loc.deity_type] ~= 'RELIGION_ENID' then
                        if pr.religion then
                            loc.deity_type = df.religious_practice_type.RELIGION_ENID
                            loc.deity_data.Religion = pr.religion
                        else
                            loc.deity_type = df.religious_practice_type.WORSHIP_HFID
                            loc.deity_data.Deity = pr.deity_hf
                        end
                        return loc.id
                    end
                end
            end
        end
    end
    return false
end

-- (0.92) A hall still being dug for a petition that something else has
-- answered meanwhile (region2: the player made the metalsmiths' guildhall
-- while the AI dug one) is given to the next petition instead: its params
-- and its zone (placed only once the digging is done) change. target:
-- {profession = 'FARMER'} or {deity_hf = n} or {religion = n}.
function retarget_hall(id, target, dry_run)
    local data = load_projects()
    local p = find(data, id)
    if not p or p.kind ~= 'temple' then return {ok = false, rejected = true, error = 'no such hall project'} end
    if p.phase ~= 'dig' then
        return {ok = false, rejected = true, error = ('the hall is already %s: its zone stands'):format(p.phase)}
    end
    local loc
    if target.profession then
        if not tostring(target.profession):match('^[%u_]+$') then return {ok = false, rejected = true, error = 'bad profession'} end
        loc = 'location=guildhall profession=' .. target.profession:lower()
    elseif target.deity_hf or target.religion then
        loc = 'location=temple'
    else
        return {ok = false, rejected = true, error = 'retarget_hall needs profession, deity_hf or religion'}
    end
    local changed = 0
    for _, c in ipairs(type(p.cells) == 'table' and p.cells.zone or {}) do
        if type(c.text) == 'string' and c.text:find('location=') then
            c.text = c.text:gsub('m{[^}]*}', 'm{' .. loc .. '}', 1)
            changed = changed + 1
        end
    end
    if changed == 0 then return {ok = false, rejected = true, error = 'the hall has no location zone'} end
    local out = {ok = true, project_id = id, zone = loc, dry_run = dry_run or nil}
    if dry_run then return out end
    p.params = type(p.params) == 'table' and p.params or {}
    p.params.profession, p.params.deity_hf, p.params.religion = target.profession, target.deity_hf, target.religion
    if type(p.summary) == 'table' then
        p.summary.guildhall = target.profession and target.profession:lower() or nil
        p.summary.deity_hf, p.summary.religion = target.deity_hf, target.religion
    end
    save_projects(data)
    return out
end

-- Dig finished -> place doors, furniture, workshops, stockpiles and zones.
-- (0.104.110) Dig jobs on a stalled level let go of their workers, so other
-- miners take them (a dwarf who took a job and then lay in the hospital for
-- years held it all along). Returns {ok, freed}.
function free_dig_jobs(id)
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then return {ok = false, rejected = true, error = 'project is not being dug'} end
    local anchor, tiles = anchor_of(p), {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do tiles[(anchor.x + x) .. ',' .. (anchor.y + y) .. ',' .. p.z] = true end
    end
    local freed = 0
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j and tiles[j.pos.x .. ',' .. j.pos.y .. ',' .. j.pos.z] then
            local okw, w = pcall(dfhack.job.getWorker, j)
            if okw and w and pcall(dfhack.job.removeWorker, j, 0) then freed = freed + 1 end
        end
        link = link.next
    end
    return {ok = true, freed = freed}
end

-- (0.104.128) the tiles of an open level still to dig raised to priority `pri`
function prioritize_project(id, pri, dry_run)
    pri = math.max(1, math.min(3, math.tointeger(pri) or URGENT_DIG_PRIORITY))
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then return {ok = false, rejected = true, error = 'project is not being dug'} end
    -- (0.105.30 live fixes) a channel level (a well's hole, dig_done 'open'):
    -- its tile is a floor to channel, which this (WALL tiles, 'd') can't raise
    -- and would turn into a plain dig; the brain no longer asks for wells
    if p.dig_done == 'open' then
        return {ok = false, rejected = true, error = 'a channel (a well\'s hole) is not raised: nothing to dig in rock'}
    end
    -- (0.104.134) the dig jobs DF made before at the old priority keep it: those
    -- nobody holds are taken away, and DF makes them again from the raised
    -- designation (Teacheroar's hospital: raised to 2, still 0 of 175 dug 18
    -- days on, its one job "no worker")
    -- (0.104.135) DF drops a tile's dig designation with its job: each tile is
    -- designated again at the new priority (0.104.134 left the hospital's first
    -- tile bare, and the stuck-level rule gave the level up a minute later)
    local function renew_jobs(level)
        local anchor, at = anchor_of(p), {}
        for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
            for y in pairs(col) do at[(anchor.x + x) .. ',' .. (anchor.y + y) .. ',' .. p.z] = true end
        end
        local gone, cleared, link = 0, {}, df.global.world.jobs.list.next
        while link do
            local j, nxt = link.item, link.next
            if j and at[j.pos.x .. ',' .. j.pos.y .. ',' .. j.pos.z] then
                local okw, w = pcall(dfhack.job.getWorker, j)
                if not (okw and w) then
                    local pos = {x = j.pos.x, y = j.pos.y, z = j.pos.z}
                    if pcall(dfhack.job.removeJob, j) then
                        gone = gone + 1
                        table.insert(cleared, pos)
                    end
                end
            end
            link = nxt
        end
        for _, c in ipairs(cleared) do
            local t = tile_info(c.x, c.y, c.z)
            if t and t.shape == 'WALL' and not t.designated then
                pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. level}}, c.z, c.x, c.y)
            end
        end
        return gone
    end
    if p.dig_pri and p.dig_pri <= pri then          -- done before: its old jobs renewed
        if dry_run then return {ok = true, dry_run = true, already = true, priority = p.dig_pri} end
        local okr, gone = pcall(renew_jobs, p.dig_pri)
        return {ok = true, already = true, priority = p.dig_pri, tiles = 0, renewed = okr and gone or 0}
    end
    local anchor, cells = anchor_of(p), {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do
            local t = tile_info(anchor.x + x, anchor.y + y, p.z)
            if t and t.shape == 'WALL' then table.insert(cells, {x = x, y = y, text = 'd' .. pri}) end
        end
    end
    if #cells == 0 then return {ok = false, rejected = true, error = 'nothing left to dig'} end
    if dry_run then return {ok = true, dry_run = true, tiles = #cells, priority = pri} end
    local s = quickfort_apply('dig', cells, p.z, anchor.x, anchor.y)
    local n = stat(s, 'dig_designated')
    if n == 0 then return {ok = false, error = 'the game took none of the tiles at the new priority'} end
    p.dig_pri = pri
    save_projects(data)
    local okr, gone = pcall(renew_jobs, pri)
    return {ok = true, tiles = n, priority = pri, renewed = okr and gone or 0}
end

-- (0.105.35) A tile's marker-only (blueprint) dig designation made a real
-- one, so the dwarves dig it: only where a dig designation stands under the
-- marker (nothing new is designated). True when it was changed.
function make_dig_real(x, y, z)
    local des, occ = dfhack.maps.getTileFlags(x, y, z)
    if not des or not occ or not occ.dig_marked or des.dig == df.tile_dig_designation.No then return false end
    occ.dig_marked = false
    local blk = dfhack.maps.getTileBlock(x, y, z)
    if blk then blk.flags.designated = true end      -- DF looks for new dig jobs in this block
    return true
end

-- (0.105.35) An AI level whose dig tiles are marker-only designations (DF's
-- blueprint mode, or quickfort's marker setting): nobody digs them. Each one
-- of the project's own tiles made a real designation; the dry run counts them.
function unmark_project_dig(id, dry_run)
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then return {ok = false, rejected = true, error = 'project is not being dug'} end
    local anchor, spots = anchor_of(p), {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do table.insert(spots, {anchor.x + x, anchor.y + y, p.z}) end
    end
    if type(p.stair) == 'table' then
        for _, c in ipairs(p.stairs or {}) do table.insert(spots, {p.stair.x, p.stair.y, c.z}) end
    end
    -- (0.105.36 D3) and the tiles dig_progress keeps: a cavern well's shaft
    -- (at the anchor), a way in's or well's shaft stairs, a gallery out to it
    for _, zk in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do table.insert(spots, {anchor.x, anchor.y, zk}) end
    for _, c in ipairs(type(p.shaft_stairs) == 'table' and p.shaft_stairs or {}) do
        table.insert(spots, {c.x, c.y, c.z})
    end
    for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do table.insert(spots, {g.x, g.y, p.z}) end
    for _, c in ipairs(type(p.chamber) == 'table' and p.chamber or {}) do table.insert(spots, {c.x, c.y, c.z}) end   -- (r2 h2)
    local marked = {}
    for _, q in ipairs(spots) do
        local t = tile_info(q[1], q[2], q[3])
        if t and t.marked then table.insert(marked, q) end
    end
    if #marked == 0 then return {ok = false, rejected = true, error = 'none of its tiles is a marker designation'} end
    if dry_run then return {ok = true, dry_run = true, tiles = #marked} end
    local n = 0
    for _, q in ipairs(marked) do
        local ok, done = pcall(make_dig_real, q[1], q[2], q[3])
        if ok and done then n = n + 1 end
    end
    -- (0.105.36 D3) tried: a way in's marker tile left after this counts as
    -- a missing step (next_step), so the way in can end
    p.unmark_tried = true
    save_projects(data)
    if n == 0 then return {ok = false, error = 'none of the marker designations could be made real'} end
    return {ok = true, tiles = n, marked = #marked}
end

-- (0.104.110) a level 90%+ dug whose last tiles haven't moved for weeks
-- (Teacheroar's tomb level: 235 of 240 for three game years, holding one of
-- the two building slots) is furnished without them when the brain says so
STALLED_SHARE = 0.9

-- (0.105.24) The game wouldn't place the well over the dug hole. Was: the
-- project cancelled for good at the first refusal, with no word on why (C,
-- F, 3 Nov). Now the refusal says what the game shows there (the tile and
-- the two below by DF's tiletype names, its four sides, a building on it,
-- quickfort's counts: `diagnosis`, kept in the project as `well_diag`), and
-- it is tried again before it is given up:
--   1. no floor on any side (quickfort's well test): a landing dug beside the
--      shaft's top (well_landing), the project back to digging, then furnished;
--   2. otherwise again a day later (WELL_RETRY_DAYS), WELL_REFUSALS_MAX times
--      in all; then cancelled, the last diagnosis in the error.
-- A refusal that will be tried again comes back with `retry` (the brain
-- doesn't take it for "no well can be placed").
WELL_REFUSALS_MAX = 3
WELL_RETRY_DAYS = 1

function well_refused(data, p, results, qf_build)
    local a = anchor_of(p)
    -- the well there after all (placed, the count read wrong): furnished
    local okb, here = pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(a.x, a.y, p.z))
        return b ~= nil and b:getType() == df.building_type.Well
    end)
    if okb and here then
        p.phase = 'furnish'
        p.furnish_started = {year = now_tick() // 403200, tick = now_tick() % 403200}
        save_projects(data)
        return {ok = true, project_id = p.id, placed = results, note = 'the well stands there already'}
    end
    local okd, diag = pcall(well_diagnosis, a.x, a.y, p.z)
    diag = okd and diag or {text = 'unreadable: ' .. tostring(diag):sub(1, 100)}
    diag.quickfort = qf_build
    diag.build = results.build
    p.well_refusals = (tonumber(p.well_refusals) or 0) + 1
    p.well_diag = diag
    local where = ('x%d y%d z%d'):format(a.x, a.y, ez(p.z))
    -- 1. no floor beside it: a landing dug (once)
    local stair = type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] or nil
    if not well_floor_beside(a.x, a.y, p.z, nil, stair) and not p.landing then
        local galls = {}
        for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do galls[g.x .. ',' .. g.y] = true end
        local land, lwhy = well_landing(a.x, a.y, p.z, stair, galls)
        local pri = type(p.params) == 'table' and p.params.pri or ''
        if land then
            local okq, s = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = 'd' .. (pri or '')}}, p.z, land.x, land.y)
            if okq and stat(s, 'dig_designated') == 1 then
                p.landing = {x = land.x, y = land.y}
                p.gallery = type(p.gallery) == 'table' and p.gallery or {}
                table.insert(p.gallery, {x = land.x, y = land.y})
                save_projects(data)
                return {ok = false, retry = true, project_id = p.id, placed = results, diagnosis = diag,
                        landing = p.landing,
                        error = ('the game would not put the well over the hole at %s yet: no floor beside it (%s); '
                            .. 'a floor is dug beside it at x%d y%d, then the well again'):format(where, diag.text, land.x, land.y)}
            end
            diag.landing_refused = true
        else
            diag.no_landing = lwhy
        end
    end
    -- 2. again a day later, WELL_REFUSALS_MAX times in all
    if p.well_refusals < WELL_REFUSALS_MAX then
        p.well_retry_at = now_tick() + WELL_RETRY_DAYS * 1200
        save_projects(data)
        return {ok = false, retry = true, project_id = p.id, placed = results, diagnosis = diag,
                refusals = p.well_refusals,
                error = ('the game would not put the well over the hole at %s (%d of %d tries; %s): tried again in a day')
                    :format(where, p.well_refusals, WELL_REFUSALS_MAX, diag.text)}
    end
    -- given up (a new well would only dig another hole). (0.105.33 B4) Marked
    -- refused: the brain tries again later, and well_spots_unreached keeps a
    -- new well off this spot (a revived cavern well may still take it up)
    p.phase = 'cancelled'
    p.refused = true
    p.cancelled_year = df.global.cur_year
    p.cancelled_tick = now_tick()   -- (0.105.47) a cavern well's cooldown counts from here (ai-well-safety)
    save_projects(data)
    return {ok = false, project_id = p.id, placed = results, diagnosis = diag, refusals = p.well_refusals,
            error = ('the game would not place the well over the hole at %s (%d tries; %s)'):format(
                where, p.well_refusals, diag.text)}
end

function furnish_project(id, buildingplan_on, stalled)
    OFFSET = elevation_offset()
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then
        return {ok = false, rejected = true, error = ('project is already %s'):format(p.phase)}
    end
    -- (0.105.33, L4) a way in has nothing to furnish: finished when every step is dug
    if p.kind == 'way_in' then
        return {ok = false, rejected = true, error = 'a way in is finished when every step is dug, never furnished'}
    end
    local prog = dig_progress(p)
    local accept_rock = prog.stuck > 0 and prog.dug + prog.stuck + prog.marked == prog.total
        and prog.stuck * 5 <= prog.total and prog.shaft_open ~= false    -- (0.104.13) never over a closed shaft
    if stalled and prog.dug >= STALLED_SHARE * prog.total and prog.shaft_open ~= false then
        accept_rock = true
    end
    if prog.dug < prog.total and not accept_rock then
        return {ok = false, rejected = true,
                error = ('digging not finished (%d of %d tiles)'):format(prog.dug, prog.total)}
    end
    if not buildingplan_on then
        return {ok = false, rejected = true,
                error = 'buildingplan is off: furniture without materials would vanish'}
    end
    local results, qf_build = {}, nil
    for _, mode in ipairs({'build', 'place', 'zone'}) do
        local cells = cells_of(p, mode)
        if #cells > 0 then
            local ok, s = pcall(quickfort_apply, mode, cells, p.z, anchor_of(p).x, anchor_of(p).y)
            results[mode] = ok and stat(s, mode .. '_designated') or ('failed: ' .. tostring(s))
            -- (0.105.24) quickfort's own counts for a well (which of its tests said no)
            if mode == 'build' and p.kind == 'well' and ok and type(s) == 'table' then
                qf_build = {}
                for k, v in pairs(s) do
                    local okv, n = pcall(function() return v.value end)
                    if okv and type(n) == 'number' and n ~= 0 then qf_build[tostring(k)] = n end
                end
            end
        end
    end
    -- smoothing (a dig-mode designation) goes on at the same time, but only
    -- on the level's own tiles and on rock that is still untouched rock (the
    -- player may have dug next to the level since it was started)
    local own = layouts.tiles_from_dig(cells_of(p, 'dig'))
    local a = anchor_of(p)
    local smooth = {}
    for _, c in ipairs(cells_of(p, 'smooth')) do
        if (own[c.x] and own[c.x][c.y]) or natural_wall(tile_info(a.x + c.x, a.y + c.y, p.z)) then
            table.insert(smooth, c)
        end
    end
    if #smooth > 0 then
        local ok, s = pcall(quickfort_apply, 'dig', smooth, p.z, anchor_of(p).x, anchor_of(p).y)
        results.smooth = ok and stat(s, 'dig_designated') or ('failed: ' .. tostring(s))
    end
    -- (0.89) a temple asked for by a petition: its new location dedicated
    local pr = type(p.params) == 'table' and p.params or {}
    -- (D0, G6) and a landmark's level zoned as a temple (params.zone)
    if (p.kind == 'temple' or (p.kind == 'landmark' and pr.zone == 'temple'))
            and (pr.deity_hf or pr.religion) and results.zone and results.zone ~= 0 then
        local okd, ded = pcall(dedicate_temple, p, pr)
        results.dedicated = okd and ded or ('failed: ' .. tostring(ded))
    end
    if p.kind == 'well' and results.build ~= 1 then
        return well_refused(data, p, results, qf_build)
    end
    -- (r2 h2) a winter cistern's pond zone: kept filling
    if p.kind == 'well' and type(p.chamber) == 'table' and type(filled_well_keep_filling) == 'function' then
        local okf, n = pcall(filled_well_keep_filling, p)
        results.pond = okf and n or ('failed: ' .. tostring(n))
    end
    -- (0.105.47, I7b) a tomb level's tombs take the fort's dead from the start
    -- (automatic burial was found off on free tombs twice in B)
    if p.kind == 'tombs' then
        pcall(function() results.burial = reqscript('ai-welfare').open_tombs(own_areas(p)).opened end)
    end
    p.phase = 'furnish'
    p.furnish_started = {year = now_tick() // 403200, tick = now_tick() % 403200}
    local saved = save_projects(data)
    return {ok = true, project_id = id, placed = results,
            warning = (not saved) and 'not recorded' or nil}
end

-- Furnishing finished (everything built, or nothing to build, e.g. a storage
-- level) -> done. Reports never change anything, so the overseer asks.
-- (0.104.12) decor_only: finished while only statues wait (they stay planned
-- and go up when there's stone; the slot goes to the next level). Enxah's
-- suites held a building slot 257 days for 4 statues with no stone to carve.
DECOR_ONLY = {Statue = true}
-- (0.105.51) give_up: a workshops level whose only missing pieces are
-- workshops (or furnaces) that waited on and on for their piece (R3: every
-- fort held 2-5 of its 5 slots with Millstones waiting >1000 days for a
-- millstone nobody made): the waiting ones are taken off (a planned one
-- holds what it already has, a mechanism) and the level finished
GIVE_UP_KINDS = {Workshop = true, Furnace = true}

-- (y2 W3) never taken off a level whatever the brain asks (the brain's
-- planner_slots.KEEP_KINDS): a well and its lid, and a way's pieces, which
-- often belong to another module (a shaft gate's lever, a cistern's floodgate)
KEEP_KINDS = {Well = true, Hatch = true, Trap = true, Lever = true, Floodgate = true, Door = true, Bridge = true,
              GrateWall = true, GrateFloor = true, BarsVertical = true, BarsFloor = true, Weapon = true,
              Support = true, SiegeEngine = true, AnimalTrap = true, GearAssembly = true, AxleHorizontal = true,
              AxleVertical = true, ScrewPump = true, WaterWheel = true, Windmill = true, Rollers = true}

-- (y2 W3) A test of whether building b is one the level placed itself: a floor
-- level's own room tiles (own_tile_test), else one of its own build cells
-- (cells.build, from its anchor) under b. nil when the level has no build cells
-- (an older record: everything in its area counts, as before).
function own_build_test(p)
    local mine = own_tile_test(p)
    if mine then return mine end
    local a = anchor_of(p)
    local cells = cells_of(p, 'build')
    if type(a) ~= 'table' or #cells == 0 then return nil end
    local pts = {}
    for _, c in ipairs(cells) do
        if type(c) == 'table' and math.tointeger(c.x) and math.tointeger(c.y) then
            table.insert(pts, {x = a.x + c.x, y = a.y + c.y})
        end
    end
    return function(b)
        for _, q in ipairs(pts) do
            if q.x >= b.x1 and q.x <= b.x2 and q.y >= b.y1 and q.y <= b.y2 then return true end
        end
        return false
    end
end

-- (R2 h3) kinds: the building kinds to take off (GIVE_UP_KINDS when nil): a parked
-- level's pieces nothing in the fort can make, or that never came in a year
-- (y2 W3) only pieces the level placed itself (own_build_test), never a KEEP_KINDS one
function drop_waiting_shops(p, kinds)
    local a, n = p.area, 0
    local list = {}
    local mine = own_build_test(p)      -- (layout B: its room tiles; else its own build cells)
    kinds = kinds or GIVE_UP_KINDS
    for _, b in ipairs(df.global.world.buildings.all) do
        local name = df.building_type[b:getType()] or ''
        if b.z == a.z and b.x1 >= a.x1 and b.x2 <= a.x2 and b.y1 >= a.y1 and b.y2 <= a.y2
                and (not mine or mine(b))
                and not b.flags.exists and kinds[name] and not KEEP_KINDS[name]
                and is_planned(b) then
            table.insert(list, b)
        end
    end
    for _, b in ipairs(list) do
        if pcall(dfhack.buildings.deconstruct, b) then n = n + 1 end
    end
    return n
end

-- (r2h7) leave_planned: the stuck sweep's give-up of a level furnishing for
-- months with pieces of any kind waiting: finished, its slot freed, the waiting
-- pieces left planned (with give_up too, the waiting workshops taken off first).
-- Not a well level. (R2 h3) drop: with give_up, building kinds (e.g. {'Bed','Box'})
-- that may be taken off besides the workshops (say which: `dropped_kinds`)
function finish_project(id, decor_only, stalled, give_up, drop, leave_planned)
    local data = load_projects()
    local p = find(data, id)
    -- (merge32) a dug way in finishes from its dig (nothing to furnish)
    if p and p.kind == 'way_in' and p.phase == 'dig' then
        p.phase = 'done'
        save_projects(data)
        return {ok = true, project_id = id, phase = 'done'}
    end
    if not p or p.phase ~= 'furnish' then
        return {ok = false, rejected = true, error = 'not a project being furnished'}
    end
    local f = furnish_progress(p)
    local kinds = GIVE_UP_KINDS
    local dropped_kinds
    if give_up and type(drop) == 'table' then
        kinds = {}
        for k in pairs(GIVE_UP_KINDS) do kinds[k] = true end
        for _, k in ipairs(drop) do
            -- (y2 W3) a KEEP_KINDS piece is never taken off: it stays waiting (refused below)
            if type(k) == 'string' and df.building_type[k] ~= nil and not KEEP_KINDS[k] then kinds[k] = true end
        end
    end
    local left, only_shops = false, true
    for name, n in pairs(f.waiting or {}) do
        if n > 0 and not (decor_only and DECOR_ONLY[name]) then left = true end
        if n > 0 and not kinds[name] then only_shops = false end
        if n > 0 and kinds[name] then
            dropped_kinds = dropped_kinds or {}
            table.insert(dropped_kinds, name)
        end
    end
    local dropped, kept
    if leave_planned and left and not (give_up and only_shops) then
        if p.kind == 'well' then
            return {ok = false, rejected = true, error = 'a well level is not given up while its well waits (the well rule orders its parts)'}
        end
        if give_up then
            local okd, n = pcall(drop_waiting_shops, p, kinds)
            dropped = okd and n or 0
        end
        kept = math.max(0, f.placed - f.done - (dropped or 0))
        -- falls through to finish
    elseif give_up and left and only_shops then
        local okd, n = pcall(drop_waiting_shops, p, kinds)
        dropped = okd and n or 0
        if dropped_kinds then table.sort(dropped_kinds) end
        -- falls through to finish
    elseif give_up then
        return {ok = false, rejected = true,
                error = left and (kinds == GIVE_UP_KINDS and 'pieces other than workshops still waiting'
                                  or 'pieces other than those named still waiting')
                        or 'no workshop waiting to give up'}
    -- (0.104.141) stalled: everything placed, nothing missing, buildings DF
    -- never finished (a 20-bed hospital at 30 of 31 for 134 days): finished,
    -- the slot freed; DF goes on building what is placed
    elseif stalled and not left and f.placed > 0 then
        -- falls through to finish
    elseif f.done < f.placed and (left or not decor_only) then
        return {ok = false, rejected = true, error = ('%d buildings still waiting'):format(f.placed - f.done)}
    end
    -- Engraving still to come: the project frees its slot but stays on the
    -- list until the walls are smooth enough to engrave.
    p.phase = #cells_of(p, 'engrave') > 0 and 'decorate' or 'done'
    if p.phase == 'decorate' then p.decorate_started = {year = now_tick() // 403200, tick = now_tick() % 403200} end
    save_projects(data)
    -- (0.105.47, I7b) and again once its coffins stand: every tomb takes the fort's dead
    local burial
    if p.kind == 'tombs' then
        pcall(function() burial = reqscript('ai-welfare').open_tombs(own_areas(p)).opened end)
    end
    -- (layout B) a floor level's pile rooms are booked for their shops (ai-builder-floorpiles.lua)
    if p.floor and type(floor_book_piles) == 'function' then pcall(floor_book_piles, p) end
    return {ok = true, project_id = id, phase = p.phase, burial = burial, dropped = dropped,
            dropped_kinds = dropped and dropped_kinds or nil,
            left_planned = kept}   -- (r2h7)
end

-- Smoothing finished -> engrave the halls (Quickfort only engraves smooth
-- stone, so anything not smoothed is skipped).
function engrave_project(id)
    local data = load_projects()
    local p = find(data, id)
    if not p or p.phase ~= 'decorate' then
        return {ok = false, rejected = true, error = 'not a project waiting to be engraved'}
    end
    local d = decor_progress(p)
    if d.smooth_waiting > 0 and not d.timed_out then
        return {ok = false, rejected = true, error = ('%d tiles still being smoothed'):format(d.smooth_waiting)}
    end
    local ok, s = pcall(quickfort_apply, 'dig', cells_of(p, 'engrave'), p.z, anchor_of(p).x, anchor_of(p).y)
    p.phase = 'done'
    save_projects(data)
    return {ok = true, project_id = id, engraved = ok and stat(s, 'dig_designated') or 0}
end

-- (r8) handed on to the ai-builder-projects files after this one (ai-builder-projects-founding)
PROJECTS_PART_LOCALS = {find = find}
