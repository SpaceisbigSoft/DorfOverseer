-- (item6) Prisoners' outcomes and necromancer sieges.
--
--   * captives: every creature sitting in a cage that is not the fort's own
--     (caught invaders, thieves and snatchers, wild beasts from the cage
--     traps), one row each with what the brain decides by (invader, thief,
--     great danger, wild, a trap's catch), the pit/pond zones (the AI's own,
--     "AI pit", with the drop under it) and the player's (counted, never
--     used: they are the player's);
--   * make_pit: the AI's own pit zone, placed over a drop that is already
--     there (an open-space tile beside a floor the dwarves walk, with at
--     least min_drop levels of open space straight under it, landing on dry
--     ground that is no cavern, no cistern and no well), near the dwarves.
--     Nothing is dug: a fort with no such drop keeps its prisoners;
--   * pit_prisoners: caged prisoners assigned to that pit, as DF's own
--     Pit/Pond screen does (the zone lists the unit, the unit points at the
--     zone: the same links the pastures use, ai-society.pasture). The
--     dwarves then carry each one to the edge and drop it in: DF's way of
--     putting a prisoner to death. The cage is left empty, and the game
--     loads an empty cage back into its trap (LoadCageTrap) by itself;
--   * necro: a necromancer siege's facts: the walking dead on the map and
--     how many are invaders or can reach the dwarves, the raisers among the
--     living (a unit whose own interactions include one that animates the
--     dead), bodies and parts lying outside while the dead are about, and
--     the necromancer towers near the fort on the world map (cached per world).
--
-- DFHack offers no way to let a prisoner out of a cage short of rewriting
-- the unit's and the cage's links by hand, and an invader let out walks
-- straight back to fight: "release" is never done here (the brain says so).
-- Fields this module isn't sure of are read inside pcall (needs an in-game
-- look: civzone_type Pit/Pond as ZONE_PIT_POND, unit.curse.own_interaction,
-- interaction effects' ANIMATE type, world_site_type Tower).
--@module = true

local U = reqscript('ai-util')
local utils = require('utils')

PIT_NAME = 'AI pit'
PIT_MIN_DROP = 6          -- levels of open space under the pit (the brain sends its own, pit_min_drop)
PIT_RADIUS = 25           -- tiles round the dwarves searched for a drop
PIT_LEVELS = 3            -- the busiest levels searched
PIT_BATCH = 5             -- prisoners assigned a call at most
MAX_ROWS = 30
CORPSE_MAX = 3000         -- bodies and parts read at most a report
TOWER_NEAR = 40           -- world tiles: towers this close are listed
TOWER_ROWS = 3
local THIEF_PROFS = {THIEF = 'thief', MASTER_THIEF = 'thief', SNATCHER = 'snatcher'}

local function report_units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end

local function report_citizens()
    if U.REPORT_CTX and U.citizens then return U.citizens(true) end
    return dfhack.units.getCitizens(true)
end

local function is(fn, u)
    local ok, v = pcall(fn, u)
    return ok and v or false
end

local function name_of(u, txt)
    local ok, n = pcall(function() return (txt or tostring)(dfhack.units.getReadableName(u)) end)
    return ok and n or ('unit ' .. tostring(u.id))
end

local function shape_at(x, y, z)
    local ok, s = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        if not tt then return nil end
        return df.tiletype_shape[df.tiletype.attrs[tt].shape]
    end)
    return ok and s or nil
end

local function flags_at(x, y, z)
    local ok, f = pcall(dfhack.maps.getTileFlags, x, y, z)
    return ok and f or nil
end

local function outside_at(x, y, z)
    local f = flags_at(x, y, z)
    return f and f.outside and true or false
end

-- --- captives ----------------------------------------------------------------------

local function great(u)
    for _, f in ipairs({'isForgottenBeast', 'isTitan', 'isMegabeast', 'isDemon', 'isGreatDanger'}) do
        if dfhack.units[f] and is(dfhack.units[f], u) then return true end
    end
    return false
end

local function thief_of(u)
    local ok, prof = pcall(function() return df.profession[u.profession] end)
    return ok and THIEF_PROFS[prof] or nil
