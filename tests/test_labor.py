"""Tests for lua/ai-labor.lua (who does what), in a real Lua engine with a
small fake of the game (pip install lupa). The fake works labours out from
the work details the way DF does: members are found by binary search, so a
member list out of order loses dwarves their labours (the 0.38.0 bug).

    python tests/test_labor.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

SRC = (ROOT / "lua" / "ai-labor.lua").read_text(encoding="utf-8")

FAKE = r"""
local src, spec = ...
local LAB = {MINE = 1, CUTWOOD = 11, HERBALIST = 41, FISH = 42, PLANT = 40, BREWER = 50}
local SK = {MINING = 0, WOODCUTTING = 1, HERBALISM = 23, FISH = 24, PLANT = 22, AXE = 38, BREWING = 30}
-- the game's enums go both ways (token -> number, number -> token), with attrs
local UL, SKL = {_first_item = 0, _last_item = 60}, {_first_item = 0, _last_item = 40, attrs = {}}
for k, v in pairs(LAB) do UL[k] = v; UL[v] = k end
for k, v in pairs(SK) do SKL[k] = v; SKL[v] = k end
local SKILL_LABOR = {MINING = 'MINE', WOODCUTTING = 'CUTWOOD', HERBALISM = 'HERBALIST', FISH = 'FISH',
                     PLANT = 'PLANT', BREWING = 'BREWER'}
for sk, l in pairs(SKILL_LABOR) do SKL.attrs[SK[sk]] = {labor = LAB[l]} end
local ICON = {MINERS = 0, WOODCUTTERS = 1, HUNTERS = 2, PLANTERS = 3, FISHERMEN = 4, PLANT_GATHERERS = 7}
local MODE = {[0] = 'Default', [1] = 'EverybodyDoesThis', [2] = 'NobodyDoesThis', [3] = 'OnlySelectedDoesThis'}
for k, v in pairs({Default = 0, EverybodyDoesThis = 1, NobodyDoesThis = 2, OnlySelectedDoesThis = 3}) do MODE[k] = v end

local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {
        __len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end,
        __index = {insert = function(self, at, v)
            local n = #self
            if at == '#' then at = n end
            for i = n, at + 1, -1 do self[i] = self[i - 1] end
            self[at] = v
        end,
        erase = function(self, at)
            local n = #self
            for i = at, n - 2 do self[i] = self[i + 1] end
            self[n - 1] = nil
        end}})
end

local function bsearch(v, id)
    local lo, hi = 0, #v - 1
    while lo <= hi do
        local mid = (lo + hi) // 2
        if v[mid] == id then return true elseif v[mid] < id then lo = mid + 1 else hi = mid - 1 end
    end
    return false
end

local details = vec()
for _, d in ipairs(spec.details) do
    local allowed = {[LAB[d.labor]] = true}
    details:insert('#', {name = d.name, icon = d.icon and ICON[d.icon] or -1, flags = {mode = d.mode or 3, no_modify = true},
                         allowed_labors = allowed, assigned_units = vec(d.members and d.members or {})})
end

local units, by_id = {}, {}
for _, u in ipairs(spec.units) do
    local skills = {}
    for _, sk in ipairs(u.skills or {}) do table.insert(skills, {id = SK[sk[1]], rating = sk[2]}) end
    local labors = {}
    for _, l in ipairs(u.labors or {}) do labors[LAB[l]] = true end
    local unit = {id = u.id, child = u.child, military = {squad_id = u.squad or -1},
                  status = {labors = labors, current_soul = {skills = skills}},
                  job = {current_job = u.busy and {} or nil}, noble = u.noble}
    table.insert(units, unit)
    by_id[u.id] = unit
end

local function recompute(u)
    for _, l in pairs(LAB) do
        for i = 0, #details - 1 do
            local d = details[i]
            if d.allowed_labors[l] then
                local m = MODE[d.flags.mode]
                u.status.labors[l] = (m == 'EverybodyDoesThis') or
                    ((m == 'OnlySelectedDoesThis' or m == 'Default') and bsearch(d.assigned_units, u.id))
            end
        end
    end
end

