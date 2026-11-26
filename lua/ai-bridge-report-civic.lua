-- ai-bridge-report-civic: the report's meetings (get_meetings), the answer
-- to a petition (answer_petition), the locations (get_locations) and the
-- stocks (get_stocks).
--
-- A part of ai-bridge.lua (0.105.119, split out of ai-bridge-report.lua when
-- it reached the size limit), loaded by it right after ai-bridge-report into
-- its own environment, as every part: what is global here is the bridge's
-- (reachable as reqscript('ai-bridge').<name>), and the bridge's shared
-- helpers are at hand. Not a command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-report-civic is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report-civic'] = '0.105.126'   -- bumped with BRIDGE_VERSION

-- (0.91) Meetings (read only, a probe): diplomats and the outpost liaison
-- meet the fort's leader (plotinfo.activities: the actor, the noble met, the
-- zone, its flags), the diplomacy under way (plotinfo.dip_meeting_info: the
-- civ, its topics), who waits to be heard (meeting_requests), and whether
-- DF is showing or about to show the meeting screen (dipscript_popups; the
-- current screen), which the player answers by hand and an unattended run
-- may not.
local function unit_word(id)
    local u = id and id ~= -1 and df.unit.find(id)
    if not u then return nil end
    local ok, n = pcall(function() return txt(dfhack.units.getReadableName(u)) end)
    return ok and n or tostring(id)
end

