-- ai-killers-cell: the cell row's pile (larder_row, larder_remove), a held
-- killer kept apart (keep_apart), the cells (cell) and the `killers` report
-- (report).
--
-- (0.105.113) A part of ai-killers (split off when it reached the size
-- limit), not a script of its own: ai-killers.lua loads it into its own
-- environment, so every name here is reqscript('ai-killers').name and the
-- names defined there are in reach.

if not PART_LOCALS then qerror('ai-killers-cell is a part of ai-killers; run ai-killers') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-killers-cell'] = '0.105.123'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, assign, burrow_named, changed, citizen, count_rooms, dead, free, in_zone, larder_by_name, larder_check, larder_low, let_out, mood_name, name_of, need, now_tick, other_in_zone, resident, restocking, save, taken_zones, zone_by_id = PART_LOCALS.U, PART_LOCALS.assign, PART_LOCALS.burrow_named, PART_LOCALS.changed, PART_LOCALS.citizen, PART_LOCALS.count_rooms, PART_LOCALS.dead, PART_LOCALS.free, PART_LOCALS.in_zone, PART_LOCALS.larder_by_name, PART_LOCALS.larder_check, PART_LOCALS.larder_low, PART_LOCALS.let_out, PART_LOCALS.mood_name, PART_LOCALS.name_of, PART_LOCALS.need, PART_LOCALS.now_tick, PART_LOCALS.other_in_zone, PART_LOCALS.resident, PART_LOCALS.restocking, PART_LOCALS.save, PART_LOCALS.taken_zones, PART_LOCALS.zone_by_id   -- (0.105.113) the hub's locals

-- the cell row's pile: pile (its id, or false), drink, food, pile_empty,
-- let_outs, stocking (the doors open for the haulers), pile_error
function larder_row(row, c, memo)
    local drink, food = larder_stock(c, memo)
    row.pile = (drink ~= nil) and tonumber(c.pile) or false
    row.drink, row.food = drink, food
    if drink ~= nil and drink + food == 0 then row.pile_empty = true end
    row.let_outs = tonumber(c.let_outs) or 0
    row.stocking = c.restock and true or nil
    -- (0.105.97, verifier) locked, empty, inside RESTOCK_GAP: the cell action
    -- can do nothing until the gap is over, so the brain doesn't ask each cycle
    local okt, t = pcall(now_tick)
    if okt and c.locked and not c.restock and c.restock_end and drink ~= nil and larder_low(c, memo)
            and t - c.restock_end < RESTOCK_GAP then
        row.restock_wait = true
    end
    -- (item 5) the fort's free meals (capped), when the pile has none: the brain
    -- waits for meals as for drink; meals_out: no meal can reach it (let out hungry)
    if drink ~= nil and food <= 0 then
        row.fort_meals = fort_meals(memo)
        row.meals_out = (okt and meals_unreachable(c, t, memo)) or nil
    end
    row.pile_error = (drink == nil and c.pile_error) or nil
    row.pile_all_food = (drink ~= nil and c.pile_all_food) or nil
    -- (0.105.98) the settings put right after it was made; found again by its name; lost
    for _, k in ipairs({'pile_fixed', 'pile_refound', 'pile_lost'}) do
        local n = tonumber(c[k])
        row[k] = (n and n > 0) and n or nil
    end
end

function larder_remove(c)
    local sp = larder_pile(c)
    if sp then pcall(dfhack.buildings.deconstruct, sp) end   -- a pile goes at once; its items stay
    -- (0.105.98) and any other pile of the cell's name (one made again after its id was lost)
    for _ = 1, 4 do
        local more = c.pile_name and larder_by_name(c.pile_name)
        if not more or more == sp then break end
        if not pcall(dfhack.buildings.deconstruct, more) then break end
        sp = more
    end
end

