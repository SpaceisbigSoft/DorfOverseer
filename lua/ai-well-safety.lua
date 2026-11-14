-- (0.105.47) Cavern wells made safe (R2, I7d "Cavern wells").
--
-- Why: the AI's cavern wells killed 11 dwarves in the 12-14 Nov run (plus 5
-- stranded in Cavern1): two fell down a fresh shaft's very column (B Sazir,
-- E Uzol, COLLISION minutes after it was placed), six drowned in the lake 1-5
-- tiles from a shaft dug minutes before (mostly miners), two were stranded
-- under a well's landing with no path back and later killed by a forgotten
-- beast (A Nomal, B Kib). E placed 13 cavern wells in 6 hours; `seal_cavern`
-- failed in A, B and E ("no door or hatch on the way down to lock"), and
-- `seal_well_stairs` locked the stair lid with no look below.
--
-- What this does (the shaft's own steps are in ai-builder-wells.lua: the
-- bottom-up order, well_up_advance; the hooks call in here):
--   1. place_gate: one cavern-well project at a time; none within
--      COOLDOWN_DAYS of one given up (the brain's cavern_well_cooldown_days);
--      a site (a shaft column, SITE_RADIUS across) given up SITE_TRIES times
--      is kept free (its boxes go to the spot search's reserved list).
--   2. The shaft dug from the bottom up (ai-builder-wells place_well): its
--      last level into the cavern is opened first, from the stair step beside
--      it, while the levels over it are still rock; no tile of the column is
--      ever a ramp or floor to stand on. Here: the column's tiles get
--      Restricted traffic while it is dug (only tiles at Normal), a dig job in
--      the column is suspended while a citizen stands in the column at or
--      under it (let go again when clear), the next level is designated only
--      with nobody in the column, and the watcher logs every citizen beside
--      an open shaft tile and every citizen who turns up in the cavern under a
--      well (the in-game probe of how they fall).
--   3. A door at the gallery's fort end (a hatch over the stair top for a
--      well in a hall), recorded with ai-threats as a way into the caverns
--      (fort_doors -> gather_openings), so seal_cavern can lock it; never
--      locked while a dwarf is beyond it (door_blocked).
--   4. lid_block / gate_block: the stair lid is never locked, and the shaft
--      gate never shut for no danger, while a citizen is below (the stair
--      column under the lid, the shaft's column, the hatch, the cavern under
--      the well); the gate is never opened under a citizen standing on the
--      shut hatch (it drops into the lake). Waits and is tried again.
--   5. rescue: a citizen stranded in the cavern under a well (no path): the
--      well's door or lid unlocked when that is all that holds them, else a
--      stair dug out from the well's stair column down to the cavern floor
--      they stand on (inside the well's door); never with a danger near them
--      or the stair's foot.
--
--   report()                      the `well_safety` section (in the pulse)
--   step(dry_run)                 the `well_safety` action: watch, traffic, doors, next level
--   rescue(x, y, z, pid, dry_run) the `well_rescue` action
--   place_gate(data, params, now, mode)   ai-builder-wells place_well's gate
--   lid_block(pid), gate_block(pid, want_closed, danger), column_block(pid)
--   fort_doors(), door_blocked(o)         ai-threats' openings and seal
--@ module = true

COOLDOWN_DAYS = 84        -- a season: no new cavern well this long after one was given up
SITE_TRIES = 2            -- a site given up this many times is kept free
SITE_RADIUS = 3           -- tiles across: the same site
SITE_LEVELS = 12          -- fort levels round it the site is kept free on
UNDER_R = 12              -- a citizen in the cavern this near the shaft (across) is under the well
UNDER_LEVELS = 20         -- ...and at most this many levels under the shaft's bottom
WATCH_TICKS = 50          -- the watcher's beat (citizens only: cheap)
LOG_MAX = 40              -- log entries kept
LOG_REPORT = 12           -- ...the newest of them in the report
SEEN_AGAIN = 1200         -- the same citizen beside the same shaft logged again after a day
RESCUE_NEAR = 15          -- a stranded citizen this near a well's shaft (across) is under it
RESCUE_MAX_LEVELS = 25    -- the rescue stair's levels at most
RESCUE_BEAST_NEAR = 30    -- no rescue with a danger this near them or the stair's foot (tiles, levels too)
RESCUE_PRIORITY = '1'
DOOR_TRIES = 3            -- a door the game won't place: tried this often
YEAR = 403200
DAY = 1200

STATE = STATE or {on = false, log = {}, seen = {}, under = {}, suspended = {}}

local DIR4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}
local DIR8 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}
local NATURAL = {STONE = true, MINERAL = true, SOIL = true, LAVA_STONE = true}

-- --- reading the game (tests replace these) ------------------------------------------

function builder()
    if BUILDER then return BUILDER end
    return reqscript('ai-builder')
end

function now_tick()
    local ok, t = pcall(function() return df.global.cur_year * YEAR + df.global.cur_year_tick end)
    return ok and t or 0
end

local function utf(s)
    if dfhack and dfhack.df2utf then
        local ok, c = pcall(dfhack.df2utf, s)
        if ok and c then return c end
    end
    return s
end

