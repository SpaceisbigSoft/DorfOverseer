-- (0.105.45, Phase 11 "fighting back") Hunting: the fort's squads sent out
-- to kill what threatens it, forgotten beasts in the caverns, titans and
-- megabeasts on the surface, ambushers, thieves, a wounded visitor keeping
-- the dwarves from their drink (the player, 14 Nov: "the dwarves can kill
-- forgotten beasts and other enemies; work it into the plan by offence").
-- The planner's half is brain/planner_hunt.py; this module only reads and
-- does what it is told:
--
--   * report(): the `hunt` section: every loose hostile or dangerous unit on
--     the map (capped at 60) with whether a squad can walk to it now (DF's
--     walk groups, the AI's cavern seals and shut gates), the squads with
--     their strength, and the AI's hunts under way; a hunt whose target died
--     or left the map is closed here (history `won` / `gone`);
--   * send(): hunt_send, kill orders through ai-military's own orders() and
--     the hunt kept in the save's site data;
--   * recall(): hunt_recall, the AI's orders cleared through the same
--     orders(), the outcome kept in a short history.
--
-- Never a target: merchants, diplomats, tame animals and pets, the fort's
-- citizens and residents, or a visitor who isn't a wounded interrupter (and
-- ai-military kill_target_ok guards the order itself as for every kill).
-- DF fields this isn't sure of are read inside pcall.
--@module = true

local U = reqscript('ai-util')

HUNT_KEY = 'ai-overseer/hunts'
MAX_TARGETS = 60             -- targets listed at most (the great ones first)
HISTORY_MAX = 20             -- finished hunts kept
SEEN_MAX = 300               -- first sightings kept at most
NEAR_TILES = 20              -- a citizen this close (x/y tiles)...
NEAR_Z = 3                   -- ...and this many levels: near the target
MIN_ARMED = 2                -- a squad sent hunting has at least this many armed
MAX_SQUADS = 10              -- squads in one hunt_send at most
REASON_MAX = 80              -- characters of a recall's reason kept

local KINDS = {'ForgottenBeast', 'Undead', 'Megabeast', 'SemiMegabeast', 'NightCreature', 'Titan', 'Demon'}

-- inside a report, the report's one walk of the units (ai-util REPORT_CTX)
local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end
local function report_units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end

local function is(fn, u)
    if type(fn) ~= 'function' then return false end
    local ok, v = pcall(fn, u)
    return ok and v or false
end

local function mil()
    local ok, M = pcall(reqscript, 'ai-military')
    return ok and M or nil
end

local function threats()
    local ok, T = pcall(reqscript, 'ai-threats')
    return ok and T or nil
end

-- --- pure parts (tested without the game) ---------------------------------------

-- Is this unit, by its facts, a hunting target? `f`: {dead, caged, hidden,
-- citizen, resident, merchant, diplomat, tame, fort_animal, visitor, wounded,
-- interrupter, danger, invader, hostile_wild, thief, ambush}. Returns the
-- answer and the reason it is (or isn't) one.
function target_ok(f)
    if f.dead then return false, 'dead' end
    if f.caged then return false, 'caged' end
    if f.hidden then return false, 'hidden' end
    if f.citizen or f.resident then return false, 'the fort\'s own' end
    if f.merchant then return false, 'merchant' end
    if f.diplomat then return false, 'diplomat' end
    if f.tame or f.fort_animal then return false, 'tame' end
    if f.visitor then
        if f.wounded and f.interrupter then return true, 'wounded_visitor' end
        return false, 'visitor'
    end
    if f.danger then return true, 'danger' end
    if f.invader then return true, 'invader' end
    if f.ambush then return true, 'ambush' end
    if f.thief then return true, 'thief' end
    if f.hostile_wild then return true, 'hostile_wild' end
    if f.interrupter then return true, 'interrupter' end
    return false, 'harmless'
end

-- Where a unit stands: 'cavern' (a Cavern layer), 'surface' (under the sky)
-- or 'inside' (the rest: the fort's levels, the rock, the deep layers).
function region_of(layer, outside)
    if type(layer) == 'string' and layer:find('^Cavern') then return 'cavern' end
    if outside then return 'surface' end
    return 'inside'
end

-- Can a squad from the fort walk to it now? `t`: {group (the target's walk
-- group, 0 unknown), main (the citizens' main group), region, layer, sealed
-- ({layer = true} the AI's cavern seals; 'all caverns' for every one),
-- gate_shut (an AI gate shut now), dist (rough tiles from home)}.
-- {ok, length, blocked_by = 'none'|'seal'|'gate'|'no_path'}.
function classify_route(t)
    local sealed = type(t.sealed) == 'table' and t.sealed or {}
    local seal_here = t.region == 'cavern' and (sealed['all caverns'] or (t.layer and sealed[t.layer])) and true or false
    if seal_here then return {ok = false, blocked_by = 'seal'} end
    if t.group and t.group ~= 0 and t.main and t.group == t.main then
        return {ok = true, length = t.dist and math.floor(t.dist + 0.5) or nil, blocked_by = 'none'}
    end
    if t.gate_shut and t.region ~= 'cavern' then return {ok = false, blocked_by = 'gate'} end
    return {ok = false, blocked_by = 'no_path'}
end

-- The history with `row` added, the newest last, at most `max` kept.
function push_history(list, row, max)
    list = type(list) == 'table' and list or {}
    table.insert(list, row)
    max = max or HISTORY_MAX
    while #list > max do table.remove(list, 1) end
    return list
end

-- The most common walk group among the citizens' groups (a list), 0 for none.
function main_group(groups)
    local n, best, best_n = {}, 0, 0
    for _, g in ipairs(groups) do
        if g and g ~= 0 then
            n[g] = (n[g] or 0) + 1
            if n[g] > best_n or (n[g] == best_n and g < best) then best, best_n = g, n[g] end
        end
    end
    return best
end

-- Citizens (a by-z table of {x, y} lists) within NEAR_TILES and NEAR_Z.
function count_near(pos, by_z)
    local n = 0
    for dz = -NEAR_Z, NEAR_Z do
        for _, p in ipairs(by_z[pos.z + dz] or {}) do
            if math.abs(p.x - pos.x) <= NEAR_TILES and math.abs(p.y - pos.y) <= NEAR_TILES then n = n + 1 end
        end
    end
    return n
end

-- Targets in order: the great dangers, then those that can reach the
-- dwarves, then by workers near; the first `max` kept.
function order_targets(list, max)
    table.sort(list, function(a, b)
        if (a.great_danger == true) ~= (b.great_danger == true) then return a.great_danger == true end
        if (a.can_reach_dwarves == true) ~= (b.can_reach_dwarves == true) then return a.can_reach_dwarves == true end
        if (a.near_workers or 0) ~= (b.near_workers or 0) then return (a.near_workers or 0) > (b.near_workers or 0) end
        return (a.id or 0) < (b.id or 0)
    end)
    max = max or MAX_TARGETS
    while #list > max do table.remove(list) end
    return list
end

-- --- the save ---------------------------------------------------------------------

-- {active = {[squad id text] = {squad_id, target_id, target_name, since_tick,
-- soldiers_at_start, soldier_ids}}, history = {...}, seen = {[unit id text] = tick}}
function load_state()
    local d = U.site_get(HUNT_KEY, {})
    if type(d) ~= 'table' then d = {} end
    d.active = type(d.active) == 'table' and d.active or {}
    d.history = type(d.history) == 'table' and d.history or {}
    d.seen = type(d.seen) == 'table' and d.seen or {}
    return d
end

local function save_state(d)
    return U.site_put(HUNT_KEY, d)
end

-- --- the game -----------------------------------------------------------------------

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

local function name_of(u, txt)
    local ok, n = pcall(function() return dfhack.units.getReadableName(u) end)
    n = ok and n or ('unit ' .. tostring(u.id))
    return txt and txt(n) or n
end

local function outside_at(p)
    local ok, des = pcall(dfhack.maps.getTileFlags, p.x, p.y, p.z)
    return ok and des and des.outside and true or false
end

local function group_at(p)
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(p.x, p.y, p.z))
    return (ok and g) or 0
end

-- a flier or a swimmer has no walk group where it is: the ground beside or
-- below it (9 tiles), the first one that has one
local function group_near(p)
    local g = group_at(p)
    if g ~= 0 then return g end
    for _, d in ipairs({{0, 0, -1}, {1, 0, 0}, {-1, 0, 0}, {0, 1, 0}, {0, -1, 0},
                        {1, 1, 0}, {-1, -1, 0}, {1, -1, 0}, {-1, 1, 0}}) do
        g = group_at({x = p.x + d[1], y = p.y + d[2], z = p.z + d[3]})
        if g ~= 0 then return g end
    end
    return 0
end

-- the layer's name as the bridge's layer_at gives it (Cavern1-3, MagmaSea,
-- Underworld, upper_levels, between_layers), from the bridge's get_layers()
local function layer_at(pos, layers)
    if type(layers) ~= 'table' or type(layers.by_gid) ~= 'table' then return nil end
    local ok, block = pcall(dfhack.maps.getTileBlock, pos.x, pos.y, pos.z)
    if not ok or not block then return nil end
    local l = layers.by_gid[block.global_feature]
    if l then return l.name end
    if not layers.top_z or pos.z > layers.top_z then return 'upper_levels' end
    return 'between_layers'
end

local function wounded(u)
    local ok, hurt = pcall(function()
        return (u.body.blood_count or 0) < (u.body.blood_max or 0)
            or (u.health ~= nil and u.health.flags.needs_healthcare) or false
    end)
    return ok and hurt == true
end

local function flier(u)
    local ok, v = pcall(function() return u.enemy.caste_flags.FLIER end)
    return ok and v and true or false
end

local function kinds_of(u)
    local out = {}
    for _, f in ipairs(KINDS) do
        local ok, yes = pcall(function() return dfhack.units['is' .. f](u) end)
        if ok and yes then table.insert(out, f) end
    end
    return out
end

local function caged(u)
    local ok, v = pcall(function() return u.flags1.caged or u.flags1.chained end)
    return ok and v and true or false
end

-- an ambusher (DF's ambush flag; one still hidden is no target: isHidden)
local function ambusher(u)
    local ok, v = pcall(function() return u.flags1.hidden_ambusher or u.flags1.hidden_in_ambush end)
    return ok and v and true or false
end

local function thief_of(u, T)
    if not (T and T.thief_kind) then return nil end
    local prof, goal
    pcall(function() prof = df.profession[u.profession] end)
    pcall(function() goal = df.unit_path_goal[u.path.goal] end)
    local ok, k = pcall(T.thief_kind, prof, goal)
    return ok and k or nil
end

-- the facts target_ok() weighs, for one unit
local function facts(u, T, hostile_wild)
    local du = dfhack.units
    local f = {dead = is(du.isDead, u), caged = caged(u), hidden = is(du.isHidden, u),
               citizen = is(du.isCitizen, u), resident = is(du.isResident, u),
               merchant = is(du.isMerchant, u), diplomat = is(du.isDiplomat, u),
               tame = is(du.isTame, u) or is(du.isPet, u),
               fort_animal = is(du.isAnimal, u) and is(du.isFortControlled, u)}
    -- the fort's own, traders, the caged and the dead: nothing more read (cheap)
    if f.dead or f.caged or f.hidden or f.citizen or f.resident or f.merchant
            or f.diplomat or f.tame or f.fort_animal then
        return f
    end
    f.visitor = is(du.isVisitor, u)
    f.danger, f.invader, f.ambush = is(du.isDanger, u), is(du.isInvader, u), ambusher(u)
    f.thief = thief_of(u, T) ~= nil
    f.hostile_wild = hostile_wild and is(hostile_wild, u) or false
    -- the costly ones only where they could matter
    if f.visitor or not (f.danger or f.invader or f.thief or f.ambush or f.hostile_wild) then
        f.interrupter = (T and T.interrupting) and is(T.interrupting, u) or false
    end
    if f.visitor then f.wounded = wounded(u) end
    return f
end

-- the AI's cavern seals ({layer = true}) and whether an AI gate is shut now
local function seals_and_gates(T)
    local sealed, shut = {}, false
    if T and T.load_state then
        pcall(function()
            for layer, s in pairs(T.load_state().sealed or {}) do
                if type(s) == 'table' then sealed[layer] = true end
            end
        end)
    end
    pcall(function()
        local G = reqscript('ai-gates')
        for _, v in pairs(G.GATES and G.GATES.closed or {}) do if v then shut = true end end
    end)
    return sealed, shut
end

-- the squad's living soldiers (units)
local function soldiers_of(sq)
    local out = {}
    for _, pos in ipairs(sq.positions) do
        pcall(function()
            if pos.occupant ~= -1 then
                local hf = df.historical_figure.find(pos.occupant)
                local u = hf and hf.unit_id ~= -1 and df.unit.find(hf.unit_id)
                if u and not dfhack.units.isDead(u) then table.insert(out, u) end
            end
        end)
    end
    return out
end

-- a crossbow or bow in hand and bolts or arrows on them (a quiver's or loose)
local function shoots(u)
    local ranged, ammo = false, false
    pcall(function()
        for _, inv in ipairs(u.inventory) do
            local it = inv.item
            local t = it:getType()
            if t == df.item_type.WEAPON then
                local okd, a = pcall(function() return it.subtype.ranged_ammo end)
                if okd and type(a) == 'string' and a ~= '' then ranged = true end
            elseif t == df.item_type.AMMO then
                ammo = true
            elseif t == df.item_type.QUIVER then
                local okc, c = pcall(dfhack.items.getContainedItems, it)
                if okc and c and #c > 0 then ammo = true end
            end
        end
    end)
    return ranged and ammo
end

local function under_sky_or_cavern(u, layers)
    local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
    return outside_at(p) or region_of(layer_at(p, layers), false) == 'cavern'
end

local function kill_order_of(sq)
    local ids = {}
    for _, o in ipairs(sq.orders) do
        pcall(function()
            if df.squad_order_kill_listst:is_instance(o) then
                for _, id in ipairs(o.units) do ids[id] = true end
            end
        end)
    end
    return ids
end

-- a squad the player gave orders to (any order not the AI's) is not the AI's to send
local function players_orders(M, sq, sid)
    for _, o in ipairs(sq.orders) do
        local ok, mine = pcall(M.ai_order, o, sid)
        if not (ok and mine) then return true end
    end
    return false
end

-- --- the report -----------------------------------------------------------------------

local function close_hunt(d, key, outcome, t, extra)
    local h = d.active[key]
    if not h then return end
    local lost = 0
    for _, id in ipairs(type(h.soldier_ids) == 'table' and h.soldier_ids or {}) do
        local u = df.unit.find(id)
        if not u or dfhack.units.isDead(u) then lost = lost + 1 end
    end
    local row = {squad_id = h.squad_id, target_id = h.target_id, target_name = h.target_name,
                 outcome = outcome, since_tick = h.since_tick, end_tick = t,
                 soldiers_at_start = h.soldiers_at_start, soldiers_lost = lost}
    for k, v in pairs(extra or {}) do row[k] = v end
    d.history = push_history(d.history, row, HISTORY_MAX)
    d.active[key] = nil
end

-- `opts.layers`: the bridge's get_layers() (for the layer names)
function report(txt, opts)
    opts = opts or {}
    local layers = opts.layers
    local d = load_state()
    local t = now_tick()
    local T = threats()
    local M = mil()
    local changed = false
    local hostile_wild
    pcall(function() hostile_wild = reqscript('ai-builder').hostile_wild end)

    -- the citizens: their groups (the main one), by level, home
    local by_z, glist, cgroups = {}, {}, {}
    local sx, sy, sz, sn = 0, 0, 0, 0
    local cit = report_citizens(true)
    for _, u in ipairs(cit) do
        local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
        by_z[p.z] = by_z[p.z] or {}
        table.insert(by_z[p.z], p)
        local g = group_at(p)
        table.insert(glist, g)
        if g ~= 0 then cgroups[g] = true end
    end
    local main = main_group(glist)
    for i, u in ipairs(cit) do
        if glist[i] == main then sx, sy, sz, sn = sx + u.pos.x, sy + u.pos.y, sz + u.pos.z, sn + 1 end
    end
    local home = sn > 0 and {x = sx / sn, y = sy / sn, z = sz / sn} or nil
    local sealed, gate_shut = seals_and_gates(T)

    -- the targets: one pass over the units
    local targets, seen_now, total = {}, {}, 0
    for _, u in ipairs(report_units()) do
        local okf, f = pcall(function()
            if not dfhack.units.isActive(u) then return nil end
            return facts(u, T, hostile_wild)
        end)
        local yes, why = false, nil
        if okf and f then yes, why = target_ok(f) end
        if yes then
            total = total + 1
            local key = tostring(u.id)
            seen_now[key] = true
            if d.seen[key] == nil then d.seen[key] = t; changed = true end
            local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            local layer = layer_at(pos, layers)
            local region = region_of(layer, outside_at(pos))
            local g = group_near(pos)
            local dist = home and (math.max(math.abs(pos.x - home.x), math.abs(pos.y - home.y))
                                   + 3 * math.abs(pos.z - home.z)) or nil
            local fire
            if T and T.fire_breath_of then
                local okb, how = pcall(T.fire_breath_of, u.race, u.caste)
                if okb then fire = how and true or false end
            end
            local kinds = kinds_of(u)
            local row = {
                id = u.id, name = name_of(u, txt), kinds = kinds, why = why,
                great_danger = is(dfhack.units.isGreatDanger, u),
                size = (function() local oks, v = pcall(function() return u.body.size_info.size_cur end)
                            return oks and v or nil end)(),
                pos = pos, layer = layer, region = region,
                flier = flier(u), fire_breather = fire,
                ambush = f.ambush, thief = f.thief,
                wounded_visitor = (f.visitor and f.wounded and f.interrupter) and true or false,
                invader = f.invader or nil,
                route = classify_route({group = g, main = main, region = region, layer = layer,
                                        sealed = sealed, gate_shut = gate_shut, dist = dist}),
                near_workers = count_near(pos, by_z),
                seen_ticks = math.max(0, t - (tonumber(d.seen[key]) or t)),
            }
            if g ~= 0 then row.can_reach_dwarves = cgroups[g] == true end
            -- (0.105.45, merge) the same facts as the threats rows (breath, venom,
            -- armour, speed...), so the hunt is judged like a defence (planner_matchup)
            pcall(function() reqscript('ai-threat-facts').add_facts(row, u) end)
            if M and M.kill_target_ok then
                local okk, k = pcall(M.kill_target_ok, u)
                row.kill_ok = okk and k == true
            end
            table.insert(targets, row)
        end
    end
    -- sightings of units no longer listed forgotten (kept capped)
    local nseen = 0
    for k in pairs(d.seen) do
        if not seen_now[k] then d.seen[k] = nil; changed = true else nseen = nseen + 1 end
    end
    if nseen > SEEN_MAX then d.seen = {}; changed = true end
    order_targets(targets, MAX_TARGETS)

    -- the hunts: closed when the target died, was caged or left; dropped when
    -- the squad is gone or its kill order no longer names the target
    local hunts = {}
    local keys = {}
    for k in pairs(d.active) do table.insert(keys, k) end
    table.sort(keys)
    for _, k in ipairs(keys) do
        local h = d.active[k]
        local u = type(h) == 'table' and df.unit.find(tonumber(h.target_id) or -1) or nil
        local sq = (type(h) == 'table' and M and M.fort_squad) and M.fort_squad(tonumber(h.squad_id) or -1) or nil
        if type(h) ~= 'table' then
            d.active[k] = nil; changed = true
        elseif u and dfhack.units.isDead(u) then
            close_hunt(d, k, 'won', t, {target_dead = true}); changed = true
        elseif not u or not is(dfhack.units.isActive, u) then
            close_hunt(d, k, 'gone', t, {target_dead = false}); changed = true
        elseif caged(u) then
            close_hunt(d, k, 'caged', t, {target_dead = false}); changed = true
        elseif not sq or not kill_order_of(sq)[u.id] then
            close_hunt(d, k, 'dropped', t, {target_dead = false}); changed = true
        else
            local sol, hurt = soldiers_of(sq), 0
            for _, s in ipairs(sol) do if wounded(s) then hurt = hurt + 1 end end
            table.insert(hunts, {squad_id = h.squad_id, target_id = h.target_id, target_name = h.target_name,
                                 since_tick = h.since_tick, soldiers_at_start = h.soldiers_at_start,
                                 soldiers_now = #sol, wounded = hurt, target_alive = true,
                                 target_pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}})
        end
    end

    -- the squads
    local squads = {}
    pcall(function()
        local fort = U.fort_entity()
        local marks = M and M.shelter_marks and M.shelter_marks() or {}
        for _, sid in ipairs(fort and fort.squads or {}) do
            local sq = df.squad.find(sid)
            if sq then
                local sol = soldiers_of(sq)
                local pw = {}
                if M and M.squad_power then
                    local okp, p = pcall(M.squad_power, sq)
                    if okp and p then pw = p end
                end
                local shooters, out_n = 0, 0
                for _, s in ipairs(sol) do
                    if shoots(s) then shooters = shooters + 1 end
                    if under_sky_or_cavern(s, layers) then out_n = out_n + 1 end
                end
                local sheltering = false
                for _, o in ipairs(sq.orders) do
                    if M and M.is_shelter_order then
                        local oks, yes = pcall(M.is_shelter_order, o, sid, marks)
                        if oks and yes then sheltering = true end
                    end
                end
                local h = d.active[tostring(sid)]
                table.insert(squads, {
                    id = sid, name = (function()
                        local okn, n = pcall(dfhack.military.getSquadName, sid)
                        n = okn and n or ('squad ' .. sid)
                        return txt and txt(n) or n
                    end)(),
                    soldiers = #sol, power = pw.power or 0, armed = pw.armed or 0, armored = pw.armored or 0,
                    melee_power = pw.melee_power, ranged_power = pw.ranged_power,   -- (0.105.45, merge) H7's split
                    ranged = #sol > 0 and shooters * 2 >= #sol,
                    at_home = next(kill_order_of(sq)) == nil and out_n * 2 < math.max(#sol, 1),
                    hunting = h and h.target_id or nil,
                    sheltering = sheltering,
                    players = (M and M.ai_order) and players_orders(M, sq, sid) or nil,
                })
            end
        end
    end)

    if changed then save_state(d) end
    local history = {}
    for i = math.max(1, #d.history - HISTORY_MAX + 1), #d.history do table.insert(history, d.history[i]) end
    return {targets = targets, targets_total = total, squads = squads, hunts = hunts, history = history,
            main_group = main ~= 0 and main or nil}
end

-- --- the actions ------------------------------------------------------------------------

local function reject(msg) return {ok = false, rejected = true, error = msg} end

-- hunt_send: {squad_ids, target_id}. Every squad checked before any is sent:
-- one that can't go refuses the whole hunt (the planner picks again).
function send(opts, dry_run)
    local M = mil()
    if not M then return reject('hunt_send: ai-military could not be loaded') end
    local tid = opts.target_id
    local u = df.unit.find(tid)
    if not u then return reject('hunt_send: no unit ' .. tostring(tid) .. ' on the map') end
    if dfhack.units.isDead(u) then return reject('hunt_send: the target is dead') end
    if caged(u) then return reject('hunt_send: the target is caged or chained') end
    if not is(dfhack.units.isActive, u) then return reject('hunt_send: the target has left the map') end
    -- the report's own rule first (never a merchant, a diplomat, a pet, the
    -- fort's own or an unhurt visitor), then ai-military's as for every kill
    local hostile_wild
    pcall(function() hostile_wild = reqscript('ai-builder').hostile_wild end)
    local okf, f = pcall(facts, u, threats(), hostile_wild)
    local okk, kok = pcall(M.kill_target_ok, u)
    if not (okf and f and target_ok(f)) or not (okk and kok) then
        return reject('hunt_send: the target is no threat the squads may attack (a merchant, a diplomat, '
                      .. 'a tame animal, the fort\'s own or a visitor)')
    end
    local ids = opts.squad_ids or {}
    if #ids == 0 then return reject('hunt_send needs squad_ids') end
    local plan = {}
    for _, sid in ipairs(ids) do
        local sq = M.fort_squad(sid)
        if not sq then return reject('hunt_send: no squad ' .. tostring(sid) .. ' in this fort') end
        if players_orders(M, sq, sid) then
            return reject('hunt_send: squad ' .. tostring(sid) .. ' is on your orders')
        end
        local okp, p = pcall(M.squad_power, sq)
        local armed = okp and p and p.armed or 0
        if armed < MIN_ARMED then
            return reject(('hunt_send: squad %s has %d armed soldier(s), %d at least are sent hunting')
                          :format(tostring(sid), armed, MIN_ARMED))
        end
        local sol = soldiers_of(sq)
        local sids = {}
        for _, s in ipairs(sol) do table.insert(sids, s.id) end
        table.insert(plan, {sid = sid, soldiers = #sol, soldier_ids = sids, armed = armed})
    end
    local name = name_of(u)
    if dry_run then
        local would = {}
        for _, p in ipairs(plan) do table.insert(would, {squad_id = p.sid, soldiers = p.soldiers, armed = p.armed}) end
        return {ok = true, dry_run = true, target_id = tid, target = name, would_send = would}
    end
    local d = load_state()
    local t = now_tick()
    local sent, results = {}, {}
    for _, p in ipairs(plan) do
        local key = tostring(p.sid)
        local okr, r = pcall(M.orders, p.sid, {tid}, false)
        r = okr and r or {ok = false, error = tostring(r)}
        table.insert(results, {squad_id = p.sid, ok = r.ok == true, error = r.error})
        if r.ok then
            local old = d.active[key]
            if old and old.target_id ~= tid then
                close_hunt(d, key, 'recalled', t, {reason = 'sent at another target', target_dead = false})
            end
            if not (old and old.target_id == tid) then
                d.active[key] = {squad_id = p.sid, target_id = tid, target_name = name, since_tick = t,
                                 soldiers_at_start = p.soldiers, soldier_ids = p.soldier_ids}
            end
            table.insert(sent, p.sid)
        end
    end
    save_state(d)
    if #sent == 0 then
        return {ok = false, rejected = true, error = 'hunt_send: no squad took the order', results = results}
    end
    return {ok = true, target_id = tid, target = name, sent = sent, results = results}
end

-- hunt_recall: {squad_ids} or {target_id}, reason. The AI's orders on those
-- squads cleared (they go back to their routine and barracks), each hunt's
-- outcome kept.
function recall(opts, dry_run)
    local M = mil()
    if not M then return reject('hunt_recall: ai-military could not be loaded') end
    local d = load_state()
    local ids = {}
    if type(opts.squad_ids) == 'table' and #opts.squad_ids > 0 then
        for _, sid in ipairs(opts.squad_ids) do table.insert(ids, sid) end
    elseif opts.target_id ~= nil then
        local keys = {}
        for k, h in pairs(d.active) do
            if type(h) == 'table' and h.target_id == opts.target_id then table.insert(keys, k) end
        end
        table.sort(keys)
        for _, k in ipairs(keys) do table.insert(ids, tonumber(k)) end
        if #ids == 0 then return reject('hunt_recall: no squad is hunting ' .. tostring(opts.target_id)) end
    else
        return reject('hunt_recall needs squad_ids or target_id')
    end
    for _, sid in ipairs(ids) do
        if not M.fort_squad(sid) then return reject('hunt_recall: no squad ' .. tostring(sid) .. ' in this fort') end
    end
    local reason = type(opts.reason) == 'string' and opts.reason:sub(1, REASON_MAX) or nil
    if dry_run then
        local would = {}
        for _, sid in ipairs(ids) do
            local h = d.active[tostring(sid)]
            table.insert(would, {squad_id = sid, target_id = h and h.target_id or nil})
        end
        return {ok = true, dry_run = true, would_recall = would}
    end
    local t = now_tick()
    local results = {}
    for _, sid in ipairs(ids) do
        local okr, r = pcall(M.orders, sid, nil, true)
        r = okr and r or {ok = false, error = tostring(r)}
        local key = tostring(sid)
        local h = d.active[key]
        if h then
            local u = df.unit.find(tonumber(h.target_id) or -1)
            close_hunt(d, key, 'recalled', t, {reason = reason, target_dead = (u ~= nil and dfhack.units.isDead(u))})
        end
        table.insert(results, {squad_id = sid, ok = r.ok == true, cleared = r.cleared, error = r.error,
                               hunt = h and h.target_id or nil})
    end
    save_state(d)
    return {ok = true, recalled = ids, results = results}
end
