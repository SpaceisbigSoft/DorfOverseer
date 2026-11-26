-- ai-threats-seal: seal_cavern (a cavern's openings walled or opened by
-- lever) and the creatures that breathe fire (fire_breath_of,
-- mark_fire_breathers).
--
-- (0.105.119) A part of ai-threats (split off ai-threats-actions when it
-- reached the size limit), not a script of its own: ai-threats.lua loads it
-- into its own environment, right after ai-threats-actions, so every name
-- here is reqscript('ai-threats').name and the names defined there are in
-- reach.

if not PART_LOCALS then qerror('ai-threats-seal is a part of ai-threats; run ai-threats') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-threats-seal'] = '0.105.119'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, report_citizens, now_tick, name_of, save_state, okey, watcher_held, lure_open_ids, insane_held = PART_LOCALS.U, PART_LOCALS.report_citizens, PART_LOCALS.now_tick, PART_LOCALS.name_of, PART_LOCALS.save_state, PART_LOCALS.okey, PART_LOCALS.watcher_held, PART_LOCALS.lure_open_ids, PART_LOCALS.insane_held   -- (0.105.119) the hub's and earlier parts' locals

-- (0.105.0 review) a citizen down in the cavern (on a cavern tile between
-- its levels, z1..z2): the seal would shut them out on the far side
local function citizen_in_cavern(z1, z2)
    if not z1 or not z2 then return nil end
    local lo, hi = math.min(z1, z2), math.max(z1, z2)
    local gids = cavern_gids()          -- (0.105.51) a cavern layer's tile, not the surface river's
    local ok, who = pcall(function()
        for _, u in ipairs(report_citizens(true)) do
            local p = u.pos
            if p.z >= lo and p.z <= hi then
                if on_cavern_tile(p.x, p.y, p.z, gids) then return u end
            end
        end
    end)
    return ok and who or nil
end

-- The caverns sealed: the doors and hatches on the given tiles (the way
-- down to the cavern: where the fort's ground meets it, the stair column)
-- locked; open: unlocked (only those the AI locked). (0.105.0 review) only
-- on those very tiles (no longer every door within a tile of them), and
-- refused while a citizen is down in the cavern (z1..z2: its levels).
-- (0.105.26) openings: every opening on record too (state.openings), but
-- never a cavern well's shaft hatch (its lever and the shaft watcher work
-- it, and the bucket needs it open whenever no great beast is about); a
-- door or hatch on a lever is shut by that lever (a lock does nothing to
-- it) when the lever works nothing else, and opened by it again after. The
-- doors and hatches found are put on record as openings. Said in the game.
local function announce(text, color)
    pcall(function() dfhack.gui.showAnnouncement('AI Overseer: ' .. text, color or COLOR_YELLOW, true) end)
end

-- a lever that works this building and nothing else, or nil
local function own_lever(bid)
    local ok, lid = pcall(function()
        local G = reqscript('ai-gates')
        local links = G.lever_links()
        for _, l in ipairs(links[bid] or {}) do
            local targets = G.lever_targets(links, l)
            if #targets == 1 and targets[1] == bid then return l end
        end
    end)
    return ok and lid or nil
end

