"""(0.105.119 item36) The fresh run's stalled moods, 25 Nov 15:00-18:30.

A, 15:44: Deler's fey armorer mood needed a forge; place_mood_shop answered
"still looking for a free 5x5 room ... (the search goes on next time)" twice,
the refusal's back-off sent the mood to a workshops level, and with a level
"coming" the shop was never placed again: no forge in the mood's 40 days
(14 real minutes), berserk, struck down. A, 15:05: Momuz's cut gem, the same
for a Jeweler's. C, E: the reserve's slaughter refused "no spare tame
animal" 16 and 12 times in 3.5 h: the herd's counts read 5 cats, 3 of them
pets, as 4 spare.

    python tests/test_item36_moods.py
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

import planner_core  # noqa: E402
import planner_moods  # noqa: E402
import planner_mood_help as MH  # noqa: E402
from planner import Memory, PLANNER_CONFIG as CFG  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
SEARCH = "still looking for a free 5x5 room for a MetalsmithsForge (the search goes on next time)"


def forge_fort(project=False) -> dict:
    s = copy.deepcopy(BASE)
    s["orders"] = []
    s["buildings"]["workshops"].pop("MetalsmithsForge", None)
    s["buildings"]["workshops"].pop("MagmaForge", None)
    s["projects"] = {"open": []}
    if project:
        s["projects"]["open"] = [{"kind": "workshops", "status": "digging",
                                  "summary": {"workshops": ["MetalsmithsForge"]}}]
    s["moods"] = {"list": [{"unit_id": 17621, "name": "Deler", "mood": "Fey", "craft": True,
                            "skill": "FORGE_ARMOR"}]}
    return s


def refuse(m, kind, s, why):
    p = planner_core.Proposal("mood", {"type": "place_mood_shop", "kind": kind}, "", 0)
    now = planner_core.abs_tick(s)
    m.refusals[planner_core.refusal_key(p)] = {"n": 2, "at": now, "until": now + 2 * 1200, "why": why}


def run(s, m):
    m.moods_seen = {"17621": planner_core.abs_tick(s)}
    props, notes = [], []
    planner_moods._mood_rules(s, m, CFG, props, notes)
    return props, notes


@test("1 mood: a refused 'search goes on next time' doesn't back the mood's placement off")
def _():
    s = forge_fort()
    m = Memory()
    refuse(m, "MetalsmithsForge", s, SEARCH)
    place, level = planner_moods.split_placeable(s, m, "mood", ["MetalsmithsForge"])
    assert place == ["MetalsmithsForge"] and level == [], (place, level)
    props, _ = run(s, m)
    assert {"type": "place_mood_shop", "kind": "MetalsmithsForge"} in [p.action for p in props], \
        [p.action for p in props]
    # "no free 5x5" (there is none) keeps its back-off: the level
    m2 = Memory()
    refuse(m2, "MetalsmithsForge", s, "no free 5x5 of roofed floor in the fort for a MetalsmithsForge")
    assert planner_moods.split_placeable(s, m2, "mood", ["MetalsmithsForge"]) == ([], ["MetalsmithsForge"])
    # the reserve's own shops keep the back-off (no life at stake)
    m3 = Memory()
    p = planner_core.Proposal("mood_reserve", {"type": "place_mood_shop", "kind": "Jewelers"}, "", 0)
    now = planner_core.abs_tick(s)
    m3.refusals[planner_core.refusal_key(p)] = {"n": 1, "at": now, "until": now + 1200, "why": SEARCH}
    assert planner_moods.split_placeable(s, m3, "mood_reserve", ["Jewelers"]) == ([], ["Jewelers"])


@test("1 mood: a level with the forge is coming: one is still placed on free floor (Deler, A)")
def _():
    s = forge_fort(project=True)
    assert planner_moods._shop_coming(s, "MetalsmithsForge")
    m = Memory()
    props, notes = run(s, m)
    pl = [p for p in props if p.action.get("type") == "place_mood_shop"]
    assert [p.action for p in pl] == [{"type": "place_mood_shop", "kind": "MetalsmithsForge"}] and pl[0].priority == 0, \
        [p.action for p in props]
    # placed: coming, nothing again (the note only)
    MH.note_mood_help(pl[0], {"ok": True}, s, m, planner_core.abs_tick(s))
    props, notes = run(s, m)
    assert not [p for p in props if p.action.get("type") == "place_mood_shop"], [p.action for p in props]
    assert any("Deler" in n and "MetalsmithsForge" in n for n in notes), notes
    # no free floor (refused, backed off): the level's note, nothing placed
    m2 = Memory()
    refuse(m2, "MetalsmithsForge", s, "no free 5x5 of roofed floor in the fort for a MetalsmithsForge")
    props, notes = run(s, m2)
    assert not [p for p in props if p.action.get("type") == "place_mood_shop"]
    assert any("already being built" in n for n in notes), notes


@test("1 mood: a material's shop (Momuz's Jeweler's) coming by a level is still placed meanwhile")
def _():
    s = forge_fort()
    s["buildings"]["workshops"].pop("Jewelers", None)
    s["projects"]["open"] = [{"kind": "workshops", "status": "digging", "summary": {"workshops": ["Jewelers"]}}]
    s.setdefault("stocks", {})["rough_gems"] = 115
    acts: list = []
    who = {"name": "Momuz", "unit_id": 17593, "stalled": 10}
    assert planner_moods._mood_shop(s, ("Jewelers",), acts, who, "a gem cut", memory=Memory())
    assert [a for a, _ in acts] == [{"type": "place_mood_shop", "kind": "Jewelers"}], acts


HERD_C = [  # C's herd at 18:40: 5 adult cats, 3 of them pets; no other kind with three adults
    {"name": "CAT", "n": 7, "f": 3, "m": 2, "kids": 2, "protected": 3, "marked": 0, "caged": 0},
    {"name": "BIRD_GOOSE", "n": 4, "f": 2, "m": 1, "kids": 1, "protected": 1, "marked": 0, "caged": 0},
    {"name": "BIRD_GUINEAFOWL", "n": 4, "f": 2, "m": 2, "kids": 0, "protected": 3, "marked": 0, "caged": 0},
]


@test("2 reserve: C's herd has no spare kind (the protected counted as adults)")
def _():
    s = forge_fort()
    s["herd"] = {"kinds": copy.deepcopy(HERD_C), "marked": 0, "marked_waiting": 0}
    assert planner_moods.spare_tame_kinds(s) == 0


@test("2 reserve: refused 'no spare tame animal': not asked again till the herd changes")
def _():
    s = forge_fort()
    s["buildings"]["workshops"].update({"Butchers": 1, "Tanners": 1})
    s["others_on_map"]["tame_animals"] = 30
    s["herd"] = {"kinds": [{"name": "CAT", "n": 7, "f": 3, "m": 2, "kids": 2, "protected": 0, "caged": 0}],
                 "marked": 0, "marked_waiting": 0}
    m = Memory()
    acts: list = []
    assert planner_moods._mood_slaughter(s, m, CFG, acts, "its bones") is True and acts
    p = planner_core.Proposal("mood_reserve", {"type": "slaughter_one"}, "", 1)
    MH.note_mood_help(p, {"ok": False, "rejected": True,
                          "error": "no spare tame animal (three or more of a kind, adult, no pet or war animal)"},
                      s, m, planner_core.abs_tick(s))
    acts = []
    assert planner_moods._mood_slaughter(s, m, CFG, acts, "its bones") is False and acts == []
    # a named mood still asks (any spare animal, a life at stake)
    acts = []
    assert planner_moods._mood_slaughter(s, m, CFG, acts, "its bones", mood={"name": "X", "unit_id": 1}) is True
    # the herd changes (a kitten grown): asked again
    s["herd"]["kinds"][0].update({"f": 4, "kids": 1})
    acts = []
    assert planner_moods._mood_slaughter(s, m, CFG, acts, "its bones") is True and acts
    # one went through: the memory cleared
    MH.note_mood_help(p, {"ok": True}, s, m, planner_core.abs_tick(s))
    assert "reserve_no_spare" not in m.mood_help


if __name__ == "__main__":
    finish()
