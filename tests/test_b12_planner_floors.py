"""(layout B, group B12) The floor hint on every new level, at send time.

brain/planner_floors.py floor_action puts masterplan_floors.hint's answer on
the start_project the overseer sends (after shop_level_action), and
floor_outcome / not_on_floor_words give the outcome line its words for a
level that went onto a floor, or did not. masterplan_floors is group B11's
module: these tests bring a stand-in (and hide the real one where "no such
module" is the case under test), so they pass with or without it.

    python tests/test_b12_planner_floors.py
"""

from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import finish, make_test  # noqa: E402
from py_parts import py_family_src  # noqa: E402  (r7) overseer.py and its parts
sys.path.insert(0, str(ROOT / "brain"))

import overseer  # noqa: E402
import planner  # noqa: E402
import planner_floors as PF  # noqa: E402
from planner_config import PLANNER_CONFIG  # noqa: E402
import test_overseer as T  # noqa: E402   (its fakes and its reset; its tests don't run here)

HINT = {"elevs": [12, 11, 13], "tag": "homes", "zone": "near", "spine": {"x": 96, "y": 101},
        "dirs": ["east", "south"], "gap": 1, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 30,
        "run_min": 10, "arms_max": 2, "sides": "both", "stagger": 0, "bay": 0, "node": 3,
        "grow": ["arm", "turn"], "turns": "alternate", "balance": False, "axial": False, "neck": False,
        "pile_w": 5, "piles_new": 1, "full_retry_days": 28}
CALLS: list[tuple] = []          # what the stand-in's hint was called with
_RECORD = overseer.record


def stand_in(answer=None, error=None):
    """A masterplan_floors whose hint answers `answer` (a value, or a function
    of the action), or raises `error`."""
    m = types.ModuleType("masterplan_floors")

    def hint(memory, action, s, traits, cfg):
        CALLS.append((memory, copy.deepcopy(action), s, traits, cfg))
        if error:
            raise error
        return answer(action) if callable(answer) else answer
    m.hint = hint
    sys.modules["masterplan_floors"] = m
    return m


def no_module():
    """As in a copy without group B11's module: the import fails."""
    sys.modules["masterplan_floors"] = None


def _before():
    T._before()
    CALLS.clear()
    overseer.record = _RECORD
    no_module()


test = make_test(before=_before)
LEVEL = {"type": "start_project", "kind": "bedrooms", "rooms": 8, "style": {"hall": "plain"},
         "plan": {"elev_lo": 9, "elev_hi": 12}}


def fort(**settings):
    s = copy.deepcopy(T.BASE)
    s["settings"].update(settings)
    return s


# --- floor_action ---------------------------------------------------------------------

@test("floor_action: a level gets the hint (a copy; the proposal's action is not changed)")
def _():
    stand_in(HINT)
    a, s, mem = copy.deepcopy(LEVEL), fort(), object()
    before = copy.deepcopy(a)
    b = PF.floor_action(a, s, mem)
    assert b is not a and a == before, a
    assert b["floor"] == HINT and {k: v for k, v in b.items() if k != "floor"} == before, b
    assert len(CALLS) == 1
    memory, action, st, traits, cfg = CALLS[0]
    assert memory is mem and action == before and st is s and cfg is PLANNER_CONFIG
    assert traits == s["settings"].get("traits", {}) and isinstance(traits, dict), traits
    own = {"floor_gap": 2}
    PF.floor_action(a, s, mem, own)
    assert CALLS[1][4] is own
    # a fort that says "hallway", and one whose settings have no such key (every running fort)
    assert PF.floor_action(a, fort(floor_layout="hallway"), mem)["floor"] == HINT
    assert "floor_layout" not in s["settings"]


@test("floor_action: False (classic on purpose) is passed on; None, True and junk leave no floor key")
def _():
    a = copy.deepcopy(LEVEL)
    stand_in(False)
    b = PF.floor_action(a, fort(), None)
    assert b is not a and b["floor"] is False and "floor" not in a
    for junk in (None, True, 0, 1, "east", [1, 2], ("a",)):
        stand_in(junk)
        assert PF.floor_action(a, fort(), None) is a, junk
    assert a == LEVEL


