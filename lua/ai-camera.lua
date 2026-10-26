-- (0.104.88, Phase 13d; 0.104.90 the second round) The camera director: the
-- game's view moves from place to place when something worth seeing happens,
-- so a player watching an unattended fort sees it without hunting for it.
--
-- What it shows, most important first: a fight (a danger near citizens), a
-- forgotten beast or invaders, a death, arrivals (a caravan, migrants, a
-- birth), a strange mood and the artifact it makes, a tantrum, a wedding, a
-- new noble, a legendary dwarf, the AI's new and finished levels, small
-- scenes (a performance, worship, a lesson, children at play, sparring);
-- with nothing new, a tour that favours the busy places: the AI's open digs,
-- the halls and pens, the busiest workshop of each kind, the farms, the gate.
-- (0.104.90) It follows a unit it shows (the mood dwarf, the caravan, the
-- migrants, the beast), puts a caption on screen, keeps a list of what it
-- showed (the Camera tab), spaces out repeats of a kind, and takes two keys:
-- Ctrl-Shift-N the next thing, Ctrl-Shift-L stay here (again to let go).
-- The keeper adds what only it knows: the plan's district names and the
-- reasons for its newest work.
--
-- It never moves while the player uses the game: the game paused, a menu
-- open, a unit or building selected, or the view moved by hand since the
-- camera last set it (then it waits a minute). It runs on its own timer
-- while an unattended keeper has checked in during the last five minutes
-- (ai-status), as the Camera rule says (on / tour only / off), at the pace
-- the Camera pace rule says (slow / normal / fast).
--@ module = true

local eventful = require('plugins.eventful')

CHECK_FRAMES = 60              -- the timer: about every second or two
HOLD_S = 60                    -- the player used the game: hands off this long
KEEPER_STALE_S = 300           -- no unattended keeper this long: the camera stops
DWELL = {fight = 45, event = 25, scene = 20, tour = 20, over = 0}
DWELL_CAT = {mood = 40, caravan = 40, beast = 40, migrants = 30, tantrum = 30, artifact = 25}
PACE = {slow = 1.6, normal = 1.0, fast = 0.6}
FIGHT_RANGE = 15               -- a danger this near a citizen (and 2 levels) is a fight
FOLLOW_STEP = 8                -- a followed unit this far from the centre: the view moves
TOUR_REBUILD_S = 120
QUEUE_MAX = 20
EVENT_TTL_S = 180
CAT_GAP_S = 120                -- (0.104.90) the same kind again this soon waits (prio < 90)
SCENE_GAP_S = 300              -- a scene of the same kind at most every 5 minutes
CAPTION_S = 8                  -- the caption on screen this long after a move
HISTORY_MAX = 20
SCENE_POLL_S = 10
SLOW_POLL_S = 60               -- legendary skills and nobles
MERGE = {death = 'deaths', migrants = 'migrants', birth = 'births'}
KEYS = {skip = 'Ctrl-Shift-N', stay = 'Ctrl-Shift-L'}
KEY = 'ai-camera'

local MOODS = {Fey = true, Secretive = true, Possessed = true, Macabre = true, Fell = true}
local BAD_MOODS = {Melancholy = 'has fallen into melancholy', Raving = 'has gone stark raving mad',
                   Traumatized = 'is traumatized'}
local TOUR_ZONES = {MeetingHall = 'a meeting hall', DiningHall = 'the dining hall', Hospital = 'the hospital',
                    Pen = 'a pasture', Barracks = 'the barracks', ArcheryRange = 'the archery range',
                    Dungeon = 'the jail', Temple = 'a temple', Tavern = 'the tavern', Library = 'the library'}
-- (0.104.90) activity events worth a look, by df.activity_event_type
SCENES = {Performance = 'A performance', Worship = 'Dwarves at worship', Sparring = 'Sparring',
          SkillDemonstration = 'A demonstration of skill', TeachTopic = 'A lesson',
          DiscussTopic = 'Scholars in discussion', Play = 'Children at play', MakeBelieve = 'Children at play',
          PlayWithToy = 'A child with a toy', Reunion = 'A reunion'}
local MONTHS = {'Granite', 'Slate', 'Felsite', 'Hematite', 'Malachite', 'Galena', 'Limestone', 'Sandstone',
                'Timber', 'Moonstone', 'Opal', 'Obsidian'}

local function fresh()
    return {mode = 'off', pace = 1.0, timer = nil, queue = {}, cur = nil, since = 0, set = nil, hold_until = 0,
            tour = {}, tour_built = 0, recent = {}, seen_mood = {}, shown = 0, hooked = false,
            history = {}, last_cat = {}, last_seen = {}, caption = nil, pinned = false, skip = false,
            scene_at = 0, slow_at = 0, art_n = nil, proj = nil, spouse = nil, legend = nil, nobles = nil,
            bad = {}, seen_act = {}, brain = {districts = {}, news = {}}}
end
CAM = CAM or fresh()
-- (0.104.90) a reload keeps the running camera's state: add what's new to it
for k, v in pairs(fresh()) do if CAM[k] == nil then CAM[k] = v end end

