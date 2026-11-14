-- (0.105.47) The way out for a mission's travellers (the messenger, every
-- member of the squads sent).
--
-- Live 14 Nov 17:09: a Make contact and a raid were set up on the World
-- screen, yet neither set out: every way off the map was shut by the AI's
-- own gates from the last run (Hatch "AI gate 1 (surface)" locked, Hatch
-- "AI gate 2 (surface)" locked, the gatehouse bridge raised). The squad (9
-- soldiers, their only order RAID_SITE) and the messenger stood idle (path
-- goal None / MarauderMill): no path to the map edge.
--
-- So, read only here (the bridge's actions do the opening):
--   way(unit_ids)       can each traveller walk out? A traveller's walk group
--                       (dfhack.maps.getWalkableGroup) against the walk groups
--                       of the surface entrances' outside tiles (ai-gates'
--                       scan: those tiles lie between the gates and the map
--                       edge, the way the stranded check reads them)
--   shut_ai()           the surface entrances the AI's own gates hold shut
--                       (ai-gates GATES.closed): the ones it may open
--   report(squads, messenger_uid, controllers)   the `missions` report's
--                       `way_out`
-- and the hold: once a way is opened for a mission, the gate watcher doesn't
-- shut it again on its "danger coming, nobody outside" look for
-- HOLD_TICKS (only an enemy right at the gate, ai-gates IMMINENT, still
-- shuts it): lua/ai-gates-watch.lua reads mission_held().
--@ module = true

OUTS_PER_ENTRANCE = 40         -- each entrance's outside tiles read for their walk groups
HOLD_TICKS = 1200              -- a game day: the travellers walk out meanwhile
MAX_SHUT = 4

MISSION_HOLD = MISSION_HOLD or {}   -- entrance id -> {until = abs tick, key = the mission}

local function gates()
    local ok, G = pcall(function() return reqscript('ai-gates').GATES end)
    if ok and type(G) == 'table' then return G end
    return nil
end

local function abs_tick()
    local ok, t = pcall(function() return reqscript('ai-util').abs_tick() end)
    if ok and type(t) == 'number' then return t end
    local ok2, t2 = pcall(function() return df.global.cur_year * 403200 + df.global.cur_year_tick end)
    return ok2 and t2 or 0
end

-- ai-gates' tile keys: (z * 4096 + y) * 4096 + x
local function unkey(k)
    if type(k) ~= 'number' then return nil end
    return k % 4096, (k // 4096) % 4096, k // (4096 * 4096)
end

local function wgroup(x, y, z)
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) end)
    return ok and type(g) == 'number' and g or 0
end

-- Pure: the walk groups of the surface entrances' outside tiles, from a
-- GATES table and a group reader. nil when the entrances aren't mapped.
function out_groups_of(G, group_at, per)
    if type(G) ~= 'table' or not G.scanned or type(G.entrances) ~= 'table' then return nil end
    local out, any = {}, false
    for _, e in ipairs(G.entrances) do
        if e.kind ~= 'cavern' then
            local n = 0
            for k in pairs(e.outs or {}) do
                local x, y, z = unkey(k)
                if x then
                    local g = group_at(x, y, z)
                    if g ~= 0 then out[g] = true; any = true end
                end
                n = n + 1
                if n >= (per or OUTS_PER_ENTRANCE) then break end
            end
        end
    end
    return any and out or {}
end

function out_groups()
    return out_groups_of(gates(), wgroup)
end

