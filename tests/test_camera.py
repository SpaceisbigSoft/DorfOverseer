"""Tests for lua/ai-camera.lua (0.104.88), the camera director, in a real Lua
engine with a stub DFHack (pip install lupa).

    python tests/test_camera.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from lua_modules_util import module_src  # (13c lua-modules) the modules' sources, with lua/ai-util.lua
RESULTS = []

try:
    from lupa import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)


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


FAKE = r"""
local src = ...
local function vec(list)
    local t = {}
    for i, v in ipairs(list or {}) do t[i - 1] = v end
    return setmetatable(t, {__len = function(self) local n = 0; while rawget(self, n) ~= nil do n = n + 1 end; return n end})
end
local W = {T = 1000, mode = 'on', unattended = true, halted = false, focus_default = true, sel_unit = nil, sel_bldg = nil,
           moves = {}, cmds = {}, units = {}, cits = {}, buildings = {}, projects = {}, gate = {x = 50, y = 50, z = 10}}
local G = {window_x = 0, window_y = 0, window_z = 0, pause_state = false,
           world = {units = {active = vec({})}, buildings = {all = vec({})}}}
local env = setmetatable({}, {__index = _G})
env.ipairs = function(t)
    if type(t) == 'table' and rawget(t, 0) ~= nil then
        local i = -1
        return function() i = i + 1; if t[i] ~= nil then return i, t[i] end end
    end
    return ipairs(t)
end
env.os = {time = function() return W.T end, clock = os.clock}
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local handlers = {death = {}, active = {}}
env.require = function(name)
    if name == 'plugins.eventful' then
        return {enableEvent = function() end, eventType = {UNIT_DEATH = 1, UNIT_NEW_ACTIVE = 2},
                onUnitDeath = handlers.death, onUnitNewActive = handlers.active}
    end
    return require(name)
end
env.reqscript = function(name)
    if name == 'ai-overseer-settings' then return {load_settings = function() return {camera = W.mode} end} end
    if name == 'ai-status' then
        return {LAST_SEEN = W.T - 10, STATUS = {unattended = W.unattended}, is_halted = function() return W.halted end}
    end
    if name == 'ai-builder' then return {load_projects = function() return {list = W.projects} end} end
    if name == 'ai-gates' then return {GATES = {entrances = {W.gate}}} end
    error('reqscript ' .. name)
end
local function unit(id, x, y, z, o)
    o = o or {}
    return {id = id, pos = {x = x, y = y, z = z}, citizen = o.citizen, danger = o.danger, mood = o.mood or -1,
            flags1 = {caged = false, chained = false}, name = o.name or ('unit ' .. id), race = 1,
            counters = {soldier_mood = -1}, relationship_ids = {Spouse = -1},
            status = {current_soul = {skills = vec({})}}}
end
env.df = {global = G, mood_type = {[-1] = 'None', [1] = 'Fey'},
          building_type = {[1] = 'Civzone', [2] = 'Workshop', [3] = 'FarmPlot'},
          civzone_type = {[5] = 'MeetingHall', [6] = 'Bedroom'}, workshop_type = {[0] = 'Masons', [1] = 'Craftsdwarfs'},
          furnace_type = {}, unit = {find = function(id) return W.units[id] end},
          building = {find = function(id) return W.bfind[id] end},
          soldier_mood_type = {[-1] = 'None', [3] = 'Tantrum'},
          activity_event_type = {[1] = 'Performance', [2] = 'Conversation'},
          job_skill = {[5] = 'MINING', attrs = {[5] = {caption_noun = 'Miner'}}},
          historical_entity = {find = function() return W.entity end},
          historical_figure = {find = function(id) return W.figs[id] end}}
