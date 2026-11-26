"""(0.105.54, the player: "fight back") The defence floor by threat
(brain/planner_defence_floor.py): soldiers enough for an even fight against
the biggest threat the fort has faced or sees, whatever the Militarism; the
slider adds above it; it rises at once and fades over seasons; a note says
it; peaceful forts' own squads shoot; the bridge's fill never drafts the
last farmer or brewer.

    python tests/test_k54_defence_floor.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from harness import test, finish, need_lua  # noqa: E402
from lua_modules_util import module_src, split_src  # noqa: E402

sys.path.insert(0, str(ROOT / "brain"))
from planner import Memory, PLANNER_CONFIG, plan, note_cycle  # noqa: E402
from planner_military import soldiers_wanted, _ranged_squad_rule  # noqa: E402
import planner_defence_floor as DF  # noqa: E402
from digest import normalize  # noqa: E402

try:
    from lupa.lua53 import LuaRuntime
except ImportError:
    LuaRuntime = None

CFG = dict(PLANNER_CONFIG)
DAY = 1200
BASE = json.loads((ROOT / "tests" / "fixtures" / "test_fort.json").read_text(encoding="utf-8"))


def fort(mil=-100, adults=40, threats=None, squads=None) -> dict:
    s = copy.deepcopy(BASE)
    s["date"]["season"] = "spring"
    s["settings"]["traits"] = {"militarism": mil}
    s["dwarves"].update(total=adults, adults=adults, idle_adults=0)
    s["needs"] = {"needs": {}, "stressed": []}
    s["others_on_map"]["threats"] = threats or []
    s["others_on_map"]["threats_that_can_reach_dwarves"] = sum(1 for t in threats or [] if t.get("can_reach_dwarves"))
    if squads is not None:
        s["military"]["squads"] = squads
        s["military"]["soldiers"] = sum(q.get("members") or 0 for q in squads)
    return normalize(s)


def goblin(i, reach=False):
    return {"id": 9000 + i, "name": "goblin", "invader": True, "size": 60000, "can_reach_dwarves": reach,
            "pos": {"x": 1, "y": 1, "z": 1}}


def beast(i=7000, size=60000 * 20, **kw):
    t = {"id": i, "name": 'Nol "The Abyssal", Forgotten Beast', "great_danger": True,
         "kinds": ["ForgottenBeast"], "size": size, "layer": "cavern_1"}
    t.update(kw)
    return t


def squad(sid, members, power):
    return {"id": sid, "name": f"Squad {sid}", "members": members, "size": 10, "leader": True,
            "routine": "Staggered training", "orders": 0, "ai_orders": 0, "power": {"power": power, "armed": members}}


@test("a quiet fort with no history: no floor, the guard (3) at Militarism -100 as before")
def _():
    s = fort()
    f = DF.defence_floor(s, Memory(), CFG, 40)
    assert f["soldiers"] == 0 and f["threat"] == 0, f
    assert soldiers_wanted(s, 40, CFG, memory=Memory()) == 3


@test("history: sieges on record raise the floor above the slider (capped at a third at Militarism 0; "
      "0.105.97: 12% at -50 and below)")
def _():
    # (0.105.97) at Militarism -100 the cap with no threat here is 12%: int(40 x .12) = 4
    # (item8) the cap at its height only just after a threat was on the map (present_tick now)
    m0 = Memory()
    m0.culture = {"sieges": 2}
    m0.defence_floor = {"present_tick": DF.abs_tick(fort())}
    assert DF.defence_floor(fort(), m0, CFG, 40)["soldiers"] == 4
    s = fort(mil=0)
    m = Memory()
    m.culture = {"sieges": 2}
    m.defence_floor = {"present_tick": DF.abs_tick(s)}
    f = DF.defence_floor(s, m, CFG, 40)
    # 40 x 1.25 = 50 at 4 a soldier (none known) -> 13; the cap int(40 x 0.33) = 13
    assert f["soldiers"] == 13 and "2 siege(s) on record" in f["why"], f
    assert soldiers_wanted(s, 40, CFG, memory=m) == 13
    # the world report's siege counts count too (an older memory)
    s2 = copy.deepcopy(s)
    s2["world"] = {"sieges": [{"id": 5, "n": 1}]}
    m2 = Memory()
    m2.defence_floor = {"present_tick": DF.abs_tick(s2)}
    assert DF.defence_floor(s2, m2, CFG, 40)["soldiers"] == 10      # 40 / 4
    # (item8) no threat on the map since none can say when: the cap is the slider's share (10% at 0, 5% at -100)
    m.defence_floor = {}
    assert DF.defence_floor(s, m, CFG, 40)["soldiers"] == 4
    m0.defence_floor = {}
    assert DF.defence_floor(fort(), m0, CFG, 40)["soldiers"] == 2
    assert soldiers_wanted(fort(), 40, CFG, memory=m0) == 3        # the guard stands


@test("a siege on the map: the invaders summed, the floor at once; capped at a third of the adults")
def _():
    s = fort(threats=[goblin(i) for i in range(6)])
    f = DF.defence_floor(s, Memory(), CFG, 40)
    assert f["present"] == 60.0 and f["soldiers"] == 13 and f["wanted"] == 15, f
    assert "6 invader(s) on the map" in f["why"]


@test("the fort's own soldiers' power: veterans need fewer; a training squad isn't counted")
def _():
    sq = [squad(1, 5, 50.0), dict(squad(2, 5, 1.0), training_squad=True)]
    s = fort(threats=[goblin(i) for i in range(6)], squads=sq)
    f = DF.defence_floor(s, Memory(), CFG, 40)
    assert f["per_soldier"] == 10.0 and f["soldiers"] == 6, f


@test("a forgotten beast: its power by threat_power, times what the fort learned of its kind (capped)")
def _():
    s = fort(threats=[beast()])
    m = Memory()
    p0 = DF.present_threat(s, m, CFG)[0]
    m.fight_factor = {"ForgottenBeast": 3.0}
    assert abs(DF.present_threat(s, m, CFG)[0] - 3 * p0) < 1e-6
    m.fight_factor = {"ForgottenBeast": 50.0}
    assert abs(DF.present_threat(s, m, CFG)[0] - CFG["floor_learned_max"] * p0) < 1e-6
    # wildlife isn't a threat to the floor
    s = fort(threats=[{"id": 1, "name": "falcon", "animal": True, "size": 129, "agitated": True}])
    assert DF.present_threat(s, Memory(), CFG)[0] == 0


@test("Militarism adds above: a militant fort keeps its slider's larger number")
def _():
    s = fort(mil=100, threats=[goblin(0)])
    f = DF.defence_floor(s, Memory(), CFG, 40)
    assert f["soldiers"] == 3, f                               # 10 / 4
    assert soldiers_wanted(s, 40, CFG, memory=Memory()) == round(40 * 0.4)


@test("rises at once, fades over seasons: note_cycle remembers the peak; plan() writes no memory")
def _():
    m = Memory()
    s = fort(threats=[goblin(i) for i in range(4)])
    t0 = s["date"].get("tick", 0)
    note_cycle(copy.deepcopy(s), m)
    assert m.defence_floor["peak"]["power"] == 40.0, m.defence_floor
    gone = fort(mil=0)                                          # (0.105.97) the cap a third at 0
    gone["date"]["tick"] = t0 + DAY                             # (same year)
    f = DF.defence_floor(normalize(gone), m, CFG, 40)
    assert f["soldiers"] == 10 and "remembered" in f["why"], f
    later = copy.deepcopy(gone)
    later["date"]["tick"] = t0 + 168 * DAY
    later["date"]["year"] = gone["date"].get("year", 0)
    fl = DF._decayed(m.defence_floor["peak"], DF.abs_tick(normalize(later)), CFG)
    assert 19 <= fl <= 21, fl                                   # halved after two seasons
    assert DF._decayed(m.defence_floor["peak"], DF.abs_tick(gone) + 600 * DAY, CFG) == 10.0   # a quarter kept
    # (0.105.97) ...for two years, then let go
    assert DF._decayed(m.defence_floor["peak"], DF.abs_tick(gone) + 2000 * DAY, CFG) == 0.0
    # a smaller threat later doesn't lower the remembered peak
    note_cycle(fort(threats=[goblin(0)]), m)
    assert m.defence_floor["peak"]["power"] == 40.0
    before = json.dumps(m.defence_floor, sort_keys=True)
    plan(fort(threats=[goblin(i) for i in range(9)]), m)
    assert json.dumps(m.defence_floor, sort_keys=True) == before


@test("plan(): the floor drafts with its reason; the note says the floor, why and the soldiers")
def _():
    s = fort(threats=[goblin(i) for i in range(6)], squads=[squad(1, 3, 12.0)])
    p, notes = plan(s, Memory())
    line = [n for n in notes if n.startswith("Defence floor")]
    assert line and "6 invader(s)" in line[0] and "soldiers 3" in line[0], notes
    fills = [x for x in p if x.rule in ("squad_fill", "squad_make")]
    assert fills and "(defence floor)" in fills[0].reason, [x.reason for x in fills]
    # no trim below the floor
    assert not [x for x in p if x.rule == "squad_trim"]


@test("never past the civilian cap (enough left to work)")
def _():
    s = fort(mil=0, adults=20)                                  # (0.105.97) the cap a third at Militarism 0
    m = Memory()
    m.culture = {"sieges": 5}
    m.defence_floor = {"present_tick": DF.abs_tick(s)}          # (item8) just after the threat: the cap at its height
    # floor wants 80/4 = 20, capped at int(20 x .33) = 6; the civilian cap 20 - 12 = 8
    assert soldiers_wanted(s, 20, CFG, memory=m) == 6
    s = fort(mil=0, adults=16)
    assert soldiers_wanted(s, 16, CFG, memory=m) == 4          # 16 - 12 civilians


def _mil_rule(peaceful, squads, made):
    props = []
    s = fort(mil=-50 if peaceful else 0)
    s["military"].setdefault("gear", {})["ranged_armed"] = 0
    _ranged_squad_rule(s, s["military"]["gear"], squads, ["Crossbow uniform", "Metal"], CFG, props, made, peaceful)
    return props


@test("a peaceful fort: every squad the AI made becomes a crossbow squad; the player's squads keep theirs")
def _():
    sq = [dict(squad(1, 5, 10), ai_uniform="Metal"), dict(squad(2, 5, 10), ai_uniform="Leather"),
          dict(squad(3, 5, 10), ai_uniform="Crossbow (leather)")]
    p = _mil_rule(True, sq, [2, 3])
    assert [(x.action["squad_id"], x.action.get("ranged")) for x in p if x.rule == "uniform"] == [(2, True)], \
        [x.action for x in p]
    p = _mil_rule(True, sq, [3])            # 1 is the player's: not touched, nothing else to convert
    assert not [x for x in p if x.rule == "uniform"], [x.action for x in p]
    # two crossbow squads: a peaceful fort keeps both
    sq2 = [dict(squad(1, 5, 10), ai_uniform="Crossbow (metal)"), dict(squad(2, 5, 10), ai_uniform="Crossbow")]
    assert not [x for x in _mil_rule(True, sq2, [1, 2]) if x.rule == "uniform"]
    assert [x for x in _mil_rule(False, sq2, [1, 2]) if x.rule == "uniform"]


@test("peaceful_ranged: Militarism below 0 and bolts can be made (a bowyer's, wood or a forge)")
def _():
    s = fort(mil=-20)
    s["stocks"]["wood"] = 5
    assert DF.peaceful_ranged(s, s["settings"]["traits"])
    assert not DF.peaceful_ranged(s, {"militarism": 0})
    s["stocks"]["wood"] = 0
    s["buildings"] = {"workshops": {}, "furnaces": {}}
    s["military"].setdefault("gear", {})["forges"] = 0
    assert not DF.peaceful_ranged(s, {"militarism": -20})


MIL_FAKE = r"""
local src = ...
local env = setmetatable({}, {__index = _G})
env.df = {global = {plotinfo = {group_id = 1}}, need_type = {[3] = 'BeWithFriends'},
          unit_labor = {PLANT = 20, BREWER = 30}}
