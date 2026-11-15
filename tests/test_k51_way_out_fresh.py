"""(0.105.51) The false "sealed in" loop.

R3 live run (15 Nov, six forts): dig_way_in refused ~1,280 times (A 232, B 253,
C 241, D 184, E 186, F 207) and 42 false NEEDS YOU lines. A's 258-spring state
read `way_out.open: false` for walk group 1 though it read open in 257-winter
(edge_groups 60, edge_tiles 1255 in both: the cached read). The cause: the
map-edge walk groups in lua/ai-way-out.lua are cached for EDGE_EVERY reports,
while DF renumbers its walk groups (C: 5166-5173 within minutes), so the
citizens' new number is missing from the stale edge set. The refusals said
(journals): "the fort already has 2 ways to the surface: no second one is
needed" (A 85, B 214, C 140, E 97), "no safe second way in found near ...:
..." (most of D and F), "the gate watcher is armed ..." (B 1, C 2).

Tested here:
  * the game: a closed verdict is never reported from the cache: re-read
    first (`fresh`), so renumbered groups read open; a fort truly sealed
    still reads closed;
  * the guard: no dig and no Needs you without a fresh read; each refusal by
    what it said; the refusal remembered past an open reading; the R3 A
    pattern (sealed/open flips, a refusal each) asks for a handful of digs,
    not one per flip.

    python tests/test_k51_way_out_fresh.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

FAKE = r"""
local src = ...
EDGE_G, INSIDE = 1, 1
G = {IMMINENT = 12, WIDE = 60}
G.GATES = {scanned = true, closed = {}, entrances = {{id = 1, kind = 'surface', x = 5, y = 1, z = 2,
                                                       equipment = {}, outer = {}}}}
G.visible_dangers = function() return {} end
G.distance_to = function() return 100 end
G.lever_links = function() return {}, {} end
U = {REPATH = {n = 0}, repath_summary = function() return {n = 0} end, citizens = function() return {} end}
reqscript = function(n)
  if n == 'ai-gates' then return G end
  if n == 'ai-util' then return U end
  error('reqscript ' .. tostring(n))
end
df = {global = {world = {map = {x_count = 10, y_count = 10, z_count = 5}}, plotinfo = {site_id = 1}},
      building = {find = function() return nil end}}
dfhack = {maps = {}}
xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local env = setmetatable({}, {__index = _G})
assert(load(src, 'ai-way-out', 't', env))()
env.group_at = function(x, y, z)
  if x == 0 or y == 0 or x == 9 or y == 9 then return EDGE_G end
  return INSIDE
