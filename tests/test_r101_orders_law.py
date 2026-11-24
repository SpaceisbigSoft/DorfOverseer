"""(0.105.101) The standing orders DFHack misplaces, and the law's slow killers.

Live 24 Nov 11:31, B and C: DFHack 53.17-r1's addresses for 16 standing
orders (gather_refuse_outside, gather_vermin_remains, every dump_*,
forbid_own_dead, forbid_own_dead_items, forbid_other_nohunt,
zoneonly_drink/fish, auto_loom, use_dyed_cloth) lie 9-9.1 MB from the other
21, which sit in one block from standing_orders_mix_food (+0..+24); auto_loom
read 2 there. The AI's "gather refuse from outside" (disposal_outside, five
times 03:39-05:49) went into some other byte of the game and was read back as
set; nothing reached the dump. ai-util's standing_order() now counts an order
only when its address lies by the others (or DF's own name, standingorder_*,
gives one there), else it is missing: never read, never written.

B's sheriff Urdim killed three citizens in y263, y264 and y266 (probe
b-incidents): never two within the killers report's year, so law_swap never
saw two. A law officer's killings now count three years back.

    python tests/test_r101_orders_law.py
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

UTIL_FAKE = r"""
local src = ...
local A = {standing_orders_mix_food = 1000, standing_orders_gather_refuse = 1004,
           standing_orders_gather_refuse_outside = 9001000, standing_orders_dump_other = 9001006,
           standingorder_dump_other = 1030, standingorder_gather_refuse_outside = 1004}
local MEM = {[1030] = 1, [1004] = 1}
df = {global = {standing_orders_mix_food = 1, standing_orders_gather_refuse = 1,
                standing_orders_gather_refuse_outside = 0, standing_orders_dump_other = 0},
      reinterpret_cast = function(t, a) return {value = MEM[a]} end}
dfhack = {internal = {getAddress = function(n) return A[n] end,
                      setAddress = function(n, a) A[n] = a; return true end}}
reqscript = function() return {} end
local env = setmetatable({}, {__index = _G})
local chunk = load(src, 'ai-util', 't', env)
chunk()
return env, A
"""


@test("standing_order: in the block -> the name; away and DF's name on a free byte -> bound there; on a taken byte -> missing")
def _():
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, A = lua.execute(UTIL_FAKE, module_src("ai-util.lua"))
    assert env.standing_order("gather_refuse") == "standing_orders_gather_refuse"
    # DF's own name for dump_other lies in the block on a free byte reading 0/1: bound
    assert env.standing_order("standing_orders_dump_other") == "standing_orders_dump_other"
    assert A["standing_orders_dump_other"] == 1030
    # DF's name for gather_refuse_outside is gather_refuse's byte: never bound, missing
    r = env.standing_order("gather_refuse_outside")
    assert r is None or r == (None, "not by the other standing orders") or (isinstance(r, tuple) and r[0] is None), r
    assert A["standing_orders_gather_refuse_outside"] == 9001000
    # once a session: the answer is kept
    assert env.STANDING_CHECKED["gather_refuse_outside"] is False


@test("bridge files: disposal, provisions and the dead's report ask standing_order before any order")
def _():
    dis = (ROOT / "lua" / "ai-disposal.lua").read_text(encoding="utf-8")
    pro = (ROOT / "lua" / "ai-provisions.lua").read_text(encoding="utf-8")
    sup = (ROOT / "lua" / "ai-bridge-report-supplies.lua").read_text(encoding="utf-8")
    assert "U.standing_order(short)" in dis
    assert "U.standing_order(name)" in pro
    assert "U.standing_order(name)" in sup


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


@test("killers: B's sheriff, kills 2.x and 1.x years ago: law_killer; a civilian's old kills don't count")
def _():
    need_lua()
    lua, env, w = world()
    w.unit(T(lua, {"id": 5, "name": "Sheriff", "citizen": True, "positions": [{"position": {"code": "SHERIFF"}}]}))
    w.unit(T(lua, {"id": 6, "name": "Mason", "citizen": True}))
    for v in (20, 21, 22, 23):
        w.unit(T(lua, {"id": v, "name": f"V{v}", "is_dead": True}))
    kill(lua, w, 6, 22, 298)              # now: y300 tick 0 (the fake)
    kill(lua, w, 6, 23, 298, 200000)
    kill(lua, w, 5, 20, 298)
    kill(lua, w, 5, 21, 298, 200000)
    rows = {x["id"]: dict(x) for x in env.report()["list"].values()}
    assert rows[5].get("law_kills") == 2 and rows[5].get("law_killer") is True, rows[5]
    assert 6 not in rows, rows.get(6)
    assert env.law_killer(5) is True


finish()
