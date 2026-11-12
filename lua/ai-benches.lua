-- (item10) Training benches: a skill cap on the AI's second workshop of a kind.
-- The coverage audit's "should" list: "the AI's workshops used for training
-- (a second workshop of a kind) get a workshop profile max skill cap, so
-- novices learn there and masters work on the good one; only the AI's own
-- workshops."
--
-- DF's workshop profile (building_workshopst.profile, the workshop's Workers
-- tab): permitted_workers, min_level and max_level (the skill range a dwarf
-- must be in to take a job there; max_level 3000 when unset) and the general
-- orders. The bridge already reads them (ai-bridge-report's workshops,
-- ai-bridge-orders' unworked jobs) and the kitchens' min_level is set by the
-- AI (act_kitchen_skill). Here:
--
--   report()            the `benches` section: for each kind the AI may cap
--                       (BENCH_KINDS), its built workshops that lie in an AI
--                       project's area (id, max/min level, workers, jobs,
--                       capped: the AI set its cap), and the skill ratings of
--                       the citizens with the kind's labour (best first, at
--                       most 40).
--   cap_bench(kind, level, dry_run)
--                       the newest of the AI's untouched workshops of that
--                       kind (no workers named, no min, no max) gets max_level
--                       = level; the oldest is left as the masters' bench.
--                       Refused with fewer than two of the AI's own, or when
--                       one is capped already.
--   release_bench(kind, dry_run)
--                       the caps the AI set on that kind lifted (max_level
--                       back to 3000), only where the cap is still the one
--                       it set (one you changed is yours: forgotten, untouched).
--
-- A workshop is the AI's when its centre lies in the area of one of the AI's
-- projects (ai-builder's registry: the levels it dug and furnished); every
-- other workshop is the player's and is never changed. The caps it set are
-- kept in the save (site data BENCH_KEY: {capped = {[id] = level}}).
--@ module = true

local U = reqscript('ai-util')

BENCH_KEY = 'ai-overseer/benches'
NO_MAX = 3000                      -- DF's max_level when the profile sets none
-- the kinds where quality matters, and the skill and labour each trains
-- (df.job_skill / df.unit_labor tokens; the craftsdwarf's trains stonecraft)
BENCH_KINDS = {
    Carpenters = {skill = 'CARPENTRY', labor = 'CARPENTER'},
    Masons = {skill = 'MASONRY', labor = 'MASON'},
    Craftsdwarfs = {skill = 'STONECRAFT', labor = 'STONECRAFTER'},
    Jewelers = {skill = 'CUTGEM', labor = 'CUTGEM'},
    Clothiers = {skill = 'CLOTHESMAKING', labor = 'CLOTHESMAKER'},
    Leatherworks = {skill = 'LEATHERWORK', labor = 'LEATHER'},
    Bowyers = {skill = 'BOWYER', labor = 'BOWYER'},
    Mechanics = {skill = 'MECHANICS', labor = 'MECHANIC'},
}
SKILLS_MAX = 40                    -- ratings reported a kind

local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end

local function load_state()
    local d = U.site_get(BENCH_KEY, {})
    if type(d) ~= 'table' then d = {} end
    if type(d.capped) ~= 'table' then d.capped = {} end
    return d
end

local function save_state(d) return U.site_put(BENCH_KEY, d) end

-- The AI's project areas: {{x1, y1, x2, y2, z}...} (swapped by the tests).
function ai_areas()
    local out = {}
    pcall(function()
        for _, p in ipairs(reqscript('ai-builder').registry_report() or {}) do
            local b = type(p) == 'table' and p.bounds
            if type(b) == 'table' and b.x1 and b.z then table.insert(out, b) end
        end
    end)
    return out
end

local function in_areas(areas, x, y, z)
    for _, b in ipairs(areas) do
        if b.z == z and x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 then return true end
    end
    return false
end

local function built(b)
    local ok, yes = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    return ok and yes
end

-- The AI's built workshops of each capped kind: kind -> {building...}, oldest first.
local function own_shops(areas)
    local out = {}
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        local okt, kind = pcall(function() return df.workshop_type[b.type] end)
        if okt and kind and BENCH_KINDS[kind] and built(b) and in_areas(areas, b.centerx, b.centery, b.z) then
            out[kind] = out[kind] or {}
            table.insert(out[kind], b)
        end
    end
    for _, list in pairs(out) do table.sort(list, function(a, b) return a.id < b.id end) end
    return out
end

local function profile_of(b)
    local pr = b.profile
    local p = {max = NO_MAX, min = 0, workers = 0}
    pcall(function() p.max = pr.max_level end)
    pcall(function() p.min = pr.min_level end)
    pcall(function() p.workers = #pr.permitted_workers end)
    return p
end

-- Pure: a workshop the player has not set (no workers named, no skill range).
function untouched(p)
    return (p.max or NO_MAX) >= NO_MAX and (p.min or 0) == 0 and (p.workers or 0) == 0
end

-- The skill ratings of the citizens holding a kind's labour, best first.
local function ratings(kind)
    local k = BENCH_KINDS[kind]
    local out = {}
    pcall(function()
        local sk, lab = df.job_skill[k.skill], df.unit_labor[k.labor]
        for _, u in ipairs(report_citizens(true)) do
            local okl, has = pcall(function() return u.status.labors[lab] end)
            if okl and has then
                local okr, r = pcall(dfhack.units.getNominalSkill, u, sk, true)
                table.insert(out, (okr and tonumber(r)) or 0)
            end
        end
    end)
    table.sort(out, function(a, b) return a > b end)
    while #out > SKILLS_MAX do table.remove(out) end
    return out
end

function report()
    local d = load_state()
    local shops = own_shops(ai_areas())
    local out = {kinds = {}}
    local alive = {}
    for kind, list in pairs(shops) do
        local rows = {}
        for _, b in ipairs(list) do
            alive[tostring(b.id)] = true
            local p = profile_of(b)
            local mine = d.capped[tostring(b.id)]
            table.insert(rows, {id = b.id, max_level = p.max < NO_MAX and p.max or nil,
                                min_level = p.min > 0 and p.min or nil, workers = p.workers > 0 and p.workers or nil,
                                jobs = #b.jobs, capped = (mine ~= nil and mine == p.max) or nil})
        end
        out.kinds[kind] = {shops = rows, skills = ratings(kind)}
    end
    -- the AI's caps on workshops gone (or no longer the AI's) forgotten
    local changed = false
    for id in pairs(d.capped) do
        if not alive[id] then d.capped[id] = nil; changed = true end
    end
    if changed then save_state(d) end
    return out
end

function cap_bench(kind, level, dry_run)
    if not BENCH_KINDS[kind] then return {ok = false, rejected = true, error = 'not a kind the AI caps: ' .. tostring(kind)} end
    level = math.floor(tonumber(level) or -1)
    if level < 1 or level > 20 then return {ok = false, rejected = true, error = 'cap_bench needs level 1-20'} end
    local list = own_shops(ai_areas())[kind] or {}
    if #list < 2 then
        return {ok = false, rejected = true, error = ('the AI has %d %s workshop(s) of its own: a training bench needs two'):format(#list, kind)}
    end
    local d = load_state()
    for _, b in ipairs(list) do
        local mine = d.capped[tostring(b.id)]
        if mine ~= nil and mine == profile_of(b).max then
            return {ok = false, rejected = true, error = ('%s %d is the training bench already'):format(kind, b.id)}
        end
    end
    -- the newest untouched one (never the oldest: the masters' bench)
    local pick
    for i = #list, 2, -1 do
        if untouched(profile_of(list[i])) then pick = list[i] break end
    end
    if not pick then return {ok = false, rejected = true, error = 'every other ' .. kind .. ' has workers or a skill range set (yours)'} end
    if dry_run then return {ok = true, dry_run = true, kind = kind, id = pick.id, level = level, masters = list[1].id} end
    local ok, err = pcall(function() pick.profile.max_level = level end)
    if not ok then return {ok = false, error = 'max_level not set: ' .. tostring(err):sub(1, 120)} end
    d.capped[tostring(pick.id)] = level
    save_state(d)
    return {ok = true, kind = kind, id = pick.id, level = level, masters = list[1].id}
end

function release_bench(kind, dry_run)
    if not BENCH_KINDS[kind] then return {ok = false, rejected = true, error = 'not a kind the AI caps: ' .. tostring(kind)} end
    local d = load_state()
    local lifted, forgot = 0, 0
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        local mine = d.capped[tostring(b.id)]
        local okt, k = pcall(function() return df.workshop_type[b.type] end)
        if mine ~= nil and okt and k == kind then
            if profile_of(b).max == mine then
                if not dry_run then pcall(function() b.profile.max_level = NO_MAX end) end
                lifted = lifted + 1
            else
                forgot = forgot + 1          -- changed since: yours
            end
            if not dry_run then d.capped[tostring(b.id)] = nil end
        end
    end
    if lifted + forgot == 0 then return {ok = false, rejected = true, error = 'no cap of the AI on a ' .. kind} end
    if not dry_run then save_state(d) end
    return {ok = lifted > 0, kind = kind, lifted = lifted, forgot = forgot > 0 and forgot or nil,
            dry_run = dry_run or nil}
end
