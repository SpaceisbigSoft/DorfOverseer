"""(0.105.113 item11) Fort C's crossbows: quivers and bolts.

C (Merchant city, 25 Nov 07:20): one crossbow squad (208) of 10 at its range,
10 wooden crossbows, `quivers_assigned` 5 of 10 `ranged_places`,
`quivers_free` 0 while 12 spare quivers lay about (9 loose, 3 in bins: on
neither of DF's equipment lists, probe i11_quivers), `supplies.quivers` 9
and `quivers_worn` 8 (5 of them the soldiers', the rest a hunter's or such),
so the ranged squad rule read plenty and made none; ~110 orders of iron bolts
in 12 hours (journal rule `arms`) while 19 melee places waited for a weapon.

Fixed: the quivers short counted from the places (planner_military_squads
_ranged_squad_rule); a quiver on neither list is free (lua/ai-military-gear-ammo
free_quivers, test_military); wooden bolts first while soldiers lack weapons.

    python tests/test_i113_crossbows.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

from planner import PLANNER_CONFIG as CFG  # noqa: E402
from planner_military_squads import _ranged_squad_rule  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TEMPLATES = ["Melee, leather armor", "Melee, metal armor", "Crossbows, leather armor", "Crossbows, metal armor"]
MELEE = {"id": 185, "members": 10, "size": 10, "leader": True, "uniform": True, "ai_uniform": "Melee, metal armor"}
XBOW = {"id": 208, "members": 10, "size": 10, "leader": True, "uniform": True, "ai_uniform": "Crossbows, metal armor",
        "ammo": {"assigned": 5, "items": 5, "specs": 1, "units": 125, "wanted": 500}}


def c_fort(**gear):
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"] = dict(s["buildings"].get("workshops") or {}, Bowyers=1, Leatherworks=1,
                                       MetalsmithsForge=3)
    s["stocks"] = dict(s.get("stocks") or {}, wood=325, leather=18)
    s["supplies"] = dict(s.get("supplies") or {}, quivers=9, quivers_worn=8)
    g = {"soldiers": 69, "armed": 27, "ranged_armed": 10, "spare_crossbows": 0, "crossbows_total": 10,
         "bolts": 150, "ranged_places": 10, "quivers_assigned": 5, "quivers_free": 0, "weapon_gaps": 19,
         "bars": {"IRON": 63}, "forges": 3}
    g.update(gear)
    s["military"] = dict(s.get("military") or {}, gear=g, squads=[dict(MELEE), dict(XBOW)],
                         uniform_templates=list(TEMPLATES))
    return s, g


def run(s, g):
    props = []
    sq = s["military"]["squads"]
    _ranged_squad_rule(s, g, sq, TEMPLATES, CFG, props, [185, 208], False, None, {})
    return props


def orders(props, recipe):
    return [p for p in props if p.action.get("type") == "work_order" and p.action.get("recipe") == recipe]


@test("C: 5 of 10 crossbow places without a quiver, none free: leather quivers made (spare/worn counts ignored)")
def _():
    s, g = c_fort()
    q = orders(run(s, g), "leather_quiver")
    assert q and q[0].action["amount"] == min(5, CFG["max_quiver_order"]), [p.action for p in q]
    assert "10 crossbow places, 5 with a quiver and 0 free" in q[0].reason, q[0].reason


@test("free quivers (the bridge hands them out) or every place filled: none made")
def _():
    s, g = c_fort(quivers_free=5)
    assert not orders(run(s, g), "leather_quiver")
    s, g = c_fort(quivers_assigned=10)
    assert not orders(run(s, g), "leather_quiver")


@test("an older bridge without the places: the spare and worn counts as before")
def _():
    s, g = c_fort()
    del g["ranged_places"], g["quivers_assigned"]
    assert not orders(run(s, g), "leather_quiver")          # 10 - 9 - 8 < 0
    s["supplies"].update(quivers=1, quivers_worn=2)
    assert orders(run(s, g), "leather_quiver")


@test("C: soldiers waiting for weapons and a bowyer with wood: wooden bolts, not iron")
def _():
    s, g = c_fort()
    p = run(s, g)
    assert orders(p, "wooden_bolts") and not orders(p, "metal_bolts"), [x.action for x in p]


@test("every soldier armed: metal bolts at the forge as before; no wood: metal even with gaps")
def _():
    s, g = c_fort(weapon_gaps=0, armed=69)
    p = run(s, g)
    assert orders(p, "metal_bolts") and not orders(p, "wooden_bolts"), [x.action for x in p]
    s, g = c_fort()
    s["stocks"]["wood"] = 3
    p = run(s, g)
    assert orders(p, "metal_bolts"), [x.action for x in p]


if __name__ == "__main__":
    finish()
