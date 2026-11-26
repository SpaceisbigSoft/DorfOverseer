"""(item8, the player, 26 Nov: "Trim to its slider") A fort far above its
Militarism slider trims back gradually (brain/planner_squad_trim.py,
brain/planner_defence_floor.py quiet_cap_share).

The live case: E ("Deep mine", Militarism 0: the slider asks 10%), 26 Nov:
39 soldiers in 4 squads of 100 citizens (95 adults), 14 keen civilians,
Goblin-haunted, a forgotten beast (Thaci, 276 strength) gone; the journal
said "38 soldiers, the fort wants 39 (defence floor)": the floor's third of
the adults (31) with Goblin-haunted's quarter put on top (39), and the trim
held while 5+ civilians badly wanted to train.

    python tests/test_item8_trim_slider.py
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
from planner import Memory, PLANNER_CONFIG, plan, record  # noqa: E402
from planner_military import soldiers_wanted  # noqa: E402
from planner_core import recently_home  # noqa: E402
import planner_defence_floor as DF  # noqa: E402
from planner_squad_trim import trim_plan  # noqa: E402
from digest import normalize  # noqa: E402

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def squad(sid, members, power):
    return {"id": sid, "name": f"Squad {sid}", "members": members, "size": 10, "leader": True,
            "routine": "Staggered training", "orders": 0, "ai_orders": 0, "power": {"power": power, "armed": members}}


E_SQUADS = [squad(185, 10, 55.7), squad(207, 10, 22.7), squad(213, 10, 76.3), squad(218, 9, 85.4)]


def beast(i=16710, reach=True):
    return {"id": i, "name": 'Thaci "Deepdrink", Forgotten Beast', "great_danger": True,
            "kinds": ["ForgottenBeast"], "size": 60000 * 20, "layer": "cavern_1", "can_reach_dwarves": reach}


def fort_e(squads=None, threats=None, keen=14, total=100, adults=95) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "summer"
    s["settings"]["traits"] = {}                       # the Deep mine: no militarism key -> 0
    s["dwarves"].update(total=total, adults=adults, idle_adults=0)
    s["needs"] = {"needs": {}, "stressed": [], "keen_civilians": keen, "keen_draftable": 4}
    s["others_on_map"]["threats"] = threats or []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats or [] if t.get("can_reach_dwarves"))
    squads = E_SQUADS if squads is None else squads
    s["military"]["squads"] = copy.deepcopy(squads)
    s["military"]["soldiers"] = sum(q.get("members") or 0 for q in squads)
    return normalize(s)


def e_memory(s, quiet_days=120) -> Memory:
    m = Memory()
    now = DF.abs_tick(s)
    m.defence_floor = {"peak": {"power": 276.4, "tick": now - quiet_days * DAY, "why": "Thaci on the map"},
                       "present_tick": now - quiet_days * DAY}
    m.culture = {"quirks": {"goblin_haunted": {"why": "at war with 1 goblin civilisation(s)", "year": 251}},
                 "sieges": 0}
    return m


def trims(p):
    return [x for x in p if x.rule == "squad_trim"]


@test("E: the floor's cap eases from the third to the slider's 10% once the beast is gone")
def _():
    s = fort_e()
    f0 = DF.defence_floor(s, e_memory(s, quiet_days=0), CFG, 100)
    assert f0["cap"] == int(95 * 0.33) == 31 and f0["soldiers"] == 31, f0
    f = DF.defence_floor(s, e_memory(s, quiet_days=120), CFG, 100)
    assert 0.10 < f["cap_share"] < 0.14 and f["soldiers"] == f["cap"] == 12, f
    f = DF.defence_floor(s, e_memory(s, quiet_days=400), CFG, 100)
    assert abs(f["cap_share"] - 0.10) < 1e-9 and f["soldiers"] == 9, f        # int(95 x .10)


@test("E: Goblin-haunted's quarter goes on the slider's number, never on the floor (31 stays 31, not 39)")
def _():
    s = fort_e()
    p, notes = plan(s, e_memory(s, quiet_days=0))
    fills = [x for x in p if x.rule == "squad_fill"]
    assert not fills, [x.reason for x in fills]                # 39 soldiers, no more drafted
    # long quiet: the slider's 10 of 100 and the quarter: 12 (round(12.5))
    p, notes = plan(s, e_memory(s, quiet_days=400))
    t = trims(p)
    assert t and "the fort wants 12 " in t[0].reason, [x.reason for x in p if "soldiers" in x.reason]


@test("E's numbers (39 soldiers, 14 keen civilians, the beast gone 120 days): a trim of 2, the reason said")
def _():
    s = fort_e()
    p, notes = plan(s, e_memory(s))
    t = trims(p)
    assert t and t[0].action == {"type": "squad_trim", "count": CFG["max_trim_per_cycle"]}, \
        [x.reason for x in p if "soldier" in x.reason]
    r = t[0].reason
    assert r.startswith("39 soldiers, the fort wants ") and "Militarism +0" in r, r
    assert "unhappiest and least skilled first" in r and "2 of at most 10 this season" in r, r


@test("a fort under its target, or within the margin: no trim")
def _():
    s = fort_e(squads=[squad(1, 8, 40.0)])
    p, _n = plan(s, e_memory(s, quiet_days=400))
    assert not trims(p)
    s = fort_e(squads=[squad(1, 10, 50.0), squad(2, 5, 25.0)])      # 15 for 12: within the margin of 3
    p, _n = plan(s, e_memory(s, quiet_days=400))
    assert not trims(p), [x.reason for x in trims(p)]


@test("an active threat on the map: no trim (a great danger that can reach the dwarves, or one the floor counts)")
def _():
    s = fort_e(threats=[beast()])
    p, notes = plan(s, e_memory(s))
    assert not trims(p), [x.reason for x in trims(p)]
    out = trim_plan(s, e_memory(s), CFG, 39, 13, {"present": 50.0, "real": 50.0}, False, False)
    assert not out.get("count") and "threat is on the map" in out["note"], out
    # an invader that can't reach them yet is real too
    gob = {"id": 9, "name": "goblin", "invader": True, "can_reach_dwarves": False, "size": 60000, "kinds": []}
    s = fort_e(threats=[gob])
    assert DF.defence_floor(s, e_memory(s), CFG, 100)["real"] > 0
    assert not trims(plan(s, e_memory(s))[0])


@test("a beast sealed in the caverns (can't reach the dwarves) is no real threat: no hold on the trim, the cap eases")
def _():
    s = fort_e(threats=[beast(reach=False)])
    f = DF.defence_floor(s, e_memory(s), CFG, 100)
    assert f["present"] > 0 and f["real"] == 0 and f["cap"] == 12, f
    assert trims(plan(s, e_memory(s))[0])
    m = Memory()
    DF.note_defence_floor(s, m, CFG)
    assert m.defence_floor["present_tick"] is None and m.defence_floor["peak"]["power"] > 0, m.defence_floor
    assert DF.quiet_cap_share(s, m, CFG, 0.33) == (0.10, None)       # no real threat yet: the slider's share


@test("never mid-fight, nor with a dwarf berserk")
def _():
    s = fort_e()
    m = e_memory(s)
    m.fight = {"tick": DF.abs_tick(s) - 2 * DAY}
    out = trim_plan(s, m, CFG, 39, 13, {}, False, False)
    assert not out.get("count") and "fight" in out["note"], out
    out = trim_plan(s, e_memory(s), CFG, 39, 13, {}, False, True)
    assert not out.get("count") and "berserk" in out["note"], out


@test("at most a squad's worth a season and 3 a week; once begun it goes on down to the wanted number")
def _():
    s = fort_e()
    now = DF.abs_tick(s)
    m = e_memory(s)
    m.trimmed = {str(100 + i): now - (10 + i) * DAY for i in range(10)}          # 10 this season
    out = trim_plan(s, m, CFG, 29, 13, {}, False, False)
    assert not out.get("count") and "this season already" in out["note"], out
    m.trimmed = {str(100 + i): now - DAY for i in range(3)}                       # 3 this week
    out = trim_plan(s, m, CFG, 36, 13, {}, False, False)
    assert not out.get("count") and "this week" in out["note"], out
    m.trimmed = {str(100 + i): now - 9 * DAY for i in range(9)}                   # 9: one place left
    assert trim_plan(s, m, CFG, 30, 13, {}, False, False)["count"] == 1
    # within the margin: nothing unless a trim is under way, then down to the wanted number exactly
    assert trim_plan(s, Memory(), CFG, 15, 13, {}, False, False) == {}
    m.trimmed = {"100": now - 20 * DAY}
    assert trim_plan(s, m, CFG, 15, 13, {}, False, False)["count"] == 2
    assert trim_plan(s, m, CFG, 14, 13, {}, False, False)["count"] == 1
    assert trim_plan(s, m, CFG, 13, 13, {}, False, False) == {}


@test("never below the guard of 3 (or the floor): the wanted number is the lowest the trim goes")
def _():
    s = fort_e(total=30, adults=30, keen=0, squads=[squad(1, 7, 28.0)])
    m = Memory()
    m.trimmed = {"1": DF.abs_tick(s) - 3 * DAY}                    # a trim under way
    m.culture = {}
    assert soldiers_wanted(s, 30, CFG, memory=m) == 3               # 10% of 30, the guard
    p, _n = plan(s, m)
    t = trims(p)
    assert t and t[0].action["count"] == 2, [x.reason for x in p if "soldier" in x.reason]
    out = trim_plan(s, m, CFG, 4, 3, {}, False, False)
    assert out["count"] == 1
    assert trim_plan(s, m, CFG, 3, 3, {}, False, False) == {}


@test("the keen hold only while the keen lift is held (a crisis)")
def _():
    s = fort_e()
    m = e_memory(s)
    m.keen_lift = {"n": 7, "tick": DF.abs_tick(s) - 5 * DAY}
    assert trim_plan(s, m, CFG, 39, 13, {}, False, False) == {}
    m.keen_lift = {}
    assert trim_plan(s, m, CFG, 39, 13, {}, False, False)["count"] == 2


@test("record: those the trim sent home are remembered (the season's count) and the fill passes them over")
def _():
    s = fort_e()
    m = e_memory(s)
    p, _n = plan(s, m)
    t = trims(p)[0]
    record([(t, {"ok": True, "removed": [{"unit_id": 501, "squad_id": 185, "name": "a"},
                                         {"unit_id": 502, "squad_id": 207, "name": "b"}]})], s, m)
    assert set(m.trimmed) == {"501", "502"}, m.trimmed
    home = recently_home(s, m)
    assert 501 in home and 502 in home, home
    out = trim_plan(s, m, CFG, 37, 13, {}, False, False)
    assert out["count"] == 1 and "3 of at most 10" in out["why"], out       # 2 this week already: one more


@test("the floor remembers when a threat was last on the map")
def _():
    s = fort_e(threats=[beast()])
    m = Memory()
    DF.note_defence_floor(s, m, CFG)
    assert m.defence_floor.get("present_tick") == DF.abs_tick(s), m.defence_floor


if __name__ == "__main__":
    finish()
