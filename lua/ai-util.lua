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

-- --- the dig guard (0.105.40b) ----------------------------------------------------
--
-- Raw adamantine, the spire it stands in and the underworld under it end a
-- fort when dug into: the spire's hollow and the underworld's open floor
-- bring out what lives down there. No dig the AI marks may take such a tile,
-- one beside it (the 8 around on its level) or the one over or under it.
-- Every path that marks digging asks dig_forbidden first: quickfort's dig
-- blueprints (lua/ai-builder.lua quickfort_apply, so every level, hall, well,
-- cistern, way in, landmark, site check and gallery), the joins and widenings
-- (ai-joins.lua), the ore veins, drifts and quarries (ai-industry.lua), and
-- DFHack's dig-now (the cistern's and the water works' plugs).
--
-- dig_forbidden reads the tile itself, hidden or not (a guard, not a survey):
--   * a mineral vein whose stone is flagged DEEP_SPECIAL in the raws (raw
--     adamantine);
--   * a tile of a deep special feature: designation.feature_local in a block
--     whose local feature is a deep_special_tube or deep_surface_portal;
--   * a tile of the underworld: designation.feature_global in a block whose
--     global feature is underworld_from_layer;
--   * map special stone (tiletype material FEATURE) of such a feature, and
--     the underworld's own HFS tiles.
-- Each block and tile is read once per game tick (the memo); the raws once.
-- The Rules switch `mine_adamantine` is kept for a sealed breach plan that
-- isn't built yet: on or off, these tiles are refused.

-- (0.105.40b fix) the map's deep floor and deep levels (DEEP_MAP), once per
-- loaded map: the floor is the top level of the lowest cavern (else the
-- magma sea's top, else the spire's top); a deep level holds a block of a
-- tube or portal, the underworld, a DEEP_SPECIAL vein, a layer of unknown
-- kind or one that could not be read. dig_forbidden answers at once (nil)
-- for a tile above the floor whose levels z-1..z+1 hold nothing deep; and
-- where the guard cannot read a tile at or below the floor or beside a deep
-- level it refuses it (GUARD_ERR) instead of letting it be dug. With no
-- floor known (a test's map) both stay as before: every tile read, an
-- error let by.
-- (0.105.40b fix) 'F' (carve a fortification) cuts the tile too; a key the
-- guard does not know is refused at a deep level (DIG_KEYS_SAFE: the keys
-- that never dig).
DIG_KEYS = {d = true, h = true, u = true, j = true, i = true, r = true, F = true}   -- quickfort keys that dig
DIG_KEYS_SAFE = {x = true, s = true, e = true, T = true, v = true, M = true, t = true, p = true,
                 z = true, o = true, c = true, a = true, b = true, m = true}
GUARD_ERR = 'the dig guard could not read the tile'
-- refusals since the map loaded, each tile counted once (tiles: the set)
DIG_GUARD = DIG_GUARD or {refused = 0, by = {}, last = {}, tiles = {}}
DIG_GUARD_LAST_MAX = 5
DIG_GUARD_TILES_MAX = 20000  -- tiles remembered for the once-per-tile count (past it: counted again)

local DEEP_INORG = {}        -- inorganic index -> DEEP_SPECIAL (the raws never change while the game runs)
local GMEMO = nil            -- {tick, map, blocks, tiles, errs}
DEEP_MAP = nil               -- {key, ok, floor, levels = {[z] = true}, at}

local function deep_inorganic(idx)
    if idx == nil then return false end
    local v = DEEP_INORG[idx]
    if v ~= nil then return v end
    local ok, inorg = pcall(function() return df.global.world.raws.inorganics.all[idx] end)
    if not (ok and inorg) then ok, inorg = pcall(function() return df.global.world.raws.inorganics[idx] end) end
    v = false
    if ok and inorg then
        local okf, f = pcall(function() return inorg.flags.DEEP_SPECIAL end)
        v = okf and f == true
    end
    DEEP_INORG[idx] = v
    return v
end
is_deep_inorganic = deep_inorganic

-- A feature init's kind: 'tube', 'under', 'cavern', 'magma' or 'other'; nil unread
local function feature_kind(f)
    if not f then return nil end
    local okt, t = pcall(function() return f:getType() end)
    if okt and t ~= nil then
        local FT = df.feature_type
        if t == FT.deep_special_tube or t == FT.deep_surface_portal then return 'tube' end
        if t == FT.underworld_from_layer then return 'under' end
        if t == FT.subterranean_from_layer then return 'cavern' end
        if t == FT.magma_core_from_layer then return 'magma' end
        return 'other'
    end
    local function is(name)
        local ok, v = pcall(function() return df[name]:is_instance(f) end)
        return ok and v == true
    end
    if is('feature_init_deep_special_tubest') or is('feature_init_deep_surface_portalst') then return 'tube' end
    if is('feature_init_underworld_from_layerst') then return 'under' end
    if is('feature_init_subterranean_from_layerst') then return 'cavern' end
    if is('feature_init_magma_core_from_layerst') then return 'magma' end
    return nil
end

-- The map's features (the fallback when DFHack's init lookups are missing):
-- local ones keyed by (region x, region y, index) where the map lists their
-- region (an index alone names a different feature in each region tile),
-- and by index alone (any_tube: a tube anywhere under that index); global
-- ones by index ({[gid] = kind}). err: the list could not be read.
local function deep_features()
    local out = {tube = {}, tube_at = {}, under = {}, global = {}, gkind = {}}
    local ok = pcall(function()
        local F = df.global.world.features
        for i, f in ipairs(F.map_features) do
            local gid = F.feature_global_idx[i]
            local lid = F.feature_local_idx[i]
            local kind = feature_kind(f)
            if gid ~= nil and gid >= 0 then
                out.global[gid] = true
                out.gkind[gid] = kind
                if kind == 'under' then out.under[gid] = true end
            end
            if lid ~= nil and lid >= 0 then
                local tube = kind == 'tube'
                if tube then out.tube[lid] = true end
                local okp, fx, fy = pcall(function() return F.feature_x[i], F.feature_y[i] end)
                if okp and fx ~= nil and fy ~= nil then
                    local k = fx .. ',' .. fy .. ',' .. lid
                    out.tube_at[k] = out.tube_at[k] or tube
                end
            end
        end
    end)
    if not ok then out.err = true end
    return out
