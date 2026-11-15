"""Tests for layout option B, group B11: the master plan's district-and-floor
table (brain/masterplan_floors.py) and its three guarded calls from
masterplan.py. No game needed.

    python tests/test_b11_masterplan_floors.py
"""

from __future__ import annotations

import copy
import json
import random
import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
from harness import test, finish  # noqa: E402
sys.path.insert(0, str(ROOT / "brain"))

import customs  # noqa: E402
import masterplan  # noqa: E402
import masterplan_floors as MF  # noqa: E402
import planner_building  # noqa: E402
from culture import new_history, profile_from  # noqa: E402
from planner import Memory, plan  # noqa: E402
from planner_shopslots import WORKSHOP_GROUPS  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}
STATE = {"date": {"year": 150, "tick": 0, "day": 1, "month": "Granite"}, "dwarves": {"total": 40}}
CFG: dict = {}
TAGS = {"homes", "halls", "storage", "industry", "defence"}
OWN_KEYS = {"elevs", "tag", "group", "zone", "spine", "dirs"}


def mem(entrance=None, elevation=None) -> Memory:
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {}}
    if entrance:
        m.atlas["entrances"][entrance] = {"kind": "surface", **({"elevation": elevation} if elevation else {})}
    return m


def traits(**kw) -> dict:
    return {"verticality": 0, "spacing": 0, "grandeur": 0, "fortification": 0, "craftsmanship": 0, **kw}


def profile(**kw) -> dict:
    return {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True, **kw}


def drawn(t=None, site=SITE, m=None, floors=True, **prof) -> Memory:
    """A memory with a plan drawn by today's masterplan.draw (no table), and
    then, unless floors is False, its floor table."""
    m = m or mem()
    t = t if t is not None else traits()
    assert masterplan.draw(STATE, m, site, t, profile(**prof)) is not None
    assert "floors" not in m.atlas["plan"]
    if floors:
        MF.ensure(m, t, profile(**prof))
    return m


def district(m, kind):
    return next((d for d in m.atlas["plan"]["districts"] if d["kind"] == kind), None)


def levels_of(d) -> list:
    """The spec's `levels`: the band by distance from the target, the higher first."""
    return sorted(range(d["lo"], d["hi"] + 1), key=lambda e: (abs(e - d["target"]), -e))


def start(kind, **kw) -> dict:
    return {"type": "start_project", "kind": kind, **kw}


def in_ranges(h: dict) -> None:
    """The bridge's parse_floor ranges for the six keys this module fills."""
    e = h["elevs"]
    assert isinstance(e, list) and 1 <= len(e) <= 6, e
    assert all(isinstance(x, int) and not isinstance(x, bool) and -400 <= x <= 400 for x in e), e
    assert len(set(e)) == len(e), e
    assert h["tag"] in TAGS and re.fullmatch(r"[a-z_]{1,24}", h["tag"]), h["tag"]
    assert h["zone"] in ("near", "mid", "far", "any"), h["zone"]
    if "group" in h:
        assert re.fullmatch(r"[a-z_]{1,24}", h["group"]), h["group"]
    if "spine" in h:
        sp = h["spine"]
        assert set(sp) == {"x", "y"} and all(isinstance(sp[k], int) and 0 <= sp[k] <= 999 for k in sp), sp
    if "dirs" in h:
        ds = h["dirs"]
        assert 1 <= len(ds) <= 4 and len(set(ds)) == len(ds) and set(ds) <= set(masterplan.DIRS), ds


class StandIn:
    """A stand-in for group B10's floor_grammar while a test runs."""
    KEYS = {"gap": 2, "kind_gap": 1, "lead": 2, "ahead": 1, "run_max": 30, "run_min": 10, "arms_max": 2,
            "sides": "both", "stagger": 0, "bay": 0, "node": 3, "grow": ["arm", "turn"], "turns": "alternate",
            "balance": False, "axial": False, "neck": False, "pile_w": 5, "piles_new": 1, "full_retry_days": 28}

    def __init__(self, extra=None, fail=False):
        self.calls, self.extra, self.fail = [], extra or {}, fail

    def __enter__(self):
        self.old = sys.modules.get("floor_grammar")
        mod = types.ModuleType("floor_grammar")

        def grammar(traits, style, cfg, **kw):
            self.calls.append({"traits": traits, "style": style, "cfg": cfg, **kw})
            if self.fail:
                raise RuntimeError("stand-in fails")
            return dict(self.KEYS, **self.extra)
        mod.grammar = grammar
        sys.modules["floor_grammar"] = mod
        return self

    def __exit__(self, *exc):
        if self.old is None:
            sys.modules.pop("floor_grammar", None)
        else:
            sys.modules["floor_grammar"] = self.old


class NoGrammar:
    """No floor_grammar importable (this copy has none; after the merge it does)."""

    def __enter__(self):
        self.old = sys.modules.get("floor_grammar")
        sys.modules["floor_grammar"] = None           # import raises ImportError
        return self

    def __exit__(self, *exc):
        if self.old is None:
            sys.modules.pop("floor_grammar", None)
        else:
            sys.modules["floor_grammar"] = self.old


# --- 1. the table covers every kind ---------------------------------------------------

@test("table: every kind of ai-layouts' KINDS and farms is in FLOOR_OF or CLASSIC_KINDS; districts, roles, zones are known")
def _():
    src = (ROOT / "lua" / "ai-layouts.lua").read_text(encoding="utf-8")
    body = re.search(r"^KINDS\s*=\s*\{(.*?)\}", src, re.S | re.M).group(1)
    kinds = re.findall(r"'([a-z_]+)'", body)
    assert len(kinds) >= 15 and "bedrooms" in kinds and "garden" in kinds, kinds
    for k in kinds + ["farms"]:
        assert (k in MF.FLOOR_OF) != (k in MF.CLASSIC_KINDS), k
    assert {"farms", "landmark", "well", "way_in", "cistern"} <= MF.CLASSIC_KINDS
    for k, (dist, role, zone) in MF.FLOOR_OF.items():
        assert dist in masterplan.STACK or dist == "farms", (k, dist)
        assert dist in TAGS and zone in ("near", "mid", "far", "any"), (k, dist, zone)
        assert role in MF.ROLES[dist] or k == "workshops", (k, role)
    assert set(MF.ROLES) == set(masterplan.STACK)
    assert MF.ROLES == {"homes": ("common", "sleeping"), "halls": ("worship", "crypt"),
                        "industry": ("crafts", "forges", "kitchens"), "storage": ("stores",), "defence": ("guard",)}
    assert MF.FLOORS_V == 1
    # every kind masterplan gives a district agrees with the table (farms: classic)
    for k, dist in masterplan.DISTRICT_OF.items():
        assert (k in MF.CLASSIC_KINDS and dist == "farms") or MF.FLOOR_OF[k][0] == dist, k


