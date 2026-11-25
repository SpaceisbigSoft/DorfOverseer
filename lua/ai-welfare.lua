-- (0.105.47, R2 burial and welfare) The unburied dead, the dead nobody can
-- reach, and a cook trained in a small fort.
--
-- Why (the 14 Nov forensics, I7b): B asked for a tomb level 23 times in
-- 261-262 and every search failed ("no safe level found"); it had 0 free
-- tombs until 263 while 190+ dead lay unburied and 2-6 ghosts walked. Slabs
-- were made only once a ghost walked, though many bodies were out of reach
-- (drowned, in ice, in the caverns), so those ghosts were bound to rise.
-- D (8 dwarves) went ten years without a good meal: its best cook had skill 1,
-- as every dwarf cooked now and then and nobody learned.
--
--   dead_scan()             the fort's own dead whose body can't be reached
--                           (out of the dwarves' walk, or gone), and those of
--                           them with no memorial slab nor an order for one
--   engrave_memorials(max, dry)
--                           an EngraveSlab work order for each of them, as
--                           DFHack's autoslab makes one for a ghost (the
--                           order names the dead: hist_figure_id)
--   corner_spots(n)         free dug floor on the AI's finished levels (a tomb
--                           level's spare tiles first, then a storage level,
--                           a workshop level, then any other that isn't lived
--                           in), beside a wall, in no zone, out of the way
--   place_corner_coffins(n, dry)
--                           a coffin planned on each (buildingplan waits for
--                           one) with a 1x1 tomb zone that takes citizens;
--                           the spots kept in the save (corner_areas)
--   open_tombs(areas, dry)  automatic burial of citizens switched on in the
--                           AI's tomb zones inside `areas` (never a tomb set
--                           aside for one dwarf); the builder calls it when a
--                           tomb level is zoned and finished
--   train_cook(dry, release)
--                           the best free cook made the kitchens' only worker
--                           (DF's workshop profile, its Workers tab), so one
--                           dwarf learns; kept until gone, then the next best.
--                           Never a kitchen the player named workers for.
--   entomb_dead(max, dry)   (item8) a free tomb assigned to each of the fort's
--                           own dead lying free in reach (DF carries them there)
--   report()                the `welfare` section: the corner coffins (placed,
--                           built, free), free coffin items, the trainee cook
--
-- Every DF read is in a pcall; the dry runs change nothing.
--@ module = true

local U = reqscript('ai-util')

WELFARE_KEY = 'ai-overseer/welfare'
SCAN_MAX = 4000            -- dead units looked at, at most, in one scan
WANTED_MAX = 20            -- the dead named in the scan's list
CORNER_MAX = 40            -- corner coffins kept in the save, at most
-- the AI's levels by how fit their spare floor is for a coffin; levels the
-- dwarves live, eat, pray or heal in are never used
CORNER_KINDS = {tombs = 1, storage = 2, workshops = 3, hall = 4, stairwell = 4, landmark = 5, industry = 5}
CORNER_NEVER = {bedrooms = true, suites = true, hospital = true, dining = true, tavern = true, temple = true,
                well = true, cistern = true, farms = true, jail = true, way_in = true, library = true,
                barracks = true, noble = true, office = true, were_cells = true}
TOMB_ZONE = 'T{citizens=true}'

local function state()
    local d = U.site_get(WELFARE_KEY, {})
    if type(d) ~= 'table' then d = {} end
    d.corner = type(d.corner) == 'table' and d.corner or {}
    d.cook = type(d.cook) == 'table' and d.cook or {}
    return d
end

local function save(d) U.site_put(WELFARE_KEY, d) end

local function txt(s) return dfhack.df2utf and dfhack.df2utf(s) or s end

local function unnamed(u) return 'unit ' .. tostring(u and u.id) end
local function name_of(u) return U.name_of(u, txt, unnamed) end   -- (r6) ai-util's

local function anchor()
    local from
    pcall(function()
        for _, u in ipairs(U.citizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then from = xyz2pos(x, y, z) break end
        end
    end)
    return from
end

-- --- the dead nobody can reach --------------------------------------------------

-- The hist figures with a memorial slab (any: loose, in a job, built).
local function memorial_hfs()
    local out = {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.SLAB) do
            pcall(function()
                if it.engraving_type == df.slab_engraving_type.Memorial then out[it.topic] = true end
            end)
        end
    end)
    return out
end

-- (0.105.51) The hist figure a work order names: DF 53.17 keeps it in the
-- order's specdata union (df-structures df.workquota.xml: manager_order.specdata,
-- a job_spec_data with hist_figure_id); there is no manager_order.hist_figure_id
-- (R3, 15 Nov: "Cannot write field manager_order.hist_figure_id", C 17, E 7).
function order_hf(o)
    local ok, hf = pcall(function() return o.specdata.hist_figure_id end)
    if ok and type(hf) == 'number' then return hf end
    return -1
