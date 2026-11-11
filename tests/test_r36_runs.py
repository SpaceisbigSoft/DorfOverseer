"""(0.105.36, group runs) the focused audit's fixes in the overseer, the
reviver, the title screen, set_rules, unburied_citizens and the hospital's
chests:

- a date-failed cycle leaves the game's events undrained (the next good cycle
  counts them), and the dead `date_bad` code is gone;
- the rules-request log line says a three-state value as it is;
- a request's open_caverns false is never (a stored false is still ai);
- the fort's dead pets, livestock and visitors are not unburied citizens;
- thread in a bag in a hospital chest is the hospital's;
- the title screen's Enter fallback needs a clamped scroll and the right line;
- the reviver's "DFHack doesn't answer yet" is said again after DF came up.

    python tests/test_r36_runs.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))

from harness import make_test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    print("SKIPPED: these tests need the lupa package (pip install lupa)")
    sys.exit(0)

import test_overseer as TO  # noqa: E402  (its fake bridge; its tests run only when it is run itself)
import test_preset as TP  # noqa: E402  (the bridge with a stub DFHack)
import revive  # noqa: E402

test = make_test(before=TO._before)
LUA_DIR = ROOT / "lua"
OVERSEER = (ROOT / "brain" / "overseer.py").read_text(encoding="utf-8")
HARNESS = re.search(r'HARNESS = r"""(.*?)"""',
                    (ROOT / "tests" / "test_hygiene_bridge.py").read_text(encoding="utf-8"), re.S).group(1)
LUA = LuaRuntime(unpack_returned_tuples=True)
H = LUA.execute(HARNESS, (LUA_DIR / "ai-bridge.lua").read_text(encoding="utf-8"), str(LUA_DIR))


@test("D7 one_cycle, date failed: the game's events are not drained; the next good cycle reads them")
def _():
    ov = TO.overseer
    b = TO.FakeBridge()
    ov.one_cycle(b, autopilot=True)
    b.advance(1)
    good = copy.deepcopy(b._state["date"])
    b._state["date"] = {"error": "lua: date failed"}
    death = {"kind": "death", "own_civ": True, "name": "Urist", "id": 9}
    b._events = [death]
    seen = []
    real = ov.crisis.note_deaths
    ov.crisis.note_deaths = lambda s, m, ev: (seen.append(list(ev)), real(s, m, ev))[1]
    try:
        ov.MEMORY_CACHE.clear()
        ov.one_cycle(b, autopilot=True)
        assert b._events == [death], b._events        # DF keeps them
        assert seen == [], seen
        b._state["date"] = good
        b.advance(1)
        ov.MEMORY_CACHE.clear()
        ov.one_cycle(b, autopilot=True)
    finally:
        ov.crisis.note_deaths = real
    assert b._events == [] and seen and death in seen[-1], seen


@test("D7 overseer: no date_bad left below the date-failed return")
def _():
    body = OVERSEER[OVERSEER.index("def one_cycle("):OVERSEER.index("def _style_choices(")]
    assert "date_bad" not in body
    assert body.count("chronicle.date_failed(state)") == 1
    assert body.index("chronicle.date_failed(state)") < body.index("events = bridge.events()")


@test("D7 rules_request: a three-state value is logged as it is, a switch as on/off")
def _():
    ov = TO.overseer
    for req, ch, want in (({"open_caverns": "never"}, {"open_caverns": {"old": "ai", "new": "never"}}, "open_caverns never"),
                          ({"open_caverns": "ai"}, {"open_caverns": {"old": "always", "new": "ai"}}, "open_caverns ai"),
                          ({"construct": False}, {"construct": {"old": True, "new": False}}, "construct off"),
                          ({"construct": True}, {"construct": {"old": False, "new": True}}, "construct on")):
        (ov.LOG_DIR / "rules-request.json").write_text(json.dumps({"rules": req}), encoding="utf-8")

        class B:
            def act(self, a, _ch=ch):
                return {"ok": True, "changed": _ch}
        TO.SAID.clear()
        ov.rules_request(B(), True)
        assert any(f"rules-request.json: {want}." in x for x in TO.SAID), (want, TO.SAID)


@test("D7 set_rules: a request's open_caverns false is never, true always; a stored false still reads ai")
def _():
    TP.reset()
    r = TP.act({"type": "set_rules", "rules": {"open_caverns": False}})
    assert r.ok and TP.saved().open_caverns == "never", (dict(r), TP.saved().open_caverns)
    r = TP.act({"type": "set_rules", "rules": {"open_caverns": True}})
    assert r.ok and TP.saved().open_caverns == "always"
    r = TP.act({"type": "set_rules", "rules": {"open_caverns": "ai"}})
    assert r.ok and TP.saved().open_caverns == "ai"
    S = TP.H.settings()
    assert S.sanitize(TP.t({"open_caverns": False})).open_caverns == "ai"
    TP.reset()


UNBURIED = r"""
local env, H, kinds = ...
local df = H.df
df.global.plotinfo.race_id, df.global.plotinfo.civ_id = 572, 77
local U = {}
for i, k in ipairs(kinds) do U[i] = {id = i, civ_id = k == 'other' and 5 or 77, race = 572, kind = k} end
local list = {}
for i in ipairs(kinds) do list[i] = {flags = {in_building = false, removed = false}, unit_id = i, race = 572} end
df.global.world.items = {other = {CORPSE = list}}
df.unit = df.unit or {}
df.unit.find = function(id) return U[id] end
H.dfhack.units = H.dfhack.units or {}
H.dfhack.units.isAnimal = function(u) return u.kind == 'pet' end
H.dfhack.units.isMerchant = function(u) return u.kind == 'merchant' end
H.dfhack.units.isDiplomat = function(u) return u.kind == 'envoy' end
H.dfhack.units.isVisitor = function(u) return u.kind == 'visitor' end
return env.unburied_citizens()
"""


@test("D6 unburied_citizens: the fort's dead pets, merchants, envoys and visitors don't count; citizens do")
def _():
    env = H.module()
    n = LUA.execute(UNBURIED, env, H, LUA.table_from(["pet", "merchant", "envoy", "visitor", "other"]))
    assert n == 0, n
    n = LUA.execute(UNBURIED, env, H, LUA.table_from(["citizen", "pet", "citizen"]))
    assert n == 2, n


@test("D6 unburied_citizens: a dead cat alone lets prune_remains' corpse pass run")
def _():
    env = H.module()
    r = LUA.execute(r"""
