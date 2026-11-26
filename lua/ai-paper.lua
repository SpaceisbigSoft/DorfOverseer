-- (item9) Paper, scrolls and codices for the library. The coverage audit's
-- "should" list: the library had 0 books and 5 of 10 sheets of paper, and
-- the kiln's parchment chain (brain/planner_industry.py _kiln_rules) needs
-- limestone and fresh hides; "paper from plants still open".
--
-- DF's writing materials (vanilla reaction_other.txt; the codes below are
-- the ones remembered, NOT read from the raws here, so every one is looked
-- up in the game's own reactions, and a reaction of the right shape is used
-- when the code differs):
--
--   slurry   a plant (one with a paper-slurry material product) milled into
--            slurry at a quern or millstone       (MAKE_SLURRY_FROM_PLANT?)
--   press    the slurry pressed into a sheet of paper at a screw press
--                                                  (PRESS_PLANT_PAPER?)
--   papyrus  papyrus sedge made straight into a sheet at the farmer's (MAKE_SHEET_FROM_PLANT)
--   scroll   a sheet and scroll rollers rolled into a blank scroll
--                                                  (MAKE_SCROLL?)
--   codex    a quire and a book binding bound into a codex  (BIND_BOOK?)
--
-- (sheets into blank quires, MAKE_QUIRE, are the kiln chain's, already
-- ordered by the planner.)
--
--   reaction(kind)   the game's reaction code for a kind, or nil (cached a
--                    world)
--   report()         the `paper` section: each kind's reaction (code, the
--                    workshops it is made at, how many of its main input are
--                    free), the quires, scrolls and codices (blank and
--                    written), the scroll rollers and book bindings free.
--   sheets_held(out) (item5) the free sheets stuck in a workshop (none
--                    of the piles takes sheets) and the piles that do
--   orders_open()    (fix6) a work order of a paper step still in the
--                    manager's list: the bridge keeps no cached copy of the
--                    section meanwhile, so the report after the order is done
--                    counts what it used (not a day-old copy that orders the
--                    step again)
--@ module = true

