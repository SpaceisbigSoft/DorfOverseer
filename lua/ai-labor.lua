-- Who does what: the AI keeps enough dwarves on the jobs a young fort lives
-- on: mining, woodcutting, plant gathering, fishing and farming.
--
-- In DF 50+ labours come from work details: the game works out each dwarf's
-- labours from the details he is a member of. So the AI never sets a labour
-- itself: it adds the dwarf to the game's own detail (Miners, Woodcutters,
-- Plant gatherers, Fisherdwarves, Planters), keeping the member list sorted
-- as the game needs it, and asks the game to recompute that dwarf's labours
-- (dfhack.units.setAutomaticProfessions), as DFHack's own autolabor does. A
-- detail set to "everybody" or "nobody" is left alone. Soldiers never; the
-- most skilled first, then dwarves the fort misses least. It never takes a
-- dwarf off a job.
--
-- Also here: the plants to gather (shrubs near the fort marked for gathering:
-- food and drink for a fort with no farm yet), and whether there's water to
-- fish in near the fort.
--@module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...) return U.report_citizens(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)
local function report_units(...) return U.report_units(...) end   -- (r6) ai-util's, looked up each call (a reload of ai-util is picked up)

MAX_MINERS = 20           -- (0.104.134: was 10) more than this get in each other's way; Teacheroar had
                          -- 15 picks, 10 miners and 260 tiles waiting on many levels
TILES_PER_MINER = 15      -- digging waiting per miner wanted (0.104.137: was 25; levels stalled for years at 10)
GATHER_RADIUS = 40        -- shrubs this far from the fort's centre are gathered
SCAN_EVERY_TICKS = 7 * 1200   -- (0.100) the shrub and water scans: once a game week
SCAN_CACHE = SCAN_CACHE      -- kept across reloads of this module within a session
SCAN_GRID = 20
SCAN_KEEP = 8                 -- (R29 W7) centres whose scans are kept at once
GATHER_MAX = 150          -- at most this many marked at a time
FISH_RADIUS = 40          -- water this close counts for fishing

-- job -> the game's detail (by its icon), the labour, the skill, the tool
-- (a weapon skill: picks are MINING weapons, axes AXE weapons)
JOBS = {
    mining = {icon = 'MINERS', labor = 'MINE', skill = 'MINING', tool = 'MINING', name = 'mine'},
    woodcutting = {icon = 'WOODCUTTERS', labor = 'CUTWOOD', skill = 'WOODCUTTING', tool = 'AXE', name = 'cut wood'},
    gathering = {icon = 'PLANT_GATHERERS', labor = 'HERBALIST', skill = 'HERBALISM', name = 'gather plants'},
    fishing = {icon = 'FISHERMEN', labor = 'FISH', skill = 'FISH', name = 'fish'},
    farming = {icon = 'PLANTERS', labor = 'PLANT', skill = 'PLANT', name = 'farm'},
}
JOB_ORDER = {'mining', 'woodcutting', 'gathering', 'fishing', 'farming'}

