"""Tests for 0.105.29 (customs urgent): the urgent levels of _project_rules
(survival workshops, the manager's suite, the dining-hall shortfall, the
social shortfall's taverns and temples, the urgent hospitals, shrine,
tombs, jail and tavern) get the fort's customs, but only when a custom
concerns their kind. Otherwise the proposal is exactly today's.

    python tests/test_customs_urgent.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import customs  # noqa: E402
import masterplan  # noqa: E402
import planner_building as pb  # noqa: E402
from planner import Memory, plan  # noqa: E402

test = make_test()

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
PROFILE = {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True}

DEFAULT: dict = {}
MONASTERY = {"piety": 100, "welfare": 40}
MERCHANT = {"trade": 80, "outsiders": 50}
DEEP = {"mining": 100, "verticality": 60}
GARDEN = {"agriculture": 80}
WAR = {"militarism": 100}
HERMIT = {"outsiders": -120, "caution": 30}
ALL = [DEFAULT, MONASTERY, MERCHANT, DEEP, GARDEN, WAR, HERMIT]


def memory(traits) -> Memory:
    """A fort with its master plan drawn (as test_customs.py's)."""
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {}}
    st = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite", "season": "spring"},
          "dwarves": {"total": 40}}
    assert masterplan.ensure(st, m, SITE, traits, PROFILE)
    return m


def district(m, kind) -> dict:
    return next(x for x in m.atlas["plan"]["districts"] if x["kind"] == kind)


def fort(traits) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = dict(traits)
    s["locations"] = {"count": {"HOSPITAL": 1, "INN_TAVERN": 1, "LIBRARY": 1, "TEMPLE": 1}, "total": 4}
    return s


class Patched:
    """Swap module attributes for a block (restored after)."""

    def __init__(self, mod, **attrs):
        self.mod, self.attrs, self.real = mod, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.real[k] = getattr(self.mod, k)
            setattr(self.mod, k, v)

    def __exit__(self, *a):
        for k, v in self.real.items():
            setattr(self.mod, k, v)


def urgent(s, m, kind) -> list:
    return [p.action for p in plan(copy.deepcopy(s), m)[0]
            if p.action.get("type") == "start_project" and p.action.get("urgent") and p.action.get("kind") == kind]


def today(s, traits, kind) -> list:
    """The urgent proposals as before this change: the urgent paths without
    the customs helper (the Hermit hold's hidden_hold filter, group A's,
    still applies to every start_project, as it did)."""
    with Patched(pb, _urgent=lambda action, *a: action):
        return urgent(s, memory(traits), kind)


def both(make, traits, kind):
    """(with the fort's customs, as if it had none) for one fort."""
    s = make(traits)
    return urgent(s, memory(traits), kind), today(s, traits, kind)


def assert_today(make, traits, kind):
    got, old = both(make, traits, kind)
    assert got, (kind, traits)
    assert got == old, (kind, traits, got, old)
    for a in got:
        assert set(a.get("customs") or []) <= {"hidden_hold"} and "plan" not in a, a
        assert "customs" not in (a.get("style") or {}), a
    return got


# --- the ways the urgent rules fire -------------------------------------------------

DINING = {"have": 5, "want": 20, "citizens": 80, "tables": 15}


def dining_fort(traits):
    return fort(traits)


def social(kind):
    return lambda s, cfg: [(kind, f"many miss a {kind}")]


def survival_fort(missing):
    def make(traits):
        s = fort(traits)
        for w in missing:
            s["buildings"]["workshops"].pop(w, None)
            s["buildings"].get("furnaces", {}).pop(w, None)
        for w in ("Still", "Kitchen", "Carpenters", "Masons", "Craftsdwarfs", "Butchers"):
            if w not in missing:
                s["buildings"]["workshops"][w] = 1
        return s
    return make


