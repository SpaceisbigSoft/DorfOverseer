-- ai-bridge-actions-civic: the action handlers for ice, memorial slabs, furniture, posts,
-- rooms, workshops, meetings, missions sent out, squads and uniforms, stone
-- use, presets and rules, disposal, world cleanup, hauling, the food store,
-- pile links, provisions and artifacts.
--
-- A part of ai-bridge.lua (r6, split out of ai-bridge-actions.lua when it was 204 KB),
-- loaded by it after ai-bridge-actions into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-actions files share with this one come from ACTIONS_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-actions-civic is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-actions-civic'] = '0.105.121'   -- bumped with BRIDGE_VERSION

local string_list = ACTIONS_PART_LOCALS.string_list

-- (0.104.45) Water the dwarves walk over: a river or pond freezes in winter,
-- the dwarves cross the ice, and it thaws under them (Enxah: the drowned lie
-- in the river channel past the main stair; SUFFOCATE and DROWN 6 a year).
-- The tile above every water or ice tile on the given levels, within
-- `radius` of (cx, cy), gets the game's "restricted" traffic, so paths go
-- round it (a bridge or a way across stays usable: restricted only costs).
-- Never a tile the player marked high or low (the AI's own painted High/Low,
-- ai-traffic ai_value, may be restricted).
function act_restrict_water(a)
    local zs = type(a.levels) == 'table' and a.levels or {}
    local cx, cy = whole_number(a.x), whole_number(a.y)
    local r = whole_number(a.radius) or 60
    -- (0.105.33) up to 9 levels: the brain's drowning guard sends the top
    -- three of every water body (planner_wells._water_traffic_rule, [:9]),
    -- and a map with three such bodies was refused every cycle
    if #zs == 0 or #zs > 9 or not cx or not cy or r < 5 or r > 120 then
        return reject('levels (1-9), x, y and radius 5-120 needed')
    end
    local sx, sy, sz = dfhack.maps.getTileSize()
    local marked, seen = 0, 0
    local frozen = df.tiletype_material.FROZEN_LIQUID
    local memo = {}
    local function ai_painted(x, y, z)
        local ok, v = pcall(function() return reqscript('ai-traffic').ai_value(x, y, z, memo) end)
        return ok and v or nil
    end
    local x0, x1 = math.max(0, cx - r), math.min(sx - 1, cx + r)
    -- (0.105.33) one protected call a row, not one closure a tile (~87k a call)
    local function row(y, z)
        for x = x0, x1 do
            local pos = xyz2pos(x, y, z)
            local d = dfhack.maps.getTileFlags(pos)
            local wet = d and d.flow_size > 0 and not d.liquid_type
            if d and not wet then
                local tt = dfhack.maps.getTileType(pos)
                wet = tt and df.tiletype.attrs[tt].material == frozen
            end
            if wet then
                seen = seen + 1
                local up = dfhack.maps.getTileFlags(xyz2pos(x, y, z + 1))
                -- (0.105.41 review) Normal, or the High/Low the AI painted
                -- itself (ai-traffic): never a value the player set by hand
                if up and (up.traffic == df.tile_traffic.Normal
                           or (up.traffic ~= df.tile_traffic.Restricted
                               and up.traffic == ai_painted(x, y, z + 1))) then
                    if not a.dry_run then up.traffic = df.tile_traffic.Restricted end
                    marked = marked + 1
                end
            end
        end
    end
    for _, z0 in ipairs(zs) do
        local z = whole_number(z0)
        if z and z >= 0 and z + 1 < sz then
            for y = math.max(0, cy - r), math.min(sy - 1, cy + r) do
                pcall(row, y, z)
            end
        end
    end
    if seen == 0 then return reject('no water or ice on those levels near the fort') end
    if marked == 0 then
        -- (0.104.138) nothing left to do is not a failure: the brain rests it long
        return {ok = false, rejected = true, nothing_to_do = true,
                error = ('all %d tiles over the water are already restricted (or set by hand)'):format(seen)}
    end
    return {ok = true, marked = marked, water_tiles = seen, dry_run = a.dry_run or nil}
end

-- (0.104.42) Memorial slabs that never get put up: the construction of the
-- slab (a building the AI placed) suspended, or the engraved slab itself
-- forbidden (Enxah: 9 ghosts, 5 MurderousGhosts among them, each with its
-- slab made; 5 slab buildings suspended at stage 0, 4 slabs forbidden;
-- 25 of 36 deaths in a year from fright). The slabs unforbidden where the
-- dwarves can reach them, the slab buildings' jobs resumed.
function act_free_slabs(a)
    local from = citizen_anchor()
    local unforbid, resumed, cleared, moved = 0, 0, 0, 0
    for _, it in ipairs(df.global.world.items.other.SLAB) do
        pcall(function()
            if it.engraving_type == df.slab_engraving_type.Memorial and not it.flags.in_building then
                if not it.flags.in_job then
                    local x, y, z = dfhack.items.getPosition(it)
                    local reach = x and (not from or dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z)))
                    if x and not reach and from and not it.flags.in_inventory then
                        -- (0.104.49) shut in the rock (Enxah's oldest ghost's slab lay
                        -- inside a wall tile, a wall built over where it lay): brought
                        -- out to where a dwarf stands, the way it would have been carried
                        if a.dry_run then
                            moved = moved + 1     -- (0.105.33) counted in a dry run too
                        elseif dfhack.items.moveToGround(it, from) then
                            moved = moved + 1
                            it.flags.forbid = false
                        end
                    elseif it.flags.forbid and reach then
                        if not a.dry_run then it.flags.forbid = false end
                        unforbid = unforbid + 1
                    end
                end
                for _, ref in ipairs(it.specific_refs) do
                    if ref.type == df.specific_ref_type.JOB then
                        local j = ref.data.job
                        local h = dfhack.job.getHolder(j)
                        if j.flags.suspend and h and h:getType() == df.building_type.Slab then
                            -- (0.104.47) suspendmanager: "Blocked by an unmovable item":
                            -- what lies on the site is unforbidden, so the builder can
                            -- clear it (never the slab itself, an artifact, or an item
                            -- on someone's job)
                            pcall(function()
                                local own = {}
                                for _, ji in ipairs(j.items) do own[ji.item.id] = true end
                                local bx, by, bz = h.centerx, h.centery, h.z
                                for _, iid in ipairs(dfhack.maps.getTileBlock(bx, by, bz).items) do
                                    local o = df.item.find(iid)
                                    if o and not own[o.id] and o.pos.x == bx and o.pos.y == by and o.pos.z == bz
                                            and not o.flags.in_job and not o.flags.artifact then
                                        if not a.dry_run then o.flags.forbid = false end
                                        cleared = cleared + 1
                                    end
                                end
                            end)
                            if not a.dry_run then j.flags.suspend = false end
                            resumed = resumed + 1
                        end
                    end
                end
            end
        end)
    end
    if unforbid + resumed + moved == 0 then return reject('no memorial slab forbidden, shut in or held by a suspended job') end
    return {ok = true, unforbidden = unforbid, resumed = resumed, cleared = cleared, moved = moved, dry_run = a.dry_run or nil}
