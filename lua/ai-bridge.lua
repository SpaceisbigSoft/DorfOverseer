-- ai-bridge: the AI's window into the fortress.
--
-- Usage (in the DFHack launcher, or from outside with dfhack-run):
--   ai-bridge version            versions, protocol and known actions
--   ai-bridge status             cheap check: in a fort? paused? date?
--   ai-bridge state              writes a full fort report to a JSON file
--   ai-bridge state --no-units   same, without the per-dwarf list (smaller)
--   ai-bridge state --tier pulse a small report (dwarves, stocks, threats,
--                                orders, projects...; never the units list)
--   ai-bridge state --tier daily the full report (the default); survey is
--                                the same for now
--   ai-bridge pause              pause the game (resume only via run, so
--                                the game can never be left running unattended)
--   ai-bridge run <ticks>        unpause, then pause again after <ticks>
--   ai-bridge act <json>         perform one action (see ACTIONS below)
--   ai-bridge watch              start the event feed (runs on map load)
--   ai-bridge events             hand over queued events, written to a file
--   ai-bridge map                cavern / magma / underworld layers and depths
--   ai-bridge probe_defence [x y z ...]  read-only: lever links, bridge, hatch
--                                and trap support, what's on the given tiles
--   ai-bridge memory             the overseer's memory from the save, written
--                                to memory-from-save.json (saved with the
--                                save_memory action from memory-to-save.json)
--   ai-bridge survey             staircases, the dwarves' busiest level and
--                                soil levels, as elevations (read-only; for
--                                the overseer's master plan)
--
-- Every command prints exactly one line of JSON: {"ok": true, ...} or
-- {"ok": false, "error": "..."}. The fort report itself goes to a UTF-8 file
-- (dfhack-config/ai-overseer/state.json) because DF names can contain
-- characters that don't survive console output.
--@ module = true

local json = require('json')
local utils = require('utils')

BRIDGE_VERSION = '0.104.129'
PROTOCOL = 1 -- bump when the report's shape changes in a breaking way

local OUT_DIR = dfhack.getDFPath() .. '/dfhack-config/ai-overseer'
local STATE_FILE = OUT_DIR .. '/state.json'
local EVENTS_FILE = OUT_DIR .. '/events.json'
-- The overseer's memory travels through files (it's too big for a command line).
local MEMORY_TO_SAVE = OUT_DIR .. '/memory-to-save.json'
local MEMORY_FROM_SAVE = OUT_DIR .. '/memory-from-save.json'
MEMORY_KEY = 'ai-overseer/memory'          -- older bridges: everything in one table
MEMORY_KIND_PREFIX = 'ai-overseer/mem/'     -- now: one key per kind, as JSON text
MEMORY_KINDS = {'working', 'timeline', 'atlas', 'chronicle', 'knowledge'}

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
local STOCK_CATEGORIES = {
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

local function txt(s)
    if s == nil then return nil end
    return dfhack.df2utf(s)
end

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
        stress = {},
        professions = {},
    }
    for _, label in pairs(STRESS_LABELS) do summary.stress[label] = 0 end

    local units = {}
    for _, u in ipairs(dfhack.units.getCitizens()) do
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

function get_instruments()
    local out = {known = {}, jobs = {}}
    for _, j in ipairs({'MakeInstrument', 'MakeInstrumentPiece', 'AssembleInstrument'}) do
        local ok, v = pcall(function() return df.job_type[j] end)
        if ok and v ~= nil then table.insert(out.jobs, j) end
    end
    local civ = df.historical_entity.find(df.global.plotinfo.civ_id)
    local allowed = {}
    pcall(function() for _, i in ipairs(civ.resources.instrument_type) do allowed[i] = true end end)
    pcall(function()
        for i, d in ipairs(df.global.world.raws.itemdefs.instruments) do
            local e = {id = d.id, name = txt(d.name), known = allowed[d.subtype] or allowed[i] or nil,
                       pieces = 0, flags = {}, materials = {}}
            pcall(function() e.pieces = #d.pieces end)
            pcall(function()
                for k, v in pairs(d.flags) do if v == true then table.insert(e.flags, tostring(k)) end end
            end)
            pcall(function()
                for k, v in pairs(d.material_str or {}) do table.insert(e.materials, txt(tostring(v))) end
            end)
            pcall(function() e.size = d.size end)
            pcall(function()
                e.piece_list = {}
                for _, pc in ipairs(d.pieces) do
                    table.insert(e.piece_list, {type = txt(tostring(pc.type)), name = txt(tostring(pc.name))})
                end
            end)
            table.insert(out.known, e)
        end
    end)
    return out
end

function get_needs(txt_fn)
    local t = txt_fn or txt
    local out = {needs = {}, deities = {}, deity_ids = {}, stressed = {}}
    local deity_names = {}
    for _, u in ipairs(dfhack.units.getCitizens()) do
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
                        local key = tostring(nd.deity_id)
                        if deity_names[key] == nil then
                            local okd, nm = pcall(function()
                                local hf = df.historical_figure.find(nd.deity_id)
                                local f = dfhack.translation and dfhack.translation.translateName or dfhack.TranslateName
                                return t(f(hf.name, true))
                            end)
                            deity_names[key] = (okd and nm and nm ~= '') and nm or ('deity ' .. key)
                        end
                        out.deities[deity_names[key]] = (out.deities[deity_names[key]] or 0) + 1
                        out.deity_ids[deity_names[key]] = nd.deity_id   -- (0.102.1) for a temple to that god
                    end
                end
            end
            -- (0.104.64) the training need's worst level for this dwarf
            for _, nd in ipairs(needs) do
                local nm = df.need_type[nd.id]
                if nm == 'Fight' or nm == 'MartialTraining' then
                    fight_focus = math.min(fight_focus or nd.focus_level, nd.focus_level)
                end
            end
            -- (0.104.64) soldiers whose training is met while two or more other
            -- needs go badly unmet (constant training leaves them no time),
            -- and civilians who badly want to train: the AI swaps them
            if soldier and not leader and #badly_other >= 2 and (fight_focus == nil or fight_focus > DISTRACTED) then
                out.starved_soldiers = out.starved_soldiers or {}
                if #out.starved_soldiers < 8 then
                    table.insert(out.starved_soldiers, {id = u.id, name = t(dfhack.units.getReadableName(u)),
                                                        unmet = badly_other})
                end
            elseif not soldier and fight_focus and fight_focus <= BADLY and dfhack.units.isAdult(u) then
                out.keen_civilians = (out.keen_civilians or 0) + 1
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
                local fight = false
                pcall(function()
                    for _, nd in ipairs(u.status.current_soul.personality.needs) do
                        local nm = df.need_type[nd.id]
                        if (nm == 'Fight' or nm == 'MartialTraining') and nd.focus_level <= -1000 then fight = true end
                    end
                end)
                table.insert(out.stressed, {id = u.id, name = t(dfhack.units.getReadableName(u)),
                                            stress = STRESS_LABELS[cat], unmet = w, bedroom = bedroom,
                                            squad = squad or nil, leader = (squad and leader) or nil,
                                            wants_fight = fight or nil})
            end
        end
    end
    table.sort(out.stressed, function(a, b) return a.stress < b.stress end)
    while #out.stressed > 8 do table.remove(out.stressed) end
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
        for _, u in ipairs(dfhack.units.getCitizens()) do
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
            for _, u in ipairs(dfhack.units.getCitizens(true)) do
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
    pcall(function() out.craft_shops = reqscript('ai-society').craft_shops() end)
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

-- Stone in stock, for the culture's material picker: the commonest stone
-- types among loose boulders, with their colour (0-1 RGB) and base value.
function get_stone_types()
    local counts = {}
    for _, item in ipairs(df.global.world.items.other.BOULDER) do
        if item.mat_type == 0 and usable(item) and not item.flags.in_job then
            counts[item.mat_index] = (counts[item.mat_index] or 0) + item:getStackSize()
        end
    end
    local colors = df.global.world.raws.descriptors.colors
    local economic = df.global.plotinfo.economic_stone
    local out = {}
    for idx, n in pairs(counts) do
        local mi = dfhack.matinfo.decode(0, idx)
        -- ores and other "economic" stone are kept for their real use
        if mi and mi.material and mi.material.flags.IS_STONE
                and not (idx < #economic and economic[idx]) then
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
    local counts = {}
    for _, item in ipairs(df.global.world.items.other.BOULDER) do
        if item.mat_type == 0 and usable(item) and not item.flags.in_job then
            counts[item.mat_index] = (counts[item.mat_index] or 0) + item:getStackSize()
        end
    end
    local out = {usable = 0, economic = {}, fuel_free = {}}
    for idx, n in pairs(counts) do
        local inorg = df.global.world.raws.inorganics.all[idx] or df.global.world.raws.inorganics[idx]
        if inorg then
            local econ = idx < #economic and economic[idx] and economic[idx] ~= 0
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

-- The fort's locations (temples, taverns, libraries...), by type.
-- (0.87) Petitions: the ones waiting for an answer (plotinfo.petitions,
-- unapproved agreements: residency and citizenship by visitors, temples and
-- guildhalls by groups) and DF's own standing orders that answer residency
-- and citizenship petitions by themselves (the standing orders screen;
-- read before they're ever changed: 0 or 1 each).
PETITION_ORDERS = {'performer', 'scholar', 'monster_hunter', 'mercenary', 'sanctuary', 'citizenship'}

local function petition_order_name(k)
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
        if hf then e.deity = txt(dfhack.translation and dfhack.translation.translateName(hf.name, true)
                                 or dfhack.TranslateName(hf.name, true)) end
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
                    local party = data and data.applicant
                    for _, pt in ipairs(a.parties) do
                        if pt.id == party and #pt.histfig_ids > 0 then
                            local hf = df.historical_figure.find(pt.histfig_ids[0])
                            local u = hf and df.unit.find(hf.unit_id)
                            if u then
                                e.name = txt(dfhack.units.getReadableName(u))
                                pcall(function() e.vampire = dfhack.units.isBloodsucker(u) or nil end)
                            end
                        end
                    end
                end)
                table.insert(out.pending, e)
            end
        end
    end)
    if #out.pending == 0 then out.pending = nil end
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
                                        name = txt(dfhack.translation and dfhack.translation.translateName(ent.name, true)
                                                   or dfhack.TranslateName(ent.name, true))})
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
    if not d or df.agreement_details_type[d.type] ~= 'Location' then
        return {ok = false, rejected = true, error = 'only temple and guildhall petitions are answered by the AI'}
    end
    local wish = location_wish(a)
    local out = {ok = true, id = id, accepted = accept or nil, declined = (not accept) or nil, wish = wish,
                 dry_run = dry_run or nil}
    if dry_run then return out end
    if accept then a.flags.petition_not_accepted = false end
    list:erase(idx)
    local still = false
    for _, v in ipairs(list) do if v == id then still = true end end
    out.ok = not still and (not accept or a.flags.petition_not_accepted == false)
    return out
end

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
                -- (0.89) what a temple is dedicated to, what a guildhall's for
                pcall(function()
                    if t == 'TEMPLE' then
                        local dt = df.religious_practice_type[b.deity_type]
                        if dt == 'WORSHIP_HFID' then e.deity_hf = b.deity_data.Deity
                        elseif dt == 'RELIGION_ENID' then e.religion = b.deity_data.Religion end
                    elseif t == 'GUILDHALL' then
                        e.profession = df.profession[c.profession]
                    end
                end)
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
    return out
end

local function count_stocks()
    local stocks = {}
    local other = df.global.world.items.other
    for _, cat in ipairs(STOCK_CATEGORIES) do
        local label, list_name = cat[1], cat[2]
        local count = 0
        for _, item in ipairs(other[df.items_other_id[list_name]]) do
            if usable(item) then
                count = count + item:getStackSize()
            end
        end
        stocks[label] = count
    end
    return stocks
end

-- (0.100, review) Counting in the background between reports was tried
-- and dropped: run all the time it cost more frame time over a session than
-- the 27 ms a report it saved, and counts a few seconds old made the
-- "have + queued" rules order twice. One count a report, as before.
function get_stocks()
    return count_stocks()
end

-- Supplies that stall a fort without anyone noticing: empty containers
-- (brewing and cooking stop without them) and what a hospital and wells use.
-- Items already in a job don't count as free.
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
    each('PLANT', function(it) if brewable(it) then out.brewable_plants = out.brewable_plants + it:getStackSize() end end)
    -- (0.104.11) plants that give thread (Enxah had none: 59 thread orders stood still)
    out.thread_plants = 0
    each('PLANT', function(it)
        local okp, yes = pcall(function()
            local mi = dfhack.matinfo.decode(it)
            return mi and mi.plant and reqscript('ai-builder').plant_thread(mi.plant)
        end)
        if okp and yes then out.thread_plants = out.thread_plants + it:getStackSize() end
    end)
    each('PLANT_GROWTH', function(it)
        if brewable(it) then out.brewable_growths = out.brewable_growths + it:getStackSize() end
    end)
    -- (0.104.28) the wool route: tame animals that can be shorn (their caste
    -- has a shearable layer: sheep, llamas, alpacas, goats...). Enxah had no
    -- fibre crop and waited for caravans while patients went without sutures.
    out.shearable = 0
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
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
    -- (0.104.79) milk to make cheese of (a liquid of a milk material, not milk of lime)
    out.milk = 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.LIQUID_MISC) do
            local mi = dfhack.matinfo.decode(it)
            local tok = mi and mi:getToken() or ''
            if tok:find('MILK') and not tok:find('MILK_OF_LIME') and not it.flags.forbid and not it.flags.rotten then
                out.milk = out.milk + 1
            end
        end
    end)
    -- (0.100) raw food stacks: a cooking job takes 2-4 whole stacks, so the
    -- planner limits meal jobs by stacks, not by items
    out.food_stacks = 0
    for _, kind in ipairs({'MEAT', 'FISH', 'PLANT', 'PLANT_GROWTH', 'CHEESE', 'EGG'}) do
        each(kind, function(it) out.food_stacks = out.food_stacks + 1 end)
    end
    -- (0.104.80) nest boxes: built ones, and free ones to build
    out.nest_boxes, out.nest_box_items = 0, 0
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.NestBox then out.nest_boxes = out.nest_boxes + 1 end
        end
    end)
    each('TOOL', function(it)
        if it.subtype and it.subtype.id == 'ITEM_TOOL_NEST_BOX' then out.nest_box_items = out.nest_box_items + 1 end
    end)
    each('TOOL', function(it)
        if it.subtype and it.subtype.id == 'ITEM_TOOL_LARGE_POT' and is_empty(it) then
            out.empty_pots = out.empty_pots + 1
        end
        if it.subtype and it.subtype.id == 'ITEM_TOOL_WHEELBARROW' then
            out.wheelbarrows = (out.wheelbarrows or 0) + 1
        end
    end)
    -- (0.88.2) bags are their own item type, BAG (live 0.88.1: 92 boxes, all
    -- stone and wood chests; 838 seed stacks in BAG items). The old count
    -- looked for cloth "boxes", so it read 0 empty bags since it was written,
    -- and the kiln never got its order.
    each('BAG', function(it)
        if is_empty(it) then out.empty_bags = out.empty_bags + 1 end
    end)
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
                    else use.empty = use.empty + 1 end
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
        local best, skilled = 0, 0
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local r = dfhack.units.getNominalSkill(u, df.job_skill.COOK, true) or 0
            if r > best then best = r end
            if r >= 5 then skilled = skilled + 1 end
        end
        local kmin = nil
        for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
            if b.type == df.workshop_type.Kitchen then
                local m = b.profile.min_level
                if kmin == nil or m < kmin then kmin = m end
            end
        end
        out.cooks = {best = best, skilled = skilled, kitchen_min = kmin}
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
    each_any('LIQUID_MISC', function(it)
        local _, mi = mat_flags(it)
        if mi and mi:getToken() == 'LYE' then out.lye = out.lye + 1 end
    end)
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
    out.quicklime, out.plaster, out.milk_of_lime, out.sheets, out.blank_quires, out.hides = 0, 0, 0, 0, 0, 0
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
    each_any('LIQUID_MISC', function(it)
        local _, mi = mat_flags(it)
        if mi and mi:getToken():find('MILK_OF_LIME') then out.milk_of_lime = out.milk_of_lime + 1 end
    end)
    each('SHEET', function(it) out.sheets = out.sheets + it:getStackSize() end)
    each('TOOL', function(it)
        if it.subtype and it.subtype.id == 'ITEM_TOOL_QUIRE' then
            local written = false
            pcall(function()
                for _, imp in ipairs(it.improvements) do
                    if imp:getType() == df.improvement_type.WRITING then written = true end
                end
            end)
            if not written then out.blank_quires = out.blank_quires + 1 end
        end
    end)
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
    local classes = {}
    each('BOULDER', function(it)
        local key = it:getMaterial() .. ':' .. it:getMaterialIndex()
        local c = classes[key]
        if c == nil then
            c = ''
            local _, mi = mat_flags(it)
            pcall(function()
                for _, rc in ipairs(mi.material.reaction_class) do
                    if rc.value == 'CALCIUM_CARBONATE' or rc.value == 'GYPSUM' then c = rc.value end
                end
            end)
            classes[key] = c
        end
        if c == 'CALCIUM_CARBONATE' then out.calcium_carbonate = out.calcium_carbonate + 1
        elseif c == 'GYPSUM' then out.gypsum = out.gypsum + 1 end
    end)
    each('CLOTH', function(it)
        local f = mat_flags(it)
        local k = f and (f.SILK and 'silk' or f.YARN and 'yarn' or f.THREAD_PLANT and 'plant') or nil
        if k then out.cloth_kinds[k] = out.cloth_kinds[k] + it:getStackSize() end
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

function get_dead()
    AI_TOMBS = nil
    local out = {ghosts = 0, ghost_names = {}, unburied = 0, tomb_coffins = 0, free_tombs = 0,
                 loose_coffins = 0}
    local race, civ = df.global.plotinfo.race_id, df.global.plotinfo.civ_id
    local from0
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then from0 = xyz2pos(x, y, z) break end
        end
    end)
    for _, u in ipairs(df.global.world.units.active) do
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
                        for _, it in ipairs(df.global.world.items.other.SLAB) do
                            if it.engraving_type == df.slab_engraving_type.Memorial and it.topic == u.hist_figure_id then
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
                        end
                    end)
                    pcall(function()
                        local body = false
                        for _, c in ipairs(df.global.world.items.other.CORPSE) do
                            if c.unit_id == u.id then
                                body = c.flags.in_building and 'entombed' or 'lying'
                            end
                        end
                        g.body = body or 'none'
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
    local from
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then from = xyz2pos(x, y, z) break end
        end
    end)
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
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            if u.status.labors[lab] then n = n + 1 end
        end
        out.burial_labor = n
    end)
    out._from = from
    -- the game's standing orders on the dead (the Orders screen)
    pcall(function() out.forbid_own_dead = df.global.standing_orders_forbid_own_dead == true end)
    pcall(function() out.forbid_own_dead_items = df.global.standing_orders_forbid_own_dead_items == true end)
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
    for _, u in ipairs(dfhack.units.getCitizens(false, true)) do
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
                    -- what each of the mood's requests still lacks (what showmood shows)
                    local ok, missing = pcall(mood_missing, job)
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
    for _, u in ipairs(dfhack.units.getCitizens(false, true)) do
        local c = u.counters2
        local starving, parched = c.hunger_timer > 75000, c.thirst_timer > 50000
        if starving then out.starving = out.starving + 1 end
        if parched then out.parched = out.parched + 1 end
        if (starving or parched) and #out.hungry_names < 3 then
            table.insert(out.hungry_names, txt(dfhack.units.getReadableName(u)))
        end
    end
    local soc = reqscript('ai-society')
    out.grazers_unpastured = #soc.unpastured_grazers()
    out.pastures = soc.pasture_count()
    local okn, pn = pcall(soc.pasture_needs)
    if okn and pn then
        out.grazer_tiles, out.grazer_tiles_smallest, out.pasture_spare = pn.need, pn.smallest, pn.spare
    end
    local oka, ai = pcall(soc.ai_pastures)
    if oka and ai then
        out.ai_pastures, out.ai_pasture_tiles, out.ai_pasture_spare = ai.count, ai.tiles, ai.spare
    end
    local okp, cap = pcall(soc.get_popcap)
    if okp and cap then out.pop_cap, out.strict_pop_cap = cap.cap, cap.strict end
    -- (0.104.78) the recreation burrow's members
    local okr, rec = pcall(soc.recreation_status)
    if okr and rec then out.recreation = rec end
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
            if okr and refuse then out.refuse_piles = (out.refuse_piles or 0) + 1 end
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

local function layers_summary()
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
    for _, u in ipairs(dfhack.units.getCitizens()) do
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

---------------------------------------------------------------------------
-- Hazards (phase 11): fire and clouds near the dwarves, dwarves standing in
-- deep water or magma, citizens gone berserk, and invaders caught in cages.
-- Cheap: the flow list and the citizens' own tiles, nothing scanned.
---------------------------------------------------------------------------
HAZARD_NEAR = 20                 -- tiles (levels count 3) from the nearest dwarf
local FIRE_FLOWS = {Fire = true, Dragonfire = true}
local CLOUD_FLOWS = {MaterialGas = true, MaterialVapor = true, Miasma = false}

-- Health: each citizen who needs care, with what DF says they need (its
-- rq_ flags: diagnosis, surgery, setting, sutures...), infected wounds and
-- active syndromes; the planner tracks how long each has waited.
HEALTH_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
             'rq_setting', 'rq_traction', 'rq_crutch'}

function get_health()
    -- (0.104.121) every citizen counted, the list still capped at 30: Teacheroar
    -- had 99 dwarves on the Rest job and a list that stopped at 30
    local out = {patients = {}, infected = 0, syndromes = 0, total = 0, resting = 0, resting_in_hospital = 0,
                 needs_counts = {}}
    pcall(function() out.hospital = hospital_survey() end)
    for _, u in ipairs(dfhack.units.getCitizens()) do
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
        if infected then out.infected = out.infected + 1 end
        if syn > 0 then out.syndromes = out.syndromes + 1 end
        if care or infected then
            out.total = out.total + 1
            pcall(function()
                for _, f in ipairs(HEALTH_RQ) do
                    if u.health.flags[f] then
                        local k = f:gsub('^rq_', '')
                        out.needs_counts[k] = (out.needs_counts[k] or 0) + 1
                    end
                end
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

-- (0.104.43) A picture of the water by the fort's middle, to a file (the
-- report stays small): Enxah's drowned lie in 7-deep water on the entrance
-- level. '#' wall, '.' floor, '^' ramp, 'X' stairs, ' ' open, 'w' water 1-3,
-- 'W' water 4-7, 'M' magma; rows north to south.
function write_water_map(cx, cy, z1, z2)
    local lines = {}
    for z = z2, z1, -1 do
        table.insert(lines, ('z %d (x %d-%d, y %d-%d)'):format(z, cx - 35, cx + 35, cy - 25, cy + 25))
        for y = cy - 25, cy + 25 do
            local row = {}
            for x = cx - 35, cx + 35 do
                local ch = '?'
                pcall(function()
                    local pos = xyz2pos(x, y, z)
                    local tt = dfhack.maps.getTileType(pos)
                    local d = dfhack.maps.getTileFlags(pos)
                    if not tt then ch = ' ' return end
                    local sh = df.tiletype_shape[df.tiletype.attrs[tt].shape]
                    ch = (sh == 'WALL' and '#') or (sh == 'FLOOR' and '.') or (sh == 'RAMP' and '^')
                        or ((sh == 'STAIR_UP' or sh == 'STAIR_DOWN' or sh == 'STAIR_UPDOWN') and 'X')
                        or ((sh == 'EMPTY' or sh == 'RAMP_TOP') and ' ') or ','
                    if d and d.flow_size > 0 then
                        ch = d.liquid_type and 'M' or (d.flow_size >= 4 and 'W' or 'w')
                    end
                end)
                table.insert(row, ch)
            end
            table.insert(lines, table.concat(row))
        end
        table.insert(lines, '')
    end
    local f = io.open(dfhack.getDFPath() .. '/dfhack-config/ai-overseer/water-map.txt', 'w')
    if f then f:write(table.concat(lines, '\n')) f:close() end
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
        out.crimes = c
    end)
    return out
end

