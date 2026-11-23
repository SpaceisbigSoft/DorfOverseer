-- probe-stairwell-dry: the builder's new-stairwell search, dry run, as JSON
-- (0.105.75). READ ONLY: dig_stairwell(params, true) designates nothing
-- (quickfort's dry run only); it changes nothing in the game.
--
--     probe-stairwell-dry [elev_lo] [elev_hi]    (default 37 38: D's industry)
--
-- For each direction from the fort's main stair: where the search would put
-- the stairwell, or why not; and the stairs it found where the dwarves live.

local json = require('json')
local args = {...}
local lo = tonumber(args[1]) or 37
local hi = tonumber(args[2]) or 38
local out = {elev_lo = lo, elev_hi = hi, dirs = {}}
local okb, B = pcall(reqscript, 'ai-builder')
if not okb then
    out.error = 'ai-builder: ' .. tostring(B)
else
    pcall(function()
        local st = B.find_stairs(10) or {}
        out.stairs = {}
        for _, s in ipairs(st) do
            table.insert(out.stairs, {x = s.x, y = s.y, z_top = s.z_top, z_bottom = s.z_bottom, count = s.count})
        end
    end)
    for _, d in ipairs({'east', 'south', 'west', 'north'}) do
        local ok, r = pcall(B.dig_stairwell, {dir = d, elev_lo = lo, elev_hi = hi}, true)
        out.dirs[d] = ok and r or {error = tostring(r):sub(1, 200)}
    end
end
print(json.encode(out))