end

-- (0.103.16) Engraved memorial slabs built, so the ghosts rest.
function act_place_slabs(a)
    local n = int_in(a.max or 5, 1, 20)
    if not n then return reject('place_slabs needs max 1-20') end
    return reqscript('ai-builder').place_slabs(n, a.dry_run == true)
end

-- (0.88) one piece of furniture into a zone: zone_id, what (traction_bench)
function act_place_in_zone(a)
    local id = whole_number(a.zone_id)
    if not id then return reject('place_in_zone needs zone_id') end
    local B = reqscript('ai-builder')
    if not B.ZONE_FURNITURE[a.what] then
        return reject('place_in_zone: what must be one of ' .. table.concat(sorted_keys(B.ZONE_FURNITURE), ', '))
    end
    return B.place_in_zone(id, a.what, a.dry_run == true)
end

function act_vacate_post(a)    -- (0.104.111) a doctor who is a patient gives his post back
    local id, uid = whole_number(a.location_id), whole_number(a.unit_id)
    if not id or not uid then return reject('vacate_post needs location_id and unit_id') end
    return reqscript('ai-society').vacate_post(id, uid, a.dry_run == true, txt)
end

-- (0.87.3) a post's labours for its holders (the game's screen turns them on)
function act_staff_labors(a)
    local id = whole_number(a.location_id)
    if not id then return reject('staff_labors needs location_id') end
    return reqscript('ai-society').staff_labors(id, a.dry_run == true, txt)
end

-- (0.85) posts at a location the game hasn't made yet (as its screen does)
function act_add_posts(a)
    local id = whole_number(a.location_id)
    if not id then return reject('add_posts needs location_id') end
    local kinds = type(a.posts) == 'table' and a.posts or nil
    return reqscript('ai-society').add_posts(id, kinds, a.dry_run == true)
end

-- Trinkets for dwarves who want to own things (lua/ai-society.lua).
function act_give_trinkets(a)
    local n = whole_number(a.max) or 10
    if n < 1 or n > 50 then return reject('give_trinkets needs max 1-50') end
    return reqscript('ai-society').give_trinkets(n, a.dry_run == true)
end

