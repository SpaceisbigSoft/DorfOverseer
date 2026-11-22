-- probe-petitions: read-only. Prints one line of JSON about the fort's
-- residency and citizenship petitions (r10 p1, Phase 12b): DF's petition
-- standing orders (by DFHack's names and by DF's own symbol names, which the
-- win64 symbol tables use), the petitions waiting (plotinfo.petitions), each
-- one's agreement (flags, details, parties) and its applicant (histfig entity
-- links, unit flags, DFHack's citizen/resident tests), the residency and
-- citizenship agreements for this site no longer waiting (what DF left after
-- an answer: compare an approved one with a denied one), and DF's petitions
-- screen. Changes nothing: no setAddress, no writes.
--
-- Run: probe-petitions   (the runner's `probe` job, or the DFHack console)

local json = require('json')

local function try(f, ...)
    local ok, v = pcall(f, ...)
    if ok then return v end
    return nil
end

local KINDS = {
    performer = {'standing_orders_petition_resident_performer', 'standingorder_petition_resident_performer'},
    scholar = {'standing_orders_petition_resident_scholar', 'standingorder_petition_resident_scholar'},
    monster_hunter = {'standing_orders_petition_resident_monster_hunter', 'standingorder_petition_resident_monster_hunter'},
    mercenary = {'standing_orders_petition_resident_mercenary', 'standingorder_petition_resident_mercenary'},
    sanctuary = {'standing_orders_petition_resident_sanctuary', 'standingorder_petition_resident_sanctuary'},
    citizenship = {'standing_orders_petition_citizenship', 'standingorder_petition_citizenship'},
}

local function hex(a) return a and string.format('0x%x', a) or nil end

local function orders()
    local out = {anchor = hex(try(dfhack.internal.getAddress, 'standing_orders_auto_collect_webs'))}
    for k, names in pairs(KINDS) do
        out[k] = {
            dfhack_name = hex(try(dfhack.internal.getAddress, names[1])),
            df_name = hex(try(dfhack.internal.getAddress, names[2])),
            value = try(function() return df.global[names[1]] end),   -- nil: not bound (yet)
        }
    end
    return out
end

local function flag_list(fl, names)
    local o = {}
    for _, n in ipairs(names) do
        if try(function() return fl[n] end) then table.insert(o, n) end
    end
    return o
end

local function unit_facts(u)
    if not u then return nil end
    return {
        id = u.id, civ_id = u.civ_id, race = try(function() return df.creature_raw.find(u.race).creature_id end),
        name = try(function() return dfhack.df2utf(dfhack.units.getReadableName(u)) end),
        profession = try(function() return df.profession[u.profession] end),
        active = try(dfhack.units.isActive, u), dead = try(dfhack.units.isDead, u),
        citizen = try(dfhack.units.isCitizen, u), resident = try(dfhack.units.isResident, u),
        visiting = try(dfhack.units.isVisiting, u), own_group = try(dfhack.units.isOwnGroup, u),
        own_civ = try(dfhack.units.isOwnCiv, u),
        flags1 = flag_list(u.flags1, {'merchant', 'diplomat', 'forest', 'invader_origin', 'active_invader', 'tame'}),
        flags2 = flag_list(u.flags2, {'resident', 'visitor', 'visitor_uninvited', 'underworld'}),
        flags3 = flag_list(u.flags3, {'guest'}),
    }
end

local function hf_facts(hfid)
    local hf = hfid and df.historical_figure.find(hfid)
    if not hf then return {id = hfid} end
    local o = {id = hf.id, civ_id = hf.civ_id, died_year = hf.died_year, unit_id = hf.unit_id, links = {}}
    for _, l in ipairs(hf.entity_links) do
        local e = df.historical_entity.find(l.entity_id)
        table.insert(o.links, {type = try(function() return df.histfig_entity_link_type[l:getType()] end),
                               entity = l.entity_id, strength = l.link_strength,
                               entity_type = e and df.historical_entity_type[e.type] or nil})
    end
    pcall(function()
        o.whereabouts = {state = df.whereabouts_type[hf.info.whereabouts.state], site = hf.info.whereabouts.site_id}
    end)
    o.unit = unit_facts(df.unit.find(hf.unit_id))
    return o
end

local function agreement_facts(a)
    local o = {id = a.id, flags = flag_list(a.flags, {'petition_not_accepted', 'convicted_accepted'}),
               parties = {}, details = {}}
    for _, p in ipairs(a.parties) do
        local hfs, ens = {}, {}
        for _, h in ipairs(p.histfig_ids) do table.insert(hfs, h) end
        for _, e in ipairs(p.entity_ids) do table.insert(ens, e) end
        table.insert(o.parties, {id = p.id, histfigs = hfs, entities = ens})
    end
    for _, d in ipairs(a.details) do
        local kind = df.agreement_details_type[d.type] or tostring(d.type)
        local e = {id = d.id, type = kind, year = d.year, tick = d.year_tick}
        pcall(function()
            local data = d.data[kind]
            for _, f in ipairs({'reason', 'applicant', 'government', 'site', 'end_year', 'end_season_tick'}) do
                local v = try(function() return data[f] end)
                if v ~= nil then e[f] = (f == 'reason') and (df.history_event_reason[v] or v) or v end
            end
            for _, p in ipairs(a.parties) do
                if p.id == data.applicant and #p.histfig_ids > 0 then e.applicant_hf = hf_facts(p.histfig_ids[0]) end
            end
        end)
        table.insert(o.details, e)
    end
    return o
end

local out = {probe = 'petitions', year = df.global.cur_year, tick = df.global.cur_year_tick}
out.orders = try(orders)
pcall(function()
    local pi = df.global.plotinfo
    out.site_id, out.civ_id, out.group_id = pi.site_id, pi.civ_id, pi.group_id
end)
pcall(function()
    local s = df.global.game.main_interface.petitions
    out.screen = {open = s.open, have_responsible_person = s.have_responsible_person, shown = #s.agreement_id,
                  selected = s.selected_agreement_id}
end)
pcall(function() out.focus = dfhack.gui.getFocusStrings(dfhack.gui.getDFViewscreen(true)) end)
out.pending, out.answered = {}, {}
local waiting = {}
pcall(function()
    for _, id in ipairs(df.global.plotinfo.petitions) do
        waiting[id] = true
        local a = df.agreement.find(id)
        if a then table.insert(out.pending, agreement_facts(a)) end
    end
end)
-- residency and citizenship agreements for this site, not waiting: the newest 40
pcall(function()
    local site = df.global.plotinfo.site_id
    local all = df.global.world.agreements.all
    for i = #all - 1, 0, -1 do
        local a = all[i]
        local d = #a.details > 0 and a.details[0] or nil
        local kind = d and df.agreement_details_type[d.type]
        if (kind == 'Residency' or kind == 'Citizenship') and not waiting[a.id]
                and try(function() return d.data[kind].site end) == site then
            table.insert(out.answered, agreement_facts(a))
            if #out.answered >= 40 then break end
        end
    end
end)
out.pending_n, out.answered_n = #out.pending, #out.answered
print(json.encode(out))
