"""(0.105.93) B's tantrums and the weakened infected.

Live 23 Nov, B (the Monastery, 53% unhappy, 25 miserable): tantrum dwarves
strangled dwarves walking about with infected wounds ("a patient waiting for
care"), Kubuk Stelidlolok (load 118) by a child. 7 infected, none treated:
the bed rule sent only the idle and never the unhappy (idle_untreated 0, 6
beds free). A heavy infection (load >= HEAVY_LOAD) is now sent busy or
unhappy too, its job given up first. And the hospital guard's one-day hold ran
out every cycle (~1300 ticks a cycle): 58 posts and recalls an hour; 3 days.

    python tests/test_r93_infected_heavy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

from planner import PLANNER_CONFIG  # noqa: E402

from lua_modules_util import module_src  # noqa: E402

HEALTH = module_src("ai-health.lua")      # with the prelude (reqscript and the like), as test_care


def pure():
    need_lua()
    from lupa.lua53 import LuaRuntime
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute("local src = ...; local e = setmetatable({}, {__index = _G}); "
                      "assert(load(src, 'h', 't', e))(); return e", HEALTH)
    return lua, env


@test("eligible: a heavy infection (B's 118) is sent busy and unhappy; a mild one busy or unhappy isn't; a heavy "
      "one in a tantrum, mad, a child, a soldier or in a mood still isn't")
def _():
    lua, e = pure()
    t = lua.table_from
    heavy = {"infected": True, "care": True, "load": 118}
    assert e.HEAVY_LOAD == 60
    assert e.eligible(t(dict(heavy, idle=False)))
    assert e.eligible(t(dict(heavy, idle=False, unhappy=True)))
    assert not e.eligible(t({"infected": True, "care": True, "load": 30, "idle": False}))
    assert not e.eligible(t({"infected": True, "care": True, "load": 30, "idle": True, "unhappy": True}))
    for k in ("tantrum", "insane", "child", "soldier", "mood", "asked", "in_hospital", "restrained"):
        assert not e.eligible(t(dict(heavy, idle=False, **{k: True}))), k


@test("rest_infected gives a busy one's job up (dfhack.job.removeWorker) before the Rest job, and passes over one "
      "still holding a job")
def _():
    body = HEALTH[HEALTH.index("function rest_infected"):]
    i = body.index("dfhack.job.removeWorker(u.job.current_job, 0)")
    assert "goto next_pick" in body[i:i + 200]
    assert i < body.index("job.job_type = df.job_type.Rest")


@test("ai-health.lua compiles under Lua 5.3")
def _():
    lua, _ = pure()
    src = (ROOT / "lua" / "ai-health.lua").read_text(encoding="utf-8")
    f = lua.eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    assert f(src) is None, f(src)


@test("the hospital guard is held 3 days after the last tantrum seen loose (was 1: B ran out each cycle)")
def _():
    assert PLANNER_CONFIG["hospital_guard_hold_ticks"] == 3600


finish()
