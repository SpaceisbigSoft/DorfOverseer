-- The fort's water: what there is near the fort, where, and of what kind,
-- the base for everything the AI does with water (wells now; cisterns,
-- channels, moats, pumps and floodgates in later steps: see handoff.md,
-- "Water engineering").
--
-- survey() reads the map blocks within RADIUS tiles of the fort's middle,
-- from SURFACE_ABOVE levels over the highest dwarf down to DEPTH levels
-- under the lowest, and sums the water by kind:
--   river     flowing surface water (river or brook tiles)
--   surface   other open water under the sky (ponds, pools, lakes)
--   cavern    water in a cavern layer
--   pool      water underground outside the caverns (a dug cistern, an
--             underground pool, a flooded level)
-- each with its tiles, volume (sum of depths, 7 = a full tile), the levels
-- it lies on, salt/stagnant shares, how much of it the dwarves have seen,
-- and the tile nearest the fort's middle; and aquifer layers (wall tiles
-- that seep water) and magma, by level. Kept in the save (site data
-- 'ai-overseer/water') and reported from there: the scan runs once a
-- season (the survey_water action), the report costs nothing.
--@ module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

WATER_KEY = 'ai-overseer/water'
RADIUS = 72
SURFACE_ABOVE = 12
DEPTH = 80
MAX_SECONDS = 4

