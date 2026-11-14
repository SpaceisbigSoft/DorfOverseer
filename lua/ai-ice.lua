-- (0.105.47, I7d 2f) Ice: the AI's water source zones on surface water taken
-- down before the freeze.
--
-- E (13 Nov): two citizens drowned in the surface pond at the AI's water
-- zone on the first day of winter; the zone was still there and the dwarves
-- filled buckets on the ice. The brain (brain/planner_ice.py) decides when
-- surface water counts as freezing (the last half-month of autumn, winter, or
-- a surface near freezing); this module only does what it is told:
--
--   retire(outside_only, dry_run)   the `retire_water_zones` action: each of
--       the AI's own water zones (ai-builder-farms keeps the water tile each
--       was made for in 'ai-overseer/water_zones') on an outside tile (or
--       every one, outside_only false) is taken down and dropped from the
--       record. Only a Water Source zone with the 3x3 the AI drew round that
--       tile: a zone the player drew is never touched. A record whose zone is
--       already gone is dropped too.
--
-- DF fields read inside pcall.
--@module = true

local U = reqscript('ai-util')

WATER_ZONES_KEY = 'ai-overseer/water_zones'     -- (ai-builder-farms' own key)

-- Pure: is this zone the AI's 3x3 round water tile (x, y, z)? `z` is
-- {kind, x1, y1, x2, y2, z}.
function is_ai_zone(zn, x, y, z)
    return type(zn) == 'table' and zn.kind == 'WaterSource' and zn.x1 == x - 1 and zn.y1 == y - 1
        and zn.x2 == x + 1 and zn.y2 == y + 1 and (zn.z == nil or zn.z == z)
end

local function outside_at(x, y, z)
    local ok, des = pcall(dfhack.maps.getTileFlags, xyz2pos(x, y, z))
    return ok and des and des.outside and true or false
end

-- the AI's zone at the record's tile (the building), or nil
local function zone_at(x, y, z)
    local ok, list = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(x, y, z))
    if not ok or type(list) ~= 'table' then return nil end
    for _, zn in ipairs(list) do
        local okk, row = pcall(function()
            return {kind = df.civzone_type[zn.type], x1 = zn.x1, y1 = zn.y1, x2 = zn.x2, y2 = zn.y2, z = zn.z}
        end)
        if okk and is_ai_zone(row, x, y, z) then return zn end
    end
    return nil
end

function retire(outside_only, dry_run)
    local list = U.site_get(WATER_ZONES_KEY, {})
    if type(list) ~= 'table' then list = {} end
    local keep, removed, dropped = {}, {}, 0
    for _, r in ipairs(list) do
        local x, y, z = type(r) == 'table' and math.tointeger(r.x), type(r) == 'table' and math.tointeger(r.y),
            type(r) == 'table' and math.tointeger(r.z)
        if not (x and y and z) then
            dropped = dropped + 1
        elseif outside_only ~= false and not outside_at(x, y, z) then
            table.insert(keep, r)
        else
            local zn = zone_at(x, y, z)
            if zn then
                if not dry_run then pcall(dfhack.buildings.deconstruct, zn) end
                table.insert(removed, {x = x, y = y, z = z})
            else
                dropped = dropped + 1          -- its zone is gone (or the player's now): the record only
            end
        end
    end
    if #removed == 0 and dropped == 0 then
        return {ok = false, rejected = true, nothing_to_do = true,
                error = outside_only ~= false and 'none of the AI\'s water zones is on surface water'
                    or 'the AI has no water zone'}
    end
    if not dry_run then U.site_put(WATER_ZONES_KEY, keep) end
    return {ok = true, removed = removed, dropped = dropped, kept = #keep, dry_run = dry_run or nil}
end