end

-- The hist figures an EngraveSlab work order already names.
local function ordered_hfs()
    local out, n = {}, 0
    pcall(function()
        for _, o in ipairs(df.global.world.manager_orders.all) do
            pcall(function()
                local hf = order_hf(o)
                if o.job_type == df.job_type.EngraveSlab and hf >= 0 then
                    out[hf] = true
                    n = n + 1
                end
            end)
        end
    end)
    return out, n
end

-- One of the fort's own: of its race and civ, and a member (or once one) of
-- the site's government when that can be read; never a merchant or diplomat.
local function fort_own(u, race, civ, group)
    if u.race ~= race or u.civ_id ~= civ then return false end
    local visitor = false
    pcall(function() visitor = u.flags1.merchant or u.flags1.diplomat end)
    if visitor then return false end
    local member = nil
    pcall(function()
        local hf = df.historical_figure.find(u.hist_figure_id)
        if hf and group and group >= 0 then
            member = false
            for _, l in ipairs(hf.entity_links) do
                if l.entity_id == group then member = true break end
            end
        end
    end)
    return member ~= false
end

-- (r9, audit A7 #25) the walk over every unit the world has ever had (tens
-- of thousands in an old world, a pcall each) kept a day for the report:
-- dead_scan() reuses it, dead_scan(true) (the memorial action) walks again;
-- an order placed drops it. Kept per fort (the group id) and game day.
DEAD_TTL = 1200
local DEAD_CACHE = nil           -- {key, at, out}

local function dead_key()
    local ok, g = pcall(function() return df.global.plotinfo.group_id end)
    return ok and g or -1
end

-- {unreachable, gone, total (both), without_slab, ordered, wanted = {{hf, id, name, why}}}
function dead_scan(fresh)
    local now = U.abs_tick()
    if not fresh and DEAD_CACHE and DEAD_CACHE.key == dead_key() and type(now) == 'number'
            and now >= DEAD_CACHE.at and now - DEAD_CACHE.at < DEAD_TTL then
        return DEAD_CACHE.out
    end
    local out = dead_scan_walk()
    DEAD_CACHE = type(now) == 'number' and {key = dead_key(), at = now, out = out} or nil
    return out
end

function dead_scan_walk()
    local out = {unreachable = 0, gone = 0, total = 0, without_slab = 0, ordered = 0, wanted = {}}
    local race, civ = U.fort_race_civ()
    local group
    pcall(function() group = df.global.plotinfo.group_id end)
    if not race then return out end
    local bodies = {}
    pcall(function()
        for _, c in ipairs(df.global.world.items.other.CORPSE) do bodies[c.unit_id] = c end
    end)
    local slabs = memorial_hfs()
    local ordered, n_orders = ordered_hfs()
    out.ordered = n_orders
    local from = anchor()
    local seen = 0
    local okl, all = pcall(function() return df.global.world.units.all end)
    for _, u in ipairs(okl and all or {}) do
        if seen >= SCAN_MAX then out.cut_short = true break end
        pcall(function()
            if not dfhack.units.isDead(u) or dfhack.units.isGhost(u) then return end
            if (u.hist_figure_id or -1) < 0 or not fort_own(u, race, civ, group) then return end
            seen = seen + 1
            local c = bodies[u.id]
            local why
            if not c then
                why = 'gone'
            elseif not c.flags.in_building then
                local x, y, z = dfhack.items.getPosition(c)
                if x and from and not dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z)) then why = 'unreachable' end
            end
            if not why then return end
            out[why] = out[why] + 1
            out.total = out.total + 1
            if slabs[u.hist_figure_id] then return end
            out.without_slab = out.without_slab + 1
            if ordered[u.hist_figure_id] then return end
            table.insert(out.wanted, {hf = u.hist_figure_id, id = u.id, name = name_of(u), why = why})
        end)
    end
    -- the out-of-reach first (their ghosts rise soonest), then the gone; oldest id first
    table.sort(out.wanted, function(a, b)
        if a.why ~= b.why then return a.why == 'unreachable' end
        return a.id < b.id
    end)
    out.wanting = #out.wanted
    while #out.wanted > WANTED_MAX do table.remove(out.wanted) end
    return out