end

-- Kinds read by index, shared for a map (a cache: {ltube = {}, gkind = {}, F})
local function new_kinds() return {ltube = {}, gkind = {}} end

-- Is the block's local feature a tube or portal? true / false; nil when it has
-- none; 'err' when it could not be read.
local function block_tube(block, K)
    local lf = block.local_feature
    if lf == nil or lf < 0 then return nil end
    local rp = block.region_pos
    local okr, rx, ry = pcall(function() return rp.x, rp.y end)
    local k = (okr and rx or '?') .. ',' .. (okr and ry or '?') .. ',' .. lf
    local v = K.ltube[k]
    if v ~= nil then return v end
    local kind
    local okl = pcall(function() kind = feature_kind(dfhack.maps.getLocalInitFeature(rp, lf)) end)
    if okl and kind then
        v = kind == 'tube'
    else
        K.F = K.F or deep_features()
        local F = K.F
        if F.tube_at[k] ~= nil then v = F.tube_at[k]
        elseif F.err then v = 'err'
        else v = F.tube[lf] == true end         -- by index alone: a tube anywhere under it counts
    end
    K.ltube[k] = v
    return v
end

-- The kind of the block's global feature ('under', 'cavern', 'magma', 'other'),
-- nil when it has none or its layer is unknown; 'err' when it could not be read
local function block_global(block, K)
    local gf = block.global_feature
    if gf == nil or gf < 0 then return nil end
    local v = K.gkind[gf]
    if v ~= nil then return v or nil end
    local kind
    local okg = pcall(function() kind = feature_kind(dfhack.maps.getGlobalInitFeature(gf)) end)
    if okg and kind then
        v = kind
    else
        K.F = K.F or deep_features()
        local F = K.F
        if F.gkind[gf] then v = F.gkind[gf]
        elseif F.global[gf] then v = 'other'
        elseif F.err then v = 'err'
        else v = false end                      -- a layer the map doesn't list: unknown
    end
    K.gkind[gf] = v
    return v or nil
end

