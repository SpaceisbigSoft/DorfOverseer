"""(group 2) The cavern well's shaft: shut only for a danger that could come
up it, by the bridge's own verdict (shaft_judge: watch_near on each linked
gate, watch_rule 2), kept shut for its hold (shut_hold), opened once the
danger has been away; short of water, a far danger that can't fly or climb
doesn't keep it shut (the bridge's `dry`). E and F (14 Nov): well_shaft 49
and 32 times, shut for demons in the underworld, 186 dead of thirst.

    python tests/test_g2_well_shaft.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
import planner_wells  # noqa: E402
import planner_threats  # noqa: E402
from planner import plan, Memory  # noqa: E402


def gate(**k):
    g = {"project_id": 9, "x": 120, "y": 121, "z": 156, "elevation": 26, "state": "none",
         "gate": "closed", "watching": True, "watch_rule": 2, "shut_hold": 0}
    g.update(k)
    return g


def state(*gates, wells=2, drink=900, patients=0, parched=0, zones=None):
    return {"settings": {"traits": {}}, "dwarves": {"total": 40, "needs_medical_care": patients},
            "society": {"parched": parched}, "stocks": {"drink": drink, "mechanisms": 5},
            "buildings": {"other": {"Well": wells}, "zones": zones or {}},
            "projects": {"open": [], "max_open": 2, "well_lids": list(gates)},
            "others_on_map": {}, "date": {"year": 5, "tick": 1000, "season": "spring"}}


def run(s):
    props, notes = [], []
    planner_wells._well_lid_rule(s, props, notes)
    return [p for p in props if p.rule == "well_shaft" and p.action.get("type") == "well_shaft"], notes


FLIER = {"id": 7, "name": "Seerjackals, Forgotten Beast", "d": 32, "reach": 95, "great": True, "flier": True,
         "mobile": True}
WALKER = {"id": 8, "name": "Cave Crocodile", "d": 50, "reach": 75, "great": True, "mobile": False}


@test("group 2: a shut gate with no danger and its hold run out is opened; the hold running, it isn't")
def _():
    p, notes = run(state(gate()))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    assert "no danger near" in p[0].reason
    p, notes = run(state(gate(shut_hold=400)))
    assert not p, [x.action for x in p]
    assert any("stays shut a while yet (400 ticks)" in n for n in notes), notes


@test("group 2: the bridge's verdict alone decides (the report's threat list doesn't shut a judged shaft)")
def _():
    s = state(gate(gate="open"))
    s["others_on_map"]["threats"] = [{"id": 5, "name": "Lizard Devil", "layer": "Cavern1",
                                      "pos": {"x": 125, "y": 120, "z": 140}}]
    p, _ = run(s)
    assert not p, [x.action for x in p]                    # the bridge saw nothing that could come up it
    s["projects"]["well_lids"][0]["watch_near"] = FLIER
    p, _ = run(s)
    # (item2) a flier great beast: the shaft kept shut for its layer too (keep_shut)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": True, "keep_shut": [9]}] and p[0].priority == 2
    assert "flies, 32 tiles from the shaft" in p[0].reason, p[0].reason


@test("group 2: shut for a danger near, water enough: kept shut and said (still a well)")
def _():
    p, notes = run(state(gate(watch_near=WALKER)))
    assert not p and any("still counted as a well" in n and "walks or swims" in n for n in notes), notes
    assert not any(n.startswith("[you]") for n in notes)
    # (item2) a flier great beast: the bridge told once to keep it shut (its watcher won't open it), then said
    p, notes = run(state(gate(watch_near=FLIER)))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [9]}], [x.action for x in p]
    assert "keep the shaft shut" in p[0].reason, p[0].reason
    p, notes = run(state(gate(watch_near=FLIER, layer_guard=True)))
    assert not p and any("kept shut" in n and "Seerjackals" in n for n in notes), notes


@test("group 2: short of water, a far danger that can't fly or climb: opened, the bridge told `dry`")
def _():
    s = state(gate(watch_near=WALKER), wells=1, patients=3)
    p, notes = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": True}], [x.action for x in p]
    assert p[0].priority == 2 and "3 injured need water" in p[0].reason and "can't fly or climb" in p[0].reason
    # the same walker near (within a walker's reach): kept shut, said
    s["projects"]["well_lids"][0]["watch_near"] = dict(WALKER, d=18)
    p, notes = run(s)
    assert not p and any("short of water" in n and "kept shut" in n for n in notes), notes
    # a flier, short of water: kept shut, said what the AI does meanwhile (no Needs you: the standing rule)
    s["projects"]["well_lids"][0]["watch_near"] = dict(WALKER, d=18, mobile=True, climber=True)
    p, notes = run(s)
    assert not p and any("kept shut, since it could come up the shaft" in n for n in notes), notes
    # (item2) a flier great beast, short of water: kept shut for its layer, said
    s["projects"]["well_lids"][0].update(watch_near=FLIER, layer_guard=True)
    p, notes = run(s)
    assert not p and any("kept shut" in n and "short of water" in n for n in notes), notes
    assert not any(n.startswith("[you]") for n in notes)


@test("group 2: short of water, the hold running: opened at once (dry)")
def _():
    p, _ = run(state(gate(shut_hold=900), wells=1, drink=10))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": True}], [x.action for x in p]


@test("group 2: `dry` taken back only once the fort has water again (no flapping with the open shaft)")
def _():
    s = state(gate(gate="open", watch_dry=True), wells=1, patients=2)
    p, _ = run(s)
    assert not p, [x.action for x in p]                    # still short: dry stays, nothing to do
    s["dwarves"]["needs_medical_care"] = 0
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": False}], [x.action for x in p]
    assert "water again" in p[0].reason
    # another well, or a water source zone: not short
    assert planner_wells.shaft_water_short(state(gate(), wells=2, patients=2), [gate()]) == ""
    assert planner_wells.shaft_water_short(state(gate(), wells=1, patients=2, zones={"WaterSource": 1}), [gate()]) == ""
    assert planner_wells.shaft_water_short(state(gate(), wells=1, parched=2), [gate()]) == "2 parched"


@test("group 2: a given-up shaft open is shut; one in the shaft itself always keeps it shut")
def _():
    p, _ = run(state(gate(gate="open", cancelled=True)))
    # (K48-K4b) close false: the bridge shuts a given-up shaft on any call; close true shut every working well too
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}] and "given-up" in p[0].reason
    near = {"id": 3, "name": "Troll", "d": 1, "in_shaft": True, "mobile": True}
    p, notes = run(state(gate(watch_near=near), wells=1, patients=4))
    assert not p and any("Troll (in the shaft)" in n for n in notes), notes


@test("group 2: the well rule counts a shaft shut for its hold as a well (no second cavern well)")
def _():
    s = state(gate(shut_hold=300), wells=1)
    assert planner_wells.shaft_judged(s["projects"]["well_lids"])
    props, notes = [], []
    m = Memory()
    m.well_failure = "no clean water inside the fort to channel a well over"
    planner_wells._well_rule(s, m, {}, __import__("planner").PLANNER_CONFIG, props, notes)
    assert not any(p.rule == "well" for p in props), [(p.rule, p.action) for p in props]


@test("group 2: the threats rule says the shaft is shut for a beast only when it is")
def _():
    src = (ROOT / "brain" / "planner_threats.py").read_text(encoding="utf-8")
    assert 'x.get("watch_rule") or 0) >= 2' in src


@test("group 2: plan() end to end: Lizard Devil 140 levels down (no verdict) doesn't keep a judged shaft shut")
def _():
    from test_planner import fort  # noqa: E402
    s = fort()
    s["others_on_map"]["threats"] = []
    s["projects"]["well_lids"] = [gate()]
    acts = [p.action for p in plan(s, Memory())[0] if p.rule == "well_shaft"]
    assert {"type": "well_shaft", "close": False} in acts, acts


# --- (item2) B, 24 Nov: a flier forgotten beast in the cavern layer the shafts open into

LAYERS = [{"name": "Cavern1", "z_top": 150, "z_bottom": 141, "discovered": True},
          {"name": "Cavern2", "z_top": 120, "z_bottom": 106, "discovered": True}]


def bgate(pid, x, z=110, **k):
    """A cavern well's linked gate, its shaft opening at level z (Cavern2 by default)."""
    return gate(project_id=pid, x=x, y=100, shaft_hatch={"x": x, "y": 100, "z": z}, **k)


