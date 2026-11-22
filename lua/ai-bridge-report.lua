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
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report'] = '0.105.64'   -- (0.105.26) bumped with BRIDGE_VERSION

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

-- (0.105.46) The craft skills, for "legendary at a craft": the skills a
-- strange mood can take (the dwarf makes an artifact at them: brain's
-- MOOD_WORKSHOPS and ai-homes' CRAFT_SHOP) and the other makers of quality
-- goods (furniture forging, engraving, pottery, glazing, wax, siege
-- engines). Not mining, woodcutting, farming, cooking, brewing, fighting,
-- talking, nursing or hauling: they make nothing an artisan would sign.
CRAFT_SKILLS = {}
for _, k in ipairs({'WOODCRAFT', 'STONECRAFT', 'BONECARVE', 'CARPENTRY', 'MASONRY', 'CUTGEM', 'ENCRUSTGEM',
                    'FORGE_WEAPON', 'FORGE_ARMOR', 'FORGE_FURNITURE', 'METALCRAFT', 'CLOTHESMAKING', 'WEAVING',
                    'LEATHERWORK', 'TANNER', 'GLASSMAKER', 'BOWYER', 'MECHANICS', 'SIEGECRAFT', 'DETAILSTONE',
                    'POTTERY', 'GLAZING', 'WAX_WORKING'}) do CRAFT_SKILLS[k] = true end

function get_dwarves(include_units)
    local summary = {
        total = 0, adults = 0, children = 0, legendary = 0,
        legendary_craft = 0,      -- (0.105.46) adults legendary at a craft skill (CRAFT_SKILLS)
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
        -- (0.105.46) legendary at a craft (CRAFT_SKILLS): the scorecard's
        -- Craftsmanship line (any skill counted miners, fighters, talkers)
        if not is_child then
            pcall(function()
                for _, sk in ipairs(u.status.current_soul.skills) do
                    if sk.rating >= 15 and CRAFT_SKILLS[df.job_skill[sk.id] or ''] then
                        summary.legendary_craft = summary.legendary_craft + 1
                        break
                    end
                end
            end)
        end
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
    local out = {needs = {}, deities = {}, deity_ids = {}, stressed = {}, worship = {}, content_ids = {}}
    local stress_cat = {}       -- (0.105.51) each listed row's stress category, for the sort
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
            -- (0.105.51) the plain unhappy (2) listed too, after the worse:
            -- E's bulk (17-30 dwarves) sat there, and stress care and the
            -- recreation burrow reach them when the fort's unhappy share is high
            if cat <= 2 then
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
                -- (0.105.48) one row a dwarf: a merge left a second insert here
                local row = {id = u.id, name = t(dfhack.units.getReadableName(u)),
                             stress = STRESS_LABELS[cat], unmet = w, bedroom = bedroom,
                             squad = squad or nil, leader = (squad and leader) or nil,
                             wants_fight = fight or nil,
                             -- (0.105.47) the need is theirs at all (met in a squad,
                             -- or not): stress care keeps them training, never releases
                             fight_need = fight_focus ~= nil or nil}
                -- (0.105.47, I7b) a child (no bedroom of their own is theirs to
                -- get: a baby was asked one four times), the long-term stress
                -- (DF's stress category follows it; it drains slowly), born
                pcall(function() if not dfhack.units.isAdult(u) then row.child = true end end)
                pcall(function() row.longterm = u.status.current_soul.personality.longterm_stress end)
                pcall(function() row.born = u.birth_year; row.hf = u.hist_figure_id end)
                table.insert(out.stressed, row)
                stress_cat[row] = cat
            end
            -- (0.105.47) the content or better (category 4+): the AI's "never
            -- draft" memory forgets one whose mood rose that far
            if cat >= 4 and #out.content_ids < 300 then table.insert(out.content_ids, u.id) end
        end
    end
    -- (0.105.51) by DF's category, the worst first (the labels sorted as
    -- words put 'unhappy' before 'very_unhappy'), then the long-term stress
    table.sort(out.stressed, function(a, b)
        local ca, cb = stress_cat[a] or 9, stress_cat[b] or 9
        if ca ~= cb then return ca < cb end
        return (tonumber(a.longterm) or 0) > (tonumber(b.longterm) or 0)
    end)
    while #out.stressed > 8 do table.remove(out.stressed) end
    -- (0.105.47, I7b) the year each of the listed came to the fort (lua/ai-welfare.lua)
    pcall(function()
        local hfs = {}
        for _, r in ipairs(out.stressed) do if r.hf and r.hf >= 0 then table.insert(hfs, r.hf) end end
        local years = reqscript('ai-welfare').arrivals(hfs)
        for _, r in ipairs(out.stressed) do if r.hf and years[r.hf] then r.arrived = years[r.hf] end end
    end)
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
-- (r6) This and report_units are the bridge's own, not copies of the modules'
-- report_citizens/report_units (those read ai-util's REPORT_CTX): these read
-- the bridge's REPORT_CTX and hand the call to its ai-util (.util: U.citizens,
-- U.units_active), so a test's stub bridge without ai-util walks afresh. Kept.
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
    local c = {count = 0, free = 0, free_items = 0, stone = {}, by_mat = {}, stone_job = {}, stone_forbid = {}}
    for _, item in ipairs(df.global.world.items.other.BOULDER) do
        if usable(item) then
            local n = item:getStackSize()
            c.count = c.count + n
            if not item.flags.in_job then
                c.free, c.free_items = c.free + n, c.free_items + 1
                if item.mat_type == 0 then c.stone[item.mat_index] = (c.stone[item.mat_index] or 0) + n end
                local key = item:getMaterial() .. ':' .. item:getMaterialIndex()
                c.by_mat[key] = (c.by_mat[key] or 0) + 1
            elseif item.mat_type == 0 then
                -- (item7) taken by a job (a mason's, a hauler's): the quarry's stone in use
                c.stone_job[item.mat_index] = (c.stone_job[item.mat_index] or 0) + item:getStackSize()
            end
        elseif item.flags.forbid and item.mat_type == 0 and not (item.flags.garbage_collect
                or item.flags.removed or item.flags.construction or item.flags.in_building) then
            -- (item7) forbidden stone: a quarry adds nothing the masons may take
            c.stone_forbid[item.mat_index] = (c.stone_forbid[item.mat_index] or 0) + item:getStackSize()
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
    local census = boulder_census()
    local counts = census.stone
    local out = {usable = 0, economic = {}, fuel_free = {}, in_job = 0, forbidden = 0}
    -- (item7) ordinary stone held by a job or forbidden, and the newest
    -- quarry's tiles (still to dig, mark dropped, dug): the quarry rule waits
    -- for one to be dug and counted before the next, and stops when the
    -- stone it brings never reaches the masons
    for idx, n in pairs(census.stone_job or {}) do
        if not stone_is_economic(economic, idx) then out.in_job = out.in_job + n end
    end
    for idx, n in pairs(census.stone_forbid or {}) do
        if not stone_is_economic(economic, idx) then out.forbidden = out.forbidden + n end
    end
    pcall(function() out.quarry = reqscript('ai-industry').quarry_status() end)
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

-- (r6) The local helpers this file's parts (ai-bridge-report-supplies, -fort,
-- -world, loaded after it) use too: the same functions, handed on.
REPORT_PART_LOCALS = {inc = inc, usable = usable, TICKS_PER_DAY = TICKS_PER_DAY}
