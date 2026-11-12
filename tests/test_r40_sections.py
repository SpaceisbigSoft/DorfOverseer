"""(0.105.40, Phase 13e E3) The full report made cheaper without changing
what it says: the per-report shared walks (REPORT_CTX, lua/ai-util.lua), the
gear report's one decode of each item, the threats' world-constant evil civ,
the deep section's cavern blocks found again by position, and the projects
decoded once a report.

Each changed section is run as it was (`git show merge39:<file>`) and as it
is now, on the same fake world, and the two outputs compared in full (and
again inside a report, where the walks are shared). The purely mechanical
switches (a module's walks of the units through the report's one walk) are
proved by reverting the switch in the new source and finding the old one.

    python tests/test_r40_sections.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

LUA_DIR = ROOT / "lua"
BASE_REF = "b1fa58f"   # (delivery) the merge39 commit E3 started from, pinned


VERSION_RE = re.compile(r"'0\.105\.\d+'")


def new(name: str) -> str:
    # (delivery) the version marks are bumped each round: compared without them
    return VERSION_RE.sub("'V'", (LUA_DIR / name).read_text(encoding="utf-8"))


def old(name: str) -> str | None:
    try:
        return subprocess.run(["git", "show", f"{BASE_REF}:lua/{name}"], cwd=ROOT, capture_output=True,
                              check=True, text=True, encoding="utf-8").stdout and VERSION_RE.sub("'V'", subprocess.run(
            ["git", "show", f"{BASE_REF}:lua/{name}"], cwd=ROOT, capture_output=True,
            check=True, text=True, encoding="utf-8").stdout)
    except Exception:  # noqa: BLE001
        return None


HAVE_OLD = old("ai-util.lua") is not None


# ---------------------------------------------------------------------------
# The fake world: units of every kind the threats, the military and the deep
# section look at, squads with gear, DF's equipment lists, map blocks. Fresh
# for each run (the sections write to the save), with counters of the walks.

FAKE = r"""
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v)
                       local n = #self
                       if at == '#' then at = n end
                       for i = n, at + 1, -1 do self[i] = self[i - 1] end
                       self[at] = v end,
                   erase = function(self, at)
                       local n = #self
                       for i = at, n - 2 do self[i] = self[i + 1] end
                       self[n - 1] = nil end}})
end
local function ipairs0(t)
    local mt = type(t) == 'table' and getmetatable(t)
    if type(t) == 'table' and (rawget(t, 0) ~= nil or (mt and mt.__vec0)) then
        local i = -1
        return function() i = i + 1; local v = t[i]; if v ~= nil then return i, v end end
    end
    return ipairs(t)
end
local function copy(v)
    if type(v) ~= 'table' then return v end
    local o = {}
    for k, x in pairs(v) do o[k] = copy(x) end
    return o
end

