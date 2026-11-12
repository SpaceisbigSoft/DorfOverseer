-- (item 12) The fort's artifacts shown and kept safe. The coverage audit
-- (12 Nov, "should"): the artifacts the moods make (lua/ai-moods.lua; the
-- camera director shows each one made) lay in the stockpiles for good; DF 50+
-- shows them on display furniture (a pedestal, a display case) in a
-- location (temple, library, tavern, guildhall) or a hall, where they add to
-- its value; thieves come for them (the heist lockout, 0.105.24) and other
-- civs claim them (the missions report, 0.105.39).
--
--   report()            the `artifacts` section: the artifacts on the map
--                       (where each is: displayed, loose, carried, in a job,
--                       forbidden, owned; whether it is the AI's to move;
--                       which other civs claim it), the display furniture
--                       (pedestals and display cases: where, how many items,
--                       whether the AI placed it), the AI's own rooms that
--                       could hold one (each location's or hall's zone inside
--                       a level the AI dug: its doors and open ways out,
--                       whether visitors may come in) and the free pedestals
--                       and display cases in store.
--   place_display(o, dry)    a free pedestal or display case built in one of
--                       those rooms (beside a wall, never in front of a door);
--                       remembered as the AI's own.
--   display_artifact(o, dry) an artifact of the AI's put on display in one
--                       of the AI's own display furniture (DF's "put item on
--                       display" job: a hauler carries it there).
--
-- Whose artifacts: the AI moves only the ones made since it first looked
-- (an artifact id at or past `first_id`, kept in the save the first time the
-- report runs). An artifact that was in the world before is the player's:
-- reported, never moved. One brought home since (recovered from a mission,
-- taken back from a thief) keeps its old id, below first_id, so it counts as
-- the player's too and is never moved. Never one a dwarf carries or owns,
-- one a job holds, a forbidden one, a book or scroll, or a squad's gear.
-- Never sold, melted, dumped or destroyed: ai-trade, ai-disposal and
-- ai-cleanup each refuse an artifact themselves (tests/test_artifacts.py
-- holds them to it).
--
-- Whose rooms: a location's or hall's zone whose centre lies in a level the
-- AI dug (ai-insane's ai_boxes: its projects' boxes, the same test its own
-- doors use). The player's rooms get no furniture and no artifacts.
--
-- Needs an in-game look (DF 53 names guarded with pcall): the display
-- furniture's building type (DisplayFurniture) and its `displayed_items`; the
-- tools' ids ITEM_TOOL_PEDESTAL / ITEM_TOOL_DISPLAY_CASE; the job type
-- PutItemOnDisplay with the item as Hauled and the furniture as its holder;
-- how many items each holds (CAP below).
--@ module = true

local U = reqscript('ai-util')

SITE_KEY = 'ai-overseer/artifacts'
KINDS = {pedestal = 'ITEM_TOOL_PEDESTAL', case = 'ITEM_TOOL_DISPLAY_CASE'}
CAP = {pedestal = 1, case = 3}      -- items each holds (a guess until seen in game; the brain has its own)
ROOM_TYPES = {TEMPLE = true, LIBRARY = true, INN_TAVERN = true, GUILDHALL = true}
HALL_LISTS = {DiningHall = 'ZONE_DINING_HALL', MeetingHall = 'ZONE_MEETING_HALL'}
-- writing is a library's, not a pedestal's
WRITTEN_TOOLS = {ITEM_TOOL_SCROLL = true, ITEM_TOOL_QUIRE = true, ITEM_TOOL_CODEX = true}
WRITTEN_TYPES = {BOOK = true, SHEET = true}
ARTIFACTS_MAX = 60       -- artifacts listed in the report at most (the AI's first)
DISPLAYS_MAX = 40
ROOMS_MAX = 20
REMEMBER_MAX = 100

-- swapped by the tests --------------------------------------------------------
function builder() return reqscript('ai-builder') end
function ai_boxes() return reqscript('ai-insane').ai_boxes() end
function danger_spots() return U.danger_spots() end
-- (fix5) the citizens' walk groups ({[g] = true}; nil when the game can't say)
function citizen_groups()
    local ok, g = pcall(function() return builder().citizen_groups() end)
    if ok and type(g) == 'table' and next(g) then return g end
    return nil
