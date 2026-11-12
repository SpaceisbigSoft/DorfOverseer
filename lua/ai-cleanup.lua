-- (0.105.40, Phase 13e) World cleanup: what slows the game down over years
-- of unattended play, counted and (only past the brain's thresholds) taken
-- off the map. The player (11 Nov): "the game slows down for various
-- reasons, automate cleanup as much as possible to keep performance high;
-- some things dwarves can clean up, some need DFHack. Unreachable
-- items/enemies may need to be deleted if they reach certain thresholds."
--
-- Dwarves first: loose refuse, forbidden clutter, the dump and the dead are
-- seen to by the existing rules (lua/ai-disposal.lua, prune_remains,
-- remove_webs, scrub_dead_units, the burial and refuse standing orders).
-- What is here is what no dwarf can do:
--   report()              the `cleanup` report section: items by state,
--                         unreachable items (no citizen's walk group reaches
--                         their tile) and for how long, loose refuse, the
--                         spatter (blood, vomit...) on the map, dead and
--                         inactive units, unreachable hostile and wild
--                         creatures and for how long, flowing water blocks.
--                         Walked in time-budgeted slices (BUDGET_MS a call),
--                         one full pass at most a game day; between, the
--                         last pass is sent as it was (cheap).
--   cleanup_items(o, dry)       unreachable items, unreachable for a year,
--                               oldest first, a batch (o.max) a call;
--   cleanup_units(o, dry)       unreachable hostile or wild creatures that
--                               are no historical figure, unreachable a season
--                               (vaporized, as DFHack's exterminate does: no
--                               corpse, what they carry drops);
--   cleanup_spatter(o, dry)     the spatter on the map's blocks outside the
--                               fort's built-up areas (o.scope 'all': inside
--                               too), as DFHack's `clean map` does (mud and
--                               snow kept: farms need the mud);
--   cleanup_dead_units(o, dry)  long-dead units nobody refers to taken off the
--                               game's active list, as DFHack's fix/dead-units
--                               does (the unit itself is kept in units.all, so
--                               nothing that refers to it dangles).
--
-- Never deleted (cleanup_items): an artifact or anything named or written
-- (a book's or a scroll's writing), an item owned by a unit, anything not
-- lying loose on the ground (in a building, a bin, a barrel, a hand), a
-- container, an item on a building's tile or in a stockpile, a construction
-- or a building's part, the player's things (forbidden for no reason the
-- game gives: ai-util forbidden_reason 'unknown') and the AI's cistern's,
-- the fort's own dead and their belongings, evidence of a murder, a trader's
-- goods, anything a job holds (in_job, or listed in a job's items), an item
-- of a kind a strange mood is waiting for, the squads' assigned gear, a
-- spider web (remove_webs sees to those). Artifact petitions ask for
-- artifacts (never deleted); work orders name kinds, not items.
-- Never removed (cleanup_units): citizens, residents, the fort's own, pets,
-- tame or domestic animals, visitors, merchants, diplomats, prisoners (caged
-- or chained), historical figures, a rider or a mount, the dead.
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/cleanup'
BUDGET_MS = 40               -- a report call's walk at most (ms of os.clock)
ACTION_BUDGET_MS = 250       -- an action's walk at most
PASS_TICKS = 1200            -- a full pass at most once a game day
ITEM_TRACK_MAX = 30000       -- unreachable items followed at most (their first-seen tick)
UNIT_TRACK_MAX = 2000
SPATTER_COUNT_MAX = 500000   -- spatter events counted at most (the count says capped past it)
MAX_ITEMS = 500              -- items deleted a call at most
MAX_UNITS = 100              -- creatures removed a call at most
MAX_DEAD = 2000              -- dead units taken off the active list a call at most
FORT_MARGIN = 10             -- the built-up areas: the box round the buildings of a level, this much wider
LIST_MAX = 10                -- unreachable creatures listed in the report at most
YEAR = 403200
SEASON = 100800
REFUSE = {CORPSE = true, CORPSEPIECE = true, REMAINS = true}
-- the builtin materials and states DFHack's clean keeps by default
MUD, WATER, SOLID, POWDER = 12, 6, 0, 3

-- --- helpers ---------------------------------------------------------------

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function ms_since(t0) return (os.clock() - t0) * 1000 end

-- a df vector (userdata, 0-based) or a Lua list (the tests', 1-based)
local function vlen(v)
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

local function fort_id()
    local okd, dir = pcall(function() return df.global.world.cur_savegame.save_dir end)
    local oks, site = pcall(function() return df.global.plotinfo.site_id end)
    return tostring(okd and dir or '?') .. '#' .. tostring(oks and site or '?')
end

-- a flag that this DF version may not have: nil, not an error
local function fl(t, k)
    local ok, v = pcall(function() return t[k] end)
    return ok and v or nil
end

local function is(f, u)
    if type(f) ~= 'function' then return false end
    local ok, v = pcall(f, u)
    return ok and v == true
end

-- --- what is followed (kept in the save's site data) -----------------------

-- ST: {fort, items = {[id] = first tick unreachable}, units = {...}, n_items,
-- n_units, pass (the walk under way), last (the last full pass, the report)}
local function pack(map)
    local out = {}
    for id, t in pairs(map) do out[#out + 1] = id; out[#out + 1] = t end
    return out
end

local function unpack_list(list, max)
    local map, n = {}, 0
    if type(list) ~= 'table' then return map, 0 end
    for i = 1, #list - 1, 2 do
        local id, t = math.tointeger(list[i]), math.tointeger(list[i + 1])
        if id and t and n < max then map[id] = t; n = n + 1 end
    end
    return map, n
end

function state()
    local f = fort_id()
    if type(ST) ~= 'table' or ST.fort ~= f then
        local d = U.site_get(SITE_KEY, {})
        local items, ni = unpack_list(d.items, ITEM_TRACK_MAX)
        local units, nu = unpack_list(d.units, UNIT_TRACK_MAX)
        ST = {fort = f, items = items, units = units, n_items = ni, n_units = nu, pass = nil, last = nil,
              passes = 0, spatter_cursor = 0}
    end
    return ST
end

function save_state()
    local st = state()
    return U.site_put(SITE_KEY, {items = pack(st.items), units = pack(st.units), tick = now_tick()})
end

-- for the tests: forget everything (a new fort)
function reset()
    ST = nil
end

local function track(st, kind, id, t)
    local map = st[kind]
    if map[id] then return map[id] end
    local cnt, max = 'n_' .. kind, kind == 'items' and ITEM_TRACK_MAX or UNIT_TRACK_MAX
    if st[cnt] >= max then return nil end
    map[id] = t
    st[cnt] = st[cnt] + 1
    return t
end

local function untrack(st, kind, id)
    if st[kind][id] then
        st[kind][id] = nil
        st['n_' .. kind] = st['n_' .. kind] - 1
    end
end

-- --- reach -----------------------------------------------------------------

-- the walk groups the citizens stand in (nil: none can be read)
function citizen_groups()
    local set, any = {}, false
    local ok = pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local okp, x, y, z = pcall(dfhack.units.getPosition, u)
            if okp and x then
                local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
                if okg and type(g) == 'number' then
                    any = true
                    if g ~= 0 then set[g] = true end
                end
            end
        end
    end)
    if ok and any and next(set) ~= nil then return set end
    return nil
end

local function group_at(x, y, z)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x, y, z))
    if ok and type(g) == 'number' then return g end
    return nil
end

-- true / false, or nil when the game can't say. A tile in no walk group (0)
-- is reached from a neighbour on its level that a citizen's group holds.
function tile_reachable(groups, x, y, z)
    if not groups then return nil end
    local g = group_at(x, y, z)
    if g == nil then return nil end
    if g ~= 0 then return groups[g] == true end
    for dx = -1, 1 do
        for dy = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                local n = group_at(x + dx, y + dy, z)
                if n and n ~= 0 and groups[n] then return true end
            end
        end
    end
    return false
end

-- --- the built-up areas ----------------------------------------------------

-- per level, the box round its buildings (rooms, workshops, stockpiles,
-- zones), FORT_MARGIN wider
function fort_boxes()
    local boxes = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.all) do
            local ok, z, x1, y1, x2, y2 = pcall(function() return b.z, b.x1, b.y1, b.x2, b.y2 end)
            if ok and type(z) == 'number' and type(x1) == 'number' and x1 >= 0 then
                local bx = boxes[z]
                if not bx then boxes[z] = {x1 = x1, y1 = y1, x2 = x2, y2 = y2}
                else
                    bx.x1, bx.y1 = math.min(bx.x1, x1), math.min(bx.y1, y1)
                    bx.x2, bx.y2 = math.max(bx.x2, x2), math.max(bx.y2, y2)
                end
            end
        end
    end)
    for _, bx in pairs(boxes) do
        bx.x1, bx.y1, bx.x2, bx.y2 = bx.x1 - FORT_MARGIN, bx.y1 - FORT_MARGIN, bx.x2 + FORT_MARGIN, bx.y2 + FORT_MARGIN
    end
    return boxes
