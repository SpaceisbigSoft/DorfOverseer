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
--     a werebeast also by unit.enemy.were_race, and changed now when
--     unit.enemy.normal_race differs from its race;
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
--                   cells = [{unit_id, locked, out, kind, days}],
--                   rooms (free jail zones and bedrooms), scanned}
--   cell(o, dry)    o.units: the ids to lock away (each in a burrow on a
--                   jail zone, else a free bedroom; the room's doors locked
--                   once they are inside); every cell not listed let out;
--                   o.release_only: only the let-outs (the AI halted). A
--                   dwarf locked in who grows thirsty or hungry is let out
--                   to eat and drink (doors open, out of the burrow) and
--                   taken back once fed. {ok, placed, locked, waiting, out,
--                   released}
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/killers'
CELL_PREFIX = 'AI killer cell '
DAY = 1200
WINDOW_TICKS = 403200      -- killings looked for a year back
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

-- --- helpers ---------------------------------------------------------------

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function txt(s)
    if s == nil then return nil end
    local ok, v = pcall(dfhack.df2utf, s)
    return ok and v or s
end

local function name_of(u)
    local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
    return ok and txt(n) or ('unit ' .. tostring(u.id))
end

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

local function enum_name(enum, v)
    local ok, n = pcall(function() return enum[v] end)
    if ok and n ~= nil then return tostring(n) end
    return tostring(v)
end

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
    local okw, were = pcall(function() return u.enemy.were_race ~= -1 end)
    if is(dfhack.units.isNightCreature, u) or tags.CRAZED or (okw and were) or changed(u) then
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

-- The killings of the fort's own by a living member, newest first:
-- {killer_id = {kills, brawls, lawful, victims = {names}, causes = {CAUSE = n}, drained}}
function killings(mem, now)
    local by = {}
    local scanned, old = 0, 0
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
            if type(y) == 'number' and y >= 0 and now - U.abs_tick(y, t or 0) > WINDOW_TICKS then
                old = old + 1
                return
            end
            old = 0
            local cause = inc.death_cause
            if type(cause) ~= 'number' or cause < 0 then return end
            local kid, vid = inc.criminal, inc.victim
            if not mem[kid] or kid == vid then return end
            local v = df.unit.find(vid)
            if not v or not own(v) then return end
            local row = by[kid] or {kills = 0, brawls = 0, lawful = 0, victims = {}, causes = {}}
            by[kid] = row
            local conflict = nil
            pcall(function() conflict = enum_name(df.conflict_level, inc.conflict_level) end)
            if mood_name(v) == 'Berserk' or changed(v) or is(dfhack.units.isBloodsucker, v)
                    or LAWFUL_CONFLICT[conflict] then
                row.lawful = row.lawful + 1
                return
            end
            local cname = enum_name(df.death_type, cause)
            row.causes[cname] = (row.causes[cname] or 0) + 1
            if cname:find('DRAIN') then row.drained = true end
            if BRAWL_CONFLICT[conflict] then row.brawls = row.brawls + 1 else row.kills = row.kills + 1 end
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

local function save(d) pcall(U.site_put, SITE_KEY, d) end

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
            if b then b.door_flags.forbidden = locked end
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
-- burrow); returns true when let out now
local function let_out(uid, c, u, t, dry)
    if not c.locked or not u then return false end
    local th, hu = need(u)
    if th < THIRST_OUT and hu < HUNGER_OUT then return false end
    if not dry then
        set_doors(c, false)
        assign(uid, u, false)
        c.locked, c.doors, c.out = false, {}, t
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
end

-- --- the cell action ---------------------------------------------------------