@test("urgent dining: deep_hall to the industry band, field_hall to the farms elevation; others as today")
def _():
    with Patched(pb, dining_shortfall=lambda s, cfg: dict(DINING)):
        a = urgent(fort(DEEP), memory(DEEP), "dining")
        ind = district(memory(DEEP), "industry")
        assert a and a[0]["customs"] == ["deep_hall"], a
        assert a[0]["plan"]["district"] == masterplan._plain(ind.get("name") or ind["kind"]), a[0]["plan"]
        assert ind["lo"] <= a[0]["plan"]["elev_target"] <= ind["hi"], (a[0]["plan"], ind)
        assert "customs" not in (a[0].get("style") or {})              # placement only
        assert a[0]["tables"] == 15 and a[0]["urgent"] is True
        a = urgent(fort(GARDEN), memory(GARDEN), "dining")
        farms = district(memory(GARDEN), "farms")
        assert a and a[0]["customs"] == ["field_hall"], a
        assert (a[0]["plan"]["elev_lo"], a[0]["plan"]["elev_hi"]) == (farms["lo"], farms["hi"]), (a[0]["plan"], farms)
        for t in (DEFAULT, MONASTERY, MERCHANT, WAR, HERMIT):
            assert_today(dining_fort, t, "dining")


@test("urgent tavern (social shortfall): market_gate puts it in the gate band; others as today")
def _():
    with Patched(pb, social_shortfall=social("tavern")):
        m = memory(MERCHANT)
        a = urgent(fort(MERCHANT), m, "tavern")
        assert a and "market_gate" in a[0]["customs"], a
        assert a[0]["customs"] == sorted(a[0]["customs"]) and "customs" not in (a[0].get("style") or {})
        lo, hi, _ = masterplan._gate_band(m, MERCHANT)
        assert (a[0]["plan"]["elev_lo"], a[0]["plan"]["elev_hi"]) == (lo, hi), (a[0]["plan"], lo, hi)
        assert a[0]["tables"] == 20
        for t in (DEFAULT, MONASTERY, DEEP, GARDEN, WAR, HERMIT):
            assert_today(fort, t, "tavern")


@test("urgent tavern (friends, both slots taken): market_gate too; default as today")
def _():
    def busy(traits):
        s = fort(traits)
        s["locations"] = {"count": {"HOSPITAL": 1, "LIBRARY": 1, "TEMPLE": 1}, "total": 3}
        s["projects"] = {"max_open": 2, "open": [
            {"id": 21, "kind": "well", "phase": "dig", "summary": {}},
            {"id": 23, "kind": "suites", "phase": "furnish", "summary": {}}]}
        s.setdefault("needs", {}).setdefault("needs", {})["BeWithFriends"] = {"badly": 150}
        return s
    with Patched(pb, social_shortfall=lambda s, cfg: []):
        a = urgent(busy(MERCHANT), memory(MERCHANT), "tavern")
        assert a and "market_gate" in a[0]["customs"] and "plan" in a[0], a
        assert_today(busy, DEFAULT, "tavern")
        assert_today(busy, GARDEN, "tavern")


@test("urgent temples (social shortfall and the shrine to all gods): cloister in style; others as today")
def _():
    with Patched(pb, social_shortfall=social("temple")):
        a = urgent(fort(MONASTERY), memory(MONASTERY), "temple")
        assert a and a[0]["style"] == {"customs": ["cloister"]} and a[0]["customs"] == ["cloister"], a
        assert "plan" not in a[0] and a[0]["size"] == "grand", a        # layout only: its placement stands
        for t in (DEFAULT, MERCHANT, DEEP, GARDEN, WAR, HERMIT):
            assert_today(fort, t, "temple")

    def gods(traits):
        s = fort(traits)
        s["dwarves"]["total"] = 100
        return s
    with Patched(pb, social_shortfall=lambda s, cfg: [], prayer_uncovered=lambda s: (60, {"Armok": 60})):
        a = urgent(gods(MONASTERY), memory(MONASTERY), "temple")
        assert a and a[0]["size"] == "shrine" and a[0]["style"]["customs"] == ["cloister"], a
        assert_today(gods, DEFAULT, "temple")
        assert_today(gods, WAR, "temple")


