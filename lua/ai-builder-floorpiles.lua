-- ai-builder-floorpiles: (layout B) a floor workshop's piles, given and linked.
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads
-- it into its own environment, so FEEDERS (ai-builder-rooms), layouts,
-- anchor_of and cells_of are plain names here, and its two functions are
-- plain names to the other floor parts (each call across files guarded
-- with type(name) == 'function').
--
-- "Workshops near their piles." The six running forts' piles already stand
-- 2 tiles from their shops; what was missing: almost no feeder pile is
-- linked to its shop (0 to 3 a fort), and kitchens, stills and
-- craftsdwarves often have no pile of their own. On a hallway-first floor
-- each shop of a workshops request goes along the hall beside its own pile
-- room(s) (ai-builder-floors on_floor makes the clusters and drops a pile
-- room that would not fit one side of a run with its shop).
--
--   floor_pile_units(params, hint, has_flag) -> list
--       which pile rooms a workshops request gets (floor_site,
--       ai-builder-floors, makes each a storage room and puts them first)
--   floor_book_piles(p) -> booked, linked
--       the project finished (finish_project's hook): each pile booked as
--       its shop's feeder (ai-pile-links remember_feeder) and, the Rules
--       switch link_feeders on and the shop one of LINKABLE, linked at once
--
-- Nothing is fetched while the part loads: ai-pile-links and
-- ai-overseer-settings are asked for inside functions, behind pcall.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-floorpiles'] = '0.105.111'

-- A shop's output pile (a name from layouts.STOCKPILES). Others: none.
FLOOR_OUTPUTS = {
    Masons = 'furniture', Carpenters = 'furniture',
    Craftsdwarfs = 'finished_goods', Clothiers = 'finished_goods', Leatherworks = 'finished_goods',
    Smelter = 'bars_blocks', WoodFurnace = 'bars_blocks', Ashery = 'bars_blocks', SoapMaker = 'bars_blocks',
    Kitchen = 'food', Still = 'food', Butchers = 'food', Fishery = 'food', Quern = 'food', Millstone = 'food',
    Tanners = 'leather',
    Loom = 'cloth',
}
FLOOR_PILES_MAX = 3          -- hint.piles_new at most
FLOOR_PILES_DEFAULT = 1
FLOOR_PILE_MIN, FLOOR_PILE_MAX = 5, 11     -- a pile room's side (layouts.storage's own range)

local function whole(v)
    if type(v) ~= 'number' and type(v) ~= 'string' then return nil end
    return math.tointeger(tonumber(v))
end

-- The level's style customs: a list as the brain sends it, or a set.
local function has_custom(params, name)
    local st = type(params.style) == 'table' and params.style or nil
    local cs = st and type(st.customs) == 'table' and st.customs or nil
    if not cs then return false end
    if cs[name] == true then return true end
    for _, c in ipairs(cs) do
        if c == name then return true end
    end
    return false
end

local function pile_units(params, hint, has_flag)
    local out = {}
    if type(params) ~= 'table' or type(params.shops) ~= 'table' then return out end
    if type(hint) ~= 'table' then hint = {} end
    local budget = whole(hint.piles_new) or FLOOR_PILES_DEFAULT
    budget = math.max(0, math.min(FLOOR_PILES_MAX, budget))
    if budget == 0 then return out end
    local size = whole(hint.pile_w) or FLOOR_PILE_MIN
    size = math.max(FLOOR_PILE_MIN, math.min(FLOOR_PILE_MAX, size))
    local feeders = type(FEEDERS) == 'table' and FEEDERS or {}
    local piles = type(layouts) == 'table' and type(layouts.STOCKPILES) == 'table' and layouts.STOCKPILES or {}
    local known = type(layouts) == 'table' and type(layouts.WORKSHOPS) == 'table' and layouts.WORKSHOPS or {}
    local cap = type(layouts) == 'table' and whole(layouts.WORKSHOP_ROOMS_MAX) or 12
    -- the shops the level will really hold (layouts.workshops: valid names, 12 at most)
    local shops = {}
    for _, name in ipairs(params.shops) do
        if type(name) == 'string' and known[name] and #shops < cap then table.insert(shops, name) end
    end
    local ore = has_custom(params, 'ore_piles')
    local standing = {}
    local function have(flag)
        if standing[flag] == nil then
            local ok, yes = false, false
            if type(has_flag) == 'function' then ok, yes = pcall(has_flag, flag) end
            standing[flag] = (ok and yes) and true or false
        end
        return standing[flag]
    end
    local taken = {}
    local function give(flag, shop, output)
        if #out >= budget or type(flag) ~= 'string' or not piles[flag] or taken[flag] then return end
        if have(flag) then return end
        taken[flag] = true
        table.insert(out, {flag = flag, shop = shop, room_size = size, output = output})
    end
    for _, shop in ipairs(shops) do
        local f = feeders[shop]
        local flag = type(f) == 'table' and f.flag or nil
        -- (custom ore_piles) the workshops layout brings its own stone room
        if flag and not (ore and flag == 'stone') then give(flag, shop, false) end
    end
    for _, shop in ipairs(shops) do
        give(FLOOR_OUTPUTS[shop], shop, true)
    end
    return out
end

-- The pile rooms a workshops request gets:
--   { {flag = 'stone', shop = 'Masons', room_size = 5, output = false} ... }
-- Feeders first (FEEDERS[shop].flag), one a distinct flag, then outputs
-- (FLOOR_OUTPUTS; never a flag already listed); hint.piles_new (0-3,
-- default 1) rows at most in all; room_size = hint.pile_w clamped to 5-11.
-- has_flag(flag) -> true: this floor's hall already has a live pile of that
-- kind (none is added). Never raises; junk -> {}.
function floor_pile_units(params, hint, has_flag)
    local ok, out = pcall(pile_units, params, hint, has_flag)
    return ok and type(out) == 'table' and out or {}
