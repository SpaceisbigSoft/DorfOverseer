-- (0.105.41, item 2) Wheelbarrows for the AI's stone piles, and the AI's
-- feeder piles linked to the workshops they feed. The coverage audit's
-- "should" list: wheelbarrows assigned to the AI's own stone stockpiles
-- (a pile's max wheelbarrows, ordered when too few are free), and feeder
-- piles linked to their workshops, "take from links only" where it fits.
--
-- How DF does it (df-structures 53.x: building_stockpilest.storage,
-- .links, .stockpile_flag; workshop .profile.links):
--   * a stockpile takes up to storage.max_wheelbarrows wheelbarrows; the
--     ones it holds are in its storage.container_item_id list (with bins
--     and barrels), and haulers bring heavy things (stone) to it in them.
--   * a workshop with any pile in profile.links.take_from_pile takes its
--     materials from those piles only; the pile lists the workshop in
--     links.give_to_workshop (quickfort links both sides, sorted by id).
--   * a pile with stockpile_flag.use_links_only takes only from the piles
--     (and workshops) that give to it, never loose items.
--
--   report()            the `pile_links` section: the fort's wheelbarrows
--                       (owned, held by piles, free, wanted by the piles'
--                       settings), the AI's own stone piles (tiles, max
--                       wheelbarrows, held), and the AI's feeder piles (its
--                       workshop, linked or why not, links only, used tiles,
--                       the workshop's jobs, days empty or idle while linked).
--   remember_feeder(x, y, z, shop_id, kind, flag)   place_feeder's pile booked
--                       as the AI's own feeder (ai-builder-rooms' one hook).
--   set_barrows(o, dry)  an AI stone pile's max wheelbarrows (o.pile_id,
--                       o.barrows; at most its tiles - 1, as quickfort sets).
--   link_feeder(o, dry)  an AI feeder pile linked to its workshop (o.pile_id);
--                       o.links_only: also fed from the AI's own bigger pile
--                       of the same kind on its level, taking from links only;
--                       o.unlink: every link the AI made undone, and the
--                       workshop never linked again by the AI.
--
-- Never the player's: only piles this module or the AI's levels placed (the
-- food store's own corners and ids, ai-food-store; its own feeder registry)
-- are changed, and only workshops standing in a level the AI dug
-- (ai-builder level_areas) with no link the AI didn't make. A pile placed
-- before this module (an older feeder) is not known as the AI's and is left.
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/pile-links'   -- {feeders = {{id, shop, kind, flag, x, y, z, linked, main, links_only,
                                      --   unlinked, empty_since, idle_since}...}}
-- the workshops the AI may tie to their feeder (each takes one kind of material,
-- any of it: the stone, wood, leather, thread or cloth its feeder holds)
LINKABLE = {Masons = true, Carpenters = true, WoodFurnace = true, Leatherworks = true, Loom = true,
            Clothiers = true}
FEEDERS_MAX = 120     -- feeder piles remembered at most
PILES_MAX = 40        -- AI stone piles listed at most
BARROWS_MAX = 10      -- a pile's max wheelbarrows at most
MAIN_REACH = 40       -- a feeder's main pile: on its level, within this many tiles
TICKS_PER_DAY = 1200
WHEELBARROW = 'ITEM_TOOL_WHEELBARROW'

-- swapped by the tests
function builder() return reqscript('ai-builder') end
function food_store() return reqscript('ai-food-store') end
function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function offset()
    local ok, v = pcall(function() return df.global.world.map.region_z - 100 end)
    return ok and math.tointeger(v) or 0
end

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

-- --- df vectors (0-based, sorted by id) ----------------------------------------------