end

local function block_in_fort(boxes, x, y, z)
    local bx = boxes[z]
    return bx ~= nil and x + 15 >= bx.x1 and x <= bx.x2 and y + 15 >= bx.y1 and y <= bx.y2
end

-- --- what keeps an item ----------------------------------------------------

-- the kinds of item a strange mood waits for (ai-moods' reading: a dwarf
-- with u.mood >= 0 and his current job's requests), and the items jobs hold
local function mood_and_job_items()
    local types, ids = {}, {}
    pcall(function()
        local l = df.global.world.jobs.list.next
        while l do
            local j = l.item
            if j then pcall(function() for _, ji in ipairs(j.items) do ids[ji.item.id] = true end end) end
            l = l.next
        end
    end)
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            pcall(function()
                if u.mood == nil or u.mood < 0 then return end
                types.any_mood = true
                local job = u.job.current_job
                if not job then return end
                local reqs = job.job_items
                pcall(function() if reqs.elements then reqs = reqs.elements end end)
                for _, ji in ipairs(reqs) do
                    local t = ji.item_type
                    if t == nil or t == -1 then types.all = true      -- a request of any kind: every kind stays
                    else types[t] = true end
                end
            end)
        end
    end)
    return types, ids
end

-- the squads' assigned gear, by id
local function assigned_ids()
    local set = {}
    pcall(function()
        for _, v in pairs(df.global.plotinfo.equipment.items_assigned) do
            pcall(function() for _, id in ipairs(v) do set[id] = true end end)
        end
    end)
    return set
