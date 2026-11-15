-- ai-builder-floorstore: (layout B, hallway-first floors) the Rules switch as
-- the builder reads it, the fort's saved floor record, what start_project and
-- cancel_project write into it, and the report's `floors` section.
--
-- A part of ai-builder, not a script of its own: ai-builder.lua loads it into
-- its own environment (PARTS), so every name here is reqscript('ai-builder').name
-- and site_get, site_put, now_tick, ez, elevation_offset, load_projects are in
-- reach. The record's own logic (migration, commit, release, the report rows)
-- is the pure module ai-floorplan; this part only binds it to the save.
--
-- Nothing here calls reqscript while the part loads (the tests' fake fort
-- knows only ai-layouts and quickfort): ai-floorplan and ai-overseer-settings
-- are fetched inside functions, each behind pcall. Nothing here reads a map tile.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-floorstore'] = '0.105.54'

FLOORS_KEY = 'ai-overseer/floors'
FLOOR_RETRY_DAYS = 28        -- the report's `full`: tags marked less than this many days ago
FLOOR_OTHERS_MAX = 30        -- the report's `others`: ids a floor at most
FLOOR_WHY_MAX = 300          -- a fallback's reason, in characters

-- ai-floorplan (the pure module), or nil and why.
local function floorplan()
    local ok, m = pcall(reqscript, 'ai-floorplan')
    if ok and type(m) == 'table' then return m end
    return nil, 'ai-floorplan could not be loaded: ' .. tostring(m):sub(1, 160)
end

local function report_ctx()
    local ok, ctx = pcall(function() return util_module().REPORT_CTX end)
    return ok and type(ctx) == 'table' and ctx or nil
end

local function deep(v)
    local ok, c = pcall(function() return util_module().deep_copy(v) end)
    if ok then return c end
    return v
end

---------------------------------------------------------------------------
-- The switch
---------------------------------------------------------------------------

-- 'hallway' only when the Rules switch can be read and says so; anything
-- unreadable (no settings module, as in every older test; an error; a missing
-- key) is 'classic', so today's path runs unchanged.
function floor_mode()
    local ok, v = pcall(function()
        return reqscript('ai-overseer-settings').load_settings().floor_layout
    end)
    if ok and v == 'hallway' then return 'hallway' end
    return 'classic'
end

---------------------------------------------------------------------------
-- The saved record
---------------------------------------------------------------------------