-- Does the block hold a DEEP_SPECIAL vein? {[lx * 16 + ly] = true} or nil
local function block_deep_veins(block)
    local deep
    for _, ev in ipairs(block.block_events) do
        if df.block_square_event_mineralst:is_instance(ev) and deep_inorganic(ev.inorganic_mat) then
            deep = deep or {}
            for lx = 0, 15 do
                for ly = 0, 15 do
                    if dfhack.maps.getTileAssignment(ev.tile_bitmask, lx, ly) then deep[lx * 16 + ly] = true end
                end
            end
        end
    end
    return deep
end

-- Which map is loaded (its region and size): the deep map is kept for it
function dig_guard_map_key()
    local ok, k = pcall(function()
        local m = df.global.world.map
        return ('%s,%s,%s:%s,%s,%s'):format(tostring(m.region_x), tostring(m.region_y), tostring(m.region_z),
                                           tostring(m.x_count), tostring(m.y_count), tostring(m.z_count))
    end)
    return ok and k or 'map'
end

-- The walk: every block once. ok false when the blocks could not be walked.
local function build_deep_map(key)
    local dm = {key = key, ok = false, levels = {}}
    local K = new_kinds()
    local caverns, magma_top, tube_top = {}, nil, nil
    local hz = {}
    local ok = pcall(function()
        for _, block in ipairs(df.global.world.map.map_blocks) do
            local z = block.map_pos.z
            local deep = false
            local okb = pcall(function()
                local t = block_tube(block, K)
                if t == true or t == 'err' then deep = true end
                if t == true and (not tube_top or z > tube_top) then tube_top = z end
                local g = block_global(block, K)
                if g == 'under' then
                    deep = true
                elseif g == 'cavern' then
                    local c = caverns[block.global_feature]
                    if not c then c = {lo = z, hi = z}; caverns[block.global_feature] = c end
                    if z < c.lo then c.lo = z end
                    if z > c.hi then c.hi = z end
                elseif g == 'magma' then
                    if not magma_top or z > magma_top then magma_top = z end
                elseif g == 'err' or (g == nil and block.global_feature ~= nil and block.global_feature >= 0) then
                    deep = true                 -- a layer of unknown kind
                end
                local veins = block_deep_veins(block)
                if veins then deep = true end
                -- (0.105.46, I6) the blocks deep_hazard reads: a deep vein, the
                -- spire's tube, the underworld (under: nothing else in it)
                if veins or t == true or g == 'under' then
                    local p = block.map_pos
                    hz[#hz + 1] = {p.x, p.y, z, under = (g == 'under' and not veins and t ~= true) or nil}
                end
            end)
            if not okb then
                deep = true
                local okp, p = pcall(function() return block.map_pos end)
                if okp and p then hz[#hz + 1] = {p.x, p.y, z} end       -- (I6) read again by the hazard walk
            end
            if deep then dm.levels[z] = true end
        end
    end)
    if not ok then return dm end
    dm.hz = hz
    local lowest
    for _, c in pairs(caverns) do
        if not lowest or c.lo < lowest.lo then lowest = c end
    end
    dm.floor = (lowest and lowest.hi) or magma_top or tube_top
    dm.ok = true
    dm.kinds = K
    return dm
end

-- The loaded map's deep floor and levels (built once per map; again a day
-- later when the walk failed)
function deep_map()
    local key = dig_guard_map_key()
    local dm = DEEP_MAP
    if dm and dm.key == key then
        if dm.ok then return dm end
        local okt, now = pcall(abs_tick)
        if not (okt and dm.at and now - dm.at >= TICKS_PER_DAY) then return dm end
    end
    dm = build_deep_map(key)
    local okt, now = pcall(abs_tick)
    dm.at = okt and now or nil
    DEEP_MAP = dm
    return dm
end

-- Is level z one the guard refuses on a read error: at or below the deep
-- floor, or within 1 level of a deep level (false with no deep floor known)
local function fail_closed(dm, z)
    if not (dm and dm.ok and dm.floor) then return false end
    if z <= dm.floor then return true end
    local L = dm.levels
    return L[z - 1] == true or L[z] == true or L[z + 1] == true
end
function dig_guard_fail_closed(z)
    local ok, v = pcall(function() return fail_closed(deep_map(), z) end)
    return ok and v == true
end

local function memo()
    local ok, t = pcall(abs_tick)
    t = ok and t or false
    if not GMEMO or GMEMO.tick ~= t then
        local okm, dm = pcall(deep_map)
        GMEMO = {tick = t, blocks = {}, tiles = {}, errs = {}, map = okm and dm or nil,
                 kinds = okm and dm and dm.kinds or new_kinds()}
    end
    return GMEMO
end

-- The memo dropped (a test, or a caller that just changed the map); the deep map with it.
function dig_guard_reset() GMEMO = nil; DEEP_MAP = nil end

-- (0.105.40b fix) everything the guard keeps, dropped when the map or world
-- unloads (the next map has its own raws, features and refusals)
function dig_guard_unload()
    DEEP_INORG = {}
    GMEMO = nil
    DEEP_MAP = nil
    DEEP_HAZARD_CACHE = nil
    UNDER_SEEN = {}          -- (0.105.46)
    DIG_GUARD = {refused = 0, by = {}, last = {}, tiles = {}}
end
if dfhack and dfhack.onStateChange then   -- (in the game a userdata-wrapped event, not a table)
    pcall(function()
        dfhack.onStateChange['ai-util-dig-guard'] = function(sc)
            if sc == SC_MAP_UNLOADED or sc == SC_WORLD_UNLOADED then dig_guard_unload() end
        end
    end)
end

-- What a block holds of the deep: {tube, under, deep = {[lx * 16 + ly] = true}, err}, or false
local function block_info(m, x, y, z)
    local key = (x // 16) .. ',' .. (y // 16) .. ',' .. z
    local b = m.blocks[key]
    if b ~= nil then return b end
    b = false
    local okb, block = pcall(function() return dfhack.maps.getTileBlock(x, y, z) end)
    if not okb then
        b = {err = true}
    elseif block then
        b = {}
        local K = m.kinds
        local okt = pcall(function()
            local t = block_tube(block, K)
            if t == 'err' then b.err = true          -- unknown: its special stone still counts (deep_tile)
            elseif t ~= nil then b.tube = t end
        end)
        if not okt then b.err = true end
        local okg = pcall(function()
            local g = block_global(block, K)
            if g == 'err' then b.err = true
            elseif g ~= nil then b.under = (g == 'under') end
        end)
        if not okg then b.err = true end
        local okv = pcall(function() b.deep = block_deep_veins(block) end)
        if not okv then b.err = true end
    end
    m.blocks[key] = b
    return b
end

-- The tile's material name; nil and true when it could not be read
local function tile_material(x, y, z)
    local ok, name = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z)
        local a = tt and df.tiletype.attrs[tt]
        return a and df.tiletype_material[a.material]
    end)
    if not ok then return nil, true end
    return name