W.bfind, W.figs = {}, {}
G.cur_year, G.cur_year_tick = 51, 1200 * 30
G.plotinfo = {group_id = 7}
G.world.artifacts = {all = vec({})}
G.world.activities = {all = vec({})}
G.world.raws = {creatures = {all = setmetatable({}, {__index = function() return {flags = {}} end})}}
env.dfhack = {
    isMapLoaded = function() return true end,
    df2utf = function(s) return s end,
    onStateChange = {},
    timeout = function() return 1 end, timeout_active = function() return true end,
    items = {getPosition = function(it) return it.x, it.y, it.z end,
             getReadableDescription = function(it) return it.desc end},
    translation = {translateName = function(n) return n.text end},
    run_command_silent = function(...) table.insert(W.cmds, table.concat({...}, ' ')) end,
    gui = {matchFocusString = function() return W.focus_default end, getDFViewscreen = function() return {} end,
           getSelectedUnit = function() return W.sel_unit end, getSelectedBuilding = function() return W.sel_bldg end,
           revealInDwarfmodeMap = function(p, c)
               G.window_x, G.window_y, G.window_z = p.x - 40, p.y - 20, p.z
               table.insert(W.moves, p) end},
    units = {getCitizens = function() return vec(W.cits) end,
             getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end,
             getReadableName = function(u) return u.name end,
             isActive = function() return true end, isDead = function() return false end, isHidden = function() return false end,
             isDanger = function(u) return u.danger == true end, isCitizen = function(u) return u.citizen == true end,
             isInvader = function(u) return u.invader == true end, isMerchant = function(u) return u.merchant == true end,
             isDiplomat = function() return false end, isBaby = function(u) return u.baby == true end}}
assert(load(src, 'ai-camera', 't', env))()
W.unit = unit
W.vec = vec
W.G = G
W.handlers = handlers
W.set_units = function()
    local all = {}
    for _, u in pairs(W.units) do table.insert(all, u) end
    G.world.units.active = vec(all)
end
W.set_artifacts = function(list) G.world.artifacts.all = vec(list) end
W.set_activities = function(list)
    for _, a in ipairs(list) do
        local evs = {}
        for i, e in ipairs(a.evlist) do e.getType = function(self) return self.t end; evs[i] = e end
        a.events = vec(evs)
    end
    G.world.activities.all = vec(list)
end
W.vecof = function(list) return vec(list) end
W.set_buildings = function(list)
    for _, b in ipairs(list) do
        b.getType = function(self) return self.bt end; b.getSubtype = function(self) return self.st end
        b.jobs = b.jobs or vec({}); W.bfind[b.id] = b
    end
    G.world.buildings.all = vec(list)