env.dfhack = {units = {isAdult = function(u) return true end}}
env.require = function() return {} end
assert(load(src, 'm', 't', env))()
return env
"""


@test("bridge: last_hands counts the farmers and brewers outside the squads; fill keeps the last")
def _():
    src = split_src("ai-military.lua")   # (r8) the hub and its parts
    assert "pcall(last_hands)" in src and "kept as the last farmer or brewer" in src
    need_lua()
    lua = LuaRuntime(unpack_returned_tuples=True)
    env = lua.execute(MIL_FAKE, module_src("ai-military.lua"))
    units = lua.eval("""function(spec)
        local out = {}
        for i, row in ipairs(spec) do
            out[i] = {id = row[1], military = {squad_id = row[2]}, status = {labors = {[20] = row[3], [30] = row[4]}}}
        end
        return out end""")
    us = units(lua.table_from([lua.table_from([1, -1, True, False]), lua.table_from([2, -1, True, True]),
                               lua.table_from([3, 5, True, True]), lua.table_from([4, -1, False, False])]))
    env.dfhack.units.getCitizens = lua.eval("function(us) return function() return us end end")(us)
    h = env.last_hands()
    assert h.n["PLANT"] == 2 and h.n["BREWER"] == 1, (h.n["PLANT"], h.n["BREWER"])
    assert list(h.of[2].values()) == ["PLANT", "BREWER"] and h.of[3] is None and h.of[4] is None


finish()