@test("role_of: the table's rows; a workshops level by its first shop's group; classic and unknown kinds None")
def _():
    want = {"dining": ("homes", "common", "near"), "suites": ("homes", "common", "near"),
            "tavern": ("homes", "common", "mid"), "hospital": ("homes", "common", "far"),
            "bedrooms": ("homes", "sleeping", "any"), "temple": ("halls", "worship", "far"),
            "memorial": ("halls", "worship", "far"), "library": ("halls", "worship", "mid"),
            "garden": ("halls", "worship", "mid"), "tombs": ("halls", "crypt", "far"),
            "storage": ("storage", "stores", "near"), "barracks": ("defence", "guard", "near"),
            "archery": ("defence", "guard", "far"), "jail": ("defence", "guard", "far")}
    for k, row in want.items():
        assert MF.role_of(k) == row and MF.role_of(k, start(k)) == row, k
    for shop, role in (("Masons", "crafts"), ("Loom", "crafts"), ("Ashery", "crafts"), ("Smelter", "forges"),
                       ("MetalsmithsForge", "forges"), ("Kitchen", "kitchens"), ("Still", "kitchens")):
        assert MF.role_of("workshops", start("workshops", shops=[shop, "Smelter"])) == ("industry", role, "mid"), shop
    assert MF.role_of("workshops") == ("industry", "crafts", "mid")
    assert MF.role_of("workshops", start("workshops", shops=["Nonsuch"])) == ("industry", "crafts", "mid")
    for shop, g in WORKSHOP_GROUPS.items():
        assert g in MF.ROLE_OF_GROUP, (shop, g)
    for k in ("farms", "landmark", "well", "way_in", "cistern", "keep", "", None, 7, ["x"]):
        assert MF.role_of(k) is None, k


# --- 2. ensure ------------------------------------------------------------------------

@test("ensure: no plan -> [] and nothing written; a plan drawn before option B gets its table, its districts untouched")
def _():
    m = Memory()
    assert MF.ensure(m, traits()) == [] and not m.atlas, m.atlas
    m = mem()
    before = copy.deepcopy(m.atlas)
    assert MF.ensure(m, traits(), profile()) == [] and m.atlas == before
    m.atlas["plan"] = {}
    assert MF.ensure(m, traits()) == [] and m.atlas["plan"] == {}
    m = drawn(traits(verticality=80), floors=False)
    p = m.atlas["plan"]
    was = json.dumps(p["districts"], sort_keys=True)
    rest = {k: copy.deepcopy(v) for k, v in p.items()}
    out = MF.ensure(m, traits(verticality=80), profile())
    assert len(out) == 1 and out[0].startswith("the floors were laid out: "), out
    assert "sleeping on " in out[0] and "kitchens on " in out[0] and "guard on " in out[0], out
    assert json.dumps(p["districts"], sort_keys=True) == was, "the districts byte for byte"
    assert {k: v for k, v in p.items() if k != "floors"} == rest, "nothing else of the plan moved"
    f = p["floors"]
    assert f["v"] == 1 and f["vertical"] == "deep" and f["placed"] == {}, f
    assert set(f["roles"]) == {"common", "sleeping", "worship", "crypt", "crafts", "forges", "kitchens",
                               "stores", "guard"}, set(f["roles"])
    for r in f["roles"].values():
        d = district(m, r["district"])
        assert r["band"] == [d["lo"], d["hi"]] and sorted(r["elevs"]) == list(range(d["lo"], d["hi"] + 1)), r
    json.dumps(f)                                         # the atlas is saved as JSON
    again = copy.deepcopy(p)
    assert MF.ensure(m, traits(verticality=80), profile()) == [] and p == again, "a second call changes nothing"
    # (a save's round trip: the same table, nothing redone)
    m.atlas = json.loads(json.dumps(m.atlas))
    assert MF.ensure(m, traits(verticality=80)) == [] and m.atlas["plan"] == again


@test("ensure: a grown band redoes that district's lists and leaves `placed` alone; a newer table is not touched")
def _():
    m = drawn(traits(verticality=80))
    p = m.atlas["plan"]
    f = p["floors"]
    f["placed"]["57"] = {"floor": 3, "role": "sleeping", "elevation": 50}
    before = copy.deepcopy(f["roles"])
    d = district(m, "homes")
    d["lo"] -= 2                                         # (masterplan.note_result: the district grew)
    was = json.dumps(p["districts"], sort_keys=True)
    out = MF.ensure(m, traits(verticality=80))
    assert len(out) == 1 and out[0].startswith("the floors were laid out again: "), out
    assert "common on" in out[0] and "sleeping on" in out[0] and "worship" not in out[0], out
    assert json.dumps(p["districts"], sort_keys=True) == was
    for role in ("common", "sleeping"):
        r = f["roles"][role]
        assert r["band"] == [d["lo"], d["hi"]] and len(r["elevs"]) == len(before[role]["elevs"]) + 2, r
    for role in before:
        if role not in ("common", "sleeping"):
            assert f["roles"][role] == before[role], role
    assert f["placed"] == {"57": {"floor": 3, "role": "sleeping", "elevation": 50}}
    assert MF.ensure(m, traits(verticality=80)) == []
    # a table of an older / broken shape is made again, its placed kept
    p["floors"] = {"v": 0, "placed": {"9": {"floor": 1, "role": "stores", "elevation": 44}}}
    assert MF.ensure(m, traits())[0].startswith("the floors were laid out: ")
    assert p["floors"]["v"] == 1 and "9" in p["floors"]["placed"]
    # a newer version's table: left as it is (the hint still works, from the bands)
    p["floors"] = {"v": 2, "something": "new"}
    assert MF.ensure(m, traits()) == [] and p["floors"] == {"v": 2, "something": "new"}
    assert isinstance(MF.hint(m, start("bedrooms"), {}, traits(), CFG), dict)


@test("ensure never raises on a junk plan; masterplan.ensure returns the plan's line and the floors' line")
def _():
    for junk in ({"districts": "x"}, {"districts": [1, None, {"kind": "homes"}]},
                 {"districts": [{"kind": "homes", "lo": 5, "hi": 2}]},
                 {"districts": [{"kind": "homes", "lo": "a", "hi": True}], "floors": 7},
                 {"districts": [{"kind": ["x"], "lo": 1, "hi": 2}]}):
        m = Memory()
        m.atlas = {"plan": copy.deepcopy(junk)}
        assert MF.ensure(m, traits()) == [], junk
        assert MF.lines(m) == [] and MF.elevs_for(m, "bedrooms", None, traits(), None, CFG) == []
    m = Memory()
    m.atlas = None
    assert MF.ensure(m, None) == [] and MF.ensure(None, None) == []
    # masterplan.ensure: a new plan gets its table right after it is drawn
    m = mem()
    out = masterplan.ensure(STATE, m, SITE, traits(), profile())
    assert len(out) == 2 and out[0].startswith("the master plan was drawn: ") \
        and out[1].startswith("the floors were laid out: "), out
    assert m.atlas["plan"]["floors"]["v"] == 1
    assert masterplan.ensure(STATE, m, SITE, traits(), profile()) == []
    # a plan drawn before option B: its table on the next call, also with no site this time
    m = drawn(floors=False)
    was = json.dumps(m.atlas["plan"]["districts"], sort_keys=True)
    out = masterplan.ensure(STATE, m, None, traits(), profile())
    assert len(out) == 1 and out[0].startswith("the floors were laid out: "), out
    assert json.dumps(m.atlas["plan"]["districts"], sort_keys=True) == was
    # no plan and no site: nothing
    m = mem()
    assert masterplan.ensure(STATE, m, None, traits(), profile()) == [] and "plan" not in m.atlas


