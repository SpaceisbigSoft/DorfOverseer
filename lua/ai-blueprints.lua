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
--   level above  + a door  a-z a legend item standing on dug floor
--   (E1) * open to the level below: dug, then cut as a channel once the
--   level below is dug, so a hall spans 2+ levels  O a fortification (a
--   rail): dug, the openings cut from it, then built ('CF').
-- (E1) The openings' rules: the tile below a '*' is dug in the drawing (or
--   another '*' over one); every tile beside a '*' is '*', '#', 'O' or '_'
--   (railed, so no one falls); every '*' is reached from an 'O' beside it
--   (the dwarves stand there to cut it); nothing on a level is left hanging
--   over a hole with nothing holding it (the cave-in check).
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
ALPHABET = {rock = '_#.,@<>X^+*O', surface = '_.@WFRUDIO+'}
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
-- (E1) An opening ('*') is cut with this dig key once the level below is dug;
-- a rail ('O') in the rock is built with this key once its openings are cut.
OPEN_KEY = 'h'
RAIL_KEY = 'CF'
-- What may stand beside an opening: another opening, rock, a rail, or the
-- rock outside the drawing.
RAIL_OK = {['*'] = true, ['#'] = true, O = true, _ = true}

local ROCK_WALK = {['.'] = true, [','] = true, ['@'] = true, ['<'] = true, ['>'] = true, X = true,
                   ['^'] = true, ['+'] = true}
local ROCK_DUG = {['*'] = true, O = true}
for k in pairs(ROCK_WALK) do ROCK_DUG[k] = true end
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
    local out = {dug = 0, built = 0, items = 0, statues = 0, doors = 0, stairs = 0, open = 0, jobs = 0}
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
                        if ch == 'O' then out.built = out.built + 1 end
                        if ch == '*' then out.open = out.open + 1 end
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
    out.jobs = out.dug + out.open + 4 * out.built + 10 * out.items
    return out
end

-- (E1) The order a level's openings are cut in: each '*' gets its distance
-- (4 ways, through '*') from an 'O' beside it; the farthest are cut first, so
-- a dwarf always stands on floor beside the tile he cuts, and the floor left
-- stays joined to the rails. Returns {[y * 64 + x] = distance}, the largest
-- distance (0 with no '*'); a '*' no 'O' leads to has none.
local N4 = {{0, -1}, {-1, 0}, {1, 0}, {0, 1}}

local function has_open(rows)
    for _, row in ipairs(rows) do if row:find('*', 1, true) then return true end end
    return false
end

local function open_distances(at, h, w)
    local dist, queue, head, far = {}, {}, 1, 0
    for y = 0, h - 1 do
        for x = 0, w - 1 do
            if at(x, y) == '*' then
                for _, d in ipairs(N4) do
                    if at(x + d[1], y + d[2]) == 'O' and not dist[y * 64 + x] then
                        dist[y * 64 + x] = 1
                        table.insert(queue, {x, y})
                    end
                end
            end
        end
    end
    while head <= #queue do
        local x, y = queue[head][1], queue[head][2]
        head = head + 1
        local dd = dist[y * 64 + x]
        if dd > far then far = dd end
        for _, d in ipairs(N4) do
            local nx, ny = x + d[1], y + d[2]
            if at(nx, ny) == '*' and not dist[ny * 64 + nx] then
                dist[ny * 64 + nx] = dd + 1
                table.insert(queue, {nx, ny})
            end
        end
    end
    return dist, far
end

