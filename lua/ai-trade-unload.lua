-- ai-trade-unload: the fort's goods out of the depot (unload) and the goods
-- a caravan long done left in the depot taken out of the game
-- (clear_caravan_goods).
--
-- (0.105.119) A part of ai-trade (split off when it reached the size
-- limit), not a script of its own: ai-trade.lua loads it into its own
-- environment, so every name here is reqscript('ai-trade').name and the
-- names defined there are in reach.

if not PART_LOCALS then qerror('ai-trade-unload is a part of ai-trade; run ai-trade') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-trade-unload'] = '0.105.134'   -- (0.105.26) bumped with BRIDGE_VERSION

local translate, depot, caravans, is_artifact, goods = PART_LOCALS.translate, PART_LOCALS.depot, PART_LOCALS.caravans, PART_LOCALS.is_artifact, PART_LOCALS.goods   -- (0.105.119) the hub's locals (goods: only a key here, taken so the name is this file's as in the one file)


-- (0.103.9) unload(): the fort's goods out of the depot; after out_of_depot below

-- (item3) The goods a caravan long done left in the depot (B and C, 24 Nov:
-- "The Moral Wire" Leaving 2903 days, time run out, 115 of its goods still
-- in the depot and its one merchant on the map not coming for them; the
-- stuck caravan's walk-off and edge steps had been tried and DF's
-- fix/stuck-merchants never runs with a merchant on the map). Its own goods
-- (flags.trader; an ENTITY_ITEMOWNER ref, where there is one, to its
-- civilisation) are taken out of the game with dfhack.items.remove, as if
-- the merchants had packed them: never given to the fort (no flag or owner
-- changed: that would be theft, and DF counts it against the civilisation),
-- never moved out onto the floor (haulers would pick the merchants' goods
-- up, and that is theft too). A bin goes with what is in it, its contents
-- first; one holding anything not the merchants' stays, as does one on a
-- job (a merchant's own pick-up), an artifact, or one whose removal DFHack
-- refuses. Refused unless DF holds that caravan Leaving with its time run
-- out, no other caravan is coming or at the depot (their goods would look
-- the same), the trade screen is shut, and none of its merchants stands in
-- the depot (one there is packing). Up to `limit` items (contents count).
CARAVAN_GOODS_MAX = 300

local function owner_civ(item)
    local found
    pcall(function()
        for _, r in ipairs(item.general_refs) do
            if r:getType() == df.general_ref_type.ENTITY_ITEMOWNER then found = r.entity_id end
        end
    end)
    return found
end

-- (0.105.114 item17) Why dfhack.items.remove never took one of them (B 19
-- tries, C 17, 0 removed; B probe 25 Nov 08:03): each good in the depot is
-- flags.in_building with a BUILDING_HOLDER ref to the depot (and its entry in
-- the depot's contained_items), neither on_ground nor in the block's items,
-- and DFHack's detachItem refuses any item with a BUILDING_HOLDER ref (or one
-- neither on the ground nor in an inventory). So a good is first taken out of
-- the depot (its contained_items entry and its holder ref gone, in_building
-- off), set on its tile as DF holds a floor item, then removed; DFHack's
-- other refusals (specific refs, world data, a cage, trigger, zone or
-- projectile ref, another building holding it) are checked before anything
-- is touched, so a good that could not go stays as it was.
local REFUSED_REFS = {'PROJECTILE', 'BUILDING_CAGED', 'BUILDING_TRIGGER', 'BUILDING_TRIGGERTARGET',
                      'BUILDING_CIVZONE_ASSIGNED'}

local function ref_type(name)
    local ok, v = pcall(function() return df.general_ref_type[name] end)
    return ok and v or nil
end

-- why DFHack would refuse it even out of the depot: nil when it can go
local function held_why(item, dep_id)
    local okw, wd = pcall(function() return item.world_data_id end)
    if okw and wd ~= nil and wd ~= -1 then return 'world_data' end
    local oks, n = pcall(function() return #item.specific_refs end)
    if oks and n and n > 0 then return 'specific_ref' end
    local holder = ref_type('BUILDING_HOLDER')
    local refused = {}
    for _, name in ipairs(REFUSED_REFS) do
        local t = ref_type(name)
        if t then refused[t] = name end
    end
    local why
    pcall(function()
        for _, r in ipairs(item.general_refs) do
            local t = r:getType()
            if refused[t] then why = why or ('ref ' .. refused[t]) end
            if holder and t == holder and r.building_id ~= dep_id then why = why or 'other_building' end
        end
    end)
    return why
end

-- a DF vector or (tests) a Lua list, at the index ipairs gave
local function vec_erase(v, i)
    if type(v) == 'table' then table.remove(v, i) else v:erase(i) end
end

local function vec_insert_sorted(v, id)
    local at, tbl = nil, type(v) == 'table'
    for i, x in ipairs(v) do
        if x == id then return end
        if x > id then at = i break end
    end
    if tbl then table.insert(v, at or (#v + 1), id)
    elseif at then v:insert(at, id) else v:insert('#', id) end
end

-- out of the depot onto its tile, so dfhack.items.remove may take it: true,
-- or nil and why (nothing changed then). (0.105.115 item19) `also`: more ref
-- types to drop with the holder (unload: UNIT_TRADEBRINGER); `at`: the tile
-- for one with no position of its own (the depot's centre)
local function refs(o, k)
    local ok, v = pcall(function() return o[k or 'general_refs'] end)
    return ok and v or {}
end

local function out_of_depot(item, dep, also, at)
    local holder = ref_type('BUILDING_HOLDER')
    local drop, more = {}, {}
    for _, name in ipairs(also or {}) do
        local t = ref_type(name)
        if t then more[t] = true end
    end
    for i, r in ipairs(refs(item)) do
        local t = r:getType()
        if (holder and t == holder) or more[t] then table.insert(drop, 1, {i, r}) end
    end
    local entry
    for i, ci in ipairs(refs(dep, 'contained_items')) do
        if ci.item == item then entry = i end
    end
    if not item.flags.in_building and #drop == 0 and not entry then return true end
    local loose = not item.flags.on_ground and not item.flags.in_inventory
    local x, y, z, blk = dfhack.items.getPosition(item)
    if loose then
        if (not x or x < 0) and at then x, y, z = at.x, at.y, at.z end
        if not x or x < 0 then return nil, 'no position' end
        local okb, b = pcall(dfhack.maps.getTileBlock, x, y, z)
        if not okb or not b then return nil, 'no map block at its tile' end
        blk = b
    end
    if entry then
        local ci = dep.contained_items[entry]
        vec_erase(dep.contained_items, entry)
        pcall(function() ci:delete() end)
    end
    for _, d in ipairs(drop) do                   -- the last first: the indices stay right
        vec_erase(item.general_refs, d[1])
        pcall(function() d[2]:delete() end)
    end
    item.flags.in_building = false
    if loose then
        pcall(function() item.pos.x, item.pos.y, item.pos.z = x, y, z end)
        vec_insert_sorted(blk.items, item.id)
        pcall(function() blk.occupancy[x % 16][y % 16].item = true end)
        item.flags.on_ground = true
    end
    return true
end

-- whether the game has it no more (DF deletes a removed item at its next pass)
local function gone_now(item, id)
    local okf, still = pcall(function() return df.item.find(id) end)
    if okf and still == nil then return true end
    return item.flags.removed == true or item.flags.garbage_collect == true
end

-- whether this good and all it holds may go: true, or false and why
local function goods_free(item, entity, depth, dep_id)
    if not merchant_item(item) then return false, 'not_theirs' end
    local o = owner_civ(item)
    if o ~= nil and o ~= entity then return false, 'other_owner' end
    local okj, busy = pcall(function() return item.flags.in_job end)
    if okj and busy then return false, 'busy' end
    if is_artifact(item) then return false, 'artifact' end
    local held = held_why(item, dep_id)
    if held then return false, held end
    local okc, inside = pcall(dfhack.items.getContainedItems, item)
    if okc and type(inside) == 'table' and #inside > 0 then
        if depth >= 3 then return false, 'nested' end
        for _, c in ipairs(inside) do
            local ok, why = goods_free(c, entity, depth + 1, dep_id)
            if not ok then return false, why end
        end
    end
    return true
end

-- the item and what it holds, the contents first
local function goods_list(item, out, depth)
    local okc, inside = pcall(dfhack.items.getContainedItems, item)
    if okc and type(inside) == 'table' and depth < 3 then
        for _, c in ipairs(inside) do goods_list(c, out, depth + 1) end
    end
    table.insert(out, item)
    return out
end

-- (0.103.9) The fort's goods left in the depot once the caravans have gone:
-- set down on the depot's tile, so the haulers store them again and dwarves
-- can own them (DF leaves them there until the next caravan: Enxah, 163).
-- (0.105.115 item19) dfhack.items.moveToGround refused them ("none moved out
-- of the depot: the game kept it in the depot", B C F 25 Nov): like the
-- merchants' goods, each one in the depot is in_building with a
-- BUILDING_HOLDER ref to it and a UNIT_TRADEBRINGER ref (probe C, E 25 Nov
-- 10:49: 174 and 166, none on_ground). So each is taken out as out_of_depot
-- does (its contained_items entry, the holder and bringer refs gone,
-- in_building off, on the ground at its tile in the depot), what it holds
-- cleared the same way, and checked: on the ground, no holder ref, out of the
-- depot's list. The depot's own building materials (PERM), the merchants'
-- goods, one on a job and one DFHack's other refusals hold stay as they are.
-- Never while a caravan is coming or at the depot, or the trade screen is open.
local function out_check(item, dep)
    if not item.flags.on_ground or item.flags.in_building then return 'not on the ground' end
    local holder = ref_type('BUILDING_HOLDER')
    for _, r in ipairs(refs(item)) do
        if holder and r:getType() == holder then return 'its holder ref stayed' end
    end
    for _, ci in ipairs(refs(dep, 'contained_items')) do
        if ci.item == item then return 'still in the depot\'s list' end
    end
end

function unload(limit, dry_run, txt)
    local busy_n, theirs = 0, 0
    local dep = depot()
    if not dep then return {ok = false, rejected = true, error = 'no trade depot built yet'} end
    if #caravans(txt) > 0 then return {ok = false, rejected = true, error = 'a caravan is coming or at the depot'} end
    local okt, open = pcall(function() return df.global.game.main_interface.trade.open end)
    if okt and open then return {ok = false, rejected = true, error = 'the trade screen is open'} end
    local items, busy_ids, kept = {}, {}, {}
    for _, ci in ipairs(dep.contained_items) do
        if ci.use_mode == df.building_item_role_type.TEMP and ci.item and merchant_item(ci.item) then
            theirs = theirs + 1     -- (r2 h5) the merchants' goods are theirs to pack, never moved
        elseif ci.use_mode == df.building_item_role_type.TEMP and ci.item then
            -- (0.104.138) one a hauler is already carrying out is left to him
            local busy = false
            pcall(function() busy = ci.item.flags.in_job end)
            local held = held_why(ci.item, dep.id)
            if busy then
                busy_n = busy_n + 1
                table.insert(busy_ids, ci.item.id)
            elseif held then kept[held] = (kept[held] or 0) + 1
            else table.insert(items, ci.item) end
        end
    end
    kept = next(kept) and kept or nil
    if #items == 0 and busy_n > 0 then
        -- (item4) the ones on a job past DEPOT_STUCK_TICKS: stuck, said so
        local okr, _, stuck = pcall(depot_busy_seen, busy_ids)
        stuck = okr and stuck or 0
        return {ok = false, rejected = true, waiting = true, busy = busy_n, stuck = stuck > 0 and stuck or nil,
                error = busy_n .. ' item(s) are being hauled out of the depot'
                        .. (stuck > 0 and (' (' .. stuck .. ' on the same job for 3+ days: stuck)') or '')}
    end
    if #items == 0 then
        local bits = {}
        for k, v in pairs(kept or {}) do table.insert(bits, v .. ' ' .. k) end
        table.sort(bits)
        return {ok = false, rejected = true, merchant_goods = theirs > 0 and theirs or nil, kept = kept,
                error = (#bits > 0 and ('none of the fort\'s goods in the depot may move (' .. table.concat(bits, ', ') .. ')')
                         or 'nothing of the fort\'s is in the depot') ..
                        (theirs > 0 and (' (' .. theirs .. ' of the merchants\' own goods are, theirs to take)') or '')}
    end
    local n = math.min(#items, limit or 50)
    if dry_run then return {ok = true, dry_run = true, items = n, at_depot = #items, kept = kept} end
    local at, moved, failed, first = xyz2pos(dep.centerx, dep.centery, dep.z), 0, 0, nil
    local also = {'UNIT_TRADEBRINGER'}
    for i = 1, n do
        local item, why = items[i], nil
        local ok, d, dwhy = pcall(out_of_depot, item, dep, also, at)
        if not ok then why = tostring(d):sub(1, 100)
        elseif not d then why = dwhy
        else
            -- what it holds: no holder or bringer ref, not in_building, left in it
            local okc, inside = pcall(dfhack.items.getContainedItems, item)
            if okc and type(inside) == 'table' then
                for _, c in ipairs(inside) do pcall(out_of_depot, c, dep, also, at) end
            end
            why = out_check(item, dep)
        end
        if why then
            failed = failed + 1
            first = first or ('item %d: %s'):format(item.id, why)
        else moved = moved + 1 end
    end
    if moved == 0 then
        return {ok = false, failed = failed, first_failure = first, error = 'none moved out of the depot: ' .. tostring(first)}
    end
    return {ok = true, items = moved, left = #items - moved, failed = failed > 0 and failed or nil,
            first_failure = first, kept = kept}
end

function clear_caravan_goods(entity, limit, dry_run, txt)
    limit = math.max(1, math.min(tonumber(limit) or 200, CARAVAN_GOODS_MAX))
    local dep = depot()
    if not dep then return {ok = false, rejected = true, error = 'no trade depot built yet'} end
    local T = df.caravan_state.T_trade_state
    local c
    for _, x in ipairs(df.global.plotinfo.caravans) do
        if x.entity == entity then c = x end
    end
    if not c then return {ok = false, rejected = true, error = 'no caravan of entity ' .. tostring(entity)} end
    local _, state = pcall(function() return T[c.trade_state] end)
    local left = tonumber(c.time_remaining) or 1
    if state ~= 'Leaving' or left > 0 then
        return {ok = false, rejected = true, state = tostring(state),
                error = ('that caravan is %s with %d ticks left: its goods are its merchants\' to pack')
                        :format(tostring(state), math.floor(left))}
    end
    for _, x in ipairs(df.global.plotinfo.caravans) do
        local ok, about = pcall(function()
            return x ~= c and not x.flags.tribute and x.time_remaining > 0
                and (x.trade_state == T.Approaching or x.trade_state == T.AtDepot)
        end)
        if ok and about then
            return {ok = false, rejected = true, error = 'another caravan is coming or at the depot: its goods would look the same'}
        end
    end
    local okt, open = pcall(function() return df.global.game.main_interface.trade.open end)
    if okt and open then return {ok = false, rejected = true, error = 'the trade screen is open'} end
    local packing = 0
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            pcall(function()
                if u.flags1.merchant and u.civ_id == entity and not u.flags1.inactive
                        and not (dfhack.units.isDead and dfhack.units.isDead(u)) and at_depot(u, dep) then
                    packing = packing + 1
                end
            end)
        end
    end)
    if packing > 0 then
        return {ok = false, rejected = true, packing = packing,
                error = packing .. ' of its merchant(s) at the depot: left to pack their goods'}
    end
    local why, theirs, take, n = {}, 0, {}, 0
    for _, ci in ipairs(dep.contained_items) do
        if ci.use_mode == df.building_item_role_type.TEMP and ci.item and merchant_item(ci.item) then
            theirs = theirs + 1
            local ok, w = goods_free(ci.item, entity, 0, dep.id)
            if not ok then
                why[w] = (why[w] or 0) + 1
            else
                local list = goods_list(ci.item, {}, 0)
                if n > 0 and n + #list > limit then break end
                n = n + #list
                table.insert(take, list)
            end
        end
    end
    local civ = '?'
    pcall(function()
        local ent = df.historical_entity.find(entity)
        if ent then civ = (txt or tostring)(translate(ent.name, true)) end
    end)
    local kept = next(why) and why or nil
    if #take == 0 then
        local bits = {}
        for k, v in pairs(why) do table.insert(bits, v .. ' ' .. k) end
        table.sort(bits)
        return {ok = false, rejected = true, goods = theirs, kept = kept, civ = civ,
                error = theirs == 0 and 'none of the merchants\' goods is in the depot'
                        or ('none of their %d goods may go (%s)'):format(theirs, table.concat(bits, ', '))}
    end
    if dry_run then
        return {ok = true, dry_run = true, goods = #take, items = n, left = theirs - #take, kept = kept, civ = civ}
    end
    local gone, inner, failed, first = 0, 0, 0, nil
    for _, list in ipairs(take) do
        local whole = true
        for i, it in ipairs(list) do
            local id, why = it.id, nil
            local okd, d, dwhy = pcall(out_of_depot, it, dep)
            if not okd then why = 'out of the depot: ' .. tostring(d):sub(1, 100)
            elseif not d then why = dwhy
            else
                local ok, r = pcall(dfhack.items.remove, it)
                if not ok then why = 'dfhack.items.remove: ' .. tostring(r):sub(1, 100)
                elseif r == false then why = 'dfhack.items.remove refused it'
                elseif not gone_now(it, id) then why = 'still in the game after its removal' end
                if why and not it.flags.in_building then
                    pcall(function() it.flags.forbid = true end)   -- out on the floor: no hauler takes it
                end
            end
            if why then
                failed = failed + 1
                first = first or ('item %d: %s'):format(id, why)
                whole = false
                break                      -- a bin whose contents could not all go stays
            elseif i < #list then
                inner = inner + 1
            end
        end
        if whole then gone = gone + 1 end
    end
    if gone == 0 and inner == 0 then
        return {ok = false, failed = failed, first_failure = first, civ = civ,
                error = 'DFHack removed none of their goods (' .. tostring(first) .. ')'}
    end
    return {ok = true, removed = gone, contents = inner, failed = failed > 0 and failed or nil,
            first_failure = first, left = theirs - gone, kept = kept, civ = civ}
end
