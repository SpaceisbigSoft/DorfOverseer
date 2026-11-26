-- ai-bridge-report-dead: the report's tombs and the dead (in_ai_tombs,
-- standing_orders_dead, get_dead).
--
-- A part of ai-bridge.lua (0.105.113, split out of ai-bridge-report-supplies.lua
-- when it reached the size limit), loaded by it right after
-- ai-bridge-report-supplies into its own environment, as every part: what
-- is global here is the bridge's (reachable as reqscript('ai-bridge').<name>),
-- and the bridge's shared helpers are at hand. The few local helpers the
-- other ai-bridge-report files share with this one come from REPORT_PART_LOCALS. Not a
-- command of its own.

if not BRIDGE_VERSION then qerror('ai-bridge-report-dead is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-report-dead'] = '0.105.126'   -- bumped with BRIDGE_VERSION

local inc = REPORT_PART_LOCALS.inc

-- The dead: ghosts of the fort's own, citizens' bodies not yet in a coffin,
-- and coffins in a tomb zone that are still free for a burial.
local CORPSE_TYPES = {CORPSE = true, CORPSEPIECE = true, REMAINS = true}
-- (item4) what dump_bodies lets past ai-util item_unfree (ai-disposal ALLOW):
-- the dead report's not_ours_dumpable asks the same
DUMP_ALLOW = {forbid = true, dump = true, owned = true, artifact = true, dead_dwarf = true, rotten = true}

local function coffin_is_free(b)
    for _, ci in ipairs(b.contained_items) do
        if ci.use_mode == 0 and CORPSE_TYPES[df.item_type[ci.item:getType()]] then
            return false
        end
    end
    return true
end