dfhack.onStateChange[KEY] = function(sc)
    if sc == SC_MAP_UNLOADED then
        if CAM.timer then pcall(dfhack.timeout_active, CAM.timer, nil) end
        local brain = CAM.brain
        CAM = fresh()
        CAM.brain = brain
    end
end

local function now() return os.time() end

local function name_of(u)
    local ok, n = pcall(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end)
    return ok and n or 'a dwarf'
end

-- (0.104.91) the name alone: the readable name ends ", <profession>", which
-- doubled up in "X, militia captain is the new militia captain"
local function short_name(u)
    local full = name_of(u)
    local okP, prof = pcall(function() return dfhack.df2utf(dfhack.units.getProfessionName(u)) end)
    if okP and prof and prof ~= '' then
        local tail = ', ' .. prof
        if full:sub(-#tail):lower() == tail:lower() then return full:sub(1, #full - #tail) end
    end
    return (full:gsub(', [^,"]+$', ''))
end

local function pos_of(u)
    local x, y, z = dfhack.units.getPosition(u)
    if x then return {x = x, y = y, z = z} end
end

function game_date()
    local ok, s = pcall(function()
        local d = df.global.cur_year_tick // 1200
        return ('%d %s y%d'):format(d % 28 + 1, MONTHS[d // 28 % 12 + 1], df.global.cur_year)
    end)
    return ok and s or ''
end

-- The Camera rule (on / tour / off), and whether an unattended keeper is about.
function wanted_mode()
    local okS, S = pcall(reqscript, 'ai-overseer-settings')
    local mode, pace = 'on', 'normal'
    if okS and S and S.load_settings then
        local ok, s = pcall(S.load_settings)
        if ok and s and s.camera then mode = s.camera end
        if ok and s and PACE[s.camera_pace] then pace = s.camera_pace end
    end
    CAM.pace = PACE[pace] or 1.0
    local okT, st = pcall(reqscript, 'ai-status')
    local keeper = okT and st and st.LAST_SEEN and os.time() - st.LAST_SEEN < KEEPER_STALE_S
        and st.STATUS and st.STATUS.unattended == true
    if not keeper then return 'off', 'no unattended keeper' end
    local okH, halted = pcall(function() return st.is_halted() end)
    if okH and halted then return 'off', 'the AI is halted' end
    return mode, nil
end

-- The player is using the game: hands off for a while.
function player_busy()
    if df.global.pause_state then return 'paused' end
    local okf, default = pcall(dfhack.gui.matchFocusString, 'dwarfmode/Default', dfhack.gui.getDFViewscreen(true))
    if okf and default == false then return 'a menu is open' end
    local okU, u = pcall(dfhack.gui.getSelectedUnit, true)
    if okU and u then return 'a unit is selected' end
    local okB, b = pcall(dfhack.gui.getSelectedBuilding, true)
    if okB and b then return 'a building is selected' end
    local s = CAM.set
    if s and (df.global.window_x ~= s.x or df.global.window_y ~= s.y or df.global.window_z ~= s.z) then
        return 'the view was moved by hand'
    end
    return nil
end

-- The keeper's places ------------------------------------------------------------

-- (0.104.90) From the keeper's report: the plan's districts (names and
-- elevations) and the reasons for its newest work.
function set_brain(t)
    if type(t) ~= 'table' then return end
    local d, n = {}, {}
    for _, x in ipairs(type(t.districts) == 'table' and t.districts or {}) do
        local lo, hi = tonumber(x.lo), tonumber(x.hi)
        if type(x.name) == 'string' and lo and hi then
            table.insert(d, {name = x.name:sub(1, 40), lo = lo, hi = hi})
        end
        if #d >= 12 then break end
    end
    for _, s in ipairs(type(t.news) == 'table' and t.news or {}) do
        if type(s) == 'string' then table.insert(n, s:sub(1, 100)) end
        if #n >= 6 then break end
    end
    CAM.brain = {districts = d, news = n, at = now()}
end

local function elev_offset()
    local ok, v = pcall(function() return reqscript('ai-builder').elevation_offset() end)
    return ok and tonumber(v) or 0
end

function district_of(z)
    local e = z + elev_offset()
    for _, d in ipairs(CAM.brain.districts or {}) do
        if e >= d.lo and e <= d.hi then return d.name end
    end
end

local function news_for(word)
    word = tostring(word or ''):lower()
    if word == '' then return nil end
    for _, s in ipairs(CAM.brain.news or {}) do
        if s:lower():find(word, 1, true) then return s end
    end
end

-- Events ------------------------------------------------------------------------

function add_event(ev)
    if not (ev and ev.x and ev.y and ev.z) then return end
    ev.at = now()
    ev.expires = ev.at + (ev.ttl or EVENT_TTL_S)
    ev.cat = ev.cat or ev.key
    for i, e in ipairs(CAM.queue) do
        -- (0.104.90) several of a kind at once become one stop
        if MERGE[ev.cat] and e.cat == ev.cat then
            e.count = (e.count or 1) + 1
            e.first_label = e.first_label or e.label
            e.label = ev.cat == 'migrants' and ('Migrants arrive: %d of them'):format(e.count)
                or ('%s and %d more %s'):format(e.first_label, e.count - 1, MERGE[ev.cat])
            e.expires = ev.expires
            return
        end
        if e.key and e.key == ev.key then CAM.queue[i] = ev; return end
    end
    table.insert(CAM.queue, ev)
    table.sort(CAM.queue, function(a, b) return a.prio > b.prio end)
    while #CAM.queue > QUEUE_MAX do table.remove(CAM.queue) end
end

local function is_beast(u)
    local ok, r = pcall(function()
        local f = df.global.world.raws.creatures.all[u.race].flags
        if f.CASTE_FEATURE_BEAST then return 'A forgotten beast' end
        if f.CASTE_TITAN then return 'A titan' end
        if f.CASTE_MEGABEAST then return 'A megabeast' end
    end)
    if ok and r then return r end
    local okm, m = pcall(dfhack.units.isMegabeast, u)
    return okm and m and 'A great beast' or nil
end

local function hook_events()
    if CAM.hooked then return end
    pcall(function()
        eventful.enableEvent(eventful.eventType.UNIT_DEATH, 10)
        eventful.enableEvent(eventful.eventType.UNIT_NEW_ACTIVE, 50)
    end)
    eventful.onUnitDeath[KEY] = function(id)
        local u = df.unit.find(id)
        if not u or not dfhack.units.isCitizen(u, true) and not dfhack.units.isDanger(u) then return end
        local p = pos_of(u)
        if p then
            local who = name_of(u)
            local cit = dfhack.units.isCitizen(u, true)
            -- (0.104.100) how they died, under the caption (DF's incident)
            local okc, cause = pcall(function()
                local inc = df.incident.find(u.counters.death_id)
                return inc and df.death_type[inc.death_cause]
            end)
            local sub = okc and type(cause) == 'string' and cause:lower():gsub('_', ' ') or nil
            add_event({x = p.x, y = p.y, z = p.z, prio = 70, kind = 'event', key = 'death' .. id,
                       cat = cit and 'death' or 'slain', label = cit and ('A death: ' .. who) or ('Slain: ' .. who),
                       sub = sub})
        end
    end
    eventful.onUnitNewActive[KEY] = function(id)
        local u = df.unit.find(id)
        if not u then return end
        local p = pos_of(u)
        if not p then return end
        local U = dfhack.units
        local function is(f) local ok, v = pcall(f, u); return ok and v end
        local beast = not U.isCitizen(u, true) and is_beast(u)
        if beast then
            add_event({x = p.x, y = p.y, z = p.z, prio = 85, kind = 'event', key = 'beast' .. id, cat = 'beast',
                       unit = id, label = beast .. ': ' .. name_of(u)})
        elseif is(U.isInvader) then
            add_event({x = p.x, y = p.y, z = p.z, prio = 90, kind = 'event', key = 'invaders', unit = id,
                       label = 'Invaders arrive'})
        elseif is(U.isMerchant) then
            add_event({x = p.x, y = p.y, z = p.z, prio = 60, kind = 'event', key = 'caravan', unit = id,
                       label = 'A caravan arrives', sub = 'following it to the depot'})
        elseif is(U.isDiplomat) then
            add_event({x = p.x, y = p.y, z = p.z, prio = 55, kind = 'event', key = 'diplomat', unit = id,
                       label = 'A diplomat arrives'})
        elseif U.isCitizen(u, true) and is(U.isBaby) then
            add_event({x = p.x, y = p.y, z = p.z, prio = 50, kind = 'event', key = 'birth' .. id, cat = 'birth',
                       label = 'A birth'})
        elseif U.isCitizen(u, true) then
            add_event({x = p.x, y = p.y, z = p.z, prio = 55, kind = 'event', key = 'migrants', cat = 'migrants',
                       unit = id, label = 'Migrants arrive'})
        end
    end
    CAM.hooked = true
end

-- Dangers near citizens: the fight with the most citizens about it.
function find_fight()
    local cits = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local p = pos_of(u)
        if p then table.insert(cits, p) end
    end
    local best, bn
    for _, u in ipairs(df.global.world.units.active) do
        if dfhack.units.isActive(u) and not dfhack.units.isDead(u) and not dfhack.units.isHidden(u)
                and not (u.flags1.caged or u.flags1.chained) and dfhack.units.isDanger(u)
                and not dfhack.units.isCitizen(u, true) then
            local p = pos_of(u)
            if p then
                local n = 0
                for _, c in ipairs(cits) do
                    if math.abs(c.z - p.z) <= 2 and math.max(math.abs(c.x - p.x), math.abs(c.y - p.y)) <= FIGHT_RANGE then
                        n = n + 1
                    end
                end
                if n > 0 and (not bn or n > bn) then best, bn = {u = u, p = p}, n end
            end
        end
    end
    if not best then return nil end
    return {x = best.p.x, y = best.p.y, z = best.p.z, prio = 100, kind = 'fight', key = 'fight', cat = 'fight',
            unit = best.u.id, ttl = 15, label = ('A fight: %s near %d %s'):format(name_of(best.u), bn, bn == 1 and 'dwarf' or 'dwarves')}
end

-- Strange moods (once each), tantrums and bad moods (once an episode).
function find_moods()
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local ok, m = pcall(function() return df.mood_type[u.mood] end)
        m = ok and m or nil
        if MOODS[m] and not CAM.seen_mood[u.id] then
            CAM.seen_mood[u.id] = true
            local p = pos_of(u)
            if p then
                add_event({x = p.x, y = p.y, z = p.z, prio = 65, kind = 'event', key = 'mood' .. u.id, cat = 'mood',
                           unit = u.id, label = name_of(u) .. ' is in a strange mood',
                           sub = 'following them to the workshop'})
            end
        end
        local okt, sm = pcall(function() return df.soldier_mood_type[u.counters.soldier_mood] end)
        local bad = BAD_MOODS[m] or ((okt and (sm == 'Tantrum' or sm == 'Enraged')) and 'is throwing a tantrum') or nil
        if bad and not CAM.bad[u.id] then
            CAM.bad[u.id] = true
            local p = pos_of(u)
            if p then
                add_event({x = p.x, y = p.y, z = p.z, prio = 60, kind = 'event', key = 'bad' .. u.id, cat = 'tantrum',
                           unit = u.id, label = name_of(u) .. ' ' .. bad})
            end
        elseif not bad then
            CAM.bad[u.id] = nil
        end
    end
end

-- (0.104.92) A dwarf gone insane is no longer a citizen to DFHack (isCitizen wants
-- a sane dwarf), so the loop above never saw "stark raving mad" or berserk
-- (23:18 and 00:07 on 25 Oct). Look at the fort's own active units for them.
local INSANE = {Raving = {'has gone stark raving mad', 60}, Berserk = {'has gone berserk', 88}}
function find_insane()
    local okc, civ = pcall(function() return df.global.plotinfo.civ_id end)
    local oka, all = pcall(function() return df.global.world.units.active end)
    if not oka or not all then return end
    for _, u in ipairs(all) do
        local ok, m = pcall(function() return df.mood_type[u.mood] end)
        local what = ok and INSANE[m] or nil
        if what and not CAM.bad[u.id] then
            local okd, dead = pcall(dfhack.units.isDead, u)
            local own = (okc and u.civ_id == civ)
            if not own then
                local oko, r = pcall(dfhack.units.isOwnCiv, u)
                own = oko and r
            end
            local p = own and not (okd and dead) and pos_of(u)
            if p then
                CAM.bad[u.id] = true
                add_event({x = p.x, y = p.y, z = p.z, prio = what[2], kind = 'event',
                           key = 'insane' .. u.id, cat = m == 'Berserk' and 'berserk' or 'tantrum', unit = u.id,
                           ttl = m == 'Berserk' and 60 or nil, label = short_name(u) .. ' ' .. what[1]})
            end
        end
    end
end

-- (0.104.90) What a mood made: a new artifact on the map.
function find_artifacts()
    local okn, n = pcall(function() return #df.global.world.artifacts.all end)
    if not okn then return end
    if not CAM.art_n then CAM.art_n = n return end
    for i = CAM.art_n, n - 1 do
        pcall(function()
            local a = df.global.world.artifacts.all[i]
            local item = a.item
            local x, y, z = dfhack.items.getPosition(item)
            if not x or x < 0 then return end
            local okN, nm = pcall(function()
                local T = dfhack.translation or {}
                local f = T.translateName or dfhack.TranslateName
                return dfhack.df2utf(f(a.name, true))
            end)
            local okD, desc = pcall(function()
                return dfhack.df2utf(dfhack.items.getReadableDescription and dfhack.items.getReadableDescription(item)
                    or dfhack.items.getDescription(item, 0, true))
            end)
            add_event({x = x, y = y, z = z, prio = 75, kind = 'event', key = 'art' .. tostring(a.id), cat = 'artifact',
                       label = 'An artifact is made: ' .. ((okN and nm and nm ~= '') and nm or 'a masterwork'),
                       sub = okD and desc or nil})
        end)
    end
    CAM.art_n = n
end

-- (0.104.90) The AI's levels: one started, one finished.
function find_levels()
    local ok, list = pcall(function() return reqscript('ai-builder').load_projects().list or {} end)
    if not ok then return end
    local first = CAM.proj == nil
    CAM.proj = CAM.proj or {}
    for _, p in ipairs(list) do
        local id, a = tostring(p.id), p.area
        local was = CAM.proj[id]
        if not first and a and a.x1 then
            local c = {x = (a.x1 + a.x2) // 2, y = (a.y1 + a.y2) // 2, z = a.z}
            local kind = tostring(p.kind or 'new')
            if was == nil and (p.phase == 'dig' or p.phase == 'furnish') then
                add_event({x = c.x, y = c.y, z = c.z, prio = 45, kind = 'event', key = 'start' .. id, cat = 'level',
                           label = ('The AI starts a %s level'):format(kind), sub = news_for(kind)})
            elseif was and was ~= 'done' and p.phase == 'done' then
                add_event({x = c.x, y = c.y, z = c.z, prio = 48, kind = 'event', key = 'done' .. id, cat = 'level',
                           label = ('The new %s level is finished'):format(kind), sub = news_for(kind)})
            end
        end
        CAM.proj[id] = p.phase
    end
end

local function first_unit(ev)
    for _, f in ipairs({function() return ev.participants.units[0] end,
                        function() return ev.participants.free_units[0] end,
                        function() return ev.unit_id end, function() return ev.unit end,
                        function() return ev.groups[0].units[0] end}) do
        local ok, v = pcall(f)
        if ok and tonumber(v) and v >= 0 then return v end
    end
end

-- (0.104.90) Small scenes: performances, worship, lessons, play, sparring.
function find_scenes()
    local ok = pcall(function()
        for _, act in ipairs(df.global.world.activities.all) do
            if not CAM.seen_act[act.id] then
                for _, ev in ipairs(act.events) do
                    local okT, t = pcall(function() return df.activity_event_type[ev:getType()] end)
                    local word = okT and SCENES[t]
                    if word then
                        local uid = first_unit(ev)
                        local u = uid and df.unit.find(uid)
                        local p = u and pos_of(u)
                        if p then
                            CAM.seen_act[act.id] = true
                            add_event({x = p.x, y = p.y, z = p.z, prio = 30, kind = 'scene', key = 'act' .. act.id,
                                       cat = 'scene_' .. t, unit = uid, ttl = 150, label = word})
                            break
                        end
                    end
                end
            end
        end
    end)
    -- weddings: a citizen's spouse set where there was none
    pcall(function()
        local first = CAM.spouse == nil
        CAM.spouse = CAM.spouse or {}
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local okS, sp = pcall(function() return u.relationship_ids.Spouse end)
            sp = okS and tonumber(sp) or -1
            local was = CAM.spouse[u.id]
            if not first and sp >= 0 and (was == nil or was < 0) then
                local other = df.unit.find(sp)
                local p = pos_of(u)
                if p and other then
                    local a, b = math.min(u.id, sp), math.max(u.id, sp)
                    add_event({x = p.x, y = p.y, z = p.z, prio = 45, kind = 'event', key = ('wed%d_%d'):format(a, b),
                               cat = 'wedding', unit = u.id, label = name_of(u) .. ' and ' .. name_of(other) .. ' are married'})
                end
            end
            CAM.spouse[u.id] = sp
        end
    end)
    return ok
end

-- (0.104.90) A dwarf reaching legendary skill; a new noble in office.
function find_slow()
    pcall(function()
        local first = CAM.legend == nil
        CAM.legend = CAM.legend or {}
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local okS, skills = pcall(function() return u.status.current_soul.skills end)
            if okS and skills then
                for _, s in ipairs(skills) do
                    if s.rating >= 15 then
                        local k = u.id .. ':' .. s.id
                        if not CAM.legend[k] then
                            CAM.legend[k] = true
                            local p = pos_of(u)
                            if not first and p then
                                local okC, cap = pcall(function() return df.job_skill.attrs[s.id].caption_noun end)
                                add_event({x = p.x, y = p.y, z = p.z, prio = 40, kind = 'event', key = 'leg' .. k,
                                           cat = 'legend', unit = u.id,
                                           label = ('%s is now a legendary %s'):format(short_name(u),
                                               (okC and cap or tostring(df.job_skill[s.id])):lower())})
                            end
                        end
                    end
                end
            end
        end
    end)
    pcall(function()
        local first = CAM.nobles == nil
        CAM.nobles = CAM.nobles or {}
        local ent = df.historical_entity.find(df.global.plotinfo.group_id)
        if not ent then return end
        local names = {}
        for _, pos in ipairs(ent.positions.own) do
            local okN, n = pcall(function() return pos.name[0] end)
            names[pos.id] = okN and n ~= '' and n or nil
        end
        for _, asg in ipairs(ent.positions.assignments) do
            local okH, hf = pcall(function() return asg.histfig2 end)
            if not okH or hf == nil then okH, hf = pcall(function() return asg.histfig end) end
            hf = okH and tonumber(hf) or -1
            local was = CAM.nobles[asg.id]
            if not first and hf >= 0 and hf ~= was and names[asg.position_id] then
                local fig = df.historical_figure.find(hf)
                local u = fig and df.unit.find(fig.unit_id)
                local p = u and pos_of(u)
                if p then
                    add_event({x = p.x, y = p.y, z = p.z, prio = 45, kind = 'event', key = 'noble' .. asg.id .. '_' .. hf,
                               cat = 'noble', unit = u.id,
                               label = ('%s is the new %s'):format(short_name(u), dfhack.df2utf(names[asg.position_id]))})
                end
            end
            CAM.nobles[asg.id] = hf
        end
    end)
end

-- The tour ------------------------------------------------------------------------

local function bounds(b) return {x1 = b.x1, x2 = b.x2, y1 = b.y1, y2 = b.y2, z = b.z} end

function build_tour()
    local stops = {}
    local function add(s)
        s.x, s.y = (s.x1 + s.x2) // 2, (s.y1 + s.y2) // 2
        table.insert(stops, s)
    end
    -- the AI's open digs and new levels
    pcall(function()
        local B = reqscript('ai-builder')
        for _, p in ipairs(B.load_projects().list or {}) do
            local a = p.area
            if (p.phase == 'dig' or p.phase == 'furnish') and a and a.x1 then
                add({x1 = a.x1, x2 = a.x2, y1 = a.y1, y2 = a.y2, z = a.z, key = 'project' .. tostring(p.id),
                     label = ('A new %s level, %s'):format(tostring(p.kind), tostring(p.phase or 'under way'))})
            end
        end
    end)
    local shops, zones_seen, farm_z = {}, {}, {}
    for _, b in ipairs(df.global.world.buildings.all) do
        local t = df.building_type[b:getType()]
        if t == 'Civzone' then
            local zt = df.civzone_type[b.type]
            local word = TOUR_ZONES[zt]
            if word and not zones_seen[zt .. b.z] then
                zones_seen[zt .. b.z] = true
                local s = bounds(b)
                local nm = tostring(b.name or '')
                s.key, s.label = 'zone' .. b.id, nm ~= '' and nm or (word:sub(1, 1):upper() .. word:sub(2))
                add(s)
            end
        elseif t == 'Workshop' or t == 'Furnace' then
            local ok, sub = pcall(function()
                return t == 'Workshop' and df.workshop_type[b:getSubtype()] or df.furnace_type[b:getSubtype()]
            end)
            sub = ok and sub or t
            -- (0.104.90) one stop for each kind; the busiest of them is shown
            local s = shops[sub]
            if not s then
                s = bounds(b)
                s.key = 'shop' .. sub
                s.label = ('The %s'):format(tostring(sub):gsub('(%l)(%u)', '%1 %2'):lower())
                s.bids = {}
                shops[sub] = s
                add(s)
            end
            if #s.bids < 12 then table.insert(s.bids, b.id) end
        elseif t == 'FarmPlot' and not farm_z[b.z] then
            farm_z[b.z] = true
            local s = bounds(b)
            s.key, s.label = 'farm' .. b.z, 'The farms'
            add(s)
        end
    end
    pcall(function()
        local G = reqscript('ai-gates').GATES
        local e = G and G.entrances and G.entrances[1]
        if e and e.x then
            add({x1 = e.x, x2 = e.x, y1 = e.y, y2 = e.y, z = e.z, key = 'gate', label = 'The main gate', always = true})
        end
    end)
    -- (0.104.93) halls of one kind on several levels all read "A meeting hall" (15 of
    -- 96 tour stops on 26 Oct looked like one hall shown over and over): name the place
    local count = {}
    for _, s in ipairs(stops) do count[s.label] = (count[s.label] or 0) + 1 end
    for _, s in ipairs(stops) do
        if count[s.label] > 1 and tostring(s.key):sub(1, 4) == 'zone' then
            local d = district_of(s.z)
            s.label = s.label .. (d and (' in ' .. d) or (', level ' .. (s.z + elev_offset())))
        end
    end
    CAM.tour, CAM.tour_built = stops, now()
    return #stops
end

-- (0.104.90) How busy a stop is now: dwarves in it, a workshop at work.
local function busy_of(s, cits)
    local n, at = 0, nil
    for _, c in ipairs(cits) do
        if c.z == s.z and c.x >= s.x1 - 3 and c.x <= s.x2 + 3 and c.y >= s.y1 - 3 and c.y <= s.y2 + 3 then n = n + 1 end
    end
    local working = false
    for _, id in ipairs(s.bids or {}) do
        local ok, b = pcall(function() return df.building.find(id) end)
        if ok and b then
            local okj, nj = pcall(function() return #b.jobs end)
            if okj and nj > 0 then
                working, at = true, {x = (b.x1 + b.x2) // 2, y = (b.y1 + b.y2) // 2, z = b.z}
                break
            end
        end
    end
    return n, working, at
end

local function next_tour_stop()
    if now() - CAM.tour_built > TOUR_REBUILD_S or #CAM.tour == 0 then build_tour() end
    if #CAM.tour == 0 then return nil end
    local cits = {}
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens(true)) do
            local p = pos_of(u)
            if p then table.insert(cits, p) end
        end
    end)
    local best, bs
    for i, s in ipairs(CAM.tour) do
        if not CAM.recent[s.key] then
            local n, working, at = busy_of(s, cits)
            local seen = CAM.last_seen[s.key]
            -- (0.104.92) a crowd counts up to 4, a stop unseen up to 10 (1 a minute): the
            -- barracks, always full, had come round every few stops (24 of 95 in an hour)
            local novelty = seen and math.min(10, (now() - seen) / 60) or 10
            local score = math.min(n, 4) + (working and 3 or 0) + novelty - i * 0.001
            if n == 0 and not working and not s.always then score = score - 4 end
            if not bs or score > bs then
                bs = score
                best = {x = at and at.x or s.x, y = at and at.y or s.y, z = at and at.z or s.z, prio = 10, kind = 'tour',
                        key = s.key, cat = 'tour', label = s.label,
                        sub = (n > 0 and ('%d %s here'):format(n, n == 1 and 'dwarf' or 'dwarves')) or (working and 'at work') or nil}
            end
        end
    end
    if not best then
        CAM.recent = {}
        return next_tour_stop()
    end
    return best
end

-- Moving the view ----------------------------------------------------------------

local function centre_on(x, y, z)
    local ok = pcall(dfhack.gui.revealInDwarfmodeMap, xyz2pos(x, y, z), true)
    if ok then CAM.set = {x = df.global.window_x, y = df.global.window_y, z = df.global.window_z} end
    return ok
end

function show(spot)
    if not centre_on(spot.x, spot.y, spot.z) then return false end
    CAM.cur, CAM.since, CAM.shown = spot, now(), CAM.shown + 1
    spot.fx, spot.fy, spot.fz = spot.x, spot.y, spot.z
    CAM.recent[spot.key or ''] = true
    CAM.last_seen[spot.key or ''] = now()
    CAM.last_cat[spot.cat or spot.key or ''] = now()
    local n = 0
    for _ in pairs(CAM.recent) do n = n + 1 end
    -- (0.104.92) a stop comes back only after half the tour has been shown (it was 4 stops)
    if n > math.max(3, math.ceil(#CAM.tour / 2)) then CAM.recent = {[spot.key or ''] = true} end
    -- the caption: the label, and what's known about it (the district, the AI's reason)
    local where = district_of(spot.z)
    local sub = spot.sub
    if where and spot.kind == 'tour' then sub = sub and (sub .. ', in ' .. where) or ('in ' .. where) end
    CAM.caption = {text = spot.label, sub = sub, at = now()}
    if spot.kind ~= 'tour' then
        table.insert(CAM.history, 1, {date = game_date(), label = spot.label, sub = sub, kind = spot.kind,
                                      x = spot.x, y = spot.y, z = spot.z})
        while #CAM.history > HISTORY_MAX do table.remove(CAM.history) end
    end
    return true
end

-- (0.104.90) Keep a followed unit in view: the view moves when it walks off.
local function follow()
    local cur = CAM.cur
    if not (cur and cur.unit) then return false end
    local u = df.unit.find(cur.unit)
    if not u then return false end
    local okD, dead = pcall(dfhack.units.isDead, u)
    if okD and dead then return false end
    local p = pos_of(u)
    if not p then return false end
    if p.z ~= cur.fz or math.max(math.abs(p.x - cur.fx), math.abs(p.y - cur.fy)) > FOLLOW_STEP then
        if centre_on(p.x, p.y, p.z) then
            cur.fx, cur.fy, cur.fz = p.x, p.y, p.z
            return true
        end
    end
    return false
end

local function pop_event()
    local t = now()
    for i = #CAM.queue, 1, -1 do
        if CAM.queue[i].expires < t then table.remove(CAM.queue, i) end
    end
    -- (0.104.90) the same kind again too soon waits its turn (urgent ones never)
    for i, e in ipairs(CAM.queue) do
        local last = CAM.last_cat[e.cat or e.key or '']
        local gap = (e.kind == 'scene') and SCENE_GAP_S or CAT_GAP_S
        if e.prio >= 90 or not last or t - last >= gap then
            return table.remove(CAM.queue, i)
        end
    end
    return nil
end

local function dwell_of(spot)
    local base = DWELL_CAT[spot.cat or ''] or DWELL[spot.kind] or DWELL.tour
    return base * (spot.kind == 'fight' and 1 or CAM.pace)
end

-- One step: what to show now, if anything.
function step()
    local mode, why = wanted_mode()
    CAM.mode, CAM.why = mode, why
    if mode == 'off' then return 'off' end
    if not dfhack.isMapLoaded() then return 'no map' end
    if CAM.pinned then CAM.why = 'staying here (' .. KEYS.stay .. ' to let go)' return 'pinned' end
    local busy = player_busy()
    if busy then
        CAM.hold_until, CAM.set, CAM.why = now() + HOLD_S, nil, busy
        return 'held'
    end
    if CAM.skip then
        CAM.skip, CAM.hold_until = false, 0
        if CAM.cur then CAM.since = -math.huge end
    end
    if now() < CAM.hold_until then return 'held' end
    CAM.why = nil
    if mode == 'on' then
        local f = find_fight()
        if f then
            CAM.fight_seen = now()
            local cur = CAM.cur
            -- a fight interrupts anything else; the camera follows it as it moves
            if not cur or cur.kind ~= 'fight' or math.max(math.abs(cur.x - f.x), math.abs(cur.y - f.y)) > FOLLOW_STEP
                    or cur.z ~= f.z then
                show(f)
            else
                cur.label = f.label
            end
            return 'fight'
        end
        -- the fight over: a few seconds on the spot, then on
        if CAM.cur and CAM.cur.kind == 'fight' then
            if now() - (CAM.fight_seen or 0) < 10 then return 'fight' end
            CAM.cur.kind = 'over'
        end
        if now() - (CAM.mood_at or 0) >= 5 then
            CAM.mood_at = now()
            find_moods()
            pcall(find_insane)
            find_artifacts()
        end
        if now() - CAM.scene_at >= SCENE_POLL_S then
            CAM.scene_at = now()
            find_scenes()
            find_levels()
        end
        if now() - CAM.slow_at >= SLOW_POLL_S then
            CAM.slow_at = now()
            find_slow()
        end
    end
    local cur = CAM.cur
    local top = mode == 'on' and CAM.queue[1] or nil
    local due = not cur or now() - CAM.since >= dwell_of(cur)
    if top and top.prio >= 90 and (not cur or (cur.prio or 0) < 90) then due = true end
    if not due then
        if follow() then return 'follow' end
        return 'dwell'
    end
    local spot = (mode == 'on' and pop_event()) or next_tour_stop()
    if spot then show(spot) return 'moved' end
    return 'nothing to show'
end

local function tick()
    CAM.timer = nil
    local ok, r = pcall(step)
    CAM.error = (not ok) and tostring(r):sub(1, 160) or nil   -- (0.104.90) cleared once a step works
    if CAM.mode ~= 'off' then
        CAM.tick_ref = tick
        CAM.timer = dfhack.timeout(CHECK_FRAMES, 'frames', tick)
    end
end

-- (0.104.90) The two keys, bound once a game session.
KEYS_BOUND = KEYS_BOUND or false
local function bind_keys()
    if KEYS_BOUND then return end
    local ok = pcall(function()
        dfhack.run_command_silent('keybinding', 'set', KEYS.skip .. '@dwarfmode/Default', 'ai-camera skip')
        dfhack.run_command_silent('keybinding', 'set', KEYS.stay .. '@dwarfmode/Default', 'ai-camera stay')
    end)
    KEYS_BOUND = ok
end

-- Started (if it isn't running) each time the keeper reports to the panel.
function ensure()
    local mode = wanted_mode()
    CAM.mode = mode
    if mode == 'off' then return false end
    hook_events()
    bind_keys()
    -- (0.104.90) a reloaded module: stop the old file's timer loop, start this one's
    if CAM.timer and CAM.tick_ref ~= tick then
        pcall(dfhack.timeout_active, CAM.timer, nil)
        CAM.timer, CAM.error = nil, nil
    end
    if not CAM.timer or not dfhack.timeout_active(CAM.timer) then
        CAM.tick_ref = tick
        CAM.timer = dfhack.timeout(CHECK_FRAMES, 'frames', tick)
    end
    return true
end

-- The player's controls (the keys, the panel's buttons, the Camera tab).
function skip()
    CAM.pinned, CAM.skip, CAM.hold_until, CAM.set = false, true, 0, nil
    return 'next'
end

function stay(on)
    if on == nil then on = not CAM.pinned end
    CAM.pinned = on and true or false
    if not CAM.pinned then CAM.since = now(); CAM.set = nil; CAM.hold_until = 0 end
    return CAM.pinned and 'staying' or 'moving on'
end

-- Back to something it showed (the Camera tab): there, and it stays.
function go(i)
    local h = CAM.history[tonumber(i) or 0]
    if not h then return false end
    if centre_on(h.x, h.y, h.z) then
        CAM.pinned = true
        CAM.caption = {text = h.label, sub = 'from ' .. h.date, at = now()}
        return true
    end
    return false
end

function status()
    local c = CAM.cur
    local cap = CAM.caption
    if cap and now() - cap.at > CAPTION_S then cap = nil end
    return {mode = CAM.mode, showing = c and c.label or nil, kind = c and c.kind or nil,
            since = c and (now() - CAM.since) or nil, held = CAM.why, queued = #CAM.queue,
            tour_stops = #CAM.tour, shown = CAM.shown, error = CAM.error, pinned = CAM.pinned,
            caption = cap, history = CAM.history, keys = KEYS}
end

-- ai-camera skip | stay | status | history | go <n>
if dfhack_flags and not dfhack_flags.module then
    local args = {...}
    local cmd = args[1] or 'status'
    if cmd == 'skip' then skip() print('Camera: on to the next thing')
    elseif cmd == 'stay' then print('Camera: ' .. stay())
    elseif cmd == 'go' then print(go(args[2]) and 'Camera: back there' or 'Camera: no such entry')
    elseif cmd == 'history' then
        for i, h in ipairs(CAM.history) do print(('%2d. %s  %s'):format(i, h.date, h.label)) end
    else
        local s = status()
        print(('Camera: %s; showing %s%s'):format(s.mode, tostring(s.showing), s.held and (' (' .. s.held .. ')') or ''))
    end
end