def bstate(*gates, threats=(), unseen=(), **k):
    s = state(*gates, **k)
    s["map"] = {"layers": LAYERS}
    s["others_on_map"]["threats"] = list(threats)
    if unseen:
        s["deep"] = {"unseen": list(unseen)}
    return s


def paddle(x, destroyer=False, layer="Cavern2"):
    return {"id": 77, "name": "Paddlecrevice", "kinds": ["ForgottenBeast"], "great_danger": True, "flier": True,
            "destroyer": destroyer or None, "layer": layer, "pos": {"x": x, "y": 100, "z": 108}}


PADDLE_NEAR = dict(FLIER, name="Paddlecrevice", d=40)
LONELY = {"id": 78, "name": "Lonelyweird", "kind": "forgotten beast", "layer": "Cavern2", "flier": True}


@test("item2: the shaft into a layer is a shaft_layer by its hatch's level and the map's layers")
def _():
    from planner_shaft_guard import shaft_layer
    s = bstate()
    assert shaft_layer(s, bgate(1, 10, z=110)) == "Cavern2"
    assert shaft_layer(s, bgate(1, 10, z=121)) == "Cavern2"          # the opening right over the layer's top
    assert shaft_layer(s, bgate(1, 10, z=145)) == "Cavern1"
    assert shaft_layer(s, bgate(1, 10, z=130)) == ""
    assert shaft_layer(state(), bgate(1, 10)) == ""                  # no layers known


