-- ai-gates-works: the gate works: stockpiles moved out of the way, fortify(), mechanisms and
-- lever links, the AI's own levers, clear_gate, traps and the gatehouse.
--
-- (13e) A part of ai-gates, not a script of its own: ai-gates.lua loads it
-- into its own environment, so every name here is reqscript('ai-gates').name
-- and the helpers defined there (tile, building_at, key, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-gates-works'] = '0.105.40'   -- (0.105.26) bumped with BRIDGE_VERSION

local U, key, unkey, T, interior, moves, inside_or_courtyard, DOOR_GROUND, citizen_starts, place, entrance = U, key, unkey, T, interior, moves, inside_or_courtyard, DOOR_GROUND, citizen_starts, place, entrance   -- (13e) the hub's and earlier parts' locals

---------------------------------------------------------------------------
-- A stockpile in the way of a gate: the AI moves it itself. The new pile
-- gets the old one's settings (DFHack's stockpiles export/import) and goes
-- on the part of the old pile that's clear of the opening, or, if too little
-- is left, on free floor nearby inside the fort. Items left on the old tiles
-- are hauled to it by the dwarves.
---------------------------------------------------------------------------

MOVE_CLEARANCE = 2     -- tiles kept free between the opening and the pile
MOVE_RADIUS = 25       -- how far from the old pile a new spot may be
MOVE_MIN_TILES = 4

-- The opening's tiles that already have a door, built or planned: {key = true}
-- (tests replace this).
function doors_in(list)
    local out = {}
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if b and b:getType() == df.building_type.Door then out[k] = true end
    end
    return out
end

-- The stockpiles on an opening's tiles: {building, ...} (tests replace this).
function stockpiles_in(list)
    local out, seen = {}, {}
    for _, k in ipairs(list) do
        local x, y, z = unkey(k)
        local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
        if b and b:getType() == df.building_type.Stockpile and not seen[b.id] then
            seen[b.id] = true
            table.insert(out, b)
        end
    end
    return out
end

-- The largest rectangle of tiles that pass ok(x, y), inside the box, no
-- bigger than max_side: {x, y, w, h} or nil.
local function best_rect(x1, y1, x2, y2, ok, max_side)
    local best, best_n
    for y = y1, y2 do
        for x = x1, x2 do
            if ok(x, y) then
                local w = 1
                while w < max_side and x + w <= x2 and ok(x + w, y) do w = w + 1 end
                local h = 1
                while h < max_side and y + h <= y2 do
                    local row = true
                    for dx = 0, w - 1 do if not ok(x + dx, y + h) then row = false break end end
                    if not row then break end
                    h = h + 1
                end
                if not best_n or w * h > best_n then best, best_n = {x = x, y = y, w = w, h = h}, w * h end
            end
        end
    end
    return best
end

-- Where the moved pile goes: {x, y, z, w, h} or nil, why.
function new_pile_spot(pile, avoid)
    local z = pile.z
    local function clear(x, y)
        for dx = -MOVE_CLEARANCE, MOVE_CLEARANCE do
            for dy = -MOVE_CLEARANCE, MOVE_CLEARANCE do
                if avoid[key(x + dx, y + dy, z)] then return false end
            end
        end
        return true
    end
    -- 1. what's left of the old pile, clear of the opening
    local inside_old = function(x, y)
        return dfhack.buildings.containsTile(pile, x, y) and clear(x, y)
    end
    local r = best_rect(pile.x1, pile.y1, pile.x2, pile.y2, inside_old, 20)
    if r and r.w * r.h >= MOVE_MIN_TILES then
        r.z, r.kept = z, true
        return r
    end
    -- 2. free floor inside the fort nearby, about as big as the old pile
    local want = math.max(MOVE_MIN_TILES, math.min(100, (pile.x2 - pile.x1 + 1) * (pile.y2 - pile.y1 + 1)))
    local side = math.max(2, math.min(10, math.ceil(math.sqrt(want))))
    local W, H = map_size()
    local function free(x, y)
        if x < 1 or y < 1 or x > W - 2 or y > H - 2 or not clear(x, y) then return false end
        local t = T(x, y, z)
        return t ~= nil and interior(t) and DOOR_GROUND[t.shape] and not t.liquid and not t.occupied
    end
    r = best_rect(pile.x1 - MOVE_RADIUS, pile.y1 - MOVE_RADIUS, pile.x2 + MOVE_RADIUS, pile.y2 + MOVE_RADIUS,
                  free, side)
    if r and r.w * r.h >= MOVE_MIN_TILES then
        r.z = z
        return r
    end
    return nil, 'no free floor inside the fort near it'
end

