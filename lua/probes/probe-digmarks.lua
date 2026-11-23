-- probe-digmarks x y z [r]: the dig marks within r (3) tiles of x, y, z on
-- that level: each marked tile, its tile type, whether a dig job stands for
-- it, whether a citizen can walk next to it; and the citizens with the mining
-- labour. READ ONLY.
local json = require('json')
local a = {...}
local X, Y, Z, R = tonumber(a[1]) or 98, tonumber(a[2]) or 144, tonumber(a[3]) or 165, tonumber(a[4]) or 3
local out = {at = {X, Y, Z}, marked = {}, jobs = 0, miners = 0}
local jobs = {}
local link = df.global.world.jobs.list.next
while link do
    local j = link.item
    if j and j.pos and j.pos.z == Z and math.abs(j.pos.x - X) <= R + 1 and math.abs(j.pos.y - Y) <= R + 1 then
        jobs[j.pos.x .. ',' .. j.pos.y] = tostring(df.job_type[j.job_type])
        out.jobs = out.jobs + 1
    end
    link = link.next
end
local from
for _, u in ipairs(df.global.world.units.active) do
    local okc, c = pcall(dfhack.units.isCitizen, u)
    if okc and c then
        from = from or u.pos
        pcall(function() if u.status.labors.MINE then out.miners = out.miners + 1 end end)
    end
end
for y = Y - R, Y + R do
    for x = X - R, X + R do
        local d = dfhack.maps.getTileFlags(x, y, Z)
        local tt = dfhack.maps.getTileType(x, y, Z)
        local row = {x = x, y = y, dig = d and tostring(df.tile_dig_designation[d.dig]) or '?',
                     tt = tt and tostring(df.tiletype[tt]) or '?', job = jobs[x .. ',' .. y], hidden = d and d.hidden or nil}
        if d and d.dig ~= df.tile_dig_designation.No then
            local reach = false
            for dy = -1, 1 do for dx = -1, 1 do
                if from then
                    local ok, w = pcall(dfhack.maps.canWalkBetween, from, xyz2pos(x + dx, y + dy, Z))
                    if ok and w then reach = true end
                end
            end end
            row.reach = reach
            table.insert(out.marked, row)
        elseif x == X and y == Y then
            out.centre = row
        end
    end
end
print(json.encode(out))