local function vlen(vec)
    local ok, n = pcall(function() return #vec end)
    return ok and n or 0
end

local function vec_has(vec, obj)
    for i = 0, vlen(vec) - 1 do
        local v = vec[i]
        if v == obj or (v ~= nil and v.id == obj.id) then return true end
    end
    return false
end

local function vec_add(vec, obj)
    if vec_has(vec, obj) then return false end
    local at = vlen(vec)
    for i = 0, vlen(vec) - 1 do
        if vec[i].id > obj.id then at = i break end
    end
    vec:insert(at, obj)
    return true
end

local function vec_drop(vec, obj)
    local n = 0
    for i = vlen(vec) - 1, 0, -1 do
        if vec[i] ~= nil and vec[i].id == obj.id then vec:erase(i) n = n + 1 end
    end
    return n > 0
end

-- --- the AI's feeder piles ---------------------------------------------------------

function registry()
    local d = U.site_get(SITE_KEY, {})
    if type(d) ~= 'table' then d = {} end
    if type(d.feeders) ~= 'table' then d.feeders = {} end
    return d
end

local function save(d) return U.site_put(SITE_KEY, d) end

local function stockpiles()
    local ok, list = pcall(function() return df.global.world.buildings.other.STOCKPILE end)
    return ok and list or {}
end

local function stockpile_at(x, y, z)
    for _, sp in ipairs(stockpiles()) do
        if sp.z == z and sp.x1 == x and sp.y1 == y then return sp end
    end
end

local function find(id)
    if id == nil then return nil end
    local ok, b = pcall(df.building.find, id)
    return ok and b or nil
end

-- The feeder place_feeder just laid: booked as the AI's own, with its workshop.
function remember_feeder(x, y, z, shop_id, kind, flag)
    local sp = stockpile_at(x, y, z)
    if not sp then return false end
    local d = registry()
    for _, f in ipairs(d.feeders) do
        if f.id == sp.id then return true end
    end
    table.insert(d.feeders, {id = sp.id, shop = math.tointeger(tonumber(shop_id)), kind = kind, flag = flag,
                             x = x, y = y, z = z})
    while #d.feeders > FEEDERS_MAX do table.remove(d.feeders, 1) end
    return save(d)
end

local function feeder_entry(d, pile_id)
    for _, f in ipairs(d.feeders) do
        if f.id == pile_id then return f end
    end
end

-- The remembered feeders whose pile is gone (or another pile stands at its
-- corner) forgotten. Saved only when something was dropped.
function prune()
    local d = registry()
    local keep, dropped = {}, 0
    for _, f in ipairs(d.feeders) do
        local sp = type(f) == 'table' and find(f.id)
        if sp and sp.x1 == f.x and sp.y1 == f.y and sp.z == f.z then table.insert(keep, f)
        else dropped = dropped + 1 end
    end
    if dropped > 0 then
        d.feeders = keep
        save(d)
    end
    return dropped
end

-- Is this stockpile the AI's own: a feeder it booked, or one the food store
-- or the AI's levels know (ai-food-store is_own).
function own_set()
    local ids = {}
    for _, f in ipairs(registry().feeders) do ids[f.id] = true end
    local okc, corners = pcall(function() return food_store().own_corners() end)
    local oki, fids = pcall(function() return food_store().own_ids() end)
    return {ids = ids, corners = okc and type(corners) == 'table' and corners or {},
            food_ids = oki and type(fids) == 'table' and fids or {}}
end

function is_own(sp, own)
    own = own or own_set()
    return own.ids[sp.id] == true or own.food_ids[sp.id] == true or own.corners[key(sp.x1, sp.y1, sp.z)] == true
end

-- --- piles ------------------------------------------------------------------------

local function takes(sp, flag)
    local ok, on = pcall(function() return sp.settings.flags[flag] end)
    return ok and on == true
end

function max_barrows(sp)
    local ok, v = pcall(function() return sp.storage.max_wheelbarrows end)
    if ok and type(v) == 'number' then return math.tointeger(v) or 0 end
    return nil
end

local function links_only(sp)
    local ok, v = pcall(function() return sp.stockpile_flag.use_links_only end)
    return ok and (v == true or v == 1)
end

local function set_links_only(sp, on)
    return pcall(function() sp.stockpile_flag.use_links_only = on end)
end

-- The pile's tiles and those holding an item (its box walked, a small one).
local function pile_tiles(sp)
    local tiles, used = 0, 0
    pcall(function()
        for y = sp.y1, sp.y2 do
            for x = sp.x1, sp.x2 do
                local des, occ = dfhack.maps.getTileFlags(x, y, sp.z)
                if des and des.pile then
                    tiles = tiles + 1
                    if occ and occ.item then used = used + 1 end
                end
            end
        end
    end)
    return tiles, used
end

-- --- the wheelbarrows ---------------------------------------------------------------

local function is_barrow(it)
    local ok, id = pcall(function() return it.subtype.id end)
    return ok and id == WHEELBARROW
end

-- Every pile's held containers: item id -> pile id (bins, barrels, wheelbarrows).
local function held_containers(piles)
    local out = {}
    for _, sp in ipairs(piles) do
        pcall(function()
            local ids = sp.storage.container_item_id
            for i = 0, vlen(ids) - 1 do out[ids[i]] = sp.id end
        end)
    end
    return out
end

function barrow_counts(piles)
    piles = piles or stockpiles()
    local held = held_containers(piles)
    local out = {owned = 0, assigned = 0, free = 0, in_job = 0, wanted = 0, by_pile = {}}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.TOOL) do
            if is_barrow(it) then
                local f = it.flags
                if not (f.removed or f.garbage_collect or f.forbid or f.trader or f.hostile) then
                    out.owned = out.owned + 1
                    local pid = held[it.id]
                    if pid then
                        out.assigned = out.assigned + 1
                        out.by_pile[pid] = (out.by_pile[pid] or 0) + 1
                    elseif f.in_job then
                        out.in_job = out.in_job + 1
                    end
                end
            end
        end
    end)
    for _, sp in ipairs(piles) do out.wanted = out.wanted + (max_barrows(sp) or 0) end
    out.free = math.max(0, out.owned - out.assigned - out.in_job)
    return out
