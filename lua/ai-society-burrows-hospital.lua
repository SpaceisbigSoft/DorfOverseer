-- ai-society-burrows-hospital: the hospital burrow: the wounded kept by their beds, with the nearest
-- drink, food and well, and the hospital locations' zones and a well that gives water.
--
-- (r9) A part of ai-society-burrows, not a script of its own: ai-society-burrows.lua
-- loads it into its own environment, so every name here is
-- reqscript('ai-society-burrows').name and the names defined there and in the
-- parts before it are in reach.

if not BURROWS_PART_LOCALS then qerror('ai-society-burrows-hospital is a part of ai-society-burrows; run ai-society-burrows') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-society-burrows-hospital'] = '0.105.65'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, S, rec_state, zone_tiles = BURROWS_PART_LOCALS.U, BURROWS_PART_LOCALS.report_citizens, BURROWS_PART_LOCALS.S, BURROWS_PART_LOCALS.rec_state, BURROWS_PART_LOCALS.zone_tiles   -- (r9) the hub's and earlier parts' locals

-- --- (0.104.167) the hospital burrow -------------------------------------------
--
-- Teacheroar, 1 Nov 15:16-15:42: seven citizens killed by citizens, five of
-- them patients waiting for care, walking the corridors and halls (82 with
-- infected wounds walked the fort), strangled or struck down by dwarves in
-- tantrums. The player's word: keep the wounded inside the hospitals. The
-- opposite of the recreation burrow (which never covers a hospital since
-- 0.104.127): a burrow over every hospital location's zones, its members
-- the citizens DF asks a treatment for.
--
-- Drink (the design): a dwarf restricted to a burrow takes no drink or food
-- from outside it, and this fort has lost dwarves to thirst. Restricting only
-- the patients already lying in a hospital bed (fed and watered by the
-- doctors, labour FEED_WATER_CIVILIANS) would be safe for drink but would
-- leave out exactly those who were killed: the ones walking about. So the
-- burrow also covers, besides the hospitals' zones, the nearest stockpile
-- that holds drink now (in its barrels, neither forbidden), the nearest that
-- holds food, and the nearest well that gives water (built, its shaft open,
-- unfrozen water under it), each only when a dwarf can walk there from a
-- hospital zone (DF's walkability groups). With no drink reachable, nobody is
-- moved in and every member is let out, and the call says why.
-- Food: with no food pile reachable, only patients lying in a hospital bed
-- are moved in (the doctors feed them), and a member who is up and about is
-- let out after HOSP_NOFOOD_DAYS. Hunger takes far longer than that to harm.
-- Nobody is kept more than `days` (28): an untreated patient goes back to
-- the fort, and is not moved in again for HOSP_OUT_DAYS.
-- (review) The members are re-checked at every report, not only when the
-- brain asks (hospital_burrow_status): no hospital zone or no drink, and they
-- are let out right there; the burrow refilled when its sources change; the
-- burrow's own units compared with the saved list (assigned but not listed:
-- let out; listed but not assigned: dropped). The burrow is found by its
-- saved id (a renamed one is still ours; a removed one took its members).
-- Never a soldier, the hospital's own staff, a baby, the insane, one in a
-- tantrum, or one in a player's burrow; one in the AI's recreation burrow is
-- taken out of it first. Each is let out once DF asks no treatment for them.
-- At most `max` members, `per` new a call.
HOSPITAL_BURROW_NAME = 'AI hospital'
HOSPITAL_BURROW_KEY = 'ai-overseer/hospital-burrow'
HOSP_RQ = {'rq_diagnosis', 'rq_immobilize', 'rq_dressing', 'rq_cleaning', 'rq_surgery', 'rq_suture',
           'rq_setting', 'rq_traction', 'rq_crutch'}
