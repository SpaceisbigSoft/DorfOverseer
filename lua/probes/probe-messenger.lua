-- probe-messenger: the fort's posts and its civilisation's messenger, as JSON
-- (r10 p2, 13b). READ ONLY: it changes nothing in the game.
--
--     probe-messenger            (in a loaded fort; prints one JSON object)
--
-- What it prints: the site government's (plotinfo.group_id) posts with their
-- flags, duties, requires_population, number, appointed_by and slots (each
-- assignment, its holder); the civilisation's (plotinfo.civ_id) site templates
-- (positions.site), its own posts holding the messenger duty, and its raw
-- [POSITION:...] entries (entity_raw.positions) with SITE / REQUIRES_POPULATION
-- / APPOINTED_BY / NUMBER; the citizens counted; what the AI's ai-nobles reads
-- (messenger_status) when it is installed. See docs/dfhack-notes.md "The
-- messenger (r10)".

local json = require('json')

local function utf(s)
    if type(s) ~= 'string' then return s end
    local ok, r = pcall(dfhack.df2utf, s)
    return ok and r or s
end

local function try(f, ...)
    local ok, v = pcall(f, ...)
    if ok then return v end
    return nil
end

local function set_names(arr, enum)
    local out = {}
    pcall(function()
        for k, v in pairs(arr) do
            if v == true then table.insert(out, tostring(enum[k] or k)) end
        end
    end)
    table.sort(out)
    return out
end

local function flag_names(flags, enum)
    local out = {}
    pcall(function()
        for i = enum._first_item or 0, enum._last_item or -1 do
            local n = enum[i]
            if n then
                local ok, v = pcall(function() return flags[i] end)
                if ok and v == true then table.insert(out, n) end
            end
        end
    end)
    return out
end

local function ints(v)
    local out = {}
    pcall(function() for _, x in ipairs(v) do table.insert(out, tonumber(x)) end end)
    return out
end

local function strs(v)
    local out = {}
    pcall(function() for _, x in ipairs(v) do table.insert(out, utf(x.value or tostring(x))) end end)
    return out
end

local function hf_name(id)
    return try(function()
        local hf = df.historical_figure.find(id)
        return hf and utf(dfhack.translation.translateName(hf.name, false)) or nil
    end)
end

local function position(ent, p)
    local o = {id = p.id, code = p.code, name = try(function() return utf(p.name[0]) end),
               flags = flag_names(p.flags, df.entity_position_flags),
               duties = set_names(p.responsibilities, df.entity_position_responsibility),
               requires_population = try(function() return tonumber(p.requires_population) end),
               number = try(function() return tonumber(p.number) end),
               precedence = try(function() return tonumber(p.precedence) end),
               appointed_by = ints(p.appointed_by), appointed_by_civ = ints(p.appointed_by_civ),
               land_holder = try(function() return tonumber(p.land_holder) end),
               squad_size = try(function() return tonumber(p.squad_size) end)}
    local by = {}
    for _, id in ipairs(o.appointed_by) do
        local code
        pcall(function()
            for _, q in ipairs(ent.positions.own) do if q.id == id then code = q.code end end
        end)
        table.insert(by, code or tostring(id))
    end
    o.appointed_by_codes = by
    return o
end

local function is_messenger(p)
    if try(function() return p.code end) == 'MESSENGER' then return true end
    return try(function() return p.responsibilities[df.entity_position_responsibility.DELIVER_MESSAGES] end) == true
end

local function entity_posts(ent, only_messenger)
    local own, site = {}, {}
    pcall(function()
        for _, p in ipairs(ent.positions.own) do
            if not only_messenger or is_messenger(p) then table.insert(own, position(ent, p)) end
        end
    end)
    pcall(function()
        for _, p in ipairs(ent.positions.site) do
            if not only_messenger or is_messenger(p) then table.insert(site, position(ent, p)) end
        end
    end)
    return own, site
end

local function assignments(ent)
    local out = {}
    pcall(function()
        for _, a in ipairs(ent.positions.assignments) do
            table.insert(out, {id = a.id, position_id = a.position_id, histfig = a.histfig,
                               holder = a.histfig ~= -1 and hf_name(a.histfig) or nil,
                               last_holder = try(function() return a.histfig2 end),
                               flags = flag_names(a.flags, df.entity_position_profile_flags or {}),
                               squad_id = try(function() return a.squad_id end),
                               position_vector_idx = try(function() return a.position_vector_idx end)})
        end
    end)
    return out
end

local function raw_positions(ent)
    local out = {}
    pcall(function()
        for _, r in ipairs(ent.entity_raw.positions) do
            table.insert(out, {code = r.code, flags = flag_names(r.flags, df.entity_position_raw_flags),
                               duties = set_names(r.responsibilities, df.entity_position_responsibility),
                               requires_population = try(function() return tonumber(r.requires_population) end),
                               number = try(function() return tonumber(r.number) end),
                               appointed_by = strs(r.appointed_by_str),
                               replaced_by = try(function() return r.replaced_by_str end),
                               land_holder = try(function() return tonumber(r.land_holder) end)})
        end
    end)
    return out
end

local out = {probe = 'messenger', read_only = true}
if not dfhack.isMapLoaded() or not dfhack.world.isFortressMode() then
    out.error = 'no fort loaded'
    print(json.encode(out))
    return
end
out.date = {year = df.global.cur_year, tick = df.global.cur_year_tick}
local pi = df.global.plotinfo
out.civ_id, out.group_id, out.site_id = pi.civ_id, pi.group_id, pi.site_id
out.citizens = try(function() return #dfhack.units.getCitizens(true) end)
out.citizens_with_residents = try(function() return #dfhack.units.getCitizens(false) end)

local fort = df.historical_entity.find(pi.group_id)
if fort then
    local own = entity_posts(fort, false)
    out.fort = {id = fort.id, type = try(function() return df.historical_entity_type[fort.type] end),
                positions = own, assignments = assignments(fort),
                next_assignment_id = try(function() return fort.positions.next_assignment_id end),
                next_position_id = try(function() return fort.positions.next_position_id end),
                messenger_posts = {}}
    pcall(function()
        for _, p in ipairs(fort.positions.own) do
            if is_messenger(p) then table.insert(out.fort.messenger_posts, p.code) end
        end
    end)
end

local civ = df.historical_entity.find(pi.civ_id)
if civ then
    local own_m = entity_posts(civ, true)
    local _, site_every = entity_posts(civ, false)
    out.civ = {id = civ.id, type = try(function() return df.historical_entity_type[civ.type] end),
               raw = try(function() return civ.entity_raw.code end),
               messenger_own = own_m, site_templates = site_every,
               raw_positions = raw_positions(civ)}
end

-- what the AI reads (nothing written: messenger_status only reads)
pcall(function()
    out.ai = reqscript('ai-nobles').messenger_status(utf)
end)

-- the World screen, if it is open: the messengers DF offers
pcall(function()
    local scr = dfhack.gui.getCurViewscreen(true)
    if df.viewscreen_worldst:is_instance(scr) then
        out.world_screen = {messenger_epp = #scr.messenger_epp,
                            messenger_candidate = scr.focus_site_messenger_candidate}
    end
end)

print(json.encode(out))
