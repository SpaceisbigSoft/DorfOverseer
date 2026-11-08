-- (0.105.27) Disposal: the forbidden things lying about, and what the AI
-- does with them, the DF way first. The player (all six forts) saw lock
-- symbols everywhere and nothing that ever cleared them away.
--
-- Who forbids items: the game, by its standing orders (used ammo, dead
-- others' things, dead citizens' things), and everything it dumps lands
-- forbidden. The AI forbids only what lies on its cistern's tiles, just
-- before the flood. The forbid flag doesn't say who set it, so an item that
-- matches none of the game's reasons counts as the player's ('unknown') and
-- is left alone unless the player said otherwise (player_items).
--
-- What this module does (the bridge's actions of the same names):
--   unforbid_items   the useful things let go, so the haulers store them;
--   mark_melt        worn or enemy metal gear lying loose marked for melting (the bridge
--                    adds a smelter work order: DF 50 doesn't make the job by
--                    itself, the DF wiki's Melt page: "the job order will
--                    still need to be made at a smelter");
--   mark_dump        junk (worn clothes and rags, rotten food, non-metal enemy
--                    junk) marked for the garbage dump;
--   empty_dump       what dumping left (forbidden) in the dump zones removed (dfhack.items.remove,
--                    as DFHack's clear-webs and invader-item-destroyer do);
--   set_standing_orders  DF's own standing orders on refuse, dumping and forbidding;
--   report           the `disposal` report section.
--
-- Never touched, by any of them: an item within 20 tiles of a danger (the
-- shared ai-util check), any item while a siege is on, one in a cavern while
-- the AI's cavern seal holds, one on the cistern's tiles, an artifact, one
-- owned by a living dwarf, and one whose reason is 'unknown' (unless
-- player_items). Nor what a job holds, what a unit carries, a building's or a
-- construction's part, a trader's or an enemy's (hostile), one on fire or
-- encased, nor evidence of a murder.
--
-- Cost: each call walks the item lists of the kinds it acts on once
-- (df.global.world.items.other[TYPE]) and stops at `max`; the dump zones are
-- read through their map blocks, never the whole item list.
--@ module = true

local U = reqscript('ai-util')      -- (13c) helpers shared by the modules

MAX_CAP = 500                -- items changed a call at most (the bridge's DISPOSAL_MAX and the brain's
                             -- planner_config DISPOSAL_ACTION_MAX are the same 500; a test checks)
SIEGE_MIN_INVADERS = 3       -- live invaders on the map that make a siege (a lone thief is a danger, not a siege)
MELT_ORDER_MAX = 20          -- a melt work order's amount at most
STATE_THREATS = 'ai-overseer/threats'

REASONS = {'own_dead', 'used_ammo', 'other_dead', 'dumped', 'ai', 'unknown'}

-- The kinds each action walks. Kinds the game doesn't know are skipped.
GEAR = {'WEAPON', 'ARMOR', 'HELM', 'GLOVES', 'SHOES', 'PANTS', 'SHIELD', 'AMMO'}
CLOTHES = {'ARMOR', 'HELM', 'GLOVES', 'SHOES', 'PANTS'}
USEFUL = {'WEAPON', 'ARMOR', 'HELM', 'GLOVES', 'SHOES', 'PANTS', 'SHIELD', 'AMMO', 'QUIVER', 'BACKPACK',
          'FLASK', 'GOBLET', 'CLOTH', 'THREAD', 'SKIN_TANNED', 'ROUGH', 'SMALLGEM', 'GEM', 'COIN', 'BAR',
          'CRAFTS', 'AMULET', 'BRACELET', 'EARRING', 'RING', 'CROWN', 'FIGURINE', 'SCEPTER', 'INSTRUMENT',
          'TOOL', 'TRAPCOMP', 'BOX', 'BARREL', 'BIN', 'BUCKET', 'BLOCKS'}
JUNK = {'ARMOR', 'HELM', 'GLOVES', 'SHOES', 'PANTS', 'CLOTH', 'WEAPON', 'SHIELD', 'AMMO', 'QUIVER',
        'BACKPACK', 'FLASK'}
ROTS = {'MEAT', 'FISH', 'FISH_RAW', 'FOOD', 'PLANT', 'PLANT_GROWTH', 'CHEESE', 'EGG'}
ENEMY_JUNK = {WEAPON = true, SHIELD = true, AMMO = true, QUIVER = true, BACKPACK = true, FLASK = true,
              ARMOR = true, HELM = true, GLOVES = true, SHOES = true, PANTS = true}
IS_CLOTHES = {ARMOR = true, HELM = true, GLOVES = true, SHOES = true, PANTS = true, CLOTH = true}

-- Flags that put an item out of reach for good (item_unfree's list, less the
-- ones these actions judge themselves: forbid, dump, owned, artifact, a dead
-- dwarf's, rotten)
local ALLOW = {forbid = true, dump = true, owned = true, artifact = true, dead_dwarf = true, rotten = true}

local function key(x, y, z) return x .. ',' .. y .. ',' .. z end

local function items_of(name)
    local ok, v = pcall(function() return df.global.world.items.other[name] end)
    return ok and v or nil
end

-- ---------------------------------------------------------------------------
-- What holds now: the siege, the cavern seal, the dump zones, the smelters
-- ---------------------------------------------------------------------------

-- {on, invaders}: live, free invaders on the map now.
function siege_state()
    local n = 0
    local okl, active = pcall(function() return df.global.world.units.active end)
    for _, u in ipairs(okl and active or {}) do
        local ok, yes = pcall(function()
            local Un = dfhack.units
            local f1 = u.flags1
            if f1 and (f1.caged or f1.chained) then return false end
            return Un.isInvader(u) and not Un.isDead(u) and (Un.isActive == nil or Un.isActive(u))
        end)
        if ok and yes then n = n + 1 end
    end
    return {on = n >= SIEGE_MIN_INVADERS, invaders = n}
end

-- The cavern layers the AI's seal holds now (ai-threats' record): how many.
function sealed_caverns()
    local d = U.site_get(STATE_THREATS, {})
    local n = 0
    for _, rec in pairs(type(d.sealed) == 'table' and d.sealed or {}) do
        if type(rec) == 'table' then n = n + 1 end
    end
    return n
end

-- A cavern tile: the same test as ai-threats' cavern_citizens.
local function cavern_tile(x, y, z)
    local ok, cave = pcall(function()
        local des = dfhack.maps.getTileFlags(x, y, z)
        return des and (des.feature_global or des.feature_local) and true or false
    end)
    return ok and cave
end

local function outside_tile(x, y, z)
    local ok, out = pcall(function()
        local des = dfhack.maps.getTileFlags(x, y, z)
        return des and des.outside and true or false
    end)
    return ok and out
end

local function dump_type()
    local ok, t = pcall(function() return df.civzone_type.Dump end)
    if ok and t ~= nil then return t end
    ok, t = pcall(function() return df.civzone_type.GarbageDump end)
    return ok and t or nil
end

local function zones()
    local ok, v = pcall(function() return df.global.world.buildings.other.ANY_ZONE end)
    if ok and v then return v end
    return df.global.world.buildings.all
end

-- Every garbage dump zone: {id, x1, y1, x2, y2, z, x, y, inside, b}.
function dump_zones()
    local want = dump_type()
    local out = {}
    if want == nil then return out end
    for _, b in ipairs(zones()) do
        local ok, row = pcall(function()
            if b.type ~= want then return nil end
            local okt, t = pcall(function() return b:getType() end)
            if okt and df.building_type and df.building_type.Civzone ~= nil and t ~= df.building_type.Civzone then
                return nil
            end
            local cx, cy = (b.x1 + b.x2) // 2, (b.y1 + b.y2) // 2
            return {id = b.id, x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z, x = cx, y = cy,
                    inside = not outside_tile(cx, cy, b.z), b = b}
        end)
        if ok and row then table.insert(out, row) end
    end
    return out
end

local function zone_has(zn, x, y, z)
    if z ~= zn.z or x < zn.x1 or x > zn.x2 or y < zn.y1 or y > zn.y2 then return false end
    local ok, yes = pcall(dfhack.buildings.containsTile, zn.b, x, y)
    if ok and yes ~= nil then return yes and true or false end
    return true
end

local function in_dump(dumps, x, y, z)
    for _, zn in ipairs(dumps) do
        if zone_has(zn, x, y, z) then return zn end
    end
    return nil
end

-- The items lying in one dump zone, read through its map blocks (one block
-- of 16x16 tiles at a time): calls fn(it) for each, stops when fn returns false.
local function zone_items(zn, fn)
    local seen = {}
    for bx = zn.x1 - zn.x1 % 16, zn.x2, 16 do
        for by = zn.y1 - zn.y1 % 16, zn.y2, 16 do
            local ok, block = pcall(dfhack.maps.getTileBlock, math.max(bx, zn.x1), math.max(by, zn.y1), zn.z)
            if ok and block then
                for _, id in ipairs(block.items) do
                    if not seen[id] then
                        seen[id] = true
                        local it = df.item.find(id)
                        if it and it.flags.on_ground and not (it.flags.removed or it.flags.garbage_collect)
                                and zone_has(zn, it.pos.x, it.pos.y, it.pos.z) then
                            if fn(it) == false then return false end
                        end
                    end
                end
            end
        end
    end
    return true
end

local function built(b)
    local ok, yes = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    return not ok or yes
end

-- {smelters, magma_smelters}: built ones.
function smelters()
    local s, m = 0, 0
    local list
    local ok, v = pcall(function() return df.global.world.buildings.other.FURNACE_ANY end)
    list = ok and v or df.global.world.buildings.all
    for _, b in ipairs(list) do
        pcall(function()
            local t = b.type
            if t == df.furnace_type.Smelter and built(b) then s = s + 1
            elseif t == df.furnace_type.MagmaSmelter and built(b) then m = m + 1 end
        end)
    end
    return s, m
end

-- The id of a melt work order with jobs left, or nil.
function melt_order()
    local found
    pcall(function()
        for _, o in ipairs(df.global.world.manager_orders.all) do
            if o.job_type == df.job_type.MeltMetalObject and (o.amount_left or 1) > 0 then
                found = o.id
                return
            end
        end
    end)
    return found
end

-- ---------------------------------------------------------------------------
-- An item's reason, and what keeps it from these actions
-- ---------------------------------------------------------------------------

-- What every action reads once: the dangers, the siege, the seal, the
-- dumps, and the shared classifier's context (ai-util forbid_context: the
-- cistern's tiles, the fort's race and civ, the other races' bodies when
-- first needed), with this module's dump and stockpile tests.
function context(opts)
    opts = opts or {}
    local ctx = U.forbid_context()
    ctx.spots, ctx.siege, ctx.sealed = U.danger_spots(), siege_state(), sealed_caverns() > 0
    ctx.dumps, ctx.player_items = dump_zones(), opts.player_items == true
    ctx.in_dump = function(x, y, z) return in_dump(ctx.dumps, x, y, z) ~= nil end
    ctx.in_stockpile = function(x, y, z) return in_stockpile(ctx, x, y, z) end
    return ctx
end

-- The stockpiles' boxes by level (read once a call, for used ammo).
local function stockpiles(ctx)
    if ctx.piles then return ctx.piles end
    local by = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.STOCKPILE) do
            pcall(function()
                by[b.z] = by[b.z] or {}
                table.insert(by[b.z], b)
            end)
        end
    end)
    ctx.piles = by
    return by