-- (0.104.168) One bedroom per household (a couple in two keeps the better,
-- one with none gets the best free one), and up to `upgrade` of the most
-- stressed moved to a free room much better for them (their likes counted)
-- (lua/ai-homes.lua). {house = 0-30, upgrade = 0-20}
-- (E4) place = true: rooms chosen by their place too (the citizens' taste)
function act_house_dwarves(a)
    local h, u = int_in(a.house or 0, 0, 30), int_in(a.upgrade or 0, 0, 20)
    if not h or not u or h + u == 0 then return reject('house_dwarves needs house 0-30 and upgrade 0-20, not both 0') end
    return reqscript('ai-homes').house(h, u, a.dry_run == true, txt, nil, a.place == true or nil)
end

-- (E4) Up to n citizens' own bedrooms (rooms the AI dug) given a piece of
-- the stock's furniture in a material, or showing a creature or item, they
-- like (lua/ai-homes.lua furnish_liked). {n = 1-10}
function act_furnish_liked(a)
    local n = int_in(a.n or 0, 1, 10)
    if not n then return reject('furnish_liked needs n 1-10') end
    return reqscript('ai-homes').furnish_liked(n, a.dry_run == true, txt)
end

-- Workshops the fort has far too many of, taken down (lua/ai-builder.lua).
function act_remove_workshops(a)
    if a.kind ~= 'SoapMaker' and a.kind ~= 'ScrewPress' then
        return reject('remove_workshops needs kind SoapMaker|ScrewPress')
    end
    local keep, max = whole_number(a.keep) or 1, whole_number(a.max) or 20
    return reqscript('ai-builder').remove_workshops(a.kind, keep, math.min(max, 40), a.dry_run == true)
end

-- A feeder stockpile beside a workshop (or goods beside the depot) (lua/ai-builder.lua).
function act_feeder_pile(a)
    local id = whole_number(a.building_id)
    if not id then return reject('feeder_pile needs building_id') end
    return reqscript('ai-builder').place_feeder(id, a.dry_run == true)
end

-- The trade screen opened from the depot (lua/ai-trade.lua), or closed.
function act_open_trade(a)
    return reqscript('ai-trade').open_screen(a.dry_run == true, txt)
end

-- (0.104.0) DF's meeting screen (a diplomat or the liaison) holds the game
-- until someone answers; nobody is at the game in an unattended run, so after
-- a long wait the overseer leaves it, as the player would with Esc: the
-- meeting ends without an agreement. Only that screen is ever left.
function meeting_focus()
    local ok, f = pcall(function() return dfhack.gui.getCurFocus(true)[1] end)
    f = ok and tostring(f or '') or ''
    local low = f:lower()
    return (low:find('meeting', 1, true) or low:find('diplomacy', 1, true)) and f or nil
end

-- (0.104.95) a sand collection zone (for glass), placed by the builder
function act_sand_zone(a)
    return reqscript('ai-builder').sand_zone(a.dry_run == true)
end

-- (0.104.2) A Water Source zone for the injured while there is no well (lua/ai-builder.lua).
function act_water_zone(a)
    if type(a.points) ~= 'table' or #a.points == 0 or #a.points > 6 then
        return reject('water_zone needs points: 1-6 water tiles {x, y, z}')
    end
    local pts = {}
    for _, p in ipairs(a.points) do
        local x, y, z = int_in(p.x, 0, 1000), int_in(p.y, 0, 1000), int_in(p.z, 0, 1000)
        if not (x and y and z) then return reject('water_zone: a point needs whole x, y and z') end
        table.insert(pts, {x = x, y = y, z = z})
    end
    return reqscript('ai-builder').water_zone(pts, a.dry_run == true)
end

function act_close_meeting(a)
    local f = meeting_focus()
    if not f then return {ok = false, rejected = true, error = 'no meeting screen is open'} end
    if a.dry_run then return {ok = true, dry_run = true, screen = f} end
    pcall(function()
        require('gui').simulateInput(dfhack.gui.getDFViewscreen(true), 'LEAVESCREEN')
    end)
    local after = meeting_focus()
    return {ok = after == nil, screen = f, error = after and ('the meeting screen is still open (' .. after .. ')') or nil}
end

-- (0.105.0, 12b) The meeting screen answered with the AI's defaults (trade
-- and peace agreed, the elves' tree quota kept, tribute by the Rules choice,
-- the requests' wishes ticked), through the buttons the player showed the AI
-- once (lua/ai-diplomacy.lua). Each open screen is written to
-- meeting-probe.json. tribute: small | pay | refuse; wishes: DF's request
-- categories (entity_sell_category names), at most 20.
function act_answer_meeting(a)
    if a.tribute ~= nil and a.tribute ~= 'small' and a.tribute ~= 'pay' and a.tribute ~= 'refuse' then
        return reject('answer_meeting: tribute is small, pay or refuse')
    end
    if a.wishes ~= nil then
        if type(a.wishes) ~= 'table' or #a.wishes > 20 then return reject('answer_meeting: wishes is a list of up to 20') end
        for _, w in ipairs(a.wishes) do
            if type(w) ~= 'string' or not w:match('^%a+$') then return reject('answer_meeting: a wish is a category name') end
        end
    end
    -- (0.105.41, item 8) a peace proposal: peace ai | accept | refuse; attacked: civ ids;
    -- the numbers from PLANNER_CONFIG
    if a.peace ~= nil and a.peace ~= 'ai' and a.peace ~= 'accept' and a.peace ~= 'refuse' then
        return reject('answer_meeting: peace is ai, accept or refuse')
    end
    local attacked
    if a.attacked ~= nil then
        if type(a.attacked) ~= 'table' then return reject('answer_meeting: attacked is a list of civ ids') end
        attacked = {}
        for i = 1, 51 do
            local v = a.attacked[i]
            if v == nil then break end
            if i > 50 then return reject('answer_meeting: attacked is at most 50 civ ids') end
            local n = int_in(v, 0, 100000000)
            if not n then return reject('answer_meeting: attacked is a list of civ ids') end
            table.insert(attacked, n)
        end
    end
    local nums = {}
    for _, k in ipairs({'peace_min', 'peace_step', 'peace_forgive'}) do
        if a[k] ~= nil then
            nums[k] = int_in(a[k], 0, 400)
            if not nums[k] then return reject('answer_meeting: ' .. k .. ' is 0-400') end
        end
    end
    return reqscript('ai-diplomacy').answer_meeting({tribute = a.tribute, wishes = a.wishes, dry_run = a.dry_run == true,
                                                     peace = a.peace, attacked = attacked, peace_min = nums.peace_min,
                                                     peace_step = nums.peace_step,
                                                     peace_forgive = nums.peace_forgive}, txt)
end

-- (0.105.24, 13b) The messenger sent on "Make contact" to a site, by driving
-- DF's World screen as the player does (lua/ai-mission-send.lua). Only with
-- the Rules switch send_messenger on; the steps run over the next frames and
-- stop (the screen shut) at the first one that differs from what was
-- recorded; the outcome shows in the `missions` report's `send`.
-- (0.105.39) Every goal: rescue, recover_artifact, explore, raid, pillage,
-- tribute, conquer with squad_ids (and hf_id / artifact_id for the target).
-- The Rules double-checked here: make_contact + send_messenger for Make
-- contact; the `missions` choice allowing the goal + send_missions for the rest.
SEND_GOALS = {make_contact = true, rescue = true, recover_artifact = true, explore = true, raid = true,
              pillage = true, tribute = true, conquer = true}
-- (0.105.39 review) the goals that can start a war: only against a site whose
-- owner the fort's civ is hostile to or at war with (ai-missions.site_hostile)
SEND_OFFENSIVE = {raid = true, pillage = true, tribute = true, conquer = true}
SEND_MISSIONS_LABEL = 'the Army tab\'s "Missions to send out"'
SEND_BY_SCREEN_LABEL = 'the Army tab\'s "Send missions by the World screen"'

-- the Rules for a goal; the goals each `missions` level allows come from
-- ai-overseer-settings' MISSION_GOALS (the one table): settings that can't
-- load refuse every goal
function send_mission_rules(goal)
    local okm, S = pcall(function() return reqscript('ai-overseer-settings') end)
    local ok, s = pcall(function() return S.load_settings() end)
    if not okm or not ok or type(s) ~= 'table' then return false, 'the Rules could not be read' end
    if goal == 'make_contact' then
        if s.make_contact == false then return false, 'the Rules switch "Make contact" is off' end
        if s.send_messenger ~= true then return false, 'the Rules tab\'s "Send the messenger by the World screen" is off' end
        return true
    end
    local okg, levels = pcall(function() return S.MISSION_GOALS end)
    if not okg or type(levels) ~= 'table' then
        return false, 'the Rules\' mission goals (ai-overseer-settings MISSION_GOALS) could not be read'
    end
    local m = s.missions
    if m == nil then m = 'all' end      -- (r10 p3) the settings' default
    local list = levels[m]
    if type(list) ~= 'table' then return false, SEND_MISSIONS_LABEL .. ' is not known' end
    local allowed = false
    for _, g in ipairs(list) do if g == goal then allowed = true end end
    if not allowed then return false, SEND_MISSIONS_LABEL .. ' is ' .. tostring(m):sub(1, 20) .. ': ' .. goal .. ' is not allowed' end
    if s.send_missions ~= true then return false, SEND_BY_SCREEN_LABEL .. ' is off' end
    return true
end

-- (0.105.39 review) a siege on or the civilian alert up: no squad leaves
-- (read as the report reads them: plotinfo.invasions' active flag,
-- plotinfo.alerts.civ_alert_idx). Unreadable counts as on. Returns why, or nil.
function send_mission_danger()
    local oka, alert = pcall(function() return df.global.plotinfo.alerts.civ_alert_idx ~= 0 end)
    if not oka then return 'the civilian alert could not be read' end
    if alert then return 'the civilian alert is up' end
    local oki, siege = pcall(function()
        for _, v in ipairs(df.global.plotinfo.invasions.list) do
            local okf, on = pcall(function() return v.flags.active end)
            if okf and on then return true end
        end
        return false
    end)
    if not oki then return 'the sieges could not be read' end
    if siege then return 'a siege is on' end
    return nil
end

-- (0.105.47, J17) the Rules' raid_policy (ai | aggressive | reactive | off;
-- unreadable: off, (0.105.48, K9) as the default) and which reasons it allows against a civ that isn't
-- hostile: 'aggressive' (any civ but the fort's friends), 'retaliation' (a
-- civ that attacked the fort), 'threat' (a hostile or ownerless camp close by)
function send_raid_policy()
    local ok, s = pcall(function() return reqscript('ai-overseer-settings').load_settings() end)
    local v = ok and type(s) == 'table' and s.raid_policy or nil
    if v == 'ai' or v == 'aggressive' or v == 'reactive' then return v end
    return 'off'
end
SEND_POLICY_OK = {['ai aggressive'] = true, ['ai retaliation'] = true, ['ai threat'] = true,
                  ['aggressive aggressive'] = true, ['aggressive retaliation'] = true, ['aggressive threat'] = true,
                  ['reactive retaliation'] = true, ['reactive threat'] = true}

