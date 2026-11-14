-- (0.105.45) A great danger sealed in a cavern, lured in and cut off.
--
-- Why: since 0.105.26 the fort locks every way into the caverns while a
-- forgotten beast (or a titan, a megabeast, a demon) is loose there
-- (ai-threats seal_cavern). A sealed beast sits in the cavern for good, and
-- the cavern's farms, trees and water with it. When the squads can't win
-- (or can't get at it) the fort lures it into a pocket on its own side of
-- the seal and cuts it off there:
--
--   * the pocket: the 1-wide way just behind one of the AI's own cavern
--     doors (an opening on the seal's record, or a door the AI placed),
--     POCKET_MIN..POCKET_MAX tiles long, on the opening's own level, with a
--     gate where it ends (the "inner gate", toward the fort). Never on the
--     underground depot's wagon road, never on a level with none of the
--     AI's own projects (when the AI has any), never a tile with a building
--     of anyone's (but the lure's own pieces);
--   * a beast that cage traps can catch (no TRAPAVOID in its caste's raws:
--     most forgotten beasts): cage traps on every pocket tile, a door as the
--     inner gate (locked). It walks in and is caught: it stays caged (the
--     AI never lets it out);
--   * a beast traps can't catch (TRAPAVOID: some titans and megabeasts): a
--     raising drawbridge on the pocket's first tile (the mouth) and another
--     as the inner gate, each on a lever of the AI's own ("AI lure lever",
--     never one of the gates' "AI gate..." levers). It walks in past the
--     lowered mouth; the mouth is raised behind it: shut in, for the
--     crossbows (an archer post, where a fortification looks into the
--     pocket) or for good.
--
-- The seal stays the seal: lure_open unlocks only this opening's door, and
-- only while nobody is down in the caverns, nobody is in or beside the
-- pocket and the inner gate is shut (refused otherwise); the record says
-- the lure holds it open (held_open: ai-threats leaves it unlocked and the
-- brain's seal rule counts it as meant), and lure_shut locks it again. The
-- gate watcher leaves an entrance with a lure's piece alone (held_ids).
--
--   report()                  the `lures` section (each pulse: cheap; the
--                             candidates' pocket plans are kept a game day)
--   build_lure(key, beast)    the next step of the pocket: its pieces
--                             placed, the levers placed, linked once built
--   lure_open(key)            the seal opened toward the pocket only
--   lure_shut(key)            the mouth raised, the seal locked, the inner
--                             gate shut; a beast caught or shut in noted
--   plan_pocket(o, tile_at, opts)   pure: the pocket behind an opening
--
-- Fields this DF may name otherwise (caste_flags.TRAPAVOID, the raws'
-- caste flags, gate_flags, door_flags, contained_items) are read in pcall.
--@module = true

local U = reqscript('ai-util')

STATE_KEY = 'ai-overseer/lure'
POCKET_MIN = 3             -- tiles of 1-wide way behind the seal, at least
POCKET_MAX = 6             -- ... and at most (the rest stays the fort's)
TRAPS_MAX = 6
RECORDS_MAX = 4            -- pockets kept on record at most
CANDIDATES_MAX = 8         -- openings looked at for a pocket, a report
LEVER_NAME = 'AI lure lever'
GATE_NAME = 'AI lure gate'
local DAY = 1200
local GREAT = {{'isForgottenBeast', 'forgotten beast'}, {'isTitan', 'titan'}, {'isMegabeast', 'megabeast'},
               {'isDemon', 'demon'}}
local FLOORISH = {FLOOR = true, SHRUB = true, SAPLING = true, BOULDER = true, PEBBLES = true, TWIG = true}
local BRIDGE_DIR = {['1,0'] = 'gd', ['-1,0'] = 'ga', ['0,1'] = 'gx', ['0,-1'] = 'gw'}
local PIECE_KEYS = {trap = 'Tc', door = 'd'}

local function okey(x, y, z) return ('%d,%d,%d'):format(x, y, z) end
local function nkey(x, y, z) return (z * 4096 + y) * 4096 + x end     -- ai-gates' own key()

function parse_key(k)
    local x, y, z = tostring(k or ''):match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
    x, y, z = tonumber(x), tonumber(y), tonumber(z)
    if x and y and z then return x, y, z end
end

local function now_tick()
    local ok, t = pcall(U.abs_tick)
    return ok and t or 0
end

-- the save's record: lures = {"x,y,z" (the opening) = {x, y, z, beast,
-- immune, tiles = {{x,y,z}}, traps = {{x,y,z}}, inner = {x,y,z,kind,dir},
-- mouth = {x,y,z,kind,dir} | nil, levers = {inner = id, mouth = id},
-- open, opened_tick, shut_tick, tick, done = {beast, how, tick}, held_beast}}
function load_state()
    local d = U.site_get(STATE_KEY, {})
    d.lures = type(d.lures) == 'table' and d.lures or {}
    return d
end

local function save_state(d) U.site_put(STATE_KEY, d) end

local function gates()
    local ok, G = pcall(reqscript, 'ai-gates')
    return ok and G or nil
end

local function threats()
    local ok, T = pcall(reqscript, 'ai-threats')
    return ok and T or nil
end

local function announce(text, color)
    pcall(function() dfhack.gui.showAnnouncement('AI Overseer: ' .. text, color or COLOR_YELLOW, true) end)
end

---------------------------------------------------------------------------
-- The pocket (pure: reads tiles through tile_at only)
---------------------------------------------------------------------------

-- tile_at(x, y, z) -> nil (off the map) or {walk, shape, cavern, outside,
-- hidden, liquid, occupied}. o: the opening {x, y, z}. opts: {immune,
-- own = {"x,y,z" = true} (the lure's own pieces: occupied is fine there),
-- avoid = {ai-gates key = true} (the depot's road), levels = {z = true} |
-- nil (the AI's own levels: nil, any)}. Returns the plan {opening, tiles,
-- traps, inner, mouth, immune, length} or nil and why.
function plan_pocket(o, tile_at, opts)
    opts = opts or {}
    local own, avoid, levels = opts.own or {}, opts.avoid or {}, opts.levels
    local ox, oy, oz = tonumber(o and o.x), tonumber(o and o.y), tonumber(o and o.z)
    if not (ox and oy and oz) then return nil, 'no opening' end
    if levels and not levels[oz] then
        return nil, 'the opening is on a level with none of the AI\'s own projects'
    end
    local function T(x, y, z) local ok, t = pcall(tile_at, x, y, z); return ok and t or nil end
    local function walkable(t) return t and t.walk and not t.hidden end
    local function fort_side(t) return walkable(t) and not t.cavern and not t.outside end
    local function good(x, y, z, t)
        local k = okey(x, y, z)
        return t and FLOORISH[t.shape] and not t.liquid and not t.cavern and not t.outside and not t.hidden
            and (not t.occupied or own[k]) and not avoid[nkey(x, y, z)]
    end
    local cav, fort = 0, {}
    for dx = -1, 1 do
        for dy = -1, 1 do
            if dx ~= 0 or dy ~= 0 then
                local t = T(ox + dx, oy + dy, oz)
                if walkable(t) and t.cavern then cav = cav + 1
                elseif fort_side(t) then table.insert(fort, {x = ox + dx, y = oy + dy, z = oz}) end
            end
        end
    end
    if cav == 0 then
        return nil, 'no cavern floor beside the opening on its level (a hatch or a stair: no pocket there)'
    end
    if #fort == 0 then return nil, 'no floor on the fort\'s side of the opening' end
    if #fort > 1 then return nil, 'the way behind the opening is wider than one tile' end
    local seen = {[okey(ox, oy, oz)] = true}
    local chain = {}
    local cur = fort[1]
    while cur and #chain <= POCKET_MAX do
        local t = T(cur.x, cur.y, cur.z)
        if not good(cur.x, cur.y, cur.z, t) then break end
        table.insert(chain, cur)
        seen[okey(cur.x, cur.y, cur.z)] = true
        local nxt = {}
        for dx = -1, 1 do
            for dy = -1, 1 do
                if dx ~= 0 or dy ~= 0 then
                    local x, y = cur.x + dx, cur.y + dy
                    if not seen[okey(x, y, cur.z)] and walkable(T(x, y, cur.z)) then
                        table.insert(nxt, {x = x, y = y, z = cur.z})
                    end
                end
            end
        end
        -- a stair or a ramp out of this tile, or a second way on: the 1-wide way ends here
        if #nxt ~= 1 then break end
        cur = nxt[1]
    end
    -- the pocket: the chain but its last tile; that one takes the inner gate
    local n = #chain
    local len = math.min(POCKET_MAX, n - 1)
    if len < POCKET_MIN then
        return nil, ('the way behind the opening is 1 tile wide for only %d tile(s) (a pocket needs %d and '
            .. 'a tile for its inner gate)'):format(math.max(0, n - 1), POCKET_MIN)
    end
    local function dir(a, b)
        local dx, dy = b.x - a.x, b.y - a.y
        return BRIDGE_DIR[dx .. ',' .. dy] or (dx ~= 0 and BRIDGE_DIR[dx .. ',0']) or BRIDGE_DIR['0,' .. dy] or 'gw'
    end
    local plan = {opening = {x = ox, y = oy, z = oz}, tiles = {}, traps = {}, immune = opts.immune == true,
                  length = len}
    for i = 1, len do table.insert(plan.tiles, {x = chain[i].x, y = chain[i].y, z = chain[i].z}) end
    local g = chain[len + 1]
    if plan.immune then
        -- the gate raises toward the pocket (its last tile), the mouth toward the opening
        plan.inner = {x = g.x, y = g.y, z = g.z, kind = 'bridge', dir = dir(g, chain[len])}
        plan.mouth = {x = chain[1].x, y = chain[1].y, z = chain[1].z, kind = 'bridge', dir = dir(chain[1], o)}
    else
        plan.inner = {x = g.x, y = g.y, z = g.z, kind = 'door'}
        for i = 1, math.min(len, TRAPS_MAX) do
            table.insert(plan.traps, {x = chain[i].x, y = chain[i].y, z = chain[i].z})
        end
    end
    return plan
end

-- Mechanisms a plan needs: one a trap, one a lever, two a link.
function mechanisms_needed(plan)
    local n = #(plan.traps or {})
    if plan.mouth then n = n + 3 end
    if plan.inner and plan.inner.kind == 'bridge' then n = n + 3 end
    return n
end

-- Pure: the lure's phase from what stands and what the beast does.
-- r: {planned, built, open, caught, in_pocket, shut, done}
function phase_of(r)
    if not r.planned then return 'idle' end
    if r.done then return 'done' end
    if r.caught then return 'caught' end
    if r.open then return 'open' end
    if r.in_pocket and r.shut then return 'shut_in' end
    if not r.built then return 'building' end
    return 'ready'
end

---------------------------------------------------------------------------
-- The game's side
---------------------------------------------------------------------------

tile_hook = nil      -- tests replace these
place_hook = nil

function game_tile(x, y, z)
    if tile_hook then return tile_hook(x, y, z) end
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return nil end
    local des, occ = dfhack.maps.getTileFlags(x, y, z)
    if not des then return nil end
    local attrs = df.tiletype.attrs[tt]
    return {walk = df.tiletype_shape.attrs[attrs.shape].walkable == true, shape = df.tiletype_shape[attrs.shape],
            cavern = (des.feature_global or des.feature_local) and true or false, outside = des.outside,
            hidden = des.hidden, liquid = des.flow_size > 0,
            occupied = occ ~= nil and occ.building ~= df.tile_building_occ.None}
end

local function place(key_text, pos)
    if place_hook then return place_hook(key_text, pos) end
    local ok, stats = pcall(function()
        return reqscript('quickfort').apply_blueprint({mode = 'build', data = {[pos.z] = {[pos.y] = {[pos.x] = key_text}}},
                                                      pos = {x = 0, y = 0, z = 0}, command = 'run'})
    end)
    if not ok then return false, tostring(stats):sub(1, 80) end
    if stats.build_designated and stats.build_designated.value > 0 then return true end
    return false, 'not placed'
end

local function find_building(id)
    if id == nil then return nil end
    local ok, b = pcall(df.building.find, tonumber(id))
    return ok and b or nil
end

local function building_at(p)
    local ok, b = pcall(dfhack.buildings.findAtTile, xyz2pos(p.x, p.y, p.z))
    return ok and b or nil
end

local function built(b)
    local ok, yes = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    return ok and yes or false
end

local function kind_of(b)
    local ok, k = pcall(function() return df.building_type[b:getType()] end)
    return ok and k or nil
end

-- Can cage traps catch it? false: its caste has TRAPAVOID (traps don't
-- trigger for it); true: they can; nil: unread.
function trap_immune(u)
    local ok, f = pcall(function() return u.enemy.caste_flags.TRAPAVOID end)
    if ok and f ~= nil then return f == true end
    local okr, fr = pcall(function()
        return df.creature_raw.find(u.race).caste[u.caste].flags.TRAPAVOID
    end)
    if okr and fr ~= nil then return fr == true end
    return nil
end

-- A building destroyer (it can break a door), from the caste's raws; nil unread.
function destroyer(u)
    local ok, v = pcall(function()
        local c = df.creature_raw.find(u.race).caste[u.caste]
        return c.flags.BUILDINGDESTROYER
    end)
    if ok and v ~= nil then return v == true end
    return nil
end

local function great_kind(u)
    for _, k in ipairs(GREAT) do
        local ok, v = pcall(dfhack.units[k[1]], u)
        if ok and v then return k[2] end
    end
end

local function on_cavern(p)
    local ok, cave = pcall(function()
        local des = dfhack.maps.getTileFlags(p.x, p.y, p.z)
        return des and (des.feature_global or des.feature_local) and true or false
    end)
    return ok and cave or false
end

local function citizens()
    local ok, l = pcall(function()
        if U.REPORT_CTX and U.citizens then return U.citizens(true) end
        return dfhack.units.getCitizens(true)
    end)
    return ok and l or {}
end

-- The citizens down on cavern tiles: {n, first (a name)}
function cavern_citizens()
    local n, first = 0, nil
    for _, u in ipairs(citizens()) do
        if on_cavern(u.pos) then
            n = n + 1
            if not first then
                local ok, name = pcall(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end)
                first = ok and name or ('unit ' .. tostring(u.id))
            end
        end
    end
    return {n = n, first = first}
end

-- Every tile of a lure: the opening, the pocket, the mouth and the inner gate.
local function lure_tiles(rec)
    local out = {{x = rec.x, y = rec.y, z = rec.z}}
    for _, p in ipairs(rec.tiles or {}) do table.insert(out, p) end
    if rec.inner then table.insert(out, rec.inner) end
    return out
end

-- Citizens in or next to the pocket (a tile off, a level up or down counted): {n, first}
function citizens_near(rec)
    local n, first = 0, nil
    local tiles = lure_tiles(rec)
    for _, u in ipairs(citizens()) do
        local p = u.pos
        for _, t in ipairs(tiles) do
            if math.abs(p.z - t.z) <= 1 and math.abs(p.x - t.x) <= 1 and math.abs(p.y - t.y) <= 1 then
                n = n + 1
                if not first then first = ('unit %d at x%d y%d z%d'):format(u.id, p.x, p.y, p.z) end
                break
            end
        end
    end
    return {n = n, first = first}
end

local function in_pocket(rec, p)
    if not p then return false end
    for _, t in ipairs(rec.tiles or {}) do
        -- (the mouth's tile is the bridge itself: beyond it is in)
        local mouth = rec.mouth and t.x == rec.mouth.x and t.y == rec.mouth.y and t.z == rec.mouth.z
        if not mouth and p.x == t.x and p.y == t.y and p.z == t.z then return true end
    end
    return false
end

-- A piece's state: {built, shut, id}. A door is shut when locked; a bridge when raised (or rising).
local function piece_state(p)
    local b = p and building_at(p)
    if not b then return {present = false} end
    local out = {present = true, id = b.id, built = built(b), kind = kind_of(b)}
    if out.kind == 'Bridge' then
        local ok, up = pcall(function() local f = b.gate_flags; return (f.raised and not f.lowering) or f.raising end)
        out.shut = ok and up and true or false
    else
        local ok, f = pcall(function() return b.door_flags.forbidden end)
        out.shut = ok and f == true or false
    end
    return out
end

-- A cage trap's state: {built, loaded (an empty cage in it), full (one with a creature)}
local function trap_state(p)
    local b = building_at(p)
    if not b or kind_of(b) ~= 'Trap' then return {present = false} end
    local out = {present = true, id = b.id, built = built(b), loaded = false, full = false}
    pcall(function()
        for _, ci in ipairs(b.contained_items) do
            local it = ci.item
            if it:getType() == df.item_type.CAGE then
                if dfhack.items.getGeneralRef(it, df.general_ref_type.CONTAINS_UNIT) then out.full = true
                else out.loaded = true end
            end
        end
    end)
    return out
end

-- Is a lever linked to this building?
local function lever_linked(G, lever_id, target_id)
    if not (G and lever_id and target_id) then return false end
    local ok, links = pcall(G.lever_links)
    if not ok or type(links) ~= 'table' then return false end
    for _, l in ipairs(links[target_id] or {}) do if l == lever_id then return true end end
    return false
end

-- The AI-held cavern openings (ai-threats' record, a door that the seal
-- holds or the AI placed): {{key, x, y, z, door_id}}.
function held_openings()
    local out = {}
    local T, G = threats(), gates()
    if not T then return out end
    local okd, d = pcall(T.load_state)
    if not okd or type(d) ~= 'table' or type(d.openings) ~= 'table' then return out end
    local holds = {ids = {}}
    pcall(function() holds = T.seal_holds(d) end)
    for _, o in pairs(d.openings) do
        if type(o) == 'table' and o.kind ~= 'well' and tonumber(o.x) then
            local b = building_at(o)
            if b and kind_of(b) == 'Door' then
                local mine = holds.ids and holds.ids[b.id]
                if not mine and G and G.ai_planned_building then
                    local ok, yes = pcall(G.ai_planned_building, b)
                    mine = ok and yes
                end
                if mine then
                    table.insert(out, {key = okey(o.x, o.y, o.z), x = o.x, y = o.y, z = o.z, door_id = b.id})
                end
            end
        end
    end
    table.sort(out, function(a, b) return a.key < b.key end)
    return out
end

-- The AI's own levels ({z = true}), or nil when none are known (no limit then).
local function own_levels()
    local ok, list = pcall(function() return reqscript('ai-builder').registry_report() end)
    if not ok or type(list) ~= 'table' then return nil end
    local out, any = {}, false
    for _, p in ipairs(list) do
        if type(p) == 'table' and tonumber(p.z) then out[tonumber(p.z)] = true; any = true end
    end
    return any and out or nil
end

local function plan_opts(rec_or_nil, immune)
    local own = {}
    if rec_or_nil then for _, p in ipairs(lure_tiles(rec_or_nil)) do own[okey(p.x, p.y, p.z)] = true end end
    local avoid = {}
    local G = gates()
    if G and G.deep_road_keys then
        local ok, road = pcall(G.deep_road_keys, true)
        if ok and type(road) == 'table' then avoid = road end
    end
    return {immune = immune, own = own, avoid = avoid, levels = own_levels()}
end

-- The great dangers loose or caged: {{id, name, kind, caged, immune, destroyer, cavern, x, y, z}}
function great_beasts()
    local out = {}
    local ok, units = pcall(function()
        if U.REPORT_CTX and U.units_active then return U.units_active() end
        return df.global.world.units.active
    end)
    if not ok then return out end
    for _, u in ipairs(units) do
        local okd, dead = pcall(dfhack.units.isDead, u)
        if okd and not dead then
            local kind = great_kind(u)
            if kind then
                local p = {x = u.pos.x, y = u.pos.y, z = u.pos.z}
                local okn, name = pcall(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end)
                local caged = false
                pcall(function() caged = (u.flags1.caged or u.flags1.chained) and true or false end)
                table.insert(out, {id = u.id, name = okn and name or kind, kind = kind, caged = caged or nil,
                                   immune = trap_immune(u), destroyer = destroyer(u),
                                   cavern = on_cavern(p) or nil, x = p.x, y = p.y, z = p.z})
                if #out >= 10 then break end
            end
        end
    end
    return out
end

local function unit_of(id)
    if id == nil then return nil end
    local ok, u = pcall(df.unit.find, tonumber(id))
    return ok and u or nil
end

-- Does the pocket hold a live beast shut in it?
local function holding(rec)
    if type(rec) ~= 'table' or rec.held_beast == nil then return false end
    local u = unit_of(rec.held_beast)
    local okd, dead = pcall(function() return dfhack.units.isDead(u) end)
    return u ~= nil and okd and not dead
end

-- One lure's facts and phase (rec: its record).
function lure_row(key, rec, G)
    G = G or gates()
    local row = {key = key, opening = {x = rec.x, y = rec.y, z = rec.z}, beast_id = rec.beast,
                 immune = rec.immune == true, planned = true, length = #(rec.tiles or {}), open = rec.open == true}
    local u = unit_of(rec.beast)
    local alive = false
    if u then
        local okd, dead = pcall(dfhack.units.isDead, u)
        alive = okd and not dead
        row.beast_kind = great_kind(u)
        pcall(function() row.beast_name = dfhack.df2utf(dfhack.units.getReadableName(u)) end)
        pcall(function() row.caught = (u.flags1.caged or u.flags1.chained) and true or nil end)
        row.beast_in_pocket = alive and in_pocket(rec, u.pos) or nil
        row.beast_in_cavern = alive and on_cavern(u.pos) or nil
    end
    row.beast_gone = (rec.beast ~= nil and not alive) or nil
    local pieces, done = 0, 0
    row.traps, row.traps_built, row.traps_loaded, row.traps_full = #(rec.traps or {}), 0, 0, 0
    for _, p in ipairs(rec.traps or {}) do
        local s = trap_state(p)
        pieces = pieces + 1
        if s.built then done = done + 1; row.traps_built = row.traps_built + 1 end
        if s.loaded then row.traps_loaded = row.traps_loaded + 1 end
        if s.full then row.traps_full = row.traps_full + 1 end
    end
    rec.levers = type(rec.levers) == 'table' and rec.levers or {}
    for _, role in ipairs({'inner', 'mouth'}) do
        local p = rec[role]
        if p then
            local s = piece_state(p)
            local r = {kind = p.kind, built = s.built or false, shut = s.shut or false, id = s.id}
            pieces = pieces + 1
            if s.built then done = done + 1 end
            if p.kind == 'bridge' then
                local lid = rec.levers[role]
                local lv = find_building(lid)
                r.lever = lid
                r.lever_built = lv and built(lv) or false
                r.linked = lv and s.id and lever_linked(G, lid, s.id) or false
                pieces = pieces + 2
                if r.lever_built then done = done + 1 end
                if r.linked then done = done + 1 end
            end
            row[role] = r
        end
    end
    local seal = building_at(rec)
    if seal then
        row.seal = {id = seal.id, locked = false}
        pcall(function() row.seal.locked = seal.door_flags.forbidden == true end)
    end
    row.pieces, row.pieces_built = pieces, done
    row.built = done >= pieces and pieces > 0
    if rec.open and rec.opened_tick then row.open_ticks = math.max(0, now_tick() - rec.opened_tick) end
    if rec.done then row.done = {beast = rec.done.beast, how = rec.done.how, days = rec.done.tick and
                                 (now_tick() - rec.done.tick) // DAY or nil} end
    local finished = rec.done and rec.done.beast == rec.beast
    local mouth_shut = (not rec.mouth) or (row.mouth and row.mouth.shut)
    row.phase = phase_of({planned = true, done = finished, caught = row.caught and not finished,
                          open = rec.open == true, in_pocket = row.beast_in_pocket, shut = mouth_shut,
                          built = row.built})
    row.held_beast = rec.held_beast
    local near = citizens_near(rec)
    row.citizens_near = near.n
    return row
end

CAND_CACHE = CAND_CACHE or nil

-- The `lures` section: {lures = [rows], candidates = [{key, x, y, z, fits,
-- why, length}], beasts = [great dangers], held_beasts = [ids], cavern_citizens,
-- mechanisms}
function report()
    local d = load_state()
    local G = gates()
    local out = {lures = {}, candidates = {}, beasts = great_beasts(), held_beasts = {}}
    local keys = {}
    for k in pairs(d.lures) do table.insert(keys, k) end
    table.sort(keys)
    for _, k in ipairs(keys) do
        local rec = d.lures[k]
        if type(rec) == 'table' then
            local ok, row = pcall(lure_row, k, rec, G)
            table.insert(out.lures, ok and row or {key = k, error = tostring(row):sub(1, 160)})
            if rec.held_beast ~= nil and ok and not row.beast_gone then table.insert(out.held_beasts, rec.held_beast) end
        end
    end
    -- the openings a pocket could go behind: worked out once a game day
    local day = now_tick() // DAY
    if not (type(CAND_CACHE) == 'table' and CAND_CACHE.day == day) then
        local list = {}
        for i, o in ipairs(held_openings()) do
            if i > CANDIDATES_MAX then break end
            local plan, why = plan_pocket(o, game_tile, plan_opts(d.lures[o.key], false))
            table.insert(list, {key = o.key, x = o.x, y = o.y, z = o.z, door_id = o.door_id, fits = plan ~= nil,
                                why = why, length = plan and plan.length or nil})
        end
        CAND_CACHE = {day = day, list = list}
    end
    out.candidates = CAND_CACHE.list
    out.cavern_citizens = cavern_citizens().n
    if G and G.free_mechanism_count then
        local ok, n = pcall(G.free_mechanism_count, 30)
        out.mechanisms = ok and n or nil
    end
    return out
end

-- (0.105.45) The seal doors a lure holds open now: {building id = true}
-- (ai-threats leaves these unlocked; the brain's seal rule counts them as meant).
function held_open()
    local out = {}
    local d = load_state()
    for _, rec in pairs(d.lures) do
        if type(rec) == 'table' and rec.open then
            local b = building_at(rec)
            if b then out[b.id] = true end
        end
    end
    return out
end

-- (0.105.45) Every piece of a lure not done (the seal door, the inner gate,
-- the mouth): {building id = true}. The gate watcher leaves an entrance with
-- one of these alone (the lure works them).
function held_ids()
    local out = {}
    local d = load_state()
    for _, rec in pairs(d.lures) do
        if type(rec) == 'table' and not (rec.done and rec.done.beast == rec.beast and not holding(rec)) then
            for _, p in ipairs({rec, rec.inner, rec.mouth}) do
                local b = p and building_at(p)
                if b then out[b.id] = true end
            end
        end
    end
    return out
end

---------------------------------------------------------------------------
-- Actions
---------------------------------------------------------------------------

local function lure_starts()
    local out = {}
    for _, u in ipairs(citizens()) do table.insert(out, {x = u.pos.x, y = u.pos.y, z = u.pos.z}) end
    local G = gates()
    if G and G.fort_starts then
        local ok, s = pcall(G.fort_starts, out)
        if ok and type(s) == 'table' and #s > 0 then return s end
    end
    return out
end

-- The pocket's next step: a new pocket planned and its pieces placed; the
-- levers placed once the bridges stand; linked once both are built.
-- beast: the great danger it is for (its raws decide traps or bridges).
function build_lure(key, beast_id, dry_run)
    local x, y, z = parse_key(key)
    if not x then return {ok = false, rejected = true, error = 'opening is "x,y,z"'} end
    local d = load_state()
    local rec = d.lures[key]
    local held = nil
    for _, o in ipairs(held_openings()) do if o.key == key then held = o end end
    if not held and not rec then
        return {ok = false, rejected = true, error = 'not one of the AI\'s cavern openings with a door it holds'}
    end
    local u = unit_of(beast_id)
    if beast_id ~= nil and not u then return {ok = false, rejected = true, error = 'no such creature'} end
    local G = gates()
    if not rec then
        local count = 0
        for _ in pairs(d.lures) do count = count + 1 end
        if count >= RECORDS_MAX then return {ok = false, rejected = true, error = 'too many lure pockets on record'} end
        local immune = u and trap_immune(u) or false
        local plan, why = plan_pocket({x = x, y = y, z = z}, game_tile, plan_opts(nil, immune))
        if not plan then return {ok = false, rejected = true, error = why} end
        local need = mechanisms_needed(plan)
        local have = 0
        if G and G.free_mechanism_count then
            local okm, n = pcall(G.free_mechanism_count, need + 2)
            have = okm and tonumber(n) or 0
        end
        if have < need then
            return {ok = false, waiting = true,
                    error = ('the pocket needs %d mechanism(s) and %d are free'):format(need, have)}
        end
        if dry_run then
            return {ok = true, dry_run = true, length = plan.length, traps = #plan.traps, immune = plan.immune,
                    inner = plan.inner.kind, mouth = plan.mouth and plan.mouth.kind or nil, mechanisms = need}
        end
        rec = {x = x, y = y, z = z, beast = beast_id, immune = plan.immune, tiles = plan.tiles,
               traps = plan.traps, inner = plan.inner, mouth = plan.mouth, levers = {}, tick = now_tick()}
        d.lures[key] = rec
    elseif beast_id ~= nil and rec.beast ~= beast_id then
        -- another beast: the same pocket waits for it (a finished lure starts again)
        if holding(rec) then
            return {ok = false, rejected = true, error = 'the pocket holds a beast shut in it: it stays shut'}
        end
        if dry_run then return {ok = true, dry_run = true, retarget = beast_id} end
        rec.beast, rec.done, rec.held_beast = beast_id, nil, nil
    end
    if dry_run then return {ok = true, dry_run = true, length = #(rec.tiles or {})} end
    rec.levers = type(rec.levers) == 'table' and rec.levers or {}
    local out = {ok = true, placed = 0, levers = 0, linked = 0, failed = {}}
    local function put(text, p, name)
        if building_at(p) then return end
        local ok, why = place(text, p)
        if ok then
            out.placed = out.placed + 1
            if name then pcall(function() local b = building_at(p); if b then b.name = name end end) end
        else
            table.insert(out.failed, ('%s at x%d y%d: %s'):format(text, p.x, p.y, tostring(why)))
        end
    end
    for _, p in ipairs(rec.traps or {}) do put(PIECE_KEYS.trap, p) end
    for _, role in ipairs({'inner', 'mouth'}) do
        local p = rec[role]
        if p then put(p.kind == 'bridge' and ('%s(1x1)'):format(p.dir or 'gw') or PIECE_KEYS.door, p, GATE_NAME) end
    end
    -- the bridges' levers (where the dwarves are, away from the pocket) and their links
    for _, role in ipairs({'inner', 'mouth'}) do
        local p = rec[role]
        if p and p.kind == 'bridge' then
            local lid = rec.levers[role]
            local lv = find_building(lid)
            if not lv then
                rec.levers[role] = nil
                local spot = nil
                if G and G.lever_spot then
                    pcall(function()
                        G.cache, G.edge_cache = {}, {}
                        spot = G.lever_spot(lure_starts(), {x = p.x, y = p.y, z = p.z})
                    end)
                end
                if spot then
                    local ok, why = place('Tl', spot)
                    local b = ok and building_at(spot) or nil
                    if b then
                        pcall(function() b.name = LEVER_NAME end)
                        rec.levers[role] = b.id
                        out.levers = out.levers + 1
                    else
                        table.insert(out.failed, 'lever: ' .. tostring(why or 'not placed'))
                    end
                else
                    table.insert(out.failed, 'no free floor for a lever where the dwarves are')
                end
            else
                local b = building_at(p)
                if b and built(b) and built(lv) and not lever_linked(G, lid, b.id) then
                    local okl, r = pcall(G.link_lever, lid, b.id, false)
                    if okl and type(r) == 'table' and r.ok then out.linked = out.linked + 1
                    elseif okl and type(r) == 'table' and r.error and not tostring(r.error):find('already') then
                        table.insert(out.failed, 'link: ' .. tostring(r.error))
                    end
                end
            end
        end
    end
    save_state(d)
    local row = lure_row(key, rec, G)
    out.built, out.phase = row.built, row.phase
    out.failed = #out.failed > 0 and table.concat(out.failed, '; '):sub(1, 300) or nil
    if out.placed + out.levers + out.linked == 0 then
        if row.built then return {ok = true, built = true, phase = row.phase, nothing_new = true} end
        return {ok = false, rejected = true, waiting = true, phase = row.phase, error = out.failed or
                'the pocket\'s pieces are being built (dwarves at work)'}
    end
    if out.placed > 0 then
        announce(('a lure pocket laid out behind the cavern door at x%d y%d (%d piece(s))'):format(x, y, out.placed))
    end
    return out
end

local function pull_to(G, lever_id, b, shut)
    if not (G and lever_id and b) then return false end
    local ok, up = pcall(function() local f = b.gate_flags; return (f.raised and not f.lowering) or f.raising end)
    if not ok then return false end
    if (up and true or false) == shut then return true end
    if shut == false and G.bridge_occupied and G.bridge_occupied(b) then return false end
    local okp, done = pcall(G.pull_instant, lever_id)
    return okp and done or false
end

-- The seal opened toward the pocket only. Refused while a citizen is down
-- in the caverns, a citizen is in or beside the pocket, the inner gate isn't
-- shut, or the pocket isn't finished.
function lure_open(key, dry_run)
    local d = load_state()
    local rec = d.lures[key]
    if type(rec) ~= 'table' then return {ok = false, rejected = true, error = 'no lure pocket there'} end
    if rec.open then return {ok = false, rejected = true, nothing_to_do = true, error = 'the lure is open already'} end
    local G = gates()
    local row = lure_row(key, rec, G)
    if row.phase == 'done' or row.caught or row.beast_gone then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'its beast is caught, shut in or gone'}
    end
    if not row.built then return {ok = false, rejected = true, error = 'the pocket is not finished'} end
    local cave = cavern_citizens()
    if cave.n > 0 then
        return {ok = false, rejected = true, waiting = true,
                error = ('%s is down in the caverns: the seal stays shut'):format(cave.first or 'a citizen')}
    end
    local near = citizens_near(rec)
    if near.n > 0 then
        return {ok = false, rejected = true, waiting = true,
                error = ('a citizen is in or beside the pocket (%s): the seal stays shut'):format(near.first or '?')}
    end
    if not (row.inner and row.inner.shut) then
        return {ok = false, rejected = true, error = 'the pocket\'s inner gate is not shut'}
    end
    local seal = building_at(rec)
    if not seal or kind_of(seal) ~= 'Door' then return {ok = false, rejected = true, error = 'no door on the opening'} end
    if G and G.lever_links then
        local ok, links = pcall(G.lever_links)
        if ok and type(links) == 'table' and #(links[seal.id] or {}) > 0 then
            return {ok = false, rejected = true, error = 'the opening\'s door is on a lever: the lure works only a locked door'}
        end
    end
    if dry_run then return {ok = true, dry_run = true, mouth = rec.mouth and 'lowered' or nil} end
    if rec.mouth then
        local b = building_at(rec.mouth)
        if not pull_to(G, rec.levers and rec.levers.mouth, b, false) then
            return {ok = false, error = 'the pocket\'s mouth would not lower'}
        end
    end
    local okf = pcall(function() seal.door_flags.forbidden = false end)
    if not okf then return {ok = false, error = 'the door would not unlock'} end
    rec.open, rec.opened_tick = true, now_tick()
    save_state(d)
    announce(('the cavern door at x%d y%d opened into a lure pocket (%s)'):format(rec.x, rec.y,
             rec.immune and 'its mouth raised once the beast is in' or 'cage traps'))
    return {ok = true, opened = true}
end

-- The mouth raised (a beast inside is shut in), the seal locked, the inner
-- gate shut. A caged beast, or one shut inside, is noted done.
function lure_shut(key, dry_run)
    local d = load_state()
    local rec = d.lures[key]
    if type(rec) ~= 'table' then return {ok = false, rejected = true, error = 'no lure pocket there'} end
    local G = gates()
    local row = lure_row(key, rec, G)
    local seal = building_at(rec)
    local changes = {}
    local locked = row.seal and row.seal.locked
    if seal and not locked then table.insert(changes, 'seal') end
    if rec.mouth and row.mouth and row.mouth.built and not row.mouth.shut then table.insert(changes, 'mouth') end
    if row.inner and row.inner.built and not row.inner.shut then table.insert(changes, 'inner') end
    local finished = rec.done and rec.done.beast == rec.beast
    local outcome = nil
    if not finished then
        if row.caught then outcome = 'caught'
        elseif row.beast_in_pocket and rec.mouth then outcome = 'shut_in'
        elseif row.beast_gone then outcome = 'gone' end
    end
    if #changes == 0 and not rec.open and not outcome then
        return {ok = false, rejected = true, nothing_to_do = true, error = 'the lure is shut already'}
    end
    if dry_run then return {ok = true, dry_run = true, shut = changes, outcome = outcome} end
    local failed = {}
    if rec.mouth and row.mouth and row.mouth.built and not row.mouth.shut then
        if not pull_to(G, rec.levers and rec.levers.mouth, building_at(rec.mouth), true) then
            table.insert(failed, 'mouth')
        end
    end
    if seal and not locked then
        if not pcall(function() seal.door_flags.forbidden = true end) then table.insert(failed, 'seal') end
    end
    if row.inner and row.inner.built and not row.inner.shut then
        local b = building_at(rec.inner)
        if rec.inner.kind == 'bridge' then
            if not pull_to(G, rec.levers and rec.levers.inner, b, true) then table.insert(failed, 'inner') end
        elseif not (b and pcall(function() b.door_flags.forbidden = true end)) then
            table.insert(failed, 'inner')
        end
    end
    local out = {ok = #failed == 0 or #failed < #changes, shut = changes, failed = #failed > 0 and failed or nil,
                 outcome = outcome}
    if rec.open then out.was_open = true end
    rec.open, rec.shut_tick = false, now_tick()
    if outcome == 'caught' then
        rec.done = {beast = rec.beast, how = 'caught', tick = now_tick()}
        out.caught = rec.beast
        announce(('the lure caught %s in a cage: it stays caged'):format(row.beast_name or 'the beast'), COLOR_GREEN)
    elseif outcome == 'shut_in' and not (failed[1] == 'mouth') then
        rec.done = {beast = rec.beast, how = 'shut_in', tick = now_tick()}
        rec.held_beast = rec.beast
        out.shut_in = rec.beast
        announce(('%s is shut in the lure pocket'):format(row.beast_name or 'the beast'), COLOR_GREEN)
    elseif outcome == 'gone' then
        rec.done = {beast = rec.beast, how = 'gone', tick = now_tick()}
        rec.held_beast = nil
    end
    save_state(d)
    return out
end
