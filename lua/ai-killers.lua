-- (item3) A killer among the fort's own: vampires, werebeasts and other
-- cursed citizens and residents, and the living citizens and residents who
-- have killed the fort's people; with a cell to lock one away in.
--
-- Why (F, 13 Nov): 70 "bleed" deaths in the log over 16 hours read like a
-- vampire at work. They were not: 42 dwarves died in 3 minutes when a hill
-- titan got into the shelter (y257), and after DF restarted 28 of them were
-- told a second time as their ghosts were put to rest (fixed in the bridge's
-- death_details). This module is the check that would have said so: no
-- cursed citizen, nobody living with a killing on record.
--
-- What it reads (all behind pcall: fields this DF may name otherwise):
--   * the curse: dfhack.units.isBloodsucker / isNightCreature, the unit's
--     curse tags (unit.curse.add_tags1/2: BLOODSUCKER, NOT_LIVING, CRAZED,
--     OPPOSED_TO_LIFE...) and the same tags on its active syndromes' effects;
--     a werebeast also by unit.enemy.were_race when it differs from the
--     unit's race and birth race (DF sets it to the own race on ordinary
--     units), and changed now when unit.enemy.normal_race differs from its race;
--   * the killings: world.incidents.all (newest first, SCAN_MAX at most,
--     WINDOW_TICKS back) whose victim was one of the fort's own (its civ or
--     group) and whose killer (incident.criminal) is a living citizen or
--     resident. Not counted: a victim berserk, changed into a beast or a
--     vampire (killed lawfully), a fight of the horseplay or training kind
--     (a sparring accident); a brawl or a nonlethal fight (a beating gone
--     too far) is counted apart;
--   * DF's own crimes (world.crimes.all: mode Murder, BloodDrinking,
--     AttemptedMurder) whose criminal is one of them.
--
-- Each suspect gets a confidence the brain acts on:
--   certain  the game's own curse flag (a vampire, a werebeast);
--   strong   two killings or more (not brawls), a death by drained blood,
--            or a murder or blood-drinking crime DF holds against them;
--   weak     one killing, or brawls only: said, never acted on.
-- The first time a suspect is seen is kept in the save (`seen_ticks`), so
-- the brain notes before it acts.
--
--   report()        the `killers` section: {list = [{id, name, kind,
--                   confidence, citizen, resident, tags, kills, brawls,
--                   lawful, victims, causes, crimes, drained, berserk,
--                   changed, child, squad_id, x, y, z, seen_ticks, cell}],
--                   cells = [{unit_id, locked, out, kind, days, pile, drink,
--                   food, pile_empty, let_outs, stocking, pile_error,
--                   pile_all_food, pile_fixed, pile_refound, pile_lost, fort_meals, meals_out}]
--                   (0.105.97: the cell's pile; 0.105.98: its settings put
--                   right, found again by its name, lost),
--                   rooms (free jail zones and bedrooms), scanned}
--   cell(o, dry)    o.units: the ids to lock away (each in a burrow on a
--                   jail zone, else a free bedroom; the room's doors locked
--                   once they are inside); every cell not listed let out;
--                   o.release_only: only the let-outs (the AI halted). A
--                   dwarf locked in who grows thirsty or hungry is let out
--                   to eat and drink (doors open, out of the burrow) and
--                   taken back once fed. (0.105.97) A pile of drink and
--                   prepared meals is made inside the cell, its doors opened
--                   for the haulers while it runs out of drink; while it holds
--                   drink (meals) the let-out waits for THIRST_LAST (HUNGER_LAST).
--                   {ok, placed, locked, waiting, out, released, stocking, apart}
--   held_ids()      (0.105.97) {unit_id = true}: every unit with a cell and
--                   every strong or certain suspect (not a child, not the
--                   law); is_held(u) the same for one unit. The other rules'
--                   last guard: no burrow, squad or office for them.
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/killers'
CELL_PREFIX = 'AI killer cell '
DAY = 1200
-- (0.105.107) killings looked for three years back, everyone's (was one year):
-- B runs a game year in ~1.5-2 real hours, so a killer's older killing aged
-- out and the cell let them go ("no longer needed", 24 Nov 16:36); Ducim
-- strangled the doctor three minutes later (16:39), his third killing that day
WINDOW_TICKS = 3 * 403200
SCAN_MAX = 4000            -- incidents read at most (the newest)
OLD_RUN = 200              -- this many older than the window in a row: the scan stops
MAX_ROWS = 12
THIRST_OUT, HUNGER_OUT = 20000, 40000   -- (DF: thirsty ~25000, dehydrated ~50000) let out before
THIRST_BACK, HUNGER_BACK = 3000, 10000  -- taken back once fed and watered
CURSE_TAGS = {'BLOODSUCKER', 'NOT_LIVING', 'OPPOSED_TO_LIFE', 'CRAZED', 'NIGHT_CREATURE', 'SUPERNATURAL',
              'NO_EAT', 'NO_DRINK', 'NO_SLEEP'}
LAWFUL_CONFLICT = {Horseplay = true, Training = true}
-- a fist fight or a beating gone too far (a sheriff's beating is Nonlethal): said, never acted on
BRAWL_CONFLICT = {Brawl = true, Nonlethal = true}
STRONG_CRIMES = {Murder = true, BloodDrinking = true, AttemptedMurder = true}
-- (0.105.101) a law officer's killings are looked for three years back (B,
-- 24 Nov: the sheriff killed three citizens in y263, y264 and y266, never two
-- within a year, so law_swap never saw two)
LAW_WINDOW_TICKS = 3 * 403200
LAW_KILLS = 2               -- (0.105.99) a law officer's killings outside a punishment: the office goes
LAW_PUNISHED = 1            -- (item21) a law officer's convicts killed in DF's beatings: the office goes too

-- --- helpers ---------------------------------------------------------------

local function now_tick() return U.now_tick(0) end            -- (r6) ai-util's: 0 when it can't be read

local function txt(s)
    if s == nil then return nil end
    local ok, v = pcall(dfhack.df2utf, s)
    return ok and v or s
end

local function name_of(u) return U.name_of_conv(u, txt) end   -- (r6) ai-util's

local function is(fn, u)
    if type(fn) ~= 'function' then return false end
    local ok, v = pcall(fn, u)
    return ok and v == true