-- store, writable, why. A newer record (ai-floorplan's migrate says 'newer')
-- is handed out untouched with writable = false: callers then only read.
-- nil, false, why when ai-floorplan cannot be loaded or the record cannot be read.
local function decode_floors()
    local FP, why = floorplan()
    if not FP then return nil, false, why end
    local okr, raw = pcall(site_get, FLOORS_KEY)
    if not okr or type(raw) ~= 'table' then raw = nil end      -- junk reads as none
    local okm, store, _, mwhy = pcall(FP.migrate, raw)
    if not okm then return nil, false, 'the floor record could not be read: ' .. tostring(store):sub(1, 160) end
    if type(store) ~= 'table' then return nil, false, 'the floor record could not be read' end
    local version = math.tointeger(FP.VERSION) or 1
    if mwhy == 'newer' or (type(store.v) == 'number' and store.v > version) then
        return store, false, 'newer'
    end
    -- junk inside a record of this version: the fields this part reads
    if type(store.floors) ~= 'table' then store.floors = {} end
    store.fallbacks = math.tointeger(store.fallbacks) or 0
    if store.last ~= nil and type(store.last) ~= 'table' then store.last = nil end
    return store, true
end

-- Inside a report (ai-util's REPORT_CTX) the record is decoded once and each
-- caller gets its own copy (as load_projects does); outside, every call decodes.
function load_floors()
    local ctx = report_ctx()
    if not ctx then return decode_floors() end
    if ctx.floors == nil then
        local store, writable, why = decode_floors()
        ctx.floors = {store = store, writable = writable, why = why}
    end
    local c = ctx.floors
    return deep(c.store), c.writable, c.why
end

function save_floors(store)
    if type(store) ~= 'table' then return false, 'no floor record to save' end
    local ctx = report_ctx()
    if ctx then ctx.floors = nil end
    local ok, a, b = pcall(site_put, FLOORS_KEY, store)
    if not ok then return false, tostring(a) end
    if a == false then return false, tostring(b) end
    return true
end

-- Each mark {z, sx, sy, tag, free}: that floor's record (made if new) marked
-- full for the tag. A mark that is not one is passed over. Returns how many.
local function apply_marks(FP, store, marks, tick)
    local n = 0
    if type(marks) ~= 'table' then return n end
    for _, m in ipairs(marks) do
        if type(m) == 'table' and math.tointeger(m.z) and math.tointeger(m.sx) and math.tointeger(m.sy)
                and type(m.tag) == 'string' then
            local ok = pcall(function()
                local f = FP.find_floor(store, m.z, m.sx, m.sy) or FP.new_floor(store, m.z, m.sx, m.sy, tick)
                FP.mark_full(store, f, m.tag, tick, type(m.free) == 'table' and m.free or nil)
            end)
            if ok then n = n + 1 end
        end
    end
    return n
end

---------------------------------------------------------------------------
-- What start_project and cancel_project write
---------------------------------------------------------------------------

-- After the project is saved: the placement floor_site found (site._commit)
-- goes into the record, with the marks of the floors found full on the way.
-- false, why when nothing was written.
function floor_commit(site, project_id)
    local ok, a, b = pcall(function()
        local c = type(site) == 'table' and site._commit or nil
        if type(c) ~= 'table' or type(c.store) ~= 'table' or type(c.floor) ~= 'table' then
            return false, 'no floor placement to record'
        end
        local FP, why = floorplan()
        if not FP then return false, why end
        local version = math.tointeger(FP.VERSION) or 1
        if type(c.store.v) == 'number' and c.store.v > version then
            return false, 'the floor record is from a newer version'
        end
        local _, writable, lwhy = load_floors()          -- the record as saved now
        if not writable then
            return false, lwhy == 'newer' and 'the floor record is from a newer version' or (lwhy or 'the floor record cannot be written')
        end
        local store, tick = c.store, now_tick()
        -- The placement first, the marks after it: a floor this project begins
        -- holds the record's next id but is not in the record yet (new_floor
        -- does not insert), and a mark on a level with no record makes one,
        -- which would take that same id. A mark on the placed floor itself is
        -- passed over (commit clears that floor's `full` anyway).
        local f, cwhy = FP.commit(store, c.floor, c.placement, project_id, tick)
        -- (B16) a placement the record refuses is not counted as booked: the record is left as it was
        if type(f) ~= 'table' then
            return false, 'the placement could not be recorded: ' .. tostring(cwhy or 'refused')
        end
        local marks = {}
        local st = type(f.stair) == 'table' and f.stair or {}
        for _, m in ipairs(type(c.marks) == 'table' and c.marks or {}) do
            if not (type(m) == 'table' and m.z == f.z and m.sx == st.x and m.sy == st.y) then
                table.insert(marks, m)
            end
        end
        apply_marks(FP, store, marks, tick)
        if type(c.free) == 'table' then f.free = c.free end
        local kind, elevation
        pcall(function()
            for _, p in ipairs(load_projects().list) do
                if p.id == project_id then kind = p.kind; break end
            end
        end)
        if type(site.floor_result) == 'table' then elevation = math.tointeger(site.floor_result.elevation) end
        if not elevation and math.tointeger(site.z) then elevation = ez(site.z) end
        store.last = {tick = tick, ok = true, kind = kind, elevation = elevation}
        return save_floors(store)
    end)
    if not ok then return false, tostring(a) end
    return a, b
end

-- A level that went the classic way (never called on a dry run): counted,
-- kept as `last`, and the floors found full marked so the next level does
-- not try them again at once. Never raises.
function floor_fallback(kind, why, elevation, marks)
    local ok, a, b = pcall(function()
        local FP, fwhy = floorplan()
        if not FP then return false, fwhy end
        local store, writable, lwhy = load_floors()
        if not store or not writable then return false, lwhy or 'the floor record cannot be written' end
        local tick = now_tick()
        apply_marks(FP, store, marks, tick)
        store.fallbacks = (math.tointeger(store.fallbacks) or 0) + 1
        store.last = {tick = tick, ok = false, kind = type(kind) == 'string' and kind or nil,
                      elevation = math.tointeger(elevation),
                      why = why ~= nil and tostring(why):sub(1, FLOOR_WHY_MAX) or nil}
        return save_floors(store)
    end)
    if not ok then return false, tostring(a) end
    return a, b
end

-- A floor project cancelled: its slots stay taken (dead), its hall's recorded
-- length goes back. Returns how many slots ai-floorplan released (0 when
-- nothing could be done).
function floor_release(p)
    local ok, n = pcall(function()
        if type(p) ~= 'table' or p.id == nil then return 0 end
        local FP = floorplan()
        if not FP then return 0 end
        local store, writable = load_floors()
        if not store or not writable then return 0 end
        local k = math.tointeger(FP.release(store, p.id)) or 0
        save_floors(store)
        return k
    end)
    return ok and n or 0
end

---------------------------------------------------------------------------
-- The report's `floors` section
---------------------------------------------------------------------------

local function empty_floors(v)
    return {v = v or 1, mode = floor_mode(), count = 0, rooms = 0, hall_tiles = 0, fallbacks = 0, list = {}}
end

-- Reads the saved floor record and the saved project records only: no map
-- tile, and nothing is written.
function floors_report()
    OFFSET = elevation_offset()
    local FP, why = floorplan()
    if not FP then
        local out = empty_floors()
        out.error = why
        return out
    end
    local version = math.tointeger(FP.VERSION) or 1
    local store, writable, lwhy = load_floors()
    if not store then
        local out = empty_floors(version)
        out.error = lwhy
        return out
    end
    if not writable then
        local out = empty_floors(version)
        out.newer = true
        return out
    end
    local okr, rows = pcall(FP.summary, store, ez, now_tick(), FLOOR_RETRY_DAYS)
    if not okr or type(rows) ~= 'table' then
        local out = empty_floors(version)
        out.error = 'the floor record could not be summed up: ' .. tostring(rows):sub(1, 160)
        return out
    end

    -- the saved projects and the dropped levels' outlines, by z
    local by_z, old_z = {}, {}
    pcall(function()
        local data = load_projects()
        for _, p in ipairs(type(data.list) == 'table' and data.list or {}) do
            if type(p) == 'table' and math.tointeger(p.z) and math.tointeger(p.id) then
                by_z[p.z] = by_z[p.z] or {}
                table.insert(by_z[p.z], {id = p.id, floor = type(p.floor) == 'table' and p.floor.id or nil})
            end
        end
        for _, a in ipairs(type(data.old_areas) == 'table' and data.old_areas or {}) do
            if type(a) == 'table' and math.tointeger(a.z) then old_z[a.z] = (old_z[a.z] or 0) + 1 end
        end
    end)
    for _, l in pairs(by_z) do table.sort(l, function(a, b) return a.id > b.id end) end

    local runs_of = {}       -- floor id -> runs in the record
    for _, f in ipairs(store.floors) do
        if type(f) == 'table' and f.id ~= nil then
            runs_of[f.id] = type(f.runs) == 'table' and #f.runs or 0
        end
    end

    local out = empty_floors(math.tointeger(store.v) or version)
    out.fallbacks = math.tointeger(store.fallbacks) or 0
    out.last = type(store.last) == 'table' and store.last or nil
    for _, row in ipairs(rows) do
        if type(row) == 'table' then
            local others = {}
            for _, p in ipairs(by_z[row.z] or {}) do
                if #others >= FLOOR_OTHERS_MAX then break end
                if p.floor == nil or p.floor ~= row.id then table.insert(others, p.id) end
            end
            row.others = others
            row.old_boxes = old_z[row.z] or 0
            local runs = runs_of[row.id]
            if runs == nil then runs = type(row.arms) == 'table' and #row.arms or 0 end
            if runs > 0 then out.count = out.count + 1 end
            out.rooms = out.rooms + (math.tointeger(row.rooms) or 0)
            out.hall_tiles = out.hall_tiles + (math.tointeger(row.hall) or 0)
            table.insert(out.list, row)
        end
    end
    return out
end
