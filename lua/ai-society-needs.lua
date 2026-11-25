-- ai-society-needs: the population cap and a dwarf leaving, idle crafting, trinkets, what is
-- stressing the fort, the citizens' clothes and the cups nobody hauls.
--
-- (r8) A part of ai-society, not a script of its own: ai-society.lua loads it
-- into its own environment, so every name here is reqscript('ai-society').name
-- and the names defined there and in the parts before it are in reach.

if not SOCIETY_PART_LOCALS then qerror('ai-society-needs is a part of ai-society; run ai-society') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-needs'] = '0.105.112'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens = SOCIETY_PART_LOCALS.U, SOCIETY_PART_LOCALS.report_citizens   -- (r8) the hub's locals

-- The population cap (DF's own setting: migrants stop coming at it). Where
-- the game keeps it moved between versions, so a few places are tried.
-- A change lasts for this session; the overseer sets it again after a restart.
local function popcap_holder()
    local tries = {
        function() return df.global.d_init.dwarf end,
        function() return df.global.d_init end,
    }
    for _, f in ipairs(tries) do
        local ok, t = pcall(f)
        if ok and t then
            local ok2, v = pcall(function() return t.population_cap end)
            if ok2 and type(v) == 'number' then return t end
        end
    end
    return nil
end

function get_popcap()
    local t = popcap_holder()
    if not t then return nil end
    local ok, strict = pcall(function() return t.strict_population_cap end)
    -- (item5) DF's baby caps (no conception past either), where this DF has them
    local okb, babies = pcall(function() return t.baby_cap_absolute end)
    local okp, pct = pcall(function() return t.baby_cap_percent end)
    return {cap = t.population_cap, strict = ok and strict or nil,
            baby_cap = okb and type(babies) == 'number' and babies or nil,
            baby_pct = okp and type(pct) == 'number' and pct or nil}
end

function set_popcap(cap, strict, babies, pct)
    local t = popcap_holder()
    if not t then return {ok = false, error = 'this DF version keeps the population cap somewhere the AI can\'t find'} end
    t.population_cap = cap
    pcall(function() t.strict_population_cap = strict end)
    local out = {ok = true, cap = cap, strict = strict}
    -- (item5) the baby caps only ever raised
    if babies then
        pcall(function()
            if t.baby_cap_absolute < babies then t.baby_cap_absolute = babies; out.baby_cap = babies end
        end)
    end
    if pct then
        pcall(function()
            if t.baby_cap_percent < pct then t.baby_cap_percent = pct; out.baby_pct = pct end
        end)
    end
    return out
end

-- Extreme low Growth: the fort slowly shrinks. One dwarf leaves, the way
-- DFHack's own emigration tool sends dwarves away: the least skilled adult
-- citizen who isn't a noble, a soldier or chained (emigration's canLeave).
-- unit_id: that citizen (a vampire the AI sends away), whatever their skills
function expel_one(txt, unit_id)
    local ok, em = pcall(reqscript, 'emigration')
    if not ok or type(em.desert) ~= 'function' or type(em.canLeave) ~= 'function' then
        return {ok = false, error = "DFHack's emigration tool isn't available"}
    end
    local best, best_score
    if unit_id then
        best = df.unit.find(unit_id)
        if not best or not dfhack.units.isCitizen(best, true) then
            return {ok = false, rejected = true, error = 'no citizen with id ' .. tostring(unit_id)}
        end
        -- (0.100, security pass) a named dwarf is sent away only for being a
        -- vampire (the rule's one use); anyone else goes by the usual pick,
        -- which leaves nobles, soldiers and children
        local okb, vamp = pcall(dfhack.units.isBloodsucker, best)
        if not (okb and vamp) then
            return {ok = false, rejected = true, error = 'only a vampire is sent away by name'}
        end
    end
    for _, u in ipairs(unit_id and {} or report_citizens(true)) do
        local okc, can = pcall(em.canLeave, u)
        if okc and can then
            local score = 0
            local soul = u.status.current_soul
            if soul then for _, sk in ipairs(soul.skills) do score = score + sk.rating end end
            if not best or score < best_score then best, best_score = u, score end
        end
    end
    if not best then
        return {ok = false, rejected = true, error = 'nobody can leave (nobles, soldiers and children stay)'}
    end
    local civ = df.global.plotinfo.civ_id
    pcall(function()
        local fort = U.fort_entity()
        civ = fort.entity_links[0].target           -- as emigration does when nobody visits
    end)
    local name = txt and txt(dfhack.units.getReadableName(best)) or tostring(best.id)
    local okd, err = pcall(em.desert, best, 'wild', civ)
    if not okd then return {ok = false, error = 'emigration failed: ' .. tostring(err)} end
    return {ok = true, unit_id = best.id, name = name}
end

-- --- recreational crafting (DFHack's idle-crafting) ----------------------------------
--
-- Dwarves who need to craft (the CraftObject need) can craft for themselves
-- at a Craftsdwarf's workshop marked for it: what idle-crafting's toggle on
-- the workshop's Workers tab does. Done through its saved state (enabled, the
-- allowed workshops) and its own map-loaded handler, which reads that state
-- and starts it.
IC_KEY = 'idle-crafting'

local function ic_state()
    return U.site_get(IC_KEY, {})
end

function idle_crafting_status()
    local d = ic_state()
    local n = 0
    for _ in pairs(type(d.allowed) == 'table' and d.allowed or {}) do n = n + 1 end
    return {enabled = d.enabled == true, workshops = n}
end

function idle_crafting(dry_run)
    local ok = pcall(reqscript, 'idle-crafting')
    if not ok then return {ok = false, rejected = true, error = 'DFHack has no idle-crafting script'} end
    -- every finished Craftsdwarf's workshop not kept for certain workers
    -- and not already allowed (one served a hundred dwarves poorly: Oct 23)
    local d = ic_state()
    d.allowed = type(d.allowed) == 'table' and d.allowed or {}
    local picks = {}
    local okl, list = pcall(function() return df.global.world.buildings.other.WORKSHOP_ANY end)
    for _, b in ipairs(okl and list or df.global.world.buildings.all) do
        local okt, is = pcall(function()
            return b:getType() == df.building_type.Workshop and b.type == df.workshop_type.Craftsdwarfs
                and b:getBuildStage() >= b:getMaxBuildStage() and #b.profile.permitted_workers == 0
        end)
        if okt and is and d.allowed[tostring(b.id)] == nil then table.insert(picks, b) end
    end
    if #picks == 0 then return {ok = false, rejected = true, error = 'no Craftsdwarf\'s workshop free for it'} end
    local pick = picks[1]
    if dry_run then return {ok = true, dry_run = true, workshop = pick.id, workshops = #picks} end
    for _, b in ipairs(picks) do d.allowed[tostring(b.id)] = -1 end
    d.enabled = true
    dfhack.persistent.saveSiteData(IC_KEY, d)
    local handler = dfhack.onStateChange[IC_KEY]
    if not handler then return {ok = false, error = 'idle-crafting is not loaded'} end
    local okh, err = pcall(handler, SC_MAP_LOADED)
    if not okh then return {ok = false, error = 'idle-crafting did not start: ' .. tostring(err):sub(1, 160)} end
    return {ok = true, workshop = pick.id, added = #picks}
end

-- Count of finished Craftsdwarf's workshops (for the report).
function craft_shops()
    local n = 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            if b:getType() == df.building_type.Workshop and b.type == df.workshop_type.Craftsdwarfs
                    and b:getBuildStage() >= b:getMaxBuildStage() then n = n + 1 end
        end
    end)
    return n
end

-- --- things to own (the AcquireObject need) -----------------------------------------
--
-- A dwarf who wants to own things gets one by picking up an item while
-- hauling it, which rarely happens in a fort that stores crafts in bins and
-- sells the rest (79 of 100 dwarves badly wanted something on Oct 23). The AI
-- gives each such dwarf a free trinket: the item becomes theirs (the game's
-- own ownership: they keep it in their room) and the need counts as met, as
-- when they pick one up themselves.
TRINKETS = {'RING', 'EARRING', 'AMULET', 'BRACELET', 'CROWN', 'SCEPTER', 'FIGURINE', 'TOTEM'}
ACQUIRE_DISTRACTED = -1000
SATISFIED_FOCUS = 400              -- the top of the "not distracted" range

local function free_trinket(item)
    local f = item.flags
    if not U.item_free(item, {held = true}) then return false end   -- (on the ground or in a bin, below)
    local ok, owner = pcall(dfhack.items.getOwner, item)
    if ok and owner then return false end
    -- loose on the ground, or in a bin (a container on the ground)
    if f.on_ground then return true end
    local okc, c = pcall(dfhack.items.getContainer, item)
    return okc and c ~= nil and c.flags.on_ground and not c.flags.in_building and not c.flags.forbid
end

function free_trinkets(limit)
    local out = {}
    for _, name in ipairs(TRINKETS) do
        local ok, list = pcall(function() return df.global.world.items.other[name] end)
        if ok and list then
            for _, item in ipairs(list) do
                if limit and #out >= limit then return out end
                if free_trinket(item) then table.insert(out, item) end
            end
        end
    end
    return out
end

-- (0.104.141) The trinkets there are, by where they are: free (to give),
-- owned, in a job, at the depot or a trader's, forbidden, in a building
-- (a bin in a workshop...), carried, other.
-- (13c) `where` (what holds those in a job or "other") is a sample of the
-- first WHERE_SAMPLE: Teacheroar's 7,000 such took a container or job
-- look-up and a string each, every daily report; `where_sampled` says how many
WHERE_SAMPLE = 300
function trinket_census()
    local out = {free = 0, owned = 0, in_job = 0, trade = 0, forbidden = 0, in_building = 0, carried = 0, other = 0}
    local sampled = 0
    for _, name in ipairs(TRINKETS) do
        local ok, list = pcall(function() return df.global.world.items.other[name] end)
        if ok and list then
            for _, item in ipairs(list) do
                local okk, k = pcall(function()
                    local f = item.flags
                    if f.removed or f.garbage_collect or f.artifact then return nil end
                    if free_trinket(item) then return 'free' end
                    if f.owned then return 'owned' end
                    if f.in_job then return 'in_job' end
                    if f.trader then return 'trade' end
                    if f.in_building then
                        local b = dfhack.items.getHolderBuilding(item)
                        if b and b:getType() == df.building_type.TradeDepot then return 'trade' end
                    end
                    if f.forbid then return 'forbidden' end
                    if f.in_inventory then return 'carried' end
                    if f.in_building then return 'in_building' end
                    return 'other'
                end)
                if okk and k then out[k] = out[k] + 1 end
                -- (0.104.141) what holds the ones not free: Teacheroar showed 0
                -- free, 16 owned, 1,232 in jobs and 5,884 "other"
                if okk and (k == 'other' or k == 'in_job') and sampled < WHERE_SAMPLE then
                    sampled = sampled + 1
                    pcall(function()
                        local where
                        if k == 'in_job' then
                            local ref = dfhack.items.getSpecificRef(item, df.specific_ref_type.JOB)
                            local j = ref and ref.data.job
                            where = 'job ' .. (j and df.job_type[j.job_type] or '?')
                        else
                            local c = dfhack.items.getContainer(item)
                            if not c then
                                where = 'loose'
                            else
                                local cf = c.flags
                                local cb = cf.in_building and dfhack.items.getHolderBuilding(c)
                                where = df.item_type[c:getType()] .. (cf.forbid and ' forbidden' or '')
                                    .. (cf.in_job and ' in a job' or '') .. (cf.in_inventory and ' carried' or '')
                                    .. (cb and (' in ' .. (df.building_type[cb:getType()] or '?')) or '')
                                    .. (cf.on_ground and '' or ' not on ground')
                            end
                        end
                        out.where = out.where or {}
                        out.where[where] = (out.where[where] or 0) + 1
                    end)
                end
            end
        end
    end
    if sampled > 0 then out.where_sampled = sampled end
    return out
end

-- (0.104.141) Butchered bones a craftsdwarf could carve (loose or in a bin,
-- not forbidden or in a job), counted up to `limit`.
-- (0.104.157) What is stressing the fort, in DF's own words: each citizen's
-- emotions of the last STRESS_DAYS days by the thought behind them
-- (df.unit_thought_type), summed by how much stress each adds (strength /
-- the emotion's divider; a negative divider eases stress). Teacheroar, 1 Nov:
-- 9 miserable, 21 very unhappy, and miserable children with no unmet need:
-- the needs alone can't say why. {causes = [{thought, citizens, stress,
-- emotions}] (the worst first, 15), eased = [...] (8), citizens, read}.
STRESS_DAYS = 28
STRESS_TOP, EASED_TOP = 15, 8