end

local function dead(u) return is(dfhack.units.isDead, u) end

local function citizen(u)
    local ok, v = pcall(dfhack.units.isCitizen, u, true)
    return ok and v == true
end

local function resident(u) return is(dfhack.units.isResident, u) end

-- one of the fort's own, alive or dead (its civ or its group)
local function own(u)
    if is(dfhack.units.isOwnGroup, u) then return true end
    local ok, o = pcall(function() return u.civ_id == df.global.plotinfo.civ_id end)
    return ok and o == true
end

local function mood_name(u)
    local ok, m = pcall(function() return u.mood >= 0 and df.mood_type[u.mood] or nil end)
    return ok and m or nil
end

local function changed(u)
    local ok, yes = pcall(function() return u.enemy.normal_race ~= -1 and u.enemy.normal_race ~= u.race end)
    return ok and yes == true
end

local function enum_name(enum, v) return U.enum_text(enum, v) end   -- (r6) ai-util's

-- the curse tags set on a mask (unit.curse.add_tags1/2, a syndrome effect's tags1/2)
local function mask_tags(mask, into)
    if mask == nil then return end
    for _, t in ipairs(CURSE_TAGS) do
        local ok, v = pcall(function() return mask[t] end)
        if ok and v == true then into[t] = true end
    end
end

-- {TAG = true} from the unit's curse and its active syndromes' effects
function curse_tags(u)
    local set = {}
    pcall(function() mask_tags(u.curse.add_tags1, set) end)
    pcall(function() mask_tags(u.curse.add_tags2, set) end)
    pcall(function()
        for _, s in ipairs(u.syndromes.active) do
            pcall(function()
                local syn = df.syndrome.find(s.type)
                for _, ce in ipairs(syn and syn.ce or {}) do
                    pcall(function() mask_tags(ce.tags1, set) end)
                    pcall(function() mask_tags(ce.tags2, set) end)
                end
            end)
        end
    end)
    return set
end

-- 'vampire', 'werebeast', 'cursed' (undead-like tags) or nil
function curse_kind(u, tags)
    tags = tags or curse_tags(u)
    if is(dfhack.units.isBloodsucker, u) or tags.BLOODSUCKER then return 'vampire' end
    -- (0.105.48) DF sets enemy.were_race (transform_race) to the unit's own
    -- race on ordinary units, so "~= -1" was true of every citizen (War-hold:
    -- 87 "certain werebeasts", the murderer cell never reached). A were-race
    -- counts only when it differs from both its race now and its birth race.
    local okw, were = pcall(function()
        local w = u.enemy.were_race
        return w ~= nil and w ~= -1 and w ~= u.race and w ~= u.enemy.normal_race
    end)
    if is(dfhack.units.isNightCreature, u) or tags.CRAZED or (okw and were == true) or changed(u) then
        return 'werebeast'
    end
    if tags.NOT_LIVING or tags.OPPOSED_TO_LIFE then return 'cursed' end
    return nil
end

-- the living citizens and residents: {id = u}
function members()
    local out = {}
    local okl, active = pcall(U.units_active)
    for _, u in ipairs(okl and active or {}) do
        if not dead(u) and (citizen(u) or resident(u)) then out[u.id] = u end
    end
    return out
end

-- (0.105.99) the units DF sentenced (a crime of theirs sentenced, or in the
-- punishments queue): a sheriff's or captain's killing of one is a punishment
function convict_ids()
    local out = {}
    pcall(function()
        local list = df.global.world.crimes.all
        for i = 0, #list - 1 do
            pcall(function() if list[i].flags.sentenced then out[list[i].criminal] = true end end)
        end
    end)
    pcall(function()
        local list = df.global.plotinfo.punishments
        for i = 0, #list - 1 do out[list[i].criminal] = true end
    end)
    return out
end

-- The killings of the fort's own by a living member, newest first:
-- {killer_id = {kills, brawls, lawful, punished, victims = {names}, causes = {CAUSE = n}, drained}}
-- (0.105.99) `punished`: a convict killed by the law (a beating): lawful,
-- not counted. B, 23 Nov: the sheriff and the captain of the guard each
-- killed a dwarf with their fists in a tantrum's brawl (one activity, no
-- crime, no sentence, punches by both at each other too): kills like any other
function killings(mem, now)
    local by = {}
    local scanned, old = 0, 0
    local convicts, is_law = nil, {}
    local ok, list = pcall(function() return df.global.world.incidents.all end)
    if not ok or not list then return by, 0 end
    local n = 0
    pcall(function() n = #list end)
    for i = n - 1, 0, -1 do
        if scanned >= SCAN_MAX or old >= OLD_RUN then break end
        scanned = scanned + 1
        local inc = list[i]
        pcall(function()
            local y, t = inc.event_year, inc.event_time
            local age = (type(y) == 'number' and y >= 0) and now - U.abs_tick(y, t or 0) or 0
            if age > LAW_WINDOW_TICKS then
                old = old + 1
                return
            end
            old = 0
            local cause = inc.death_cause
            if type(cause) ~= 'number' or cause < 0 then return end
            local kid, vid = inc.criminal, inc.victim
            if not mem[kid] or kid == vid then return end
            -- (0.105.101) past a year only a law officer's killings still count
            if age > WINDOW_TICKS then
                if is_law[kid] == nil then is_law[kid] = law(mem[kid]) end
                if not is_law[kid] then return end
            end
            local v = df.unit.find(vid)
            if not v or not own(v) then return end
            local row = by[kid] or {kills = 0, brawls = 0, lawful = 0, punished = 0, victims = {}, causes = {}}
            by[kid] = row
            local conflict = nil
            pcall(function() conflict = enum_name(df.conflict_level, inc.conflict_level) end)
            if mood_name(v) == 'Berserk' or changed(v) or is(dfhack.units.isBloodsucker, v)
                    or LAWFUL_CONFLICT[conflict] then
                row.lawful = row.lawful + 1
                return
            end
            -- (item21) a convict's death is DF's punishment, the officer in office or no longer
            convicts = convicts or convict_ids()
            if convicts[vid] then row.punished = row.punished + 1; return end
            local cname = enum_name(df.death_type, cause)
            row.causes[cname] = (row.causes[cname] or 0) + 1
            if cname:find('DRAIN') then row.drained = true end
            if BRAWL_CONFLICT[conflict] then row.brawls = row.brawls + 1 else row.kills = row.kills + 1 end
            -- (0.105.112) people killed (no animal), any conflict; the newest tick
            if not is(dfhack.units.isAnimal, v) then row.people, row.last = (row.people or 0) + 1, math.max(row.last or 0, now - age) end
            if #row.victims < 3 then table.insert(row.victims, name_of(v)) end
        end)
    end
    return by, scanned
end

-- DF's crimes against a living member: {criminal_id = {Murder = n, ...}}
function crimes(mem)
    local by = {}
    pcall(function()
        local list = df.global.world.crimes.all
        for i = #list - 1, math.max(0, #list - 1000), -1 do
            pcall(function()
                local cr = list[i]
                local kind = enum_name(df.crime_type, cr.mode)
                if STRONG_CRIMES[kind] and mem[cr.criminal] then
                    by[cr.criminal] = by[cr.criminal] or {}
                    by[cr.criminal][kind] = (by[cr.criminal][kind] or 0) + 1
                end
            end)
        end
    end)
    return by
end

-- (0.105.99) the law offices a unit holds (SHERIFF, CAPTAIN_OF_THE_GUARD)
function law_codes(u)
    local out = {}
    pcall(function()
        for _, p in ipairs(dfhack.units.getNoblePositions(u) or {}) do
            local code = tostring(p.position.code)
            if code:find('SHERIFF') or code:find('CAPTAIN_OF_THE_GUARD') then table.insert(out, code) end
        end
    end)
    return out
end

-- (0.105.99) is unit id `id` a law officer who killed LAW_KILLS or more
-- outside a punishment (the report's last word, in the save's record)?
function law_killer(id)
    local s = state().seen[tostring(id)]
    return type(s) == 'table' and s.law_killer == true
end

-- the sheriff or captain of the guard (a punishment can kill: never locked away for it)
function law(u)
    local ok, yes = pcall(function()
        for _, p in ipairs(dfhack.units.getNoblePositions(u) or {}) do
            local code = tostring(p.position.code)
            if code:find('SHERIFF') or code:find('CAPTAIN_OF_THE_GUARD') then return true end
            local okr, r = pcall(function() return p.position.responsibilities.LAW_ENFORCEMENT end)
            if okr and r then return true end
        end
        return false
    end)
    return ok and yes == true
end

function confidence(kind, k, cr)
    if kind == 'vampire' or kind == 'werebeast' then return 'certain' end
    k = k or {}
    cr = cr or {}
    if (k.kills or 0) >= 2 or k.drained or next(cr) ~= nil then return 'strong' end
    if (k.kills or 0) + (k.brawls or 0) > 0 or kind == 'cursed' then return 'weak' end
    return nil
end

-- --- the save's record -----------------------------------------------------

-- {seen = {uid = {tick, confidence}}, cells = {uid = {zone, kind, tick, doors, locked, out}}}
function state()
    local d = U.site_get(SITE_KEY, {})
    d.seen = type(d.seen) == 'table' and d.seen or {}
    d.cells = type(d.cells) == 'table' and d.cells or {}
    return d
end

local HELD_MEMO = nil      -- (0.105.97) held_ids read once a second at most (each candidate asks); a save clears it
local function save(d) HELD_MEMO = nil; pcall(U.site_put, SITE_KEY, d) end

-- --- rooms and doors (as ai-threats' moon cells) ----------------------------

local function burrow_named(name, make)
    for _, b in ipairs(df.global.plotinfo.burrows.list) do
        if tostring(b.name) == name then return b end
    end
    if not make then return nil end
    local b = df.burrow:new()
    b.id = df.global.plotinfo.burrows.next_id
    df.global.plotinfo.burrows.next_id = b.id + 1
    b.name = name
    df.global.plotinfo.burrows.list:insert('#', b)
    return b
end

local function zone_by_id(id)
    local ok, b = pcall(df.building.find, id)
    if ok and b then return b end
    for _, z in ipairs(df.global.world.buildings.all) do
        if z.id == id then return z end
    end
end

local function in_zone(z, x, y, zz)
    if zz ~= z.z or x < z.x1 or x > z.x2 or y < z.y1 or y > z.y2 then return false end
    local ok, yes = pcall(dfhack.buildings.containsTile, z, x, y)
    return not ok or yes
end

-- the doors and hatches on a zone's tiles and the ring round it
function zone_doors(z)
    local out = {}
    for y = z.y1 - 1, z.y2 + 1 do
        for x = z.x1 - 1, z.x2 + 1 do
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z.z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    out[b.id] = b
                end
            end)
        end
    end
    return out
end

local function other_in_zone(z, uid)
    local okl, active = pcall(U.units_active)
    for _, u in ipairs(okl and active or {}) do
        if u.id ~= uid and not dead(u) then
            local ok, inside = pcall(function() return in_zone(z, u.pos.x, u.pos.y, u.pos.z) end)
            if ok and inside then return true end
        end
    end
    return false
end

-- the zones held by a cell now: ours and ai-threats' moon cells
local function taken_zones(d)
    local taken = {}
    for _, c in pairs(d.cells) do if type(c) == 'table' and c.zone then taken[c.zone] = true end end
    pcall(function()
        for _, c in pairs(reqscript('ai-threats').load_state().cells) do
            if type(c) == 'table' and c.zone then taken[c.zone] = true end
        end
    end)
    return taken
end

-- a jail zone, else a free bedroom; the nearest to pos, never one taken
function cell_room(pos, taken)
    local best, bd, kind
    local function try(z, k)
        if taken[z.id] then return end
        local dd = math.abs(z.x1 - pos.x) + math.abs(z.y1 - pos.y) + 3 * math.abs(z.z - pos.z)
        if not bd or dd < bd then best, bd, kind = z, dd, k end
    end
    pcall(function() for _, z in ipairs(df.global.world.buildings.other.ZONE_DUNGEON) do try(z, 'jail') end end)
    if best then return best, kind end
    pcall(function()
        for _, z in ipairs(df.global.world.buildings.other.ZONE_BEDROOM) do
            if z.assigned_unit_id == -1 then try(z, 'bedroom') end
        end
    end)
    return best, kind
end

local function count_rooms(taken)
    local n = 0
    pcall(function() for _, z in ipairs(df.global.world.buildings.other.ZONE_DUNGEON) do
        if not taken[z.id] then n = n + 1 end
    end end)
    pcall(function() for _, z in ipairs(df.global.world.buildings.other.ZONE_BEDROOM) do
        if z.assigned_unit_id == -1 and not taken[z.id] then n = n + 1 end
    end end)
    return n
end

local function need(u)
    local th, hu = 0, 0
    pcall(function() th = u.counters2.thirst_timer or 0 end)
    pcall(function() hu = u.counters2.hunger_timer or 0 end)
    return th, hu
end

local function set_doors(c, locked)
    local errs
    for _, bid in ipairs(c.doors or {}) do
        local ok, err = pcall(function()
            local b = df.building.find(bid)
            if b and not select(2, U.lock_door(b, locked, 'killers')) then error('the lock could not be written') end -- (0.105.47) ai-util: the walk map redone
        end)
        if not ok then errs = (errs or '') .. tostring(err):sub(1, 60) end
    end
    return errs
end

local function assign(uid, u, on)
    pcall(function()
        local b = burrow_named(CELL_PREFIX .. uid, false)
        if b and u then dfhack.burrows.setAssignedUnit(b, u, on) end
    end)
end

-- a locked-in dwarf grown thirsty or hungry let out (doors open, out of the
-- burrow); returns true when let out now. (0.105.97) While the cell's pile
-- holds drink (meals), only at THIRST_LAST (HUNGER_LAST): out_levels, in
-- the larder's part below. Each let-out counted (let_outs, in the save).
local function let_out(uid, c, u, t, dry, memo)
    if not c.locked or not u then return false end
    local th, hu = need(u)
    local tl, hl = THIRST_OUT, HUNGER_OUT
    pcall(function() tl, hl = out_levels(c, memo, t) end)
    if urgent_now(c, u, t) then tl, hl = THIRST_LAST, HUNGER_LAST end   -- (0.105.114) not calm: the last resort only
    if th < tl and hu < hl then return false end
    if not dry then
        set_doors(c, false)
        assign(uid, u, false)
        c.locked, c.doors, c.out = false, {}, t
        c.let_outs = (tonumber(c.let_outs) or 0) + 1
    end
    return true
end

local function free(uid, c, u, dry)
    if dry then return end
    set_doors(c, false)
    pcall(function()
        local b = burrow_named(CELL_PREFIX .. uid, false)
        if b then
            if u then dfhack.burrows.setAssignedUnit(b, u, false) end
            dfhack.burrows.clearTiles(b)
        end
    end)
    c.pile_name = c.pile_name or (LARDER_PREFIX .. uid)      -- (0.105.98) found by its name too
    pcall(larder_remove, c)     -- (0.105.97) the cell's pile goes with it
end

-- --- the cell's larder (0.105.97) ----------------------------------------------
--
-- (0.105.97) A killer's cell keeps them fed and watered inside it. Live 23
-- Nov, B (the Monastery, no jail zone): the cells were the killers' own free
-- bedrooms, with no drink or food in them, so each killer was let out every
-- time their thirst passed THIRST_OUT, walked through the fort and was taken
-- back once fed; the killers were "waiting" (out) almost every cycle of the
-- hour, and Degël killed again inside hospital zone 333 while out. Now a
-- small stockpile is made inside the cell room (1-2 free floor tiles, never
-- the bed's or a door's tile, nor beside a door), taking only drink and
-- prepared meals and linked to nothing, so haulers bring drink and food in
-- and the killer drinks and eats there.
--
-- The doors: kept locked (the lock is what holds a killer in a tantrum or a
-- strange mood; a burrow only keeps a sane dwarf at their work) and opened
-- only while the pile runs low, for at most RESTOCK_TICKS, so the haulers
-- can walk in; the killer stays assigned to the cell's burrow meanwhile, so
-- they have no reason to leave. Locked again once stocked (and nobody else
-- inside), or when the time is up; then not opened again for RESTOCK_GAP (a
-- fort with no drink at all would hold the doors open for good). A drink
-- barrel a hauler leaves in the pile counts (its drink is counted inside it).
-- While the pile holds drink a thirsty killer is let out only at THIRST_LAST
-- (near DF's dehydration), while it holds meals a hungry one only at
-- HUNGER_LAST: a last resort. With none, the old levels (THIRST_OUT,
-- HUNGER_OUT) stay.
LARDER_PREFIX = 'AI cell larder '
THIRST_LAST, HUNGER_LAST = 45000, 70000
RESTOCK_TICKS = 2 * DAY        -- the doors open this long at most for the haulers
RESTOCK_GAP = 3 * DAY          -- and not again sooner than this after
LARDER_TRIES = 3               -- placings tried before the cell goes without one
LARDER_SCAN = 400              -- items in the pile looked at at most
LARDER_FOOD_VECTORS = {'meat', 'fish', 'unprepared_fish', 'egg', 'plants', 'cheese_plant', 'cheese_animal',
                       'seeds', 'leaves', 'powder_plant', 'powder_creature', 'glob', 'glob_paste', 'glob_pressed',
                       'liquid_plant', 'liquid_animal', 'liquid_misc'}
LARDER_DRINK_VECTORS = {'drink_plant', 'drink_animal'}

local function larder_builder() return reqscript('ai-builder') end

-- the cell's pile, while it stands
-- (0.105.98) The id kept (c.pile) is always the stockpile's building id; when
-- it no longer finds a stockpile of ours, the pile is looked for by its name
-- (c.pile_name, "AI cell larder <uid>") and the id kept again (c.pile_refound
-- counts it); found by neither, the id is forgotten (c.pile_lost counts it) so
-- larder_make lays a new one. Live 23 Nov 22:11, B: the report gave one
-- cell's pile as 1538 and a probe found no building 1538 just after. The
-- report only gives an id that found a stockpile that cycle, so the pile went
-- after it (a cell let go takes its pile with it; a pile moved out of a gate's
-- opening, ai-gates-works move_stockpile, keeps its name under a new id; a pile
-- whose tiles are all built over goes): the name finds it again in the
-- second case, and a cell whose id was lost by any way finds its own pile
-- instead of laying a second one beside it.
local function larder_ours(b, name)
    local okt, yes = pcall(function() return b:getType() == df.building_type.Stockpile end)
    if not (okt and yes) then return false end
    if not name then return true end
    local okn, n = pcall(function() return tostring(b.name or '') end)
    return okn and (n == name or n == '')       -- '' : a 0.105.97 pile whose name didn't take
end

local function larder_by_name(name)
    if not name then return nil end
    local found
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.STOCKPILE) do
            if tostring(b.name) == name then found = b; return end
        end
    end)
    return found
