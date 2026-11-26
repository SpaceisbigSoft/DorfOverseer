-- ai-fights-scan: DF's beatings spared (spare_beatings, beating_on), a
-- cursed unit's choke (cursed_choke), the units' scan of each pass
-- (scan_units) and a strangling hold read (grapple_of, choke_of).
--
-- (0.105.119) A part of ai-fights (split off when it reached the size
-- limit), not a script of its own: ai-fights.lua loads it into its own
-- environment, so every name here is reqscript('ai-fights').name and the
-- names defined there are in reach. Only helpers live here: the watcher's
-- state, its timer and its loop stay in ai-fights.lua.

if not PART_LOCALS then qerror('ai-fights-scan is a part of ai-fights; run ai-fights') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-fights-scan'] = '0.105.119'   -- (0.105.26) bumped with BRIDGE_VERSION

local attack_row, attacks_of, bump, conflict_citizen, conflicts_by_unit, field, find_unit, hurt = PART_LOCALS.attack_row, PART_LOCALS.attacks_of, PART_LOCALS.bump, PART_LOCALS.conflict_citizen, PART_LOCALS.conflicts_by_unit, PART_LOCALS.field, PART_LOCALS.find_unit, PART_LOCALS.hurt   -- (0.105.119) the hub's locals
local in_tantrum, is, job_of, living_citizen, log, makeown, unit_name = PART_LOCALS.in_tantrum, PART_LOCALS.is, PART_LOCALS.job_of, PART_LOCALS.living_citizen, PART_LOCALS.log, PART_LOCALS.makeown, PART_LOCALS.unit_name

-- --- (item21) DF's beatings ----------------------------------------------------

-- every punishment waiting or under way: its beating and hammer strikes set
-- to 0 (the prison time kept). Returns the entries spared.
function spare_beatings(S, now, dry)
    if S.spare_beatings == false then return 0 end
    local list = nil
    pcall(function() list = df.global.plotinfo.punishments end)
    if list == nil then return 0 end
    S.beat_logged = S.beat_logged or {}
    local n = 0
    for _, p in ipairs(list) do
        local b, hs = field(p, 'beating'), field(p, 'hammer_strikes')
        if (type(b) == 'number' and b > 0) or (type(hs) == 'number' and hs > 0) then
            local done = false
            if not dry then
                done = pcall(function()
                    if type(b) == 'number' and b > 0 then p.beating = 0 end
                    if type(hs) == 'number' and hs > 0 then p.hammer_strikes = 0 end
                end)
            end
            local cid = field(p, 'criminal')
            local last = S.beat_logged[cid]
            if done or not (last and now - last >= 0 and now - last < ATTACK_LOG_TICKS) then
                S.beat_logged[cid] = now
                local cu, ou = find_unit(cid), find_unit(field(p, 'officer'))
                if done then n = n + 1; bump(S, 'beatings_spared') end
                log(S, {kind = 'beating_spared', tick = now, criminal = cid, criminal_name = cu and unit_name(cu) or nil,
                        officer = field(p, 'officer'), officer_name = ou and unit_name(ou) or nil, beating = b,
                        hammer_strikes = hs, prison = field(p, 'prison_counter'), spared = done,
                        dry = dry or nil})
            end
        end
    end
    for k, t in pairs(S.beat_logged) do if now - t >= ATTACK_LOG_TICKS or now < t then S.beat_logged[k] = nil end end
    return n
end

-- a law officer's beating (job BeatCriminal) of a living citizen: stopped (the
-- officer's job removed) once the convict is suffocating, unconscious,
-- bleeding or held in a strangling grip. True when stopped (or would be, dry).
function beating_on(S, now, dry, u, target, h)
    if S.spare_beatings == false then return false end
    local g = grapple_of(h.attack)
    local danger = hurt(target) or ((g and CHOKE_MOVES[g]) and 'choke hold') or nil
    if not danger then return false end
    local done = false
    if not dry then
        done = pcall(function()
            local j = u.job.current_job
            if j == nil then error('no job') end
            dfhack.job.removeJob(j)
        end)
        if done then
            bump(S, 'beatings_stopped')
            if danger == 'suffocating' or danger == 'choke hold' then bump(S, 'chokes') end
        end
    end
    local key = tostring(u.id) .. '>' .. tostring(target.id)
    local last = S.attack_logged[key]
    S.attack_logged[key] = now
    if not done and last and now - last >= 0 and now - last < TANTRUM_LOG_TICKS then return true end
    log(S, {kind = 'beating_stopped', tick = now, id = u.id, name = unit_name(u), target = target.id,
            target_name = unit_name(target), danger = danger, grapple = g, stopped = done, dry = dry or nil,
            suffocation = field(field(target, 'counters'), 'suffocation'), attack = attack_row(h.attack)})
    return true