-- Every check of the format, in order: FORMAT SIZE SYMBOL (each stops the
-- check when it fails), then LEGEND JOIN STAIRS REACH OPEN RAIL SUPPORT LIMIT
-- (OPEN and RAIL, E1: only a drawing with '*' meets them).
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
                        local rail = not surface and ch == 'O'      -- (E1) built from beside it
                        local must = walkset[ch] or is_letter(ch) or rail
                        if must and not seen[key(i, x, y)] then
                            local near = false
                            if (is_letter(ch) and not walkable(ch)) or rail then
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

    -- (E1) OPEN: each '*' over dug floor (or another '*') of the drawing,
    -- and reached from an 'O' beside it (the dwarves cut it from there)
    local any_open = false
    if not surface then
        for i = 1, n do
            if has_open(g[i]) then any_open = true end
        end
    end
    if any_open then
        for i = 1, n do
            for y = 0, h - 1 do
                for x = 0, w - 1 do
                    if cell(g, i, x, y) == '*' then
                        local below = i < n and cell(g, i + 1, x, y) or nil
                        if not below then
                            why('OPEN', i, x, y, "an opening ('*') on the lowest level: no level below it in the drawing")
                        elseif not (below == '*' or ROCK_WALK[below] or is_letter(below)) then
                            why('OPEN', i, x, y, ("an opening ('*') needs the level below dug here, not %s")
                                :format(char_words(below)))
                        end
                    end
                end
            end
            local dist = open_distances(function(x, y) return cell(g, i, x, y) end, h, w)
            local told = {}
            for y = 0, h - 1 do
                for x = 0, w - 1 do
                    if cell(g, i, x, y) == '*' and not dist[y * 64 + x] and not told[y * 64 + x] then
                        why('OPEN', i, x, y, "no rail ('O') leads to this opening: the dwarves cut it standing on an "
                                             .. "'O' beside it")
                        local stack = {{x, y}}
                        told[y * 64 + x] = true
                        while #stack > 0 do
                            local p = table.remove(stack)
                            for _, d in ipairs(N4) do
                                local nx, ny = p[1] + d[1], p[2] + d[2]
                                if cell(g, i, nx, ny) == '*' and not told[ny * 64 + nx] then
                                    told[ny * 64 + nx] = true
                                    table.insert(stack, {nx, ny})
                                end
                            end
                        end
                    end
                end
            end
        end
    end

    -- (E1) RAIL: every tile beside an opening is railed ('*', '#', 'O', '_')
    if any_open then
        for i = 1, n do
            local told = {}
            for y = 0, h - 1 do
                for x = 0, w - 1 do
                    if cell(g, i, x, y) == '*' then
                        for _, d in ipairs(N8) do
                            local nx, ny = x + d[1], y + d[2]
                            local c = cell(g, i, nx, ny)
                            if c and not RAIL_OK[c] and not told[ny * 64 + nx] then
                                told[ny * 64 + nx] = true
                                why('RAIL', i, nx, ny, ("%s beside an opening: a dwarf could fall; rail the edge "
                                                        .. "with '#' or 'O'"):format(char_words(c)))
                            end
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
    elseif any_open then
        -- (E1) SUPPORT (rock, the cave-in check): on each level, every tile
        -- but the openings is held: by the rock outside the drawing (a '_',
        -- the drawing's edge), by rock below it ('#' or '_' on the next
        -- level, or the map under the lowest), or through a held tile beside
        -- it (4 ways). A tile left hanging over a hole would cave in.
        for i = 1, n do
            local held, queue, head = {}, {}, 1
            for y = 0, h - 1 do
                for x = 0, w - 1 do
                    local ch = cell(g, i, x, y)
                    if ch ~= '*' then
                        local below = i < n and cell(g, i + 1, x, y) or '#'
                        if ch == '_' or x == 0 or y == 0 or x == w - 1 or y == h - 1 or below == '#' or below == '_' then
                            held[y * 64 + x] = true
                            table.insert(queue, {x, y})
                        end
                    end
                end
            end
            while head <= #queue do
                local x, y = queue[head][1], queue[head][2]
                head = head + 1
                for _, d in ipairs(N4) do
                    local nx, ny = x + d[1], y + d[2]
                    local c = cell(g, i, nx, ny)
                    if c and c ~= '*' and not held[ny * 64 + nx] then
                        held[ny * 64 + nx] = true
                        table.insert(queue, {nx, ny})
                    end
                end
            end
            for y = 0, h - 1 do
                for x = 0, w - 1 do
                    if cell(g, i, x, y) ~= '*' and not held[y * 64 + x] then
                        why('SUPPORT', i, x, y, 'nothing holds this over the opening below: it would cave in')
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
--   construct  surface: one 'Cw' 'Cf' 'Cr' 'Cu' 'Cd' 'Cx' 'CF' cell per tile;
--              rock (E1): a 'CF' cell per rail ('O'), built once the
--              level's openings are cut
--   open       rock (E1): one 'h' (channel) cell per opening ('*'), each with
--              its wave (1 is cut first: the farthest from the rails); cut
--              only once this level and the one below are dug
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
                   open = {}, tiles = {}, built = {}, solid = {}, footprint = {}, furniture = {}, halls = {},
                   smooth = {}, engrave = {}, summary = {}, orient = 0, engrave_all = false,
                   style = {}}
        local digkeys, pilekeys, zonekeys = {}, {}, {}
        local ztext = (i == zlevel) and zone_text(bp, zkind) or ''
        local function furn(t) L.furniture[t] = (L.furniture[t] or 0) + 1 end
        local dist, far = {}, 0
        if not surface and has_open(g[i]) then
            dist, far = open_distances(function(c, r) return cell(g, i, c, r) end, h, w)
        end
        local cuts = {}
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
                    local dug = ROCK_DUG[ch] or is_letter(ch)
                    floorish = dug and ch ~= '*' and ch ~= 'O'
                    if dug then
                        mark(L.tiles, x, y)
                        if DIG_KEY[ch] then
                            table.insert(L.dig, {x = x, y = y, text = DIG_KEY[ch]})
                        else
                            digkeys[r][c] = 'd'
                        end
                    end
                    if ch == 'O' then
                        table.insert(L.construct, {x = x, y = y, text = RAIL_KEY})
                        mark(L.built, x, y)
                        mark(L.solid, x, y)
                    elseif ch == '*' then
                        local d = dist[r * 64 + c] or far
                        table.insert(cuts, {x = x, y = y, text = OPEN_KEY, wave = far - d + 1})
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
        table.sort(cuts, function(a, b)
            if a.wave ~= b.wave then return a.wave < b.wave end
            if a.y ~= b.y then return a.y < b.y end
            return a.x < b.x
        end)
        L.open = cuts
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
                            if nc and (ROCK_WALK[nc] or is_letter(nc)) then touches = true end
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
        local count, rails = 0, 0
        for _, col in pairs(surface and L.built or L.tiles) do for _ in pairs(col) do count = count + 1 end end
        if not surface then rails = #L.construct end
        L.summary = {landmark = bp.name, purpose = bp.purpose, level = i, levels = n,
                     dug = (not surface) and count or 0, built = surface and count or rails,
                     opened = #cuts > 0 and #cuts or nil}
        out.levels[i] = L
    end
    return out
end

---------------------------------------------------------------------------
-- (E2) The build order of a surface drawing, with scaffolding
---------------------------------------------------------------------------
-- A surface landmark goes up level by level from the bottom. A tile is
-- built by a dwarf standing on a walkable tile beside it (8 ways, the same
-- level) that a dwarf can walk to from '@'; a stair is also built from the
-- up stair under it (a stair column grows from below) [verify]. Where the
-- next tiles can't be reached so, a temporary stair column (scaffolding:
-- 'Cu' on the ground, 'Cx' above) is planned first, on ground left walkable
-- ('.') with open air ('_') over it on every level it climbs (outside the
-- finished shape), and taken down (top first) once the part it serves is
-- built. Never walls a dwarf in: no step leaves a tile that was reachable
-- walkable but cut off from '@' (the walls that would close a space wait,
-- inside-out, until the space has another way out), and a removal waits
-- while anyone stands where it would strand them (its `cut` tiles).
--
-- build_stages(bp, q) -> {list = {step...}, scaffold = {columns, tiles}},
-- or nil and reasons ({code = 'ORDER', level, x, y, words}, on the
-- drawing's own grid). A step: {kind = 'build' | 'scaffold' | 'remove',
-- level, dz, cells = {{x, y, text, gx, gy}}, cut = {{x, y, dz}} (remove)},
-- x, y in to_layouts' frame (level 1's '@' at 0, 0, after q quarter turns);
-- text a construction key ('Cw' 'Cf' 'Cr' 'Cu' 'Cd' 'Cx' 'CF'), 'd' a door,
-- or the scaffold's key (a 'remove' step's tiles are taken down). The
-- furniture, stockpiles and zone come after the last step, as before.
-- A rock drawing has no steps. Pure: the drawing only, no map.
SCAFFOLD_MAX = {columns = 4, tiles = 24}