HOSP_DAYS = 28              -- the longest stay (the brain may send its own)
HOSP_OUT_DAYS = 7           -- one let out after the longest stay: not moved in again for this long
HOSP_NOFOOD_DAYS = 3        -- no food reachable: one up and about is let out after this
HOSP_WELL_DEPTH = 2         -- a well's water: at least this deep (of 7)
local HOSP_FOOD = {FOOD = true, MEAT = true, FISH = true, CHEESE = true, EGG = true, PLANT = true, PLANT_GROWTH = true}
local HOSP_SCAN_MAX = 2000           -- items looked at in one pile

local function hb_state()
    local d = U.site_get(HOSPITAL_BURROW_KEY, {members = {}})
    d.members = type(d.members) == 'table' and d.members or {}
    d.out = type(d.out) == 'table' and d.out or {}
    return d
end

local function hb_save(d)
    U.site_put(HOSPITAL_BURROW_KEY, d)
end

local function hb_now()
    return U.abs_tick()
end

-- The hospital locations' zones (as the bridge's hospital_survey finds them)
-- and the units holding a post at any of them.
function hospital_zones()
    local ids, staff, zones = {}, {}, {}
    pcall(function()
        for _, loc in ipairs(dfhack.world.getCurrentSite().buildings) do
            pcall(function()
                if df.abstract_building_type[loc:getType()] ~= 'HOSPITAL' then return end
                for _, bid in ipairs(loc:getContents().building_ids) do ids[bid] = true end
                for _, o in ipairs(loc.occupations or {}) do
                    if o.unit_id ~= -1 then staff[o.unit_id] = true end
                end
            end)
        end
    end)
    for _, b in ipairs(df.global.world.buildings.all) do
        if ids[b.id] and b:getType() == df.building_type.Civzone then table.insert(zones, b) end
    end
    table.sort(zones, function(a, c) return a.id < c.id end)
    return zones, staff
end

local function walk_group(p)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, p)
    return ok and type(g) == 'number' and g or 0
end

-- A tile of the building a dwarf can stand on: its middle, else the first
-- walkable one of its tiles.
local function stand_pos(b)
    local mid = xyz2pos(math.floor((b.x1 + b.x2) / 2), math.floor((b.y1 + b.y2) / 2), b.z)
    if walk_group(mid) ~= 0 then return mid end
    local n = 0
    for y = b.y1, b.y2 do
        for x = b.x1, b.x2 do
            local p = xyz2pos(x, y, b.z)
            if walk_group(p) ~= 0 then return p end
            n = n + 1
            if n > 400 then return nil end
        end
    end
    return nil
end

local function can_walk(a, c)
    local ok, yes = pcall(dfhack.maps.canWalkBetween, a, c)
    if ok and type(yes) == 'boolean' then return yes end
    local ga = walk_group(a)
    return ga ~= 0 and ga == walk_group(c)
end

local function in_zones(pos, zones)
    if not pos then return false end
    for _, z in ipairs(zones) do
        if pos.z == z.z and pos.x >= z.x1 and pos.x <= z.x2 and pos.y >= z.y1 and pos.y <= z.y2 then
            local okc, inside = pcall(dfhack.buildings.containsTile, z, pos.x, pos.y)
            if not okc or inside then return true end
        end
    end
    return false
end

-- What a pile holds now: drink, food (in barrels and pots too; never a
-- forbidden item, nor what lies in a forbidden barrel).
local function pile_holds(b)
    local drink, food, seen = false, false, 0
    local function forbidden(it)
        local okf, f = pcall(function() return it.flags.forbid end)
        return okf and f and true or false
    end
    local function look(it)
        local okt, t = pcall(function() return df.item_type[it:getType()] end)
        if not okt then return end
        if t == 'DRINK' then drink = true elseif HOSP_FOOD[t] then food = true end
    end
    local ok, items = pcall(dfhack.buildings.getStockpileContents, b)
    if not ok or type(items) ~= 'table' and type(items) ~= 'userdata' then return false, false end
    for _, it in ipairs(items) do
        seen = seen + 1
        if seen > HOSP_SCAN_MAX or (drink and food) then break end
        if not forbidden(it) then
            look(it)
            pcall(function()
                for _, c in ipairs(dfhack.items.getContainedItems(it)) do
                    if not forbidden(c) then look(c) end
                end
            end)
        end
    end
    return drink, food