function get_meetings()
    local out = {}
    pcall(function()
        for _, a in ipairs(df.global.plotinfo.activities) do
            local e = {actor = unit_word(a.unit_actor), noble = unit_word(a.unit_noble), place = a.place,
                       delay = a.delay, room_rank = a.worstroomrank, flags = {}}
            for _, f in ipairs({'next_step', 'checked_building', 'add_delay', 'topic_discussed', 'meeting_done'}) do
                pcall(function() if a.flags[f] then table.insert(e.flags, f) end end)
            end
            if a.tree_quota and a.tree_quota ~= -1 then e.tree_quota = a.tree_quota end
            -- (0.105.24) a visitor (not a citizen) meeting the noble: B and F's
            -- mayors (2-5 Nov) met poets, dancers and bards, who come to ask to
            -- stay, as often as their own citizens ("unable to complain")
            pcall(function()
                local u = df.unit.find(a.unit_actor)
                if u and not dfhack.units.isCitizen(u) then e.visitor = true end
                -- (0.105.26) a resident (lives here, not a citizen) isn't a visitor come to ask
                if e.visitor and dfhack.units.isResident and dfhack.units.isResident(u) then e.resident = true end
                -- (0.105.30 live fixes) a stranger: a visitor, not a resident, not of the
                -- fort's race (E's thief, 8 Nov, a weasel woman, asked for meetings first)
                if e.visitor and not e.resident and u.race ~= df.global.plotinfo.race_id then e.stranger = true end
            end)
            out.activities = out.activities or {}
            table.insert(out.activities, e)
        end
    end)
    pcall(function()
        for _, m in ipairs(df.global.plotinfo.dip_meeting_info) do
            local ent = df.historical_entity.find(m.civ_id)
            local cr = ent and df.creature_raw.find(ent.race)
            local e = {civ = m.civ_id, race = cr and cr.creature_id or nil, step = m.cur_step, topics = {}}
            for _, t in ipairs(m.topic_list) do table.insert(e.topics, df.meeting_topic[t] or tostring(t)) end
            local hf = df.historical_figure.find(m.diplomat_id)
            local u = hf and df.unit.find(hf.unit_id)
            e.diplomat = u and unit_word(u.id) or nil
            out.diplomacy = out.diplomacy or {}
            table.insert(out.diplomacy, e)
        end
    end)
    pcall(function() out.requests = #df.global.plotinfo.meeting_requests end)
    -- (0.105.24) of those waiting, the visitors (an entry that is a unit id or holds one)
    pcall(function()
        local n, res = 0, 0
        for _, r in ipairs(df.global.plotinfo.meeting_requests) do
            local id = type(r) == 'number' and r or nil
            if not id then pcall(function() id = r.unit_id end) end
            local u = id and df.unit.find(id)
            if u and not dfhack.units.isCitizen(u) then
                n = n + 1
                local resident = dfhack.units.isResident and dfhack.units.isResident(u)
                if resident then res = res + 1 end   -- (0.105.26)
                -- (0.105.30 live fixes) of those, strangers: not residents, not of the fort's race
                if not resident and u.race ~= df.global.plotinfo.race_id then
                    out.strangers = out.strangers or {}
                    if #out.strangers < 5 then table.insert(out.strangers, unit_word(u.id)) end
                    out.requests_strangers = (out.requests_strangers or 0) + 1
                end
            end
        end
        out.requests_visitors = n
        out.requests_residents = res     -- (0.105.26) of those, residents (not visitors come to ask)
        out.requests_strangers = out.requests_strangers or 0
    end)
    pcall(function() out.popups = #df.global.plotinfo.dipscript_popups end)
    pcall(function() out.screen = dfhack.gui.getCurFocus(true)[1] end)
    return out
end

-- (0.89) Answer a location petition (a temple or guildhall) as the
-- petitions screen does: agreeing clears the agreement's "not approved" flag
-- (DFHack's list-agreements: "this gets unset by accepting a petition") and
-- takes it off the waiting list; declining only takes it off the list.
function answer_petition(id, accept, dry_run)
    local list = df.global.plotinfo.petitions
    local idx
    for i, v in ipairs(list) do if v == id then idx = i end end
    if idx == nil then return {ok = false, rejected = true, error = 'no petition ' .. tostring(id) .. ' is waiting'} end
    local a = df.agreement.find(id)
    local d = a and a.details[0]
    local kind = d and df.agreement_details_type[d.type]
    -- (0.105.9) residency too (every fort held 300+ waiting); (r10 p1) citizenship
    -- declined as residency is (off the list); agreed only by DF's standing order
    if not d or (kind ~= 'Location' and kind ~= 'Residency' and (kind ~= 'Citizenship' or accept)) then
        return {ok = false, rejected = true, error = kind == 'Citizenship' and 'citizenship is agreed by DF\'s standing order or its petitions screen'
                or 'only temple, guildhall, residency and (declined) citizenship petitions are answered by the AI'}
    end
    local wish = kind == 'Location' and location_wish(a) or nil
    local out = {ok = true, id = id, accepted = accept or nil, declined = (not accept) or nil, wish = wish,
                 kind = kind, dry_run = dry_run or nil}
    if kind == 'Residency' or kind == 'Citizenship' then
        pcall(function()
            local party = d.data[kind].applicant
            for _, pt in ipairs(a.parties) do
                if pt.id == party and #pt.histfig_ids > 0 then
                    local hf = df.historical_figure.find(pt.histfig_ids[0])
                    out.unit = hf and hf.unit_id >= 0 and hf.unit_id or nil
                end
            end
        end)
    end
    if dry_run then return out end
    local busy = petitions_screen_busy()     -- (r10 p1) never under the player's eyes
    if busy then return {ok = false, waiting = true, id = id, error = busy .. ': answered later'} end
    if accept then a.flags.petition_not_accepted = false end
    list:erase(idx)
    local still = false
    for _, v in ipairs(list) do if v == id then still = true end end
    out.ok = not still and (not accept or a.flags.petition_not_accepted == false)
    return out
end

-- The fort's locations (temples, taverns, libraries...), by type.
LOCATION_SUPPLIES = {'goblets', 'instruments', 'paper', 'splints', 'thread', 'cloth', 'crutches', 'powder',
                     'buckets', 'soap'}

-- (R29 W5) the written items (BOOK, or a quire/scroll with WRITING) and the
-- blank quires and scrolls held by the furniture standing in a location's
-- zones (bookcases, chests): written, blank
local function written_on(it)
    if it:getType() == df.item_type.BOOK then return true end
    local w = false
    pcall(function()
        for _, imp in ipairs(it.improvements) do
            if imp:getType() == df.improvement_type.WRITING then w = true end
        end
    end)
    return w
end

local function library_books(c)
    local n, blank = 0, 0
    for _, bid in ipairs(c.building_ids) do
        local z = df.building.find(bid)
        for _, ib in ipairs(z and z.contained_buildings or {}) do
            local bt = df.building_type[ib:getType()]
            if bt == 'Bookcase' or bt == 'Box' then
                for _, ci in ipairs(ib.contained_items) do
                    local it = ci.item
                    if it and ci.use_mode ~= df.building_item_role_type.PERM then
                        if written_on(it) then n = n + 1
                        else
                            local okt, id = pcall(function() return it.subtype.id end)
                            if okt and (id == 'ITEM_TOOL_QUIRE' or id == 'ITEM_TOOL_SCROLL') then blank = blank + 1 end
                        end
                    end
                end
            end
        end
    end
    return n, blank
end

function get_locations()
    local site = dfhack.world.getCurrentSite()
    -- count = {...}: never an empty table, which would reach Python as a list
    local out = {count = {}, total = 0}
    if not site then return out end
    for _, b in ipairs(site.buildings) do
        local gone = false
        pcall(function() gone = b.flags.DOES_NOT_EXIST end)
        if not gone then
            local t = df.abstract_building_type[b:getType()] or tostring(b:getType())
            out.count[t] = (out.count[t] or 0) + 1
            out.total = out.total + 1
            -- (0.83) what each location keeps and holds, and who works there:
            -- DF's location screen (desired goblets, instruments, paper,
            -- thread...; the counts the game last took; the occupations)
            pcall(function()
                local c = b:getContents()
                if not c then return end
                local e = {id = b.id, type = t, tier = c.location_tier, value = c.location_value,
                           want = {}, have = {}, jobs = {}}
                for _, k in ipairs(LOCATION_SUPPLIES) do
                    pcall(function()
                        e.want[k] = c['desired_' .. k]
                        e.have[k] = c['count_' .. k]
                    end)
                end
                pcall(function() e.want.copies = c.desired_copies end)
                pcall(function()
                    for _, k in ipairs(LOCATION_SUPPLIES) do
                        if c.need_more[k] then e.short = e.short or {}; table.insert(e.short, k) end
                    end
                end)
                -- (R29 W5) a library's books: the written items (codices, written
                -- quires and scrolls) on its bookcases and in its chests. Until R29
                -- `books` was #copied_artifacts, a list DF never fills in a fort:
                -- 0 in every fort ever, while A held 6 codices and B 11 plus 11
                -- copies (probe 25 Nov 21:32). That list stays as copied_artifacts
                if t == 'LIBRARY' then
                    pcall(function() e.copied_artifacts = #b.copied_artifacts end)
                    pcall(function() e.books, e.blank = library_books(c) end)
                    -- scholars no longer happy (the wiki: some dislike the post): given back
                    pcall(function()
                        for _, o in ipairs(b.occupations) do
                            local u = o.unit_id ~= -1 and df.unit.find(o.unit_id)
                            if u and df.occupation_type[o.type] == 'SCHOLAR' then
                                local okc, cat = pcall(dfhack.units.getStressCategory, u)
                                if okc and type(cat) == 'number' and cat <= 1 then
                                    e.unhappy = e.unhappy or {}
                                    table.insert(e.unhappy, {post = 'SCHOLAR', unit_id = u.id})
                                end
                            end
                        end
                    end)
                end
                -- (0.105.12, 14.1 step 4) who may come in (DF's location screen:
                -- visitors, residents, members only): the flags set, by name
                pcall(function()
                    local on = {}
                    for k, v in pairs(b.flags) do
                        if v == true then table.insert(on, tostring(k)) end
                    end
                    e.flags = on
                end)
                -- (0.104.146) a temple's dedication: to one deity (its worshippers
                -- pray there), a religion (its deities), or all ('any')
                if t == 'TEMPLE' then
                    pcall(function()
                        local dt = df.religious_practice_type[b.deity_type]
                        if dt == 'WORSHIP_HFID' then
                            e.deity_hf = b.deity_data.Deity
                        elseif dt == 'RELIGION_ENID' then
                            e.religion = b.deity_data.Religion      -- (0.89)
                            local ent = df.historical_entity.find(b.deity_data.Religion)
                            e.religion_deities = {}
                            for _, hfid in ipairs(ent and ent.relations.deities or {}) do
                                table.insert(e.religion_deities, hfid)
                            end
                        else
                            e.any_deity = true
                        end
                    end)
                    if e.deity_hf == nil and e.religion_deities == nil then e.any_deity = true end
                end
                -- (0.90) its zones (furniture goes into the first)
                pcall(function()
                    for _, bid in ipairs(c.building_ids) do
                        e.zones = e.zones or {}
                        table.insert(e.zones, bid)
                    end
                end)
                -- (0.104.4) chests standing in its zones: a tavern keeps its goblets
                -- (and a temple its instruments) in a chest of its own
                pcall(function()
                    local n, off, ch, lone = 0, 0, {}, {}
                    e.zone_chairs = ch      -- (item39) zone id -> its chairs (pair_chairs)
                    -- (R30c item24) zone id -> its chairs with no chair beside them
                    -- (pair_chairs' own test, the four sides): A asked 5 times in 3 h
                    -- and C twice, refused "every chair in zone N has one beside it"
                    e.zone_lone_chairs = lone
                    for _, bid in ipairs(c.building_ids) do
                        local z = df.building.find(bid)
                        local at = {}
                        for _, ib in ipairs(z and z.contained_buildings or {}) do
                            local t = df.building_type[ib:getType()]
                            if t == 'Box' then n = n + 1
                            elseif t == 'Chair' then ch[tostring(bid)] = (ch[tostring(bid)] or 0) + 1
                                at[#at + 1] = {ib.x1, ib.y1}
                            end
                        end
                        if #at > 0 then
                            local set, k = {}, 0
                            for _, p in ipairs(at) do set[p[1] .. ',' .. p[2]] = true end
                            for _, p in ipairs(at) do
                                local x, y = p[1], p[2]
                                if not (set[(x + 1) .. ',' .. y] or set[(x - 1) .. ',' .. y]
                                        or set[x .. ',' .. (y + 1)] or set[x .. ',' .. (y - 1)]) then k = k + 1 end
                            end
                            lone[tostring(bid)] = k
                        end
                        pcall(function() if z.spec_sub_flag.active == false then off = off + 1 end end)
                    end
                    e.chests = n
                    -- (0.105.113 item9) every zone inactive: nobody gathers there
                    if off > 0 and off == #c.building_ids then e.inactive = true end
                end)
                -- (0.103.13) a location laid over a dining hall (the AI's stop-gap
                -- temple or tavern, or one the player made so): its zones all
                -- share their centre with a dining hall zone
                pcall(function()
                    local all = #c.building_ids > 0
                    for _, bid in ipairs(c.building_ids) do
                        local z, here = df.building.find(bid), false
                        if z then
                            local okz, zs = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(z.centerx, z.centery, z.z))
                            for _, o in ipairs(okz and zs or {}) do
                                if o.id ~= z.id and df.civzone_type[o.type] == 'DiningHall' then here = true end
                            end
                        end
                        if not here then all = false end
                    end
                    if all then e.over_dining = true end
                end)
                -- (0.89) what a guildhall's for (a temple's dedication: above)
                if t == 'GUILDHALL' then pcall(function() e.profession = df.profession[c.profession] end) end
                pcall(function()
                    for _, o in ipairs(b.occupations) do
                        local k = df.occupation_type[o.type] or tostring(o.type)
                        local j = e.jobs[k] or {posts = 0, filled = 0}
                        j.posts = j.posts + 1
                        if o.histfig_id ~= -1 then j.filled = j.filled + 1 end
                        e.jobs[k] = j
                    end
                end)
                if next(e.jobs) == nil then e.jobs = nil end
                out.list = out.list or {}
                table.insert(out.list, e)
            end)
        end
    end
    out.built = abs_tick()     -- (0.105.26) when this copy was built (the section is cached): the planner
                               -- tells a stale "open" from the player opening a place the AI shut
    return out
end

FREE_STOCKS = {mechanisms = true, blocks = true, chains = true, bins = true, barrels = true}

-- (0.100, review) Counting in the background between reports was tried
-- and dropped: run all the time it cost more frame time over a session than
-- the 27 ms a report it saved, and counts a few seconds old made the
-- "have + queued" rules order twice. One count a report, as before.
function get_stocks()
    local stocks = {}
    for _, cat in ipairs(STOCK_CATEGORIES) do
        local label = cat[1]
        local w = stock_walk(cat[2])
        local free = w.free
        stocks[label] = w.count
        -- (0.104.155) those no job has claimed: Teacheroar's 3 mechanisms "in
        -- store" were all taken, so no rule ordered more while 6 buildings waited
        if FREE_STOCKS[label] then stocks[label .. '_free'] = free end
        -- (0.104.156) mechanisms by the link's own test (none on a tile no dwarf
        -- can walk to, forbidden or owned): 3 counted free, 1 usable, no order
        if label == 'mechanisms' then
            local okc, c = pcall(function() return reqscript('ai-gates').mechanism_counts() end)
            if okc and type(c) == 'table' and type(c.usable) == 'number' then
                stocks.mechanisms_free = math.min(free, c.usable)
                if c.unwalkable_at then stocks.mechanisms_unwalkable_at = c.unwalkable_at end
            end
        end
    end
    return stocks
end