local items = {}
for _, t in ipairs(spec.tools) do
    table.insert(items, {subtype = {skill_melee = SK[t.skill]}, flags = {forbid = t.forbid}, holder = t.holder})
end

-- a 20x20 surface at z 10: shrubs where spec says, water where spec says
local tiles = {}
local function key(x, y, z) return x .. ',' .. y .. ',' .. z end
for x = 0, 19 do for y = 0, 19 do
    tiles[key(x, y, 10)] = {tt = 1, d = {hidden = false, outside = true, dig = 0, flow_size = 0, liquid_type = false}}
end end
for _, s in ipairs(spec.shrubs or {}) do tiles[key(s[1], s[2], 10)].tt = 2 end
for _, w in ipairs(spec.water or {}) do tiles[key(w[1], w[2], 10)].d.flow_size = 7 end
local block = {flags = {designated = false}, designation = {}, tiletype = {}}
for x = 0, 15 do
    block.designation[x], block.tiletype[x] = {}, {}
    for y = 0, 15 do block.designation[x][y] = {dig = 0}; block.tiletype[x][y] = 1 end
end
local left = spec.dig or 0
for x = 0, 15 do for y = 0, 15 do
    if left > 0 then block.designation[x][y].dig = 1; left = left - 1; block.flags.designated = true end
end end

-- the game's job list (a linked list): {type, worker, suspend}
local JT = {[1] = 'BrewDrink', [2] = 'CustomReaction', attrs = {[1] = {labor = LAB.BREWER}, [2] = {labor = -1}}}
local head = {}
local last = head
for _, j in ipairs(spec.jobs or {}) do
    local job = {job_type = j.type or 1, reaction_name = j.reaction or '', flags = {suspend = j.suspend == true},
                 worker = j.worker}
    last.next = {item = job}
    last = last.next
end