local SOLID_KEY = {Cw = true, CF = true}
local STAIR_KEY = {Cu = true, Cd = true, Cx = true}
local KEY_SYM = {Cw = 'W', CF = 'O', Cf = 'F', Cr = 'R', Cu = 'U', Cd = 'D', Cx = 'I', d = 'd'}

local function stage_plan(bp)
    local g = grids_of(bp)
    local n, h, w = #g, #g[1], #g[1][1]
    local jx, jy
    for r = 0, h - 1 do
        local c = g[1][r + 1]:find('@', 1, true)
        if c then jx, jy = c - 1, r end
    end
    local function K(i, x, y) return (i * 64 + y) * 64 + x end
    local jobs, job_at = {}, {}
    for i = 1, n do
        for y = 0, h - 1 do
            for x = 0, w - 1 do
                local ch = cell(g, i, x, y)
                local below = i > 1 and cell(g, i - 1, x, y) or nil
                local key = CONSTRUCT[ch] or (needs_floor(i, ch, below) and 'Cf') or nil
                if key then
                    local j = {i = i, x = x, y = y, text = key, solid = SOLID_KEY[key] or false}
                    table.insert(jobs, j)
                    job_at[K(i, x, y)] = j
                end
                if ch == '+' then
                    local j = {i = i, x = x, y = y, text = 'd', door = true, solid = false}
                    table.insert(jobs, j)
                    job_at[-K(i, x, y)] = j      -- the door's own key (its floor may share the tile)
                end
            end
        end
    end
    return {g = g, n = n, h = h, w = w, jx = jx, jy = jy, K = K, jobs = jobs, job_at = job_at}