end

function larder_pile(c)
    if type(c) ~= 'table' then return nil end
    if c.pile then
        local ok, b = pcall(df.building.find, tonumber(c.pile))
        if ok and b and larder_ours(b, c.pile_name) then return b end
    end
    if not c.pile_name then return nil end
    local b = larder_by_name(c.pile_name)
    if b then
        if c.pile then c.pile_refound = (tonumber(c.pile_refound) or 0) + 1 end
        c.pile = b.id
        return b
    end
    if c.pile then c.pile_lost, c.pile = (tonumber(c.pile_lost) or 0) + 1, nil end
    return nil
end

-- a tile of the room the pile may take: floor, no building (bed, door,
-- chest...) on it, no pile, no water; strict: no door beside it either
local function larder_tile_free(z, x, y, strict)
    if not in_zone(z, x, y, z.z) then return false end
    local ok, free = pcall(function()
        local tt = dfhack.maps.getTileType(x, y, z.z)
        if not tt or df.tiletype.attrs[tt].shape ~= df.tiletype_shape.FLOOR then return false end
        local des = dfhack.maps.getTileFlags(x, y, z.z)
        if des and (des.pile or (des.flow_size or 0) > 0) then return false end
        if dfhack.buildings.findAtTile(xyz2pos(x, y, z.z)) then return false end
        if not strict then return true end
        for dy = -1, 1 do
            for dx = -1, 1 do
                local b = dfhack.buildings.findAtTile(xyz2pos(x + dx, y + dy, z.z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    return false
                end
            end
        end
        return true
    end)
    return ok and free == true
end

-- the pile's rectangle: two free tiles side by side, else one; away from
-- the doors first (a small bedroom may have no such tile: then beside one)
function larder_spot(z)
    for _, strict in ipairs({true, false}) do
        local one
        for y = z.y1, z.y2 do
            for x = z.x1, z.x2 do
                if larder_tile_free(z, x, y, strict) then
                    if larder_tile_free(z, x + 1, y, strict) then return {x = x, y = y, z = z.z, w = 2, h = 1} end
                    if larder_tile_free(z, x, y + 1, strict) then return {x = x, y = y, z = z.z, w = 1, h = 2} end
                    one = one or {x = x, y = y, z = z.z, w = 1, h = 1}
                end
            end
        end
        if one then return one end
    end
    return nil
end

-- drink and prepared meals only, written by hand and read back.
-- (0.105.98) Live 23 Nov 22:11, B (DFHack 53.17-r1): both cells' piles took
-- every food (meat 14800/14800, seeds, plants, globs... all on, prepared
-- meals on) and both rows said pile_all_food. 0.105.97 ran DFHack's presets
-- (`stockpiles import library/booze -s <id>`, then `library/preparedmeals -m
-- enable`) and wrote by hand only when they didn't read right; the end state
-- is what a new `f` pile gets (every food on), so neither the presets nor
-- the hand-written loops changed that pile when they ran: the likeliest
-- reading is that the new pile's food lists were not yet filled (length 0:
-- nothing to clear, no drink to enable, so the read-back failed) and were
-- filled with everything on after, and nothing looked at the pile again.
-- Now: no presets (commands whose effect we can't follow or test here; the
-- hand-written settings are the same each time and read back); every list in settings.food written
-- element by element (every one off, then drink_plant and drink_animal all
-- on), prepared_meals on and every other food switch off, flags.food on and
-- every other category off, bins 0 (max_barrels kept). Read back exactly; on
-- creation and again each cycle the cell stands while the read-back differs
-- (larder_check: c.pile_fixed counts the corrections, c.pile_all_food only
-- when the write itself didn't take).
LARDER_FLAGS = {'animals', 'food', 'furniture', 'corpses', 'refuse', 'stone', 'ammo', 'coins', 'bars_blocks',
                'gems', 'finished_goods', 'leather', 'cloth', 'wood', 'weapons', 'armor', 'sheet'}
local LARDER_DRINK, LARDER_VECTORS = {}, {}
for _, k in ipairs(LARDER_DRINK_VECTORS) do LARDER_DRINK[k] = true; table.insert(LARDER_VECTORS, k) end
for _, k in ipairs(LARDER_FOOD_VECTORS) do table.insert(LARDER_VECTORS, k) end

-- the fields of a settings struct: the known names, and whatever pairs() gives
local function larder_fields(s, known)
    local seen, out = {}, {}
    for _, k in ipairs(known) do if not seen[k] then seen[k] = true; table.insert(out, k) end end
    pcall(function()
        for k in pairs(s) do
            if type(k) == 'string' and not seen[k] then seen[k] = true; table.insert(out, k) end
        end
    end)
    return out
end

-- a vector of switches: its length, else nil (a boolean, a number: not one)
local function larder_len(v)
    if type(v) ~= 'userdata' and type(v) ~= 'table' then return nil end
    local ok, n = pcall(function() return #v end)
    return ok and type(n) == 'number' and n or nil
end

local function larder_on(x) return x == true or x == 1 end

-- (item 5) a switch written in the type it reads: DF's food lists read as
-- 0/1, and a boolean written to a number errors (in a pcall: B's pile said
-- pile_all_food, 24 Nov 16:46)
local function larder_put(t, k, want)
    if type(t[k]) == 'number' then t[k] = want and 1 or 0 else t[k] = want end
end

-- the lengths of the pile's food lists added up (a new pile's may be 0)
function larder_size(sp)
    local n = 0
    pcall(function()
        local f = sp.settings.food
        for _, k in ipairs(larder_fields(f, LARDER_VECTORS)) do
            local okv, v = pcall(function() return f[k] end)
            n = n + ((okv and larder_len(v)) or 0)
        end
    end)
    return n
end

-- true when the pile takes drink and prepared meals and nothing else.
-- quick: each list's first and last switch only (B's meat list is 14800
-- long: the whole read is kept for once a day, larder_keep_right)
function larder_reads_right(sp, quick)
    local ok, right = pcall(function()
        local f, fl = sp.settings.food, sp.settings.flags
        for _, k in ipairs(larder_fields(fl, LARDER_FLAGS)) do
            local okv, v = pcall(function() return fl[k] end)
            if okv and type(v) == 'boolean' and v ~= (k == 'food') then return false end
        end
        if fl.food ~= true or not larder_on(f.prepared_meals) then return false end
        local drinks = 0
        for _, k in ipairs(larder_fields(f, LARDER_VECTORS)) do
            local okv, v = pcall(function() return f[k] end)
            v = okv and v
            local n = larder_len(v)
            if n then
                local want = LARDER_DRINK[k] == true
                if quick then
                    if n > 0 and (larder_on(v[0]) ~= want or larder_on(v[n - 1]) ~= want) then return false end
                else
                    for i = 0, n - 1 do
                        if larder_on(v[i]) ~= want then return false end
                    end
                end
                if want then drinks = drinks + n end
            elseif (type(v) == 'boolean' or (k == 'prepared_meals' and type(v) == 'number'))
                    and larder_on(v) ~= (k == 'prepared_meals') then
                return false
            end
        end
        if drinks == 0 then return false end      -- lists not filled yet: no drink to take
        local okb, bins = pcall(function() return sp.storage.max_bins end)
        if okb and type(bins) == 'number' and bins ~= 0 then return false end
        return true
    end)
    return ok and right == true
end

-- the settings written; true when the pile reads right after
function larder_settings(sp)
    pcall(function()
        local f = sp.settings.food
        for _, k in ipairs(larder_fields(f, LARDER_VECTORS)) do
            pcall(function()
                local v = f[k]
                local n = larder_len(v)
                if n then
                    local want = LARDER_DRINK[k] == true
                    for i = 0, n - 1 do pcall(larder_put, v, i, want) end
                elseif type(v) == 'boolean' then
                    f[k] = (k == 'prepared_meals')
                end
            end)
        end
        pcall(larder_put, f, 'prepared_meals', true)
    end)
    pcall(function()
        local fl = sp.settings.flags
        for _, k in ipairs(larder_fields(fl, LARDER_FLAGS)) do
            pcall(function() if type(fl[k]) == 'boolean' then fl[k] = (k == 'food') end end)
        end
        fl.food = true
    end)
    pcall(function() sp.storage.max_bins = 0 end)
    return larder_reads_right(sp)
end

-- (0.105.98) the stockpile on a tile: findAtTile's building when it is one,
-- else the newest stockpile whose box holds the tile (the id kept is always
-- the stockpile's own building id, never a zone's or a bed's)
local function larder_at(x, y, zz)
    local okf, b = pcall(dfhack.buildings.findAtTile, xyz2pos(x, y, zz))
    if okf and b and larder_ours(b, nil) then return b end
    local best
    pcall(function()
        for _, p in ipairs(df.global.world.buildings.other.STOCKPILE) do
            if p.z == zz and x >= p.x1 and x <= p.x2 and y >= p.y1 and y <= p.y2
                    and (not best or p.id > best.id) then
                best = p
            end
        end
    end)
    return best
end

-- (item 5) barrels: its tiles - 1 (at least 1): a tile holds one item or
-- container, so 2 drink barrels could fill a 2-tile pile and leave the meals
-- no tile. On creation and each cycle (B's were made with 2).
function larder_barrels(sp)
    local tiles = (sp.x2 - sp.x1 + 1) * (sp.y2 - sp.y1 + 1)
    local want = math.max(1, tiles - 1)
    if sp.storage.max_barrels ~= want then sp.storage.max_barrels = want end
    return want
end

-- the pile made in the cell room (when none stands); the pile, or nil and why
function larder_make(uid, c, z, dry)
    if not dry then c.pile_name = c.pile_name or (LARDER_PREFIX .. uid) end   -- (0.105.98) found again by it
    local sp = larder_pile(c)
    if not sp and dry then sp = larder_by_name(LARDER_PREFIX .. uid) end
    if sp then return sp end
    if (tonumber(c.pile_tries) or 0) >= LARDER_TRIES then return nil, 'no pile could be made in the cell' end
    local r = larder_spot(z)
    if not r then return nil, 'no free floor in the cell for a pile' end
    if dry then return nil, 'dry run' end
    c.pile_tries = (tonumber(c.pile_tries) or 0) + 1
    local okq, good = pcall(function()
        return (larder_builder().qf_try('place', {{x = 0, y = 0, text = ('f(%dx%d)'):format(r.w, r.h)}}, r.z, r.x, r.y, false))
    end)
    if not okq or not good then return nil, 'the game would not place a pile in the cell' end
    local b = larder_at(r.x, r.y, r.z)
    if not b then return nil, 'the new pile was not found' end
    pcall(function() b.name = LARDER_PREFIX .. uid end)
    pcall(larder_barrels, b)
    pcall(function() b.storage.max_bins = 0 end)
    c.pile, c.pile_tries = b.id, nil
    c.pile_all_food = (not larder_settings(b)) or nil   -- the write didn't take: said in the report
    pcall(function()
        c.pile_tried = c.pile_all_food and now_tick() or nil
        c.pile_size = c.pile_all_food and larder_size(b) or nil
    end)
    return b
end

-- (0.105.98) each cycle the cell stands: a pile that no longer reads drink
-- and meals only (B's two, made by 0.105.97; or one DF filled after it was
-- made) written again; c.pile_fixed counts the corrections that took
-- (each cycle the quick read; the whole read once a day, c.pile_read)
LARDER_READ_GAP = DAY
function larder_keep_right(c, sp, dry)
    if not sp then return false end
    local okt, t = pcall(now_tick)
    t = okt and tonumber(t) or nil
    local whole = not (t and c.pile_read and t >= c.pile_read and t - c.pile_read < LARDER_READ_GAP)
    if larder_reads_right(sp, not whole) then
        if not dry then
            c.pile_all_food = nil
            if whole then c.pile_read = t end
        end
        return false
    end
    if dry then return true end
    -- a write that didn't take is tried again once a day, not each cycle, or
    -- at once when the pile's lists change length (DF filling a new pile's)
    local size = larder_size(sp)
    if c.pile_all_food and t and c.pile_tried and t >= c.pile_tried and t - c.pile_tried < LARDER_READ_GAP
            and c.pile_size == size then
        return false
    end
    local ok = larder_settings(sp)
    if ok then c.pile_fixed, c.pile_read = (tonumber(c.pile_fixed) or 0) + 1, t end
    c.pile_all_food, c.pile_tried, c.pile_size = (not ok) or nil, (not ok) and t or nil, (not ok) and size or nil
    return ok
end

-- the drink (units) and prepared meals (items) the pile holds, a barrel's
-- drink counted inside it; nil when there is no pile. memo: one read a call
function larder_stock(c, memo)
    local sp = larder_pile(c)
    if not sp then return nil, nil end
    if memo and memo[sp.id] then return memo[sp.id][1], memo[sp.id][2] end
    local drink, food, seen = 0, 0, 0
    local function look(it)
        local okf, f = pcall(function() return it.flags.forbid end)
        if okf and f then return end
        local okt, t = pcall(function() return df.item_type[it:getType()] end)
        if not okt then return end
        local okn, n = pcall(function() return it.stack_size end)
        n = (okn and tonumber(n)) or 1
        if t == 'DRINK' then drink = drink + n elseif t == 'FOOD' then food = food + n end
    end
    pcall(function()
        for _, it in ipairs(dfhack.buildings.getStockpileContents(sp)) do
            seen = seen + 1
            if seen > LARDER_SCAN then break end
            look(it)
            pcall(function() for _, ci in ipairs(dfhack.items.getContainedItems(it)) do look(ci) end end)
        end
    end)
    if memo then memo[sp.id] = {drink, food} end
    return drink, food
end

-- (item 5) the fort's free prepared meals (at most FORT_MEALS_CAP counted),
-- once a call; 0 when they can't be read
FORT_MEALS_CAP = 20
function fort_meals(memo)
    if memo and memo.fort_meals ~= nil then return memo.fort_meals end
    local n = 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.FOOD) do
            if U.item_free(it) then n = n + 1 end
            if n >= FORT_MEALS_CAP then break end
        end
    end)
    if memo then memo.fort_meals = n end
    return n
