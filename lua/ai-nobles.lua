-- The fort's offices: who holds them, and appointing the best-suited dwarf
-- to a vacant one (manager, bookkeeper, broker, chief medical dwarf, sheriff,
-- captain of the guard).
--
-- A fort needs these without anyone at the keyboard: from 20 citizens DF
-- does a work order only once the manager has validated it, and almost
-- everything the AI makes is a work order. DFHack has no call that appoints,
-- so this writes the same two records DF's nobles screen does (as DFHack's
-- own make-monarch script does for a monarch):
--   * the office's assignment names the dwarf's historical figure as holder;
--   * the figure gets a position link to the fort's government (the entity),
--     pointing at that assignment.
-- Then it reads the appointment back through DFHack's own getNoblePositions;
-- if DFHack doesn't see it, both writes are undone and it says so. A history
-- event is added as the game does (so legends show it); if that fails the
-- appointment stands.
--@module = true

-- A DF name in words (dfhack.TranslateName was renamed in DFHack 50.15).
local function translate(name, english)
    local ok, s = pcall(function() return dfhack.translation.translateName(name, english) end)
    if ok and s then return s end
    ok, s = pcall(function() return dfhack.TranslateName(name, english) end)
    return ok and s or '?'
end

-- office -> the skills that make a good holder (the first counts most)
OFFICES = {
    MANAGER = {'ORGANIZATION', 'RECORD_KEEPING'},
    BOOKKEEPER = {'RECORD_KEEPING', 'ORGANIZATION'},
    BROKER = {'APPRAISAL', 'NEGOTIATION', 'PERSUASION', 'JUDGING_INTENT'},
    CHIEF_MEDICAL_DWARF = {'DIAGNOSE'},
    -- justice: crimes are reported to the sheriff (a fort without one leaves
    -- them unpunished); a dwarf who reads people and can fight
    SHERIFF = {'JUDGING_INTENT', 'OBSERVATION', 'MELEE_COMBAT', 'DISCIPLINE'},
    -- the post a growing fort adds over the sheriff's: leads the fort guard
    CAPTAIN_OF_THE_GUARD = {'JUDGING_INTENT', 'MELEE_COMBAT', 'LEADERSHIP', 'DISCIPLINE'},
}
OFFICE_ORDER = {'MANAGER', 'BOOKKEEPER', 'CHIEF_MEDICAL_DWARF', 'BROKER', 'SHERIFF', 'CAPTAIN_OF_THE_GUARD'}

-- Pure: the best candidate. Each: {id, skills = {level, level...} in the
-- office's order, offices = offices already held, soldier = bool, child =
-- bool}. Dwarves without an office before any with one (one job each), then
-- the skilled (the first skill counts double), never a child, soldiers last; ties to the
-- lower id.
function pick_holder(cands)
    local best, best_score
    for _, c in ipairs(cands) do
        if not c.child then
            local score = 0
            for i, lvl in ipairs(c.skills or {}) do score = score + (i == 1 and 2 or 1) * (lvl or 0) end
            -- a dwarf already holding an office only when nobody else will do
            score = score * 10 - 1000 * (c.offices or 0) - (c.soldier and 15 or 0)
            if best_score == nil or score > best_score or (score == best_score and c.id < best.id) then
                best, best_score = c, score
            end
        end
    end
    return best
end

-- --- the game -----------------------------------------------------------------

local function fort_entity()
    return df.historical_entity.find(df.global.plotinfo.group_id)
end

local function position_of(ent, id)
    for _, p in ipairs(ent.positions.own) do
        if p.id == id then return p end
    end
end

local function skill(u, name)
    local id = df.job_skill[name]
    local soul = u.status.current_soul
    if not soul or not id then return 0 end
    for _, s in ipairs(soul.skills) do
        if s.id == id then return s.rating end
    end
    return 0
end

local function offices_held(u)
    local ok, n = pcall(function()
        local list = dfhack.units.getNoblePositions(u)
        return list and #list or 0
    end)
    return ok and n or 0
end

local function holds(u, code)
    local list = dfhack.units.getNoblePositions(u)
    for _, p in ipairs(list or {}) do
        if p.position.code == code then return true end
    end
    return false
end

-- (0.101.6) DF keeps, besides the assignments, a list per duty of the posts
-- held (assignments_by_type: MANAGE_PRODUCTION, TRADE, HEALTH_MANAGEMENT...),
-- and the game finds its manager, broker, doctor there. Appointments written
-- before 0.101.6 left it empty: the Enxah fort's manager was never seen, so no
-- work order ever started. Returns the held posts missing from it, and the
-- listed posts no longer held; with fix, puts that right.
function sync_held(ent, fix)
    local missing, stale = 0, 0
    for _, a in ipairs(ent.positions.assignments) do
        local p = a.histfig ~= -1 and position_of(ent, a.position_id)
        if p then
            for i, on in ipairs(p.responsibilities) do
                if on then
                    local lst, found = ent.assignments_by_type[i], false
                    for _, b in ipairs(lst) do if b == a then found = true break end end
                    if not found then
                        missing = missing + 1
                        if fix then lst:insert('#', a) end
                    end
                end
            end
        end
    end
    for i, lst in ipairs(ent.assignments_by_type) do
        for k = #lst - 1, 0, -1 do
            if lst[k].histfig == -1 then
                stale = stale + 1
                if fix then lst:erase(k) end
            end
        end
    end
    return missing, stale