-- The citizens: {{id, x, y, z, name}}.
function citizens()
    if CITIZENS_FN then return CITIZENS_FN() end
    local out = {}
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then
                local okn, nm = pcall(dfhack.units.getReadableName, u)
                table.insert(out, {id = u.id, x = x, y = y, z = z, name = okn and utf(nm) or ('unit ' .. u.id)})
            end
        end
    end)
    return out
end

-- The dangers loose on the map (not citizens, not caged or tame): {{id, x, y, z, name}}.
function dangers()
    if DANGERS_FN then return DANGERS_FN() end
    local out = {}
    local B = builder()
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function()
                if not dfhack.units.isActive(u) or dfhack.units.isDead(u) or dfhack.units.isCitizen(u, true) then return end
                if u.flags1.caged or u.flags1.chained then return end
                local okt, tame = pcall(dfhack.units.isTame, u)
                if okt and tame then return end
                local okw, wild = pcall(B.hostile_wild, u)
                if not (dfhack.units.isDanger(u) or (okw and wild)) then return end
                local okn, nm = pcall(dfhack.units.getReadableName, u)
                table.insert(out, {id = u.id, x = u.pos.x, y = u.pos.y, z = u.pos.z, name = okn and utf(nm) or nil})
            end)
        end
    end)
    return out
end

-- Dig jobs on given columns: {{id, x, y, z, suspended, job}}. cols: {"x,y" = true}.
function column_jobs(cols)
    if JOBS_FN then return JOBS_FN(cols) end
    local out = {}
    pcall(function()
        local link = df.global.world.jobs.list.next
        while link do
            local j = link.item
            if j and cols[j.pos.x .. ',' .. j.pos.y] then
                local okt, name = pcall(function() return df.job_type[j.job_type] end)
                if okt and (name == 'DigChannel' or name == 'Dig' or name == 'CarveRamp') then
                    table.insert(out, {id = j.id, x = j.pos.x, y = j.pos.y, z = j.pos.z,
                                       suspended = j.flags.suspend == true, job = j})
                end
            end
            link = link.next
        end
    end)
    return out
end

function set_suspended(row, on)
    if SUSPEND_FN then return SUSPEND_FN(row, on) end
    local ok = pcall(function() row.job.flags.suspend = on end)
    return ok
end

-- A tile's traffic made Restricted when it is Normal (never the player's
-- other setting). True when changed.
function restrict_tile(x, y, z)
    if TRAFFIC_FN then return TRAFFIC_FN(x, y, z) end
    local ok, done = pcall(function()
        local des = dfhack.maps.getTileFlags(x, y, z)
        if des and des.traffic == df.tile_traffic.Normal then
            des.traffic = df.tile_traffic.Restricted
            return true
        end
        return false
    end)
    return ok and done or false
end

-- {type = 'Door'|'Hatch'|other, id, built, locked, b} at a tile, or nil.
function building_on(x, y, z)
    if BUILDING_FN then return BUILDING_FN(x, y, z) end
    local out
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if not b then return end
        local ty = b:getType()
        out = {id = b.id, b = b,
               type = (ty == df.building_type.Door and 'Door') or (ty == df.building_type.Hatch and 'Hatch')
                   or tostring(df.building_type[ty] or ty)}
        pcall(function() out.built = b:getBuildStage() >= b:getMaxBuildStage() end)
        pcall(function() out.locked = b.door_flags.forbidden == true end)
    end)
    return out
end

function unlock(bd)
    if UNLOCK_FN then return UNLOCK_FN(bd) end
    -- (0.105.47) through ai-util's lock_door: DF's walk map redone after it
    local okm, U = pcall(reqscript, 'ai-util')
    if not (okm and type(U) == 'table') then return false end
    local _, ok = U.lock_door(bd and bd.b, false, 'well')
    return ok
end

local function log(kind, text, extra)
    local e = {tick = now_tick(), kind = kind, text = text}
    for k, v in pairs(extra or {}) do e[k] = v end
    table.insert(STATE.log, e)
    while #STATE.log > LOG_MAX do table.remove(STATE.log, 1) end
    pcall(function() print('[ai-well-safety] ' .. text) end)
end

-- --- the wells ------------------------------------------------------------------------

function is_cavern_well(p)
    return type(p) == 'table' and p.kind == 'well' and type(p.shaft_stairs) == 'table' and p.shaft_stairs[1] ~= nil
end

local function find(data, id)
    for _, p in ipairs(data.list or {}) do if p.id == id then return p end end
end

