"""(0.105.36, group builder) The focused audit's builder findings (D3) and
X1's cistern shut:

- a way in's or cavern well's marker-only shaft, stair or gallery tile is made
  real by unmark_project_dig (it went over the plain dig cells only, so the
  brain asked for ever); a way in whose marker step could not be made real
  ends (cancel) instead of holding the emergency slot for good
- a cistern that leaked once through a gap: the bridge walls the gap up after
  the water has gone (it waited for ever); the brain retires one whose gap the
  game won't let it close
- cistern_retire retires only with its floodgate shut
- count_items counts a part carried to its job as reserved
- the cistern's "shut it now" is a rule of its own, never held by the cistern
  rule's cooldown

    python tests/test_r36_builder.py
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import make_test, finish  # noqa: E402

import planner_core  # noqa: E402
import planner_wells as pw  # noqa: E402
from planner import Memory, plan, select  # noqa: E402
from planner_core import abs_tick  # noqa: E402
import test_planner as TPL  # noqa: E402
import test_r32_wayin as R32  # noqa: E402   (the way-in rig; its tests run only when it is run itself)
from test_r35_core import TILE_FLAGS_FAKE, TILE_FLAGS_CLEAN  # noqa: E402
import test_r35_fix as R35F  # noqa: E402   (the cistern rig)

test = make_test()
LUA, B, W = R32.LUA, R32.B, R32.W


def _open1():
    return B.projects_report().open[1]


# --- D3 Med 1: a way in's marker-only step --------------------------------------------

@test("way in: a marker-only column step is made real by unmark_project_dig (the real make_dig_real); then dug, finished")
def _():
    W.reset()
    assert R32.way_in().ok
    W.dig_all()
    t = W.get(41, 25, 27)
    t.shape, t.designated, t.marked = "WALL", False, True
    blocks = LUA.execute(TILE_FLAGS_FAKE, W)
    try:
        o = _open1()
        assert o.dig.marked == 1 and o.dig.dug == 6 and o.next is False, (dict(o.dig), o.next)
        d = B.unmark_project_dig(o.id, True)
        assert d.ok and d.dry_run and d.tiles == 1 and not W.get(41, 25, 27).designated, dict(d)
        d = B.unmark_project_dig(o.id, False)
        assert d.ok and d.tiles == 1 and W.get(41, 25, 27).designated and not W.get(41, 25, 27).marked, dict(d)
        assert any(b.flags.designated for b in blocks.values())
        W.dig_all()
        o = _open1()
        assert o.next == "finish" and o.dig.dug == o.dig.total == 7, (o.next, dict(o.dig))
    finally:
        LUA.execute(TILE_FLAGS_CLEAN)


@test("way in: a marker step that could not be made real counts as missing: the way in is cancelled, not held for good")
def _():
    W.reset()
    assert R32.way_in().ok
    W.dig_all()
    t = W.get(41, 25, 27)
    t.shape, t.designated, t.marked = "WALL", False, True
    real = B.make_dig_real
    B.make_dig_real = LUA.eval("function() return false end")
    try:
        o = _open1()
        assert o.next is False, o.next                     # not tried yet: the unmark first
        d = B.unmark_project_dig(o.id, False)
        assert not d.ok and "could be made real" in d.error, dict(d)
        o = _open1()
        assert o.dig.marked == 1 and o.next == "cancel", (dict(o.dig), o.next)
    finally:
        B.make_dig_real = real


@test("way in: a step still being dug never counts as missing (no cancel while the rest waits)")
def _():
    W.reset()
    assert R32.way_in().ok
    o = _open1()
    assert o.next is False and o.dig.dug == 0, (o.next, dict(o.dig))


@test("cavern well: marker-only shaft and gallery tiles are found and made real")
def _():
    import test_builder as TB
    TB._reset(False)
    TB.lake_beside()
    r = TB.gallery_well()
    assert r.ok, r.error
    n = 0
    for t in TB.W.tiles.values():
        if t.designated:
            t.designated, t.marked = False, True
            n += 1
    assert n > 16
    TB.LUA.execute(TILE_FLAGS_FAKE, TB.W)
    try:
        pid = TB.B.projects_report().open[1].id
        assert TB.B.projects_report().open[1].dig.marked == n
        d = TB.B.unmark_project_dig(pid, False)
        assert d.ok and d.tiles == n and TB.designated_count() == n, (dict(d), n)
        assert TB.B.projects_report().open[1].dig.marked == 0
    finally:
        TB.LUA.execute(TILE_FLAGS_CLEAN)


# --- D3 Med 2: a leak through a gap ---------------------------------------------------

_CIST_RIG = """
  local B = ...
  df.building_type[9] = 'Floodgate'; df.building_type.Floodgate = 9
  local g = MKS(80, 50, 60, 9, true); g.gate_flags = {closed = true}
  WET = {}
  B.tile_info = function(x, y, z) return {shape = 'FLOOR', liquid = WET[x..','..y..','..z] == true, magma = false} end
  B.cistern_status = function() return {depth = 2} end
  SEALED = false
  B.cistern_sealed = function()
    if SEALED then return true end
    return false, 'x9 y12 elevation 40', {{words = 'x9 y12'}}
  end
  local C = {n = 0}
  GAPS_RESULT = {ok = true, sealing = true}
  B.cistern_close_gaps = function(d, p, gaps, dry_run, save)
    C.n = C.n + 1
    local r = {}
    for k, v in pairs(GAPS_RESULT) do r[k] = v end
    return r
  end
  B.pull = function() return true end
  return C
