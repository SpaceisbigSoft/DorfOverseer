-- ai-bridge-report-world: the report's hazards, the deep, others on the map, the dwarves'
-- levels, nobles, mandates, the order desk, and the event feed.
--
-- A part of ai-bridge.lua (r6, split out of ai-bridge-report.lua when it was 194 KB),
-- loaded by it after ai-bridge-report into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-report files share with this one come from REPORT_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-report-world is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report-world'] = '0.105.114'   -- bumped with BRIDGE_VERSION

local utils = require('utils')
local inc, TICKS_PER_DAY = REPORT_PART_LOCALS.inc, REPORT_PART_LOCALS.TICKS_PER_DAY
local layer_at, citizen_positions, nearest = REPORT_PART_LOCALS.layer_at, REPORT_PART_LOCALS.citizen_positions, REPORT_PART_LOCALS.nearest

---------------------------------------------------------------------------
-- Hazards (phase 11): fire and clouds near the dwarves, dwarves standing in
-- deep water or magma, citizens gone berserk, and invaders caught in cages.
-- Cheap: the flow list and the citizens' own tiles, nothing scanned.
---------------------------------------------------------------------------
local FIRE_FLOWS = {Fire = true, Dragonfire = true}
local CLOUD_FLOWS = {MaterialGas = true, MaterialVapor = true, Miasma = false}

function get_hazards()
    local out = {fires = 0, fire_near = nil, clouds = 0, cloud_near = nil, miasma = 0,
                 wet = {}, burning = {}, berserk = {}, caged = 0}
    local cit = citizen_positions()
    pcall(function()
        for _, f in ipairs(df.global.flows) do
            if f.density > 0 then
                local t = df.flow_type[f.type]
                local d = nearest({x = f.pos.x, y = f.pos.y, z = f.pos.z}, cit)
                if FIRE_FLOWS[t] then
                    out.fires = out.fires + 1
                    if d and (not out.fire_near or d < out.fire_near) then out.fire_near = d end
                elseif t == 'Miasma' then
                    out.miasma = out.miasma + 1
                    -- (0.104.159) where: 8x8 cells on a level
                    MIASMA_CELLS = MIASMA_CELLS or {}
                    local k = f.pos.z * 1000000 + (f.pos.x // 8) * 1000 + (f.pos.y // 8)
                    local c = MIASMA_CELLS[k] or {n = 0, x = f.pos.x, y = f.pos.y, z = f.pos.z}
                    c.n = c.n + 1
                    MIASMA_CELLS[k] = c
                elseif CLOUD_FLOWS[t] then
                    out.clouds = out.clouds + 1
                    if d and (not out.cloud_near or d < out.cloud_near) then out.cloud_near = d end
                end
            end
        end
    end)
    -- (0.104.159) the miasma's spots, the worst 5: the zone there and what
    -- rots near it (Teacheroar, 1 Nov: miasma the worst stress, 128 of 150
    -- disgusted, while the remains were being rotted away daily)
    pcall(function()
        local cells = MIASMA_CELLS or {}
        MIASMA_CELLS = nil
        local list = {}
        for _, c in pairs(cells) do table.insert(list, c) end
        table.sort(list, function(a, b) return a.n > b.n end)
        while #list > 5 do table.remove(list) end
        if #list == 0 then return end
        for _, c in ipairs(list) do
            c.rotting = {}
            pcall(function()
                for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(c.x, c.y, c.z)) or {}) do
                    c.zone = c.zone or df.civzone_type[zn.type]
                end
            end)
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(c.x, c.y, c.z))
                if b then c.building = df.building_type[b:getType()] end
            end)
            -- a refuse pile within 10 tiles on that level
            pcall(function()
                for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
                    if sp.z == c.z and sp.settings.flags.refuse and sp.x1 - 10 <= c.x and c.x <= sp.x2 + 10
                            and sp.y1 - 10 <= c.y and c.y <= sp.y2 + 10 then
                        c.refuse_pile = sp.id
                    end
                end
            end)
            pcall(function()
                local des = dfhack.maps.getTileFlags(c.x, c.y, c.z)
                c.outside = des and des.outside and true or false
            end)
        end
        for _, kind in ipairs({'CORPSE', 'CORPSEPIECE', 'REMAINS', 'MEAT', 'FISH', 'FISH_RAW', 'PLANT', 'FOOD'}) do
            local okl, items = pcall(function() return df.global.world.items.other[kind] end)
            for _, it in ipairs(okl and items or {}) do
                local okp, x, y, z = pcall(dfhack.items.getPosition, it)
                if okp and x then
                    if type(x) ~= 'number' then x, y, z = x.x, x.y, x.z end
                    for _, c in ipairs(list) do
                        if z == c.z and math.abs(x - c.x) <= 8 and math.abs(y - c.y) <= 8 then
                            c.rotting[kind] = (c.rotting[kind] or 0) + 1
                        end
                    end
                end
            end
        end
        out.miasma_spots = list
    end)
    for _, u in ipairs(report_citizens()) do
        local name
        local function who()
            name = name or txt(dfhack.units.getReadableName(u))
            return {id = u.id, name = name}
        end
        pcall(function()
            local des = dfhack.maps.getTileFlags(u.pos.x, u.pos.y, u.pos.z)
            if des and des.flow_size >= 4 then
                if des.liquid_type == true or des.liquid_type == 1 then table.insert(out.burning, who())
                else table.insert(out.wet, who()) end
            end
        end)
        pcall(function()
            if u.mood == df.mood_type.Berserk then table.insert(out.berserk, who()) end
        end)
    end
    -- (0.100.1, review) DFHack's citizen list leaves out the insane, and a
    -- berserk dwarf is insane: the fort's own people gone berserk, from all units
    pcall(function()
        local seen = {}
        for _, b in ipairs(out.berserk) do seen[b.id] = true end
        for _, u in ipairs(report_units()) do
            -- (0.104.140) one of the fort's own changed into a beast (a
            -- werebeast's night, its race not its own): it attacks everyone, and
            -- like a berserk dwarf only soldiers stop it
            local changed = false
            pcall(function()
                changed = not dfhack.units.isDead(u) and u.enemy.normal_race ~= -1 and u.enemy.normal_race ~= u.race
                    and u.civ_id == df.global.plotinfo.civ_id
                    and (u.enemy.were_race == nil or u.enemy.were_race == -1 or u.race == u.enemy.were_race)
            end)
            if changed and not seen[u.id] then
                seen[u.id] = true
                table.insert(out.berserk, {id = u.id, name = txt(dfhack.units.getReadableName(u)), changed = true})
            end
            if u.mood == df.mood_type.Berserk and not seen[u.id] and not dfhack.units.isDead(u) then
                local own = false
                pcall(function() own = dfhack.units.isOwnGroup(u) end)
                if not own then pcall(function() own = u.civ_id == df.global.plotinfo.civ_id end) end
                if own then
                    table.insert(out.berserk, {id = u.id, name = txt(dfhack.units.getReadableName(u))})
                end
            end
            -- invaders caught in cages (13c: in this walk, not one of their own)
            pcall(function()
                if u.flags1.caged and not dfhack.units.isCitizen(u, true) and dfhack.units.isActive(u)
                        and (dfhack.units.isInvader(u) or dfhack.units.isDanger(u)) then
                    out.caged = out.caged + 1
                end
            end)
        end
    end)
    -- cage traps: how many, how many hold a catch (a full one catches nothing
    -- more until its cage is hauled away and an empty one loaded), empty cages
    -- free for them, and whether an animal stockpile (where full cages go) exists
    out.cage_traps, out.cage_traps_full, out.free_cages, out.animal_piles = 0, 0, 0, 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.CageTrap then
                out.cage_traps = out.cage_traps + 1
                for _, ci in ipairs(b.contained_items) do
                    local it = ci.item
                    if it:getType() == df.item_type.CAGE and dfhack.items.getGeneralRef(it, df.general_ref_type.CONTAINS_UNIT) then
                        out.cage_traps_full = out.cage_traps_full + 1
                        break
                    end
                end
            end
        end
        for _, it in ipairs(df.global.world.items.other.CAGE) do
            local f = it.flags
            if not (f.in_building or f.in_job or f.forbid or f.trader or f.removed or f.garbage_collect)
                    and not dfhack.items.getGeneralRef(it, df.general_ref_type.CONTAINS_UNIT) then
                out.free_cages = out.free_cages + 1
            end
        end
        for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
            if sp.settings.flags.animals then out.animal_piles = out.animal_piles + 1 end
        end
    end)
    return out
