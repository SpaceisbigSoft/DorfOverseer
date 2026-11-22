-- ai-threats-survey: the cavern openings and whether their seal holds, the units that keep
-- the dwarves from drink, food and sleep, and survey() (the threats report).
--
-- (r8) A part of ai-threats, not a script of its own: ai-threats.lua loads it
-- into its own environment, so every name here is reqscript('ai-threats').name
-- and the names defined there are in reach.

if not PART_LOCALS then qerror('ai-threats-survey is a part of ai-threats; run ai-threats') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-threats-survey'] = '0.105.68'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, report_units, DAY, now_tick, name_of, save_state, is, outside_at, citizens, dist_to, reaches, fire_report, prisoners_report, thieves_report, undead_report, were_report, surface_report, rescue_report = PART_LOCALS.U, PART_LOCALS.report_citizens, PART_LOCALS.report_units, PART_LOCALS.DAY, PART_LOCALS.now_tick, PART_LOCALS.name_of, PART_LOCALS.save_state, PART_LOCALS.is, PART_LOCALS.outside_at, PART_LOCALS.citizens, PART_LOCALS.dist_to, PART_LOCALS.reaches, PART_LOCALS.fire_report, PART_LOCALS.prisoners_report, PART_LOCALS.thieves_report, PART_LOCALS.undead_report, PART_LOCALS.were_report, PART_LOCALS.surface_report, PART_LOCALS.rescue_report   -- (r8) the hub's and earlier parts' locals

-- --- (0.105.26) the cavern openings ------------------------------------------------
-- F lost 54 and C 12 to forgotten beasts that came in through caverns the AI
-- opened. Every opening onto a cavern the AI knows is kept in the save
-- (state.openings, by "x,y,z"): the gates scan's cavern entrances (their
-- doors and hatches, or the opening itself while it has none: the brain has
-- doors put on it), each cavern well's shaft hatch (the well's own lever
-- works it: the shaft watcher shuts it while a danger that could come up it is near),
-- and every door or hatch the seal found on the way down. The seal locks
-- them all while a forgotten beast or other great danger is about.
OPENINGS_MAX = 60

local function okey(x, y, z) return ('%d,%d,%d'):format(x, y, z) end

-- Pure-ish: one opening put on record (false when known, bad or the record is full).
function note_opening(d, x, y, z, kind, source, t)
    x, y, z = tonumber(x), tonumber(y), tonumber(z)
    if not (x and y and z) then return false end
    local k = okey(x, y, z)
    local o = d.openings[k]
    if o then
        if kind ~= 'open' and o.kind == 'open' then o.kind, o.source = kind, source end
        -- (r9, A4 26) a cavern well's shaft hatch is the well's, whatever found
        -- it first: the gates' scan can take it for a cavern entrance's hatch
        -- (it is read first), and the seal then locked every shaft hatch as a
        -- 'gate' (War-hold: all five read locked)
        if kind == 'well' and o.kind ~= 'well' then o.kind, o.source = kind, source end
        return false
    end
    local n = 0
    for _ in pairs(d.openings) do n = n + 1 end
    if n >= OPENINGS_MAX then return false end
    d.openings[k] = {x = x, y = y, z = z, kind = kind, source = source, tick = t}
    return true
end

function gather_openings(d, t)
    pcall(function()
        local G = reqscript('ai-gates')
        for _, e in ipairs(G.GATES and G.GATES.entrances or {}) do
            if e.kind == 'cavern' then
                local src = 'cavern entrance ' .. tostring(e.id)
                local doors = 0
                for _, b in ipairs(e.equipment or {}) do
                    if b.kind == 'door' or b.kind == 'hatch' then
                        note_opening(d, b.x1, b.y1, b.z, 'gate', src, t)
                        doors = doors + 1
                    end
                end
                if doors == 0 then note_opening(d, e.x, e.y, e.z, 'open', src, t) end
            end
        end
    end)
    pcall(function()
        for _, w in ipairs(reqscript('ai-builder').well_lids(false) or {}) do
            local h = w.shaft_hatch
            if type(h) == 'table' then
                note_opening(d, h.x, h.y, h.z, 'well', 'cavern well ' .. tostring(w.project_id), t)
            end
        end
    end)
    -- (0.105.47) each cavern well's door at its gallery's fort end (a hatch over
    -- its stair top in a hall): a way into the caverns the seal locks
    pcall(function()
        for _, w in ipairs(reqscript('ai-well-safety').fort_doors() or {}) do
            note_opening(d, w.x, w.y, w.z, 'gate', 'cavern well ' .. tostring(w.project_id) .. ' door', t)
        end
    end)
