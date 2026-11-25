-- ai-homes-furnish: a piece in a dwarf's own room from the stock, in a
-- material or showing a creature they like; the report's citizens_taste.
--
-- (r9) A part of ai-homes, not a script of its own: ai-homes.lua loads it
-- into its own environment, so every name here is reqscript('ai-homes').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-homes-furnish is a part of ai-homes; run ai-homes') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-homes-furnish'] = '0.105.110'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, location_zone_ids, load_liked_statues, furnish, stress_cat, people, can_walk, enum_name = PART_LOCALS.U, PART_LOCALS.location_zone_ids, PART_LOCALS.load_liked_statues, PART_LOCALS.furnish, PART_LOCALS.stress_cat, PART_LOCALS.people, PART_LOCALS.can_walk, PART_LOCALS.enum_name   -- (r9) the hub's locals

-- --- (E4) rooms furnished in what the dwarf likes --------------------------
--
-- furnish_liked(n): for up to n citizens whose own bedroom the AI dug (inside
-- one of its projects' outlines, the old ones too: a player's room is never
-- furnished), one piece of furniture from the fort's stock put up in it: a
-- statue whose image shows a creature or an item they like (DF's art image:
-- the statue's image elements), or one of a material they like; else a
-- cabinet, a chest, a table or a chair of a liked material or kind. Only a
-- kind the room doesn't have; only an item free for a new job (ai-util's
-- one list: never in a job, owned, forbidden, an artifact...), lying on the
-- ground, that the room's bed can be walked to from; never while a strange
-- mood gathers (the moody take what they please); a statue (it blocks the
-- way) only on a floor tile whose neighbours stay joined without it. The
-- statues it puts up are kept in the save (LIKED_STATUES_KEY), so the room
-- still counts as a bedroom, not a noble's suite.

FURNISH_KINDS = {
    {kind = 'Statue', list = 'STATUE', blocking = true},
    {kind = 'Cabinet', list = 'CABINET'},
    {kind = 'Box', list = 'BOX'},
    {kind = 'Table', list = 'TABLE'},
    {kind = 'Chair', list = 'CHAIR'},
}
FURNISH_MAX = 10
STRANGE_MOODS = {Fey = true, Secretive = true, Possessed = true, Macabre = true, Fell = true}
-- building types a dwarf can't walk through
BLOCKING = {Statue = true, Support = true, GrateWall = true, BarsVertical = true, Window = true}

-- a material's kind: stone, metal, gem, glass, wood or other
local function mat_kind(mt, mi)
    local ok, k = pcall(function()
        local info = dfhack.matinfo.decode(mt, mi)
        local f = info.material.flags
        if f.IS_GEM then return 'gem' end
        if f.IS_METAL then return 'metal' end
        if f.IS_GLASS then return 'glass' end
        if f.IS_STONE then return 'stone' end
        if f.WOOD or f.STRUCTURAL_PLANT_MAT then return 'wood' end
        return 'other'
    end)
    return ok and k or 'other'
end

-- The tile hooks (the tests swap them): ai-builder's tile reading.
function TILE(x, y, z) return reqscript('ai-builder').tile_info(x, y, z) end
function BLOCKED_AT(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, x, y, z)
    if not ok or not b then return false end
    return BLOCKING[df.building_type[b:getType()]] == true
end
function DOOR_AT(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, x, y, z)
    if not ok or not b then return false end
    local t = df.building_type[b:getType()]
    return t == 'Door' or t == 'Hatch'
end
-- The outlines of every level the AI dug (its projects' and the old ones'):
-- {{x1, y1, x2, y2, z}}. A module field: the tests swap it.
function ai_areas()
    local out = {}
    pcall(function()
        local B = reqscript('ai-builder')
        local data = B.load_projects()
        for _, p in ipairs(data.list) do
            if p.kind ~= 'way_in' then
                for _, a in ipairs(B.project_areas(p)) do table.insert(out, a) end
            end
        end
        for _, a in ipairs(type(data.old_areas) == 'table' and data.old_areas or {}) do table.insert(out, a) end
    end)
    return out