-- The shaft: {x, y (the column), top (the well's level), hz (its bottom,
-- the level opening into the cavern), lid (the stair column's top step), stairs}.
function geom(p)
    local B = builder()
    local a = B.anchor_of(p)
    local hz
    for _, z in ipairs(type(p.shaft) == 'table' and p.shaft or {}) do
        if not hz or z < hz then hz = z end
    end
    hz = hz or (p.z - 1)
    return {x = a.x, y = a.y, top = p.z, hz = hz, lid = p.shaft_stairs[1], stairs = p.shaft_stairs}
end

local function cheb(a, x, y) return math.max(math.abs(a.x - x), math.abs(a.y - y)) end

-- in the shaft's column, from the cavern's air under it up to `upto` (default: under the top)
local function in_column(g, c, upto)
    return c.x == g.x and c.y == g.y and c.z >= g.hz - 1 and c.z <= (upto or (g.top - 1))
end

local function on_stairs_below_lid(g, c)
    for _, s in ipairs(g.stairs) do
        if c.x == s.x and c.y == s.y and c.z == s.z and c.z < g.lid.z then return true end
    end
    return false
end

-- in the cavern under the well
function under(g, c)
    if c.z >= g.hz or c.z < g.hz - UNDER_LEVELS or cheb(g, c.x, c.y) > UNDER_R then return false end
    if in_column(g, c) then return false end
    local t = builder().tile_info(c.x, c.y, c.z)
    return t ~= nil and t.feature and true or false
end

-- the wells the watcher and the report look at: being dug, furnished, built,
-- or given up over a shaft dug open into the cavern
local function watched(p)
    if not is_cavern_well(p) then return false end
    if p.phase == 'dig' or p.phase == 'furnish' or p.phase == 'done' then return true end
    local B = builder()
    local ok, open = pcall(B.shaft_left_open, p)
    return ok and open or false
end

-- --- 4. who is below ------------------------------------------------------------------

local function first_name(list) return list[1] and (list[1].name or ('unit ' .. tostring(list[1].id))) or nil end

function below_rows(p, cits, opts)
    opts = opts or {}
    local g = geom(p)
    local out = {}
    for _, c in ipairs(cits or citizens()) do
        local hit = in_column(g, c, opts.upto)
            or (opts.stairs and on_stairs_below_lid(g, c))
            or (opts.under and under(g, c))
            or (opts.hatch and c.x == g.x and c.y == g.y and c.z == g.hz)
        if hit then table.insert(out, c) end
    end
    return out
end

-- Who is in the shaft's column (a dig into it, or the break into the cavern, waits). nil: nobody.
function column_block(pid, cits, upto)
    local data = builder().load_projects()
    local p = find(data, pid)
    if not p or not is_cavern_well(p) then return nil end
    return first_name(below_rows(p, cits, {upto = upto}))
end

-- Who is below the stair lid (it isn't locked on them). nil: nobody.
function lid_block(pid, cits)
    local data = builder().load_projects()
    local p = find(data, pid)
    if not p or not is_cavern_well(p) then return nil end
    return first_name(below_rows(p, cits, {stairs = true, under = true, hatch = true}))
end

-- Who keeps the shaft gate as it is: opening, a citizen on the shut hatch or
-- in the column; shutting for no danger, a citizen in the column or the
-- cavern under it. A danger near: the gate shuts all the same.
function gate_block(pid, want_closed, danger, cits)
    if want_closed and danger then return nil end
    local data = builder().load_projects()
    local p = find(data, pid)
    if not p or not is_cavern_well(p) then return nil end
    if want_closed then return first_name(below_rows(p, cits, {under = true, hatch = true})) end
    return first_name(below_rows(p, cits, {hatch = true}))
end

-- --- 1. one at a time, the cooldown, the sites -----------------------------------------

local function gone_tick(p)
    if tonumber(p.cancelled_tick) then return tonumber(p.cancelled_tick) end
    if tonumber(p.cancelled_year) then return tonumber(p.cancelled_year) * YEAR end
    return nil
end

local function cavern_kind(p)
    return type(p) == 'table' and p.kind == 'well'
        and (type(p.shaft_stairs) == 'table' or (type(p.summary) == 'table' and p.summary.cavern == true))
end

-- {active = {ids}, gone = n, last_gone = tick, cooldown_left = ticks,
-- closed = {{x, y, z, tries}}}. stamp: a given-up cavern well with no tick
-- gets `now` (true when one was stamped: the caller saves).
function book_of(data, now, opts)
    opts = opts or {}
    now = now or now_tick()
    local days = tonumber(opts.cooldown_days) or COOLDOWN_DAYS
    local tries = math.tointeger(tonumber(opts.site_tries)) or SITE_TRIES
    local out = {active = {}, gone = 0, closed = {}}
    local gone, stamped = {}, false
    for _, p in ipairs(data.list or {}) do
        if cavern_kind(p) then
            if p.phase == 'dig' or p.phase == 'furnish' then
                table.insert(out.active, p.id)
            elseif p.phase == 'cancelled' then
                if opts.stamp and not gone_tick(p) then p.cancelled_tick, stamped = now, true end
                local t = gone_tick(p)
                out.gone = out.gone + 1
                if t and (not out.last_gone or t > out.last_gone) then out.last_gone = t end
                local a = builder().anchor_of(p)
                if a then table.insert(gone, {x = a.x, y = a.y, z = p.z}) end
            end
        end
    end
    if out.last_gone and days > 0 then
        out.cooldown_left = math.max(0, days * DAY - (now - out.last_gone))
    end
    if tries > 0 then
        for _, g in ipairs(gone) do
            local n = 0
            for _, h in ipairs(gone) do if cheb(g, h.x, h.y) <= SITE_RADIUS then n = n + 1 end end
            if n >= tries then
                local dup = false
                for _, c in ipairs(out.closed) do if cheb(c, g.x, g.y) <= SITE_RADIUS then dup = true end end
                if not dup then table.insert(out.closed, {x = g.x, y = g.y, z = g.z, tries = n}) end
            end
        end
    end
    return out, stamped
end

-- place_well's gate for a cavern well. mode 'active': only "one at a time"
-- (a given-up well taken up again doesn't wait out the cooldown). Returns
-- {reject = result} or {reserved = {boxes}, closed = n}.
function place_gate(data, params, now, mode)
    params = type(params) == 'table' and params or {}
    local t = type(now) == 'table' and ((tonumber(now.year) or 0) * YEAR + (tonumber(now.tick) or 0)) or now_tick()
    local book = book_of(data, t, {cooldown_days = params.cooldown_days, site_tries = params.site_tries})
    if #book.active > 0 then
        return {reject = {ok = false, rejected = true, one_at_a_time = true, project_id = book.active[1],
                          error = ('a cavern well is already being dug or built (project %d): one at a time')
                              :format(book.active[1])}}
    end
    if mode == 'active' then return {} end
    if (book.cooldown_left or 0) > 0 then
        local left = math.ceil(book.cooldown_left / DAY)
        return {reject = {ok = false, rejected = true, cooldown = true, days_left = left,
                          error = ('a cavern well was given up %d day(s) ago: the next one only after %d more day(s)')
                              :format((t - book.last_gone) // DAY, left)}}
    end
    local boxes = {}
    for _, c in ipairs(book.closed) do
        for z = c.z - SITE_LEVELS, c.z + SITE_LEVELS do
            table.insert(boxes, {x1 = c.x - SITE_RADIUS, y1 = c.y - SITE_RADIUS, x2 = c.x + SITE_RADIUS,
                                 y2 = c.y + SITE_RADIUS, z = z})
        end
    end
    return {reserved = boxes, closed = #book.closed}
end

-- --- 3. the door at the gallery's fort end ----------------------------------------------

-- Where it goes: {x, y, z, kind = 'door'|'hatch', key} or nil, why.
function door_spot(p)
    local land = type(p.landing) == 'table' and p.landing or nil
    local tiles = {}
    for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do
        if not (land and g.x == land.x and g.y == land.y) then table.insert(tiles, g) end
    end
    if #tiles > 0 then
        -- the tile at the fort's end; with a one-tile gallery only once the well stands
        if #tiles == 1 and p.phase == 'dig' then return nil, 'a one-tile gallery: the door once the well stands' end
        return {x = tiles[1].x, y = tiles[1].y, z = p.z, kind = 'door', key = 'd'}
    end
    local top = p.shaft_stairs[1]
    return {x = top.x, y = top.y, z = top.z, kind = 'hatch', key = 'H'}
end

-- The door's state: none, waiting (its tile not dug yet), planned, built, locked, gone, refused.
function door_state(p)
    local d = type(p.fort_door) == 'table' and p.fort_door or nil
    if d then
        local b = building_on(d.x, d.y, d.z)
        if b and (b.type == 'Door' or b.type == 'Hatch') then
            if not b.built then return 'planned', d end
            return b.locked and 'locked' or 'built', d, b
        end
        if (tonumber(d.fails) or 0) >= DOOR_TRIES then return 'refused', d end
        return 'gone', d
    end
    return 'none'
end

local function door_tile_ready(spot)
    local t = builder().tile_info(spot.x, spot.y, spot.z)
    if not t or t.building or t.designated then return false end
    if spot.kind == 'door' then return t.shape == 'FLOOR' end
    return t.shape == 'STAIR_DOWN' or t.shape == 'STAIR_UPDOWN'
end

-- One door placed for this well (or nil when none is due). {stage, x, y, z, kind}.
function place_door(p, dry_run)
    local st = door_state(p)
    if st ~= 'none' and st ~= 'gone' then return nil end
    local spot, why = door_spot(p)
    if not spot then return {stage = 'waiting', why = why} end
    if building_on(spot.x, spot.y, spot.z) or not door_tile_ready(spot) then
        return {stage = 'waiting', why = 'its tile is not dug yet (or something stands there)'}
    end
    local r = {stage = dry_run and 'place' or 'placed', x = spot.x, y = spot.y, z = spot.z, kind = spot.kind}
    if dry_run then return r end
    local B = builder()
    local ok, s = pcall(B.quickfort_apply, 'build', {{x = 0, y = 0, text = spot.key}}, spot.z, spot.x, spot.y)
    local fails = type(p.fort_door) == 'table' and tonumber(p.fort_door.fails) or 0
    if not ok or B.stat(s, 'build_designated') ~= 1 then
        p.fort_door = {x = spot.x, y = spot.y, z = spot.z, kind = spot.kind, fails = fails + 1}
        r.stage, r.error = 'refused', ('the game would not place the %s at x%d y%d'):format(spot.kind, spot.x, spot.y)
        return r
    end
    p.fort_door = {x = spot.x, y = spot.y, z = spot.z, kind = spot.kind, fails = fails > 0 and fails or nil}
    log('door', ('cavern well %d: a %s at its fort end (x%d y%d z%d), a way into the caverns the seal can lock')
        :format(p.id, spot.kind, spot.x, spot.y, spot.z), {project_id = p.id})
    return r
end

-- Every cavern well's door: {{x, y, z, kind, project_id}} (ai-threats' openings).
function fort_doors()
    local out = {}
    local data = builder().load_projects()
    for _, p in ipairs(data.list or {}) do
        local d = is_cavern_well(p) and type(p.fort_door) == 'table' and p.fort_door or nil
        if d and math.tointeger(d.x) and (watched(p) or p.phase == 'cancelled') then
            table.insert(out, {x = d.x, y = d.y, z = d.z, kind = d.kind, project_id = p.id})
        end
    end
    return out
end

-- Who is beyond a well's door (the gallery past it, the stair column, the
-- shaft, the cavern under it): the seal doesn't lock it on them. o: {x, y, z}.
function door_blocked(o, cits)
    local data = builder().load_projects()
    for _, p in ipairs(data.list or {}) do
        local d = is_cavern_well(p) and type(p.fort_door) == 'table' and p.fort_door or nil
        if d and d.x == o.x and d.y == o.y and d.z == o.z then
            cits = cits or citizens()
            local beyond = {}
            for i, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do
                if not (g.x == d.x and g.y == d.y) then beyond[g.x .. ',' .. g.y .. ',' .. p.z] = true end
            end
            for _, c in ipairs(cits) do
                if beyond[c.x .. ',' .. c.y .. ',' .. c.z] then return c.name or ('unit ' .. tostring(c.id)) end
            end
            local opts = {stairs = true, under = true, hatch = true}
            if d.kind == 'door' then
                -- the stair column's top step is beyond a gallery's door too
                local g = geom(p)
                for _, c in ipairs(cits) do
                    if c.x == g.lid.x and c.y == g.lid.y and c.z == g.lid.z then return c.name end
                end
            end
            return first_name(below_rows(p, cits, opts))
        end
    end
    return nil
end

-- --- 2. the watcher: the column, the logs, the next level --------------------------------

local function column_open_levels(g)
    local B = builder()
    local out = {}
    for z = g.hz, g.top do
        local t = B.tile_info(g.x, g.y, z)
        if t and t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP' and not t.building then out[z] = true end
    end
    return out
end

-- One look at every watched well. Returns {changed (projects to save), suspended, released, advanced, logged}.
function watch_once(data, cits)
    local B = builder()
    local own = data == nil          -- loaded here: saved here too
    data = data or B.load_projects()
    cits = cits or citizens()
    local now = now_tick()
    local res = {changed = false, suspended = 0, released = 0, advanced = 0, logged = 0, wells = 0}
    local cols, by_col = {}, {}
    for _, p in ipairs(data.list or {}) do
        if watched(p) then
            res.wells = res.wells + 1
            local g = geom(p)
            -- the log: beside an open shaft tile (or in it), and new in the cavern under it
            local open = column_open_levels(g)
            STATE.under[p.id] = STATE.under[p.id] or {}
            local now_under = {}
            for _, c in ipairs(cits) do
                local key = p.id .. ':' .. c.id
                if open[c.z] and cheb(g, c.x, c.y) <= 1 then
                    local last = STATE.seen[key]
                    if not last or now - last >= SEEN_AGAIN or now < last then
                        STATE.seen[key] = now
                        local inside = c.x == g.x and c.y == g.y
                        log(inside and 'in_shaft' or 'beside_shaft',
                            ('%s %s cavern well %d\'s open shaft at x%d y%d z%d (%s)'):format(
                                tostring(c.name), inside and 'is in' or 'stands beside', p.id, c.x, c.y, c.z,
                                p.phase == 'dig' and 'being dug' or p.phase),
                            {project_id = p.id, unit = c.id, x = c.x, y = c.y, z = c.z})
                        res.logged = res.logged + 1
                    end
                end
                if under(g, c) then
                    now_under[c.id] = true
                    if not STATE.under[p.id][c.id] then
                        local ago = type(p.started) == 'table' and tonumber(p.started.year)
                            and (now - (tonumber(p.started.year) * YEAR + (tonumber(p.started.tick) or 0))) or nil
                        log('under_well', ('%s turned up in the cavern under cavern well %d at x%d y%d z%d '
                                .. '(%d tiles from its shaft%s)'):format(tostring(c.name), p.id, c.x, c.y, c.z,
                                cheb(g, c.x, c.y), ago and (', ' .. (ago // DAY) .. ' day(s) after it was placed') or ''),
                            {project_id = p.id, unit = c.id, x = c.x, y = c.y, z = c.z})
                        res.logged = res.logged + 1
                    end
                end
            end
            STATE.under[p.id] = now_under
            if p.phase == 'dig' then
                cols[g.x .. ',' .. g.y] = true
                by_col[g.x .. ',' .. g.y] = {p = p, g = g}
                -- the next level of a bottom-up shaft, nobody in the column
                local nz = type(p.up) == 'table' and type(p.up.zs) == 'table' and p.up.zs[1] or nil
                if nz then
                    local busy = first_name(below_rows(p, cits, {upto = nz}))
                    local okv, stage, z = pcall(B.well_up_advance, p, false, busy)
                    if okv and stage == 'designated' then
                        res.advanced, res.changed = res.advanced + 1, true
                        log('level', ('cavern well %d: its shaft dug up to z%d (from the bottom up)'):format(p.id, z),
                            {project_id = p.id, z = z})
                    elseif okv and stage == 'refused' then
                        res.changed = true
                    end
                end
            end
        end
    end
    -- the dig guard: a dig job in a column is suspended while a citizen
    -- stands in that column at or under its level; let go when clear
    if next(cols) then
        for _, j in ipairs(column_jobs(cols)) do
            local w = by_col[j.x .. ',' .. j.y]
            local busy
            if w then
                for _, c in ipairs(cits) do
                    if c.x == w.g.x and c.y == w.g.y and c.z <= j.z and c.z >= w.g.hz - 1 then busy = c break end
                end
            end
            if busy and not j.suspended then
                if set_suspended(j, true) then
                    STATE.suspended[j.id] = w.p.id
                    res.suspended = res.suspended + 1
                    log('suspended', ('cavern well %d: the dig at z%d held while %s stands in the shaft\'s column (z%d)')
                        :format(w.p.id, j.z, tostring(busy.name), busy.z), {project_id = w.p.id, unit = busy.id})
                end
            elseif not busy and j.suspended and STATE.suspended[j.id] then
                if set_suspended(j, false) then
                    STATE.suspended[j.id] = nil
                    res.released = res.released + 1
                end
            end
        end
    end
    if own and res.changed then pcall(B.save_projects, data) end
    return res
end

local function watch_alive()
    if not (STATE.on and STATE.timer) then return false end
    if not (dfhack and type(dfhack.timeout_active) == 'function') then return true end
    local ok, active = pcall(dfhack.timeout_active, STATE.timer)
    return (ok and active) and true or false
end

local function tick()
    STATE.timer = nil
    if not STATE.on then return end
    local ok, err = pcall(function()
        local B = builder()
        local data = B.load_projects()
        local r = watch_once(data)
        if r.changed then B.save_projects(data) end
        if r.wells == 0 then STATE.on = false end
    end)
    STATE.error = (not ok) and tostring(err):sub(1, 160) or nil
    if STATE.on then STATE.timer = dfhack.timeout(WATCH_TICKS, 'ticks', tick) end
end

function watch_start()
    if watch_alive() then return false end
    STATE.on = true
    STATE.timer = dfhack.timeout(WATCH_TICKS, 'ticks', tick)
    return true
end

if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-well-safety'] = function(sc)
        if sc == SC_MAP_UNLOADED then STATE = {on = false, log = {}, seen = {}, under = {}, suspended = {}} end
    end
end

-- the shaft's column made Restricted traffic (once a well, while it is dug)
local function restrict_column(p, dry_run)
    if p.ws_traffic or p.phase ~= 'dig' then return 0 end
    local g = geom(p)
    local n = 0
    if not dry_run then
        for z = g.hz, g.top do if restrict_tile(g.x, g.y, z) then n = n + 1 end end
        p.ws_traffic = true
    else
        n = g.top - g.hz + 1
    end
    return n
end

-- --- the action and the report ------------------------------------------------------------

-- What a well still needs from the step: {'traffic', 'door', 'level'}.
local function todo_of(p, cits)
    local out = {}
    if p.phase == 'dig' and not p.ws_traffic then table.insert(out, 'traffic') end
    local st = door_state(p)
    if st == 'none' or st == 'gone' then
        local spot = door_spot(p)
        if spot and door_tile_ready(spot) and not building_on(spot.x, spot.y, spot.z) then table.insert(out, 'door') end
    end
    if p.phase == 'dig' and type(p.up) == 'table' and type(p.up.zs) == 'table' and p.up.zs[1] then
        local busy = first_name(below_rows(p, cits, {upto = p.up.zs[1]}))
        local okv, stage = pcall(builder().well_up_advance, p, true, busy)
        if okv and stage == 'next' then table.insert(out, 'level') end
    end
    return out
end

function step(dry_run)
    local B = builder()
    local data = B.load_projects()
    local cits = citizens()
    local out = {ok = true, wells = {}, traffic = 0, doors = 0, advanced = 0, dry_run = dry_run or nil}
    local any, changed = false, false
    for _, p in ipairs(data.list or {}) do
        if watched(p) then
            any = true
            local r = {project_id = p.id}
            local n = restrict_column(p, dry_run)
            if n > 0 then out.traffic, r.traffic, changed = out.traffic + n, n, true end
            local d = place_door(p, dry_run)
            if d then
                r.door = d
                if d.stage == 'placed' or d.stage == 'place' then out.doors = out.doors + 1 end
                if not dry_run and (d.stage == 'placed' or d.stage == 'refused') then changed = true end
            end
            table.insert(out.wells, r)
        end
    end
    if not any then return {ok = false, rejected = true, nothing_to_do = true, error = 'no cavern well to watch'} end
    if not dry_run then
        local r = watch_once(data, cits)
        out.advanced = r.advanced
        if r.changed then changed = true end
        out.watch_started = watch_start() or nil
        if changed then B.save_projects(data) end
    else
        for _, p in ipairs(data.list or {}) do
            if watched(p) then
                for _, t in ipairs(todo_of(p, cits)) do if t == 'level' then out.advanced = out.advanced + 1 end end
            end
        end
        out.watch_started = (not watch_alive()) or nil
    end
    if not (out.watch_started or out.traffic > 0 or out.doors > 0 or out.advanced > 0) then
        return {ok = false, rejected = true, nothing_to_do = true, wells = out.wells,
                error = 'nothing to do: the watcher runs, the shafts are restricted, the doors stand'}
    end
    return out
end

function report(opts)
    opts = opts or {}
    local B = builder()
    local data = B.load_projects()
    local now = now_tick()
    local okb, book, stamped = pcall(book_of, data, now, {stamp = true, cooldown_days = opts.cooldown_days})
    if okb and stamped then pcall(B.save_projects, data) end
    local cits = citizens()
    local wells, todo = {}, {}
    local any = false
    for _, p in ipairs(data.list or {}) do
        if watched(p) then
            any = true
            local g = geom(p)
            local okoff, off = pcall(B.elevation_offset)
            off = okoff and off or 0
            local row = {project_id = p.id, phase = p.phase, x = g.x, y = g.y, z = g.top, hz = g.hz,
                         elevation = g.top + off, bottom_elevation = g.hz + off}
            if type(p.up) == 'table' and type(p.up.zs) == 'table' then
                row.dug_up = true
                row.levels_left = #p.up.zs
                if p.up.zs[1] then row.next_z = p.up.zs[1] end
                if p.up.refused then row.level_refused = p.up.refused end
            end
            row.held = type(p.held) == 'table' or nil
            row.traffic = p.ws_traffic and true or nil
            local st, d = door_state(p)
            row.door = st
            if d then row.door_at = {x = d.x, y = d.y, z = d.z, kind = d.kind} end
            row.column = first_name(below_rows(p, cits, {}))
            local under_list = {}
            for _, c in ipairs(cits) do
                if under(g, c) and #under_list < 5 then
                    table.insert(under_list, {id = c.id, name = c.name, x = c.x, y = c.y, z = c.z})
                end
            end
            if #under_list > 0 then row.under = under_list end
            row.below_lid = first_name(below_rows(p, cits, {stairs = true, under = true, hatch = true}))
            local t = todo_of(p, cits)
            if #t > 0 then
                row.todo = t
                for _, x in ipairs(t) do todo[x] = true end
            end
            table.insert(wells, row)
        end
    end
    local alive = watch_alive()
    if any and not alive then todo.watch = true end
    local tl = {}
    for k in pairs(todo) do table.insert(tl, k) end
    table.sort(tl)
    local log_out = {}
    for i = math.max(1, #STATE.log - LOG_REPORT + 1), #STATE.log do table.insert(log_out, STATE.log[i]) end
    local suspended = 0
    for _ in pairs(STATE.suspended) do suspended = suspended + 1 end
    return {watching = alive, wells = wells, todo = tl, log = log_out, logged = #STATE.log,
            suspended = suspended > 0 and suspended or nil, watch_error = STATE.error,
            book = okb and {active = book.active, gone = book.gone, last_gone = book.last_gone,
                            cooldown_days_left = book.cooldown_left and math.ceil(book.cooldown_left / DAY) or 0,
                            closed_sites = #book.closed} or nil,
            book_error = (not okb) and tostring(book):sub(1, 120) or nil}
end

-- --- 5. the rescue -----------------------------------------------------------------------

local function refuse(why, extra)
    local r = {ok = false, rejected = true, error = why}
    for k, v in pairs(extra or {}) do r[k] = v end
    return r
end

-- a tile the rescue stair may be dug in: natural rock, nothing wet beside it
local function diggable(x, y, z)
    local B = builder()
    local t = B.tile_info(x, y, z)
    if not t or t.shape ~= 'WALL' or t.liquid or t.aquifer or t.warm or t.designated or t.building then return false end
    if t.material and not NATURAL[t.material] then return false end
    for _, d in ipairs(DIR8) do
        local n = B.tile_info(x + d[1], y + d[2], z)
        if n and (n.liquid or n.aquifer) then return false end
    end
    return true
end

-- A stair from the well's stair column down to the cavern floor of the
-- stranded walk group `target`: {cells = {{x, y, z, key}}, foot = {x, y, z}} or nil, why.
function rescue_plan(p, target)
    local B = builder()
    local g = geom(p)
    local bottom
    for _, s in ipairs(g.stairs) do if not bottom or s.z < bottom.z then bottom = s end end
    if not bottom then return nil, 'the well has no stair column' end
    -- the columns: the stair column itself (its bottom step made up/down),
    -- then the rock beside its bottom step (a down stair there)
    local cands = {{x = bottom.x, y = bottom.y, own = true}}
    for _, d in ipairs(DIR4) do
        local cx, cy = bottom.x + d[1], bottom.y + d[2]
        if not (cx == g.x and cy == g.y) then table.insert(cands, {x = cx, y = cy}) end
    end
    local best, why = nil, 'no rock to dig a stair through from the well\'s stairs down to where they stand'
    for _, c in ipairs(cands) do
        local cells = {}
        local ok = true
        if c.own then
            table.insert(cells, {x = c.x, y = c.y, z = bottom.z, key = 'i'})
        elseif diggable(c.x, c.y, bottom.z) then
            table.insert(cells, {x = c.x, y = c.y, z = bottom.z, key = 'j'})
        else
            ok = false
        end
        local foot
        local z = bottom.z - 1
        while ok and not foot do
            if bottom.z - z > RESCUE_MAX_LEVELS then ok, why = false, ('more than %d levels of stair'):format(RESCUE_MAX_LEVELS) break end
            if not diggable(c.x, c.y, z) then ok = false break end
            for _, d in ipairs(DIR4) do
                local nx, ny = c.x + d[1], c.y + d[2]
                local t = B.tile_info(nx, ny, z)
                if t and t.shape ~= 'WALL' and not t.liquid and B.walk_group(nx, ny, z) == target then
                    foot = {x = c.x, y = c.y, z = z, out = {x = nx, y = ny, z = z}}
                    break
                end
            end
            table.insert(cells, {x = c.x, y = c.y, z = z, key = foot and 'u' or 'i'})
            z = z - 1
        end
        if ok and foot and (not best or #cells < #best.cells) then best = {cells = cells, foot = foot} end
    end
    if best then return best end
    return nil, why
end

-- The well a stranded spot is under: the given one, else the nearest whose
-- shaft is within RESCUE_NEAR (across) and above them.
local function well_over(data, x, y, z, pid)
    local best, bd
    for _, p in ipairs(data.list or {}) do
        if is_cavern_well(p) and (pid == nil or p.id == pid) and (watched(p) or p.phase == 'cancelled') then
            local g = geom(p)
            local d = cheb(g, x, y)
            if z < g.hz and d <= RESCUE_NEAR and (not bd or d < bd) then best, bd = p, d end
        end
    end
    return best
end

function rescue(x, y, z, pid, dry_run)
    x, y, z = math.tointeger(tonumber(x)), math.tointeger(tonumber(y)), math.tointeger(tonumber(z))
    if not (x and y and z) then return refuse('well_rescue needs x, y, z (where the stranded stand)') end
    local B = builder()
    local data = B.load_projects()
    local p = well_over(data, x, y, z, math.tointeger(tonumber(pid)))
    if not p then return refuse(('nobody at x%d y%d z%d is under a cavern well'):format(x, y, z)) end
    local g = geom(p)
    local target = B.walk_group(x, y, z)
    if not target or target == 0 then return refuse(('nobody can stand at x%d y%d z%d'):format(x, y, z)) end
    -- the beast check: nothing opened toward them with a danger near them or the stair's foot
    local spots = {{x = x, y = y, z = z}, {x = g.x, y = g.y, z = g.hz - 1}}
    for _, d in ipairs(dangers()) do
        for _, sp in ipairs(spots) do
            local dd = math.max(math.abs(d.x - sp.x), math.abs(d.y - sp.y), math.abs(d.z - sp.z))
            if dd <= RESCUE_BEAST_NEAR then
                return refuse(('%s is %d tiles from them: the way up is not opened until it is gone')
                    :format(tostring(d.name or 'a danger'), dd), {waiting = true, danger = d.name, danger_d = dd})
            end
        end
    end
    -- 1. the way back is only held shut: the well's door or lid unlocked
    local bottom
    for _, s in ipairs(g.stairs) do if not bottom or s.z < bottom.z then bottom = s end end
    local joined = bottom and B.walk_group(bottom.x, bottom.y, bottom.z) == target
    if joined then
        local held = {}
        local _, d, bd = door_state(p)
        if bd and bd.locked then table.insert(held, bd) end
        local lid = building_on(g.lid.x, g.lid.y, g.lid.z)
        if lid and lid.type == 'Hatch' and lid.locked and not (bd and lid.id == bd.id) then table.insert(held, lid) end
        if #held == 0 then
            return refuse('their way up by the well is open (the same walk group): they can walk up', {joined = true})
        end
        if not dry_run then
            for _, b in ipairs(held) do unlock(b) end
            log('rescue', ('cavern well %d: its door unlocked for a dwarf stranded at x%d y%d z%d'):format(p.id, x, y, z),
                {project_id = p.id})
        end
        return {ok = true, unlocked = #held, project_id = p.id, dry_run = dry_run or nil}
    end
    -- 2. a stair dug out to them
    if type(p.rescue) == 'table' and p.rescue.tick and now_tick() - p.rescue.tick < 3 * DAY then
        return refuse(('a stair out is already being dug for them (cavern well %d)'):format(p.id), {digging = true})
    end
    local plan, why = rescue_plan(p, target)
    if not plan then return refuse(why) end
    local okoff, off = pcall(B.elevation_offset)
    off = okoff and off or 0
    local out = {ok = true, project_id = p.id, stair = #plan.cells, dry_run = dry_run or nil,
                 foot = {x = plan.foot.x, y = plan.foot.y, elevation = plan.foot.z + off}}
    for _, c in ipairs(plan.cells) do
        local okd, st = pcall(B.quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. RESCUE_PRIORITY}}, c.z, c.x, c.y, 'run', true)
        if not okd or B.stat(st, 'dig_designated') ~= 1 then
            return refuse(('the game would not dig the stair out at x%d y%d z%d'):format(c.x, c.y, c.z))
        end
    end
    if dry_run then return out end
    for _, c in ipairs(plan.cells) do
        pcall(B.quickfort_apply, 'dig', {{x = 0, y = 0, text = c.key .. RESCUE_PRIORITY}}, c.z, c.x, c.y)
    end
    p.rescue = {cells = plan.cells, x = x, y = y, z = z, tick = now_tick(),
                tries = (type(p.rescue) == 'table' and tonumber(p.rescue.tries) or 0) + 1}
    B.save_projects(data)
    log('rescue', ('cavern well %d: a stair dug out from its stairs down to a dwarf stranded at x%d y%d z%d (%d tiles)')
        :format(p.id, x, y, z, #plan.cells), {project_id = p.id})
    return out
end
