-- ai-builder-projects: the project lifecycle: projects saved with the fort, start, dig
-- progress, furnish, finish, engrave, cancel; founding; polish.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-projects'] = '0.105.32'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, ez = info, ez

---------------------------------------------------------------------------
-- Projects, saved with the fort
---------------------------------------------------------------------------

function load_projects()
    -- (0.105.33, L8) through ai-util's site_get: a value that isn't a table reads as none
    local data = site_get(PROJECTS_KEY)
    data.next_id = math.tointeger(data.next_id) or 1
    data.list = type(data.list) == 'table' and data.list or {}
    return data
end

OLD_AREAS_MAX = 600       -- (0.104.19) outlines of levels dropped from the list, kept for safety

function save_projects(data)
    -- keep every open project, and only the most recent closed ones;
    -- (0.104.19) a dropped level's outline is kept (`old_areas`): the quarry
    -- and vein mining stay out of every level the AI ever dug, not only the
    -- last 20 (Enxah: the quarry ate the walls of the older bedroom levels)
    local closed = 0
    data.old_areas = type(data.old_areas) == 'table' and data.old_areas or {}
    -- (0.105.33, industry 2) finished projects dropped from the list, so the
    -- report's done_total never stops at KEEP_CLOSED_PROJECTS; an older save
    -- starts from its dropped outlines (the closest count it has)
    data.dropped_done = math.tointeger(data.dropped_done) or #data.old_areas
    for i = #data.list, 1, -1 do
        local p = data.list[i]
        p.redug_changed = nil        -- (0.105.33) the report's own mark, not kept
        -- (0.104.152, review) a cavern well is never dropped: its shaft gate and
        -- stair lid are run from its project for as long as the well stands
        local cavern_well = p.kind == 'well' and (type(p.shaft_stairs) == 'table' or p.shaft_gate ~= nil)
        if p.phase ~= 'dig' and p.phase ~= 'furnish' and p.phase ~= 'decorate' and not cavern_well then
            closed = closed + 1
            if closed > KEEP_CLOSED_PROJECTS then
                for _, a in ipairs(project_areas(p)) do
                    table.insert(data.old_areas, {x1 = a.x1, y1 = a.y1, x2 = a.x2, y2 = a.y2, z = a.z})
                end
                if p.phase == 'done' then data.dropped_done = data.dropped_done + 1 end
                table.remove(data.list, i)
            end
        end
    end
    while #data.old_areas > OLD_AREAS_MAX do table.remove(data.old_areas, 1) end
    return site_put(PROJECTS_KEY, data)
end

-- (0.105.33, L4) The boxes a project keeps others out of: its level's area,
-- and (a way in) one box for each other level its column crosses.
function project_areas(p)
    local out = {}
    if type(p.area) == 'table' then table.insert(out, p.area) end
    for _, a in ipairs(type(p.areas) == 'table' and p.areas or {}) do
        if type(a) == 'table' then table.insert(out, a) end
    end
    return out
end

-- (0.105.33, industry 2) Every project ever finished: those still listed and
-- those dropped from the list since. Never saturates.
function done_total(data)
    local n = math.tointeger(data.dropped_done)
        or (type(data.old_areas) == 'table' and #data.old_areas or 0)
    for _, p in ipairs(data.list) do
        if p.phase == 'done' then n = n + 1 end
    end
    return n
end

-- (0.104.19) Every level the AI has dug or is digging: the open and recent
-- projects' areas and the outlines of older ones.
function level_areas()
    local data = load_projects()
    local out = {}
    for _, p in ipairs(data.list) do
        for _, a in ipairs(project_areas(p)) do table.insert(out, a) end
    end
    for _, a in ipairs(type(data.old_areas) == 'table' and data.old_areas or {}) do
        table.insert(out, a)
    end
    -- (0.105.23, 14.1 step 4c) the underground depot's road and hall, one box
    -- a level: the quarry and vein drifts keep out of its walls too
    local okd, deep = pcall(function() return deep_depot_data() end)
    if okd and deep and type(deep.tiles) == 'table' then
        local box = {}
        for _, t in ipairs(deep.tiles) do
            local b = box[t.z]
            if not b then b = {x1 = t.x, y1 = t.y, x2 = t.x, y2 = t.y, z = t.z}; box[t.z] = b end
            b.x1, b.y1 = math.min(b.x1, t.x), math.min(b.y1, t.y)
            b.x2, b.y2 = math.max(b.x2, t.x), math.max(b.y2, t.y)
        end
        for _, b in pairs(box) do table.insert(out, b) end
    end
    return out
end


-- Designate the stair extension: 'i' on the old bottom if it was an up-only
-- stair, 'i' on the levels between, 'u' on the new level.
local function stair_cells(stair, z)
    local cells = {}
    if stair.bottom_shape == 'STAIR_UP' then
        table.insert(cells, {z = stair.z_bottom, text = 'i'})
    end
    for zz = stair.z_bottom - 1, z + 1, -1 do table.insert(cells, {z = zz, text = 'i'}) end
    table.insert(cells, {z = z, text = 'u'})
    return cells
end

local function undo_dig(dig_cells, stairs, z, anchor, stair)
    pcall(quickfort_apply, 'dig', dig_cells, z, anchor.x, anchor.y, 'undo')
    for _, c in ipairs(stairs or {}) do
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.text}}, c.z, stair.x, stair.y, 'undo')
    end
end

-- The layout's dig cells plus the site's extra tiles (corridor, centre).
-- (0.104.128) an urgent level dug before the rest: Teacheroar's new hospital
-- sat at 0 of 175 tiles with 260 others waiting for 10 miners, all at the
-- default priority 4. Its tiles are designated one by one at this priority.
URGENT_DIG_PRIORITY = 2

function prioritized(cells, pri)
    local out = {}
    for _, c in ipairs(cells) do
        local w, h = 1, 1
        local ew, eh = tostring(c.text):match('^d%((%d+)x(%d+)%)$')
        if ew then w, h = tonumber(ew), tonumber(eh) end
        if ew or c.text == 'd' then
            for dx = 0, w - 1 do
                for dy = 0, h - 1 do table.insert(out, {x = c.x + dx, y = c.y + dy, text = 'd' .. pri}) end
            end
        else
            table.insert(out, c)
        end
    end
    return out
end

local function site_dig_cells(L, extra)
    local cells = {}
    for _, c in ipairs(L.dig) do table.insert(cells, c) end
    for x, col in pairs(extra) do
        for y in pairs(col) do table.insert(cells, {x = x, y = y, text = 'd'}) end
    end
    return cells
end

-- A fortified fort closes each new level off with a door where its corridor
-- leaves the existing fort (only when there is a new corridor to put it in).
-- The plan's doors can say otherwise: 'open' puts no door there, 'fortified'
-- puts one there and a second where the corridor meets the level (site.inner).
function entry_door(L, site, style)
    local build, furniture = {}, {}
    for _, c in ipairs(L.build) do table.insert(build, c) end
    for k, v in pairs(L.furniture) do furniture[k] = v end
    local want = type(style) == 'table' and style.entry_door
    if site.doors == 'open' then want = false end
    if site.doors == 'fortified' then want = true end
    local doors = {}
    if want and site.join then table.insert(doors, site.join) end
    if site.doors == 'fortified' and site.inner then table.insert(doors, site.inner) end
    for _, d in ipairs(doors) do
        table.insert(build, {x = d.x, y = d.y, text = 'd'})
        furniture.Door = (furniture.Door or 0) + 1
    end
    return build, furniture
end

