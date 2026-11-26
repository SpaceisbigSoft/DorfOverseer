-- ai-bridge-report-fort: the report's moods, society, buildings, jobs, layers, health,
-- the hospital survey and justice.
--
-- A part of ai-bridge.lua (r6, split out of ai-bridge-report.lua when it was 194 KB),
-- loaded by it after ai-bridge-report into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-report files share with this one come from REPORT_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-report-fort is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report-fort'] = '0.105.125'   -- bumped with BRIDGE_VERSION

local utils = require('utils')
local inc = REPORT_PART_LOCALS.inc

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
                -- (0.105.99) DF's thirst counter: a moody dwarf drinks nothing till the
                -- artifact is made (B, 24 Nov: Edzul died of thirst on day 43 of a mood)
                pcall(function() e.thirst = u.counters2.thirst_timer end)
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
    if okp and cap then
        out.pop_cap, out.strict_pop_cap = cap.cap, cap.strict
        out.baby_cap, out.baby_pct = cap.baby_cap, cap.baby_pct      -- (item5)
    end
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
    -- (r9, A7 2) the evil weather's keep-in: its members, and its guard run
    -- here at every report (thirsty or hungry let out; no keep-in call for a
    -- day: everyone out), so a brain that lost the spell's memory lets out strays
    local okw, wk = pcall(soc.weather_keep_in_status, txt)
    if okw and wk then out.weather_keep_in = wk
    elseif not okw then out.weather_keep_in = {error = tostring(wk):sub(1, 160)} end
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
        trap_kinds = {}, ai_levers = 0,   -- (0.105.46) Trap buildings by df.trap_type; the AI's levers
    }
    local tables = {}
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
                if t == df.building_type.Table then table.insert(tables, b) end   -- (0.105.51)
                -- (0.105.46) a lever is a Trap building (trap_type Lever), so
                -- `other` had no "Lever" and the scorecard read 0 levers:
                -- traps by kind, and the AI's own levers (named "AI ...",
                -- not the player's "AI gate" for the AI to work)
                if t == df.building_type.Trap then
                    pcall(function()
                        local kind = df.trap_type[b.trap_type] or tostring(b.trap_type)
                        inc(out.trap_kinds, kind)
                        if kind == 'Lever' then
                            local n = tostring(b.name or ''):lower()
                            if n:find('^ai ') and n ~= 'ai gate' then out.ai_levers = out.ai_levers + 1 end
                        end
                    end)
                end
            end
        end
    end
    -- (0.105.51, R3 fort B) where the tables stand: B had 29 tables for 83
    -- dwarves and 6 of them in its one dining hall (the rest in offices,
    -- nobles' dining rooms, the hospital), LackTables the worst stress, and the
    -- AI counted all 29. hall: in a dining hall nobody owns; meeting: in a
    -- meeting hall or tavern zone nobody owns; owned: in a zone a unit owns
    -- (a noble's dining room, an office); other: anywhere else. Each table
    -- once. halls: the dining hall zones nobody owns, and of them with a table.
    pcall(function()
        local d = {hall = 0, meeting = 0, owned = 0, other = 0, halls = 0, halls_with_tables = 0, owned_halls = 0}
        local per = {}
        for _, b in ipairs(tables) do
            local kind = 'other'
            pcall(function()
                for _, z in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(b.x1, b.y1, b.z)) or {}) do
                    local zt = df.civzone_type[z.type]
                    local owned = z.assigned_unit_id ~= -1
                    if owned then kind = 'owned' break
                    elseif zt == 'DiningHall' then kind = 'hall'; per[z.id] = (per[z.id] or 0) + 1
                    elseif zt == 'MeetingHall' and kind == 'other' then kind = 'meeting' end
                end
            end)
            d[kind] = d[kind] + 1
        end
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == df.building_type.Civzone and df.civzone_type[b.type] == 'DiningHall' then
                if b.assigned_unit_id == -1 then
                    d.halls = d.halls + 1
                    if per[b.id] then d.halls_with_tables = d.halls_with_tables + 1 end
                else
                    d.owned_halls = d.owned_halls + 1
                end
            end
        end
        out.dining = d
    end)
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