-- Unit `u` (in cell burrow `cell_b`) out of every other burrow, out of
-- their squad and out of any military office (as ai-threats' moon_cell's
-- unsquad does for the cursed). Nothing is kept to restore: a killer let
-- go is a civilian again, the fill and the offices find their own.
-- Returns the words of what was done, or nil.
function keep_apart(u, cell_b, dry)
    local did = {}
    pcall(function()
        local keep = cell_b and cell_b.id or nil
        local others = {}
        for _, bid in ipairs(u.burrows or {}) do
            if bid ~= keep then table.insert(others, bid) end
        end
        for _, bid in ipairs(others) do
            local okf, b = pcall(df.burrow.find, bid)
            if not okf then b = nil end
            if not b then
                for _, x in ipairs(df.global.plotinfo.burrows.list) do if x.id == bid then b = x break end end
            end
            -- a werebeast's moon cell (ai-threats) stays: it is a cell too
            if b and tostring(b.name):sub(1, #'AI moon cell ') ~= 'AI moon cell ' then
                if not dry then dfhack.burrows.setAssignedUnit(b, u, false) end
                table.insert(did, 'out of burrow ' .. tostring(b.name ~= '' and b.name or bid))
            end
        end
    end)
    local oksq, sq = pcall(function() return u.military.squad_id end)
    if oksq and type(sq) == 'number' and sq >= 0 then
        if dry then
            table.insert(did, 'out of squad ' .. sq)
        else
            -- DFHack's removeFromSquad also takes a squad leader's office link off
            local oks, done = pcall(function() return dfhack.military.removeFromSquad(u.id) end)
            table.insert(did, 'out of squad ' .. sq .. ((oks and done) and '' or ' (the game kept them in it)'))
        end
    end
    -- a militia commander or captain's post still held (one leading no squad)
    pcall(function()
        local N = reqscript('ai-nobles')
        local ent = U.fort_entity()
        local hf = df.historical_figure.find(u.hist_figure_id)
        if not (ent and hf) then return end
        for _, a in ipairs(ent.positions.assignments) do
            if a.histfig == hf.id then
                local p
                for _, pp in ipairs(ent.positions.own) do if pp.id == a.position_id then p = pp break end end
                if p and N.MILITARY_OFFICES[p.code] then
                    if not dry then
                        N.undo_appointment(a, hf, ent)
                        pcall(N.sync_held, ent, true)
                    end
                    table.insert(did, 'off the ' .. tostring(p.code):lower():gsub('_', ' '))
                end
            end
        end
    end)
    if #did == 0 then return nil end
    return name_of(u) .. ': ' .. table.concat(did, ', ')
end

-- --- the cell action ---------------------------------------------------------

function cell(o, dry)
    o = o or {}
    local d = state()
    local t = now_tick()
    local want = {}
    for _, id in ipairs(o.units or {}) do want[tostring(id)] = true end
    local out = {ok = true, placed = {}, locked = {}, waiting = {}, out = {}, released = {}, stocking = {},
                 apart = {}, dry_run = dry or nil}
    local memo = {}             -- (0.105.97) each cell's pile read once a call
    -- (0.105.114) the brain's urgent ones (a werebeast, a killing within a
    -- day): locked at once, the doors not opened for the haulers (urgent_now)
    local urg = {}
    for _, id in ipairs(o.urgent or {}) do urg[tostring(id)] = true end
    if not o.release_only then
        for uid, c in pairs(d.cells) do
            if type(c) == 'table' and not dry then c.urgent_brain = urg[uid] and t or nil end
        end
    end
    out.urgent = {}
    -- let out: those not wanted (unless only the let-outs run), the dead and
    -- gone, and the thirsty or hungry
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' then
            local u = df.unit.find(tonumber(uid))
            if not u or dead(u) or (not o.release_only and not want[uid]) then
                free(uid, c, u, dry)
                if not dry then d.cells[uid] = nil end
                table.insert(out.released, u and name_of(u) or uid)
            elseif let_out(uid, c, u, t, dry, memo) then
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
                -- (0.105.97) the cell's pile made, and a locked cell opened for the haulers when it runs low
                local why = (c and urgent_now(c, u, t)) or (urg[uid] and 'brain') or nil
                if why then table.insert(out.urgent, {name = name_of(u), why = why}) end
                local lk = z and c and larder_check(uid, c, z, t, dry, memo, u)
                if lk == 'wait' or (lk == 'open' and dry) then table.insert(out.stocking, name_of(u)) end
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
                            d.cells[uid] = {zone = z.id, kind = kind, tick = t, doors = {},
                                            urgent_brain = urg[uid] and t or nil}
                            taken[z.id] = true
                        else
                            out.error = 'the cell\'s burrow could not be made: ' .. tostring(eb):sub(1, 100)
                            z = nil
                        end
                    end
                    if z then table.insert(out.placed, name_of(u)) end
                elseif not c.locked then
                    local th, hu = need(u)
                    -- (0.105.94) back once under the levels that let them out:
                    -- the timers only fall by drinking and eating. Live 23 Nov,
                    -- B: Led Siguntat drank just after she was let out, her
                    -- thirst passed 3000 again before a cycle saw it, and she
                    -- stayed out ten days ("waiting" 60 times an hour)
                    if c.out and (th >= THIRST_OUT or hu >= HUNGER_OUT) then
                        table.insert(out.waiting, name_of(u))        -- still out to eat and drink
                    elseif c.out then
                        if not dry then assign(uid, u, true); c.out = nil end
                        table.insert(out.waiting, name_of(u))        -- back to the cell
                    elseif restocking(c, t, dry, memo, u) then
                        table.insert(out.stocking, name_of(u))       -- (0.105.97) the doors open for the haulers
                    elseif in_zone(z, u.pos.x, u.pos.y, u.pos.z) and not other_in_zone(z, u.id) then
                        for id, b in pairs(zone_doors(z)) do
                            local okf, f = pcall(function() return b.door_flags.forbidden end)
                            if okf and not f and not dry then
                                U.lock_door(b, true, 'killers') -- (0.105.47) ai-util: the walk map redone
                                table.insert(c.doors, id)
                            end
                        end
                        if not dry then c.locked = true end
                        table.insert(out.locked, name_of(u))
                    else
                        table.insert(out.waiting, name_of(u))
                    end
                end
                -- (0.105.97) a killer with a cell is in no other burrow, squad
                -- or military office (B, 23 Nov): each cycle, as other rules
                -- (or the player) may have put them back
                if z and (dry or d.cells[uid]) then
                    local okk, kept = pcall(keep_apart, u, burrow_named(CELL_PREFIX .. uid, false), dry)
                    if okk and kept then table.insert(out.apart, kept) end
                end
            end
        end
    end
    if not dry then save(d) end
    if #out.urgent == 0 then out.urgent = nil end
    local any = #out.placed + #out.locked + #out.released + #out.waiting + #out.out + #out.stocking + #out.apart
    if any == 0 and not out.error then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'every cell is as it should be'}
    end
    if out.error and #out.placed + #out.locked == 0 and #out.waiting + #out.stocking == 0 then out.ok = false end
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
    local memo = {}             -- (0.105.97) each cell's pile read once
    local seen = {}
    -- (0.105.98) each cell's pile known by its name too, and its settings put
    -- right with the report: the brain asks for the cell action only while a
    -- cell needs something (a locked, stocked cell is left alone), and the
    -- report runs each cycle
    for uid, c in pairs(d.cells) do
        if type(c) == 'table' and c.pile then
            c.pile_name = c.pile_name or (LARDER_PREFIX .. uid)
            pcall(function() larder_keep_right(c, larder_pile(c), false) end)
            pcall(function() larder_barrels(larder_pile(c)) end)   -- (item 5)
        end
    end
    local ids = {}
    for id in pairs(mem) do table.insert(ids, id) end
    table.sort(ids)
    for _, id in ipairs(ids) do
        local u = mem[id]
        local tags = curse_tags(u)
        local kind = curse_kind(u, tags)
        local k, cr = kills[id], crime[id]
        local conf = confidence(kind, k, cr)
        -- (item21) the law that beat a convict to death: a row (weak), so its office can go to a calm dwarf
        if not conf and k and (k.punished or 0) >= LAW_PUNISHED and law(u) then conf = 'weak' end
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
                row.people, row.last_ago = k.people, k.last and t - k.last
                if (k.punished or 0) > 0 then row.punished = k.punished end
            end
            if cr then row.crimes = cr end
            pcall(function() if dfhack.units.isAdult(u) == false then row.child = true end end)
            pcall(function() row.stress = dfhack.units.getStressCategory(u) end)   -- (0.105.112)
            pcall(function() if u.military.squad_id ~= -1 then row.squad_id = u.military.squad_id end end)
            if law(u) then
                row.law, row.law_codes = true, law_codes(u)
                -- (0.105.99) killings outside a lawful punishment (fights): at
                -- LAW_KILLS the office may go to a calmer dwarf (ai-nobles-swap)
                row.law_kills = k and (k.kills + k.brawls) or 0
                if row.law_kills >= LAW_KILLS and row.kind == 'killer' then row.law_killer = true end
                -- (item21) B and D, 25 Nov: four convicts strangled in DF's beatings by the guard
                if (row.punished or 0) >= LAW_PUNISHED and row.kind == 'killer' then row.law_killer = true end
            end
            s.law_killer = row.law_killer
            s.exempt = (row.child or (row.law and row.kind == 'killer')) or nil   -- (0.105.97) held_ids: never held
            pcall(function() row.x, row.y, row.z = u.pos.x, u.pos.y, u.pos.z end)
            local c = d.cells[key]
            if type(c) == 'table' then
                row.cell = {locked = c.locked or nil, out = c.out and true or nil, kind = c.kind}
                pcall(function() larder_row(row.cell, c, memo) end)     -- (0.105.97)
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
            if u and not dead(u) then
                if c.pile then pcall(larder_meal_track, c, t, memo) end      -- (item 5)
                let_out(uid, c, u, t, false, memo)
            end
            local crow = {unit_id = tonumber(uid), locked = c.locked or nil, out = c.out and true or nil,
                          kind = c.kind, days = c.tick and (t - c.tick) // DAY or nil}
            if u and not dead(u) then crow.urgent = urgent_of(u) end    -- (0.105.114) the unit's own, live
            pcall(function() larder_row(crow, c, memo) end)                 -- (0.105.97)
            table.insert(out.cells, crow)
        end
    end
    out.rooms = count_rooms(taken_zones(d))
    save(d)
    return out
end
