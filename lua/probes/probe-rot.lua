-- probe-rot: what makes the miasma. Every miasma tile's 8x8 cell, and every
-- organic item (food, fish, meat, bodies, parts, remains) within 6 tiles of a
-- miasma tile on its level or the one below: its kind, rot state, container,
-- the building holding it, the building on its tile, a stockpile there. Also
-- the fort-wide count of rotten food by where it lies. READ ONLY.
--
--     probe-rot [radius]
local json = require('json')
local R = tonumber(({...})[1]) or 6
local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
local KINDS = {'FISH_RAW', 'FISH', 'MEAT', 'FOOD', 'CORPSE', 'CORPSEPIECE', 'REMAINS', 'PLANT', 'PLANT_GROWTH',
               'CHEESE', 'EGG', 'GLOB', 'VERMIN', 'SEEDS', 'DRINK', 'POWDER_MISC', 'LIQUID_MISC'}

local out = {radius = R, miasma_tiles = 0, cells = {}, near = {}, near_by = {}, rotten_by = {}, rotten_at = {}, rot_kinds = {}, fish_raw = {}}
local mtiles = {}
local okm, MK = pcall(function() return df.flow_type.Miasma end)
pcall(function()
    for _, f in ipairs(df.global.flows) do
        if f.type == MK and f.density > 0 and f.pos.x >= 0 then
            out.miasma_tiles = out.miasma_tiles + 1
            local k = f.pos.z * 1000000 + (f.pos.x // 8) * 1000 + (f.pos.y // 8)
            local c = mtiles[k]
            if not c then c = {x = f.pos.x, y = f.pos.y, z = f.pos.z, n = 0, d = 0}; mtiles[k] = c end
            c.n = c.n + 1
            c.d = math.max(c.d, f.density)
        end
    end
end)
local cells = {}
for _, c in pairs(mtiles) do cells[#cells + 1] = c end
table.sort(cells, function(a, b) return a.n > b.n end)
for i = 1, math.min(#cells, 12) do table.insert(out.cells, cells[i]) end

local function near_cell(x, y, z)
    for _, c in ipairs(cells) do
        if (z == c.z or z == c.z - 1) and math.abs(x - (c.x // 8 * 8 + 4)) <= R + 4
            and math.abs(y - (c.y // 8 * 8 + 4)) <= R + 4 then return c end
    end
end

local function where(it)
    local w = {}
    pcall(function()
        local c = dfhack.items.getContainer(it)
        if c then w.container = df.item_type[c:getType()] end
    end)
    pcall(function()
        local b = dfhack.items.getHolderBuilding(it)
        if b then w.held_by = df.building_type[b:getType()]; pcall(function() w.held_sub = b:getSubtype() end) end
    end)
    local okp, x, y, z = pcall(dfhack.items.getPosition, it)
    if okp and x then
        w.x, w.y, w.z = x, y, z
        pcall(function()
            local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
            if b then w.on = df.building_type[b:getType()] end
        end)
        pcall(function()
            local fl = dfhack.maps.getTileFlags(x, y, z)
            w.outside = fl.outside == true
        end)
    end
    pcall(function() if it.flags.in_job then w.in_job = true end end)
    pcall(function() if it.flags.dump then w.dump = true end end)
    pcall(function() if it.flags.forbid then w.forbid = true end end)
    pcall(function() if it.flags.on_ground then w.ground = true end end)
    return w
end

local function place_key(w)
    if w.held_by then return 'in ' .. w.held_by end
    if w.container then return 'in ' .. w.container .. (w.on == 'Stockpile' and ' on a pile' or '') end
    if w.on == 'Stockpile' then return 'loose on a pile' end
    if w.on then return 'loose on a ' .. w.on end
    return w.ground and 'loose on the floor' or 'held/carried'
end

for _, kind in ipairs(KINDS) do
    pcall(function()
        for _, it in ipairs(df.global.world.items.other[kind]) do
            local okr, rotten = pcall(function() return it.flags.rotten == true end)
            rotten = okr and rotten
            local okt, rt = pcall(function() return it.rot_timer end)
            rt = okt and rt or nil
            if rotten then
                local w = where(it)
                local k = kind .. ' ' .. place_key(w)
                out.rotten_by[k] = (out.rotten_by[k] or 0) + 1
                if w.x then
                    local tk = kind .. ' ' .. w.x .. ',' .. w.y .. ',' .. w.z .. (w.outside and ' outside' or ' inside')
                        .. (w.forbid and ' forbid' or '') .. (w.dump and ' dump' or '') .. (w.in_job and ' in_job' or '')
                    out.rotten_at[tk] = (out.rotten_at[tk] or 0) + 1
                end
            end
            if kind == 'FISH_RAW' and not rotten then
                local k = place_key(where(it))
                out.fish_raw[k] = (out.fish_raw[k] or 0) + 1
            end
            local okp, x, y, z = pcall(dfhack.items.getPosition, it)
            if okp and x and #cells > 0 then
                local c = near_cell(x, y, z)
                if c then
                    local w = where(it)
                    local k = kind .. (rotten and ' ROTTEN ' or ' ') .. place_key(w)
                    out.near_by[k] = (out.near_by[k] or 0) + 1
                    if rt then out.rot_kinds[kind] = math.max(out.rot_kinds[kind] or 0, rt) end
                    if (rotten or kind == 'FISH_RAW' or kind == 'CORPSE' or kind == 'CORPSEPIECE' or kind == 'REMAINS'
                        or kind == 'MEAT') and #out.near < 40 then
                        local okd, d = pcall(function() return txt(dfhack.items.getDescription(it, 0, true)) end)
                        w.id, w.kind, w.what, w.rotten, w.rot_timer = it.id, kind, okd and d or kind, rotten or nil, rt
                        table.insert(out.near, w)
                    end
                end
            end
        end
    end)
end
print(json.encode(out))
