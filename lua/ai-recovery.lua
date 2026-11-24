-- (0.105.46, I4) A fallen fort and its migrants.
--
-- Why: D (the Hermit hold) sat at 15 dwarves for ten years, then 8: DF sent
-- it no migrants. After the first two waves DF sends migrants by the wealth
-- the fort created, as the outgoing dwarven caravan reports it, and only
-- under the population cap (the AI's cap rule, ai-society get_popcap). When
-- the brain (brain/planner_recovery.py) finds a fallen fort with its cap
-- open and nobody coming for half a year, it calls a wave with DFHack's own
-- `force Migrants` (the script queues DF's own Migrants event for the fort's
-- civilisation; DF makes the wave).
--
--   report()            the `migration` section: {force = 'force' | nil (the
--                       script that can call a wave), queued (Migrants events
--                       waiting in DF's timed events), civ (the fort's
--                       civilisation found), hermit_tool (DFHack's own
--                       `hermit` is on: it turns migrants away; nil unknown)}
--   call_migrants(dry)  the `call_migrants` action: refused while a wave is
--                       already queued; a dry run says what it would run
--
-- Every read is behind pcall (fields this DF may name otherwise).
--@module = true

CARAVAN_UNITS_MAX = 60     -- (r2 h9) merchants (and their animals) told to leave in one go at most

-- The DFHack script that calls a migrant wave, or nil.
local function force_script()
    local ok, path = pcall(function() return dfhack.findScript('force') end)
    if ok and path then return 'force' end
    return nil
end

-- DF's Migrants events already queued (a called wave not yet arrived).
local function queued()
    local n = 0
    local ok = pcall(function()
        local want = df.timed_event_type.Migrants
        for _, ev in ipairs(df.global.timed_events) do
            if ev.type == want then n = n + 1 end
        end
    end)
    return ok and n or nil
end

-- DFHack's own hermit tool (it blocks caravans, migrants and diplomats): on,
-- off, or nil when this DFHack can't say.
local function hermit_on()
    local ok, on = pcall(function()
        if not dfhack.findScript('hermit') then return false end
        local h = reqscript('hermit')
        if type(h.isEnabled) == 'function' then return h.isEnabled() == true end
        return nil
    end)
    if ok then return on end
    return nil
end

-- --- (r2 h9) the caravans and their merchants --------------------------------------
--
-- B (15 Nov run): the y251 caravan said "will be leaving soon" and never
-- embarked; its two merchants were still on the map in y261, the fort's 325
-- goods stayed locked in the depot, and for ten years no caravan and no
-- migrant came (12 waves called by force Migrants brought nobody). DF's own
-- bug 12624 has caravans stuck "Leaving" for years with the same signs. The
-- trade module (ai-trade.lua) sees only caravans coming or at the depot; this
-- reads them all (DF's plotinfo.caravans) with the merchants still on the
-- map, whether each can walk off it (ai-way-out's edge groups), for the
-- brain's migrant drought (brain/planner_outside.py).
--
--   caravans()          {{entity, own (the fort's civ), state (DF's trade
--                       state's name), days_left, tribute, merchants (on the
--                       map, alive), can_leave (of those, how many stand in a
--                       walk group that reaches the map's edge; nil unknown)}}
--   free_caravan(e, d, step)  the `free_caravan` action: the merchants of a
--                       caravan that is Leaving (or out of time) told to walk
--                       off the map as DFHack's own emigration does
--                       (flags1.forest, the leave countdown); only those who
--                       can reach the edge; refused for a caravan coming or
--                       trading. (0.105.97) `step` escalates (the brain's
--                       planner_outside picks it, each once the one before
--                       failed for a while): 'walk' (nil: the above), 'edge'
--                       (each merchant that can reach the edge teleported to
--                       the nearest map-edge tile of its own walk group, then
--                       told to leave: none fighting or held), 'dismiss' (no
--                       merchant of it left on the map and DF still holds it
--                       Leaving: DFHack's `fix/stuck-merchants`, only while no
--                       merchant of ANY caravan is on the map as its docs ask,
--                       then `caravan leave <id>`; what each returned is said)

local function trade_state_name(c)
    local ok, n = pcall(function() return df.caravan_state.T_trade_state[c.trade_state] end)
    if ok and n then return tostring(n) end
    local okr, v = pcall(function() return c.trade_state end)
    return okr and tostring(v) or '?'
end

-- the merchants (and their pack animals: DF flags them merchants too) on the
-- map, alive, by their civilisation
local function merchants_by_civ()
    local by = {}
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function()
                if u.flags1.merchant and not u.flags1.left and not u.flags1.inactive
                        and not (dfhack.units.isDead and dfhack.units.isDead(u)) then
                    local list = by[u.civ_id] or {}
                    table.insert(list, u)
                    by[u.civ_id] = list
                end
            end)
        end
    end)
    return by
end

-- the map's edge groups (ai-way-out), or nil; (0.105.73) fresh: read again
-- unless read this tick, for a "can't leave" verdict (DF renumbers its walk
-- groups: the cache missed them, live 22 Nov)
local function edges(fresh)
    local ok, g = pcall(function()
        local W = reqscript('ai-way-out')
        if fresh and W.edge_groups_fresh then return W.edge_groups_fresh() end
        return W.edge_groups()
    end)
    if ok and type(g) == 'table' then return g end
    return nil
end

local function can_leave(u, eg)
    if not eg then return nil end
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(u.pos) end)
    if not ok or type(g) ~= 'number' or g == 0 then return false end
    return eg[g] == true
end

-- (0.105.73) the edges for these merchants: the cache, read again first when
-- any would read "can't leave"
local function edges_for(list)
    local eg = edges()
    if not eg then return edges(true) end
    for _, u in ipairs(list) do
        if can_leave(u, eg) == false then return edges(true) or eg end
    end
    return eg
end

-- is this caravan done trading (DF's Leaving, or out of time and not coming)?
local function leaving(c, state)
    if state == 'Leaving' then return true end
    local ok, t = pcall(function() return c.time_remaining end)
    return ok and type(t) == 'number' and t <= 0 and state ~= 'Approaching'
end

function caravans()
    local out = {}
    local by = merchants_by_civ()
    local okc, civ = pcall(function() return df.global.plotinfo.civ_id end)
    pcall(function()
        for _, c in ipairs(df.global.plotinfo.caravans) do
            local state = trade_state_name(c)
            local e = {entity = c.entity, own = okc and c.entity == civ or nil, state = state}
            pcall(function() e.days_left = math.floor(c.time_remaining / 1200) end)
            pcall(function() e.tribute = c.flags.tribute or nil end)
            local list = by[c.entity] or {}
            e.merchants = #list
            if #list > 0 and leaving(c, state) then
                local leg = edges_for(list)
                local n, known = 0, leg ~= nil
                for _, u in ipairs(list) do if can_leave(u, leg) then n = n + 1 end end
                e.can_leave = known and n or nil
                e.leaving = true
            elseif leaving(c, state) then
                e.leaving = true
            end
            table.insert(out, e)
        end
    end)
    return out
end

-- (0.105.97) the caravan of this civilisation and its index in DF's list
-- (DFHack's `caravan` command numbers them by that index)
local function find_caravan(entity)
    local c, idx
    pcall(function()
        for i, x in ipairs(df.global.plotinfo.caravans) do
            if x.entity == entity then c, idx = x, i end
        end
    end)
    return c, idx
end

-- --- (0.105.97) the escalation: taken to the edge, then dismissed -------------------
--
-- B (23 Nov): a caravan stuck "Leaving" 118 days with 2 merchants on the map
-- (DF bug 12624), told to walk off twice and staying: no caravan and no
-- migrant came since. The AI now takes them to the map's edge itself, and
-- when DF still holds the caravan once they are gone, runs DFHack's own fixes.

-- the walk group of a tile (tests replace this)
function edge_group_at(x, y, z)
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) end)
    return ok and type(g) == 'number' and g or 0
end

local function mkpos(x, y, z)
    if type(xyz2pos) == 'function' then return xyz2pos(x, y, z) end
    return {x = x, y = y, z = z}
end

-- Pure: the border tiles of a W x H map on level z with a walk group ({x, y, z, g}).
function edge_tiles_at(W, H, z, at)
    local out = {}
    local function look(x, y)
        local g = at(x, y, z)
        if type(g) == 'number' and g ~= 0 then table.insert(out, {x = x, y = y, z = z, g = g}) end
    end
    for x = 0, W - 1 do
        look(x, 0)
        if H > 1 then look(x, H - 1) end
    end
    for y = 1, H - 2 do
        look(0, y)
        if W > 1 then look(W - 1, y) end
    end
    return out
end

-- Pure: the nearest border tile of walk group g to pos, on the nearest level
-- (lo..hi) that has one; memo keeps each level's tiles (one read a level for
-- all the merchants). nil: none.
function edge_tile_near(W, H, lo, hi, at, pos, g, memo)
    memo = memo or {}
    local span = math.max(pos.z - lo, hi - pos.z, 0)
    for dz = 0, span do
        local best, bd
        local zs = dz == 0 and {pos.z} or {pos.z - dz, pos.z + dz}
        for _, z in ipairs(zs) do
            if z >= lo and z <= hi then
                local list = memo[z]
                if not list then
                    list = edge_tiles_at(W, H, z, at)
                    memo[z] = list
                end
                for _, t in ipairs(list) do
                    if t.g == g then
                        local d = math.abs(t.x - pos.x) + math.abs(t.y - pos.y)
                        if not bd or d < bd then best, bd = t, d end
                    end
                end
            end
        end
        if best then return best end
    end
    return nil
end

-- a merchant never moved: one fighting, or a prisoner (caged, chained, in a
-- cage); nil when free
local function held(u)
    local okp, pris = pcall(function() return u.flags1.caged or u.flags1.chained end)
    if okp and pris then return 'prisoner' end
    local okc, ct = pcall(function() return dfhack.units.getContainer(u) end)
    if okc and ct then return 'prisoner' end
    local oko, opp = pcall(function() return u.opponent.unit_id end)
    if oko and type(opp) == 'number' and opp ~= -1 then return 'combat' end
    return nil
end

local function map_box()
    local ok, W, H, Z = pcall(function()
        local m = df.global.world.map
        return m.x_count, m.y_count, m.z_count
    end)
    if not ok or type(W) ~= 'number' or W <= 0 then return nil end
    local lo, hi = 0, Z - 1
    pcall(function()
        local z = reqscript('ai-way-out').EDGE.z     -- the levels the edge groups were read on
        if type(z) == 'table' and type(z[1]) == 'number' and type(z[2]) == 'number' then lo, hi = z[1], z[2] end
    end)
    return W, H, lo, hi
end

local function walk_off(u)
    pcall(function() u.flags1.forest = true end)
    pcall(function() u.animal.leave_countdown = 2 end)
end

-- step 'edge': each merchant (and pack animal) that can reach the edge, not
-- fighting, not held, teleported to the nearest edge tile of its own walk
-- group and told to leave at once
local function to_edge(entity, state, list, dry)
    local eg = edges_for(list)
    if not eg then return {ok = false, error = 'the map edge groups could not be read'} end
    local W, H, lo, hi = map_box()
    if not W then return {ok = false, error = 'the map could not be read'} end
    local memo, moved, shut, kept, notile, failed = {}, 0, 0, 0, 0, 0
    for _, u in ipairs(list) do
        if moved >= CARAVAN_UNITS_MAX then break end
        local why = held(u)
        local can = can_leave(u, eg)
        if why then
            kept = kept + 1
        elseif not can then
            shut = shut + 1
        else
            local okg, g = pcall(function() return dfhack.maps.getWalkableGroup(u.pos) end)
            local okt, t = pcall(edge_tile_near, W, H, lo, hi, edge_group_at,
                                 {x = u.pos.x, y = u.pos.y, z = u.pos.z}, okg and g or 0, memo)
            if not okg or not okt or not t then
                notile = notile + 1
            elseif dry then
                moved = moved + 1
            else
                local okm, done = pcall(function() return dfhack.units.teleport(u, mkpos(t.x, t.y, t.z)) end)
                if okm and done ~= false then
                    walk_off(u)
                    moved = moved + 1
                else
                    failed = failed + 1
                end
            end
        end
    end
    local function nz(n) return n > 0 and n or nil end
    local out = {step = 'edge', state = state, dry_run = dry or nil, moved = moved, told = moved, shut = nz(shut),
                 held = nz(kept), no_tile = nz(notile), failed = nz(failed)}
    if moved == 0 then
        out.ok, out.rejected = false, true
        out.error = ('%d merchant(s) on the map, none taken to the edge (%d with no way out, %d fighting or held, '
                     .. '%d with no edge tile, %d teleports failed)'):format(#list, shut, kept, notile, failed)
        return out
    end
    out.ok = true
    return out
end

-- a DFHack command run, its answer kept (short)
local function run_cmd(name, ...)
    local okc, out, rv = pcall(dfhack.run_command_silent, name, ...)
    local words = table.concat({name, ...}, ' ')
    if not okc then return {cmd = words, ok = false, out = tostring(out):sub(1, 200)} end
    return {cmd = words, ok = rv == (CR_OK or 0), rv = tonumber(rv) or nil, out = tostring(out or ''):sub(1, 200)}
end

local function has_script(name)
    local ok, p = pcall(function() return dfhack.findScript(name) end)
    return ok and p ~= nil and p ~= false
end

-- step 'dismiss': no merchant of it on the map, DF still holding it Leaving
local function dismiss(entity, idx, dry)
    local by = merchants_by_civ()
    if by[entity] and #by[entity] > 0 then
        return {ok = false, rejected = true, step = 'dismiss',
                error = #by[entity] .. ' of its merchant(s) still on the map: not dismissed'}
    end
    local others = 0
    for _, l in pairs(by) do others = others + #l end
    local ran, skipped = {}, nil
    -- DFHack's docs: fix/stuck-merchants is never run with any merchant on the map
    if others > 0 then
        skipped = others .. ' merchant(s) of another caravan on the map: fix/stuck-merchants not run'
    elseif not has_script('fix/stuck-merchants') then
        skipped = 'this DFHack has no fix/stuck-merchants'
    elseif dry then
        table.insert(ran, run_cmd('fix/stuck-merchants', '-n'))    -- its own dry run: lists, changes nothing
    else
        table.insert(ran, run_cmd('fix/stuck-merchants'))
    end
    if not has_script('caravan') then
        skipped = (skipped and skipped .. '; ' or '') .. 'this DFHack has no caravan command'
    elseif type(idx) == 'number' and not dry then
        table.insert(ran, run_cmd('caravan', 'leave', tostring(idx)))
    end
    local any = false
    for _, x in ipairs(ran) do if x.ok then any = true end end
    local c2 = find_caravan(entity)
    local still = c2 ~= nil and leaving(c2, trade_state_name(c2)) or false
    local out = {step = 'dismiss', dry_run = dry or nil, ran = ran, skipped = skipped, still = still, index = idx}
    if not any then
        out.ok = false
        out.error = 'nothing could be run' .. (skipped and (': ' .. skipped) or '')
        return out
    end
    out.ok = true
    return out
end

function free_caravan(entity, dry, step)
    if step ~= nil and step ~= 'walk' and step ~= 'edge' and step ~= 'dismiss' then
        return {ok = false, rejected = true, error = 'free_caravan step is walk, edge or dismiss, not ' .. tostring(step)}
    end
    local c, idx = find_caravan(entity)
    if not c then return {ok = false, rejected = true, error = 'no caravan of entity ' .. tostring(entity)} end
    local state = trade_state_name(c)
    if not leaving(c, state) then
        return {ok = false, rejected = true, error = 'that caravan is ' .. tostring(state) .. ', not leaving: left to trade'}
    end
    if step == 'dismiss' then return dismiss(entity, idx, dry) end
    local list = merchants_by_civ()[entity] or {}
    if #list > 0 and step == 'edge' then return to_edge(entity, state, list, dry) end
    if #list == 0 then return {ok = false, rejected = true, error = 'none of its merchants is on the map'} end
    local eg = edges_for(list)
    local told, shut = 0, 0
    for _, u in ipairs(list) do
        if told >= CARAVAN_UNITS_MAX then break end
        local can = can_leave(u, eg)
        if can == false then
            shut = shut + 1
        else
            if not dry then walk_off(u) end
            told = told + 1
        end
    end
    if told == 0 then
        return {ok = false, rejected = true, shut = shut,
                error = shut .. ' merchant(s) on the map, none with a way to the map edge'}
    end
    return {ok = true, dry_run = dry or nil, told = told, shut = shut > 0 and shut or nil, state = state,
            step = 'walk'}
end

function report()
    local out = {force = force_script(), queued = queued(), hermit_tool = hermit_on()}
    pcall(function()
        out.civ = df.historical_entity.find(df.global.plotinfo.civ_id) ~= nil
    end)
    -- (r2 h9) every caravan DF holds, with its merchants still on the map
    local okc, cs = pcall(caravans)
    if okc and type(cs) == 'table' and #cs > 0 then out.caravans = cs end
    return out
end

function call_migrants(dry)
    local name = force_script()
    if not name then
        return {ok = false, error = 'this DFHack has no force script to call a migrant wave'}
    end
    local before = queued()
    if before and before > 0 then
        return {ok = false, rejected = true, error = 'a migrant wave is already on its way', queued = before}
    end
    if dry then return {ok = true, dry_run = true, script = name, queued = before} end
    local out, rv = dfhack.run_command_silent(name, 'Migrants')
    if rv ~= (CR_OK or 0) then
        return {ok = false, error = name .. ' Migrants failed: ' .. tostring(out):sub(1, 160)}
    end
    local after = queued()
    if after ~= nil and after <= (before or 0) then
        return {ok = false, error = name .. ' Migrants queued no wave: ' .. tostring(out):sub(1, 160)}
    end
    return {ok = true, script = name, queued = after}
end