end

-- (item34) F 25 Nov: a weremole, a dwarf again 11 s, strangled a bitten mason
-- (both 'were syndrome', unseen). A dwarf of the fort in dwarf form choking or
-- suffocating another, one of them bitten: both out of their conflicts.
local function cursed(u)
    return u ~= nil and not is(dfhack.units.isDead, u) and were_of(u) == 'were syndrome'
        and field(u, 'civ_id') == field(df.global.plotinfo, 'civ_id')
end

function cursed_choke(S, now, dry, u, hits, cu)
    for _, h in ipairs(hits) do
        local t = find_unit(h.target)
        if t and t.id ~= u.id and (cu or cursed(t)) and (cursed(t) or unit_kind(t) == 'citizen') then
            local g = grapple_of(h.attack)
            local suff = field(field(t, 'counters'), 'suffocation')
            if (g and CHOKE_MOVES[g]) or (type(suff) == 'number' and suff > 0) then
                local mo = not dry and makeown() or nil
                local done = mo ~= nil and pcall(mo.remove_from_conflict, u) and pcall(mo.remove_from_conflict, t)
                if done then bump(S, 'chokes'); bump(S, 'cursed_chokes'); S.recent[u.id], S.recent[t.id] = now, now end
                local key = tostring(u.id) .. '#' .. tostring(t.id)
                local last = S.attack_logged[key]
                S.attack_logged[key] = now
                if not (last and now - last >= 0 and now - last < TANTRUM_LOG_TICKS) then
                    log(S, {kind = 'cursed_choke', tick = now, id = u.id, name = unit_name(u), target = t.id,
                            target_name = unit_name(t), grapple = g, suffocation = suff, separated = done,
                            dry = dry or nil})
                end
                return true
            end
        end
    end
    return false
end