local function emotion_divider(t)
    local ok, d = pcall(function() return df.emotion_type.attrs[t].divider end)
    if ok and type(d) == 'number' then return d end
    return nil
end

-- (0.104.168) what a few thoughts were about (DF's subthought, its
-- circumstance): a complaint nobody heard (UnableComplain, COMPLAINT_UNREGISTERED)
-- carries DF's reason (history_event_reason: insufficient_work,
-- work_request, make_weapon, vent_at_boss, cry_on_boss), and a hated
-- vermin seen (AnnoyedVermin, NEAR_HATED_VERMIN) the creature (assumed the
-- race id: the caption is "accosted by [vermin]"). Tallied per thought as
-- `about` = {word = n}. Teacheroar, 1 Nov: 24 citizens unable to complain,
-- 15 accosted by vermin, and the census couldn't say why or by what.
local function about_reason(sub) return df.history_event_reason[sub] end
local function about_creature(sub)
    local cr = df.creature_raw.find(sub)
    return cr and cr.creature_id or nil
end
STRESS_ABOUT = {UnableComplain = about_reason, Complained = about_reason,
                AnnoyedVermin = about_creature, NearVermin = about_creature}

function stress_census(units)
    local now = U.abs_tick()
    local since = now - STRESS_DAYS * 1200
    local by, citizens, read, no_divider = {}, 0, 0, 0
    for _, u in ipairs(units or report_citizens()) do
        citizens = citizens + 1
        local ok, ems = pcall(function() return u.status.current_soul.personality.emotions end)
        if ok and ems then
            read = read + 1
            local seen = {}
            local okc, child = pcall(function() return dfhack.units.isChild(u) or dfhack.units.isBaby(u) end)
            child = okc and child or false
            for _, em in ipairs(ems) do
                local okt, when = pcall(function() return U.abs_tick(em.year, em.year_tick) end)
                if not okt or when >= since then
                    local name = df.unit_thought_type[em.thought] or tostring(em.thought)
                    local d = emotion_divider(em.type)
                    local stress = 0
                    if d and d ~= 0 then stress = (em.strength or 0) / d else no_divider = no_divider + 1 end
                    local e = by[name] or {thought = name, citizens = 0, stress = 0, emotions = 0, kinds = {}}
                    e.stress, e.emotions = e.stress + stress, e.emotions + 1
                    local ek = df.emotion_type[em.type] or tostring(em.type)
                    e.kinds[ek] = (e.kinds[ek] or 0) + 1
                    local about = STRESS_ABOUT[name]          -- (0.104.168)
                    if about then
                        local okw, w = pcall(function() return about(em.subthought) end)
                        if okw and w ~= nil then
                            e.about = e.about or {}
                            e.about[tostring(w)] = (e.about[tostring(w)] or 0) + 1
                        end
                    end
                    if not seen[name] then
                        seen[name], e.citizens = true, e.citizens + 1
                        if child then e.children = (e.children or 0) + 1 end   -- (0.104.159)
                    end
                    by[name] = e
                end
            end
        end
    end
    local worse, eased = {}, {}
    for _, e in pairs(by) do
        e.stress = math.floor(e.stress + 0.5)
        local top, topn = nil, 0
        for k, n in pairs(e.kinds) do if n > topn then top, topn = k, n end end
        e.emotion, e.kinds = top, nil
        if e.stress > 0 then table.insert(worse, e) elseif e.stress < 0 then table.insert(eased, e) end
    end
    table.sort(worse, function(a, b) return a.stress > b.stress end)
    table.sort(eased, function(a, b) return a.stress < b.stress end)
    while #worse > STRESS_TOP do table.remove(worse) end
    while #eased > EASED_TOP do table.remove(eased) end
    -- (0.105.46) the citizens upset by the same old booze, kept whether or
    -- not it is among the top STRESS_TOP (the scorecard read 0 when it fell off)
    local sb = by.SameBooze
    return {causes = worse, eased = eased, citizens = citizens, read = read, days = STRESS_DAYS,
            no_divider = no_divider > 0 and no_divider or nil,
            same_booze = (sb and sb.stress > 0) and sb.citizens or 0}