function seal_cavern(layer, tiles, open, dry_run, z1, z2, openings)
    local d = load_state()
    local t = now_tick()
    local rec = type(d.sealed[layer]) == 'table' and d.sealed[layer] or nil
    if open then
        if not rec then return {ok = false, rejected = true, nothing_to_do = true, error = 'the AI sealed nothing there'} end
        -- (0.105.26 seal fix) an entrance the gate watcher holds shut (an
        -- ordinary danger at it) is left shut: the watcher opens it later
        local watched = watcher_held()
        local n, kept = 0, 0
        for _, bid in ipairs(rec.ids or {}) do
            pcall(function()
                local b = df.building.find(bid)
                if b and watched[b.id] then
                    kept = kept + 1
                elseif b then
                    if not dry_run then U.lock_door(b, false, 'seal') end -- (0.105.47) ai-util: the walk map redone
                    n = n + 1
                end
            end)
        end
        for sid, lever in pairs(type(rec.pulled) == 'table' and rec.pulled or {}) do
            pcall(function()
                local b = df.building.find(tonumber(sid))
                if b and watched[b.id] then
                    kept = kept + 1
                elseif b and b.door_flags.closed then
                    if not dry_run then reqscript('ai-gates').pull_instant(lever) end
                    n = n + 1
                end
            end)
        end
        if not dry_run then
            d.sealed[layer] = nil
            save_state(d)
            announce(('the ways into the caverns opened again (%s): no great beast left'):format(tostring(layer)),
                     COLOR_GREEN)
        end
        return {ok = true, unlocked = n, layer = layer, watcher_kept = kept > 0 and kept or nil, dry_run = dry_run or nil}
    end
    local inside = citizen_in_cavern(z1, z2)
    if inside then
        return {ok = false, rejected = true, waiting = true,
                error = name_of(inside) .. ' is down in ' .. tostring(layer) .. ': not sealed while a dwarf is on the far side'}
    end
    local skip, list, given = {}, {}, {}
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.kind == 'well' and o.x then skip[okey(o.x, o.y, o.z)] = true end
    end
    for _, p in ipairs(tiles or {}) do
        local x, y, z = tonumber(p.x), tonumber(p.y), tonumber(p.z)
        if x and y and z then
            table.insert(list, {x = x, y = y, z = z})
            given[okey(x, y, z)] = true
        end
    end
    local well_kept, well_why, well_dwarf = 0, nil, 0
    if openings then
        for _, o in pairs(d.openings) do
            if type(o) == 'table' and o.x and o.kind ~= 'well' then
                -- (0.105.47, K48-K4) a cavern well's door with a dwarf beyond it, or
                -- whose shaft gate keeps the cavern out: left open. (r2h7) by
                -- seal_lockable, the test the openings report gives the brain
                local okl, can, why, blocked, code = pcall(seal_lockable, o)
                if okl and not can and (code == 'blocked' or code == 'skip') then
                    well_kept = well_kept + 1
                    if blocked then
                        well_dwarf = well_dwarf + 1
                        well_why = tostring(why)
                    else
                        well_why = well_why or tostring(why)
                    end
                elseif not okl or can then
                    table.insert(list, {x = o.x, y = o.y, z = o.z})
                end
                -- (not lockable for want of a door: nothing to add; the walk below finds nothing there either)
            end
        end
    end
    local found, at = {}, {}
    for _, p in ipairs(list) do
        if not skip[okey(p.x, p.y, p.z)] then
            pcall(function()
                local b = dfhack.buildings.findAtTile(xyz2pos(p.x, p.y, p.z))
                if b and (b:getType() == df.building_type.Door or b:getType() == df.building_type.Hatch) then
                    found[b.id] = b
                    at[b.id] = p
                end
            end)
        end
    end
    rec = rec or {ids = {}, tick = t}
    rec.pulled = type(rec.pulled) == 'table' and rec.pulled or {}
    local have, n, already, adopted, pull_failed = {}, 0, 0, 0, 0
    for _, id in ipairs(rec.ids) do have[id] = true end
    -- (0.105.26 seal fix) one the gate watcher already holds shut goes on
    -- the record too, so the watcher doesn't open it while the beast is about
    local watched = watcher_held()
    local insane = insane_held()      -- (0.105.40b fix) ai-insane's locks: the seal's now
    local lure = lure_open_ids()      -- (0.105.45) a lure's open door is left to the lure
    for id in pairs(lure) do found[id] = nil end
    for id, b in pairs(found) do
        local lever = own_lever(id)
        if lever then
            local okc, c = pcall(function() return b.door_flags.closed end)
            if okc and not c then
                -- (0.105.33 review) counted only when the pull worked (a failed
                -- pull said "locked" and the opening still read unsealed)
                if not dry_run then
                    local okp, pulled = pcall(function() return reqscript('ai-gates').pull_instant(lever) end)
                    if okp and pulled then
                        rec.pulled[tostring(id)] = lever
                        n = n + 1
                    else
                        pull_failed = pull_failed + 1
                    end
                else
                    n = n + 1
                end
            elseif okc then
                already = already + 1
                if watched[id] and rec.pulled[tostring(id)] == nil then
                    if not dry_run then rec.pulled[tostring(id)] = lever end
                    adopted = adopted + 1
                end
            end
        else
            local okf, f = pcall(function() return b.door_flags.forbidden end)
            if okf and not f then
                if not dry_run then
                    U.lock_door(b, true, 'seal') -- (0.105.47) ai-util: the walk map redone
                    if not have[id] then table.insert(rec.ids, id); have[id] = true end
                end
                n = n + 1
            elseif okf then
                already = already + 1
                if (watched[id] or insane[id]) and not have[id] then
                    if not dry_run then table.insert(rec.ids, id); have[id] = true end
                    adopted = adopted + 1
                end
            end
        end
        local p = at[id]
        if p and given[okey(p.x, p.y, p.z)] and not dry_run then
            note_opening(d, p.x, p.y, p.z, 'way_down', tostring(layer), t)
        end
    end
    if n == 0 and adopted > 0 then
        -- everything locked already, some by the gate watcher: on the seal's record now
        if not dry_run then
            d.sealed[layer] = rec
            save_state(d)
        end
        return {ok = true, locked = 0, adopted = adopted, layer = layer, dry_run = dry_run or nil}
    end
    if n == 0 and well_kept > 0 and already == 0 and pull_failed == 0 then
        -- (0.105.51) the only ways down on record are cavern wells' doors, left
        -- open (their shaft gate keeps the cavern out, or a dwarf is beyond):
        -- said as such, not "no door or hatch" (the planner leaves them out too)
        if not dry_run then save_state(d) end
        return {ok = false, rejected = true, well_kept = well_kept, nothing_lockable = true,   -- (r2h7)
                nothing_to_do = well_dwarf == 0 or nil, waiting = well_dwarf > 0 or nil,
                error = 'only cavern well doors on the way down, left open: ' .. tostring(well_why):sub(1, 100)}
    end
    if n == 0 then
        if not dry_run then save_state(d) end          -- (the openings found are kept)
        return {ok = false, rejected = true, nothing_to_do = already > 0 and pull_failed == 0,
                pull_failed = pull_failed > 0 and pull_failed or nil,
                nothing_lockable = (already == 0 and pull_failed == 0) or nil,   -- (r2h7) the brain stops asking
                error = pull_failed > 0 and (pull_failed .. ' lever(s) on the way down would not pull: the doors stay open')
                    or already > 0 and 'every door and hatch on the way down is locked already'
                    or 'no door or hatch on the way down to lock'}
    end
    if not dry_run then
        d.sealed[layer] = rec
        save_state(d)
        announce(('%d way(s) into the caverns locked against a great beast (%s)'):format(n, tostring(layer)))
    end
    return {ok = true, locked = n, adopted = adopted > 0 and adopted or nil, layer = layer, dry_run = dry_run or nil,
            pull_failed = pull_failed > 0 and pull_failed or nil,
            well_kept = well_kept > 0 and well_kept or nil}   -- (0.105.47) a well's door left: a dwarf beyond it
