-- Small helpers shared by the AI's Lua modules (13c): the fort's entity, the
-- game's absolute tick, the save's site data, and whether an item is free for
-- a new job. Each was copied into many modules, and the copies had drifted.
--
-- A module takes it with `local U = reqscript('ai-util')`; the tests load a
-- module through tests/lua_modules_util.py, which hands it this one.
--@module = true

TICKS_PER_DAY = 1200
TICKS_PER_MONTH = 28 * TICKS_PER_DAY
TICKS_PER_YEAR = 403200

-- The fort's own entity (the site government), or nil.
function fort_entity()
    return df.historical_entity.find(df.global.plotinfo.group_id)
end

-- Ticks since the world began, from a year and its tick (an event's
-- year/year_tick); with no arguments, now. Not protected: a caller that may
-- run with no world loaded wraps it in pcall.
function abs_tick(year, tick)
    if year == nil then year, tick = df.global.cur_year, df.global.cur_year_tick end
    return year * TICKS_PER_YEAR + tick
end

-- --- per-report shared walks (0.105.40, E3) ---------------------------------------
--
-- A full report walked the units dozens of times: each section (and each part
-- of the threats, the military, the needs...) asked DFHack for the citizens
-- or walked world.units.active itself. The game stands still for the length
-- of one dfhack-run call, so one walk serves them all: the bridge's
-- build_state sets REPORT_CTX here (report_begin) and clears it at the end
-- (report_end). Outside a report (an action, a test) every call walks afresh,
-- exactly as before. The lists hold the same units in the same order as the
-- walk they replace; citizens() hands out a copy (a caller may sort it), the
-- others are shared and read-only.
REPORT_CTX = nil

function report_begin(ctx)
    REPORT_CTX = ctx or {}
    REPORT_CTX.walks = REPORT_CTX.walks or {units = 0, items = 0, citizens = 0}
    return REPORT_CTX
end

function report_end() REPORT_CTX = nil end

-- `build()` once a report under `key` (outside one: every call). A build that
-- throws is not kept.
function report_memo(key, build)
    local c = REPORT_CTX
    if not c then return build() end
    local m = c.memo
    if not m then m = {}; c.memo = m end
    local v = m[key]
    if v == nil then
        v = build()
        if v == nil then m[key] = false else m[key] = v end
        return v
    end
    if v == false then return nil end
    return v
end

local function copy_list(l)
    local out = {}
    for i = 1, #l do out[i] = l[i] end
    return out
end

