"""(0.105.92) A killer let out of their cell to eat and drink goes back once
fed, not only in the short window while their thirst is under 3000.

Live 23 Nov, B (the Monastery): Led Siguntat "Tourtouches" (seven tantrums, a
killer) was let out at thirst 20000, drank, and her thirst passed 3000 again
before a cycle saw it: ten days loose ("waiting" 60 times an hour), in a
tantrum among the wounded. The timers only fall by drinking and eating, so
under the let-out levels (THIRST_OUT, HUNGER_OUT) means fed.

    python tests/test_r92_killer_back.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402

SRC = (ROOT / "lua" / "ai-killers.lua").read_text(encoding="utf-8")


@test("ai-killers: one let out stays out only while at or over the let-out levels (THIRST_OUT, HUNGER_OUT)")
def _():
    assert re.search(r"if c\.out and \(th >= THIRST_OUT or hu >= HUNGER_OUT\) then", SRC), "the back test"
    assert not re.search(r"th > THIRST_BACK or hu > HUNGER_BACK", SRC), "the old 3000 window"
    m = re.search(r"THIRST_OUT, HUNGER_OUT = (\d+), (\d+)", SRC)
    assert m and int(m.group(1)) == 20000 and int(m.group(2)) == 40000, m


@test("ai-killers.lua compiles under Lua 5.3")
def _():
    need_lua()
    from lupa.lua53 import LuaRuntime
    f = LuaRuntime().eval("function(s) local f, e = load(s, 'b', 't', {}) return e end")
    assert f(SRC) is None, f(SRC)


finish()