end

-- What stands on one opening now: {building = 'Door'|'Hatch'|other, id,
-- built, locked, closed} (nothing: no building there).
local function opening_state(o)
    local row = {}
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(o.x, o.y, o.z))
        if not b then return end
        local ty = b:getType()
        if ty == df.building_type.Door or ty == df.building_type.Hatch then
            row.building = ty == df.building_type.Door and 'Door' or 'Hatch'
            row.id = b.id
            pcall(function() row.built = b:getBuildStage() >= b:getMaxBuildStage() end)
            pcall(function() row.locked = b.door_flags.forbidden == true end)
            pcall(function() row.closed = b.door_flags.closed == true end)
        else
            row.building = tostring(df.building_type[ty] or ty)
        end
    end)
    return row
end

-- (r2h7) THE one test of "can the seal lock this opening", used by the
-- openings report (the brain counts only rows it marks lockable) and by
-- seal_cavern itself, so the two can't disagree again (R3: the planner
-- counted the cavern well's door and hatch, the bridge refused them 24 of 24
-- times). o: an opening on record ({x, y, z, kind, source}); row: its
-- opening_state (read here when nil). Returns lockable (bool), why (the
-- reason it isn't: a string), blocked (a dwarf beyond it: a name; the
-- seal waits for them rather than gives up) and the reason's code ('shaft',
-- 'none', 'blocked', 'skip').
--   * a cavern well's shaft hatch (kind 'well') never: its watcher and
--     lever work it (the bucket needs it open unless a danger is near);
--   * nothing but a door or hatch is lockable (a wall, an empty tile);
--   * a cavern well's door with a dwarf beyond it (door_blocked), or whose
--     well's shaft gate keeps the cavern out (door_seal_skip): left open.
function seal_lockable(o, row)
    if type(o) ~= 'table' then return false, 'not an opening' end
    if o.kind == 'well' then
        return false, 'a cavern well\'s shaft hatch: its own watcher shuts it when a danger comes near', nil, 'shaft'
    end
    row = row or opening_state(o)
    if row.building ~= 'Door' and row.building ~= 'Hatch' then
        return false, row.building and ('a ' .. tostring(row.building) .. ', not a door or hatch') or 'no door or hatch there',
            nil, 'none'
    end
    if type(o.source) == 'string' and o.source:find('^cavern well') then
        local okw, W = pcall(reqscript, 'ai-well-safety')
        if okw and W then
            local okb, who = pcall(function() return W.door_blocked(o) end)
            if okb and who then
                local name = tostring(who)
                return false, name .. ' is beyond the cavern well\'s door', name, 'blocked'
            end
            local oks, why = pcall(W.door_seal_skip, o)
            if oks and type(why) == 'string' then return false, why, nil, 'skip' end
        end
    end
    return true
end

-- (0.105.26 seal fix) What the seal holds, from its record: {ids = {building
-- id = true} (locked by it, or shut by their lever), locked = {id = true}
-- (the lock), pulled = {id = true} (shut by their lever), levers = {lever id
-- = true}}. The gate watcher (ai-gates) opens none of these while it stands.
function seal_holds(d)
    d = d or load_state()
    local out = {ids = {}, locked = {}, pulled = {}, levers = {}}
    for _, rec in pairs(d.sealed) do
        if type(rec) == 'table' then
            for _, id in ipairs(type(rec.ids) == 'table' and rec.ids or {}) do
                id = tonumber(id) or id
                out.ids[id], out.locked[id] = true, true
            end
            for sid, lever in pairs(type(rec.pulled) == 'table' and rec.pulled or {}) do
                local id = tonumber(sid) or sid
                out.ids[id], out.pulled[id] = true, true
                if lever ~= nil then out.levers[tonumber(lever) or lever] = true end
            end
        end
    end
    return out