# --- 3. roles to elevations -----------------------------------------------------------

@test("roles: a flat plan gives every role its district's levels as they are; others turn them by the role's place")
def _():
    for vert, word in ((-100, "flat"), (0, "balanced"), (60, "deep"), (120, "deep")):
        for fort in (0, 50):
            t = traits(verticality=vert, fortification=fort)
            m = drawn(t)
            p = m.atlas["plan"]
            assert p["vertical"] == word and p["floors"]["vertical"] == word, (vert, p["vertical"])
            roles = p["floors"]["roles"]
            for dist, names in MF.ROLES.items():
                d = district(m, dist)
                at = 0
                if d is None:
                    assert dist == "defence" and fort < 30
                    d, at, dist = district(m, "halls"), 2, "halls"      # after the halls' own two roles
                lv = levels_of(d)
                for i, role in enumerate(names):
                    k = 0 if word == "flat" else (at + i) % len(lv)
                    assert roles[role] == {"district": dist, "elevs": lv[k:] + lv[:k], "band": [d["lo"], d["hi"]]}, \
                        (vert, fort, role, roles[role], lv)
            assert "farms" not in {r["district"] for r in roles.values()}
    # by hand: a band 9..11 with its target 10; 20..23 with its target 22
    m = Memory()
    m.atlas = {"plan": {"vertical": "deep", "spine": {"x": 5, "y": 6}, "districts": [
        {"kind": "homes", "name": "the Hearths", "lo": 9, "hi": 11, "target": 10},
        {"kind": "halls", "name": "the Halls", "lo": 20, "hi": 23, "target": 22},
        {"kind": "industry", "name": "the Forges", "lo": 1, "hi": 2, "target": 2},
        {"kind": "storage", "name": "the Vaults", "lo": 4, "hi": 4}]}}
    MF.ensure(m, traits())
    r = {k: v["elevs"] for k, v in m.atlas["plan"]["floors"]["roles"].items()}
    assert r == {"common": [10, 11, 9], "sleeping": [11, 9, 10],
                 "worship": [22, 23, 21, 20], "crypt": [23, 21, 20, 22], "guard": [21, 20, 22, 23],
                 "crafts": [2, 1], "forges": [1, 2], "kitchens": [2, 1], "stores": [4]}, r
    m.atlas["plan"]["vertical"] = "flat"
    assert MF.ensure(m, traits())[0].startswith("the floors were laid out again")
    r = {k: v["elevs"] for k, v in m.atlas["plan"]["floors"]["roles"].items()}
    assert r["common"] == r["sleeping"] == [10, 11, 9] and r["crypt"] == r["guard"] == [22, 23, 21, 20], r


@test("elevs_for: the role's list; full floors for the tag last; floor_elevs_max; a table not yet made")
def _():
    m = drawn(traits(verticality=120))
    roles = m.atlas["plan"]["floors"]["roles"]
    assert len(roles["sleeping"]["elevs"]) == 4, roles["sleeping"]
    for kind, role in (("bedrooms", "sleeping"), ("dining", "common"), ("tombs", "crypt"), ("storage", "stores"),
                       ("temple", "worship"), ("jail", "guard")):
        assert MF.elevs_for(m, kind, start(kind), traits(verticality=120), None, CFG) == roles[role]["elevs"], kind
    assert MF.elevs_for(m, "workshops", start("workshops", shops=["Smelter"]), traits(), None, CFG) \
        == roles["forges"]["elevs"]
    assert MF.elevs_for(m, "workshops", start("workshops", shops=["Still"]), traits(), None, CFG) \
        == roles["kitchens"]["elevs"]
    sl = roles["sleeping"]["elevs"]
    assert MF.elevs_for(m, "bedrooms", None, traits(), None, {"floor_elevs_max": 2}) == sl[:2]
    assert MF.elevs_for(m, "bedrooms", None, traits(), None, {"floor_elevs_max": 99}) == sl[:6]
    assert MF.elevs_for(m, "bedrooms", None, traits(), None, {"floor_elevs_max": "x"}) == sl[:4]
    assert MF.elevs_for(m, "bedrooms", None, traits(), None, {"floor_elevs_max": 0}) == sl[:1]
    # the report: floors full for the homes go last (in their order); another tag's does not count
    rep = {"v": 1, "list": [{"id": 1, "elevation": sl[0], "stair": {"x": 100, "y": 100}, "full": ["homes"]},
                            {"id": 2, "elevation": sl[2], "full": ["homes", "industry"]},
                            {"id": 3, "elevation": sl[1], "full": ["industry"]}, "junk", {"full": ["homes"]}]}
    assert MF.elevs_for(m, "bedrooms", None, traits(), rep, CFG) == [sl[1], sl[3], sl[0], sl[2]]
    assert MF.elevs_for(m, "bedrooms", None, traits(), rep, {"floor_elevs_max": 2}) == [sl[1], sl[3]]
    # a floor on another stair is another floor
    rep["list"][0]["stair"] = {"x": 3, "y": 3}
    assert MF.elevs_for(m, "bedrooms", None, traits(), rep, CFG) == [sl[0], sl[1], sl[3], sl[2]]
    for junk in ({"error": "boom", "list": rep["list"]}, {"list": "x"}, "x", 7, []):
        assert MF.elevs_for(m, "bedrooms", None, traits(), junk, CFG) == sl, junk
    # no table yet (a plan drawn before option B, ensure not yet run): the same lists, nothing written
    m2 = drawn(traits(verticality=120), floors=False)
    for kind in ("bedrooms", "dining", "tombs", "jail", "storage"):
        assert MF.elevs_for(m2, kind, None, traits(), None, CFG) == MF.elevs_for(m, kind, None, traits(), None, CFG)
    assert "floors" not in m2.atlas["plan"]
    # a band grown since ensure last ran: the list follows the district at once
    d = district(m, "storage")
    d["hi"] += 1
    assert set(MF.elevs_for(m, "storage", None, traits(), None, {"floor_elevs_max": 6})) \
        == set(range(d["lo"], d["hi"] + 1))
    assert MF.elevs_for(m, "farms", None, traits(), None, CFG) == []
    assert MF.elevs_for(Memory(), "bedrooms", None, traits(), None, CFG) == []
    assert MF.elevs_for(None, None, "x", None, 3, None) == []