end

function in_stockpile(ctx, x, y, z)
    for _, b in ipairs(stockpiles(ctx)[z] or {}) do
        if x >= b.x1 and x <= b.x2 and y >= b.y1 and y <= b.y2 then
            local ok, yes = pcall(dfhack.buildings.containsTile, b, x, y)
            if not ok or yes == nil or yes then return true end
        end
    end
    return false
end

-- Why a forbidden item is forbidden ('free' when it isn't): the one
-- classifier the census uses too (ai-util forbidden_reason).
function reason_of(it, kind, x, y, z, ctx)
    return (U.forbidden_reason(it, ctx, kind, x, y, z))
end

-- nil if the item may be touched, else why not (a word): what no action
-- touches (a job's, a unit's, a building's...), then the masks.
function blocked(it, x, y, z, reason, ctx)
    local why = U.item_unfree(it, ALLOW)
    if why then return why == 'held' and 'held' or 'busy' end
    if x == nil then return 'off_map' end
    local f = it.flags
    if f.artifact then return 'artifact' end
    if f.owned then
        local u, alive = U.item_owner(it)
        if u == nil or alive then return 'owned' end
    end
    if ctx.cistern[key(x, y, z)] then return 'cistern' end
    if U.near_danger(ctx.spots, x, y, z) then return 'danger' end
    if ctx.sealed and cavern_tile(x, y, z) then return 'cavern' end
    if reason == 'unknown' and not ctx.player_items then return 'unknown' end
    return nil
end

local function position(it)
    local ok, x, y, z = pcall(dfhack.items.getPosition, it)
    if ok and type(x) == 'number' and x >= 0 then return x, y, z end
    return nil
end

local function is_metal(it)
    local ok, yes = pcall(function()
        local mi = dfhack.matinfo.decode(it)
        return mi and mi.material and mi.material.flags.IS_METAL and true or false
    end)
    return ok and yes
end

local function quality(it)
    local ok, q = pcall(function() return it:getQuality() end)
    return ok and tonumber(q) or 0
end

local function wear(it)
    local ok, w = pcall(function() return it.wear end)
    return ok and tonumber(w) or 0
end

-- The squads' assigned gear (the uniforms' items), by id.
local function assigned_ids()
    local set = {}
    pcall(function()
        for _, v in pairs(df.global.plotinfo.equipment.items_assigned) do
            pcall(function() for _, id in ipairs(v) do set[id] = true end end)
        end
    end)
    return set
end

local function set_of(list, default)
    local out = {}
    for _, r in ipairs(type(list) == 'table' and #list > 0 and list or default) do out[r] = true end
    return out
end

local function new_result(dry_run)
    return {ok = true, n = 0, skipped = {}, by_reason = {}, by_type = {}, dry_run = dry_run or nil}
end

local function skip(res, why) res.skipped[why] = (res.skipped[why] or 0) + 1 end

local function count(res, reason, kind)
    res.n = res.n + 1
    res.by_reason[reason] = (res.by_reason[reason] or 0) + 1
    res.by_type[kind] = (res.by_type[kind] or 0) + 1
end

-- One pass over each kind in `kinds` (each list once, though a kind be named
-- twice), fn(it, kind) for each item until it returns false.
local function walk(kinds, fn)
    local done = {}
    for _, kind in ipairs(kinds) do
        if not done[kind] then
            done[kind] = true
            local list = items_of(kind)
            for _, it in ipairs(list or {}) do
                if fn(it, kind) == false then return end
            end
        end
    end
end

local function siege_refusal(ctx, what)
    return {ok = false, rejected = true, waiting = true, siege = true, invaders = ctx.siege.invaders,
            error = ('a siege is on (%d invaders on the map): no %s until it is over'):format(ctx.siege.invaders, what)}
end

local function clamp_max(max, default)
    max = math.tointeger(tonumber(max)) or default
    if max < 1 then max = 1 end
    if max > MAX_CAP then max = MAX_CAP end
    return max
end

-- ---------------------------------------------------------------------------
-- The actions
-- ---------------------------------------------------------------------------

-- Forbidden items of the given reasons let go (forbid off), so the haulers
-- store them: only loose ones on the ground, of the useful kinds (no bodies:
-- the burial and refuse rules see to those). opts: reasons (default own_dead,
-- used_ammo, other_dead), max (default 50), player_items ('unknown' is let go
-- only when it is listed and player_items is true). 'dumped' and 'ai' are
-- refused: the dump's would be carried back and dumped again for ever, and
-- the cistern's stay forbidden.
function unforbid_items(opts, dry_run)
    opts = opts or {}
    local want = set_of(opts.reasons, {'own_dead', 'used_ammo', 'other_dead'})
    for _, r in ipairs({'dumped', 'ai'}) do
        if want[r] then
            return {ok = false, rejected = true, error = ('unforbid_items: never the %s items'):format(r)}
        end
    end
    local ctx = context(opts)
    if ctx.siege.on then return siege_refusal(ctx, 'unforbidding') end
    local max = clamp_max(opts.max, 50)
    local res = new_result(dry_run)
    walk(USEFUL, function(it, kind)
        local f = it.flags
        if not f.forbid or not U.on_ground(it) then return end
        local x, y, z = position(it)
        local reason = x and reason_of(it, kind, x, y, z, ctx) or 'unknown'
        local why = blocked(it, x, y, z, reason, ctx)
        if why then skip(res, why); return end
        if not want[reason] then skip(res, 'reason'); return end
        if not dry_run then it.flags.forbid = false end
        count(res, reason, kind)
        if res.n >= max then res.more = true; return false end
    end)
    res.unforbidden = res.n
    if res.n == 0 and not dry_run then
        res.ok, res.rejected, res.error = false, true, 'no forbidden item of those reasons may be let go now'
    end
    return res
end

-- Is it a tool the fort works with: a pick (mining) or an axe (wood
-- cutting), by its skill or its id? A weapon whose kind can't be read counts
-- as one (kept).
function is_tool(it, kind)
    if kind ~= 'WEAPON' then return false end
    local ok, yes = pcall(function()
        local st = it.subtype
        local js = df.job_skill
        local sk = st.skill_melee
        if sk == js.MINING or sk == js.AXE then return true end
        local id = tostring(st.id or '')
        return id:find('PICK', 1, true) ~= nil or id:find('AXE', 1, true) ~= nil
    end)
    return not ok or yes == true
end

-- Made by another race than the fort's (crafted items record their maker's
-- race), or nil when the item doesn't say.
local function foreign_made(it, ctx)
    local ok, r = pcall(function() return it.maker_race end)
    if not ok or type(r) ~= 'number' or r < 0 or ctx.race == nil then return nil end
    return r ~= ctx.race
end

-- Metal weapons, armour and ammo marked for melting (melt on, forbid and
-- dump off: a forbidden item isn't melted): the clutter, not the stock.
-- Only an item lying loose on the ground (never one in a bin, a hand or a
-- building), and of those:
--   forbidden: worn (wear >= 1) or a dead enemy's (other_dead; kept when
--     keep_enemy_gear and unworn);
--   not forbidden: only outside every stockpile, and worn (wear >= 2) or
--     made by another race (the enemy's left on the field; whether a maker
--     was an enemy or a trader can't be told, so never stock in a pile).
-- Never a pick or an axe (the miners' and woodcutters' tools), a masterwork,
-- an artifact, or a squad's assigned gear. opts: max (default 20),
-- keep_masterwork (only true: masterworks are never melted),
-- keep_enemy_gear, player_items. Returns also smelters, magma_smelters,
-- can_melt, already (marked before), melt_order (a waiting order's id) and
-- needs_order.
function mark_melt(opts, dry_run)
    opts = opts or {}
    if opts.keep_masterwork == false then
        return {ok = false, rejected = true, error = 'masterworks are never melted (keep_masterwork must stay true)'}
    end
    local ctx = context(opts)
    if ctx.siege.on then return siege_refusal(ctx, 'melting') end
    local max = clamp_max(opts.max, 20)
    local keep_enemy = opts.keep_enemy_gear == true
    local assigned = assigned_ids()
    local res = new_result(dry_run)
    res.already = 0
    walk(GEAR, function(it, kind)
        local f = it.flags
        if f.melt then res.already = res.already + 1; return end
        if not U.on_ground(it) then return end
        if not is_metal(it) then return end
        local x, y, z = position(it)
        if not x then return end
        local reason = reason_of(it, kind, x, y, z, ctx)
        local w = wear(it)
        local enemy
        if f.forbid then
            enemy = reason == 'other_dead'
            if w < 1 and not enemy then return end
            if enemy and keep_enemy and w < 1 then skip(res, 'enemy_gear'); return end
        else
            if in_stockpile(ctx, x, y, z) then return end
            enemy = foreign_made(it, ctx) == true
            if w < 2 and not enemy then return end
            if enemy and keep_enemy and w < 2 then skip(res, 'enemy_gear'); return end
        end
        if is_tool(it, kind) then skip(res, 'tool'); return end
        local why = blocked(it, x, y, z, reason, ctx)
        if why then skip(res, why); return end
        if quality(it) >= 5 then skip(res, 'masterwork'); return end
        if assigned[it.id] then skip(res, 'assigned'); return end
        if not dry_run then
            it.flags.melt = true
            it.flags.forbid = false
            it.flags.dump = false
        end
        count(res, reason, kind)
        if res.n >= max then res.more = true; return false end
    end)
    res.marked = res.n
    res.smelters, res.magma_smelters = smelters()
    res.can_melt = res.smelters + res.magma_smelters > 0
    res.melt_order = melt_order()
    res.needs_order = res.can_melt and res.melt_order == nil and (res.n + res.already) > 0
    if res.n == 0 and not dry_run and not res.needs_order then
        res.ok, res.rejected, res.error = false, true, 'no worn or enemy metal gear may be marked for melting now'
    end
    return res
end

-- Junk marked for the garbage dump (dump on, forbid and melt off), lying
-- loose on the ground only: worn (wear >= 2) non-metal clothes and rags,
-- rotten food, and a dead other's non-metal gear. opts: reasons (the forbidden reasons taken,
-- and 'free' for what isn't forbidden; default own_dead, used_ammo,
-- other_dead; what isn't forbidden is taken whatever they say), max (default
-- 50), player_items ('unknown' is taken only when both it is listed and
-- player_items is true). Refused (but in a dry run) when the fort has no dump zone.
function mark_dump(opts, dry_run)
    opts = opts or {}
    local ctx = context(opts)
    if ctx.siege.on then return siege_refusal(ctx, 'dumping') end
    if #ctx.dumps == 0 and not dry_run then
        return {ok = false, rejected = true, no_dump_zone = true, stale = {'disposal'},
                error = 'the fort has no garbage dump zone (place_dump first)'}
    end
    local want = set_of(opts.reasons, {'own_dead', 'used_ammo', 'other_dead', 'free'})
    local max = clamp_max(opts.max, 50)
    local res = new_result(dry_run)
    res.no_dump_zone = #ctx.dumps == 0 or nil
    local kinds = {}
    for _, k in ipairs(JUNK) do table.insert(kinds, k) end
    for _, k in ipairs(ROTS) do table.insert(kinds, k) end
    local rots = {}
    for _, k in ipairs(ROTS) do rots[k] = true end
    walk(kinds, function(it, kind)
        local f = it.flags
        if f.dump then return end
        if not U.on_ground(it) then return end      -- never one in a bin, a hand or a building
        local x, y, z = position(it)
        local junk
        if rots[kind] then
            junk = f.rotten
        else
            local metal = is_metal(it)
            if not metal and IS_CLOTHES[kind] and wear(it) >= 2 then junk = true end
            if not junk and not metal and ENEMY_JUNK[kind] and f.forbid then junk = 'enemy' end
        end
        if not junk then return end
        local reason = x and reason_of(it, kind, x, y, z, ctx) or 'unknown'
        if junk == 'enemy' and reason ~= 'other_dead' then return end
        if reason == 'dumped' then return end          -- in the dump already
        -- what isn't forbidden is junk whatever the reasons (the reasons pick the forbidden)
        local why = blocked(it, x, y, z, reason, ctx)
        if why then skip(res, why); return end
        if reason ~= 'free' and not want[reason] then skip(res, 'reason'); return end
        if not dry_run then
            it.flags.dump = true
            it.flags.forbid = false
            it.flags.melt = false
        end
        count(res, reason, kind)
        if res.n >= max then res.more = true; return false end
    end)
    res.marked = res.n
    if res.n == 0 and not dry_run then
        res.ok, res.rejected, res.error = false, true, 'no junk may be marked for the dump now'
    end
    return res
end

-- What dumping left in the dump zones removed from the game
-- (dfhack.items.remove, each in a pcall): only a FORBIDDEN loose item on the
-- ground there (what the haulers dump lands forbidden; an unforbidden one
-- lying there is somebody's, left alone). Never the remains of one of the
-- fort's own (a body or part of its race or its civ, or the dead_dwarf
-- flag: a ghost waits on those), one in a container or a unit's hands, one
-- that holds other items, an artifact, one a job holds, a building's part,
-- an owned one, or one the masks keep. opts: max (default 100).
function empty_dump(opts, dry_run)
    opts = opts or {}
    local ctx = context(opts)
    if ctx.siege.on then return siege_refusal(ctx, 'emptying of the dump') end
    if #ctx.dumps == 0 then
        return {ok = false, rejected = true, no_dump_zone = true, stale = {'disposal'},
                error = 'the fort has no garbage dump zone'}
    end
    local max = clamp_max(opts.max, 100)
    local res = new_result(dry_run)
    res.failed = 0
    for _, zn in ipairs(ctx.dumps) do
        local go = zone_items(zn, function(it)
            local f = it.flags
            if not f.forbid then skip(res, 'not_forbidden'); return end
            if not U.on_ground(it) then skip(res, 'held'); return end
            if f.container then skip(res, 'container'); return end
            local okc, inside = pcall(dfhack.items.getContainedItems, it)
            if okc and type(inside) == 'table' and #inside > 0 then skip(res, 'container'); return end
            local kind = U.item_kind(it)
            if U.fort_remains(it, kind, ctx) then skip(res, 'own_remains'); return end
            local x, y, z = it.pos.x, it.pos.y, it.pos.z
            local why = blocked(it, x, y, z, 'dumped', ctx)
            if why then skip(res, why); return end
            if not dry_run then
                local ok, r = pcall(dfhack.items.remove, it)
                if not ok or r == false then res.failed = res.failed + 1; return end
            end
            count(res, 'dumped', 'any')
            if res.n >= max then res.more = true; return false end
        end)
        if go == false then break end
    end
    res.by_type = nil
    res.removed = res.n
    if res.n == 0 and not dry_run then
        res.ok, res.rejected = false, true
        res.error = res.failed > 0 and ('the game removed none of the %d items tried'):format(res.failed)
            or 'nothing in the dump may be removed now'
    end
    return res
end

-- DF's standing orders on refuse, dumping and forbidding, set by name
-- ('gather_refuse' or 'standing_orders_gather_refuse'): {name = 0|1 (or
-- true/false)}. Only the forbid_*, gather_* and dump_* orders that exist and
-- read 0 or 1 now; any other name refuses the whole call.
ORDER_FAMILIES = {'forbid_', 'gather_', 'dump_'}

local function order_global(name)
    if type(name) ~= 'string' then return nil end
    local short = name:gsub('^standing_orders_', '')
    local fam = false
    for _, p in ipairs(ORDER_FAMILIES) do
        if short:sub(1, #p) == p then fam = true end
    end
    if not fam or not short:match('^[%w_]+$') then return nil end
    return 'standing_orders_' .. short, short
end

function read_order(full)
    local ok, v = pcall(function() return df.global[full] end)
    if not ok then return nil end
    if v == true then return 1 elseif v == false then return 0 end
    return v
end

function set_standing_orders(orders, dry_run)
    if type(orders) ~= 'table' or next(orders) == nil then
        return {ok = false, rejected = true, error = 'set_standing_orders needs orders {name = 0|1}'}
    end
    local plan, was = {}, {}
    for name, v in pairs(orders) do
        local full, short = order_global(name)
        if not full then
            return {ok = false, rejected = true, error = 'set_standing_orders: not a refuse, dump or forbid order: ' .. tostring(name)}
        end
        if v == true then v = 1 elseif v == false then v = 0 end
        if v ~= 0 and v ~= 1 then
            return {ok = false, rejected = true, error = ('set_standing_orders: %s must be 0 or 1'):format(short)}
        end
        local cur = read_order(full)
        if cur == nil then
            return {ok = false, rejected = true, error = 'set_standing_orders: the game has no order ' .. short}
        end
        if cur ~= 0 and cur ~= 1 then
            return {ok = false, rejected = true, error = ('standing order %s reads %s, not 0 or 1: left alone'):format(short, tostring(cur))}
        end
        was[short] = cur
        if cur ~= v then plan[short] = {full = full, v = v} end
    end
    local set = {}
    for short, p in pairs(plan) do set[short] = p.v end
    if dry_run then return {ok = true, dry_run = true, would_set = next(set) and set or nil, now = was} end
    for _, p in pairs(plan) do
        local ok = pcall(function()
            -- the global's own kind: a bool order stays a bool
            local cur = df.global[p.full]
            if type(cur) == 'boolean' then df.global[p.full] = p.v == 1 else df.global[p.full] = p.v end
        end)
        if not ok or read_order(p.full) ~= p.v then
            return {ok = false, error = 'the game did not keep ' .. p.full, was = was}
        end
    end
    return {ok = true, set = next(set) and set or nil, was = was, unchanged = next(set) == nil or nil}
end

-- ---------------------------------------------------------------------------
-- The report section
-- ---------------------------------------------------------------------------

-- {dump_zones = [{id, x, y, z, inside, items}], dumped_items, marked_dump,
-- marked_melt, smelters, magma_smelters, sealed_caverns, siege, invaders}
function report()
    local out = {dump_zones = {}, dumped_items = 0, marked_dump = 0, marked_melt = 0}
    for _, zn in ipairs(dump_zones()) do
        local n = 0
        zone_items(zn, function() n = n + 1 end)
        table.insert(out.dump_zones, {id = zn.id, x = zn.x, y = zn.y, z = zn.z, inside = zn.inside, items = n})
        out.dumped_items = out.dumped_items + n
    end
    -- the marks: one pass over the items in play
    local list = items_of('IN_PLAY')
    if not list then
        local ok, all = pcall(function() return df.global.world.items.all end)
        list = ok and all or {}
    end
    for _, it in ipairs(list) do
        local f = it.flags
        if not (f.removed or f.garbage_collect) then
            if f.dump then out.marked_dump = out.marked_dump + 1 end
            if f.melt then out.marked_melt = out.marked_melt + 1 end
        end
    end
    out.smelters, out.magma_smelters = smelters()
    out.melt_order = melt_order()
    out.sealed_caverns = sealed_caverns()
    local s = siege_state()
    out.siege, out.invaders = s.on, s.invaders
    return out
end