@test("floor_action: a raising hint, a broken module and a broken fort leave the action as it is")
def _():
    a = copy.deepcopy(LEVEL)
    for err in (RuntimeError("boom"), KeyError("plan"), RecursionError(), ZeroDivisionError()):
        stand_in(error=err)
        assert PF.floor_action(a, fort(), None) is a, err
        assert CALLS, "the stand-in was not asked"
    sys.modules["masterplan_floors"] = types.ModuleType("masterplan_floors")      # no hint in it
    assert PF.floor_action(a, fort(), None) is a
    stand_in(HINT)
    for s in (None, {}, [], "x", {"settings": None}, {"settings": []}, {"settings": {"traits": "x"}}):
        b = PF.floor_action(a, s, None)                  # no settings: not classic, no sliders
        assert b["floor"] == HINT and CALLS[-1][3] == {} and isinstance(CALLS[-1][2], dict), s
    assert PF.floor_action(a, fort(), None, None)["floor"] == HINT and CALLS[-1][4] is PLANNER_CONFIG
    assert a == LEVEL


@test("floor_action: any other action, a non-dict, a level with a floor key, a fort at classic: the same object, unasked")
def _():
    stand_in(HINT)
    same = [{"type": "work_order", "job": "brew_drink", "amount": 5},
            {"type": "extend_project", "kind": "bedrooms", "id": 3},
            {"kind": "bedrooms"},                                     # no type
            {"type": "start_project"},                                # no kind
            {"type": "start_project", "kind": None},
            {"type": "start_project", "kind": 7},
            dict(LEVEL, floor=False),                                 # a rule that keeps its own place
            dict(LEVEL, floor=None),
            dict(LEVEL, floor={"elevs": [3]}),
            None, "start_project", 5, ["start_project"], ()]
    for a in same:
        keep = copy.deepcopy(a)
        assert PF.floor_action(a, fort(), None) is a and a == keep, a
    a = copy.deepcopy(LEVEL)
    assert PF.floor_action(a, fort(floor_layout="classic"), None) is a and a == LEVEL
    assert not CALLS, CALLS


@test("floor_action: with no masterplan_floors importable the action comes back untouched, nothing raises")
def _():
    no_module()
    a = copy.deepcopy(LEVEL)
    assert PF.floor_action(a, fort(), None) is a and a == LEVEL
    sys.modules.pop("masterplan_floors", None)           # not even a marker: the import looks on disk
    if not (ROOT / "brain" / "masterplan_floors.py").exists():
        assert PF.floor_action(a, fort(), None) is a and a == LEVEL
    else:                                                # after the merge: the real module, still no raise
        b = PF.floor_action(a, fort(), overseer.Memory())
        assert b is a or (isinstance(b, dict) and (b["floor"] is False or isinstance(b["floor"], dict))), b
        sys.modules.pop("masterplan_floors", None)
    assert a == LEVEL
    src = (ROOT / "brain" / "planner_floors.py").read_text(encoding="utf-8")
    top = src[:src.index("def floor_action")]
    assert "import masterplan_floors" not in top, "the import belongs inside floor_action's try"


# --- the outcome words ------------------------------------------------------------------

ANSWER = {"ok": True, "project_id": 57, "kind": "bedrooms", "z": 152, "elevation": 12, "corridor": 0,
          "floor": {"id": 3, "elevation": 12, "stair": {"x": 96, "y": 101}, "arm": "east", "side": "north",
                    "u": 13, "hall_new": 39, "new_floor": False, "piles": [], "units": 2}}


def answer(**floor):
    r = copy.deepcopy(ANSWER)
    r["floor"].update(floor)
    return r