@test("elevs_for: a Deep mine (Surface -80) offers no floor above its ceiling")
def _():
    t = traits(verticality=120, surface=-100)
    m = mem()
    m.atlas["entrances"]["100,101,160"] = {"kind": "surface", "elevation": 60}
    site = dict(SITE, soil=[58, 59, 60])
    m = drawn(t, site=site, m=m)
    assert m.atlas["plan"]["ceiling"] == 59
    for d in m.atlas["plan"]["districts"]:               # (E's: a district grown up to the surface)
        if d["kind"] == "halls":
            d["lo"], d["hi"], d["target"] = 58, 61, 60
    MF.ensure(m, t)
    assert m.atlas["plan"]["floors"]["roles"]["worship"]["elevs"] == [60, 61, 59, 58]
    assert MF.elevs_for(m, "temple", start("temple"), t, None, CFG) == [59, 58]
    assert MF.elevs_for(m, "tombs", start("tombs"), t, None, CFG) == [59, 58]
    assert MF.elevs_for(m, "temple", start("temple"), traits(verticality=120), None, CFG) == [60, 61, 59, 58]
    # with the classic hint's own (cut) band on the action: still the role's list, under the ceiling
    a = start("temple")
    a["plan"] = masterplan.hint(m, "temple", traits=t)
    assert a["plan"]["elev_hi"] == 59
    assert MF.elevs_for(m, "temple", a, t, None, CFG) == [59, 58]
    h = MF.hint(m, a, {}, t, CFG)
    assert h["elevs"] == [59, 58] and h["tag"] == "halls", h
    # nothing under the ceiling at all: nothing said (the builder's own default)
    for d in m.atlas["plan"]["districts"]:
        if d["kind"] == "halls":
            d["lo"], d["hi"], d["target"] = 60, 61, 60
    assert MF.elevs_for(m, "temple", start("temple"), t, None, CFG) == []
    assert MF.hint(m, start("temple"), {}, t, CFG) is None


# --- 4. the customs --------------------------------------------------------------------

def custom_fort(**tr):
    """A plan with a defence district, the way in known (the gate band needs
    the surface), and the fort's sliders."""
    t = traits(fortification=40, **tr)
    m = drawn(t, m=mem(entrance="100,60,160", elevation=60))
    return m, t


def with_customs(m, t, kind, **kw) -> dict:
    a = start(kind, **kw)
    planner_building.apply_customs(a, m, t, profile_from(t, m.culture or new_history()), 40)
    return a


@test("hint: a custom's band gives the floors (cells, deep_hall, market_gate, gate_barracks) and the tag follows the district")
def _():
    # cells: bedrooms beside the temple (the halls' band)
    m, t = custom_fort(piety=100, welfare=40)
    a = with_customs(m, t, "bedrooms", rooms=6)
    assert a["customs"] == ["cells"], a
    halls = district(m, "halls")
    h = MF.hint(m, a, {}, t, CFG)
    assert h["tag"] == "halls" and h["zone"] == "any", h
    assert set(h["elevs"]) <= set(range(halls["lo"], halls["hi"] + 1)) and h["elevs"][0] == a["plan"]["elev_target"], h
    assert h["elevs"] == sorted(range(halls["lo"], halls["hi"] + 1),
                                key=lambda e: (abs(e - a["plan"]["elev_target"]), -e))[:4]
    in_ranges(h)
    # deep_hall: the dining hall in the deeps (the industry's band)
    m, t = custom_fort(mining=100, verticality=60)
    a = with_customs(m, t, "dining", tables=4)
    assert a["customs"] == ["deep_hall"], a
    ind = district(m, "industry")
    h = MF.hint(m, a, {}, t, CFG)
    assert h["tag"] == "industry" and h["zone"] == "near", h
    assert set(h["elevs"]) <= set(range(ind["lo"], ind["hi"] + 1)) and h["elevs"][0] == a["plan"]["elev_target"], h
    assert "group" not in h
    # market_gate: the tavern in the gate band (57 down to 55), still a level of the homes
    m, t = custom_fort(trade=80, outsiders=50)
    a = with_customs(m, t, "tavern")
    assert "market_gate" in a["customs"] and (a["plan"]["elev_lo"], a["plan"]["elev_hi"]) == (55, 57), a
    h = MF.hint(m, a, {}, t, CFG)
    assert h["elevs"] == [57, 56, 55] and h["tag"] == "homes" and h["zone"] == "mid", h
    assert h["dirs"][-1] == "north" or "north" in h["dirs"], h         # the way in is north of the stair
    # gate_barracks: barracks and ranges in the gate band (58 down to 56), the defence's
    m, t = custom_fort(militarism=100)
    for kind, zone in (("barracks", "near"), ("archery", "far")):
        a = with_customs(m, t, kind)
        assert "gate_barracks" in a["customs"] and (a["plan"]["elev_lo"], a["plan"]["elev_hi"]) == (56, 58), a
        h = MF.hint(m, a, {}, t, CFG)
        assert h["elevs"] == [58, 57, 56] and h["tag"] == "defence" and h["zone"] == zone, (kind, h)
        in_ranges(h)
    # the same fort's bedrooms: no custom, the district's own band on the action -> the role's list
    a = with_customs(m, t, "bedrooms", rooms=6)
    assert "customs" not in a and a["plan"]["district"], a
    h = MF.hint(m, a, {}, t, CFG)
    assert h["elevs"] == m.atlas["plan"]["floors"]["roles"]["sleeping"]["elevs"][:4] and h["tag"] == "homes", h
    # a set piece's place: the great hall among the halls
    a = with_customs(m, t, "dining", set_piece="great hall")
    h = MF.hint(m, a, {}, t, CFG)
    halls = district(m, "halls")
    assert h["tag"] == "halls" and set(h["elevs"]) <= set(range(halls["lo"], halls["hi"] + 1)), h


@test("hint: False for a level by the fields, join false, a landmark's level and a classic kind; None without a plan")
def _():
    t = traits(agriculture=80)
    m = drawn(t, site=dict(SITE, soil=[50]))
    assert customs.has(t, "field_hall") and customs.has(t, "field_kitchens")
    a = with_customs(m, t, "dining", tables=4)
    assert a["customs"] == ["field_hall"], a
    assert MF.hint(m, a, {}, t, CFG) is False
    a = with_customs(m, t, "workshops", shops=["Kitchen", "Still"])
    assert a["customs"] == ["field_kitchens"], a
    assert MF.hint(m, a, {}, t, CFG) is False
    a = with_customs(m, t, "workshops", shops=["Masons"])          # no food shop: an ordinary level
    assert isinstance(MF.hint(m, a, {}, t, CFG), dict)
    m = drawn()
    assert MF.hint(m, start("bedrooms", join=False), {}, traits(), CFG) is False
    assert isinstance(MF.hint(m, start("workshops", shops=["Loom"], join="band"), {}, traits(), CFG), dict)
    assert MF.hint(m, start("memorial", landmark=3), {}, traits(), CFG) is False
    assert MF.hint(m, start("dining", landmark="L1"), {}, traits(), CFG) is False
    for kind in ("farms", "landmark", "well", "way_in", "cistern", "keep", None, 5):
        assert MF.hint(m, start(kind), {}, traits(), CFG) is False, kind
        assert MF.hint(Memory(), start(kind), {}, traits(), CFG) is False, kind
    # no master plan yet: say nothing (the builder's own default)
    for mm in (Memory(), mem()):
        for kind in MF.FLOOR_OF:
            assert MF.hint(mm, start(kind), {}, traits(), CFG) is None, kind
        assert "plan" not in (mm.atlas or {})
    # never raises
    for args in ((None, None, None, None, None), (m, "x", 3, "t", 5), (m, {}, None, None, None),
                 (m, {"kind": "bedrooms", "plan": "x", "customs": 7, "style": 3}, [], [], []),
                 (m, {"kind": "workshops", "shops": [None], "plan": {"elev_lo": "a", "spine": 9, "dirs": 4}}, {}, {}, {})):
        r = MF.hint(*args)
        assert r is None or r is False or isinstance(r, dict), args