return function()
    local C = {citizens = 0, active = 0, decode = 0, entities = 0, blocks = 0, getblock = 0, site_get = 0}
    -- the units
    local function unit(id, p, extra)
        local u = {id = id, race = 1, civ_id = p.civ or 1, pos = p.pos or {x = 10 + id, y = 20, z = 120},
                   flags1 = {caged = p.caged, chained = false, on_ground = p.down}, profession = p.prof or 0,
                   path = {goal = p.goal or 0}, status = {labors = {[7] = p.rescuer}},
                   military = {squad_id = p.squad or -1, squad_position = p.squad_pos or -1},
                   health = p.hurt and {flags = {needs_healthcare = true}} or nil,
                   job = {current_job = nil}, enemy = {normal_race = p.were and 2 or -1, caste_flags = {}},
                   inventory = vec(p.inv or {}), relationship_ids = {Mother = p.mother or -1},
                   body = {size_info = {size_cur = 5000}}, mood = p.mood or -1, _p = p}
        for k, v in pairs(extra or {}) do u[k] = v end
        return u
    end
    local units = {
        unit(1, {isCitizen = true, isActive = true}),
        unit(2, {isCitizen = true, isActive = true, rescuer = true, mood = 1, pos = {x = 30, y = 40, z = 160}}),
        unit(3, {isCitizen = true, isActive = true, squad = 1, squad_pos = 0}),
        unit(4, {isCitizen = true, isActive = true, squad = 1, squad_pos = 1, hurt = true, down = true}),
        unit(5, {isCitizen = true, isActive = true, squad = 2, squad_pos = 0, isBloodsucker = true}),
        unit(6, {isCitizen = true, isActive = true, isBaby = true, mother = 3}),
        unit(7, {isCitizen = true, isActive = true, insane = true, isNightCreature = true, were = true}),
        unit(20, {isActive = true, caged = true, isInvader = true, civ = 9}),
        unit(21, {isActive = true, prof = 5, civ = 9}),
        unit(22, {isActive = true, isUndead = true, civ = 9, pos = {x = 80, y = 80, z = 155}}),
        unit(23, {isActive = true, isDanger = true, isGreatDanger = true, isTitan = true, pos = {x = 90, y = 10, z = 158}}),
        unit(24, {isActive = true, isDead = true, isDanger = true}),
        unit(25, {isActive = true, isForgottenBeast = true, pos = {x = 5, y = 5, z = 40}}),
        unit(26, {isActive = true, isHidden = true, isDemon = true}),
        unit(27, {isActive = true, goal = 2, civ = 9}),
    }
    local active = vec(units)
    local by_id = {}
    for _, u in ipairs(units) do by_id[u.id] = u end
    -- the items
    local IT = {WEAPON = 1, ARMOR = 2, HELM = 3, PANTS = 4, GLOVES = 5, SHOES = 6, SHIELD = 7, AMMO = 8, BAR = 9,
                QUIVER = 10, FLASK = 11, CORPSE = 12, CORPSEPIECE = 13}
    local item_type = {}
    for k, v in pairs(IT) do item_type[k] = v; item_type[v] = k end
    local function item(id, kind, mat, sub, flags, extra)
        local it = {id = id, _type = IT[kind], mat = mat, flags = flags or {}, _sub = sub and sub.n or 0,
                    subtype = sub, pos = {x = id % 50, y = 30, z = 120}, handedness = {[0] = id % 2 == 0, [1] = id % 2 == 1}}
        function it:getType() return self._type end
        function it:getSubtype() return self._sub end
        function it:getMaterial() return self.mat and 0 or 420 end
        function it:getMaterialIndex() return self.mat == 'IRON' and 1 or self.mat == 'STEEL' and 2 or 7 end
        function it:getStackSize() return 3 end
        for k, v in pairs(extra or {}) do it[k] = v end
        return it
    end
    local AXE = {id = 'ITEM_WEAPON_AXE_BATTLE', n = 1, armorlevel = 0}
    local XBOW = {id = 'ITEM_WEAPON_CROSSBOW', n = 2, ranged_ammo = 'BOLT'}
    local PICK = {id = 'ITEM_WEAPON_PICK', n = 3}
    local MAIL = {id = 'ITEM_ARMOR_MAIL_SHIRT', n = 1, armorlevel = 2}
    local BOLT = {id = 'ITEM_AMMO_BOLTS', n = 1}
    local held_axe = item(101, 'WEAPON', 'IRON', AXE, {in_inventory = true})
    local worn_mail = item(201, 'ARMOR', 'STEEL', MAIL, {in_inventory = true})
    units[3].inventory = vec({{item = held_axe, mode = 1}, {item = worn_mail, mode = 2}})
    held_axe._holder, worn_mail._holder = units[3], units[3]
    local other = {
        WEAPON = vec({held_axe, item(102, 'WEAPON', 'IRON', AXE), item(103, 'WEAPON', 'STEEL', AXE),
                      item(104, 'WEAPON', nil, XBOW), item(105, 'WEAPON', 'IRON', PICK),
                      item(106, 'WEAPON', 'IRON', AXE, {forbid = true}), item(107, 'WEAPON', 'COPPER', AXE),
                      item(108, 'WEAPON', 'IRON', AXE, {in_job = true}), item(109, 'WEAPON', 'IRON', XBOW)}),
        ARMOR = vec({worn_mail, item(202, 'ARMOR', 'IRON', MAIL), item(203, 'ARMOR', nil, MAIL)}),
        HELM = vec({item(301, 'HELM', 'IRON', {id = 'ITEM_HELM_HELM', n = 1})}),
        PANTS = vec({item(401, 'PANTS', 'IRON', {id = 'ITEM_PANTS_GREAVES', n = 1})}),
        GLOVES = vec({item(501, 'GLOVES', 'IRON', {id = 'ITEM_GLOVES_GAUNTLETS', n = 1}),
                      item(502, 'GLOVES', 'IRON', {id = 'ITEM_GLOVES_GAUNTLETS', n = 1})}),
        SHOES = vec({item(601, 'SHOES', 'IRON', {id = 'ITEM_SHOES_BOOTS', n = 1})}),
        SHIELD = vec({item(701, 'SHIELD', nil, {id = 'ITEM_SHIELD_SHIELD', n = 1})}),
        AMMO = vec({item(801, 'AMMO', 'IRON', BOLT), item(802, 'AMMO', nil, BOLT, {forbid = true})}),
        BAR = vec({item(901, 'BAR', 'IRON'), item(902, 'BAR', 'PIG_IRON'), item(903, 'BAR', 'GOLD')}),
        QUIVER = vec({item(1001, 'QUIVER')}), FLASK = vec({item(1101, 'FLASK')}),
        CORPSE = vec({item(1201, 'CORPSE', nil, nil, nil, {pos = {x = 3, y = 3, z = 170}})}), CORPSEPIECE = vec({}),
    }
    setmetatable(other, {__index = function(t, k) local v = vec({}); rawset(t, k, v); return v end})
    local function ids(l) return vec(l) end
    local equipment = {
        items_assigned = {WEAPON = ids({101}), ARMOR = ids({201}), HELM = ids({}), PANTS = ids({}), GLOVES = ids({}),
                          SHOES = ids({}), SHIELD = ids({})},
        items_unassigned = {WEAPON = ids({102, 103, 104, 106, 107, 108, 109}), ARMOR = ids({202, 203}), HELM = ids({301}),
                            PANTS = ids({401}), GLOVES = ids({501, 502}), SHOES = ids({601}), SHIELD = ids({701}),
                            QUIVER = ids({1001}), FLASK = ids({1101})},
        items_unmanifested = {WEAPON = ids({}), ARMOR = ids({}), HELM = ids({}), PANTS = ids({}), GLOVES = ids({}),
                              SHOES = ids({}), SHIELD = ids({})},
        work_weapons = ids({105}), update = {},
    }
    -- the squads
    local UC = {weapon = 0, body = 1, head = 2, pants = 3, gloves = 4, shoes = 5, shield = 6, _last_item = 6}
    local function spec(t, sub, assigned, cls, choice)
        return {item_type = t, item_subtype = sub or -1, mattype = -1, matindex = -1, material_class = cls or 0,
                indiv_choice = choice or {melee = true, ranged = false}, assigned = vec(assigned or {})}
    end
    local function uniform(w, extra)
        local u = {}
        for c = 0, 6 do u[c] = vec({}) end
        u[0] = vec(w)
        for c, l in pairs(extra or {}) do u[c] = vec(l) end
        return u
    end
    local function position(hf, w, extra, assigned)
        return {occupant = hf, equipment = {assigned_items = vec(assigned or {}), uniform = uniform(w, extra),
                                            quiver = -1, flask = -1}}
    end
    local sq1 = {id = 1, cur_routine_idx = 1, orders = vec({}), ammo = {ammunition = vec({}), ammo_items = vec({})},
                 positions = vec({position(1003, {spec(1, 1, {101}, 1)}, {[1] = {spec(2, -1, {201}, 2)}}, {101, 201}),
                                  position(1004, {spec(1, 1, {}, 1)}, {[4] = {spec(5, -1, {})}, [6] = {spec(7, -1, {})}}),
                                  position(-1, {})})}
    local sq2 = {id = 2, cur_routine_idx = 0, orders = vec({}),
                 ammo = {ammunition = vec({{amount = 50, assigned = vec({801})}}), ammo_items = vec({801})},
                 positions = vec({position(1005, {spec(1, 2, {}, 0, {ranged = true, melee = false})})})}
    local squads = {[1] = sq1, [2] = sq2}
    local hfs = {[1003] = {unit_id = 3}, [1004] = {unit_id = 4}, [1005] = {unit_id = 5}}
    local fort = {squads = vec({1, 2}), uniforms = vec({{name = 'Metal'}})}
    -- the map: 3 caverns' blocks among plain ones
    local blocks = {}
    local bpos = {}
    for z = 30, 44 do
        for bx = 0, 2 do
            for by = 0, 1 do
                local gf = (z <= 34) and 11 or (z <= 39 and 12 or (z == 44 and 13 or -1))
                local des = {}
                for x = 0, 15 do des[x] = {}; for y = 0, 15 do des[x][y] = {hidden = (x + y + z) % 3 == 0} end end
                local b = {map_pos = {x = bx * 16, y = by * 16, z = z}, global_feature = gf, designation = des}
                table.insert(blocks, b)
                bpos[bx .. ',' .. by .. ',' .. z] = b
            end
        end
    end
    local map_blocks = setmetatable({}, {__vec0 = true, __len = function() return #blocks end,
        __index = function(_, i) if i == 0 then C.blocks = C.blocks + 1 end return blocks[i + 1] end})
    local feats = {}
    local fidx = {}
    for i, gid in ipairs({11, 12, 13}) do
        feats[i - 1] = {start_depth = i - 1, flags = {Discovered = gid ~= 13}, _kind = 'cavern'}
        fidx[i - 1] = gid
    end
    local store = {}
    local df = {
        item_type = item_type, uniform_category = UC, items_other_id = setmetatable({}, {__index = function(_, k) return k end}),
        inv_item_role_type = {[1] = 'Weapon', [2] = 'Worn', [3] = 'Hauled', Weapon = 1, Worn = 2, Hauled = 3},
        entity_material_category = {[0] = 'None', [1] = 'WeaponMelee', [2] = 'Armor'},
        job_skill = setmetatable({}, {__index = function(_, k) return k end}),
        historical_entity_type = {Civilization = 0, [0] = 'Civilization'},
        profession = {[5] = 'THIEF'}, unit_path_goal = {[2] = 'SeekKidnapVictim'},
        unit_labor = {RECOVER_WOUNDED = 7}, mood_type = {[1] = 'Fey'}, flow_type = {[1] = 'Fire', [2] = 'MaterialDust'},
        trap_type = {Lever = 1}, civzone_type = {Barracks = 1, ArcheryRange = 2},
        building_type = setmetatable({Workshop = 1, [1] = 'Workshop'}, {__index = function() return nil end}),
        workshop_type = {MetalsmithsForge = 1, MagmaForge = 2},
        layer_type = {[0] = 'Cavern1', [1] = 'Cavern2', [2] = 'Cavern3'},
        feature_init_subterranean_from_layerst = {is_instance = function(_, f) return f._kind == 'cavern' end},
        feature_init_magma_core_from_layerst = {is_instance = function() return false end},
        feature_init_underworld_from_layerst = {is_instance = function() return false end},
        squad_order_kill_listst = {is_instance = function() return false end},
        squad_order_defend_burrowsst = {is_instance = function() return false end},
        squad = {find = function(id) return squads[id] end},
        historical_figure = {find = function(id) return hfs[id] end},
        unit = {find = function(id) return by_id[id] end},
        item = {find = function() return nil end},
        historical_entity = {find = function(id) if id == 10 then return fort end return nil end},
        creature_raw = {find = function() return {creature_id = 'GOBLIN'} end},
        world_region = {find = function() return {evil = true, reanimating = true} end},
        global = {
            cur_year = 120, cur_year_tick = 5000, pause_state = false,
            flows = vec({{density = 5, type = 1, pos = {x = 12, y = 20, z = 120}},
                         {density = 3, type = 2, pos = {x = 31, y = 40, z = 160}, guide_id = 4, mat_type = 0, mat_index = 1}}),
            plotinfo = {civ_id = 1, group_id = 10, site_id = 7, equipment = equipment,
                        alerts = {routines = vec({{name = 'Off duty'}, {name = 'Staggered training'}}), list = vec({})},
                        burrows = {list = vec({})}},
            world = {
                cur_savegame = {save_dir = 'region9'},
                units = {active = setmetatable({}, {__vec0 = true, __len = function() return #active end,
                    __index = function(_, i) if i == 0 then C.active = C.active + 1 end return active[i] end})},
                items = {other = other, all = vec({})},
                entities = {all = setmetatable({}, {__vec0 = true, __len = function() return 3 end,
                    __index = function(_, i)
                        if i == 0 then C.entities = C.entities + 1 end
                        local l = {{type = 0, entity_raw = {code = 'PLAINS'}}, {type = 1, entity_raw = {code = 'X'}},
                                   {type = 0, entity_raw = {code = 'EVIL'}}}
                        return l[i + 1] end})},
                buildings = {all = vec({}), other = setmetatable({}, {__index = function() return vec({}) end})},
                jobs = {list = {next = {item = {pos = {x = 13, y = 20, z = 120}}, next = nil}}},
                world_data = {moon_phase = 3},
                raws = {itemdefs = {weapons = vec({{id = 'ITEM_WEAPON_CROSSBOW', subtype = 2}})}},
                features = {map_features = vec({feats[0], feats[1], feats[2]}),
                            feature_global_idx = setmetatable({}, {__index = function(_, i) return fidx[i] end})},
                map = {map_blocks = map_blocks, region_z = 100},
            },
        },
    }
    local function is_fn(k)
        return function(u, ...) local p = type(u) == 'table' and u._p; return p and p[k] or false end
    end
    local dfhack = {
        units = setmetatable({
            getCitizens = function(exclude_residents, include_insane)
                C.citizens = C.citizens + 1
                local out = {}
                for _, u in ipairs(units) do
                    if u._p.isCitizen and (include_insane or not u._p.insane) then table.insert(out, u) end
                end
                return out
            end,
            getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end,
            getReadableName = function(u) return 'Unit ' .. u.id end,
            getNominalSkill = function(u, k) return (u.id * 3 + #tostring(k)) % 12 end,
            getStressCategory = function(u) return u.id % 7 end,
            getContainer = function() return nil end,
            isCitizen = is_fn('isCitizen'),
        }, {__index = function(_, k) return is_fn(k) end}),
        items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end,
                 getHolderUnit = function(it) return it._holder end,
                 getContainer = function() return nil end,
                 getDescription = function(it) return 'item ' .. it.id end,
                 getSubtypeDef = function(t, st) if t == 1 and st == 2 then return {id = 'ITEM_WEAPON_CROSSBOW', ranged_ammo = 'BOLT'} end
                                                 if t == 1 and st == 1 then return {id = 'ITEM_WEAPON_AXE_BATTLE'} end return nil end},
        matinfo = {decode = function(it, idx)
            C.decode = C.decode + 1
            if type(it) == 'table' and it.mat then
                return {inorganic = {id = it.mat}, material = {flags = {IS_METAL = true}}}
            end
            return {material = {flags = {WOOD = type(it) == 'table' and it.id == 104 or false}},
                    toString = function() return 'dust' end}
        end},
        maps = {getTileFlags = function(x, y, z) return {outside = z >= 150, feature_global = z <= 45} end,
                getWalkableGroup = function(p) return (p.z <= 45 and p.x % 2 == 0) and 1 or (p.z > 45 and 1 or 3) end,
                getTileBiomeRgn = function() return 1, 1 end,
                getRegionBiome = function() return {evilness = 40, region_id = 2} end,
                canWalkBetween = function() return true end,
                getTileType = function() return nil end,
                getTileSize = function() return 48, 32, 200 end,
                getTileBlock = function(x, y, z)
                    if type(x) == 'table' then x, y, z = x.x, x.y, x.z end
                    C.getblock = C.getblock + 1
                    return bpos[(x // 16) .. ',' .. (y // 16) .. ',' .. z]
                end},
        military = {getSquadName = function(id) return 'Squad ' .. id end},
        buildings = {findAtTile = function() return nil end},
        persistent = {getSiteData = function(k, d) C.site_get = C.site_get + 1; local v = store[k]; if v == nil then return d end return copy(v) end,
                      saveSiteData = function(k, v) store[k] = copy(v) end},
        filesystem = {mtime = function() return nil end},
        findScript = function() return nil end,
        df2utf = function(s) return s end,
    }
    local base = {df = df, dfhack = dfhack, ipairs = ipairs0, C = C, store = store,
                  xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end,
                  xy2pos = function(x, y) return {x = x, y = y} end}
    return setmetatable(base, {__index = _G})
end
"""

# Loads a set of modules (name -> source) over one fake world: reqscript of
# any of them answers its environment (loaded on first ask; a cycle gets the
# environment being loaded), anything else is an error (the callers pcall).
LOADER = r"""
local base, srcs = ...
local envs = {}
local function req(name)
    if envs[name] then return envs[name] end
    local src = srcs[name]
    if not src then error('no ' .. tostring(name) .. ' here') end
    local env = setmetatable({}, {__index = base})
    envs[name] = env
    assert(load(src, name, 't', env))()
    return env
end
base.reqscript = req
return req
"""

DEEP_EQ = r"""
local function eq(a, b, path, seen)
    if type(a) ~= type(b) then return false, path .. ': ' .. type(a) .. ' vs ' .. type(b) end
    if type(a) ~= 'table' then
        if a == b or (a ~= a and b ~= b) then return true end
        if type(a) == 'number' and math.type(a) ~= math.type(b) then return false, path .. ': number subtype' end
        return false, path .. ': ' .. tostring(a) .. ' vs ' .. tostring(b)
    end
    seen = seen or {}
    if seen[a] == b then return true end
    seen[a] = b
    for k, v in pairs(a) do
        local ok, why = eq(v, b[k], path .. '.' .. tostring(k), seen)
        if not ok then return false, why end
    end
    for k, v in pairs(b) do
        if a[k] == nil then return false, path .. '.' .. tostring(k) .. ': missing on the left' end
    end
    return true
end
return eq
"""


def fresh():
    lua = LuaRuntime(unpack_returned_tuples=True)
    make = lua.execute(FAKE)
    return lua, make


def deep_eq(lua, a, b):
    ok, why = lua.execute(DEEP_EQ)(a, b, "out")
    return ok, why


def to_py(v, depth=0):
    """A Lua value as plain Python (tables: dicts keyed by str(key))."""
    if depth > 40:
        return "<deep>"
    if hasattr(v, "items") and not isinstance(v, (dict, str)):
        return {str(k): to_py(x, depth + 1) for k, x in v.items()}
    if isinstance(v, float) and v.is_integer():
        return ("float", v)
    return v


def first_diff(a, b, path="out"):
    if type(a) is not type(b):
        return f"{path}: {a!r} vs {b!r}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k) != b.get(k):
                return first_diff(a.get(k), b.get(k), f"{path}.{k}")
        return None
    return None if a == b else f"{path}: {a!r} vs {b!r}"


def load_set(lua, base, srcs: dict):
    t = lua.table_from({k: v for k, v in srcs.items()})
    return lua.execute(LOADER, base, t)


# ---------------------------------------------------------------------------
# ai-util's shared walks

@test("REPORT_CTX: inside a report the citizens are asked once per set of arguments (a fresh copy each), "
      "the active units and all items walked once; outside every call walks afresh, the vectors themselves")
def _():
    lua, make = fresh()
    base = make()
    req = load_set(lua, base, {"ai-util": new("ai-util.lua")})
    U = req("ai-util")
    C = base.C
    out1 = U.citizens(False, True)
    assert len(out1) == 7 and C.citizens == 1
    U.citizens(False, True)
    assert C.citizens == 2                        # outside a report: afresh
    assert lua.eval('rawequal')(U.units_active(), base.df["global"].world.units.active)
    ctx = U.report_begin()
    a, b = U.citizens(False, True), U.citizens(False, True)
    c = U.citizens()
    assert C.citizens == 4, C.citizens            # (false, true) once, () once
    assert len(a) == 7 and len(c) == 6 and a is not b
    assert [u.id for u in a.values()] == [u.id for u in out1.values()]
    lua.execute("local a = ...; table.remove(a, 1)", a)     # a caller changing its copy changes no one else's
    assert len(U.citizens(False, True)) == 7 and C.citizens == 4
    l1, l2 = U.units_active(), U.units_active()
    assert lua.eval("rawequal")(l1, l2) and len(l1) == 15 and C.active == 1, (len(l1), C.active)
    assert [u.id for u in l1.values()] == [base.df["global"].world.units.active[i].id for i in range(15)]
    assert ctx.walks.citizens == 2 and ctx.walks.units == 1
    calls = lua.eval("{n = 0}")
    f = lua.eval("function(c) return function() c.n = c.n + 1; return nil end end")(calls)
    assert U.report_memo("k", f) is None and U.report_memo("k", f) is None and calls.n == 1   # nil kept too
    U.report_end()
    assert U.REPORT_CTX is None
    U.citizens(True)
    assert C.citizens == 5


@test("deep_copy: the same keys, values (integer or float), nesting and metatables; the copy is its own")
def _():
    lua, make = fresh()
    base = make()
    U = load_set(lua, base, {"ai-util": new("ai-util.lua")})("ai-util")
    ok, why = lua.execute(r"""
        local U = ...
        local mt = {__index = {x = 1}}
        local shared = {9}
        local v = {next_id = 4, f = 1.5, list = {{id = 1, area = {x1 = 1, z = 2}}, {id = 2, phase = 'done'}},
                   m = setmetatable({}, mt), a = shared, b = shared, [3] = 'three', flag = false}
        local c = U.deep_copy(v)
        assert(c ~= v and c.list ~= v.list and c.list[1].area ~= v.list[1].area)
        assert(getmetatable(c.m) == mt and c.a == c.b and c.a ~= shared)
        c.list[1].area.x1 = 99
        assert(v.list[1].area.x1 == 1)
        c.list[1].area.x1 = 1
        assert(math.type(c.next_id) == 'integer' and math.type(c.f) == 'float')
        return true, nil
    """, U)
    assert ok, why


# ---------------------------------------------------------------------------
# The mechanical switches: each module's walks of the units through the
# report's one walk. Reverting the switch in the new source gives the old.

MECHANICAL = ["ai-military.lua", "ai-diplomacy.lua", "ai-health.lua", "ai-nobles.lua", "ai-labor.lua",
              "ai-society.lua", "ai-society-burrows.lua", "ai-trade.lua", "ai-water.lua", "ai-homes.lua"]
HELPER = '''
-- (0.105.40 E3) inside a report, the report's one walk of the units
-- (ai-util REPORT_CTX: the same units, same order); outside one, afresh
local function report_citizens(...)
    if U.REPORT_CTX and U.citizens then return U.citizens(...) end
    return dfhack.units.getCitizens(...)
end
local function report_units()
    if U.REPORT_CTX and U.units_active then return U.units_active() end
    return df.global.world.units.active
end
'''


def revert_switch(src: str) -> str:
    assert src.count(HELPER) == 1
    src = src.replace(HELPER, "")
    src = src.replace("report_citizens(", "dfhack.units.getCitizens(")
    src = src.replace("ipairs(report_units())", "ipairs(df.global.world.units.active)")
    src = src.replace("ipairs(units or report_units())", "ipairs(units or df.global.world.units.active)")
    return src


@test("the modules' switch to the report's one walk is the only change (reverted, each is merge39's file)")
def _():
    if not HAVE_OLD:
        print("  (no merge39 here: skipped)")
        return
    for name in MECHANICAL:
        o = old(name)
        assert o is not None, name
        assert revert_switch(new(name)) == o, name
        assert "report_units()" in new(name) or "report_citizens(" in new(name), name


@test("ai-bridge-report: besides REPORT_CTX and the deep blocks, only the switch to the report's one walk")
def _():
    if not HAVE_OLD:
        return
    src = new("ai-bridge-report.lua")
    i = src.index("-- (0.105.40 E3) The per-report shared walks")
    j = src.index("function report_units()", i)
    j = src.index("\nend\n", j) + 5
    src = src[:i] + src[j:].lstrip("\n")
    i = src.index("-- (0.105.40 E3) Which blocks lie in each cavern")
    j = src.index("function get_deep()", i)
    src = src[:i] + src[j:]
    src = src.replace("report_citizens(", "dfhack.units.getCitizens(").replace(
        "ipairs(report_units())", "ipairs(df.global.world.units.active)")
    o = old("ai-bridge-report.lua")
    # the deep section's block sort: the new one keeps positions and tries the kept ones first
    new_sort = src[src.index("    local cave_blocks\n"):src.index("        return cave_blocks[l] or {}")]
    old_sort = o[o.index("    local cave_blocks\n"):o.index("        return cave_blocks[l] or {}")]
    src = src.replace(new_sort, old_sort)
    assert src == o.replace("\n\nREPORT_MEMO = nil\n\n", "\n\nREPORT_MEMO = nil\n"), "ai-bridge-report differs"


# ---------------------------------------------------------------------------
# The sections run as they were and as they are, on the same fake world

def threats_srcs(version: str) -> dict:
    get = old if version == "old" else new
    return {"ai-threats": get("ai-threats.lua"), "ai-util": get("ai-util.lua")}


def run_threats(version: str, inside: bool, times: int = 1):
    lua, make = fresh()
    base = make()
    req = load_set(lua, base, threats_srcs(version))
    T, U = req("ai-threats"), req("ai-util")
    outs = []
    for _ in range(times):
        if inside:
            U.report_begin()
        outs.append(T.survey(lua.eval("tostring")))
        if inside:
            U.report_end()
    return lua, base, outs


@test("threats (fire, prisoners, thieves, undead, were, surface, rescue, caverns): the same report, "
      "outside and inside a report, twice; the units walked once and the world's entities once")
def _():
    if not HAVE_OLD:
        return
    lua, base_o, outs_o = run_threats("old", False, 2)
    for inside in (False, True):
        lua_n, base_n, outs_n = run_threats("new", inside, 2)
        for a, b in zip(outs_o, outs_n):        # (two engines: compared as plain Python)
            pb = to_py(b)
            # (fix41) the evil weather is its own section now (weather_section), not in the survey
            assert "weather" not in pb, pb
            assert to_py(a) == pb, (inside, first_diff(to_py(a), pb))
        if inside:
            assert base_n.C.active == 2, base_n.C.active                # one walk a report, not five
            assert base_n.C.citizens == 2, base_n.C.citizens
    assert base_o.C.active == 10 and base_o.C.citizens == 6, (base_o.C.active, base_o.C.citizens)
    assert base_o.C.entities == 2 and base_n.C.entities == 1, (base_o.C.entities, base_n.C.entities)
    o = to_py(outs_o[0])
    assert o["prisoners"]["caged"] == 1 and o["thieves"]["now"] == 2 and o["undead"]["undead"] == 1, o
    assert o["surface"]["list"] and o["rescue"]["holders"] == 1 and o["thieves"]["evil_civ"] is True, o
    assert o["fire"]["fires"] == 1 and o["were"]["list"] and o["cavern_citizens"]["n"] == 0, o


@test("(fix41) the weather section: the same in two engines, outside a report and inside one (the shared walks)")
def _():
    outs = []
    for inside in (False, True):
        lua, make = fresh()
        base = make()
        req = load_set(lua, base, threats_srcs("new"))
        T, U = req("ai-threats"), req("ai-util")
        if inside:
            U.report_begin()
        outs.append(to_py(T.weather_section()))
        if inside:
            U.report_end()
    a, b = outs
    assert "error" not in a and "evil_cloud" in a and "region" in a, a
    assert a == b, first_diff(a, b)


def military_srcs(version: str) -> dict:
    get = old if version == "old" else new
    return {"ai-military": get("ai-military.lua"), "ai-military-gear": get("ai-military-gear.lua"),
            "ai-util": get("ai-util.lua")}


def run_military(version: str, inside: bool):
    lua, make = fresh()
    base = make()
    req = load_set(lua, base, military_srcs(version))
    M, U = req("ai-military"), req("ai-util")
    if inside:
        U.report_begin()
    r = M.report(lua.eval("tostring"))
    if inside:
        U.report_end()
    G = req("ai-military-gear")
    return lua, base, r, G


@test("military (squads, gear: spare, stray, gaps and why, kit, quivers, flasks; mothers): the same report "
      "as merge39's, outside and inside a report; each item's metal decoded once, not once a count")
def _():
    if not HAVE_OLD:
        return
    _, base_o, ro, _ = run_military("old", False)
    o = to_py(ro)
    g = o["gear"]
    assert "error" not in g, g
    assert g["soldiers"] == 3 and g["armed"] >= 1 and g["spare"]["weapons"] >= 1 and g["bars"], g
    assert g.get("weapon_gaps_why") and g.get("kit") and "error" not in g["kit"], g
    assert g["spare_crossbows"] >= 1 and g["bolts"] == 3 and g["forges"] == 0, g
    assert o["soldier_mothers"], o
    for inside in (False, True):
        _, base_n, rn, G = run_military("new", inside)
        n = to_py(rn)
        assert o == n, (inside, first_diff(o, n))
        assert G.CLAIM_MEMO is None
        assert base_n.C.decode < base_o.C.decode, (base_n.C.decode, base_o.C.decode)
    _, base_n, _, _ = run_military("new", True)
    assert base_n.C.citizens == 1 and base_o.C.citizens == 2, (base_n.C.citizens, base_o.C.citizens)


@test("military gear outside gear_report (an action's own reads): no memo, every item decoded afresh")
def _():
    lua, make = fresh()
    base = make()
    req = load_set(lua, base, military_srcs("new"))
    G = req("ai-military-gear")
    it = base.df["global"].world["items"].other.WEAPON[2]
    n0 = base.C.decode
    G.metal_token(it)
    G.metal_token(it)
    assert base.C.decode == n0 + 2 and G.metal_token(it) == "STEEL"
    r = G.assign_weapons(True, 50)
    assert r.ok and r.dry_run, r


# ---------------------------------------------------------------------------
# The hub's own sections (ai-bridge-report): the deep section's cavern blocks

HUB_ENV = r"""
local base, report_src, util = ...
local env = setmetatable({BRIDGE_VERSION = 'test', txt = tostring,
                          abs_tick = function() return 120 * 403200 + 5000 end,
                          qerror = error}, {__index = base})
env.require = function(n) if n == 'utils' then return {listpairs = function() return function() end end} end error(n) end
env.reqscript = function(n) if n == 'ai-util' and util then return util end error('no ' .. n) end
assert(load(report_src, 'ai-bridge-report', 't', env))()
return env
"""


def hub(version: str, with_util: bool):
    lua, make = fresh()
    base = make()
    util = None
    if with_util:
        util = load_set(lua, base, {"ai-util": (old if version == "old" else new)("ai-util.lua")})("ai-util")
    src = (old if version == "old" else new)("ai-bridge-report.lua")
    env = lua.execute(HUB_ENV, base, src, util)
    return lua, base, env


@test("deep: the second report finds the caverns' blocks again by position (no walk of every block) "
      "and says the same as merge39's walk; a map of another size walks again")
def _():
    if not HAVE_OLD:
        return
    _, base_o, Ho = hub("old", False)
    o1, o2 = to_py(Ho.get_deep()), to_py(Ho.get_deep())
    walks_old = base_o.C.blocks
    assert o1 == o2 and o1["caverns"] and o1["dangers"], o1
    assert any(c["seen"] > 0 for c in o1["caverns"].values()), o1
    for with_util in (False, True):
        lua, base_n, Hn = hub("new", with_util)
        if with_util:
            Hn.report_ctx_begin()
        n1 = to_py(Hn.get_deep())
        if with_util:
            Hn.report_ctx_end()
            Hn.report_ctx_begin()
        n2 = to_py(Hn.get_deep())
        if with_util:
            Hn.report_ctx_end()
        assert n1 == o1 and n2 == o1, first_diff(o1, n2)
        # the layers' walk (once, as before) plus the first deep walk; the second fetched by position
        assert base_n.C.blocks == walks_old - 1, (base_n.C.blocks, walks_old)
        assert base_n.C.getblock > 0
        # a block that moved (another map, same count): the full walk again, the same answer
        Hn.DEEP_BLOCKS.key = "elsewhere"
        n3 = to_py(Hn.get_deep())
        assert n3 == o1 and base_n.C.blocks == walks_old, base_n.C.blocks


@test("others_on_map, moods, dwarf levels: the same as merge39's, inside a report and out")
def _():
    if not HAVE_OLD:
        return
    _, _, Ho = hub("old", False)
    names = ["get_others_on_map", "get_moods", "get_dwarf_levels"]
    outs_o = {}
    for nm in names:
        try:
            outs_o[nm] = to_py(Ho[nm]())
        except Exception as e:  # noqa: BLE001
            outs_o[nm] = ("error", str(e).split(":")[-1])
    for with_util in (False, True):
        _, base_n, Hn = hub("new", with_util)
        if with_util:
            Hn.report_ctx_begin()
        for nm in names:
            try:
                v = to_py(Hn[nm]())
            except Exception as e:  # noqa: BLE001
                v = ("error", str(e).split(":")[-1])
            assert v == outs_o[nm], (nm, with_util, first_diff(outs_o[nm], v) if isinstance(v, dict) else v)
        if with_util:
            Hn.report_ctx_end()
            assert Hn.REPORT_CTX is None
    assert not isinstance(outs_o["get_others_on_map"], tuple), outs_o["get_others_on_map"]


# ---------------------------------------------------------------------------
# The projects: decoded once a report, a copy to each caller, dropped on a save

PROJ_ENV = r"""
local base, src, util, key = ...
local env = setmetatable({PROJECTS_KEY = key, KEEP_CLOSED_PROJECTS = 2}, {__index = base})
env.site_get = function(k) return util.site_get(k, {}) end
env.site_put = function(k, d) return util.site_put(k, d) end
env.util_module = function() return util end
assert(load(src, 'ai-builder-projects', 't', env))()
return env
"""


@test("load_projects: inside a report decoded once, each caller its own copy (a change to one is no one "
      "else's), a save drops it; outside every call decodes; the data as merge39's")
def _():
    if not HAVE_OLD:
        return
    lua, make = fresh()
    base = make()
    U = load_set(lua, base, {"ai-util": new("ai-util.lua")})("ai-util")
    key = "ai-overseer/projects"
    base.store[key] = lua.execute("""return {next_id = 5, list = {{id = 1, kind = 'bedroom', phase = 'dig',
        area = {x1 = 1, y1 = 2, x2 = 3, y2 = 4, z = 5}}, {id = 2, kind = 'well', phase = 'done'}},
        old_areas = {{x1 = 0, y1 = 0, x2 = 1, y2 = 1, z = 1}}}""")
    Pn = lua.execute(PROJ_ENV, base, new("ai-builder-projects.lua"), U, key)
    Po = lua.execute(PROJ_ENV, base, old("ai-builder-projects.lua"), U, key)
    want = to_py(Po.load_projects())
    C = base.C
    n0 = C.site_get
    assert to_py(Pn.load_projects()) == want and C.site_get == n0 + 1
    Pn.load_projects()
    assert C.site_get == n0 + 2                              # outside a report: each call decodes
    U.report_begin()
    a = Pn.load_projects()
    b = Pn.load_projects()
    assert C.site_get == n0 + 3 and to_py(a) == want and to_py(b) == want and a != b
    a.list[1].phase = "furnish"
    a.next_id = 99
    assert to_py(Pn.load_projects()) == want and C.site_get == n0 + 3
    assert Pn.save_projects(a)
    c = Pn.load_projects()
    assert C.site_get == n0 + 4 and c.next_id == 99 and c.list[1].phase == "furnish"
    U.report_end()
    assert to_py(Po.load_projects()) == to_py(c)


# ---------------------------------------------------------------------------
# The hub: REPORT_CTX for the length of build_state, cleared however it ends



@test("build_state: the sections share one walk (REPORT_CTX), and it is cleared after the report, "
      "and after a section that throws (ai-util's too)")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    make = lua.execute(FAKE)
    base = make()
    U = load_set(lua, base, {"ai-util": new("ai-util.lua")})("ai-util")
    hubsrc = new("ai-bridge.lua")
    # the hub's build_state, its REPORT_CTX helpers and a stub report around them
    start = hubsrc.index("local build_state_body\nfunction build_state(")
    end = hubsrc.index("local function ensure_watching()")
    rep = new("ai-bridge-report.lua")
    r0 = rep.index("-- (0.105.40 E3) The per-report shared walks")
    r1 = rep.index("\nend\n", rep.index("function report_units()", r0)) + 5
    chunk = rep[r0:r1] + "\n" + hubsrc[start:end]
    env = lua.execute(r"""
        local base, chunk, util = ...
        local env = setmetatable({}, {__index = base})
        env.reqscript = function(n) if n == 'ai-util' then return util end error('no ' .. n) end
        env.get_dwarves = function() return {total = 1}, nil end
        env.sorted_keys = function(t) local o = {} for k in pairs(t) do o[#o + 1] = k end table.sort(o) return o end
        env.abs_tick = function() return 1000 end
        env.fort_key = function() return 'r#1' end
        env.PULSE_SECTIONS = {}
        env.SECTION_CACHE, env.SECTION_CACHE_DAYS, env.SECTION_REBUILDS = {}, {}, 2
        assert(load(chunk, 'hub', 't', env))()
        return env
    """, base, chunk, U)
    lua.execute(r"""
        local env = ...
        env.SECTIONS = {a = function() return #env.report_citizens(true) end,
                        b = function() return #env.report_citizens(true) + #env.report_units() end,
                        c = function() return env.REPORT_CTX ~= nil and env.REPORT_CTX.util ~= nil end}
    """, env)
    s = env.build_state(False)
    assert s.a == 6 and s.b == 21 and s.c is True, (s.a, s.b, s.c)
    assert base.C.citizens == 1 and base.C.active == 1, (base.C.citizens, base.C.active)
    assert env.REPORT_CTX is None and U.REPORT_CTX is None and env.REPORT_MEMO is None
    lua.execute("local env = ... env.SECTIONS.z = function() error('boom') end", env)
    try:
        env.build_state(False)
        raise AssertionError("no throw")
    except Exception as e:  # noqa: BLE001
        assert "boom" in str(e), e
    assert env.REPORT_CTX is None and U.REPORT_CTX is None and env.REPORT_MEMO is None
    env.report_citizens(True)
    assert base.C.citizens == 3        # (the throwing report's one, then this one, afresh)


if __name__ == "__main__":
    finish()