end

-- (0.104.157) The citizens' clothes: worn items by wear (DF's 0 new .. 3
-- tattered, "XX"), and how many go without shoes, something on the legs
-- (trousers, skirt) or the body (shirt, robe, armour). Babies left out.
-- {citizens, worn = {new, worn, threadbare, tattered}, without = {shoes,
-- legs, body}, tattered_wearers}.
-- Items of one kind (df.items_other_id) no one holds: not owned, worn,
-- carried, forbidden, in a job, at the depot or kept in a building (a
-- location's chest).
-- With `detail`, also what the free ones are (0.104.157: 118 free shoes and
-- 34 free cups lay in store while 63 went barefoot and 149 drank without a
-- cup): {n, kinds = {subtype = n}, races = {maker race = n}, stored = {in a
-- container, loose}}.
-- (0.104.168) WHY THE USED CUPS AREN'T HAULED. Teacheroar, 1 Nov: 34 free
-- cups lay loose in a dining hall (10) and a meeting hall (24) for hours with
-- 79 of 107 finished goods tiles free, 137 citizens drinking without a cup
-- (dwarves drink only from cups on a stockpile). For each free cup off the
-- piles, the first reason found (free_cups_detail.why):
--   location            in a zone of a location (a tavern keeps its own cups:
--                       DF doesn't haul them away; why_locations by type)
--   pile_refuses        no finished goods pile takes goblets at all
--   pile_refuses_material  piles take goblets, not of this material
--   pile_refuses_quality   ... not of this quality
--   links_only          the only piles that take it take from links only
--   no_room             the piles that take it are full
--   unreachable         on a tile walked to by no citizen
--   should_haul         nothing found: DF should haul it (a hauling backlog)
-- And every cup's flags (free_cups_detail.flags: forbid, owned, dump...), so
-- what is still unknown can be read from the next report in the game.
CUP_FLAGS = {'forbid', 'owned', 'dump', 'in_job', 'in_building', 'in_inventory', 'trader', 'on_ground', 'hidden'}
-- DF's finished goods "other materials" (DFHack's stockpiles plugin order):
-- wood first, bone, tooth, horn, pearl, shell (2-6), the glasses at 11-13
CUP_OTHER_MATS = {wood = 0, bone = 2, tooth = 3, horn = 4, pearl = 5, shell = 6,
                  green_glass = 11, clear_glass = 12, crystal_glass = 13}
CUP_DEPOT_REACH = 8      -- (0.104.168, review) a finished goods pile this near a depot is the caravans' (FEEDERS.Depot)

-- The cup's material: {kind = 'inorganic' | 'wood' | <glass> | 'other', index}.
function cup_material(it)
    local out = {kind = 'other'}
    pcall(function()
        local mi = dfhack.matinfo.decode(it)
        if not mi then return end
        if mi.inorganic then out.kind, out.index = 'inorganic', mi.index return end
        local tok = tostring(mi:getToken() or '')
        if tok:find('GLASS_GREEN') then out.kind = 'green_glass'
        elseif tok:find('GLASS_CLEAR') then out.kind = 'clear_glass'
        elseif tok:find('GLASS_CRYSTAL') then out.kind = 'crystal_glass'
        elseif mi.plant and mi.material and mi.material.flags.WOOD then out.kind = 'wood'
        elseif mi.material then
            -- (0.104.168, review) bone, horn, shell... by the material's own flags
            for _, k in ipairs({'BONE', 'TOOTH', 'HORN', 'PEARL', 'SHELL'}) do
                local okf, on = pcall(function() return mi.material.flags[k] end)
                if okf and on then out.kind = k:lower() break end
            end
        end
    end)
    return out
end

-- The fort's finished goods piles: {b, takes_goblets, links_only, free,
-- depot (the caravans' pile beside a depot), outdoor, x, y, z (its middle)}.
function cup_piles()
    local out = {}
    local depots = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRADE_DEPOT) do table.insert(depots, b) end
    end)
    pcall(function()
        local gob = df.item_type.GOBLET
        for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
            local okf, on = pcall(function() return sp.settings.flags.finished_goods end)
            if okf and on then
                local p = {b = sp, free = 0, x = (sp.x1 + sp.x2) // 2, y = (sp.y1 + sp.y2) // 2, z = sp.z}
                for _, dp in ipairs(depots) do
                    if dp.z == sp.z and sp.x2 >= dp.x1 - CUP_DEPOT_REACH and sp.x1 <= dp.x2 + CUP_DEPOT_REACH
                            and sp.y2 >= dp.y1 - CUP_DEPOT_REACH and sp.y1 <= dp.y2 + CUP_DEPOT_REACH then
                        p.depot = true
                    end
                end
                pcall(function() p.outdoor = dfhack.maps.getTileFlags(p.x, p.y, p.z).outside == true end)
                pcall(function() p.takes_goblets = sp.settings.finished_goods.type[gob] and true or false end)
                pcall(function() p.links_only = sp.stockpile_flag.use_links_only == true end)   -- (0.105.41) 53.x: the flag lives in stockpile_flag
                pcall(function()
                    for y = sp.y1, sp.y2 do
                        for x = sp.x1, sp.x2 do
                            local des, occ = dfhack.maps.getTileFlags(x, y, sp.z)
                            if des and des.pile and not occ.item then p.free = p.free + 1 end
                        end
                    end
                end)
                table.insert(out, p)
            end
        end
    end)
    return out
end

-- Does this pile take this cup? true, or false and why.
function pile_takes_cup(p, it, mat)
    if not p.takes_goblets then return false, 'pile_refuses' end
    local fg = p.b.settings.finished_goods
    local okm, matok = pcall(function()
        if mat.kind == 'inorganic' then return fg.mats[mat.index] and true or false end
        local i = CUP_OTHER_MATS[mat.kind]
        if i then return fg.other_mats[i] and true or false end
        -- (0.104.168, review) a material not known here: taken only if the
        -- pile takes some "other material" at all
        for _, v in ipairs(fg.other_mats) do if v then return true end end
        return false
    end)
    if okm and matok == false then return false, 'pile_refuses_material' end
    local okq, qok = pcall(function() return fg.quality_core[it:getQuality()] and true or false end)
    if okq and qok == false then return false, 'pile_refuses_quality' end
    -- (0.104.168, review) the overall quality (with its decorations) too
    local okt, tok = pcall(function() return fg.quality_total[it:getOverallQuality()] and true or false end)
    if okt and tok == false then return false, 'pile_refuses_quality' end
    if p.links_only then return false, 'links_only' end
    if p.free <= 0 then return false, 'no_room' end
    return true
end

-- The location (its type) whose zone holds this tile, or nil.
function location_at(pos)
    local t
    pcall(function()
        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(pos) or {}) do
            local lid = zn.location_id
            if lid and lid >= 0 and not t then
                t = 'location'
                pcall(function()
                    local site = dfhack.world.getCurrentSite()
                    for _, b in ipairs(site.buildings) do
                        if b.id == lid then t = df.abstract_building_type[b:getType()] or 'location' end
                    end
                end)
            end
        end
    end)
    return t
