-- Blueprints for the AI overseer's landmarks (the Design track, D0): the
-- format, its checks, its cost, turning it, and its translation into level
-- layouts in the exact shape ai-layouts makes them. Pure functions, no game
-- access. The authority on the format; brain/blueprint.py mirrors
-- check_format and cost (same codes, same order, same words), tested
-- against the same fixtures (tests/test_d0_blueprints.py).
--
-- A blueprint is one object:
--   {v = 1, name, purpose, ground = 'rock' | 'surface', ['for'],
--    levels = {{grid = {'##@##', '#...#', ...}}, ...},
--    legend = {a = 'Statue', ...}, zone = {kind, level},
--    finish = {smooth = 0-3, engrave = 'none' | 'halls' | 'all'}, materials}
-- Rows run north to south; level 1 is the join level and the others run
-- down from it (rock) or up (surface). A blueprint's positions describe its
-- own shape only: they are never map coordinates. A reason's position is on
-- the drawing as it was given: level (from 1), x the column, y the row
-- (both from 0).
--
-- The alphabet, rock:  _ outside (left alone)  # rock kept  . dug floor
--   , dug floor smoothed and engraved  @ the join (dug floor; exactly one,
--   in row 0 of level 1)  < > X up, down, up/down stair  ^ a ramp up to the
--   level above  + a door  a-z a legend item standing on dug floor.
-- Surface:  _ outside (open air above level 1)  . ground left walkable (on
--   level 1) or the walkable top of a wall below (above it)  @ the join
--   W wall  F floor  R ramp  U D I up, down, up/down stair  O fortification
--   + a door  a-z a legend item (above level 1, a door or an item stands on
--   a floor built for it, 'Cf', unless a wall below gives one).
-- The format's checks don't see the map: rock levels are checked by the
-- bridge's site checks, surface tiles by keep_tile and the walk test.
--@ module = true

local layouts = reqscript('ai-layouts')

BP_LIMITS = {w = 31, h = 31, levels = 5, dug = 700, built = 400, items = 40, statues = 16, doors = 8,
             stairs = 4, legend = 12, cost_max = 2500}
ALPHABET = {rock = '_#.,@<>X^+', surface = '_.@WFRUDIO+'}
MAX_REASONS = 24          -- check_format's list stops here (the bridge sends 8)

-- The legend's furniture: the Quickfort build keys ai-layouts uses for them,
-- and the building type its furniture counts use (Chest is a Box there).
FURNITURE = {Statue = 's', Table = 't', Chair = 'c', Bed = 'b', Coffin = 'n', Cabinet = 'f', Chest = 'h',
             Bookcase = '~c', ArmorStand = 'a', WeaponRack = 'r'}
FURNITURE_TYPE = {Chest = 'Box', ArmorStand = 'Armorstand', WeaponRack = 'Weaponrack'}
BLOCKING = {Statue = true}  -- an item no one walks through

-- Every legend name: the furniture, the workshops (ai-layouts.WORKSHOPS,
-- placed by their centre tile, 3x3 of plain floor) and 'pile:<type>'
-- (ai-layouts.STOCKPILES: a stockpile on that tile; adjacent tiles of one
-- type make one pile). ITEMS: name -> Quickfort key; ITEM_KIND: name ->
-- 'furniture' | 'workshop' | 'pile'.
ITEMS, ITEM_KIND = {}, {}
for k, v in pairs(FURNITURE) do ITEMS[k], ITEM_KIND[k] = v, 'furniture' end
for k, v in pairs(layouts.WORKSHOPS) do ITEMS[k], ITEM_KIND[k] = v, 'workshop' end
for k, v in pairs(layouts.STOCKPILES) do ITEMS['pile:' .. k], ITEM_KIND['pile:' .. k] = v, 'pile' end

-- The zone over one level's floor, as ai-layouts writes them ('' = none).
-- A tomb is one 1x1 tomb zone on each coffin, as ai-layouts.tombs does.
ZONES = {temple = 'm{location=temple}', tomb = 'T{citizens=true}', dining = 'h', meeting = 'm',
         library = 'm{location=library}', none = ''}
LANDMARK_KINDS = {descent = true, god_hall = true, ziggurat = true, chronicle_hall = true, great_hall = true,
                  tower = true, necropolis = true, gate_hall = true, garden_court = true}
ENGRAVE = {none = true, halls = true, all = true}

-- Construction keys on the surface (Quickfort build phase).
CONSTRUCT = {W = 'Cw', F = 'Cf', R = 'Cr', U = 'Cu', D = 'Cd', I = 'Cx', O = 'CF'}
-- Dig keys in rock: stairs and ramps (every other dug tile is 'd').
DIG_KEY = {['<'] = 'u', ['>'] = 'j', X = 'i', ['^'] = 'r'}