end

-- (item 5) Live B, 24 Nov 16:46: Ducim's pile held 3 drink, no meal (the
-- fort cooks ~110 a day); he was out (hunger 40000) and killed. The doors
-- opened only while the pile had no drink, so meals never got in. Now low
-- with no drink, or no meal while the fort has free ones (none: not opened).
local function larder_low(c, memo)
    local drink, food = larder_stock(c, memo)
    if drink == nil then return false end
    return drink <= 0 or (food <= 0 and fort_meals(memo) > 0)
end

-- (item 5) the meals' clock: c.meal_none, when the pile was first seen with
-- no meal; c.meal_open, when the doors were first opened for the haulers
-- after it (both cleared once a meal is in). Not in a dry run.
MEAL_WAIT = 2 * DAY
function larder_meal_track(c, t, memo)
    local drink, food = larder_stock(c, memo)
    if drink == nil or food > 0 then c.meal_none, c.meal_open = nil, nil; return end
    c.meal_none = c.meal_none or t
    if c.restock then c.meal_open = c.meal_open or t end
end

-- (item 5) no meal can reach the pile: the fort has none free, or the pile
-- has held none for MEAL_WAIT since the doors were opened for the haulers
function meals_unreachable(c, t, memo)
    if fort_meals(memo) <= 0 then return true end
    return c.meal_open ~= nil and t ~= nil and t - c.meal_open >= MEAL_WAIT
