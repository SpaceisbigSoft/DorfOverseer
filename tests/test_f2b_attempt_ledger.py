"""(F2b) One attempt ledger for every action (brain/planner_attempts.py):
keyed by the action's type and all its parameters, with the target the bridge
answered with and the reason (counts aside); outcomes ok, refused, error and
"done, nothing changed"; a failed key held until what it depends on changes
(never the bridge's version), with a doubling time backstop in game days and
real minutes; the same no for the same target three times: the backstop, said
once ("held: <action> at <target>: <reason> x3").

Evidence: D, 26 Nov: a butcher's shop (its site chosen in Lua) refused about
19 times in 7 h, its waits doubled to 64 then 84 game days, a game day being
about one cycle; a refusal began no cooldown; a new bridge version tried again
at once (gap-F, F2).

    python tests/test_f2b_attempt_ledger.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import PLANNER_CONFIG, Memory, plan, record, select, abs_tick, TICKS_PER_DAY, TICKS_PER_YEAR  # noqa: E402
from planner_core import Proposal  # noqa: E402
import planner_attempts as A  # noqa: E402
import planner_refusal_streak as rs  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(PLANNER_CONFIG)
NO_ROOM = "no room for a 5x5 workshop near the stockpiles (3 sites looked at)"


def fort(fps=None, version="0.105.134"):
    s = copy.deepcopy(BASE)
    s["date"] = dict(s["date"], year=250, tick=200000, season="summer")
    s["bridge_version"] = version
    s["projects"] = dict(s.get("projects") or {}, done_total=57)
    if fps is not None:
        s["perf"] = {"fps": fps}
    return s


def at(s, days):
    t = abs_tick(s) + int(days * TICKS_PER_DAY)
    s = copy.deepcopy(s)
    s["date"] = dict(s["date"], year=t // TICKS_PER_YEAR, tick=t % TICKS_PER_YEAR)
    return s


def shop():
    return Proposal("build", {"type": "build_workshop", "kind": "Butchers"}, "no butcher's shop", 6)


def refuse(p, s, m, n=1, why=NO_ROOM, **extra):
    for _ in range(n):
        record([(p, dict({"ok": False, "error": why}, **extra))], s, m, CFG)


def held(p, s, m):
    """Only the ledger: the other back-offs set aside."""
    m.last_fired.clear()
    m.refusals.clear()
    m.refusal_streaks.clear()
    allowed, h = select([p], s, m, CFG)
    return not allowed, h


def rec_of(m, p):
    return A.ledger_book(m).get(A.attempt_key(p))


@test("the key: the type and all parameters (lists in any order); a changed parameter is another key")
def _():
    a = Proposal("x", {"type": "give_room", "unit_id": 4, "ids": [3, 1, 2], "extra": {"b": 1, "a": 2}}, "", 5)
    b = Proposal("y", {"extra": {"a": 2, "b": 1}, "ids": [1, 2, 3], "unit_id": 4, "type": "give_room"}, "", 5)
    assert A.attempt_key(a) == A.attempt_key(b)
    assert A.attempt_key(a) == A.attempt_key(Proposal("x", dict(a.action, dry_run=True), "", 5))
    assert A.attempt_key(a) != A.attempt_key(Proposal("x", dict(a.action, unit_id=5), "", 5))
    # a parameter the old REFUSAL_KEYS left out still makes another key
    assert A.attempt_key(a) != A.attempt_key(Proposal("x", dict(a.action, floor=3), "", 5))


@test("the target from the answer: ids, x/y/z, at/pos, coordinates in the words, a raised refusal's _target")
def _():
    assert A.reply_target({"ok": True, "building_id": 77}) == "building 77"
    assert A.reply_target({"ok": False, "x": 1, "y": 2, "z": 3}) == "(1,2,3)"
    assert A.reply_target({"ok": True, "at": {"x": 5, "y": 6, "z": 7}}) == "(5,6,7)"
    assert A.reply_target({"ok": True, "at": [5, 6]}) == "(5,6)"
    assert A.reply_target({"ok": False, "error": "blocked at 10, 20, 30 by a wall"}) == "(10,20,30)"
    assert A.reply_target({"ok": False, "error": "nothing"}) == ""
    assert A.refusal_target({"ok": False, "site": {"x": 1, "y": 2, "z": 3}, "error": "x"}) == {"_target": "(1,2,3)"}
    assert A.refusal_target(None) == {} and A.reply_target({"_target": "site 4"}) == "site 4"
    import bridge
    e = bridge._refused({"ok": False, "error": "no", "building_id": 9})
    assert isinstance(e, bridge.BridgeError) and str(e) == "no" and e.reply["building_id"] == 9
    assert bridge.BridgeError("x").reply is None


@test("the reason without its counts; outcomes: ok, refused, error (Lua), none; the halt and waits not counted")
def _():
    assert A.norm_reason(NO_ROOM) == A.norm_reason(NO_ROOM.replace("3 sites", "4 sites"))
    assert A.outcome_of({"ok": True}) == "ok"
    assert A.outcome_of({"ok": False, "error": "no"}) == "refused"
    assert A.outcome_of({"ok": False, "error": "ai-x.lua:12: attempt to index a nil value"}) == "error"
    assert A.outcome_of({"ok": None, "error": "no reply from the game"}) == "error"
    for r in ({"ok": False, "halted": True}, {"ok": False, "waiting": True}, {"ok": False, "timed_out": True}):
        assert A.outcome_of(r) is None, r


@test("D's shop: refused at the site Lua chose, held 1 day then 2; the same no there three times: the backstop, "
      "said once")
def _():
    s, m, p = fort(), Memory(), shop()
    refuse(p, s, m, 1, x=40, y=50, z=10)
    r = rec_of(m, p)
    assert r["o"] == "refused" and r["t"] == "(40,50,10)" and r["u"] - r["at"] == TICKS_PER_DAY, r
    h, lines = held(p, s, m)
    assert h and "at (40,50,10)" in lines[0] and "tries again in 1 day(s)" in lines[0], lines
    assert not held(p, at(s, 1.01), m)[0], "the day is over"
    refuse(p, s, m, 1, x=40, y=50, z=10)
    assert rec_of(m, p)["u"] - rec_of(m, p)["at"] == 2 * TICKS_PER_DAY
    refuse(p, s, m, 1, x=40, y=50, z=10)
    r = rec_of(m, p)
    assert r["s"] == 3 and r["x"] == 3 and r["u"] - r["at"] == 28 * TICKS_PER_DAY, r
    _props, notes = plan(s, m)
    said = [n for n in notes if n.startswith("held: ")]
    assert said == ["held: build workshop Butchers at (40,50,10): " + A.norm_reason(NO_ROOM) + " x3"], said
    h, lines = held(p, at(s, 20), m)
    assert h and "x3" in lines[0], lines
    _props, notes = plan(s, m)
    assert not [n for n in notes if n.startswith("held: ")], "said once"
    # the backstop doubles, capped
    days = []
    for _ in range(6):
        refuse(p, s, m, 1, x=40, y=50, z=10)
        days.append((rec_of(m, p)["u"] - rec_of(m, p)["at"]) // TICKS_PER_DAY)
    assert days == [56, 112, 224, 336, 336, 336], days


@test("a new bridge version is no reason to try again; a changed target or reason begins the streak again")
def _():
    s, m, p = fort(), Memory(), shop()
    refuse(p, s, m, 3, x=40, y=50, z=10)
    assert held(p, fort(version="0.105.135"), m)[0], "a new bridge: still held"
    refuse(p, s, m, 1, x=41, y=50, z=10)
    assert rec_of(m, p)["s"] == 1 and "x" not in rec_of(m, p), "another site: the streak begins again"
    refuse(p, s, m, 1, why="no stone for it", x=41, y=50, z=10)
    assert rec_of(m, p)["s"] == 1 and rec_of(m, p)["n"] == 5, rec_of(m, p)


@test("held until what it depends on changes: a new level ends a hold for room, a migrant one for 'nobody free'")
def _():
    s, m, p = fort(), Memory(), shop()
    refuse(p, s, m, 3)
    assert held(p, s, m)[0]
    s2 = copy.deepcopy(s)
    s2["projects"]["done_total"] += 1
    assert not held(p, s2, m)[0], "a new level: asked at once"
    q = Proposal("staff", {"type": "staff_location", "location_id": 3, "post": "TAVERN_KEEPER"}, "x", 6)
    s3 = copy.deepcopy(s)
    m2 = Memory()
    refuse(q, s3, m2, 3, why="nobody free to take the post (2 kept out)")
    assert held(q, s3, m2)[0]
    s4 = copy.deepcopy(s3)
    s4["dwarves"]["adults"] += 1
    assert not held(q, s4, m2)[0], "a new dwarf: asked again"
    assert held(q, s3, m2)[0], "the same dwarves: still held"


@test("real minutes in a fast fort: the first wait is at least 2 real minutes, the backstop an hour")
def _():
    s, m, p = fort(fps=100), Memory(), shop()
    refuse(p, s, m, 1)
    r = rec_of(m, p)
    assert r["u"] - r["at"] == max(TICKS_PER_DAY, 100 * 60 * 2)
    refuse(p, s, m, 2)
    r = rec_of(m, p)
    assert r["u"] - r["at"] == max(28 * TICKS_PER_DAY, 100 * 60 * 60), r


@test("ok clears the hold; done and nothing changed three times (record_no_effect) holds; note_no_effect wires it")
def _():
    s, m, p = fort(), Memory(), shop()
    refuse(p, s, m, 2)
    record([(p, {"ok": True, "building_id": 12})], s, m, CFG)
    r = rec_of(m, p)
    assert r["o"] == "ok" and "u" not in r and r["t"] == "building 12"
    assert not held(p, s, m)[0]
    now = abs_tick(s)
    for i in range(2):
        A.record_no_effect(m, A.attempt_key(p), now)
        assert "u" not in rec_of(m, p), "unsure: not held before the streak"
    A.record_no_effect(m, p, now)
    r = rec_of(m, p)
    assert r["o"] == "none" and r["x"] == 3 and r["t"] == "building 12" and isinstance(r["u"], int), r
    h, lines = held(p, s, m)
    assert h and "done, nothing changed x3" in lines[0], lines
    # the opt-in no-effect rules: the same reason again after a done one is a "none"
    m = Memory()
    q = Proposal("quivers", {"type": "give_quiver", "unit_id": 5}, "1 without a quiver and 1 free", 6)
    for i in range(4):
        record([(q, {"ok": True})], s, m, CFG)
    r = rec_of(m, q)
    assert r["o"] == "none" and r["s"] == 3 and isinstance(r["u"], int), r


@test("a Lua error is held as a refusal; no answer (ok None) only from the streak on")
def _():
    s, m, p = fort(), Memory(), shop()
    refuse(p, s, m, 1, why="ai-builder.lua:100: attempt to index a nil value (field 'grid')")
    assert rec_of(m, p)["o"] == "error" and isinstance(rec_of(m, p)["u"], int)
    m, p = Memory(), shop()
    for i in range(3):
        record([(p, {"ok": None, "error": "no reply from the game (timeout)"})], s, m, CFG)
        assert ("u" in rec_of(m, p)) == (i == 2), rec_of(m, p)


@test("never held: an emergency rule, the critical defence, a release; dry runs not counted")
def _():
    s = fort()
    for q in (Proposal("threat_alert", {"type": "civ_alert", "on": True}, "x", 1),
              Proposal("gate_doors", {"type": "build_gate_doors", "id": 3}, "x", 1),
              Proposal("calm_burrow", {"type": "calm_burrow", "release": True}, "x", 1)):
        m = Memory()
        refuse(q, s, m, 4, why="nobody can reach it")
        assert not held(q, s, m)[0], q.rule
    m, p = Memory(), Proposal("build", {"type": "build_workshop", "kind": "Butchers", "dry_run": True}, "x", 6)
    refuse(p, s, m, 3)
    assert not A.ledger_book(m), A.ledger_book(m)


@test("kept through the save (Memory.repeat_book); an old save without it loads; at most LEDGER_KEEP records")
def _():
    s, m, p = fort(), Memory(), shop()
    refuse(p, s, m, 3, x=1, y=2, z=3)
    m2 = Memory.from_dict(json.loads(json.dumps(m.to_dict())))
    assert rec_of(m2, p) == rec_of(m, p) and held(p, s, m2)[0]
    old = m.to_dict()
    old.pop("repeat_book")
    m3 = Memory.from_dict(old)
    assert not held(p, s, m3)[0] and A.ledger_book(m3) == {}
    for i in range(A.LEDGER_KEEP + 10):
        refuse(Proposal("homes", {"type": "give_room", "unit_id": i}, "x", 6), at(s, i / 100), m, 1, why="no room")
    assert len(A.ledger_book(m)) == A.LEDGER_KEEP
    assert rec_of(m, p) is not None, "a hold still running is kept longest"
    # an older save: the game's time went back, the hold no longer holds
    assert A.ledger_wait(m, p, s, abs_tick(s) - 10) is None


@test("the working memory's budget: a full ledger beside full refusal streaks and a long fort's dead")
def _():
    import memstore
    from tokens import TokenBank
    s, m = fort(), Memory()
    for i in range(A.LEDGER_KEEP + 5):
        q = Proposal("build", {"type": "build_workshop", "kind": f"Shop{i:03d}", "ids": list(range(20))}, "x", 6)
        refuse(q, at(s, i / 100), m, 3, why="w" * 200 + " (a long bracketed list " + "z" * 100 + ")",
               x=100 + i, y=200, z=30)
    assert len(A.ledger_book(m)) == A.LEDGER_KEEP
    m.refusal_streaks.clear()
    for i in range(CFG["r5p3_refusal_keep"]):
        m.refusal_streaks[f"rule{i}:" + '{"kind": "workshops"}'] = {
            "n": 9, "why": "x" * 100, "sig": {"v": "0.105.60", "levels": 40, "wells": 3}, "at": 103000000 + i,
            "until": 104000000, "days": 28, "rule": f"rule{i}", "type": "start_project"}
    m.dead_told = [[100000 + i, 250 * 403200 + i] for i in range(600)]
    m.refusals.clear()
    sizes = memstore.sizes(m, TokenBank(), "AI Test Run#1234")
    print("    working:", sizes["working"], "of", memstore.BUDGETS["working"])
    assert not memstore.over_budget(m, TokenBank(), "AI Test Run#1234"), sizes


@test("config drift: r5p3_refusal_keep has one default (PLANNER_CONFIG's), used when cfg lacks it")
def _():
    assert CFG["r5p3_refusal_keep"] == 30
    book = {f"k{i}": {"n": 1, "at": 100 + i} for i in range(50)}
    rs._prune(book, 200, {})
    assert len(book) == PLANNER_CONFIG["r5p3_refusal_keep"], len(book)


finish()