@test("item2: B 16:46-16:49: short of water, Paddlecrevice (flies) 40 tiles from shaft 128: neither 128 nor 63 opened")
def _():
    g128 = bgate(128, 100, watch_near=PADDLE_NEAR, shut_hold=900)
    g63 = bgate(63, 170, shut_hold=900)                               # 70 off: past the watcher's own reach
    s = bstate(g128, g63, threats=[paddle(60)], wells=2, patients=1)
    p, notes = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [63, 128]}], \
        [x.action for x in p]
    assert "open its shaft" not in p[0].reason and "open the" not in p[0].reason, p[0].reason
    assert "Paddlecrevice" in p[0].reason and "keep the shaft shut" in p[0].reason, p[0].reason
    assert any("x170" in n and "kept shut" in n and "short of water" in n for n in notes), notes
    # once the bridge holds them (layer_guard): nothing asked, no flapping
    for g in (g128, g63):
        g["layer_guard"] = True
    p, notes = run(s)
    assert not p, [(x.action, x.reason) for x in p]
    # the hold run out, water enough, no watcher verdict at all ("no danger near now"): still shut
    for g in (g128, g63):
        g.pop("watch_near", None)
        g["shut_hold"] = 0
    s = bstate(g128, g63, threats=[paddle(60)])
    p, notes = run(s)
    assert not p, [(x.action, x.reason) for x in p]


@test("item2: a flier beast in the layer: within 60 tiles of any shaft into it, all kept; a destroyer anywhere in it")
def _():
    a, b = bgate(1, 100), bgate(2, 300)
    p, _ = run(bstate(a, b, threats=[paddle(150)]))                   # 50 from a, 150 from b: both kept
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1, 2]}], [x.action for x in p]
    p, _ = run(bstate(bgate(1, 100), bgate(2, 300), threats=[paddle(200)]))   # 100 from each: opened
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    assert "no danger near" in p[0].reason
    p, _ = run(bstate(bgate(1, 100), bgate(2, 300), threats=[paddle(200, destroyer=True)]))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1, 2]}], [x.action for x in p]
    assert "breaks buildings" in p[0].reason, p[0].reason
    # in another layer: not these shafts'
    p, _ = run(bstate(bgate(1, 100), threats=[paddle(100, destroyer=True, layer="Cavern1")]))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    # a great walker in the layer: the watcher's per-shaft distance alone
    walker = dict(paddle(110), flier=False)
    p, _ = run(bstate(bgate(1, 100), threats=[walker]))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]


@test("item2: an open shaft into a layer with a flier beast is shut at once, said with the layer")
def _():
    p, _ = run(bstate(bgate(1, 100, gate="open"), bgate(2, 140, z=145, gate="open"), threats=[paddle(150)]))
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1]}], [x.action for x in p]
    assert "Cavern2" in p[0].reason and "shut the shaft" in p[0].reason and p[0].priority == 2, p[0].reason