end

-- A well that gives water: fully built, and down its shaft no shut hatch
-- (the AI's cavern shaft gate, lua/ai-builder.lua shaft_gate_state 'closed',
-- or anyone's), no ice, but water HOSP_WELL_DEPTH deep (never magma) before
-- the shaft meets solid ground.
function well_gives_water(b)
    local okb, built = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    if not (okb and built) then return false end
    local x, y = b.centerx or b.x1, b.centery or b.y1
    for z = b.z - 1, math.max(0, b.z - 100), -1 do
        local p = xyz2pos(x, y, z)
        local okh, h = pcall(dfhack.buildings.findAtTile, p)
        if okh and h and df.building_type.Hatch ~= nil and h:getType() == df.building_type.Hatch then
            local okc, closed = pcall(function() return h.door_flags.closed end)
            if not okc or closed then return false end
        end
        local okt, tt = pcall(dfhack.maps.getTileType, p)
        if not okt or not tt then return false end
        local oka, shape, mat = pcall(function()
            local at = df.tiletype.attrs[tt]
            return df.tiletype_shape[at.shape], df.tiletype_material[at.material]
        end)
        if not oka then return false end
        if mat == 'FROZEN_LIQUID' then return false end
        local okf, des = pcall(dfhack.maps.getTileFlags, p)
        if not okf or not des then return false end
        if (des.flow_size or 0) > 0 then
            if des.liquid_type == true or des.liquid_type == 1 then return false end      -- magma
            return des.flow_size >= HOSP_WELL_DEPTH
        end
        if shape ~= 'EMPTY' and shape ~= 'RAMP_TOP' then return false end              -- the shaft ends dry
    end
    return false
end

-- The nearest drink pile, food pile and well a dwarf can walk to from a
-- hospital zone: {drink = b, food = b, well = b, dist = {...}}.
local function hospital_sources(zones)
    local from = {}
    for _, z in ipairs(zones) do
        local p = stand_pos(z)
        if p then table.insert(from, p) end
    end
    local out = {dist = {}}
    if #from == 0 then return out end
    local function reach(p)
        local best
        for _, f in ipairs(from) do
            local dd = math.abs(p.x - f.x) + math.abs(p.y - f.y) + 3 * math.abs(p.z - f.z)
            if (not best or dd < best) and can_walk(f, p) then best = dd end
        end
        return best
    end
    local function offer(kind, b, dd)
        if dd and (not out.dist[kind] or dd < out.dist[kind]) then out[kind], out.dist[kind] = b, dd end
    end
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = b:getType()
        if t == df.building_type.Stockpile then
            local okf, food = pcall(function() return b.settings.flags.food end)
            if okf and food then
                local has_drink, has_food = pile_holds(b)
                if has_drink or has_food then
                    local p = stand_pos(b)
                    local dd = p and reach(p)
                    if has_drink then offer('drink', b, dd) end
                    if has_food then offer('food', b, dd) end
                end
            end
        elseif df.building_type.Well ~= nil and t == df.building_type.Well and well_gives_water(b) then
            -- a dwarf draws water standing beside the well
            local x, y = b.centerx or b.x1, b.centery or b.y1
            for dy = -1, 1 do
                for dx = -1, 1 do
                    if dx ~= 0 or dy ~= 0 then
                        local p = xyz2pos(x + dx, y + dy, b.z)
                        if walk_group(p) ~= 0 then offer('well', b, reach(p)) end
                    end
                end
            end
        end
    end
    return out
end

local function hb_sig(zones, src)
    local parts = {}
    for _, z in ipairs(zones) do table.insert(parts, tostring(z.id)) end
    for _, k in ipairs({'drink', 'food', 'well'}) do
        table.insert(parts, k .. '=' .. tostring(src[k] and src[k].id or '-'))
    end
    return table.concat(parts, ',')
end

local function fill_hospital_burrow(burrow, zones, src)
    dfhack.burrows.clearTiles(burrow)
    local n = 0
    for _, z in ipairs(zones) do n = n + zone_tiles(z, burrow) end
    if src.drink then n = n + zone_tiles(src.drink, burrow) end
    if src.food and src.food ~= src.drink then n = n + zone_tiles(src.food, burrow) end
    if src.well then
        local w = src.well
        local x, y = w.centerx or w.x1, w.centery or w.y1
        for dy = -1, 1 do
            for dx = -1, 1 do
                if dfhack.burrows.setAssignedTile(burrow, xyz2pos(x + dx, y + dy, w.z), true) then n = n + 1 end
            end
        end
    end
    return n
end

-- The burrow by its saved id (a renamed one is still ours). Gone (the player
-- removed it): its members went with it, the list is cleared. An older save
-- with no id: the one by our name.
local function hb_burrow(d)
    if d.burrow_id ~= nil then
        for _, b in ipairs(df.global.plotinfo.burrows.list) do
            if b.id == d.burrow_id then return b end
        end
        d.members, d.burrow_id, d.sig, d.filled, d.tiles = {}, nil, nil, nil, nil
        return nil
    end
    local b = S.find_burrow(HOSPITAL_BURROW_NAME)
    if b then d.burrow_id = b.id end
    return b
end

-- The units the burrow holds now (unit id -> true), or nil when unreadable.
local function burrow_unit_ids(b)
    -- (0.105.48) DFHack 53.17 has no dfhack.burrows.listUnits: the burrow's own list
    local ids = {}
    local ok = pcall(function() for _, id in ipairs(b.units) do ids[id] = true end end)
    return ok and ids or nil
end

-- The burrow's own units against the saved list: assigned but not listed
-- (a throw mid-call, a player's hand): let out; listed but no longer
-- assigned (the player took them out): dropped from the list.
local function hb_reconcile(d, b, dry_run, released, name)
    local ids = burrow_unit_ids(b)
    if not ids then return end
    for id in pairs(ids) do
        if not d.members[tostring(id)] then
            local u = df.unit.find(id)
            if not dry_run and u then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            table.insert(released, u and name(u) or tostring(id))
        end
    end
    for id in pairs(d.members) do
        if not ids[tonumber(id)] then d.members[id] = nil end
    end
end

-- A treatment asked by DF (its rq_ flags; needs_healthcare alone is set for
-- every infected dwarf walking about: 0.104.150).
function is_patient(u)
    local ok, yes = pcall(function()
        if not (u.health and u.health.flags.needs_healthcare) then return false end
        for _, f in ipairs(HOSP_RQ) do
            if u.health.flags[f] then return true end
        end
        return false
    end)
    if ok and yes then return true end
    return in_quarantine(u)
end

-- (0.105.41, item 11) a citizen the AI quarantined for carrying a contact
-- syndrome (lua/ai-syndromes.lua quarantine) is kept in the hospital burrow
-- as a patient is, with every guard of the burrow's own
function in_quarantine(u)
    local okm, Q = pcall(reqscript, 'ai-syndromes')
    if not okm or type(Q) ~= 'table' or not Q.quarantined then return false end
    local ok, yes = pcall(Q.quarantined, u.id)
    return ok and yes == true
end

local function in_tantrum(u)
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    return okm and (m == 'Tantrum' or m == 'Enraged')
end

-- (review) the same citizen test for moving in and for keeping: a citizen
-- and sane (getCitizens(true) lists the insane too)
local function hb_citizen(u)
    local okc, cit = pcall(dfhack.units.isCitizen, u)
    if not (okc and cit) then return false end
    local oks, sane = pcall(dfhack.units.isSane, u)
    return not (oks and sane == false)
end

-- (r9, audit A7 #21) The AI shelter's burrow, whose members are the
-- evil-weather keep-in's (weather_keep_in): the AI's own, not a player's
-- burrow, for the hospital and calm-down burrows. Its id, or -3 with none.
local function shelter_id()
    local ok, b = pcall(S.find_burrow, S.SHELTER_NAME)
    return ok and b and b.id or -3
end

-- (r9, audit A7 #21) One taken into the hospital or a calm room comes out of
-- the weather keep-in (the next keep-in skips them while they are there, as
-- one in another burrow; let out of it, they are kept in again)
local function wk_take_out(u, sid)
    pcall(function()
        for _, b in ipairs(df.global.plotinfo.burrows.list) do
            if b.id == sid then dfhack.burrows.setAssignedUnit(b, u, false) break end
        end
    end)
    pcall(function()
        local d = U.site_get(WEATHER_KEEP_KEY, nil)
        if type(d) == 'table' and type(d.members) == 'table' and d.members[tostring(u.id)] then
            d.members[tostring(u.id)] = nil
            U.site_put(WEATHER_KEEP_KEY, d)
        end
    end)
end

-- Whether in a burrow other than ours and the recreation one, and whether
-- in the recreation one; (r9) and whether in the AI shelter's (the weather
-- keep-in: no player's burrow)
local function burrows_of(u, own_id, rec_id, sid)
    local other, rec, wk = false, false, false
    local ok = pcall(function()
        for _, bid in ipairs(u.burrows or {}) do
            if bid == rec_id then rec = true
            elseif bid == sid then wk = true
            elseif bid ~= own_id then other = true end
        end
    end)
    if not ok then return true, false, false end
    return other, rec, wk
end

local function in_hospital_bed(u, zones)
    local ok, yes = pcall(function()
        local j = u.job.current_job
        if not (j and j.job_type == df.job_type.Rest) then return false end
        local bed = dfhack.buildings.findAtTile(u.pos)
        return bed ~= nil and bed:getType() == df.building_type.Bed and in_zones(u.pos, zones)
    end)
    return ok and yes or false
end

-- eligible, and whether in the recreation burrow now (r9: and the weather keep-in's)
local function hb_eligible(u, staff, own_id, rec_id, sid)
    local okb, baby = pcall(dfhack.units.isBaby, u)
    if okb and baby then return false end
    if not hb_citizen(u) or u.military.squad_id ~= -1 or staff[u.id] or in_tantrum(u) then return false end
    if in_mood(u) then return false end              -- (0.105.51) a strange mood needs its workshop
    if not is_patient(u) then return false end
    local other, rec, wk = burrows_of(u, own_id, rec_id, sid)
    if other then return false end
    return true, rec, wk
end

-- (0.105.33, L6) The report's sources, cached: hospital_sources reads every
-- food pile's contents and walks from each hospital zone to each pile. Kept
-- HB_SRC_TTL ticks for the same zones, the chosen piles and well re-checked
-- at each report (still holding drink and food, the well still giving water).
HB_SRC_TTL = 600             -- half a day
-- (0.105.33 fix) the cache keeps the buildings' ids, never the objects: a
-- pile or well the player removed meanwhile is freed by DF (reading it, a
-- use-after-free no pcall catches). Each is found again by id at the next
-- report; one gone, the sources are worked out afresh. Cleared when the map
-- unloads (a reload within half a day keeps the same zone ids).
local HB_SRC = nil           -- {key, at, ids = {drink, food, well}, dist}
local function hb_find(id)
    if id == nil then return nil end
    local ok, b = pcall(function() return df.building.find(id) end)
    if ok and b then return b end
    local okl, found = pcall(function()
        for _, x in ipairs(df.global.world.buildings.all) do
            if x.id == id then return x end
        end
    end)
    return okl and found or nil
end
local function hb_src_key(zones)
    local parts = {}
    for _, z in ipairs(zones) do table.insert(parts, tostring(z.id)) end
    return table.concat(parts, ',')
end
-- (0.105.36, D5) only sources that found drink or a well are kept: a cached
-- "no drink" (nothing in it to re-check) let out, within half a day, the
-- patients the tick had just moved in on drink brought back
local function hb_src_store(key, now, src)
    if not (src.drink or src.well) then HB_SRC = nil; return end
    local ids = {}
    for _, k in ipairs({'drink', 'food', 'well'}) do
        if src[k] then ids[k] = src[k].id end
    end
    HB_SRC = {key = key, at = now, ids = ids, dist = src.dist}
end
local function hospital_sources_cached(zones, now)
    local key = hb_src_key(zones)
    local c = HB_SRC
    if c and c.key == key and now >= c.at and now - c.at < HB_SRC_TTL then
        local src, good = {dist = c.dist}, true
        for _, k in ipairs({'drink', 'food', 'well'}) do
            if c.ids[k] ~= nil then
                src[k] = hb_find(c.ids[k])
                if not src[k] then good = false end
            end
        end
        if good and src.drink then
            local okd, dr = pcall(pile_holds, src.drink)
            if not (okd and dr) then good = false end
        end
        if good and src.food and src.food ~= src.drink then
            local okf, _, fo = pcall(pile_holds, src.food)
            if not (okf and fo) then good = false end
        end
        if good and src.well then
            local okw, w = pcall(well_gives_water, src.well)
            if not (okw and w) then good = false end
        end
        if good then return src end
    end
    local src = hospital_sources(zones)
    hb_src_store(key, now, src)
    return src
end
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-society-burrows-hb'] = function(sc)
        if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then HB_SRC = nil end
    end
end

-- The members' checks (the burrow already reconciled). With no hospital
-- zone or no drink reachable, everyone out: returns why. Else the tiles
-- refilled when the sources changed (returns nil, tiles), and each member
-- let out who is healed, gone, drafted, staff, raging, in a player's burrow,
-- or in too long.
-- (0.105.22) a member thirsty or hungry this far is let out to drink and eat
-- where they can (B, 3 Nov: 36 of a night's 71 who died of thirst were in
-- the hospital burrow, its "drink they can reach" one pile; the bedridden get
-- water only from a well) and not taken back in until they've drunk
HOSP_THIRST = 25000          -- DFHack's "thirsty"
HOSP_HUNGER = 50000          -- DF's "hungry"

local function hb_dry(u)
    local ok, yes = pcall(function()
        return u.counters2.thirst_timer >= HOSP_THIRST or u.counters2.hunger_timer >= HOSP_HUNGER
    end)
    return ok and yes == true
end

local function hb_maintain(d, b, zones, staff, src, now, dry_run, name, released)
    local function let_out(id, u, timed)
        if not dry_run and u and b then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
        d.members[id] = nil
        if timed then d.out[id] = now end
        table.insert(released, u and name(u) or id)
    end
    local why
    if #zones == 0 then
        why = 'no hospital zone: make a zone a hospital location first'
    elseif not src.drink and not src.well then
        why = 'no drink reachable from the hospital (no stockpile holding drink and no well giving water that a '
              .. 'dwarf can walk to): nobody is kept in the hospital without it'
    end
    if why then
        for id in pairs(d.members) do let_out(id, df.unit.find(tonumber(id))) end
        d.why = why
        return why
    end
    d.why = nil
    d.drink = src.drink and 'stockpile' or 'well'
    d.food = src.food ~= nil
    local tiles
    local sig = hb_sig(zones, src)
    if b and not dry_run and (sig ~= d.sig or not d.filled or now - d.filled >= 7 * 1200) then
        tiles = fill_hospital_burrow(b, zones, src)
        d.filled, d.sig, d.tiles = now, sig, tiles
    end
    local days = tonumber(d.days) or HOSP_DAYS
    local rec_b = S.find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    for id, since in pairs(d.members) do
        local u = df.unit.find(tonumber(id))
        since = tonumber(since) or now
        local keep = u and hb_citizen(u) and u.military.squad_id == -1 and not staff[u.id] and is_patient(u)
                     and not in_tantrum(u) and not in_mood(u)
                     and not (burrows_of(u, b and b.id or -1, rec_id, shelter_id())) and true or false
        if keep and hb_dry(u) then
            let_out(id, u, true)                 -- (0.105.22) to drink and eat
        elseif keep and now - since >= days * 1200 then
            let_out(id, u, true)
        elseif keep and not src.food and now - since >= HOSP_NOFOOD_DAYS * 1200 and not in_hospital_bed(u, zones) then
            let_out(id, u, true)
        elseif not keep then
            let_out(id, u)
        end
    end
    return nil, tiles
end

-- For the report: the burrow, its members and tiles, the hospital zones, and
-- the patients who could join walking outside the hospitals. (review) Also
-- the bridge's own guard, at every report: the members re-checked and let
-- out here (no hospital, no drink, healed...), with no brain needed.
function hospital_burrow_status(txt)
    local function name(u) return (txt or tostring)(dfhack.units.getReadableName(u)) end
    local d = hb_state()
    local now = hb_now()
    local zones, staff = hospital_zones()
    local had_id = d.burrow_id
    local b = hb_burrow(d)
    local released = {}
    local before = 0
    for _ in pairs(d.members) do before = before + 1 end
    if b then hb_reconcile(d, b, false, released, name) end
    local tiles
    if next(d.members) ~= nil then
        local src = #zones > 0 and hospital_sources_cached(zones, now) or {dist = {}}
        local _
        _, tiles = hb_maintain(d, b, zones, staff, src, now, false, name, released)
    end
    local after = 0
    for _ in pairs(d.members) do after = after + 1 end
    if #released > 0 or tiles or after ~= before or had_id ~= d.burrow_id then hb_save(d) end
    local rec_b = S.find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    local out = {burrow = b and b.id or nil, members = after, tiles = d.tiles, hospital_zones = #zones,
                 drink = d.drink, food = d.food, why = d.why, outside = 0, patients = 0,
                 released_now = #released > 0 and released or nil}
    for _, u in ipairs(report_citizens(true)) do
        if is_patient(u) then
            out.patients = out.patients + 1
            if not d.members[tostring(u.id)] and hb_eligible(u, staff, b and b.id or -1, rec_id)
                    and not in_zones(u.pos, zones) then
                out.outside = out.outside + 1
            end
        end
    end
    return out
end

-- `release`: the brain's word that the burrow is to be emptied (the rule
-- switched off, the hospital gone, its status unreadable).
function hospital_burrow_tick(max, per, dry_run, txt, days, release)
    max, per, days = max or 30, per or 10, days or HOSP_DAYS
    local function name(u) return (txt or tostring)(dfhack.units.getReadableName(u)) end
    local d = hb_state()
    local now = hb_now()
    local zones, staff = hospital_zones()
    local b = hb_burrow(d)
    local released, added = {}, {}
    if b then hb_reconcile(d, b, dry_run, released, name) end
    if release then
        for id in pairs(d.members) do
            local u = df.unit.find(tonumber(id))
            if not dry_run and u and b then pcall(dfhack.burrows.setAssignedUnit, b, u, false) end
            d.members[id] = nil
            table.insert(released, u and name(u) or id)
        end
        if not dry_run then hb_save(d) end
        if #released == 0 then return {ok = true, unchanged = true, members = 0} end
        return {ok = true, released = released, added = {}, members = 0, dry_run = dry_run or nil}
    end
    d.days = days
    local src = #zones > 0 and hospital_sources(zones) or {dist = {}}
    -- (0.105.36, D5) the report's cache takes the tick's fresh sources, so
    -- the two agree on the drink and on the tiles' signature
    if #zones > 0 then hb_src_store(hb_src_key(zones), now, src) end
    local why, tiles = hb_maintain(d, b, zones, staff, src, now, dry_run, name, released)
    if why then
        if not dry_run then hb_save(d) end
        if #released > 0 then
            return {ok = true, released = released, added = {}, members = 0, note = why, dry_run = dry_run or nil}
        end
        return {ok = false, rejected = true, error = why}
    end
    if not b and dry_run then
        return {ok = true, dry_run = true, note = 'the burrow would be made', drink = d.drink}
    end
    if not b then
        b = S.new_burrow(HOSPITAL_BURROW_NAME)
        d.burrow_id, d.members = b.id, {}
        tiles = fill_hospital_burrow(b, zones, src)
        d.filled, d.sig, d.tiles = now, hb_sig(zones, src), tiles
        hb_save(d)
    end
    local count = 0
    for _ in pairs(d.members) do count = count + 1 end
    -- the patients walking outside the hospitals first; with no food in
    -- reach only those lying in a hospital bed (the doctors feed them)
    local rec_b = S.find_burrow(RECREATION_NAME)
    local rec_id = rec_b and rec_b.id or -2
    local cands = {}
    local sid = shelter_id()
    for _, u in ipairs(report_citizens(true)) do
        local key = tostring(u.id)
        local was = tonumber(d.out[key])
        if was and now - was >= HOSP_OUT_DAYS * 1200 then d.out[key] = nil; was = nil end
        if not d.members[key] and not was then
            local ok, in_rec, in_wk = hb_eligible(u, staff, b.id, rec_id, sid)
            -- (0.105.22) never one already thirsty or hungry; a bedridden one
            -- (in a hospital bed) only with a well giving water
            local bed = in_hospital_bed(u, zones)
            if ok and not hb_dry(u) and ((src.food and not bed) or (bed and src.well)) then
                table.insert(cands, {u = u, inside = in_zones(u.pos, zones) and 1 or 0, rec = in_rec, wk = in_wk})
            end
        end
    end
    table.sort(cands, function(a, c) if a.inside ~= c.inside then return a.inside < c.inside end return a.u.id < c.u.id end)
    local rec
    for _, c in ipairs(cands) do
        if count >= max or #added >= per then break end
        local key = tostring(c.u.id)
        if dry_run then
            count = count + 1
            table.insert(added, name(c.u))
        else
            if c.rec and rec_b then
                -- out of the AI's own recreation burrow first (patients never join it: 0.104.78)
                rec = rec or rec_state()
                pcall(dfhack.burrows.setAssignedUnit, rec_b, c.u, false)
                rec.members[key] = nil
                if type(rec.friends) == 'table' then rec.friends[key] = nil end
                rec.out[key] = now
                U.site_put(RECREATION_KEY, rec)
            end
            if c.wk then wk_take_out(c.u, sid) end            -- (r9) out of the weather keep-in
            -- (review) each one listed and saved as moved in: a throw can't leave one assigned unlisted
            local oka = pcall(dfhack.burrows.setAssignedUnit, b, c.u, true)
            if oka then
                d.members[key] = now
                hb_save(d)
                count = count + 1
                table.insert(added, name(c.u) .. (c.rec and ' (from the recreation burrow)' or ''))
            end
        end
    end
    if not dry_run then hb_save(d) end
    if #added == 0 and #released == 0 and not tiles then
        return {ok = true, unchanged = true, members = count}     -- nothing to change is no refusal
    end
    return {ok = true, burrow_id = b.id, tiles = tiles, added = added, released = released, members = count,
            drink = d.drink, food = src.food ~= nil, dry_run = dry_run or nil}
end

-- (r9) this part's locals the parts after it use, handed on
BURROWS_PART_LOCALS.HOSP_SCAN_MAX = HOSP_SCAN_MAX
BURROWS_PART_LOCALS.hb_state = hb_state
BURROWS_PART_LOCALS.hb_now = hb_now
BURROWS_PART_LOCALS.walk_group = walk_group
BURROWS_PART_LOCALS.stand_pos = stand_pos
BURROWS_PART_LOCALS.can_walk = can_walk
BURROWS_PART_LOCALS.in_zones = in_zones
BURROWS_PART_LOCALS.pile_holds = pile_holds
BURROWS_PART_LOCALS.burrow_unit_ids = burrow_unit_ids
BURROWS_PART_LOCALS.in_tantrum = in_tantrum
BURROWS_PART_LOCALS.hb_citizen = hb_citizen
BURROWS_PART_LOCALS.shelter_id = shelter_id
BURROWS_PART_LOCALS.wk_take_out = wk_take_out