end

-- the levels a locked-in dwarf is let out at: the last-resort ones while
-- the pile holds drink (thirst) or meals (hunger); (item 5) the hunger's
-- last-resort one too while no meal is in but one may still come
function out_levels(c, memo, t)
    local drink, food = larder_stock(c, memo)
    local hl = HUNGER_OUT
    if drink ~= nil and (food > 0 or not meals_unreachable(c, t, memo)) then hl = HUNGER_LAST end
    return ((drink or 0) > 0) and THIRST_LAST or THIRST_OUT, hl
end

-- each cycle while the cell stands: the pile made if missing; a locked cell
-- whose pile runs low opened for the haulers (not sooner than RESTOCK_GAP
-- after the last time). 'open' when the doors were opened now, 'wait' when
-- the pile runs low but the doors stay locked (inside the gap), else nil.
-- (0.105.97, verifier) a killer in a tantrum (or enraged): the doors never
-- opened for them, and shut again if open (B's killings were tantrums)
local function raging(u)
    if not u then return false end
    local okm, m = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
    return okm and (m == 'Tantrum' or m == 'Enraged') or false
end

-- (0.105.114) a held killer who is not calm: 'raging' (a tantrum, enraged or
-- berserk), 'transformed' (in a were form now), 'were' (a werebeast curse's
-- syndrome: WERECURSE or a BODY_TRANSFORMATION effect), else nil. Live E, 25
-- Nov 06:00-08:00: Dentconstruct (a werebeast, two citizens killed) was out
-- of his cell 30 of 77 cycles, the doors opened for the haulers each time
-- the pile ran low ("waits for drink and meals"); he killed two at 08:00.
-- Such a one is locked at once: the doors never opened for the haulers
-- (drink and meals come once calm), let out only at the last-resort levels.
function urgent_of(u)
    if not u then return nil end
    if raging(u) or mood_name(u) == 'Berserk' then return 'raging' end
    if changed(u) then return 'transformed' end
    local found = nil
    pcall(function()
        local BT = nil
        pcall(function() BT = df.creature_interaction_effect_type.BODY_TRANSFORMATION end)
        for _, a in ipairs(u.syndromes.active) do
            local syn = df.syndrome.find(a.type)
            if syn then
                pcall(function()
                    for _, cl in ipairs(syn.syn_class) do
                        if (type(cl) == 'string' and cl or cl.value) == 'WERECURSE' then found = 'were' end
                    end
                end)
                pcall(function()
                    for _, ce in ipairs(syn.ce) do
                        if BT ~= nil and ce:getType() == BT then found = 'were' end
                    end
                end)
                if found then return end
            end
        end
    end)
    return found
end

-- the urgency now: the unit's own, or the brain's (the killer_cell action's
-- `urgent`: a werebeast, one who killed within a day), kept a DAY
function urgent_now(c, u, t)
    local own = urgent_of(u)
    if own then return own end
    if c and c.urgent_brain and t and t - c.urgent_brain >= 0 and t - c.urgent_brain < DAY then return 'brain' end
    return nil
end

local function larder_check(uid, c, z, t, dry, memo, u)
    local sp, why = larder_make(uid, c, z, dry)
    if not dry then c.pile_error = (not sp) and why or nil end
    pcall(larder_keep_right, c, sp, dry)       -- (0.105.98) drink and meals only, each cycle
    if sp and not dry then pcall(larder_barrels, sp); pcall(larder_meal_track, c, t, memo) end   -- (item 5)
    if not sp or not c.locked or c.out then return nil end
    if not larder_low(c, memo) then return nil end
    -- (0.105.97, merge) never opened while the killer rages (B's killings were tantrums)
    if raging(u) or urgent_now(c, u, t) then return 'wait' end   -- (0.105.114) nor while not calm
    if c.restock_end and t - c.restock_end < RESTOCK_GAP then return 'wait' end
    if not dry then
        set_doors(c, false)
        c.locked, c.doors, c.restock = false, {}, t
        pcall(larder_meal_track, c, t, memo)      -- (item 5) the doors opened: the meals' clock
    end
    return 'open'
end

-- while the doors stand open for the haulers: true; false (and the doors may
-- lock again) once stocked or the time is up
-- (0.105.97, verifier) and the doors shut at once when the killer starts to
-- rage while they stand open (the burrow holds no one in a tantrum)
local function restocking(c, t, dry, memo, u)
    if not c.restock then return false end
    if not raging(u) and not urgent_now(c, u, t) and larder_low(c, memo) and t - c.restock < RESTOCK_TICKS then return true end
    if not dry then c.restock, c.restock_end = nil, t end
    return false
end

-- --- (0.105.97) the held: kept in, kept apart ---------------------------------
-- Live 23 Nov, B (no jail: the cells are burrows on bedrooms): the recreation
-- rule added the celled Degel and Fath Shemnish to the recreation burrow (a
-- dwarf in several burrows may go to any of them), `appoint` made Fath (2
-- kills) militia captain and soldier_swap had drafted him; the killers were
-- "waiting" out of their cells almost every cycle and Degel killed again in a
-- hospital. Every rule that puts a dwarf into a burrow, a squad or an office
-- asks is_held first (reqscript('ai-killers').is_held, behind pcall); the
-- brain skips the same ids (brain/planner_killers.py held_killer_ids).

-- {unit_id = true}: those with a cell, and the strong or certain suspects
-- the report saw (d.seen), but never a child or the law (s.exempt)
function held_ids()
    local okc, sec = pcall(os.time)
    local at = (okc and sec or 0) .. ':' .. tostring(now_tick())
    if HELD_MEMO and HELD_MEMO.at == at then return HELD_MEMO.ids end
    local d = state()
    local out = {}
    for uid, c in pairs(d.cells) do
        local id = tonumber(uid)
        if id and type(c) == 'table' then out[id] = true end
    end
    for uid, s in pairs(d.seen) do
        local id = tonumber(uid)
        if id and type(s) == 'table' and (s.confidence == 'strong' or s.confidence == 'certain') and not s.exempt then
            out[id] = true
        end
    end
    HELD_MEMO = {at = at, ids = out}
    return out
end

-- is unit `u` (a unit or an id) held? `ids`: a held_ids() already read (a loop)
function is_held(u, ids)
    if u == nil then return false end
    local id = u
    if type(u) ~= 'number' then
        local ok, v = pcall(function() return u.id end)
        if not ok then return false end
        id = v
    end
    return (ids or held_ids())[id] == true
end

-- (0.105.113) this file's locals the later part uses (it takes back the ones
-- it uses as locals of its own): all functions, set once here
PART_LOCALS = {U = U, assign = assign, burrow_named = burrow_named, changed = changed, citizen = citizen, count_rooms = count_rooms, dead = dead, free = free, in_zone = in_zone, larder_by_name = larder_by_name, larder_check = larder_check, larder_low = larder_low, let_out = let_out, mood_name = mood_name, name_of = name_of, need = need, now_tick = now_tick, other_in_zone = other_in_zone, resident = resident, restocking = restocking, save = save, taken_zones = taken_zones, zone_by_id = zone_by_id}

---------------------------------------------------------------------------
-- (0.105.113) The rest of the killers lives in a part beside this file
-- (ai-killers-cell.lua): the cell row's pile (larder_row, larder_remove),
-- keep_apart, cell and report. It runs in this module's own environment, so
-- its names stay reqscript('ai-killers').name for the bridge and the other
-- modules, and a test's swap (K.cell = ...) reaches it. DFHack reloads a
-- module when its own file changes: a change to the part alone is picked up
-- once ai-killers.lua is touched too, or the game restarts.
---------------------------------------------------------------------------

PARTS = {'cell'}
-- each part marks the version it came with; started afresh at each load, so
-- a part that failed to load shows as unmarked
PART_VERSIONS = {['ai-killers'] = '0.105.135'}   -- (0.105.26) bumped with BRIDGE_VERSION

local function part_path(name)
    local dir = debug.getinfo(1, 'S').source:match('^@(.*[/\\])')
    if dir then
        local f = io.open(dir .. name .. '.lua', 'r')
        if f then f:close() return dir .. name .. '.lua' end
    end
    return dfhack.findScript and dfhack.findScript(name) or nil
end

-- a test that loads this file from its text (not from a file) hands the
-- parts' texts in PART_SOURCES (tests/lua_modules_util.py); nil in the game
for _, part in ipairs(PARTS) do
    local name = 'ai-killers-' .. part
    local src = type(PART_SOURCES) == 'table' and PART_SOURCES[name] or nil
    if src then
        assert(load(src, name, 't', _ENV))()
    else
        local path = part_path(name)
        if not path then error('ai-killers: ' .. name .. '.lua is missing (it goes beside ai-killers.lua)') end
        assert(loadfile(path, 't', _ENV))()
    end
end