@test("urgent survival workshops: food shops only -> field_kitchens; with Carpenters, as today")
def _():
    food = survival_fort(["Still", "Kitchen"])
    a = urgent(food(GARDEN), memory(GARDEN), "workshops")
    assert a and a[0]["shops"] == ["Still", "Kitchen"] and a[0]["customs"] == ["field_kitchens"], a
    farms = district(memory(GARDEN), "farms")
    assert (a[0]["plan"]["elev_lo"], a[0]["plan"]["elev_hi"]) == (farms["lo"], farms["hi"]), a[0]["plan"]
    mixed = survival_fort(["Still", "Kitchen", "Carpenters"])
    assert_today(mixed, GARDEN, "workshops")             # not all food: the custom doesn't concern it
    for t in (DEFAULT, MONASTERY, MERCHANT, WAR, HERMIT):
        assert_today(food, t, "workshops")
        assert_today(mixed, t, "workshops")
    # the Deep mine's ore_piles is a workshops layout custom: style only, placement unchanged
    got, old = both(mixed, DEEP, "workshops")
    assert got[0]["style"] == {"customs": ["ore_piles"]} and got[0]["customs"] == ["ore_piles"], got
    assert "plan" not in got[0]
    assert {k: v for k, v in got[0].items() if k not in ("style", "customs")} == old[0]


@test("urgent suites, hospitals, tombs: no custom concerns them -> as today under every preset")
def _():
    def manager(traits):
        s = fort(traits)
        return s
    with Patched(pb, manager_needs_office=lambda s: True):
        for t in ALL:
            assert_today(manager, t, "suites")

    def hospital(traits):
        return fort(traits)
    with Patched(pb, hospital_shortfall=lambda s, traits, cfg: {"resting": 10, "have": 4, "want": 12,
                                                               "citizens": 80, "beds": 8}):
        for t in ALL:
            assert_today(hospital, t, "hospital")

    def ghosts(traits):
        s = fort(traits)
        s["dead"] = {"free_tombs": 0, "unburied": 3, "ghosts": 3}
        s["projects"]["open"] = [{"id": i, "kind": k, "phase": "dig", "dig": {"total": 100, "dug": 10, "stuck": 0}}
                                 for i, k in ((1, "bedrooms"), (2, "dining"))]
        return s
    for t in ALL:
        got = assert_today(ghosts, t, "tombs")
        assert "style" in got[0]                         # its own layout style, as before


@test("apply_customs: the shared helper, urgent vs not (memory None, unconcerned kinds)")
def _():
    m = memory(DEEP)
    a = {"type": "start_project", "kind": "hospital", "beds": 6, "urgent": True}
    assert pb.apply_customs(a, m, DEEP, PROFILE, 40, urgent=True) is None and "plan" not in a and "customs" not in a
    a = {"type": "start_project", "kind": "hospital", "beds": 6}
    w = pb.apply_customs(a, m, DEEP, PROFILE, 40)               # the ladder's: the plan's hint as always
    assert w and a["plan"] is w and "customs" not in a
    a = {"type": "start_project", "kind": "dining", "tables": 8, "urgent": True}
    assert pb.apply_customs(a, None, DEEP, PROFILE, 40, urgent=True) is None and a == {
        "type": "start_project", "kind": "dining", "tables": 8, "urgent": True}
    # a plan without the district the custom wants: the urgent placement stands (no hint kept)
    with Patched(masterplan, hint=lambda *a, **k: {"district": "halls", "elev_lo": 1, "elev_hi": 2, "elev_target": 1}):
        a = {"type": "start_project", "kind": "dining", "tables": 8, "urgent": True}
        assert pb.apply_customs(a, m, DEEP, PROFILE, 40, urgent=True) is None and "plan" not in a, a


if __name__ == "__main__":
    finish()
