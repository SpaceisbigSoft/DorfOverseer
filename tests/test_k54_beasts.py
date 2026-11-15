"""(0.105.54, "fight back") Forgotten beasts, titans and megabeasts get killed,
not only hidden from:

  * planner_matchup.beast_plan: the tactic from the beast's facts (never
    melee at fire, a cloud, dust or webs; melee only about even; crossbows;
    else a cage trap line or the lure pocket, with what is missing);
  * planner_threats: the sealed cavern beast's plan acted on: the squads
    posted at the door (or the crossbows behind a cavern opening's
    fortifications), then the seal opened for the fight and held open; shut
    again when the fight goes badly; kept sealed while it can't be beaten;
  * planner_lure: no lure when the fight is ready;
  * planner_military: a dust or web beast on the surface or inside: no melee
    squad, crossbows from a safe spot.

    python tests/test_k54_beasts.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, plan, PLANNER_CONFIG, TICKS_PER_DAY, abs_tick  # noqa: E402
import planner_matchup as PM  # noqa: E402
import planner_threats as PT  # noqa: E402

BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
CFG = PLANNER_CONFIG
DOOR = {"x": 5, "y": 6, "z": 121}


def squad(i, melee=0.0, ranged=0.0, crossbow=False, **kw):
    q = {"id": i, "name": f"Squad{i}", "members": 6, "size": 10, "leader": True, "orders": 0, "ai_orders": 0,
         "power": {"power": melee + ranged, "melee_power": melee, "ranged_power": ranged, "armed": 6,
                   "ranged": 6 if ranged else 0}}
    if crossbow:
        q["ai_uniform"] = "crossbow leather"
    q.update(kw)
    return q


def beast(**kw):
    t = {"id": 50, "name": "Ozkak", "great_danger": True, "kinds": ["ForgottenBeast"], "facts": 1,
         "size": 60000 * 25, "can_reach_dwarves": False, "layer": "Cavern1", "pos": {"x": 30, "y": 30, "z": 115},
         "distance_to_nearest_dwarf": 200}
    t.update(kw)
    return t


def cave_fort(row=None, squads=(), sealed=True, **kw):
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    door = dict(DOOR, kind="gate", building="Door", built=True, locked=sealed, sealed=sealed)
    s["threats"] = {"sealed": {"all caverns": {"doors": 1, "days": 2}} if sealed else {},
                    "openings": {"list": [door], "n": 1}}
    s["deep"] = {"caverns": [{"name": "Cavern1", "discovered": True, "open": True, "z_top": 120, "z_bottom": 110,
                              "open_at": DOOR, "column": []}],
                 "dangers": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "layer": "Cavern1"}],
                 "cursed": []}
    row = row if row is not None else beast()
    s["others_on_map"]["threats"] = [row]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    s["military"]["squads"] = [copy.deepcopy(q) for q in squads]
    s.update(kw)
    return s


def acts(props, rule=None, typ=None):
    return [p for p in props if (rule is None or p.rule == rule) and (typ is None or p.action.get("type") == typ)]


# --- the plan (pure) ------------------------------------------------------------

@test("beast_plan: never melee a fire breather, a cloud, dust or webs, however strong the melee squads")
def _():
    strong = [squad(1, melee=5000)]
    for facts, word in ((dict(breath=["fire"]), "fire"), (dict(fire_breather=True), "fire"),
                        (dict(breath=["poison_gas"]), "cloud"), (dict(breath=["dust", "deadly"]), "cloud"),
                        (dict(breath=["dust"]), "dust"), (dict(webs=True), "webs"), (dict(breath=["web"]), "webs")):
        p = PM.beast_plan(beast(**facts), strong, 2.0)
        assert p["tactic"] != "melee" and p["no_melee"] and word in p["no_melee"], (facts, p)
        assert not p["ready"] and "a crossbow squad" in p["missing"], p
    # spit or a venom bite: melee is allowed when about even
    p = PM.beast_plan(beast(breath=["spit"]), strong, 2.0)
    assert p["tactic"] == "melee" and p["ready"], p


@test("beast_plan: melee only about even; crossbows when they alone are; else cage traps or the lure, missing said")
def _():
    t = beast()
    need = PM.judge(t, [])["need"]
    assert PM.beast_plan(t, [squad(1, melee=need * 2.1)], 2.0)["tactic"] == "melee"
    # (the bar given: the general engagement bar's) a lower bar lets the same squads go
    assert not PM.beast_plan(t, [squad(1, melee=need * 1.2)], 2.0)["ready"]
    assert PM.beast_plan(t, [squad(1, melee=need * 1.2)], 1.0)["tactic"] == "melee"
    fire = beast(breath=["fire"])
    fneed = PM.judge(fire, [])["need"]
    p = PM.beast_plan(fire, [squad(1, melee=10000), squad(2, ranged=fneed * 2.5, crossbow=True)], 2.0)
    assert p["tactic"] == "ranged" and p["ready"] and "no melee" in p["why"], p
    # crossbows without bolts in the quivers don't count as ready
    q = squad(2, ranged=fneed * 2.5, crossbow=True)
    q["power"]["ranged"] = 0
    p = PM.beast_plan(fire, [q], 2.0)
    assert not p["ready"] and any("bolts" in m for m in p["missing"]), p
    # weak: a cage trap line if traps take it, the lure (drawbridges) if not
    p = PM.beast_plan(beast(), [squad(1, melee=1)], 2.0)
    assert p["tactic"] == "cage" and p["goal"] == "melee" and not p["ready"], p
    p = PM.beast_plan(beast(trap_avoid=True, breath=["fire"]), [squad(1, melee=1)], 2.0)
    assert p["tactic"] == "lure" and p["goal"] == "ranged", p


@test("fight_bar_of: the general engagement bar's fight_bar when there is one, else fight_ratio")
def _():
    import planner_military
    assert PM.fight_bar_of({}, None, {"fight_ratio": 2.0}) == 2.0
    old = getattr(planner_military, "fight_bar", None)
    try:
        planner_military.fight_bar = lambda s, memory, cfg: 1.1
        assert PM.fight_bar_of({}, None, {"fight_ratio": 2.0}) == 1.1
        planner_military.fight_bar = lambda cfg: (0.9, "words")
        assert PM.fight_bar_of({}, None, {"fight_ratio": 2.0}) == 0.9
    finally:
        if old is None:
            del planner_military.fight_bar
        else:
            planner_military.fight_bar = old


# --- the cavern beast: sealed, then killed ----------------------------------------

@test("cavern beast, squads about even and no breath: posted at the door, then the seal opened and the kill ordered")
def _():
    m = Memory()
    sq = [squad(1, melee=500), squad(2, melee=500)]
    s = cave_fort(squads=sq)
    props, notes = plan(s, m)
    st = acts(props, "beast_hunt", "squad_station")
    assert {p.action["squad_id"] for p in st} == {1, 2}, [(p.rule, p.action) for p in props]
    assert all({k: p.action[k] for k in "xyz"} == DOOR for p in st), st
    assert not acts(props, typ="seal_cavern"), "not opened before they're posted"
    assert m.beast_hunt["stage"] == "posting" and m.beast_hunt["tactic"] == "melee", m.beast_hunt
    assert any("Ozkak" in n and "stage: the squads take their posts" in n for n in notes), notes
    # posted: the seal opens, the squads go at it
    for q in s["military"]["squads"]:
        q.update(ai_orders=1, orders=1, stationed=dict(DOOR), sheltering=True)
    props, notes = plan(s, m)
    op = acts(props, "beast_hunt", "seal_cavern")
    assert op and op[0].action == {"type": "seal_cavern", "layer": "all caverns", "open": True}, props
    kill = acts(props, "beast_hunt", "squad_orders")
    assert {p.action["squad_id"] for p in kill} == {1, 2} and all(p.action["kill"] == [50] for p in kill), kill
    assert m.beast_hunt["stage"] == "open", m.beast_hunt
    # open: the lock isn't asked again while the fight is on
    s["threats"]["sealed"] = {}
    s["threats"]["openings"]["list"][0].update(locked=False, sealed=False)
    for q in s["military"]["squads"]:
        q["kill_ids"] = [50]
    props, notes = plan(s, m)
    assert not acts(props, typ="seal_cavern"), [(p.rule, p.action) for p in acts(props, typ="seal_cavern")]
    assert any("stage: the seal is open for the fight" in n for n in notes), notes
    # the fight goes badly (called off): locked again, not tried again for a while
    m.called_off = {"50": abs_tick(s)}
    props, notes = plan(s, m)
    lock = acts(props, "seal_cavern", "seal_cavern")
    assert lock and not lock[0].action.get("open"), [(p.rule, p.action) for p in props if "seal" in p.action.get("type", "")]
    assert m.beast_hunt["stage"] == "sealed" and any("locked again" in n for n in notes), (m.beast_hunt, notes)


@test("cavern beast: the seal opened is locked again after beast_open_days if the fight never came")
def _():
    m = Memory()
    s = cave_fort(squads=[squad(1, melee=500, ai_orders=1, orders=1, kill_ids=[50])], sealed=False)
    m.beast_hunt = {"id": 50, "stage": "open", "opened": abs_tick(s) - 4 * TICKS_PER_DAY, "squads": [1],
                    "tactic": "melee"}
    props, notes = plan(s, m)
    assert acts(props, "seal_cavern", "seal_cavern"), notes
    assert m.beast_hunt["stage"] == "sealed" and m.beast_hunt["retry"] > abs_tick(s)
    assert any("never came" in n for n in notes), notes


@test("cavern fire breather, only melee squads: kept sealed, no post, no opening; the plan and what's missing said")
def _():
    m = Memory()
    s = cave_fort(row=beast(breath=["fire"]), squads=[squad(1, melee=5000)])
    props, notes = plan(s, m)
    assert not acts(props, "beast_hunt"), [(p.rule, p.action) for p in acts(props, "beast_hunt")]
    line = [n for n in notes if n.startswith("Ozkak") and "kept sealed" in n]
    assert line and "it breathes fire: no melee" in line[0] and "missing: a crossbow squad" in line[0], notes
    assert "building toward crossbows" in line[0], line
    # the lure is built after lure_after_days (the squads can't settle it)
    s["threats"]["sealed"]["all caverns"]["days"] = 8
    s["lures"] = {"lures": [], "beasts": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "cavern": True,
                                           "immune": False}],
                  "candidates": [{"key": "5,6,121", "fits": True, "x": 5, "y": 6, "length": 4}], "mechanisms": 20}
    props, notes = plan(s, m)
    assert acts(props, "lure_build", "build_lure"), notes


@test("cavern fire breather, crossbows strong enough and a fortified cavern opening: posted, then the seal opens (no kill order)")
def _():
    m = Memory()
    fire = beast(breath=["fire"])
    need = PM.judge(fire, [])["need"]
    sq = [squad(1, melee=5000), squad(2, ranged=need * 3, crossbow=True)]
    s = cave_fort(row=fire, squads=sq, killzones={"entrances": [{"id": 7, "kind": "cavern", "x": 5, "y": 7, "z": 121,
                                                                  "posts": 3, "fortifications": 3}]})
    props, notes = plan(s, m)
    ap = acts(props, "beast_hunt", "archer_post")
    assert ap and ap[0].action == {"type": "archer_post", "entrance_id": 7, "squads": [2]}, props
    assert not acts(props, "beast_hunt", "squad_station"), "no melee squad is posted at a fire breather"
    s["military"]["squads"][1].update(ai_orders=1, orders=1, guarding=True)
    props, notes = plan(s, m)
    assert acts(props, "beast_hunt", "seal_cavern") and not acts(props, "beast_hunt", "squad_orders"), props
    # the lure isn't built for a fight that's ready
    s2 = cave_fort(row=fire, squads=sq, killzones=s["killzones"])
    s2["threats"]["sealed"]["all caverns"]["days"] = 8
    s2["lures"] = {"lures": [], "beasts": [{"id": 50, "name": "Ozkak", "kind": "forgotten beast", "cavern": True}],
                   "candidates": [{"key": "5,6,121", "fits": True, "x": 5, "y": 6, "length": 4}], "mechanisms": 20}
    props, notes = plan(s2, Memory())
    assert not acts(props, "lure_build") and any("no lure" in n for n in notes), notes
    # no fortified cavern opening: kept sealed, the fortifications said missing
    s3 = cave_fort(row=fire, squads=sq)
    props, notes = plan(s3, Memory())
    assert not acts(props, "beast_hunt") and any("missing: fortifications at a cavern opening" in n for n in notes), notes


@test("two great beasts below, or citizens in the caverns: the seal stays shut")
def _():
    s = cave_fort(squads=[squad(1, melee=500), squad(2, melee=500)])
    s["deep"]["dangers"].append({"id": 51, "name": "Zas", "kind": "forgotten beast", "layer": "Cavern1"})
    props, notes = plan(s, Memory())
    assert not acts(props, "beast_hunt") and any("one at a time" in n for n in notes), notes
    s = cave_fort(squads=[squad(1, melee=500)])
    s["threats"]["cavern_citizens"] = {"n": 1, "list": [{"id": 3, "name": "Kib", "x": 9, "y": 9, "z": 115}]}
    props, notes = plan(s, Memory())
    assert not acts(props, "beast_hunt", "seal_cavern"), props


# --- a beast on the surface or inside ------------------------------------------------

@test("a dust-breathing beast inside: no melee squad (one on it comes back); the crossbows shoot")
def _():
    s = copy.deepcopy(BASE)
    row = beast(breath=["dust", "deadly"], can_reach_dwarves=True, layer="fort_levels", distance_to_nearest_dwarf=5)
    need = PM.judge(row, [])["need"]
    s["others_on_map"]["threats"] = [row]
    s["others_on_map"]["threats_that_can_reach_dwarves"] = 1
    s["entrances"]["intruders_inside"] = [50]
    s["military"]["squads"] = [squad(1, melee=5000, ai_orders=1, orders=1, kill_ids=[50]),
                               squad(2, ranged=need * 3, crossbow=True)]
    props, notes = plan(s, Memory())
    rec = [p for p in props if p.action.get("squad_id") == 1]
    assert rec and all(p.action.get("clear") or p.action.get("type") == "shelter_squads" for p in rec), \
        [(p.rule, p.action) for p in rec]
    shoot = [p for p in props if p.action.get("type") == "squad_orders" and p.action.get("squad_id") == 2]
    assert shoot and 50 in shoot[0].action["kill"], [(p.rule, p.action) for p in props if "squad" in p.action.get("type", "")]
    assert not [p for p in props if p.action.get("type") == "squad_orders" and p.action.get("squad_id") == 1
                and 50 in (p.action.get("kill") or [])]
    assert any("no melee" in n and "stage: shooting" in n for n in notes), notes
    # crossbows too weak: they hide, and it says what's missing
    s["military"]["squads"][1]["power"].update(power=1, ranged_power=1)
    props, notes = plan(s, Memory())
    assert not [p for p in props if p.action.get("type") == "squad_orders" and 50 in (p.action.get("kill") or [])]
    assert any("stage: hiding" in n and "more crossbows" in n for n in notes), notes


if __name__ == "__main__":
    finish()