function act_send_mission(a)
    local goal = a.goal
    if goal == nil then goal = 'make_contact' end
    if type(goal) ~= 'string' or not SEND_GOALS[goal] then
        return reject('send_mission: goal is one of make_contact, rescue, recover_artifact, explore, raid, pillage, tribute, conquer')
    end
    local site = int_in(a.site_id, 0, 1000000)
    if not site then return reject('send_mission needs site_id: a site\'s id') end
    local squads
    if a.squad_ids ~= nil then
        if type(a.squad_ids) ~= 'table' then return reject('send_mission: squad_ids is a list of squad ids') end
        squads = {}
        for i = 1, 21 do
            local v = a.squad_ids[i]
            if v == nil then break end
            if i > 20 then return reject('send_mission: at most 20 squads') end
            local n = int_in(v, 0, 100000000)
            if not n then return reject('send_mission: squad_ids is a list of squad ids') end
            table.insert(squads, n)
        end
    end
    if goal ~= 'make_contact' and (not squads or #squads == 0) then
        return reject('send_mission: ' .. goal .. ' needs squad_ids')
    end
    local hf, art
    if a.hf_id ~= nil then
        hf = int_in(a.hf_id, 0, 100000000)
        if not hf then return reject('send_mission: hf_id is a historical figure\'s id') end
    end
    if a.artifact_id ~= nil then
        art = int_in(a.artifact_id, 0, 100000000)
        if not art then return reject('send_mission: artifact_id is an artifact\'s id') end
    end
    local on, why = send_mission_rules(goal)
    if not on then return reject('send_mission: ' .. why) end
    if goal ~= 'make_contact' then
        local danger = send_mission_danger()
        if danger then return reject('send_mission: no squad goes out while ' .. danger) end
    end
    local owner = nil                 -- (0.105.41, item 8) whom an offensive mission attacks
    if SEND_OFFENSIVE[goal] then
        local okh, h, hwhy = pcall(function() return reqscript('ai-missions').site_hostile(site) end)
        if not okh or type(h) ~= 'table' then
            return reject('send_mission: ' .. goal .. ' refused: who owns site ' .. site .. ' could not be read' ..
                          (okh and hwhy and (' (' .. tostring(hwhy):sub(1, 60) .. ')') or ''))
        end
        if h.ours then
            return reject('send_mission: ' .. goal .. ' refused: site ' .. site .. ' is the fort\'s own civilisation\'s')
        end
        -- (0.105.47, J17) the raid policy (brain/planner_raids.py): a raid on a
        -- civ that isn't hostile only for the reason the brain gives (policy)
        -- and only when the Rules' raid_policy allows it; 'off': no attack at all
        local rp = send_raid_policy()
        if rp == 'off' then
            return reject('send_mission: ' .. goal .. ' refused: the Army tab\'s "Raids" is off')
        end
        if h.hostile ~= true and h.at_war ~= true and not SEND_POLICY_OK[rp .. ' ' .. tostring(a.policy)] then
            return reject('send_mission: ' .. goal .. ' only against a site whose owner is hostile or at war with ' ..
                          'the fort\'s civilisation (site ' .. site .. ': ' .. tostring(h.relation):sub(1, 30) .. ')' ..
                          (a.policy and (', not for "' .. tostring(a.policy):sub(1, 20) .. '" with Raids ' .. rp) or ''))
        end
        owner = {h.civ, h.owner}
    end
    -- (0.105.41, item 8) the fort attacked them: remembered in the save, so a
    -- peace offer from them is weighed with it (lua/ai-diplomacy.lua).
    -- (r9, audit A8 #15) booked by the sender once the run is 'sent', not
    -- here: start() answers ok at once, and a run that stopped at its first
    -- step still refused their peace for good
    local r = reqscript('ai-mission-send').start({goal = goal, site_id = site, squad_ids = squads, hf_id = hf,
                                                  artifact_id = art, dry_run = a.dry_run == true,
                                                  attacks = owner and {owner[1], owner[2]} or nil})
    return r
end

function act_close_trade(a)
    if a.dry_run then return {ok = true, dry_run = true} end
    if not reqscript('ai-trade').opened_by_ai() and a.force ~= true then
        return reject('the player opened this trade screen: left open')
    end
    return reqscript('ai-trade').close_screen(a.unloading == true)
end

-- Someone to the depot for a caravan: the broker asked for, anyone after
-- `wait_ticks` (lua/ai-trade.lua).
function act_call_trader(a)
    local wait = int_in(a.wait_ticks or 1200, 0, 403200)
    if not wait then return reject('call_trader wait_ticks must be 0-403200') end
    return reqscript('ai-trade').call_trader(abs_tick(), wait,
                                             a.dry_run == true, txt)
end

-- A noble given a free room of the kind its office asks for (lua/ai-nobles.lua).
function act_give_room(a)
    local id = whole_number(a.unit_id)
    if not id or type(a.kind) ~= 'string' then return reject('give_room needs unit_id and kind') end
    return reqscript('ai-nobles').give_room(id, a.kind, a.dry_run == true, txt)
end

function act_squad_release(a)
    local id = whole_number(a.unit_id)
    if not id then return reject('squad_release needs unit_id') end
    return reqscript('ai-military').release(id, a.dry_run == true, txt, a.mother == true, a.tantrum == true)   -- (0.105.99) tantrum
end

-- (0.104.65) A swap: a soldier trained enough goes back to work and the
-- place goes at once to the keenest outside (the fill puts those longing to
-- train first); a release alone left the squads short (34 soldiers, 31 wanted
-- after the release, so no fill came).
function act_squad_swap(a)
    local id = whole_number(a.unit_id)
    if not id then return reject('squad_swap needs unit_id') end
    local u = df.unit.find(id)
    local sid = u and u.military.squad_id or -1
    if sid == -1 then return reject('not in a squad') end
    local M = reqscript('ai-military')
    local r = M.release(id, a.dry_run == true, txt)
    if not r.ok or a.dry_run then return r end
    -- (0.104.138) never the one just sent home, nor those sent home lately
    local avoid = {[id] = true}
    for _, v in ipairs(type(a.avoid) == 'table' and a.avoid or {}) do
        local n = whole_number(v)
        if n then avoid[n] = true end
    end
    local okf, f = pcall(M.fill, sid, 1, txt, avoid, a.strict == true)   -- (0.104.168) strict in a crisis
    return {ok = true, released = r.name, squad_id = sid, filled = okf and f or tostring(f)}
end

function act_squad_trim(a)
    local n = int_in(a.count, 1, 5)
    if not n then return reject('squad_trim needs count 1-5') end
    return reqscript('ai-military').trim(n, a.dry_run == true, txt)
end

function act_squad_fill(a)
    local id, n = whole_number(a.squad_id), int_in(a.count, 1, 10)
    if not id or not n then return reject('squad_fill needs squad_id and count 1-10') end
    local avoid = {}                                  -- (0.104.138) those sent home lately
    for _, v in ipairs(type(a.avoid) == 'table' and a.avoid or {}) do
        local u = whole_number(v)
        if u then avoid[u] = true end
    end
    return reqscript('ai-military').fill(id, n, txt, avoid, a.strict == true, a.keen_only == true)   -- (0.104.168)
end

-- A squad given a barracks to train in (lua/ai-military.lua).
function act_squad_barracks(a)
    local sid, zid = whole_number(a.squad_id), whole_number(a.zone_id)
    if not sid or not zid then return reject('squad_barracks needs squad_id and zone_id') end
    return reqscript('ai-military').assign_barracks(sid, zid, a.dry_run == true)
end

-- (0.87) DF's standing orders that answer residency and citizenship
-- petitions: each 0 (ask) or 1 (accept); refused unless every one reads 0
-- or 1 now (anything else would mean the game uses these values otherwise)
function act_petition_orders(a)
    if type(a.orders) ~= 'table' then return reject('petition_orders needs orders {kind = 0|1}') end
    local via, why = petition_orders_bind()     -- (r10 p1) Windows: DF's own names for them
    local cur, set = {}, {}
    for _, k in ipairs(PETITION_ORDERS) do
        local okv, v = pcall(function() return df.global[petition_order_name(k)] end)
        if not okv or (v ~= 0 and v ~= 1) then
            return {ok = false, rejected = true, error = 'standing order ' .. k .. ' reads ' .. tostring(v) .. ', not 0 or 1: left alone'
                    .. (not okv and why and (' (' .. why .. ')') or '')}
        end
        cur[k] = v
    end
    for k, v in pairs(a.orders) do
        if cur[k] == nil or (v ~= 0 and v ~= 1) then return reject('petition_orders: unknown ' .. tostring(k) .. '=' .. tostring(v)) end
        if cur[k] ~= v then set[k] = v end
    end
    if a.dry_run then return {ok = true, dry_run = true, would_set = set, now = cur, via = via} end
    local busy = next(set) and petitions_screen_busy()     -- (r10 p1) never under the player's eyes
    if busy then return {ok = false, waiting = true, error = busy .. ': the orders are set later'} end
    for k, v in pairs(set) do df.global[petition_order_name(k)] = v end
    for k, v in pairs(set) do
        if df.global[petition_order_name(k)] ~= v then return {ok = false, error = 'the game did not keep ' .. k} end
    end
    return {ok = true, set = next(set) and set or nil, was = cur, via = via}
end

-- A squad given one of the fort's uniform templates (lua/ai-military.lua).
function act_set_uniform(a)
    local id = whole_number(a.squad_id)
    if not id or (a.kind ~= 'leather' and a.kind ~= 'metal') then
        return reject('set_uniform needs squad_id and kind leather or metal')
    end
    return reqscript('ai-military').set_uniform(id, a.kind, a.dry_run == true, txt, a.ranged == true)
end

-- (0.82) mark the uniform of a squad the AI made (copied before 0.82) as the AI's
function act_adopt_uniform(a)
    local id = whole_number(a.squad_id)
    if not id then return reject('adopt_uniform needs squad_id') end
    return reqscript('ai-military').adopt_uniform(id, a.dry_run == true, txt)
end

-- Let the masons and crafters use one kind of economic stone (DF's stone
-- settings): never an ore.
function act_allow_stone(a)
    if type(a.stone) ~= 'string' or not a.stone:match('^[%u%d_]+$') then return reject('allow_stone needs stone (a token)') end
    local economic = df.global.plotinfo.economic_stone
    local raws = df.global.world.raws.inorganics.all or df.global.world.raws.inorganics
    for idx, inorg in ipairs(raws) do
        if inorg.id == a.stone then
            if a.keep == true then
                -- back to "economic": kept from ordinary jobs (coal for coke)
                if idx < #economic and economic[idx] and economic[idx] ~= 0 then
                    return {ok = false, rejected = true, error = a.stone .. ' is kept already'}
                end
                if a.dry_run == true then return {ok = true, dry_run = true, stone = a.stone, keep = true} end
                local ok = pcall(function() economic[idx] = true end)
                if not ok then pcall(function() economic[idx] = 1 end) end
                return {ok = true, stone = a.stone, keep = true}
            end
            -- (0.104.124) an ore only when the brain asks for it by name with ore = true
            -- (Teacheroar: 13 ghosts and 38 dead with no stone for slabs or coffins, 197 iron-ore boulders)
            if #inorg.metal_ore.mat_index > 0 and a.ore ~= true then return reject(a.stone .. ' is an ore: kept for the smelter') end
            if FUEL_STONES[a.stone] then return reject(a.stone .. ' is coal: kept for coke') end
            if not (idx < #economic and economic[idx] and economic[idx] ~= 0) then
                return {ok = false, rejected = true, error = a.stone .. ' may already be used'}
            end
            if a.dry_run == true then return {ok = true, dry_run = true, stone = a.stone} end
            local ok = pcall(function() economic[idx] = false end)
            if not ok then pcall(function() economic[idx] = 0 end) end
            local now_econ = economic[idx] and economic[idx] ~= 0
            if now_econ then return {ok = false, error = 'the game kept ' .. a.stone .. ' economic'} end
            return {ok = true, stone = a.stone}
        end
    end
    return reject('no such stone: ' .. a.stone)
end

-- A small chamber dug in ordinary stone, for boulders (lua/ai-industry.lua).
function act_quarry(a)
    local n = int_in(a.count or 30, 1, 30)
    if not n then return reject('quarry needs count 1-30') end
    return reqscript('ai-industry').quarry(n, a.dry_run == true)
end

-- A squad's uniform weapon made one kind (lua/ai-military.lua).
function act_set_uniform_weapon(a)
    local id = whole_number(a.squad_id)
    if not id or type(a.weapon) ~= 'string' or not a.weapon:match('^ITEM_WEAPON_[%u_]+$') then
        return reject('set_uniform_weapon needs squad_id and weapon (ITEM_WEAPON_...)')
    end
    return reqscript('ai-military').set_uniform_weapon(id, a.weapon, a.dry_run == true)
end

-- (0.105.97) a squad back on duty or given an order: its soldiers on leave in
-- the recreation burrow let out at once (not at the burrow's next tick, a
-- week off), so the burrow and the duty don't pull on them both
local function squad_rec_release(id, r)
    local okl, out = pcall(function() return reqscript('ai-society').recreation_release_squad(id, txt) end)
    if okl and type(out) == 'table' and #out > 0 and type(r) == 'table' then r.recreation_released = out end
end

function act_squad_routine(a)
    local id = whole_number(a.squad_id)
    if not id or type(a.routine) ~= 'string' then return reject('squad_routine needs squad_id and routine') end
    local r = reqscript('ai-military').set_routine(id, a.routine)
    -- (0.105.97) back on duty: its soldiers in the recreation burrow let out now
    if r and r.ok and not a.routine:lower():find('off duty', 1, true) then squad_rec_release(id, r) end
    return r
end

function act_squad_orders(a)
    local id = whole_number(a.squad_id)
    if not id then return reject('squad_orders needs squad_id') end
    if a.clear == true then return reqscript('ai-military').orders(id, nil, true) end
    if type(a.kill) ~= 'table' or #a.kill == 0 or #a.kill > 50 then
        return reject('squad_orders needs kill: a list of 1-50 unit ids, or clear: true')
    end
    local ids = {}
    for _, v in ipairs(a.kill) do
        local n = whole_number(v)
        if not n then return reject('kill must list unit ids') end
        table.insert(ids, n)
    end
    local r = reqscript('ai-military').orders(id, ids, false)
    -- (0.105.97, verifier) a kill order lets its soldiers on leave out of the recreation burrow too
    if type(r) == 'table' and r.ok then squad_rec_release(id, r) end
    return r
end

function act_pull_gate(a)
    local id = whole_number(a.lever_id)
    if not id then return reject('pull_gate needs lever_id') end
    return reqscript('ai-military').pull_gate(id)
end

-- (0.105.4) apply_preset: a named preset (built-in or saved) applied to the
-- fort's settings exactly as the window's Load preset does (traits, Extreme,
-- the Rules it carries; ai-overseer-settings apply_preset), saved with its
-- name in the fort's site data. For keeper.py --preset: six runs from one
-- embark, one preset each. A dry run saves nothing. An unknown name is
-- refused, naming the known ones. Allowed while halted (DISPLAY_ONLY): it
-- changes the player's settings, as the window may, not the fort.
function act_apply_preset(a)
    if type(a.name) ~= 'string' or a.name == '' then return reject('apply_preset needs a preset name') end
    local S = reqscript('ai-overseer-settings')
    local before = S.current_preset()
    local merged, rules = S.apply_preset(a.name, nil, 'keeper', a.dry_run == true)
    if not merged then return reject(rules) end
    local ai = S.for_ai(merged)
    ai.preset = a.dry_run == true and before or a.name
    return {ok = true, preset = a.name, previous = before, dry_run = a.dry_run == true or nil,
            traits = ai.traits, extreme = ai.extreme, rules = rules, settings = ai}
end

-- (0.105.20) The Rules tab's on/off switches set from outside the window
-- (logs/rules-request.json, read by the overseer): only keys whose default is
-- true or false, each to true or false. Returns what changed.
function act_set_rules(a)
    if type(a.rules) ~= 'table' then return reject('set_rules needs rules: {name = true|false}') end
    local S = reqscript('ai-overseer-settings')
    local defs = S.defaults()
    local cur = S.load_settings()
    local changed, unknown = {}, {}
    -- (0.105.27) a cycle named in RULE_CHOICES (disposal) takes one of its choices
    local function choice_ok(k, v)
        local choices = type(k) == 'string' and type(S.RULE_CHOICES) == 'table' and S.RULE_CHOICES[k]
        if type(choices) ~= 'table' or type(v) ~= 'string' then return false end
        for _, c in ipairs(choices) do if c == v then return true end end
        return false
    end
    for k, v in pairs(a.rules) do
        -- (v35 fix) open_caverns is three-state: a request's true is always.
        -- (0.105.36, D7) a request's false is the player's explicit off: never
        -- (only a stored setting's false, the old default, means the AI decides)
        if k == 'open_caverns' and type(v) == 'boolean' then v = v and 'always' or 'never' end
        if not choice_ok(k, v) and (type(k) ~= 'string' or type(defs[k]) ~= 'boolean' or type(v) ~= 'boolean') then
            table.insert(unknown, tostring(k))
        elseif cur[k] ~= v then
            changed[k] = {old = cur[k], new = v}
            cur[k] = v
        end
    end
    if #unknown > 0 then
        table.sort(unknown)
        -- (0.105.39) the choices named from RULE_CHOICES (disposal, missions, ...)
        local cycles = {}
        for c in pairs(type(S.RULE_CHOICES) == 'table' and S.RULE_CHOICES or {}) do table.insert(cycles, c) end
        table.sort(cycles)
        return reject('set_rules: not an on/off switch (or a choice of ' .. table.concat(cycles, ', ')
                      .. ') of the Rules tab: ' .. table.concat(unknown, ', '))
    end
    if next(changed) and a.dry_run ~= true then S.save_settings(cur) end
    return {ok = true, changed = changed, dry_run = a.dry_run == true or nil}
end

---------------------------------------------------------------------------
-- (0.105.27) Disposal (lua/ai-disposal.lua): the forbidden things lying
-- about let go, melted, dumped, or (the dump's) removed; DF's standing
-- orders on refuse; a dump zone placed. Every item action leaves alone what
-- lies near danger, everything during a siege, the sealed caverns, the
-- cistern's tiles, artifacts, a living dwarf's things and (without
-- player_items) what no game reason explains.
---------------------------------------------------------------------------

-- (0.105.27 fixes) 'dumped' is no reason to unforbid: what the dump holds
-- would be stored, marked and dumped again for ever
local DISPOSAL_REASONS = {own_dead = true, used_ammo = true, other_dead = true, unknown = true}
-- a call's max at most: the same 500 as ai-disposal's MAX_CAP and the brain's
-- planner_config DISPOSAL_ACTION_MAX (a test checks the three agree)
local DISPOSAL_MAX = 500
local DUMP_REASONS = {own_dead = true, used_ammo = true, other_dead = true, free = true, unknown = true}

-- opts for the item actions: reasons (a list from `allowed`), max (1..DISPOSAL_MAX),
-- player_items (bool); or nil, error
local function disposal_opts(a, allowed, name)
    local o = {}
    if a.reasons ~= nil then
        o.reasons = string_list(a.reasons, allowed, 10)
        if not o.reasons then
            return nil, ('%s: reasons is a list of %s'):format(name, table.concat(sorted_keys(allowed), ', '))
        end
    end
    if a.max ~= nil then
        o.max = int_in(a.max, 1, DISPOSAL_MAX)
        if not o.max then return nil, ('%s: max is 1-%d'):format(name, DISPOSAL_MAX) end
    end
    for _, k in ipairs({'player_items', 'keep_masterwork', 'keep_enemy_gear', 'bodies', 'junk', 'near'}) do   -- (0.105.51) bodies, junk: mark_dump's; (item8) near: mark_dump's and empty_dump's
        if a[k] ~= nil and type(a[k]) ~= 'boolean' then return nil, ('%s: %s is true or false'):format(name, k) end
        o[k] = a[k]
    end
    return o
end

function act_unforbid_items(a)
    local o, err = disposal_opts(a, DISPOSAL_REASONS, 'unforbid_items')
    if not o then return reject(err) end
    return reqscript('ai-disposal').unforbid_items(o, a.dry_run == true)
end

-- The marks set (on the game's melt list). (0.105.48, A2-4) The smelter's
-- "melt a metal object" order is the planner's (disposal_melt_order, through
-- its order check and stuck hold): DF 50 makes no melt job by itself (DF
-- wiki, Melt: "the job order will still need to be made at a smelter"), and
-- an order placed here went past both.
function act_mark_melt(a)
    local o, err = disposal_opts(a, {}, 'mark_melt')
    if not o then return reject(err) end
    return reqscript('ai-disposal').mark_melt(o, a.dry_run == true)
end

function act_mark_dump(a)
    local o, err = disposal_opts(a, DUMP_REASONS, 'mark_dump')
    if not o then return reject(err) end
    return reqscript('ai-disposal').mark_dump(o, a.dry_run == true)
end

function act_empty_dump(a)
    local o, err = disposal_opts(a, {}, 'empty_dump')
    if not o then return reject(err) end
    return reqscript('ai-disposal').empty_dump(o, a.dry_run == true)
end

function act_set_standing_orders(a)
    if type(a.orders) ~= 'table' then return reject('set_standing_orders needs orders {name = 0|1}') end
    return reqscript('ai-disposal').set_standing_orders(a.orders, a.dry_run == true)
end

-- A garbage dump zone: on the surface, or (inside = true) in a dug room near
-- the entrance. The builder places it (ai-builder-dump place_dump_zone, (r9)
-- group settings'); refused while the fort has one of that kind already.
-- place_dump_zone(inside, dry_run) is expected to return a table as
-- place_surface does: {ok = true, kind = 'dump', x, y, z or elevation,
-- inside, dry_run} or {ok = false, rejected?, waiting?, error}.
-- (item8) move = true (outside only): the outside dump whose edge is a
-- ramp's (ai-disposal ramp_edge > 0; DF leaves what it dumps on the ramp)
-- replaced by a flat one, the old zone removed once the new one stands.
function act_place_dump(a)
    if a.inside ~= nil and type(a.inside) ~= 'boolean' then return reject('place_dump: inside is true or false') end
    if a.move ~= nil and type(a.move) ~= 'boolean' then return reject('place_dump: move is true or false') end
    local inside = a.inside == true
    if a.move and inside then return reject('place_dump: move is for the dump outside') end
    local okz, zones = pcall(function() return reqscript('ai-disposal').dump_zones() end)
    local move_from
    if okz then
        for _, zn in ipairs(zones) do
            local oke, edge = pcall(function() return reqscript('ai-disposal').ramp_edge(zn) end)
            if a.move and not move_from and zn.inside == false and oke and edge > 0 then
                move_from = zn.id
            elseif zn.inside == inside then
                return {ok = false, rejected = true, nothing_to_do = true, stale = {'disposal'}, zone_id = zn.id,
                        error = ('the fort has a garbage dump %s already (zone %d at x%d y%d)')
                            :format(inside and 'inside' or 'outside', zn.id, zn.x, zn.y)}
            end
        end
    end
    local okb, B = pcall(reqscript, 'ai-builder')
    if not okb or type(B) ~= 'table' or type(B.place_dump_zone) ~= 'function' then
        return {ok = false, error = 'the builder has no place_dump_zone (ai-builder-dump.lua is older than this bridge)'}
    end
    if a.move and not move_from then
        return {ok = false, rejected = true, nothing_to_do = true, stale = {'disposal'},
                error = 'place_dump: no dump outside has a ramp at its edge (nothing to move)'}
    end
    local ok, r = pcall(B.place_dump_zone, inside, a.dry_run == true, move_from and {move_from = move_from} or nil)
    if not ok then return {ok = false, error = 'place_dump_zone failed: ' .. tostring(r):sub(1, 300)} end
    if type(r) ~= 'table' then return {ok = false, error = 'place_dump_zone returned ' .. type(r) .. ', not a table'} end
    if r.ok == nil then r.ok = false end
    r.inside = inside
    return r
end

---------------------------------------------------------------------------
-- (0.105.40, 13e) World cleanup (lua/ai-cleanup.lua): what no dwarf can
-- clean up, taken off the map only past the brain's thresholds. Each takes
-- dry_run (counts, changes nothing).
---------------------------------------------------------------------------

-- (0.105.40 review) the Rules' World cleanup: 'off', 'safe' or 'full' (nil:
-- the settings can't be read). Every cleanup action is refused at off (or
-- unread); cleanup_units, and cleanup_items at level full, need full.
local function cleanup_setting()
    local ok, s = pcall(function() return reqscript('ai-overseer-settings').load_settings() end)
    if ok and type(s) == 'table' and (s.world_cleanup == 'off' or s.world_cleanup == 'safe'
                                      or s.world_cleanup == 'full') then
        return s.world_cleanup
    end
    return nil
end

local function cleanup_off(name, setting)
    if setting == 'off' or setting == nil then
        return reject(name .. ': the Rules\' World cleanup is ' .. tostring(setting or 'unreadable'))
    end
    return nil
end

local function cleanup_num(a, key, lo, hi, name)
    if a[key] == nil then return true, nil end
    local n = int_in(a[key], lo, hi)
    if not n then return false, ('%s: %s is %d-%d'):format(name, key, lo, hi) end
    return true, n
end

-- unreachable items, unreachable for a year (min_age), oldest first: max a
-- call. level: 'safe' (the default: only the low-value kinds) or 'full' (any
-- kind; only while the Rules' World cleanup is at full: else read as safe)
function act_cleanup_items(a)
    local o = {}
    for _, k in ipairs({{'max', 1, 500}, {'min_age', 100800, 40320000}, {'min_count', 0, 10000000}}) do
        local ok, v = cleanup_num(a, k[1], k[2], k[3], 'cleanup_items')
        if not ok then return reject(v) end
        o[k[1]] = v
    end
    if a.level ~= nil and a.level ~= 'safe' and a.level ~= 'full' then
        return reject('cleanup_items: level is safe or full')
    end
    local setting = cleanup_setting()
    local off = cleanup_off('cleanup_items', setting)
    if off then return off end
    o.level = a.level or 'safe'
    if o.level == 'full' and setting ~= 'full' then o.level = 'safe' end
    return reqscript('ai-cleanup').cleanup_items(o, a.dry_run == true)
end

-- unreachable hostile or wild creatures that are no historical figure, a season unreachable
function act_cleanup_units(a)
    local o = {}
    for _, k in ipairs({{'max', 1, 100}, {'min_age', 100800, 40320000}}) do
        local ok, v = cleanup_num(a, k[1], k[2], k[3], 'cleanup_units')
        if not ok then return reject(v) end
        o[k[1]] = v
    end
    if a.kinds ~= nil then
        o.kinds = string_list(a.kinds, {hostile = true, wild = true}, 2)
        if not o.kinds then return reject('cleanup_units: kinds is a list of hostile, wild') end
    end
    local setting = cleanup_setting()
    if setting ~= 'full' then
        return reject('cleanup_units: only while the Rules\' World cleanup is full (it is '
                      .. tostring(setting or 'unreadable') .. ')')
    end
    return reqscript('ai-cleanup').cleanup_units(o, a.dry_run == true)
end

-- the spatter on the map's blocks (scope outside the fort's areas, or all), budget_ms a call
function act_cleanup_spatter(a)
    if a.scope ~= nil and a.scope ~= 'outside' and a.scope ~= 'all' then
        return reject('cleanup_spatter: scope is outside or all')
    end
    local ok, b = cleanup_num(a, 'budget_ms', 10, 500, 'cleanup_spatter')
    if not ok then return reject(b) end
    local off = cleanup_off('cleanup_spatter', cleanup_setting())
    if off then return off end
    return reqscript('ai-cleanup').cleanup_spatter({scope = a.scope, budget_ms = b}, a.dry_run == true)
end

-- long-dead units nobody refers to, off the game's active list (as fix/dead-units)
function act_cleanup_dead_units(a)
    local o = {}
    for _, k in ipairs({{'max', 1, 2000}, {'min_age', 100800, 40320000}}) do
        local ok, v = cleanup_num(a, k[1], k[2], k[3], 'cleanup_dead_units')
        if not ok then return reject(v) end
        o[k[1]] = v
    end
    local off = cleanup_off('cleanup_dead_units', cleanup_setting())
    if off then return off end
    return reqscript('ai-cleanup').cleanup_dead_units(o, a.dry_run == true)
end

-- (0.105.40 M5) hauling balanced (lua/ai-hauling.lua): idle civilians who
-- don't haul put on the AI's own hauling detail; key specialists taken off
-- hauling (back = true: given it back). Never the player's details.
function act_add_haulers(a)
    local n = int_in(a.count, 1, 10)
    if not n then return reject('add_haulers needs count 1-10') end
    return reqscript('ai-hauling').add_haulers(n, a.dry_run == true, txt)
end

function act_relieve_haulers(a)
    -- (0.105.119 item33) cooks: the best free cooks (ids) kept at the kitchen,
    -- off hauling and with the cooking labour; with back, every one given back
    if a.cooks ~= nil then
        local ids = {}
        for _, v in ipairs(type(a.cooks) == 'table' and a.cooks or {}) do
            local id = whole_number(v)
            if id then table.insert(ids, id) end
        end
        if #ids > 5 then return reject('relieve_haulers: at most 5 cooks') end
        if #ids == 0 and a.back ~= true then return reject('relieve_haulers: cooks needs unit ids (or back)') end
        return reqscript('ai-hauling').relieve_cooks(ids, a.back == true, a.dry_run == true, txt)
    end
    local n = int_in(a.count, 1, 5)
    if not n then return reject('relieve_haulers needs count 1-5') end
    -- (0.105.40b fix) shrink: the AI's own detail's extra haulers taken off it
    if a.back == true and a.shrink == true then return reject('relieve_haulers: back or shrink, not both') end
    return reqscript('ai-hauling').relieve_haulers(n, a.back == true, a.dry_run == true, txt, a.shrink == true)
end

-- (0.105.40b, M6) The food store (lua/ai-food-store.lua): a food pile near a
-- kitchen or still, about `tiles` tiles, taking `barrels` barrels (more: the
-- near ones are full); an AI food pile's max barrels (never the player's).
function act_food_pile(a)
    local id = whole_number(a.building_id)
    if not id then return reject('food_pile needs building_id (a kitchen or still)') end
    local o = {building_id = id, more = a.more == true}
    for _, k in ipairs({{'tiles', 4, 64}, {'barrels', 0, 100}, {'reach', 4, 30}}) do
        if a[k[1]] ~= nil then
            local n = int_in(a[k[1]], k[2], k[3])
            if not n then return reject(('food_pile: %s is %d-%d'):format(k[1], k[2], k[3])) end
            o[k[1]] = n
        end
    end
    return reqscript('ai-food-store').food_pile(o, a.dry_run == true)
end

function act_food_barrels(a)
    local id = whole_number(a.pile_id)
    if not id then return reject('food_barrels needs pile_id') end
    local n = int_in(a.barrels, 0, 100)
    if not n then return reject('food_barrels: barrels is 0-100') end
    return reqscript('ai-food-store').food_barrels({pile_id = id, barrels = n}, a.dry_run == true)
end

-- (0.105.41, item 2) Wheelbarrows and feeder links (lua/ai-pile-links.lua):
-- an AI stone pile's max wheelbarrows; an AI feeder pile linked to its
-- workshop (links_only: fed from the AI's bigger pile of its kind, taking
-- from links only), or unlinked. Never the player's piles or workshops.
function act_pile_barrows(a)
    local id = whole_number(a.pile_id)
    if not id then return reject('pile_barrows needs pile_id') end
    local n = int_in(a.barrows, 0, 10)
    if not n then return reject('pile_barrows: barrows is 0-10') end
    return reqscript('ai-pile-links').set_barrows({pile_id = id, barrows = n}, a.dry_run == true)
end

function act_feeder_link(a)
    local id = whole_number(a.pile_id)
    if not id then return reject('feeder_link needs pile_id (an AI feeder pile)') end
    if a.unlink == true and a.links_only == true then return reject('feeder_link: unlink or links_only, not both') end
    return reqscript('ai-pile-links').link_feeder({pile_id = id, unlink = a.unlink == true,
                                                   links_only = a.links_only == true}, a.dry_run == true)
end

-- (0.105.41, item 4) Provisions from the land (lua/ai-provisions.lua):
-- hunters (count more, or the AI's own off the hunt: stop), DF's standing
-- orders on butchering, tanning and cooking, a fruit-gathering zone over the
-- fruit trees near the fort, farm plots on a cavern's soil near `at`.
function act_hunters(a)
    if a.stop == true then return reqscript('ai-provisions').hunters({stop = true}, a.dry_run == true, txt) end
    local n = int_in(a.count, 1, 5)
    if not n then return reject('hunters needs count 1-5 (or stop = true)') end
    return reqscript('ai-provisions').hunters({count = n}, a.dry_run == true, txt)
end

function act_food_standing(a)
    if type(a.orders) ~= 'table' then return reject('food_standing needs orders {name = 0|1}') end
    return reqscript('ai-provisions').food_standing({orders = a.orders}, a.dry_run == true)
end

function act_fruit_zone(a)
    -- (item6) pause = true / false: the AI's fruit zones paused (food to spare) or set going again
    if a.pause ~= nil then
        if type(a.pause) ~= 'boolean' then return reject('fruit_zone: pause is true or false') end
        return reqscript('ai-provisions').fruit_pause(a.pause, a.dry_run == true)
    end
    local o = {}
    if a.min_trees ~= nil then
        o.min_trees = int_in(a.min_trees, 1, 50)
        if not o.min_trees then return reject('fruit_zone: min_trees is 1-50') end
    end
    return reqscript('ai-provisions').fruit_zone(o, a.dry_run == true)
end

function act_cavern_farm(a)
    local at = type(a.at) == 'table' and a.at or nil
    local x, y, z = at and whole_number(at.x), at and whole_number(at.y), at and whole_number(at.z)
    if not (x and y and z) then return reject('cavern_farm needs at {x, y, z} (a cavern tile)') end
    local n = int_in(a.tiles, 4, 60)
    if not n then return reject('cavern_farm needs tiles 4-60') end
    return reqscript('ai-provisions').cavern_farm({at = {x = x, y = y, z = z}, tiles = n}, a.dry_run == true)
end

-- (item 12) The fort's artifacts shown: display furniture built in the AI's
-- own rooms, an artifact of the AI's put on display (lua/ai-artifacts.lua)
function act_place_display(a)
    local id = whole_number(a.zone_id)
    if not id then return reject('place_display needs zone_id (a location\'s or hall\'s zone)') end
    if a.kind ~= nil and a.kind ~= 'pedestal' and a.kind ~= 'case' then
        return reject('place_display: kind is pedestal or case')
    end
    return reqscript('ai-artifacts').place_display({zone_id = id, kind = a.kind or 'pedestal'}, a.dry_run == true)
end

function act_display_artifact(a)
    local item, bld = whole_number(a.item_id), whole_number(a.building_id)
    if not item or not bld then return reject('display_artifact needs item_id and building_id') end
    return reqscript('ai-artifacts').display_artifact({item_id = item, building_id = bld}, a.dry_run == true)
end