end

-- (0.105.26 seal fix) The doors, hatches and bridges of the entrances the
-- gate watcher holds shut now: {building id = true}. The seal's open path
-- leaves these shut (the watcher opens them again when its danger is gone).
local function watcher_held()
    local out = {}
    pcall(function()
        local G = reqscript('ai-gates').GATES
        if type(G) ~= 'table' or type(G.closed) ~= 'table' then return end
        for _, e in ipairs(G.entrances or {}) do
            if G.closed[e.id] then
                for _, list in ipairs({e.equipment or {}, e.outer or {}}) do
                    for _, g in ipairs(list) do if g.id ~= nil then out[g.id] = true end end
                end
            end
        end
    end)
    return out
end

-- (0.105.45) The seal doors a lure holds open now (lua/ai-lure.lua): {id = true}.
-- The seal leaves these unlocked while the lure is open (it locks them again).
local function lure_open_ids()
    local ok, ids = pcall(function() return reqscript('ai-lure').held_open() end)
    return ok and type(ids) == 'table' and ids or {}
end

-- {list = [{x, y, z, kind, source, building?, id?, built?, locked?, closed?,
-- sealed? (the seal locked it, or shut it by its lever, and (0.105.26 seal
-- fix) it is locked, or shut, now: one opened again since reads unsealed,
-- so the brain seals it again)}], n}
function openings_report(d, t, txt)
    gather_openings(d, t)
    local held = seal_holds(d)   -- the doors and hatches the seal locked or shut by their lever
    local list = {}
    local lure = lure_open_ids()   -- (0.105.45)
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.x and o.y and o.z then
            local row = opening_state(o)
            if row.id and ((held.locked[row.id] and row.locked) or (held.pulled[row.id] and row.closed)) then
                row.sealed = true
            end
            if row.id and lure[row.id] then row.lure_open = true end     -- (0.105.45) open on purpose
            -- (0.105.51) a cavern well's door the seal leaves open (seal_cavern asks the
            -- same): its shaft gate keeps the cavern out, or a dwarf is beyond it. R3:
            -- the planner counted "1 door on record, 1 open" and the seal was refused
            -- "no door or hatch on the way down to lock" (A 12, B 9, C 7, E 7 times)
            -- (r2h7) the seal's own test (seal_lockable): the brain counts these rows only
            local okl, can, why, blocked, code = pcall(seal_lockable, o, row)
            row.lockable = (okl and can) and true or false
            if okl and code == 'blocked' then row.well_blocked = tostring(blocked):sub(1, 60)
            elseif okl and code == 'skip' then row.seal_skip = tostring(why):sub(1, 120) end
            row.x, row.y, row.z, row.kind, row.source = o.x, o.y, o.z, o.kind, o.source
            table.insert(list, row)
        end
    end
    table.sort(list, function(a, b)
        if a.z ~= b.z then return a.z < b.z end
        if a.y ~= b.y then return a.y < b.y end
        return a.x < b.x
    end)
    return {list = list, n = #list}
end

-- (0.105.51) The cavern layers' map features: {[global feature index] =
-- true} (world.features.map_features' subterranean layers, as the bridge's
-- get_layers reads them), or nil when they can't be read.
function cavern_gids()
    local ok, out = pcall(function()
        local feats = df.global.world.features
        local t, n = {}, 0
        for i, f in ipairs(feats.map_features) do
            if df.feature_init_subterranean_from_layerst:is_instance(f) then
                t[feats.feature_global_idx[i]] = true
                n = n + 1
            end
        end
        return n > 0 and t or nil
    end)
    return ok and out or nil
end