end

-- what one walk (a pass slice, an action) reads once
function item_context()
    local ctx = U.forbid_context()
    ctx.mood_types, ctx.job_ids = mood_and_job_items()
    ctx.assigned = assigned_ids()
    ctx.in_stockpile = function(x, y, z)
        local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
        if not ok or not b then return false end
        local okt, sp = pcall(function() return b:getType() == df.building_type.Stockpile end)
        return okt and sp == true
    end
    return ctx
end

local function has_ref(it, name)
    local ok, r = pcall(function()
        return dfhack.items.getGeneralRef(it, df.general_ref_type[name]) ~= nil
    end)
    return ok and r == true
end

local function written(it)
    local ok, r = pcall(function()
        for _, imp in ipairs(it.improvements) do
            if imp:getType() == df.improvement_type.WRITING or imp:getType() == df.improvement_type.PAGES then
                return true
            end
        end
        return false
    end)
    return ok and r == true
end

-- nil: the item may go; else why it stays (a word). Read on an item seen
-- unreachable (x, y, z its tile).
function item_keep(it, ctx, x, y, z)
    local f = it.flags
    if f.removed or f.garbage_collect then return 'gone' end
    if f.artifact or fl(f, 'artifact_mood') or has_ref(it, 'IS_ARTIFACT') then return 'artifact' end
    if written(it) then return 'named' end
    if f.owned then return 'owned' end
    local oko, owner = pcall(dfhack.items.getOwner, it)
    if oko and owner ~= nil then return 'owned' end
    if f.construction or f.in_building or f.encased then return 'built' end
    if not U.on_ground(it) or f.in_inventory then return 'held' end
    if f.container then return 'container' end
    if f.in_job or ctx.job_ids[it.id] then return 'job' end
    if f.trader then return 'trader' end
    if f.murder then return 'evidence' end
    if f.on_fire then return 'fire' end
    if f.spider_web then return 'web' end
    local kind = U.item_kind(it)
    if f.dead_dwarf or (REFUSE[kind or ''] and U.fort_remains(it, kind, ctx)) then return 'own_dead' end
    if ctx.assigned[it.id] then return 'squad' end
    if ctx.mood_types.any_mood then
        local okt, t = pcall(function() return it:getType() end)
        if ctx.mood_types.all or (okt and ctx.mood_types[t]) then return 'mood' end
    end
    if f.forbid then
        local ok, why = pcall(U.forbidden_reason, it, ctx, kind, x, y, z)
        if not ok or why == 'unknown' then return 'player' end
        if why == 'ai' then return 'ai' end
    elseif x and ctx.cistern[x .. ',' .. y .. ',' .. z] then
        return 'ai'
    end
    local okb, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, z))
    if okb and b then
        local okt, sp = pcall(function() return b:getType() == df.building_type.Stockpile end)
        return (okt and sp) and 'stockpile' or 'building'
    end
    return nil
end

-- --- what keeps a creature -------------------------------------------------

