-- ai-builder-projects: the project lifecycle: projects saved with the fort, start, dig
-- progress, furnish, finish, engrave, cancel; founding; polish.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-projects'] = '0.105.97'   -- (0.105.26) bumped with BRIDGE_VERSION

local info, ez = info, ez

---------------------------------------------------------------------------
-- Projects, saved with the fort
---------------------------------------------------------------------------

local function decode_projects()
    -- (0.105.33, L8) through ai-util's site_get: a value that isn't a table reads as none
    local data = site_get(PROJECTS_KEY)
    data.next_id = math.tointeger(data.next_id) or 1
    data.list = type(data.list) == 'table' and data.list or {}
    return data
end

-- (0.105.40 E3) A report read the projects 10-20 times, each a JSON decode of
-- the whole record (old_areas up to 600 boxes): inside a report (ai-util's
-- REPORT_CTX) it is decoded once and each caller gets its own deep copy (a
-- caller may change its copy and save it); save_projects drops the decoded
-- one, so a read after a save decodes the saved record again. Outside a
-- report every call decodes, as before.
function load_projects()
    local okc, ctx = pcall(function() return util_module().REPORT_CTX end)
    if not (okc and type(ctx) == 'table') then return decode_projects() end
    if ctx.projects == nil then ctx.projects = decode_projects() end
    return util_module().deep_copy(ctx.projects)
end

OLD_AREAS_MAX = 600       -- (0.104.19) outlines of levels dropped from the list, kept for safety
MOOD_SHOP_OPEN_MAX = NEED_SLOTS or 3    -- (R1 g6) a mood's workshops level takes no slot while fewer urgent workshops levels are open
                                        -- (R2 h3) the small needs' pool (NEED_SLOTS, ai-builder.lua): one number

function save_projects(data)
    -- keep every open project, and only the most recent closed ones;
    -- (0.104.19) a dropped level's outline is kept (`old_areas`): the quarry
    -- and vein mining stay out of every level the AI ever dug, not only the
    -- last 20 (Enxah: the quarry ate the walls of the older bedroom levels)
    local closed, kept_free = 0, 0
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
        -- (0.105.54) a finished workshops level with free rooms stays (WORKSHOP_KEEP_FREE at most):
        -- the next workshops go into it (join_workshop_level)
        local free_level = p.kind == 'workshops' and p.phase == 'done' and p.parent == nil
            and (math.tointeger(p.free_left) or 0) > 0 and kept_free < (WORKSHOP_KEEP_FREE or 0)
        if free_level then kept_free = kept_free + 1 end
        if p.phase ~= 'dig' and p.phase ~= 'furnish' and p.phase ~= 'decorate' and not cavern_well
                and not free_level then
            closed = closed + 1
            if closed > KEEP_CLOSED_PROJECTS then
                for _, a in ipairs(project_areas(p)) do
                    -- (0.105.40b fix) a well's outline marked: ai-insane leaves its doors to the well's rules
                    table.insert(data.old_areas, {x1 = a.x1, y1 = a.y1, x2 = a.x2, y2 = a.y2, z = a.z,
                                                  well = p.kind == 'well' or nil})
                end
                if p.phase == 'done' then data.dropped_done = data.dropped_done + 1 end
                table.remove(data.list, i)
            end
        end
    end
    while #data.old_areas > OLD_AREAS_MAX do table.remove(data.old_areas, 1) end
    -- (0.105.40 E3) the report's decoded copy is stale now
    -- (K48-K4b) and the in-game timers' copies (watch_projects)
    PROJECTS_GEN = (PROJECTS_GEN or 0) + 1
    pcall(function() local c = util_module().REPORT_CTX; if type(c) == 'table' then c.projects = nil end end)
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

function undo_dig(dig_cells, stairs, z, anchor, stair)
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

-- (0.105.41) The corridor and avenue a site adds (its `extra`), as a list of
-- anchor-relative tiles, sorted: kept with the project for ai-traffic (High).
local function extra_list(extra)
    local out = {}
    for x, col in pairs(type(extra) == 'table' and extra or {}) do
        for y in pairs(col) do table.insert(out, {x = x, y = y}) end
    end
    table.sort(out, function(a, b) return a.x < b.x or (a.x == b.x and a.y < b.y) end)
    return out
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
    -- (0.105.54) nor a free room's middle: a workshop is put there later
    for _, c in ipairs(type(L.rooms_at) == 'table' and L.rooms_at or {}) do
        if tostring(c.text):sub(1, 4) == 'free' then
            for dx = -1, 1 do
                for dy = -1, 1 do covered[(c.x + dx) .. ',' .. (c.y + dy)] = true end
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