end

local function in_areas(areas, pos)
    if not pos then return false end
    for _, a in ipairs(areas) do
        if type(a) == 'table' and a.z == pos.z and tonumber(a.x1) and pos.x >= a.x1 and pos.x <= a.x2
                and pos.y >= a.y1 and pos.y <= a.y2 then
            return true
        end
    end
    return false
end

local function shape_ok(t)
    local s = t and tostring(t.shape) or ''
    return s == 'FLOOR' or s == 'RAMP' or s:find('STAIR') ~= nil
end

local function passable(x, y, z)
    local t = TILE(x, y, z)
    if not shape_ok(t) then return false end
    return not (t.building and BLOCKED_AT(x, y, z))
end

-- the eight around a tile, in turn (each next to the one before)
local RING = {{0, -1}, {1, -1}, {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}, {-1, -1}}
local ORTHO4 = {{1, 0}, {-1, 0}, {0, 1}, {0, -1}}

-- Would a building that blocks the way on (x, y) leave its walkable
-- neighbours joined? (Counted round the ring through orthogonal steps only:
-- stricter than DF, which also steps diagonally.)
function keeps_way(x, y, z)
    local open = {}
    for i, d in ipairs(RING) do open[i] = passable(x + d[1], y + d[2], z) end
    local runs, any = 0, false
    for i = 1, 8 do
        if open[i] then
            any = true
            if not open[(i - 2) % 8 + 1] then runs = runs + 1 end
        end
    end
    if any and runs == 0 then runs = 1 end      -- all eight open
    return any and runs <= 1
end

