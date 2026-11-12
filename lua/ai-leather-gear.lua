-- (item10) Leather armour for the soldiers while metal is short.
--
-- The AI gives a squad the fort's leather uniform until there is metal
-- armour for it (brain/planner_military.py: "leather until the forge has
-- made metal armour and helms for every soldier"), but it only ever ordered
-- metal gear: a leather uniform's entries stayed empty while hides lay
-- tanned. Here, the `leather_gear` report section:
--
--   wanted   slot -> {item kind id (or 'any') -> empty entries}: the soldiers'
--            uniform entries (body, head, pants, gloves, shoes) that ask for
--            leather (material class Leather) and hold nothing
--   given    slot -> entries of that kind holding an item
--   spare    item kind id -> free leather items of it (on DF's unassigned
--            list, nobody's, not held by a unit): what DF can still hand out
--   classes  material class -> entries (every class the uniforms ask for,
--            for the in-game look: is the leather template's class 'Leather'?)
--
-- The brain (brain/planner_leather.py) orders the kinds asked for from the
-- tanned hides at the leatherworks. Read only: nothing here changes the game.
--@ module = true

local U = reqscript('ai-util')

-- uniform category -> the item list it takes from
SLOTS = {{'body', 'ARMOR'}, {'head', 'HELM'}, {'pants', 'PANTS'}, {'gloves', 'GLOVES'}, {'shoes', 'SHOES'}}

local function fort_squads()
    local out = {}
    pcall(function()
        local fort = U.fort_entity()
        for _, sid in ipairs(fort and fort.squads or {}) do
            local sq = df.squad.find(sid)
            if sq then table.insert(out, sq) end
        end
    end)
    return out
end

local function class_of(spec)
    local ok, c = pcall(function() return df.entity_material_category[spec.material_class] end)
    return ok and c or nil
end

local function kind_id(item_type, subtype)
    if subtype == nil or subtype == -1 then return 'any' end
    local ok, def = pcall(dfhack.items.getSubtypeDef, item_type, subtype)
    return (ok and def and def.id) or tostring(subtype)
end

-- Pure-ish: is the item made of leather?
function is_leather(it)
    local ok, yes = pcall(function()
        local mi = dfhack.matinfo.decode(it)
        return mi ~= nil and mi.material ~= nil and mi.material.flags.LEATHER == true
    end)
    return ok and yes or false
end

local SPARE_OK = {forbid = true, dump = true}

function report()
    local out = {wanted = {}, given = {}, spare = {}, classes = {}, soldiers = 0}
    for _, sq in ipairs(fort_squads()) do
        for _, pos in ipairs(sq.positions) do
            if pos.occupant ~= -1 then
                out.soldiers = out.soldiers + 1
                for _, slot in ipairs(SLOTS) do
                    local cat, list = slot[1], slot[2]
                    pcall(function()
                        for _, spec in ipairs(pos.equipment.uniform[df.uniform_category[cat]]) do
                            local cls = class_of(spec) or '?'
                            out.classes[cls] = (out.classes[cls] or 0) + 1
                            if cls == 'Leather' then
                                if #spec.assigned > 0 then
                                    out.given[cat] = (out.given[cat] or 0) + 1
                                else
                                    local id = kind_id(df.item_type[list], spec.item_subtype)
                                    out.wanted[cat] = out.wanted[cat] or {}
                                    out.wanted[cat][id] = (out.wanted[cat][id] or 0) + 1
                                end
                            end
                        end
                    end)
                end
            end
        end
    end
    -- the free leather pieces DF may still hand out (walked only when an entry waits)
    if next(out.wanted) == nil then return out end
    local una
    pcall(function() una = df.global.plotinfo.equipment.items_unassigned end)
    for _, slot in ipairs(SLOTS) do
        local list = slot[2]
        pcall(function()
            local listed
            if una then
                listed = {}
                for _, id in ipairs(una[list]) do listed[id] = true end
            end
            for _, it in ipairs(df.global.world.items.other[list]) do
                if (not listed or listed[it.id]) and is_leather(it) and U.item_free(it, SPARE_OK) then
                    local id = kind_id(df.item_type[list], it:getSubtype())
                    out.spare[id] = (out.spare[id] or 0) + 1
                end
            end
        end)
    end
    return out
end