-- (r1g9) the world and the site (ai-util fort_id), not the save folder DF's
-- seasonal autosave renames (the layers were walked again every season)
local function layer_cache_key()
    local x, y, z = dfhack.maps.getTileSize()
    local okf, fort = pcall(function() return reqscript('ai-util').fort_id() end)
    if not okf or type(fort) ~= 'string' then
        fort = tostring(df.global.world.cur_savegame.save_dir) .. '#' .. tostring(df.global.plotinfo.site_id)
    end
    return ('%s:%d:%d:%d'):format(fort, x, y, z)
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
                    -- (item7) and beds, at any stage (one placed waits for its bed)
                    pcall(function()
                        local n = 0
                        for _, b in ipairs(df.global.world.buildings.other.BED) do
                            if b.z == z.z and b.centerx >= z.x1 and b.centerx <= z.x2
                                    and b.centery >= z.y1 and b.centery <= z.y2 then
                                n = n + 1
                            end
                        end
                        ze.beds_planned = n
                    end)
                    table.insert(e.zones, ze)
                end
            end
            -- (R30c item24) a post holder's labours given back here, before they are
            -- read: DIAGNOSE, SURGERY and BONE_SETTING are in no work detail (only
            -- Orderlies, everybody, holds SUTURING and DRESSING_WOUNDS: probed in A, B
            -- and F, 25 Nov), so a recompute of the dwarf's details takes them off
            -- again; the staff rule asked for them every minute (A 63 staff_labors in
            -- 3 h, all "given", and 2-7 a fort refused "every post holder has the
            -- labours", on again by the time it ran). A member of the recreation
            -- burrow keeps them off (its labours are off on purpose): marked.
            local okso, SOC = pcall(reqscript, 'ai-society')
            local okrm, rec = pcall(function() return reqscript('ai-labor').rec_member_ids() end)
            if not okrm or type(rec) ~= 'table' then rec = {} end
            for _, o in ipairs(loc.occupations) do
                local u = o.unit_id ~= -1 and df.unit.find(o.unit_id)
                if u then
                    local post = df.occupation_type[o.type]
                    if rec[u.id] then
                        e.recreation = (e.recreation or 0) + 1
                    elseif okso and type(SOC) == 'table' and SOC.give_post_labors then
                        local okg, added = pcall(SOC.give_post_labors, u, post)
                        if okg and type(added) == 'table' and #added > 0 then
                            e.relabored = (e.relabored or 0) + #added
                        end
                    end
                    local st = {post = post, labors = {}, unit_id = u.id, recreation = rec[u.id] or nil}
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

-- (item5) A punishment's convict as a unit: the field is a unit in the
-- df-structures this was written against, an id in some others.
function punished_unit(pu)
    local c = pu.criminal
    if type(c) == 'number' then return c >= 0 and df.unit.find(c) or nil end
    return c
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
    -- (item5) the citizens serving time, and how thirsty: a prisoner gets
    -- water only from a well or a water zone (Hammerstirred, no well: 9 office
    -- holders, jailed for a mandate nobody met, died of thirst in their chains)
    pcall(function()
        out.prisoners = {}
        for _, pu in ipairs(df.global.plotinfo.punishments) do
            if (pu.prison_counter or 0) > 0 and #out.prisoners < 20 then
                local u = punished_unit(pu)
                if u and not dfhack.units.isDead(u) then
                    local th = 0
                    pcall(function() th = u.counters2.thirst_timer end)
                    table.insert(out.prisoners, {id = u.id, name = txt(dfhack.units.getReadableName(u)),
                                                 thirst = th, days = pu.prison_counter})
                end
            end
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

-- (r10 p1, Phase 12b) DF's petition standing orders, reached where DFHack's
-- names miss them. In DFHack 53.17-r1 (df-structures 611369f, the same commit
-- at the 53.17-r1 tag and on master) df.game_v.xml declares the six globals as
-- standing_orders_petition_* (original-name standingorder_petition_*), and
-- DFHack binds a global by that name (DataStatics.cpp INIT_GLOBAL_FUNCTION_ITEM,
-- VersionInfo::getAddress). symbols.xml's win64 tables (STEAM, ITCH, CLASSIC)
-- list these six under DF's own names, standingorder_petition_*, so on Windows
-- df.global.standing_orders_petition_* reads "global address not known": every
-- fort's `orders: []`. The linux64 tables use DFHack's names. The fix: when
-- DFHack's name has no address and DF's name has one, bind DFHack's name to it
-- (dfhack.internal.setAddress, LuaApi.cpp: it sets the global's pointer, so
-- df.global reads and writes it). Guards: each address within
-- PETITION_ORDER_NEAR bytes of standing_orders_auto_collect_webs (a standing
-- order DFHack binds by name on every platform: 2-21 bytes away in all five
-- 53.17 tables), six different addresses, and each byte reads 0 or 1 once
-- bound; otherwise unbound again and left alone. Tried once a session.
PETITION_ORDER_SYMBOLS = {
    performer = 'standingorder_petition_resident_performer', scholar = 'standingorder_petition_resident_scholar',
    monster_hunter = 'standingorder_petition_resident_monster_hunter',
    mercenary = 'standingorder_petition_resident_mercenary', sanctuary = 'standingorder_petition_resident_sanctuary',
    citizenship = 'standingorder_petition_citizenship',
}
PETITION_ORDER_ANCHOR = 'standing_orders_auto_collect_webs'
PETITION_ORDER_NEAR = 128
PETITION_BIND = PETITION_BIND or nil       -- {via = 'names'|'symbols'|nil, why = ...}, once a session

function petition_orders_bind()
    if PETITION_BIND then return PETITION_BIND.via, PETITION_BIND.why end
    local I = dfhack.internal
    local via, why, bound_now
    local ok, err = pcall(function()
        if type(I) ~= 'table' or not I.getAddress or not I.setAddress then why = 'no dfhack.internal'; return end
        local todo, mine = {}, 0
        for _, k in ipairs(PETITION_ORDERS) do
            local a = I.getAddress(petition_order_name(k))
            if a == nil then table.insert(todo, k)
            elseif a == I.getAddress(PETITION_ORDER_SYMBOLS[k]) then mine = mine + 1 end   -- bound by an earlier load
        end
        if #todo == 0 then via = (mine > 0) and 'symbols' or 'names'; return end
        local anchor = I.getAddress(PETITION_ORDER_ANCHOR)
        if not anchor then why = PETITION_ORDER_ANCHOR .. ' has no address'; return end
        -- (r10 v12) no two orders on one byte, none on the anchor itself, the
        -- ones already bound included
        local addrs, seen = {}, {[anchor] = true}
        for _, k in ipairs(PETITION_ORDERS) do
            local b = I.getAddress(petition_order_name(k))
            if b ~= nil then
                if seen[b] then why = 'two petition orders share an address'; return end
                seen[b] = true
            end
        end
        for _, k in ipairs(todo) do
            local a = I.getAddress(PETITION_ORDER_SYMBOLS[k])
            if not a then why = 'no address for ' .. PETITION_ORDER_SYMBOLS[k]; return end
            if math.abs(a - anchor) > PETITION_ORDER_NEAR then why = PETITION_ORDER_SYMBOLS[k] .. ' is not by the other standing orders'; return end
            if seen[a] then why = 'two petition orders share an address'; return end
            seen[a], addrs[k] = true, a
        end
        bound_now = addrs                       -- (r10 v12) unbound again if anything below raises
        for k, a in pairs(addrs) do I.setAddress(petition_order_name(k), a) end
        for k in pairs(addrs) do
            local okv, v = pcall(function() return df.global[petition_order_name(k)] end)
            if not okv or (v ~= 0 and v ~= 1) then
                for k2 in pairs(addrs) do pcall(I.setAddress, petition_order_name(k2), 0) end
                why = 'standing order ' .. k .. ' read ' .. tostring(v) .. ' at DF\'s address: unbound, left alone'
                return
            end
        end
        via = 'symbols'
    end)
    if not ok then
        via, why = nil, tostring(err)
        for k2 in pairs(bound_now or {}) do pcall(I.setAddress, petition_order_name(k2), 0) end
    end
    PETITION_BIND = {via = via, why = why}
    return via, why
end

-- (r10 p1) The player reading petitions: DF's petitions screen
-- (main_interface.petitions.open, Gui.cpp's ".../Petitions" focus) or the
-- standing orders' Petitions tab (".../STANDING_ORDERS/PETITIONS"). Nothing
-- about petitions is changed under it; nil when neither is open.
function petitions_screen_busy()
    local ok, open = pcall(function() return df.global.game.main_interface.petitions.open end)
    if ok and open then return 'DF\'s petitions screen is open' end
    local okf, fs = pcall(function() return dfhack.gui.getFocusStrings(dfhack.gui.getDFViewscreen(true)) end)
    if okf and type(fs) == 'table' then
        for _, f in ipairs(fs) do
            f = tostring(f)
            if f:find('/Petitions', 1, true) then return 'DF\'s petitions screen is open' end
            if f:find('STANDING_ORDERS/PETITIONS', 1, true) then return 'the standing orders\' Petitions tab is open' end
        end
    end
    return nil
end

-- (r6) shared with ai-bridge-report-world
REPORT_PART_LOCALS.layer_at, REPORT_PART_LOCALS.citizen_positions, REPORT_PART_LOCALS.nearest = layer_at, citizen_positions, nearest