@test("floor_outcome: the floor, its elevation, the hall and the new hall; a new floor said")
def _():
    assert PF.floor_outcome(ANSWER) == "done: on floor #3 (elevation 12), along the east hall, 39 tiles of new hall"
    assert PF.floor_outcome(answer(new_floor=True)) == \
        "done: on floor #3 (elevation 12), along the east hall, 39 tiles of new hall, a new floor"
    assert PF.floor_outcome(answer(hall_new=1, arm="south")) == \
        "done: on floor #3 (elevation 12), along the south hall, 1 tile of new hall"
    assert PF.floor_outcome(answer(hall_new=0)) == "done: on floor #3 (elevation 12), along the east hall, no new hall"
    assert PF.floor_outcome(answer(id=3.0, elevation=-4.0, hall_new=6.0)) == \
        "done: on floor #3 (elevation -4), along the east hall, 6 tiles of new hall"       # Lua's numbers
    # a thin answer still reads; the level's own elevation stands in for the floor's
    assert PF.floor_outcome({"ok": True, "elevation": 7, "floor": {}}) == "done: on a floor (elevation 7)"
    assert PF.floor_outcome({"ok": True, "floor": {"id": "x", "arm": 5, "hall_new": "many", "new_floor": 1}}) == \
        "done: on a floor"
    for r in (None, 5, {}, {"floor": None}, {"floor": False}, {"floor": True}, {"floor": [3]}, {"floor": "3"}):
        assert PF.floor_outcome(r) is None, r


@test("not_on_floor_words: the reasons, 120 characters at most; nothing without them")
def _():
    why = "floor 3: no room; floor 4: refused: aquifer at x101 y96 z11"
    assert PF.not_on_floor_words({"ok": True, "not_on_floor": why}) == f" (not on a floor: {why})"
    long = "floor 3: no room; " * 20
    w = PF.not_on_floor_words({"not_on_floor": long})
    inner = w[len(" (not on a floor: "):-1]
    assert len(long) == 360 and 110 <= len(inner) <= 120 and inner.endswith("...") and long.startswith(inner[:-3]), w
    cut = "y" * 400
    assert PF.not_on_floor_words({"not_on_floor": cut}) == " (not on a floor: " + "y" * 117 + "...)"
    exact = "x" * 120
    assert PF.not_on_floor_words({"not_on_floor": exact}) == f" (not on a floor: {exact})"
    assert PF.not_on_floor_words({"not_on_floor": "a\n  b\tc "}) == " (not on a floor: a b c)"
    for r in (None, 5, {}, {"not_on_floor": None}, {"not_on_floor": ""}, {"not_on_floor": "  "},
              {"not_on_floor": True}, {"not_on_floor": ["x"]}, {"not_on_floor": {"a": 1}}):
        assert PF.not_on_floor_words(r) == "", r


# --- one overseer cycle -------------------------------------------------------------------

class FloorBridge(T.FakeBridge):
    """A game that answers a start_project with `reply` (merged over ok)."""

    def __init__(self, reply=None, **kw):
        super().__init__(**kw)
        self.reply = reply

    def act(self, action):
        r = super().act(action)
        if action["type"] == "start_project" and self.reply is not None:
            return copy.deepcopy(self.reply)
        return r


def young(reply=None, **settings):
    """T.young(): too few beds, so the planner wants a bedrooms level."""
    b = FloorBridge(reply)
    st = b._state
    st["mandates"] = []
    st["buildings"]["other"]["Bed"] = 20
    st["settings"]["mode"] = "autopilot"
    st["settings"].update(settings)
    return b


def cycle(b, backend=None):
    recorded = []

    def rec(results, *a, **kw):
        recorded.extend(copy.deepcopy(results))
        return _RECORD(results, *a, **kw)
    overseer.record = rec
    try:
        overseer.one_cycle(b, autopilot=True, controls=b.status(), **({"backend": backend} if backend else {}))
    finally:
        overseer.record = _RECORD
    sent = [a for a in b.acted if a["type"] == "start_project"]
    lines = [x for x in T.SAID if '"start_project"' in x and " -> " in x]
    journal = [e for e in T.entries("decision") if e["action"]["type"] == "start_project"]
    return sent, lines, journal, [(p, r) for p, r in recorded if p.action["type"] == "start_project"]


def words(line):
    return line[line.rindex(" [") + 2:-1]