-- dfhack.units.getCitizens(...), asked once a report for each set of arguments
-- (a fresh copy to each caller).
-- (Called with the caller's own arguments, as many as it gave.)
function citizens(...)
    local c = REPORT_CTX
    if not c then return dfhack.units.getCitizens(...) end
    c.citizens = c.citizens or {}
    local key = select('#', ...) .. ':' .. tostring((...)) .. ':' .. tostring((select(2, ...)))
    local l = c.citizens[key]
    if not l then
        l = dfhack.units.getCitizens(...)
        c.citizens[key] = l
        c.walks.citizens = c.walks.citizens + 1
    end
    return copy_list(l)
end

local function list_of(vec)
    local out = {}
    for _, v in ipairs(vec) do out[#out + 1] = v end
    return out
end

-- world.units.active: the vector itself outside a report, a list of the same
-- units (same order) walked once inside one.
function units_active()
    local c = REPORT_CTX
    if not c then return df.global.world.units.active end
    if not c.units_active then
        c.units_active = list_of(df.global.world.units.active)
        c.walks.units = c.walks.units + 1
    end
    return c.units_active
end

-- world.items.all, as units_active.
function items_all()
    local c = REPORT_CTX
    if not c then return df.global.world.items.all end
    if not c.items_all then
        c.items_all = list_of(df.global.world.items.all)
        c.walks.items = c.walks.items + 1
    end
    return c.items_all
end

-- A copy of a plain table (a decoded save record) all the way down: the same
-- keys and values, the same metatables; a table met twice is copied once.
function deep_copy(v, seen)
    if type(v) ~= 'table' then return v end
    seen = seen or {}
    if seen[v] then return seen[v] end
    local out = {}
    seen[v] = out
    for k, x in pairs(v) do out[deep_copy(k, seen)] = deep_copy(x, seen) end
    local mt = getmetatable(v)
    if mt ~= nil then setmetatable(out, mt) end
    return out
end

-- The save's site data under `key`, or `default` when there is none, it
-- can't be read, or (a table default) it isn't a table.
function site_get(key, default)
    local ok, d = pcall(function() return dfhack.persistent.getSiteData(key, default) end)
    if not ok or d == nil then return default end
    if type(default) == 'table' and type(d) ~= 'table' then return default end
    return d
end

-- Saves `value` as the site data under `key`. Returns true, or false and
-- the error (callers that only log it may ignore it; none should need to
-- guess why a value didn't stick).
function site_put(key, value)
    local ok, err = pcall(function() dfhack.persistent.saveSiteData(key, value) end)
    if ok then return true end
    return false, tostring(err)
end

-- --- is an item free for a new job? ------------------------------------------------
--
-- The one list (13c). Before it, about a dozen copies disagreed: some missed
-- rotten, encased, on fire, a spider web, owned, an artifact, evidence of a
-- murder or a dead dwarf's belongings, some missed the dump or a job, and
-- some counted an item in a dwarf's hands. In checking order: what the fort
-- can never use first, then what a job holds, then what the player (or the
-- AI) set aside, then what a unit carries. `in_inventory` alone is not a
-- reason: DF sets it for an item in a bin or barrel too.
UNFREE = {
    {'removed', 'gone'}, {'garbage_collect', 'gone'},
    {'construction', 'in a building'}, {'in_building', 'in a building'},
    {'encased', 'encased'},
    {'trader', 'a trader\'s'}, {'hostile', 'an enemy\'s'}, {'owned', 'owned by a dwarf'},
    {'artifact', 'an artifact'}, {'murder', 'evidence of a murder'}, {'dead_dwarf', 'a dead dwarf\'s'},
    {'rotten', 'rotten'}, {'on_fire', 'on fire'}, {'spider_web', 'a spider web'},
    {'in_job', 'taken by a job'}, {'forbid', 'forbidden'}, {'dump', 'marked for the dump'},
}

-- nil when the item is free, else the flag that stops it ('held' for an
-- item a unit carries) and why in words. `allow` (optional): a set of flag
-- names (and 'held') the caller doesn't mind, e.g. {in_job = true} to count
-- stock a job may be using, {held = true} to skip the holder look-up.
function item_unfree(it, allow)
    local f = it.flags
    for _, row in ipairs(UNFREE) do
        local name = row[1]
        if f[name] and not (allow and allow[name]) then return name, row[2] end
    end
    if f.in_inventory and not (allow and allow.held) then
        local ok, u = pcall(dfhack.items.getHolderUnit, it)
        if ok and u ~= nil then return 'held', 'carried' end
    end
    return nil
end

function item_free(it, allow)
    return item_unfree(it, allow) == nil
end

-- --- near danger? -------------------------------------------------------------------
--
-- (0.105.27, moved from ai-military-gear) Where the live dangers stand, and
-- whether a tile lies within DANGER_TILES of one (and 3 levels): no dwarf is
-- sent there for an item (a field of the dead under fire is no place to fetch
-- a sword), and the disposal actions leave such items alone.
DANGER_TILES = 20

-- {{x, y, z}...}: every live unit that is a danger or an invader, but a
-- caged or chained captive.
function danger_spots()
    local out = {}
    local okl, active = pcall(units_active)     -- (0.105.40) the report's one walk
    for _, u in ipairs(okl and active or {}) do
        local ok, bad = pcall(function()
            local Un = dfhack.units
            -- (0.105.2 review) a caged or chained captive is no danger
            local f1 = u.flags1
            if f1 and (f1.caged or f1.chained) then return false end
            return not Un.isDead(u) and (Un.isDanger(u) or Un.isInvader(u))
        end)
        if ok and bad then
            local x, y, z = dfhack.units.getPosition(u)
            if x then table.insert(out, {x = x, y = y, z = z}) end
        end
    end
    return out
end

-- true if (x, y, z) lies within `tiles` (default DANGER_TILES, walked
-- across: |dx| + |dy|) and 3 levels of a spot.
function near_danger(spots, x, y, z, tiles)
    tiles = tiles or DANGER_TILES
    for _, d in ipairs(spots or {}) do
        if math.abs(d.x - x) + math.abs(d.y - y) <= tiles and math.abs(d.z - z) <= 3 then
            return true
        end
    end
    return false
end

-- --- the cistern's tiles ------------------------------------------------------------
--
-- (0.105.27) The tiles the AI's cistern fills ("x,y,z" = true): its room on
-- its level, the tunnel on the source's level (all of it but the plug, the
-- last tile, beside the source), and the shaft from the room's level to the
-- source's; and the same for every retired cistern (its room always, its
-- tunnel and shaft when the record has them). The AI forbids what lies there
-- before the flood (ai-builder-cistern forbid_items_on); the disposal actions
-- and the census leave those items be. Read from the save (the cistern's
-- records), so no builder load is needed. {} with no cistern.
CISTERN_KEY = 'ai-overseer/cistern'

local function add_cistern(set, p)
    if type(p) ~= 'table' or type(p.cistern) ~= 'table' then return end
    local c = p.cistern
    local z = c.z
    if type(z) ~= 'number' then return end
    for y = c.y1, c.y2 do
        for x = c.x1, c.x2 do set[x .. ',' .. y .. ',' .. z] = true end
    end
    local zi = tonumber(p.intake_z) or z
    local path = type(p.tunnel_path) == 'table' and p.tunnel_path or {}
    for i = 1, #path - 1 do              -- the last tile is the plug
        local q = path[i]
        if type(q) == 'table' and q.x and q.y then set[q.x .. ',' .. q.y .. ',' .. zi] = true end
    end
    if type(p.shaft) == 'table' and p.shaft.x and p.shaft.y then
        for zz = math.min(z, zi), math.max(z, zi) do set[p.shaft.x .. ',' .. p.shaft.y .. ',' .. zz] = true end
    end
end

function cistern_tiles()
    local set = {}
    pcall(function()
        local d = site_get(CISTERN_KEY, {})
        add_cistern(set, type(d) == 'table' and d.plan)
    end)
    pcall(function()
        for _, r in ipairs(site_get(CISTERN_KEY .. '/retired', {})) do
            pcall(add_cistern, set, r)
        end
    end)
    return set
end

-- --- why an item is forbidden ----------------------------------------------------
--
-- (0.105.27 disposal fixes) The ONE classifier the census (ai-census
-- items.forbidden) and the disposal actions (ai-disposal) both use, so what
-- the census counts is what the actions act on. Who set item_flags.forbid
-- can't be read, so a forbidden item is put down to a reason from its
-- signature, first match wins:
--   ai          on the cistern's tiles (cistern_tiles above)
--   dumped      lying in a garbage dump zone (ctx.in_dump)
--   own_dead    the dead_dwarf flag, an owner who is dead, or a body (or a
--               part) of one of the fort's own: its race AND its civ (a civ
--               that can't be read counts as the fort's)
--   other_dead  a body or part of another race or civ, or what the dead wore
--               or carried (DEAD_GEAR) lying on the ground within the 3x3
--               round such a body
--   used_ammo   ammo on the ground outside a stockpile (ctx.in_stockpile)
--   unknown     the rest: maybe the player's
-- An item that isn't forbidden is 'free'. The second value says whether it
-- is a body or a part: 'own', 'other', or nil.
DEAD_GEAR = {WEAPON = true, ARMOR = true, HELM = true, SHOES = true, GLOVES = true, PANTS = true,
             SHIELD = true, AMMO = true, QUIVER = true, BACKPACK = true, FLASK = true, CROWN = true,
             RING = true, EARRING = true, BRACELET = true, AMULET = true, SCEPTER = true}
