-- ai-bridge-report: the fort report's readers (dwarves, needs, stocks,
-- supplies, the dead, moods, society, health, justice, hazards, the deep,
-- others on the map...) and the event feed.
--
-- A part of ai-bridge.lua (13c, when the 409 KB file was split), loaded by it
-- into its own environment: what is global here is the bridge's (reachable as
-- reqscript('ai-bridge').<name>), and the bridge's shared helpers (txt,
-- reject, int_in, whole_number, sorted_keys, abs_tick, translate_name,
-- in_fort, NOT_IN_FORT, OUT_DIR) are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-report is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report'] = '0.105.40'   -- (0.105.26) bumped with BRIDGE_VERSION

local utils = require('utils')

local TICKS_PER_DAY = 1200
local TICKS_PER_MONTH = 33600 -- 28 days
local MONTHS = {
    'Granite', 'Slate', 'Felsite', 'Hematite', 'Malachite', 'Galena',
    'Limestone', 'Sandstone', 'Timber', 'Moonstone', 'Opal', 'Obsidian',
}
local SEASONS = {'spring', 'summer', 'autumn', 'winter'}
-- dfhack.units.getStressCategory: 0 = most stressed ... 6 = least
local STRESS_LABELS = {
    [0] = 'miserable', [1] = 'very_unhappy', [2] = 'unhappy', [3] = 'fine',
    [4] = 'content', [5] = 'happy', [6] = 'ecstatic',
}

-- Item stock categories reported to the AI: label -> DF item list.
STOCK_CATEGORIES = {
    {'drink', 'DRINK'},
    {'prepared_meals', 'FOOD'},
    {'meat', 'MEAT'},
    {'fish', 'FISH'},
    {'plants', 'PLANT'},
    {'plant_growths', 'PLANT_GROWTH'},   -- fruit, leaves, nuts: much of what gathering brings in
    {'cheese', 'CHEESE'},
    {'eggs', 'EGG'},
    {'raw_fish', 'FISH_RAW'},            -- caught, not yet cleaned at a fishery
    {'seeds', 'SEEDS'},
    {'wood', 'WOOD'},
    {'boulders', 'BOULDER'},
    {'blocks', 'BLOCKS'},
    {'metal_bars', 'BAR'},
    {'cloth', 'CLOTH'},
    {'thread', 'THREAD'},
    {'leather', 'SKIN_TANNED'},
    {'rough_gems', 'ROUGH'},
    {'cut_gems', 'SMALLGEM'},          -- (cut gems are SMALLGEM; GEM is a large gem)
    {'weapons', 'WEAPON'},
    {'armor', 'ARMOR'},
    {'ammo', 'AMMO'},
    {'barrels', 'BARREL'},
    {'mechanisms', 'TRAPPARTS'},
    {'chains', 'CHAIN'},                 -- ropes and chains (a well needs one)
    {'bins', 'BIN'},
}

local function inc(t, key, n)
    t[key] = (t[key] or 0) + (n or 1)
end

---------------------------------------------------------------------------
-- Sections of the report
---------------------------------------------------------------------------