local env = setmetatable({}, {__index = _G})
env.df = {
    unit_labor = UL, job_skill = SKL, work_detail_icon_type = ICON, work_detail_mode = MODE,
    job_type = JT,
    tile_dig_designation = {No = 0, Default = 1},
    tiletype_shape = {FLOOR = 1, SHRUB = 2},
    tiletype = {attrs = {[1] = {shape = 1}, [2] = {shape = 2}}},
    unit = {find = function(id) return by_id[id] end},
    global = {world = {items = {other = {WEAPON = items}}, map = {map_blocks = {block}}, jobs = {list = head},
                       raws = {reactions = {reactions = {{code = 'BREW_FANCY', skill = SK.BREWING}}}}},
              plotinfo = {labor_info = {work_details = spec.no_details and vec() or details}}},
}
env.dfhack = {
    units = {getCitizens = function() return units end,
             isChild = function(u) return u.child == true end, isBaby = function() return false end,
             getNoblePositions = function(u) return u.noble and {1} or {} end,
             getReadableName = function(u) return 'dwarf ' .. u.id end,
             setAutomaticProfessions = (not spec.old_dfhack) and recompute or nil},
    items = {getHolderUnit = function(i) return i.holder and by_id[i.holder] or nil end},
    job = {getWorker = function(j) return j.worker end},
    maps = {
        getTileType = function(x, y, z) local t = tiles[key(x, y, z)]; return t and t.tt end,
        getTileFlags = function(x, y, z) local t = tiles[key(x, y, z)]; if t then return t.d, {} end end,
        getTileBlock = function() return {flags = {}} end,
    },
}
env.reqscript = function() return {found_center = function() return {x = 10, y = 10, z = 10, what = 'the wagon'} end} end
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then          -- DF vectors start at 0
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
assert(load(src, 'ai-labor', 't', env))()
return env, details, by_id, LAB, recompute, tiles, key
"""


def game(units, tools, details, dig=0, **kw):
    lua = LuaRuntime(unpack_returned_tuples=True)

    def lt(v):
        if isinstance(v, dict):
            return lua.table_from({k: lt(x) for k, x in v.items()})
        if isinstance(v, (list, tuple)):
            return lua.table_from([lt(x) for x in v])
        return v
    spec = lt({"units": units, "tools": tools, "details": details, "dig": dig, **kw})
    env, dets, by_id, lab, recompute, tiles, key = lua.execute(FAKE, SRC, spec)
    return dict(lua=lua, env=env, details=dets, by_id=by_id, lab=lab, recompute=recompute, tiles=tiles, key=key)


def members(g, i):
    v = g["details"][i].assigned_units
    out, j = [], 0
    while v[j] is not None:
        out.append(v[j])
        j += 1
    return out


def test(name):
    def wrap(fn):
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception as e:  # noqa: BLE001
            RESULTS.append((name, False, f"{type(e).__name__}: {e}"))
        return fn
    return wrap


SEVEN = [{"id": 1, "labors": ["MINE"], "skills": [("MINING", 5)]},
         {"id": 2, "squad": 25, "skills": [("MINING", 4)]},           # the soldier
         {"id": 3, "skills": [("MINING", 2), ("FISH", 1)]},           # a little mining
         {"id": 4, "skills": [("PLANT", 6)]},                         # a skilled farmer
         {"id": 5, "skills": [("HERBALISM", 1)]},
         {"id": 6, "noble": True},
         {"id": 7, "child": True}]
DETAILS = [{"name": "Miners", "icon": "MINERS", "labor": "MINE", "members": [1]},
           {"name": "Woodcutters", "icon": "WOODCUTTERS", "labor": "CUTWOOD"},
           {"name": "Plant gatherers", "icon": "PLANT_GATHERERS", "labor": "HERBALIST"},
           {"name": "Fisherdwarves", "icon": "FISHERMEN", "labor": "FISH"},
           {"name": "Planters", "icon": "PLANTERS", "labor": "PLANT", "mode": 1}]
PICK, AXE = {"skill": "MINING"}, {"skill": "AXE"}


@test("miners wanted: none without digging, never more than the picks, 3 for a new fort, at most 20 (0.104.134)")
def _():
    w = game([], [], [])["env"].miners_wanted
    assert w(0, 5, 10) == 0 and w(100, 1, 10) == 1 and w(100, 3, 6) == 3 and w(100, 9, 6) == 3
    assert w(10, 5, 6) == 1 and w(60, 5, 6) == 3 and w(5000, 50, 200) == 20 and w(262, 15, 160) == 15 and w(174, 15, 160) == 12


@test("the survey: every job's detail, mode and workers; picks against soldiers' picks; digging apart from gathering")
def _():
    g = game(SEVEN, [{**PICK, "holder": 1}, PICK, {**PICK, "holder": 2}, {**PICK, "forbid": True}, AXE],
             DETAILS, dig=60, shrubs=[(3, 3), (4, 4)], water=[(14, 14)])
    s = g["env"].survey()
    assert (s.miners, s.picks, s.soldier_picks, s.dig, s.want, s.need) == (1, 2, 1, 60, 2, 1), dict(s)
    assert s.detail == "Miners" and s.detail_mode == "OnlySelectedDoesThis", dict(s)
    assert s.jobs.farming.mode == "EverybodyDoesThis" and s.jobs.gathering.detail == "Plant gatherers"
    assert s.jobs.woodcutting.tools == 1 and s.shrubs == 2 and s.fish_water >= 1, dict(s.jobs.woodcutting)
    assert s.jobs.mining.unsorted is None


@test("narrow (0.104.10): an everybody detail goes to the most skilled crew; widened back only if the AI narrowed it")
def _():
    g = game(SEVEN, [], DETAILS)
    env, by_id, lab, lua = g["env"], g["by_id"], g["lab"], g["lua"]
    lua.execute("""local env = ...
      local store = {}
      env.dfhack.persistent = {getSiteData = function(k, d) return store[k] or d end,
                               saveSiteData = function(k, v) store[k] = v end}""", env)
    assert by_id[3].status.labors[lab.PLANT] is not False          # (everybody plants today)
    dry = env.narrow("farming", 2, True)
    assert dry.ok and dry.keep == 2 and members(g, 4) == [], dict(dry)
    r = env.narrow("farming", 2, False)
    assert r.ok and len(members(g, 4)) == 2 and 4 in members(g, 4), (dict(r), members(g, 4))   # the skilled farmer kept
    assert g["details"][4].flags.mode == 3
    assert by_id[4].status.labors[lab.PLANT] and not all(by_id[i].status.labors[lab.PLANT] for i in (1, 3, 5))
    assert env.narrowed().farming
    again = env.narrow("farming", 2, False)
    assert not again.ok and "not everybody" in again.error, dict(again)
    w = env.widen("farming", False)
    assert w.ok and g["details"][4].flags.mode == 1 and not env.narrowed().farming, dict(w)
    assert not env.widen("gathering", False).ok                  # never narrowed by the AI: left alone


@test("assigning: members stay in order and the game's own recompute gives the labour; it survives a recompute")
def _():
    g = game(SEVEN, [{**PICK, "holder": 1}, PICK, PICK, {**PICK, "holder": 2}], DETAILS, dig=200)
    env, by_id, lab = g["env"], g["by_id"], g["lab"]
    dry = env.assign("mining", 10, True)
    assert dry.ok and list(dry.assigned.values()) == ["dwarf 3", "dwarf 5"], dict(dry)
    assert not by_id[3].status.labors[lab.MINE]                # a dry run changes nothing
    r = env.assign("mining", 10, False)
    assert r.ok and list(r.assigned.values()) == ["dwarf 3", "dwarf 5"], dict(r)
    assert members(g, 0) == [1, 3, 5], members(g, 0)
    for i in (1, 3, 5, 2, 6):
        g["recompute"](by_id[i])                               # (migrants arrive: the game recomputes everyone)
    assert all(by_id[i].status.labors[lab.MINE] for i in (1, 3, 5))
    assert not by_id[2].status.labors[lab.MINE] and not by_id[6].status.labors[lab.MINE]
    again = env.assign("mining", 10, False)                    # all picks in use now
    assert not again.ok and "no more miners wanted" in again.error, dict(again)


@test("0.38.0's out-of-order member list is put back in order and everyone's labours recomputed")
def _():
    d = [dict(DETAILS[0], members=[5, 9, 1])] + DETAILS[1:]
    units = SEVEN + [{"id": 9}]
    g = game(units, [PICK], d)
    assert g["env"].survey().jobs.mining.unsorted is True
    r = g["env"].assign("mining", 0, False)
    assert r.ok and list(r.repaired.values()) == ["Miners"] and members(g, 0) == [1, 5, 9], members(g, 0)
    assert all(g["by_id"][i].status.labors[g["lab"].MINE] for i in (1, 5, 9))


@test("trim (0.104.166): an 'only selected' detail cut to the best few, never one breaking down; others left alone")
def _():
    units = [{"id": i, "skills": [("FISH", s)]} for i, s in ((11, 9), (12, 7), (13, 5), (14, 3), (15, 1), (16, 0))]
    dets = [dict(d) for d in DETAILS]
    dets[3] = {**dets[3], "members": [11, 12, 13, 14, 15, 16]}
    g = game(units, [], dets)
    env, by_id, lab, lua = g["env"], g["by_id"], g["lab"], g["lua"]
    lua.execute("""local env = ...
      env.dfhack.units.getStressCategory = function(u) if u.id == 11 then return 0 end return 4 end""", env)
    dry = env.trim("fishing", 2, True)
    assert dry.ok and dry.removed == 4 and members(g, 3) == [11, 12, 13, 14, 15, 16], dict(dry)
    r = env.trim("fishing", 2, False)
    assert r.ok and members(g, 3) == [12, 13], (dict(r), members(g, 3))     # 11 is miserable: not kept
    assert by_id[12].status.labors[lab.FISH] and not by_id[15].status.labors[lab.FISH]
    again = env.trim("fishing", 2, False)
    assert not again.ok and "only 2" in again.error, dict(again)
    assert env.trim("fishing", 0, False).ok and members(g, 3) == []
    assert "not \"only selected\"" in env.trim("farming", 1, False).error   # everybody farms: left alone


@test("gatherers and fishers: anyone outside squads, those with the skill first, miners last")
def _():
    g = game(SEVEN, [], DETAILS)
    r = g["env"].assign("gathering", 2, False)
    assert r.ok and list(r.assigned.values()) == ["dwarf 5", "dwarf 3"], dict(r)
    f = g["env"].assign("fishing", 1, False)
    assert f.ok and list(f.assigned.values()) == ["dwarf 3"], dict(f)
    assert g["by_id"][3].status.labors[g["lab"].FISH]


@test("woodcutting never past the free axes; a detail set to everybody or nobody is left alone")
def _():
    g = game(SEVEN, [AXE], DETAILS)
    r = g["env"].assign("woodcutting", 3, False)
    assert r.ok and len(r.assigned) == 1, dict(r)
    assert "no free axe" in g["env"].assign("woodcutting", 1, False).error
    assert "everybody already does this" in g["env"].assign("farming", 1, False).error
    g["details"][3].flags.mode = 2
    assert "set to nobody" in g["env"].assign("fishing", 1, False).error


@test("no work detail, or a DFHack without the recompute: the labour is set directly")
def _():
    g = game(SEVEN, [PICK, PICK], DETAILS, dig=100, no_details=True)
    r = g["env"].assign("mining", 5, False)
    assert r.ok and g["by_id"][3].status.labors[g["lab"].MINE], dict(r)
    g = game(SEVEN, [], DETAILS, old_dfhack=True)
    r = g["env"].assign("gathering", 1, False)
    assert r.ok and g["by_id"][5].status.labors[g["lab"].HERBALIST], dict(r)


@test("gathering: shrubs near the fort are marked; none left is refused")
def _():
    g = game(SEVEN, [], DETAILS, shrubs=[(3, 3), (4, 4), (5, 5)])
    assert g["env"].gather_plants(2, True).marked == 2
    r = g["env"].gather_plants(10, False)
    assert r.ok and r.marked == 3, dict(r)
    assert g["tiles"][g["key"](4, 4, 10)].d.dig == 1
    s = g["env"].survey()
    assert s.shrubs == 0
    assert g["env"].gather_plants(10, False).rejected



@test("gathering jobs: the farthest waiting ones go first, down to `keep`; taken ones stay")
def _():
    g = game([], [], [])
    lua, cancel = g["lua"], g["env"].gathering_to_cancel
    jobs = lua.table_from([lua.table_from(j) for j in (
        {"id": 1, "d": 5, "taken": False}, {"id": 2, "d": 50, "taken": False}, {"id": 3, "d": 90, "taken": True},
        {"id": 4, "d": 30, "taken": False}, {"id": 5, "d": 70, "taken": False})])
    ids = lambda t: [t[i] for i in range(1, len(t) + 1)]
    assert ids(cancel(jobs, 2)) == [5, 2, 4], ids(cancel(jobs, 2))      # 5 jobs, keep 2: the 3 farthest free
    assert ids(cancel(jobs, 5)) == []
    assert ids(cancel(jobs, 0)) == [5, 2, 4, 1]                          # the taken one is never cancelled

@test("work waiting: jobs nobody has taken, by labour (a reaction's by its skill); assigning any labour; skilled first")
def _():
    units = SEVEN + [{"id": 8, "skills": [("BREWING", 4)]},                  # a skilled brewer, not on it
                     {"id": 9, "labors": ["BREWER"], "busy": True, "skills": [("BREWING", 1)]}]
    details = DETAILS + [{"name": "Brewers", "labor": "BREWER", "members": [9]}]
    jobs = [{"type": 1}, {"type": 1}, {"type": 2, "reaction": "BREW_FANCY"}, {"type": 1, "worker": True},
            {"type": 1, "suspend": True}]
    g = game(units, [], details, jobs=jobs)
    s = g["env"].survey()
    w = s.waiting[1]
    assert w.labor == "BREWER" and w.jobs == 3 and w.holders == 1 and w.idle == 0 and w.detail == "Brewers", dict(w)
    k = [dict(x) for x in s.skilled_off.values()]
    assert {"labor": "BREWER", "skilled": 1, "detail": "Brewers"} in k, k
    r = g["env"].assign("BREWER", 3, False, None, 3)              # only the skilled
    assert r.ok and list(r.assigned.values()) == ["dwarf 8"], dict(r)
    assert members(g, 5) == [8, 9] and g["by_id"][8].status.labors[50] is True
    r = g["env"].assign("NOT_A_LABOR", 1, False, None)
    assert r.ok is False and "unknown job" in r.error


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