CORPSE_KINDS = {CORPSE = true, CORPSEPIECE = true}
-- (0.105.28) every dead creature's item type DF 50 has (df-structures
-- item_type: CORPSE, CORPSEPIECE and REMAINS, the remains of vermin and small
-- creatures, which carry a race but no unit). All are bodies to the
-- classifier (corpse_side, fort_remains); only CORPSE_KINDS mark the tiles
-- whose gear is a dead other's (a dead rat by a helm says nothing of it).
DEAD_KINDS = {CORPSE = true, CORPSEPIECE = true, REMAINS = true}

local function tkey(x, y, z) return x .. ',' .. y .. ',' .. z end

-- The item's type name ('WEAPON'...), or nil.
function item_kind(it)
    local ok, k = pcall(function() return df.item_type[it:getType()] end)
    if ok and type(k) == 'string' then return k end
    return nil
end

-- Where the item is (through its holder or container): x, y, z, or nil off the map.
function item_pos(it)
    local okp, x, y, z = pcall(function() return dfhack.items.getPosition(it) end)
    if okp and type(x) == 'number' and x >= 0 then return x, y, z end
    if okp and (type(x) == 'userdata' or type(x) == 'table') then
        local okc, cx, cy, cz = pcall(function() return x.x, x.y, x.z end)
        if okc and type(cx) == 'number' and cx >= 0 then return cx, cy, cz end
    end
    if okp then return nil end
    local okq, qx, qy, qz = pcall(function() return it.pos.x, it.pos.y, it.pos.z end)
    if okq and type(qx) == 'number' and qx >= 0 then return qx, qy, qz end
    return nil
