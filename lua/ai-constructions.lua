-- ai-constructions (0.105.30, construction round G3): what the fort has
-- built, counted. Read only.
--
-- Finished constructions (walls, floors, ramps, stairs, fortifications) are
-- map tiles, not buildings, so nothing in the report counted them. The game
-- keeps one record for each in df.global.world.event.constructions
-- (df-structures df.event.xml: struct construction, instance-vector
-- $global.world.event.constructions; older layouts had world.constructions):
-- pos, item_type (what it was built of), flags.top_of_wall (the floor the
-- game puts over a built wall: skipped, it is no construction of anyone's).
--
-- survey() walks that list once and returns
--   {total, by_shape = {wall, floor, ramp, stair_up, stair_down, stair_updown, fortification, other},
--    by_item = {blocks, boulder, log, bar, other},
--    surface = {total, wall, floor, ...}, underground = {total, wall, floor, ...},
--    roofed_surface_tiles,      -- walkable, not outside, not subterranean, under a built floor
--    planned = {n, by_type},    -- Construction buildings not built yet (waiting), by df.construction_type
--    ai = {keep, halls, gate_pieces, wings, cavern_walls, cistern, room_walls, soil_floors},
--    soil_floors = {{project_id, kind, elevation, tiles, floored}...}, soil_floors_left,
--    soil_floors_placed,        -- tiles on the projects' soil_floors records (ai.soil_floors: built ones)
--    block_pct, line, ms, where}
-- Surface means not designation.subterranean (set by the map, not by a roof).
-- The `ai` counts come from the AI's own records: the keep's and the halls'
-- site data (their boxes, the roof level above), the cistern's sealing list,
-- the scanned entrances (their recorded pieces, else the built walls round a
-- way in on the surface; a cavern opening's walls: walls and fortifications
-- only, never floors), each project's soil-floor record, and the projects' boxes
-- underground (room walls, soil floors). A tile counts once, in the first that
-- claims it.
--
-- Cost: one pass over the list (two tile reads each, a z-bucketed box test)
-- and one over the buildings; capped by SURVEY_SECONDS (then `partial`), and
-- kept for SURVEY_CACHE_TICKS (a game day) so the census and the report share it.
--@ module = true

PART_VERSIONS = {['ai-constructions'] = '0.105.33'}   -- bumped with BRIDGE_VERSION

SURVEY_SECONDS = 0.25          -- time cap on the walk (a fort of 50,000 built tiles)
SURVEY_CACHE_TICKS = 1200      -- a game day
GATE_BOX = 8                   -- tiles round a way in where a built wall is a gate piece (gatehouse, wings)
CAVERN_BOX = 2                 -- ... round a cavern opening, walls only
-- the AI's kinds that count only walls (and fortifications): never a floor,
-- a door or a hatch spot (the gate's recorded pieces hold those too)
WALLS_ONLY = {gate_pieces = true, wings = true, cavern_walls = true, room_walls = true}

SHAPES = {WALL = 'wall', FLOOR = 'floor', RAMP = 'ramp', STAIR_UP = 'stair_up', STAIR_DOWN = 'stair_down',
          STAIR_UPDOWN = 'stair_updown', FORTIFICATION = 'fortification'}
SHAPE_KEYS = {'wall', 'floor', 'ramp', 'stair_up', 'stair_down', 'stair_updown', 'fortification', 'other'}
ITEMS = {BLOCKS = 'blocks', BOULDER = 'boulder', WOOD = 'log', BAR = 'bar'}
ITEM_KEYS = {'blocks', 'boulder', 'log', 'bar', 'other'}
AI_KEYS = {'keep', 'halls', 'gate_pieces', 'wings', 'cavern_walls', 'cistern', 'room_walls', 'soil_floors'}
-- the shapes a dwarf stands on (for "walkable" under a roof)
WALKABLE = {floor = true, ramp = true, stair_up = true, stair_down = true, stair_updown = true,
            BOULDER = true, PEBBLES = true}

SURVEY_CACHE = SURVEY_CACHE or nil
SURVEY_RESUME = SURVEY_RESUME or nil   -- (0.105.33) {site, at}: where a cut-short walk stopped

local function counts(keys)
    local t = {}
    for _, k in ipairs(keys) do t[k] = 0 end
    return t
end

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

-- The game's list of constructions, and where it was found; nil if none.
function construction_list()
    local ok, v = pcall(function() return df.global.world.event.constructions end)
    if ok and v ~= nil then return v, 'world.event.constructions' end
    ok, v = pcall(function() return df.global.world.constructions end)
    if ok and v ~= nil then return v, 'world.constructions' end
    return nil, nil
end

-- tiletype -> one of SHAPE_KEYS (or the raw shape name for the walkable
-- natural ones), cached by tiletype: a few hundred kinds at most
local SHAPE_CACHE = {}
local function tile_shape(tt)
    if tt == nil then return 'other' end
    local s = SHAPE_CACHE[tt]
    if s == nil then
        local ok, n = pcall(function() return df.tiletype_shape[df.tiletype.attrs[tt].shape] end)
        n = ok and n or nil
        s = n and (SHAPES[n] or (WALKABLE[n] and n) or 'other') or 'other'
        SHAPE_CACHE[tt] = s
    end
    return s
end

local function shape_at(x, y, z)
    local ok, tt = pcall(dfhack.maps.getTileType, x, y, z)
    return tile_shape(ok and tt or nil)
end

local function flags_at(x, y, z)
    local ok, d = pcall(dfhack.maps.getTileFlags, x, y, z)
    return ok and d or nil
end

-- (0.105.33) designation.subterranean, pcalled as ai-builder's tile_info
-- does (a missing field throws): nil when it can't be read
local function subterranean(d)
    local ok, v = pcall(function() return d.subterranean end)
    if ok then return v end
    return nil
end

local function item_name(it)
    local ok, n = pcall(function() return df.item_type[it] end)
    return ok and n and ITEMS[n] or 'other'
end

local function site_get(k)
    local ok, d = pcall(dfhack.persistent.getSiteData, k, {})
    return ok and type(d) == 'table' and d or {}
end

-- A "x,y,z" string or an {x, y, z} table -> x, y, z (or nil).
local function unkey(v)
    if type(v) == 'string' then
        local x, y, z = v:match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
        return tonumber(x), tonumber(y), tonumber(z)
    elseif type(v) == 'table' then
        local x, y, z = v.x or v[1], v.y or v[2], v.z or v[3]
        if type(x) == 'number' and type(y) == 'number' and type(z) == 'number' then return x, y, z end
    end
end

-- The AI's own pieces, as the places that claim them: `sets` (exact tiles,
-- looked at first) and boxes by z. A box: {cat, x1, y1, x2, y2, where =
-- 'surface'|'under'|nil, walls = true (walls only), floors = cat for floors}.
function ai_regions()
    local R = {sets = {}, boxes = {}, errors = nil, soil_recorded = 0}
    local function err(what, e)
        R.errors = R.errors or {}
        R.errors[what] = tostring(e):sub(1, 120)
    end
    local function claim(cat, x, y, z)
        if x and R.sets[key(x, y, z)] == nil then R.sets[key(x, y, z)] = cat end
    end
    local function box(z, b)
        R.boxes[z] = R.boxes[z] or {}
        table.insert(R.boxes[z], b)
    end
    local function each(list, fn) if type(list) == 'table' then for _, v in pairs(list) do fn(v) end end end
    -- the keep: its ring at z, its roof (and roof stair) at z + 1
    local ok, e = pcall(function()
        local k = site_get('ai-overseer/keep')
        if k.stage and k.x and k.y and k.z and k.r then
            for z = k.z, k.z + 1 do
                box(z, {cat = 'keep', x1 = k.x - k.r, y1 = k.y - k.r, x2 = k.x + k.r, y2 = k.y + k.r})
            end
        end
    end)
    if not ok then err('keep', e) end
    -- the halls (ai-builder-halls.lua): their recorded tiles, their box and roof
    ok, e = pcall(function()
        local d = site_get('ai-overseer/halls')
        each(d.list, function(h)
            if type(h) ~= 'table' then return end
            each(h.tiles, function(v) claim('halls', unkey(v)) end)
            if h.x1 and h.y1 and h.x2 and h.y2 and h.z then
                for z = h.z, h.z + 1 do
                    box(z, {cat = 'halls', x1 = math.min(h.x1, h.x2), y1 = math.min(h.y1, h.y2),
                            x2 = math.max(h.x1, h.x2), y2 = math.max(h.y1, h.y2)})
                end
            end
        end)
    end)
    if not ok then err('halls', e) end
    -- the cistern's own walls and floors closing its gaps
    ok, e = pcall(function()
        local d = site_get('ai-overseer/cistern')
        if type(d.sealing) == 'table' then
            for k in pairs(d.sealing) do claim('cistern', unkey(k)) end
        end
    end)
    if not ok then err('cistern', e) end
    -- the soil floors (ai-builder-rooms floor_soil_rooms): each project
    -- keeps its own, p.soil_floors = {"x,y", ...} at p.z
    ok, e = pcall(function()
        local B = reqscript('ai-builder')
        local data = type(B.load_projects) == 'function' and B.load_projects() or nil
        each(type(data) == 'table' and data.list or nil, function(p)
            if type(p) ~= 'table' or type(p.z) ~= 'number' then return end
            each(p.soil_floors, function(k)
                local x, y = tostring(k):match('^(%-?%d+),(%-?%d+)$')
                if x then
                    R.soil_recorded = R.soil_recorded + 1
                    claim('soil_floors', tonumber(x), tonumber(y), p.z)
                end
            end)
        end)
    end)
    if not ok then err('soil_floors', e) end
    -- (0.105.30 seams) the wing walls, from ai-gates' saved record (by way
    -- in), so they count as wings before a scan and never as gate pieces
    ok, e = pcall(function()
        local d = site_get('ai-overseer/wings')
        for _, list in pairs(type(d) == 'table' and d or {}) do
            each(list, function(v) claim('wings', unkey(v)) end)
        end
    end)
    if not ok then err('wings', e) end
    -- the ways in (scanned this session: ai-gates keeps them in memory)
    ok, e = pcall(function()
        local G = reqscript('ai-gates')
        local list = type(G.GATES) == 'table' and G.GATES.entrances or nil
        each(list, function(en)
            if type(en) ~= 'table' then return end
            each(en.wings, function(v) claim('wings', unkey(v)) end)
            each(en.wing_pieces, function(v) claim('wings', unkey(v)) end)
            local cavern = en.kind == 'cavern'
            each(en.pieces, function(v) claim(cavern and 'cavern_walls' or 'gate_pieces', unkey(v)) end)
            each(en.seal_pieces, function(v) claim('cavern_walls', unkey(v)) end)
            if en.x and en.y and en.z then
                local r = (tonumber(en.width) or 1) + (cavern and CAVERN_BOX or GATE_BOX)
                for z = en.z - 1, en.z + 1 do
                    box(z, {cat = cavern and 'cavern_walls' or 'gate_pieces', x1 = en.x - r, y1 = en.y - r,
                            x2 = en.x + r, y2 = en.y + r, where = (not cavern) and 'surface' or nil,
                            walls = true})
                end
            end
        end)
    end)
    if not ok then err('gates', e) end
    -- the projects underground: built walls in their box and its edge (room
    -- repairs), built floors there (soil floors)
    ok, e = pcall(function()
        local B = reqscript('ai-builder')
        each(B.registry_report(), function(p)
            local b = type(p) == 'table' and p.bounds or nil
            if type(b) == 'table' and b.x1 and b.z then
                box(b.z, {cat = 'room_walls', x1 = b.x1 - 1, y1 = b.y1 - 1, x2 = b.x2 + 1, y2 = b.y2 + 1,
                          walls = true, floors = 'soil_floors'})
            end
        end)
    end)
    if not ok then err('projects', e) end
    return R