local ROCK_DUG = {['.'] = true, [','] = true, ['@'] = true, ['<'] = true, ['>'] = true, X = true,
                  ['^'] = true, ['+'] = true}
local ROCK_WALK = ROCK_DUG
local SURF_WALK = {['.'] = true, ['@'] = true, F = true, R = true, U = true, D = true, I = true, ['+'] = true}
local SURF_BUILT = {W = true, F = true, R = true, U = true, D = true, I = true, O = true}
local SURF_UNDER = {W = true, F = true, R = true, U = true, D = true, I = true}   -- what an upper tile may stand on
local STAIR = {['<'] = true, ['>'] = true, X = true, U = true, D = true, I = true}

local function is_letter(ch) return ch ~= nil and ch:match('^%l$') ~= nil end

-- A door or an item above the surface's first level stands on a floor
-- built for it ('Cf', counted as built), unless a wall below gives one.
local function needs_floor(i, ch, below)
    return i > 1 and (ch == '+' or is_letter(ch)) and below ~= nil and below ~= 'W' and below ~= '_'
end

local function int(v)
    if math.type(v) == 'integer' then return v end
    if math.type(v) == 'float' and v == math.floor(v) then return math.tointeger(v) end
    return nil
end

-- An object (a JSON {}): a table with string keys only. A list: a table
-- whose keys are exactly 1..n, n >= 1.
local function is_object(v)
    if type(v) ~= 'table' then return false end
    for k in pairs(v) do if type(k) ~= 'string' then return false end end
    return true
end

local function is_list(v)
    if type(v) ~= 'table' then return false end
    local n, count = #v, 0
    if n < 1 then return false end
    for k in pairs(v) do
        if math.type(k) ~= 'integer' or k < 1 or k > n then return false end
        count = count + 1
    end
    return count == n
end

local function shown(s)
    if type(s) ~= 'string' then return 'a name' end
    if #s <= 20 and s:match('^[%w_:]+$') then return "'" .. s .. "'" end
    return 'a name'
end

local function char_words(ch)
    local b = ch:byte()
    if b < 33 or b > 126 then return ('character code %d'):format(b) end
    return "'" .. ch .. "'"
end

local function where(level, x, y)
    if level and x and y then return ('L%d x%d y%d: '):format(level, x, y) end
    if level and y then return ('L%d y%d: '):format(level, y) end
    if level then return ('L%d: '):format(level) end
    return ''
end

-- The grids as lists of strings, and a cell reader (nil outside the drawing).
local function grids_of(bp)
    local g = {}
    for i, lv in ipairs(bp.levels) do g[i] = lv.grid end
    return g
end

local function cell(g, i, x, y)
    local rows = g[i]
    if not rows then return nil end
    local row = rows[y + 1]
    if not row or x < 0 or x >= #row then return nil end
    return row:sub(x + 1, x + 1)
end

local function legend_of(bp)
    return is_object(bp.legend) and bp.legend or {}
end

local function item_of(legend, ch)
    local v = legend[ch]
    if type(v) == 'string' and ITEMS[v] then return v end
    return nil
end

local N8 = {{-1, -1}, {0, -1}, {1, -1}, {-1, 0}, {1, 0}, {-1, 1}, {0, 1}, {1, 1}}

-- The cost of a (well-formed) drawing: dug and built tiles, items (furniture
-- and workshops; piles are free), statues, doors, stair columns, and jobs =
-- dug + 4 x built + 10 x items.
function cost(bp)
    local out = {dug = 0, built = 0, items = 0, statues = 0, doors = 0, stairs = 0, jobs = 0}
    if type(bp) ~= 'table' or type(bp.levels) ~= 'table' then return out end
    local surface = bp.ground == 'surface'
    local legend = legend_of(bp)
    local columns = {}
    local function below_of(i, y, x)
        local lv = bp.levels[i - 1]
        local row = type(lv) == 'table' and type(lv.grid) == 'table' and lv.grid[y] or nil
        return type(row) == 'string' and row:sub(x, x) or nil
    end
    for lv_i, lv in ipairs(bp.levels) do
        for y, row in ipairs(type(lv) == 'table' and type(lv.grid) == 'table' and lv.grid or {}) do
            if type(row) == 'string' then
                for x = 1, #row do
                    local ch = row:sub(x, x)
                    if surface then
                        if SURF_BUILT[ch] or needs_floor(lv_i, ch, below_of(lv_i, y, x)) then
                            out.built = out.built + 1
                        end
                    elseif ROCK_DUG[ch] or is_letter(ch) then
                        out.dug = out.dug + 1
                    end
                    if ch == '+' then out.doors = out.doors + 1 end
                    if STAIR[ch] and (surface == (ch == 'U' or ch == 'D' or ch == 'I')) then
                        columns[(y - 1) * 64 + (x - 1)] = true
                    end
                    if is_letter(ch) then
                        local name = item_of(legend, ch)
                        if name and ITEM_KIND[name] ~= 'pile' then out.items = out.items + 1 end
                        if name == 'Statue' then out.statues = out.statues + 1 end
                    end
                end
            end
        end
    end
    for _ in pairs(columns) do out.stairs = out.stairs + 1 end
    out.jobs = out.dug + 4 * out.built + 10 * out.items
    return out