end

-- Why this one tile is the deep's ('raw adamantine', 'the adamantine spire',
-- 'the underworld'), or nil; second: true when part of it could not be read
function deep_tile(x, y, z, m)
    m = m or memo()
    local k = x .. ',' .. y .. ',' .. z
    local t = m.tiles[k]
    if t ~= nil then return t or nil, m.errs[k] end
    t = false
    local err = false
    local b = block_info(m, x, y, z)
    if b then
        err = b.err == true
        local okd, d = pcall(function() return dfhack.maps.getTileFlags(x, y, z) end)
        if not okd then err = true end
        if not (okd and d) then d = nil end
        local fl = d and d.feature_local
        local fg = d and d.feature_global
        if b.deep and b.deep[(x & 15) * 16 + (y & 15)] then t = 'raw adamantine'
        elseif b.tube and fl then t = 'the adamantine spire'
        elseif b.under and fg then t = 'the underworld'
        else
            local mat, merr = tile_material(x, y, z)
            if merr then err = true end
            if mat == 'HFS' then t = 'the underworld'
            -- local special stone: the tube's (not a block's whose local feature is known not to be one)
            elseif mat == 'FEATURE' and fl and b.tube ~= false then t = 'the adamantine spire'
            elseif mat == 'FEATURE' and fg and b.under ~= false then t = 'the underworld'
            end
        end
    end
    m.tiles[k] = t
    if err then m.errs[k] = true end
    return t or nil, err or nil
end