end

-- An EngraveSlab order for one dead (as autoslab makes them), approved.
local function slab_order(hf)
    local mo = df.global.world.manager_orders
    local o = df.manager_order:new()
    -- (0.105.51) the dead named first: a failed write leaves no order id used
    local ok, err = pcall(function()
        o.job_type = df.job_type.EngraveSlab
        o.specdata.hist_figure_id = hf
    end)
    -- (item7) once: a new manager_order's frequency is NONE (-1), and such
    -- an order never ends (B, 24 Nov: 14 of them, all left 1, one dwarf's
    -- slab engraved 71 times while the walking ghost's waited for a blank)
    -- (item7) its own guard: a game (or a test's fake) without the enum keeps the order
    if ok then pcall(function() o.frequency = df.workquota_frequency_type.OneTime end) end
    if not ok then
        pcall(function() o:delete() end)
        error(err)
    end
    o.id = mo.manager_order_next_id
    mo.manager_order_next_id = mo.manager_order_next_id + 1
    o.amount_left = 1
    o.amount_total = 1
    pcall(function() o.status.validated = true end)
    mo.all:insert('#', o)
    return o.id
end

-- (r1g8) The fort's walking ghosts with no memorial slab at all and no
-- EngraveSlab order of the AI's own (kept in the save, by hf) still open:
-- DFHack's autoslab orders one, but its jobs are the ones lifted off a full
-- mason's bench, and F (15-16 Nov) never got Udil's slab engraved in 6 years
-- while other slabs were put up 164 times. {{hf, id, name}}
function ghost_scan()
    local out = {}
    local race, civ = U.fort_race_civ()
    local group
    pcall(function() group = df.global.plotinfo.group_id end)
    if not race then return out end
    local slabs = memorial_hfs()
    local d = state()
    local mine = type(d.ghost_orders) == 'table' and d.ghost_orders or {}
    local live = {}
    pcall(function()
        for _, o in ipairs(df.global.world.manager_orders.all) do live[o.id] = true end
    end)
    local okl, all = pcall(function() return df.global.world.units.all end)
    for _, u in ipairs(okl and all or {}) do
        pcall(function()
            if not dfhack.units.isGhost(u) then return end
            local hf = u.hist_figure_id or -1
            if hf < 0 or not fort_own(u, race, civ, group) or slabs[hf] then return end
            local oid = mine[tostring(hf)]
            if oid and live[oid] then return end
            table.insert(out, {hf = hf, id = u.id, name = name_of(u), why = 'ghost'})
        end)
    end
    table.sort(out, function(a, b) return a.id < b.id end)
    return out
end

function engrave_memorials(max, dry_run, ghosts)
    max = math.max(1, math.min(10, math.tointeger(max) or 5))
    if ghosts then
        local list = ghost_scan()
        if #list == 0 then
            return {ok = false, rejected = true, nothing_to_do = true,
                    error = 'every ghost has a memorial slab or an open order of the AI\'s for one'}
        end
        local named, ids = {}, {}
        local d = state()
        d.ghost_orders = type(d.ghost_orders) == 'table' and d.ghost_orders or {}
        for i = 1, math.min(max, #list) do
            local w = list[i]
            if dry_run then
                table.insert(named, w.name)
            else
                local ok, id = pcall(slab_order, w.hf)
                if ok then
                    table.insert(ids, id) table.insert(named, w.name)
                    d.ghost_orders[tostring(w.hf)] = id
                elseif #named == 0 then
                    return {ok = false, error = 'the game took no memorial order: ' .. tostring(id):sub(1, 120)}
                end
            end
        end
        if not dry_run and #ids > 0 then pcall(save, d) end
        return {ok = true, ordered = named, order_ids = (#ids > 0) and ids or nil, ghosts = true,
                left = #list - #named, dry_run = dry_run or nil}
    end
    local scan = dead_scan(true)
    DEAD_CACHE = nil                 -- (r9) the orders placed now: the report walks again
    if #scan.wanted == 0 then
        return {ok = false, rejected = true, nothing_to_do = true,
                error = 'every dead citizen out of reach has a memorial slab or an order for one'}
    end
    local named, ids = {}, {}
    for i = 1, math.min(max, #scan.wanted) do
        local w = scan.wanted[i]
        if not dry_run then
            local ok, id = pcall(slab_order, w.hf)
            if ok then table.insert(ids, id) table.insert(named, w.name)
            elseif #named == 0 then
                return {ok = false, error = 'the game took no memorial order: ' .. tostring(id):sub(1, 120)}
            end
        else
            table.insert(named, w.name)
        end
    end
    return {ok = true, ordered = named, order_ids = (#ids > 0) and ids or nil, left = scan.wanting - #named,
            dry_run = dry_run or nil}
end

-- --- coffins anywhere ------------------------------------------------------------

-- The spots in the save that still stand as a coffin (or a coffin planned).
function corner_areas()
    local out = {}
    for _, sp in ipairs(state().corner) do
        if type(sp) == 'table' and sp.x and sp.y and sp.z then
            table.insert(out, {x1 = sp.x, y1 = sp.y, x2 = sp.x, y2 = sp.y, z = sp.z})
        end
    end
    return out
end

local function near(list, x, y, z)
    for _, s in ipairs(list) do
        if s.z == z and math.abs(s.x - x) <= 1 and math.abs(s.y - y) <= 1 then return true end
    end
    return false
end

-- Up to n spots: {x, y, z, kind}, the fittest levels first, never two side by side.
function corner_spots(n)
    local B = reqscript('ai-builder')
    local okp, data = pcall(B.load_projects)
    local levels = {}
    for _, p in ipairs(okp and data and data.list or {}) do
        if type(p) == 'table' and p.phase == 'done' and not CORNER_NEVER[p.kind or ''] then
            -- (F4, S2) a floor level: its own rooms only (B.own_areas), never the main hall or a
            -- neighbour's room inside its box
            local areas = B.own_areas and B.own_areas(p) or (B.project_areas and B.project_areas(p)) or {p.area}
            for _, a in ipairs(areas) do
                if type(a) == 'table' and a.x1 then
                    table.insert(levels, {area = a, kind = p.kind, rank = CORNER_KINDS[p.kind or ''] or 6})
                end
            end
        end
    end
    table.sort(levels, function(a, b)
        if a.rank ~= b.rank then return a.rank < b.rank end
        return (a.area.z or 0) > (b.area.z or 0)
    end)
    local from = anchor()
    local picked = {}
    for _, lv in ipairs(levels) do
        if #picked >= n then break end
        local a = lv.area
        local own = a.own
        local area = {x1 = a.x1, y1 = a.y1, x2 = a.x2, y2 = a.y2, z = a.z,
                      has = own and function(x, y) return own({x1 = x, y1 = y, x2 = x, y2 = y}) end
                          or function() return true end}
        local okz, spots = pcall(B.zone_spots, area)
        for _, sp in ipairs(okz and spots or {}) do
            if #picked >= n then break end
            local x, y, z = sp.x, sp.y, a.z
            local free = not near(picked, x, y, z)
            if free then
                local okt, taken = pcall(B.tile_taken, x, y, z)
                free = okt and not taken
            end
            if free then
                local t = B.tile_info(x, y, z)
                free = t and not t.outside and not t.designated
            end
            if free and from then
                local okw, walk = pcall(dfhack.maps.canWalkBetween, from, xyz2pos(x, y, z))
                free = (not okw) or walk
            end
            if free then table.insert(picked, {x = x, y = y, z = z, kind = lv.kind}) end
        end
    end
    return picked
end

-- (0.105.47) coffins planned with a tomb each where the dead can lie now
function place_corner_coffins(n, dry_run)
    n = math.max(1, math.min(10, math.tointeger(n) or 5))
    local d = state()
    if #d.corner >= CORNER_MAX then
        return {ok = false, rejected = true, error = ('%d coffins already stand on the AI\'s levels outside a tomb level'):format(#d.corner)}
    end
    n = math.min(n, CORNER_MAX - #d.corner)
    local B = reqscript('ai-builder')
    local spots = corner_spots(n)
    if #spots == 0 then
        return {ok = false, rejected = true, error = 'no free dug floor on the AI\'s finished levels for a coffin'}
    end
    local placed, last = {}, nil
    for _, sp in ipairs(spots) do
        local good, failed, res = B.qf_try('build', {{x = 0, y = 0, text = 'n'}}, sp.z, sp.x, sp.y, dry_run)
        if good then
            local zg, zf = B.qf_try('zone', {{x = 0, y = 0, text = TOMB_ZONE}}, sp.z, sp.x, sp.y, dry_run)
            table.insert(placed, {x = sp.x, y = sp.y, z = sp.z, kind = sp.kind, zone = zg or nil})
            if not dry_run then
                table.insert(d.corner, {x = sp.x, y = sp.y, z = sp.z, kind = sp.kind, zone = zg or nil,
                                        at = U.abs_tick()})
            end
        else
            last = (failed or '?') .. ': ' .. tostring(type(res) == 'string' and res or 'quickfort refused it')
        end
    end
    if #placed == 0 then
        return {ok = false, rejected = true, error = 'quickfort took no coffin at the spots found (' .. tostring(last):sub(1, 100) .. ')'}
    end
    if not dry_run then
        save(d)
        pcall(open_tombs, corner_areas(), false)
    end
    return {ok = true, placed = placed, kept = #d.corner, dry_run = dry_run or nil}
end

-- (0.105.47) automatic burial on in the AI's tomb zones inside the areas
function open_tombs(areas, dry_run)
    local n = 0
    if type(areas) ~= 'table' or #areas == 0 then return {ok = true, opened = 0} end
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_TOMB) do
            pcall(function()
                local mine = false
                for _, ar in ipairs(areas) do
                    -- (F4, S2) ar.own: a floor level's own rooms (ai-builder own_areas)
                    if z.z == ar.z and z.x1 >= ar.x1 and z.x2 <= ar.x2 and z.y1 >= ar.y1 and z.y2 <= ar.y2
                            and (type(ar.own) ~= 'function' or ar.own(z)) then mine = true end
                end
                local owner = -1
                pcall(function() owner = z.assigned_unit_id end)
                if mine and (owner == nil or owner < 0) and z.zone_settings.tomb.flags.no_citizens then
                    if not dry_run then z.zone_settings.tomb.flags.no_citizens = false end
                    n = n + 1
                end
            end)
        end
    end)
    return {ok = true, opened = n, dry_run = dry_run or nil}
end

-- (0.105.112 item8) A tomb given to each of the fort's own dead whose body
-- lies free in the dwarves' reach and waits with free tombs standing open (B,
-- 24 Nov: Dodok, dead of thirst while raving, lay 165 days on a meeting hall
-- floor with 10 open tombs: DF's automatic burial never took him). A tomb
-- zone assigned to a dead unit is how the player buries one by hand: the
-- dwarves carry the body to that coffin. Free tombs only: a coffin with no
-- body, in a tomb zone nobody owns that takes citizens, reachable from the
-- body. At most `max` a call; the nearest tomb to each body.
local function tomb_free(z)
    local owner = -1
    pcall(function() owner = z.assigned_unit_id end)
    if owner ~= nil and owner >= 0 then return false end
    local closed = true
    pcall(function() closed = z.zone_settings.tomb.flags.no_citizens end)
    if closed then return false end
    local coffin = nil
    pcall(function()
        for _, b in ipairs(z.contained_buildings) do
            if b:getType() == df.building_type.Coffin and b:getBuildStage() >= b:getMaxBuildStage() then
                local used = false
                for _, ci in ipairs(b.contained_items) do
                    local t = df.item_type[ci.item:getType()] or ''
                    if ci.use_mode == 0 and (t == 'CORPSE' or t == 'CORPSEPIECE' or t == 'REMAINS') then used = true end
                end
                if not used then coffin = b end
            end
        end
    end)
    return coffin
end

function entomb_dead(max, dry_run)
    max = math.max(1, math.min(10, math.tointeger(max) or 3))
    local tombs, owned = {}, {}
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_TOMB) do
            pcall(function()
                local c = tomb_free(z)
                if c then table.insert(tombs, {z = z, pos = xyz2pos(c.centerx, c.centery, c.z)}) end
                local o = z.assigned_unit_id
                if o ~= nil and o >= 0 then owned[o] = true end
            end)
        end
    end)
    if #tombs == 0 then
        return {ok = false, rejected = true, error = 'no free tomb that takes citizens (a coffin with no body, the zone nobody\'s)'}
    end
    local from = anchor()
    local race, civ, group = U.fort_race_civ()
    local ctx = {U = U, race = race, civ = civ, group = group}
    local given, waiting, taken = {}, 0, {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.CORPSE) do
            if #given >= max then break end
            pcall(function()
                local f = it.flags
                if f.in_building or f.removed or f.forbid or f.dump or f.in_job or f.in_inventory
                        or not U.on_ground(it) then return end
                if U.corpse_side(it, 'CORPSE', ctx) ~= 'own' then return end
                local u = df.unit.find(it.unit_id)
                if not u or not dfhack.units.isDead(u) or owned[u.id] then return end
                local x, y, z = dfhack.items.getPosition(it)
                if not x then return end
                local at = xyz2pos(x, y, z)
                if from and not dfhack.maps.canWalkBetween(from, at) then return end
                waiting = waiting + 1
                local best, bd = nil, nil
                for i, t in ipairs(tombs) do
                    if not taken[i] and dfhack.maps.canWalkBetween(at, t.pos) then
                        local d = math.abs(t.pos.x - x) + math.abs(t.pos.y - y) + 3 * math.abs(t.pos.z - z)
                        if not bd or d < bd then best, bd = i, d end
                    end
                end
                if not best then return end
                local t = tombs[best]
                local ok = dry_run
                if not dry_run then
                    local oks, r = pcall(dfhack.buildings.setOwner, t.z, u)
                    ok = oks and r ~= false and t.z.assigned_unit_id == u.id
                end
                if ok then
                    taken[best] = true
                    owned[u.id] = true
                    table.insert(given, {unit = u.id, name = name_of(u), zone = t.z.id,
                                         x = t.pos.x, y = t.pos.y, z = t.pos.z})
                end
            end)
        end
    end)
    if #given == 0 then
        return {ok = false, rejected = true, waiting = waiting,
                error = waiting > 0 and 'no free tomb the waiting dead can be carried to'
                    or 'no body of the fort\'s own lies free in reach without a tomb of its own'}
    end
    return {ok = true, given = given, free_tombs = #tombs - #given, dry_run = dry_run or nil}
end

-- --- a cook trained -------------------------------------------------------------

local function kitchens()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            pcall(function()
                if b.type == df.workshop_type.Kitchen and b:getBuildStage() >= b:getMaxBuildStage() then
                    table.insert(out, b)
                end
            end)
        end
    end)
    return out
end

local function cook_skill(u)
    local ok, r = pcall(dfhack.units.getNominalSkill, u, df.job_skill.COOK, true)
    return ok and tonumber(r) or 0
end

-- free to cook: an adult, sane, in no squad, no noble's office.
-- (0.105.48, K3) and able to reach the kitchen now: not in a strange mood,
-- not waiting for a treatment (DF's rq_ flags: a cook bedridden for a
-- season kept the kitchen shut), not kept in any burrow (the AI's hospital,
-- recreation or calm-down burrow, a player's: the kitchen may be outside it)
local COOK_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
                 'rq_setting', 'rq_traction', 'rq_crutch'}
-- (0.105.51) {burrow id = true}: the AI's recreation and shelter burrows
function cook_skip_burrows()
    local out = {}
    pcall(function()
        local S = reqscript('ai-society')
        for _, name in ipairs({'AI recreation', 'AI shelter'}) do
            local b = S.find_burrow(name)
            if b then out[b.id] = true end
        end
    end)
    return out
end

local function can_cook(u)
    local ok, yes = pcall(function()
        return dfhack.units.isAlive(u) and dfhack.units.isAdult(u) and dfhack.units.isSane(u)
            and (u.military.squad_id or -1) < 0
    end)
    if not (ok and yes) then return false end
    local okn, noble = pcall(function() return #dfhack.units.getNoblePositions(u) > 0 end)
    if okn and noble then return false end
    local okm, mood = pcall(function() return u.mood end)
    if okm and type(mood) == 'number' and mood >= 0 then return false end      -- df.mood_type.None is -1
    local okh, patient = pcall(function()
        if not (u.health and u.health.flags.needs_healthcare) then return false end
        for _, f in ipairs(COOK_RQ) do if u.health.flags[f] then return true end end
        return false
    end)
    if okh and patient then return false end
    -- (0.105.51) the AI's recreation burrow and its shelter (the alarm's and
    -- evil weather's keep-in) are a short stay: not counted. R3 (15 Nov): D's
    -- trainee swapped 97 times, two tavern keepers in and out of the recreation burrow
    local okb, inb = pcall(function()
        local skip = cook_skip_burrows()
        for _, id in ipairs(u.burrows) do
            if not skip[id] then return true end
        end
        return false
    end)
    if okb and inb then return false end
    return true
end

local function workers_of(b)
    local out = {}
    pcall(function() for _, id in ipairs(b.profile.permitted_workers) do table.insert(out, id) end end)
    return out
end

local function set_workers(b, ids)
    local pw = b.profile.permitted_workers
    while #pw > 0 do pw:erase(#pw - 1) end
    for _, id in ipairs(ids) do pw:insert('#', id) end
end

function train_cook(dry_run, release)
    local d = state()
    local mine = type(d.cook.kitchens) == 'table' and d.cook.kitchens or {}
    local ks = kitchens()
    if release then
        local freed = 0
        for _, b in ipairs(ks) do
            local w = workers_of(b)
            if mine[tostring(b.id)] and #w == 1 and w[1] == d.cook.unit then
                if not dry_run then pcall(set_workers, b, {}) end
                freed = freed + 1
            end
        end
        if not dry_run then d.cook = {}; save(d) end
        return {ok = true, released = freed, dry_run = dry_run or nil}
    end
    if #ks == 0 then return {ok = false, rejected = true, error = 'the fort has no kitchen'} end
    -- the one kept, while still free to cook; else the best free cook
    local cur = d.cook.unit and df.unit.find(d.cook.unit)
    local pick = (cur and can_cook(cur)) and cur or nil
    if not pick then
        local best, best_r = nil, -1
        for _, u in ipairs(U.citizens(true)) do
            if can_cook(u) then
                local r = cook_skill(u)
                if r > best_r or (r == best_r and best and u.id < best.id) then best, best_r = u, r end
            end
        end
        pick = best
    end
    if not pick then return {ok = false, rejected = true, error = 'nobody free to learn to cook'} end
    -- (0.105.48, K3) ONE kitchen kept for the trainee (it was every kitchen
    -- with no named workers: a fort cooked nothing while its one cook was
    -- bedridden, moody or kept in a burrow). The one kept before if still
    -- ours, else the first with no named workers; any other the AI had
    -- (a save from before) opened to every cook again.
    -- ours: one the AI keeps whose workers are still none or its trainee alone
    local function ours(b)
        local w = workers_of(b)
        return mine[tostring(b.id)] and (#w == 0 or (#w == 1 and w[1] == d.cook.unit)) or false
    end
    local players, keep = 0, nil
    for _, b in ipairs(ks) do
        if not keep and ours(b) then keep = b end
    end
    for _, b in ipairs(ks) do
        if not ours(b) and #workers_of(b) > 0 then
            players = players + 1        -- workers the player named: never touched
        elseif not keep and #workers_of(b) == 0 then
            keep = b
        end
    end
    if not keep then
        return {ok = false, rejected = true, error = 'every kitchen has workers named by the player'}
    end
    local opened = 0
    local kept = {}
    for _, b in ipairs(ks) do
        local k = tostring(b.id)
        if b == keep then
            if not dry_run then
                pcall(set_workers, b, {pick.id})
                pcall(function() b.profile.min_level = 0 end)
            end
            kept[k] = true
        elseif ours(b) then
            if #workers_of(b) > 0 then
                if not dry_run then pcall(set_workers, b, {}) end
                opened = opened + 1
            end
        end
    end
    if not dry_run then mine = kept end
    local set = 1
    -- the cooking labour on, for the work details that hold it back
    local labour = false
    if not dry_run then
        -- (r9, audit A7 #22) through the work details (ai-labor), so the
        -- game's next recompute doesn't take it back; the flag alone without it
        local okl, L = pcall(reqscript, 'ai-labor')
        if okl and type(L) == 'table' and L.give_labor then
            local okg, has = pcall(L.give_labor, pick, 'COOK')
            labour = okg and has == true
        else
            pcall(function() pick.status.labors[df.unit_labor.COOK] = true; labour = true end)
        end
        local changed = d.cook.unit ~= pick.id
        d.cook = {unit = pick.id, name = name_of(pick), kitchens = mine,
                  since = changed and U.abs_tick() or d.cook.since, skill0 = changed and cook_skill(pick) or d.cook.skill0}
        save(d)
    end
    return {ok = true, cook = name_of(pick), unit_id = pick.id, skill = cook_skill(pick), kitchens = set,
            kitchen_id = keep.id, open_kitchens = #ks - 1 - players, reopened = opened > 0 and opened or nil,
            labour = labour or nil,
            players_kitchens = players > 0 and players or nil, dry_run = dry_run or nil}
end

-- --- the report ------------------------------------------------------------------

function report()
    local d = state()
    local out = {corner = {placed = #d.corner, built = 0, free = 0}, coffin_items = 0}
    -- the corner coffins: built (a Coffin building at the spot), free (none in it)
    pcall(function()
        for _, sp in ipairs(d.corner) do
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(sp.x, sp.y, sp.z))
                if b and b:getType() == df.building_type.Coffin and b:getBuildStage() >= b:getMaxBuildStage() then
                    out.corner.built = out.corner.built + 1
                    local empty = true
                    for _, ci in ipairs(b.contained_items) do
                        if ci.use_mode == 0 then
                            local t = df.item_type[ci.item:getType()]
                            if t == 'CORPSE' or t == 'CORPSEPIECE' or t == 'REMAINS' then empty = false end
                        end
                    end
                    if empty then out.corner.free = out.corner.free + 1 end
                end
            end)
        end
    end)
    out.corner.waiting = out.corner.placed - out.corner.built
    -- free coffins in store (no building, no job, not forbidden)
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.COFFIN) do
            pcall(function()
                local f = it.flags
                if not (f.in_building or f.in_job or f.forbid or f.construction or f.garbage_collect) then
                    out.coffin_items = out.coffin_items + 1
                end
            end)
        end
    end)
    -- the trainee cook
    if d.cook.unit then
        local u = df.unit.find(d.cook.unit)
        out.cook = {unit = d.cook.unit, name = d.cook.name, skill = u and cook_skill(u) or nil,
                    free = u and can_cook(u) or false, since = d.cook.since, skill0 = d.cook.skill0}
    end
    return out
end

-- --- when each stressed dwarf came ----------------------------------------------
--
-- (0.105.47, I7b) B's and E's miserable dwarves stayed so for years: their
-- stress was inherited from a disaster before or soon after they came, not
-- made now. The year each came is read from the world's history: the newest
-- events first, the "settled at the site" change of state for that figure
-- [verify in game: DF 53 history_event_change_hf_statest has hfid, site,
-- year]. A figure not found within the budget is looked for again a day
-- later; one found is kept for the session.
ARRIVAL_SCAN = 60000       -- history events looked at, at most, a call
ARRIVALS = ARRIVALS or {}  -- hf -> year (kept for the session)
ARRIVALS_MISS = ARRIVALS_MISS or {}   -- hf -> the day it was last looked for and not found

function arrivals(hfs)
    local out, want, n = {}, {}, 0
    local day = 0
    pcall(function() day = U.abs_tick() // U.TICKS_PER_DAY end)
    for _, hf in ipairs(hfs or {}) do
        if ARRIVALS[hf] then out[hf] = ARRIVALS[hf]
        elseif ARRIVALS_MISS[hf] ~= day and hf >= 0 then want[hf] = true; n = n + 1 end
    end
    if n == 0 then return out end
    local site = -1
    pcall(function() site = df.global.plotinfo.site_id end)
    pcall(function()
        local ev = df.global.world.history.events
        local last = #ev - 1
        local first = math.max(0, last - ARRIVAL_SCAN + 1)
        for i = last, first, -1 do
            if n == 0 then break end
            local e = ev[i]
            local ok, hit = pcall(function()
                return df.history_event_change_hf_statest:is_instance(e) and want[e.hfid] and e.site == site
            end)
            if ok and hit then
                -- the newest such event is kept (a dwarf who left and came back: the return)
                ARRIVALS[e.hfid] = e.year
                out[e.hfid] = e.year
                want[e.hfid] = nil
                n = n - 1
            end
        end
    end)
    for hf in pairs(want) do ARRIVALS_MISS[hf] = day end
    return out
end