end
function walk_group(x, y, z)
    local ok, g = pcall(function() return builder().walk_group(x, y, z) end)
    return ok and tonumber(g) or nil
end

-- (fix5) why no hauler is sent for the artifact to the display (nil: go), as
-- the disposal actions guard: near a danger, or out of the citizens' reach
function haul_guard(it, b)
    local x, y, z = U.item_pos(it)
    local spots = (function() local ok, s = pcall(danger_spots); return ok and s or {} end)()
    if x and U.near_danger(spots, x, y, z) then return 'near a danger' end
    if U.near_danger(spots, b.centerx, b.centery, b.z) then return 'near a danger (the display)' end
    local groups = citizen_groups()
    if groups then
        local g = x and walk_group(x, y, z)
        if g and not groups[g] then return 'out of the citizens\' reach' end
        -- the furniture's own tile may not be walkable: it or a tile beside it in reach
        local seen, near = false, false
        for dx = -1, 1 do
            for dy = -1, 1 do
                local gb = walk_group(b.centerx + dx, b.centery + dy, b.z)
                if gb then seen = true; if groups[gb] then near = true end end
            end
        end
        if seen and not near then return 'out of the citizens\' reach (the display)' end
    end
    return nil
end

local function int(v)
    local n = tonumber(v)
    return n and math.tointeger(n) or nil
end

local function words(name)
    local ok, s = pcall(function() return dfhack.df2utf(dfhack.translation.translateName(name, true)) end)
    if ok and type(s) == 'string' and s ~= '' then return s:sub(1, 60) end
    ok, s = pcall(function() return dfhack.TranslateName(name, true) end)
    if ok and type(s) == 'string' and s ~= '' then return s:sub(1, 60) end
    return nil
end

-- --- the save's record ---------------------------------------------------------

function registry()
    local d = U.site_get(SITE_KEY, {})
    if type(d) ~= 'table' then d = {} end
    if type(d.displays) ~= 'table' then d.displays = {} end
    return d
end

local function save(d)
    while #d.displays > REMEMBER_MAX do table.remove(d.displays, 1) end
    return U.site_put(SITE_KEY, d)
end

-- The artifact records, in id order (DF appends): a list of the game's.
local function all_records()
    local ok, v = pcall(function() return df.global.world.artifacts.all end)
    return ok and v or nil
end