@test("hint: a district a custom names is missing, a plan with no such district, junk bands: the fallbacks")
def _():
    m = drawn()
    p = m.atlas["plan"]
    # the action's plan names a district the plan no longer has: the kind's own tag, the plan's band
    a = start("bedrooms", plan={"elev_lo": 40, "elev_hi": 41, "elev_target": 41, "district": "the Gone Halls"})
    h = MF.hint(m, a, {}, traits(), CFG)
    assert h["tag"] == "homes" and h["elevs"] == [41, 40], h
    # the kind's district is gone from the plan: the action's band, else nothing to offer
    p["districts"] = [d for d in p["districts"] if d["kind"] != "storage"]
    assert MF.hint(m, start("storage"), {}, traits(), CFG) is None
    h = MF.hint(m, start("storage", plan={"elev_lo": 44, "elev_hi": 45}), {}, traits(), CFG)
    assert h["tag"] == "storage" and h["elevs"] == [44, 45] and h["zone"] == "near", h
    # no defence district: the guard's floors among the halls, dealt after the halls' own roles
    assert district(m, "defence") is None
    halls = district(m, "halls")
    lv = levels_of(halls)
    h = MF.hint(m, start("barracks"), {}, traits(), CFG)
    assert h["tag"] == "halls" and h["zone"] == "near" and h["elevs"] == (lv[2 % len(lv):] + lv[:2 % len(lv)])[:4], h
    # a junk band on the action is not followed
    for pl in ({"elev_lo": 9, "elev_hi": 3}, {"elev_lo": True, "elev_hi": 4}, {"elev_lo": "1", "elev_hi": 4}):
        h = MF.hint(m, start("bedrooms", plan=pl), {}, traits(), CFG)
        assert h["elevs"] == p["floors"]["roles"]["sleeping"]["elevs"][:4], (pl, h)
    # a band off the scale is cut to the bridge's range
    h = MF.hint(m, start("bedrooms", plan={"elev_lo": 399, "elev_hi": 900, "elev_target": 420}), {}, traits(), CFG)
    assert h["elevs"] == [400, 399], h


# --- 5. the deep band ------------------------------------------------------------------

@test("hint: the Deep mine's deep band: the floors inside it, nearest its target first; the action's spine")
def _():
    t = traits(verticality=120)
    m = drawn(t)
    ind = district(m, "industry")
    a = start("workshops", shops=["Smelter"])
    a["plan"] = masterplan.hint(m, "workshops", traits=t, action=a)
    band = masterplan.deep_band(m, "workshops", -28, -50)
    assert band and band["deep"] is True and (band["elev_lo"], band["elev_hi"], band["elev_target"]) == (-33, -28, -28)
    a["plan"].update(band)                               # (as planner_descent does)
    a["plan"]["spine"] = {"x": 77, "y": 88}
    h = MF.hint(m, a, {}, t, CFG)
    assert h["elevs"] == [-28, -29, -30, -31] and all(-33 <= e <= -28 for e in h["elevs"]), h
    assert h["spine"] == {"x": 77, "y": 88} and h["tag"] == "industry" and h["group"] == "smithing", h
    assert MF.hint(m, a, {}, t, {"floor_elevs_max": 6})["elevs"] == [-28, -29, -30, -31, -32, -33]
    in_ranges(h)
    # the band's own target leads (the level used least)
    a["plan"]["elev_target"] = -30
    assert MF.hint(m, a, {}, t, CFG)["elevs"] == [-30, -29, -31, -28]
    # a deep band that happens to equal the district's band is still the deep band
    a["plan"].update({"elev_lo": ind["lo"], "elev_hi": ind["hi"], "elev_target": ind["lo"], "deep": True})
    assert MF.hint(m, a, {}, t, CFG)["elevs"][0] == ind["lo"]
    # full floors of the deep band go last too
    a["plan"].update(band)
    rep = {"list": [{"elevation": -28, "full": ["industry"], "stair": {"x": 77, "y": 88}}]}
    assert MF.hint(m, a, {"floors": rep}, t, CFG)["elevs"] == [-29, -30, -31, -32]


# --- 6. the grammar; the bridge's ranges ----------------------------------------------

@test("hint: floor_grammar's keys are merged in (called as the contract says); none importable: the six keys only")
def _():
    t = traits(fortification=75)
    m = drawn(t, layout="rings")
    m.culture["quirks"] = {}
    a = start("workshops", shops=["Masons", "Smelter"], style={"hall": "plain", "grand": True}, urgent=True)
    cfg = {"floor_elevs_max": 3, "floor_gap": 2}
    with StandIn(extra={"tag": "evil", "elevs": [999], "zone": "x", "group": "y", "spine": 1, "dirs": 2}) as g:
        h = MF.hint(m, a, {}, t, cfg)
        assert len(g.calls) == 1, g.calls
        c = g.calls[0]
        assert c["traits"] is t and c["style"] == a["style"] and c["cfg"] is cfg, c
        assert c["pattern"] == "rings" and c["seed"] == "Test#1" and c["doors"] == "fortified", c
        assert c["quirks"] == frozenset() and isinstance(c["quirks"], frozenset), c
        assert c["customs"] == frozenset(customs.active(t)) and isinstance(c["customs"], frozenset), c
        assert c["language"] is False and c["grand"] is True and c["urgent"] is True, c
        assert set(c) == {"traits", "style", "cfg", "pattern", "quirks", "customs", "doors", "seed", "language",
                          "grand", "urgent"}, set(c)
        for k, v in StandIn.KEYS.items():
            assert h[k] == v, k
        roles = m.atlas["plan"]["floors"]["roles"]
        assert h["elevs"] == roles["crafts"]["elevs"][:3] and h["tag"] == "industry" and h["zone"] == "mid", h
        assert h["group"] == "crafts" and h["spine"] == {"x": 100, "y": 100}, h
        assert h["dirs"] == list(dict.fromkeys(district(m, "industry")["dirs"])), h
        assert set(h) == set(StandIn.KEYS) | OWN_KEYS, set(h)
        # the action's doors; a set piece is grand; a plain level is neither grand nor urgent
        b = start("dining", set_piece="great hall", plan={"elev_lo": 50, "elev_hi": 51, "doors": "open"})
        MF.hint(m, b, {}, t, cfg)
        c = g.calls[-1]
        assert c["doors"] == "open" and c["grand"] is True and c["urgent"] is False and c["style"] is None, c
        MF.hint(m, start("bedrooms"), {}, traits(), cfg)
        c = g.calls[-1]
        assert c["grand"] is False and c["doors"] in ("open", "doored"), c
        # the fort's earned rules and its design language
        import quirks
        rule_of = {r: q for q, e in quirks.data()["quirks"].items() for r in (e.get("rules") or [])}
        held = [rule_of[r] for r in ("narrow_ways", "symmetric") if r in rule_of]
        m.culture["quirks"] = {q: {} for q in held}
        m.culture["design"] = {"mode": "guided", "lang": {"name": "x", "symmetry": "mirror"}}
        MF.hint(m, start("bedrooms"), {}, traits(), cfg)
        c = g.calls[-1]
        assert c["quirks"] == frozenset(r for r in ("narrow_ways", "symmetric") if r in rule_of), c
        assert c["language"] is True, c
    with StandIn(fail=True):
        h = MF.hint(m, a, {}, t, cfg)                    # a grammar that raises: the six keys, no more
        assert set(h) == OWN_KEYS, h
    with NoGrammar():
        h = MF.hint(m, a, {}, t, cfg)
        assert set(h) == OWN_KEYS, h
        h = MF.hint(m, start("bedrooms"), {}, t, cfg)
        assert set(h) == {"elevs", "tag", "zone", "spine", "dirs"}, h
        p = m.atlas["plan"]
        p["spine"] = {"top": 60, "bottom": 30}           # a plan with no stair column known
        for d in p["districts"]:
            d.pop("dirs", None)
            d.pop("wings", None)
        h = MF.hint(m, start("bedrooms"), {}, t, cfg)
        assert set(h) == {"elevs", "tag", "zone"}, h