end

-- Lying loose on the ground: not in a bin, a barrel, a unit's hands or a building.
function on_ground(it)
    local f = it.flags
    return f.on_ground == true and not (f.in_inventory or f.in_building or f.construction) and true or false
end

-- The item's owner and whether he lives: (unit, alive) or (nil, nil).
function item_owner(it)
    local ok, u = pcall(dfhack.items.getOwner, it)
    if not ok or u == nil then return nil, nil end
    local okd, dead = pcall(function()
        return dfhack.units.isDead(u) or (u.flags2 ~= nil and u.flags2.killed == true)
    end)
    return u, not (okd and dead)
end

-- The fort's race and civ (either nil when the game can't say).
function fort_race_civ()
    local okr, race = pcall(function() return df.global.plotinfo.race_id end)
    local okc, civ = pcall(function() return df.global.plotinfo.civ_id end)
    return okr and tonumber(race) or nil, okc and tonumber(civ) or nil
end

-- The race and civ of the creature a body (or part) was: (race, civ), each nil when unknown.
function corpse_race_civ(it)
    local okr, race = pcall(function() return it.race end)
    local okc, civ = pcall(function()
        local u = df.unit.find(it.unit_id)
        return u and u.civ_id
    end)
    return okr and tonumber(race) or nil, okc and tonumber(civ) or nil
end

-- A body, part or remains (DEAD_KINDS): 'own' (the fort's race
-- and civ) or 'other'; nil for anything else. A race that can't be read
-- counts as another's; a civ that can't be read as the fort's.
function corpse_side(it, kind, ctx)
    if not DEAD_KINDS[kind or ''] then return nil end
    local race, civ = corpse_race_civ(it)
    if race == nil or ctx.race == nil or race ~= ctx.race then return 'other' end
    if civ ~= nil and ctx.civ ~= nil and civ ~= ctx.civ then return 'other' end
    return 'own'
end

