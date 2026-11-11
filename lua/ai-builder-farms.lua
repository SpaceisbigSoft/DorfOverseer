-- ai-builder-farms: farm plots and crops, water and sand zones, pastures.
--
-- (13c) A part of ai-builder, not a script of its own: ai-builder.lua loads it
-- into its own environment, so every name here is reqscript('ai-builder').name
-- and the helpers defined there (info, quickfort_apply, ...) are in reach.

PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-builder-farms'] = '0.105.36'   -- (0.105.26) bumped with BRIDGE_VERSION

local ez = ez

---------------------------------------------------------------------------
-- Farm plots. Crops grow on soil, or on stone that has been muddied (by
-- water). The AI first lays plots on such floor the fort already has, inside
-- and walkable from where the dwarves are; if that isn't enough, it digs a
-- farm level in a soil layer (layouts.farms). See docs/building.md.
---------------------------------------------------------------------------

FARM_MAX_SIDE = 6          -- plots on existing floor: at most 6x6 each
FARM_MIN_SIDE = 2          -- and at least 2x2 (never a 1-wide corridor)
FARM_SCAN_LEVELS = 12      -- levels searched: the ones most dwarves are on
FARM_SCAN_MARGIN = 20      -- tiles searched around where the dwarves are
FARM_PLOT_W = 5            -- a dug farm level's plots are 5x3
FARM_SEARCH_SECONDS = 2

-- Rectangles of free soil or muddy floor near the dwarves, adding up to about
-- `want` tiles: {x, y, z, w, h}, busiest levels first.
-- (13c) its own name: the pastures' living-grass list below (no dead grass)
-- used to reassign this one when the module loaded, so dead grass never farmed
local FARM_GRASS = {GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true, GRASS_DEAD = true}