end

-- --- the finished project's piles booked and linked -------------------------------

-- (each swapped by the tests)
function floor_pile_links() return reqscript('ai-pile-links') end
function floor_settings() return reqscript('ai-overseer-settings').load_settings() end
function floor_stockpiles() return df.global.world.buildings.other.STOCKPILE end
function floor_building_at(x, y, z) return dfhack.buildings.findAtTile(xyz2pos(x, y, z)) end

-- The stockpile at the tile: the one whose corner it is (as ai-pile-links
-- finds one), else the one whose box holds it.
local function pile_at(x, y, z)
    local ok, list = pcall(floor_stockpiles)
    if not ok or list == nil then return nil end
    local inside
    local okw = pcall(function()
        for _, sp in ipairs(list) do
            if sp.z == z then
                if sp.x1 == x and sp.y1 == y then inside = sp return end
                if not inside and x >= sp.x1 and x <= sp.x2 and y >= sp.y1 and y <= sp.y2 then inside = sp end
            end
        end
    end)
    return okw and inside or nil
end

-- A workshop or a furnace, built or planned (where the game's types can't
-- be read, whatever stands on a workshop's own build cell is taken as it).
local function is_shop(b)
    local ok, yes = pcall(function()
        local t = b:getType()
        return t == df.building_type.Workshop or t == df.building_type.Furnace
    end)
    if not ok then return true end
    return yes == true
end

-- The project's workshop buildings of one kind: its build cells whose text
-- is layouts.WORKSHOPS[shop], the building standing on each.
local function shops_of(p, shop, ax, ay)
    local out = {}
    local key = type(shop) == 'string' and layouts.WORKSHOPS[shop] or nil
    if not key then return out end
    for _, c in ipairs(cells_of(p, 'build')) do
        if type(c) == 'table' and c.text == key and whole(c.x) and whole(c.y) then
            local x, y = ax + whole(c.x), ay + whole(c.y)
            local ok, b = pcall(floor_building_at, x, y, p.z)
            if ok and b and b.id ~= nil and is_shop(b) then table.insert(out, {b = b, x = x, y = y}) end
        end
    end
    return out
end

local function book_piles(p)
    local booked, linked = 0, 0
    if type(p) ~= 'table' or type(p.floor) ~= 'table' or type(p.floor.piles) ~= 'table' then return 0, 0 end
    local a = anchor_of(p)
    local z = whole(p.z)
    if type(a) ~= 'table' or not whole(a.x) or not whole(a.y) or not z then return 0, 0 end
    local ax, ay = whole(a.x), whole(a.y)
    local okm, links = pcall(floor_pile_links)
    if not okm or type(links) ~= 'table' or type(links.remember_feeder) ~= 'function' then return 0, 0 end
    -- the Rules switch, read once: off, or not readable -> booked only (the
    -- planner's own rule links a booked feeder later)
    local may_link = false
    pcall(function() may_link = floor_settings().link_feeders ~= false end)
    local linkable = type(links.LINKABLE) == 'table' and links.LINKABLE or {}
    local feeders = type(FEEDERS) == 'table' and FEEDERS or {}
    local fed = {}               -- shop building id -> true: it has its feeder from this project
    for _, row in ipairs(p.floor.piles) do
        pcall(function()
            if type(row) ~= 'table' or not whole(row.x) or not whole(row.y) then return end
            local shop, flag = row.shop, row.flag
            local f = type(shop) == 'string' and feeders[shop] or nil
            -- an output pile is no feeder: nothing booked
            if row.output == true or type(f) ~= 'table' or f.flag ~= flag then return end
            local sp = pile_at(ax + whole(row.x), ay + whole(row.y), z)
            if not sp or sp.id == nil then return end
            -- the workshop: the nearest of its kind in the project, one not fed yet first
            local best, bd, bfed
            for _, s in ipairs(shops_of(p, shop, ax, ay)) do
                local d = math.max(math.abs(s.x - (sp.x1 + sp.x2) // 2), math.abs(s.y - (sp.y1 + sp.y2) // 2))
                local isfed = fed[s.b.id] == true
                if not best or (bfed and not isfed) or (bfed == isfed and d < bd) then best, bd, bfed = s, d, isfed end
            end
            if not best then return end
            -- (the pile's corner: ai-pile-links finds a pile by it)
            local okr, kept = pcall(links.remember_feeder, sp.x1, sp.y1, sp.z, best.b.id, shop, flag)
            if not okr or not kept then return end
            booked = booked + 1
            fed[best.b.id] = true
            if may_link and linkable[shop] and type(links.link_feeder) == 'function' then
                local okl, r = pcall(links.link_feeder, {pile_id = sp.id}, false)
                if okl and type(r) == 'table' and r.ok == true then linked = linked + 1 end
            end
        end)
    end
    return booked, linked
end

-- A floor project finished: for each of p.floor.piles ({x, y, flag, shop},
-- x and y relative to anchor_of(p) on p.z) the stockpile at its tile and
-- the workshop of its shop among the project's build cells (built or
-- planned); ai-pile-links.remember_feeder(x, y, z, shop building id, shop,
-- flag) in map coordinates; then, the Rules switch link_feeders not off and
-- the shop one of ai-pile-links.LINKABLE, link_feeder({pile_id}) at once.
-- Output piles are not booked. A missing pile or shop is skipped; nothing
-- raises. Returns booked, linked.
function floor_book_piles(p)
    local ok, booked, linked = pcall(book_piles, p)
    if not ok then return 0, 0 end
    return booked or 0, linked or 0
end