end

-- (0.105.40b) A creature that breathes, spits or hurls fire (a dragon, a fire
-- imp, a generated beast with a fire breath), or burns to the touch: no melee
-- squad goes at it (the fire takes a squad in its armour before it lands a
-- blow; brain/planner_firebreath.py). Read from its caste's raws: each natural
-- ability (caste.body_info.interactions, CAN_DO_INTERACTION) whose CDI:FLOW is
-- DRAGONFIRE, FIREJET or FIREBALL (interaction.material_breath), or whose
-- interaction's material target emits one of those (a generated beast's);
-- the caste flag IMMOLATE. One answer per race and caste, kept for the
-- session (raws don't change while a world is loaded).
-- Returns 'breath' / 'jet' / 'fireball' / 'burns', or false.
FIRE_BREATH_CACHE = FIRE_BREATH_CACHE or {}
local FIRE_FLOW_HOW = {DRAGONFIRE = 'breath', FIREJET = 'jet', FIREBALL = 'fireball'}

-- (fix41) the cache belongs to one world: another save loaded in the same
-- DFHack session has other races under the same numbers (generated beasts)
function fire_breath_of(race, caste)
    -- (r1g9) the world by its name, not the save folder an autosave renames
    local okw, world = pcall(function() return U.world_name() end)
    if not okw or type(world) ~= 'string' then
        okw, world = pcall(function() return df.global.world.cur_savegame.save_dir end)
    end
    world = tostring(okw and world or '?')
    if FIRE_BREATH_WORLD ~= world then
        FIRE_BREATH_CACHE, FIRE_BREATH_WORLD = {}, world
    end
    local key = tostring(race) .. ':' .. tostring(caste)
    local v = FIRE_BREATH_CACHE[key]
    if v ~= nil then return v end
    v = false
    local fire = {}
    pcall(function()
        for name, how in pairs(FIRE_FLOW_HOW) do
            local e = df.breath_attack_type[name]
            if e ~= nil then fire[e] = how end
        end
    end)
    local okc, c = pcall(function() return df.creature_raw.find(race).caste[caste] end)
    if okc and c then
        pcall(function()
            for _, a in ipairs(c.body_info.interactions) do
                local info = a.interaction
                local how = fire[info.material_breath]
                if not how then
                    pcall(function()
                        local it = df.interaction.find(info.type_id)
                        for _, t in ipairs(it and it.targets or {}) do
                            local okb, b = pcall(function() return t.breath_attack_type end)
                            if okb and b ~= nil and fire[b] then how = fire[b]; break end
                        end
                    end)
                end
                if how then v = how; return end
            end
        end)
        if not v then
            local oki, imm = pcall(function() return c.flags.IMMOLATE end)
            if oki and imm then v = 'burns' end
        end
    end
    FIRE_BREATH_CACHE[key] = v
    return v
end

-- (0.105.40b) The others_on_map report's threats marked: fire_breather = true
-- and fire_how for each one that breathes fire (nothing added to the others,
-- so a report without one is as before). Returns how many were marked.
function mark_fire_breathers(o)
    local n = 0
    for _, t in ipairs(type(o) == 'table' and type(o.threats) == 'table' and o.threats or {}) do
        local u = type(t) == 'table' and t.id ~= nil and df.unit.find(t.id) or nil
        if u then
            local okf, how = pcall(fire_breath_of, u.race, u.caste)
            if okf and how then
                t.fire_breather, t.fire_how = true, how
                n = n + 1
            end
        end
    end
    return n
end