-- Pure: who can't walk out. units: {{id, x, y, z}}; groups: out_groups().
-- {known, n, blocked = {ids}} (known false when the groups aren't known).
function judge(units, groups, group_at)
    local r = {known = groups ~= nil, n = 0, blocked = {}}
    if groups == nil then return r end
    for _, u in ipairs(units or {}) do
        r.n = r.n + 1
        local g = group_at(u.x, u.y, u.z)
        if g == 0 or not groups[g] then table.insert(r.blocked, u.id) end
    end
    return r
end

local function unit_pos(uid)
    local ok, u = pcall(function() return df.unit.find(uid) end)
    if not ok or not u then return nil end
    local okp, x, y, z = pcall(function() return u.pos.x, u.pos.y, u.pos.z end)
    local okd, gone = pcall(function() return u.flags1.inactive or u.flags2.killed end)
    if not okp or (okd and gone) then return nil end
    return {id = uid, x = x, y = y, z = z}
end

function way(unit_ids)
    local units = {}
    for _, id in ipairs(unit_ids or {}) do
        local p = unit_pos(id)
        if p then table.insert(units, p) end
    end
    return judge(units, out_groups(), wgroup)
end

-- Pure: the surface entrances the AI's own gates hold shut (GATES.closed),
-- {{id, kind, x, y, z, held}} at most MAX_SHUT
function shut_ai_of(G, holds, now)
    local out = {}
    if type(G) ~= 'table' or type(G.entrances) ~= 'table' then return out end
    for _, e in ipairs(G.entrances) do
        if e.kind ~= 'cavern' and G.closed and G.closed[e.id] and #out < MAX_SHUT then
            local h = holds and holds[e.id]
            table.insert(out, {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z,
                               held = (h and now and h['until'] > now) or nil})
        end
    end
    return out
end

function shut_ai()
    return shut_ai_of(gates(), MISSION_HOLD, abs_tick())
end

-- The hold: an entrance opened for a mission's travellers isn't shut again
-- by the watcher's "danger coming, nobody outside" look until it ends.
function hold(entrance_id, key, ticks)
    local now = abs_tick()
    MISSION_HOLD[entrance_id] = {['until'] = now + (ticks or HOLD_TICKS), key = tostring(key or 'mission'):sub(1, 40),
                                 since = now}
    return MISSION_HOLD[entrance_id]
end

function mission_held(entrance_id)
    local h = MISSION_HOLD[entrance_id]
    if not h then return false end
    if h['until'] <= abs_tick() then MISSION_HOLD[entrance_id] = nil; return false end
    return true
end

function holds()
    local out = {}
    for id, h in pairs(MISSION_HOLD) do
        if h['until'] > abs_tick() then table.insert(out, {id = id, key = h.key, ['until'] = h['until']}) end
    end
    return out
end

-- Open one way out for a mission (the bridge's mission_way action): the
-- entrance by ai-gates' open_entrance (its own refusals: an enemy within
-- IMMINENT, a great danger in sight, the cavern seal, a gate the AI didn't
-- shut), then the hold.
function open_way(entrance_id, key, dry_run)
    local okg, r = pcall(function() return reqscript('ai-gates').open_entrance(entrance_id, dry_run == true, false) end)
    if not okg then return {ok = false, error = 'open_entrance failed: ' .. tostring(r):sub(1, 120)} end
    if type(r) ~= 'table' then return {ok = false, error = 'open_entrance said nothing'} end
    if r.ok and not dry_run then
        local h = hold(entrance_id, key)
        r.hold_until = h['until']
    end
    r.for_mission = tostring(key or 'mission'):sub(1, 40)
    return r
end

-- The `missions` report's `way_out`: {known, messenger = blocked? (nil:
-- no messenger home), squads = {["<id>"] = blocked members}, shut = the
-- AI's shut surface entrances, holds}
function report(squads, messenger_uid)
    local groups = out_groups()
    local out = {known = groups ~= nil, squads = {}}
    if groups == nil then return out end
    if messenger_uid then
        local p = unit_pos(messenger_uid)
        if p then out.messenger_blocked = #judge({p}, groups, wgroup).blocked > 0 end
    end
    for _, s in ipairs(squads or {}) do
        local units = {}
        for _, uid in ipairs(s.units or {}) do
            local p = unit_pos(uid)
            if p then table.insert(units, p) end
        end
        if #units > 0 then out.squads[tostring(s.id)] = #judge(units, groups, wgroup).blocked end
    end
    out.shut = shut_ai()
    local h = holds()
    if #h > 0 then out.holds = h end
    return out
end

-- A set-up mission's waiting travellers that can't walk out (unit ids)
function blocked_of(unit_ids)
    return way(unit_ids).blocked
end