-- The remains of one of the fort's own, in the widest sense (nothing ever
-- destroys these): the dead_dwarf flag, or a body or part of the fort's
-- race OR its civ (or whose race, or kind, can't be read); REMAINS too.
function fort_remains(it, kind, ctx)
    if it.flags.dead_dwarf then return true end
    if kind == nil then return true end         -- can't tell what it is: kept
    if not DEAD_KINDS[kind] then return false end
    local race, civ = corpse_race_civ(it)
    if race == nil or (ctx.race ~= nil and race == ctx.race) then return true end
    if civ ~= nil and ctx.civ ~= nil and civ == ctx.civ then return true end
    return false
end

-- The context forbidden_reason reads: the cistern's tiles, the fort's race
-- and civ, and the caller's own tests for a dump zone's tile and a
-- stockpile's (opts.in_dump(x, y, z), opts.in_stockpile(x, y, z)). The other
-- races' bodies are found on the first need (one pass over the bodies).
function forbid_context(opts)
    opts = opts or {}
    local ctx = {cistern = cistern_tiles(), in_dump = opts.in_dump, in_stockpile = opts.in_stockpile}
    ctx.race, ctx.civ = fort_race_civ()
    return ctx
end

-- The bodies and parts in the game: a list (items.other's, else the whole list filtered).
local function corpse_items()
    local out = {}
    local ok = pcall(function()
        local other = df.global.world.items.other
        for _, name in ipairs({'CORPSE', 'CORPSEPIECE'}) do
            for _, it in ipairs(other[name]) do table.insert(out, it) end
        end
    end)
    if ok then return out end
    out = {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.all) do
            if CORPSE_KINDS[item_kind(it) or ''] then table.insert(out, it) end
        end
    end)
    return out
end

-- The tiles where another's body or part lies on the ground ("x,y,z" = true), once a context.
function other_corpse_tiles(ctx)
    if ctx.corpse_tiles then return ctx.corpse_tiles end
    local set = {}
    for _, it in ipairs(corpse_items()) do
        pcall(function()
            local f = it.flags
            if f.removed or f.garbage_collect or not on_ground(it) then return end
            if corpse_side(it, item_kind(it) or 'CORPSE', ctx) ~= 'other' then return end
            local x, y, z = item_pos(it)
            if x then set[tkey(x, y, z)] = true end
        end)
    end
    ctx.corpse_tiles = set
    return set
end

-- Within the 3x3 round another's body?
function near_other_corpse(ctx, x, y, z)
    local set = other_corpse_tiles(ctx)
    if next(set) == nil then return false end
    for dx = -1, 1 do
        for dy = -1, 1 do
            if set[tkey(x + dx, y + dy, z)] then return true end
        end
    end
    return false
end

-- Why the item is forbidden (see above): reason, corpse side ('own',
-- 'other' or nil). kind and x, y, z are read from the item when not given.
function forbidden_reason(it, ctx, kind, x, y, z)
    local f = it.flags
    kind = kind or item_kind(it)
    local corpse = corpse_side(it, kind, ctx)
    if not f.forbid then return 'free', corpse end
    if x == nil then x, y, z = item_pos(it) end
    if x and ctx.cistern[tkey(x, y, z)] then return 'ai', corpse end
    if x and ctx.in_dump and ctx.in_dump(x, y, z) then return 'dumped', corpse end
    if f.dead_dwarf then return 'own_dead', corpse end
    if f.owned then
        local u, alive = item_owner(it)
        if u ~= nil and not alive then return 'own_dead', corpse end
    end
    if corpse == 'own' then return 'own_dead', corpse end
    if corpse == 'other' then return 'other_dead', corpse end
    local ground = x ~= nil and on_ground(it)
    if ground and DEAD_GEAR[kind or ''] and near_other_corpse(ctx, x, y, z) then return 'other_dead', nil end
    if ground and kind == 'AMMO' and not (ctx.in_stockpile and ctx.in_stockpile(x, y, z)) then
        return 'used_ammo', nil
    end
    return 'unknown', nil
end