end

local function in_box(b, x, y) return x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 end

-- Which of the AI's records claims a built tile (nil: none).
function ai_claim(R, x, y, z, shape, surface)
    local c = R.sets[key(x, y, z)]
    if c then return c end
    for _, b in ipairs(R.boxes[z] or {}) do
        if in_box(b, x, y) and (b.where == nil or (b.where == 'surface') == surface) then
            if not b.walls then return b.cat end
            if shape == 'wall' or shape == 'fortification' then return b.cat end
            if b.floors and shape == 'floor' then return b.floors end
        end
    end
    return nil
end

-- The Construction buildings not built yet: placed, waiting for a builder or
-- for their item.
function planned_constructions()
    local out = {n = 0, by_type = {}}
    local ctype = df.building_type.Construction
    for _, b in ipairs(df.global.world.buildings.all) do
        local okt, t = pcall(function() return b:getType() end)
        if okt and t == ctype then
            out.n = out.n + 1
            local okn, n = pcall(function() return df.construction_type[b.type] end)
            n = okn and n or 'other'
            out.by_type[n] = (out.by_type[n] or 0) + 1
        end
    end
    return out
end

-- "Built: N walls, M floors (P% blocks), K above ground; Q waiting."
function line_of(s)
    if type(s) ~= 'table' or not s.by_shape then return nil end
    local q = s.planned and s.planned.n or 0
    return ('Built: %d walls, %d floors (%s blocks), %d above ground; %d waiting.'):format(
        s.by_shape.wall, s.by_shape.floor, s.block_pct and (s.block_pct .. '%') or '-',
        s.surface.total, q)