end

function cup_citizen_groups()
    local g = {}
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local okg, w = pcall(dfhack.maps.getWalkableGroup, xyz2pos(dfhack.units.getPosition(u)))
            if okg and w and w ~= 0 then g[w] = true end
        end
    end)
    return g
end

local CUP_RANK = {pile_refuses = 1, pile_refuses_material = 2, pile_refuses_quality = 3, links_only = 4, no_room = 5}

-- Why this free cup (off the piles, at pos) isn't hauled: the first reason
-- (and, for a location, its type).
function cup_why(it, pos, ctx)
    local loc = location_at(pos)
    if loc then return 'location', loc end
    local mat = cup_material(it)
    local best, rank = nil, 0
    for _, p in ipairs(ctx.piles) do
        local ok, why = pile_takes_cup(p, it, mat)
        if ok then rank = 99 break end
        if (CUP_RANK[why] or 0) > rank then best, rank = why, CUP_RANK[why] end
    end
    if rank ~= 99 then return best or 'pile_refuses' end
    if next(ctx.groups) then
        local okg, w = pcall(dfhack.maps.getWalkableGroup, pos)
        if okg and w and w ~= 0 and not ctx.groups[w] then return 'unreachable' end
    end
    return 'should_haul'
end

-- (0.104.168, review) A tile in a zone indoors (a hall, a dining room), not
-- a location's (a tavern keeps its own) and not under the sky (a pasture).
function cup_in_indoor_hall(pos)
    local okz, zs = pcall(dfhack.buildings.findCivzonesAt, pos)
    if not okz or not zs or #zs == 0 or location_at(pos) then return false end
    local oko, out_ = pcall(function() return dfhack.maps.getTileFlags(pos.x, pos.y, pos.z).outside end)
    return not (oko and out_)
