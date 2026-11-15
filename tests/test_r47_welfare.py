"""(0.105.47, I7b) Unhappiness from the unburied dead and ghosts, and welfare
rules that switched off in small forts.

  * coffins anywhere (planner_welfare burial_corner): after a season of the
    dead outnumbering the free tombs, a week after a tomb level's search
    failed, or at once when 10+ more wait with no tomb level under way; not
    while the Rules switch for tomb levels is off; their coffins ordered;
  * memorial slabs ahead for the dead nobody can reach (slabs_ahead), blanks
    for them, the engraved ones put up while no ghost walks;
  * recreation from 5 citizens, scaled (a quarter of a small fort at most);
  * lavish meals past meals_hard_max_pd while good meals are short and a
    quarter of the fort badly wants one; a cook trained in a small fort;
  * stress care: never a child; the long-term stress read for every listed
    dwarf; the top unmet need answered when bedroom and squad aren't it;
  * lua/ai-welfare.lua in a fake fort (dead_scan, engrave_memorials, corner
    coffins, open_tombs, train_cook, report, arrivals) and the wiring
    (bridge, report, builder, digest, overseer).

    python tests/test_r47_welfare.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "brain"))
from harness import test, finish, skip  # noqa: E402
from lua_modules_util import module_src  # noqa: E402
from planner import PLANNER_CONFIG, Memory, plan  # noqa: E402
from planner_core import Proposal, AGENDA_THEMES  # noqa: E402
import planner_welfare as W  # noqa: E402
import planner_society as PS  # noqa: E402
from digest import SECTION_DEFAULTS, digest, normalize  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG
DAY = 1200
YEAR = 403200
LUA = ROOT / "lua"


def st(dead=None, welfare=None, projects=None, tick=0, year=262, pop=28, **extra) -> dict:
    s = {"settings": {"traits": {}, "fort_goal": "expand"}, "dwarves": {"total": pop},
         "date": {"year": year, "tick": tick}, "dead": dead or {}, "welfare": welfare or {},
         "projects": {"open": projects or []}, "orders": [], "_errors": {},
         "buildings": {"workshops": {"Masons": 1, "Carpenters": 1, "Kitchen": 1}},
         "stocks": {"wood": 50}, "supplies": {"slabs": 0}}
    s.update(extra)
    return s


def run(s, memory=None, rules_=None):
    props, notes = [], []
    W._welfare_rules(s, CFG, props, notes, memory, rules_ or {})
    return props, notes


def by(props, rule):
    return [p for p in props if p.rule == rule]


def c_max(p):
    c = by(p, "burial_corner")
    return c[0].action["max"] if c else None


# ---- coffins anywhere ---------------------------------------------------------------------

@test("burial_corner: the dead outnumber the free tombs a season with no tomb level come: coffins anywhere")
def _():
    m = Memory()
    dead = {"unburied": 6, "free_tombs": 0, "why": {"free": 6}}
    p, _ = run(st(dead, tick=0), m)
    assert not by(p, "burial_corner") and m.welfare["short_since"] == 262 * YEAR, (p, m.welfare)
    p, _ = run(st(dead, tick=40 * DAY), m)
    assert not by(p, "burial_corner"), p
    p, _ = run(st(dead, tick=84 * DAY), m)
    c = by(p, "burial_corner")
    assert c and c[0].action == {"type": "coffins_anywhere", "max": 6} and "84 days" in c[0].reason, c
    # a tomb level open but stalled a season: still the fallback
    p, _ = run(st(dead, tick=90 * DAY, projects=[{"kind": "tombs"}]), m)
    assert by(p, "burial_corner"), p
    # enough tombs again: the clock is forgotten
    run(st({"unburied": 6, "free_tombs": 6, "why": {"free": 6}}, tick=91 * DAY), m)
    assert "short_since" not in m.welfare, m.welfare


@test("burial_corner: a week after a tomb level's search failed ('no safe level found'), or at once with 10+ more dead")
def _():
    m = Memory()
    key = 'tombs_ghosts:' + json.dumps({"kind": "tombs", "type": "start_project"}, sort_keys=True)
    m.refusals = {key: {"n": 3, "at": 262 * YEAR + 2 * DAY, "until": 262 * YEAR + 20 * DAY, "why": "no safe level found near 1 staircase(s)"}}
    dead = {"unburied": 4, "free_tombs": 0, "why": {"free": 4}}
    run(st(dead, tick=0), m)
    p, _ = run(st(dead, tick=5 * DAY), m)
    assert not by(p, "burial_corner"), p
    p, _ = run(st(dead, tick=8 * DAY), m)
    c = by(p, "burial_corner")
    assert c and "search failed" in c[0].reason and c[0].action["max"] == 4, c
    # many more dead than tombs, nothing under way: at once
    m2 = Memory()
    p, _ = run(st({"unburied": 190, "free_tombs": 0, "why": {"free": 150, "unreachable": 40}}), m2)
    c = by(p, "burial_corner")
    assert c and c[0].action["max"] == CFG["burial_corner_max"] and "150 more dead" in c[0].reason, c
    # ...but not while a tomb level is being dug (its own season first)
    p, _ = run(st({"unburied": 190, "free_tombs": 0, "why": {"free": 150}}, projects=[{"kind": "tombs"}]), Memory())
    assert not by(p, "burial_corner"), p


@test("burial_corner: the unreachable, the outside and other civs' dead aren't counted; coffins already placed are")
def _():
    m = Memory()
    p, _ = run(st({"unburied": 30, "free_tombs": 0, "why": {"free": 2, "unreachable": 28}}), m)
    assert not by(p, "burial_corner"), p
    p, _ = run(st({"unburied": 30, "free_tombs": 2, "why": {"free": 20}},
                  welfare={"corner": {"placed": 10, "built": 2, "waiting": 8}}), Memory())
    assert c_max(p) == 10, p



@test("burial_corner: not while the Rules switch for tomb levels is off, nor with the welfare section failed")
def _():
    s = st({"unburied": 50, "free_tombs": 0, "why": {"free": 50}})
    s["settings"]["levels"] = {"tombs": False}
    p, _ = run(s, Memory())
    assert not by(p, "burial_corner"), p
    s = st({"unburied": 50, "free_tombs": 0, "why": {"free": 50}})
    s["_errors"] = {"welfare": "boom"}
    p, _ = run(s, Memory())
    assert not by(p, "burial_corner"), p
    s["_errors"] = {"dead": "boom"}
    p, _ = run(s, Memory())
    assert not p, p


@test("burial_coffins: the placed coffins' items ordered (stone; wood while stone is short), never twice")
def _():
    s = st({"unburied": 0, "free_tombs": 0}, welfare={"corner": {"placed": 6, "built": 1, "waiting": 5},
                                                      "coffin_items": 2},
           stocks={"wood": 50, "stone_usable": 500})
    p, _ = run(s, Memory())
    c = by(p, "burial_coffins")
    assert c and c[0].action == {"type": "work_order", "recipe": "stone_coffin", "amount": 3} and c[0].is_order, c
    s["orders"] = [{"recipe": "stone_coffin", "amount_left": 3}]
    p, _ = run(s, Memory())
    assert not by(p, "burial_coffins"), p
    s["orders"] = []
    s["welfare"]["coffin_items"] = 5
    p, _ = run(s, Memory())
    assert not by(p, "burial_coffins"), p


# ---- memorial slabs ahead -----------------------------------------------------------------

@test("slabs_ahead: memorials ordered for the dead nobody can reach before a ghost rises; blanks for them")
def _():
    dead = {"unburied": 0, "free_tombs": 5, "unreachable_dead": 9, "unreachable_bodies": 7, "gone_bodies": 2,
            "unreachable_no_slab": 8, "memorials_wanted": 8, "memorial_orders": 0, "ghosts": 0}
    s = st(dead, stocks={"wood": 0, "stone_usable": 500})
    p, notes = run(s, Memory())
    a = by(p, "slabs_ahead")
    assert a and a[0].action == {"type": "engrave_memorials", "max": CFG["slabs_ahead_max"]}, a
    assert "before their ghosts rise" in a[0].reason
    b = by(p, "slabs_ahead_blanks")
    assert b and b[0].action == {"type": "work_order", "recipe": "stone_slab", "amount": 8}, b
    assert any("9 of the fort's dead can't be reached (7 out of the dwarves' walk, 2 with no body left), 8 with "
               "no memorial slab" in n for n in notes), notes
    # blanks enough, or already ordered (this cycle by the ghosts' rule): no second order
    s["supplies"]["slabs"] = 10
    assert not by(run(s, Memory())[0], "slabs_ahead_blanks")
    s["supplies"]["slabs"] = 0
    props = [Proposal("slabs", {"type": "work_order", "recipe": "stone_slab", "amount": 3}, "x", 3, True)]
    W._welfare_rules(s, CFG, props, [], Memory(), {})
    assert not by(props, "slabs_ahead_blanks"), props


@test("slabs_ahead: not with the Rules switch for slabs off; a note with no mason's workshop; engraved ones put up")
def _():
    dead = {"memorials_wanted": 3, "unreachable_dead": 3}
    p, _ = run(st(dead), Memory(), {"engrave_slabs": False})
    assert not by(p, "slabs_ahead"), p
    s = st(dead)
    s["buildings"]["workshops"] = {"Kitchen": 1}
    p, notes = run(s, Memory())
    assert not by(p, "slabs_ahead") and any("once the fort has a mason's workshop" in n for n in notes), notes
    s = st({"ghosts": 0})
    s["supplies"]["memorial_slabs"] = 4
    pl = by(run(s, Memory())[0], "slabs_ahead_place")
    assert pl and pl[0].action == {"type": "place_slabs", "max": 4}, pl
    s["dead"]["ghosts"] = 2                       # the ghosts' own slabs rule does it then
    assert not by(run(s, Memory())[0], "slabs_ahead_place")


# ---- recreation in small forts ------------------------------------------------------------

def rec_state(pop, lonely=0):
    return {"settings": {"traits": {}}, "dwarves": {"total": pop}, "date": {"year": 260, "tick": 0},
            "society": {"recreation": {"members": 0}}, "others_on_map": {},
            "needs": {"needs": {"BeWithFriends": {"badly": lonely}}}}


@test("recreation: from 5 citizens (was 30); a fort of 8 gets 2 places and 1 for friends; under 5 none")
def _():
    assert CFG["recreation_min_citizens"] == 5
    worst = [{"id": i, "stress": "miserable"} for i in range(1, 5)]
    props = []
    PS._recreation_rule(rec_state(8, lonely=4), CFG, worst, props)
    assert props and props[0].action["max"] == 2 and props[0].action["friends"] == 1, props
    props = []
    PS._recreation_rule(rec_state(28, lonely=10), CFG, worst, props)
    assert props and props[0].action["max"] == 7 and props[0].action["friends"] == 3, props
    props = []
    PS._recreation_rule(rec_state(4), CFG, worst, props)
    assert not props, props
    props = []                                    # a big fort as before
    PS._recreation_rule(rec_state(95), CFG, worst, props)
    assert props[0].action["max"] == 8, props


# ---- good meals and a cook ----------------------------------------------------------------

def meal_state(pop=8, meals=800, good=0, badly=6, distracted=6):
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = pop
    s["stocks"]["prepared_meals"] = meals
    s["supplies"].update(good_meals=good, meal_servings=meals)
    s["needs"] = {"needs": {"EatGoodMeal": {"badly": badly, "distracted": distracted}}}
    s["orders"] = []
    return s


@test("needs_meal: past meals_hard_max_pd (100 plain meals a dwarf) lavish meals still, while good ones are short and a quarter badly want one")
def _():
    props = []
    PS._needs_rules(meal_state(), CFG, props, {})
    m = by(props, "needs_meal")
    assert m and m[0].action["recipe"] == "prepare_lavish_meal", props
    props = []
    PS._needs_rules(meal_state(badly=1, distracted=6), CFG, props, {})        # 1 of 8 badly: the cap holds
    assert not by(props, "needs_meal"), props
    props = []
    PS._needs_rules(meal_state(good=40), CFG, props, {})                     # 5 good a dwarf: none wanted
    assert not by(props, "needs_meal"), props


@test("train_cook: a fort of 8 whose best cook is skill 1 and wants good meals keeps one cook at the kitchens")
def _():
    s = st(pop=8, needs={"needs": {"EatGoodMeal": {"badly": 6, "distracted": 6}}})
    s["supplies"] = {"good_meals": 0, "cooks": {"best": 1, "best_any": 1, "kitchen_min": 0, "able_skills": [1, 0]}}
    c = by(run(s, Memory())[0], "train_cook")
    assert c and c[0].action == {"type": "train_cook"} and "skill 1" in c[0].reason, c
    # kept: not asked again while the trainee can cook...
    s["welfare"] = {"cook": {"unit": 7, "name": "Urist", "free": True, "skill": 2}}
    assert not by(run(s, Memory())[0], "train_cook")
    # ...the next best when they can't
    s["welfare"]["cook"]["free"] = False
    c = by(run(s, Memory())[0], "train_cook")
    assert c and "next best" in c[0].reason, c
    # the fort grew: the kitchens open to every cook
    s["dwarves"]["total"] = 60
    c = by(run(s, Memory())[0], "train_cook")
    assert c and c[0].action == {"type": "train_cook", "release": True}, c


@test("train_cook: not with a good cook, nor in a big fort, nor with no kitchen, nor when nobody wants a good meal")
def _():
    base = st(pop=8, needs={"needs": {"EatGoodMeal": {"badly": 6}}})
    base["supplies"] = {"good_meals": 0, "cooks": {"best": 6, "best_any": 6}}
    assert not by(run(base, Memory())[0], "train_cook")
    s = copy.deepcopy(base); s["supplies"]["cooks"] = {"best": 1}; s["dwarves"]["total"] = 80
    assert not by(run(s, Memory())[0], "train_cook")
    s = copy.deepcopy(base); s["supplies"]["cooks"] = {"best": 1}; s["buildings"]["workshops"] = {}
    assert not by(run(s, Memory())[0], "train_cook")
    s = copy.deepcopy(base); s["supplies"]["cooks"] = {"best": 1}; s["needs"] = {"needs": {}}
    assert not by(run(s, Memory())[0], "train_cook")


# ---- stress care --------------------------------------------------------------------------

def care_state(stressed, welfare=80, **extra):
    s = {"settings": {"traits": {"welfare": welfare}, "rules": {}}, "dwarves": {"total": 28},
         "date": {"year": 262, "tick": 0}, "others_on_map": {}, "orders": [],
         "noble_rooms": {"free": {"bedroom": 3}}, "buildings": {"workshops": {"Kitchen": 1, "Craftsdwarfs": 1}},
         "needs": {"stressed": stressed, "needs": {}, "trinkets": 5, "idle_crafting": {}}}
    s.update(extra)
    return s


def care(s):
    props = []
    PS._stress_care(s, CFG, [x for x in s["needs"]["stressed"]], props, Memory())
    return [p for p in props if p.rule == "stress_care"]


@test("stress_care: never a child or baby (a Dwarven Baby was asked a bedroom four times)")
def _():
    baby = {"id": 5, "name": "Baby", "stress": "miserable", "bedroom": False, "child": True, "unmet": []}
    assert not care(care_state([baby]))
    adult = dict(baby, id=6, name="Adult", child=None)
    p = care(care_state([baby, adult]))
    assert p and p[0].action == {"type": "give_room", "unit_id": 6, "kind": "bedroom"}, p


@test("stress_care: bedroom and squad aren't it: the top unmet need answered (a lavish meal, trinkets, crafting; prayer and friends by the recreation stay)")
def _():
    x = {"id": 9, "name": "Kib", "stress": "miserable", "bedroom": True, "unmet": ["Fight", "EatGoodMeal"],
         "wants_fight": True, "longterm": 120000}
    p = care(care_state([x]))
    assert p and p[0].action == {"type": "work_order", "recipe": "prepare_lavish_meal", "amount": 5}, p
    assert "long-term stress 120000" in p[0].reason and p[0].priority == 3, p
    x["unmet"] = ["AcquireObject"]
    p = care(care_state([x]))
    assert p and p[0].action == {"type": "give_trinkets", "max": 3}, p
    x["unmet"] = ["CraftObject"]
    p = care(care_state([x]))
    assert p and p[0].action == {"type": "idle_crafting"}, p
    # prayer and friends: the recreation rule's stay (this dwarf among the most stressed); the next need
    x["unmet"] = ["PrayOrMeditate", "BeWithFriends", "EatGoodMeal"]
    p = care(care_state([x]))
    assert p and p[0].action["recipe"] == "prepare_lavish_meal", p
    x["unmet"] = ["PrayOrMeditate"]
    assert not care(care_state([x]))
    props = []
    PS._needs_notes(care_state([x]), CFG, [], props, Memory())
    assert [q.rule for q in props if q.action.get("type") == "recreation"] == ["recreation"], props
    x["unmet"] = ["Fight", "MartialTraining"]           # the squads' (planner_military), not stress care's
    assert not care(care_state([x]))


@test("stress_care and needs_meal: one lavish order a cycle (the fort's rule when it orders; stress care's only when it doesn't)")
def _():
    s = meal_state(pop=96, meals=5890, good=159, badly=37, distracted=37)
    s["needs"]["stressed"] = [{"id": 9, "name": "Likot", "stress": "miserable", "bedroom": True, "unmet": ["EatGoodMeal"]}]
    s["noble_rooms"] = {"free": {"bedroom": 0}}
    props, _ = plan(normalize(s), Memory())
    lav = [p.rule for p in props if p.action.get("recipe") == "prepare_lavish_meal"]
    assert lav == ["needs_meal"], lav
    # with the cap off stress care's own (what main did: none)
    assert PS.lavish_due(s, CFG) and not PS.lavish_due(s, dict(CFG, meals_cap_skip_share=99))


@test("stress_care: the long-term stress read for every listed dwarf: very unhappy for years counts at Welfare 0, the worst first")
def _():
    a = {"id": 1, "name": "A", "stress": "very_unhappy", "bedroom": True, "unmet": ["EatGoodMeal"], "longterm": 5000}
    b = {"id": 2, "name": "B", "stress": "very_unhappy", "bedroom": True, "unmet": ["EatGoodMeal"],
         "longterm": 120000}
    p = care(care_state([a, b], welfare=0))
    assert p and "B is very unhappy" in p[0].reason and "near breaking" in p[0].reason, p
    assert not care(care_state([a], welfare=0))


@test("report: each stressed dwarf's long-term stress, birth and arrival year, child; the count of the dead nobody can reach")
def _():
    src = (LUA / "ai-bridge-report.lua").read_text(encoding="utf-8")
    i = src.index("function get_needs")
    body = src[i:src.index("\nend\n", i)]
    for k in ("row.child = true", "row.longterm = u.status.current_soul.personality.longterm_stress",
              "row.born = u.birth_year", "reqscript('ai-welfare').arrivals(hfs)", "r.arrived = years[r.hf]"):
        assert k in body, k
    i = src.index("function get_dead")
    body = src[i:src.index("\nend\n", i)]
    for k in ("out.unreachable_dead = sc.total", "out.memorials_wanted = sc.wanting", "out.unreachable_no_slab"):
        assert k in body, k
    # the digest's DEAD line carries the count (every whole number of the section)
    s = normalize(copy.deepcopy(BASE))
    s["dead"]["unreachable_dead"] = 12
    assert "unreachable_dead:12" in digest(s), digest(s)[:400]


@test("memory: welfare's short_since is kept in the save")
def _():
    m = Memory()
    m.welfare = {"short_since": 1234}
    assert Memory.from_dict(json.loads(json.dumps(m.to_dict()))).welfare == {"short_since": 1234}


@test("plan(): the welfare rules run from plan() (a fort of 8 with the dead out of reach and no good cook)")
def _():
    s = copy.deepcopy(BASE)
    s["dwarves"]["total"] = 8
    s["dead"].update(memorials_wanted=3, unreachable_dead=3, unburied=40, free_tombs=0, why={"free": 40})
    s["supplies"].update(good_meals=0, cooks={"best": 1, "best_any": 1})
    s["needs"] = {"needs": {"EatGoodMeal": {"badly": 6, "distracted": 6}}, "stressed": []}
    s["welfare"] = {"corner": {"placed": 0, "built": 0, "waiting": 0}, "coffin_items": 0}
    props, _ = plan(s, Memory())
    rules = {p.rule for p in props}
    assert {"slabs_ahead", "burial_corner", "train_cook"} <= rules, sorted(rules)


# ---- wiring -------------------------------------------------------------------------------

@test("wiring: actions, dry runs, the welfare section, the module list, the caches, labels, digest, themes")
def _():
    b = (LUA / "ai-bridge.lua").read_text(encoding="utf-8")
    for a in ("coffins_anywhere", "engrave_memorials", "train_cook"):
        assert re.search(r"\n    %s = function\(a\)" % a, b), a
        assert "'%s'" % a in b[b.index("DRY_OK = {}"):b.index("}) do DRY_OK[name] = true end")], a
        assert f"CACHE_INVALIDATES.{a} = " in b, a
    assert "welfare = function() return safe(function() return reqscript('ai-welfare').report() end) end" in b
    assert "'ai-welfare'" in b[b.index("BRIDGE_MODULES = {"):b.index("MARKED_MODULES")]
    assert "welfare" in SECTION_DEFAULTS
    import overseer
    for a in ("coffins_anywhere", "engrave_memorials", "train_cook"):
        assert a in overseer.ACTION_LABELS if hasattr(overseer, "ACTION_LABELS") else a in (ROOT / "brain" / "overseer.py").read_text()
    for r in ("burial_corner", "burial_coffins", "slabs_ahead", "slabs_ahead_blanks", "slabs_ahead_place", "train_cook"):
        assert r in AGENDA_THEMES, r
    acts = (LUA / "ai-bridge-actions.lua").read_text(encoding="utf-8")
    i = acts.index("function act_allow_burial")
    assert "reqscript('ai-welfare').corner_areas()" in acts[i:acts.index("\nend\n", i)]
    proj = (LUA / "ai-builder-projects.lua").read_text(encoding="utf-8")
    assert proj.count("reqscript('ai-welfare').open_tombs(project_areas(p))") == 2
    rep = (LUA / "ai-bridge-report.lua").read_text(encoding="utf-8")
    i = rep.index("function in_ai_tombs")
    assert "corner_areas()" in rep[i:rep.index("\nend\n", i)]


# ---- lua/ai-welfare.lua in a fake fort ----------------------------------------------------

FAKE = r"""
local src = ...
local W = {units = {}, cits = {}, byid = {}, corpses = {}, slabs = {}, coffins = {}, hfs = {}, site = {},
           unreach = {}, spots = {}, taken = {}, qf = {}, kitchens = {}, tombs = {}, bat = {}, events = {}}