end

function sync_offices(dry_run)
    local ent = fort_entity()
    if not ent then return {ok = false, error = 'no fort government (entity) found'} end
    local missing, stale = sync_held(ent, not dry_run)
    if missing + stale == 0 then return {ok = false, rejected = true, error = 'the duty lists are right already'} end
    return {ok = true, added = missing, removed = stale, dry_run = dry_run or nil}
end

-- The fort's offices (read-only): code -> {held_by, vacant assignments,
-- appointable}, plus what the AI may fill.
function survey(txt)
    local ent = fort_entity()
    if not ent then return {error = 'no fort government (entity) found'} end
    local out = {entity = ent.id, offices = {}}
    pcall(function()   -- (0.101.6) held posts the game can't see
        local missing, stale = sync_held(ent, false)
        if missing + stale > 0 then out.unlisted, out.stale_listed = missing, stale end
    end)
    for idx, a in ipairs(ent.positions.assignments) do
        local p = position_of(ent, a.position_id)
        if p then
            local o = out.offices[p.code] or {vacant = 0, held = {}, appointed_by = #p.appointed_by,
                                                ai = OFFICES[p.code] ~= nil}
            if a.histfig == -1 then
                o.vacant = o.vacant + 1
            else
                local hf = df.historical_figure.find(a.histfig)
                table.insert(o.held, hf and (txt or tostring)(translate(hf.name)) or tostring(a.histfig))
            end
            out.offices[p.code] = o
        end
    end
    return out
end

local function candidates(code)
    local wants = OFFICES[code]
    local out = {}
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        if u.hist_figure_id >= 0 then
            local skills = {}
            for i, name in ipairs(wants) do skills[i] = skill(u, name) end
            table.insert(out, {id = u.id, skills = skills, offices = offices_held(u),
                               soldier = u.military.squad_id >= 0,
                               child = dfhack.units.isChild(u) or dfhack.units.isBaby(u)})
        end
    end
    return out
end

local function add_event(ent, hf, pos)
    pcall(function()
        local id = df.global.hist_event_next_id
        df.global.hist_event_next_id = id + 1
        df.global.world.history.events:insert('#', {
            new = df.history_event_add_hf_entity_linkst,
            year = df.global.cur_year, seconds = df.global.cur_year_tick, id = id,
            civ = ent.id, histfig = hf.id, link_type = df.histfig_entity_link_type.POSITION,
            position_id = pos.id, appointer_hfid = -1, promise_to_hfid = -1,
        })
    end)
end

-- Appoint the best-suited citizen to a vacant `code` office.
function appoint(code, dry_run, txt)
    if not OFFICES[code] then
        return {ok = false, rejected = true, error = 'the AI only appoints ' .. table.concat(OFFICE_ORDER, ', ')}
    end
    local ent = fort_entity()
    if not ent then return {ok = false, error = 'no fort government (entity) found'} end
    local assignment, a_idx, pos
    for idx, a in ipairs(ent.positions.assignments) do
        local p = position_of(ent, a.position_id)
        if p and p.code == code then
            if a.histfig ~= -1 then
                return {ok = false, rejected = true, error = code .. ' is already held'}
            end
            assignment, a_idx, pos = a, idx, p
            break
        end
    end
    if not assignment then
        return {ok = false, rejected = true, error = 'the fort has no ' .. code .. ' office yet'}
    end
    local c = pick_holder(candidates(code))
    if not c then return {ok = false, rejected = true, error = 'no grown citizen to appoint'} end
    local u = df.unit.find(c.id)
    local hf = u and df.historical_figure.find(u.hist_figure_id)
    if not hf then return {ok = false, error = 'the chosen dwarf has no historical figure'} end
    local name = (txt or tostring)(dfhack.units.getReadableName(u))
    local out = {ok = true, office = code, name = name, unit_id = u.id, skills = c.skills, dry_run = dry_run or nil}
    if dry_run then return out end
    local ok = write_appointment(ent, assignment, a_idx, pos, u)
    if not ok then
        return {ok = false, office = code, error = 'DFHack did not see the appointment, so it was undone: '
                .. 'appoint the ' .. code:lower():gsub('_', ' ') .. ' in the nobles screen'}
    end
    return out
end

-- Undo an appointment written here.
function undo_appointment(assignment, hf)
    assignment.histfig = -1
    for i = #hf.entity_links - 1, 0, -1 do
        local l = hf.entity_links[i]
        if df.histfig_entity_link_positionst:is_instance(l) and l.assignment_id == assignment.id then
            hf.entity_links:erase(i)
            pcall(function() l:delete() end)
        end
    end