end

-- --- workshops ----------------------------------------------------------------------

function shop_kind(b)
    local ok, kind = pcall(function()
        local t = b:getType()
        if t == df.building_type.Workshop then return df.workshop_type[b.type]
        elseif t == df.building_type.Furnace then return df.furnace_type[b.type] end
    end)
    return ok and kind or nil
end

-- (swapped by the tests) the boxes of every level the AI has dug
function ai_areas()
    local ok, areas = pcall(function() return builder().level_areas() end)
    return ok and type(areas) == 'table' and areas or {}
end

local function in_areas(areas, x, y, z)
    for _, a in ipairs(areas) do
        if type(a) == 'table' and a.z == z and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 then return true end
    end
    return false
end

local function shop_links(b)
    local ok, l = pcall(function() return b.profile.links end)
    return ok and l or nil
end

-- The workshop's jobs, and those a dwarf is at.
local function shop_jobs(b)
    local n, working = 0, 0
    pcall(function()
        for _, j in ipairs(b.jobs) do
            n = n + 1
            local okw, w = pcall(dfhack.job.getWorker, j)
            if okw and w then working = working + 1 end
        end
    end)
    return n, working
end

-- Why the AI may not link this feeder to this workshop (nil: it may).
local function link_refusal(f, sp, b, areas)
    if not b then return 'workshop_gone' end
    local kind = shop_kind(b)
    if not kind or not LINKABLE[kind] then return 'kind' end
    if not in_areas(areas, b.centerx, b.centery, b.z) then return 'players_workshop' end
    local l = shop_links(b)
    if not l then return 'no_links' end
    -- a link the AI didn't make: the player set this workshop up
    for i = 0, vlen(l.take_from_pile) - 1 do
        local p = l.take_from_pile[i]
        if p and p.id ~= sp.id then return 'player_links' end
    end
    if vlen(l.give_to_pile) > 0 then return 'player_links' end
    if f.unlinked then return 'unlinked' end
    return nil
end