local function in_tomb_zone(b)
    local ok, zones = pcall(dfhack.buildings.findCivzonesAt, xyz2pos(b.centerx, b.centery, b.z))
    if not ok or not zones then return false, nil end
    for _, z in ipairs(zones) do
        if z.type == df.civzone_type.Tomb then
            -- a tomb set aside for one dwarf (a noble's) isn't free for others
            local okid, owner = pcall(function() return z.assigned_unit_id end)
            return true, okid and owner or -1, z
        end
    end
    return false, nil
end

-- (0.104.16) a free tomb zone's own state: whether the game would bury a
-- citizen there (zone active, citizens not turned away)
local function tomb_state(z)
    local st = {}
    pcall(function() if z.is_active == 0 or z.is_active == false then st.inactive = true end end)
    pcall(function() if z.zone_settings.tomb.flags.no_citizens then st.no_citizens = true end end)
    pcall(function() if z.zone_settings.tomb.flags.no_pets == false then st.pets = true end end)
    return st
end

-- (0.104.21) The AI's tomb levels' areas (cached for one report).
AI_TOMBS = nil
function in_ai_tombs(x, y, z)
    if not AI_TOMBS then
        AI_TOMBS = {}
        pcall(function()
            local B = reqscript('ai-builder')
            -- (R29 W7) read only (own_areas builds its own tables): no copy of the record
            local read = type(B.projects_read_only) == 'function' and B.projects_read_only or B.load_projects
            for _, p in ipairs(read().list) do
                if p.kind == 'tombs' and type(p.area) == 'table' then
                    -- (F4, S2) a floor tomb level: its own rooms only (a.own)
                    local oko, own = pcall(function() return B.own_areas(p) end)
                    for _, a in ipairs(oko and type(own) == 'table' and own or {p.area}) do
                        table.insert(AI_TOMBS, a)
                    end
                end
            end
        end)
        -- (0.105.47) and the coffins the AI put on its other levels (lua/ai-welfare.lua)
        pcall(function()
            for _, a in ipairs(reqscript('ai-welfare').corner_areas()) do table.insert(AI_TOMBS, a) end
        end)
    end
    for _, a in ipairs(AI_TOMBS) do
        if z == a.z and x >= a.x1 and x <= a.x2 and y >= a.y1 and y <= a.y2
                and (type(a.own) ~= 'function' or a.own({x1 = x, y1 = y, x2 = x, y2 = y})) then return true end
    end
    return false
end

-- (0.105.27) the game's standing orders on the dead, refuse and dumping
-- (uint8_t globals, df.global.standing_orders_*): {name = 0/1} for each
-- that exists in this DF, the name without the prefix
STANDING_DEAD_ORDERS = {
    'forbid_used_ammo', 'forbid_own_dead', 'forbid_own_dead_items', 'forbid_other_nohunt',
    'forbid_other_dead_items', 'gather_refuse', 'gather_refuse_outside',
    'dump_corpses', 'dump_skulls', 'dump_bones', 'dump_shells', 'dump_skins', 'dump_hair', 'dump_other',
}

local function standing_kept(name)
    return name:match('^forbid_') or name:match('^gather_refuse') or name:match('^dump_')
end

function standing_orders_dead()
    local out = {}
    local function read(name)
        local ok, v = pcall(function() return df.global['standing_orders_' .. name] end)
        if not ok or v == nil then return end
        if type(v) == 'boolean' then out[name] = v and 1 or 0
        elseif type(v) == 'number' then out[name] = v ~= 0 and 1 or 0 end
    end
    for _, name in ipairs(STANDING_DEAD_ORDERS) do read(name) end
    -- any other of the kind this DF has (the globals listed, where the game lets them be)
    pcall(function()
        for k in pairs(df.global) do
            local name = type(k) == 'string' and k:match('^standing_orders_(.+)$')
            if name and out[name] == nil and standing_kept(name) then read(name) end
        end
    end)
    return out
end

function get_dead()
    AI_TOMBS = nil
    local out = {ghosts = 0, ghost_names = {}, unburied = 0, tomb_coffins = 0, free_tombs = 0,
                 loose_coffins = 0}
    local race, civ = df.global.plotinfo.race_id, df.global.plotinfo.civ_id
    local from0 = citizen_anchor()
    -- (13c) the memorial slabs by whom they remember, read once (each ghost
    -- walked every slab)
    local memorials
    local function memorials_of(hf)
        if not memorials then
            memorials = {}
            for _, it in ipairs(df.global.world.items.other.SLAB) do
                if it.engraving_type == df.slab_engraving_type.Memorial then
                    memorials[it.topic] = memorials[it.topic] or {}
                    table.insert(memorials[it.topic], it)
                end
            end
        end
        return memorials[hf] or {}
    end
    -- and the bodies by whose they are (the last one listed, as before)
    local bodies
    local function body_of(id)
        if not bodies then
            bodies = {}
            for _, c in ipairs(df.global.world.items.other.CORPSE) do bodies[c.unit_id] = c end
        end
        return bodies[id]
    end
    -- (0.105.94) every ghostly unit, not only the active list's: a ghost
    -- drops off the active list between its appearances (F, 23 Nov: Urvad's
    -- ghost in units.all only, dead.ghosts 0, so no slab rule ever ran)
    local ghostly = {}
    pcall(function()
        for _, u in ipairs(df.global.world.units.all) do
            local okg, g = pcall(function() return u.flags3.ghostly end)
            if okg and g then table.insert(ghostly, u) end
        end
    end)
    if #ghostly == 0 then ghostly = report_units() end
    for _, u in ipairs(ghostly) do
        if dfhack.units.isGhost(u) and u.race == race and u.civ_id == civ then
            out.ghosts = out.ghosts + 1
            if #out.ghost_names < 5 then
                table.insert(out.ghost_names, txt(dfhack.units.getReadableName(u)))
            end
            -- (0.104.39) each ghost: its kind (a violent one scares dwarves to
            -- death: 24 of Enxah's 34 deaths in a year were fright) and what
            -- memorial slab there is for it
            pcall(function()
                out.ghost_list = out.ghost_list or {}
                if #out.ghost_list < 20 then
                    local g = {id = u.id, hf = u.hist_figure_id, name = txt(dfhack.units.getReadableName(u))}
                    pcall(function() g.kind = df.ghost_type[u.ghost_info.type] end)
                    pcall(function()
                        for _, it in ipairs(memorials_of(u.hist_figure_id)) do
                            local st = it.flags.in_building and 'built' or it.flags.in_job and 'job'
                                or it.flags.construction and 'built' or 'loose'
                            g.slab = (g.slab == 'built') and 'built' or st
                            -- (0.104.41) where it is and what holds it
                            local x, y, z = dfhack.items.getPosition(it)
                            g.slab_at = {x = x, y = y, z = z, forbid = it.flags.forbid or nil,
                                         dump = it.flags.dump or nil, trader = it.flags.trader or nil,
                                         owned = it.flags.owned or nil}
                            pcall(function()
                                for _, ref in ipairs(it.specific_refs) do
                                    if ref.type == df.specific_ref_type.JOB then
                                        local j = ref.data.job
                                        g.slab_job = {type = df.job_type[j.job_type], suspended = j.flags.suspend or nil,
                                                      worker = dfhack.job.getWorker(j) and true or nil}
                                        local h = dfhack.job.getHolder(j)
                                        if h then g.slab_job.building = df.building_type[h:getType()]; g.slab_job.stage = h:getBuildStage() end
                                        -- (0.104.46) why it's suspended, by DFHack's suspendmanager
                                        pcall(function()
                                            local sm = require('plugins.suspendmanager')
                                            local keys = {}
                                            for k, v in pairs(sm) do if type(v) == 'function' then table.insert(keys, k) end end
                                            table.sort(keys)
                                            out.sm_api = keys
                                            for _, fn in ipairs({'suspendmanager_suspensionDescription', 'suspensionDescription',
                                                                 'getSuspensionDescription', 'suspendmanager_getDescription'}) do
                                                if sm[fn] then g.slab_job.why = tostring(sm[fn](j)) break end
                                            end
                                            if sm.isKeptSuspended then g.slab_job.kept = sm.isKeptSuspended(j) end
                                        end)
                                        pcall(function()
                                            local pos = xyz2pos(h.centerx, h.centery, h.z)
                                            local n = 0
                                            for _, it2 in ipairs(dfhack.maps.getTileBlock(pos).items) do
                                                local i2 = df.item.find(it2)
                                                if i2 and i2.pos.x == pos.x and i2.pos.y == pos.y and i2.pos.z == pos.z then n = n + 1 end
                                            end
                                            g.slab_job.items_on_tile = n
                                            g.slab_job.at = {x = pos.x, y = pos.y, z = pos.z}
                                        end)
                                    end
                                end
                            end)
                            pcall(function()
                                if from0 and x then g.slab_at.reach = dfhack.maps.canWalkBetween(from0, xyz2pos(x, y, z)) end
                            end)
                            -- (0.104.48) out of reach: the tiles round it, to see why
                            pcall(function()
                                if g.slab_at.reach == false and x then
                                    local rows = {}
                                    for yy = y - 3, y + 3 do
                                        local row = {}
                                        for xx = x - 3, x + 3 do
                                            local ch = '?'
                                            local tt = dfhack.maps.getTileType(xx, yy, z)
                                            local d, occ = dfhack.maps.getTileFlags(xx, yy, z)
                                            if tt then
                                                local sh = df.tiletype_shape[df.tiletype.attrs[tt].shape]
                                                ch = (sh == 'WALL' and '#') or (sh == 'FLOOR' and '.') or (sh == 'RAMP' and '^')
                                                    or (sh and sh:find('STAIR') and 'X') or (sh == 'EMPTY' and ' ') or ','
                                                if occ and occ.building ~= df.tile_building_occ.None then ch = 'B' end
                                                if d and d.flow_size > 0 then ch = d.flow_size >= 4 and 'W' or 'w' end
                                                if xx == x and yy == y then ch = '@' end
                                            end
                                            table.insert(row, ch)
                                        end
                                        table.insert(rows, table.concat(row))
                                    end
                                    g.slab_at.around = rows
                                    local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z))
                                    if b then g.slab_at.building = df.building_type[b:getType()] end
                                end
                            end)
                        end
                    end)
                    pcall(function()
                        local c = body_of(u.id)
                        g.body = c and (c.flags.in_building and 'entombed' or 'lying') or 'none'
                    end)
                    table.insert(out.ghost_list, g)
                end
            end)
        end
    end
    -- (0.104.15) why the unburied aren't buried: Enxah had 104 bodies and
    -- 7 free tombs for a whole season. Forbidden (DF's "forbid your dead"
    -- standing order, or by hand), marked for dumping, out of the dwarves'
    -- reach, or already on someone's job.
    local why = {forbidden = 0, dump = 0, in_job = 0, unreachable = 0, outside = 0, carried = 0,
                 not_ours = 0, free = 0, not_ours_loose = 0}  -- (item8) loose 0 said: none (B: both marked, read as an old bridge)
    local samples = {}
    local side_ctx
    pcall(function()
        local U = reqscript('ai-util')
        if type(U.corpse_side) == 'function' and type(U.fort_race_civ) == 'function' then
            local r, c, g = U.fort_race_civ()
            side_ctx = {U = U, race = r, civ = c, group = g}
        end
    end)
    local from = from0      -- where the first citizen stands (13c: found once, above)
    local D, dumps, edges = nil, nil, {}    -- (item8) the dumps, for left_beside
    pcall(function() D = reqscript('ai-disposal'); dumps = D.left_beside and D.dump_zones() end)
    for _, it in ipairs(df.global.world.items.other.CORPSE) do
        local ok, r = pcall(function() return it.race end)
        if ok and r == race and not it.flags.in_building and not it.flags.removed then
            out.unburied = out.unburied + 1
            pcall(function()
                local f = it.flags
                if f.forbid then why.forbidden = why.forbidden + 1 end
                if f.dump then why.dump = why.dump + 1 end
                if f.in_job then why.in_job = why.in_job + 1 end
                if f.in_inventory then why.carried = why.carried + 1 end
                local x, y, z = dfhack.items.getPosition(it)
                local reach = true
                if x and from then
                    reach = dfhack.maps.canWalkBetween(from, xyz2pos(x, y, z))
                    if not reach then why.unreachable = why.unreachable + 1 end
                    local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
                    if d and d.outside then why.outside = why.outside + 1 end
                end
                -- (0.104.16) whose body: the fort's own dead, or a visitor's,
                -- a merchant's, a migrant's who never joined (DF buries only
                -- its own in the fort's tombs)
                -- (0.105.51) the shared classifier (ai-util corpse_side: the
                -- dead one's record, a visitor or merchant of any civ is not
                -- ours), else the civ alone as before
                local okc, own = pcall(function()
                    if side_ctx then return side_ctx.U.corpse_side(it, 'CORPSE', side_ctx) == 'own' end
                    local du = df.unit.find(it.unit_id)
                    return du ~= nil and du.civ_id == civ
                end)
                if okc and not own then
                    why.not_ours = why.not_ours + 1
                    -- (0.105.51) of those, the ones neither marked for the dump
                    -- nor lying in a garbage dump zone: the brain's burial_others
                    -- asks for these alone (a dumped body stays counted above)
                    local loose = not f.dump
                    if loose and x then
                        pcall(function()
                            for _, zn in ipairs(dfhack.buildings.findCivzonesAt(xyz2pos(x, y, z)) or {}) do
                                if zn.type == df.civzone_type.Dump then loose = false end
                            end
                        end)
                    end
                    -- (item8) beside a dump on a ramp's edge: DF dumped it there, as dump_bodies says
                    if loose and x and dumps and D.left_beside(dumps, x, y, z, edges) then
                        loose = false
                        why.not_ours_beside = (why.not_ours_beside or 0) + 1
                    end
                    if loose then why.not_ours_loose = (why.not_ours_loose or 0) + 1 end
                    -- (0.105.99) of the loose, those dump_bodies takes (the same
                    -- test) and the dwarves can walk to: burial_others asks for
                    -- these alone, and says why when none (B, 24 Nov: 44 refusals
                    -- in 2 hours for a visitor's body the action kept)
                    if loose then
                        local okd, dumpable = pcall(function()
                            return side_ctx ~= nil and side_ctx.U.dumpable_other_body(it, 'CORPSE', side_ctx)
                        end)
                        -- (item4) and free for the action to touch, as dump_bodies
                        -- asks (ai-disposal blocked: on the ground, on no job, in
                        -- no hand): one carried or on a job counted dumpable and
                        -- the action refused ("no body ... may be marked")
                        local free = true
                        if okd and dumpable and reach then
                            local okf, f2 = pcall(function()
                                local SU = side_ctx.U
                                return SU.on_ground(it) and SU.item_unfree(it, DUMP_ALLOW) == nil
                            end)
                            free = not okf or f2 == true
                        end
                        if okd and dumpable and reach and not free then
                            why.not_ours_busy = (why.not_ours_busy or 0) + 1
                        elseif okd and dumpable then
                            if reach then
                                why.not_ours_dumpable = (why.not_ours_dumpable or 0) + 1
                            else
                                why.not_ours_unreachable = (why.not_ours_unreachable or 0) + 1
                            end
                        elseif okd and side_ctx ~= nil then
                            why.not_ours_kept = (why.not_ours_kept or 0) + 1
                        end
                    end
                end
                -- (0.105.99) forbidden where the dwarves can walk: the burial
                -- rule's unforbid_dead asked only while forbidden outnumbered
                -- unreachable (B, 24 Nov: 2 forbidden on a barracks floor, 6
                -- unforbidden under water, so never). And the out-of-reach under water.
                if f.forbid and reach and not f.in_job and (not okc or own) then
                    why.forbidden_reach = (why.forbidden_reach or 0) + 1
                end
                if not reach and x then
                    pcall(function()
                        local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
                        if d and d.flow_size > 0 and not d.liquid_type then
                            why.in_water = (why.in_water or 0) + 1
                        end
                    end)
                end
                if reach and not f.forbid and not f.dump and not f.in_job and not f.in_inventory
                        and (not okc or own) then
                    why.free = why.free + 1          -- nothing in the way that the AI can see
                end
                if #samples < 5 and (f.forbid or not reach) and x then
                    local smp = {x = x, y = y, z = z, forbidden = f.forbid or nil, reach = reach}
                    -- (0.104.39) what the spot is: water over it, open space,
                    -- and how this one died (Enxah: 29 bodies out of reach)
                    pcall(function()
                        local d = dfhack.maps.getTileFlags(xyz2pos(x, y, z))
                        if d and d.flow_size > 0 then
                            smp.water = d.flow_size
                            if d.liquid_type then smp.magma = true end
                        end
                        local tt = dfhack.maps.getTileType(xyz2pos(x, y, z))
                        if tt then smp.shape = df.tiletype_shape[df.tiletype.attrs[tt].shape] end
                    end)
                    pcall(function()
                        local du = df.unit.find(it.unit_id)
                        local inc = du and df.incident.find(du.counters.death_id)
                        if inc then smp.cause = df.death_type[inc.death_cause] end
                    end)
                    table.insert(samples, smp)
                end
            end)
        end
    end
    if out.unburied > 0 then
        out.why = why
        if #samples > 0 then out.samples = samples end
    end
    -- (0.104.39) how the fort's own died this year and last (DF's death
    -- incidents): Enxah lost dwarves overnight with none of it said
    pcall(function()
        local by, n, killers, by_citizen = {}, 0, {}, {}
        local y0 = df.global.cur_year - 1
        for _, inc in ipairs(df.global.world.incidents.all) do
            pcall(function()
                if inc.type == df.incident_type.Death and inc.event_year >= y0 then
                    local du = df.unit.find(inc.victim)
                    if du and du.civ_id == civ and du.race == race then
                        local c = df.death_type[inc.death_cause] or tostring(inc.death_cause)
                        by[c] = (by[c] or 0) + 1
                        n = n + 1
                        -- (0.104.50) who struck them down: a citizen (a fight, a
                        -- berserk, the guard), a ghost, a beast, an outsider
                        pcall(function()
                            local k = inc.criminal ~= -1 and df.unit.find(inc.criminal)
                            if k then
                                local who = (dfhack.units.isGhost(k) or dfhack.units.isDead(k)) and 'ghost'
                                    or (dfhack.units.isCitizen(k) or k.civ_id == civ) and 'citizen'
                                    or (dfhack.units.isAnimal and dfhack.units.isAnimal(k)) and 'animal'
                                    or 'outsider'
                                killers[who] = (killers[who] or 0) + 1
                                if who == 'citizen' and #by_citizen < 8 then
                                    table.insert(by_citizen, {cause = c, killer = txt(dfhack.units.getReadableName(k)),
                                                              victim = txt(dfhack.units.getReadableName(du))})
                                end
                            end
                        end)
                    end
                end
            end)
        end
        out.deaths = {since_year = y0, n = n, by_cause = by, killers = killers,
                      by_citizen = #by_citizen > 0 and by_citizen or nil}
    end)
    -- (0.104.16) who may bury them (the Burial labour, HAUL_BODY) and whether
    -- the free tombs can be walked to
    pcall(function()
        local n, lab = 0, df.unit_labor.HAUL_BODY
        for _, u in ipairs(report_citizens(true)) do
            if u.status.labors[lab] then n = n + 1 end
        end
        out.burial_labor = n
    end)
    out._from = from
    -- the game's standing orders on the dead (the Orders screen)
    -- (0.105.27) they are uint8_t 0/1, never true: `== true` read them false always
    out.standing = standing_orders_dead()
    out.forbid_own_dead = (out.standing.forbid_own_dead or 0) ~= 0
    out.forbid_own_dead_items = (out.standing.forbid_own_dead_items or 0) ~= 0
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Coffin and b:getBuildStage() >= b:getMaxBuildStage() then
            local tomb, owner, zone = in_tomb_zone(b)
            if not tomb then
                out.loose_coffins = out.loose_coffins + 1
            else
                out.tomb_coffins = out.tomb_coffins + 1
                local st = zone and tomb_state(zone) or {}
                -- (0.104.21) a tomb closed to citizens outside the AI's tomb
                -- levels (a noble's, or one you set up) isn't free for the dead:
                -- not counted, so the tomb rules see the real room
                local reserved = st.no_citizens and not in_ai_tombs(b.centerx, b.centery, b.z)
                if reserved and coffin_is_free(b) and (owner == nil or owner < 0) then
                    out.reserved_tombs = (out.reserved_tombs or 0) + 1
                elseif coffin_is_free(b) and (owner == nil or owner < 0) then
                    out.free_tombs = out.free_tombs + 1
                    if zone then
                        if st.inactive then out.free_tombs_inactive = (out.free_tombs_inactive or 0) + 1 end
                        if st.no_citizens then
                            out.free_tombs_no_citizens = (out.free_tombs_no_citizens or 0) + 1
                            -- (0.104.19) where: a noble's tomb, or a tomb of the AI's levels
                            out.closed_tombs = out.closed_tombs or {}
                            if #out.closed_tombs < 8 then
                                table.insert(out.closed_tombs, {x = b.centerx, y = b.centery, z = b.z, zone = zone.id})
                            end
                        end
                    end
                    pcall(function()
                        if out._from and not dfhack.maps.canWalkBetween(out._from, xyz2pos(b.centerx, b.centery, b.z)) then
                            out.free_tombs_unreachable = (out.free_tombs_unreachable or 0) + 1
                        end
                    end)
                end
            end
        end
    end
    out._from = nil
    -- (0.105.47, I7b) the fort's dead whose bodies can't be reached (out of the
    -- dwarves' walk, or gone: drowned, in ice, in the caverns) and how many of
    -- them have no memorial slab nor an order for one (lua/ai-welfare.lua)
    pcall(function()
        local sc = reqscript('ai-welfare').dead_scan()
        out.unreachable_dead = sc.total
        out.unreachable_bodies = sc.unreachable
        out.gone_bodies = sc.gone
        out.unreachable_no_slab = sc.without_slab
        out.memorials_wanted = sc.wanting
        out.memorial_orders = sc.ordered
    end)
    return out
end