end

local function intelligent(u)
    local ok, yes = pcall(function()
        local f = df.creature_raw.find(u.race).caste[u.caste].flags
        return f.CAN_SPEAK or f.CAN_LEARN
    end)
    return ok and yes and true or false
end

-- the zone a unit is assigned to (pasture, pit), or nil
local function zone_of(u)
    local ok, id = pcall(function()
        local ref = dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED)
        return ref and ref.building_id or nil
    end)
    return ok and id or nil
end

-- A creature in a cage that is not the fort's: not a citizen, not the
-- fort's own tame animal, not a merchant, visitor or diplomat.
function is_prisoner(u)
    if not u.flags1.caged or is(dfhack.units.isDead, u) then return false end
    if is(dfhack.units.isCitizen, u) then return false end
    if is(dfhack.units.isMerchant, u) or is(dfhack.units.isVisitor, u) or is(dfhack.units.isDiplomat, u) then
        return false
    end
    if is(dfhack.units.isTame, u) and is(dfhack.units.isOwnCiv, u) then return false end
    return true
end

function prisoner_row(u, txt)
    local row = {id = u.id, name = name_of(u, txt)}
    pcall(function() row.race = df.creature_raw.find(u.race).creature_id end)
    row.invader = is(dfhack.units.isInvader, u) or nil
    row.danger = is(dfhack.units.isDanger, u) or nil
    row.great = great(u) or nil
    row.thief = thief_of(u)
    row.intelligent = intelligent(u) or nil
    row.zone = zone_of(u)
    pcall(function()
        local cage = dfhack.units.getContainer(u)
        if not cage then return end
        if cage.flags.in_building then row.trap = true end
        local x, y, z = dfhack.items.getPosition(cage)
        if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
        if x then row.outside = outside_at(x, y, z) or nil end
    end)
    return row
end

-- the walk groups the citizens stand in (a landing in one of them would let
-- a prisoner who lived through the fall walk back into the fort)
function citizen_groups()
    local g = {}
    for _, u in ipairs(report_citizens()) do
        local ok, w = pcall(dfhack.maps.getWalkableGroup, xyz2pos(u.pos.x, u.pos.y, u.pos.z))
        if ok and w and w ~= 0 then g[w] = true end
    end
    return g
end

-- open space straight under (x, y, z) down to a landing: how many levels,
-- and whether the fall is clean (no water, no cavern, no cistern, the
-- landing solid and in no citizen's walk group)
function drop_below(x, y, z, cistern, groups)
    local n = 0
    local zz = z - 1
    while zz >= 0 and n < 60 do
        local f = flags_at(x, y, zz)
        if not f then return n, false end
        if f.feature_global or f.feature_local then return n, false end      -- a cavern below
        if cistern and cistern[x .. ',' .. y .. ',' .. zz] then return n, false end
        local s = shape_at(x, y, zz)
        if s ~= 'EMPTY' then
            -- the landing: deep water breaks the fall (and a cistern or well drinks it)
            if (f.flow_size or 0) > 0 and not f.liquid_type then return n, false end
            if s == nil or s == 'WALL' then return n, false end
            if groups then
                local ok, w = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, zz))
                if ok and w and w ~= 0 and groups[w] then return n, false end
            end
            return n, true
        end
        if (f.flow_size or 0) > 0 and not f.liquid_type then return n, false end
        n = n + 1
        zz = zz - 1
    end
    return n, false
end

local function pit_zones()
    local list = {}
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_PIT_POND) do table.insert(list, z) end
    end)
    return list
end

local function is_ai_pit(z)
    local ok, n = pcall(function() return tostring(z.name) end)
    return ok and n == PIT_NAME
end

function ai_pit()
    for _, z in ipairs(pit_zones()) do
        if is_ai_pit(z) then return z end
    end
    return nil
end