@test("a cycle: the bridge gets the level with its floor; the journal, record and the said line keep the proposal's own action")
def _():
    stand_in(lambda a: dict(HINT, tag=a["kind"]))
    b = young(ANSWER)
    sent, lines, journal, recorded = cycle(b)
    assert len(sent) == 1 and sent[0]["kind"] == "bedrooms" and sent[0]["floor"] == dict(HINT, tag="bedrooms"), sent
    own = {k: v for k, v in sent[0].items() if k != "floor"}
    assert len(journal) == 1 and journal[0]["action"] == own and "floor" not in journal[0]["action"], journal
    assert journal[0]["result"]["floor"]["id"] == 3                  # the answer is journaled whole
    assert len(recorded) == 1 and recorded[0][0].action == own and recorded[0][1]["floor"]["id"] == 3
    assert len(lines) == 1 and json.dumps(own) in lines[0] and '"floor"' not in lines[0][:lines[0].rindex(" [")]
    assert words(lines[0]) == "done: on floor #3 (elevation 12), along the east hall, 39 tiles of new hall", lines
    # the hint was asked with the proposal's action, the cycle's state and its memory
    memory, action, st, traits, cfg = CALLS[-1]
    assert action == own and isinstance(memory, overseer.Memory) and st["fort"] == b._state["fort"]
    assert traits == st["settings"].get("traits", {}) and isinstance(cfg, dict) and "floor" not in action


@test("a cycle: the outcome words for a new floor, for not_on_floor, for a join, and for a plain answer")
def _():
    stand_in(HINT)
    why = "floor 3: no room; floor 4: refused: aquifer at x101 y96 z11"
    cases = [
        (answer(new_floor=True),
         "done: on floor #3 (elevation 12), along the east hall, 39 tiles of new hall, a new floor"),
        ({"ok": True, "project_id": 58, "kind": "bedrooms", "not_on_floor": why}, f"done (not on a floor: {why})"),
        ({"ok": True, "project_id": 58, "not_on_floor": "floor 3: no room; " * 20},
         "done (not on a floor: " + ("floor 3: no room; " * 20)[:117].rstrip() + "...)"),
        ({"ok": True, "project_id": 4, "joined": 4, "how": "free_room"}, "done: into workshops level #4 (a free room)"),
        ({"ok": True, "project_id": 4, "joined": 4, "how": "extended", "not_on_floor": why},
         f"done: into workshops level #4 (the level extended) (not on a floor: {why})"),
        # a join wins over a floor (the annex comes first in the builder); felling first, too
        (dict(answer(), joined=4, how="free_room"), "done: into workshops level #4 (a free room)"),
        ({"ok": True, "clearing": True, "trees": 2, "x": 5, "y": 6, "floor": ANSWER["floor"]},
         "started: 2 tree(s) at x5 y6 marked for felling first; placed once they're down"),
        ({"ok": False, "error": "no site", "not_on_floor": why}, f"refused: no site (not on a floor: {why})"),
        ({"ok": False, "error": "no site", "floor": ANSWER["floor"]}, "refused: no site"),
        ({"ok": True, "project_id": 9}, "done"),
        (None, "done"),                                    # the fake's own plain answer
    ]
    for reply, want in cases:
        _before()
        stand_in(HINT)
        sent, lines, journal, _ = cycle(young(reply))
        assert len(sent) == 1 and len(lines) == 1, (reply, sent, lines)
        assert words(lines[0]) == want, (words(lines[0]), want)


@test("a cycle: not_on_floor is said for a level only (another action's answer is left alone)")
def _():
    stand_in(HINT)

    class B(FloorBridge):
        def act(self, action):
            r = super().act(action)
            return dict(r, not_on_floor="x", floor={"id": 1}) if action["type"] == "work_order" else r
    b = B()
    b._state["mandates"] = []
    b._state["stocks"]["drink"] = 10
    b._state["settings"]["mode"] = "autopilot"
    overseer.one_cycle(b, autopilot=True, controls=b.status())
    said = [x for x in T.SAID if '"work_order"' in x and " -> " in x]
    assert said and all(words(x) == "done" for x in said), said