end
env.citizen_spots = function() return {{id = 1, x = 4, y = 4, z = 2}, {id = 2, x = 5, y = 5, z = 2}} end
return env
"""


def _world():
    if LuaRuntime is None:
        skip("needs the lupa package")
    L = LuaRuntime(unpack_returned_tuples=True)
    return L, L.execute(FAKE, module_src("ai-way-out.lua"))


@test("game: DF renumbers the walk groups between two reads of the cached edges: the closed verdict is re-read "
      "first and the fort reads open (fresh); a fort truly sealed still reads closed, fresh")
def _():
    L, env = _world()
    r = env.report()
    assert r.open is True and r.inside_group == 1
    # the walk map redone by DF (not by the AI: no repath counted): every group renumbered
    L.execute("EDGE_G, INSIDE = 5170, 5170")
    r = env.report()
    assert r.known is True and r.open is True and r.inside_group == 5170, (r.open, r.inside_group)
    assert r.fresh is True
    # truly cut off now: the citizens' group touches no edge group
    L.execute("INSIDE = 5173")
    r = env.report()
    assert r.open is False and r.fresh is True
    # open from the cache: no re-read, no `fresh` claimed
    L.execute("INSIDE = 5170")
    env.report()
    r = env.report()
    assert r.open is True and r.fresh is None


# --- the guard -----------------------------------------------------------------------

NOW = 120 * 403200 + 5000


def _s(tick=5000, fresh=True, open_=False):
    wo = {"known": True, "open": open_, "inside_group": 5022, "edge_groups": 60, "shut_by": [],
          "nearest_entrances": [1, 2], "cause": {"invaders": 0, "great": 0, "seen": 0}}
    if fresh:
        wo["fresh"] = True
    return {"date": {"year": 120, "tick": tick}, "missions": {},
            "others_on_map": {"threats_that_can_reach_dwarves": 0}, "settings": {"traits": {}},
            "entrances": {"entrances": []}, "way_out": wo}


class _Mem:
    def __init__(self):
        self.way_out = {}
        self.way_in = {}
        self.second_way = {}


def _run(s, m):
    import planner_way_out as pw
    pw.note_way_out_cycle(s, m)
    props, notes = [], []
    pw._way_out_rule(s, pw.PLANNER_CONFIG, props, notes, m)
    return props, notes


def _needs(notes):
    from planner_core import NEEDS_YOU
    return [n for n in notes if n.startswith(NEEDS_YOU)]


@test("guard: a closed verdict not read fresh: no dig and never Needs you, however long")
def _():
    m = _Mem()
    m.way_out = {"since": NOW - 30 * 1200, "digs": 5, "dig_tick": NOW - 30 * 1200}
    props, notes = _run(_s(fresh=False), m)
    assert props == [] and not _needs(notes) and "fresh read" in notes[-1], notes


@test("guard, refusal 'the fort already has 2 ways to the surface': no more digs; the player asked only once it "
      "stays sealed (fresh) way_out_ask_after_ticks")
def _():
    import planner_way_out as pw
    m = _Mem()
    props, _n = _run(_s(), m)
    assert [p.action for p in props] == [{"type": "dig_way_in", "second": True}]
    why = "the fort already has 2 ways to the surface: no second one is needed"
    pw.note_way_out(props[0], {"ok": False, "rejected": True, "error": why, "why": why}, _s(), m, NOW)
    assert m.way_out["refused"]["kind"] == "pointless"
    props, notes = _run(_s(tick=5000 + 6 * 1200), m)     # past the dig retry: no dig, the player asked
    assert props == [] and _needs(notes), notes
    # sealed only a moment: not asked yet
    m2 = _Mem()
    m2.way_out = {"since": NOW, "refused": {"kind": "pointless", "n": 1, "tick": NOW, "why": why}}
    props, notes = _run(_s(tick=5100), m2)
    assert props == [] and not _needs(notes) and "asks the player" in notes[-1], notes
    props, notes = _run(_s(tick=5000 + 700), m2)
    assert props == [] and _needs(notes) and "2 ways to the surface" in _needs(notes)[0], notes


@test("guard, refusal 'no safe second way in found': asked again after 4, 8, 16 days, remembered past an open "
      "reading; 'the gate watcher is armed': not a try, asked again soon")
def _():
    import planner_way_out as pw
    m = _Mem()
    why = ("no safe second way in found near x98 y164 z40: the fort is more than 30 tiles of digging away; "
           "not natural rock (TREE); another AI project; the nearer spots are within 6 tiles of the gate")
    props, _n = _run(_s(), m)
    pw.note_way_out(props[0], {"ok": False, "rejected": True, "error": why, "why": why}, _s(), m, NOW)
    assert m.way_out["refused"] == {"kind": "refused", "n": 1, "tick": NOW, "why": why[:160]}
    # the walk map reads open, then sealed again: the refusal stays
    _run(_s(tick=5600, open_=True), m)
    assert m.way_out.get("refused", {}).get("n") == 1, m.way_out
    props, notes = _run(_s(tick=5000 + 3 * 1200), m)
    assert props == [] and "refused" in notes[-1], notes
    props, _n = _run(_s(tick=5000 + 4 * 1200 + 1), m)
    assert [p.action["type"] for p in props] == ["dig_way_in"]
    pw.note_way_out(props[0], {"ok": False, "why": why}, _s(), m, NOW + 4 * 1200 + 1)
    assert m.way_out["refused"]["n"] == 2
    # second refusal in a row: 8 days
    _run(_s(tick=5000 + 4 * 1200 + 100, open_=True), m)     # (the flip resets the try count, not the refusal)
    assert m.way_out["refused"]["n"] == 2
    props, _n = _run(_s(tick=5000 + 11 * 1200), m)
    assert props == [], "8 days after the second refusal, not 7"
    props, _n = _run(_s(tick=5000 + 12 * 1200 + 2), m)
    assert [p.action["type"] for p in props] == ["dig_way_in"]
    # the watcher armed: not a try
    m3 = _Mem()
    props, _n = _run(_s(), m3)
    w = "the gate watcher is armed (enemies about): no new way in is dug until the alarm is over"
    pw.note_way_out(props[0], {"ok": False, "why": w}, _s(), m3, NOW)
    assert not m3.way_out.get("digs") and "refused" not in m3.way_out
    props, _n = _run(_s(tick=5000 + 200), m3)
    assert [p.action["type"] for p in props] == ["dig_way_in"]
    assert pw.refusal_kind("a way in is already being dug (project 12)") == "wait"


@test("guard, the R3 A pattern replayed (sealed/open flips every ~5,000 ticks for 170,000 ticks, each dig "
      "refused 'no safe second way in found'): a handful of digs, not one per flip")
def _():
    import planner_way_out as pw
    why = "no safe second way in found near x98 y164 z40: not natural rock (TREE); another AI project"
    m = _Mem()
    digs = 0
    t = 44214
    while t < 44214 + 170000:
        props, _n = _run(_s(tick=t), m)
        for p in props:
            if p.action.get("type") == "dig_way_in":
                digs += 1
                pw.note_way_out(p, {"ok": False, "why": why}, _s(tick=t), m, 120 * 403200 + t)
        _run(_s(tick=t + 2500, open_=True), m)       # the next report reads open
        t += 5000
    # unfixed: one per flip (34); now 4, 8, 16, 32, 32... days apart over ~140 days
    assert digs <= 7, digs


@test("refusal_kind reads the game's own words: each phrase it matches is in lua/ai-builder-projects.lua")
def _():
    import planner_way_out as pw
    src = (ROOT / "lua" / "ai-builder-projects.lua").read_text(encoding="utf-8")
    for phrase, kind in (("ways to the surface: no second one is needed", "pointless"),
                         ("gate watcher is armed", "wait"), ("already being dug", "wait"),
                         ("not mapped yet", "wait"), ("search failed", "wait")):
        assert phrase in src, phrase
        assert pw.refusal_kind(f"x {phrase} y") == kind
    assert pw.refusal_kind("no safe second way in found near x1 y2 z3: another AI project") == "refused"


finish()
