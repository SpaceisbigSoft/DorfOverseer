"""(item7) The great dangers below the fort hasn't seen yet (B, 24 Nov: three
forgotten beasts in the caverns, all on tiles not yet revealed, so `deep`
dangers was empty and the seal rule saw none).

  * the bridge sends them apart (deep.unseen), never among the seen dangers;
  * one that can walk to the dwarves is sealed out as a seen one is (no kill
    plan for it);
  * any of them keeps the ways down locked ("no beast left" not said);
  * the rest said in a note; B's own case (nothing joins, the well's gate)
    asks nothing of the bridge.

    python tests/test_item7_unseen.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402
import planner  # noqa: E402,F401
import planner_threats as pt  # noqa: E402
import planner_unseen as pu  # noqa: E402
from planner_core import Memory  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = dict(pt.PLANNER_CONFIG)
LUA = ROOT / "lua"

# B, 24 Nov 22:32 (probe i7-fb): Cavern1 z 123-146 (no tile in the citizens' walk group)
CAVERNS = [{"discovered": True, "name": "Cavern1", "open": False, "seen": 2504, "z_bottom": 123, "z_top": 146},
           {"discovered": False, "name": "Cavern2", "open": False, "seen": 0, "z_bottom": 114, "z_top": 118}]
WELL_HATCH = {"building": "Hatch", "built": True, "closed": False, "id": 248, "kind": "well", "lockable": False,
              "locked": False, "source": "cavern well 25", "x": 131, "y": 129, "z": 143}
WELL_DOOR = {"building": "Door", "built": True, "closed": True, "id": 1785, "kind": "gate", "lockable": False,
             "locked": False, "seal_skip": "cavern well 25: its shaft gate keeps the cavern out (open); the door "
                                           "would cut the well off", "source": "cavern well 25 door",
             "x": 117, "y": 142, "z": 165}
BONEPHANTOM = {"id": 16495, "name": 'Siga Sutwarosp Galka Oce "Bonephantom the Deeps of Dust", Forgotten Beast',
               "kind": "forgotten beast", "layer": "Cavern1"}
PADDLECREVICE = {"id": 16704, "name": 'Arstruk Dakësru Gozru "Paddlecrevice the Hellish", Forgotten Beast',
                 "kind": "forgotten beast", "layer": "Cavern2", "flier": True}


def fort(unseen=(), dangers=(), sealed=None, openings=(WELL_HATCH, WELL_DOOR)):
    s = copy.deepcopy(BASE)
    s["map"]["elevation_offset"] = -129
    s["threats"] = {"sealed": dict(sealed or {}), "openings": {"list": [dict(o) for o in openings],
                                                              "n": len(openings)},
                    "cavern_citizens": {"list": [], "n": 0}}
    s["deep"] = {"caverns": copy.deepcopy(CAVERNS), "dangers": [dict(x) for x in dangers], "cursed": [],
                 "unseen": [dict(x) for x in unseen]}
    s["civ_alert"], s["civ_alert_ready"] = False, True
    return s


def run(s, m=None):
    props, notes = [], []
    pt._cavern_beasts(s, CFG, m or Memory(), s["threats"], pt.threat_rules_of(s), props, notes)
    return props, notes


def seals(props):
    return [p for p in props if p.rule == "seal_cavern"]


@test("B (22:32): three unseen beasts, none can walk to the dwarves, only the well's gate: a note, nothing asked")
def _():
    s = fort(unseen=[BONEPHANTOM, PADDLECREVICE])
    props, notes = run(s)
    assert not seals(props) and not [p for p in props if p.rule in ("threat_alert", "beast_hunt")], \
        [(p.rule, p.action) for p in props]
    n = [x for x in notes if "not yet seen" in x]
    assert n and "Bonephantom" in n[0] and "flies, Cavern2" in n[0] and "none can walk to the dwarves" in n[0], notes


@test("a seal on and the beasts gone out of sight: kept locked, not opened 'no forgotten beast left'")
def _():
    s = fort(unseen=[BONEPHANTOM], sealed={pt.ALL_CAVERNS: {"days": 3}})
    props, notes = run(s)
    assert not [p for p in seals(props) if p.action.get("open")], [(p.rule, p.action) for p in props]
    assert any("stay locked while they live" in x for x in notes), notes
    # none left, seen or not: opened as before
    s = fort(sealed={pt.ALL_CAVERNS: {"days": 3}})
    assert [p for p in seals(run(s)[0]) if p.action.get("open")]
    # an old per-layer seal: kept while an unseen beast is in that layer
    s = fort(unseen=[BONEPHANTOM], sealed={"Cavern1": {"days": 3}})
    assert not [p for p in seals(run(s)[0]) if p.action.get("open")]


@test("an unseen beast that can walk to the dwarves is sealed out as a seen one is (a lockable door on the way)")
def _():
    door = dict(WELL_DOOR, lockable=True, seal_skip=None, source="cavern entrance 4")
    walker = dict(BONEPHANTOM, can_reach_dwarves=True)
    props, notes = run(fort(unseen=[walker], openings=[WELL_HATCH, door]))
    p = seals(props)
    assert p and p[0].action.get("layer") == pt.ALL_CAVERNS and not p[0].action.get("open"), \
        [(x.rule, x.action) for x in props]
    assert "not yet seen" in p[0].reason, p[0].reason
    assert not [x for x in props if x.rule == "beast_hunt"]
    # one that can't: nothing locked for it
    assert not seals(run(fort(unseen=[BONEPHANTOM], openings=[WELL_HATCH, door]))[0])


@test("unseen_great: great kinds only, a lure's held beast left out, a forgotten beast anywhere")
def _():
    s = fort(unseen=[BONEPHANTOM, dict(id=7, kind="night creature", layer="Cavern1"),
                     dict(id=8, kind="forgotten beast", layer="upper_levels"), dict(id=9, kind="titan")])
    s["lures"] = {"held_beasts": [16495]}
    assert [x["id"] for x in pu.unseen_great(s)] == [8], pu.unseen_great(s)
    assert pu.unseen_great({}) == [] and pu.unseen_great({"deep": {"unseen": "x"}}) == []


@test("the bridge: a hidden great danger goes to deep.unseen, never among the seen dangers")
def _():
    src = (LUA / "ai-bridge-report-world.lua").read_text(encoding="utf-8")
    i = src.index("function get_deep()")
    body = src[i:src.index("\nend\n", i)]
    j = body.index("elseif not dfhack.units.isHidden(u) then")
    k = body.index("out.unseen = out.unseen or {}")
    assert j < k and "table.insert(out.dangers" in body[j:k] and "table.insert(out.dangers" not in body[k:]
    assert "can_reach_dwarves = (g ~= 0) and (groups[g] == true) or nil" in body[k:]
    assert len(src.encode()) + src.count("\n") < 59900


if __name__ == "__main__":
    finish()