@test("hint: elevs, tag, group, zone, spine and dirs stay inside the bridge's ranges for 400 random forts")
def _():
    rng = random.Random(1105)
    sliders = ("verticality", "spacing", "grandeur", "fortification", "craftsmanship", "piety", "welfare", "trade",
               "outsiders", "militarism", "mining", "agriculture", "caution", "surface", "stockpile")
    kinds = sorted(MF.FLOOR_OF)
    shops = sorted(WORKSHOP_GROUPS) + ["Nonsuch"]
    said = {"dict": 0, "false": 0, "none": 0}
    with NoGrammar():
        for i in range(400):
            t = {k: rng.choice((-150, -100, -60, -40, 0, 30, 50, 80, 100, 150)) for k in sliders}
            top = rng.randint(-380, 395)
            depth = rng.randint(1, 60)
            site = {"stairs": [{"x": rng.randint(0, 999), "y": rng.randint(0, 999), "elev_top": top,
                                "elev_bottom": top - depth, "count": 5}],
                    "citizen_elevation": top - rng.randint(0, depth), "elevation_offset": -100,
                    "soil": [top - rng.randint(0, 6)] if rng.random() < 0.6 else []}
            m = mem(entrance=f"{rng.randint(0, 999)},{rng.randint(0, 999)},50" if rng.random() < 0.7 else None,
                    elevation=top if rng.random() < 0.7 else None)
            m.atlas["survey"]["layers"] = [{"name": "Cavern1", "z_top": top + 100 - depth - rng.randint(2, 30),
                                            "z_bottom": top - depth - 40}]
            prof = profile(layout=rng.choice(("grid", "rings", "branching", "stacked")))
            got = masterplan.ensure(STATE, m, site, t, prof)
            if got and rng.random() < 0.3:
                masterplan.new_era(m, 2, prof, t)
            if got and rng.random() < 0.3:
                d = rng.choice(m.atlas["plan"]["districts"])
                masterplan.note_stairwell(m, d["id"], rng.randint(0, 999), rng.randint(0, 999))
            rep = None
            if rng.random() < 0.5:
                rep = {"v": 1, "list": [{"id": n, "elevation": rng.randint(top - depth, top),
                                         "full": rng.sample(sorted(TAGS), rng.randint(0, 3))} for n in range(6)]}
            for _ in range(6):
                kind = rng.choice(kinds)
                a = start(kind)
                if kind == "workshops":
                    a["shops"] = rng.sample(shops, rng.randint(1, 3))
                if rng.random() < 0.7:
                    planner_building.apply_customs(a, m, t, profile_from(t, m.culture), rng.randint(5, 200),
                                                   urgent=rng.random() < 0.3)
                if rng.random() < 0.1:
                    a["plan"] = {"elev_lo": rng.randint(-500, 0), "elev_hi": rng.randint(0, 500),
                                 "spine": {"x": rng.randint(-5, 1005), "y": rng.randint(-5, 1005)},
                                 "dirs": ["up", "north", "north", 3]}
                h = MF.hint(m, a, {"floors": rep} if rep else {}, t, {"floor_elevs_max": rng.choice((1, 4, 6, 50))})
                if h is None:
                    said["none"] += 1
                elif h is False:
                    said["false"] += 1
                    assert set(a.get("customs") or []) & {"field_hall", "field_kitchens"}, a
                else:
                    said["dict"] += 1
                    assert set(h) <= OWN_KEYS, h
                    in_ranges(h)
                    ceil = masterplan.ceiling(m, t)
                    assert ceil is None or max(h["elevs"]) <= ceil, (h, ceil)
                    assert ("group" in h) == (kind == "workshops" and a["shops"][0] in WORKSHOP_GROUPS), (a, h)
                    json.dumps(h)
    assert said["dict"] > 1000 and said["none"] > 20, said


# --- 7. note_result and lines ----------------------------------------------------------

def answer(pid, floor_id, el, new=False, **kw) -> dict:
    return {"ok": True, "project_id": pid, "kind": "bedrooms", "z": 150, "elevation": el,
            "floor": {"id": floor_id, "elevation": el, "stair": {"x": 100, "y": 100}, "arm": "east", "side": "north",
                      "u": 13, "hall_new": 39, "new_floor": new, "units": 2}, **kw}


