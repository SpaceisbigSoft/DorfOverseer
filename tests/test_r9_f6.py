"""(r9, f6) The low-FPS back-off's measure carried into the cycle's state
(B8: the saved states read fps_low None while their perf.fps said 4-24);
every CACHE_INVALIDATES entry names a real action and real sections.

    python tests/test_r9_f6.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402


class SlowGame:
    """A running fort at 15 FPS whose date moves."""
    def __init__(self):
        self.t, self.acts = 100, []

    def handshake(self):
        return {"bridge_version": "x", "dfhack_version": "y"}

    def status(self):
        self.t += 40
        return {"in_fort": True, "paused": False, "halted": False, "fps": 15,
                "date": {"year": 150, "tick": self.t, "day": 1, "month": "Granite", "season": "spring"}}

    def act(self, a):
        self.acts.append(a)
        return {"ok": True}


@test("(r9, B8) the loop's fps_low and what it judged by reach the cycle; the cycle puts both in its state")
def _():
    seen = []
    real = (overseer.one_cycle, overseer.Bridge, time.monotonic, time.sleep, sys.argv, overseer.say)
    clock, calls = [0.0], [0]

    def fake_sleep(_s):
        calls[0] += 1
        clock[0] += 2.0
        if calls[0] >= 400:
            raise KeyboardInterrupt
    overseer.one_cycle = lambda bridge, autopilot, backend=None, controls=None, **kw: seen.append(dict(controls))
    overseer.Bridge = SlowGame
    time.monotonic = lambda: clock[0]
    time.sleep = fake_sleep
    overseer.say = lambda m: None
    sys.argv = ["overseer.py", "--autopilot", "--unattended"]
    overseer.FPS_PEAK["fps"] = 0
    try:
        overseer.main()
    finally:
        overseer.one_cycle, overseer.Bridge, time.monotonic, time.sleep, sys.argv, overseer.say = real
    assert seen and seen[-1]["fps_low"] == 15, [c.get("fps_low") for c in seen]
    fs = seen[-1]["fps_seen"]
    assert fs["median"] == 15 and fs["low"] == 15 and fs["samples"] >= 30, fs
    # the cycle: both into the state (kept as it is in the saved season states)
    import overseer_cycle
    got = {}
    real2 = (overseer.get_state, overseer.fort_key, overseer.say)
    overseer.get_state = lambda bridge, tier: got.setdefault("s", {"date": {}})
    overseer.fort_key = lambda s: None                 # the cycle stops right after
    overseer.say = lambda m: None
    try:
        overseer_cycle.one_cycle(None, False, None, {"fps_low": 15, "fps_seen": fs})
    finally:
        overseer.get_state, overseer.fort_key, overseer.say = real2
    assert got["s"]["fps_low"] == 15 and got["s"]["fps_seen"] == fs, got


@test("(r9) CACHE_INVALIDATES: every key is a bridge action and every section it names a report section")
def _():
    from harness import need_lua
    need_lua()
    import bridge_behaviour as BB
    env = BB.hub()
    pairs = BB.lua().eval("""function(env)
        local out = {}
        for a, secs in pairs(env.CACHE_INVALIDATES) do
            for _, s in ipairs(secs) do out[#out + 1] = {a, s} end
        end
        return out end""")(env)
    bad = []
    for i in range(1, len(pairs) + 1):
        a, sec = pairs[i][1], pairs[i][2]
        if env.ACTIONS[a] is None:
            bad.append(("no action", a))
        if env.SECTIONS[sec] is None:
            bad.append(("no section", a, sec))
    assert len(pairs) > 50 and not bad, bad


if __name__ == "__main__":
    finish()
