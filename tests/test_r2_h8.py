"""(r2 h8) Round 2, group h8: landmarks rebuilt after a cancel, the season's
barracks, Goblin-haunted, one temple a hall (A6 findings 1-3, its slider
table; R-F 9).

- a landmark's level is not given up at the 56-day unreached mark (D's Long
  Descent: projects 43-46, 0 of 47-75 tiles in 59-67 days; A's chronicle
  hall: project 114, 0 of 247 in 56 days); a landmark with a part standing
  counts as built, an earlier copy still dug holds off a new one, and one
  built is never wished again (even past the list's cut);
- the bridge's "built through its levels" answer is no step failure, and the
  report says 'levels' (not the saved 'open') once the openings are done;
- the season's training need weighed by Militarism (D, Hermit hold: 42 of 56
  seasons barracks at "45-58% long for training"); a season's
  raise:barracks can start a barracks (planner_building's gate);
- Goblin-haunted: "TotalWar" (all six forts' diplomacy) counts as a war;
  the leanings' "at war" likewise;
- a blueprint level's zone in several rectangles carries one Quickfort label
  (one zone, one temple: B's god halls made 27 temples each).

    python tests/test_r2_h8.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime  # noqa: F401
    HAVE_LUPA = True
except ImportError:  # pragma: no cover
    HAVE_LUPA = False

from planner_core import TICKS_PER_DAY, TICKS_PER_YEAR, Proposal, abs_tick  # noqa: E402

BASE = json.loads((HERE / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
# the six forts' diplomacy, 15-16 Nov (run2/*/state-last.json)
CIVS = [{"race": "GOBLIN", "relation": "Skirmishing"}, {"race": "DWARF", "relation": "Peace"},
        {"race": "GOBLIN", "relation": "TotalWar", "name": "the Doom of Fangs"}, {"race": "GOBLIN", "relation": "Peace"}]


def load_test(name: str) -> dict:
    """Another test file's helpers (its tests don't run: not __main__)."""
    src = (HERE / name).read_text(encoding="utf-8")
    src = re.sub(r"\n(if __name__ == \"__main__\":\s*\n\s*)?finish\(\)\s*$", "\n", src)
    ns = {"__name__": "x_" + name[:-3], "__file__": str(HERE / name)}
    exec(compile(src, name, "exec"), ns)
    return ns


def fort(**kw):
    s = copy.deepcopy(BASE)
    s.update(kw)
    return s


def stamp_days_ago(s, days):
    t = abs_tick(s) - days * TICKS_PER_DAY
    return {"year": t // TICKS_PER_YEAR, "tick": t % TICKS_PER_YEAR}


# --- 3. Goblin-haunted ----------------------------------------------------------

@test("Goblin-haunted: a goblin civ at 'TotalWar' (the game's word) counts as a goblin war; Skirmishing and Peace don't")
def _():
    from overseer import world_facts
    from planner import Memory
    s = fort(diplomacy={"civs": copy.deepcopy(CIVS)})
    f = world_facts(s, Memory())
    assert f.get("goblin_wars") == 1, f.get("goblin_wars")
    s["diplomacy"]["civs"][2]["relation"] = "Peace"
    assert world_facts(s, Memory()).get("goblin_wars") == 0
    s["diplomacy"]["civs"][2]["relation"] = "War"          # an older word still counts
    assert world_facts(s, Memory()).get("goblin_wars") == 1


@test("the quirk Goblin-haunted is earnable from the run's diplomacy (its earn test passes on goblin_wars)")
def _():
    rules = json.loads((ROOT / "brain" / "choices.json").read_text(encoding="utf-8"))
    q = next(v for k, v in rules.items() if isinstance(v, dict) and k == "goblin_haunted") \
        if "goblin_haunted" in rules else None
    if q is None:                    # choices.json keeps quirks under a section
        q = next(v["goblin_haunted"] for v in rules.values() if isinstance(v, dict) and "goblin_haunted" in v)
    cond = q["earn"]["all"][0]
    from overseer import world_facts
    from planner import Memory
    f = world_facts(fort(diplomacy={"civs": copy.deepcopy(CIVS)}), Memory())
    assert cond["fact"] == "goblin_wars" and f[cond["fact"]] >= cond["min"], (cond, f.get("goblin_wars"))


@test("leanings: a neighbour at 'TotalWar' is 'at war' (Fortification +15), not only 'goblins in the world'")
def _():
    import leanings
    civs = [_ for _ in copy.deepcopy(CIVS)]
    at_war = [c for c in civs if str(c.get("relation", "")).lower() in leanings.WAR_WORDS]
    assert [c["name"] for c in at_war] == ["the Doom of Fangs"], at_war


# --- 1. landmark levels and the slow-dig cancel ---------------------------------

def landmark_level(pid, days, dug=0, total=247, kind="landmark"):
    s = fort()
    p = {"id": pid, "kind": kind, "phase": "dig", "dig": {"dug": dug, "total": total, "digging": 0},
         "started": stamp_days_ago(s, days), "summary": {"landmark": "The Hall of the Chronicle", "level": 2}}
    s["projects"] = {"open": [p], "finished": 0, "max_open": 2}
    return s


def cancels(s):
    from digest import normalize
    from planner import Memory, plan
    ps, _ = plan(normalize(copy.deepcopy(s)), Memory())
    return [p for p in ps if p.action.get("type") == "cancel_project"]


@test("A's chronicle hall level (project 114, 0 of 247 tiles dug in 56 days) is no longer given up; "
      "an ordinary level of the same is (unreached_dig_days stays 56)")
def _():
    assert cancels(landmark_level(114, 56)) == []
    assert cancels(landmark_level(114, 120)) == []
    c = cancels(landmark_level(18, 56, total=77, kind="tavern"))
    assert len(c) == 1 and c[0].action["project_id"] == 18 and c[0].action.get("unreached"), c


@test("a landmark's level still dug nothing after h8_landmark_dig_days (336) is given up (no slot held for ever)")
def _():
    from planner_config import PLANNER_CONFIG
    days = PLANNER_CONFIG["h8_landmark_dig_days"]
    assert days >= 4 * PLANNER_CONFIG["unreached_dig_days"]
    c = cancels(landmark_level(44, days))
    assert len(c) == 1 and c[0].action["project_id"] == 44, c


# --- 1. the landmark's copies -----------------------------------------------------

def design_fort():
    s = fort()
    s["date"]["season"] = "spring"
    s["settings"] = dict(s["settings"], design="architect", traits={"grandeur": 60})
    return s


def lm_memory(status="building", **kw):
    from planner import Memory
    m = Memory()
    e = {"id": 1, "kind": "chronicle_hall", "for": "Garetho the Bronze", "name": "The Hall of the Chronicle",
         "status": status, "by": "library", "tries": 0, "reasons": [], "landmark_id": 4,
         "project_ids": [102, 103], "started": 0, "env": [21, 15, 2, "rock"], "site": "S1", "tried": []}
    e.update(kw)
    m.atlas = {"landmarks": {"next": 2, "last_started": 0, "sites": None, "drawn": None, "list": [e]}}
    return m


def run(s, m, mode="architect"):
    import planner_design as PD
    props, notes = [], []
    PD.run_landmarks(s, {"grandeur": 60}, {}, props, notes, m, mode, abs_tick(s))
    return [p.action.get("type") for p in props], notes


@test("a level cancelled while the other stands (dug out): the landmark is kept as built, not started again elsewhere")
def _():
    s = design_fort()
    s["landmarks"] = {"list": [{"id": 4, "name": "The Hall of the Chronicle", "purpose": "chronicle_hall",
                                "status": "dropped", "stage": "done", "levels": 2, "project_ids": [102, 103]}]}
    s["projects"] = {"open": [], "decorating": [{"id": 102, "kind": "landmark", "phase": "decorate"}], "max_open": 2}
    m = lm_memory()
    acts, notes = run(s, m)
    e = m.atlas["landmarks"]["list"][0]
    assert e["status"] == "built" and e.get("partial"), e
    assert "blueprint_sites" not in acts and any("stands in part" in n for n in notes), (acts, notes)
    assert ["chronicle_hall", "Garetho the Bronze"] in m.atlas["landmarks"]["built_keys"]


@test("seen standing earlier (a level furnished), then a level cancelled: built; nothing stands: the next site as before")
def _():
    s = design_fort()
    rep = {"id": 4, "name": "x", "purpose": "chronicle_hall", "status": "building", "stage": "levels", "levels": 2,
           "project_ids": [102, 103]}
    s["landmarks"] = {"list": [rep]}
    s["projects"] = {"open": [{"id": 102, "kind": "landmark", "phase": "furnish"},
                              {"id": 103, "kind": "landmark", "phase": "dig"}], "max_open": 2}
    m = lm_memory()
    run(s, m)
    e = m.atlas["landmarks"]["list"][0]
    assert e["status"] == "building" and e.get("part_built"), e
    rep["status"] = "dropped"
    s["projects"] = {"open": [], "max_open": 2}
    run(s, m)
    assert e["status"] == "built", e
    # nothing of it ever stood: freed as before (0.105.37), its copy remembered
    m = lm_memory()
    s["landmarks"] = {"list": [dict(rep, status="dropped")]}
    run(s, m)
    e = m.atlas["landmarks"]["list"][0]
    assert e["status"] in ("due", "sites") and e["landmark_id"] is None and e["old_copies"] == [4], e


@test("an earlier copy still being dug: no new copy is started; once a level of it stands, the landmark is built")
def _():
    s = design_fort()
    s["landmarks"] = {"list": [{"id": 4, "name": "x", "purpose": "chronicle_hall", "status": "dropped",
                                "stage": "done", "levels": 2, "project_ids": [102, 103]}]}
    s["projects"] = {"open": [{"id": 102, "kind": "landmark", "phase": "dig"}], "max_open": 2}
    m = lm_memory(status="sites", landmark_id=None, old_copies=[4])
    m.atlas["landmarks"]["sites"] = {"for": 1, "asked": abs_tick(s), "list": [{"id": "S2"}]}
    acts, notes = run(s, m)
    assert acts == [] and any("earlier copy is still being dug" in n for n in notes), (acts, notes)
    s["projects"]["open"][0]["phase"] = "furnish"
    run(s, m)
    assert m.atlas["landmarks"]["list"][0]["status"] == "built"


@test("a landmark built once is never wished again, even after its entry left the list (LANDMARK_LIST_MAX)")
def _():
    import planner_design as PD
    lang = {"landmarks": [{"kind": "chronicle_hall", "for": "Garetho the Bronze", "words": "w"},
                          {"kind": "great_hall", "for": None, "words": "w"}]}
    m = lm_memory(status="built")
    PD.mark_built(m, m.atlas["landmarks"]["list"][0], 100)
    m.atlas["landmarks"]["list"] = []                       # cut from the list
    w = PD._wish(lang, m, {}, guided=False)
    assert w and w["kind"] == "great_hall", w


@test("the bridge's 'built through its levels' answer is no step failure: five of them don't free the slot")
def _():
    import planner_design as PD
    s = design_fort()
    s["landmarks"] = {"list": [{"id": 4, "name": "x", "purpose": "chronicle_hall", "status": "building",
                                "stage": "open", "levels": 2, "project_ids": [102, 103]}]}
    s["projects"] = {"open": [{"id": 102, "kind": "landmark", "phase": "dig"}], "max_open": 2}
    m = lm_memory()
    p = Proposal("landmark_step", {"type": "landmark_step", "landmark_id": 4}, "x", 6)
    levels = {"ok": False, "rejected": True, "stage": "levels", "landmark_id": 4,
              "error": "a rock landmark is built through its levels' projects"}
    for _ in range(PD.LANDMARK_STEP_FAILS + 1):
        PD.note_design(p, levels, s, m, abs_tick(s))
    e = m.atlas["landmarks"]["list"][0]
    assert int(e.get("step_fails") or 0) == 0, e
    acts, _ = run(s, m)
    assert e["status"] == "building" and e["landmark_id"] == 4, e
    assert "landmark_step" not in acts, acts                # not asked again this week, though the report says 'open'


if HAVE_LUPA:
    E1 = load_test("test_x_e1.py")

    @test("the bridge's report: a rock landmark whose openings are all done reports 'levels', not the saved 'open'")
    def _():
        E1["_reset"]()
        B, W, FIX, lt, lua_list = E1["B"], E1["W"], E1["FIX"], E1["lt"], E1["lua_list"]
        bp = FIX["good_atrium"]
        E1["rock_site"](7, 7, 2)
        r = B.build_landmark(lt(bp), "S1", E1["meta"](), lt(E1["NOW"]), False)
        assert r.ok, dict(r)
        E1["dig_all"]()
        E1["furnish_levels"](r)
        assert E1["report"]().stage == "open"
        assert B.landmark_step(1, False).ok          # the cut
        E1["dig_all"]()
        s = B.landmark_step(1, False)                # the rails
        assert s.ok and s.railed == 8, dict(s)
        for c in lua_list(W.placed):
            if c.mode == "build" and c.text == "CF":
                W.set(c.x, c.y, c.z, E1["T"]({"building": False, "shape": "FORTIFICATION"}))
        rep = E1["report"]()
        assert rep.status == "building" and rep.stage == "levels", (rep.status, rep.stage)
        st = B.landmark_step(1, False)
        assert not st.ok and st.stage == "levels", dict(st)

    D0 = load_test("test_d0_blueprints.py")

    @test("a library god hall (a cross: several zone rectangles) gets one Quickfort label on every zone cell: one temple")
    def _():
        BP, LUA_ = D0["BP"], D0["LUA"]
        bp = json.loads((ROOT / "brain" / "landmarks" / "god_hall.json").read_text(encoding="utf-8"))
        out = BP.to_layouts(D0["to_lua"](bp), 0)
        levels = D0["lua_list"](out.levels)
        texts = []
        for L in levels:
            texts += [c.text for c in D0["lua_list"](L.zone)]
        assert len(texts) > 1, texts
        assert all(t.startswith("m/aizone1{location=temple}") for t in texts), texts[:5]
        # quickfort's own reading (internal/quickfort/parse.lua): key 'm', label 'aizone1', the extent apart
        for t in texts:
            m = re.match(r"^(%s)/([\w\-_][\w\-_]+)(\{[^}]*\})?(\(\-?\d+x\-?\d+\))?$" % "[A-Za-z]", t)
            assert m and m.group(2) == "aizone1", t
        # one rectangle: left as it was
        one = D0["lua_list"](BP.one_zone(LUA_.table_from([LUA_.table_from({"x": 0, "y": 0, "text": "h(5x5)"})]), 1))
        assert one[0].text == "h(5x5)"
        two = D0["lua_list"](BP.one_zone(LUA_.table_from([LUA_.table_from({"x": 0, "y": 0, "text": "h(5x5)"}),
                                                          LUA_.table_from({"x": 5, "y": 0, "text": "h(2x3)"})]), 2))
        assert [c.text for c in two] == ["h/aizone2(5x5)", "h/aizone2(2x3)"], [c.text for c in two]


# --- 2. the season's barracks -----------------------------------------------------

def season_fort(militarism, training=0.5, social=0.3, pop=40):
    s = fort()
    s["dwarves"] = dict(s.get("dwarves") or {}, total=pop)
    s["settings"] = dict(s["settings"], traits={"militarism": militarism} if militarism is not None else {})
    s["needs"] = {"needs": {"MartialTraining": {"distracted": int(training * pop)},
                            "BeWithFriends": {"distracted": int(social * pop)}}}
    return s


@test("the season's training need is weighed by Militarism: a Hermit hold's or Garden fort's 50% longing to train "
      "no longer makes barracks the season's character; the War-hold's still does")
def _():
    import season
    from planner import Memory
    for mil in (None, -30, -60):
        ch = season.pick(season_fort(mil), Memory())["choice"]
        assert ch != "raise:barracks", (mil, ch)
    assert season.pick(season_fort(150), Memory())["choice"] == "raise:barracks"
    # before: 0.6 a share whatever the fort (a 50% longing scored 0.30, over every other need here)
    sc = season.score_options(season_fort(None), Memory())
    assert abs(sc["raise:barracks"][0] - 0.5 * 0.6 * season.training_weight(season_fort(None))) < 1e-6, sc
    assert season.training_weight(season_fort(150)) > 1 > season.training_weight(season_fort(0)) \
        > season.training_weight(season_fort(-60)) >= 0.1


@test("D's seasons (Hermit hold, 45-58% long for training) fall under the keep line from training alone")
def _():
    import season
    from planner import Memory
    for share in (0.45, 0.58):
        sc = season.score_options(season_fort(None, training=share, social=0), Memory())
        assert sc.get("raise:barracks", (0,))[0] < season.KEEP_BELOW, (share, sc)


@test("a season's raise:barracks lets the barracks rule act at Militarism 0 with no soldiers (planner_building's gate)")
def _():
    import season
    from harness import code_has
    from planner import Memory
    from planner_building import barracks_wanted
    s = fort(military={"soldiers": 0, "squads": []})      # R-F: no soldiers
    m = Memory()
    assert not barracks_wanted(s, {}, m)
    m.culture = dict(m.culture or {})
    m.culture["season_choice"] = {"choice": "raise:barracks", "until": abs_tick(s) + season.SEASON_TICKS}
    assert barracks_wanted(s, {}, m)
    m.culture["season_choice"]["until"] = abs_tick(s) - 1           # the season over
    assert not barracks_wanted(s, {}, m)
    assert barracks_wanted(s, {"militarism": 50}, None) and barracks_wanted(fort(military={"soldiers": 3}), {}, None)
    from py_parts import py_family_src  # (r7 d4) planner_building and its parts
    src = py_family_src("planner_building")
    assert code_has(src, 'if (allow["barracks"] and barracks_wanted(s, traits, memory)')


if __name__ == "__main__":
    finish()