@test("note_result: the level kept in `placed` (the newest 80); a line only for a new floor's hall; junk never raises")
def _():
    m = drawn()
    placed = m.atlas["plan"]["floors"]["placed"]
    line = MF.note_result(m, start("bedrooms", rooms=6), answer(57, 3, 50, new=True))
    assert line == "a main hall was begun on elevation 50 for the homes", line
    assert placed == {"57": {"floor": 3, "role": "sleeping", "elevation": 50}}, placed
    assert MF.note_result(m, start("workshops", shops=["Smelter"]), answer(58, 3, 50)) is None
    assert placed["58"] == {"floor": 3, "role": "forges", "elevation": 50}
    # the tag the hint carried is the one said
    a = start("bedrooms", floor={"elevs": [61], "tag": "halls"})
    assert MF.note_result(m, a, answer(59, 4, 61, new=True)) == "a main hall was begun on elevation 61 for the halls"
    assert MF.note_result(m, start("jail"), answer(60, 5, 62, new=True)).endswith("for the halls"), "no defence district"
    # nothing kept: a refusal, the classic way, a dry run, another action, no plan
    n = len(placed)
    for a, r in ((start("bedrooms"), {"ok": False, "floor": {"id": 1, "elevation": 3, "new_floor": True}}),
                 (start("bedrooms"), {"ok": True, "project_id": 70, "elevation": 50, "not_on_floor": "floor 3: no room"}),
                 (start("bedrooms"), {"ok": True, "project_id": 71, "floor": False}),
                 (start("bedrooms", dry_run=True), answer(72, 3, 50, new=True)),
                 (start("bedrooms"), answer(73, 3, 50, new=True, dry_run=True)),
                 ({"type": "farm_plots"}, answer(74, 3, 50, new=True)),
                 (None, answer(75, 3, 50)), (start("bedrooms"), None), ("x", "y"), (start("bedrooms"), [1]),
                 (start("bedrooms"), {"ok": True, "project_id": {"a": 1}, "floor": {"id": []}})):
        assert MF.note_result(m, a, r) is None, (a, r)
    assert len(placed) == n, placed
    assert MF.note_result(Memory(), start("bedrooms"), answer(1, 1, 5, new=True)) is None
    assert MF.note_result(None, start("bedrooms"), answer(1, 1, 5, new=True)) is None
    # the newest 80; a project noted again moves to the end
    for i in range(100, 200):
        MF.note_result(m, start("storage"), answer(i, 9, 44))
    assert len(placed) == 80 and list(placed)[0] == "120" and list(placed)[-1] == "199", list(placed)[:3]
    MF.note_result(m, start("storage"), answer(120, 9, 45))
    assert len(placed) == 80 and list(placed)[-1] == "120" and placed["120"]["elevation"] == 45
    # a plan with no table yet: made here, its districts untouched
    m = drawn(floors=False)
    was = json.dumps(m.atlas["plan"]["districts"], sort_keys=True)
    assert MF.note_result(m, start("dining"), answer(5, 1, 50)) is None
    assert m.atlas["plan"]["floors"]["placed"] == {"5": {"floor": 1, "role": "common", "elevation": 50}}
    assert json.dumps(m.atlas["plan"]["districts"], sort_keys=True) == was


@test("masterplan.note_result: the floors' line when the district has none of its own; the district's own wins")
def _():
    m = drawn()
    a = start("bedrooms", rooms=6)
    a["plan"] = masterplan.hint(m, "bedrooms")
    line = masterplan.note_result(m, a, answer(57, 3, 50, new=True), STATE)
    assert line.startswith("the first level of ") and line.endswith("was begun at elevation 50"), line
    assert m.atlas["plan"]["floors"]["placed"]["57"]["floor"] == 3
    line = masterplan.note_result(m, a, answer(58, 4, 51, new=True), STATE)
    assert line == "a main hall was begun on elevation 51 for the homes", line
    assert len(district(m, "homes")["levels"]) == 2
    assert masterplan.note_result(m, a, answer(59, 4, 51), STATE) is None
    # a level without the classic hint (a mood's workshop): the plan's note says nothing, the floor is still kept
    b = start("workshops", shops=["Masons"])
    assert masterplan.note_result(m, b, answer(60, 6, 44, new=True), STATE) \
        == "a main hall was begun on elevation 44 for the workshops"
    assert m.atlas["plan"]["floors"]["placed"]["60"]["role"] == "crafts"
    # no floor in the answer: exactly as before
    assert masterplan.note_result(m, a, {"ok": True, "project_id": 61, "elevation": 50}, STATE) is None
    assert "61" not in m.atlas["plan"]["floors"]["placed"]
    # a district grown by misses: the next ensure redoes its floors
    d = district(m, "homes")
    lo0, hi0 = d["lo"], d["hi"]
    for i in range(masterplan.GROW_AFTER_MISSES):
        line = masterplan.note_result(m, a, {"ok": True, "project_id": 70 + i, "elevation": 20}, STATE)
    assert " grew to elevations " in line and (d["lo"], d["hi"]) != (lo0, hi0), line
    out = masterplan.ensure(STATE, m, None, traits(), profile())
    assert len(out) == 1 and out[0].startswith("the floors were laid out again: "), out
    assert m.atlas["plan"]["floors"]["roles"]["sleeping"]["band"] == [d["lo"], d["hi"]]


@test("lines: the floors in words, with the report's counts and a line a floor; [] without a table; junk never raises")
def _():
    m = drawn(floors=False)
    assert MF.lines(m) == [] and MF.lines(Memory()) == [] and MF.lines(None) == []
    before = masterplan.lines(m)
    MF.ensure(m, traits())
    roles = m.atlas["plan"]["floors"]["roles"]
    out = MF.lines(m)
    assert len(out) == 1 and out[0].startswith("floors: common on "), out
    sl = ", ".join(str(e) for e in roles["sleeping"]["elevs"][:3])
    assert f"sleeping on {sl}" in out[0] and "; worship on " in out[0] and "(" not in out[0], out
    order = [w.split(" on ")[0] for w in out[0][len("floors: "):].split("; ")]
    assert order == ["common", "sleeping", "worship", "crypt", "crafts", "forges", "kitchens", "stores", "guard"], order
    MF.note_result(m, start("bedrooms"), answer(57, 3, 50, new=True))
    MF.note_result(m, start("dining"), answer(58, 3, 50))
    MF.note_result(m, start("storage"), answer(59, 4, 44, new=True))
    assert MF.lines(m)[0].endswith(" (2 laid out, 3 levels)"), MF.lines(m)
    rep = {"v": 1, "mode": "hallway", "count": 3, "rooms": 41, "hall_tiles": 150, "fallbacks": 1, "list": [
        {"id": 3, "elevation": 50, "z": 150, "stair": {"x": 100, "y": 100}, "hub": "dug", "no_hall": False,
         "width": 3, "rooms": 7, "hall": 69, "tags": ["homes", "industry"], "full": ["homes"],
         "arms": [{"dir": "east", "len": 23, "runs": 1, "tag": "homes", "slots": 7}]},
        {"id": 4, "elevation": 44, "rooms": 1, "tags": ["storage"], "full": [], "arms": []},
        {"id": 5, "elevation": 43, "no_hall": True, "arms": []}, "junk", {"id": 6}]}
    out = MF.lines(m, rep)
    assert out[0].endswith(" (3 laid out, 41 rooms, 1 level placed the old way)"), out[0]
    assert out[1] == "elevation 50: 7 rooms (homes, industry), halls east, full for homes", out[1]
    assert out[2] == "elevation 44: 1 room (storage)" and out[3] == "elevation 43: no main hall can start here", out
    assert len(out) == 4 and len(MF.lines(m, rep, limit=2)) == 2 and MF.lines(m, rep, limit=0) == []
    assert MF.lines(m, {"error": "boom", "count": 9})[0].endswith(" (2 laid out, 3 levels)")
    for junk in ("x", 7, [], {"count": "a", "list": 5}, {"list": [None, {"elevation": "x"}]}):
        assert len(MF.lines(m, junk)) == 1, junk
    assert MF.lines(m, rep, limit="x") == []
    # masterplan.lines: its own lines as before, then the floors, inside its limit
    after = masterplan.lines(m)
    assert after[:len(before)] == before and after[len(before):] == MF.lines(m), after
    assert masterplan.lines(m, limit=len(before)) == before
    assert len(masterplan.lines(m, limit=3)) == 3