@test("item2: an unseen great beast in the layer keeps its shafts shut (it can't be seen to be near); other layers open")
def _():
    s = bstate(bgate(1, 100), bgate(2, 140, z=145), unseen=[LONELY])
    p, notes = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1]}], [x.action for x in p]
    assert "no danger near" in p[0].reason and "Lonelyweird" in p[0].reason and "kept shut" in p[0].reason, p[0].reason
    assert any("Lonelyweird" in n and "unseen" in n for n in notes), notes
    # one held in a lure pocket: no longer counted
    s["lures"] = {"held_beasts": [78]}
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    # the shaft's layer unknown (no map layers): an unseen great beast in any cavern keeps it shut
    s = bstate(bgate(1, 100), unseen=[LONELY])
    s["map"] = {}
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1]}], [x.action for x in p]


BONE = {"id": 16495, "name": "Bonephantom", "kind": "forgotten beast", "layer": "Cavern2"}


@test("merge 0.105.111: an unseen walker that can't reach the dwarves keeps no shaft shut; one that can does")
def _():
    s = bstate(bgate(1, 100), unseen=[BONE])
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False}], [x.action for x in p]
    s = bstate(bgate(1, 100), unseen=[dict(BONE, can_reach_dwarves=True)])
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1]}], [x.action for x in p]


THIRSTY = {"id": 501, "name": "Urist", "timer": 61000, "level": "dehydrated", "reason": "injured"}


@test("item2: dying of thirst with no other water: the guarded shaft farthest from the beast opened, and said")
def _():
    g1, g2 = bgate(1, 100, shut_hold=900), bgate(2, 160, shut_hold=900)
    s = bstate(g1, g2, threats=[paddle(80)], wells=2, patients=1)
    p, _ = run(s)                                                     # short, nobody dying: both kept
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1, 2]}], [x.action for x in p]
    s["thirst"] = {"list": [THIRSTY]}
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": True, "keep_shut": [1]}], \
        [x.action for x in p]
    assert "farthest from Paddlecrevice" in p[0].reason and "80 tiles from it" in p[0].reason, p[0].reason
    assert "Urist" in p[0].reason and p[0].priority == 2
    # opened: the same one stays the spare (not shut again next turn)
    g2["gate"] = "open"
    p, _ = run(s)
    assert not p or all(2 not in x.action.get("keep_shut", []) and not x.action.get("close") for x in p), \
        [x.action for x in p]
    # a dehydrated dwarf who can drink booze (reason "unknown"): no shaft opened
    g2["gate"] = "closed"
    s["thirst"] = {"list": [dict(THIRSTY, reason="unknown")]}
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "keep_shut": [1, 2]}], [x.action for x in p]
    # a shaft into another layer gives water: no guarded shaft opened
    s["thirst"] = {"list": [THIRSTY]}
    s["projects"]["well_lids"].append(bgate(3, 100, z=145, shut_hold=900))
    s["buildings"]["other"]["Well"] = 3
    p, _ = run(s)
    assert [x.action for x in p] == [{"type": "well_shaft", "close": False, "dry": True, "keep_shut": [1, 2]}], \
        [x.action for x in p]


@test("item2: the bridge's side: keep_shut passed, kept shut gates marked so the watcher leaves them, reported")
def _():
    act = (ROOT / "lua" / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    assert "well_shaft_step(a.close == true, a.dry_run == true, dry, keep)" in act
    sh = (ROOT / "lua" / "ai-builder-wells-shaft.lua").read_text(encoding="utf-8")
    assert "function well_shaft_step(want_closed, dry_run, dry, keep)" in sh
    assert "or p.phase == 'cancelled' or guarded" in sh and "sg.layer_guard" in sh
    wt = (ROOT / "lua" / "ai-builder-wells-watch.lua").read_text(encoding="utf-8")
    assert "r.layer_guard = true" in wt
    # the watcher opens only what it shut for a danger (auto_shut), never a brain_shut gate
    assert "sg.auto_shut and w.p.phase ~= 'cancelled'" in wt and "not sg.brain_shut" in wt
    from overseer_words import short
    assert "kept shut for a great beast" in short({"type": "well_shaft", "close": False, "keep_shut": [1]})


if __name__ == "__main__":
    finish()
