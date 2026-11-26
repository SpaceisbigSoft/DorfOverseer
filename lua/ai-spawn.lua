-- ai-spawn: units set down on the map by the AI's own tests (the siege test's
-- war party, ai-siege-invite spawn_party; the danger test's invaders,
-- ai-military-duty spawn_test_threat). One call, spawn_units{...}:
--
--   race      creature token ('GOBLIN') or race index
--   caste     caste token or index; nil: each unit a random caste
--   count     units (1..SPAWN_MAX)
--   pos       {x, y, z}: where they go
--   spread    tiles round pos they are spread over (same level)
--   civ_id    their civilisation (-1/nil: none); group_id: a government of it
--             (create-unit only: the arena makes no historical figures)
--   flags     unit flags1 names set on each ('active_invader', ...)
--   equip     a list of create-unit equipment strings
--             ('ITEM_WEAPON_SPEAR:INORGANIC:IRON'); true: none named, nothing
--             given; nil/false: unarmed
--
-- Returns the new units' ids and info {route ('create-unit' or 'arena'),
-- equipped, equip_error, cu_error}, or nil, a short reason and info. Never
-- throws.
--
-- Two routes, in order:
--  1. DFHack's modtools/create-unit (in case a later DFHack fixes it). DFHack
--     53.17-r1's is stale for DF 53: "create-unit.lua:164: Cannot read field
--     world.arena_spawn: not found" (A, 25 Nov 23:21); it also drives the
--     pre-Steam arena screens (viewscreen_dwarfmodest:new, D_LOOK_ARENA_CREATURE).
--  2. DF 53's own arena spawner, the way DFHack 53's gui/sandbox drives it,
--     done from code: the game made an arena for a moment (gametype
--     DWARF_ARENA), world.arena's race/caste lists holding only this race,
--     the arena's creature window opened on the map screen
--     (ARENA_CREATE_CREATURE), the race picked in main_interface.arena_unit,
--     one left click on a map tile per unit (the tile under the mouse read
--     back from DFHack, only in the screen's middle-right, away from the
--     game's own panels); the new units are those with ids from the old
--     unit_next_id, each moved at once to its tile round pos. Everything it
--     changed (gametype, gamemode, pause, the view, the mouse, world.arena's
--     lists, arena_unit, the bottom menu, the unit sheet) is put back
--     whatever happened, and any screen the clicks pushed is dismissed.
--     Equipment: world.arena.equipment's lists (what the arena gives each
--     unit it makes); refused or not given: the units come unarmed.
--
-- DF 53 names used are DFHack 53.17-r1's (tests/fixtures/df-names.json):
-- world.arena (race, caste, creature_cnt, last_race, last_caste, interaction,
-- equipment.item_types/item_subtypes/item_materials/item_counts),
-- game.main_interface.arena_unit (open, context, race, caste, interaction,
-- editing_filter, races_filtered, castes_filtered, races_all, castes_all).
--@ module = true

SPAWN_MAX = 30
-- the screen part (fractions of gps.dimx, dimy) the arena's clicks go in:
-- right of the middle, clear of the top bar, the bottom toolbar and the
-- creature window (the game draws it on the left)
CLICK_X = {0.50, 0.80}
CLICK_Y = {0.30, 0.70}
CLICK_STEP = 2                -- every 2nd text column and row of it looked at
EQUIP_KINDS = {               -- create-unit's item tokens: the item type, the raws' list
    {'ITEM_WEAPON_', 'WEAPON', 'weapons'}, {'ITEM_ARMOR_', 'ARMOR', 'armor'}, {'ITEM_HELM_', 'HELM', 'helms'},
    {'ITEM_SHIELD_', 'SHIELD', 'shields'}, {'ITEM_PANTS_', 'PANTS', 'pants'}, {'ITEM_SHOES_', 'SHOES', 'shoes'},
    {'ITEM_GLOVES_', 'GLOVES', 'gloves'}, {'ITEM_AMMO_', 'AMMO', 'ammo'},
}

local function try(f, ...)
    local ok, v = pcall(f, ...)
    if ok then return v end
    return nil
end

-- an error's text without its "file:line: " head, cut short
local function short(e, n)
    local s = tostring(e):gsub('^[^\n]-%.lua:%d+: ', ''):gsub('^%[string "[^"]*"%]:%d+: ', '')
    return s:sub(1, n or 120)
end