end

---------------------------------------------------------------------------
-- The deep: the caverns (found yet, and whether the fort's ground joins
-- them), the great dangers on the map (forgotten beasts, titans, demons,
-- night creatures, the undead) and where, and cursed citizens (vampires,
-- werebeasts) living among the dwarves.
---------------------------------------------------------------------------

JUNCTIONS = JUNCTIONS or {}      -- (0.104.103) cavern name -> {tick, found}: looked for once a week
-- (0.105.40 E3) Which blocks lie in each cavern never changes while the map
-- is loaded (a block's global_feature is set when the map is made), yet
-- get_deep walked every block of the map (~25,000 on a 4x4 embark) each
-- report to sort them. The caverns' block positions are kept (positions, not
-- pointers: DF memory isn't kept between runs) under the layers' key and the
-- map's block count, and the blocks fetched again by position, in the same
-- order. Any block not found, or a key that differs: the full walk.
local function deep_key(layers)
    local ok, k = pcall(function() return tostring(layers.key) .. ':' .. #df.global.world.map.map_blocks end)
    return ok and k or nil
end

function deep_blocks_keep(layers, pos)
    local key = deep_key(layers)
    if not key or not layers.key then DEEP_BLOCKS = nil return end
    local by_idx = {}
    for bl, list in pairs(pos) do by_idx[bl._idx] = list end
    DEEP_BLOCKS = {key = key, pos = by_idx}
end

function deep_blocks_again(layers)
    local d = DEEP_BLOCKS
    if not d or not layers.key or d.key ~= deep_key(layers) then return nil end
    local ok, out = pcall(function()
        local out = {}
        for _, bl in ipairs(layers.list) do
            local list = d.pos[bl._idx]
            if list then
                local blocks = {}
                for i, p in ipairs(list) do
                    local b = dfhack.maps.getTileBlock(p[1], p[2], p[3])
                    if not b or b.global_feature == nil or layers.by_gid[b.global_feature] ~= bl then error('moved') end
                    blocks[i] = b
                end
                out[bl] = blocks
            end
        end
        return out
    end)
    return ok and out or nil
end

-- (0.105.46, I6) the caverns' block positions by layer (the kept ones, else
-- one walk of the map's blocks, kept as deep_blocks_keep does)
function deep_positions(layers)
    local d = DEEP_BLOCKS
    if d and layers.key and d.key == deep_key(layers) then
        local out = {}
        for _, bl in ipairs(layers.list) do out[bl] = d.pos[bl._idx] end
        return out
    end
    local pos = {}
    for _, block in ipairs(df.global.world.map.map_blocks) do
        local bl = layers.by_gid[block.global_feature]
        if bl then
            pos[bl] = pos[bl] or {}
            table.insert(pos[bl], {block.map_pos.x, block.map_pos.y, block.map_pos.z})
        end
    end
    deep_blocks_keep(layers, pos)
    return pos
end

-- (0.105.46, I6) the found caverns' seen samples and "open" by
-- lua/ai-cavern-scan.lua (kept per map, sliced); nil without it (the old walk)
local function deep_scan(layers, cit_list, groups)
    local okm, CS = pcall(reqscript, 'ai-cavern-scan')
    if not (okm and type(CS) == 'table' and CS.scan) then return nil end
    local ok, r = pcall(function()
        local pos = deep_positions(layers)
        local rows = {}
        for _, l in ipairs(layers.list) do
            if tostring(l.name):find('Cavern') and l.discovered then
                rows[#rows + 1] = {name = l.name, blocks = pos[l] or {}}
            end
        end
        return CS.scan(rows, groups, cit_list, tostring(deep_key(layers) or '?'), abs_tick())
    end)
    return ok and r or nil
end

function get_deep()
    local layers = get_layers()
    local cit_list, groups = citizen_positions()
    local out = {caverns = {}, dangers = {}, cursed = {}}
    local scanned = deep_scan(layers, cit_list, groups)
    -- (13c) the map's blocks sorted by cavern in one pass (each cavern walked
    -- every block of the map before)
    local cave_blocks
    local function blocks_of(l)
        if not cave_blocks then
            cave_blocks = deep_blocks_again(layers)
        end
        if not cave_blocks then
            cave_blocks = {}
            local pos = {}
            for _, block in ipairs(df.global.world.map.map_blocks) do
                local bl = layers.by_gid[block.global_feature]
                if bl then
                    cave_blocks[bl] = cave_blocks[bl] or {}
                    table.insert(cave_blocks[bl], block)
                    pos[bl] = pos[bl] or {}
                    table.insert(pos[bl], {block.map_pos.x, block.map_pos.y, block.map_pos.z})
                end
            end
            deep_blocks_keep(layers, pos)
        end
        return cave_blocks[l] or {}
    end
    for _, l in ipairs(layers.list) do
        if tostring(l.name):find('Cavern') then
            local row = {name = l.name, discovered = l.discovered, z_top = l.z_top, z_bottom = l.z_bottom,
                         seen = 0, open = false}
            if l.discovered and scanned and scanned[l.name] then
                local sc = scanned[l.name]          -- (0.105.46, I6)
                row.seen, row.open, row.open_at = sc.seen, sc.open, sc.open_at
            elseif l.discovered then
                -- (0.104.101) every block of the cavern is looked at; only the
                -- walkability checks of seen tiles are capped. The old cap
                -- counted hidden tiles too and stopped after ~170 blocks of a
                -- ~1,300-block cavern: Teacheroar's Cavern1 read "seen 0, not
                -- open" while dwarves worked and died in it, so nothing sealed it
                local walks = 0
                for _, block in ipairs(blocks_of(l)) do
                    local bx, by, bz = block.map_pos.x, block.map_pos.y, block.map_pos.z
                    for x = 0, 15, 5 do
                        for y = 0, 15, 5 do
                            if not block.designation[x][y].hidden then
                                row.seen = row.seen + 1
                                if walks < 4000 then
                                    walks = walks + 1
                                    local g = dfhack.maps.getWalkableGroup({x = bx + x, y = by + y, z = bz})
                                    if g ~= 0 and groups[g] then
                                        row.open = true
                                        row.open_at = row.open_at or {x = bx + x, y = by + y, z = bz}
                                    end
                                end
                            end
                        end
                    end
                    if row.open then break end
                end
            end
            -- (0.104.103) where the dwarves' dug ground actually meets the cavern:
            -- a walkable tile outside the cavern beside (or over, or under) a
            -- walkable cavern tile of the same walk group, searched over the
            -- dwarves' x/y span near the cavern's ceiling. Up to 4, with shapes.
            local now_j = abs_tick()
            local cj = JUNCTIONS[row.name]
            if row.open and cj and now_j - cj.tick < 7 * 1200 then
                row.junctions = cj.found
            elseif row.open then
                pcall(function()
                    local ps = cit_list
                    local x1, x2, y1, y2 = math.huge, -math.huge, math.huge, -math.huge
                    for _, p in ipairs(ps) do
                        x1, x2 = math.min(x1, p.x), math.max(x2, p.x)
                        y1, y2 = math.min(y1, p.y), math.max(y2, p.y)
                    end
                    -- (r5 p4) each tile read once: a tile was read again as the
                    -- neighbour of each of its 26 neighbours (up to 27 reads)
                    local seen_info = {}
                    local function info(x, y, z)
                        local k = x + y * 1024 + z * 1048576
                        local v = seen_info[k]
                        if v ~= nil then return v or nil end
                        local tt = dfhack.maps.getTileType(x, y, z)
                        if not tt then seen_info[k] = false; return nil end
                        local des = dfhack.maps.getTileFlags(x, y, z)
                        local g = dfhack.maps.getWalkableGroup(xyz2pos(x, y, z))
                        v = {cave = des and (des.feature_global or des.feature_local), g = g,
                             shape = df.tiletype_shape[df.tiletype.attrs[tt].shape]}
                        seen_info[k] = v
                        return v
                    end
                    local found = {}
                    for z = row.z_top - 1, row.z_top + 3 do
                        for y = math.max(1, y1 - 5), y2 + 5 do
                            for x = math.max(1, x1 - 5), x2 + 5 do
                                local t = info(x, y, z)
                                if t and not t.cave and t.g ~= 0 and groups[t.g] then
                                    for dz = -1, 1 do
                                        for dy = -1, 1 do
                                            for dx = -1, 1 do
                                                local n = (dx ~= 0 or dy ~= 0 or dz ~= 0) and info(x + dx, y + dy, z + dz)
                                                if n and n.cave and n.g == t.g and #found < 4 then
                                                    table.insert(found, {x = x, y = y, z = z, shape = t.shape,
                                                                         cave = {x = x + dx, y = y + dy, z = z + dz,
                                                                                 shape = n.shape}})
                                                end
                                            end
                                        end
                                    end
                                end
                                if #found >= 4 then break end
                            end
                            if #found >= 4 then break end
                        end
                        if #found >= 4 then break end
                    end
                    row.junctions = found
                    JUNCTIONS[row.name] = {tick = now_j, found = found}
                end)
            end
            -- (0.104.102) the way up from where it meets the fort: each level's tile
            -- and building (a hatch, a door), so the seal can be placed
            if row.open_at then
                local col = {}
                for dz = 0, 6 do
                    pcall(function()
                        local x, y, z = row.open_at.x, row.open_at.y, row.open_at.z + dz
                        local tt = dfhack.maps.getTileType(x, y, z)
                        local shape = tt and df.tiletype_shape[df.tiletype.attrs[tt].shape] or '?'
                        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
                        local bt = b and df.building_type[b:getType()] or nil
                        local closed, locked
                        if b then pcall(function() closed = b.door_flags.closed end) end
                        -- (fix3) locked (forbidden): the way down shut to the dwarves
                        if b then pcall(function() locked = b.door_flags.forbidden or nil end) end
                        local des = dfhack.maps.getTileFlags(x, y, z)
                        table.insert(col, {z = z, shape = shape, building = bt, closed = closed, locked = locked,
                                           cavern = des and (des.feature_global or des.feature_local) or nil})
                    end)
                end
                row.column = col
            end
            table.insert(out.caverns, row)
        end
    end
    local KINDS = {{'isForgottenBeast', 'forgotten beast'}, {'isTitan', 'titan'}, {'isMegabeast', 'megabeast'},
                   {'isDemon', 'demon'}, {'isNightCreature', 'night creature'}, {'isUndead', 'undead'}}
    local function kind_of(u)
        for _, k in ipairs(KINDS) do
            local ok, v = pcall(dfhack.units[k[1]], u)
            if ok and v then return k[2] end
        end
    end
    for _, u in ipairs(report_units()) do
        if dfhack.units.isActive(u) and not dfhack.units.isDead(u) then
            local citizen = dfhack.units.isCitizen(u, true)
            if citizen then
                local okb, vamp = pcall(dfhack.units.isBloodsucker, u)
                local okn, were = pcall(dfhack.units.isNightCreature, u)
                local kind = (okb and vamp) and 'vampire' or ((okn and were) and 'werebeast') or nil
                if kind then
                    table.insert(out.cursed, {id = u.id, name = txt(dfhack.units.getReadableName(u)), kind = kind})
                end
            elseif not dfhack.units.isHidden(u) then
                local kind = kind_of(u)
                local caged_ = u.flags1.caged or u.flags1.chained
                -- (0.104.138, 12j) every loose one listed (20 caged beasts hid
                -- the rest before), and the count in full
                if kind then out.dangers_total = (out.dangers_total or 0) + 1 end
                if kind and (#out.dangers < 20 or not caged_) then
                    local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                    local g = dfhack.maps.getWalkableGroup(pos)
                    table.insert(out.dangers, {id = u.id, name = txt(dfhack.units.getReadableName(u)), kind = kind,
                                               layer = layer_at(pos, layers),
                                               can_reach_dwarves = (g ~= 0) and (groups[g] == true) or nil,
                                               caged = (u.flags1.caged or u.flags1.chained) or nil})
                end
            else
                -- (item7) a great danger on tiles the fort hasn't seen yet (DF
                -- announced its coming): kept apart, never read as seen. B (24
                -- Nov): three forgotten beasts, all hidden, so `dangers` was empty
                -- and a seal would have been opened "no beast left" with them below
                local kind = kind_of(u)
                if kind and not (u.flags1.caged or u.flags1.chained) and #(out.unseen or {}) < 10 then
                    local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                    local g = dfhack.maps.getWalkableGroup(pos)
                    local okf, fl = pcall(function() return u.enemy.caste_flags.FLIER end)
                    out.unseen = out.unseen or {}
                    table.insert(out.unseen, {id = u.id, name = txt(dfhack.units.getReadableName(u)), kind = kind,
                                              layer = layer_at(pos, layers),
                                              can_reach_dwarves = (g ~= 0) and (groups[g] == true) or nil,
                                              flier = (okf and fl) and true or nil})
                end
            end
        end
    end
    return out
end

local function can_fly(u)
    local ok, flier = pcall(function() return u.enemy.caste_flags.FLIER end)
    return ok and flier or false
end

function get_others_on_map()
    local out = {
        threats = {},
        threats_that_can_reach_dwarves = 0,
        contained_dangers = 0, -- caged or chained, so not a live threat
        visitors = 0, merchants = 0, diplomats = 0, tame_animals = 0,
    }
    local cit_pos, cit_groups = citizen_positions()
    local layers = get_layers()
    -- (0.104.140) the trade depot: a threat near it while a caravan is in
    -- (merchants have no walls; the walk groups say nothing of them)
    local depot
    pcall(function()
        local d = df.global.world.buildings.other.TRADE_DEPOT[0]
        if d then depot = {x = d.centerx, y = d.centery, z = d.z} end
    end)
    local okb, builder = pcall(reqscript, 'ai-builder')       -- (0.104.153) once, not per creature
    HOSTILE_WILD = (okb and builder and builder.hostile_wild) or function() return false end
    local okt, TF = pcall(reqscript, 'ai-threat-facts')     -- (0.105.45) a threat's attacks, breath, armour...
    if not okt then TF = nil end
    local okth, TH = pcall(reqscript, 'ai-threats')         -- (0.105.51) thieves marked
    if not okth then TH = nil end
    for _, u in ipairs(report_units()) do
        if dfhack.units.isActive(u) and not dfhack.units.isDead(u)
                and not dfhack.units.isHidden(u)
                and not dfhack.units.isCitizen(u, true) then
            local contained = u.flags1.caged or u.flags1.chained
            -- (r1 g7) a visitor turned killer (or a hero spotted after an
            -- artifact) is a threat though DF doesn't call it a danger yet
            local turned = false
            if TH and TH.is_turned and not dfhack.units.isDanger(u) then
                local okt2, yes = pcall(TH.is_turned, u)
                turned = okt2 and yes == true
            end
            if (dfhack.units.isDanger(u) or turned) and contained then
                out.contained_dangers = out.contained_dangers + 1
            elseif dfhack.units.isDanger(u) or turned then
                local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                local group = dfhack.maps.getWalkableGroup(pos)
                -- true / false, or nil when DF's path data can't say
                -- (the unit is in water, in the air, or on an unwalkable tile).
                -- false means "probably can't WALK to them": DF's walk groups
                -- ignore climbing, swimming and building destroyers, and only
                -- update while the game is unpaused. Not a guarantee of safety.
                local reach = nil
                if group ~= 0 then reach = cit_groups[group] == true end
                local flier = can_fly(u)
                local dist, dz = nearest(pos, cit_pos)
                if reach then
                    out.threats_that_can_reach_dwarves = out.threats_that_can_reach_dwarves + 1
                end
                local kinds = {}
                for _, f in ipairs({'ForgottenBeast', 'Undead', 'Megabeast', 'SemiMegabeast', 'NightCreature', 'Titan', 'Demon'}) do
                    local okk, yes = pcall(function() return dfhack.units['is' .. f](u) end)
                    if okk and yes then table.insert(kinds, f) end
                end
                table.insert(out.threats, {
                    id = u.id,
                    name = txt(dfhack.units.getReadableName(u)),
                    kinds = #kinds > 0 and kinds or nil,
                    great_danger = dfhack.units.isGreatDanger(u),
                    invader = dfhack.units.isInvader(u),
                    turned = turned or nil,     -- (r1 g7) a visitor turned killer
                    visitor = (function() local okv, v = pcall(dfhack.units.isVisitor, u)
                                   return (okv and v) and true or nil end)(),
                    -- (0.105.48, K1) an animal (DF agitates wild ones: a falcon, a
                    -- wolf) is wildlife to the brain's triage, not an enemy: no
                    -- fort-wide alarm or gates for a small one, a hunting squad
                    animal = (function() local oka, v = pcall(dfhack.units.isAnimal, u)
                                  return (oka and v) and true or nil end)(),
                    agitated = (function() local oka, v = pcall(dfhack.units.isAgitated, u)
                                    return (oka and v) and true or nil end)(),
                    pos = pos,
                    -- (0.104.118) its body size (a dwarf is about 60,000), to weigh
                    -- it against the squads (fight or hide)
                    size = (function() local oks, v = pcall(function() return u.body.size_info.size_cur end)
                                return oks and v or nil end)(),
                    layer = layer_at(pos, layers),
                    can_reach_dwarves = reach,
                    flier = flier,
                    -- (0.104.139, phase 11) what size alone doesn't say: breath,
                    -- dust, webs and the like (its caste's interactions), and
                    -- whether it breaks buildings (a door doesn't hold it)
                    abilities = (function()
                        local okc, n = pcall(function()
                            return #df.creature_raw.find(u.race).caste[u.caste].body_info.interactions
                        end)
                        return (okc and n and n > 0) and n or nil
                    end)(),
                    destroyer = (function()
                        local okc, v = pcall(function()
                            local c = df.creature_raw.find(u.race).caste[u.caste]
                            return (c.misc.buildingdestroyer or 0) > 0     -- (review: a misc field, not a flag)
                        end)
                        return (okc and v) and true or nil
                    end)(),
                    levels_from_nearest_dwarf = dz,
                    distance_to_nearest_dwarf = dist,
                    depot_distance = depot and (math.abs(pos.x - depot.x) + math.abs(pos.y - depot.y)
                                                + 3 * math.abs(pos.z - depot.z)) or nil,
                })
                if TF then pcall(TF.add_facts, out.threats[#out.threats], u) end   -- (0.105.45) for the matchup
                -- (0.105.51) a thief or snatcher marked here too (the pulse has no
                -- threats section: E's spotted artifact seekers got the whole
                -- defence), with the crowd round them (no squad into a full tavern)
                if TH then
                    pcall(function()
                        local row = out.threats[#out.threats]
                        local kind = TH.unit_thief_kind(u)
                        if kind then
                            row.thief = kind
                            row.crowd, row.location = TH.crowd_of(u, report_units())
                        end
                    end)
                end
            elseif (function()                          -- (0.104.153) hostile wild animals in the caverns
                        local okh, h = pcall(function() return HOSTILE_WILD(u) end)
                        if not (okh and h) or contained then return false end
                        local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                        local layer = layer_at(pos, layers)
                        if not tostring(layer or ''):find('^Cavern') then return false end
                        out.wild_hostile_total = (out.wild_hostile_total or 0) + 1
                        out.wild_hostile = out.wild_hostile or {}
                        if #out.wild_hostile < 60 then
                            table.insert(out.wild_hostile, {id = u.id, name = txt(dfhack.units.getReadableName(u)),
                                                            pos = pos, layer = layer, flier = can_fly(u) or nil})
                        end
                        return true
                    end)() then
                -- counted above
            elseif dfhack.units.isMerchant(u) then
                out.merchants = out.merchants + 1
            elseif dfhack.units.isDiplomat(u) then
                out.diplomats = out.diplomats + 1
            elseif dfhack.units.isVisitor(u) then
                out.visitors = out.visitors + 1
            elseif dfhack.units.isAnimal(u) and dfhack.units.isFortControlled(u) then
                out.tame_animals = out.tame_animals + 1
            end
        elseif dfhack.units.isActive(u) and not dfhack.units.isDead(u) and dfhack.units.isHidden(u) and not dfhack.units.isCitizen(u, true)
                and not (u.flags1.caged or u.flags1.chained) and dfhack.units.isGreatDanger(u) then
            -- (item16) a great beast on unrevealed tiles: B's flier Urnut left the
            -- threats on alternate pulses (flying over unseen cavern), and the shaft
            -- guard opened the wells "no danger near"; deep.unseen is in the full report only
            out.hidden_great = out.hidden_great or {}
            if #out.hidden_great < 10 then
                local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                table.insert(out.hidden_great, {id = u.id, name = txt(dfhack.units.getReadableName(u)),
                    pos = pos, layer = layer_at(pos, layers), flier = can_fly(u) or nil})
            end
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Where the dwarves are, nobles and their mandates
---------------------------------------------------------------------------

function get_dwarf_levels()
    local zmin, zmax, by_layer, outside, n = nil, nil, {}, 0, 0
    local layers = get_layers()
    for _, u in ipairs(report_citizens()) do
        local z = u.pos.z
        zmin = math.min(zmin or z, z)
        zmax = math.max(zmax or z, z)
        inc(by_layer, layer_at(u.pos, layers) or 'unknown')
        -- (0.103.19) citizens out under the sky (Sky-reachers)
        n = n + 1
        pcall(function()
            local des = dfhack.maps.getTileFlags(u.pos)
            if des and des.outside then outside = outside + 1 end
        end)
    end
    return {z_top = zmax, z_bottom = zmin, by_layer = by_layer, outside = outside, citizens = n}
end

function get_nobles()
    local out = {}
    for _, u in ipairs(report_citizens()) do
        local positions = dfhack.units.getNoblePositions(u)
        if positions then
            for _, p in ipairs(positions) do
                table.insert(out, {position = p.position.code, unit_id = u.id,
                                   name = txt(dfhack.units.getReadableName(u, true))})
            end
        end
    end
    return out
end

function get_mandates()
    local out = {}
    for _, m in ipairs(df.global.world.mandates.all) do
        local mat = dfhack.matinfo.decode(m.mat_type, m.mat_index)
        table.insert(out, {
            kind = df.mandate_type[m.mode] or tostring(m.mode),
            by = m.unit and txt(dfhack.units.getReadableName(m.unit, true)) or nil,
            item = df.item_type[m.item_type] or tostring(m.item_type),
            -- which kind exactly, e.g. ITEM_SHOES_SHOES vs ITEM_SHOES_BOOTS
            subtype = (function()
                if m.item_subtype < 0 then return nil end
                local def = dfhack.items.getSubtypeDef(m.item_type, m.item_subtype)
                return def and def.id or nil
            end)(),
            material = mat and txt(mat:toString()) or nil,
            -- a specific stone can be passed straight to a stone recipe
            material_token = mat and mat:getToken() or nil,
            material_is_stone = (mat and mat.mode == 'inorganic'
                and mat.material.flags.IS_STONE) and true or false,
            remaining = m.amount_remaining,
            total = m.amount_total,
            -- timeout_counter counts once per 10 ticks
            days_left = math.max(0, (m.timeout_limit - m.timeout_counter) * 10 // TICKS_PER_DAY),
        })
    end
    return out
end

-- (0.101.6) Why orders don't start: the manager, his job, his office and its
-- furniture, and each workshop's order settings (the order_desk section).
function get_order_desk()
    local out = {offices = {}, workshops = {}, manage_jobs = 0}
    local mgr
    for _, u in ipairs(report_units()) do
        if dfhack.units.isCitizen(u) then
            for _, np in ipairs(dfhack.units.getNoblePositions(u) or {}) do
                if np.position.code == 'MANAGER' then mgr = u end
            end
        end
    end
    if mgr then
        local j = mgr.job.current_job
        out.manager = {id = mgr.id, job = j and df.job_type[j.job_type] or nil,
                       squad = mgr.military.squad_id ~= -1 or nil,
                       pos = {mgr.pos.x, mgr.pos.y, mgr.pos.z}}
    end
    for _, z in ipairs(df.global.world.buildings.other.ZONE_OFFICE) do
        local furn = {}
        for _, b in ipairs(z.contained_buildings) do
            local t = df.building_type[b:getType()]
            furn[t] = (furn[t] or 0) + (b:getBuildStage() >= b:getMaxBuildStage() and 1 or 0)
        end
        table.insert(out.offices, {id = z.id, owner = z.assigned_unit_id,
            manager_owns = mgr and z.assigned_unit_id == mgr.id or nil, built = furn,
            active = z.spec_sub_flag and z.spec_sub_flag.active or nil})
    end
    -- (0.104.21) where a workshop is and whether the dwarves can reach it,
    -- its skill limits (Enxah's masons took no job from a coffin and a
    -- block order for two game months, 168 boulders about)
    local from = citizen_anchor()
    local groups = citizen_walk_groups()
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        local pr = b.profile
        local e = {id = b.id, type = df.workshop_type[b.type],
            max_orders = pr.max_general_orders, blocked = pr.flags.block_general_orders or nil,
            workers = #pr.permitted_workers, jobs = #b.jobs,
            built = b:getBuildStage() >= b:getMaxBuildStage(),
            pos = {b.centerx, b.centery, b.z}}
        pcall(function()
            if pr.min_level and pr.min_level > 0 then e.min_level = pr.min_level end
            if pr.max_level and pr.max_level < 3000 then e.max_level = pr.max_level end
        end)
        pcall(function()
            if groups then
                -- (0.105.48, A2-1) out of reach of every citizen's walk group
                local ok = false
                for dy = -2, 2 do for dx = -2, 2 do
                    if not ok then
                        local g = dfhack.maps.getWalkableGroup(xyz2pos(b.centerx + dx, b.centery + dy, b.z))
                        if g and groups[g] then ok = true end
                    end
                end end
                if not ok then e.unreachable = true end
            elseif from then
                local ok = false
                for dy = -2, 2 do for dx = -2, 2 do
                    if not ok and dfhack.maps.canWalkBetween(from, xyz2pos(b.centerx + dx, b.centery + dy, b.z)) then ok = true end
                end end
                if not ok then e.unreachable = true end
            end
        end)
        -- (0.104.23) the jobs at the masons' and carpenters': what, suspended,
        -- who is on it (Enxah's coffins: 5 put on the bench, none taken up)
        pcall(function()
            local t = df.workshop_type[b.type]
            -- (0.104.33) and any workshop holding 5+ jobs (the craftsdwarf's
            -- held 7 each while 21 dwarves badly wanted to craft)
            -- (0.104.74) and any workshop with a custom-reaction job nobody works
            -- (Enxah: instrument jobs at three craftsdwarf's benches, untaken)
            local idle_reaction = false
            for _, j in ipairs(b.jobs) do
                if j.reaction_name and j.reaction_name ~= '' and not dfhack.job.getWorker(j) then idle_reaction = true end
            end
            if t == 'Masons' or t == 'Carpenters' or #b.jobs >= 5 or idle_reaction then
                e.job_list = {}
                for _, j in ipairs(b.jobs) do
                    local w = dfhack.job.getWorker(j)
                    local entry = {type = df.job_type[j.job_type], suspended = j.flags.suspend or nil,
                                   worker = w and w.id or nil,
                                   order = (j.order_id ~= -1) and j.order_id or nil}
                    pcall(function()        -- (0.104.33) a custom reaction's name, a do-now flag
                        if j.reaction_name and j.reaction_name ~= '' then entry.reaction = j.reaction_name end
                        if j.flags['do_now'] then entry.do_now = true end
                    end)
                    -- (0.104.74) what the job still needs: each requirement's item
                    -- type, material, count and how many items are on it
                    pcall(function()
                        if #j.job_items > 0 then
                            entry.needs = {}
                            for _, ji in ipairs(j.job_items) do
                                local mi = (ji.mat_type ~= -1) and dfhack.matinfo.decode(ji.mat_type, ji.mat_index)
                                table.insert(entry.needs, ('%s%s x%d'):format(df.item_type[ji.item_type] or 'any',
                                    mi and (' ' .. mi:getToken()) or '', ji.quantity))
                            end
                            entry.has_items = #j.items
                        end
                    end)
                    table.insert(e.job_list, entry)
                end
            end
        end)
        table.insert(out.workshops, e)
    end
    -- (0.104.23) who may do masonry and carpentry
    pcall(function()
        -- (0.104.34) jobs left on the benches by orders that are gone
        -- (cancelled as stuck: DF keeps their jobs), never worked
        pcall(function() out.orphan_jobs = orphan_jobs(true) end)
        out.labor_holders = {}
        -- (0.104.73) and the crafts (instrument and craft jobs sat unworked
        -- on every craftsdwarf's bench): holders, and those free (no job, not a soldier)
        out.labor_free = {}
        local citizens = report_citizens(true)     -- (13c) once, not once a labour
        for _, name in ipairs({'MASON', 'CARPENTER', 'STONECUTTER', 'WOOD_CRAFT', 'STONE_CRAFT', 'BONE_CARVE',
                               'METAL_CRAFT', 'GLASSMAKER', 'MECHANIC', 'FORGE_WEAPON'}) do   -- (x4) the arming hold's smith
            local lab, n, free = df.unit_labor[name], 0, 0
            if lab then
                for _, u in ipairs(citizens) do
                    if u.status.labors[lab] then
                        n = n + 1
                        if not u.job.current_job and u.military.squad_id == -1 then free = free + 1 end
                    end
                end
                out.labor_holders[name] = n
                out.labor_free[name] = free
            end
        end
    end)
    -- (0.101.6) the game's own list of who manages production (DF's
    -- nobles screen fills it; a hand-written appointment may not)
    pcall(function()
        local ent = df.historical_entity.find(df.global.plotinfo.group_id)
        out.manage_production = {}
        for _, a in ipairs(ent.assignments_by_type.MANAGE_PRODUCTION) do
            table.insert(out.manage_production, {assignment = a.id, histfig = a.histfig, histfig2 = a.histfig2})
        end
        out.manager_hf = mgr and mgr.hist_figure_id or nil
        out.positions = {}
        for _, a in ipairs(ent.positions.assignments) do
            if a.histfig ~= -1 then table.insert(out.positions, {a.id, a.position_id, a.histfig, a.histfig2}) end
        end
    end)
    for _, j in utils.listpairs(df.global.world.jobs.list) do
        if j.job_type == df.job_type.ManageWorkOrders then out.manage_jobs = out.manage_jobs + 1 end
    end
    return out
end

---------------------------------------------------------------------------
-- Event feed. DFHack's eventful plugin calls these handlers as things
-- happen; they queue events until the AI collects them with
-- `ai-bridge events`. Globals, so the queue survives between script runs.
---------------------------------------------------------------------------

EVENT_QUEUE = EVENT_QUEUE or {}
local MAX_QUEUED_EVENTS = 300
local WATCH_KEY = 'ai-overseer'

function push_event(ev)
    ev.year, ev.tick = df.global.cur_year, df.global.cur_year_tick
    table.insert(EVENT_QUEUE, ev)
    while #EVENT_QUEUE > MAX_QUEUED_EVENTS do table.remove(EVENT_QUEUE, 1) end
end

local function describe_unit(id)
    local u = df.unit.find(id)
    if not u then return {unit_id = id} end
    -- where it is (for a death, where it died); -30000 means nowhere
    local x, y, z
    local okp, px, py, pz = pcall(function() return u.pos.x, u.pos.y, u.pos.z end)
    if okp and type(px) == 'number' and px >= 0 then x, y, z = px, py, pz end
    return {
        unit_id = id, x = x, y = y, z = z,
        name = txt(dfhack.units.getReadableName(u)),
        own_civ = dfhack.units.isOwnCiv(u),
        hostile = dfhack.units.isDanger(u),
        animal = dfhack.units.isAnimal(u),
        -- forgotten beasts, titans, megabeasts (not "Giant Dragonfly")
        great = dfhack.units.isGreatDanger(u),
    }
end

-- (0.104.100) What killed it, from DF's incident (the overnight review of 26
-- Oct: 15 dwarves died in 50 s and the log couldn't say how): the cause
-- (DROWN, STRUCK_DOWN, THIRST...), the killer's name and kind (a citizen, a
-- ghost, a beast, an animal, an outsider), and `again` when this unit's death
-- was already told (a ghost laid to rest dies a second time).
DEATHS_TOLD = DEATHS_TOLD or {}
OLD_DEATH_TICKS = 1200   -- (item3) a death older than a day when told was told before
function death_details(ev, id)
    local u = df.unit.find(id)
    if not u then return end
    if DEATHS_TOLD[id] then ev.again = true end
    DEATHS_TOLD[id] = true
    pcall(function() if dfhack.units.isGhost(u) then ev.ghost = true end end)
    local inc = df.incident.find(u.counters.death_id)
    if not inc then return end
    -- (item3) a death that happened more than a day before it is told is
    -- `again` too: a ghost laid to rest dies a second time, and DEATHS_TOLD
    -- is lost when DF restarts. F (13 Nov): after the 08:00-10:57 restarts,
    -- 28 of the titan's 42 victims (y257) were told as fresh "bleed" deaths,
    -- one at a time over 11 hours, each the second its ghost was put to rest
    -- (read as a killer among the citizens; and counted as new deaths)
    pcall(function()
        local y, t = inc.event_year, inc.event_time
        if type(y) == 'number' and type(t) == 'number' and y >= 0 and t >= 0
                and abs_tick() - (y * 403200 + t) > OLD_DEATH_TICKS then
            ev.again, ev.old_death = true, true
        end
    end)
    ev.cause = df.death_type[inc.death_cause] or tostring(inc.death_cause)
    -- (0.104.139) how far the fight had gone (Brawl, Lethal, NoQuarter), and
    -- whether the dead was a patient: what each killing was
    pcall(function() ev.conflict = df.conflict_level[inc.conflict_level] or tostring(inc.conflict_level) end)
    -- (0.104.150) a patient only when DF asks for a treatment (its rq_ flags);
    -- needs_healthcare alone is set for every infected dwarf walking about
    -- (Teacheroar: 91 of 162), so that is said as `infected`
    pcall(function()
        if not (u.health and u.health.flags.needs_healthcare) then return end
        for _, k in ipairs(HEALTH_RQ) do
            if u.health.flags[k] then ev.patient = true return end
        end
        ev.infected = true
    end)
    -- (0.104.148) the victim's own mood: a melancholy or raving dwarf stops
    -- drinking (Teacheroar's 4 thirst deaths overnight, with 1,348 drinks
    -- in store, were no patients); a strange mood too
    pcall(function()
        local m = u.mood and u.mood >= 0 and df.mood_type[u.mood]
        if m then ev.mood = tostring(m) end
    end)
    local k = inc.criminal ~= -1 and df.unit.find(inc.criminal) or nil
    if k then
        ev.killer = txt(dfhack.units.getReadableName(k))
        ev.killer_id = k.id
        pcall(function()
            local m = df.soldier_mood_type and df.soldier_mood_type[k.counters.soldier_mood]
            if m and m ~= 'None' then ev.killer_mood = m end
        end)
        local okg, ghost = pcall(dfhack.units.isGhost, k)
        ev.killer_kind = (okg and ghost) and 'ghost'
            or dfhack.units.isGreatDanger(k) and 'great beast'
            or (dfhack.units.isCitizen(k) or dfhack.units.isOwnCiv(k)) and 'citizen'
            or dfhack.units.isAnimal(k) and 'animal'
            or 'outsider'
        -- (0.105.24) which outsider: a visitor (DF's guest flag; the 2-5 Nov
        -- "outsider" killers were mostly artifact thieves who had come as
        -- visitors and asked the mayor for a meeting), or one dead already
        -- (an old wound: F's farmer suffocated in the hospital 3 years after
        -- the goblin dancer who wounded her died)
        pcall(function() if dfhack.units.isVisitor(k) then ev.killer_visitor = true end end)
        pcall(function() if dfhack.units.isDead(k) then ev.killer_dead = true end end)
        -- (0.105.47, R2 item 3) what the killer was in: DF's conflict level
        -- read "None" on every death of the run (I7c), so a tantrum (in one, or
        -- one begun in the last 2 days by the ledger), berserk or possessed
        -- killer is marked (kill_kind; and as the conflict when DF gives none),
        -- and where the killer stood, so tantrum beatings and berserkers part
        pcall(function()
            local kind = reqscript('ai-tantrums').kill_kind(k, abs_tick())
            if kind then
                ev.kill_kind = kind
                if ev.conflict == nil or ev.conflict == 'None' then
                    ev.conflict_df = ev.conflict
                    ev.conflict = kind:sub(1, 1):upper() .. kind:sub(2)
                end
            end
        end)
        -- (0.105.99) a calm killer in a fight the victim was drawn into (the
        -- victim's Conflict / JoinConflict thoughts): a brawl, and whose
        -- tantrum it grew from (E, 23 Nov: two patients "suffocated by" a
        -- miner and an axedwarf who had joined the fight round a tantrum)
        -- (0.105.99, verifier) a citizen killer only: a dwarf in a fight with an
        -- invader or a beast carries the same thoughts, and that is no brawl
        if ev.kill_kind == nil and ev.killer_kind == 'citizen' then
            pcall(function()
                local kind, from = reqscript('ai-tantrums').fight_of(u, abs_tick())
                if not kind then return end
                ev.kill_kind = kind
                if ev.conflict == nil or ev.conflict == 'None' then
                    ev.conflict_df = ev.conflict
                    ev.conflict = 'Brawl'
                end
                local t = from and df.unit.find(from)
                if t and t.id ~= k.id then
                    ev.brawl_tantrum_id = t.id
                    ev.brawl_tantrum = txt(dfhack.units.getReadableName(t))
                end
            end)
        end
        pcall(function()
            if k.pos.x >= 0 then ev.killer_x, ev.killer_y, ev.killer_z = k.pos.x, k.pos.y, k.pos.z end
        end)
    end
end

-- (0.105.15) An invasion event's size: the invaders on the map now (alive,
-- active) and, read field by field so a DF change can't break it, the
-- record's size and siege flag (kept for a later look, not acted on).
function invasion_details(ev, id)
    local n = 0
    for _, u in ipairs(report_units()) do
        local ok, yes = pcall(function()
            return dfhack.units.isInvader(u) and dfhack.units.isActive(u) and not dfhack.units.isDead(u)
        end)
        if ok and yes then n = n + 1 end
    end
    ev.invaders_now = n
    for _, v in ipairs(df.global.plotinfo.invasions.list) do
        if v.id == id then
            pcall(function() ev.civ_id = v.civ_id end)
            pcall(function() ev.size = v.size end)
            pcall(function() ev.siege = v.flags.siege and true or false end)
            break
        end
    end
end

function start_watching()
    local ok, eventful = pcall(require, 'plugins.eventful')
    if not ok then return false end
    eventful.enableEvent(eventful.eventType.UNIT_DEATH, 10)
    eventful.enableEvent(eventful.eventType.UNIT_NEW_ACTIVE, 50)
    eventful.enableEvent(eventful.eventType.INVASION, 50)
    eventful.onUnitDeath[WATCH_KEY] = function(id)
        local ev = describe_unit(id)
        ev.kind = 'death'
        pcall(death_details, ev, id)
        -- (r1 g7) a visitor who killed one of the fort's own: a target (ai-threats TURNED)
        pcall(function() reqscript('ai-threats').note_death(ev) end)
        push_event(ev)
    end
    eventful.onUnitNewActive[WATCH_KEY] = function(id)
        -- Only arrivals that matter to an overseer: your own civ (migrants,
        -- births) and anything dangerous. Wildlife and caravan animals would
        -- crowd out more important events.
        local u = df.unit.find(id)
        if not u then return end
        if dfhack.units.isAnimal(u) and not dfhack.units.isDanger(u) then return end
        if not (dfhack.units.isOwnCiv(u) or dfhack.units.isDanger(u)
                or dfhack.units.isInvader(u)) then return end
        local ev = describe_unit(id)
        ev.kind = 'arrival'
        push_event(ev)
    end
    eventful.onInvasion[WATCH_KEY] = function(id)
        -- (0.105.15) DF makes an invasion for a lone thief too: say how many
        -- invaders are on the map now and what the record holds, so the brain
        -- calls it a siege only when an army came
        local ev = {kind = 'invasion', invasion_id = id}
        pcall(invasion_details, ev, id)
        push_event(ev)
    end
    -- Forget the previous fort's layers and events when a map unloads.
    dfhack.onStateChange[WATCH_KEY] = function(sc)
        if sc == SC_MAP_UNLOADED then
            LAYER_CACHE = nil
            EVENT_QUEUE = {}
            LAST_REPORT_ID = nil
            WATER_PLAN = nil           -- (0.104.81, 13c) a half-done cistern plan belongs to the fort unloaded
            DEATHS_TOLD = {}
            JUNCTIONS = {}
            -- (0.105.33) the fort's cached sections and its "has stairs" go with it
            SECTION_CACHE = {}
            FOUNDED_SITE, FOUNDED_NEAR = nil, nil
        end
    end
    -- Stamped with the bridge version, so an updated script re-registers
    -- its handlers instead of leaving the old ones running.
    WATCHING = BRIDGE_VERSION
    return true
end

function get_recent_announcements(n)
    local list = df.global.world.status.announcements
    local merged = {}
    for i = 0, #list - 1 do
        local r = list[i]
        if r.flags.continuation and #merged > 0 then
            merged[#merged].text = merged[#merged].text .. ' ' .. txt(r.text)
        else
            table.insert(merged, {
                text = txt(r.text),
                type = df.announcement_type[r.type] or tostring(r.type),
                year = r.year,
            })
        end
    end
    local out = {}
    for i = math.max(1, #merged - n + 1), #merged do
        table.insert(out, merged[i])
    end
    return out
end