-- Smoothing and engraving: only on this level's own new tiles and on rock
-- walls that were untouched natural rock when the site was checked (never on
-- the player's existing rooms), and never on floors where furniture or a
-- workshop will stand.
function decoration_cells(L, site, build)
    local a, z = site.anchor, site.z
    local covered = {}
    for _, c in ipairs(build) do
        local r = (#c.text >= 2 and c.text:sub(1, 1) == 'w') and 1 or 0   -- workshops are 3x3
        for dx = -r, r do
            for dy = -r, r do
                covered[(c.x + dx) .. ',' .. (c.y + dy)] = true
            end
        end
    end
    local function ours(x, y)
        return (L.tiles[x] and L.tiles[x][y]) or (site.extra[x] and site.extra[x][y])
    end
    local function keep(c)
        if covered[c.x .. ',' .. c.y] then return false end
        if ours(c.x, c.y) then return true end
        return natural_wall(info(a.x + c.x, a.y + c.y, z)) == true
    end
    local out = {smooth = {}, engrave = {}}
    for _, phase in ipairs({'smooth', 'engrave'}) do
        for _, c in ipairs(L[phase] or {}) do
            if keep(c) then table.insert(out[phase], c) end
        end
    end
    return out
end

-- params: kind + layout params (rooms, room_size, tables, piles, shops).
-- dry_run: find the site and check it with Quickfort, but change nothing.
function start_project(params, now, dry_run)
    OFFSET = elevation_offset()
    local kind = params.kind
    local L, err = layouts.make(kind, params)
    if not L then return {ok = false, rejected = true, error = err} end
    local data = load_projects()
    local open = open_projects(data)
    -- (a farm level gets one more slot: food comes before everything else)
    -- (urgent: what a well or a strange mood is waiting for; a dwarf's
    -- sanity or the fort's water doesn't wait for a bedroom level)
    -- (0.104.12) two urgent ones beyond the two (Enxah: soap for festering
    -- wounds and tombs for 35 dead both waited on one extra slot)
    if #open >= slot_cap(open) + (params.urgent == true and URGENT_EXTRA or (kind == 'farms' and 1 or 0)) then
        return {ok = false, rejected = true,
                error = ('already %d unfinished building projects'):format(#open)}
    end
    local stairs, why = find_stairs(STAIRS_TO_TRY)
    if not stairs then return {ok = false, error = why} end
    local reserved = {}
    for _, p in ipairs(open) do table.insert(reserved, p.area) end
    -- (0.105.22) nor where a level was given up as out of reach lately
    local banned = {}
    for _, p in ipairs(data.list) do
        if p.unreached and type(p.area) == 'table' and tonumber(p.cancelled_year)
                and df.global.cur_year - p.cancelled_year < UNREACHED_YEARS then
            table.insert(reserved, p.area)
            if type(p.stair) == 'table' and math.tointeger(p.stair.x) and math.tointeger(p.stair.y) then
                banned[math.tointeger(p.stair.x) * 100000 + math.tointeger(p.stair.y)] = true
            end
        end
    end
    -- (0.105.26) the area reserve holds on its own level only: B's stair
    -- column nobody reached was still offered at every other level. A stair
    -- a level was given up on as out of reach isn't used again, at any
    -- level, while no citizen can walk to it (its walk group isn't one of
    -- theirs; unknown counts as not reached)
    if next(banned) then
        stairs = unreached_stairs_dropped(stairs, banned)
        if #stairs == 0 then
            return {ok = false, error = 'every staircase near the dwarves leads only to levels given up as '
                                        .. 'out of reach (no citizen can walk to it)'}
        end
    end
    local plan = type(params.plan) == 'table' and params.plan or nil
    -- (0.105.23, 14.1 step 4c) max_elev: no level above it (the Deep mine keeps under the surface)
    local ceil = math.tointeger(params.max_elev)
    local site, why2 = choose_site(L, stairs, reserved, plan, ceil and (ceil - OFFSET) or nil)
    if not site then return {ok = false, error = why2} end

    -- Dry run: Quickfort must agree that every tile can be designated.
    local dig = site_dig_cells(L, site.extra)
    if params.urgent == true then dig = prioritized(dig, URGENT_DIG_PRIORITY) end   -- (0.104.128)
    local expected = count(L.tiles) + count(site.extra)
    local a, stair = site.anchor, site.stair
    local dry = quickfort_apply('dig', dig, site.z, a.x, a.y, 'run', true)
    if stat(dry, 'dig_designated') ~= expected or stat(dry, 'dig_invalid_tiles') > 0
            or stat(dry, 'out_of_bounds') > 0 or stat(dry, 'invalid_keys') > 0 then
        return {ok = false, error = ('dry run disagreed: %d of %d tiles designatable'):format(
            stat(dry, 'dig_designated'), expected)}
    end

    local stairs_cells = site.extend and stair_cells(stair, site.z) or {}
    local build, furniture = entry_door(L, site, params.style)
    local decor = decoration_cells(L, site, build)
    local where = {stair = {x = stair.x, y = stair.y, z_top = stair.z_top, z_bottom = stair.z_bottom,
                            elevation_top = ez(stair.z_top), elevation_bottom = ez(stair.z_bottom)},
                   anchor = a, corridor = site.corridor, new_corridor = site.new_corridor}
    if dry_run then
        return {ok = true, dry_run = true, kind = kind, z = site.z, elevation = ez(site.z),
                extends_stairs = site.extend, in_district = site.in_district,
                stair = where.stair, anchor = a, corridor = site.corridor, new_corridor = site.new_corridor,
                area = site.area, tiles = expected, summary = L.summary, furniture = furniture,
                decoration = {smooth = #decor.smooth, engrave = #decor.engrave}}
    end

    -- The level first, then the stairs; if anything goes wrong part-way,
    -- take back everything this call designated.
    local done, result = pcall(function()
        local real = quickfort_apply('dig', dig, site.z, a.x, a.y)
        local n = stat(real, 'dig_designated')
        for _, c in ipairs(stairs_cells) do
            local s = quickfort_apply('dig', {{x = 0, y = 0, text = c.text}}, c.z, stair.x, stair.y)
            if stat(s, 'dig_designated') ~= 1 then
                error(('could not designate the stairs on z%d'):format(ez(c.z)))
            end
        end
        return n
    end)
    if not done then
        undo_dig(dig, stairs_cells, site.z, a, stair)
        return {ok = false, error = 'designating failed and was undone: ' .. tostring(result)}
    end
    local p = {
        id = data.next_id, kind = kind, phase = 'dig',
        params = {rooms = params.rooms, room_size = params.room_size, tables = params.tables, beds = params.beds,
                  dormitory = params.dormitory,
                  piles = params.piles, shops = params.shops, size = params.size,
                  plots = params.plots, plot_w = params.plot_w,
                  name = params.name, style = params.style,
                  deity_hf = params.deity_hf, religion = params.religion, profession = params.profession},
        stair = {x = stair.x, y = stair.y}, anchor = {x = a.x, y = a.y},
        z = site.z, area = site.area, corridor = site.corridor, new_corridor = site.new_corridor,
        stairs = stairs_cells, summary = L.summary, furniture = furniture,
        -- the exact cells, so later steps never depend on regenerating the layout
        cells = {dig = dig, build = build, place = L.place, zone = L.zone,
                 smooth = decor.smooth, engrave = decor.engrave},
        started = now, designated = result,
        plan = plan, in_district = site.in_district,   -- the overseer's hint, and whether it was met
    }
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    local saved = save_projects(data)
    if not saved then
        undo_dig(dig, stairs_cells, site.z, a, stair)
        return {ok = false, error = 'could not save the project with the fort, so it was undone'}
    end
    return {ok = true, project_id = p.id, kind = kind, z = site.z, elevation = ez(site.z),
            extends_stairs = site.extend, in_district = site.in_district,
            stair = {x = stair.x, y = stair.y},
            anchor = a, corridor = site.corridor, new_corridor = site.new_corridor,   -- (0.105.33) Spacing
            tiles = expected, designated = result, summary = L.summary,
            warning = (result ~= expected) and ('only %d of %d tiles designated'):format(result, expected) or nil}
end

function cells_of(p, phase)
    return (type(p.cells) == 'table' and type(p.cells[phase]) == 'table') and p.cells[phase] or {}
end

-- How far the digging has got, and whether it's stuck.
REDIG_MAX = 3        -- (0.105.33, L4) times a lost shaft, stair or gallery tile is designated again

function dig_progress(p)
    local total, dug, stuck, marked, digging = 0, 0, 0, 0, 0
    local jobs = job_tiles()
    local waiting = {}             -- (0.104.110) what the tiles left wait on: up to 5, with their jobs
    -- (0.104.127) can a dwarf get beside a waiting tile? (Teacheroar: the new
    -- hospital 0 of 175 and a bedrooms level 0 of 89 for years, each one dig
    -- job with "no worker")
    local groups
    local function reach_words(x, y, z)
        if groups == nil then
            groups = {}
            pcall(function()
                for _, cp in ipairs(citizen_positions()) do
                    local g = dfhack.maps.getWalkableGroup(xyz2pos(cp.x, cp.y, cp.z))
                    if g and g ~= 0 then groups[g] = true end
                end
            end)
        end
        local seen_walk = false
        for dz = 0, 0 do                -- (a wall is dug from beside it, on its own level)
            for dy = -1, 1 do
                for dx = -1, 1 do
                    if dx ~= 0 or dy ~= 0 then
                        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x + dx, y + dy, z + dz))
                        if okg and g and g ~= 0 then
                            if groups[g] then return 'reachable' end
                            seen_walk = true
                        end
                    end
                end
            end
        end
        return seen_walk and 'beside ground the dwarves can\'t reach' or 'no open ground beside it'
    end
    -- (0.104.136) what DF cancels digging for: warm stone, damp stone (water or
    -- an aquifer beside it), a hidden tile (Teacheroar: two hospital levels began
    -- at x109 y40 z157 beside the cistern and neither was ever dug)
    local function risk_words(x, y, z)
        local out = {}
        local t = tile_info(x, y, z)
        if t and t.warm then table.insert(out, 'warm stone') end
        if t and t.hidden then table.insert(out, 'hidden') end
        if t and t.aquifer then table.insert(out, 'aquifer') end
        local wet = false
        for dz = -1, 1 do
            for dy = -1, 1 do
                for dx = -1, 1 do
                    local n = tile_info(x + dx, y + dy, z + dz)
                    if n and (n.liquid or n.aquifer) then wet = true end
                end
            end
        end
        if wet then table.insert(out, 'damp (water or an aquifer beside it)') end
        return out
    end
    local function check(x, y, z, done)
        total = total + 1
        local t = tile_info(x, y, z)
        if t and done(t) then
            dug = dug + 1
        elseif jobs[x .. ',' .. y .. ',' .. z] then
            digging = digging + 1  -- a dwarf is on it now
            if #waiting < 5 then
                local okr, rw = pcall(reach_words, x, y, z)
                local okk, risk = pcall(risk_words, x, y, z)
                table.insert(waiting, ('x%d y%d z%d: %s%s%s'):format(x, y, z, job_words(jobs[x .. ',' .. y .. ',' .. z]),
                                                                    okr and rw ~= 'reachable' and (', ' .. rw) or '',
                                                                    okk and #risk > 0 and (', ' .. table.concat(risk, ', ')) or ''))
            end
        elseif t and t.marked then
            marked = marked + 1    -- marker-only designation: nobody will dig it
        elseif t and not t.designated then
            stuck = stuck + 1      -- still wall, and not designated any more
        end
    end
    local not_wall = function(t) return t.shape ~= 'WALL' end
    if p.dig_done == 'open' then        -- a channel: done once the floor is gone
        not_wall = function(t) return t.shape ~= 'WALL' and t.shape ~= 'FLOOR' end
    end
    local anchor = anchor_of(p)
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do check(anchor.x + x, anchor.y + y, p.z, not_wall) end
    end
    for _, c in ipairs(p.stairs or {}) do
        local want = c.text == 'u' and 'STAIR_UP' or 'STAIR_UPDOWN'
        check(p.stair.x, p.stair.y, c.z, function(t) return t.shape == want end)
    end
    -- a cavern well's shaft: each rock level open (no wall, floor or ramp left)
    -- (0.104.13) and the stairs it is dug from. A shaft tile or stair the game
    -- dropped (a channel above turns the rock below it into a ramp) is
    -- designated again, so the shaft never stalls on a lost designation, and
    -- the well waits for every level of it.
    local open_shape = function(t) return t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP' end
    local pri = type(p.params) == 'table' and p.params.pri or ''
    local shaft_open, redug = true, 0
    -- (0.105.33, L4) each tile at most REDIG_MAX times (counted in the
    -- project): one the game (or the player) keeps taking off stays stuck,
    -- so the project can end instead of putting it back for ever
    local function keep(x, y, z, done, key)
        local before = stuck
        check(x, y, z, done)
        local t = tile_info(x, y, z)
        if not (t and done(t)) then shaft_open = false end
        local tk = x .. ',' .. y .. ',' .. z
        local times = type(p.redug) == 'table' and tonumber(p.redug[tk]) or 0
        if stuck > before and t and not t.marked and times < REDIG_MAX then
            local ok, s = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = key .. (pri or '')}}, z, x, y)
            if ok and stat(s, 'dig_designated') == 1 then
                stuck, redug = stuck - 1, redug + 1
            end
            if type(p.redug) ~= 'table' then p.redug = {} end
            p.redug[tk], p.redug_changed = times + 1, true
        end
    end
    -- (0.105.4 review) the shaft's last level (it opens into the cavern) and
    -- the stair step beside it are held undug until the shaft gate's lever
    -- stands and its hatch cover and mechanisms are in store: counted, never
    -- designated again here, and the shaft isn't open while they wait
    local held = type(p.held) == 'table' and p.held or nil
    local held_n = 0
    local function is_held(x, y, z)
        return held ~= nil and z == held.z and ((x == anchor.x and y == anchor.y)
            or (held.stair and x == held.stair.x and y == held.stair.y))
    end
    local function keep_or_hold(x, y, z, done, key)
        if is_held(x, y, z) then
            total, held_n, shaft_open = total + 1, held_n + 1, false
        else
            keep(x, y, z, done, key)
        end
    end
    for _, zk in ipairs(p.shaft or {}) do
        keep_or_hold(anchor.x, anchor.y, zk, open_shape, 'h')
    end
    for _, c in ipairs(p.shaft_stairs or {}) do
        local want = STAIR_SHAPES[c.key]
        keep_or_hold(c.x, c.y, c.z, function(t) return t.shape == want end, c.key)
    end
    -- (0.105.3) Hammerstirred: a gallery out to the shaft, each tile dug to a floor
    for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do
        keep(g.x, g.y, p.z, function(t) return t.shape ~= 'WALL' end, 'd')
    end
    local out = {total = total, dug = dug, stuck = stuck, marked = marked, digging = digging,
                 waiting = #waiting > 0 and waiting or nil}
    if p.shaft then out.shaft_open, out.redesignated = shaft_open, redug > 0 and redug or nil end
    if held_n > 0 then out.held = held_n end          -- (0.105.4 review)
    -- (0.105.31) a well's channel not dug: why
    if p.kind == 'well' and dug == 0 and total > 0 then
        local okw, w = pcall(well_dig_check, p, jobs)
        if okw and w then out.well_check = w end
        if p.renewed then out.renewed = p.renewed end
    end
    return out
end

-- Buildings inside the project's area: placed, built, and still waiting for
-- materials (only buildingplan's own "planned" list counts as waiting, so
-- furniture that already has its materials isn't ordered again).
function furnish_progress(p)
    local placed, done, waiting = 0, 0, {}
    local a = p.area
    for _, b in ipairs(df.global.world.buildings.all) do
        if b.z == a.z and b.x1 >= a.x1 and b.x2 <= a.x2 and b.y1 >= a.y1 and b.y2 <= a.y2 then
            local t = b:getType()
            if t ~= df.building_type.Stockpile and t ~= df.building_type.Civzone then
                placed = placed + 1
                -- 'exists' = actually built, not just planned
                if b.flags.exists then
                    done = done + 1
                elseif is_planned(b) then
                    local name = df.building_type[t] or tostring(t)
                    waiting[name] = (waiting[name] or 0) + 1
                end
            end
        end
    end
    return {placed = placed, done = done, waiting = waiting}
end

-- A {year, tick} date as ticks, or nil.
local function tick_of(d)
    return type(d) == 'table' and (tonumber(d.year) or 0) * 403200 + (tonumber(d.tick) or 0) or nil
end

-- (0.104.142) The open-project cap: the base, plus a slot for each level
-- furnishing FURNISH_LEND_DAYS or more (FURNISH_LEND_MAX at most).
function slot_cap(open)
    local lent = 0
    for _, p in ipairs(open or {}) do
        if p.phase == 'furnish' then
            local since = tick_of(p.furnish_started)
            if since and (now_tick() - since) // 1200 >= FURNISH_LEND_DAYS then lent = lent + 1 end
        end
    end
    return MAX_OPEN_PROJECTS + math.min(FURNISH_LEND_MAX, lent)
end

-- Smoothing progress: how many cells still have a smoothing job waiting.
function decor_progress(p)
    local a = anchor_of(p)
    local total, waiting, done, marked = 0, 0, 0, 0
    for _, c in ipairs(cells_of(p, 'smooth')) do
        total = total + 1
        local t = tile_info(a.x + c.x, a.y + c.y, p.z)
        if t and t.smoothing and t.marked then marked = marked + 1   -- marker mode: never dug
        elseif t and t.smoothing then waiting = waiting + 1
        elseif t and t.smoothed then done = done + 1 end
    end
    local since = tick_of(p.decorate_started)
    local days = since and math.max(0, (now_tick() - since) // 1200) or 0
    return {smooth_total = total, smooth_waiting = waiting, smooth_done = done, smooth_marked = marked,
            engrave_total = #cells_of(p, 'engrave'), days_waiting = days,
            timed_out = p.phase == 'decorate' and days >= DECOR_TIMEOUT_DAYS}
end

-- What the overseer should do next for this project, if anything.
local function next_step(p, r)
    -- (0.105.24) a well the game refused: tried again only after its wait
    if p.kind == 'well' and p.phase == 'dig' and tonumber(p.well_retry_at) and now_tick() < p.well_retry_at then
        return false
    end
    -- (merge32) an emergency way in has nothing to build: finished once dug
    if p.kind == 'way_in' and p.phase == 'dig' and r.dig and r.dig.total > 0 and r.dig.dug == r.dig.total then
        return 'finish'
    end
    -- (0.105.33, L4) a way in with a step missing is no way in: never
    -- furnished as if dug; once nothing else is left, it is given up
    if p.kind == 'way_in' then
        if p.phase == 'dig' and r.dig and r.dig.stuck > 0
                and r.dig.dug + r.dig.stuck + r.dig.marked == r.dig.total then
            return 'cancel'
        end
        return false
    end
    if p.phase == 'dig' and r.dig and r.dig.total > 0 and r.dig.dug == r.dig.total then
        return 'furnish'
    elseif p.phase == 'dig' and r.dig and r.dig.stuck > 0 and r.dig.shaft_open ~= false
            and r.dig.dug + r.dig.stuck + r.dig.marked == r.dig.total then
        -- Everything still designated is dug; the rest was cancelled (by the
        -- game, e.g. damp stone, or by the player). A few rock spots are
        -- fine: furnish what's there. Too many: give up on this site.
        return r.dig.stuck * 5 <= r.dig.total and 'furnish' or 'cancel'
    elseif p.phase == 'furnish' and r.furnish and r.furnish.done == r.furnish.placed then
        return 'finish'
    elseif p.phase == 'decorate' and r.decor and (r.decor.smooth_waiting == 0 or r.decor.timed_out) then
        return 'engrave'
    end
    return false      -- (false, not nil, so the key reaches Python)
end

-- Report section: every unfinished project. Projects that are only waiting
-- for decoration (engraving) are listed separately and don't use up a slot.
function projects_report()
    OFFSET = elevation_offset()
    local data = load_projects()
    local out, decorating, finished = {}, {}, 0
    local redug_seen = false
    for _, p in ipairs(data.list) do
        if p.phase == 'dig' or p.phase == 'furnish' or p.phase == 'decorate' then
            local r = {id = p.id, kind = p.kind, phase = p.phase, z = p.z, elevation = ez(p.z),
                       summary = p.summary, furniture = p.furniture, started = p.started}
            if p.phase == 'dig' then r.dig = dig_progress(p) end
            -- (0.92) a hall built for a petition: what it's dedicated to
            local pr = type(p.params) == 'table' and p.params or {}
            if pr.profession or pr.deity_hf or pr.religion then
                r.dedication = {profession = pr.profession, deity_hf = pr.deity_hf, religion = pr.religion}
            end
            if p.phase == 'furnish' then
                r.furnish = furnish_progress(p)
                local since = tick_of(p.furnish_started)
                r.furnish.days = since and math.max(0, (now_tick() - since) // 1200) or 0
            end
            if p.phase ~= 'dig' then r.decor = decor_progress(p) end
            -- (0.105.24) a well the game refused: how often, and what it showed
            if p.kind == 'well' and p.well_refusals then
                r.well_refused = {times = p.well_refusals, landing = p.landing,
                                  seen = type(p.well_diag) == 'table' and p.well_diag.text or nil}
            end
            r.next = next_step(p, r) or false
            if p.redug_changed then p.redug_changed, redug_seen = nil, true end
            table.insert(p.phase == 'decorate' and decorating or out, r)
        elseif p.phase == 'done' then
            finished = finished + 1
        end
    end
    -- (0.105.33, L4) the tiles the report designated again are counted with the fort
    if redug_seen then pcall(save_projects, data) end
    local okc, cap = pcall(slot_cap, open_projects(data))
    local okl, lids = pcall(well_lids, true, data)     -- (0.104.151)
    -- (0.105.33, industry 2) `finished` counts only the KEEP_CLOSED_PROJECTS
    -- kept closed ones (20 at most); done_total every level ever finished
    return {open = out, decorating = decorating, finished = finished, done_total = done_total(data),
            max_open = okc and cap or MAX_OPEN_PROJECTS,
            max_open_base = MAX_OPEN_PROJECTS, well_lids = (okl and #lids > 0) and lids or nil,
            well_lids_error = (not okl) and tostring(lids):sub(1, 120) or nil}
end

-- The box a project covers, in map coordinates: {x1, y1, x2, y2, z}, from
-- its dig cells (or its build cells if nothing was dug). nil if no cells.
function bounds_of(p)
    local a = anchor_of(p)
    if type(a) ~= 'table' or type(p.cells) ~= 'table' then return nil end
    local cells = type(p.cells.dig) == 'table' and p.cells.dig or {}
    if #cells == 0 then cells = type(p.cells.build) == 'table' and p.cells.build or {} end
    local x1, y1, x2, y2
    for _, c in ipairs(cells) do
        if type(c) == 'table' and type(c.x) == 'number' and type(c.y) == 'number' then
            x1 = math.min(x1 or c.x, c.x); x2 = math.max(x2 or c.x, c.x)
            y1 = math.min(y1 or c.y, c.y); y2 = math.max(y2 or c.y, c.y)
        end
    end
    if not x1 then return nil end
    return {x1 = a.x + x1, y1 = a.y + y1, x2 = a.x + x2, y2 = a.y + y2, z = p.z}
end

REGISTRY_MAX = 400

-- Report section: every AI project still on record (any phase), newest
-- last, for the overseer's map of what it built where.
function registry_report()
    OFFSET = elevation_offset()
    local list = load_projects().list
    local out = {}
    for i = math.max(1, #list - REGISTRY_MAX + 1), #list do
        local p = list[i]
        local params = type(p.params) == 'table' and p.params or {}
        local plan = type(p.plan) == 'table' and p.plan or {}
        table.insert(out, {id = p.id, kind = p.kind, phase = p.phase, z = p.z,
                           elevation = p.z and ez(p.z) or nil, bounds = bounds_of(p),
                           style = params.style, name = params.name, started = p.started,
                           district = plan.district, in_district = p.in_district})
    end
    return out
end

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
    if p.kind == 'temple' and (pr.deity_hf or pr.religion) and results.zone and results.zone ~= 0 then
        local okd, ded = pcall(dedicate_temple, p, pr)
        results.dedicated = okd and ded or ('failed: ' .. tostring(ded))
    end
    if p.kind == 'well' and results.build ~= 1 then
        return well_refused(data, p, results, qf_build)
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

function finish_project(id, decor_only, stalled)
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
    local left = false
    for name, n in pairs(f.waiting or {}) do
        if n > 0 and not (decor_only and DECOR_ONLY[name]) then left = true end
    end
    -- (0.104.141) stalled: everything placed, nothing missing, buildings DF
    -- never finished (a 20-bed hospital at 30 of 31 for 134 days): finished,
    -- the slot freed; DF goes on building what is placed
    if stalled and not left and f.placed > 0 then
        -- falls through to finish
    elseif f.done < f.placed and (left or not decor_only) then
        return {ok = false, rejected = true, error = ('%d buildings still waiting'):format(f.placed - f.done)}
    end
    -- Engraving still to come: the project frees its slot but stays on the
    -- list until the walls are smooth enough to engrave.
    p.phase = #cells_of(p, 'engrave') > 0 and 'decorate' or 'done'
    if p.phase == 'decorate' then p.decorate_started = {year = now_tick() // 403200, tick = now_tick() % 403200} end
    save_projects(data)
    return {ok = true, project_id = id, phase = p.phase}
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

-- Only while digging: removes dig designations on the project's own tiles
-- (dug tiles stay dug, stairs are never removed).
---------------------------------------------------------------------------
-- Founding (a fresh embark): the fort's first staircase. Every level the AI
-- digs grows from a staircase where the dwarves live, and a new embark has
-- none, so the first step is a stair shaft from a surface tile near the
-- wagon down into the ground: a down stair on the surface, up/down stairs
-- through the soil, an up stair on the first level of rock (or 3 levels down
-- when there's no rock near). Never into an aquifer, water, a cavern or warm
-- stone: the whole column is checked before anything is designated. After
-- that, the usual rules dig every level from it.
---------------------------------------------------------------------------

FOUND_RADIUS = 10        -- tiles from the wagon (or the dwarves) to look for the shaft (the builder
                         -- finds stairs within 10 of where the dwarves are)
FOUND_MAX_DEPTH = 8      -- levels the shaft may go down to reach rock
FOUND_SURFACE = {FLOOR = true, PEBBLES = true, SHRUB = true, BOULDER = false}

-- Where the dwarves' wagon stands (a fresh embark), else the middle of the
-- citizens on their busiest level. {x, y, z, what}
function found_center()
    local ok, w = pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.Wagon then
                return {x = b.centerx, y = b.centery, z = b.z, what = 'the wagon'}
            end
        end
    end)
    if ok and w then return w end
    local pos = citizen_positions()
    if #pos == 0 then return nil end
    local by_z = {}
    for _, p in ipairs(pos) do by_z[p.z] = (by_z[p.z] or 0) + 1 end
    local bz, bn = nil, -1
    for z, n in pairs(by_z) do if n > bn then bz, bn = z, n end end
    local xs, ys = {}, {}
    for _, p in ipairs(pos) do if p.z == bz then table.insert(xs, p.x); table.insert(ys, p.y) end end
    table.sort(xs); table.sort(ys)
    return {x = xs[(#xs + 1) // 2], y = ys[(#ys + 1) // 2], z = bz, what = 'the dwarves'}
end

-- The column under a surface tile: {depth to the first rock level, or nil}
-- or nil, why (aquifer, water, cavern, warm stone, open space, not natural).
function found_column(x, y, z)
    local rock
    for d = 1, FOUND_MAX_DEPTH do
        local t = tile_info(x, y, z - d)
        if not t then return nil, 'the map ends' end
        if t.aquifer then return nil, ('an aquifer %d level(s) down'):format(d) end
        if t.liquid then return nil, ('water or magma %d level(s) down'):format(d) end
        if t.feature then return nil, ('a cavern %d level(s) down'):format(d) end
        if t.warm then return nil, ('warm stone %d level(s) down'):format(d) end
        if t.shape ~= 'WALL' then return nil, ('open space %d level(s) down'):format(d) end
        if not NATURAL[t.material] then return nil, ('%s %d level(s) down'):format(tostring(t.material), d) end
        -- and around it: digging the stair opens its sides to anything beside
        for _, n in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
            local nt = tile_info(x + n[1], y + n[2], z - d)
            if nt and nt.aquifer then return nil, ('an aquifer beside it %d level(s) down'):format(d) end
            if nt and nt.liquid then return nil, ('water or magma beside it %d level(s) down'):format(d) end
            if nt and nt.feature then return nil, ('a cavern beside it %d level(s) down'):format(d) end
            -- (0.100, review) open space beside the shaft (a ravine, a river's
            -- channel): the shaft would open into it
            if nt and nt.shape ~= 'WALL' then return nil, ('open space beside it %d level(s) down'):format(d) end
        end
        if t.material ~= 'SOIL' and not rock then rock = d end
        if rock and d >= rock then break end
    end
    return {rock = rock}
end

function found_site()
    local c = found_center()
    if not c then return nil, 'no citizens and no wagon' end
    local best, best_score, why_not = nil, nil, {}
    local w, h = map_size()
    for r = 2, FOUND_RADIUS do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = c.x + dx, c.y + dy
                    local t = (x > 1 and y > 1 and x < w - 2 and y < h - 2) and tile_info(x, y, c.z) or nil
                    if t and FOUND_SURFACE[t.shape] and not t.liquid and not t.building and not t.designated then
                        local col, why = found_column(x, y, c.z)
                        if col then
                            -- near the wagon, and rock not far down
                            local score = r + (col.rock and col.rock * 2 or 20)
                            if not best_score or score < best_score then
                                best, best_score = {x = x, y = y, z = c.z, rock = col.rock}, score
                            end
                        elseif why then
                            why_not[why:gsub('%d+ level%(s%) down', 'below')] = true
                        end
                    end
                end
            end
        end
        if best and r >= 6 then break end          -- (looked far enough for a good one)
    end
    if not best then
        local list = {}
        for k in pairs(why_not) do table.insert(list, k) end
        table.sort(list)
        return nil, ('no tile within %d of %s with solid, dry ground under it%s'):format(
            FOUND_RADIUS, c.what, #list > 0 and (' (found: ' .. table.concat(list, ', ') .. ')') or '')
    end
    best.near = c.what
    return best
end

-- A down stair on the founding level near the wagon or the dwarves (one the
-- AI dug, or yours), even if the dwarves have wandered from it.
function stair_near_center()
    local c = found_center()
    if not c then return nil end
    for dx = -FOUND_RADIUS, FOUND_RADIUS do
        for dy = -FOUND_RADIUS, FOUND_RADIUS do
            local sh = stair_shape(c.x + dx, c.y + dy, c.z)
            if sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN' then return {x = c.x + dx, y = c.y + dy, z = c.z} end
        end
    end
    return nil
end

FOUNDED_KEY = 'ai-overseer/founded'     -- where the AI laid out the first staircase (in the save)

local function founded_site()
    local ok, f = pcall(dfhack.persistent.getSiteData, FOUNDED_KEY, nil)
    return ok and type(f) == 'table' and tonumber(f.x) and f or nil
end

function has_staircase()
    if find_stairs(1) ~= nil or stair_near_center() ~= nil then return true end
    -- the AI's own first shaft, wherever the dwarves have gone since
    local f = founded_site()
    if f then
        local sh = stair_shape(f.x, f.y, f.z)
        return sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN'
    end
    return false
end

function found_fort(dry_run)
    if has_staircase() then return {ok = false, rejected = true, error = 'the fort already has a staircase'} end
    -- a shaft already designated (by the AI earlier, or by you) that the miners
    -- haven't dug yet: wait for it rather than start a second
    local f = founded_site()
    if f then
        local t = tile_info(f.x, f.y, f.z)
        if t and (t.designated or (t.shape or ''):find('^STAIR')) then
            return {ok = false, rejected = true, waiting = true,
                    error = ('the first staircase at x%d y%d is being dug; waiting for the miners'):format(f.x, f.y)}
        end
    end
    local c = found_center()
    if c then
        for dx = -FOUND_RADIUS, FOUND_RADIUS do
            for dy = -FOUND_RADIUS, FOUND_RADIUS do
                local t = tile_info(c.x + dx, c.y + dy, c.z)
                local below = t and t.designated and tile_info(c.x + dx, c.y + dy, c.z - 1)
                if below and below.designated then
                    return {ok = false, rejected = true, waiting = true,
                            error = ('a staircase is designated at x%d y%d; waiting for the miners to dig it'):format(
                                c.x + dx, c.y + dy)}
                end
            end
        end
    end
    local site, why = found_site()
    if not site then return {ok = false, error = why} end
    local depth = site.rock or 3
    local cells = {{z = site.z, text = 'j'}}
    for d = 1, depth - 1 do table.insert(cells, {z = site.z - d, text = 'i'}) end
    table.insert(cells, {z = site.z - depth, text = 'u'})
    local out = {ok = true, x = site.x, y = site.y, z = site.z, elevation = ez(site.z), levels = depth,
                 rock = site.rock ~= nil, near = site.near}
    if dry_run then out.dry_run = true return out end
    local done, err = pcall(function()
        for _, c in ipairs(cells) do
            local st = quickfort_apply('dig', {{x = 0, y = 0, text = c.text}}, c.z, site.x, site.y)
            if stat(st, 'dig_designated') ~= 1 then error(('could not designate the stair on z%d'):format(ez(c.z))) end
        end
    end)
    if not done then
        for _, c in ipairs(cells) do
            pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.text}}, c.z, site.x, site.y, 'undo')
        end
        return {ok = false, error = 'designating the first stair failed and was undone: ' .. tostring(err)}
    end
    site_put(FOUNDED_KEY, {x = site.x, y = site.y, z = site.z})
    return out
end

-- (0.105.22) `unreached`: given up because no dwarf got to dig it (B, 3-5
-- Nov: a tomb level placed 11 times on the same stair column nobody could
-- reach, given up after 336 days each time): its area is kept off-limits to
-- new levels for UNREACHED_YEARS
UNREACHED_YEARS = 5

-- (0.105.26) The staircases less those in `banned` (x * 100000 + y: the stair
-- of a level given up as out of reach) that no citizen can walk to: none of
-- the column's tiles is in a walk group a citizen stands in. When the walk
-- groups can't be read, a banned stair counts as not reached.
function unreached_stairs_dropped(stairs, banned)
    local groups
    local okp, pos = pcall(citizen_positions)
    if okp and type(pos) == 'table' then
        groups = {}
        for _, cp in ipairs(pos) do
            local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(cp.x, cp.y, cp.z))
            if not okg then groups = nil break end
            if g and g ~= 0 then groups[g] = true end
        end
    end
    local function reached(st)
        if not groups then return false end
        local zb, zt = math.tointeger(st.z_bottom) or st.z, math.tointeger(st.z_top) or st.z
        if not zb or not zt then return false end
        for z = zb, zt do
            local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(st.x, st.y, z))
            if okg and g and g ~= 0 and groups[g] then return true end
        end
        return false
    end
    local kept = {}
    for _, st in ipairs(stairs) do
        if not (banned[st.x * 100000 + st.y] and not reached(st)) then table.insert(kept, st) end
    end
    return kept
end

function cancel_project(id, unreached)
    local data = load_projects()
    local p = find(data, id)
    if not p then return {ok = false, rejected = true, error = 'no such AI project'} end
    if p.phase ~= 'dig' then
        return {ok = false, rejected = true, error = 'only projects still being dug can be cancelled'}
    end
    undo_dig(cells_of(p, 'dig'), p.stairs, p.z, anchor_of(p), p.stair)
    -- (0.105.33, L4) and what dig_progress keeps designated: a well's shaft,
    -- the stairs it is dug from and its gallery, a way in's column and tunnel
    local pri = type(p.params) == 'table' and p.params.pri or ''
    local function undo_one(x, y, z, key)
        pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = key .. pri}}, z, x, y, 'undo')
    end
    local a = anchor_of(p)
    -- (0.105.33 merge) a well's own undo (ai-builder-wells.lua undo_well_cells),
    -- one place for what a well designates beyond cells.dig
    if p.kind == 'well' and type(undo_well_cells) == 'function' and type(a) == 'table'
            and pcall(undo_well_cells, p) then
        -- done
    else
        for _, zk in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
            if type(a) == 'table' then undo_one(a.x, a.y, zk, 'h') end
        end
        for _, c in ipairs(type(p.shaft_stairs) == 'table' and p.shaft_stairs or {}) do
            undo_one(c.x, c.y, c.z, c.key)
        end
        for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do undo_one(g.x, g.y, p.z, 'd') end
    end
    p.phase = 'cancelled'
    if unreached then
        p.unreached = true
        p.cancelled_year = df.global.cur_year
    end
    save_projects(data)
    return {ok = true, project_id = id}
end

---------------------------------------------------------------------------
-- (0.105.32, wayin) An emergency way in: E (8 Nov) lost 64 dwarves to
-- thirst outside a hatch that read open while DF's walk map was split at it,
-- and the brain could only ask the player to "dig or build them a way in".
-- dig_way_in digs one: a 1-wide stair column from a floor of the fort's
-- inside (near its top) up (or down) through solid ground to open ground in
-- the stranded dwarves' walk group, a short tunnel on the fort's level when
-- the column can't stand right beside the fort. Never through water, magma,
-- a cavern, an aquifer, warm stone, a building or another AI project, nor
-- beside open water or a cavern; at least WAY_IN_GATE_APART tiles from the
-- existing entrance's gate pieces; WAY_IN_MAX_DIG tiles of digging at most.
-- A project of kind 'way_in' (emergency = true: no hatch now; the gate scan
-- sees a new surface entrance and may fortify it later like any other).
---------------------------------------------------------------------------

WAY_IN_MAX_DIG = 30       -- tiles of digging, the column and its tunnel
WAY_IN_GATE_APART = 6     -- tiles (across) from every piece of the existing gates
WAY_IN_GATE_CLEAR = 3     -- and its tunnel, and the fort tile it opens on, this far (not into the gate's own shaft)
WAY_IN_RADIUS = 12        -- columns tried this far (across) from the stranded spot and the nearest inside tile
WAY_IN_TUNNEL = 8         -- longest tunnel on the fort's level to the column
WAY_IN_ZSPAN = 8          -- the stranded ground's end of the column: this many levels up or down
WAY_IN_PRIORITY = '1'     -- dig priority: they are dying of thirst out there
WAY_IN_SECONDS = 2        -- the search stops here
WAY_IN_INVADER_NEAR = 30  -- (merge32 review) no way in dug with an invader in sight this near its ends
WAY_IN_TRIES = 3          -- (0.105.33, L4) searches, each without the columns quickfort refused

-- (0.105.33, secondway) a second way to the surface by design: the same digger,
-- from open ground under the sky this far (across) from the existing entrance
WAY_IN_SECOND_MIN = 15
WAY_IN_SECOND_MAX = 40
WAY_IN_SECOND_PRIORITY = '4'   -- nobody is dying: the ordinary dig priority
WAY_IN_SECOND_CENTERS = 4      -- surface spots searched round (the best first)

local WAY_IN_SIDES = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
WAY_IN_NO_GROUND = 'no open ground of theirs to come up (or down) to'

-- (tests replace this) the gate scan's module, or nil
function way_in_gates()
    local ok, G = pcall(reqscript, 'ai-gates')
    return ok and type(G) == 'table' and G or nil
end

local function wkey(x, y, z) return (z * 4096 + y) * 4096 + x end   -- (ai-gates' key)

-- The fort's side: {group, set (the scan's inside, or nil), pieces = {{x1, y1, x2, y2}},
-- anchors = {{x, y, z}}: the founding stair or main stair}, or nil, why.
function way_in_fort()
    local out = {pieces = {}, anchors = {}}
    local G = way_in_gates()
    local GT = G and G.GATES
    if type(GT) == 'table' and GT.scanned and type(GT.inside) == 'table' then
        out.set = GT.inside
        local okf, fi = pcall(function() return G.fort_interior() end)
        if okf and type(fi) == 'table' and math.tointeger(fi.group) and fi.group ~= 0 then
            out.group = fi.group
            -- (0.105.33, L4) 'citizens inside' gives a group and no tile: no anchor
            if math.tointeger(fi.x) and math.tointeger(fi.y) and math.tointeger(fi.z) then
                table.insert(out.anchors, {x = fi.x, y = fi.y, z = fi.z})
            end
        end
        for _, e in ipairs(type(GT.entrances) == 'table' and GT.entrances or {}) do
            if math.tointeger(e.x) then table.insert(out.pieces, {x1 = e.x, y1 = e.y, x2 = e.x, y2 = e.y}) end
            for _, b in ipairs(type(e.equipment) == 'table' and e.equipment or {}) do
                local x1, y1 = math.tointeger(b.x1 or b.x), math.tointeger(b.y1 or b.y)
                if x1 and y1 then
                    table.insert(out.pieces, {x1 = x1, y1 = y1, x2 = math.tointeger(b.x2) or x1,
                                              y2 = math.tointeger(b.y2) or y1})
                end
            end
            for _, s in ipairs(type(e.split) == 'table' and e.split or {}) do
                if math.tointeger(s.x) then table.insert(out.pieces, {x1 = s.x, y1 = s.y, x2 = s.x, y2 = s.y}) end
            end
        end
    end
    -- else the walk group of the founding stair (or the main stair)
    local f = founded_site()
    if f and math.tointeger(f.x) and math.tointeger(f.y) and math.tointeger(f.z) then
        table.insert(out.pieces, {x1 = f.x, y1 = f.y, x2 = f.x, y2 = f.y})
        if not out.group then
            local g = walk_group(f.x, f.y, f.z - 1)
            if g ~= 0 then out.group = g; table.insert(out.anchors, {x = f.x, y = f.y, z = f.z - 1}) end
        end
    end
    if not out.group then
        local oks, stairs = pcall(find_stairs, 1)
        local s = oks and type(stairs) == 'table' and stairs[1] or nil
        if s then
            local g = walk_group(s.x, s.y, s.z_bottom)
            if g ~= 0 then out.group = g; table.insert(out.anchors, {x = s.x, y = s.y, z = s.z_bottom}) end
        end
    end
    if not out.group then return nil, 'no fort to dig from (no gate scan, founding stair or main stair found)' end
    return out
end

-- A tile of the fort's inside a dwarf can stand on.
local function way_in_inside(fort, memo, x, y, z)
    local k = wkey(x, y, z)
    local v = memo[k]
    if v ~= nil then return v end
    v = false
    if not fort.set or fort.set[k] then
        local t = info(x, y, z)
        v = t ~= nil and t.shape ~= 'WALL' and not t.outside and not t.feature and not t.liquid
            and walk_group(x, y, z) == fort.group
    end
    memo[k] = v
    return v
end

-- Open ground of the stranded group under the sky, fit to step off a stair onto (not
-- the deep depot's road or hall, which share their walk group: E's group A).
local function way_in_ground(t, x, y, z, target)
    return t ~= nil and t.shape == 'FLOOR' and t.outside and not t.liquid and not t.feature
        and walk_group(x, y, z) == target
end

-- plan = {x, y, cells = {{x, y, z, key}} (the column), tunnel = {{x, y}}, z_fort, from, to, tiles}
-- or nil, why. The column at (cx, cy); fort_below: the fort is under the stranded ground.
local function way_in_column(ctx, cx, cy, fort_below)
    local sz, target = ctx.z, ctx.target
    -- the stranded ground's end: the first level (from the far side) where it can be reached
    local top, top_key, out_tile, first
    local zs, ze, step = sz + WAY_IN_ZSPAN, sz - WAY_IN_ZSPAN, -1
    if not fort_below then zs, ze, step = sz - WAY_IN_ZSPAN, sz + WAY_IN_ZSPAN, 1 end
    local why = WAY_IN_NO_GROUND
    for z = zs, ze, step do
        local t = info(cx, cy, z)
        -- (0.105.33, L4) the top 'j' goes into natural ground: quickfort
        -- won't dig one into a built floor
        if fort_below and way_in_ground(t, cx, cy, z, target) and NATURAL[t.material] and not t.designated
                and not t.building and not building_at(cx, cy, z) then
            local ok, w = ctx.safe(cx, cy, z - 1)
            local okn, wn = ctx.dry_beside(cx, cy, z)
            if ok and okn then top, top_key, out_tile, first = z, 'j', {x = cx, y = cy, z = z}, z - 1 break end
            why = (not ok) and w or wn
        elseif t and t.shape == 'WALL' then
            for _, s in ipairs(WAY_IN_SIDES) do
                local nx, ny = cx + s[1], cy + s[2]
                if way_in_ground(info(nx, ny, z), nx, ny, z, target) then
                    local ok, w = ctx.safe(cx, cy, z)
                    if ok then
                        top, top_key, out_tile, first = z, fort_below and 'j' or 'u', {x = nx, y = ny, z = z}, z
                    else
                        why = w
                    end
                    break
                end
            end
            if top then break end
        end
    end
    if not top then return nil, why end
    -- then toward the fort, a level at a time, until a level joins it
    local cells = {}
    if top_key == 'j' and first ~= top then table.insert(cells, {x = cx, y = cy, z = top, key = 'j'}) end
    local dz = fort_below and -1 or 1
    local z = first
    while true do
        local n = #cells + 1
        if n > WAY_IN_MAX_DIG or n >= ctx.best_cost then
            return nil, ('more than %d tiles of digging'):format(math.min(WAY_IN_MAX_DIG, ctx.best_cost - 1)), true
        end
        local ok, w = ctx.safe(cx, cy, z)
        if not ok then return nil, w end
        table.insert(cells, {x = cx, y = cy, z = z, key = (z == top) and top_key or 'i'})
        if z ~= top and ctx.near(z, cx, cy) then
            local budget = math.min(WAY_IN_TUNNEL, WAY_IN_MAX_DIG - #cells, ctx.best_cost - 1 - #cells)
            local tunnel, from = ctx.tunnel(cx, cy, z, budget)
            if tunnel then
                cells[#cells].key = fort_below and 'u' or 'j'
                return {x = cx, y = cy, cells = cells, tunnel = tunnel, z_fort = z, from = from, to = out_tile,
                        tiles = #cells + #tunnel}
            end
        end
        z = z + dz
        if math.abs(z - top) > WAY_IN_MAX_DIG then return nil, 'no fort level within reach' end
    end
end

-- (0.105.33) Open ground under the sky (not a building, not dug, not a cavern
-- or water) a stair can come up to.
local function way_in_sky(t)
    return t ~= nil and t.shape == 'FLOOR' and t.outside and not t.subterranean and not t.hidden
        and not t.liquid and not t.feature and not t.building and not t.designated
end

-- (0.105.33) The second way in's surface end: the fort's one surface entrance
-- (the gate scan's) and the surface spots 15-40 tiles from it in the outside
-- walk group, best first (over the fort's inside, then nearer the entrance).
-- Returns {entrance = {x, y, z}, group, spots = {{x, y, z}}} or nil, why.
function way_in_second_spots(fort, GM, deadline_all)
    local GT = GM and GM.GATES
    if not (type(GT) == 'table' and GT.scanned and type(GT.entrances) == 'table') then
        return nil, 'the entrances are not mapped yet (scan them first)'
    end
    local surf = {}
    for _, e in ipairs(GT.entrances) do
        if e.kind == 'surface' and math.tointeger(e.x) then table.insert(surf, e) end
    end
    if #surf == 0 then return nil, 'the fort has no surface entrance to keep the new one apart from' end
    if #surf > 1 then
        return nil, ('the fort already has %d ways to the surface: no second one is needed'):format(#surf)
    end
    local e = surf[1]
    -- the outside walk group: the entrance's outside tiles (or the ground over it)
    local group = 0
    for k in pairs(type(e.outs) == 'table' and e.outs or {}) do
        local kk = math.tointeger(k)
        if kk then
            local g = walk_group(kk % 4096, (kk // 4096) % 4096, kk // (4096 * 4096))
            if g ~= 0 then group = g break end
        end
    end
    if group == 0 then
        for dz = 1, 2 do
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local t = info(e.x + dx, e.y + dy, e.z + dz)
                    if group == 0 and t and t.outside and t.shape ~= 'WALL' and t.shape ~= 'EMPTY' then
                        group = walk_group(e.x + dx, e.y + dy, e.z + dz)
                    end
                end
            end
        end
    end
    if group == 0 then return nil, 'no outside ground found at the entrance' end
    local W, H = map_size()
    local R = WAY_IN_SECOND_MAX
    local bx1, by1 = math.max(2, e.x - R), math.max(2, e.y - R)
    local bx2, by2 = math.min(W - 3, e.x + R), math.min(H - 3, e.y + R)
    -- how far (across) each column is from the fort's inside: a distance map from
    -- the inside's columns, over the box
    local dist, queue, head = {}, {}, 1
    local function ck(x, y) return y * 4096 + x end
    if fort.set then
        for k in pairs(fort.set) do
            local x, y = k % 4096, (k // 4096) % 4096
            if x >= bx1 and x <= bx2 and y >= by1 and y <= by2 and not dist[ck(x, y)] then
                dist[ck(x, y)] = 0
                table.insert(queue, {x, y})
            end
        end
        while head <= #queue do
            local c = queue[head]
            head = head + 1
            local d = dist[ck(c[1], c[2])] + 1
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local nx, ny = c[1] + dx, c[2] + dy
                    if nx >= bx1 and nx <= bx2 and ny >= by1 and ny <= by2 and not dist[ck(nx, ny)] then
                        dist[ck(nx, ny)] = d
                        table.insert(queue, {nx, ny})
                    end
                end
            end
        end
    end
    local zs = {0}
    for i = 1, WAY_IN_ZSPAN do table.insert(zs, i); table.insert(zs, -i) end
    local spots = {}
    local deadline = math.min(os.clock() + WAY_IN_SECONDS, deadline_all or math.huge)
    for x = bx1, bx2 do
        if os.clock() > deadline then break end
        for y = by1, by2 do
            local de = math.max(math.abs(x - e.x), math.abs(y - e.y))
            if de >= WAY_IN_SECOND_MIN and de <= WAY_IN_SECOND_MAX and (x + y) % 2 == 0 then
                for _, dz in ipairs(zs) do
                    local z = e.z + 1 + dz
                    local t = info(x, y, z)
                    -- (fix33) not on the fort's inside (a walled courtyard the
                    -- scan counts in): the top there is no second way out
                    if way_in_sky(t) and not (fort.set and fort.set[wkey(x, y, z)])
                            and walk_group(x, y, z) == group and not building_at(x, y, z) then
                        local di = dist[ck(x, y)] or 999
                        table.insert(spots, {x = x, y = y, z = z, rank = di * 1000 + de})
                        break
                    end
                end
            end
        end
    end
    if #spots == 0 then
        return nil, ('no open ground under the sky %d-%d tiles from the entrance'):format(WAY_IN_SECOND_MIN, WAY_IN_SECOND_MAX)
    end
    table.sort(spots, function(a, b)
        if a.rank ~= b.rank then return a.rank < b.rank end
        if a.x ~= b.x then return a.x < b.x end
        return a.y < b.y
    end)
    -- the best few, apart from each other (round different sides of the fort)
    local picked = {}
    for _, sp in ipairs(spots) do
        local apart = true
        for _, q in ipairs(picked) do
            if math.max(math.abs(q.x - sp.x), math.abs(q.y - sp.y)) < 2 * WAY_IN_RADIUS then apart = false break end
        end
        if apart then table.insert(picked, sp) end
        if #picked >= WAY_IN_SECOND_CENTERS then break end
    end
    return {entrance = {x = e.x, y = e.y, z = e.z}, group = group, spots = picked}
end

-- dig_way_in{x, y, z}: the stranded spot (map coordinates). (0.105.33)
-- dig_way_in{second = true}: no stranded spot; a second way to the surface,
-- its top 15-40 tiles from the fort's one surface entrance. Returns
-- {ok, project_id, from, to, tiles, levels, column, tunnel, dry_run} or
-- {ok = false, rejected = true, error = why, why = why}.
function dig_way_in(params, now, dry_run)
    OFFSET = elevation_offset()
    CACHE = {}
    local ok, r = pcall(function() return way_in_plan_and_dig(params, now, dry_run) end)
    CACHE = nil
    if not ok then return {ok = false, error = 'the way-in search failed: ' .. tostring(r):sub(1, 160)} end
    return r
end

local function refuse(why) return {ok = false, rejected = true, error = why, why = why} end

local function pos_out(p)
    return p and {x = p.x, y = p.y, z = p.z, elevation = ez(p.z)} or nil
end

function way_in_plan_and_dig(params, now, dry_run)
    local second = params.second == true
    local sx, sy, sz = math.tointeger(params.x), math.tointeger(params.y), math.tointeger(params.z)
    if not second and (not sx or not sy or not sz) then return refuse('dig_way_in needs x, y, z') end
    local W, H, D = map_size()
    if not second and (sx < 0 or sy < 0 or sx >= W or sy >= H or sz < 0 or (D and sz >= D)) then
        return refuse('that spot is off the map')
    end
    local data = load_projects()
    -- (fix33) the second way to the surface never holds the emergency way in
    -- for dwarves cut off (the two dig side by side; reserved keeps them apart)
    for _, p in ipairs(data.list) do
        if p.kind == 'way_in' and p.phase == 'dig' and (second or not p.second) then
            return refuse(('a way in is already being dug (project %d)'):format(p.id))
        end
    end
    -- (fix33) one deadline for the whole search (the second way's spot scan
    -- and every column search): the game's freeze stays short
    local deadline_all = os.clock() + WAY_IN_SECONDS * WAY_IN_TRIES
    -- (merge32 review) not during a siege: a new hole in the fort while the
    -- gate watcher has it shut lets the enemy in by it
    local GM = way_in_gates()
    if GM and type(GM.GATES) == 'table' and GM.GATES.armed then
        return refuse('the gate watcher is armed (enemies about): no new way in is dug until the alarm is over')
    end
    local target, extra_centers, second_e, fort0
    if second then
        local fwhy0
        fort0, fwhy0 = way_in_fort()
        if not fort0 then return refuse(fwhy0) end
        local pick, pwhy = way_in_second_spots(fort0, GM, deadline_all)
        if not pick then return refuse(pwhy) end
        target, second_e = pick.group, pick.entrance
        sx, sy, sz = pick.spots[1].x, pick.spots[1].y, pick.spots[1].z
        extra_centers = {}
        for i = 2, #pick.spots do table.insert(extra_centers, {x = pick.spots[i].x, y = pick.spots[i].y}) end
    else
        local here = info(sx, sy, sz)
        target = walk_group(sx, sy, sz)
        if not here or target == 0 then
            return refuse(('nobody can stand at x%d y%d z%d (no walkable ground there)'):format(sx, sy, ez(sz)))
        end
        if here.feature then
            return refuse('that spot is in a cavern: no way in is dug from a cavern (it would open the fort to it)')
        end
    end
    local fort, fwhy = fort0, nil
    if not fort then fort, fwhy = way_in_fort() end
    if not fort then return refuse(fwhy) end
    if not second and target == fort.group then
        return refuse('that spot already joins the fort\'s inside (the same walk group): no way in is needed')
    end
    -- (0.105.33) the second way's top: 15-40 tiles (across) from the entrance
    local function in_band(x, y)
        if not second_e then return true end
        local d = math.max(math.abs(x - second_e.x), math.abs(y - second_e.y))
        return d >= WAY_IN_SECOND_MIN and d <= WAY_IN_SECOND_MAX
    end
    -- the AI's other projects, by level
    local areas = {}
    local oka, list = pcall(level_areas)
    for _, a in ipairs(oka and list or {}) do
        if type(a) == 'table' and math.tointeger(a.z) then
            areas[a.z] = areas[a.z] or {}
            table.insert(areas[a.z], a)
        end
    end
    local function reserved(x, y, z)
        for _, a in ipairs(areas[z] or {}) do
            if x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 then return true end
        end
        return false
    end
    local function gate_dist(x, y)
        local d = math.huge
        for _, p in ipairs(fort.pieces) do
            local dx = (x < p.x1) and (p.x1 - x) or ((x > p.x2) and (x - p.x2) or 0)
            local dy = (y < p.y1) and (p.y1 - y) or ((y > p.y2) and (y - p.y2) or 0)
            d = math.min(d, math.max(dx, dy))
        end
        return d
    end
    local memo_in = {}
    local function inside(x, y, z) return way_in_inside(fort, memo_in, x, y, z) end
    -- no open water, magma, aquifer or cavern beside (and over, under) a dug tile
    local function wet(x, y, z)
        for dz = -1, 1 do
            for dx = -1, 1 do
                for dy = -1, 1 do
                    if (dx ~= 0 or dy ~= 0 or dz ~= 0) and (dz == 0 or (dx == 0 and dy == 0)) then
                        local n = info(x + dx, y + dy, z + dz)
                        if n and n.liquid then return ('water or magma beside x%d y%d z%d'):format(x, y, ez(z)) end
                        if n and n.feature then return ('a cavern beside x%d y%d z%d'):format(x, y, ez(z)) end
                        if n and n.aquifer then return ('an aquifer beside x%d y%d z%d'):format(x, y, ez(z)) end
                    end
                end
            end
        end
    end
    local memo_safe = {}
    local function safe(x, y, z)
        local k = wkey(x, y, z)
        local v = memo_safe[k]
        if v == nil then
            local okw, w = natural_wall(info(x, y, z))
            if okw and reserved(x, y, z) then okw, w = false, 'another AI project' end
            if okw then
                local wt = wet(x, y, z)
                if wt then okw, w = false, wt end
            elseif w then
                w = ('%s at x%d y%d z%d'):format(w, x, y, ez(z))
            end
            v = okw and true or w
            memo_safe[k] = v
        end
        if v == true then return true end
        return false, v
    end
    local function dry_beside(x, y, z)
        if reserved(x, y, z) then return false, 'another AI project' end
        local wt = wet(x, y, z)
        if wt then return false, wt end
        return true
    end
    -- where to look: around the stranded spot and around the fort's inside tile nearest it
    local centers = {{x = sx, y = sy}}
    local best_in, best_d
    if fort.set then
        for k in pairs(fort.set) do
            local x, y, z = k % 4096, (k // 4096) % 4096, k // (4096 * 4096)
            local d = math.max(math.abs(x - sx), math.abs(y - sy)) + 2 * math.abs(z - sz)
            if (not best_d or d < best_d) and inside(x, y, z) then best_in, best_d = {x = x, y = y, z = z}, d end
        end
    end
    best_in = best_in or fort.anchors[1]
    if best_in and (best_in.x ~= sx or best_in.y ~= sy) then table.insert(centers, {x = best_in.x, y = best_in.y}) end
    for _, c in ipairs(extra_centers or {}) do table.insert(centers, c) end      -- (0.105.33)
    -- "is the fort within reach of a tunnel on this level?": inside tiles per level, as
    -- prefix sums over the box (round the center being searched) the columns and their
    -- tunnels can reach
    local reach = WAY_IN_RADIUS + WAY_IN_TUNNEL + 1
    local cur                                 -- the center being searched: {x, y, box, sums}
    local function level_sums(z)
        local s = cur.sums[z]
        if s then return s end
        local b = cur.box
        s = {}
        for x = b.x1 - 1, b.x2 do s[x] = {} end
        for y = b.y1 - 1, b.y2 do s[b.x1 - 1][y] = 0 end
        for x = b.x1, b.x2 do
            s[x][b.y1 - 1] = 0
            for y = b.y1, b.y2 do
                s[x][y] = (inside(x, y, z) and 1 or 0) + s[x - 1][y] + s[x][y - 1] - s[x - 1][y - 1]
            end
        end
        cur.sums[z] = s
        return s
    end
    local function near(z, x, y)
        local r, b = WAY_IN_TUNNEL + 1, cur.box
        local x1, y1 = math.max(b.x1, x - r), math.max(b.y1, y - r)
        local x2, y2 = math.min(b.x2, x + r), math.min(b.y2, y + r)
        if x1 > x2 or y1 > y2 then return false end
        local s = level_sums(z)
        return s[x2][y2] - s[x1 - 1][y2] - s[x2][y1 - 1] + s[x1 - 1][y1 - 1] > 0
    end
    for _, c in ipairs(centers) do
        c.box = {x1 = math.max(0, c.x - reach), y1 = math.max(0, c.y - reach),
                 x2 = math.min(W - 1, c.x + reach), y2 = math.min(H - 1, c.y + reach)}
        c.sums = {}
    end
    -- a tunnel on level z from the column's foot (x, y) to a tile beside the fort's inside
    local function tunnel(x, y, z, budget)
        local seen, queue, head = {[wkey(x, y, z)] = 0}, {{x = x, y = y, d = 0}}, 1
        while head <= #queue do
            local c = queue[head]
            head = head + 1
            for _, s in ipairs(WAY_IN_SIDES) do
                local nx, ny = c.x + s[1], c.y + s[2]
                if inside(nx, ny, z) and gate_dist(nx, ny) >= WAY_IN_GATE_CLEAR then
                    local path, p = {}, c
                    while p.parent do table.insert(path, 1, {x = p.x, y = p.y}); p = p.parent end
                    return path, {x = nx, y = ny, z = z}
                end
            end
            if c.d < budget then
                for _, s in ipairs(WAY_IN_SIDES) do
                    local nx, ny = c.x + s[1], c.y + s[2]
                    local k = wkey(nx, ny, z)
                    if not seen[k] and gate_dist(nx, ny) >= WAY_IN_GATE_CLEAR and safe(nx, ny, z) then
                        seen[k] = true
                        table.insert(queue, {x = nx, y = ny, d = c.d + 1, parent = c})
                    end
                end
            end
        end
    end
    local ctx = {z = sz, target = target, safe = safe, dry_beside = dry_beside, near = near, tunnel = tunnel,
                 best_cost = WAY_IN_MAX_DIG + 1}
    -- (0.105.33, L4) a column whose cells quickfort's dry run refuses is
    -- left out and the search run again (WAY_IN_TRIES times in all)
    local banned, refused_last = {}, nil
    local pri = second and WAY_IN_SECOND_PRIORITY or WAY_IN_PRIORITY
    local best, cells, out
    for attempt = 1, WAY_IN_TRIES do
    ctx.best_cost = WAY_IN_MAX_DIG + 1
    local best_rank
    best = nil
    local whys, tried, near_gate, too_long, no_ground, off_band = {}, {}, 0, 0, 0, 0
    for k in pairs(banned) do tried[k] = true end
    local deadline = math.min(os.clock() + WAY_IN_SECONDS, deadline_all)
    local timed_out = false
    for _, c in ipairs(centers) do
        cur = c
        for r = 0, WAY_IN_RADIUS do
            for dx = -r, r do
                for dy = -r, r do
                    if math.max(math.abs(dx), math.abs(dy)) == r then
                        local x, y = c.x + dx, c.y + dy
                        local k = y * 4096 + x
                        if not tried[k] and x > 1 and y > 1 and x < W - 2 and y < H - 2 then
                            tried[k] = true
                            if os.clock() > deadline then timed_out = true break end
                            if gate_dist(x, y) < WAY_IN_GATE_APART then
                                near_gate = near_gate + 1
                            elseif not in_band(x, y) then
                                off_band = off_band + 1
                            else
                                for _, below in ipairs({true, false}) do
                                    local plan, why, long = way_in_column(ctx, x, y, below)
                                    if plan and second and not (plan.to and in_band(plan.to.x, plan.to.y)
                                            and not (fort.set and fort.set[wkey(plan.to.x, plan.to.y, plan.to.z)])) then
                                        plan, why = nil, nil       -- (its top steps off out of the band, or
                                    end                            -- (fix33) into the fort's inside: a courtyard)
                                    if plan then
                                        local rank = plan.tiles * 1000000 + (x - sx) ^ 2 + (y - sy) ^ 2
                                        if not best_rank or rank < best_rank then
                                            best, best_rank = plan, rank
                                            ctx.best_cost = plan.tiles + 1     -- (a tie: the one nearer them)
                                        end
                                    elseif long then
                                        too_long = too_long + 1
                                    elseif why == WAY_IN_NO_GROUND then
                                        no_ground = no_ground + 1
                                    elseif why then
                                        local w = why:gsub(' at x%d+ y%d+ z%-?%d+', '')
                                        w = w:gsub(' beside x%d+ y%d+ z%-?%d+', ' beside it')
                                        whys[w] = (whys[w] or 0) + 1
                                    end
                                end
                            end
                        end
                    end
                end
                if timed_out then break end
            end
            if timed_out then break end
        end
        if timed_out then break end
    end
    if not best then
        if refused_last then return refuse(refused_last) end
        local words = {}
        for w, n in pairs(whys) do table.insert(words, {w = w, n = n}) end
        table.sort(words, function(a, b) if a.n ~= b.n then return a.n > b.n end return a.w < b.w end)
        local bits = {}
        if too_long > 0 then table.insert(bits, ('the fort is more than %d tiles of digging away'):format(WAY_IN_MAX_DIG)) end
        for i = 1, math.min(2, #words) do table.insert(bits, words[i].w) end
        if #bits == 0 and no_ground > 0 then table.insert(bits, WAY_IN_NO_GROUND) end
        if near_gate > 0 then table.insert(bits, ('the nearer spots are within %d tiles of the gate'):format(WAY_IN_GATE_APART)) end
        return refuse(('no safe %s found near x%d y%d z%d%s%s'):format(second and 'second way in' or 'way in', sx, sy, ez(sz),
            #bits > 0 and ': ' or '', table.concat(bits, '; ')) .. (timed_out and ' (search cut short)' or ''))
    end
    -- (merge32 review) an invader in sight near either end: not now
    -- (0.105.33, L4) nor a great danger (a forgotten beast, a megabeast)
    if GM and type(GM.visible_dangers) == 'function' then
        local okv, vis = pcall(GM.visible_dangers)
        for _, d in ipairs(okv and type(vis) == 'table' and vis or {}) do
            if (d.invader or d.great) and d.pos then
                for _, e in ipairs({best.from, best.to}) do
                    local dd = e and math.max(math.abs(d.pos.x - e.x), math.abs(d.pos.y - e.y), math.abs(d.pos.z - e.z))
                    if dd and dd <= WAY_IN_INVADER_NEAR then
                        return refuse(('%s is in sight %d tiles from where the way in would come out: '
                            .. 'not dug until they are gone'):format(d.invader and 'an invader' or 'a great danger', dd))
                    end
                end
            end
        end
    end
    -- the keys, at the way-in's priority: each tile one quickfort cell
    cells = {}
    for _, c in ipairs(best.cells) do table.insert(cells, {x = c.x, y = c.y, z = c.z, key = c.key}) end
    for _, t in ipairs(best.tunnel) do table.insert(cells, {x = t.x, y = t.y, z = best.z_fort, key = 'd'}) end
    local zlo, zhi = best.z_fort, best.z_fort
    for _, c in ipairs(best.cells) do zlo, zhi = math.min(zlo, c.z), math.max(zhi, c.z) end
    out = {ok = true, from = pos_out(best.from), to = pos_out(best.to), tiles = best.tiles,
           levels = zhi - zlo + 1, column = {x = best.x, y = best.y, elevation_top = ez(zhi), elevation_bottom = ez(zlo)},
           tunnel = #best.tunnel, dry_run = dry_run or nil, second = second or nil}
    if second_e then
        out.entrance = pos_out(second_e)
        out.apart = math.max(math.abs(best.to.x - second_e.x), math.abs(best.to.y - second_e.y))
    end
    for _, c in ipairs(cells) do
        local okd, st = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'run', true)
        if not okd or stat(st, 'dig_designated') ~= 1 then
            refused_last = ('the game would not dig x%d y%d z%d (%s)'):format(c.x, c.y, ez(c.z), c.key)
            banned[best.y * 4096 + best.x] = true
            best = nil
            break
        end
    end
    if best then break end
    end
    if not best then return refuse(refused_last) end
    if dry_run then return out end
    local done, err = pcall(function()
        for _, c in ipairs(cells) do
            local st = quickfort_apply('dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y)
            if stat(st, 'dig_designated') ~= 1 then error(('could not designate x%d y%d z%d'):format(c.x, c.y, ez(c.z))) end
        end
    end)
    local function undo()
        for _, c in ipairs(cells) do pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. pri}}, c.z, c.x, c.y, 'undo') end
    end
    if not done then undo() return {ok = false, error = 'designating the way in failed and was undone: ' .. tostring(err)} end
    local x1, y1, x2, y2 = best.x, best.y, best.x, best.y
    local gallery = {}
    for _, t in ipairs(best.tunnel) do
        x1, y1, x2, y2 = math.min(x1, t.x), math.min(y1, t.y), math.max(x2, t.x), math.max(y2, t.y)
        table.insert(gallery, {x = t.x, y = t.y})
    end
    -- (0.105.33, L4) the column's other levels kept out of the quarry, the
    -- vein drifts and other projects too (level_areas)
    local col_areas = {}
    for _, c in ipairs(best.cells) do
        if c.z ~= best.z_fort then
            table.insert(col_areas, {x1 = c.x, y1 = c.y, x2 = c.x, y2 = c.y, z = c.z})
        end
    end
    local p = {
        id = data.next_id, kind = 'way_in', phase = 'dig', emergency = (not second) or nil, second = second or nil,
        params = {pri = pri}, z = best.z_fort, anchor = {x = best.x, y = best.y}, stair = {x = best.x, y = best.y},
        area = {x1 = x1, y1 = y1, x2 = x2, y2 = y2, z = best.z_fort},
        areas = col_areas,
        cells = {dig = {}}, shaft_stairs = best.cells, gallery = gallery,
        from = best.from, to = best.to,
        stranded = (not second) and {x = sx, y = sy, z = sz, group = target} or nil,
        entrance = second_e,
        summary = {way_in = true, emergency = (not second) or nil, second = second or nil, tiles = best.tiles,
                   levels = out.levels, tunnel = #gallery},
        started = now, designated = #cells,
    }
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    if not save_projects(data) then
        undo()
        return {ok = false, error = 'could not save the way in with the fort, so it was undone'}
    end
    out.project_id = p.id
    return out
end

---------------------------------------------------------------------------
-- Polish: idle hands smooth, then engrave, a finished level dug plain (a
-- young fort builds plain; region2 then stood 40% idle for a year with
-- every level rough). Smoothing and engraving make the rooms nicer to live
-- in and add to the fort's wealth (migrants follow wealth). One level at a
-- time, the rooms dwarves use most first; engraving two weeks after the
-- smoothing was asked for (only smooth stone takes an engraving).
---------------------------------------------------------------------------

POLISH_ORDER = {dining = 1, tavern = 2, suites = 3, hospital = 4, temple = 5, library = 6, bedrooms = 7,
                barracks = 8, memorial = 9, jail = 10, archery = 11, garden = 12}
POLISH_ENGRAVE_AFTER = 14 * 1200

local function room_cells(p, key)
    local cells = {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do table.insert(cells, {x = x, y = y, text = key}) end
    end
    return cells
end

-- Pure: the next project to polish and what to do: (project, 'smooth' |
-- 'engrave') or nil. projects: the registry's list; now: game tick.
function polish_pick(projects, now)
    local best, best_rank, what
    for _, p in ipairs(projects) do
        local rank = POLISH_ORDER[p.kind]
        local pol = p.polish or {}
        if p.phase == 'done' and rank then
            local step
            if not pol.step then step = 'smooth'
            elseif pol.step == 'smooth' and type(pol.at) == 'number' and now - pol.at >= POLISH_ENGRAVE_AFTER then
                step = 'engrave'
            end
            if pol.step == 'smooth' and not step then return nil, 'a level is being smoothed' end
            if step and (not best_rank or rank < best_rank) then best, best_rank, what = p, rank, step end
        end
    end
    return best, what
end

function polish_next(dry_run)
    OFFSET = elevation_offset()
    local data = load_projects()
    local now = now_tick()
    local p, what = polish_pick(data.list, now)
    if not p then
        return {ok = false, rejected = true, waiting = what ~= nil or nil,
                error = what or 'every finished level is polished'}
    end
    local cells = room_cells(p, what == 'smooth' and 's' or 'e')
    if #cells == 0 then return {ok = false, rejected = true, error = 'nothing dug in that level'} end
    local out = {ok = true, project_id = p.id, kind = p.kind, step = what, elevation = ez(p.z), tiles = #cells,
                 dry_run = dry_run or nil}
    if dry_run then return out end
    local ok, s = pcall(quickfort_apply, 'dig', cells, p.z, anchor_of(p).x, anchor_of(p).y)
    local n = ok and stat(s, 'dig_designated') or 0
    p.polish = {step = what == 'smooth' and 'smooth' or 'engraved', at = now}
    save_projects(data)
    out.designated = n
    if n == 0 then
        -- nothing took (soil, built floors, already done): the level counts as polished
        out.note = 'nothing there could be ' .. (what == 'smooth' and 'smoothed' or 'engraved')
    end
    return out
end