end

local function game_tick()
    local ok, t = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok and t or nil
end

local function site_id()
    local ok, s = pcall(function() return df.global.plotinfo.site_id end)
    return ok and s or nil
end

-- The survey (see the top). `fresh`: walk again even if one from today is kept.
function survey(fresh)
    local now, site = game_tick(), site_id()
    local c = SURVEY_CACHE
    if not fresh and c and now and c.tick and c.site == site and now >= c.tick and now - c.tick < SURVEY_CACHE_TICKS then
        return c.result
    end
    local t0 = os.clock()
    local out = {total = 0, by_shape = counts(SHAPE_KEYS), by_item = counts(ITEM_KEYS),
                 surface = counts(SHAPE_KEYS), underground = counts(SHAPE_KEYS),
                 roofed_surface_tiles = 0, ai = counts(AI_KEYS), wall_tops = 0}
    out.surface.total, out.underground.total = 0, 0
    local list, where = construction_list()
    out.where = where
    local R = ai_regions()
    out.ai_errors = R.errors
    out.soil_floors_placed = R.soil_recorded   -- placed by floor_rooms (ai.soil_floors: of those, built)
    if list == nil then
        out.missing = true          -- [verify] neither field: the structure moved
    else
        -- (0.105.33) a walk cut short resumes next time where it stopped
        -- (it always restarted at the first record: a big fort's counts were
        -- always the same first records), round to the start again
        local start = (SURVEY_RESUME and SURVEY_RESUME.site == site) and SURVEY_RESUME.at or 0
        local n, stopped = 0, nil
        local function visit(i, con)
            n = n + 1
            if n % 256 == 0 and os.clock() - t0 > SURVEY_SECONDS then
                out.partial = true
                stopped = i - 1
                return false
            end
            local okp, x, y, z, top, item = pcall(function()
                local p = con.pos
                return p.x, p.y, p.z, con.flags.top_of_wall, con.item_type
            end)
            if okp then
                if top then
                    out.wall_tops = out.wall_tops + 1
                else
                    local shape = shape_at(x, y, z)
                    if not SHAPES[shape:upper()] then shape = 'other' end
                    local d = flags_at(x, y, z)
                    local surface = d ~= nil and not subterranean(d)
                    out.total = out.total + 1
                    out.by_shape[shape] = out.by_shape[shape] + 1
                    local it = item_name(item)
                    out.by_item[it] = out.by_item[it] + 1
                    local side = surface and out.surface or out.underground
                    side.total = side.total + 1
                    side[shape] = side[shape] + 1
                    -- a built floor on the surface roofs the tile under it
                    if surface and shape == 'floor' then
                        local below = flags_at(x, y, z - 1)
                        if below and not below.outside and not subterranean(below)
                                and WALKABLE[shape_at(x, y, z - 1)] then
                            out.roofed_surface_tiles = out.roofed_surface_tiles + 1
                        end
                    end
                    local cat = ai_claim(R, x, y, z, shape, surface)
                    if cat and WALLS_ONLY[cat] and shape ~= 'wall' and shape ~= 'fortification' then cat = nil end
                    if cat == 'soil_floors' and shape ~= 'floor' then cat = nil end
                    if cat then out.ai[cat] = out.ai[cat] + 1 end
                end
            end
            return true
        end
        local i = 0
        for _, con in ipairs(list) do          -- from the resume point on
            i = i + 1
            if i > start and not visit(i, con) then break end
        end
        if stopped == nil and start > 0 then
            i = 0
            for _, con in ipairs(list) do      -- then the records before it
                i = i + 1
                if i > start or not visit(i, con) then break end
            end
        end
        SURVEY_RESUME = stopped and {site = site, at = stopped} or nil
        if start > 0 then out.resumed_at = start end
    end
    local okq, planned = pcall(planned_constructions)
    out.planned = okq and planned or {n = 0, by_type = {}, error = tostring(planned):sub(1, 120)}
    -- the finished halls' soil still bare (ai-builder-rooms soil_floor_report):
    -- {{project_id, kind, elevation, tiles, floored}...}, for the brain's soil
    -- floor step (planner_construct reads constructions.soil_floors)
    local okf, rep = pcall(function() return reqscript('ai-builder').soil_floor_report() end)
    if okf and type(rep) == 'table' then
        out.soil_floors, out.soil_floors_left = rep.projects, rep.tiles
    end
    out.block_pct = out.total > 0 and math.floor(100 * out.by_item.blocks / out.total + 0.5) or nil
    out.line = line_of(out)
    out.ms = math.floor((os.clock() - t0) * 1000)
    SURVEY_CACHE = {tick = now, site = site, result = out}
    return out
end
