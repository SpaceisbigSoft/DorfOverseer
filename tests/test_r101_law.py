"""(0.105.101) The law's slow killers.

B's sheriff Urdim killed three citizens in y263, y264 and y266 (probe
b-incidents, 24 Nov 11:31): never two within the killers report's year, so
law_swap never saw two. A law officer's killings now count three years back;
anyone else's still one.

    python tests/test_r101_law.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

ITEM3 = (ROOT / "tests" / "test_item3_killers.py").read_text(encoding="utf-8")
FAKE = re.search(r'FAKE = r"""(.*?)"""', ITEM3, re.S).group(1)

def world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-killers.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def kill(lua, w, killer, victim, year, tick=0):
    w.incidents[len(w.incidents) + 1] = T(lua, {"criminal": killer, "victim": victim, "death_cause": 7,
                                                "conflict_level": 0, "event_year": year, "event_time": tick})


@test("killers: B's sheriff, kills 2.x and 1.x years ago: law_killer; a civilian's kills count three years back too (0.105.107), older ones don't")
def _():
    need_lua()
    lua, env, w = world()
    w.unit(T(lua, {"id": 5, "name": "Sheriff", "citizen": True, "positions": [{"position": {"code": "SHERIFF"}}]}))
    w.unit(T(lua, {"id": 6, "name": "Mason", "citizen": True}))
    for v in (20, 21, 22, 23):
        w.unit(T(lua, {"id": v, "name": f"V{v}", "is_dead": True}))
    kill(lua, w, 6, 22, 296)              # now: y300 tick 0 (the fake): past three years
    kill(lua, w, 6, 23, 296, 200000)
    kill(lua, w, 5, 20, 298)
    kill(lua, w, 5, 21, 298, 200000)
    rows = {x["id"]: dict(x) for x in env.report()["list"].values()}
    assert rows[5].get("law_kills") == 2 and rows[5].get("law_killer") is True, rows[5]
    assert 6 not in rows, rows.get(6)
    assert env.law_killer(5) is True


finish()