-- Pure: how many miners the digging wants. dig = tiles designated, picks =
-- picks a miner could use (not in a soldier's hands), adults = grown citizens
-- outside squads. Never more than there are picks; 3 or so for a new fort,
-- a third of the dwarves later, at most MAX_MINERS.
function miners_wanted(dig, picks, adults)
    if (dig or 0) <= 0 then return 0 end
    local by_dig = math.ceil(dig / TILES_PER_MINER)
    local by_pop = math.max(3, math.ceil((adults or 0) / 3))
    return math.max(0, math.min(picks or 0, by_dig, by_pop, MAX_MINERS))
end

-- Pure: the n best candidates. Each: {id, skill = level in this job, other =
-- best other skill level, idle = bool, noble = bool, busy = jobs already
-- held}. Skilled first, then those the fort misses least (low other skill,
-- idle, few jobs already); nobles last; ties to the lower id.
function pick_workers(cands, n)
    local list = {}
    for _, c in ipairs(cands) do table.insert(list, c) end
    local function score(c)
        return (c.skill or c.mining or 0) * 10 - (c.other or 0) + (c.idle and 3 or 0)
            - (c.noble and 20 or 0) - 4 * (c.busy or 0)
    end
    table.sort(list, function(a, b)
        local sa, sb = score(a), score(b)
        if sa ~= sb then return sa > sb end
        return a.id < b.id
    end)
    local out = {}
    for i = 1, math.min(n, #list) do out[i] = list[i] end
    return out
end

-- Pure: is a list of ids in order (the game finds members by binary search)?
function is_sorted(ids)
    for i = 2, #ids do
        if ids[i] < ids[i - 1] then return false end
    end
    return true
end

-- --- the game -----------------------------------------------------------------

local function enum(e, k) if e == nil or k == nil then return nil end return e[k] end

local function has_labor(u, labor)
    local ok, v = pcall(function() return u.status.labors[labor] end)
    return ok and v == true
end

local function grown(u)
    return not (dfhack.units.isChild(u) or dfhack.units.isBaby(u))
end

local function in_squad(u) return u.military.squad_id >= 0 end

-- (0.105.119 item33) the AI's recreation burrow's members (ai-society-burrows
-- RECREATION_KEY): their labours are off on purpose while they are in
-- (rec_labors_off, at every report), so no labour rule may pick them. A, 25
-- Nov: the doctor Kel, in the burrow, was put back on Planters 30 times in an
-- hour, the burrow took it off again each report, and the labour rule's
-- "skilled in plant aren't on the Planters detail" asks between were refused
-- "nobody outside the squads left for this job" 48 times in 3.5 h.
REC_KEY = 'ai-overseer/recreation'
function rec_member_ids()
    local set = {}
    pcall(function()
        local d = U.site_get(REC_KEY, {members = {}})
        for k, _ in pairs(type(d) == 'table' and type(d.members) == 'table' and d.members or {}) do
            local id = tonumber(k)
            if id then set[id] = true end
        end
    end)
    return set
end

-- (r33c) Why a grown citizen outside the squads with no job is not one the
-- fort could put to work (the idle count's honesty: the digest read 38% idle
-- in B while it counted the recreation burrow's members, the mad and the
-- caged among the "truly idle"): 'recreation' (the AI's recreation burrow:
-- its labours are off on purpose), 'unfit' (insane: melancholy, raving,
-- berserk, traumatized, or crazed; caged or chained), 'on_break' (DF's own
-- break), or nil (no excuse: idle). rec: rec_member_ids() (optional).
UNFIT_MOODS = {Melancholy = true, Raving = true, Berserk = true, Traumatized = true}
function idle_excuse(u, rec)
    if rec and rec[u.id] then return 'recreation' end
    local unfit = false
    pcall(function()
        local m = df.mood_type[u.mood]
        if m and UNFIT_MOODS[m] then unfit = true end
    end)
    pcall(function() if dfhack.units.isCrazed and dfhack.units.isCrazed(u) then unfit = true end end)
    pcall(function() if u.flags1.caged or u.flags1.chained then unfit = true end end)
    if unfit then return 'unfit' end
    local brk = false
    pcall(function()
        local OB = df.misc_trait_type.OnBreak
        for _, t in ipairs(u.status.misc_traits) do
            if OB ~= nil and t.id == OB then brk = true break end
        end
    end)
    if brk then return 'on_break' end
    return nil
end

-- (r33c) In a social activity (prayer, the tavern, a performance, reading):
-- no job, but not free for one either
function in_activity(u)
    local ok, busy = pcall(function() return #u.social_activities > 0 end)
    return ok and busy == true
end

-- (r33c) Free for work now: no job, no social activity, no excuse
function is_free(u, rec)
    return u.job.current_job == nil and not in_activity(u) and idle_excuse(u, rec) == nil
end

local function skill(u, id)
    local soul = u.status.current_soul
    if not soul or not id then return 0 end
    for _, s in ipairs(soul.skills) do
        if s.id == id then return s.rating end
    end
    return 0
end

local function best_other(u, id)
    local soul, best = u.status.current_soul, 0
    if not soul then return 0 end
    for _, s in ipairs(soul.skills) do
        if s.id ~= id and s.rating > best then best = s.rating end
    end
    return best
end

-- (a tool a job holds, or a dwarf carries, still counts: count_tools sorts
-- out the soldiers' ones; an artifact pick digs as well as any)
local TOOL_OK = {in_job = true, held = true, artifact = true}
local function usable(item) return U.item_free(item, TOOL_OK) end

-- Tools of a weapon skill (picks, axes): usable ones, and those in a
-- soldier's hands (a squad with "any weapon" takes them: those can't work).
-- (0.105.119 item33) and those built into a building (a weapon trap's
-- blade: D, 25 Nov, had its three iron picks in weapon traps, 1217 tiles
-- designated and nobody able to dig for two years)
local function count_tools(weapon_skill)
    local free, soldiers, built = 0, 0, 0
    local want = enum(df.job_skill, weapon_skill)
    if not want then return 0, 0, 0 end
    for _, item in ipairs(df.global.world.items.other.WEAPON) do
        local ok, s = pcall(function() return item.subtype.skill_melee end)
        if ok and s == want and usable(item) then
            local holder = dfhack.items.getHolderUnit(item)
            if holder and in_squad(holder) then soldiers = soldiers + 1
            else free = free + 1 end
        elseif ok and s == want and item.flags.in_building and not item.flags.removed then
            built = built + 1
        end
    end
    return free, soldiers, built
end

local function shape_of(block, x, y)
    local attrs = df.tiletype.attrs[block.tiletype[x][y]]
    return attrs and attrs.shape
end

-- Tiles designated for digging, and shrubs marked for gathering (a gather
-- mark is a dig designation on a shrub).
local function count_designations(limit)
    local dig, gather = 0, 0
    local SHRUB = df.tiletype_shape.SHRUB
    for _, block in ipairs(df.global.world.map.map_blocks) do
        if block.flags.designated then
            for x = 0, 15 do
                for y = 0, 15 do
                    if block.designation[x][y].dig ~= df.tile_dig_designation.No then
                        if shape_of(block, x, y) == SHRUB then gather = gather + 1
                        else dig = dig + 1 end
                        if dig >= limit then return dig, gather end
                    end
                end
            end
        end
    end
    return dig, gather
end

local function details()
    local ok, v = pcall(function() return df.global.plotinfo.labor_info.work_details end)
    return ok and v or nil
end

-- The game's own detail for a job (found by its icon), else any detail
-- carrying the labour; and its mode's name.
function detail_for(job)
    local J = job_spec(job)
    local list = details()
    if not J or not list then return nil, nil end
    local icon, labor = J.icon and enum(df.work_detail_icon_type, J.icon), enum(df.unit_labor, J.labor)
    local found
    for _, d in ipairs(list) do
        if icon and d.icon == icon then found = d break end
    end
    if not found and labor then
        -- a detail carrying the labour: one the player hasn't fixed first
        for _, d in ipairs(list) do
            if d.allowed_labors[labor] then
                local okm, m = pcall(function() return df.work_detail_mode[d.flags.mode] end)
                if not found or (okm and m ~= 'EverybodyDoesThis' and m ~= 'NobodyDoesThis') then
                    found = d
                    if okm and m ~= 'EverybodyDoesThis' and m ~= 'NobodyDoesThis' then break end
                end
            end
        end
    end
    if not found then return nil, nil end
    local ok, mode = pcall(function() return df.work_detail_mode[found.flags.mode] end)
    return found, ok and mode or nil
end

local function ids_of(wd)
    local out = {}
    for _, v in ipairs(wd.assigned_units) do table.insert(out, v) end
    return out
end

local function is_member(wd, id)
    for _, v in ipairs(wd.assigned_units) do
        if v == id then return true end
    end
    return false
end

-- Members kept in order, as the game needs (it finds them by binary search).
local function insert_sorted(wd, id)
    if is_member(wd, id) then return end
    local vec, at = wd.assigned_units, #wd.assigned_units
    for i, v in ipairs(vec) do
        if v > id then at = i break end
    end
    vec:insert(at, id)
end

local function recompute(u)
    if dfhack.units.setAutomaticProfessions then
        return pcall(dfhack.units.setAutomaticProfessions, u)
    end
    return false
end

-- (r9, audit A7 #22) One dwarf given a labour, or taken off labours, the
-- way DF 50 keeps them: through the work details. A flag set directly is
-- set back by the game's next recompute of a detail that holds the dwarf
-- (step_down's surgeon was back at surgery the next day). give_labor: into
-- the detail carrying it ("only selected"); a detail set to nobody is the
-- player's choice, left; with no detail (or an old DFHack) the flag directly.
-- Returns whether the dwarf has the labour after.
function give_labor(u, token)
    local labor = enum(df.unit_labor, token)
    if not (u and labor) then return false end
    local wd, mode = detail_for(token)
    if wd and mode == 'NobodyDoesThis' then return has_labor(u, labor) end
    if wd and mode ~= 'EverybodyDoesThis' then
        insert_sorted(wd, u.id)
        recompute(u)
    end
    if not has_labor(u, labor) then pcall(function() u.status.labors[labor] = true end) end
    return has_labor(u, labor)
end

-- take_labors: out of every work detail carrying one of the labours (all
-- that detail's labours go with it), then recomputed; a labour still on
-- (no detail holds it, an old DFHack) off directly. Returns the tokens now
-- off, in the order given.
function take_labors(u, tokens)
    local labs = {}
    for _, tk in ipairs(tokens or {}) do
        local l = enum(df.unit_labor, tk)
        if l then table.insert(labs, {tk, l}) end
    end
    if not u or #labs == 0 then return {} end
    local changed = false
    for _, d in ipairs(details() or {}) do
        local carries = false
        for _, x in ipairs(labs) do
            pcall(function() if d.allowed_labors[x[2]] then carries = true end end)
        end
        if carries and is_member(d, u.id) then
            for i = #d.assigned_units - 1, 0, -1 do
                if d.assigned_units[i] == u.id then d.assigned_units:erase(i) end
            end
            changed = true
        end
    end
    if changed then recompute(u) end
    local off = {}
    for _, x in ipairs(labs) do
        if has_labor(u, x[2]) then pcall(function() u.status.labors[x[2]] = false end) end
        if not has_labor(u, x[2]) then table.insert(off, x[1]) end
    end
    return off
end

-- A detail whose members are out of order (bridge 0.38.0 appended them):
-- put them in order and recompute everyone's labours. Returns true if fixed.
local function repair(wd)
    local ids = ids_of(wd)
    if is_sorted(ids) then return false end
    table.sort(ids)
    local vec = wd.assigned_units
    for i, v in ipairs(ids) do vec[i - 1] = v end
    return true
end

-- A job name the AI knows (mining...), or any of the game's labours by
-- token (BREWER, SMELT, ...): its detail-finding record.
function job_spec(job)
    if JOBS[job] then return JOBS[job] end
    local okl, l = pcall(function() return df.unit_labor[job] end)
    if not okl or type(l) ~= 'number' or l < 0 then return nil end
    return {labor = job, skill = skill_token_for(l), name = tostring(job):lower()}
end

-- The skill that trains a labour (df.job_skill attrs), as a token.
function skill_token_for(labor)
    local ok, tok = pcall(function()
        for sk = df.job_skill._first_item, df.job_skill._last_item do
            local a = df.job_skill.attrs[sk]
            if a and a.labor == labor then return df.job_skill[sk] end
        end
    end)
    return ok and tok or nil
end

-- memo (optional, one survey's): the citizens and who holds an office, read
-- once for all the jobs (13c: they were read again for each of the five)
-- One citizen as a pick_workers candidate for `job` (sk: its skill id).
local function cand_of(u, job, sk, memo)
    local noble, busy = memo.noble[u.id], 0
    if noble == nil then
        noble = false
        pcall(function() noble = #dfhack.units.getNoblePositions(u) > 0 end)
        memo.noble[u.id] = noble
    end
    for _, other in ipairs(JOB_ORDER) do
        local l = enum(df.unit_labor, JOBS[other].labor)
        if other ~= job and l and has_labor(u, l) then busy = busy + 1 end
    end
    return {id = u.id, skill = skill(u, sk), other = best_other(u, sk),
            idle = u.job.current_job == nil, noble = noble, busy = busy}
end

local function citizens(job, memo)
    local J = job_spec(job)
    local labor, sk = enum(df.unit_labor, J.labor), enum(df.job_skill, J.skill)
    local doing, cands, soldiers = {}, {}, 0
    memo = memo or {}
    memo.units = memo.units or report_citizens(true)
    memo.noble = memo.noble or {}
    memo.rec = memo.rec or rec_member_ids()     -- (item33) never a recreation member
    for _, u in ipairs(memo.units) do
        if grown(u) then
            if labor and has_labor(u, labor) then
                if in_squad(u) then soldiers = soldiers + 1 else table.insert(doing, u) end
            elseif not in_squad(u) and not memo.rec[u.id] then
                table.insert(cands, cand_of(u, job, sk, memo))
            end
        end
    end
    return doing, cands, soldiers
end

-- The fort's centre (the wagon, else the citizens' median), from ai-builder.
local function centre()
    local ok, c = pcall(function() return reqscript('ai-builder').found_center() end)
    return ok and c or nil
end

-- Water to fish in near the fort: tiles of water 4/7 deep or more (a cistern's
-- or a well shaft's water counts too), within FISH_RADIUS and 6 levels of the centre; and ice there (the
-- water freezes in winter).
local function fish_water(c)
    if not c then return 0, 0 end
    local n, ice = 0, 0
    local FROZEN = df.tiletype_material and df.tiletype_material.FROZEN_LIQUID
    for z = c.z - 6, c.z + 6 do
        for x = c.x - FISH_RADIUS, c.x + FISH_RADIUS, 2 do          -- every other tile is plenty
            for y = c.y - FISH_RADIUS, c.y + FISH_RADIUS, 2 do
                local d = dfhack.maps.getTileFlags(x, y, z)
                if d and not d.hidden then
                    if d.flow_size >= 4 and not d.liquid_type then n = n + 1 end
                    local tt = FROZEN and dfhack.maps.getTileType(x, y, z)
                    local attrs = tt and df.tiletype.attrs[tt]
                    if attrs and attrs.material == FROZEN then ice = ice + 1 end
                end
            end
        end
    end
    return n, ice
end

-- Shrubs near the fort that could be gathered (outside, revealed, unmarked).
local function shrubs(c, limit, mark)
    if not c then return 0 end
    local n = 0
    local SHRUB = df.tiletype_shape.SHRUB
    local DEAD = df.tiletype_special and df.tiletype_special.DEAD
    for z = c.z - 3, c.z + 3 do
        for x = c.x - GATHER_RADIUS, c.x + GATHER_RADIUS do
            for y = c.y - GATHER_RADIUS, c.y + GATHER_RADIUS do
                local tt = dfhack.maps.getTileType(x, y, z)
                local attrs = tt and df.tiletype.attrs[tt]
                if attrs and attrs.shape == SHRUB and (DEAD == nil or attrs.special ~= DEAD) then
                    local d, occ = dfhack.maps.getTileFlags(x, y, z)
                    if d and not d.hidden and d.outside and d.dig == df.tile_dig_designation.No then
                        n = n + 1
                        if mark then
                            d.dig = df.tile_dig_designation.Default
                            local block = dfhack.maps.getTileBlock(x, y, z)
                            if block then block.flags.designated = true end
                        end
                        if n >= limit then return n end
                    end
                end
            end
        end
    end
    return n
end

-- One job's row of the survey: who does it, who could, soldiers with the
-- labour, its detail and mode, and (a job with a tool) the tools free and in
-- soldiers' hands. Also returns the candidates themselves.
local function job_row(job, memo)
    local J = job_spec(job)
    local doing, cands, soldiers = citizens(job, memo)
    local wd, mode = detail_for(job)
    local row = {doing = #doing, candidates = #cands, soldiers = soldiers,
                 detail = wd and tostring(wd.name) or nil, mode = mode,
                 unsorted = wd and not is_sorted(ids_of(wd)) or nil}
    if J.tool then row.tools, row.soldier_tools, row.built_tools = count_tools(J.tool) end
    return row, cands, wd
end

-- The report's "labor" section: per job, the detail, its mode, who does it,
-- tools; plus digging and gathering waiting, shrubs and water near.
function survey()
    -- (0.100.1) how long each part takes, in the report (`ms`), so the
    -- slow one is known rather than guessed
    local clock, ms, t = os.clock, {}, os.clock()
    local function lap(name) local n = clock(); ms[name] = math.floor((n - t) * 1000 + 0.5); t = n end
    local dig, gather = count_designations(5000)
    lap('designations')
    local c = centre()
    local out = {dig = dig, gather_marked = gather, jobs = {}, ms = ms}
    local memo = {}
    for _, job in ipairs(JOB_ORDER) do out.jobs[job] = job_row(job, memo) end
    lap('jobs')
    local m = out.jobs.mining
    out.adults = m.doing + m.candidates
    -- (0.100) the two map scans (some 46k tiles for shrubs, 21k for water)
    -- ran on every report: shrubs and water change slowly, so a week of game
    -- time apart (and again when the fort's centre moves)
    local okt, now = pcall(U.abs_tick)
    -- (0.100.1) the centre on a 20-tile grid: in a young fort the dwarves'
    -- middle moves every report, and the exact tile missed the cache each time
    -- (overnight run: labor 60-76 ms a report)
    local where = c and ((c.x // SCAN_GRID) .. ',' .. (c.y // SCAN_GRID) .. ',' .. c.z) or '-'
    -- (R29 W7, 13e) one copy per centre: the centre's level is the one most
    -- citizens stand on, and in a grown fort it changes between two or three
    -- levels from report to report, so the one copy kept missed almost every
    -- time (25 Nov: `scanned` in five forts of six, ~55 ms a report). Each
    -- centre's copy keeps its own week, as the one copy did.
    local sc = type(SCAN_CACHE) == 'table' and type(SCAN_CACHE.by) == 'table' and SCAN_CACHE or {by = {}}
    SCAN_CACHE = sc
    local e = okt and sc.by[where]
    if e and now >= e.at and now - e.at < SCAN_EVERY_TICKS then
        out.shrubs, out.fish_water, out.ice = e.shrubs, e.fish_water, e.ice
    else
        out.shrubs = shrubs(c, 500, false)
        out.fish_water, out.ice = fish_water(c)
        if okt then
            -- the stale copies dropped, and never more than SCAN_KEEP kept
            local n = 0
            for k, v in pairs(sc.by) do
                if now < v.at or now - v.at >= SCAN_EVERY_TICKS then sc.by[k] = nil else n = n + 1 end
            end
            if n >= SCAN_KEEP then sc.by = {} end
            sc.by[where] = {at = now, shrubs = out.shrubs, fish_water = out.fish_water, ice = out.ice}
        end
        ms.scanned = true
    end
    lap('scans')
    -- (the fields the miners rule of bridge 0.38 read, kept)
    out.miners, out.picks, out.soldier_picks, out.candidates = m.doing, m.tools or 0, m.soldier_tools or 0, m.candidates
    out.want = miners_wanted(dig, out.picks, out.adults)
    out.need = math.max(0, out.want - out.miners)
    out.built_picks = m.built_tools or 0       -- (item33) picks built into traps: no miner's
    out.detail, out.detail_mode = m.detail, m.mode
    local okw, w = pcall(waiting_work, 12)
    out.waiting = okw and w or {error = tostring(w):sub(1, 160)}
    lap('waiting')
    local oks, sk = pcall(skilled_off, 10)
    out.skilled_off = oks and sk or {error = tostring(sk):sub(1, 160)}
    lap('skilled')
    pcall(function() out.narrowed = narrowed() end)       -- (0.104.10) details the AI narrowed
    return out
end

-- --- work waiting for a worker ---------------------------------------------------
--
-- The game's jobs nobody has taken (not suspended), by the labour each needs
-- (the job type's labour; a reaction's by its skill): for each, how many
-- dwarves outside the squads have the labour, how many of those are idle, and
-- the detail that carries it. Also dwarves skilled (Competent or better) in a
-- detail's labour who aren't on it (migrants arrive with trades).

SKILLED = 3                -- df.skill_rating Competent
-- (0.105.48, A2-5) the labour of a workshop's skill-less jobs (53.17: stone
-- furniture is the stone carver's; MASON builds walls)
JOB_SHOP_LABOR = {Masons = 'STONE_CARVER', Carpenters = 'CARPENTER'}
local REACTION_LABOR

local REACTION_SKILL

-- (0.105.48 r2) the skill a job trains (DFHack 53.17 has no job.getSkill): its
-- type's (df.job_type attrs), a custom reaction's its own; nil if none
function job_skill(job)
    local ok, sk = pcall(function() return df.job_type.attrs[job.job_type].skill end)
    if ok and sk and sk >= 0 then return sk end
    if df.job_type[job.job_type] == 'CustomReaction' then
        if not REACTION_SKILL then
            REACTION_SKILL = {}
            pcall(function()
                for _, r in ipairs(df.global.world.raws.reactions.reactions) do
                    REACTION_SKILL[r.code] = r.skill
                end
            end)
        end
        local rs = REACTION_SKILL[job.reaction_name]
        if rs and rs >= 0 then return rs end
    end
    return nil
end

local function reaction_labor(code)
    if not REACTION_LABOR then
        REACTION_LABOR = {}
        pcall(function()
            for _, r in ipairs(df.global.world.raws.reactions.reactions) do
                local l = -1
                if r.skill and r.skill >= 0 then l = df.job_skill.attrs[r.skill].labor end
                REACTION_LABOR[r.code] = l
            end
        end)
    end
    return REACTION_LABOR[code]
end

function job_labor(job)
    local ok, l = pcall(function() return df.job_type.attrs[job.job_type].labor end)
    if ok and l and l >= 0 then return l end
    if df.job_type[job.job_type] == 'CustomReaction' then
        local rl = reaction_labor(job.reaction_name)
        if rl and rl >= 0 then return rl end
    end
    local oks, sk = pcall(function() return df.job_type.attrs[job.job_type].skill end)
    if oks and sk and sk >= 0 then
        local okl, l2 = pcall(function() return df.job_skill.attrs[sk].labor end)
        if okl and l2 and l2 >= 0 then return l2 end
    end
    -- (0.105.48, A2-5) jobs whose type names no skill (ConstructSlab,
    -- ConstructCoffin, ConstructTable, ConstructDoor...): the memorial
    -- slab's engraving is the engraver's, the rest by the workshop
    local name = df.job_type[job.job_type]
    if name == 'EngraveSlab' then return df.unit_labor.ENGRAVER end
    local okh, kind = pcall(function()
        local b = dfhack.job.getHolder(job)
        return b and df.workshop_type[b.type] or nil
    end)
    if okh and kind and JOB_SHOP_LABOR[kind] then return df.unit_labor[JOB_SHOP_LABOR[kind]] end
    return nil
end

local function each_job(fn)
    local link = df.global.world.jobs.list.next
    while link do
        if link.item then fn(link.item) end
        link = link.next
    end
end

function waiting_work(limit)
    local by = {}
    each_job(function(job)
        if job.flags.suspend or dfhack.job.getWorker(job) then return end
        local l = job_labor(job)
        if l then by[l] = (by[l] or 0) + 1 end
    end)
    -- (r33c) idle: no job (as before: prayer and the tavern counted); free:
    -- no job, no social activity, not in the recreation burrow, not mad or
    -- caged (is_free): the ones who could take a waiting job now. B (26 Nov)
    -- read 28 "idle" holders of every labour while 8 were free
    local holders, idle, free = {}, {}, {}
    local rec = rec_member_ids()
    for _, u in ipairs(report_citizens(true)) do
        if grown(u) and not in_squad(u) then
            local none = u.job.current_job == nil
            local f = none and is_free(u, rec)
            for l in pairs(by) do
                if u.status.labors[l] then
                    holders[l] = (holders[l] or 0) + 1
                    if none then idle[l] = (idle[l] or 0) + 1 end
                    if f then free[l] = (free[l] or 0) + 1 end
                end
            end
        end
    end
    local rows = {}
    for l, n in pairs(by) do
        local tok = df.unit_labor[l]
        if tok then
            local wd, mode = detail_for(tok)
            table.insert(rows, {labor = tok, jobs = n, holders = holders[l] or 0, idle = idle[l] or 0,
                                free = free[l] or 0,
                                detail = wd and tostring(wd.name) or nil, mode = mode})
        end
    end
    table.sort(rows, function(a, b) return a.jobs > b.jobs end)
    local out = {}
    for i = 1, math.min(limit or 12, #rows) do out[i] = rows[i] end
    return out
end

-- Labours carried by a detail the AI may add to (not everybody/nobody), with
-- the dwarves skilled in it who aren't on it.
-- (0.105.119 item33) counted as assign() would pick them: never a
-- recreation member (its labours are off on purpose), and never a dwarf who
-- is on the detail already (the labour is held off by something else: a
-- post, a burrow; putting him on again changes nothing lasting)
function skilled_off(limit)
    local list = details() or {}
    local out = {}
    local seen = {}
    local rec = rec_member_ids()
    for _, d in ipairs(list) do
        local okm, m = pcall(function() return df.work_detail_mode[d.flags.mode] end)
        if okm and m ~= 'EverybodyDoesThis' and m ~= 'NobodyDoesThis' then
            for l = 0, df.unit_labor._last_item do
                local okl, allowed = pcall(function() return d.allowed_labors[l] end)
                if okl and allowed and not seen[l] then
                    seen[l] = true
                    local tok = df.unit_labor[l]
                    local sk = enum(df.job_skill, skill_token_for(l))
                    local n = 0
                    if sk then
                        for _, u in ipairs(report_citizens(true)) do
                            if grown(u) and not in_squad(u) and not u.status.labors[l] and skill(u, sk) >= SKILLED
                                    and not rec[u.id] and not is_member(d, u.id) then
                                n = n + 1
                            end
                        end
                    end
                    if n > 0 and tok then table.insert(out, {labor = tok, skilled = n, detail = tostring(d.name)}) end
                end
            end
        end
    end
    table.sort(out, function(a, b) return a.skilled > b.skilled end)
    local r = {}
    for i = 1, math.min(limit or 10, #out) do r[i] = out[i] end
    return r
end

local function name_of(u, txt) return U.name_of_raw(u, txt) end   -- (r6) ai-util's, not protected

-- Put up to `count` more dwarves on a job. Mining never past what the digging
-- and the picks want; woodcutting never past the axes. count 0 only puts the
-- details' member lists in order. skip_labors (optional, a list of labour
-- names): a dwarf holding any of them is not picked (fix3: no miner or
-- woodcutter made a hunter); nil leaves the choice as it always was.
function assign(job, count, dry_run, txt, min_skill, skip_labors)
    local J = job_spec(job)
    if not J then return {ok = false, rejected = true, error = 'unknown job: ' .. tostring(job)} end
    local labor = enum(df.unit_labor, J.labor)
    if not labor then return {ok = false, error = 'no ' .. J.labor .. ' labour in this DF version'} end
    local repaired = {}
    if not dry_run then
        local list = details() or {}
        for _, d in ipairs(list) do
            if repair(d) then table.insert(repaired, tostring(d.name)) end
        end
        if #repaired > 0 then
            for _, u in ipairs(report_citizens(true)) do recompute(u) end
        end
    end
    if (count or 0) <= 0 then
        return {ok = true, repaired = repaired, assigned = {}}
    end
    -- (13c) only this job's row (and, for mining, the digging waiting): the
    -- whole survey (every job, the map scans, the waiting work) ran here once
    local row, cands, wd = job_row(job)
    local mode = row.mode
    if mode == 'EverybodyDoesThis' then
        return {ok = false, rejected = true, survey = row, repaired = repaired,
                error = ('everybody already does this (the %s work detail is set to everybody)'):format(row.detail or job)}
    end
    if mode == 'NobodyDoesThis' then
        return {ok = false, rejected = true, survey = row, repaired = repaired,
                error = ('the %s work detail is set to nobody (your choice): the AI leaves it'):format(row.detail or job)}
    end
    local n, dig = count, 0
    if job == 'mining' then
        dig = count_designations(5000)
        local want = miners_wanted(dig, row.tools or 0, row.doing + row.candidates)
        n = math.min(n, math.max(0, want - row.doing))
    elseif J.tool then n = math.min(n, math.max(0, (row.tools or 0) - row.doing)) end
    if n <= 0 then
        return {ok = false, rejected = true, survey = row, repaired = repaired,
                error = job == 'mining'
                    and ('no more miners wanted (%d mining, %d picks free, %d tiles to dig)'):format(row.doing, row.tools or 0, dig)
                    or ('no free %s for another dwarf'):format(J.tool == 'AXE' and 'axe' or 'tool')}
    end
    if min_skill then
        local keep = {}
        for _, c in ipairs(cands) do if (c.skill or 0) >= min_skill then table.insert(keep, c) end end
        cands = keep
    end
    if type(skip_labors) == 'table' and #skip_labors > 0 then
        local skip = {}
        for _, name in ipairs(skip_labors) do
            local l = enum(df.unit_labor, name)
            if l then table.insert(skip, l) end
        end
        local keep = {}
        for _, c in ipairs(cands) do
            local u = df.unit.find(c.id)
            local held = false
            for _, l in ipairs(skip) do if u and has_labor(u, l) then held = true end end
            if not held then table.insert(keep, c) end
        end
        cands = keep
    end
    local picked = pick_workers(cands, n)
    if #picked == 0 then
        return {ok = false, rejected = true, survey = row, repaired = repaired,
                error = 'nobody outside the squads left for this job'}
    end
    local names, failed = {}, {}
    for _, c in ipairs(picked) do
        local u = df.unit.find(c.id)
        if u and dry_run then
            table.insert(names, name_of(u, txt))
        elseif u then
            if wd then insert_sorted(wd, u.id) end
            local ok = wd and recompute(u)
            if not ok then u.status.labors[labor] = true end   -- (no detail, or an old DFHack: set it directly)
            if has_labor(u, labor) then table.insert(names, name_of(u, txt))
            else table.insert(failed, name_of(u, txt)) end
        end
    end
    if #names == 0 then
        return {ok = false, survey = row, repaired = repaired,
                error = ('the game didn\'t give the %s labour (to %s)'):format(J.labor, table.concat(failed, ', '))}
    end
    return {ok = true, dry_run = dry_run or nil, job = job, assigned = names, failed = failed, survey = row,
            detail = row.detail, detail_mode = mode, repaired = repaired}
end

-- (0.104.10) Free time: a work detail set to "everybody does this" (DF's
-- default for planting and plant gathering) keeps every dwarf on call, and
-- Enxah's 88 citizens had 167 jobs and 3 idle while 44 badly wanted time with
-- friends. narrow() turns such a detail to "only selected" with the `keep`
-- most skilled at it; widen() turns it back. Only a detail the AI narrowed is
-- ever widened (site data 'ai-overseer/narrowed'); one you set otherwise is
-- left alone.
NARROWED_KEY = 'ai-overseer/narrowed'

function narrowed()
    return U.site_get(NARROWED_KEY, {})
end

local function set_mode(wd, name)
    local v = enum(df.work_detail_mode, name)
    if v == nil then return false end
    wd.flags.mode = v
    return true
end

function narrow(job, keep, dry_run, txt)
    local J = job_spec(job)
    if not J or not JOBS[job] then return {ok = false, rejected = true, error = 'unknown job: ' .. tostring(job)} end
    local wd, mode = detail_for(job)
    if not wd then return {ok = false, rejected = true, error = 'no work detail for ' .. job} end
    if mode ~= 'EverybodyDoesThis' then
        return {ok = false, rejected = true, error = ('the %s work detail is %s, not everybody: left as it is'):format(
            tostring(wd.name), tostring(mode))}
    end
    keep = math.max(1, math.min(30, keep or 5))
    -- (0.105.33) An "everybody" detail has already given the labour to nearly
    -- every civilian, so those holding it are candidates too (they were left
    -- out, and the narrowed detail kept nobody).
    local memo = {noble = {}}
    local doing, cands = citizens(job, memo)
    local sk = enum(df.job_skill, J.skill)
    local pool = {}
    for _, u in ipairs(doing) do table.insert(pool, cand_of(u, job, sk, memo)) end
    for _, c in ipairs(cands) do table.insert(pool, c) end
    local picked = pick_workers(pool, keep)
    if #picked < keep then
        return {ok = false, rejected = true, error = ('only %d civilians could take the %s work detail (keep %d): left as it is'):format(
            #picked, tostring(wd.name), keep)}
    end
    local names = {}
    for _, c in ipairs(picked) do
        local u = df.unit.find(c.id)
        if u then table.insert(names, name_of(u, txt)) end
    end
    local out = {ok = true, job = job, detail = tostring(wd.name), keep = #picked, workers = names, dry_run = dry_run or nil}
    if dry_run then return out end
    if enum(df.work_detail_mode, 'OnlySelectedDoesThis') == nil then
        return {ok = false, error = 'this DF has no "only selected" mode'}
    end
    for i = #wd.assigned_units - 1, 0, -1 do wd.assigned_units:erase(i) end
    for _, c in ipairs(picked) do insert_sorted(wd, c.id) end
    set_mode(wd, 'OnlySelectedDoesThis')
    for _, u in ipairs(report_citizens(true)) do recompute(u) end
    local n = narrowed()
    n[job] = true
    U.site_put(NARROWED_KEY, n)
    return out
end

function widen(job, dry_run)
    local n = narrowed()
    if not n[job] then return {ok = false, rejected = true, error = 'the AI never narrowed ' .. tostring(job)} end
    local wd, mode = detail_for(job)
    if not wd then return {ok = false, rejected = true, error = 'no work detail for ' .. tostring(job)} end
    if mode ~= 'OnlySelectedDoesThis' then
        n[job] = nil
        U.site_put(NARROWED_KEY, n)
        return {ok = false, rejected = true, error = 'the detail was changed since: left as it is'}
    end
    if dry_run then return {ok = true, dry_run = true, job = job} end
    if not set_mode(wd, 'EverybodyDoesThis') then return {ok = false, error = 'no "everybody" mode'} end
    for _, u in ipairs(report_citizens(true)) do recompute(u) end
    n[job] = nil
    U.site_put(NARROWED_KEY, n)
    return {ok = true, job = job, detail = tostring(wd.name)}
end

-- (0.104.166) A detail with far more on it than the job needs: all but the
-- `keep` best taken off ("only selected" details only; one the player set to
-- everybody or nobody is left alone). Teacheroar, 1 Nov: 84 civilians on the
-- Fisherdwarves detail (2 wanted, no fish ever caught in its stagnant and
-- cavern water); 26 had fishing as their best skill and 4 of the 8 miserable
-- were fisherdwarves, alone at the water for days, missing friends, crafts
-- and prayer. Those breaking down (stress category 1 or worse) are never kept.
function trim(job, keep, dry_run, txt)
    local J = job_spec(job)
    if not J or not JOBS[job] then return {ok = false, rejected = true, error = 'unknown job: ' .. tostring(job)} end
    local wd, mode = detail_for(job)
    if not wd then return {ok = false, rejected = true, error = 'no work detail for ' .. job} end
    if mode ~= 'OnlySelectedDoesThis' then
        return {ok = false, rejected = true, error = ('the %s work detail is %s, not "only selected": left as it is'):format(
            tostring(wd.name), tostring(mode))}
    end
    keep = math.max(0, math.min(30, keep or 2))
    local sk = enum(df.job_skill, J.skill)
    local calm, all = {}, {}
    for _, id in ipairs(ids_of(wd)) do
        local u = df.unit.find(id)
        if u then
            local okc, cat = pcall(dfhack.units.getStressCategory, u)
            local noble = false
            pcall(function() noble = #dfhack.units.getNoblePositions(u) > 0 end)
            local c = {id = id, skill = skill(u, sk), other = best_other(u, sk), idle = false, noble = noble, busy = 0}
            table.insert(all, c)
            if not (okc and type(cat) == 'number' and cat <= 1) then table.insert(calm, c) end
        end
    end
    if #all <= keep then
        return {ok = false, rejected = true, error = ('only %d on the %s work detail (keep %d)'):format(#all, tostring(wd.name), keep)}
    end
    local kept = pick_workers(calm, keep)
    if #kept < keep then
        -- (0.105.33) too few calm ones: the rest from those breaking down,
        -- rather than nobody on the detail at all
        local have = {}
        for _, c in ipairs(kept) do have[c.id] = true end
        local rest = {}
        for _, c in ipairs(all) do if not have[c.id] then table.insert(rest, c) end end
        for _, c in ipairs(pick_workers(rest, keep - #kept)) do table.insert(kept, c) end
    end
    local names = {}
    for _, c in ipairs(kept) do
        local u = df.unit.find(c.id)
        if u then table.insert(names, name_of(u, txt)) end
    end
    local out = {ok = true, job = job, detail = tostring(wd.name), was = #all, kept = #kept, removed = #all - #kept,
                 workers = names, dry_run = dry_run or nil}
    if dry_run then return out end
    for i = #wd.assigned_units - 1, 0, -1 do wd.assigned_units:erase(i) end
    for _, c in ipairs(kept) do insert_sorted(wd, c.id) end
    for _, u in ipairs(report_citizens(true)) do recompute(u) end
    local doing = citizens(job)
    out.still = #doing          -- with the labour after (another detail may carry it too)
    return out
end

-- Mark up to `count` shrubs near the fort for gathering.
function gather_plants(count, dry_run)
    local c = centre()
    if not c then return {ok = false, error = 'no fort centre (no wagon and no citizens on the map)'} end
    local n = shrubs(c, math.min(count or GATHER_MAX, GATHER_MAX), not dry_run)
    if not dry_run then SCAN_CACHE = nil end     -- (0.100) the marked shrubs: count again next report
    if n == 0 then
        return {ok = false, rejected = true,
                error = ('no shrubs to gather within %d tiles of %s'):format(GATHER_RADIUS, c.what or 'the fort')}
    end
    return {ok = true, dry_run = dry_run or nil, marked = n, near = c.what}
end


-- Too many plant-gathering jobs waiting: a fort marked shrubs far and wide
-- (bridge 0.38-0.40), and ~850 jobs stood in the job list a year later, the
-- fort full of food. Waiting gathering jobs nobody has taken are cancelled,
-- the farthest from the fort first, down to `keep`. Pure part first.

-- jobs: {{id, d (distance), taken}}; the ids to cancel.
function gathering_to_cancel(jobs, keep)
    local free = {}
    for _, j in ipairs(jobs) do
        if not j.taken then table.insert(free, j) end
    end
    table.sort(free, function(a, b)
        if a.d ~= b.d then return a.d > b.d end
        return a.id < b.id
    end)
    local taken = #jobs - #free
    local out = {}
    local excess = #jobs - math.max(keep, taken)
    for i = 1, math.min(excess, #free) do table.insert(out, free[i].id) end
    return out
end

local function has_worker(job)
    for _, ref in ipairs(job.general_refs) do
        if df.general_ref_unit_workerst:is_instance(ref) then return true end
    end
    return false
end

-- (item4) The fruit-gathering zones' boxes ({x1, y1, x2, y2, z}): DF makes
-- a zone's GatherPlants jobs again from the zone itself, so cancelling them
-- doesn't stick (B, 24 Nov: "135 plant-gathering jobs wait ... cancel all but
-- 20" done 29 times in 1.5 hours). A zone lies on its trees' floor; the
-- fruit hangs in the crowns above it (ZONE_CROWN levels).
ZONE_CROWN = 12
local function gather_zones()
    local out = {}
    pcall(function()
        local CIV = df.building_type.Civzone
        for _, b in ipairs(df.global.world.buildings.all) do
            pcall(function()
                if b:getType() == CIV and df.civzone_type[b.type] == 'PlantGathering' then
                    table.insert(out, {x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z})
                end
            end)
        end
    end)
    return out
end

-- Pure: is (x, y, z) over one of the zones' boxes (its floor or a crown above)?
function in_gather_zone(zones, x, y, z)
    for _, b in ipairs(zones) do
        if x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 and z >= b.z and z <= b.z + ZONE_CROWN then
            return true
        end
    end
    return false
end

local function zone_job(j, zones)
    local okr, ref = pcall(function()
        for _, r in ipairs(j.general_refs) do
            if df.general_ref_building_civzone_assignedst and df.general_ref_building_civzone_assignedst:is_instance(r) then
                return true
            end
        end
        return false
    end)
    if okr and ref then return true end
    return in_gather_zone(zones, j.pos.x, j.pos.y, j.pos.z)
end

function trim_gathering(keep, dry_run)
    keep = math.max(0, keep or 20)
    local c = centre() or {x = 0, y = 0, z = 0}
    local jobs, by_id = {}, {}
    local zones, zoned = gather_zones(), 0
    local GATHER = df.job_type.GatherPlants
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j and j.job_type == GATHER then
            if zone_job(j, zones) then
                zoned = zoned + 1      -- (item4) a fruit zone's: DF makes it again, left
            else
                local d = math.abs(j.pos.x - c.x) + math.abs(j.pos.y - c.y) + 3 * math.abs(j.pos.z - c.z)
                table.insert(jobs, {id = j.id, d = d, taken = has_worker(j)})
                by_id[j.id] = j
            end
        end
        link = link.next
    end
    -- (item4) the zones' jobs count toward what is kept: only marked plants' beyond it go
    local cancel = gathering_to_cancel(jobs, math.max(0, keep - zoned))
    if #cancel == 0 then
        if zoned > 0 then
            return {ok = false, rejected = true, zone_jobs = zoned, jobs = #jobs + zoned,
                    error = ('%d of the %d plant-gathering jobs are fruit zones\' (the game makes them again): '
                             .. 'nothing to cancel'):format(zoned, #jobs + zoned)}
        end
        return {ok = false, rejected = true, error = ('only %d plant-gathering jobs: nothing to cancel'):format(#jobs)}
    end
    if dry_run then return {ok = true, dry_run = true, jobs = #jobs + zoned, zone_jobs = zoned, cancel = #cancel} end
    local done, unmarked = 0, 0
    for _, id in ipairs(cancel) do
        local j = by_id[id]
        -- (the shrub's gather mark goes too, or the game makes the job again)
        pcall(function()
            local d = dfhack.maps.getTileFlags(j.pos)
            if d and d.dig ~= df.tile_dig_designation.No then
                d.dig = df.tile_dig_designation.No
                unmarked = unmarked + 1
            end
        end)
        if pcall(dfhack.job.removeJob, j) then done = done + 1 end
    end
    if done == 0 then return {ok = false, error = 'the game would not cancel the gathering jobs'} end
    return {ok = true, jobs = #jobs + zoned, cancelled = done, left = #jobs + zoned - done,
            zone_jobs = zoned > 0 and zoned or nil, unmarked = unmarked}
end
