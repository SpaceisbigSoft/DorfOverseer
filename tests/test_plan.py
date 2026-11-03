"""Tests for milestone 4a: the master plan (brain/masterplan.py) and the
phases of a fort's life (brain/phases.py). No game needed.

    python tests/test_plan.py
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain"))

import masterplan  # noqa: E402
import memstore  # noqa: E402
import overseer  # noqa: E402

overseer.THROTTLE_MEMORY_SAVE = False      # each cycle reads and writes the memory (the throttle has its own test)
import phases  # noqa: E402
import planner  # noqa: E402
import timeline  # noqa: E402
from planner import PLANNER_CONFIG, Memory  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
TMP = Path(tempfile.mkdtemp())
memstore.FORTS_DIR = TMP / "forts"
memstore.LEGACY_FILE = TMP / "overseer-memory.json"
overseer.say = lambda m: None
overseer.JOURNAL = TMP / "decisions.jsonl"
RESULTS = []
DAY = 1200
YEAR = 403200


def test(name):
    def wrap(fn):
        shutil.rmtree(memstore.FORTS_DIR, ignore_errors=True)
        overseer.LAST_FULL.clear()
        try:
            fn()
            RESULTS.append((name, True, ""))
        except AssertionError as e:
            RESULTS.append((name, False, str(e)))
        except Exception:  # noqa: BLE001
            import traceback
            RESULTS.append((name, False, traceback.format_exc()))
        return fn
    return wrap


def state_at(day: int) -> dict:
    s = copy.deepcopy(BASE)
    s["date"] = {"year": day // 336, "tick": (day % 336) * DAY, "day": 1, "month": "Granite", "season": "spring"}
    return s


SITE = {"stairs": [{"x": 100, "y": 100, "z_top": 160, "z_bottom": 130, "elev_top": 60, "elev_bottom": 30,
                    "count": 8}],
        "citizen_elevation": 50, "soil": [58, 59], "elevation_offset": -100}


def mem_with_survey(entrance=None) -> Memory:
    m = Memory()
    m.culture = {"seed": "Test#1", "eras": [{"year": 150, "title": "Plain era"}]}
    m.atlas = {"survey": {"elevation_offset": -100, "tick": 1,
                          "layers": [{"name": "Cavern1", "z_top": 120, "z_bottom": 115, "discovered": True}]},
               "entrances": {}}
    if entrance:
        m.atlas["entrances"][entrance] = {"kind": "surface"}
    return m


def traits(**kw):
    return {"verticality": 0, "spacing": 0, "grandeur": 0, "fortification": 0, "craftsmanship": 0, **kw}


def profile(**kw):
    return {"layout": "grid", "palette": "dark", "temple": "shrine", "entry_doors": True, **kw}


# --- drawing the plan ----------------------------------------------------------------

@test("plan: deep forts stack a band per district, top to bottom; the site's range is kept")
def _():
    m = mem_with_survey()
    p = masterplan.draw(state_at(50000), m, SITE, traits(verticality=80), profile())
    d = {x["kind"]: x for x in p["districts"]}
    # (0.105.14) a deep fort reaches down to the cavern's margin (top at 20, +3 clear), not
    # only 3 below the spine's bottom (30)
    assert p["vertical"] == "deep" and p["range"] == [23, 60], p["range"]
    assert d["halls"]["lo"] > d["homes"]["hi"] > d["storage"]["hi"] > d["industry"]["hi"], d
    assert d["homes"]["lo"] <= 50 <= d["homes"]["hi"], "homes around the fort's heart"
    for x in d.values():
        assert 23 <= x["lo"] <= x["hi"] <= 60, x
    h = masterplan.hint(m, "bedrooms") if masterplan.has_plan(m) else None
    if h is not None:
        assert h.get("extend") == masterplan.DEEP_EXTEND, h
    assert "defence" not in d, "no defence district at low Fortification"
    assert d["farms"]["lo"] == 58, "farms where the soil is"


@test("plan: flat forts keep every district near the heart, apart by direction")
def _():
    m = mem_with_survey()
    p = masterplan.draw(state_at(50000), m, SITE, traits(verticality=-80, fortification=50), profile())
    d = {x["kind"]: x for x in p["districts"]}
    assert p["vertical"] == "flat" and "defence" in d
    assert all(x["lo"] >= 49 and x["hi"] <= 51 for k, x in d.items() if k != "farms"), d
    assert d["homes"]["dirs"] != d["industry"]["dirs"], "homes and work on different sides"


@test("plan: the axis faces away from the main surface entrance; patterns pick directions")
def _():
    m = mem_with_survey(entrance="100,60,160")        # the entrance is north of the stair
    p = masterplan.draw(state_at(50000), m, SITE, traits(), profile(layout="stacked"))
    assert p["axis"] == "south", p["axis"]
    assert all(x["dirs"] == ["south"] for x in p["districts"]), "stacked: all one way"
    p2 = masterplan.draw(state_at(50000), m, SITE, traits(), profile(layout="branching"))
    arms = [x["dirs"][0] for x in p2["districts"] if x["kind"] != "farms"]
    assert len(set(arms)) >= 3, arms
    p3 = masterplan.draw(state_at(50000), m, SITE, traits(), profile(layout="rings"))
    assert all(len(x["dirs"]) == 4 for x in p3["districts"])


@test("plan: names follow the style and the fort; grammar from the sliders")
def _():
    m = mem_with_survey()
    p = masterplan.draw(state_at(50000), m, SITE, traits(grandeur=70, fortification=60), profile(palette="dark"))
    names = [x["name"] for x in p["districts"]]
    assert all(n.startswith("the Dark ") for n in names), names
    p2 = masterplan.draw(state_at(50000), mem_with_survey(), SITE, traits(grandeur=70, fortification=60),
                         profile(palette="dark"))
    assert [x["name"] for x in p2["districts"]] == names, "the same fort names the same way"
    assert p["grammar"] == {"avenue": 3, "corridors": "dog-leg", "doors": "doored"}, p["grammar"]


@test("plan: balanced forts get bands of 3 levels that don't overlap")
def _():
    m = mem_with_survey()
    p = masterplan.draw(state_at(50000), m, SITE, traits(), profile())
    ds = sorted((x for x in p["districts"] if x["kind"] != "farms"), key=lambda x: -x["hi"])
    assert p["vertical"] == "balanced" and all(x["hi"] - x["lo"] == 2 for x in ds), ds
    for upper, lower in zip(ds, ds[1:]):
        assert upper["lo"] > lower["hi"], (upper, lower)


@test("plan: an older formula's plan is redrawn only while nothing has been built in it")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(), profile())
    m.atlas["plan"]["formula"] = 1
    for d in m.atlas["plan"]["districts"]:
        d["lo"] = d["hi"] = 50                         # the old, cramped bands
    assert masterplan.needs_redraw(m)
    out = masterplan.ensure(state_at(50100), m, SITE, traits(), profile())
    assert out and "redrawn" in out[0] and not masterplan.needs_redraw(m)
    assert any(d["lo"] != d["hi"] for d in m.atlas["plan"]["districts"])
    m.atlas["plan"]["formula"] = 1
    m.atlas["plan"]["districts"][0]["levels"] = [{"id": 1, "in": True}]
    assert not masterplan.needs_redraw(m), "a plan with a level built in it keeps its design"
    assert masterplan.ensure(state_at(50200), m, SITE, traits(verticality=100), profile()) == []


@test("plan: drawn once; no stairs known yet means no plan")
def _():
    m = mem_with_survey()
    assert masterplan.ensure(state_at(50000), m, {"stairs": []}, traits(), profile()) == []
    assert not masterplan.has_plan(m)
    assert masterplan.ensure(state_at(50000), m, SITE, traits(), profile())
    first = copy.deepcopy(m.atlas["plan"])
    assert masterplan.ensure(state_at(50100), m, SITE, traits(verticality=100), profile(layout="rings")) == []
    assert m.atlas["plan"] == first


# --- using it -------------------------------------------------------------------------

@test("0.104.107: corridors never 1 wide: 2 by default, 3 for grand or spacious forts, 2 for old 1-wide plans")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(), profile())
    assert masterplan.hint(m, "bedrooms")["avenue"] == 2
    m.atlas["plan"]["grammar"] = {"avenue": 1}                   # a plan drawn before 0.104.107
    assert masterplan.hint(m, "bedrooms")["avenue"] == 2
    m2 = mem_with_survey()
    masterplan.ensure(state_at(50000), m2, SITE, traits(grandeur=80), profile())
    assert masterplan.hint(m2, "bedrooms", traits=traits(grandeur=80))["avenue"] == 3


@test("hint: the district's band, its directions and the spine; farms follow the soil instead")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(verticality=80), profile())
    h = masterplan.hint(m, "bedrooms")
    d = next(x for x in m.atlas["plan"]["districts"] if x["kind"] == "homes")
    assert h["elev_lo"] == d["lo"] and h["elev_hi"] == d["hi"] and h["spine"] == {"x": 100, "y": 100}
    assert h["dirs"] == d["dirs"] and h["district"] == d["name"][:40]
    assert masterplan.hint(m, "farms") is None and masterplan.hint(m, "nonsense") is None
    assert masterplan.hint(Memory(), "bedrooms") is None, "no plan, no hint"


@test("hint: a district's levels spread through its band")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(verticality=80), profile())
    seen = []
    for i in range(3):
        h = masterplan.hint(m, "bedrooms")
        seen.append(h["elev_target"])
        masterplan.note_result(m, {"type": "start_project", "kind": "bedrooms", "plan": h},
                               {"ok": True, "project_id": i, "elevation": h["elev_target"], "in_district": True},
                               state_at(50000))
    assert len(set(seen)) == 3, seen


@test("results: the first level opens a district; levels that land elsewhere make it grow")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(verticality=80), profile())
    d = next(x for x in m.atlas["plan"]["districts"] if x["kind"] == "storage")
    act = {"type": "start_project", "kind": "storage", "plan": masterplan.hint(m, "storage")}
    line = masterplan.note_result(m, act, {"ok": True, "project_id": 1, "elevation": d["lo"], "in_district": True},
                                  state_at(50000))
    assert line and line.startswith("the first level of the Dark"), line
    lo, hi = d["lo"], d["hi"]
    assert masterplan.note_result(m, act, {"ok": True, "project_id": 2, "elevation": 0, "in_district": False},
                                  state_at(50000)) is None
    line = masterplan.note_result(m, act, {"ok": True, "project_id": 3, "elevation": 0, "in_district": False},
                                  state_at(50000))
    assert line and "grew" in line and (d["lo"], d["hi"]) != (lo, hi), (line, d)
    assert d["levels"][0]["name"].startswith("the First of the Dark"), d["levels"][0]
    assert masterplan.note_result(m, act, {"ok": False}, state_at(50000)) is None
    # a level built without a hint (a mood's workshop) is no miss
    n = len(d["levels"])
    masterplan.note_result(m, {"type": "start_project", "kind": "storage"},
                           {"ok": True, "project_id": 9, "elevation": 0}, state_at(50000))
    assert len(d["levels"]) == n and d["missed"] == 0


@test("eras: a new era gives each district a new wing; the plan itself isn't redrawn")
def _():
    m = mem_with_survey(entrance="100,60,160")
    masterplan.ensure(state_at(50000), m, SITE, traits(), profile(layout="stacked"))
    before = {x["kind"]: (x["lo"], x["hi"]) for x in m.atlas["plan"]["districts"]}
    out = masterplan.new_era(m, 2)
    homes = next(x for x in m.atlas["plan"]["districts"] if x["kind"] == "homes")
    assert out and homes["dirs"][0] != "south" and len(homes["wings"]) == 2, homes
    assert {x["kind"]: (x["lo"], x["hi"]) for x in m.atlas["plan"]["districts"]} == before
    assert masterplan.new_era(m, 2) == [], "the same era twice adds nothing"


@test("planner: a new level carries the plan's hint; plan() still never changes memory")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(verticality=80), profile())
    s = copy.deepcopy(BASE)
    s["buildings"]["other"]["Bed"] = 20                  # short of beds: a bedroom level
    before = json.dumps(m.to_dict(), sort_keys=True)
    props, _ = planner.plan(s, m, PLANNER_CONFIG)
    assert json.dumps(m.to_dict(), sort_keys=True) == before
    b = [p for p in props if p.action.get("type") == "start_project"]
    assert b and b[0].action["plan"]["district"].startswith("the Dark"), [p.action for p in b]
    assert "(in the Dark" in b[0].reason


# --- phases ------------------------------------------------------------------------------

def run_days(m, start, n, **row):
    for d in range(start, start + n):
        s = state_at(d)
        for k, v in row.items():
            if k == "drink":
                s["stocks"]["drink"] = v
            elif k == "threats":
                s["others_on_map"]["threats_that_can_reach_dwarves"] = v
        timeline.record(s, m, row.get("events", []), PLANNER_CONFIG)
        phases.update(s, m, row.get("events", []))
    return s


@test("phases: an old fort the AI takes over is growing, not founding; a siege starts at once")
def _():
    m = Memory()
    m.atlas = {"plan": {"tick": 50000 * DAY, "districts": [{}]}}
    s = run_days(m, 50000, 15)
    assert phases.current(m) in ("growth", "prosperity"), phases.current(m)     # (the fixture fort is well off)
    s = state_at(50015)
    timeline.record(s, m, [], PLANNER_CONFIG)
    assert phases.update(s, m, [{"kind": "invasion"}]) == "a siege: the fort turns to its defence"
    assert phases.held_kinds(m, 50015 * DAY).keys() == {"library", "memorial"}, "taverns and temples go ahead"
    assert phases.held_kinds(m, 50015 * DAY + 29 * DAY) == {}, "a long siege holds nothing back after 4 weeks"
    assert m.chronicle["phase"]["log"][0]["from"] in ("growth", "prosperity"), "the first look was quiet"


@test("phases: after a siege comes recovery, then (after at least 14 days) growth again")
def _():
    m = Memory()
    run_days(m, 49999, 1)                                   # the first look, quietly
    s = state_at(50000)
    timeline.record(s, m, [], PLANNER_CONFIG)
    phases.update(s, m, [{"kind": "invasion"}])
    run_days(m, 50001, 20)
    assert phases.current(m) == "recovery", phases.current(m)
    assert "library" in phases.held_kinds(m) and "temple" not in phases.held_kinds(m)
    run_days(m, 50021, 60)
    assert phases.current(m) in ("growth", "prosperity"), phases.current(m)
    log = [x["phase"] for x in m.chronicle["phase"]["log"]]
    assert log[:2] == ["siege", "recovery"], log


@test("phases: a small fort is founding; a phase isn't left before 14 days")
def _():
    m = Memory()
    s = state_at(50000)
    s["dwarves"]["total"] = 12
    timeline.record(s, m, [], PLANNER_CONFIG)
    phases.update(s, m, [])
    assert phases.current(m) == "founding"
    m2 = Memory()
    run_days(m2, 49999, 1)
    s = state_at(50000)
    timeline.record(s, m2, [], PLANNER_CONFIG)
    phases.update(s, m2, [{"kind": "invasion"}])
    for d in range(50001, 50010):                      # 9 quiet days: still under siege's minimum
        s = state_at(d)
        timeline.record(s, m2, [], PLANNER_CONFIG)
        phases.update(s, m2, [])
    assert phases.current(m2) in ("siege", "recovery")
    assert len(m2.chronicle["phase"]["log"]) == 1, m2.chronicle["phase"]["log"]


@test("phases: wildlife and cavern creatures that can reach the dwarves are no siege; invaders are")
def _():
    m = Memory()
    for d in range(50000, 50006):
        s = state_at(d)
        s["others_on_map"]["threats"] = [{"id": 1, "can_reach_dwarves": True, "name": "crundle"}]
        s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
        timeline.record(s, m, [], PLANNER_CONFIG)
        phases.update(s, m, [])
    assert phases.current(m) != "siege", phases.current(m)
    for d in range(50006, 50010):
        s = state_at(d)
        s["others_on_map"]["threats"] = [{"id": 2, "can_reach_dwarves": True, "invader": True, "name": "goblin"}]
        timeline.record(s, m, [], PLANNER_CONFIG)
        phases.update(s, m, [])
    assert phases.current(m) == "siege"


@test("plan: caverns are read in the survey's own terms; too little room means no plan yet")
def _():
    m = mem_with_survey()
    m.atlas["survey"]["elevation_offset"] = 0            # the atlas's copy is off (a failed map section)
    m.atlas["survey"]["layers"] = [{"name": "Cavern1", "z_top": 128, "z_bottom": 120}]   # elevation 28
    p = masterplan.draw(state_at(50000), m, SITE, traits(), profile())
    assert p["range"][0] == 31, p["range"]               # 128 - 100 (the site's offset) + 3
    tight = dict(SITE, stairs=[dict(SITE["stairs"][0], elev_bottom=59, elev_top=60)])
    m2 = mem_with_survey()
    m2.atlas["survey"]["layers"] = [{"name": "Cavern1", "z_top": 157, "z_bottom": 150}]  # elevation 57
    assert masterplan.draw(state_at(50000), m2, tight, traits(), profile()) is None
    assert masterplan.draw(state_at(50000), mem_with_survey(), {"stairs": [{"x": 1, "y": 1, "elev_top": None}],
                                                                 "elevation_offset": -100},
                           traits(), profile()) is None
    m3 = mem_with_survey()
    del m3.atlas["survey"]["layers"]
    assert masterplan.draw(state_at(50000), m3, SITE, traits(), profile()) is None, "caverns unknown: wait"


@test("plan: a deep fort squeezed into a small site gets thinner bands, not piled-up ones")
def _():
    m = mem_with_survey()
    small = dict(SITE, stairs=[dict(SITE["stairs"][0], elev_bottom=48, elev_top=60)])   # range 45..60
    p = masterplan.draw(state_at(50000), m, small, traits(verticality=100, fortification=50), profile())
    ds = sorted((x for x in p["districts"] if x["kind"] != "farms"), key=lambda x: -x["hi"])
    for upper, lower in zip(ds, ds[1:]):
        assert upper["lo"] >= lower["hi"], (upper, lower)        # at most one shared level
    assert len({(x["lo"], x["hi"]) for x in ds}) == len(ds), ds


@test("planner: the phase holds back grand halls, and says why")
def _():
    m = Memory()
    s = copy.deepcopy(BASE)
    m.chronicle = {"phase": {"now": "siege", "since": s["date"]["year"] * YEAR + s["date"]["tick"] - DAY, "log": []}}
    s["locations"]["count"].pop("LIBRARY", None)
    s["dwarves"]["total"] = 120
    props, notes = planner.plan(s, m, PLANNER_CONFIG)
    assert not any(p.action.get("kind") == "library" for p in props)
    assert any("under siege" in n for n in notes), notes


# --- milestone 4b: varied details, grammar, quirks ---------------------------------------

import quirks  # noqa: E402


def earn(history, traits_, extra=None, days=90):
    """Run the quirk check for `days` (conditions must hold a season)."""
    out = []
    for d in range(0, days + 1, 6):
        out += quirks.update(history, traits_, {"wood": 10, "boulders": 10},
                             {"year": 150, "tick": d * DAY}, extra)
    return out


@test("variety: each level's orientation and pillar rhythm are seeded; a save and reload keep them")
def _():
    m = mem_with_survey()
    v = masterplan.variety(m, "bedrooms")
    assert v["orient"] in (0, 1, 2, 3) and 3 <= v["rhythm"] <= 6
    from tokens import TokenBank
    texts = memstore.texts_of(m, TokenBank(), "Test#1")
    m2, _ = memstore.join({k: memstore.decode(k, t) for k, t in texts.items()})
    assert masterplan.variety(m2, "bedrooms") == v
    seen = set()
    for i in range(12):
        m.atlas.setdefault("registry", {})[f"project:{i}"] = {"kind": "dining"}
        seen.add(masterplan.variety(m, "dining")["orient"])
    assert len(seen) >= 3, seen


@test("hint: carries the plan's corridor grammar")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(grandeur=70, fortification=60), profile())
    h = masterplan.hint(m, "bedrooms")
    assert (h["avenue"], h["corridors"], h["doors"]) == (3, "dog-leg", "doored"), h


@test("Warren: earned by a cramped, plain fort or by sieges; small rooms, narrow dog-leg ways, no grand halls")
def _():
    h = {}
    assert any("Warren" in c for c in earn(h, {"spacing": -80, "grandeur": -10})), h
    h2 = {"sieges": 2}
    assert any("Warren" in c for c in earn(h2, {"fortification": 60})), "the other way to earn it"
    m = mem_with_survey()
    m.culture.update(h)
    masterplan.ensure(state_at(50000), m, SITE, traits(grandeur=70), profile())
    hint = masterplan.hint(m, "bedrooms")
    assert (hint["avenue"], hint["corridors"]) == (1, "dog-leg"), hint
    s = copy.deepcopy(BASE)
    s["buildings"]["other"]["Bed"] = 20
    props, _ = planner.plan(s, m, PLANNER_CONFIG)
    bed = next(p for p in props if p.action.get("kind") == "bedrooms")
    assert bed.action["room_size"] == 2, bed.action
    from weights import score_area
    top = score_area("halls", {"grandeur": 80}, m.culture)[0]
    assert top["id"] != "pillared", top


@test("Mirror-minded: never a mirror image (as drawn, or a quarter turn)")
def _():
    h = {}
    assert any("Mirror-minded" in c for c in earn(h, {"grandeur": 70, "craftsmanship": 70}))
    m = mem_with_survey()
    m.culture.update(h)
    for i in range(20):
        m.atlas.setdefault("registry", {})[f"project:{i}"] = {"kind": "temple"}
        assert masterplan.variety(m, "temple")["orient"] in (0, 3)


@test("The Great Shaft: needs a cavern reached; levels gather close around the stair, wide avenues")
def _():
    t = {"verticality": 80, "mining": 60}
    assert not any("Great Shaft" in c for c in earn({}, t, {"caverns_reached": 0}))
    h = {}
    assert any("Great Shaft" in c for c in earn(h, t, {"caverns_reached": 1}))
    m = mem_with_survey(entrance="100,60,160")
    m.culture.update(h)
    masterplan.ensure(state_at(50000), m, SITE, traits(), profile(layout="rings"))
    hint = masterplan.hint(m, "storage")
    assert hint["avenue"] == 3 and hint["dirs"] == ["south"], hint


@test("planner: the door rule follows the fort's style now, not when the plan was drawn")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(), profile(entry_doors=False))
    assert m.atlas["plan"]["grammar"]["doors"] == "open"
    s = copy.deepcopy(BASE)
    s["buildings"]["other"]["Bed"] = 20
    s["settings"]["traits"] = {"fortification": 80}
    props, _ = planner.plan(s, m, PLANNER_CONFIG)
    bed = next(p for p in props if p.action.get("kind") == "bedrooms")
    assert bed.action["plan"]["doors"] == "fortified", bed.action["plan"]


@test("Last Stand: lost after 3 years without another such death")
def _():
    m = mem_with_survey()
    m.chronicle = {"phase": {"now": "siege", "since": 50000 * DAY,
                             "log": [{"phase": "siege", "from": "growth", "tick": 50000 * DAY}]}}
    m.atlas["events"] = [{"k": "death", "x": 1, "y": 1, "z": 1, "t": 50002 * DAY}]
    f = overseer.world_facts(state_at(50003), m)
    earn(m.culture, {"caution": 70}, f, days=1)
    assert "last_stand" in m.culture.get("quirks", {})
    m.atlas["events"] = []                               # folded away after a year
    later = state_at(50003 + 3 * 336 + 1)
    f = overseer.world_facts(later, m)
    assert f["years_since_inside_death"] == 3 and f["deaths_inside_in_siege"] == 0, f
    out = quirks.update(m.culture, {"caution": 70}, None, later["date"], f)
    assert any("no longer Last Stand" in c for c in out), out
    assert "for" in quirks.fade_text("warren") or quirks.fade_text("warren")


@test("Last Stand: a citizen killed inside during a siege; a keep's place beside the homes")
def _():
    m = mem_with_survey()
    masterplan.ensure(state_at(50000), m, SITE, traits(), profile())
    m.chronicle = {"phase": {"now": "siege", "since": 50000 * DAY,
                             "log": [{"phase": "siege", "from": "growth", "tick": 50000 * DAY}]}}
    m.atlas["events"] = [{"k": "death", "x": 1, "y": 1, "z": 1, "t": 50002 * DAY},              # inside
                         {"k": "death", "x": 5, "y": 5, "z": 5, "t": 50002 * DAY, "near": "entrance:1,1,1"}]
    f = overseer.world_facts(state_at(50003), m)
    assert f["deaths_inside_in_siege"] == 1 and f["caverns_reached"] == 1, f
    assert any("Last Stand" in c for c in earn(m.culture, {"caution": 70}, f, days=1))
    out = masterplan.apply_quirks(m)
    assert out and masterplan.apply_quirks(m) == [], "once"
    assert any(x.startswith("places kept for:") and "inner keep" in x for x in masterplan.lines(m))


# --- the whole cycle -------------------------------------------------------------------

@test("overseer: after the AI acts, the next cycle reads the full report, not the morning's")
def _():
    class B:
        version = {"recipes": ["brew_drink"], "tools": []}

        def __init__(self):
            self.s = copy.deepcopy(BASE)
            self.s["stocks"]["drink"] = 10           # it will order drink
            self.s["tier"] = "daily"
            self.tiers = []

        def state(self, include_units=True, tier=None):
            self.tiers.append(tier)
            out = copy.deepcopy(self.s)
            if tier == "pulse":
                out = {k: out[k] for k in ("fort", "date", "stocks", "orders")}
                out["tier"] = "pulse"
            return out

        def events(self):
            return []

        def survey(self):
            return dict(SITE, ok=True)

        def act(self, a):
            return {"ok": True, "order_id": 7}

        def status(self):
            return {"halted": False, "decisions": {}}
    b = B()
    overseer.one_cycle(b, autopilot=True)                 # acts: orders drink
    assert not overseer.LAST_FULL, "the morning's report is no longer trusted"
    overseer.one_cycle(b, autopilot=True, tier="pulse")
    assert b.tiers[-1] is None, b.tiers                    # so the 'pulse' cycle read the full report


@test("overseer: the survey draws the plan once; the panel and the strategist see it")
def _():
    class B:
        version = {"recipes": [], "tools": []}

        def __init__(self):
            self.s = copy.deepcopy(BASE)
            self.surveys = 0
            self.acted = []

        def state(self, include_units=True, tier=None):
            return copy.deepcopy(self.s)

        def events(self):
            return []

        def survey(self):
            self.surveys += 1
            return dict(SITE, ok=True)

        def act(self, a):
            self.acted.append(a)
            return {"ok": True}

        def status(self):
            return {"halted": False, "decisions": {}}
    b = B()
    overseer.one_cycle(b, autopilot=True)
    b.s["date"]["tick"] += DAY
    overseer.one_cycle(b, autopilot=True)
    m = Memory.from_dict(memstore.read_logged("AI Test Run#1234")["memory"])
    assert m.atlas["plan"]["districts"] and b.surveys == 1, b.surveys
    assert any(e["k"] == "plan" for e in m.chronicle["entries"]), m.chronicle["entries"]
    culture = [a for a in b.acted if a["type"] == "set_culture"]
    assert culture and culture[-1]["culture"]["plan"] and culture[-1]["culture"]["phase"], culture[-1]["culture"].keys()
    brief = memstore.brief(m)
    assert brief[0].startswith("phase: ") and brief[1].startswith("plan: "), brief



@test("Sky-reachers (0.103.19): the share of citizens out under the sky, a slow average kept in the culture")
def _():
    m = mem_with_survey()
    m.culture = {}
    s = state_at(50003)
    s["map"] = {"dwarves": {"outside": 20, "citizens": 50}}
    f = overseer.world_facts(s, m)
    assert f["surface_share"] == 0.4 and m.culture["surface_share_avg"] == 0.4, f
    s["map"]["dwarves"]["outside"] = 0                     # one day indoors moves it a little
    f = overseer.world_facts(s, m)
    assert 0.38 <= f["surface_share"] <= 0.39, f
    s["map"]["dwarves"] = {"outside": 1, "citizens": 5}    # too few to say
    assert "surface_share" not in overseer.world_facts(s, m)


@test("Waste Not (0.103.19): wood and stone per dwarf, for a poor site")
def _():
    m = mem_with_survey()
    s = state_at(50003)
    s["stocks"] = {"wood": 20, "boulders": 40}
    s["dwarves"] = {"total": 30}
    f = overseer.world_facts(s, m)
    assert f["materials_pd"] == 2.0, f

for name, ok, msg in RESULTS:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print("    " + msg.replace("\n", "\n    "))
passed = sum(1 for _, ok, _ in RESULTS if ok)
print(f"\n{passed} passed, {len(RESULTS) - passed} failed")
sys.exit(0 if passed == len(RESULTS) else 1)