-- The free floor tiles inside a bedroom zone for one more piece: beside a
-- wall (or in the open with room all round), not in front of a door; for a
-- blocking piece, only where the way round stays (keeps_way). Beside a
-- wall first, then reading order.
function room_spots(z, blocking)
    local spots = {}
    pcall(function()
        for y = z.y1, z.y2 do
            for x = z.x1, z.x2 do
                local okc, inside = pcall(dfhack.buildings.containsTile, z, x, y)
                local t = (not okc or inside) and TILE(x, y, z.z)
                if t and tostring(t.shape) == 'FLOOR' and not t.building and not t.items and not t.liquid then
                    local walls, door, open = 0, false, 0
                    for _, d in ipairs(ORTHO4) do
                        local n = TILE(x + d[1], y + d[2], z.z)
                        if n and tostring(n.shape) == 'WALL' then walls = walls + 1
                        elseif n and n.building and DOOR_AT(x + d[1], y + d[2], z.z) then door = true
                        elseif shape_ok(n) then open = open + 1 end
                    end
                    if not door and ((walls >= 1 and open >= 1) or (walls == 0 and open >= 4))
                            and (not blocking or keeps_way(x, y, z.z)) then
                        table.insert(spots, {x = x, y = y, z = z.z, walls = walls})
                    end
                end
            end
        end
    end)
    table.sort(spots, function(a, b)
        if (a.walls == 0) ~= (b.walls == 0) then return b.walls == 0 end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    return spots
end

-- What a statue's image shows: {creatures = {race = true}, items = {'it' = true}}
local function image_of(it)
    local out = {creatures = {}, items = {}}
    pcall(function()
        local chunk = df.art_image_chunk.find(it.image.id)
        local img = chunk.images[it.image.subid].art_image
        for _, e in ipairs(img.elements) do
            local okr, race = pcall(function() return e.race end)
            if okr and tonumber(race) and race >= 0 then out.creatures[race] = true end
            local oki, ity = pcall(function() return e.item_type end)
            if oki and tonumber(ity) and ity >= 0 then out.items[tostring(ity)] = true end
        end
    end)
    return out
end

-- The free furniture in stock: {kind = {{it, mt, mi, ity, ist, pos, img}}}
function stock_furniture()
    local out = {}
    for _, k in ipairs(FURNISH_KINDS) do
        local list = {}
        pcall(function()
            for _, it in ipairs(df.global.world.items.other[k.list]) do
                local okf, free = pcall(function() return it.flags.on_ground and U.item_free(it) end)
                if okf and free then
                    local r = {it = it, mt = it:getMaterial(), mi = it:getMaterialIndex(), ity = it:getType(),
                               ist = it:getSubtype()}
                    local okp, x, y, z = pcall(dfhack.items.getPosition, it)
                    r.pos = okp and x and {x = x, y = y, z = z} or nil
                    -- (a chest, not a bag: a bag is cloth or leather)
                    local mk = k.kind == 'Box' and mat_kind(r.mt, r.mi) or nil
                    if r.pos and (k.kind ~= 'Box' or mk == 'stone' or mk == 'metal' or mk == 'wood'
                                  or mk == 'glass' or mk == 'gem') then
                        if k.kind == 'Statue' then r.img = image_of(it) end
                        table.insert(list, r)
                    end
                end
            end
        end)
        out[k.kind] = list
    end
    return out
end

-- How much the household would like the item: 3 for a statue showing a
-- creature or an item they like, 2 for a material they like, 1 for a kind
-- of item they like; 0: not at all.
local function like_score(r, ps)
    local s = 0
    for _, p in ipairs(ps) do
        local t = taste_of(p)
        local n = 0
        if r.img then
            for race in pairs(r.img.creatures) do if t.creature[race] then n = n + 3 break end end
            for ity in pairs(r.img.items) do
                if t.item[ity .. ':-1'] then n = n + 3 break end
                local hit = false
                for key in pairs(t.item) do if key:match('^' .. ity .. ':') then hit = true break end end
                if hit then n = n + 3 break end
            end
        end
        if t.mat[r.mt .. ':' .. r.mi] then n = n + 2 end
        if t.item[r.ity .. ':' .. r.ist] or t.item[r.ity .. ':-1'] then n = n + 1 end
        s = s + n
    end
    return s
end

local function strange_mood_now(order)
    for _, p in ipairs(order) do
        local ok, m = pcall(function() return df.mood_type[p.u.mood] end)
        if ok and STRANGE_MOODS[m] then return true end
    end
    return false
end

-- The plan: up to `max` {p, ps, room, z, kind, item, spot, score, why}
-- (one piece a household), most stressed first.
function furnish_plan(by, order, max)
    local plan = {}
    if strange_mood_now(order) then return plan, 'a strange mood is gathering what it wants' end
    local areas = ai_areas()
    if #areas == 0 then return plan, 'no room the AI dug' end
    local loc = location_zone_ids()
    local stock = stock_furniture()
    local any = false
    for _, l in pairs(stock) do if #l > 0 then any = true end end
    if not any then return plan, 'no free furniture in stock' end
    local cands = {}
    for _, p in ipairs(order) do
        local q = p.spouse and by[p.spouse]
        -- the room's owner, once a household (a couple's: the one whose name it's in)
        if not p.child and #p.own == 1 and not (q and #q.own > 0 and q.id < p.id) then
            table.insert(cands, {p = p, cat = stress_cat(p.u)})
        end
    end
    table.sort(cands, function(a, b) if a.cat ~= b.cat then return a.cat < b.cat end return a.p.id < b.p.id end)
    local taken = {}
    for _, c in ipairs(cands) do
        if #plan >= max then break end
        local p = c.p
        local z = p.own[1]
        local room = furnish(z)
        if room.bed_pos and not loc[z.id] and in_areas(areas, room.bed_pos) then
            local q = p.spouse and by[p.spouse]
            local ps = q and {p, q} or {p}
            local best
            for _, k in ipairs(FURNISH_KINDS) do
                if not room.kinds[k.kind] and not (k.kind == 'Statue' and room.statue) then
                    for _, r in ipairs(stock[k.kind] or {}) do
                        if not taken[r] then
                            local s = like_score(r, ps)
                            if s > 0 and (not best or s > best.score) then
                                best = {kind = k, item = r, score = s}
                            end
                        end
                    end
                end
            end
            if best and can_walk(p.u, best.item.pos) then
                local okw, walk = pcall(function() return dfhack.maps.canWalkBetween(best.item.pos, room.bed_pos) end)
                local spot = (not okw or walk ~= false) and room_spots(z, best.kind.blocking)[1] or nil
                if spot then
                    taken[best.item] = true
                    table.insert(plan, {p = p, ps = ps, z = z, kind = best.kind.kind, item = best.item, spot = spot,
                                        score = best.score})
                end
            end
        end
    end
    return plan, #plan == 0 and 'no citizen\'s room lacks a piece they would like that the stock has' or nil
end

local function liked_words(e, txt)
    local r = e.item
    local what = e.score >= 3 and (r.img and 'showing something they like' or 'they like') or
                 (e.score >= 2 and 'of a material they like' or 'of a kind they like')
    local mat = ''
    pcall(function() mat = ' of ' .. txt(dfhack.matinfo.decode(r.mt, r.mi):toString()) end)
    return ('a %s%s, %s'):format(e.kind:lower() == 'box' and 'chest' or e.kind:lower(), mat, what)
end

function furnish_liked(n, dry_run, txt, units)
    txt = txt or tostring
    n = math.max(1, math.min(FURNISH_MAX, tonumber(n) or 1))
    local store = load_liked_statues()
    local by, order = people(units)
    local plan, why = furnish_plan(by, order, n)
    local out = {placed = 0, lines = {}, dry_run = dry_run or nil}
    local function name(p) return txt(dfhack.units.getReadableName(p.u)) end
    local new_statues = {}
    for _, e in ipairs(plan) do
        local ok = dry_run
        if not dry_run then
            local pos = xyz2pos and xyz2pos(e.spot.x, e.spot.y, e.spot.z) or {x = e.spot.x, y = e.spot.y, z = e.spot.z}
            local okc, b = pcall(dfhack.buildings.constructBuilding,
                                 {type = df.building_type[e.kind], pos = pos, items = {e.item.it}})
            ok = okc and b ~= nil
            if ok and e.kind == 'Statue' then table.insert(new_statues, b.id) end
        end
        if ok then
            out.placed = out.placed + 1
            if #out.lines < 8 then
                table.insert(out.lines, name(e.p) .. "'s room: " .. liked_words(e, txt))
            end
        end
    end
    if #new_statues > 0 then
        local ids = type(store.ids) == 'table' and store.ids or {}
        for _, id in ipairs(new_statues) do table.insert(ids, id) end
        while #ids > 400 do table.remove(ids, 1) end
        U.site_put(LIKED_STATUES_KEY, {ids = ids})
    end
    out.ok = out.placed > 0
    if not out.ok then
        out.rejected = true
        out.error = why or 'the game took none of the pieces'
    end
    return out
end

-- --- (E4) the report's citizens_taste section -------------------------------

-- (for the tests and a look in the console) each citizen's taste by id:
-- {id = {place, craft, lean, dreams}}
function citizen_tastes(units)
    local _, order = people(units)
    local out = {}
    for _, p in ipairs(order) do
        local t = taste_of(p)
        out[p.id] = {place = t.place, craft = t.craft, lean = t.lean, dreams = t.dreams, plant = t.plant}
    end
    return out
end

local function top(counts, n, describe)
    local list = {}
    for k, c in pairs(counts) do table.insert(list, {k = k, n = c}) end
    table.sort(list, function(a, b) if a.n ~= b.n then return a.n > b.n end return tostring(a.k) < tostring(b.k) end)
    local out = {}
    for i = 1, math.min(n, #list) do
        local e = describe(list[i].k)
        e.n = list[i].n
        table.insert(out, e)
    end
    return out
end

-- The citizens' taste, summed over the grown-ups (once in 3 days: each
-- citizen's soul and the free furniture read): how many hold each leaning,
-- where their rooms would go, their values and dreams, the most liked
-- materials, creatures, items, colours, shapes and plants (token, name, n),
-- and how many rooms furnish_liked could furnish now.
function citizens_taste(units, txt)
    txt = txt or tostring
    load_liked_statues()
    local by, order = people(units)
    local out = {citizens = #order, adults = 0, leanings = {}, place = {}, values = {}, dreams = {}}
    local mats, creatures, items, colors, shapes, plants = {}, {}, {}, {}, {}, {}
    local matkey = {}
    local function bump(t, k) t[k] = (t[k] or 0) + 1 end
    for _, p in ipairs(order) do
        if not p.child then
            out.adults = out.adults + 1
            local t = taste_of(p)
            for k, v in pairs(t.lean) do if v >= TASTE_HOLD then bump(out.leanings, k) end end
            if t.place then bump(out.place, t.place) end
            for k in pairs(t.values) do bump(out.values, k) end
            for _, d in ipairs(t.dreams) do bump(out.dreams, d) end
            for k, m in pairs(t.mat) do bump(mats, k); matkey[k] = m end
            for k in pairs(t.creature) do bump(creatures, k) end
            for k in pairs(t.item) do bump(items, k) end
            for k in pairs(t.color) do bump(colors, k) end
            for k in pairs(t.shape) do bump(shapes, k) end
            for k in pairs(t.plant) do bump(plants, k) end
        end
    end
    -- (creature_raw: creature_id and name[0]; colours, shapes, plants: id and name)
    local function raw_name(kind, id)
        local e = {}
        pcall(function()
            if kind == 'creature' then
                local r = df.creature_raw.find(id)
                e.token = tostring(r.creature_id)
                e.name = txt(r.name[0])
            else
                local r = df[kind].find(id)
                e.token = tostring(r.id)
                e.name = txt(r.name)
            end
        end)
        e.token = e.token or tostring(id)
        return e
    end
    out.likes = {
        materials = top(mats, TASTE_TOP, function(k)
            local m = matkey[k]
            local e = {kind = mat_kind(m[1], m[2])}
            pcall(function()
                local info = dfhack.matinfo.decode(m[1], m[2])
                e.token = info:getToken()
                e.name = txt(info:toString())
            end)
            e.token = e.token or k
            return e
        end),
        creatures = top(creatures, TASTE_TOP, function(k) return raw_name('creature', k) end),
        items = top(items, TASTE_TOP, function(k)
            local it = tonumber(k:match('^(-?%d+)'))
            return {token = tostring(enum_name(df.item_type, it) or k)}
        end),
        colors = top(colors, 3, function(k) return raw_name('descriptor_color', k) end),
        shapes = top(shapes, 3, function(k) return raw_name('descriptor_shape', k) end),
        plants = top(plants, 3, function(k) return raw_name('plant_raw', k) end),
    }
    -- a few dwarves and where their rooms would go (taste_of's place)
    out.samples = {}
    for _, p in ipairs(order) do
        if #out.samples >= SAMPLES then break end
        local t = p.taste
        if t and t.place then
            table.insert(out.samples, txt(dfhack.units.getReadableName(p.u)) .. ': ' .. t.place
                         .. (#t.dreams > 0 and (' (dreams: ' .. t.dreams[1]:lower():gsub('_', ' ') .. ')') or ''))
        end
    end
    local okp, plan, why = pcall(furnish_plan, by, order, FURNISH_MAX)
    out.furnish_ready = okp and #plan or 0
    if okp and #plan == 0 and why then out.furnish_why = why end
    out.strange_mood = strange_mood_now(order) or nil
    return out
end