function get_hazards()
    local out = {fires = 0, fire_near = nil, clouds = 0, cloud_near = nil, miasma = 0,
                 wet = {}, burning = {}, berserk = {}, caged = 0}
    pcall(function()          -- (0.104.45) once a game week
        local wk = df.global.cur_year * 100 + df.global.cur_year_tick // (1200 * 7)
        if WATER_MAP_WEEK ~= wk then
            WATER_MAP_WEEK = wk
            write_water_map(95, 98, 165, 169)
        end
    end)
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
                elseif CLOUD_FLOWS[t] then
                    out.clouds = out.clouds + 1
                    if d and (not out.cloud_near or d < out.cloud_near) then out.cloud_near = d end
                end
            end
        end
    end)
    for _, u in ipairs(dfhack.units.getCitizens()) do
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
        for _, u in ipairs(df.global.world.units.active) do
            if u.mood == df.mood_type.Berserk and not seen[u.id] and not dfhack.units.isDead(u) then
                local own = false
                pcall(function() own = dfhack.units.isOwnGroup(u) end)
                if not own then pcall(function() own = u.civ_id == df.global.plotinfo.civ_id end) end
                if own then
                    table.insert(out.berserk, {id = u.id, name = txt(dfhack.units.getReadableName(u))})
                end
            end
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
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if u.flags1.caged and not dfhack.units.isCitizen(u, true) and dfhack.units.isActive(u)
                    and (dfhack.units.isInvader(u) or dfhack.units.isDanger(u)) then
                out.caged = out.caged + 1
            end
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
function get_deep()
    local layers = get_layers()
    local _, groups = citizen_positions()
    local out = {caverns = {}, dangers = {}, cursed = {}}
    local blocks = df.global.world.map.map_blocks
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
                for _, block in ipairs(blocks) do
                    if layers.by_gid[block.global_feature] == l then
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
                    end
                    if row.open then break end
                end
            end
            -- (0.104.103) where the dwarves' dug ground actually meets the cavern:
            -- a walkable tile outside the cavern beside (or over, or under) a
            -- walkable cavern tile of the same walk group, searched over the
            -- dwarves' x/y span near the cavern's ceiling. Up to 4, with shapes.
            local now_j = df.global.cur_year * 403200 + df.global.cur_year_tick
            local cj = JUNCTIONS[row.name]
            if row.open and cj and now_j - cj.tick < 7 * 1200 then
                row.junctions = cj.found
            elseif row.open then
                pcall(function()
                    local ps = citizen_positions()
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
                        local closed
                        if b then pcall(function() closed = b.door_flags.closed end) end
                        local des = dfhack.maps.getTileFlags(x, y, z)
                        table.insert(col, {z = z, shape = shape, building = bt, closed = closed,
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
    for _, u in ipairs(df.global.world.units.active) do
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
                if kind and #out.dangers < 20 then
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
    for _, u in ipairs(df.global.world.units.active) do
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
                for _, f in ipairs({'Undead', 'Megabeast', 'SemiMegabeast', 'NightCreature', 'Titan', 'Demon'}) do
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
                    levels_from_nearest_dwarf = dz,
                    distance_to_nearest_dwarf = dist,
                })
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
    for _, u in ipairs(dfhack.units.getCitizens()) do
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
    for _, u in ipairs(dfhack.units.getCitizens()) do
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

---------------------------------------------------------------------------
-- Event feed. DFHack's eventful plugin calls these handlers as things
-- happen; they queue events until the AI collects them with
-- `ai-bridge events`. Globals, so the queue survives between script runs.
---------------------------------------------------------------------------

EVENT_QUEUE = EVENT_QUEUE or {}
local MAX_QUEUED_EVENTS = 300
local WATCH_KEY = 'ai-overseer'

local function push_event(ev)
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
    local k = inc.criminal ~= -1 and df.unit.find(inc.criminal) or nil
    if k then
        ev.killer = txt(dfhack.units.getReadableName(k))
        local okg, ghost = pcall(dfhack.units.isGhost, k)
        ev.killer_kind = (okg and ghost) and 'ghost'
            or dfhack.units.isGreatDanger(k) and 'great beast'
            or (dfhack.units.isCitizen(k) or dfhack.units.isOwnCiv(k)) and 'citizen'
            or dfhack.units.isAnimal(k) and 'animal'
            or 'outsider'
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
        push_event({kind = 'invasion', invasion_id = id})
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

---------------------------------------------------------------------------
-- Actions: the only ways the AI can change the game. Version 1 is limited to
-- changes that are easy to see and to undo.
---------------------------------------------------------------------------

-- DFHack automation tools the AI may switch on or off. autolabor is left out
-- on purpose: turning it on rewrites every dwarf's labor assignments.
TOOL_ALLOWLIST = {
    autobutcher = true, autochop = true, autofarm = true, seedwatch = true,
    nestboxes = true, tailor = true, autoclothing = true, suspendmanager = true,
    -- needed by building projects: planned furniture waits for materials
    -- instead of vanishing
    buildingplan = true,
    -- engraves memorial slabs for ghosts (needs blank slabs in stock)
    autoslab = true,
    -- cuts rough gems at a jeweller's (the AI sells cut gems)
    autogems = true,
}
local MAX_ORDER_AMOUNT = 500
local AI_ORDERS_KEY = 'ai-overseer/orders'

-- Work orders the AI may queue. Each recipe is copied from the order sets that
-- ship with DFHack (hack/data/orders/*.json), so DF is known to accept it.
-- The AI picks a recipe name; it never supplies job types or other raw fields.
--   kind 'stone': the AI may name a specific stone (INORGANIC:<STONE>);
--                 otherwise any stone is used.
ORDER_RECIPES = {
    -- drink and food
    brew_drink = {job = 'CustomReaction', reaction = 'BREW_DRINK_FROM_PLANT'},
    brew_drink_from_fruit = {job = 'CustomReaction', reaction = 'BREW_DRINK_FROM_PLANT_GROWTH'},
    make_mead = {job = 'CustomReaction', reaction = 'MAKE_MEAD'},
    -- meal_ingredients = how many ingredients per meal (DF's easy / fine / lavish)
    prepare_easy_meal = {job = 'PrepareMeal', meal_ingredients = 2},
    prepare_fine_meal = {job = 'PrepareMeal', meal_ingredients = 3},
    prepare_lavish_meal = {job = 'PrepareMeal', meal_ingredients = 4},
    mill_plants = {job = 'MillPlants'},
    process_plants = {job = 'ProcessPlants'},
    process_plants_barrel = {job = 'ProcessPlantsBarrel'},
    press_honeycomb = {job = 'CustomReaction', reaction = 'PRESS_HONEYCOMB'},
    -- industry
    make_charcoal = {job = 'MakeCharcoal'},
    make_ash = {job = 'MakeAsh'},
    make_potash = {job = 'MakePotashFromAsh'},
    make_lye = {job = 'MakeLye'},
    make_soap_from_tallow = {job = 'CustomReaction', reaction = 'MAKE_SOAP_FROM_TALLOW'},
    render_fat = {job = 'CustomReaction', reaction = 'RENDER_FAT'},
    dye_cloth = {job = 'DyeCloth'},
    spin_thread = {job = 'SpinThread', material_category = {'strand'}},
    shear_creature = {job = 'ShearCreature'},                               -- (0.104.28) the wool route
    milk_creature = {job = 'MilkCreature'},                                 -- (0.104.79) the dairy
    make_cheese = {job = 'MakeCheese'},
    stone_nest_box = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_NEST_BOX', kind = 'stone'},   -- (0.104.80)
    weave_plant_cloth = {job = 'WeaveCloth', material_category = {'plant'}},
    weave_yarn_cloth = {job = 'WeaveCloth', material_category = {'yarn'}},
    weave_silk_cloth = {job = 'WeaveCloth', material_category = {'silk'}},
    cloth_bag = {job = 'ConstructBag', material_category = {'cloth'}},
    silk_bag = {job = 'ConstructBag', material_category = {'silk'}},         -- (0.86) bags of the cloth there is
    yarn_bag = {job = 'ConstructBag', material_category = {'yarn'}},
    make_quicklime = {job = 'CustomReaction', reaction = 'MAKE_QUICKLIME'},  -- the kiln and paper chains (0.86)
    make_plaster_powder = {job = 'CustomReaction', reaction = 'MAKE_PLASTER_POWDER'},
    make_milk_of_lime = {job = 'CustomReaction', reaction = 'MAKE_MILK_OF_LIME'},
    make_parchment = {job = 'CustomReaction', reaction = 'MAKE_PARCHMENT'},
    make_quire = {job = 'CustomReaction', reaction = 'MAKE_QUIRE'},
    cloth_rope = {job = 'MakeChain', material_category = {'cloth'}},      -- a rope (a well needs one)
    metal_chain = {job = 'MakeChain', kind = 'metal'},                     -- a chain (a jail's restraint)
    metal_anvil = {job = 'ForgeAnvil', kind = 'metal'},
    traction_bench = {job = 'ConstructTractionBench'},                     -- (0.88) a table, a mechanism, a rope or chain                    -- (0.86) a new forge needs one
    -- ore to bars at the smelter, one ore stone (INORGANIC:<ORE>) a job, a
    -- charcoal or coke each (DFHack's smelting library waits for 100 coal)
    smelt_ore = {job = 'SmeltOre', kind = 'stone'},
    -- steel, in two steps at the smelter (each takes flux stone and a fuel):
    -- iron to pig iron, then pig iron and iron to two steel bars
    pig_iron = {job = 'CustomReaction', reaction = 'PIG_IRON_MAKING'},
    -- coke, the smelter's fuel, from coal (the game's own smelter reactions)
    -- (the reaction codes are looked up in the game's raws: a smelter
    -- reaction that makes coke from that stone; 0.53's guessed codes were wrong)
    coke_bituminous = {job = 'CustomReaction', reaction_find = 'COAL_BITUMINOUS'},
    coke_lignite = {job = 'CustomReaction', reaction_find = 'LIGNITE'},
    steel = {job = 'CustomReaction', reaction = 'STEEL_MAKING'},
    -- wood
    wooden_bed = {job = 'ConstructBed', material_category = {'wood'}},
    -- wooden furniture (the Materials choice "wood where it will do")
    wooden_table = {job = 'ConstructTable', material_category = {'wood'}},
    wooden_chair = {job = 'ConstructThrone', material_category = {'wood'}},
    wooden_door = {job = 'ConstructDoor', material_category = {'wood'}},
    wooden_cabinet = {job = 'ConstructCabinet', material_category = {'wood'}},
    wooden_chest = {job = 'ConstructChest', material_category = {'wood'}},
    wooden_coffin = {job = 'ConstructCoffin', material_category = {'wood'}},
    wooden_armor_stand = {job = 'ConstructArmorStand', material_category = {'wood'}},
    wooden_weapon_rack = {job = 'ConstructWeaponRack', material_category = {'wood'}},
    wooden_bookcase = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_BOOKCASE', material_category = {'wood'}},
    -- clothing shoes (not metal boots), for nobles' mandates
    leather_shoes = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_SHOES', material_category = {'leather'}},
    cloth_shoes = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_SHOES', material_category = {'cloth'}},
    cloth_socks = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_SOCKS', material_category = {'cloth'}},
    leather_low_boots = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_BOOTS_LOW', material_category = {'leather'}},
    -- (0.100) crossbow soldiers carry bolts in a quiver (DFHack's military.json order)
    leather_quiver = {job = 'MakeQuiver', material_category = {'leather'}},
    wooden_bin = {job = 'ConstructBin', material_category = {'wood'}},
    wooden_bucket = {job = 'MakeBucket', material_category = {'wood'}},
    wooden_barrel = {job = 'MakeBarrel', material_category = {'wood'}},
    wooden_cage = {job = 'MakeCage', material_category = {'wood'}},
    wooden_splint = {job = 'ConstructSplint', material_category = {'wood'}},
    wooden_crutch = {job = 'ConstructCrutch', material_category = {'wood'}},
    wooden_jug = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_JUG', material_category = {'wood'}},
    wheelbarrow = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_WHEELBARROW', material_category = {'wood'}},
    -- stone (any stone, or a named one)
    stone_blocks = {job = 'ConstructBlocks', kind = 'stone'},
    stone_crafts = {job = 'MakeCrafts', kind = 'stone'},      -- trade goods (any rock crafts)
    -- (0.104.95) crafts of a precious metal at the forge (a craft's value is mostly its material)
    metal_crafts = {job = 'MakeCrafts', kind = 'metal'},
    -- (0.104.95) glass: bags of sand filled at a glass furnace (a hauler, from a
    -- sand zone), then green glass goods made from them there with fuel
    -- (DFHack's own data/orders/glassstock.json: the job and GLASS_GREEN)
    collect_sand = {job = 'CollectSand'},
    glass_crafts = {job = 'MakeCrafts', material = 'GLASS_GREEN'},
    glass_blocks = {job = 'ConstructBlocks', material = 'GLASS_GREEN'},
    glass_table = {job = 'ConstructTable', material = 'GLASS_GREEN'},
    glass_chair = {job = 'ConstructThrone', material = 'GLASS_GREEN'},
    glass_door = {job = 'ConstructDoor', material = 'GLASS_GREEN'},
    glass_cabinet = {job = 'ConstructCabinet', material = 'GLASS_GREEN'},
    glass_chest = {job = 'ConstructChest', material = 'GLASS_GREEN'},
    glass_statue = {job = 'ConstructStatue', material = 'GLASS_GREEN'},
    glass_window = {job = 'MakeWindow', material = 'GLASS_GREEN'},
    -- (0.103.10) jewellery a dwarf wears: Be extravagant is met by wearing an
    -- item with a quality modifier (DF wiki, Needs), and a worn one is owned
    stone_amulet = {job = 'MakeAmulet', kind = 'stone'},
    stone_bracelet = {job = 'MakeBracelet', kind = 'stone'},
    stone_ring = {job = 'MakeRing', kind = 'stone'},
    stone_earring = {job = 'MakeEarring', kind = 'stone'},
    stone_mugs = {job = 'MakeGoblet', kind = 'stone'},        -- mugs for the tavern
    -- (0.104.4) wooden goblets ("cups", DF wiki) at the craftsdwarf's, when there's no stone
    wooden_cups = {job = 'MakeGoblet', material_category = {'wood'}},
    -- (0.104.122) wooden crafts (figurines, rings, amulets... the craftsdwarf's
    -- pick) for the dwarves who want something to own when stone is short
    wood_crafts = {job = 'MakeCrafts', material_category = {'wood'}},
    stone_table = {job = 'ConstructTable', kind = 'stone'},
    stone_chair = {job = 'ConstructThrone', kind = 'stone'},
    stone_door = {job = 'ConstructDoor', kind = 'stone'},
    stone_cabinet = {job = 'ConstructCabinet', kind = 'stone'},
    stone_chest = {job = 'ConstructChest', kind = 'stone'},
    stone_coffin = {job = 'ConstructCoffin', kind = 'stone'},
    stone_statue = {job = 'ConstructStatue', kind = 'stone'},
    stone_slab = {job = 'ConstructSlab', kind = 'stone'},
    stone_armor_stand = {job = 'ConstructArmorStand', kind = 'stone'},
    stone_weapon_rack = {job = 'ConstructWeaponRack', kind = 'stone'},
    -- furniture in metal, at the forge (silver, gold and other metals the
    -- soldiers' gear doesn't need: brain/planner.py picks the metal)
    metal_table = {job = 'ConstructTable', kind = 'metal'},
    metal_chair = {job = 'ConstructThrone', kind = 'metal'},
    metal_door = {job = 'ConstructDoor', kind = 'metal'},
    metal_cabinet = {job = 'ConstructCabinet', kind = 'metal'},
    metal_chest = {job = 'ConstructChest', kind = 'metal'},
    metal_coffin = {job = 'ConstructCoffin', kind = 'metal'},
    metal_armor_stand = {job = 'ConstructArmorStand', kind = 'metal'},
    metal_weapon_rack = {job = 'ConstructWeaponRack', kind = 'metal'},
    stone_altar = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_ALTAR', kind = 'stone'},
    stone_bookcase = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_BOOKCASE', kind = 'stone'},
    stone_pedestal = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_PEDESTAL', kind = 'stone'},
    -- a "rock pot": food and drink storage made by a craftsdwarf, no wood needed
    stone_large_pot = {job = 'MakeTool', item_subtype = 'ITEM_TOOL_LARGE_POT', kind = 'stone'},
    mechanisms = {job = 'ConstructMechanisms', kind = 'stone'},
    -- (0.92.1) the cistern's floodgate, at the mason's
    stone_floodgate = {job = 'ConstructFloodgate', kind = 'stone'},
    stone_hatch_cover = {job = 'ConstructHatchCover', kind = 'stone'},      -- (0.104.105) a hatch over a stair needs one
    -- soldiers' gear, in a named weapon-grade metal (steel, iron, bronze...)
    metal_battle_axe = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_AXE_BATTLE', kind = 'metal'},
    metal_pick = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_PICK', kind = 'metal'},   -- (0.99.4) more miners
    -- crafts set with cut gems at the jeweller's (far more valuable to sell)
    encrust_goods = {job = 'EncrustWithGems', item_category = {'finished_goods'}, kind = 'gem'},
    cut_gems = {job = 'CutGems', kind = 'gem'},                    -- (0.104.84) when there is no autogems
    -- a crossbow squad: wooden crossbows and bolts at the bowyer's, metal bolts at the forge
    wooden_crossbow = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_CROSSBOW', material_category = {'wood'}},
    wooden_bolts = {job = 'MakeAmmo', item_subtype = 'ITEM_AMMO_BOLTS', material_category = {'wood'}},
    metal_bolts = {job = 'MakeAmmo', item_subtype = 'ITEM_AMMO_BOLTS', kind = 'metal'},
    metal_spear = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_SPEAR', kind = 'metal'},
    metal_mace = {job = 'MakeWeapon', item_subtype = 'ITEM_WEAPON_MACE', kind = 'metal'},
    metal_mail_shirt = {job = 'MakeArmor', item_subtype = 'ITEM_ARMOR_MAIL_SHIRT', kind = 'metal'},
    metal_breastplate = {job = 'MakeArmor', item_subtype = 'ITEM_ARMOR_BREASTPLATE', kind = 'metal'},
    metal_helm = {job = 'MakeHelm', item_subtype = 'ITEM_HELM_HELM', kind = 'metal'},
    metal_greaves = {job = 'MakePants', item_subtype = 'ITEM_PANTS_GREAVES', kind = 'metal'},
    metal_gauntlets = {job = 'MakeGloves', item_subtype = 'ITEM_GLOVES_GAUNTLETS', kind = 'metal'},
    metal_high_boots = {job = 'MakeShoes', item_subtype = 'ITEM_SHOES_BOOTS', kind = 'metal'},
    metal_shield = {job = 'MakeShield', item_subtype = 'ITEM_SHIELD_SHIELD', kind = 'metal'},
}

local function reject(reason)
    return {ok = false, rejected = true, error = reason}
end

-- Which plugins are on, from DFHack's own `enable` listing (the same way the
-- DFHack control panel reads it). Works for plugins without a Lua module too.
local function enabled_map()
    local out = {}
    local text = dfhack.run_command_silent('enable') or ''
    for line in text:gmatch('[^\n]+') do
        local name, state = line:match('^%s*(%S+):%s+(%S+)')
        if name then out[name] = (state == 'on') end
    end
    return out
end

function plugin_enabled(name, map)
    map = map or enabled_map()
    if map[name] ~= nil then return map[name] end
    local ok, mod = pcall(require, 'plugins.' .. name)
    if ok and type(mod) == 'table' and mod.isEnabled then
        return mod.isEnabled()
    end
    return nil -- state unknown
end

local function sorted_keys(t)
    local out = {}
    for k in pairs(t) do table.insert(out, k) end
    table.sort(out)
    return out
end

local function whole_number(v)
    return math.tointeger(tonumber(v))
end

-- Manager orders the AI created, stored in the fort's save, so the AI can
-- only ever cancel its own orders and never the player's.
local function ai_orders()
    local data = dfhack.persistent.getSiteData(AI_ORDERS_KEY, {ids = {}})
    data.ids = type(data.ids) == 'table' and data.ids or {}
    return data
end

local function save_ai_orders(data)
    -- Forget orders DF has already finished and removed.
    local live = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do live[tostring(o.id)] = true end
    for id in pairs(data.ids) do
        if not live[id] then data.ids[id] = nil end
    end
    return pcall(dfhack.persistent.saveSiteData, AI_ORDERS_KEY, data)
end

-- Which of our recipes an existing manager order corresponds to (best
-- effort), so the planner can count what's already queued.
-- (0.101.8) stone, gem and metal recipes share a job: tell them apart by the
-- order's material (a stone door was read back as metal_door: the AI's
-- report then said it had ordered metal furniture in a fort with no bars)
local function order_kind(order)
    if order.mat_type ~= 0 then return nil end
    if order.mat_index == -1 then return 'stone' end
    local ok, info = pcall(dfhack.matinfo.decode, order.mat_type, order.mat_index)
    if not ok or not info then return nil end
    local f = info.material.flags
    return f.IS_METAL and 'metal' or f.IS_GEM and 'gem' or f.IS_STONE and 'stone' or nil
end

-- (0.104.119) a recipe naming a material (green glass) is only its own
-- orders: rock crafts were read as glass_crafts (pairs() order decided)
local MAT_CACHE = {}
function material_matches(r, order)
    if not r.material then return true end
    local mi = MAT_CACHE[r.material]
    if mi == nil then
        local ok, m = pcall(dfhack.matinfo.find, r.material)
        mi = ok and m or false
        MAT_CACHE[r.material] = mi
    end
    if not mi then return false end
    return order.mat_type == mi.type and (mi.index == -1 or order.mat_index == mi.index)
end

local function recipe_of(order)
    local job = df.job_type[order.job_type]
    local kind = order_kind(order)
    local subtype_token = nil
    if order.item_subtype >= 0 then
        -- DF usually leaves item_type NONE on orders; the job type implies it.
        local it = order.item_type
        if it == df.item_type.NONE then it = df.job_type.attrs[order.job_type].item end
        local def = dfhack.items.getSubtypeDef(it, order.item_subtype)
        subtype_token = def and def.id or nil
    end
    for name, r in pairs(ORDER_RECIPES) do
        -- (a recipe whose reaction is looked up in the raws, like coke: 0.54
        -- couldn't recognise its own coke orders and placed one every 2 days)
        local reaction = r.reaction or (r.reaction_find and coke_reaction(r.reaction_find)) or ''
        if r.job == job
                and reaction == order.reaction_name
                and (not r.meal_ingredients or r.meal_ingredients == order.mat_type)
                and (not r.item_subtype or r.item_subtype == subtype_token)
                and (not (r.kind == 'stone' or r.kind == 'metal' or r.kind == 'gem') or r.kind == kind)
                and material_matches(r, order) then
            local cats_ok = true
            for _, cat in ipairs(r.material_category or {}) do
                if not order.material_category[cat] then cats_ok = false end
            end
            if cats_ok then return name end
        end
    end
    return nil
end

-- (0.104.13) The jobs each AI order has made, by the order's id: how many,
-- how many suspended, how many a dwarf is on. Enxah's bucket order sat 28
-- days at a time, cancelled as stuck 30 times, with the reason never seen;
-- a suspended job is one the order never gets back to by itself.
function order_jobs(ids)
    local by = {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and ids[tostring(oid)] then
                local e = by[oid] or {n = 0, suspended = 0, working = 0}
                e.n = e.n + 1
                if j.flags.suspend then e.suspended = e.suspended + 1 end
                if dfhack.job.getWorker(j) then e.working = e.working + 1 end
                -- (0.104.73) where an unworked job waits, and the labour and
                -- skill it calls for (Enxah: 4 instrument orders, each one
                -- job nobody took)
                if not e.at and not dfhack.job.getWorker(j) then
                    pcall(function()
                        local b = dfhack.job.getHolder(j)
                        if b then
                            local bt = df.building_type[b:getType()] or '?'
                            local okw, wt = pcall(function() return df.workshop_type[b.type] end)
                            e.at = (okw and wt) and (bt .. ':' .. wt) or bt
                            e.at_id = b.id
                            -- (0.104.125) the workshop's worker profile: Teacheroar's
                            -- rope and cloth jobs waited 41 days with 175 dwarves
                            -- holding the labour (who may work there?)
                            pcall(function()
                                local pr = b.profile
                                local n = #pr.permitted_workers
                                if n > 0 then e.permitted = n end
                                if (pr.min_level or 0) > 0 then e.min_skill = pr.min_level end
                                if pr.max_level and pr.max_level < 3000 then e.max_skill = pr.max_level end
                            end)
                        end
                        local okl, lab = pcall(dfhack.job.getSpecificLabor, j)
                        if okl and lab and lab ~= -1 then e.labor = df.unit_labor[lab] end
                        local okk, sk = pcall(dfhack.job.getSkill, j)
                        if okk and sk and sk ~= -1 then e.skill = df.job_skill[sk] end
                    end)
                end
                by[oid] = e
            end
        end
        link = link.next
    end
    return by
end

function get_orders()
    local ai_ids = ai_orders().ids
    local okj, jobs_of = pcall(order_jobs, ai_ids)
    if not okj then jobs_of = {} end
    local out = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do
        table.insert(out, {
            id = o.id,
            recipe = recipe_of(o),
            job = df.job_type[o.job_type] or tostring(o.job_type),
            reaction = o.reaction_name ~= '' and o.reaction_name or nil,
            amount_left = o.amount_left,
            amount_total = o.amount_total,
            repeats = df.workquota_frequency_type[o.frequency] ~= 'OneTime',
            by_ai = ai_ids[tostring(o.id)] == true,
            jobs = jobs_of[o.id],
        })
        -- (0.101.2) the game's own view of the order: approved by the manager,
        -- active, tied to one workshop, conditions (a fresh fort's orders never
        -- moved: this says why)
        local e = out[#out]
        pcall(function()
            e.validated = o.status.validated == true
            e.active = o.status.active or nil
            -- (0.101.4) when the game next checks the order, and the fort's
            -- order-check countdown (plotinfo.manager_timer)
            if o.finished_year ~= -1 then e.next_check = {o.finished_year, o.finished_year_tick} end
            e.check_timer = df.global.plotinfo.manager_timer
            if o.workshop_id ~= -1 then e.workshop_id = o.workshop_id end
            if o.max_workshops ~= 0 then e.max_workshops = o.max_workshops end
            if #o.item_conditions > 0 then e.item_conditions = #o.item_conditions end
            if #o.order_conditions > 0 then e.order_conditions = #o.order_conditions end
        end)
    end
    return out
end

function get_tools()
    local out = {}
    local map = enabled_map()
    for name in pairs(TOOL_ALLOWLIST) do
        -- true / false, or nil when the state can't be read
        out[name] = plugin_enabled(name, map)
    end
    return out
end

-- The game's reaction that turns a stone (e.g. COAL_BITUMINOUS) into coke:
-- one whose code or name says coke and whose reagent is that stone. Its code,
-- or nil.
COKE_CACHE = COKE_CACHE or {}
function coke_reaction(stone)
    if COKE_CACHE[stone] ~= nil then return COKE_CACHE[stone] or nil end
    local ok, code = pcall(function()
        for _, r in ipairs(df.global.world.raws.reactions.reactions) do
            local text = (tostring(r.code) .. ' ' .. tostring(r.name)):upper()
            if text:find('COKE', 1, true) then
                for _, rg in ipairs(r.reagents) do
                    local ok2, mat = pcall(function()
                        return dfhack.matinfo.decode(rg.mat_type, rg.mat_index)
                    end)
                    local id = ok2 and mat and mat.inorganic and mat.inorganic.id
                    if id == stone then return r.code end
                end
                if text:find(stone:gsub('COAL_', ''), 1, true) then return r.code end
            end
        end
    end)
    code = ok and code or nil
    COKE_CACHE[stone] = code or false
    return code
end

-- Is there a reaction with this code in the game's raws?
function reaction_exists(code)
    local ok, found = pcall(function()
        for _, r in ipairs(df.global.world.raws.reactions.reactions) do
            if r.code == code then return true end
        end
        return false
    end)
    return ok and found
end

function act_work_order(a)
    local recipe = ORDER_RECIPES[a.recipe]
    if recipe and recipe.reaction_find then
        local code = coke_reaction(recipe.reaction_find)
        if not code then
            return reject(('the game has no coke reaction for %s (recipe %s)'):format(recipe.reaction_find, a.recipe))
        end
        local copy = {}
        for k, v in pairs(recipe) do if k ~= 'reaction_find' then copy[k] = v end end
        copy.reaction = code
        recipe = copy
    end
    if recipe and recipe.reaction and not reaction_exists(recipe.reaction) then
        return reject(('the game has no reaction %s (recipe %s)'):format(recipe.reaction, a.recipe))
    end
    if not recipe then
        return reject(('unknown recipe: %s (known: %s)'):format(
            tostring(a.recipe), table.concat(sorted_keys(ORDER_RECIPES), ', ')))
    end
    local amount = whole_number(a.amount)
    if not amount or amount < 1 or amount > MAX_ORDER_AMOUNT then
        return reject(('amount must be a whole number from 1 to %d'):format(MAX_ORDER_AMOUNT))
    end

    -- Built field by field from the recipe and checked values. Never pass
    -- AI-written JSON to workorder: some of its fields are run as Lua code.
    local spec = {amount_total = amount}
    for k, v in pairs(recipe) do
        if k ~= 'kind' then spec[k] = v end
    end
    if recipe.kind == 'stone' then
        spec.material = 'INORGANIC' -- any stone
        if a.material ~= nil then
            local info = type(a.material) == 'string' and a.material:match('^INORGANIC:')
                and dfhack.matinfo.find(a.material)
            if not info or not info.material.flags.IS_STONE then
                return reject('material must be a stone, written INORGANIC:<STONE>, e.g. INORGANIC:GRANITE')
            end
            spec.material = a.material
        end
    elseif recipe.kind == 'gem' then
        local info = type(a.material) == 'string' and a.material:match('^INORGANIC:')
            and dfhack.matinfo.find(a.material)
        if not info or not info.material.flags.IS_GEM then
            return reject('this recipe needs a gem, written INORGANIC:<GEM>, e.g. INORGANIC:AMETHYST')
        end
        spec.material = a.material
    elseif recipe.kind == 'metal' then
        local info = type(a.material) == 'string' and a.material:match('^INORGANIC:')
            and dfhack.matinfo.find(a.material)
        if not info or not info.material.flags.IS_METAL then
            return reject('this recipe needs a metal, written INORGANIC:<METAL>, e.g. INORGANIC:IRON')
        end
        spec.material = a.material
    elseif a.material ~= nil then
        return reject(('recipe %s does not take a material'):format(a.recipe))
    end

    local wo = reqscript('workorder')
    local orders = wo.preprocess_orders({spec})
    wo.fillin_defaults(orders)
    local all = df.global.world.manager_orders.all
    local count_before = #all
    local new_id = df.global.world.manager_orders.manager_order_next_id
    wo.create_orders(orders, true)
    if #all ~= count_before + 1 or all[#all - 1].id ~= new_id then
        return {ok = false, error = 'the game did not accept the work order'}
    end
    local data = ai_orders()
    data.ids[tostring(new_id)] = true
    local saved = save_ai_orders(data)
    return {ok = true, order_id = new_id, recipe = a.recipe, amount = amount,
            material = spec.material,
            warning = (not saved) and 'order created but not recorded; the AI cannot cancel it later' or nil}
end

-- True if DF's own screens might be holding this order right now. Deleting an
-- order that a screen points at would crash DF, so we refuse in that case.
local function order_in_use_by_ui(order)
    local ok, busy = pcall(function()
        local mi = df.global.game.main_interface
        local wo = mi.info.work_orders
        if mi.info.open and mi.info.current_mode == df.info_interface_mode_type.WORK_ORDERS then
            return true
        end
        if mi.job_details.open then return true end
        return wo.conditions.wq == order or wo.entering_wq == order
            or wo.b_entering_wq == order or mi.job_details.wq == order
            or mi.image_creator.ics.wq == order
    end)
    return (not ok) or busy -- if we can't tell, assume it's in use
end

-- Free an order the same way DFHack's `orders clear` does.
local function free_order(order)
    for _, c in ipairs(order.item_conditions) do c:delete() end
    for _, c in ipairs(order.order_conditions) do c:delete() end
    if order.items then
        for _, e in ipairs(order.items.elements) do e:delete() end
        order.items:delete()
    end
    order:delete()
end

-- (0.101.2) The manager approves ("validates") work orders in an office with
-- a chair; a new fort's office waits for a chair that needs an approved
-- order (a deadlock: two test forts never brewed, cooked or made a bed).
-- The AI's own orders that have waited are approved here, as the manager
-- would; never the player's. A working manager goes on approving the rest.
function act_approve_orders(a)
    local ids = ai_orders().ids
    local n = 0
    for _, o in ipairs(df.global.world.manager_orders.all) do
        if ids[tostring(o.id)] and not o.status.validated then
            if not a.dry_run then o.status.validated = true end
            n = n + 1
        end
    end
    if n == 0 then return reject('no unapproved orders of the AI\'s') end
    return {ok = true, approved = n, dry_run = a.dry_run or nil}
end

-- (0.104.13) The AI's own orders' jobs a workshop suspended are taken up
-- again (the player's "resume" in the workshop). Only jobs made by the AI's
-- orders: never a construction (suspendmanager's) or a player's job.
function act_unsuspend_orders(a)
    local ids = ai_orders().ids
    local want = math.tointeger(tonumber(a.order_id))
    local n, kinds = 0, {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j and j.flags.suspend then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and ids[tostring(oid)] and (not want or want == oid) then
                if not a.dry_run then j.flags.suspend = false end
                n = n + 1
                local k = df.job_type[j.job_type] or tostring(j.job_type)
                kinds[k] = (kinds[k] or 0) + 1
            end
        end
        link = link.next
    end
    if n == 0 then return reject('no suspended job of the AI\'s orders') end
    return {ok = true, unsuspended = n, kinds = kinds, dry_run = a.dry_run or nil}
end

-- (0.104.15) The fort's own dead, forbidden where they lie, unforbidden
-- so they can be carried to a free tomb (only bodies of the fort's race the
-- dwarves can walk to; never one a job holds).
function act_unforbid_dead(a)
    local race = df.global.plotinfo.race_id
    local max = math.tointeger(tonumber(a.max)) or 20
    local from
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local x, y, z = dfhack.units.getPosition(u)
        if x then from = xyz2pos(x, y, z) break end
    end
    local n = 0
    for _, it in ipairs(df.global.world.items.other.CORPSE) do
        if n >= max then break end
        local ok, r = pcall(function() return it.race end)
        if ok and r == race and it.flags.forbid and not it.flags.in_building and not it.flags.removed
                and not it.flags.in_job then
            local x, y, z = dfhack.items.getPosition(it)
            if x and from and dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z)) then
                if not a.dry_run then it.flags.forbid = false end
                n = n + 1
            end
        end
    end
    if n == 0 then return reject('no forbidden body of the fort\'s the dwarves can reach') end
    return {ok = true, unforbidden = n, dry_run = a.dry_run or nil}
end

-- (0.104.17) Automatic burial of citizens switched back on in the AI's own
-- tomb levels (each coffin a 1x1 tomb zone): Enxah's 7 free tombs all had it
-- off ("no citizens") while 104 bodies lay unburied. Never a tomb outside an
-- AI tomb level, never one set aside for one dwarf.
function act_allow_burial(a)
    local okp, data = pcall(function() return reqscript('ai-builder').load_projects() end)
    local areas = {}
    for _, p in ipairs(okp and data and data.list or {}) do
        if p.kind == 'tombs' and type(p.area) == 'table' then table.insert(areas, p.area) end
    end
    if #areas == 0 then return reject('no tomb level of the AI\'s') end
    local n = 0
    for _, z in ipairs(df.global.world.buildings.all) do
        if z:getType() == df.building_type.Civzone and z.type == df.civzone_type.Tomb then
            local mine = false
            for _, ar in ipairs(areas) do
                if z.z == ar.z and z.x1 >= ar.x1 and z.x2 <= ar.x2 and z.y1 >= ar.y1 and z.y2 <= ar.y2 then mine = true end
            end
            local okf, off = pcall(function() return z.zone_settings.tomb.flags.no_citizens end)
            local oko, owner = pcall(function() return z.assigned_unit_id end)
            if mine and okf and off and (not oko or owner == nil or owner < 0) then
                if not a.dry_run then z.zone_settings.tomb.flags.no_citizens = false end
                n = n + 1
            end
        end
    end
    if n == 0 then return reject('every AI tomb already takes citizens') end
    return {ok = true, opened = n, dry_run = a.dry_run or nil}
end

-- (0.101.4) Below 20 citizens orders need no approval, but the manager hands
-- them out only from an office with a chair; with no chair in the fort every
-- order waits forever (the Enxah fort never ran one in 3 years). One chair is
-- made the old way: a job put straight on a carpenter's (wood) or mason's
-- (stone) bench, the way a player clicks "add job" in the workshop.
function act_bootstrap_chair(a)
    local benches = {}
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        if (b.type == df.workshop_type.Carpenters or b.type == df.workshop_type.Masons)
                and b:getBuildStage() >= b:getMaxBuildStage() then
            for _, j in ipairs(b.jobs) do
                if j.job_type == df.job_type.ConstructThrone then
                    return reject('a chair job is already waiting at a workshop')
                end
            end
            table.insert(benches, b)
        end
    end
    table.sort(benches, function(x, y)   -- wood first: a carpenter's chair
        return (x.type == df.workshop_type.Carpenters and 0 or 1) < (y.type == df.workshop_type.Carpenters and 0 or 1)
    end)
    local b = benches[1]
    if not b then return reject('no finished carpenter\'s or mason\'s workshop') end
    if not (dfhack.job.createLinked and dfhack.job.assignToWorkshop) then
        return reject('this DFHack has no workshop job API')
    end
    local wood = b.type == df.workshop_type.Carpenters
    if a.dry_run then return {ok = true, dry_run = true, workshop = b.id, wood = wood} end
    local job = dfhack.job.createLinked()
    job.job_type = df.job_type.ConstructThrone
    job.mat_type = -1
    local ji = df.job_item:new()
    ji.mat_type = -1
    ji.mat_index = -1
    ji.quantity = 1
    if wood then
        job.material_category.wood = true
        ji.item_type = df.item_type.WOOD
        ji.vector_id = df.job_item_vector_id.WOOD
    else
        ji.item_type = df.item_type.BOULDER
        ji.vector_id = df.job_item_vector_id.BOULDER
        ji.flags3.hard = true
    end
    job.job_items.elements:insert('#', ji)
    dfhack.job.assignToWorkshop(job, b)
    return {ok = true, workshop = b.id, job_id = job.id, material = wood and 'wood' or 'stone'}
end

-- (0.104.21) Jobs put straight on a workshop's bench when the AI's order for
-- them makes none (Enxah: a 29-coffin order took no job at the masons in
-- two game months while a tomb level waited and 106 dead lay unburied).
-- Only coffins so far: stone at a mason's, or wood at a carpenter's.
-- (0.104.32) and blank slabs: autoslab's engrave jobs waiting for one filled
-- the masons' job list (10 jobs: 7 of them "needs unengraved slab"), so no
-- slab and too few coffins could ever reach the bench (13 ghosts, 90 dead)
BENCH_JOBS = {
    coffin = {job = 'ConstructCoffin', shops = {Masons = 'stone', Carpenters = 'wood'}},
    slab = {job = 'ConstructSlab', shops = {Masons = 'stone'}},
}
-- jobs that may be lifted off a full bench to make room (make_room): only
-- unworked ones of orders that are not the AI's, waiting on what the bench
-- jobs make; the order makes them again later
BENCH_LIFT = {EngraveSlab = true}
BENCH_MAX = 5

-- (0.104.34) Jobs at a workshop whose work order no longer exists: the AI
-- cancels an order it finds stuck, and DF leaves the order's jobs on the
-- bench, unworked for good (Enxah: 14 jewellery and craft jobs on three
-- craftsdwarf's benches, 2 engrave jobs on the masons'). Only unworked jobs
-- with an order id that is gone; never a player's job (no order) or a
-- construction. count_only: just count them.
function orphan_jobs(count_only, max)
    local live = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do live[o.id] = true end
    local found, kinds = {}, {}
    local link = df.global.world.jobs.list.next
    while link do
        local j = link.item
        if j then
            local ok, oid = pcall(function() return j.order_id end)
            if ok and oid and oid ~= -1 and not live[oid] and not dfhack.job.getWorker(j)
                    and dfhack.job.getHolder and dfhack.job.getHolder(j) then
                table.insert(found, j)
                local k = df.job_type[j.job_type] or tostring(j.job_type)
                kinds[k] = (kinds[k] or 0) + 1
            end
        end
        link = link.next
    end
    if count_only then return #found end
    local n = 0
    for i = 1, math.min(#found, max or 30) do
        if pcall(dfhack.job.removeJob, found[i]) then n = n + 1 end
    end
    return n, kinds, #found
end

function act_clear_orphan_jobs(a)
    if a.dry_run then
        local n = orphan_jobs(true)
        if n == 0 then return reject('no job without its order') end
        return {ok = true, dry_run = true, orphans = n}
    end
    local n, kinds, found = orphan_jobs(false, math.tointeger(tonumber(a.max)) or 30)
    if found == 0 then return reject('no job without its order') end
    if n == 0 then return {ok = false, error = 'the game would not remove the jobs'} end
    return {ok = true, removed = n, found = found, kinds = kinds}
end

-- (0.104.23) A workshop's limit of jobs taken from work orders ("max general
-- orders"), raised when its slots are all held by jobs that can't go on
-- (Enxah's masons: 5 engrave-memorial jobs of autoslab's, "needs unengraved
-- slab", held all 5 for 250 days, so the AI's slab, coffin and block orders
-- never reached the bench: the slabs those jobs wait for included).
function act_order_slots(a)
    local id = math.tointeger(tonumber(a.workshop_id))
    local n = math.tointeger(tonumber(a.max))
    if not id or not n or n < 1 or n > 15 then return reject('workshop_id and max 1-15 needed') end
    local b = df.building.find(id)
    if not b or not df.building_workshopst:is_instance(b) then return reject('no such workshop') end
    local old = b.profile.max_general_orders
    if n <= old then return reject(('the workshop already takes %d'):format(old)) end
    if not a.dry_run then b.profile.max_general_orders = n end
    return {ok = true, workshop = id, before = old, max = n, dry_run = a.dry_run or nil}
end

function act_bench_jobs(a)
    local spec = BENCH_JOBS[tostring(a.kind)]
    if not spec then return reject('kind must be one of: coffin, slab') end
    local n = math.tointeger(tonumber(a.count)) or 1
    if n < 1 or n > BENCH_MAX then return reject(('count must be 1-%d'):format(BENCH_MAX)) end
    if not (dfhack.job.createLinked and dfhack.job.assignToWorkshop) then
        return reject('this DFHack has no workshop job API')
    end
    local want = a.material == 'wood' and 'wood' or a.material == 'stone' and 'stone' or nil
    local jt = df.job_type[spec.job]
    local bench, have = nil, 0
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        local mat = spec.shops[df.workshop_type[b.type]]
        if mat and (not want or want == mat) and b:getBuildStage() >= b:getMaxBuildStage() then
            local waiting = 0
            for _, j in ipairs(b.jobs) do if j.job_type == jt then waiting = waiting + 1 end end
            have = have + waiting
            if not bench or (#b.jobs < #bench.jobs) then bench = b end
        end
    end
    if not bench then return reject('no finished workshop for ' .. tostring(a.kind)) end
    if have >= BENCH_MAX then return reject(('%d such jobs already wait at the benches'):format(have)) end
    n = math.min(n, BENCH_MAX - have)
    local lifted = 0
    if 10 - #bench.jobs < n and a.make_room then
        local mine = ai_orders().ids
        local lift = {}
        for _, j in ipairs(bench.jobs) do
            if BENCH_LIFT[df.job_type[j.job_type]] and not dfhack.job.getWorker(j)
                    and not (j.order_id ~= -1 and mine[tostring(j.order_id)]) then
                table.insert(lift, j)
            end
        end
        local want_free = n - (10 - #bench.jobs)
        if not a.dry_run then
            for i = 1, math.min(want_free, #lift) do
                if pcall(dfhack.job.removeJob, lift[i]) then lifted = lifted + 1 end
            end
        else
            lifted = math.min(want_free, #lift)
        end
    end
    n = math.min(n, 10 - #bench.jobs + (a.dry_run and lifted or 0))
    if n < 1 then return reject('the workshop\'s job list is full') end
    local wood = spec.shops[df.workshop_type[bench.type]] == 'wood'
    if a.dry_run then return {ok = true, dry_run = true, workshop = bench.id, count = n, lifted = lifted, material = wood and 'wood' or 'stone'} end
    for _ = 1, n do
        local job = dfhack.job.createLinked()
        job.job_type = jt
        job.mat_type = -1
        local ji = df.job_item:new()
        ji.mat_type = -1
        ji.mat_index = -1
        ji.quantity = 1
        if wood then
            job.material_category.wood = true
            ji.item_type = df.item_type.WOOD
            ji.vector_id = df.job_item_vector_id.WOOD
        else
            ji.item_type = df.item_type.BOULDER
            ji.vector_id = df.job_item_vector_id.BOULDER
            ji.flags3.hard = true
        end
        job.job_items.elements:insert('#', ji)
        dfhack.job.assignToWorkshop(job, bench)
    end
    return {ok = true, workshop = bench.id, count = n, lifted = lifted > 0 and lifted or nil,
            material = wood and 'wood' or 'stone'}
end

function act_cancel_work_order(a)
    local id = whole_number(a.order_id)
    if not id then return reject('order_id must be a whole number') end
    local data = ai_orders()
    if not data.ids[tostring(id)] then
        return reject(('order %d was not created by the AI (or has finished); the AI only cancels its own orders'):format(id))
    end
    local all = df.global.world.manager_orders.all
    for i = #all - 1, 0, -1 do
        local order = all[i]
        if order.id == id then
            if order_in_use_by_ui(order) then
                return reject('the work orders screen is open; try again when it is closed')
            end
            -- Remove "after order X completes" conditions pointing at it.
            for _, other in ipairs(all) do
                local conds = other.order_conditions
                for j = #conds - 1, 0, -1 do
                    if conds[j].order_id == id then
                        local c = conds[j]
                        conds:erase(j)
                        c:delete()
                    end
                end
            end
            all:erase(i)
            free_order(order)
            data.ids[tostring(id)] = nil
            save_ai_orders(data)
            -- (0.104.34) its jobs that nobody works go with it (DF leaves them)
            local gone = 0
            pcall(function() gone = orphan_jobs(false, 30) end)
            return {ok = true, order_id = id, cancelled = true, jobs_removed = gone > 0 and gone or nil}
        end
    end
    data.ids[tostring(id)] = nil
    save_ai_orders(data)
    return {ok = true, order_id = id, cancelled = false,
            note = 'order was already finished or removed'}
end

function act_tool(a)
    if not TOOL_ALLOWLIST[a.name] then
        return reject(('tool not allowed: %s (allowed: %s)'):format(
            tostring(a.name), table.concat(sorted_keys(TOOL_ALLOWLIST), ', ')))
    end
    if type(a.enabled) ~= 'boolean' then
        return reject('enabled must be true or false')
    end
    local output, rv = dfhack.run_command_silent(a.enabled and 'enable' or 'disable', a.name)
    if rv ~= CR_OK then
        return {ok = false, error = ('%s %s failed: %s'):format(
            a.enabled and 'enable' or 'disable', a.name, (output or ''):gsub('%s+$', ''))}
    end
    return {ok = true, name = a.name, enabled = plugin_enabled(a.name)}
end

function act_civ_alert(a)
    if type(a.on) ~= 'boolean' then return reject('on must be true or false') end
    local civ = reqscript('gui/civ-alert')
    if a.on then
        if df.global.plotinfo.alerts.civ_alert_idx ~= 0 then
            -- already_on: the alert is someone else's (usually the player's)
            return {ok = true, on = true, already_on = true, note = 'civilian alert was already on'}
        end
        if not civ.can_sound_alarm() then
            return reject('no civilian alert burrow is set up yet; the player must choose one in the civ-alert settings first')
        end
        civ.sound_alarm()
    else
        civ.clear_alarm()
    end
    return {ok = true, on = df.global.plotinfo.alerts.civ_alert_idx ~= 0}
end

---------------------------------------------------------------------------
-- Building projects (lua/ai-builder.lua). The AI names a level kind and a
-- size; the builder decides where and checks every tile. See docs/building.md.
---------------------------------------------------------------------------

local function int_in(v, lo, hi)
    local n = math.tointeger(tonumber(v))
    if n == nil or n < lo or n > hi then return nil end
    return n
end

local function string_list(v, allowed, max)
    if type(v) ~= 'table' then return nil end
    local out, seen = {}, {}
    for _, name in ipairs(v) do
        if type(name) ~= 'string' or not allowed[name] then return nil end
        if not seen[name] then table.insert(out, name); seen[name] = true end
    end
    if #out == 0 or #out > max then return nil end
    return out
end

-- The fort's building style (from its culture); every field is optional.
-- Returns style (or nil when none was given), error.
local function parse_style(st)
    if st == nil then return nil end
    if type(st) ~= 'table' then return nil, 'style must be an object' end
    local hall = st.hall or 'plain'
    if hall ~= 'plain' and hall ~= 'rounded' and hall ~= 'pillared' then
        return nil, 'style.hall must be plain, rounded or pillared'
    end
    local smooth, statues = int_in(st.smooth or 0, 0, 3), int_in(st.statues or 0, 0, 4)
    if not smooth or not statues then
        return nil, 'style.smooth must be 0-3 and style.statues 0-4'
    end
    if st.entry_door ~= nil and type(st.entry_door) ~= 'boolean' then
        return nil, 'style.entry_door must be true or false'
    end
    local spacing = int_in(st.spacing or 0, -200, 200)
    if not spacing then return nil, 'style.spacing must be -200 to 200' end
    -- optional: how the level is turned (0-3) and the pillar rhythm (3-6 tiles)
    local orient, rhythm
    if st.orient ~= nil then
        orient = int_in(st.orient, 0, 3)
        if not orient then return nil, 'style.orient must be 0-3' end
    end
    if st.rhythm ~= nil then
        rhythm = int_in(st.rhythm, 3, 6)
        if not rhythm then return nil, 'style.rhythm must be 3-6' end
    end
    return {hall = hall, smooth = smooth, statues = statues, entry_door = st.entry_door == true,
            spacing = spacing, orient = orient, rhythm = rhythm}
end

-- The overseer's master plan for a new level: a hint where to put it (the
-- builder tries it first, then searches as usual). Every field but the
-- elevation band is optional. Returns plan (or nil when none was given), error.
local PLAN_DIRS = {north = true, south = true, east = true, west = true}
function parse_plan(pl)
    if pl == nil then return nil end
    if type(pl) ~= 'table' then return nil, 'plan must be an object' end
    local out = {}
    if pl.spine ~= nil then
        local sp = type(pl.spine) == 'table' and pl.spine or {}
        local x, y = int_in(sp.x, 0, 999), int_in(sp.y, 0, 999)
        if not x or not y then return nil, 'plan.spine needs x and y, 0-999' end
        out.spine = {x = x, y = y}
    end
    local lo, hi = int_in(pl.elev_lo, -400, 400), int_in(pl.elev_hi, -400, 400)
    if not lo or not hi or lo > hi then
        return nil, 'plan needs elev_lo and elev_hi, -400 to 400, elev_lo <= elev_hi'
    end
    out.elev_lo, out.elev_hi = lo, hi
    if pl.elev_target ~= nil then
        out.elev_target = int_in(pl.elev_target, -400, 400)
        if not out.elev_target then return nil, 'plan.elev_target must be -400 to 400' end
    else
        out.elev_target = lo + (hi - lo) // 2       -- the middle of the band
    end
    if pl.dirs ~= nil then
        if type(pl.dirs) ~= 'table' then return nil, 'plan.dirs must be a list' end
        local dirs, seen, n = {}, {}, 0
        for _ in pairs(pl.dirs) do n = n + 1 end
        for _, d in ipairs(pl.dirs) do
            if type(d) ~= 'string' or not PLAN_DIRS[d] or seen[d] then
                return nil, 'plan.dirs must be distinct names from north, south, east, west'
            end
            seen[d] = true
            table.insert(dirs, d)
        end
        if #dirs == 0 or #dirs > 4 or n ~= #dirs then
            return nil, 'plan.dirs needs 1-4 of north, south, east, west'
        end
        out.dirs = dirs
    end
    if pl.district ~= nil then
        local d = pl.district
        if type(d) ~= 'string' or #d > 40 or not d:match("^[A-Za-z0-9' %-]+$") then
            return nil, 'plan.district must be up to 40 letters, digits, spaces, apostrophes or hyphens'
        end
        out.district = d
    end
    -- corridor grammar (all optional): width, shape, doors
    if pl.avenue ~= nil then
        out.avenue = int_in(pl.avenue, 1, 3)
        if not out.avenue then return nil, 'plan.avenue must be 1-3' end
    end
    if pl.corridors ~= nil then
        if pl.corridors ~= 'straight' and pl.corridors ~= 'dog-leg' then
            return nil, 'plan.corridors must be "straight" or "dog-leg"'
        end
        out.corridors = pl.corridors
    end
    if pl.doors ~= nil then
        if pl.doors ~= 'open' and pl.doors ~= 'doored' and pl.doors ~= 'fortified' then
            return nil, 'plan.doors must be "open", "doored" or "fortified"'
        end
        out.doors = pl.doors
    end
    return out
end

function act_start_project(a)
    local layouts = reqscript('ai-layouts')
    local p = {kind = a.kind}
    if a.kind == 'bedrooms' then
        p.rooms = int_in(a.rooms, 1, 32)
        p.room_size = int_in(a.room_size or 3, 2, 4)
        if not p.rooms or not p.room_size then
            return reject('bedrooms needs rooms 1-32 and room_size 2-4')
        end
        -- (0.103.11) one hall of 4-20 beds and a dormitory zone (Communal)
        if a.dormitory == true then
            p.dormitory = true
            p.rooms = math.max(4, math.min(20, p.rooms))
        end
    elseif a.kind == 'suites' then
        p.suites = int_in(a.suites, 1, 8)
        if not p.suites then return reject('suites needs suites 1-8') end
    elseif a.kind == 'jail' then
        p.cells = int_in(a.cells, 1, 8)
        if not p.cells then return reject('jail needs cells 1-8') end
    elseif a.kind == 'dining' then
        p.tables = int_in(a.tables, 4, 90)
        if not p.tables then return reject('dining needs tables 4-90') end
    elseif a.kind == 'storage' then
        p.piles = string_list(a.piles, layouts.STOCKPILES, 12)
        p.room_size = int_in(a.room_size or 7, 5, 11)
        if not p.piles or not p.room_size then
            return reject('storage needs piles (1-12 of: ' ..
                table.concat(sorted_keys(layouts.STOCKPILES), ', ') .. ') and room_size 5-11')
        end
    elseif a.kind == 'temple' then
        if a.size ~= 'shrine' and a.size ~= 'grand' then
            return reject('temple needs size "shrine" or "grand"')
        end
        p.size = a.size
        -- (0.89) dedicated: to a deity (a figure) or a religion, or a guildhall
        if a.deity_hf ~= nil then
            p.deity_hf = whole_number(a.deity_hf)
            if not p.deity_hf or not df.historical_figure.find(p.deity_hf) then return reject('no such deity') end
        end
        if a.religion ~= nil then
            p.religion = whole_number(a.religion)
            if not p.religion or not df.historical_entity.find(p.religion) then return reject('no such religion') end
        end
        if a.profession ~= nil then
            if type(a.profession) ~= 'string' or df.profession[a.profession] == nil or not a.profession:match('^[%u_]+$') then
                return reject('profession must be one of DF\'s professions, e.g. MINER')
            end
            p.profession = a.profession
        end
    elseif a.kind == 'hospital' or a.kind == 'barracks' then
        p.beds = int_in(a.beds, 4, 20)
        if not p.beds then return reject(a.kind .. ' needs beds 4-20') end
    elseif a.kind == 'archery' then
        p.lanes = int_in(a.lanes or 2, 1, 3)
        p.length = int_in(a.length or 12, 8, 16)
        if not p.lanes or not p.length then return reject('archery needs lanes 1-3 and length 8-16') end
    elseif a.kind == 'tombs' then
        p.coffins = int_in(a.coffins, 4, 30)
        if not p.coffins then return reject('tombs needs coffins 4-30') end
    elseif a.kind == 'tavern' then
        p.tables = int_in(a.tables, 4, 20)
        if not p.tables then return reject('tavern needs tables 4-20') end
    elseif a.kind == 'library' then
        p.bookcases = int_in(a.bookcases, 4, 20)
        if not p.bookcases then return reject('library needs bookcases 4-20') end
    elseif a.kind == 'memorial' then
        if type(a.name) ~= 'string' or not a.name:match("^[A-Za-z' ]+$") or #a.name > 40 then
            return reject('memorial needs a name: letters, spaces and apostrophes, up to 40')
        end
        p.name = a.name
    elseif a.kind == 'garden' then
        if type(a.name) ~= 'string' or not a.name:match("^[A-Za-z' ]+$") or #a.name > 40 then
            return reject('garden needs a name: letters, spaces and apostrophes, up to 40')
        end
        p.name = a.name
    elseif a.kind == 'workshops' then
        p.shops = string_list(a.shops, layouts.WORKSHOPS, 12)
        if not p.shops then
            return reject('workshops needs shops (1-12 of: ' ..
                table.concat(sorted_keys(layouts.WORKSHOPS), ', ') .. ')')
        end
    else
        return reject(('unknown level kind: %s (known: %s)'):format(
            tostring(a.kind), table.concat(layouts.KINDS, ', ')))
    end
    local style, err = parse_style(a.style)
    if err then return reject(err) end
    p.style = style
    local plan, perr = parse_plan(a.plan)
    if perr then return reject(perr) end
    p.plan = plan
    p.urgent = a.urgent == true or nil       -- a well's or a mood's workshop: one slot more
    return reqscript('ai-builder').start_project(p, get_date(), a.dry_run == true)
end

-- Farm plots: on soil or muddy floor the fort already has, else (dig = true)
-- a new farm level dug in a soil layer. The AI says how many tiles; the
-- builder finds where. See docs/building.md.
function act_farm_plots(a)
    local tiles = int_in(a.tiles, 4, 400)
    if not tiles then return reject('farm_plots needs tiles 4-400') end
    if a.dig ~= nil and type(a.dig) ~= 'boolean' then return reject('dig must be true or false') end
    local style, err = parse_style(a.style)
    if err then return reject(err) end
    if a.outside ~= nil and type(a.outside) ~= 'boolean' then return reject('outside must be true or false') end
    -- (0.99.10) `outside` reaches the builder: it was dropped here, so the
    -- outdoor search never ran (region2's "no free soil" seven times over)
    return reqscript('ai-builder').farm_plots({tiles = tiles, dig = a.dig == true, outside = a.outside == true,
                                               style = style}, get_date(), a.dry_run == true)
end

-- A well: the builder finds a free floor inside the fort with a straight
-- drop to clean water, channels it, and places the well once it's dug.
function act_place_well(a)
    return reqscript('ai-builder').place_well({inside_only = a.inside_only == true, cavern = a.cavern == true,
                                               urgent = a.urgent == true},
                                              get_date(), a.dry_run == true)
end

local function project_id(a)
    return math.tointeger(tonumber(a.project_id))
end

function act_furnish_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').furnish_project(id, plugin_enabled('buildingplan') == true, a.stalled == true)
end

-- (0.104.110) a stalled level's dig jobs let go of their workers
function act_free_dig_jobs(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').free_dig_jobs(id)
end

-- (0.104.128) an open level's tiles left to dig raised to a higher priority
function act_prioritize_dig(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').prioritize_project(id, a.priority, a.dry_run == true)
end

function act_finish_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').finish_project(id, a.decor_only == true)
end

-- The fort's culture, written by the overseer so the panel's Culture page can
-- show it (and so it travels with the save). Display only: nothing in the
-- game reads it.
CULTURE_KEY = 'ai-overseer/culture'
local CULTURE_ENUMS = {
    hall = {plain = true, rounded = true, pillared = true},
    palette = {any = true, dark = true, light = true, warm = true, cool = true, precious = true,
               purpose = true, wood = true},
    temple = {none = true, shrine = true, grand = true},
}

local function clean_text(v, max)
    if type(v) ~= 'string' then return nil end
    return (v:gsub('[^%w %.,;:\'%(%)!%?%-]', '')):sub(1, max)
end

-- (0.104.0) The AI's ledger: the few things it must remember that the game
-- can't tell it (it raised the alert, it closed the gate, it banned cooking
-- brewables, the memorials it built...). Written into the save the moment
-- they change, so a save always holds the ledger that goes with its game:
-- the memory the overseer writes only once a game week could be older than
-- the game it was saved with (a reload lost the stop-gap temple, 0.103.13).
LEDGER_KEY = 'ai-overseer/ledger'
LEDGER_FIELDS = {
    ai_alert_raised = true, gate_closed_by_ai = true, kitchen_ban = true, farm_steer = true,
    tree_year = true, libraries_imported = true, squads_trained = true, squads_rested = true,
    tools_seen_on = true, tools_player_disabled = true, stuck_cancelled = true, wishes_agreed = true,
    last_expel_tick = true, last_memorial_tick = true, last_garden_tick = true, gardens_built = true,
    memorials_built = true, quick_locations = true, at = true,
}
LEDGER_MAX_ITEMS = 600

local function ledger_clean(v, depth, budget)
    if budget.n <= 0 then return nil end
    budget.n = budget.n - 1
    local t = type(v)
    if t == 'boolean' then return v end
    if t == 'number' then
        if v ~= v or v == math.huge or v == -math.huge then return nil end
        return math.tointeger(v) or v
    end
    if t == 'string' then return (v:gsub('%c', '')):sub(1, 120) end   -- (names may carry accents)
    if t ~= 'table' or depth >= 3 then return nil end
    local out = {}
    for k, x in pairs(v) do
        local key = type(k) == 'number' and math.tointeger(k) or (type(k) == 'string' and (k:gsub('%c', '')):sub(1, 120))
        if key ~= nil and key ~= false then
            local c = ledger_clean(x, depth + 1, budget)
            if c ~= nil then out[key] = c end
        end
    end
    return out
end

function ledger_data()
    local ok, d = pcall(dfhack.persistent.getSiteData, LEDGER_KEY, {})
    return ok and type(d) == 'table' and d or {}
end

function act_ledger_set(a)
    if type(a.values) ~= 'table' then return reject('ledger_set needs values') end
    local out, budget = {}, {n = LEDGER_MAX_ITEMS}
    for k, v in pairs(a.values) do
        if type(k) ~= 'string' or not LEDGER_FIELDS[k] then
            return reject(('ledger_set: %s is not a ledger field'):format(tostring(k)))
        end
        local c = ledger_clean(v, 0, budget)
        if c ~= nil then out[k] = c end
    end
    if budget.n <= 0 then return reject('ledger_set: too much to keep') end
    if a.dry_run then return {ok = true, dry_run = true} end
    local ok = pcall(dfhack.persistent.saveSiteData, LEDGER_KEY, out)
    if not ok then return {ok = false, error = 'the ledger could not be saved with the fort'} end
    return {ok = true}
end

function act_set_culture(a)
    local c = type(a.culture) == 'table' and a.culture or nil
    if not c then return reject('set_culture needs a culture object') end
    local pr = type(c.profile) == 'table' and c.profile or {}
    local profile = {}
    for k, allowed in pairs(CULTURE_ENUMS) do
        if pr[k] ~= nil then
            if not allowed[pr[k]] then return reject(('culture.profile.%s is not allowed'):format(k)) end
            profile[k] = pr[k]
        end
    end
    profile.smooth = int_in(pr.smooth or 0, 0, 3)
    profile.statues = int_in(pr.statues or 0, 0, 4)
    if profile.smooth == nil or profile.statues == nil then return reject('culture.profile numbers out of range') end
    profile.entry_doors = pr.entry_doors == true
    local memorials = {}
    for _, m in ipairs(type(pr.memorials) == 'table' and pr.memorials or {}) do
        local t = clean_text(m, 40)
        if t and #memorials < 12 then table.insert(memorials, t) end
    end
    profile.memorials = memorials
    local eras = {}
    for _, e in ipairs(type(c.eras) == 'table' and c.eras or {}) do
        if type(e) == 'table' and #eras < 12 then
            table.insert(eras, {year = math.tointeger(tonumber(e.year)) or 0, title = clean_text(e.title, 60) or ''})
        end
    end
    -- the weights engine's choices and the fort's quirks (display only)
    local function says(v, max) return type(v) == 'string' and (v:gsub('[^%w %.,;:\'%(%)!%?%-%+]', '')):sub(1, max) or nil end
    local choices = {}
    for _, ch in ipairs(type(c.choices) == 'table' and c.choices or {}) do
        if type(ch) == 'table' and #choices < 16 then
            table.insert(choices, {name = says(ch.name, 30) or '?', choice = says(ch.choice, 50) or '?',
                                   why = says(ch.why, 160) or '', by_ai = ch.by_ai == true,
                                   later = says(ch.later, 100)})
        end
    end
    local quirks = {}
    for _, q in ipairs(type(c.quirks) == 'table' and c.quirks or {}) do
        if type(q) == 'table' and #quirks < 6 then
            table.insert(quirks, {name = says(q.name, 30) or '?', since = math.tointeger(tonumber(q.since)) or 0,
                                  why = says(q.why, 160) or '', does = says(q.does, 200) or '',
                                  fade = says(q.fade, 160) or ''})
        end
    end
    -- the master plan in words, and the fort's current phase (display only)
    local plan = {}
    for _, s in ipairs(type(c.plan) == 'table' and c.plan or {}) do
        local t = says(s, 160)
        if t and #plan < 8 then table.insert(plan, t) end
    end
    -- (0.94) what each slider does now (brain/temperament.py), for the panel
    local effects = {}
    for k, v in pairs(type(c.effects) == 'table' and c.effects or {}) do
        if type(k) == 'string' and k:match('^[%l_]+$') and #k <= 20 and type(v) == 'string' then
            effects[k] = (v:gsub("[^%w %.,;:'%(%)!%?%-%+%%/]", '')):sub(1, 140)
        end
    end
    -- (0.95) what leans each slider beyond your setting (brain/leanings.py)
    local leanings = {}
    for k, v in pairs(type(c.leanings) == 'table' and c.leanings or {}) do
        if type(k) == 'string' and k:match('^[%l_]+$') and #k <= 20 and type(v) == 'string' then
            leanings[k] = (v:gsub("[^%w %.,;:'%(%)!%?%-%+%%/]", '')):sub(1, 110)
        end
    end
    local data = {
        choices = choices, quirks = quirks, effects = effects, leanings = leanings,
        plan = plan, phase = says(c.phase, 120),
        guide = clean_text(c.guide, 400) or '',
        stone = clean_text(c.stone, 40),
        profile = profile, eras = eras,
        beasts_slain = math.tointeger(tonumber(c.beasts_slain)) or 0,
        sieges = math.tointeger(tonumber(c.sieges)) or 0,
        updated = get_date(),
    }
    local ok = pcall(dfhack.persistent.saveSiteData, CULTURE_KEY, data)
    return ok and {ok = true} or {ok = false, error = 'could not save the culture with the fort'}
end

-- What the AI has learned (your preferences and lessons, self-tuned targets,
-- the outcome log's verdicts), for the panel's Culture tab (Shift-V). Display
-- only: nothing in the game reads it.
LEARNED_KEY = 'ai-overseer/learned'

local function says(v, max)
    return type(v) == 'string' and (v:gsub('[^%w %.,;:\'"%(%)!%?%-%+%%/>]', '')):sub(1, max) or nil
end

local function says_list(v, n, max)
    local out = {}
    for _, s in ipairs(type(v) == 'table' and v or {}) do
        local t = says(s, max)
        if t and #out < n then table.insert(out, t) end
    end
    return out
end

function act_set_learned(a)
    local l = type(a.learned) == 'table' and a.learned or nil
    if not l then return reject('set_learned needs a learned object') end
    local prefs = {}
    for _, p in ipairs(type(l.prefs) == 'table' and l.prefs or {}) do
        if type(p) == 'table' and #prefs < 12 then
            table.insert(prefs, {text = says(p.text, 60) or '?', weight = tonumber(p.weight) or 0,
                                 lesson = p.lesson == true, inherited = p.inherited == true,
                                 how = says(p.how, 240) or '', effect = says(p.effect, 60) or ''})
        end
    end
    local tuned = {}
    for _, t in ipairs(type(l.tuned) == 'table' and l.tuned or {}) do
        if type(t) == 'table' and #tuned < 8 then
            table.insert(tuned, {name = says(t.name, 50) or '?', value = tonumber(t.value) or 0,
                                 default = tonumber(t.default) or 0, why = says(t.why, 160) or '',
                                 date = says(t.date, 30) or ''})
        end
    end
    local data = {
        prefs = prefs, tuned = tuned,
        verdicts = says_list(l.verdicts, 6, 200), waiting = says_list(l.waiting, 4, 200),
        lessons = says_list(l.lessons, 6, 120), log = says_list(l.log, 6, 200),
        trends = says_list(l.trends, 6, 160), places = says_list(l.places, 4, 160),
        story = says_list(l.story, 4, 160),
        updated = get_date(),
    }
    local ok = pcall(dfhack.persistent.saveSiteData, LEARNED_KEY, data)
    return ok and {ok = true} or {ok = false, error = 'could not save what the AI learned with the fort'}
end

function act_engrave_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').engrave_project(id)
end

-- Idle hands: the next finished level smoothed, then engraved (lua/ai-builder.lua).
function act_polish(a)
    return reqscript('ai-builder').polish_next(a.dry_run == true)
end

function act_cancel_project(a)
    local id = project_id(a)
    if not id then return reject('project_id must be a whole number') end
    return reqscript('ai-builder').cancel_project(id)
end

-- The overseer's memory (cooldowns, culture history, token bank...), kept in
-- the save so it matches whichever save is loaded. The file holds
-- {fort, kinds = {working = "<json text>", ...}, drop_legacy}: each kind is
-- stored as text, untouched, under its own key (only changed kinds are sent).
-- An older brain's {fort, memory} still goes to the old single key.
local function drop_legacy_memory()
    local del = dfhack.persistent.deleteSiteData
    if type(del) == 'function' and pcall(del, MEMORY_KEY) then return end
    -- no delete in this DFHack: leave a marker cmd_memory reads as absent
    pcall(dfhack.persistent.saveSiteData, MEMORY_KEY, {dropped = true})
end

function act_save_memory(a)
    local ok, data = pcall(json.decode_file, MEMORY_TO_SAVE)
    if not ok or type(data) ~= 'table' or type(data.fort) ~= 'string' then
        return reject('the memory file is missing or not valid')
    end
    if data.kinds == nil and data.memory ~= nil then
        local saved = pcall(dfhack.persistent.saveSiteData, MEMORY_KEY, data)
        return saved and {ok = true, saved = {'legacy'}}
            or {ok = false, error = 'could not store the memory with the fort'}
    end
    -- (0.104.44) the texts in files of their own, as they are (the Lua JSON
    -- decoder took ~5 s on 60 KB)
    if type(data.kinds_files) == 'table' then
        data.kinds = data.kinds or {}
        for kind, name in pairs(data.kinds_files) do
            if type(name) ~= 'string' or not name:match('^memory%-to%-save%.[%a_]+%.txt$') then
                return reject('bad memory file name')
            end
            local f = io.open(OUT_DIR .. '/' .. name, 'rb')
            if not f then return reject('the memory file for ' .. tostring(kind) .. ' is missing') end
            data.kinds[kind] = f:read('*a')
            f:close()
        end
    end
    if type(data.kinds) ~= 'table' then return reject('the memory file has no kinds') end
    local allowed = utils.invert(MEMORY_KINDS)
    local names = {}
    for kind, text in pairs(data.kinds) do
        if not allowed[kind] then return reject(('unknown memory kind: %s'):format(tostring(kind))) end
        if type(text) ~= 'string' then return reject(('memory kind %s must be text'):format(kind)) end
        table.insert(names, kind)
    end
    table.sort(names)
    local saved = {}
    for _, kind in ipairs(names) do
        local done = pcall(dfhack.persistent.saveSiteData, MEMORY_KIND_PREFIX .. kind,
                           {fort = data.fort, text = data.kinds[kind]})
        if not done then
            return {ok = false, saved = saved, error = ('could not store the %s memory with the fort'):format(kind)}
        end
        table.insert(saved, kind)
    end
    if data.drop_legacy == true then drop_legacy_memory() end
    return {ok = true, saved = saved}
end

-- The overseer's report for the on-screen panel (memory only, not the save).
function act_report_status(a)
    local ok, err = reqscript('ai-status').set_status(a.status)
    if not ok then return reject(err) end
    -- (0.104.88) the camera director starts (or keeps running) while an
    -- unattended keeper reports; it says what it shows
    local okc, cam = pcall(function()
        local C = reqscript('ai-camera')
        -- (0.104.90) the keeper's places: the plan's districts, its newest work's reasons
        if type(a.status) == 'table' and type(a.status.camera) == 'table' then C.set_brain(a.status.camera) end
        C.ensure()
        local st = C.status()
        return {mode = st.mode, showing = st.showing, kind = st.kind, held = st.held, queued = st.queued,
                tour_stops = st.tour_stops, shown = st.shown, error = st.error, pinned = st.pinned}
    end)
    return {ok = true, camera = okc and cam or {error = tostring(cam):sub(1, 120)}}
end

-- Military (lua/ai-military.lua). Squads are the player's; the AI fills
-- them, sets their schedule, gives (and clears) its own kill orders, and
-- pulls the lever named "AI gate".
-- DFHack's own work-order libraries (conditioned orders, e.g. smelting
-- whenever bars run low). Only these ones.
local ORDER_LIBRARIES = {smelting = true, rockstock = true}

function act_import_orders(a)
    if not ORDER_LIBRARIES[a.library] then
        return reject('library must be one of: ' .. table.concat(sorted_keys(ORDER_LIBRARIES), ', '))
    end
    local before = #df.global.world.manager_orders.all
    local out, rv = dfhack.run_command_silent('orders', 'import', 'library/' .. a.library)
    if rv ~= CR_OK then
        return {ok = false, error = ('orders import failed: %s'):format((out or ''):gsub('%s+$', ''))}
    end
    return {ok = true, library = a.library, added = #df.global.world.manager_orders.all - before}
end

-- (0.104.116) Spider webs removed (DFHack's clear-webs, webs only): a
-- fort's caverns held 10,000 of them, a fifth of the items on the map.
function act_clear_webs(a)
    if not dfhack.findScript('clear-webs') then
        return {ok = false, error = 'DFHack has no clear-webs script in this version'}
    end
    local before = #df.global.world.items.other.ANY_WEBS
    if a.dry_run then return {ok = true, dry_run = true, webs = before} end
    local out, rv = dfhack.run_command_silent('clear-webs', '--websOnly')
    if rv ~= CR_OK then return {ok = false, error = 'clear-webs failed: ' .. tostring(out):sub(1, 160)} end
    return {ok = true, removed = before - #df.global.world.items.other.ANY_WEBS}
end

-- (0.104.113) What fills the map, read only (lua/ai-census.lua).
function act_census(a)
    return reqscript('ai-census').census()
end

-- (0.104.108) Areas on one level joined by a corridor (lua/ai-joins.lua).
function act_join_levels(a)
    return reqscript('ai-joins').join_levels(a.dry_run == true)
end

-- The fort's entrances and their gates (lua/ai-gates.lua).
function act_scan_entrances(a)
    local t0 = os.clock()
    local r = reqscript('ai-gates').scan(df.global.cur_year * 403200 + df.global.cur_year_tick)
    r.ok, r.ms = true, math.floor((os.clock() - t0) * 1000)
    return r
end

function act_build_gate_doors(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('build_gate_doors needs entrance_id') end
    return reqscript('ai-gates').build_doors(id)
end

local GATE_STYLES = {plain = true, narrow = true, fortified = true, gatehouse = true, grand = true, drawbridge = true}

function act_fortify_entrance(a)
    local id = whole_number(a.entrance_id)
    if not id then return reject('fortify_entrance needs entrance_id') end
    if not GATE_STYLES[a.style] then return reject('fortify_entrance needs style plain|narrow|fortified|gatehouse|grand|drawbridge') end
    return reqscript('ai-gates').fortify(id, a.style)
end

-- A fresh embark: the fort's first staircase (lua/ai-builder.lua found_fort).
function act_found_fort(a)
    return reqscript('ai-builder').found_fort(a.dry_run == true)
end

-- (unattended) Unpause the game: DF pauses itself for many announcements,
-- and a fort left alone would wait there for days. Refused while halted.
local function saving_now()
    local ok, r = pcall(function() return df.global.plotinfo.main.autosave_request end)
    return ok and r == true
end

function act_unpause(a)
    if saving_now() then return {ok = false, rejected = true, error = 'the game is saving'} end
    local was = df.global.pause_state
    -- (a = {unstick = true}) time isn't moving though the game isn't paused:
    -- DF waits on a popup announcement. Those wait in world.status.popups;
    -- they're taken off (their text is in the reports anyway).
    local cleared = 0
    if a.unstick == true then
        pcall(function()
            local list = df.global.world.status.popups
            while #list > 0 do
                local p = list[#list - 1]
                list:erase(#list - 1)
                pcall(function() p:delete() end)
                cleared = cleared + 1
            end
        end)
    end
    df.global.pause_state = false
    return {ok = true, was_paused = was == true, popups_cleared = cleared}
end

-- (unattended) No announcement pauses the game or opens a popup box while
-- the fort is left to the AI: DF's per-announcement flags PAUSE and DO_MEGA
-- (the box) are cleared in memory only (DF's settings files are untouched:
-- restarting DF brings them back). dry_run counts without changing.
local function announcement_flags()
    for _, get in ipairs({function() return df.global.d_init.announcements.flags end,
                          function() return df.global.announcements.flags end}) do
        local ok, f = pcall(get)
        if ok and f ~= nil then
            local ok2 = pcall(function() return f[0].PAUSE end)
            if ok2 then return f end
        end
    end
    return nil
end

function act_quiet_announcements(a)
    local flags = announcement_flags()
    if not flags then return {ok = false, rejected = true, error = 'announcement settings not found in this DF'} end
    local pause, box, seen = 0, 0, 0
    -- (a DFHack enum is walked by its first and last item: pairs() gives nothing,
    -- which is why 0.36.1 found 0 kinds and quieted nothing)
    local t = df.announcement_type
    for i = t._first_item, t._last_item do
        pcall(function()
            local fl = flags[i]
            seen = seen + 1
            if fl.PAUSE then pause = pause + 1; if not a.dry_run then fl.PAUSE = false end end
            if fl.DO_MEGA then box = box + 1; if not a.dry_run then fl.DO_MEGA = false end end
        end)
    end
    if seen == 0 then return {ok = false, error = 'no announcement kinds could be read'} end
    return {ok = true, dry_run = a.dry_run == true or nil, pausing = pause, boxes = box, kinds = seen}
end

-- (unattended) Save the game now, in its own save folder (DFHack's quicksave).
function act_save_game(a)
    if not dfhack.findScript('quicksave') then
        return {ok = false, rejected = true, error = 'DFHack has no quicksave script here'}
    end
    if a.dry_run == true then return {ok = true, dry_run = true} end
    if saving_now() then return {ok = true, already = true, by = 'the game is saving itself now'} end
    -- DF's own seasonal autosave usually comes at the same moment: if any save
    -- was written in the last 15 minutes, another one is only lag
    local okm, newest = pcall(function()
        local root = dfhack.getDFPath() .. '/save'
        local best = 0
        for _, name in ipairs(dfhack.filesystem.listdir(root) or {}) do
            for _, p in ipairs({root .. '/' .. name, root .. '/' .. name .. '/world.sav'}) do
                local m = tonumber(dfhack.filesystem.mtime(p))
                -- (on Windows DFHack gives the file time in 100 ns steps since 1601,
                -- which read as seconds made "saved -2239490023674139 minutes ago")
                if m and m > 1e15 then m = m / 1e7 - 11644473600
                elseif m and m > 1e11 then m = m / 1000 end
                if m and m > best and m <= os.time() + 60 then best = m end
            end
        end
        return best
    end)
    if okm and newest and newest > 0 and os.time() - newest < 15 * 60 then
        return {ok = true, already = true,
                by = ('the game saved itself %d minute(s) ago'):format(math.floor((os.time() - newest) / 60))}
    end
    local out, rv = dfhack.run_command_silent('quicksave')
    if rv ~= CR_OK then return {ok = false, error = ('quicksave failed: %s'):format((out or ''):gsub('%s+$', ''))} end
    return {ok = true, requested = true}       -- (DF saves over the next frames)
end

-- Traps behind a gate, in the fort's trap style.
function act_place_traps(a)
    local id = whole_number(a.entrance_id)
    local n = int_in(a.count, 1, 8)
    if not id or not n then return reject('place_traps needs entrance_id and count 1-8') end
    if not (a.kind == 'cage' or a.kind == 'stonefall' or a.kind == 'weapon') then
        return reject('place_traps needs kind cage|stonefall|weapon')
    end
    return reqscript('ai-gates').place_traps(id, a.kind, n)
end

-- Link a lever to a bridge, door or hatch (a mechanic does the job).
function act_link_lever(a)
    local lid, tid = whole_number(a.lever_id), whole_number(a.target_id)
    if not lid or not tid then return reject('link_lever needs lever_id and target_id') end
    -- (0.100, security pass) the action links the AI's own lever to a
    -- drawbridge, as the gate rule asks; never the player's levers, and never
    -- a floodgate (water or magma behind it). The cistern links its floodgate
    -- itself, inside the builder.
    local lever, target = df.building.find(lid), df.building.find(tid)
    if not (lever and tostring(lever.name or ''):lower():find('^ai gate')) then
        return reject('only a lever named "AI gate" is linked by the AI')
    end
    if not (target and target:getType() == df.building_type.Bridge) then
        return reject('the AI links its lever to a drawbridge only')
    end
    return reqscript('ai-gates').link_lever(lid, tid, a.dry_run == true)
end

function act_arm_gates(a) return reqscript('ai-gates').arm() end
function act_open_gates(a) return reqscript('ai-gates').open_all() end

-- Set-ups the AI does itself (lua/ai-society.lua).
function act_setup_shelter(a)
    return reqscript('ai-society').setup_shelter()
end

function act_set_population_cap(a)
    local cap = int_in(a.cap, 7, 1000)
    if not cap then return reject('set_population_cap needs cap 7-1000') end
    local strict = int_in(a.strict or (cap + 20), cap, 1100)
    if not strict then return reject('strict must be at least the cap') end
    return reqscript('ai-society').set_popcap(cap, strict)
end

-- (0.100, security pass) at most one dwarf sent away a game week, whoever
-- asks (the planner waits 28 days already); kept in the save
EXPEL_KEY, EXPEL_GAP_TICKS = 'ai-overseer/expel', 7 * 1200
function act_expel_dwarf(a)
    local id = a.unit_id ~= nil and whole_number(a.unit_id) or nil
    local now = df.global.cur_year * 403200 + df.global.cur_year_tick
    local okg, last = pcall(dfhack.persistent.getSiteData, EXPEL_KEY, {})
    local tick = okg and type(last) == 'table' and tonumber(last.tick) or nil
    if tick and now >= tick and now - tick < EXPEL_GAP_TICKS then
        return reject('a dwarf was sent away less than a week ago')
    end
    local r = reqscript('ai-society').expel_one(txt, id)
    if r and r.ok then pcall(dfhack.persistent.saveSiteData, EXPEL_KEY, {tick = now}) end
    return r
end

-- A new pasture on grass near the fort's surface entrances, sized for the
-- herd (the planner says how many tiles), then the waiting grazers go in.
function act_make_pasture(a)
    local tiles = int_in(a.tiles, 9, 600)
    if not tiles then return reject('make_pasture needs tiles 9-600') end
    local r = reqscript('ai-builder').make_pasture({tiles = tiles}, a.dry_run == true)
    if r.ok and not r.dry_run then
        local ok, p = pcall(reqscript('ai-society').pasture, 50)
        r.assigned = ok and type(p) == 'table' and p.assigned or 0
    end
    return r
end

-- (0.104.83) Squads hold the gate (lua/ai-society.lua guard_gate); war dogs posted there (gate_dogs).
function act_guard_gate(a)   -- (module-level: the chunk's 200-local limit)
    local x, y, z = int_in(a.x, 0, 1000), int_in(a.y, 0, 1000), int_in(a.z, 0, 1000)
    if not x or not y or not z or type(a.squads) ~= 'table' or #a.squads == 0 then
        return reject('guard_gate needs x, y, z and squads')
    end
    local ids = {}
    for _, s in ipairs(a.squads) do
        local id = int_in(s, 0, 1000000)
        if id then table.insert(ids, id) end
    end
    return reqscript('ai-society').guard_gate(ids, x, y, z, int_in(a.radius or 5, 2, 10), a.dry_run == true)
end

function act_gate_dogs(a)   -- (module-level: the chunk's 200-local limit)
    local x, y, z = int_in(a.x, 0, 1000), int_in(a.y, 0, 1000), int_in(a.z, 0, 1000)
    if not x or not y or not z then return reject('gate_dogs needs x, y, z') end
    return reqscript('ai-society').gate_dogs(x, y, z, int_in(a.max or 4, 1, 12), a.dry_run == true)
end

-- (0.104.82) A new stairwell for a district (lua/ai-builder.lua dig_stairwell).
function act_dig_stairwell(a)   -- (module-level: the chunk's 200-local limit)
    local lo, hi = int_in(a.elev_lo, -500, 500), int_in(a.elev_hi or a.elev_lo, -500, 500)
    if type(a.dir) ~= 'string' or not lo or not hi then
        return reject('dig_stairwell needs dir and elev_lo (elev_hi)')
    end
    local spine
    if type(a.spine) == 'table' then spine = {x = int_in(a.spine.x, 0, 1000), y = int_in(a.spine.y, 0, 1000)} end
    return reqscript('ai-builder').dig_stairwell({dir = a.dir, elev_lo = lo, elev_hi = hi, spine = spine,
        min_dist = int_in(a.min_dist or 10, 4, 60), max_dist = int_in(a.max_dist or 40, 6, 80)}, a.dry_run == true)
end

-- (0.104.81) Tame animals put to war training (lua/ai-society.lua train_war).
function act_train_war(a)   -- (module-level: the chunk's 200-local limit)
    local n = int_in(a.max, 1, 10)
    if not n then return reject('train_war needs max 1-10') end
    return reqscript('ai-society').train_war(n, a.dry_run == true, txt)
end

-- (0.104.80) Nest boxes in the hens' pasture (lua/ai-society.lua nest_boxes).
function act_nest_boxes(a)   -- (module-level: the chunk's 200-local limit)
    local n = int_in(a.max, 1, 10)
    if not n then return reject('nest_boxes needs max 1-10') end
    return reqscript('ai-society').nest_boxes(n, a.dry_run == true)
end

function act_pasture(a)
    local n = int_in(a.count, 1, 50)
    if not n then return reject('pasture needs count 1-50') end
    return reqscript('ai-society').pasture(n)
end

-- Who does what (lua/ai-labor.lua): more dwarves on a job through the game's
-- own work details; never a soldier, never anyone taken off a job.
local LABOR_JOBS = {mining = true, woodcutting = true, gathering = true, fishing = true, farming = true}

function act_assign_labor(a)
    local n = int_in(a.count, 0, 10)
    local L = reqscript('ai-labor')
    if type(a.job) ~= 'string' or not n or not (LABOR_JOBS[a.job] or L.job_spec(a.job)) then
        return reject('assign_labor needs job (mining|woodcutting|gathering|fishing|farming, or a labour '
                      .. 'like BREWER) and count 0-10')
    end
    local min_skill = a.min_skill ~= nil and int_in(a.min_skill, 0, 20) or nil
    return L.assign(a.job, n, a.dry_run == true, txt, min_skill)
end

function act_assign_miners(a)
    local n = int_in(a.count, 1, 10)
    if not n then return reject('assign_miners needs count 1-10') end
    return reqscript('ai-labor').assign('mining', n, a.dry_run == true, txt)
end

-- Shrubs near the fort marked for gathering (food and drink before farms).
-- Waiting plant-gathering jobs beyond `keep` cancelled (lua/ai-labor.lua).
function act_trim_gathering(a)
    local keep = int_in(a.keep, 0, 200)
    if not keep then return reject('trim_gathering needs keep 0-200') end
    return reqscript('ai-labor').trim_gathering(keep, a.dry_run == true)
end

-- (0.99.6) autofarm's thresholds by crop: {thresholds = {PLANT_ID = n}}.
-- autofarm plants a crop while its stock is under its threshold; the AI
-- raises the brewable crops' and lowers the rest while drink is short.
function act_farm_thresholds(a)
    if type(a.thresholds) ~= 'table' then return reject('farm_thresholds needs thresholds {PLANT_ID = n}') end
    local by_n, count = {}, 0
    for id, n in pairs(a.thresholds) do
        n = int_in(n, 0, 10000)
        if type(id) ~= 'string' or not id:match('^[%u%d_]+$') or not n then
            return reject('farm_thresholds: plant ids are raws ids (A-Z, 0-9, _), thresholds 0-10000')
        end
        local found = false
        -- (13c) autofarm takes only plants with seeds (SEED): any other id
        -- stops it part-way, the earlier ones set and the rest not
        for _, raw in ipairs(df.global.world.raws.plants.all) do
            if raw.id == id then found = raw.flags.SEED and true or 'noseed' break end
        end
        if not found then return reject('farm_thresholds: no plant ' .. id) end
        if found == 'noseed' then return reject('farm_thresholds: ' .. id .. ' has no seeds (autofarm takes only crops)') end
        by_n[n] = by_n[n] or {}
        table.insert(by_n[n], id)
        count = count + 1
    end
    if count == 0 then return reject('farm_thresholds: no crops given') end
    if a.dry_run then return {ok = true, dry_run = true, crops = count} end
    if not plugin_enabled('autofarm') then
        dfhack.run_command_silent('enable', 'autofarm')
    end
    for n, ids in pairs(by_n) do
        table.sort(ids)
        local args = {'threshold', tostring(n)}
        for _, id in ipairs(ids) do table.insert(args, id) end
        local output, rv = dfhack.run_command_silent('autofarm', table.unpack(args))
        if rv ~= CR_OK then
            return {ok = false, error = 'autofarm threshold failed: ' .. tostring(output):gsub('%s+$', '')}
        end
    end
    return {ok = true, crops = count}
end

-- (0.100) Cooking eats brewable plants and fruit, and keeps no seed (brewing
-- does): while drink is short the AI bans cooking them in the kitchen
-- settings, the way DFHack's ban-cooking brew does, and lifts its own bans
-- once drink recovers. {ban = true/false}. Only the exclusions the AI added
-- are kept (in the save) and later removed: the player's own stay.
KITCHEN_KEY = 'ai-overseer/kitchen'

-- (0.100) Does this material make a drink (DRINK_MAT among its reaction products)?
local function mat_brews(m)
    for _, id in ipairs(m.reaction_product.id) do
        local v = type(id) == 'string' and id or id.value
        if v == 'DRINK_MAT' then return true end
    end
    return false
end

-- (0.100) The kitchen exclusions for every brewable cookable plant (its
-- STRUCTURAL material, item PLANT) and growth (item PLANT_GROWTH, subtype the
-- growth's index), as ban-cooking.lua's brew list makes them.
function brewable_cook_keys()
    local out = {}
    for _, p in ipairs(df.global.world.raws.plants.all) do
        if p.material_defs.type.drink ~= -1 and p.material_defs.idx.drink ~= -1 then
            for _, m in ipairs(p.material) do
                if m.id == 'STRUCTURAL' then
                    if m.flags.EDIBLE_COOKED and mat_brews(m) then
                        local mi = dfhack.matinfo.find(p.id, m.id)
                        if mi then table.insert(out, {t = df.item_type.PLANT, s = -1, mt = mi.type, mi = mi.index}) end
                    end
                    break
                end
            end
            for k, g in ipairs(p.growths) do
                local mi = dfhack.matinfo.decode(g)
                if mi and mi.material and mi.material.flags.EDIBLE_COOKED and mat_brews(mi.material) then
                    table.insert(out, {t = df.item_type.PLANT_GROWTH, s = k, mt = mi.type, mi = mi.index})
                end
            end
        end
    end
    return out
end

-- (0.103.14) Only cooks this skilled or better work the kitchens (DF's
-- workshop profile, as its Workers tab sets): good meals from a skilled cook
function act_kitchen_skill(a)
    local n = int_in(a.min_level, 0, 15)
    if not n then return reject('kitchen_skill needs min_level 0-15') end
    local set = 0
    for _, b in ipairs(df.global.world.buildings.other.WORKSHOP_ANY) do
        if b.type == df.workshop_type.Kitchen then
            if not a.dry_run then b.profile.min_level = n end
            set = set + 1
        end
    end
    if set == 0 then return reject('the fort has no kitchen') end
    return {ok = true, kitchens = set, min_level = n, dry_run = a.dry_run == true or nil}
end

function act_kitchen_brewables(a)
    if type(a.ban) ~= 'boolean' then return reject('kitchen_brewables needs ban = true or false') end
    local data = dfhack.persistent.getSiteData(KITCHEN_KEY, {bans = {}})
    local had = type(data.bans) == 'table' and data.bans or {}
    if a.ban then
        local ok, keys = pcall(brewable_cook_keys)
        if not ok then return {ok = false, error = 'kitchen_brewables: ' .. tostring(keys):sub(1, 120)} end
        if a.dry_run then return {ok = true, dry_run = true, kinds = #keys} end
        local added = 0
        for _, k in ipairs(keys) do
            -- false when the exclusion is there already (the player's own, or ours)
            if dfhack.kitchen.addExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then
                table.insert(had, k)
                added = added + 1
            end
        end
        pcall(dfhack.persistent.saveSiteData, KITCHEN_KEY, {bans = had})
        return {ok = true, banned = added, kinds = #keys, held = #had}
    end
    if a.dry_run then return {ok = true, dry_run = true, held = #had} end
    local lifted = 0
    for _, k in ipairs(had) do
        if dfhack.kitchen.removeExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then lifted = lifted + 1 end
    end
    pcall(dfhack.persistent.saveSiteData, KITCHEN_KEY, {bans = {}})
    return {ok = true, lifted = lifted}
end

-- (0.104.30) Fat and tallow kept from the cooks while the hospital has no
-- soap (Enxah: 149 fat, then 13 tallow, cooked into meals before any soap
-- was made, wounds festering): a kitchen exclusion for each kind in stock,
-- lifted with ban = false. Only the AI's own exclusions are lifted.
KITCHEN_FAT_KEY = 'ai-overseer/kitchen-fat'

function act_kitchen_fat(a)
    if type(a.ban) ~= 'boolean' then return reject('kitchen_fat needs ban = true or false') end
    local data = dfhack.persistent.getSiteData(KITCHEN_FAT_KEY, {bans = {}})
    local had = type(data.bans) == 'table' and data.bans or {}
    if a.ban then
        local seen, keys = {}, {}
        for _, it in ipairs(df.global.world.items.other.GLOB) do
            local okm, mi = pcall(dfhack.matinfo.decode, it)
            local token = okm and mi and mi:getToken() or ''
            if token:find(':TALLOW$') or token:find(':FAT$') then
                local k = it.mat_type .. ':' .. it.mat_index
                if not seen[k] then
                    seen[k] = true
                    table.insert(keys, {t = df.item_type.GLOB, s = -1, mt = it.mat_type, mi = it.mat_index})
                end
            end
        end
        if a.dry_run then return {ok = true, dry_run = true, kinds = #keys} end
        local added = 0
        for _, k in ipairs(keys) do
            if dfhack.kitchen.addExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then
                table.insert(had, k)
                added = added + 1
            end
        end
        pcall(dfhack.persistent.saveSiteData, KITCHEN_FAT_KEY, {bans = had})
        if added == 0 and #keys == 0 then return reject('no fat or tallow in the fort') end
        return {ok = true, banned = added, kinds = #keys, held = #had}
    end
    if a.dry_run then return {ok = true, dry_run = true, held = #had} end
    local lifted = 0
    for _, k in ipairs(had) do
        if dfhack.kitchen.removeExclusion({Cook = true}, k.t, k.s, k.mt, k.mi) then lifted = lifted + 1 end
    end
    pcall(dfhack.persistent.saveSiteData, KITCHEN_FAT_KEY, {bans = {}})
    return {ok = true, lifted = lifted}
end

-- (0.99.7) Soldiers who don't pick up their uniforms: DFHack's
-- uniform-unstick frees items assigned to one soldier but held by another
-- (or in a container) so their owners can claim them. Its report goes back.
function act_unstick_uniforms(a)
    local okr, changed = pcall(function() return reqscript('ai-military').replace_clothing(a.dry_run == true) end)
    if a.dry_run then return {ok = true, dry_run = true, replace_clothing = okr and changed or nil} end
    -- (0.99.9) the AI's uniforms replace clothes, and what blocks a uniform
    -- item is dropped (uniform-unstick's report named everyday gloves and shoes)
    local output, rv = dfhack.run_command_silent('uniform-unstick', '--all', '--free', '--drop')
    output = tostring(output or ''):gsub('%s+$', '')
    if rv ~= CR_OK then return {ok = false, error = 'uniform-unstick failed: ' .. output:sub(1, 200)} end
    local lines = 0
    for _ in output:gmatch('[^\n]+') do lines = lines + 1 end
    return {ok = true, lines = lines, report = output:sub(1, 400),
            replace_clothing = okr and changed or tostring(changed):sub(1, 120)}
end

-- (0.104.58) Gear DF keeps assigned to no one, or on no list, put back where
-- DF hands it out (lua/ai-military.lua free_stray_gear). A global: the main
-- chunk is at Lua's locals limit.
function act_free_stray_gear(a)
    local n = int_in(a.limit or 100, 1, 500)
    if not n then return reject('free_stray_gear: limit 1-500') end
    return reqscript('ai-military').free_stray_gear(a.dry_run == true, n)
end

-- (0.104.60) Weapons put on the soldiers' places when DF leaves the entry
-- empty with free weapons about (lua/ai-military.lua assign_weapons).
function act_assign_weapons(a)
    local n = int_in(a.limit or 10, 1, 50)
    if not n then return reject('assign_weapons: limit 1-50') end
    return reqscript('ai-military').assign_weapons(a.dry_run == true, n)
end

-- (0.104.77) A chair beside each lone chair in a tavern zone (lua/ai-builder.lua pair_chairs).
-- (0.104.78) `zones`: several tried in turn until one gets chairs (Enxah's
-- proper tavern answered "every chair has one beside it")
function act_pair_chairs(a)
    local n = int_in(a.max or 5, 1, 20)
    if not n then return reject('pair_chairs: max 1-20') end
    local ids = {}
    if type(a.zones) == 'table' then
        for _, z in ipairs(a.zones) do local id = whole_number(z); if id then table.insert(ids, id) end end
    elseif a.zone_id ~= nil then
        local id = whole_number(a.zone_id); if id then table.insert(ids, id) end
    end
    if #ids == 0 then return reject('pair_chairs needs zone_id or zones') end
    local B, said = reqscript('ai-builder'), {}
    for _, id in ipairs(ids) do
        local r = B.pair_chairs(id, a.dry_run == true, n)
        if r.ok then return r end
        table.insert(said, tostring(r.error))
    end
    return {ok = false, rejected = true, error = table.concat(said, '; ')}
end

-- (0.104.78) The recreation burrow: the low-mood moved in, the recovered let
-- out (lua/ai-society.lua recreation_tick).
function act_recreation(a)
    local n = int_in(a.max or 8, 1, 30)
    local days = int_in(a.days or 28, 3, 112)
    if not n or not days then return reject('recreation: max 1-30, days 3-112') end
    -- (0.104.80) places for those who badly want friends, a short stay each
    local f, fd = int_in(a.friends or 0, 0, 10), int_in(a.friend_days or 7, 3, 28)
    if not f or not fd then return reject('recreation: friends 0-10, friend_days 3-28') end
    return reqscript('ai-society').recreation_tick(n, days, a.dry_run == true, txt, f, fd)
end

function act_gather_plants(a)
    local n = int_in(a.count or 100, 1, 150)
    if not n then return reject('gather_plants needs count 1-150') end
    return reqscript('ai-labor').gather_plants(n, a.dry_run == true)
end

-- Outside things: a refuse pile, a trade depot (lua/ai-builder.lua).
function act_place_surface(a)
    if a.kind ~= 'refuse' and a.kind ~= 'depot' and a.kind ~= 'dump' and a.kind ~= 'cages' then
        return reject('place_surface needs kind refuse|depot|dump|cages')
    end
    return reqscript('ai-builder').place_surface(a.kind, a.dry_run == true)
end

-- (0.101) A bridge across water on the surface (lua/ai-builder.lua crossings).
function act_build_crossing(a)
    local x, y, z = whole_number(a.x), whole_number(a.y), whole_number(a.z)
    local len, width = int_in(a.len, 1, 9), int_in(a.width or 1, 1, 3)
    if not (x and y and z and len and width) or not ({n = 1, s = 1, e = 1, w = 1})[a.dir] then
        return reject('build_crossing needs x, y, z, dir n|s|e|w, len 1-9 and width 1-3')
    end
    if a.kind ~= nil and a.kind ~= 'cheap' and a.kind ~= 'refined' then
        return reject('kind must be cheap or refined')
    end
    local now = df.global.cur_year * 403200 + df.global.cur_year_tick
    return reqscript('ai-builder').build_crossing(x, y, z, a.dir, len, width, a.kind or 'cheap', now, a.dry_run == true)
end

function act_remove_crossing(a)
    local i = int_in(a.index, 1, 50)
    if not i then return reject('remove_crossing needs index 1-50 (one of the AI\'s own bridges)') end
    return reqscript('ai-builder').remove_crossing(i, a.dry_run == true)
end

-- The keep: walls round the way in, then a roof (lua/ai-builder.lua), a step at a time.
function act_place_keep(a)
    return reqscript('ai-builder').place_keep(a.dry_run == true)
end

-- Worn-out clothes lying about marked for the garbage dump (DFHack's
-- cleanowned: "scattered" = only things on the ground, "x" = only the badly
-- worn), when the game runs slowly from too many items.
-- (0.104.7) One spare tame animal to the butcher: fat for tallow, tallow for
-- soap, soap for wounds (Enxah: 7 infected wounds, no soap, no fat, 42 tame
-- animals). Never a pet, a war or hunting animal, a caged or wild one, a
-- child, or the last two of a kind; from the most numerous kind, a male while
-- the kind has more than one. The game's butcher does the rest.
function slaughter_pick(animals)
    local by_race = {}
    for _, a in ipairs(animals) do
        local r = by_race[a.race] or {n = 0, males = 0, list = {}}
        r.n = r.n + 1
        if a.male then r.males = r.males + 1 end
        table.insert(r.list, a)
        by_race[a.race] = r
    end
    local best_race, best
    for race, r in pairs(by_race) do
        if r.n >= 3 and (not best or r.n > best.n or (r.n == best.n and race < best_race)) then
            best_race, best = race, r
        end
    end
    if not best then return nil end
    -- a male while the kind has two or more; else a female (the one male breeds)
    local want_male = best.males > 1
    table.sort(best.list, function(x, y)
        local xw, yw = (x.male == want_male), (y.male == want_male)
        if xw ~= yw then return xw end
        return x.id < y.id
    end)
    return best.list[1], best_race, best.n
end

function act_slaughter_one(a)
    local cands, marked = {}, 0
    for _, u in ipairs(df.global.world.units.active) do
        local ok, fit = pcall(function()
            if not dfhack.units.isAnimal(u) or not dfhack.units.isFortControlled(u) or dfhack.units.isDead(u) then return false end
            if u.flags2.slaughter then marked = marked + 1 return false end
            if dfhack.units.isPet(u) or dfhack.units.isWar(u) or dfhack.units.isHunter(u) then return false end
            if not dfhack.units.isAdult(u) or u.flags1.caged then return false end
            return true
        end)
        if ok and fit then
            local race = df.creature_raw.find(u.race)
            table.insert(cands, {id = u.id, unit = u, race = race and race.creature_id or tostring(u.race),
                                 male = dfhack.units.isMale(u)})
        end
    end
    if marked > 0 then return {ok = false, rejected = true, waiting = true, error = ('%d animal(s) already wait for the butcher'):format(marked)} end
    local pick, race, n = slaughter_pick(cands)
    if not pick then return {ok = false, rejected = true, error = 'no spare tame animal (three or more of a kind, adult, no pet or war animal)'} end
    local out = {ok = true, race = race, of = n, unit_id = pick.id, dry_run = a.dry_run or nil}
    if a.dry_run then return out end
    pick.unit.flags2.slaughter = true
    return out
end

-- (0.104.8) Instruments for the tavern and temples (DF 50 builds most from
-- parts made at several workshops, then assembled): DFHack's `instruments`
-- tool lists what the fort can make and orders an instrument with all its
-- parts. A hand-held one (they're kept in the location's chest), the fewest
-- parts first. Pure pick, then the action.
function instrument_pick(listed, defs)
    local best
    for _, d in ipairs(defs) do
        local placed = false
        for _, f in ipairs(d.flags or {}) do if f == 'PLACED_AS_BUILDING' then placed = true end end
        if not placed and listed[(d.name or ''):lower()] then
            if not best or (d.pieces or 0) < (best.pieces or 0)
                    or ((d.pieces or 0) == (best.pieces or 0) and d.name < best.name) then
                best = d
            end
        end
    end
    return best
end

function act_order_instrument(a)   -- (module-level: the chunk's 200-local limit)
    local n = int_in(a.amount or 2, 1, 10)
    if not n then return reject('order_instrument needs amount 1-10') end
    if not dfhack.findScript('instruments') then
        return {ok = false, error = 'DFHack has no instruments script in this version'}
    end
    local out, rv = dfhack.run_command_silent('instruments', 'list')
    if rv ~= CR_OK then return {ok = false, error = 'instruments list failed: ' .. tostring(out):sub(1, 120)} end
    local text = tostring(out):lower()
    -- the raws' own names (the tool lists and orders by them; accents and all)
    local defs = {}
    pcall(function()
        for _, d in ipairs(df.global.world.raws.itemdefs.instruments) do
            local e = {name = d.name, pieces = 0, flags = {}}
            pcall(function() e.pieces = #d.pieces end)
            pcall(function() if d.flags.PLACED_AS_BUILDING then e.flags = {'PLACED_AS_BUILDING'} end end)
            table.insert(defs, e)
        end
    end)
    local listed = {}
    for _, d in ipairs(defs) do
        local nm = (d.name or ''):lower()
        if nm ~= '' and text:find(nm, 1, true) then listed[nm] = true end
    end
    local pick = instrument_pick(listed, defs)
    if not pick then return {ok = false, rejected = true, error = 'no hand-held instrument the fort can make'} end
    local res = {ok = true, instrument = txt(pick.name), pieces = pick.pieces, amount = n, dry_run = a.dry_run or nil}
    if a.dry_run then return res end
    -- (0.104.68) what the tool made: 105 orders on Enxah left no order in the
    -- report; the tool's own words and the work orders before and after
    local before = #df.global.world.manager_orders.all
    local had = {}
    for _, o in ipairs(df.global.world.manager_orders.all) do had[o.id] = true end
    local o2, rv2 = dfhack.run_command_silent('instruments', 'order', pick.name, tostring(n))
    if rv2 ~= CR_OK then return {ok = false, error = 'instruments order failed: ' .. tostring(o2):sub(1, 160)} end
    res.orders_made = #df.global.world.manager_orders.all - before
    -- (0.104.69) the tool's orders are the AI's: counted as queued, cancelled
    -- if stuck (Enxah: 31 instrument orders piled up, none counted)
    pcall(function()
        local data = ai_orders()
        for _, o in ipairs(df.global.world.manager_orders.all) do
            if not had[o.id] then data.ids[tostring(o.id)] = true end
        end
        save_ai_orders(data)
    end)
    res.report = txt(tostring(o2 or ''):gsub('%s+$', ''):sub(1, 300))
    if res.orders_made <= 0 then
        res.ok, res.rejected = false, true
        res.error = 'the instruments tool made no work order for ' .. txt(pick.name) .. ': ' .. res.report:sub(1, 120)
    end
    return res
end

-- (0.104.69) Instrument orders piled up (one a month asked, none counted as
-- queued): those the instruments tool makes (a custom reaction MAKE_<entity>
-- IN...), not yet begun, beyond `keep`, are cancelled; the rest become the
-- AI's. A global: the main chunk is at Lua's locals limit.
function act_trim_instrument_orders(a)
    local keep = int_in(a.keep or 1, 0, 10)
    if not keep then return reject('trim_instrument_orders: keep 0-10') end
    local all = df.global.world.manager_orders.all
    local mine, cancelled = {}, 0
    for _, o in ipairs(all) do
        local okr, r = pcall(function() return o.reaction_name end)
        if okr and type(r) == 'string' and r:match('^MAKE_ENT%d+ IN') then table.insert(mine, o) end
    end
    local data = ai_orders()
    -- begun ones (some made) first: they are kept
    table.sort(mine, function(x, y)
        local bx, by = x.amount_left < x.amount_total, y.amount_left < y.amount_total
        if bx ~= by then return bx end
        return x.id < y.id
    end)
    for i, o in ipairs(mine) do
        if i > keep and o.amount_left == o.amount_total then
            if not a.dry_run then
                data.ids[tostring(o.id)] = true
                save_ai_orders(data)
                local r = act_cancel_work_order({order_id = o.id})
                if r and r.ok then cancelled = cancelled + 1 end
                data = ai_orders()
            else
                cancelled = cancelled + 1
            end
        elseif not a.dry_run then
            data.ids[tostring(o.id)] = true
        end
    end
    if not a.dry_run then save_ai_orders(data) end
    return {ok = true, found = #mine, cancelled = cancelled, kept = #mine - cancelled, dry_run = a.dry_run or nil}
end

-- (0.104.10) free time: an "everybody" work detail narrowed to a crew, or back (lua/ai-labor.lua)
function act_narrow_detail(a)
    if a.job ~= 'farming' and a.job ~= 'gathering' then return reject('narrow_detail: job must be farming or gathering') end
    if a.widen == true then return reqscript('ai-labor').widen(a.job, a.dry_run == true) end
    local n = int_in(a.keep or 5, 1, 30)
    if not n then return reject('narrow_detail needs keep 1-30') end
    return reqscript('ai-labor').narrow(a.job, n, a.dry_run == true, txt)
end

function act_tidy(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    local out, rv = dfhack.run_command_silent('cleanowned', 'scattered', 'x')
    if rv ~= CR_OK then return {ok = false, error = 'cleanowned failed: ' .. tostring(out):sub(1, 160)} end
    local n = 0
    for _ in tostring(out):gmatch('[Mm]arked') do n = n + 1 end
    for _ in tostring(out):gmatch('[Dd]ump') do n = math.max(n, 1) end
    return {ok = true, marked_lines = n, said = tostring(out):sub(1, 200)}
end

-- (0.104.0) Old remains rot away when the game runs slowly from too many
-- items: DFHack's deteriorate for non-entombed corpses and body parts nobody
-- can craft with (its defaults). Usable parts (bones, hair, wool) and food are
-- left alone; entombed dead are never touched. Stays on in this save.
function act_prune_remains(a)
    if not dfhack.findScript('deteriorate') then
        return {ok = false, error = 'DFHack has no deteriorate script in this version'}
    end
    -- (0.104.115) and, asked for by name: worn clothes thrown on the floor
    -- ('clothes': only on the ground and worn, never armour) and usable parts
    -- ('usable-parts': Teacheroar held 7,227 butchered bones and shells on the
    -- ground, 6,627 dead creatures still on the map's books)
    local cats = {'corpses', 'unusable-parts'}
    for _, c in ipairs(type(a.extra) == 'table' and a.extra or {}) do
        if c == 'clothes' or c == 'usable-parts' then table.insert(cats, c) end
    end
    if a.dry_run then return {ok = true, dry_run = true, categories = cats} end
    local out, rv = dfhack.run_command_silent('deteriorate', 'enable', table.concat(cats, ','))
    if rv ~= CR_OK then
        return {ok = false, error = 'deteriorate failed: ' .. tostring(out):sub(1, 160)}
    end
    out, rv = dfhack.run_command_silent('enable', 'deteriorate')
    if rv ~= CR_OK then
        return {ok = false, error = 'enable deteriorate failed: ' .. tostring(out):sub(1, 160)}
    end
    return {ok = true, categories = cats, said = tostring(out):sub(1, 200)}
end

-- An office filled by the AI (lua/ai-nobles.lua): manager, bookkeeper,
-- broker, chief medical dwarf; read back through DFHack, undone if unseen.
function act_appoint(a)
    if type(a.office) ~= 'string' then return reject('appoint needs office') end
    return reqscript('ai-nobles').appoint(a.office, a.dry_run == true, txt)
end

-- A new squad, led by an appointed militia commander or captain (lua/ai-military.lua).
function act_make_squad(a)
    return reqscript('ai-military').make_squad(a.dry_run == true, txt)
end

-- A vein of the metal the fort needs marked for digging (lua/ai-industry.lua).
function act_mine_ore(a)
    if type(a.metal) ~= 'string' or not a.metal:match('^[A-Z_]+$') then return reject('mine_ore needs metal') end
    local n = int_in(a.count or 40, 1, 60)
    if not n then return reject('mine_ore needs count 1-60') end
    return reqscript('ai-industry').mine(a.metal, n, a.dry_run == true)
end

-- Take down a gate the AI built at an entrance that wasn't one (lua/ai-gates.lua).
function act_clear_gate(a)
    local x, y, z = whole_number(a.x), whole_number(a.y), whole_number(a.z)
    if not (x and y and z) then return reject('clear_gate needs x, y, z') end
    local pieces = type(a.pieces) == 'table' and a.pieces or nil
    return reqscript('ai-gates').clear_gate(x, y, z, pieces, a.dry_run == true)
end

-- Goods to the depot for a caravan (lua/ai-trade.lua); the trade is yours.
function act_bring_goods(a)
    -- (0.104.78) up to 120 at a time: the finished-goods piles full of crafts
    local n = int_in(a.count or 40, 1, 120)
    if not n then return reject('bring_goods needs count 1-120') end
    return reqscript('ai-trade').bring(n, a.dry_run == true, txt, a.keep_treasures == true, a.keep_trinkets == true)
end

-- (0.103.8) The fort's goods left in the depot after the caravans: back out.
function act_unload_depot(a)
    local n = int_in(a.max or 50, 1, 200)
    if not n then return reject('unload_depot needs max 1-200') end
    return reqscript('ai-trade').unload(n, a.dry_run == true, txt)
end

-- A deal ticked on the open trade screen, and the Trade button pressed if
-- asked and calibrated (lua/ai-trade.lua). wants: {{key, count}} in order.
function act_trade_deal(a)
    local wants = {}
    for _, w in ipairs(type(a.wants) == 'table' and a.wants or {}) do
        local n = int_in(w.count, 1, 500)
        if type(w.key) ~= 'string' or not n then return reject('trade_deal wants {key, count 1-500}') end
        table.insert(wants, {key = w.key, count = n})
    end
    if #wants == 0 then return reject('trade_deal needs wants') end
    local margin = tonumber(a.margin) or 1.2
    if margin < 1.0 or margin > 3 then return reject('trade_deal margin must be 1.0-3') end
    local T = reqscript('ai-trade')
    -- (0.100, security pass) a trade screen the player opened is the
    -- player's: the AI neither ticks goods there nor presses Trade
    if not a.dry_run and a.force ~= true and not T.opened_by_ai() then
        return reject('the player opened this trade screen: the AI leaves the deal to them')
    end
    local r = T.deal(wants, margin, a.dry_run == true, txt)
    -- nothing to buy (or turned down before): the screen closed, if asked
    if r.rejected and a.close == true and not a.dry_run and T.opened_by_ai() then
        local c = T.close_screen()
        r.closed = c.closed
    end
    if r.ok and not r.waiting and not a.dry_run and a.press == true and r.calibrated then
        local p = T.press('Trade', txt)
        r.press = p
        r.answer, r.traded, r.counter, r.closed = p.answer, p.traded, p.counter, p.closed
    end
    return r
end

-- Recreational crafting turned on at a Craftsdwarf's workshop (lua/ai-society.lua).
function act_idle_crafting(a)
    return reqscript('ai-society').idle_crafting(a.dry_run == true)
end

-- Survey the water near the fort (lua/ai-water.lua): kept in the save. In
-- slices: each call scans for at most ~0.15 s and says "done = false" until
-- the survey is finished; then the cistern plan, one fort level a call
-- (the lag pass: the whole survey froze the game ~1.4 s, the plan up to 3 s).
WATER_PLAN = WATER_PLAN or nil
function act_survey_water(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    local W = reqscript('ai-water')
    local now = df.global.cur_year * 403200 + df.global.cur_year_tick
    if not WATER_PLAN then
        local r = W.scan_step(now)
        if not r.ok then return r end
        if not r.done then return {ok = true, done = false, scanning = true, left = r.left} end
        WATER_PLAN = {i = 1}
        return {ok = true, done = false, planning = true}
    end
    local B = reqscript('ai-builder')
    local i = WATER_PLAN.i
    local okp, plan, why = pcall(B.plan_cistern, i, i)
    if okp and plan and (not WATER_PLAN.best or plan.score < WATER_PLAN.best.score) then WATER_PLAN.best = plan end
    if okp and not plan and why then WATER_PLAN.why = WATER_PLAN.why or why end
    if not okp then WATER_PLAN.why = tostring(plan):sub(1, 160) end
    if i < (B.CISTERN_LEVELS or 6) then
        WATER_PLAN.i = i + 1
        return {ok = true, done = false, planning = true, level = i}
    end
    local r = W.last() or {ok = true}
    r.cistern = WATER_PLAN.best or {none = true, why = WATER_PLAN.why or 'no still, fresh water on the level under a fort level'}
    WATER_PLAN = nil
    pcall(dfhack.persistent.saveSiteData, 'ai-overseer/water', r)
    local kinds = {}
    for _, bd in ipairs(r.bodies or {}) do table.insert(kinds, ('%s %d'):format(bd.kind, bd.tiles)) end
    return {ok = true, done = true, bodies = kinds, aquifer = r.aquifer, magma = r.magma, cistern = r.cistern}
end

-- The cistern (lua/ai-builder.lua): one step of building it, or keeping it filled.
function act_cistern_step(a)
    if a.shut == true then return reqscript('ai-builder').cistern_shut(a.dry_run == true) end
    return reqscript('ai-builder').cistern_step(a.dry_run == true)
end

-- Trinkets for dwarves who want to own things (lua/ai-society.lua).
-- (0.84) a vacant post at a location (hospital staff, scribes, the tavern keeper)
function act_staff_location(a)
    local id = whole_number(a.location_id)
    if not id or type(a.post) ~= 'string' then return reject('staff_location needs location_id and post') end
    return reqscript('ai-society').staff_location(id, a.post, a.dry_run == true, txt)
end

-- (0.87.3) a post's labours for its holders (the game's screen turns them on)
-- (0.92) give a hall still being dug to another petition: project_id and
-- one of profession, deity_hf, religion
function act_retarget_hall(a)
    local id = whole_number(a.project_id)
    if not id then return reject('retarget_hall needs project_id') end
    local t = {}
    if a.profession ~= nil then
        if type(a.profession) ~= 'string' or df.profession[a.profession] == nil then return reject('unknown profession') end
        t.profession = a.profession
    elseif a.deity_hf ~= nil then
        t.deity_hf = whole_number(a.deity_hf)
        if not t.deity_hf or not df.historical_figure.find(t.deity_hf) then return reject('no such deity') end
    elseif a.religion ~= nil then
        t.religion = whole_number(a.religion)
        if not t.religion or not df.historical_entity.find(t.religion) then return reject('no such religion') end
    else
        return reject('retarget_hall needs profession, deity_hf or religion')
    end
    return reqscript('ai-builder').retarget_hall(id, t, a.dry_run == true)
end

-- (0.89) answer a temple or guildhall petition: id, accept (true/false)
function act_answer_petition(a)
    local id = whole_number(a.id)
    if not id or type(a.accept) ~= 'boolean' then return reject('answer_petition needs id and accept true|false') end
    return answer_petition(id, a.accept, a.dry_run == true)
end

-- (0.88) alerts: {TYPE = ticks | false, default = ticks}; max 1-100
function act_dismiss_alerts(a)
    local n = whole_number(a.max)
    if not n or n < 1 or n > 100 then return reject('dismiss_alerts needs max 1-100') end
    if type(a.ages) ~= 'table' then return reject('dismiss_alerts needs ages {TYPE = ticks, default = ticks}') end
    local ages = {}
    for k, v in pairs(a.ages) do
        if type(k) ~= 'string' or not (k == 'default' or df.announcement_alert_type[k] ~= nil) then
            return reject('unknown alert type: ' .. tostring(k))
        end
        local t = whole_number(v)
        if v == false then ages[k] = false
        elseif t and t >= 0 then ages[k] = t
        else return reject('alert ages are whole ticks or false') end
    end
    return reqscript('ai-reports').dismiss_alerts(ages, n, a.dry_run == true)
end

-- (0.88) one piece of furniture into a zone: zone_id, what (traction_bench)
-- (0.103.16) Engraved memorial slabs built, so the ghosts rest.
-- (0.104.42) Memorial slabs that never get put up: the construction of the
-- slab (a building the AI placed) suspended, or the engraved slab itself
-- forbidden (Enxah: 9 ghosts, 5 MurderousGhosts among them, each with its
-- slab made; 5 slab buildings suspended at stage 0, 4 slabs forbidden;
-- 25 of 36 deaths in a year from fright). The slabs unforbidden where the
-- dwarves can reach them, the slab buildings' jobs resumed.
-- (0.104.45) Water the dwarves walk over: a river or pond freezes in winter,
-- the dwarves cross the ice, and it thaws under them (Enxah: the drowned lie
-- in the river channel past the main stair; SUFFOCATE and DROWN 6 a year).
-- The tile above every water or ice tile on the given levels, within
-- `radius` of (cx, cy), gets the game's "restricted" traffic, so paths go
-- round it (a bridge or a way across stays usable: restricted only costs).
-- Never a tile the player marked high or low.
function act_restrict_water(a)
    local zs = type(a.levels) == 'table' and a.levels or {}
    local cx, cy = math.tointeger(tonumber(a.x)), math.tointeger(tonumber(a.y))
    local r = math.tointeger(tonumber(a.radius)) or 60
    if #zs == 0 or #zs > 6 or not cx or not cy or r < 5 or r > 120 then
        return reject('levels (1-6), x, y and radius 5-120 needed')
    end
    local sx, sy, sz = dfhack.maps.getTileSize()
    local marked, seen = 0, 0
    for _, z0 in ipairs(zs) do
        local z = math.tointeger(tonumber(z0))
        if z and z >= 0 and z + 1 < sz then
            for y = math.max(0, cy - r), math.min(sy - 1, cy + r) do
                for x = math.max(0, cx - r), math.min(sx - 1, cx + r) do
                    pcall(function()
                        local pos = xyz2pos(x, y, z)
                        local d = dfhack.maps.getTileFlags(pos)
                        local wet = d and d.flow_size > 0 and not d.liquid_type
                        if not wet then
                            local tt = dfhack.maps.getTileType(pos)
                            wet = tt and df.tiletype.attrs[tt].material == df.tiletype_material.FROZEN_LIQUID
                        end
                        if wet then
                            seen = seen + 1
                            local up = dfhack.maps.getTileFlags(xyz2pos(x, y, z + 1))
                            if up and up.traffic == df.tile_traffic.Normal then
                                if not a.dry_run then up.traffic = df.tile_traffic.Restricted end
                                marked = marked + 1
                            end
                        end
                    end)
                end
            end
        end
    end
    if seen == 0 then return reject('no water or ice on those levels near the fort') end
    if marked == 0 then return reject(('all %d tiles over the water are already restricted (or set by hand)'):format(seen)) end
    return {ok = true, marked = marked, water_tiles = seen, dry_run = a.dry_run or nil}
end

function act_free_slabs(a)
    local from
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local x, y, z = dfhack.units.getPosition(u)
            if x then from = xyz2pos(x, y, z) break end
        end
    end)
    local unforbid, resumed, cleared, moved = 0, 0, 0, 0
    for _, it in ipairs(df.global.world.items.other.SLAB) do
        pcall(function()
            if it.engraving_type == df.slab_engraving_type.Memorial and not it.flags.in_building then
                if not it.flags.in_job then
                    local x, y, z = dfhack.items.getPosition(it)
                    local reach = x and (not from or dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z)))
                    if x and not reach and from and not it.flags.in_inventory then
                        -- (0.104.49) shut in the rock (Enxah's oldest ghost's slab lay
                        -- inside a wall tile, a wall built over where it lay): brought
                        -- out to where a dwarf stands, the way it would have been carried
                        if not a.dry_run and dfhack.items.moveToGround(it, from) then
                            moved = moved + 1
                            it.flags.forbid = false
                        end
                    elseif it.flags.forbid and reach then
                        if not a.dry_run then it.flags.forbid = false end
                        unforbid = unforbid + 1
                    end
                end
                for _, ref in ipairs(it.specific_refs) do
                    if ref.type == df.specific_ref_type.JOB then
                        local j = ref.data.job
                        local h = dfhack.job.getHolder(j)
                        if j.flags.suspend and h and h:getType() == df.building_type.Slab then
                            -- (0.104.47) suspendmanager: "Blocked by an unmovable item":
                            -- what lies on the site is unforbidden, so the builder can
                            -- clear it (never the slab itself, an artifact, or an item
                            -- on someone's job)
                            pcall(function()
                                local own = {}
                                for _, ji in ipairs(j.items) do own[ji.item.id] = true end
                                local bx, by, bz = h.centerx, h.centery, h.z
                                for _, iid in ipairs(dfhack.maps.getTileBlock(bx, by, bz).items) do
                                    local o = df.item.find(iid)
                                    if o and not own[o.id] and o.pos.x == bx and o.pos.y == by and o.pos.z == bz
                                            and not o.flags.in_job and not o.flags.artifact then
                                        if not a.dry_run then o.flags.forbid = false end
                                        cleared = cleared + 1
                                    end
                                end
                            end)
                            if not a.dry_run then j.flags.suspend = false end
                            resumed = resumed + 1
                        end
                    end
                end
            end
        end)
    end
    if unforbid + resumed + moved == 0 then return reject('no memorial slab forbidden, shut in or held by a suspended job') end
    return {ok = true, unforbidden = unforbid, resumed = resumed, cleared = cleared, moved = moved, dry_run = a.dry_run or nil}
end

function act_place_slabs(a)
    local n = int_in(a.max or 5, 1, 20)
    if not n then return reject('place_slabs needs max 1-20') end
    return reqscript('ai-builder').place_slabs(n, a.dry_run == true)
end

function act_place_in_zone(a)
    local id = whole_number(a.zone_id)
    if not id then return reject('place_in_zone needs zone_id') end
    local B = reqscript('ai-builder')
    if not B.ZONE_FURNITURE[a.what] then
        return reject('place_in_zone: what must be one of ' .. table.concat(sorted_keys(B.ZONE_FURNITURE), ', '))
    end
    return B.place_in_zone(id, a.what, a.dry_run == true)
end

function act_vacate_post(a)    -- (0.104.111) a doctor who is a patient gives his post back
    local id, uid = whole_number(a.location_id), whole_number(a.unit_id)
    if not id or not uid then return reject('vacate_post needs location_id and unit_id') end
    return reqscript('ai-society').vacate_post(id, uid, a.dry_run == true, txt)
end

function act_staff_labors(a)   -- (module-level: the chunk's 200-local limit)
    local id = whole_number(a.location_id)
    if not id then return reject('staff_labors needs location_id') end
    return reqscript('ai-society').staff_labors(id, a.dry_run == true, txt)
end

-- (0.85) posts at a location the game hasn't made yet (as its screen does)
function act_add_posts(a)
    local id = whole_number(a.location_id)
    if not id then return reject('add_posts needs location_id') end
    local kinds = type(a.posts) == 'table' and a.posts or nil
    return reqscript('ai-society').add_posts(id, kinds, a.dry_run == true)
end

function act_give_trinkets(a)
    local n = whole_number(a.max) or 10
    if n < 1 or n > 50 then return reject('give_trinkets needs max 1-50') end
    return reqscript('ai-society').give_trinkets(n, a.dry_run == true)
end

-- Workshops the fort has far too many of, taken down (lua/ai-builder.lua).
function act_remove_workshops(a)
    if a.kind ~= 'SoapMaker' and a.kind ~= 'ScrewPress' then
        return reject('remove_workshops needs kind SoapMaker|ScrewPress')
    end
    local keep, max = whole_number(a.keep) or 1, whole_number(a.max) or 20
    return reqscript('ai-builder').remove_workshops(a.kind, keep, math.min(max, 40), a.dry_run == true)
end

-- A feeder stockpile beside a workshop (or goods beside the depot) (lua/ai-builder.lua).
function act_feeder_pile(a)
    local id = whole_number(a.building_id)
    if not id then return reject('feeder_pile needs building_id') end
    return reqscript('ai-builder').place_feeder(id, a.dry_run == true)
end

-- The trade screen opened from the depot (lua/ai-trade.lua), or closed.
function act_open_trade(a)
    return reqscript('ai-trade').open_screen(a.dry_run == true, txt)
end

-- (0.104.0) DF's meeting screen (a diplomat or the liaison) holds the game
-- until someone answers; nobody is at the game in an unattended run, so after
-- a long wait the overseer leaves it, as the player would with Esc: the
-- meeting ends without an agreement. Only that screen is ever left.
local function meeting_focus()
    local ok, f = pcall(function() return dfhack.gui.getCurFocus(true)[1] end)
    f = ok and tostring(f or '') or ''
    local low = f:lower()
    return (low:find('meeting', 1, true) or low:find('diplomacy', 1, true)) and f or nil
end

-- (0.104.2) A Water Source zone for the injured while there is no well (lua/ai-builder.lua).
-- (0.104.95) a sand collection zone (for glass), placed by the builder
function act_sand_zone(a)
    return reqscript('ai-builder').sand_zone(a.dry_run == true)
end

function act_water_zone(a)
    if type(a.points) ~= 'table' or #a.points == 0 or #a.points > 6 then
        return reject('water_zone needs points: 1-6 water tiles {x, y, z}')
    end
    local pts = {}
    for _, p in ipairs(a.points) do
        local x, y, z = int_in(p.x, 0, 1000), int_in(p.y, 0, 1000), int_in(p.z, 0, 1000)
        if not (x and y and z) then return reject('water_zone: a point needs whole x, y and z') end
        table.insert(pts, {x = x, y = y, z = z})
    end
    return reqscript('ai-builder').water_zone(pts, a.dry_run == true)
end

function act_close_meeting(a)
    local f = meeting_focus()
    if not f then return {ok = false, rejected = true, error = 'no meeting screen is open'} end
    if a.dry_run then return {ok = true, dry_run = true, screen = f} end
    pcall(function()
        require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
    end)
    local after = meeting_focus()
    return {ok = after == nil, screen = f, error = after and ('the meeting screen is still open (' .. after .. ')') or nil}
end

function act_close_trade(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    if not reqscript('ai-trade').opened_by_ai() and a.force ~= true then
        return reject('the player opened this trade screen: left open')
    end
    return reqscript('ai-trade').close_screen(a.unloading == true)
end

-- Someone to the depot for a caravan: the broker asked for, anyone after
-- `wait_ticks` (lua/ai-trade.lua).
function act_call_trader(a)
    local wait = int_in(a.wait_ticks or 1200, 0, 403200)
    if not wait then return reject('call_trader wait_ticks must be 0-403200') end
    return reqscript('ai-trade').call_trader(df.global.cur_year * 403200 + df.global.cur_year_tick, wait,
                                             a.dry_run == true, txt)
end

-- A noble given a free room of the kind its office asks for (lua/ai-nobles.lua).
function act_give_room(a)
    local id = whole_number(a.unit_id)
    if not id or type(a.kind) ~= 'string' then return reject('give_room needs unit_id and kind') end
    return reqscript('ai-nobles').give_room(id, a.kind, a.dry_run == true, txt)
end

function act_squad_release(a)
    local id = whole_number(a.unit_id)
    if not id then return reject('squad_release needs unit_id') end
    return reqscript('ai-military').release(id, a.dry_run == true, txt)
end

-- (0.104.65) A swap: a soldier trained enough goes back to work and the
-- place goes at once to the keenest outside (the fill puts those longing to
-- train first); a release alone left the squads short (34 soldiers, 31 wanted
-- after the release, so no fill came). A global: the main chunk is at Lua's
-- locals limit.
function act_squad_swap(a)
    local id = whole_number(a.unit_id)
    if not id then return reject('squad_swap needs unit_id') end
    local u = df.unit.find(id)
    local sid = u and u.military.squad_id or -1
    if sid == -1 then return reject('not in a squad') end
    local M = reqscript('ai-military')
    local r = M.release(id, a.dry_run == true, txt)
    if not r.ok or a.dry_run then return r end
    local okf, f = pcall(M.fill, sid, 1, txt)
    return {ok = true, released = r.name, squad_id = sid, filled = okf and f or tostring(f)}
end

function act_squad_trim(a)
    local n = int_in(a.count, 1, 5)
    if not n then return reject('squad_trim needs count 1-5') end
    return reqscript('ai-military').trim(n, a.dry_run == true, txt)
end

function act_squad_fill(a)
    local id, n = whole_number(a.squad_id), int_in(a.count, 1, 10)
    if not id or not n then return reject('squad_fill needs squad_id and count 1-10') end
    return reqscript('ai-military').fill(id, n, txt)
end

-- A squad given one of the fort's uniform templates (lua/ai-military.lua).
-- A squad given a barracks to train in (lua/ai-military.lua).
function act_squad_barracks(a)
    local sid, zid = whole_number(a.squad_id), whole_number(a.zone_id)
    if not sid or not zid then return reject('squad_barracks needs squad_id and zone_id') end
    return reqscript('ai-military').assign_barracks(sid, zid, a.dry_run == true)
end

-- (0.87) DF's standing orders that answer residency and citizenship
-- petitions: each 0 (ask) or 1 (accept); refused unless every one reads 0
-- or 1 now (anything else would mean the game uses these values otherwise)
function act_petition_orders(a)
    if type(a.orders) ~= 'table' then return reject('petition_orders needs orders {kind = 0|1}') end
    local cur, set = {}, {}
    for _, k in ipairs(PETITION_ORDERS) do
        local okv, v = pcall(function() return df.global[petition_order_name(k)] end)
        if not okv or (v ~= 0 and v ~= 1) then
            return {ok = false, rejected = true, error = 'standing order ' .. k .. ' reads ' .. tostring(v) .. ', not 0 or 1: left alone'}
        end
        cur[k] = v
    end
    for k, v in pairs(a.orders) do
        if cur[k] == nil or (v ~= 0 and v ~= 1) then return reject('petition_orders: unknown ' .. tostring(k) .. '=' .. tostring(v)) end
        if cur[k] ~= v then set[k] = v end
    end
    if a.dry_run then return {ok = true, dry_run = true, would_set = set, now = cur} end
    for k, v in pairs(set) do df.global[petition_order_name(k)] = v end
    for k, v in pairs(set) do
        if df.global[petition_order_name(k)] ~= v then return {ok = false, error = 'the game did not keep ' .. k} end
    end
    return {ok = true, set = next(set) and set or nil, was = cur}
end

function act_set_uniform(a)
    local id = whole_number(a.squad_id)
    if not id or (a.kind ~= 'leather' and a.kind ~= 'metal') then
        return reject('set_uniform needs squad_id and kind leather or metal')
    end
    return reqscript('ai-military').set_uniform(id, a.kind, a.dry_run == true, txt, a.ranged == true)
end

-- (0.82) mark the uniform of a squad the AI made (copied before 0.82) as the AI's
function act_adopt_uniform(a)
    local id = whole_number(a.squad_id)
    if not id then return reject('adopt_uniform needs squad_id') end
    return reqscript('ai-military').adopt_uniform(id, a.dry_run == true, txt)
end

-- Let the masons and crafters use one kind of economic stone (DF's stone
-- settings): never an ore.
function act_allow_stone(a)
    if type(a.stone) ~= 'string' or not a.stone:match('^[%u%d_]+$') then return reject('allow_stone needs stone (a token)') end
    local economic = df.global.plotinfo.economic_stone
    local raws = df.global.world.raws.inorganics.all or df.global.world.raws.inorganics
    for idx, inorg in ipairs(raws) do
        if inorg.id == a.stone then
            if a.keep == true then
                -- back to "economic": kept from ordinary jobs (coal for coke)
                if idx < #economic and economic[idx] and economic[idx] ~= 0 then
                    return {ok = false, rejected = true, error = a.stone .. ' is kept already'}
                end
                if a.dry_run == true then return {ok = true, dry_run = true, stone = a.stone, keep = true} end
                local ok = pcall(function() economic[idx] = true end)
                if not ok then pcall(function() economic[idx] = 1 end) end
                return {ok = true, stone = a.stone, keep = true}
            end
            -- (0.104.124) an ore only when the brain asks for it by name with ore = true
            -- (Teacheroar: 13 ghosts and 38 dead with no stone for slabs or coffins, 197 iron-ore boulders)
            if #inorg.metal_ore.mat_index > 0 and a.ore ~= true then return reject(a.stone .. ' is an ore: kept for the smelter') end
            if FUEL_STONES[a.stone] then return reject(a.stone .. ' is coal: kept for coke') end
            if not (idx < #economic and economic[idx] and economic[idx] ~= 0) then
                return {ok = false, rejected = true, error = a.stone .. ' may already be used'}
            end
            if a.dry_run == true then return {ok = true, dry_run = true, stone = a.stone} end
            local ok = pcall(function() economic[idx] = false end)
            if not ok then pcall(function() economic[idx] = 0 end) end
            local now_econ = economic[idx] and economic[idx] ~= 0
            if now_econ then return {ok = false, error = 'the game kept ' .. a.stone .. ' economic'} end
            return {ok = true, stone = a.stone}
        end
    end
    return reject('no such stone: ' .. a.stone)
end

-- A small chamber dug in ordinary stone, for boulders (lua/ai-industry.lua).
function act_quarry(a)
    local n = int_in(a.count or 30, 1, 30)
    if not n then return reject('quarry needs count 1-30') end
    return reqscript('ai-industry').quarry(n, a.dry_run == true)
end

-- A squad's uniform weapon made one kind (lua/ai-military.lua).
function act_set_uniform_weapon(a)
    local id = whole_number(a.squad_id)
    if not id or type(a.weapon) ~= 'string' or not a.weapon:match('^ITEM_WEAPON_[%u_]+$') then
        return reject('set_uniform_weapon needs squad_id and weapon (ITEM_WEAPON_...)')
    end
    return reqscript('ai-military').set_uniform_weapon(id, a.weapon, a.dry_run == true)
end

function act_squad_routine(a)
    local id = whole_number(a.squad_id)
    if not id or type(a.routine) ~= 'string' then return reject('squad_routine needs squad_id and routine') end
    return reqscript('ai-military').set_routine(id, a.routine)
end

function act_squad_orders(a)
    local id = whole_number(a.squad_id)
    if not id then return reject('squad_orders needs squad_id') end
    if a.clear == true then return reqscript('ai-military').orders(id, nil, true) end
    if type(a.kill) ~= 'table' or #a.kill == 0 or #a.kill > 50 then
        return reject('squad_orders needs kill: a list of 1-50 unit ids, or clear: true')
    end
    local ids = {}
    for _, v in ipairs(a.kill) do
        local n = whole_number(v)
        if not n then return reject('kill must list unit ids') end
        table.insert(ids, n)
    end
    return reqscript('ai-military').orders(id, ids, false)
end

function act_pull_gate(a)
    local id = whole_number(a.lever_id)
    if not id then return reject('pull_gate needs lever_id') end
    return reqscript('ai-military').pull_gate(id)
end

ACTIONS = {
    join_levels = act_join_levels,
    census = act_census,
    clear_webs = act_clear_webs,
    scan_entrances = act_scan_entrances,
    build_gate_doors = act_build_gate_doors,
    fortify_entrance = act_fortify_entrance,
    arm_gates = act_arm_gates,
    link_lever = act_link_lever,
    place_traps = act_place_traps,
    unpause = act_unpause,
    found_fort = act_found_fort,
    quiet_announcements = act_quiet_announcements,
    save_game = act_save_game,
    open_gates = act_open_gates,
    setup_shelter = act_setup_shelter,
    set_population_cap = act_set_population_cap,
    expel_dwarf = act_expel_dwarf,
    pasture = act_pasture,
    nest_boxes = act_nest_boxes,             -- (0.104.80)
    train_war = act_train_war,               -- (0.104.81)
    dig_stairwell = act_dig_stairwell,       -- (0.104.82)
    guard_gate = act_guard_gate,             -- (0.104.83)
    gate_dogs = act_gate_dogs,               -- (0.104.83)
    make_pasture = act_make_pasture,
    import_orders = act_import_orders,
    squad_fill = act_squad_fill,
    squad_swap = act_squad_swap,          -- (0.104.65)
    pair_chairs = act_pair_chairs,        -- (0.104.77)
    recreation = act_recreation,          -- (0.104.78)
    squad_trim = act_squad_trim,
    squad_release = act_squad_release,
    quick_location = function(a)
        if a.kind ~= 'temple' and a.kind ~= 'tavern' then return reject('quick_location needs kind temple or tavern') end
        return reqscript('ai-builder').quick_location(a.kind, a.dry_run == true)
    end,
    assign_miners = act_assign_miners,
    assign_labor = act_assign_labor,
    appoint = act_appoint,
    place_surface = act_place_surface,
    build_crossing = act_build_crossing,
    remove_crossing = act_remove_crossing,
    place_keep = act_place_keep,
    tidy = act_tidy,
    narrow_detail = act_narrow_detail,
    order_instrument = act_order_instrument,
    trim_instrument_orders = act_trim_instrument_orders,   -- (0.104.69)
    slaughter_one = act_slaughter_one,
    prune_remains = act_prune_remains,
    ledger_set = act_ledger_set,
    make_squad = act_make_squad,
    mine_ore = act_mine_ore,
    clear_gate = act_clear_gate,
    bring_goods = act_bring_goods,
    unload_depot = act_unload_depot,
    kitchen_skill = act_kitchen_skill,
    place_slabs = act_place_slabs,
    free_slabs = act_free_slabs,
    restrict_water = act_restrict_water,
    trade_deal = act_trade_deal,
    squad_barracks = act_squad_barracks,
    call_trader = act_call_trader,
    feeder_pile = act_feeder_pile,
    idle_crafting = act_idle_crafting,
    give_trinkets = act_give_trinkets,
    staff_location = act_staff_location,
    add_posts = act_add_posts,
    staff_labors = act_staff_labors,
    vacate_post = act_vacate_post,
    dismiss_alerts = act_dismiss_alerts,
    answer_petition = act_answer_petition,
    retarget_hall = act_retarget_hall,
    place_in_zone = act_place_in_zone,
    survey_water = act_survey_water,
    cistern_step = act_cistern_step,
    remove_workshops = act_remove_workshops,
    open_trade = act_open_trade,
    close_trade = act_close_trade,
    close_meeting = act_close_meeting,
    water_zone = act_water_zone,
    sand_zone = act_sand_zone,
    give_room = act_give_room,
    gather_plants = act_gather_plants,
    farm_thresholds = act_farm_thresholds,
    kitchen_brewables = act_kitchen_brewables,   -- (0.100) cooking keeps brewables while drink is short
    unstick_uniforms = act_unstick_uniforms,
    free_stray_gear = act_free_stray_gear,   -- (0.104.58)
    assign_weapons = act_assign_weapons,     -- (0.104.60)
    trim_gathering = act_trim_gathering,
    squad_routine = act_squad_routine,
    set_uniform = act_set_uniform,
    petition_orders = act_petition_orders,
    adopt_uniform = act_adopt_uniform,
    set_uniform_weapon = act_set_uniform_weapon,
    allow_stone = act_allow_stone,
    quarry = act_quarry,
    polish = act_polish,
    squad_orders = act_squad_orders,
    pull_gate = act_pull_gate,
    work_order = act_work_order,
    cancel_work_order = act_cancel_work_order,
    approve_orders = act_approve_orders,
    unsuspend_orders = act_unsuspend_orders,
    unforbid_dead = act_unforbid_dead,
    allow_burial = act_allow_burial,
    bench_jobs = act_bench_jobs,
    clear_orphan_jobs = act_clear_orphan_jobs,
    order_slots = act_order_slots,
    kitchen_fat = act_kitchen_fat,
    repair_rooms = function(a) return reqscript('ai-builder').repair_rooms(a.dry_run == true) end,
    bootstrap_chair = act_bootstrap_chair,
    sync_offices = function(a) return reqscript('ai-nobles').sync_offices(a.dry_run == true) end,
    tool = act_tool,
    civ_alert = act_civ_alert,
    start_project = act_start_project,
    farm_plots = act_farm_plots,
    place_well = act_place_well,
    furnish_project = act_furnish_project,
    free_dig_jobs = act_free_dig_jobs,
    prioritize_dig = act_prioritize_dig,
    finish_project = act_finish_project,
    engrave_project = act_engrave_project,
    set_culture = act_set_culture,
    set_learned = act_set_learned,
    report_status = act_report_status,
    save_memory = act_save_memory,
    cancel_project = act_cancel_project,
}

---------------------------------------------------------------------------
-- Time control. Globals (not locals) so they survive between script runs.
---------------------------------------------------------------------------

MAX_RUN_TICKS = 100800 -- one season

local function cancel_run()
    if run_timer_id then dfhack.timeout_active(run_timer_id, nil) end
    run_timer_id = nil
    run_until = nil
end

local function abs_tick()
    return df.global.cur_year * 403200 + df.global.cur_year_tick
end

---------------------------------------------------------------------------
-- Commands
---------------------------------------------------------------------------

local function in_fort()
    return dfhack.isMapLoaded() and dfhack.world.isFortressMode()
end

local NOT_IN_FORT = {ok = false, error = 'no fortress is loaded (the game is at a menu or in another mode)'}

function version_info()
    return {
        ok = true,
        bridge = 'ai-bridge',
        bridge_version = BRIDGE_VERSION,
        protocol = PROTOCOL,
        dfhack_version = dfhack.getDFHackVersion(),
        df_version = dfhack.getDFVersion(),
        world_loaded = dfhack.isWorldLoaded(),
        map_loaded = dfhack.isMapLoaded(),
        df_path = dfhack.getDFPath(),     -- the game's folder (saves are in save/)
        actions = sorted_keys(ACTIONS),
        recipes = sorted_keys(ORDER_RECIPES),
        tools = sorted_keys(TOOL_ALLOWLIST),
        level_kinds = reqscript('ai-layouts').KINDS,
        stockpiles = sorted_keys(reqscript('ai-layouts').STOCKPILES),
        workshops = sorted_keys(reqscript('ai-layouts').WORKSHOPS),
    }
end

-- Run one section of the report; if it fails, keep the rest of the report
-- and put the error where that section would have been.
local function safe(fn, ...)
    local ok, result = pcall(fn, ...)
    if ok then return result end
    return {error = tostring(result)}
end

-- The report's sections: name -> function(ctx) returning that section.
-- ctx.dwarves / ctx.units come from one get_dwarves call shared by both.
-- A DF name in words (dfhack.TranslateName was renamed in DFHack 50.15).
local function translate_name(name, english)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, english) end)
    if ok and s then return s end
    ok, s = pcall(function() return dfhack.TranslateName(name, english) end)
    return ok and s or nil
end

SECTIONS = {   -- (0.100) a module field: the tests swap in their own
    protocol = function() return PROTOCOL end,
    bridge_version = function() return BRIDGE_VERSION end,
    paused = function() return df.global.pause_state end,
    fort = function()
        return safe(function()
            local okw, world = pcall(function() return txt(translate_name(df.global.world.world_data.name)) end)
            local okn, name = pcall(function()
                return txt(translate_name(df.world_site.find(df.global.plotinfo.site_id).name, true))
            end)
            return {save_dir = df.global.world.cur_savegame.save_dir,
                    site_id = df.global.plotinfo.site_id,
                    world = okw and world or nil,
                    name = okn and name or nil}
        end)
    end,
    date = function() return get_date() end,
    wealth = function() return df.global.plotinfo.tasks.wealth.total end,
    dwarves = function(ctx) return ctx.dwarves end,
    units = function(ctx) return ctx.units end,
    stocks = function() return safe(get_stocks) end,
    supplies = function() return safe(get_supplies) end,
    dead = function() return safe(get_dead) end,
    -- (0.104.20) rooms whose walls were dug open
    room_gaps = function() return safe(function() return reqscript('ai-builder').room_gaps_report() end) end,
    justice = function() return safe(get_justice) end,
    society = function() return safe(get_society) end,
    entrances = function() return safe(function() return reqscript('ai-gates').summary() end) end,
    military = function() return safe(function() return reqscript('ai-military').report(txt) end) end,
    moods = function() return safe(get_moods) end,
    buildings = function() return safe(get_buildings) end,
    jobs = function() return safe(get_jobs) end,
    others_on_map = function() return safe(get_others_on_map) end,
    deep = function() return safe(get_deep) end,
    -- (0.104.95, 13b) the fort's world-map missions, read only (lua/ai-missions.lua)
    missions = function() return safe(function() return reqscript('ai-missions').report() end) end,
    needs = function() return safe(get_needs) end,
    hazards = function() return safe(get_hazards) end,
    health = function() return safe(get_health) end,
    -- the last water survey (lua/ai-water.lua), from the save: no scan here
    water = function()
        return safe(function()
            local w = reqscript('ai-water').last() or {none = true}
            -- a survey under way (in slices): the planner asks for the next slice
            if reqscript('ai-water').scanning() or WATER_PLAN then w.scanning = true end
            local okc, st = pcall(function() return reqscript('ai-builder').cistern_status() end)
            w.cistern_status = okc and st or nil
            return w
        end)
    end,
    logistics = function()
        return safe(function()
            local B = reqscript('ai-builder')
            local okf, feeders = pcall(B.feeder_survey)
            local oks, storage = pcall(B.storage_survey)
            local counts = {}
            pcall(function()
                counts.items = #df.global.world.items.all
                counts.units = #df.global.world.units.active
                local n, link = 0, df.global.world.jobs.list.next
                while link do n = n + 1; link = link.next end
                counts.jobs = n
            end)
            return {feeders = okf and feeders or {error = tostring(feeders):sub(1, 160)},
                    storage = oks and storage or {error = tostring(storage):sub(1, 160)},
                    counts = counts}
        end)
    end,
    map = function()
        return {
            size = {dfhack.maps.getTileSize()},
            -- add to a z-level to get the elevation the game shows on screen
            elevation_offset = df.global.world.map.region_z - 100,
            layers = safe(layers_summary),
            dwarves = safe(get_dwarf_levels),
        }
    end,
    nobles = function() return safe(get_nobles) end,
    mandates = function() return safe(get_mandates) end,
    civ_alert = function() return df.global.plotinfo.alerts.civ_alert_idx ~= 0 end,
    -- Read directly: gui/civ-alert's can_sound_alarm() creates alert
    -- entries when they're missing, and a report must not change the game.
    civ_alert_ready = function()
        return safe(function()
            local l = df.global.plotinfo.alerts.list
            return (#l >= 2 and #l[1].burrows > 0)
                or df.global.plotinfo.alerts.civ_alert_idx ~= 0
        end)
    end,
    orders = function() return safe(get_orders) end,
    -- (0.101.6) why orders don't start: the manager, his job, his office and
    -- its furniture, and each workshop's order settings
    order_desk = function() return safe(function()
        local out = {offices = {}, workshops = {}, manage_jobs = 0}
        local mgr
        for _, u in ipairs(df.global.world.units.active) do
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
        local from
        pcall(function()
            for _, u in ipairs(dfhack.units.getCitizens(true)) do
                local x, y, z = dfhack.units.getPosition(u)
                if x then from = xyz2pos(x, y, z) break end
            end
        end)
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
            for _, name in ipairs({'MASON', 'CARPENTER', 'STONECUTTER', 'WOOD_CRAFT', 'STONE_CRAFT', 'BONE_CARVE',
                                   'METAL_CRAFT', 'GLASSMAKER', 'MECHANIC'}) do
                local lab, n, free = df.unit_labor[name], 0, 0
                if lab then
                    for _, u in ipairs(dfhack.units.getCitizens(true)) do
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
    end) end,
    stone_types = function() return safe(get_stone_types) end,
    -- stone the masons may use, and the economic stone lying about
    stone_use = function() return safe(get_stone_use) end,
    locations = function() return safe(get_locations) end,
    petitions = function() return safe(get_petitions) end,
    diplomacy = function() return safe(get_diplomacy) end,
    meetings = function() return safe(get_meetings) end,
    -- (0.88) the alert icons down the left of the screen, by type (lua/ai-reports.lua)
    alerts = function() return safe(function() return reqscript('ai-reports').alerts_report() end) end,
    projects = function() return safe(function() return reqscript('ai-builder').projects_report() end) end,
    -- every AI project on record, with where it is (small: ids and boxes)
    registry = function() return safe(function() return reqscript('ai-builder').registry_report() end) end,
    farms = function() return safe(function() return reqscript('ai-builder').farms_report() end) end,
    -- (0.101) water on the surface and the crossings over it (weekly: slow, changes slowly)
    crossings = function() return safe(function() return reqscript('ai-builder').crossings_report() end) end,
    -- a fresh embark: has the fort a staircase yet (lua/ai-builder.lua found_fort)?
    founding = function()
        return safe(function()
            -- (0.100) a fort with its staircase keeps it: the scan (up to 12
            -- levels across the fort, ~12 ms a report) runs until it's found,
            -- then not again this session for that site
            local site = df.global.plotinfo.site_id
            if FOUNDED_SITE == site then return {stairs = true, near = FOUNDED_NEAR} end
            local B = reqscript('ai-builder')
            local c = B.found_center()
            local stairs = B.has_staircase()
            if stairs then FOUNDED_SITE, FOUNDED_NEAR = site, c and c.what or nil end
            return {stairs = stairs, near = c and c.what or nil}
        end)
    end,
    -- who digs: miners, picks, digging waiting (lua/ai-labor.lua)
    labor = function() return safe(function() return reqscript('ai-labor').survey() end) end,
    -- caravans, the depot and goods for it (lua/ai-trade.lua)
    trade = function() return safe(function() return reqscript('ai-trade').survey(txt) end) end,
    -- uncovered ore near the fort, by metal (lua/ai-industry.lua)
    industry = function() return safe(function() return reqscript('ai-industry').survey() end) end,
    -- the fort's offices: holders, vacancies (lua/ai-nobles.lua)
    offices = function() return safe(function() return reqscript('ai-nobles').survey(txt) end) end,
    -- the rooms the nobles' offices ask for and don't have (lua/ai-nobles.lua)
    noble_rooms = function() return safe(function() return reqscript('ai-nobles').rooms_survey(txt) end) end,
    tools = function() return safe(get_tools) end,
    -- the player's settings from the control panel (gui/ai-overseer)
    settings = function()
        return safe(function()
            local S = reqscript('ai-overseer-settings')
            return S.for_ai(S.load_settings())
        end)
    end,
    events_waiting = function() return #EVENT_QUEUE end,
    -- (0.104.7, a probe) the instruments the fort's civilisation knows (each
    -- world invents its own): parts, size, materials, and DF's instrument jobs
    instruments = function() return safe(get_instruments) end,
    -- (0.104.0) the AI's ledger, as saved with this game
    ledger = function() return safe(ledger_data) end,
    recent_announcements = function() return safe(get_recent_announcements, 15) end,
}

-- The pulse: a small report for the frequent check between full ones.
PULSE_SECTIONS = {
    'protocol', 'bridge_version', 'paused', 'fort', 'date', 'wealth', 'dwarves', 'stocks',
    'others_on_map', 'civ_alert', 'civ_alert_ready', 'orders', 'projects', 'entrances',
    'moods', 'military', 'settings', 'events_waiting', 'hazards', 'ledger',
}
TIERS = {pulse = true, daily = true, survey = true}
-- report sections rebuilt only every so many game days (the lag pass, Oct 23:
-- each full report froze the game ~0.5 s; these walk every item or stockpile)
SECTION_CACHE_DAYS = {logistics = 3, industry = 7,   -- industry: 300-450 ms live (veins and every boulder)
    -- (0.100) slow and slow-changing, read only for slow decisions: rebuilt
    -- in rotation (SECTION_REBUILDS a report, the stalest first), so no one
    -- report pays for all of them (region2: a full report froze ~250 ms)
    -- (supplies isn't cached: "have + queued" rules read it against live
    -- orders, and a stale count made them order twice; review 24 Oct)
    room_gaps = 3, needs = 1, instruments = 28, registry = 3, noble_rooms = 3, locations = 2, petitions = 2, diplomacy = 7, crossings = 7,
    missions = 1}   -- (0.104.95) every world site walked
SECTION_REBUILDS = 2       -- expired cached sections rebuilt in one report (a missing one always is)
-- (0.100) the cached sections each action changes (cleared when it succeeds)
CACHE_INVALIDATES = {
    place_in_zone = {'justice'},
    give_room = {'noble_rooms'}, appoint = {'noble_rooms'}, quick_location = {'locations'},
    add_posts = {'locations'}, staff_location = {'locations'}, vacate_post = {'locations', 'health'}, retarget_hall = {'locations', 'registry'},
    answer_petition = {'petitions', 'locations'}, petition_orders = {'petitions'},
    give_trinkets = {'needs'}, idle_crafting = {'needs'}, unload_depot = {'needs'},
    -- (review) furnishing makes the temple, hospital, offices and rooms: the
    -- rules that read locations and noble_rooms would start a second level
    start_project = {'registry'}, furnish_project = {'registry', 'locations', 'noble_rooms'},
    finish_project = {'registry', 'locations', 'noble_rooms'},
    cancel_project = {'registry', 'locations', 'noble_rooms'}, engrave_project = {'registry'},
    build_crossing = {'crossings'}, remove_crossing = {'crossings'},
    unforbid_dead = {'dead'}, allow_burial = {'dead'}, repair_rooms = {'room_gaps'},
}
SECTION_CACHE = SECTION_CACHE or {}
-- (0.104.8) a new bridge starts with an empty cache: DFHack keeps a script's
-- globals across runs, so a section cached by older code (0.104.7's
-- instruments with raw names) outlived the fix for 28 days
if SECTION_CACHE_VERSION ~= BRIDGE_VERSION then
    SECTION_CACHE = {}
    SECTION_CACHE_VERSION = BRIDGE_VERSION
end

-- tier: 'pulse' (PULSE_SECTIONS only), or 'daily' / 'survey' (everything;
-- survey is the same as daily for now). Default daily.
function build_state(include_units, tier)
    tier = tier or 'daily'
    local names
    if tier == 'pulse' then
        names = PULSE_SECTIONS
        include_units = false
    else
        names = sorted_keys(SECTIONS)
    end
    local ctx = {}
    local clock = os.clock
    local t0 = clock()
    ctx.dwarves, ctx.units = get_dwarves(include_units)
    -- how long each section takes inside the game (the lag pass, Oct 23):
    -- sections over 5 ms, kept in LAST_TIMING and the report's _timing
    local timing = {dwarves = math.floor((clock() - t0) * 1000 + 0.5)}
    local state = {}
    local now = df.global.cur_year * 403200 + df.global.cur_year_tick
    local site = df.global.plotinfo.site_id
    -- (0.100) which expired cached sections are rebuilt this time: the
    -- stalest SECTION_REBUILDS of them; the rest send their last copy a
    -- report longer (a section never built, or from another site, always is)
    local rebuild = {}
    do
        local due = {}
        for _, name in ipairs(names) do
            local days, c = SECTION_CACHE_DAYS[name], SECTION_CACHE[name]
            if days and c and c.site == site and now >= c.tick and now - c.tick >= days * 1200 then
                table.insert(due, {name = name, age = now - c.tick})
            end
        end
        table.sort(due, function(a, b) return a.age > b.age end)
        for i = 1, math.min(SECTION_REBUILDS, #due) do rebuild[due[i].name] = true end
    end
    for _, name in ipairs(names) do
        local t = clock()
        -- slow sections that change slowly are rebuilt only every few game
        -- days (SECTION_CACHE_DAYS); between, the last copy is sent
        local days, c = SECTION_CACHE_DAYS[name], SECTION_CACHE[name]
        local fresh = c and c.site == site and now >= c.tick
        if days and fresh and (now - c.tick < days * 1200 or not rebuild[name]) then
            state[name] = c.value
        else
            state[name] = SECTIONS[name](ctx)
            local v = state[name]
            if days and not (type(v) == 'table' and v.error) then   -- (an error is tried again next time)
                SECTION_CACHE[name] = {tick = now, site = site, value = v}
            end
        end
        local ms = math.floor((clock() - t) * 1000 + 0.5)
        if ms >= 5 then timing[name] = ms end
    end
    state.tier = tier
    state._timing = timing
    LAST_TIMING = timing
    return state
end

local function ensure_watching()
    if WATCHING ~= BRIDGE_VERSION then start_watching() end
end

local function cmd_status()
    if not in_fort() then
        return {ok = true, in_fort = false, world_loaded = dfhack.isWorldLoaded()}
    end
    local remaining = nil
    if run_timer_id and dfhack.timeout_active(run_timer_id) and run_until then
        remaining = math.max(0, run_until - abs_tick())
    end
    ensure_watching()
    local st = reqscript('ai-status')
    st.mark_seen()
    return {
        ok = true, in_fort = true, paused = df.global.pause_state,
        date = get_date(), run_ticks_remaining = remaining,
        events_waiting = #EVENT_QUEUE,
        -- in-game controls: the halt switch, and your answers to the co-pilot
        halted = st.is_halted(),
        decisions = st.decisions(),
        -- simulation and graphics frames per second, as DF measures them
        fps = df.global.enabler.calculated_fps,
        gfps = df.global.enabler.calculated_gfps,
        -- DF's trade screen holds time still while it's open (seen 0.58.0): the
        -- overseer trades then without waiting for the next day
        trade_open = trade_screen_open(),
    }
end

function trade_screen_open()
    local ok, v = pcall(function() return df.global.game.main_interface.trade.open end)
    return ok and v == true
end

local function cmd_state(args)
    if not in_fort() then return NOT_IN_FORT end
    ensure_watching()
    local flags = utils.invert(args)
    local include_units = not flags['--no-units']
    local tier = 'daily'
    if flags['--tier'] then
        tier = args[flags['--tier'] + 1]
        if not TIERS[tier] then return reject('--tier must be pulse, daily or survey') end
    end
    local start = os.clock()
    local state = build_state(include_units, tier)
    local built = os.clock()
    dfhack.filesystem.mkdir_recursive(OUT_DIR)
    json.encode_file(state, STATE_FILE, {pretty = false})
    -- the five slowest sections, and the time to write the file, for bridge.log
    local slow = {}
    for name, ms in pairs(state._timing or {}) do table.insert(slow, {name, ms}) end
    table.sort(slow, function(a, b) return a[2] > b[2] end)
    local top = {}
    for i = 1, math.min(6, #slow) do top[i] = slow[i][1] .. ' ' .. slow[i][2] end
    return {
        ok = true,
        file = STATE_FILE,
        build_ms = math.floor((os.clock() - start) * 1000 + 0.5),
        write_ms = math.floor((os.clock() - built) * 1000 + 0.5),
        slowest = table.concat(top, ', '),
        citizens = state.dwarves.total,
        tier = tier,
    }
end

local function cmd_pause(paused) -- only ever called with true
    if not in_fort() then return NOT_IN_FORT end
    cancel_run() -- a manual pause/unpause replaces any timed run
    df.global.pause_state = paused
    return {ok = true, paused = df.global.pause_state}
end

-- ai-bridge run <ticks>: unpause, then pause again after that many game ticks.
local function cmd_run(args)
    if not in_fort() then return NOT_IN_FORT end
    local ticks = whole_number(args[1])
    if not ticks or ticks < 1 or ticks > MAX_RUN_TICKS then
        return reject(('ticks must be a whole number from 1 to %d (1200 ticks = 1 day)'):format(MAX_RUN_TICKS))
    end
    cancel_run()
    local id = dfhack.timeout(ticks, 'ticks', function()
        df.global.pause_state = true
        run_timer_id = nil
        run_until = nil
    end)
    if not id then return {ok = false, error = 'could not start the timer'} end
    run_timer_id = id
    run_until = abs_tick() + ticks
    df.global.pause_state = false
    return {ok = true, running = true, ticks = ticks}
end

-- ai-bridge act <json>: run one action, e.g.
--   ai-bridge act {"type":"work_order","recipe":"brew_drink","amount":10}
local function cmd_act(args)
    if not in_fort() then return NOT_IN_FORT end
    local text = table.concat(args, ' ')
    local ok, action = pcall(json.decode, text)
    if not ok or type(action) ~= 'table' then
        return reject('act needs one JSON object, e.g. {"type":"tool","name":"autochop","enabled":true}')
    end
    local fn = ACTIONS[action.type]
    if not fn then
        return reject(('unknown action type: %s (known: %s)'):format(
            tostring(action.type), table.concat(sorted_keys(ACTIONS), ', ')))
    end
    -- The in-game kill switch: while halted, nothing that changes the fort
    -- gets through, whatever the overseer asks.
    -- A dry run changes nothing, so it's allowed while halted.
    local dry = (action.type == 'start_project' or action.type == 'farm_plots' or action.type == 'place_well'
                 or action.type == 'make_pasture' or action.type == 'link_lever' or action.type == 'save_game'
                 or action.type == 'quiet_announcements' or action.type == 'found_fort'
                 or action.type == 'assign_miners' or action.type == 'assign_labor'
                 or action.type == 'gather_plants' or action.type == 'trim_gathering'
                 or action.type == 'appoint'
                 or action.type == 'place_surface' or action.type == 'place_keep' or action.type == 'make_squad'
                 or action.type == 'mine_ore' or action.type == 'clear_gate' or action.type == 'bring_goods'
                 or action.type == 'unload_depot' or action.type == 'kitchen_skill' or action.type == 'place_slabs'
                 or action.type == 'give_room' or action.type == 'set_uniform' or action.type == 'adopt_uniform' or action.type == 'petition_orders'
                 or action.type == 'set_uniform_weapon' or action.type == 'allow_stone' or action.type == 'prioritize_dig'
                 or action.type == 'quarry' or action.type == 'polish' or action.type == 'trade_deal' or action.type == 'call_trader'
                 or action.type == 'open_trade' or action.type == 'close_trade'
                 or action.type == 'squad_barracks' or action.type == 'feeder_pile'
                 or action.type == 'idle_crafting' or action.type == 'give_trinkets' or action.type == 'staff_location' or action.type == 'vacate_post' or action.type == 'add_posts' or action.type == 'staff_labors'
                 or action.type == 'dismiss_alerts' or action.type == 'place_in_zone' or action.type == 'answer_petition' or action.type == 'retarget_hall'
                 or action.type == 'remove_workshops' or action.type == 'survey_water'
                 or action.type == 'cistern_step' or action.type == 'water_zone' or action.type == 'sand_zone'
                 or action.type == 'kitchen_brewables')   -- (0.100) its dry run only counts
        and action.dry_run == true
    if not DISPLAY_ONLY[action.type] and not dry and reqscript('ai-status').is_halted() then
        return {ok = false, rejected = true, halted = true, action = action.type,
                error = 'the AI is halted in the game (Ctrl-Shift-H to resume)'}
    end
    local result = fn(action)
    result.action = action.type
    -- (0.100) an action that changed what a cached section shows: built again
    -- in the next report (else e.g. a room given looked still free for days)
    if result.ok == true and not action.dry_run then
        for _, name in ipairs(CACHE_INVALIDATES[action.type] or {}) do SECTION_CACHE[name] = nil end
    end
    return result
end

-- ai-bridge watch: start the event feed (run from onMapLoad.init).
local function cmd_watch()
    if not in_fort() then return NOT_IN_FORT end
    return {ok = start_watching(), watching = WATCHING == BRIDGE_VERSION}
end

-- ai-bridge events: hand over queued events (written to a file, since unit
-- names can contain characters the console can't carry) and clear the queue.
local function cmd_events()
    if not in_fort() then return NOT_IN_FORT end
    ensure_watching()
    -- announcements (moods, tantrums, ghosts, crimes...) become events too
    local ok, found, newest = pcall(function()
        return reqscript('ai-reports').scan(LAST_REPORT_ID, txt)
    end)
    if ok then
        LAST_REPORT_ID = newest
        for _, ev in ipairs(found) do push_event(ev) end
    end
    local events = EVENT_QUEUE
    EVENT_QUEUE = {}
    dfhack.filesystem.mkdir_recursive(OUT_DIR)
    json.encode_file({events = events}, EVENTS_FILE, {pretty = false})
    return {ok = true, file = EVENTS_FILE, count = #events,
            reports_error = (not ok) and tostring(found) or nil}
end

-- ai-bridge reports: how the latest announcements would be sorted, without
-- taking anything off the event feed (for brain/selftest.py).
-- ai-bridge probe: where this DF version keeps squad data (diagnostics).
local function cmd_probe()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-military').probe() end)
    return {ok = true, probe = ok and r or tostring(r)}
end

-- ai-bridge probe_defence [x y z ...]: read-only facts milestone 5 needs from
-- this DF version before anything is built: whether the game has the job and
-- reference types a lever link uses, the building types of drawbridges,
-- hatches and traps, the fort's levers and what they are linked to, and
-- what stands on the given tiles (the blocked entrances). Changes nothing.
-- The building ids that the given items (mechanisms) point to with a
-- reference of the given type (BUILDING_TRIGGER or BUILDING_TRIGGERTARGET).
function probe_link_ids(items, ref_name)
    local ids = {}
    for _, it in ipairs(items or {}) do
        for _, ref in ipairs(it.general_refs or {}) do
            if df.general_ref_type[ref:getType()] == ref_name then table.insert(ids, ref.building_id) end
        end
    end
    return ids
end

-- DF's trade screen, read only (for automatic trading).
local function cmd_probe_trade()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-trade').probe_screen(txt) end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    r.ok = true
    return r
end

-- (0.104.97, 13b) ai-bridge probe_missions: the World screen, read only
local function cmd_probe_missions()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-missions').probe_screen() end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    r.ok = true
    return r
end

-- (0.104.129, 12i) ai-bridge probe_justice: DF's Justice screen and the
-- crimes, read only (Teacheroar: 1,571 crimes, 399 waiting for a trial, 1
-- ever sentenced; DF convicts only from that screen). The player convicts one
-- case by hand while brain/probe_justice.py --watch records it.
local function probe_plain(v)
    local tv = type(v)
    if tv == 'number' or tv == 'string' or tv == 'boolean' then return v end
    if tv == 'userdata' then
        local okn, n = pcall(function() return #v end)
        if okn and type(n) == 'number' then
            local first = {}
            for i = 0, math.min(n, 4) - 1 do
                local oke, e = pcall(function() return v[i] end)
                local te = oke and type(e)
                if te == 'number' or te == 'string' or te == 'boolean' then table.insert(first, e) end
            end
            return {n = n, first = (#first > 0) and first or nil}
        end
        local oks, s = pcall(tostring, v)
        return oks and s:sub(1, 60) or '?'
    end
    return nil
end

local function probe_fields(obj, limit)
    local out, n = {}, 0
    pcall(function()
        for k, v in pairs(obj) do
            if n >= (limit or 120) then break end
            local okv, pv = pcall(probe_plain, v)
            if okv and pv ~= nil then out[tostring(k)] = pv; n = n + 1 end
        end
    end)
    return out
end

local function cmd_probe_justice()
    if not in_fort() then return NOT_IN_FORT end
    local out = {ok = true}
    pcall(function() out.focus = dfhack.gui.getCurFocus(true) end)
    pcall(function() out.mouse = {x = df.global.gps.mouse_x, y = df.global.gps.mouse_y} end)
    pcall(function()
        local info = df.global.game.main_interface.info
        out.info = probe_fields(info, 60)
        out.justice = probe_fields(info.justice, 150)
    end)
    pcall(function()
        local list = df.global.world.crimes.all
        out.crimes = #list
        local sentenced, newest_sentenced = 0, nil
        for i = #list - 1, math.max(0, #list - 600), -1 do
            local cr = list[i]
            if cr.flags.sentenced then
                sentenced = sentenced + 1
                if not newest_sentenced then newest_sentenced = probe_fields(cr, 60) end
            end
        end
        out.sentenced = sentenced
        out.newest_sentenced = newest_sentenced
    end)
    pcall(function() out.punishments = #df.global.plotinfo.punishments end)
    return out
end

-- The defence test (brain/defence_test.py): hostile invaders set down
-- outside. args: count race [--dry]
local function cmd_test_threat(args)
    if not in_fort() then return NOT_IN_FORT end
    -- (0.100, security pass) real invaders: never while the AI is halted
    if reqscript('ai-status').is_halted() then
        return {ok = false, rejected = true, error = 'the AI is halted (the switch in the game): no test invaders'}
    end
    local flags = utils.invert(args or {})
    local n = tonumber((args or {})[1]) or 3
    local race = (args or {})[2]
    if race and (race:sub(1, 2) == '--' or not race:match('^[A-Z_]+$')) then race = nil end
    local r = reqscript('ai-military').spawn_test_threat(n, race, flags['--dry'] ~= nil)
    if r.ok == false and r.rejected then r.ok = true; r.refused = r.error; r.error = nil end
    return r
end

-- The mouse is on one of the trade screen's buttons: remember where.
local function cmd_trade_here(args)
    if not in_fort() then return NOT_IN_FORT end
    local name = (args or {})[1] or 'Trade'
    if name ~= 'Trade' and name ~= 'Depot' then return {ok = false, error = 'buttons: Trade, Depot'} end
    return reqscript('ai-trade').calibrate(name)
end

-- Press the Trade button on the open screen (what's ticked is traded).
local function cmd_trade_press()
    if not in_fort() then return NOT_IN_FORT end
    if reqscript('ai-status').is_halted() then return {ok = false, error = 'the AI is halted in the game'} end
    local r = reqscript('ai-trade').press('Trade', txt)
    if r.ok == false and r.rejected then r.ok = true; r.refused = r.error; r.error = nil end
    return r
end

-- What soldiers' uniforms ask for, what's assigned to them, what they carry.
local function cmd_probe_squads()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-military').probe_squads(txt) end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    return {ok = true, soldiers = r}
end

local function cmd_probe_occupations()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-society').probe_occupations(txt) end)
    if not ok then return {ok = false, error = tostring(r):sub(1, 300)} end
    r.ok = true
    return r
end

local function cmd_probe_defence(args)
    if not in_fort() then return NOT_IN_FORT end
    local out = {}
    local function has_enum(enum, name)
        local ok, v = pcall(function() return enum[name] end)
        return ok and v ~= nil
    end
    out.job_types = {}
    for _, n in ipairs({'LinkBuildingToTrigger', 'PullLever', 'ConstructHatchCover', 'ConstructMechanisms'}) do
        out.job_types[n] = has_enum(df.job_type, n)
    end
    out.ref_types = {}
    for _, n in ipairs({'BUILDING_TRIGGER', 'BUILDING_TRIGGERTARGET', 'BUILDING_HOLDER'}) do
        out.ref_types[n] = has_enum(df.general_ref_type, n)
    end
    out.job_roles = {}
    for _, n in ipairs({'job_role_type', 'job_item_ref.T_role'}) do
        local ok, v = pcall(function()
            local e = n == 'job_role_type' and df.job_role_type or df.job_item_ref.T_role
            return e ~= nil and e.LinkToTarget ~= nil and e.LinkToTrigger ~= nil
        end)
        out.job_roles[n] = ok and v or false
    end
    out.building_types = {}
    for _, n in ipairs({'Bridge', 'Hatch', 'Trap', 'Door', 'Floodgate', 'GrateFloor', 'BarsFloor'}) do
        out.building_types[n] = has_enum(df.building_type, n)
    end
    out.trap_types = {}
    for _, n in ipairs({'Lever', 'CageTrap', 'StoneFallTrap', 'WeaponTrap', 'TrackStop', 'PressurePlate'}) do
        out.trap_types[n] = has_enum(df.trap_type, n)
    end
    out.buildings_api = {}
    for _, n in ipairs({'constructBuilding', 'deconstruct', 'markedForRemoval', 'findAtTile', 'getSize'}) do
        out.buildings_api[n] = type(dfhack.buildings[n]) == 'function'
    end
    out.job_api = {}
    for _, n in ipairs({'linkIntoWorld', 'attachJobItem', 'addGeneralRef'}) do
        out.job_api[n] = type(dfhack.job[n]) == 'function'
    end
    local wanted = {}
    -- what stands on the given tiles
    out.tiles = {}
    for i = 1, #args - 2, 3 do
        local x, y, z = tonumber(args[i]), tonumber(args[i + 1]), tonumber(args[i + 2])
        if x and y and z then
            local t = {x = x, y = y, z = z}
            local ok_t, err_t = pcall(function()
                local b = dfhack.buildings.findAtTile(x, y, z)
                if b then
                    local bt = b:getType()
                    t.building = df.building_type[bt]
                    t.id = b.id
                    t.size = {b.x2 - b.x1 + 1, b.y2 - b.y1 + 1}
                    if bt == df.building_type.Bridge then t.direction = b.direction end
                    if bt == df.building_type.Trap then t.trap = df.trap_type[b.trap_type] end
                    local mechs = {}
                    for _, ci in ipairs(b.contained_items or {}) do table.insert(mechs, ci.item) end
                    t.levers = probe_link_ids(mechs, 'BUILDING_TRIGGER')
                    for _, lid in ipairs(t.levers) do wanted[lid] = true end
                    t.linked = #t.levers > 0
                end
                local tt = dfhack.maps.getTileType(x, y, z)
                t.shape = tt and df.tiletype_shape[df.tiletype.attrs[tt].shape] or nil
                local des = dfhack.maps.getTileFlags(x, y, z)
                if des and des.flow_size > 0 then
                    t.liquid = (des.liquid_type == true or des.liquid_type == 1) and 'magma' or 'water'
                    t.depth = des.flow_size
                end
            end)
            if not ok_t then t.error = tostring(err_t) end
            table.insert(out.tiles, t)
        end
    end
    -- the levers, and what each is linked to. A link lives on the
    -- mechanisms: the lever keeps its linked mechanisms, each with a
    -- BUILDING_TRIGGERTARGET reference to the bridge or door it works; the
    -- target holds a mechanism with a BUILDING_TRIGGER reference back to the
    -- lever (DF 53.16: the lever's linked mechanisms sit in the targets and
    -- carry a BUILDING_HOLDER reference to them). Levers named "AI gate" and
    -- levers working a probed tile come first, then the rest (at most 40).
    out.levers = {}
    out.levers_total = 0
    local ok_l, err_l = pcall(function()
        local named, working, others = {}, {}, {}
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever then
                out.levers_total = out.levers_total + 1
                local name = txt(b.name) or ''
                local targets = {}
                local tids = probe_link_ids(b.linked_mechanisms, 'BUILDING_HOLDER')
                if #tids == 0 then tids = probe_link_ids(b.linked_mechanisms, 'BUILDING_TRIGGERTARGET') end
                for _, tid in ipairs(tids) do
                    local tb = df.building.find(tid)
                    table.insert(targets, {id = tid, type = tb and df.building_type[tb:getType()] or '?'})
                end
                local e = {id = b.id, name = name, x = b.centerx, y = b.centery, z = b.z,
                           targets = targets, mechanisms = #b.linked_mechanisms,
                           pending = #b.jobs > 0}
                table.insert(name:lower() == 'ai gate' and named or wanted[b.id] and working or others, e)
            end
        end
        for _, e in ipairs(named) do table.insert(out.levers, e) end
        for _, e in ipairs(working) do table.insert(out.levers, e) end
        for _, e in ipairs(others) do
            if #out.levers >= 40 then break end
            table.insert(out.levers, e)
        end
    end)
    if not ok_l then out.levers_error = tostring(err_l) end
    return {ok = true, probe = out}
end

local function cmd_reports()
    if not in_fort() then return NOT_IN_FORT end
    local R = reqscript('ai-reports')
    local list = df.global.world.status.announcements
    local merged = R.merge(list, #list, function(t) return df.announcement_type[t] or tostring(t) end, txt)
    local out = {}
    for i = math.max(1, #merged - 39), #merged do
        local a = merged[i]
        table.insert(out, {type = a.type, topic = R.classify(a.type, a.text) or false,
                           text = (a.text or ''):sub(1, 100)})
    end
    return {ok = true, reports = out}
end

-- ai-bridge map: the layer summary on its own (cheap after the first call).
local function cmd_map()
    if not in_fort() then return NOT_IN_FORT end
    local x, y, z = dfhack.maps.getTileSize()
    return {ok = true, size = {x, y, z}, layers = layers_summary()}
end

-- These only change what's displayed, so they still work while halted.
-- (save_memory is the AI's own bookkeeping, not a change to the fort.)
DISPLAY_ONLY = {report_status = true, set_culture = true, set_learned = true, save_memory = true,
                ledger_set = true}

-- ai-bridge memory: hand the memory stored in the save to the overseer, as
-- {kinds = {working = {fort, text}, ...}, legacy = <old single table>}.
local function cmd_memory(args)
    if not in_fort() then return NOT_IN_FORT end
    local out, present = {kinds = {}}, false
    -- (0.104.62) raw files only for a brain that asks (`memory raw`): an older
    -- one would take the raw JSON for the text
    local want_raw = type(args) == 'table' and args[1] == 'raw'
    for _, kind in ipairs(MEMORY_KINDS) do
        -- (0.104.62) a long kind goes to a file as the save keeps it, JSON
        -- text, undecoded: DFHack's Lua JSON decoder took 14 s on Enxah's
        -- 200 KB at each keeper start, the game frozen meanwhile; Python reads it
        local raw_file
        pcall(function()
            local okr, raw = pcall(dfhack.persistent.getSiteDataString, MEMORY_KIND_PREFIX .. kind)
            if want_raw and okr and type(raw) == 'string' and #raw > 20000 and raw:sub(1, 1) == '{' then
                dfhack.filesystem.mkdir_recursive(OUT_DIR)
                local path = OUT_DIR .. '/memory-from-save.' .. kind .. '.json'
                local f = io.open(path, 'wb')
                if f then f:write(raw) f:close() raw_file = path end
            end
        end)
        local ok, v
        if raw_file then
            ok, v = true, nil
            out.kinds[kind] = {raw = raw_file}
            present = true
        else
            ok, v = pcall(dfhack.persistent.getSiteData, MEMORY_KIND_PREFIX .. kind, nil)
        end
        if ok and type(v) == 'table' and type(v.text) == 'string' then
            -- (0.104.44) a long text goes to a file of its own as it is: the
            -- Lua JSON encoder took 9.5 s on Enxah's 200 KB (over the 10 s
            -- limit, so from 08:36 the save's memory was never read or written)
            local file
            if #v.text > 20000 then
                pcall(function()
                    dfhack.filesystem.mkdir_recursive(OUT_DIR)
                    local path = OUT_DIR .. '/memory-from-save.' .. kind .. '.txt'
                    local f = io.open(path, 'wb')
                    if f then f:write(v.text) f:close() file = path end
                end)
            end
            out.kinds[kind] = file and {fort = v.fort, file = file} or {fort = v.fort, text = v.text}
            present = true
        end
    end
    local ok, legacy = pcall(dfhack.persistent.getSiteData, MEMORY_KEY, nil)
    -- a table without .fort is the "dropped" marker, not memory
    if ok and type(legacy) == 'table' and legacy.fort ~= nil then
        out.legacy = legacy
        present = true
    end
    if not present then return {ok = true, present = false} end
    if next(out.kinds) == nil then out.kinds = nil end -- (an empty table would encode as [])
    dfhack.filesystem.mkdir_recursive(OUT_DIR)
    json.encode_file(out, MEMORY_FROM_SAVE, {pretty = false})
    return {ok = true, present = true, file = MEMORY_FROM_SAVE}
end

-- ai-bridge survey: the staircases, the dwarves' busiest level and the levels
-- with soil, as elevations, for the overseer's master plan. Read-only.
local function cmd_survey()
    if not in_fort() then return NOT_IN_FORT end
    local ok, r = pcall(function() return reqscript('ai-builder').survey() end)
    if not ok or type(r) ~= 'table' then return {ok = false, error = 'survey failed: ' .. tostring(r)} end
    return r
end

-- ai-bridge halt [on|off|toggle]: the kill switch (Ctrl-Shift-H in game).
local function cmd_halt(args)
    if not in_fort() then return NOT_IN_FORT end
    local st = reqscript('ai-status')
    local arg = args[1] or 'toggle'
    local now = st.is_halted()
    if arg == 'on' then now = st.set_halted(true)
    elseif arg == 'off' then now = st.set_halted(false)
    elseif arg == 'toggle' then now = st.set_halted(not now)
    elseif arg ~= 'show' then return reject('use: ai-bridge halt on|off|toggle|show') end
    return {ok = true, halted = now}
end

-- ai-bridge assumptions: every game name and DFHack call the AI relies on,
-- checked in this DF and DFHack (read-only). Each round of fixes so far
-- found a guess about DF 53 that was wrong (a work detail's field name, a
-- stock's name); this lists them before a run instead of during one.
ASSUMPTIONS = {
    -- enums and job types
    'df.job_type.LinkBuildingToTrigger', 'df.job_type.MakeChain', 'df.job_type.ConstructMechanisms',
    'df.unit_labor.MINE', 'df.unit_labor.CUTWOOD', 'df.unit_labor.HERBALIST', 'df.unit_labor.FISH',
    'df.unit_labor.PLANT', 'df.job_skill.MINING', 'df.job_skill.AXE', 'df.job_skill.HERBALISM',
    'df.work_detail_icon_type.MINERS', 'df.work_detail_icon_type.PLANT_GATHERERS',
    'df.work_detail_icon_type.FISHERMEN', 'df.work_detail_icon_type.PLANTERS',
    'df.work_detail_mode.OnlySelectedDoesThis', 'df.work_detail_mode.EverybodyDoesThis',
    'df.tiletype_shape.SHRUB', 'df.tiletype_shape.STAIR_UPDOWN', 'df.tiletype_material.TREE',
    'df.tiletype_material.GRASS_LIGHT', 'df.tile_dig_designation.Default', 'df.tile_dig_designation.Channel',
    'df.civzone_type.Pen', 'df.civzone_type.Tomb', 'df.building_type.Wagon', 'df.building_type.Hatch',
    'df.building_type.Well', 'df.building_type.FarmPlot', 'df.building_type.Bridge',
    'df.workshop_type.Fishery', 'df.workshop_type.Mechanics', 'df.workshop_type.Clothiers',
    'df.general_ref_type.BUILDING_HOLDER', 'df.general_ref_type.BUILDING_TRIGGER',
    'df.general_ref_type.BUILDING_CIVZONE_ASSIGNED',
    -- game state the AI reads or writes
    'df.global.plotinfo.labor_info.work_details', 'df.global.plotinfo.main.autosave_request',
    'df.global.world.status.popups', 'df.global.d_init.announcements.flags',
    'df.global.enabler.calculated_fps', 'df.global.plotinfo.alerts.list', 'df.global.plotinfo.burrows.list',
    'df.global.world.manager_orders.all', 'df.global.world.mandates.all',
    'df.global.world.items.other.TRAPPARTS', 'df.global.world.items.other.CHAIN',
    'df.global.world.items.other.PLANT_GROWTH', 'df.global.world.items.other.FISH_RAW',
    -- fields on real objects (checked on the first one the fort has)
    'DETAIL.flags.mode', 'DETAIL.icon', 'DETAIL.assigned_units', 'DETAIL.allowed_labors',
    'UNIT.status.labors', 'UNIT.military.squad_id', 'UNIT.job', 'UNIT.status.current_soul',
    'TILE.subterranean', 'TILE.outside', 'TILE.dig', 'TILE.flow_size', 'TILE.hidden',
    -- DFHack calls
    'dfhack.units.setAutomaticProfessions', 'dfhack.units.getNoblePositions', 'dfhack.units.getCitizens',
    'dfhack.military.makeSquad', 'dfhack.military.addToSquad', 'dfhack.items.getHolderUnit',
    'dfhack.buildings.findCivzonesAt', 'dfhack.maps.getTileFlags', 'dfhack.persistent.getSiteData',
    'UTILS.insert_sorted', 'QUICKFORT.apply_blueprint',
    -- appointing (lua/ai-nobles.lua)
    'df.histfig_entity_link_positionst', 'df.history_event_add_hf_entity_linkst',
    'df.histfig_entity_link_type.POSITION', 'df.global.hist_event_next_id', 'df.global.world.history.events',
    'df.global.plotinfo.group_id', 'ENTITY.positions.own', 'ENTITY.positions.assignments',
    'FIGURE.entity_links',
    -- squads (lua/ai-military.lua make_squad)
    'df.uniform_category._last_item', 'df.squad_uniform_spec', 'df.histfig_entity_link_squadst',
    'df.trap_type.Lever', 'UNIT.owned_buildings', 'dfhack.buildings.setOwner', 'dfhack.items.setOwner', 'dfhack.items.getOwner', 'dfhack.buildings.deconstruct', 'df.building_floodgatest', 'dfhack.maps.getBlock', 'df.viewscreen_titlest', 'df.need_type', 'df.building_def', 'dfhack.maps.getTileBiomeRgn', 'dfhack.maps.getRegionBiome', 'df.world_geo_biome', 'df.global.plotinfo.economic_stone', 'df.global.world.raws.itemdefs.weapons', 'df.uniform_category.weapon', 'dfhack.job.removeJob', 'df.general_ref_unit_workerst', 'ENTITY.uniforms', 'df.civzone_type.Office', '(dfhack.translation and dfhack.translation.translateName) or dfhack.TranslateName', 'df.global.squad_next_id', 'df.civzone_type.SandCollection', 'df.job_type.CollectSand', 'df.job_type.MakeWindow', 'df.furnace_type.GlassFurnace',
    -- captains' posts added by the AI (lua/ai-military.lua add_post, 0.81)
    'df.entity_position_assignment', 'ENTITY.positions.next_assignment_id', 'ENTITY.squads',
    'ENTITY.positions.assignments_by_type',
    -- staffing locations (lua/ai-society.lua staff_location, 0.84)
    'df.occupation_type.DOCTOR', 'df.occupation_type.SCRIBE', 'df.occupation_type.TAVERN_KEEPER', 'UNIT.occupations',
    'df.occupation', 'df.global.occupation_next_id', 'df.global.world.occupations.all',
    -- petitions (0.87)
    'df.global.plotinfo.petitions', 'df.agreement', 'df.agreement_details_type.Residency',
    'df.global.standing_orders_petition_citizenship', 'df.global.standing_orders_petition_resident_performer',
    'df.history_event_reason',
    -- the kiln and paper chains (0.86)
    'df.improvement_type.WRITING', 'df.global.world.items.other.SHEET', 'df.global.world.items.other.POWDER_MISC',
    'df.global.world.items.other.CORPSEPIECE', 'df.furnace_type.Kiln',
    'df.job_skill.DIAGNOSE', 'df.job_skill.SET_BONE', 'df.job_skill.WRITING', 'dfhack.units.getNominalSkill',
    -- ore (lua/ai-industry.lua)
    'df.block_square_event_mineralst', 'dfhack.maps.getTileAssignment', 'dfhack.maps.getWalkableGroup',
    'df.global.world.raws.inorganics', 'df.furnace_type.Smelter', 'df.furnace_type.WoodFurnace',
    'df.workshop_type.MetalsmithsForge',
    -- taking down a mistaken gate (lua/ai-gates.lua clear_gate)
    'dfhack.constructions.designateRemove', 'dfhack.constructions.findAtTile', 'dfhack.buildings.deconstruct',
    'dfhack.buildings.findAtTile', 'TILE.subterranean',
    -- trade (lua/ai-trade.lua)
    'df.global.plotinfo.caravans', 'df.caravan_state.T_trade_state.AtDepot', 'dfhack.items.markForTrade',
    'df.global.world.buildings.other.TRADE_DEPOT', 'df.building_item_role_type.TEMP', 'dfhack.maps.canWalkBetween',
    -- the logs folder of a copied save
    'df.global.world.world_data.name',
    -- (0.88) the alert icons, the bags, furniture into a zone
    'df.global.world.status.announcement_alert', 'df.announcement_alert_type.DEATH', 'df.report.find',
    -- (0.104.78) pointers: empty (nil) unless an alert is being looked at, so '?' = a nil value is fine,
    -- only an unknown field fails (they were reported missing every day)
    '?df.global.game.main_interface.announcement_alert.viewing_alert', '?df.global.game.main_interface.current_hover_alert',
    '?df.global.game.main_interface.hover_announcement_alert', 'df.global.world.items.other.SEEDS',
    'df.global.world.items.other.TRACTION_BENCH', 'dfhack.items.getContainer', 'dfhack.buildings.containsTile',
    'df.building_type.TractionBench', 'df.global.world.items.other.BAG',
    -- (0.89) location petitions, dedications
    'df.agreement.get_vector', 'df.agreement_details_type.Location', 'df.religious_practice_type.WORSHIP_HFID',
    'df.abstract_building_templest', 'df.abstract_building_guildhallst', 'df.global.plotinfo.site_id',
    'df.global.plotinfo.trees_removed', 'df.global.plotinfo.main.custom_difficulty.tree_fell_count',
    'df.global.world.items.other.STATUE', 'df.global.plotinfo.civ_id',
    'df.global.plotinfo.activities', 'df.global.plotinfo.dip_meeting_info', 'df.global.plotinfo.dipscript_popups', 'df.meeting_topic', 'df.diplomacy_state_type.Peace', 'df.historical_entity_type.Civilization',
}

local function cmd_assumptions()
    if not in_fort() then return NOT_IN_FORT end
    local env = {df = df, dfhack = dfhack}
    pcall(function() env.UTILS = require('utils') end)
    env.REACTION = function(code) return reaction_exists(code) or nil end
    env.COKE = function(stone) return coke_reaction(stone) end
    pcall(function() env.QUICKFORT = reqscript('quickfort') end)
    pcall(function() env.DETAIL = df.global.plotinfo.labor_info.work_details[0] end)
    pcall(function() env.UNIT = dfhack.units.getCitizens()[1] or dfhack.units.getCitizens()[0] end)
    pcall(function() env.ENTITY = df.historical_entity.find(df.global.plotinfo.group_id) end)
    pcall(function() env.FIGURE = df.historical_figure.find(env.UNIT.hist_figure_id) end)
    pcall(function()
        local u = env.UNIT
        env.TILE = dfhack.maps.getTileFlags(u.pos.x, u.pos.y, u.pos.z)
    end)
    -- every work order recipe's job type and every stock's item list
    local list = {}
    for _, a in ipairs(ASSUMPTIONS) do table.insert(list, a) end
    for name, r in pairs(ORDER_RECIPES) do
        if type(r) == 'table' and r.job then table.insert(list, 'df.job_type.' .. r.job .. ' (recipe ' .. name .. ')') end
        if type(r) == 'table' and r.reaction then
            table.insert(list, 'REACTION("' .. r.reaction .. '") (recipe ' .. name .. ')')
        end
        if type(r) == 'table' and r.reaction_find then
            table.insert(list, 'COKE("' .. r.reaction_find .. '") (recipe ' .. name .. ')')
        end
    end
    for _, cat in ipairs(STOCK_CATEGORIES) do table.insert(list, 'df.items_other_id.' .. cat[2]) end
    local failed, passed = {}, 0
    for _, a in ipairs(list) do
        local expr = a:gsub(' %(.*%)$', '')
        local nil_ok = expr:sub(1, 1) == '?'
        if nil_ok then expr = expr:sub(2) end
        local holder = expr:match('^(%u+)%.')
        local ok, v = pcall(function()
            if holder and env[holder] == nil then error(holder:lower() .. ' not found in this fort') end
            local fn = load('return ' .. expr, a, 't', env)
            return fn()
        end)
        if ok and (v ~= nil or nil_ok) then passed = passed + 1
        else table.insert(failed, a .. (ok and ': missing' or (': ' .. tostring(v):gsub('^.-:%d+: ', '')))) end
    end
    table.sort(failed)
    -- (ok: the check ran; a failed list comes back as data, not an error)
    return {ok = true, all_found = #failed == 0, passed = passed, failed = failed}
end

local COMMANDS = {
    halt = cmd_halt,
    memory = cmd_memory,
    survey = cmd_survey,
    watch = cmd_watch,
    events = cmd_events,
    reports = cmd_reports,
    probe = cmd_probe,
    probe_defence = cmd_probe_defence,
    probe_squads = cmd_probe_squads,
    probe_occupations = cmd_probe_occupations,
    probe_trade = cmd_probe_trade,
    probe_missions = cmd_probe_missions,
    probe_justice = cmd_probe_justice,
    trade_here = cmd_trade_here,
    test_threat = cmd_test_threat,
    trade_press = cmd_trade_press,
    assumptions = cmd_assumptions,
    map = cmd_map,
    version = function() return version_info() end,
    status = cmd_status,
    state = cmd_state,
    pause = function() return cmd_pause(true) end,
    run = cmd_run,
    act = cmd_act,
}

local function main(args)
    local name = table.remove(args, 1) or 'version'
    local fn = COMMANDS[name]
    if not fn then
        return {ok = false, error = ('unknown command: %s (known: %s)'):format(
            tostring(name), table.concat(sorted_keys(COMMANDS), ', '))}
    end
    local ok, result = xpcall(fn, debug.traceback, args)
    if not ok then
        return {ok = false, error = tostring(result)}
    end
    return result
end

if dfhack_flags.module then
    return
end

print(json.encode(main({...}), {pretty = false}))
