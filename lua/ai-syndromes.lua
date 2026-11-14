-- (0.105.41, item 11) Syndromes beyond infection, and miasma.
--
-- Syndromes: a dwarf with an active syndrome (forgotten beast breath, dust or
-- blood; cave spider venom; evil rain or cloud; something eaten or drunk) is
-- read from unit.syndromes.active, by name, how long, its routes (the
-- syndrome's flags: contact, inhaled, injected, ingested), its effects (the
-- deadly ones marked) and where it came from: the material that carries it
-- (material.syndrome.syndrome), learned from the contaminants the fort
-- meets (on the dwarves' bodies, their gear, the fort's floors) and, for one
-- not met yet, from the game's raws walked once in slices. A citizen whose
-- body is spattered with a material that carries a CONTACT syndrome spreads
-- it (DF tracks spatter from feet to floor and floor to feet): a carrier.
-- The fort's floors are walked for such spatter in time-budgeted slices
-- (only the map blocks in the fort's built-up areas, ai-cleanup fort_boxes,
-- each fetched by dfhack.maps.getBlock: never the whole map), a
-- pass at most once a game day, the last finished pass reported between.
--
--   report()                  the `syndromes` report section
--   clean(o, dry)             the `clean_contaminants` action: the syndrome
--                             carrying spatter taken off the citizens' bodies,
--                             their carried and worn things, and the fort's
--                             floors (as DFHack's `clean` does, but only the
--                             syndrome materials: blood, mud, vomit are left)
--   quarantine(o, dry)        the `quarantine_syndromes` action: the carriers
--                             kept in the AI's hospital burrow (ai-society-
--                             burrows reads QUARANTINE_KEY: a quarantined
--                             citizen counts as a patient there, with its
--                             drink, food, longest stay and every guard) for
--                             o.days after last seen carrying; release = all out.
--                             (fix5) Never a squad member (the burrow doesn't
--                             hold soldiers): left out and counted (soldiers);
--                             one drafted since is let out
--
-- Miasma: the Miasma flows on the map (df.global.flows: the game's own list,
-- cheap), those indoors and those within the fort's built-up areas, grouped
-- by map block; the rotting things in and round the worst blocks (bodies,
-- parts, remains, rotten meat, fish and food lying loose); the fort's own
-- dead among them (the burial rules' and the tombs'); the garbage dump zones
-- under the sky.
--
--   miasma_report()           the `miasma` report section
--   clear_miasma(o, dry)      the `clear_miasma` action: the rotting things
--                             found near miasma marked for the garbage dump
--                             (only with a dump zone under the sky), at most
--                             o.max. Never the fort's own dead (burial), an
--                             artifact, owned, held, in a container or a
--                             building, a trader's, in a job, already marked,
--                             in a stockpile (a pile's contents are its
--                             owner's: the player's refuse pile indoors is
--                             said, not emptied), or forbidden for no reason
--                             the game gives (the player's: ai-util
--                             forbidden_reason 'unknown'). Another's body
--                             forbidden by the game's dead-items order is
--                             unforbidden as it is marked (as the disposal
--                             rules do). (fix5) Only near the living areas'
--                             miasma (none in the caverns); never one near
--                             a danger, on a cavern tile, or where no
--                             citizen's walk group reaches; and a whole
--                             corpse the butcher would take is left while
--                             the fort has a butcher's shop.
--
-- Field names from df-structures (53.x): syndrome.flags SYN_CONTACT,
-- SYN_INHALED, SYN_INJECTED, SYN_INGESTED; syndrome.ce[i]:getType();
-- material.syndrome.syndrome; unit.body.spatters[i].base.mat_type;
-- item.contaminants (a pointer to a vector of spatter, nil when none);
-- block_square_event_material_spatterst; flow_info type/density/pos.
--@ module = true

local U = reqscript('ai-util')