-- nil and its kind ('hostile' or 'wild') when it may go, else why it stays
function unit_keep(u)
    local Un = dfhack.units
    if is(Un.isDead, u) or u.flags2.killed then return 'dead' end
    if Un.isActive and not is(Un.isActive, u) then return 'inactive' end
    if is(Un.isCitizen, u) or is(Un.isResident, u) then return 'citizen' end
    if is(Un.isOwnGroup, u) or is(Un.isOwnCiv, u) then return 'fort' end
    if is(Un.isPet, u) or is(Un.isTame, u) or is(Un.isDomesticated, u) then return 'tame' end
    if is(Un.isVisitor, u) or is(Un.isMerchant, u) or is(Un.isDiplomat, u) or is(Un.isForest, u) then
        return 'visitor'
    end
    local f1 = u.flags1
    if fl(f1, 'caged') or fl(f1, 'chained') or is(Un.isPrisoner, u) then return 'prisoner' end
    if fl(f1, 'rider') or fl(f1, 'ridden') then return 'riding' end
    local okh, hf, hf2 = pcall(function() return u.hist_figure_id, u.hist_figure_id2 end)
    if not okh or (hf or -1) ~= -1 or (hf2 or -1) ~= -1 then return 'historical' end
    if is(Un.isDanger, u) or is(Un.isInvader, u) then return nil, 'hostile' end
    if is(Un.isWildlife, u) or fl(u.flags2, 'roaming_wilderness_population_source') then return nil, 'wild' end
    return 'other'
end

-- --- a dead unit's record --------------------------------------------------

-- the tick a unit died, or nil when the game can't say
local function death_tick(u)
    local ok, t = pcall(function()
        local id = u.counters.death_id
        if id == nil or id < 0 then return nil end
        local inc = df.incident.find(id)
        if not inc then return nil end
        return U.abs_tick(inc.event_year, inc.event_time)
    end)
    return ok and t or nil
end