KINDS = {
    slurry = {codes = {'MAKE_SLURRY_FROM_PLANT', 'MAKE_PAPER_SLURRY'}, words = {'SLURRY', 'PULP'}, counts = true},
    press = {codes = {'PRESS_PLANT_PAPER', 'PRESS_PAPER'}, words = {'PAPER'}, counts = true},
    papyrus = {codes = {'MAKE_SHEET_FROM_PLANT', 'MAKE_PAPYRUS', 'PRESS_PAPYRUS'}, words = {'SHEET', 'PAPYRUS'}, counts = true},   -- (merge: vanilla 53.17's code checked in reaction_other.txt)
    scroll = {codes = {'MAKE_SCROLL'}, words = {'SCROLL'}},
    codex = {codes = {'BIND_BOOK', 'MAKE_CODEX', 'BIND_CODEX'}, words = {'BOOK', 'CODEX'}},
}
KIND_ORDER = {'slurry', 'press', 'papyrus', 'scroll', 'codex'}
CUSTOM_NAMES = {SCREW_PRESS = 'ScrewPress', SOAP_MAKER = 'SoapMaker', SOAP_MAKERS = 'SoapMaker'}
ITEMS_MAX = 40000       -- input items looked at a report at most (each list)

-- the reaction codes found, by the world's save folder and kind
CACHE = CACHE or {}
-- (r1g9) the world by its name (ai-util world_name), not the save folder
-- DF's seasonal autosave renames
local function world_key()
    local okw, world = pcall(function() return reqscript('ai-util').world_name() end)
    if not okw or type(world) ~= 'string' then
        okw, world = pcall(function() return df.global.world.cur_savegame.save_dir end)
    end
    return okw and world ~= nil and tostring(world) or ''
end
if dfhack and dfhack.onStateChange then
    dfhack.onStateChange['ai-paper'] = function(sc)
        if sc == SC_WORLD_UNLOADED or sc == SC_MAP_UNLOADED then CACHE = {} end
    end
end

local function item_type_name(t)
    local ok, n = pcall(function() return df.item_type[t] end)
    return ok and n or nil
end

local function reagent_types(rx)
    local out = {}
    pcall(function()
        for _, rg in ipairs(rx.reagents) do
            local okt, t = pcall(function() return rg.item_type end)
            table.insert(out, okt and item_type_name(t) or '?')
        end
    end)
    return out
end

-- the product items' types, and the TOOL ones' subtype ids
local function product_types(rx)
    local out = {}
    pcall(function()
        for _, pr in ipairs(rx.products) do
            local okt, t = pcall(function() return pr.item_type end)
            local name = okt and item_type_name(t) or nil
            if name == 'TOOL' then
                local oks, id = pcall(function()
                    return dfhack.items.getSubtypeDef(df.item_type.TOOL, pr.item_subtype).id
                end)
                if oks and id then name = 'TOOL:' .. id end
            end
            if name then table.insert(out, name) end
        end
    end)
    return out
end

local function has(list, v)
    for _, x in ipairs(list) do if x == v then return true end end
    return false
end

local function text_of(rx)
    local okc, code = pcall(function() return rx.code end)
    local okn, name = pcall(function() return rx.name end)
    return ((okc and tostring(code) or '') .. ' ' .. (okn and tostring(name) or '')):upper()
end

local function says(rx, words)
    local text = text_of(rx)
    for _, w in ipairs(words) do if text:find(w, 1, true) then return true end end
    return false
end

-- a reagent's material product wanted (HAS_MATERIAL_REACTION_PRODUCT), '' if none
local function wanted_product(rg)
    local ok, v = pcall(function() return rg.has_material_reaction_product end)
    return ok and v ~= nil and tostring(v) or ''
end

-- (the reaction's shape, for a game whose code differs from the remembered one)
SHAPES = {
    slurry = function(rx, ins, outs)
        return has(ins, 'PLANT') and not has(outs, 'SHEET') and says(rx, KINDS.slurry.words)
    end,
    press = function(rx, ins, outs)
        return has(outs, 'SHEET') and not has(ins, 'PLANT') and not has(ins, 'CORPSEPIECE')
            and not says(rx, {'PARCHMENT', 'PAPYRUS'})
    end,
    papyrus = function(rx, ins, outs)
        return has(outs, 'SHEET') and has(ins, 'PLANT')
    end,
    scroll = function(rx, ins, outs)
        return has(outs, 'TOOL:ITEM_TOOL_SCROLL')
    end,
    codex = function(rx, ins, outs)
        return has(outs, 'BOOK')
    end,
}

local function reactions()
    local ok, list = pcall(function() return df.global.world.raws.reactions.reactions end)
    return ok and list or {}
end

-- The game's reaction for a paper kind: a remembered code the game has, else
-- the first reaction of that shape. The reaction itself, or nil.
function find_reaction(kind)
    local k = KINDS[kind]
    if not k then return nil end
    local all = reactions()
    for _, code in ipairs(k.codes) do
        for _, rx in ipairs(all) do
            local okc, c = pcall(function() return rx.code end)
            if okc and c == code then return rx end
        end
    end
    for _, rx in ipairs(all) do
        local okm, match = pcall(SHAPES[kind], rx, reagent_types(rx), product_types(rx))
        if okm and match then return rx end
    end
    return nil
end

-- its code, cached a world (false: none)
function reaction(kind)
    local key = world_key() .. '|' .. tostring(kind)
    if CACHE[key] == nil then
        local rx = find_reaction(kind)
        local ok, code = pcall(function() return rx and rx.code end)
        CACHE[key] = (ok and code) or false
    end
    return CACHE[key] or nil
end

-- (fix6) the tools a paper step's order makes (wooden_scroll_rollers, wooden_book_binding)
PAPER_TOOLS = {ITEM_TOOL_SCROLL_ROLLERS = true, ITEM_TOOL_BOOK_BINDING = true}

function orders_open()
    local codes = {}
    for _, kind in ipairs(KIND_ORDER) do
        local c = reaction(kind)
        if c then codes[c] = true end
    end
    local open = false
    pcall(function()
        for _, o in ipairs(df.global.world.manager_orders.all) do
            local rn = o.reaction_name
            if rn and rn ~= '' and codes[rn] then open = true; return end
            if o.item_subtype and o.item_subtype >= 0 then
                local okd, def = pcall(dfhack.items.getSubtypeDef, df.item_type.TOOL, o.item_subtype)
                if okd and def and PAPER_TOOLS[def.id] and df.job_type[o.job_type] == 'MakeTool' then
                    open = true; return
                end
            end
        end
    end)
    return open
end

-- the workshops a reaction is made at, by the brain's names (Quern,
-- Millstone, Farmers, Craftsdwarfs, ScrewPress, Custom:<code>)
function reaction_shops(rx)
    local out = {}
    pcall(function()
        local b = rx.building
        for i, t in ipairs(b.type) do
            local sub = b.subtype[i]
            local tn = df.building_type[t]
            local name
            if tn == 'Workshop' then
                name = df.workshop_type[sub]
                if name == 'Custom' then
                    local okd, code = pcall(function() return df.building_def.find(b.custom[i]).code end)
                    name = okd and code and (CUSTOM_NAMES[code] or ('Custom:' .. code)) or nil
                end
            elseif tn == 'Furnace' then
                name = df.furnace_type[sub]
            end
            if name and not has(out, name) then table.insert(out, name) end
        end
    end)
    return out
end

-- the reaction's main reagent: the one wanting a material product, else the first
local function main_reagent(rx)
    local first
    pcall(function()
        for _, rg in ipairs(rx.reagents) do
            first = first or rg
            if wanted_product(rg) ~= '' then first = rg; error('found') end
        end
    end)
    return first
end

local function free(it)
    local f = it.flags
    return not (f.forbid or f.garbage_collect or f.rotten or f.trader or f.removed or f.in_job or f.dump)
end

-- (R2 h3) a reagent's reaction class wanted (REACTION_CLASS), '' if none
local function wanted_class(rg)
    local ok, v = pcall(function() return rg.reaction_class end)
    return ok and v ~= nil and tostring(v) or ''
end

-- rclass (R2 h3): the reagent's reaction class, matched against the material's
-- own classes when it names one (a press reagent of REACTION_CLASS form counted
-- nothing before: the six forts' press inputs stayed 0)
local function material_has(it, want, words, seen, rclass)
    local okk, key = pcall(function() return tostring(it:getMaterial()) .. ':' .. tostring(it:getMaterialIndex()) end)
    key = okk and key or nil
    if key and seen[key] ~= nil then return seen[key] end
    local found = false
    if rclass and rclass ~= '' then
        pcall(function()
            local mi = dfhack.matinfo.decode(it)
            for _, c in ipairs(mi.material.reaction_class) do
                if tostring(c.value or c) == rclass then found = true end
            end
        end)
        if found then
            if key then seen[key] = true end
            return true
        end
    end
    pcall(function()
        local mi = dfhack.matinfo.decode(it)
        for _, p in ipairs(mi.material.reaction_product.id) do
            local v = tostring(p.value or p)
            if want ~= '' then
                if v == want then found = true end
            else
                for _, w in ipairs(words) do if v:find(w, 1, true) then found = true end end
            end
        end
    end)
    if key then seen[key] = found end
    return found
end

-- how many of a reaction's main input are free (stack sizes summed)
function count_inputs(rx, kind)
    local rg = main_reagent(rx)
    if not rg then return 0 end
    local okt, t = pcall(function() return rg.item_type end)
    local list_name = okt and item_type_name(t) or nil
    if not list_name or list_name == 'NONE' then return 0 end
    local want = wanted_product(rg)
    local rclass = want == '' and wanted_class(rg) or ''
    local words = KINDS[kind] and KINDS[kind].words or {}
    local n, looked, seen = 0, 0, {}
    pcall(function()
        for _, it in ipairs(df.global.world.items.other[list_name]) do
            looked = looked + 1
            if looked > ITEMS_MAX then break end
            if free(it) and material_has(it, want, words, seen, rclass) then
                local oks, sz = pcall(function() return it:getStackSize() end)
                n = n + (oks and sz or 1)
            end
        end
    end)
    return n
end

local function written(it)
    local w = false
    pcall(function()
        for _, imp in ipairs(it.improvements) do
            if imp:getType() == df.improvement_type.WRITING then w = true end
        end
    end)
    return w
end

function report()
    local out = {reactions = {}, quires_blank = 0, quires_written = 0, scrolls_blank = 0, scrolls_written = 0,
                 codices = 0, rollers = 0, bindings = 0, sheets = 0, thread = 0}
    for _, kind in ipairs(KIND_ORDER) do
        local rx = find_reaction(kind)
        local e = {code = false}
        if rx then
            pcall(function() e.code = rx.code end)
            e.shops = reaction_shops(rx)
            if KINDS[kind].counts then e.inputs = count_inputs(rx, kind) end
        end
        out.reactions[kind] = e
    end
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.TOOL) do
            if free(it) then
                local id = it.subtype and it.subtype.id
                if id == 'ITEM_TOOL_QUIRE' then
                    if written(it) then out.quires_written = out.quires_written + 1
                    else out.quires_blank = out.quires_blank + 1 end
                elseif id == 'ITEM_TOOL_SCROLL' then
                    if written(it) then out.scrolls_written = out.scrolls_written + 1
                    else out.scrolls_blank = out.scrolls_blank + 1 end
                elseif id == 'ITEM_TOOL_SCROLL_ROLLERS' then out.rollers = out.rollers + 1
                elseif id == 'ITEM_TOOL_BOOK_BINDING' then out.bindings = out.bindings + 1
                end
            end
        end
    end)
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.BOOK) do
            out.codices = out.codices + 1
        end
    end)
    -- (merge) BIND_BOOK takes a quire, a binding and thread (vanilla 53.17): free thread counted
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.THREAD) do
            if free(it) then out.thread = out.thread + 1 end
        end
    end)
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.SHEET) do
            if free(it) then
                local oks, sz = pcall(function() return it:getStackSize() end)
                out.sheets = out.sheets + (oks and sz or 1)
            end
        end
    end)
    pcall(function() sheets_held(out) end)
    pcall(function() out.writing = writing() end)
    return out