end

-- (0.104.168) What the AI can fix of it itself (`accept_cups` in the bridge):
-- when loose cups lie that no pile takes, the finished goods pile with the
-- most room is set to take goblets (and those cups' materials and quality);
-- loose forbidden cups in a hall (a zone, not a location's) are unforbidden.
-- Never the cups of a location (a tavern's), on a pile, or held by anything.
function accept_cups(dry_run)
    local ok, list = pcall(function() return df.global.world.items.other.GOBLET end)
    if not ok or not list then return {ok = false, error = 'no item list for cups'} end
    local piles = cup_piles()
    local out = {ok = true, dry_run = dry_run or nil, unforbidden = 0, piles_set = 0, materials_set = 0}
    local refused, forbidden = {}, {}
    for _, it in ipairs(list) do
        pcall(function()
            local f = it.flags
            if f.removed or f.garbage_collect or f.artifact or f.owned or f.in_inventory or f.in_job or f.trader
                    or f.in_building or f.dump or f.construction or not f.on_ground then return end
            local x, y, z = dfhack.items.getPosition(it)
            local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
            local okb, b = pcall(dfhack.buildings.findAtTile, pos)
            if okb and b and b:getType() == df.building_type.Stockpile then return end
            if location_at(pos) then return end
            if f.forbid then
                if cup_in_indoor_hall(pos) and dfhack.maps.getWalkableGroup(pos) ~= 0 then table.insert(forbidden, it) end
                return
            end
            -- (0.104.168, review) as the census counts them: in a container never here
            if dfhack.items.getContainer(it) then return end
            local mat = cup_material(it)
            local takes = false
            for _, p in ipairs(piles) do
                local okp, yes, why = pcall(pile_takes_cup, p, it, mat)
                if okp and (yes or why == 'no_room' or why == 'links_only') then takes = true break end
            end
            if not takes then table.insert(refused, {it = it, mat = mat, pos = pos}) end
        end)
    end
    out.cups_refused, out.cups_forbidden = #refused, #forbidden
    if #refused == 0 and #forbidden == 0 then
        return {ok = false, rejected = true,
                error = 'no loose cup is refused by every finished goods pile, nor forbidden in a hall'}
    end
    -- (0.104.168, review) the pile nearest the cups, with room, indoors and
    -- not the caravans' pile beside the depot (cups sent there would be sold)
    local best, best_d
    if #refused > 0 then
        for _, p in ipairs(piles) do
            if not p.links_only and p.free > 0 and not p.depot and not p.outdoor then
                local dist = 0
                for _, r in ipairs(refused) do
                    dist = dist + math.abs(r.pos.x - p.x) + math.abs(r.pos.y - p.y) + 10 * math.abs(r.pos.z - p.z)
                end
                if not best or dist < best_d then best, best_d = p, dist end
            end
        end
        if not best and #forbidden == 0 then
            return {ok = false, rejected = true,
                    error = ('%d loose cup(s) no pile takes, and no indoor finished goods pile with room (the '
                             .. 'depot\'s left to the caravans) to take them'):format(#refused)}
        end
    end
    if best then
        out.pile_id = best.b.id
        if dry_run then
            out.piles_set = best.takes_goblets and 0 or 1
        else
            local fg = best.b.settings.finished_goods
            pcall(function()
                if not fg.type[df.item_type.GOBLET] then fg.type[df.item_type.GOBLET] = true; out.piles_set = 1 end
            end)
            local seen = {}
            for _, r in ipairs(refused) do
                local key = r.mat.kind .. tostring(r.mat.index or '')
                if not seen[key] then
                    seen[key] = true
                    pcall(function()
                        if r.mat.kind == 'inorganic' then
                            if not fg.mats[r.mat.index] then
                                fg.mats[r.mat.index] = true; out.materials_set = out.materials_set + 1
                            end
                        elseif CUP_OTHER_MATS[r.mat.kind] and not fg.other_mats[CUP_OTHER_MATS[r.mat.kind]] then
                            fg.other_mats[CUP_OTHER_MATS[r.mat.kind]] = true; out.materials_set = out.materials_set + 1
                        end
                    end)
                end
                pcall(function()
                    local q = r.it:getQuality()
                    if not fg.quality_core[q] then fg.quality_core[q] = true; out.materials_set = out.materials_set + 1 end
                end)
                pcall(function()
                    local q = r.it:getOverallQuality()
                    if not fg.quality_total[q] then fg.quality_total[q] = true; out.materials_set = out.materials_set + 1 end
                end)
            end
        end
    end
    if dry_run then
        out.unforbidden = #forbidden
    else
        for _, it in ipairs(forbidden) do
            pcall(function() it.flags.forbid = false; out.unforbidden = out.unforbidden + 1 end)
        end
    end
    return out
end

local function bump(t, k) k = tostring(k or '?'); t[k] = (t[k] or 0) + 1 end

function free_items_count(kind, detail)
    local ok, list = pcall(function() return df.global.world.items.other[kind] end)
    if not ok or not list then return nil end
    local n = 0
    local d = detail and {kinds = {}, races = {}, stored = {}, wear = {}, place = {}} or nil
    -- (0.104.168) for cups: why each free one off the piles isn't hauled, and every cup's flags
    local cup_ctx
    if d and kind == 'GOBLET' then
        cup_ctx = {piles = cup_piles(), groups = cup_citizen_groups()}
        d.why, d.why_locations, d.flags, d.mats, d.why_at = {}, {}, {}, {}, {}
        d.piles = {finished_goods = #cup_ctx.piles, take_goblets = 0}
        for _, p in ipairs(cup_ctx.piles) do
            if p.takes_goblets then d.piles.take_goblets = d.piles.take_goblets + 1 end
        end
    end
    for _, it in ipairs(list) do
        if cup_ctx then
            pcall(function()
                if it.flags.removed or it.flags.garbage_collect then return end
                for _, fl in ipairs(CUP_FLAGS) do
                    local okv, v = pcall(function() return it.flags[fl] end)
                    if okv and v then bump(d.flags, fl) end
                end
                -- forbidden, loose in a hall (a zone, not a location's): accept_cups frees these
                if it.flags.forbid and it.flags.on_ground and not it.flags.in_inventory then
                    local x, y, z = dfhack.items.getPosition(it)
                    local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
                    if cup_in_indoor_hall(pos) and dfhack.maps.getWalkableGroup(pos) ~= 0 then
                        d.forbidden_in_halls = (d.forbidden_in_halls or 0) + 1
                    end
                end
            end)
        end
        local okf, free = pcall(function()
            local f = it.flags
            return not (f.removed or f.garbage_collect or f.artifact or f.owned or f.in_inventory or f.forbid
                        or f.in_job or f.trader or f.in_building or f.dump or f.hostile or f.construction)
        end)
        -- (0.104.157) a product still in its workshop (Teacheroar: 34 cups in the
        -- craftsdwarf's, the finished goods piles full) or one on a tile no
        -- dwarf can walk to (91 of 118 shoes) is no use to anyone yet
        local where = 'free'
        if okf and free then
            pcall(function()
                local hb = dfhack.items.getHolderBuilding(it)
                if hb and hb:getType() == df.building_type.Workshop then where = 'workshop' return end
                local x, y, z = dfhack.items.getPosition(it)
                local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
                if pos and dfhack.maps.getWalkableGroup(pos) == 0 then where = 'unwalkable' end
            end)
            if where ~= 'free' then
                if d then bump(d.place, where) end
                free = false
            end
        end
        if okf and free then
            n = n + 1
            if d then
                pcall(function() bump(d.kinds, it.subtype and it.subtype.id or 'none') end)
                pcall(function()
                    local cr = df.creature_raw.find(it.maker_race)
                    bump(d.races, cr and cr.creature_id or 'unknown')
                end)
                pcall(function() bump(d.stored, dfhack.items.getContainer(it) and 'container' or 'loose') end)
                pcall(function() bump(d.wear, it.wear) end)
                -- where: on a stockpile, on a tile no dwarf can walk to, or elsewhere
                pcall(function()
                    local x, y, z = dfhack.items.getPosition(it)
                    local pos = type(x) == 'number' and xyz2pos(x, y, z) or x
                    local okb, b = pcall(dfhack.buildings.findAtTile, pos)
                    -- in a zone: the garbage dump (the old `tidy` sent owned things
                    -- there), a tavern, a dining hall... by DF's zone type
                    local zt
                    pcall(function()
                        for _, zn in ipairs(dfhack.buildings.findCivzonesAt(pos) or {}) do
                            zt = zt or df.civzone_type[zn.type]
                        end
                    end)
                    if okb and b and b:getType() == df.building_type.Stockpile then bump(d.place, 'stockpile')
                    elseif zt then bump(d.place, 'zone ' .. tostring(zt))
                    else bump(d.place, 'elsewhere') end
                    -- (0.104.168) a cup off the piles: why DF leaves it there
                    if cup_ctx and not (okb and b and b:getType() == df.building_type.Stockpile) then
                        bump(d.mats, cup_material(it).kind)
                        local okw, why, loc = pcall(cup_why, it, pos, cup_ctx)
                        why = okw and why or 'unknown'
                        -- (0.104.168, review) in a bin or barrel: hauled with it, never by accept_cups
                        if dfhack.items.getContainer(it) then why, loc = 'in_container', nil end
                        bump(d.why, why)
                        if loc then bump(d.why_locations, loc) end
                        if #d.why_at < 4 then
                            table.insert(d.why_at, ('%s at x%d y%d z%d'):format(why, pos.x, pos.y, pos.z))
                        end
                    end
                    if not (okb and b and b:getType() == df.building_type.Stockpile) then
                        d.elsewhere_at = d.elsewhere_at or {}
                        if #d.elsewhere_at < 4 then
                            table.insert(d.elsewhere_at, ('x%d y%d z%d'):format(pos.x, pos.y, pos.z))
                        end
                    end
                end)
            end
        end
    end
    if d then d.n = n; return d end
    return n
end

local WORN_MODE
local function worn_mode()
    if WORN_MODE == nil then
        local ok, v = pcall(function() return df.unit_inventory_item.T_mode.Worn end)
        if not ok or v == nil then ok, v = pcall(function() return df.inv_item_role_type.Worn end) end
        WORN_MODE = (ok and v ~= nil) and v or 2
    end
    return WORN_MODE
end

local WEAR_NAMES = {[0] = 'new', [1] = 'worn', [2] = 'threadbare', [3] = 'tattered'}

function clothing_census(units)
    local out = {citizens = 0, worn = {new = 0, worn = 0, threadbare = 0, tattered = 0},
                 without = {shoes = 0, legs = 0, body = 0}, tattered_wearers = 0}
    local mode = worn_mode()
    for _, u in ipairs(units or report_citizens()) do
        local okb, baby = pcall(dfhack.units.isBaby, u)
        if not (okb and baby) then
            out.citizens = out.citizens + 1
            local has, tattered = {}, false
            pcall(function()
                for _, inv in ipairs(u.inventory) do
                    if inv.mode == mode and inv.item then
                        local it = inv.item
                        local okt, tn = pcall(function() return df.item_type[it:getType()] end)
                        if okt and tn then has[tn] = true end
                        local okw, w = pcall(function() return it.wear end)
                        w = (okw and type(w) == 'number') and math.max(0, math.min(3, w)) or 0
                        local k = WEAR_NAMES[w]
                        out.worn[k] = out.worn[k] + 1
                        if w >= 3 then tattered = true end
                    end
                end
            end)
            if not has.SHOES then out.without.shoes = out.without.shoes + 1 end
            if not has.PANTS then out.without.legs = out.without.legs + 1 end
            if not has.ARMOR then out.without.body = out.without.body + 1 end
            if tattered then out.tattered_wearers = out.tattered_wearers + 1 end
        end
    end
    -- in store, free for a dwarf to take: footwear (DFHack's tailor only
    -- replaces worn-out clothes, so the barefoot never get any: Teacheroar,
    -- 1 Nov, 63 of 150 barefoot, "NoShoes" the worst stress) and cups (149 of
    -- 150 drank without one; the taverns keep theirs in their own chests)
    out.free_shoes, out.free_cups = free_items_count('SHOES'), free_items_count('GOBLET')
    out.free_shoes_detail = free_items_count('SHOES', true)
    out.free_cups_detail = free_items_count('GOBLET', true)
    return out
end

function free_bones(limit)
    local n = 0
    local ok, list = pcall(function() return df.global.world.items.other.CORPSEPIECE end)
    if not ok or not list then return 0 end
    for _, item in ipairs(list) do
        if limit and n >= limit then break end
        local f = item.flags
        local okb, bone = pcall(function() return item.corpse_flags.bone and not item.corpse_flags.unbutchered end)
        if okb and bone and not (f.forbid or f.in_job or f.removed or f.garbage_collect or f.dump
                or f.in_inventory or f.rotten) then
            n = n + 1
        end
    end
    return n
end

local function acquire_need(u)
    local ok, needs = pcall(function() return u.status.current_soul.personality.needs end)
    if not ok or not needs then return nil end
    for _, nd in ipairs(needs) do
        if df.need_type[nd.id] == 'AcquireObject' then return nd end
    end
end

-- Does `u` like what `item` is made of, or its kind (their preferences)?
local function pref_name(p)
    -- (13c) the global enum: unit_preference.type is a unitpref_type (there is
    -- no T_type), so this was always nil and no trinket matched a dwarf's likes
    local ok, n = pcall(function() return df.unitpref_type[p.type] end)
    return ok and n or nil
end

function likes(u, item)
    local ok, prefs = pcall(function() return u.status.current_soul.preferences end)
    if not ok or not prefs then return false end
    local okm, mt, mi = pcall(function() return item:getMaterial(), item:getMaterialIndex() end)
    local okt, it, st = pcall(function() return item:getType(), item:getSubtype() end)
    for _, p in ipairs(prefs) do
        local n = pref_name(p)
        if n == 'LikeMaterial' and okm and p.mattype == mt and p.matindex == mi then return true end
        if n == 'LikeItem' and okt and p.item_type == it and (p.item_subtype == -1 or p.item_subtype == st) then
            return true
        end
    end
    return false
end

-- Up to `max` dwarves who badly want something get a trinket each (most
-- distracted first; to each the most valuable one they like, else the most
-- valuable left).
function give_trinkets(max, dry_run)
    local wanting = {}
    -- (residents too: the fort's poets and bards count in the needs report,
    -- and getCitizens(true) left them out: "nobody wants" while 16 did)
    for _, u in ipairs(report_citizens()) do
        local nd = acquire_need(u)
        if nd and nd.focus_level <= ACQUIRE_DISTRACTED and dfhack.units.isAdult(u) and u.mood == -1 then
            table.insert(wanting, {u = u, nd = nd})
        end
    end
    table.sort(wanting, function(a, b) return a.nd.focus_level < b.nd.focus_level end)
    if #wanting == 0 then return {ok = false, rejected = true, error = 'nobody wants something to own'} end
    local items = free_trinkets(200)
    table.sort(items, function(a, b) return dfhack.items.getValue(a) > dfhack.items.getValue(b) end)
    if #items == 0 then
        return {ok = false, rejected = true, wanting = #wanting,
                error = 'no free rings, amulets, figurines or other trinkets to give'}
    end
    local n = math.min(max or 10, #wanting, #items)
    if dry_run then return {ok = true, dry_run = true, would_give = n, wanting = #wanting, trinkets = #items} end
    local given, liked = 0, 0
    for i = 1, n do
        local w, pick = wanting[i], 1
        for j, item in ipairs(items) do
            if likes(w.u, item) then pick = j break end
        end
        local item = table.remove(items, pick)
        local okg, r = pcall(dfhack.items.setOwner, item, w.u)
        if okg and r ~= false then
            w.nd.focus_level = math.max(w.nd.focus_level, SATISFIED_FOCUS)
            given = given + 1
            if pick > 1 or likes(w.u, item) then liked = liked + 1 end
        end
    end
    return {ok = given > 0, given = given, liked = liked, wanting = #wanting, trinkets_left = #items,
            error = given == 0 and 'the game took no trinket' or nil}
end


-- --- staffing locations (0.84) ---------------------------------------------------
--