-- nil: the dead unit's record may leave the active list; else why it stays
function dead_keep(u, now, min_age, fort_race, fort_civ)
    local Un = dfhack.units
    if not (is(Un.isDead, u) or u.flags2.killed) then return 'alive' end
    local ok3, ghost = pcall(function() return u.flags3.ghostly end)
    if ok3 and ghost then return 'ghost' end
    local okc, civ, race, hf = pcall(function() return u.civ_id, u.race, u.hist_figure_id end)
    if not okc then return 'unknown' end
    -- the fort's own: its race, or its civ's historical figures (memorials, ghosts, the dead's names)
    if fort_race ~= nil and race == fort_race and (civ == fort_civ or civ == -1) then return 'own' end
    if is(Un.isCitizen, u) then return 'own' end
    if fort_civ ~= nil and civ == fort_civ and (hf or -1) ~= -1 then return 'own' end
    local oks, squad = pcall(function() return u.military.squad_id end)
    if oks and type(squad) == 'number' and squad ~= -1 then return 'referenced' end
    local okb, nb = pcall(function() return #u.burrows end)
    if okb and nb > 0 then return 'referenced' end
    local t = death_tick(u)
    if t == nil then return 'when' end
    if now - t < min_age then return 'recent' end
    return nil
end

-- --- the pass (the report's walk, in slices) -------------------------------

local function new_pass(t)
    return {phase = 'items', i = 0, tick = t, t_ms = 0, calls = 0,
            items = {total = 0, on_ground = 0, in_buildings = 0, in_containers = 0, forbidden = 0, dump = 0,
                     rotten = 0, artifacts = 0, refuse_loose = 0, unreachable = 0, unreachable_season = 0,
                     unreachable_old = 0, kept = {}, oldest_days = 0, unknown_reach = 0},
            units = {active = 0, all = 0, dead_active = 0, dead_all = 0, inactive_all = 0,
                     unreachable = {hostile = 0, wild = 0}, unreachable_old = 0, dead_removable = 0, list = {}},
            spatter = {events = 0, outside = 0, blocks = 0, capped = false},
            fluids = {blocks = 0},
            seen_items = {}, seen_units = {}}
end

local function bump(t, k) t[k] = (t[k] or 0) + 1 end

-- one item counted; an unreachable one followed
local function pass_item(p, st, it, ctx, groups)
    local f = it.flags
    if f.removed or f.garbage_collect then return end
    local c = p.items
    c.total = c.total + 1
    if f.forbid then c.forbidden = c.forbidden + 1 end
    if f.dump then c.dump = c.dump + 1 end
    if f.rotten then c.rotten = c.rotten + 1 end
    if f.artifact then c.artifacts = c.artifacts + 1 end
    if f.in_building or f.construction then c.in_buildings = c.in_buildings + 1; return end
    if not U.on_ground(it) then c.in_containers = c.in_containers + 1; return end
    c.on_ground = c.on_ground + 1
    local x, y, z = U.item_pos(it)
    if not x then return end
    local kind = U.item_kind(it)
    local reach = tile_reachable(groups, x, y, z)
    if reach == nil then
        c.unknown_reach = c.unknown_reach + 1
        if st.items[it.id] then p.seen_items[it.id] = true end     -- can't say: still followed
        return
    end
    if reach then
        if REFUSE[kind or ''] or f.rotten then c.refuse_loose = c.refuse_loose + 1 end
        untrack(st, 'items', it.id)
        return
    end
    c.unreachable = c.unreachable + 1
    local why = item_keep(it, ctx, x, y, z)
    if why then
        bump(c.kept, why)
        untrack(st, 'items', it.id)
        return
    end
    local first = track(st, 'items', it.id, p.tick)
    p.seen_items[it.id] = true
    if not first then bump(c.kept, 'untracked'); return end
    local age = p.tick - first
    if age >= SEASON then c.unreachable_season = c.unreachable_season + 1 end
    if age >= YEAR then c.unreachable_old = c.unreachable_old + 1 end
    local days = age // 1200
    if days > c.oldest_days then c.oldest_days = days end
end

local function race_name(u)
    local ok, n = pcall(function() return df.creature_raw.find(u.race).creature_id end)
    return ok and n or tostring(u.race)
end

local function pass_unit(p, st, u, groups)
    local c = p.units
    c.active = c.active + 1
    if is(dfhack.units.isDead, u) or u.flags2.killed then
        c.dead_active = c.dead_active + 1
        if not dead_keep(u, p.tick, YEAR, p.race, p.civ) then c.dead_removable = c.dead_removable + 1 end
        return
    end
    local why, kind = unit_keep(u)
    if why then untrack(st, 'units', u.id); return end
    local okp, x, y, z = pcall(dfhack.units.getPosition, u)
    local reach = nil
    if okp and x then reach = tile_reachable(groups, x, y, z) end
    if reach == nil then
        if st.units[u.id] then p.seen_units[u.id] = true end     -- can't say: still followed
        return
    end
    if reach then untrack(st, 'units', u.id); return end
    c.unreachable[kind] = c.unreachable[kind] + 1
    local first = track(st, 'units', u.id, p.tick)
    p.seen_units[u.id] = true
    if not first then return end
    local age = p.tick - first
    if age >= SEASON then c.unreachable_old = c.unreachable_old + 1 end
    if #c.list < LIST_MAX then
        table.insert(c.list, {id = u.id, race = race_name(u), kind = kind, days = age // 1200})
    end
end

local function is_spatter(ev)
    local ok, yes = pcall(function()
        return ev:getType() == df.block_square_event_type.material_spatter
    end)
    return ok and yes
end

local function keep_spatter(ev)
    local ok, mt, ms = pcall(function() return ev.mat_type, ev.mat_state end)
    if not ok then return true end
    return (mt == MUD and ms == SOLID) or (mt == WATER and ms == POWDER)
end

local function pass_block(p, b, boxes)
    local okf, flowing = pcall(function() return b.flags.update_liquid or b.flags.update_liquid_twice end)
    if okf and flowing then p.fluids.blocks = p.fluids.blocks + 1 end
    local s = p.spatter
    if s.capped then return end
    local okp, bx, by, bz = pcall(function() return b.map_pos.x, b.map_pos.y, b.map_pos.z end)
    local inside = okp and block_in_fort(boxes, bx, by, bz)
    local n = 0
    pcall(function()
        for _, ev in ipairs(b.block_events) do
            if is_spatter(ev) and not keep_spatter(ev) then n = n + 1 end
        end
    end)
    if n > 0 then
        s.blocks = s.blocks + 1
        s.events = s.events + n
        if not inside then s.outside = s.outside + n end
        if s.events >= SPATTER_COUNT_MAX then s.capped = true end
    end
end

local function item_list()
    local ok, l = pcall(function() return df.global.world.items.other.IN_PLAY end)
    if ok and l then return l end
    return df.global.world.items.all
end

-- the pass ends: what wasn't seen unreachable this pass is no longer followed
local function finish_pass(st, p)
    -- (a pass with no citizen's walk group read at some slice prunes nothing)
    for _, kind in ipairs(p.blind and {} or {'items', 'units'}) do
        local seen = p['seen_' .. kind]
        for id in pairs(st[kind]) do
            if not seen[id] then untrack(st, kind, id) end
        end
    end
    p.items.tracked, p.units.tracked = st.n_items, st.n_units
    local out = {tick = p.tick, items = p.items, units = p.units, spatter = p.spatter, fluids = p.fluids,
                 groups = p.groups, pass_ms = math.floor(p.t_ms + 0.5), calls = p.calls}
    st.last = out
    st.pass = nil
    st.passes = (st.passes or 0) + 1
    save_state()
    return out
end

-- one slice of the pass, budget_ms at most; returns the finished pass or nil
function step(budget_ms)
    local st = state()
    local t0 = os.clock()
    local now = now_tick()
    local p = st.pass
    if not p then
        if st.last and now >= st.last.tick and now - st.last.tick < PASS_TICKS then return nil end
        p = new_pass(now)
        st.pass = p
    end
    p.calls = p.calls + 1
    local groups = citizen_groups()
    p.groups = 0
    if not groups then p.blind = true end
    if groups then for _ in pairs(groups) do p.groups = p.groups + 1 end end
    p.race, p.civ = U.fort_race_civ()
    local ctx
    local done = false
    while not done and ms_since(t0) < budget_ms do
        if p.phase == 'items' then
            local list = item_list()
            local n = vlen(list)
            ctx = ctx or item_context()
            local stop = math.min(n, p.i + 500)
            while p.i < stop do
                local it = vget(list, p.i)
                p.i = p.i + 1
                if it then pcall(pass_item, p, st, it, ctx, groups) end
            end
            if p.i >= n then p.phase, p.i = 'units', 0 end
        elseif p.phase == 'units' then
            local list = df.global.world.units.active
            local n = vlen(list)
            while p.i < n and ms_since(t0) < budget_ms do
                local u = vget(list, p.i)
                p.i = p.i + 1
                if u then pcall(pass_unit, p, st, u, groups) end
            end
            if p.i >= n then p.phase, p.i = 'units_all', 0 end
        elseif p.phase == 'units_all' then
            local list = df.global.world.units.all
            local n = vlen(list)
            local stop = math.min(n, p.i + 2000)
            local c = p.units
            while p.i < stop do
                local u = vget(list, p.i)
                p.i = p.i + 1
                if u then
                    c.all = c.all + 1
                    pcall(function()
                        if u.flags2.killed or dfhack.units.isDead(u) then c.dead_all = c.dead_all + 1 end
                        if u.flags1.inactive then c.inactive_all = c.inactive_all + 1 end
                    end)
                end
            end
            if p.i >= n then p.phase, p.i = 'blocks', 0 end
        elseif p.phase == 'blocks' then
            local okl, list = pcall(function() return df.global.world.map.map_blocks end)
            local n = okl and vlen(list) or 0
            p.boxes = p.boxes or fort_boxes()
            local stop = math.min(n, p.i + 1000)
            while p.i < stop do
                local b = vget(list, p.i)
                p.i = p.i + 1
                if b then pass_block(p, b, p.boxes) end
            end
            if p.i >= n then done = true end
        else
            done = true
        end
    end
    p.t_ms = p.t_ms + ms_since(t0)
    if done then return finish_pass(st, p) end
    return nil
end

-- the `cleanup` report section
function report()
    local t0 = os.clock()
    local st = state()
    step(BUDGET_MS)
    local out = {}
    if st.last then
        for k, v in pairs(st.last) do out[k] = v end
    else
        local p = st.pass or new_pass(now_tick())
        out = {tick = p.tick, items = p.items, units = p.units, spatter = p.spatter, fluids = p.fluids,
               groups = p.groups, pass_ms = math.floor(p.t_ms + 0.5), calls = p.calls}
        out.partial = true          -- no pass has finished yet: the counts so far
    end
    out.walking = st.pass ~= nil or nil
    out.passes = st.passes
    out.ms = math.floor(ms_since(t0) + 0.5)
    out.limits = {items_year = YEAR, units_season = SEASON, max_items = MAX_ITEMS, max_units = MAX_UNITS}
    return out
end

-- --- the actions -----------------------------------------------------------

local function clamp(v, lo, hi, default)
    local n = math.tointeger(tonumber(v))
    if not n then return default end
    if n < lo then return lo end
    if n > hi then return hi end
    return n
end

local function oldest_first(map)
    local list = {}
    for id, t in pairs(map) do list[#list + 1] = {id = id, t = t} end
    table.sort(list, function(a, b) return a.t < b.t or (a.t == b.t and a.id < b.id) end)
    return list
end

local function no_groups()
    return {ok = false, rejected = true, error = 'no citizen stands in a walk group the game can read: nothing is '
                                                .. 'known to be unreachable'}
end

-- o: max (1-500, default 200), min_age (ticks unreachable, at least a season,
-- default a year), min_count (refused when fewer may go)
function cleanup_items(o, dry_run)
    o = o or {}
    local st = state()
    local t0 = os.clock()
    local max = clamp(o.max, 1, MAX_ITEMS, 200)
    local min_age = clamp(o.min_age, SEASON, 100 * YEAR, YEAR)
    local min_count = clamp(o.min_count, 0, 10000000, 0)
    local groups = citizen_groups()
    if not groups then return no_groups() end
    local now = now_tick()
    local ctx = item_context()
    local res = {ok = true, removed = 0, kept = {}, dry_run = dry_run or nil, candidates = 0, failed = 0,
                 by_type = {}, tracked = st.n_items}
    local pick = {}
    for _, e in ipairs(oldest_first(st.items)) do
        if now - e.t < min_age then break end
        if ms_since(t0) > ACTION_BUDGET_MS then res.cut_short = true; break end
        local it = df.item.find(e.id)
        if not it then
            untrack(st, 'items', e.id)
        else
            local x, y, z = U.item_pos(it)
            local why
            if not x then why = 'off_map'
            elseif tile_reachable(groups, x, y, z) ~= false then why = 'reachable'
            else
                local okk, w = pcall(item_keep, it, ctx, x, y, z)
                if okk then why = w else why = 'unknown' end
            end
            if why then
                bump(res.kept, why)
                untrack(st, 'items', e.id)
            else
                res.candidates = res.candidates + 1
                if #pick < max then pick[#pick + 1] = {it = it, t = e.t} end
            end
        end
    end
    if res.candidates < min_count or res.candidates == 0 then
        res.ok, res.rejected = false, true
        res.error = ('%d item(s) unreachable long enough may go, under the %d asked for'):format(res.candidates,
                                                                                               math.max(1, min_count))
        return res
    end
    res.oldest_days = (now - pick[1].t) // 1200
    if dry_run then
        res.would_remove = #pick
        for _, e in ipairs(pick) do bump(res.by_type, U.item_kind(e.it) or '?') end
        return res
    end
    for _, e in ipairs(pick) do
        local kind = U.item_kind(e.it) or '?'
        local id = e.it.id
        local ok, r = pcall(function() return dfhack.items.remove(e.it) end)
        if ok and r ~= false then
            res.removed = res.removed + 1
            bump(res.by_type, kind)
            untrack(st, 'items', id)
        else
            res.failed = res.failed + 1
        end
    end
    res.left = res.candidates - res.removed
    res.more = res.left > 0
    if st.last and type(st.last.items) == 'table' then
        local c = st.last.items
        c.unreachable_old = math.max(0, (c.unreachable_old or 0) - res.removed)
        c.unreachable = math.max(0, (c.unreachable or 0) - res.removed)
    end
    save_state()
    if res.removed == 0 then res.ok, res.error = false, 'the game removed none of the ' .. res.failed .. ' items tried' end
    res.ms = math.floor(ms_since(t0) + 0.5)
    return res
end

-- o: max (1-100, default 20), min_age (ticks unreachable, at least a season,
-- default a season), kinds ({'hostile', 'wild'}, default both)
function cleanup_units(o, dry_run)
    o = o or {}
    local st = state()
    local max = clamp(o.max, 1, MAX_UNITS, 20)
    local min_age = clamp(o.min_age, SEASON, 100 * YEAR, SEASON)
    local kinds = {}
    for _, k in ipairs(type(o.kinds) == 'table' and #o.kinds > 0 and o.kinds or {'hostile', 'wild'}) do kinds[k] = true end
    local groups = citizen_groups()
    if not groups then return no_groups() end
    local now = now_tick()
    local res = {ok = true, removed = 0, kept = {}, dry_run = dry_run or nil, candidates = 0, by_race = {}, list = {}}
    local pick = {}
    for _, e in ipairs(oldest_first(st.units)) do
        if now - e.t < min_age then break end
        local u = df.unit.find(e.id)
        if not u then
            untrack(st, 'units', e.id)
        else
            local okk, why, kind = pcall(unit_keep, u)
            if not okk then why = 'unknown' end
            if not why and not kinds[kind] then why = 'kind' end
            if not why then
                local okp, x, y, z = pcall(dfhack.units.getPosition, u)
                if not (okp and x) or tile_reachable(groups, x, y, z) ~= false then why = 'reachable' end
            end
            if why then
                bump(res.kept, why)
                if why ~= 'kind' then untrack(st, 'units', e.id) end
            else
                res.candidates = res.candidates + 1
                if #pick < max then pick[#pick + 1] = {u = u, kind = kind, t = e.t} end
            end
        end
    end
    if #pick == 0 then
        res.ok, res.rejected, res.error = false, true, 'no hostile or wild creature unreachable long enough'
        return res
    end
    for _, e in ipairs(pick) do
        local r = race_name(e.u)
        bump(res.by_race, r)
        if #res.list < LIST_MAX then
            table.insert(res.list, {id = e.u.id, race = r, kind = e.kind, days = (now - e.t) // 1200})
        end
    end
    if dry_run then res.would_remove = #pick; return res end
    for _, e in ipairs(pick) do
        -- DFHack's exterminate, method vaporize: the creature vanishes (no
        -- corpse); what it carries drops where it stood
        local ok = pcall(function() e.u.animal.vanish_countdown = 1 end)
        if ok then
            res.removed = res.removed + 1
            untrack(st, 'units', e.u.id)
        end
    end
    res.left = res.candidates - res.removed
    res.more = res.left > 0
    if st.last and type(st.last.units) == 'table' then
        st.last.units.unreachable_old = math.max(0, (st.last.units.unreachable_old or 0) - res.removed)
    end
    save_state()
    if res.removed == 0 then res.ok, res.error = false, 'none of the creatures could be vaporized' end
    return res
end

-- o: scope ('outside' the built-up areas, the default; 'all': inside too),
-- budget_ms (default 150, at most 500): a call walks the map's blocks from
-- where the last stopped, as long as its budget lasts
function cleanup_spatter(o, dry_run)
    o = o or {}
    local st = state()
    local t0 = os.clock()
    local budget = clamp(o.budget_ms, 10, 500, 150)
    local scope = o.scope == 'all' and 'all' or 'outside'
    local okl, list = pcall(function() return df.global.world.map.map_blocks end)
    if not okl or not list then return {ok = false, error = 'the map\'s blocks can\'t be read'} end
    local n = vlen(list)
    local boxes = fort_boxes()
    local res = {ok = true, scope = scope, removed = 0, blocks = 0, dry_run = dry_run or nil, kept_mud_snow = 0}
    local i = st.spatter_cursor or 0
    if i >= n then i = 0 end
    local start, walked = i, 0
    while walked < n and ms_since(t0) < budget do
        local b = vget(list, i)
        if b then
            local okp, bx, by, bz = pcall(function() return b.map_pos.x, b.map_pos.y, b.map_pos.z end)
            if okp and (scope == 'all' or not block_in_fort(boxes, bx, by, bz)) then
                local evs = b.block_events
                local cleaned = false
                for j = vlen(evs) - 1, 0, -1 do
                    local ev = vget(evs, j)
                    if ev and is_spatter(ev) then
                        if keep_spatter(ev) then
                            res.kept_mud_snow = res.kept_mud_snow + 1
                        else
                            if not dry_run then
                                pcall(verase, evs, j)
                                pcall(function() ev:delete() end)
                            end
                            res.removed = res.removed + 1
                            cleaned = true
                        end
                    end
                end
                if cleaned then res.blocks = res.blocks + 1 end
            end
        end
        i = (i + 1) % math.max(1, n)
        walked = walked + 1
    end
    res.walked, res.of = walked, n
    res.more = walked < n
    if not dry_run then
        st.spatter_cursor = i
        if st.last and type(st.last.spatter) == 'table' then
            local s = st.last.spatter
            s.events = math.max(0, (s.events or 0) - res.removed)
            if scope == 'outside' then s.outside = math.max(0, (s.outside or 0) - res.removed)
            else s.outside = 0 end
        end
    end
    if dry_run then res.would_remove, res.removed = res.removed, 0 end
    if not dry_run and res.removed == 0 and not res.more then
        res.ok, res.rejected, res.error = false, true, 'no spatter to clean ' .. (scope == 'all' and 'on the map'
                                                                                or 'outside the fort\'s areas')
    end
    res.ms = math.floor(ms_since(t0) + 0.5)
    return res
end

-- o: min_age (ticks dead, at least a season, default a year), max (default 500)
function cleanup_dead_units(o, dry_run)
    o = o or {}
    local now = now_tick()
    local min_age = clamp(o.min_age, SEASON, 100 * YEAR, YEAR)
    local max = clamp(o.max, 1, MAX_DEAD, 500)
    local race, civ = U.fort_race_civ()
    local active = df.global.world.units.active
    local res = {ok = true, removed = 0, kept = {}, dry_run = dry_run or nil, active = vlen(active)}
    local go = {}
    for i = vlen(active) - 1, 0, -1 do
        local u = vget(active, i)
        if u then
            local ok, why = pcall(dead_keep, u, now, min_age, race, civ)
            if not ok then why = 'unknown' end
            if why == nil then
                if #go < max then go[#go + 1] = i else res.more = true end
            elseif why ~= 'alive' then
                bump(res.kept, why)
            end
        end
    end
    res.candidates = #go + (res.more and 1 or 0)
    if #go == 0 then
        res.ok, res.rejected, res.error = false, true, 'no dead unit long dead and unreferenced on the active list'
        return res
    end
    if dry_run then res.would_remove = #go; return res end
    -- go holds indexes from the back: erased in that order, the others don't move
    for _, i in ipairs(go) do
        if pcall(verase, active, i) then res.removed = res.removed + 1 end
    end
    res.active = vlen(active)
    local st = state()
    if st.last and type(st.last.units) == 'table' then
        local c = st.last.units
        c.dead_removable = math.max(0, (c.dead_removable or 0) - res.removed)
        c.dead_active = math.max(0, (c.dead_active or 0) - res.removed)
    end
    return res
end