local function vec(t)
    return setmetatable(t or {}, {__index = {insert = function(self, _, v) table.insert(self, v) end,
                                             erase = function(self, i) table.remove(self, i + 1) end}})
end
W.vec = vec
local function key(p) return p.x .. ',' .. p.y .. ',' .. p.z end
W.key = key
local orders = vec({})
local env = setmetatable({}, {__index = _G})
env.xyz2pos = function(x, y, z) return {x = x, y = y, z = z} end
local events = setmetatable({}, {__len = function() return #W.events end,
                                 __index = function(_, i) return W.events[i + 1] end})
env.df = {
    global = {plotinfo = {race_id = 1, civ_id = 10, group_id = 99, site_id = 5}, cur_year = 262, cur_year_tick = 0,
              world = {units = {all = W.units}, items = {other = {CORPSE = W.corpses, SLAB = W.slabs, COFFIN = W.coffins}},
                       manager_orders = {all = orders, manager_order_next_id = 100},
                       buildings = {other = {WORKSHOP_ANY = W.kitchens, ZONE_TOMB = W.tombs}},
                       history = {events = events}}},
    slab_engraving_type = {Memorial = 'Memorial'},
    job_type = {EngraveSlab = 'EngraveSlab'},
    manager_order = {new = function() return {status = {}} end},
    historical_figure = {find = function(id) return W.hfs[id] end},
    unit = {find = function(id) return W.byid[id] end},
    workshop_type = {Kitchen = 'Kitchen'},
    building_type = {Coffin = 'Coffin'},
    job_skill = {COOK = 'COOK'},
    unit_labor = {COOK = 'COOK'},
    item_type = setmetatable({}, {__index = function(_, k) return k end}),
    history_event_change_hf_statest = {is_instance = function(_, e) return e.kind == 'state' end},
}
env.dfhack = {
    units = {isDead = function(u) return u.dead == true end, isGhost = function(u) return u.ghost == true end,
             getReadableName = function(u) return u.nm or ('Dwarf ' .. u.id) end,
             getPosition = function(u) return u.pos.x, u.pos.y, u.pos.z end,
             getCitizens = function() local o = {} for _, u in ipairs(W.cits) do o[#o + 1] = u end return o end,
             isAlive = function(u) return not u.dead end, isAdult = function(u) return not u.child end,
             isSane = function(u) return not u.insane end, getNoblePositions = function(u) return u.noble or {} end,
             getNominalSkill = function(u) return u.cook or 0 end},
    items = {getPosition = function(it) return it.pos.x, it.pos.y, it.pos.z end},
    maps = {canWalkBetween = function(a, b) return not W.unreach[key(b)] end},
    buildings = {findAtTile = function(p) return W.bat[key(p)] end},
    persistent = {getSiteData = function(k, d) local v = W.site[k]; if v == nil then return d end return v end,
                  saveSiteData = function(k, v) W.site[k] = v end},
}
local B = {}
function B.load_projects() return {list = W.projects or {}} end
function B.project_areas(p) return {p.area} end
function B.zone_spots(a) return W.spots[a.z] or {} end
function B.tile_taken(x, y, z) return W.taken[x .. ',' .. y .. ',' .. z] == true end
function B.tile_info(x, y, z) return {shape = 'FLOOR'} end
function B.qf_try(mode, cells, z, x, y, dry)
    table.insert(W.qf, {mode = mode, text = cells[1].text, x = x, y = y, z = z, dry = dry})
    return true, nil, {}
end
env.reqscript = function(n) if n == 'ai-builder' then return B end error('no module ' .. tostring(n)) end
W.orders = orders
assert(load(src, 'ai-welfare', 't', env))()
-- helpers to build the fort
function W.citizen(t)
    t.pos = t.pos or {x = 10, y = 10, z = 100}
    t.race = t.race or 1; t.civ_id = t.civ_id or 10
    t.military = t.military or {squad_id = -1}
    t.status = t.status or {labors = {}}
    t.flags1 = t.flags1 or {}
    table.insert(W.units, t); W.byid[t.id] = t
    if not t.dead then table.insert(W.cits, t) end
    if t.hist_figure_id then W.hfs[t.hist_figure_id] = W.hfs[t.hist_figure_id] or {entity_links = {{entity_id = 99}}} end
    return t
end
function W.kitchen(id, workers)
    local b = {id = id, type = 'Kitchen', profile = {permitted_workers = vec(workers or {}), min_level = 3}}
    function b:getBuildStage() return 1 end
    function b:getMaxBuildStage() return 1 end
    table.insert(W.kitchens, b)
    return b
end
return env, W
"""


def lua_world():
    lua = LuaRuntime(unpack_returned_tuples=True)
    env, w = lua.execute(FAKE, module_src("ai-welfare.lua"))
    return lua, env, w


def T(lua, d):
    if isinstance(d, dict):
        return lua.table_from({k: T(lua, v) for k, v in d.items()})
    if isinstance(d, list):
        return lua.table_from([T(lua, v) for v in d])
    return d


def py(v):
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    try:
        keys = list(v.keys())
    except AttributeError:
        return v
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [py(v[k]) for k in sorted(keys)]
    return {k: py(v[k]) for k in keys}


def need_lua():
    """(0.105.48) without lupa the test is skipped (and counted so), not passed."""
    if LuaRuntime is None:
        skip("needs the lupa package (pip install lupa)")
    return True


def dead_fort(lua, w):
    w.citizen(T(lua, {"id": 1, "nm": "Alive"}))                                   # the anchor
    w.citizen(T(lua, {"id": 2, "nm": "Drowned", "dead": True, "hist_figure_id": 202}))
    w.citizen(T(lua, {"id": 3, "nm": "Buried", "dead": True, "hist_figure_id": 203}))
    w.citizen(T(lua, {"id": 4, "nm": "Gone", "dead": True, "hist_figure_id": 204}))
    w.citizen(T(lua, {"id": 5, "nm": "Ghost", "dead": True, "ghost": True, "hist_figure_id": 205}))
    w.citizen(T(lua, {"id": 6, "nm": "Slabbed", "dead": True, "hist_figure_id": 206}))
    w.citizen(T(lua, {"id": 7, "nm": "Merchant", "dead": True, "hist_figure_id": 207, "flags1": {"merchant": True}}))
    w.citizen(T(lua, {"id": 8, "nm": "Lying", "dead": True, "hist_figure_id": 208}))
    w.citizen(T(lua, {"id": 9, "nm": "Ordered", "dead": True, "hist_figure_id": 209}))
    w.citizen(T(lua, {"id": 10, "nm": "Elsewhere", "dead": True, "hist_figure_id": 210}))
    w.hfs[210] = T(lua, {"entity_links": [{"entity_id": 55}]})                  # never one of the fort's
    w.unreach["50,50,40"] = True
    corpses = [(2, (50, 50, 40), False), (3, (1, 1, 100), True), (6, (50, 50, 40), False),
               (8, (11, 11, 100), False), (9, (50, 50, 40), False), (10, (50, 50, 40), False),
               (7, (50, 50, 40), False)]
    for uid, (x, y, z), inb in corpses:
        w.corpses[len(w.corpses) + 1] = T(lua, {"unit_id": uid, "pos": {"x": x, "y": y, "z": z},
                                               "flags": {"in_building": inb}})
    w.slabs[1] = T(lua, {"engraving_type": "Memorial", "topic": 206})
    w.orders.insert(w.orders, "#", T(lua, {"job_type": "EngraveSlab", "hist_figure_id": 209}))


@test("ai-welfare dead_scan: the fort's dead out of reach or gone, those without a slab or an order, never a ghost, visitor or stranger")
def _():
    if not need_lua():
        return
    lua, env, w = lua_world()
    dead_fort(lua, w)
    r = py(env.dead_scan())
    assert r["unreachable"] == 3 and r["gone"] == 1 and r["total"] == 4, r        # 2, 6, 9 out of reach; 4 gone
    assert r["without_slab"] == 3 and r["ordered"] == 1 and r["wanting"] == 2, r
    assert [x["name"] for x in r["wanted"]] == ["Drowned", "Gone"] and r["wanted"][0]["why"] == "unreachable", r


@test("ai-welfare engrave_memorials: an approved EngraveSlab order naming each; the dry run orders nothing; then nothing to do")
def _():
    if not need_lua():
        return
    lua, env, w = lua_world()
    dead_fort(lua, w)
    r = py(env.engrave_memorials(5, True))
    assert r["ok"] and r["ordered"] == ["Drowned", "Gone"] and len(w.orders) == 1, r
    r = py(env.engrave_memorials(5, False))
    assert r["ok"] and r["order_ids"] == [100, 101] and len(w.orders) == 3, r
    o = w.orders[2]
    assert o.job_type == "EngraveSlab" and o.hist_figure_id == 202 and o.amount_total == 1 and o.status.validated
    r = py(env.engrave_memorials(5, False))
    assert r["ok"] is False and r.get("nothing_to_do"), r


@test("ai-welfare corner coffins: the fittest finished level first, never side by side, never lived-in or taken; a tomb each; kept; dry run keeps nothing")
def _():
    if not need_lua():
        return
    lua, env, w = lua_world()
    w.citizen(T(lua, {"id": 1}))
    w.projects = T(lua, [
        {"kind": "bedrooms", "phase": "done", "area": {"x1": 0, "y1": 0, "x2": 9, "y2": 9, "z": 90}},
        {"kind": "workshops", "phase": "done", "area": {"x1": 0, "y1": 0, "x2": 9, "y2": 9, "z": 91}},
        {"kind": "storage", "phase": "done", "area": {"x1": 0, "y1": 0, "x2": 9, "y2": 9, "z": 92}},
        {"kind": "storage", "phase": "dig", "area": {"x1": 0, "y1": 0, "x2": 9, "y2": 9, "z": 93}},
    ])
    sp = lambda pts: T(lua, [{"x": x, "y": y} for x, y in pts])  # noqa: E731
    w.spots[90] = sp([(1, 1)])
    w.spots[91] = sp([(5, 5), (7, 7)])
    w.spots[92] = sp([(1, 1), (2, 1), (4, 1), (6, 1)])
    w.spots[93] = sp([(1, 1)])
    w.taken["6,1,92"] = True
    r = py(env.place_corner_coffins(4, True))
    assert r["ok"] and r["dry_run"] and [(p["x"], p["z"]) for p in r["placed"]] == [(1, 92), (4, 92), (5, 91), (7, 91)], r
    assert not py(w.site).get("ai-overseer/welfare"), py(w.site)
    r = py(env.place_corner_coffins(3, False))
    assert r["ok"] and r["kept"] == 3, r
    real = [q for q in py(w.qf) if not q["dry"]]
    assert [q["text"] for q in real] == ["n", "T{citizens=true}"] * 3, real
    areas = py(env.corner_areas())
    assert areas[0] == {"x1": 1, "y1": 1, "x2": 1, "y2": 1, "z": 92}, areas
    # nowhere left
    lua, env, w = lua_world()
    r = py(env.place_corner_coffins(3, False))
    assert r["ok"] is False and r["rejected"] and "no free dug floor" in r["error"], r


@test("ai-welfare open_tombs: automatic burial on in the AI's tombs inside the areas, never one set aside for one dwarf")
def _():
    if not need_lua():
        return
    lua, env, w = lua_world()
    for i, (x, owner) in enumerate([(1, -1), (2, 33), (50, -1)]):
        w.tombs[i + 1] = T(lua, {"x1": x, "x2": x, "y1": 1, "y2": 1, "z": 92, "assigned_unit_id": owner,
                                 "zone_settings": {"tomb": {"flags": {"no_citizens": True}}}})
    areas = T(lua, [{"x1": 0, "y1": 0, "x2": 9, "y2": 9, "z": 92}])
    r = py(env.open_tombs(areas, True))
    assert r["opened"] == 1 and w.tombs[1].zone_settings.tomb.flags.no_citizens is True, r
    r = py(env.open_tombs(areas, False))
    assert r["opened"] == 1 and w.tombs[1].zone_settings.tomb.flags.no_citizens is False
    assert w.tombs[2].zone_settings.tomb.flags.no_citizens is True and w.tombs[3].zone_settings.tomb.flags.no_citizens is True


@test("ai-welfare train_cook: the best free cook made the kitchens' only worker and kept; a player's kitchen untouched; the next best when gone; released")
def _():
    if not need_lua():
        return
    lua, env, w = lua_world()
    w.citizen(T(lua, {"id": 1, "nm": "Soldier", "cook": 9, "military": {"squad_id": 3}}))
    w.citizen(T(lua, {"id": 2, "nm": "Child", "cook": 8, "child": True}))
    w.citizen(T(lua, {"id": 3, "nm": "Urist", "cook": 1}))
    w.citizen(T(lua, {"id": 4, "nm": "Kib", "cook": 0}))
    k1 = w.kitchen(50)
    k2 = w.kitchen(51, T(lua, [4]))                       # the player's choice
    r = py(env.train_cook(True, False))
    assert r["ok"] and r["cook"] == "Urist" and len(k1.profile.permitted_workers) == 0, r
    r = py(env.train_cook(False, False))
    assert r["ok"] and r["unit_id"] == 3 and r["kitchens"] == 1 and r["players_kitchens"] == 1, r
    assert list(k1.profile.permitted_workers.values()) == [3] and k1.profile.min_level == 0
    assert list(k2.profile.permitted_workers.values()) == [4]
    assert w.byid[3].status.labors["COOK"] is True
    # kept though another is now better
    w.byid[4].cook = 5
    assert py(env.train_cook(False, False))["unit_id"] == 3
    rep = py(env.report())
    assert rep["cook"]["unit"] == 3 and rep["cook"]["free"] is True and rep["cook"]["skill"] == 1, rep
    # the trainee drafted: the next best
    w.byid[3].military = T(lua, {"squad_id": 2})
    assert py(env.report())["cook"]["free"] is False
    assert py(env.train_cook(False, False))["unit_id"] == 4
    assert list(k1.profile.permitted_workers.values()) == [4]
    r = py(env.train_cook(False, True))
    assert r["released"] == 1 and len(k1.profile.permitted_workers) == 0 and list(k2.profile.permitted_workers.values()) == [4], r
    assert "cook" not in py(env.report())


@test("ai-welfare report: corner coffins built and free, free coffins in store; arrivals from the history, newest first, cached")
def _():
    if not need_lua():
        return
    lua, env, w = lua_world()
    w.site["ai-overseer/welfare"] = T(lua, {"corner": [{"x": 1, "y": 1, "z": 92}, {"x": 4, "y": 1, "z": 92},
                                                       {"x": 7, "y": 1, "z": 92}], "cook": {}})

    def coffin(full):
        b = lua.eval("function(full) local b = {contained_items = full and {{use_mode = 0, item = {getType = function() return 'CORPSE' end}}} or {}}"
                     " function b:getType() return 'Coffin' end function b:getBuildStage() return 1 end"
                     " function b:getMaxBuildStage() return 1 end return b end")(full)
        return b
    w.bat["1,1,92"] = coffin(False)
    w.bat["4,1,92"] = coffin(True)
    w.coffins[1] = T(lua, {"flags": {}})
    w.coffins[2] = T(lua, {"flags": {"in_job": True}})
    r = py(env.report())
    assert r["corner"] == {"placed": 3, "built": 2, "free": 1, "waiting": 1} and r["coffin_items"] == 1, r
    w.events[1] = T(lua, {"kind": "state", "hfid": 11, "site": 5, "year": 250})
    w.events[2] = T(lua, {"kind": "other", "hfid": 12, "site": 5, "year": 255})
    w.events[3] = T(lua, {"kind": "state", "hfid": 12, "site": 6, "year": 256})
    w.events[4] = T(lua, {"kind": "state", "hfid": 12, "site": 5, "year": 262})
    w.events[5] = T(lua, {"kind": "state", "hfid": 11, "site": 5, "year": 258})
    got = py(env.arrivals(T(lua, [11, 12, 13])))
    assert got == {11: 258, 12: 262}, got
    w.events[6] = T(lua, {"kind": "state", "hfid": 11, "site": 5, "year": 263})
    assert py(env.arrivals(T(lua, [11])))[11] == 258                  # kept for the session


if __name__ == "__main__":
    finish()
