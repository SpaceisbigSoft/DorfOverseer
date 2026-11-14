-- ai-bridge-design: the Design track's bridge actions (D0): candidate sites
-- for a landmark (blueprint_sites), a drawing built on one (build_blueprint),
-- a surface landmark's next stage (landmark_step), and the report's
-- `landmarks` section. The work is ai-builder's (ai-builder-landmarks.lua);
-- the format is ai-blueprints'. Here the arguments are checked, as
-- act_start_project checks its own (int_in, the name pattern, the deity).
--
-- A part of ai-bridge.lua, loaded by it into its own environment: what is
-- global here is the bridge's, and the bridge's shared helpers (reject,
-- int_in, whole_number, sorted_keys, get_date, ...) are at hand. Not a
-- command of its own.
--
-- No coordinates leave the bridge: a site goes out as an id and words, and
-- a refusal's positions are on the drawing's own grid.

if not BRIDGE_VERSION then qerror('ai-bridge-design is a part of ai-bridge; run ai-bridge') end
PART_VERSIONS = PART_VERSIONS or {}; PART_VERSIONS['ai-bridge-design'] = '0.105.46'   -- (0.105.26) bumped with BRIDGE_VERSION

-- design.LANDMARK_KINDS (brain/design.py)
LANDMARK_KINDS = {'descent', 'god_hall', 'ziggurat', 'chronicle_hall', 'great_hall', 'tower', 'necropolis',
                  'gate_hall', 'garden_court'}
local KIND_SET = {}
for _, k in ipairs(LANDMARK_KINDS) do KIND_SET[k] = true end

BP_CAP_MIN, BP_CAP_MAX = 400, 2500

local function purpose_of(a)
    if type(a.purpose) ~= 'string' or not KIND_SET[a.purpose] then
        return nil, 'purpose must be one of: ' .. table.concat(LANDMARK_KINDS, ', ')
    end
    return a.purpose
end

-- blueprint_sites {env = {w 5-31, h 5-31, levels 1-5, ground}, purpose, n 1-4}:
-- up to n sites, each an id and words (lua/ai-builder-landmarks.lua).
function act_blueprint_sites(a)
    local env = type(a.env) == 'table' and a.env or nil
    if not env then return reject('env must be {w, h, levels, ground}') end
    local e = {w = int_in(env.w, 5, 31), h = int_in(env.h, 5, 31), levels = int_in(env.levels, 1, 5),
               ground = (env.ground == 'rock' or env.ground == 'surface') and env.ground or nil}
    if not e.w or not e.h then return reject('env.w and env.h must be 5-31') end
    if not e.levels then return reject('env.levels must be 1-5') end
    if not e.ground then return reject('env.ground must be "rock" or "surface"') end
    local purpose, perr = purpose_of(a)
    if not purpose then return reject(perr) end
    local n = 4
    if a.n ~= nil then
        n = int_in(a.n, 1, 4)
        if not n then return reject('n must be 1-4') end
    end
    return reqscript('ai-builder').landmark_sites(e, purpose, n)
end

-- build_blueprint {bp, site 'S1'-'S4', name, purpose, cap 400-2500, deity_hf?,
-- by 'ai'/'library', dry_run}: the drawing checked on the site, then begun.
function act_build_blueprint(a)
    if type(a.bp) ~= 'table' then return reject('bp must be a blueprint object') end
    if type(a.site) ~= 'string' or not a.site:match('^S[1-4]$') then return reject('site must be S1-S4') end
    if type(a.name) ~= 'string' or not a.name:match("^[A-Za-z' ]+$") or #a.name > 40 then
        return reject('name: letters, spaces and apostrophes, up to 40')
    end
    local purpose, perr = purpose_of(a)
    if not purpose then return reject(perr) end
    local cap = int_in(a.cap, BP_CAP_MIN, BP_CAP_MAX)
    if not cap then return reject(('cap must be %d-%d'):format(BP_CAP_MIN, BP_CAP_MAX)) end
    local okl, BPM = pcall(reqscript, 'ai-blueprints')
    if okl and type(BPM) == 'table' and type(BPM.BP_LIMITS) == 'table' and BPM.BP_LIMITS.cost_max then
        cap = math.min(cap, BPM.BP_LIMITS.cost_max)
    end
    if a.by ~= 'ai' and a.by ~= 'library' then return reject('by must be "ai" or "library"') end
    local deity
    if a.deity_hf ~= nil then
        deity = whole_number(a.deity_hf)
        if not deity or not df.historical_figure.find(deity) then return reject('no such deity') end
    end
    local meta = {name = a.name, purpose = purpose, by = a.by, cap = cap, deity_hf = deity}
    return reqscript('ai-builder').build_landmark(a.bp, a.site, meta, get_date(), a.dry_run == true)
end

-- landmark_step {landmark_id, dry_run}: a surface landmark's next stage.
function act_landmark_step(a)
    local id = int_in(a.landmark_id, 1, 1000000)
    if not id then return reject('landmark_id must be a landmark\'s number') end
    return reqscript('ai-builder').landmark_step(id, a.dry_run == true)
end

-- The report's `landmarks` section.
function get_landmarks()
    return reqscript('ai-builder').landmarks_report()
end

-- version_info's mirror check (brain/blueprint.py against ai-blueprints):
-- the limits and the legend's item names, or nil when the module won't load.
function blueprint_mirror()
    local ok, BPM = pcall(reqscript, 'ai-blueprints')
    if not ok or type(BPM) ~= 'table' then return nil, nil end
    local limits = type(BPM.BP_LIMITS) == 'table' and BPM.BP_LIMITS or nil
    local items = type(BPM.ITEMS) == 'table' and sorted_keys(BPM.ITEMS) or nil
    return limits, items
end
