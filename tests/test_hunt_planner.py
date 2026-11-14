"""(0.105.45) Hunting (brain/planner_hunt.py): a threat that can't reach the
dwarves yet judged against the fort's squads, a party sent when it clearly
wins, a reserve kept home, the retreat when it goes badly, what is learned
from the outcomes (once each); the Rules switch `hunt` (off / small / ai) in
the settings and the window; the wiring in planner.py and note_cycle.

    python tests/test_hunt.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, code_has  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, note_cycle  # noqa: E402
import planner_hunt as PH  # noqa: E402
from planner_core import Proposal, abs_tick, player_rules  # noqa: E402
from planner_military import threat_power  # noqa: E402
from digest import normalize, SECTION_DEFAULTS  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

DAY = 1200
CFG = dict(PLANNER_CONFIG)
SETTINGS = (ROOT / "lua" / "ai-overseer-settings.lua").read_text(encoding="utf-8")
GUI = (ROOT / "lua" / "gui" / "ai-overseer.lua").read_text(encoding="utf-8")


def squad(i, soldiers=5, power=100.0, **kw):
    q = {"id": i, "name": f"Squad {i}", "soldiers": soldiers, "power": power, "armed": soldiers,
         "armored": soldiers, "ranged": 0, "at_home": True, "hunting": None, "sheltering": False}
    q.update(kw)
    return q


def target(i=500, **kw):
    t = {"id": i, "name": f"Beast {i}", "kinds": [], "great_danger": False, "size": 60000,
         "pos": {"x": 10, "y": 10, "z": 50}, "layer": "surface", "region": "surface", "flier": False,
         "fire_breather": False, "ambush": False, "thief": False, "wounded_visitor": False,
         "route": {"ok": True, "length": 40, "blocked_by": "none"}, "near_workers": 0, "seen_ticks": 600,
         "can_reach_dwarves": False}
    t.update(kw)
    return t


def state(targets=(), squads=(), hunts=(), history=None, settings=None, threats=None, **extra):
    s = {"date": {"year": 200, "tick": 50000, "day": 1, "month": "Granite", "season": "spring"},
         "dwarves": {"total": 60, "adults": 50},
         "settings": dict({"traits": {}}, **(settings or {})),
         "others_on_map": {"threats": list(threats or [])},
         "civ_alert": False,
         "hunt": {"targets": list(targets), "squads": list(squads), "hunts": list(hunts)}}
    if history is not None:
        s["hunt"]["history"] = history
    s.update(extra)
    return normalize(s)


def run(s, memory=None, cfg=None, proposals=None):
    props, notes = list(proposals or []), []
    PH._hunt_rule(s, dict(cfg or CFG), props, notes, memory)
    return props, notes


def sends(props):
    return [p for p in props if p.action.get("type") == "hunt_send"]


def recalls(props):
    return [p for p in props if p.action.get("type") == "hunt_recall"]


# --- judging and the party ------------------------------------------------------------------

@test("a thief: the smallest squad that clears the ratio goes, and the reserve stays home")
def _():
    s = state([target(thief=True)], [squad(1, 5, 100), squad(2, 6, 300), squad(3, 4, 50)])
    p, n = run(s)
    [x] = sends(p)
    assert x.rule == "hunt" and x.priority == 2 and x.action == {"type": "hunt_send", "squad_ids": [3],
                                                                   "target_id": 500}, x
    assert "a thief" in x.reason and "stay home" in x.reason, x.reason


@test("the ratio: a party too weak is not sent, and the note says the strengths")
def _():
    need = threat_power(target(great_danger=True, kinds=["Titan"], size=60000 * 400))
    weak = need * 2.5          # above fight_ratio (2) but under hunt_ratio (3)
    s = state([target(great_danger=True, kinds=["Titan"], size=60000 * 400)],
              [squad(1, 10, weak), squad(2, 10, 1.0), squad(3, 10, 1.0)])
    p, n = run(s)
    assert not sends(p) and any("too weak" in x for x in n), n
    s = state([target(great_danger=True, kinds=["Titan"], size=60000 * 400)],
              [squad(1, 10, need * 3.2), squad(2, 10, 1.0), squad(3, 10, 1.0)])
    p, n = run(s)
    assert [x.action["squad_ids"] for x in sends(p)] == [[1]], (p, n)


@test("the reserve: max(3, a third of the soldiers) and one whole squad stay home")
def _():
    # one squad only: it can't leave (no one would guard the fort)
    p, n = run(state([target(thief=True)], [squad(1, 10, 500)]))
    assert not sends(p) and any("at home" in x for x in n), n
    # two squads of 3: sending one leaves 3 (>= 3, >= 0.34*6=3) and one squad: allowed
    p, n = run(state([target(thief=True)], [squad(1, 3, 500), squad(2, 3, 500)]))
    assert len(sends(p)) == 1
    # 2 squads, 10 + 4: sending the 10 leaves 4 (< 0.34 * 14 = 5): the 4 goes instead
    p, n = run(state([target(thief=True)], [squad(1, 10, 500), squad(2, 4, 500)]))
    assert [x.action["squad_ids"] for x in sends(p)] == [[2]], p
    # only the big one is strong enough: refused for the reserve
    p, n = run(state([target(thief=True)], [squad(1, 10, 500), squad(2, 4, 1)]))
    assert not sends(p) and any("fewer than 5 soldiers" in x for x in n), n


@test("a party of two squads when one isn't enough; the reserve still kept")
def _():
    need = threat_power(target(kinds=["ForgottenBeast"], great_danger=True, size=60000 * 100))
    s = state([target(kinds=["ForgottenBeast"], great_danger=True, size=60000 * 100, region="cavern",
                      layer="cavern1")],
              [squad(1, 5, need * 1.6), squad(2, 5, need * 1.6), squad(3, 5, need * 0.5), squad(4, 5, need * 0.5)])
    p, n = run(s)
    [x] = sends(p)
    assert sorted(x.action["squad_ids"]) == [1, 2], x.action
    assert "forgotten beast" in x.reason and "in the caverns" in x.reason, x.reason


@test("a fire breather or a flier: only a party of crossbows, never melee")
def _():
    for kw, word in (({"fire_breather": True}, "breathes fire"), ({"flier": True}, "flies")):
        s = state([target(**kw)], [squad(1, 5, 900), squad(2, 5, 900), squad(3, 5, 900)])
        p, n = run(s)
        assert not sends(p) and any(word in x and "crossbows" in x for x in n), (kw, n)
        s = state([target(**kw)], [squad(1, 5, 900), squad(2, 5, 900, ranged=5), squad(3, 5, 900)])
        p, n = run(s)
        assert [x.action["squad_ids"] for x in sends(p)] == [[2]], (kw, p)


@test("skipped: in reach of the dwarves, called off (military or hunt), behind the seal, no way, already hunted")
def _():
    sq = [squad(1, 5, 900), squad(2, 5, 900)]
    p, n = run(state([target(can_reach_dwarves=True, thief=True)], sq,
                     threats=[]))
    assert not sends(p) and any("military rules' fight" in x for x in n), n
    m = Memory()
    m.called_off = {"500": 1}
    s = state([target(great_danger=True, kinds=["Titan"])], sq, threats=[{"id": 500, "can_reach_dwarves": False}])
    p, n = run(s, m)
    assert not sends(p) and any("called off" in x for x in n), n
    m = Memory()
    m.hunt_seen = {"off": {"500": {"tick": 1, "why": "lost"}}}
    p, n = run(state([target(thief=True)], sq), m)
    assert not sends(p) and any("called off" in x for x in n), n
    p, n = run(state([target(region="cavern", route={"ok": False, "length": None, "blocked_by": "seal"},
                             great_danger=True, kinds=["ForgottenBeast"])], sq))
    assert not sends(p) and any("cavern seal" in x and "lure and cut-off" in x for x in n), n
    p, n = run(state([target(route={"ok": False, "blocked_by": "no_path"})], sq))
    assert not sends(p) and any("no way" in x for x in n), n
    p, n = run(state([target(thief=True)], [squad(1, 5, 900, at_home=False, hunting=500), squad(2, 5, 900),
                                            squad(3, 5, 900)]))
    assert not sends(p), p


@test("priority: the wounded visitor and thieves first, then an ambush near workers, then great dangers; one a cycle")
def _():
    ts = [target(1, great_danger=True, kinds=["Titan"], near_workers=4), target(2, ambush=True, near_workers=2),
          target(3, wounded_visitor=True), target(4, thief=True, route={"ok": True, "length": 90})]
    sq = [squad(i, 5, 5000) for i in range(1, 7)]
    p, n = run(state(ts, sq))
    assert [x.action["target_id"] for x in sends(p)] == [3], p
    assert any("waits; one new hunt a cycle" in x for x in n), n
    p, n = run(state(ts[:2], sq))
    assert [x.action["target_id"] for x in sends(p)] == [2], p
    # great dangers by the workers near, then distance
    g = [target(7, great_danger=True, kinds=["Titan"], near_workers=0, route={"ok": True, "length": 5}),
         target(8, great_danger=True, kinds=["Titan"], near_workers=3, route={"ok": True, "length": 80})]
    p, n = run(state(g, sq))
    assert [x.action["target_id"] for x in sends(p)] == [8], p


@test("one great danger hunted at a time")
def _():
    sq = [squad(1, 5, 5000, at_home=False, hunting=7), squad(2, 5, 5000), squad(3, 5, 5000), squad(4, 5, 5000)]
    hunts = [{"squad_id": 1, "target_id": 7, "since_tick": abs_tick(state()) - 100, "soldiers_at_start": 5,
              "soldiers_now": 5, "wounded": 0, "target_alive": True}]
    ts = [target(7, great_danger=True, kinds=["Titan"]), target(8, great_danger=True, kinds=["ForgottenBeast"])]
    p, n = run(state(ts, sq, hunts))
    assert not sends(p) and any("one great danger is hunted at a time" in x for x in n), n
    assert not recalls(p) and any("4 hour" not in x and "after Beast 7" in x for x in n), n


@test("squads ordered elsewhere this cycle, sheltering or away are not free")
def _():
    sq = [squad(3, 5, 900), squad(2, 5, 900, sheltering=True), squad(4, 5, 900, at_home=False), squad(1, 5, 900),
          squad(5, 5, 900)]
    other = [Proposal("squad_attack", {"type": "squad_orders", "squad_id": 3, "kill": [9]}, "x", 0)]
    p, n = run(state([target(thief=True)], sq), proposals=other)
    assert [x.action["squad_ids"] for x in sends(p)] == [[1]], p


# --- the Rules switch and the sliders ---------------------------------------------------------

@test("Rules: off sends nothing (and calls hunters home); small only thieves, ambushes, wounded visitors; ai beasts too")
def _():
    sq = [squad(i, 5, 5000) for i in range(1, 4)]
    beast = target(1, great_danger=True, kinds=["Titan"])
    p, n = run(state([beast], sq, settings={"hunt": "off"}))
    assert not sends(p) and any("off on the Rules tab" in x for x in n), n
    p, n = run(state([beast], sq, settings={"hunt": "small"}))
    assert not sends(p) and any("'small'" in x for x in n), n
    p, n = run(state([beast, target(2, thief=True)], sq, settings={"hunt": "small"}))
    assert [x.action["target_id"] for x in sends(p)] == [2], p
    p, n = run(state([beast], sq))
    assert [x.action["target_id"] for x in sends(p)] == [1], p
    hunts = [{"squad_id": 1, "target_id": 1, "since_tick": abs_tick(state()), "soldiers_at_start": 5,
              "soldiers_now": 5, "wounded": 0, "target_alive": True}]
    p, n = run(state([beast], [squad(1, 5, 5000, at_home=False, hunting=1)] + sq[1:], hunts,
                     settings={"hunt": "off"}))
    assert [x.action for x in recalls(p)] == [{"type": "hunt_recall", "squad_ids": [1],
                                               "reason": "hunting is off on the Rules tab"}], p
    assert player_rules({"settings": {}})["hunt"] == "ai"
    assert player_rules({"settings": {"hunt": "small"}})["hunt"] == "small"
    assert player_rules({"settings": {"hunt": "all"}})["hunt"] == "ai"


@test("sliders: Caution raises the bar, Militarism lowers it, bounded; great dangers gated at the extremes")
def _():
    base = PH.hunt_ratio(state(), CFG)
    assert base == CFG["hunt_ratio"] == 1.5 * CFG["fight_ratio"]
    hi = PH.hunt_ratio(state(settings={"traits": {"caution": 200, "militarism": -200}}), CFG)
    lo = PH.hunt_ratio(state(settings={"traits": {"caution": -200, "militarism": 200}}), CFG)
    assert lo < base < hi and lo >= CFG["hunt_ratio_min"] and hi <= CFG["hunt_ratio_max"], (lo, base, hi)
    assert lo >= CFG["fight_ratio"]
    sq = [squad(i, 5, 5000) for i in range(1, 4)]
    beast = target(1, great_danger=True, kinds=["Titan"])
    for tr in ({"militarism": -100}, {"caution": 150}):
        p, n = run(state([beast], sq, settings={"traits": tr}))
        assert not sends(p) and any("great dangers are hunted only" in x for x in n), (tr, n)
    p, n = run(state([target(2, thief=True)], sq, settings={"traits": {"militarism": -150}}))
    assert len(sends(p)) == 1


@test("Rules attack policy 'never' sends no hunt")
def _():
    p, n = run(state([target(thief=True)], [squad(1, 5, 900), squad(2, 5, 900)],
                     settings={"attack_policy": "never"}))
    assert not sends(p) and any("sends squads against nothing" in x for x in n), n


# --- never: siege, crisis, alarm ------------------------------------------------------------

@test("never during a siege (and the hunters come home), in a crisis, with the alarm up or a great fight on")
def _():
    sq = [squad(1, 5, 900), squad(2, 5, 900), squad(3, 5, 900)]
    t = target(thief=True)
    p, n = run(state([t], sq, threats=[{"id": 9, "invader": True, "can_reach_dwarves": False}]))
    assert not sends(p) and any("siege" in x for x in n), n
    p, n = run(state([t], sq, threats=[{"id": 9, "can_reach_dwarves": True}]))
    assert not sends(p) and any("can reach the dwarves" in x for x in n), n
    m = Memory()
    m.crisis = {"why": "deaths"}
    p, n = run(state([t], sq), m)
    assert not sends(p) and any("crisis" in x for x in n), n
    p, n = run(state([t], sq, civ_alert=True))
    assert not sends(p) and any("alarm is up" in x for x in n), n
    m = Memory()
    m.ai_alert_raised = True
    p, n = run(state([t], sq), m)
    assert not sends(p) and any("alarm is up" in x for x in n), n
    m = Memory()
    m.fight = {"tick": 1, "keys": ["Titan"], "soldiers": 10}
    p, n = run(state([t], sq), m)
    assert not sends(p) and any("fight with a great danger" in x for x in n), n
    hunts = [{"squad_id": 1, "target_id": 500, "since_tick": abs_tick(state()), "soldiers_at_start": 5,
              "soldiers_now": 5, "wounded": 0, "target_alive": True}]
    p, n = run(state([t], [squad(1, 5, 900, at_home=False, hunting=500)] + sq[1:], hunts,
                     threats=[{"id": 9, "invader": True}]))
    assert [x.action["squad_ids"] for x in recalls(p)] == [[1]] and "come home" in recalls(p)[0].reason, p


# --- the retreat ----------------------------------------------------------------------------

def _hunting(**h):
    now = abs_tick(state())
    row = {"squad_id": 1, "target_id": 500, "since_tick": now - 200, "soldiers_at_start": 6, "soldiers_now": 6,
           "wounded": 0, "target_alive": True}
    row.update(h)
    return row


@test("retreat: a third lost, half wounded, over the days, a fire breather met in melee; each marks the target")
def _():
    sq = [squad(1, 6, 900, at_home=False, hunting=500), squad(2, 5, 900), squad(3, 5, 900)]
    now = abs_tick(state())
    cases = (({"soldiers_now": 4}, {}, "2 of the 6 soldiers who went are lost", "lost"),
             ({"soldiers_now": 5}, {}, None, None),
             ({"wounded": 3}, {}, "3 of the 6 soldiers left are wounded", "lost"),
             ({"since_tick": now - 3 * DAY - 1}, {}, "over 3 days", "time"),
             ({}, {"fire_breather": True}, "breathes fire and the party fights in melee", "ability"),
             ({}, {"flier": True}, "flies and the party has no crossbows", "ability"))
    for h, tk, words, kind in cases:
        m = Memory()
        p, n = run(state([target(thief=True, **tk)], sq, [_hunting(**h)]), m)
        r = recalls(p)
        if words is None:
            assert not r and any("5 of 6 soldiers" in x for x in n), (h, n)
            assert m.hunt_seen.get("off") is None, m.hunt_seen
            continue
        assert len(r) == 1 and r[0].rule == "squad_recall" and r[0].guard and r[0].priority == 0, (h, p)
        assert r[0].action["squad_ids"] == [1] and words in r[0].action["reason"], (h, r[0].action)
        assert m.hunt_seen["off"]["500"]["why"] == kind, (h, m.hunt_seen)
    # a party of crossbows at a fire breather: kept on
    sq2 = [squad(1, 6, 900, at_home=False, hunting=500, ranged=6), squad(2, 5, 900), squad(3, 5, 900)]
    p, n = run(state([target(thief=True, fire_breather=True)], sq2, [_hunting()]))
    assert not recalls(p), p


@test("retreat: a party of two squads judged together; a dead target needs no recall")
def _():
    sq = [squad(1, 3, 900, at_home=False, hunting=500), squad(2, 3, 900, at_home=False, hunting=500),
          squad(3, 5, 900), squad(4, 5, 900)]
    hs = [_hunting(squad_id=1, soldiers_at_start=3, soldiers_now=1), _hunting(squad_id=2, soldiers_at_start=3,
                                                                              soldiers_now=3)]
    p, n = run(state([target(thief=True)], sq, hs))
    assert [x.action["squad_ids"] for x in recalls(p)] == [[1, 2]], p          # 2 of 6 lost
    hs = [_hunting(target_alive=False, soldiers_now=0)]
    p, n = run(state([target(thief=True)], sq, hs))
    assert not recalls(p) and any("dead or gone" in x for x in n), n


@test("a timed-out target rests hunt_rest_days, then may be hunted again; a lost one stays off")
def _():
    s = state([target(thief=True)], [squad(1, 5, 900), squad(2, 5, 900), squad(3, 5, 900)])
    now = abs_tick(s)
    m = Memory()
    m.hunt_seen = {"off": {"500": {"tick": now - DAY, "why": "time"}}}
    p, n = run(s, m)
    assert not sends(p) and any("rests a few days" in x for x in n), n
    m.hunt_seen = {"off": {"500": {"tick": now - CFG["hunt_rest_days"] * DAY, "why": "time"}}}
    p, n = run(s, m)
    assert len(sends(p)) == 1
    m.hunt_seen = {"off": {"500": {"tick": now - 100 * DAY, "why": "lost"}}}
    p, n = run(s, m)
    assert not sends(p)


# --- learning ---------------------------------------------------------------------------------

@test("learning: a won hunt x0.9, a lost (recalled with losses) x1.5 capped, gone nothing; each entry once")
def _():
    hist = [{"kinds": ["Titan"], "outcome": "won", "lost": 0, "of": 6, "tick": 100},
            {"kinds": ["ForgottenBeast"], "outcome": "recalled", "lost": 2, "of": 6, "tick": 200},
            {"kinds": ["Megabeast"], "outcome": "gone", "lost": 0, "of": 6, "tick": 300},
            {"kinds": ["Demon"], "outcome": "recalled", "lost": 0, "of": 6, "tick": 400}]
    m = Memory()
    m.fight_factor = {"ForgottenBeast": 3.5}
    s = state([], [], history=hist)
    notes = PH.note_hunt_cycle(s, m, CFG)
    assert m.fight_factor == {"Titan": 0.9, "ForgottenBeast": 4.0}, m.fight_factor
    assert len(notes) == 2 and all("hunt learned" in x for x in notes), notes
    assert PH.note_hunt_cycle(s, m, CFG) == [] and m.fight_factor == {"Titan": 0.9, "ForgottenBeast": 4.0}
    # a bloody win teaches like a loss; the old learned keys kept, the new one added
    hist2 = hist + [{"kinds": ["Titan"], "outcome": "won", "lost": 3, "of": 6, "tick": 500}]
    PH.note_hunt_cycle(state([], [], history=hist2), m, CFG)
    assert m.fight_factor["Titan"] == 1.35, m.fight_factor
    assert len(m.hunt_seen["learned"]) == 5
    # a factor already above 4 (a called-off fight) isn't raised further by a hunt nor cut back
    m.fight_factor["Titan"] = 10.0
    PH.note_hunt_cycle(state([], [], history=[{"kinds": ["Titan"], "outcome": "recalled", "lost": 4, "of": 6,
                                               "tick": 600}]), m, CFG)
    assert m.fight_factor["Titan"] == 10.0


@test("learning (H1's history): caged counts as won, dropped and gone teach nothing, soldiers_lost and end_tick read")
def _():
    hist = [{"kinds": ["Titan"], "outcome": "caged", "soldiers_lost": 0, "of": 6, "end_tick": 100,
             "target_dead": False, "reason": "caged"},
            {"kinds": ["Megabeast"], "outcome": "dropped", "soldiers_lost": 0, "of": 6, "end_tick": 200},
            {"kinds": ["ForgottenBeast"], "outcome": "recalled", "soldiers_lost": 2, "of": 6, "end_tick": 300}]
    m = Memory()
    PH.note_hunt_cycle(state([], [], history=hist), m, CFG)
    assert m.fight_factor == {"Titan": 0.9, "ForgottenBeast": 1.5}, m.fight_factor


@test("a target the bridge says may not be killed (kill_ok false) is skipped; an invader target means a siege")
def _():
    sq = [squad(1, 5, 900), squad(2, 5, 900), squad(3, 5, 900)]
    p, n = run(state([target(thief=True, kill_ok=False, why="a merchant")], sq))
    assert not sends(p) and any("kill_ok" in x and "a merchant" in x for x in n), n
    p, n = run(state([target(thief=True), target(9, invader=True)], sq))
    assert not sends(p) and any("siege" in x for x in n), n
    assert PH._party_power(target(), [squad(1, power=10), squad(2, power={"power": 5})]) == 15


@test("learning feeds the judging: a kind learned stronger needs a stronger party")
def _():
    t = target(great_danger=True, kinds=["Titan"], size=60000 * 100)
    need = threat_power(t)
    sq = [squad(1, 5, need * 3.2), squad(2, 5, 1), squad(3, 5, 1)]
    p, _ = run(state([t], sq), Memory())
    assert len(sends(p)) == 1
    m = Memory()
    m.fight_factor = {"Titan": 1.5}
    p, n = run(state([t], sq), m)
    assert not sends(p) and any("too weak" in x for x in n), n


@test("note_hunt_cycle forgets the off marks of targets no longer on the map")
def _():
    m = Memory()
    m.hunt_seen = {"off": {"500": {"tick": 1, "why": "lost"}, "77": {"tick": 1, "why": "lost"}}}
    PH.note_hunt_cycle(state([target(500)], []), m, CFG)
    assert list(m.hunt_seen["off"]) == ["500"], m.hunt_seen


# --- wiring -------------------------------------------------------------------------------------

def fixture(**hunt):
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    base["others_on_map"]["threats"] = []
    base["others_on_map"]["threats_that_can_reach_dwarves"] = 0
    base["civ_alert"] = False
    base["hunt"] = hunt
    return base


@test("plan() carries the rule; note_cycle learns; the digest default; without the section nothing is said")
def _():
    st = fixture(targets=[target(thief=True)], squads=[squad(1, 5, 900), squad(2, 5, 900), squad(3, 5, 900)],
                 hunts=[], history=[{"kinds": ["Titan"], "outcome": "won", "lost": 0, "of": 5, "tick": 9}])
    m = Memory()
    note_cycle(st, m)
    assert m.fight_factor.get("Titan") == 0.9, m.fight_factor
    props, notes = plan(st, m)
    assert [p.action for p in props if p.rule == "hunt"] == [{"type": "hunt_send", "squad_ids": [1],
                                                              "target_id": 500}], [p.rule for p in props]
    assert SECTION_DEFAULTS["hunt"] == {"targets": [], "squads": [], "hunts": []}
    base = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))
    assert "hunt" not in base
    p, n = run(normalize(base))
    assert p == [] and n == []
    p, n = run(normalize(dict(base, hunt={"error": "boom"})))
    assert p == [] and n == []
    assert Memory.from_dict(Memory(hunt_seen={"off": {"1": {"tick": 2, "why": "lost"}}}).to_dict()).hunt_seen


@test("config: the hunt numbers are in PLANNER_CONFIG")
def _():
    for k in ("hunt_ratio", "hunt_slider_weight", "hunt_ratio_min", "hunt_ratio_max", "hunt_reserve_min",
              "hunt_reserve_share", "hunt_max_days", "hunt_rest_days", "hunt_great_militarism_min",
              "hunt_great_caution_max", "hunt_learned_keep", "hunt_cooldown_ticks"):
        assert k in PLANNER_CONFIG, k
    assert PLANNER_CONFIG["hunt_reserve_min"] == 3 and PLANNER_CONFIG["hunt_max_days"] == 3


@test("settings and window: hunt off | small | ai, default ai; sanitize, for_ai, RULE_CHOICES; a free row")
def _():
    assert "HUNT_CHOICES = {'off', 'small', 'ai'}" in SETTINGS
    assert code_has(SETTINGS, "hunt = HUNT_CHOICES,")
    assert code_has(SETTINGS, "hunt = 'ai',")
    assert code_has(SETTINGS, "out.hunt = one_of(s.hunt, HUNT_CHOICES, d.hunt)")
    assert code_has(SETTINGS, "hunt = s.hunt,")
    assert code_has(GUI, "view_id = 'hunt'") and code_has(GUI, "p:set_field('hunt', v)")
    mref = GUI[GUI.index("function MilitaryPage:refresh()"):]
    assert "self.subviews.hunt:setOption(" in mref
    mil = GUI[GUI.index("function MilitaryPage:init()"):GUI.index("function RulesPage:refresh")]
    frames = [(int(t), int(l), int(w)) for t, l, w in
              re.findall(r"frame = \{t = t \+ (\d+), l = (\d+), w = (\d+)\}", mil)]
    me = (19, 64, 50)
    assert me in frames
    for t, l, w in frames:
        if t == 19 and (t, l, w) != me:
            assert l + w <= 64, (t, l, w)
    assert 64 + 50 <= 118
    from strategist import rules_line
    assert "hunt" not in rules_line(player_rules({"settings": {}}))
    if LuaRuntime is not None:
        lua = LuaRuntime(unpack_returned_tuples=True)
        chk = lua.eval("function(src, n) local f, e = load(src, n, 't', {}); return f ~= nil, e end")
        for name, src in (("settings", SETTINGS), ("gui", GUI)):
            ok = chk(src, name)
            assert ok[0], (name, ok)


finish()
