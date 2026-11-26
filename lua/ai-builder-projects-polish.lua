-- ai-builder-projects-polish: polish: idle hands smooth, then engrave, a finished level dug plain.
--
-- (r8) A part of ai-builder, not a script of its own: cut from ai-builder-projects.lua
-- (which had grown to 164 KB) at a section boundary, the code as it stood. ai-builder.lua
-- loads it into its own environment right after the part before it (PARTS), so every
-- name here is reqscript('ai-builder').name and the hub's helpers are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-projects-polish'] = '0.105.128'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

---------------------------------------------------------------------------
-- Polish: idle hands smooth, then engrave, a finished level dug plain (a
-- young fort builds plain; region2 then stood 40% idle for a year with
-- every level rough). Smoothing and engraving make the rooms nicer to live
-- in and add to the fort's wealth (migrants follow wealth). One level at a
-- time, the rooms dwarves use most first; engraving two weeks after the
-- smoothing was asked for (only smooth stone takes an engraving).
---------------------------------------------------------------------------

POLISH_ORDER = {dining = 1, tavern = 2, suites = 3, hospital = 4, temple = 5, library = 6, bedrooms = 7,
                barracks = 8, memorial = 9, jail = 10, archery = 11, garden = 12}
POLISH_ENGRAVE_AFTER = 14 * 1200

local function room_cells(p, key)
    local cells = {}
    for x, col in pairs(layouts.tiles_from_dig(cells_of(p, 'dig'))) do
        for y in pairs(col) do table.insert(cells, {x = x, y = y, text = key}) end
    end
    return cells
end

-- Pure: the next project to polish and what to do: (project, 'smooth' |
-- 'engrave') or nil. projects: the registry's list; now: game tick.
function polish_pick(projects, now)
    local best, best_rank, what
    for _, p in ipairs(projects) do
        local rank = POLISH_ORDER[p.kind]
        local pol = p.polish or {}
        if p.phase == 'done' and rank then
            local step
            if not pol.step then step = 'smooth'
            elseif pol.step == 'smooth' and type(pol.at) == 'number' and now - pol.at >= POLISH_ENGRAVE_AFTER then
                step = 'engrave'
            end
            if pol.step == 'smooth' and not step then return nil, 'a level is being smoothed' end
            if step and (not best_rank or rank < best_rank) then best, best_rank, what = p, rank, step end
        end
    end
    return best, what
end

function polish_next(dry_run)
    OFFSET = elevation_offset()
    local data = load_projects()
    local now = now_tick()
    local p, what = polish_pick(data.list, now)
    if not p then
        return {ok = false, rejected = true, waiting = what ~= nil or nil,
                error = what or 'every finished level is polished'}
    end
    local cells = room_cells(p, what == 'smooth' and 's' or 'e')
    if #cells == 0 then return {ok = false, rejected = true, error = 'nothing dug in that level'} end
    local out = {ok = true, project_id = p.id, kind = p.kind, step = what, elevation = ez(p.z), tiles = #cells,
                 dry_run = dry_run or nil}
    if dry_run then return out end
    local ok, s = pcall(quickfort_apply, 'dig', cells, p.z, anchor_of(p).x, anchor_of(p).y)
    local n = ok and stat(s, 'dig_designated') or 0
    p.polish = {step = what == 'smooth' and 'smooth' or 'engraved', at = now}
    save_projects(data)
    out.designated = n
    if n == 0 then
        -- nothing took (soil, built floors, already done): the level counts as polished
        out.note = 'nothing there could be ' .. (what == 'smooth' and 'smoothed' or 'engraved')
    end
    return out
end
