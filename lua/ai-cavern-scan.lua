-- (0.105.46, I6) The deep section's caverns: which sample tiles of each found
-- cavern the dwarves have seen, and whether any of them joins the fort's
-- ground (the walk groups the citizens stand in).
--
-- Why: get_deep read 16 sample tiles of every block of every found cavern
-- (~1,300 blocks a cavern) each report, nearly all still hidden in a sealed
-- fort: most of the deep section's 265 ms (run check 12-13 Nov). A tile once
-- seen is never hidden again, so the seen samples are kept (per map) and
-- only the blocks with samples still hidden are read again:
--   * every report: the seen samples' walk groups (the "open" test, up to
--     OPEN_CHECKS a cavern, as before), and the blocks in the columns round
--     each citizen (NEAR_MAX at most: where a breach from the fort shows
--     first);
--   * the rest of the hidden blocks in slices (lua/ai-slices.lua), a whole
--     pass every few reports; the first pass for a map (or after a cavern is
--     found) is walked whole, as before.
-- Pure reads; nothing is changed in the game.
--@module = true

SCAN_MS = 30          -- a report's slice of the hidden blocks
SCAN_ITEMS = nil      -- and its count of blocks (nil: time only; the tests set it)
NEAR_MAX = 300        -- blocks round the citizens read every report
OPEN_CHECKS = 4000    -- seen samples whose walk group is looked at, a cavern (as before)
FULL = 0xFFFF         -- all 16 samples of a block seen

CAVERN_SCAN = CAVERN_SCAN or nil   -- {key, caverns = {[name] = state}}

local function slices()
    local ok, S = pcall(reqscript, 'ai-slices')
    return ok and type(S) == 'table' and S.run and S or nil
end

-- a cavern's state for its block positions: mask (per block, the samples
-- seen), seen (the seen samples, in the order found), cols (block column ->
-- block indexes)
local function cavern_state(blocks)
    local c = {blocks = blocks, mask = {}, seen = {}, cols = {}}
    for i, p in ipairs(blocks) do
        local k = (p[1] // 16) .. ',' .. (p[2] // 16)
        local l = c.cols[k]
        if not l then l = {}; c.cols[k] = l end
        l[#l + 1] = i
    end
    return c
end

-- read block i's hidden samples again; returns true when the block was read
function scan_block(c, i)
    local m = c.mask[i] or 0
    if m == FULL then return false end
    local p = c.blocks[i]
    local block = dfhack.maps.getTileBlock(p[1], p[2], p[3])
    if not block then
        c.mask[i] = FULL            -- no block there: nothing to see
        return false
    end
    local des = block.designation
    for sx = 0, 3 do
        local row = des[sx * 5]
        for sy = 0, 3 do
            local bit = 1 << (sx * 4 + sy)
            if m & bit == 0 and not row[sy * 5].hidden then
                m = m | bit
                c.seen[#c.seen + 1] = {x = p[1] + sx * 5, y = p[2] + sy * 5, z = p[3]}
            end
        end
    end
    c.mask[i] = m
    return true
end

-- The state for this map (`key`) and these caverns: rows = {{name, blocks =
-- {{x, y, z}, ...}}, ...} (the block positions, as the deep section keeps them)
function state_for(key, rows)
    local st = CAVERN_SCAN
    if not st or st.key ~= key then
        st = {key = key, caverns = {}}
        CAVERN_SCAN = st
    end
    for _, r in ipairs(rows) do
        local c = st.caverns[r.name]
        if not c or (c.blocks ~= r.blocks and #c.blocks ~= #r.blocks) then
            st.caverns[r.name] = cavern_state(r.blocks)
        end
    end
    return st
end

-- scan(rows, groups, positions, key, now) -> {[name] = {seen, open, open_at}}
--   groups: the citizens' walk groups ({[g] = true}); positions: the citizens' {x, y, z}
function scan(rows, groups, positions, key, now)
    local st = state_for(key, rows)
    local names = {}
    for _, r in ipairs(rows) do names[#names + 1] = tostring(r.name) end
    -- the columns round the citizens, each cavern's blocks there
    local near = 0
    local cols = {}
    for _, p in ipairs(positions or {}) do
        local bx, by = p.x // 16, p.y // 16
        for dx = -1, 1 do
            for dy = -1, 1 do cols[(bx + dx) .. ',' .. (by + dy)] = true end
        end
    end
    for _, r in ipairs(rows) do
        local c = st.caverns[r.name]
        for k in pairs(cols) do
            for _, i in ipairs(c.cols[k] or {}) do
                if near >= NEAR_MAX then break end
                if scan_block(c, i) then near = near + 1 end
            end
        end
    end
    -- the rest, in slices
    local S = slices()
    local function items()
        local out = {}
        for _, r in ipairs(rows) do
            local c = st.caverns[r.name]
            for i = 1, #c.blocks do
                if (c.mask[i] or 0) ~= FULL then out[#out + 1] = {c, i} end
            end
        end
        return out
    end
    local function visit(_, it) scan_block(it[1], it[2]) end
    local status
    if S then
        local _, s2, done, total = S.run('cavern_scan', {key = key .. '|' .. table.concat(names, ','), now = now,
                                                         ttl = 0, whole_first = true, items = items,
                                                         init = function() return true end, visit = visit,
                                                         max_ms = SCAN_MS, max_items = SCAN_ITEMS})
        status = {state = s2, done = done, total = total, near = near}
    else
        for _, it in ipairs(items()) do pcall(visit, nil, it) end
        status = {state = 'done', near = near}
    end
    -- the open test: the seen samples' walk groups
    local out = {}
    for _, r in ipairs(rows) do
        local c = st.caverns[r.name]
        local row = {seen = #c.seen, open = false}
        local n = 0
        for _, p in ipairs(c.seen) do
            if n >= OPEN_CHECKS then break end
            n = n + 1
            local g = dfhack.maps.getWalkableGroup({x = p.x, y = p.y, z = p.z})
            if g ~= 0 and groups[g] then
                row.open = true
                row.open_at = {x = p.x, y = p.y, z = p.z}
                break
            end
        end
        out[r.name] = row
    end
    LAST_STATUS = status
    return out, status
end