@test("a cycle with the fort at classic, with a hint of None, with a raising hint, with no module: the level goes out without a floor")
def _():
    for setup, settings in ((lambda: stand_in(HINT), {"floor_layout": "classic"}),
                            (lambda: stand_in(None), {}),
                            (lambda: stand_in(error=RuntimeError("boom")), {}),
                            (no_module, {})):
        _before()
        setup()
        sent, lines, journal, recorded = cycle(young(None, **settings))
        assert len(sent) == 1 and "floor" not in sent[0], sent
        assert journal[0]["action"] == sent[0] == recorded[0][0].action and words(lines[0]) == "done"
    _before()
    stand_in(False)
    sent, _, journal, _ = cycle(young())
    assert sent[0]["floor"] is False and "floor" not in journal[0]["action"], sent


@test("the strategist's level (a workshops level): sent with the floor hint and shop_level_action's keys; journaled as proposed")
def _():
    stand_in(lambda a: dict(HINT, tag="industry", group="crafts"))
    b = FloorBridge(dict(answer(piles=["stone"]), kind="workshops"))
    b._state["mandates"] = []
    b.version = dict(T.FakeBridge.version, level_kinds=["workshops", "bedrooms"],
                     workshops=["Masons", "Carpenters"], stockpiles=[])
    c = T.FakeClaude(answer='{"note":"more masonry","actions":[{"type":"start_project","kind":"workshops",'
                            '"shops":["Masons"]}]}')
    sent, lines, journal, recorded = cycle(b, backend=c)
    assert len(c.calls) == 1 and len(sent) == 1, (len(c.calls), sent, T.SAID)
    a = sent[0]
    assert a["kind"] == "workshops" and a["shops"] == ["Masons"]
    assert a["floor"] == dict(HINT, tag="industry", group="crafts"), a
    assert isinstance(a.get("spare"), int) and isinstance(a.get("spare_for"), list), a      # shop_level_action's
    own = {k: v for k, v in a.items() if k not in ("floor", "spare", "spare_for")}
    assert "style" in own                                           # review.py's own additions are the proposal's
    assert journal[0]["action"] == own == recorded[0][0].action, (journal[0]["action"], own)
    assert journal[0]["reason"].startswith("strategist:") and journal[0]["rule"] == "build"
    # the hint is asked with the action as shop_level_action left it (the level the builder gets)
    assert CALLS[-1][1] == {k: v for k, v in a.items() if k != "floor"}, CALLS[-1][1]
    assert words(lines[0]) == "done: on floor #3 (elevation 12), along the east hall, 39 tiles of new hall"


# --- what did not change ---------------------------------------------------------------------

@test("plan() is untouched: no proposal on the test fort carries a floor, with a hint to be had or not")
def _():
    import digest
    outs = []
    for setup in (no_module, lambda: stand_in(HINT)):
        setup()
        CALLS.clear()
        s = digest.normalize(copy.deepcopy(T.BASE))
        s["buildings"]["other"]["Bed"] = 20
        props, _notes = planner.plan(s, planner.Memory())
        levels = [p.action for p in props if p.action.get("type") == "start_project"]
        assert levels and not any("floor" in a for a in levels), levels
        assert not CALLS, "plan() asked for a floor hint"
        outs.append([(p.rule, p.action) for p in props])
    assert outs[0] == outs[1]
    from py_parts import py_family_src
    assert "planner_floors" not in py_family_src("planner")     # (r7 d2) planner.py and its parts


@test("the overseer: floor_action wraps shop_level_action at the one send; p.action goes on as proposed")
def _():
    src = py_family_src("overseer")
    assert "r = bridge.act(floor_action(shop_level_action(p.action, state), state, memory))" in src
    assert "from planner_floors import floor_action" in src
    code = [x for x in src.splitlines() if not x.lstrip().startswith("#")]
    assert sum("bridge.act(floor_action(" in x for x in code) == 1
    assert not any("bridge.act(shop_level_action(" in x for x in code), "a send without the floor hint"
    assert sum("floor_action(" in x for x in code) == 1          # nowhere else: the journal and record keep p.action


if __name__ == "__main__":
    finish()