function get_date()
    local tick = df.global.cur_year_tick
    local month = tick // TICKS_PER_MONTH -- 0..11
    return {
        year = df.global.cur_year,
        tick = tick,
        month = MONTHS[month + 1],
        day = (tick % TICKS_PER_MONTH) // TICKS_PER_DAY + 1,
        season = SEASONS[month // 3 + 1],
    }
end

local function top_skills(unit, n)
    local soul = unit.status.current_soul
    if not soul then return {} end
    local skills = {}
    for _, s in ipairs(soul.skills) do
        if s.rating > 0 then
            local attrs = df.job_skill.attrs[s.id]
            table.insert(skills, {
                skill = (attrs and attrs.caption) or df.job_skill[s.id] or tostring(s.id),
                level = s.rating,
            })
        end
    end
    table.sort(skills, function(a, b) return a.level > b.level end)
    local out = {}
    for i = 1, math.min(n, #skills) do out[i] = skills[i] end
    return out
end

function get_dwarves(include_units)
    local summary = {
        total = 0, adults = 0, children = 0, legendary = 0,
        idle_adults = 0, in_squads = 0, needs_medical_care = 0,
        -- (0.105.33) idle_adults split: in a social activity (praying, the
        -- tavern, a performance, reading: DF's u.social_activities, not a
        -- job) and truly free (no job, no activity). in_activity + idle_free
        -- == idle_adults; soldiers are in neither (they are never idle here)
        in_activity = 0, idle_free = 0,
        stress = {},
        professions = {},
    }
    for _, label in pairs(STRESS_LABELS) do summary.stress[label] = 0 end

    local units = {}
    for _, u in ipairs(report_citizens()) do
        local is_child = dfhack.units.isChild(u) or dfhack.units.isBaby(u)
        local job = u.job.current_job
        local in_squad = u.military.squad_id >= 0
        -- DF's own hospital flag. (u.body.wounds also holds old scars, so
        -- counting wounds overstates injuries badly.)
        local needs_care = u.health ~= nil and u.health.flags.needs_healthcare
        local stress = STRESS_LABELS[dfhack.units.getStressCategory(u)] or 'unknown'
        local profession = txt(dfhack.units.getProfessionName(u))

        summary.total = summary.total + 1
        if is_child then
            summary.children = summary.children + 1
        else
            summary.adults = summary.adults + 1
            if not job and not in_squad then
                summary.idle_adults = summary.idle_adults + 1
                local oka, busy = pcall(function() return #u.social_activities > 0 end)
                if oka and busy then
                    summary.in_activity = summary.in_activity + 1
                else
                    summary.idle_free = summary.idle_free + 1
                end
            end
        end
        if in_squad then summary.in_squads = summary.in_squads + 1 end
        -- (0.103.6) a dwarf legendary at some skill (rating 15+), for quirks
        pcall(function()
            for _, sk in ipairs(u.status.current_soul.skills) do
                if sk.rating >= 15 then summary.legendary = summary.legendary + 1 break end
            end
        end)
        if needs_care then summary.needs_medical_care = summary.needs_medical_care + 1 end
        inc(summary.stress, stress)
        inc(summary.professions, profession)

        if include_units then
            table.insert(units, {
                id = u.id,
                name = txt(dfhack.units.getReadableName(u, true)),
                profession = profession,
                age = math.floor(dfhack.units.getAge(u) or 0),
                child = is_child,
                job = job and txt(dfhack.job.getName(job)) or nil,
                in_squad = in_squad,
                needs_medical_care = needs_care,
                stress = stress,
                top_skills = top_skills(u, 3),
            })
        end
    end
    return summary, include_units and units or nil
end

-- What the dwarves miss: for each need (df.need_type), how many citizens
-- are distracted by it (focus at or under DISTRACTED, as DFHack's allneeds
-- grades it) and badly (BADLY); prayer by deity; and the most stressed
-- dwarves with their worst unmet needs.
DISTRACTED, BADLY = -1000, -10000

function get_needs(txt_fn)
    local t = txt_fn or txt
    local out = {needs = {}, deities = {}, deity_ids = {}, stressed = {}, worship = {}}
    local deity_names = {}
    -- (0.105.23) a deity's name, looked up once a report
    local function deity_name(id)
        local key = tostring(id)
        if deity_names[key] == nil then
            local okd, nm = pcall(function()
                return t(translate_name(df.historical_figure.find(id).name, true))
            end)
            deity_names[key] = (okd and nm and nm ~= '') and nm or ('deity ' .. key)
        end
        return deity_names[key]
    end
    -- (0.104.168) the keen the fill could draft in a crisis (ai-military's
    -- test, strict): the keen lift is sized on these, not on nobles, nursing
    -- mothers, patients or the breaking-down, whom the fill passes over
    local okd, MIL = pcall(reqscript, 'ai-military')
    local okmo, mothers = false, nil
    if okd then okmo, mothers = pcall(MIL.nursing_mothers) end
    if not okmo then okd = false end
    if okd then out.keen_draftable = 0 end      -- (none read: missing, and the brain uses keen_civilians)
    for _, u in ipairs(report_citizens()) do
        local okn, needs = pcall(function() return u.status.current_soul.personality.needs end)
        if okn and needs then
            local worst = {}
            -- (0.104.64) soldiers counted apart: on constant training they
            -- have little free time for the other needs
            local soldier, leader = false, false
            pcall(function() soldier, leader = u.military.squad_id ~= -1, u.military.squad_position == 0 end)
            local fight_focus, badly_other = nil, {}
            for _, nd in ipairs(needs) do
                local name = df.need_type[nd.id] or tostring(nd.id)
                local r = out.needs[name] or {have = 0, distracted = 0, badly = 0}
                out.needs[name] = r
                r.have = r.have + 1
                if nd.focus_level <= DISTRACTED then
                    r.distracted = r.distracted + 1
                    if nd.focus_level <= BADLY then
                        r.badly = r.badly + 1
                        if soldier then r.badly_soldiers = (r.badly_soldiers or 0) + 1 end
                        if name ~= 'Fight' and name ~= 'MartialTraining' then table.insert(badly_other, name) end
                    end
                    table.insert(worst, {name = name, focus = nd.focus_level})
                    if name == 'PrayOrMeditate' and nd.deity_id >= 0 then
                        local nm = deity_name(nd.deity_id)
                        out.deities[nm] = (out.deities[nm] or 0) + 1
                        out.deity_ids[nm] = nd.deity_id   -- (0.102.1) for a temple to that god
                    end
                end
                -- (0.105.23, 14.1 step 4b) every citizen who prays to a god, met
                -- or not: the Monastery raises a temple to each god most worship
                -- (the distracted alone said nothing once a temple to all gods stood)
                if name == 'PrayOrMeditate' and nd.deity_id >= 0 then
                    local nm = deity_name(nd.deity_id)
                    out.worship[nm] = (out.worship[nm] or 0) + 1
                    out.deity_ids[nm] = nd.deity_id
                end
                -- (0.104.64) the training need's worst level for this dwarf
                if name == 'Fight' or name == 'MartialTraining' then
                    fight_focus = math.min(fight_focus or nd.focus_level, nd.focus_level)
                end
            end
            -- (0.104.64) soldiers whose training is met while two or more other
            -- needs go badly unmet (constant training leaves them no time),
            -- and civilians who badly want to train: the AI swaps them
            if soldier and not leader and #badly_other >= 2 and (fight_focus == nil or fight_focus > DISTRACTED) then
                out.starved_soldiers = out.starved_soldiers or {}
                out.starved_soldiers_total = (out.starved_soldiers_total or 0) + 1   -- (0.104.138, 12j)
                if #out.starved_soldiers < 8 then
                    table.insert(out.starved_soldiers, {id = u.id, name = t(dfhack.units.getReadableName(u)),
                                                        unmet = badly_other})
                end
            elseif not soldier and fight_focus and fight_focus <= BADLY and dfhack.units.isAdult(u) then
                out.keen_civilians = (out.keen_civilians or 0) + 1
                if okd and MIL.draftable(u, mothers, 'keen') then   -- (0.104.168; 0.105.21 the very unhappy keen too)
                    out.keen_draftable = (out.keen_draftable or 0) + 1
                end
            end
            local cat = dfhack.units.getStressCategory(u)
            if cat <= 1 then
                table.sort(worst, function(a, b) return a.focus < b.focus end)
                local w = {}
                for i = 1, math.min(3, #worst) do w[i] = worst[i].name end
                -- (0.102.4) what the AI can do for them: a bedroom of their
                -- own, out of a squad (DF wiki, Keeping your dwarves unstressed)
                local bedroom = false
                pcall(function()
                    for _, b in ipairs(u.owned_buildings) do
                        if df.building_civzonest:is_instance(b) and df.civzone_type[b.type] == 'Bedroom' then bedroom = true end
                    end
                end)
                local squad, leader = u.military.squad_id ~= -1, u.military.squad_position == 0
                -- (0.104.38) one who longs to fight or train (the military
                -- module keeps them in the squad: 412 releases asked and refused)
                local fight = fight_focus ~= nil and fight_focus <= DISTRACTED
                table.insert(out.stressed, {id = u.id, name = t(dfhack.units.getReadableName(u)),
                                            stress = STRESS_LABELS[cat], unmet = w, bedroom = bedroom,
                                            squad = squad or nil, leader = (squad and leader) or nil,
                                            wants_fight = fight or nil})
            end
        end
    end
    table.sort(out.stressed, function(a, b) return a.stress < b.stress end)
    while #out.stressed > 8 do table.remove(out.stressed) end
    -- (D0) each god's spheres (up to 4 words), beside deity_ids: the Design
    -- track's symbols. [verify] DF 53: hf.info.spheres, a list of sphere_type
    -- (or a struct holding it as .spheres)
    out.deity_spheres = {}
    for nm, id in pairs(out.deity_ids) do
        pcall(function()
            local sp = df.historical_figure.find(id).info.spheres
            local okl, inner = pcall(function() return sp.spheres end)
            local list = (okl and inner) or sp
            local words = {}
            for _, s in ipairs(list) do
                if #words < 4 then table.insert(words, (tostring(df.sphere_type[s] or s):lower():gsub('_', ' '))) end
            end
            if #words > 0 then out.deity_spheres[nm] = words end
        end)
    end
    -- (0.104.7, a probe for Be with friends) the game's activities under way by
    -- kind (socialising is an activity, not a job), how many citizens are in
    -- one, the idle ones and where they stand (a meeting hall, dining hall,
    -- tavern or temple zone, or elsewhere), and how many have a friend
    pcall(function()
        local soc = {activities = {}, in_activity = 0, idle = 0, idle_in_zone = 0, idle_elsewhere = 0,
                     citizens = 0}
        for _, act in ipairs(df.global.world.activities.all) do
            local okk, k = pcall(function() return df.activity_entry_type[act.type] end)
            k = okk and k or '?'
            soc.activities[k] = (soc.activities[k] or 0) + 1
        end
        local SOCIAL_ZONES = {MeetingHall = true, DiningHall = true}
        -- (0.104.61) the zones of the fort's locations (tavern, temple,
        -- library...), from each location's own list: a zone's location_id
        -- isn't readable here, so idle dwarves in a tavern counted as elsewhere
        local loc_zone = {}
        pcall(function()
            for _, b in ipairs(dfhack.world.getCurrentSite().buildings) do
                pcall(function()
                    local typ = df.abstract_building_type[b:getType()] or '?'
                    for _, bid in ipairs(b:getContents().building_ids) do loc_zone[bid] = typ end
                end)
            end
        end)
        soc.idle_at, soc.idle_spots = {}, {}
        -- (0.104.28) what the citizens are doing right now, by job (the queued
        -- jobs say little: Enxah, 51 of 60 at a job, 127 queued, 34 badly
        -- wanting friends), soldiers apart
        soc.doing, soc.soldiers = {}, 0
        for _, u in ipairs(report_citizens()) do
            soc.citizens = soc.citizens + 1
            pcall(function()
                if u.military.squad_id ~= -1 then soc.soldiers = soc.soldiers + 1 end
                local j = u.job.current_job
                if j then
                    local k = df.job_type[j.job_type] or '?'
                    soc.doing[k] = (soc.doing[k] or 0) + 1
                end
            end)
            pcall(function() if #u.social_activities > 0 then soc.in_activity = soc.in_activity + 1 end end)
            if not u.job.current_job and #u.social_activities == 0 and dfhack.units.isAdult(u)
                    and u.military.squad_id == -1 then
                soc.idle = soc.idle + 1
                local here, where = false, nil
                pcall(function()
                    for _, z in ipairs(dfhack.buildings.findCivzonesAt(u.pos) or {}) do
                        local zt = df.civzone_type[z.type]
                        if SOCIAL_ZONES[zt] then here, where = true, where or zt end
                        if loc_zone[z.id] then here, where = true, loc_zone[z.id] end
                        where = where or zt
                    end
                end)
                where = where or 'no zone'
                soc.idle_at[where] = (soc.idle_at[where] or 0) + 1
                -- (0.104.61) where the idle outside any zone stand, and can they walk to a tavern
                if where == 'no zone' and #soc.idle_spots < 6 then
                    local spot = ('%d,%d,%d'):format(u.pos.x, u.pos.y, u.pos.z)
                    pcall(function()
                        for zid, typ in pairs(loc_zone) do
                            if typ == 'INN_TAVERN' then
                                local z = df.building.find(zid)
                                if z then
                                    local zp = xyz2pos(z.centerx, z.centery, z.z)
                                    spot = spot .. (' tavern#%d %s'):format(zid,
                                        dfhack.maps.canWalkBetween(u.pos, zp) and 'reach' or 'NO-REACH')
                                end
                            end
                        end
                    end)
                    table.insert(soc.idle_spots, spot)
                end
                if here then soc.idle_in_zone = soc.idle_in_zone + 1 else soc.idle_elsewhere = soc.idle_elsewhere + 1 end
            end
        end
        -- (0.104.63, a probe for Be with friends) how DF keeps who knows whom:
        -- the fields of a citizen's first relationship entry, and each
        -- citizen's entries bucketed by the entry's rank (friends form near 15)
        pcall(function()
            local fr = {fields = {}, entries = {}, none = 0, sampled = 0, by_rank = {}}
            local function dump(o, depth, prefix)
                if depth > 2 then return end
                for k, v in pairs(o) do
                    local tv = type(v)
                    if tv == 'number' or tv == 'boolean' or tv == 'string' then
                        fr.fields[prefix .. tostring(k)] = v
                    elseif tv == 'userdata' then
                        pcall(dump, v, depth + 1, prefix .. tostring(k) .. '.')
                    end
                end
            end
            for _, u in ipairs(report_citizens(true)) do
                local hf = df.historical_figure.find(u.hist_figure_id)
                local okv, list = pcall(function() return hf.info.relationships.hf_visual end)
                if okv and list then
                    fr.sampled = fr.sampled + 1
                    if #list == 0 then fr.none = fr.none + 1 end
                    fr.entries[#fr.entries + 1] = #list
                    if next(fr.fields) == nil and #list > 0 then pcall(dump, list[0], 0, '') end
                    -- love and trust by bucket; citizens with no one of love 50+
                    local close = 0
                    for _, r in ipairs(list) do
                        local okr, love, trust = pcall(function() return r.core.love, r.core.trust end)
                        local function bucket(v)
                            return (not okr or type(v) ~= 'number') and '?' or v >= 100 and '100+' or v >= 50 and '50-99'
                                or v >= 10 and '10-49' or v >= 0 and '0-9' or 'neg'
                        end
                        local bl, bt = 'love ' .. bucket(love), 'trust ' .. bucket(trust)
                        fr.by_rank[bl] = (fr.by_rank[bl] or 0) + 1
                        fr.by_rank[bt] = (fr.by_rank[bt] or 0) + 1
                        if okr and type(love) == 'number' and love >= 50 then close = close + 1 end
                    end
                    fr.close = fr.close or {}
                    local cb = close == 0 and '0' or close <= 2 and '1-2' or close <= 5 and '3-5' or '6+'
                    fr.close[cb] = (fr.close[cb] or 0) + 1
                    -- the badly-wanting-friends citizens among them
                    pcall(function()
                        for _, nd in ipairs(u.status.current_soul.personality.needs) do
                            if df.need_type[nd.id] == 'BeWithFriends' and nd.focus_level <= -1000 then
                                fr.close_badly = fr.close_badly or {}
                                fr.close_badly[cb] = (fr.close_badly[cb] or 0) + 1
                            end
                        end
                    end)
                end
            end
            table.sort(fr.entries)
            soc.relations = fr
        end)
        out.social = soc
    end)
    local okc, ic = pcall(function() return reqscript('ai-society').idle_crafting_status() end)
    out.idle_crafting = okc and ic or nil
    -- free trinkets the AI can give dwarves who want to own things, and the craft shops
    pcall(function() out.trinkets = #reqscript('ai-society').free_trinkets(500) end)
    -- (0.104.141) where the trinkets made went (owned, free, in jobs, at the
    -- depot...) and the bones a craftsdwarf could carve: Teacheroar made ~15
    -- of each 20 ordered and the AI never saw one free
    pcall(function() out.trinket_census = reqscript('ai-society').trinket_census() end)
    pcall(function() out.bones = reqscript('ai-society').free_bones(2000) end)
    -- (0.104.157) what stresses the fort (DF's thoughts) and the citizens' clothes
    pcall(function() out.stress_causes = reqscript('ai-society').stress_census() end)
    pcall(function() out.clothing = reqscript('ai-society').clothing_census() end)
    pcall(function() out.craft_shops = reqscript('ai-society').craft_shops() end)
    -- (0.104.168) the cats (vermin hunters) and how many are safe from the butcher
    pcall(function() out.vermin_hunters = reqscript('ai-society').vermin_hunters() end)
    -- petitions the fort agreed to and hasn't fulfilled (DFHack's list-agreements)
    pcall(function()
        local la = reqscript('list-agreements')
        local temples, guilds = la.get_fort_agreements(true)
        out.petitions = {temples = {}, guildhalls = {}}
        for _, agr in ipairs(temples) do
            local okn, nm = pcall(la.get_deity_name, agr)
            table.insert(out.petitions.temples, t(okn and nm or '?'))
        end
        for _, agr in ipairs(guilds) do
            local okn, nm = pcall(la.get_guildhall_profession, agr)
            table.insert(out.petitions.guildhalls, t(okn and nm or '?'))
        end
    end)
    return out
end

-- Same exclusions as DFHack's own autofish tool, plus items built into
-- buildings or constructions. Note: in_inventory is NOT excluded, because DF
-- sets it for items inside barrels and bins too, not just items held by units.
local function usable(item)
    local f = item.flags
    return not (f.forbid or f.garbage_collect or f.rotten or f.trader
        or f.hostile or f.removed or f.dump or f.on_fire or f.encased
        or f.spider_web or f.owned or f.in_building or f.construction)
end

-- (13c) What one report reads more than once is read once: build_state sets
-- REPORT_MEMO for the length of a report; nil outside one (and set so at
-- each run of the script), so an action or a test reads afresh.
REPORT_MEMO = nil

-- (0.105.40 E3) The per-report shared walks: REPORT_CTX for the length of a
-- report (build_state), nil outside one. The table is ai-util's REPORT_CTX
-- too (report_begin there), so the modules' sections (threats, military,
-- health...) share the same walks as the bridge's own. Without ai-util (a
-- test's stub bridge) each call walks afresh, as before.
REPORT_CTX = nil

function report_ctx_begin()
    REPORT_CTX = {walks = {units = 0, items = 0, citizens = 0}}
    local ok, U = pcall(reqscript, 'ai-util')
    if ok and type(U) == 'table' and type(U.report_begin) == 'function' then
        U.report_begin(REPORT_CTX)
        REPORT_CTX.util = U
    end
    return REPORT_CTX
end

function report_ctx_end()
    local c = REPORT_CTX
    REPORT_CTX = nil
    if c and c.util then pcall(c.util.report_end) end
    return c
end

-- dfhack.units.getCitizens(...), once a report for each set of arguments
function report_citizens(...)
    local c = REPORT_CTX
    if c and c.util then return c.util.citizens(...) end
    return dfhack.units.getCitizens(...)
end

-- world.units.active: walked once a report (the same units, same order)
function report_units()
    local c = REPORT_CTX
    if c and c.util then return c.util.units_active() end
    return df.global.world.units.active
end

-- (13c) The loose boulders, walked once a report (the stocks, stone_types,
-- stone_use and supplies sections each walked them): usable ones' count and
-- the free ones' (no job holds them), the free stone by inorganic index, and
-- the free items by material ('type:index').
function boulder_census()
    local memo = REPORT_MEMO
    if memo and memo.boulders then return memo.boulders end
    local c = {count = 0, free = 0, free_items = 0, stone = {}, by_mat = {}}
    for _, item in ipairs(df.global.world.items.other.BOULDER) do
        if usable(item) then
            local n = item:getStackSize()
            c.count = c.count + n
            if not item.flags.in_job then
                c.free, c.free_items = c.free + n, c.free_items + 1
                if item.mat_type == 0 then c.stone[item.mat_index] = (c.stone[item.mat_index] or 0) + n end
                local key = item:getMaterial() .. ':' .. item:getMaterialIndex()
                c.by_mat[key] = (c.by_mat[key] or 0) + 1
            end
        end
    end
    if memo then memo.boulders = c end
    return c
end

-- (13c) One stock list (a df.items_other_id name) walked once a report:
-- usable items' count, the free ones' count (stack sizes) and free items.
function stock_walk(list_name)
    if list_name == 'BOULDER' then return boulder_census() end
    local memo = REPORT_MEMO
    local w = memo and memo.stock and memo.stock[list_name]
    if w then return w end
    w = {count = 0, free = 0, free_items = 0}
    for _, item in ipairs(df.global.world.items.other[df.items_other_id[list_name]]) do
        if usable(item) then
            local n = item:getStackSize()
            w.count = w.count + n
            if not item.flags.in_job then w.free, w.free_items = w.free + n, w.free_items + 1 end
        end
    end
    if memo then
        memo.stock = memo.stock or {}
        memo.stock[list_name] = w
    end
    return w
end

-- Is stone `idx` "economic" (plotinfo.economic_stone holds 0/1 numbers, and
-- 0 is truthy in Lua, so the value itself must be checked)?  0.105.33: the
-- stone list tested only `economic[idx]` and so was always empty.
local function stone_is_economic(economic, idx)
    return idx < #economic and economic[idx] ~= nil and economic[idx] ~= 0
        and economic[idx] ~= false
end

-- Stone in stock, for the culture's material picker: the commonest stone
-- types among loose boulders, with their colour (0-1 RGB) and base value.
function get_stone_types()
    local counts = boulder_census().stone
    local colors = df.global.world.raws.descriptors.colors
    local economic = df.global.plotinfo.economic_stone
    local out = {}
    for idx, n in pairs(counts) do
        local mi = dfhack.matinfo.decode(0, idx)
        -- ores and other "economic" stone are kept for their real use
        if mi and mi.material and mi.material.flags.IS_STONE
                and not stone_is_economic(economic, idx) then
            local ci = mi.material.state_color.Solid
            local c = (ci >= 0 and ci < #colors) and colors[ci] or nil
            table.insert(out, {
                token = mi:getToken(), name = txt(mi.material.state_name.Solid), count = n,
                value = mi.material.material_value,
                rgb = c and {c.red, c.green, c.blue} or nil,
            })
        end
    end
    table.sort(out, function(a, b) return a.count > b.count end)
    while #out > 12 do table.remove(out) end
    return out
end

-- Coal: made into coke at the smelter (bituminous coal 9 bars, lignite 5),
-- the smelter's fuel; never for furniture.
FUEL_STONES = {COAL_BITUMINOUS = 'coke_bituminous', LIGNITE = 'coke_lignite'}

-- Stone the masons and crafters may use: loose boulders of non-"economic"
-- stone (DF keeps economic stone, ores, flux and the like, from ordinary
-- jobs unless it's allowed in the stone settings), and the economic stone
-- lying about by kind: {usable = n, economic = {TOKEN = {n, ore, flux}}}.
-- region2 ran out of usable stone in y52 and every stone order stood still.
function get_stone_use()
    local economic = df.global.plotinfo.economic_stone
    local counts = boulder_census().stone
    local out = {usable = 0, economic = {}, fuel_free = {}}
    for idx, n in pairs(counts) do
        local inorg = df.global.world.raws.inorganics.all[idx] or df.global.world.raws.inorganics[idx]
        if inorg then
            local econ = stone_is_economic(economic, idx)
            local fuel = FUEL_STONES[inorg.id] or false
            if not econ and fuel then
                out.fuel_free[inorg.id] = n           -- coal the masons may use: should be coke
            elseif not econ then
                out.usable = out.usable + n
            else
                local ore = #inorg.metal_ore.mat_index > 0
                local flux = false
                pcall(function()
                    for _, rc in ipairs(inorg.material.reaction_class) do
                        local v = type(rc) == 'string' and rc or rc.value
                        if v == 'FLUX' then flux = true end
                    end
                end)
                out.economic[inorg.id] = {n = n, ore = ore or nil, flux = flux or nil, fuel = fuel or nil}
            end
        end
    end
    return out
end

-- (0.87) Petitions: the ones waiting for an answer (plotinfo.petitions,
-- unapproved agreements: residency and citizenship by visitors, temples and
-- guildhalls by groups) and DF's own standing orders that answer residency
-- and citizenship petitions by themselves (the standing orders screen;
-- read before they're ever changed: 0 or 1 each).
PETITION_ORDERS = {'performer', 'scholar', 'monster_hunter', 'mercenary', 'sanctuary', 'citizenship'}

function petition_order_name(k)
    return k == 'citizenship' and 'standing_orders_petition_citizenship' or ('standing_orders_petition_resident_' .. k)
end

-- (0.89) What a location petition asks for: a temple (to a deity or a
-- religion's first deity) or a guildhall (for a profession), its tier (1 a
-- temple or guildhall, 2 a temple complex or grand guildhall) and how many
-- days since it was made (an agreed one lapses after a year).
function location_wish(a)
    local d = a.details[0]
    local L = d.data.Location
    local e = {loc = df.abstract_building_type[L.type] or tostring(L.type), tier = L.tier}
    pcall(function()
        local dt = df.religious_practice_type[L.deity_type]
        if dt == 'WORSHIP_HFID' then e.deity_hf = L.deity_data.Deity
        elseif dt == 'RELIGION_ENID' then
            e.religion = L.deity_data.Religion
            local ent = df.historical_entity.find(L.deity_data.Religion)
            if ent and #ent.relations.deities > 0 then e.deity_hf = ent.relations.deities[0] end
        end
        local hf = e.deity_hf and df.historical_figure.find(e.deity_hf)
        if hf then e.deity = txt(translate_name(hf.name, true)) end
    end)
    pcall(function()
        if e.loc == 'GUILDHALL' and L.profession >= 0 then e.profession = df.profession[L.profession] end
    end)
    pcall(function()
        e.days = math.floor(((df.global.cur_year - d.year) * 403200 + df.global.cur_year_tick - d.year_tick) / 1200)
    end)
    return e
end

function get_petitions()
    local out = {pending = {}, orders = {}}
    for _, k in ipairs(PETITION_ORDERS) do
        pcall(function() out.orders[k] = df.global[petition_order_name(k)] end)
    end
    pcall(function()
        for _, id in ipairs(df.global.plotinfo.petitions) do
            local a = df.agreement.find(id)
            local d = a and a.details[0]
            if d then
                local e = {id = id, type = df.agreement_details_type[d.type] or tostring(d.type)}
                -- (0.89.1) every waiting petition's age and applicant: the
                -- player's petitions screen showed 2 where the report had 11
                pcall(function()
                    e.days = math.floor(((df.global.cur_year - d.year) * 403200 + df.global.cur_year_tick - d.year_tick) / 1200)
                end)
                pcall(function()
                    local data = d.data[e.type]
                    local party = data and data.applicant
                    for _, pt in ipairs(a.parties) do
                        if pt.id == party then
                            local hfid = #pt.histfig_ids > 0 and pt.histfig_ids[0] or nil
                            local hf = hfid and df.historical_figure.find(hfid)
                            e.applicant = {hf = hfid, entities = #pt.entity_ids}
                            if hf then
                                local u = df.unit.find(hf.unit_id)
                                e.applicant.unit = u and u.id or nil
                                e.applicant.on_map = u and dfhack.units.isActive(u) or false
                                e.applicant.dead = (u and dfhack.units.isDead(u)) or (hf.died_year ~= -1) or nil
                                if u then
                                    e.name = txt(dfhack.units.getReadableName(u))
                                    pcall(function() e.vampire = dfhack.units.isBloodsucker(u) or nil end)
                                end
                            end
                        end
                    end
                    if data and data.end_year ~= nil then e.end_year = data.end_year end
                end)
                if e.type == 'Location' then
                    local okw, w = pcall(location_wish, a)
                    if okw then for k, v in pairs(w) do e[k] = v end end
                end
                pcall(function()
                    local data = d.data[e.type]
                    if data and data.reason ~= nil then e.reason = df.history_event_reason[data.reason] end
                end)
                table.insert(out.pending, e)
            end
        end
    end)
    if #out.pending == 0 then out.pending = nil end
    -- (0.105.9) DF's residents on the map (unit ids, 200 at most): an agreed
    -- residency petition is seen to work when its applicant shows here
    pcall(function()
        if not dfhack.units.isResident then return end
        local res = {}
        for _, u in ipairs(report_units()) do
            if #res < 200 and dfhack.units.isAlive(u) and dfhack.units.isResident(u)
                    and not dfhack.units.isCitizen(u) then table.insert(res, u.id) end
        end
        out.residents = res
        out.residents_n = #res
    end)
    -- (0.89) location petitions agreed to, not yet fulfilled, under a year old
    pcall(function()
        local site_id = df.global.plotinfo.site_id
        local waiting = {}
        for _, id in ipairs(df.global.plotinfo.petitions) do waiting[id] = true end
        for _, a in ipairs(df.agreement.get_vector()) do
            local d = #a.details > 0 and a.details[0] or nil
            if d and df.agreement_details_type[d.type] == 'Location' and d.data.Location.site == site_id
                    and not waiting[a.id] and not a.flags.petition_not_accepted
                    and not a.flags.convicted_accepted then
                local w = location_wish(a)
                if w.days and w.days < 336 then
                    w.id = a.id
                    out.agreed = out.agreed or {}
                    table.insert(out.agreed, w)
                end
            end
        end
    end)
    return out
end

-- (0.89) The elves' tree quota: DF counts the trees the fort has removed
-- (plotinfo.trees_removed) and the elves mind past the difficulty's cap
-- (plotinfo.main.custom_difficulty.tree_fell_count, a higher one for savage
-- land). elves: an elven civilisation's caravan has come (they set the quota).
function get_diplomacy()
    local out = {}
    pcall(function() out.trees_removed = df.global.plotinfo.trees_removed end)
    pcall(function()
        local d = df.global.plotinfo.main.custom_difficulty
        out.tree_cap, out.tree_cap_savage = d.tree_fell_count, d.tree_fell_count_savage
    end)
    pcall(function()
        for _, c in ipairs(df.global.plotinfo.caravans) do
            local ent = df.historical_entity.find(c.entity)
            local cr = ent and df.creature_raw.find(ent.race)
            if cr and cr.creature_id == 'ELF' then out.elves = true end
        end
    end)
    -- (0.89.1) the fort's civilisation's relations with the other
    -- civilisations (its diplomacy states): elves at peace set a tree quota
    -- whether or not their caravan is on the map now
    pcall(function()
        local civ = df.historical_entity.find(df.global.plotinfo.civ_id)
        out.civs = {}
        for _, st in ipairs(civ.relations.diplomacy.state) do
            local ent = df.historical_entity.find(st.group_id)
            if ent and df.historical_entity_type[ent.type] == 'Civilization' then
                local cr = df.creature_raw.find(ent.race)
                local race = cr and cr.creature_id or '?'
                local rel = df.diplomacy_state_type[st.relation] or tostring(st.relation)
                table.insert(out.civs, {id = ent.id, race = race, relation = rel,
                                        name = txt(translate_name(ent.name, true))})
                if race == 'ELF' and rel ~= 'TotalWar' and rel ~= 'NoContact' then out.elves = true end
            end
        end
        if #out.civs == 0 then out.civs = nil end
    end)
    return out
end

-- (0.91) Meetings (read only, a probe): diplomats and the outpost liaison
-- meet the fort's leader (plotinfo.activities: the actor, the noble met, the
-- zone, its flags), the diplomacy under way (plotinfo.dip_meeting_info: the
-- civ, its topics), who waits to be heard (meeting_requests), and whether
-- DF is showing or about to show the meeting screen (dipscript_popups; the
-- current screen), which the player answers by hand and an unattended run
-- may not.
local function unit_word(id)
    local u = id and id ~= -1 and df.unit.find(id)
    if not u then return nil end
    local ok, n = pcall(function() return txt(dfhack.units.getReadableName(u)) end)
    return ok and n or tostring(id)
end

function get_meetings()
    local out = {}
    pcall(function()
        for _, a in ipairs(df.global.plotinfo.activities) do
            local e = {actor = unit_word(a.unit_actor), noble = unit_word(a.unit_noble), place = a.place,
                       delay = a.delay, room_rank = a.worstroomrank, flags = {}}
            for _, f in ipairs({'next_step', 'checked_building', 'add_delay', 'topic_discussed', 'meeting_done'}) do
                pcall(function() if a.flags[f] then table.insert(e.flags, f) end end)
            end
            if a.tree_quota and a.tree_quota ~= -1 then e.tree_quota = a.tree_quota end
            -- (0.105.24) a visitor (not a citizen) meeting the noble: B and F's
            -- mayors (2-5 Nov) met poets, dancers and bards, who come to ask to
            -- stay, as often as their own citizens ("unable to complain")
            pcall(function()
                local u = df.unit.find(a.unit_actor)
                if u and not dfhack.units.isCitizen(u) then e.visitor = true end
                -- (0.105.26) a resident (lives here, not a citizen) isn't a visitor come to ask
                if e.visitor and dfhack.units.isResident and dfhack.units.isResident(u) then e.resident = true end
                -- (0.105.30 live fixes) a stranger: a visitor, not a resident, not of the
                -- fort's race (E's thief, 8 Nov, a weasel woman, asked for meetings first)
                if e.visitor and not e.resident and u.race ~= df.global.plotinfo.race_id then e.stranger = true end
            end)
            out.activities = out.activities or {}
            table.insert(out.activities, e)
        end
    end)
    pcall(function()
        for _, m in ipairs(df.global.plotinfo.dip_meeting_info) do
            local ent = df.historical_entity.find(m.civ_id)
            local cr = ent and df.creature_raw.find(ent.race)
            local e = {civ = m.civ_id, race = cr and cr.creature_id or nil, step = m.cur_step, topics = {}}
            for _, t in ipairs(m.topic_list) do table.insert(e.topics, df.meeting_topic[t] or tostring(t)) end
            local hf = df.historical_figure.find(m.diplomat_id)
            local u = hf and df.unit.find(hf.unit_id)
            e.diplomat = u and unit_word(u.id) or nil
            out.diplomacy = out.diplomacy or {}
            table.insert(out.diplomacy, e)
        end
    end)
    pcall(function() out.requests = #df.global.plotinfo.meeting_requests end)
    -- (0.105.24) of those waiting, the visitors (an entry that is a unit id or holds one)
    pcall(function()
        local n, res = 0, 0
        for _, r in ipairs(df.global.plotinfo.meeting_requests) do
            local id = type(r) == 'number' and r or nil
            if not id then pcall(function() id = r.unit_id end) end
            local u = id and df.unit.find(id)
            if u and not dfhack.units.isCitizen(u) then
                n = n + 1
                local resident = dfhack.units.isResident and dfhack.units.isResident(u)
                if resident then res = res + 1 end   -- (0.105.26)
                -- (0.105.30 live fixes) of those, strangers: not residents, not of the fort's race
                if not resident and u.race ~= df.global.plotinfo.race_id then
                    out.strangers = out.strangers or {}
                    if #out.strangers < 5 then table.insert(out.strangers, unit_word(u.id)) end
                    out.requests_strangers = (out.requests_strangers or 0) + 1
                end
            end
        end
        out.requests_visitors = n
        out.requests_residents = res     -- (0.105.26) of those, residents (not visitors come to ask)
        out.requests_strangers = out.requests_strangers or 0
    end)
    pcall(function() out.popups = #df.global.plotinfo.dipscript_popups end)
    pcall(function() out.screen = dfhack.gui.getCurFocus(true)[1] end)
    return out
end

-- (0.89) Answer a location petition (a temple or guildhall) as the
-- petitions screen does: agreeing clears the agreement's "not approved" flag
-- (DFHack's list-agreements: "this gets unset by accepting a petition") and
-- takes it off the waiting list; declining only takes it off the list.
function answer_petition(id, accept, dry_run)
    local list = df.global.plotinfo.petitions
    local idx
    for i, v in ipairs(list) do if v == id then idx = i end end
    if idx == nil then return {ok = false, rejected = true, error = 'no petition ' .. tostring(id) .. ' is waiting'} end
    local a = df.agreement.find(id)
    local d = a and a.details[0]
    local kind = d and df.agreement_details_type[d.type]
    -- (0.105.9) residency too (every fort held 300+ waiting); citizenship stays yours
    if not d or (kind ~= 'Location' and kind ~= 'Residency') then
        return {ok = false, rejected = true, error = 'only temple, guildhall and residency petitions are answered by the AI'}
    end
    local wish = kind == 'Location' and location_wish(a) or nil
    local out = {ok = true, id = id, accepted = accept or nil, declined = (not accept) or nil, wish = wish,
                 kind = kind, dry_run = dry_run or nil}
    if kind == 'Residency' then
        pcall(function()
            local party = d.data.Residency.applicant
            for _, pt in ipairs(a.parties) do
                if pt.id == party and #pt.histfig_ids > 0 then
                    local hf = df.historical_figure.find(pt.histfig_ids[0])
                    out.unit = hf and hf.unit_id >= 0 and hf.unit_id or nil
                end
            end
        end)
    end
    if dry_run then return out end
    if accept then a.flags.petition_not_accepted = false end
    list:erase(idx)
    local still = false
    for _, v in ipairs(list) do if v == id then still = true end end
    out.ok = not still and (not accept or a.flags.petition_not_accepted == false)
    return out
end

-- The fort's locations (temples, taverns, libraries...), by type.
LOCATION_SUPPLIES = {'goblets', 'instruments', 'paper', 'splints', 'thread', 'cloth', 'crutches', 'powder',
                     'buckets', 'soap'}

function get_locations()
    local site = dfhack.world.getCurrentSite()
    -- count = {...}: never an empty table, which would reach Python as a list
    local out = {count = {}, total = 0}
    if not site then return out end
    for _, b in ipairs(site.buildings) do
        local gone = false
        pcall(function() gone = b.flags.DOES_NOT_EXIST end)
        if not gone then
            local t = df.abstract_building_type[b:getType()] or tostring(b:getType())
            out.count[t] = (out.count[t] or 0) + 1
            out.total = out.total + 1
            -- (0.83) what each location keeps and holds, and who works there:
            -- DF's location screen (desired goblets, instruments, paper,
            -- thread...; the counts the game last took; the occupations)
            pcall(function()
                local c = b:getContents()
                if not c then return end
                local e = {id = b.id, type = t, tier = c.location_tier, value = c.location_value,
                           want = {}, have = {}, jobs = {}}
                for _, k in ipairs(LOCATION_SUPPLIES) do
                    pcall(function()
                        e.want[k] = c['desired_' .. k]
                        e.have[k] = c['count_' .. k]
                    end)
                end
                pcall(function() e.want.copies = c.desired_copies end)
                pcall(function()
                    for _, k in ipairs(LOCATION_SUPPLIES) do
                        if c.need_more[k] then e.short = e.short or {}; table.insert(e.short, k) end
                    end
                end)
                pcall(function() e.books = #b.copied_artifacts end)
                -- (0.105.12, 14.1 step 4) who may come in (DF's location screen:
                -- visitors, residents, members only): the flags set, by name
                pcall(function()
                    local on = {}
                    for k, v in pairs(b.flags) do
                        if v == true then table.insert(on, tostring(k)) end
                    end
                    e.flags = on
                end)
                -- (0.104.146) a temple's dedication: to one deity (its worshippers
                -- pray there), a religion (its deities), or all ('any')
                if t == 'TEMPLE' then
                    pcall(function()
                        local dt = df.religious_practice_type[b.deity_type]
                        if dt == 'WORSHIP_HFID' then
                            e.deity_hf = b.deity_data.Deity
                        elseif dt == 'RELIGION_ENID' then
                            e.religion = b.deity_data.Religion      -- (0.89)
                            local ent = df.historical_entity.find(b.deity_data.Religion)
                            e.religion_deities = {}
                            for _, hfid in ipairs(ent and ent.relations.deities or {}) do
                                table.insert(e.religion_deities, hfid)
                            end
                        else
                            e.any_deity = true
                        end
                    end)
                    if e.deity_hf == nil and e.religion_deities == nil then e.any_deity = true end
                end
                -- (0.90) its zones (furniture goes into the first)
                pcall(function()
                    for _, bid in ipairs(c.building_ids) do
                        e.zones = e.zones or {}
                        table.insert(e.zones, bid)
                    end
                end)
                -- (0.104.4) chests standing in its zones: a tavern keeps its goblets
                -- (and a temple its instruments) in a chest of its own
                pcall(function()
                    local n = 0
                    for _, bid in ipairs(c.building_ids) do
                        local z = df.building.find(bid)
                        for _, ib in ipairs(z and z.contained_buildings or {}) do
                            if df.building_type[ib:getType()] == 'Box' then n = n + 1 end
                        end
                    end
                    e.chests = n
                end)
                -- (0.103.13) a location laid over a dining hall (the AI's stop-gap
                -- temple or tavern, or one the player made so): its zones all
                -- share their centre with a dining hall zone
                pcall(function()
                    local all = #c.building_ids > 0
                    for _, bid in ipairs(c.building_ids) do
                        local z, here = df.building.find(bid), false
                        if z then
                            local okz, zs = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(z.centerx, z.centery, z.z))
                            for _, o in ipairs(okz and zs or {}) do
                                if o.id ~= z.id and df.civzone_type[o.type] == 'DiningHall' then here = true end
                            end
                        end
                        if not here then all = false end
                    end
                    if all then e.over_dining = true end
                end)
                -- (0.89) what a guildhall's for (a temple's dedication: above)
                if t == 'GUILDHALL' then pcall(function() e.profession = df.profession[c.profession] end) end
                pcall(function()
                    for _, o in ipairs(b.occupations) do
                        local k = df.occupation_type[o.type] or tostring(o.type)
                        local j = e.jobs[k] or {posts = 0, filled = 0}
                        j.posts = j.posts + 1
                        if o.histfig_id ~= -1 then j.filled = j.filled + 1 end
                        e.jobs[k] = j
                    end
                end)
                if next(e.jobs) == nil then e.jobs = nil end
                out.list = out.list or {}
                table.insert(out.list, e)
            end)
        end
    end
    out.built = abs_tick()     -- (0.105.26) when this copy was built (the section is cached): the planner
                               -- tells a stale "open" from the player opening a place the AI shut
    return out
end

FREE_STOCKS = {mechanisms = true, blocks = true, chains = true, bins = true, barrels = true}

-- (0.100, review) Counting in the background between reports was tried
-- and dropped: run all the time it cost more frame time over a session than
-- the 27 ms a report it saved, and counts a few seconds old made the
-- "have + queued" rules order twice. One count a report, as before.
function get_stocks()
    local stocks = {}
    for _, cat in ipairs(STOCK_CATEGORIES) do
        local label = cat[1]
        local w = stock_walk(cat[2])
        local free = w.free
        stocks[label] = w.count
        -- (0.104.155) those no job has claimed: Teacheroar's 3 mechanisms "in
        -- store" were all taken, so no rule ordered more while 6 buildings waited
        if FREE_STOCKS[label] then stocks[label .. '_free'] = free end
        -- (0.104.156) mechanisms by the link's own test (none on a tile no dwarf
        -- can walk to, forbidden or owned): 3 counted free, 1 usable, no order
        if label == 'mechanisms' then
            local okc, c = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
            if okc and type(c) == 'table' and type(c.usable) == 'number' then
                stocks.mechanisms_free = math.min(free, c.usable)
                if c.unwalkable_at then stocks.mechanisms_unwalkable_at = c.unwalkable_at end
            end
        end
    end
    return stocks
end

-- (13c) Where the first citizen with a place on the map stands: what the
-- report and the actions judge "can the dwarves walk there" from (the dead,
-- tombs, workshops, slabs). nil when nobody has one. (Was written out four
-- times.)
function citizen_anchor()
    local from
    pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then from = xyz2pos(x, y, z) break end
        end
    end)
    return from
end

local function is_empty(item)
    local ok, inside = pcall(dfhack.items.getContainedItems, item)
    return ok and #inside == 0
end

-- A workshop's name in the report: DF's workshop type, and for the custom
-- ones (the soap maker's, the screw press) the AI's name or the raws' code.
CUSTOM_SHOP_NAMES = {SOAP_MAKER = 'SoapMaker', SOAP_MAKERS = 'SoapMaker', SCREW_PRESS = 'ScrewPress'}
function workshop_name(b)
    local name = df.workshop_type[b.type] or tostring(b.type)
    if name == 'Custom' then
        local ok, code = pcall(function() return df.building_def.find(b.custom_type).code end)
        if ok and code then name = CUSTOM_SHOP_NAMES[code] or ('Custom:' .. code) end
    end
    return name
end

-- (0.99.5) Can a still brew this item? Its material names a drink among its
-- reaction products (the raws' MATERIAL_REACTION_PRODUCT:DRINK_MAT).
function brewable(item)
    local ok, yes = pcall(function()
        local mi = dfhack.matinfo.decode(item)
        if not mi or not mi.material then return false end
        for _, id in ipairs(mi.material.reaction_product.id) do
            local v = type(id) == 'string' and id or id.value
            if v == 'DRINK_MAT' then return true end
        end
        return false
    end)
    return ok and yes or false
end

local function mat_flags(item)
    local mi = dfhack.matinfo.decode(item)
    return mi and mi.material and mi.material.flags, mi
end

GOOD_MEAL_VALUE = 20

-- Supplies that stall a fort without anyone noticing: empty containers
-- (brewing and cooking stop without them) and what a hospital and wells use.
-- Items already in a job don't count as free.
-- (0.105.33) A test: is this item kept in a chest (or other container
-- building) inside a hospital's zone? The hospital zones are found once, each
-- container's answer kept for the call.
function hospital_store_test()
    local zones = {}
    pcall(function()
        for _, b in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                if df.abstract_building_type[b:getType()] == 'HOSPITAL' then
                    for _, bid in ipairs(b:getContents().building_ids) do zones[bid] = true end
                end
            end)
        end
    end)
    if next(zones) == nil then return function() return false end end
    local seen = {}
    return function(it)
        local ok, r = pcall(function()
            local c = dfhack.items.getContainer(it)
            if not c then return false end
            if seen[c.id] ~= nil then return seen[c.id] end
            local ans = false
            -- (0.105.36, D6) thread in a bag in the chest: the bag has no holder
            -- building, so walk up the containers (a few levels) to the one that has
            local bld, up = nil, c
            for _ = 1, 4 do
                bld = dfhack.items.getHolderBuilding(up)
                if bld then break end
                up = dfhack.items.getContainer(up)
                if not up then break end
            end
            if bld then
                for _, z in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(bld.centerx, bld.centery, bld.z)) or {}) do
                    if zones[z.id] then ans = true break end
                end
            end
            seen[c.id] = ans
            return ans
        end)
        return ok and r == true
    end
end

function get_supplies()
    local out = {empty_barrels = 0, empty_pots = 0, empty_bags = 0, buckets = 0, slabs = 0, fuel = 0, wheelbarrows = 0,
                 splints = 0, crutches = 0, soap = 0, ash = 0, lye = 0, tallow = 0, fat = 0, errors = {}}
    local other = df.global.world.items.other
    local function each(list_name, fn)
        local ok, err = pcall(function()
            for _, it in ipairs(other[df.items_other_id[list_name]]) do
                if usable(it) and not it.flags.in_job then fn(it) end
            end
        end)
        if not ok then out.errors[list_name] = tostring(err):sub(1, 120) end
    end
    each('BARREL', function(it) if is_empty(it) then out.empty_barrels = out.empty_barrels + 1 end end)
    -- (0.99.5) what a still can brew: a plant or growth whose material makes
    -- a drink (DRINK_MAT). region2's 325 "fruit" were leaves and the like:
    -- "Brew drink from fruit: Needs unrotten fermentable leaf or fruit"
    out.brewable_plants, out.brewable_growths = 0, 0
    -- (0.104.11) plants that give thread (Enxah had none: 59 thread orders stood still)
    -- (0.104.138) one pass for both, ai-builder looked up once and each plant
    -- kind's answer kept (the supplies section ran ~255 ms every report)
    out.thread_plants = 0
    -- (0.105.31 reserve fixes) the thread plants a still could brew too: the
    -- mood reserve's processing for thread leaves the drink's plants alone
    out.thread_brewable_plants = 0
    local okB, B = pcall(reqscript, 'ai-builder')
    local thread_of = {}
    each('PLANT', function(it)
        local n = it:getStackSize()
        local brews = brewable(it)
        if brews then out.brewable_plants = out.brewable_plants + n end
        local okp, yes = pcall(function()
            local okk, key = pcall(function() return it:getActualMaterialIndex() end)
            if okk and key ~= nil and thread_of[key] ~= nil then return thread_of[key] end
            local mi = dfhack.matinfo.decode(it)
            local yes_ = (okB and mi and mi.plant and B.plant_thread(mi.plant)) and true or false
            if okk and key ~= nil then thread_of[key] = yes_ end
            return yes_
        end)
        if okp and yes then
            out.thread_plants = out.thread_plants + n
            if brews then out.thread_brewable_plants = out.thread_brewable_plants + n end
        end
    end)
    each('PLANT_GROWTH', function(it)
        if brewable(it) then out.brewable_growths = out.brewable_growths + it:getStackSize() end
    end)
    -- (0.105.24) drink by kind (its material): dwarves who drink the same
    -- booze day after day are upset by it (SameBooze: B and E's worst stress)
    out.drink_kinds = 0
    pcall(function()
        local kinds = {}
        each('DRINK', function(it)
            local _, mi = mat_flags(it)
            local tok = mi and mi:getToken()
            if tok then kinds[tok] = (kinds[tok] or 0) + it:getStackSize() end
        end)
        local list = {}
        for tok, n in pairs(kinds) do table.insert(list, {tok, n}) end
        table.sort(list, function(a, b) return a[2] > b[2] end)
        out.drink_kinds = #list
        out.drink_by_kind = {}
        for i = 1, math.min(5, #list) do out.drink_by_kind[list[i][1]] = list[i][2] end
    end)
    -- (0.104.28) the wool route: tame animals that can be shorn (their caste
    -- has a shearable layer: sheep, llamas, alpacas, goats...). Enxah had no
    -- fibre crop and waited for caravans while patients went without sutures.
    out.shearable = 0
    pcall(function()
        for _, u in ipairs(report_units()) do
            if dfhack.units.isTame(u) and dfhack.units.isAlive(u) and not dfhack.units.isCitizen(u) then
                local okc, n = pcall(function()
                    return #df.creature_raw.find(u.race).caste[u.caste].shearable_tissue_layer
                end)
                if okc and n and n > 0 then out.shearable = out.shearable + 1 end
                -- (0.104.79) and those that can be milked (cows, goats, llamas...)
                local okm, m = pcall(function()
                    local c = df.creature_raw.find(u.race).caste[u.caste]
                    return c.flags.MILKABLE or (c.misc.milkable or 0) > 0
                end)
                if okm and m and dfhack.units.isAdult(u) and dfhack.units.isFemale(u) then
                    out.milkable = (out.milkable or 0) + 1
                end
                -- (0.104.80) and the hens that lay (chickens, ducks, geese...):
                -- they lay only in a nest box they can reach
                local oke, e = pcall(function()
                    return df.creature_raw.find(u.race).caste[u.caste].flags.LAYS_EGGS
                end)
                if oke and e and dfhack.units.isAdult(u) and dfhack.units.isFemale(u) and not u.flags1.caged then
                    out.egg_layers = (out.egg_layers or 0) + 1
                    if dfhack.units.getGeneralRef(u, df.general_ref_type.BUILDING_CIVZONE_ASSIGNED) then
                        out.egg_layers_penned = (out.egg_layers_penned or 0) + 1
                    end
                end
            end
        end
    end)
    -- (0.100) raw food stacks: a cooking job takes 2-4 whole stacks, so the
    -- planner limits meal jobs by stacks, not by items
    out.food_stacks = 0
    for _, kind in ipairs({'MEAT', 'FISH', 'PLANT', 'PLANT_GROWTH', 'CHEESE', 'EGG'}) do
        local okw, w = pcall(stock_walk, kind)      -- (13c) the stocks section's walk
        if okw then out.food_stacks = out.food_stacks + w.free_items
        else out.errors[kind] = tostring(w):sub(1, 120) end
    end
    -- (0.104.80) nest boxes: built ones, and free ones to build
    out.nest_boxes, out.nest_box_items = 0, 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.NestBox then out.nest_boxes = out.nest_boxes + 1 end
        end
    end)
    -- (13c) the tools, once: nest boxes, empty large pots, wheelbarrows and
    -- blank quires (no writing on them)
    out.blank_quires = 0
    each('TOOL', function(it)
        local id = it.subtype and it.subtype.id
        if id == 'ITEM_TOOL_NEST_BOX' then out.nest_box_items = out.nest_box_items + 1
        elseif id == 'ITEM_TOOL_LARGE_POT' then
            if is_empty(it) then out.empty_pots = out.empty_pots + 1 end
        elseif id == 'ITEM_TOOL_WHEELBARROW' then out.wheelbarrows = out.wheelbarrows + 1
        elseif id == 'ITEM_TOOL_QUIRE' then
            local written = false
            pcall(function()
                for _, imp in ipairs(it.improvements) do
                    if imp:getType() == df.improvement_type.WRITING then written = true end
                end
            end)
            if not written then out.blank_quires = out.blank_quires + 1 end
        end
    end)
    -- (0.88.2) bags are their own item type, BAG (live 0.88.1: 92 boxes, all
    -- stone and wood chests; 838 seed stacks in BAG items). The old count
    -- looked for cloth "boxes", so it read 0 empty bags since it was written,
    -- and the kiln never got its order.
    -- (13c) counted in the one walk of the bags below
    -- (0.88) where the bags go: every bag by what it holds, and the seeds
    -- still loose. DF stores seeds in bags whenever it can (DF wiki, Bag),
    -- one bag per kind of seed, so each kind lying loose takes the next new bag.
    local ok_b, err_b = pcall(function()
        local use = {empty = 0, empty_in_job = 0, held = {}, bags = 0, seed_containers = {}}
        for _, it in ipairs(other.BAG) do
            if not it.flags.garbage_collect and not it.flags.removed then
                use.bags = use.bags + 1
                local inside = dfhack.items.getContainedItems(it)
                if #inside == 0 then
                    if it.flags.in_job then use.empty_in_job = use.empty_in_job + 1
                    else
                        use.empty = use.empty + 1
                        if usable(it) then out.empty_bags = out.empty_bags + 1 end
                    end
                else
                    local k = df.item_type[inside[1]:getType()] or '?'
                    use.held[k] = (use.held[k] or 0) + 1
                end
            end
        end
        local loose, bagged = {}, {}
        local n_loose = 0
        for _, it in ipairs(other.SEEDS) do
            if usable(it) and not it.flags.in_job then
                local key = it:getMaterial() .. ':' .. it:getMaterialIndex()
                local c = dfhack.items.getContainer(it)
                if c == nil then
                    loose[key] = true
                    n_loose = n_loose + it:getStackSize()
                else
                    bagged[key] = true
                    local ct = df.item_type[c:getType()] or '?'
                    use.seed_containers[ct] = (use.seed_containers[ct] or 0) + 1
                end
            end
        end
        local function count(t) local n = 0 for _ in pairs(t) do n = n + 1 end return n end
        -- a loose kind that already has a bag somewhere still wants one of its
        -- own only if that bag is full; counted apart so the planner can tell
        local loose_new = 0
        for k in pairs(loose) do if not bagged[k] then loose_new = loose_new + 1 end end
        use.seed_kinds_loose, use.seed_kinds_loose_unbagged = count(loose), loose_new
        use.seed_kinds_bagged, use.seeds_loose = count(bagged), n_loose
        out.bag_use = use
    end)
    if not ok_b then out.errors.bag_use = tostring(err_b):sub(1, 120) end
    -- empty ones only: lye is kept in buckets (the soap chain), and a full one
    -- isn't one the hospital can use (Oct 23: 97 bucket orders while lye sat in them)
    each('BUCKET', function(it) if is_empty(it) then out.buckets = out.buckets + 1 end end)
    -- (0.100) quivers: free ones (soldiers pick a spare up themselves) and worn ones
    out.quivers, out.quivers_worn = 0, 0
    each('QUIVER', function(it)
        if it.flags.in_inventory then out.quivers_worn = out.quivers_worn + 1 else out.quivers = out.quivers + 1 end
    end)
    each('SLAB', function(it) out.slabs = (out.slabs or 0) + 1 end)
    -- (0.103.16) engraved memorial slabs nobody has put up yet
    pcall(function() out.memorial_slabs = #reqscript('ai-builder').memorial_slabs() end)
    -- (0.83) good meals: EatGoodMeal is met by a preferred food or a meal
    -- worth over 20 (DF wiki, Needs): servings of prepared meals and those
    -- worth more than GOOD_MEAL_VALUE each
    out.meal_servings, out.good_meals = 0, 0
    each('FOOD', function(it)
        local n = it:getStackSize()
        out.meal_servings = out.meal_servings + n
        local okv, v = pcall(dfhack.items.getValue, it)
        if okv and v and n > 0 and v / n > GOOD_MEAL_VALUE then out.good_meals = out.good_meals + n end
    end)
    -- (0.103.14) the fort's cooks (a lavish meal's worth grows with the cook's
    -- skill) and the lowest skill its kitchens let cook
    pcall(function()
        -- (0.105.8) best and skilled count only the cooks who can cook now:
        -- adults, sane, in no squad, with the cooking labour. Counting every
        -- citizen kept the six forts' kitchens at 3+ or 6+ for cooks who were
        -- soldiers (A: 27 of 37 in squads), and the lavish meals stuck at the
        -- kitchen for weeks; best_any keeps the old count
        local best, skilled, best_any, able = 0, 0, 0, {}
        for _, u in ipairs(report_citizens(true)) do
            local r = dfhack.units.getNominalSkill(u, df.job_skill.COOK, true) or 0
            if r > best_any then best_any = r end
            local ok_c, can = pcall(function()
                return dfhack.units.isAdult(u) and dfhack.units.isSane(u)
                    and (u.military.squad_id or -1) < 0
                    and u.status.labors[df.unit_labor.COOK] == true
            end)
            if ok_c and can then
                table.insert(able, r)
                if r > best then best = r end
                if r >= 5 then skilled = skilled + 1 end
            end
        end
        table.sort(able, function(x, y) return x > y end)
        local top = {}
        for i = 1, math.min(5, #able) do top[i] = able[i] end
        local kmin = nil
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            if b.type == df.workshop_type.Kitchen then
                local m = b.profile.min_level
                if kmin == nil or m < kmin then kmin = m end
            end
        end
        out.cooks = {best = best, skilled = skilled, kitchen_min = kmin, best_any = best_any,
                     able = #able, able_skills = top}
    end)
    each('SPLINT', function(it) out.splints = out.splints + it:getStackSize() end)
    each('CRUTCH', function(it) out.crutches = out.crutches + it:getStackSize() end)
    each('BAR', function(it)
        local _, mi = mat_flags(it)
        local token = mi and mi:getToken() or ''
        if token:find('SOAP') then out.soap = out.soap + it:getStackSize() end
        if token == 'ASH' then out.ash = out.ash + it:getStackSize() end
        if token:find('^COAL') then out.fuel = (out.fuel or 0) + it:getStackSize() end   -- charcoal, coke
    end)
    -- (0.104.95) glass: bags of sand (sand powder, in a bag), the sand zones,
    -- and the sand in the fort's geology (a sand zone needs some)
    out.sand_bags = 0
    each('POWDER_MISC', function(it)
        local _, mi = mat_flags(it)
        if mi and mi.inorganic and mi.inorganic.flags.SOIL_SAND then out.sand_bags = out.sand_bags + 1 end
    end)
    pcall(function()
        local n = 0
        for _, z in ipairs(df.global.world.buildings.other.ZONE_SAND_COLLECTION or {}) do n = n + 1 end
        out.sand_zones = n
    end)
    if out.sand_zones == nil then
        pcall(function()
            local n = 0
            for _, b in ipairs(df.global.world.buildings.other.ACTIVITY_ZONE) do
                if b.type == df.civzone_type.SandCollection then n = n + 1 end
            end
            out.sand_zones = n
        end)
    end
    pcall(function()
        local names, seen = {}, {}
        local p = reqscript('ai-builder').citizen_positions()[1]
        if not p then return end
        local rx, ry = dfhack.maps.getTileBiomeRgn(p.x, p.y, p.z)
        if type(rx) == 'table' or type(rx) == 'userdata' then rx, ry = rx.x, rx.y end
        local okr, region = pcall(dfhack.maps.getRegionBiome, rx, ry)
        if not okr or not region then region = dfhack.maps.getRegionBiome(xy2pos(rx, ry)) end
        local biome = df.world_geo_biome.find(region.geo_index)
        for _, layer in ipairs(biome.layers) do
            local inorg = df.global.world.raws.inorganics.all[layer.mat_index]
            if inorg and inorg.flags.SOIL_SAND and not seen[inorg.id] then
                seen[inorg.id] = true
                table.insert(names, (inorg.id:lower():gsub('_', ' ')))   -- (gsub's count dropped)
            end
        end
        out.sand_layers = names
    end)
    -- the soap chain: lye (in buckets), tallow and fat (globs)
    local function each_any(list_name, fn)
        local ok, err = pcall(function()
            for _, it in ipairs(other[df.items_other_id[list_name]]) do
                local f = it.flags
                if not (f.forbid or f.garbage_collect or f.rotten or f.trader or f.removed or f.in_job) then fn(it) end
            end
        end)
        if not ok then out.errors[list_name] = tostring(err):sub(1, 120) end
    end
    -- the liquids, once (13c): lye; milk of lime (the kiln and paper chains);
    -- (0.104.79) milk to make cheese of (a liquid of a milk material, not
    -- milk of lime), which only has to be neither forbidden nor rotten
    out.milk, out.milk_of_lime = 0, 0
    local ok_l, err_l = pcall(function()
        for _, it in ipairs(other.LIQUID_MISC) do
            local f = it.flags
            local _, mi = mat_flags(it)
            local tok = mi and mi:getToken() or ''
            if tok:find('MILK') and not tok:find('MILK_OF_LIME') and not f.forbid and not f.rotten then
                out.milk = out.milk + 1
            end
            if not (f.forbid or f.garbage_collect or f.rotten or f.trader or f.removed or f.in_job) then
                if tok == 'LYE' then out.lye = out.lye + 1
                elseif tok:find('MILK_OF_LIME') then out.milk_of_lime = out.milk_of_lime + 1 end
            end
        end
    end)
    if not ok_l then out.errors.LIQUID_MISC = tostring(err_l):sub(1, 120) end
    each_any('GLOB', function(it)
        local _, mi = mat_flags(it)
        local token = mi and mi:getToken() or ''
        if token:find(':TALLOW$') then out.tallow = out.tallow + it:getStackSize()
        elseif token:find(':FAT$') then out.fat = out.fat + it:getStackSize() end
    end)
    -- (0.86) the kiln and paper chains (DF's reaction_other raws): quicklime
    -- and plaster powder (in bags), milk of lime (in buckets), sheets, blank
    -- quires (no writing on them), fresh hides that make parchment, and the
    -- boulders the kiln takes (calcium carbonate, gypsum); cloth by kind
    -- (a plant-cloth bag order can't use silk or yarn cloth)
    out.quicklime, out.plaster, out.sheets, out.hides = 0, 0, 0, 0
    out.calcium_carbonate, out.gypsum = 0, 0
    out.cloth_kinds = {plant = 0, silk = 0, yarn = 0}
    out.anvils = 0
    each('ANVIL', function(it) out.anvils = out.anvils + 1 end)
    -- (0.88) free traction benches (a hospital wants one), tables and ropes for one
    out.traction_benches, out.tables, out.ropes = 0, 0, 0
    each('TRACTION_BENCH', function(it) out.traction_benches = out.traction_benches + 1 end)
    -- (0.90) free statues, to lift a location's value to its tier
    out.statues = 0
    each('STATUE', function(it) out.statues = out.statues + 1 end)
    each('TABLE', function(it) out.tables = out.tables + 1 end)
    each('CHAIN', function(it) out.ropes = out.ropes + 1 end)
    each_any('POWDER_MISC', function(it)
        local _, mi = mat_flags(it)
        local token = mi and mi:getToken() or ''
        if token:find('QUICKLIME') then out.quicklime = out.quicklime + 1
        elseif token:find('PLASTER') then out.plaster = out.plaster + 1 end
    end)
    each('SHEET', function(it) out.sheets = out.sheets + it:getStackSize() end)
    local function has_product(mat, id)
        local found = false
        pcall(function()
            for _, p in ipairs(mat.reaction_product.id) do if p.value == id then found = true end end
        end)
        return found
    end
    each_any('CORPSEPIECE', function(it)
        local _, mi = mat_flags(it)
        if mi and mi.material and has_product(mi.material, 'PARCHMENT_MAT') then out.hides = out.hides + 1 end
    end)
    -- (13c) from the one walk of the boulders a report
    local okb, census = pcall(boulder_census)
    if okb then
        for key, n in pairs(census.by_mat) do
            local c = ''
            local mt, mx = key:match('^(-?%d+):(-?%d+)$')
            local mi = mt and dfhack.matinfo.decode(tonumber(mt), tonumber(mx))
            pcall(function()
                for _, rc in ipairs(mi.material.reaction_class) do
                    if rc.value == 'CALCIUM_CARBONATE' or rc.value == 'GYPSUM' then c = rc.value end
                end
            end)
            if c == 'CALCIUM_CARBONATE' then out.calcium_carbonate = out.calcium_carbonate + n
            elseif c == 'GYPSUM' then out.gypsum = out.gypsum + n end
        end
    else
        out.errors.BOULDER = tostring(census):sub(1, 120)
    end
    -- (0.105.33) the hospital's stock (thread and cloth kept in its chests
    -- for sutures and dressings) is not the fort's: counted apart, so a mood
    -- or a reserve doesn't read it as weaving stock (C's yarn reserve
    -- re-ordered six times from it; F's silk/yarn looked met by it)
    out.hospital = {thread = 0, cloth = 0}
    local in_hospital = hospital_store_test()
    each('CLOTH', function(it)
        if in_hospital(it) then out.hospital.cloth = out.hospital.cloth + it:getStackSize() return end
        local f = mat_flags(it)
        local k = f and (f.SILK and 'silk' or f.YARN and 'yarn' or f.THREAD_PLANT and 'plant') or nil
        if k then out.cloth_kinds[k] = out.cloth_kinds[k] + it:getStackSize() end
    end)
    -- (0.104.140) thread by kind, as cloth: a stuck plant-cloth weave can turn
    -- to silk or yarn thread at hand (webs collected, wool spun)
    out.thread_kinds = {plant = 0, silk = 0, yarn = 0}
    each('THREAD', function(it)
        if in_hospital(it) then out.hospital.thread = out.hospital.thread + it:getStackSize() return end
        local f = mat_flags(it)
        local k = f and (f.SILK and 'silk' or f.YARN and 'yarn' or f.THREAD_PLANT and 'plant') or nil
        if k then out.thread_kinds[k] = out.thread_kinds[k] + it:getStackSize() end
    end)
    if next(out.errors) == nil then out.errors = nil end
    return out
end

-- The dead: ghosts of the fort's own, citizens' bodies not yet in a coffin,
-- and coffins in a tomb zone that are still free for a burial.
local CORPSE_TYPES = {CORPSE = true, CORPSEPIECE = true, REMAINS = true}

local function coffin_is_free(b)
    for _, ci in ipairs(b.contained_items) do
        if ci.use_mode == 0 and CORPSE_TYPES[df.item_type[ci.item:getType()]] then
            return false
        end
    end
    return true
end

local function in_tomb_zone(b)
    local ok, zones = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(b.centerx, b.centery, b.z))
    if not ok or not zones then return false, nil end
    for _, z in ipairs(zones) do
        if z.type == df.civzone_type.Tomb then
            -- a tomb set aside for one dwarf (a noble's) isn't free for others
            local okid, owner = pcall(function() return z.assigned_unit_id end)
            return true, okid and owner or -1, z
        end
    end
    return false, nil
end

-- (0.104.16) a free tomb zone's own state: whether the game would bury a
-- citizen there (zone active, citizens not turned away)
local function tomb_state(z)
    local st = {}
    pcall(function() if z.is_active == 0 or z.is_active == false then st.inactive = true end end)
    pcall(function() if z.zone_settings.tomb.flags.no_citizens then st.no_citizens = true end end)
    pcall(function() if z.zone_settings.tomb.flags.no_pets == false then st.pets = true end end)
    return st
end

-- (0.104.21) The AI's tomb levels' areas (cached for one report).
AI_TOMBS = nil
function in_ai_tombs(x, y, z)
    if not AI_TOMBS then
        AI_TOMBS = {}
        pcall(function()
            for _, p in ipairs(reqscript('ai-builder').load_projects().list) do
                if p.kind == 'tombs' and type(p.area) == 'table' then table.insert(AI_TOMBS, p.area) end
            end
        end)
    end
    for _, a in ipairs(AI_TOMBS) do
        if z == a.z and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 then return true end
    end
    return false
end

-- (0.105.27) the game's standing orders on the dead, refuse and dumping
-- (uint8_t globals, df.global.standing_orders_*): {name = 0/1} for each
-- that exists in this DF, the name without the prefix
STANDING_DEAD_ORDERS = {
    'forbid_used_ammo', 'forbid_own_dead', 'forbid_own_dead_items', 'forbid_other_nohunt',
    'forbid_other_dead_items', 'gather_refuse', 'gather_refuse_outside',
    'dump_corpses', 'dump_skulls', 'dump_bones', 'dump_shells', 'dump_skins', 'dump_hair', 'dump_other',
}

local function standing_kept(name)
    return name:match('^forbid_') or name:match('^gather_refuse') or name:match('^dump_')
end

function standing_orders_dead()
    local out = {}
    local function read(name)
        local ok, v = pcall(function() return df.global['standing_orders_' .. name] end)
        if not ok or v == nil then return end
        if type(v) == 'boolean' then out[name] = v and 1 or 0
        elseif type(v) == 'number' then out[name] = v ~= 0 and 1 or 0 end
    end
    for _, name in ipairs(STANDING_DEAD_ORDERS) do read(name) end
    -- any other of the kind this DF has (the globals listed, where the game lets them be)
    pcall(function()
        for k in pairs(df.global) do
            local name = type(k) == 'string' and k:match('^standing_orders_(.+)$')
            if name and out[name] == nil and standing_kept(name) then read(name) end
        end
    end)
    return out
end

function get_dead()
    AI_TOMBS = nil
    local out = {ghosts = 0, ghost_names = {}, unburied = 0, tomb_coffins = 0, free_tombs = 0,
                 loose_coffins = 0}
    local race, civ = df.global.plotinfo.race_id, df.global.plotinfo.civ_id
    local from0 = citizen_anchor()
    -- (13c) the memorial slabs by whom they remember, read once (each ghost
    -- walked every slab)
    local memorials
    local function memorials_of(hf)
        if not memorials then
            memorials = {}
            for _, it in ipairs(df.global.world.items.other.SLAB) do
                if it.engraving_type == df.slab_engraving_type.Memorial then
                    memorials[it.topic] = memorials[it.topic] or {}
                    table.insert(memorials[it.topic], it)
                end
            end
        end
        return memorials[hf] or {}
    end
    -- and the bodies by whose they are (the last one listed, as before)
    local bodies
    local function body_of(id)
        if not bodies then
            bodies = {}
            for _, c in ipairs(df.global.world.items.other.CORPSE) do bodies[c.unit_id] = c end
        end
        return bodies[id]
    end
    for _, u in ipairs(report_units()) do
        if dfhack.units.isGhost(u) and u.race == race and u.civ_id == civ then
            out.ghosts = out.ghosts + 1
            if #out.ghost_names < 5 then
                table.insert(out.ghost_names, txt(dfhack.units.getReadableName(u)))
            end
            -- (0.104.39) each ghost: its kind (a violent one scares dwarves to
            -- death: 24 of Enxah's 34 deaths in a year were fright) and what
            -- memorial slab there is for it
            pcall(function()
                out.ghost_list = out.ghost_list or {}
                if #out.ghost_list < 20 then
                    local g = {id = u.id, hf = u.hist_figure_id, name = txt(dfhack.units.getReadableName(u))}
                    pcall(function() g.kind = df.ghost_type[u.ghost_info.type] end)
                    pcall(function()
                        for _, it in ipairs(memorials_of(u.hist_figure_id)) do
                            local st = it.flags.in_building and 'built' or it.flags.in_job and 'job'
                                or it.flags.construction and 'built' or 'loose'
                            g.slab = (g.slab == 'built') and 'built' or st
                            -- (0.104.41) where it is and what holds it
                            local x, y, z = dfhack.items.getPosition(it)
                            g.slab_at = {x = x, y = y, z = z, forbid = it.flags.forbid or nil,
                                         dump = it.flags.dump or nil, trader = it.flags.trader or nil,
                                         owned = it.flags.owned or nil}
                            pcall(function()
                                for _, ref in ipairs(it.specific_refs) do
                                    if ref.type == df.specific_ref_type.JOB then
                                        local j = ref.data.job
                                        g.slab_job = {type = df.job_type[j.job_type], suspended = j.flags.suspend or nil,
                                                      worker = dfhack.job.getWorker(j) and true or nil}
                                        local h = dfhack.job.getHolder(j)
                                        if h then g.slab_job.building = df.building_type[h:getType()]; g.slab_job.stage = h:getBuildStage() end
                                        -- (0.104.46) why it's suspended, by DFHack's suspendmanager
                                        pcall(function()
                                            local sm = require('plugins.suspendmanager')
                                            local keys = {}
                                            for k, v in pairs(sm) do if type(v) == 'function' then table.insert(keys, k) end end
                                            table.sort(keys)
                                            out.sm_api = keys
                                            for _, fn in ipairs({'suspendmanager_suspensionDescription', 'suspensionDescription',
                                                                 'getSuspensionDescription', 'suspendmanager_getDescription'}) do
                                                if sm[fn] then g.slab_job.why = tostring(sm[fn](j)) break end
                                            end
                                            if sm.isKeptSuspended then g.slab_job.kept = sm.isKeptSuspended(j) end
                                        end)
                                        pcall(function()
                                            local pos = xyz2pos(h.centerx, h.centery, h.z)
                                            local n = 0
                                            for _, it2 in ipairs(dfhack.maps.getTileBlock(pos).items) do
                                                local i2 = df.item.find(it2)
                                                if i2 and i2.pos.x == pos.x and i2.pos.y == pos.y and i2.pos.z == pos.z then n = n + 1 end
                                            end
                                            g.slab_job.items_on_tile = n
                                            g.slab_job.at = {x = pos.x, y = pos.y, z = pos.z}
                                        end)
                                    end
                                end
                            end)
                            pcall(function()
                                if from0 and x then g.slab_at.reach = dfhack.maps.canWalkBetween(from0, xyz2pos(x, y, z)) end
                            end)
                            -- (0.104.48) out of reach: the tiles round it, to see why
                            pcall(function()
                                if g.slab_at.reach == false and x then
                                    local rows = {}
                                    for yy = y - 3, y + 3 do
                                        local row = {}
                                        for xx = x - 3, x + 3 do
                                            local ch = '?'
                                            local tt = dfhack.maps.getTileType(xx, yy, z)
                                            local d, occ = dfhack.maps.getTileFlags(xx, yy, z)
                                            if tt then
                                                local sh = df.tiletype_shape[df.tiletype.attrs[tt].shape]
                                                ch = (sh == 'WALL' and '#') or (sh == 'FLOOR' and '.') or (sh == 'RAMP' and '^')
                                                    or (sh and sh:find('STAIR') and 'X') or (sh == 'EMPTY' and ' ') or ','
                                                if occ and occ.building ~= df.tile_building_occ.None then ch = 'B' end
                                                if d and d.flow_size > 0 then ch = d.flow_size >= 4 and 'W' or 'w' end
                                                if xx == x and yy == y then ch = '@' end
                                            end
                                            table.insert(row, ch)
                                        end
                                        table.insert(rows, table.concat(row))
                                    end
                                    g.slab_at.around = rows
                                    local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
                                    if b then g.slab_at.building = df.building_type[b:getType()] end
                                end
                            end)
                        end
                    end)
                    pcall(function()
                        local c = body_of(u.id)
                        g.body = c and (c.flags.in_building and 'entombed' or 'lying') or 'none'
                    end)
                    table.insert(out.ghost_list, g)
                end
            end)
        end
    end
    -- (0.104.15) why the unburied aren't buried: Enxah had 104 bodies and
    -- 7 free tombs for a whole season. Forbidden (DF's "forbid your dead"
    -- standing order, or by hand), marked for dumping, out of the dwarves'
    -- reach, or already on someone's job.
    local why = {forbidden = 0, dump = 0, in_job = 0, unreachable = 0, outside = 0, carried = 0,
                 not_ours = 0, free = 0}
    local samples = {}
    local from = from0      -- where the first citizen stands (13c: found once, above)
    for _, it in ipairs(df.global.world.items.other.CORPSE) do
        local ok, r = pcall(function() return it.race end)
        if ok and r == race and not it.flags.in_building and not it.flags.removed then
            out.unburied = out.unburied + 1
            pcall(function()
                local f = it.flags
                if f.forbid then why.forbidden = why.forbidden + 1 end
                if f.dump then why.dump = why.dump + 1 end
                if f.in_job then why.in_job = why.in_job + 1 end
                if f.in_inventory then why.carried = why.carried + 1 end
                local x, y, z = dfhack.items.getPosition(it)
                local reach = true
                if x and from then
                    reach = dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z))
                    if not reach then why.unreachable = why.unreachable + 1 end
                    local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
                    if d and d.outside then why.outside = why.outside + 1 end
                end
                -- (0.104.16) whose body: the fort's own dead, or a visitor's,
                -- a merchant's, a migrant's who never joined (DF buries only
                -- its own in the fort's tombs)
                local okc, own = pcall(function()
                    local du = df.unit.find(it.unit_id)
                    return du ~= nil and du.civ_id == civ
                end)
                if okc and not own then why.not_ours = why.not_ours + 1 end
                if reach and not f.forbid and not f.dump and not f.in_job and not f.in_inventory
                        and (not okc or own) then
                    why.free = why.free + 1          -- nothing in the way that the AI can see
                end
                if #samples < 5 and (f.forbid or not reach) and x then
                    local smp = {x = x, y = y, z = z, forbidden = f.forbid or nil, reach = reach}
                    -- (0.104.39) what the spot is: water over it, open space,
                    -- and how this one died (Enxah: 29 bodies out of reach)
                    pcall(function()
                        local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
                        if d and d.flow_size > 0 then
                            smp.water = d.flow_size
                            if d.liquid_type then smp.magma = true end
                        end
                        local tt = dfhack.maps.getTileType(xyz2pos(x, y, z))
                        if tt then smp.shape = df.tiletype_shape[df.tiletype.attrs[tt].shape] end
                    end)
                    pcall(function()
                        local du = df.unit.find(it.unit_id)
                        local inc = du and df.incident.find(du.counters.death_id)
                        if inc then smp.cause = df.death_type[inc.death_cause] end
                    end)
                    table.insert(samples, smp)
                end
            end)
        end
    end
    if out.unburied > 0 then
        out.why = why
        if #samples > 0 then out.samples = samples end
    end
    -- (0.104.39) how the fort's own died this year and last (DF's death
    -- incidents): Enxah lost dwarves overnight with none of it said
    pcall(function()
        local by, n, killers, by_citizen = {}, 0, {}, {}
        local y0 = df.global.cur_year - 1
        for _, inc in ipairs(df.global.world.incidents.all) do
            pcall(function()
                if inc.type == df.incident_type.Death and inc.event_year >= y0 then
                    local du = df.unit.find(inc.victim)
                    if du and du.civ_id == civ and du.race == race then
                        local c = df.death_type[inc.death_cause] or tostring(inc.death_cause)
                        by[c] = (by[c] or 0) + 1
                        n = n + 1
                        -- (0.104.50) who struck them down: a citizen (a fight, a
                        -- berserk, the guard), a ghost, a beast, an outsider
                        pcall(function()
                            local k = inc.criminal ~= -1 and df.unit.find(inc.criminal)
                            if k then
                                local who = (dfhack.units.isGhost(k) or dfhack.units.isDead(k)) and 'ghost'
                                    or (dfhack.units.isCitizen(k) or k.civ_id == civ) and 'citizen'
                                    or (dfhack.units.isAnimal and dfhack.units.isAnimal(k)) and 'animal'
                                    or 'outsider'
                                killers[who] = (killers[who] or 0) + 1
                                if who == 'citizen' and #by_citizen < 8 then
                                    table.insert(by_citizen, {cause = c, killer = txt(dfhack.units.getReadableName(k)),
                                                              victim = txt(dfhack.units.getReadableName(du))})
                                end
                            end
                        end)
                    end
                end
            end)
        end
        out.deaths = {since_year = y0, n = n, by_cause = by, killers = killers,
                      by_citizen = #by_citizen > 0 and by_citizen or nil}
    end)
    -- (0.104.16) who may bury them (the Burial labour, HAUL_BODY) and whether
    -- the free tombs can be walked to
    pcall(function()
        local n, lab = 0, df.unit_labor.HAUL_BODY
        for _, u in ipairs(report_citizens(true)) do
            if u.status.labors[lab] then n = n + 1 end
        end
        out.burial_labor = n
    end)
    out._from = from
    -- the game's standing orders on the dead (the Orders screen)
    -- (0.105.27) they are uint8_t 0/1, never true: `== true` read them false always
    out.standing = standing_orders_dead()
    out.forbid_own_dead = (out.standing.forbid_own_dead or 0) ~= 0
    out.forbid_own_dead_items = (out.standing.forbid_own_dead_items or 0) ~= 0
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Coffin and b:getBuildStage() >= b:getMaxBuildStage() then
            local tomb, owner, zone = in_tomb_zone(b)
            if not tomb then
                out.loose_coffins = out.loose_coffins + 1
            else
                out.tomb_coffins = out.tomb_coffins + 1
                local st = zone and tomb_state(zone) or {}
                -- (0.104.21) a tomb closed to citizens outside the AI's tomb
                -- levels (a noble's, or one you set up) isn't free for the dead:
                -- not counted, so the tomb rules see the real room
                local reserved = st.no_citizens and not in_ai_tombs(b.centerx, b.centery, b.z)
                if reserved and coffin_is_free(b) and (owner == nil or owner < 0) then
                    out.reserved_tombs = (out.reserved_tombs or 0) + 1
                elseif coffin_is_free(b) and (owner == nil or owner < 0) then
                    out.free_tombs = out.free_tombs + 1
                    if zone then
                        if st.inactive then out.free_tombs_inactive = (out.free_tombs_inactive or 0) + 1 end
                        if st.no_citizens then
                            out.free_tombs_no_citizens = (out.free_tombs_no_citizens or 0) + 1
                            -- (0.104.19) where: a noble's tomb, or a tomb of the AI's levels
                            out.closed_tombs = out.closed_tombs or {}
                            if #out.closed_tombs < 8 then
                                table.insert(out.closed_tombs, {x = b.centerx, y = b.centery, z = b.z, zone = zone.id})
                            end
                        end
                    end
                    pcall(function()
                        if out._from and not dfhack.maps.canWalkBetween(out._from, xyz2pos(b.centerx, b.centery, b.z)) then
                            out.free_tombs_unreachable = (out.free_tombs_unreachable or 0) + 1
                        end
                    end)
                end
            end
        end
    end
    out._from = nil
    return out
end

-- Strange moods and broken minds. For a crafting mood: the skill (which
-- decides the workshop), the workshop it has claimed, and how many of the
-- items it wants it has gathered. `detail` is DFHack's own showmood text.
local CRAFT_MOODS = {Fey = true, Secretive = true, Possessed = true, Macabre = true, Fell = true}

-- How many entries a game list has. Some lists changed shape in DF 53
-- (a job's item list is now a struct holding the list in .elements), so
-- try both, and say nil rather than fail the whole report.
local function list_len(v)
    if v == nil then return nil end
    local ok, n = pcall(function() return #v end)
    if ok and type(n) == 'number' then return n end
    ok, n = pcall(function() return #v.elements end)
    if ok and type(n) == 'number' then return n end
    return nil
end

-- A mood job's requests not yet met: {item, material, flags, quantity}.
-- (0.105.24) the fallback only: lua/ai-moods.lua's mood_report counts cloth
-- by its dimension and says what the fort holds for each request.
function mood_missing(job)
    local got = {}
    for _, ref in ipairs(job.items) do
        local idx = ref.job_item_idx
        if idx and idx >= 0 then got[idx] = (got[idx] or 0) + ref.item:getStackSize() end
    end
    local out = {}
    local reqs = job.job_items
    pcall(function() if reqs.elements then reqs = reqs.elements end end)   -- (a job_reqst in 53: its vector is .elements)
    for idx, ji in ipairs(reqs) do
        local left = ji.quantity - (got[idx] or 0)
        if left > 0 then
            local flags = {}
            for _, fl in ipairs({ji.flags1, ji.flags2, ji.flags3}) do
                for name, on in pairs(fl) do
                    if on == true and type(name) == 'string' then table.insert(flags, name) end
                end
            end
            table.sort(flags)
            local mat
            if ji.mat_type >= 0 then
                local mi = dfhack.matinfo.decode(ji.mat_type, ji.mat_index)
                mat = mi and txt(mi:toString()) or nil
            end
            table.insert(out, {item = df.item_type[ji.item_type] or tostring(ji.item_type), material = mat,
                               flags = flags, quantity = left})
        end
    end
    return out
end

function get_moods()
    local list = {}
    -- (exclude_residents = false, include_insane = true): a broken mind still counts
    for _, u in ipairs(report_citizens(false, true)) do
        local mood = u.mood >= 0 and (df.mood_type[u.mood] or tostring(u.mood)) or nil
        -- "Baby" is how the game marks a baby being carried: not a mood
        if mood and mood ~= 'Baby' then
            local e = {unit_id = u.id, name = txt(dfhack.units.getReadableName(u)), mood = mood,
                       craft = CRAFT_MOODS[mood] == true}
            if e.craft then
                e.skill = df.job_skill[u.job.mood_skill] or tostring(u.job.mood_skill)
                local job = u.job.current_job
                if job then
                    e.job = df.job_type[job.job_type]
                    e.items_needed = list_len(job.job_items)
                    e.items_have = list_len(job.items)
                    -- what each of the mood's requests still lacks (what showmood shows);
                    -- (0.105.24) in the mood's order, each with what the fort holds for
                    -- it (free within reach, forbidden, claimed by a job: lua/ai-moods.lua)
                    local okm, M = pcall(reqscript, 'ai-moods')
                    local ok, missing = false, nil
                    if okm and M then ok, missing = pcall(M.mood_report, job, u, txt) end
                    if not ok then ok, missing = pcall(mood_missing, job) end
                    if ok then e.missing = missing end
                    local holder = dfhack.job.getHolder(job)
                    if holder then
                        local t = holder:getType()
                        e.workshop = (t == df.building_type.Workshop and df.workshop_type[holder.type])
                            or (t == df.building_type.Furnace and df.furnace_type[holder.type])
                            or df.building_type[t]
                    end
                end
            end
            table.insert(list, e)
        end
    end
    local out = {list = list}
    if #list > 0 then
        local ok, text = pcall(dfhack.run_command_silent, 'showmood')
        if ok and text then out.detail = txt(text):sub(1, 1500) end
    end
    return out
end

-- Society: offices nobody holds, citizens starving or parched, grazing
-- animals without a pasture (they starve).
local KEY_OFFICES = {MANAGER = true, BOOKKEEPER = true, BROKER = true, CHIEF_MEDICAL_DWARF = true,
                     SHERIFF = true, CAPTAIN_OF_THE_GUARD = true}

function get_society()
    local out = {vacant = {}, starving = 0, parched = 0, hungry_names = {}, grazers_unpastured = 0}
    local fort = df.historical_entity.find(df.global.plotinfo.group_id)
    if fort then
        local codes, held = {}, {}
        for _, pos in ipairs(fort.positions.own) do codes[pos.id] = pos.code end
        for _, a in ipairs(fort.positions.assignments) do
            local code = codes[a.position_id]
            if code and KEY_OFFICES[code] then
                if a.histfig ~= -1 then held[code] = true elseif held[code] == nil then held[code] = false end
            end
        end
        for code, h in pairs(held) do
            if not h then table.insert(out.vacant, code) end
        end
        table.sort(out.vacant)
    end
    for _, u in ipairs(report_citizens(false, true)) do
        local c = u.counters2
        local starving, parched = c.hunger_timer > 75000, c.thirst_timer > 50000
        if starving then out.starving = out.starving + 1 end
        if parched then out.parched = out.parched + 1 end
        if (starving or parched) and #out.hungry_names < 3 then
            table.insert(out.hungry_names, txt(dfhack.units.getReadableName(u)))
        end
    end
    local soc = reqscript('ai-society')
    -- (13c) the pastures and the grazers waiting for one, in one pass
    local okq, pr = pcall(soc.pasture_report)
    if okq and pr then
        out.grazers_unpastured, out.pastures = pr.grazers, pr.count
        local pn, ai = pr.needs, pr.ai
        out.grazer_tiles, out.grazer_tiles_smallest, out.pasture_spare = pn.need, pn.smallest, pn.spare
        out.ai_pastures, out.ai_pasture_tiles, out.ai_pasture_spare = ai.count, ai.tiles, ai.spare
    else
        out.pastures, out.pastures_error = 0, tostring(pr):sub(1, 160)
    end
    local okp, cap = pcall(soc.get_popcap)
    if okp and cap then out.pop_cap, out.strict_pop_cap = cap.cap, cap.strict end
    -- (0.104.78) the recreation burrow's members
    -- (0.105.33 fix) txt for the released names; a failure reported (the
    -- brain then lets everyone out), not a missing section
    local okr, rec = pcall(soc.recreation_status, txt)
    if okr and rec then out.recreation = rec
    elseif not okr then out.recreation = {error = tostring(rec):sub(1, 160)} end
    -- (0.104.167) the hospital burrow: its members and tiles, the patients walking outside;
    -- (review) the members re-checked here at every report (no drink, no hospital: let out)
    local okh, hb = pcall(soc.hospital_burrow_status, txt)
    if okh and hb then out.hospital_burrow = hb
    elseif not okh then out.hospital_burrow = {error = tostring(hb):sub(1, 160)} end
    -- (0.104.169) the calm-down burrows: the citizens in a tantrum, those kept
    -- in a free bedroom till calm, whether they stay inside; the members
    -- re-checked here at every report (calm, too long, thirsty: let out)
    local okc, cb = pcall(soc.calm_burrow_status, txt)
    if okc and cb then out.calm_burrow = cb
    elseif not okc then out.calm_burrow = {error = tostring(cb):sub(1, 160)} end
    -- (0.104.81) war dogs: who can be trained, who is, who trains them
    local oka, an = pcall(soc.animal_training_report)
    if oka and an then out.animals = an elseif not oka then out.animals = {error = tostring(an):sub(1, 160)} end
    local okg, gd = pcall(soc.gate_dogs_report)                  -- (0.104.83)
    if okg and gd and out.animals and not out.animals.error then out.animals.gate = gd end
    return out
end

function get_buildings()
    local out = {
        workshops = {}, furnaces = {}, zones = {}, other = {},
        stockpiles = 0, refuse_piles = 0, under_construction = 0, workshop_jobs_queued = 0,
        being_built = {},     -- building type -> count, not finished yet (a depot waiting for its stone)
    }
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        if t == df.building_type.Stockpile then
            out.stockpiles = out.stockpiles + 1
            local okr, refuse = pcall(function() return b.settings.flags.refuse end)
            if okr and refuse then
                out.refuse_piles = (out.refuse_piles or 0) + 1
                -- (0.104.159) where, and whether under the sky (refuse rotting
                -- indoors fills the fort with miasma)
                pcall(function()
                    local cx, cy = (b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2
                    local des = dfhack.maps.getTileFlags(cx, cy, b.z)
                    out.refuse_list = out.refuse_list or {}
                    table.insert(out.refuse_list, {id = b.id, x = cx, y = cy, z = b.z,
                                                   outside = des and des.outside and true or false,
                                                   tiles = (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1)})
                end)
            end
        elseif t == df.building_type.Civzone then
            inc(out.zones, df.civzone_type[b.type] or tostring(b.type))
        else
            if b:getBuildStage() < b:getMaxBuildStage() then
                out.under_construction = out.under_construction + 1
                inc(out.being_built, df.building_type[t] or tostring(t))
            elseif t == df.building_type.Workshop then
                inc(out.workshops, workshop_name(b))
                out.workshop_jobs_queued = out.workshop_jobs_queued + #b.jobs
            elseif t == df.building_type.Furnace then
                inc(out.furnaces, df.furnace_type[b.type] or tostring(b.type))
                out.workshop_jobs_queued = out.workshop_jobs_queued + #b.jobs
            else
                inc(out.other, df.building_type[t] or tostring(t))
            end
        end
    end
    -- spots outside being cleared of trees (kind -> trees left to fell)
    local okc, clearing = pcall(function() return reqscript('ai-builder').clearing_status() end)
    out.clearing = okc and clearing or {}
    -- the keep above ground (the Surface ambition), once begun
    local okk, keep = pcall(function() return reqscript('ai-builder').keep_status() end)
    out.keep = okk and keep or nil
    -- (0.105.30) the surface halls (lua/ai-builder-halls.lua), once begun
    local okh, halls = pcall(function() return reqscript('ai-builder').halls_status() end)
    out.halls = okh and halls or nil
    -- (0.105.23, 14.1 step 4c) the Deep mine's underground trade depot, once begun
    local okd, deep = pcall(function() return reqscript('ai-builder').deep_depot_status() end)
    out.deep_depot = okd and deep or nil
    return out
end

function get_jobs()
    local out = {total = 0, suspended = 0, by_type = {}, gather_targets = {}}
    local GATHER = df.job_type.GatherPlants
    for _, job in utils.listpairs(df.global.world.jobs.list) do
        if job then
            out.total = out.total + 1
            if job.flags.suspend then out.suspended = out.suspended + 1 end
            inc(out.by_type, df.job_type[job.job_type] or tostring(job.job_type))
            -- what plant-gathering jobs are aimed at (a fort had ~1000 of them:
            -- shrubs marked by hand or by the AI, fruit trees, or something else)
            if job.job_type == GATHER then
                pcall(function()
                    local tt = dfhack.maps.getTileType(job.pos)
                    local a = tt and df.tiletype.attrs[tt]
                    local shape = a and df.tiletype_shape[a.shape] or '?'
                    local mat = a and df.tiletype_material[a.material] or '?'
                    local key = (mat == 'TREE' or mat == 'PLANT' and shape ~= 'SHRUB') and ('tree ' .. shape:lower())
                        or shape:lower()
                    local d = dfhack.maps.getTileFlags(job.pos)
                    if d and d.dig ~= df.tile_dig_designation.No then key = key .. ' (marked)' end
                    if d and not d.outside then key = key .. ' (inside)' end
                    inc(out.gather_targets, key)
                end)
            end
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Map layers: which caverns, magma sea and underworld exist, their depth,
-- and whether the fort has discovered them. Cached per fort, because the
-- layers never move.
---------------------------------------------------------------------------

local function layer_cache_key()
    local x, y, z = dfhack.maps.getTileSize()
    return ('%s:%d:%d:%d:%d'):format(df.global.world.cur_savegame.save_dir,
        df.global.plotinfo.site_id, x, y, z)
end

function get_layers()
    if LAYER_CACHE and LAYER_CACHE.key == layer_cache_key() then
        -- "discovered" can change, so refresh just that. Look the feature up
        -- again by index: never keep a pointer to DF memory between runs.
        local mf = df.global.world.features.map_features
        for _, l in ipairs(LAYER_CACHE.list) do
            local f = l._idx < #mf and mf[l._idx] or nil
            l.discovered = f and f.flags.Discovered and true or false
        end
        return LAYER_CACHE
    end
    local feats = df.global.world.features
    local by_gid, list = {}, {}
    for i, f in ipairs(feats.map_features) do
        if df.feature_init_subterranean_from_layerst:is_instance(f)
                or df.feature_init_magma_core_from_layerst:is_instance(f)
                or df.feature_init_underworld_from_layerst:is_instance(f) then
            local l = {
                name = df.layer_type[f.start_depth] or ('Layer' .. tostring(f.start_depth)),
                discovered = f.flags.Discovered and true or false,
                _idx = i,
            }
            by_gid[feats.feature_global_idx[i]] = l
            table.insert(list, l)
        end
    end
    for _, block in ipairs(df.global.world.map.map_blocks) do
        local l = by_gid[block.global_feature]
        if l then
            local z = block.map_pos.z
            l.z_bottom = math.min(l.z_bottom or z, z)
            l.z_top = math.max(l.z_top or z, z)
        end
    end
    table.sort(list, function(a, b) return (a.z_top or -1) > (b.z_top or -1) end)
    local top = nil
    for _, l in ipairs(list) do
        if l.z_top then top = math.max(top or l.z_top, l.z_top) end
    end
    LAYER_CACHE = {key = layer_cache_key(), by_gid = by_gid, list = list, top_z = top}
    return LAYER_CACHE
end

-- Name of the layer a position is in: Cavern1-3, MagmaSea or Underworld;
-- otherwise 'upper_levels' (above the first cavern: surface and the usual
-- fort) or 'between_layers' (solid rock between the deep layers).
local function layer_at(pos, layers)
    local block = dfhack.maps.getTileBlock(pos)
    if not block then return nil end
    layers = layers or get_layers()
    local l = layers.by_gid[block.global_feature]
    if l then return l.name end
    if not layers.top_z or pos.z > layers.top_z then return 'upper_levels' end
    return 'between_layers'
end

function layers_summary()
    local out = {}
    for _, l in ipairs(get_layers().list) do
        table.insert(out, {name = l.name, discovered = l.discovered,
                           z_top = l.z_top, z_bottom = l.z_bottom})
    end
    return out
end

---------------------------------------------------------------------------
-- Who else is on the map, and can the threats reach the dwarves?
---------------------------------------------------------------------------

local function citizen_positions()
    local list, groups = {}, {}
    for _, u in ipairs(report_citizens()) do
        local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
        table.insert(list, p)
        local g = dfhack.maps.getWalkableGroup(p)
        if g ~= 0 then groups[g] = true end
    end
    return list, groups
end

local function nearest(pos, positions)
    local best_d, best_dz = nil, nil
    for _, p in ipairs(positions) do
        local dz = math.abs(p.z - pos.z)
        local d = math.max(math.abs(p.x - pos.x), math.abs(p.y - pos.y)) + dz * 3
        if not best_d or d < best_d then best_d, best_dz = d, dz end
    end
    return best_d, best_dz
end

-- Health: each citizen who needs care, with what DF says they need (its
-- rq_ flags: diagnosis, surgery, setting, sutures...), infected wounds and
-- active syndromes; the planner tracks how long each has waited.
HEALTH_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
             'rq_setting', 'rq_traction', 'rq_crutch'}

function get_health()
    -- (0.104.121) every citizen counted, the list still capped at 30: Teacheroar
    -- had 99 dwarves on the Rest job and a list that stopped at 30
    local out = {patients = {}, infected = 0, syndromes = 0, total = 0, resting = 0, resting_in_hospital = 0,
                 needs_counts = {}, waiting = 0, splint_wait = 0, stitch_wait = 0, waiting_ids = {}}
    pcall(function() out.hospital = hospital_survey() end)
    for _, u in ipairs(report_citizens()) do
        local resting = false
        pcall(function()
            local j = u.job.current_job
            resting = j ~= nil and j.job_type == df.job_type.Rest
        end)
        if resting then
            out.resting = out.resting + 1
            pcall(function()
                for _, z in ipairs(dfhack.buildings.findCivzonesAt(u.pos) or {}) do
                    if HOSPITAL_ZONES[z.id] then out.resting_in_hospital = out.resting_in_hospital + 1 break end
                end
            end)
        end
        local care = false
        pcall(function() care = u.health ~= nil and u.health.flags.needs_healthcare end)
        local infected = false
        pcall(function()
            for _, w in ipairs(u.body.wounds) do
                if w.flags.infection then infected = true break end
            end
        end)
        local syn = 0
        pcall(function() syn = #u.syndromes.active end)
        -- (0.104.159) by name: what the fort is sick (or high) with
        pcall(function()
            for _, a in ipairs(u.syndromes.active) do
                local sd = df.syndrome.find(a.type)
                local nm = sd and sd.syn_name ~= '' and txt(sd.syn_name) or ('syndrome ' .. tostring(a.type))
                out.syndrome_names = out.syndrome_names or {}
                out.syndrome_names[nm] = (out.syndrome_names[nm] or 0) + 1
            end
        end)
        if infected then out.infected = out.infected + 1 end
        if syn > 0 then out.syndromes = out.syndromes + 1 end
        if care or infected then
            out.total = out.total + 1
            -- (0.104.133, 12j) the counts the brain's rules need, in full:
            -- those with any treatment asked (and their ids, so each one's wait
            -- is tracked), splints (immobilize or traction), stitches (suture
            -- or dressing)
            pcall(function()
                local any, splint, stitch = false, false, false
                for _, f in ipairs(HEALTH_RQ) do
                    if u.health.flags[f] then
                        local k = f:gsub('^rq_', '')
                        out.needs_counts[k] = (out.needs_counts[k] or 0) + 1
                        any = true
                        if k == 'immobilize' or k == 'traction' then splint = true end
                        if k == 'suture' or k == 'dressing' then stitch = true end
                    end
                end
                if any then
                    out.waiting = out.waiting + 1
                    if #out.waiting_ids < 400 then table.insert(out.waiting_ids, u.id) end
                end
                if splint then out.splint_wait = out.splint_wait + 1 end
                if stitch then out.stitch_wait = out.stitch_wait + 1 end
            end)
        end
        if (care or infected) and #out.patients < 30 then
            local p = {id = u.id, name = txt(dfhack.units.getReadableName(u)), needs = {},
                       infected = infected or nil, syndromes = syn > 0 and syn or nil}
            pcall(function()
                for _, f in ipairs(HEALTH_RQ) do
                    if u.health.flags[f] then table.insert(p.needs, (f:gsub('^rq_', ''))) end
                end
            end)
            pcall(function()
                local j = u.job.current_job
                p.job = j and txt(dfhack.job.getName(j)) or nil
            end)
            pcall(function()
                local zs = dfhack.buildings.findCivzonesAt(u.pos) or {}
                for _, z in ipairs(zs) do
                    if HOSPITAL_ZONES[z.id] then p.in_hospital = true end
                end
                local b = dfhack.buildings.findAtTile(u.pos)
                p.on = b and df.building_type[b:getType()] or nil
            end)
            table.insert(out.patients, p)
        end
    end
    return out
end

-- (0.87.2) Read only: why patients wait (region2: a dwarf needing a dressing
-- and a bone set waited 355 days with the hospital staffed and no treatment
-- job ever made). The hospital location's zones (its building_ids), their
-- type and what stands in them (beds, traction benches, tables, chests), and
-- the staff's medical labours. HOSPITAL_ZONES (zone id -> true) is filled
-- for the patients' "in_hospital" check.
HOSPITAL_ZONES = {}
local MED_LABORS = {'DIAGNOSE', 'SURGERY', 'BONE_SETTING', 'SUTURING', 'DRESSING_WOUNDS', 'FEED_WATER_CIVILIANS',
                    'RECOVER_WOUNDED'}

function hospital_survey()
    HOSPITAL_ZONES = {}
    local site = dfhack.world.getCurrentSite()
    local out = {}
    for _, loc in ipairs(site and site.buildings or {}) do
        if df.abstract_building_type[loc:getType()] == 'HOSPITAL' then
            local e = {id = loc.id, zones = {}, staff = {}}
            local c = loc:getContents()
            for _, bid in ipairs(c and c.building_ids or {}) do
                local z = df.building.find(bid)
                if z then
                    HOSPITAL_ZONES[z.id] = true
                    local ze = {id = z.id, type = df.civzone_type[z.type] or tostring(z.type), beds = 0,
                                traction = 0, tables = 0, chests = 0,
                                x1 = z.x1, y1 = z.y1, x2 = z.x2, y2 = z.y2, z = z.z}   -- (0.104.126) where it is
                    pcall(function()
                        for _, ref in ipairs(z.contained_buildings) do
                            local t = df.building_type[ref:getType()]
                            if t == 'Bed' then ze.beds = ze.beds + 1
                            elseif t == 'TractionBench' then ze.traction = ze.traction + 1
                            elseif t == 'Table' then ze.tables = ze.tables + 1
                            elseif t == 'Box' then ze.chests = ze.chests + 1 end
                        end
                    end)
                    -- (0.88) traction benches standing or planned on the zone's
                    -- tiles at any stage (a planned one may not be linked yet)
                    pcall(function()
                        local n = 0
                        for _, b in ipairs(df.global.world.buildings.other.TRACTION_BENCH) do
                            if b.z == z.z and b.centerx >= z.x1 and b.centerx <= z.x2
                                    and b.centery >= z.y1 and b.centery <= z.y2 then
                                n = n + 1
                            end
                        end
                        ze.traction_planned = n
                    end)
                    table.insert(e.zones, ze)
                end
            end
            for _, o in ipairs(loc.occupations) do
                local u = o.unit_id ~= -1 and df.unit.find(o.unit_id)
                if u then
                    local st = {post = df.occupation_type[o.type], labors = {}, unit_id = u.id}
                    for _, l in ipairs(MED_LABORS) do
                        pcall(function() if u.status.labors[df.unit_labor[l]] then table.insert(st.labors, l) end end)
                    end
                    if #st.labors == 0 then st.labors = nil end
                    table.insert(e.staff, st)
                end
            end
            table.insert(out, e)
        end
    end
    return out
end

-- (0.104.131, 12i) A crime the AI may convict: DF has solved it (its culprit
-- known and it discovered), it waits for a trial nobody gave (Teacheroar: 399),
-- it happened here, the culprit is a living citizen, and its sentence has no
-- hammer strikes. Learned from the player's own conviction (probe_justice,
-- 31 Oct 14:25): the Justice screen sets `accused` to the culprit and DF
-- sentences the case itself a few seconds later.
CONVICT_PER_CALL_MAX = 10

-- (0.104.141) Culprits not to convict now: one already convicted and waiting
-- for the sentence, or serving one (Teacheroar's Wrestler was convicted 6
-- times in 5 minutes and suffocated by the sheriff).
function convict_busy(list)
    local busy = {}
    pcall(function()
        for i = 0, #list - 1 do
            local c = list[i]
            if c.accused ~= -1 and not c.flags.sentenced then busy[c.accused] = true end
        end
    end)
    pcall(function()
        for _, pu in ipairs(df.global.plotinfo.punishments) do busy[pu.criminal] = true end
    end)
    return busy
end

function convictable(cr, site_id)
    local ok, yes = pcall(function()
        local f = cr.flags
        if f.sentenced or not f.needs_trial or not f.discovered then return false end
        if cr.accused ~= -1 or cr.criminal == -1 then return false end
        if site_id and cr.site ~= site_id then return false end
        if (cr.punishment.hammerstrikes or 0) > 0 then return false end
        -- (0.104.141) nor a sentence of a beating (the field, where this DF has
        -- it): Teacheroar's sheriff beat a fisherdwarf to death at 19:05 for a
        -- disorderly-behaviour case the AI convicted at 18:10
        local okb, beat = pcall(function() return cr.punishment.give_beating end)
        if okb and beat and beat ~= 0 then return false end
        local okb2, beat2 = pcall(function() return cr.punishment.beating end)
        if okb2 and beat2 and beat2 ~= 0 then return false end
        local u = df.unit.find(cr.criminal)
        if not u or dfhack.units.isDead(u) or not dfhack.units.isCitizen(u) then return false end
        -- nor a child, or a culprit wounded (a beating or a chain kills sooner)
        local oka, adult = pcall(dfhack.units.isAdult, u)
        if oka and adult == false then return false end
        -- (review: not by scars, healed wounds stay listed) bleeding or in care
        local okw, hurt = pcall(function()
            return (u.body.blood_count or 0) < (u.body.blood_max or 0) or (u.health and u.health.flags.needs_healthcare)
        end)
        if okw and hurt then return false end
        return true
    end)
    return ok and yes or false
end

-- (0.104.52) Justice: the jail zones with their restraints (in use or free),
-- and the punishments waiting (beatings, hammer strikes, time in jail).
-- Enxah: 2 chains for 73 dwarves, a tantrum a minute, and a sheriff who
-- beat a clothier to death.
function get_justice()
    local out = {jails = {}, restraints = 0, restraints_used = 0, punish = {n = 0, beatings = 0, hammer = 0, prison = 0}}
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_DUNGEON) do
            local e = {id = z.id, z = z.z, chains = 0, cages = 0, used = 0}
            for _, b in ipairs(df.global.world.buildings.other.CHAIN) do
                if b.z == z.z and dfhack.buildings.containsTile(z, b.centerx, b.centery) then
                    e.chains = e.chains + 1
                    if b.chained and b.chained ~= -1 and b.chained ~= nil then e.used = e.used + 1 end
                end
            end
            pcall(function()
                for _, b in ipairs(df.global.world.buildings.other.CAGE) do
                    if b.z == z.z and dfhack.buildings.containsTile(z, b.centerx, b.centery) then
                        e.cages = e.cages + 1
                        if #b.assigned_units > 0 then e.used = e.used + 1 end
                    end
                end
            end)
            -- (0.104.138) the free floor a chain could go on (the brain picked
            -- the emptiest jail blind: "no free floor in zone 453" 16 times)
            pcall(function()
                local B = reqscript('ai-builder')
                local area = B.zone_area(z.id)
                e.free = area and #B.zone_spots(area) or 0
            end)
            out.restraints = out.restraints + e.chains + e.cages
            out.restraints_used = out.restraints_used + e.used
            table.insert(out.jails, e)
        end
    end)
    pcall(function()
        for _, pu in ipairs(df.global.plotinfo.punishments) do
            out.punish.n = out.punish.n + 1
            if (pu.beating or 0) > 0 then out.punish.beatings = out.punish.beatings + 1 end
            if (pu.hammerstrikes or 0) > 0 then out.punish.hammer = out.punish.hammer + 1 end
            if (pu.prison_counter or 0) > 0 then out.punish.prison = out.punish.prison + 1 end
        end
    end)
    -- (0.104.126) the crimes DF holds (Teacheroar: 61 citizens killed by
    -- citizens since y87, the jail empty, no punishment ever): how many, of
    -- what kind, which are sentenced, and the newest one's plain fields (the
    -- names differ between versions, so read, not assumed)
    pcall(function()
        local list = df.global.world.crimes.all
        local c = {n = #list, recent = 0, kinds = {}, flags = {}}
        local year = df.global.cur_year
        for i = #list - 1, math.max(0, #list - 400), -1 do
            local cr = list[i]
            pcall(function()
                if (cr.event_year or -1) >= year - 1 then c.recent = c.recent + 1 end
                local okm, m = pcall(function() return df.crime_type[cr.mode] or tostring(cr.mode) end)
                if okm and m then c.kinds[m] = (c.kinds[m] or 0) + 1 end
                for k, v in pairs(cr.flags) do
                    if v == true then c.flags[k] = (c.flags[k] or 0) + 1 end
                end
            end)
        end
        pcall(function()
            local cr = list[#list - 1]
            local f = {}
            for k, v in pairs(cr) do
                local tv = type(v)
                if tv == 'number' or tv == 'boolean' or tv == 'string' then f[k] = v end
            end
            c.newest = f
        end)
        pcall(function()
            local site = df.global.plotinfo.site_id
            local n, sent = 0, 0
            -- (review) counted as act_convict picks: one case a culprit, none busy
            local busy = convict_busy(list)
            for i = 0, #list - 1 do
                if convictable(list[i], site) and not busy[list[i].criminal] then
                    n = n + 1
                    busy[list[i].criminal] = true
                end
                -- (0.104.138) sentenced over every crime (the flags above count the
                -- newest 400; the AI convicts the oldest first)
                pcall(function() if list[i].flags.sentenced then sent = sent + 1 end end)
            end
            c.convictable, c.sentenced_all = n, sent
        end)
        out.crimes = c
    end)
    return out
end

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

function get_deep()
    local layers = get_layers()
    local cit_list, groups = citizen_positions()
    local out = {caverns = {}, dangers = {}, cursed = {}}
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
            if l.discovered then
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
                    local function info(x, y, z)
                        local tt = dfhack.maps.getTileType(x, y, z)
                        if not tt then return nil end
                        local des = dfhack.maps.getTileFlags(x, y, z)
                        local g = dfhack.maps.getWalkableGroup(xyz2pos(x, y, z))
                        return {cave = des and (des.feature_global or des.feature_local), g = g,
                                shape = df.tiletype_shape[df.tiletype.attrs[tt].shape]}
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
    for _, u in ipairs(report_units()) do
        if dfhack.units.isActive(u) and not dfhack.units.isDead(u)
                and not dfhack.units.isHidden(u)
                and not dfhack.units.isCitizen(u, true) then
            local contained = u.flags1.caged or u.flags1.chained
            if dfhack.units.isDanger(u) and contained then
                out.contained_dangers = out.contained_dangers + 1
            elseif dfhack.units.isDanger(u) then
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
            if from then
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
                               'METAL_CRAFT', 'GLASSMAKER', 'MECHANIC'}) do
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
function death_details(ev, id)
    local u = df.unit.find(id)
    if not u then return end
    if DEATHS_TOLD[id] then ev.again = true end
    DEATHS_TOLD[id] = true
    pcall(function() if dfhack.units.isGhost(u) then ev.ghost = true end end)
    local inc = df.incident.find(u.counters.death_id)
    if not inc then return end
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
