-- probe-ghost-slab: every walking ghost of the fort's race and civ, and each
-- memorial slab engraved for it: the slab's set flags, its container, the
-- building holding it, the building on its tile, its specific refs, and what
-- the bridge's slab count (ai-builder.memorial_slabs) and item_unfree say.
-- READ ONLY.
local json = require('json')
local function txt(s) local ok, r = pcall(dfhack.df2utf, tostring(s or '')) return ok and r or tostring(s or '') end
local out = {ghosts = {}}
local race, civ = df.global.plotinfo.race_id, df.global.plotinfo.civ_id
local counted = {}
pcall(function() for _, it in ipairs(reqscript('ai-builder').memorial_slabs()) do counted[it.id] = true end end)
for _, u in ipairs(df.global.world.units.all) do
    if dfhack.units.isGhost(u) and u.race == race and u.civ_id == civ then
        local g = {id = u.id, hf = u.hist_figure_id, name = txt(dfhack.units.getReadableName(u)), slabs = {}}
        pcall(function() g.kind = df.ghost_type[u.ghost_info.type] end)
        for _, it in ipairs(df.global.world.items.other.SLAB) do
            if it.engraving_type == df.slab_engraving_type.Memorial and it.topic == u.hist_figure_id then
                local s = {id = it.id, flags = {}, counted = counted[it.id] or false}
                for k, v in pairs(it.flags) do if v == true then table.insert(s.flags, k) end end
                pcall(function() local c = dfhack.items.getContainer(it); if c then s.container = df.item_type[c:getType()] end end)
                pcall(function() local b = dfhack.items.getHolderBuilding(it); if b then s.held_by = df.building_type[b:getType()] end end)
                local x, y, z = dfhack.items.getPosition(it)
                s.x, s.y, s.z = x, y, z
                pcall(function() local b = dfhack.buildings.findAtTile(xyz2pos(x, y, z)); if b then s.on = df.building_type[b:getType()] end end)
                pcall(function()
                    s.refs = {}
                    for _, r in ipairs(it.specific_refs) do table.insert(s.refs, tostring(df.specific_ref_type[r.type])) end
                    for _, r in ipairs(it.general_refs) do table.insert(s.refs, tostring(r:getType())) end
                end)
                pcall(function() s.unfree = {reqscript('ai-util').item_unfree(it, {in_job = true})} end)
                table.insert(g.slabs, s)
            end
        end
        table.insert(out.ghosts, g)
    end
end
print(json.encode(out))