end

-- The two records DF's nobles screen writes, read back through DFHack (and
-- undone if it doesn't see them); then the history event. Returns true/false.
function write_appointment(ent, assignment, a_idx, pos, u)
    local hf = df.historical_figure.find(u.hist_figure_id)
    if not hf then return false end
    assignment.histfig = hf.id
    hf.entity_links:insert('#', {new = df.histfig_entity_link_positionst, entity_id = ent.id,
                                 link_strength = 100, assignment_id = assignment.id,
                                 assignment_vector_idx = a_idx, start_year = df.global.cur_year})
    if not holds(u, pos.code) then
        undo_appointment(assignment, hf)
        return false
    end
    pcall(function() assignment.histfig2 = hf.id end)   -- DF's "last holder"
    pcall(sync_held, ent, true)                          -- (0.101.6) the game's duty lists
    add_event(ent, hf, pos)
    return true
end

-- --- rooms the nobles want ------------------------------------------------------

-- A noble's office may ask for rooms of its own (DF's position raws:
-- required office, bedroom, dining room, tomb). Without one the noble is
-- unhappy and makes demands. The AI gives each such noble a free room of
-- the kind (an office or bedroom of a suites level it built, a tomb), and
-- builds a suites level when there is none free.
ROOM_ZONES = {office = 'Office', bedroom = 'Bedroom', dining = 'DiningHall', tomb = 'Tomb'}
local REQUIRED = {office = 'required_office', bedroom = 'required_bedroom', dining = 'required_dining',
                  tomb = 'required_tomb'}

local function owns(u, zone_type)
    for _, z in ipairs(u.owned_buildings) do
        local ok, t = pcall(function() return df.civzone_type[z.type] end)
        if ok and t == zone_type then return true end
    end
    return false
end

-- (0.100.1, review) a dining hall given to a noble is theirs alone: the
-- fort's shared one is never given (one unowned hall is always kept, and of
-- the others the smallest goes)
local function free_zones(zone_type)
    local list = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.Civzone and df.civzone_type[b.type] == zone_type
                and b.assigned_unit_id == -1 then
            table.insert(list, b)
        end
    end
    return list
end

local function area(b)
    local ok, a = pcall(function() return (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1) end)
    return ok and a or math.huge
end

local function free_zone(zone_type)
    local list = free_zones(zone_type)
    if zone_type == 'DiningHall' then
        if #list < 2 then return nil end
        table.sort(list, function(a, b) return area(a) < area(b) end)
    end
    return list[1]
end

-- {{unit_id, name, office, needs = {'office', 'bedroom'...}}, ...} and the
-- free zones of each kind.
function rooms_survey(txt)
    local out, free = {}, {}
    for kind, zt in pairs(ROOM_ZONES) do
        local n = #free_zones(zt)
        if zt == 'DiningHall' then n = math.max(0, n - 1) end     -- the shared hall isn't given
        free[kind] = n
    end
    for _, u in ipairs(dfhack.units.getCitizens(true)) do
        local list = dfhack.units.getNoblePositions(u)
        if list then
            local needs, office = {}, nil
            for _, np in ipairs(list) do
                for kind, field in pairs(REQUIRED) do
                    local ok, v = pcall(function() return np.position[field] end)
                    if ok and v and v > 0 and not owns(u, ROOM_ZONES[kind]) then
                        needs[kind] = true
                        office = office or np.position.code
                    end
                end
            end
            local kinds = {}
            for k in pairs(needs) do table.insert(kinds, k) end
            table.sort(kinds)
            if #kinds > 0 then
                table.insert(out, {unit_id = u.id, name = (txt or tostring)(dfhack.units.getReadableName(u)),
                                   office = office, needs = kinds})
            end
        end
    end
    return {nobles = out, free = free}
end

-- Give the noble a free room of the kind.
function give_room(unit_id, kind, dry_run, txt)
    local zt = ROOM_ZONES[kind]
    if not zt then return {ok = false, rejected = true, error = 'unknown room kind: ' .. tostring(kind)} end
    local u = df.unit.find(unit_id)
    if not u then return {ok = false, rejected = true, error = 'no such dwarf'} end
    if owns(u, zt) then return {ok = false, rejected = true, error = 'already has one'} end
    local z = free_zone(zt)
    if not z then return {ok = false, rejected = true, error = 'no free ' .. kind .. ' to give'} end
    local name = (txt or tostring)(dfhack.units.getReadableName(u))
    if dry_run then return {ok = true, dry_run = true, name = name, kind = kind, zone = z.id} end
    if not dfhack.buildings.setOwner(z, u) or not owns(u, zt) then
        return {ok = false, error = 'the game did not give ' .. name .. ' the ' .. kind}
    end
    return {ok = true, name = name, kind = kind, zone = z.id}
end
