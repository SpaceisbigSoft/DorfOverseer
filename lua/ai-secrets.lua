-- (0.105.95) The secrets of life and death: who could become a necromancer.
--
-- Live 23 Nov: C and F each hold the artifact slab "Kuluruxen, Nightsearch"
-- (engraving type Secrets). What the game does (DF wiki, Necromancer, Slab):
--   * a slab can't be read in fortress mode; only a book or scroll whose
--     written content carries the secret (an INTERACTION reference) makes a
--     reader a necromancer: immortal, raising the dead;
--   * the corpses a citizen necromancer raises are hostile to all life,
--     except a dead citizen raised as an intelligent undead, who stays one.
--
--   report()            the `secrets` part of the artifacts section: the
--                       secrets slabs (kept: harmless here), the secrets books
--                       and scrolls (forbidden or not, in a building), the
--                       necromancers and undead citizens on the map.
--   forbid(ids, on, dry)  each listed item, re-checked to be a secrets book or
--                       scroll, forbidden (on) or let go (not on): a forbidden
--                       book is never taken to be read.
--@module = true

local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
local function is(f, u) local ok, r = pcall(f, u) return ok and r or false end

local function interaction_ref(wc)
    local ok, yes = pcall(function()
        local want = df.general_ref_type.INTERACTION
        for _, ref in ipairs(wc.refs) do
            if ref:getType() == want then return true end
        end
        return false
    end)
    return ok and yes or false
end

-- a book or scroll (any item with written pages) that carries the secret
function secrets_item(it)
    local ok, yes = pcall(function()
        for _, imp in ipairs(it.improvements) do
            local t = imp:getType()
            if t == df.improvement_type.WRITING or t == df.improvement_type.PAGES then
                for _, cid in ipairs(imp.contents or {}) do
                    local wc = df.written_content.find(cid)
                    if wc and interaction_ref(wc) then return true end
                end
            end
        end
        return false
    end)
    return ok and yes or false
end

local function necromancer(u)
    local ok, yes = pcall(function()
        local hf = df.historical_figure.find(u.hist_figure_id)
        return hf ~= nil and hf.info ~= nil and hf.info.known_info ~= nil
            and hf.info.known_info.known_secrets ~= nil and #hf.info.known_info.known_secrets > 0
    end)
    return ok and yes or false
end

function report()
    local out = {slabs = 0, books = {}, necromancers = {}, undead_citizens = 0}
    pcall(function()
        local want = df.slab_engraving_type.Secrets
        for _, it in ipairs(df.global.world.items.other.SLAB) do
            if want ~= nil and it.engraving_type == want then out.slabs = out.slabs + 1 end
        end
    end)
    for _, k in ipairs({'BOOK', 'TOOL'}) do
        pcall(function()
            for _, it in ipairs(df.global.world.items.other[k]) do
                if #out.books < 20 and secrets_item(it) then
                    local row = {id = it.id, forbidden = it.flags.forbid or nil, in_building = it.flags.in_building or nil}
                    pcall(function() row.name = txt(dfhack.items.getReadableDescription(it)) end)
                    table.insert(out.books, row)
                end
            end
        end)
    end
    pcall(function()
        for _, u in ipairs(df.global.world.units.active) do
            if not is(dfhack.units.isDead, u) then
                local cit = is(dfhack.units.isCitizen, u)
                if cit and is(dfhack.units.isUndead, u) then out.undead_citizens = out.undead_citizens + 1 end
                if #out.necromancers < 10 and necromancer(u) then
                    table.insert(out.necromancers, {id = u.id, name = txt(dfhack.units.getReadableName(u)),
                                                    citizen = cit or nil})
                end
            end
        end
    end)
    return out
end

function forbid(ids, on, dry_run)
    local out = {ok = true, changed = {}, skipped = {}, dry_run = dry_run or nil}
    for _, id in ipairs(ids or {}) do
        local it = df.item.find(tonumber(id) or -1)
        if not it or not secrets_item(it) then
            table.insert(out.skipped, id)
        elseif it.flags.forbid ~= on then
            if not dry_run then it.flags.forbid = on end
            table.insert(out.changed, it.id)
        end
    end
    if #out.changed == 0 then
        return {ok = false, rejected = true, error = on and 'no secrets book or scroll left to forbid'
                or 'no forbidden secrets book or scroll to let go', skipped = out.skipped}
    end
    return out
end