move_hook = nil        -- tests replace this
-- Move one stockpile out of an opening. Returns ok, text.
function move_stockpile(pile, avoid)
    if move_hook then return move_hook(pile, avoid) end
    local spot, why = new_pile_spot(pile, avoid)
    if not spot then return false, why end
    local qf = reqscript('quickfort')
    local function put(r, command, dry)
        local cell = ('c(%dx%d)'):format(r.w, r.h)
        local ok, stats = pcall(qf.apply_blueprint, {mode = 'place', data = {[r.z] = {[r.y] = {[r.x] = cell}}},
                                                     pos = {x = 0, y = 0, z = 0}, command = command or 'run',
                                                     dry_run = dry})
        return ok and stats and stats.place_designated and stats.place_designated.value > 0
    end
    local old_name, old_id = pile.name, pile.id
    local file = ('ai-move-%d'):format(old_id)
    -- (0.100) the command's own result too: pcall only catches a Lua error, and a
    -- failed export meant the pile was moved without its settings
    local okx, _, rvx = pcall(dfhack.run_command_silent, 'stockpiles', 'export', file, '-s', tostring(old_id))
    if not okx or rvx ~= CR_OK then return false, 'could not copy its settings' end
    local old_box = {x = pile.x1, y = pile.y1, z = pile.z, w = pile.x2 - pile.x1 + 1, h = pile.y2 - pile.y1 + 1}
    if not spot.kept and not put(spot, 'run', true) then return false, 'the game would not take a stockpile there' end
    dfhack.buildings.deconstruct(pile)        -- a stockpile goes at once; its items stay where they lie
    if not put(spot) then
        put(old_box)                         -- put it back where it was, rather than lose it
        return false, 'the game refused the new stockpile, so the old one was put back'
    end
    local new = dfhack.buildings.findAtTile(xyz2pos(spot.x, spot.y, spot.z))
    if new and new:getType() == df.building_type.Stockpile then
        pcall(dfhack.run_command_silent, 'stockpiles', 'import', file, '-s', tostring(new.id))
        if old_name and #old_name > 0 then new.name = old_name end
    end
    cache = {}                               -- the opening's tiles are free now
    return true, ('%s %dx%d at x%d y%d'):format(spot.kept and 'kept' or 'moved to', spot.w, spot.h, spot.x, spot.y)
end

