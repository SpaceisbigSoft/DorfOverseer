"""Tests for lua/ai-status.lua (the in-game panel's data and the halt switch),
in a real Lua engine (pip install lupa).

    python tests/test_status.py
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

LUA = LuaRuntime(unpack_returned_tuples=True)
SRC = (ROOT / "lua" / "ai-status.lua").read_text(encoding="utf-8")
M, SAVE = LUA.execute(r"""
local src = ...
local save = {}
_G.SC_MAP_UNLOADED = 99
_G.dfhack = {isMapLoaded = function() return true end, onStateChange = {},
  persistent = {getSiteData = function(k, d) return save[k] or d end,
                saveSiteData = function(k, v) save[k] = v end},
  gui = {showAnnouncement = function() end}}
_G.COLOR_LIGHTRED, _G.COLOR_LIGHTGREEN = 12, 10
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-status', 't', env))()
return env, save
""", SRC)


def t(d):
    out = LUA.table()
    for k, v in d.items():
        if isinstance(v, dict):
            out[k] = t(v)
        elif isinstance(v, list):
            lst = LUA.table()
            for i, x in enumerate(v, 1):
                lst[i] = t(x) if isinstance(x, dict) else x
            out[k] = lst
        else:
            out[k] = v
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


@test("halt switch is saved with the fort and toggles")
def _():
    assert M.is_halted() is False
    M.set_halted(True)
    assert M.is_halted() is True and SAVE["ai-overseer/halt"].halted is True
    M.set_halted(False)
    assert M.is_halted() is False


@test("status report: text cleaned and capped, odd pending ids refused, at most 3 questions")
def _():
    ok = M.set_status(t({"mode": "Co-pilot", "acting": "acting", "last": ["a\nb", "x" * 500],
                         "pending": [{"id": "abc123", "text": "dig"}, {"id": "bad id!", "text": "x"},
                                     {"id": "d1", "text": "a"}, {"id": "d2", "text": "b"},
                                     {"id": "d3", "text": "c"}]}))
    assert ok
    s = M.STATUS
    assert s.last[1] == "a b" and len(s.last[2]) == 90
    ids = [s.pending[i].id for i in range(1, len(s.pending) + 1)]
    assert ids == ["abc123", "d1", "d2"], ids


@test("the player's to-do list is kept (cleaned, at most 10)")
def _():
    M.set_status(t({"mode": "x", "acting": "y", "todo": ["set up a burrow\nnow"] + [f"t{i}" for i in range(15)]}))
    todo = M.STATUS.todo
    assert todo[1] == "set up a burrow now" and len(todo) == 10, [todo[i] for i in range(1, len(todo) + 1)]


@test("answers wait for the overseer, then are forgotten once it acknowledges them")
def _():
    M.decide("abc123", True)
    M.decide("evil id", True)               # ignored
    d = M.decisions()
    assert d["abc123"] == "yes" and d["evil id"] is None
    M.set_status(t({"mode": "x", "acting": "y", "ack": ["abc123"]}))
    assert M.decisions()["abc123"] is None



@test("a different fort: the old report and answers are forgotten")
def _():
    M.set_status(t({"mode": "x", "acting": "y", "pending": [{"id": "q1", "text": "dig"}]}))
    M.decide("q1", True)
    M.mark_seen()
    assert M.LAST_SEEN is not None
    LUA.globals().dfhack.onStateChange["ai-status"](99)
    assert M.STATUS is None and M.decisions()["q1"] is None and M.LAST_SEEN is None


if __name__ == "__main__":
    for name, ok, msg in RESULTS:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"\n        {msg}" if msg else ""))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print(f"\n{len(RESULTS) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