-- The first artifact id that is the AI's: set (and saved) the first time it
-- is asked: the next id the game will give (the last record's + 1).
function first_id()
    local d = registry()
    if int(d.first_id) then return int(d.first_id) end
    -- walked once in a fort's life (then kept in the save)
    local list = all_records()
    local ok, n = pcall(function()
        local top = -1
        for _, a in ipairs(list) do if a.id > top then top = a.id end end
        return top + 1
    end)
    -- the records unread: nothing is the AI's this time (asked again next report)
    if not ok or int(n) == nil then return math.maxinteger end
    d.first_id = int(n)
    save(d)
    return d.first_id
end

local function is_mine_display(d, id)
    for _, v in ipairs(d.displays) do if v == id then return true end end
    return false
end

-- --- reading the game -----------------------------------------------------------

-- the artifact items in play (items.other.ANY_ARTIFACT; else each record's item)
function artifact_items()
    local ok, list = pcall(function() return df.global.world.items.other.ANY_ARTIFACT end)
    if ok and list then
        local out = {}
        for _, it in ipairs(list) do table.insert(out, it) end
        return out
    end
    local out = {}
    pcall(function()
        for _, a in ipairs(all_records()) do
            local it = a.item
            if it and U.item_pos(it) then table.insert(out, it) end
        end
    end)
    return out
end

-- the artifact record of an item, or nil
function record_of(it)
    local ok, a = pcall(function()
        local ref = dfhack.items.getGeneralRef(it, df.general_ref_type.IS_ARTIFACT)
        return ref and df.artifact_record.find(ref.artifact_id)
    end)
    return ok and a or nil
end

-- the display furniture standing (buildings.other.DISPLAY_CASE, df-structures' name for the display furniture list; else every building)
function display_buildings()
    local ok, list = pcall(function() return df.global.world.buildings.other.DISPLAY_CASE end)
    local out = {}
    if ok and list then
        for _, b in ipairs(list) do table.insert(out, b) end
        return out
    end
    pcall(function()
        local want = df.building_type.DisplayFurniture
        for _, b in ipairs(df.global.world.buildings.all) do
            if b:getType() == want then table.insert(out, b) end
        end
    end)
    return out
end

-- a tool's kind: 'pedestal', 'case' or nil
function tool_kind(it)
    local ok, id = pcall(function() return it.subtype.id end)
    if not ok then return nil end
    for k, v in pairs(KINDS) do if v == id then return k end end
    return nil
end

-- (kind, items shown) of a display furniture building
function display_state(b)
    local kind, n, contained = nil, nil, 0
    pcall(function()
        for _, ci in ipairs(b.contained_items) do
            contained = contained + 1
            kind = kind or tool_kind(ci.item)
        end
    end)
    pcall(function() n = #b.displayed_items end)
    if n == nil then n = math.max(0, contained - 1) end
    return kind or '?', n
end

local function built(b)
    local ok, yes = pcall(function() return b:getBuildStage() >= b:getMaxBuildStage() end)
    return ok and yes == true
end

-- the civzone (id) at a tile that is in `zones` (a set), or nil
local function zone_at(zones, x, y, z)
    local ok, list = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(x, y, z))
    for _, zn in ipairs(ok and list or {}) do
        if zones[zn.id] then return zn.id end
    end
    return nil
end

-- The fort's locations and halls whose zone could hold a display:
-- {{zone_id, location_id, type, visitors, x1, y1, x2, y2, z}}.
function room_candidates()
    local out = {}
    pcall(function()
        local site = dfhack.world.getCurrentSite()
        for _, loc in ipairs(site and site.buildings or {}) do
            pcall(function()
                if loc.flags.DOES_NOT_EXIST then return end
                local t = df.abstract_building_type[loc:getType()]
                if not ROOM_TYPES[t] then return end
                local visitors = false
                pcall(function() visitors = loc.flags.VISITORS_ALLOWED == true end)
                for _, bid in ipairs(loc:getContents().building_ids) do
                    local z = df.building.find(bid)
                    if z then
                        table.insert(out, {zone_id = z.id, location_id = loc.id, type = t, visitors = visitors,
                                           x1 = z.x1, y1 = z.y1, x2 = z.x2, y2 = z.y2, z = z.z})
                    end
                end
            end)
        end
    end)
    local seen = {}
    for _, r in ipairs(out) do seen[r.zone_id] = true end
    for t, list in pairs(HALL_LISTS) do
        pcall(function()
            for _, z in ipairs(df.global.world.buildings.other[list]) do
                if not seen[z.id] then
                    seen[z.id] = true
                    table.insert(out, {zone_id = z.id, type = t, visitors = false,
                                       x1 = z.x1, y1 = z.y1, x2 = z.x2, y2 = z.y2, z = z.z})
                end
            end
        end)
    end
    table.sort(out, function(a, b) return a.zone_id < b.zone_id end)
    return out
end

local function in_boxes(boxes, x, y, z)
    for _, a in ipairs(boxes) do
        if a.z == z and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2 then return true end
    end
    return false
end

-- The ways out of a zone's box: the ring of tiles round it, each a wall
-- (shut), a door or hatch, or an open way (anything else that isn't wall
-- or fortification). (doors, openings)
function ways_out(r, B)
    local doors, open = 0, 0
    local function look(x, y)
        local t = B.tile_info(x, y, r.z)
        if not t or t.shape == 'WALL' or t.shape == 'FORTIFICATION' then return end
        if t.building and B.door_at(x, y, r.z) then doors = doors + 1 else open = open + 1 end
    end
    for x = r.x1 - 1, r.x2 + 1 do look(x, r.y1 - 1); look(x, r.y2 + 1) end
    for y = r.y1, r.y2 do look(r.x1 - 1, y); look(r.x2 + 1, y) end
    return doors, open
end

-- The candidate rooms that are the AI's own (centre in a level the AI dug),
-- with their ways out and whether open to the sky.
function ai_rooms(B)
    B = B or builder()
    local okb, boxes = pcall(ai_boxes)
    boxes = okb and boxes or {}
    local out = {}
    for _, r in ipairs(room_candidates()) do
        local cx, cy = (r.x1 + r.x2) // 2, (r.y1 + r.y2) // 2
        if in_boxes(boxes, cx, cy, r.z) then
            local okw, doors, open = pcall(ways_out, r, B)
            r.doors, r.openings = okw and doors or nil, okw and open or nil
            local okt, t = pcall(B.tile_info, cx, cy, r.z)
            r.outside = okt and t and t.outside or nil
            r.secure = okw and doors > 0 and open == 0 or false
            table.insert(out, r)
            if #out >= ROOMS_MAX then break end
        end
    end
    return out
end

-- the squads' assigned gear (a set of item ids)
local function assigned_ids()
    local set = {}
    pcall(function()
        for _, v in pairs(df.global.plotinfo.equipment.items_assigned) do
            pcall(function() for _, id in ipairs(v) do set[id] = true end end)
        end
    end)
    return set
end

local function written(it, kind)
    if WRITTEN_TYPES[kind] then return true end
    if kind == 'TOOL' then
        local ok, id = pcall(function() return it.subtype.id end)
        return ok and WRITTEN_TOOLS[id] == true
    end
    return false
end

-- Where an artifact item is: 'displayed', 'in_building', 'carried', 'in_job',
-- 'forbidden', 'owned', 'away', 'gear', 'written' or 'loose' (free to show),
-- and the building holding it (displayed / in_building).
function state_of(it, kind, assigned, displays)
    local f = it.flags
    if not U.item_pos(it) then return 'away' end
    local okb, hb = pcall(dfhack.items.getHolderBuilding, it)
    if okb and hb then
        if displays[hb.id] then return 'displayed', hb.id end
        return 'in_building', hb.id
    end
    if f.in_job then return 'in_job' end
    local okh, u = pcall(dfhack.items.getHolderUnit, it)
    if okh and u then return 'carried' end
    if f.owned then return 'owned' end
    if f.forbid then return 'forbidden' end
    if written(it, kind) then return 'written' end
    if assigned[it.id] then return 'gear' end
    if f.trader or f.hostile or f.removed or f.garbage_collect or f.in_building or f.construction then
        return 'in_building'
    end
    return 'loose'
end

-- the entity ids that claim an artifact other than the fort's group and civ
function claims_of(a)
    local out = {}
    pcall(function()
        local civ, group = df.global.plotinfo.civ_id, df.global.plotinfo.group_id
        for _, eid in ipairs(a.entity_claims) do
            if eid ~= civ and eid ~= group then table.insert(out, eid) end
        end
    end)
    return out
end

local function entity_name(eid)
    local ok, e = pcall(df.historical_entity.find, eid)
    return ok and e and words(e.name) or ('entity ' .. tostring(eid))
end

-- --- the report ----------------------------------------------------------------

function report()
    local d = registry()
    local first = first_id()
    local B = builder()
    local rooms = ai_rooms(B)
    local room_of = {}
    for _, r in ipairs(rooms) do room_of[r.zone_id] = r end
    -- every zone of a location or hall (the player's too), to place display furniture
    local all_zones, zone_info = {}, {}
    for _, r in ipairs(room_candidates()) do all_zones[r.zone_id] = true; zone_info[r.zone_id] = r end

    local displays, dset, by_zone = {}, {}, {}
    for _, b in ipairs(display_buildings()) do
        local kind, n = display_state(b)
        local zid = zone_at(all_zones, b.centerx or b.x1, b.centery or b.y1, b.z)
        local zi = zid and zone_info[zid]
        local row = {id = b.id, kind = kind, items = n, cap = CAP[kind], x = b.centerx or b.x1, y = b.centery or b.y1,
                     z = b.z, built = built(b), ai = is_mine_display(d, b.id), zone_id = zid,
                     location = zi and zi.type or nil, ai_room = zid ~= nil and room_of[zid] ~= nil}
        dset[b.id] = row
        if zid then by_zone[zid] = (by_zone[zid] or 0) + 1 end
        if #displays < DISPLAYS_MAX then table.insert(displays, row) end
    end
    for _, r in ipairs(rooms) do r.displays = by_zone[r.zone_id] or 0 end

    local assigned = assigned_ids()
    local arts, counts = {}, {total = 0, mine = 0, displayed = 0, loose = 0, mine_loose = 0, claimed = 0,
                                 displayed_open = 0}
    for _, it in ipairs(artifact_items()) do
        local a = record_of(it)
        local aid = a and int(a.id)
        local kind = U.item_kind(it)
        local st, bid = state_of(it, kind, assigned, dset)
        if st ~= 'away' then
            counts.total = counts.total + 1
            local mine = aid ~= nil and aid >= first
            local row = {id = aid, item_id = it.id, kind = kind, state = st, mine = mine, building_id = bid}
            local x, y, z = U.item_pos(it)
            row.x, row.y, row.z = x, y, z
            row.name = a and words(a.name) or nil
            local cl = a and claims_of(a) or {}
            if #cl > 0 then
                row.claimed_by = {}
                for i = 1, math.min(3, #cl) do table.insert(row.claimed_by, entity_name(cl[i])) end
                counts.claimed = counts.claimed + 1
            end
            if mine then counts.mine = counts.mine + 1 end
            if st == 'displayed' then
                counts.displayed = counts.displayed + 1
                local disp = dset[bid]
                local r = disp and disp.zone_id and (room_of[disp.zone_id] or zone_info[disp.zone_id])
                if r and r.visitors then counts.displayed_open = counts.displayed_open + 1 end
            end
            if st == 'loose' then
                counts.loose = counts.loose + 1
                if mine then counts.mine_loose = counts.mine_loose + 1 end
            end
            table.insert(arts, row)
        end
    end
    -- the AI's loose ones first, then the claimed, then by id
    table.sort(arts, function(p, q)
        local pa, qa = p.mine and p.state == 'loose', q.mine and q.state == 'loose'
        if pa ~= qa then return pa end
        if (p.claimed_by ~= nil) ~= (q.claimed_by ~= nil) then return p.claimed_by ~= nil end
        return (p.id or -1) < (q.id or -1)
    end)
    while #arts > ARTIFACTS_MAX do table.remove(arts) end

    local free = {pedestal = 0, case = 0}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.TOOL) do
            local k = tool_kind(it)
            if k and U.item_free(it) then free[k] = free[k] + 1 end
        end
    end)
    local api = {display_job = false}
    pcall(function() api.display_job = df.job_type.PutItemOnDisplay ~= nil end)
    return {artifacts = arts, counts = counts, displays = displays, rooms = rooms, free = free,
            first_id = first < math.maxinteger and first or nil, api = api}
end

-- --- the actions -----------------------------------------------------------------

local function reject(msg, extra)
    local out = {ok = false, rejected = true, error = msg}
    for k, v in pairs(extra or {}) do out[k] = v end
    return out
end

-- o: {zone_id, kind = 'pedestal'|'case'}
function place_display(o, dry_run)
    local kind = o.kind or 'pedestal'
    if not KINDS[kind] then return reject('place_display: kind is pedestal or case') end
    local B = builder()
    local room
    for _, r in ipairs(ai_rooms(B)) do if r.zone_id == o.zone_id then room = r end end
    if not room then
        return reject(('zone %s is no location or hall in a level the AI dug: the player\'s rooms are '
            .. 'left as they are'):format(tostring(o.zone_id)))
    end
    local item
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.TOOL) do
            if tool_kind(it) == kind and U.item_free(it) then item = it; break end
        end
    end)
    if not item then return reject('no free ' .. (kind == 'case' and 'display case' or 'pedestal') .. ' in store') end
    local okA, area = pcall(B.zone_area, room.zone_id)
    if not okA or not area then return reject('no zone ' .. tostring(room.zone_id)) end
    local okS, spots = pcall(B.zone_spots, area)
    spots = okS and spots or {}
    if #spots == 0 then return reject('no free floor beside a wall in zone ' .. room.zone_id) end
    if dry_run then
        return {ok = true, dry_run = true, zone_id = room.zone_id, kind = kind, x = spots[1].x, y = spots[1].y}
    end
    local last
    for i = 1, math.min(#spots, 12) do
        local sp = spots[i]
        local ok, b, err = pcall(dfhack.buildings.constructBuilding,
                                 {type = df.building_type.DisplayFurniture, pos = xyz2pos(sp.x, sp.y, area.z),
                                  items = {item}})
        if ok and b then
            local d = registry()
            table.insert(d.displays, b.id)
            save(d)
            return {ok = true, building_id = b.id, zone_id = room.zone_id, kind = kind, x = sp.x, y = sp.y,
                    location = room.type}
        end
        last = ok and tostring(err) or tostring(b)
    end
    return {ok = false, error = 'the game took the ' .. kind .. ' at none of the spots: ' .. tostring(last):sub(1, 120)}
end

-- o: {item_id, building_id}
function display_artifact(o, dry_run)
    local it = df.item.find(o.item_id)
    if not it then return reject('no item ' .. tostring(o.item_id)) end
    if not it.flags.artifact then return reject('item ' .. it.id .. ' is no artifact') end
    local a = record_of(it)
    if not a or int(a.id) == nil or int(a.id) < first_id() then
        return reject('that artifact was the fort\'s before the AI came: the player\'s to place')
    end
    local d = registry()
    local b = df.building.find(o.building_id)
    if not b or not is_mine_display(d, b.id) then
        return reject('building ' .. tostring(o.building_id) .. ' is no display furniture the AI placed')
    end
    if not built(b) then return reject('that display is not built yet') end
    local kind, n = display_state(b)
    local cap = CAP[kind] or 1
    local waiting = 0
    pcall(function()
        for _, j in ipairs(b.jobs) do
            if j.job_type == df.job_type.PutItemOnDisplay then waiting = waiting + 1 end
        end
    end)
    if n + waiting >= cap then return reject(('that %s holds %d already'):format(kind, n + waiting)) end
    local st = state_of(it, U.item_kind(it), assigned_ids(), {})
    if st ~= 'loose' then return reject('that artifact is ' .. st .. ': left where it is') end
    local guard = haul_guard(it, b)
    if guard then return reject('that artifact lies ' .. guard .. ': no hauler sent') end
    local okj = pcall(function() return df.job_type.PutItemOnDisplay end)
    if not (okj and df.job_type.PutItemOnDisplay and dfhack.job.attachJobItem and dfhack.job.linkIntoWorld) then
        return reject('this DF version has no put-on-display job')
    end
    if dry_run then return {ok = true, dry_run = true, item_id = it.id, building_id = b.id, kind = kind} end
    local job = df.job:new()
    job.job_type = df.job_type.PutItemOnDisplay
    job.pos = xyz2pos(b.centerx, b.centery, b.z)
    dfhack.job.addGeneralRef(job, df.general_ref_type.BUILDING_HOLDER, b.id)
    if not dfhack.job.attachJobItem(job, it, df.job_item_ref.T_role.Hauled, -1, -1) then
        dfhack.job.linkIntoWorld(job, true)
        dfhack.job.removeJob(job)
        return {ok = false, error = 'the game would not attach the artifact to the display job'}
    end
    dfhack.job.linkIntoWorld(job, true)
    b.jobs:insert('#', job)
    return {ok = true, job_id = job.id, item_id = it.id, building_id = b.id, kind = kind,
            name = words(a.name)}
end