local function guard_read(x, y, z, m)
    local why, err = deep_tile(x, y, z, m)
    if why then return why end
    local anyerr = err
    for dy = -1, 1 do
        for dx = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                why, err = deep_tile(x + dx, y + dy, z, m)
                if why then return 'next to ' .. why end
                anyerr = anyerr or err
            end
        end
    end
    why, err = deep_tile(x, y, z - 1, m)
    if why then return 'over ' .. why end
    anyerr = anyerr or err
    why, err = deep_tile(x, y, z + 1, m)
    if why then return 'under ' .. why end
    return nil, anyerr or err
end

-- Why digging (x, y, z) is refused, or nil: the tile itself is the deep's,
-- or one of the 8 beside it on its level, or the one over or under it.
-- (0.105.40b fix) nil at once above the deep floor where levels z-1..z+1
-- hold nothing deep; GUARD_ERR where the guard could not read a tile at or
-- below the floor or beside a deep level.
function dig_forbidden(x, y, z)
    x, y, z = math.tointeger(x), math.tointeger(y), math.tointeger(z)
    if not (x and y and z) then return nil end
    local okm, m = pcall(memo)
    local dm = okm and m and m.map or nil
    if dm and dm.ok and dm.floor and z - 1 > dm.floor then
        local L = dm.levels
        if not (L[z - 1] or L[z] or L[z + 1]) then return nil end
    end
    local ok, why, err = false, nil, nil
    if okm and m then ok, why, err = pcall(guard_read, x, y, z, m) end
    if ok and why then return why end
    if (not ok or err) and fail_closed(dm, z) then
        local g = DIG_GUARD
        local k = x .. ',' .. y .. ',' .. z
        g.unreadable_tiles = g.unreadable_tiles or {}
        g.nunreadable = g.nunreadable or 0
        if not g.unreadable_tiles[k] then
            -- (fix41-ff) remembered up to DIG_GUARD_TILES_MAX tiles, as the
            -- refusals are (past it each is counted again, nothing kept)
            if g.nunreadable < DIG_GUARD_TILES_MAX then
                g.unreadable_tiles[k] = true
                g.nunreadable = g.nunreadable + 1
            end
            g.unreadable = (g.unreadable or 0) + 1
        end
        return GUARD_ERR
    end
    return nil
end

-- A refusal kept for the report (by: the path that asked). (0.105.40b fix)
-- each tile counted once (a path asking for it again every day is one
-- refusal, not one a day); by[path]: the tiles that path was refused.
function dig_refused(by, x, y, z, why)
    local g = DIG_GUARD
    g.tiles = g.tiles or {}
    g.ntiles = g.ntiles or 0
    g.by = g.by or {}
    g.asked = (g.asked or 0) + 1
    local path = by or '?'
    local k = tostring(x) .. ',' .. tostring(y) .. ',' .. tostring(z)
    local seen = g.tiles[k]
    if seen and seen[path] then return false end
    if not seen and g.ntiles < DIG_GUARD_TILES_MAX then seen = {}; g.tiles[k] = seen; g.ntiles = g.ntiles + 1 end
    if seen then seen[path] = true end
    g.by[path] = (g.by[path] or 0) + 1
    if seen and next(seen, next(seen)) ~= nil then return true end   -- the tile counted already (another path)
    g.refused = (g.refused or 0) + 1
    g.last = g.last or {}
    table.insert(g.last, {by = by, x = x, y = y, z = z, why = why})
    while #g.last > DIG_GUARD_LAST_MAX do table.remove(g.last, 1) end
    return true
end

-- The first refused tile of a list of {x, y, z} (or {x, y} with `z`):
-- why, the tile; nil when every tile may be dug. `by`: kept as a refusal.
function dig_check_tiles(tiles, z, by)
    for _, t in ipairs(tiles or {}) do
        local tz = t.z or z
        local why = dig_forbidden(t.x, t.y, tz)
        if why then
            if by then dig_refused(by, t.x, t.y, tz, why) end
            return why, {x = t.x, y = t.y, z = tz}
        end
    end
    return nil
end

