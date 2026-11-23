-- ai-builder-projects-progress: a project's progress: its cells, dig progress (lost tiles designated
-- again), furnish progress, parked levels, the building slots, the projects' report, the registry.
--
-- (r8) A part of ai-builder, not a script of its own: cut from ai-builder-projects.lua
-- (which had grown to 164 KB) at a section boundary, the code as it stood. ai-builder.lua
-- loads it into its own environment right after the part before it (PARTS), so every
-- name here is reqscript('ai-builder').name and the hub's helpers are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-projects-progress'] = '0.105.70'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez


function cells_of(p, phase)
    return (type(p.cells) == 'table' and type(p.cells[phase]) == 'table') and p.cells[phase] or {}
end

-- How far the digging has got, and whether it's stuck.
REDIG_MAX = 3        -- (0.105.33, L4) times a lost shaft, stair or gallery tile is designated again
-- (y2) at most this many undug tiles of a level with nothing dug are tested for a
-- dwarf-reachable side (dig_progress's `reach`); past it the answer is `partial`
REACH_CHECK_MAX = 600

-- (0.105.48, K7c) read only unless `redig` is true: the report only counts
-- the lost shaft, stair and gallery tiles it would designate again
-- (`redig_due`, not counted as stuck); redig_projects (an action, so never
-- while halted) puts them back (`redesignated`), dry_run counting only.
function dig_progress(p, redig, dry_run)
    local total, dug, stuck, marked, digging = 0, 0, 0, 0, 0
    local jobs = job_tiles()
    local waiting = {}             -- (0.104.110) what the tiles left wait on: up to 5, with their jobs
    -- (0.104.127) can a dwarf get beside a waiting tile? (Teacheroar: the new
    -- hospital 0 of 175 and a bedrooms level 0 of 89 for years, each one dig
    -- job with "no worker")
    local groups
    local function reach_words(x, y, z)
        if groups == nil then
            groups = {}
            pcall(function()
                for _, cp in ipairs(citizen_positions()) do
                    local g = dfhack.maps.getWalkableGroup(xyz2pos(cp.x, cp.y, cp.z))
                    if g and g ~= 0 then groups[g] = true end
                end
            end)
        end
        local seen_walk = false
        for dz = 0, 0 do                -- (a wall is dug from beside it, on its own level)
            for dy = -1, 1 do
                for dx = -1, 1 do
                    if dx ~= 0 or dy ~= 0 then
                        local okg, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(x + dx, y + dy, z + dz))
                        if okg and g and g ~= 0 then
                            if groups[g] then return 'reachable' end
                            seen_walk = true
                        end
                    end
                end
            end
        end
        return seen_walk and 'beside ground the dwarves can\'t reach' or 'no open ground beside it'
    end
    -- (0.104.136) what DF cancels digging for: warm stone, damp stone (water or
    -- an aquifer beside it), a hidden tile (Teacheroar: two hospital levels began
    -- at x109 y40 z157 beside the cistern and neither was ever dug)
    local function risk_words(x, y, z)
        local out = {}
        local t = tile_info(x, y, z)
        if t and t.warm then table.insert(out, 'warm stone') end
        if t and t.hidden then table.insert(out, 'hidden') end
        if t and t.aquifer then table.insert(out, 'aquifer') end
        local wet = false
        for dz = -1, 1 do
            for dy = -1, 1 do
                for dx = -1, 1 do
                    local n = tile_info(x + dx, y + dy, z + dz)
                    if n and (n.liquid or n.aquifer) then wet = true end
                end
            end
        end
        if wet then table.insert(out, 'damp (water or an aquifer beside it)') end
        return out
    end
    local undug = {}               -- (y2) tiles with a job or a designation, for `reach`
    local function check(x, y, z, done)
        total = total + 1
        local t = tile_info(x, y, z)
        if t and done(t) then
            dug = dug + 1
        elseif jobs[x .. ',' .. y .. ',' .. z] then
            table.insert(undug, {x, y, z})
            digging = digging + 1  -- a dwarf is on it now
            if #waiting < 5 then
                local okr, rw = pcall(reach_words, x, y, z)
                local okk, risk = pcall(risk_words, x, y, z)
                table.insert(waiting, ('x%d y%d z%d: %s%s%s'):format(x, y, z, job_words(jobs[x .. ',' .. y .. ',' .. z]),
                                                                    okr and rw ~= 'reachable' and (', ' .. rw) or '',
                                                                    okk and #risk > 0 and (', ' .. table.concat(risk, ', ')) or ''))
            end
        elseif t and t.marked then
            marked = marked + 1    -- marker-only designation: nobody will dig it
        elseif t and not t.designated then
            stuck = stuck + 1      -- still wall, and not designated any more
        else
            table.insert(undug, {x, y, z})
        end
    end
    local not_wall = function(t) return t.shape ~= 'WALL' end
    if p.dig_done == 'open' then        -- a channel: done once the floor is gone
        not_wall = function(t) return t.shape ~= 'WALL' and t.shape ~= 'FLOOR' end
    end
    local anchor = anchor_of(p)
    local up_top = type(p.up) == 'table' and type(well_up_waits) == 'function'    -- (0.105.47)
    local top_waits = 0
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do
            if up_top and well_up_waits(p, anchor.x + x, anchor.y + y, p.z) then
                total, top_waits = total + 1, top_waits + 1     -- (0.105.47) the top waits for the shaft under it
            else
                check(anchor.x + x, anchor.y + y, p.z, not_wall)
            end
        end
    end
    for _, c in ipairs(p.stairs or {}) do
        local want = c.text == 'u' and 'STAIR_UP' or 'STAIR_UPDOWN'
        check(p.stair.x, p.stair.y, c.z, function(t) return t.shape == want end)
    end
    -- a cavern well's shaft: each rock level open (no wall, floor or ramp left)
    -- (0.104.13) and the stairs it is dug from. A shaft tile or stair the game
    -- dropped (a channel above turns the rock below it into a ramp) is
    -- designated again, so the shaft never stalls on a lost designation, and
    -- the well waits for every level of it.
    local open_shape = function(t) return t.shape ~= 'WALL' and t.shape ~= 'FLOOR' and t.shape ~= 'RAMP' end
    local pri = type(p.params) == 'table' and p.params.pri or ''
    local shaft_open, redug, due = true, 0, 0
    -- (0.105.33, L4) each tile at most REDIG_MAX times (counted in the
    -- project): one the game (or the player) keeps taking off stays stuck,
    -- so the project can end instead of putting it back for ever
    local function keep(x, y, z, done, key)
        local before = stuck
        check(x, y, z, done)
        local t = tile_info(x, y, z)
        if not (t and done(t)) then shaft_open = false end
        local tk = x .. ',' .. y .. ',' .. z
        local times = type(p.redug) == 'table' and tonumber(p.redug[tk]) or 0
        if stuck > before and t and not t.marked and times < REDIG_MAX then
            if not redig or dry_run then
                stuck, due = stuck - 1, due + 1      -- (0.105.48) waits for redig_projects
            else
                local ok, s = pcall(quickfort_apply, 'dig', {{x = 0, y = 0, text = key .. (pri or '')}}, z, x, y)
                if ok and stat(s, 'dig_designated') == 1 then
                    stuck, redug = stuck - 1, redug + 1
                end
                if type(p.redug) ~= 'table' then p.redug = {} end
                p.redug[tk], p.redug_changed = times + 1, true
            end
        end
    end
    -- (0.105.4 review) the shaft's last level (it opens into the cavern) and
    -- the stair step beside it are held undug until the shaft gate's lever
    -- stands and its hatch cover and mechanisms are in store: counted, never
    -- designated again here, and the shaft isn't open while they wait
    local held = type(p.held) == 'table' and p.held or nil
    local held_n = top_waits
    -- (0.105.47) a cavern shaft dug from the bottom up (ai-well-safety): the
    -- levels over the one being dug, and the top, wait undesignated too
    local up = type(p.up) == 'table' and type(well_up_waits) == 'function'
    local function is_held(x, y, z)
        if up and well_up_waits(p, x, y, z) then return true end
        return held ~= nil and z == held.z and ((x == anchor.x and y == anchor.y)
            or (held.stair and x == held.stair.x and y == held.stair.y))
    end
    local function keep_or_hold(x, y, z, done, key)
        if is_held(x, y, z) then
            total, held_n, shaft_open = total + 1, held_n + 1, false
        else
            keep(x, y, z, done, key)
        end
    end
    for _, zk in ipairs(p.shaft or {}) do
        keep_or_hold(anchor.x, anchor.y, zk, open_shape, 'h')
    end
    for _, c in ipairs(p.shaft_stairs or {}) do
        local want = STAIR_SHAPES[c.key]
        -- (K48-K4b, A4 16) the bottom up-stair made an up/down stair by a rescue
        -- stair dug down from it is still the stair (not stuck, not re-dug)
        keep_or_hold(c.x, c.y, c.z, function(t)
            return t.shape == want or (c.key == 'u' and t.shape == 'STAIR_UPDOWN')
        end, c.key)
    end
    -- (0.105.3) Hammerstirred: a gallery out to the shaft, each tile dug to a floor
    for _, g in ipairs(type(p.gallery) == 'table' and p.gallery or {}) do
        keep(g.x, g.y, p.z, function(t) return t.shape ~= 'WALL' end, 'd')
    end
    -- (r2 h2) a winter cistern's chamber, one level under the well
    for _, c in ipairs(type(p.chamber) == 'table' and p.chamber or {}) do
        if type(c) == 'table' and c.x and c.z then keep(c.x, c.y, c.z, function(t) return t.shape ~= 'WALL' end, 'd') end
    end
    local out = {total = total, dug = dug, stuck = stuck, marked = marked, digging = digging,
                 waiting = #waiting > 0 and waiting or nil}
    -- (y2) nothing dug yet: is any of its undug tiles (with a job or designated)
    -- beside ground a citizen walks in? A level's inner tiles read "no open ground
    -- beside it" until the outer ones are dug, so the 5 `waiting` lines alone never
    -- show a level cut off. Stops at the first reachable tile (the usual case);
    -- REACH_CHECK_MAX tiles at most (then `partial`). The brain's dig check gives a
    -- level up as unreached only on {reachable = 0, partial = nil}.
    if dug == 0 and #undug > 0 then
        local reach = {checked = 0, reachable = 0, tiles = #undug}
        for _, c in ipairs(undug) do
            if reach.checked >= REACH_CHECK_MAX then reach.partial = true; break end
            reach.checked = reach.checked + 1
            local okr, rw = pcall(reach_words, c[1], c[2], c[3])
            if not okr then reach.partial = true; break end      -- unknown: never "cut off"
            if rw == 'reachable' then reach.reachable = 1; break end
        end
        if next(groups or {}) == nil then reach.partial = true end  -- no citizen's walk group read
        out.reach = reach
    end
    if top_waits > 0 then shaft_open = false end      -- (0.105.47)
    if p.shaft then out.shaft_open = shaft_open end
    if redug > 0 then out.redesignated = redug end
    if due > 0 then out.redig_due = due end           -- (0.105.48) lost tiles redig_projects puts back
    if held_n > 0 then out.held = held_n end          -- (0.105.4 review)
    -- (0.105.31) a well's channel not dug: why
    if p.kind == 'well' and dug == 0 and total > 0 then
        local okw, w = pcall(well_dig_check, p, jobs)
        if okw and w then out.well_check = w end
        if p.renewed then out.renewed = p.renewed end
    end
    return out
end

-- Buildings inside the project's area: placed, built, and still waiting for
-- materials (only buildingplan's own "planned" list counts as waiting, so
-- furniture that already has its materials isn't ordered again).
-- (layout B, B16) A floor level's box (round all its rooms) can hold a neighbour's rooms on the
-- same hall: for a floor level a building counts only when its middle tile is one the level dug.
-- nil for any other level (its box is its own).
function own_tile_test(p)
    if type(p.floor) ~= 'table' then return nil end
    local a = anchor_of(p)
    if type(a) ~= 'table' then return nil end
    local own = layouts.tiles_from_dig(cells_of(p, 'dig'))
    return function(b)
        local x, y = (b.x1 + b.x2) // 2 - a.x, (b.y1 + b.y2) // 2 - a.y
        return own[x] ~= nil and own[x][y] == true
    end
end

-- (F4, S2) The boxes a reader counts or places in (tombs opened, coffins put in a corner):
-- project_areas(p), but a floor level's is its rooms' box alone (copied, never the saved
-- table) with own(b): true when the middle tile of b (anything with x1, y1, x2, y2) is one
-- of the level's own room tiles -- never the main hall (its links), never a neighbour's room.
function own_areas(p)
    local a, box = anchor_of(p), p.area
    if type(p.floor) ~= 'table' or type(a) ~= 'table' or type(box) ~= 'table' then return project_areas(p) end
    local own = layouts.tiles_from_dig(cells_of(p, 'dig'))
    for _, l in ipairs(type(p.links) == 'table' and p.links or {}) do
        if type(l) == 'table' and l.x ~= nil and own[l.x] then own[l.x][l.y] = nil end
    end
    local ax, ay = a.x, a.y
    return {{x1 = box.x1, y1 = box.y1, x2 = box.x2, y2 = box.y2, z = box.z,
             own = function(b)
                 local x, y = (b.x1 + b.x2) // 2 - ax, (b.y1 + b.y2) // 2 - ay
                 return own[x] ~= nil and own[x][y] == true
             end}}
end

-- (r9, audit A3 17) the buildings on level z. Inside a report (ai-util
-- REPORT_CTX) the fort's buildings are walked once and kept by level, so the
-- levels being furnished (War-hold: four) no longer walk them each; outside
-- one, a walk as before.
local function buildings_on(z)
    local okc, ctx = pcall(function() return util_module().REPORT_CTX end)
    if not (okc and type(ctx) == 'table') then return df.global.world.buildings.all, false end
    local by_z = ctx.buildings_by_z
    if not by_z then
        by_z = {}
        for _, b in ipairs(df.global.world.buildings.all) do
            local l = by_z[b.z]
            if not l then l = {}; by_z[b.z] = l end
            l[#l + 1] = b
        end
        ctx.buildings_by_z = by_z
    end
    return by_z[z] or {}, true
end

function furnish_progress(p)
    local placed, done, waiting, shops = 0, 0, {}, nil
    local a = p.area
    local mine = own_tile_test(p)       -- (layout B)
    for _, b in ipairs((buildings_on(a.z))) do
        if b.z == a.z and b.x1 >= a.x1 and b.x2 <= a.x2 and b.y1 >= a.y1 and b.y2 <= a.y2
                and (not mine or mine(b)) then
            local t = b:getType()
            if t ~= df.building_type.Stockpile and t ~= df.building_type.Civzone then
                placed = placed + 1
                -- 'exists' = actually built, not just planned
                if b.flags.exists then
                    done = done + 1
                elseif is_planned(b) then
                    local name = df.building_type[t] or tostring(t)
                    waiting[name] = (waiting[name] or 0) + 1
                    -- (0.105.51) a planned workshop or furnace by its kind (a
                    -- Quern waits for a quern, a Millstone for a millstone and
                    -- a mechanism): the brain orders the piece it lacks
                    local oks, st = pcall(function() return b:getSubtype() end)
                    local sub
                    if oks and t == df.building_type.Workshop then
                        sub = df.workshop_type[st]
                    elseif oks and t == df.building_type.Furnace then
                        sub = df.furnace_type[st]
                    end
                    if sub then
                        shops = shops or {}
                        shops[sub] = (shops[sub] or 0) + 1
                    end
                end
            end
        end
    end
    return {placed = placed, done = done, waiting = waiting, waiting_shops = shops}
end

-- A {year, tick} date as ticks, or nil.
local function tick_of(d)
    return type(d) == 'table' and (tonumber(d.year) or 0) * 403200 + (tonumber(d.tick) or 0) or nil
end

-- (R2 h3) A furnish progress's missing pieces in one word ("Bed:1,Box:1"; '' none):
-- what park_project keeps, and what the level waits on while it is parked.
function furnish_sig(f)
    local keys = {}
    for k, n in pairs(type(f) == 'table' and type(f.waiting) == 'table' and f.waiting or {}) do
        if (tonumber(n) or 0) > 0 then table.insert(keys, tostring(k) .. ':' .. math.floor(tonumber(n))) end
    end
    table.sort(keys)
    return table.concat(keys, ',')
end

-- (R2 h3) Parked: the brain parked it (park_project) and it still waits on the
-- very pieces it was parked for. Once one comes (or another goes missing) it is
-- an ordinary level again and holds its slot. f: its furnish_progress, if known.
function is_parked(p, f)
    if type(p) ~= 'table' or p.phase ~= 'furnish' or type(p.parked) ~= 'table'
            or type(p.parked.sig) ~= 'string' or p.parked.sig == '' then
        return false
    end
    if f == nil then
        local ok, got = pcall(furnish_progress, p)
        if not ok then return false end
        f = got
    end
    return furnish_sig(f) == p.parked.sig
end

-- (R2 h3) the small need a project (or a start_project's params) is for, or nil:
-- its `need` (NEED_KINDS), or a strange mood's workshops level (R1 g6)
function project_need(p, kind)
    if type(p) ~= 'table' then return nil end
    local need = p.need
    if need == nil and type(p.params) == 'table' then need = p.params.need end
    if NEED_KINDS[need] then return need end
    local mood = p.mood == true or (type(p.params) == 'table' and p.params.mood == true)
    if mood and (kind or p.kind) == 'workshops' then return 'mood' end
    return nil
end

local function urgent_shops(q)
    return q.kind == 'workshops' and (q.urgent == true or (type(q.params) == 'table' and q.params.urgent == true))
end

-- (R2 h3) the needs' pool in use: open small-need levels (and, as R1 g6 counted
-- them, urgent workshops levels), a parked one not counted
function need_slots_used(open)
    local n = 0
    for _, q in ipairs(open or {}) do
        if (project_need(q) or urgent_shops(q)) and not is_parked(q) then n = n + 1 end
    end
    return n
end

-- (R2 h3) May a small need start over the ordinary cap? (R1 g6's mood rule, for
-- every need): while fewer than NEED_SLOTS of the pool are open
function need_slot_free(open, params, kind)
    if not project_need(params, kind) then return false end
    return need_slots_used(open) < NEED_SLOTS
end

-- (0.104.142) The open-project cap: the base, plus a slot for each level
-- furnishing FURNISH_LEND_DAYS or more (FURNISH_LEND_MAX at most).
-- (D0, G6) A landmark takes one slot whatever its levels: each level past the
-- first is a project of its own (kind 'landmark', one params.landmark_id), so
-- it adds a slot back, and lends once; a surface landmark being built has no
-- project at all, so it takes one (landmarks_open_surface, ai-builder-landmarks)
-- (R2 h3) and a slot back for each parked level (PARK_MAX at most) and for each
-- small need's level (NEED_SLOTS at most: they have their own pool), so neither
-- holds an ordinary slot; a level is counted once (parked first, then need, then lent)
-- (y2 W4) and one back for the lone crossbows Bowyer's level (r2h4 starts it past the cap)
function slot_cap(open)
    local lent, again, seen, parked, needs, bow = 0, 0, {}, 0, 0, 0
    for _, p in ipairs(open or {}) do
        local lid = p.kind == 'landmark' and type(p.params) == 'table' and p.params.landmark_id or nil
        local dup = lid ~= nil and seen[lid] == true
        if lid ~= nil then seen[lid] = true end
        if dup then
            again = again + 1
        elseif parked < PARK_MAX and is_parked(p) then
            parked = parked + 1
        elseif project_need(p) then
            needs = needs + 1
        elseif bow == 0 and p.kind == 'workshops'
                and (p.crossbows == true or (type(p.params) == 'table' and p.params.crossbows == true)) then
            bow = 1                     -- (y2 W4) the lone crossbows Bowyer's level: no slot once open either
        elseif p.phase == 'furnish' then
            local since = tick_of(p.furnish_started)
            if since and (now_tick() - since) // 1200 >= FURNISH_LEND_DAYS then lent = lent + 1 end
        end
    end
    local surface = 0
    if type(landmarks_open_surface) == 'function' then
        local ok, n = pcall(landmarks_open_surface)
        if ok and math.tointeger(n) then surface = n end
    end
    return MAX_OPEN_PROJECTS + math.min(FURNISH_LEND_MAX, lent) + parked + math.min(NEED_SLOTS, needs)
        + bow + again - surface
end

-- (R2 h3) Parks a level being furnished that has waited on the same pieces for the
-- brain's h3_park_days (sig: its furnish sig as the report gave it; refused if it
-- changed since): it stops holding a building slot (slot_cap) and stays open, its
-- pieces still ordered, until one of them comes.
function park_project(id, sig, dry_run)
    local data = load_projects()
    local p
    for _, q in ipairs(data.list) do if q.id == id then p = q end end
    if not p or p.phase ~= 'furnish' then
        return {ok = false, rejected = true, error = 'not a project being furnished'}
    end
    local f = furnish_progress(p)
    local now_sig = furnish_sig(f)
    if now_sig == '' then
        return {ok = false, rejected = true, error = 'nothing is missing: it finishes instead'}
    end
    if type(sig) == 'string' and sig ~= '' and sig ~= now_sig then
        return {ok = false, rejected = true, error = ('its missing pieces changed (%s, was %s)'):format(now_sig, sig)}
    end
    if is_parked(p, f) then
        return {ok = true, project_id = id, parked = true, sig = now_sig, already = true}
    end
    if dry_run then return {ok = true, project_id = id, parked = true, sig = now_sig, dry_run = true} end
    p.parked = {sig = now_sig, year = now_tick() // 403200, tick = now_tick() % 403200}
    if not save_projects(data) then return {ok = false, error = 'could not save the project with the fort'} end
    return {ok = true, project_id = id, parked = true, sig = now_sig}
end

-- Smoothing progress: how many cells still have a smoothing job waiting.
function decor_progress(p)
    local a = anchor_of(p)
    local total, waiting, done, marked = 0, 0, 0, 0
    for _, c in ipairs(cells_of(p, 'smooth')) do
        total = total + 1
        local t = tile_info(a.x + c.x, a.y + c.y, p.z)
        if t and t.smoothing and t.marked then marked = marked + 1   -- marker mode: never dug
        elseif t and t.smoothing then waiting = waiting + 1
        elseif t and t.smoothed then done = done + 1 end
    end
    local since = tick_of(p.decorate_started)
    local days = since and math.max(0, (now_tick() - since) // 1200) or 0
    return {smooth_total = total, smooth_waiting = waiting, smooth_done = done, smooth_marked = marked,
            engrave_total = #cells_of(p, 'engrave'), days_waiting = days,
            timed_out = p.phase == 'decorate' and days >= DECOR_TIMEOUT_DAYS}
end

-- What the overseer should do next for this project, if anything.
local function next_step(p, r)
    -- (0.105.24) a well the game refused: tried again only after its wait
    if p.kind == 'well' and p.phase == 'dig' and tonumber(p.well_retry_at) and now_tick() < p.well_retry_at then
        return false
    end
    -- (merge32) an emergency way in has nothing to build: finished once dug
    if p.kind == 'way_in' and p.phase == 'dig' and r.dig and r.dig.total > 0 and r.dig.dug == r.dig.total then
        return 'finish'
    end
    -- (0.105.33, L4) a way in with a step missing is no way in: never
    -- furnished as if dug; once nothing else is left, it is given up
    if p.kind == 'way_in' then
        -- (0.105.36 D3) a marker-only step the AI already tried to make real counts as missing
        local missing = r.dig and (r.dig.stuck + (p.unmark_tried and r.dig.marked or 0)) or 0
        if p.phase == 'dig' and r.dig and missing > 0
                and r.dig.dug + r.dig.stuck + r.dig.marked == r.dig.total then
            return 'cancel'
        end
        return false
    end
    if p.phase == 'dig' and r.dig and r.dig.total > 0 and r.dig.dug == r.dig.total then
        return 'furnish'
    elseif p.phase == 'dig' and r.dig and r.dig.stuck > 0 and r.dig.shaft_open ~= false
            and r.dig.dug + r.dig.stuck + r.dig.marked == r.dig.total then
        -- Everything still designated is dug; the rest was cancelled (by the
        -- game, e.g. damp stone, or by the player). A few rock spots are
        -- fine: furnish what's there. Too many: give up on this site.
        return r.dig.stuck * 5 <= r.dig.total and 'furnish' or 'cancel'
    elseif p.phase == 'furnish' and r.furnish and r.furnish.done == r.furnish.placed then
        return 'finish'
    elseif p.phase == 'decorate' and r.decor and (r.decor.smooth_waiting == 0 or r.decor.timed_out) then
        return 'engrave'
    end
    return false      -- (false, not nil, so the key reaches Python)
end

-- Report section: every unfinished project. Projects that are only waiting
-- for decoration (engraving) are listed separately and don't use up a slot.
function projects_report()
    OFFSET = elevation_offset()
    local data = load_projects()
    local out, decorating, finished = {}, {}, 0
    for _, p in ipairs(data.list) do
        if p.phase == 'dig' or p.phase == 'furnish' or p.phase == 'decorate' then
            local r = {id = p.id, kind = p.kind, phase = p.phase, z = p.z, elevation = ez(p.z),
                       summary = p.summary, furniture = p.furniture, started = p.started,
                       -- (0.105.48, A3 14) the planner's "dig first" and well rules read these
                       urgent = (p.urgent == true or (type(p.params) == 'table' and p.params.urgent == true)) or nil,
                       dig_done = p.dig_done}
            if p.phase == 'dig' then r.dig = dig_progress(p) end
            -- (y2 W1) a floor level (layout B): its floor and the new hall tiles it digs first
            -- (its rooms open off them: unreached until they are dug)
            if type(p.floor) == 'table' then
                r.floor = {id = p.floor.id, hall = math.tointeger(p.floor.hall) or 0}
            end
            -- (0.92) a hall built for a petition: what it's dedicated to
            local pr = type(p.params) == 'table' and p.params or {}
            if pr.profession or pr.deity_hf or pr.religion then
                r.dedication = {profession = pr.profession, deity_hf = pr.deity_hf, religion = pr.religion}
            end
            if p.phase == 'furnish' then
                r.furnish = furnish_progress(p)
                local since = tick_of(p.furnish_started)
                r.furnish.days = since and math.max(0, (now_tick() - since) // 1200) or 0
                -- (R2 h3) what it waits on in one word, and whether it is parked (holds no slot)
                r.furnish.sig = furnish_sig(r.furnish)
                if type(p.parked) == 'table' then
                    r.parked = is_parked(p, r.furnish)
                    local pt = tick_of(p.parked)
                    r.parked_days = pt and math.max(0, (now_tick() - pt) // 1200) or nil
                end
            end
            r.need = project_need(p)       -- (R2 h3) the small need it is for (its own pool)
            if p.phase ~= 'dig' then r.decor = decor_progress(p) end
            -- (0.105.24) a well the game refused: how often, and what it showed
            if p.kind == 'well' and p.well_refusals then
                r.well_refused = {times = p.well_refusals, landing = p.landing,
                                  seen = type(p.well_diag) == 'table' and p.well_diag.text or nil}
            end
            r.next = next_step(p, r) or false
            table.insert(p.phase == 'decorate' and decorating or out, r)
        elseif p.phase == 'done' then
            finished = finished + 1
        end
    end
    -- (0.105.48, K7c) the report changes nothing: lost tiles are put back by redig_projects
    local okc, cap = pcall(slot_cap, open_projects(data))
    local okl, lids = pcall(well_lids, true, data)     -- (0.104.151)
    -- (0.105.33, industry 2) `finished` counts only the KEEP_CLOSED_PROJECTS
    -- kept closed ones (20 at most); done_total every level ever finished
    return {open = out, decorating = decorating, finished = finished, done_total = done_total(data),
            max_open = okc and cap or MAX_OPEN_PROJECTS,
            -- (R2 h3) the small needs' pool: free places (need_slot_free)
            need_slots_free = (function()
                local ok, n = pcall(need_slots_used, open_projects(data))
                return ok and math.max(0, NEED_SLOTS - n) or nil
            end)(),
            max_open_base = MAX_OPEN_PROJECTS, well_lids = (okl and #lids > 0) and lids or nil,
            well_lids_error = (not okl) and tostring(lids):sub(1, 120) or nil}
end

-- (0.105.48, K7c) The action that puts back what projects_report counts as
-- redig_due: a well's shaft and its stairs, a gallery, a way in's steps that
-- lost their designation, each tile at most REDIG_MAX times (counted in the
-- project). Was done inside the report (every cycle, halted or not).
function redig_projects(dry_run)
    local data = load_projects()
    local n, projects, changed = 0, {}, false
    for _, p in ipairs(data.list) do
        if p.phase == 'dig' then
            local d = dig_progress(p, true, dry_run == true)
            local k = dry_run and (d.redig_due or 0) or (d.redesignated or 0)
            if k > 0 then
                n = n + k
                table.insert(projects, p.id)
            end
            if p.redug_changed then p.redug_changed, changed = nil, true end
        end
    end
    if changed and not dry_run then pcall(save_projects, data) end
    if n == 0 and not changed then
        return {ok = false, rejected = true, error = 'no lost shaft, stair or gallery tile to designate again'}
    end
    return {ok = true, dry_run = dry_run == true or nil, tiles = n, projects = projects}
end

-- The box a project covers, in map coordinates: {x1, y1, x2, y2, z}, from
-- its dig cells (or its build cells if nothing was dug). nil if no cells.
function bounds_of(p)
    local a = anchor_of(p)
    if type(a) ~= 'table' or type(p.cells) ~= 'table' then return nil end
    local cells = type(p.cells.dig) == 'table' and p.cells.dig or {}
    if #cells == 0 then cells = type(p.cells.build) == 'table' and p.cells.build or {} end
    local x1, y1, x2, y2
    for _, c in ipairs(cells) do
        if type(c) == 'table' and type(c.x) == 'number' and type(c.y) == 'number' then
            x1 = math.min(x1 or c.x, c.x); x2 = math.max(x2 or c.x, c.x)
            y1 = math.min(y1 or c.y, c.y); y2 = math.max(y2 or c.y, c.y)
        end
    end
    if not x1 then return nil end
    return {x1 = a.x + x1, y1 = a.y + y1, x2 = a.x + x2, y2 = a.y + y2, z = p.z}
end

REGISTRY_MAX = 400

-- Report section: every AI project still on record (any phase), newest
-- last, for the overseer's map of what it built where.
function registry_report()
    OFFSET = elevation_offset()
    local list = load_projects().list
    local out = {}
    for i = math.max(1, #list - REGISTRY_MAX + 1), #list do
        local p = list[i]
        local params = type(p.params) == 'table' and p.params or {}
        local plan = type(p.plan) == 'table' and p.plan or {}
        table.insert(out, {id = p.id, kind = p.kind, phase = p.phase, z = p.z,
                           elevation = p.z and ez(p.z) or nil, bounds = bounds_of(p),
                           style = params.style, name = params.name, started = p.started,
                           district = plan.district, in_district = p.in_district,
                           -- (D0, G6) a landmark's level: named after its landmark, and which
                           landmark_id = p.kind == 'landmark' and params.landmark_id or nil,
                           joins = p.parent,    -- (0.105.54) an annex: shops added to that workshops level
                           level = p.kind == 'landmark' and params.level or nil})
    end
    return out
end