-- (0.105.51) Is this a cavern tile: a feature tile (global or local) whose
-- block belongs to a cavern layer. R3 (15 Nov, A B C E F): fisherdwarves and
-- others at the surface's river (elevation 32, a local feature's tiles, 90
-- levels above Cavern1) read as "down in the caverns", and the alarm went up
-- each time a forgotten beast was in Cavern1. gids: cavern_gids() (nil: the
-- feature flags alone, as before).
function on_cavern_tile(x, y, z, gids)
    local des = dfhack.maps.getTileFlags(x, y, z)
    if not (des and (des.feature_global or des.feature_local)) then return false end
    if not gids then return true end
    local okb, gid = pcall(function()
        local b = dfhack.maps.getTileBlock(x, y, z)
        return b and b.global_feature
    end)
    if not okb or type(gid) ~= 'number' then return true end     -- unknown: counted, to be safe
    return gids[gid] == true
end

-- (0.105.26) Citizens down in a cavern (on a cavern tile): the seal waits for them.
function cavern_citizens(txt)
    local out = {list = {}, n = 0}
    local gids = cavern_gids()
    for _, u in ipairs(report_citizens(true)) do
        local ok, cave = pcall(on_cavern_tile, u.pos.x, u.pos.y, u.pos.z, gids)
        if ok and cave then
            out.n = out.n + 1
            if #out.list < 10 then
                table.insert(out.list, {id = u.id, name = name_of(u, txt), x = u.pos.x, y = u.pos.y, z = u.pos.z})
            end
        end
    end
    return out
end

-- --- who keeps the dwarves from drink and food ------------------------------------
--
-- (item1, 14 Nov) B, 13 Nov 17:05-17:45 (y259 Obsidian - y260 Slate): 66 of
-- 77 citizens died of thirst with 845 drinks in store. DF's gamelog: from the
-- squad's fight with a crossbow thief on, "X cancels Drink: Interrupted by a
-- human spearman." ~4900 times (Eat and Sleep too) for two game months. The
-- spearman (Om Konlihiñer, a visitor told of an artifact by a citizen,
-- beaten in that fight, "I must withdraw!") stayed inside the fort near the
-- stores; DF made every dwarf who saw him on the way to a drink drop it, but
-- he was no invader and not isDanger, so the AI counted no threat, lowered
-- the alarm, opened the gates and sent nobody. The report's job
-- cancellations name who interrupts; this reads them, finds that unit (its
-- race and profession, nearest the cancelling dwarves) and says so: the
-- planner sends a squad at it and kill_target_ok (ai-military) takes it as
-- a target. The other reasons for a cancelled Drink or Eat are counted too,
-- so a parched fort says why.

INTERRUPT_WINDOW = 2 * DAY   -- job cancellations this recent are read
INTERRUPT_MAX_REPORTS = 4000 -- newest reports walked at most
INTERRUPT_NEAR = 20          -- a cancelling dwarf this close (tiles; levels count 3) to the unit
INTERRUPT_MIN = 6            -- this many Drink/Eat/Sleep cancellations by it in the window...
INTERRUPT_MIN_DWARVES = 2    -- ...by this many dwarves, with it near...
INTERRUPT_MIN_NEAR = 3       -- ...at least this many of them: the unit blocks the dwarves
local NEEDS_JOBS = {Drink = 'drink', Eat = 'eat', Sleep = 'sleep'}

-- "Name, Profession cancels Drink: Interrupted by a human spearman." -> name, job, reason
function parse_cancel(text)
    if type(text) ~= 'string' then return nil end
    local who, job, why = text:match('^(.-) cancels ([^:]+): (.-)%.?%s*$')
    if not who or who == '' then return nil end
    return who, job, why
end

-- "Interrupted by a human spearman" -> "human spearman" (nil for other reasons)
function interrupter_of(why)
    if type(why) ~= 'string' then return nil end
    local who = why:match('^Interrupted by (.+)$')
    if not who then return nil end
    who = who:lower():gsub('^an? ', ''):gsub('^the ', ''):gsub('%s+$', '')
    if who == '' or who == 'combat' then return nil end
    return who
end

