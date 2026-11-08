"""Tests for 0.105.29 (customs fixes), after an independent check of the
customs round:

1. one customs pass at the end of plan() (planner_building.customs_pass):
   every rule's new level gets the fort's customs, not only _project_rules'
   (ore_piles on bags, cloth, gems... levels; field_kitchens on a fishery);
2. field_hall / field_kitchens keep 3 levels under the surface and inside
   the plan's range, else don't apply (the normal district, no stamp);
3. the gate bands keep out of the shelter's margin: market_gate s-5 .. s-3,
   gate_barracks s-4 .. s-2;
4. a custom is stamped (action["customs"]) only when it changed the level;
5. the central pass and the urgent path are one function (apply_customs).

    python tests/test_customs_fixes.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import make_test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import masterplan  # noqa: E402
import planner as pl  # noqa: E402
import planner_building as pb  # noqa: E402
from planner import Memory, Proposal, plan  # noqa: E402
from planner_industry import _deep_surface_filter  # noqa: E402
from lupa.lua53 import LuaRuntime  # noqa: E402

test = make_test()

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
REAL = ROOT / "tests" / "fixtures" / "real"
SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
STATE = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite", "season": "spring"},
         "dwarves": {"total": 40}}
PROFILE = {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True}
SURFACE = 60

DEFAULT: dict = {}
MONASTERY = {"piety": 100, "welfare": 40}
MERCHANT = {"trade": 80, "outsiders": 50}
DEEP = {"mining": 100, "verticality": 60}
GARDEN = {"agriculture": 80}
WAR = {"militarism": 100}
HERMIT = {"outsiders": -120, "caution": 30}


def presets() -> dict:
    """BUILTIN_PRESETS from lua/ai-overseer-settings.lua (as test_customs.py)."""
    src = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
    block = re.search(r"^BUILTIN_PRESETS = \{.*?^\}", src, re.S | re.M).group(0)
    lua = LuaRuntime()
    lua.execute(block)
    t = lua.globals().BUILTIN_PRESETS
    return {name: dict(t[name].items()) for name in t.keys()}


PRESETS = presets()


def memory(traits, soil=(58, 59), entrance="100,60,160") -> Memory:
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {entrance: {"kind": "surface", "elevation": SURFACE}} if entrance else {}}
    assert masterplan.ensure(copy.deepcopy(STATE), m, dict(SITE, soil=list(soil)), traits, PROFILE)
    return m


def district(m, kind) -> dict:
    return next(x for x in m.atlas["plan"]["districts"] if x["kind"] == kind)


def real(name, traits) -> dict:
    s = json.loads((REAL / name).read_text(encoding="utf-8"))
    for k, v in BASE.items():
        s.setdefault(k, copy.deepcopy(v))
    s.setdefault("settings", {})["traits"] = dict(traits)
    return s


def levels(props) -> list:
    return [p for p in props if p.action.get("type") == "start_project"]


class Patched:
    def __init__(self, mod, target, **attrs):
        self.mod, self.target, self.attrs, self.real = mod, target, attrs, {}

    def __enter__(self):
        for k, v in self.attrs.items():
            self.real[k] = getattr(self.target, k)
            if isinstance(v, dict) and isinstance(self.real[k], dict):
                setattr(self.target, k, {**self.real[k], **v})
            else:
                setattr(self.target, k, v)

    def __exit__(self, *a):
        for k, v in self.real.items():
            setattr(self.target, k, v)


# --- 1. the central pass ------------------------------------------------------------

@test("fix 1: the Deep mine's workshop levels from bags, cloth, gems, bottleneck... all carry ore_piles")
def _():
    s = real("region2-0.48-y52-spring.json", DEEP)
    props = levels(plan(copy.deepcopy(s), memory(DEEP))[0])
    shops = [p for p in props if p.action["kind"] == "workshops"]
    rules = {p.rule for p in shops}
    assert rules - {"build"}, rules                       # proposers outside _project_rules' ladder
    for p in shops:
        assert p.action["customs"] == ["ore_piles"], (p.rule, p.action)
        assert p.action["style"]["customs"] == ["ore_piles"], (p.rule, p.action)
        assert "plan" not in p.action, (p.rule, p.action)  # a layout custom: the rule's placement stands
    # the same fort at default sliders: no customs keys anywhere
    for p in levels(plan(copy.deepcopy(real("region2-0.48-y52-spring.json", DEFAULT)), memory(DEFAULT))[0]):
        assert "customs" not in p.action and "customs" not in (p.action.get("style") or {}), p.action


@test("fix 1: the Garden fort's fishery level (food shops only) goes to the farms (field_kitchens)")
def _():
    s = real("region2-0.83-y62-spring.json", GARDEN)
    m = memory(GARDEN, soil=(55, 56))
    fish = [p for p in levels(plan(copy.deepcopy(s), m)[0]) if p.rule == "fishery"]
    assert fish, "the fixture proposes a fishery"
    a = fish[0].action
    assert a["customs"] == ["field_kitchens"] and a["plan"]["elev_target"] == 55, a
    assert a["plan"]["district"] == masterplan._plain(district(m, "farms")["name"]), a


@test("fix 1: customs_pass keeps a rule's own placement when the hint doesn't apply; skips done levels")
def _():
    m = memory(GARDEN, soil=(55, 56))
    own = {"type": "start_project", "kind": "workshops", "shops": ["Masons"], "max_elev": 50, "style": {"x": 1}}
    food = {"type": "start_project", "kind": "workshops", "shops": ["Still"], "near": "farms"}
    done = {"type": "start_project", "kind": "workshops", "shops": ["Still"], "customs": ["field_kitchens"]}
    ladder = {"type": "start_project", "kind": "dining", "plan": {"district": "x"}}
    other = {"type": "place_surface", "kind": "depot"}
    props = [Proposal("r", copy.deepcopy(a), "", 1) for a in (own, food, done, ladder, other)]
    pb.customs_pass(props, m, GARDEN, 40)
    assert props[0].action == own, props[0].action           # no custom concerns a mason's level
    assert props[1].action["customs"] == ["field_kitchens"] and props[1].action["near"] == "farms"
    assert props[1].action["plan"]["elev_target"] == 55, props[1].action
    assert props[2].action == done and props[3].action == ladder and props[4].action == other
    # a shared style dict is never changed in place
    style = {"hall": "plain"}
    p1 = Proposal("r", {"type": "start_project", "kind": "workshops", "shops": ["Masons"], "style": style}, "", 1)
    pb.customs_pass([p1], memory(DEEP), DEEP, 40)
    assert p1.action["style"]["customs"] == ["ore_piles"] and style == {"hall": "plain"}
    # no custom on: nothing at all, the very same objects
    for t in (DEFAULT, {"fortification": 50}):
        acts = [copy.deepcopy(a) for a in (own, food)]
        ps = [Proposal("r", a, "", 1) for a in acts]
        pb.customs_pass(ps, m, t, 40)
        assert all(p.action is a for p, a in zip(ps, acts)) and acts == [own, food]


@test("fix 5: the urgent levels and every other rule's go through one function, run once by plan()")
def _():
    assert not hasattr(pb, "_urgent")
    calls = []
    real_apply = pb.apply_customs

    def spy(action, *a, **kw):
        calls.append((action.get("kind"), kw.get("urgent", False)))
        return real_apply(action, *a, **kw)
    s = real("region2-0.48-y52-spring.json", DEEP)
    with Patched(pb, pb, apply_customs=spy):
        props = levels(plan(copy.deepcopy(s), memory(DEEP))[0])
    assert len(calls) == len(props) and "workshops" in {k for k, _u in calls}, (calls, len(props))
    assert sum(1 for _k, u in calls if u) >= len(props) - 1, calls     # all but the ladder's level
    # without the pass, no proposal of these rules gets a custom
    with Patched(pl, pl, customs_pass=lambda *a: None):
        bare = levels(plan(copy.deepcopy(s), memory(DEEP))[0])
    assert any(p.rule != "build" and "customs" not in p.action for p in bare)


# --- 2. field_hall / field_kitchens kept under the surface ----------------------------

@test("fix 2: field_hall with the soil at, above or just under the surface: the normal district, no stamp")
def _():
    food = {"type": "start_project", "kind": "workshops", "shops": ["Still", "Kitchen"]}
    for soil in ((58, 59), (59, 59), (60, 60), (61, 62)):
        m = memory(GARDEN, soil=soil)
        h = masterplan.hint(m, "dining", traits=GARDEN, profile=PROFILE)
        homes = district(m, "homes")
        assert "customs" not in h and h["district"] == homes["name"][:40], (soil, h)
        assert (h["elev_lo"], h["elev_hi"]) == (homes["lo"], homes["hi"]), (soil, h)
        w = masterplan.hint(m, "workshops", traits=GARDEN, profile=PROFILE, action=food)
        assert "customs" not in w and w["district"] == district(m, "industry")["name"][:40], (soil, w)
        # a miss is the homes district's, never the farms'
        a = {"type": "start_project", "kind": "dining", "tables": 10}
        pb.apply_customs(a, m, GARDEN, PROFILE, 40)
        assert "customs" not in a, a
        masterplan.note_result(m, a, {"ok": True, "project_id": 1, "elevation": 50, "in_district": False}, STATE)
        assert not district(m, "farms").get("missed"), district(m, "farms")


@test("fix 2: a farms band grown up to the surface is cut at s-3 and to the plan's range")
def _():
    m = memory(GARDEN, soil=(55, 56))
    farms = district(m, "farms")
    farms["lo"], farms["hi"], farms["target"] = 55, 62, 61         # grown by misses, past the range (top 60)
    for _ in range(5):
        h = masterplan.hint(m, "dining", traits=GARDEN, profile=PROFILE)
        assert h["customs"] == ["field_hall"] and (h["elev_lo"], h["elev_hi"]) == (55, SURFACE - 3), h
        assert 55 <= h["elev_target"] <= SURFACE - 3, h
        farms.setdefault("levels", []).append({"elevation": h["elev_target"]})
    farms["lo"], farms["hi"] = SURFACE - 2, SURFACE + 2            # nothing 3 under: no custom
    h = masterplan.hint(m, "dining", traits=GARDEN, profile=PROFILE)
    assert "customs" not in h and h["elev_hi"] <= SURFACE - 3, h


# --- 3. the gate bands --------------------------------------------------------------

@test("fix 3: market_gate taverns stay in s-5 .. s-3, gate_barracks in s-4 .. s-2, out of the shelter's margin")
def _():
    for traits, kinds, band in ((PRESETS["Merchant city"], ("tavern",), (SURFACE - 5, SURFACE - 3)),
                                (PRESETS["War-hold"], ("barracks", "archery"), (SURFACE - 4, SURFACE - 2))):
        m = memory(traits)
        for k in kinds:
            seen = []
            for i in range(6):                           # later levels spread through the band
                h = masterplan.hint(m, k, traits=traits, profile=PROFILE)
                assert (h["elev_lo"], h["elev_hi"]) == band, (k, h)
                assert band[0] <= h["elev_target"] <= band[1], (k, h)
                seen.append(h["elev_target"])
                masterplan.note_result(m, {"type": "start_project", "kind": k, "plan": h},
                                       {"ok": True, "project_id": 100 + i, "elevation": h["elev_target"],
                                        "in_district": True}, STATE)
            assert seen[0] == band[1] and max(seen) <= band[1], (k, seen)   # the band's top first


# --- 4. stamps only when the custom changed the level -------------------------------

@test("fix 4: hidden_hold stamped only when the ceiling lowered max_elev")
def _():
    m = memory(HERMIT)
    ceil = masterplan.ceiling(m, HERMIT)
    props = [Proposal("b", {"type": "start_project", "kind": "storage", "max_elev": ceil - 5}, "", 6),
             Proposal("b", {"type": "start_project", "kind": "storage", "max_elev": ceil}, "", 6),
             Proposal("b", {"type": "start_project", "kind": "storage", "max_elev": ceil + 3}, "", 6),
             Proposal("b", {"type": "start_project", "kind": "storage"}, "", 6)]
    before = [copy.deepcopy(p.action) for p in props]
    out = _deep_surface_filter({}, HERMIT, m, props, [])
    assert out[0].action == before[0] and out[1].action == before[1], (out[0].action, out[1].action)
    for p in out[2:]:
        assert p.action["max_elev"] == ceil and p.action["customs"] == ["hidden_hold"], p.action


@test("fix 4: wide_ways not stamped when narrow_ways (Warren) sets the way back to 1, or it was 3 already")
def _():
    m = memory(MERCHANT)
    h = masterplan.hint(m, "bedrooms", traits=MERCHANT, profile=PROFILE)
    assert h["avenue"] == 3 and h["customs"] == ["wide_ways"], h
    with Patched(masterplan, masterplan, has_rule=lambda c, r: r == "narrow_ways"):
        h = masterplan.hint(m, "bedrooms", traits=MERCHANT, profile=PROFILE)
        assert h["avenue"] == 1 and "customs" not in h, h
        tv = masterplan.hint(m, "tavern", traits=MERCHANT, profile=PROFILE)
        assert tv["customs"] == ["market_gate"], tv
    with Patched(masterplan, masterplan, has_rule=lambda c, r: r == "great_shaft"):
        h = masterplan.hint(m, "bedrooms", traits=MERCHANT, profile=PROFILE)
        assert h["avenue"] == 3 and "customs" not in h, h
    with Patched(masterplan, masterplan, _grammar=lambda t, p: {"avenue": 3, "corridors": "straight"}):
        h = masterplan.hint(m, "bedrooms", traits=MERCHANT, profile=PROFILE)
        assert h["avenue"] == 3 and "customs" not in h, h
    # winding_ways likewise under narrow_ways (it would be 1 and dog-leg anyway)
    mh = memory(HERMIT)
    with Patched(masterplan, masterplan, has_rule=lambda c, r: r == "narrow_ways"):
        h = masterplan.hint(mh, "bedrooms", traits=HERMIT, profile=PROFILE, citizens=40)
        assert h["avenue"] == 1 and "customs" not in h, h


@test("fix 4: cells, deep_hall and field_hall stamped only when the district changed from the default")
def _():
    cases = ((MONASTERY, "bedrooms", "halls", "cells", (58, 59)),
             (DEEP, "dining", "industry", "deep_hall", (58, 59)),
             (GARDEN, "dining", "farms", "field_hall", (55, 56)))
    for traits, kind, dkind, cid, soil in cases:
        m = memory(traits, soil=soil)
        assert masterplan.hint(m, kind, traits=traits, profile=PROFILE)["customs"] == [cid]
        with Patched(masterplan, masterplan, DISTRICT_OF={kind: dkind}):
            h = masterplan.hint(m, kind, traits=traits, profile=PROFILE)
            assert "customs" not in h and h["district"] == district(m, dkind)["name"][:40], (cid, h)
            a = {"type": "start_project", "kind": kind}
            pb.apply_customs(a, m, traits, PROFILE, 40)
            assert "customs" not in a, (cid, a)


# --- defaults ------------------------------------------------------------------------

@test("defaults: plan() over the real fixtures carries no customs key at all")
def _():
    for f in sorted(REAL.glob("*.json")):
        s = real(f.name, DEFAULT)
        for p in levels(plan(copy.deepcopy(s), memory(DEFAULT))[0]):
            assert "customs" not in p.action and "customs" not in (p.action.get("style") or {}), (f.name, p.action)


if __name__ == "__main__":
    finish()
