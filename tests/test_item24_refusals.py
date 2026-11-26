"""(R30c item24) Refusals that repeated for 3 hours in W1 (25 Nov 19:21-22:24,
bridge 0.105.121): each rule now reads from the report what the bridge would
answer, as 0.105.119 item39's cap_full_pass did.

  staff       the hospital's post labours given back by the report itself (DIAGNOSE,
              SURGERY and BONE_SETTING are in no work detail: a recompute takes them
              off), and a recreation-burrow member's left off
  pair_chairs a zone whose every chair has one beside it (zone_lone_chairs 0)
  food_store  the near piles full but no free roofed floor round the shop (room False)
  squad_fill  every dwarf the fill could draft is in `avoid` (military.draft_ids)

    python tests/test_item24_refusals.py
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

import digest  # noqa: E402
import planner_food as PF  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
from planner_draft_pool import draft_pool_left  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
LUA = ROOT / "lua"
CFG = PLANNER_CONFIG


def fort() -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    return s


def by_rule(props, rule):
    return [x for x in props if x.rule == rule]


def lua(name: str) -> str:
    return (LUA / name).read_text(encoding="utf-8").replace("\r\n", "\n")


# --- staff ---------------------------------------------------------------------------------

def _hospital(staff):
    s = fort()
    s["dwarves"]["needs_medical_care"] = 1
    s["health"] = {"hospital": [{"id": 3, "staff": staff, "zones": [{"type": "MeetingHall", "beds": 4}]}]}
    s["locations"] = {"count": {"HOSPITAL": 1}, "total": 1, "list": [{"id": 3, "type": "HOSPITAL", "jobs": {}}]}
    return s


@test("item24 staff: a recreation member's post labours are off on purpose: not asked; another's still are")
def _():
    s = _hospital([{"post": "DIAGNOSTICIAN", "labors": ["SUTURING"], "unit_id": 1, "recreation": True}])
    assert not [x for x in by_rule(plan(s, Memory())[0], "staff") if x.action.get("type") == "staff_labors"]
    s = _hospital([{"post": "DIAGNOSTICIAN", "labors": ["SUTURING"], "unit_id": 1, "recreation": True},
                   {"post": "SURGEON", "labors": ["SUTURING"], "unit_id": 2}])
    p = [x for x in by_rule(plan(s, Memory())[0], "staff") if x.action.get("type") == "staff_labors"]
    assert p and "surgeon" in p[0].reason and "diagnostician" not in p[0].reason, p


@test("item24 staff: the report gives the post labours back before it reads them, never a recreation member's")
def _():
    t = lua("ai-bridge-report-fort.lua")
    i_give, i_read = t.index("pcall(SOC.give_post_labors, u, post)"), t.index("for _, l in ipairs(MED_LABORS) do")
    assert i_give < i_read
    assert "if rec[u.id] then" in t and "recreation = rec[u.id] or nil" in t
    p = lua("ai-society-posts.lua")
    assert "if u and POST_LABORS[post] and not rec[u.id] then" in p
    for f in ("ai-bridge-report-fort.lua", "ai-society-posts.lua"):
        assert len(lua(f).encode("utf-8")) < 60000, f


# --- pair_chairs ---------------------------------------------------------------------------

def _tavern(**e):
    s = fort()
    s["dwarves"]["total"] = 95
    s["locations"] = {"list": [{"id": 5, "type": "INN_TAVERN", "zones": [358, 545], "chests": 2,
                                "have": {"goblets": 10, "instruments": 5}, "want": {"goblets": 10, "instruments": 5},
                                **e}]}
    s.setdefault("needs", {}).setdefault("needs", {})["BeWithFriends"] = {"badly": 59, "distracted": 70}
    return s


@test("item24 pair_chairs: zones whose every chair has one beside it are not asked (A: 358 and 545)")
def _():
    s = _tavern(zone_chairs={"358": 12, "545": 8}, zone_lone_chairs={"358": 0, "545": 0})
    assert not by_rule(plan(s, Memory())[0], "pair_chairs")
    c = by_rule(plan(_tavern(zone_chairs={"358": 12, "545": 8}, zone_lone_chairs={"358": 0, "545": 3}),
                     Memory())[0], "pair_chairs")
    assert c and c[0].action["zones"] == [545], c
    # an older bridge (no zone_lone_chairs): both, as before
    c = by_rule(plan(_tavern(zone_chairs={"358": 12, "545": 8}), Memory())[0], "pair_chairs")
    assert c and c[0].action["zones"] == [358, 545], c


@test("item24 pair_chairs: the needs' quick fix reads the same (planner_tantrums)")
def _():
    from planner_locations import zone_has_chairs
    loc = {"zone_chairs": {"1": 4, "2": 4}, "zone_lone_chairs": {"1": 0, "2": 1}}
    assert not zone_has_chairs(loc, 1) and zone_has_chairs(loc, 2)
    assert "zone_has_chairs(e, z)" in (ROOT / "brain" / "planner_tantrums.py").read_text(encoding="utf-8")


@test("item24 pair_chairs: the report counts each zone's lone chairs (the four sides), under 60,000 bytes")
def _():
    t = lua("ai-bridge-report-civic.lua")
    assert "e.zone_lone_chairs = lone" in t and "lone[tostring(bid)] = k" in t
    assert len(t.encode("utf-8")) < 60000


# --- food_store ----------------------------------------------------------------------------

STILL = {"id": 20, "kind": "Still", "x": 25, "y": 21, "z": 100, "elevation": 0, "x1": 24, "y1": 20, "x2": 26, "y2": 22}
KITCHEN = {"id": 21, "kind": "Kitchen", "x": 31, "y": 21, "z": 100, "elevation": 0,
           "x1": 30, "y1": 20, "x2": 32, "y2": 22}


def _full(shops):
    pile = {"id": 1, "x1": 20, "y1": 24, "x2": 26, "y2": 30, "z": 100, "elevation": 0, "tiles": 49, "used": 49,
            "outside": 0, "barrels": 49, "bins": 0, "ai": True, "shop_id": 20}
    s = copy.deepcopy(BASE)
    s["food_store"] = {"piles": [pile], "shops": [dict(x) for x in shops], "reach": 20,
                       "items": {"loose": 4, "in_shops": 10, "exposed": 0, "in_containers": 0, "rotten": 0, "total": 0}}
    s["dwarves"]["total"] = 40
    return digest.normalize(s)


def _mine(s):
    props, notes = [], []
    PF._food_store_rule(s, CFG, props, notes, Memory())
    return [x for x in props if x.rule == "food_store"], notes


@test("item24 food_store: the near piles full and no free roofed floor round the Still: a note, not asked")
def _():
    props, notes = _mine(_full([dict(STILL, pile=1, dist=2, room=False)]))
    assert not props and any("no free roofed floor" in n for n in notes), (props, notes)
    props, _ = _mine(_full([dict(STILL, pile=1, dist=2, room=True)]))
    assert props and props[0].action["building_id"] == 20, props
    # an older bridge (no room on a shop with a near pile): asked, as before
    props, _ = _mine(_full([dict(STILL, pile=1, dist=2)]))
    assert props and props[0].action["building_id"] == 20, props


@test("item24 food_store: the Still has no room but the Kitchen the same piles serve has: the Kitchen")
def _():
    props, _ = _mine(_full([dict(STILL, pile=1, dist=2, room=False), dict(KITCHEN, pile=1, dist=6, room=True)]))
    assert props and props[0].action["building_id"] == 21, props


@test("item24 food_store: the report says `room` for every kitchen and still, a pile near or not")
def _():
    t = lua("ai-food-store.lua")
    i = t.index("local okr, r = pcall(inside_rect, box_of(b), SIDE_MIN, SIDE_MIN, REACH)")
    assert "if not d or d > REACH then" not in t[i - 400:i], t[i - 400:i]


# --- squad_fill ----------------------------------------------------------------------------

def _army(draft_ids=None, pool=None):
    s = fort()
    s["settings"]["traits"] = {"militarism": 0}
    s["military"]["squads"][1]["members"] = 4
    s["military"]["soldiers"] = 14
    if draft_ids is not None:
        s["military"]["draft_ids"] = draft_ids
        s["military"]["draft_pool"] = len(draft_ids) if pool is None else pool
    return s


def _home(ids):
    from planner_core import abs_tick
    m = Memory()
    m.released = {str(i): abs_tick(fort()) - 10 for i in ids}
    return m


@test("item24 squad_fill: every dwarf the fill could draft was sent home lately: a note, no fill (A 78 in 3 h)")
def _():
    s = _army([101, 102, 103])
    p, notes = plan(s, _home([101, 102, 103]))
    assert not by_rule(p, "squad_fill") and any("nobody left to draft" in n for n in notes), notes
    p, _ = plan(_army([101, 102, 103]), _home([101, 102]))
    f = by_rule(p, "squad_fill")
    assert f and f[0].action["avoid"][:2] in ([101, 102], [102, 101]), f
    # nobody draftable at all, nobody sent home: not asked either
    assert not by_rule(plan(_army([]), Memory())[0], "squad_fill")


@test("item24 squad_fill: an older bridge, or the list cut at its cap: asked as before")
def _():
    assert by_rule(plan(_army(), Memory())[0], "squad_fill")
    assert by_rule(plan(_army([101], pool=250), _home([101]))[0], "squad_fill")
    assert draft_pool_left({}, [1]) is None
    assert draft_pool_left({"draft_pool": 0, "draft_ids": {}}, []) == 0      # an empty Lua table
    assert draft_pool_left({"draft_pool": 2, "draft_ids": [5, 6]}, [5]) == 1


@test("item24 squad_fill: a squad with no leader is still asked (the fill seats one without `avoid`)")
def _():
    s = _army([101])
    s["military"]["squads"][1]["leader"] = False
    assert by_rule(plan(s, _home([101]))[0], "squad_fill")


@test("item24 squad_fill: the military report lists the fill's pool (draft_pool_ids), under 60,000 bytes")
def _():
    d, m = lua("ai-military-draft.lua"), lua("ai-military.lua")
    assert "function draft_pool_ids()" in d and "candidates(false)" in d
    assert "out.draft_pool = #ids" in m and "out.draft_ids = ids" in m
    assert len(d.encode("utf-8")) < 60000 and len(m.encode("utf-8")) < 60000


if __name__ == "__main__":
    finish()