local function pit_drop(z)
    local best = 0
    local cis = U.cistern_tiles and U.cistern_tiles() or {}
    local groups = citizen_groups()
    for y = z.y1, z.y2 do
        for x = z.x1, z.x2 do
            if shape_at(x, y, z.z) == 'EMPTY' then
                local n, clean = drop_below(x, y, z.z, cis, groups)
                if clean and n > best then best = n end
            end
        end
    end
    return best
end

function report(txt)
    local out = {caged = 0, list = {}, pits = {}, player_pits = 0}
    for _, u in ipairs(report_units()) do
        local okp, yes = pcall(is_prisoner, u)
        if okp and yes then
            out.caged = out.caged + 1
            if #out.list < MAX_ROWS then
                local okr, row = pcall(prisoner_row, u, txt)
                if okr then table.insert(out.list, row) end
            end
        end
    end
    for _, z in ipairs(pit_zones()) do
        if is_ai_pit(z) then
            local row = {id = z.id, x = z.x1, y = z.y1, z = z.z, assigned = 0}
            pcall(function() row.assigned = #z.assigned_units end)
            local okd, d = pcall(pit_drop, z)
            row.drop = okd and d or nil
            table.insert(out.pits, row)
        else
            out.player_pits = out.player_pits + 1
        end
    end
    return out
end

-- --- the AI's pit -------------------------------------------------------------------

-- where the dwarves are: the busiest levels inside, each with its median x, y
local function busy_levels()
    local byz = {}
    for _, u in ipairs(report_citizens()) do
        local x, y, z = u.pos.x, u.pos.y, u.pos.z
        if not outside_at(x, y, z) then
            byz[z] = byz[z] or {xs = {}, ys = {}, n = 0}
            local l = byz[z]
            l.n = l.n + 1
            table.insert(l.xs, x)
            table.insert(l.ys, y)
        end
    end
    local out = {}
    for z, l in pairs(byz) do
        table.sort(l.xs)
        table.sort(l.ys)
        table.insert(out, {z = z, n = l.n, x = l.xs[(#l.xs + 1) // 2], y = l.ys[(#l.ys + 1) // 2]})
    end
    table.sort(out, function(a, b) return a.n > b.n or (a.n == b.n and a.z > b.z) end)
    return out
end

local function walkable_floor(x, y, z)
    if shape_at(x, y, z) ~= 'FLOOR' then return false end
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    return ok and g and g ~= 0 or false
end

-- an open-space tile with a clean drop of min_drop levels or more under it
-- and a floor the dwarves walk beside it; inside before outside, nearest first
function find_drop(min_drop, radius)
    min_drop = min_drop or PIT_MIN_DROP
    radius = radius or PIT_RADIUS
    local cis = U.cistern_tiles and U.cistern_tiles() or {}
    local groups = citizen_groups()
    local best, best_score
    local levels = busy_levels()
    for i = 1, math.min(PIT_LEVELS, #levels) do
        local L = levels[i]
        for dy = -radius, radius do
            for dx = -radius, radius do
                local x, y, z = L.x + dx, L.y + dy, L.z
                if shape_at(x, y, z) == 'EMPTY' then
                    local f = flags_at(x, y, z)
                    local okb, b = pcall(function() return dfhack.buildings.findAtTile(xyz2pos(x, y, z)) end)
                    if f and not f.hidden and not (f.feature_global or f.feature_local) and (f.flow_size or 0) == 0
                            and not (okb and b) and not cis[x .. ',' .. y .. ',' .. z] then
                        local edge = false
                        for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
                            if walkable_floor(x + d[1], y + d[2], z) then edge = true break end
                        end
                        if edge then
                            local n, clean = drop_below(x, y, z, cis, groups)
                            if clean and n >= min_drop then
                                local score = math.max(math.abs(dx), math.abs(dy)) + (f.outside and 1000 or 0)
                                if not best_score or score < best_score then
                                    best, best_score = {x = x, y = y, z = z, drop = n, outside = f.outside or nil}, score
                                end
                            end
                        end
                    end
                end
            end
        end
    end
    return best
end

local function place_zone(spot, dry)
    local qf = reqscript('quickfort')
    local text = ('p{name="%s"}'):format(PIT_NAME)
    local ok, stats = pcall(qf.apply_blueprint, {mode = 'zone', data = {[spot.z] = {[spot.y] = {[spot.x] = text}}},
                                                 pos = {x = 0, y = 0, z = 0}, command = 'run', dry_run = dry})
    return ok and stats and stats.zone_designated and stats.zone_designated.value > 0
end

-- The AI's pit: the one there, or a new zone over a drop found near the dwarves.
function make_pit(opts, dry_run)
    opts = opts or {}
    local min_drop = tonumber(opts.min_drop) or PIT_MIN_DROP
    local have = ai_pit()
    if have then
        pcall(function() have.zone_settings.pond.flag.keep_filled = false end)   -- (merge) never a pond
        return {ok = true, existing = true, zone_id = have.id, x = have.x1, y = have.y1, z = have.z}
    end
    local spot = find_drop(min_drop, tonumber(opts.radius) or PIT_RADIUS)
    if not spot then
        return {ok = false, rejected = true, no_drop = true,
                error = ('no open drop of %d levels or more beside a floor near the dwarves (the AI digs none)'):format(min_drop)}
    end
    if not place_zone(spot, true) then
        return {ok = false, rejected = true, error = ('the game would not take a pit zone at x%d y%d z%d'):format(spot.x, spot.y, spot.z)}
    end
    local out = {ok = true, x = spot.x, y = spot.y, z = spot.z, drop = spot.drop, outside = spot.outside}
    if dry_run then out.dry_run = true return out end
    if not place_zone(spot, false) then return {ok = false, error = 'the game refused the pit zone'} end
    pcall(function()
        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(spot.x, spot.y, spot.z)) or {}) do
            if is_ai_pit(zn) then
                out.zone_id = zn.id
                -- (merge) quickfort's `p` zone is made with keep_filled on (a pond:
                -- DFHack 53.17-r1 zone.lua): a pit must stay dry
                pcall(function() zn.zone_settings.pond.flag.keep_filled = false end)
            end
        end
    end)
    return out
end

-- Caged prisoners into the AI's pit (ids from the brain, at most PIT_BATCH):
-- each still caged, a prisoner, no great danger, in no zone yet.
function pit_prisoners(opts, dry_run)
    opts = opts or {}
    local pit = ai_pit()
    if not pit then return {ok = false, rejected = true, error = 'the AI has no pit (make_pit first)'} end
    local min_drop = tonumber(opts.min_drop) or PIT_MIN_DROP
    local drop = pit_drop(pit)
    if drop < min_drop then
        return {ok = false, rejected = true, drop = drop,
                error = ('the AI pit drops %d level(s), under the %d it needs'):format(drop, min_drop)}
    end
    local max = math.min(tonumber(opts.max) or PIT_BATCH, PIT_BATCH)
    local done, skipped, ids = 0, {}, {}
    for _, id in ipairs(type(opts.ids) == 'table' and opts.ids or {}) do
        if done >= max then break end
        local u = df.unit.find(id)
        local why
        if not u then why = 'gone'
        elseif not is_prisoner(u) then why = 'not a caged prisoner'
        elseif great(u) then why = 'a great danger: kept caged'
        elseif zone_of(u) then why = 'already assigned to a zone'
        end
        if why then
            skipped[tostring(id)] = why
        else
            if not dry_run then
                utils.insert_sorted(pit.assigned_units, u.id)
                local ref = df.general_ref_building_civzone_assignedst:new()
                ref.building_id = pit.id
                u.general_refs:insert('#', ref)
            end
            done = done + 1
            table.insert(ids, u.id)
        end
    end
    if done == 0 then
        return {ok = false, rejected = true, error = 'no prisoner could go to the pit', skipped = skipped}
    end
    return {ok = true, assigned = done, ids = ids, pit_id = pit.id, drop = drop,
            skipped = next(skipped) and skipped or nil, dry_run = dry_run or nil}
end

-- --- necromancer sieges -----------------------------------------------------------------

-- a living unit that can raise the dead: one of its own interactions animates
local ANIMATE_MEMO = {}
local function animates(iid)
    if ANIMATE_MEMO[iid] ~= nil then return ANIMATE_MEMO[iid] end
    local ok, yes = pcall(function()
        local it = df.interaction.find(iid)
        if not it then return false end
        for _, e in ipairs(it.effects) do
            local t = e:getType()
            local name = df.interaction_effect_type and df.interaction_effect_type[t]
            if name == 'ANIMATE' then return true end
        end
        return false
    end)
    ANIMATE_MEMO[iid] = ok and yes or false
    return ANIMATE_MEMO[iid]
end

function is_raiser(u)
    if is(dfhack.units.isUndead, u) then return false end
    local ok, yes = pcall(function()
        for _, iid in ipairs(u.curse.own_interaction) do
            if animates(iid) then return true end
        end
        return false
    end)
    return ok and yes or false
end

local function surface_corpses()
    local n, read = 0, 0
    pcall(function()
        for _, kind in ipairs({'CORPSE', 'CORPSEPIECE'}) do
            for _, it in ipairs(df.global.world.items.other[kind]) do
                read = read + 1
                if read > CORPSE_MAX then return end
                local okp, x, y, z = pcall(dfhack.items.getPosition, it)
                if okp and x then
                    if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
                    if outside_at(x, y, z) then n = n + 1 end
                end
            end
        end
    end)
    return n
end

-- the necromancer towers near the fort (world tiles), kept for the world loaded
TOWER_MEMO = TOWER_MEMO or nil
function towers()
    local okk, key = pcall(function()
        return tostring(df.global.world.cur_savegame.save_dir) .. '#' .. #df.global.world.world_data.sites
    end)
    if okk and TOWER_MEMO and TOWER_MEMO.key == key then return TOWER_MEMO.list end
    local list = {}
    local ok = pcall(function()
        local sites = df.global.world.world_data.sites
        local fort = df.global.plotinfo.site_id
        local fx, fy
        for _, s in ipairs(sites) do
            if s.id == fort then fx, fy = s.pos.x, s.pos.y break end
        end
        if not fx then return end
        for _, s in ipairs(sites) do
            if df.world_site_type[s.type] == 'Tower' then
                local dx, dy = s.pos.x - fx, s.pos.y - fy
                local d = math.max(math.abs(dx), math.abs(dy))
                if d <= TOWER_NEAR then
                    local way = (dy < 0 and 'north' or dy > 0 and 'south' or '') .. (dx > 0 and 'east' or dx < 0 and 'west' or '')
                    local row = {id = s.id, dist = d, way = way ~= '' and way or 'here'}
                    pcall(function() row.name = dfhack.df2utf(dfhack.translation.translateName(s.name, true)) end)
                    table.insert(list, row)
                end
            end
        end
    end)
    table.sort(list, function(a, b) return a.dist < b.dist or (a.dist == b.dist and a.id < b.id) end)
    while #list > TOWER_ROWS do table.remove(list) end
    if okk and ok then TOWER_MEMO = {key = key, list = list} end
    return list
end

function necro(txt)
    local out = {undead = 0, undead_invaders = 0, raisers = {}, surface_corpses = 0}
    for _, u in ipairs(report_units()) do
        if is(dfhack.units.isActive, u) and not is(dfhack.units.isDead, u) and not u.flags1.caged
                and not is(dfhack.units.isCitizen, u) then
            if is(dfhack.units.isUndead, u) then
                out.undead = out.undead + 1
                if is(dfhack.units.isInvader, u) then out.undead_invaders = out.undead_invaders + 1 end
            elseif is_raiser(u) and #out.raisers < 5 then
                table.insert(out.raisers, {id = u.id, name = name_of(u, txt), invader = is(dfhack.units.isInvader, u) or nil,
                                           outside = outside_at(u.pos.x, u.pos.y, u.pos.z) or nil})
            end
        end
    end
    -- the bodies outside only while the dead (or a raiser) are about: a walk of the corpses
    if out.undead > 0 or #out.raisers > 0 then out.surface_corpses = surface_corpses() end
    local okt, tw = pcall(towers)
    out.towers = okt and tw or {}
    return out
end