# --- 8. the classic hint and the planner are as they were --------------------------------

@test("unchanged: masterplan.hint and variety give the same with and without the table; DISTRICT_OF as it was")
def _():
    assert masterplan.DISTRICT_OF == {
        "bedrooms": "homes", "dining": "homes", "tavern": "homes", "hospital": "homes",
        "temple": "halls", "library": "halls", "memorial": "halls", "garden": "halls", "tombs": "halls",
        "storage": "storage", "workshops": "industry", "farms": "farms", "barracks": "defence", "archery": "defence"}
    for t in (traits(), traits(verticality=120, fortification=80, grandeur=70), traits(verticality=-100, spacing=60),
              traits(fortification=40, militarism=100, trade=80, outsiders=50)):
        a = drawn(t, m=mem(entrance="100,60,160", elevation=60), floors=False)
        b = drawn(t, m=mem(entrance="100,60,160", elevation=60))
        MF.note_result(b, start("bedrooms"), answer(57, 3, 50, new=True))
        assert "floors" not in a.atlas["plan"] and b.atlas["plan"]["floors"]["placed"]
        prof = profile_from(t, a.culture)
        for kind in list(masterplan.DISTRICT_OF) + ["suites", "jail"]:
            for kw in ({}, {"traits": t, "profile": prof, "citizens": 40}, {"slot": "great hall", "traits": t}):
                assert masterplan.hint(a, kind, **kw) == masterplan.hint(b, kind, **kw), (kind, kw)
            assert masterplan.variety(a, kind) == masterplan.variety(b, kind), kind
        assert masterplan.brief(a) == masterplan.brief(b)
        assert masterplan.camera_districts(a) == masterplan.camera_districts(b)
        assert {k: v for k, v in b.atlas["plan"].items() if k != "floors"} == a.atlas["plan"]


@test("unchanged: a full planner.plan() on the test fort proposes the same with and without the table")
def _():
    def props(m, s):
        out, notes = plan(copy.deepcopy(s), m)
        return [(p.rule, json.dumps(p.action, sort_keys=True, default=str), p.reason, p.priority) for p in out], notes
    for tr in ({}, {"verticality": 120, "mining": 100}, {"militarism": 100, "fortification": 60}):
        s = copy.deepcopy(BASE)
        s["settings"]["traits"] = tr
        s["buildings"]["zones"]["Barracks"] = 0
        a = drawn(traits(**tr), floors=False)
        b = drawn(traits(**tr))
        MF.note_result(b, start("bedrooms"), answer(57, 3, 50, new=True))
        pa, na = props(a, s)
        pb, nb = props(b, s)
        assert pa == pb and na == nb, tr
        assert any('"start_project"' in x[1] for x in pa), "the fort wants a level"
        assert not any('"floor"' in x[1] for x in pa), "plan()'s proposals carry no floor hint"
        assert "floors" not in a.atlas["plan"], "plan() never makes the table"


# --- 9. the floors follow the stair ----------------------------------------------------

@test("hint: a district with its own stairwell gives that stair as the spine; otherwise the plan's; then the action's")
def _():
    m = drawn(traits(fortification=40))
    h = MF.hint(m, start("workshops", shops=["Masons"]), {}, traits(), CFG)
    assert h["spine"] == {"x": 100, "y": 100}, h
    masterplan.note_stairwell(m, "industry", 131, 100)
    h = MF.hint(m, start("workshops", shops=["Masons"]), {}, traits(), CFG)
    assert h["spine"] == {"x": 131, "y": 100}, h
    assert MF.hint(m, start("bedrooms"), {}, traits(), CFG)["spine"] == {"x": 100, "y": 100}
    assert MF.hint(m, start("storage"), {}, traits(), CFG)["spine"] == {"x": 100, "y": 100}
    # the classic hint on the action already carries the stairwell: the same
    a = start("workshops", shops=["Masons"])
    a["plan"] = masterplan.hint(m, "workshops", action=a)
    assert a["plan"]["spine"] == {"x": 131, "y": 100}
    assert MF.hint(m, a, {}, traits(), CFG)["spine"] == {"x": 131, "y": 100}
    a["plan"]["spine"] = {"x": 7, "y": 8}
    assert MF.hint(m, a, {}, traits(), CFG)["spine"] == {"x": 7, "y": 8}
    a["plan"]["spine"] = {"x": 7, "y": 1000}             # outside the map's range: the district's
    assert MF.hint(m, a, {}, traits(), CFG)["spine"] == {"x": 131, "y": 100}
    # a level a custom moved hangs on the stair of the district it went to
    m, t = custom_fort(piety=100, welfare=40)
    masterplan.note_stairwell(m, "halls", 100, 140)
    a = start("bedrooms")
    assert MF.hint(m, a, {}, t, CFG)["spine"] == {"x": 100, "y": 100}, "no plan on the action: the homes'"
    a = with_customs(m, t, "bedrooms")
    h = MF.hint(m, a, {}, t, CFG)
    assert h["tag"] == "halls" and h["spine"] == {"x": 100, "y": 140}, h
    # a floor full on the main stair is not full on the district's own
    m = drawn(traits(fortification=40))
    el = m.atlas["plan"]["floors"]["roles"]["crafts"]["elevs"]
    rep = {"list": [{"elevation": el[0], "stair": {"x": 100, "y": 100}, "full": ["industry"]}]}
    a = start("workshops", shops=["Masons"])
    assert MF.hint(m, a, {"floors": rep}, traits(), CFG)["elevs"][-1] == el[0] or len(el) == 1
    masterplan.note_stairwell(m, "industry", 131, 100)
    assert MF.hint(m, a, {"floors": rep}, traits(), CFG)["elevs"] == el[:4]


@test("hint: dirs are the district's newest wing's way, then its ways, then the action's plan's, each once")
def _():
    m = drawn()
    d = district(m, "homes")
    d["dirs"] = ["south", "north"]
    d["wings"] = [{"era": 1, "dir": "south"}, {"era": 2, "dir": "west"}]
    h = MF.hint(m, start("bedrooms"), {}, traits(), CFG)
    assert h["dirs"] == ["west", "south", "north"], h
    h = MF.hint(m, start("bedrooms", plan={"elev_lo": d["lo"], "elev_hi": d["hi"], "dirs": ["east", "north", "up"]}),
                {}, traits(), CFG)
    assert h["dirs"] == ["west", "south", "north", "east"], h
    # a new era's wing leads
    masterplan.new_era(m, 2, profile(), traits())
    d = district(m, "storage")
    assert MF.hint(m, start("storage"), {}, traits(), CFG)["dirs"][0] == d["wings"][-1]["dir"] == d["dirs"][0]
    d["dirs"], d["wings"] = "x", [None, {"dir": 5}]
    assert "dirs" not in MF.hint(m, start("storage"), {}, traits(), CFG)


if __name__ == "__main__":
    finish()