"""


def _cistern_store():
    T = R35F.LUA_T
    R35F._STORE["ai-overseer/cistern"] = T({"stage": "filling", "plan": T({
        "v": 2, "floodgate": T({"x": 80, "y": 50}), "intake_z": 60,
        "cistern": T({"z": 60, "x1": 10, "y1": 10, "x2": 14, "y2": 14}), "well": T({"x": 12, "y": 12, "z": 62}),
        "plug": T({"x": 79, "y": 50}), "tunnel_path": T([]), "source": "pool"})})


@test("cistern lua: leaked once through a gap: once dry and shut, the AI walls the gap up (the leak kept); closed: cleared")
def _():
    BL, Bc = R35F._BL, R35F._B
    real = {k: Bc[k] for k in ("tile_info", "cistern_status", "cistern_sealed", "cistern_close_gaps", "pull")}
    BL.execute(R35F.GAME_FAKE)
    try:
        calls = BL.execute(_CIST_RIG, Bc)
        _cistern_store()
        wet = BL.eval("WET")
        wet["11,11,62"] = True
        r = Bc.cistern_step(False)
        assert r.leak and r.shut, dict(r)
        wet["11,11,62"] = None
        r = Bc.cistern_step(True)                           # a dry run: the gaps' dry run, nothing saved
        d = R35F._STORE["ai-overseer/cistern"]
        assert calls.n == 1 and d.leak and d.unsealed is None, (calls.n, d.unsealed)
        for _ in range(5):
            r = Bc.cistern_step(False)
        d = R35F._STORE["ai-overseer/cistern"]
        assert calls.n == 6 and d.leak and d.leaks == 1 and d.unsealed == "x9 y12 elevation 40", (calls.n, d.unsealed)
        assert r.ok and r.sealing and r.leak == d.leak and r.leaks == 1, dict(r)
        BL.execute("SEALED = true")
        try:
            Bc.cistern_step(False)        # cleared; the filling step after it may want more of the game
        except Exception:  # noqa: BLE001
            pass
        d = R35F._STORE["ai-overseer/cistern"]
        assert d.leak is None and d.unsealed is None and d.leaks == 1 and calls.n == 6, (d.leak, d.unsealed)
    finally:
        for k, v in real.items():
            Bc[k] = v
        BL.execute(R35F.GAME_CLEAN)


def _cistern_state(**k):
    s = TPL.fort()
    s["water"] = dict(s.get("water") or {}, cistern_status=dict({"v": 2, "stage": "filling", "gate": "shut",
                                                                  "depth": 2}, **k))
    return s


@test("cistern: a leak through a gap the game won't let the AI close is retired after its tries; before, the step")
def _():
    s = _cistern_state(leak="x11 y11 elevation 62", leaks=1, unsealed="x9 y12 elevation 40")
    props, notes = plan(copy.deepcopy(s), Memory())
    c = [p for p in props if p.rule == "cistern"]
    assert len(c) == 1 and not c[0].action.get("retire"), [p.action for p in c]
    assert any("walls up the gap at x9 y12" in n for n in notes), notes
    s = _cistern_state(leak="x11 y11 elevation 62", leaks=1, unsealed="x9 y12 elevation 40",
                       unsealed_why="x9 y12: a stair there", unsealed_refusals=pw.CISTERN_RETRY_SEALS - 1)
    c = [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "cistern"]
    assert len(c) == 1 and not c[0].action.get("retire"), [p.action for p in c]
    s["water"]["cistern_status"]["unsealed_refusals"] = pw.CISTERN_RETRY_SEALS
    c = [p for p in plan(copy.deepcopy(s), Memory())[0] if p.rule == "cistern"]
    assert len(c) == 1 and c[0].action.get("retire") is True and "a stair" in c[0].action["why"], [p.action for p in c]


# --- D3 Low: cistern_retire only with its floodgate shut ------------------------------

def _retire_rig(closed, lever, pull_ok=True, closes=True):
    BL, Bc = R35F._BL, R35F._B
    BL.execute("df.building_type[9] = 'Floodgate'; df.building_type.Floodgate = 9")
    g = BL.eval("function(c) local b = MKS(80, 50, 60, 9, true); b.gate_flags = {closed = c}; return b end")(closed)
    pulls = BL.execute("""local B, g, ok, closes = ...; local P = {}
      B.pull = function(id, i) P[#P + 1] = id; if ok and closes then g.gate_flags.closed = true end
        return ok, ok and '' or 'no such lever' end
      return P""", Bc, g, pull_ok, closes)
    T = R35F.LUA_T
    R35F._STORE["ai-overseer/cistern"] = T(dict({"stage": "done", "plan": T({
        "floodgate": T({"x": 80, "y": 50}), "intake_z": 60, "cistern": T({"z": 60})})},
        **({"lever_id": 5} if lever else {})))
    R35F._STORE["ai-overseer/cistern/retired"] = None
    return Bc, pulls


@test("cistern_retire: an open floodgate is shut first; no lever: not retired (said, and it keeps watching it)")
def _():
    BL, Bc = R35F._BL, R35F._B
    real_pull = Bc.pull
    BL.execute(R35F.GAME_FAKE)
    try:
        Bc, pulls = _retire_rig(False, True)
        r = Bc.cistern_retire(False, "leaked twice")
        assert r.ok and r.retired and list(pulls.values()) == [5], dict(r)
        Bc, pulls = _retire_rig(False, False)
        for dry in (True, False):
            r = Bc.cistern_retire(dry, "leaked twice")
            assert not r.ok and r.rejected and "no lever" in r.error and len(pulls) == 0, dict(r)
        assert R35F._STORE["ai-overseer/cistern"].stage == "done"
        Bc, pulls = _retire_rig(False, True, pull_ok=False)
        r = Bc.cistern_retire(False, "leaked twice")
        assert not r.ok and "would not shut" in r.error and R35F._STORE["ai-overseer/cistern"].stage == "done", dict(r)
        Bc, pulls = _retire_rig(True, False)                # shut already, no lever: retired
        r = Bc.cistern_retire(False, "leaked twice")
        assert r.ok and r.retired and len(pulls) == 0, dict(r)
    finally:
        Bc.pull = real_pull
        BL.execute(R35F.GAME_CLEAN)


# --- D3 Low: count_items and a part carried to its job --------------------------------

@test("count_items: a part carried to its job is reserved; one carried for nothing, or forbidden, counts as neither")
def _():
    BL, Bc = R35F._BL, R35F._B
    BL.execute(R35F.GAME_FAKE)
    try:
        r = BL.execute("""local B = ...
          local SAVED = {items = dfhack.items, other = df.global.world}
          local U = {}
          dfhack.items = setmetatable({getHolderUnit = function(it) return it.held and U or nil end},
                                      {__index = SAVED.items})
          local function item(f, held) f.in_inventory = held or nil; return {flags = f, held = held} end
          df.global.world = {items = {other = {TRAPPARTS = {
            item({}), item({in_job = true}), item({in_job = true}, true), item({}, true), item({forbid = true}),
            item({in_job = true, forbid = true}, true)}}}}
          local free, reserved = B.count_items('TRAPPARTS')
          dfhack.items, df.global.world = SAVED.items, SAVED.other
          return {free, reserved}""", Bc)
        assert (r[1], r[2]) == (1, 2), (r[1], r[2])
    finally:
        BL.execute(R35F.GAME_CLEAN)


# --- X1: the cistern's shut never waits out the cistern rule's cooldown --------------

@test("cistern shut: its own rule (no cooldown, emergency, never held by the strategist); allowed right after a step")
def _():
    r = pw.CISTERN_SHUT_RULE
    assert r in planner_core.NO_COOLDOWN and r in planner_core.EMERGENCY and r in planner_core.LIMIT_EXEMPT
    assert r in planner_core.STEER_PROTECTED
    s = _cistern_state(stage="done", gate="open", depth=3, sealed_now=False, unsealed="x10 y10 z100")
    m = Memory()
    m.last_fired["cistern"] = abs_tick(s) - 300            # a routine cistern step a quarter day earlier
    props, notes = plan(copy.deepcopy(s), m)
    allowed, held = select(props, s, m)
    c = [p for p in allowed if p.rule == r]
    assert c and c[0].action == {"type": "cistern_step", "shut": True}, [(p.rule, p.action) for p in allowed]
    assert not any(h.startswith(r) for h in held), held


if __name__ == "__main__":
    finish()