end

-- Every check of the format, in order: FORMAT SIZE SYMBOL (each stops the
-- check when it fails), then LEGEND JOIN STAIRS REACH SUPPORT LIMIT.
-- Returns ok, reasons (a list of {code, level, x, y, words}, MAX_REASONS at
-- most, in the order found).
function check_format(bp)
    local reasons = {}
    local function why(code, level, x, y, words)
        if #reasons < MAX_REASONS then
            table.insert(reasons, {code = code, level = level, x = x, y = y, words = where(level, x, y) .. words})
        end
    end
    local function done() return #reasons == 0, reasons end

    -- FORMAT: the object's fields
    if not is_object(bp) then
        why('FORMAT', nil, nil, nil, 'a blueprint is one object')
        return done()
    end
    if bp.v ~= nil and int(bp.v) ~= 1 then why('FORMAT', nil, nil, nil, 'v must be 1') end
    if bp.ground ~= 'rock' and bp.ground ~= 'surface' then
        why('FORMAT', nil, nil, nil, "ground must be 'rock' or 'surface'")
    end
    local nlev = nil
    if not is_list(bp.levels) then
        why('FORMAT', nil, nil, nil, 'levels must be a list of 1 to 5 levels')
    else
        nlev = #bp.levels
        for i, lv in ipairs(bp.levels) do
            if not is_object(lv) or not is_list(lv.grid) then
                why('FORMAT', i, nil, nil, 'a level is {"grid": [rows]}')
            else
                for y, row in ipairs(lv.grid) do
                    if type(row) ~= 'string' then why('FORMAT', i, nil, y - 1, 'a row must be a string') end
                end
            end
        end
    end
    if bp.legend ~= nil and not is_object(bp.legend) then
        why('FORMAT', nil, nil, nil, 'legend must be an object')
    end
    if bp.zone ~= nil then
        if not is_object(bp.zone) or type(bp.zone.kind) ~= 'string' or ZONES[bp.zone.kind] == nil then
            why('FORMAT', nil, nil, nil, 'zone must be {"kind": temple, tomb, dining, meeting, library or none, "level"}')
        elseif bp.zone.level ~= nil then
            local zl = int(bp.zone.level)
            if not zl or zl < 1 or (nlev and zl > nlev) then
                why('FORMAT', nil, nil, nil, 'zone level must be one of the levels')
            end
        end
    end
    if bp.finish ~= nil then
        local f = bp.finish
        if not is_object(f) then
            why('FORMAT', nil, nil, nil, 'finish must be an object')
        else
            local s = 0
            if f.smooth ~= nil then s = int(f.smooth) end
            if not s or s < 0 or s > 3 then why('FORMAT', nil, nil, nil, 'finish smooth must be 0 to 3') end
            if f.engrave ~= nil and not ENGRAVE[f.engrave] then
                why('FORMAT', nil, nil, nil, "finish engrave must be 'none', 'halls' or 'all'")
            end
        end
    end
    if bp.materials ~= nil and not is_object(bp.materials) then
        why('FORMAT', nil, nil, nil, 'materials must be an object')
    end
    if bp.purpose ~= nil and not LANDMARK_KINDS[bp.purpose] then
        why('FORMAT', nil, nil, nil, 'purpose must be a landmark kind')
    end
    if bp.name ~= nil and (type(bp.name) ~= 'string' or #bp.name > 40 or not bp.name:match("^[A-Za-z' ]+$")) then
        why('FORMAT', nil, nil, nil, 'name: letters, spaces and apostrophes, up to 40')
    end
    if bp['for'] ~= nil and (type(bp['for']) ~= 'string' or #bp['for'] > 60) then
        why('FORMAT', nil, nil, nil, "'for' must be a name, up to 60 characters")
    end
    if #reasons > 0 then return done() end

    -- SIZE: up to 5 levels of one w x h (up to 31 x 31)
    local g = grids_of(bp)
    local n = #g
    if n > BP_LIMITS.levels then
        why('SIZE', nil, nil, nil, ('%d levels; at most %d'):format(n, BP_LIMITS.levels))
    end
    local h, w = #g[1], #g[1][1]
    if w < 1 or w > BP_LIMITS.w then
        why('SIZE', 1, nil, nil, ('%d tiles wide; 1 to %d'):format(w, BP_LIMITS.w))
    end
    if h > BP_LIMITS.h then
        why('SIZE', 1, nil, nil, ('%d rows; at most %d'):format(h, BP_LIMITS.h))
    end
    for i = 1, n do
        if #g[i] ~= h then
            why('SIZE', i, nil, nil, ('%d rows; level 1 has %d'):format(#g[i], h))
        end
        for y, row in ipairs(g[i]) do
            if #row ~= w then
                why('SIZE', i, nil, y - 1, ('%d tiles wide; row 0 of level 1 has %d'):format(#row, w))
            end
        end
    end
    if #reasons > 0 then return done() end

    -- SYMBOL: the ground's alphabet, and a-z for the legend
    local ground = bp.ground
    local alphabet = ALPHABET[ground]
    for i = 1, n do
        for y = 0, h - 1 do
            local row = g[i][y + 1]
            for x = 0, w - 1 do
                local ch = row:sub(x + 1, x + 1)
                if not is_letter(ch) and not alphabet:find(ch, 1, true) then
                    why('SYMBOL', i, x, y, ('%s is not in the %s alphabet'):format(char_words(ch), ground))
                end
            end
        end
    end
    if #reasons > 0 then return done() end

    local surface = ground == 'surface'
    local legend = legend_of(bp)

    -- LEGEND: up to 12 letters, each a known item; every letter drawn is in
    -- it; a workshop has 3x3 of plain floor, its own
    local keys = {}
    for k in pairs(legend) do table.insert(keys, k) end
    table.sort(keys)
    if #keys > BP_LIMITS.legend then
        why('LEGEND', nil, nil, nil, ('%d legend entries; at most %d'):format(#keys, BP_LIMITS.legend))
    end
    for _, k in ipairs(keys) do
        if not is_letter(k) then
            why('LEGEND', nil, nil, nil, ('legend key %s must be one letter, a to z'):format(shown(k)))
        elseif not item_of(legend, k) then
            why('LEGEND', nil, nil, nil, ("legend '%s': %s is not an item"):format(k, shown(legend[k])))
        end
    end
    local missing, claimed = {}, {}
    local floor = surface and {['.'] = true, F = true} or {['.'] = true, [','] = true}
    for i = 1, n do
        for y = 0, h - 1 do
            for x = 0, w - 1 do
                local ch = cell(g, i, x, y)
                if is_letter(ch) then
                    local name = item_of(legend, ch)
                    if legend[ch] == nil and not missing[ch] then
                        missing[ch] = true
                        why('LEGEND', i, x, y, ("'%s' is not in the legend"):format(ch))
                    elseif name and ITEM_KIND[name] == 'workshop' then
                        local ok = not claimed[(i * 64 + y) * 64 + x]
                        for _, d in ipairs(N8) do
                            local nx, ny = x + d[1], y + d[2]
                            local c = cell(g, i, nx, ny)
                            if not (c and floor[c]) or claimed[(i * 64 + ny) * 64 + nx] then ok = false end
                        end
                        if ok then
                            for dy = -1, 1 do
                                for dx = -1, 1 do claimed[(i * 64 + y + dy) * 64 + x + dx] = true end
                            end
                        else
                            why('LEGEND', i, x, y, ('a workshop (%s) needs the 8 tiles around it as plain floor, '
                                                    .. 'not shared'):format(name))
                        end
                    end
                end
            end
        end
    end

    -- JOIN: exactly one '@', in row 0 of level 1
    local joins, jl, jx, jy = 0, nil, nil, nil
    for i = 1, n do
        for y = 0, h - 1 do
            for x = 0, w - 1 do
                if cell(g, i, x, y) == '@' then
                    joins = joins + 1
                    if joins == 1 then
                        jl, jx, jy = i, x, y
                    else
                        why('JOIN', i, x, y, "a second '@'; the join is one tile")
                    end
                end
            end
        end
    end
    if joins == 0 then
        why('JOIN', nil, nil, nil, "no '@' (the join, in row 0 of level 1)")
    elseif jl ~= 1 or jy ~= 0 then
        why('JOIN', jl, jx, jy, "'@' must be in row 0 of level 1")
    end
    local join_ok = joins == 1 and jl == 1 and jy == 0

    -- STAIRS: every stair and ramp leads to its partner
    for i = 1, n do
        for y = 0, h - 1 do
            for x = 0, w - 1 do
                local ch = cell(g, i, x, y)
                local up = (surface and i < n and cell(g, i + 1, x, y)) or (not surface and i > 1 and cell(g, i - 1, x, y)) or nil
                local down = (surface and i > 1 and cell(g, i - 1, x, y)) or (not surface and i < n and cell(g, i + 1, x, y)) or nil
                local bad = nil
                if not surface then
                    if ch == '>' then
                        if not down then bad = "a down stair on the lowest level"
                        elseif down ~= '<' and down ~= 'X' then bad = "a down stair needs '<' or 'X' below it" end
                    elseif ch == '<' then
                        if not up then bad = "an up stair on level 1 leads out of the blueprint"
                        elseif up ~= '>' and up ~= 'X' then bad = "an up stair needs '>' or 'X' above it" end
                    elseif ch == 'X' then
                        if not up then bad = "'X' on level 1 leads out of the blueprint; use '>'"
                        elseif not down then bad = "'X' on the lowest level; use '<'"
                        elseif up ~= '>' and up ~= 'X' then bad = "'X' needs '>' or 'X' above it"
                        elseif down ~= '<' and down ~= 'X' then bad = "'X' needs '<' or 'X' below it" end
                    elseif ch == '^' then
                        if not up then bad = "a ramp on level 1 leads out of the blueprint"
                        elseif up ~= '.' and up ~= ',' then bad = "a ramp needs dug floor ('.' or ',') above it" end
                    end
                else
                    if ch == 'U' then
                        if not up then bad = "an up stair on the top level"
                        elseif up ~= 'D' and up ~= 'I' then bad = "an up stair needs 'D' or 'I' above it" end
                    elseif ch == 'D' then
                        if not down then bad = "a down stair on level 1 (the ground)"
                        elseif down ~= 'U' and down ~= 'I' then bad = "a down stair needs 'U' or 'I' below it" end
                    elseif ch == 'I' then
                        if not down then bad = "'I' on level 1 (the ground); use 'U'"
                        elseif not up then bad = "'I' on the top level; use 'D'"
                        elseif up ~= 'D' and up ~= 'I' then bad = "'I' needs 'D' or 'I' above it"
                        elseif down ~= 'U' and down ~= 'I' then bad = "'I' needs 'U' or 'I' below it" end
                    elseif ch == 'R' then
                        if not up then bad = "a ramp on the top level leads out of the blueprint"
                        elseif up ~= '_' then bad = "a ramp needs open air ('_') above it" end
                    end
                end
                if bad then why('STAIRS', i, x, y, bad) end
            end
        end
    end

    -- REACH: every dug (rock) or walkable (surface) tile reached from '@'
    if join_ok then
        local walkset = surface and SURF_WALK or ROCK_WALK
        local function walkable(ch)
            if ch == nil then return false end
            if walkset[ch] then return true end
            if is_letter(ch) then return not BLOCKING[item_of(legend, ch) or ''] end
            return false
        end
        local function key(i, x, y) return (i * 64 + y) * 64 + x end
        local up_stairs = surface and {U = true, I = true} or {['<'] = true, X = true}
        local down_stairs = surface and {D = true, I = true} or {['>'] = true, X = true}
        local ramp = surface and 'R' or '^'
        local seen, queue, head = {[key(1, jx, jy)] = true}, {{1, jx, jy}}, 1
        local function go(i, x, y)
            local k = key(i, x, y)
            if not seen[k] and walkable(cell(g, i, x, y)) then
                seen[k] = true
                table.insert(queue, {i, x, y})
            end
        end
        while head <= #queue do
            local i, x, y = table.unpack(queue[head])
            head = head + 1
            local ch = cell(g, i, x, y)
            for _, d in ipairs(N8) do go(i, x + d[1], y + d[2]) end
            -- the level above (rock: i - 1; surface: i + 1) and below
            local ui = surface and i + 1 or i - 1
            local di = surface and i - 1 or i + 1
            local upc, dnc = cell(g, ui, x, y), cell(g, di, x, y)
            if up_stairs[ch] and upc and down_stairs[upc] then go(ui, x, y) end
            if down_stairs[ch] and dnc and up_stairs[dnc] then go(di, x, y) end
            if ch == ramp then
                for _, d in ipairs(N8) do go(ui, x + d[1], y + d[2]) end
            end
            for _, d in ipairs(N8) do
                if cell(g, di, x + d[1], y + d[2]) == ramp then go(di, x + d[1], y + d[2]) end
            end
        end
        for i = 1, n do
            local any = false
            for y = 0, h - 1 do
                for x = 0, w - 1 do
                    local ch = cell(g, i, x, y)
                    if surface and ch ~= '_' then any = true end
                    if not surface and (ROCK_DUG[ch] or is_letter(ch)) then any = true end
                end
            end
            if not any then
                why('REACH', i, nil, nil, 'nothing drawn on this level')
            else
                for y = 0, h - 1 do
                    for x = 0, w - 1 do
                        local ch = cell(g, i, x, y)
                        local must = walkset[ch] or is_letter(ch)
                        if must and not seen[key(i, x, y)] then
                            local near = false
                            if is_letter(ch) and not walkable(ch) then
                                for _, d in ipairs(N8) do
                                    if seen[key(i, x + d[1], y + d[2])] then near = true end
                                end
                            end
                            if not near then why('REACH', i, x, y, "not reached from '@'") end
                        end
                    end
                end
            end
        end
    end

    -- SUPPORT (surface): nothing above level 1 stands over open air ('_');
    -- '.' up there is the walkable top of a wall below; a ramp stands on a
    -- wall's top; a floor isn't built where a wall's top is one already
    if surface then
        for i = 2, n do
            for y = 0, h - 1 do
                for x = 0, w - 1 do
                    local ch, below = cell(g, i, x, y), cell(g, i - 1, x, y)
                    if ch ~= '_' then
                        if below == '_' then
                            why('SUPPORT', i, x, y, "nothing to stand on: open air ('_') below")
                        elseif (ch == '.' or ch == 'R') and below ~= 'W' then
                            why('SUPPORT', i, x, y, ("%s above the ground needs a wall ('W') below; use 'F' "
                                                     .. 'for a floor'):format(char_words(ch)))
                        elseif ch == 'F' and below == 'W' then
                            why('SUPPORT', i, x, y, "the wall below already makes a floor here; use '.'")
                        end
                    end
                end
            end
        end
    end

    -- LIMIT: the tile, item and job caps
    local c = cost(bp)
    local L = BP_LIMITS
    if c.dug > L.dug then why('LIMIT', nil, nil, nil, ('%d dug tiles; at most %d'):format(c.dug, L.dug)) end
    if c.built > L.built then why('LIMIT', nil, nil, nil, ('%d built tiles; at most %d'):format(c.built, L.built)) end
    if c.items > L.items then why('LIMIT', nil, nil, nil, ('%d items; at most %d'):format(c.items, L.items)) end
    if c.statues > L.statues then
        why('LIMIT', nil, nil, nil, ('%d statues; at most %d'):format(c.statues, L.statues))
    end
    if c.doors > L.doors then why('LIMIT', nil, nil, nil, ('%d doors; at most %d'):format(c.doors, L.doors)) end
    if c.stairs > L.stairs then
        why('LIMIT', nil, nil, nil, ('%d stair columns; at most %d'):format(c.stairs, L.stairs))
    end
    if c.jobs > L.cost_max then
        why('LIMIT', nil, nil, nil, ('%d jobs; at most %d'):format(c.jobs, L.cost_max))
    end
    return done()
end

-- q quarter turns clockwise (0-3), a real rotation of every level's grid:
-- row 0 (north) faces east after 1, south after 2, west after 3. The
-- bridge turns a drawing so row 0 faces the corridor that joins it.
-- (ai-layouts.orient_layout's four turns are mirrors and transposes, with
-- no half turn, so they can't face row 0 south.)
local function rotate_grid(rows)
    local h, w = #rows, #rows[1]
    local out = {}
    for r = 0, w - 1 do
        local chars = {}
        for c = 0, h - 1 do
            local src = rows[h - c]
            chars[c + 1] = src:sub(r + 1, r + 1)
        end
        out[r + 1] = table.concat(chars)
    end
    return out
end

function rotate(bp, q)
    q = (int(q) or 0) % 4
    local out = {}
    for k, v in pairs(bp) do out[k] = v end
    local levels = {}
    for i, lv in ipairs(bp.levels) do
        local copy = {}
        for k, v in pairs(lv) do copy[k] = v end
        local grid = lv.grid
        for _ = 1, q do grid = rotate_grid(grid) end
        copy.grid = grid
        levels[i] = copy
    end
    out.levels = levels
    return out
end

-- Greedy rectangles: each unclaimed cell with a key grows east as far as
-- the key runs, then south while the whole run matches. keys[r][c] (0-based
-- r, c) is a string or nil; (c0, r0) is the drawing's (0, 0).
local function merge(keys, h, w, c0, r0)
    local used, cells = {}, {}
    for r = 0, h - 1 do
        for c = 0, w - 1 do
            local k = keys[r] and keys[r][c]
            if k and not used[r * 64 + c] then
                local cw = 1
                while c + cw < w and keys[r][c + cw] == k and not used[r * 64 + c + cw] do cw = cw + 1 end
                local ch = 1
                while r + ch < h do
                    local row = keys[r + ch]
                    local ok = row ~= nil
                    for dc = 0, cw - 1 do
                        if ok and (row[c + dc] ~= k or used[(r + ch) * 64 + c + dc]) then ok = false end
                    end
                    if not ok then break end
                    ch = ch + 1
                end
                for dr = 0, ch - 1 do
                    for dc = 0, cw - 1 do used[(r + dr) * 64 + c + dc] = true end
                end
                table.insert(cells, {x = c - c0, y = r - r0,
                                     text = (cw == 1 and ch == 1) and k or ('%s(%dx%d)'):format(k, cw, ch)})
            end
        end
    end
    return cells
end

local function mark(set, x, y)
    set[x] = set[x] or {}
    set[x][y] = true
end

local function bounds_of(set)
    local x1, y1, x2, y2 = math.huge, math.huge, -math.huge, -math.huge
    for x, col in pairs(set) do
        for y in pairs(col) do
            x1, x2 = math.min(x1, x), math.max(x2, x)
            y1, y2 = math.min(y1, y), math.max(y2, y)
        end
    end
    if x1 == math.huge then return {x1 = 0, y1 = 0, x2 = 0, y2 = 0} end
    return {x1 = x1, y1 = y1, x2 = x2, y2 = y2}
end

local function zone_text(bp, kind)
    local z = ZONES[kind]
    if kind == 'meeting' and type(bp.name) == 'string' and #bp.name <= 40 and bp.name:match("^[A-Za-z' ]+$") then
        return ('m{name="%s"}'):format(bp.name)
    end
    return z
end

-- The drawing as Quickfort layouts, one per level, after q quarter turns
-- (rotate). Returns {levels = {L1..Ln}, dz = {0, -1, ...} (rock) or
-- {0, 1, ...} (surface), quarter = q, cost = cost(bp)}, or nil and the
-- reasons when check_format refuses it. Each L is shaped as ai-layouts
-- makes one (kind = 'landmark'), with level 1's '@' at (0, 0) and every
-- level in the same frame (so the stairs line up):
--   dig        rock: 'd' / 'd(WxH)' over the floors (greedy rectangles), one
--              'u' 'j' 'i' 'r' cell per stair and ramp tile
--   build      doors 'd', furniture by its key, a workshop at its centre
--   place      stockpiles ('f(3x2)'), one rectangle per run of a pile type
--   zone       the bp.zone over the level's floor (rectangles; contiguous
--              ones make one zone in Quickfort), a tomb on each coffin
--   construct  surface: one 'Cw' 'Cf' 'Cr' 'Cu' 'Cd' 'Cx' 'CF' cell per tile
--   tiles      the dug tiles (rock; empty on the surface)
--   built      the constructed tiles (surface)
--   solid      the tiles nothing walks through once built (surface W and O)
--   footprint  every tile of the drawing that isn't '_'
--   bounds     of the tiles (rock) or the footprint (surface)
--   furniture  counts by building type, as ai-layouts counts them
--   halls      one rectangle round the level's tiles (for engraving)
--   smooth, engrave  rock only: ',' floors always; finish.smooth 1 every
--              plain floor, 2 also the '#' walls touching a dug tile, 3 or
--              engrave 'all' engraves them all; 'halls' engraves the '#'
--              walls touching ',' floors
function to_layouts(bp, q)
    local ok, reasons = check_format(bp)
    if not ok then return nil, reasons end
    q = (int(q) or 0) % 4
    local total = cost(bp)
    local rb = rotate(bp, q)
    local g = grids_of(rb)
    local n, h, w = #g, #g[1], #g[1][1]
    local surface = bp.ground == 'surface'
    local legend = legend_of(bp)
    local r0, c0
    for r = 0, h - 1 do
        local c = g[1][r + 1]:find('@', 1, true)
        if c then r0, c0 = r, c - 1 end
    end
    local zone = is_object(bp.zone) and bp.zone or nil
    local zkind = zone and zone.kind or 'none'
    local zlevel = zone and (int(zone.level) or 1) or 0
    local finish = is_object(bp.finish) and bp.finish or {}
    local smooth_lv = int(finish.smooth) or 0
    local engrave = finish.engrave or 'none'
    local out = {levels = {}, dz = {}, quarter = q, cost = total}
    for i = 1, n do
        out.dz[i] = surface and (i - 1) or -(i - 1)
        local L = {kind = 'landmark', level = i, dig = {}, build = {}, place = {}, zone = {}, construct = {},
                   tiles = {}, built = {}, solid = {}, footprint = {}, furniture = {}, halls = {},
                   smooth = {}, engrave = {}, summary = {}, orient = 0, engrave_all = false,
                   style = {}}
        local digkeys, pilekeys, zonekeys = {}, {}, {}
        local ztext = (i == zlevel) and zone_text(bp, zkind) or ''
        local function furn(t) L.furniture[t] = (L.furniture[t] or 0) + 1 end
        for r = 0, h - 1 do
            digkeys[r], pilekeys[r], zonekeys[r] = {}, {}, {}
            local row = g[i][r + 1]
            for c = 0, w - 1 do
                local ch = row:sub(c + 1, c + 1)
                local x, y = c - c0, r - r0
                if ch ~= '_' then mark(L.footprint, x, y) end
                local name = is_letter(ch) and item_of(legend, ch) or nil
                local floorish
                if surface then
                    floorish = SURF_WALK[ch] or is_letter(ch)
                    local below = i > 1 and g[i - 1][r + 1]:sub(c + 1, c + 1) or nil
                    local key = CONSTRUCT[ch] or (needs_floor(i, ch, below) and 'Cf') or nil
                    if key then
                        table.insert(L.construct, {x = x, y = y, text = key})
                        mark(L.built, x, y)
                        if ch == 'W' or ch == 'O' then mark(L.solid, x, y) end
                    end
                else
                    floorish = ROCK_DUG[ch] or is_letter(ch)
                    if floorish then
                        mark(L.tiles, x, y)
                        if DIG_KEY[ch] then
                            table.insert(L.dig, {x = x, y = y, text = DIG_KEY[ch]})
                        else
                            digkeys[r][c] = 'd'
                        end
                    end
                end
                if ch == '+' then
                    table.insert(L.build, {x = x, y = y, text = 'd'})
                    furn('Door')
                elseif name then
                    local kind = ITEM_KIND[name]
                    if kind == 'pile' then
                        pilekeys[r][c] = ITEMS[name]
                    else
                        table.insert(L.build, {x = x, y = y, text = ITEMS[name]})
                        furn(kind == 'furniture' and (FURNITURE_TYPE[name] or name) or name)
                    end
                end
                if ztext ~= '' and floorish then
                    if zkind == 'tomb' then
                        if name == 'Coffin' then table.insert(L.zone, {x = x, y = y, text = ztext}) end
                    else
                        zonekeys[r][c] = ztext
                    end
                end
            end
        end
        -- the floors first, then the stairs and ramps (each one cell)
        local floors = merge(digkeys, h, w, c0, r0)
        for _, cc in ipairs(L.dig) do table.insert(floors, cc) end
        L.dig = floors
        L.place = merge(pilekeys, h, w, c0, r0)
        if zkind ~= 'tomb' then L.zone = merge(zonekeys, h, w, c0, r0) end
        -- smoothing and engraving (rock)
        if not surface then
            local sm_floor, en_floor, walls = {}, {}, {}
            local seen_wall = {}
            for r = 0, h - 1 do
                local row = g[i][r + 1]
                for c = 0, w - 1 do
                    local ch = row:sub(c + 1, c + 1)
                    local x, y = c - c0, r - r0
                    local plain = ch == '.' or ch == ',' or ch == '@'
                    if plain and (ch == ',' or smooth_lv >= 1 or engrave == 'all') then
                        table.insert(sm_floor, {x = x, y = y, text = 's'})
                    end
                    if plain and (ch == ',' or engrave == 'all') then
                        table.insert(en_floor, {x = x, y = y, text = 'e'})
                    end
                    if ch == '#' then
                        local touches, touches_engraved = false, false
                        for _, d in ipairs(N8) do
                            local nc = cell(g, i, c + d[1], r + d[2])
                            if nc and (ROCK_DUG[nc] or is_letter(nc)) then touches = true end
                            if nc == ',' then touches_engraved = true end
                        end
                        if touches then table.insert(walls, {x = x, y = y, e = touches_engraved}) end
                    end
                end
            end
            for _, cc in ipairs(sm_floor) do table.insert(L.smooth, cc) end
            for _, wl in ipairs(walls) do
                local eng = smooth_lv >= 3 or engrave == 'all' or (engrave == 'halls' and wl.e)
                if smooth_lv >= 2 or eng then table.insert(L.smooth, {x = wl.x, y = wl.y, text = 's'}) end
            end
            for _, cc in ipairs(en_floor) do table.insert(L.engrave, cc) end
            for _, wl in ipairs(walls) do
                local eng = smooth_lv >= 3 or engrave == 'all' or (engrave == 'halls' and wl.e)
                if eng then table.insert(L.engrave, {x = wl.x, y = wl.y, text = 'e'}) end
            end
        end
        L.bounds = bounds_of(surface and L.footprint or L.tiles)
        local b = L.bounds
        L.halls = {{x = b.x1, y = b.y1, w = b.x2 - b.x1 + 1, h = b.y2 - b.y1 + 1}}
        local count = 0
        for _, col in pairs(surface and L.built or L.tiles) do for _ in pairs(col) do count = count + 1 end end
        L.summary = {landmark = bp.name, purpose = bp.purpose, level = i, levels = n,
                     dug = (not surface) and count or 0, built = surface and count or 0}
        out.levels[i] = L
    end
    return out
end