-- Does a quickfort dig cell's text dig (d, h, u, j, i, r, F with a priority,
-- options or extents)? Its key's first letter, its base text (no extents),
-- and its extents' width and height. Second form (unknown = true): a key
-- the guard knows neither as digging nor as safe.
local function cell_parts(text)
    local key = text:match('^%s*(%a)')
    local w, h = text:match('%((%-?%d+)%s*x%s*(%-?%d+)%)%s*$')
    local base = text:gsub('%(%-?%d+%s*x%s*%-?%d+%)%s*$', '')
    return key, base, math.tointeger(tonumber(w)) or 1, math.tointeger(tonumber(h)) or 1
end
function dig_cell(text)
    if type(text) ~= 'string' then return nil end
    local key, base, w, h = cell_parts(text)
    if not key or not DIG_KEYS[key] then return nil end
    return key, base, w, h
end
function dig_cell_unknown(text)
    if type(text) ~= 'string' then return false end
    local key = text:match('^%s*(%S)')
    if not key then return false end
    return not (DIG_KEYS[key] or DIG_KEYS_SAFE[key])
end

local function span(a, n)
    if n == 0 then n = 1 end
    if n > 0 then return a, a + n - 1 end
    return a + n + 1, a
end

-- Quickfort dig data ({[z] = {[y] = {[x] = text}}}, at pos ox, oy, oz) with
-- the refused tiles taken out (a cell with extents split into its allowed
-- tiles when part of it is refused). A channel (h) is refused over a
-- refused tile too (it digs the tile under it). Returns the data (the same
-- table when nothing is refused), how many tiles were refused and the first
-- one's reason. `by`: refusals kept for the report (nil: a dry run, not kept).
-- (0.105.40b fix) a key the guard doesn't know is refused at a deep level.
function dig_guard_data(data, ox, oy, oz, by)
    local refused, first = 0, nil
    local out, changed = {}, false
    for z, grid in pairs(data) do
        local og = {}
        out[z] = og
        local deep_z = nil
        for y, row in pairs(grid) do
            for x, text in pairs(row) do
                local key, base, w, h = dig_cell(text)
                local function put(px, py, t)
                    og[py] = og[py] or {}
                    if og[py][px] == nil then og[py][px] = t end
                end
                if not key then
                    local unknown = dig_cell_unknown(text)
                    if unknown then
                        if deep_z == nil then deep_z = dig_guard_fail_closed(oz + z) end
                    end
                    if unknown and deep_z then
                        local _, _, uw, uh = cell_parts(text)
                        local x1, x2 = span(x, uw)
                        local y1, y2 = span(y, uh)
                        local why = ('an unknown dig key (%s) at a deep level'):format(text:match('^%s*(%S)'))
                        for ty = y1, y2 do
                            for tx = x1, x2 do
                                refused = refused + 1
                                if by then dig_refused(by, ox + tx, oy + ty, oz + z, why) end
                            end
                        end
                        first = first or why
                        changed = true
                    else
                        put(x, y, text)
                    end
                else
                    local x1, x2 = span(x, w)
                    local y1, y2 = span(y, h)
                    local bad = {}
                    local nbad = 0
                    for ty = y1, y2 do
                        for tx = x1, x2 do
                            local mx, my, mz = ox + tx, oy + ty, oz + z
                            local why = dig_forbidden(mx, my, mz)
                            if not why and key == 'h' then
                                why = dig_forbidden(mx, my, mz - 1)
                                if why then why = 'a channel down to a tile ' .. why end
                            end
                            if why then
                                bad[ty * 100000 + tx] = true
                                nbad = nbad + 1
                                refused = refused + 1
                                first = first or why
                                if by then dig_refused(by, mx, my, mz, why) end
                            end
                        end
                    end
                    if nbad == 0 then
                        put(x, y, text)
                    else
                        changed = true
                        for ty = y1, y2 do
                            for tx = x1, x2 do
                                if not bad[ty * 100000 + tx] then put(tx, ty, base) end
                            end
                        end
                    end
                end
            end
        end
    end
    if not changed then return data, 0, nil end
    return out, refused, first
end