local function fort_middle()
    local xs, ys, zs, n = 0, 0, {}, 0
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local x, y, z = dfhack.units.getPosition(u)
        if x then
            xs, ys, n = xs + x, ys + y, n + 1
            table.insert(zs, z)
        end
    end
    if n == 0 then return nil end
    table.sort(zs)
    return {x = xs // n, y = ys // n, z_low = zs[1], z_high = zs[#zs], z_mid = zs[(#zs + 1) // 2]}
end

local function new_body(kind)
    return {kind = kind, tiles = 0, volume = 0, z1 = math.huge, z2 = -math.huge, salt = 0, stagnant = 0,
            seen = 0, deep = 0, nearest = nil}
end

local RIVER_MATS = {RIVER = true, BROOK = true}

-- A survey in slices (the lag pass: the whole scan froze the game ~1.4 s):
-- start_survey() sets it up, survey_step(job, seconds) scans levels from the
-- top down until the time is up and says whether it's done, finish_survey()
-- sums it up. survey() does it all at once (the tests).
function start_survey()
    local mid = fort_middle()
    if not mid then return nil, 'no citizens' end
    local W, H, Z = dfhack.maps.getTileSize()
    local job = {mid = mid,
                 x1 = math.max(0, mid.x - RADIUS), x2 = math.min(W - 1, mid.x + RADIUS),
                 y1 = math.max(0, mid.y - RADIUS), y2 = math.min(H - 1, mid.y + RADIUS),
                 z1 = math.max(0, mid.z_low - DEPTH), z2 = math.min(Z - 1, mid.z_high + SURFACE_ABOVE),
                 bodies = {river = new_body('river'), surface = new_body('surface'), cavern = new_body('cavern'),
                           pool = new_body('pool')},
                 aquifer = {}, magma = {}}
    job.z = job.z2
    return job
end

function survey_step(job, seconds)
    local mid, bodies, aquifer, magma = job.mid, job.bodies, job.aquifer, job.magma
    local x1, x2, y1, y2 = job.x1, job.x2, job.y1, job.y2
    local deadline = os.clock() + seconds
    local first = true
    while job.z >= job.z1 do
        if not first and os.clock() > deadline then return false end   -- (at least one level a call)
        first = false
        local bz = job.z
        job.z = job.z - 1
        for by = y1 // 16, y2 // 16 do
            for bx = x1 // 16, x2 // 16 do
                local block = dfhack.maps.getBlock(bx, by, bz)
                if block then
                    for lx = 0, 15 do
                        local col = block.designation[lx]
                        for ly = 0, 15 do
                            local d = col[ly]
                            local x, y = bx * 16 + lx, by * 16 + ly
                            if d.flow_size > 0 then
                                local is_magma = d.liquid_type == true or d.liquid_type == 1
                                if is_magma then
                                    local m = magma[bz] or 0
                                    magma[bz] = m + 1
                                    -- (0.105.0) the highest magma outside the caverns, nearest
                                    -- the fort's middle: what a magma workshop is dug to
                                    if not (d.feature_local or d.feature_global) then
                                        local dist = math.max(math.abs(x - mid.x), math.abs(y - mid.y))
                                        local t = job.magma_top
                                        if not t or bz > t.z or (bz == t.z and dist < t.d) then
                                            job.magma_top = {x = x, y = y, z = bz, d = dist}
                                        end
                                    end
                                else
                                    local tt = block.tiletype[lx][ly]
                                    local mat = df.tiletype_material[df.tiletype.attrs[tt].material]
                                    local kind = (d.feature_local or d.feature_global) and 'cavern'
                                        or RIVER_MATS[mat] and 'river'
                                        or d.outside and 'surface' or 'pool'
                                    local b = bodies[kind]
                                    b.tiles = b.tiles + 1
                                    b.volume = b.volume + d.flow_size
                                    if d.flow_size >= 4 then b.deep = b.deep + 1 end
                                    if bz < b.z1 then b.z1 = bz end
                                    if bz > b.z2 then b.z2 = bz end
                                    if d.water_salt then b.salt = b.salt + 1 end
                                    if d.water_stagnant then b.stagnant = b.stagnant + 1 end
                                    if not d.hidden then b.seen = b.seen + 1 end
                                    local dist = math.max(math.abs(x - mid.x), math.abs(y - mid.y))
                                        + 2 * math.abs(bz - mid.z_mid)
                                    if not b.nearest or dist < b.nearest.d then
                                        b.nearest = {x = x, y = y, z = bz, d = dist, depth = d.flow_size}
                                    end
                                end
                            elseif d.water_table then
                                aquifer[bz] = (aquifer[bz] or 0) + 1
                            end
                        end
                    end
                end
            end
        end
    end
    return true
end

function finish_survey(job)
    local bodies, aquifer, magma = job.bodies, job.aquifer, job.magma
    local out = {ok = true, middle = job.mid, box = {x1 = job.x1, x2 = job.x2, y1 = job.y1, y2 = job.y2,
                                                     z1 = job.z1, z2 = job.z2},
                 bodies = {}, aquifer = nil, magma = nil}
    for _, kind in ipairs({'river', 'surface', 'cavern', 'pool'}) do
        local b = bodies[kind]
        if b.tiles > 0 then
            b.salt_share = math.floor(100 * b.salt / b.tiles + 0.5)
            b.stagnant_share = math.floor(100 * b.stagnant / b.tiles + 0.5)
            b.seen_share = math.floor(100 * b.seen / b.tiles + 0.5)
            b.salt, b.stagnant, b.seen = nil, nil, nil
            table.insert(out.bodies, b)
        end
    end
    local function levels(t)
        local lo, hi, n = math.huge, -math.huge, 0
        for z, c in pairs(t) do
            n = n + c
            if z < lo then lo = z end
            if z > hi then hi = z end
        end
        if n == 0 then return nil end
        return {z1 = lo, z2 = hi, tiles = n}
    end
    out.aquifer = levels(aquifer)
    out.magma = levels(magma)
    if out.magma and job.magma_top then out.magma.top_nearest = job.magma_top end   -- (0.105.0)
    return out
end

function survey()
    local job, why = start_survey()
    if not job then return {ok = false, error = why} end
    survey_step(job, 1e9)
    return finish_survey(job)
end

-- The scan, kept in the save with the tick it was made.
function scan(now_tick)
    local r = survey()
    if r.ok then
        r.tick = now_tick
        U.site_put(WATER_KEY, r)
    end
    return r
end

-- One slice of a survey (`seconds` of scanning at most): {done = false,
-- level} while it goes on (the next call carries on), or the finished
-- survey (kept in the save) when done.
SLICE_SECONDS = 0.15
JOB = JOB or nil

-- (0.105.33) the fort a sliced survey belongs to (the world's save and the
-- site): a survey begun in one fort is never finished into another's save
local function fort_id()
    local ok, v = pcall(function()
        return tostring(df.global.world.cur_savegame.save_dir) .. ':' .. tostring(df.global.plotinfo.site_id)
    end)
    return ok and v or nil
end

-- (0.105.33) the half-done survey belongs to the fort unloaded
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-water'] = function(sc)
        if sc == SC_MAP_UNLOADED then JOB = nil end
    end
end

function scan_step(now_tick, seconds)
    if JOB and JOB.fort ~= fort_id() then JOB = nil end
    if not JOB then
        local why
        JOB, why = start_survey()
        if not JOB then return {ok = false, error = why} end
        JOB.started = now_tick
        JOB.fort = fort_id()
    end
    if not survey_step(JOB, seconds or SLICE_SECONDS) then
        return {ok = true, done = false, level = JOB.z, left = JOB.z - JOB.z1 + 1}
    end
    local r = finish_survey(JOB)
    JOB = nil
    r.tick = now_tick
    r.done = true
    U.site_put(WATER_KEY, r)
    return r
end

function scanning() return JOB ~= nil end

-- The last scan (or nil): what the fort report shows.
function last()
    local d = U.site_get(WATER_KEY, nil)
    return type(d) == 'table' and d.ok and d or nil
end