end
return env, W
"""


def fresh():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, W = lua.execute(FAKE, module_src("ai-camera.lua"))
    return lua, env, W


def citizens(lua, W, spots):
    for i, (x, y, z) in enumerate(spots):
        u = W.unit(100 + i, x, y, z, lua.table_from({"citizen": True}))
        W.units[100 + i] = u
    W.cits = lua.table_from([W.units[100 + i] for i in range(len(spots))])
    W.set_units()


def buildings(lua, W):
    def b(i, bt, x, y, z, **kw):
        t = lua.table_from({"id": i, "bt": bt, "x1": x, "x2": x + 4, "y1": y, "y2": y + 4, "z": z, **kw})
        return t
    W.set_buildings(lua.table_from([b(1, 1, 10, 10, 5, type=5, name=""), b(2, 1, 30, 10, 5, type=6, name=""),
                                    b(3, 2, 60, 60, 6, st=0), b(4, 2, 70, 60, 6, st=0), b(5, 3, 20, 80, 4)]))


@test("camera (0.104.88): the tour visits the halls, one workshop of each kind, the farms and the gate; never a bedroom")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(0, 0, 0)])
    buildings(lua, W)
    assert env.build_tour() == 4, env.build_tour()                  # meeting hall, masons (once), farms, the gate
    labels = [W.moves and None]
    seen = []
    for _ in range(6):
        W.T += 25
        assert env.step() in ("moved", "dwell"), env.step()
        seen.append(env.status().showing)
    assert "A meeting hall" in seen and "The masons" in seen and "The farms" in seen and "The main gate" in seen, seen
    assert len(W.moves) >= 4


@test("camera (0.104.88): hands off while the player uses the game: paused, a menu, a selection, the view moved by hand")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(0, 0, 0)])
    buildings(lua, W)
    assert env.step() == "moved"
    n = len(W.moves)
    W.G.window_x = W.G.window_x + 7                                  # the player scrolled
    W.T += 30
    assert env.step() == "held" and env.status().held == "the view was moved by hand" and len(W.moves) == n
    W.T += 30
    assert env.step() == "held"                                       # still within the minute
    W.T += 31
    assert env.step() == "moved"                                      # the minute is up
    for key, val in (("focus_default", False), ("sel_unit", lua.table_from({"id": 1}))):
        lua.execute("local W, k, v = ...; W[k] = v", W, key, val)
        W.T += 100
        assert env.step() == "held", key
        lua.execute("local W, k = ...; W[k] = (k == 'focus_default') or nil", W, key)
        W.T += 61
    W.G.pause_state = True
    W.T += 100
    assert env.step() == "held"


@test("camera (0.104.88): a fight interrupts the tour at once and the camera follows it; then back to the tour")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(20, 20, 5), (22, 21, 5)])
    buildings(lua, W)
    env.step()
    gob = W.unit(900, 25, 22, 5, lua.table_from({"danger": True, "name": "a goblin"}))
    W.units[900] = gob
    W.set_units()
    W.T += 2
    assert env.step() == "fight" and env.status().kind == "fight" and "2 dwarves" in env.status().showing, env.status().showing
    n = len(W.moves)
    gob.pos.x = 27                                                    # a step: the camera stays
    W.T += 2
    assert env.step() == "fight" and len(W.moves) == n
    gob.pos.x, gob.pos.y = 34, 30                                     # far: the camera follows
    citizens(lua, W, [(33, 30, 5)])
    W.units[900] = gob
    W.set_units()
    W.T += 2
    assert env.step() == "fight" and len(W.moves) == n + 1
    W.units[900] = None
    W.set_units()
    W.T += 20
    assert env.step() == "moved" and env.status().kind == "tour"


@test("camera (0.104.88): events take the most important first; tour only ignores them; off without an unattended keeper")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5)])
    buildings(lua, W)
    env.ensure()
    env.add_event(lua.table_from({"x": 1, "y": 1, "z": 1, "prio": 55, "kind": "event", "key": "migrants", "label": "Migrants arrive"}))
    env.add_event(lua.table_from({"x": 2, "y": 2, "z": 2, "prio": 70, "kind": "event", "key": "death1", "label": "A death: Urist"}))
    assert env.step() == "moved" and env.status().showing == "A death: Urist"
    W.T += 26
    assert env.step() == "moved" and env.status().showing == "Migrants arrive"
    W.T += 5                                                          # an invasion cuts the dwell short
    W.units[77] = W.unit(77, 9, 9, 9)
    W.units[77].invader = True
    W.handlers.active["ai-camera"](77)
    assert env.step() == "moved" and env.status().showing == "Invaders arrive"
    W.mode = "tour"
    env.add_event(lua.table_from({"x": 3, "y": 3, "z": 3, "prio": 65, "kind": "event", "key": "mood", "label": "a mood"}))
    W.T += 30
    env.step()
    assert env.status().kind == "tour"
    W.mode, W.unattended = "on", False
    W.T += 30
    assert env.step() == "off" and env.status().mode == "off"
    W.unattended, W.halted = True, True
    assert env.step() == "off"


@test("camera (0.104.88): a strange mood is shown once, a death of a citizen as a death")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5), (6, 6, 5)])
    W.units[100].mood = 1
    buildings(lua, W)
    env.ensure()
    assert env.step() == "moved" and env.status().showing == "unit 100 is in a strange mood", env.status().showing
    for _ in range(3):
        W.T += 41                                                     # (0.104.90) a mood holds 40 s, following the dwarf
        env.step()
        assert "strange mood" not in str(env.status().showing)            # once only
    W.handlers.death["ai-camera"](101)
    W.T += 30
    env.step()
    assert env.status().showing == "A death: unit 101", env.status().showing


def run_until(env, W, pred, steps=40, dt=5):
    for _ in range(steps):
        W.T += dt
        env.step()
        if pred():
            return True
    return False


@test("camera (0.104.90): follows the unit it shows (the mood dwarf) as it walks off")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5)])
    W.units[100].mood = 1
    env.ensure()
    assert env.step() == "moved"
    n = len(W.moves)
    W.units[100].pos.x = 30                                           # it walks to a workshop
    W.T += 3
    assert env.step() == "follow" and len(W.moves) == n + 1 and W.moves[n + 1].x == 30
    W.T += 3
    assert env.step() == "dwell"                                      # it stands there: no more moves
    assert "ai-camera skip" in " ".join(list(W.cmds.values())), list(W.cmds.values())   # the keys are bound


@test("camera (0.104.90): the busy workshop and the crowded hall come before empty rooms")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(12, 12, 5), (13, 12, 5), (11, 11, 5)])       # three in the meeting hall
    buildings(lua, W)
    W.bfind[4].jobs = W.vecof(lua.table_from([1]))                    # the second masons' shop is at work
    env.build_tour()
    env.step()
    first = env.status().showing
    W.T += 25
    env.step()
    second = env.status().showing
    assert {first, second} == {"A meeting hall", "The masons"}, (first, second)
    assert W.moves[2].x == 72 or W.moves[1].x == 72, [(m.x, m.y) for m in W.moves.values()]   # the busy one


@test("camera (0.104.90): several deaths at once are one stop; the same kind again waits; a caption and the list")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5)])
    env.ensure()
    for i, nm in enumerate(["Urist", "Doren", "Kib"]):
        env.add_event(lua.table_from({"x": 1, "y": 1, "z": 1, "prio": 70, "kind": "event", "key": f"death{i}",
                                      "cat": "death", "label": f"A death: {nm}"}))
    assert env.step() == "moved" and env.status().showing == "A death: Urist and 2 more deaths", env.status().showing
    cap = env.status().caption
    assert cap and cap.text == "A death: Urist and 2 more deaths"
    env.add_event(lua.table_from({"x": 2, "y": 2, "z": 2, "prio": 70, "kind": "event", "key": "death9",
                                  "cat": "death", "label": "A death: Mosus"}))
    W.T += 26
    env.step()
    assert env.status().kind == "tour", env.status().showing          # too soon after the last death
    W.T += 9
    assert env.status().caption is None                               # the caption is gone after 8 s
    W.T += 100
    env.step()
    assert env.status().showing == "A death: Mosus", env.status().showing
    h = env.status().history
    assert h[1].label == "A death: Mosus" and h[2].label.startswith("A death: Urist") and h[1].date == "3 Slate y51", h[1].date


@test("camera (0.104.90): an artifact, a level started and finished, a performance, a wedding, a tantrum")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5), (9, 9, 5)])
    W.projects = lua.table_from([lua.table_from({"id": 1, "kind": "temple", "phase": "dig",
                                                 "area": lua.table_from({"x1": 40, "x2": 50, "y1": 40, "y2": 50, "z": 3})})])
    env.set_brain(lua.table_from({"news": lua.table_from(["build temple: the gods are wanted"]),
                                  "districts": lua.table_from([lua.table_from({"name": "the Pale Halls", "lo": 0, "hi": 9})])}))
    env.ensure()
    env.step()                                                         # the baselines
    W.set_artifacts(lua.table_from([lua.table_from({"id": 3, "name": lua.table_from({"text": "The Bronze Dawn"}),
                                                    "item": lua.table_from({"x": 7, "y": 7, "z": 5, "desc": "a granite throne"})})]))
    W.projects[1].phase = "done"
    W.set_activities(lua.table_from([lua.table_from({"id": 8, "evlist": lua.table_from([lua.table_from({
        "t": 1, "participants": lua.table_from({"units": W.vecof(lua.table_from([101]))})})])})]))
    W.units[100].relationship_ids.Spouse = 101
    W.units[101].counters.soldier_mood = 3
    seen = []
    def collect():
        s = env.status()
        if s.showing and s.showing not in seen:
            seen.append(s.showing)
            if s.caption and s.caption.sub:
                seen.append("sub:" + s.caption.sub)
        return False
    run_until(env, W, collect, steps=200, dt=5)
    want = ["An artifact is made: The Bronze Dawn", "sub:a granite throne", "The new temple level is finished",
            "sub:build temple: the gods are wanted", "A performance", "unit 100 and unit 101 are married",
            "unit 101 is throwing a tantrum"]
    for w in want:
        assert w in seen, (w, seen)
    assert seen.index("An artifact is made: The Bronze Dawn") < seen.index("A performance")   # the bigger news first


@test("camera (0.104.92): a dwarf gone stark raving mad or berserk is shown though DFHack no longer counts them citizens")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5)])
    lua.execute("local W, env = ...; env.df.mood_type[6] = 'Raving'; env.df.mood_type[7] = 'Berserk'; W.G.plotinfo.civ_id = 3", W, env)
    for uid, mood, x in ((200, 6, 40), (201, 7, 60)):
        u = W.unit(uid, x, 40, 5, lua.table_from({"mood": mood}))
        u.civ_id = 3
        W.units[uid] = u
    stranger = W.unit(202, 70, 70, 5, lua.table_from({"mood": 7}))
    stranger.civ_id = 9
    W.units[202] = stranger
    W.set_units()
    env.ensure()
    seen = []
    run_until(env, W, lambda: seen.append(env.status().showing) and False, steps=60, dt=10)
    assert "unit 200 has gone stark raving mad" in seen and "unit 201 has gone berserk" in seen, seen
    assert "unit 202 has gone berserk" not in seen and seen.count("unit 201 has gone berserk") >= 1, seen


@test("camera (0.104.92): a stop always full (the barracks) doesn't crowd out the rest of the tour")
def _():
    lua, env, W = fresh()
    lua.execute("local env = ...; for i, k in ipairs({'Carpenters', 'Mechanics', 'Still', 'Kitchen'}) do env.df.workshop_type[i + 1] = k end", env)
    citizens(lua, W, [(22, 82, 4)] * 8 + [(0, 0, 0)])                # 8 dwarves always on the farms
    def b(i, bt, x, y, z, **kw):
        return lua.table_from({"id": i, "bt": bt, "x1": x, "x2": x + 4, "y1": y, "y2": y + 4, "z": z, **kw})
    W.set_buildings(lua.table_from([b(1, 1, 10, 10, 5, type=5, name=""), b(6, 1, 90, 10, 5, type=5, name=""),
                                    b(7, 1, 10, 90, 7, type=5, name=""), b(8, 1, 90, 90, 7, type=5, name=""),
                                    b(3, 2, 60, 60, 6, st=0), b(4, 2, 70, 30, 6, st=1), b(5, 3, 20, 80, 4),
                                    b(9, 2, 40, 30, 6, st=2), b(10, 2, 40, 50, 6, st=3), b(11, 2, 50, 30, 6, st=4),
                                    b(12, 2, 50, 50, 6, st=5)]))
    env.ensure()
    seen = []
    def collect():
        s = env.status()
        if s.kind == "tour" and (not seen or seen[-1] != s.showing):
            seen.append(s.showing)
        return False
    run_until(env, W, collect, steps=120, dt=10)
    farms = sum(1 for x in seen if x == "The farms")
    assert len(seen) >= 12 and farms <= len(seen) // 5 + 1, (farms, len(seen), seen)
    assert len(set(seen)) >= 8, seen                                  # every stop comes round
    assert "A meeting hall, level 5" in seen and "A meeting hall, level 7" in seen, seen   # (0.104.93)


@test("camera (0.104.91): a new noble's caption names them without their profession")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5)])
    W.units[100].name = 'Lokum Esathel "Clearedring", militia captain'
    W.entity = lua.table_from({"positions": lua.table_from({
        "own": W.vecof(lua.table_from([lua.table_from({"id": 2, "name": W.vecof(lua.table_from(["militia captain"]))})])),
        "assignments": W.vecof(lua.table_from([lua.table_from({"id": 4, "position_id": 2, "histfig2": -1})]))})})
    env.ensure()
    env.step()
    W.figs[50] = lua.table_from({"unit_id": 100})
    W.entity.positions.assignments[0].histfig2 = 50
    W.T += 61
    env.step()
    seen = []
    run_until(env, W, lambda: seen.append(env.status().showing) and False, steps=30, dt=10)
    assert 'Lokum Esathel "Clearedring" is the new militia captain' in seen, seen


@test("camera (0.104.90): a legendary dwarf, a new noble, a forgotten beast followed")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(5, 5, 5)])
    W.entity = lua.table_from({"positions": lua.table_from({
        "own": W.vecof(lua.table_from([lua.table_from({"id": 2, "name": W.vecof(lua.table_from(["mayor"]))})])),
        "assignments": W.vecof(lua.table_from([lua.table_from({"id": 4, "position_id": 2, "histfig2": -1})]))})})
    env.ensure()
    env.step()
    W.units[100].status.current_soul.skills = W.vecof(lua.table_from([lua.table_from({"id": 5, "rating": 15})]))
    W.figs[50] = lua.table_from({"unit_id": 100})
    W.entity.positions.assignments[0].histfig2 = 50
    W.T += 61
    env.step()
    seen = []
    run_until(env, W, lambda: seen.append(env.status().showing) and False, steps=30, dt=10)
    assert "unit 100 is now a legendary miner" in seen and "unit 100 is the new mayor" in seen, seen
    lua.execute("local W = ...; W.G.world.raws.creatures.all = {[1] = {flags = {}}, [9] = {flags = {CASTE_FEATURE_BEAST = true}}}", W)
    W.units[66] = W.unit(66, 80, 80, 1)
    W.units[66].race = 9
    W.handlers.active["ai-camera"](66)
    W.T += 41
    env.step()
    assert env.status().showing == "A forgotten beast: unit 66", env.status().showing
    W.units[66].pos.z = 2
    W.T += 2
    assert env.step() == "follow"


@test("camera (0.104.90): the keys: next now, stay here, back to an entry; the pace; districts in the tour caption")
def _():
    lua, env, W = fresh()
    citizens(lua, W, [(12, 12, 5)])
    buildings(lua, W)
    env.set_brain(lua.table_from({"districts": lua.table_from([lua.table_from({"name": "the Pale Halls", "lo": 5, "hi": 5})])}))
    env.ensure()
    env.step()
    assert env.status().showing == "A meeting hall" and env.status().caption.sub == "1 dwarf here, in the Pale Halls", env.status().caption.sub
    W.T += 3
    env.skip()
    assert env.step() == "moved" and env.status().showing != "A meeting hall"
    env.stay()
    W.T += 100
    assert env.step() == "pinned" and env.status().pinned
    env.stay()
    W.T += 25
    assert env.step() == "moved"
    env.add_event(lua.table_from({"x": 3, "y": 4, "z": 2, "prio": 55, "kind": "event", "key": "k", "label": "Something"}))
    W.T += 25
    env.step()
    assert env.go(1) and W.moves[len(W.moves)].x == 3 and env.status().pinned
    # pace: fast cuts the event's 25 s to 15
    lua.execute("local W = ...; W.pace = 'fast'", W)
    lua.execute("""local env, W = ...
        local old = env.reqscript
        env.reqscript = function(n) if n == 'ai-overseer-settings' then
            return {load_settings = function() return {camera = 'on', camera_pace = W.pace} end} end return old(n) end""", env, W)
    env.stay(False)
    env.step()
    W.T += 16
    assert env.step() == "moved"


@test("camera (0.104.90): reloading the module over an older camera's state adds the new fields")
def _():
    lua = LuaRuntime(unpack_returned_tuples=True)
    src = module_src("ai-camera.lua")
    env, W = lua.execute(FAKE.replace("assert(load(src, 'ai-camera', 't', env))()",
        "env.CAM = {mode = 'on', queue = {}, tour = {}, tour_built = 0, recent = {}, seen_mood = {}, shown = 184, since = 0, hold_until = 0}\n"
        "assert(load(src, 'ai-camera', 't', env))()"), src)
    citizens(lua, W, [(5, 5, 5)])
    buildings(lua, W)
    assert env.step() == "moved" and env.CAM.shown == 185 and env.status().caption is not None
    env.CAM.timer, env.CAM.error = 5, "old"                          # the old file's loop still running
    env.ensure()
    assert env.CAM.error is None and env.CAM.tick_ref is not None and env.CAM.timer == 1


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