function cell(o, dry)
    o = o or {}
    local d = state()
    local t = now_tick()
    local want = {}
    for _, id in ipairs(o.units or {}) do want[tostring(id)] = true end
    local out = {ok = true, placed = {}, locked = {}, waiting = {}, out = {}, released = {}, dry_run = dry or nil}
    -- let out: those not wanted (unless only the let-outs run), the dead and
    -- gone, and the thirsty or hungry
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' then
            local u = df.unit.find(tonumber(uid))
            if not u or dead(u) or (not o.release_only and not want[uid]) then
                free(uid, c, u, dry)
                if not dry then d.cells[uid] = nil end
                table.insert(out.released, u and name_of(u) or uid)
            elseif let_out(uid, c, u, t, dry) then
                table.insert(out.out, name_of(u))
            end
        end
    end
    if not o.release_only then
        local taken = taken_zones(d)
        for uid in pairs(want) do
            local u = df.unit.find(tonumber(uid))
            if u and not dead(u) then
                local c = d.cells[uid]
                local z = c and c.zone and zone_by_id(c.zone)
                if not z then
                    local kind
                    z, kind = cell_room(u.pos, taken)
                    if not z then
                        out.error = 'no jail zone or free bedroom for a cell'
                    elseif not dry then
                        local okb, eb = pcall(function()
                            local b = burrow_named(CELL_PREFIX .. uid, true)
                            dfhack.burrows.clearTiles(b)
                            for y = z.y1, z.y2 do
                                for x = z.x1, z.x2 do
                                    if in_zone(z, x, y, z.z) then dfhack.burrows.setAssignedTile(b, xyz2pos(x, y, z.z), true) end
                                end
                            end
                            dfhack.burrows.setAssignedUnit(b, u, true)
                        end)
                        if okb then
                            d.cells[uid] = {zone = z.id, kind = kind, tick = t, doors = {}}
                            taken[z.id] = true
                        else
                            out.error = 'the cell\'s burrow could not be made: ' .. tostring(eb):sub(1, 100)
                            z = nil
                        end
                    end
                    if z then table.insert(out.placed, name_of(u)) end
                elseif not c.locked then
                    local th, hu = need(u)
                    if c.out and (th > THIRST_BACK or hu > HUNGER_BACK) then
                        table.insert(out.waiting, name_of(u))        -- still out to eat and drink
                    elseif c.out then
                        if not dry then assign(uid, u, true); c.out = nil end
                        table.insert(out.waiting, name_of(u))        -- back to the cell
                    elseif in_zone(z, u.pos.x, u.pos.y, u.pos.z) and not other_in_zone(z, u.id) then
                        for id, b in pairs(zone_doors(z)) do
                            local okf, f = pcall(function() return b.door_flags.forbidden end)
                            if okf and not f and not dry then
                                b.door_flags.forbidden = true
                                table.insert(c.doors, id)
                            end
                        end
                        if not dry then c.locked = true end
                        table.insert(out.locked, name_of(u))
                    else
                        table.insert(out.waiting, name_of(u))
                    end
                end
            end
        end
    end
    if not dry then save(d) end
    local any = #out.placed + #out.locked + #out.released + #out.waiting + #out.out
    if any == 0 and not out.error then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'every cell is as it should be'}
    end
    if out.error and #out.placed + #out.locked == 0 and #out.waiting == 0 then out.ok = false end
    return out
end

-- --- the report --------------------------------------------------------------

function report()
    local t = now_tick()
    local d = state()
    local mem = members()
    local kills, scanned = killings(mem, t)
    local crime = crimes(mem)
    local out = {list = {}, cells = {}, scanned = scanned}
    local seen = {}
    local ids = {}
    for id in pairs(mem) do table.insert(ids, id) end
    table.sort(ids)
    for _, id in ipairs(ids) do
        local u = mem[id]
        local tags = curse_tags(u)
        local kind = curse_kind(u, tags)
        local k, cr = kills[id], crime[id]
        local conf = confidence(kind, k, cr)
        if conf then
            local key = tostring(id)
            local s = type(d.seen[key]) == 'table' and d.seen[key] or {tick = t}
            s.confidence = conf
            seen[key] = s
            local tl = {}
            for tag in pairs(tags) do table.insert(tl, tag) end
            table.sort(tl)
            local row = {id = id, name = name_of(u), kind = kind or 'killer', confidence = conf,
                         citizen = citizen(u) or nil, resident = (not citizen(u) and resident(u)) or nil,
                         tags = #tl > 0 and tl or nil, seen_ticks = t - (tonumber(s.tick) or t),
                         berserk = mood_name(u) == 'Berserk' or nil, changed = changed(u) or nil}
            if k then
                row.kills, row.brawls, row.lawful, row.drained = k.kills, k.brawls, k.lawful, k.drained or nil
                row.victims, row.causes = k.victims, k.causes
            end
            if cr then row.crimes = cr end
            pcall(function() if dfhack.units.isAdult(u) == false then row.child = true end end)
            pcall(function() if u.military.squad_id ~= -1 then row.squad_id = u.military.squad_id end end)
            if law(u) then row.law = true end
            pcall(function() row.x, row.y, row.z = u.pos.x, u.pos.y, u.pos.z end)
            local c = d.cells[key]
            if type(c) == 'table' then
                row.cell = {locked = c.locked or nil, out = c.out and true or nil, kind = c.kind}
            end
            table.insert(out.list, row)
        end
    end
    -- the surest first (a vampire never pushed off the list by brawlers), then the most killings
    local RANK = {certain = 0, strong = 1, weak = 2}
    table.sort(out.list, function(a, b)
        if RANK[a.confidence] ~= RANK[b.confidence] then return RANK[a.confidence] < RANK[b.confidence] end
        if (a.kills or 0) ~= (b.kills or 0) then return (a.kills or 0) > (b.kills or 0) end
        return a.id < b.id
    end)
    out.total = #out.list
    while #out.list > MAX_ROWS do table.remove(out.list) end
    d.seen = seen          -- the ones no longer suspected are forgotten
    -- the let-outs run with the report too (a halted brain never shuts a dwarf in to die)
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' then
            local u = df.unit.find(tonumber(uid))
            if u and not dead(u) then let_out(uid, c, u, t, false) end
            table.insert(out.cells, {unit_id = tonumber(uid), locked = c.locked or nil, out = c.out and true or nil,
                                     kind = c.kind, days = c.tick and (t - c.tick) // DAY or nil})
        end
    end
    out.rooms = count_rooms(taken_zones(d))
    save(d)
    return out
end