local env, H = ...
local df = H.df
df.global.plotinfo.race_id, df.global.plotinfo.civ_id = 572, 77
df.global.world.items = {other = {CORPSE = {{flags = {in_building = false, removed = false}, unit_id = 9, race = 160}}}}
df.unit = df.unit or {}
df.unit.find = function(id) if id == 9 then return {id = 9, civ_id = 77, race = 160} end end
H.dfhack.units = H.dfhack.units or {}
H.dfhack.units.isAnimal = function(u) return u.race == 160 end
H.cmds = {}
H.dfhack.findScript = function() return 'x' end
H.dfhack.run_command_silent = function(...) table.insert(H.cmds, table.concat({...}, ' ')); return 'ok', 0 end
local n = env.unburied_citizens()
env.act_prune_remains({})
return n, table.concat(H.cmds, '|')
""", env, H)
    assert r[0] == 0 and "deteriorate now corpses" in r[1], r


@test("D6 hospital_store_test: thread in a bag in a hospital chest is the hospital's")
def _():
    env = H.module()
    r = LUA.execute("""local env, H = ...
      local d = H.dfhack
      local chest_h, chest_f = {id = 50}, {id = 51}
      local bag_h, bag_f, loose_bag = {id = 60, box = chest_h}, {id = 61, box = chest_f}, {id = 62}
      local hosp = {getType = function() return 1 end, getContents = function() return {building_ids = {9}} end}
      H.df.abstract_building_type = {[1] = 'HOSPITAL'}
      d.world.getCurrentSite = function() return {buildings = {hosp}} end
      d.items = {getContainer = function(it) return it.box end,
                 getHolderBuilding = function(c) return (c == chest_h and {centerx = 1, centery = 1, z = 1})
                                                    or (c == chest_f and {centerx = 2, centery = 2, z = 1}) or nil end}
      d.buildings = {findCivzonesAt = function(p) return p.x == 1 and {{id = 9}} or {{id = 4}} end}
      env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
      local test = env.hospital_store_test()
      return test({box = bag_h}), test({box = bag_f}), test({box = loose_bag}), test({box = chest_h})
    """, env, H)
    assert tuple(r) == (True, False, False, True), r


TITLE_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.dfhack_flags = {module = true}
env.LOG = {}
env.TIMERS = {}
env.dfhack = {timeout = function(n, u, f) table.insert(env.TIMERS, f) end, isWorldLoaded = function() return false end,
              gui = {}, screen = {}}
env.require = function() return {simulateInput = function(scr, key) table.insert(env.LOG, key) end} end
assert(load(src, 'ai-title', 't', env))()
env.LOAD_LOG = {steps = {}}
return env
"""


@test("D7 title fallback: Enter only with the scroll clamped below the line and the line the wanted one")
def _():
    L = LuaRuntime(unpack_returned_tuples=True)
    env = L.execute(TITLE_FAKE, (LUA_DIR / "ai-title.lua").read_text(encoding="utf-8"))
    run = L.eval("function(env) local f = table.remove(env.TIMERS, 1); f() end")
    went = []

    def go(scroll, sel, line_ok):
        went.clear()
        scr = L.table_from({"scroll_position_world_choice": scroll, "selected": sel})
        env.then_if_scrolled(scr, "scroll_position_world_choice", 2, lambda: went.append("click"),
                             lambda: went.append("key"), line_ok)
        run(env)
        return list(went)

    assert go(1, 2, lambda: True) == ["key"]
    assert go(1, 2, lambda: False) == []          # the line at 2 is another world now
    assert go(3, 2, lambda: True) == []           # not pulled back toward the top
    assert go(1, 0, lambda: True) == []           # not highlighted
    assert go(2, 2, lambda: False) == ["click"]   # the scroll held: the top button, as before
    src = (LUA_DIR / "ai-title.lua").read_text(encoding="utf-8")
    assert "t3.savegame_header_game[gi].filename_noext == folder" in src
    assert "t2.savegame_header_world[wi].world_name == world" in src


@test("D7 revive: busy_said is reset once DF answers, so a later slow start is said again")
def _():
    t = [0.0]
    rv = revive.Reviver(lambda *_: None, dfhack=None, launcher=lambda *_: None, clock=lambda: t[0])
    rv.probe = lambda: "title"
    rv.candidates = lambda: ([], None)
    rv.busy_said = True
    rv.tick()
    assert rv.busy_said is False
    rv.busy_said = True
    rv.probe = lambda: "world"
    t[0] += 10000
    rv.tick()
    assert rv.busy_said is False


if __name__ == "__main__":
    finish()