-- (0.105.40b fix) the guard itself threw over a blueprint: its levels at or
-- below the deep floor (or beside a deep level) dropped whole, the rest let
-- by as before. Returns the data, how many cells were dropped, and why.
function dig_guard_drop_deep(data, ox, oy, oz, by)
    local out, dropped = {}, 0
    for z, grid in pairs(data) do
        if dig_guard_fail_closed(oz + z) then
            for y, row in pairs(grid) do
                for x, _ in pairs(row) do
                    dropped = dropped + 1
                    if by then pcall(dig_refused, by, ox + x, oy + y, oz + z, GUARD_ERR) end
                end
            end
        else
            out[z] = grid
        end
    end
    if dropped == 0 then return data, 0, nil end
    return out, dropped, GUARD_ERR
end

-- (0.105.40b) The report's `deep_hazard` (in the `deep` section): the raw
-- adamantine the dwarves have uncovered (tiles, the highest level it is on,
-- the nearest such tile to `near` {x, y, z}), whether the spire or the
-- underworld has been seen, and the guard's refusals since the map loaded.
-- Only uncovered tiles are counted: the AI doesn't look through rock (the
-- guard does: it refuses hidden ones too). Kept a game day.
-- (0.105.40b fix) the walk reads only the blocks that can hold any of it (a
-- local feature, a deep level, at or below the deep floor) when the deep
-- map is known; the spire by the block's own region and index (block_tube).
DEEP_HAZARD_CACHE = nil
-- (0.105.46, I6) the underworld once seen on this map (by the deep map's
-- key): its blocks aren't read again (a seen tile is never hidden again)
UNDER_SEEN = UNDER_SEEN or {}

-- One block of the hazard walk, counted into base; st.best_d: the nearest so far
local function hazard_block(block, base, K, near, st)
    local p = block.map_pos
    local evs = nil
    for _, ev in ipairs(block.block_events) do
        if df.block_square_event_mineralst:is_instance(ev) and deep_inorganic(ev.inorganic_mat) then
            evs = evs or {}
            table.insert(evs, ev)
        end
    end
    local tube = block_tube(block, K) == true
    if evs or tube then
        local des = block.designation
        for lx = 0, 15 do
            local row = des[lx]
            for ly = 0, 15 do
                local d = row[ly]
                if not d.hidden then
                    local hit = false
                    if tube and d.feature_local then hit = true; base.spire_seen = true end
                    if not hit and evs then
                        for _, ev in ipairs(evs) do
                            if dfhack.maps.getTileAssignment(ev.tile_bitmask, lx, ly) then hit = true; break end
                        end
                    end
                    if hit then
                        base.adamantine_seen = true
                        base.tiles = base.tiles + 1
                        local x, y, z = p.x + lx, p.y + ly, p.z
                        if not base.top_z or z > base.top_z then base.top_z = z end
                        if type(near) == 'table' and near.x and near.y and near.z then
                            local dd = math.abs(x - near.x) + math.abs(y - near.y) + 3 * math.abs(z - near.z)
                            if not st.best_d or dd < st.best_d then
                                st.best_d = dd
                                base.nearest = {x = x, y = y, z = z}
                            end
                        end
                    end
                end
            end
        end
    end
    if not base.underworld_seen and block_global(block, K) == 'under' then
        for lx = 0, 15, 5 do
            for ly = 0, 15, 5 do
                if not block.designation[lx][ly].hidden then base.underworld_seen = true end
            end
        end
    end
end

local function new_base()
    return {adamantine_seen = false, tiles = 0, spire_seen = false, underworld_seen = false}
end

local function hazard_slices()
    local ok, S = pcall(function() return reqscript('ai-slices') end)
    return ok and type(S) == 'table' and S.run and S or nil
end
HAZARD_SLICE_MS = 30     -- (0.105.46) a report's slice of the hazard walk
HAZARD_SLICE_ITEMS = nil -- (0.105.46) and its count of blocks (nil: time only; the tests set it)

