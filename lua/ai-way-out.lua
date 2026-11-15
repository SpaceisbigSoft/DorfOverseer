-- (0.105.47, J16) The way out: can the citizens walk off the map?
--
-- The player (14 Nov 17:25): "something needs to be fixed so the dwarves
-- don't lock themselves in or can't get out". Live on War-hold the same day:
-- after the last run the fort was sealed by the AI's own gates (Hatch "AI
-- gate 1 (surface)" and Hatch "AI gate 2 (surface)" shut by their "AI gate
-- lever"s, the gatehouse bridge raised by its lever), and the citizens'
-- walk group (6712) reached none of the map's edge tiles; a messenger and a
-- 9-dwarf squad sent on missions could never leave. Nothing looked at it.
--
--   report()          the `way_out` report section: {known, open, inside_group,
--                     citizens, edge_groups (how many), shut_by = the surface
--                     entrances' shut pieces with their state (the AI's and
--                     the player's), sealed_by_locks, cause = the dangers in
--                     sight, armed, closed (the watcher's), repaths}
--   open_way(id, o)   one surface entrance opened by what DF honours: a hatch
--                     or door on an "AI gate" lever by its lever (pulled at
--                     once), a bridge on one by its lever (a dwarf's pull; at
--                     once with o.instant), a lock the AI put on unlocked
--                     (ai-util lock_door, the walk map redone); a gate the
--                     watcher booked shut goes through ai-gates open_entrance
--                     first. The player's own gates (no "AI gate" lever, no
--                     "AI gate" name) are reported, never touched.
--   leave(dry_run)    the keeper or overseer stopping: with no enemy in reach,
--                     every surface entrance opened (bridges at once) and the
--                     watcher disarmed, so a fort left alone is never sealed.
--
-- The map's edge groups (the walk groups of the walkable tiles on the map's
-- border, over the surface's levels) are cached per map and read again
-- every EDGE_EVERY reports or after the walk map was redone (ai-util repath).
--@ module = true

EDGE_EVERY = 10          -- reports between two reads of the edge groups
EDGE_Z_SPAN = 25         -- levels above and below the surface entrances read
EDGE_Z_FALLBACK = 60     -- no entrance mapped: this many levels down from the top
SHUT_MAX = 12            -- pieces listed in shut_by at most

EDGE = EDGE or {}        -- {key, groups, tiles, report, repath_n, z = {lo, hi}}
WAY = WAY or {reports = 0}

local U = reqscript('ai-util')

local function gates()
    local ok, G = pcall(function() return reqscript('ai-gates') end)
    if ok and type(G) == 'table' then return G end
    return nil
end

local function wgroup(x, y, z)
    local ok, g = pcall(function() return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) end)
    return ok and type(g) == 'number' and g or 0
end
group_at = wgroup            -- tests replace this

-- --- the edge groups -----------------------------------------------------------------

-- Pure: the walk groups of the border tiles of a W x H map on levels lo..hi
-- ({group = true}, and how many tiles had one).
function edge_groups_of(W, H, lo, hi, at)
    local out, n = {}, 0
    local function look(x, y, z)
        local g = at(x, y, z)
        if g ~= 0 then
            out[g] = true
            n = n + 1
        end
    end
    for z = lo, hi do
        for x = 0, W - 1 do
            look(x, 0, z)
            if H > 1 then look(x, H - 1, z) end
        end
        for y = 1, H - 2 do
            look(0, y, z)
            if W > 1 then look(W - 1, y, z) end
        end
    end
    return out, n
end

-- Pure: the levels to read, from the surface entrances (G.entrances) and the
-- map's height Z.
function z_range(G, Z)
    local lo, hi
    for _, e in ipairs(type(G) == 'table' and G.entrances or {}) do
        if e.kind ~= 'cavern' and type(e.z) == 'number' then
            lo = math.min(lo or e.z, e.z)
            hi = math.max(hi or e.z, e.z)
        end
    end
    if not lo then return math.max(0, Z - EDGE_Z_FALLBACK), Z - 1 end
    return math.max(0, lo - EDGE_Z_SPAN), math.min(Z - 1, hi + EDGE_Z_SPAN)
end

local function map_dims()
    local ok, W, H, Z = pcall(function()
        local m = df.global.world.map
        return m.x_count, m.y_count, m.z_count
    end)
    if ok and type(W) == 'number' and W > 0 then return W, H, Z end
    return nil