function fortify(id, style, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if not GAP[style] then return {ok = false, rejected = true, error = 'unknown gate style ' .. tostring(style)} end
    -- (0.105.30 fixes) the depot's wagon road takes no door whatever style
    -- is asked: the wagon style (a 3-wide drawbridge, or left open)
    local asked_style
    if e.deep_road and style ~= 'wagon' then asked_style, style = style, 'wagon' end
    -- (0.105.33) where the fort's citizens are, as the scan reads them
    -- (fort_starts: not a ledge, a treetop, the AI keep/hall or the deep depot hall)
    starts = starts or fort_starts(citizen_starts())
    cache, edge_cache = {}, {}      -- the map may have changed since the scan
    -- stockpiles in the opening are moved out of the way first
    local moved = {}
    local avoid = {}
    for _, k in ipairs(e.inside_list) do avoid[k] = true end
    for k in pairs(e.outs) do avoid[k] = true end
    local ok_list, piles = pcall(stockpiles_in, e.inside_list)
    for _, pile in ipairs(ok_list and piles or {}) do
        local ok, text = move_stockpile(pile, avoid)
        if not ok then
            return {ok = false, error = 'a stockpile is in the opening and could not be moved: ' .. tostring(text)}
        end
        table.insert(moved, text)
    end
    local okd, doors_present = pcall(doors_in, e.inside_list)
    local plan, why = plan_gate(e, style, starts, okd and doors_present or {})
    if not plan then return {ok = false, error = why} end
    local out, failed = {walls = 0, doors = 0, inner_doors = 0, traps = 0, statues = 0, doors_later = 0,
                         support_walls = 0, hatches = 0}, {}
    out.pieces = {}                 -- every tile it placed on ("x,y,z"), so the gate can be taken down exactly
    out.asked_style = asked_style
    local wall_keys = {}
    local function put(list, key_text, field)
        for _, k in ipairs(list) do
            local x, y, z = unkey(k)
            if key_text == 'd' and e.deep_road then
                -- (0.105.30 fixes) never a door on the depot's wagon road
                out.doors_refused = (out.doors_refused or 0) + 1
            elseif key_text == 'd' and not wall_beside(x, y, z) then
                -- its walls are only planned: the door is added once they're
                -- built (the next scans see a narrow gap between walls)
                out.doors_later = out.doors_later + 1
            else
                local ok, reason = place(key_text, {x = x, y = y, z = z})
                if ok then
                    out[field] = out[field] + 1
                    if #out.pieces < 80 then table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z)) end
                    if key_text == 'Cw' then table.insert(wall_keys, ('%d,%d,%d'):format(x, y, z)) end
                else
                    table.insert(failed, key_text .. ':' .. tostring(reason))
                end
            end
        end
    end
    put(plan.walls, 'Cw', 'walls')
    if plan.sealed then pcall(note_sealed, wall_keys) end     -- (0.105.30 fixes) clear_gate's record under rock
    put(plan.support, 'Cw', 'support_walls')
    put(plan.hatches, 'H', 'hatches')
    put(plan.doors, 'd', 'doors')
    if plan.bridge then
        -- the lever first: where the dwarves are, away from this gate. No such
        -- spot, or the game refuses the bridge: doors in the gap instead, so
        -- the opening is never left with nothing to close it
        local br = plan.bridge
        local spot = lever_spot(starts, e)
        local placed_bridge = false
        if spot then
            local text = ('%s(%dx%d)'):format(br.dir, br.w, br.h)
            local ok, reason = place(text, {x = br.x, y = br.y, z = br.z})
            if ok then
                placed_bridge = true
                out.bridge = {x = br.x, y = br.y, z = br.z, w = br.w, h = br.h}
                local okl, why = place('Tl', spot)
                if okl then
                    name_at(spot, LEVER_NAME)
                    out.lever = spot
                else
                    -- the player's own "AI gate" lever, if free, is linked instead
                    table.insert(failed, 'Tl:' .. tostring(why))
                end
            else
                table.insert(failed, text .. ':' .. tostring(reason))
            end
        else
            out.bridge_note = 'no free floor for its lever where the dwarves are, away from the gate: doors instead'
        end
        if not placed_bridge and style == 'wagon' then
            -- (0.105.30) never doors on the depot's wagon road: left open, said so
            out.bridge_note = (out.bridge_note and (out.bridge_note .. '; ') or '')
                .. 'no doors on the underground depot\'s wagon road: it stays open'
        elseif not placed_bridge then
            put(br.keys, 'd', 'doors')
            out.style = 'plain'
        end
    end
    put(plan.inner, 'd', 'inner_doors')
    put(plan.traps, 'Tc', 'traps')
    put(plan.statues, 's', 'statues')
    out.kept_doors = plan.kept_doors
    -- (0.105.32) a door or hatch put where a stuck one was taken down: never on a lever for a year
    for _, list in ipairs({plan.hatches or {}, plan.doors or {}}) do
        for _, k in ipairs(list) do
            local hx, hy, hz = unkey(k)
            local oks, at = pcall(stuck_spot, hx, hy, hz)
            if oks and at and not out.no_lever then
                out.no_lever = {x = hx, y = hy, z = hz}
                out.no_lever_why = 'a gate there stayed shut for DF though it read open and was taken down: '
                    .. 'no lever drives the new one for a year (the watcher locks it)'
            end
        end
    end
    if plan.water then out.water = plan.water end
    if plan.water_gate then
        out.ok, out.water_gate, out.style = true, true, style
        return out
    end
    if plan.shore then
        local x, y, z = unkey(plan.walls[1] or plan.doors[1] or e.inside_list[1])
        out.shore, out.line = true, {x = x, y = y, z = z}
    end
    if plan.moved_in then
        local x, y, z = unkey((plan.walls[1] or plan.doors[1] or plan.support[1]) or e.inside_list[1])
        out.moved_in, out.moved_why = plan.moved_in, plan.moved_why
        out.line = {x = x, y = y, z = z}
    end
    out.ok = out.walls + out.doors + out.support_walls + out.hatches + (out.bridge and 1 or 0) > 0
    out.style = out.style or style
    if #failed > 0 then out.failed = table.concat(failed, '; '):sub(1, 300) end
    if #moved > 0 then out.stockpiles_moved = table.concat(moved, '; ') end
    if out.ok and out.support_walls > 0 and out.doors_later > 0 then
        out.note = 'a wall goes beside the door first; the door follows once it is built'
    end
    if not out.ok and out.doors_later > 0 and not out.failed then
        local x, y = unkey(plan.doors[1] or e.inside_list[1])
        out.error = ('a door needs a wall beside it, and there is none at x%d y%d (nothing to hang a door on '
            .. 'there, and walling it shut would cut the way through)'):format(x, y)
    elseif not out.ok then
        out.error = 'nothing could be placed (' .. (out.failed or '?') .. ')'
    end
    return out
end

---------------------------------------------------------------------------
-- Linking a lever to a bridge, door or hatch. Quickfort can't link, so the AI
-- makes DF's own LinkBuildingToTrigger job on the lever, with two free
-- mechanisms: one goes into the target (LinkToTarget), one into the lever
-- (LinkToTrigger). A dwarf with the mechanic labour does it. The defence
-- probe found every part of this in DF 53.16; dry_run checks without acting.
---------------------------------------------------------------------------

LINK_TARGETS = {Bridge = true, Door = true, Hatch = true, Floodgate = true, GrateFloor = true, BarsFloor = true,
                GearAssembly = true}      -- (0.105.37 E3) the pump stack's power switch (ai-waterworks.lua)

-- Mechanisms no one is using: {item, ...} (tests replace this).
-- (0.94.1) Why a mechanism can't be used for a link (nil when it can).
-- The cistern counted its mechanisms more loosely than the link takes them
-- (region2: "2 free" in the report, "0 free" at the link, 146 refusals), so
-- both now use this one test, and the report says what holds the others.
local function item_pos(it)
    local ok, x, y, z = pcall(dfhack.items.getPosition, it)
    if not ok or x == nil then return nil end
    if type(x) == 'table' or type(x) == 'userdata' then
        local okp, p = pcall(function() return {x = x.x, y = x.y, z = x.z} end)
        return okp and p or nil
    end
    return {x = x, y = y, z = z}
end

local function group_at(p)
    if not p or not (dfhack.maps and dfhack.maps.getWalkableGroup) then return nil end
    local ok, g = pcall(dfhack.maps.getWalkableGroup, xyz2pos(p.x, p.y, p.z))
    return ok and g or nil
end

-- The walkable group a dwarf reaches the item from: its own tile, or for
-- one held in a workshop (whose own tiles may be impassable) a walkable tile
-- beside it. nil when unread (no map API: the tests), 0 when none.
local function reach_group(it, in_shop)
    local p = item_pos(it)
    if not p then return nil end
    local g = group_at(p)
    if g == nil or g ~= 0 or not in_shop then return g, p end
    for dy = -1, 1 do
        for dx = -1, 1 do
            local g2 = group_at({x = p.x + dx, y = p.y + dy, z = p.z})
            if g2 and g2 ~= 0 then return g2, p end
        end
    end
    return 0, p
end

UNWALKABLE_AT = {}       -- (0.104.156) where the last unwalkable mechanisms lay (3 at most)

function mechanism_unusable(it)
    local _, why = U.item_unfree(it)       -- (lua/ai-util.lua's list)
    if why then return why end
    local okb, b = pcall(dfhack.items.getHolderBuilding, it)
    if okb and b then
        local okt, t = pcall(function() return df.building_type[b:getType()] end)
        -- (0.95.1) one made and left in its workshop (no stockpile takes it
        -- yet) is a stored product, not a part of the building: a job takes
        -- it from there. region2's 5 mechanisms all sat in the Mechanic's
        -- workshop, and the cistern ordered more that sat there too.
        if okt and (t == 'Workshop' or t == 'Furnace') then return nil end
        return 'held in a ' .. tostring(okt and t or 'building')
    end
    -- (0.104.156) Teacheroar, 1 Nov: 2 of the 3 "free" mechanisms lay at x92
    -- y106 z168, a tile no dwarf can walk to; every link took them first and
    -- DF cancelled it ("Item inaccessible"), and no rule ordered more
    local g, p = reach_group(it, false)
    if g == 0 then
        if p and #UNWALKABLE_AT < 3 then table.insert(UNWALKABLE_AT, ('x%d y%d z%d'):format(p.x, p.y, p.z)) end
        return 'where no dwarf can walk'
    end
    return nil
end

-- (0.104.156) `near` (a position): only mechanisms a dwarf can walk to from
-- there (the same walkable group), nearest first. Teacheroar, 1 Nov: the
-- cavern well's link job took the first two in the item list and DF
-- cancelled it each time ("Link a building to trigger: Item inaccessible"),
-- 25 times in 2 hours; the cistern's lever lost its link 3 times the same
-- way on 31 Oct. Returns the list and how many usable ones were out of reach.
function free_mechanisms(n, near)
    local out, cands, unreachable, far_at = {}, {}, 0, {}
    local want = near and group_at(near) or nil
    if want == 0 then want = nil end            -- the lever's own tile unread: no filter
    for _, it in ipairs(df.global.world.items.other.TRAPPARTS) do
        if not mechanism_unusable(it) then
            if want then
                local okb, hb = pcall(dfhack.items.getHolderBuilding, it)
                local g, p = reach_group(it, okb and hb ~= nil)
                if p and g == want then
                    local d = math.abs(p.x - near.x) + math.abs(p.y - near.y) + 3 * math.abs(p.z - near.z)
                    table.insert(cands, {it = it, d = d})
                else
                    unreachable = unreachable + 1
                    if p and #far_at < 3 then
                        table.insert(far_at, ('x%d y%d z%d (group %s)'):format(p.x, p.y, p.z, tostring(g)))
                    end
                end
            else
                table.insert(out, it)
                if #out >= n then break end
            end
        end
    end
    if want then
        table.sort(cands, function(a, b) return a.d < b.d end)
        for i = 1, math.min(n, #cands) do table.insert(out, cands[i].it) end
    end
    return out, unreachable, far_at
end

-- (0.94.1) The mechanisms there are: usable, taken by a job, and the rest by
-- why they can't be used (for the cistern's and the gates' reports).
function mechanism_counts()
    local out = {usable = 0, reserved = 0, why = {}}
    UNWALKABLE_AT = {}
    for _, it in ipairs(df.global.world.items.other.TRAPPARTS) do
        local why = mechanism_unusable(it)
        if not why then out.usable = out.usable + 1
        elseif why == 'taken by a job' then out.reserved = out.reserved + 1
        elseif why ~= 'gone' and why ~= 'in a building' then out.why[why] = (out.why[why] or 0) + 1 end
    end
    if #UNWALKABLE_AT > 0 then out.unwalkable_at = table.concat(UNWALKABLE_AT, '; ') end
    return out
end

-- The roles a job's items play. DF 53.16's structures call the enum
-- job_role_type (older ones: job_item_ref.T_role); found by name, never
-- assumed (an unknown name used to stop the link with a Lua error).
function link_roles()
    for _, get in ipairs({function() return df.job_role_type end,
                          function() return df.job_item_ref.T_role end}) do
        local ok, r = pcall(get)
        if ok and r ~= nil then
            local ok2, has = pcall(function() return r.LinkToTarget ~= nil and r.LinkToTrigger ~= nil end)
            if ok2 and has then return r end
        end
    end
    return nil
end

function link_lever(lever_id, target_id, dry_run)
    local lever = df.building.find(lever_id)
    if not lever or lever:getType() ~= df.building_type.Trap or lever.trap_type ~= df.trap_type.Lever then
        return {ok = false, rejected = true, error = 'no lever with id ' .. tostring(lever_id)}
    end
    local target = df.building.find(target_id)
    local tname = target and df.building_type[target:getType()]
    if not target or not LINK_TARGETS[tname] then
        return {ok = false, rejected = true, error = 'building ' .. tostring(target_id) .. ' is not a bridge, door or hatch'}
    end
    for _, b in ipairs({lever, target}) do
        if b:getBuildStage() < b:getMaxBuildStage() then
            return {ok = false, rejected = true, error = 'building ' .. b.id .. ' is not built yet'}
        end
    end
    -- (0.105.32) a gate DF held shut though it read open was taken down here:
    -- no lever drives a piece at this spot for a year (the watcher locks it)
    if (tname == 'Hatch' or tname == 'Door') and stuck_spot then
        local oks, at = pcall(stuck_spot, target.x1, target.y1, target.z)
        if oks and at then
            return {ok = false, rejected = true, stuck_spot = true,
                    error = ('a gate at x%d y%d z%d stayed shut for DF though it read open and was taken down: '
                        .. 'no lever drives a new one there for a year (the watcher locks it instead)'):format(
                        target.x1, target.y1, target.z)}
        end
    end
    local levers = lever_links()
    for _, lid in ipairs(levers[target_id] or {}) do
        if lid == lever_id then return {ok = false, rejected = true, error = 'that lever is already linked to it'} end
    end
    for _, j in ipairs(lever.jobs) do
        if j.job_type == df.job_type.LinkBuildingToTrigger then
            return {ok = false, rejected = true, error = 'a link job is already waiting at that lever'}
        end
    end
    local roles = link_roles()
    if not (roles and df.job_type.LinkBuildingToTrigger and roles.LinkToTarget and roles.LinkToTrigger
            and dfhack.job.addGeneralRef and dfhack.job.attachJobItem and dfhack.job.linkIntoWorld) then
        return {ok = false, rejected = true, error = 'this DF version has no lever-link job'}
    end
    local mechs, unreachable = free_mechanisms(2, {x = lever.centerx, y = lever.centery, z = lever.z})
    if #mechs < 2 then
        local held = {}
        local okc, c = pcall(mechanism_counts)
        if okc then for why, n in pairs(c.why) do table.insert(held, n .. ' ' .. why) end end
        if (unreachable or 0) > 0 then table.insert(held, unreachable .. ' out of reach of the lever') end
        table.sort(held)
        return {ok = false, error = ('a link needs 2 free mechanisms (%d free%s)'):format(#mechs,
                    #held > 0 and ('; ' .. table.concat(held, ', ')) or ''), mechanisms = #mechs}
    end
    if dry_run then return {ok = true, dry_run = true, target = tname, mechanisms = #mechs} end
    local job = df.job:new()
    job.job_type = df.job_type.LinkBuildingToTrigger
    job.pos = xyz2pos(lever.centerx, lever.centery, lever.z)
    dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, lever.id)
    dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_TRIGGERTARGET, target.id)
    if not (dfhack.job.attachJobItem(job, mechs[1], roles.LinkToTarget, -1, -1)
            and dfhack.job.attachJobItem(job, mechs[2], roles.LinkToTrigger, -1, -1)) then
        dfhack.job.linkIntoWorld(job, true)
        dfhack.job.removeJob(job)
        return {ok = false, error = 'the game would not attach the items to the link job'}
    end
    dfhack.job.linkIntoWorld(job, true)
    lever.jobs:insert('#', job)
    -- (0.105.23) once the mechanic links it, a door or hatch is shut by the
    -- link: the watch opens it again and gives it its lever at once
    if tname == 'Hatch' or tname == 'Door' then pcall(link_watch_start) end
    local ids = {}
    for _, m in ipairs(mechs) do table.insert(ids, m.id) end
    return {ok = true, job_id = job.id, target = tname, mechanism_ids = ids}
end

---------------------------------------------------------------------------
-- A lever the AI places itself for a drawbridge: on free floor where the
-- dwarves are (the middle of the citizens, on their busiest level), beside a
-- wall where it's out of the way. Named "AI gate lever" so the AI knows it.
---------------------------------------------------------------------------

LEVER_NAME = 'AI gate lever'

function lever_spot(starts, e)
    if not starts or #starts == 0 then return nil end
    -- away from the gate it works (as the watcher wants: 20+ tiles or 4+ levels)
    local function away(x, y, z)
        if not e then return true end
        return math.abs(z - e.z) > 3 or math.max(math.abs(x - e.x), math.abs(y - e.y)) >= LEVER_AWAY
    end
    -- the busiest level, then the middle of the citizens on it
    local per_z = {}
    for _, p in ipairs(starts) do per_z[p.z] = (per_z[p.z] or 0) + 1 end
    local bz, bn = nil, -1
    for z, n in pairs(per_z) do if n > bn or (n == bn and z < bz) then bz, bn = z, n end end
    local xs, ys = {}, {}
    for _, p in ipairs(starts) do if p.z == bz then table.insert(xs, p.x); table.insert(ys, p.y) end end
    table.sort(xs); table.sort(ys)
    local cx, cy = xs[(#xs + 1) // 2], ys[(#ys + 1) // 2]
    local best, best_d
    for r = 0, 24 do
        for dx = -r, r do
            for dy = -r, r do
                if math.max(math.abs(dx), math.abs(dy)) == r then
                    local x, y = cx + dx, cy + dy
                    local t = T(x, y, bz)
                    if t and interior(t) and DOOR_GROUND[t.shape] and not t.liquid and not t.occupied
                            and wall_beside(x, y, bz) and away(x, y, bz) then
                        local d = dx * dx + dy * dy
                        if not best_d or d < best_d then best, best_d = {x = x, y = y, z = bz}, d end
                    end
                end
            end
        end
        if best then return best end
    end
    return nil
end

-- Take down a gate the AI built at an entrance that turned out not to be one
-- (0.39 walled the shade of trees): the pieces it recorded (a gate with no
-- record is refused). Planned pieces are cancelled, built ones are marked for
-- removal by the dwarves.
GATE_PIECES_MAX, GATE_PIECE_REACH = 80, 15
local function surface_tile(x, y, z)
    local d = dfhack.maps.getTileFlags(x, y, z)
    return d ~= nil and not d.subterranean
end

-- (0.105.30 fixes) The walls the `sealed` style placed, kept with the save
-- ({"x,y,z", ...}): under rock clear_gate takes down only these.
SEALED_KEY = 'ai-overseer/sealed_walls'
SEALED_RECORD_MAX = 200

function sealed_records()
    local d = U.site_get(SEALED_KEY, {})
    local set = {}
    for _, k in ipairs(type(d) == 'table' and type(d.walls) == 'table' and d.walls or {}) do set[k] = true end
    return set, (type(d) == 'table' and type(d.walls) == 'table') and d.walls or {}
end

function note_sealed(keys)
    if #keys == 0 then return end
    local set, list = sealed_records()
    local out = {}
    for _, k in ipairs(list) do table.insert(out, k) end
    for _, k in ipairs(keys) do
        if not set[k] then set[k] = true; table.insert(out, k) end
    end
    while #out > SEALED_RECORD_MAX do table.remove(out, 1) end
    U.site_put(SEALED_KEY, {walls = out})
end

-- (0.105.30) A wall the AI built in a cavern opening (a sealed gate): a
-- construction with a cavern tile beside it, (0.105.30 fixes) and recorded
-- by the sealed style when placed (sealed_records). Only such walls are
-- taken down under rock.
local function sealed_wall_tile(x, y, z)
    local okr, rec = pcall(sealed_records)
    if not (okr and rec[('%d,%d,%d'):format(x, y, z)]) then return false end
    local ok, yes = pcall(function()
        local pos = xyz2pos(x, y, z)
        local built = dfhack.constructions.findAtTile(pos)
        if not built then
            local b = dfhack.buildings.findAtTile(pos)
            built = b and df.building_type[b:getType()] == 'Construction'
        end
        if not built then return false end
        for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}}) do
            local des = dfhack.maps.getTileFlags(x + d[1], y + d[2], z)
            if des and (des.feature_global or des.feature_local) then return true end
        end
        return false
    end)
    return ok and yes or false
end

function clear_gate(x, y, z, pieces, dry_run)
    if not surface_tile(x, y, z) and not sealed_wall_tile(x, y, z) then
        return {ok = false, rejected = true, error = 'that gate is under rock: part of the fort, kept'}
    end
    if not GATES.scanned then return {ok = false, rejected = true, error = 'map the entrances first'} end
    -- The fort's live entrances: their tiles inside, the tiles out from
    -- them, and the gates that close them. A hatch over a stair is a level
    -- above the stair (0.42's cleanup took the main stair's hatch with a
    -- tree gate 4 tiles off, checking the same level only).
    local live, keep_ids = {}, {}
    for _, e in ipairs(GATES.entrances or {}) do
        for _, k in ipairs(e.inside_list or {}) do table.insert(live, {unkey(k)}) end
        for k in pairs(e.outs or {}) do table.insert(live, {unkey(k)}) end
        for _, b in ipairs(e.equipment or {}) do keep_ids[b.id] = true end
    end
    local function near_live(px, py, pz, r)
        for _, t in ipairs(live) do
            if math.abs(t[3] - pz) <= 1 and math.abs(t[1] - px) <= r and math.abs(t[2] - py) <= r then
                return true
            end
        end
        return false
    end
    if near_live(x, y, z, 3) then
        return {ok = false, rejected = true, error = 'it is still an entrance of the fort: kept'}
    end
    local spots = {}
    -- (0.105.30 fixes) the wing walls recorded for this way in (build_wings):
    -- part of its gate, taken down with it
    local okw, wings = pcall(function() return wing_records()[('%d,%d,%d'):format(x, y, z)] end)
    wings = (okw and type(wings) == 'table' and #wings > 0) and wings or nil
    if wings then
        local all = {}
        for i, k in ipairs(type(pieces) == 'table' and pieces or {}) do
            if i <= GATE_PIECES_MAX then table.insert(all, k) end
        end
        for i, k in ipairs(wings) do if i <= WINGS_MAX then table.insert(all, k) end end
        pieces = all
    end
    if type(pieces) == 'table' and #pieces > 0 then
        -- (0.100, security pass) the pieces a fortify recorded lie round its
        -- gate on the surface: anything else (under rock, far off, a list of
        -- thousands) isn't one, and is skipped
        for i, k in ipairs(pieces) do
            if i > GATE_PIECES_MAX + (wings and WINGS_MAX or 0) then break end
            local px, py, pz = tostring(k):match('^(%-?%d+),(%-?%d+),(%-?%d+)$')
            px, py, pz = tonumber(px), tonumber(py), tonumber(pz)
            if px and math.abs(px - x) <= GATE_PIECE_REACH and math.abs(py - y) <= GATE_PIECE_REACH
                    and math.abs(pz - z) <= 1 then
                if surface_tile(px, py, pz) then
                    table.insert(spots, {x = px, y = py, z = pz})
                elseif sealed_wall_tile(px, py, pz) then
                    table.insert(spots, {x = px, y = py, z = pz, cavern = true})   -- (0.105.30) walls only
                end
            end
        end
    else
        -- (0.100, review) no record of what was placed (a gate from before
        -- 0.4x): the area round it holds the player's doors and the keep's
        -- walls too, so nothing is guessed at; it's left
        return {ok = false, rejected = true,
                error = 'no record of that gate\'s pieces: left standing (take it down by hand if it\'s in the way)'}
    end
    local removed, cancelled = 0, 0
    local KINDS = {Door = true, Hatch = true, Trap = true, Statue = true, Bridge = true}
    for _, p in ipairs(spots) do
        local pos = xyz2pos(p.x, p.y, p.z)
        local b = dfhack.buildings.findAtTile(pos)
        local kind = b and df.building_type[b:getType()]
        if near_live(p.x, p.y, p.z, 1) or (b and keep_ids[b.id]) then
            -- beside a live entrance, or one of its gates: never a leftover
        elseif p.cavern and b and kind ~= 'Construction' then
            -- (0.105.30) under rock only the sealed gate's walls
        elseif b and kind == 'Trap' and b.trap_type == df.trap_type.Lever then
            -- a lever is never a gate piece (it may work the fort's real gate)
        elseif b and (KINDS[kind] or kind == 'Construction') then
            if not dry_run then
                if kind == 'Construction' then
                    local ok, only_planned = dfhack.constructions.designateRemove(pos)
                    if ok then if only_planned then cancelled = cancelled + 1 else removed = removed + 1 end end
                else
                    local built = b:getBuildStage() >= b:getMaxBuildStage()
                    dfhack.buildings.deconstruct(b)
                    if built then removed = removed + 1 else cancelled = cancelled + 1 end
                end
            else
                removed = removed + 1
            end
        elseif dfhack.constructions.findAtTile(pos) then
            local t = dfhack.maps.getTileType(pos)
            local shape = t and df.tiletype_shape[df.tiletype.attrs[t].shape]
            if shape == 'WALL' then                     -- a built wall (not a floor someone made)
                if not dry_run then dfhack.constructions.designateRemove(pos) end
                removed = removed + 1
            end
        end
    end
    if removed + cancelled == 0 then
        return {ok = false, rejected = true, error = 'nothing of that gate is left to take down'}
    end
    if wings and not dry_run then
        pcall(function()                         -- (0.105.30 fixes) its wings taken down with it
            local d = wing_records()
            d[('%d,%d,%d'):format(x, y, z)] = nil
            U.site_put(WINGS_KEY, d)
        end)
    end
    return {ok = true, removed = removed, cancelled = cancelled, wings = wings and #wings or nil,
            dry_run = dry_run or nil}
end

-- Name the building just placed at pos (quickfort can't name a lever).
name_hook = nil       -- tests replace this
function name_at(pos, name)
    if name_hook then return name_hook(pos, name) end
    pcall(function()
        local b = dfhack.buildings.findAtTile(xyz2pos(pos.x, pos.y, pos.z))
        if b then b.name = name end
    end)
end

-- (0.105.12, 14.1 step 4) A lever of the AI's own for a gate that has none
-- (the founding stair's hatch: a lever-worked hatch is the machinery of a
-- fort that cares for its engineering and its walls). Placed where the
-- dwarves are, away from the gate, named "AI gate lever"; the gate rule
-- links it once built. Refused (waiting) while an unlinked AI lever stands
-- or is being built anywhere.
function place_gate_lever(id, dry_run, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    if #(e.equipment or {}) == 0 then
        return {ok = false, rejected = true, error = 'that entrance has no gate yet: a lever works a gate'}
    end
    -- (0.105.32) a gate there stuck shut for DF and was taken down: no lever for a year
    for _, g in ipairs(e.equipment) do
        local oks, at = pcall(stuck_spot, g.x1, g.y1, g.z)
        if (g.kind == 'door' or g.kind == 'hatch') and oks and at then
            return {ok = false, rejected = true, stuck_spot = true,
                    error = ('a gate at x%d y%d z%d stayed shut for DF though it read open and was taken down: '
                        .. 'no lever for a gate there for a year (the watcher locks it instead)'):format(g.x1, g.y1, g.z)}
        end
    end
    -- (0.105.33) only one that can work this entrance (inside, away from it):
    -- a lever never linked elsewhere no longer stops every other one
    if lever_waiting_for(e, GATES.inside, unlinked_ai_levers()) then
        return {ok = false, waiting = true, error = 'an AI gate lever stands unlinked or is being built: it goes first'}
    end
    cache, edge_cache = {}, {}
    -- (0.105.23) where the fort's citizens are (fort_starts: not one on a ledge or a treetop)
    local spot = lever_spot(starts or fort_starts(citizen_starts()), e)
    if not spot then return {ok = false, error = 'no free floor for a lever where the dwarves are, away from the gate'} end
    if dry_run then return {ok = true, dry_run = true, at = spot} end
    local ok, why = place('Tl', spot)
    if not ok then return {ok = false, error = 'the lever could not be placed: ' .. tostring(why)} end
    name_at(spot, LEVER_NAME)
    return {ok = true, at = spot}
end

-- Levers the AI may link: named "AI gate..." (the player's "AI gate", or the
-- AI's own "AI gate lever"), built, with no link and no job. {{id,x,y,z}}.
function free_levers()
    local out = {}
    pcall(function()
        for _, b in ipairs(df.global.world.buildings.other.TRAP) do
            if b.trap_type == df.trap_type.Lever and tostring(b.name or ''):lower():find('^ai gate')
                    and #b.linked_mechanisms == 0 and #b.jobs == 0
                    and b:getBuildStage() >= b:getMaxBuildStage() then
                table.insert(out, {id = b.id, x = b.centerx, y = b.centery, z = b.z})
            end
        end
    end)
    return out
end

-- Mechanisms free to use (for traps and links), counted up to `cap`.
function free_mechanism_count(cap)
    local ok, list = pcall(free_mechanisms, cap or 200)
    return ok and #list or 0
end

---------------------------------------------------------------------------
-- Traps behind a gate: on the way in, just inside the gate line (never
-- outside it, never on the tile right behind a door, where an inner door
-- may go), nearest first, in the fort's trap style.
---------------------------------------------------------------------------

TRAP_KEYS = {cage = 'Tc', stonefall = 'Ts', weapon = 'Tw'}
MAX_TRAPS = 8

function trap_tiles(e, n, starts)
    -- the gate's own tiles: what closes it (doors, bridges, hatches). (0.105.9)
    -- hatches too: every fort's only gate was the founding stair's hatch, so
    -- no fort ever had a trap (the six forts, y257). Behind a hatch the way
    -- in goes down its stair; the traps go on the floor at the stair's foot
    -- (stairs are never trapped: only floor is)
    local gate, only_hatch = {}, true
    for _, b in ipairs(e.equipment or {}) do
        if b.x1 and b.x2 and b.y1 and b.y2 and b.z then
            for x = b.x1, b.x2 do for y = b.y1, b.y2 do gate[key(x, y, b.z)] = true end end
            if b.kind ~= 'hatch' then only_hatch = false end
        end
    end
    if not next(gate) then return {} end
    -- inside the gate: what the dwarves reach without crossing it, less what
    -- the outside reaches without crossing it (a pocket between a moved-in
    -- gate and the opening, where a dwarf may stand)
    local inside = explore(starts, gate)
    local pocket, q, h = {}, {}, 1
    -- (a hatch sits on the opening itself: its stair down is the fort, no pocket)
    for _, k in ipairs(only_hatch and {} or e.inside_list or {}) do
        if not gate[k] and not pocket[k] then pocket[k] = true; table.insert(q, k) end
    end
    while h <= #q and #q < 5000 do
        local k = q[h]
        h = h + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if pocket[nk] or gate[nk] then return end
                if not (e.outs and e.outs[nk]) and inside_or_courtyard(T(nx, ny, nz), nk) then
                    pocket[nk] = true                -- (inside tiles only: never round by another way in)
                    table.insert(q, nk)
                end
            end)
        end
    end
    for k in pairs(pocket) do inside[k] = nil end
    local dist, queue, head = {}, {}, 1
    for k in pairs(gate) do dist[k] = 0; table.insert(queue, k) end
    local picks = {}
    while head <= #queue and #picks < n do
        local k = queue[head]
        head = head + 1
        local x, y, z = unkey(k)
        local t = T(x, y, z)
        if t then
            moves(x, y, z, t, function(nx, ny, nz)
                local nk = key(nx, ny, nz)
                if dist[nk] or not inside[nk] then return end
                dist[nk] = dist[k] + 1
                if dist[nk] <= 8 then table.insert(queue, nk) end
            end)
        end
        local d = dist[k]
        if d >= 2 and #picks < n then
            local tt = T(x, y, z)
            if tt and DOOR_GROUND[tt.shape] and not tt.liquid and not tt.occupied then
                table.insert(picks, k)
            end
        end
    end
    return picks
end

function place_traps(id, kind, n, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    local k = TRAP_KEYS[kind]
    if not k then return {ok = false, rejected = true, error = 'unknown trap kind ' .. tostring(kind)} end
    n = math.max(1, math.min(MAX_TRAPS, math.floor(tonumber(n) or 0)))
    if #(e.equipment or {}) == 0 then
        return {ok = false, rejected = true, error = 'that entrance has no gate yet: traps go behind a gate'}
    end
    starts = starts or fort_starts(citizen_starts())      -- (0.105.33) as the scan reads them
    cache, edge_cache = {}, {}
    local tiles = trap_tiles(e, n, starts)
    if #tiles == 0 then return {ok = false, error = 'no free floor just inside that gate for traps'} end
    local placed, failed = 0, {}
    local first
    for _, tk in ipairs(tiles) do
        local x, y, z = unkey(tk)
        local ok, why = place(k, {x = x, y = y, z = z})
        if ok then
            placed = placed + 1
            first = first or {x = x, y = y, z = z}
        else
            table.insert(failed, tostring(why))
        end
    end
    if placed == 0 then return {ok = false, error = 'no trap could be placed (' .. table.concat(failed, '; '):sub(1, 200) .. ')'} end
    return {ok = true, traps = placed, kind = kind, at = first,
            failed = #failed > 0 and table.concat(failed, '; '):sub(1, 200) or nil}
end

-- (0.105.23, 14.1 step 4a) Build the gatehouse in front of an entrance's lid
-- hatch (plan_gatehouse): the drawbridge first (refused, nothing else is
-- placed), named "AI gatehouse bridge" so the scan knows it; then the walls,
-- the corridor's traps in the fort's style, and a lever where the dwarves
-- are (unless an AI lever stands unlinked: that one is linked instead). The
-- gate rule links the lever to the bridge once both are built.
function build_gatehouse(id, kind, n, dry_run, starts)
    local e = entrance(id)
    if not e then return {ok = false, rejected = true, error = 'no such entrance (scan first)'} end
    local tk = TRAP_KEYS[kind or 'cage']
    if not tk then return {ok = false, rejected = true, error = 'unknown trap kind ' .. tostring(kind)} end
    if not e.sealed then return {ok = false, rejected = true, error = 'that entrance has no gate yet: the hatch first'} end
    if e.gatehouse == 'standing' then return {ok = false, rejected = true, error = 'a gatehouse stands there already'} end
    local h = lid_hatch(e)
    if not h then
        return {ok = false, rejected = true, error = 'a gatehouse goes in front of a hatch over the founding stair'}
    end
    cache, edge_cache = {}, {}            -- the map may have changed since the scan
    local plan, why = plan_gatehouse(e, h)
    if not plan then return {ok = false, error = why} end
    n = math.max(0, math.min(#plan.corridor, math.floor(tonumber(n) or #plan.corridor)))
    local br = plan.bridge
    local out = {ok = true, bridge = {x = br.x, y = br.y, z = br.z}, dir = br.dir, length = plan.len,
                 walls = 0, natural_walls = plan.natural, traps = 0, kind = kind or 'cage', pieces = {}}
    if dry_run then
        out.dry_run, out.walls, out.traps = true, #plan.walls, n
        return out
    end
    local okb, whyb = place(('%s(1x1)'):format(br.dir), {x = br.x, y = br.y, z = br.z})
    if not okb then return {ok = false, error = 'the game would not place the drawbridge: ' .. tostring(whyb)} end
    name_at({x = br.x, y = br.y, z = br.z}, GATEHOUSE_NAME)
    table.insert(out.pieces, ('%d,%d,%d'):format(br.x, br.y, br.z))
    local failed = {}
    for _, k in ipairs(plan.walls) do
        local x, y, z = unkey(k)
        local ok, w = place('Cw', {x = x, y = y, z = z})
        if ok then
            out.walls = out.walls + 1
            table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, 'Cw:' .. tostring(w))
        end
    end
    for i = 1, n do
        local x, y, z = unkey(plan.corridor[i])
        local ok, w = place(tk, {x = x, y = y, z = z})
        if ok then
            out.traps = out.traps + 1
            table.insert(out.pieces, ('%d,%d,%d'):format(x, y, z))
        else
            table.insert(failed, tk .. ':' .. tostring(w))
        end
    end
    if lever_waiting_for(e, GATES.inside, unlinked_ai_levers()) then      -- (0.105.33)
        out.lever_note = 'an AI gate lever stands unlinked: it works the bridge'
    else
        local spot = lever_spot(starts or fort_starts(citizen_starts()), e)
        if spot and place('Tl', spot) then
            name_at(spot, LEVER_NAME)
            out.lever = spot
        else
            out.lever_note = 'no lever placed (no free floor where the dwarves are, away from the gate): the gate rule places one'
        end
    end
    if #failed > 0 then out.failed = table.concat(failed, '; '):sub(1, 300) end
    return out
end