end

-- (item5) Where the free sheets lie. A sheet pressed at the screw press (or
-- made at the farmer's or the tanner's) stays in that workshop, held by it,
-- until a stockpile that takes sheets calls for it, and the craftsdwarf's
-- quire and scroll jobs don't fetch it from there (live, fort A 26 Nov: 2
-- sheets in the screw press, 65 piles and none taking sheets, every
-- make_quire order stuck at "2 left" for 28 days). out.sheets_in_shops: the
-- free sheets held by a workshop other than a craftsdwarf's (where they are
-- used), out.sheets_shop / sheets_shop_id: the workshop holding most of
-- them, out.sheet_piles: the stockpiles taking sheets (DF 53's own group).
SHEET_USERS = {Craftsdwarfs = true}

function shop_name(b)
    local okn, name = pcall(function() return df.workshop_type[b.type] end)
    name = okn and name or nil
    if name == 'Custom' then
        local okd, code = pcall(function() return df.building_def.find(b.custom_type).code end)
        name = okd and code and (CUSTOM_NAMES[code] or ('Custom:' .. code)) or name
    end
    return name
end

function sheets_held(out)
    out.sheets_in_shops, out.sheet_piles = 0, 0
    local by, names = {}, {}
    for _, it in ipairs(df.global.world.items.other.SHEET) do
        if free(it) then
            local okh, b = pcall(dfhack.items.getHolderBuilding, it)
            if okh and b and b:getType() == df.building_type.Workshop then
                local name = shop_name(b)
                if not SHEET_USERS[name] then
                    local oks, sz = pcall(function() return it:getStackSize() end)
                    local n = oks and sz or 1
                    out.sheets_in_shops = out.sheets_in_shops + n
                    by[b.id] = (by[b.id] or 0) + n
                    names[b.id] = name
                end
            end
        end
    end
    local best
    for id, n in pairs(by) do
        if not best or n > by[best] or (n == by[best] and id < best) then best = id end
    end
    if best then out.sheets_shop, out.sheets_shop_id = names[best] or '?', best end
    pcall(function()
        for _, sp in ipairs(df.global.world.buildings.other.STOCKPILE) do
            local okf, on = pcall(function() return sp.settings.flags.sheet end)
            if okf and on then out.sheet_piles = out.sheet_piles + 1 end
        end
    end)
end

-- (R29 W5) the fort's written works, so the books can be watched: `items`
-- every written item held (codices, written quires and scrolls; no trader's),
-- `works` the distinct works among them, `copies` the items that are no
-- artifact (a scribe's copy: the originals are artifacts), `own` the works
-- whose author is one of the fort's citizens (written here; the 25 Nov run's
-- 37 codices were all old artifacts), `scholars` the fort's scholar posts
-- filled. Live (probe 25 Nov 21:33): A 7 codices and 1 copy, B 11 and 11,
-- E 11 and 10, D none; own 0 everywhere.
local function contents_of(it)
    local ids = {}
    pcall(function()
        for _, imp in ipairs(it.improvements) do
            local ty = imp:getType()
            if ty == df.improvement_type.WRITING or ty == df.improvement_type.PAGES then
                for _, w in ipairs(imp.contents) do table.insert(ids, w) end
            end
        end
    end)
    return ids
end

function writing()
    local w = {items = 0, works = 0, copies = 0, own = 0, scholars = 0}
    local seen, citizen_hf = {}, {}
    pcall(function()
        for _, u in ipairs(dfhack.units.getCitizens()) do
            if u.hist_figure_id ~= -1 then citizen_hf[u.hist_figure_id] = true end
            for _, o in ipairs(u.occupations) do
                if df.occupation_type[o.type] == 'SCHOLAR' then w.scholars = w.scholars + 1 end
            end
        end
    end)
    local function look(it)
        if it.flags.trader or it.flags.garbage_collect then return end
        local ids = contents_of(it)
        if #ids == 0 then return end
        w.items = w.items + 1
        if not it.flags.artifact then w.copies = w.copies + 1 end
        for _, id in ipairs(ids) do
            if not seen[id] then
                seen[id] = true
                w.works = w.works + 1
                pcall(function()
                    local wc = df.written_content.find(id)
                    if wc and citizen_hf[wc.author] then w.own = w.own + 1 end
                end)
            end
        end
    end
    pcall(function() for _, it in ipairs(df.global.world.items.other.BOOK) do look(it) end end)
    pcall(function()
        for _, it in ipairs(df.global.world.items.other.TOOL) do
            local id = it.subtype and it.subtype.id
            if id == 'ITEM_TOOL_QUIRE' or id == 'ITEM_TOOL_SCROLL' then look(it) end
        end
    end)
    return w
end