-- one look at the living citizens: a tantrum that attacks a citizen ended,
-- a calm citizen's attack on a citizen logged, or counted as sparring
-- (item3: spar_reason). Returns the tantrums ended.
function scan_units(S, now, dry, list)
    local units = {}
    local ok = pcall(function() units = df.global.world.units.active end)
    if not ok or units == nil then return 0 end
    S.tantrum_logged = S.tantrum_logged or {}
    S.attack_logged = S.attack_logged or {}
    S.attack_seen = S.attack_seen or {}              -- (item3) a state from an older load of this file
    S.spar_logged = S.spar_logged or {}
    S.spars_recent = S.spars_recent or {}
    S.counts.spars = S.counts.spars or 0
    local calm = {}
    local on = S.end_tantrums ~= false
    local by = nil
    local ended = 0
    for _, u in ipairs(units) do
        local tantrum = in_tantrum(u)
        local hits = attacks_of(u)
        local cu = #hits > 0 and cursed(u)
        local kind = (tantrum or #hits > 0) and not cu and unit_kind(u) or nil
        if (cu or kind == 'citizen') and cursed_choke(S, now, dry, u, hits, cu) then
            -- (item34) a choke with a bitten dwarf in it: taken apart above
        elseif kind == 'citizen' then
            by = by or conflicts_by_unit(list)
            if tantrum then
                local target, how, at, act_id = nil, nil, nil, nil
                for _, h in ipairs(hits) do
                    target = living_citizen(h.target)
                    if target then how, at = 'attack', h.attack; break end
                end
                if not target then
                    target = living_citizen(field(field(u, 'opponent'), 'unit_id'))
                    if target then how = 'opponent' end
                end
                if not target then
                    target, act_id = conflict_citizen(by, u.id)
                    if target then how = 'conflict' end
                end
                if target then
                    local before = field(u.counters, 'soldier_mood_countdown')
                    local done = false
                    if on and not dry and type(before) == 'number' and before > 1 then
                        done = pcall(function() u.counters.soldier_mood_countdown = 1 end)
                        if done then
                            ended = ended + 1
                            bump(S, 'tantrums_ended')
                        end
                    end
                    local last = S.tantrum_logged[u.id]
                    if not (last and now - last >= 0 and now - last < TANTRUM_LOG_TICKS) then
                        S.tantrum_logged[u.id] = now
                        bump(S, 'tantrum_attacks')
                        local mood = nil
                        pcall(function() mood = df.soldier_mood_type[u.counters.soldier_mood] end)
                        log(S, {kind = 'tantrum_ended', tick = now, id = u.id, name = unit_name(u),
                                mood = mood, target = target.id, target_name = unit_name(target), how = how,
                                countdown = before, ended = done, off = (not on) or nil, dry = dry or nil,
                                suffocation = field(field(target, 'counters'), 'suffocation'),
                                activity_id = act_id, opponent_timer = field(field(u, 'opponent'), 'timer'),
                                attack = attack_row(at)})
                    end
                end
            else
                -- (item3) a calm citizen's attacks: all of this pass's seen first (a
                -- mutual pair is both ways in the same ticks), judged below
                for _, h in ipairs(hits) do
                    local target = living_citizen(h.target)
                    if target then
                        S.attack_seen[tostring(u.id) .. '>' .. tostring(target.id)] = now
                        table.insert(calm, {u = u, target = target, h = h})
                    end
                end
            end
        end
    end
    local tidx = nil
    for _, c in ipairs(calm) do
        local u, target, h = c.u, c.target, c.h
        local job = job_of(u)
        local beat = job == BEAT_JOB and beating_on(S, now, dry, u, target, h)
        tidx = tidx or training_index()
        local why, what = nil, nil
        if job ~= BEAT_JOB then why, what = spar_reason(S, by, u, target, now, tidx) end
        if beat then
            -- (item21) a beating stopped: its own log entry
        elseif why then
            -- (item3) sparring: counted once a pair a ATTACK_LOG_TICKS, kept out of the log
            local lo, hi = math.min(u.id, target.id), math.max(u.id, target.id)
            local key = tostring(lo) .. '~' .. tostring(hi)
            local last = S.spar_logged[key]
            if not (last and now - last >= 0 and now - last < ATTACK_LOG_TICKS) then
                S.spar_logged[key] = now
                bump(S, 'spars')
                table.insert(S.spars_recent, {tick = now, id = u.id, name = unit_name(u), target = target.id,
                                              target_name = unit_name(target), why = why, what = what})
                while #S.spars_recent > SPAR_RECENT_KEEP do table.remove(S.spars_recent, 1) end
            end
        else
            local key = tostring(u.id) .. '>' .. tostring(target.id)
            local last = S.attack_logged[key]
            if not (last and now - last >= 0 and now - last < ATTACK_LOG_TICKS) then
                S.attack_logged[key] = now
                bump(S, 'attacks')
                log(S, {kind = 'attack', tick = now, id = u.id, name = unit_name(u), target = target.id,
                        target_name = unit_name(target), job = job,
                        suffocation = field(field(target, 'counters'), 'suffocation'),
                        attack = attack_row(h.attack)})
            end
        end
    end
    for id, t in pairs(S.tantrum_logged) do if now - t >= TANTRUM_LOG_TICKS or now < t then S.tantrum_logged[id] = nil end end
    for k, t in pairs(S.attack_logged) do if now - t >= ATTACK_LOG_TICKS or now < t then S.attack_logged[k] = nil end end
    for k, t in pairs(S.attack_seen) do if now - t > MUTUAL_TICKS or now < t then S.attack_seen[k] = nil end end
    for k, t in pairs(S.spar_logged) do if now - t >= ATTACK_LOG_TICKS or now < t then S.spar_logged[k] = nil end end
    return ended
end

-- --- (0.105.112) a strangling hold: separated at once ------------------------

-- the grapple move of an attack's wrestle_info (df.wrestle_attack_type's name:
-- 1 Choke, 13 FollowStrangle, as DF 53.x lists them), or nil
function grapple_of(at)
    local g = field(field(at, 'wrestle_info'), 'grapple_attack')
    if type(g) ~= 'number' or g < 0 then return nil end
    local ok, nm = pcall(function() return df.wrestle_attack_type[g] end)
    if ok and type(nm) == 'string' then return nm end
    return CHOKE_CODES[g] or tostring(g)
end

-- a unit of the conflict choking a living citizen of it: {by, victim, how =
-- 'hold' (a Choke/FollowStrangle grapple; only when `fighting`, a brawl or
-- worse: wrestlers choke in sparring) or 'suffocation' (its target's
-- counters.suffocation > 0, at any level), grapple, suffocation}, or nil
function choke_of(j, fighting)
    local cit = {}
    for _, r in ipairs(j.units) do if r.kind == 'citizen' then cit[r.id] = r end end
    local found = nil
    for _, r in ipairs(j.units) do
        if r.kind ~= 'dead' then
            for _, h in ipairs(attacks_of(r.u)) do
                local v = cit[h.target]
                if v and h.target ~= r.id then
                    local g = grapple_of(h.attack)
                    local suff = field(field(v.u, 'counters'), 'suffocation')
                    if type(suff) ~= 'number' then suff = nil end
                    local c = {by = r.id, by_name = unit_name(r.u), victim = v.id, victim_name = unit_name(v.u),
                               grapple = g, suffocation = suff}
                    if fighting and g and CHOKE_MOVES[g] then
                        c.how = 'hold'
                        return c
                    end
                    if suff and suff > 0 and not found then
                        c.how = 'suffocation'
                        found = c
                    end
                end
            end
        end
    end
    return found
end
