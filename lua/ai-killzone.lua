-- ai-killzone: kill zones at the fort's gates and cavern openings (0.105.45,
-- Phase 11 (b): defensive works where the squads can't win).
--
--   plan_corridor(e, M, bridge)  pure: the 1-wide stretch every enemy must
--                         walk on the INSIDE approach from an entrance (a run
--                         of single tiles in a walk outward from the opening:
--                         every way deeper passes each of them), 3-6 tiles,
--                         its trap tiles and a drawbridge spot
--   drop_ok(x, y, z, M)   pure: may a 1-wide channel go under the bridge (no
--                         water, magma, cavern, aquifer or fort level below,
--                         and the dig guard of ai-util says yes)
--   bypass(e, entrances)  pure: the dwarf-safe rule (as build_gatehouse:
--                         never the citizens' only way in shut without a
--                         lever that works it)
--   report()              the `killzones` section: per entrance its kind,
--                         the traps planned/built/full, the drawbridge, the
--                         fortifications (ai-siege's survey), the state; the
--                         enemies on the map and whether DF's traps work on
--                         them (TRAPAVOID); mechanisms, trap weapons, cages
--   build_killzone(...)   the action: traps placed (buildingplan waits for
--                         mechanisms and weapons), a drawbridge flat or over
--                         a channel dug first (one step a call: channel, the
--                         ramp it leaves removed, the bridge), a lever
--   reset_cage_traps(id)  full cages in the zone's cage traps: DF itself
--                         hauls them to an animal stockpile and loads an
--                         empty cage; this says what that waits for
--
-- How often enemies came each way is the brain's: the atlas keeps it per
-- entrance (threats, deaths, kills; brain/atlas.py note_events), and
-- brain/planner_killzone.py reads it beside this section.
--
-- DF's traps: a cage trap catches anything without the TRAPAVOID caste flag
-- (big or small: titans and forgotten beasts too, unless they carry the flag);
-- weapon and stone-fall traps likewise never strike a TRAPAVOID creature.
-- Great beasts often carry it (most megabeasts, titans and forgotten beasts
-- in vanilla raws): the report reads the flag from each enemy's caste raws
-- and says so, and the brain builds only the drawbridge for those. Traps
-- never fire on the fort's own citizens, tame animals or friendly visitors.
--
-- Nothing here touches the player's own: placing goes through ai-gates'
-- place (it refuses an occupied tile), the bridge and lever carry the AI's
-- names, and the records (site data) hold only what the AI placed.
--@ module = true

local U = reqscript('ai-util')

KZ_KEY = 'ai-overseer/killzones'       -- {["x,y,z" of the entrance] = record}
CORRIDOR_MIN, CORRIDOR_MAX = 3, 6       -- the 1-wide stretch's length, and traps in it at most
GATE_GAP = 2            -- the first tile behind a gate stays free (an inner door may go there; as trap_tiles)
SEARCH_DEPTH = 24       -- tiles in from the opening looked at
SEARCH_TILES = 6000     -- tiles walked at most for one entrance
BRIDGE_REACH = 7        -- a drawbridge at most this far in: the gate scan (ai-gates near(): 8 tiles) counts it the entrance's gate
ENTRANCES_MAX = 8
NEAR_ENTRANCE = 40      -- an enemy this near an entrance (tiles, a level counts 3) is listed as coming that way
THREATS_MAX = 20
BRIDGE_NAME = 'AI killzone bridge'
TRAP_KEYS = {cage = 'Tc', stonefall = 'Ts', weapon = 'Tw'}
KINDS = {cage = true, weapon = true, stonefall = true, mixed = true}
BRIDGE_DIR = {['1,0'] = 'gd', ['-1,0'] = 'ga', ['0,1'] = 'gx', ['0,-1'] = 'gw'}   -- raises toward the outside (as the gatehouse's)
-- rock the drop's walls may be dug in (never a construction, a cavern's feature or the deep)
NATURAL = {STONE = true, MINERAL = true, SOIL = true, LAVA_STONE = true}
FLOOR_SHAPES = {FLOOR = true, SHRUB = true, SAPLING = true, BOULDER = true, PEBBLES = true, TWIG = true}

-- The modules this one leans on, through functions the tests replace.
function gates() return reqscript('ai-gates') end
function siege_mod() return reqscript('ai-siege') end
function builder() return reqscript('ai-builder') end

local function key3(x, y, z) return ('%d,%d,%d'):format(x, y, z) end

---------------------------------------------------------------------------
-- The corridor (pure: reads the map only through M)
--
-- M = {T = fn(x, y, z) -> tile or nil ({walk, shape, outside, liquid,
-- occupied, hidden, feature, special, aquifer, material}), moves =
-- fn(x, y, z, t, visit(nx, ny, nz)) (ai-gates' walking moves), key, unkey
-- (ai-gates' key), inside = {key = true} (the fort's inside; nil: any
-- walkable tile under a roof), starts = {{x, y, z}} (where the citizens are),
-- road = {key = true} (the depot's wagon road: no trap on it), floor =
-- {shape = true}, dig_forbidden = fn(x, y, z) -> why or nil}
---------------------------------------------------------------------------

local function orth_dir(ax, ay, az, bx, by, bz)
    if az ~= bz then return nil end
    local dx, dy = bx - ax, by - ay
    if math.abs(dx) + math.abs(dy) ~= 1 then return nil end
    return dx, dy
end

-- The walk outward from the opening: dist[key], layers[d] = {keys}, the
-- last layer known whole, and whether the walk stopped short.
function walk_in(e, M)
    local key, unkey, T = M.key, M.unkey, M.T
    local function in_fort(k, t)
        if M.inside then return M.inside[k] == true end
        return t and t.walk and not t.outside
    end
    local dist, layers, queue = {}, {[0] = {}}, {}
    local function seed(k)
        if dist[k] == nil then
            dist[k] = 0
            queue[#queue + 1] = k
            table.insert(layers[0], k)
        end
    end
    for _, k in ipairs(e.inside_list or {}) do seed(k) end
    for _, b in ipairs(e.equipment or {}) do
        if b.x1 and b.x2 and b.y1 and b.y2 and b.z then
            for x = b.x1, b.x2 do for y = b.y1, b.y2 do seed(key(x, y, b.z)) end end
        end
    end
    if #queue == 0 and e.x and e.y and e.z then seed(key(e.x, e.y, e.z)) end
    local head, whole, short = 1, SEARCH_DEPTH, false
    while head <= #queue do
        local k = queue[head]
        head = head + 1
        local d = dist[k]
        if #queue > SEARCH_TILES then
            whole, short = math.min(whole, d), true      -- layers past d only partly walked
            break
        end
        if d >= SEARCH_DEPTH then
            short = true
        else
            local x, y, z = unkey(k)
            local t = T(x, y, z)
            if t then
                M.moves(x, y, z, t, function(nx, ny, nz)
                    local nk = key(nx, ny, nz)
                    if dist[nk] ~= nil then return end
                    local nt = T(nx, ny, nz)
                    if not (nt and nt.walk and not nt.hidden and in_fort(nk, nt)) then return end
                    dist[nk] = d + 1
                    layers[d + 1] = layers[d + 1] or {}
                    table.insert(layers[d + 1], nk)
                    queue[#queue + 1] = nk
                end)
            end
        end
    end
    local deepest = 0
    for d in pairs(layers) do if d > deepest then deepest = d end end
    return dist, layers, math.min(whole, deepest), short
end

-- Is the way past depth d where the citizens are? A citizen farther in than
-- d, or one the walk never reached because it stopped short. No citizens
-- known: the way goes on (a layer past d) is enough.
local function citizens_beyond(d, dist, layers, short, M)
    local starts = M.starts or {}
    if #starts == 0 then return layers[d + 1] ~= nil and #layers[d + 1] > 0 end
    for _, p in ipairs(starts) do
        local ds = dist[M.key(p.x, p.y, p.z)]
        if (ds and ds > d) or (ds == nil and short) then return true end
    end
    return false
end

-- The corridor for entrance e: {tiles = {{x, y, z, d}} (trap tiles, the
-- outermost first), bridge = {x, y, z, dir, d} or nil, bridge_why, from, to
-- (its depths), length (the stretch's tiles)}, or nil and why.
function plan_corridor(e, M, want_bridge)
    local floor = M.floor or FLOOR_SHAPES
    local dist, layers, whole, short = walk_in(e, M)
    local function usable(k)
        local x, y, z = M.unkey(k)
        local t = M.T(x, y, z)
        return t and floor[t.shape] and not t.liquid and not t.occupied and not t.hidden
            and not (M.road and M.road[k]) or false
    end
    local why = 'no 1-wide stretch every enemy must walk within ' .. SEARCH_DEPTH .. ' tiles of the opening'
    local d = GATE_GAP
    while d < whole do
        if layers[d] and #layers[d] == 1 then
            local d1, d2 = d, d
            while d2 + 1 < whole and layers[d2 + 1] and #layers[d2 + 1] == 1 do d2 = d2 + 1 end
            d = d2 + 1
            local goes_on = layers[d2 + 1] and #layers[d2 + 1] > 0
            if d2 - d1 + 1 < CORRIDOR_MIN then
                why = ('the 1-wide stretch %d tiles in is only %d long (%d wanted)'):format(d1, d2 - d1 + 1, CORRIDOR_MIN)
            elseif not goes_on or not citizens_beyond(d2, dist, layers, short, M) then
                why = ('the 1-wide stretch %d tiles in leads nowhere the citizens are (a dead end)'):format(d1)
            else
                local plan = {tiles = {}, from = d1, to = d2, length = d2 - d1 + 1}
                local bridge_at
                if want_bridge then
                    plan.bridge_why = ('no straight tile in the stretch within %d tiles of the opening'):format(BRIDGE_REACH)
                    for dd = d1, math.min(d2, BRIDGE_REACH) do
                        local k = layers[dd][1]
                        local x, y, z = M.unkey(k)
                        if usable(k) then
                            -- straight: one way in on the outer side, one on to the inner, in line
                            local px, py, pz, ox, oy
                            for _, pk in ipairs(layers[dd - 1] or {}) do
                                local ax, ay, az = M.unkey(pk)
                                local dx, dy = orth_dir(ax, ay, az, x, y, z)
                                if dx and not ox then px, py, pz, ox, oy = ax, ay, az, dx, dy end
                            end
                            local nk = layers[dd + 1] and layers[dd + 1][1]
                            local nx, ny, nz
                            if nk and #layers[dd + 1] == 1 then nx, ny, nz = M.unkey(nk) end
                            local ix, iy = nil, nil
                            if nx then ix, iy = orth_dir(x, y, z, nx, ny, nz) end
                            if ox and ix and ix == ox and iy == oy then
                                -- raises toward the outside (the way the enemy comes from)
                                plan.bridge = {x = x, y = y, z = z, d = dd, dir = BRIDGE_DIR[(-ox) .. ',' .. (-oy)]}
                                plan.bridge_why = nil
                                bridge_at = dd
                                break
                            end
                        end
                    end
                end
                for dd = d1, d2 do
                    local k = layers[dd][1]
                    if (not bridge_at or dd > bridge_at) and usable(k) and #plan.tiles < CORRIDOR_MAX then
                        local x, y, z = M.unkey(k)
                        table.insert(plan.tiles, {x = x, y = y, z = z, d = dd})
                    end
                end
                if #plan.tiles > 0 or plan.bridge then return plan end
                why = ('the 1-wide stretch %d tiles in has no free floor for traps (stairs, ramps or buildings)'):format(d1)
            end
        else
            d = d + 1
        end
    end
    if short and whole < GATE_GAP + CORRIDOR_MIN then
        why = 'the way in branches too much to walk (' .. SEARCH_TILES .. ' tiles)'
    end
    return nil, why
end

-- May a channel go under (x, y, z), for a drawbridge over a drop? The tile
-- below must be natural rock (it becomes the pit, its ramp removed), the one
-- under that solid, none of the eight beside the pit walkable (a level of
-- the fort below would open into it), and nowhere water, magma, an
-- aquifer, a cavern or the deep (ai-util's dig guard). Returns true, or
-- false and why.
function drop_ok(x, y, z, M)
    local T = M.T
    local here = T(x, y, z)
    if not here then return false, 'the tile could not be read' end
    if here.aquifer then return false, 'an aquifer' end
    local below = T(x, y, z - 1)
    if not below then return false, 'the level below could not be read' end
    if below.shape ~= 'WALL' or not NATURAL[below.material] then
        return false, ('below is %s, not natural rock'):format(tostring(below.shape):lower())
    end
    if below.liquid or below.aquifer then return false, 'water below (an aquifer or a flow)' end
    if below.feature or below.special then return false, 'a cavern or the deep below' end
    local under = T(x, y, z - 2)
    if not under or under.shape ~= 'WALL' or under.liquid or under.feature or under.special then
        return false, 'two levels down is not solid rock (a cavern, water or a dug level)'
    end
    for dy = -1, 1 do
        for dx = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                local n = T(x + dx, y + dy, z - 1)
                if not n then return false, 'beside the pit could not be read' end
                if n.liquid or n.aquifer then return false, 'water or magma beside the pit' end
                if n.feature or n.special then return false, 'a cavern beside the pit' end
                if n.walk or n.shape ~= 'WALL' then return false, 'an open tile beside the pit (a level below)' end
            end
        end
    end
    if M.dig_forbidden then
        for _, zz in ipairs({z, z - 1}) do
            local why = M.dig_forbidden(x, y, zz)
            if why then return false, 'the dig guard: ' .. tostring(why) end
        end
    end
    return true
end

-- The dwarf-safe rule (as build_gatehouse): a drawbridge that can shut the
-- citizens' only way in goes up only with a lever that works it (placed with
-- it), and stands lowered; a channel (which cuts the way until its bridge is
-- built) only where the citizens have another way in. A cavern opening is
-- never the citizens' way in (they come in from the surface). Traps never
-- fire on citizens. {channel = bool, lever_needed = bool, why}
function bypass(e, entrances)
    if e.kind == 'cavern' then
        return {channel = true, lever_needed = false, why = 'a cavern opening: the citizens come in from the surface'}
    end
    local others = 0
    for _, o in ipairs(entrances or {}) do
        if o.id ~= e.id and o.kind ~= 'cavern' then others = others + 1 end
    end
    if others > 0 then
        return {channel = true, lever_needed = true,
                why = ('%d other way(s) in from the surface while the channel waits for its bridge'):format(others)}
    end
    return {channel = false, lever_needed = true,
            why = 'the citizens\' only way in: no channel (it would cut them off until its bridge stands); '
                .. 'the drawbridge stands on the floor, lowered, worked by a lever'}
end

-- The kinds of the n traps, outermost first: cage first (it holds what it
-- catches); mixed: cages in the outer half, weapon traps behind.
function trap_kinds(kind, n)
    local out = {}
    for i = 1, n do
        if kind == 'mixed' then out[i] = (i <= math.ceil(n / 2)) and 'cage' or 'weapon'
        else out[i] = kind end
    end
    return out
end

---------------------------------------------------------------------------
-- The game: the map through ai-gates, records, buildings
---------------------------------------------------------------------------

-- The map for plan_corridor and drop_ok, read through ai-gates (its cache
-- reset: the map may have changed since its scan). Tests replace this.
function game_map(G, starts)
    G = G or gates()
    G.cache, G.edge_cache = {}, {}
    local road = {}
    pcall(function() road = G.deep_road_keys(false) or {} end)
    return {T = G.T, moves = G.moves, key = G.key, unkey = G.unkey, inside = (G.GATES or {}).inside,
            starts = starts or {}, road = road, floor = G.DOOR_GROUND or FLOOR_SHAPES,
            dig_forbidden = U.dig_forbidden}
end

function records()
    local d = U.site_get(KZ_KEY, {})
    return type(d) == 'table' and d or {}
end

local function save_records(d) U.site_put(KZ_KEY, d) end

-- The record of entrance e: its own spot, or within 3 tiles on its level
-- (walls move an entrance's first tile a little, as the brain's _near_spot).
function record_for(e, recs)
    recs = recs or records()
    local exact = recs[key3(e.x, e.y, e.z)]
    if type(exact) == 'table' then return exact, key3(e.x, e.y, e.z) end
    for k, r in pairs(recs) do
        local x, y, z = tostring(k):match('^(-?%d+),(-?%d+),(-?%d+)$')
        x, y, z = tonumber(x), tonumber(y), tonumber(z)
        if type(r) == 'table' and z == e.z and x and math.abs(x - e.x) <= 3 and math.abs(y - e.y) <= 3 then
            return r, k
        end
    end
    return nil
end

-- What stands at a tile: {kind = 'cage'|'weapon'|'stonefall'|'lever'|'bridge'|..., id, built, full, raised}.
-- Tests replace this.
function building_info(x, y, z)
    local out
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if not b then return end
        out = {id = b.id}
        pcall(function() out.built = b:getBuildStage() >= b:getMaxBuildStage() end)
        local ty = b:getType()
        if ty == df.building_type.Trap then
            local tt = b.trap_type
            out.kind = (tt == df.trap_type.CageTrap and 'cage') or (tt == df.trap_type.StoneFallTrap and 'stonefall')
                or (tt == df.trap_type.WeaponTrap and 'weapon') or (tt == df.trap_type.Lever and 'lever') or 'trap'
            if out.kind == 'cage' then
                -- (as the hazards report: a cage holding a creature is a catch)
                for _, ci in ipairs(b.contained_items) do
                    local it = ci.item
                    if it:getType() == df.item_type.CAGE
                            and dfhack.items.getGeneralRef(it, df.general_ref_type.CONTAINS_UNIT) then
                        out.full = true
                        break
                    end
                end
            end
        elseif ty == df.building_type.Bridge then
            out.kind = 'bridge'
            pcall(function() out.raised = b.gate_flags.raised == true end)
            pcall(function() out.name = tostring(b.name or '') end)
            pcall(function()
                local l = gates().lever_links()[b.id]
                out.linked = l ~= nil and #l > 0
            end)
        else
            out.kind = tostring(df.building_type[ty] or ty):lower()
        end
    end)
    return out
end

-- A tile's shape and dig mark now (fresh, not the scan's cache): ai-siege's tile. Tests replace this.
function tile_now(x, y, z)
    local ok, t = pcall(function() return siege_mod().tile(x, y, z) end)
    return ok and t or nil
end

-- The ai-siege survey of an entrance: fortifications and the posts behind them.
local function fort_survey(e, G)
    local S = siege_mod()
    local memo = {}
    local function T(x, y, z)
        local k = key3(x, y, z)
        local v = memo[k]
        if v == nil then v = S.tile(x, y, z) or false; memo[k] = v end
        return v or nil
    end
    local ok, row = pcall(S.survey, e, (G.GATES or {}).inside or {}, T, {})
    if ok and type(row) == 'table' then return row end
    return nil
end

---------------------------------------------------------------------------
-- The enemies and the supplies
---------------------------------------------------------------------------

local function is(f, u)
    local ok, v = pcall(f, u)
    return ok and v == true
end

-- Does DF's trap leave this creature alone? Its caste's TRAPAVOID flag (the
-- unit's copy first, then the caste raws). nil when neither can be read.
function trap_avoid(u)
    local ok, v = pcall(function() return u.enemy.caste_flags.TRAPAVOID end)
    if ok and v ~= nil then return v == true end
    local okc, c = pcall(function() return df.creature_raw.find(u.race).caste[u.caste].flags.TRAPAVOID end)
    if okc and c ~= nil then return c == true end
    return nil
end

local function nearest_entrance(pos, entrances)
    local best, best_d
    for _, e in ipairs(entrances) do
        if e.x and e.y and e.z then
            local d = math.abs(pos.x - e.x) + math.abs(pos.y - e.y) + 3 * math.abs(pos.z - e.z)
            if d <= NEAR_ENTRANCE and (not best_d or d < best_d) then best, best_d = e, d end
        end
    end
    return best, best_d
end

function threats(entrances, txt)
    local out = {}
    local units = (U.REPORT_CTX and U.units_active) and U.units_active() or df.global.world.units.active
    for _, u in ipairs(units) do
        if #out >= THREATS_MAX then break end
        if not (u.flags1.caged or u.flags1.chained) and not is(dfhack.units.isDead, u)
                and is(dfhack.units.isActive, u) and not is(dfhack.units.isCitizen, u)
                and (is(dfhack.units.isDanger, u) or is(dfhack.units.isInvader, u)) then
            local pos = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
            local row = {id = u.id, great = is(dfhack.units.isGreatDanger, u) or nil,
                         invader = is(dfhack.units.isInvader, u) or nil, trapavoid = trap_avoid(u), pos = pos}
            pcall(function() row.name = (txt or tostring)(dfhack.units.getReadableName(u)) end)
            local e, d = nearest_entrance(pos, entrances)
            if e then row.entrance_id, row.distance = e.id, d end
            table.insert(out, row)
        end
    end
    return out
end

local function count_free(kind)
    local n = 0
    pcall(function()
        for _, it in ipairs(df.global.world.items.other[kind]) do
            if U.item_free(it, {}) then n = n + 1 end
        end
    end)
    return n
end

local function mechanics()
    local n = 0
    pcall(function()
        local lab = df.unit_labor.MECHANIC
        for _, u in ipairs(U.citizens(true)) do
            local ok, has = pcall(function() return u.status.labors[lab] end)
            if ok and has and u.military.squad_id < 0 then n = n + 1 end
        end
    end)
    return n
end

---------------------------------------------------------------------------
-- The section
---------------------------------------------------------------------------

-- The entrances the AI holds (gated or open; the surface ones and the cavern
-- openings), at most ENTRANCES_MAX: cavern openings and gated ones first.
local function held_entrances(G)
    local list = {}
    for _, e in ipairs((G.GATES or {}).entrances or {}) do
        if e.x and e.y and e.z then table.insert(list, e) end
    end
    table.sort(list, function(a, b)
        if (a.sealed == true) ~= (b.sealed == true) then return a.sealed == true end
        return (a.id or 0) < (b.id or 0)
    end)
    while #list > ENTRANCES_MAX do table.remove(list) end
    return list
end

-- What stands of a record now: traps built and full, the bridge.
function record_state(rec)
    local st = {planned = 0, built = 0, full = 0, kinds = {}}
    for _, t in ipairs(type(rec.traps) == 'table' and rec.traps or {}) do
        st.planned = st.planned + 1
        local b = building_info(t.x, t.y, t.z)
        if b and (b.kind == 'cage' or b.kind == 'weapon' or b.kind == 'stonefall') then
            st.kinds[b.kind] = (st.kinds[b.kind] or 0) + 1
            if b.built then st.built = st.built + 1 end
            if b.full then st.full = st.full + 1 end
        else
            st.gone = (st.gone or 0) + 1        -- taken down (by the player, a siege) or never placed
        end
    end
    local br = type(rec.bridge) == 'table' and rec.bridge or nil
    if br then
        st.bridge = {x = br.x, y = br.y, z = br.z, channel = br.channel == true, stage = rec.stage}
        local b = building_info(br.x, br.y, br.z)
        if b and b.kind == 'bridge' then
            st.bridge.id, st.bridge.built, st.bridge.raised, st.bridge.linked = b.id, b.built == true, b.raised, b.linked
        end
        -- the next step of a channelled bridge can go: the channel dug, the ramp removed
        if rec.stage == 'channel' then
            local t = tile_now(br.x, br.y, br.z)
            st.bridge.step_ready = t ~= nil and not t.walk and t.shape ~= 'FLOOR' or nil
        elseif rec.stage == 'ramp' then
            local t = tile_now(br.x, br.y, br.z - 1)
            st.bridge.step_ready = t ~= nil and t.shape == 'FLOOR' or nil
        end
    end
    return st
end

function report(txt)
    local G = gates()
    local out = {entrances = {}, scanned = (G.GATES or {}).scanned == true}
    if not out.scanned or not (G.GATES or {}).inside then return out end
    local recs = records()
    local held = held_entrances(G)
    local starts = {}
    pcall(function() starts = G.fort_starts(G.citizen_starts()) end)
    local M = game_map(G, starts)
    for _, e in ipairs(held) do
        local row = {id = e.id, kind = e.kind, x = e.x, y = e.y, z = e.z, sealed = e.sealed == true}
        local ok, err = pcall(function()
            local rec = record_for(e, recs)
            local surv = fort_survey(e, G)
            if surv then row.fortifications, row.posts = surv.fortifications, surv.posts end
            if e.gatehouse == 'standing' then
                row.state, row.why = 'gatehouse', 'the gatehouse\'s trap corridor and drawbridge stand in front of it'
            end
            if rec then
                local st = record_state(rec)
                row.kind_traps = rec.kind
                row.traps = {planned = st.planned, built = st.built, full = st.full, gone = st.gone, kinds = st.kinds}
                row.drawbridge = st.bridge
                if rec.stage ~= 'done' then
                    row.state = 'building'
                elseif st.built < st.planned - (st.gone or 0) or (st.bridge and not st.bridge.built) then
                    row.state = 'building'
                else
                    row.state = 'standing'
                end
                row.bridge_note = rec.bridge_note
            elseif not row.state then
                local plan, why = plan_corridor(e, M, true)
                if plan then
                    row.state = 'possible'
                    row.corridor = plan.length
                    row.trap_tiles = #plan.tiles          -- (the bridge's tile apart)
                    row.depth = plan.from
                    if plan.bridge then
                        local okd, whyd = drop_ok(plan.bridge.x, plan.bridge.y, plan.bridge.z, M)
                        local bp = bypass(e, held)
                        row.drawbridge = {possible = true, channel = (okd and bp.channel) or false,
                                          why = not okd and whyd or (not bp.channel and bp.why) or nil}
                    else
                        row.drawbridge = {possible = false, why = plan.bridge_why}
                    end
                else
                    row.state, row.why = 'none', why
                end
            end
        end)
        if not ok then row.error = tostring(err):sub(1, 160) end
        table.insert(out.entrances, row)
    end
    out.threats = threats(held, txt)
    out.free_mechanisms = (function() local okm, n = pcall(G.free_mechanism_count, 200); return okm and n or nil end)()
    out.trap_weapons = count_free('TRAPCOMP') + count_free('WEAPON')
    out.trapcomps = count_free('TRAPCOMP')
    out.free_cages = count_free('CAGE')
    out.mechanics = mechanics()
    out.free_levers = (function() local okl, l = pcall(G.free_levers); return okl and #l or nil end)()
    return out
end

---------------------------------------------------------------------------
-- The actions
---------------------------------------------------------------------------

-- A lever where the dwarves are, for the bridge (as build_gatehouse): none
-- when an unlinked AI lever can work it already. Returns spot, note.
local function lever_for(G, e, starts, dry_run)
    local okw, waiting = pcall(G.lever_waiting_for, e, (G.GATES or {}).inside, G.unlinked_ai_levers())
    if okw and waiting then return nil, 'an AI gate lever stands unlinked: it works the bridge' end
    local oks, spot = pcall(G.lever_spot, starts, e)
    if not (oks and spot) then return nil, nil end
    if dry_run then return spot, nil end
    if G.place('Tl', spot) then
        G.name_at(spot, G.LEVER_NAME)
        return spot, nil
    end
    return nil, nil
end

local function place_bridge(G, br)
    local ok, why = G.place(('%s(1x1)'):format(br.dir), {x = br.x, y = br.y, z = br.z})
    if ok then G.name_at({x = br.x, y = br.y, z = br.z}, BRIDGE_NAME) end
    return ok, why
end

local function dig(text, x, y, z)
    local ok, fail = builder().qf_try('dig', {{x = x, y = y, text = text}}, z, 0, 0, false, 1, false)
    return ok, fail
end

-- One step of a channelled drawbridge: the channel dug -> its ramp removed
-- -> the bridge placed over the drop (and its lever).
local function advance(G, e, rec, rk, recs, dry_run, starts)
    local br = rec.bridge
    local out = {ok = true, entrance_id = e.id, stage = rec.stage, bridge = {x = br.x, y = br.y, z = br.z}}
    if rec.stage == 'channel' then
        local t = tile_now(br.x, br.y, br.z)
        if t and (t.walk or t.shape == 'FLOOR') then
            if t.designated then
                return {ok = false, waiting = true, error = 'the channel under the drawbridge is not dug yet'}
            end
            if dry_run then out.dry_run, out.step = true, 'channel again'; return out end
            local ok, fail = dig('h', br.x, br.y, br.z)        -- the mark was lost: again
            if not ok then return {ok = false, error = 'the channel could not be marked again (' .. tostring(fail) .. ')'} end
            out.step = 'channel marked again'
            return out
        end
        local below = tile_now(br.x, br.y, br.z - 1)
        if below and below.shape == 'RAMP' then
            if dry_run then out.dry_run, out.step = true, 'ramp'; return out end
            if not below.designated then
                local ok, fail = dig('z', br.x, br.y, br.z - 1)
                if not ok then return {ok = false, error = 'the ramp in the channel could not be marked for removal ('
                    .. tostring(fail) .. ')'} end
            end
            rec.stage = 'ramp'
            out.step = 'the channel\'s ramp marked for removal (a pit nothing climbs out of)'
        else
            rec.stage = 'ramp'
            out.step = 'no ramp left in the channel'
        end
        recs[rk] = rec
        save_records(recs)
        out.stage = rec.stage
        return out
    elseif rec.stage == 'ramp' then
        local below = tile_now(br.x, br.y, br.z - 1)
        if below and below.shape == 'RAMP' then
            return {ok = false, waiting = true, error = 'the ramp in the channel is not removed yet'}
        end
        if dry_run then out.dry_run, out.step = true, 'bridge'; return out end
        local ok, why = place_bridge(G, br)
        if not ok then return {ok = false, error = 'the game would not place the drawbridge: ' .. tostring(why)} end
        local spot, note = lever_for(G, e, starts, false)
        rec.stage = 'done'
        recs[rk] = rec
        save_records(recs)
        out.stage, out.step, out.lever, out.lever_note = 'done', 'the drawbridge placed over the drop', spot, note
        return out
    end
    return {ok = false, rejected = true, error = 'a kill zone stands there already'}
end

-- build_killzone: traps in the 1-wide stretch inside entrance `id` (n, of
-- kind cage|weapon|stonefall|mixed; 0: the drawbridge alone, for enemies
-- the traps leave alone), and a drawbridge (flat, or over a channel where
-- the rules allow one). Called again, a channelled bridge goes one step on.
function build_killzone(id, n, kind, drawbridge, dry_run, starts)
    local G = gates()
    local e = G.entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if not (G.GATES or {}).inside then return {ok = false, rejected = true, error = 'the fort is not mapped yet'} end
    kind = kind or 'cage'
    if not KINDS[kind] then return {ok = false, rejected = true, error = 'kind is cage, weapon, stonefall or mixed'} end
    n = math.max(0, math.min(CORRIDOR_MAX, math.floor(tonumber(n) or 4)))
    if n == 0 and not drawbridge then
        return {ok = false, rejected = true, error = 'nothing to build: no traps and no drawbridge'}
    end
    local recs = records()
    local rec, rk = record_for(e, recs)
    if not starts then
        starts = {}
        pcall(function() starts = G.fort_starts(G.citizen_starts()) end)
    end
    if rec then return advance(G, e, rec, rk, recs, dry_run, starts) end
    if e.gatehouse == 'standing' then
        return {ok = false, rejected = true, error = 'the gatehouse\'s trap corridor and drawbridge are its kill zone'}
    end
    local M = game_map(G, starts)
    local plan, why = plan_corridor(e, M, drawbridge == true)
    if not plan then return {ok = false, error = why} end
    local out = {ok = true, entrance_id = e.id, kind = kind, corridor = plan.length, depth = plan.from,
                 traps = 0, placed = {}}
    -- the bridge, by the dwarf-safe rule
    local br, channel
    if drawbridge and plan.bridge then
        local held = held_entrances(G)
        local bp = bypass(e, held)
        local okd, whyd = drop_ok(plan.bridge.x, plan.bridge.y, plan.bridge.z, M)
        channel = bp.channel and okd
        if not okd then out.channel_why = whyd
        elseif not bp.channel then out.channel_why = bp.why end
        if bp.lever_needed and not channel then
            -- flat on the only way in: only with a lever that can work it
            local spot, note = lever_for(G, e, starts, true)
            if not spot and not note then
                out.bridge_note = 'no drawbridge: the citizens\' only way in, and no free floor for its lever'
            else
                br = plan.bridge
            end
        else
            br = plan.bridge
        end
    elseif drawbridge then
        out.bridge_note = 'no drawbridge: ' .. tostring(plan.bridge_why)
    end
    if drawbridge and not br then
        plan = plan_corridor(e, M, false) or plan        -- no bridge after all: its tile takes a trap
    end
    local tiles = {}
    for i = 1, math.min(n, #plan.tiles) do tiles[i] = plan.tiles[i] end
    local kinds = trap_kinds(kind, #tiles)
    if dry_run then
        out.dry_run, out.traps = true, #tiles
        out.trap_kinds = kinds
        if br then out.drawbridge = {x = br.x, y = br.y, z = br.z, dir = br.dir, channel = channel or false} end
        return out
    end
    local failed, rec_traps = {}, {}
    for i, t in ipairs(tiles) do
        local ok, w = G.place(TRAP_KEYS[kinds[i]], {x = t.x, y = t.y, z = t.z})
        if ok then
            out.traps = out.traps + 1
            table.insert(rec_traps, {x = t.x, y = t.y, z = t.z, kind = kinds[i]})
        else
            table.insert(failed, kinds[i] .. ':' .. tostring(w))
        end
    end
    local stage = 'done'
    if br then
        if channel then
            local ok, fail = dig('h', br.x, br.y, br.z)
            if ok then
                stage = 'channel'
                out.drawbridge = {x = br.x, y = br.y, z = br.z, dir = br.dir, channel = true, stage = 'channel'}
            else
                channel = false
                out.channel_why = 'quickfort would not mark the channel (' .. tostring(fail) .. ')'
            end
        end
        if not channel then
            local ok, w = place_bridge(G, br)
            if ok then
                out.drawbridge = {x = br.x, y = br.y, z = br.z, dir = br.dir, channel = false}
                local spot, note = lever_for(G, e, starts, false)
                out.lever, out.lever_note = spot, note
            else
                table.insert(failed, 'bridge:' .. tostring(w))
                br = nil
            end
        end
    end
    if out.traps == 0 and not br then
        return {ok = false, error = 'nothing could be placed (' .. table.concat(failed, '; '):sub(1, 200) .. ')'}
    end
    recs[key3(e.x, e.y, e.z)] = {
        x = e.x, y = e.y, z = e.z, entrance_kind = e.kind, kind = kind, traps = rec_traps, stage = stage,
        bridge = br and {x = br.x, y = br.y, z = br.z, dir = br.dir, channel = channel == true} or nil,
        bridge_note = out.bridge_note or out.channel_why,
        tick = (function() local okt, t = pcall(U.abs_tick); return okt and t or nil end)(),
    }
    save_records(recs)
    if #failed > 0 then out.failed = table.concat(failed, '; '):sub(1, 300) end
    return out
end

-- reset_cage_traps: the zone's full cage traps. DF re-arms a cage trap by
-- itself: a hauler (Animal Hauling) carries the full cage to an animal
-- stockpile and an empty cage is loaded. So nothing is moved here; this says
-- what that waits for: an animal stockpile, empty cages. ok = false while one
-- is missing (waiting), with the count.
function reset_cage_traps(id, dry_run)
    local G = gates()
    local e = G.entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    local rec = record_for(e)
    if not rec then return {ok = false, rejected = true, error = 'no kill zone of the AI\'s at that entrance'} end
    local full, cages = 0, 0
    for _, t in ipairs(type(rec.traps) == 'table' and rec.traps or {}) do
        local b = building_info(t.x, t.y, t.z)
        if b and b.kind == 'cage' then
            cages = cages + 1
            if b.full then full = full + 1 end
        end
    end
    local piles = 0
    pcall(function()
        for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
            if sp.settings.flags.animals then piles = piles + 1 end
        end
    end)
    local free = count_free('CAGE')
    local out = {ok = true, entrance_id = e.id, cage_traps = cages, full = full, animal_piles = piles,
                 free_cages = free, dry_run = dry_run or nil,
                 note = 'DF re-arms a full cage trap itself: a hauler takes the cage to an animal stockpile and '
                     .. 'loads an empty one'}
    if full == 0 then out.note = 'no cage trap there holds a catch' return out end
    local needs = {}
    if piles == 0 then table.insert(needs, 'an animal stockpile (where full cages go)') end
    if free < full then table.insert(needs, ('%d more empty cage(s)'):format(full - free)) end
    if #needs > 0 then
        out.ok, out.waiting = false, true
        out.error = ('%d full cage trap(s) wait for %s'):format(full, table.concat(needs, ' and '))
        out.needs = needs
    end
    return out
end