-- The AI's own bigger pile of the feeder's kind on its level, nearest
-- (within MAIN_REACH), holding something: the one a feeder may take from.
local function main_pile(sp, flag, own)
    local best, bd
    local mt = pile_tiles(sp)
    for _, p in ipairs(stockpiles()) do
        if p.id ~= sp.id and p.z == sp.z and takes(p, flag) and is_own(p, own) and not own.ids[p.id] then
            local d = math.max(math.abs((p.x1 + p.x2) // 2 - (sp.x1 + sp.x2) // 2),
                               math.abs((p.y1 + p.y2) // 2 - (sp.y1 + sp.y2) // 2))
            local tiles, used = 0, 0
            if d <= MAIN_REACH then tiles, used = pile_tiles(p) end
            if d <= MAIN_REACH and tiles > mt and used > 0 and (not bd or d < bd) then best, bd = p, d end
        end
    end
    return best
end

-- --- the report --------------------------------------------------------------------

local function days_since(t, now)
    if type(t) ~= 'number' then return nil end
    return math.max(0, (now - t) // TICKS_PER_DAY)
end

function report()
    pcall(prune)
    local off, now = offset(), now_tick()
    local piles = stockpiles()
    local own = own_set()
    local barrows = barrow_counts(piles)
    local stone, ai_wanted = {}, 0
    for _, sp in ipairs(piles) do
        if takes(sp, 'stone') and is_own(sp, own) then
            local tiles, used = pile_tiles(sp)
            local mb = max_barrows(sp) or 0
            ai_wanted = ai_wanted + mb
            table.insert(stone, {id = sp.id, x1 = sp.x1, y1 = sp.y1, x2 = sp.x2, y2 = sp.y2, z = sp.z,
                                 elevation = sp.z + off, tiles = tiles, used = used, barrows = mb,
                                 held = barrows.by_pile[sp.id] or 0, feeder = own.ids[sp.id] == true or nil})
        end
    end
    table.sort(stone, function(a, b)
        if a.tiles ~= b.tiles then return a.tiles > b.tiles end
        return a.id < b.id
    end)
    while #stone > PILES_MAX do table.remove(stone) end
    barrows.by_pile = nil
    barrows.ai_wanted = ai_wanted
    local d = registry()
    local areas = ai_areas()
    local rows, unlinked, changed = {}, 0, false
    for _, f in ipairs(d.feeders) do
        local sp = find(f.id)
        if sp then
            local b = find(f.shop)
            local l = b and shop_links(b)
            local linked = l ~= nil and vec_has(l.take_from_pile, sp)
            local tiles, used = pile_tiles(sp)
            local jobs, working = 0, 0
            if b then jobs, working = shop_jobs(b) end
            -- a linked workshop with work waiting: since when its pile is empty,
            -- and since when nobody is at its jobs
            local empty = linked and used == 0 and jobs > 0
            local idle = linked and jobs > 0 and working == 0
            if empty and not f.empty_since then f.empty_since, changed = now, true
            elseif not empty and f.empty_since then f.empty_since, changed = nil, true end
            if idle and not f.idle_since then f.idle_since, changed = now, true
            elseif not idle and f.idle_since then f.idle_since, changed = nil, true end
            local why = not linked and link_refusal(f, sp, b, areas) or nil
            local main = not linked and not why and main_pile(sp, f.flag or 'stone', own) or nil
            table.insert(rows, {pile_id = sp.id, shop_id = f.shop, kind = f.kind, flag = f.flag,
                                x = sp.x1, y = sp.y1, z = sp.z, elevation = sp.z + off,
                                linked = linked, links_only = links_only(sp), why = why,
                                main = main and main.id or (linked and f.main) or nil,
                                tiles = tiles, used = used, jobs = jobs, working = working,
                                empty_days = days_since(f.empty_since, now),
                                idle_days = days_since(f.idle_since, now), unlinked = f.unlinked or nil})
            if not linked then unlinked = unlinked + 1 end
        end
    end
    if changed then save(d) end
    return {barrows = barrows, stone_piles = stone, feeders = rows, unlinked = unlinked, feeders_ai = #rows,
            linkable = (function()
                local k = {}
                for n in pairs(LINKABLE) do table.insert(k, n) end
                table.sort(k)
                return k
            end)()}
end

-- --- the actions -------------------------------------------------------------------

local function clamp(v, lo, hi)
    local n = math.tointeger(tonumber(v))
    if not n then return nil end
    return math.max(lo, math.min(hi, n))
end

function set_barrows(o, dry_run)
    local id = math.tointeger(tonumber(o.pile_id))
    local sp = id and find(id)
    if not sp or not takes(sp, 'stone') then
        return {ok = false, rejected = true, stale = {'pile_links'}, error = 'no stone stockpile with that id'}
    end
    if not is_own(sp) then
        return {ok = false, rejected = true, error = 'that stone pile is the player\'s: the AI leaves it as it is'}
    end
    local tiles = pile_tiles(sp)
    local n = clamp(o.barrows, 0, math.min(BARROWS_MAX, math.max(tiles - 1, 0)))
    if not n then return {ok = false, rejected = true, error = 'barrows must be a number'} end
    local had = max_barrows(sp)
    if had == nil then return {ok = false, error = 'the pile\'s max wheelbarrows could not be read'} end
    if had == n then
        return {ok = false, rejected = true, stale = {'pile_links'}, error = ('it takes %d wheelbarrows already'):format(n)}
    end
    local out = {ok = true, pile_id = sp.id, barrows = n, had = had, dry_run = dry_run or nil}
    if dry_run then return out end
    if not pcall(function() sp.storage.max_wheelbarrows = n end) then
        return {ok = false, error = 'the game would not take the max wheelbarrows'}
    end
    return out
end

local function unlink(d, f, sp, b, dry_run)
    local out = {ok = true, pile_id = sp.id, shop_id = f.shop, unlinked = true, dry_run = dry_run or nil}
    if dry_run then return out end
    local l = b and shop_links(b)
    if l then vec_drop(l.take_from_pile, sp) end
    pcall(function() if b then vec_drop(sp.links.give_to_workshop, b) end end)
    local m = f.main and find(f.main)
    if m then
        pcall(function() vec_drop(m.links.give_to_pile, sp) end)
        pcall(function() vec_drop(sp.links.take_from_pile, m) end)
    end
    if f.links_only then set_links_only(sp, false) end
    f.linked, f.main, f.links_only, f.unlinked = nil, nil, nil, true
    f.empty_since, f.idle_since = nil, nil
    save(d)
    return out
end

function link_feeder(o, dry_run)
    local id = math.tointeger(tonumber(o.pile_id))
    local d = registry()
    local f = id and feeder_entry(d, id)
    local sp = f and find(id)
    if not sp then
        return {ok = false, rejected = true, stale = {'pile_links'},
                error = 'not a feeder pile the AI placed (the AI links only its own)'}
    end
    local b = find(f.shop)
    local l = b and shop_links(b)
    local linked = l ~= nil and vec_has(l.take_from_pile, sp)
    if o.unlink then
        if not linked and not f.links_only then
            return {ok = false, rejected = true, stale = {'pile_links'}, error = 'the feeder is not linked'}
        end
        return unlink(d, f, sp, b, dry_run)
    end
    if linked then
        return {ok = false, rejected = true, stale = {'pile_links'}, error = 'the feeder is linked already'}
    end
    local why = link_refusal(f, sp, b, ai_areas())
    if why then
        local words = {workshop_gone = 'its workshop is gone', kind = 'that workshop uses more than one material',
                       players_workshop = 'the workshop is the player\'s', no_links = 'the workshop takes no links',
                       player_links = 'the player linked that workshop', unlinked = 'the AI took its link off once'}
        return {ok = false, rejected = true, why = why, error = 'not linked: ' .. (words[why] or why)}
    end
    local own = own_set()
    local main = o.links_only and main_pile(sp, f.flag or 'stone', own) or nil
    local out = {ok = true, pile_id = sp.id, shop_id = b.id, kind = shop_kind(b), main = main and main.id or nil,
                 links_only = main and true or nil, dry_run = dry_run or nil}
    if o.links_only and not main then out.note = 'no AI pile of its kind near to feed it: it takes loose things too' end
    if dry_run then return out end
    local okl, err = pcall(function()
        vec_add(l.take_from_pile, sp)
        vec_add(sp.links.give_to_workshop, b)
    end)
    if not okl then return {ok = false, error = 'the game would not take the link: ' .. tostring(err):sub(1, 120)} end
    f.linked = true
    if main then
        local okm = pcall(function()
            vec_add(main.links.give_to_pile, sp)
            vec_add(sp.links.take_from_pile, main)
        end)
        if okm and set_links_only(sp, true) then
            f.main, f.links_only = main.id, true
        else
            pcall(function() vec_drop(main.links.give_to_pile, sp) end)
            pcall(function() vec_drop(sp.links.take_from_pile, main) end)
            out.main, out.links_only, out.warning = nil, nil, 'the pile-to-pile link would not take'
        end
    end
    save(d)
    return out
end