local function vlen(v) return try(function() return #v end) or 0 end

-- a DF vector's values as a Lua list (1-based), and back
local function vcopy(v)
    local t = {}
    for i = 0, vlen(v) - 1 do t[#t + 1] = v[i] end
    return t
end

local function vset(v, t)
    v:resize(0)
    for _, x in ipairs(t) do v:insert('#', x) end
end

-- the race's index and raw, and its castes' indices (the one named, or all)
function race_castes(race, caste)
    local creatures = df.global.world.raws.creatures.all
    local rid, cre
    if type(race) == 'number' then
        rid, cre = race, creatures[race]
    else
        for i, c in ipairs(creatures) do
            if c.creature_id == race then rid, cre = i, c break end
        end
    end
    if not cre then return nil, 'no creature ' .. tostring(race) end
    local castes = {}
    for i, c in ipairs(cre.caste) do
        if caste == nil or caste == i or c.caste_id == caste then table.insert(castes, i) end
    end
    if #castes == 0 then return nil, 'no caste ' .. tostring(caste) .. ' of ' .. tostring(race) end
    return rid, castes
end

-- a tile a unit can stand on: walkable, no water or magma, no building
-- (outside: and open to the sky, as pos is)
function standable(x, y, z, outside)
    local ok, good = pcall(function()
        if not dfhack.maps.isValidTilePos(x, y, z) then return false end
        local tt = dfhack.maps.getTileType(x, y, z)
        if not tt then return false end
        local a = df.tiletype_shape.attrs[df.tiletype.attrs[tt].shape]
        if not a or not a.walkable then return false end
        local f = dfhack.maps.getTileFlags(x, y, z)
        if not f or (f.flow_size or 0) > 0 then return false end
        if outside and not f.outside then return false end
        return dfhack.buildings.findAtTile(xyz2pos(x, y, z)) == nil
    end)
    return ok and good
end

-- the tiles round pos (pos first, then by distance) the units go to: standable,
-- on pos's walkable group (none inside the fort when pos is outside)
function spawn_tiles(pos, spread)
    local f = try(dfhack.maps.getTileFlags, pos.x, pos.y, pos.z)
    local outside = f and f.outside or false
    local grp = try(dfhack.maps.getWalkableGroup, xyz2pos(pos.x, pos.y, pos.z))
    local out = {}
    for dy = -spread, spread do
        for dx = -spread, spread do
            local x, y = pos.x + dx, pos.y + dy
            if standable(x, y, pos.z, outside) then
                local g = try(dfhack.maps.getWalkableGroup, xyz2pos(x, y, pos.z))
                if not grp or grp == 0 or g == grp then
                    table.insert(out, {x = x, y = y, z = pos.z, d = dx * dx + dy * dy})
                end
            end
        end
    end
    table.sort(out, function(a, b) return a.d < b.d end)
    return out
end

-- create-unit's equipment strings as {item_type, subtype, mat_type, mat_index}
function equip_rows(list)
    local rows = {}
    for _, s in ipairs(list) do
        local tok, mat = tostring(s):match('^([%w_]+):(.+)$')
        if not tok then error('bad equipment ' .. tostring(s)) end
        local kind
        for _, k in ipairs(EQUIP_KINDS) do
            if tok:sub(1, #k[1]) == k[1] then kind = k break end
        end
        if not kind then error('unknown item ' .. tok) end
        local sub
        for _, d in ipairs(df.global.world.raws.itemdefs[kind[3]]) do
            if d.id == tok then sub = d.subtype break end
        end
        if not sub then error('no item ' .. tok) end
        local mi = dfhack.matinfo.find(mat)
        if not mi then error('no material ' .. mat) end
        table.insert(rows, {df.item_type[kind[2]], sub, mi.type, mi.index})
    end
    return rows
end

-- the units made since: ids from `next0` (unit_next_id before), else (with
-- `before`) the active units not in it
local function made_since(next0, before)
    local out = {}
    local next1 = try(function() return df.global.unit_next_id end)
    if next0 and next1 and next1 > next0 then
        for id = next0, next1 - 1 do
            local u = try(df.unit.find, id)
            if u then table.insert(out, u) end
        end
        return out
    end
    if not before then return out end
    for _, u in ipairs(try(function() return df.global.world.units.active end) or {}) do
        if not before[u.id] then table.insert(out, u) end
    end
    return out
end

local function active_ids()
    local seen = {}
    for _, u in ipairs(try(function() return df.global.world.units.active end) or {}) do seen[u.id] = true end
    return seen
end

-- --- route 1: modtools/create-unit ---------------------------------------------------------

local function by_create_unit(o)
    local okm, CU = pcall(reqscript, 'modtools/create-unit')
    if not okm or type(CU) ~= 'table' or not CU.createUnit then return nil, 'DFHack has no modtools/create-unit' end
    local range = {offset_x = o.spread, offset_y = o.spread, offset_z = 0}
    local function make(eq)
        local next0 = try(function() return df.global.unit_next_id end)
        local before = active_ids()
        local units = CU.createUnit(o.race, o.caste, o.pos, range, 'Walkable', nil, false, o.civ_id, o.group_id,
                                    nil, nil, nil, o.count, eq, nil, nil, nil, o.flags, nil)
        if type(units) ~= 'table' or #units == 0 then units = made_since(next0, before) end
        if #units == 0 then error('no unit made') end
        return units
    end
    local eq = type(o.equip) == 'table' and #o.equip > 0 and o.equip or nil
    local ok, units = pcall(make, eq)
    local equip_error
    if not ok and eq then
        equip_error = short(units)
        eq = nil
        ok, units = pcall(make, nil)
    end
    if not ok then return nil, short(units, 160) end
    return units, nil, {equipped = eq ~= nil, equip_error = equip_error}
end

-- --- route 2: DF 53's arena -----------------------------------------------------------------

local function set_mouse(x, y)
    local gps = df.global.gps
    gps.mouse_x, gps.mouse_y = x, y
    pcall(function()
        gps.precise_mouse_x = x * gps.tile_pixel_x + gps.tile_pixel_x // 2
        gps.precise_mouse_y = y * gps.tile_pixel_y + gps.tile_pixel_y // 2
    end)
end

-- the screen points (text columns, rows) in CLICK_X/CLICK_Y whose map tile
-- (as DFHack reads the mouse) a unit can stand on, nearest pos first
function click_points(pos)
    local gps = df.global.gps
    local w, h = gps.dimx, gps.dimy
    local seen, out = {}, {}
    for sy = math.floor(h * CLICK_Y[1]), math.floor(h * CLICK_Y[2]), CLICK_STEP do
        for sx = math.floor(w * CLICK_X[1]), math.floor(w * CLICK_X[2]), CLICK_STEP do
            set_mouse(sx, sy)
            local m = try(dfhack.gui.getMousePos)
            if m and m.x and m.x >= 0 then
                local k = m.x .. ',' .. m.y .. ',' .. m.z
                if not seen[k] and standable(m.x, m.y, m.z, false) then
                    seen[k] = true
                    -- outside first (a unit the teleport fails to move stays where it was made)
                    local inside = standable(m.x, m.y, m.z, true) and 0 or 1000000
                    table.insert(out, {sx = sx, sy = sy, x = m.x, y = m.y, z = m.z,
                                       d = (m.x - pos.x) ^ 2 + (m.y - pos.y) ^ 2 + 100 * math.abs(m.z - pos.z) + inside})
                end
            end
        end
    end
    table.sort(out, function(a, b) return a.d < b.d end)
    return out
end

-- the index in `vec` holding `want` (a race id), else 0; nil when empty
local function pick_index(vec, want)
    local n = vlen(vec)
    if n == 0 then return nil, 0 end
    for i = 0, n - 1 do
        if try(function() return vec[i] end) == want then return i, n end
    end
    return 0, n
end

-- what the arena's window shows, for a reason
local function arena_words(au)
    return ('arena_unit open=%s race=%s caste=%s races_filtered=%d castes_filtered=%d races_all=%d castes_all=%d')
        :format(tostring(try(function() return au.open end)), tostring(try(function() return au.race end)),
                tostring(try(function() return au.caste end)), vlen(try(function() return au.races_filtered end)),
                vlen(try(function() return au.castes_filtered end)), vlen(try(function() return au.races_all end)),
                vlen(try(function() return au.castes_all end)))
end

-- everything the arena route changes, read before it changes it
local function save_state(eq)
    local g, mi, arena = df.global, df.global.game.main_interface, df.global.world.arena
    local au, gps = mi.arena_unit, df.global.gps
    local S = {gametype = g.gametype, gamemode = g.gamemode, pause = g.pause_state,
               window = {g.window_x, g.window_y, g.window_z}, mouse = {gps.mouse_x, gps.mouse_y},
               bottom = mi.bottom_mode_selected, sheets = try(function() return mi.view_sheets.open end),
               race = vcopy(arena.race), caste = vcopy(arena.caste), cnt = vcopy(arena.creature_cnt),
               last_race = arena.last_race, last_caste = arena.last_caste, interaction = arena.interaction,
               au_race = au.race, au_caste = au.caste, au_interaction = au.interaction,
               au_context = try(function() return au.context end), au_filter = au.editing_filter}
    pcall(function() S.precise = {gps.precise_mouse_x, gps.precise_mouse_y} end)
    if eq then
        S.eq = {types = vcopy(arena.equipment.item_types), subtypes = vcopy(arena.equipment.item_subtypes),
                mt = vcopy(arena.equipment.item_materials.mat_type), mi = vcopy(arena.equipment.item_materials.mat_index),
                counts = vcopy(arena.equipment.item_counts)}
    end
    return S
end

-- put it all back, each step on its own (one failing never skips the rest);
-- the screens the clicks pushed over the map screen dismissed. The errors
-- of steps that failed, or nil.
local function restore_state(S, scr)
    local errs = {}
    local function step(name, f)
        local ok, e = pcall(f)
        if not ok then table.insert(errs, name .. ': ' .. short(e, 60)) end
    end
    local g = df.global
    local function mi() return g.game.main_interface end
    local function arena() return g.world.arena end
    step('arena_unit', function()
        local au = mi().arena_unit
        au.open, au.editing_filter = false, S.au_filter or false
        au.race, au.caste, au.interaction = S.au_race, S.au_caste, S.au_interaction
        if S.au_context ~= nil then au.context = S.au_context end
    end)
    step('bottom', function() mi().bottom_mode_selected = -1 end)
    step('sheets', function() if S.sheets == false then mi().view_sheets.open = false end end)
    step('lists', function()
        local a = arena()
        vset(a.race, S.race); vset(a.caste, S.caste); vset(a.creature_cnt, S.cnt)
        a.last_race, a.last_caste, a.interaction = S.last_race, S.last_caste, S.interaction
    end)
    if S.eq then
        step('equipment', function()
            local e = arena().equipment
            vset(e.item_types, S.eq.types); vset(e.item_subtypes, S.eq.subtypes)
            vset(e.item_materials.mat_type, S.eq.mt); vset(e.item_materials.mat_index, S.eq.mi)
            vset(e.item_counts, S.eq.counts)
        end)
    end
    step('gametype', function() g.gametype = S.gametype end)
    step('gamemode', function() g.gamemode = S.gamemode end)
    step('mouse', function()
        local gps = g.gps
        gps.mouse_x, gps.mouse_y = S.mouse[1], S.mouse[2]
        if S.precise then gps.precise_mouse_x, gps.precise_mouse_y = S.precise[1], S.precise[2] end
    end)
    step('window', function() g.window_x, g.window_y, g.window_z = S.window[1], S.window[2], S.window[3] end)
    step('pause', function() g.pause_state = S.pause end)
    step('screens', function()
        for _ = 1, 4 do
            local top = dfhack.gui.getDFViewscreen(true)
            if not top or df.viewscreen_dwarfmodest:is_instance(top) or dfhack.screen.isDismissed(top) then break end
            dfhack.screen.dismiss(top)
        end
    end)
    return #errs > 0 and table.concat(errs, '; ') or nil
end

-- the clicks, with the arena state already saved (any error: the caller restores)
local function arena_clicks(o, scr, rid, castes, eq_rows, tiles, out)
    local g, mi, arena = df.global, df.global.game.main_interface, df.global.world.arena
    local au = mi.arena_unit
    local gui = require('gui')
    pcall(dfhack.gui.revealInDwarfmodeMap, xyz2pos(o.pos.x, o.pos.y, o.pos.z), true)
    g.gamemode, g.gametype = df.game_mode.DWARF, df.game_type.DWARF_ARENA
    -- world.arena: only this race (gui/sandbox's init_arena, cut to one creature)
    arena.race:resize(0); arena.caste:resize(0); arena.creature_cnt:resize(0)
    for _, c in ipairs(castes) do arena.race:insert('#', rid); arena.caste:insert('#', c) end
    arena.creature_cnt:insert('#', 0)
    arena.last_race, arena.last_caste, arena.interaction = -1, -1, -1
    if eq_rows then
        local ok, e = pcall(function()
            local q = arena.equipment
            q.item_types:resize(0); q.item_subtypes:resize(0); q.item_counts:resize(0)
            q.item_materials.mat_type:resize(0); q.item_materials.mat_index:resize(0)
            for _, r in ipairs(eq_rows) do
                q.item_types:insert('#', r[1]); q.item_subtypes:insert('#', r[2])
                q.item_materials.mat_type:insert('#', r[3]); q.item_materials.mat_index:insert('#', r[4])
                q.item_counts:insert('#', 1)
            end
        end)
        if not ok then
            out.equip_error = 'arena equipment: ' .. short(e)
            pcall(function()
                local q = arena.equipment
                q.item_types:resize(0); q.item_subtypes:resize(0); q.item_counts:resize(0)
                q.item_materials.mat_type:resize(0); q.item_materials.mat_index:resize(0)
            end)
        end
    end
    -- the creature window, opened as gui/sandbox opens it
    local function open()
        au.open, au.editing_filter = false, false
        mi.bottom_mode_selected = -1
        au.race, au.caste, au.interaction = 0, 0, -1
        au.races_filtered:resize(0); au.races_all:resize(0); au.castes_filtered:resize(0); au.castes_all:resize(0)
        gui.simulateInput(scr, 'ARENA_CREATE_CREATURE')
        if not au.open then error('the arena creature window did not open (' .. arena_words(au) .. ')') end
        au.editing_filter = false
        local ri = pick_index(au.races_filtered, rid)
        if not ri then error('the arena window lists no creature (' .. arena_words(au) .. ')') end
        -- arena_unit.race: the row of the window's list (gui/sandbox sets 0);
        -- if a click made another race, the race's id is tried once instead
        au.race = out.race_sel == 'id' and rid or ri
        if vlen(au.castes_filtered) == 0 then error('the arena window lists no caste (' .. arena_words(au) .. ')') end
    end
    out.race_sel = 'row'
    open()
    local sel = au.race
    local context = try(function() return au.context end)
    local points = click_points(o.pos)
    if #points == 0 then error('no map tile to click in the screen\'s middle (view at the spot)') end
    out.clicks = 0
    for i = 1, o.count do
        if not au.open then open(); sel = au.race end
        local nc = vlen(au.castes_filtered)
        if nc == 0 then error('the arena window lists no caste (' .. arena_words(au) .. ')') end
        au.caste = (o.caste == nil and nc > 1) and math.random(0, nc - 1) or 0
        local p = points[(i - 1) % #points + 1]
        local next0 = g.unit_next_id
        set_mouse(p.sx, p.sy)
        gui.simulateInput(scr, '_MOUSE_L')
        out.clicks = out.clicks + 1
        local made = made_since(next0, nil)
        if #made == 0 then
            if i == 1 then
                error(('the click placed no unit (screen %d,%d = map %d,%d,%d; %s)')
                      :format(p.sx, p.sy, p.x, p.y, p.z, arena_words(au)))
            end
            out.stopped = 'click ' .. i .. ' placed no unit'
            break
        end
        local t = tiles[(i - 1) % #tiles + 1]
        for _, u in ipairs(made) do
            table.insert(out.units, u)
            if u.race == rid and (u.pos.x ~= t.x or u.pos.y ~= t.y or u.pos.z ~= t.z) then
                pcall(dfhack.units.teleport, u, xyz2pos(t.x, t.y, t.z))
            end
        end
        -- a click that changed the window (it hit the window, not the map): no more
        if au.race ~= sel then out.stopped = 'the window\'s race changed (' .. tostring(au.race) .. ')' break end
        if context ~= nil and try(function() return au.context end) ~= context then out.stopped = 'the window changed' break end
        if made[1].race ~= rid then
            if out.race_sel == 'id' or i == o.count then out.stopped = 'a unit of another race' break end
            out.race_sel = 'id'                -- arena_unit.race the race's id, not the row: once
            sel = rid
            au.race = rid
        end
    end
end

local function by_arena(o)
    if not dfhack.isMapLoaded() then return nil, 'no map loaded' end
    if not df.game_type.DWARF_ARENA or not df.global.world.arena or not df.global.game.main_interface.arena_unit then
        return nil, 'this DF has no arena spawner'
    end
    if df.global.gametype == df.game_type.DWARF_ARENA then return nil, 'the arena is open already (gui/sandbox?)' end
    if df.global.game.main_interface.arena_unit.open then return nil, 'the arena creature window is open' end
    local scr = dfhack.gui.getDFViewscreen(true)
    if not scr or not df.viewscreen_dwarfmodest:is_instance(scr) then return nil, 'the map screen is not on top' end
    local rid, castes = race_castes(o.race, o.caste)
    if not rid then return nil, castes end
    local tiles = spawn_tiles(o.pos, o.spread)
    if #tiles == 0 then return nil, 'no tile round the spot a unit can stand on' end
    local eq_rows, equip_error
    if type(o.equip) == 'table' and #o.equip > 0 then
        local ok, r = pcall(equip_rows, o.equip)
        if ok then eq_rows = r else equip_error = short(r) end
    end
    local okS, S = pcall(save_state, eq_rows ~= nil)
    if not okS then return nil, 'the arena state unreadable: ' .. short(S) end
    local out = {units = {}, equip_error = equip_error}
    local ok, err = pcall(arena_clicks, o, scr, rid, castes, eq_rows, tiles, out)
    local rerr = restore_state(S, scr)
    -- units of another race (a click on the window's list): sent away
    local units, wrong = {}, 0
    for _, u in ipairs(out.units) do
        if u.race == rid then table.insert(units, u)
        else
            wrong = wrong + 1
            pcall(function() u.animal.vanish_countdown = 2 end)
        end
    end
    local info = {equip_error = out.equip_error, restore_error = rerr, clicks = out.clicks, stopped = out.stopped,
                  wrong_race = wrong > 0 and wrong or nil, race_sel = out.race_sel}
    if #units == 0 then
        local why = not ok and short(err, 200) or (wrong > 0 and ('the arena made ' .. wrong .. ' of another race (sent away)'))
                    or 'no unit made'
        return nil, why .. (rerr and (' [restore: ' .. rerr .. ']') or ''), info
    end
    if not ok then info.error = short(err, 160) end
    -- arena units: no historical name (gui/sandbox's finalize_units); armed?
    local armed = 0
    for _, u in ipairs(units) do
        pcall(function() u.name.has_name = false end)
        pcall(function() u.profession = df.profession.STANDARD end)
        if (try(function() return #u.inventory end) or 0) > 0 then armed = armed + 1 end
    end
    info.equipped = eq_rows ~= nil and armed > 0
    if eq_rows and armed == 0 and not info.equip_error then info.equip_error = 'the arena gave them no equipment' end
    return units, nil, info
end

-- --- the call ------------------------------------------------------------------------------

local function finish(units, o, arena)
    local ids = {}
    local flags = {}
    for _, f in ipairs(o.flags or {}) do flags[f] = true end
    if arena and flags.active_invader then flags.marauder = true end   -- gui/sandbox's hostile sentients
    for _, u in ipairs(units) do
        pcall(function()
            if o.civ_id and o.civ_id >= 0 then u.civ_id = o.civ_id end
            for f in pairs(flags) do u.flags1[f] = true end
        end)
        table.insert(ids, u.id)
    end
    return ids
end

local function spawn(o)
    if type(o) ~= 'table' or o.race == nil or type(o.pos) ~= 'table' then return nil, 'spawn_units: no race or pos', {} end
    o = {race = o.race, caste = o.caste, count = math.max(1, math.min(SPAWN_MAX, tonumber(o.count) or 1)),
         pos = {x = o.pos.x, y = o.pos.y, z = o.pos.z}, spread = math.max(0, tonumber(o.spread) or 0),
         civ_id = o.civ_id, group_id = o.group_id, flags = o.flags, equip = o.equip}
    local units, why, info = by_create_unit(o)
    if units then
        info.route = 'create-unit'
        return finish(units, o, false), nil, info
    end
    local cu_error = why
    local okA
    okA, units, why, info = pcall(by_arena, o)        -- its own restore runs inside; this catches the checks
    if not okA then units, why, info = nil, short(units, 160), {} end
    info = info or {}
    info.cu_error = cu_error
    if not units then
        info.route = 'none'
        return nil, 'create-unit: ' .. tostring(cu_error) .. '; arena: ' .. tostring(why), info
    end
    info.route = 'arena'
    return finish(units, o, true), nil, info
end

function spawn_units(o)
    local ok, ids, why, info = pcall(spawn, o)
    if not ok then return nil, 'spawn_units: ' .. short(ids, 200), {route = 'none'} end
    return ids, why, info
end