-- outside: also soil and grass under the sky, when there is too little
-- inside (surface crops only grow there; a site whose soil is all on the
-- surface farms there until it has more)
-- Returns spots, why (nil, or 'no citizens'), timed_out (13c: true when a
-- pass ran out of time before `want` was found).
UNDER_ONLY = false
function find_farm_spots(want, reserved, outside)
    local area = fort_scan_area(FARM_SCAN_MARGIN)
    if not area then return {}, 'no citizens' end
    local groups, levels = area.groups, area.levels
    local x1, y1, x2, y2 = area.x1, area.y1, area.x2, area.y2

    local good_cache, used = {}, {}
    local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
    local function good(x, y, z)
        local k = key(x, y, z)
        if used[k] then return false end
        local v = good_cache[k]
        if v ~= nil then return v end
        if not floor_material(x, y, z) then
            good_cache[k] = false
            return false
        end
        local t = tile_info(x, y, z)
        if PASS_OUTSIDE and t and t.outside and SURFACE_SCAN then
            -- (0.99.8) why the surface's tiles were turned down, for the refusal
            local why = (t.shape ~= 'FLOOR' and ('shape ' .. tostring(t.shape)))
                or (not (t.material == 'SOIL' or FARM_GRASS[t.material]) and ('material ' .. tostring(t.material)))
                or (t.liquid and 'water') or (t.building and 'building') or (t.designated and 'designated')
                or (inside_any(reserved, x, y, z) and 'reserved')
                or (groups[walk_group(x, y, z)] ~= true and 'out of reach')
                or (tile_taken(x, y, z) and 'taken') or 'ok'
            SURFACE_SCAN.seen[why] = (SURFACE_SCAN.seen[why] or 0) + 1
        end
        v = t ~= nil and t.shape == 'FLOOR' and not t.liquid and not t.feature
            and (not t.outside or (PASS_OUTSIDE and (t.material == 'SOIL' or FARM_GRASS[t.material])))
            -- (0.105.5) Hammerstirred: plots for underground crops only where
            -- DF counts the floor subterranean (a roofed floor in the light
            -- grows surface crops only)
            -- (0.105.7 review) and only where the flag was read: a roofed
            -- floor in the light (flag unreadable) isn't taken for underground,
            -- else plots went where plump helmets can't grow and were asked for again
            and not (UNDER_ONLY and (t.outside or t.subterranean ~= true))
            and not t.building and not t.designated
            and not inside_any(reserved, x, y, z)
            and groups[walk_group(x, y, z)] == true
            and (t.material == 'SOIL' or FARM_GRASS[t.material] or mud_at(x, y, z))
            and not tile_taken(x, y, z)
        good_cache[k] = v
        return v
    end

    local spots, total, cut = {}, 0, false
    local deadline
    for pass = 1, outside and 2 or 1 do
    PASS_OUTSIDE = pass == 2
    good_cache = {}
    -- (0.99.7) each pass gets its own time, and the outdoor pass searches
    -- the surface's levels, not only those most dwarves stand on (region2:
    -- "no free soil" with the surface out of the 12 busiest levels)
    local scan = levels
    if PASS_OUTSIDE then
        scan = {}
        SURFACE_SCAN = {levels = {}, seen = {}}
        for _, z in ipairs(surface_levels(area)) do
            table.insert(scan, {z = z})
            table.insert(SURFACE_SCAN.levels, ez(z))
        end
    end
    -- (13c) the clock starts after surface_levels, which used to eat the
    -- outdoor pass's time
    deadline = os.clock() + FARM_SEARCH_SECONDS
    for i = 1, math.min(FARM_SCAN_LEVELS, #scan) do
        local z = scan[i].z
        for y = y1, y2 do
            if total >= want then break end
            if os.clock() > deadline then cut = true break end
            for x = x1, x2 do
                if total >= want then break end
                if good(x, y, z) then
                    local rw = 1
                    while rw < FARM_MAX_SIDE and good(x + rw, y, z) do rw = rw + 1 end
                    local rh = 1
                    while rh < FARM_MAX_SIDE do
                        local row_ok = true
                        for dx = 0, rw - 1 do
                            if not good(x + dx, y + rh, z) then row_ok = false break end
                        end
                        if not row_ok then break end
                        rh = rh + 1
                    end
                    -- no bigger than what's still wanted (but never under the minimum)
                    rh = math.max(FARM_MIN_SIDE, math.min(rh, math.ceil((want - total) / rw)))
                    if rw >= FARM_MIN_SIDE and rh >= FARM_MIN_SIDE then
                        local fits = true
                        for dy = 0, rh - 1 do
                            for dx = 0, rw - 1 do
                                if not good(x + dx, y + dy, z) then fits = false end
                            end
                        end
                        if fits then
                            for dy = 0, rh - 1 do
                                for dx = 0, rw - 1 do used[key(x + dx, y + dy, z)] = true end
                            end
                            table.insert(spots, {x = x, y = y, z = z, w = rw, h = rh})
                            total = total + rw * rh
                        end
                    end
                end
            end
        end
    end
    end
    PASS_OUTSIDE = false
    return spots, nil, cut and total < want
end

SOIL_RADIUS = 30          -- around each staircase, when looking for soil
SOIL_STEP = 4             -- sample every 4th tile (soil layers are wide)

-- Why no farm level could be dug, in words: no soil near the staircases at
-- all, or soil on some levels but no safe spot there (with the first reason).
local function farm_level_why(level_error, reserved)
    local stairs = find_stairs(STAIRS_TO_TRY)
    if not stairs then return 'no farm level: ' .. tostring(level_error) end
    local soil = soil_levels(stairs)
    local zs = {}
    for z in pairs(soil) do table.insert(zs, z) end
    if #zs == 0 then
        return ('no soil on any level the staircases reach (elevation %d to %d)'):format(
            ez(math.max(1, stairs[1].z_bottom - MAX_LEVELS_BELOW)), ez(stairs[1].z_top))
    end
    table.sort(zs)
    -- the first reason a farm level centred on the main stairs fails at a soil level
    local L = layouts.make('farms', {plots = 2, plot_w = FARM_PLOT_W})
    local reason
    CACHE = {}
    for _, z in ipairs(zs) do
        local ok, why = check_site(L, {}, stairs[1].x, stairs[1].y, z, reserved, {x = 0, y = 0})
        if not ok then reason = why break end
    end
    CACHE = nil
    local range = #zs == 1 and ('elevation %d'):format(ez(zs[1]))
        or ('elevation %d to %d'):format(ez(zs[1]), ez(zs[#zs]))
    return ('there is soil at %s, but no safe spot for a farm level there%s'):format(
        range, reason and (' (' .. reason .. ')') or '')
end

-- params: tiles (how many farm tiles are wanted), dig (may start a farm level
-- if existing floor isn't enough), style (the fort's, for that level).
-- dry_run: says what it would do, changes nothing.
function farm_plots(params, now, dry_run)
    OFFSET = elevation_offset()
    local want = math.tointeger(tonumber(params.tiles)) or 0
    local data = load_projects()
    local reserved = {}
    for _, p in ipairs(open_projects(data)) do table.insert(reserved, p.area) end
    SURFACE_SCAN = nil
    -- (0.105.5) underground = true: subterranean floor only, never the surface
    UNDER_ONLY = params.underground == true
    local okf, spots, why, cut = pcall(find_farm_spots, want, reserved, params.outside == true and not UNDER_ONLY)
    UNDER_ONLY = false
    PASS_OUTSIDE = false        -- (0.105.33 L5) also when the search threw in its second pass
    if not okf then error(spots) end
    local placed, refused, tiles = {}, 0, 0
    for _, sp in ipairs(spots) do
        local cell = {{x = 0, y = 0, text = ('p(%dx%d)'):format(sp.w, sp.h)}}
        if qf_try('build', cell, sp.z, sp.x, sp.y, dry_run) then
            table.insert(placed, {x = sp.x, y = sp.y, elevation = ez(sp.z), w = sp.w, h = sp.h})
            tiles = tiles + sp.w * sp.h
        else
            refused = refused + 1
        end
    end
    local out = {ok = true, dry_run = dry_run or nil, placed = placed, tiles = tiles,
                 refused = refused > 0 and refused or nil, timed_out = cut or nil}
    local short = want - tiles
    if short > 0 and params.dig then
        local plots = math.max(1, math.min(12, math.ceil(short / (FARM_PLOT_W * 3))))
        out.level = start_project({kind = 'farms', plots = plots, plot_w = FARM_PLOT_W, style = params.style,
                                   max_elev = params.max_elev},          -- (0.105.23)
                                  now, dry_run)
    end
    if tiles == 0 and not (out.level and out.level.ok) then
        local reasons = {}
        if why then table.insert(reasons, why) end
        table.insert(reasons, #spots == 0 and ((cut and 'search cut short: ' or '') .. 'no free soil or muddy floor near the dwarves')
            or ('the game refused plots on %d spot(s)'):format(refused))
        if out.level and out.level.rejected then
            table.insert(reasons, 'no farm level now: ' .. tostring(out.level.error))
        elseif out.level then
            local ok, text = pcall(farm_level_why, out.level.error, reserved)
            table.insert(reasons, ok and text or ('no farm level: ' .. tostring(out.level.error)))
        elseif not params.dig then
            table.insert(reasons, 'and no new level may be dug now')
        end
        if SURFACE_SCAN then
            -- (0.99.8) what the surface held, so a refusal says why
            local parts = {}
            for k, n in pairs(SURFACE_SCAN.seen) do table.insert(parts, {k = k, n = n}) end
            table.sort(parts, function(a, b) return a.n > b.n end)
            local words = {}
            for i = 1, math.min(5, #parts) do table.insert(words, parts[i].k .. ' ' .. parts[i].n) end
            local lv = {}
            for _, e in ipairs(SURFACE_SCAN.levels) do table.insert(lv, tostring(e)) end
            table.insert(reasons, ('the surface (elevation %s): %s'):format(
                #lv > 0 and table.concat(lv, ', ') or 'none found', #words > 0 and table.concat(words, ', ') or 'no tiles'))
            out.surface = SURFACE_SCAN
        end
        out.ok, out.error = false, table.concat(reasons, '; ')
    end
    return out
end

-- (0.99.6) What a plant brews from: 'plant' (the plant itself, its
-- STRUCTURAL material makes a drink), 'growth' (a fruit or other growth
-- does), or nil. From the raws' MATERIAL_REACTION_PRODUCT:DRINK_MAT.
function plant_brews(raw)
    local out = nil
    for _, m in ipairs(raw.material) do
        local ok, ids = pcall(function() return m.reaction_product.id end)
        if ok and ids then
            for _, id in ipairs(ids) do
                local v = type(id) == 'string' and id or id.value
                if v == 'DRINK_MAT' then
                    if m.id == 'STRUCTURAL' then return 'plant' end
                    out = 'growth'
                end
            end
        end
    end
    return out
end

-- (0.104.11) Does a plant give thread (a THREAD material: pig tails, rope
-- reeds, hemp...)? Processed at a farmer's workshop, the thread goes to
-- the hospital's sutures and the loom.
function plant_thread(raw)
    local ok, yes = pcall(function()
        for _, m in ipairs(raw.material) do if m.id == 'THREAD' then return true end end
        return false
    end)
    return ok and yes or false
end

SEASON_FLAGS = {'SPRING', 'SUMMER', 'AUTUMN', 'WINTER'}

-- (0.105.5) Hammerstirred (2 Nov): plots lay fallow all year on six forts
-- (fort B: 4 of 5 surface plots, 147 seeds; fort E: 4 of 4, 162 seeds) while
-- autofarm was on and its thresholds set: the player's plot menu offered only
-- "Leave fallow" in every season. DF lists a crop for a plot only when the
-- fort has its seeds and the plant grows there: a subterranean crop (plump
-- helmet, cave wheat, pig tail, quarry bush) only on an underground plot, a
-- surface crop only on a surface plot whose biome is among the plant's
-- BIOME_ flags, and only in the seasons it has (SPRING..WINTER). The fort's
-- seeds were nearly all underground crops. These helpers repeat DF's test, so
-- the report can say per plot what it may grow, and set_farm_crops can set it.
local SUBTERRANEAN_FLAGS = {'BIOME_SUBTERRANEAN_WATER', 'BIOME_SUBTERRANEAN_CHASM', 'BIOME_SUBTERRANEAN_LAVA'}
FARM_CROPS_KEY = 'ai-overseer/farm_crops'

-- true/false, or nil when the structure has no such flag (never refuse on
-- a name this DFHack doesn't know)
local function plant_flag(raw, name)
    local ok, v = pcall(function() return raw.flags[name] end)
    if not ok or v == nil then return nil end
    return v == true
end

-- (0.105.5) An underground crop: a BIOME_SUBTERRANEAN_* flag (or, on an
-- older structure, an underground depth).
function crop_underground(raw)
    for _, f in ipairs(SUBTERRANEAN_FLAGS) do
        if plant_flag(raw, f) then return true end
    end
    local ok, d = pcall(function() return raw.underground_depth_min end)
    return ok and type(d) == 'number' and d > 0 or false
end

-- (0.105.5) Does it grow in season s (0 spring .. 3 winter)?
function crop_in_season(raw, s)
    return plant_flag(raw, SEASON_FLAGS[s + 1]) == true
end

-- (0.105.5) A tile's place for farming: under = an underground plot (DF's
-- subterranean flag; else not under the sky), biome = df.biome_type name of
-- its region, align = {good, evil, savage}. Overridden by the tests.
function plot_place(x, y, z)
    local out = {under = false}
    local d = dfhack.maps.getTileFlags(x, y, z)
    if d then
        local ok, sub = pcall(function() return d.subterranean end)
        if ok and sub ~= nil then out.under = sub == true
        else
            out.under = not d.outside
            out.guessed = true       -- (0.105.7 review) the flag couldn't be read
        end
    end
    pcall(function()
        local rx, ry = dfhack.maps.getTileBiomeRgn(x, y, z)
        if type(rx) == 'table' or type(rx) == 'userdata' then rx, ry = rx.x, rx.y end
        local okb, bt = pcall(dfhack.maps.getBiomeType, rx, ry)
        if okb and bt then out.biome = df.biome_type[bt] end
        local okr, region = pcall(dfhack.maps.getRegionBiome, rx, ry)
        if okr and region then
            out.align = {good = region.evilness < 33, evil = region.evilness > 65, savage = region.savagery > 65}
        end
    end)
    return out
end

-- (0.105.5) May this plant be set on a plot at `place` (seasons aside)?
-- DF's own list: seeds (SEED), underground crops underground only, surface
-- crops on the surface in a biome they have, GOOD/EVIL/SAVAGE plants only
-- where the land is so. Biome unknown: any surface crop is let through.
function crop_grows_on(raw, place)
    if plant_flag(raw, 'SEED') == false then return false end
    local under = crop_underground(raw)
    if place.under then return under end
    if under then return false end
    if place.biome and plant_flag(raw, 'BIOME_' .. place.biome) == false then return false end
    local a = place.align
    if a then
        if plant_flag(raw, 'GOOD') and not a.good then return false end
        if plant_flag(raw, 'EVIL') and not a.evil then return false end
        if plant_flag(raw, 'SAVAGE') and not a.savage then return false end
    end
    return true
end

-- (0.105.5) Seeds the planters can take, by plant index (not held, see
-- item_held, nor rotten). seed_free: also for the plants in store.
function seed_free(it) return not (item_held(it) or it.flags.rotten) end
function seed_stock()
    local out = {}
    for _, it in ipairs(df.global.world.items.other.SEEDS) do
        if seed_free(it) then
            local idx = it:getMaterialIndex()
            out[idx] = (out[idx] or 0) + it:getStackSize()
        end
    end
    return out
end

function farm_plot_buildings()
    local out = {}
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.FarmPlot then table.insert(out, b) end
    end
    return out
end

function current_season()
    return math.max(0, math.min(3, df.global.cur_year_tick // 100800))   -- 3 months of 28 days
end

local function plant_raw(idx)
    if not idx or idx < 0 then return nil end
    return df.plant_raw.find(idx)
end

function farm_crops_data()
    local d = site_get(FARM_CROPS_KEY)
    if type(d.set) ~= 'table' then d.set = {} end
    return d
end

-- (0.105.5) Per plot: where it is, what it holds each season, whether that
-- grows there, and what it could grow from the seeds in store (DF's menu).
function farm_plot_list(seeds, season)
    local out = {}
    -- (0.105.33 B4) the crops the AI set itself (ai_now: this season's is
    -- the AI's), so the brain asks for a drink swap only where the bridge makes one
    local okd, cd = pcall(farm_crops_data)
    local set = okd and type(cd) == 'table' and type(cd.set) == 'table' and cd.set or {}
    for _, b in ipairs(farm_plot_buildings()) do
        if #out >= 40 then break end
        local place = plot_place(b.centerx, b.centery, b.z)
        local p = {id = b.id, x = b.centerx, y = b.centery, elevation = ez(b.z),
                   tiles = (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1),
                   underground = place.under, biome = place.biome and place.biome:lower() or nil,
                   crops = {}, options = 0, options_any = 0}
        local any = {}
        for s = 0, 3 do
            local id = b.plant_id[s]
            local raw = plant_raw(id)
            p.crops[s + 1] = raw and raw.id or ''
            local n, nb = 0, 0
            for idx, c in pairs(seeds) do
                local r = c > 0 and plant_raw(idx)
                if r and crop_in_season(r, s) and crop_grows_on(r, place) then
                    n = n + 1
                    any[idx] = true
                    if s == season and plant_brews(r) ~= nil then nb = nb + 1 end
                end
            end
            if s == season then
                p.options = n
                -- (0.105.36) the brewable crops that grow on this plot this
                -- season (its biome too, as set_farm_crops tests it): the
                -- brain asks for a drink swap only where one can be made
                p.brew_options = nb
                p.fallow = raw == nil
                -- (0.105.7 review) a crop whose seeds have run out can't be
                -- sown again: not "fine" (no_seeds), so the plot is moved on
                p.ok_now = raw ~= nil and crop_in_season(raw, s) and crop_grows_on(raw, place)
                    and (seeds[id] or 0) > 0
                if raw ~= nil and (seeds[id] or 0) <= 0 then p.no_seeds = true end
                local mine = set[tostring(b.id)]
                p.ai_now = raw ~= nil and type(mine) == 'table' and mine[s + 1] == id or false
            end
        end
        for _ in pairs(any) do p.options_any = p.options_any + 1 end
        -- nothing the fort has seeds of grows here in any season (DF's menu
        -- shows only "Leave fallow")
        p.dead = p.options_any == 0 or nil
        table.insert(out, p)
    end
    return out
end

-- (0.105.5) Sets each farm plot's crop for every season where a crop the
-- fort has seeds of grows there, the current season first. A season's crop
-- is changed only when the slot is empty, holds a crop that can't grow
-- there, or holds the crop the AI set itself last time (a crop the player
-- chose that grows there is kept). The pick: while drink is short
-- (params.drink) the brewable crops first; a thread crop on one plot when
-- params.thread; else spread over the crops (fewest plots first, then the
-- most seeds). This season's seeds are shared out by the plots' tiles.
-- (0.105.24) params.variety: brewable crops first, one no plot grows yet
-- before a second plot of the same (drinks of several kinds).
function set_farm_crops(params, dry_run)
    local season = current_season()
    local seeds = seed_stock()
    local plots = farm_plot_buildings()
    if #plots == 0 then return {ok = false, error = 'the fort has no farm plots'} end
    local data = farm_crops_data()
    local left = {}
    for k, v in pairs(seeds) do left[k] = v end
    local used = {[0] = {}, {}, {}, {}}
    local thread_set = {}
    -- (0.105.31) seasons some plot already grows a fibre crop in (the mood
    -- reserve's plant cloth: params.thread swaps one AI-set plot to fibre
    -- only where none does)
    local thread_now = {}
    for _, b in ipairs(plots) do
        for k = 0, 3 do
            local okr, r = pcall(plant_raw, b.plant_id[k])
            if okr and r and plant_thread(r) then thread_now[k] = true end
        end
    end
    -- (0.105.31 reserve fixes) a plot season swapped back for drink
    -- (params.drink) belongs to the drink for that season and the next: the
    -- thread swap doesn't take it again (they swapped it to and fro each call)
    local okn, now_season = pcall(function() return (tonumber(df.global.cur_year) or 0) * 4 + season end)
    now_season = okn and now_season or season
    if type(data.drink_held) ~= 'table' then data.drink_held = {} end
    local changed, dead, kept, set_plots = 0, 0, 0, {}
    for _, b in ipairs(plots) do
        local place = plot_place(b.centerx, b.centery, b.z)
        local tiles = (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1)
        local key = tostring(b.id)
        local mine = type(data.set[key]) == 'table' and data.set[key] or {}
        local held = type(data.drink_held[key]) == 'table' and data.drink_held[key] or {}
        local plot_out, any = {id = b.id, crops = {}}, false
        for k = 0, 3 do
            local s = (season + k) % 4
            local cands = {}
            for idx, n in pairs(seeds) do
                local r = n > 0 and plant_raw(idx)
                -- (0.105.6) A (2 Nov): the current season took a crop only while
                -- seeds were left over after the plots already sown; with 7 plump
                -- helmet seeds for 21 tiles two plots stayed bare while the report
                -- counted the crop as an option, and the rule fired every day. A
                -- plot with fewer seeds than tiles is still partly sown, so any
                -- seed in store will do; the leftover only orders the choice.
                if r and crop_in_season(r, s) and crop_grows_on(r, place) then
                    table.insert(cands, {idx = idx, raw = r, brews = plant_brews(r) ~= nil,
                                         thread = plant_thread(r), seeds = n,
                                         left = s == season and (left[idx] or 0) or n})
                end
            end
            if #cands > 0 then any = true end
            local cur = b.plant_id[s]
            local cur_raw = plant_raw(cur)
            -- (0.105.7 review) with no seed of it left in store the slot is as
            -- good as fallow: another crop with seeds goes in (if there is one)
            local cur_ok = cur_raw ~= nil and crop_in_season(cur_raw, s) and crop_grows_on(cur_raw, place)
                and ((seeds[cur] or 0) > 0 or #cands == 0)
            local ours = mine[s + 1] ~= nil and mine[s + 1] == cur
            -- the AI's own crop is kept too while it still grows there, unless
            -- drink is short and it doesn't brew while a brewable one could
            -- go in (no churn of plots already sown)
            local swap = false
            if cur_ok and ours and params.drink == true and plant_brews(cur_raw) == nil then
                for _, c in ipairs(cands) do if c.brews then swap = true break end end
            end
            -- (0.105.24) drink of one kind: B and E's dwarves upset by "the same
            -- old booze" (SameBooze, the worst stress in both, 2-5 Nov): with
            -- params.variety the AI's own brewable crop another plot already
            -- grows this season gives way to a brewable one nobody grows yet
            if cur_ok and ours and not swap and params.variety == true and plant_brews(cur_raw) ~= nil
                    and (used[s][cur] or 0) >= 1 then
                for _, c in ipairs(cands) do
                    if c.brews and c.idx ~= cur and (used[s][c.idx] or 0) == 0 then swap = true break end
                end
            end
            -- (0.105.31) params.thread: one of the AI's own plots gives way to a
            -- fibre crop in a season no plot grows one (F, 8 Nov: a weaver's
            -- mood needed plant cloth, no fibre crop on any plot, and died)
            local drink_owns = tonumber(held[s + 1]) ~= nil and now_season - tonumber(held[s + 1]) <= 1
            if cur_ok and ours and not swap and params.thread == true and not thread_now[s]
                    and not thread_set[s] and not plant_thread(cur_raw) and not drink_owns then
                for _, c in ipairs(cands) do if c.thread then swap = true break end end
            end
            if cur_ok and not swap then
                if not ours then kept = kept + 1 end
                used[s][cur] = (used[s][cur] or 0) + 1
                if s == season then left[cur] = (left[cur] or 0) - tiles end
                if ours then plot_out.crops[SEASON_FLAGS[s + 1]:lower()] = cur_raw.id end
            elseif #cands > 0 then
                local want_thread = params.thread == true and not thread_set[s]
                table.sort(cands, function(a, c)
                    if (params.drink == true or params.variety == true) and a.brews ~= c.brews then return a.brews end
                    -- (0.105.24) variety: a brewable crop no plot grows yet this season first
                    if params.variety == true and a.brews and c.brews then
                        local ua, uc = used[s][a.idx] or 0, used[s][c.idx] or 0
                        if (ua == 0) ~= (uc == 0) then return ua == 0 end
                    end
                    if want_thread and a.thread ~= c.thread then return a.thread end
                    -- (0.105.6) a crop with seeds left over first, then the least used
                    if (a.left > 0) ~= (c.left > 0) then return a.left > 0 end
                    local ua, uc = used[s][a.idx] or 0, used[s][c.idx] or 0
                    if ua ~= uc then return ua < uc end
                    if a.seeds ~= c.seeds then return a.seeds > c.seeds end
                    return a.idx < c.idx
                end)
                local pick = cands[1]
                -- (0.105.31 reserve fixes) swapped back for drink: the drink's for a season
                if swap and params.drink == true and pick.brews and pick.idx ~= cur then held[s + 1] = now_season end
                used[s][pick.idx] = (used[s][pick.idx] or 0) + 1
                if pick.thread then thread_set[s] = true end
                if s == season then left[pick.idx] = (left[pick.idx] or 0) - tiles end
                if pick.idx ~= cur then
                    changed = changed + 1
                    if not dry_run then b.plant_id[s] = pick.idx end
                end
                mine[s + 1] = pick.idx
                plot_out.crops[SEASON_FLAGS[s + 1]:lower()] = pick.raw.id
            end
        end
        if not any then dead = dead + 1 end
        data.set[key] = mine
        data.drink_held[key] = next(held) and held or nil
        table.insert(set_plots, plot_out)
    end
    local out = {ok = true, plots = #plots, changed = changed, kept = kept, dead = dead > 0 and dead or nil,
                 dry_run = dry_run or nil, set = set_plots}
    local any_set = false
    for _, p in ipairs(set_plots) do if next(p.crops) then any_set = true break end end
    -- (0.105.31 reserve fixes) a fibre crop asked and none grows on any plot
    -- this season (no fibre seed grows where the plots are, or the plots are
    -- the drink's): said, so the brain waits for the next season
    if params.thread == true and not thread_now[season] and not thread_set[season] then
        out.thread_none = true
        out.reason = 'no fibre crop the fort has seeds of can go on its plots this season '
            .. '(none grows where they are, or the plots are kept for drink)'
    end
    if changed == 0 and kept == 0 and not any_set then
        out.ok, out.error = false, ('no crop the fort has seeds of grows on any of its %d plot(s) '
            .. '(underground crops need underground plots)'):format(#plots)
        return out
    end
    if not dry_run then
        -- (0.105.33 L5) plots gone since: their entries dropped (the site data
        -- grew without bound)
        local live = {}
        for _, b in ipairs(plots) do live[tostring(b.id)] = true end
        for _, t in ipairs({data.set, data.drink_held}) do
            local gone = {}
            for k in pairs(t) do if not live[tostring(k)] then table.insert(gone, k) end end
            for _, k in ipairs(gone) do t[k] = nil end
        end
        data.ai = true
        site_put(FARM_CROPS_KEY, data)
    end
    return out
end


-- (0.99.6) The crops the fort has seeds for: seeds and stock of each, what it
-- brews from, the seasons it grows in, above or below ground; and what the
-- plots grow this season. For steering autofarm toward drink.
local function crops_report()
    local crops, other = {}, df.global.world.items.other
    local function crop(idx)
        local raw = df.plant_raw.find(idx)
        if not raw then return nil end
        local c = crops[raw.id]
        if not c then
            -- (0.105.5) Hammerstirred (2 Nov): every crop showed all four
            -- seasons and plump helmets "surface": read through the same
            -- tests set_farm_crops uses (crop_in_season, crop_underground)
            local seasons = {}
            for k = 0, 3 do
                if crop_in_season(raw, k) then table.insert(seasons, SEASON_FLAGS[k + 1]:lower()) end
            end
            local under = crop_underground(raw)
            c = {name = raw.name, seeds = 0, stock = 0, brews = plant_brews(raw), seasons = seasons,
                 underground = under, planted = 0, thread = plant_thread(raw) or nil,
                 seed = plant_flag(raw, 'SEED') ~= false or nil}
            crops[raw.id] = c
        end
        return c
    end
    for _, it in ipairs(other.SEEDS) do
        if seed_free(it) then
            local c = crop(it:getMaterialIndex())
            if c then c.seeds = c.seeds + it:getStackSize() end
        end
    end
    for _, it in ipairs(other.PLANT) do
        if seed_free(it) then
            local raw = df.plant_raw.find(it:getMaterialIndex())
            local c = raw and crops[raw.id]
            if c then c.stock = c.stock + it:getStackSize() end
        end
    end
    local season = current_season()
    local plots_under, plots_above = 0, 0
    for _, b in ipairs(farm_plot_buildings()) do
        -- (0.105.5) DF's own underground test for the plot (plot_place)
        if plot_place(b.centerx, b.centery, b.z).under then plots_under = plots_under + 1
        else plots_above = plots_above + 1 end
        local id = b.plant_id[season]
        if id and id >= 0 then
            local c = crop(id)
            if c then c.planted = c.planted + 1 end
        end
    end
    -- (0.105.5) per plot: its crops by season, whether this season's grows
    -- there, how many crops in store could, and plots where none ever could
    local okp, list = pcall(farm_plot_list, seed_stock(), season)
    local out = {crops = crops, season = SEASON_FLAGS[season + 1]:lower(),
                 plots_underground = plots_under, plots_surface = plots_above}
    if okp then
        out.plot_list = list
        local fallow, dead, wrong = 0, 0, 0
        for _, p in ipairs(list) do
            if p.dead then dead = dead + 1
            elseif p.fallow then fallow = fallow + 1
            elseif not p.ok_now then wrong = wrong + 1 end
        end
        out.plots_fallow, out.plots_dead, out.plots_wrong = fallow, dead, wrong
        -- fallow plots that could grow something this season
        local idle = 0
        for _, p in ipairs(list) do
            if not p.dead and (p.fallow or not p.ok_now) and p.options > 0 then idle = idle + 1 end
        end
        out.plots_idle = idle
    else
        out.plot_list_error = tostring(list):sub(1, 120)
    end
    return out
end

-- Report section: the fort's farm plots (built or still waiting to be built).
function farms_report()
    local plots, tiles, built = 0, 0, 0
    for _, b in ipairs(df.global.world.buildings.all) do
        if b:getType() == df.building_type.FarmPlot then
            plots = plots + 1
            tiles = tiles + (b.x2 - b.x1 + 1) * (b.y2 - b.y1 + 1)
            if b.flags.exists then built = built + 1 end
        end
    end
    local out = {plots = plots, tiles = tiles, built = built}
    local ok, cr = pcall(crops_report)
    if ok and cr then
        out.crops, out.season = cr.crops, cr.season
        out.plots_underground, out.plots_surface = cr.plots_underground, cr.plots_surface
        -- (0.105.5) the plots one by one, and the counts the planner reads
        out.plot_list, out.plot_list_error = cr.plot_list, cr.plot_list_error
        out.plots_fallow, out.plots_dead, out.plots_wrong, out.plots_idle =
            cr.plots_fallow, cr.plots_dead, cr.plots_wrong, cr.plots_idle
        out.crops_by_ai = farm_crops_data().ai == true or nil
    else
        out.crops_error = tostring(cr):sub(1, 120)
    end
    return out
end

-- (0.104.2) A Water Source zone over open water the dwarves can walk to:
-- buckets are filled there for the injured (and the thirsty) while the fort
-- has no well. `points` are candidate water tiles {x, y, z}, best first (the
-- planner's choice from the water survey); the first one that is liquid
-- water now (not ice, magma or salt) with a bank the citizens reach gets a
-- 3x3 zone centred on it. Kept in site data 'ai-overseer/water_zones'.
WATER_ZONES_KEY = 'ai-overseer/water_zones'
WATER_BANK_RADIUS = 10    -- (0.105.5) water tiles this far around each point are tried too...
WATER_BANK_TRIES = 120     -- ...at most this many a point, the nearest first
BANK_SHAPES = {FLOOR = true, BOULDER = true, PEBBLES = true, TWIG = true, SAPLING = true, SHRUB = true, RAMP = true}

function water_zones()
    return site_get(WATER_ZONES_KEY)
end

function water_zone(points, dry_run)
    local groups = citizen_groups()
    local last = 'no open water the dwarves can walk to'
    local whys = {}
    local function note(w) last = w; table.insert(whys, w) end
    -- (0.105.5) Hammerstirred (2 Nov): the cavern water's nearest tile
    -- (x133 y130) had "no bank the dwarves reach" and the zone was refused
    -- while two forts ran out of drink. A body's nearest tile is only where
    -- the search starts: the water tiles around it (WATER_BANK_RADIUS, the
    -- nearest first) are tried too, so the first stretch of shore the
    -- dwarves walk to gets the zone, however long the walk.
    local tries = {}
    for _, p in ipairs(points or {}) do
        local x, y, z = math.tointeger(p.x), math.tointeger(p.y), math.tointeger(p.z)
        table.insert(tries, {x = x, y = y, z = z, first = true})
        if x and y and z then
            local near = {}
            for dx = -WATER_BANK_RADIUS, WATER_BANK_RADIUS do
                for dy = -WATER_BANK_RADIUS, WATER_BANK_RADIUS do
                    if dx ~= 0 or dy ~= 0 then
                        local n = tile_info(x + dx, y + dy, z)
                        if n and n.liquid and not n.magma and not n.salt then
                            table.insert(near, {x = x + dx, y = y + dy, z = z, d = math.max(math.abs(dx), math.abs(dy))})
                        end
                    end
                end
            end
            table.sort(near, function(a, b) return a.d < b.d or (a.d == b.d and (a.x < b.x or (a.x == b.x and a.y < b.y))) end)
            for i = 1, math.min(#near, WATER_BANK_TRIES) do table.insert(tries, near[i]) end
        end
    end
    for _, p in ipairs(tries) do
        local x, y, z = math.tointeger(p.x), math.tointeger(p.y), math.tointeger(p.z)
        local t = x and y and z and tile_info(x, y, z)
        if not t then
            if p.first then note('no such tile') end
        elseif not t.liquid or t.magma or t.salt then
            if p.first then note(('the water at x%d y%d is frozen, salt or gone'):format(x, y)) end
        else
            -- a bank beside the water, or (a pond sunk below the ground) on the level above it
            local bank
            for _, dz in ipairs({0, 1}) do
                for _, d in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                    local n = tile_info(x + d[1], y + d[2], z + dz)
                    if n and not n.liquid and BANK_SHAPES[n.shape] and groups[walk_group(x + d[1], y + d[2], z + dz)] then
                        bank = {x = x + d[1], y = y + d[2], above = dz == 1 or nil}
                        break
                    end
                end
                if bank then break end
            end
            if not bank then
                if p.first then
                    note(('no bank the dwarves reach beside the water at x%d y%d'):format(x, y))
                end
            else
                local cell = {{x = 0, y = 0, text = 'w(3x3)'}}
                local good, failed = qf_try('zone', cell, z, x - 1, y - 1, dry_run)
                if good then
                    if not dry_run then
                        local list = water_zones()
                        table.insert(list, {x = x, y = y, z = z})
                        site_put(WATER_ZONES_KEY, list)
                    end
                    return {ok = true, x = x, y = y, elevation = ez(z), bank = bank, stagnant = t.stagnant or nil,
                            cavern = t.feature or nil, outside = t.outside or nil, dry_run = dry_run or nil}
                elseif failed == 'run' then
                    note('the game refused the water source zone')
                else
                    note(('the game would not place a water source at x%d y%d'):format(x, y))
                end
            end
        end
    end
    return {ok = false, error = #whys > 1 and table.concat(whys, '; ') or last}
end

-- (0.104.95) A sand collection zone: glass is made from bags of sand, which a
-- hauler fills at a glass furnace from a Sand zone. The zone must lie on a
-- sand floor or beside a sand wall (diagonally too; DF wiki "Sand"). The
-- nearest such floor the dwarves walk to, on the ground outside first (sand
-- is in the soil layers), then the fort's levels. Kept in site data.
SAND_ZONES_KEY = 'ai-overseer/sand_zones'
SAND_RADIUS = 40
SAND_SECONDS = 1.0

-- Is the natural soil at this tile sand? (its layer's inorganic has SOIL_SAND)
function sand_tile(x, y, z)
    local t = tile_info(x, y, z)
    if not t or t.material ~= 'SOIL' then return false end
    local ok, yes = pcall(function()
        local idx = reqscript('ai-industry').stone_at(x, y, z)
        local inorg = idx and df.global.world.raws.inorganics.all[idx]
        return inorg ~= nil and inorg.flags.SOIL_SAND == true
    end)
    return ok and yes or false
end

function sand_zones()
    return site_get(SAND_ZONES_KEY)
end

-- A floor tile the dwarves reach, on sand or beside it: {x, y, z} or nil, why.
function find_sand_spot()
    local area = fort_scan_area(SAND_RADIUS)
    if not area then return nil, 'no citizens' end
    local zs, seen = {}, {}
    local okS, surf = pcall(surface_levels, area)
    for _, z in ipairs(okS and surf or {}) do if not seen[z] then seen[z] = true; table.insert(zs, z) end end
    for _, l in ipairs(area.levels) do if not seen[l.z] then seen[l.z] = true; table.insert(zs, l.z) end end
    local deadline = os.clock() + SAND_SECONDS     -- (13c) after surface_levels, not eaten by it
    local best, best_d, cut
    for _, z in ipairs(zs) do
        for y = area.y1, area.y2 do
            if os.clock() > deadline then cut = true break end
            for x = area.x1, area.x2 do
                local f = tile_info(x, y, z)
                if f and f.shape == 'FLOOR' and not f.liquid and not f.building
                        and area.groups[walk_group(x, y, z)] then
                    local d = math.abs(x - area.cx) + math.abs(y - area.cy)
                    if (not best_d or d < best_d) then
                        local sandy = sand_tile(x, y, z)
                        if not sandy then
                            for _, e in ipairs({{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}}) do
                                local n = tile_info(x + e[1], y + e[2], z)
                                if n and n.shape == 'WALL' and sand_tile(x + e[1], y + e[2], z) then sandy = true break end
                            end
                        end
                        if sandy then best, best_d = {x = x, y = y, z = z}, d end
                    end
                end
            end
        end
        if best then break end          -- the first level with sand (the ground outside before the fort)
    end
    if best then return best end
    return nil, (cut and 'search cut short: ' or '') .. 'no sand floor or sand wall the dwarves walk to near the fort', cut
end

function sand_zone(dry_run)
    if #sand_zones() > 0 then
        return {ok = false, rejected = true, error = 'the fort has a sand zone already'}
    end
    local spot, why, cut = find_sand_spot()
    if not spot then return {ok = false, rejected = true, error = why, timed_out = cut or nil} end
    local good, failed = qf_try('zone', {{x = 0, y = 0, text = 's'}}, spot.z, spot.x, spot.y, dry_run)
    if failed == 'dry' then
        return {ok = false, error = ('the game would not place a sand zone at x%d y%d'):format(spot.x, spot.y)}
    elseif not good then
        return {ok = false, error = 'the game refused the sand zone'}
    end
    local out = {ok = true, x = spot.x, y = spot.y, elevation = ez(spot.z), dry_run = dry_run or nil}
    if dry_run then return out end
    local list = sand_zones()
    table.insert(list, spot)
    site_put(SAND_ZONES_KEY, list)
    return out
end

---------------------------------------------------------------------------
-- Pastures. Grazers eat living grass (dead grass doesn't feed them). A new
-- pasture goes on grass near the fort's surface entrances, walkable from
-- where the dwarves are, sized for the herd that needs it. Grazers are put
-- in it by ai-society. See docs/building.md.
---------------------------------------------------------------------------

PASTURE_RADIUS = 40        -- tiles around a surface entrance
PASTURE_LEVELS = 2         -- levels above and below it (the surface is uneven)
PASTURE_MIN_SIDE = 3
PASTURE_MAX_ZONES = 4
PASTURE_BIG_SIDE = 31        -- one pasture as big as this (a herd grazes in one zone, not across several)
PASTURE_KEEP_CLEAR = 3     -- tiles kept free around an entrance (its gate)
PASTURE_SEARCH_SECONDS = 2
PASTURE_NAME = 'AI pasture'

PASTURE_GRASS = {GRASS_LIGHT = true, GRASS_DARK = true, GRASS_DRY = true}   -- living grass: animals graze it
local GRAZE_SHAPES = {FLOOR = true, SHRUB = true, SAPLING = true}

-- Living grass on this tile? Tile types looked up once.
local GRASS_TT = nil
function grass_at(x, y, z)
    local tt = dfhack.maps.getTileType(x, y, z)
    if not tt then return false end
    if not GRASS_TT then
        GRASS_TT = {}
        for t, _ in ipairs(df.tiletype) do
            local attrs = df.tiletype.attrs[t]
            if attrs and PASTURE_GRASS[df.tiletype_material[attrs.material]]
                    and GRAZE_SHAPES[df.tiletype_shape[attrs.shape]] then
                GRASS_TT[t] = true
            end
        end
    end
    return GRASS_TT[tt] == true
end

-- Where pastures should be near: the fort's surface entrances (once the
-- overseer has mapped them), else the top of the main staircase.
function pasture_anchors()
    local out = {}
    local ok, s = pcall(function() return reqscript('ai-gates').summary() end)
    if ok and s and s.scanned then
        for _, e in ipairs(s.entrances or {}) do
            if e.kind == 'surface' then table.insert(out, {x = e.x, y = e.y, z = e.z}) end
        end
    end
    if #out == 0 then
        local stair = find_main_stair()
        if stair then table.insert(out, {x = stair.x, y = stair.y, z = stair.z_top}) end
    end
    return out
end

-- One rectangle near the anchors holding at least `want` tiles of living
-- grass (other open ground inside it is fine: animals walk it, they only
-- graze the grass), nearest first: {x, y, z, w, h, grass} or nil. An animal
-- grazes inside its own pasture only, so several small zones that add up to
-- enough grass feed nobody (bridge 0.38 made those).
-- (13c) Out of time: nil, 'search cut short: ...', true.
function find_pasture_rect(want, reserved, until_clock)
    local anchors = pasture_anchors()
    if #anchors == 0 then return nil, 'no surface entrance or staircase to start from' end
    local groups = {}
    for _, p in ipairs(citizen_positions()) do
        local g = walk_group(p.x, p.y, p.z)
        if g ~= 0 then groups[g] = true end
    end
    local mw, mh = map_size()
    -- A zone may cover any tile the dwarves have seen (quickfort's only
    -- rule): trees, boulders and slopes too; animals walk round what they
    -- can't cross. Grass is counted; the rest is just inside it.
    local OPEN_SHAPES = {FLOOR = true, SHRUB = true, SAPLING = true, BOULDER = true, PEBBLES = true,
                         TWIG = true, RAMP = true}
    local function near_anchor(x, y, z)
        for _, a in ipairs(anchors) do
            if math.abs(a.z - z) <= 1 and math.max(math.abs(a.x - x), math.abs(a.y - y)) <= PASTURE_KEEP_CLEAR then
                return true
            end
        end
        return false
    end
    -- per tile: false (can't be in a pasture), 1 (grass), 0 (open ground)
    local cache = {}
    local function key(x, y, z) return (z * 4096 + y) * 4096 + x end
    local function tile(x, y, z)
        local k = key(x, y, z)
        local v = cache[k]
        if v ~= nil then return v end
        v = false
        if x >= 1 and y >= 1 and x <= mw - 2 and y <= mh - 2 then
            local t = tile_info(x, y, z)
            local tree = t and is_tree(t)
            if t and not t.hidden and (OPEN_SHAPES[t.shape] or tree) and not t.liquid and not t.feature
                    and not t.building and (tree or not t.designated)
                    and (tree or groups[walk_group(x, y, z)] == true)
                    and not inside_any(reserved, x, y, z) and not near_anchor(x, y, z)
                    and not tile_taken(x, y, z) then
                v = grass_at(x, y, z) and 1 or 0
            end
        end
        cache[k] = v
        return v
    end
    local function rect(x0, y0, z, w, h)
        local grass = 0
        for y = y0, y0 + h - 1 do
            for x = x0, x0 + w - 1 do
                local v = tile(x, y, z)
                if v == false then return nil end
                grass = grass + v
            end
        end
        return grass
    end
    -- grass tiles nearest the anchors first, as places to centre a pasture on
    local cands, cut = {}, false
    local deadline = until_clock or (os.clock() + PASTURE_SEARCH_SECONDS)
    for _, a in ipairs(anchors) do
        for z = a.z - PASTURE_LEVELS, a.z + PASTURE_LEVELS do
            if os.clock() > deadline then cut = true break end
            for y = a.y - PASTURE_RADIUS, a.y + PASTURE_RADIUS, 2 do
                for x = a.x - PASTURE_RADIUS, a.x + PASTURE_RADIUS, 2 do
                    if tile(x, y, z) == 1 then
                        table.insert(cands, {x = x, y = y, z = z,
                                             d = math.abs(a.x - x) + math.abs(a.y - y) + 3 * math.abs(a.z - z)})
                    end
                end
            end
        end
    end
    if #cands == 0 then
        return nil, (cut and 'search cut short: ' or '') .. 'no living grass the dwarves can walk to near the fort\'s surface entrances', cut
    end
    table.sort(cands, function(p, q)
        if p.d ~= q.d then return p.d < q.d end
        if p.z ~= q.z then return p.z > q.z end
        if p.y ~= q.y then return p.y < q.y end
        return p.x < q.x
    end)
    local s0 = math.max(PASTURE_MIN_SIDE, math.ceil(math.sqrt(want)))
    for i, c in ipairs(cands) do
        if os.clock() > deadline then cut = true break end
        for side = s0, PASTURE_BIG_SIDE, 3 do
            local x0, y0 = c.x - side // 2, c.y - side // 2
            local g = rect(x0, y0, c.z, side, side)
            if g == nil then break end                  -- (a bigger square holds the same blocked tile)
            if g >= want then return {x = x0, y = y0, z = c.z, w = side, h = side, grass = g} end
        end
    end
    return nil, (cut and 'search cut short: ' or '')
        .. ('no single patch near the fort with %d tiles of grass the dwarves can reach'):format(want), cut
end

-- Make pasture zones for about `tiles` tiles of grass. Returns the zones made.
-- One zone big enough when there's room for it; else the old way (several
-- patches), but never one smaller than the hungriest waiting animal needs.
function make_pasture(params, dry_run)
    OFFSET = elevation_offset()
    local want = math.tointeger(tonumber(params.tiles)) or 0
    local data = load_projects()
    local reserved = {}
    for _, p in ipairs(open_projects(data)) do table.insert(reserved, p.area) end
    local need = 20
    pcall(function()
        local soc = reqscript('ai-society')
        for _, u in ipairs(soc.unpastured_grazers()) do need = math.max(need, soc.grazer_tiles(u)) end
    end)
    local spots, why = {}, nil
    local big, why_big, cut = find_pasture_rect(math.max(want, need), reserved)
    if big then
        spots = {big}
    else
        -- no room for the whole herd in one: pastures that each feed at least
        -- the hungriest animal (the herd is shared out over them)
        local got, taken, stop = 0, {}, os.clock() + 2 * PASTURE_SEARCH_SECONDS
        for _, r in ipairs(reserved) do table.insert(taken, r) end
        while got < want and #spots < PASTURE_MAX_ZONES do
            if os.clock() > stop then cut = true break end
            local r, _, cut_r = find_pasture_rect(need, taken, stop)
            if cut_r then cut = true end
            if not r then break end
            table.insert(spots, r)
            table.insert(taken, {x1 = r.x, y1 = r.y, x2 = r.x + r.w - 1, y2 = r.y + r.h - 1, z = r.z})
            got = got + r.grass
        end
        if #spots == 0 then why = why_big end
    end
    local made, tiles, refused = {}, 0, 0
    for _, sp in ipairs(spots) do
        local cell = {{x = 0, y = 0, text = ('n{name="%s"}(%dx%d)'):format(PASTURE_NAME, sp.w, sp.h)}}
        if qf_try('zone', cell, sp.z, sp.x, sp.y, dry_run) then
            table.insert(made, {x = sp.x, y = sp.y, z = sp.z, elevation = ez(sp.z), w = sp.w, h = sp.h})
            tiles = tiles + sp.w * sp.h
        else
            refused = refused + 1
        end
    end
    if tiles == 0 then
        return {ok = false, timed_out = cut or nil, error = why or (#spots == 0
            and ((cut and 'search cut short: ' or '') .. 'no free patch of living grass (3x3 or more) near the fort\'s surface entrances')
            or ('the game refused the pasture on %d spot(s)'):format(refused))}
    end
    return {ok = true, dry_run = dry_run or nil, zones = made, tiles = tiles,
            refused = refused > 0 and refused or nil, timed_out = cut or nil}
end