QUARANTINE_KEY = 'ai-overseer/quarantine'
BUDGET_MS = 15               -- a report's floor walk at most (ms of os.clock)
ACTION_BUDGET_MS = 150       -- an action's floor walk at most
RAWS_BUDGET_MS = 20          -- the raws walk (for an unknown syndrome's source), a report at most
PASS_TICKS = 1200            -- a new floor pass a game day after the last one started at the soonest
LIST_MAX = 30                -- afflicted citizens listed
QUARANTINE_DAYS = 7          -- kept this long after last seen carrying (the brain sends its own)
QUARANTINE_MAX = 30
MIASMA_FLOWS_MAX = 20000     -- flows looked at, at most
MIASMA_SPOTS = 12            -- the worst blocks searched for what rots
MIASMA_ITEMS_MAX = 4000      -- items looked at near miasma, at most
MIASMA_LIST = 20
CLEAR_MAX = 200

-- the effects that kill or cripple (creature_interaction_effect_type)
DEADLY = {NECROSIS = true, BLEEDING = true, PARALYSIS = true, UNCONSCIOUSNESS = true, COUGH_BLOOD = true,
          VOMIT_BLOOD = true, IMPAIR_FUNCTION = true}
ROUTES = {SYN_CONTACT = 'contact', SYN_INHALED = 'inhaled', SYN_INJECTED = 'injected', SYN_INGESTED = 'ingested'}
-- what rots into miasma: bodies, parts and remains always; these when rotten
BODY_KINDS = {CORPSE = true, CORPSEPIECE = true, REMAINS = true}
FOOD_KINDS = {MEAT = true, FISH = true, FISH_RAW = true, PLANT = true, PLANT_GROWTH = true, CHEESE = true,
              EGG = true, GLOB = true, FOOD = true}

-- --- helpers ---------------------------------------------------------------

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function ms_since(t0) return (os.clock() - t0) * 1000 end

local function vlen(v)
    if v == nil then return 0 end
    local ok, n = pcall(function() return #v end)
    return ok and n or 0
end

local function vget(v, i)        -- i 0-based
    if type(v) == 'table' then return v[i + 1] end
    return v[i]
end

local function verase(v, i)      -- i 0-based
    if type(v) == 'table' then table.remove(v, i + 1) else v:erase(i) end
end

local function free(obj)
    if type(obj) ~= 'table' then pcall(function() obj:delete() end) end
end

local function txt(s)
    local ok, t = pcall(dfhack.df2utf, s)
    return ok and t or tostring(s)
end

local function unit_name(u)
    local ok, n = pcall(dfhack.units.getReadableName, u)
    return ok and txt(n) or ('unit ' .. tostring(u.id))
end

-- --- syndromes and the materials that carry them ---------------------------

SYN_CACHE = SYN_CACHE or {}       -- syndrome id -> info
MAT_CACHE = MAT_CACHE or {}       -- 'type:index' -> {ids, contact, name, source}
SOURCES = SOURCES or {}           -- syndrome id -> {kind, what}

function reset()
    SYN_CACHE, MAT_CACHE, SOURCES, PASS, LAST, RAWS = {}, {}, {}, nil, nil, nil
    QCACHE = nil
end

-- What kind of source a material token is: forgotten beast, cave spider,
-- evil weather, night creature, creature, plant, mineral.
function source_kind(mode, id)
    id = tostring(id or ''):upper()
    if mode == 'creature' then
        if id:find('FORGOTTEN_BEAST') then return 'forgotten_beast' end
        if id:find('SPIDER_CAVE') or id:find('CAVE_SPIDER') then return 'cave_spider' end
        if id:find('NIGHT_CREATURE') or id:find('DEMON') or id:find('TITAN') or id:find('HF') == 1 then
            return 'night_creature'
        end
        return 'creature'
    elseif mode == 'inorganic' then
        if id:find('EVIL') or id:find('CLOUD') or id:find('RAIN') then return 'evil_weather' end
        return 'mineral'
    elseif mode == 'plant' then
        return 'plant'
    end
    return 'unknown'
end

local function matinfo(mt, mi)
    local ok, info = pcall(dfhack.matinfo.decode, mt, mi)
    if ok and info then return info end
    return nil
end

-- the source of a material: {kind, what} (what: the material in words)
local function mat_source(info)
    local mode, id = nil, nil
    pcall(function()
        if info.creature then mode, id = 'creature', info.creature.creature_id
        elseif info.plant then mode, id = 'plant', info.plant.id
        elseif info.inorganic then mode, id = 'inorganic', info.inorganic.id end
    end)
    local okn, name = pcall(function() return info:toString() end)
    return {kind = source_kind(mode, id), what = okn and txt(name) or tostring(id or '?'), id = id}
end

-- the syndromes a material carries (material.syndrome.syndrome)
local function mat_syndrome_list(mat)
    local out = {}
    pcall(function()
        for _, sd in ipairs(mat.syndrome.syndrome) do out[#out + 1] = sd end
    end)
    return out
end

function syndrome_info(id)
    local c = SYN_CACHE[id]
    if c then return c end
    local okf, sd = pcall(df.syndrome.find, id)
    if not okf then sd = nil end
    c = {id = id, name = 'syndrome ' .. tostring(id), routes = {}, effects = {}, deadly = false, known = sd ~= nil}
    if sd then
        pcall(function() if sd.syn_name ~= '' then c.name = txt(sd.syn_name) end end)
        local okr = pcall(function()
            for flag, word in pairs(ROUTES) do
                if sd.flags[flag] then table.insert(c.routes, word) end
            end
        end)
        if not okr then c.routes_unknown = true end
        table.sort(c.routes)
        pcall(function()
            local seen = {}
            for _, ce in ipairs(sd.ce) do
                local okt, t = pcall(function() return df.creature_interaction_effect_type[ce:getType()] end)
                if okt and t and not seen[t] then
                    seen[t] = true
                    table.insert(c.effects, t)
                    if DEADLY[t] then c.deadly = true end
                end
            end
        end)
        table.sort(c.effects)
    end
    SYN_CACHE[id] = c
    return c
end

local function has_route(info, word)
    for _, r in ipairs(info.routes) do if r == word then return true end end
    return false
end

-- Does a syndrome spread by touch? (contact; routes the game didn't let us
-- read count as contact: the cleaning is harmless, the carrier kept safe)
function spreads(info)
    return info.routes_unknown == true or has_route(info, 'contact')
end

-- What a material (type, index) carries: {ids = {...}, contact = bool,
-- name, source}; nil for one that carries no syndrome. Cached; each
-- syndrome's source learned on the way.
function material_syndromes(mt, mi)
    if mt == nil or mt < 0 then return nil end
    local key = tostring(mt) .. ':' .. tostring(mi)
    local c = MAT_CACHE[key]
    if c ~= nil then return c or nil end
    local info = matinfo(mt, mi)
    local list = info and mat_syndrome_list(info.material) or {}
    if #list == 0 then
        MAT_CACHE[key] = false
        return nil
    end
    local src = mat_source(info)
    c = {ids = {}, contact = false, name = src.what, source = src}
    for _, sd in ipairs(list) do
        local okid, id = pcall(function() return sd.id end)
        if okid and id ~= nil then
            table.insert(c.ids, id)
            if not SOURCES[id] then SOURCES[id] = src end
            if spreads(syndrome_info(id)) then c.contact = true end
        end
    end
    MAT_CACHE[key] = c
    return c
end

-- A spatter's (or unit spatter's) material: type, index (DF 50+: .base)
local function spatter_mat(sp)
    local ok, mt, mi = pcall(function() return sp.base.mat_type, sp.base.mat_index end)
    if ok and mt ~= nil then return mt, mi end
    ok, mt, mi = pcall(function() return sp.mat_type, sp.mat_index end)
    if ok then return mt, mi end
    return nil
end

-- The raws walked for the syndromes' sources (inorganics, plants,
-- creatures' materials), in slices of RAWS_BUDGET_MS; only while a syndrome
-- of unknown source is seen. RAWS = {phase, i, done}.
local function raws_lists()
    local out = {}
    pcall(function() table.insert(out, {'inorganic', df.global.world.raws.inorganics.all}) end)
    if #out == 0 then pcall(function() table.insert(out, {'inorganic', df.global.world.raws.inorganics}) end) end
    pcall(function() table.insert(out, {'plant', df.global.world.raws.plants.all}) end)
    pcall(function() table.insert(out, {'creature', df.global.world.raws.creatures.all}) end)
    return out
end

local function learn_from(mode, raw, mats)
    for _, mat in ipairs(mats) do
        local list = mat_syndrome_list(mat)
        if #list > 0 then
            local okn, name = pcall(function() return mat.state_name.Liquid ~= '' and mat.state_name.Liquid
                                                   or mat.state_name.Solid end)
            local id = mode == 'creature' and raw.creature_id or raw.id
            local what = (okn and name and name ~= '') and txt(name) or tostring(mat.id or '?')
            for _, sd in ipairs(list) do
                local okid, sid = pcall(function() return sd.id end)
                if okid and sid ~= nil and not SOURCES[sid] then
                    SOURCES[sid] = {kind = source_kind(mode, id), what = what, id = id}
                end
            end
        end
    end
end

function raws_step(budget)
    RAWS = RAWS or {phase = 1, i = 0}
    if RAWS.done then return true end
    local t0 = os.clock()
    local lists = raws_lists()
    while RAWS.phase <= #lists do
        local mode, list = lists[RAWS.phase][1], lists[RAWS.phase][2]
        local n = vlen(list)
        while RAWS.i < n do
            local raw = vget(list, RAWS.i)
            RAWS.i = RAWS.i + 1
            pcall(function()
                if mode == 'inorganic' then learn_from(mode, raw, {raw.material})
                else
                    local mats = {}
                    for _, m in ipairs(raw.material) do mats[#mats + 1] = m end
                    learn_from(mode, raw, mats)
                end
            end)
            if ms_since(t0) >= budget then return false end
        end
        RAWS.phase, RAWS.i = RAWS.phase + 1, 0
    end
    RAWS.done = true
    return true
end

-- --- the citizens ------------------------------------------------------------

local function citizens()
    local ok, l = pcall(U.citizens)
    return ok and l or {}
end

-- The syndrome materials on a unit's body: list of material cache entries
local function body_carries(u)
    local out = {}
    pcall(function()
        local v = u.body.spatters
        for i = 0, vlen(v) - 1 do
            local sp = vget(v, i)
            local mt, mi = spatter_mat(sp)
            local m = mt and material_syndromes(mt, mi)
            if m and m.contact then out[#out + 1] = m end
        end
    end)
    return out
end

-- The citizens carrying a contact syndrome on their bodies: {id = names}
function carriers()
    local out = {}
    for _, u in ipairs(citizens()) do
        local c = body_carries(u)
        if #c > 0 then
            local names, seen = {}, {}
            for _, m in ipairs(c) do
                if not seen[m.name] then seen[m.name] = true; table.insert(names, m.name) end
            end
            out[u.id] = {u = u, materials = names}
        end
    end
    return out
end

local function syndrome_age_days(a)
    local ok, t = pcall(function() return a.ticks end)
    if ok and type(t) == 'number' then return t // 1200 end
    return nil
end

-- --- the floors: a pass in slices ----------------------------------------------

PASS, LAST = PASS, LAST

local function fort_boxes()
    -- (0.105.46, I6) every building walked once a report for the boxes (U.report_memo),
    -- not once for each of the syndromes', miasma's and cleanup's reads
    local function build()
        local ok, C = pcall(reqscript, 'ai-cleanup')
        if ok and C and C.fort_boxes then
            local okb, b = pcall(C.fort_boxes)
            if okb and b then return b end
        end
        return {}
    end
    if U.report_memo then return U.report_memo('fort_boxes', build) end
    return build()
end

-- The map blocks in the fort's built-up areas: {{x, y, z}} (block coordinates)
function fort_block_list(boxes)
    local out = {}
    local zs = {}
    for z in pairs(boxes) do zs[#zs + 1] = z end
    table.sort(zs)
    for _, z in ipairs(zs) do
        local bx = boxes[z]
        for x = math.max(0, bx.x1) // 16, math.max(0, bx.x2) // 16 do
            for y = math.max(0, bx.y1) // 16, math.max(0, bx.y2) // 16 do
                table.insert(out, {x, y, z})
            end
        end
    end
    return out
end

local function get_block(c)
    local ok, b = pcall(dfhack.maps.getBlock, c[1], c[2], c[3])
    if ok then return b end
    return nil
end

local function is_spatter(ev)
    local ok, yes = pcall(function()
        return ev:getType() == df.block_square_event_type.material_spatter
    end)
    return ok and yes
end

-- tiles covered by an event (its amount grid)
local function event_tiles(ev)
    local n = 0
    pcall(function()
        for x = 0, 15 do
            for y = 0, 15 do
                if ev.amount[x][y] > 0 then n = n + 1 end
            end
        end
    end)
    return n
end

-- One block: its syndrome spatter events {ev, index, m}
local function block_syndrome_events(b)
    local out = {}
    pcall(function()
        local evs = b.block_events
        for j = 0, vlen(evs) - 1 do
            local ev = vget(evs, j)
            if ev and is_spatter(ev) then
                local okm, mt, mi = pcall(function() return ev.mat_type, ev.mat_index end)
                local m = okm and material_syndromes(mt, mi)
                if m then table.insert(out, {ev = ev, j = j, m = m}) end
            end
        end
    end)
    return out
end

local function new_pass(t)
    return {started = t, cursor = 0, events = 0, tiles = 0, blocks = 0, contact_tiles = 0, materials = {},
            list = fort_block_list(fort_boxes())}
end

-- A slice of the floor pass; returns the last finished pass.
function floor_step(budget)
    local t = now_tick()
    if not PASS then
        if LAST and t - (LAST.started or 0) < PASS_TICKS and t >= (LAST.started or 0) then return LAST end
        PASS = new_pass(t)
    end
    local n = #PASS.list
    local t0 = os.clock()
    while PASS.cursor < n and ms_since(t0) < budget do
        PASS.cursor = PASS.cursor + 1
        local b = get_block(PASS.list[PASS.cursor])
        if b then
            local evs = block_syndrome_events(b)
            if #evs > 0 then
                PASS.blocks = PASS.blocks + 1
                for _, e in ipairs(evs) do
                    local nt = event_tiles(e.ev)
                    PASS.events = PASS.events + 1
                    PASS.tiles = PASS.tiles + nt
                    if e.m.contact then PASS.contact_tiles = PASS.contact_tiles + nt end
                    PASS.materials[e.m.name] = (PASS.materials[e.m.name] or 0) + nt
                end
            end
        end
    end
    if PASS.cursor >= n then
        LAST = {started = PASS.started, done = t, tiles = PASS.tiles, contact_tiles = PASS.contact_tiles,
                events = PASS.events, blocks = PASS.blocks, materials = PASS.materials}
        PASS = nil
    end
    return LAST
end

-- --- the quarantine (read by ai-society-burrows) ------------------------------

QCACHE = QCACHE

function quarantine_state()
    local d = U.site_get(QUARANTINE_KEY, {ids = {}})
    if type(d) ~= 'table' then d = {ids = {}} end
    d.ids = type(d.ids) == 'table' and d.ids or {}
    return d
end

-- (fix5) a squad member: the hospital burrow never holds one (ai-society-
-- burrows leaves soldiers out), so the quarantine leaves them out too
function in_squad(u)
    local ok, sq = pcall(function() return u.military.squad_id end)
    return ok and tonumber(sq) ~= nil and tonumber(sq) ~= -1
end

-- Is the unit (id) in quarantine now? Read once a game tick.
function quarantined(id)
    local t = now_tick()
    if not QCACHE or QCACHE.t ~= t then
        local set = {}
        for k, v in pairs(quarantine_state().ids) do
            local untl = tonumber(type(v) == 'table' and v.till or v)
            if untl and untl > t then set[tonumber(k)] = true end
        end
        QCACHE = {t = t, set = set}
    end
    return QCACHE.set[tonumber(id)] == true
end

function quarantine(o, dry_run)
    o = o or {}
    local days = tonumber(o.days) or QUARANTINE_DAYS
    local max = tonumber(o.max) or QUARANTINE_MAX
    local t = now_tick()
    local d = quarantine_state()
    local out = {ok = true, added = {}, kept = 0, released = {}, dry_run = dry_run or nil}
    if o.release then
        for k in pairs(d.ids) do table.insert(out.released, tonumber(k) or k) end
        d.ids = {}
    else
        local car = carriers()
        local n = 0
        for k, v in pairs(d.ids) do
            local id = tonumber(k)
            local untl = tonumber(type(v) == 'table' and v.till or v) or 0
            local okf, mu = pcall(df.unit.find, id)
            if okf and mu and in_squad(mu) then        -- (fix5) drafted since: not held, so not counted
                d.ids[k] = nil
                table.insert(out.released, id)
            elseif car[id] then
                d.ids[k] = {till = t + days * 1200, since = type(v) == 'table' and v.since or t}
                n = n + 1
            elseif untl <= t then
                d.ids[k] = nil
                table.insert(out.released, id)
            else
                n = n + 1
            end
        end
        out.kept = n
        local ids = {}
        local soldiers = 0
        for id, c in pairs(car) do
            if in_squad(c.u) then soldiers = soldiers + 1 else ids[#ids + 1] = id end
        end
        if soldiers > 0 then out.soldiers = soldiers end
        table.sort(ids)
        for _, id in ipairs(ids) do
            if not d.ids[tostring(id)] then
                if n >= max then out.capped = true break end
                d.ids[tostring(id)] = {till = t + days * 1200, since = t}
                n = n + 1
                table.insert(out.added, {id = id, name = unit_name(car[id].u), carries = car[id].materials})
            end
        end
        out.members = n
    end
    if #out.added == 0 and #out.released == 0 then out.unchanged = true end
    if not dry_run then
        U.site_put(QUARANTINE_KEY, d)
        QCACHE = nil
    end
    return out
end

-- --- cleaning ------------------------------------------------------------------

-- Take the syndrome spatter off a vector of spatters; returns how many.
local function clean_vector(v, dry_run)
    local n = 0
    for i = vlen(v) - 1, 0, -1 do
        local sp = vget(v, i)
        local mt, mi = spatter_mat(sp)
        if mt and material_syndromes(mt, mi) then
            if dry_run then n = n + 1
            elseif pcall(verase, v, i) then
                free(sp)
                n = n + 1
            end
        end
    end
    return n
end

local function item_contaminants(it)
    local ok, v = pcall(function() return it.contaminants end)
    if ok and v ~= nil then return v end
    return nil
end

-- o.units (default true), o.tiles (default true), o.budget_ms
function clean(o, dry_run)
    o = o or {}
    local t0 = os.clock()
    local budget = math.max(10, math.min(500, tonumber(o.budget_ms) or ACTION_BUDGET_MS))
    local res = {ok = true, units = 0, unit_spatter = 0, items = 0, tile_events = 0, tiles = 0,
                 dry_run = dry_run or nil, materials = {}}
    if o.units ~= false then
        for _, u in ipairs(citizens()) do
            local got = 0
            pcall(function() got = clean_vector(u.body.spatters, dry_run) end)
            pcall(function()
                for _, inv in ipairs(u.inventory) do
                    local v = item_contaminants(inv.item)
                    if v then
                        local k = clean_vector(v, dry_run)
                        if k > 0 then res.items = res.items + 1; got = got + k end
                    end
                end
            end)
            if got > 0 then
                res.units = res.units + 1
                res.unit_spatter = res.unit_spatter + got
            end
        end
    end
    if o.tiles ~= false then
        local list = fort_block_list(fort_boxes())
        local n = #list
        local i = (CLEAN_CURSOR or 0) % math.max(1, n)
        local walked = 0
        while walked < n and ms_since(t0) < budget do
            local b = get_block(list[i + 1])
            if b then
                local evs = block_syndrome_events(b)
                for k = #evs, 1, -1 do       -- the highest index first: erasing keeps the others' indices
                    local e = evs[k]
                    local nt = event_tiles(e.ev)
                    local done = dry_run or pcall(verase, b.block_events, e.j)
                    if done then
                        if not dry_run then free(e.ev) end
                        res.tile_events = res.tile_events + 1
                        res.tiles = res.tiles + nt
                        res.materials[e.m.name] = (res.materials[e.m.name] or 0) + nt
                    end
                end
            end
            i = (i + 1) % math.max(1, n)
            walked = walked + 1
        end
        res.walked, res.of = walked, n
        res.more = walked < n or nil
        if not dry_run then CLEAN_CURSOR = i end
        if not dry_run and LAST and not res.more then
            LAST.tiles, LAST.contact_tiles, LAST.events, LAST.materials = 0, 0, 0, {}
        end
    end
    if not next(res.materials) then res.materials = nil end
    if not dry_run and res.unit_spatter == 0 and res.tile_events == 0 and not res.more then
        res.ok, res.rejected, res.error = false, true, 'no syndrome-carrying spatter on the citizens or the fort\'s floors'
    end
    res.ms = math.floor(ms_since(t0) + 0.5)
    return res
end

-- --- the report ----------------------------------------------------------------

function report()
    local out = {afflicted = 0, list = {}, by_name = {}, deadly = 0, carriers = 0, carrier_ids = {}, soldier_carriers = 0,
                 sources = {}, unknown_sources = 0}
    local car = carriers()
    local unknown = false
    for _, u in ipairs(citizens()) do
        local syns = {}
        pcall(function()
            for _, a in ipairs(u.syndromes.active) do
                local info = syndrome_info(a.type)
                local src = SOURCES[a.type]
                local row = {id = a.type, name = info.name, days = syndrome_age_days(a), routes = info.routes,
                             deadly = info.deadly or nil, effects = info.effects,
                             source = src and src.kind or nil, source_what = src and src.what or nil}
                if not src then unknown = true end
                table.insert(syns, row)
            end
        end)
        if #syns > 0 then
            out.afflicted = out.afflicted + 1
            local deadly = false
            for _, r in ipairs(syns) do
                out.by_name[r.name] = (out.by_name[r.name] or 0) + 1
                local k = r.source or 'unknown'
                out.sources[k] = (out.sources[k] or 0) + 1
                if not r.source then out.unknown_sources = out.unknown_sources + 1 end
                if r.deadly then deadly = true end
            end
            if deadly then out.deadly = out.deadly + 1 end
            if #out.list < LIST_MAX then
                table.insert(out.list, {id = u.id, name = unit_name(u), syndromes = syns,
                                        carrier = car[u.id] and true or nil,
                                        carries = car[u.id] and car[u.id].materials or nil,
                                        quarantined = quarantined(u.id) or nil})
            end
        end
    end
    for id, c in pairs(car) do
        out.carriers = out.carriers + 1
        if in_squad(c.u) then out.soldier_carriers = out.soldier_carriers + 1 end
        if #out.carrier_ids < 100 then table.insert(out.carrier_ids, id) end
        local listed = false
        for _, r in ipairs(out.list) do if r.id == id then listed = true break end end
        if not listed and #out.list < LIST_MAX then
            table.insert(out.list, {id = id, name = unit_name(c.u), syndromes = {}, carrier = true,
                                    carries = c.materials, quarantined = quarantined(id) or nil})
        end
    end
    table.sort(out.carrier_ids)
    if unknown then
        local okr, done = pcall(raws_step, RAWS_BUDGET_MS)
        out.raws_walked = okr and done or false
    end
    local okf, floors = pcall(floor_step, BUDGET_MS)
    if okf and floors then
        out.floors = {tiles = floors.tiles, contact_tiles = floors.contact_tiles, blocks = floors.blocks,
                      materials = floors.materials, at = floors.done}
    elseif not okf then
        out.floors = {error = tostring(floors):sub(1, 160)}
    end
    local q = quarantine_state()
    local qn, t = 0, now_tick()
    for k, v in pairs(q.ids) do
        local untl = tonumber(type(v) == 'table' and v.till or v)
        local okf, mu = pcall(df.unit.find, tonumber(k))
        if untl and untl > t and not (okf and mu and in_squad(mu)) then qn = qn + 1 end   -- (fix5) a soldier isn't held
    end
    out.quarantined = qn
    if out.soldier_carriers == 0 then out.soldier_carriers = nil end
    if not next(out.by_name) then out.by_name = nil end
    if not next(out.sources) then out.sources = nil end
    return out
end

-- --- miasma ----------------------------------------------------------------------

local function tile_outside(x, y, z)
    local ok, o = pcall(function()
        local f = dfhack.maps.getTileFlags(x, y, z)
        return f and f.outside
    end)
    return ok and o == true
end

-- (fix5) a cavern tile (the same test as ai-disposal's and ai-threats')
local function tile_cavern(x, y, z)
    local ok, c = pcall(function()
        local f = dfhack.maps.getTileFlags(x, y, z)
        return f and (f.feature_global or f.feature_local) and true or false
    end)
    return ok and c == true
end

-- (fix5) the walk groups the citizens stand in ({[g] = true}), nil when the game can't say
local function citizen_groups()
    local set, any = {}, false
    for _, u in ipairs(citizens()) do
        local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(u.pos) end)
        if ok and type(g) == 'number' then
            any = true
            if g ~= 0 then set[g] = true end
        end
    end
    return any and set or nil
end

local function tile_reached(groups, x, y, z)
    if not groups then return true end                  -- the game can't say: as before
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) end)
    if not ok or type(g) ~= 'number' then return true end
    return groups[g] == true
end

-- (fix5) a butcher's shop stands in the fort
local function has_butcher()
    local found = false
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            local ok, yes = pcall(function()
                return b:getType() == df.building_type.Workshop and df.workshop_type[b.type] == 'Butchers'
            end)
            if ok and yes then found = true break end
        end
    end)
    return found
end

-- (fix5) a body the butcher would take (as ai-provisions counts them): a
-- whole corpse not yet butchered, not rotten, of no sapient race
local SAPIENT = {}
local function sapient(race)
    if race == nil then return true end
    if SAPIENT[race] == nil then
        local ok, v = pcall(function()
            local cr = df.creature_raw.find(race)
            for _, c in ipairs(cr.caste) do
                if c.flags.CAN_SPEAK or c.flags.CAN_LEARN then return true end
            end
            return false
        end)
        SAPIENT[race] = not ok or v == true
    end
    return SAPIENT[race]
end

function for_butcher(it, kind)
    if kind ~= 'CORPSE' then return false end
    local ok, yes = pcall(function()
        return not it.flags.rotten and it.corpse_flags.unbutchered == true and not sapient(it.race)
    end)
    return ok and yes == true
end

-- the garbage dump zones: {x, y, z, outside}
function dump_zones()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            local okz, isz = pcall(function() return b:getType() == df.building_type.Civzone end)
            if okz and isz then
                local t = df.civzone_type[b.type]
                if t == 'Dump' or t == 'GarbageDump' then
                    local cx, cy = (b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2
                    table.insert(out, {id = b.id, x = cx, y = cy, z = b.z, outside = tile_outside(cx, cy, b.z),
                                       x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2})
                end
            end
        end
    end)
    return out
end

local function in_dump(dumps, x, y, z)
    for _, d in ipairs(dumps) do
        if d.z == z and x >= d.x1 and x <= d.x2 and y >= d.y1 and y <= d.y2 then return true end
    end
    return false
end

-- the miasma flows grouped by block: {key = {x, y, z, n, density, indoor, living}}.
-- (fix5) Only the living areas' spots (indoors, within the fort's built-up
-- areas, no cavern tile): what rots in the caverns or far off is no one's
-- to haul (tiles/indoor still count every flow, for the report).
local function miasma_blocks(boxes)
    local spots, tiles, indoor, living = {}, 0, 0, 0
    local okm, kind = pcall(function() return df.flow_type.Miasma end)
    if not okm then return spots, 0, 0, 0 end
    pcall(function()
        local flows = df.global.flows
        -- (0.105.46, I6) only the miasma flows (U.flows_where: the flows walked once a report)
        if U.flows_where then
            local okw, l = pcall(U.flows_where, function(t) return t == kind end)
            if okw and l then flows = l end
        end
        local n = math.min(vlen(flows), MIASMA_FLOWS_MAX)
        for i = 0, n - 1 do
            local f = vget(flows, i)
            local ok, t, d, x, y, z = pcall(function() return f.type, f.density, f.pos.x, f.pos.y, f.pos.z end)
            if ok and t == kind and (d or 0) > 0 and x and x >= 0 then
                tiles = tiles + 1
                local inside = not tile_outside(x, y, z)
                local bx = boxes[z]
                local near = bx ~= nil and x >= bx.x1 and x <= bx.x2 and y >= bx.y1 and y <= bx.y2
                if inside then indoor = indoor + 1 end
                local spot = inside and near and not tile_cavern(x, y, z)
                if spot then living = living + 1 end
                if spot then
                    local key = (x // 16) .. ',' .. (y // 16) .. ',' .. z
                    local s = spots[key]
                    if not s then
                        s = {bx = x // 16, by = y // 16, x = x, y = y, z = z, n = 0, density = 0, living = 0}
                        spots[key] = s
                    end
                    s.n = s.n + 1
                    s.density = math.max(s.density, d)
                    s.living = s.living + 1
                end
            end
        end
    end)
    return spots, tiles, indoor, living
end

local function block_items(x, y, z)
    local ok, b = pcall(dfhack.maps.getTileBlock, x, y, z)
    if not ok or not b then return {} end
    local out = {}
    pcall(function()
        for _, id in ipairs(b.items) do out[#out + 1] = id end
    end)
    return out
end

local function in_stockpile(x, y, z)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if not ok or not b then return false end
    local okt, sp = pcall(function() return b:getType() == df.building_type.Stockpile end)
    return okt and sp
end

-- What rots near the worst indoor spots: a list of {it, kind, what, x, y, z, side}.
local function rotting_near(spots, max_spots)
    local list = {}
    for _, s in pairs(spots) do list[#list + 1] = s end
    table.sort(list, function(a, b)
        if a.living ~= b.living then return a.living > b.living end
        return a.n > b.n
    end)
    local seen_block, seen_item, found = {}, {}, {}
    local looked = 0
    for i = 1, math.min(#list, max_spots) do
        local s = list[i]
        for dz = 0, -1, -1 do
            for dx = -1, 1 do
                for dy = -1, 1 do
                    local bx, by = (s.bx + dx) * 16, (s.by + dy) * 16
                    local key = bx .. ',' .. by .. ',' .. (s.z + dz)
                    if bx >= 0 and by >= 0 and not seen_block[key] then
                        seen_block[key] = true
                        for _, id in ipairs(block_items(bx, by, s.z + dz)) do
                            looked = looked + 1
                            if looked > MIASMA_ITEMS_MAX then return found, true end
                            if not seen_item[id] then
                                seen_item[id] = true
                                local okf, it = pcall(df.item.find, id)
                                if okf and it then
                                    local kind = U.item_kind(it)
                                    local rotten = false
                                    pcall(function() rotten = it.flags.rotten == true end)
                                    if kind and (BODY_KINDS[kind] or (FOOD_KINDS[kind] and rotten)) then
                                        local x, y, z = U.item_pos(it)
                                        if x and not tile_outside(x, y, z) and not tile_cavern(x, y, z) then
                                            table.insert(found, {it = it, kind = kind, x = x, y = y, z = z})
                                        end
                                    end
                                end
                            end
                        end
                    end
                end
            end
        end
    end
    return found, false
end

-- Why a rotting thing is left alone by clear_miasma (nil: it may be marked);
-- the second value: unforbid it too (another's body the game forbade).
function keep_rotting(e, ctx, dumps)
    local it = e.it
    local f = it.flags
    if f.removed or f.garbage_collect then return 'gone' end
    if U.fort_remains(it, e.kind, ctx) then return 'own_dead' end
    if f.artifact then return 'artifact' end
    if f.dump then return 'marked' end
    if f.in_job then return 'in_job' end
    if f.owned then return 'owned' end
    if f.trader then return 'trader' end
    if f.in_building or f.construction then return 'in_building' end
    if not U.on_ground(it) then return 'held' end
    if in_dump(dumps, e.x, e.y, e.z) then return 'in_dump' end
    -- (fix5) no hauler sent near a danger, into the caverns, or where none can walk
    if U.near_danger(ctx.danger, e.x, e.y, e.z) then return 'danger' end
    if tile_cavern(e.x, e.y, e.z) then return 'cavern' end
    if not tile_reached(ctx.groups, e.x, e.y, e.z) then return 'unreachable' end
    -- (fix5) a body waiting for the butcher, while there is one's shop
    if ctx.butcher and for_butcher(it, e.kind) then return 'for_butcher' end
    if in_stockpile(e.x, e.y, e.z) then return 'in_pile' end
    if f.forbid then
        local why = U.forbidden_reason(it, ctx, e.kind, e.x, e.y, e.z)
        if why == 'other_dead' then return nil, true end
        return 'forbidden'
    end
    return nil, false
end

local function miasma_scan()
    local boxes = fort_boxes()
    local spots, tiles, indoor, living = miasma_blocks(boxes)
    local found, capped = rotting_near(spots, MIASMA_SPOTS)
    return {spots = spots, tiles = tiles, indoor = indoor, living = living, found = found, capped = capped}
end

local function ctx_for(dumps)
    local ctx = U.forbid_context({in_dump = function(x, y, z) return in_dump(dumps, x, y, z) end,
                                  in_stockpile = in_stockpile})
    local okd, spots = pcall(U.danger_spots)
    ctx.danger = okd and spots or {}
    local okg, groups = pcall(citizen_groups)
    ctx.groups = okg and groups or nil
    ctx.butcher = has_butcher()
    return ctx
end

function miasma_report()
    local m = miasma_scan()
    local dumps = dump_zones()
    local out = {tiles = m.tiles, indoor = m.indoor, living = m.living, spots = {}, sources = {}, items = {},
                 markable = 0, capped = m.capped or nil, dumps = #dumps, dump_outside = 0, kept = {}}
    for _, d in ipairs(dumps) do if d.outside then out.dump_outside = out.dump_outside + 1 end end
    local list = {}
    for _, s in pairs(m.spots) do list[#list + 1] = s end
    table.sort(list, function(a, b) return a.n > b.n end)
    for i = 1, math.min(#list, 8) do
        local s = list[i]
        table.insert(out.spots, {x = s.x, y = s.y, z = s.z, tiles = s.n, density = s.density,
                                 living = s.living > 0 or nil})
    end
    local ctx = ctx_for(dumps)
    for _, e in ipairs(m.found) do
        local why = keep_rotting(e, ctx, dumps)
        local k = why == 'own_dead' and 'own_dead' or (BODY_KINDS[e.kind] and (e.kind == 'REMAINS' and 'remains'
                  or 'corpse') or 'food')
        out.sources[k] = (out.sources[k] or 0) + 1
        if why then out.kept[why] = (out.kept[why] or 0) + 1 else out.markable = out.markable + 1 end
        if #out.items < MIASMA_LIST then
            local okd, what = pcall(function() return txt(dfhack.items.getDescription(e.it, 0, true)) end)
            table.insert(out.items, {id = e.it.id, kind = e.kind, what = okd and what or e.kind,
                                     x = e.x, y = e.y, z = e.z, kept = why})
        end
    end
    if not next(out.sources) then out.sources = nil end
    if not next(out.kept) then out.kept = nil end
    return out
end

function clear_miasma(o, dry_run)
    o = o or {}
    local max = math.max(1, math.min(CLEAR_MAX, tonumber(o.max) or 50))
    local dumps = dump_zones()
    local outside = false
    for _, d in ipairs(dumps) do if d.outside then outside = true end end
    if not outside then
        return {ok = false, rejected = true, error = 'no garbage dump zone under the sky: the rotting things '
                                                     .. 'would only be carried to an indoor one'}
    end
    local m = miasma_scan()
    local ctx = ctx_for(dumps)
    local res = {ok = true, marked = 0, unforbidden = 0, kept = {}, dry_run = dry_run or nil, kinds = {}}
    for _, e in ipairs(m.found) do
        local why, unforbid = keep_rotting(e, ctx, dumps)
        if why then
            res.kept[why] = (res.kept[why] or 0) + 1
        elseif res.marked >= max then
            res.capped = true
        else
            if not dry_run then
                pcall(function()
                    if unforbid then e.it.flags.forbid = false end
                    e.it.flags.dump = true
                end)
            end
            res.marked = res.marked + 1
            if unforbid then res.unforbidden = res.unforbidden + 1 end
            res.kinds[e.kind] = (res.kinds[e.kind] or 0) + 1
        end
    end
    if not next(res.kept) then res.kept = nil end
    if res.marked == 0 then
        res.ok, res.rejected = false, true
        res.error = 'nothing rotting near the miasma that the AI may mark for the dump'
    end
    return res
end