-- the phrases DF may call a unit by in "Interrupted by a ...": its profession,
-- its race and profession, its race (an animal), each lower case
function unit_phrases(race, prof)
    local out = {}
    race = type(race) == 'string' and race:lower() or nil
    prof = type(prof) == 'string' and prof:lower() or nil
    if prof and prof ~= '' then table.insert(out, prof) end
    if race and race ~= '' and prof and prof ~= '' then table.insert(out, race .. ' ' .. prof) end
    if race and race ~= '' then table.insert(out, race) end
    return out
end

-- rows {text, tick, x, y, z, n}: the cancellations within the window, by who
-- interrupted ({n, drink, eat, sleep, other, dwarves, spots}) and the reasons
-- for cancelled Drink and Eat jobs ({Drink = {reason = n}})
function tally_cancels(rows, now, window)
    local out = {by_who = {}, reasons = {Drink = {}, Eat = {}}, n = 0}
    for _, r in ipairs(rows or {}) do
        if type(r) == 'table' and (not now or not r.tick or now - r.tick <= window) then
            local name, job, why = parse_cancel(r.text)
            if name then
                local k = tonumber(r.n) or 1
                out.n = out.n + k
                if out.reasons[job] then
                    local short = tostring(why):sub(1, 60)
                    out.reasons[job][short] = (out.reasons[job][short] or 0) + k
                end
                local who = interrupter_of(why)
                if who then
                    local w = out.by_who[who]
                    if not w then
                        w = {n = 0, drink = 0, eat = 0, sleep = 0, other = 0, dwarves = 0, names = {}, spots = {}}
                        out.by_who[who] = w
                    end
                    w.n = w.n + k
                    local kind = NEEDS_JOBS[job] or 'other'
                    w[kind] = w[kind] + k
                    if not w.names[name] then w.names[name] = true; w.dwarves = w.dwarves + 1 end
                    if r.x and r.y and r.z and #w.spots < 200 then
                        table.insert(w.spots, {x = r.x, y = r.y, z = r.z, n = k, needs = NEEDS_JOBS[job] ~= nil})
                    end
                end
            end
        end
    end
    return out
end