---------------------------------------------------------------------------
-- (0.105.54, layout option A part 2) Workshops grouped onto shared levels.
-- Nearly every new workshop began a workshops level of its own (B: 20 of 25
-- levels held one shop, ~250 dug tiles each, ~18 tiles apart). Every
-- start_project of kind 'workshops' (every rule's "place a workshop": the
-- industry, the bottleneck's second shops, paper, moods, needs, ...) now
-- goes into an AI workshops level that stands first:
--   1. a free room (a slot a level was planned with, empty) of a level of
--      the shop's industry (WORKSHOP_GROUPS); a room planned for that very
--      shop first; a stone user beside the level's ore pile;
--   2. else that level extended: its layout made again with more rooms, the
--      new rooms (and any corridor they need) dug as a small project of its
--      own linked to the level (`parent`), when the new tiles keep the old
--      ones exactly (a ring's loop that would have to grow: no);
--   3. then the same in a level of another industry;
-- only then a new level, planned for several shops at once (at least
-- WORKSHOP_LEVEL_ROOMS rooms, the brain's spare_for naming what comes next).
-- join = false keeps a level where the rule put it; 'band': only a level in
-- the plan's elevation band (a placement custom: field kitchens).
---------------------------------------------------------------------------

WORKSHOP_LEVEL_ROOMS = 4     -- a new workshops level is planned with at least this many rooms
WORKSHOP_EXTEND_SPARE = 2    -- an extension digs at most this many empty rooms beyond the shops
WORKSHOP_KEEP_FREE = 6       -- finished levels with free rooms kept on the list (not dropped) at most

WORKSHOP_GROUPS = {
    MetalsmithsForge = 'smithing', Smelter = 'smithing', WoodFurnace = 'smithing',
    Kiln = 'smithing', GlassFurnace = 'smithing',
    Craftsdwarfs = 'crafts', Jewelers = 'crafts', Masons = 'crafts', Mechanics = 'crafts',
    Carpenters = 'crafts', Bowyers = 'crafts',
    Kitchen = 'food', Still = 'food', Butchers = 'food', Tanners = 'food', Farmers = 'food',
    Fishery = 'food', Millstone = 'food', Quern = 'food', ScrewPress = 'food',   -- (slurry milled, then pressed)
    Loom = 'cloth', Clothiers = 'cloth', Leatherworks = 'cloth',
    Ashery = 'soap', SoapMaker = 'soap',
}
-- each industry's shops in the order a fort usually wants them (a new level's spare rooms)
WORKSHOP_GROUP_ORDER = {
    smithing = {'Smelter', 'MetalsmithsForge', 'WoodFurnace', 'Kiln', 'GlassFurnace'},
    crafts = {'Craftsdwarfs', 'Masons', 'Mechanics', 'Jewelers', 'Carpenters', 'Bowyers'},
    food = {'Kitchen', 'Still', 'Butchers', 'Tanners', 'Farmers', 'Fishery', 'Quern', 'Millstone', 'ScrewPress'},
    cloth = {'Loom', 'Clothiers', 'Leatherworks'},
    soap = {'Ashery', 'SoapMaker'},
}
-- shops whose input lies in the ore pile room (stone, ore): a free room nearest it
WORKSHOP_PILE_USERS = {Masons = true, Craftsdwarfs = true, Mechanics = true, Smelter = true, Jewelers = true}

local JOIN_PHASES = {dig = true, furnish = true, decorate = true, done = true}

-- A new level's planned rooms beyond its shops: the brain's spare/spare_for,
-- else (no word from it) the shops' industry-mates up to WORKSHOP_LEVEL_ROOMS.
function workshop_spares(params)
    local shops = type(params.shops) == 'table' and params.shops or {}
    local spare = math.tointeger(params.spare)
    local names = type(params.spare_for) == 'table' and params.spare_for or nil
    if spare == nil then
        spare = math.max(0, WORKSHOP_LEVEL_ROOMS - #shops)
        if names == nil then
            names = {}
            local have = {}
            for _, s in ipairs(shops) do have[s] = true end
            for _, s in ipairs(WORKSHOP_GROUP_ORDER[WORKSHOP_GROUPS[shops[1] or ''] or ''] or {}) do
                if #names < spare and not have[s] then table.insert(names, s) end
            end
        end
    end
    spare = math.max(spare, names and #names or 0)
    return math.max(0, math.min(spare, layouts.WORKSHOP_ROOMS_MAX - #shops)), names
end

-- The level's layout made again from its own params (extra: more empty
-- rooms), or nil.
local function level_layout(p, extra)
    local pr = p.params
    local ok, L = pcall(layouts.make, 'workshops', {shops = pr.shops, style = pr.style,
                                                    spare = (math.tointeger(pr.spare) or 0) + (extra or 0),
                                                    spare_for = pr.spare_for})
    return ok and L or nil
end

-- Every tile the level has (its own cells, what its extensions added, the stair), anchor-relative.
local function level_known(p)
    local t = layouts.tiles_from_dig(cells_of(p, 'dig'))
    for _, c in ipairs(type(p.ext_tiles) == 'table' and p.ext_tiles or {}) do
        if type(c) == 'table' and math.tointeger(c.x) and math.tointeger(c.y) then add(t, c.x, c.y) end
    end
    add(t, 0, 0)
    return t
end

-- The made-again layout is the level as it was dug: each of its workshops
-- where the level's own cells put it, each of its tiles one of the level's.
-- (A level dug by an older layout, or turned another way: false.)
local function layout_matches(L, p, known)
    local built = {}
    for _, c in ipairs(cells_of(p, 'build')) do built[c.x .. ',' .. c.y] = c.text end
    for _, c in ipairs(L.build) do
        if built[c.x .. ',' .. c.y] ~= c.text then return false end
    end
    for x, col in pairs(L.tiles) do
        for y in pairs(col) do if not has(known, x, y) then return false end end
    end
    return true
end

local function level_group(p)
    local s = type(p.params) == 'table' and type(p.params.shops) == 'table' and p.params.shops[1] or nil
    return s and WORKSHOP_GROUPS[s] or nil
end

-- The level's free rooms: {x, y, planned} (centre tile, anchor-relative), and its pile room's centre.
local function free_rooms(p, L)
    local taken = type(p.taken) == 'table' and p.taken or {}
    local out, pile = {}, nil
    for _, c in ipairs(L.rooms_at or {}) do
        local tag = tostring(c.text)
        if tag == 'pile' then pile = {x = c.x, y = c.y} end
        if tag:sub(1, 4) == 'free' and taken[c.x .. ',' .. c.y] == nil then
            table.insert(out, {x = c.x, y = c.y, planned = tag:match('^free:(.+)$')})
        end
    end
    return out, pile
end

-- A free room still empty in the game: its middle 3x3 dug (or being dug,
-- while the level digs) with nothing built on it.
local function room_empty(p, r)
    local a = anchor_of(p)
    for dx = -1, 1 do
        for dy = -1, 1 do
            local t = tile_info(a.x + r.x + dx, a.y + r.y + dy, p.z)
            if not t or t.building then return false end
            if p.phase ~= 'dig' and t.shape == 'WALL' then return false end
        end
    end
    return true
end

-- Which free room each shop goes to: the room planned for it, else beside
-- the pile room (a stone user), else the first. nil when they don't all fit.
local function pick_rooms(p, shops, rooms, pile)
    local left = {}
    for _, r in ipairs(rooms) do if room_empty(p, r) then table.insert(left, r) end end
    if #left < #shops then return nil end
    local out = {}
    for i, name in ipairs(shops) do
        local best, bi
        for j, r in ipairs(left) do
            local score = (r.planned == name) and 0 or 1000
            if pile and WORKSHOP_PILE_USERS[name] then
                score = score + math.abs(r.x - pile.x) + math.abs(r.y - pile.y)
            else
                score = score + j               -- the rooms in order
            end
            if not best or score < best then best, bi = score, j end
        end
        out[i] = left[bi]
        table.remove(left, bi)
    end
    return out
end

local function shop_cells(shops, rooms)
    local build, furniture = {}, {}
    for i, name in ipairs(shops) do
        table.insert(build, {x = rooms[i].x, y = rooms[i].y, text = layouts.WORKSHOPS[name]})
        furniture[name] = (furniture[name] or 0) + 1
    end
    return build, furniture
end

local function box_of(cells, a, z, pad)
    local x1, y1, x2, y2
    for _, c in ipairs(cells) do
        x1, x2 = math.min(x1 or c.x, c.x), math.max(x2 or c.x, c.x)
        y1, y2 = math.min(y1 or c.y, c.y), math.max(y2 or c.y, c.y)
    end
    return {x1 = a.x + x1 - pad, y1 = a.y + y1 - pad, x2 = a.x + x2 + pad, y2 = a.y + y2 + pad, z = z}
end

local function mark_taken(p, shops, rooms)
    p.taken = type(p.taken) == 'table' and p.taken or {}
    for i, name in ipairs(shops) do p.taken[rooms[i].x .. ',' .. rooms[i].y] = name end
    p.free_left = math.max(0, (math.tointeger(p.free_left) or 0) - #shops)
end

-- An annex: the level's own small project for what is added to it (the
-- ordinary lifecycle: dug, furnished, done).
local function annex_project(data, parent, shops, dig, build, furniture, area, now, how, designated, urgent)
    local a = anchor_of(parent)
    local sm = {workshops = shops, joins = parent.id, how = how}
    return {
        id = data.next_id, kind = 'workshops', phase = 'dig', parent = parent.id,
        urgent = urgent or nil,
        params = {shops = shops, style = {}, joins = parent.id},
        stair = parent.stair, anchor = {x = a.x, y = a.y}, z = parent.z, area = area,
        corridor = 0, new_corridor = 0, stairs = {}, summary = sm, furniture = furniture, links = {},
        cells = {dig = dig, build = build, place = {}, zone = {}, smooth = {}, engrave = {}},
        started = now, designated = designated, plan = parent.plan, in_district = parent.in_district,
    }
end

local function joined_result(p, parent, how, tiles, dry_run)
    return {ok = true, dry_run = dry_run or nil, project_id = p and p.id or nil, kind = 'workshops',
            joined = parent.id, how = how, z = parent.z, elevation = ez(parent.z),
            in_district = parent.in_district, anchor = anchor_of(parent),
            corridor = 0, new_corridor = 0, extends_stairs = false,
            tiles = tiles, designated = tiles,
            summary = {workshops = p and p.summary.workshops or nil, joins = parent.id, how = how}}
end

-- 1. into free rooms of `parent`
local function join_free(data, parent, L, params, now, dry_run)
    local shops = params.shops
    local rooms, pile = free_rooms(parent, L)
    if parent.phase == 'dig' then
        -- (its furnishing places them: only rooms of its own dig, not an extension's still to come)
        local own = layouts.tiles_from_dig(cells_of(parent, 'dig'))
        local kept = {}
        for _, r in ipairs(rooms) do if has(own, r.x, r.y) then table.insert(kept, r) end end
        rooms = kept
    end
    local picked = pick_rooms(parent, shops, rooms, pile)
    if not picked then return nil end
    if dry_run then return joined_result(nil, parent, 'free_room', 0, true) end
    local build, furniture = shop_cells(shops, picked)
    if parent.phase == 'dig' then
        -- still being dug: the level's own furnishing places them
        parent.cells.build = parent.cells.build or {}
        for _, c in ipairs(build) do table.insert(parent.cells.build, c) end
        parent.furniture = type(parent.furniture) == 'table' and parent.furniture or {}
        for k, v in pairs(furniture) do parent.furniture[k] = (parent.furniture[k] or 0) + v end
        parent.summary = type(parent.summary) == 'table' and parent.summary or {}
        local list = {}
        for _, s in ipairs(type(parent.summary.workshops) == 'table' and parent.summary.workshops or {}) do
            table.insert(list, s)
        end
        for _, s in ipairs(shops) do table.insert(list, s) end
        parent.summary.workshops = list
        mark_taken(parent, shops, picked)
        if not save_projects(data) then return {ok = false, error = 'could not save the project with the fort'} end
        local r = joined_result(parent, parent, 'free_room', 0)
        r.summary.workshops = shops
        return r
    end
    -- dug already: an annex whose 'dig' is the rooms' middles (dug: it is furnished next)
    local dig = {}
    for _, r in ipairs(picked) do table.insert(dig, {x = r.x - 1, y = r.y - 1, text = 'd(3x3)'}) end
    local p = annex_project(data, parent, shops, dig, build, furniture, box_of(build, anchor_of(parent), parent.z, 3),
                            now, 'free_room', 0, params.urgent == true)
    mark_taken(parent, shops, picked)
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    if not save_projects(data) then return {ok = false, error = 'could not save the project with the fort'} end
    return joined_result(p, parent, 'free_room', 0)
end

-- 2. `parent` extended by the shops' rooms (and up to WORKSHOP_EXTEND_SPARE empty ones)
local function join_extend(data, parent, L0, known, params, now, dry_run, open)
    local shops = params.shops
    local a = anchor_of(parent)
    local spare_want = math.min(WORKSHOP_EXTEND_SPARE, math.max(0, math.tointeger(params.spare) or 0))
    local why
    for _, extra in ipairs(spare_want > 0 and {#shops + spare_want, #shops} or {#shops}) do
        local L = level_layout(parent, extra)
        if not L then return nil, 'the level\'s layout could not be made again' end
        -- the old level unchanged: its tiles, workshops and rooms where they were
        local same = layout_matches(L0, {cells = {build = L.build}}, L.tiles)
        local old_rooms = {}
        for _, c in ipairs(L.rooms_at or {}) do old_rooms[c.x .. ',' .. c.y] = c.text end
        for _, c in ipairs(L0.rooms_at or {}) do
            if old_rooms[c.x .. ',' .. c.y] ~= c.text then same = false end
        end
        if not same then
            why = 'growing it moves its rooms'
        else
            local delta, cells, n = {}, {}, 0
            for x, col in pairs(L.tiles) do
                for y in pairs(col) do
                    if not has(known, x, y) then
                        add(delta, x, y); n = n + 1
                        table.insert(cells, {x = x, y = y, text = 'd'})
                    end
                end
            end
            -- the new rooms (those L0 hasn't), in order
            local new_rooms = {}
            for _, c in ipairs(L.rooms_at or {}) do
                local found = false
                for _, o in ipairs(L0.rooms_at or {}) do if o.x == c.x and o.y == c.y then found = true end end
                if not found then table.insert(new_rooms, {x = c.x, y = c.y}) end
            end
            if n == 0 or #new_rooms < #shops then
                why = 'no new room'
            else
                local pseudo = {tiles = delta, bounds = nil}
                local b = box_of(cells, {x = 0, y = 0}, parent.z, 0)
                pseudo.bounds = {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2}
                -- kept clear of every other open project (not the level's own, nor its annexes)
                local others = {}
                for _, o in ipairs(open) do
                    if o ~= parent and o.parent ~= parent.id and type(o.area) == 'table' then
                        table.insert(others, o.area)
                    end
                end
                local ok, why2, area = check_site(pseudo, {}, a.x, a.y, parent.z, others, nil,
                    function(x, y) return has(known, x - a.x, y - a.y) end)
                if not ok then
                    why = why2
                else
                    local dig = params.urgent == true and prioritized(cells, URGENT_DIG_PRIORITY) or cells
                    local dry = quickfort_apply('dig', dig, parent.z, a.x, a.y, 'run', true)
                    if stat(dry, 'dig_designated') ~= n or stat(dry, 'dig_invalid_tiles') > 0
                            or stat(dry, 'out_of_bounds') > 0 or stat(dry, 'invalid_keys') > 0 then
                        why = ('dry run disagreed: %d of %d tiles designatable'):format(stat(dry, 'dig_designated'), n)
                    elseif dry_run then
                        return joined_result(nil, parent, 'extension', n, true)
                    else
                        local real = quickfort_apply('dig', dig, parent.z, a.x, a.y)
                        local got = stat(real, 'dig_designated')
                        local picked = {}
                        for i = 1, #shops do picked[i] = new_rooms[i] end
                        local build, furniture = shop_cells(shops, picked)
                        -- its area: round its workshops (what its furnishing counts); the
                        -- whole new dig is kept as a second box (project_areas)
                        local p = annex_project(data, parent, shops, dig, build, furniture,
                                                box_of(build, a, parent.z, 3), now, 'extension', got,
                                                params.urgent == true)
                        p.areas = {area}
                        -- the level now has `extra` rooms more; the shops take the first of them
                        parent.params.spare = (math.tointeger(parent.params.spare) or 0) + extra
                        parent.ext_tiles = type(parent.ext_tiles) == 'table' and parent.ext_tiles or {}
                        for _, c in ipairs(cells) do table.insert(parent.ext_tiles, {x = c.x, y = c.y}) end
                        parent.free_left = (math.tointeger(parent.free_left) or 0) + extra
                        mark_taken(parent, shops, picked)
                        data.next_id = data.next_id + 1
                        table.insert(data.list, p)
                        if not save_projects(data) then
                            undo_dig(dig, {}, parent.z, a, parent.stair)
                            return {ok = false, error = 'could not save the project with the fort, so it was undone'}
                        end
                        local r = joined_result(p, parent, 'extension', n)
                        r.designated = got
                        r.area = area
                        return r
                    end
                end
            end
        end
    end
    return nil, why
end

-- Returns the start_project result when the shops went into a standing
-- level, or nil and why none took them (a new level is dug then).
function join_workshop_level(params, data, now, dry_run, open, ceil_z)
    if params.join == false then return nil, 'the rule keeps its own level' end
    local shops = type(params.shops) == 'table' and params.shops or {}
    if #shops == 0 then return nil end
    local band = params.join == 'band' and plan_band(params.plan) or nil
    if params.join == 'band' and not band then return nil, 'no band to join in' end
    local group = WORKSHOP_GROUPS[shops[1]]
    -- only a level the dwarves can walk to (its stair in one of their walk groups; unknown: any)
    local okg, groups = pcall(citizen_groups)
    if not okg or type(groups) ~= 'table' then groups = {} end
    local any_group = next(groups) == nil
    local cands = {}
    for _, p in ipairs(data.list) do
        if p.kind == 'workshops' and p.parent == nil and p.floor == nil   -- (layout B) a floor's shops are no classic level
                and JOIN_PHASES[p.phase] and not p.unreached
                and type(p.params) == 'table' and type(p.params.shops) == 'table' and #p.params.shops > 0
                and type(p.cells) == 'table' and type(anchor_of(p)) == 'table' and math.tointeger(p.z)
                and (not ceil_z or p.z <= ceil_z)
                and (not band or (p.z >= band.lo and p.z <= band.hi))
                and (any_group or (type(p.stair) == 'table' and math.tointeger(p.stair.x)
                     and groups[walk_group(p.stair.x, p.stair.y, p.z)] == true)) then
            table.insert(cands, p)
        end
    end
    -- the newest first (nearest where the fort grows now)
    table.sort(cands, function(x, y) return (x.id or 0) > (y.id or 0) end)
    local whys = {}
    local made = {}
    local function layout_of(p)
        if made[p.id] == nil then
            local L0 = level_layout(p, 0)
            local known = level_known(p)
            if L0 and layout_matches(L0, p, known) then
                made[p.id] = {L = L0, known = known}
            else
                made[p.id] = false
            end
        end
        return made[p.id] or nil
    end
    for _, same in ipairs({true, false}) do
        -- (layout B) start_project asks for the free rooms alone first (join_steps), the floor next
        for _, step in ipairs(type(params.join_steps) == 'table' and params.join_steps or {'free', 'extend'}) do
            for _, p in ipairs(cands) do
                if (level_group(p) == group) == same then
                    local m = layout_of(p)
                    if m then
                        local r, why
                        if step == 'free' then
                            r = join_free(data, p, m.L, params, now, dry_run)
                        else
                            r, why = join_extend(data, p, m.L, m.known, params, now, dry_run, open)
                        end
                        if r then return r end
                        if why and #whys < 3 then table.insert(whys, ('level %d: %s'):format(p.id, why)) end
                    end
                end
            end
        end
    end
    return nil, #whys > 0 and table.concat(whys, '; ') or nil
end

-- params: kind + layout params (rooms, room_size, tables, piles, shops).
-- dry_run: find the site and check it with Quickfort, but change nothing.
function start_project(params, now, dry_run)
    OFFSET = elevation_offset()
    local kind = params.kind
    -- (0.105.54) a workshops level is planned for several shops (workshop_spares)
    if kind == 'workshops' then
        params.spare, params.spare_for = workshop_spares(params)
    end
    local L, err = layouts.make(kind, params)
    if not L then return {ok = false, rejected = true, error = err} end
    local data = load_projects()
    local open = open_projects(data)
    -- (a farm level gets one more slot: food comes before everything else)
    -- (urgent: what a well or a strange mood is waiting for; a dwarf's
    -- sanity or the fort's water doesn't wait for a bedroom level)
    -- (0.104.12) two urgent ones beyond the two (Enxah: soap for festering
    -- wounds and tombs for 35 dead both waited on one extra slot)
    -- (R1 g6) a workshops level a strange mood waits for (params.mood) takes no
    -- slot: R-AD, A's jeweller's refused 19 times and D's 15 by "already N
    -- unfinished building projects" while moods wanted a cut gem; two died
    -- (urgent workshops levels open at most MOOD_SHOP_OPEN_MAX: one stuck
    -- furnishing is no "coming" shop to the brain, so another would follow)
    -- (R2 h3) one pool with the other small needs (need_slot_free): a paper shop, a
    -- well, a still or kitchen while drink or meals are short
    local mood_shop = need_slot_free(open, params, kind)
    -- (r2h4) the crossbow squad's Bowyer's workshop (params.crossbows, the bridge
    -- lets it through for a lone Bowyers) takes no slot either: one such level
    -- open at a time, and not past MOOD_SHOP_OPEN_MAX urgent workshops levels
    local bowyer_shop = params.crossbows == true and kind == 'workshops'
    if bowyer_shop then
        local n = 0
        for _, q in ipairs(open) do
            local qp = type(q.params) == 'table' and q.params or {}
            if q.kind == 'workshops' and (q.crossbows == true or qp.crossbows == true) then
                bowyer_shop = false
            elseif q.kind == 'workshops' and (q.urgent == true or qp.urgent == true) then
                n = n + 1
            end
        end
        bowyer_shop = bowyer_shop and n < MOOD_SHOP_OPEN_MAX
        mood_shop = mood_shop or bowyer_shop
    end
    if not mood_shop and #open >= slot_cap(open) + (params.urgent == true and URGENT_EXTRA or (kind == 'farms' and 1 or 0)) then
        return {ok = false, rejected = true,
                error = ('already %d unfinished building projects'):format(#open)}
    end
    -- (layout B) hallway-first floors: a new level is offered to its floor's main hall first
    -- (floor_site, ai-builder-floors.lua), and placed as before when the floor says no. Off
    -- (the Rules switch at classic, a kind that stays classic, the floor parts absent, the
    -- settings unreadable) nothing below runs differently.
    local floors_on = type(floor_site) == 'function' and type(floor_mode) == 'function'
        and FLOOR_KINDS and FLOOR_KINDS[kind] and params.floor ~= false and params.join ~= false
        and floor_mode() == 'hallway'
    -- (0.105.54) a workshop goes into a standing workshops level first (join_workshop_level)
    -- (layout B) with the floors on only into a free room now; the level is extended after the floor refused
    local join_why
    if floors_on and kind == 'workshops' then params.join_steps = {'free'} end
    if kind == 'workshops' then
        local ceil0 = math.tointeger(params.max_elev)
        local okj, jr, jwhy = pcall(join_workshop_level, params, data, now, dry_run, open,
                                    ceil0 and (ceil0 - OFFSET) or nil)
        if okj and jr then return jr end
        if okj then join_why = jwhy else join_why = 'failed: ' .. tostring(jr) end
    end
    params.join_steps = nil
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
    -- (0.105.47, R2 item 3) a hospital off the stairs (ai-builder-sites stair_gap_ok):
    -- its own stair's and the main stair's (the most used, the first listed)
    if kind == 'hospital' then
        L.stair_gap = HOSPITAL_STAIR_GAP
        L.main_stair = stairs[1]
    end
    local plan = type(params.plan) == 'table' and params.plan or nil
    -- (0.105.23, 14.1 step 4c) max_elev: no level above it (the Deep mine keeps under the surface)
    local ceil = math.tointeger(params.max_elev)
    local site, why2, floor_why, floor_marks, floor_big
    if floors_on then
        local okf, s2, L2, marks, big = pcall(floor_site, params, stairs, reserved, data, ceil and (ceil - OFFSET) or nil)
        if okf and s2 then
            site, L = s2, L2      -- everything below reads the floor's composed layout
        else
            floor_why = tostring(okf and L2 or s2):sub(1, 300)      -- (nil, why, marks) or the error
            floor_marks = okf and marks or nil
            floor_big = okf and type(big) == 'table' and big or nil   -- (r3 g2) too big for a run: for the brain
        end
    end
    if not site and floors_on and kind == 'workshops' then          -- the classic way: a standing level extended
        params.join_steps = nil
        local okj, jr, jwhy = pcall(join_workshop_level, params, data, now, dry_run, open, ceil and (ceil - OFFSET) or nil)
        if okj and jr then jr.not_on_floor = floor_why; jr.floor_big = floor_big; return jr end
        if okj then join_why = jwhy or join_why else join_why = 'failed: ' .. tostring(jr) end
    end
    -- (r3 g2) with the floors on, the classic level keeps clear of the floors' hubs and planned halls
    local reserved_open = reserved
    -- (r3 V2) a level sent classic on purpose (floor = false: too big for any run, a holy level with only
    -- soil left, a field custom, a landmark) keeps clear too, while the fort's floors are on
    local keep_on = floors_on or (type(floor_mode) == 'function' and FLOOR_KINDS ~= nil and FLOOR_KINDS[kind]
        and (params.floor == false or params.join == false)
        and select(2, pcall(floor_mode)) == 'hallway')
    if not site and keep_on and type(floor_keep_boxes) == 'function' then
        local okk, keep = pcall(floor_keep_boxes, params, stairs)
        if okk and type(keep) == 'table' and #keep > 0 then
            reserved = {}
            for _, r in ipairs(reserved_open) do table.insert(reserved, r) end
            for _, r in ipairs(keep) do table.insert(reserved, r) end
        end
    end
    if not site then site, why2 = choose_site(L, stairs, reserved, plan, ceil and (ceil - OFFSET) or nil) end
    reserved = reserved_open
    if not site and floor_big then return {ok = false, error = why2, not_on_floor = floor_why, floor_big = floor_big} end
    if not site then return {ok = false, error = why2, not_on_floor = floor_why} end

    -- Dry run: Quickfort must agree that every tile can be designated.
    local dig = site_dig_cells(L, site.extra)
    if params.urgent == true then dig = prioritized(dig, URGENT_DIG_PRIORITY) end   -- (0.104.128)
    local expected = count(L.tiles) + count(site.extra)
    local a, stair = site.anchor, site.stair
    local dry = quickfort_apply('dig', dig, site.z, a.x, a.y, 'run', true)
    if stat(dry, 'dig_designated') ~= expected or stat(dry, 'dig_invalid_tiles') > 0
            or stat(dry, 'out_of_bounds') > 0 or stat(dry, 'invalid_keys') > 0 then
        return {ok = false, error = ('dry run disagreed: %d of %d tiles designatable'):format(
            stat(dry, 'dig_designated'), expected)
            .. (type(dry) == 'table' and dry.dig_guard_why and ((' (%d refused: %s: left alone: it guards the underworld)'):format(
                stat(dry, 'dig_guard_refused'), dry.dig_guard_why)) or '')}   -- (0.105.40b) the dig guard's
    end

    local stairs_cells = site.extend and stair_cells(stair, site.z) or {}
    local build, furniture = entry_door(L, site, params.style)
    local decor = decoration_cells(L, site, build)
    -- (group 6) the open ground over the level's middle (the scorecard's surface for it)
    local gx, gy = a.x, a.y
    if type(site.area) == 'table' and site.area.x1 and site.area.x2 and site.area.y1 and site.area.y2 then
        gx, gy = (site.area.x1 + site.area.x2) // 2, (site.area.y1 + site.area.y2) // 2
    end
    local okg, gz = pcall(ground_above, gx, gy, site.z)
    if not okg then gz = nil end
    local ground = gz and {ground_z = gz, ground_elevation = ez(gz), cover = gz - site.z - 1} or {}
    local where = {stair = {x = stair.x, y = stair.y, z_top = stair.z_top, z_bottom = stair.z_bottom,
                            elevation_top = ez(stair.z_top), elevation_bottom = ez(stair.z_bottom)},
                   anchor = a, corridor = site.corridor, new_corridor = site.new_corridor}
    if dry_run then
        return {ok = true, dry_run = true, kind = kind, z = site.z, elevation = ez(site.z), not_joined = join_why,
                extends_stairs = site.extend, in_district = site.in_district,
                stair = where.stair, anchor = a, corridor = site.corridor, new_corridor = site.new_corridor,
                area = site.area, tiles = expected, summary = L.summary, furniture = furniture,
                decoration = {smooth = #decor.smooth, engrave = #decor.engrave},
                ground_z = ground.ground_z, ground_elevation = ground.ground_elevation, cover = ground.cover,
                floor = site.floor_result, not_on_floor = floor_why}     -- (layout B)
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
        urgent = params.urgent == true or nil,     -- (0.105.48, A3 14) the report's row carries it
        crossbows = params.crossbows == true or nil,   -- (r2h4) the crossbow squad's Bowyer's: one open at a time
        params = {rooms = params.rooms, room_size = params.room_size, tables = params.tables, beds = params.beds,
                  dormitory = params.dormitory,
                  piles = params.piles, shops = params.shops, size = params.size,
                  plots = params.plots, plot_w = params.plot_w,
                  name = params.name, style = params.style,
                  spare = params.spare, spare_for = params.spare_for,   -- (0.105.54) its free rooms
                  deity_hf = params.deity_hf, religion = params.religion, profession = params.profession},
        stair = {x = stair.x, y = stair.y}, anchor = {x = a.x, y = a.y},
        z = site.z, area = site.area, corridor = site.corridor, new_corridor = site.new_corridor,
        stairs = stairs_cells, summary = L.summary, furniture = furniture,
        links = extra_list(site.extra),   -- (0.105.41) the corridor to the level: ai-traffic's High tiles
        areas = site.areas,               -- (layout B) the new hall's box, kept beside the rooms' (project_areas)
        floor = site.floor,               -- (layout B) {id, slots, hall, piles}: the floor this level is part of
        -- the exact cells, so later steps never depend on regenerating the layout
        cells = {dig = dig, build = build, place = L.place, zone = L.zone,
                 smooth = decor.smooth, engrave = decor.engrave},
        started = now, designated = result,
        plan = plan, in_district = site.in_district,   -- the overseer's hint, and whether it was met
        -- (0.105.54) its free rooms; (V4) none on a floor: unit_params drops the spares there and
        -- join_workshop_level skips floor levels, so save_projects must not keep it as a "free level"
        free_left = (kind == 'workshops' and not site.floor and (params.spare or 0) > 0) and params.spare or nil,
    }
    -- (layout B) a floor's level: its new hall tiles are its links (links = site.links or extra_list(site.extra))
    if site.links then p.links = site.links end
    data.next_id = data.next_id + 1
    table.insert(data.list, p)
    local saved = save_projects(data)
    if not saved then
        undo_dig(dig, stairs_cells, site.z, a, stair)
        return {ok = false, error = 'could not save the project with the fort, so it was undone'}
    end
    -- (layout B) the floor's record: the level booked on it, or why it went the classic way
    if site.floor and type(floor_commit) == 'function' then
        pcall(floor_commit, site, p.id)
    elseif floors_on and floor_why and type(floor_fallback) == 'function' then
        pcall(floor_fallback, kind, floor_why, ez(site.z), floor_marks)
    end
    return {ok = true, project_id = p.id, kind = kind, z = site.z, elevation = ez(site.z),
            floor = site.floor_result, not_on_floor = floor_why,     -- (layout B)
            floor_big = floor_big,                                   -- (r3 g2) {need, run_max, kind}: too big for a run
            extends_stairs = site.extend, in_district = site.in_district,
            stair = {x = stair.x, y = stair.y},
            anchor = a, corridor = site.corridor, new_corridor = site.new_corridor,   -- (0.105.33) Spacing
            tiles = expected, designated = result, summary = L.summary,
            ground_z = ground.ground_z, ground_elevation = ground.ground_elevation, cover = ground.cover,  -- (group 6)
            not_joined = join_why,     -- (0.105.54) why no standing workshops level took the shops
            warning = (result ~= expected) and ('only %d of %d tiles designated'):format(result, expected) or nil}
end

-- (R2 h3) start_project_level, and the small need it was started for (params.need,
-- NEED_KINDS) kept on the new project (`need`): it is counted in the needs' pool
-- (need_slot_free) and not in the ordinary cap (slot_cap). The level is made by
-- several paths (a new level, a standing level's free room, an extension, a
-- floor), so the mark is put on once the project exists.
start_project_level = start_project
function start_project(params, now, dry_run)
    local r = start_project_level(params, now, dry_run)
    local need = type(params) == 'table' and project_need(params, params.kind) or nil
    if need and not dry_run and type(r) == 'table' and r.ok and math.tointeger(r.project_id) then
        pcall(function()
            local data = load_projects()
            local p
            for _, q in ipairs(data.list) do if q.id == r.project_id then p = q end end
            if p and p.need == nil then
                p.need = need
                save_projects(data)
            end
        end)
        r.need = need
    end
    return r
end

-- (r8) The rest of the project lifecycle (progress, the steps on order, founding and
-- cancelling, the way in, polish) is in the files loaded right after this one:
-- ai-builder-projects-progress, -finish, -founding, -wayin, -polish.
