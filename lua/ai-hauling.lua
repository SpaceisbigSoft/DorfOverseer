-- Hauling, balanced (0.105.40, M5). In DF 50+ a dwarf's labours come from
-- the work details he is in; the ten hauling labours (stone, wood, bodies,
-- food, refuse, items, furniture, animals, trade goods, water) are the
-- game's "Haulers" detail, set to "everybody does this" in a new fort:
-- every civilian hauls but those the player made specialists (the dwarf's
-- "only do assigned work details", flags4.only_do_assigned_jobs).
--
-- The report's `hauling` section: the haul jobs waiting for a hauler and
-- taken, by labour, and how long the waiting ones have waited (each waiting
-- item first seen here; a stockpile job nobody takes is deleted by the game
-- after 1,000 ticks and made again, so the item is followed, not the job);
-- the haulers by labour and the idle ones; the idle civilians who don't haul
-- (the AI may give them hauling); the key specialists who haul (doctors and
-- the chief medical dwarf, the manager, bookkeeper and broker, the posts
-- the AI staffs, a dwarf in a strange mood, a legendary worker); the game's
-- Haulers detail, the AI's own and the other details carrying hauling.
--
-- What the AI may change, and nothing else:
--   * its own work detail, "AI haulers" (only selected, the ten hauling
--     labours, its own icon AI_ICON: never the game's Haulers icon), made the
--     first time it adds a hauler (never while a labor screen is open: the
--     game's screen holds its own list of the details) and remembered in the
--     save (site data HAULING_KEY). One you remove, or set to everybody or
--     nobody, is yours from then on: never made again, never changed. The
--     dwarves it added are remembered (st.added) and taken off it again, a
--     few at a time and only those on it a week or more, while the fort has
--     had haulers to spare for a week (the brain's hauling_shrink).
--   * a key specialist hauling only through the game's Haulers detail at
--     "everybody", and given no labour by any other "everybody" detail
--     (the specialist mark takes him off every one of them): made a
--     specialist (only assigned work details), the AI remembering it did;
--     given back when no longer key or when the hauling needs every hand.
--     One you set back yourself is left as you set it.
-- The game's Haulers detail and every other detail are never changed; a
-- Haulers detail set to "nobody" means nobody hauls (your choice), and one
-- set to "only selected" means you pick the haulers (your choice): the AI
-- adds no hauler then. Soldiers, children, the player's specialists and
-- dwarves in a mood are never made haulers.
--@module = true

local U = reqscript('ai-util')

local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end

HAUL_LABORS = {'HAUL_STONE', 'HAUL_WOOD', 'HAUL_BODY', 'HAUL_FOOD', 'HAUL_REFUSE', 'HAUL_ITEM',
               'HAUL_FURNITURE', 'HAUL_ANIMALS', 'HAUL_TRADE', 'HAUL_WATER'}
HAUL_SET = {}
for _, l in ipairs(HAUL_LABORS) do HAUL_SET[l] = true end

AI_DETAIL_NAME = 'AI haulers'
AI_ICON = 'CUSTOM_8'                   -- the AI's detail's icon (the game's Haulers detail has HAULERS)
LABOR_SCREEN = 'dwarfmode/Info/LABOR'  -- no detail made while a labor screen is open
HAULING_KEY = 'ai-overseer/hauling'   -- {made, gone, relieved = {[id] = tick}, yours = {[id] = true}, added = {[id] = tick}}
SHRINK_AGE = 7 * 1200                  -- a dwarf the AI added is taken off its detail only after a week on it
LEGENDARY = 15                         -- df.skill_rating Legendary
ADD_MAX, RELIEVE_MAX = 10, 5           -- a call's caps
SEEN = SEEN                            -- waiting item -> the tick first seen (kept across script reloads,
                                       -- cleared when the map unloads: another fort's item ids)

-- The posts and offices whose holders are kept off hauling while others can
KEY_POSTS = {DOCTOR = 'doctor', DIAGNOSTICIAN = 'diagnostician', SURGEON = 'surgeon', BONE_DOCTOR = 'bone doctor',
             TAVERN_KEEPER = 'tavern keeper', SCRIBE = 'scribe'}
KEY_OFFICES = {CHIEF_MEDICAL_DWARF = 'chief medical dwarf', MANAGER = 'manager', BOOKKEEPER = 'bookkeeper',
               BROKER = 'broker'}
STRANGE_MOODS = {Fey = true, Secretive = true, Possessed = true, Macabre = true, Fell = true}
-- the order they are relieved in (the most needed at their own work first).
-- (0.105.40b fix) A dwarf in a strange mood is not relieved: the mood keeps
-- him at it already, and the specialist mark would outlast it; he is only
-- never made a hauler.
KEY_ORDER = {['chief medical dwarf'] = 2, doctor = 3, diagnostician = 3, surgeon = 3, ['bone doctor'] = 3,
             manager = 4, bookkeeper = 4, broker = 4, ['tavern keeper'] = 5, scribe = 5, legendary = 6}

-- Pure: the hauling labour an item kind goes by (as DFHack's labormanager
-- maps them); cage_unit: a cage or trap with a creature in it.
ITEM_HAUL = {
    BOULDER = 'HAUL_STONE', ROUGH = 'HAUL_STONE', SMALLGEM = 'HAUL_STONE', ROCK = 'HAUL_STONE',
    WOOD = 'HAUL_WOOD',
    CORPSE = 'HAUL_BODY',
    CORPSEPIECE = 'HAUL_REFUSE', REMAINS = 'HAUL_REFUSE', VERMIN = 'HAUL_REFUSE',
    MEAT = 'HAUL_FOOD', FISH = 'HAUL_FOOD', FISH_RAW = 'HAUL_FOOD', FOOD = 'HAUL_FOOD', CHEESE = 'HAUL_FOOD',
    SEEDS = 'HAUL_FOOD', PLANT = 'HAUL_FOOD', PLANT_GROWTH = 'HAUL_FOOD', DRINK = 'HAUL_FOOD', EGG = 'HAUL_FOOD',
    GLOB = 'HAUL_FOOD', LIQUID_MISC = 'HAUL_FOOD', POWDER_MISC = 'HAUL_FOOD',
    DOOR = 'HAUL_FURNITURE', FLOODGATE = 'HAUL_FURNITURE', BED = 'HAUL_FURNITURE', CHAIR = 'HAUL_FURNITURE',
    WINDOW = 'HAUL_FURNITURE', TABLE = 'HAUL_FURNITURE', COFFIN = 'HAUL_FURNITURE', STATUE = 'HAUL_FURNITURE',
    BOX = 'HAUL_FURNITURE', BIN = 'HAUL_FURNITURE', ARMORSTAND = 'HAUL_FURNITURE', WEAPONRACK = 'HAUL_FURNITURE',
    CABINET = 'HAUL_FURNITURE', HATCH_COVER = 'HAUL_FURNITURE', GRATE = 'HAUL_FURNITURE', QUERN = 'HAUL_FURNITURE',
    MILLSTONE = 'HAUL_FURNITURE', SLAB = 'HAUL_FURNITURE', ANVIL = 'HAUL_FURNITURE', BARREL = 'HAUL_FURNITURE',
    TRACTION_BENCH = 'HAUL_FURNITURE', BOOKCASE = 'HAUL_FURNITURE', PEDESTAL = 'HAUL_FURNITURE',
    DISPLAY_CASE = 'HAUL_FURNITURE', CAGE = 'HAUL_FURNITURE', ANIMALTRAP = 'HAUL_FURNITURE',
}
function item_haul(kind, cage_unit)
    if (kind == 'CAGE' or kind == 'ANIMALTRAP') and cage_unit then return 'HAUL_ANIMALS' end
    return ITEM_HAUL[kind or ''] or 'HAUL_ITEM'
end

-- Pure: a haul job's labour: the job type's own (a hauling one), else the
-- labour the game wrote into a stockpile job (item_subtype), else the item's.
function haul_labor_of(type_labor, subtype_labor, kind, cage_unit)
    if HAUL_SET[type_labor or ''] then return type_labor end
    if HAUL_SET[subtype_labor or ''] then return subtype_labor end
    return item_haul(kind, cage_unit)
end

-- Pure: the n idle civilians to make haulers, those the fort misses least
-- first (lowest best skill), ties to the lower id. cands: {id, best}.
function pick_haulers(cands, n)
    local list = {}
    for _, c in ipairs(cands) do table.insert(list, c) end
    table.sort(list, function(a, b)
        if (a.best or 0) ~= (b.best or 0) then return (a.best or 0) < (b.best or 0) end
        return a.id < b.id
    end)
    local out = {}
    for i = 1, math.min(n, #list) do out[i] = list[i] end
    return out
end

-- Pure: the key specialists to relieve first (by KEY_ORDER, then id).
function order_specialists(list)
    local out = {}
    for _, c in ipairs(list) do table.insert(out, c) end
    table.sort(out, function(a, b)
        local oa, ob = KEY_ORDER[a.why] or 9, KEY_ORDER[b.why] or 9
        if oa ~= ob then return oa < ob end
        return a.id < b.id
    end)
    return out
end

-- --- the game -----------------------------------------------------------------

local function enum(e, k) if e == nil or k == nil then return nil end return e[k] end

local function details()
    local ok, v = pcall(function() return df.global.plotinfo.labor_info.work_details end)
    return ok and v or nil
end

local function mode_of(wd)
    local ok, m = pcall(function() return df.work_detail_mode[wd.flags.mode] end)
    return ok and m or nil
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

local function remove_member(wd, id)
    for i = #wd.assigned_units - 1, 0, -1 do
        if wd.assigned_units[i] == id then wd.assigned_units:erase(i) end
    end
end

local function carries_haul(wd)
    for _, l in ipairs(HAUL_LABORS) do
        local id = enum(df.unit_labor, l)
        local ok, yes = pcall(function() return id ~= nil and wd.allowed_labors[id] end)
        if ok and yes then return true end
    end
    return false
end

function state() return U.site_get(HAULING_KEY, {}) end
local function save(st) U.site_put(HAULING_KEY, st) end

-- The game's Haulers detail (its icon, never one named as the AI's or with
-- the AI's icon), the AI's own (by name, only while the AI made it and it is
-- still "only selected"), and the other details carrying hauling (yours:
-- never changed).
function find_details(st)
    local game, mine, others = nil, nil, {}
    local icon = enum(df.work_detail_icon_type, 'HAULERS')
    local ai_icon = enum(df.work_detail_icon_type, AI_ICON)
    local list = details() or {}
    -- the game's own: the Haulers icon and the game's "default" mark, else the icon alone
    for pass = 1, 2 do
        for _, d in ipairs(list) do
            local own = pass == 2 or (function()
                local ok, v = pcall(function() return d.flags.no_modify end)
                return ok and v == true
            end)()
            if not game and icon ~= nil and d.icon == icon and own
                    and tostring(d.name) ~= AI_DETAIL_NAME and not (ai_icon ~= nil and d.icon == ai_icon) then
                game = d
            end
        end
    end
    for _, d in ipairs(list) do
        if d ~= game then
            if st.made and not st.gone and tostring(d.name) == AI_DETAIL_NAME and not mine then
                mine = d
            elseif carries_haul(d) then
                table.insert(others, d)
            end
        end
    end
    return game, mine, others
end

local function specialist(u)
    local ok, v = pcall(function() return u.flags4.only_do_assigned_jobs end)
    return ok and v == true
end

local function set_specialist(u, v)
    return pcall(function() u.flags4.only_do_assigned_jobs = v end)
end

local function has_labor(u, id)
    local ok, v = pcall(function() return u.status.labors[id] end)
    return ok and v == true
end

local function hauls(u)
    local n = 0
    for _, l in ipairs(HAUL_LABORS) do
        local id = enum(df.unit_labor, l)
        if id ~= nil and has_labor(u, id) then n = n + 1 end
    end
    return n
end

local function grown(u)
    return not (dfhack.units.isChild(u) or dfhack.units.isBaby(u))
end

local function in_squad(u) return u.military.squad_id >= 0 end

local function idle(u) return u.job.current_job == nil end

local function hurt(u)
    local ok, v = pcall(function() return u.health ~= nil and u.health.flags.needs_healthcare end)
    return ok and v == true
end

local function best_skill(u)
    local best = 0
    pcall(function()
        for _, s in ipairs(u.status.current_soul.skills) do
            if s.rating > best then best = s.rating end
        end
    end)
    return best
end

local function in_mood(u)
    local ok, m = pcall(function() return u.mood >= 0 and df.mood_type[u.mood] end)
    return ok and m and STRANGE_MOODS[m] or false
end

-- Why a dwarf is kept at his own work (nil: he isn't a key specialist).
-- (0.105.40b fix) a strange mood is no reason: see KEY_ORDER.
function key_reason(u)
    local why
    pcall(function()
        for _, o in ipairs(u.occupations) do
            local t = df.occupation_type[o.type]
            if KEY_POSTS[t] and (not why or (KEY_ORDER[KEY_POSTS[t]] or 9) < (KEY_ORDER[why] or 9)) then
                why = KEY_POSTS[t]
            end
        end
    end)
    pcall(function()
        for _, np in ipairs(dfhack.units.getNoblePositions(u) or {}) do
            local w = KEY_OFFICES[np.position.code]
            if w and (not why or (KEY_ORDER[w] or 9) < (KEY_ORDER[why] or 9)) then why = w end
        end
    end)
    if why then return why end
    local legendary = false
    pcall(function()
        for _, s in ipairs(u.status.current_soul.skills) do
            if s.rating >= LEGENDARY then
                local l = df.job_skill.attrs[s.id].labor
                local tok = l and l >= 0 and df.unit_labor[l]
                if tok and not HAUL_SET[tok] then legendary = true end
            end
        end
    end)
    return legendary and 'legendary' or nil
end

-- The labours a dwarf gets from the details (as the game works them out):
-- an "everybody" detail unless he is a specialist; "only selected" (or
-- default) ones he is a member of. `skip`: a detail left out.
local function detail_labors(u, skip)
    local got = {}
    local spec = specialist(u)
    for _, d in ipairs(details() or {}) do
        if d ~= skip then
            local m = mode_of(d)
            if (m == 'EverybodyDoesThis' and not spec)
                    or ((m == 'OnlySelectedDoesThis' or m == 'Default') and is_member(d, u.id)) then
                for _, l in ipairs(HAUL_LABORS) do
                    local id = enum(df.unit_labor, l)
                    local ok, yes = pcall(function() return d.allowed_labors[id] end)
                    if ok and yes then got[l] = true end
                end
            end
        end
    end
    return got
end

-- His hauling labours set as the details give them (the other labours are
-- left as they are: no full recompute, so labours given straight to a post
-- holder stay).
local function sync_hauling(u)
    local got = detail_labors(u)
    for _, l in ipairs(HAUL_LABORS) do
        local id = enum(df.unit_labor, l)
        if id ~= nil then pcall(function() u.status.labors[id] = got[l] == true end) end
    end
end

-- Any labour at all on a detail (its allowed_labors).
local function any_labor(d)
    local ok, yes = pcall(function()
        for _, v in pairs(d.allowed_labors) do if v == true then return true end end
        return false
    end)
    return ok and yes == true
end

-- (0.105.40b fix) Another "everybody" detail giving a dwarf some labour (any,
-- not only hauling): the specialist mark would take him off that one too.
local function other_everybody(game)
    for _, d in ipairs(details() or {}) do
        if d ~= game and mode_of(d) == 'EverybodyDoesThis' and any_labor(d) then return true end
    end
    return false
end

-- How a key dwarf hauls: 'ai' (the AI's detail), 'everybody' (the game's
-- Haulers detail at everybody is the only "everybody" detail giving him any
-- labour, and nothing else of yours gives him hauling), else 'yours'.
local function hauls_via(u, game, mine)
    if mine and is_member(mine, u.id) then
        local rest = detail_labors(u, mine)
        if next(rest) == nil then return 'ai' end
        return 'yours'
    end
    if game and mode_of(game) == 'EverybodyDoesThis' and not specialist(u) and not other_everybody(game) then
        local rest = detail_labors(u, game)
        if next(rest) == nil then return 'everybody' end
    end
    return 'yours'
end

-- The relieved ones the player set back (no longer specialists): theirs now.
-- (0.105.40b fix) The ones the AI added no longer on its detail (you took
-- them off, or the detail is gone): forgotten.
local function settle(st, mine)
    local changed = false
    st.relieved = st.relieved or {}
    st.yours = st.yours or {}
    st.added = type(st.added) == 'table' and st.added or {}
    for k in pairs(st.added) do
        if not (mine and is_member(mine, tonumber(k))) then
            st.added[k] = nil
            changed = true
        end
    end
    for k in pairs(st.relieved) do
        local u = df.unit.find(tonumber(k))
        if not u or dfhack.units.isDead(u) then
            st.relieved[k] = nil
            changed = true
        elseif not specialist(u) then
            st.relieved[k] = nil
            st.yours[k] = true
            changed = true
        end
    end
    return changed
end

-- --- the backlog -------------------------------------------------------------

local function is_haul_job(job)
    local ok, yes = pcall(function()
        local a = df.job_type.attrs[job.job_type]
        if a.type == df.job_type_class.Hauling then return true end
        local l = a.labor
        return l ~= nil and l >= 0 and HAUL_SET[df.unit_labor[l]] == true
    end)
    return ok and yes == true
end

local function first_item(job)
    local ok, it = pcall(function() return job.items[0] and job.items[0].item end)
    return ok and it or nil
end

local function cage_unit(it)
    local ok, r = pcall(function()
        return dfhack.items.getGeneralRef(it, df.general_ref_type.CONTAINS_UNIT) ~= nil
    end)
    return ok and r == true
end

function job_haul_labor(job)
    local tl, sl
    pcall(function()
        local l = df.job_type.attrs[job.job_type].labor
        if l and l >= 0 then tl = df.unit_labor[l] end
    end)
    pcall(function()
        if df.job_type[job.job_type] == 'StoreItemInStockpile' and job.item_subtype >= 0 then
            sl = df.unit_labor[job.item_subtype]
        end
    end)
    local it = first_item(job)
    local kind = it and U.item_kind(it) or nil
    return haul_labor_of(tl, sl, kind, it and (kind == 'CAGE' or kind == 'ANIMALTRAP') and cage_unit(it))
end

-- The haul jobs: waiting (nobody on it, not suspended) and taken, by labour,
-- with the waiting ones' ages in days.
function backlog(now)
    local by, total = {}, {waiting = 0, taken = 0, old = 0, oldest_days = 0}
    local seen, prev = {}, SEEN or {}
    local link = df.global.world.jobs.list.next
    while link do
        local job = link.item
        if job and is_haul_job(job) then
            local l = job_haul_labor(job)
            local row = by[l]
            if not row then row = {waiting = 0, taken = 0, oldest_days = 0}; by[l] = row end
            if dfhack.job.getWorker(job) then
                row.taken = row.taken + 1
                total.taken = total.taken + 1
            elseif not job.flags.suspend then
                row.waiting = row.waiting + 1
                total.waiting = total.waiting + 1
                local it = first_item(job)
                local key = it and ('i' .. it.id) or ('j' .. job.id)
                local since = prev[key] or now
                seen[key] = since
                local days = now and since and math.max(0, (now - since) // 1200) or 0
                if days > row.oldest_days then row.oldest_days = days end
                if days > total.oldest_days then total.oldest_days = days end
                if days >= 1 then total.old = total.old + 1 end
            end
        end
        link = link.next
    end
    if now then SEEN = seen end
    total.by = by
    return total
end

-- --- the haulers ---------------------------------------------------------------

-- The citizens as haulers: who hauls (by labour, and idle), the idle who
-- don't (candidates), the key specialists who do.
local function haulers(st, game, mine)
    local out = {civilians = 0, idle = 0, any = 0, idle_any = 0, candidates = 0, player_specialists = 0,
                 by = {}, specialists = {}, relievable = 0, relieved = 0, relieved_stale = 0}
    local cands, keys = {}, {}
    local yours, relieved = st.yours or {}, st.relieved or {}
    for _, u in ipairs(report_citizens(true)) do
        if grown(u) and not in_squad(u) then
            out.civilians = out.civilians + 1
            local free = idle(u)
            if free then out.idle = out.idle + 1 end
            local n = hauls(u)
            local why = key_reason(u)
            local k = tostring(u.id)
            if relieved[k] then
                out.relieved = out.relieved + 1
                if not why then out.relieved_stale = out.relieved_stale + 1 end
            elseif specialist(u) then
                out.player_specialists = out.player_specialists + 1
            end
            if n > 0 then
                out.any = out.any + 1
                if free then out.idle_any = out.idle_any + 1 end
                for _, l in ipairs(HAUL_LABORS) do
                    local id = enum(df.unit_labor, l)
                    if id ~= nil and has_labor(u, id) then
                        local row = out.by[l]
                        if not row then row = {holders = 0, idle = 0}; out.by[l] = row end
                        row.holders = row.holders + 1
                        if free then row.idle = row.idle + 1 end
                    end
                end
                if why then
                    local via = hauls_via(u, game, mine)
                    if yours[k] then via = 'yours' end
                    table.insert(keys, {id = u.id, why = why, via = via, unit = u})
                    if via ~= 'yours' then out.relievable = out.relievable + 1 end
                end
            elseif free and not why and not specialist(u) and not hurt(u) and not in_mood(u) then
                out.candidates = out.candidates + 1
                table.insert(cands, {id = u.id, best = best_skill(u), unit = u})
            end
        end
    end
    return out, cands, order_specialists(keys)
end

local function name_of(u, txt)
    return (txt or tostring)(dfhack.units.getReadableName(u))
end

-- The report's `hauling` section.
function report(txt)
    local st = state()
    local okt, now = pcall(U.abs_tick)
    local out = {backlog = backlog(okt and now or nil)}
    local game, mine, others = find_details(st)
    settle(st, mine)                              -- (read only here: saved by the actions)
    local h, _, keys = haulers(st, game, mine)
    out.haulers = h
    h.specialists = {}
    for i = 1, math.min(12, #keys) do
        local c = keys[i]
        table.insert(h.specialists, {id = c.id, name = name_of(c.unit, txt), why = c.why, via = c.via})
    end
    if game then
        out.detail = {name = tostring(game.name), mode = mode_of(game), members = #game.assigned_units}
    end
    if mine then
        out.ai_detail = {name = tostring(mine.name), mode = mode_of(mine), members = #mine.assigned_units}
        -- (0.105.40b fix) the dwarves the AI added on it, and those a week or more
        local added, old = 0, 0
        for _, t in pairs(st.added) do
            added = added + 1
            if okt and type(t) == 'number' and now - t >= SHRINK_AGE then old = old + 1 end
        end
        out.ai_detail.added, out.ai_detail.added_old = added, old
    end
    out.ai_detail_gone = st.gone or nil
    out.other_details = #others
    return out
end

-- --- the actions -----------------------------------------------------------------

-- The AI's own detail, made if it has none yet (nil and why when it can't:
-- you removed it or set it to everybody or nobody, or this DF can't).
local function ensure_detail(st, dry_run)
    local _, mine = find_details(st)
    if st.made and not st.gone and not mine then
        st.gone = true                     -- removed (or renamed) by you: yours from now on
        return nil, 'the AI haulers work detail was removed or renamed: the AI makes no other'
    end
    if mine then
        local m = mode_of(mine)
        if m ~= 'OnlySelectedDoesThis' then
            st.gone = true
            return nil, ('the AI haulers work detail was set to %s: yours now, the AI leaves it'):format(tostring(m))
        end
        -- (0.105.40b fix) an older build gave it the Haulers icon: its own now
        if not dry_run then
            pcall(function()
                local ai_icon = df.work_detail_icon_type[AI_ICON]
                if ai_icon ~= nil and mine.icon ~= ai_icon then mine.icon = ai_icon end
            end)
        end
        return mine
    end
    if st.gone then return nil, 'the AI haulers work detail was taken over by you: the AI leaves hauling to you' end
    -- (0.105.40b fix) never while a labor screen is open (the game's screen
    -- keeps its own list of the details): made on a later call
    local okf, open = pcall(function() return dfhack.gui.matchFocusString(LABOR_SCREEN) end)
    if okf and open then
        return nil, 'a labor screen is open in the game: the AI makes its haulers detail once it is closed', true
    end
    if dry_run then return 'new' end
    local list = details()
    local OS = enum(df.work_detail_mode, 'OnlySelectedDoesThis')
    if not list or OS == nil or not df.work_detail then return nil, 'this DF has no work details' end
    local ok, wd = pcall(function()
        local d = df.work_detail:new()
        d.name = AI_DETAIL_NAME
        d.flags.mode = OS
        pcall(function() d.icon = df.work_detail_icon_type[AI_ICON] end)
        for _, l in ipairs(HAUL_LABORS) do
            local id = enum(df.unit_labor, l)
            if id ~= nil then d.allowed_labors[id] = true end
        end
        list:insert('#', d)
        return d
    end)
    if not ok then return nil, 'the game would not take a new work detail: ' .. tostring(wd):sub(1, 120) end
    st.made = true
    return wd
end

-- Up to `count` idle civilians who don't haul made haulers (the AI's own
-- detail), those the fort misses least first.
function add_haulers(count, dry_run, txt)
    local st = state()
    local game, mine = find_details(st)
    local changed = settle(st, mine)
    if game and mode_of(game) == 'NobodyDoesThis' then
        if changed then save(st) end
        return {ok = false, rejected = true,
                error = ('the %s work detail is set to nobody (your choice): the AI adds no hauler'):format(tostring(game.name))}
    end
    -- (0.105.40b fix) "only selected": you pick the haulers (a new fort's is
    -- "everybody"), so the AI adds none through its own detail either
    if game and mode_of(game) == 'OnlySelectedDoesThis' then
        if changed then save(st) end
        return {ok = false, rejected = true, yours = true,
                error = ('the %s work detail is set to only selected (your choice): the AI adds no hauler'):format(tostring(game.name))}
    end
    local _, cands = haulers(st, game, mine)
    local picked = pick_haulers(cands, math.max(0, math.min(ADD_MAX, count or 0)))
    if #picked == 0 then
        if changed then save(st) end
        return {ok = false, rejected = true, error = 'no idle civilian without hauling (soldiers, children, '
                .. 'specialists, the key workers and those in a mood are never made haulers)'}
    end
    local fresh = mine == nil
    local wd, why, later = ensure_detail(st, dry_run)
    if not wd then
        if not dry_run then save(st) end
        return {ok = false, rejected = true, waiting = later or nil, error = why}
    end
    local okt, now = pcall(U.abs_tick)
    local names = {}
    for _, c in ipairs(picked) do
        table.insert(names, name_of(c.unit, txt))
        if not dry_run then
            insert_sorted(wd, c.id)
            sync_hauling(c.unit)
            st.added[tostring(c.id)] = okt and now or 0
        end
    end
    if not dry_run then save(st) end
    return {ok = true, dry_run = dry_run or nil, added = names, detail = AI_DETAIL_NAME,
            made = fresh or nil}
end

-- Up to `count` key specialists taken off hauling (only what the AI may
-- change: its own detail, or "everybody" through a specialist mark it
-- remembers); back = true gives hauling back to the ones it relieved (those
-- no longer key first); (0.105.40b fix) shrink = true takes off the AI's own
-- detail up to `count` of the dwarves it added there a week or more ago (the
-- most skilled first: the fort misses them most), never one you added.
function relieve_haulers(count, back, dry_run, txt, shrink)
    local st = state()
    local game, mine = find_details(st)
    settle(st, mine)
    count = math.max(0, math.min(RELIEVE_MAX, count or 0))
    local names = {}
    if shrink then
        local okt, now = pcall(U.abs_tick)
        local list = {}
        for k, t in pairs(st.added) do
            local u = df.unit.find(tonumber(k))
            if u and mine and okt and type(t) == 'number' and now - t >= SHRINK_AGE then
                table.insert(list, {id = u.id, unit = u, best = best_skill(u)})
            end
        end
        table.sort(list, function(a, b)
            if a.best ~= b.best then return a.best > b.best end
            return a.id < b.id
        end)
        for i = 1, math.min(count, #list) do
            local c = list[i]
            table.insert(names, name_of(c.unit, txt))
            if not dry_run then
                remove_member(mine, c.id)
                sync_hauling(c.unit)
                st.added[tostring(c.id)] = nil
            end
        end
        if not dry_run then save(st) end
        if #names == 0 then
            return {ok = false, rejected = true, nothing_to_do = true,
                    error = 'nobody the AI put on its haulers detail a week or more ago is on it'}
        end
        return {ok = true, dry_run = dry_run or nil, shrunk = names}
    end
    if back then
        local list = {}
        for k in pairs(st.relieved) do
            local u = df.unit.find(tonumber(k))
            if u then table.insert(list, {id = u.id, unit = u, key = key_reason(u) and 1 or 0}) end
        end
        table.sort(list, function(a, b)
            if a.key ~= b.key then return a.key < b.key end
            return a.id < b.id
        end)
        for i = 1, math.min(count, #list) do
            local c = list[i]
            table.insert(names, name_of(c.unit, txt))
            if not dry_run then
                set_specialist(c.unit, false)
                sync_hauling(c.unit)
                st.relieved[tostring(c.id)] = nil
            end
        end
        if not dry_run then save(st) end
        if #names == 0 then return {ok = false, rejected = true, error = 'the AI relieved nobody of hauling'} end
        return {ok = true, dry_run = dry_run or nil, back = names}
    end
    local _, _, keys = haulers(st, game, mine)
    local okt, now = pcall(U.abs_tick)
    local done = 0
    for _, c in ipairs(keys) do
        if done >= count then break end
        if c.via == 'ai' or c.via == 'everybody' then
            done = done + 1
            table.insert(names, name_of(c.unit, txt) .. ' (' .. c.why .. ')')
            if not dry_run then
                if c.via == 'ai' then
                    remove_member(mine, c.id)
                    st.added[tostring(c.id)] = nil
                else
                    set_specialist(c.unit, true)
                    st.relieved[tostring(c.id)] = okt and now or 0
                end
                sync_hauling(c.unit)
            end
        end
    end
    if not dry_run then save(st) end
    if #names == 0 then
        return {ok = false, rejected = true, error = 'no key worker hauls through a detail the AI may change '
                .. '(your own details and specialists are left as they are)'}
    end
    return {ok = true, dry_run = dry_run or nil, relieved = names}
end

-- (0.105.40b fix) The waiting items' first-seen ticks belong to the fort
-- loaded: cleared when the map unloads (as ai-gates clears GATES), so the
-- next fort's item ids never inherit an old age.
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-hauling'] = function(sc)
        if sc == SC_MAP_UNLOADED then SEEN = nil end
    end
end