end

-- The state: built[k] = the symbol built there ('W' 'O' 'F' 'R' 'U' 'D' 'I',
-- 'd' a door), scaffolding in sc[k] ('U' or 'I').
local function sim(P)
    local S = {built = {}, sc = {}}
    local g, n, h, w, K = P.g, P.n, P.h, P.w, P.K
    local function eff(i, x, y)
        local k = K(i, x, y)
        return S.sc[k] or S.built[k]
    end
    S.eff = eff
    local function solid(b) return b == 'W' or b == 'O' end
    -- extra: {k = sym} taken as built on top of the state (a stage's walls)
    local function walk(i, x, y, extra)
        if i < 1 or i > n or x < 0 or y < 0 or x >= w or y >= h then return false end
        local k = K(i, x, y)
        local b = (extra and extra[k]) or eff(i, x, y)
        if b == '-' then b = nil end
        if solid(b) then return false end
        if b then return true end
        if i == 1 then return cell(g, 1, x, y) ~= '_' end
        local bk = K(i - 1, x, y)
        local under = (extra and extra[bk]) or eff(i - 1, x, y)
        return under == 'W'
    end
    S.walk = walk
    local function sym_at(i, x, y, extra)
        local k = K(i, x, y)
        local b = (extra and extra[k]) or eff(i, x, y)
        if b == '-' then return nil end
        return b
    end
    -- Every tile reached from '@': seen[k] = true. grow: floor jobs taken as
    -- they come within reach (built on the way); returns seen, taken.
    function S.reach(extra, grow)
        extra = extra or {}
        local taken = {}
        local seen
        local again = true
        while again do
            again = false
            seen = {}
            local queue, head = {}, 1
            local function go(i, x, y)
                local k = K(i, x, y)
                if not seen[k] and walk(i, x, y, extra) then
                    queue[#queue + 1] = {i, x, y}
                    seen[k] = #queue
                end
            end
            local function take(j)
                if grow and grow[j] and not taken[j] then
                    taken[j] = true
                    extra[K(j.i, j.x, j.y)] = j.door and (extra[K(j.i, j.x, j.y)] or 'd') or KEY_SYM[j.text]
                    again = true
                end
            end
            go(1, P.jx, P.jy)
            while head <= #queue do
                local i, x, y = table.unpack(queue[head])
                head = head + 1
                local b = sym_at(i, x, y, extra)
                if grow then
                    for _, d in ipairs(N8) do
                        local nx, ny = x + d[1], y + d[2]
                        take(P.job_at[K(i, nx, ny)])
                        if walk(i, nx, ny, extra) and not seen[K(i, nx, ny)] then go(i, nx, ny) end
                    end
                    if (b == 'U' or b == 'I') and i < n then
                        local j = P.job_at[K(i + 1, x, y)]
                        if j and STAIR_KEY[j.text] then take(j) end
                    end
                    b = sym_at(i, x, y, extra)
                end
                for _, d in ipairs(N8) do go(i, x + d[1], y + d[2]) end
                if (b == 'U' or b == 'I') and i < n then
                    local up = sym_at(i + 1, x, y, extra)
                    if up == 'D' or up == 'I' then go(i + 1, x, y) end
                end
                if (b == 'D' or b == 'I') and i > 1 then
                    local dn = sym_at(i - 1, x, y, extra)
                    if dn == 'U' or dn == 'I' then go(i - 1, x, y) end
                end
                if b == 'R' and i < n then
                    for _, d in ipairs(N8) do go(i + 1, x + d[1], y + d[2]) end
                end
                if i > 1 then
                    for _, d in ipairs(N8) do
                        if sym_at(i - 1, x + d[1], y + d[2], extra) == 'R' then go(i - 1, x + d[1], y + d[2]) end
                    end
                end
            end
            if not grow then break end
        end
        return seen, taken
    end
    -- Can a dwarf in `seen` build (or take down) the tile at i, x, y?
    -- Beside it on its level, or (a stair) on the up stair under it.
    function S.stand(seen, i, x, y, stair)
        for _, d in ipairs(N8) do
            if seen[K(i, x + d[1], y + d[2])] then return true end
        end
        if stair and i > 1 and seen[K(i - 1, x, y)] then
            local b = eff(i - 1, x, y)
            if b == 'U' or b == 'I' then return true end
        end
        return false
    end
    -- Tiles in `before` still walkable (with extra) but not in `after`.
    function S.cut(before, after, extra)
        local out = {}
        for k in pairs(before) do
            if not after[k] then
                local x = k % 64
                local y = (k // 64) % 64
                local i = k // 4096
                if walk(i, x, y, extra) then out[#out + 1] = {i = i, x = x, y = y} end
            end
        end
        table.sort(out, function(a, b) return K(a.i, a.x, a.y) < K(b.i, b.x, b.y) end)
        return out
    end
    return S
end

local function turn_xy_bp(x, y, q)
    for _ = 1, q % 4 do x, y = -y, x end
    return x, y
end

local function order_reason(level, x, y, words)
    return {code = 'ORDER', level = level, x = x, y = y, words = where(level, x, y) .. words}
end

-- The ring of 8 round a tile, in order, and whether the reachable ones of
-- them are one group joined round it (so walling the tile cuts nothing off).
local RING = {{-1, -1}, {0, -1}, {1, -1}, {1, 0}, {1, 1}, {0, 1}, {-1, 1}, {-1, 0}}
local function simple_point(seen, K, j)
    local on, any = {}, 0
    for r, d in ipairs(RING) do
        if seen[K(j.i, j.x + d[1], j.y + d[2])] then on[r] = true any = any + 1 end
    end
    if any == 0 then return true end
    -- groups along the ring: a corner (odd r) joins its two sides; a side
    -- (even r) joins the next side across the corner between them too
    local group, g = {}, 0
    local function mark(r0)
        local stack = {r0}
        group[r0] = g
        while #stack > 0 do
            local r = table.remove(stack)
            local nb = {r % 8 + 1, (r - 2) % 8 + 1}
            if r % 2 == 0 then nb[3] = (r + 1) % 8 + 1; nb[4] = (r - 3) % 8 + 1 end
            for _, o in ipairs(nb) do
                if on[o] and not group[o] then group[o] = g stack[#stack + 1] = o end
            end
        end
    end
    for r = 1, 8 do
        if on[r] and not group[r] then g = g + 1 mark(r) end
    end
    return g <= 1
end

function build_stages(bp, q)
    if type(bp) ~= 'table' or bp.ground ~= 'surface' then
        return {list = {}, scaffold = {columns = 0, tiles = 0}}
    end
    local ok, reasons = check_format(bp)
    if not ok then return nil, reasons end
    q = (int(q) or 0) % 4
    local P = stage_plan(bp)
    local S = sim(P)
    local K, n = P.K, P.n
    local function simple(seen, j) return simple_point(seen, K, j) end
    local done = {}
    local steps = {}
    local columns = {}           -- {x, y, top, used}
    local sc_tiles = 0
    local function pending_dep(j)
        if j.i > 1 then
            local below = P.job_at[K(j.i - 1, j.x, j.y)]
            if below and not done[below] then return true end
        end
        if j.door then
            local floor = P.job_at[K(j.i, j.x, j.y)]
            if floor and not done[floor] then return true end
        end
        return false
    end
    local function commit(kind, level, list, extra)
        for _, j in ipairs(list) do
            done[j] = true
            local k = K(j.i, j.x, j.y)
            if j.door then
                S.built[k] = S.built[k] or 'd'
            else
                S.built[k] = KEY_SYM[j.text]
            end
        end
        table.sort(list, function(a, b)
            if a.y ~= b.y then return a.y < b.y end
            if a.x ~= b.x then return a.x < b.x end
            return (a.door and 1 or 0) < (b.door and 1 or 0)
        end)
        table.insert(steps, {kind = kind, level = level, jobs = list})
    end
    -- The columns a step leans on (it can't be done without them), on the
    -- state before it: floors (grown) or walls and doors (beside a dwarf).
    local function leans(list, grown)
        local need = {}
        for _, c in ipairs(columns) do
            local saved = {}
            for i = 1, c.top do local k = K(i, c.x, c.y); saved[k] = S.sc[k]; S.sc[k] = nil end
            local miss = false
            if grown then
                local g2 = {}
                for _, j in ipairs(list) do g2[j] = true end
                local _, t2 = S.reach({}, g2)
                for _, j in ipairs(list) do if not t2[j] then miss = true break end end
            else
                local extra = {}
                for _, j in ipairs(list) do if j.solid then extra[K(j.i, j.x, j.y)] = KEY_SYM[j.text] end end
                local seen = S.reach(extra)
                for _, j in ipairs(list) do
                    if not S.stand(seen, j.i, j.x, j.y, false) then miss = true break end
                end
            end
            for k, v in pairs(saved) do S.sc[k] = v end
            if miss then need[#need + 1] = c end
        end
        return need
    end
    local guard = 0
    while true do
        guard = guard + 1
        if guard > 4000 then return nil, {order_reason(nil, nil, nil, 'the build order did not settle')} end
        local left = false
        for _, j in ipairs(P.jobs) do if not done[j] then left = true break end end
        if not left then break end
        local R0 = S.reach()
        local progressed = false
        for L = 1, n do
            -- floors, stairs and ramps first (they only open ways), taken
            -- as they come within reach (the dwarves build them outward)
            local grow, any = {}, false
            for _, j in ipairs(P.jobs) do
                if not done[j] and j.i == L and not j.solid and not j.door and not pending_dep(j) then
                    grow[j] = true
                    any = true
                end
            end
            if any then
                local _, taken = S.reach({}, grow)
                local list = {}
                for _, j in ipairs(P.jobs) do if taken[j] then list[#list + 1] = j end end
                if #list > 0 then
                    local need = leans(list, true)
                    commit('build', L, list)
                    for _, c in ipairs(need) do c.used = #steps end
                    progressed = true
                    break
                end
            end
            -- then the walls and fortifications (and the doors), inside-out
            local cand = {}
            for _, j in ipairs(P.jobs) do
                if not done[j] and j.i == L and (j.solid or j.door) and not pending_dep(j)
                        and S.stand(R0, j.i, j.x, j.y, false) then
                    cand[#cand + 1] = j
                end
            end
            -- inside-out: the farthest from '@' first; a wall joins the step
            -- only while every tile of it keeps a dwarf's place beside it,
            -- whatever order they go up in, and no reachable tile is cut off
            local function far(j)
                local v = R0[K(j.i, j.x, j.y)]
                if v then return v end
                v = 0
                for _, d in ipairs(N8) do
                    local o = R0[K(j.i, j.x + d[1], j.y + d[2])]
                    if o and o > v then v = o end
                end
                return v
            end
            for _, j in ipairs(cand) do j.far = far(j) end
            table.sort(cand, function(a, b)
                if a.far ~= b.far then return a.far > b.far end
                return K(a.i, a.x, a.y) < K(b.i, b.x, b.y)
            end)
            local take, extra = {}, {}
            local R1 = {}
            for k, v in pairs(R0) do R1[k] = v end
            for _, j in ipairs(cand) do
                local k = K(j.i, j.x, j.y)
                local trial, local_only = R1, false
                if j.solid and R1[k] then
                    extra[k] = KEY_SYM[j.text]
                    if j.i == 1 and simple(R1, j) then
                        -- (a tile whose reachable neighbours stay joined round
                        -- it: walling it cuts nothing off, no search needed)
                        R1[k] = nil
                        local_only = true
                    else
                        trial = S.reach(extra)
                    end
                end
                local good = S.stand(trial, j.i, j.x, j.y, false)
                if good then
                    for _, t in ipairs(take) do
                        if not S.stand(trial, t.i, t.x, t.y, false) then good = false break end
                    end
                end
                if good and trial ~= R1 and #S.cut(R0, trial, extra) > 0 then good = false end
                if good then
                    take[#take + 1] = j
                    R1 = trial
                else
                    if local_only then R1[k] = R0[k] end
                    if j.solid then extra[k] = nil end
                end
            end
            cand = take
            if #cand > 0 then
                local need = leans(cand, false)
                commit('build', L, cand)
                for _, c in ipairs(need) do c.used = #steps end
                progressed = true
                break
            end
        end
        if not progressed then
            -- stuck: the lowest level with tiles ready but out of reach
            local L, stuck
            for lv = 1, n do
                stuck = {}
                for _, j in ipairs(P.jobs) do
                    if not done[j] and j.i == lv and not pending_dep(j)
                            and not S.stand(R0, j.i, j.x, j.y, STAIR_KEY[j.text]) then
                        stuck[#stuck + 1] = j
                    end
                end
                if #stuck > 0 then L = lv break end
            end
            if not L then
                local j
                for _, jj in ipairs(P.jobs) do if not done[jj] then j = jj break end end
                return nil, {order_reason(j.i, j.x, j.y, 'no build order that keeps a way out: these walls would close '
                    .. 'a space before it has another way out')}
            end
            local j1 = stuck[1]
            if L == 1 then
                return nil, {order_reason(j1.i, j1.x, j1.y, 'no dwarf can reach this tile from a walkable one to build it')}
            end
            -- a scaffold stair: a new column, or an old one climbing higher
            local best
            for y = 0, P.h - 1 do
                for x = 0, P.w - 1 do
                    local old
                    for _, c in ipairs(columns) do if c.x == x and c.y == y and not c.down then old = c end end
                    local from = old and (old.top + 1) or 1
                    local good = from <= L
                    if good and not old then
                        good = cell(P.g, 1, x, y) == '.' and not S.eff(1, x, y) and R0[K(1, x, y)] ~= nil
                    end
                    for i = math.max(from, 2), L do
                        if good and (cell(P.g, i, x, y) ~= '_' or S.eff(i, x, y)) then good = false end
                    end
                    if good then
                        for _, c in ipairs(columns) do
                            if not c.down and c ~= old and math.abs(c.x - x) + math.abs(c.y - y) == 0 then good = false end
                        end
                    end
                    if good then
                        local saved = {}
                        for i = from, L do
                            local k = K(i, x, y)
                            saved[k] = S.sc[k]
                            S.sc[k] = (i == 1) and 'U' or 'I'
                        end
                        local seen = S.reach()
                        local gain = 0
                        for _, j in ipairs(stuck) do
                            if S.stand(seen, j.i, j.x, j.y, STAIR_KEY[j.text]) then gain = gain + 1 end
                        end
                        for k, v in pairs(saved) do S.sc[k] = v end
                        if gain > 0 then
                            local over = 0          -- the finished shape above it (later levels)
                            for i = L + 1, n do if cell(P.g, i, x, y) ~= '_' then over = over + 1 end end
                            local dist = math.max(math.abs(x - P.jx), math.abs(y - P.jy))
                            local score = {-gain, over, L - from + 1, dist, y, x}
                            local better = not best
                            if best then
                                for t = 1, #score do
                                    if score[t] ~= best.score[t] then better = score[t] < best.score[t] break end
                                end
                            end
                            if better then best = {x = x, y = y, from = from, old = old, score = score} end
                        end
                    end
                end
            end
            if not best then
                return nil, {order_reason(j1.i, j1.x, j1.y, 'no dwarf can reach this tile, and there is no open ground '
                    .. "('.' with open air above) beside the shape for a scaffold stair")}
            end
            local add = L - best.from + 1
            if (not best.old and #columns >= SCAFFOLD_MAX.columns) or sc_tiles + add > SCAFFOLD_MAX.tiles then
                return nil, {order_reason(j1.i, j1.x, j1.y, ('it would take more scaffolding than allowed '
                    .. '(%d stair columns, %d tiles)'):format(SCAFFOLD_MAX.columns, SCAFFOLD_MAX.tiles))}
            end
            local c = best.old or {x = best.x, y = best.y, top = 0}
            if not best.old then table.insert(columns, c) end
            for i = best.from, L do
                local key = (i == 1) and 'Cu' or 'Cx'
                S.sc[K(i, c.x, c.y)] = (i == 1) and 'U' or 'I'
                table.insert(steps, {kind = 'scaffold', level = i, column = c,
                                     jobs = {{i = i, x = c.x, y = c.y, text = key}}})
                sc_tiles = sc_tiles + 1
            end
            c.top = L
            c.used = #steps
        end
    end
    -- the scaffolding comes down (top first) after the last step that
    -- leans on it; the whole order is then replayed and checked (else every
    -- column comes down at the end)
    local function with_removals(at_end)
        local out = {}
        local after = {}
        for _, c in ipairs(columns) do
            local at = at_end and #steps or math.max(c.used or #steps, 1)
            after[at] = after[at] or {}
            table.insert(after[at], c)
        end
        for s, st in ipairs(steps) do
            table.insert(out, st)
            for _, c in ipairs(after[s] or {}) do
                for i = c.top, 1, -1 do
                    table.insert(out, {kind = 'remove', level = i, column = c,
                                       jobs = {{i = i, x = c.x, y = c.y, text = (i == 1) and 'Cu' or 'Cx'}}})
                end
            end
        end
        return out
    end
    local function replay(list)
        local R = sim(P)
        local fin = {}
        local cuts = {}
        for s, st in ipairs(list) do
            local before = R.reach()
            if st.kind == 'remove' then
                local j = st.jobs[1]
                local k = K(j.i, j.x, j.y)
                if not R.sc[k] or (j.i < n and R.sc[K(j.i + 1, j.x, j.y)]) then return false end
                local sv = R.sc[k]
                R.sc[k] = nil
                local by_side = R.stand(before, j.i, j.x, j.y, false)
                R.sc[k] = sv
                local below = j.i > 1 and before[K(j.i - 1, j.x, j.y)] and R.sc[K(j.i - 1, j.x, j.y)]
                if not (by_side or below) then return false end
                R.sc[k] = nil
                local after = R.reach()
                cuts[s] = R.cut(before, after)
                -- (0.105.37 fix) a removal that leaves a tile cut off (one the
                -- remover or a builder could be standing on) is refused: this
                -- order fails, and with none left the drawing is refused
                if #cuts[s] > 0 then return false end
            else
                local extra = {}
                for _, j in ipairs(st.jobs) do
                    if st.kind == 'build' and j.solid then extra[K(j.i, j.x, j.y)] = KEY_SYM[j.text] end
                end
                local R1 = R.reach(extra)
                if #R.cut(before, R1, extra) > 0 then return false end
                local grow = {}
                for _, j in ipairs(st.jobs) do
                    if j.i > 1 then
                        local bj = P.job_at[K(j.i - 1, j.x, j.y)]
                        if bj and not fin[bj] then return false end
                    end
                    if j.door then
                        local fj = P.job_at[K(j.i, j.x, j.y)]
                        if fj and not fin[fj] then return false end
                    end
                    if st.kind == 'build' and not j.solid and not j.door then grow[j] = true end
                end
                local _, taken = R.reach({}, grow)
                for _, j in ipairs(st.jobs) do
                    local can
                    if grow[j] then can = taken[j]
                    else can = R.stand(R1, j.i, j.x, j.y, st.kind == 'scaffold' or STAIR_KEY[j.text]) end
                    if not can then return false end
                end
                for _, j in ipairs(st.jobs) do
                    local k = K(j.i, j.x, j.y)
                    if st.kind == 'scaffold' then R.sc[k] = (j.i == 1) and 'U' or 'I'
                    elseif j.door then R.built[k] = R.built[k] or 'd'
                    else R.built[k] = KEY_SYM[j.text] end
                    fin[j] = true
                end
            end
        end
        for _ in pairs(R.sc) do return false end
        return true, cuts
    end
    local list = with_removals(false)
    local good, cuts = replay(list)
    if not good then
        list = with_removals(true)
        good, cuts = replay(list)
    end
    if not good then
        return nil, {order_reason(nil, nil, nil, 'no safe order to put up and take down its scaffolding')}
    end
    -- in to_layouts' frame
    local function frame(x, y) return turn_xy_bp(x - P.jx, y - P.jy, q) end
    local out = {list = {}, scaffold = {columns = #columns, tiles = sc_tiles}}
    for s, st in ipairs(list) do
        local step = {kind = st.kind, level = st.level, dz = st.level - 1, cells = {}}
        for _, j in ipairs(st.jobs) do
            local x, y = frame(j.x, j.y)
            table.insert(step.cells, {x = x, y = y, text = j.text, gx = j.x, gy = j.y})
        end
        if st.kind == 'remove' then
            step.cut = {}
            for _, c in ipairs(cuts[s] or {}) do
                local x, y = frame(c.x, c.y)
                table.insert(step.cut, {x = x, y = y, dz = c.i - 1})
            end
        end
        table.insert(out.list, step)
    end
    return out
end