-- the units that keep the dwarves from their needs: cands {id, phrases, x, y, z};
-- a phrase's units are ranked by the cancellations near them (several human
-- spearmen visit: only the one by the dwarves counts; with no places in the
-- reports, the one with most citizens `cit` {x, y, z} about it). Returns {id = row}
function blocking_units(tally, cands, cfg, cit)
    cfg = cfg or {}
    local near_r = cfg.near or INTERRUPT_NEAR
    local min_n, min_d = cfg.min or INTERRUPT_MIN, cfg.min_dwarves or INTERRUPT_MIN_DWARVES
    local min_near = cfg.min_near or INTERRUPT_MIN_NEAR
    local out = {}
    for who, w in pairs(tally and tally.by_who or {}) do
        local needs = (w.drink or 0) + (w.eat or 0) + (w.sleep or 0)
        if needs >= min_n and (w.dwarves or 0) >= min_d then
            local matched = {}
            for _, c in ipairs(cands or {}) do
                for _, p in ipairs(c.phrases or {}) do
                    if p == who then table.insert(matched, c) break end
                end
            end
            local function close(a, b)
                return math.max(math.abs(a.x - b.x), math.abs(a.y - b.y)) + 3 * math.abs(a.z - b.z) <= near_r
            end
            local placed = 0
            for _, sp in ipairs(w.spots or {}) do if sp.needs then placed = placed + 1 end end
            local best, best_n = nil, -1
            for _, c in ipairs(matched) do
                local near = 0
                if placed > 0 then
                    for _, sp in ipairs(w.spots) do
                        if sp.needs and close(sp, c) then near = near + (sp.n or 1) end
                    end
                else
                    -- no places in the reports: the citizens about it now
                    for _, p in ipairs(cit or {}) do if close(p, c) then near = near + 1 end end
                end
                if placed > 0 and near >= min_near then
                    out[c.id] = {id = c.id, who = who, near = near, cancels = needs, drink = w.drink, eat = w.eat,
                                 sleep = w.sleep, dwarves = w.dwarves}
                elseif placed == 0 and near > best_n then
                    best, best_n = c, near
                end
            end
            -- no places: one alone by that name, else the one with the most dwarves about it
            if best and (#matched == 1 or best_n >= min_near) then
                out[best.id] = {id = best.id, who = who, near = best_n, cancels = needs, drink = w.drink,
                                eat = w.eat, sleep = w.sleep, dwarves = w.dwarves}
            end
        end
    end
    return out
end

-- the game's job cancellations of the last window (world.status.reports, newest first)
local function read_cancels(now, window)
    local rows = {}
    pcall(function()
        local reps = df.global.world.status.reports
        local seen, tail = 0, nil
        for i = #reps - 1, 0, -1 do
            seen = seen + 1
            if seen > INTERRUPT_MAX_REPORTS then break end
            local r = reps[i]
            local okt, t = pcall(function() return U.abs_tick(r.year, r.time) end)
            if okt and t and now - t > window then break end
            local text = tostring(r.text)
            -- a long line goes on in the next report(s) (flags.continuation): read backwards, put together
            local cont = false
            pcall(function() cont = r.flags.continuation and true or false end)
            if cont then
                tail = tail and (text .. ' ' .. tail) or text
                text = nil
            elseif tail then
                text, tail = text .. ' ' .. tail, nil
            end
            if text and text:find(' cancels ', 1, true) then
                local row = {text = text, tick = okt and t or nil, n = 1}
                pcall(function() row.n = 1 + math.max(0, math.tointeger(r.repeat_count) or 0) end)
                pcall(function()
                    if r.pos.x >= 0 then row.x, row.y, row.z = r.pos.x, r.pos.y, r.pos.z end
                end)
                table.insert(rows, row)
            end
        end
    end)
    return rows
end

-- (0.105.46, I2) the cancellations of the last `window` ticks, newest first
-- ({text, tick, n, x, y, z}): lua/ai-thirst.lua reads each dwarf's last
-- cancelled Drink job from them
function cancel_rows(window)
    return read_cancels(now_tick(), window or INTERRUPT_WINDOW)
end

local function race_name(u)
    local ok, n = pcall(function() return df.global.world.raws.creatures.all[u.race].name[0] end)
    return ok and n or nil
end

local function prof_name(u)
    local ok, n = pcall(dfhack.units.getProfessionName, u)
    return ok and n or nil
end

INTERRUPT_MEMO = nil         -- {tick, blocking = {id = row}, tally}

-- the blocking units now ({id = row}) and the tally, read once a game tick
function interrupt_read()
    local now = now_tick()
    local m = INTERRUPT_MEMO
    if m and m.tick == now then return m end
    local tally = tally_cancels(read_cancels(now, INTERRUPT_WINDOW), now, INTERRUPT_WINDOW)
    local cands, cit = {}, {}
    if next(tally.by_who) then
        for _, u in ipairs(report_citizens(true)) do
            table.insert(cit, {x = u.pos.x, y = u.pos.y, z = u.pos.z})
        end
        for _, u in ipairs(report_units()) do
            if dfhack.units.isActive(u) and not dfhack.units.isDead(u) and not is(dfhack.units.isCitizen, u) then
                table.insert(cands, {id = u.id, x = u.pos.x, y = u.pos.y, z = u.pos.z,
                                     phrases = unit_phrases(race_name(u), prof_name(u))})
            end
        end
    end
    m = {tick = now, tally = tally, blocking = blocking_units(tally, cands, nil, cit)}
    INTERRUPT_MEMO = m
    return m
end

-- (item1) a unit DF's own reports show keeping the dwarves from drink, food or sleep
function interrupting(u)
    local ok, m = pcall(interrupt_read)
    return ok and m and u and m.blocking[u.id] ~= nil or false
end

-- the report's part: who blocks the dwarves (each unit with what DF says of
-- it), the top interrupters, and why Drink and Eat jobs were cancelled
function interrupters_report(cit, groups, txt)
    local m = interrupt_read()
    local out = {window_days = INTERRUPT_WINDOW // DAY, cancels = m.tally.n, list = {}, by_who = {}, reasons = {}}
    for who, w in pairs(m.tally.by_who) do
        table.insert(out.by_who, {who = who, n = w.n, drink = w.drink, eat = w.eat, sleep = w.sleep,
                                  dwarves = w.dwarves})
    end
    table.sort(out.by_who, function(a, b) return a.n > b.n end)
    while #out.by_who > 5 do table.remove(out.by_who) end
    for job, rs in pairs(m.tally.reasons) do
        local l = {}
        for why, n in pairs(rs) do table.insert(l, {why = why, n = n}) end
        table.sort(l, function(a, b) return a.n > b.n end)
        while #l > 3 do table.remove(l) end
        if #l > 0 then out.reasons[job:lower()] = l end
    end
    local mil
    pcall(function() mil = reqscript('ai-military') end)
    for id, row in pairs(m.blocking) do
        local u = df.unit.find(id)
        if u and not dfhack.units.isDead(u) and #out.list < 10 then
            local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            local r = {id = id, name = name_of(u, txt), who = row.who, cancels = row.cancels, drink = row.drink,
                       eat = row.eat, sleep = row.sleep, dwarves = row.dwarves, near = row.near, pos = pos,
                       inside = not outside_at(pos.x, pos.y, pos.z), can_reach_dwarves = reaches(pos, groups),
                       distance = dist_to(pos, cit),
                       caged = (u.flags1.caged or u.flags1.chained) or nil,
                       visitor = is(dfhack.units.isVisitor, u) or nil,
                       merchant = is(dfhack.units.isMerchant, u) or nil,
                       diplomat = is(dfhack.units.isDiplomat, u) or nil,
                       invader = is(dfhack.units.isInvader, u) or nil,
                       danger = is(dfhack.units.isDanger, u) or nil}
            if mil and mil.kill_target_ok then
                local okk, yes = pcall(mil.kill_target_ok, u)
                r.kill_ok = okk and yes or false
            end
            table.insert(out.list, r)
        end
    end
    table.sort(out.list, function(a, b) return (a.cancels or 0) > (b.cancels or 0) end)
    return out
end

function survey(txt)
    local d = load_state()
    local t = now_tick()
    local cit, groups = citizens()
    local out = {}
    -- (0.105.46, I6) each part's time (os.clock ms, those over 5) in _ms: the run
    -- check had threats at 165 ms median with no word of which part
    local ms = {}
    local function part(name, fn, ...)
        local t0 = os.clock()
        local ok, v = pcall(fn, ...)
        out[name] = ok and v or {error = tostring(v):sub(1, 160)}
        local dt = math.floor((os.clock() - t0) * 1000 + 0.5)
        if dt >= 5 then ms[name] = dt end
    end
    part('fire', fire_report, d, cit)
    part('prisoners', prisoners_report, txt)
    part('thieves', thieves_report, d, t, cit, groups, txt)
    part('undead', undead_report, cit, groups, txt)
    -- (fix41) the evil weather is its own section (weather_section), read in the pulse too
    part('were', were_report, d, t, txt)
    part('surface', surface_report, cit, txt)
    part('rescue', rescue_report)
    part('openings', openings_report, d, t, txt)          -- (0.105.26)
    part('cavern_citizens', cavern_citizens, txt)         -- (0.105.26)
    part('interrupters', interrupters_report, cit, groups, txt)   -- (item1) who keeps them from drink
    out.sealed = {}
    for layer, s in pairs(d.sealed) do
        if type(s) == 'table' then
            out.sealed[layer] = {doors = #(s.ids or {}), days = s.tick and (t - s.tick) // DAY or nil}
        end
    end
    save_state(d)
    if next(ms) then out._ms = ms end
    return out
end

-- (r8) this part's locals the next part uses
PART_LOCALS.okey, PART_LOCALS.watcher_held, PART_LOCALS.lure_open_ids = okey, watcher_held, lure_open_ids