end

local function map_key(W, H, Z)
    local ok, site = pcall(function() return df.global.plotinfo.site_id end)
    return ('%s:%d:%d:%d'):format(tostring(ok and site or '?'), W, H, Z)
end

-- The edge groups, cached ({group = true}, or nil when the map can't be read).
function edge_groups(force)
    local W, H, Z = map_dims()
    if not W then return nil end
    local k = map_key(W, H, Z)
    local rp = U.REPATH and U.REPATH.n or 0
    local G = gates()
    local GT = G and G.GATES or nil
    if not force and EDGE.key == k and EDGE.groups and EDGE.repath_n == rp
            and (WAY.reports - (EDGE.report or 0)) < EDGE_EVERY then
        return EDGE.groups
    end
    local lo, hi = z_range(GT, Z)
    -- the game's reader without a pcall a tile (thousands of tiles): the
    -- whole read protected once, else tile by tile
    local reader = group_at
    if reader == wgroup then
        reader = function(x, y, z) return dfhack.maps.getWalkableGroup(xyz2pos(x, y, z)) or 0 end
    end
    local okr, groups, n = pcall(edge_groups_of, W, H, lo, hi, reader)
    if not okr then groups, n = edge_groups_of(W, H, lo, hi, group_at) end
    EDGE.key, EDGE.groups, EDGE.tiles, EDGE.report, EDGE.repath_n = k, groups, n, WAY.reports, rp
    EDGE.z = {lo, hi}
    return groups
end

-- --- the citizens' group -------------------------------------------------------------

-- Pure: the group most citizens stand in ({x, y, z} each), how many, and
-- where they stand on average. 0 groups (in the air, unread) don't count.
function main_group(units, at)
    local count, best, bn = {}, nil, 0
    for _, u in ipairs(units or {}) do
        local g = at(u.x, u.y, u.z)
        if g ~= 0 then
            count[g] = (count[g] or 0) + 1
            if count[g] > bn or (count[g] == bn and g < best) then best, bn = g, count[g] end
        end
    end
    if not best then return nil, 0, nil end
    local sx, sy, sz = 0, 0, 0
    for _, u in ipairs(units) do
        if at(u.x, u.y, u.z) == best then sx, sy, sz = sx + u.x, sy + u.y, sz + u.z end
    end
    return best, bn, {x = sx // bn, y = sy // bn, z = sz // bn}
end

function citizen_spots()
    local out = {}
    local ok = pcall(function()
        for _, u in ipairs(U.citizens(true)) do
            if not (u.flags1.inactive or u.flags2.killed) then
                table.insert(out, {id = u.id, x = u.pos.x, y = u.pos.y, z = u.pos.z})
            end
        end
    end)
    return ok and out or {}
end

-- --- the gates on the way --------------------------------------------------------------

local function lever_name(lid)
    local ok, n = pcall(function() return tostring(df.building.find(lid).name or '') end)
    return ok and n or ''
end

local function ai_lever(G, name)
    local ok, yes = pcall(G.ai_lever_name, name)
    return ok and yes and true or false
end

-- A piece's state now: {shut, locked, raised, moving, jobs}, nil if unread.
-- (0.105.48, K2) shut: a bridge raised; a door or hatch locked, or (on its
-- lever) closed. DF's `closed` is set on any door or hatch at rest (nobody
-- passing), which an ordinary dwarf walks through: not shut.
function piece_now(g, b)
    local st = {}
    if g.kind == 'bridge' then
        local ok = pcall(function()
            local f = b.gate_flags
            st.raised = (f.raised and not f.lowering) or f.raising or false
            st.moving = (f.raising or f.lowering) and true or false
        end)
        if not ok then return nil end
        st.shut = st.raised
    else
        local ok = pcall(function()
            st.closed = b.door_flags.closed == true
            st.locked = b.door_flags.forbidden == true
        end)
        if not ok then return nil end
        st.shut = st.locked or (st.closed and g.lever_driven == true) or false
    end
    pcall(function() st.jobs = #b.jobs end)
    return st
end

-- The lever a piece is worked by (a bridge's lever_id, a door's or hatch's
-- drive lever), and whether it is the AI's own for this entrance: named "AI
-- gate..." and working nothing but this entrance's gates.
function piece_lever(G, e, g, levers)
    local lid = g.kind == 'bridge' and g.lever_id or g.drive_lever or (g.lever_driven and g.lever_id) or nil
    if not lid then return nil, false end
    if not ai_lever(G, lever_name(lid)) then return lid, false end
    local okm, mine = pcall(G.entrance_gate_ids, e)
    mine = okm and mine or {}
    local okt, targets = pcall(G.lever_targets, levers or {}, lid)
    for _, tid in ipairs(okt and targets or {}) do
        if not mine[tid] then return lid, false end     -- it works something else too (a well's hatch)
    end
    return lid, true
end

-- Is this piece the AI's? Its lever is, or the scan named it "AI gate...", or
-- the watcher shut it (GATES.mine).
local function ai_owned(G, g, b, own_lever)
    if own_lever then return true end
    local okn, name = pcall(function() return tostring(b.name or '') end)
    if okn and name:find('^AI gate') then return true end
    local GT = G.GATES or {}
    return type(GT.mine) == 'table' and GT.mine[g.id] == true
end

local function pieces_of(e)
    local out = {}
    for _, g in ipairs(e.equipment or {}) do table.insert(out, g) end
    for _, g in ipairs(e.outer or {}) do table.insert(out, g) end
    return out
end

-- The surface entrances' shut pieces: {{entrance, id, kind, x, y, z, name,
-- raised|closed|locked, lever, ai}} (at most SHUT_MAX), and whether every
-- surface entrance is shut. (0.105.48, K2) An entrance is shut when every
-- piece it needs (its equipment: the scan keeps only those, any one open
-- lets a dwarf through) is shut, or its gatehouse bridge (outer) is raised.
function shut_by(G, levers)
    local out, entrances, shut_e = {}, 0, 0
    local GT = G and G.GATES or nil
    if not GT or not GT.entrances then return out, false end
    for _, e in ipairs(GT.entrances) do
        if e.kind ~= 'cavern' then
            entrances = entrances + 1
            local outer = {}
            for _, g in ipairs(e.outer or {}) do outer[g.id] = true end
            local need, need_shut, outer_shut = 0, 0, false
            for _, g in ipairs(pieces_of(e)) do
                local okb, b = pcall(df.building.find, g.id)
                local st = okb and b and piece_now(g, b) or nil
                if not outer[g.id] then
                    need = need + 1
                    if st and st.shut then need_shut = need_shut + 1 end
                elseif st and st.shut then
                    outer_shut = true
                end
                if st and st.shut then
                    local lid, own = piece_lever(G, e, g, levers)
                    if #out < SHUT_MAX then
                        local okn, name = pcall(function() return tostring(b.name or '') end)
                        table.insert(out, {entrance = e.id, id = g.id, kind = g.kind, x = g.x or b.x1, y = g.y or b.y1,
                                           z = g.z or b.z, name = okn and name ~= '' and name:sub(1, 40) or nil,
                                           raised = st.raised or nil, closed = st.closed or nil,
                                           locked = st.locked or nil, moving = st.moving or nil,
                                           lever = lid, ai = ai_owned(G, g, b, own),
                                           booked = (GT.closed and GT.closed[e.id]) and true or nil})
                    end
                end
            end
            if outer_shut or (need > 0 and need_shut == need) then shut_e = shut_e + 1 end
        end
    end
    return out, entrances > 0 and shut_e == entrances
end

-- The dangers in sight, as the watcher counts them: {invaders, great,
-- nearest (to any surface entrance), seen}.
function cause(G)
    local out = {invaders = 0, great = 0, seen = 0}
    if not G then return out end
    local okv, vis = pcall(G.visible_dangers)
    local nearest = math.huge
    for _, d in ipairs(okv and vis or {}) do
        out.seen = out.seen + 1
        if d.invader then out.invaders = out.invaders + 1 end
        if d.great then out.great = out.great + 1 end
        for _, e in ipairs((G.GATES or {}).entrances or {}) do
            if e.kind ~= 'cavern' then
                local okd, dd = pcall(G.distance_to, e, d.pos)
                if okd and dd < nearest then nearest = dd end
            end
        end
    end
    out.nearest = nearest < math.huge and nearest or nil
    return out
end

-- Pure: the verdict from the groups. open: the citizens' group touches an
-- edge group (nil: unknown).
function judge(inside, edges)
    if inside == nil or edges == nil then return nil end
    return edges[inside] == true
end

function report()
    WAY.reports = (WAY.reports or 0) + 1
    local G = gates()
    local out = {known = false}
    local edges = edge_groups()
    local spots = citizen_spots()
    local inside, n, at = main_group(spots, group_at)
    local open = judge(inside, edges)
    out.known = open ~= nil
    out.open = open
    out.inside_group = inside
    out.citizens = #spots
    out.in_group = n
    out.at = at
    local ne = 0
    for _ in pairs(edges or {}) do ne = ne + 1 end
    out.edge_groups = ne
    out.edge_tiles = EDGE.tiles
    local GT = G and G.GATES or {}
    local okl, levers = pcall(function() return G and G.lever_links() or {} end)
    local list, all_shut = shut_by(G, okl and levers or {})
    out.shut_by = #list > 0 and list or nil
    -- DF's walk groups pass a locked door: the groups may join the edge with
    -- every surface entrance locked (the citizens can't walk through it)
    out.sealed_by_locks = (open == true and all_shut) or nil
    out.cause = cause(G)
    out.armed = GT.armed and true or nil
    local closed = 0
    for _ in pairs(GT.closed or {}) do closed = closed + 1 end
    out.closed = closed > 0 and closed or nil
    out.away = GT.away or nil
    out.repaths = U.repath_summary()
    if at and GT.entrances then
        -- the surface entrances from the nearest to the citizens
        local order = {}
        for _, e in ipairs(GT.entrances) do
            if e.kind ~= 'cavern' and type(e.x) == 'number' then
                table.insert(order, {id = e.id, d = math.max(math.abs(e.x - at.x), math.abs(e.y - at.y))
                                                  + 3 * math.abs((e.z or at.z) - at.z)})
            end
        end
        table.sort(order, function(a, b) return a.d < b.d end)
        local ids = {}
        for i = 1, math.min(#order, 6) do ids[i] = order[i].id end
        out.nearest_entrances = #ids > 0 and ids or nil
    end
    return out
end

-- --- opening ---------------------------------------------------------------------------

local function find_entrance(GT, id)
    for _, e in ipairs(GT.entrances or {}) do if e.id == id then return e end end
    return nil
end

-- Open one surface entrance by what DF honours. o: {dry_run, instant (a
-- bridge pulled at once too), leaving (the AI stopping: no IMMINENT check
-- here, leave() judged it)}.
function open_way(id, o)
    o = o or {}
    local G = gates()
    if not G or not G.GATES or not G.GATES.scanned then
        return {ok = false, rejected = true, error = 'map the entrances first'}
    end
    local GT = G.GATES
    local e = find_entrance(GT, id)
    if not e then return {ok = false, rejected = true, error = 'no entrance ' .. tostring(id)} end
    if e.kind == 'cavern' then
        return {ok = false, rejected = true, error = 'a cavern entrance is not a way off the map'}
    end
    local okv, vis = pcall(G.visible_dangers)
    local nearest = math.huge
    for _, d in ipairs(okv and vis or {}) do
        if d.great and not o.leaving then
            return {ok = false, rejected = true, waiting = true, error = 'a great danger is in sight'}
        end
        local okd, dd = pcall(G.distance_to, e, d.pos)
        if okd and dd < nearest then nearest = dd end
    end
    if nearest <= (G.IMMINENT or 12) then
        return {ok = false, rejected = true, waiting = true, nearest = nearest,
                error = ('an enemy is %d tiles from this entrance'):format(nearest)}
    end
    local okh, held = pcall(G.seal_holds)
    held = okh and held or {ids = {}, levers = {}}
    local out = {ok = true, entrance = id, dry_run = o.dry_run or nil, did = {}, players = {}, kept = 0,
                 waiting = 0, opened = 0}
    -- the watcher's own booking first: it opens what it shut and unbooks it
    if GT.closed and GT.closed[e.id] then
        if o.dry_run then
            table.insert(out.did, 'would open what the gate watcher shut')
        else
            local okr, r = pcall(G.open_entrance, id, false, false)
            if okr and type(r) == 'table' then
                out.via_watcher = r.ok and true or false
                out.opened = out.opened + (r.opened or 0)
                if r.ok then table.insert(out.did, ('the watcher\'s %d piece(s) opened'):format(r.opened or 0)) end
            end
        end
    end
    local okl, levers = pcall(G.lever_links)
    levers = okl and levers or {}
    local pulled = {}
    for _, g in ipairs(pieces_of(e)) do
        local okb, b = pcall(df.building.find, g.id)
        local st = okb and b and piece_now(g, b) or nil
        if st and st.shut then
            local lid, own = piece_lever(G, e, g, levers)
            local mine = ai_owned(G, g, b, own)
            local where = ('%s %d'):format(g.kind, g.id)
            local okseal, sealed = pcall(G.seal_has, held, g)
            if okseal and sealed then
                out.kept = out.kept + 1
            elseif lid and own then
                if g.kind == 'bridge' then
                    local busy = st.moving or (st.jobs or 0) > 0
                    local okq, pending = pcall(G.lever_pull_pending, lid)
                    -- (0.105.48 round 2, A5 #11/#12) at once: a dwarf's pull still
                    -- queued at the lever (nobody comes: the lever cut off, the
                    -- civilians burrowed; or open_all's own) is no wait: the
                    -- instant pull takes it away first (pull_instant)
                    if o.instant and not st.moving then pending = false end
                    local okoc, occ = pcall(G.bridge_occupied, b)
                    if busy or (okq and pending) then
                        out.waiting = out.waiting + 1
                        table.insert(out.did, where .. ': already moving or a pull is on its way')
                    elseif okoc and occ then
                        out.waiting = out.waiting + 1
                        table.insert(out.did, where .. ': someone stands where it comes down')
                    elseif o.dry_run then
                        table.insert(out.did, ('would pull lever %d%s to lower %s'):format(lid,
                            o.instant and ' at once' or '', where))
                    elseif not pulled[lid] then
                        pulled[lid] = true
                        local okp, done = pcall(o.instant and G.pull_instant or G.pull, lid)
                        if okp and done then
                            out.opened = out.opened + 1
                            if not o.instant then out.waiting = out.waiting + 1 end
                            table.insert(out.did, ('lever %d pulled%s (%s)'):format(lid, o.instant and ' at once' or
                                ' (a dwarf\'s job)', where))
                        else
                            out.waiting = out.waiting + 1
                            table.insert(out.did, ('lever %d would not be pulled (%s)'):format(lid, where))
                        end
                    end
                else
                    if st.locked and not o.dry_run then pcall(G.lock_gate, b, false) end
                    if st.closed and not pulled[lid] then
                        if o.dry_run then
                            table.insert(out.did, ('would pull lever %d at once to open %s'):format(lid, where))
                        else
                            pulled[lid] = true
                            local okp, done = pcall(G.pull_instant, lid)
                            if okp and done then
                                out.opened = out.opened + 1
                                table.insert(out.did, ('lever %d pulled at once (%s)'):format(lid, where))
                            else
                                out.waiting = out.waiting + 1
                                table.insert(out.did, ('lever %d would not be pulled (%s)'):format(lid, where))
                            end
                        end
                    elseif st.locked then
                        if o.dry_run then table.insert(out.did, 'would unlock ' .. where)
                        else out.opened = out.opened + 1; table.insert(out.did, 'unlocked ' .. where) end
                    end
                end
                if not o.dry_run and type(GT.mine) == 'table' then GT.mine[g.id] = nil end
            elseif mine and st.locked and g.kind ~= 'bridge' then
                -- (0.105.48, K2) a lock the AI put on (a plain door at rest reads
                -- closed too: no `not closed` test); on the player's lever, its
                -- lock is undone and the lever left theirs
                if o.dry_run then
                    table.insert(out.did, 'would unlock ' .. where)
                else
                    local okc, changed = pcall(G.lock_gate, b, false)
                    if okc and changed then
                        out.opened = out.opened + 1
                        table.insert(out.did, 'unlocked ' .. where)
                    end
                    if type(GT.mine) == 'table' then GT.mine[g.id] = nil end
                end
                if lid and st.closed and g.lever_driven then
                    table.insert(out.players, {id = g.id, kind = g.kind, lever = lid,
                                               x = g.x or b.x1, y = g.y or b.y1, z = g.z or b.z})
                end
            else
                -- the player's own (their lever, or a door the AI never named or shut): reported only
                table.insert(out.players, {id = g.id, kind = g.kind, lever = lid,
                                           x = g.x or b.x1, y = g.y or b.y1, z = g.z or b.z})
            end
        end
    end
    if not o.dry_run then
        if GT.closed and GT.closed[e.id] and out.waiting == 0 and out.kept == 0 then GT.closed[e.id] = nil end
        pcall(G.gates_persist)
        pcall(U.repath, 'way_out')
        -- the edge groups read again at the next report (the walk map changes)
        EDGE.report = nil
    end
    if #out.players == 0 then out.players = nil end
    if out.opened == 0 and out.waiting == 0 and not o.dry_run and not out.via_watcher then
        out.ok = false
        out.nothing = true
        out.error = out.players and 'only the player\'s own gates shut this entrance: the AI does not open them'
            or (out.kept > 0 and 'the cavern seal holds this entrance') or 'nothing of the AI\'s is shut there'
    end
    out.did = table.concat(out.did, '; ')
    if out.did == '' then out.did = nil end
    return out
end

-- The AI stopping (the keeper's Ctrl-C, the STOP file, the end of a run):
-- with no enemy in reach (no invader or great danger in sight, nothing within
-- the watcher's WIDE of a surface entrance), every surface entrance opened
-- at once and the watcher disarmed. With one in reach, left as it is (the
-- watcher keeps watching, and lifts its lockdown itself once the danger is gone).
local function leave_gates(dry_run)
    local G = gates()
    if not G or not G.GATES then return {ok = false, rejected = true, error = 'no gates module'} end
    -- (0.105.48 round 2, A1 #7) a dry run (it passes the halt) restores nothing:
    -- gates_restore may arm the watcher or open the saved gates
    if not dry_run then pcall(G.gates_restore) end
    local GT = G.GATES
    if not GT.scanned or not GT.entrances then
        -- no map of the entrances: the saved lockdown opened by its ids
        if dry_run then return {ok = true, dry_run = true, unmapped = true} end
        local okr, r = pcall(G.open_all)
        return {ok = okr, unmapped = true, opened = okr and type(r) == 'table' and r.opened or 0}
    end
    local c = cause(G)
    if c.invaders > 0 or c.great > 0 or (c.nearest and c.nearest <= (G.WIDE or 60)) then
        return {ok = false, rejected = true, enemy = true, cause = c,
                error = ('an enemy is in reach (%d invader(s), %d great danger(s), nearest %s tiles): the gates '
                         .. 'stay as the watcher keeps them'):format(c.invaders, c.great, tostring(c.nearest or '?'))}
    end
    local out = {ok = true, dry_run = dry_run or nil, entrances = {}, opened = 0, cause = c}
    if not dry_run then
        local okr, r = pcall(G.open_all)       -- disarmed; what it booked opened
        if okr and type(r) == 'table' then out.watcher_opened = r.opened end
    end
    for _, e in ipairs(GT.entrances) do
        if e.kind ~= 'cavern' then
            local r = open_way(e.id, {dry_run = dry_run, instant = true, leaving = true})
            -- (round 2, A5 #12) waiting is a count (0 is truthy in Lua), or true on a refusal
            local waits = r.waiting == true or (type(r.waiting) == 'number' and r.waiting > 0)
            if r.ok or waits then
                table.insert(out.entrances, {id = e.id, opened = r.opened, waiting = waits and r.waiting or nil,
                                             players = r.players and #r.players or nil})
                out.opened = out.opened + (r.opened or 0)
            elseif r.players then
                table.insert(out.entrances, {id = e.id, players = #r.players})
            end
        end
    end
    if not dry_run then
        local okt, t = pcall(U.abs_tick)
        GT.left_open = {tick = okt and t or nil, opened = out.opened}
        pcall(dfhack.gui.showAnnouncement, ('AI Overseer stopped: %d gate piece(s) opened, the fort left open')
            :format(out.opened), COLOR_GREEN, false)
    end
    return out
end

-- (0.105.48, K3) The AI stopping lets go of its alarm and burrows too: its
-- own alarm lowered when no invader nor great danger is in sight, every
-- member of its own burrows let out (lua/ai-society.lua stand_down; the
-- player's alarm and burrows untouched), whatever the gates' answer. The
-- gates' answer as before, with `stood_down` (what was let go) added.
function leave(dry_run)
    local out = leave_gates(dry_run)
    local ok, r = pcall(function() return reqscript('ai-society').stand_down({stopping = true, dry_run = dry_run}) end)
    if type(out) ~= 'table' then out = {ok = false, error = 'no answer from the gates'} end
    if ok and type(r) == 'table' and (r.alarm or r.burrows) then out.stood_down = r end
    return out
end