function deep_hazard(near, mine_adamantine)
    local ok, now = pcall(abs_tick)
    local day = ok and (now // TICKS_PER_DAY) or nil
    local c = DEEP_HAZARD_CACHE
    local base
    if c and day and c.day == day then
        base = c.base
    else
        local okd, dm = pcall(deep_map)
        dm = okd and dm or nil
        local limit = dm and dm.ok and dm.floor and dm or nil
        local K = (dm and dm.kinds) or new_kinds()
        if limit and type(dm.hz) == 'table' then
            -- (0.105.46, I6) only the blocks that can hold any of it (listed by
            -- the deep map's walk, once per map), sliced over reports when
            -- lua/ai-slices.lua is there; the underworld's not again once seen
            local key = dm.key
            local function visit(acc, b)
                if b.under and (acc.base.underworld_seen or UNDER_SEEN[key]) then return end
                local block = dfhack.maps.getTileBlock(b[1], b[2], b[3])
                if not block then return end
                acc.walked = acc.walked + 1
                hazard_block(block, acc.base, K, near, acc)
            end
            local function init()
                local b = new_base()
                if UNDER_SEEN[key] then b.underworld_seen = true end
                return {base = b, walked = 0}
            end
            local function finish(acc)
                local b = acc.base
                if b.underworld_seen then UNDER_SEEN[key] = true end
                b.nearest_z = b.nearest and b.nearest.z or b.top_z
                b.deep_floor = dm.floor
                return {base = b, walked = acc.walked}
            end
            local S = hazard_slices()
            local r, st
            if S then
                r, st = S.run('deep_hazard', {key = key, now = ok and now or nil, ttl = TICKS_PER_DAY,
                                              whole_first = true, items = function() return dm.hz end,
                                              init = init, visit = visit, finish = finish,
                                              max_ms = HAZARD_SLICE_MS, max_items = HAZARD_SLICE_ITEMS})
            end
            if not r then
                local acc = init()
                for _, b in ipairs(dm.hz) do pcall(visit, acc, b) end
                r, st = finish(acc), 'done'
            end
            base = r.base
            -- a pass under way: the last whole one is sent, and the next report goes on
            DEEP_HAZARD_CACHE = {day = st ~= 'partial' and day or nil, base = base, walked = r.walked,
                                 status = st}
        else
            base = new_base()
            local st = {}
            local walked = 0
            pcall(function()
                for _, block in ipairs(df.global.world.map.map_blocks) do
                    local p = block.map_pos
                    local lf = block.local_feature
                    if not limit or (lf ~= nil and lf >= 0) or p.z <= limit.floor or limit.levels[p.z] then
                        walked = walked + 1
                        hazard_block(block, base, K, near, st)
                    end
                end
            end)
            base.nearest_z = base.nearest and base.nearest.z or base.top_z
            base.deep_floor = dm and dm.ok and dm.floor or nil
            DEEP_HAZARD_CACHE = {day = day, base = base, walked = walked}
        end
    end
    local out = {}
    for k, v in pairs(base) do out[k] = v end
    local g = DIG_GUARD
    out.refused = g.refused or 0
    if out.refused > 0 then
        out.refused_by = g.by
        out.refused_last = g.last[#g.last]
    end
    if (g.unreadable or 0) > 0 then out.unreadable = g.unreadable end
    if g.swept then out.swept = g.swept end
    if mine_adamantine == true then
        out.mine_adamantine = true
        out.note = 'mine_adamantine is on, but the sealed breach plan is not built yet: adamantine is still left alone'
    end
    return out
end

-- --- (0.105.46, I6) the flows, walked once a report ------------------------------------
--
-- df.global.flows (fire, smoke, mist, miasma, clouds...) was walked whole by
-- the threats' fire and cloud reads and the miasma report, each reading every
-- flow's type, density and place. Now one walk a report groups them by type
-- (REPORT_CTX, as citizens()); each reader takes only the types it wants, in
-- the game's order. Outside a report: a walk each call, as before.
function flows_by_type()
    return report_memo('flows_by_type', function()
        local by = {}
        local i = 0
        for _, f in ipairs(df.global.flows) do
            i = i + 1
            local t = f.type
            if t ~= nil then
                local l = by[t]
                if not l then l = {}; by[t] = l end
                l[#l + 1] = {i, f}
            end
        end
        return by
    end)
end

-- The flows whose type `want(type)` says yes to (asked once per type present), in the game's order
function flows_where(want)
    local by = flows_by_type() or {}
    local picked = {}
    for t, l in pairs(by) do
        local ok, yes = pcall(want, t)
        if ok and yes then
            for _, e in ipairs(l) do picked[#picked + 1] = e end
        end
    end
    table.sort(picked, function(a, b) return a[1] < b[1] end)
    local out = {}
    for k, e in ipairs(picked) do out[k] = e[2] end
    return out
end
